# SubFlow 骨架搭建计划

> 本计划供 Codex/AI Agent 执行，目标是搭建完整的项目骨架，所有外部服务调用暂用空实现。

## 当前状态

已完成：
- [x] 项目结构 (apps/, libs/, infra/, docs/, scripts/)
- [x] docker-compose.dev.yml (Redis, Postgres, MinIO)
- [x] libs/subflow/config.py 配置管理
- [x] Provider 基础框架 (ASR/LLM 抽象接口 + 空实现)
- [x] apps/api/main.py 入口
- [x] apps/worker/main.py 入口

## 待完成任务

### Phase 1: 数据模型层

**目标**: 定义核心数据结构

#### 1.1 创建 `libs/subflow/models/__init__.py`

```python
# 导出所有模型
```

#### 1.2 创建 `libs/subflow/models/job.py`

定义任务模型：
```python
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

class JobStatus(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Job:
    id: str
    video_url: str  # S3 URL
    status: JobStatus = JobStatus.PENDING
    source_language: str | None = None
    target_language: str = "zh"
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None
    result_url: str | None = None  # 字幕文件 S3 URL
```

#### 1.3 创建 `libs/subflow/models/artifact.py`

定义中间产物：
```python
from dataclasses import dataclass
from enum import Enum

class ArtifactType(Enum):
    VOCALS_AUDIO = "vocals_audio"
    VAD_SEGMENTS = "vad_segments"
    ASR_RESULTS = "asr_results"
    FULL_TRANSCRIPT = "full_transcript"
    GLOBAL_CONTEXT = "global_context"
    SEMANTIC_CHUNKS = "semantic_chunks"
    TRANSLATION = "translation"
    SUBTITLE_FILE = "subtitle_file"

@dataclass
class Artifact:
    job_id: str
    type: ArtifactType
    path: str  # S3 path
    metadata: dict = field(default_factory=dict)
```

#### 1.4 创建 `libs/subflow/models/segment.py`

定义语音/语义段落：
```python
@dataclass
class VADSegment:
    start: float
    end: float

@dataclass
class ASRSegment:
    id: int
    start: float
    end: float
    text: str
    language: str | None = None

@dataclass
class SemanticChunk:
    id: int
    text: str
    translation: str | None = None
    start: float
    end: float
    source_segment_ids: list[int] = field(default_factory=list)
```

---

### Phase 2: Stage 抽象层

**目标**: 定义流水线阶段接口

#### 2.1 创建 `libs/subflow/stages/base.py`

```python
from abc import ABC, abstractmethod
from typing import Any

class Stage(ABC):
    """流水线阶段抽象基类"""
    
    name: str
    
    @abstractmethod
    async def execute(self, context: dict) -> dict:
        """执行阶段逻辑，返回更新后的 context"""
        ...
    
    @abstractmethod
    def validate_input(self, context: dict) -> bool:
        """校验输入是否满足要求"""
        ...
```

#### 2.2 创建各 Stage 空实现

| 文件 | 类名 | 说明 |
|------|------|------|
| `stages/audio_preprocess.py` | `AudioPreprocessStage` | 音频提取 + 人声分离 |
| `stages/vad.py` | `VADStage` | 语音活动检测 |
| `stages/asr.py` | `ASRStage` | 语音识别 |
| `stages/llm_passes.py` | `GlobalUnderstandingPass`, `SemanticChunkingPass`, `TranslationPass`, `QAPass` | LLM 四个 Pass |
| `stages/export.py` | `ExportStage` | 字幕导出 |

每个 Stage 实现：
- `__init__` 接收配置
- `execute` 暂时 `raise NotImplementedError` 或返回模拟数据
- `validate_input` 检查必要字段

---

### Phase 3: Pipeline 编排层

**目标**: 实现流水线编排

#### 3.1 创建 `libs/subflow/pipeline/executor.py`

```python
from libs.subflow.stages.base import Stage

class PipelineExecutor:
    """流水线执行器"""
    
    def __init__(self, stages: list[Stage]):
        self.stages = stages
    
    async def run(self, initial_context: dict) -> dict:
        """顺序执行所有阶段"""
        context = initial_context.copy()
        for stage in self.stages:
            if not stage.validate_input(context):
                raise ValueError(f"Stage {stage.name} input validation failed")
            context = await stage.execute(context)
        return context
```

