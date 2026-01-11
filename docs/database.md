# SubFlow 数据库设计文档

> PostgreSQL-First 数据持久化架构

## 概述

SubFlow 采用 **PostgreSQL-First** 架构，所有核心业务数据存储在 PostgreSQL 中。Redis 仅用于任务队列，二进制大文件（音视频）通过 BlobStore 进行内容寻址存储。

---

## 架构决策

### 为什么选择 PostgreSQL 作为主存储？

| 之前的方案 | 问题 |
|-----------|------|
| Project 元数据存 Redis | 带 TTL 过期风险，服务重启可能丢失 |
| 结构化数据存 JSON 文件 | 无法按条件查询（时间范围、置信度等）|
| 数据分散在多处 | 难以保证一致性和事务性 |

### 现在的存储策略

| 数据类型 | 存储位置 | 说明 |
|----------|----------|------|
| Project 元数据 | PostgreSQL | 持久化，支持 SQL 查询 |
| Stage 运行记录 | PostgreSQL | 独立表，易扩展 |
| VAD/ASR/语义块等结构化数据 | PostgreSQL | 支持按条件查询 |
| 二进制文件（音视频） | BlobStore (CAS) | 基于 SHA256 的内容寻址存储 |
| 导出字幕文件 | S3/MinIO | 保持现有路径格式 |
| Redis | 仅任务队列 | `subflow:projects:queue` |

---

## 数据库 Schema

Schema 定义位于: `infra/migrations/001_init.sql`

### 核心表

```sql
-- 项目表
projects (
    id            VARCHAR PRIMARY KEY,
    name          TEXT NOT NULL,
    media_url     TEXT NOT NULL,
    source_language TEXT NULL,
    target_language TEXT NOT NULL,
    auto_workflow BOOLEAN NOT NULL DEFAULT TRUE,
    status        TEXT NOT NULL,        -- pending/processing/paused/completed/failed
    current_stage INTEGER NOT NULL DEFAULT 0,
    error_message TEXT NULL,
    created_at    TIMESTAMPTZ NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL
)

-- 阶段运行记录表
stage_runs (
    project_id    VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    stage         TEXT NOT NULL,        -- audio_preprocess/vad/asr/llm_asr_correction/llm
    status        TEXT NOT NULL,        -- pending/running/completed/failed
    started_at    TIMESTAMPTZ NULL,
    completed_at  TIMESTAMPTZ NULL,
    error_message TEXT NULL,
    metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (project_id, stage)
)
```

### 处理结果表

```sql
-- VAD 检测结果
vad_segments (
    project_id    VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    segment_index INTEGER NOT NULL,
    start_time    DOUBLE PRECISION NOT NULL,
    end_time      DOUBLE PRECISION NOT NULL,
    region_id     INTEGER NULL,
    PRIMARY KEY (project_id, segment_index)
)

-- ASR 识别结果
asr_segments (
    project_id      VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    segment_index   INTEGER NOT NULL,
    start_time      DOUBLE PRECISION NOT NULL,
    end_time        DOUBLE PRECISION NOT NULL,
    text            TEXT NOT NULL,
    corrected_text  TEXT NULL,          -- Stage 4 纠错后回写
    language        TEXT NULL,
    confidence      DOUBLE PRECISION NULL,
    PRIMARY KEY (project_id, segment_index)
)

-- 全局理解结果
global_contexts (
    project_id         VARCHAR PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    topic              TEXT NULL,
    domain             TEXT NULL,
    style              TEXT NULL,
    glossary           JSONB NOT NULL DEFAULT '{}'::jsonb,
    translation_notes  TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]
)

-- 语义块
semantic_chunks (
    id             BIGSERIAL PRIMARY KEY,
    project_id     VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chunk_index    INTEGER NOT NULL,
    text           TEXT NOT NULL,
    translation    TEXT NULL,
    asr_segment_ids INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    UNIQUE (project_id, chunk_index)
)

-- 翻译分段（关联语义块）
translation_chunks (
    id               BIGSERIAL PRIMARY KEY,
    semantic_chunk_id BIGINT NOT NULL REFERENCES semantic_chunks(id) ON DELETE CASCADE,
    chunk_order      INTEGER NOT NULL,
    text             TEXT NOT NULL,
    segment_ids      INTEGER[] NOT NULL DEFAULT ARRAY[]::INTEGER[],
    UNIQUE (semantic_chunk_id, chunk_order)
)

-- 字幕导出记录
subtitle_exports (
    id           VARCHAR PRIMARY KEY,
    project_id   VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL,
    format       TEXT NOT NULL,         -- srt/vtt/ass/json
    content_mode TEXT NOT NULL,         -- both/primary_only/secondary_only
    source       TEXT NOT NULL,         -- auto/edited
    config_json  JSONB NOT NULL DEFAULT '{}'::jsonb,
    storage_key  TEXT NOT NULL          -- S3/MinIO 存储路径
)
```

### 索引设计

```sql
-- 时间范围查询优化
CREATE INDEX idx_vad_segments_project_time ON vad_segments(project_id, start_time, end_time);
CREATE INDEX idx_asr_segments_project_time ON asr_segments(project_id, start_time, end_time);

-- 项目关联查询
CREATE INDEX idx_semantic_chunks_project_id ON semantic_chunks(project_id);
CREATE INDEX idx_subtitle_exports_project_id ON subtitle_exports(project_id);
```

