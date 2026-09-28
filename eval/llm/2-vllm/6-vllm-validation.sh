curl http://127.0.0.1:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "medmodelllm",
        "messages": [
            {"role": "system", "content": "你是一个专业的医疗健康顾问，能够提供有关体检指标异常的专业健康建议。"},
            {"role": "user", "content": "活化部分凝血酶原时间APTT 19.00 秒，稍稍低于参考值 23-35"}
        ]
    }'