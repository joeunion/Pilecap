"""The row half of the family: `archive_row`/`restore_row`, `require_live`,
`allowed_acts`, `resolve_subject`, and the `ArchivedOut` shape.

One planted archivable noun, built with its table inside the test's
transaction and joined to the kind registry through the registry's own cache
(`authz._kinds`) — a model built under `isolate_apps` is not in the global app
registry, and the vocabulary is derived from that registry. A planted
`archive_blockers.py` goes through the real discovery walk.
"""

from __future__ import annotations

import importlib.machinery
import sys
from collections.abc import Iterator
from types import ModuleType
from typing import Any

import pytest
from django.db import connection, models, transaction

from apps.accounts.models import User
from apps.core import authz, verbs
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.authz import reset_policies
from apps.core.exceptions import ArchiveBlocked, Archived, Blocker, NotFound, RestoreBlocked
from apps.core.models import Archivable, Organization, OrgScopedModel, Tenant
from apps.core.policies import may_archive
from apps.core.schemas import ArchivedOut
from apps.core.services import create_organization
from apps.core.tests.isolation import isolated_apps
from apps.core.time import now
from apps.core.verbs import allowed_acts, archive_row, require_live, resolve_subject, restore_row
from apps.example import policies as example_policies
from apps.example.models import Widget, WidgetEntry

pytestmark = pytest.mark.django_db

NOUN = "zzz_shelf"


@pytest.fixture(autouse=True)
def _vocabulary_restored() -> Iterator[None]:
    reset_policies()
    yield
    reset_policies()


@pytest.fixture
def shelf(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzShelf(OrgScopedModel, Archivable):
            label = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzShelf)
        monkeypatch.setitem(example_policies.POLICIES, f"{NOUN}.archive", may_archive)
        monkeypatch.setitem(example_policies.POLICIES, f"{NOUN}.restore", may_archive)
        reset_policies()
        kinds = dict(authz.kind_registry())
        kinds[NOUN] = ZzzShelf
        authz._kinds = kinds
        yield ZzzShelf
        reset_policies()


@pytest.fixture
def branches(
    tenant: Tenant, root_org: Organization, owner: User
) -> tuple[Organization, Organization]:
    acting = actor_for(user=owner, tenant=tenant, org=root_org)
    a = create_organization(tenant=tenant, parent=root_org, name="A", slug="a", actor=acting)
    b = create_organization(tenant=tenant, parent=root_org, name="B", slug="b", actor=acting)
    return a, b


def _plant_blockers(
    monkeypatch: pytest.MonkeyPatch, module: str, noun: str, *held: Blocker
) -> None:
    dotted = f"apps.example.{module}"
    planted = ModuleType(dotted)
    planted.__spec__ = importlib.machinery.ModuleSpec(dotted, loader=None)

    def holds_it(*, tenant: Any, obj: Any) -> tuple[Blocker, ...]:
        return tuple(held)

    planted.BLOCKERS = {noun: holds_it}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, dotted, planted)


HELD = Blocker(noun="widget", door="route:widget-list", label="Archive the widgets first")


# --- archive_row / restore_row / require_live --------------------------------


def test_archive_then_restore_round_trips_and_is_idempotent(
    shelf: Any, tenant: Tenant, root_org: Organization, admin_actor: Actor
) -> None:
    row = shelf.objects.create(tenant=tenant, organization=root_org, label="s")

    with transaction.atomic():
        archived, changed = archive_row(tenant=tenant, actor=admin_actor, row=row, noun=NOUN)
    assert changed is True
    assert archived.archived_at is not None
    assert archived.archived_by == admin_actor.user
    first = archived.archived_at

    with transaction.atomic():
        again, changed = archive_row(
            tenant=tenant, actor=system_actor(tenant=tenant), row=row, noun=NOUN
        )
    assert changed is False
    assert again.archived_at == first  # the FIRST press's date and archiver are kept
    assert again.archived_by == admin_actor.user

    with transaction.atomic():
        restored, changed = restore_row(tenant=tenant, actor=admin_actor, row=row, noun=NOUN)
    assert changed is True
    assert restored.archived_at is None and restored.archived_by is None
    with transaction.atomic():
        _, changed = restore_row(tenant=tenant, actor=admin_actor, row=row, noun=NOUN)
    assert changed is False


