"""LLM passes (real provider with safe fallbacks)."""

from __future__ import annotations

import json
from typing import Any

from subflow.config import Settings
from subflow.models.segment import ASRSegment, SemanticChunk
from subflow.providers import get_llm_provider
from subflow.providers.llm import Message
from subflow.stages.base import Stage


class GlobalUnderstandingPass(Stage):
    name = "llm_global_understanding"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("full_transcript"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        transcript = str(context.get("full_transcript", "")).strip()

        if not self.settings.llm.api_key:
            context["global_context"] = {
                "topic": "unknown",
                "domain": "unknown",
                "style": "unknown",
                "speakers": [],
                "glossary": {},
                "outline": [],
                "translation_notes": [],
            }
            return context

        prompt = (
            "你是一个专业的视频内容分析助手。请分析以下视频转录文本，提取：\n"
            "1. 视频主题和领域\n"
            "2. 语言风格 (正式/非正式/技术等)\n"
            "3. 说话人信息\n"
            "4. 核心术语表 (原文 -> 建议翻译)\n"
            "5. 内容大纲\n"
            "6. 翻译注意事项\n\n"
            "以 JSON 格式输出。"
        )

        result = await self.llm.complete_json(
            [
                Message(role="system", content=prompt),
                Message(role="user", content=transcript),
            ]
        )
        context["global_context"] = result
        return context


class SemanticChunkingPass(Stage):
    name = "llm_semantic_chunking"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("asr_segments"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        asr_segments: list[ASRSegment] = list(context.get("asr_segments", []))
        if not self.settings.llm.api_key:
            context["semantic_chunks"] = [
                SemanticChunk(
                    id=segment.id,
                    text=segment.text,
                    start=segment.start,
                    end=segment.end,
                    source_segment_ids=[segment.id],
                )
                for segment in asr_segments
            ]
            return context

        asr_payload = [
            {"id": s.id, "start": s.start, "end": s.end, "text": s.text, "language": s.language}
            for s in asr_segments
        ]
        prompt = (
            "将以下 ASR 转录结果重组为语义完整的翻译单元。\n\n"
            "切分原则：\n"
            "1. 每个块表达一个完整的意思\n"
            "2. 每块翻译后约 15-25 个中文字符\n"
            "3. 保持时间映射关系\n\n"
            "输入 ASR 段落:\n"
            f"{json.dumps(asr_payload, ensure_ascii=False)}\n\n"
            "以 JSON 数组格式输出，每项包含:\n"
            "- id: 序号\n"
            "- text: 原文\n"
            "- start: 开始时间\n"
            "- end: 结束时间\n"
            "- source_segment_ids: 来源 ASR 段落 ID"
        )

        result = await self.llm.complete_json([Message(role="system", content=prompt)])
        if not isinstance(result, list):
            raise ValueError("Semantic chunking output must be a JSON array")

        chunks: list[SemanticChunk] = []
        for item in result:
            chunks.append(
                SemanticChunk(
                    id=int(item["id"]),
                    text=str(item["text"]),
                    start=float(item.get("start", 0.0)),
                    end=float(item.get("end", 0.0)),
                    source_segment_ids=list(item.get("source_segment_ids", [])),
                )
            )
        context["semantic_chunks"] = chunks
        return context


class TranslationPass(Stage):
    name = "llm_translation"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("semantic_chunks")) and bool(context.get("target_language"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        context = dict(context)
        target_language = str(context.get("target_language", "zh"))
        chunks: list[SemanticChunk] = list(context.get("semantic_chunks", []))

        if not self.settings.llm.api_key:
            for chunk in chunks:
                chunk.translation = f"[{target_language}] {chunk.text}"
            context["semantic_chunks"] = chunks
            return context

        global_context: dict = dict(context.get("global_context") or {})
        glossary: dict[str, str] = dict(global_context.get("glossary") or {})
        glossary_text = json.dumps(glossary, ensure_ascii=False)

        batch_size = 8
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            payload = [{"id": c.id, "text": c.text} for c in batch]
            prompt = (
                "你是一个专业字幕翻译助手。请把以下内容翻译成目标语言。\n"
                f"目标语言: {target_language}\n"
                "要求：\n"
                "1) 保持原意、自然流畅，适合字幕\n"
                "2) 严格遵守术语表（glossary）中的译法\n"
                "3) 输出 JSON 数组，每项包含 id, translation\n\n"
                f"glossary: {glossary_text}\n\n"
                f"items: {json.dumps(payload, ensure_ascii=False)}"
            )
            result = await self.llm.complete_json([Message(role="system", content=prompt)])
            if not isinstance(result, list):
                raise ValueError("Translation output must be a JSON array")
            mapping = {int(item["id"]): str(item["translation"]) for item in result}
            for c in batch:
                c.translation = mapping.get(c.id, c.translation or c.text)

        context["semantic_chunks"] = chunks
        return context


class QAPass(Stage):
    name = "llm_qa"

    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = get_llm_provider(settings.llm.model_dump())

    def validate_input(self, context: dict[str, Any]) -> bool:
        return bool(context.get("semantic_chunks"))

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.llm.api_key:
            return dict(context)

        context = dict(context)
        chunks: list[SemanticChunk] = list(context.get("semantic_chunks", []))
        payload = [{"id": c.id, "text": c.text, "translation": c.translation} for c in chunks]
        prompt = (
            "你是字幕审校助手。请检查以下字幕翻译并在必要时做微调：\n"
            "- 术语一致性\n"
            "- 漏译/错译\n"
            "- 流畅度\n"
            "- 字幕长度合理\n\n"
            "输出 JSON 数组，每项包含 id, translation（最终稿）。\n\n"
            f"items: {json.dumps(payload, ensure_ascii=False)}"
        )
        result = await self.llm.complete_json([Message(role="system", content=prompt)])
        if isinstance(result, list):
            mapping = {int(item["id"]): str(item["translation"]) for item in result}
            for c in chunks:
                if c.id in mapping:
                    c.translation = mapping[c.id]
            context["semantic_chunks"] = chunks
        return context
