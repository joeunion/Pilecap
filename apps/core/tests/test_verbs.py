"""The noun-verb family's seam: the hook walk, the marker walk, the blocker walk.

Every plant here goes through the REAL discovery walk: a module object with a
real `__spec__` placed in `sys.modules` is what `importlib.util.find_spec`
answers first, so the walk under test is the one production runs — never a
seam around it. Each plant is removed with its test (`monkeypatch`).
"""

from __future__ import annotations

import importlib.machinery
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import models

from apps.core import discovery, verbs
from apps.core.authz import _declarations, policies, reset_policies
from apps.core.blockers import BLOCKER_VERBS, blockers_for, declared_blockers
from apps.core.exceptions import Blocker
from apps.core.models import OrgScopedModel
from apps.core.tests.isolation import isolated_apps

#: The app the plants land in. Any installed `apps.*` app answers the walk; the
#: worked example is the one a product reads.
HOME = "apps.example"


@pytest.fixture(autouse=True)
def _vocabulary_restored() -> Iterator[None]:
    reset_policies()
    yield
    reset_policies()


def plant(monkeypatch: pytest.MonkeyPatch, dotted: str, **attributes: Any) -> ModuleType:
    module = ModuleType(dotted)
    module.__spec__ = importlib.machinery.ModuleSpec(dotted, loader=None)
    for name, value in attributes.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, dotted, module)
    return module


class _Spy(ModuleType):
    """A module that records every attribute anybody asks it for."""

    asked: list[str]

    def __getattr__(self, name: str) -> Any:
        self.__dict__.setdefault("asked", []).append(name)
        raise AttributeError(name)


def held_by_live_rows(*, tenant: Any, obj: Any) -> tuple[Blocker, ...]:
    return (
        Blocker(
            noun="widget",
            door=f"route:widget-list?policy={obj}",
            label="Move or archive the widgets that name this policy first",
        ),
    )


# --- the walk the vocabulary and the family share ----------------------------


def test_the_vocabulary_walks_through_the_family_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """`authz._declarations` is a caller of `discovery.declared` — one walk, two readers.

    A planted `policies.py` reaches the policy registry through the family's
    walk, so the two can never come to disagree about what an app declared.
    """
    calls: list[tuple[str, str]] = []
    real = discovery.declared

    def counted(module: str, attribute: str, **kwargs: Any) -> Any:
        calls.append((module, attribute))
        return real(module, attribute, **kwargs)

    monkeypatch.setattr(discovery, "declared", counted)
    assert _declarations("policies", "POLICIES") == real("policies", "POLICIES")
    assert ("policies", "POLICIES") in calls

    def planted_predicate(actor: Any, obj: Any = None) -> bool:
        return True

    plant(monkeypatch, f"{HOME}.zzz_verbs_probe", POLICIES={"widget.update": planted_predicate})
    found = real("zzz_verbs_probe", "POLICIES")
    assert [(config.label, dict(value)) for config, value in found] == [
        ("example", {"widget.update": planted_predicate})
    ]
    assert policies()  # the registry still derives through the moved walk


def test_the_vocabulary_reading_ignores_a_non_dict_and_a_hook_refuses_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plant(monkeypatch, "apps.example_portal.archive_blockers", BLOCKERS={})
    elsewhere = _declarers_beside(HOME, "archive_blockers")
    assert "apps.example_portal" in elsewhere
    plant(monkeypatch, f"{HOME}.archive_blockers", BLOCKERS=["not", "a", "dict"])
    assert _declarers_beside(None, "archive_blockers") == elsewhere
    with pytest.raises(ImproperlyConfigured) as caught:
        verbs.hook("archive_blockers")
    assert "apps/example/archive_blockers.py" in str(caught.value)


def _declarers_beside(home: str | None, module: str) -> list[str]:
    """The apps whose `<module>.BLOCKERS` the vocabulary reads, `home` left out."""
    return [config.name for config, _ in verbs.declared(module, "BLOCKERS") if config.name != home]


def test_a_hook_name_outside_the_closed_tuple_is_never_walked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _Spy(f"{HOME}.frobnicate_blockers")
    spy.__spec__ = importlib.machinery.ModuleSpec(spy.__name__, loader=None)
    monkeypatch.setitem(sys.modules, spy.__name__, spy)

    with pytest.raises(ValueError, match="not a family hook module"):
        verbs.hook("frobnicate_blockers")
    with pytest.raises(ValueError, match="one of archive, restore, move, merge"):
        blockers_for("frobnicate", "widget", tenant=None, obj=None)
    assert spy.__dict__.get("asked", []) == []


