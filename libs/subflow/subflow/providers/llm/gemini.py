"""Google Gemini LLM Provider implementation (google-generativeai SDK)."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, TypedDict

from subflow.error_codes import ErrorCode
from subflow.exceptions import ProviderError
from subflow.providers.llm.base import LLMCompletionResult, LLMProvider, LLMUsage, Message

logger = logging.getLogger(__name__)


class _GeminiPart(TypedDict):
    text: str


class _GeminiContent(TypedDict):
    role: str
    parts: list[_GeminiPart]


_GENAI_LOCK = threading.Lock()


def _coerce_usage(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _parse_usage_metadata(obj: object) -> LLMUsage | None:
    usage_obj: object | None = getattr(obj, "usage_metadata", None)
    if usage_obj is None:
        if isinstance(obj, dict):
            usage_obj = obj.get("usage_metadata")
    if usage_obj is None:
        return None

    def _get(field: str) -> int | None:
        if isinstance(usage_obj, dict):
            return _coerce_usage(usage_obj.get(field))
        return _coerce_usage(getattr(usage_obj, field, None))

    prompt = _get("prompt_token_count")
    completion = _get("candidates_token_count")
    total = _get("total_token_count")
    if prompt is None and completion is None and total is None:
        return None
    return LLMUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _split_system_instruction(messages: list[Message]) -> tuple[str | None, list[Message]]:
    system_chunks: list[str] = []
    non_system: list[Message] = []
    for m in messages:
        role = str(m.role or "").strip().lower()
        if role == "system":
            if m.content:
                system_chunks.append(m.content)
            continue
        non_system.append(m)
    system_instruction = "\n\n".join(system_chunks).strip() if system_chunks else None
    return system_instruction or None, non_system


def _to_gemini_contents(messages: list[Message]) -> list[_GeminiContent]:
    contents: list[_GeminiContent] = []
    for m in messages:
        role = str(m.role or "").strip().lower()
        if role == "assistant":
            role = "model"
        elif role == "user":
            role = "user"
        elif role == "model":
            role = "model"
        else:
            role = "user"
        contents.append({"role": role, "parts": [{"text": str(m.content)}]})
    return contents


class GeminiProvider(LLMProvider):
    """Google Gemini API provider (Google AI Studio / compatible endpoints)."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str | None = None,
    ) -> None:
        self.api_key = str(api_key or "")
        self.model = str(model or "").strip()
        self.base_url = str(base_url or "").strip() or None
        if not self.api_key:
            raise ValueError("GeminiProvider requires api_key")
        if not self.model:
            raise ValueError("GeminiProvider requires model")

    def _build_generation_config(self, temperature: float, max_tokens: int | None) -> object:
        cfg: dict[str, Any] = {"temperature": float(temperature)}
        if max_tokens is not None:
            cfg["max_output_tokens"] = int(max_tokens)
        try:
            from google.generativeai.types import GenerationConfig  # type: ignore[import-not-found]

            return GenerationConfig(**cfg)
        except Exception:
            return cfg

    def _generate_sync(
        self,
        contents: list[_GeminiContent],
        *,
        system_instruction: str | None,
        temperature: float,
        max_tokens: int | None,
    ) -> object:
        import google.generativeai as genai  # type: ignore[import-not-found]

        kwargs: dict[str, Any] = {"api_key": self.api_key}
        if self.base_url:
            kwargs["client_options"] = {"api_endpoint": self.base_url}
        genai.configure(**kwargs)

        model_kwargs: dict[str, Any] = {"model_name": self.model}
        if system_instruction:
            model_kwargs["system_instruction"] = system_instruction

        model = genai.GenerativeModel(**model_kwargs)
        generation_config = self._build_generation_config(temperature=temperature, max_tokens=max_tokens)
        return model.generate_content(contents, generation_config=generation_config)

    async def _generate(
        self,
        messages: list[Message],
        *,
        temperature: float,
        max_tokens: int | None,
    ) -> tuple[str, LLMUsage | None, int]:
        system_instruction, non_system = _split_system_instruction(messages)
        contents = _to_gemini_contents(non_system)
        started = time.perf_counter()
        try:
            with _GENAI_LOCK:
                response = await asyncio.to_thread(
                    self._generate_sync,
                    contents,
                    system_instruction=system_instruction,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
        except Exception as exc:
            logger.warning("llm request failed: %s", exc)
            raise ProviderError("gemini", str(exc), error_code=ErrorCode.LLM_FAILED) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        usage_parsed = _parse_usage_metadata(response)
        logger.info(
            "llm call (provider=%s, model=%s, latency_ms=%s, prompt_tokens=%s, completion_tokens=%s, total_tokens=%s)",
            "gemini",
            self.model,
            latency_ms,
            getattr(usage_parsed, "prompt_tokens", None),
            getattr(usage_parsed, "completion_tokens", None),
            getattr(usage_parsed, "total_tokens", None),
        )

        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            candidates = getattr(response, "candidates", None)
            if candidates and isinstance(candidates, list):
                first = candidates[0]
                content = getattr(first, "content", None)
                parts = getattr(content, "parts", None)
                if parts and isinstance(parts, list):
                    part0 = parts[0]
                    text = str(getattr(part0, "text", "") or "").strip()
        return text, usage_parsed, latency_ms

    async def complete(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str:
        text, _usage, _latency_ms = await self._generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return text

    async def complete_with_usage(
        self,
        messages: list[Message],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> LLMCompletionResult:
        text, usage, _latency_ms = await self._generate(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return LLMCompletionResult(text=text, usage=usage)

    async def complete_json(
        self,
        messages: list[Message],
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        json_messages = list(messages)
        if json_messages and json_messages[0].role == "system":
            json_messages[0] = Message(
                role="system",
                content=json_messages[0].content + "\n\nRespond with valid JSON only.",
            )
        else:
            json_messages.insert(0, Message(role="system", content="Respond with valid JSON only."))

        text = await self.complete(json_messages, temperature=temperature)
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            data = json.loads(text.strip())
            if not isinstance(data, dict):
                raise ValueError(f"Expected JSON object, got {type(data).__name__}")
            return data
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse JSON response: {exc}") from exc

