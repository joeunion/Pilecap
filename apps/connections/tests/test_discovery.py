"""Registration by discovery, and the sibling this app refuses to import.

Two properties, and both of them are about a file that was *not* edited:

* dropping this app under `apps/` installed it, mounted its router, published
  its event names and registered its policies — `config/` and `pyproject.toml`
  stay untouched;
* `apps/events` sits *beside* this app in the layer contract, so the hand-off is
  a runtime lookup and never an import — in this app's own tests as much as in
  its source. The spine has landed, so the hand-off is now asserted at the far
  end: an `Event` row, in the right tenant, with the right name.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.urls import reverse

from apps.connections.events import WEBHOOK_RECEIVED
from apps.connections.models import Connection, InboundWebhook
from apps.connections.services import _accepts, _events_callable, record_inbound_webhook
from apps.core.actor import system_actor
from apps.core.models import Tenant
from apps.core.tests.tree_census import source_tree

pytestmark = pytest.mark.django_db

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "apps" / "connections"


def _events(tenant: Tenant) -> Any:
    """This tenant's rows in the event spine, through the registry.

    `django_apps.get_model` rather than `from apps.events.models import Event`:
    the app is a sibling this app refuses to import, and
    `test_nothing_in_this_app_imports_apps_events` reads every file under
    `apps/connections` — this one included.
    """
    return django_apps.get_model("events", "Event").objects.for_tenant(tenant)


def test_the_app_installed_itself() -> None:
    config = django_apps.get_app_config("connections")
    assert config.name == "apps.connections"
    assert getattr(config, "depends_on", ()) == ("core", "accounts", "events")


def test_the_router_was_mounted_under_the_app_label() -> None:
    """No `PREFIX` in `api.py`: the label already says what the resource is."""
    assert reverse("api:connection-list") == "/api/v1/connections/"


def test_the_event_names_are_declared_in_one_file() -> None:
    from apps.connections import events

    declared = {
        value
        for name, value in vars(events).items()
        if name.isupper() and isinstance(value, str) and not name.startswith("_")
    }
    assert declared == {
        "connections.connection.created",
        "connections.connection.credentials_updated",
        "connections.connection.revoked",
        "connections.webhook.received",
    }
    for name in declared:
        app, noun, verb = name.split(".")
        assert app == "connections"
        assert verb.endswith(("ed", "d")), f"{name} is not past tense"


def test_the_policies_are_discovered_by_authz() -> None:
    from apps.core.authz import policies, reset_policies

    reset_policies()
    found = policies()
    assert {"connection.create", "connection.update", "connection.revoke"} <= set(found)


def test_both_models_are_tenant_scoped() -> None:
    from apps.core.models import TenantScopedModel

    assert issubclass(Connection, TenantScopedModel)
    assert issubclass(InboundWebhook, TenantScopedModel)


def test_nothing_in_this_app_imports_apps_events() -> None:
    """The layer contract makes them siblings; the coupling is a runtime lookup.

    Read with `ast` rather than `grep`, so a function-local import — which
    `import-linter` would catch and a careless reviewer would not — fails here
    too.
    """
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        tree = source_tree(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{path.name}:{node.lineno}"
                    for alias in node.names
                    if alias.name.startswith("apps.events")
                ]
            elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("apps.events"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


def test_the_hand_off_is_absent_rather_than_broken_without_the_events_app() -> None:
    """Whichever tree this runs in, the lookup answers instead of raising."""
    found = _events_callable("services", "emit")
    if django_apps.is_installed("apps.events"):
        assert callable(found)
    else:
        assert found is None
    assert _events_callable("services", "no_such_function_anywhere") is None


def test_a_verified_delivery_reaches_the_event_spine(
    tenant: Tenant, other_tenant: Tenant, connection: Connection
) -> None:
    """The hand-off, asserted at the far end rather than at this app's border.

    `handed_off_to` is this app's own note to itself; the property is that a row
    exists in the spine, named for what arrived and owned by the tenant it
    arrived for. The `Event` model is reached through the app registry, because
    the sibling this app refuses to import is refused in its tests too.
    """
    received = record_inbound_webhook(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=connection,
        body="{}",
        headers={},
        event_type="thing.happened",
    )

    assert received.status == InboundWebhook.Status.HANDED_OFF
    assert received.handed_off_to == "events.emit"
    assert received.handed_off_at is not None

    event = _events(tenant).get(name=WEBHOOK_RECEIVED)
    assert event.tenant_id == tenant.pk
    assert event.payload["event_type"] == "thing.happened"
    assert event.payload["connection_id"] == str(connection.pk)
    # The sibling that cannot pass vacuously: a delivery for one tenant does not
    # become an event in another.
    assert not _events(other_tenant).exists()


def test_the_spines_own_receiver_is_preferred_when_its_signature_fits() -> None:
    """Which of the two interfaces takes the delivery is *checked*, not attempted.

    `_hand_off` tries `apps.events.receivers.verify_and_store` first and falls
    to `emit`. Against the spine as it landed the first one does not bind — that
    receiver is a *door-side* helper that verifies a signature and stores the
    body, and by the time this app calls, both have already happened here. So
    the fall-through is the live path, and it is a decision rather than a
    `TypeError` swallowed at the call site.

    This is the guard that makes that safe: it says yes to a signature that
    fits and no to the one that does not.

    **Re-pointed at the narrowed receiver** (ADR connections-1, rung W6). It
    takes `source=` — one row carrying both the tenant and the secret — where it
    used to take `secret` and `tenant` as a loose pair a caller had to keep
    matched. What the assertions say is unchanged in substance: this app's
    probe still does not bind, and the receiver's real signature still does.
    """
    receiver = _events_callable("receivers", "verify_and_store")
    assert receiver is not None, "the spine still exposes a receiver"
    # What `_hand_off` actually offers. Still not a fit, still on purpose.
    assert not _accepts(receiver, source=None, event_type="", body="", headers={}, verified=True)
    # The receiver's own shape: raw bytes, an unchecked signature, and the row.
    assert _accepts(receiver, request_body=b"body", signature="sig", source=None, name="x")
    # And the loose pair is gone rather than merely unused.
    assert not _accepts(
        receiver, request_body=b"body", signature="sig", secret="s", tenant=None, name="x"
    )
