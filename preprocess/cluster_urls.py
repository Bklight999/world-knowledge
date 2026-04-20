"""
Standalone URL prefix clustering tool.

Usage:
    python cluster_urls.py game/                       # process all {domain}.txt in game/
    python cluster_urls.py game/ conference/            # multiple directories
    python cluster_urls.py game/ --max-group 20        # custom max group size
    python cluster_urls.py game/ --max-clusters 50     # limit total clusters to 50
"""

import argparse
import glob
import os
import re
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


MAX_GROUP_SIZE = 15
MAX_CLUSTERS = 30
MIN_CLUSTER_SIZE = 3
MAX_SHOW_PER_CLUSTER = 50
SEPARATOR = "==" * 30


def prefix_cluster(urls, max_group_size=MAX_GROUP_SIZE):
    """Adaptive-depth prefix grouping: recursively split until each group <= max_group_size."""
    if not urls:
        return {}

    parsed_list = []
    for url in urls:
        p = urlparse(url)
        path = p.path.strip("/")
        segs = tuple(path.split("/")) if path else ()
        parsed_list.append((url, segs))

    if not parsed_list:
        return {}
        
    base_p = urlparse(urls[0])
    base = base_p.scheme + "://" + base_p.netloc
    max_d = max((len(s) for _, s in parsed_list), default=0)

    def _split(entries, depth):
        if len(entries) <= max_group_size or depth > max_d:
            pfx_segs = entries[0][1][:depth] if entries else ()
            pfx = base + "/" + "/".join(pfx_segs) if pfx_segs else base
            return {pfx: [u for u, _ in entries]}
        subs = {}
        for u, segs in entries:
            k = segs[: depth + 1] if len(segs) > depth else segs
            subs.setdefault(k, []).append((u, segs))
        if len(subs) > max_group_size:
            pfx_segs = entries[0][1][:depth] if entries else ()
            pfx = base + "/" + "/".join(pfx_segs) if pfx_segs else base
            return {pfx: [u for u, _ in entries]}
        out = {}
        for v in subs.values():
            out.update(_split(v, depth + 1))
        return out

    init = {}
    for u, segs in parsed_list:
        k = segs[:1] if segs else ()
        init.setdefault(k, []).append((u, segs))

    groups = {}
    for v in init.values():
        groups.update(_split(v, 1))
    return groups


def merge_clusters(clusters, max_clusters=MAX_CLUSTERS, min_size=MIN_CLUSTER_SIZE):
    """Merge clusters in two phases:
    Phase 1: reduce total cluster count to <= max_clusters.
    Phase 2: absorb any remaining small clusters (< min_size URLs) into their
             most similar neighbor to eliminate fragments.
    """
    result = {k: list(set(v)) for k, v in clusters.items()}

    def get_path_segments(prefix):
        parsed = urlparse(prefix)
        path = parsed.path.strip("/")
        path_segs = tuple(path.split("/")) if path else ()
        return (parsed.scheme, parsed.netloc) + path_segs

    def common_segment_count(p1, p2):
        segs1 = get_path_segments(p1)
        segs2 = get_path_segments(p2)
        common_segs = []
        for s1, s2 in zip(segs1, segs2):
            if s1 == s2:
                common_segs.append(s1)
            else:
                break
        if len(common_segs) < 2:
            return 0, ""
        if len(common_segs) == 2:
            return 0, f"{common_segs[0]}://{common_segs[1]}"
        return len(common_segs) - 2, f"{common_segs[0]}://{common_segs[1]}/{'/'.join(common_segs[2:])}"

    def _actual_prefix(urls):
        """Compute the real common URL prefix of a list of URLs at path-segment level."""
        if not urls:
            return ""
        parts = urlparse(urls[0])
        base = f"{parts.scheme}://{parts.netloc}"
        all_segs = []
        for u in urls:
            path = urlparse(u).path.strip("/")
            all_segs.append(tuple(path.split("/")) if path else ())
        common = []
        for segments in zip(*all_segs):
            if len(set(segments)) == 1:
                common.append(segments[0])
            else:
                break
        return f"{base}/{'/'.join(common)}" if common else base

    def _merge_into_larger(res, p1, p2):
        """Merge p1 and p2: URLs go into whichever key has more URLs (keeps that key)."""
        if len(res[p1]) >= len(res[p2]):
            keep, drop = p1, p2
        else:
            keep, drop = p2, p1
        res[keep] = list(set(res[keep] + res[drop]))
        del res[drop]
        return res

    # --- Phase 1: enforce max_clusters ---
    while len(result) > max_clusters:
        prefixes = list(result.keys())
        best_i, best_j = 0, 1
        best_seg_count = -1
        best_merge_size = float('inf')

        for i in range(len(prefixes)):
            for j in range(i + 1, len(prefixes)):
                seg_count, _ = common_segment_count(prefixes[i], prefixes[j])
                merge_size = len(result[prefixes[i]]) + len(result[prefixes[j]])
                if (seg_count > best_seg_count) or \
                   (seg_count == best_seg_count and merge_size < best_merge_size):
                    best_seg_count = seg_count
                    best_i, best_j = i, j
                    best_merge_size = merge_size

        result = _merge_into_larger(result, prefixes[best_i], prefixes[best_j])

    # --- Phase 2: absorb small clusters (<= min_size) into large neighbors ---
    changed = True
    while changed:
        changed = False
        small = [p for p, urls in result.items() if len(urls) <= min_size]
        if not small or len(result) <= 1:
            break
        for sp in small:
            if sp not in result or len(result) <= 1:
                break
            large_now = [p for p in result if p != sp and len(result[p]) > min_size]
            if not large_now:
                break
            best_other = large_now[0]
            best_seg = -1
            best_size = float('inf')
            for op in large_now:
                seg_count, _ = common_segment_count(sp, op)
                size = len(result[op])
                if (seg_count > best_seg) or \
                   (seg_count == best_seg and size < best_size):
                    best_seg = seg_count
                    best_other = op
                    best_size = size
            result[best_other] = list(set(result[best_other] + result[sp]))
            del result[sp]
            changed = True

    # --- Phase 3: recalculate prefixes to reflect actual cluster content ---
    recalculated = {}
    for _, urls in result.items():
        new_pfx = _actual_prefix(urls)
        if new_pfx in recalculated:
            recalculated[new_pfx] = list(set(recalculated[new_pfx] + urls))
        else:
            recalculated[new_pfx] = urls
    return recalculated


