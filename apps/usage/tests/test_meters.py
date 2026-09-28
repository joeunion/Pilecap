"""The vocabulary: what a meter name is, who declares it, and when it is refused.

The property under test is not "the regular expression works". It is that a name
nobody declared **cannot reach the ledger**, because that is the failure a meter
registry exists to prevent: a typo accrues money under a name no aggregate sums,
no threshold matches, and nobody notices until a customer's bill is short.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core.exceptions import Invalid
from apps.usage.meters import (
    check_meter,
    declared_meters,
    grammar_complaint,
    validate_declared_meters,
)
from apps.usage.tests.conftest import METER, plant_meters, unplant_meters


def test_a_real_meters_module_is_discovered_by_the_real_walk(declared_meter: str) -> None:
    """The registry finds a file it has never seen, in an app that is not this one.

    The whole point of discovery: an app declares its meters in its own file and
    edits nothing central, so five apps in a parallel wave never collide over one
    list. A test that monkeypatched the registry could not tell this from a
    registry that finds nothing.
    """
    registry = declared_meters()
    assert declared_meter in registry.get("example", frozenset())
    assert check_meter(declared_meter) == declared_meter


def test_a_planted_meters_module_is_invisible_to_every_other_worker(declared_meter: str) -> None:
    """The plant is found by this process's walk and by nobody else's.

    Every xdist worker runs out of one checkout, so a plant written into
    `apps/example/` is a module every other worker's `declared_meters()` walks —
    found by `find_spec`, removed by this fixture's teardown before
    `import_module` reads it, and a test that only meant to record some usage
    fails with `FileNotFoundError`. The shared tree is the one thing the workers
    have in common, so it is the thing the plant must leave alone.
    """
    assert declared_meter in declared_meters().get("example", frozenset())
    shared = Path(importlib.import_module("apps.example").__file__ or "").parent / "meters.py"
    assert not shared.exists(), f"the plant is in the shared tree at {shared}"


def test_a_meter_no_app_declares_is_refused(a_declared_meter: str) -> None:
    """A plausible typo is refused, and the refusal names where it should live."""
    with pytest.raises(Invalid) as refusal:
        check_meter("example.widgets.conut")
    assert refusal.value.errors["meter"] == [
        "'example.widgets.conut' is not declared in apps/example/meters.py."
    ]


def test_a_meter_from_an_app_that_declares_nothing_is_refused(a_declared_meter: str) -> None:
    with pytest.raises(Invalid) as refusal:
        check_meter("nosuchapp.tokens.input")
    assert "declares any meters" in refusal.value.errors["meter"][0]


@pytest.mark.parametrize(
    ("name", "tell"),
    [
        ("widgets.count", "three segments"),
        ("example.widgets.count.extra", "three segments"),
        ("Example.Widgets.Count", "lowercase letters"),
        ("example..count", "lowercase letters"),
        ("example.widgets.9count", "lowercase letters"),
        ("example.widgets." + "x" * 200, "longer than"),
    ],
)
def test_the_grammar_refuses_what_is_not_app_noun_unit(name: str, tell: str) -> None:
    """Every way a name can fail the grammar says which way it failed.

    A refusal that only said "invalid" would send the reader to the regular
    expression; each of these sends them to the rule they broke.
    """
    assert tell in grammar_complaint(name)


def test_a_well_formed_name_has_no_complaint() -> None:
    assert grammar_complaint(METER) == ""
    assert grammar_complaint(METER, app_label="example") == ""


def test_a_name_claiming_another_apps_label_is_refused() -> None:
    """The first segment is the DECLARING app, which is what makes it a check.

    Without this, `apps/example/meters.py` could declare `files.storage.bytes`
    and two apps would own one published contract — with no way to tell, from the
    name, which of them a rename has to go through.
    """
    complaint = grammar_complaint("files.storage.bytes", app_label="example")
    assert "claims the app 'files'" in complaint


@pytest.mark.django_db
def test_a_malformed_declaration_refuses_at_boot() -> None:
    """A bad name in a real `meters.py` stops the process, not the request.

    `UsageConfig.ready()` calls this, so what a deployment gets is a refusal to
    start rather than a meter that quietly accrues under a name nothing matches.
    The plant is this test's own victim and is removed whatever happens.
    """
    plant_meters('BROKEN = "example.widgets"\n')
    try:
        with pytest.raises(ImproperlyConfigured) as refusal:
            validate_declared_meters()
        assert "apps/example/meters.py declares a meter that is not a meter name" in str(
            refusal.value
        )
        assert "three segments" in str(refusal.value)
    finally:
        unplant_meters()


@pytest.mark.django_db
def test_a_declaration_claiming_another_app_refuses_at_boot() -> None:
    """The second half of the same refusal, planted the other way."""
    plant_meters('STOLEN = "files.storage.bytes"\n')
    try:
        with pytest.raises(ImproperlyConfigured) as refusal:
            validate_declared_meters()
        assert "claims the app 'files'" in str(refusal.value)
    finally:
        unplant_meters()


def test_the_declared_vocabulary_on_this_tree_is_valid() -> None:
    """Whatever the tree actually declares today, it is well-formed.

    Zero meters is a legal answer right now — `files` and `completions` arrive in
    later rungs — and this test is here so that the day one of them lands with a
    bad name, a test in THIS app says so rather than a worker failing to boot in
    somebody's staging environment.
    """
    assert validate_declared_meters() == declared_meters()
