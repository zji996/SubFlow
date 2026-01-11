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

### 1. 语义块翻译分段 (translation_chunks)
- **问题**：不同语言语序差异大，无法做到段落 1:1 对应翻译
- **解决**：改用 `translation_chunks`，每个 chunk 映射到一个或多个 `segment_ids`
- 翻译分段与意译语义一致，支持意译均分

### 2. 动态窗口机制
- **问题**：固定 6 个段落的窗口可能不足以表达完整语义
- **解决**：LLM 可返回 `need_more_context` 请求更大窗口
- 系统自动扩展窗口并重试，最大窗口 = 15 个段落

### 3. 上下文衔接
- 向 LLM 传递上一轮翻译结果 `【上一轮翻译】`

**效果**: 100% 覆盖率，语义块翻译自然流畅

---

## 分区级并行 (2026-01)

为提升 Stage 5 Pass 2 的吞吐，在启用 `PARALLEL_ENABLED=true` 时，会基于 `vad_regions` 之间的静音间隔（`PARALLEL_MIN_GAP_SECONDS`）将段落分区：

- **分区内**：保持原有贪心串行算法（继续使用 `【上一轮翻译】` 做上下文衔接）
- **分区间**：并行执行；分区首个窗口 **不携带** `【上一轮翻译】` 上下文
- **全局上下文**：Pass 1 产出的 `global_context` 对所有分区共享
- **chunk id**：合并分区结果后按时间顺序重新编号，确保连续

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
└─────────────────┘                                 │ translation_chunks  │
                                                    └─────────────────────┘
                                                              │
                                                              ▼
                                                    ┌─────────────────────┐
                                                    │ TranslationChunk    │
                                                    │ (翻译分段)           │
                                                    ├─────────────────────┤
                                                    │ segment_ids: []     │
                                                    │ text: str           │
                                                    └─────────────────────┘
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

### 3. TranslationChunk (翻译分段)

翻译的语义分段，每个分段映射到一个或多个 ASR 段落。用于实现"意译均分"功能。

```python
@dataclass
class TranslationChunk:
    text: str                    # 翻译片段（与意译语义一致）
    segment_ids: list[int]       # 关联的 ASRSegment.id 列表
```

> [!NOTE]
> **与 SegmentTranslation 的区别**：
> - `SegmentTranslation`：1 个段落 → 1 个翻译（1:1，语序依赖强）
> - `TranslationChunk`：1 个翻译片段 → N 个段落（1:N，语序无关）

### 4. SemanticChunk (语义块表)

语义切分后的翻译单元，包含完整翻译和翻译分段。

```python
@dataclass
class SemanticChunk:
    id: int                                   # 语义块编号
    text: str                                 # 语义块内容 (纠错后原文)
    translation: str                          # 完整意译 (Pass 2 直接产出)
    asr_segment_ids: list[int]                # 关联的 ASRSegment.id 列表
    translation_chunks: list[TranslationChunk]  # 翻译分段列表
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
5. **动态窗口**：LLM 可请求更多上下文，系统自动扩展窗口重试

### 贪心串行流程（支持动态窗口）

```python
DEFAULT_WINDOW_SIZE = 6
MAX_WINDOW_SIZE = 15

cursor = 0
window_size = DEFAULT_WINDOW_SIZE

while cursor < len(asr_segments):
    window = asr_segments[cursor : cursor + window_size]
    result = LLM(window, context)
    
    # 检查是否需要更多上下文
    if result.need_more_context:
        requested = result.need_more_context.additional_segments
        new_size = min(window_size + requested, MAX_WINDOW_SIZE)
        if new_size > window_size:
            window_size = new_size
            continue  # 不推进 cursor，用更大窗口重试
        # 已达最大窗口，强制处理当前结果
    
    # 创建语义块（已包含翻译）
    create_semantic_chunk(result.translation, result.translation_chunks)
    
    # 前进 cursor（系统自动计算 max(segment_ids) + 1）
    cursor = max(all_segment_ids) + 1
    window_size = DEFAULT_WINDOW_SIZE  # 重置窗口大小
