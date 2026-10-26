"""Rule 16 admits an irregular plural app and names the valve for a deliberate singular."""

# does-not-cover: `newapp`'s half of the same refusal — `apps/core/tests/test_newapp.py`.
# does-not-cover: a plural `IRREGULAR_PLURALS` lacks (`oxen`) — refused, by design.

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from apps.core.lexicon import PLURAL_REMEDY
from quality.checks.rule_16_the_rest_of_the_grammar import naming_grammar

ROOT = Path(__file__).resolve().parents[2]
RULES = "quality/rules.yaml"


def _rule_16() -> dict[str, Any]:
    doc = yaml.safe_load((ROOT / RULES).read_text())
    return next(r for r in doc["rules"] if str(r["id"]) == "16")


def _apps_findings(tmp_path: Path, *labels: str) -> dict[str, str]:
    """Rule 16's `apps` findings over a copy holding one empty app per label, by app."""
    (tmp_path / "quality").mkdir(parents=True)
    shutil.copy(ROOT / RULES, tmp_path / RULES)
    for label in labels:
        app = tmp_path / "apps" / label
        app.mkdir(parents=True)
        for name in ("__init__", "apps", "models"):
            (app / f"{name}.py").write_text("")
    return {
        f.path.split("/")[1]: f.msg
        for f in naming_grammar(tmp_path, _rule_16()).findings
        if f.klass == "apps"
    }


def test_an_irregular_plural_app_passes_rule_16(tmp_path: Path) -> None:
    found = _apps_findings(tmp_path, "people", "children", "staff", "widget")
    assert sorted(found) == ["widget"]


def test_the_refusal_says_irregulars_are_admitted_and_names_the_valve(tmp_path: Path) -> None:
    message = _apps_findings(tmp_path, "widget")["widget"]
    assert PLURAL_REMEDY in message
    assert (
        "an irregular plural (people, children…) is already admitted; a deliberate singular "
        "(a mass noun such as billing) is an entry under scope_extensions: {16: …} in "
        "quality/local/rules.yaml, with its reason"
    ) in message