def normalize_url(url):
    """http->https, strip trailing slash, normalize URL format."""
    url = re.sub(r'^http://', 'https://', url)
    return url.rstrip('/')


def load_urls(path):
    """Load and deduplicate URLs, filter out PDF files."""
    with open(path, encoding='utf-8') as f:
        raw = [line.strip() for line in f if line.strip()]
    
    seen = set()
    deduped = []
    for u in raw:
        norm = normalize_url(u)
        # Skip PDF files
        if norm.lower().endswith('.pdf'):
            continue
        if norm not in seen:
            seen.add(norm)
            deduped.append(norm)
    return deduped


class _LinkExtractor(HTMLParser):
    """Extract href values from <a> tags."""

    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            for name, value in attrs:
                if name == 'href' and value:
                    self.links.append(value)

    def error(self, message):
        pass


def _normalize_link(url):
    """Normalize a discovered link: https, no fragment, no trailing slash."""
    p = urlparse(url)
    path = p.path.rstrip('/')
    normalized = f"https://{p.netloc}{path}"
    if p.query:
        normalized += '?' + p.query
    return normalized


_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.3',
}


def _fetch_page_links(url, site_netloc, timeout=20, max_retries=3):
    """Fetch *url* with retries and return (status, set of normalized same-site hrefs).

    status: 'ok', 'fetch_error', 'empty_links'
    """
    html = None
    for attempt in range(max_retries):
        try:
            req = Request(url, headers=_HEADERS)
            with urlopen(req, timeout=timeout, context=_SSL_CTX) as resp:
                charset = resp.headers.get_content_charset() or 'utf-8'
                html = resp.read().decode(charset, errors='replace')
            break
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(1 * (attempt + 1))

    if html is None:
        return 'fetch_error', set()

    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass

    links = set()
    for href in parser.links:
        absolute = urljoin(url, href)
        p = urlparse(absolute)
        if p.netloc != site_netloc:
            continue
        links.add(_normalize_link(absolute))
    status = 'ok' if links else 'empty_links'
    return status, links


def compute_link_counts(urls, max_workers=32):
    """Crawl each URL, parse <a> tags, compute real in/out link counts (same-site).

    out_count: number of unique same-site URLs this page links to
    in_count:  number of pages (in the dataset) that link to this URL
    """
    if not urls:
        return {}

    site_netloc = urlparse(urls[0]).netloc
    url_set = set(urls)

    raw_outlinks = {}
    total = len(urls)
    print(f"    Crawling {total} URLs ({max_workers} workers)...", file=sys.stderr)

    stats = {'ok': 0, 'fetch_error': 0, 'empty_links': 0}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        fut_map = {pool.submit(_fetch_page_links, u, site_netloc): u for u in urls}
        done = 0
        for fut in as_completed(fut_map):
            url = fut_map[fut]
            status, links = fut.result()
            raw_outlinks[url] = links
            stats[status] += 1
            done += 1
            if done % 200 == 0 or done == total:
                print(f"    Crawled {done}/{total}", file=sys.stderr)

    summary = (f"{stats['ok']} ok, {stats['fetch_error']} fetch_error, "
               f"{stats['empty_links']} empty_links")
    print(f"    Crawl summary: {summary}", file=sys.stderr)

    # Calculate in_count: invert outlink graph (only count URLs in dataset)
    in_counter = {u: 0 for u in urls}
    for src, links in raw_outlinks.items():
        for link in links:
            if link in url_set:
                in_counter[link] += 1

    # Compile final result
    result = {}
    for url in urls:
        out_count = len(raw_outlinks.get(url, set()))
        in_count = in_counter.get(url, 0)
        result[url] = (in_count, out_count)

    return result, stats


