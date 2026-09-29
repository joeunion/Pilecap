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

from dataclasses import dataclass
from typing import Any, ClassVar, Final, TypeVar

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


# The class attribute `Archivable` sets to declare that a noun leaves the book by
# being ARCHIVED. Named once, here, for `APPEND_ONLY_ATTR`'s reason: the mixin
# that declares it, the walk that discovers it, `introspect` that prints it and
# house rule 75 that reads it say the same word.
ARCHIVABLE_ATTR = "archivable"

#: The two columns the mixin brings. `archived_at` is the name `comms` and
#: `files` already carry on their hand-built halves — lifted, never renamed.
ARCHIVED_AT = "archived_at"
ARCHIVED_BY = "archived_by"


def is_archivable(model: type[models.Model]) -> bool:
    """Whether this model declared `Archivable` (`archivable = True`).

    An attribute lookup, as `is_append_only` and `is_inherited_downward` are:
    the declaration is the fact, and it is inherited — a proxy or subclass of an
    archivable noun is archivable, and one that meant otherwise would have to
    say `archivable = False` in its own body, where a reviewer sees it.
    """
    return bool(getattr(model, ARCHIVABLE_ATTR, False))


def archivable_models(*, registry: Any = None) -> list[type[models.Model]]:
    """Every model in the product that declared `Archivable`. **Discovered, never listed.**

    The population the list door's `?show=`, the face's archive road and house
    rules 74 and 75 all ask about. A product adds a noun by declaring the mixin
    on it, in the same commit, with no edit to `core`. `registry` is an app
    registry to ask instead of the global one — a test's `isolate_apps`
    registry, which is how `core` proves the discovery against a planted model.
    """
    from django.apps import apps as django_apps

    source = registry if registry is not None else django_apps
    return [model for model in source.get_models() if is_archivable(model)]


