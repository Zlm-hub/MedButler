from fastapi import FastAPI, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Annotated
from PIL import Image
import base64
import io


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
    return {
        "original_file_size": len(files[0]),
        "resized_file_size": resized_image.getbuffer().nbytes,
        "message": "Image resized successfully",
        "base64ed_image": base64_image,
    }

# 挂载静态文件目录
app.mount("/", StaticFiles(directory="static"), name="static")