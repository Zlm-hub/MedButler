from fastapi import FastAPI, File
from fastapi.responses import PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from PIL import Image
import base64
import io
import json
import re
import httpx

from config import cfg
from logger import log_event, Timer, get_recent_logs

LLM_BASE_URL = cfg.LLAMA_BASE_URL
# 流式下 read 超时 = 相邻两个 chunk 的最大间隔（生成中 token 间隔很短），
# 但思考模型偶发长停顿，默认给 300s 兜底；总时长不再受固定限制
STREAM_TIMEOUT = httpx.Timeout(
    connect=cfg.STREAM_CONNECT_TIMEOUT,
    read=cfg.STREAM_READ_TIMEOUT,
    write=cfg.STREAM_WRITE_TIMEOUT,
    pool=10.0,
)

def resize_image(image_data, max_size=1280):
    """
    调整图像大小，确保最长边不超过max_size
    """
    image = Image.open(image_data)
    width, height = image.size

    if width > height:
        new_width = min(width, max_size)
        new_height = int(height * (new_width / width))
    else:
        new_height = min(height, max_size)
        new_width = int(width * (new_height / height))

    resized_image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    img_byte_arr = io.BytesIO()
    resized_image.save(img_byte_arr, format=image.format or 'JPEG')
    img_byte_arr.seek(0)

    return img_byte_arr

def encode_image_to_base64(image_file):
    """
    将图像文件编码为base64字符串
    """
    return base64.b64encode(image_file.read()).decode('utf-8')

def clean_analysis(text):
    """
    从 VL 输出中提纯「异常指标结论」：只保留含方向词(偏高/偏低/↑↓/异常等)且带数值的关键行，
    丢弃模型的思考/分析废话。若整体是「未见异常」类结论则原样返回该短句。
    """
    if not text:
        return text
    # 未见异常/均正常 类结论：取首个含该结论的短句直接返回
    if re.search(r"(未见异常|未发现异常|未发现明显异常|各项指标正常|指标均正常|一切正常|均正常)", text):
        for seg in re.split(r"[\n。；;]", text):
            if re.search(r"(未见异常|未发现异常|未发现明显异常|各项指标正常|指标均正常|一切正常|均正常)", seg):
                return seg.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    kept = []
    for l in lines:
        # 带方向词且含数值 -> 异常指标行
        if re.search(r"(偏高|偏低|异常|↑|↓|高于|低于|超出|超标|增高|降低|升高|下降|上 arrow|上抬)", l) and re.search(r"\d", l):
            kept.append(l)
    if kept:
        return "\n".join(kept)
    # 提纯失败（如模型只列出数值未给方向）：best-effort 返回原文，避免丢结果
    return text.strip()

def _clean_content_ok(text):
    """content 干净正文判断：非空且开头不是思考/分析废话"""
    return bool(text and not re.match(r"^(分析|解读|首先|思考|好的|用户|根据|让我)", text[:10]))

