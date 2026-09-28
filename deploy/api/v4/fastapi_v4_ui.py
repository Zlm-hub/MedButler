from fastapi import FastAPI, File, HTTPException
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from PIL import Image
import base64
import io
import re
import httpx

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

app = FastAPI()

@app.post("/image")
@app.post("/image/")
async def analyze_image(files: Annotated[list[bytes], File()]):
    # print(files[0])
    if len(files[0]) <= 100:
        return {"error": "No image file provided"}
    resized_image = resize_image(io.BytesIO(files[0]), max_size=1280)
    base64_image = encode_image_to_base64(resized_image)
    
    async def _call_model(payload):
        # 每次调用使用全新连接：llama.cpp 在多模态请求之后的复用连接上会返回 404
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post("http://127.0.0.1:8080/v1/chat/completions", json=payload)
            resp.raise_for_status()
            return resp.json()

    # 调用 VL 模型（多模态）—— 获取图像摘要
    # 思考型模型：VL 必须开思考才能准确读图；但 content 偶尔为空或开头是「分析/解读」等思考废话。
    # 故带重试：优先取干净 content，异常则换温度重试；最后再做结论提纯。
    try:
        vl_text_prompt = "请直接给出这张医学检测报告图片的异常指标结论：列出指标名、数值及偏高/偏低，无异常则说明未发现异常指标。只输出结论，不要分析过程。"
        raw_summary = ""
        for attempt in range(3):
            vl_payload = {
                "model": "medmodelvl",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": vl_text_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                        ]
                    }
                ],
                "max_tokens": 4096,
                "temperature": 0.0 if attempt == 0 else 0.3
            }
            vl_result = await _call_model(vl_payload)
            _vm = vl_result["choices"][0]["message"]
            _c = (_vm.get("content") or "").strip()
            _rc = (_vm.get("reasoning_content") or "").strip()
            # 干净正文：非空且开头不是思考/分析废话
            if _c and not re.match(r"^(分析|解读|首先|思考|好的|用户|根据|让我)", _c[:10]):
                raw_summary = _c
                break
            if attempt == 2:  # 最后一次兜底：用 reasoning 也行
                raw_summary = _rc or _c

        summary = clean_analysis(raw_summary)

        # 调用 LLM —— 基于摘要生成建议
        llm_payload = {
            "model": "medmodelvl",
            "messages": [
                {
                    "role": "user",
                    "content": f"基于以下异常指标结论，用简洁中文分点给出饮食、运动、生活方式方面的健康建议：\n\n{summary}\n\n只输出建议。"
                }
            ],
            # "stop": ["<|eot_id|>"],
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": 2048,
            "temperature": 0.6,
            "repeat_penalty": 1.2
        }

        llm_result = await _call_model(llm_payload)
        _lm = llm_result["choices"][0]["message"]
        suggestion = (_lm.get("content") or _lm.get("reasoning_content") or "").strip()
        suggestion = suggestion.replace("<|eot_id|>", "")

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to call downstream model service: {str(e)}"
        )
    except KeyError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected response format from model service: missing {e}"
        )

    return {
        "original_file_size": len(files[0]),
        "resized_file_size": resized_image.getbuffer().nbytes,
        # "message": "Image resized successfully",
        # "base64ed_image": base64_image,
        "analysis_result": summary,
        "health_recommendations": suggestion,
    }

# 挂载静态文件目录
app.mount("/", StaticFiles(directory="ui", html=True), name="ui")