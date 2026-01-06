"""Provider factory and registry."""

from libs.subflow.providers.asr.base import ASRProvider
from libs.subflow.providers.llm.base import LLMProvider


def get_asr_provider(config: dict) -> ASRProvider:
    """Get ASR provider based on configuration."""
    provider_type = config.get("provider", "glm_asr")

    match provider_type:
        case "glm_asr":
            from libs.subflow.providers.asr.glm_asr import GLMASRProvider

            return GLMASRProvider(
                base_url=config["base_url"],
                api_key=config.get("api_key"),
                model=config.get("model", "glm-asr-nano-2512"),
            )
        case _:
            raise ValueError(f"Unknown ASR provider: {provider_type}")


def get_llm_provider(config: dict) -> LLMProvider:
    """Get LLM provider based on configuration."""
    provider_type = config.get("provider", "openai")

    match provider_type:
        case "openai" | "openai_compat":
            from libs.subflow.providers.llm.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(
                base_url=config["base_url"],
                api_key=config.get("api_key", ""),
                model=config.get("model", "gpt-4"),
            )
        case _:
            raise ValueError(f"Unknown LLM provider: {provider_type}")