#: What `BaseModel.authz_kind` holds until a model says otherwise: "derive my
#: kind from my class name" (ADR core-25). A sentinel rather than `None`
#: because `None` is the OPT-OUT — a model declaring that it is not a kind at
#: all — and the two have to be tellable apart, or the reason the opt-out
#: demands could never be required of it. The value is deliberately outside the
#: key grammar, so no product can type it by accident and mean something.
AUTHZ_KIND_DERIVED: Final[str] = "*derive*"


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

    # --- The authorization kind (ADR core-25) -------------------------------
    #
    # **A model IS a kind, and a kind carries four verbs.** `core.authz`
    # derives `<kind>.create/read/update/delete` for every first-party concrete
    # model, so a product that adds a model gets its four permissions with no
    # edit to `core` and no list anywhere for somebody to forget. None of these
    # three attributes is a FIELD and none of them migrates: they are read off
    # the class at import, the way `lifecycle` and `inherited_downward` are.
    #
    # The kind is the IMMUTABLE key under a renamable class name: a product
    # that renames `Invoice` to `Bill` sets `authz_kind = "invoice"` and no
    # grant row, no role collection and no product's `require` call breaks.

    #: The kind this model is authorized as. The default says "derive it from
    #: my class name"; a string overrides that; `None` opts the model out of
    #: the vocabulary altogether and then `authz_kind_reason` is required.
    #: `None` and the default have to be tellable apart, which is why the
    #: default is a sentinel rather than `None`.
    authz_kind: ClassVar[str | None] = AUTHZ_KIND_DERIVED

    #: Why this model is not a kind. Required when `authz_kind` is `None`, and
    #: a sentence rather than a marker, because an opt-out is a claim a
    #: reviewer has to be able to disagree with.
    authz_kind_reason: ClassVar[str] = ""

    #: The name of a `CASCADE` foreign key to the aggregate this row belongs
    #: to. An owned child is authorized under its parent's kind — writing a
    #: line of a ledger IS writing the ledger — and the refusal at import when
    #: the named key is not `CASCADE` is what keeps that from being asserted of
    #: a row that outlives its parent and is therefore its own record.
    authz_kind_of: ClassVar[str | None] = None

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

    # --- THE TENANT-ROOT MEMO, AND IT IS A CACHE WITH A DECLARED CONTRACT ----
    #
    # The counterpart, one register down, of the permission memo declared on
    # `core.actor.Actor._permission_rows` — written in the same five clauses and
    # in the same place (on the carrier, beside the slot) so that a reader who
    # has found one finds the other without being told. Two shapes for "resolve
    # this once per request" would be the cost this states instead of paying.
    #
    # * **Source of truth** — the `core_organization` row of this tenant whose
    #   `parent` is NULL. There is exactly one and the DATABASE holds that, not
    #   a service remembering to look (`Organization.Meta`,
    #   `organization_one_root_per_tenant`); `core.services.move_organization`
    #   refuses to move a root, and `Organization.parent` is `PROTECT`ed. So the
    #   row this remembers cannot become a different row, and cannot stop being
    #   the root, while the instance that remembers it lives.
    # * **Key** — this `Tenant` INSTANCE, which is the key and the carrier at
    #   once. A memo on one tenant's instance is unreachable from another's, so
    #   the cross-identity confusion the permission memo needs a gate to refuse
    #   (`core.authz._memo_box`) cannot be expressed here at all.
    # * **TTL** — the instance's lifetime, which is one request, one activity,
    #   one command: a door builds `request.tenant` per request
    #   (`core.middleware`) and hands that one object down to every service it
    #   calls. **Never process-wide and never across requests**, which is why
    #   the slot is a scalar `None` that every fill ASSIGNS over on the
    #   instance: a mutable class attribute would be one box shared by every
    #   tenant in the process, and that is a cache, not a memo.
    #
    #   **One carrier lives longer than that, and the clause is wrong in
    #   letter for it**: a socket holds its `Tenant` for the life of the
    #   CONNECTION, which `apps/realtime/bridge.py` expects to run for hours.
    #   It is harmless in effect only because nothing on that path resolves the
    #   root — `apps/realtime` never calls `root_organization`, so the slot on a
    #   consumer's tenant is never filled — and the source-of-truth clause above
    #   says why it would still be right if it were: the row a tenant's root is
    #   cannot become a different row while the instance lives. Trigger for
    #   revisiting: the first socket path that resolves the root, which is the
    #   day the TTL sentence has to say "or one connection" and mean it.
    # * **Invalidation** — `forget_root()`, and nothing else.
    # * **Failure** — a miss is the one indexed read. A tenant with no root
    #   raises (`core.services.root_organization`) and remembers NOTHING: a
    #   broken database must not become an answer the rest of the request
    #   agrees with.
    # * **Stampede** — none: one instance, one thread, one call chain.
    #
    # **What it does NOT decide.** Whether a tenant-wide read should ask at the
    # root or at the acting hat is open, and this is right under either answer:
    # it makes the resolution happen once per request instead of once per call,
    # and says nothing about which node the question is about.
    _root_organization: Organization | None = None

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

    def remember_root(self, organization: Organization) -> None:
        """Fill the memo from a node the caller is already holding. Else a no-op.

        The other half of "one resolution": a site that has just resolved an
        organization for its own reasons — `core.middleware.resolve_org` reading
        the acting hat, which every door does on every request — hands it here
        rather than letting the request's first tenant-wide read fetch the same
        row again.

        **The test is `parent is None`, and the database is why that is
        enough**: at most one row per tenant can satisfy it
        (`organization_one_root_per_tenant`), so a node that passes both clauses
        IS this tenant's root and there is nothing to take the caller's word
        about. Anything else is silently left alone, exactly as a memo lookup
        about another identity misses rather than answers.
        """
        if organization.parent_id is None and organization.tenant_id == self.pk:
            self._root_organization = organization

    def forget_root(self) -> None:
        """Drop the memoised root; the next question pays the one indexed read.

        The one invalidation. An instance that never asked has nothing to drop,
        which is why this is unconditional rather than guarded.
        """
        self._root_organization = None


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

    # deprecated v2.1 → removed v3.0, and deliberately still here. These three
    # are no longer this field's `choices` — a role is a key now, and two of the
    # three layers behind it are not enum members at all (ADR core-25). What
    # keeps the class is that `owner`, `admin` and `member` are still the
    # template's own roles by those exact names, every fixture and every test in
    # the tree spells them through here, and house rule 41 reads "which roles
    # are privileged" off this body and `is_privileged` below by AST
    # (`quality/checks.py::_privileged_role_words`). Removing it in the same
    # release that moved the validation would have been two changes wearing one
    # migration.
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
    # A ROLE KEY, not an enum member (ADR core-25). The value is `owner`, a key
    # some app declared in its `roles.py`, or the `key` of a `Role` row this
    # tenant owns — three layers behind one string, and only the first is a
    # constant. `choices` came off because two of the three layers are not
    # knowable at import: a per-process list cannot hold a per-tenant row, and a
    # field that validated against one would refuse every custom role a tenant
    # ever made. The validation moved into the three services that write this
    # column (`add_membership`, `set_role`, `invite_member`), which can read the
    # tenant, and the deploy census (`djb.W054`) is the belt behind them.
    #
    # `blank=True, default=""` is the roleless membership: somebody who belongs
    # here and holds nothing beyond what a grant gives them. It is a legal state
    # of the column and never a state a door sets — `set_role` refuses it.
    role = models.CharField(max_length=64, blank=True, default="")

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
        """Owner or admin — the roles that may write without a policy saying so.

        **deprecated v2.1 → removed v3.0.** `core.authz.allows` no longer
        consults it: what a person may do is a COLLECTION now, and two of the
        three layers behind a role key are not these two words. A predicate
        that wants "how much authority here" asks
        `core.authz.holds(actor, "<kind>.<verb>", at=...)`; this stays through
        v2.x because seven un-swept `policies.py` files read it and because
        house rule 41 reads "which roles are privileged" off this body by AST.
        """
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


