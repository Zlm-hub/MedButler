from fastapi import FastAPI, File, HTTPException
from fastapi.staticfiles import StaticFiles
from typing import Annotated
from PIL import Image
import base64
import io
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

app = FastAPI()

@app.post("/image/")
async def analyze_image(files: Annotated[list[bytes], File()]):
    # print(files[0])
    if len(files[0]) <= 100:
        return {"error": "No image file provided"}
    resized_image = resize_image(io.BytesIO(files[0]), max_size=1280)
    base64_image = encode_image_to_base64(resized_image)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            # 调用 VL 模型（多模态）—— 获取图像摘要
            vl_payload = {
                "model": "medmodelvl",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text", 
                                "text": "请仔细分析这张医学检测报告图片，识别并列出其中的异常指标。如果没有发现异常指标，请明确说明'未发现异常指标'。请以简洁、专业的中文医学术语回答。"
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                "max_tokens": 256
            }

            vl_resp = await client.post("http://127.0.0.1:8001/v1/chat/completions", json=vl_payload)
            vl_resp.raise_for_status()
            vl_result = vl_resp.json()
            summary = vl_result["choices"][0]["message"]["content"].strip()

            # 调用 LLM —— 基于摘要生成建议
            llm_payload = {
                "model": "medmodelllm",
                "messages": [
                    {
                        "role": "user",
                        "content": f"根据以下医学检测报告分析结果，提供相应的健康建议和注意事项：\n\n{summary}\n\n请以简洁明了的中文给出实用的健康建议，包括饮食、运动和生活方式等方面的指导。"
                    }
                ],
                "max_tokens": 512
            }

            llm_resp = await client.post("http://127.0.0.1:8000/v1/chat/completions", json=llm_payload)
            llm_resp.raise_for_status()
            llm_result = llm_resp.json()
            suggestion = llm_result["choices"][0]["message"]["content"].strip()

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
        "vl_summary": summary,
        "llm_suggestion": suggestion,
    }

# 挂载静态文件目录
app.mount("/", StaticFiles(directory="static"), name="static")