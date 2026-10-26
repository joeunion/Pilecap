"""The rows this app owns, and the field that keeps a secret a secret.

Two tables, one aggregate: a `Connection` is a tenant's relationship with one
external system, and an `InboundWebhook` is a thing that system told us,
received and stored before anything tried to interpret it.

**Credentials are encrypted at rest** by `EncryptedJSONField`. That is not
belt-and-braces over database encryption: a `pg_dump` handed to a contractor, a
replica in the wrong region, a `SELECT *` in a support query and an ORM
traceback in a log aggregator are four ways a plaintext token leaves the
database without anybody breaking in. The ciphertext is what is stored; the key
is in the environment (`CONNECTIONS_ENCRYPTION_KEY`), which is a different
blast radius from the database.
"""

from __future__ import annotations

from typing import ClassVar
from uuid import UUID

from django.db import models

from apps.core.fields import EncryptedJSONField as CoreEncryptedJSONField
from apps.core.fields import encryption_keys, fernet
from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import ScopedManager, TenantScopedModel

# Re-exported because this module is where they have always been imported from,
# including by this app's own tests. The implementation is `apps.core.fields`'.
__all__ = [
    "ACCESS_TOKEN_KEY",
    "WEBHOOK_SECRET_KEY",
    "Connection",
    "ConnectionManager",
    "EncryptedJSONField",
    "InboundWebhook",
    "encryption_keys",
    "fernet",
]

# Where the shared secret an inbound webhook is signed with lives: inside the
# encrypted credentials blob, under a reserved key, rather than in a column of
# its own. One encrypted place for every secret this app holds means there is
# no second thing to remember to protect.
# The reserved KEY name inside the blob, not the secret it points at.
WEBHOOK_SECRET_KEY = "webhook_secret"  # noqa: S105 — the dict key a connection's webhook secret is stored under  # pragma: allowlist secret

# The credential key an OAuth exchange writes and `client.http_client` reads.
ACCESS_TOKEN_KEY = "access_token"  # noqa: S105 — the dict key a connection's access token is stored under


class EncryptedJSONField(CoreEncryptedJSONField):
    """`core.fields.EncryptedJSONField`, under the name this app's migration knows.

    The implementation moved down into `apps.core.fields` when a second app —
    `accounts`, for an identity provider's client secret — needed the same
    cipher, and one cipher is one thing to rotate rather than two that drift.

    The subclass stays because a field's *import path* is recorded in every
    migration that uses it: importing the base under its new name here would be
    an `AlterField` on a column whose contents, encoding and key are all
    unchanged.
    """


class ConnectionManager(ScopedManager["Connection"]):
    """`for_tenant`, plus the one lookup that happens before a tenant is known."""

    def for_webhook(self, connection_id: UUID) -> Connection | None:
        """Resolve the connection an inbound webhook names, tenant unknown.

        This is the one read in the app that cannot go through `for_tenant`, and
        the reason is structural rather than convenient: an inbound webhook
        arrives unauthenticated from somebody else's server, so there is no
        session, no token and no `X-Tenant` header — **the tenant is a fact
        about the connection, and the connection is what we are looking up.**

        What stands in for the tenancy is the pair the receiver checks straight
        afterwards: an unguessable UUID in the path, and an HMAC over the body
        with this connection's own secret. A revoked connection has no secret
        (`services.revoke_connection` clears it), so it can no longer be posted
        to, which is why the status filter is here rather than in the caller.
        """
        return (
            self.get_queryset().filter(pk=connection_id, status=Connection.Status.CONNECTED).first()
        )


