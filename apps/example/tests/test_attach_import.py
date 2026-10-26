"""The widget takes notes, tags and files, and a file of widgets imports."""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from temporalio.client import Client as TemporalClient
from temporalio.testing import WorkflowEnvironment

from apps.example.models import Widget
from apps.example.services import create_widget
from pilecap import Actor
from pilecap.accounts import User
from pilecap.imports import ImportSettled, apply_import, create_import
from pilecap.tenancy import Organization, Tenant
from pilecap.testing import (
    Import,
    ImportRow,
    actor_for,
    attach_interceptors,
    build_worker,
    memory_store,
    replace_workflow_client,
    run_db,
    stored_csv,
    system_actor,
)
from pilecap.testing import attach_note as note_one
from pilecap.testing import attach_tag as tag_one
from pilecap.workflows import workflow_id

__all__ = ["memory_store"]  # the imports app's object-store double, used as a fixture below

WIDGETS = "/api/v1/widgets/"


def body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


# --- attachments -----------------------------------------------------------------


@pytest.mark.django_db
def test_the_detail_answers_the_tags_and_the_notes_app_answers_for_the_widget(
    api: Client, tenant: Tenant, root_org: Organization, owner: User, owner_actor: Actor
) -> None:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Tagged")
    other = create_widget(tenant=tenant, actor=owner_actor, name="Bare")
    tag_one(tenant=tenant, actor=owner_actor, subject=widget)
    note_one(tenant=tenant, actor=owner_actor, subject=widget)
    api.force_login(owner)

    detail = api.get(f"{WIDGETS}{widget.pk}/")
    bare = api.get(f"{WIDGETS}{other.pk}/")
    notes = api.get("/api/v1/djb_notes/", {"subject": f"widget:{widget.pk}"})

    assert detail.status_code == 200, detail.content
    assert [tag["name"] for tag in body(detail)["tags"]] == ["Specimen"]
    assert body(bare)["tags"] == []
    assert notes.status_code == 200, notes.content
    assert len(body(notes)["items"]) == 1
    # A list's row is the row; the words are the record's.
    listed = api.get(WIDGETS)
    assert all("tags" not in row for row in body(listed)["items"])


def test_the_tree_declares_the_three_attachments() -> None:
    """The tree declares the three attachments the owners' tests read."""
    assert Widget.attachments == ("notes", "tags", "files")


# --- import, on a real worker -----------------------------------------------------

THREE_ROWS = "external_ref,name,notes\r\nCRM-1,Alpha,a\r\nCRM-2,Bravo,b\r\nCRM-3,Charlie,c\r\n"
# The same three rows with other line endings: other bytes, so a new run.
THE_SAME_ROWS_AGAIN = THREE_ROWS.replace("\r\n", "\n")


def _run_id(tenant: Tenant, run: Import, phase: str) -> str:
    return workflow_id(tenant=tenant, app="djb_imports", noun="import", key=f"{run.pk}-{phase}")


async def _local_client(
    env: WorkflowEnvironment, monkeypatch: pytest.MonkeyPatch
) -> TemporalClient:
    """Point every client at the test server, including the on-commit start."""
    target = env.client.service_client.config.target_host
    namespace = env.client.namespace

    async def connect() -> TemporalClient:
        return attach_interceptors(await TemporalClient.connect(target, namespace=namespace))

    replace_workflow_client(monkeypatch, connect)
    return attach_interceptors(env.client)


async def _import(client: TemporalClient, tenant: Tenant, actor: Actor, text: str) -> ImportSettled:
    """Stage one file, wait for its preview, apply it, wait for the apply."""
    version = await run_db(stored_csv, actor, text)
    run, created = await run_db(
        create_import, tenant=tenant, actor=actor, kind="widget", file_version=version
    )
    assert created
    checked: ImportSettled = await client.get_workflow_handle(
        _run_id(tenant, run, "check"), result_type=ImportSettled
    ).result()
    assert checked.status == "previewed", checked
    await run_db(apply_import, tenant=tenant, actor=actor, import_=run)
    applied: ImportSettled = await client.get_workflow_handle(
        _run_id(tenant, run, "apply"), result_type=ImportSettled
    ).result()
    return applied


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_three_row_file_applied_twice_is_three_widgets_then_three_unchanged(
    memory_store: dict[str, bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    def world() -> tuple[Tenant, Actor]:
        from pilecap.accounts import create_user
        from pilecap.tenancy import Membership, add_membership, create_tenant, root_organization

        tenant = create_tenant(name="Acme", slug="acme", actor=system_actor())
        owner = create_user(email="importer@acme.com", password="a" * 24)
        add_membership(
            user=owner,
            tenant=tenant,
            is_default=True,
            role=Membership.Role.OWNER,
            actor=system_actor(tenant=tenant),
        )
        return tenant, actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))

    tenant, actor = await run_db(world)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = await _local_client(env, monkeypatch)
        async with build_worker(client):
            first = await _import(client, tenant, actor, THREE_ROWS)
            second = await _import(client, tenant, actor, THE_SAME_ROWS_AGAIN)

    assert first.status == "imported", first
    assert first.counts == {"create": 3, "update": 0, "unchanged": 0, "refused": 0}
    assert second.status == "imported", second
    assert second.counts == {"create": 0, "update": 0, "unchanged": 3, "refused": 0}
    widgets = await run_db(
        lambda: sorted(Widget.objects.filter(tenant=tenant).values_list("external_ref", "name"))
    )
    assert widgets == [("CRM-1", "Alpha"), ("CRM-2", "Bravo"), ("CRM-3", "Charlie")]
    outcomes = await run_db(
        lambda: sorted(
            ImportRow.objects.filter(tenant=tenant).values_list("run__created_at", "outcome")
        )
    )
    assert [outcome for _, outcome in outcomes] == ["created"] * 3 + ["unchanged"] * 3
