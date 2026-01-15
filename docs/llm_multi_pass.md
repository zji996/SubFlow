# Stage 5: LLM 多 Pass 翻译 (Multi-Pass LLM Translation)

本文件描述 Stage 5 的两轮 LLM 处理：全局理解（Pass 1）+ 逐段翻译（Pass 2）。

## 总览

**目标**：在 Stage 4 完成 ASR 纠错之后，生成稳定、衔接自然、适合字幕阅读的逐段翻译。

```
ASR（纠错后） → Pass 1 全局理解 → Pass 2 逐段翻译（1:1）
```

## Pass 1：全局理解（保持不变）

**输入**：`full_transcript`（Stage 4 回写纠错后的完整文本）  
**输出**：`global_context`（topic/domain/style/glossary/translation_notes）

关键点：
- 限制输入 token（截断策略由实现控制）
- 输出为 JSON 对象

## Pass 2：逐段翻译（核心重构）

### 设计原则

- **1:1**：每个 `ASRCorrectedSegment`（或已回写到 `ASRSegment.text`）对应一个翻译
- **无需合并**：Stage 3 的句子级切分已尽量保证每段是完整句子
- **可并行**：不再依赖上一句译文，支持批量并行翻译
- **全局上下文**：复用 Pass 1 的 `global_context`

### System Prompt（翻译）

```
你是一位专业的翻译专家。将给定的多个句子翻译成目标语言。

## 规则
1. 意译优先：翻译要通顺自然，传达意思而非逐字翻译
2. 适合字幕：简洁明了，适合阅读
3. 保持顺序：按输入顺序输出翻译

## 输入格式
每行一个句子，格式为 "[id]: 句子内容"

## 输出格式
每行一个翻译，格式为 "[id]: 翻译内容"
```

### User Input（动态内容）

```
目标语言：zh

全局上下文：
{ "topic": "...", "domain": "...", "style": "...", "glossary": {...}, "translation_notes": [...] }

待翻译：
[0]: <句子1>
[1]: <句子2>
[2]: <句子3>
```

### 输出

模型只返回多行 **纯文本译文**（不需要 JSON），格式与输入一致：

```
[0]: <翻译1>
[1]: <翻译2>
[2]: <翻译3>
```

## 数据结构

Stage 5 的核心输出为逐段翻译：

```python
@dataclass
class SegmentTranslation:
    segment_id: int
    source_text: str
    translation: str
```

（实现层可复用/兼容既有的 `semantic_chunks` 存储，但每条仅对应一个 `segment_id`，不再依赖 `translation_chunks`。）

## 字幕导出（Stage 6 相关）

- 时间戳：来自 `ASRSegment.start/end`（权威）
- 主字幕：`SegmentTranslation.translation`
- 副字幕：`ASRCorrectedSegment.text`（无纠错则回退到 `ASRSegment.text`）
