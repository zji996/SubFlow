# SubFlow 测试覆盖率提升与代码质量改进计划

## 任务概述

对 SubFlow 项目进行全面的测试覆盖率提升和代码质量改进。这是一个长时间运行的任务，目标是显著提高项目的可维护性和可靠性。

## 当前状态

- 后端测试：32 个测试通过（`apps/worker/tests/`）
- 核心库位于 `libs/subflow/`
- 前端位于 `apps/web/`
- API 位于 `apps/api/`

---

## 任务一：后端单元测试补充（预计 2-3 小时）

### 目标

为核心库 `libs/subflow/` 中的关键模块添加单元测试，目标覆盖率达到 70%+。

### 重点测试模块

1. **Pipeline 模块**
   - `pipeline/orchestrator.py` - 测试 run_stage、run_all、错误处理、进度回调
   - `pipeline/stage_runners.py` - 测试各 Runner 的正确调用
   - `pipeline/context.py` - 测试 ProgressReporter 协议

2. **Stages 模块**
   - `stages/llm_passes.py` - 测试 GlobalUnderstandingPass、SemanticChunkingPass 的解析逻辑
   - `stages/llm_asr_correction.py` - 测试纠错逻辑
   - `stages/export.py` - 测试字幕导出配置处理

3. **Models 模块**
   - 测试 Project、StageRun、SubtitleExport 的序列化/反序列化
   - 测试 serializers.py 中的各类 deserialize 函数

4. **Export 模块**
   - `export/subtitle_exporter.py` - 测试各格式导出
   - `export/formatters/` - 测试 SRT、VTT、ASS、JSON 格式化器

### 测试方法

- 使用 pytest
- 使用 mock 隔离外部依赖（LLM API、文件系统）
- 使用 fixtures 共享测试数据
- 测试正常路径和边界情况

### 验收标准

- [ ] 新增测试文件位于 `libs/subflow/tests/`
- [ ] 所有新增测试通过
- [ ] 覆盖关键的错误处理路径
- [ ] 使用 `uv run --project libs/subflow pytest` 运行通过

---

## 任务二：API 集成测试（预计 1-2 小时）

### 目标

为 `apps/api/` 添加 API 集成测试，测试关键端点。

### 重点测试端点

1. **Projects CRUD**
   - POST /projects - 创建项目
   - GET /projects - 列表项目
   - GET /projects/{id} - 获取项目
   - DELETE /projects/{id} - 删除项目

2. **Exports API**（新增功能）
   - GET /projects/{id}/exports - 列表导出
   - POST /projects/{id}/exports - 创建导出
   - GET /projects/{id}/exports/{export_id}/download - 下载导出

3. **Subtitles API**
   - GET /projects/{id}/subtitles/preview
   - GET /projects/{id}/subtitles/download

### 测试方法

- 使用 FastAPI TestClient
- 使用 fakeredis 或 mock Redis
- 测试成功响应和错误响应（404、400、409 等）

### 验收标准

- [ ] 测试文件位于 `apps/api/tests/`
- [ ] 覆盖所有主要端点
- [ ] 测试认证/权限边界（如有）
- [ ] 使用 `uv run --project apps/api pytest` 运行通过

---

## 任务三：代码质量检查与修复（预计 1 小时）

### 目标

运行静态分析工具，修复发现的问题。

### 检查项

1. **类型检查**
   - 运行 mypy 或 pyright，修复类型错误
   - 补充缺失的类型注解

2. **代码风格**
   - 运行 ruff 检查代码风格
   - 修复警告（unused imports、formatting 等）

3. **文档字符串**
   - 为公共 API 补充 docstring
   - 重点：Pipeline、Stages、Export 模块

### 验收标准

- [ ] mypy/pyright 检查无错误或仅有已知的忽略项
- [ ] ruff 检查无错误
- [ ] 核心公共函数有 docstring

---

## 任务四：前端类型检查（预计 30 分钟）

### 目标

确保前端 TypeScript 代码类型安全。

### 检查项

1. 运行 `npm run build`（已包含 tsc）
2. 检查并修复任何 TypeScript 错误
3. 确保 API 类型定义与后端一致

### 验收标准

- [ ] `npm run build` 无错误
- [ ] 无 `any` 类型滥用
- [ ] API 响应类型与后端匹配

---

## 执行顺序建议

1. 先完成**任务三**（代码质量），以便后续测试基于干净的代码
2. 然后**任务一**（后端单元测试），这是最耗时的部分
3. 接着**任务二**（API 集成测试）
4. 最后**任务四**（前端类型检查）

---

## 重要约束

- **不要修改业务逻辑**：只添加测试和修复质量问题
- **不要引入新依赖**：使用现有的 pytest、mock 等
- **保持测试独立**：每个测试应能独立运行
- **优先覆盖核心路径**：时间不够时优先测试 Pipeline 和 Export

---

## 测试运行命令参考

```bash
# 后端核心库测试
uv run --project libs/subflow --directory libs/subflow --group dev pytest -v

# Worker 测试（已有）
uv run --project apps/worker --directory apps/worker --group dev pytest -v

# API 测试
uv run --project apps/api --directory apps/api --group dev pytest -v

# 前端构建检查
cd apps/web && npm run build
```

---

## 预期产出

完成后，项目应该：
1. 有更高的测试覆盖率（新增 30+ 测试）
2. 代码质量问题得到修复
3. 关键模块有完整的单元测试
4. API 端点有集成测试覆盖

---

*任务预计总时长：4-6 小时*  
*创建日期：2026-01-08*
