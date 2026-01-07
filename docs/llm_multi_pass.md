# Stage 5: LLM 多 Pass 翻译 (Multi-Pass LLM Translation)

本文件从 `docs/architecture.md` 中拆出，用于集中描述 Stage 5 的提示词、输入/输出与各 Pass 的职责边界。

## 总览

**目标**：通过 **2 轮** LLM 处理，完成全局理解、语义块切分与翻译（ASR 纠错已在 Stage 4 完成）。

```
                    ┌───────────────┐
                    │ ASR Results + │
                    │ Full Transcr. │
                    └───────┬───────┘
                            │
    ┌───────────────────────┴───────────────────────┐
    ▼                                               ▼
┌─────────┐                                   ┌─────────────────┐
│ Pass 1  │──────────────────────────────────▶│     Pass 2      │
│全局理解  │  (术语表/领域/风格)                │语义切分+翻译     │
│≤8K tok  │                                   │  贪心串行处理    │
└─────────┘                                   └─────────────────┘
```

**核心思想**：既然语义切分已经切出完整的语义句子，那么在同一步中完成翻译是最自然的——LLM 已经理解了上下文，无需再开一个 Pass。

**输入 Artifact**: `asr_segments.json` + `full_transcript.txt`（使用 Stage 4 回写后的纠错文本）  
**输出 Artifact**: `global_context.json` + `semantic_chunks.json`

---

## 关键修复 (2026-01)

### 1. 简化 LLM 输出
- LLM 只需要输出 `translation` + `asr_segment_ids`
- `next_cursor` 由系统自动计算 `max(asr_segment_ids) + 1`

### 2. 优化提示词
- **必须从段落 0 开始**（除非是纯语气词）
- **意译**：翻译要通顺自然，传达意思而非逐字翻译
- **窗口大小 = 6**：每次处理 6 个段落

### 3. 上下文衔接
- 向 LLM 传递上一轮翻译结果 `【上一轮翻译】`

**效果**: 100% 覆盖率，16 chunks 覆盖 40 个段落

---

## 数据模型设计

采用**链表式多表结构**，分离 ASR 原始结果、纠错后结果、语义块与翻译。

### 表结构概览

```
┌─────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   ASRSegment    │     │  ASRCorrectedSegment│     │   SemanticChunk     │
│   (ASR原始段落)  │────▶│  (ASR纠错段落)       │◀────│   (语义块+翻译)      │
├─────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│ id: int         │     │ id: int             │     │ id: int             │
│ start: float    │     │ asr_segment_id: int │     │ text: str           │
│ end: float      │     │ text: str (纠正后)   │     │ translation: str    │
│ text: str       │     └─────────────────────┘     │ asr_segment_ids: [] │
└─────────────────┘                                 └─────────────────────┘
```

### 1. ASRSegment (ASR 原始段落表)

存储 ASR 识别的原始结果，**不可变**，作为时间戳的权威来源。

```python
@dataclass
class ASRSegment:
    id: int              # 段落编号，从 0 开始
    start: float         # 开始时间 (秒)
    end: float           # 结束时间 (秒)
    text: str            # ASR 识别的原始文本 (未纠错)
```

### 2. ASRCorrectedSegment (ASR 纠错段落表)

存储经过 LLM 纠错后的段落文本，1:1 对应 `ASRSegment`（由 Stage 4 产出，供导出阶段作为子字幕使用）。

```python
@dataclass
class ASRCorrectedSegment:
    id: int                        # 纠错段落编号
    asr_segment_id: int            # 关联的 ASRSegment.id
    text: str                      # 纠错后的完整文本（由 LLM 直接输出）
```

> [!IMPORTANT]
> **废弃替换式纠错**：不再使用 `corrections` 替换对，LLM 直接输出纠错后的完整文本。
> 原因：简单字符串替换会导致错误（如 "is" -> "it's" 会把 "this" 变成 "thit's"）。

### 3. SemanticChunk (语义块表)

语义切分后的翻译单元，包含翻译结果。

```python
@dataclass
class SemanticChunk:
    id: int                      # 语义块编号
    text: str                    # 语义块内容 (纠错后原文)
    translation: str             # 翻译结果 (Pass 2 直接产出)
    asr_segment_ids: list[int]   # 关联的 ASRSegment.id 列表
```

---

## Pass 1: 全局理解 (Global Understanding)

**目标**：建立全局认知，提取关键信息指导后续切分与翻译。

**Token 限制**：
- 总请求 ≤ 8000 tokens
- Transcript 输入 ≤ 6000 tokens
- 超限时智能采样：开头 2000 + 中间 2000 + 结尾 2000 tokens

**输出** (JSON)：
```json
{
  "topic": "视频主题",
  "domain": "技术/教育/娱乐/...",
  "style": "正式/非正式/技术",
  "glossary": {"source_term": "目标翻译"},
  "translation_notes": ["注意事项"]
}
```

---

## Pass 2: 语义切分 + 翻译 (Semantic Chunking with Translation)

**目标**：以贪心串行方式处理（已纠错的）ASR 段落，每次提取一个语义完整的块，并完成翻译。

### 核心原则

1. **一步到位**：切分与翻译在同一次 LLM 调用中完成
2. **贪心串行**：每次只处理一个语义块，cursor 前进，直到处理完所有段落
3. **语义完整**：每块表达一个完整意思，便于翻译
4. **完整覆盖**：保证段落不遗漏；未进入 chunk 的段落在导出阶段仍会逐段输出（主字幕可能为空）

