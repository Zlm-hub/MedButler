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

# 病理/诊断类关键词：命中说明报告含疾病诊断，走病理提纯分支
_PATHOLOGY_KW = re.compile(
    r"(癌|肿瘤|恶性|良性|分化|浸润|转移|病灶|结节|增生|息肉|囊肿|溃疡|糜烂|狭窄|反流"
    r"|切缘|淋巴结|气道播散|贴壁|微乳头|腺癌|鳞癌|感染|病变|梗死|梗阻|结石|坏死)"
)
_NO_FINDING_KW = re.compile(r"(未见异常|未发现异常|未发现明显异常|各项指标正常|指标均正常|一切正常|均正常)")

def clean_analysis(text):
    """
    从 VL 输出中提纯「关键结论」：
    - 检验报告：保留含方向词(偏高/偏低/↑↓/异常等)且带数值的关键行
    - 病理/诊断报告：保留含病理关键词的诊断行（无数值也保留）
    - 「未见异常」类短句只有在全文无病理关键词时才直接采信（防止把确诊报告读成无异常）
    """
    if not text:
        return text
    has_pathology = bool(_PATHOLOGY_KW.search(text))
    # 未见异常/均正常 类结论：全文无病理关键词时，取首个含该结论的短句直接返回
    if not has_pathology and _NO_FINDING_KW.search(text):
        for seg in re.split(r"[\n。；;]", text):
            if _NO_FINDING_KW.search(seg):
                return seg.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    kept = []
    for l in lines:
        # 带方向词且含数值 -> 异常指标行；含病理关键词 -> 病理诊断行
        if (re.search(r"(偏高|偏低|异常|↑|↓|高于|低于|超出|超标|增高|降低|升高|下降)", l) and re.search(r"\d", l)) \
                or _PATHOLOGY_KW.search(l):
            kept.append(l)
    if kept:
        return "\n".join(kept)
    # 提纯失败（如模型只列出数值未给方向）：best-effort 返回原文，避免丢结果
    return text.strip()

def _clean_content_ok(text):
    """content 干净正文判断：非空且开头不是思考/分析废话"""
    return bool(text and not re.match(r"^(分析|解读|首先|思考|好的|用户|根据|让我)", text[:10]))

def _vl_temperature(attempt):
    """读图温度阶梯：首次 0.0（稳定），重试逐次升温打破复读循环"""
    if attempt == 0:
        return 0.0
    return min(1.0, cfg.VL_RETRY_TEMPERATURE + 0.3 * (attempt - 1))

