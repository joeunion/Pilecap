"""The model primitives every app builds on.

`BaseModel` is mandatory: every concrete model in the product inherits it —
directly for the few rows no tenant owns, and through `TenantScopedModel` for
everything a tenant does own, which in a product is nearly everything.

**Tenancy is on.** The shape is the only one this template supports: shared
schema, a `tenant` foreign key, reads through `ScopedManager.for_tenant()`, and
`TenantMiddleware` resolving `request.tenant` from the acting user's
`Membership`. It fails closed — no membership means `request.tenant is None`
and every scoped read returns nothing. There is no superuser exemption, because
an exemption is a leak with a nicer name.

A genuinely single-tenant product opts out once, in its own `architecture.md`:
models inherit `BaseModel` instead, `TenantMiddleware` comes out of settings,
and house rule 8 is disabled with the reason recorded.
"""

from __future__ import annotations

from typing import Any, ClassVar, TypeVar

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models

from apps.core.ids import uuid7
from apps.core.lifecycle import AppendOnlyViolation, Lifecycle, LifecycleKind

# --- The materialized path -----------------------------------------------------
#
# An organization's place in its tenant's tree is a string, not a walk: `0000`
# is the root, `0000.0001` its second child, `0000.0001.0000` that child's
# first. Segments are FIXED WIDTH, which is the property everything else rests
# on — a fixed width makes "is A an ancestor of B" a prefix test that cannot
# accidentally match (`0001` can never be a prefix of `00010`, because there is
# no `00010`), and it makes the read path one indexed `LIKE 'prefix.%'` rather
# than a recursive CTE or an adjacency walk. Reads happen on every request;
# moves happen almost never. This is the trade, made deliberately.
PATH_SEPARATOR = "."
PATH_SEGMENT_WIDTH = 4
# Base 36 — digits then lowercase letters — so a segment is four characters that
# sort the same way as bytes and as integers, which is what lets the database
# compare paths without decoding them.
PATH_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
PATH_SEGMENT_LIMIT = len(PATH_ALPHABET) ** PATH_SEGMENT_WIDTH  # 1,679,616 children
# How deep a tenant's tree may go. Twelve is not a guess about org charts: it is
# the number that keeps `path` under a size Postgres indexes happily while being
# far past anything a distribution network has needed. A product that hits it
# has a modelling problem, and the refusal says so rather than silently
# truncating a path.
PATH_MAX_DEPTH = 12
PATH_MAX_LENGTH = PATH_MAX_DEPTH * (PATH_SEGMENT_WIDTH + 1) - 1
# The root of every tenant's tree. One per tenant, created by `create_tenant`.
ROOT_SEGMENT = PATH_ALPHABET[0] * PATH_SEGMENT_WIDTH

# The field an `OrgScopedModel` carries, named once so the queryset, the checks
# and the migrations all say the same word.
ORG_FIELD = "organization"


class PathOverflow(ValueError):
    """The tree cannot hold this: too deep, or too many children under one node."""


def encode_path_segment(index: int) -> str:
    """`0 -> "0000"`, `35 -> "000z"`, `36 -> "0010"`. Fixed width, base 36."""
    if index < 0 or index >= PATH_SEGMENT_LIMIT:
        raise PathOverflow(
            f"A node may hold {PATH_SEGMENT_LIMIT} children; asked for index {index}."
        )
    digits = ""
    remaining = index
    for _ in range(PATH_SEGMENT_WIDTH):
        remaining, digit = divmod(remaining, len(PATH_ALPHABET))
        digits = PATH_ALPHABET[digit] + digits
    return digits


def decode_path_segment(segment: str) -> int:
    """The inverse of `encode_path_segment`, for finding the next free index."""
    value = 0
    for character in segment:
        position = PATH_ALPHABET.find(character)
        if position < 0 or len(segment) != PATH_SEGMENT_WIDTH:
            raise ValueError(f"{segment!r} is not a path segment.")
        value = value * len(PATH_ALPHABET) + position
    return value


def child_path(parent_path: str, index: int) -> str:
    """The path of the `index`-th child of `parent_path`."""
    path = f"{parent_path}{PATH_SEPARATOR}{encode_path_segment(index)}"
    if len(path) > PATH_MAX_LENGTH:
        raise PathOverflow(
            f"A tenant's tree is at most {PATH_MAX_DEPTH} deep; {path!r} would be deeper."
        )
    return path


def path_depth(path: str) -> int:
    """How far below the root a path sits. The root itself is 0."""
    return path.count(PATH_SEPARATOR)


def is_descendant_path(path: str, ancestor_path: str) -> bool:
    """Whether `path` is `ancestor_path` or lies underneath it.

    The separator is part of the test rather than a bare `startswith`, so that
    a path can never be read as a descendant of one it merely shares a prefix
    of. With fixed-width segments that cannot arise; the check is written this
    way anyway, because the day somebody widens a segment is the day a bare
    prefix test starts quietly returning other people's rows.
    """
    return path == ancestor_path or path.startswith(ancestor_path + PATH_SEPARATOR)


