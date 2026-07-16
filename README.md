# VolStream

聚焦短期趋势的加密货币量价与订单流分析工具。

## 主要功能

- 支持 15m / 1h / 4h 三个周期 K 线分析。
- 每个 K 线周期计算 10 个量价指标：EMA12/26、MACD、RSI14、VWAP、OBV、Delta、CVD、ATR。
- WebSocket 实时接收成交数据，计算 Volume Profile（POC / Value Area）。
- 大额订单（Whale）与冰山订单（Iceberg）迹象检测。
- 三周期共振加权，输出统一趋势信号。
- 使用 PostgreSQL + TimescaleDB 持久化 K 线与分析结果，默认保留 30 天。

## 本地快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 复制环境变量
cp .env.example .env

# 3. 启动数据库
docker-compose up -d

# 4. 初始化表结构
python main.py init-db

# 5. 同步最近 30 天历史 K 线
python main.py sync --symbol BTC/USDT

# 6. 启动实时分析
python main.py run --symbol BTC/USDT
```

## 测试

```bash
pytest
```

数据库相关测试默认跳过，需要 PostgreSQL/TimescaleDB 时设置：

```bash
SKIP_DB_TESTS=0 pytest
```

## 生产部署（GitHub Actions + 自有服务器）

### 服务器首次准备

1. 在服务器上克隆仓库：

```bash
git clone https://github.com/<your-username>/volstream.git /opt/volstream
cd /opt/volstream
```

2. 服务器必须安装 Docker 与 Docker Compose。

3. 可选：在服务器上手动放置 `.env` 文件，后续由 GitHub Actions 自动覆盖。

### 配置 GitHub Secrets

在仓库 `Settings -> Secrets and variables -> Actions` 中添加：

| Secret | 说明 |
|--------|------|
| `SSH_PRIVATE_KEY` | 部署服务器的 SSH 私钥 |
| `SSH_HOST` | 服务器 IP 或域名 |
| `SSH_USER` | SSH 用户名 |
| `SSH_PORT` | SSH 端口（可选，默认 22） |
| `PROJECT_DIR` | 服务器上的项目目录（可选，默认 `/opt/volstream`） |
| `ENV_FILE` | 生产环境完整的 `.env` 文件内容 |

### 部署触发

- 每次 `push` 到 `main` 分支会自动运行测试并部署。
- 也可在 GitHub Actions 页面手动触发 `workflow_dispatch`。

### 部署流程

1. GitHub Actions 运行单元测试。
2. 通过 SSH 连接服务器，拉取最新代码。
3. 将 `ENV_FILE` 写入服务器 `.env`。
4. 执行 `docker-compose up -d --build` 重建并启动服务。
5. 执行 `python main.py init-db` 确保表结构最新。
6. 清理旧 Docker 镜像。

## 服务器配置建议

详见计划文件中的「服务器部署配置建议」章节。

- 1-3 个交易对：2C4G + 50GB SSD
- 5-10 个交易对：4C8G + 100GB SSD
- 10+ 交易对：独立数据库服务器
