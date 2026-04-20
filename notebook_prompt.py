import json
import os
import re
import argparse
from urllib.parse import urlparse

output_dir = "./questions/notebook_prompt"

QUESTION_TEMPLATE = """**【Role】**
You are a Web Intelligence Agent specializing in website analysis and knowledge organization.
You will receive a **pre-clustered URL file** for a website, where URLs are already grouped by path prefix. Your task is to scrape these URLs **category by category** and produce a structured **Guidebook** that stays within a target token range.

**【Constraints】**
- **Maximum** Guidebook length: **{token_limit}** tokens
- **Minimum** Guidebook length: **{min_token}** tokens
- You must actively manage content length throughout the process — compress when too long, expand when too short.
- **Small-site rule (≤ 250 URLs):** Before starting, check the **Total URLs** count on the first line of the cluster file. **If the total is 250 or fewer, you MUST include every single URL in the guidebook — no filtering, no skipping.** All URL-selection and priority rules below become irrelevant for small sites. Only apply filtering when total URLs > 250.
- **Strict URL cap per category (SELECTIVE mode only):** The cap depends on the total number of categories:
  - If **≤ 8 categories** total: at most **20** scraped-page entries per category.
  - If **> 8 categories** total: at most **10** scraped-page entries per category.
  This cap is **absolute** — no exceptions, even if a category has many high-`in`/high-`out` URLs. Select the top URLs by priority (see URL Priority Rules below). In FULL mode, this cap does not apply — include all URLs.
- **No external links:** Do NOT include any **external links** that lead to a different domain in the Guidebook. Only document pages belonging to the website's own domain.
- **Summarize, don't copy:** Do NOT copy raw page content verbatim into the Guidebook. Always **summarize and condense** the key information in your own words. The Guidebook should be a concise guide, not a dump of webpage text.
- **⚠️ REAL SCRAPING ONLY — NO SIMULATION:** Every page summary in the Guidebook MUST be derived from an actual `web_agent()` call. You are FORBIDDEN from simulating, mocking, or bypassing `web_agent()`. If your code never executes `web_agent()` but still produces summaries, the entire output is INVALID and will be discarded. This is the #1 failure mode — take it seriously.
- **Every scraped page must have a URL:** Each entry under "Scraped Pages" **MUST** include the full URL in parentheses. An entry without a URL is **INVALID**. Format: `- **[Page Title]** (https://full.url/path): [summary]`. Never write a summary without its corresponding URL.
- **Follow your token plan:** The length and detail of each category's content should be guided by the **planned token allocation** from Phase 0. Spend more tokens on categories with more URLs, fewer on small ones. Focus on specific, useful information (names, dates, numbers, features). Do not pad with generic or repetitive descriptions.

**【URL Priority Rules】** (only apply when total URLs > 250)

Each URL in the cluster file has link metrics in the format `[in:X out:Y score:S]`, where `in` is the number of inbound links (how many other pages on the site link to it), `out` is the number of outbound links, and `score` is a composite importance score.

**Primary sort:** Higher `score` value = higher priority (most important page).
**Secondary sort:** If `score` values are the same, higher `in` value = higher priority.
**Tertiary sort:** If `in` values are also the same, higher `out` value = higher priority.

**【Input】**
A clustered URL file is located at: `{queue_file_path}`

The file format:
```
Total: <N> clusters, <M> URLs  [SHOW_ALL/FILTERED ...]  |  per-cluster sizes: [<c1>, <c2>, ...]
============================================================
[Prefix] <prefix_url>  (<shown>/<total> URLs)
<url_1>  [in:<X> out:<Y> score:<S>]
<url_2>  [in:<X> out:<Y> score:<S>]
...
============================================================
[Prefix] <prefix_url>  (<shown>/<total> URLs)
<url_3>  [in:<X> out:<Y> score:<S>]
<url_4>  [in:<X> out:<Y> score:<S>]
...
... (<K> more)
```
The first line contains global statistics: total number of clusters, total number of URLs, an optional mode tag like `[SHOW_ALL ...]` or `[FILTERED ...]`, and the URL count for each cluster after `per-cluster sizes:`. Categories are separated by lines of repeated `=` characters. Each category starts with a `[Prefix]` header showing `(shown/total URLs)`. Each URL is annotated with `[in:X out:Y score:S]` link metrics — `in` is inbound links, `out` is outbound links, `score` is a composite importance score. If a category has more URLs than shown, it ends with `... (N more)`.

**【Tools】**
Below is a complete Python code block containing ALL the tool functions you need. **You MUST copy and execute this ENTIRE code block AS-IS in your very first code cell.** After that, simply call these functions by name — do NOT redefine, rewrite, or re-implement any of them unless a function throws a runtime error.

⚠️⚠️⚠️ **ABSOLUTE RULE: DO NOT REWRITE ANY FUNCTION BELOW.** ⚠️⚠️⚠️
Every past failure (crashed guidebooks, missing categories, lost content, wrong token counts) was caused by rewriting these functions. The functions are tested and correct. **If you rewrite even one function, the entire task will fail.**
- If a function throws an error, **read the error message carefully** and fix your *calling code* — the bug is almost certainly in how you call the function, not in the function itself.
- **DO NOT** write your own version of `get_next_category()`, `mark_category_done()`, `rewrite_category_section()`, or `parse_cluster_stats()`. Use them exactly as provided.

⚠️ **IMPORTANT: Functions do NOT persist between separate code execution steps.** If you define functions in one code block and call them in the next, you will get a `NameError`. To avoid this:
- **Always include the full tool function definitions AND your logic in the SAME code block.** For example, paste all functions first, then immediately write your Phase 0 / Phase 1 code below them in the same block.
- If you must split across multiple blocks, **re-paste the function definitions at the top of every new code block.**

```python
{tool_functions_code}
```

**【Workflow】**

⚠️ **You MUST execute the phases in strict order: Phase 0 → Phase 1 → Phase 2. Do NOT skip Phase 0.** Phase 1 depends on the plan file created in Phase 0. If you jump to Phase 1 first, `read_plan()` will fail and you will waste steps recovering.

### Phase 0: Initialization & Planning

Before processing any category, you must create a token-allocation plan.

**Step 1: Parse Cluster Statistics**
- Call `parse_cluster_stats()` — the one already defined above, do NOT rewrite it. It reads the first line of the queue file and extracts:
  - Total number of clusters
  - Total number of URLs
  - Per-cluster URL counts
- Determine the **processing mode**:
  - If total URLs ≤ 250 → **FULL mode**: every URL must be included; URL filtering rules do NOT apply.
  - If total URLs > 250 → **SELECTIVE mode**: apply URL priority rules; max URLs per category = 20 if ≤ 8 categories, 10 if > 8 categories.

**Step 2: Create Token Allocation Plan**
- **URL cap** (SELECTIVE only): 20 per category if ≤ 8 categories, 10 if > 8. FULL mode has no cap.
- **Effective URL count** per cluster = `min(actual_count, cap)` (FULL: use `actual_count`).
- **Allocate tokens proportionally by effective URL count** — more URLs → more tokens. Do NOT split equally. Rough guide: ~50–80 tokens per page entry + ~100–150 for category header/summary.
- **⚠️ Total planned tokens MUST be within [{min_token}, {token_limit}].** Adjust allocations to stay in range.
- Call `write_plan(plan_text)` to save to `{plan_file_path}`. Include: mode (FULL/SELECTIVE), URL cap, and per-category breakdown (prefix URL, actual/effective URL count, token allocation).

**Step 3:** Proceed to Phase 1.

⚠️ **Phase 0 MUST be fully completed (stats parsed + plan written) BEFORE you call `get_next_category()`.** The `get_next_category()` function permanently removes data from the queue file. If you call it before `parse_cluster_stats()`, the header line will be destroyed and stats parsing will fail with no way to recover.

---

### Phase 1: Category-by-Category Processing (Loop)

Process the clustered URL file one category at a time:

**Step 1: Load Next Category**
- Call `get_next_category()` — the one already defined above. **Do NOT write your own version.** This function returns the current unprocessed category block. It is safe to call multiple times — it always returns the same category until you explicitly call `mark_category_done()`.
- If it returns `None`, all categories have been processed — proceed to **Phase 2**.

**Step 1.5: Read Token Budget (MANDATORY — do NOT skip)**
- ⚠️ **This step is NOT optional. You MUST execute it for every category before writing anything.**
- Call `read_plan()` to open and read the plan file (`{plan_file_path}`).
- If `read_plan()` returns an empty string, **STOP and go back to Phase 0 Step 2 to create the plan first.** Never proceed without a plan.
- Find the current category's prefix URL in the plan and extract its **planned token allocation** (e.g., `budget = 1200`).
- **Print it explicitly:** `print(f"Token budget for this category: {{budget}}")` — this forces you to be aware of the target.
- You will use this number in Step 3 to control the length of your output. For example: if the budget is 500 tokens, write a brief summary with short page entries; if 2000 tokens, write detailed summaries with rich page entries.

**Step 2: Select & Scrape Member Pages**
- **In FULL mode (≤ 250 URLs):** Scrape **all** member URLs in the category. No filtering.
- **In SELECTIVE mode (> 250 URLs):**
  - Parse the `[in:X out:Y score:S]` metrics for each URL.
  - Sort URLs by `score` descending, then by `in` descending, then by `out` descending.
  - Select the **top N** URLs where N is the per-category cap (20 if ≤ 8 categories, 10 if > 8), or all if fewer than the cap. **Never exceed the cap, regardless of how many high-priority URLs exist.**
- **⚠️⚠️⚠️ ABSOLUTE RULE: You MUST call `web_agent()` to fetch and read EVERY selected URL. ⚠️⚠️⚠️**
  - For each URL, call: `result = web_agent(task="Scrape the content of <URL> and extract the page title and key information.")`
  - Then use `result` (the actual returned content) to write your summary.
  - `web_agent()` is a REAL, WORKING function already defined in your environment. It connects to a real web scraping service. You MUST actually call it for every URL. If you get a `NameError`, you forgot to paste the tool functions — re-paste them and try again.
  - **FORBIDDEN — any of the following will make the ENTIRE guidebook INVALID and the run will be restarted from scratch:**
    - ❌ Simulating or mocking `web_agent()` in any way (defining `def web_agent(task):`, assigning `web_agent = lambda ...`, wrapping it, etc.)
    - ❌ Guessing or fabricating page content based on the URL path instead of calling `web_agent()`
    - ❌ Writing placeholder/generic text like "This page provides information about...", "Key topics include...", "For specific details, please refer to..."
    - ❌ Using `ask_llm()` or any other LLM call to generate fake summaries instead of `web_agent()`
    - ❌ Any code path where a summary is written to the guidebook WITHOUT a real `web_agent()` call for that URL
    - ❌ Using try/except to catch `NameError` on `web_agent` and falling back to fabricated content
  - If `web_agent()` fails for a particular URL (timeout, error, empty response), you may skip that URL — but you must still attempt the call. Never silently substitute fake content.
- Skip useless pages (login walls, error pages, empty pages, cookie/privacy notices) — but only AFTER fetching them and confirming they are useless.

**Step 3: Write Category Section (target the token budget from Step 1.5)**
- **Before writing, recall the token budget** you extracted in Step 1.5. Your entire section for this category (header + summary + all scraped page entries) should aim for approximately that many tokens. This is a target, not a hard wall — being within ±20% is acceptable, but being 2x over or under means you ignored the plan.
- Use `append_to_guidebook(text)` to append this category's section to the guidebook.
- **Category Summary** should describe what this category covers: the main topics, the types of pages it contains, and what a user can find here. Adjust detail level based on the budget (brief if budget is small, detailed if budget is large).
- Each category section MUST follow this format. **YOU MUST EXACTLY USE "## Category: [Name]" AS THE HEADER. DO NOT CHANGE THE FORMAT.**
  ```markdown
  ## Category: [Descriptive Name Based on Content]
  - **URL Prefix:** [the prefix URL for this group]
  - **Category Summary:** [Describe what this category covers: its main topics, the types of pages it contains, and what a user can find here. Adjust length to token budget. No filler.]

  **Scraped Pages:**
  - **[Page Title]** ([full URL — REQUIRED]): [Specific details — names, dates, numbers, features, etc. Adjust length to token budget. No fluff.]
  - **[Page Title]** ([full URL — REQUIRED]): [summary]
  - ...

  > 📌 This category may contain additional pages beyond those listed. For further exploration, visit: [prefix URL]
  ```
- **Every entry under "Scraped Pages" MUST have a URL in parentheses.** An entry like `- **[Title]**: [summary]` without a URL is **INVALID** and must be fixed.

**Step 4: Mark Done & Continue**
- After successfully appending this category to the guidebook, call `mark_category_done()` to advance the progress index. **Only call this after `append_to_guidebook()` succeeds** — this ensures no category is skipped even if an earlier step fails or retries.
- Return to **Step 1** to process the next category.
- Do NOT check tokens after every category — token adjustment is handled in Phase 2.
- **⚠️ You MUST process ALL categories until `get_next_category()` returns `None`.** Do not stop early for any reason — not because of token counts, not because of errors on individual pages, not because you think you have "enough" content. Every category must be written to the guidebook before moving to Phase 2.

---

### Phase 2: Refinement & Finalization

After all categories have been processed:

**Step 1: Token-Based Compression or Expansion**
- Call `count_guidebook_tokens()`.
- **If tokens > {token_limit}:** Compress the guidebook:
  - Call `read_guidebook()` to review all content.
  - Identify verbose or repetitive sections and rewrite them with `rewrite_category_section()`.
  - Repeat until within limit.
- **If tokens < {min_token}:** Expand the guidebook. Follow these steps **exactly** to avoid content loss:
  1. **Pick expansion target:** Call `read_plan()` to load the plan file. Compare each category's **planned token allocation** against its actual content length. Pick the category with the **largest gap** (actual content far below planned allocation). If multiple categories have similar gaps, prefer the one with more URLs or richer information.
  2. **Read the target category's existing content precisely:** Call `read_guidebook()` to get the full text. Locate the target category's `## Category:` section and **copy its complete content verbatim** (from `## Category:` header to just before the next `## Category:` or end of file) into a variable. This is your reconstruction baseline — **do NOT rely on memory; you must work from the exact text you just read.**
  3. **Scrape new content:** Re-visit URLs in that category (or scrape additional URLs from the original cluster that were not included) to gather more detailed, specific information. **You MUST personally fetch and read the webpages — do NOT invent content or ask an LLM to "expand" without new data, as this causes hallucinations.**
  4. **Build a complete replacement section from scratch:** Using the exact text from Step 2 + the new data from Step 3, write the full category section in markdown — include the `## Category:` header, URL Prefix, Category Summary, and ALL Scraped Pages (keep every original entry + add newly expanded/added entries). **Do NOT parse existing Scraped Pages line-by-line with regex to merge** — this drops multi-line summaries. Instead, augment directly on top of the verbatim text from Step 2.
  5. **Call the provided `rewrite_category_section(category_name, new_section_text)` function** to replace the old section with the new one. Pass the **full section text** (starting with `## Category: ...`). **Use the function exactly as provided — do NOT redefine or rewrite it.**
  6. Call `count_guidebook_tokens()` to check progress. Repeat steps 1–5 for other categories until the guidebook reaches at least `{min_token}` tokens.

  ⚠️ **Expansion pitfalls to avoid:**
  - **DO NOT redefine `rewrite_category_section()`** — use the one already loaded. Rewriting it removes header-preservation logic and causes content corruption.
  - **DO NOT parse existing Scraped Pages line-by-line with regex** to merge old and new entries. Multi-line summaries will be silently dropped, making the "expanded" section shorter than the original.
  - **DO NOT call `save_final_guidebook()` with partial content** during expansion — it overwrites the entire file. Only use it in Step 2 below for the final save with Overview.
  - **DO NOT rely on memory to reconstruct original content.** You must read the target section precisely from `read_guidebook()` in Step 2 and augment on that basis.

**Step 2: Add Overview Header & Save**
- Call `read_guidebook()` to get the full current content.
- Prepend an Overview section at the top:
  ```markdown
  # [Website Domain] Guidebook

  ## Overview
  - **Website:** [base URL]
  - **Total Categories:** [number]
  - **Total Pages Analyzed:** [number]
  [2-3 sentence high-level overview of the website's purpose and content.]

  ---
  ```
- Call `save_final_guidebook(full_content)` with the complete content (Overview + all category sections).
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
    \"\"\"⚠️ DO NOT MODIFY THIS FUNCTION.
    Parse the first line of the queue file to get total clusters, total URLs, and per-cluster counts.
    Format: 'Total: 6 clusters, 464 URLs  |  per-cluster sizes: [42, 25, 52, 24, 28, 293]'
    Returns a dict with keys: n_clusters, n_urls, per_cluster, mode, or None if parsing fails.\"\"\"
    if not os.path.exists(QUEUE_FILE):
        print("[✘] Queue file does not exist.")
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
        print(f"[✘] Could not parse stats from first line: {{first_line}} ({{e}})")
        return None
    mode = "FULL" if n_urls <= 250 else "SELECTIVE"
    url_cap = 20 if n_clusters <= 8 else 10
    print(f"[✔] Parsed stats: {{n_clusters}} clusters, {{n_urls}} URLs")
    print(f"    Per-cluster counts: {{per_cluster}}")
    print(f"    Processing mode: {{mode}} ({{'include ALL URLs' if mode == 'FULL' else f'filter by priority, max {{url_cap}} per category'}})")
    return {{"n_clusters": n_clusters, "n_urls": n_urls, "per_cluster": per_cluster, "mode": mode}}


def write_plan(plan_text):
    \"\"\"Write the token allocation plan to the plan file.\"\"\"
    os.makedirs(os.path.dirname(PLAN_PATH) or ".", exist_ok=True)
    with open(PLAN_PATH, 'w', encoding='utf-8') as f:
        f.write(plan_text)
    print(f"[✔] Plan written to {{PLAN_PATH}}")


def read_plan():
    \"\"\"Read the full content of the plan file.\"\"\"
    if not os.path.exists(PLAN_PATH):
        print("[✘] Plan file does not exist.")
        return ""
    with open(PLAN_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def get_next_category():
    \"\"\"⚠️ DO NOT MODIFY THIS FUNCTION.
    Non-destructive & idempotent: returns the current unprocessed category block
    WITHOUT advancing the index. Safe to call multiple times — always returns
    the same category until you call mark_category_done().
    Returns the block text (starting with [Prefix] ...), or None if all done.\"\"\"
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
        print("[✔] All categories have been processed.")
        return None

    next_block = blocks[idx]
    print(f"[✔] Current category {{idx + 1}}/{{len(blocks)}}: {{next_block.splitlines()[0]}}")
    print(f"    Remaining after this: {{len(blocks) - idx - 1}}")
    return next_block


def mark_category_done():
    \"\"\"⚠️ DO NOT MODIFY THIS FUNCTION.
    Advance the progress index by 1. Call this AFTER you have successfully
    appended the current category to the guidebook.\"\"\"
    idx = 0
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, 'r') as f:
            try:
                idx = int(f.read().strip())
            except ValueError:
                idx = 0
    with open(PROGRESS_FILE, 'w') as f:
        f.write(str(idx + 1))
    print(f"[✔] Category {{idx + 1}} marked as done.")


def count_guidebook_tokens():
    \"\"\"Count the exact token count of the current guidebook using tiktoken (cl100k_base).\"\"\"
    if not os.path.exists(GUIDEBOOK_PATH):
        return 0
    with open(GUIDEBOOK_PATH, 'r', encoding='utf-8') as f:
        text = f.read()
    return len(_ENC.encode(text))


def append_to_guidebook(text):
    \"\"\"Append a text block to the guidebook file.\"\"\"
    with open(GUIDEBOOK_PATH, 'a', encoding='utf-8') as f:
        f.write(text.rstrip() + '\\n\\n')
    tokens = count_guidebook_tokens()
    print(f"[✔] Appended to guidebook. Current length: ~{{tokens}} tokens")


def read_guidebook():
    \"\"\"Read the full content of the guidebook.\"\"\"
    if not os.path.exists(GUIDEBOOK_PATH):
        return ""
    with open(GUIDEBOOK_PATH, 'r', encoding='utf-8') as f:
        return f.read()


def rewrite_category_section(category_name, new_compressed_text):
    \"\"\"⚠️ DO NOT MODIFY THIS FUNCTION.
    Rewrite/compress an entire category section in the guidebook.
    This replaces the old section with 'new_compressed_text'.
    Returns True if successful, False otherwise.
    \"\"\"
    if not os.path.exists(GUIDEBOOK_PATH):
        print("[✘] Guidebook does not exist.")
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
        print(f"[✘] Category matching '{{clean_name}}' not found in guidebook.")
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
    print(f"[✔] Rewrote category '{{clean_name}}'. Current length: ~{{tokens}} tokens")
    return True


def save_final_guidebook(full_content):
    \"\"\"Save the final version of the guidebook (overwrites the file).\"\"\"
    with open(GUIDEBOOK_PATH, 'w', encoding='utf-8') as f:
        f.write(full_content)
    tokens = count_guidebook_tokens()
    print(f"[✔] Final guidebook saved to {{GUIDEBOOK_PATH}} (~{{tokens}} tokens)")"""

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
        description="Generate guidebook prompts from pre-clustered URL files."
    )
    parser.add_argument(
        "--cluster_files", type=str, nargs="+", required=True,
        help="Paths to cluster files (e.g. ./conference/ehaweb_org_clusters.txt)",
    )
    parser.add_argument(
        "--token_limit", type=int, default=24_000,
        help="Maximum guidebook token count (default: 24000)",
    )
    parser.add_argument(
        "--min_token", type=int, default=8_000,
        help="Minimum guidebook token count (default: 8000)",
    )
    args = parser.parse_args()
    main(args.cluster_files, args.token_limit, args.min_token)
