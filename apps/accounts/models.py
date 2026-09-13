"""The custom user model, the token a machine acts as one with, and the rows
that say which identity provider a person may arrive through.

Set on day zero and deliberately boring: email is the identifier, there are no
product fields, and nothing here knows what the product is. Anything a product
wants to know about a person belongs on the product's own model, with a foreign
key to this one.

`django.contrib.auth.models.User` is never imported anywhere in the tree; use
`get_user_model()` or `settings.AUTH_USER_MODEL`.

**An IdP answers *who*; never *what they may do*** (`architecture.md`, "Auth &
identity"). `SsoConnection`, `SsoDomain` and `SsoIdentity` below are all about
the first question. Nothing here grants anything: authorization stays in
`core.Membership.role` and each app's `policies.py`, and a person who signs in
through a brand-new connection lands with exactly the membership that
connection's `default_role` says and not one permission more.
"""

from __future__ import annotations

from typing import Any, ClassVar
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.core.fields import EncryptedJSONField
from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import BaseModel, Membership, ScopedManager, Tenant, TenantScopedModel


class UserManager(BaseUserManager["User"]):
    """Creates users keyed on a normalised email address."""

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create(email, password, **extra)

    def _create(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError("A user needs an email address.")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    """A person who can sign in. UUID primary key and timestamps from BaseModel."""

    #: ADR core-13 + ADR ident-5. **The row outlives the person on purpose**, and
    #: that is the whole design of `services.erase_user`: every foreign key in
    #: the deployment points here, the audit trail most of all, and "who approved
    #: this refund" cannot be allowed to become "user 4f2c, deleted". So erasure
    #: anonymises rather than deletes, and the table is unbounded by decision.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "the deployment's people, and the anchor every audit row hangs off. "
            "Erasure is anonymisation, not deletion (`services.erase_user`, ADR "
            "ident-5): the personal half goes and the row stays, because deleting "
            "it would either refuse against a PROTECTing key or take the record "
            "that the person ever acted with it."
        ),
        trigger=(
            "2026-08-24 — a deployment whose erased rows outnumber its live ones "
            "by enough to matter, or a compliance ask that requires the row itself "
            "to go, which is where tenant-level erasure gets decided too."
        ),
    )

    email = models.EmailField(unique=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    # The one identity join between this table and Zitadel: the `sub` claim the
    # platform IdP asserts for this person. **Nullable, and it stays nullable
    # forever** — a user created by `seed`, by `createsuperuser` or by an
    # invitation has never signed in through Zitadel and has no subject yet, and
    # a column that demanded one would make every one of those paths a migration
    # problem instead of a login problem.
    #
    # Unique for the reason `SsoIdentity.subject` is: a subject is the account
    # itself, where an address is a label an employer can reassign. Two rows
    # claiming one subject would be two people inheriting one login.
    #
    # Written at first RP login and nowhere else (W2-R3, one writer). It is here
    # now, in R2's single expand-only leaf, because rule 6 allows one migration
    # leaf per app per rung and R3 has none of its own.
    zitadel_sub = models.CharField(max_length=255, null=True, blank=True, unique=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    objects = UserManager()

    # NO RECENCY INDEX (ADR core-11). No production read orders users by
    # recency; the admin changelist that does is a window, not a door —
    # ops-only, at platform cardinality. TRIGGER: a measured admin finding.
    class Meta(BaseModel.Meta):
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.email


class ApiToken(BaseModel):
    """A bearer token that acts as one user, optionally pinned to one tenant.

    The token is a machine's way in through the same doors a person uses: the
    REST API and the MCP mount both authenticate with it and both end up with a
    `user` and a `tenant`, so neither door can see more than the other.

    Only the SHA-256 of the token is stored. The plaintext exists once, in the
    return value of `services.issue_token`, and is never recoverable — a lost
    token is reissued, not looked up.

    `tenant` is nullable on purpose: a token with a tenant is pinned to it, and
    a token without one resolves the tenant exactly as a signed-in user does,
    from the user's memberships.

    `scopes` is the token's **ceiling** — which families of capability it may
    reach — and it is nullable for the same kind of reason and a stronger one.
    `NULL` means no ceiling: the token can do whatever its person can, which is
    what every token minted before ceilings existed was promised and what it
    keeps. A ceiling never grants: the person's role and the app's policies
    still decide underneath, so a narrow token is strictly less than its person
    and never more. The vocabulary and the two door checks live in
    `apps/core/api/scopes.py`; nothing below a door reads this column.
    """

    #: ADR core-13. A token dies with the person or the tenant it belongs to —
    #: both foreign keys CASCADE, and that IS the lifecycle. Revocation is a
    #: state (`revoked_at`), never a delete, because "this token was used at
    #: 03:00" has to stay answerable after somebody revokes it; a revoked row is
    #: therefore a small permanent cost of an account that still exists, and it
    #: leaves with the account.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="api_tokens",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="api_tokens",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=200)
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(
        null=True,
        blank=True,
        default=None,
        help_text=(
            "The families of capability this token may reach, as "
            "`section:read` / `section:write` names. Empty here means no "
            "limit: the token can do whatever its person can."
        ),
    )

    # NO RECENCY INDEX (ADR core-11). Every read rides either the
    # `(user, name)` unique constraint or the token-hash lookup; nothing
    # walks these by time.
    class Meta(BaseModel.Meta):
        verbose_name = "API token"
        verbose_name_plural = "API tokens"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "name"],
                name="apitoken_unique_name_per_user",
            ),
        ]

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def __str__(self) -> str:
        return self.name


