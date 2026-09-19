"""The event spine's four tables.

One sentence each, because the shape is the design:

* **`Event`** — the product said something happened. Tenant-scoped, immutable in
  practice, and carrying the three ids (`correlation_id`, `causation_id`,
  `trace_id`) that let a webhook delivered tomorrow be joined to the request
  that caused it.
* **`Outbox`** — one row per event, holding *dispatch* state. It exists because
  "the event happened" and "everyone who should hear about it has heard" are two
  different facts, and writing the second onto the first would mean a delivery
  failure rewriting history. It is written in the same transaction as the event
  (the outbox pattern): if the business write rolls back, neither exists.
* **`WebhookEndpoint`** — a subscriber. **Subscribers are data, not code**: an
  integration is added by inserting a row, never by importing this app.
* **`Delivery`** — one endpoint's attempt at one event, including the attempt
  that never succeeded. `dead_lettered_at` is what makes "which events did we
  fail to deliver, and to whom" a query instead of a log search.

`Outbox` and `Delivery` are `BaseModel` rather than `TenantScopedModel` on
purpose: they are the *mechanism*, not the tenant's data, and the two queries
that matter for them — "what is still pending across the deployment" and "what
is old enough to purge" — are deliberately cross-tenant operations run by the
system. The tenant is one join away, on the event, and every read that serves a
tenant goes through it.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.conf import settings
from django.db import models

from apps.core.fields import EncryptedCharField
from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import BaseModel, TenantScopedModel


class Event(TenantScopedModel):
    """Something that happened, said once, in the shape a subscriber reads.

    `name` is `<app>.<noun>.<past-tense verb>` and is declared in the emitting
    app's `events.py` — `services.emit` refuses a name no app declared, because
    an undeclared event name is a published contract nobody wrote down.

    `v` is the payload version. Every payload carries one, so a subscriber that
    was written against v1 can tell that this is v2 rather than guessing from
    the keys it finds.
    """

    #: ADR core-13. Nothing sweeps this table and nothing is meant to. The
    #: spine's history IS the product's audit surface: `replay_events` re-sends
    #: from these rows, every `Delivery` and every `Outbox` row describes one of
    #: them, and erasure deliberately does not rewrite a payload — a
    #: rewritten event would lie to a replay about what was emitted.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "what the product said happened, kept for as long as anybody can ask what "
            "happened. `replay_events` re-sends from this table, so a deleted event is "
            "a webhook that can never be sent again and a `Delivery` row describing "
            "nothing; and the payload is not rewritable either, because a "
            "rewritten event would lie to a replay about what was emitted. The "
            "disagreeable half, said out loud: this table grows with every write the "
            "product makes, forever, and that is the price of a replayable spine."
        ),
        trigger=(
            "2026-08-24 — the first of: a stated retention obligation on event "
            "payloads, a deployment past ~10 million rows in `events_event`, or the "
            "first product that needs an archival RESIDUAL rather than a live table. "
            "Whichever arrives first turns this into a `purged` declaration with a "
            "window, and the window is a decision somebody signs."
        ),
    )

    name = models.CharField(max_length=255, db_index=True)
    v = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(default=dict, blank=True)

    # --- Which part of the tenant -------------------------------------------
    # The organization of the ROW the event is about, when that row has one —
    # not the acting hat (ADR realtime-2a). A write made by a regional manager
    # into a child branch belongs to the branch, and a hat-stamped event would
    # fan it to the manager's subtree and not to the branch's own sockets.
    #
    # **Nullable, and null means tenant-wide.** An event about something no part
    # of the tenant owns in particular — a tenant-scoped row, an inbound webhook
    # somebody else composed — has no organization and is heard by the whole
    # tenant, which is what every event in this table did before the column
    # existed. History therefore stays honest without a backfill.
    #
    # `PROTECT` for the reason `Delivery.endpoint` is protected: the event is
    # the record that something happened somewhere, and deleting the somewhere
    # must not quietly take the record with it. An organization that is finished
    # with is not deleted; the tree keeps its shape.
    organization = models.ForeignKey(
        "core.Organization",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
    )

    # --- Who ---------------------------------------------------------------
    # Both nullable and both SET_NULL, for the reason `core.audit` gives: a user
    # erased under a data-protection request must not take the record of what
    # happened with them, and a purged token must not either.
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    actor_token = models.ForeignKey(
        "accounts.ApiToken",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    actor_kind = models.CharField(max_length=16, blank=True)

    # --- As part of what ----------------------------------------------------
    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    causation_id = models.CharField(max_length=64, blank=True)
    trace_id = models.CharField(max_length=64, blank=True)

    # When the thing happened, which is not always when the row was written —
    # an inbound webhook carries the sender's moment, and `created_at` carries
    # ours.
    occurred_at = models.DateTimeField(db_index=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "event"
        verbose_name_plural = "events"
        indexes: ClassVar[Any] = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            models.Index(fields=["tenant", "-created_at"], name="event_recency"),
            models.Index(fields=["tenant", "-occurred_at"], name="event_tenant_occurred"),
            models.Index(fields=["tenant", "name"], name="event_tenant_name"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.pk})"


class Outbox(BaseModel):
    """The dispatch state of one event. The outbox half of the outbox pattern.

    Written in the emitting service's transaction, so the promise "we will tell
    everybody" is made atomically with the write it is about. A dispatch
    workflow starts on commit and moves this row to `dispatched`; a delivery
    that exhausts its retries moves it to `failed`, where `replay_events` can
    find it.
    """

    #: ADR core-13. **Purged, and the plan's table said unbounded** — the
    #: declaration follows the tree, because a sweeper hidden behind an
    #: `unbounded` declaration is the poller-that-was-never-built read
    #: backwards. `purge_dispatched_outbox` has swept `dispatched` rows past
    #: `EVENTS_OUTBOX_RETENTION_DAYS` (30) since this app landed, on the same
    #: schedule that sweeps idempotency records. The `failed` population is
    #: never swept and that is where the replay contract actually lives.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.events.services.purge_dispatched_outbox",
        reason=(
            "a `dispatched` row is the receipt for a promise already kept, and "
            "`EVENTS_OUTBOX_RETENTION_DAYS` is how long that receipt is worth "
            "keeping. A `failed` row is never swept — it is the record of something "
            "that never reached its subscriber and the population "
            "`replay_events --failed-only` walks — so the sweeper's FILTER, not this "
            "kind, is what the replay contract rests on."
        ),
    )

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DISPATCHED = "dispatched", "Dispatched"
        FAILED = "failed", "Failed"

    # One outbox row per event, and it dies with the event it describes: a
    # dispatch record for an event nobody has is not a record of anything.
    event = models.OneToOneField(
        Event,
        on_delete=models.CASCADE,
        related_name="outbox",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    # How many times dispatch has been *started* — not how many HTTP attempts
    # were made, which is `Delivery.attempts` and is Temporal's business. It is
    # what makes a replay's workflow id deterministic and still distinct from
    # the first run's.
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    # NO RECENCY INDEX (ADR core-11). The drain rides
    # `outbox_status_next_attempt` below — rule 30's proven reader — and
    # nothing reads this table by `created_at`. Dropping the inherited bare
    # index is pure write-cost saving on the hottest insert path here.
    class Meta(BaseModel.Meta):
        verbose_name = "outbox row"
        verbose_name_plural = "outbox rows"
        indexes: ClassVar[Any] = [
            # The surveyor's standing lens: "events that never dispatched".
            models.Index(fields=["status", "next_attempt_at"], name="outbox_status_next_attempt"),
        ]

    def __str__(self) -> str:
        return f"{self.event_id} [{self.status}]"


class WebhookEndpoint(TenantScopedModel):
    """Where a tenant wants its events delivered. A subscriber, as data.

    `event_names` is an allow-list; **empty means every event**, which is the
    honest default for "tell me what happens here" and is what an integration
    usually wants on day one.

    `secret` is the shared secret the HMAC signature is computed with, and it is
    **encrypted at rest** (`core.fields.EncryptedCharField`). A signature cannot
    be computed from a hash, so this is one of the few values a product must
    keep recoverable — which makes "recoverable by us, opaque in a `pg_dump`"
    the only honest storage for it. It is never logged, never returned by a
    door, and never put in an exception message. It was plaintext until a security
    review found it sitting beside `Connection.credentials`, which had been encrypted
    since the day that app landed.

    Reading it costs a decrypt and **it cannot be filtered on** — two endpoints
    holding the same secret hold different ciphertext. Nothing wants to: the
    delivery activity resolves the endpoint row by id and signs with what that
    row carries.
    """

    #: The key vocabulary predates the class name. Every door, every refusal
    #: sentence and every `require` in this app has said `endpoint.*` since the
    #: app landed, and `snake_case(WebhookEndpoint)` would have made the
    #: vocabulary say `webhook_endpoint.*` — two words for one noun, which is the
    #: defect house rule 54 (a) exists to refuse. The class keeps its name
    #: because `Endpoint` alone says nothing in a tree that also has an API
    #: endpoint in every docstring; the KIND is the shorter word the doors
    #: already use.
    authz_kind: ClassVar[str | None] = "endpoint"

    #: ADR core-13. Configuration, not traffic: a row arrives when somebody
    #: adds an integration and leaves when somebody removes it. Retirement is a
    #: state (`is_active=False`), and `Delivery.endpoint` is PROTECT, so an
    #: endpoint cannot leave while any delivery still says what was sent to it.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a subscriber is a tenant's configuration and grows with the tenant's "
            "integrations, not with its traffic: one row per place a tenant wants its "
            "events delivered. Deactivating is the retirement, deleting is a person's "
            "act, and `Delivery.endpoint` PROTECTs — so the row outlives the "
            "integration by exactly as long as the deliveries that name it."
        ),
        trigger=(
            "2026-08-24 — the first product that MINTS endpoints programmatically "
            "(per install, per device, per short-lived session) rather than one per "
            "integration. At that point subscribers become traffic and this becomes "
            "`purged` on inactivity, with `Delivery`'s PROTECT as the ordering "
            "constraint the sweeper has to respect."
        ),
    )

    url = models.URLField(max_length=500)
    # `max_length` on an encrypted field bounds the PLAINTEXT, as a validator;
    # the column is unbounded text because ciphertext is about 4/3 the size of
    # what went in, plus a 73-byte envelope. `core.fields` carries the
    # arithmetic and the reason.
    secret = EncryptedCharField(max_length=255)
    is_active = models.BooleanField(default=True)
    event_names = models.JSONField(default=list, blank=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "webhook endpoint"
        verbose_name_plural = "webhook endpoints"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "url"],
                name="webhookendpoint_unique_url_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.url} ({'active' if self.is_active else 'inactive'})"

    def wants(self, name: str) -> bool:
        """Whether this endpoint has asked for that event name."""
        names = self.event_names or []
        return not names or name in names


class Delivery(BaseModel):
    """One endpoint's attempt at one event, including the one that never landed.

    Unique on (endpoint, event), which is what makes the delivery activity
    idempotent: Temporal guarantees an activity runs *at least* once, so the row
    is claimed by `get_or_create` and a retry updates it rather than writing a
    second one.
    """

    #: ADR core-13. Ninety days past the moment a delivery reached a FINAL
    #: state (ratified prose — no deployment has real deliveries yet, so
    #: the number is a decision and not a measurement). `pending` and `failed`
    #: are still owed to a subscriber and are never swept; the sweeper rides the
    #: schedule this app already owns (`activities.PURGE`).
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.events.services.purge_deliveries",
        reason=(
            "one attempt's record, kept ninety days past the moment it finished. A "
            "`delivered` or `dead` row answers 'what became of this webhook', and "
            "after the window nobody asks; a `pending` or `failed` row is a promise "
            "still outstanding and is never swept, which is the half of this "
            "declaration a reviewer should check first."
        ),
    )

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        DELIVERED = "delivered", "Delivered"
        FAILED = "failed", "Failed"
        DEAD = "dead", "Dead-lettered"

    endpoint = models.ForeignKey(
        WebhookEndpoint,
        # PROTECT, not CASCADE: the deliveries are the record of what was sent
        # to whom, and deleting an endpoint must not quietly take that with it.
        # An endpoint that is finished with is deactivated.
        on_delete=models.PROTECT,
        related_name="deliveries",
    )
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="deliveries",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    last_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    dead_lettered_at = models.DateTimeField(null=True, blank=True, db_index=True)

    correlation_id = models.CharField(max_length=64, blank=True, db_index=True)
    causation_id = models.CharField(max_length=64, blank=True)
    trace_id = models.CharField(max_length=64, blank=True)

    # NO RECENCY INDEX (ADR core-11). The measured reads ride
    # `delivery_status_created` below, which already leads on `status`;
    # dropping the inherited bare `created_at` index is pure write-cost
    # saving.
    class Meta(BaseModel.Meta):
        verbose_name = "delivery"
        verbose_name_plural = "deliveries"
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "event"],
                name="delivery_unique_endpoint_per_event",
            ),
        ]
        indexes: ClassVar[Any] = [
            models.Index(fields=["status", "-created_at"], name="delivery_status_created"),
        ]

    def __str__(self) -> str:
        return f"{self.event_id} to {self.endpoint_id} [{self.status}]"

    @property
    def event_name(self) -> str:
        """The name of the event this attempt was carrying.

        A derived read over this row's own relation, which is what a model
        property is for — and it is here rather than in the wire schema for a
        reason worth knowing: a ninja `resolve_` hook is consulted *before*
        plain attribute access on whatever object is being validated, so it
        fires again when a `DeliveryOut` is re-validated as an item of
        `DeliveryPage` and finds no `event` on it. The HTTP door would have
        worked and the machine door would not. A property is found by both.

        Every read that reaches a door goes through `selectors.list_deliveries`,
        which selects the event — so this costs no query. The query pins on both
        doors' delivery lists are what keep that true.
        """
        return str(self.event.name)
