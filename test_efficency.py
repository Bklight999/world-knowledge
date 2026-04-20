import json
import argparse
import os
import matplotlib.pyplot as plt


def _count_steps_including_subagent(data):
    """Count total steps including sub-agent steps."""
    main_steps = data['session']['steps']
    total = len(main_steps)
    for step in main_steps:
        action = step.get('action', {})
        ob = action.get('observation', [])
        if isinstance(ob, dict) and 'session' in ob and 'steps' in ob['session']:
            total += len(ob['session']['steps'])
    return total


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='test efficency')
    parser.add_argument("--domain_name", type=str, default="www_ageofempires_com")
    args = parser.parse_args()

    ans_dir = f'./output_ans/{args.domain_name}'
    output_dir = f'./results/{args.domain_name}'
    os.makedirs(output_dir, exist_ok=True)

    efficency_data = []

    for file in os.listdir(ans_dir):
        if file.endswith('.jsonl'):
            notebook_id = file.split('_')[1].split('jsonl')[0]
            datas = []
            with open(os.path.join(ans_dir, file), 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        datas.append(data)
                    except json.JSONDecodeError:
                        continue

            print(len(datas))
            if len(datas) == 0:
                continue

            total_steps = 0
            for data in datas:
                total_steps += _count_steps_including_subagent(data)
            avg_steps = total_steps / len(datas)
            efficency_data.append({
                'notebook_id': notebook_id,
                'avg_steps': avg_steps
            })
    
    plt.bar([data['notebook_id'] for data in efficency_data], [data['avg_steps'] for data in efficency_data])
    for i, data in enumerate(efficency_data):
        plt.text(i, data['avg_steps'], f'{data["avg_steps"]:.2f}', ha='center', va='bottom')
    plt.xlabel('notebook_id')
    plt.ylabel('avg_steps')
    plt.title('avg_steps per notebook')
    plt.savefig(os.path.join(output_dir, 'efficency.png'))

    for data in efficency_data:
        with open(os.path.join(output_dir, f'efficiency_{data["notebook_id"]}.txt'), 'w') as f:
            f.write(f'{data["avg_steps"]:.2f}')