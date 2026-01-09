"""Pipeline factories."""

from __future__ import annotations

from subflow.config import Settings
from subflow.pipeline.executor import PipelineExecutor
from subflow.stages import (
    ASRStage,
    AudioPreprocessStage,
    GlobalUnderstandingPass,
    LLMASRCorrectionStage,
    SemanticChunkingPass,
    VADStage,
)


def create_translation_pipeline(config: Settings) -> PipelineExecutor:
    """创建标准翻译流水线 (2 Pass LLM 处理)"""
    stages = [
        AudioPreprocessStage(config),
        VADStage(config),
        ASRStage(config),
        LLMASRCorrectionStage(config),
        GlobalUnderstandingPass(config),
        SemanticChunkingPass(config),
    ]
    return PipelineExecutor(stages)
