import os
import json
import glob
import matplotlib.pyplot as plt
import argparse

def compute_accuracy_for_file(filepath):
    """Compute the accuracy for a single JSONL file."""
    total = 0
    correct = 0
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                # Skip malformed lines.
                continue
            
            # Support both string and numeric corr values.
            corr = data.get("corr", 0)
            if isinstance(corr, str):
                is_correct = corr.strip() == "1"
            else:
                is_correct = (corr == 1)
            
            total += 1
            if is_correct:
                correct += 1
    
    if total == 0:
        return 0.0
    return correct / total

def main(folder_path):
    # Find all ans_*.jsonl files under the target directory.
    pattern = os.path.join(folder_path, "ans_*.jsonl")
    file_list = sorted(glob.glob(pattern))
    
    if not file_list:
        print("No ans_*.jsonl files found.")
        return
    
    file_names = []
    accuracies = []
    
    for filepath in file_list:
        acc = compute_accuracy_for_file(filepath)
        filename = os.path.basename(filepath)
        file_names.append(filename)
        accuracies.append(acc)
        print(f"{filename}: accuracy = {acc:.4f}")
    
    plt.figure(figsize=(10, 6))
    x_positions = range(len(file_names))
    
    plt.bar(x_positions, accuracies, color='skyblue')
    plt.xticks(x_positions, file_names, rotation=45, ha='right')
    plt.ylim(0, 1.0)
    plt.ylabel("Accuracy")
    plt.xlabel("File Name")
    plt.title("Model Accuracy per JSONL File")
    
    for x, acc in zip(x_positions, accuracies):
        plt.text(x, acc + 0.01, f"{acc:.2f}", ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    plt.show()
    plt.savefig(f"{folder_path}/accuracy.png")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", type=str, default="./results/ehaweb_org")
    args = parser.parse_args()

    main(args.folder)