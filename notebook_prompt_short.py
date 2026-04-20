import json
import os
import re
import argparse
from urllib.parse import urlparse

output_dir = "./questions/notebook_prompt"

QUESTION_TEMPLATE = """You are a Web Intelligence Agent that analyzes websites and organizes their content into a structured knowledge document called a **Guidebook** — a concise, categorized summary of a website's pages and their key information.

**Input**

Your input is a **clustered URL file** at `{queue_file_path}`. This file contains URLs from a single website, pre-grouped into categories by their URL path prefix (e.g., all `/blog/...` URLs form one category, all `/docs/...` URLs form another). Each URL is annotated with link metrics in the format `[in:X out:Y score:S]`, where `in` is how many other pages link to it (inbound links), `out` is how many links it contains (outbound links), and `score` is a composite importance score derived from both. Categories are separated by `===...===` lines, and each starts with a `[Prefix]` header.

**Tools**

You have access to `web_agent(task=...)`, a function that fetches and reads real web pages — use it to scrape each URL's content. In addition, the code block below provides helper functions for managing the Guidebook (appending content, tracking progress, counting tokens, etc.). Copy and execute this entire block in your first code cell:

```python
{tool_functions_code}
```

**Tool Usage**

1. Call `parse_cluster_stats()` to read the file header and get the total number of URLs and categories. Based on the site size, decide your processing mode: for small sites (≤ 250 URLs), use **FULL mode** where every URL is included; for larger sites, use **SELECTIVE mode** where you pick the most important URLs per category (ranked by `score`, up to 20 per category if ≤ 8 categories, or 10 if more).
2. Create a token allocation plan — distribute the target Guidebook length ({min_token}–{token_limit} tokens) across categories proportionally by each category's **effective URL count** (i.e., the number of URLs you will actually scrape, after applying the per-category cap from step 1 — not the raw total), then save it with `write_plan()`.
3. Process categories one by one: call `get_next_category()` to load a category, scrape its selected URLs with `web_agent()`, write the category section with `append_to_guidebook()`, then call `mark_category_done()` to advance. Repeat until all categories are done.
4. After all categories are processed, check the total length with `count_guidebook_tokens()`. If it exceeds {token_limit}, compress verbose sections with `rewrite_category_section()`. If it falls below {min_token}, expand by scraping additional URLs. Finally, prepend an Overview header and call `save_final_guidebook()`.

**Output format per category:**
```markdown
## Category: [Name]
- **URL Prefix:** [prefix URL]
- **Category Summary:** [what this category covers]

**Scraped Pages:**
- **[Page Title]** (https://full.url/path): [summary of key info]
- ...

> This category may contain additional pages. Visit: [prefix URL]
```

**Rules:**
- Scraping: You MUST call web_agent(task="...") to fetch real content for every selected URL. Summarize the key information. Crucially, every page summary must come from a real web_agent() call. Never fabricate or guess content. Do NOT use placeholders to stand in for URL summaries, and NEVER rely on your internal knowledge to hallucinate or invent page content.
- Every scraped page entry must include its full URL.
- Only include pages from the website's own domain — no external links.
- Summarize in your own words; do not copy page content verbatim.
- Process ALL categories before finalizing.
"""