def ancestor_paths(path: str) -> tuple[str, ...]:
    """Every path from the root down to this one, inclusive, root first.

        "0000.0001.0002" -> ("0000", "0000.0001", "0000.0001.0002")

    **String decomposition, not a query.** The materialized path already
    contains its own ancestry — that is the whole reason it is materialized —
    so "who is above me" costs no database round trip at all, and
    `ScopedQuerySet.governing` can resolve inherited configuration in the one
    query it was going to make anyway.
    """
    segments = path.split(PATH_SEPARATOR)
    return tuple(PATH_SEPARATOR.join(segments[: index + 1]) for index in range(len(segments)))


def is_org_scoped(model: type[models.Model]) -> bool:
    """Whether this model carries the `organization` foreign key.

    Read off the field registry rather than off the class hierarchy, so a
    product that reaches the same shape another way is still recognised, and so
    the answer cannot drift from what the database actually holds.
    """
    return any(field.name == ORG_FIELD for field in model._meta.concrete_fields)


class InheritedDownward:
    """Declare that this model's rows are **configuration inherited downwards**.

        class WidgetPolicy(InheritedDownward, OrgScopedModel):
            ...

    A marker and nothing else — its whole body is one class attribute, and a
    model may equally write `inherited_downward = True` by hand. It is a class
    named `InheritedDownward` rather than a bare attribute because it is what
    the refusals name: somebody who reads "declare `InheritedDownward`" in a
    `TypeError` can grep for it and land on this docstring.

    **What it unlocks, and what it does not.** It makes
    `ScopedQuerySet.governing(org)` legal — "the nearest row on my ancestor
    chain wins" — and it widens `core.authz.may_be_named` so a branch may
    *name* a policy its parent owns. It does **not** widen `visible_to` by one
    row: a branch still cannot list its parent's rows, and it never learns of
    any row it was not handed. Upward **config resolution**, never upward
    **visibility** (ADR core-3, and `architecture.md`'s A5a: a hole without
    edges is the leak, and the edge here is that the caller must already hold
    the reference).

    Sideways is not this, and never becomes this: a product wanting one branch
    to share with a sibling writes a named policy with a recorded reason.
    """

    inherited_downward: ClassVar[bool] = True


# The class attribute a model sets to declare its rows append-only. Named once,
# here, so the model that declares it, the helper that discovers it and the
# house rule that reads it all say the same word.
APPEND_ONLY_ATTR = "append_only"


def is_append_only(model: type[models.Model]) -> bool:
    """Whether this model declared `append_only = True`.

    Append-only means: a service may `.create()` a row and nothing anywhere may
    update or delete one. `AuditEntry` is the first member and was for a long
    time the only one, hard-coded by name into house rule 20 — which is exactly
    the shape that does not survive a product: a witnessed fact, an accrual and
    a stage-transition log are all the same promise, and none of them is called
    `AuditEntry`.

    A class attribute rather than an `AppendOnlyModel` base, deliberately (ADR
    core-6): a base would put MRO churn on `AuditEntry` to buy a property the
    attribute already has, and the scanner reads the registry either way.
    """
    return bool(getattr(model, APPEND_ONLY_ATTR, False))


def append_only_models() -> list[type[models.Model]]:
    """Every model in the product that declared itself append-only.

    **The population, discovered rather than listed** — which is what turns
    "the audit trail is append-only" from a rule about one model's name into a
    closed question over the registry. A product adds a member by declaring it,
    and house rule 20 covers it in the same commit with no edit to
    `rules.yaml`.
    """
    from django.apps import apps as django_apps

    return [model for model in django_apps.get_models() if is_append_only(model)]


def is_inherited_downward(model: type[models.Model]) -> bool:
    """Whether this model declared `InheritedDownward`.

    An attribute lookup rather than an `issubclass` test, for the same reason
    `is_org_scoped` reads the field registry: the declaration is the fact, and
    a product that reaches it by writing the attribute directly has declared it
    just as loudly as one that inherits the marker.
    """
    return bool(getattr(model, "inherited_downward", False))


