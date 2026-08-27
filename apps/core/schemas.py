"""The wire shapes core owns. Pydantic, like every other door's.

There are two kinds here and they are deliberately few: `ping`'s answer, and
the **measured number** — a value a door computes and a client must never have
to compute again.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field


def example(value: Any) -> dict[str, Any]:
    """Declare the realistic value this field shows in the API document.

        channel: str = Field(..., json_schema_extra=example("email"))
        amount: Decimal = Field(..., json_schema_extra=example("12.50"))

    **The declaration seam for house rule 41's examples** (the owner's ruling of
    2026-08-24). `apps.core.api.docs` synthesises an example for every field
    that does not use this, from the field's own type — which is always shaped
    right and never *says* anything: a synthesised `channel` is `"channel"` and
    a synthesised `status` is whichever enum member happens to be first. One
    call here replaces that with the value a caller would actually send.

    It returns the `json_schema_extra` mapping rather than a whole `Field`, so
    it composes with everything else a field already declares — a default, a
    constraint, an alias — instead of being a second way to write a field that
    has to grow a parameter every time Pydantic does.

    **Never a real person, a real key or a real customer.** An example is
    published, and an example is copied: `person@example.com`, a reserved
    documentation domain, a token that is visibly a placeholder. The census
    under house rule 41 counts declarations; nothing counts realism, and that
    blind spot is declared there.

    **And never a value a secret scanner cannot tell from a secret.** A
    realistic 64-character digest or a realistic-looking API key is, to
    `detect-secrets`, exactly a leaked one — the full gate failed on
    `WorkflowRunOut.input_digest`'s first example for that reason. Allow-listing
    the finding is the wrong fix twice over, because
    every product cloned from this template inherits the scanner *and* the
    example, and would learn to allow-list its own.

    The fix is to lower the value's **Shannon entropy over its characters**,
    which is what the scanner measures — so use FEW distinct symbols
    (`deadbeef` repeated scores 2.156 against a 3.0 limit), not a repeated
    block of many (four copies of a 16-symbol block still score 4.0, exactly
    what a random digest scores). That distinction cost a full-gate
    run once, which is why it is written down rather than left as "make it look
    fake".
    """
    return {"example": value}


# --- The one seam every request body inherits (SB-1) --------------------------


class StrictIn(Schema):
    """A body a client SENDS. **An unknown field is a refusal, not a shrug.**

    The owner's ruling of 2026-08-24, and it is one line of configuration
    because it has to be exactly one: `extra="forbid"` declared per schema is a
    thing forty schemas can each forget, and the fortieth is the one a customer
    finds.

    **The measured failure it closes.** FT-1′ F6: `POST /webhook-endpoints/`
    with `event_types` — the wrong name for `event_names` — answered **201** and
    handed back a signing secret for an endpoint subscribed to *nothing*.
    Pydantic's default is `extra="ignore"`, so the field the subscriber meant
    reached no column and no answer said so. A healthy status on a request that
    did not do what it said is the worst refusal shape a platform whose callers
    are agents can have: there is no signal to branch on, no error to retry, and
    the discovery happens weeks later as "the webhooks never fired".

    **Requests only, and the asymmetry is deliberate.** An `Out` schema is what
    this server *sends*, and a client that fails on a field it has not seen
    before is a client that breaks every time the product adds a column — so
    responses stay open and additive (Postel's rule, applied at the end that
    can afford it). Strictness is for the direction where silence is
    indistinguishable from success.

    Everything a request schema already declares still works — `from_attributes`
    is simply not one of them, because nothing constructs a request body out of
    a model. A subclass that needs its own `model_config` should extend rather
    than replace:

        class WidgetIn(StrictIn):
            model_config = ConfigDict(**StrictIn.model_config, populate_by_name=True)

    **Who is held to this is not a list.** `apps/core/tests/test_strict_bodies.py`
    derives the population from the live OpenAPI document's `requestBody` refs,
    so a new `In`/`Patch` schema that inherits `ninja.Schema` directly fails by
    name on the day it is added.

    The refusal a violation produces is recomposed by the one mapper into the
    registered `invalid_body` grammar — see `config/api.py::on_schema_validation`.

    **The name is `apps/comms`'s**, kept rather than replaced. That app had
    already written this rule as a `model_validator` for its own management
    door (`StrictIn`, C1b-2), which is where the danger was first measured; what
    the ruling changed is that it is the platform's now and costs one line
    instead of a validator. Keeping the name means the app that was right about
    it first reads as having been promoted rather than overruled — and it ends
    in `In`, which is what the naming grammar (house rule 16) asks of a shape
    that only ever travels inward.
    """

    model_config = ConfigDict(extra="forbid")


class PingOut(Schema):
    """Whether the machine door is open, and whose door it is."""

    ok: bool = Field(json_schema_extra=example(True))
    tenant: str | None = Field(json_schema_extra=example("acme"))
    #: The acting hat — which node of the tenant's tree this token acts as.
    #: An agent that cannot see which hat it is wearing cannot tell a partial
    #: answer from an empty table, so `ping` says.
    org: str | None = Field(default=None, json_schema_extra=example("northern-branch"))


class MeasuredBasisOut(Schema):
    """How a measured number was arrived at: the formula, and what went into it.

    `formula` is a short human-readable string (`"gross - discounts - refunds"`,
    `"closed / opened"`), and `inputs` are the named values it was evaluated
    over. Between them a person can check the arithmetic without a second
    request and without a second implementation.

    **The example below is hand-written, and the arithmetic in it is real.**
    A synthesised one is shaped right and says nothing — `formula` came
    out as `"formula"` and `inputs` as `{}`, which is a published example of a
    basis that explains nothing about a value it does not contain. The one here
    is the same sum `MeasuredOut`'s example resolves, so a reader who checks the
    subtraction gets the answer the sibling field shows.
    """

    formula: str = Field(json_schema_extra=example("gross - discounts"))
    inputs: dict[str, Decimal] = Field(
        json_schema_extra=example({"gross": "1400.00", "discounts": "159.50"})
    )


class MeasuredOut(Schema):
    """A number the server computed, **with its basis attached** (ADR core-7).

        MeasuredOut(
            value=Decimal("1240.50"),
            basis=MeasuredBasisOut(
                formula="gross - discounts",
                inputs={"gross": Decimal("1400.00"), "discounts": Decimal("159.50")},
            ),
        )

    The contract is one sentence: **a number the UI never computes.** The
    alternative — ship the parts and let each door add them up — is how a
    dashboard, an export and an assistant come to disagree about revenue while
    every one of them is reading the same rows. It was honoured 104 times by
    convention in the product this was lifted from, which is a convention
    worth making a type.

    `Decimal`, not `float`, at both levels: house rule 15, and money that
    round-trips through a float is money that stops adding up. Pydantic renders
    a `Decimal` as a **string** in `model_dump(mode="json")` and on the wire, so
    the value that arrives is the value that was computed.

    **The name.** The suffix is the naming grammar's (rule 16) and it is
    accurate: this shape only ever travels outward. ADR core-7 writes it
    `Measured`/`MeasuredBasis` in prose; the classes carry the suffix every
    other schema in the tree carries, which is what keeps rule 16 silent
    without an exemption. See rung W1-R1's report.

    **Enforcement is at criteria-tier, honestly** (ADR core-7): "any endpoint
    returning a computed aggregate" is an open set, and no closed question can
    scope it. The engineering lead's checklist carries the line; there is no
    AST rule pretending to recognise an aggregate, and that blind spot is
    declared rather than disguised.

    **Its own example is hand-written and its arithmetic is real.** The
    synthesised one published `{"value": "value", …}`, which does not validate
    against this very schema — a published example a client cannot paste back is
    an instrument that is wrong about the one thing it exists to show. The value
    below is exactly what `MeasuredBasisOut`'s example evaluates to, and
    `apps/core/tests/test_published_examples.py` recomputes the subtraction
    rather than trusting the two strings to have been typed consistently.
    """

    value: Decimal = Field(json_schema_extra=example("1240.50"))
    basis: MeasuredBasisOut


# --- The tenancy and hierarchy doors' shapes -----------------------------------
# One schema per shape, shared by both doors (architect E1). An MCP tool that
# built its own dict would be a second answer to the same question, and the day
# the two disagree is the day nobody can say which one the product means.


class OrganizationOut(Schema):
    """One node of a tenant's org tree, as both doors return it.

    `path` and `depth` are on the wire because they are what makes the tree
    legible to a client without a second round trip: `depth` says how far down
    this node sits, and `path` sorts a flat list back into tree order. They are
    read-only everywhere — the services own those columns (house rule 24), and
    there is no `In` schema that carries either.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str = Field(json_schema_extra=example("Northern branch"))
    slug: str = Field(json_schema_extra=example("northern-branch"))
    parent_id: UUID | None
    path: str = Field(json_schema_extra=example("0000.0001"))
    depth: int = Field(json_schema_extra=example(1))
    created_at: datetime
    updated_at: datetime