# --- Customer SSO -------------------------------------------------------------
# The three rows that answer "which identity provider is this person's, and who
# are they there". Read them in that order: a `SsoConnection` is one tenant's
# IdP; a `SsoDomain` is an email domain that connection claims, and the only
# index home-realm discovery has to consult; a `SsoIdentity` is one person at
# that IdP, keyed on the subject the IdP asserts rather than on their address.


# The prefix every per-connection allauth provider id carries. allauth resolves
# a provider config by this string (`SOCIALACCOUNT_PROVIDERS`, or an adapter's
# `list_apps`), so it has to be stable, free of meaning a reader could guess a
# tenant from, and derivable from the row without a second lookup. The
# connection's own UUID is all three.
PROVIDER_ID_PREFIX = "sso-"

# The keys inside `SsoConnection.metadata`. Named once, here, because they are
# written by a service and read by the provider resolver, and a typo between
# those two would be a login that silently talked to the wrong issuer.
ISSUER_KEY = "issuer"
CLIENT_ID_KEY = "client_id"
# A dict KEY name, not a credential; the pragma is the audit, not a mute.
CLIENT_SECRET_KEY = "client_secret"  # pragma: allowlist secret


def normalise_domain(value: str) -> str:
    """The one form a domain is compared in: lower case, no `@`, no whitespace.

    Everything that reads or writes a claimed domain goes through this — the
    service that stores it, the manager that looks it up, the adapter that
    checks an assertion against it. A domain normalised in two places is a
    domain that matches in one of them.
    """
    return (value or "").strip().lower().lstrip("@").rstrip(".")


def domain_of(email: str) -> str:
    """The domain half of an address, normalised. Empty when there is not one."""
    _, _, domain = (email or "").strip().partition("@")
    return normalise_domain(domain)


def provider_id_for(connection_pk: UUID) -> str:
    """The allauth provider id a connection's login URL is built from."""
    return f"{PROVIDER_ID_PREFIX}{connection_pk.hex}"


