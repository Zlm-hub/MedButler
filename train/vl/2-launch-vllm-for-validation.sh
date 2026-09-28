#!/bin/sh

vllm serve /root/autodl-tmp/qwen35-4b-med-vl \
    --host 0.0.0.0 \
    --port 8000 \
    --max-model-len=8k \
    --gpu_memory_utilization=0.90
