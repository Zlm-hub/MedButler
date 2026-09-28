import csv
import json
from itertools import islice

def csv_to_dict(csv_file):
    data = []
    with open(csv_file, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        for row in reader:
            data.append(row)
    return data

question = csv_to_dict('question.csv')
for item in islice(question, 10):
    print(f"{item}")

answer = csv_to_dict('answer.csv')
for item in islice(answer, 10):
    print(f"{item}")

question_dict = {}
for item in question:
    question_dict[item['question_id']] = item['content']
#print(question_dict)

answer_dict = {}
for item in answer:
    answer_dict[item['question_id']] = item['content']
#print(answer_dict)

common_keys = question_dict.keys() & answer_dict.keys()
merged_dict = {question_dict[k]: answer_dict[k] for k in common_keys}

count = 0
for key, value in merged_dict.items():
    print(f"{key}: {value}")
    count += 1
    if count >= 10:
        break

result_list = []
for question, answer in merged_dict.items():
    conversations = []
    conversations.append({"role": "user", "content": question})
    conversations.append({"role": "assistant", "content": answer})
    result_list.append({"conversations": conversations})


with open('med-dataset.json', 'w', encoding='utf-8') as f:
    json.dump(result_list, f, indent=2, ensure_ascii=False)

# total = len(result_list)
# chunk_size = total // 3

# part1 = result_list[:chunk_size]
# part2 = result_list[chunk_size:2*chunk_size]
# part3 = result_list[2*chunk_size:]

# with open('med-dataset-train.json', 'w', encoding='utf-8') as f:
#     json.dump(part1, f, indent=2, ensure_ascii=False)

# with open('med-dataset-valid.json', 'w', encoding='utf-8') as f:
#     json.dump(part2, f, indent=2, ensure_ascii=False)

# with open('med-dataset-test.json', 'w', encoding='utf-8') as f:
#     json.dump(part3, f, indent=2, ensure_ascii=False)

