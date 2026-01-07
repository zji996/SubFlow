# 后端适配前端需求计划

## 目标

根据 `frontend_plan.md` 的前端需求，确认并调整后端 API / 数据库 / MinIO 等基础设施。

---

## 1. 现状确认（探索任务）

### 1.1 数据库

确认当前项目存储方式：
- 查看 `libs/subflow/subflow/models/project.py` 中 `Project` 数据模型
- 查看是否使用数据库（Postgres/SQLite）还是文件存储
- 确认 `docker-compose.dev.yml` 中数据库配置

**需确认字段**：
- `id`, `name`, `media_url` ✓ 已有
- `source_language` - 是否已有？
- `target_language` - 是否已有？
- `auto_workflow` - 是否已有？（新增）
- `status` - 是否已有？枚举值是什么？
- `current_stage` - 是否已有？
- `created_at` - 是否已有？（日期分组需要）

### 1.2 MinIO / 对象存储

确认当前文件存储方式：
- 查看 `libs/subflow/subflow/storage/` 目录
- 确认是否使用 MinIO 还是本地文件
- 查看 `docker-compose.dev.yml` 中 MinIO 配置

### 1.3 现有 API

查看 `apps/api/routes/projects.py` 确认现有 API：
- `POST /api/projects` - 创建项目
- `GET /api/projects` - 列表
- `GET /api/projects/{id}` - 详情
- `POST /api/projects/{id}/run` - 运行下一阶段
- `POST /api/projects/{id}/run-all` - 运行全部
- `GET /api/projects/{id}/artifacts/{stage}` - 获取阶段产物
- `GET /api/projects/{id}/subtitles` - 获取字幕
- `DELETE /api/projects/{id}` - 删除

---

## 2. 需新增/修改的功能

### 2.1 Project 模型扩展

新增字段：
```python
@dataclass
class Project:
    # 现有字段
    id: str
    name: str
    media_url: str
    status: ProjectStatus
    current_stage: int
    
    # 需确认/新增
    source_language: str | None  # 可选，自动检测
    target_language: str         # 必选
    auto_workflow: bool = True   # 工作流模式，默认自动
    created_at: datetime         # 创建时间（日期分组需要）
    updated_at: datetime         # 更新时间
```

### 2.2 API 扩展

#### 2.2.1 创建项目 API 扩展

`POST /api/projects`

新增请求字段：
```json
{
  "name": "项目名",
  "media_url": "...",
  "source_language": "en",      // 可选
  "target_language": "zh",      // 必选
  "auto_workflow": true         // 新增
}
```

#### 2.2.2 字幕下载 API（新增/扩展）

`GET /api/projects/{id}/subtitles/download`

Query 参数：
- `format`: `srt` | `vtt` | `ass`
- `content`: `both` | `primary_only` | `secondary_only`
- `primary_position`: `top` | `bottom` (当 content=both)

ASS 格式额外参数：
- `primary_font`: 字体名
- `primary_size`: 字号
- `primary_color`: 颜色（十六进制）
- `secondary_font`: 字体名
- `secondary_size`: 字号
- `secondary_color`: 颜色

Response: 文件流下载

#### 2.2.3 字幕预览 API（新增）

`GET /api/projects/{id}/subtitles/preview`

Query 参数：同上

Response:
```json
{
  "entries": [
    {
      "index": 1,
      "start": "00:00:05,000",
      "end": "00:00:08,000",
      "primary": "大家好，欢迎收看...",
      "secondary": "What is going on..."
    }
  ],
  "total": 19
}
```

### 2.3 字幕导出器扩展

查看 `libs/subflow/subflow/export/subtitle_exporter.py`：
- 确认是否支持 SRT / VTT / ASS
- ASS 是否支持自定义样式
- 如不支持，需扩展

### 2.4 ASS 样式支持

新增 ASS 样式配置模型：
```python
@dataclass
class AssStyleConfig:
    primary_font: str = "思源黑体"
    primary_size: int = 36
    primary_color: str = "#FFFFFF"
    primary_outline_color: str = "#000000"
    primary_outline_width: int = 2
    
    secondary_font: str = "Arial"
    secondary_size: int = 24
    secondary_color: str = "#CCCCCC"
    secondary_outline_color: str = "#000000"
    secondary_outline_width: int = 1
    
    position: str = "bottom"  # top | bottom
    margin: int = 20
```

---

## 3. 实施任务

### 3.1 模型层
- [ ] 确认 `Project` 模型现有字段
- [ ] 新增 `auto_workflow` 字段
- [ ] 确认 `created_at` 字段存在
- [ ] 新增 `AssStyleConfig` 模型

### 3.2 存储层
- [ ] 确认 MinIO / 本地存储配置
- [ ] 确认项目文件存储结构

### 3.3 导出器
- [ ] 确认 SRT / VTT 支持
- [ ] 扩展 ASS 格式支持（带样式）
- [ ] 新增 `content` 选项（both/primary_only/secondary_only）

### 3.4 API 层
- [ ] 扩展 `POST /api/projects` 请求体
- [ ] 新增 `GET /api/projects/{id}/subtitles/download`
- [ ] 新增 `GET /api/projects/{id}/subtitles/preview`

### 3.5 工作流逻辑
- [ ] 确认 `auto_workflow` 模式下 Stage 1-6 自动运行
- [ ] 确认手动模式下每阶段暂停

---

## 4. 验证

```bash
# 测试
uv run --project apps/worker --directory apps/worker --group dev pytest -v

# 类型检查
uv run --project libs/subflow --directory libs/subflow --group dev mypy .

# API 测试
uv run --project apps/api --directory apps/api --group dev pytest -v
```

---

## 5. 输出

完成后请总结：
1. 当前后端支持情况（哪些已有，哪些需新增）
2. 已完成的修改
3. 需要注意的问题

**前端实现将由用户交给另一个助手完成，本任务只做后端适配。**
