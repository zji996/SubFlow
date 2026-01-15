"""Canonical error codes surfaced to API/UI."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    UNKNOWN = "UNKNOWN"
    INVALID_MEDIA = "INVALID_MEDIA"

    AUDIO_PREPROCESS_FAILED = "AUDIO_PREPROCESS_FAILED"
    VAD_FAILED = "VAD_FAILED"
    ASR_FAILED = "ASR_FAILED"
    LLM_FAILED = "LLM_FAILED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    EXPORT_FAILED = "EXPORT_FAILED"

    PROVIDER_FAILED = "PROVIDER_FAILED"
