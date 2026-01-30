from __future__ import annotations

import json
import httpx
import pytest

from subflow.exceptions import StageExecutionError
from subflow.models.segment import ASRSegment
from subflow.providers.llm import (
    LLMUsage,
    Message,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
)
from subflow.providers.llm.openai_compat import OpenAICompatProvider
from subflow.stages.llm_passes import SemanticChunkingPass, TRANSLATE_SEGMENT_TOOL
from subflow.utils.json_repair import parse_tool_arguments_safe


def test_tool_use_dataclasses_roundtrip() -> None:
    tool = ToolDefinition(
        name="t",
        description="d",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    )
    call = ToolCall(id="c1", name="t", arguments={"id": 1, "translation": "x"})
    result = ToolCallResult(tool_calls=[call], usage=LLMUsage(prompt_tokens=1, completion_tokens=2))
    assert tool.name == "t"
    assert result.tool_calls[0].arguments["id"] == 1


def test_parse_tool_arguments_safe_repairs_truncated_json() -> None:
    raw = '{"id": 1, "translation": "未完成的字符串'
    assert parse_tool_arguments_safe(raw) == {"id": 1, "translation": "未完成的字符串"}


@pytest.mark.asyncio
async def test_openai_compat_complete_with_tools_parses_streamed_tool_calls() -> None:
    sse = "\n".join(
        [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_0","type":"function","function":{"name":"translate_segment","arguments":"{\\"id\\":0,"}},{"index":1,"id":"call_1","type":"function","function":{"name":"translate_segment","arguments":"{\\"id\\":1,\\"translation\\":\\"t1\\"}"}}]}}]}',
            "",
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"translation\\":\\"t0\\"}"}}]}}]}',
            "",
            "data: [DONE]",
            "",
        ]
    ).encode("utf-8")

    def _handler(request: httpx.Request) -> httpx.Response:  # noqa: ANN001
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = OpenAICompatProvider(api_key="x", model="gpt-4", base_url="https://example.com/v1")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        result = await provider.complete_with_tools(
            messages=[Message(role="user", content="hi")],
            tools=[TRANSLATE_SEGMENT_TOOL],
        )
    finally:
        await provider.close()

    assert [c.id for c in result.tool_calls] == ["call_0", "call_1"]
    assert [c.arguments for c in result.tool_calls] == [
        {"id": 0, "translation": "t0"},
        {"id": 1, "translation": "t1"},
    ]


@pytest.mark.asyncio
async def test_openai_compat_complete_with_tools_skips_unparseable_tool_arguments() -> None:
    sse = "\n".join(
        [
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_0","type":"function","function":{"name":"translate_segment","arguments":"{\\"id\\":0,\\"translation\\":"}},{"index":1,"id":"call_1","type":"function","function":{"name":"translate_segment","arguments":"{\\"id\\":1,\\"translation\\":\\"t1\\"}"}}]}}]}',
            "",
            "data: [DONE]",
            "",
        ]
    ).encode("utf-8")

    def _handler(request: httpx.Request) -> httpx.Response:  # noqa: ANN001
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    provider = OpenAICompatProvider(api_key="x", model="gpt-4", base_url="https://example.com/v1")
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        result = await provider.complete_with_tools(
            messages=[Message(role="user", content="hi")],
            tools=[TRANSLATE_SEGMENT_TOOL],
        )
    finally:
        await provider.close()

    assert [c.id for c in result.tool_calls] == ["call_1"]
    assert [c.arguments for c in result.tool_calls] == [{"id": 1, "translation": "t1"}]


@pytest.mark.asyncio
async def test_semantic_chunking_prefers_tool_use(settings) -> None:
    class _DummyToolLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_with_tools(  # noqa: ANN001, ARG002
            self,
            messages,
            tools,
            *,
            parallel_tool_calls=True,
            temperature=0.3,
            max_tokens=None,
        ):
            self.calls += 1
            return ToolCallResult(
                tool_calls=[
                    ToolCall(
                        id="c0",
                        name="translate_segment",
                        arguments={"id": 0, "translation": "t0"},
                    ),
                    ToolCall(
                        id="c1",
                        name="translate_segment",
                        arguments={"id": 1, "translation": "t1"},
                    ),
                ],
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = "x"
    stage.llm = _DummyToolLLM()

    out = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=0, start=0.0, end=1.0, text="A"),
                ASRSegment(id=1, start=1.0, end=2.0, text="B"),
            ],
            "target_language": "zh",
            "global_context": {"topic": "x"},
        }
    )

    translations = {t.segment_id: t.translation for t in out["segment_translations"]}
    assert translations == {0: "t0", 1: "t1"}
    assert stage.llm.calls == 1


@pytest.mark.asyncio
async def test_semantic_chunking_tool_use_raises_when_tools_unsupported(settings) -> None:
    class _DummyUnsupportedLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_with_tools(self, *args, **kwargs):  # noqa: ANN001, D401
            self.calls += 1
            raise NotImplementedError("no tools")

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = "x"
    stage.llm = _DummyUnsupportedLLM()

    with pytest.raises(StageExecutionError):
        await stage.execute(
            {
                "asr_segments": [
                    ASRSegment(id=0, start=0.0, end=1.0, text="A"),
                    ASRSegment(id=1, start=1.0, end=2.0, text="B"),
                ],
                "target_language": "zh",
                "global_context": {"topic": "x"},
            }
        )
    assert stage.llm.calls == 1


