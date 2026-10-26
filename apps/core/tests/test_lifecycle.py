"""LF1-1: the lifecycle primitive is closed, and it refuses at import.

Criterion LF1-1 of rung LF-1 (cycle P5's lead report, under the ratified
ADR core-13 — `docs/product/architecture.md`, the ADR home). Its absent-answer
is the whole reason this file exists first: seven rungs fan out from
`apps/core/lifecycle.py`, and a seam proven only in prose is the cycle-0
four-trees defect — four rungs building four different things against one
sentence.

Two properties carry the criterion:

* **The census closes.** `declared_lifecycles()` and `undeclared_models()`
  partition the concrete registry with nothing falling between them and nothing
  in both. That is the property rule 31 (LF-Q) will stand on, and it is the one
  that fails silently — a reader that quietly skipped a model would make a
  backlog look smaller than it is, which is the failure mode a ratchet cannot
  survive.
* **A malformed declaration refuses at import.** `PURGED` with nothing to purge
  it, `UNBOUNDED` with no reason or no dated trigger. At import and not at gate
  time: the tier `core.exceptions.register_refusal` set (E9), and the only one
  that cannot be wrong in a running process.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import textwrap
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.apps.registry import Apps
from django.contrib.sites.models import Site
from django.db import models

from apps.core import lifecycle as lifecycle_module
from apps.core.audit import AuditEntry
from apps.core.idempotency import IdempotencyRecord
from apps.core.lifecycle import (
    LIFECYCLE_ATTR,
    Lifecycle,
    LifecycleKind,
    LifecycleRegistry,
    declared_lifecycles,
    declared_populations,
    lifecycle_of,
    population_sources,
    third_party_lifecycles,
    undeclared_models,
)
from apps.core.models import Invitation, Membership, Organization, Tenant

# --- the vocabulary ----------------------------------------------------------


def test_the_vocabulary_is_four_words_and_closed() -> None:
    """ADR core-13's lexicon, verbatim. A fifth word is an ADR, not a string."""
    assert [kind.value for kind in LifecycleKind] == [
        "purged",
        "bounded",
        "unbounded",
        "append_only",
    ]


def test_an_invented_kind_refuses() -> None:
    with pytest.raises(ValueError, match="one of purged, bounded, unbounded, append_only"):
        Lifecycle(kind="eventually")  # type: ignore[arg-type]


# --- malformed declarations refuse AT IMPORT ---------------------------------
#
# The constructor-level proofs come first because they name the exact sentence;
# the module-import proof below is what makes the TIER true, and it imports a
# real file through the real machinery rather than calling `__post_init__`.


def test_purged_without_a_purger_refuses() -> None:
    """The poller-that-was-never-built, refused at the declaration site."""
    with pytest.raises(ValueError, match="names what purges it"):
        Lifecycle(kind=LifecycleKind.PURGED)


def test_purged_by_must_be_a_dotted_path() -> None:
    """Rule 31 has to RESOLVE it, so a bare function name is not a declaration."""
    with pytest.raises(ValueError, match="DOTTED path"):
        Lifecycle(kind=LifecycleKind.PURGED, purged_by="purge_expired")


def test_a_purger_on_a_kind_that_does_not_purge_refuses() -> None:
    """A sweeper named on a bounded table is a wrong kind or an unmeant delete."""
    with pytest.raises(ValueError, match="only meaningful on a `purged` lifecycle"):
        Lifecycle(kind=LifecycleKind.BOUNDED, purged_by="apps.core.idempotency.purge_expired")


@pytest.mark.parametrize("kind", [LifecycleKind.UNBOUNDED, LifecycleKind.APPEND_ONLY])
def test_a_reasoned_kind_without_a_reason_refuses(kind: LifecycleKind) -> None:
    with pytest.raises(ValueError, match="carries a `reason`"):
        Lifecycle(kind=kind, trigger="2026-08-24 — something")


