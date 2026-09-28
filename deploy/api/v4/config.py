"""
MedButler v4 配置模块（自包含，零第三方依赖）

- 优先读取同目录 .env 文件（KEY=VALUE，# 注释），未配置的项走内置默认值
- 使用：from config import cfg
"""
import os

_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _load_env(path=_ENV_PATH):
    """解析 .env：返回 dict；文件不存在返回 {}"""
    values = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key, val = key.strip(), val.strip().strip("'\"")
                if key:
                    values[key] = val
    except OSError:
        pass
    return values


_env = _load_env()


def _get(key, default, cast=str):
    try:
        return cast(_env.get(key, default))
    except (TypeError, ValueError):
        return default


class Cfg:
    """v4 运行配置（env 覆盖 -> 默认值）"""

    # 下游 llama-server
    LLAMA_BASE_URL = _get("LLAMA_BASE_URL", "http://127.0.0.1:8080")

    # v4 服务自身（供启动脚本/文档参考；uvicorn 端口由启动命令决定）
    V4_HOST = _get("V4_HOST", "0.0.0.0")
    V4_PORT = _get("V4_PORT", 8000, int)

    # 图像预处理
    IMAGE_MAX_SIZE = _get("IMAGE_MAX_SIZE", 1280, int)

    # VL 生成（多模态，开思考）
    VL_MODEL_NAME = _get("VL_MODEL_NAME", "medmodelvl")
    VL_MAX_TOKENS = _get("VL_MAX_TOKENS", 4096, int)
    VL_MAX_ATTEMPTS = _get("VL_MAX_ATTEMPTS", 3, int)
    VL_RETRY_TEMPERATURE = _get("VL_RETRY_TEMPERATURE", 0.3, float)

    # LLM 生成（文本，关思考）
    LLM_MAX_TOKENS = _get("LLM_MAX_TOKENS", 2048, int)
    LLM_TEMPERATURE = _get("LLM_TEMPERATURE", 0.6, float)
    LLM_REPEAT_PENALTY = _get("LLM_REPEAT_PENALTY", 1.2, float)

    # 流式超时（秒）：read 为相邻 chunk 最大间隔，非总时长
    STREAM_CONNECT_TIMEOUT = _get("STREAM_CONNECT_TIMEOUT", 10.0, float)
    STREAM_READ_TIMEOUT = _get("STREAM_READ_TIMEOUT", 300.0, float)
    STREAM_WRITE_TIMEOUT = _get("STREAM_WRITE_TIMEOUT", 60.0, float)

    # 日志
    LOG_LEVEL = _get("LOG_LEVEL", "INFO").upper()


cfg = Cfg()