SMALL_SITE_THRESHOLD = 250


def _importance_score(in_count, out_count):
    return in_count + 0.3 * out_count


def write_clusters(clusters, output_path, link_counts):
    """Write clustered URLs to output file with link count information."""
    total_clusters = len(clusters)
    total_urls = sum(len(m) for m in clusters.values())
    show_all = total_urls < SMALL_SITE_THRESHOLD

    sorted_clusters = sorted(clusters.items())
    size_summary = ", ".join(f"{len(m)}" for _, m in sorted_clusters)

    with open(output_path, 'w', encoding='utf-8') as f:
        mode_label = "SHOW_ALL (< {} URLs)".format(SMALL_SITE_THRESHOLD) if show_all else "FILTERED"
        f.write(f"Total: {total_clusters} clusters, {total_urls} URLs  [{mode_label}]  |  per-cluster sizes: [{size_summary}]\n")
        f.write(SEPARATOR + "\n")

        for i, (prefix, members) in enumerate(sorted_clusters):
            if i > 0:
                f.write(SEPARATOR + "\n")

            ranked = sorted(
                members,
                key=lambda u: _importance_score(*link_counts.get(u, (0, 0))),
                reverse=True
            )

            if show_all:
                qualified = [(u, link_counts.get(u, (0, 0))) for u in ranked]
            else:
                threshold = max(3, int(len(members) * 0.05))
                qualified = [(u, link_counts.get(u, (0, 0)))
                             for u in ranked
                             if link_counts.get(u, (0, 0))[0] >= threshold
                             or link_counts.get(u, (0, 0))[1] >= threshold]

            displayed = qualified[:MAX_SHOW_PER_CLUSTER]
            f.write(f"[Prefix] {prefix}  ({len(displayed)}/{len(members)} URLs)\n")

            for u, (inc, outc) in displayed:
                score = _importance_score(inc, outc)
                f.write(f"{u}  [in:{inc} out:{outc} score:{score:.0f}]\n")

    return total_clusters, total_urls


def default_output_path(input_path):
    """Generate default output path: {input}_clusters.txt"""
    base, ext = os.path.splitext(input_path)
    return base + "_clusters" + ext


def find_domain_txts(directory):
    """Find all {domain}.txt files in directory, excluding *_clusters.txt."""
    pattern = os.path.join(directory, "*.txt")
    results = []
    for path in sorted(glob.glob(pattern)):
        basename = os.path.basename(path)
        if basename.endswith("_clusters.txt"):
            continue
        results.append(path)
    return results


def process_single_file(input_path, max_group, max_clusters, min_size, workers):
    """Process a single {domain}.txt file. Returns True on success."""
    output_path = default_output_path(input_path)
    domain_name = os.path.splitext(os.path.basename(input_path))[0]

    if os.path.exists(output_path):
        print(f"  SKIP (already exists) {os.path.basename(output_path)}")
        return False

    urls = load_urls(input_path)
    if not urls:
        print(f"  SKIP (empty) {os.path.basename(input_path)}")
        return False

    # Step 1: Compute link counts (in/out)
    link_counts, crawl_stats = compute_link_counts(urls, max_workers=workers)

    # Step 2: Generate initial clusters
    clusters = prefix_cluster(urls, max_group_size=max_group)

    # Step 3: Merge clusters to meet max_clusters limit
    clusters = merge_clusters(clusters, max_clusters=max_clusters, min_size=min_size)

    # Step 4: Write results to file
    n_clusters, n_urls = write_clusters(clusters, output_path, link_counts)

    print(f"  SUCCESS: {os.path.basename(input_path)} -> {os.path.basename(output_path)}  "
          f"({n_clusters} clusters, {n_urls} URLs)")

    summary = (f"{domain_name}  |  urls: {len(urls)}  |  "
               f"ok: {crawl_stats['ok']}  fetch_error: {crawl_stats['fetch_error']}  "
               f"empty_links: {crawl_stats['empty_links']}  |  clusters: {n_clusters}")
    print(summary)
    return True