### 贪心串行流程

```
cursor = 0
while cursor < len(asr_segments):
    window = asr_segments[cursor : cursor + WINDOW_SIZE]
    result = LLM(window, context)
    
    # 1. 创建语义块（已包含翻译）
    create_semantic_chunk(result.translation, result.asr_segment_ids)
    
    # 2. 前进 cursor（系统自动计算 max(asr_segment_ids) + 1）
    cursor = next_cursor
```

### System Prompt (优化版)

> [!IMPORTANT]
> **优化要点**：
> - `next_cursor` 由系统自动计算（`max(asr_segment_ids) + 1`），无需 LLM 输出
> - LLM 收到上一个语义块作为上下文参考

````text
从 ASR 段落提取第一个语义完整的翻译单元。

规则：
1. 必须从段落0开始（除非是纯语气词如um/uh则跳过）
2. 延伸到语义完整为止
3. 意译：翻译要通顺自然，传达意思而非逐字翻译
4. 删除幻觉（如 transcribe the speech）

只输出 JSON：
```json
{
  "translation": "意译结果",
  "asr_segment_ids": [0, 1, 2]
}
```
````

> 说明：实现层兼容 legacy 的 `chunk` 包装结构，方便逐步迁移。

### 上一语义块上下文

从第二个窗口开始，user input 中会包含上一个语义块的原文和译文，帮助 LLM 保持衔接：

```
上一个语义块（保持衔接）：
- 原文: Pretty soon, version nine is coming out.
- 译文: 版本9很快就要发布了。
```

### User Input (动态内容)

````text
目标语言：en

【上一轮翻译】版本9很快就要发布了。

全局上下文：
{"topic":"人工智能应用","domain":"技术","style":"技术","glossary":{"人工智能":"AI","机器学习":"machine learning"},"translation_notes":["术语要保持一致，尽量口语化、适合字幕显示"]}

ASR 段落：
[
  {"id": 0, "start": 0.0, "end": 1.2, "text": "嗯"},
  {"id": 1, "start": 1.2, "end": 2.0, "text": "那个"},
  {"id": 2, "start": 2.0, "end": 3.6, "text": "我们今天聊人工只能"},
  {"id": 3, "start": 3.6, "end": 5.0, "text": "的应用场景"}
]
````

### LLM 输出示例

**示例**
```json
{
  "translation": "Today we'll discuss AI application scenarios",
  "asr_segment_ids": [2, 3]
}
```

---

## 字幕导出

每个 **ASR 段落单独成行**，共享其所属 `SemanticChunk` 的翻译（如果存在），并输出对应段落的纠错后原文：

- `start/end`：始终来自 `ASRSegment`（时间戳权威来源）
- `primary_text`：该段落所属语义块的翻译（可为空）
- `secondary_text`：该段落的纠错后原文

```python
def export_subtitle_per_asr_segment(
    chunks: list[SemanticChunk],
    asr_segments: list[ASRSegment],
    corrected: dict[int, ASRCorrectedSegment],
) -> str:
    # Build segment_id -> chunk mapping
    chunk_by_seg_id: dict[int, SemanticChunk] = {}
    for chunk in chunks:
        for seg_id in chunk.asr_segment_ids:
            chunk_by_seg_id[seg_id] = chunk

    subtitles = []
    for seg in asr_segments:
        corr = corrected.get(seg.id)
        chunk = chunk_by_seg_id.get(seg.id)
        translation = (chunk.translation if chunk is not None else "") or ""
        source = (corr.text if corr is not None else seg.text) or ""
        subtitles.append({
            "start": seg.start,
            "end": seg.end,
            "translation": translation,
            "source": source,
        })
    return format_as_srt(subtitles)
```

---

## JSON 解析与重试

所有 Pass 的 LLM 输出支持：
1. **Markdown 代码块**：自动提取 ```json ... ``` 中的内容
2. **重试机制**：解析失败最多重试 3 次，追加错误提示

---

## 附录：完整数据流示例

```
输入 ASRSegment[]:
  [0] start=0.0, end=1.2, text="嗯"
  [1] start=1.2, end=2.0, text="那个"
  [2] start=2.0, end=3.6, text="我们今天聊人工只能"
  [3] start=3.6, end=5.0, text="的应用场景"

Pass 1 输出:
  GlobalContext: topic="人工智能", domain="技术", glossary={...}

Pass 2 LLM 输出 (贪心串行，一次调用):
  translation="Today we'll discuss AI application scenarios"
  asr_segment_ids=[2, 3]

Stage 4（ASR 纠错）应用后 ASRCorrectedSegment[]:
  [0] asr_segment_id=0, text="嗯"
  [1] asr_segment_id=1, text="那个"
  [2] asr_segment_id=2, text="我们今天聊人工智能"  # 示例：来自 Stage 4
  [3] asr_segment_id=3, text="的应用场景"

SemanticChunk[]:
  [0] text="我们今天聊人工智能的应用场景"
      translation="Today we'll discuss AI application scenarios"
      asr_segment_ids=[2, 3]

字幕导出:
  # 每个段落单独成行，共享同一个 translation
  1
  00:00:02,000 --> 00:00:03,600
  Today we'll discuss AI application scenarios
  我们今天聊人工智能

  2
  00:00:03,600 --> 00:00:05,000
  Today we'll discuss AI application scenarios
  的应用场景
```