class Connection(TenantScopedModel):
    """One tenant's relationship with one external system.

    The `provider` slug says which system (`"stripe"`, `"slack"`, the bundled
    `"example"`); the `name` says which account of it, because a tenant with two
    Slack workspaces has two connections and needs to tell them apart.

    Providers themselves are product work — this app ships the shape, the
    registry (`providers.py`) and one fake.
    """

    #: ADR core-13. **Configuration, not data that ages.** This row IS the fact
    #: that this tenant talks to that system: `Connection.id` is the unguessable
    #: half of the inbound webhook URL a provider has stored on its side, the
    #: audit trail names the row by id, and every `InboundWebhook` ever received
    #: hangs off it. A tenant opens one per system it integrates with — tens,
    #: over the life of an account, not one per thing that happens — so the table
    #: grows with the customer list and not with the traffic, and there is no age
    #: at which a connected integration stops being true.
    #:
    #: **Not `bounded`, and that is the reviewer-disagreeable half.** The cascade
    #: is the obvious reading — every row here has a `tenant` — but `tenant` is
    #: `PROTECT` (`TenantScopedModel`), so nothing dies with anything: closing a
    #: tenant is a status transition and a connection outlives it. Calling this
    #: bounded would name a cascade that does not exist and would let a reader
    #: believe offboarding already removes it. Offboarding removes it
    #: DELIBERATELY, through `revoke_connection` and the erasure path, and until
    #: somebody writes that sweep this table is unbounded on purpose.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a tenant's configured integration is configuration, not data that ages: "
            "the row is the fact that this tenant talks to that system, its id is the "
            "unguessable half of the webhook URL the provider holds, and a revoked "
            "connection is the record that the integration existed. The population "
            "grows with the customer list, not with the traffic — tens per tenant "
            "over the life of an account — and `tenant` is PROTECT, so no cascade "
            "removes one and calling this `bounded` would name a mechanism that is "
            "not there."
        ),
        trigger=(
            "2026-08-24 — the first product that opens a connection per END USER "
            "rather than one per integration (a per-seat OAuth grant is the shape), "
            "or the first deployment whose revoked connections outnumber its live "
            "ones by enough to matter. Either turns a configuration table into a "
            "data table, and this declaration into the wrong one."
        ),
    )

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        # Reserved, unwritten (rule 22); trigger: an adapter telling a refused credential apart.
        ERROR = "error", "Error"
        REVOKED = "revoked", "Revoked"

    provider = models.SlugField(max_length=64)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CONNECTED)

    credentials = EncryptedJSONField(default=dict, blank=True)

    # The revocation reason; never a response body or header (an upstream 401 echoes the token).
    last_error = models.TextField(blank=True)

    connected_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    #: Refuse a body-only `X-Signature` delivery; rows older than 2.5.0 are `False`.
    #: Contraction trigger: no row is `False`, or 2027-02-24 — then the v1 branch goes.
    is_signature_v2_required = models.BooleanField(default=True)

    objects: ClassVar[ConnectionManager] = ConnectionManager()

    class Meta(TenantScopedModel.Meta):
        verbose_name = "connection"
        verbose_name_plural = "connections"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "provider", "name"],
                name="connection_unique_name_per_provider_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.provider}: {self.name}"

    @property
    def is_connected(self) -> bool:
        return self.status == self.Status.CONNECTED

    @property
    def has_credentials(self) -> bool:
        """Whether anything is stored — never *what*.

        This is what an `Out` schema and the admin are allowed to say about the
        credentials, and it is enough to answer the only question a human asks
        of the list ("is this one set up?").
        """
        return bool(self.credentials)

    @property
    def webhook_secret(self) -> str:
        """The shared secret an inbound webhook is signed with, or empty."""
        credentials = self.credentials or {}
        return str(credentials.get(WEBHOOK_SECRET_KEY, "") or "")

    @property
    def access_token(self) -> str:
        credentials = self.credentials or {}
        return str(credentials.get(ACCESS_TOKEN_KEY, "") or "")


