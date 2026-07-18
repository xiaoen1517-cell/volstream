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

## 生产部署（GitHub Actions + GHCR + 自有服务器）

部署流程：**本地 push 代码 → GitHub Actions 运行测试 → 构建 Docker 镜像并推送到 GHCR → SSH 到服务器拉取镜像 → docker-compose 重启服务**。

服务器上**不需要**手动 `git pull` 或 `docker build`，只需要保留 `docker-compose.yml` 与 `.env`。

### 服务器首次准备

1. 在服务器上创建项目目录：

```bash
mkdir -p /opt/volstream
cd /opt/volstream
```

2. 服务器必须安装 Docker 与 Docker Compose。

3. 手动放置初始 `docker-compose.yml`（从仓库复制 `docker-compose.prod.yml`）：

```bash
cp /path/to/volstream/docker-compose.prod.yml /opt/volstream/docker-compose.yml
```

4. 后续 `.env` 文件由 GitHub Actions 自动写入。

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

GitHub Actions 使用仓库内置的 `GITHUB_TOKEN` 登录 GHCR，无需额外配置 Token。

### 部署触发

- 每次 `push` 到 `main` 分支会自动运行测试并部署。
- 也可在 GitHub Actions 页面手动触发 `workflow_dispatch`。

### 镜像 Tag 规则

每次构建会生成两个 tag：

- `ghcr.io/<your-username>/volstream:latest`
- `ghcr.io/<your-username>/volstream:<YYYYMMDD-HHMMSS>-<short-sha>`

例如：`ghcr.io/your-username/volstream:20240716-034052-a1b2c3d`

服务器部署时使用带时间戳的 tag，`latest` 可供手动回滚或本地测试。

### 部署流程

1. GitHub Actions 运行单元测试。
2. 构建 Docker 镜像并推送到 `ghcr.io`（同时保存为 tar 包）。
3. 通过 SSH 连接服务器。
4. 将 `ENV_FILE` 写入服务器 `.env`。
5. 将 `docker-compose.prod.yml` 同步到服务器。
6. 将镜像 tar 包 `volstream-image.tar.gz` scp 到服务器。
7. 服务器执行 `gunzip -c volstream-image.tar.gz | docker load` 加载镜像。
8. 给镜像打上固定本地 tag `volstream:deployed`。
9. 执行 `docker compose up -d` 重启服务。
10. 执行 `python main.py init-db` 确保表结构最新。
11. 清理旧 Docker 镜像与 tar 包。

## 网络与交易所选择

### 交易所选择

项目默认使用 **Binance**（`config.yaml` 中 `exchange.name: binance`）。

如果你的服务器位于中国大陆，Binance WebSocket 可能无法直连，会遇到类似超时日志：

```
WebSocket 连接超时: timed out during opening handshake
```

此时可以切换到 **OKX**：

```yaml
exchange:
  name: okx
```

OKX WebSocket 在中国大陆通常比 Binance 稳定。

### 配置代理

如果仍然遇到网络问题，可以配置 SOCKS5/HTTP 代理。在 `.env` 中配置：

```env
WS_PROXY=socks5://127.0.0.1:1080
# 或 HTTP 代理
WS_PROXY=http://127.0.0.1:7890
```

代理需要在 Docker 容器内可访问（例如代理运行在宿主机上时使用宿主机的 IP）。

### 调整超时

在 `.env` 中可调整 WebSocket 连接超时：

```env
WS_OPEN_TIMEOUT=30
WS_PING_TIMEOUT=20
WS_CLOSE_TIMEOUT=10
```

## 服务器配置建议

详见计划文件中的「服务器部署配置建议」章节。

- 1-3 个交易对：2C4G + 50GB SSD
- 5-10 个交易对：4C8G + 100GB SSD
- 10+ 交易对：独立数据库服务器
