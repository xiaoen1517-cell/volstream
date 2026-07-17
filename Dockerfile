FROM python:3.11-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 确保项目结构完整，并验证 Python 语法
ENV PYTHONPATH=/app
RUN python -m compileall src/

# 默认命令：启动实时分析（可通过 docker-compose 覆盖）
CMD ["python", "main.py", "run", "--symbol", "BTC/USDT"]
