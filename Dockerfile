# 缠论K线分析工具 Docker 镜像
FROM python:3.11-slim

# 设置环境变量，避免交互提示
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TUSHARE_TOKEN="" \
    CHANLUN_LOG_LEVEL=INFO

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 复制项目源码
COPY . .

# 暴露 Streamlit 默认端口
EXPOSE 8501

# 默认启动 Web 界面（可通过 docker-compose 或 command 覆盖为 CLI）
CMD ["streamlit", "run", "web/app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501"]