@pytest.mark.parametrize("kind", [LifecycleKind.UNBOUNDED, LifecycleKind.APPEND_ONLY])
def test_a_reasoned_kind_without_a_dated_trigger_refuses(kind: LifecycleKind) -> None:
    with pytest.raises(ValueError, match="DATED `trigger`"):
        Lifecycle(kind=kind, reason="a reason long enough to be a clause", trigger="when it grows")


def test_a_one_word_reason_is_not_a_reason() -> None:
    """An escape hatch nobody has to justify is an off switch — gate.py's number."""
    with pytest.raises(ValueError, match="carries a `reason`"):
        Lifecycle(
            kind=LifecycleKind.UNBOUNDED,
            reason="big",
            trigger="2026-08-24 — something",
        )


def test_a_shaped_but_impossible_date_is_not_a_date() -> None:
    """`2026-13-45` matches the SHAPE of a date and is not one."""
    with pytest.raises(ValueError, match="DATED `trigger`"):
        Lifecycle(
            kind=LifecycleKind.UNBOUNDED,
            reason="a reason long enough to be a clause",
            trigger="2026-13-45 — never",
        )


def test_a_malformed_declaration_refuses_AT_IMPORT(tmp_path: Path) -> None:
    """**The tier.** A real module, imported the real way, raising on import.

    E9's precedent (`core.exceptions.register_refusal`) and the strongest tier
    the tree has. A system check would be quieter and would let a wrong
    declaration ride in a running process until somebody remembered to run
    `manage.py check`; a gate rule would let it ride until somebody ran the
    gate. This raises the moment the class body is evaluated.
    """
    module_name = "djb_lifecycle_import_probe"
    source = tmp_path / f"{module_name}.py"
    source.write_text(
        textwrap.dedent(
            """
            from apps.core.lifecycle import Lifecycle, LifecycleKind

            class Malformed:
                lifecycle = Lifecycle(kind=LifecycleKind.PURGED)
            """
        )
    )
    sys.path.insert(0, str(tmp_path))
    try:
        with pytest.raises(ValueError, match="names what purges it"):
            importlib.import_module(module_name)
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop(module_name, None)


# --- the readers, and the census ---------------------------------------------


def test_the_census_closes_over_the_concrete_registry() -> None:
    """LF1-1's pin: declared + undeclared == the registry, and nothing is in both.

    Cycle-0 #8's shape — a reader that quietly skipped a model would make a
    backlog look smaller than it is, and a ratchet built on a lying census
    ratchets nothing. Asserted as a partition rather than as two counts,
    because two counts that happen to add up is not the same claim.
    """
    registry = {model._meta.label for model in django_apps.get_models()}
    declared = set(declared_lifecycles())
    undeclared = {model._meta.label for model in undeclared_models()}

    assert declared | undeclared == registry
    assert declared & undeclared == set()


def test_undeclared_models_is_the_registry_minus_the_declarations() -> None:
    """The same sentence the criterion uses, said as one equality."""
    registry = {model._meta.label for model in django_apps.get_models()}
    assert {model._meta.label for model in undeclared_models()} == registry - set(
        declared_lifecycles()
    )


def test_undeclared_models_is_ordered_so_a_backlog_is_diffable() -> None:
    labels = [model._meta.label for model in undeclared_models()]
    assert labels == sorted(labels)


def test_a_declaration_knows_which_model_it_belongs_to() -> None:
    """`declared_for` is filled by the reader, never written by hand."""
    assert lifecycle_of(Tenant) is not None
    assert lifecycle_of(Tenant).declared_for == "core.Tenant"  # type: ignore[union-attr]
    assert Tenant.lifecycle.declared_for == ""


