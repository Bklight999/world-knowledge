import json
import re
import argparse
from urllib.parse import urlparse


def url_to_safe_name(url):
    """Convert URL to safe filename, matching shell's url_to_safe_name:
       replace all non-alphanumeric chars with '_', strip leading/trailing '_'."""
    raw = urlparse(url).netloc
    return re.sub(r'[^a-zA-Z0-9]', '_', raw).strip('_')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--notebook_id", type=str, default="6")
    parser.add_argument("--token_limit", type=int, default=16000, help="Token limit used in guidebook filename (default: 16000)")
    parser.add_argument("--url", type=str, default="https://www2024.thewebconf.org/")
    args = parser.parse_args()
    
    datas = []
    domain = url_to_safe_name(args.url)
    print(domain)

    with open('./data/WebWalker.jsonl', 'r') as f:
        for line in f:
            if args.url in line:
                datas.append(json.loads(line))


    difficulty_order = {'easy': 0, 'medium': 1, 'hard': 2}
    type_order = {'single_source': 0, 'multi_source': 1}
    datas.sort(key=lambda x: (difficulty_order.get(x['info']['difficulty_level'], 3), type_order.get(x['info']['type'], 2)))


    notebook = ""
    if args.notebook_id != "6": # 6 为 without notebook 测试，不做 notebook 质检，直接跑 CK-pro
        with open(f'./questions/{domain}_final_guidebook_{args.token_limit}_{args.notebook_id}.md', 'r') as f:
            notebook = f.read()


    problem_set = []

    for i, data in enumerate(datas):
        Question = data["question"] + f" The website is: {args.url}"

        if args.notebook_id != "6":
            Question = f"""You are an advanced web information gathering expert and navigation planner.
I will provide you with a [Main Page URL], a [Notebook] containing summaries of sub-pages, and a [Target Question] that needs to be resolved.
**Your task is to evaluate this information, determine which specific web pages should be explored next, and ultimately obtain the final answer to the question by visiting these pages.**

[Input Data]
1. Main Page URL: {args.url}
2. Target Question: {data["question"]}
3. Sub-page Summaries Notebook:
{notebook}

[Your Decision Logic]
Please carefully read the "content summary" of each sub-page in the Notebook and analyze its relevance to the "Target Question":
1. **Answer Directly (Rare)**: If the "content summary" in the Notebook already contains the specific factual data needed to fully answer the question, please provide the answer directly.
2. **Explore Sub-pages (Most Common)**: If the topic of one or more sub-pages in the Notebook is highly relevant to the question (e.g., the question is about finding executives, and a sub-page summary is "About Us - Team Introduction"), please extract the URLs of these sub-pages and explore them to find the answer. **If you find a potential answer on these sub-pages, carefully verify its accuracy and relevance. If you are not highly confident it is the correct answer, or if you still cannot find the answer after visiting all selected sub-pages**, do NOT give up — return to the [Main Page URL] and explore it from scratch to look for additional clues or links not covered by the Notebook.
3. **Explore Main Page from Scratch (Fallback)**: If all the sub-page summaries provided in the Notebook are completely irrelevant to the question (e.g., they are all privacy policies, disclaimers, etc.), it indicates that the current branch is invalid. In this case, you must decide to return to the [Main Page URL] to start looking for new clues from scratch."""

        problem = {
            "task_id": f"test{i}",
            "Question": Question,
            "Level": "1",
            "Final answer": data["answer"],
            "file_name": "",
            "difficulty": data['info']['difficulty_level']
        }

        problem_set.append(problem)

    with open(f'./test_data/problem_set_{domain}_with_notebook_{args.notebook_id}.jsonl', 'w', encoding='utf-8') as f:
        for p in problem_set:
            jsonline = json.dumps(p, ensure_ascii=False)
            f.write(jsonline + "\n")