def connection_pk_from_provider_id(provider_id: str) -> UUID | None:
    """The connection a provider id names, or `None` if it names none.

    Deliberately total: this is called with whatever appeared in a URL, and a
    malformed id has to be "no such connection" rather than an exception in the
    middle of a login.
    """
    if not provider_id.startswith(PROVIDER_ID_PREFIX):
        return None
    try:
        return UUID(hex=provider_id[len(PROVIDER_ID_PREFIX) :])
    except (ValueError, AttributeError):
        return None


class SsoConnectionManager(ScopedManager["SsoConnection"]):
    """`for_tenant`, plus the lookup a login has before it knows the tenant."""

    def by_provider_id(self, provider_id: str) -> SsoConnection | None:
        """Resolve the connection an allauth callback names, tenant unknown.

        The second of the two reads in this repository that cannot go through
        `for_tenant`, and for the same structural reason as
        `connections.ConnectionManager.for_webhook`: **the tenant is a fact
        about the connection, and the connection is what we are looking up.** A
        browser coming back from an IdP carries no session for this product yet,
        no bearer token and no `X-Tenant` header — the provider id in the
        callback URL is the whole of what it has.

        A disabled connection resolves to nothing, so switching a connection off
        stops its logins at the callback rather than merely hiding its button.
        """
        pk = connection_pk_from_provider_id(provider_id)
        if pk is None:
            return None
        return self.get_queryset().filter(pk=pk, status=SsoConnection.Status.ACTIVE).first()


