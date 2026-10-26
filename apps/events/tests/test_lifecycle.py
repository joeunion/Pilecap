"""How the spine's four tables end, and the machine that ends two of them.

ADR core-13, house rule 31. The declarations live on the
models; this module is what says they are **true** — which is the half a
declaration cannot prove about itself.

Three properties, in the order a reviewer should read them.

## 1 · The purge takes exactly the finished deliveries and nothing else

`Delivery` has four statuses and only two of them are finished. A `delivered`
row says the subscriber took it; a `dead` row says we gave up saying so. A
`pending` row is a promise the dispatch is still keeping and a `failed` row is
one it is still retrying, and deleting either would delete work the relay still
owes — the failure this filter exists not to commit. So the population is
seeded in **all four states, at two ages each**, and the assertion is on the
survivors by id rather than on a count, because a count cannot tell "took the
right two" from "took two".

The window is measured from `delivered_at` / `dead_lettered_at` and never from
`created_at`, which is the second half of the same property: a delivery that has
been failing for a hundred days is old and is not finished, and a purge keyed on
row age would take it.

## 2 · The chain rule 31 walks is really there

Rule 31 proves the chain is *written down*; it does not prove the schedule
carries the right window, and it explicitly does not prove the filter is right
(its own `does_not_cover` says both). So the chain is walked here too — schedule
declaration, workflow, activity, service — and the window the schedule's action
carries is pinned against the constant the declaration on the model quotes. That
is the seam that stayed invisible: `purge_expired` existed for a whole cycle with
nothing calling it, and every link of this chain was where the silence was.

The audit half is the same walk from the other end: the deployment's own sweep
is an action somebody has to be able to find later, and with no tenant it lands
in the **platform** population — `AuditEntry.objects.for_platform()`, which is
what `manage.py audit_tail --platform` reads.

## 3 · Every model in this app has declared, and what it declared is coherent

The census is over the app registry, not over a list in this file: a table added
on Thursday is in it without anybody remembering. `Outbox` is the entry worth
reading twice — the ratified retention table called it
*unbounded-with-reason*, and this tree has swept its `dispatched` rows since the
app landed. The declaration follows the tree.

The replay posture that reason rests on is proved where it already was —
`test_services.py::test_purging_leaves_the_failures_alone` and
`test_commands.py`'s `replay_events` coverage — and is deliberately not copied
here: a second copy of an assertion is a second thing to keep true.
"""

from __future__ import annotations

import importlib
import inspect
from datetime import timedelta
from typing import Any

import pytest
from django.apps import apps as django_apps

from apps.core.actor import system_actor
from apps.core.audit import AuditEntry
from apps.core.lifecycle import Lifecycle, LifecycleKind, lifecycle_of
from apps.core.models import Tenant
from apps.core.time import now
from apps.core.types import Swept
from apps.events import activities, services
from apps.events.models import Delivery, Event, Outbox, WebhookEndpoint
from apps.events.types import PurgeExpired, PurgeOutcome
from apps.example.events import WIDGET_CREATED

# `transaction=True`, for the reason `test_activities.py` states beside its own
# marker: an activity calls `close_old_connections()` at both ends, and inside
# the wrapping transaction a plain `django_db` test uses that closes the
# connection the test itself is holding. Two tests here drive the activity, so
# the whole module runs the way the worker does — against real commits.
pytestmark = pytest.mark.django_db(transaction=True)

# Comfortably past the ninety-day window and comfortably inside it. Both are
# derived from `DELIVERY_RETENTION_DAYS` rather than typed, so the day the
# ratified number moves this file moves with it instead of going quietly wrong.
PAST_THE_WINDOW = activities.DELIVERY_RETENTION_DAYS + 10
INSIDE_THE_WINDOW = activities.DELIVERY_RETENTION_DAYS - 10


def _delivery(
    *,
    tenant: Tenant,
    endpoint: WebhookEndpoint,
    status: str,
    days: int,
) -> Delivery:
    """One delivery in one state, finished (or not) `days` ago.

    Both terminal timestamps are written from the same moment so that a filter
    reading the wrong one is visible: a `dead` row carries `dead_lettered_at`
    and a `delivered` row carries `delivered_at`, and neither carries the
    other's.
    """
    event = services.record_event(
        tenant=tenant, name=WIDGET_CREATED, payload={"n": days}, actor=system_actor(tenant=tenant)
    )
    finished_at = now() - timedelta(days=days)
    delivery = Delivery.objects.create(endpoint=endpoint, event=event, status=status, attempts=1)
    if status == Delivery.Status.DELIVERED:
        Delivery.objects.filter(pk=delivery.pk).update(delivered_at=finished_at)
    elif status == Delivery.Status.DEAD:
        Delivery.objects.filter(pk=delivery.pk).update(dead_lettered_at=finished_at)
    else:
        # Not finished, and deliberately OLD: the row that a purge keyed on
        # `created_at` would take and this one must not.
        Delivery.objects.filter(pk=delivery.pk).update(created_at=finished_at)
    return delivery


