"""
Crawl sub-links from given root URLs and save to {domain}.txt files.

Usage:
    # Read URLs from a txt file (one URL per line)
    python crawl_urls.py urls.txt

    # Multiple input files
    python crawl_urls.py urls1.txt urls2.txt

    # Custom output directory
    python crawl_urls.py urls.txt -o output/

    # Limit max pages per URL
    python crawl_urls.py urls.txt --max-pages 1000

    # Custom worker count
    python crawl_urls.py urls.txt --workers 32
"""

import argparse
import os
import re
import queue
import threading
import time
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


MAX_PAGES_PER_URL = 50000
MAX_WORKERS = 64


def url_to_filename(root_url):
    """Convert URL to a safe filename based on its netloc."""
    netloc = urlparse(root_url).netloc
    return re.sub(r"[^a-zA-Z0-9]", "_", netloc).strip("_")


def ensure_trailing_slash(url):
    """Ensure URL ends with / (unless the path already has a file extension)."""
    parsed = urlparse(url)
    path = parsed.path
    if path and "." in path.rsplit("/", 1)[-1]:
        return url
    if not path.endswith("/"):
        return parsed._replace(path=path + "/").geturl()
    return url


def crawl_urls(base_url, max_count=MAX_PAGES_PER_URL, max_workers=MAX_WORKERS):
    """BFS crawl to discover same-domain URLs."""
    base_url = base_url.rstrip("/")
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    session = requests.Session()
    session.headers.update(headers)

    valid_urls = []
    seen_urls = {base_url}
    url_queue = queue.Queue()
    url_queue.put(base_url)
    lock = threading.Lock()
    stop_event = threading.Event()
    # Debug counters
    stats = {"fetch_ok": 0, "fetch_err": 0, "non_html": 0, "non_200": 0}

    def worker(pbar):
        while not stop_event.is_set():
            try:
                current_url = url_queue.get(timeout=20)
            except queue.Empty:
                break
            if stop_event.is_set():
                url_queue.task_done()
                break
            resp = None
            max_retries = 3
            try:
                for attempt in range(max_retries):
                    try:
                        resp = session.get(
                            current_url, timeout=60, verify=False,
                            allow_redirects=True
                        )
                        break
                    except Exception:
                        if attempt < max_retries - 1:
                            time.sleep(2 ** attempt)
                if resp is None:
                    with lock:
                        stats["fetch_err"] += 1
                    continue
                content_type = resp.headers.get("Content-Type", "")
                if resp.status_code != 200:
                    with lock:
                        stats["non_200"] += 1
                        # Print first few failures for debugging
                        if stats["non_200"] <= 3:
                            print(f"  [DEBUG] {resp.status_code} {current_url}", file=sys.stderr)
                    continue
                if "text/html" not in content_type:
                    with lock:
                        stats["non_html"] += 1
                    continue
                with lock:
                    stats["fetch_ok"] += 1
                    if len(valid_urls) >= max_count:
                        stop_event.set()
                    else:
                        valid_urls.append(current_url)
                        pbar.update(1)
                        if len(valid_urls) >= max_count:
                            stop_event.set()
                if not stop_event.is_set():
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for a_tag in soup.find_all("a", href=True):
                        if stop_event.is_set():
                            break
                        full_url = urljoin(current_url, a_tag["href"])
                        clean_url = (
                            full_url.split("#")[0].split("?")[0].rstrip("/")
                        )
                        if urlparse(clean_url).netloc == base_domain:
                            with lock:
                                if clean_url not in seen_urls:
                                    seen_urls.add(clean_url)
                                    url_queue.put(clean_url)
            except Exception:
                pass
            finally:
                url_queue.task_done()

    with tqdm(total=max_count, desc=f"Crawling {base_domain}", unit="url") as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for _ in range(max_workers):
                executor.submit(worker, pbar)
            while not stop_event.is_set():
                if url_queue.unfinished_tasks == 0:
                    break
                stop_event.wait(0.5)
            stop_event.set()

    print(f"  [Stats] ok={stats['fetch_ok']} non_200={stats['non_200']} "
          f"non_html={stats['non_html']} fetch_err={stats['fetch_err']} "
          f"discovered={len(seen_urls)}", file=sys.stderr)

    return sorted(set(ensure_trailing_slash(u) for u in valid_urls))


def load_urls_from_file(filepath):
    """Load URLs from a txt file, one URL per line. Skip empty lines and comments (#)."""
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def main():
    parser = argparse.ArgumentParser(
        description="Crawl sub-links from given root URLs and save to {domain}.txt"
    )
    parser.add_argument("input_files", nargs="+", help="Txt file(s) containing root URLs (one per line)")
    parser.add_argument("-o", "--output-dir", default=".", help="Output directory (default: current dir)")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES_PER_URL,
                        help=f"Max pages to crawl per URL (default: {MAX_PAGES_PER_URL})")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS,
                        help=f"Max concurrent threads (default: {MAX_WORKERS})")
    args = parser.parse_args()

    # Load all URLs from input files
    all_urls = []
    for filepath in args.input_files:
        if not os.path.isfile(filepath):
            print(f"Warning: {filepath} not found, skipping", file=sys.stderr)
            continue
        urls = load_urls_from_file(filepath)
        print(f"Loaded {len(urls)} URLs from {filepath}")
        all_urls.extend(urls)

    if not all_urls:
        print("No URLs to process. Exiting.")
        sys.exit(1)

    # Deduplicate while preserving order
    seen = set()
    unique_urls = []
    for u in all_urls:
        if u not in seen:
            seen.add(u)
            unique_urls.append(u)

    print(f"\nTotal: {len(unique_urls)} unique root URLs to crawl\n")
    os.makedirs(args.output_dir, exist_ok=True)

    for i, root_url in enumerate(unique_urls, 1):
        fname = url_to_filename(root_url)
        txt_path = os.path.join(args.output_dir, f"{fname}.txt")

        if os.path.exists(txt_path):
            with open(txt_path) as f:
                existing = [line.strip() for line in f if line.strip()]
            print(f"[{i}/{len(unique_urls)}] SKIP (exists) {txt_path}  ({len(existing)} URLs)")
            continue

        print(f"\n[{i}/{len(unique_urls)}] Crawling: {root_url}")
        sub_urls = crawl_urls(root_url, max_count=args.max_pages, max_workers=args.workers)

        with open(txt_path, "w") as f:
            for url in sub_urls:
                f.write(url + "\n")
        print(f"Saved {len(sub_urls)} URLs -> {txt_path}")

    print(f"\nDone. Processed {len(unique_urls)} root URL(s).")


if __name__ == "__main__":
    main()