#: Which archive cut a queryset has chosen. `None` is the default and means "not
#: yet decided": `for_tenant()` decides it as LIVE. The two widenings set it
#: before or after the scope, and it rides every clone so a later
#: `for_tenant()` does not re-narrow a widened read.
ARCHIVE_SCOPE_LIVE = "live"
ARCHIVE_SCOPE_ALL = "all"
ARCHIVE_SCOPE_ARCHIVED = "archived"


class ScopedQuerySet(models.QuerySet[_ScopedT]):
    """A queryset that can only be narrowed to one tenant, never widened.

    `for_tenant(None)` returns nothing. That is the whole fail-closed
    behaviour: an unresolved tenant reads an empty table rather than the
    table.

    **On an `Archivable` noun, `for_tenant()` also leaves archived rows out**:
    the book a person works from is the live one, and every list, search and
    count gets that for free. `including_archived()` and `archived_only()` are
    the only two widenings, and the list door's `?show=archived` is the one
    reader of the second. Neither widens the TENANT or the HAT: they are about
    the archive, never about whose rows these are. **A model that has not
    declared the mixin reads exactly as it always did** — its `for_tenant()`
    SQL is byte-identical, and both widenings refuse on it.
    """

    #: See `ARCHIVE_SCOPE_*`. A class default, copied through `_clone`.
    archive_scope: str | None = None

    def _clone(self) -> ScopedQuerySet[_ScopedT]:
        # `_clone` is Django's private copy seam; django-stubs does not declare it.
        clone: ScopedQuerySet[_ScopedT] = super()._clone()  # type: ignore[misc]
        clone.archive_scope = self.archive_scope
        return clone

    def for_tenant(self, tenant: Tenant | None) -> ScopedQuerySet[_ScopedT]:
        if tenant is None:
            return self.none()
        scoped = self.filter(tenant=tenant)
        if is_archivable(self.model) and self.archive_scope is None:
            scoped = scoped.filter(**{f"{ARCHIVED_AT}__isnull": True})
            scoped.archive_scope = ARCHIVE_SCOPE_LIVE
        return scoped

    def _require_archivable(self, widening: str) -> None:
        if not is_archivable(self.model):
            raise TypeError(
                f"{self.model.__name__} has not declared `Archivable`, so {widening}() "
                "is not legal on it: it has no archived rows to include. A noun joins "
                "the archive by declaring the mixin (apps.core.models.Archivable)."
            )

    def including_archived(self) -> ScopedQuerySet[_ScopedT]:
        """Live AND archived rows — the widening a restore, a detail read or an
        audit read makes. Legal before or after `for_tenant()`; the tenant and
        the hat still narrow it exactly as they did."""
        self._require_archivable("including_archived")
        widened: ScopedQuerySet[_ScopedT] = self.all()
        if widened.archive_scope == ARCHIVE_SCOPE_LIVE:
            widened._drop_live_exclusion()
        elif widened.archive_scope == ARCHIVE_SCOPE_ARCHIVED:
            raise TypeError(
                "archived_only() already chose the archived cut; including_archived() "
                "after it would be a second answer to one question. Ask for one."
            )
        widened.archive_scope = ARCHIVE_SCOPE_ALL
        return widened

    def archived_only(self) -> ScopedQuerySet[_ScopedT]:
        """Archived rows alone — the list door's `?show=archived` cut (exclusive)."""
        self._require_archivable("archived_only")
        narrowed = self.including_archived().filter(**{f"{ARCHIVED_AT}__isnull": False})
        narrowed.archive_scope = ARCHIVE_SCOPE_ARCHIVED
        return narrowed

    def _drop_live_exclusion(self) -> None:
        """Take `for_tenant()`'s `archived_at IS NULL` back out of this clone's WHERE.

        It is a top-level AND clause of the query `for_tenant()` built, and it
        stays one through every `filter()`, `exclude()` and `visible_to()` —
        each of those ANDs a clause beside it. What moves it is an OR
        combination (`qs1 | qs2`), after which it is nested inside the OR and
        removing it would change what the OR means; that refuses rather than
        guesses.
        """
        from django.db.models.lookups import IsNull

        field = self.model._meta.get_field(ARCHIVED_AT)
        where = self.query.where
        if where.connector == "AND" and not where.negated:
            for child in list(where.children):
                lhs = getattr(child, "lhs", None)
                if (
                    isinstance(child, IsNull)
                    and child.rhs is True
                    and getattr(lhs, "target", None) is field
                    and getattr(lhs, "alias", None) == self.query.base_table
                ):
                    where.children.remove(child)
                    return
        raise TypeError(
            f"{self.model.__name__}: including_archived() could not find the live "
            "exclusion for_tenant() added — the queryset was OR-combined (or negated) "
            "after it. Widen before combining: "
            "`Model.objects.for_tenant(t).including_archived().filter(...) | ...`."
        )

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

    def including_archived(self) -> ScopedQuerySet[_ScopedT]:
        return self.get_queryset().including_archived()

    def archived_only(self) -> ScopedQuerySet[_ScopedT]:
        return self.get_queryset().archived_only()


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


