from __future__ import annotations

from subflow.config import Settings
from subflow.stages.llm_passes import GlobalUnderstandingPass


async def test_global_understanding_pass_falls_back_without_api_key() -> None:
    settings = Settings(llm={"api_key": ""})
    stage = GlobalUnderstandingPass(settings)

    out = await stage.execute({"full_transcript": "hello", "target_language": "zh"})

    assert out["global_context"]["topic"] == "unknown"
    assert out["global_context"]["glossary"] == {}
    assert out["global_context"]["translation_notes"] == []
