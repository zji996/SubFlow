from __future__ import annotations

from subflow.export.formatters.ass import ASSFormatter
from subflow.models.subtitle_types import (
    AssStyleConfig,
    SubtitleContent,
    SubtitleEntry,
    SubtitleExportConfig,
    SubtitleFormat,
)


def test_ass_formatter_inline_combines_primary_secondary() -> None:
    formatter = ASSFormatter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.ASS,
        content=SubtitleContent.BOTH,
        primary_position="top",
        ass_style=AssStyleConfig(inline_mode=True, secondary_size=45),
    )
    out = formatter.format(
        [
            SubtitleEntry(
                index=1,
                start=0.0,
                end=1.23,
                primary_text="你好，世界",
                secondary_text="Hello",
            )
        ],
        config,
    )
    dialogues = [line for line in out.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 1
    assert "你好 世界 \\N{\\fs45}Hello" in dialogues[0]


def test_ass_formatter_dual_style_separates_lines_and_styles() -> None:
    formatter = ASSFormatter()
    config = SubtitleExportConfig(
        format=SubtitleFormat.ASS,
        content=SubtitleContent.BOTH,
        primary_position="top",
        ass_style=AssStyleConfig(inline_mode=False),
    )
    out = formatter.format(
        [
            SubtitleEntry(
                index=1,
                start=0.0,
                end=1.0,
                primary_text="Primary",
                secondary_text="Secondary",
            )
        ],
        config,
    )
    dialogues = [line for line in out.splitlines() if line.startswith("Dialogue:")]
    assert len(dialogues) == 2
    assert ",Default,," in dialogues[0]
    assert dialogues[0].endswith(",Primary")
    assert ",Secondary,," in dialogues[1]
    assert dialogues[1].endswith(",Secondary")
