# VAD 数据结构简化与数据库落库优化计划

> **背景**：当前使用贪心句子对齐 ASR 模式后，`vad_segments` 与 `vad_regions` 实际存储相同内容，且数据已全面迁移到 PostgreSQL，但存在命名混乱和冗余。

---

## 一、问题诊断

### 1.1 当前状态

| 概念 | 代码现状 | 实际用途 |
|------|---------|---------|
| `vad_segments` | VADStage 输出 = `list(vad_regions)` | 仅用于向后兼容 |
| `vad_regions` | NeMo VAD 检测出的粗粒度语音区域 | **真正需要的数据** |
| `vad_frame_probs` | 帧级概率张量，存储为 `.bin` 文件 | 贪心句子对齐核心依赖 |
| `vad_segments` 表 | 存储 `vad_regions` 数据 | 命名与实际内容不符 |

### 1.2 冗余点

1. **Context 中的重复 key**：`vad_segments` 和 `vad_regions` 始终相同
2. **文档过时**：`architecture.md` 仍描述 `vad_segments.json`（细分片段），但实际已废弃
3. **数据库表名不准确**：`vad_segments` 表存储的是 `vad_regions`

---

## 二、优化目标

### 2.1 必须完成

- [ ] 统一术语：在代码和文档中只保留 `vad_regions`
- [ ] 更新数据库表名（或保留表名但统一代码层命名）
- [ ] 清理 `vad_segments` 相关的冗余 context key
- [ ] 更新 `architecture.md` Stage 2 输出描述

### 2.2 可选优化

- [ ] 评估 `vad_frame_probs.bin` 是否需要迁移到数据库 BYTEA 字段
- [ ] 清理 `audio_chunk_merger.py` 和 `vad_region_mapper.py` 中的兼容代码

---

## 三、详细任务

### Task 1: 代码层统一命名

**目标**：在 PipelineContext 中废弃 `vad_segments` key，统一使用 `vad_regions`

**探索范围**：
- `libs/subflow/subflow/stages/vad.py` - VADStage 输出
- `libs/subflow/subflow/stages/asr.py` - ASR 输入读取
- `libs/subflow/subflow/pipeline/orchestrator.py` - 恢复逻辑
- `libs/subflow/subflow/pipeline/stage_runners.py` - VADRunner 持久化
- `libs/subflow/subflow/pipeline/context.py` - PipelineContext 类型定义

**约束**：
- 保持对 `vad_segments` 的读取兼容（fallback），避免破坏正在运行的任务
- 优先写入 `vad_regions`，`vad_segments` 作为别名

**验收标准**：
- Stage 2 执行后，context 中只有 `vad_regions`（`vad_segments` 可选保留为别名）
- Stage 3（ASR）正常读取 `vad_regions` 工作

---

### Task 2: 数据库 Schema 评估

**目标**：决定是否重命名 `vad_segments` 表为 `vad_regions`

**探索范围**：
- `infra/migrations/001_init.sql` - 当前 schema
- `apps/api/routes/projects/preview.py` - API 查询
- `libs/subflow/subflow/repositories/vad_segment_repo.py` - Repository 层

**决策点**：
1. **方案 A**：新增迁移脚本 `ALTER TABLE vad_segments RENAME TO vad_regions`，同步修改 Repository 和索引
2. **方案 B**：保留表名 `vad_segments`，只在代码层使用 `vad_regions` 概念（降低迁移风险）

**建议**：倾向**方案 B**，因为：
- 表名变更需要停服迁移
- 表结构本身没问题，只是命名不精确
- 可以通过 Repository 命名和注释明确语义

**验收标准**：
- 做出决策并记录到 `docs/adr/` 或 `architecture.md`

---

### Task 3: 文档更新

**目标**：`architecture.md` Stage 2 输出描述与代码实际对齐

**当前描述（需修改）**：
```markdown
**输出 Artifact**:
- `vad_segments.json` (细分片段时间戳列表)
- `vad_regions.json` (非连续语音区域列表)
- `vad_frame_probs` (帧级概率张量，用于贪心句子对齐模式)
```

**目标描述**：
```markdown
**输出 Artifact**:
- `vad_regions` (PostgreSQL `vad_segments` 表，存储粗粒度语音区域)
- `vad_frame_probs.bin` (ArtifactStore，帧级概率张量，用于贪心句子对齐)
```

**探索范围**：
- `docs/architecture.md` - Stage 2 部分
- `docs/quickstart.md` - 如有提及 `vad_segments.json`

**验收标准**：
- 文档中不再提及 `vad_segments.json` 文件输出
- 明确说明数据落库位置

---

### Task 4: 清理冗余工具函数

**目标**：评估并简化 VAD 相关工具函数

**探索范围**：
- `libs/subflow/subflow/utils/vad_region_mapper.py` - 检查是否仍需要 `vad_segments` 参数
- `libs/subflow/subflow/utils/audio_chunk_merger.py` - 同上
- `libs/subflow/subflow/models/serializers.py` - `serialize_vad_segments` / `deserialize_vad_segments`

**约束**：
- 如果有外部调用依赖这些序列化函数，保留但标记为 deprecated

**验收标准**：
- 函数签名统一使用 `vad_regions`
- 移除或标记废弃的 `vad_segments` 相关函数

---

### Task 5: 测试覆盖

**目标**：确保重构后测试通过

**探索范围**：
- `apps/worker/tests/test_vad_stage_uses_vocals_audio_path.py`
- `apps/worker/tests/test_orchestrator.py`
- `libs/subflow/tests/test_serializers.py`
- `libs/subflow/tests/test_stage_runners.py`

**验收标准**：
- 所有现有测试通过（可能需要更新断言）
- 如有新增逻辑，补充对应测试

---

## 四、优先级排序

| 优先级 | 任务 | 风险 |
|--------|------|------|
| P0 | Task 3: 文档更新 | 低 - 纯文档 |
| P1 | Task 1: 代码层统一命名 | 中 - 需兼容处理 |
| P2 | Task 2: 数据库 Schema 评估 | 低 - 决策任务 |
| P3 | Task 4: 清理冗余工具函数 | 低 - 可选 |
| P3 | Task 5: 测试覆盖 | 低 - 随 Task 1 同步 |

---

## 五、后续考虑

### 5.1 vad_frame_probs 存储方式

**当前**：存储在 ArtifactStore（文件系统）

**是否迁移到数据库**：
- **优点**：统一查询，减少外部依赖
- **缺点**：BYTEA 字段可能很大（10 分钟视频约 30KB），增加数据库压力

**建议**：暂不迁移，帧级概率是临时使用数据，Stage 3 用完即丢弃

### 5.2 跨 Stage 数据清理

贪心句子对齐后，`sentence_segments` 替代了原来的 `vad_segments` 作为 ASR 切分边界。是否需要在 Stage 3 完成后清理 `vad_segments` 表数据？

**建议**：保留，因为：
1. 可用于调试和可视化
2. 重跑 Stage 3 时需要原始 VAD 数据

---

*计划版本: 1.0.0*
*创建时间: 2026-01-21*
