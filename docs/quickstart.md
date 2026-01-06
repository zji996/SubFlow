# Quickstart (本地开发)

> 说明：本项目 Python 部分统一用 `uv`；本节只说明一键启动，不展开 Docker/服务依赖细节。

## 前置条件

- 已安装 `uv`
- 已安装 Node.js（用于 `apps/web`）
- 依赖服务（Redis / MinIO / Postgres 等）请自行用 Docker 启动（例如 `infra/docker-compose.dev.yml`）
- 如果你用 Docker 在 `./data/` 下跑了 Postgres/MinIO，`data/` 可能会被 root 占用；建议为 SubFlow 单独建一个可写目录并在 `.env` 里设置 `DATA_DIR=./data/subflow`
- Worker 使用 `demucs/torch`（需要 GPU 的工作都在 worker），建议安装并使用 Python 3.13：`uv python install 3.13`

## 一键启动（推荐）

在仓库根目录运行：

```bash
bash scripts/manager.sh up
```

默认端口：

- API: `http://localhost:8100`（Swagger: `http://localhost:8100/docs`）
- Web: `http://localhost:5173`

日志与 PID：

- 日志：`logs/api.log`、`logs/worker.log`、`logs/web.log`
- PID：`logs/api.pid`、`logs/worker.pid`、`logs/web.pid`

## 常用命令

```bash
# 查看状态
bash scripts/manager.sh status

# 停止全部
bash scripts/manager.sh down

# 只启动 API
bash scripts/manager.sh up api

# 自定义端口
bash scripts/manager.sh up --api-port 8100 --web-port 5173
```

## 提交任务（可选）

```bash
curl -X POST "http://localhost:8100/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Video",
    "media_url": "s3://bucket/path/to/video.mp4",
    "target_language": "zh",
    "language": "en"
  }'
```
