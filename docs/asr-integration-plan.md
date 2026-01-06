# ASR 集成计划

## 目标

将 vLLM 托管的 GLM-ASR 集成到 SubFlow，充分利用其并发能力。

## vLLM GLM-ASR API 分析

### 请求格式
```bash
curl http://localhost:8000/v1/audio/transcriptions \
  -H "Authorization: Bearer abc123" \
  -F "model=glm-asr" \
  -F "file=@audio.wav" \
  -F "response_format=text" \
  -F "language=zh" # 可选：源语言提示（不传则自动识别）
```

### 响应格式
```json
{
  "text": "transcribed text here",
  "usage": {"type": "duration", "seconds": 15}
}
```

### vLLM 参数
- `--max-num-seqs 50` → 支持 50 个并发序列
- 可以安全地并行发送多个请求

---

## 实现计划

### Task 1: 更新 GLMASRProvider

**文件**: `libs/subflow/providers/asr/glm_asr.py`

修改点:
1. 添加 `response_format=text` 参数
2. 使用连接池复用 httpx.AsyncClient
3. 新增 `transcribe_batch` 方法支持并发

```python
class GLMASRProvider(ASRProvider):
    def __init__(
        self,
        base_url: str,
        model: str = "glm-asr",
        api_key: str = "abc123",
        max_concurrent: int = 20,  # 并发限制
        timeout: float = 300.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.max_concurrent = max_concurrent
        self.timeout = timeout
        self._semaphore: asyncio.Semaphore | None = None
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """复用连接池"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_connections=self.max_concurrent),
            )
        return self._client

    async def _get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
        return self._semaphore

    async def transcribe_batch(
        self,
        audio_paths: list[str],
    ) -> list[str]:
        """并发转录多个音频文件"""
        semaphore = await self._get_semaphore()

        async def _transcribe_one(path: str) -> str:
            async with semaphore:
                result = await self.transcribe(path)
                return result[0].text if result else ""

        return await asyncio.gather(*[_transcribe_one(p) for p in audio_paths])

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
```

---

### Task 2: 更新 ASRStage 调用真实 Provider

**文件**: `libs/subflow/stages/asr.py`

```python
class ASRStage(Stage):
    name = "asr"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = GLMASRProvider(
            base_url=settings.asr_base_url,
            model=settings.asr_model,
            api_key=settings.asr_api_key,
            max_concurrent=settings.asr_max_concurrent,
        )

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        vad_segments: list[VADSegment] = context["vad_segments"]
        vocals_path: str = context["vocals_audio_path"]
        
        # 1. 切割音频为独立片段
        segment_paths = await self._cut_audio_segments(vocals_path, vad_segments)
        
        # 2. 并发调用 ASR
        texts = await self.provider.transcribe_batch(segment_paths)
        
        # 3. 组装结果
        asr_segments = []
        for i, (vad_seg, text) in enumerate(zip(vad_segments, texts)):
            asr_segments.append(ASRSegment(
                id=i,
                start=vad_seg.start,
                end=vad_seg.end,
                text=text,
            ))
        
        context["asr_segments"] = asr_segments
        context["full_transcript"] = " ".join(s.text for s in asr_segments)
        
        # 4. 清理临时文件
        await self._cleanup_segments(segment_paths)
        
        return context
```

---

### Task 3: 更新配置

**文件**: `libs/subflow/config.py`

新增配置项:
```python
# ASR
asr_base_url: str = "http://localhost:8000/v1"
asr_model: str = "glm-asr"
asr_api_key: str = "abc123"
asr_max_concurrent: int = 20  # 并发数，建议设为 max-num-seqs 的 40%
```

**文件**: `.env.example`

```bash
ASR_BASE_URL=http://localhost:8000/v1
ASR_MODEL=glm-asr
ASR_API_KEY=abc123
ASR_MAX_CONCURRENT=20
```

---

### Task 4: 音频切割工具

**文件**: `libs/subflow/utils/audio.py` (新建)

```python
import asyncio
import subprocess
from pathlib import Path

async def cut_audio_segment(
    input_path: str,
    output_path: str,
    start: float,
    end: float,
) -> None:
    """使用 ffmpeg 切割音频片段"""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-ss", str(start),
        "-to", str(end),
        "-c", "copy",  # 无损切割
        output_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await proc.wait()


async def cut_audio_segments_batch(
    input_path: str,
    segments: list[tuple[float, float]],
    output_dir: str,
) -> list[str]:
    """批量切割音频，返回输出路径列表"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    tasks = []
    output_paths = []
    for i, (start, end) in enumerate(segments):
        output_path = str(output_dir / f"segment_{i:04d}.wav")
        output_paths.append(output_path)
        tasks.append(cut_audio_segment(input_path, output_path, start, end))
    
    await asyncio.gather(*tasks)
    return output_paths
```

---

## 性能优化策略

### 并发度设置

| vLLM max-num-seqs | 建议 ASR_MAX_CONCURRENT | 说明 |
|-------------------|------------------------|------|
| 50 | 20 | 留余量给其他请求 |
| 100 | 40 | 高并发场景 |
| 200 | 80 | 极限性能 |

### 批处理流程

```
VAD Segments (N个)
       │
       ▼
┌──────────────────┐
│ 并行 FFmpeg 切割  │  ← asyncio.gather
└──────────────────┘
       │
       ▼
┌──────────────────┐
│ 并行 ASR 请求    │  ← Semaphore 控制并发
│ (max_concurrent) │
└──────────────────┘
       │
       ▼
  ASR Segments (N个)
```

### 连接池优化

```python
# httpx 连接池配置
limits = httpx.Limits(
    max_connections=max_concurrent,
    max_keepalive_connections=max_concurrent // 2,
)
```

---

## 执行顺序

1. **Task 3**: 更新配置 (5 分钟)
2. **Task 4**: 创建音频切割工具 (10 分钟)
3. **Task 1**: 更新 GLMASRProvider (15 分钟)
4. **Task 2**: 更新 ASRStage (10 分钟)
5. **测试**: 端到端验证 (10 分钟)

---

## 测试命令

```bash
# 单元测试
uv run --project apps/worker --directory apps/worker pytest tests/test_asr.py

# 集成测试（需要 vLLM 运行）
ASR_BASE_URL=http://localhost:8000/v1 \
ASR_MODEL=glm-asr \
ASR_API_KEY=abc123 \
uv run --project apps/worker python -c "
import asyncio
from libs.subflow.providers.asr.glm_asr import GLMASRProvider

async def main():
    provider = GLMASRProvider(
        base_url='http://localhost:8000/v1',
        model='glm-asr',
        api_key='abc123',
    )
    result = await provider.transcribe('test.wav')
    print(result)
    await provider.close()

asyncio.run(main())
"
```

---

*计划创建时间: 2026-01-06*