def test_a_live_child_blocks_the_archive_and_nothing_is_written(
    shelf: Any,
    tenant: Tenant,
    root_org: Organization,
    admin_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = shelf.objects.create(tenant=tenant, organization=root_org, label="s")
    _plant_blockers(monkeypatch, "archive_blockers", NOUN, HELD)

    with pytest.raises(ArchiveBlocked) as caught, transaction.atomic():
        archive_row(tenant=tenant, actor=admin_actor, row=row, noun=NOUN)
    assert caught.value.blocking == (HELD,)
    assert shelf.objects.including_archived().get(pk=row.pk).archived_at is None


def test_a_restore_blocker_blocks_the_restore(
    shelf: Any,
    tenant: Tenant,
    root_org: Organization,
    admin_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = shelf.objects.create(tenant=tenant, organization=root_org, label="s", archived_at=now())
    _plant_blockers(monkeypatch, "restore_blockers", NOUN, HELD)

    with pytest.raises(RestoreBlocked), transaction.atomic():
        restore_row(tenant=tenant, actor=admin_actor, row=row, noun=NOUN)
    assert shelf.objects.including_archived().get(pk=row.pk).archived_at is not None


def test_archive_row_refuses_a_model_that_did_not_declare(
    tenant: Tenant, admin_actor: Actor
) -> None:
    with pytest.raises(TypeError, match="has not declared `Archivable`"):
        # The worked ledger: append-only, so never archivable (D8), whichever
        # nouns adopt the mixin.
        archive_row(tenant=tenant, actor=admin_actor, row=WidgetEntry(), noun="widget_entry")


def test_require_live_refuses_an_archived_row_naming_its_restore(
    shelf: Any, tenant: Tenant, root_org: Organization
) -> None:
    require_live(shelf(tenant=tenant, organization=root_org, label="live"), noun=NOUN)
    require_live(WidgetEntry(), noun="widget_entry")  # not archivable, so always live
    with pytest.raises(Archived) as caught:
        require_live(
            shelf(tenant=tenant, organization=root_org, label="x", archived_at=now()), noun=NOUN
        )
    assert caught.value.remedies[0].destination == f"route:{NOUN}-restore"


# --- A1.7 · allowed_acts -------------------------------------------------------


def test_allowed_acts_answers_per_actor_and_per_state(
    shelf: Any,
    tenant: Tenant,
    root_org: Organization,
    member_actor: Actor,
    admin_actor: Actor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An act is offered only where its door is mounted: the planted noun's doors,
    # beside the live mount, for this test only.
    mounted = verbs.mounted_url_names() | {
        f"{NOUN}-{verb}" for verb in ("update", "delete", "archive", "restore")
    }
    monkeypatch.setattr(verbs, "mounted_url_names", lambda: mounted)
    live = shelf(tenant=tenant, organization=root_org, label="live")
    archived = shelf(tenant=tenant, organization=root_org, label="gone", archived_at=now())

    member_acts = allowed_acts(member_actor, live)
    assert "archive" not in member_acts
    admin_acts = allowed_acts(admin_actor, live)
    assert "archive" in admin_acts
    assert "restore" not in admin_acts
    assert "read" not in admin_acts and "create" not in admin_acts
    assert set(admin_acts) >= {"update", "delete", "archive"}

    assert allowed_acts(admin_actor, archived) == ("restore",)
    assert allowed_acts(member_actor, archived) == ()
    # The system actor is refused archive by the predicate that declared it.
    assert "archive" not in allowed_acts(system_actor(tenant=tenant, org=root_org), live)


# --- A1.8 · resolve_subject ------------------------------------------------------


def test_resolve_subject_answers_not_found_for_a_sibling_branch(
    tenant: Tenant, owner: User, branches: tuple[Organization, Organization]
) -> None:
    a, b = branches
    in_b = Widget.objects.create(tenant=tenant, organization=b, name="theirs", owner=owner)
    in_a = Widget.objects.create(tenant=tenant, organization=a, name="mine", owner=owner)
    wearing_a = actor_for(user=owner, tenant=tenant, org=a)

    with pytest.raises(NotFound):
        resolve_subject(wearing_a, "widget", in_b.pk)
    assert resolve_subject(wearing_a, "widget", in_a.pk) == in_a
    for missing in ("no-such-kind", "widget"):
        with pytest.raises(NotFound):
            resolve_subject(wearing_a, missing, "not-a-uuid")


def test_resolve_subject_includes_archived_rows_in_the_subtree(
    shelf: Any, tenant: Tenant, owner: User, branches: tuple[Organization, Organization]
) -> None:
    a, b = branches
    archived_in_a = shelf.objects.create(
        tenant=tenant, organization=a, label="a", archived_at=now()
    )
    archived_in_b = shelf.objects.create(
        tenant=tenant, organization=b, label="b", archived_at=now()
    )
    wearing_a = actor_for(user=owner, tenant=tenant, org=a)

    assert resolve_subject(wearing_a, NOUN, archived_in_a.pk) == archived_in_a
    with pytest.raises(NotFound):
        resolve_subject(wearing_a, NOUN, archived_in_b.pk)


# --- ArchivedOut ---------------------------------------------------------------


def test_archived_out_reads_the_two_columns(
    shelf: Any, tenant: Tenant, root_org: Organization, owner: User
) -> None:
    class ZzzShelfOut(ArchivedOut):
        label: str

    live = shelf(tenant=tenant, organization=root_org, label="live")
    gone = shelf(
        tenant=tenant, organization=root_org, label="gone", archived_at=now(), archived_by=owner
    )

    assert ZzzShelfOut.model_validate(live, from_attributes=True).model_dump() == {
        "archived_at": None,
        "archived_by": None,
        "label": "live",
    }
    dumped = ZzzShelfOut.model_validate(gone, from_attributes=True).model_dump(mode="json")
    assert dumped["archived_by"] == {"id": str(owner.pk), "name": None}
    assert dumped["archived_at"] is not None