class InboundWebhook(TenantScopedModel):
    """One verified delivery from an external system, stored before it is read.

    `verify → store → hand off → 202` (`architecture.md`). This row is the
    "store": it exists so that a hand-off which fails, or an `apps/events` that
    is not in the tree yet, costs a retry rather than the event. Nothing
    interprets the body inline.

    **One row per delivery the sender names.** Providers retry — a timeout on
    their side, a redeploy on ours, an operator clicking "resend" — and each
    retry carries the same delivery id — `X-Delivery-Id`, or the `Webhook-Id` /
    `Svix-Id` a real ESP names it with (`services.DELIVERY_ID_HEADERS` is the
    list, in priority order) — which is the provider's own claim that this is
    the same delivery rather than a second thing that happened.
    `delivery_id` plus the constraint below is this product taking that claim at
    its word (ADR connections-1). A provider that sends no id has made no claim,
    and gets a row per delivery: dedup never invents identity.
    """

    #: ADR core-13. **Processed, then mortal.** A stored delivery earns its keep
    #: twice: once when the hand-off is retried against it, and for a while
    #: afterwards, when a human asks "did they send it, and what exactly did they
    #: send?" — the body and the signing headers together are what make that
    #: question answerable (`services.KEPT_HEADERS`). After that it is somebody
    #: else's customer data that this product is only the custodian of, and
    #: keeping it is a liability with no reader.
    #:
    #: **The window is on `handed_off_at`, and an unprocessed row is never
    #: touched.** `status=received` means the hand-off has not happened — an open
    #: promise — and a purge that swept by `created_at` would destroy a
    #: replayable delivery before its workflow ever consumed it. That is the one
    #: failure this declaration exists to make impossible, and it is why the
    #: filter is a status AND a clock rather than an age.
    #:
    #: A provider that redelivers after the window gets a fresh row rather than
    #: the dedup answer, which is correct: the delivery it names is genuinely
    #: gone from here, and the processing downstream is idempotent by its own
    #: idempotency key. The residual is that one redelivery becomes one more
    #: hand-off ninety days later, which is a retry, not a duplicate event.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.PURGED,
        purged_by="apps.connections.services.purge_inbound_webhooks",
        reason=(
            "somebody else's customer data, held only as long as it is useful: for "
            "the hand-off's retries, and for the support window in which a human "
            "asks what the provider actually sent. Ninety days after the hand-off "
            "closed, nothing reads it."
        ),
    )

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        HANDED_OFF = "handed_off", "Handed off"
        HANDLED = "handled", "Handled"
        HANDLER_FAILED = "handler_failed", "Handler failed"

    connection = models.ForeignKey(
        Connection,
        # An owned child of the aggregate: an inbound webhook has no meaning
        # without the connection it arrived through.
        on_delete=models.CASCADE,
        related_name="inbound_webhooks",
    )

    # The sender's own id for this delivery, from whichever of
    # `services.DELIVERY_ID_HEADERS` it sent (ADR connections-1; E1′ widened the
    # one spelling to three when a real ESP turned out to use neither of ours).
    # **Null, not empty string**, and that is the whole
    # mechanism rather than a style choice: the unique constraint below is what
    # makes a redelivery one row, and Postgres treats every NULL as distinct —
    # so providers that send no id keep getting a row each, while providers that
    # do are held to one. An empty string would collide on the second delivery
    # from every silent provider in the product.
    # DJ001 says "avoid null on a string field", and it is right almost
    # everywhere: two spellings of absence is a bug factory. Here the NULL is
    # the mechanism and the empty string would break it, so the rule is
    # answered rather than silenced.
    delivery_id = models.CharField(max_length=200, null=True, blank=True)  # noqa: DJ001

    event_type = models.CharField(max_length=200, blank=True)
    headers = models.JSONField(default=dict, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    handed_off_to = models.CharField(max_length=64, blank=True)
    handed_off_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "inbound webhook"
        verbose_name_plural = "inbound webhooks"
        constraints = [
            # Per connection, never global: `evt_1` from one provider has
            # nothing to do with `evt_1` from another, and two accounts of one
            # provider number their deliveries independently. A global
            # constraint would silently drop somebody else's first delivery.
            models.UniqueConstraint(
                fields=["connection", "delivery_id"],
                name="inboundwebhook_unique_delivery_per_connection",
            ),
        ]
        indexes = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            models.Index(fields=["tenant", "-created_at"], name="inboundwebhook_recency"),
            models.Index(fields=["connection", "status"], name="inboundwebhook_by_status"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type or 'webhook'} on {self.connection_id}"