class Archivable(models.Model):
    """Declare that this noun leaves the book by being **archived**.

        class Widget(OrgScopedModel, Archivable):
            ...

    **List it AFTER the scoped base.** Django hands a model that declares no
    `Meta` the Meta of the first base that has one; a mixin listed first would
    hand over its own and the noun would silently lose the scoped base's
    ordering and its tenant-leading recency index (house rule 37). The order is
    therefore refused at class definition rather than documented and hoped for.

    **What it brings — two columns and one read discipline, nothing else:**

    * `archived_at` — WHEN, and the whole state (D7: a date, never an
      `is_archived`/`is_active` boolean). The name `comms` and `files` already
      carry, lifted and never renamed.
    * `archived_by` — WHO, a `PROTECT` foreign key to the user (users are kept,
      so an archive can always say whose press it was). `NULL` for a row
      archived by the product acting for itself, or before this column existed.
      No reverse accessor: `related_name="+"`.
    * `ScopedQuerySet.for_tenant()` leaves archived rows out, and
      `.including_archived()` / `.archived_only()` are the only widenings.

    **What it deliberately does NOT bring:** a writer. Archiving and restoring a
    noun is that noun's own service pair — `archive_<noun>` / `restore_<noun>`,
    keyword-only, `tenant` + `actor`, idempotent, `authz.require` →
    `core.policies.may_archive`, over `core.verbs.archive_row` /
    `restore_row`, emitting `<app>.<noun>.archived` / `.restored` inside the
    transaction and never cascading — because a write belongs to the app that
    owns the row (A3), and a generic writer here would be a door outside the
    noun's app. **An archived row's reads answer read-only; its writes other
    than restore refuse `archived`** (`core.verbs.require_live`).

    **Append-only and archivable are disjoint** (D8): a ledger's rows are
    witnessed facts, and hiding one is a rewrite by another name. A model
    declaring both is refused here at class definition, and house rule 75
    refuses the same shape in the source without running it.
    """

    archivable: ClassVar[bool] = True

    # rule-22: an ABSTRACT mixin's fields add no column to core; each declaring
    # noun's own app makes its migration (`makemigrations <app>`), expand-only.
    archived_at = models.DateTimeField(null=True, blank=True)
    # rule-22: the same abstract mixin's second column — no table in core owns it.
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if is_append_only(cls):
            raise TypeError(
                f"{cls.__qualname__} declares both `{APPEND_ONLY_ATTR} = True` and "
                "`Archivable`. They are disjoint (D8): an append-only row is a "
                "witnessed fact and archiving one is a rewrite by another name. A "
                "ledger is superseded by a new row, never archived."
            )
        mro = cls.__mro__
        if BaseModel in mro and mro.index(Archivable) < mro.index(BaseModel):
            raise TypeError(
                f"{cls.__qualname__} lists `Archivable` before its scoped base. List "
                "it after — `class Noun(OrgScopedModel, Archivable)` — or the noun "
                "inherits the mixin's Meta and loses the base's ordering and its "
                "recency index (house rule 37)."
            )

    @property
    def is_archived(self) -> bool:
        """Derived from the date, never stored (D7)."""
        return self.archived_at is not None


# The class attribute `Movable` sets: this noun changes node (and, optionally,
# owner) through the family's move verb.
MOVABLE_ATTR = "movable"


def is_movable(model: type[models.Model]) -> bool:
    """Whether this model declared `Movable` (`movable = True`). Inherited."""
    return bool(getattr(model, MOVABLE_ATTR, False))


class Movable:
    """Declare that this noun can be MOVED — re-homed at another node of the tree.

        class Widget(OrgScopedModel, Archivable, Movable):
            move_owner_field = "owner"

    **A marker, no column**: the row already has its `organization`. What the
    declaration buys is the road (house rule 74: a `<noun>-move` route and its
    twin, `<kind>.move` in the vocabulary) and the one seam every noun's
    `move_<noun>` service calls — `core.verbs.rehome(row, organization)`, which
    moves the row and every MUTABLE row that derives its organization from it
    (`derive_org_from`), in one transaction, and refuses `move_blocked` over an
    APPEND-ONLY derived row: a ledger line is recorded where it was written,
    and rewriting its organization is the update house rule 20 forbids.

    `move_owner_field` names the FK a move may also reassign (the owner axis),
    or `None` when the noun has no owner to hand over.

    `organization_name` is here so an `Out` can say WHERE the row lives in
    words (`core.schemas.HomedOut`) — the record's lede reads a name, never the
    slug; a list that answers it `select_related("organization")`s.
    """

    movable: ClassVar[bool] = True
    move_owner_field: ClassVar[str | None] = None

    @property
    def organization_name(self) -> str:
        """The name of the node this row lives at."""
        return str(getattr(getattr(self, "organization", None), "name", "") or "")


# The class attribute `Versioned` sets: this noun's writes carry the version they
# were made against. Named once, here, for `ARCHIVABLE_ATTR`'s reason.
VERSIONED_ATTR = "versioned"