class SsoConnection(TenantScopedModel):
    """One tenant's identity provider.

    `protocol` says how the assertion arrives (`oidc` today; `saml` is the
    recorded escalation — see the class docstring on `Protocol`). `metadata`
    holds the IdP's issuer, client id and client secret, encrypted at rest by
    `core.fields.EncryptedJSONField`, for the reasons that field's docstring
    gives: a `pg_dump`, a replica, a `SELECT *` in a support query and an ORM
    traceback are four ways a plaintext client secret leaves the database
    without anybody breaking in.

    `enforced` is the only field here that takes anything away: with it on,
    somebody whose email domain this connection claims may **not** sign in with
    a password, because a customer who has turned SSO on has done so exactly so
    that disabling an account at the IdP disables it here.

    `default_role` is what a just-in-time provisioned membership is created at.
    It is a *role*, which is data; it is not a policy, which is code. An IdP
    that could name a policy would be an IdP deciding what somebody may do.
    """

    #: ADR core-13. A tenant's identity configuration is part of the tenant: the
    #: `TenantScopedModel` key CASCADEs, and disabling a connection is a state
    #: (`disable_sso_connection`) rather than a delete, so the row is bounded by
    #: the customer and by nothing else.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    class SyncState(models.TextChoices):
        """Where this row's intent has got to on its way into Zitadel.

        The row is the intent and Zitadel is the materialisation (ADR ident-2),
        so there is a gap between the two by construction: the service commits,
        the workflow starts on commit, the activity drives the management API.
        This column is that gap, said out loud. `PENDING` means "we have said
        what we want and Zitadel has not been told yet"; `APPLIED` means the
        activity got an id back and `zitadel_idp_id` is it; `FAILED` means the
        run gave up, and the message is in the workflow's history where the
        retries are.

        `UNMANAGED` is the honest default for every row that predates this
        column and for every row nobody has synced: it is not "not yet", it is
        "nobody ever asked". `zitadel_audit` reports those separately for
        exactly that reason.
        """

        UNMANAGED = "unmanaged", "Not managed in Zitadel"
        PENDING = "pending", "Waiting to be applied"
        APPLIED = "applied", "Applied"
        FAILED = "failed", "Failed to apply"

    class Protocol(models.TextChoices):
        OIDC = "oidc", "OpenID Connect"
        # Present in the vocabulary and refused by the service, deliberately —
        # see `services.create_sso_connection`. The column exists now so that
        # turning SAML on is a service change and a settings change, not a
        # migration on a table customers already have rows in.
        SAML = "saml", "SAML 2.0"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DISABLED = "disabled", "Disabled"

    protocol = models.CharField(max_length=8, choices=Protocol.choices, default=Protocol.OIDC)
    name = models.CharField(max_length=200)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)

    # Issuer, client id and client secret. Encrypted, and therefore unfilterable
    # — everything a query narrows by (the tenant, the status, the claimed
    # domains) is a column or a row beside it.
    metadata = EncryptedJSONField(default=dict, blank=True)

    enforced = models.BooleanField(default=False)
    default_role = models.CharField(
        max_length=16,
        choices=Membership.Role.choices,
        default=Membership.Role.MEMBER,
    )
    disabled_at = models.DateTimeField(null=True, blank=True)

    # --- the materialisation, written back by `apply_identity_config` --------
    # `zitadel_idp_id` is the external IdP object this connection became inside
    # Zitadel. Blank means there is not one — either nobody has synced this row
    # or the sync has not landed yet, and `sync_state` is what tells those apart.
    #
    # Deliberately **not** in `metadata`: metadata is encrypted, and an encrypted
    # column cannot be filtered, joined or read by the drift report without
    # decrypting every row in the table. A resource id is not a secret — it is a
    # public name for an object whose secrets live elsewhere.
    zitadel_idp_id = models.CharField(max_length=64, blank=True, default="")
    sync_state = models.CharField(
        max_length=16,
        choices=SyncState.choices,
        default=SyncState.UNMANAGED,
    )

    objects: ClassVar[SsoConnectionManager] = SsoConnectionManager()

    class Meta(TenantScopedModel.Meta):
        verbose_name = "SSO connection"
        verbose_name_plural = "SSO connections"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "name"],
                name="ssoconnection_unique_name_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.protocol}: {self.name}"

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE

    @property
    def provider_id(self) -> str:
        """The allauth provider id this connection is known by."""
        return provider_id_for(self.pk)

    @property
    def issuer(self) -> str:
        return str((self.metadata or {}).get(ISSUER_KEY, "") or "")

    @property
    def client_id(self) -> str:
        return str((self.metadata or {}).get(CLIENT_ID_KEY, "") or "")

    @property
    def client_secret(self) -> str:
        """The secret itself. Read by the provider resolver and by nothing else.

        Never on an `Out` schema, never in a log line, never in the admin —
        `has_client_secret` is what those are allowed to say.
        """
        return str((self.metadata or {}).get(CLIENT_SECRET_KEY, "") or "")

    @property
    def has_client_secret(self) -> bool:
        """Whether one is stored — never *what*."""
        return bool(self.client_secret)

    @property
    def email_domains(self) -> list[str]:
        """The domains this connection claims, sorted.

        Derived from `SsoDomain` rows rather than stored as a list, because the
        one property that matters about the set — that no two tenants claim the
        same domain — is a `UNIQUE` constraint on a column and cannot be a
        constraint on a JSON array. Reading it costs a query; a caller listing
        many connections prefetches `domains`.
        """
        return sorted(domain.domain for domain in self.domains.all())


class SsoDomainManager(ScopedManager["SsoDomain"]):
    """`for_tenant`, plus home-realm discovery itself."""

    def claim(self, domain: str) -> SsoDomain | None:
        """Whoever already claims this domain, active or not.

        The read behind "no two tenants claim the same domain", used by
        `services.create_sso_connection` so the refusal is a `Conflict` with a
        sentence in it rather than a database constraint error. The constraint
        is still what actually holds the line — this is the polite version, and
        the two racing transactions still meet it.

        Not filtered by status on purpose: a *disabled* connection keeps its
        claim, because re-enabling it must not depend on nobody having taken the
        domain in the meantime.
        """
        cleaned = normalise_domain(domain)
        if not cleaned:
            return None
        return self.get_queryset().select_related("connection").filter(domain=cleaned).first()

    def for_domain(self, domain: str) -> SsoDomain | None:
        """The claim on an email domain, whoever holds it.

        This is home-realm discovery: a person types an address, and the whole
        question is *which tenant's IdP owns that domain* — so a tenant-scoped
        read is not merely inconvenient here, it is the wrong question. What
        makes it safe is that the caller (`selectors.realm_for_email`) returns
        only the method and the connection's own id: never a tenant name, never
        a slug, never a count.
        """
        cleaned = normalise_domain(domain)
        if not cleaned:
            return None
        return (
            self.get_queryset()
            .select_related("connection", "connection__tenant")
            .filter(domain=cleaned, connection__status=SsoConnection.Status.ACTIVE)
            .first()
        )


