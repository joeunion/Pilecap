# census: cross-app population=apps/connections/**/*.py for a sideways import of apps.events
"""Registration by discovery, and the sibling this app refuses to import.

Two properties, and both of them are about a file that was *not* edited:

* dropping this app under `apps/` installed it, mounted its router, published
  its event names and registered its policies — `config/` and `pyproject.toml`
  stay untouched;
* `apps/events` sits *beside* this app in the layer contract, so the hand-off
  and the inbound verifier are `core.bridge` names and never an import — in
  this app's own tests as much as in its source. The spine has landed, so the
  hand-off is asserted at the far end: an `Event` row, in the right tenant, with
  the right name.
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
from apps.connections.services import _accepts, record_inbound_webhook
from apps.core import bridge
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
        "connections.connection.signature_scheme_updated",
        "connections.webhook.received",
    }
    for name in declared:
        app, noun, verb = name.split(".")
        assert app == "connections"
        assert verb.endswith(("ed", "d")), f"{name} is not past tense"


def test_the_apps_keys_are_discovered_by_authz() -> None:
    """The three keys are in the vocabulary. **They carry no predicate.**

    They used to be in `policies()`, and the Phase-W sweep took them out: each
    one asked "is this person an owner or an admin of the tenant", which is the
    DATA half's question, and a predicate restating it was a second opinion
    about rows the tenant owns (house rule 54 (c)). What has to stay true is
    that the words still exist and still answer, and that is what this asserts —
    the `vocabulary()`, not the predicate table.

    The refusal sentences are the other half of "still answers", and
    `refusal_sentence` is derived from `ACTION_PROSE`, so a key that lost its
    prose would quietly change the words a refused caller reads.
    """
    from apps.connections import policies as connection_policies
    from apps.core.authz import policies, refusal_sentence, reset_policies, vocabulary

    reset_policies()
    keys = {"connection.create", "connection.update", "connection.revoke"}
    assert keys <= set(vocabulary())
    for key in sorted(keys):
        assert refusal_sentence(key) == connection_policies.ACTION_PROSE[key]
    # And the predicate table is empty for this app, which is the sweep itself.
    assert not {key for key in policies() if key.startswith("connection.")}


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


REACHED = (
    bridge.EMIT,
    bridge.VERIFY_AND_STORE,
    bridge.SIGNATURE_MATCHES,
    bridge.SIGNATURE_V2_MATCHES,
    bridge.SIGNATURE_V2_TOLERANCE,
)


def test_every_name_this_app_reaches_is_one_the_events_app_filled() -> None:
    """The five bridge names are registered, and each is the events app's own function.

    Named by `__module__` rather than by importing the functions — this app does
    not import `apps.events`, in its tests either.
    """
    registered = bridge.registered()
    for name in REACHED:
        assert name in registered, f"{name} is not registered"
        assert registered[name].__module__.startswith("apps.events."), name
    assert bridge.get(bridge.VERIFY_AND_STORE).__module__ == "apps.events.receivers"


def test_an_unregistered_name_is_a_refusal_in_production_never_a_fall_through(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`get`, not `find`: strict mode raises where the reach used to answer `None`.

    The runtime lookup this replaced answered `None` for an events app that was
    not installed, and the door fell through to a verifier of its own — the fail
    open shape that made two verifiers. Through the bridge, a production process
    with nothing registered refuses at the first call and says which name.
    """
    settings.BRIDGE_STRICT = True
    monkeypatch.setattr(bridge, "_registry", {})
    for name in REACHED:
        with pytest.raises(bridge.BridgeNotRegistered, match=name):
            bridge.get(name)


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
    """Which of the two interfaces takes the delivery is checked, not attempted.

    `_hand_off` falls from `bridge.VERIFY_AND_STORE` to `bridge.EMIT`: the receiver takes
    `source=` (ADR connections-1), so this app's probe does not bind and its own shape does.
    """
    receiver = bridge.get(bridge.VERIFY_AND_STORE)
    assert receiver.__module__ == "apps.events.receivers", "the spine still exposes a receiver"
    # What `_hand_off` actually offers. Still not a fit, still on purpose.
    assert not _accepts(receiver, source=None, event_type="", body="", headers={}, verified=True)
    # The receiver's own shape: raw bytes, an unchecked signature, and the row.
    assert _accepts(receiver, request_body=b"body", signature="sig", source=None, name="x")
    # And the loose pair is gone rather than merely unused.
    assert not _accepts(
        receiver,
        request_body=b"body",
        signature="sig",
        secret="s",  # noqa: S106 — a signing secret the test both signs and verifies with
        tenant=None,
        name="x",
    )
