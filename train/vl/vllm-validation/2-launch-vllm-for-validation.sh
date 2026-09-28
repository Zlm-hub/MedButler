#!/bin/sh

OMP_NUM_THREADS=8 uv run vllm serve /root/autodl-tmp/qwen35-4b-med-vl \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len=8k \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    --served-model-name medmodelvl \
    --gpu_memory_utilization=0.90
