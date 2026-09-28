#!/bin/sh

OMP_NUM_THREADS=8 uv run vllm serve /root/autodl-tmp/qwen35-4b-med-vl \
    --host 0.0.0.0 \
    --port 8001 \
	--trust-remote-code \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
	--max-model-len 8196 \
	--max-num-batched-tokens 8196 \
	--max-num-seqs 2 \
	--dtype auto \
	--kv-cache-dtype auto \
	--tensor-parallel-size 1 \
    --served-model-name medmodelvl \
    --gpu_memory_utilization 0.45