def is_versioned(model: type[models.Model]) -> bool:
    """Whether this model declared `Versioned` (`versioned = True`). Inherited."""
    return bool(getattr(model, VERSIONED_ATTR, False))


class Versioned:
    """Declare that a write to this noun names the version it was made against.

        class Widget(OrgScopedModel, Archivable, Versioned):
            ...

    **Opt-in, and no column** (the owner's ruling; `architecture.md`'s
    concurrency row: last-write-wins under `select_for_update` by default, an
    optimistic token per noun where the product decides). The version is
    DERIVED from `updated_at` — `BaseModel.updated_at` is `auto_now`, so every
    save that names it moves it — in integer microseconds since the epoch
    (`core.concurrency.version_of`): exact, monotonic under the row lock, and
    below 2**53, so a browser holds it as a plain number.

    **What adopting it demands** — the noun's `Patch` (and `MoveIn`, `MergeIn`)
    carries `version` REQUIRED (`core.schemas.VersionedIn`), its `Out` carries
    it (`core.schemas.VersionedOut`), and its service locks, then calls
    `core.concurrency.require_version(locked, version)` before writing — a
    stale one is `stale_version` (409) naming the current version. House rule
    74 demands the body field; house rule 76 demands that no write to the noun
    leaves `updated_at` where it was (a `save(update_fields=[…])` or a queryset
    `.update(…)` that does not name it), because a write that does not move the
    token is a write the next reader's version cannot see.

    A plain mixin rather than an abstract model: it brings no field and no
    Meta, so it cannot disturb the scoped base's (the reason `Archivable` must
    be listed after it does not arise here).
    """

    versioned: ClassVar[bool] = True

    @property
    def version(self) -> int:
        """The optimistic-concurrency token: `updated_at` in integer microseconds."""
        from apps.core.concurrency import version_of

        return version_of(self)


# The class attribute `Mergeable` sets: two rows of this noun can become one.
MERGEABLE_ATTR = "mergeable"


def is_mergeable(model: type[models.Model]) -> bool:
    """Whether this model declared `Mergeable` (`mergeable = True`). Inherited."""
    return bool(getattr(model, MERGEABLE_ATTR, False))


class Mergeable(models.Model):
    """Declare that two rows of this noun can be MERGED — the loser folded into a survivor.

        class Widget(OrgScopedModel, Archivable, Mergeable):
            merge_keeps = {"entries": "an append-only ledger stays where it was written"}

    **The redirect lives on the loser row** (principle 9: one owner). A merged
    loser is never deleted — a `PROTECT` child or an append-only ledger may
    still name it — so it survives as a tombstone: ARCHIVED (`archived_by` the
    merging person) with `merged_into` naming the survivor. Its reads answer
    read-only; its writes refuse `merged` (`core.verbs.require_live`), naming
    the survivor's detail door.

    **What it demands:**

    * `Archivable` — the loser leaves the book by being archived, so a
      mergeable noun that is not archivable is refused HERE, at class
      definition, before anything could merge it;
    * `merge_keeps` — `{reverse accessor name: reason}` for every foreign key
      into this noun that stays on the loser (an append-only ledger, `PROTECT`
      history). Every OTHER foreign key into the noun is re-pointed by its
      owning app's `merge_repointers.py`; house rule 74's merge clause asks
      the closed question over the ORM's own `_meta.related_objects`.

    One nullable self-FK, `PROTECT`, no reverse accessor. A chain is never two
    hops long: `core.verbs.merge_rows` re-points every earlier loser of the
    loser at the survivor in the same transaction.

    **No unmerge** (principle 6): merge is an administrator's press, confirmed
    twice on the face precisely because it is not undone here.
    """

    mergeable: ClassVar[bool] = True
    merge_keeps: ClassVar[dict[str, str]] = {}

    # rule-22: an ABSTRACT mixin's field adds no column to core; each declaring
    # noun's own app makes its migration (`makemigrations <app>`), expand-only.
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not is_archivable(cls):
            raise TypeError(
                f"{cls.__qualname__} declares `Mergeable` without `Archivable`. A merged "
                "loser leaves the book by being archived (it survives as a tombstone "
                "naming its survivor), so a mergeable noun is archivable first: "
                f"`class {cls.__name__}(OrgScopedModel, Archivable, Mergeable)`."
            )
        mro = cls.__mro__
        if BaseModel in mro and mro.index(Mergeable) < mro.index(BaseModel):
            raise TypeError(
                f"{cls.__qualname__} lists `Mergeable` before its scoped base. List it "
                "after — the noun would otherwise inherit the mixin's Meta and lose the "
                "base's ordering and its recency index (house rule 37)."
            )

    @classmethod
    def lineage(cls, survivor: Any) -> list[Any]:
        """The survivor's pk and every loser's merged into it — for a read that must widen.

        A child a merge KEPT on the loser (`merge_keeps`) still names the loser;
        a survivor's aggregate read that must include it filters
        `<fk>__in=Noun.lineage(survivor)`. One hop is always enough: chains are
        compressed at merge time.
        """
        manager: Any = cls.objects  # type: ignore[attr-defined]
        losers = (
            # rule-24: the losers of one survivor the caller already reached, by
            # primary key only — the survivor's reach is the read's authorization.
            manager.for_tenant(survivor.tenant)
            .including_archived()
            .filter(merged_into=survivor)
            .values_list("pk", flat=True)
        )
        return [survivor.pk, *losers]


