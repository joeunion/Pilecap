"""A product extends rules 11 and 3, and `newapp`'s labels, from its drawer: the Django half."""

# does-not-cover: the drawer's refusals and rule 16 — `quality/tests/test_scope_extensions.py`.

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from django.conf import settings

from apps.core import checks
from apps.core.management.commands import newapp

ROOT = Path(__file__).resolve().parents[3]
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


@pytest.fixture
def at_copy(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Aim the Django checks and `newapp` at a copy, their caches cleared both ways."""

    def aim(root: Path) -> None:
        monkeypatch.setattr(settings, "BASE_DIR", root)
        checks._rules.cache_clear()

    yield aim
    checks._rules.cache_clear()


def _rule_11(monkeypatch: pytest.MonkeyPatch, root: Path) -> list[str]:
    """Rule 11's findings for the copy's one product app."""
    billing = SimpleNamespace(label="billing", path=str(root / "apps" / "billing"))
    monkeypatch.setattr(checks, "_local_app_configs", lambda: [billing])
    return [str(e.msg) for e in checks.check_canonical_shape()]


def _rule_3_views(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Rule 3's plain-view findings with the template's views and one product view mounted."""
    scope = _rule("3")["scope"]
    live = {
        str(e["url_name"]): str(e["view"])
        for key in ("allow_unauthenticated_views", "authenticated_views")
        for e in scope[key]
    }
    live["billing-status"] = "apps.billing.views.status"
    monkeypatch.setattr(checks, "first_party_plain_views", lambda: live)
    return [str(e.msg) for e in checks.check_plain_view_auth()]


def test_newapp_admits_the_drawers_singular_label(tmp_path: Path, at_copy: Any) -> None:
    """`newapp billing` reads the same union, so the label it refuses is the one rule 16 reds."""
    at_copy(_product(tmp_path, None))
    assert "billing" not in newapp.singular_apps_the_grammar_admits()
    at_copy(_product(tmp_path / "with", EXTENSIONS))
    assert "billing" in newapp.singular_apps_the_grammar_admits()


def test_a_product_module_passes_rule_11_with_its_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, at_copy: Any
) -> None:
    """The `billing` app's `pricing.py` reds rule 11 bare, naming the road; declared, it passes."""
    at_copy(_product(tmp_path, None))
    red = _rule_11(monkeypatch, tmp_path)
    assert len(red) == 1 and "pricing.py" in red[0] and "scope_extensions: {11:" in red[0], red
    at_copy(_product(tmp_path / "with", EXTENSIONS))
    assert _rule_11(monkeypatch, tmp_path / "with") == []


def test_a_public_view_and_route_pass_rule_3_with_their_extension(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, at_copy: Any
) -> None:
    """A product's open view reds rule 3 bare, naming the road; its route joins the allow-list."""
    at_copy(_product(tmp_path, None))
    red = _rule_3_views(monkeypatch)
    assert len(red) == 1 and "billing-status" in red[0] and "scope_extensions: {3:" in red[0], red
    assert "api:billing-status" not in checks.unauthenticated_url_names()
    at_copy(_product(tmp_path / "with", EXTENSIONS))
    assert _rule_3_views(monkeypatch) == []
    assert "api:billing-status" in checks.unauthenticated_url_names()
    assert "apps_billing_api_status" in checks.unauthenticated_operation_ids()
