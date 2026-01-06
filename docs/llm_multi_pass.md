# Stage 4: LLM 多 Pass 处理 (Multi-Pass LLM Processing)

本文件从 `docs/architecture.md` 中拆出，用于集中描述 Stage 4 的提示词、输入/输出与各 Pass 的职责边界。

## 总览

**目标**：通过 **2 轮** LLM 处理，完成全局理解、语义块切分与翻译。

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
│全局理解  │  (术语表/领域/风格)                │语义切分+纠错+翻译│
│≤8K tok  │                                   │  贪心串行处理    │
└─────────┘                                   └─────────────────┘
```

**核心思想**：既然语义切分已经切出完整的语义句子，那么在同一步中完成翻译是最自然的——LLM 已经理解了上下文，无需再开一个 Pass。

**输入 Artifact**: `asr_results.json` + `full_transcript.txt`  
**输出 Artifact**: `translation_result.json` (语义块 + 翻译 + 时间戳)

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
│ text: str       │     │ corrections: []     │     │ asr_segment_ids: [] │
└─────────────────┘     │ is_filler: bool     │     └─────────────────────┘
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

存储经过 LLM 纠错后的段落文本，1:1 对应 `ASRSegment`。

```python
@dataclass
class ASRCorrectedSegment:
    id: int                        # 纠错段落编号
    asr_segment_id: int            # 关联的 ASRSegment.id
    text: str                      # 纠错后的文本
    corrections: list[Correction]  # 纠错详情列表
    is_filler: bool = False        # 是否为纯语气词段落

@dataclass
class Correction:
    original: str    # 原错误文本
    corrected: str   # 修正后文本
```

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

## Pass 2: 语义切分 + 纠错 + 翻译 (Semantic Chunking with Translation)

**目标**：以贪心串行方式处理 ASR 段落，每次提取一个语义完整的块，同时完成纠错和翻译。

### 核心原则

1. **一步到位**：切分、纠错、翻译在同一次 LLM 调用中完成
2. **贪心串行**：每次只处理一个语义块，cursor 前进，直到处理完所有段落
3. **语义完整**：每块表达一个完整意思，便于翻译
4. **跳过语气词**：纯语气词段落标记为 filler，不参与翻译
5. **仅谐音纠错**：只纠正 ASR 中的谐音字错误，不纠正断句、重复词等
6. **替换式纠错**：只输出 corrections 替换对，不输出完整纠错后文本

### 贪心串行流程

```
cursor = 0
while cursor < len(asr_segments):
    window = asr_segments[cursor : cursor + WINDOW_SIZE]
    result = LLM(window, context)
    
    # 1. 记录 filler 段落
    for id in result.filler_segment_ids:
        create_corrected_segment(id, is_filler=True)
    
    # 2. 应用纠错（通过字符串替换）
    if result.corrected_segments:  # 可选字段，可能不存在或为空
        for seg in result.corrected_segments:
            apply_corrections_by_replace(seg.asr_segment_id, seg.corrections)
    
    # 3. 创建语义块（已包含翻译）
    create_semantic_chunk(result.chunk)
    
    # 4. 前进 cursor
    cursor = result.next_cursor
```

### 纠错文本生成逻辑

由于 LLM 只输出 `corrections` 替换对，纠错后的文本需要通过字符串替换生成：

```python
def apply_corrections(original_text: str, corrections: list[Correction]) -> str:
    """Apply corrections to original ASR text via string replacement."""
    result = original_text
    for corr in corrections:
        result = result.replace(corr.original, corr.corrected)
    return result