# The class attribute `Duplicable` sets: a row of this noun can be saved as new.
DUPLICABLE_ATTR = "duplicable"


@dataclass(frozen=True, slots=True)
class Duplicate:
    """What a duplicate carries across: `copies` from the source, `resets` to the default.

        duplicate = Duplicate(
            copies=("notes", "policy"), resets=("name", "owner", "onboarded_at", "external_ref")
        )

    **Every concrete editable field of the noun is in exactly one of them**, or
    is a platform key the family owns (the id, the tenant, the organization,
    the timestamps, the archive/merge/duplicate columns) — house rule 74's
    duplicate clause is that closed question over `_meta.concrete_fields`, so a
    field added later is refused until somebody decides which side it is on.
    `resets` means the model field's own default (`None` for a nullable field
    without one) — unless the noun's service FILLS it: an owner FK reset to the
    pressing person, a name the copy takes, are the service's
    `duplicate_row(..., fill={...})`, set BEFORE the copy's one save (a NOT NULL
    owner cannot be set after it — the save would already have failed), and the
    copy is validated first, so a clash on a unique constraint is `invalid`.
    """

    copies: tuple[str, ...] = ()
    resets: tuple[str, ...] = ()


#: The unique constraint every duplicable noun declares, by suffix.
DUPLICATE_KEY_CONSTRAINT = "duplicate_key"
#: The system check a duplicable noun without that constraint fails.
DUPLICATE_KEY_CHECK_ID = "core.E001"


def duplicate_key_constraint() -> models.UniqueConstraint:
    """The partial unique constraint a duplicable noun declares in its own `Meta`.

        class Meta(OrgScopedModel.Meta):
            constraints = [duplicate_key_constraint()]

    `(tenant, duplicated_from, duplicate_key)` unique where the key is
    non-empty — a repeated press with one key finds the first copy (the
    exports shape). Named `<app_label>_<model>_duplicate_key` by Django's own
    `%(app_label)s` / `%(class)s` interpolation, so one call serves every noun
    and a copied noun names its own.

    **The constraint is the model's, never the field's.** It used to be added
    by the key field as it was contributed — and a migration renders its model
    STATES into classes too, so a state that did not hold the constraint yet (a
    `CreateModel` the autodetector split an `AddConstraint` out of, which a
    circular foreign key forces) rendered into a table that did, and the
    `AddConstraint` after it failed `DuplicateTable` on a fresh database. A
    constraint the `Meta` declares is one the migration state holds exactly.
    """
    return models.UniqueConstraint(
        fields=["tenant", "duplicated_from", "duplicate_key"],
        condition=~models.Q(duplicate_key=""),
        name=f"%(app_label)s_%(class)s_{DUPLICATE_KEY_CONSTRAINT}",
    )


class DuplicateKeyField(models.CharField):  # type: ignore[type-arg]
    """`duplicate_key`, the caller's idempotency key — and the check that its constraint is there.

    The field adds nothing to the model (`duplicate_key_constraint` says why);
    it only CHECKS: a concrete noun carrying it whose `Meta` does not declare
    `duplicate_key_constraint()` is a system-check error naming the line to
    add. `makemigrations` runs the checks, so the omission is refused before a
    migration is written without it.
    """

    def check(self, **kwargs: Any) -> list[Any]:
        from django.core import checks

        errors: list[Any] = [*super().check(**kwargs)]
        model = getattr(self, "model", None)
        if model is None or model._meta.abstract:
            return errors
        meta = model._meta
        wanted = f"{meta.app_label}_{meta.model_name}_{DUPLICATE_KEY_CONSTRAINT}"
        if not any(c.name == wanted for c in meta.constraints):
            errors.append(
                checks.Error(
                    f"{model.__name__} declares `Duplicable` and its `Meta` does not declare "
                    f"the duplicate key's constraint `{wanted}`: add "
                    "`duplicate_key_constraint()` (apps.core.models) to its "
                    "`Meta.constraints`. The constraint is the model's, never the field's — "
                    "a constraint a field adds is one a migration state does not hold.",
                    obj=model,
                    id=DUPLICATE_KEY_CHECK_ID,
                )
            )
        return errors


def is_duplicable(model: type[models.Model]) -> bool:
    """Whether this model declared `Duplicable` (`duplicable = True`). Inherited."""
    return bool(getattr(model, DUPLICABLE_ATTR, False))


