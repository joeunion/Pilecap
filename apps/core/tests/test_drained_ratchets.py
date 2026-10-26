"""Rule 84's readers in `core`'s tests survive a `ratchets:` block drained to nothing."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from apps.core.tests import test_drawer_seam, test_road_census, test_roads

_GATE = importlib.import_module("quality.gate")

#: The test functions that read rule 84's `ratchets:` block, and whether each takes `tmp_path`.
READERS: dict[str, tuple[Callable[..., Any], bool]] = {
    "drawer_seam": (
        test_drawer_seam.test_rule_84_freezes_every_class_and_records_none_at_zero,
        False,
    ),
    "roads": (test_roads.test_unmarked_counts_no_frozen_class_at_zero, True),
    "road_census": (test_road_census.test_the_population_names_every_class_the_rule_records, True),
}


def _drain(rule: dict[str, Any], shape: str, monkeypatch: pytest.MonkeyPatch) -> None:
    if shape == "absent":
        monkeypatch.delitem(rule, "ratchets", raising=False)
    else:
        monkeypatch.setitem(rule, "ratchets", None)


@pytest.mark.parametrize("shape", ["absent", "empty"])
@pytest.mark.parametrize("reader", sorted(READERS))
def test_a_reader_of_rule_84s_ratchets_survives_the_block_drained(
    reader: str, shape: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drained block is the frozen-at-zero form, and each reader takes it as no classes."""
    fn, takes_tmp = READERS[reader]
    _drain(_GATE.RULES_BY_ID["84"], shape, monkeypatch)
    if takes_tmp:
        fn(tmp_path)
    else:
        fn()
