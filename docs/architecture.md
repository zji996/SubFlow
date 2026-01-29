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
│  │Process  │  │Segment  │  │Transcr. │  │              │  │Translate│  │Format   │
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
┌────────────┐     ┌────────────┐     ┌────────────┐     ┌───────────────┐
│   Video    │────▶│   FFmpeg   │────▶│   Demucs   │────▶│ FFmpeg Norm.  │────▶ vocals.wav
│  .mp4/.mkv │     │  提取音频   │     │  人声分离   │     │  峰值归一化     │
└────────────┘     └────────────┘     └────────────┘     └───────────────┘
```

**关键决策**：
- 人声分离是必要步骤，背景音乐会严重干扰 VAD 和 ASR
- 默认对人声做峰值归一化（`AUDIO_NORMALIZE=true`，目标 `AUDIO_NORMALIZE_TARGET_DB=-1`）
- 输出标准化为 16kHz 单声道 WAV

**输入 Artifact**: 原始视频文件
**输出 Artifact**: `vocals.wav` (纯净人声音频)

---

### Stage 2: VAD 时间戳获取 (Voice Activity Detection)

**目标**：检测语音活动区间，生成时间戳分割点。

```
┌────────────┐     ┌────────────┐     ┌────────────┐
│ vocals.wav │────▶│ NeMo VAD   │────▶│  Regions   │
│            │     │            │     │  列表      │
└────────────┘     └────────────┘     └────────────┘
```

**关键决策**：
- 宁细勿粗：静音阈值设置较短（~300ms），让 LLM 后续决定合并
- 生成的是"候选切分点"，不是最终字幕边界

**输入 Artifact**: `vocals.wav`
**输出 Artifact**:
- `vad_regions` (PostgreSQL `vad_segments` 表，存储粗粒度语音区域)
- `vad_frame_probs.bin` (ArtifactStore，帧级概率张量，用于贪心句子对齐模式)

---

### Stage 3: ASR 语音识别 (Speech Recognition)

**目标**：使用贪心句子对齐算法，生成句子级别的精确分割和识别结果。

```
┌──────────────────────────────────────────────────────────────────────┐
│  贪心句子对齐：ASR 标点 + VAD Valley 联合定位句子边界                  │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  对每个 VAD region:                                                  │
│    cursor = region.start                                             │
│                                                                      │
│    while cursor < region.end:                                        │
│      1. 切取 [cursor, cursor+max_chunk_s] 音频 → ASR 识别            │
│         "This is great. And then we..."                              │
│                                                                      │
│      2. 找第一个句末标点（。？！）→ 估算时间位置                      │
│         sentence = "This is great."                                  │
│         estimated_time = cursor + chunk_duration * char_ratio        │
│                                                                      │
│      2b. 【超长句子处理】若没找到句末标点，但有逗号且估计时长          │
│          超过 max_segment_s（默认 8s），则在逗号处强制切分            │
│          → 防止说话人连续说 30 秒不带句号导致超长 segment             │
│                                                                      │
│      3. VAD Valley 搜索：在 estimated_time ± 1s 找静音点             │
│         actual_cut_time = find_vad_valley(...)                       │
│                                                                      │
│      4. 输出 SentenceSegment(cursor, actual_cut_time, sentence)      │
│         cursor = actual_cut_time → 继续下一轮                        │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

**核心价值**：
- 每次 ASR 输入 ≥ 几秒，有足够上下文，**消除短 segment 幻觉**
- 利用 ASR 输出的标点符号定位句子边界，**保证每段是完整句子**
- 用 VAD 帧级概率找静音点，**切分点在自然停顿处**
- `max_segment_s` 限制单 segment 最大时长，**防止超长句子**

**关键理解**：

> 贪心方法估计的**区间**才是核心价值，而非直接使用其文本输出。
> 有了精确的区间后，可以继续走"合并识别 + 分段识别" 进入 Stage 4 进行 LLM 纠错。

