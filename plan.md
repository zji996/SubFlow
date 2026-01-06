# LLM Pipeline 问题修复计划

本计划修复 Pass 2 语义切分中的 3 个核心问题。

---

## 问题分析

### 问题 1: ASR 幻觉未过滤
**现象**: Segment 0 包含 "So, can you transcribe the speech into a written format?" 这是 ASR 模型幻觉
**原因**: LLM 没有识别出这是无效内容
**解决**: 在 prompt 中添加 "ASR 幻觉检测" 规则，要求 LLM 标记明显不属于视频内容的段落

### 问题 2: 替换式纠错导致错误
**现象**: `{"original": "is", "corrected": "it's"}` 导致 "this" 变成 "thit's"
**原因**: 简单字符串替换会匹配到所有出现位置
**解决**: 废弃替换式纠错，改为让 LLM 直接输出纠错后的完整文本

### 问题 3: ASR 段落覆盖不完整
**现象**: 40 个 ASR 段落只有 ~25 个被 SemanticChunk 覆盖，导致字幕大量空白
**原因**: 贪心算法每次只提取"第一个"语义块，cursor 跳跃可能跳过内容
**解决**: 
  1. 修改 prompt 要求 LLM 保证完整覆盖
  2. 修改字幕导出逻辑：每个 ASR 段落单独成行，共享所属 SemanticChunk 的翻译

---

## 修改任务

### 1. 更新 docs/llm_multi_pass.md

#### 1.1 废弃替换式纠错，改为直接输出纠错后文本

修改 **数据模型设计** 部分：

```python
@dataclass
class ASRCorrectedSegment:
    id: int
    asr_segment_id: int
    text: str                      # 纠错后的完整文本（直接由 LLM 输出）
    is_filler: bool = False
    is_hallucination: bool = False # 新增：是否为 ASR 幻觉
```

删除 `corrections: list[Correction]` 字段和 `Correction` 类。

#### 1.2 修改 Pass 2 System Prompt

**新增规则**:
- ASR 幻觉检测：识别不属于视频内容的文本（如 ASR 模型的指令回复）
- 完整覆盖要求：确保所有 ASR 段落都被标记或包含在语义块中
- 直接输出纠错后文本：不再使用替换，而是直接输出 `text` 字段

**新 JSON 格式**:
```json
{
  "filler_segment_ids": [0, 1],
  "hallucination_segment_ids": [0],
  "corrected_segments": [
    {
      "asr_segment_id": 2,
      "text": "纠错后的完整文本"
    }
  ],
  "chunk": {
    "text": "语义块原文",
    "translation": "翻译结果",
    "asr_segment_ids": [2, 3]
  },
  "next_cursor": 4
}
```

#### 1.3 修改字幕导出逻辑

修改 **字幕导出** 部分，描述新的导出策略：

```
每个 ASR 段落输出一条字幕：
- 第一行：该段落所属 SemanticChunk 的翻译（如果存在）
- 第二行：该段落的纠错后原文

如果一个 SemanticChunk 包含多个 ASR 段落：
- 每个段落都单独成行
- 每行都显示相同的翻译
- 每行显示各自的原文

示例：
3
00:00:09,300 --> 00:00:11,160
测试版本几乎准备好了，大概如此，可能还需要一个月或一年。
The beta will be almost ready.

4
00:00:11,160 --> 00:00:14,300
测试版本几乎准备好了，大概如此，可能还需要一个月或一年。
Something like that, you know, who knows, it could be another month or year.
```

---

### 2. 修改 libs/subflow/subflow/models/segment.py

#### [MODIFY] ASRCorrectedSegment 类
- 移除 `corrections` 字段
- 移除 `Correction` 类
- 新增 `is_hallucination: bool = False` 字段

---

### 3. 修改 libs/subflow/subflow/stages/llm_passes.py

#### [MODIFY] SemanticChunkingPass._get_system_prompt()

更新 prompt 内容：
1. 添加 ASR 幻觉检测规则
2. 废弃替换式纠错，改为直接输出纠错后文本
3. 添加完整覆盖要求
4. 更新 JSON 输出格式

#### [MODIFY] SemanticChunkingPass._parse_result()

更新解析逻辑：
1. 解析 `hallucination_segment_ids` 字段
2. 直接使用 `corrected_segments[].text` 作为纠错后文本
3. 移除 `_apply_corrections` 方法

---

### 4. 修改 libs/subflow/subflow/export/subtitle_exporter.py

#### [MODIFY] SubtitleExporter.build_entries()

实现新的导出策略：
1. 遍历所有 ASR 段落（而非 SemanticChunk）
2. 查找每个段落所属的 SemanticChunk
3. 每个段落生成一条字幕，使用所属 chunk 的翻译
4. 跳过 hallucination 和 filler 段落

---

### 5. 修改 libs/subflow/subflow/pipeline/orchestrator.py

#### [MODIFY] _corrected_to_json() 和 _corrected_from_json()

更新序列化逻辑：
1. 移除 `corrections` 字段序列化
2. 添加 `is_hallucination` 字段序列化

---

### 6. 更新测试

#### [MODIFY] apps/worker/tests/test_semantic_chunking_pass_parse_result.py

更新测试用例以适应新的数据结构：
1. 移除 corrections 相关测试
2. 添加 hallucination_segment_ids 测试
3. 添加 text 直接输出测试

---

## 验证步骤

```bash
# 1. 运行现有测试
uv run --project apps/worker --directory apps/worker --group dev pytest

# 2. 重新处理测试项目
# 删除现有 LLM 和 export 产物
rm -rf data/projects/proj_7822e1229f344f9eb5b81c283c22df0c/llm
rm -rf data/projects/proj_7822e1229f344f9eb5b81c283c22df0c/export

# 3. 通过 API 重新运行 LLM 和 export 阶段
# POST /projects/{id}/run {"stage": "llm"}
# POST /projects/{id}/run {"stage": "export"}

# 4. 检查输出
cat data/projects/proj_7822e1229f344f9eb5b81c283c22df0c/export/subtitles.srt
```

**预期结果**:
- [ ] 没有 "thit's" 等替换错误
- [ ] ASR 幻觉 "So, can you transcribe..." 被过滤
- [ ] 每个 ASR 段落都有对应字幕（filler/hallucination 除外）
- [ ] 跨段落的语义块在相关段落上都显示相同翻译

---

## 执行顺序

1. 更新 `docs/llm_multi_pass.md` 文档
2. 修改 `segment.py` 数据模型
3. 修改 `llm_passes.py` 处理逻辑
4. 修改 `subtitle_exporter.py` 导出逻辑
5. 修改 `orchestrator.py` 序列化
6. 更新测试文件
7. 运行验证

---

*为 Codex 生成 - 请按顺序执行*
