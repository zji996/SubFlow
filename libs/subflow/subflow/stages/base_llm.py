"""Shared base class for LLM-powered stages."""

from __future__ import annotations

from subflow.config import Settings
from subflow.providers import get_llm_provider
from subflow.stages.base import Stage
from subflow.utils.llm_json import LLMJSONHelper


class BaseLLMStage(Stage):
    """Base class for LLM-powered stages."""

    profile_attr: str

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        routing = getattr(settings, "llm_stage", None)
        self.profile = str(getattr(routing, self.profile_attr, "fast") or "fast")
        self.llm_cfg = settings.llm_config_for(self.profile)
        self.llm = get_llm_provider(self.llm_cfg)
        self.api_key = str(self.llm_cfg.get("api_key") or "")
        self.json_helper = LLMJSONHelper(self.llm, max_retries=3)

    async def close(self) -> None:
        await self.llm.close()