class SsoDomain(TenantScopedModel):
    """An email domain one connection claims, and no other may.

    A row rather than an element of a JSON list on `SsoConnection`, for one
    reason: **`domain` is unique across every tenant**, and only a column can be.
    Two tenants both claiming `example.com` is not a validation nicety — it is
    the difference between "this address belongs to Acme" and "whichever
    connection the scan happened to reach first". The database refuses it, in
    every transaction, including the two that raced.
    """

    #: ADR core-13. The class docstring above already says it: a claim on a
    #: domain has no meaning without the connection that claims it, the key
    #: CASCADEs, and the row dies with its parent.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    connection = models.ForeignKey(
        SsoConnection,
        # An owned child of the aggregate: a claim on a domain has no meaning
        # without the connection that claims it.
        on_delete=models.CASCADE,
        related_name="domains",
    )
    domain = models.CharField(max_length=253, unique=True)

    objects: ClassVar[SsoDomainManager] = SsoDomainManager()

    class Meta(TenantScopedModel.Meta):
        verbose_name = "SSO domain"
        verbose_name_plural = "SSO domains"
        ordering = ["domain"]
        # OPTS OUT of the inherited `(tenant, -created_at)` composite (ADR
        # core-11). This is the one scoped model with no recency read at all:
        # the ordering is `domain`, every lookup is the unique domain itself,
        # and the population is a handful of verified domains per tenant. An
        # index nothing reads is write cost and nothing else — rule 30 in the
        # other direction. Rule 37's coverage edge does not reach it (its
        # default ordering does not lead on `created_at`), so this empty list
        # is a decision written down, not a silence.
        indexes: ClassVar[Any] = []

    def __str__(self) -> str:
        return self.domain


class SsoIdentityManager(ScopedManager["SsoIdentity"]):
    """`for_tenant`, plus the lookup one assertion makes."""

    def for_subject(self, *, connection: SsoConnection, subject: str) -> SsoIdentity | None:
        """This connection's row for this IdP subject, or none.

        Scoped by the connection, which carries its tenant — so the same subject
        arriving through two different connections finds two different rows, and
        neither tenant's memberships are visible from the other. That is the
        property `test_sso.py`'s cross-tenant collision test pins.
        """
        return (
            self.for_tenant(connection.tenant)
            .select_related("user", "connection")
            .filter(connection=connection, subject=subject)
            .first()
        )


