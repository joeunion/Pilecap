"""`core.bulk.run_bulk`: one verb over a selection, honest about each item.

The noun and its per-item `@service` are planted HERE (`isolated_apps` plus a
table inside the test's transaction), so core proves the batch contract against
the shape a product writes: every item its own service call, its own
transaction, its own audit row.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from django.db import connection, models

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.audit import AuditEntry
from apps.core.bulk import MAX_ITEMS, run_bulk
from apps.core.exceptions import Conflict, Invalid, NotFound
from apps.core.models import Archivable, Organization, OrgScopedModel, Tenant
from apps.core.service import service
from apps.core.tests.isolation import isolated_apps
from apps.core.verbs import ROADS, archive_row


@pytest.fixture
def task_model(db: None) -> Iterator[Any]:
    with isolated_apps("apps.core", "apps.accounts") as registry:
        assert registry is not None
        registry.register_model("accounts", User)

        class ZzzTask(OrgScopedModel, Archivable):
            """A noun archived in batches."""

            name = models.CharField(max_length=50)

            class Meta:
                app_label = "core"

        with connection.schema_editor() as editor:
            editor.create_model(ZzzTask)
        yield ZzzTask


@service
def zzz_archive_task(*, tenant: Tenant, actor: Actor, task: Any) -> Any:
    """The per-item service a noun's bulk route calls — refusing one row on purpose."""
    if task.name == "held":
        raise Conflict("This task is held.")
    row, _changed = archive_row(tenant=tenant, actor=actor, row=task, noun="zzz_task")
    return row


def _run(task_model: Any, tenant: Tenant, actor: Actor, ids: list[Any]) -> Any:
    def resolve(pk: Any) -> Any:
        found = task_model.objects.for_tenant(tenant).including_archived().filter(pk=pk).first()
        if found is None:
            raise NotFound()
        return found

    return run_bulk(
        tenant=tenant,
        actor=actor,
        verb="archive",
        ids=ids,
        resolve=resolve,
        act=lambda row: zzz_archive_task(tenant=tenant, actor=actor, task=row),
        is_settled=ROADS["archive"].settled["archive"],
    )


def test_a_partial_batch_answers_each_item_in_order(
    task_model: Any, tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    rows = [
        task_model.objects.create(tenant=tenant, organization=root_org, name=name)
        for name in ("first", "held", "third")
    ]

    report = _run(task_model, tenant, owner_actor, [row.pk for row in rows])

    assert [r.outcome for r in report.results] == ["done", "refused", "done"]
    assert [r.id for r in report.results] == [row.pk for row in rows]
    refusal = report.results[1].refusal
    assert refusal is not None
    assert refusal["code"] == "conflict" and refusal["detail"] == "This task is held."
    assert refusal["remedies"]
    assert (report.done, report.unchanged, report.refused) == (2, 0, 1)
    # The first and third are committed; the second is untouched.
    states = {
        row.name: row.archived_at is not None
        for row in task_model.objects.for_tenant(tenant).including_archived()
    }
    assert states == {"first": True, "held": False, "third": True}
    # The refused item left its own error row, under its own service.
    errors = AuditEntry.objects.for_tenant(tenant).filter(
        action="core.zzz_archive_task", outcome="error"
    )
    assert errors.count() == 1
    assert errors.get().error_code == "conflict"


def test_a_settled_row_is_unchanged_and_a_retry_converges(
    task_model: Any, tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    rows = [
        task_model.objects.create(tenant=tenant, organization=root_org, name=name)
        for name in ("one", "two")
    ]
    first = _run(task_model, tenant, owner_actor, [rows[0].pk])
    assert [r.outcome for r in first.results] == ["done"]

    again = _run(task_model, tenant, owner_actor, [row.pk for row in rows])
    assert [r.outcome for r in again.results] == ["unchanged", "done"]


def test_an_unreachable_id_is_not_found_and_the_rest_still_run(
    task_model: Any, tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    row = task_model.objects.create(tenant=tenant, organization=root_org, name="real")
    report = _run(task_model, tenant, owner_actor, [uuid4(), row.pk])
    assert [r.outcome for r in report.results] == ["refused", "done"]
    assert report.results[0].refusal is not None
    assert report.results[0].refusal["code"] == "not_found"


@pytest.mark.parametrize(
    "ids",
    [
        pytest.param([uuid4() for _ in range(MAX_ITEMS + 1)], id="201"),
        pytest.param([], id="none"),
    ],
)
def test_the_envelope_is_invalid_naming_ids(
    task_model: Any, tenant: Tenant, owner_actor: Actor, ids: list[Any]
) -> None:
    with pytest.raises(Invalid) as caught:
        _run(task_model, tenant, owner_actor, ids)
    assert "ids" in caught.value.errors


def test_a_repeated_id_is_invalid_naming_ids(
    task_model: Any, tenant: Tenant, owner_actor: Actor
) -> None:
    same = uuid4()
    with pytest.raises(Invalid) as caught:
        _run(task_model, tenant, owner_actor, [same, same])
    assert "ids" in caught.value.errors


def test_the_bulk_verb_derives_its_plural_twin() -> None:
    from apps.core.checks import _VERB_TOOLS

    assert _VERB_TOOLS["bulk"] == ("bulk_{noun}s",)
    assert ROADS["bulk"].url_names("widget") == ("widget-bulk",)
    assert ROADS["bulk"].grants == ()