def test_the_hook_digest_names_modules_per_app(monkeypatch: pytest.MonkeyPatch) -> None:
    before = verbs.declared_hooks()
    plant(monkeypatch, f"{HOME}.archive_blockers", BLOCKERS={})
    plant(monkeypatch, f"{HOME}.merge_repointers", REPOINTERS={})
    after = verbs.declared_hooks()
    assert after["example"] == sorted(
        {*before.get("example", []), "archive_blockers", "merge_repointers"}
    )


@isolated_apps("apps.core")
def test_the_marker_walk_is_the_registry() -> None:
    class ZzzMarked(OrgScopedModel):
        archivable = True
        label = models.CharField(max_length=10)

        class Meta:
            app_label = "core"

    class ZzzUnmarked(OrgScopedModel):
        label = models.CharField(max_length=10)

        class Meta:
            app_label = "core"

    found = verbs.declared_models("archivable", registry=ZzzMarked._meta.apps)
    assert ZzzMarked in found
    assert ZzzUnmarked not in found


def test_every_road_names_a_marker_and_its_routes() -> None:
    assert verbs.ROADS["archive"].marker == "archivable"
    assert verbs.ROADS["archive"].routes == ("archive", "restore")
    assert set(verbs.ROADS["archive"].settled) == {"archive", "restore"}


# --- A1.5 · the blocker walk --------------------------------------------------


def test_blockers_for_returns_what_a_planted_app_declares(monkeypatch: pytest.MonkeyPatch) -> None:
    plant(monkeypatch, f"{HOME}.archive_blockers", BLOCKERS={"widget_policy": held_by_live_rows})

    held = blockers_for("archive", "widget_policy", tenant=None, obj="p1")

    assert held == (
        Blocker(
            noun="widget",
            door="route:widget-list?policy=p1",
            label="Move or archive the widgets that name this policy first",
        ),
    )
    assert blockers_for("archive", "widget", tenant=None, obj="p1") == ()
    # The verb decides the module: a RESTORE asks restore_blockers, not archive's.
    assert blockers_for("restore", "widget_policy", tenant=None, obj="p1") == ()


def test_the_blocker_verbs_are_the_closed_tuples_blocker_members() -> None:
    assert BLOCKER_VERBS == ("archive", "restore", "move", "merge")


@pytest.mark.parametrize(
    ("blockers", "says"),
    [
        (["widget_policy"], "must export `BLOCKERS` as a dict"),
        ({"Widget Policy": held_by_live_rows}, "is not a noun word"),
        ({"widget_policy": "not callable"}, "is not callable"),
    ],
    ids=["not-a-dict", "not-a-noun", "not-callable"],
)
def test_a_malformed_declaration_is_refused_naming_its_file(
    monkeypatch: pytest.MonkeyPatch, blockers: Any, says: str
) -> None:
    plant(monkeypatch, f"{HOME}.archive_blockers", BLOCKERS=blockers)
    with pytest.raises(ImproperlyConfigured) as caught:
        blockers_for("archive", "widget_policy", tenant=None, obj="p1")
    assert "apps/example/archive_blockers.py" in str(caught.value)
    assert says in str(caught.value)


def test_a_function_answering_a_list_is_refused_naming_its_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def answers_a_list(*, tenant: Any, obj: Any) -> Any:
        return list(held_by_live_rows(tenant=tenant, obj=obj))

    plant(monkeypatch, f"{HOME}.archive_blockers", BLOCKERS={"widget_policy": answers_a_list})
    with pytest.raises(ImproperlyConfigured) as caught:
        blockers_for("archive", "widget_policy", tenant=None, obj="p1")
    assert "apps/example/archive_blockers.py" in str(caught.value)
    assert "answered list" in str(caught.value)


def test_declared_blockers_is_every_app_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    plant(monkeypatch, f"{HOME}.move_blockers", BLOCKERS={"widget": held_by_live_rows})
    assert [label for label, _ in declared_blockers("move")] == ["example"]


@pytest.mark.parametrize(
    "fields",
    [
        {"noun": "Widget", "door": "route:widget-list", "label": "x"},
        {"noun": "widget", "door": "https://example.com/widgets", "label": "x"},
        {"noun": "widget", "door": "self:reread", "label": "x"},
        {"noun": "widget", "door": "route:widget-list", "label": "  "},
    ],
    ids=["noun", "url-door", "other-kind-door", "empty-label"],
)
def test_a_malformed_blocker_is_refused_where_it_is_written(fields: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        Blocker(**fields)
