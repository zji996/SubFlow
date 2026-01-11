# SubFlow 架构设计文档

> 视频语义翻译系统 - Video Semantic Translation System

## 目录

1. [系统概述](#系统概述)
2. [设计理念](#设计理念)
3. [整体架构](#整体架构)
4. [流水线阶段](#流水线阶段)
5. [数据流设计](#数据流设计)
6. [数据存储架构](#数据存储架构)
7. [核心抽象](#核心抽象)
8. [扩展点](#扩展点)

---

## 系统概述

SubFlow 是一个基于语义理解的视频字幕翻译系统。与传统的逐句翻译不同，SubFlow 采用**多阶段流水线架构**，通过全局语境理解和语义块切分，生成更加自然、准确的翻译字幕。

### 核心价值主张

| 传统方案 | SubFlow 方案 |
|---------|-------------|
| 逐句翻译，缺乏上下文 | 全局理解后翻译，术语一致 |
| 按时间戳机械切分 | 按语义边界智能切分 |
| 翻译与原文时间强绑定 | 语义块独立对齐，表达更自然 |
| 单次处理，质量不稳定 | 多 Pass 审校，质量可控 |

---

## 设计理念

### 1. 分离关注点 (Separation of Concerns)

系统将复杂的翻译任务拆解为独立的阶段，每个阶段专注于单一职责：

```
音频处理 → 时间切分 → 文本识别 → 语义理解 → 翻译生成 → 格式输出
```

### 2. 语义优先 (Semantic-First)

时间戳服务于语义，而非语义迁就时间戳。翻译单元的边界由语义完整性决定，而非由 VAD 静音点机械切分。

### 3. 上下文感知 (Context-Aware)

翻译过程中始终携带全局上下文：
- 全文主题和领域
- 统一的术语表
- 说话人风格信息

### 4. 渐进式精化 (Progressive Refinement)

采用多 Pass 策略，每一轮处理都在前一轮的基础上精化结果，而非一次性完成所有工作。

---

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              SubFlow                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                        Pipeline Orchestrator                      │   │
│  │                          (流水线编排器)                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│       ┌────────────────────────────┼────────────────────────────┐      │
│       │                            │                            │      │
│       ▼                            ▼                            ▼      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────────┐  ┌─────────┐  ┌─────────┐
│  │ Stage 1 │─▶│ Stage 2 │─▶│ Stage 3 │─▶│   Stage 4    │─▶│ Stage 5 │─▶│ Stage 6 │
│  │Audio    │  │VAD      │  │ASR      │  │LLM ASR Corr. │  │LLM      │  │Export   │
│  │Process  │  │Segment  │  │Transcr. │  │(3.5)         │  │Translate│  │Format   │
│  └─────────┘  └─────────┘  └─────────┘  └──────────────┘  └─────────┘  └─────────┘
│       │            │            │            │            │            │
│       ▼            ▼            ▼            ▼            ▼            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       Artifact Store                              │   │
│  │                     (中间产物存储层)                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                     External Services                             │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │   │
│  │  │  FFmpeg  │  │  Demucs  │  │ GLM-ASR  │  │   LLM    │         │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘         │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 层次说明

| 层次 | 职责 |
|------|------|
| **Pipeline Orchestrator** | 编排各阶段执行顺序，处理错误恢复，管理整体进度 |
| **Stage (阶段)** | 完成特定处理任务，输入/输出均为标准化的 Artifact |
| **Repository 层** | 数据库访问抽象，封装 PostgreSQL 操作 |
| **Artifact Store** | 二进制文件存储（音视频等） |
| **External Services** | 实际的计算引擎，通过适配器模式接入 |

---

## 流水线阶段

### Stage 1: 音频预处理 (Audio Preprocessing)

**目标**：从视频中提取纯净人声，为后续处理提供高质量输入。

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│   Video    │────▶│   FFmpeg   │────▶│   Demucs   │────▶ vocals.wav
│  .mp4/.mkv │     │  提取音频   │     │  人声分离   │
└────────────┘     └────────────┘     └────────────┘
```

**关键决策**：
- 人声分离是必要步骤，背景音乐会严重干扰 VAD 和 ASR
- 输出标准化为 16kHz 单声道 WAV

**输入 Artifact**: 原始视频文件
**输出 Artifact**: `vocals.wav` (纯净人声音频)

---

### Stage 2: VAD 时间戳获取 (Voice Activity Detection)

**目标**：检测语音活动区间，生成时间戳分割点。

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│ vocals.wav │────▶│ NeMo VAD   │────▶│  Segments  │
│            │     │            │     │  列表      │
└────────────┘     └────────────┘     └────────────┘
```

**关键决策**：
- 宁细勿粗：静音阈值设置较短（~300ms），让 LLM 后续决定合并
- 生成的是"候选切分点"，不是最终字幕边界

**输入 Artifact**: `vocals.wav`
**输出 Artifact**:
- `vad_segments.json` (细分片段时间戳列表)
- `vad_regions.json` (非连续语音区域列表，可选)

---

### Stage 3: ASR 语音识别 (Speech Recognition)

**目标**：将语音段落转换为文本。

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│ Audio Segs │────▶│  GLM-ASR   │────▶│   Text +   │
│            │     │            │     │ Timestamps │
└────────────┘     └────────────┘     └────────────┘
```

**关键决策**：
- 分段识别策略：每个 VAD segment 独立送入 ASR（时间戳继承自 VAD）
- 合并识别策略：在每个 VAD region 内将 segments 合并为 ≤30s 的识别块，再做整体 ASR（上下文更完整）
- 时间戳由 VAD 段边界继承，ASR 仅负责文本输出
- 可并行处理多个段落

**输入 Artifact**: `vad_segments.json` + `vocals.wav`
**输出 Artifact**:
- `asr_segments.json` (分段 ASR，带时间戳的文本列表)
- `asr_merged_chunks.json` (region 内合并识别块列表，含 `segment_ids` 与整体识别 `text`)
- `full_transcript.txt` (基于分段 ASR 的完整文本)

---

### Stage 4: LLM ASR 纠错 (LLM ASR Correction)

**目标**：对比 “region 内合并识别” 与 “分段识别”，纠正分段 ASR 的听错字、漏字、多字，并删除明显幻觉。

**并行策略（2026-01）**：
- 纠错任务以 `asr_merged_chunks` 为单位执行
- 当启用 `PARALLEL_ENABLED=true` 时，会基于 `vad_regions` 的 region gap（`PARALLEL_MIN_GAP_SECONDS`）进行分区；分区间可并行处理
- LLM 并发上限按服务类型控制：`CONCURRENCY_LLM_FAST` / `CONCURRENCY_LLM_POWER`（取决于 `LLM_ASR_CORRECTION=fast|power`）

**输入 Artifact**: `asr_segments.json` + `asr_merged_chunks.json`  
**输出 Artifact**: `asr_corrected_segments.json`

---

### Stage 5: LLM 多 Pass 翻译 (Multi-Pass LLM Translation)

**目标**：通过 2 轮 LLM 处理，完成全局理解、语义块切分与翻译（ASR 纠错已在 Stage 4 完成）。

- Pass 1（全局理解）：生成 `global_context`（主题/领域/风格/术语表/翻译注意事项）
- Pass 2（语义切分+翻译）：从（已纠错的）`asr_segments` 生成 `semantic_chunks`，包含：
  - `translation`：完整意译
  - `translation_chunks`：翻译分段（1 个 chunk 可覆盖多个段落）

**并行策略（2026-01）**：
- Pass 2 在启用 `PARALLEL_ENABLED=true` 时，会按 `vad_regions` 的 region gap 分区；每个分区内部保持贪心串行，分区间并行
- 分区间无 `【上一轮翻译】` 上下文传递；Pass 1 的 `global_context` 共享
- LLM 并发上限按服务类型控制：`CONCURRENCY_LLM_POWER`（或当 `LLM_SEMANTIC_TRANSLATION=fast` 时使用 `CONCURRENCY_LLM_FAST`）

Stage 5 的详细提示词、输入/输出 JSON、以及给 LLM 的实际输入（System Prompt + User Input）已拆到：`docs/llm_multi_pass.md`。

**输入 Artifact**: `asr_segments.json` + `full_transcript.txt`  
**输出 Artifact**: `global_context.json` + `semantic_chunks.json`

---

### Stage 6: 字幕输出 (Subtitle Export)

**目标**：将翻译结果导出为标准字幕格式（默认双行字幕）。

- 第一行（主字幕）：根据 `translation_style` 配置
  - `per_chunk`（默认）：按 `translation_chunks` 分配（同一 chunk 覆盖的段落共享翻译片段）
  - `full`：`SemanticChunk.translation`（完整意译，所有段落共享）
- 第二行（子字幕）：每个 `ASRSegment` 对应的 `ASRCorrectedSegment.text`（若无纠错则回退到 `ASRSegment.text`）

```
┌────────────┐     ┌────────────┐     ┌───────────────┐
│ Translation│────▶│  Formatter │────▶│  .srt/.vtt/   │
│   Result   │     │            │     │  .ass/.json   │
└────────────┘     └────────────┘     └───────────────┘
```

**支持格式**：
| 格式 | 特点 |
|------|------|
| **SRT** | 最通用，兼容性最好 |
| **VTT** | Web 友好，支持样式 |
| **ASS** | 高级样式，动画效果 |
| **JSON** | 程序化处理，自定义渲染 |

**输入 Artifact**: `semantic_chunks.json` + `asr_segments.json` (+ `asr_corrected_segments.json` 可选)
**输出 Artifact**: 字幕文件 (`.srt`, `.vtt`, `.ass` 等)

---

## 数据流设计

### Artifact 定义

系统中的所有中间产物都以 Artifact 形式存储，确保可追溯、可复用。

```
Artifact
├── metadata
│   ├── id: string           # 唯一标识
│   ├── type: ArtifactType   # 类型枚举
│   ├── created_at: datetime
│   ├── source_stage: string # 产生该 Artifact 的阶段
│   └── dependencies: []     # 依赖的其他 Artifact ID
└── payload
    └── (具体内容，类型相关)
```

### 主要 Artifact 类型

| Artifact Type | 内容 | 产生阶段 |
|---------------|------|----------|
| `VIDEO_INPUT` | 原始视频文件路径 | 输入 |
| `VOCALS_AUDIO` | 提取的人声音频 | Stage 1 |
| `VAD_SEGMENTS` | 语音活动时间段列表 | Stage 2 |
| `VAD_REGIONS` | 非连续语音区域列表（可选） | Stage 2 |
| `ASR_RESULTS` | 带时间戳的识别文本 | Stage 3 |
| `ASR_MERGED_CHUNKS` | region 内合并识别块列表 | Stage 3 |
| `FULL_TRANSCRIPT` | 完整转录文本 | Stage 3 |
| `ASR_CORRECTED_SEGMENTS` | ASR 纠错段落文本 | Stage 4 |
| `GLOBAL_CONTEXT` | 全局理解结果 | Stage 5.1 |
| `SEMANTIC_CHUNKS` | 语义块切分结果（包含翻译） | Stage 5.2 |
| `SUBTITLE_FILE` | 最终字幕文件 | Stage 6 |

---

## 数据存储架构

SubFlow 采用 **PostgreSQL-First** 架构，详细请参考 [`docs/database.md`](./database.md)。

### 存储分层

| 数据类型 | 存储位置 | 说明 |
|----------|----------|------|
| 项目元数据 | PostgreSQL `projects` 表 | 持久化，支持 SQL 查询 |
| Stage 运行记录 | PostgreSQL `stage_runs` 表 | 独立表，易扩展 |
| VAD/ASR 结果 | PostgreSQL | 支持按时间范围查询 |
| 语义块/翻译 | PostgreSQL | 支持条件查询 |
| 二进制文件 | BlobStore (CAS) | 基于 SHA256 的内容寻址存储 |
| 导出字幕文件 | S3/MinIO | 保持现有路径格式 |
| Redis | 任务队列 | `subflow:projects:queue` |

### Repository 模式

所有数据库操作通过 Repository 封装：

```
libs/subflow/subflow/repositories/
├── project_repo.py       # ProjectRepository
├── stage_run_repo.py     # StageRunRepository
├── vad_segment_repo.py   # VADSegmentRepository
├── asr_segment_repo.py   # ASRSegmentRepository
├── global_context_repo.py
├── semantic_chunk_repo.py
└── subtitle_export_repo.py
```

### 数据库迁移

```bash
# 执行迁移
uv run --project apps/api scripts/db_migrate.py
```

详细的 Schema 定义见 `infra/migrations/001_init.sql`。

---

## 核心抽象

### Stage 接口

每个处理阶段遵循统一的接口契约：

```
Stage
├── name: string
├── input_types: [ArtifactType]    # 需要的输入类型
├── output_types: [ArtifactType]   # 产出的输出类型
├── execute(inputs) -> outputs     # 执行逻辑
└── validate(inputs) -> bool       # 输入校验
```

### Service Adapter (服务适配器)

外部服务通过适配器接入，便于替换和测试：

```
ServiceAdapter
├── ASRAdapter
│   ├── GLMASRAdapter        # GLM-ASR 实现
│   ├── WhisperAdapter       # Whisper 实现 (备选)
│   └── MockASRAdapter       # 测试用 Mock
├── LLMAdapter
│   ├── OpenAIAdapter
│   ├── ClaudeAdapter
│   └── LocalLLMAdapter
└── AudioAdapter
    ├── FFmpegAdapter
    └── DemucsAdapter
```

### Pipeline Configuration (流水线配置)

支持通过配置调整流水线行为：

```yaml
pipeline:
  stages:
    audio_preprocessing:
      enabled: true
      demucs_model: "htdemucs_ft"
    vad:
      min_speech_duration_ms: 250
      min_silence_duration_ms: 300
    asr:
      model: "glm-asr-nano-2512"
      parallel_workers: 4
    llm:
      passes: ["global_understanding", "semantic_chunking", "translation", "qa"]
      model: "gpt-4"
      temperature: 0.3
    export:
      formats: ["srt", "vtt"]
```

---

## 扩展点

### 1. 新增 ASR 引擎

实现 `ASRAdapter` 接口即可接入新的 ASR 服务。

### 2. 自定义 LLM Pass

LLM 处理阶段支持插件式扩展，可添加自定义 Pass：
- 特定领域的术语增强
- 自定义质量检查规则
- 多语言同步翻译

### 3. 输出格式扩展

实现 `SubtitleFormatter` 接口添加新的输出格式。

### 4. 批处理与并发

流水线编排器支持：
- 多视频批量处理
- 阶段内并行（如多 ASR segment 并行）
- 分布式执行（未来）

---

## 附录

### A. 为什么需要人声分离？

| 问题 | 影响 |
|------|------|
| 背景音乐 | VAD 误判，将音乐识别为语音 |
| 环境噪音 | ASR 准确率下降 |
| 多人重叠 | 识别混乱，时间戳错位 |

### B. 为什么语义切分优于时间切分？

传统方案：固定时长切分（如每 5 秒一条字幕）
- ❌ 可能在句中断开
- ❌ 翻译时缺少完整上下文
- ❌ 不同语言语序导致别扭

SubFlow 方案：语义块切分
- ✅ 每块表达完整意思
- ✅ 翻译单元边界自然
- ✅ 阅读体验流畅

### C. LLM 多 Pass vs 单 Pass

| 单 Pass | 多 Pass |
|---------|---------|
| 一次性完成所有任务 | 任务分解，逐步精化 |
| Prompt 复杂，容易遗漏 | 每步 Prompt 简洁专注 |
| 难以保证术语一致 | 术语表贯穿全程 |
| 无法中途干预 | 可检视中间结果 |

---

*文档版本: 0.2.0*
*最后更新: 2026-01-11*