class SsoIdentity(TenantScopedModel):
    """One person at one identity provider.

    **Keyed on the IdP's subject, not on the email address.** An address is a
    label a person's employer can reassign — `j.smith@acme.com` can become a
    different human being — while the subject an IdP asserts is the account
    itself. Keying on the address is how somebody inherits their predecessor's
    access along with their desk.

    The email is stored anyway, as *what the IdP said at the time*, because it
    is what makes a support conversation possible and because it is the thing a
    later assertion is compared against.
    """

    #: ADR core-13 + ADR ident-5. Bounded twice over — both keys CASCADE, so the
    #: row dies with the connection or with the person. **Bounded is not the same
    #: as erased**, and the distinction is the one ER-1 exists for: the row
    #: survives an erasure (the person's `User` row survives too), and it is
    #: `erase_user` that takes the address out of it. `subject` and
    #: `last_seen_at` stay, because a subject is what a later assertion is
    #: matched against and a login time is a fact about a login.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    connection = models.ForeignKey(
        SsoConnection,
        on_delete=models.CASCADE,
        related_name="identities",
    )
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="sso_identities",
    )
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    objects: ClassVar[SsoIdentityManager] = SsoIdentityManager()

    class Meta(TenantScopedModel.Meta):
        verbose_name = "SSO identity"
        verbose_name_plural = "SSO identities"
        constraints = [
            models.UniqueConstraint(
                fields=["connection", "subject"],
                name="ssoidentity_unique_subject_per_connection",
            ),
        ]
        indexes = [
            # Re-added by hand: this list SHADOWS `TenantScopedModel.Meta`'s
            # inherited composite (Django does not merge Meta.indexes down an
            # inheritance chain), and the model's default ordering is still
            # `-created_at`. ADR core-11; rule 37's coverage edge.
            models.Index(fields=["tenant", "-created_at"], name="ssoidentity_recency"),
            models.Index(fields=["user"], name="ssoidentity_by_user"),
        ]

    def __str__(self) -> str:
        return f"{self.subject} at {self.connection_id}"


# --- The deployment's own look, as a row ------------------------------------
#
# WHY THIS IS NOT TENANT-SCOPED, decided by the lead and confirmed here against
# `manage.py introspect` rather than assumed. Every other row in this module a
# customer owns inherits `TenantScopedModel`; this one inherits `BaseModel`
# directly, beside `ApiToken`, because it is **the deployment's** configuration
# and no customer's. There is exactly one Zitadel instance and one login screen,
# and a tenant-scoped table would promise per-tenant branding that the single
# shared LabelPolicy cannot deliver — a schema making a promise the API cannot
# keep. Per-tenant branding is the RECORDED TRIGGER (ADR ident-2's amendment),
# not something built here: it needs Zitadel organisations per tenant, which is
# a different shape and a different rung.
#
# (The stage-2 criteria said "deployment-level platform config like
# SsoConnection"; `SsoConnection` is `TenantScopedModel`, so it is the wrong
# example for the scoping half even though it is the right family. The
# unambiguous half of the ruling — NOT tenant-scoped — is what is built, and the
# introspect dump that settles it is in the rung's report.)