def _thinking_looped(text):
    """思考复读检测：最近 400 字内同一 >=16 字片段出现 >=3 次判定为循环"""
    if len(text) < 120:
        return False
    tail = text[-400:]
    frag_len = 16
    for i in range(0, len(tail) - frag_len + 1, 8):
        if tail.count(tail[i:i + frag_len]) >= 3:
            return True
    return False

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
                log_event(f"收到无效请求：文件过小（{len(files[0])} 字节），已拒绝", level="warning")
                yield emit({"stage": "error", "detail": "No image file provided"})
                return

            log_event(f"收到分析请求：原图 {len(files[0]) / 1024:.0f} KB，开始全流程处理")

            t_resize = Timer()
            resized_image = resize_image(io.BytesIO(files[0]), max_size=cfg.IMAGE_MAX_SIZE)
            base64_image = encode_image_to_base64(resized_image)
            log_event(
                f"图片预处理完成：{len(files[0]) / 1024:.0f} KB → {resized_image.getbuffer().nbytes / 1024:.0f} KB"
                f"（base64 {len(base64_image)} 字符），耗时 {t_resize.elapsed():.2f}s"
            )
            yield emit({
                "stage": "start",
                "original_size": len(files[0]),
                "resized_size": resized_image.getbuffer().nbytes,
            })

            # ---------- VL（多模态，开思考）流式 + 重试 ----------
            vl_text_prompt = (
                "解读这张医学报告图片。先判断报告类型，再严格按对应格式输出，"
                "禁止输出任何分析、思考或解读过程。\n"
                "一、若这是检验报告（化验单，含数值指标和参考值区间），每行一条异常指标，格式固定为：\n"
                "- 指标名：数值（参考值区间）偏高\n"
                "- 指标名：数值（参考值区间）偏低\n"
                "二、若这是病理报告或诊断报告（以文字诊断为主，通常无数值指标），"
                "把报告里的关键信息逐条列出，每行一条，格式固定为：\n"
                "- 诊断：<报告中的疾病/病变诊断原文，有几个列几个>\n"
                "- 关键发现：<切缘、淋巴结、分化程度、浸润程度、气道播散等任何重要信息>\n"
                "注意：只要图片中出现任何疾病诊断（如肿瘤、癌、结节、感染、病变等），"
                "严禁输出「未发现异常指标」。\n"
                "三、仅当图片既无数值异常、也无任何疾病诊断时，才只输出一句话：未发现异常指标。"
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
                    "temperature": _vl_temperature(attempt),
                    "repeat_penalty": cfg.VL_REPEAT_PENALTY,
                    "repeat_last_n": cfg.VL_REPEAT_LAST_N,
                    "frequency_penalty": cfg.VL_FREQUENCY_PENALTY,
                    "stream": True,
                }
                log_event(
                    f"第 {attempt + 1} 次读图开始：温度 {vl_payload['temperature']:.2f}，"
                    f"max_tokens={cfg.VL_MAX_TOKENS}（流式，开思考）"
                )
                t_vl = Timer()
                reasoning_parts, content_parts = [], []
                reasoning_acc, loop_aborted = "", False
                try:
                    # 每次调用使用全新连接：llama.cpp 在多模态请求之后的复用连接上会返回 404
                    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                        async with client.stream("POST", f"{LLM_BASE_URL}/v1/chat/completions", json=vl_payload) as resp:
                            resp.raise_for_status()
                            async for rc, cc in _iter_sse_lines(resp):
                                if rc:
                                    reasoning_parts.append(rc)
                                    reasoning_acc += rc
                                    if _thinking_looped(reasoning_acc):
                                        # 复读循环：立即断开，不再等它烧完 4096 tokens
                                        loop_aborted = True
                                        log_event(
                                            f"第 {attempt + 1} 次读图思考陷入复读循环，提前中断"
                                            f"（耗时 {t_vl.elapsed():.2f}s，已产出思考 {len(reasoning_acc)} 字）",
                                            level="warning",
                                        )
                                        break
                                    # 思考过程实时推给前端（浅色展示）
                                    yield emit({"stage": "vl_thinking", "attempt": attempt, "text": rc})
                                if cc:
                                    content_parts.append(cc)
                                    yield emit({"stage": "analysis_delta", "attempt": attempt, "text": cc})
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    log_event(
                        f"读图调用失败（VL 服务，第 {attempt + 1} 次，耗时 {t_vl.elapsed():.2f}s）：{e!r}",
                        level="error",
                    )
                    if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                        yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "network"})
                        continue
                    yield emit({"stage": "error", "detail": f"Failed to call model service: {e}"})
                    return

                _rc = "".join(reasoning_parts).strip()
                _c = "".join(content_parts).strip()

                # 复读被掐断：重试换温度，最后一次则只信正文（思考是垃圾复读）
                if loop_aborted:
                    if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                        log_event(
                            f"准备第 {attempt + 2} 次重试（换温度 {_vl_temperature(attempt + 1):.2f}）",
                            level="warning",
                        )
                        yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "think loop"})
                        continue
                    log_event("已用完全部尝试且思考均循环，只取正文兜底", level="warning")
                    raw_summary = _c
                    break

                accepted = _clean_content_ok(_c)
                verdict = "采纳" if accepted else "结论不干净，不采纳"
                log_event(
                    f"第 {attempt + 1} 次读图结束：耗时 {t_vl.elapsed():.2f}s，"
                    f"思考 {len(_rc)} 字 / 结论 {len(_c)} 字 → {verdict}"
                )
                if accepted:
                    raw_summary = _c
                    break
                if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                    # 本次未采纳：前端清空半成品结论后重试
                    log_event(
                        f"准备第 {attempt + 2} 次重试（换温度 {_vl_temperature(attempt + 1):.2f}）",
                        level="warning",
                    )
                    yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "content not clean"})
                else:
                    log_event(f"已用完 {cfg.VL_MAX_ATTEMPTS} 次尝试，用最后一次输出兜底", level="warning")
                    raw_summary = _rc or _c  # 最后一次兜底：用思考内容也行

            summary = clean_analysis(raw_summary)
            log_event(f"结论提纯完成：原文 {len(raw_summary)} 字 → 提纯后 {len(summary)} 字")
            # 定格分析区（前端用此最终版覆盖增量）
            yield emit({"stage": "analysis", "data": summary})

            # ---------- LLM（无图，关思考）流式生成建议 ----------
            llm_user_prompt = (
                "你是专业的健康顾问。基于下面的报告分析结论，判断结论类型并严格按对应 Markdown 格式输出，"
                "除该格式外不要输出任何其他文字（不要开头语、不要总结语、不要复述结论）：\n\n"
                "一、若结论包含病理/诊断信息（如肿瘤、癌、结节、病灶、切缘、淋巴结等），按此格式输出：\n"
                "### 诊断解读\n"
                "- 用通俗语言解释每条诊断的含义\n\n"
                "### 需要关注的点\n"
                "- 指出结论中的风险因素或积极因素（如分化程度、转移情况、切缘状态）\n\n"
                "### 后续建议\n"
                "- 就诊科室、复查方向等，并提醒以主治医生意见为准\n\n"
                "二、若结论仅为化验指标异常（偏高/偏低），按此格式输出：\n"
                "### 饮食建议\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "### 运动建议\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "### 生活方式\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "三、若结论为「未发现异常指标」，则只输出一句话说明各项指标正常、保持现有健康习惯即可，"
                "不要输出上述任何格式。\n\n"
                f"报告分析结论：\n{summary}"
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
            log_event(f"健康建议生成开始：关思考，max_tokens={cfg.LLM_MAX_TOKENS}（流式）")
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
                log_event(
                    f"建议生成调用失败（LLM 服务，耗时 {t_llm.elapsed():.2f}s）：{e!r}",
                    level="error",
                )
                yield emit({"stage": "error", "detail": f"Failed to call model service: {e}"})
                return

            suggestion = "".join(suggestion_parts).strip().replace("<|eot_id|>", "")
            log_event(f"健康建议生成完成：耗时 {t_llm.elapsed():.2f}s，长度 {len(suggestion)} 字")

            yield emit({"stage": "recommendations", "data": suggestion})
            log_event(
                f"请求处理完成：总耗时 {t_total.elapsed():.2f}s"
                f"（结论 {len(summary)} 字 / 建议 {len(suggestion)} 字）"
            )
            yield emit({"stage": "done", "total_elapsed": round(t_total.elapsed(), 2)})

        except Exception as e:  # 任何未预期异常也以事件形式告知前端
            log_event(f"请求处理异常：{e!r}（总耗时 {t_total.elapsed():.2f}s）", level="error")
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
