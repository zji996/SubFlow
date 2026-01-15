# 贪心切分回退策略优化 + Stage 5 翻译并行化

> 目标：优化断句策略，支持批量并行翻译

---

## 1. 贪心切分回退策略优化

### 当前逻辑
```
10s 内找句末标点（。？！）
  ↓ 未找到
扩展到 15s 重试
  ↓ 仍无标点
强制在 15s 切分
```

**问题**：15s 作为单段太长，不适合字幕阅读

### 优化后逻辑
```
10s 内找句末标点（。？！；?!;.）
  ↓ 未找到
在 10s 内找第一个非整句标点（逗号 ,、，等）
  ↓ 仍未找到
扩展到 15s 找句末标点
  ↓ 仍未找到
在 15s 内找第一个非整句标点
  ↓ 仍未找到
强制在 15s 切分
```

### 标点分类

**整句标点 (sentence_endings)**：
```
。？！；?!;.
```

**非整句标点 (clause_endings)**：
```
，,、：:—–
```

### 代码改动

**文件**: `libs/subflow/subflow/utils/greedy_sentence_aligner.py`

**改动**:

1. 新增 `clause_endings` 配置项：
```python
@dataclass(frozen=True)
class GreedySentenceAlignerConfig:
    max_chunk_s: float = 10.0
    fallback_chunk_s: float = 15.0
    sentence_endings: str = "。？！；?!;."
    clause_endings: str = "，,、：:—–"  # 新增
    # ... 其他字段
```

2. 新增 `split_first_clause()` 函数（类似 `split_first_sentence`，但使用 `clause_endings`）

3. 修改 `greedy_sentence_align_region()` 逻辑：
```python
# 第一优先级：在 max_chunk_s 内找句末标点
sentence, _ = split_first_sentence(text, sentence_endings)
if sentence:
    # 正常处理
    ...

# 第二优先级：在 max_chunk_s 内找非整句标点
if not sentence:
    clause, _ = split_first_clause(text, clause_endings)
    if clause:
        sentence = clause  # 使用子句作为切分点
        
# 第三优先级：扩展到 fallback_chunk_s 找句末标点
if not sentence and chunk_end < region_end:
    extended_text = await transcribe_window(cursor, extended_end)
    sentence, _ = split_first_sentence(extended_text, sentence_endings)
    
# 第四优先级：在 fallback_chunk_s 内找非整句标点
if not sentence:
    clause, _ = split_first_clause(extended_text, clause_endings)
    if clause:
        sentence = clause

# 最后：强制切分
if not sentence:
    sentence = text.strip()
```

### 配置项

新增环境变量：
```env
GREEDY_SENTENCE_ASR_CLAUSE_ENDINGS=，,、：:—–
```

---

## 2. Stage 5 翻译并行化

### 当前逻辑
```
for segment in asr_segments:
    translation = await llm.translate(segment, previous_translation=last)
    # 串行，依赖上一句译文
```

**问题**：串行处理慢，但实际上贪心切分已保证合理断点，不再需要上下文衔接

### 优化后逻辑
```
# 1. 按完整句子分组（连续的 segments 可能组成一个完整意思）
sentence_groups = group_segments_by_sentence(asr_segments)
# 例如: [[seg0], [seg1, seg2], [seg3], ...]

# 2. 构建批量翻译任务
batches = build_translation_batches(sentence_groups, max_segments_per_batch=10)

# 3. 并行执行
async def translate_batch(batch):
    # 一次 LLM 调用翻译多段
    return await llm.translate_batch(batch)

results = await asyncio.gather(*[translate_batch(b) for b in batches])

# 4. 合并结果
translations = flatten(results)
```

### 批量翻译 Prompt

**System Prompt**:
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

**User Input 示例**:
```
目标语言：zh

全局上下文：
{"topic": "...", "glossary": {...}}

待翻译：
[0]: What is going on, everybody?
[1]: Welcome back to another video.
[2]: Today we're testing FSD Beta 9.
```