class OrganizationIn(StrictIn):
    """A new node, under a parent the caller names.

    `parent_id` is required and there is no default, deliberately: "create it
    under the root" is a decision, and a create that silently chose the root
    when a client forgot would put a branch in a place nobody asked for.
    """

    parent_id: UUID
    name: str = Field(min_length=1, max_length=255, json_schema_extra=example("Northern branch"))
    slug: str = Field(min_length=1, max_length=255, json_schema_extra=example("northern-branch"))


class OrganizationPatch(StrictIn):
    """A rename, and only a rename.

    The slug is absent on purpose: it is the handle `X-Org` names, so changing
    it silently invalidates every stored header, every bookmark and every
    script. `move` is absent for the opposite reason — it is a verb with a
    workflow behind it, and it has its own route.
    """

    name: str = Field(min_length=1, max_length=255, json_schema_extra=example("Northern branch"))


class OrganizationMoveIn(StrictIn):
    """Where a subtree is going. One field, because that is the whole decision."""

    new_parent_id: UUID


class OrganizationFilter(FilterSchema):
    """The narrowings a client may ask for on the organization list.

    `name` is `icontains` for the same reason the example app's is: "find the
    branch I half-remember" is the real question. `depth` is exact — it is a
    small integer and a range would invite a client to ask for the whole tree
    one level at a time.
    """

    name: Annotated[str | None, FilterLookup(q="name__icontains")] = None
    depth: int | None = None