def build_question_data(index, base_url, queue_file_path, guidebook_path,
                        plan_file_path, token_limit, min_token, id):
    safe_queue_path = queue_file_path.replace('\\', '/')
    safe_guidebook_path = guidebook_path.replace('\\', '/')
    safe_plan_path = plan_file_path.replace('\\', '/')

    tool_functions_code = f"""import os
import re
import tiktoken

QUEUE_FILE = "{safe_queue_path}"
GUIDEBOOK_PATH = "{safe_guidebook_path}"
PLAN_PATH = "{safe_plan_path}"
PROGRESS_FILE = "{safe_queue_path.replace('.txt', '_progress.txt')}"
_ENC = tiktoken.get_encoding("cl100k_base")

os.makedirs(os.path.dirname(GUIDEBOOK_PATH) or ".", exist_ok=True)
os.makedirs(os.path.dirname(PLAN_PATH) or ".", exist_ok=True)


def parse_cluster_stats():
    if not os.path.exists(QUEUE_FILE):
        print("[x] Queue file does not exist.")
        return None
    with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
        first_line = f.readline().strip()
    try:
        left, right = first_line.split('|', 1)
        parts = left.replace(',', ' ').split()
        n_clusters = int(parts[1])
        n_urls = int(parts[3])
        bracket_content = right.split('[')[1].split(']')[0]
        per_cluster = [int(x.strip()) for x in bracket_content.split(',')]
    except (IndexError, ValueError) as e:
        print(f"[x] Could not parse stats: {{first_line}} ({{e}})")
        return None
    mode = "FULL" if n_urls <= 250 else "SELECTIVE"
    print(f"[ok] {{n_clusters}} clusters, {{n_urls}} URLs, mode={{mode}}, per_cluster={{per_cluster}}")
    return {{"n_clusters": n_clusters, "n_urls": n_urls, "per_cluster": per_cluster, "mode": mode}}


def write_plan(plan_text):
    os.makedirs(os.path.dirname(PLAN_PATH) or ".", exist_ok=True)
    with open(PLAN_PATH, 'w', encoding='utf-8') as f:
        f.write(plan_text)
    print(f"[ok] Plan written to {{PLAN_PATH}}")


def read_plan():
    if not os.path.exists(PLAN_PATH):
        return ""
    with open(PLAN_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def get_next_category():
    if not os.path.exists(QUEUE_FILE):
        return None
    with open(QUEUE_FILE, 'r', encoding='utf-8') as f:
        content = f.read().strip()
    if not content:
        return None
    sep_line = None
    for line in content.split('\\n'):
        stripped = line.strip()
        if len(stripped) >= 10 and all(c == '=' for c in stripped):
            sep_line = stripped
            break
    if sep_line is None:
        return None
    blocks = [b.strip() for b in content.split(sep_line) if b.strip() and '[Prefix]' in b]
    if not blocks:
        return None
    idx = 0
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            try:
                idx = int(f.read().strip())
            except ValueError:
                idx = 0
    if idx >= len(blocks):
        print("[ok] All categories processed.")
        return None
    print(f"[ok] Category {{idx + 1}}/{{len(blocks)}}: {{blocks[idx].splitlines()[0]}}")
    return blocks[idx]


def mark_category_done():
    idx = 0
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            try:
                idx = int(f.read().strip())
            except ValueError:
                idx = 0
    with open(PROGRESS_FILE, 'w') as f:
        f.write(str(idx + 1))
    print(f"[ok] Category {{idx + 1}} done.")


def count_guidebook_tokens():
    if not os.path.exists(GUIDEBOOK_PATH):
        return 0
    with open(GUIDEBOOK_PATH, 'r', encoding='utf-8') as f:
        text = f.read()
    return len(_ENC.encode(text))


def append_to_guidebook(text):
    with open(GUIDEBOOK_PATH, 'a', encoding='utf-8') as f:
        f.write(text.rstrip() + '\\n\\n')
    tokens = count_guidebook_tokens()
    print(f"[ok] Appended. Current: ~{{tokens}} tokens")


def read_guidebook():
    if not os.path.exists(GUIDEBOOK_PATH):
        return ""
    with open(GUIDEBOOK_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def rewrite_category_section(category_name, new_compressed_text):
    if not os.path.exists(GUIDEBOOK_PATH):
        return False
    with open(GUIDEBOOK_PATH, 'r', encoding='utf-8') as f:
        content = f.read()
    clean_name = category_name.replace("##", "").replace("Category:", "").strip()
    safe_name = re.escape(clean_name)
    pattern = re.compile(
        rf"(^##\\s*Category:\\s*[^\\n]*{{safe_name}}[^\\n]*\\n)(.*?)(?=^##\\s*Category:|\\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE
    )
    match = pattern.search(content)
    if not match:
        print(f"[x] Category '{{clean_name}}' not found.")
        return False
    if not new_compressed_text.strip().startswith("##"):
        replacement = match.group(1) + new_compressed_text.strip() + "\\n\\n"
    else:
        replacement = new_compressed_text.strip() + "\\n\\n"
    new_content = content[:match.start()] + replacement + content[match.end():]
    new_content = re.sub(r'\\n{{3,}}', '\\n\\n', new_content)
    with open(GUIDEBOOK_PATH, 'w', encoding='utf-8') as f:
        f.write(new_content)
    tokens = count_guidebook_tokens()
    print(f"[ok] Rewrote '{{clean_name}}'. Current: ~{{tokens}} tokens")
    return True


def save_final_guidebook(full_content):
    with open(GUIDEBOOK_PATH, 'w', encoding='utf-8') as f:
        f.write(full_content)
    tokens = count_guidebook_tokens()
    print(f"[ok] Final guidebook saved (~{{tokens}} tokens)")"""

    return {
        "task_id": f"test_{index - 1}",
        "Question": QUESTION_TEMPLATE.format(
            tool_functions_code=tool_functions_code,
            queue_file_path=safe_queue_path,
            plan_file_path=safe_plan_path,
            token_limit=token_limit,
            min_token=min_token,
        ),
    }


