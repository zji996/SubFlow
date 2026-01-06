# SubFlow Codex 实现计划

> 本文档供 Codex 执行，每个 Task 可独立执行。参考 [architecture.md](./architecture.md) 获取设计细节。

---

## 项目状态速览

| 组件 | 状态 | 说明 |
|------|------|------|
| ASR Stage | ✅ 完成 | GLM-ASR 集成可用 |
| Audio Preprocess | ⚠️ Mock | 需要 FFmpeg + Demucs |
| VAD Stage | ⚠️ Mock | 需要 Silero VAD |
| LLM Passes(4个) | ⚠️ Mock | 需要真实 LLM 调用 |
| Export Formatters | ✅ 完成 | SRT/VTT/ASS |
| Storage Service | ❌ 缺失 | 需要 MinIO 集成 |
| Frontend | ❌ 缺失 | 需创建 Vite+React |

---

## Phase 1: Audio Processing

### Task 1.1: FFmpeg Provider

**创建文件**: `libs/subflow/providers/audio/ffmpeg.py`

**功能要求**:
```python
class FFmpegProvider:
    async def extract_audio(self, video_path: str, output_path: str) -> str:
        """从视频提取音频，输出 16kHz 单声道 WAV"""
        
    async def cut_segment(self, audio_path: str, start: float, end: float, output_path: str) -> str:
        """切割音频片段"""
```

**实现要点**:
- 使用 asyncio.create_subprocess_exec 调用 ffmpeg
- 输出格式: `-ar 16000 -ac 1 -f wav`
- 错误处理: 检查返回码

---

### Task 1.2: Demucs Provider

**创建文件**: `libs/subflow/providers/audio/demucs.py`

**功能要求**:
```python
class DemucsProvider:
    def __init__(self, model: str = "htdemucs_ft"):
        ...
        
    async def separate_vocals(self, audio_path: str, output_dir: str) -> str:
        """分离人声，返回 vocals.wav 路径"""
```

**实现要点**:
- 调用 `demucs --two-stems=vocals -n {model} {audio_path} -o {output_dir}`
- 等待进程完成
- 返回 `{output_dir}/{model}/{stem_name}/vocals.wav`

---

### Task 1.3: 更新 Audio Preprocess Stage

**修改文件**: `libs/subflow/stages/audio_preprocess.py`

**替换当前 Mock 实现**:
```python
class AudioPreprocessStage(Stage):
    def __init__(self, settings: Settings):
        self.settings = settings
        self.ffmpeg = FFmpegProvider()
        self.demucs = DemucsProvider(model=settings.demucs_model)
        
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        # 1. 下载/定位视频
        # 2. FFmpeg 提取音频
        # 3. Demucs 分离人声
        # 4. 返回 vocals_audio_path
```

---

## Phase 2: VAD

### Task 2.1: Silero VAD Provider

**创建文件**: `libs/subflow/providers/vad/silero_vad.py`

**功能要求**:
```python
class SileroVADProvider:
    def __init__(self, min_silence_duration_ms: int = 300, min_speech_duration_ms: int = 250):
        self.model, self.utils = torch.hub.load('snakers4/silero-vad', 'silero_vad')
        
    def detect(self, audio_path: str) -> list[tuple[float, float]]:
        """返回语音活动时间段 [(start, end), ...]"""
```

**实现要点**:
- 使用 torchaudio 加载音频
- 重采样到 16kHz
- 调用 `get_speech_timestamps`

---

### Task 2.2: 更新 VAD Stage

**修改文件**: `libs/subflow/stages/vad.py`

```python
class VADStage(Stage):
    def __init__(self, settings: Settings):
        self.provider = SileroVADProvider(
            min_silence_duration_ms=settings.vad.min_silence_duration_ms,
        )
        
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        timestamps = self.provider.detect(context["vocals_audio_path"])
        context["vad_segments"] = [VADSegment(start=s, end=e) for s, e in timestamps]
        return context
```

---