async def _iter_sse_lines(resp):
    """把 httpx 流式响应解析成 delta 字典序列"""
    async for line in resp.aiter_lines():
        if not line.startswith("data: "):
            continue
        data = line[len("data: "):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or [{}]
        delta = (choices[0] or {}).get("delta") or {}
        yield (delta.get("reasoning_content") or "", delta.get("content") or "")

app = FastAPI()

@app.post("/image")
@app.post("/image/")
async def analyze_image(files: Annotated[list[bytes], File()]):
    async def event_stream():
        t_total = Timer()

        def emit(obj):
            return json.dumps(obj, ensure_ascii=False) + "\n"

        try:
            if len(files[0]) <= 100:
                log_event("request_rejected", level="warning", reason="file too small", size=len(files[0]))
                yield emit({"stage": "error", "detail": "No image file provided"})
                return

            log_event("request_start", original_size=len(files[0]), stream=True)

            t_resize = Timer()
            resized_image = resize_image(io.BytesIO(files[0]), max_size=cfg.IMAGE_MAX_SIZE)
            base64_image = encode_image_to_base64(resized_image)
            log_event(
                "image_resized",
                original_size=len(files[0]),
                resized_size=resized_image.getbuffer().nbytes,
                base64_len=len(base64_image),
                elapsed=t_resize.elapsed(),
            )
            yield emit({
                "stage": "start",
                "original_size": len(files[0]),
                "resized_size": resized_image.getbuffer().nbytes,
            })

            # ---------- VL（多模态，开思考）流式 + 重试 ----------
            vl_text_prompt = (
                "解读这张医学检测报告图片，只输出异常指标结论，禁止输出任何分析、思考或解读过程。"
                "输出格式必须严格遵守：\n"
                "1) 存在异常指标时，每行一条，格式固定为：\n"
                "- 指标名：数值（参考值区间）偏高\n"
                "- 指标名：数值（参考值区间）偏低\n"
                "2) 未发现异常时，只输出一句话：未发现异常指标。"
            )
            raw_summary = ""
            for attempt in range(cfg.VL_MAX_ATTEMPTS):
                vl_payload = {
                    "model": cfg.VL_MODEL_NAME,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": vl_text_prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                            ]
                        }
                    ],
                    "max_tokens": cfg.VL_MAX_TOKENS,
                    "temperature": 0.0 if attempt == 0 else cfg.VL_RETRY_TEMPERATURE,
                    "repeat_penalty": cfg.VL_REPEAT_PENALTY,
                    "repeat_last_n": cfg.VL_REPEAT_LAST_N,
                    "stream": True,
                }
                log_event("vl_attempt_start", attempt=attempt, temperature=vl_payload["temperature"], max_tokens=cfg.VL_MAX_TOKENS, stream=True)
                t_vl = Timer()
                reasoning_parts, content_parts = [], []
                try:
                    # 每次调用使用全新连接：llama.cpp 在多模态请求之后的复用连接上会返回 404
                    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                        async with client.stream("POST", f"{LLM_BASE_URL}/v1/chat/completions", json=vl_payload) as resp:
                            resp.raise_for_status()
                            async for rc, cc in _iter_sse_lines(resp):
                                if rc:
                                    reasoning_parts.append(rc)
                                    # 思考过程实时推给前端（浅色展示）
                                    yield emit({"stage": "vl_thinking", "attempt": attempt, "text": rc})
                                if cc:
                                    content_parts.append(cc)
                                    yield emit({"stage": "analysis_delta", "attempt": attempt, "text": cc})
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    log_event("model_call_fail", level="error", endpoint="8080(stream-vl)", attempt=attempt, elapsed=t_vl.elapsed(), error=repr(e))
                    if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                        yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "network"})
                        continue
                    yield emit({"stage": "error", "detail": f"Failed to call model service: {e}"})
                    return

                _rc = "".join(reasoning_parts).strip()
                _c = "".join(content_parts).strip()
                accepted = _clean_content_ok(_c)
                log_event(
                    "vl_attempt_done",
                    attempt=attempt,
                    elapsed=t_vl.elapsed(),
                    content_len=len(_c),
                    reasoning_len=len(_rc),
                    accepted=accepted,
                )
                if accepted:
                    raw_summary = _c
                    break
                if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                    # 本次未采纳：前端清空半成品结论后重试
                    yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "content not clean"})
                else:
                    raw_summary = _rc or _c  # 最后一次兜底：用思考内容也行

            summary = clean_analysis(raw_summary)
            log_event("analysis_cleaned", raw_len=len(raw_summary), clean_len=len(summary))
            # 定格分析区（前端用此最终版覆盖增量）
            yield emit({"stage": "analysis", "data": summary})

            # ---------- LLM（无图，关思考）流式生成建议 ----------
            llm_user_prompt = (
                "你是专业的健康顾问。基于下面的异常指标结论，严格按照以下 Markdown 格式输出健康建议，"
                "除该格式外不要输出任何其他文字（不要开头语、不要总结语、不要复述指标）：\n\n"
                "### 饮食建议\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "### 运动建议\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "### 生活方式\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "若结论为「未发现异常指标」，则只输出一句话说明各项指标正常、保持现有健康习惯即可，"
                "不要输出上述三段格式。\n\n"
                f"异常指标结论：\n{summary}"
            )
            llm_payload = {
                "model": cfg.VL_MODEL_NAME,
                "messages": [
                    {
                        "role": "user",
                        "content": llm_user_prompt
                    }
                ],
                "chat_template_kwargs": {"enable_thinking": False},
                "max_tokens": cfg.LLM_MAX_TOKENS,
                "temperature": cfg.LLM_TEMPERATURE,
                "repeat_penalty": cfg.LLM_REPEAT_PENALTY,
                "stream": True,
            }
            log_event("llm_call_start", enable_thinking=False, max_tokens=cfg.LLM_MAX_TOKENS, stream=True)
            t_llm = Timer()
            suggestion_parts = []
            try:
                async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                    async with client.stream("POST", f"{LLM_BASE_URL}/v1/chat/completions", json=llm_payload) as resp:
                        resp.raise_for_status()
                        async for rc, cc in _iter_sse_lines(resp):
                            if cc:
                                suggestion_parts.append(cc)
                                yield emit({"stage": "recommendations_delta", "text": cc})
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                log_event("model_call_fail", level="error", endpoint="8080(stream-llm)", elapsed=t_llm.elapsed(), error=repr(e))
                yield emit({"stage": "error", "detail": f"Failed to call model service: {e}"})
                return

            suggestion = "".join(suggestion_parts).strip().replace("<|eot_id|>", "")
            log_event("llm_call_done", elapsed=t_llm.elapsed(), suggestion_len=len(suggestion))

            yield emit({"stage": "recommendations", "data": suggestion})
            log_event("request_done", total_elapsed=t_total.elapsed(), analysis_len=len(summary), suggestion_len=len(suggestion))
            yield emit({"stage": "done", "total_elapsed": round(t_total.elapsed(), 2)})

        except Exception as e:  # 任何未预期异常也以事件形式告知前端
            log_event("request_error", level="error", error=repr(e), total_elapsed=t_total.elapsed())
            try:
                yield emit({"stage": "error", "detail": str(e)})
            except Exception:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# 日志监控：浏览器/直接访问 /logs?lines=200 查看最近日志
@app.get("/logs", response_class=PlainTextResponse)
def recent_logs(lines: int = 200):
    return get_recent_logs(lines)

# 挂载静态文件目录
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")
