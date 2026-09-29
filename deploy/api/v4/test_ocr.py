"""
直接测 llama-server 的读图转录能力（绕过 v4，隔离变量）
用法：
    python test_ocr.py <图片路径> [最长边像素，默认1280]

在 1280/1600/2048 下分别测出「纯转录」质量，判断病理报告读不出是
分辨率问题（→ 调 IMAGE_MAX_SIZE / B 方案有救）还是模型能力边界（→ 只能 C 方案微调）。
"""
import base64
import io
import json
import sys

import httpx
from PIL import Image

BASE_URL = "http://127.0.0.1:8080"
MODEL = "medmodelvl"


def resize_and_encode(image_path: str, max_size: int) -> str:
    img = Image.open(image_path)
    w, h = img.size
    if max(w, h) > max_size:
        if w >= h:
            nw = max_size
            nh = int(h * (nw / w))
        else:
            nh = max_size
            nw = int(w * (nh / h))
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    if img.mode != "RGB":
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    print(f"[缩放后] {img.size[0]}x{img.size[1]}，JPEG {buf.getbuffer().nbytes // 1024} KB")
    return base64.b64encode(buf.getvalue()).decode()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    image_path = sys.argv[1]
    max_size = int(sys.argv[2]) if len(sys.argv) > 2 else 1280

    b64 = resize_and_encode(image_path, max_size)
    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "把这张图片里的所有文字原样抄录出来，不要解读、不要总结，只抄录。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
        "max_tokens": 2048,
        "temperature": 0.0,
        "repeat_penalty": 1.1,
        "repeat_last_n": 256,
        "stream": False,
    }

    print(f"[测试] 分辨率上限 {max_size}px，纯转录任务，贪心解码...")
    with httpx.Client(timeout=httpx.Timeout(connect=10, read=600, write=120, pool=10)) as client:
        resp = client.post(f"{BASE_URL}/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
    msg = data["choices"][0]["message"]
    reasoning = (msg.get("reasoning_content") or "").strip()
    content = (msg.get("content") or "").strip()
    print(f"\n===== 思考（{len(reasoning)} 字，前 500 字）=====")
    print(reasoning[:500] or "(空)")
    print(f"\n===== 转录正文（{len(content)} 字）=====")
    print(content or "(空)")


if __name__ == "__main__":
    main()
