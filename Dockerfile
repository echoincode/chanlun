# 缠论K线分析工具 Docker 镜像
FROM python:3.12-slim

# 安装 tzdata 并锁定时区为 Asia/Shanghai（日志与页面时间展示依赖本地时区）
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

# 设置环境变量，避免交互提示
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai \
    CHANLUN_LOG_LEVEL=INFO

WORKDIR /app

# 先复制依赖文件，利用 Docker 层缓存
#   --only-binary=:all:  : 强制使用 wheel，避免源码编译（更快、更稳）
#   --no-cache-dir       : 不落 pip 缓存，减少层体积
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --only-binary=:all: -r requirements.txt

# 复制项目源码
COPY . .

# 暴露 Streamlit 默认端口
EXPOSE 8501

# 默认启动 Web 界面（可通过 docker-compose 或 command 覆盖为 CLI）
#   --server.headless=true       容器内无显示，避免尝试调起浏览器
#   --browser.gatherUsageStats=false  关闭匿名统计与首次邮箱注册提示
CMD ["streamlit", "run", "web/app.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