---

## Repository 层

所有数据库操作通过 Repository 模式封装，位于 `libs/subflow/subflow/repositories/`。

### 类结构

```
repositories/
├── __init__.py          # 导出所有 Repository
├── base.py              # DatabasePool + BaseRepository
├── project_repo.py      # ProjectRepository
├── stage_run_repo.py    # StageRunRepository
├── vad_segment_repo.py  # VADSegmentRepository
├── asr_segment_repo.py  # ASRSegmentRepository
├── global_context_repo.py
├── semantic_chunk_repo.py
└── subtitle_export_repo.py
```

### DatabasePool

单例模式管理连接池：

```python
class DatabasePool:
    """Singleton connection pool manager."""
    _pool: AsyncConnectionPool | None = None

    @classmethod
    async def get_pool(cls, settings: Settings) -> AsyncConnectionPool:
        if cls._pool is None:
            cls._pool = AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=2,
                max_size=10,
            )
            await cls._pool.open()
        return cls._pool

    @classmethod
    async def close(cls) -> None:
        if cls._pool:
            await cls._pool.close()
            cls._pool = None
```

### 使用示例

```python
from subflow.repositories import DatabasePool, ProjectRepository, ASRSegmentRepository

# 初始化
pool = await DatabasePool.get_pool(settings)
project_repo = ProjectRepository(pool)
asr_repo = ASRSegmentRepository(pool)

# CRUD 操作
project = await project_repo.get(project_id)
asr_segments = await asr_repo.get_by_project(project_id)

# 批量写入
await asr_repo.bulk_insert(project_id, segments)

# 时间范围查询
segments = await asr_repo.get_by_time_range(project_id, start=10.0, end=30.0)
```

---

## 数据迁移

### 迁移脚本

位于 `scripts/db_migrate.py`，管理 schema 版本：

```bash
# 执行迁移
uv run --project apps/api scripts/db_migrate.py

# 指定数据库 URL
uv run --project apps/api scripts/db_migrate.py --database-url postgresql://...
```

### 迁移记录表

```sql
schema_migrations (
    name TEXT PRIMARY KEY,      -- 迁移文件名，如 001_init.sql
    applied_at TIMESTAMPTZ NOT NULL
)
```

### 添加新迁移

1. 在 `infra/migrations/` 创建新 SQL 文件（如 `002_add_index.sql`）
2. 文件名必须以数字前缀排序
3. 运行 `scripts/db_migrate.py`，脚本会自动识别并应用未执行的迁移

---

## Pipeline 数据流

### Stage 输出写入 DB

| Stage | 写入的表 | 方法 |
|-------|----------|------|
| Stage 1 (Audio) | stage_runs | `stage_run_repo.mark_completed()` |
| Stage 2 (VAD) | vad_segments | `vad_repo.bulk_insert()` |
| Stage 3 (ASR) | asr_segments | `asr_repo.bulk_insert()` |
| Stage 4 (LLM Correction) | asr_segments.corrected_text | `asr_repo.update_corrected_texts()` |
| Stage 5 (LLM Translation) | global_contexts, semantic_chunks, translation_chunks | 事务写入 |

### 幂等性保证

每个 Stage 开始前会清除该 Stage 的旧数据：

```python
# Stage 2 重跑前
await vad_repo.delete_by_project(project_id)

# Stage 3 重跑前
await asr_repo.delete_by_project(project_id)

# Stage 5 重跑前
await global_context_repo.delete(project_id)
await semantic_chunk_repo.delete_by_project(project_id)
```

---

## 级联删除

所有外键使用 `ON DELETE CASCADE`，删除 Project 时自动清理所有关联数据：

```
DELETE FROM projects WHERE id = 'proj_xxx';
-- 自动删除:
--   - stage_runs
--   - vad_segments
--   - asr_segments
--   - global_contexts
--   - semantic_chunks (及其 translation_chunks)
--   - subtitle_exports
```

---

## BlobStore（大文件存储）

二进制文件（音视频）不存入数据库，而是使用内容寻址存储：

- 存储路径: `data/blobs/{sha256[:2]}/{sha256[2:4]}/{sha256}`
- 引用计数: `file_blobs`, `project_files` 表
- 删除项目时自动减少引用计数，无引用的 blob 可被 GC

---

## 配置

### 环境变量

```bash
# .env
POSTGRES_USER=postgres
POSTGRES_PASSWORD=postgres
POSTGRES_DB=subflow
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# 完整连接串（自动构建）
# DATABASE_URL=postgresql://postgres:postgres@localhost:5432/subflow
```

### Docker Compose

```yaml
# infra/docker-compose.dev.yml
postgres:
  image: postgres:17
  environment:
    POSTGRES_USER: ${POSTGRES_USER:-postgres}
    POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
    POSTGRES_DB: ${POSTGRES_DB:-subflow}
  ports:
    - "5432:5432"
  volumes:
    - ../data/postgres:/var/lib/postgresql/data
```

---

*文档版本: 1.0*
*创建时间: 2026-01-11*
