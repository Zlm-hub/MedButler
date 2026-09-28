#!/bin/sh

uv run uvicorn fastapi_v3_vllm:app --host 0.0.0.0 --port 8080