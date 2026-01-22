# ADR: VAD Regions 命名统一与落库语义

- 日期：2026-01-21
- 状态：Accepted

## 背景

在引入「贪心句子对齐 ASR」后，Stage 2 的 `vad_segments` 与 `vad_regions` 在实际运行中长期保持相同（均为粗粒度语音区域）。同时，数据已迁移到 PostgreSQL，但表名 `vad_segments` 实际存储的是 `vad_regions`，造成命名混乱与冗余。

## 决策

1. **代码与文档统一术语为 `vad_regions`**：
   - PipelineContext 以 `vad_regions` 作为唯一写入的 key；
   - `vad_segments` 仅作为读取兼容的 legacy alias（fallback）。
2. **数据库保留表名 `vad_segments`（方案 B）**：
   - 继续使用现有表结构与索引，不新增停服迁移；
   - Repository 层以 `VADRegionRepository` 表达语义，但底层仍读写 `vad_segments` 表。
3. **region_id 规则**：
   - 落库时为每个 region 填充稳定的 `region_id`（默认与 region 顺序一致），以支持预览与聚合查询。

## 影响

- Stage 2 执行完成后，context 仅包含 `vad_regions`（不再重复写入 `vad_segments`）。
- API 在按 `region_id` 过滤 ASR segments 时，优先使用 `asr_merged_chunks.segment_ids` 进行映射；旧数据可回退到历史查询路径。