def main():
    """Main entry point - parse arguments and process files."""
    parser = argparse.ArgumentParser(description="URL prefix clustering tool with link analysis")
    parser.add_argument("dirs", nargs="*", help="Directory(s) containing {domain}.txt files")
    parser.add_argument("--file", type=str, default=None,
                        help="Process a single {domain}.txt file instead of a directory")
    parser.add_argument("--max-group", type=int, default=MAX_GROUP_SIZE,
                        help=f"Max URLs per cluster before splitting (default: {MAX_GROUP_SIZE})")
    parser.add_argument("--max-clusters", type=int, default=MAX_CLUSTERS,
                        help=f"Max number of clusters; merge if exceeded (default: {MAX_CLUSTERS})")
    parser.add_argument("--min-size", type=int, default=MIN_CLUSTER_SIZE,
                        help=f"Min URLs per cluster; smaller ones get absorbed (default: {MIN_CLUSTER_SIZE})")
    parser.add_argument("--workers", type=int, default=64,
                        help="Max concurrent crawl threads per domain (default: 8)")
    args = parser.parse_args()

    # ------ Single file mode ------
    if args.file:
        if not os.path.isfile(args.file):
            print(f"Error: {args.file} is not a file", file=sys.stderr)
            sys.exit(1)
        try:
            ok = process_single_file(args.file, args.max_group, args.max_clusters,
                                     args.min_size, args.workers)
            sys.exit(0 if ok else 1)
        except Exception as e:
            print(f"  ERROR processing {args.file}: {str(e)}", file=sys.stderr)
            sys.exit(1)

    if not args.dirs:
        parser.error("Either provide directory(s) as positional args, or use --file")

    # ------ Directory mode (original) ------
    total_files = 0
    for d in args.dirs:
        if not os.path.isdir(d):
            print(f"Warning: {d} is not a directory, skipping", file=sys.stderr)
            continue

        # Find all domain .txt files in directory
        txt_files = find_domain_txts(d)
        if not txt_files:
            print(f"Warning: no valid .txt files found in {d}", file=sys.stderr)
            continue

        # Print directory header
        print(f"\n{'='*60}")
        print(f"Directory: {d}  ({len(txt_files)} domain files to process)")
        print("=" * 60)

        # Per-directory summary log
        dir_name = os.path.basename(os.path.normpath(d))
        summary_path = os.path.join(d, f"{dir_name}_summary.txt")
        summary_lines = []

        # Process each domain file
        for input_path in txt_files:
            output_path = default_output_path(input_path)
            domain_name = os.path.splitext(os.path.basename(input_path))[0]

            if os.path.exists(output_path):
                print(f"  SKIP (already exists) {os.path.basename(output_path)}")
                continue

            urls = load_urls(input_path)
            
            if not urls:
                print(f"  SKIP (empty) {os.path.basename(input_path)}")
                continue

            try:
                # Step 1: Compute link counts (in/out)
                link_counts, crawl_stats = compute_link_counts(urls, max_workers=args.workers)
                
                # Step 2: Generate initial clusters
                clusters = prefix_cluster(urls, max_group_size=args.max_group)
                
                # Step 3: Merge clusters to meet max_clusters limit
                clusters = merge_clusters(clusters, max_clusters=args.max_clusters,
                                          min_size=args.min_size)
                
                # Step 4: Write results to file
                n_clusters, n_urls = write_clusters(clusters, output_path, link_counts)
                
                # Print progress
                print(f"  SUCCESS: {os.path.basename(input_path)} -> {os.path.basename(output_path)}  "
                      f"({n_clusters} clusters, {n_urls} URLs)")
                total_files += 1

                # Record crawl summary
                summary_lines.append(
                    f"{domain_name}  |  urls: {len(urls)}  |  "
                    f"ok: {crawl_stats['ok']}  fetch_error: {crawl_stats['fetch_error']}  "
                    f"empty_links: {crawl_stats['empty_links']}  |  "
                    f"clusters: {n_clusters}")
                
            except Exception as e:
                print(f"  ERROR processing {os.path.basename(input_path)}: {str(e)}", file=sys.stderr)
                summary_lines.append(f"{domain_name}  |  ERROR: {str(e)}")
                continue

        # Write per-directory summary
        if summary_lines:
            with open(summary_path, 'w', encoding='utf-8') as sf:
                sf.write(f"Crawl Summary for {dir_name}/ ({len(summary_lines)} domains)\n")
                sf.write("=" * 80 + "\n")
                for line in summary_lines:
                    sf.write(line + "\n")
            print(f"  Summary written to {summary_path}")

    # Final summary
    print(f"\nDone. Processed {total_files} files successfully.")


if __name__ == "__main__":
    main()