@pytest.fixture
def endpoint(tenant: Tenant) -> WebhookEndpoint:
    return WebhookEndpoint.objects.create(
        tenant=tenant,
        url="https://subscriber.example/hook",
        secret="a-shared-secret",  # noqa: S106 — a signing secret the test both signs and verifies with  # pragma: allowlist secret
    )


# --- 1 · The eligible population, and only it --------------------------------


def test_the_purge_takes_exactly_the_finished_deliveries_past_the_window(
    tenant: Tenant, endpoint: WebhookEndpoint
) -> None:
    """Eight rows in, two out. The survivors are asserted by id, not by count.

    The two it takes are the only two that are BOTH finished and past the
    window. Six survive, and each survives for a different reason, which is why
    they are all here: two are finished and young, and four are old and not
    finished — the population a purge keyed on row age would have eaten.
    """
    old_delivered = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DELIVERED, days=PAST_THE_WINDOW
    )
    old_dead = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DEAD, days=PAST_THE_WINDOW
    )
    young_delivered = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DELIVERED, days=INSIDE_THE_WINDOW
    )
    young_dead = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DEAD, days=INSIDE_THE_WINDOW
    )
    old_pending = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.PENDING, days=PAST_THE_WINDOW
    )
    old_failed = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.FAILED, days=PAST_THE_WINDOW
    )
    young_pending = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.PENDING, days=INSIDE_THE_WINDOW
    )
    young_failed = _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.FAILED, days=INSIDE_THE_WINDOW
    )

    events_before = set(Event.objects.values_list("pk", flat=True))
    outbox_before = set(Outbox.objects.values_list("pk", flat=True))
    assert Delivery.objects.count() == 8

    removed = services.purge_deliveries(
        before=now() - timedelta(days=activities.DELIVERY_RETENTION_DAYS), tenant=None
    )

    assert removed.count == 2
    assert set(Delivery.objects.values_list("pk", flat=True)) == {
        young_delivered.pk,
        young_dead.pk,
        old_pending.pk,
        old_failed.pk,
        young_pending.pk,
        young_failed.pk,
    }
    assert not Delivery.objects.filter(pk__in=[old_delivered.pk, old_dead.pk]).exists()

    # The two populations the delivery sweep must not touch, as NON-DIFFS. A
    # `Delivery.event` is a CASCADE from `Event`, so a purge that reached for
    # the event instead of the delivery would take the outbox row with it and
    # every one of these three sets would move at once.
    assert set(Event.objects.values_list("pk", flat=True)) == events_before
    assert set(Outbox.objects.values_list("pk", flat=True)) == outbox_before


def test_the_purge_is_idempotent(tenant: Tenant, endpoint: WebhookEndpoint) -> None:
    """Temporal runs an activity at least once, so the second run must be a no-op."""
    _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DELIVERED, days=PAST_THE_WINDOW
    )
    before = now() - timedelta(days=activities.DELIVERY_RETENTION_DAYS)

    assert services.purge_deliveries(before=before, tenant=None).count == 1
    assert services.purge_deliveries(before=before, tenant=None).count == 0


# --- 2 · The chain, and the row it leaves behind -----------------------------


def test_the_declared_chain_reaches_the_delivery_sweeper() -> None:
    """The schedule carries the window `Delivery.lifecycle` quotes; rule 31 walks the rest."""
    declaration = next(one for one in activities.SCHEDULES if one.name == "events.purge-expired")
    action: Any = declaration.schedule("djb-tests").action

    # The workflow the schedule names.
    assert action.workflow == services.PURGE_WORKFLOW == "PurgeExpiredWorkflow"

    # The window it carries, against the constant the model's declaration quotes.
    window: PurgeExpired = action.args[0]
    assert window.delivery_retention_days == activities.DELIVERY_RETENTION_DAYS == 90

    # The service `Delivery.lifecycle` names, through the dotted path it carries.
    declared = lifecycle_of(Delivery)
    assert declared is not None
    module_path, _, attribute = declared.purged_by.rpartition(".")
    assert getattr(importlib.import_module(module_path), attribute) is services.purge_deliveries