```

### System Prompt (优化版)

> [!IMPORTANT]
> **核心设计要点**：
> - **translation_chunks 而非 segments**：翻译分段按语义切分，不是按原文段落 1:1 对应
> - **动态窗口**：LLM 可返回 `need_more_context` 请求更多段落
> - `next_cursor` 由系统自动计算，无需 LLM 输出
> - LLM 收到上一个语义块作为上下文参考

````text
你是一位专业的翻译专家。从 ASR 段落中提取第一个语义完整的翻译单元。

## 核心规则

1. **从段落0开始**（除非是纯语气词如 um/uh/嗯/那个 则跳过）
2. **延伸到语义完整为止**，形成一个自然的翻译单元
3. **意译优先**：翻译要通顺自然、信达雅，传达意思而非逐字翻译

## 翻译分段规则 (translation_chunks)

- 每个 chunk 是翻译的一个语义片段，映射到一个或多个 segment_ids
- 分段方式由目标语言的语序和语义决定，不必与原文段落一一对应
- 所有 chunks 拼接后 = 完整翻译 (translation)
- 所有 segment_ids 合并后 = 覆盖的段落范围

## 输出格式

**情况1：正常输出**
```json
{
  "translation": "完整意译",
  "translation_chunks": [
    {"text": "翻译片段1", "segment_ids": [0, 1]},
    {"text": "翻译片段2", "segment_ids": [2]}
  ]
}
```

**情况2：窗口不足，需要更多上下文**
```json
{
  "need_more_context": {
    "reason": "当前语义块未完成，句子在段落5处中断",
    "additional_segments": 4
  }
}
```

## 重要约束

- translation_chunks 的 segment_ids 合并后必须覆盖所有被选中的段落
- 如果窗口内所有段落都是语气词/填充词，返回空翻译并覆盖所有段落
- 只在确实无法形成完整语义时才请求更多上下文
````

> 说明：实现层兼容 legacy 的 `asr_segment_ids` 格式，方便逐步迁移。

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

**示例 1：正常输出（translation_chunks）**
```json
{
  "translation": "Today we'll discuss AI application scenarios",
  "translation_chunks": [
    {"text": "Today we'll discuss AI application scenarios", "segment_ids": [2, 3]}
  ]
}
```

> 注意：中文 "我们今天聊人工智能的应用场景" 翻译为英文时，语序相同，可以合并为一个 chunk。

**示例 2：语序调整需要多个 chunks**

假设原文段落：
- [0] "明天"
- [1] "我想去"
- [2] "北京"

```json
{
  "translation": "I want to go to Beijing tomorrow",
  "translation_chunks": [
    {"text": "I want to go to", "segment_ids": [1]},
    {"text": "Beijing", "segment_ids": [2]},
    {"text": "tomorrow", "segment_ids": [0]}
  ]
}
```

> 注意：中文 "明天我想去北京" → 英文 "I want to go to Beijing tomorrow"，语序不同，chunks 按目标语言语序排列。

**示例 3：请求更多上下文**
```json
{
  "need_more_context": {
    "reason": "句子在段落5处被截断：'如果我们考虑到...'，需要后续段落完成语义",
    "additional_segments": 3
  }
}
```

---

## 字幕导出

每个 **ASR 段落单独成行**，输出对应段落的纠错后原文。翻译文本根据 `translation_style` 配置：

| TranslationStyle | 描述 |
|------------------|------|
| `per_chunk` (默认) | 根据 `translation_chunks` 分配翻译；同一 chunk 覆盖的多个段落共享该 chunk 的翻译 |
| `full` | 每行显示完整意译 (`translation`)，语义块内所有段落共享 |

**per_chunk 分配逻辑**：
- 遍历 `translation_chunks`
- 每个 chunk 的翻译文本分配给其覆盖的所有 `segment_ids`
- 若一个段落被多个 chunk 覆盖（理论上不应发生），取第一个

- `start/end`：始终来自 `ASRSegment`（时间戳权威来源）
- `primary_text`：翻译文本（根据 style 选择）
- `secondary_text`：该段落的纠错后原文

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
  translation_chunks=[
    {text: "Today we'll discuss AI application scenarios", segment_ids: [2, 3]}
  ]

Stage 4（ASR 纠错）应用后 ASRCorrectedSegment[]:
  [0] asr_segment_id=0, text="嗯"
  [1] asr_segment_id=1, text="那个"
  [2] asr_segment_id=2, text="我们今天聊人工智能"  # 示例：来自 Stage 4
  [3] asr_segment_id=3, text="的应用场景"

SemanticChunk[]:
  [0] text="我们今天聊人工智能的应用场景"
      translation="Today we'll discuss AI application scenarios"
      asr_segment_ids=[2, 3]
      translation_chunks=[
        {text: "Today we'll discuss AI application scenarios", segment_ids: [2, 3]}
      ]

字幕导出 (translation_style=per_chunk):
  1
  00:00:02,000 --> 00:00:03,600
  Today we'll discuss AI application scenarios
  我们今天聊人工智能

  2
  00:00:03,600 --> 00:00:05,000
  Today we'll discuss AI application scenarios
  的应用场景

  (注：两个段落共享同一个 chunk 的翻译)

字幕导出 (translation_style=full):
  1
  00:00:02,000 --> 00:00:03,600
  Today we'll discuss AI application scenarios
  我们今天聊人工智能

  2
  00:00:03,600 --> 00:00:05,000
  Today we'll discuss AI application scenarios
  的应用场景
```