class MembershipOut(Schema):
    """Who belongs where, and as what.

    `user_email` rather than a nested user shape: a membership answers "which
    person, which branch, which role", and the person's own record is the
    accounts door's business. It is resolved off the related row, which is why
    every list here `select_related`s the user — and why the query pin in the
    tests is what turns a lost `select_related` into a failure rather than a
    slow page.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    user_email: str = Field(json_schema_extra=example("dana@example.com"))
    organization_id: UUID | None
    role: str = Field(json_schema_extra=example("admin"))
    is_default: bool = Field(json_schema_extra=example(True))
    created_at: datetime
    updated_at: datetime


class MembershipIn(StrictIn):
    """A person, a branch, a role.

    The role a caller names is bounded at the write by the granter's own
    ceiling (house rule 29) — this schema carries what was *asked for*, and
    `add_membership` decides whether the asker could have granted it.
    """

    user_id: UUID
    organization_id: UUID | None = None
    role: str = Field(min_length=1, max_length=32, json_schema_extra=example("admin"))
    is_default: bool = Field(default=False, json_schema_extra=example(False))


class MembershipRolePatch(StrictIn):
    """The one column a membership update may move."""

    role: str = Field(min_length=1, max_length=32, json_schema_extra=example("admin"))


class MembershipFilter(FilterSchema):
    """Narrow by role, or by the branch a membership is held on."""

    role: str | None = None
    organization_id: UUID | None = None


class InvitationOut(Schema):
    """An outstanding invitation. **The token is not on this shape.**

    A pending invitation's plaintext token is a bearer credential: whoever holds
    it becomes a member. It is returned exactly once, by the issue route, in
    `InvitationIssuedOut`, and never again by a list or a read — a list route
    that carried it would turn "who have we invited" into "hand me every
    outstanding credential".
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str = Field(json_schema_extra=example("dana@example.com"))
    #: The node this offer was sent from, and the node its membership will land
    #: on (ADR core-20). It is on the shape rather than implied, because "a
    #: place in which branch" is the substance of the offer and a reader who had
    #: to infer it from the sender's hat would be inferring it from something
    #: the response does not carry.
    organization_id: UUID = Field(json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8b30"))
    role: str = Field(json_schema_extra=example("member"))
    status: str = Field(json_schema_extra=example("pending"))
    expires_at: datetime
    accepted_at: datetime | None
    created_at: datetime
    updated_at: datetime


class InvitationIssuedOut(Schema):
    """The one answer that carries the token, at the one moment it exists.

    `invite_member` returns the row and the plaintext together and stores only a
    hash, so this is the only shape in the product that can ever show it. A
    caller that loses it issues a new invitation; there is no route that will
    tell them again, and that is the point.
    """

    invitation: InvitationOut
    token: str = Field(json_schema_extra=example("inv_9c1f2a7b4e6d40f0a1b2c3d4e5f60718"))


class InvitationIn(StrictIn):
    """Who to invite, where, and as what.

    `organization_id` omitted is the ACTING HAT and never the tenant's root
    (ADR core-20): an offer made from a branch is an offer of a place in that
    branch. The door resolves a named id through the hat's own subtree, so a
    node outside it is `not_found` rather than a placement — a caller can only
    ever be surprised narrower.
    """

    email: str = Field(min_length=3, max_length=254, json_schema_extra=example("dana@example.com"))
    organization_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8b30")
    )
    role: str = Field(
        default="member", min_length=1, max_length=32, json_schema_extra=example("member")
    )


class InvitationAcceptIn(StrictIn):
    """The token from the link, and nothing else.

    No tenant, no email, no user id: the token names the invitation and the
    session names the person. A shape that let a caller say who they were
    accepting *as* is the impersonation ADR core-16 keeps off the machine door.
    """

    token: str = Field(
        min_length=1,
        max_length=512,
        json_schema_extra=example("inv_9c1f2a7b4e6d40f0a1b2c3d4e5f60718"),
    )