class BaseModel(models.Model):
    """UUIDv7 primary key and timestamps. Every concrete model inherits this.

    The key is minted by `apps.core.ids.uuid7` — time-sortable, so ids sort by
    creation and inserts append to the index rather than scattering through it.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    # No `db_index=True` (ADR core-11, house rule 37). A bare index on
    # `created_at` orders the WHOLE DEPLOYMENT by time, and every supported
    # read here is tenant-scoped: a paginated page walked backwards down that
    # index examining other tenants' entries and discarding them (F1a measured
    # 102,300 foreign rows per page; F1b measured 255,000 on AuditEntry). The
    # tenant-leading composite in `TenantScopedModel.Meta` is the replacement
    # for every scoped model. A model that inherits THIS class and no tenant
    # gets no recency index at all unless it names the read that wants one —
    # rule 30's discipline: no index without a proven reader.
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{type(self).__name__} {self.pk}"

    # --- The append-only runtime belt (ADR core-14) -------------------------
    #
    # House rule 20's static half reads the source: `.delete()`, `.update()`
    # and `.bulk_update()` on a name that mentions a declared member. It cannot
    # see a BOUND name — `row = fetch(); row.field = x; row.save()` reads as
    # three innocent lines — and a probe drove exactly that tamper on an
    # append-only member through a full CLEAN gate. P4's production database
    # grant is the third belt and it protects production only, which is not
    # where a tamper gets written.
    #
    # So the model refuses it too, at the last possible moment, for the whole
    # DECLARED population at zero per-model cost. Not a mixin
    # (`AppendOnlyModel`): a base class would put MRO churn on every member to
    # buy a property the one-line declaration already carries, which is the
    # trade ADR core-6 already made and ADR core-14 declines to re-open.
    #
    # The hot path pays one attribute read. `_state.adding` is checked first,
    # so an ordinary `.create()` — the only write an append-only model ever
    # legitimately does — never reaches the population lookup at all.

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Write the row, unless this model declared its rows unrewritable.

        `_state.adding` is the honest test and `pk is None` is not: `BaseModel`
        mints the UUID in Python, so an unsaved row already has a primary key.
        A row loaded from the database and saved again has `adding` False
        whatever the caller believed they were doing, which is precisely the
        case this exists to catch.

        DOES NOT COVER — declared, and the two other belts are named because a
        belt whose gaps are unstated is worse than no belt: a queryset-level
        `Model.objects.filter(...).update(...)` never reaches an instance's
        `save()` and is house rule 20's static half plus the production DB
        grant (ADR core-14's declared residue, three belts stated honestly);
        `bulk_create`/`bulk_update`, `QuerySet.delete()` and raw SQL likewise;
        and `save_base(raw=True)`, which is how `loaddata` writes a fixture.
        """
        if not self._state.adding and is_append_only(type(self)):
            raise AppendOnlyViolation(
                f"{type(self)._meta.label} declared `{APPEND_ONLY_ATTR} = True`: a row of it "
                f"is created once and never changed. Correct it the way a ledger is "
                f"corrected — write a superseding row — rather than by rewriting the one "
                f"that was witnessed."
            )
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> Any:
        """Remove the row, unless this model declared its rows unremovable."""
        if is_append_only(type(self)):
            raise AppendOnlyViolation(
                f"{type(self)._meta.label} declared `{APPEND_ONLY_ATTR} = True`: a row of it "
                f"is never deleted. Retention on an append-only table is archival, dated "
                f"and declared (`apps.core.lifecycle`), never a DELETE at a call site."
            )
        return super().delete(*args, **kwargs)


