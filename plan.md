# API 路由拆分优化计划

## 背景

当前 `apps/api/routes/projects.py` 文件有 **1288 行**，包含多种功能域的路由处理逻辑。虽然不存在架构层面的耦合问题，但文件过大影响了代码的可维护性和可读性。

## 目标

将 `projects.py` 按功能域拆分为多个独立的路由文件，保持 API 路径不变（`/projects/*`），同时提升代码组织结构。

## 拆分方案

### 目标文件结构

```
apps/api/routes/
├── __init__.py
├── projects/              # 新建目录
│   ├── __init__.py        # 导出 router
│   ├── core.py           # 项目核心 CRUD（约 150 行）
│   ├── execution.py      # Pipeline 执行相关（约 100 行）
│   ├── preview.py        # 项目预览/段落查询（约 250 行）
│   ├── artifacts.py      # Artifact 查询（约 80 行）
│   ├── exports.py        # 导出历史管理（约 400 行）
│   └── subtitles.py      # 字幕预览/下载/编辑（约 250 行）
├── uploads.py            # 保持不变
```

### 功能划分

| 文件 | 端点 | 职责 |
|------|------|------|
| **core.py** | `POST /`, `GET /`, `GET /{id}`, `DELETE /{id}` | 项目 CRUD |
| **execution.py** | `POST /{id}/run`, `POST /{id}/run-all` | Pipeline 执行触发 |
| **preview.py** | `GET /{id}/preview`, `GET /{id}/preview/segments` | 项目预览与段落分页 |
| **artifacts.py** | `GET /{id}/artifacts/{stage}`, `GET /{id}/artifacts/{stage}/{name}` | Artifact 内容查询 |
| **exports.py** | `GET /{id}/exports`, `POST /{id}/exports`, `GET /{id}/exports/{eid}`, `GET /{id}/exports/{eid}/download` | 导出历史 CRUD 与下载 |
| **subtitles.py** | `GET /{id}/subtitles/preview`, `GET /{id}/subtitles/edit-data`, `GET /{id}/subtitles/download` | 字幕实时预览与下载 |

### 共享依赖处理

创建 `projects/_deps.py` 或直接在 `__init__.py` 中提供共享工具：

1. **辅助函数**：
   - `_service(request)` → 获取 `ProjectService`
   - `_pool(request)` → 获取数据库连接池
   - `_to_response(project)` → 转换为 `ProjectResponse`
   - `_safe_filename_base(value)` → 安全文件名处理
   - `_load_subtitle_materials(pool, project_id)` → 加载字幕素材

2. **Pydantic Models**：
   - 保留在各自文件中，或提取到 `projects/schemas.py`

### 路由挂载方式

```python
# apps/api/routes/projects/__init__.py
from fastapi import APIRouter

from .core import router as core_router
from .execution import router as execution_router
from .preview import router as preview_router
from .artifacts import router as artifacts_router
from .exports import router as exports_router
from .subtitles import router as subtitles_router

router = APIRouter(prefix="/projects", tags=["projects"])

router.include_router(core_router)
router.include_router(execution_router)
router.include_router(preview_router)
router.include_router(artifacts_router)
router.include_router(exports_router)
router.include_router(subtitles_router)
```

```python
# apps/api/main.py（修改）
from routes.projects import router as projects_router  # 路径不变
```

## 实施步骤

### 阶段 1：创建目录结构
- 创建 `routes/projects/` 目录
- 创建 `__init__.py` 和各子模块文件
- 创建 `_deps.py` 放置共享依赖

### 阶段 2：提取共享代码
- 将 Pydantic models 提取到 `schemas.py`
- 将辅助函数提取到 `_deps.py`

### 阶段 3：拆分路由
按以下顺序拆分（从简单到复杂）：
1. `artifacts.py` - 最简单，约 80 行
2. `core.py` - CRUD 操作，约 150 行
3. `execution.py` - 执行触发，约 100 行
4. `preview.py` - 预览查询，约 250 行
5. `subtitles.py` - 字幕操作，约 250 行
6. `exports.py` - 最复杂，约 400 行

### 阶段 4：更新入口
- 更新 `routes/projects/__init__.py` 组合所有路由
- 确保 `main.py` 导入路径正确

### 阶段 5：验证与清理
- 运行现有测试确保 API 兼容性
- 删除旧的 `routes/projects.py`

## 验收标准

1. **API 兼容**：所有现有端点路径、请求/响应格式保持不变
2. **测试通过**：`apps/api/tests/` 下所有测试通过
3. **代码行数**：每个子模块不超过 400 行
4. **无循环依赖**：模块间无循环导入

## 风险与注意事项

1. **导入路径变更**：其他模块如果直接从 `routes.projects` 导入，需要更新
2. **共享状态**：`_service()` 等工厂函数需确保在新模块中可访问
3. **类型提示**：拆分后需确保类型提示完整

## 优先级

**低** - 这是代码组织优化，不影响功能。建议在以下情况执行：
- 需要为 `routes/` 添加新功能时
- 有空闲时间进行技术债务清理时