class Duplicable(models.Model):
    """Declare that a row of this noun can be DUPLICATED — saved as a new row.

        class Widget(OrgScopedModel, Archivable, Duplicable):
            duplicate = Duplicate(
                copies=("notes", "policy"),
                resets=("name", "owner", "onboarded_at", "external_ref"),
            )

            class Meta(OrgScopedModel.Meta):
                constraints = [duplicate_key_constraint()]

    **Two columns, a constraint and a declaration.** `duplicated_from` names the source
    (`SET_NULL`: lineage is a courtesy, not a claim — the source may be
    purged); `duplicate_key` is the caller's idempotency key, unique per
    `(tenant, duplicated_from)` when non-empty, so a retried press answers the
    FIRST copy rather than a second one — by the constraint the noun declares
    in its OWN `Meta` (`constraints = [duplicate_key_constraint()]`; a
    duplicable noun without it fails `core.E001`). `duplicate` says which fields copy and
    which reset (`Duplicate`); the seam every noun's `duplicate_<noun>` calls is
    `core.verbs.duplicate_row`, which also copies the owned children the
    declaration lists and NEVER an append-only one (a ledger is the source's
    history, not the copy's).

    A duplicate IS a create: the noun's service asks `<noun>.create` at the
    acting hat, where the copy lands (ADR core-20), and reach on the source.
    """

    duplicable: ClassVar[bool] = True
    duplicate: ClassVar[Duplicate] = Duplicate()

    # rule-22: an ABSTRACT mixin's field adds no column to core; each declaring
    # noun's own app makes its migration (`makemigrations <app>`), expand-only.
    duplicated_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # rule-22: the same abstract mixin's second column — no table in core owns it.
    duplicate_key = DuplicateKeyField(max_length=200, blank=True, default="")

    class Meta:
        abstract = True

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        mro = cls.__mro__
        if BaseModel in mro and mro.index(Duplicable) < mro.index(BaseModel):
            raise TypeError(
                f"{cls.__qualname__} lists `Duplicable` before its scoped base. List it "
                "after — the noun would otherwise inherit the mixin's Meta and lose the "
                "base's ordering and its recency index (house rule 37)."
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
    # The role key this offer names, validated by `invite_member` against the
    # tenant's own three layers rather than by `choices` — see
    # `Membership.role`, which this column becomes at acceptance. A key that
    # stopped existing between the offer and the click is a `Conflict` at
    # `accept_invitation`, not a 500 from an enum lookup.
    role = models.CharField(max_length=64, blank=True, default="")
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


# --- The three permission tables (ADR core-25) ---------------------------------
#
# **Three layers, one owner each.** `owner` is the platform's and is the whole
# vocabulary; a declared role is an app's `roles.py` and is code; a tenant's own
# roles, its deltas on the declared ones, and one person's exceptions are ROWS,
# and these are those rows. Nothing below stores a permission the code layer
# already knows: a `RolePermission` is a DIFFERENCE from a declared collection,
# and a `Grant` is a difference from a membership's collection.
#
# Every one of them is read inside `core.authz` and written by a `core` service.
# A door never touches them, which is what makes "who gave this person this
# capability, and when" answerable from `AuditEntry` alone.


class Role(TenantScopedModel):
    """A role one tenant made for itself, named by a key nobody else uses.

    The third layer. `owner` is the platform's one role and `admin`/`member` are
    the template's declarations in `apps/core/roles.py`; a tenant that needs
    "Approver" makes one of these, and its collection is assembled entirely out
    of `RolePermission` rows — a custom role starts empty and holds exactly what
    somebody put in it.

    **`key` is the immutable half and `name` is the renamable one** (§D10): a
    membership, an invitation and every delta row join on the key, so a tenant
    that decides "Approver" should read "Reviewer" changes `name` and nothing
    else has to be rewritten. `create_role` refuses a key that collides with
    `owner`, with a declared role or with a reserved permission — a collision
    against code is a service rule rather than a constraint, because the code
    layer is not a table the database can join against.

    Unique PER TENANT and not per node: reshaping a role for one branch is a
    withhold on that branch's membership or a second role assigned there, not a
    third copy of the role. `Role(OrgScopedModel)` resolved through `governing()`
    was rejected — it is a tree walk on every `require`.
    """

    #: A tenant's own role vocabulary is small, deliberate and referenced by key
    #: from three other tables; it dies only when somebody deletes it, and
    #: `delete_role` refuses while any membership or pending invitation still
    #: names the key.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a tenant's own role vocabulary. There is no sweeper and none is wanted: a "
            "role nobody deleted is a role somebody still hands out, and the rows that "
            "join to it — memberships, pending invitations, deltas — join on the KEY, so "
            "a swept row would silently empty a collection rather than free anything."
        ),
        trigger=(
            "2026-09-14 — the first tenant whose retired roles are worth archiving rather "
            "than deleting buys an `archived_at` column and a `list_roles` filter then, "
            "and this becomes a bounded declaration with the sweep behind it."
        ),
    )

    key = models.SlugField(max_length=64)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "role"
        verbose_name_plural = "roles"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "key"],
                name="role_unique_key_per_tenant",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.key})"


