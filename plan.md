# 修复流式响应的 Token 统计和并发统计问题

## 问题描述

改成流式响应后，OpenAI 兼容 Provider 的日志显示：
```
latency_ms=10185, prompt_tokens=None, completion_tokens=None, total_tokens=None
```

Token 统计全部为 `None`，并发统计也显示为 0。

## 根本原因分析

### 1. Token 统计问题

**文件**: `libs/subflow/subflow/providers/llm/openai_compat.py`

当前流式实现中，代码尝试从以下两个来源获取 token 统计：
1. `x-usage` 或 `x-openai-usage` 响应头（第 195 行）
2. 最后一个 SSE 事件的 `usage` 字段（第 241 行 `last_event`）

**问题**：
- 标准 OpenAI API 流式模式默认 **不返回** token 统计信息
- 需要显式添加 `stream_options: {"include_usage": true}` 参数
- 启用后，token 统计会在流的最后一个 chunk 中返回（`choices: []` 的特殊 chunk）

**参考**: OpenAI API 文档说明，当设置 `stream_options.include_usage: true` 时，最终 chunk 会包含完整的 usage 统计。

### 2. 并发统计问题

**相关文件**:
- `libs/subflow/subflow/pipeline/concurrency.py` - 并发追踪器
- `libs/subflow/subflow/stages/llm_passes.py` - LLM 阶段（第 152-154 行, 639-641 行等）

**问题**：并发统计依赖于从 `tracker.snapshot(service)` 获取的 `state.active` 和 `state.max`。

经核查，并发追踪逻辑本身是正确的。但问题可能出在：
1. `llm_calls_count` 统计依赖 `usage is not None`（第 150 行）：`"llm_calls_count": 1 if usage is not None else 0`
2. 如果 `usage` 为 `None`，则 `llm_calls_count` 计为 0
3. 这可能影响到 metrics 的正确记录

## 修复计划

### P0: 修复 OpenAI 兼容 Provider 流式 Token 统计

**文件**: `libs/subflow/subflow/providers/llm/openai_compat.py`

1. **在请求 payload 中添加 `stream_options`** (第 163-170 行)：
   ```python
   payload = {
       "model": self.model,
       "messages": [{...}],
       "temperature": temperature,
       "stream": True,
       "stream_options": {"include_usage": True},  # 新增
   }
   ```

2. **正确解析最终 chunk 中的 usage** (第 196-224 行)：
   - 当收到 `choices: []` 的 chunk 时，检查是否包含 `usage` 字段
   - 更新 `last_event` 的处理逻辑，确保从最终 chunk 正确提取 usage

3. **测试兼容性**：
   - 标准 OpenAI API ✓
   - vLLM 兼容端点（需确认是否支持 `stream_options`）
   - 其他 OpenAI 兼容服务（如 self-hosted）

### P1: 修复 LLM 调用计数逻辑

**文件**: `libs/subflow/subflow/stages/llm_passes.py`

当前逻辑（第 150 行）：
```python
"llm_calls_count": 1 if usage is not None else 0,
```

修改为：无论 usage 是否为 None，只要调用成功就计数为 1：
```python
"llm_calls_count": 1,
```

以及其他类似位置的修复（搜索 `llm_calls_count`）。

**文件**: `libs/subflow/subflow/stages/llm_asr_correction.py`

同样检查并修复该文件中的 `llm_calls_count` 逻辑。

### P2: 优化并发状态快照获取时机

确保在正确的时机获取 `tracker.snapshot()`，以反映真实的并发状态。

## 实现步骤

1. [ ] 修改 `openai_compat.py`：
   - 添加 `stream_options: {"include_usage": true}`
   - 确保正确解析最终 chunk 的 usage

2. [ ] 修改 `llm_passes.py`：
   - 搜索所有 `llm_calls_count` 并修复计数逻辑

3. [ ] 修改 `llm_asr_correction.py`：
   - 同上修复 `llm_calls_count`

4. [ ] 测试验证：
   - 使用 OpenAI API 测试 token 统计
   - 验证并发统计正确显示

## 验收标准

- [ ] 日志中 `prompt_tokens`, `completion_tokens`, `total_tokens` 正确显示数值
- [ ] `llm_calls_count` 正确计数每次 LLM 调用
- [ ] `active_tasks` 和 `max_concurrent` 正确反映并发状态
