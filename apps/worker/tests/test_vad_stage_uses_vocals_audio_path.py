from __future__ import annotations

from subflow.config import Settings
from subflow.providers.vad import NemoMarbleNetVADProvider
from subflow.stages.vad import VADStage


class _DummyVADProvider:
    def __init__(self) -> None:
        self.called_with: str | None = None

    def detect(self, audio_path: str) -> list[tuple[float, float]]:
        self.called_with = str(audio_path)
        return [(0.0, 1.0)]


async def test_vad_stage_uses_vocals_audio_path(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )

    vocals_path = tmp_path / "vocals.wav"
    audio_path = tmp_path / "audio.wav"
    stage = VADStage(settings)
    stage.provider = _DummyVADProvider()  # type: ignore[assignment]

    out = await stage.execute(
        {
            "audio_path": str(audio_path),
            "vocals_audio_path": str(vocals_path),
        }
    )

    assert stage.provider.called_with == str(vocals_path)  # type: ignore[union-attr]
    assert out["vad_segments"][0].start == 0.0
    assert out["vad_segments"][0].end == 1.0


async def test_vad_stage_does_not_hard_split_provider_segments(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )

    class _LongDummyProvider:
        def detect(self, audio_path: str) -> list[tuple[float, float]]:
            return [(0.0, 25.0)]

    stage = VADStage(settings)
    stage.provider = _LongDummyProvider()  # type: ignore[assignment]

    out = await stage.execute({"vocals_audio_path": str(tmp_path / "vocals.wav")})
    segs = out["vad_segments"]
    assert [(s.start, s.end) for s in segs] == [(0.0, 25.0)]


def test_vad_stage_uses_nemo_provider_by_default(tmp_path) -> None:
    settings = Settings(
        data_dir=str(tmp_path / "data"),
        log_dir=str(tmp_path / "logs"),
        models_dir=str(tmp_path / "models"),
    )

    stage = VADStage(settings)
    assert stage.provider_name == "nemo"
    assert isinstance(stage.provider, NemoMarbleNetVADProvider)
