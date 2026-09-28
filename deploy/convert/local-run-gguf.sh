#!/usr/bin/env bash
# ============================================================
# 在【本地】把云端产出的 GGUF 下回来，并用 4060 跑起来看图
# 运行环境：本地 Windows（推荐 WSL2 里编译/运行，路径用 /mnt/d/...）
#
# 本地内存只有 16GB，所以"转换"放云上做了；本地只负责"编译 CUDA 版
# + 量化(可选) + 推理"。量化若想在本地做也行（峰值约 12GB，16GB 够）。
# ============================================================

# ---- 1. 把云端产物下回本地（在本机 Git Bash / WSL2 跑，不是云上）----
# 端口/主机以 AutoDL 控制台为准；下面是之前实例的示例
# scp -P 47027 -r root@connect.cqa1.seetacloud.com:~/qwen35-4b-med-vl-IQ4_XS.gguf* /mnt/d/Local-model/qwen35-4b-med-vl/
# （Windows 原生路径写法：D:/Local-model/qwen35-4b-med-vl/）

# ---- 2. 本地编译官方 llama.cpp CUDA（官方已原生支持 Qwen3.5，无需分叉）----
git clone --depth 1 https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j --target llama-server llama-mtmd-cli

# ---- 3. 跑服务（mmproj 文件名以你实际下载的为准）----
./build/bin/llama-server \
  -m /mnt/d/Local-model/qwen35-4b-med-vl/qwen35-4b-med-vl-IQ4_XS.gguf \
  --mmproj /mnt/d/Local-model/qwen35-4b-med-vl/qwen35-4b-med-vl-bf16.mmproj.gguf \
  -ngl 999 --host 0.0.0.0 --port 8080
# 浏览器开 http://localhost:8080 即可传图对话（同时是 OpenAI 兼容 API）

# ---- 4. 接回 v4 前端 ----
# 编辑 fastapi_v4_ui.py，把写死的 127.0.0.1:8000(LLM) 和 :8001(VL)
# 两处都改成 127.0.0.1:8080 —— Qwen3.5-4B 是统一多模态模型，
# 看图+给建议一个服务全包，不必再起两个。
