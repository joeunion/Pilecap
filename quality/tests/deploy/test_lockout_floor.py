"""The lockout floor: every home of `ZITADEL_MAX_PASSWORD_ATTEMPTS` says one value, under 100."""

# does-not-cover: what a deployment's own environment sets — this reads the shipped defaults.

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
NIST_CEILING = 100
HOMES = {
    "config/settings/base.py": r'"ZITADEL_MAX_PASSWORD_ATTEMPTS", default=(\d+)\)',
    "compose.yaml": r"\$\{ZITADEL_MAX_PASSWORD_ATTEMPTS:-(\d+)\}",
    "deploy/compose.yaml": r"\$\{ZITADEL_MAX_PASSWORD_ATTEMPTS:-(\d+)\}",
    ".env.example": r"^ZITADEL_MAX_PASSWORD_ATTEMPTS=(\d+)$",
    "deploy/env.staging.example": r"^ZITADEL_MAX_PASSWORD_ATTEMPTS=(\d+)$",
}


def shipped(home: str) -> int:
    found = re.findall(HOMES[home], (ROOT / home).read_text(encoding="utf-8"), re.M)
    assert len(found) == 1, f"{home}: {len(found)} lockout defaults, expected one"
    return int(found[0])


@pytest.mark.parametrize("home", sorted(HOMES))
def test_the_shipped_lockout_is_bounded_and_under_nists_ceiling(home: str) -> None:
    assert 0 < shipped(home) < NIST_CEILING, f"{home} ships {shipped(home)}"


def test_every_home_ships_the_one_value() -> None:
    values = {home: shipped(home) for home in HOMES}
    assert len(set(values.values())) == 1, values
