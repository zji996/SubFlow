from __future__ import annotations

import pytest

from subflow.config import Settings
from subflow.exceptions import ConfigurationError
from subflow.stages.llm_passes import GlobalUnderstandingPass


async def test_global_understanding_pass_raises_without_api_key() -> None:
    settings = Settings(llm_fast={"api_key": ""}, llm_power={"api_key": ""})
    stage = GlobalUnderstandingPass(settings)

    with pytest.raises(ConfigurationError):
        await stage.execute({"full_transcript": "hello", "target_language": "zh"})
