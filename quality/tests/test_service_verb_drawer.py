"""A product's own service verbs, declared in its drawer, read beside the platform's lexicon."""

# does-not-cover: the engine's exit status on a refused drawer — the drawer drives own that path.

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from quality.checks.rule_16 import event_grammar
from quality.checks.rule_16_the_rest_of_the_grammar import naming_grammar
from quality.engine import world
from quality.engine.lexicon import service_verb_lexicon

ROOT = Path(__file__).resolve().parents[2]
RULES = "quality/rules.yaml"
DRAWER = "quality/local/rules.yaml"
SERVICE = "pick_up_shipment"


def _rule_16() -> dict[str, Any]:
    """House rule 16's declaration, as the template file carries it."""
    doc = yaml.safe_load((ROOT / RULES).read_text())
    return next(r for r in doc["rules"] if str(r["id"]) == "16")


def _platform_verbs() -> tuple[str, ...]:
    """The template's lexicon, read off its own list."""
    return tuple(str(v) for v in _rule_16()["scope"]["service_verbs"])


def _product(tmp_path: Path, drawer: str | None) -> Path:
    """A product-shaped copy: the template's rules, an optional drawer, one app with one service."""
    (tmp_path / "quality").mkdir(parents=True)
    shutil.copy(ROOT / RULES, tmp_path / RULES)
    if drawer is not None:
        (tmp_path / "quality" / "local").mkdir()
        (tmp_path / DRAWER).write_text(drawer)
    app = tmp_path / "apps" / "bookings"
    app.mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "apps.py").write_text("")
    (app / "services.py").write_text(f"def {SERVICE}(*, shipment):\n    return shipment\n")
    return tmp_path


def lexicon(root: Path) -> tuple[str, ...]:
    """The one reader rule 16's runner and `roads shape` ask, over the copy."""
    return service_verb_lexicon(root, _platform_verbs())


def _service_hits(root: Path) -> list[str]:
    """Rule 16's `services` findings on the copy."""
    found = naming_grammar(root, _rule_16()).findings
    return [f.msg for f in found if f.klass == "services"]


def _drawer_problems(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> list[str]:
    """The engine's own drawer read, aimed at a scratch drawer."""
    path = tmp_path / "rules.yaml"
    path.write_text(text)
    monkeypatch.setattr(world, "LOCAL_RULES_PATH", path)
    return world._read_local()[2]


def test_a_product_verb_reaches_the_scaffolds_lexicon(tmp_path: Path) -> None:
    """The one reader returns the drawer's word beside every platform word."""
    declared = lexicon(_product(tmp_path, "service_verbs:\n  - pick_up\n"))
    assert "pick_up" in declared
    assert set(_platform_verbs()) <= set(declared)


def test_a_product_verb_passes_rule_16_on_the_product_copy(tmp_path: Path) -> None:
    """A service named after the drawer's verb is no rule-16 finding."""
    assert _service_hits(_product(tmp_path, "service_verbs:\n  - pick_up\n")) == []


def test_without_a_drawer_the_lexicon_is_the_platforms(tmp_path: Path) -> None:
    """No drawer: the platform's list exactly, and the product's service is refused."""
    root = _product(tmp_path, None)
    assert lexicon(root) == _platform_verbs()
    assert len(_service_hits(root)) == 1


def test_the_drawer_takes_the_service_verbs_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`service_verbs:` is one of the drawer's keys."""
    assert "service_verbs" in world.LOCAL_KEYS
    assert _drawer_problems(monkeypatch, tmp_path, "service_verbs:\n  - pick_up\n") == []


@pytest.mark.parametrize("word", ["add", "Pick-Up", "1st"])
def test_a_colliding_or_malformed_word_is_refused_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, word: str
) -> None:
    """A platform word or a non-identifier is refused by name, at the drawer read and the reader."""
    text = f"service_verbs:\n  - '{word}'\n"
    problems = _drawer_problems(monkeypatch, tmp_path, text)
    assert len(problems) == 1 and f"`{word}`" in problems[0], problems
    with pytest.raises(ValueError, match=f"`{word}`"):
        lexicon(_product(tmp_path / "copy", text))


@pytest.mark.parametrize(
    ("event", "hits"),
    [
        ("bookings.shipment.picked_up", 0),
        ("bookings.shipment.dead_lettered", 0),
        ("bookings.shipment.closed", 0),
        ("bookings.shipment.pick_up", 1),
        ("bookings.shipment.pick_uped", 1),
        ("bookings.shipment.lent", 0),
        ("bookings.shipment.lent_out", 0),
        ("bookings.shipment.built", 0),
        ("bookings.shipment.ran", 0),
        ("bookings.shipment.lended", 1),
        ("bookings.shipment.payed", 1),
        ("bookings.shipment.setted", 1),
        ("bookings.shipment.seeded", 0),
        ("bookings.shipment.needed", 0),
        ("bookings.shipment.cancelled", 0),
    ],
)
def test_an_event_says_a_phrasal_verb_in_its_first_word(
    tmp_path: Path, event: str, hits: int
) -> None:
    """Rule 16's event arm reads the tense off the word before a trailing particle."""
    root = _product(tmp_path, "service_verbs:\n  - pick_up\n")
    (root / "apps" / "bookings" / "events.py").write_text(f'SHIPMENT_EVENT = "{event}"\n')
    assert len(event_grammar(root, _rule_16()).findings) == hits