def main(cluster_files, token_limit, min_token):
    os.makedirs(output_dir, exist_ok=True)
    token_str = f"{token_limit // 1000}k"

    if not cluster_files:
        print("No cluster files provided. Use --cluster_files.")
        return

    for cluster_file in cluster_files:
        if not os.path.exists(cluster_file):
            print(f"[SKIP] File not found: {cluster_file}")
            continue

        basename = re.sub(r'(_\d+_cluster|_clusters)\.txt$', '', os.path.basename(cluster_file))

        with open(cluster_file, "r", encoding="utf-8") as f:
            content = f.read()

        base_url = None
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("[Prefix]"):
                parts = line.split()
                if len(parts) >= 2:
                    p = urlparse(parts[1])
                    base_url = f"{p.scheme}://{p.netloc}"
                    break
            elif line.startswith("http"):
                p = urlparse(line)
                base_url = f"{p.scheme}://{p.netloc}"
                break

        if not base_url:
            print(f"[SKIP] Could not determine base URL from {cluster_file}")
            continue

        domain = urlparse(base_url).netloc
        print(f"\nProcessing: {cluster_file}  (domain: {domain})")

        queue_dir = "./queue_file"
        os.makedirs(queue_dir, exist_ok=True)

        for id in range(1, 10):
            queue_file_path = os.path.abspath(
                os.path.join(queue_dir, f"{basename}_queue_{id}.txt")
            )
            with open(queue_file_path, "w", encoding="utf-8") as f:
                f.write(content)

            guidebook_path = os.path.abspath(
                os.path.join(
                    "./questions",
                    f"{basename}_final_guidebook_{token_limit}_{id}.md",
                )
            )
            os.makedirs(os.path.dirname(guidebook_path), exist_ok=True)

            plan_file_path = os.path.abspath(
                os.path.join(
                    "./plans",
                    f"{basename}_{id}_plan.txt",
                )
            )

            data = build_question_data(
                id, base_url, queue_file_path, guidebook_path,
                plan_file_path, token_limit, min_token, id,
            )

            file_path = os.path.join(
                output_dir, f"{basename}_{token_str}_{id}.jsonl"
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            print(f"  Generated: {file_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate simplified inference-time guidebook prompts."
    )
    parser.add_argument(
        "--cluster_files", type=str, nargs="+", required=True,
        help="Paths to cluster files",
    )
    parser.add_argument(
        "--token_limit", type=int, default=24_000,
        help="Maximum guidebook token count (default: 24000)",
    )
    parser.add_argument(
        "--min_token", type=int, default=8_000,
        help="Minimum guidebook token count (default: 4000)",
    )
    args = parser.parse_args()
    main(args.cluster_files, args.token_limit, args.min_token)
