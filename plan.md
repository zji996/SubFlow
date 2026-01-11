# SubFlow 前端预览与清理优化计划

## 背景

后端已完成数据落库（`projects.media_files`、`asr_merged_chunks` 表），并新增了预览 API：
- `GET /projects/{id}/preview` - 返回统计信息和 VAD regions
- `GET /projects/{id}/preview/segments` - 分页返回 ASR 段落及关联的语义块/翻译

前端已有 `PreviewPage.tsx` 组件和 API 客户端 `preview.ts`，但存在以下问题需修复。

---

## 任务 1：修复预览页面数据加载

### 问题
- 时间轴视图显示空白
- ASR 段落显示 `(0 / 0)`

### 目标
确保前端正确调用后端 API 并渲染数据。

### 约束
- 检查 `PreviewPage.tsx` 中 API 调用逻辑
- 检查 `preview.ts` 中接口定义是否与后端响应匹配
- 后端 API 定义在 `apps/api/routes/projects.py` 的 `get_project_preview` 和 `get_project_preview_segments` 函数

### 验收标准
- 时间轴正确显示 VAD regions 色块
- 段落列表正确显示 ASR 段落数量和内容
- 点击时间轴 region 可筛选对应段落

---

## 任务 2：修复语义分段显示

### 问题
后端 LLM 已实现语义均分（`translation_chunks`），但前端段落数量与后端不一致。

### 背景知识
- 后端 `semantic_chunks` 表存储语义块，每个语义块关联多个 `asr_segment_ids`
- 后端 `translation_chunks` 表存储翻译分段，每个翻译分段关联多个 `segment_ids`
- 前端应展示：ASR 段落 → 所属语义块 → 该段落对应的翻译片段

### 目标
前端正确展示每个 ASR 段落对应的翻译片段（`translation_chunk_text`）。

### 约束
- 检查后端 `/preview/segments` 响应中 `semantic_chunk.translation_chunk_text` 字段
- 确保前端正确解析并显示该字段

### 验收标准
- 每个 ASR 段落展开后显示完整翻译和对应片段
- 翻译片段与 ASR 段落数量逻辑一致

---

## 任务 3：移除调试产物（Debug Artifacts）

### 问题
前端项目详情页仍显示 `stage1.json`、`asr_merged_chunks.json` 等调试产物，但这些数据已落库。

### 目标
完全移除调试产物的显示，因为：
1. 数据已落库到 PostgreSQL
2. 有更友好的预览页面可查看

### 需要清理的内容

**前端**：
- `ProjectDetailPage.tsx` 中的调试产物 `<details>` 区块（约第 353-385 行）
- `handlePreviewArtifact` 函数及相关状态
- `api/projects.ts` 中的 `getArtifactContent` 函数（如不再使用）

**后端**（可选，低优先级）：
- `apps/api/routes/projects.py` 中的 `get_artifact_content` 端点可考虑保留用于调试，或移除

### 验收标准
- 项目详情页不再显示任何 artifact 相关内容
- 无 TypeScript 编译错误
- 移除未使用的 import 和函数

---

## 任务 4：清理相关代码

### 目标
确保代码整洁，无死代码。

### 需检查
- `artifactPreview`、`artifactLoading`、`artifactError` 等状态变量
- `getArtifactContent` API 函数
- 相关的 Modal 或预览 UI 组件

### 验收标准
- `npm run build` 无警告
- 代码无未使用的变量和函数

---

## 执行顺序建议

1. **任务 1** - 修复预览页面（最高优先级，用户可见）
2. **任务 3 + 4** - 移除调试产物并清理代码
3. **任务 2** - 检查语义分段显示（依赖任务 1 完成后验证）

---

## 测试方法

```bash
# 构建前端
cd apps/web && npm run build

# 重启服务
bash scripts/manager.sh restart web

# 访问预览页面
# http://localhost:5173/projects/{projectId}/preview
```

---

*创建时间: 2026-01-11*