**配置项**：
```env
GREEDY_SENTENCE_ASR_MAX_CHUNK_S=10.0         # 初始窗口（秒）
GREEDY_SENTENCE_ASR_FALLBACK_CHUNK_S=15.0    # 扩展窗口（未找到句末标点时）
GREEDY_SENTENCE_ASR_MAX_SEGMENT_S=8.0        # 单 segment 最大时长，超过则在逗号处强制切分
GREEDY_SENTENCE_ASR_VAD_SEARCH_RANGE_S=1.0   # VAD valley 搜索范围 ±秒
GREEDY_SENTENCE_ASR_VAD_VALLEY_THRESHOLD=0.3 # 低于该概率视为 valley（静音）
GREEDY_SENTENCE_ASR_PARALLEL_GAP_S=2.0       # region gap >= 该值可并行
GREEDY_SENTENCE_ASR_CLAUSE_ENDINGS=，,、：:—– # 备选切分标点（逗号/顿号/冒号/破折号等）

# Stage 3/4 合并识别 chunk 配置（用于提供更长 ASR 上下文）
MERGED_CHUNK_MAX_SEGMENTS=20        # 每个 merged chunk 最多包含的 segment 数
MERGED_CHUNK_MAX_DURATION_S=60.0    # 每个 merged chunk 最大时长（秒，含静音间隔）
```

**输入 Artifact**: `vad_regions.json` + `vad_frame_probs` + `vocals.wav`
**输出 Artifact**:
- `sentence_segments.json` (句子级 segment，含时间戳)
- `asr_segments.json` (分段 ASR，用于 Stage 4 纠错)
- `asr_merged_chunks.json` (合并 ASR chunks，用于 Stage 4 纠错；可跨 region)
- `full_transcript.txt`

---

### Stage 4: LLM ASR 纠错 (LLM ASR Correction)

**目标**：对比 "合并识别" 与 "分段识别"，纠正分段 ASR 的听错字、漏字、多字，并删除明显幻觉。

**与 Stage 3 的配合**：

Stage 4 的输入来自 Stage 3 的 `sentence_segments`：

```
贪心句子对齐输出:
  sentence_segments = [
    {start: 0.0,  end: 3.5,  text: "This is great."},
    {start: 3.5,  end: 7.2,  text: "And then we go."},
    ...
  ]

Stage 4 处理:
  对每个 merged_chunk (若干相邻 sentence_segments):
    1. merged_asr_text = ASR(合并音频)        → 上下文完整
    2. per_segment_asr = [ASR(seg) for seg]   → 时间戳精确
    3. LLM 对比纠错 → corrected_segments
```

**关键理解**：
- 贪心方法的**区间**是核心价值，提供了精确的句子边界
- Stage 4 使用这些区间重新进行"合并识别 + 分段识别"
- LLM 对比两种识别结果，纠正错误，输出最终文本

**并行策略（2026-01）**：
- 纠错任务以 `asr_merged_chunks` 为单位执行
- `asr_merged_chunks` 的窗口大小由 `MERGED_CHUNK_MAX_SEGMENTS` / `MERGED_CHUNK_MAX_DURATION_S` 控制（默认 20 段 / 60s）
- 不再受 `vad_regions` 边界限制：merged chunk 可跨 region（用于提供更长上下文、减少幻觉）
- LLM 并发上限按服务类型控制：`CONCURRENCY_LLM_FAST` / `CONCURRENCY_LLM_POWER`

**输入 Artifact**: `sentence_segments.json` + `asr_segments.json` + `asr_merged_chunks.json`  
**输出 Artifact**: `asr_corrected_segments.json`


---

### Stage 5: LLM 多 Pass 翻译 (Multi-Pass LLM Translation)

**目标**：通过 2 轮 LLM 处理，完成全局理解与逐段翻译（ASR 纠错已在 Stage 4 完成）。

- Pass 1（全局理解）：生成 `global_context`（主题/领域/风格/术语表/翻译注意事项）
- Pass 2（逐段翻译）：对 `asr_corrected_segments` 逐段翻译（1:1），支持批量并行（按 LLM 并发上限控制）

Stage 5 的详细提示词、输入/输出 JSON、以及给 LLM 的实际输入（System Prompt + User Input）已拆到：`docs/llm_multi_pass.md`。

**输入 Artifact**: `asr_segments.json` + `full_transcript.txt`  
**输出 Artifact**: `global_context.json` + `semantic_chunks.json`（每段 1 条；不再做多段合并）

---

### Stage 6: 字幕输出 (Subtitle Export)

**目标**：将翻译结果导出为标准字幕格式（默认双行字幕）。

- 第一行（主字幕）：每个段落对应的译文（1:1）
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
| `VAD_REGIONS` | 语音活动区域列表（存储在 PostgreSQL `vad_segments` 表） | Stage 2 |
| `ASR_RESULTS` | 带时间戳的识别文本 | Stage 3 |
| `ASR_MERGED_CHUNKS` | 合并识别 chunks（可跨 region，用于 Stage 4 对比纠错） | Stage 3 |
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
├── vad_region_repo.py    # VADRegionRepository
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
│   ├── AnthropicAdapter
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