**LLM Output 示例**:
```
[0]: 大家好呀？
[1]: 欢迎回来观看新一期视频。
[2]: 今天我们来测试 FSD Beta 9。
```

### 分组策略

将 segments 按"完整句子"分组：
- 以句末标点结尾的 segment 作为一组的结尾
- 连续无句末标点的 segments 合并为一组

```python
def group_segments_by_sentence(segments, sentence_endings="。？！；?!;."):
    groups = []
    current_group = []
    for seg in segments:
        current_group.append(seg)
        # 如果以句末标点结尾，结束当前组
        if seg.text.rstrip()[-1:] in sentence_endings:
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)
    return groups
```

### 并发控制

复用现有 LLM 并发配置：
```env
CONCURRENCY_LLM_POWER=30
```

每个 batch 包含 5-10 段，由 semaphore 控制并发数

### 代码改动

**文件**: `libs/subflow/subflow/stages/llm_passes.py`

**改动**:

1. 去掉 `【上一轮翻译】` 逻辑
2. 新增 `_build_batch_user_input()` 方法
3. 新增批量翻译解析逻辑 `_parse_batch_translation()`
4. 修改 `execute()` 为并行批量处理

### 配置项

新增环境变量：
```env
LLM_TRANSLATION_BATCH_SIZE=10  # 每批翻译的段落数
```

---

## 3. 文档更新

### docs/llm_multi_pass.md

更新 Pass 2 描述：
- 移除 `【上一轮翻译】` 说明
- 添加批量翻译 prompt
- 添加并行处理说明

### docs/architecture.md

更新 Stage 5 说明：
- 添加并行翻译说明

---

## 4. 验收标准

### 贪心切分优化
- [ ] 10s 内优先找句末标点
- [ ] 10s 内无句末标点时，找逗号等非整句标点
- [ ] 扩展到 15s 时同样优先句末、其次非整句
- [ ] 单元测试覆盖各种边界情况

### 翻译并行化
- [ ] 批量翻译 prompt 正确
- [ ] 并行执行，无死锁
- [ ] 输出顺序正确
- [ ] 翻译质量不下降

### 文档
- [ ] llm_multi_pass.md 已更新
- [ ] architecture.md 已更新

---

## 5. 测试建议

### 单元测试

1. 贪心切分回退策略：
   - 10s 内有句号 → 按句号切
   - 10s 内无句号有逗号 → 按逗号切
   - 10s 内无标点，15s 有句号 → 按句号切
   - 15s 内无句号有逗号 → 按逗号切
   - 15s 内无标点 → 强制切

2. 批量翻译解析：
   - 正常输出解析
   - 格式错误处理

### 集成测试

使用 `assets/test_video/vocals.wav` 端到端测试

---

## 6. 收尾工作

完成以上改动后，请执行以下收尾任务：

1. **运行所有测试**：
   ```bash
   uv run --project libs/subflow --directory libs/subflow --group dev pytest
   uv run --project apps/api --directory apps/api --group dev pytest
   uv run --project apps/worker --directory apps/worker --group dev pytest
   ```

2. **更新 .env.example**：
   - 新增 `GREEDY_SENTENCE_ASR_CLAUSE_ENDINGS`
   - 新增 `LLM_TRANSLATION_BATCH_SIZE`

3. **清理废弃代码**：
   - 移除 `_get_user_input` 中的 `previous_translation` 参数
   - 移除相关的串行逻辑

4. **代码格式化**：
   ```bash
   uv run --project libs/subflow ruff format libs/subflow
   uv run --project apps/api ruff format apps/api
   uv run --project apps/worker ruff format apps/worker
   ```

5. **验证无 lint 错误**：
   ```bash
   uv run --project libs/subflow ruff check libs/subflow
   ```

---

// turbo-all
