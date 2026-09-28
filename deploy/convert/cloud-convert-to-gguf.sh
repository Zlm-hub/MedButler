#!/usr/bin/env bash
# ============================================================
# 在【云端 AutoDL】把微调模型 qwen35-4b-med-vl 转 GGUF + 量化
# 更新（2026-09-28 晚）：经 GitHub 源码核实——官方 llama.cpp 已原生
#   支持 Qwen3_5ForConditionalGeneration（文本 conversion/qwen.py 的
#   Qwen3_5TextModel + 视觉 conversion/qwen3vl.py 的 mmproj 类），
#   无需任何补丁分叉。tekintian/llama-cpp 仓库实际不存在，勿用。
# ============================================================
set -e

# ---- 0. 前置确认 ----
df -h /root/autodl-tmp
ls /root/autodl-tmp/qwen35-4b-med-vl   # 应看到 config.json / model.safetensors-* 等

# ---- 1. 清掉旧残骸 + 克隆官方 llama.cpp（ghfast 镜像绕 GitHub 封锁）----
unset http_proxy https_proxy all_proxy ALL_PROXY
rm -rf ~/llama.cpp ~/llama-cpp
git clone --depth 1 https://ghfast.top/https://github.com/ggml-org/llama.cpp.git
cd ~/llama.cpp

# ---- 2. Python 环境（官方转换脚本 import torch，requirements 里带了）----
python -m venv .venv && source .venv/bin/activate
pip install -U pip -i https://mirrors.aliyun.com/pypi/simple/
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/
# 若 torch 下载太慢的兜底：直接用现成 venv（vLLM 环境里有 torch）
# source /root/autodl-tmp/MedButler/deploy/launch-vllm/.venv/bin/activate

# ---- 3. 转换：主模型 + 视觉 mmproj（官方新流程，跑两次）----
export MODEL=/root/autodl-tmp/qwen35-4b-med-vl
python convert_hf_to_gguf.py "$MODEL" \
  --outfile ~/qwen35-4b-med-vl-bf16.gguf --outtype bf16
python convert_hf_to_gguf.py "$MODEL" --mmproj \
  --outfile ~/qwen35-4b-med-vl-mmproj-bf16.gguf --outtype bf16
ls -lh ~/qwen35-4b-med-vl*.gguf*

# ---- 4. 编译 llama-quantize（纯 CPU 即可）----
cmake -B build
cmake --build build --config Release -j --target llama-quantize

# ---- 5. 量化 IQ4_XS（自动屏蔽离群张量，推荐）----
./build/bin/llama-quantize \
  ~/qwen35-4b-med-vl-bf16.gguf \
  ~/qwen35-4b-med-vl-IQ4_XS.gguf IQ4_XS
# Q4_K_M 备选（需手动保 3 个离群张量 bf16，否则精度爆炸）：
# ./build/bin/llama-quantize \
#   --tensor-type "blk\.9\.ssm_out\.weight=bf16" \
#   --tensor-type "blk\.15\.attn_output\.weight=bf16" \
#   --tensor-type "blk\.24\.ffn_gate\.weight=bf16" \
#   ~/qwen35-4b-med-vl-bf16.gguf ~/qwen35-4b-med-vl-Q4_K_M.gguf Q4_K_M

echo "===== 产出（下面 scp 回本地）====="
ls -lh ~/*med-vl*.gguf
# IQ4_XS 确认完好后可删 bf16 中间产物，释放 8.3G：
# rm ~/qwen35-4b-med-vl-bf16.gguf
