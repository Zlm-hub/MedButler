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

def _vl_temperature(attempt):
    """读图温度阶梯：首次 0.0（稳定），重试逐次升温打破复读循环"""
    if attempt == 0:
        return 0.0
    return min(1.0, cfg.VL_RETRY_TEMPERATURE + 0.3 * (attempt - 1))

def _repetition_looped(text):
    """复读检测（思考段/建议段通用），命中任一规则判定为循环：
    规则1（句级循环）：最近 400 字内同一 >=16 字片段出现 >=3 次
    规则2（词汤/变体循环）：最近 400 字的 4-gram 唯一率 < 0.55（正常文本通常 >0.85）"""
    if len(text) < 120:
        return False
    tail = text[-400:]
    # 规则1：句级精确循环
    frag_len = 16
    for i in range(0, len(tail) - frag_len + 1, 8):
        if tail.count(tail[i:i + frag_len]) >= 3:
            return True
    # 规则2：4-gram 重复率（每次变几个字的「词汤」循环，规则1 抓不住）
    grams = [tail[i:i + 4] for i in range(0, len(tail) - 3)]
    if len(grams) >= 100 and len(set(grams)) / len(grams) < 0.55:
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

            # ---------- VL（多模态，关思考）纯转录：B 方案第一段 ----------
            # 实测结论：4B 量化模型做"解读式"读图易幻觉/循环，做"转录式"读图又快又准；
            # 解读全部交给第二段纯文字 LLM，各干各的强项
            vl_text_prompt = "把这张医学报告图片里的所有文字原样抄录出来，不要解读、不要总结，只抄录。"
            transcript = ""
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
                    "chat_template_kwargs": {"enable_thinking": False},
                    "stream": True,
                }
                log_event(
                    f"第 {attempt + 1} 次报告转录开始：温度 {vl_payload['temperature']:.2f}，"
                    f"max_tokens={cfg.VL_MAX_TOKENS}（流式，关思考）"
                )
                t_vl = Timer()
                content_parts, content_acc = [], ""
                loop_aborted = False
                try:
                    # 每次调用使用全新连接：llama.cpp 在多模态请求之后的复用连接上会返回 404
                    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                        async with client.stream("POST", f"{LLM_BASE_URL}/v1/chat/completions", json=vl_payload) as resp:
                            resp.raise_for_status()
                            async for rc, cc in _iter_sse_lines(resp):
                                if cc:
                                    content_parts.append(cc)
                                    content_acc += cc
                                    if _repetition_looped(content_acc):
                                        # 复读循环：立即断开，不再等它烧完 max_tokens
                                        loop_aborted = True
                                        log_event(
                                            f"第 {attempt + 1} 次报告转录陷入复读循环，提前中断"
                                            f"（耗时 {t_vl.elapsed():.2f}s，已产出 {len(content_acc)} 字）",
                                            level="warning",
                                        )
                                        break
                                    # 转录内容实时推给前端分析区
                                    yield emit({"stage": "analysis_delta", "attempt": attempt, "text": cc})
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    log_event(
                        f"转录调用失败（VL 服务，第 {attempt + 1} 次，耗时 {t_vl.elapsed():.2f}s）：{e!r}",
                        level="error",
                    )
                    if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                        yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "network"})
                        continue
                    yield emit({"stage": "error", "detail": f"Failed to call model service: {e}"})
                    return

                _c = "".join(content_parts).strip()

                if loop_aborted:
                    if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                        log_event(
                            f"准备第 {attempt + 2} 次重试（换温度 {_vl_temperature(attempt + 1):.2f}）",
                            level="warning",
                        )
                        yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "loop"})
                        continue
                    log_event("已用完全部尝试且均循环，只取已产出正文兜底", level="warning")
                    transcript = _c
                    break

                if _c:
                    transcript = _c
                    log_event(f"第 {attempt + 1} 次报告转录结束：耗时 {t_vl.elapsed():.2f}s，转录 {len(_c)} 字 → 采纳")
                    break
                log_event(
                    f"第 {attempt + 1} 次报告转录为空：耗时 {t_vl.elapsed():.2f}s，重试或兜底",
                    level="warning",
                )
                if attempt < cfg.VL_MAX_ATTEMPTS - 1:
                    yield emit({"stage": "vl_retry", "attempt": attempt + 1, "reason": "empty"})
                else:
                    transcript = _c

            if not transcript.strip():
                # 空转录不该继续：拿空输入生成建议只会产出垃圾
                log_event("转录失败：所有尝试均未产出有效内容，不生成建议", level="error")
                yield emit({
                    "stage": "error",
                    "detail": "未能识别这张报告的内容（模型连续多次无法稳定读图）。请重试，或上传更清晰、光线更好的照片。",
                })
                return
            # 定格分析区：转录原文（markdown 硬换行保持行结构），前端用此最终版覆盖增量
            yield emit({"stage": "analysis", "data": transcript.replace("\n", "  \n")})

            # ---------- LLM（无图，关思考）流式生成解读与建议 ----------
            # 实测结论：4B 模型长文生成是塌缩重灾区，解读任务必须限制篇幅（200 字内），
            # 让模型"先说诊断→再说好消息→再说风险→提醒遵医嘱"的短输出又快又准
            llm_user_prompt = (
                "你是专业的健康顾问。下面是一张医学报告的原文转录，请判断报告类型并按要求输出，"
                "不要输出任何思考过程：\n\n"
                "一、若这是病理/影像/诊断类报告（含诊断意见、影像所见、检查结论等）："
                "用不超过200字向患者通俗解读——先说最重要的诊断，再说好消息（哪些结果是有利的），"
                "再说需要警惕的风险，最后一句提醒遵医嘱。\n\n"
                "二、若这是化验单且存在异常指标（偏高/偏低），严格按此 Markdown 格式输出：\n"
                "### 饮食建议\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "### 运动建议\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "### 生活方式\n"
                "- 要点一\n"
                "- 要点二\n\n"
                "三、若这是化验单且所有指标均在正常范围，只输出一句话说明各项指标正常、"
                "保持现有健康习惯即可。\n\n"
                f"报告原文转录：\n{transcript}"
            )
            suggestion = ""
            for llm_attempt in range(cfg.LLM_MAX_ATTEMPTS):
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
                    "temperature": cfg.LLM_TEMPERATURE + 0.3 * llm_attempt,
                    "repeat_penalty": cfg.LLM_REPEAT_PENALTY,
                    "repeat_last_n": cfg.LLM_REPEAT_LAST_N,
                    "frequency_penalty": cfg.LLM_FREQUENCY_PENALTY,
                    "stream": True,
                }
                log_event(
                    f"健康建议生成开始（第 {llm_attempt + 1} 次）：关思考，"
                    f"温度 {llm_payload['temperature']:.2f}，max_tokens={cfg.LLM_MAX_TOKENS}（流式）"
                )
                t_llm = Timer()
                suggestion_parts, suggestion_acc = [], ""
                llm_looped = False
                try:
                    async with httpx.AsyncClient(timeout=STREAM_TIMEOUT) as client:
                        async with client.stream("POST", f"{LLM_BASE_URL}/v1/chat/completions", json=llm_payload) as resp:
                            resp.raise_for_status()
                            async for rc, cc in _iter_sse_lines(resp):
                                if cc:
                                    suggestion_parts.append(cc)
                                    suggestion_acc += cc
                                    if _repetition_looped(suggestion_acc):
                                        llm_looped = True
                                        log_event(
                                            f"健康建议生成陷入复读循环，提前中断"
                                            f"（第 {llm_attempt + 1} 次，耗时 {t_llm.elapsed():.2f}s，已产出 {len(suggestion_acc)} 字）",
                                            level="warning",
                                        )
                                        break
                                    yield emit({"stage": "recommendations_delta", "text": cc})
                except (httpx.RequestError, httpx.HTTPStatusError) as e:
                    log_event(
                        f"建议生成调用失败（LLM 服务，耗时 {t_llm.elapsed():.2f}s）：{e!r}",
                        level="error",
                    )
                    yield emit({"stage": "error", "detail": f"Failed to call model service: {e}"})
                    return

                suggestion = "".join(suggestion_parts).strip().replace("<|eot_id|>", "")
                if not llm_looped:
                    break
                if llm_attempt < cfg.LLM_MAX_ATTEMPTS - 1:
                    log_event(
                        f"准备第 {llm_attempt + 2} 次重试（换温度 {cfg.LLM_TEMPERATURE + 0.3 * (llm_attempt + 1):.2f}）",
                        level="warning",
                    )
                    yield emit({"stage": "recommendations", "data": ""})  # 清空前端半成品建议
                else:
                    log_event("健康建议多次重试仍复读，放弃本次生成", level="error")
                    yield emit({"stage": "error", "detail": "健康建议生成异常，请重试"})
                    return

            log_event(f"健康建议生成完成：耗时 {t_llm.elapsed():.2f}s，长度 {len(suggestion)} 字")

            yield emit({"stage": "recommendations", "data": suggestion})
            log_event(
                f"请求处理完成：总耗时 {t_total.elapsed():.2f}s"
                f"（转录 {len(transcript)} 字 / 建议 {len(suggestion)} 字）"
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
