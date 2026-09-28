#!/bin/sh

uv run vllm serve /root/autodl-tmp/qwen35-4b \
    --host 0.0.0.0 \
    --port 8000 \
    --trust-remote-code \
    --max-model-len 8196 \
    --max-num-batched-tokens 8196 \
    --max-num-seqs 2 \
    --dtype auto \
    --kv-cache-dtype auto \
    --tensor-parallel-size 1 \
    --gpu-memory-utilization 0.85 