## Phase 3: LLM Passes

### Task 3.1: Global Understanding Pass

**修改文件**: `libs/subflow/stages/llm_passes.py` - `GlobalUnderstandingPass`

**Prompt 设计**:
```
你是一个专业的视频内容分析助手。请分析以下视频转录文本，提取：
1. 视频主题和领域
2. 语言风格 (正式/非正式/技术等)
3. 说话人信息
4. 核心术语表 (原文 -> 建议翻译)
5. 内容大纲
6. 翻译注意事项

以 JSON 格式输出。
```

**输出结构**:
```python
{
    "topic": str,
    "domain": str,
    "style": str,
    "speakers": list[str],
    "glossary": dict[str, str],
    "outline": list[str],
    "translation_notes": list[str]
}
```

---

### Task 3.2: Semantic Chunking Pass

**修改文件**: `libs/subflow/stages/llm_passes.py` - `SemanticChunkingPass`

**Prompt 设计**:
```
将以下 ASR 转录结果重组为语义完整的翻译单元。

切分原则：
1. 每个块表达一个完整的意思
2. 每块翻译后约 15-25 个中文字符
3. 保持时间映射关系

输入 ASR 段落:
{asr_segments}

以 JSON 数组格式输出，每项包含:
- id: 序号
- text: 原文
- start: 开始时间
- end: 结束时间
- source_segment_ids: 来源 ASR 段落 ID
```

---

### Task 3.3: Translation Pass

**修改文件**: `libs/subflow/stages/llm_passes.py` - `TranslationPass`

**实现策略**:
- 滑动窗口: 当前块 + 前后各 2 块上下文
- 术语表约束: 强制使用 global_context 中的 glossary
- 批量处理: 每次翻译 5-10 个块

---

### Task 3.4: QA Pass

**修改文件**: `libs/subflow/stages/llm_passes.py` - `QAPass`

**审校检查项**:
- 术语一致性
- 漏译检测
- 译文流畅度
- 长度合理性 (字幕显示)

---

## Phase 4: Storage

### Task 4.1: MinIO Storage Service

**创建文件**: `libs/subflow/services/storage.py`

```python
class StorageService:
    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str):
        ...
        
    async def upload_file(self, local_path: str, remote_key: str) -> str:
        """上传文件，返回 URL"""
        
    async def download_file(self, remote_key: str, local_path: str) -> str:
        """下载文件"""
        
    async def get_presigned_url(self, remote_key: str, expires_in: int = 3600) -> str:
        """生成预签名下载 URL"""
```

---

## Phase 5: Frontend

### Task 5.1: 初始化项目

```bash
cd apps
npx -y create-vite@latest web -- --template react-ts
cd web
npm install
npm install -D @tailwindcss/vite tailwindcss
npm install react-router-dom
```

**vite.config.ts 配置**:
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000'
    }
  }
})
```

**src/index.css**:
```css
@import "tailwindcss";
```

---

### Task 5.2: 核心页面

**创建文件结构**:
```
apps/web/src/
├── api/
│   ├── client.ts       # fetch wrapper
│   └── jobs.ts         # job API 调用
├── pages/
│   ├── HomePage.tsx    # 首页/上传
│   ├── JobsPage.tsx    # 任务列表  
│   └── JobDetailPage.tsx # 任务详情
├── components/
│   ├── Layout.tsx
│   ├── JobCard.tsx
│   ├── VideoUpload.tsx
│   └── SubtitlePreview.tsx
├── hooks/
│   └── usePolling.ts   # 状态轮询
├── App.tsx
└── main.tsx
```

---

## 执行顺序建议

1. Phase 1 (Audio) → 可独立测试
2. Phase 2 (VAD) → 依赖 Phase 1
3. Phase 3 (LLM) → 可并行开发
4. Phase 4 (Storage) → 可并行开发
5. Phase 5 (Frontend) → 可并行开发

---

*文档版本: 1.0*
*最后更新: 2026-01-06*
