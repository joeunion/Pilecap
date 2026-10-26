# census: cross-app population=apps/**/*.py reads every app's services and door modules
"""One audit row per door call (ADR core-29): the outermost witnessing `@service` writes it."""

from __future__ import annotations

import ast
import importlib
from collections.abc import Iterable
from pathlib import Path

import pytest
from django.conf import settings
from django.test import Client

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.audit import AuditEntry
from apps.core.models import Tenant
from apps.core.tests.tree_census import source_tree

pytestmark = pytest.mark.django_db(transaction=True)


def test_one_archive_through_the_rest_door_writes_one_audit_row(
    api: Client, tenant: Tenant, owner: User, owner_actor: Actor
) -> None:
    """`archive_widget` over REST emits, records, enqueues and records a run; one row says so."""
    from apps.example.services import create_widget

    widget = create_widget(tenant=tenant, actor=owner_actor, name="Spares")
    before = set(AuditEntry.objects.for_tenant(tenant).values_list("pk", flat=True))
    api.force_login(owner)

    response = api.post(f"/api/v1/widgets/{widget.pk}/archive/", headers={"x-tenant": tenant.slug})

    assert response.status_code == 200, response.content
    written = list(
        AuditEntry.objects.for_tenant(tenant)
        .exclude(pk__in=before)
        .values_list("action", "door", "actor_user_id")
    )
    assert written == [("example.archive_widget", "rest", owner.pk)], written


#: The door modules rule 42 reads (`quality/checks/rule_42.py::DOOR_GLOBS`), by the same names.
DOOR_GLOBS = (
    "apps/*/api.py",
    "apps/*/api/*.py",
    "apps/*/mcp.py",
    "apps/*/consumers.py",
    "apps/*/activities.py",
    "apps/*/receivers.py",
    "apps/*/management/commands/*.py",
)


def unwitnessed_services() -> dict[str, str]:
    """`{name: module}` for every installed app's `@service(witness=False)`."""
    from django.apps import apps as django_apps

    found: dict[str, str] = {}
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        try:
            module = importlib.import_module(f"{config.name}.services")
        except ModuleNotFoundError:
            continue
        for name, value in vars(module).items():
            if getattr(value, "__witness__", True) is False and value.__module__ == module.__name__:
                found[name] = module.__name__
    return found


def direct_door_calls(root: Path, names: Iterable[str]) -> list[str]:
    """`<path>:<line> <name>` for every call by one of `names` in a door module under `root`."""
    wanted = set(names)
    hits: list[str] = []
    for pattern in DOOR_GLOBS:
        for path in sorted(root.glob(pattern)):
            for node in ast.walk(source_tree(path)):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if called in wanted:
                    hits.append(f"{path.relative_to(root)}:{node.lineno} {called}")
    return hits


def test_the_four_platform_internal_services_are_the_declared_population() -> None:
    """`emit`, `record_event`, `enqueue_dispatch` and `record_run` — ADR core-29's four."""
    assert set(unwitnessed_services()) == {"emit", "record_event", "enqueue_dispatch", "record_run"}


#: The doors that call an unwitnessed service directly: there it is the door call's one row.
DOOR_CALLED = {
    "apps/events/activities.py enqueue_dispatch",
    "apps/events/receivers.py record_event",
    "apps/events/receivers.py enqueue_dispatch",
    "apps/events/management/commands/replay_events.py enqueue_dispatch",
}


def test_the_doors_that_call_an_unwitnessed_service_directly_are_the_known_four() -> None:
    """A new direct door call is named here: it is where that service writes the door's row."""
    root = Path(str(settings.BASE_DIR))
    sites = {
        f"{hit.split(':')[0]} {hit.split()[-1]}"
        for hit in direct_door_calls(root, unwitnessed_services())
    }
    assert sites == DOOR_CALLED


def test_an_unwitnessed_service_writes_its_row_alone_and_none_under_a_witness(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """`record_event` called by a door is that call's row; under `create_widget` it is not."""
    from apps.core.services import root_organization
    from apps.events.services import record_event
    from apps.example.events import WIDGET_CREATED

    before = AuditEntry.objects.for_tenant(tenant).filter(action="events.record_event").count()
    record_event(
        name=WIDGET_CREATED,
        tenant=tenant,
        payload={"organization_id": str(root_organization(tenant=tenant).pk)},
        actor=owner_actor,
    )
    alone = AuditEntry.objects.for_tenant(tenant).filter(action="events.record_event").count()
    assert alone == before + 1

    from apps.example.services import create_widget

    create_widget(tenant=tenant, actor=owner_actor, name="Nested")
    assert (
        AuditEntry.objects.for_tenant(tenant).filter(action="events.record_event").count() == alone
    )


def test_a_door_calling_an_unwitnessed_service_is_named(tmp_path: Path) -> None:
    """The negative: a scratch `api.py` that calls `record_event` is named by file and line."""
    door = tmp_path / "apps" / "zzz_probe" / "api.py"
    door.parent.mkdir(parents=True)
    door.write_text(
        "from apps.events.services import record_event\n\n\ndef post():\n    record_event()\n"
    )
    assert direct_door_calls(tmp_path, ["record_event"]) == ["apps/zzz_probe/api.py:5 record_event"]
