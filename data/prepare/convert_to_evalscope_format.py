import json
import sys

def convert_conversations_to_jsonl(input_file: str, output_file: str):
    with open(input_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    with open(output_file, 'w', encoding='utf-8') as out_f:
        for item in data:
            conversations = item.get("conversations", [])
            user_msg = None
            assistant_msg = None

            # 遍历对话，找到第一个 user 和紧随其后的 assistant 消息
            for i, msg in enumerate(conversations):
                if msg["role"] == "user" and user_msg is None:
                    user_msg = msg["content"]
                elif msg["role"] == "assistant" and user_msg is not None and assistant_msg is None:
                    assistant_msg = msg["content"]
                    break  # 只取第一轮问答

            # 如果找到了成对的问答，就写入
            if user_msg is not None and assistant_msg is not None:
                line = {
                    "query": user_msg.strip(),
                    "response": assistant_msg.strip()
                }
                out_f.write(json.dumps(line, ensure_ascii=False) + '\n')
            else:
                print(f"跳过无效对话项: {item}")

    print(f"成功将 {input_file} 转换为 {output_file}")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python convert_conversations_to_jsonl.py <input.json> <output.jsonl>")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    convert_conversations_to_jsonl(input_path, output_path)