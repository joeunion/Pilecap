"""A product extends a rule's product-reachable scope lists from its drawer: the engine half."""

# does-not-cover: the engine's exit status on a refused drawer — the drawer drives own that path.
# does-not-cover: rules 11 and 3 and `newapp` — `apps/core/tests/test_scope_extensions.py`.

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from apps.core.reach import extended_scope
from quality.checks.rule_16_the_rest_of_the_grammar import naming_grammar
from quality.engine import world

ROOT = Path(__file__).resolve().parents[2]
RULES = "quality/rules.yaml"
DRAWER = "quality/local/rules.yaml"

EXTENSIONS = """\
scope_extensions:
  16:
    app_name_exemptions:
      - app: billing
        reason: a mass noun, and "billings" names nothing this product keeps
  11:
    extra_modules:
      billing: [pricing]
  3:
    allow_unauthenticated:
      - url_name: "api:billing-status"
        operation_id: "apps_billing_api_status"
        reason: the public status a customer reads before anybody signs in
    allow_unauthenticated_views:
      - url_name: billing-status
        view: apps.billing.views.status
        reason: the public status page a customer reads before signing in
"""


def _rule(rule_id: str) -> dict[str, Any]:
    """One template rule's declaration, as the template file carries it."""
    doc = yaml.safe_load((ROOT / RULES).read_text())
    return next(r for r in doc["rules"] if str(r["id"]) == rule_id)


def _product(tmp_path: Path, drawer: str | None) -> Path:
    """A product copy: the template's rules, a drawer if any, a `billing` app with `pricing.py`."""
    (tmp_path / "quality").mkdir(parents=True)
    shutil.copy(ROOT / RULES, tmp_path / RULES)
    if drawer is not None:
        (tmp_path / "quality" / "local").mkdir()
        (tmp_path / DRAWER).write_text(drawer)
    app = tmp_path / "apps" / "billing"
    app.mkdir(parents=True)
    for name in ("__init__", "apps", "models", "pricing"):
        (app / f"{name}.py").write_text("")
    return tmp_path


def _rule_16_apps(root: Path) -> list[str]:
    """Rule 16's `apps` findings on the copy."""
    return [f.msg for f in naming_grammar(root, _rule("16")).findings if f.klass == "apps"]


def test_without_a_drawer_every_rule_reads_its_own_scope(tmp_path: Path) -> None:
    """No drawer: the reader returns each template rule's scope exactly; the product app reds."""
    root = _product(tmp_path, None)
    for rule in yaml.safe_load((ROOT / RULES).read_text())["rules"]:
        assert extended_scope(root, rule) == dict(rule.get("scope") or {}), rule["id"]
    assert len(_rule_16_apps(root)) == 1


def test_a_mass_noun_app_passes_rule_16_with_its_extension(tmp_path: Path) -> None:
    """The `billing` app is no rule-16 finding once the drawer admits the label, with its reason."""
    assert _rule_16_apps(_product(tmp_path, EXTENSIONS)) == []


def _drawer_problems(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> list[str]:
    """The engine's own drawer read, aimed at a scratch drawer."""
    path = tmp_path / "rules.yaml"
    path.write_text(text)
    monkeypatch.setattr(world, "LOCAL_RULES_PATH", path)
    return world._read_local()[2]


def test_the_drawer_takes_the_scope_extensions_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`scope_extensions:` is one of the drawer's keys, and the worked drawer reads clean."""
    assert "scope_extensions" in world.LOCAL_KEYS
    assert _drawer_problems(monkeypatch, tmp_path, EXTENSIONS) == []


@pytest.mark.parametrize(
    ("text", "names"),
    [
        (
            "scope_extensions:\n  17:\n    exemptions:\n      - app: billing\n"
            "        reason: a REST-only upload door\n",
            ("rule 17", "`exemptions`", "reach: product"),
        ),
        (
            "scope_extensions:\n  9999:\n    app_name_exemptions: []\n",
            ("rule 9999", "no template rule"),
        ),
        (
            "scope_extensions:\n  16:\n    app_name_exemptions:\n      - app: core\n"
            "        reason: the platform's own package, again\n",
            ("rule 16", "core", "already carries"),
        ),
        (
            "scope_extensions:\n  16:\n    app_name_exemptions:\n      - app: billing\n",
            ("rule 16", "billing", "reason"),
        ),
        (
            "scope_extensions:\n  16:\n    service_verbs: [pick_up]\n",
            ("rule 16", "`service_verbs`", "its own drawer key"),
        ),
    ],
    ids=["platform-only", "unknown-rule", "template-entry", "no-reason", "verbs-home"],
)
def test_a_refused_extension_names_the_rule_and_the_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str, names: tuple[str, ...]
) -> None:
    """Each refusal is one drawer problem (exit 2 at the engine) naming what it refused."""
    problems = _drawer_problems(monkeypatch, tmp_path, text)
    assert len(problems) == 1 and all(n in problems[0] for n in names), problems