def test_one_run_of_the_sweep_purges_and_leaves_a_platform_audit_row(
    tenant: Tenant, endpoint: WebhookEndpoint
) -> None:
    """The activity, triggered directly, on the shape the schedule hands it.

    A direct trigger rather than a time-skipping server (E1-2 allows either):
    the end-to-end run through the real Temporal environment is
    `test_workflows.py::test_housekeeping_purges_expired_keys_and_old_outbox_rows`,
    which was later extended with a delivery. What is only visible here is the
    AUDIT row — the deployment's own sweep, in the population that has no tenant.
    """
    _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DELIVERED, days=PAST_THE_WINDOW
    )
    _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.PENDING, days=PAST_THE_WINDOW
    )

    outcome: PurgeOutcome = activities.purge_expired_records(
        PurgeExpired(
            outbox_retention_days=30,
            delivery_retention_days=activities.DELIVERY_RETENTION_DAYS,
        )
    )

    assert outcome.deliveries == 1
    assert Delivery.objects.count() == 1

    row = AuditEntry.objects.for_platform().filter(action="events.purge_deliveries").get()
    assert row.tenant_id is None
    assert row.actor_user_id is None
    assert row.actor_token_id is None
    assert row.actor_kind == "system"
    assert row.outcome == "ok"


def test_a_replayed_history_without_the_window_does_not_sweep_everything(
    tenant: Tenant, endpoint: WebhookEndpoint
) -> None:
    """Zero means "the declared default", not "delete everything finished".

    A schedule action written before `delivery_retention_days` existed
    deserialises out of a Temporal history as zero. Without the fallback in the
    activity, `now() - timedelta(days=0)` is now, and every finished delivery in
    the deployment goes. This is `ReconcileOutbox.batch_size`'s finding, one
    field along.
    """
    _delivery(
        tenant=tenant, endpoint=endpoint, status=Delivery.Status.DELIVERED, days=INSIDE_THE_WINDOW
    )

    outcome = activities.purge_expired_records(PurgeExpired(outbox_retention_days=30))

    assert outcome.deliveries == 0
    assert Delivery.objects.count() == 1


@pytest.mark.parametrize("sweep", ["purge_dispatched_outbox", "purge_deliveries"])
def test_each_daily_sweep_is_on_the_factorys_one_signature(sweep: str) -> None:
    """ADR core-22 absence 1: `(*, before, tenant: None) -> Swept`, `daily_purge`'s shape."""
    signature = inspect.signature(getattr(services, sweep), eval_str=True)

    assert list(signature.parameters) == ["before", "tenant"]
    assert {p.kind for p in signature.parameters.values()} == {inspect.Parameter.KEYWORD_ONLY}
    assert signature.parameters["tenant"].annotation is None
    assert signature.return_annotation is Swept


# --- 3 · The census over this app --------------------------------------------

#: What each of this app's four tables declared, as the pin a reviewer reads.
#: Written out rather than derived from the models, for the reason every pin in
#: this repository is written out: a pin derived from the thing it pins cannot
#: fail, and the point of this one is that CHANGING a declaration is a diff
#: somebody has to look at.
DECLARED: dict[str, LifecycleKind] = {
    "events.Event": LifecycleKind.UNBOUNDED,
    "events.Outbox": LifecycleKind.PURGED,
    "events.WebhookEndpoint": LifecycleKind.UNBOUNDED,
    "events.Delivery": LifecycleKind.PURGED,
}


def test_every_model_in_this_app_declares_how_its_data_dies() -> None:
    """The census is over the REGISTRY, so a table added on Thursday is in it."""
    declared = {
        model._meta.label: lifecycle_of(model)
        for model in django_apps.get_app_config("events").get_models()
    }

    undeclared = sorted(label for label, one in declared.items() if one is None)
    assert undeclared == [], (
        f"{undeclared} carry no lifecycle. House rule 31's `events` ratchet is at zero "
        "— this app has no backlog left to spend."
    )
    assert {label: one.kind for label, one in declared.items() if one} == DECLARED


@pytest.mark.parametrize("label", sorted(DECLARED))
def test_each_declaration_carries_what_its_kind_owes(label: str) -> None:
    """`purged` owes a callable that resolves; `unbounded` owes a dated trigger.

    The primitive refuses a malformed declaration at import, so this cannot fail
    on the grammar. What it CAN fail on is the half the grammar does not check:
    a `purged_by` that still parses as a dotted path after the callable it named
    was moved or renamed — rule 31's `unresolvable` class, said here as a test so
    it fails in this app's suite and not only in the gate.
    """
    model = django_apps.get_model(label)
    declared = lifecycle_of(model)
    assert isinstance(declared, Lifecycle)

    if declared.kind is LifecycleKind.PURGED:
        module_path, _, attribute = declared.purged_by.rpartition(".")
        assert callable(getattr(importlib.import_module(module_path), attribute))
    else:
        assert declared.reason.strip()
        assert declared.trigger.strip()