class Tenant(BaseModel):
    """The tenant a scoped row belongs to.

    `slug` is the public handle: it is what an `X-Tenant:` header names, so it
    is unique and stable. Rename the `name`, never the `slug`.

    `settings` is the tenant's own configuration, including its feature flags
    (`core.flags.is_enabled`). JSON rather than a column per option, because a
    product adds options weekly and a migration per checkbox is a migration
    queue; and validated on the way in by the service that writes it, because
    unvalidated JSON is a schema nobody can read.

    `timezone` and `locale` are **display** concerns and only that: everything
    is stored in UTC (`core.time`), and a tenant's timezone decides what a human
    sees, never what a query filters on.
    """

    #: ADR core-13. The customer list of the installation: a tenant is closed
    #: (`Status.CLOSED`), never removed. Every scoped table PROTECTs off this
    #: row, so a DELETE would refuse anyway — and if it did not, it would take
    #: the audit trail of everything that tenant ever did with it.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "the installation's own customer list. Closing a tenant is a status "
            "transition (`close_tenant`), not a delete: every scoped table PROTECTs "
            "off this row and the audit trail names it, so removing one would either "
            "refuse or erase the record that the tenant existed."
        ),
        trigger=(
            "2026-08-24 — the first deployment whose closed-tenant rows outnumber its "
            "open ones by enough to matter, or a contractual obligation to remove a "
            "former customer's tenant row rather than close it."
        ),
    )

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        SUSPENDED = "suspended", "Suspended"
        CLOSED = "closed", "Closed"

    name = models.CharField(max_length=255, unique=True)
    slug = models.SlugField(max_length=255, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    settings = models.JSONField(default=dict, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    locale = models.CharField(max_length=16, default="en-us")
    suspended_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # NO RECENCY INDEX, and no reader wants one (ADR core-11). This is a
    # platform-cardinality table — one row per customer — and no measured
    # read ever used the bare `created_at` index that used to sit here by
    # inheritance. Rule 30's discipline, applied to indexes: an index
    # without a proven reader is write cost and nothing else.
    class Meta(BaseModel.Meta):
        verbose_name = "tenant"
        verbose_name_plural = "tenants"

    def __str__(self) -> str:
        return self.name

    @property
    def is_active(self) -> bool:
        return self.status == self.Status.ACTIVE


class Membership(BaseModel):
    """Who belongs to which tenant, **where in it**, and what they may do there.

    A user may belong to many tenants and has at most one default — the tenant
    a request resolves to when no `X-Tenant` header names another.

    **`organization` is the "where".** A membership is person × tenant × org ×
    role, and the org is what makes a role mean something in a network: an
    `admin` of a sub-seller and an `admin` of the whole tenant hold the same
    word and must not hold the same power. A flat product never notices — every
    membership lands on the tenant's root and the tree is one node deep.

    A person may hold several memberships in one tenant (a regional manager
    over two branches), which is why the uniqueness is per *organization*.
    Their **effective role** on any node is the best role they hold on that
    node or on one of its ancestors — `core.authz.effective_role` computes it,
    and roles inherit downwards only.

    **Role lives here, never on `User`**: the same person is an owner of their
    own workspace and a member of a client's, and a role on the user could not
    say both. Three of them, deliberately few (`architecture.md`: roles are
    data, policies are code) — a product that needs "may approve refunds"
    writes a predicate in its app's `policies.py`, it does not add a fourth
    role and hope the meaning stays legible.
    """

    #: ADR core-13. **The cascade IS the lifecycle.** A membership dies three
    #: ways and all three are somebody else's act: `revoke_membership` removes
    #: it, deleting the person CASCADEs it, deleting the tenant CASCADEs it.
    #: There is no sweeper and none is wanted — a membership nobody revoked is
    #: a membership somebody still holds.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        "Organization",
        on_delete=models.PROTECT,
        related_name="memberships",
        help_text="Where in the tenant's tree this membership sits. The root, by default.",
    )
    is_default = models.BooleanField(default=False)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)

    # NO RECENCY INDEX (ADR core-11). The reads ride
    # `membership_unique_user_per_organization` (measure_identity pins them
    # at 1/2/2 statements), and the memberships list door's `-created_at`
    # ordering sorts the tenant FK-index slice — bounded by the tenant's
    # staff count, which is the right payer. TRIGGER: a measured top-N
    # finding on that list at product scale buys `(tenant, -created_at)`
    # then, and not before.
    class Meta(BaseModel.Meta):
        verbose_name = "membership"
        verbose_name_plural = "memberships"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "tenant", "organization"],
                name="membership_unique_user_per_organization",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="membership_one_default_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.organization_id} as {self.role}"

    @property
    def is_privileged(self) -> bool:
        """Owner or admin — the roles that may write without a policy saying so."""
        return self.role in {self.Role.OWNER, self.Role.ADMIN}

    # The wire needs the person's address, and it is a PROPERTY rather than a
    # `Field(alias="user.email")` on the schema — ADR example-3, and the reason
    # is that the two doors do not agree on aliases: REST renders by field name
    # and the MCP transport renders `structuredContent` by alias, so an alias
    # makes one row answer under two key sets. A real attribute is found under
    # one name by both. It costs no query as long as the read select_relateds
    # the user, which `core.selectors.list_memberships` does.

    @property
    def user_email(self) -> str:
        """Who this membership belongs to, without the caller fetching the user."""
        return str(getattr(self.user, "email", "") or "")


_ScopedT = TypeVar("_ScopedT", bound="TenantScopedModel")


