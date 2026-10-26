"""`apps.core.lexicon.looks_plural`: the one plural test rule 16, `newapp` and `scaffold` ask."""

# does-not-cover: a plural the tuple lacks (`oxen`) — still refused; the refusal names the valve.

from __future__ import annotations

import pytest

from apps.core.lexicon import IRREGULAR_PLURALS, inflected, looks_plural


@pytest.mark.parametrize("word", IRREGULAR_PLURALS)
def test_irregular_plurals_read_as_plural(word: str) -> None:
    assert {"people", "children", "staff"} <= set(IRREGULAR_PLURALS)
    assert looks_plural(word)
    assert looks_plural(f"shift_{word}")
    assert inflected(word) == word


@pytest.mark.parametrize("word", ["person", "widget", "child", "status", "analysis", "address"])
def test_singulars_still_refused(word: str) -> None:
    assert not looks_plural(word)


def test_an_irregular_is_the_whole_last_segment_never_a_suffix() -> None:
    assert not looks_plural("metadata")
    assert not looks_plural("chairmen")
