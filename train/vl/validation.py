import base64
import requests
import json
import os
from PIL import Image
import io

# 验证改这里 4-1
API_KEY = "EMPTY"

def encode_image(image_path):
    # 打开图像并等比缩放至最长边不超过1280
    with Image.open(image_path) as img:
        # 获取原始尺寸
        width, height = img.size
        max_dimension = max(width, height)
        
        # 如果最长边超过1280，则进行缩放
        if max_dimension > 1280:
            # 计算缩放比例
            scale = 1280 / max_dimension
            new_width = int(width * scale)
            new_height = int(height * scale)
            
            # 等比缩放图像
            img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        
        # 将图像转换为base64
        buffered = io.BytesIO()
        img.save(buffered, format=img.format or 'JPEG')
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

image_path = "./test-img/scan_item10-_69.jpg"
# image_path = "./test-img/scan_item10-_72.jpg"
# image_path = "./test-img/scan_item10-_71.jpg"

base64_image = encode_image(image_path)
print(base64_image)

response = requests.post(
    # 验证改这里 4-2
    url="http://127.0.0.1:8000/v1/chat/completions",
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    data=json.dumps({
        # 验证改这里 4-3
        "model": "/root/autodl-tmp/qwen35-4b-med-vl",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "解读这个医学报告，一句话指出其中异常指标"
                    },
                    # 验证改这里 4-4
                    # {
                    #     "type": "image_url",
                    #     "image_url": {
                    #         "url": "https://www.familyhandyman.com/wp-content/uploads/2018/02/handcrafted-log-home.jpg"
                    #     }
                    # },
                    {
                        ## OpenAI 文档地址 https://platform.openai.com/docs/guides/images-vision
                        ## 文档里 type 用的是 input_image，但不要用

                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpg;base64,{base64_image}",
                        },
                    }
                ]
            }
        ],
    })
)

result = response.json()
print(result)
output = result["choices"][0]["message"]["content"]
print(output)