class InvitationFilter(FilterSchema):
    """Narrow the invitation list by status, the address invited, or the branch."""

    status: str | None = None
    email: Annotated[str | None, FilterLookup(q="email__icontains")] = None
    organization_id: UUID | None = Field(
        default=None, json_schema_extra=example("019654f6-6c1b-7b0e-9e5f-2f6c4d1a8b30")
    )


class TenantSettingsOut(Schema):
    """A tenant's own configuration, as both doors return it.

    `settings` is the free-form half and `timezone`/`locale` are the two the
    template itself reads — they are columns rather than settings keys because
    the product renders dates with them, and a typo in a JSON key would be a
    silently wrong timestamp instead of a refusal.

    **`flags` is deliberately not here.** Feature flags have their own route and
    their own shape, because they resolve against deployment defaults and a
    settings read that folded them in would answer a different question than
    the flags route does.
    """

    model_config = ConfigDict(from_attributes=True)

    name: str
    slug: str
    status: str
    timezone: str
    locale: str
    settings: dict[str, Any]


class TenantSettingsIn(StrictIn):
    """What a caller may change about their own tenant.

    `values` is **merged at the top level**, not replaced — a key set to `null`
    is removed, which is how a client clears one. That is `update_tenant_settings`'s
    grammar and this schema does not invent a second one.

    `name`, `slug` and `status` are absent: a rename is a bigger decision than a
    settings PUT, and status is what `suspend_tenant`/`close_tenant` move.
    """

    values: dict[str, Any] | None = None
    timezone: str | None = None
    locale: str | None = None


class FlagsOut(Schema):
    """Every flag this tenant resolves, and what it resolves to.

    The map is the union of the deployment's declared defaults and the tenant's
    own overrides, so a client sees every flag that exists rather than only the
    ones somebody has touched. `enabled_for` is the one resolver; this shape is
    its answer.
    """

    flags: dict[str, bool]


class FlagIn(StrictIn):
    """Set one flag, or clear the tenant's opinion of it.

    `enabled: null` is **not** `false`. It removes the tenant's override so the
    flag falls back to the deployment default — "we have no opinion" and "we
    say no" are different answers, and a client that could only send a boolean
    could never say the first one.
    """

    enabled: bool | None


# --- The list envelope, for both doors ----------------------------------------
# ONE class, and both doors get the shape from it rather than each declaring it.
# `@paginate` builds `Paged<Out>` by subclassing whatever the paginator names as
# its `Output`, and `apps.core.api.pagination.CursorPagination.Output` is itself
# a subclass of this class — as is every MCP `*Page` below. One declaration,
# reached three ways, which is what makes house rule 17's twins byte-equal by
# construction. A tool has no decorator to give it an envelope, and the fix is
# not a second declaration of the fields.


class ListPage(Schema):
    """The envelope every list answers with, through every door (ADR core-18).

    `items` is widened to `list[Any]` here and narrowed by whoever subclasses
    it, which is exactly what ninja's `@paginate` does when it builds
    `PagedWidgetOut` out of this class at mount time.

    * **`has_more`** — whether another page exists, answered by fetching one row
      more than asked for. No `COUNT` statement is involved, which is the whole
      point: the total used to be charged to every request and is now charged to
      the ones that ask.
    * **`next_cursor`** — the opaque token for the next page, `null` on the last
      one. `has_more: false` and `next_cursor: null` say the same thing twice on
      purpose: a client can branch on either without learning the other.
    * **`count`** — the exact number of matching rows, and **`null` unless
      `include_count=true` was sent**. `null` is "not counted", which is a
      different fact from `0` and is said differently.
    """

    items: list[Any]
    has_more: bool = Field(..., json_schema_extra=example(True))
    next_cursor: str | None = Field(
        ...,
        json_schema_extra=example("eyJrIjpbIjIwMjYtMDgtMjNUMDk6MzA6MDBaIl0sInYiOjF9.p3Qb1w"),
    )
    # Required on the wire even though it is usually `null`: the response ALWAYS
    # carries the key, and a contract that made it optional would let a
    # generated client treat "absent" and "not counted" as two different
    # answers. They are one answer, and it is `null`.
    count: int | None = Field(..., json_schema_extra=example(None))


class OrganizationPage(ListPage):
    """One page of organizations, in the envelope the HTTP list uses."""

    items: list[OrganizationOut]


class MembershipPage(ListPage):
    """One page of memberships, in the envelope the HTTP list uses."""

    items: list[MembershipOut]


class InvitationPage(ListPage):
    """One page of invitations, in the envelope the HTTP list uses."""

    items: list[InvitationOut]
