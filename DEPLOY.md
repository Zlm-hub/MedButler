# MedButler 启动与部署指南

> 本文档整合了实际跑通验证过的启动步骤与踩坑经验。主路径：**本地 Windows 离线部署**（llama.cpp + GGUF 量化模型）。

## 架构总览

```
浏览器 ──> v4 Web 服务 (FastAPI :8000)
                │  NDJSON 流式（思考过程/结论/建议实时推送）
                ▼
          llama-server (llama.cpp CUDA :8080)
                │  OpenAI 兼容接口（completion + multimodal）
                ▼
          qwen35-4b-med-vl GGUF (IQ4_XS 量化, 4060 8G 可跑)
```

- **一个模型包打天下**：Qwen3.5-4B 是统一多模态模型，读报告图 + 生成健康建议都走 8080 一个服务。
- **启动顺序**：先 8080（模型加载约 1 分钟），再 8000。
- **停止**：直接结束对应进程即可（后台任务/窗口关闭）。

---

## 一、本地部署（Windows，主路径）

### 1. 前置条件

| 组件 | 位置 | 说明 |
| --- | --- | --- |
| llama.cpp CUDA 版 | `D:\llama-server\main\llama-server.exe` | 官方预编译 b11223+，`cudart` DLL 需与 exe 同级 |
| 量化模型 | `D:\Local-model\qwen35-4b-med-vl\qwen35-4b-med-vl-IQ4_XS.gguf` | 云端转换产出（见第二节） |
| 视觉投影 | `D:\Local-model\qwen35-4b-med-vl\qwen35-4b-med-vl-mmproj-bf16.gguf` | 与主模型配套 |
| v4 Python 环境 | `D:\llama-server\v4-venv` | 装见 `requirements/api-v4.txt`（fastapi/uvicorn/httpx/pillow/python-multipart），**不需要 vllm** |

### 2. 启动推理服务（:8080）

方式一（推荐）：双击 `D:\llama-server\run-med-vl.bat`，内容等价于：

```bat
D:\llama-server\main\llama-server.exe ^
  -m "D:\Local-model\qwen35-4b-med-vl\qwen35-4b-med-vl-IQ4_XS.gguf" ^
  --mmproj "D:\Local-model\qwen35-4b-med-vl\qwen35-4b-med-vl-mmproj-bf16.gguf" ^
  -ngl 99 -c 8192 ^
  --cache-type-k q8_0 --cache-type-v q8_0 ^
  --port 8080
```

> ⚠️ KV 旗标是 `--cache-type-k/v`，写成旧名 `--kv-cache-type` 会报 `invalid argument`。

验证（模型加载完约 1 分钟）：

```bash
curl http://127.0.0.1:8080/v1/models
# 返回 JSON 且 capabilities 含 "multimodal" 即就绪
```

### 3. 启动 v4 Web 服务（:8000）

```bash
cd MedButler/deploy/api/v4
D:\llama-server\v4-venv\Scripts\python.exe -m uvicorn fastapi_v4_ui:app --host 0.0.0.0 --port 8000
```

Linux/WSL 下等价：`sh launch-fastapi-v4.sh`（自动读取 `.env` 的 `V4_HOST`/`V4_PORT`）。

### 4. 使用与验证

- 浏览器打开 **http://127.0.0.1:8000/**，上传报告图片
- 全程流式：思考过程实时滚动 → 异常指标结论 → 三段健康建议
- 日志监控：**http://127.0.0.1:8000/logs?lines=200**（文件落盘 `logs/medbutler.log`，按天滚动留 14 天）

### 5. 配置调整

所有运行参数集中在 `deploy/api/v4/.env`（模板见同目录 `.env.example`），改完重启 v4 生效：

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `LLAMA_BASE_URL` | `http://127.0.0.1:8080` | 下游 llama-server 地址 |
| `IMAGE_MAX_SIZE` | `1280` | 上传图最长边缩放上限 |
| `VL_MAX_TOKENS` / `VL_MAX_ATTEMPTS` | `4096` / `3` | 读图思考上限 / 重试次数 |
| `LLM_MAX_TOKENS` / `LLM_TEMPERATURE` | `2048` / `0.6` | 建议生成参数 |
| `STREAM_READ_TIMEOUT` | `300` | 流式相邻 chunk 间隔上限（非总时长） |

---

## 二、云端部署（AutoDL / Linux，训练与 vLLM）

> 云端负责**训练**与**GGUF 转换**；推理上线走本地（第一节）。

### vLLM 推理服务（训练后验证用）

```bash
cd MedButler/deploy/launch-vllm
uv sync          # 按 pyproject.toml + uv.lock 装依赖（阿里镜像）
sh 1-launch-llm.sh   # 文本模型 medmodelllm，:8000
sh 2-launch-vl.sh    # 多模态 medmodelvl，:8001（gpu_memory_utilization 0.45）
```

训练/评估模块的依赖安装：

```bash
pip install -r requirements/train.txt      # 微调训练
pip install -r requirements/eval-llm.txt   # EvalScope 评估
pip install -r requirements/vllm-service.txt
```

### GGUF 转换（云端转 → 本地跑）

```bash
# 云端：llama.cpp convert_hf_to_gguf.py，主模型 + mmproj 各转一次
sh MedButler/deploy/convert/cloud-convert-to-gguf.sh

# 本地：下载产物后编译/启动
# 见 deploy/convert/local-run-gguf.sh（含 llama.cpp CUDA 编译步骤）
```

---

## 三、常见问题排查

| 现象 | 根因与解法 |
| --- | --- |
| 调 llama-server 报 `404 File Not Found` | 多模态请求后**复用同一 HTTP 连接**会 404 → 每次调用新建连接（v4 已内置 `async with httpx.AsyncClient`） |
| LLM 输出为空 / 死循环 | 思考型模型：**LLM 文本调用必须关思考**（`"chat_template_kwargs": {"enable_thinking": false}`），VL 读图必须开 |
| VL 偶发 content 为空 | 思考耗光 token → v4 自动换温度重试（日志看 `vl_attempt_done` 的 `content_len/reasoning_len`） |
| 前端「请求超时」 | 已根治（流式）。若再现，查 `/logs` 中 `vl_attempt_done` 的 `elapsed` |
| v4 起不来 / 端口占用 | `netstat -ano | grep :8000` 找 PID → `taskkill /F /PID <pid>` |
| Windows 装 vllm 失败 | v4 不需要 vllm（走 llama-server HTTP）；vllm 仅云端 Linux 用 |
| git push 大文件超时/502 | HTTPS 走代理慢且不稳 → **用 SSH**（`git@github.com:...`，本机 22 端口直连 GitHub 畅通，~3 MiB/s） |
| 分析结果格式乱 | 输出格式已在 prompt 钉死（VL 固定行格式 / LLM 三段 Markdown），若乱多为模型温度漂移，可在 `.env` 调低 `LLM_TEMPERATURE` |

---

## 四、目录速查

```
MedButler/
├── DEPLOY.md                ← 本文档
├── README.md                ← 项目介绍 + 效果预览
├── requirements/            ← 分模块 pip 依赖
├── data/                    # raw(原始数据) / prepare(脚本+数据集) / images
├── train/                   # llm + vl 微调脚本
├── eval/llm/                # evalscope / vllm-service / result-viewer
└── deploy/
    ├── convert/             # GGUF 转换
    ├── launch-vllm/         # 云端 vLLM 部署
    ├── validation/          # 部署前验证
    └── api/v4/              # ★ 主服务（fastapi_v4_ui.py + config.py + logger.py + ui/）
```