class ScopedQuerySet(models.QuerySet[_ScopedT]):
    """A queryset that can only be narrowed to one tenant, never widened.

    `for_tenant(None)` returns nothing. That is the whole fail-closed
    behaviour: an unresolved tenant reads an empty table rather than the
    table.
    """

    def for_tenant(self, tenant: Tenant | None) -> ScopedQuerySet[_ScopedT]:
        if tenant is None:
            return self.none()
        return self.filter(tenant=tenant)

    def visible_to(self, actor_or_org: Any) -> ScopedQuerySet[_ScopedT]:
        """Narrow to one organization's **subtree**. The second half of a read.

        House rule 24: an `OrgScopedModel` is read
        `Model.objects.for_tenant(t).visible_to(actor_or_org)`. `for_tenant`
        answers *whose data*; this answers *which part of their network* —
        and the two are different questions, because a tenant with a dealer
        network is one tenant whose members must not see each other.

        **Visibility flows down only.** A seller sees its own rows and its
        sub-sellers'; it never sees its parent's, and never a sibling's.
        Upward or sideways inheritance is available only as an explicit policy
        with a named reason (`architecture.md`, Hierarchy), never as a default
        and never as a superuser exemption.

        The filter is a prefix scan over the materialized path — one indexed
        `LIKE 'prefix.%'` against `organization_path_prefix`, no recursion and
        no tree walk on the read path. Django escapes the LIKE metacharacters
        in `__startswith`, so a slug that somehow carried a `%` or a `_` could
        not widen the scan; paths are base36 and dots anyway, which is the
        belt to that brace.

        `visible_to(None)` returns nothing — the same fail-closed shape
        `for_tenant(None)` has, for the same reason: an unresolved hat reads an
        empty table rather than the table.

        `actor_or_org` is an `Organization`, or anything carrying one on `.org`
        (an `Actor`, an MCP `Principal`, a request). It is typed `Any` because
        `core.models` sits below `core.actor` and may not name it.
        """
        org = actor_or_org if isinstance(actor_or_org, Organization) else None
        if org is None and actor_or_org is not None:
            candidate = getattr(actor_or_org, "org", None)
            org = candidate if isinstance(candidate, Organization) else None
        if org is None:
            return self.none()
        if not is_org_scoped(self.model):
            raise TypeError(
                f"{self.model.__name__} has no `{ORG_FIELD}` — visible_to() is for an "
                "OrgScopedModel. A tenant-scoped model is read with for_tenant() alone."
            )
        prefix = org.path
        return self.filter(
            models.Q(**{f"{ORG_FIELD}__path": prefix})
            | models.Q(**{f"{ORG_FIELD}__path__startswith": prefix + PATH_SEPARATOR})
        )

    def governing(self, org: Organization | None) -> ScopedQuerySet[_ScopedT]:
        """The rows on this org's **ancestor chain**, nearest first. Config only.

            policy = (
                WidgetPolicy.objects.for_tenant(tenant).governing(actor.org).first()
            )

        The read `visible_to` is deliberately not: "which of these rows governs
        me", answered by walking *up* from the acting organization to the root
        and taking the nearest. Three call sites in the product this was lifted
        from ran the identical algorithm — a funnel definition, a document
        template and a quiet-hours window — and each had written it again
        (ADR core-3).

        **Upward config resolution, never upward visibility.** `visible_to` is
        untouched by this and stays downward-only: a branch still cannot list
        its parent's rows. What it may do is *resolve* the parent's policy,
        which it was already being governed by whether it could see it or not.
        That is why it is legal only on a model that has **declared**
        `InheritedDownward` — the population is opt-in, one class attribute
        wide, and readable off the registry.

        **No extra query.** The ancestor chain is decomposed out of `org.path`
        in Python (`ancestor_paths`), so this is one `IN` over an indexed
        column plus the ordering — the same single query the caller was going
        to make. Nearest-first is `-organization__depth`, and depth is
        denormalised for exactly this.

        `governing(None)` returns nothing, the same fail-closed shape
        `for_tenant(None)` and `visible_to(None)` have: an unresolved hat
        resolves no configuration rather than the root's.

        The declaration is checked **before** the argument, unlike
        `visible_to`: a missing `InheritedDownward` is a fact about the model
        and a mistake in the code, and it should say so whether or not the hat
        happened to be `None` on the call that found it.
        """
        if not is_inherited_downward(self.model) or not is_org_scoped(self.model):
            raise TypeError(
                f"{self.model.__name__} has not declared `InheritedDownward`, so "
                "governing() is not legal on it. Upward resolution is opt-in per model "
                "(apps.core.models.InheritedDownward): a row is inherited downwards "
                "only when somebody decided it is configuration, and a model that "
                "carries no `organization` cannot be governed by one at all."
            )
        if org is None:
            return self.none()
        return self.filter(**{f"{ORG_FIELD}__path__in": ancestor_paths(org.path)}).order_by(
            f"-{ORG_FIELD}__depth"
        )


class ScopedManager(models.Manager[_ScopedT]):
    """The only supported way to read a tenant-scoped model."""

    def get_queryset(self) -> ScopedQuerySet[_ScopedT]:
        return ScopedQuerySet(self.model, using=self._db)

    def for_tenant(self, tenant: Tenant | None) -> ScopedQuerySet[_ScopedT]:
        return self.get_queryset().for_tenant(tenant)

    def visible_to(self, actor_or_org: Any) -> ScopedQuerySet[_ScopedT]:
        return self.get_queryset().visible_to(actor_or_org)

    def governing(self, org: Organization | None) -> ScopedQuerySet[_ScopedT]:
        return self.get_queryset().governing(org)