@pytest.mark.asyncio
async def test_semantic_chunking_reduces_batch_size_on_large_missing(settings) -> None:
    class _DummyLLM:
        def __init__(self) -> None:
            self.calls = 0
            self.request_sizes: list[int] = []

        async def complete_with_tools(  # noqa: ANN001, ARG002
            self,
            messages,
            tools,
            *,
            parallel_tool_calls=True,
            temperature=0.3,
            max_tokens=None,
        ):
            self.calls += 1
            user = str(messages[-1].content or "")
            payload = json.loads(user.split("待翻译：\n", 1)[1])
            self.request_sizes.append(len(payload))

            if self.calls == 1:
                calls: list[ToolCall] = []
            else:
                calls = [
                    ToolCall(
                        id=f"c{item['id']}",
                        name="translate_segment",
                        arguments={"id": item["id"], "translation": f"t{item['id']}"},
                    )
                    for item in payload
                ]
            return ToolCallResult(
                tool_calls=calls,
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = "x"
    stage.llm = _DummyLLM()

    out = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(
                    id=i,
                    start=float(i),
                    end=float(i + 1),
                    text=f"S{i}." if i == 9 else f"S{i}",
                )
                for i in range(10)
            ],
            "target_language": "zh",
            "global_context": {"topic": "x"},
        }
    )

    translations = {t.segment_id: t.translation for t in out["segment_translations"]}
    assert translations == {i: f"t{i}" for i in range(10)}
    assert stage.llm.request_sizes == [10, 5, 5]


@pytest.mark.asyncio
async def test_semantic_chunking_skips_missing_single_translation_after_retry(settings) -> None:
    class _MetricsRecorder:
        def __init__(self) -> None:
            self.metrics_calls: list[dict] = []

        async def report(self, progress: int, message: str) -> None:  # noqa: ARG002
            return None

        async def report_metrics(self, metrics) -> None:  # noqa: ANN001
            self.metrics_calls.append(dict(metrics or {}))

    class _DummyLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_with_tools(  # noqa: ANN001, ARG002
            self,
            messages,
            tools,
            *,
            parallel_tool_calls=True,
            temperature=0.3,
            max_tokens=None,
        ):
            self.calls += 1
            if self.calls == 1:
                tool_calls = [
                    ToolCall(
                        id="c0",
                        name="translate_segment",
                        arguments={"id": 0, "translation": "t0"},
                    )
                ]
            else:
                tool_calls = []
            return ToolCallResult(
                tool_calls=tool_calls,
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = "x"
    stage.llm = _DummyLLM()

    recorder = _MetricsRecorder()
    out = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=0, start=0.0, end=1.0, text="A"),
                ASRSegment(id=1, start=1.0, end=2.0, text="B"),
            ],
            "target_language": "zh",
            "global_context": {"topic": "x"},
        },
        progress_reporter=recorder,
    )

    translations = {t.segment_id: t.translation for t in out["segment_translations"]}
    assert translations == {0: "t0", 1: "B"}
    assert stage.llm.calls == 2

    statuses = [m.get("retry_status") for m in recorder.metrics_calls if "retry_status" in m]
    assert statuses[:2] == ["retrying", "failed"]


@pytest.mark.asyncio
async def test_semantic_chunking_reports_recovered_when_retry_succeeds(settings) -> None:
    class _MetricsRecorder:
        def __init__(self) -> None:
            self.metrics_calls: list[dict] = []

        async def report(self, progress: int, message: str) -> None:  # noqa: ARG002
            return None

        async def report_metrics(self, metrics) -> None:  # noqa: ANN001
            self.metrics_calls.append(dict(metrics or {}))

    class _DummyLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def complete_with_tools(  # noqa: ANN001, ARG002
            self,
            messages,
            tools,
            *,
            parallel_tool_calls=True,
            temperature=0.3,
            max_tokens=None,
        ):
            self.calls += 1
            if self.calls == 1:
                tool_calls = [
                    ToolCall(
                        id="c0",
                        name="translate_segment",
                        arguments={"id": 0, "translation": "t0"},
                    )
                ]
            else:
                tool_calls = [
                    ToolCall(
                        id="c1",
                        name="translate_segment",
                        arguments={"id": 1, "translation": "t1"},
                    )
                ]
            return ToolCallResult(
                tool_calls=tool_calls,
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

    stage = SemanticChunkingPass.__new__(SemanticChunkingPass)
    stage.settings = settings
    stage.profile = "power"
    stage.api_key = "x"
    stage.llm = _DummyLLM()

    recorder = _MetricsRecorder()
    out = await stage.execute(
        {
            "asr_segments": [
                ASRSegment(id=0, start=0.0, end=1.0, text="A"),
                ASRSegment(id=1, start=1.0, end=2.0, text="B"),
            ],
            "target_language": "zh",
            "global_context": {"topic": "x"},
        },
        progress_reporter=recorder,
    )

    translations = {t.segment_id: t.translation for t in out["segment_translations"]}
    assert translations == {0: "t0", 1: "t1"}
    assert stage.llm.calls == 2

    statuses = [m.get("retry_status") for m in recorder.metrics_calls if "retry_status" in m]
    assert statuses[:2] == ["retrying", "recovered"]
