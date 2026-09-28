from fastapi import FastAPI, File, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

app = FastAPI()

# 挂载静态文件目录
app.mount("/", StaticFiles(directory="static"), name="static")