class RolePermission(TenantScopedModel):
    """One tenant's difference of opinion with a role's collection.

    `include` adds a permission to a role; `exclude` takes one away. On a
    DECLARED role both are legal and the row is a delta on what the code says;
    on a CUSTOM role only `include` is — there is nothing to subtract from, and
    `create_role_permission` refuses the other shape rather than storing a row
    that can never do anything.

    **`role_key` is a string and not a foreign key, on purpose.** Two of the
    three role layers are code: `owner` is the platform's and a declared role
    lives in an `apps/<x>/roles.py`, so half the keys this column names have no
    row to point at. The join is the key, exactly as it is on `Membership.role`,
    and the belt that catches a key naming nothing is the deploy census
    (`djb.W054`), not a constraint.

    **NOT A KIND OF ITS OWN, and the opt-out is the declaration** (§D10, rule
    54 (a)'s sanctioned shape). Editing a role's collection is editing the role:
    these rows are authorized under `role.update`, there is no second thing here
    for anybody to be given a capability over, and a derived `role_permission`
    kind would put four keys in the vocabulary that no door will ever ask for.

    The other two spellings do not fit, and both were tried:
    `authz_kind_of = "role"` names a `CASCADE` foreign key to the aggregate, and
    this model has none by design — see the paragraph above. `authz_kind =
    "role"` is refused at boot by `core.authz.kind_registry_of`, which reads a
    declared kind another model already owns as a COLLISION (`core.Role and
    core.RolePermission both claim the authorization kind 'role'`) and cannot
    tell an alias from a mistake. The opt-out says the same thing in the one
    grammar the registry has: this model is not a kind, and the sentence says
    why.
    """

    authz_kind: ClassVar[str | None] = None
    authz_kind_reason: ClassVar[str] = (
        "a delta on a role's collection, authorized under `role.update` and never on its "
        "own. No door reaches one of these rows except through the role it belongs to, and "
        "a `role_permission.*` key would be four permissions nobody could be given a "
        "reason to hold: the thing you are given authority over is the role."
    )

    #: A delta outlives every row that made it relevant: a tenant that excluded
    #: `invoice.delete` from `admin` two years ago is still excluding it, and
    #: the fact that nobody currently holds `admin` says nothing about that.
    #: Custom-role rows die with `delete_role`, which is a cascade in the
    #: service rather than in the schema — the key is not a foreign key.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a tenant's standing delta on a role's collection. It is a decision, not an "
            "event: it applies to whoever holds the role today and to whoever holds it "
            "next year, so there is no age at which a row of this table has stopped "
            "meaning anything. `delete_role` removes a custom role's rows with it."
        ),
        trigger=(
            "2026-09-14 — the first product that retires a DECLARED role from its "
            "`roles.py` and wants the deltas naming it swept; that sweep is a management "
            "command over `role_key not in role_declarations()`, and it buys the count."
        ),
    )

    class Effect(models.TextChoices):
        INCLUDE = "include", "Include"
        EXCLUDE = "exclude", "Exclude"

    role_key = models.CharField(max_length=64)
    permission = models.CharField(max_length=255)
    effect = models.CharField(max_length=8, choices=Effect.choices, default=Effect.INCLUDE)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "role permission"
        verbose_name_plural = "role permissions"
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "role_key", "permission"],
                name="rolepermission_unique_per_role",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.effect} {self.permission} for {self.role_key}"


class Grant(TenantScopedModel):
    """One permission handed to, or taken from, one person in one place.

    The bottom layer, and the one an administrator reaches for when a role is
    the wrong size for one person: `allow` gives this membership a capability
    its role does not carry, `withhold` takes one away that it does. A withhold
    beats an allow and beats every role — "forbid overrides permit" — because
    the alternative is a subtraction somebody can undo by being given something.

    **It hangs off the MEMBERSHIP and not off the person**, which is what makes
    it positional: the same person holds a different set of exceptions in the
    branch they run and in the branch they merely belong to, and a grant on the
    user would have no answer to "where". `CASCADE` says the rest — an exception
    to a membership that no longer exists is not an exception to anything, and a
    row that outlived its membership would come back to life the day somebody
    was re-added.
    """

    #: BOUNDED, and the cascade IS the lifecycle (ADR core-13's shape): a grant
    #: dies with its membership, which dies with the person or the tenant. There
    #: is no sweeper, because a grant nobody revoked is an exception somebody
    #: still means.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    class Effect(models.TextChoices):
        ALLOW = "allow", "Allow"
        WITHHOLD = "withhold", "Withhold"

    membership = models.ForeignKey(
        Membership,
        on_delete=models.CASCADE,
        related_name="grants",
    )
    permission = models.CharField(max_length=255)
    effect = models.CharField(max_length=8, choices=Effect.choices, default=Effect.ALLOW)

    class Meta(TenantScopedModel.Meta):
        verbose_name = "grant"
        verbose_name_plural = "grants"
        constraints = [
            models.UniqueConstraint(
                fields=["membership", "permission"],
                name="grant_unique_permission_per_membership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.effect} {self.permission} to {self.membership_id}"
