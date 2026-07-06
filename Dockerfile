# Hugging Face Spaces 用 Docker 运行本应用
FROM python:3.11-slim

WORKDIR /app

# 先装后端依赖（利用缓存）；pip 走阿里云源——阿里云服务器直连 PyPI 会超时
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com -r backend/requirements.txt

# 复制全部代码（含已打包的 frontend/dist）
COPY . .

# HF Spaces 默认对外端口为 7860
EXPOSE 7860

WORKDIR /app/backend
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
