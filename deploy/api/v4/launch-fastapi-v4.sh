#!/bin/sh
# 启动 v4 服务：自动读取同目录 .env 中的 V4_HOST / V4_PORT（未配置时走默认值）
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a

uv run uvicorn fastapi_v4_ui:app --host "${V4_HOST:-0.0.0.0}" --port "${V4_PORT:-8000}"
