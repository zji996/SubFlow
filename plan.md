# SubFlow PostgreSQL 迁移计划 - Phase 2-5

> **目标**：基于已完成的 Phase 1（Schema 已在 `infra/migrations/001_init.sql`），完成后端代码从 Redis + JSON 到 PostgreSQL 的迁移
> **策略**：一次性迁移，不向后兼容
> **前置条件**：已执行 `uv run --project apps/api scripts/db_migrate.py` 创建数据库表

---

## 已完成

### Phase 1: 数据库表结构 ✅
- `infra/migrations/001_init.sql` - 8 张核心表
- `scripts/db_migrate.py` - 迁移脚本 + schema_migrations 记录表

---

## Phase 2: Repository 层实现

### 2.1 创建 Repository 目录结构

```
libs/subflow/subflow/repositories/
├── __init__.py
├── base.py              # 基础类，连接池管理
├── project_repo.py      # ProjectRepository
├── stage_run_repo.py    # StageRunRepository
├── vad_segment_repo.py  # VADSegmentRepository
├── asr_segment_repo.py  # ASRSegmentRepository
├── global_context_repo.py
├── semantic_chunk_repo.py
└── subtitle_export_repo.py
```

### 2.2 BaseRepository

```python
# libs/subflow/subflow/repositories/base.py
from contextlib import asynccontextmanager
from typing import AsyncIterator
import psycopg
from psycopg_pool import AsyncConnectionPool
from subflow.config import Settings

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

class BaseRepository:
    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[psycopg.AsyncConnection]:
        async with self.pool.connection() as conn:
            yield conn
```

### 2.3 ProjectRepository

实现以下方法：
- `create(project: Project) -> Project`
- `get(project_id: str) -> Project | None`
- `update(project: Project) -> Project`
- `delete(project_id: str) -> bool`
- `list(limit: int = 100, offset: int = 0) -> list[Project]`
- `update_status(project_id: str, status: str, current_stage: int | None = None) -> None`

**注意**：
- 使用 `psycopg` 的 `Row` 模式或 `dataclass` 映射
- 实现可选的 Redis 缓存层（读取时先查缓存，写入时同步更新/失效）

### 2.4 StageRunRepository

- `create_or_update(project_id: str, stage: str, status: str, ...) -> StageRun`
- `get(project_id: str, stage: str) -> StageRun | None`
- `list_by_project(project_id: str) -> list[StageRun]`
- `mark_running(project_id: str, stage: str) -> None`
- `mark_completed(project_id: str, stage: str, metadata: dict) -> None`
- `mark_failed(project_id: str, stage: str, error_code: str, error_message: str) -> None`

### 2.5 VADSegmentRepository

- `bulk_insert(project_id: str, segments: list[VADSegment]) -> None`
- `get_by_project(project_id: str) -> list[VADSegment]`
- `delete_by_project(project_id: str) -> None` (用于重跑)

### 2.6 ASRSegmentRepository

- `bulk_insert(project_id: str, segments: list[ASRSegment]) -> None`
- `get_by_project(project_id: str) -> list[ASRSegment]`
- `update_corrected_texts(project_id: str, corrections: dict[int, str]) -> None`
- `get_by_time_range(project_id: str, start: float, end: float) -> list[ASRSegment]`
- `delete_by_project(project_id: str) -> None`

### 2.7 GlobalContextRepository

- `save(project_id: str, context: GlobalContext) -> None`
- `get(project_id: str) -> GlobalContext | None`
- `delete(project_id: str) -> None`

### 2.8 SemanticChunkRepository

- `bulk_insert(project_id: str, chunks: list[SemanticChunk]) -> list[int]` (返回新 ID)
- `get_by_project(project_id: str) -> list[SemanticChunk]` (含 translation_chunks)
- `delete_by_project(project_id: str) -> None`

事务处理：semantic_chunks 和 translation_chunks 在同一事务中写入

### 2.9 SubtitleExportRepository

- `create(export: SubtitleExport) -> SubtitleExport`
- `get(export_id: str) -> SubtitleExport | None`
- `list_by_project(project_id: str) -> list[SubtitleExport]`

---

## Phase 3: Pipeline Stage 适配

### 3.1 注入 Repository 到 Pipeline

修改 `Pipeline` 类，使其接收 Repository 实例（或通过工厂方法创建）

```python
# libs/subflow/subflow/pipeline/pipeline.py
class Pipeline:
    def __init__(
        self,
        settings: Settings,
        project_repo: ProjectRepository,
        stage_run_repo: StageRunRepository,
        vad_repo: VADSegmentRepository,
        asr_repo: ASRSegmentRepository,
        global_context_repo: GlobalContextRepository,
        semantic_chunk_repo: SemanticChunkRepository,
        # ...其他依赖
    ):
        ...
```

### 3.2 各 Stage 修改

#### Stage 1 (AudioPreprocessStage)
- 无结构化数据输出，仅更新 stage_run

#### Stage 2 (VADStage)
**Before**: `artifact_store.save_json("vad_segments.json", segments)`
**After**: `vad_repo.bulk_insert(project_id, segments)`

清理：删除写入 JSON 的逻辑

#### Stage 3 (ASRStage)
**Before**: 
- `artifact_store.save_json("asr_segments.json", segments)`
- `artifact_store.save_text("full_transcript.txt", text)`

**After**:
- `asr_repo.bulk_insert(project_id, segments)`
- （可选保留 full_transcript.txt 到 BlobStore，或直接不存）

#### Stage 4 (LLMASRCorrectionStage)
**Before**: `artifact_store.save_json("asr_corrected_segments.json", corrected)`
**After**: `asr_repo.update_corrected_texts(project_id, corrections_map)`

