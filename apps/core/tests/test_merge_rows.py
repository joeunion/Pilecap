"""`core.verbs.merge_rows`: two rows become one, and the loser survives as a tombstone.

The nouns are planted here (`isolated_apps` + a `schema_editor` table inside the
test's transaction), and so are the repointers and the blockers: the hook walk
is narrowed to a planted population for the length of a test, so core proves
its own seam — every `"*"` and `<noun>` repointer called, the chain compressed,
the loser archived naming its survivor — without depending on which attach
owners a deployment installed. The real repointers answer to
`test_repointer_conformance.py`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from django.db import connection, models, transaction

from apps.accounts.models import User
from apps.core import verbs
from apps.core.exceptions import (
    CODE_STATUSES,
    Archived,
    Blocker,
    Invalid,
    MergeBlocked,
    Merged,
    wire_refusal,
)
from apps.core.models import Archivable, Mergeable, Organization, OrgScopedModel, Tenant
from apps.core.tests.isolation import isolated_apps
from apps.core.verbs import MergeOutcome, Repointed, Repointer, merge_counts, merge_rows

NOUN = "zzz_merge_crate"


@dataclass
class Calls:
    """What the planted repointers were asked, in order."""

    counted: list[tuple[str, Any]] = field(default_factory=list)
    repointed: list[tuple[str, Any, Any]] = field(default_factory=list)


@pytest.fixture
def crate(db: None) -> Iterator[Any]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzMergeCrate(OrgScopedModel, Archivable, Mergeable):
            """A noun two rows of which can become one."""

            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzMergeCrate)
        yield ZzzMergeCrate


def _planted_hook(
    calls: Calls, *, blockers: dict[str, Callable[..., tuple[Blocker, ...]]] | None = None
) -> Callable[[str], list[tuple[Any, dict[Any, Any]]]]:
    def repointer(title: str, left: int) -> Repointer:
        def count(*, tenant: Tenant, loser: Any) -> int:
            calls.counted.append((title, loser.pk))
            return left

        def repoint(*, tenant: Tenant, actor: Any, loser: Any, survivor: Any) -> int:
            calls.repointed.append((title, loser.pk, survivor.pk))
            return left

        return Repointer(title=title, count=count, repoint=repoint)

    planted: dict[str, list[tuple[Any, dict[Any, Any]]]] = {
        "merge_repointers": [
            (SimpleNamespace(label="zzz_any"), {"*": repointer("Stickers", 3)}),
            (SimpleNamespace(label="zzz_own"), {NOUN: repointer("Labels", 2)}),
        ],
        "merge_blockers": [(SimpleNamespace(label="zzz_block"), blockers or {})],
    }

    def hook(module: str) -> list[tuple[Any, dict[Any, Any]]]:
        return planted.get(module, [])

    return hook


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    recorded = Calls()
    monkeypatch.setattr(verbs, "hook", _planted_hook(recorded))
    return recorded


def _row(model: Any, tenant: Tenant, org: Organization, name: str, **extra: Any) -> Any:
    return model.objects.create(tenant=tenant, organization=org, name=name, **extra)


def _merge(tenant: Tenant, actor: Any, loser: Any, into: Any) -> MergeOutcome:
    with transaction.atomic():
        return merge_rows(tenant=tenant, actor=actor, loser=loser, into=into, noun=NOUN)


@isolated_apps("apps.core", "apps.accounts")
def test_mergeable_without_archivable_is_refused_at_class_definition() -> None:
    with pytest.raises(TypeError) as caught:

        class ZzzLoose(OrgScopedModel, Mergeable):
            class Meta:
                app_label = "core"

    assert "declares `Mergeable` without `Archivable`" in str(caught.value)


def test_the_merge_calls_every_repointer_and_leaves_a_tombstone(
    crate: Any, calls: Calls, tenant: Tenant, root_org: Organization, owner_actor: Any
) -> None:
    loser = _row(crate, tenant, root_org, "dup")
    survivor = _row(crate, tenant, root_org, "keep")
    before = loser.updated_at

    outcome = _merge(tenant, owner_actor, loser, survivor)

    assert outcome.changed is True
    # Every "*" repointer, then the noun's own, each asked to move loser → survivor.
    assert calls.repointed == [
        ("Stickers", loser.pk, survivor.pk),
        ("Labels", loser.pk, survivor.pk),
    ]
    # The event's `repoints` come from the APPLY's answers.
    assert outcome.repoints == (Repointed("Stickers", 3), Repointed("Labels", 2))
    assert calls.counted == []
    gone = crate.objects.for_tenant(tenant).including_archived().get(pk=loser.pk)
    assert gone.merged_into_id == survivor.pk
    assert gone.archived_at is not None
    assert gone.archived_by_id == owner_actor.user.pk
    assert gone.updated_at > before
    # The survivor is untouched and still in the book.
    assert crate.objects.for_tenant(tenant).filter(pk=survivor.pk).exists()


def test_the_dry_run_counts_without_writing(
    crate: Any, calls: Calls, tenant: Tenant, root_org: Organization
) -> None:
    loser = _row(crate, tenant, root_org, "dup")
    assert merge_counts(tenant=tenant, loser=loser, noun=NOUN) == (
        Repointed("Stickers", 3),
        Repointed("Labels", 2),
    )
    assert calls.repointed == []


def test_the_same_pair_again_is_unchanged(
    crate: Any, calls: Calls, tenant: Tenant, root_org: Organization, owner_actor: Any
) -> None:
    loser = _row(crate, tenant, root_org, "dup")
    survivor = _row(crate, tenant, root_org, "keep")
    _merge(tenant, owner_actor, loser, survivor)
    calls.repointed.clear()

    again = _merge(tenant, owner_actor, loser, survivor)

    assert again.changed is False
    assert again.repoints == ()
    assert calls.repointed == []


def test_a_prior_loser_of_the_loser_is_compressed_to_the_survivor(
    crate: Any, calls: Calls, tenant: Tenant, root_org: Organization, owner_actor: Any
) -> None:
    first = _row(crate, tenant, root_org, "first")
    middle = _row(crate, tenant, root_org, "middle")
    last = _row(crate, tenant, root_org, "last")
    _merge(tenant, owner_actor, first, middle)

    _merge(tenant, owner_actor, middle, last)

    every = crate.objects.for_tenant(tenant).including_archived()
    assert every.get(pk=first.pk).merged_into_id == last.pk
    assert every.get(pk=middle.pk).merged_into_id == last.pk
    assert sorted(map(str, crate.lineage(last))) == sorted(map(str, (last.pk, first.pk, middle.pk)))


def test_the_refusals_and_what_they_leave_alone(
    crate: Any, calls: Calls, tenant: Tenant, root_org: Organization, owner_actor: Any
) -> None:
    row = _row(crate, tenant, root_org, "one")
    other = _row(crate, tenant, root_org, "two")
    third = _row(crate, tenant, root_org, "three")

    with pytest.raises(Invalid) as same:
        _merge(tenant, owner_actor, row, row)
    assert "into" in same.value.errors

    archived = _row(crate, tenant, root_org, "shelved", archived_at="2026-01-01T00:00:00Z")
    with pytest.raises(Archived):
        _merge(tenant, owner_actor, row, archived)

    _merge(tenant, owner_actor, row, other)
    with pytest.raises(Merged) as elsewhere:
        _merge(tenant, owner_actor, row, third)
    assert wire_refusal(elsewhere.value)["merged_into"] == str(other.pk)
    assert calls.repointed == [
        ("Stickers", row.pk, other.pk),
        ("Labels", row.pk, other.pk),
    ]


def test_a_merge_blocker_refuses_with_nothing_repointed(
    crate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Any,
) -> None:
    recorded = Calls()

    def held(*, tenant: Tenant, obj: Any) -> tuple[Blocker, ...]:
        return (Blocker(noun="zzz_ledger", door="route:zzz_ledger-list", label="Settle it"),)

    monkeypatch.setattr(verbs, "hook", _planted_hook(recorded, blockers={NOUN: held}))
    loser = _row(crate, tenant, root_org, "dup")
    survivor = _row(crate, tenant, root_org, "keep")

    with pytest.raises(MergeBlocked) as caught:
        _merge(tenant, owner_actor, loser, survivor)

    assert wire_refusal(caught.value)["code"] == "merge_blocked"
    assert recorded.repointed == []
    fresh = crate.objects.for_tenant(tenant).get(pk=loser.pk)
    assert fresh.merged_into_id is None and fresh.archived_at is None


def test_merged_is_a_registered_409_and_a_write_on_the_loser_names_the_survivor(
    crate: Any, calls: Calls, tenant: Tenant, root_org: Organization, owner_actor: Any
) -> None:
    assert CODE_STATUSES["merged"] == 409
    assert CODE_STATUSES["merge_blocked"] == 409
    loser = _row(crate, tenant, root_org, "dup")
    survivor = _row(crate, tenant, root_org, "keep")
    gone = _merge(tenant, owner_actor, loser, survivor).loser

    with pytest.raises(Merged) as caught:
        verbs.require_live(gone, noun=NOUN)
    body = wire_refusal(caught.value)
    assert body["code"] == "merged"
    assert body["merged_into"] == str(survivor.pk)
    assert body["remedies"][0]["destination"] == f"route:{NOUN}-detail"

    # A restore is not the way back: there is no unmerge.
    with pytest.raises(Merged), transaction.atomic():
        verbs.restore_row(tenant=tenant, actor=owner_actor, row=gone, noun=NOUN)


def test_a_mergeable_that_takes_no_attachment_merges_with_every_real_repointer_at_zero(
    crate: Any,
    monkeypatch: pytest.MonkeyPatch,
    tenant: Tenant,
    root_org: Organization,
    owner_actor: Any,
) -> None:
    """The REAL hook walk, not a planted one: a noun without `attachments` merges.

    Every `"*"` owner the tree installs (notes, files, tags) answers for every
    noun, and a mergeable noun need not take any of their kinds — so each one's
    repointer is a no-op counted 0 there, never a refusal that stops the merge.
    """
    from apps.core import authz

    kinds = dict(authz.kind_registry())
    kind = authz.kind_of(crate)
    assert kind is not None
    kinds[kind] = crate
    monkeypatch.setattr(authz, "_kinds", kinds)
    assert not getattr(crate, "attachments", ())
    loser = _row(crate, tenant, root_org, "dup")
    survivor = _row(crate, tenant, root_org, "keep")
    owners = [label for label, _ in verbs.repointers_for(NOUN)]
    assert {"notes", "files", "tags"} <= set(owners), owners

    counted = merge_counts(tenant=tenant, loser=loser, noun=NOUN)
    outcome = _merge(tenant, owner_actor, loser, survivor)

    assert outcome.changed is True
    assert [r.left for r in counted] == [0] * len(owners)
    assert [r.left for r in outcome.repoints] == [0] * len(owners)
    gone = crate.objects.for_tenant(tenant).including_archived().get(pk=loser.pk)
    assert gone.merged_into_id == survivor.pk
