"""Pipeline factories."""

from __future__ import annotations

from libs.subflow.config import Settings
from libs.subflow.pipeline.executor import PipelineExecutor
from libs.subflow.stages import (
    ASRStage,
    AudioPreprocessStage,
    ExportStage,
    GlobalUnderstandingPass,
    QAPass,
    SemanticChunkingPass,
    TranslationPass,
    VADStage,
)


def create_translation_pipeline(config: Settings) -> PipelineExecutor:
    """创建标准翻译流水线"""
    stages = [
        AudioPreprocessStage(config),
        VADStage(config),
        ASRStage(config),
        GlobalUnderstandingPass(config),
        SemanticChunkingPass(config),
        TranslationPass(config),
        QAPass(config),
        ExportStage(config, format="srt"),
    ]
    return PipelineExecutor(stages)