#### 3.2 创建 `libs/subflow/pipeline/factory.py`

```python
def create_translation_pipeline(config: Settings) -> PipelineExecutor:
    """创建标准翻译流水线"""
    stages = [
        AudioPreprocessStage(config),
        VADStage(config),
        ASRStage(config),
        GlobalUnderstandingPass(config),
        SemanticChunkingPass(config),
        TranslationPass(config),
        QAPass(config),
        ExportStage(config),
    ]
    return PipelineExecutor(stages)
```

---

### Phase 4: API 层

**目标**: 实现 REST API

#### 4.1 更新 `apps/api/main.py`

添加路由：
- `POST /jobs` - 创建翻译任务
- `GET /jobs/{job_id}` - 查询任务状态
- `GET /jobs/{job_id}/result` - 获取结果（重定向到 S3）

#### 4.2 创建 `apps/api/routes/jobs.py`

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/jobs", tags=["jobs"])

class CreateJobRequest(BaseModel):
    video_url: str
    target_language: str = "zh"

class JobResponse(BaseModel):
    id: str
    status: str
    result_url: str | None = None

@router.post("", response_model=JobResponse)
async def create_job(request: CreateJobRequest):
    # TODO: 创建任务，推送到 Redis 队列
    pass

@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: str):
    # TODO: 从数据库查询任务状态
    pass
```

#### 4.3 创建 `apps/api/services/` 目录

- `apps/api/services/job_service.py` - 任务 CRUD
- `apps/api/services/storage_service.py` - S3 操作封装

---

### Phase 5: Worker 层

**目标**: 实现后台任务处理

#### 5.1 更新 `apps/worker/main.py`

实现 Redis 队列消费循环：
```python
async def main():
    redis = Redis.from_url(settings.redis_url)
    pipeline = create_translation_pipeline(settings)
    
    while True:
        job_data = await redis.brpop("subflow:jobs", timeout=5)
        if job_data:
            await process_job(job_data, pipeline)
```

#### 5.2 创建 `apps/worker/handlers/job_handler.py`

```python
async def process_job(job_data: dict, pipeline: PipelineExecutor):
    """处理单个翻译任务"""
    try:
        # 更新状态为 processing
        # 下载视频到临时目录
        # 执行 pipeline
        # 上传结果到 S3
        # 更新状态为 completed
        pass
    except Exception as e:
        # 更新状态为 failed
        pass
```

---

### Phase 6: 字幕格式化

**目标**: 实现字幕输出格式

#### 6.1 创建 `libs/subflow/formatters/__init__.py`

#### 6.2 创建 `libs/subflow/formatters/base.py`

```python
from abc import ABC, abstractmethod

class SubtitleFormatter(ABC):
    @abstractmethod
    def format(self, chunks: list[SemanticChunk]) -> str:
        ...
```

#### 6.3 创建格式实现

| 文件 | 类名 |
|------|------|
| `formatters/srt.py` | `SRTFormatter` |
| `formatters/vtt.py` | `VTTFormatter` |
| `formatters/ass.py` | `ASSFormatter` |

---

## 执行顺序

1. **Phase 1** - 数据模型（无依赖）
2. **Phase 2** - Stage 抽象（依赖 Phase 1）
3. **Phase 3** - Pipeline 编排（依赖 Phase 2）
4. **Phase 6** - 字幕格式化（无依赖，可并行）
5. **Phase 4** - API 层（依赖 Phase 1）
6. **Phase 5** - Worker 层（依赖 Phase 1, 3）

## 注意事项

1. **所有 Provider 调用暂为空实现**
   - ASR: 返回模拟的 `ASRSegment` 列表
   - LLM: 返回模拟的 JSON 响应

2. **保持目录结构规范**
   - 参考 `AGENTS.md` 中的目录结构
   - 不新增顶层目录

3. **导入路径**
   - 使用绝对路径：`from libs.subflow.xxx import yyy`

4. **类型注解**
   - 使用 Python 3.11+ 语法：`list[T]`, `dict[K, V]`, `T | None`

5. **异步优先**
   - 所有 I/O 操作使用 `async/await`

---

*计划版本: 0.1.0*
*创建时间: 2026-01-06*