def test_an_attribute_named_lifecycle_that_is_not_one_is_not_a_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reader is TYPED, so a model's own `lifecycle` column or attribute is no declaration.

    why-not `Site`: `apps/accounts/lifecycle.py` declares it; a stand-in no declaration can claim.
    """

    class StandIn(models.Model):
        lifecycle = models.CharField(max_length=16)

        class Meta:
            app_label = "lifecycle_stand_in"
            apps = Apps()

        def __str__(self) -> str:
            return self.lifecycle

    assert getattr(StandIn, LIFECYCLE_ATTR) is not None
    assert StandIn._meta.label not in third_party_lifecycles()
    assert lifecycle_of(StandIn) is None
    monkeypatch.setattr(StandIn, LIFECYCLE_ATTR, "quarterly")
    assert lifecycle_of(StandIn) is None


# --- core's own six ----------------------------------------------------------


def test_every_core_model_declares_its_lifecycle() -> None:
    """LF-1 owns `apps/core/**`, and this is the whole of what it owns."""
    core_models = {
        model._meta.label for model in django_apps.get_models() if model._meta.app_label == "core"
    }
    assert core_models <= set(declared_lifecycles())


@pytest.mark.parametrize(
    ("model", "kind"),
    [
        (Tenant, LifecycleKind.UNBOUNDED),
        (Organization, LifecycleKind.UNBOUNDED),
        (Membership, LifecycleKind.BOUNDED),
        (Invitation, LifecycleKind.UNBOUNDED),
        (IdempotencyRecord, LifecycleKind.PURGED),
        (AuditEntry, LifecycleKind.APPEND_ONLY),
    ],
)
def test_the_core_declarations_say_what_the_rung_said_they_would(
    model: type[Any], kind: LifecycleKind
) -> None:
    declared = lifecycle_of(model)
    assert declared is not None
    assert declared.kind is kind


def test_the_idempotency_record_is_the_worked_example() -> None:
    """The grammar fits something REAL: the callable exists and is importable.

    `purged_by` is resolved here rather than merely compared as a string,
    because a dotted path that resolves to nothing is exactly the promise this
    vocabulary exists to stop somebody making. Rule 31 (LF-Q) takes the next
    step and walks from the callable to the schedule that reaches it; this
    proves the first link.
    """
    declared = lifecycle_of(IdempotencyRecord)
    assert declared is not None
    assert declared.purged_by == "apps.core.idempotency.purge_expired"

    module_path, _, attribute = declared.purged_by.rpartition(".")
    assert callable(getattr(importlib.import_module(module_path), attribute))


def test_the_audit_entry_is_append_only_in_both_declarations() -> None:
    """Two attributes, two questions, and they agree.

    `append_only = True` says rows are never rewritten (rule 20's population);
    `lifecycle` says what happens to them over time (rule 31's). A table can be
    one without the other, which is why they are separate — and this one is
    both, which is why they have to agree.
    """
    assert AuditEntry.append_only is True
    declared = lifecycle_of(AuditEntry)
    assert declared is not None
    assert declared.is_append_only


# --- the third-party hook ----------------------------------------------------


def test_no_shared_file_exists_for_third_party_declarations() -> None:
    """The parallel-agents invariant, asserted as an absence.

    The failure this guards against is a central
    `THIRD_PARTY_LIFECYCLES` dict that every app in a wave has to edit — one
    shared file, one merge conflict per app, which is the collision the whole
    template is built around removing. The declaration surface is
    `apps/<x>/lifecycle.py` and there is nowhere else to put one.
    """
    assert not hasattr(lifecycle_module, "THIRD_PARTY_LIFECYCLES")
    module_constants = {
        name
        for name, value in vars(lifecycle_module).items()
        if not name.startswith("_") and isinstance(value, dict)
    }
    assert module_constants == set()

    # And the one surface there is, is composed from the app rather than listed:
    # `<app>.lifecycle`, per installed app, found by the one discovery walk.
    walk = inspect.getsource(lifecycle_module._third_party_registry)
    assert "imported(LIFECYCLE_ATTR)" in walk


def test_a_third_party_module_is_discovered_and_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """The discovery walk, over a real module, through the real machinery.

    Only the app-config list is doubled — `find_spec`, `import_module` and
    `register(registry)` are all the production path over
    `apps/core/tests/lifecycle.py`, which is a real file with a real
    `register`. No app in this tree owns a third-party table yet (allauth's two
    and `django_session` are not declared yet), so a double is
    the only way to prove the walk today; the day those exist, production code
    proves it and `apps/core/tests/lifecycle.py` goes away.
    """

    class FakeConfig:
        name = "apps.core.tests"

    monkeypatch.setattr(django_apps, "get_app_configs", lambda: [FakeConfig()])

    declared = third_party_lifecycles()
    assert Site._meta.label in declared
    assert declared[Site._meta.label].kind is LifecycleKind.UNBOUNDED
    assert lifecycle_of(Site) is not None


def test_an_app_without_a_lifecycle_module_is_simply_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery, not registration: an app declares by existing, or not at all.

    **Re-pointed twice as the tree grew.** It first named `apps/realtime` as
    the bare app, under a cross-territory exception; then a stronger derived
    form landed the
    first real
    `apps/<x>/lifecycle.py` — `apps/accounts/lifecycle.py`, allauth's five
    tables — exactly as the sibling test above anticipated ("the day those
    exist, production code proves it"). What this asserted before was
    `third_party_lifecycles() == {}`, which was the same property only while the
    population happened to be empty, and is now simply false.

    The property has not changed and is now stated as itself: point the walk at
    one app that has NO module and it declares nothing. The app is DERIVED
    rather than named, so this keeps proving the skip as the declaration fan-out
    gives the remaining apps their modules, right up until none is left — at
    which point it says so instead of passing vacuously.
    """
    bare = next(
        (
            config.name
            for config in django_apps.get_app_configs()
            if config.name.startswith("apps.")
            and config.name != lifecycle_module.__name__.rsplit(".", 1)[0]
            and importlib.util.find_spec(f"{config.name}.{LIFECYCLE_ATTR}") is None
        ),
        None,
    )
    assert bare is not None, "every app now has a lifecycle module — nothing left to skip"

    class FakeConfig:
        name = bare

    monkeypatch.setattr(django_apps, "get_app_configs", lambda: [])
    core_only = third_party_lifecycles()
    monkeypatch.setattr(django_apps, "get_app_configs", lambda: [FakeConfig()])

    assert third_party_lifecycles() == core_only


def test_the_primitive_does_not_discover_itself() -> None:
    """`apps.core.lifecycle` IS the primitive and declares nothing about itself."""
    assert not hasattr(lifecycle_module, "register")


def test_two_apps_declaring_one_table_differently_is_refused() -> None:
    """Import order is not a way to settle a disagreement about retention."""
    registry = LifecycleRegistry()
    registry.declare(
        Site,
        Lifecycle(
            kind=LifecycleKind.UNBOUNDED,
            reason="one app's opinion, long enough to be a clause",
            trigger="2026-08-24 — a trigger",
        ),
        source="apps.first.lifecycle",
    )
    with pytest.raises(ValueError, match="already has a lifecycle declared by"):
        registry.declare(
            Site,
            Lifecycle(kind=LifecycleKind.BOUNDED),
            source="apps.second.lifecycle",
        )


def test_the_same_declaration_twice_is_not_a_disagreement() -> None:
    """A module imported twice is not an error — `register_refusal`'s precedent."""
    registry = LifecycleRegistry()
    same = Lifecycle(kind=LifecycleKind.BOUNDED)
    registry.declare(Site, same, source="apps.first.lifecycle")
    registry.declare(Site, same, source="apps.first.lifecycle")
    assert registry.declarations()[Site._meta.label].kind is LifecycleKind.BOUNDED


def test_a_model_that_can_declare_for_itself_is_not_declared_from_outside() -> None:
    """One table, one declaration, and the model's own always wins by refusing."""
    registry = LifecycleRegistry()
    with pytest.raises(ValueError, match="declares its own `lifecycle` on the model"):
        registry.declare(Tenant, Lifecycle(kind=LifecycleKind.BOUNDED), source="apps.x.lifecycle")


# --- the off-ORM half: populations no table holds ------------------------------


A_POPULATION = Lifecycle(
    kind=LifecycleKind.PURGED,
    purged_by="apps.example.services.purge_scratch",
    reason="a scratch population, declared by a test and held by nothing",
)


def test_a_population_is_declared_by_name_and_read_back_by_name() -> None:
    """The whole of the off-ORM half: a keyspace with no `_meta.label` to key on."""
    registry = LifecycleRegistry()
    registry.declare_population("scratch.Blob", A_POPULATION, source="apps.x.lifecycle")

    assert registry.populations() == {
        "scratch.Blob": replace(A_POPULATION, declared_for="scratch.Blob")
    }
    assert registry.sources()["scratch.Blob"] == "apps.x.lifecycle"


def test_a_population_never_lands_in_the_model_key_space() -> None:
    """Two dicts, deliberately.

    Readers downstream split a declaration key on its dot to get an app label;
    a population name sitting in the model half would silently become a model in
    an app no database has.
    """
    registry = LifecycleRegistry()
    registry.declare_population("scratch.Blob", A_POPULATION, source="apps.x.lifecycle")
    assert registry.declarations() == {}


def test_a_concrete_models_label_is_refused_as_a_population() -> None:
    """A table carries its declaration on the class. This is `declare`'s refusal
    from the other side, and without it the two halves could hold two opinions
    about one set of rows."""
    registry = LifecycleRegistry()
    with pytest.raises(ValueError, match="is a concrete model's label"):
        registry.declare_population(Tenant._meta.label, A_POPULATION, source="apps.x.lifecycle")


def test_two_apps_declaring_one_population_differently_is_refused() -> None:
    """Import order is not a way to settle a disagreement about erasure, either."""
    registry = LifecycleRegistry()
    registry.declare_population("scratch.Blob", A_POPULATION, source="apps.first.lifecycle")
    with pytest.raises(ValueError, match="already has a lifecycle declared by"):
        registry.declare_population(
            "scratch.Blob",
            Lifecycle(kind=LifecycleKind.BOUNDED),
            source="apps.second.lifecycle",
        )


def test_the_same_population_declaration_twice_is_not_a_disagreement() -> None:
    """A module imported twice is not an error — `declare`'s precedent, kept."""
    registry = LifecycleRegistry()
    registry.declare_population("scratch.Blob", A_POPULATION, source="apps.first.lifecycle")
    registry.declare_population("scratch.Blob", A_POPULATION, source="apps.first.lifecycle")
    assert set(registry.populations()) == {"scratch.Blob"}


def test_the_live_tree_declares_at_least_one_population_through_the_hook() -> None:
    """The seam is discovered, not just declarable.

    Derived from the reader rather than naming `search.Document`: the day a
    second app declares one this keeps meaning what it says, and the day the
    discovery hook stops finding any of them it fails instead of measuring less.
    """
    declared = declared_populations()
    assert declared, "no app declares an off-ORM population; the seam is unexercised"
    for name, entry in declared.items():
        assert entry.declared_for == name
        assert "." in name
        assert population_sources()[name].endswith("lifecycle.py")


def test_no_declared_population_is_also_a_table() -> None:
    """The live-tree half of the refusal above: the two censuses never overlap."""
    labels = {model._meta.label for model in django_apps.get_models()}
    assert set(declared_populations()) & labels == set()


# --- the admin log, retained whole by declaration ---------------------------


def test_the_admin_log_is_declared_retained_with_the_owners_reason() -> None:
    """`admin.LogEntry` is kept whole by declaration, so erasure's silence on it is a decision."""
    from django.contrib.admin.models import LogEntry

    declared = lifecycle_of(LogEntry)

    assert declared is not None, "admin.LogEntry declares no lifecycle; erasure skips it by silence"
    assert declared.kind is LifecycleKind.UNBOUNDED
    assert declared.reason == "the owner retains every admin log (2026-10-08)"
    assert LogEntry not in undeclared_models()
    assert lifecycle_module._third_party_registry().sources()[LogEntry._meta.label] == (
        "apps/core/lifecycle.py"
    )
