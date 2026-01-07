# SubFlow 开发规范

## 目录结构

```
SubFlow/
├─ apps/           # 独立应用（各有 pyproject.toml）
│  ├─ api/         # REST API
│  └─ worker/      # 后台 Worker
├─ libs/subflow/   # 共享核心库
│  ├─ pipeline/    # 流水线编排
│  ├─ stages/      # 处理阶段
│  └─ providers/   # 外部服务适配器 (ASR/LLM/Audio)
├─ infra/          # Docker / docker-compose
├─ scripts/        # 脚本（无独立环境，借用 app）
├─ docs/           # 文档
├─ third_party/    # Git submodule（只作为引用/对照，不直接修改业务代码）
├─ models/         # 模型权重 (gitignored)
├─ data/           # 临时缓存 (gitignored)
└─ logs/           # 日志 (gitignored)
```

## 常用命令

```bash
# 确保使用 Astral 官方 uv（某些环境里 snap 版 uv 会异常）
source ~/.local/bin/env
uv --version

# Worker 依赖 demucs/torch/nemo，建议使用 Python 3.11（兼容性最好）
uv python install 3.11

# 依赖安装/同步（统一使用 uv，不使用 pip/poetry）
uv sync --project libs/subflow
uv sync --project apps/api
uv sync --project apps/worker

# 启动
uv run --project apps/api --directory apps/api uvicorn main:app --reload --port 8100
uv run --project apps/worker --directory apps/worker python main.py

# 测试
uv run --project apps/worker --directory apps/worker --group dev pytest

# 脚本（必须借用 app 环境）
uv run --project apps/worker scripts/xxx.py

# 一键启动（本地开发）
bash scripts/manager.sh up

# 代码质量（如项目已配置 ruff）
uv run --project apps/api --directory apps/api ruff check .
uv run --project apps/api --directory apps/api ruff format .
```

## 依赖引用

```toml
# apps/*/pyproject.toml
[project]
dependencies = ["subflow"]

[tool.uv.sources]
subflow = { path = "../../libs/subflow", editable = true }
```

```python
# 导入路径
from subflow.providers import get_asr_provider
```

## Provider 模式

ASR/LLM 通过抽象接口调用外部 API，配置驱动切换后端：

| Provider | 环境变量 | 可选值 |
|----------|---------|--------|
| ASR | `ASR_PROVIDER` | `glm_asr`, `whisper_api` |
| LLM | `LLM_FAST_PROVIDER` / `LLM_POWER_PROVIDER` | `openai`, `openai_compat`, `anthropic` |

## 禁止事项

- ❌ `apps/A` import `apps/B`
- ❌ `libs` import `apps`
- ❌ `scripts/` 包含 pyproject.toml
- ❌ 裸跑 `uv run scripts/xxx.py`
- ❌ 硬编码路径/密钥
- ❌ `.env` 提交 Git
- ❌ 新增顶层目录（除 `third_party/` 外）
- ❌ 直接修改 `third_party/`（如需更新 submodule，请用 submodule 机制/明确变更目的）
