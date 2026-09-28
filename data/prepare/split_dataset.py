import json
import random
from pathlib import Path

def split_dataset(input_file, train_file, test_file, train_ratio=0.8, random_seed=42):
    """
    将 JSONL 数据集分割为训练集和测试集
    
    Args:
        input_file: 输入的 JSONL 文件路径
        train_file: 训练集输出文件路径
        test_file: 测试集输出文件路径
        train_ratio: 训练集比例，默认 0.8
        random_seed: 随机种子，默认 42
    """
    random.seed(random_seed)
    
    data = []
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    
    random.shuffle(data)
    
    split_idx = int(len(data) * train_ratio)
    train_data = data[:split_idx]
    test_data = data[split_idx:]
    
    with open(train_file, 'w', encoding='utf-8') as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    with open(test_file, 'w', encoding='utf-8') as f:
        for item in test_data:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    
    print(f"数据集分割完成:")
    print(f"总样本数: {len(data)}")
    print(f"训练集样本数: {len(train_data)} ({len(train_data)/len(data)*100:.1f}%)")
    print(f"测试集样本数: {len(test_data)} ({len(test_data)/len(data)*100:.1f}%)")
    print(f"训练集已保存到: {train_file}")
    print(f"测试集已保存到: {test_file}")

if __name__ == "__main__":
    input_path = Path(__file__).parent / "med-dataset.jsonl"
    train_path = Path(__file__).parent / "med-dataset-train.jsonl"
    test_path = Path(__file__).parent / "med-dataset-test.jsonl"
    
    split_dataset(input_path, train_path, test_path, train_ratio=0.8, random_seed=42)