# census: cross-app population=apps/*/services.py,apps/*/selectors.py for the door's vocabulary
"""The domain vocabulary, and the rule that makes it worth having.

House rule 14 is a *shape* rule, not a taste one: a `services.py` that imported
`HttpError` would be callable only from the REST door, and there are five. The
last test here reads the tree and proves nothing under `services.py` or
`selectors.py` names a status code or an HTTP exception. It is the cheap
version of the gate's own check, and it fails on the day somebody reaches for
`Http404` in a service.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.core.exceptions import (
    NON_FIELD_KEY,
    Conflict,
    DomainError,
    Forbidden,
    Invalid,
    NotFound,
    RateLimited,
    as_invalid,
)
from apps.core.tests.tree_census import source_tree

APPS_DIR = Path(__file__).resolve().parents[3] / "apps"

# What a service may not reach for: the door's vocabulary, not the domain's.
FORBIDDEN_IMPORTS = ("ninja", "django.http")
FORBIDDEN_NAMES = ("HttpError", "Http404")


def test_every_refusal_is_a_domain_error_with_a_stable_code() -> None:
    for exc in (NotFound(), Conflict(), Forbidden(), Invalid(), RateLimited()):
        assert isinstance(exc, DomainError)
        assert exc.code and exc.code != DomainError.code
        assert str(exc) == exc.detail


def test_invalid_keeps_the_fields_and_summarises_them() -> None:
    exc = Invalid({"name": ["Too short."], "notes": ["Not like that."]})
    assert exc.errors == {"name": ["Too short."], "notes": ["Not like that."]}
    assert "Too short." in exc.detail and "Not like that." in exc.detail


def test_invalid_from_django_keeps_the_field_map() -> None:
    exc = Invalid.from_django(DjangoValidationError({"name": ["Too short."]}))
    assert exc.errors == {"name": ["Too short."]}


def test_invalid_from_django_puts_an_object_level_message_under_all() -> None:
    exc = Invalid.from_django(DjangoValidationError("Nothing about this holds."))
    assert exc.errors == {NON_FIELD_KEY: ["Nothing about this holds."]}


def test_as_invalid_translates_and_keeps_the_cause() -> None:
    with pytest.raises(Invalid) as raised:
        with as_invalid():
            raise DjangoValidationError({"name": ["Too short."]})
    assert raised.value.errors == {"name": ["Too short."]}
    assert isinstance(raised.value.__cause__, DjangoValidationError)


def test_as_invalid_lets_everything_else_through() -> None:
    with pytest.raises(RuntimeError):
        with as_invalid():
            raise RuntimeError("not a validation problem")


def _offences(source: Path) -> list[str]:
    tree = source_tree(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [a.name for a in node.names if a.name.split(".")[0] in FORBIDDEN_IMPORTS]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in FORBIDDEN_IMPORTS:
                found += [f"{module}.{a.name}" for a in node.names]
            found += [a.name for a in node.names if a.name in FORBIDDEN_NAMES]
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            found.append(node.id)
    return found


@pytest.mark.parametrize("filename", ["services.py", "selectors.py"])
def test_no_service_or_selector_speaks_http(filename: str) -> None:
    checked = sorted(APPS_DIR.glob(f"*/{filename}"))
    assert checked, f"no {filename} found — the scan would pass vacuously"
    for source in checked:
        assert _offences(source) == [], f"{source} reaches for the door's vocabulary"
