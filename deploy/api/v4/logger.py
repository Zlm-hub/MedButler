"""
MedButler v4 全链路日志模块（自包含，不依赖项目其他文件）

- 写文件：deploy/api/v4/logs/medbutler.log（按天滚动，保留 14 天）
- 同时输出到控制台（uvicorn 终端可见）
- 用法：
    from logger import log_event, Timer, get_recent_logs
    log_event("vl_attempt_done", attempt=1, elapsed=3.21, content_len=120)
    t = Timer(); ... ; t.elapsed()  -> 3.21（秒，两位小数）
    get_recent_logs(200)            -> 最近 200 行日志文本
"""
import logging
import os
import time
from logging.handlers import TimedRotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 日志级别：优先 .env 的 LOG_LEVEL，默认 INFO
_LEVEL = "INFO"
try:
    from config import cfg as _cfg
    _LEVEL = _cfg.LOG_LEVEL
except Exception:
    pass

logger = logging.getLogger("medbutler")
logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
logger.propagate = False

if not logger.handlers:  # 防止 uvicorn --reload 重复挂 handler
    _fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)

    _fh = TimedRotatingFileHandler(
        os.path.join(LOG_DIR, "medbutler.log"),
        when="midnight", backupCount=14, encoding="utf-8",
    )
    _fh.suffix = "%Y%m%d"
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)


def log_event(event, level="info", **fields):
    """记录一条结构化事件：事件名 | key=value | ..."""
    parts = [event]
    for k, v in fields.items():
        if isinstance(v, float):
            v = f"{v:.2f}"
        parts.append(f"{k}={v}")
    msg = " | ".join(str(p) for p in parts)
    lv = level if level in ("info", "warning", "error", "debug") else "info"
    getattr(logger, lv)(msg)


class Timer:
    """简易计时器：t = Timer(); ... ; t.elapsed() -> 秒（float）"""

    def __init__(self):
        self._start = time.perf_counter()

    def elapsed(self):
        return time.perf_counter() - self._start


def get_recent_logs(lines=200):
    """读取当前日志文件最后 N 行，供 /logs 端点展示。"""
    path = os.path.join(LOG_DIR, "medbutler.log")
    if not os.path.exists(path):
        return "(暂无日志)"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = "".join(f.readlines()[-max(1, int(lines)):])
            return content if content.strip() else "(暂无日志)"
    except OSError as e:
        return f"(读取日志失败: {e})"
