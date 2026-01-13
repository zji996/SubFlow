"""Provider factory and registry."""

from __future__ import annotations

from typing import Any
from collections.abc import Mapping

from subflow.exceptions import ConfigurationError
from subflow.providers.audio.base import AudioProvider
from subflow.providers.asr.base import ASRProvider
from subflow.providers.llm.base import LLMProvider
from subflow.providers.vad.base import VADProvider


def get_asr_provider(config: Mapping[str, Any]) -> ASRProvider:
    """Get ASR provider based on configuration."""
    provider_type = config.get("provider", "glm_asr")

    match provider_type:
        case "glm_asr":
            from subflow.providers.asr.glm_asr import GLMASRProvider

            return GLMASRProvider(
                base_url=config["base_url"],
                api_key=str(config.get("api_key") or ""),
                model=config.get("model", "glm-asr-nano-2512"),
                max_concurrent=int(config.get("max_concurrent", 20)),
                timeout=float(config.get("timeout", 300.0)),
            )
        case _:
            raise ConfigurationError(f"Unknown ASR provider: {provider_type}")


def get_llm_provider(config: Mapping[str, Any]) -> LLMProvider:
    """Get LLM provider based on configuration."""
    provider_type = config.get("provider", "openai")

    match provider_type:
        case "openai" | "openai_compat":
            from subflow.providers.llm.openai_compat import OpenAICompatProvider

            return OpenAICompatProvider(
                api_key=config.get("api_key", ""),
                model=config.get("model", "gpt-4"),
                base_url=config.get("base_url"),
                provider=str(provider_type),
            )
        case "gemini":
            from subflow.providers.llm.gemini import GeminiProvider

            api_key = str(config.get("api_key") or "").strip()
            model = str(config.get("model") or "").strip()
            if not api_key or not model:
                raise ConfigurationError(
                    f"Gemini provider requires api_key/model (got api_key={bool(api_key)} model={model!r})"
                )
            return GeminiProvider(
                api_key=api_key,
                model=model,
                base_url=config.get("base_url"),
            )
        case "anthropic" | "claude":
            from subflow.providers.llm.anthropic import AnthropicProvider

            api_key = str(config.get("api_key") or "").strip()
            if not api_key:
                raise ConfigurationError("Anthropic provider requires api_key")
            model = str(config.get("model") or "claude-sonnet-4-20250514").strip()
            return AnthropicProvider(
                api_key=api_key,
                model=model,
                base_url=config.get("base_url"),
            )
        case _:
            raise ConfigurationError(f"Unknown LLM provider: {provider_type}")


def get_vad_provider(config: Mapping[str, Any]) -> VADProvider:
    provider_type = str(config.get("provider", "nemo_marblenet")).strip().lower()

    match provider_type:
        case "nemo_marblenet" | "nemo":
            from subflow.providers.vad.nemo_marblenet import NemoMarbleNetVADProvider

            return NemoMarbleNetVADProvider(
                model_path=str(config["nemo_model_path"]),
                threshold=float(config.get("threshold", 0.60)),
                min_silence_duration_ms=int(config.get("min_silence_duration_ms", 60)),
                min_speech_duration_ms=int(config.get("min_speech_duration_ms", 100)),
                target_max_segment_s=config.get("target_max_segment_s"),
                split_threshold=config.get("split_threshold"),
                split_search_backtrack_ratio=float(config.get("split_search_backtrack_ratio", 0.7)),
                split_search_forward_ratio=float(config.get("split_search_forward_ratio", 0.03)),
                split_gap_s=float(config.get("split_gap_s", 0.0)),
                device=config.get("nemo_device"),
            )
        case _:
            raise ConfigurationError(f"Unknown VAD provider: {provider_type}")


def get_audio_provider(config: Mapping[str, Any]) -> AudioProvider:
    provider_type = str(config.get("provider", "ffmpeg_demucs")).strip().lower()

    match provider_type:
        case "ffmpeg_demucs" | "default":
            from subflow.providers.audio.default import FFmpegDemucsAudioProvider

            return FFmpegDemucsAudioProvider(
                ffmpeg_bin=str(config.get("ffmpeg_bin") or "ffmpeg"),
                demucs_bin=str(config.get("demucs_bin") or "demucs"),
                demucs_model=str(config.get("demucs_model") or "htdemucs_ft"),
                max_duration_s=config.get("max_duration_s"),
            )
        case _:
            raise ConfigurationError(f"Unknown audio provider: {provider_type}")
