# Quickstart (本地开发)

> 说明：本项目 Python 部分统一用 `uv`；本节覆盖从启动到跑通 6 阶段 pipeline（含字幕预览）。

## 前置条件

- 已安装 `uv`
- 已安装 Node.js（用于 `apps/web`）
- 依赖服务（Redis / MinIO / Postgres 等）请自行用 Docker 启动（例如 `docker-compose -f docker-compose.dev.yml up -d`；也可使用 `infra/docker-compose.dev.yml`）
- 如果你用 Docker 在 `./data/` 下跑了 Postgres/MinIO，`data/` 可能会被 root 占用；建议为 SubFlow 单独建一个可写目录并在 `.env` 里设置 `DATA_DIR=./data/subflow`
- Worker 依赖 `demucs/torch/nemo`（需要 GPU 的工作都在 worker），建议使用 Python 3.11：`uv python install 3.11`

## 环境变量（最小）

建议在仓库根目录放一个本地 `.env`（不要提交）：

- `ASR_BASE_URL`：GLM-ASR 服务地址（默认 `http://localhost:8000/v1`）
- `ASR_API_KEY`：GLM-ASR Key（如果你的 ASR 服务需要）
- `LLM_FAST_*` / `LLM_POWER_*`：Stage 4/5 需要的 fast/power 两套 LLM 配置（见 `.env.example`）
- `VAD_NEMO_MODEL_PATH`：NeMo VAD 模型 `.nemo` 文件路径（默认会指向仓库根目录的 `models/.../*.nemo`）

可选（并发/路由，见 `.env.example`）：

- `LLM_ASR_CORRECTION` / `LLM_GLOBAL_UNDERSTANDING` / `LLM_SEMANTIC_TRANSLATION`：各阶段选择 `fast/power`
- `CONCURRENCY_ASR` / `CONCURRENCY_LLM_FAST` / `CONCURRENCY_LLM_POWER`：按服务类型设置并发
- `PARALLEL_ENABLED` / `PARALLEL_MIN_GAP_SECONDS`：基于 VAD region gap 的分区并行（Stage 4/5）

快速确认 worker 侧能找到 VAD 模型：

```bash
uv run --project apps/worker --directory apps/worker \
  python -c "from subflow.config import Settings; from pathlib import Path; s=Settings(); p=Path(s.vad.nemo_model_path); print(p); print('exists=', p.exists())"
```

## 一键启动（推荐）

在仓库根目录运行：

```bash
# 1. 启动依赖服务（如果还没启动）
cd infra && docker-compose -f docker-compose.dev.yml up -d && cd ..

# 2. 执行数据库迁移（首次或 schema 更新后）
uv run --project apps/api scripts/db_migrate.py

# 3. 启动服务
bash scripts/manager.sh up
```

默认端口：

- API: `http://localhost:8100`（Swagger: `http://localhost:8100/docs`）
- Web: `http://localhost:5173`

日志与 PID：

- 日志：`logs/api.log`、`logs/worker.log`、`logs/web.log`
- PID：`logs/api.pid`、`logs/worker.pid`、`logs/web.pid`

## 6 阶段 Pipeline（概览）

Stage 顺序与名称（结构化数据存储在 PostgreSQL，详见 `docs/database.md`）：

1. `audio_preprocess`：抽音频 + 人声分离（Demucs）→ BlobStore
2. `vad`：NeMo VAD → `vad_segments` 表（存储 `vad_regions`）
3. `asr`：分段 ASR + 合并块 ASR → `asr_segments` 表
4. `llm_asr_correction`：用合并块 ASR 纠错分段 ASR → 更新 `asr_segments.corrected_text`
5. `llm`：全局理解 + 语义切分+翻译 → `global_contexts` / `semantic_chunks` / `translation_chunks` 表
6. `export`：导出字幕（`subtitles.srt`，双行字幕）→ S3/MinIO

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

## 跑通一次（API 方式）

### 1) 创建项目

```bash
curl -X POST "http://localhost:8100/projects" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Demo Video",
    "media_url": "s3://bucket/path/to/video.mp4",
    "source_language": "en",
    "target_language": "zh",
    "auto_workflow": true
  }'
```

### 2) 执行全部阶段

将上一步返回的 `id` 替换进去：

```bash
curl -X POST "http://localhost:8100/projects/<project_id>/run-all" \
  -H "Content-Type: application/json" \
  -d '{}'
```

### 3) 查看进度

```bash
curl "http://localhost:8100/projects/<project_id>"
```

### 4) 预览字幕

```bash
curl "http://localhost:8100/projects/<project_id>/subtitles/preview?format=srt&content=both"
```

### 5) 查看 artifacts / 工作文件（可选）

Artifacts（JSON/字幕等小文件）默认走 MinIO/S3（`ARTIFACT_STORE_BACKEND=s3`），API 可直接读取：

```bash
curl "http://localhost:8100/projects/<project_id>/artifacts/export/subtitles.srt"
```

工作文件（输入视频、`audio.wav`、`vocals.wav` 等大文件）默认保留本地：

- 项目工作目录：`DATA_DIR/projects/<project_id>/`
- 内容寻址 blobs：`DATA_DIR/blobs/<hash[:2]>/<hash[2:4]>/<hash>`

如需清理无引用 blobs（`ref_count=0`）：

```bash
uv run --project apps/worker scripts/gc_blobs.py --dry-run
uv run --project apps/worker scripts/gc_blobs.py
```

## 跑通一次（Web UI 方式）

- 打开 `http://localhost:5173`
- 新建项目后点击“执行全部”
- 等待完成后在项目详情页点击“预览字幕”

## Troubleshooting

### VAD 模型不可用

先确认 worker 侧能找到 `.nemo`：

```bash
uv run --project apps/worker --directory apps/worker \
  python -c "from subflow.config import Settings; from pathlib import Path; s=Settings(); p=Path(s.vad.nemo_model_path); print(p); print('exists=', p.exists())"
```

如果 `exists=False`，在 `.env` 里显式设置 `VAD_NEMO_MODEL_PATH`（参考 `.env.example`）。
