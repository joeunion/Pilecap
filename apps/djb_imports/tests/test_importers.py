"""The importer registry: discovered through the family's walk, refused when malformed."""

from __future__ import annotations

import importlib.machinery
import sys
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.djb_imports.selectors import get_importer, list_importers
from apps.djb_imports.tests import planted


def _plant(monkeypatch: pytest.MonkeyPatch, dotted: str, declared: dict[str, object]) -> None:
    module = ModuleType(dotted)
    module.__spec__ = importlib.machinery.ModuleSpec(dotted, loader=None)
    module.IMPORTERS = declared  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, dotted, module)


def test_a_planted_importers_module_is_found(planted_importer: None) -> None:
    assert list_importers() == planted.IMPORTERS
    assert get_importer("widget") is planted.IMPORTERS["widget"]
    assert get_importer("gadget") is None


def test_one_kind_declared_twice_is_refused_naming_both(
    planted_importer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(monkeypatch, "apps.files.importers", {"widget": planted.IMPORTERS["widget"]})

    with pytest.raises(ImproperlyConfigured, match="both declare an importer for .widget."):
        list_importers()


def test_a_value_that_is_not_an_importer_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _plant(monkeypatch, "apps.example.importers", {"widget": object()})

    with pytest.raises(ImproperlyConfigured, match="apps.core.verbs.Importer"):
        list_importers()
