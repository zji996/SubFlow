from __future__ import annotations

from subflow.config import Settings
from subflow.stages.llm_passes import SemanticChunkingPass


def test_semantic_chunking_clean_translation_strips_wrappers() -> None:
    stage = SemanticChunkingPass(Settings())
    assert stage._clean_translation("```text\nhi\n```") == "hi"
    assert stage._clean_translation('"hi"') == "hi"
    assert stage._clean_translation(" hi ") == "hi"