class IdentityBranding(BaseModel):
    """What the hosted identity screen should look like: the intent, as a row.

    **The row is the intent; the console is a window, not a door** (house rule
    27). Somebody with console access can repaint Zitadel's login page in
    thirty seconds and nothing in this codebase would know — which is exactly
    the regime the entrance survey measured: a person crossed from a styled
    sign-in page onto a purple Zitadel screen and back, and the two had never
    been told about each other. This table is the half that can be told.
    `set_identity_branding` writes it, `apply_identity_config` materialises it,
    and `zitadel_audit` reports a console edit that disagrees with it as drift.

    **One active row, enforced in the database.** A deployment has one login
    screen, so a second active branding row would be two intents for one
    surface, and whichever ran last would win silently. The partial unique index
    below makes that unrepresentable rather than merely discouraged; superseding
    is `is_active=False` on the old row and a new one, so what the screen used
    to look like stays answerable.

    **The defaults are DERIVED, never typed here.** `product_name` and `accent`
    default to the same `PRODUCT_NAME`/`BRAND_ACCENT` the entrance templates
    read (`apps/accounts/templatetags/entrance.py`, `templates/account/
    base_entrance.html`), which is the one-declared-value law: one source, two
    consumers, so the page before the hosted step and the page after it match by
    construction instead of because somebody kept two values in step. The
    service is where that derivation happens — a model default reading settings
    at import time would freeze the value into the migration.
    """

    #: ADR core-13. **UNBOUNDED, not `bounded`** — this row has no owning FK to
    #: CASCADE from, so nothing structural ever caps or clears its population,
    #: which is exactly what `bounded` means everywhere else it is declared in
    #: this module (`ApiToken`, `SsoConnection`, `SsoDomain`, `SsoIdentity`: a
    #: key CASCADEs and the row dies with its parent). This row's shape — one
    #: active plus an ever-growing history of superseded ones, never deleted —
    #: is `apps/comms/models.py`'s `MessageTemplate` shape exactly, and that one
    #: is declared `unbounded` with the same reasoning: superseding is a state
    #: change and never a delete, because "what did the login screen look like
    #: in March" is a question an incident review asks. Growth is merely SLOW
    #: — a human act measured in years — which is the reason, not the kind.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "one active row per deployment, plus every superseded one behind it, "
            "kept forever so 'what did the login screen look like in March' stays "
            "answerable. Growth is one row per restyle, which is a human act "
            "measured in years — bounded in PRACTICE, not by any owning row."
        ),
        trigger=(
            "2026-08-31 — the first deployment whose branding history is large "
            "enough to be a cost, or a ruling that a superseded row nothing "
            "references may be purged; either turns this into a `purged` "
            "declaration with a callable and a `ScheduleDeclaration` behind it."
        ),
    )

    #: Shown on the hosted screen, and the same string the entrance templates
    #: print. Not a foreign key to anything: the deployment is not a row here.
    product_name = models.CharField(max_length=200)

    #: The ONE colour, as a CSS hex string — the value `BRAND_ACCENT` declares
    #: and the entrance token block consumes. Zitadel calls it `primaryColor`;
    #: the translation lives in `zitadel.py`, where every other name Zitadel
    #: uses is translated, so this column stays in our vocabulary.
    accent = models.CharField(max_length=9)

    #: The surface pair, light and dark, mirroring the entrance token block's
    #: `--surface`/`--ink`. Blank means "let Zitadel keep its own", which is the
    #: honest default for a deployment that has only set an accent.
    background_color = models.CharField(max_length=9, blank=True, default="")
    font_color = models.CharField(max_length=9, blank=True, default="")
    background_color_dark = models.CharField(max_length=9, blank=True, default="")
    font_color_dark = models.CharField(max_length=9, blank=True, default="")

    #: A URL Zitadel can fetch the logo from, or empty. Deliberately a reference
    #: and not an upload: the logo endpoints are a multipart asset API, and
    #: putting file bytes through the identity seam would give `zitadel.py` a
    #: second job (ADR files-2 owns bytes; this owns configuration).
    logo_url = models.URLField(blank=True, default="")

    #: `is_` because the naming grammar says a boolean says so (house rule 16).
    #: The criteria called this field `disable_watermark`; the grammar wins, and
    #: `zitadel.py` maps it onto Zitadel's own `disableWatermark` at the edge.
    is_watermark_disabled = models.BooleanField(default=False)

    #: Exactly one row is the live intent. See the class docstring.
    is_active = models.BooleanField(default=True)

    # --- the materialisation, written back by `apply_identity_config` --------
    # `SsoConnection`'s pair, one field lighter: a LabelPolicy is a SINGLETON on
    # the org and has no id of its own to record, so there is nothing to hold
    # where `zitadel_idp_id` sits. `sync_state` still answers "has this intent
    # reached Zitadel", which is the question the audit and the operator ask.
    sync_state = models.CharField(
        max_length=16,
        choices=SsoConnection.SyncState.choices,
        default=SsoConnection.SyncState.UNMANAGED,
    )

    class Meta(BaseModel.Meta):
        verbose_name = "identity branding"
        verbose_name_plural = "identity branding"
        constraints = [
            # A partial unique index: any number of superseded rows, at most one
            # live one. `is_active` is the column and the condition both, which
            # is the standard shape for "one of these is current".
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="identitybranding_one_active",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.product_name} ({self.accent})"
