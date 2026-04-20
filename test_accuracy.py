import json
import os
from transformers import AutoTokenizer
import argparse
from openai import OpenAI
import jsonlines
import logging
from tqdm import tqdm
from pathlib import Path
import math
import pickle
from datetime import datetime
import time
import requests
from urllib.parse import urlparse


def generate_text_template(question, predict, gt, tokenizer=None):
    system_prompt = "You are a professional LLM judge."
    user_prompt = f"""Please judge whether the answer is fully consistent with the ground truth.

The question is: {question}
The answer is: {predict}
The ground truth is: {gt}

If the question contains multiple sub-questions or multiple required components, the answer must correctly address ALL of them to be considered consistent.

Output 1 if the answer is completely consistent with the ground truth; otherwise output 0.
Please output only the number without any other words.
"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    return messages



def call_vllm_api(client, messages, args, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=args.model_name,
                messages=messages,
                temperature=args.temperature,
                top_p=args.top_p,
                max_tokens=args.max_tokens,
                n=args.n,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            return response
        except Exception as e:
            print(f"vLLM API call failed (attempt {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                raise e


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='vLLM inference using OpenAI compatible API')
    parser.add_argument("--max_tokens", type=int, default=4096)
    parser.add_argument("--model_name", type=str, default="ck")
    parser.add_argument("--temperature", type=float, default=1.0)
    parser.add_argument("--top_p", type=float, default=0.95)
    parser.add_argument("--n", type=int, default=1)
    parser.add_argument("--notebook_id", type=int, default=6)
    parser.add_argument("--domain_name", type=str, default="sigchi_org")
    parser.add_argument("--api_base", type=str, default="http://localhost:8080/v1")
    parser.add_argument("--api_key", type=str, default="EMPTY")
    parser.add_argument("--request_delay", type=float, default=0.5)
    parser.add_argument("--filename", type=str, default="www24_ans.jsonl")
    args = parser.parse_args()

    # client
    client = OpenAI(
        api_key=args.api_key,
        base_url=args.api_base
    )

    # load input
    answer_and_gt_file = f"./output_ans/{args.domain_name}/ans_{args.notebook_id}.jsonl"
    answer_and_gt = []
    with open(answer_and_gt_file, 'r') as f:
        for line in f:
            try:
                answer_and_gt.append(json.loads(line))
            except:
                continue

    # prepare messages
    vllm_input_data = []
    for data in answer_and_gt:
        print('guidebook' in data['task'])
        if 'guidbook' not in data['task']:
            print(1)
            question = data['task']
        else:
            print(2)
            question = data['task'].split(
                'You can answer the question with the help of the guidbook'
            )[0]
        predict = data['eval']['pred']
        gt = data['eval']['gold']
        steps = len(data['session']['steps'])
        messages = generate_text_template(question, predict, gt)
        vllm_input_data.append((messages, predict, gt, question, steps))

    print(f"Total {len(vllm_input_data)} input samples\n")

    all_outputs = []

    for input_data in tqdm(vllm_input_data, desc="Running"):
        messages, predict, gt, question, steps= input_data
        flag = True
        try:
            response = call_vllm_api(client, messages, args)
        except Exception as e:
            flag = False
        all_outputs.append({
            "question": question,
            "predict": predict,
            "gt": gt,
            "corr": response.choices[0].message.content if flag else 0,
            "steps": steps
        })
        time.sleep(args.request_delay)  # avoid overloading the API
    
    output_dir = f"./results/{args.domain_name}"
    os.makedirs(output_dir, exist_ok=True)

    with open(f"{output_dir}/ans_{args.notebook_id}.jsonl", "w") as f:
        for output in all_outputs:
            f.write(json.dumps(output, ensure_ascii=False) + "\n")
    
    with open(f"{output_dir}/score_{args.notebook_id}.txt", "wb") as f:
        f.write(str(sum([int(output["corr"]) for output in all_outputs]) / len(all_outputs)).encode("utf-8"))

    print("All done; results saved to vllm_outputs.jsonl")