class TenantScopedModel(BaseModel):
    """Abstract base for rows that belong to exactly one tenant.

    Uniqueness on a scoped model puts `tenant` in the constraint; a service
    that writes one takes `tenant` as an explicit keyword argument and never
    reads it from global state.
    """

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
    )

    objects = ScopedManager["TenantScopedModel"]()

    class Meta(BaseModel.Meta):
        abstract = True
        # THE TENANT-LEADING RECENCY COMPOSITE (ADR core-11; house rule 37).
        #
        # `BaseModel.Meta.ordering` is `["-created_at"]` and the cursor seam
        # (`apps/core/api/pagination.py::_total_ordering`) extends it with the
        # pk, so the effective total ordering of a default list page is
        # `created_at DESC, id ASC` — the coordinate system every minted
        # cursor names a position in. This index serves it tenant-locally:
        # `tenant` is the equality prefix, `created_at` the scan order, and the
        # `id` tiebreak is an Incremental Sort over near-singleton timestamp
        # groups. Foreign-tenant rows examined per page: 0.
        #
        # TWO COLUMNS, not three: `(tenant, -created_at, id)` would remove the
        # Incremental Sort but pays 16 bytes/row forever to sort groups that
        # are almost always size 1, and it does NOT make the keyset
        # continuation sargable (Django's expanded `_after` OR is the binding
        # constraint, not the column set). Revisit on a measured Incremental
        # Sort cost or a same-timestamp-burst finding.
        #
        # NO ORGANIZATION COLUMN on the org-scoped half: F1a swept that family
        # and no index moves the narrow-hat plan while recency ordering stands
        # (the lever is `eqjoinsel`, not an access path — ADR core-12), and an
        # org column in the middle breaks the tenant-wide walk for the root
        # hat, which is the flat product's only hat. A flat product pays
        # nothing (architect rule A5).
        #
        # `%(class)s` is interpolated by Django for an index declared on an
        # abstract base, so each concrete model gets its own name. Django does
        # NOT merge `Meta.indexes` down an inheritance chain: a concrete model
        # that declares its own `indexes` SHADOWS this one and must re-add it
        # by hand. Rule 37 is the tripwire over exactly that hole.
        indexes: ClassVar[Any] = [
            models.Index(fields=["tenant", "-created_at"], name="%(class)s_recency"),
        ]


