from __future__ import annotations

from subflow.models.segment import ASRSegment
from subflow.utils.translation_distributor import distribute_translation


def _segs(durations: list[float]) -> list[ASRSegment]:
    out: list[ASRSegment] = []
    t = 0.0
    for i, d in enumerate(durations):
        out.append(ASRSegment(id=i, start=t, end=t + float(d), text=f"s{i}", language="en"))
        t += float(d)
    return out


def test_distribute_translation_empty_translation_all_empty() -> None:
    chunks = distribute_translation("   ", _segs([1.0, 1.0]))
    assert [c.text for c in chunks] == ["", ""]


def test_distribute_translation_single_segment_full_text() -> None:
    chunks = distribute_translation(" hello ", _segs([1.0])[:1])
    assert len(chunks) == 1
    assert chunks[0].text == "hello"


def test_distribute_translation_punctuation_duration_weighted() -> None:
    segs = _segs([1.0, 3.0])
    chunks = distribute_translation("A,B,C,D", segs)
    assert [c.segment_id for c in chunks] == [0, 1]
    assert chunks[0].text == "A"
    assert chunks[1].text == "B C D"


def test_distribute_translation_more_segments_than_pieces_shares_last() -> None:
    chunks = distribute_translation("A,B", _segs([1.0, 1.0, 1.0]))
    assert [c.text for c in chunks] == ["A", "B", "B"]


def test_distribute_translation_no_punctuation_cjk_even_split() -> None:
    chunks = distribute_translation("甲乙丙丁", _segs([1.0, 1.0]))
    assert [c.text for c in chunks] == ["甲乙", "丙丁"]


def test_distribute_translation_no_punctuation_words_even_split() -> None:
    chunks = distribute_translation("one two three four", _segs([1.0, 1.0]))
    assert [c.text for c in chunks] == ["one two", "three four"]