```

### System Prompt

````text
你是一个专业的字幕切分、纠错与翻译助手。

任务：从给定窗口的 ASR 段落中，提取“第一个”语义完整、翻译友好的语义块（字幕翻译单元），并输出其翻译。

处理规则：
1) 跳过前置语气词：如“嗯”“那个”“就是”“然后”等无实际意义的填充词
2) ASR 纠错：**仅修正谐音字错误**，不修正断句错误、重复词、漏字等其他问题
3) 语义完整性：每块表达一个完整意思
4) 翻译友好：切分点便于目标语言自然表达
5) 长度适中：每块原文 10-30 词（翻译后约 15-40 汉字）
6) 时间对齐：输出必须保留与原始 ASR 段落的映射关系（asr_segment_ids）
7) 翻译：输出 chunk.translation，适合字幕显示；遵循 glossary 与 translation_notes

输出格式（JSON，仅输出第一个语义块；所有 id 都是窗口内相对序号；用 ```json ... ``` 包裹）：
```json
{
  "filler_segment_ids": [0, 1],
  "corrected_segments": [
    {
      "asr_segment_id": 2,
      "corrections": [
        {"original": "错误文本", "corrected": "正确文本"}
      ]
    }
  ],
  "chunk": {
    "text": "纠错后语义块原文",
    "translation": "翻译结果（字幕风格）",
    "asr_segment_ids": [2, 3]
  },
  "next_cursor": 4
}
```

说明：
- `filler_segment_ids`: 被跳过的语气词段落 ID（从当前窗口开头算起）
- `corrected_segments`: 可选字段，如果没有需要纠正的谐音字错误，可以省略该字段或设为空数组
- `corrections`: 只包含需要替换的 original 和 corrected 文本对，客户端通过字符串替换生成纠错后文本
- `chunk.asr_segment_ids`: 构成该语义块的 ASR 段落 ID
- `next_cursor`: 下一次应从 segments 中的哪个位置继续（相对于输入数组）
- 如果剩余全是语气词，chunk 可为 null，next_cursor 设为最后位置
````

### User Input (动态内容)

````text
目标语言：en

视频全局上下文（用于风格与术语一致性参考）：
```json
{
  "topic": "人工智能应用",
  "domain": "技术",
  "style": "技术",
  "glossary": {"人工智能": "AI", "机器学习": "machine learning"},
  "translation_notes": ["术语要保持一致，尽量口语化、适合字幕显示"]
}
```

窗口内 ASR 段落（id 为窗口内相对序号）：
```json
[
  {"id": 0, "start": 0.0, "end": 1.2, "text": "嗯"},
  {"id": 1, "start": 1.2, "end": 2.0, "text": "那个"},
  {"id": 2, "start": 2.0, "end": 3.6, "text": "我们今天聊人工只能"},
  {"id": 3, "start": 3.6, "end": 5.0, "text": "的应用场景"}
]
```
````

### LLM 输出示例

**示例 1：有谐音字纠错**
```json
{
  "filler_segment_ids": [0, 1],
  "corrected_segments": [
    {"asr_segment_id": 2, "corrections": [{"original": "人工只能", "corrected": "人工智能"}]}
  ],
  "chunk": {
    "text": "我们今天聊人工智能的应用场景",
    "translation": "Today we'll discuss AI application scenarios",
    "asr_segment_ids": [2, 3]
  },
  "next_cursor": 4
}
```

**示例 2：无纠错（corrected_segments 省略）**
```json
{
  "filler_segment_ids": [],
  "chunk": {
    "text": "这是一段没有错误的文本",
    "translation": "This is a text without errors",
    "asr_segment_ids": [0, 1]
  },
  "next_cursor": 2
}
```

---

## 字幕导出

通过 `asr_segment_ids` 查询时间戳：

```python
def export_subtitle(chunks: list[SemanticChunk], 
                    asr_segments: dict[int, ASRSegment]) -> str:
    subtitles = []
    for chunk in chunks:
        start = asr_segments[chunk.asr_segment_ids[0]].start
        end = asr_segments[chunk.asr_segment_ids[-1]].end
        subtitles.append({
            "start": start,
            "end": end,
            "text": chunk.translation
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
  corrected_segments: [{asr_segment_id: 2, corrections: [{人工只能→人工智能}]}]
  # 注意：segment 3 没有谐音错误，不在 corrected_segments 中

应用纠错后 ASRCorrectedSegment[]:
  [0] asr_segment_id=0, is_filler=true, text="嗯"
  [1] asr_segment_id=1, is_filler=true, text="那个"
  [2] text="我们今天聊人工智能", corrections=[{人工只能→人工智能}]
      (通过 "人工只能" -> "人工智能" 替换生成)
  [3] text="的应用场景", corrections=[]

SemanticChunk[]:
  [0] text="我们今天聊人工智能的应用场景"
      translation="Today we'll discuss AI application scenarios"
      asr_segment_ids=[2, 3]

字幕导出:
  start = ASRSegment[2].start = 2.0
  end = ASRSegment[3].end = 5.0

  1
  00:00:02,000 --> 00:00:05,000
  Today we'll discuss AI application scenarios
```