class Organization(TenantScopedModel):
    """A node in one tenant's org tree. **Every tenant has exactly one root.**

    `architecture.md` rules hierarchy a template primitive rather than a
    product's problem: a distribution network, a franchise, a group of
    practices and a plain flat company are the same shape with different
    depths, and retrofitting the shape later means rewriting every read in the
    product. So the tree is here from the start and **a flat product is a
    depth-one tree that pays nothing**: `create_tenant` makes the root, every
    membership lands on it, and `visible_to(root)` is the whole table.

    Three columns carry the structure and they are deliberately redundant:

    * `parent` is the truth — the edge, `PROTECT`ed so a node with children
      cannot be deleted out from under them;
    * `path` is the truth made fast — the materialized path (see the module
      header), unique per tenant, indexed for prefix scans;
    * `depth` is `path`'s segment count, denormalised so "everything two levels
      down" is a column comparison rather than a string function.

    All three are written **only** by the services in `core.services`
    (`create_organization`, `move_organization`, and the move's activity), and
    house rule 24 refuses a write to `path` or `parent` anywhere else. A path
    edited by hand is a subtree that silently disappears from every read in the
    product, which is the failure this model most needs to be impossible.

    `slug` is the public handle an `X-Org:` header names — unique **per
    tenant**, because two tenants naming their root `hq` is not a collision.
    """

    #: ADR core-13. A node of a tenant's tree outlives everything hung off it
    #: by construction: `parent` and every `OrgScopedModel.organization` are
    #: PROTECT, and `Membership.organization` is too, so a node is removable
    #: only once nothing anywhere points at it — and nothing in this template
    #: removes one. The tree is the tenant's shape, and a shape does not expire.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a tenant's org tree is its shape, not its traffic: it grows when the "
            "business does and is bounded by the business, not by time. Every "
            "reference to a node is PROTECT, so a node cannot leave while any row "
            "still places itself in it, and the audit trail's `acting_org` places "
            "actions in nodes for as long as the trail is readable."
        ),
        trigger=(
            "2026-08-24 — the first product that genuinely retires branches (a "
            "franchise network churning outlets), which is the product that needs "
            "`archived_at` on a node and a rule about what a retired node's rows "
            "are still allowed to say."
        ),
    )

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
        help_text="Null for the tenant's root node, and for nothing else.",
    )
    path = models.CharField(max_length=PATH_MAX_LENGTH, editable=False)
    depth = models.PositiveSmallIntegerField(default=0, editable=False)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "organization"
        verbose_name_plural = "organizations"
        ordering = ["path"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "slug"],
                name="organization_unique_slug_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["tenant", "path"],
                name="organization_unique_path_per_tenant",
            ),
            # One root per tenant, held by the database rather than by a
            # service remembering to look. A second root would be a second
            # tree, and every `visible_to` in the product would answer for one
            # of them.
            models.UniqueConstraint(
                fields=["tenant"],
                condition=models.Q(parent__isnull=True),
                name="organization_one_root_per_tenant",
            ),
        ]
        indexes = [
            # `varchar_pattern_ops` is what makes `LIKE 'prefix%'` an index scan
            # under a non-C collation, which every real database has. Without
            # the opclass the index exists and the planner ignores it, and the
            # read path this whole design exists to make cheap becomes a
            # sequential scan nobody notices until the network is large.
            #
            # **Tenant-less on purpose.** `visible_to()` reaches this table
            # through a JOIN from an org-scoped model, where the tenant filter
            # sits on the *outer* row and the organization side of the join
            # carries only the path predicate. This is the index that read
            # takes, and it is why the composite below does not replace it.
            models.Index(
                fields=["path"],
                name="organization_path_prefix",
                opclasses=["varchar_pattern_ops"],
            ),
            # The same prefix scan, made tenant-local — the subtree read every
            # socket connect issues (`realtime.selectors.list_subtree_org_ids`)
            # and every `move_organization` takes.
            #
            # M4's FINDING 1 measured what the tenant-less index above costs
            # that read: because a materialized path is only unique *per
            # tenant*, `LIKE '0000.0015.%'` matches the same branch in every
            # tenant, so the planner's estimate of the prefix index is the
            # cross-tenant row count and its selectivity is judged against the
            # WHOLE table. Above a share of the tenant's organizations it gave
            # up and read the tenant FK index instead, filtering the path
            # predicate over every organization row the tenant has — so the
            # cost of one hat's connect followed the TENANT's org count rather
            # than the hat's. Leading with `tenant_id` makes both legs of the
            # selector's `OR` tenant-qualified index conditions, which is both
            # a plan the planner will take much further up the selectivity
            # curve and a scan that never touches another tenant's entries.
            #
            # F1e measured this before landing it, at all six hat shapes in all
            # three seeded worlds (`quality/perf-realtime-measurement.md` §5):
            # no hat in any world got a worse plan, and the wide hat's 1,052
            # discarded rows went to zero. It is not a universal fix and does
            # not pretend to be — at 100% of a tenant the planner still reads
            # the tenant index and is right to, and at 27.6% the two plans
            # measure as a tie. The doc carries the crossover it moved.
            models.Index(
                fields=["tenant", "path"],
                name="organization_tenant_prefix",
                opclasses=["", "varchar_pattern_ops"],
            ),
            models.Index(fields=["tenant", "depth"], name="organization_tenant_depth"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def is_root(self) -> bool:
        return self.parent_id is None

    def contains(self, other: Organization) -> bool:
        """Whether `other` is this node or lies underneath it. **Downward only.**"""
        return is_descendant_path(other.path, self.path)


class OrgScopedModel(TenantScopedModel):
    """Abstract base for rows one *part* of a tenant owns.

    The choice between this and `TenantScopedModel` is an architectural one and
    the architect skill states it: a row every member of the tenant may see is
    tenant-scoped; a row that belongs to a seller, a branch or a practice
    inside the tenant is org-scoped. Getting it wrong in the safe direction
    (org-scoping something everybody may see) costs a `visible_to(root)`;
    getting it wrong the other way is a leak between the tenant's own customers.

    Every read of one of these is `for_tenant(t).visible_to(actor_or_org)` —
    house rule 24, by AST, with canaries.

    ## The landing gate — `derive_org_from`

    Some org-scoped rows do not *choose* their organization: they inherit it
    from something they point at. A channel preference belongs wherever its
    recipient belongs; a line belongs wherever its order does. A model that
    works that way says so:

        class ChannelPreference(OrgScopedModel):
            # ...along with its `recipient` foreign key, to a model that is
            # itself org-scoped:
            derive_org_from = "recipient"

    and `clean()` then refuses a **final** `organization` that disagrees with
    the target's, on insert and on update alike. It is an invariant on the
    row's own fields-by-reference, which is the kind of rule `clean()` is for
    (`architecture.md`, D3): a database `CheckConstraint` cannot reach across
    a row to read the parent's column, and a service that remembers to check is
    a service that will one day be written by somebody who does not.

    What this catches is a whole class rather than a bug: a write that derived
    the organization from the *actor's hat* while the row it hangs off belongs
    somewhere else, so the row lands in a branch its own parent cannot see. It
    is silent, it is a leak in whichever direction the mismatch went, and no
    read afterwards can tell you it happened.

    **Declared blind spot**: this runs where something calls `full_clean()`.
    That is the house style for a service (`with as_invalid(): row.full_clean()`)
    and it is what the admin does, but it is not a closed question — a service
    that saves without validating is not caught here, and rule 26's AST check
    is the belt to that brace.
    """

    #: The FK whose organization this row's must equal, or `None` when the row
    #: chooses its own. See the landing gate above.
    derive_org_from: ClassVar[str | None] = None

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
    )

    class Meta(TenantScopedModel.Meta):
        abstract = True

    def clean(self) -> None:
        """Django's own hook, plus the landing gate when one is declared."""
        super().clean()
        self._refuse_a_derived_organization_that_disagrees()

    def _refuse_a_derived_organization_that_disagrees(self) -> None:
        declared = type(self).derive_org_from
        if not declared:
            return
        # A declaration naming a field that does not exist is a mistake in the
        # model, not in the row: `get_field` raising FieldDoesNotExist here is
        # louder and more useful than silently checking nothing.
        self._meta.get_field(declared)
        try:
            target = getattr(self, declared)
        except ObjectDoesNotExist:
            # The FK is not set. That is the FK's own `null=False` to refuse,
            # and `clean_fields()` has already said so; adding a second message
            # about a comparison that cannot be made would only be noise.
            return
        if target is None:
            return
        expected = getattr(target, f"{ORG_FIELD}_id", None)
        if expected is None or self.organization_id == expected:
            return
        raise ValidationError(
            {
                ORG_FIELD: [
                    f"This row takes its organization from `{declared}`, which is in a "
                    "different one. A row whose organization disagrees with its parent's "
                    "lands in a branch that cannot see it — leave it unset, or set it to "
                    f"the same organization `{declared}` is in."
                ]
            }
        )


class Invitation(OrgScopedModel):
    """An offer to join one part of a tenant, made before the person has an account.

    **It records where it was sent from** (ADR core-20, the placement law:
    *"comes from where you sent it. Don't elevate
    out of context"*). `organization` is the LANDING NODE — the acting hat at
    grant time — and it is the node every authority question about this row is
    asked at: whether the sender may invite at all, whether the role they named
    is within their own ceiling there, which pending offer a re-issue supersedes,
    who may withdraw it, and where the membership lands when it is accepted.

    It carried no organization before this, and both halves of that were
    wrong at once. An owner acting under a branch's hat issued an offer that
    became a membership at the tenant ROOT — a grant reaching further than the
    context it was sent from, with nothing in the request saying so. And a branch
    admin, who administers a branch and nothing above it, was refused outright,
    because the authority question was asked at a root they hold nothing on. The
    landing node was a constant where it should have been the context.

    The alternative — create the user, then let them set a password — puts a
    row on the user table for somebody who has not agreed to anything, and
    makes "has this person signed up" unanswerable. An invitation is a token
    with an email, a role and an expiry, and it becomes a `Membership` at the
    moment the person actually signs up (`accounts.adapter`).

    Only the SHA-256 of the token is stored, for the same reason `ApiToken`
    does it: the emailed link is a bearer credential, and a leaked database
    should not hand over every outstanding invitation.

    **Acceptance is wired through allauth's `save_user` adapter hook, not a
    signal** (house rule 4). A `post_save` on `User` would be logic hidden
    where nobody looks for it, and it would fire for every user ever created —
    including the ones a test or a management command made.
    """

    #: ADR core-13. An invitation is the record that an offer was MADE, which
    #: is a fact somebody may need to cite long after the offer stopped
    #: standing: it is accepted, revoked or left to expire, and in all three
    #: cases the row remains. It is the one core table that holds a personal
    #: identifier (`email`) for somebody who may never have had an account,
    #: which is why erasure reaches it through
    #: `apps.core.services.redact_invitations` — the ADDRESS leaves, the row
    #: does not.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "the record that an offer was made, and to whom: 'who let this person "
            "in' is a question a dispute turns on, and it is unanswerable from a "
            "deleted row. Expiry is a state (`expires_at` past, status still "
            "pending), never a delete. The personal half is erasable without the "
            "row: `redact_invitations` voids and blanks the address platform-wide."
        ),
        trigger=(
            "2026-08-24 — the first tenant whose invitation table is large enough "
            "to be worth sweeping, or the first jurisdiction that requires the ROW "
            "gone rather than the address; either one turns this into a `purged` "
            "declaration with a callable and a schedule behind it."
        ),
    )

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REVOKED = "revoked", "Revoked"

    email = models.EmailField()
    role = models.CharField(
        max_length=16,
        choices=Membership.Role.choices,
        default=Membership.Role.MEMBER,
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta(OrgScopedModel.Meta):
        verbose_name = "invitation"
        verbose_name_plural = "invitations"
        constraints = [
            # ONE PENDING OFFER PER ADDRESS PER NODE, not per tenant (ADR
            # core-20). Two branches may each have a live offer out to the same
            # person, because they are offers of two different places — and the
            # tenant-wide form made one branch's re-issue silently withdraw
            # another's, which is the same "acting outside your context" the
            # placement law closes at the other end. Accepting both is
            # coherent: `Membership` is unique on person x tenant x
            # organization, so it is two memberships in two branches.
            models.UniqueConstraint(
                fields=["tenant", "organization", "email"],
                condition=models.Q(status="pending"),
                name="invitation_one_pending_per_email_per_org",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.email} to {self.organization_id} as {self.role}"

    @property
    def is_pending(self) -> bool:
        return self.status == self.Status.PENDING