#### Stage 5 (LLMTranslationStage)
**Before**:
- `artifact_store.save_json("global_context.json", context)`
- `artifact_store.save_json("semantic_chunks.json", chunks)`

**After**:
- `global_context_repo.save(project_id, context)`
- `semantic_chunk_repo.bulk_insert(project_id, chunks)`

### 3.3 幂等性保证

每个 Stage 开始前，先清除该 Stage 的旧数据：

```python
# Stage 2
await vad_repo.delete_by_project(project_id)
# Stage 3
await asr_repo.delete_by_project(project_id)
# Stage 4: 只更新 corrected_text，不需要删除
# Stage 5
await global_context_repo.delete(project_id)
await semantic_chunk_repo.delete_by_project(project_id)
```

---

## Phase 4: API 层适配

### 4.1 修改 ProjectService

**文件**: `apps/api/services/project_service.py`

**Before**:
```python
self.store = ProjectStore(redis=redis, ...)  # Redis
```

**After**:
```python
self.project_repo = ProjectRepository(pool)
self.stage_run_repo = StageRunRepository(pool)
# Redis 仅用于队列
```

方法修改：
- `create_project()`: 使用 `project_repo.create()`
- `get_project()`: 使用 `project_repo.get()`（可选 Redis 缓存）
- `list_projects()`: 使用 `project_repo.list()`
- `delete_project()`: 使用 `project_repo.delete()` + 级联删除自动处理

### 4.2 修改 Worker

**文件**: `apps/worker/worker.py`

Worker 需要初始化 Repository 并传递给 Pipeline。

```python
async def run_stage(project_id: str, stage: str):
    pool = await DatabasePool.get_pool(settings)
    project_repo = ProjectRepository(pool)
    # ...初始化其他 repo
    pipeline = Pipeline(settings, project_repo, ...)
    await pipeline.run_stage(project_id, stage)
```

### 4.3 修改字幕相关 API

**文件**: `apps/api/routes/projects.py`

#### `_load_subtitle_materials()` 重写：

**Before**:
```python
chunks_bytes = await artifact_store.load(project_id, "llm", "semantic_chunks.json")
asr_bytes = await artifact_store.load(project_id, "asr", "asr_segments.json")
```

**After**:
```python
chunks = await semantic_chunk_repo.get_by_project(project_id)
asr_segments = await asr_repo.get_by_project(project_id)
```

#### `get_subtitle_edit_data()`:
- 从 Repository 查询数据，按时间排序
- 移除 JSON 解析逻辑

#### `create_export()`:
- 使用 `subtitle_export_repo.create()`

### 4.4 保留 Artifacts API（仅二进制）

`GET /projects/{id}/artifacts/{stage}/{name}` 保留用于：
- `audio.wav`, `vocals.wav` 等二进制文件

结构化数据改用专用端点（可选，基于现有实现）：
- `GET /projects/{id}/asr-segments`
- `GET /projects/{id}/semantic-chunks`

---

## Phase 5: 清理与测试

### 5.1 废弃代码移除

删除或标记废弃：
- `libs/subflow/subflow/services/project_store.py`
- `ArtifactStore` 中 JSON 读写逻辑（保留二进制文件支持）

### 5.2 Workdir 临时目录

引入 `data/workdir/{project_id}/` 用于 Pipeline 执行时的临时文件：
- 各种中间产物（如 ASR 处理中的临时音频片段）
- Stage 完成后自动清理

### 5.3 测试用例更新

更新现有测试：
- Mock Repository 而非 Redis/ArtifactStore
- 验证 Repository 方法被正确调用
- 集成测试使用真实 PostgreSQL（可用 testcontainers）

### 5.4 删除不再需要的依赖

检查并移除：
- `redis` 在 `libs/subflow` 中不再需要（仅 `apps/api` 和 `apps/worker` 需要用于队列）

---

## 执行顺序

**建议按以下顺序执行**：

1. **Phase 2.1-2.2**: 创建 base.py 和连接池管理
2. **Phase 2.3**: 实现 ProjectRepository
3. **Phase 4.1**: 修改 ProjectService 使用 ProjectRepository
4. **Phase 2.4**: 实现 StageRunRepository
5. **Phase 2.5-2.6**: 实现 VAD/ASR Repository
6. **Phase 3.2**: 修改 Stage 2-3
7. **Phase 2.6 (corrected_text)**: 完善 ASRSegmentRepository
8. **Phase 3.2**: 修改 Stage 4
9. **Phase 2.7-2.8**: 实现 GlobalContext/SemanticChunk Repository
10. **Phase 3.2**: 修改 Stage 5
11. **Phase 4.3**: 修改字幕 API
12. **Phase 2.9**: 实现 SubtitleExportRepository
13. **Phase 5**: 清理和测试

---

## 验收标准

### 功能验收

- [ ] 新项目创建后，数据存入 PostgreSQL `projects` 表，Redis 中无 Project JSON
- [ ] Pipeline 各阶段完成后，结构化数据可通过 SQL 查询
- [ ] 按时间范围查询 ASR 段落正常工作
- [ ] 字幕导出功能正常
- [ ] 字幕编辑功能正常
- [ ] 删除项目后，所有关联数据级联删除

### 代码检查

- [ ] `ruff check` 通过
- [ ] `pytest` 通过
- [ ] 无废弃的 Redis/JSON 数据访问代码

---

## Codex 可自主决策事项

- `psycopg` vs `asyncpg`：推荐使用 `psycopg[pool]`（已在依赖中）
- 连接池大小配置
- Redis 缓存失效策略的具体实现
- Repository 内部实现细节

---

*计划版本: 2.0*
*创建时间: 2026-01-11*
*前置: Phase 1 已完成*
