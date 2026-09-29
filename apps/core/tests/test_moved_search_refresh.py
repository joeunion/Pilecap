"""A searchable `Movable` refreshes its document on `.moved`.

A search document carries its row's organization — that is who may find it. A
row that MOVES changes node, and a kind whose `refresh_on` does not name the
row's `<app>.<noun>.moved` event keeps its document at the node it left: found
by the branch it left, missed by the one it joined, until the hourly reconcile
gets to it.

**The census.** Every declared searchable kind (each app's `search.py`
`SEARCHABLES`, found the way the search app finds them — by the conventional
module, never a list) whose model declares `Movable` must name a `refresh_on`
event whose noun is the model's kind and whose verb is `moved`. Planted both
ways below; the live population is asserted too.
"""

from __future__ import annotations

import importlib
import importlib.util
from types import SimpleNamespace
from typing import Any

from django.apps import apps as django_apps

from apps.core.authz import kind_of
from apps.core.models import is_movable
from apps.example.models import Widget

#: The conventional module a searchable kind is declared in, and its attribute.
SEARCH_MODULE = "search"
SEARCHABLES = "SEARCHABLES"


def declared_searchables() -> list[Any]:
    """Every installed app's `search.py` `SEARCHABLES`, in app order."""
    found: list[Any] = []
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module = f"{config.name}.{SEARCH_MODULE}"
        if importlib.util.find_spec(module) is None:
            continue
        found.extend(getattr(importlib.import_module(module), SEARCHABLES, None) or [])
    return found


def stale_on_move(searchables: list[Any]) -> list[str]:
    """The movable kinds whose `refresh_on` names no `<app>.<kind>.moved` event."""
    stale: list[str] = []
    for declaration in searchables:
        model = declaration.model
        if not is_movable(model):
            continue
        kind = kind_of(model)
        moved = [
            name
            for name in declaration.refresh_on
            if str(name).split(".")[1:] == [str(kind), "moved"]
        ]
        if not moved:
            stale.append(f"{model._meta.label} ({declaration.label})")
    return stale


def test_every_searchable_movable_kind_refreshes_on_moved() -> None:
    assert stale_on_move(declared_searchables()) == []


def test_the_census_names_a_movable_kind_that_omits_moved() -> None:
    assert is_movable(Widget), "the planted kind needs a movable model"
    planted = SimpleNamespace(
        model=Widget,
        label="zzz-stale-widgets",
        refresh_on=("example.widget.created", "example.widget.updated"),
    )
    assert stale_on_move([planted]) == ["example.Widget (zzz-stale-widgets)"]


def test_the_census_is_silent_for_a_kind_that_names_moved() -> None:
    planted = SimpleNamespace(
        model=Widget,
        label="zzz-fresh-widgets",
        refresh_on=("example.widget.created", "example.widget.moved"),
    )
    assert stale_on_move([planted]) == []


def test_the_population_is_not_empty() -> None:
    """The floor: a walk that found no searchable kind would make the census vacuous."""
    assert declared_searchables()
