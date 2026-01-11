# SubFlow

> 🎬 基于语义理解的视频字幕翻译系统 | Semantic-Aware Video Subtitle Translation

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

## ✨ 特性

- **语义优先** - 按语义边界智能切分，而非机械时间切分
- **全局理解** - 翻译前通读全文，术语一致、上下文连贯
- **多 Pass 处理** - 6 阶段 Pipeline，层层精化
- **高质量人声** - Demucs 人声分离 + NeMo VAD + GLM-ASR

## 🏗️ 架构

```
视频 → 音频预处理 → VAD → ASR → ASR纠错 → 语义翻译 → 字幕导出
         ↓           ↓      ↓       ↓          ↓          ↓
      人声分离    时间戳   文本    LLM纠错    全局理解    SRT/VTT
```

详见 [架构设计](docs/architecture.md) | [数据库设计](docs/database.md) | [LLM 多 Pass](docs/llm_multi_pass.md)

## 🚀 快速开始

```bash
# 1. 启动依赖服务
cd infra && docker-compose -f docker-compose.dev.yml up -d && cd ..

# 2. 配置环境变量
cp .env.example .env  # 编辑填写 ASR/LLM API Key

# 3. 数据库迁移
uv run --project apps/api scripts/db_migrate.py

# 4. 一键启动
bash scripts/manager.sh up
```

- **API**: http://localhost:8100 ([Swagger](http://localhost:8100/docs))
- **Web**: http://localhost:5173

详见 [Quickstart](docs/quickstart.md)

## 📚 文档

| 文档 | 说明 |
|------|------|
| [Quickstart](docs/quickstart.md) | 本地开发完整指南 |
| [架构设计](docs/architecture.md) | 系统架构与设计理念 |
| [数据库设计](docs/database.md) | PostgreSQL-First 架构 |
| [LLM 多 Pass](docs/llm_multi_pass.md) | Stage 4/5 详解 |
| [开发规范](AGENTS.md) | Monorepo 结构与规范 |

## 🛠️ 技术栈

**音频**: FFmpeg, Demucs | **VAD**: NeMo MarbleNet | **ASR**: GLM-ASR  
**LLM**: GPT-4 / Claude | **后端**: FastAPI | **前端**: React + Vite  
**存储**: PostgreSQL + MinIO + Redis

## 📝 License

[Apache License 2.0](LICENSE)
