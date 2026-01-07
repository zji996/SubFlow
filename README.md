# SubFlow

> 🎬 基于语义理解的视频字幕翻译系统 | Semantic-Aware Video Subtitle Translation

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

## ✨ 特性

- **语义优先**：基于语义块切分，而非机械的时间切分
- **全局理解**：翻译前通读全文，确保术语一致性
- **多 Pass 处理**：理解 → 切分 → 翻译 → 审校，层层精化
- **高质量人声**：Demucs 人声分离，提升 ASR 准确率

## 🏗️ 架构

```
视频输入 → 音频预处理 → VAD切分 → ASR识别 → LLM多Pass → 字幕输出
              ↓            ↓          ↓           ↓           ↓
          人声分离     时间戳获取   文本转录    语义翻译    SRT/VTT/ASS
```

详细架构设计请参阅 [docs/architecture.md](docs/architecture.md)

## 📖 文档

| 文档 | 说明 |
|------|------|
| [架构设计](docs/architecture.md) | 系统整体架构与设计理念 |
| [Quickstart](docs/quickstart.md) | 本地开发一键启动（uv + manager） |
| [LLM 多 Pass](docs/llm_multi_pass.md) | Stage 4 提示词与数据模型 |
| [开发规范](AGENTS.md) | Monorepo 结构、Provider 设计、禁止事项 |

## 🚀 快速开始（本地开发）

```bash
# 一键启动（API + Worker + Web）
bash scripts/manager.sh up
```

- API: `http://localhost:8100`（Swagger: `http://localhost:8100/docs`）
- Web: `http://localhost:5173`

更多说明见 `docs/quickstart.md`。

## 🧪 测试与类型检查

```bash
# Worker tests
uv run --project apps/worker --directory apps/worker --group dev pytest -v

# Core lib type check
uv run --project libs/subflow --directory libs/subflow --group dev mypy .
```

## 🛠️ 技术栈

- **音频处理**: FFmpeg, Demucs (htdemucs_ft)
- **语音活动检测**: NeMo MarbleNet Frame-VAD
- **语音识别**: GLM-ASR-Nano-2512
- **语义处理**: LLM (GPT-4 / Claude / 本地模型)

## 📝 License

[Apache License 2.0](LICENSE)
