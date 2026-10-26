"""Membership, and the escalation wall."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser

from apps.core import events
from apps.core.actor import Actor
from apps.core.authz import (
    OWNER_ROLE,
    collection,
    default_role_key,
    effective_permissions,
    may_be_named,
    read_kinds_by_node,
    refusal_sentence,
    require,
    role_declarations,
)
from apps.core.exceptions import Conflict, Forbidden, Invalid, NotFound, as_invalid
from apps.core.models import Membership, Organization, Role, Tenant
from apps.core.schemas import MembershipOut
from apps.core.service import service
from apps.core.services._hub import _landing_node

# --- Membership, and the escalation wall -------------------------------------
#
# THE ROLE KEY, AND WHERE IT IS VALIDATED (ADR core-25). `Membership.role` and
# `Invitation.role` carried `choices` until `0018`, and a `choices` list is
# exactly the wrong instrument for a value with three layers behind it: `owner`
# is the platform's, a declared role is some app's `roles.py`, and a custom role
# is a ROW one tenant owns. The first is a constant, the second is per process,
# the third is per tenant — and a per-process list cannot hold a per-tenant row,
# so a field validating against one would have refused every custom role the
# moment the feature shipped.
#
# So the validation moved here, into the three services that write the column,
# which are the only three places that have a tenant to read the third layer
# with. The belt behind them is the deploy census (`djb.W054` in
# `apps/core/checks.py`), which asks the same question of the rows that are
# already there.


# rule-16: not a capability and not an act — this is the vocabulary RESOLUTION the
# three writers below share, and a verb in front of it would make a lookup read as
# something somebody does. It is public because `MembershipAdmin` builds its role
# field from the same three layers, and a second derivation of "what may this
# tenant name" is exactly the drift this function exists to prevent.
def known_role_keys(*, tenant: Tenant) -> frozenset[str]:
    """Every role key this tenant may name, all three layers at once.

    `owner` (the platform's one role), every key an app declares in a
    `roles.py`, and every `core.Role` row this tenant owns. **Not `""`** — the
    roleless membership is a legal state of the column and is not a key
    anybody names; the one road to it is `add_membership(role="")`, and the
    services that take a role from a caller refuse it by not finding it here.
    """
    return (
        frozenset({OWNER_ROLE})
        | frozenset(role_declarations())
        | frozenset(
            str(key) for key in Role.objects.for_tenant(tenant).values_list("key", flat=True)
        )
    )


def _refuse_unknown_role(*, tenant: Tenant, role: str, allow_roleless: bool = False) -> None:
    """`Invalid` for a role key this tenant cannot name. The replacement for `choices`.

    ANOTHER TENANT'S CUSTOM ROLE IS UNKNOWN HERE, and that is the half a
    constraint could not have given: `Role.objects.for_tenant(tenant)` is the
    scoped read, so a key that exists in a neighbouring tenant reads exactly
    like a typo, which is what it is from this tenant's side.

    The refusal names the field and lists what this tenant may actually say,
    because "that is not a role" with no list is a support ticket — and the list
    is the three layers, which is the shape the caller has to learn anyway.
    """
    if allow_roleless and role == "":
        return
    known = known_role_keys(tenant=tenant)
    if role in known:
        return
    raise Invalid(
        {
            "role": [
                f"{role!r} is not a role in this tenant. It is one of "
                f"{', '.join(sorted(known))} — `owner`, a role an app declares in its "
                "`roles.py`, or one this tenant made for itself."
            ]
        }
    )


# rule-16: not a capability and not an act — a key's display name, the replacement for
# `Membership.Role(value).label`, which was an attribute access and not a verb
# either. Public for the same reason as `known_role_keys` above: the admin and the
# invitation mail must call one another's answer, not two.
def role_label(*, tenant: Tenant, key: str) -> str:
    """What to call a role key in something a person reads.

    The declaration's `name`, a custom `Role` row's `name`, `"Owner"` for the
    platform role, and otherwise the key itself — never a `ValueError`. It
    replaces `Membership.Role(value).label`, which raised for anything outside
    the three constants and would therefore have crashed the invitation mail for
    every custom role the moment one existed.

    A key that resolves to nothing comes back as itself rather than as a blank:
    a message naming `approver` when the role has been deleted is legible, and
    a message naming nothing at all is a bug report.
    """
    if key == OWNER_ROLE:
        return "Owner"
    declared = role_declarations().get(key)
    if declared is not None:
        return declared.name
    row = Role.objects.for_tenant(tenant).filter(key=key).first()
    if row is not None:
        return str(row.name)
    return key


def _placement(*, tenant: Tenant, organization: Organization | None, actor: Actor) -> Organization:
    """The node a grant or an offer lands on (ADR core-20, the placement law).

    The node NAMED, or — when none is — the hat, and never the root: a
    grant comes from where you sent it, and landing somebody at the root instead
    is a grant reaching further than the context it was sent from.

    One function because `add_membership` and `invite_member` had these three
    lines each, character for character, and the placement law is one rule. A
    node belonging to another tenant is `invalid` rather than `not_found`
    because the caller named a row they can see and asked for something
    incoherent with it; the doors resolve ids through the hat's own
    subtree, so a node outside it never reaches here at all.
    """
    where = organization if organization is not None else _landing_node(tenant=tenant, actor=actor)
    if where.tenant_id != tenant.pk:
        raise Invalid({"organization": ["That organization belongs to another tenant."]})
    return where


def _refuse_escalation(
    *,
    actor: Actor,
    tenant: Tenant,
    organization: Organization,
    role: str,
) -> None:
    """**The escalation wall.** Two refusals, and they are different refusals.

    1. **Outside your subtree.** The granter must hold a role on `organization`
       or on one of its ancestors. Holding `owner` of one branch says nothing
       about the branch next door, and a grant that reached sideways would make
       the tree decorative.
    2. **Above your own effective role.** An `admin` may make somebody an
       `admin` or a `member`, never an `owner`. Without this, one admin
       promotes themselves — or a colleague, then asks the colleague — and the
       role system has no ceiling at all.

    **The wall is keyed on the actor's KIND, and that is a re-keying with a
    reason** (ADR core-22, the L1 ruling of 2026-08-26). It used to read
    `granter is None` — and a granter was `actor.user if actor is not None else
    None`, so two very different situations arrived as the same `None`: the
    product acting for itself, and *nobody having been told who was acting*.
    The second is not an altitude, it is a missing argument, and a wall whose
    escape hatch is a parameter somebody forgot is a wall with a hole in the
    shape of forgetfulness.

    So `actor` is required at every call site now, and `kind == "system"` is
    the declared way past: the tenant's own creation, an invitation accepted at
    signup, a management command, a schedule. **A system actor is a named
    audited altitude, never an exemption** — the `AuditEntry` for that grant
    records `actor_kind=system` with no person, which is ADR core-22's third
    actor semantic said out loud, and a reviewer meeting one can tell it from a
    human grant at a glance. An exemption leaves no trace; an altitude does.

    A `human` or `agent` actor carrying no user is refused rather than waved
    through: nobody is authenticated, so there is no ceiling to measure and no
    reason to believe the grant is legitimate.
    """
    _refuse_handing_out(
        actor=actor,
        tenant=tenant,
        organization=organization,
        permissions=collection(tenant, role),
        opening="You may not grant what you do not hold yourself:",
    )


def _missing_sentences(opening: str, missing: frozenset[str]) -> str:
    """The refusal a set comparison can make: the missing keys' own SENTENCES.

    Sentences and never keys, sorted. `widget.approve` is a word for this
    codebase; "You may not approve that widget." is what the person reading the
    refusal is actually short of, and it is already written down — every key in
    the vocabulary carries its own, derived or declared. A key the vocabulary
    does not know cannot reach here (both callers validate first), and
    `refusal_sentence` falls back to a generic line if one ever does.
    """
    return " ".join([opening, *sorted(refusal_sentence(key) for key in missing)])


def _refuse_handing_out(
    *,
    actor: Actor,
    tenant: Tenant,
    organization: Organization,
    permissions: frozenset[str],
    opening: str = "You may not hand out what you do not hold yourself:",
) -> None:
    """**Nobody hands out what they do not hold.** The hand-out rule, as a set.

    `permissions` is what this act would give somebody — a role's whole
    collection, the keys a role gained, the one key a grant names. Every one of
    them must already be in the granter's own effective set **at the node the
    act lands on**, and the difference is the refusal.

    **Why a set and not a rank.** `_refuse_escalation` used to compare
    `rank(role) > rank(held)` over a three-word table. A tenant's own role is a
    fourth word with no rank at all — `rank("approver")` is `0` — so it sorted
    BELOW `member` and everybody could hand it out, whatever its collection
    said. The measured hole on this tree: a plain member holding
    `membership.create` by grant assigned a custom `approver` carrying
    `organization.create`, a key that member does not hold, and the membership
    was written. A set comparison has no such blind spot, because it never asks
    how big a role is — only whether you already hold every piece of it.

    The two altitudes are unchanged from the rank wall and for the reasons ADR
    core-22's L1 ruling gives: `system` is a named audited altitude and passes;
    a `human` or `agent` actor carrying no user is refused, because nobody is
    authenticated and there is no set to measure.

    **When the thing is absent:** an empty effective set at the node is its own
    refusal with its own sentence — the granter is standing outside the subtree
    entirely, and telling them which keys they are short of would describe the
    smaller of two problems.
    """
    if actor.kind == "system":
        return
    granter = actor.user
    if granter is None:
        raise Forbidden(
            "This request resolved nobody, so there is no role of your own to grant "
            "beneath. Sign in, or act as the system."
        )
    held = effective_permissions(granter, tenant, organization, memo=actor)
    if not held:
        raise Forbidden(
            "You hold no role over that part of the organization, so you may not grant one there."
        )
    missing = frozenset(permissions) - held
    if not missing:
        return
    raise Forbidden(_missing_sentences(opening, missing))


def _refuse_taking_back(
    *,
    actor: Actor,
    tenant: Tenant,
    membership: Membership,
    verb: str,
) -> None:
    """**The other half of the wall: what the person being acted _on_ holds.**

    `_refuse_handing_out` bounds what an act *gives*. That is the whole ceiling
    only while the only way to change what somebody may do is to hand them
    something; it is not. An `admin` who may not *grant* `owner` could take the
    owner's hat away instead — remove the row, or set its role to `member` — and
    arrive at the same power by subtraction. So what the target **currently
    holds** at the node their membership sits on is measured against what the
    actor holds there, and anything the target has that the actor does not is
    refused.

    **A set difference, for the reason `_refuse_handing_out` gives.** It used to
    be `rank(membership.role) > rank(held)`, which could only compare three
    words and sorted every custom role below `member`. The set has no such
    blind spot; the refusal names the SENTENCES of what the actor is short of.

    **Four roads reach it and this is the only guard on any of them.**
    `revoke_membership` calls it before a delete (SEC-1's MED-1), `set_role`
    before a role change, and `create_grant`/`delete_grant` before a withhold
    lands or an allow is withdrawn — so the predicate, the sentence and the
    comparison are one thing rather than four that agree today. The demotion
    road used to answer `200` before this guard existed.

    **Parameterised by the verb, where `_refuse_orphaning_the_tenant`
    deliberately is not.** That guard's sentence is a fact about the tenant and
    a remedy, true whichever road asked. This one's sentence names the act it
    refused, and telling somebody they may not *remove* a row when they asked
    to demote it would be a refusal that describes something they never did.
    One template, one word substituted — and the tests string-compare the two
    sentences with the substitution applied, so they cannot drift into two
    grammars.

    **Keyed on `actor.kind`, exactly as `_refuse_escalation` is** and for the
    identical reason (ADR core-22, L1): `system` is the product acting for
    itself and is a named audited altitude the row records, where the old
    `acting_user is None` could not tell that apart from nobody having said who
    was acting.

    **Call it after `_refuse_escalation`, never before.** That wall refuses an
    actor who holds *no* role at the node with its own sentence; without it
    first, this one would quote an effective role of `None` at somebody who is
    simply standing outside the subtree.
    """
    if actor.kind == "system":
        return
    acting_user = actor.user
    if acting_user is None:
        raise Forbidden(
            f"This request resolved nobody, so there is no role of your own to {verb} "
            "beneath. Sign in, or act as the system."
        )
    where = membership.organization
    held_by_them = effective_permissions(membership.user, tenant, where)
    missing = held_by_them - effective_permissions(acting_user, tenant, where, memo=actor)
    if not missing:
        return
    raise Forbidden(
        _missing_sentences(
            f"You may not {verb} somebody who holds what you do not:",
            missing,
        )
    )


@service
def add_membership(
    *,
    user: AbstractBaseUser,
    tenant: Tenant,
    organization: Organization | None = None,
    is_default: bool = False,
    role: str | None = None,
    actor: Actor,
) -> Membership:
    """Put a user somewhere in a tenant's tree.

    **`organization` omitted is the HAT, and never the root** (ADR
    core-20, the placement law; the owner's ruling of 2026-08-24). A grant comes
    from where you sent it: somebody acting under a branch's hat who names no
    node meant that branch, and landing them at the root instead is a grant
    reaching further than the context it was sent from. It used to default to
    the root unconditionally, and both halves of that were wrong at once — an owner
    acting in a branch silently placed people above it, and a branch admin, who
    holds nothing at the root, was refused by the escalation wall for a node
    they never named.

    **With no actor there is no hat, and the root is right.** `create_tenant`,
    the seed command and `accept_invitation` all reach here without one; a
    tenant's first membership is the whole tenant by definition.

    Naming a node explicitly still works and is what a network does: a
    membership at a sub-seller sees that sub-seller and everything under it, and
    nothing else. The door resolves the id through the hat's own subtree, so a
    node outside it is `not_found` rather than a placement.

    At most one membership per user is the default; asking for a second default
    moves the flag rather than tripping the constraint, because "which tenant do
    I land in" is a setting, not an error.

    **The first membership of a tenant is its owner.** Somebody has to be able
    to add the second one, and defaulting the first to `member` produces a
    tenant that nobody — including the person who just created it — can
    administer. An explicit `role` always wins.

    `actor` is the person doing the granting, when there is one, and passing it
    is what turns the escalation wall on (`_refuse_escalation`). Every door
    passes it.
    """
    where = _placement(tenant=tenant, organization=organization, actor=actor)
    if is_default:
        Membership.objects.of(user).filter(is_default=True).update(is_default=False)
    if role is None:
        first = not Membership.objects.for_tenant(tenant).exists()
        # THE FIRST MEMBERSHIP IS STILL THE OWNER, and everybody after it gets
        # whatever role this deployment declared as the default — `member` on
        # the template, `""` in a product that deleted it. `Membership.Role`'s
        # constants are no longer this column's `choices`, so the second half
        # reads the declaration rather than an enum member: a product that
        # renamed its entry-level role would otherwise have got `member`, a key
        # its own `roles.py` no longer holds.
        role = OWNER_ROLE if first else default_role_key()
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=where,
        role=role,
    )
    # THE CAPABILITY, AND IT IS SECOND — behind the escalation wall, not in
    # front of it. Putting somebody in a tenant is `membership.create` at the
    # node it lands on, and until the vocabulary had a key for it this service
    # authorized nothing at all: the wall bounds the role being GRANTED, and
    # for a member granting `member` that comparison is `1 > 1` — false — so a
    # plain member could add people, against this route's own published
    # contract. The wall still speaks first, and deliberately: it is the one
    # that refuses an actor holding NOTHING here, and the one that refuses a
    # request nobody is behind, each with its own sentence saying which.
    # Standing before capability, exactly as `set_role` orders its three.
    require(actor, "membership.create", where)
    # THE KEY, AFTER THE WALL. **Standing is judged before the payload is
    # believed** — the tree's own ruling, pinned in
    # `test_role_ceiling.py`'s
    # `test_a_role_this_product_does_not_know_does_not_get_you_past_the_ceiling`:
    # somebody who holds nothing over this node hears that, and not a spelling
    # lesson about a value they were never entitled to grant anyway.
    #
    # `""` is legal here and only here: a membership that holds nothing beyond
    # its grants is a state the system reaches (`accept_invitation` of an offer
    # that named no role, a deployment with no default declared), and it is
    # never a state a caller asks a door for.
    _refuse_unknown_role(tenant=tenant, role=role, allow_roleless=True)
    membership = Membership(
        user_id=user.pk,
        tenant=tenant,
        organization=where,
        is_default=is_default,
        role=role,
    )
    with as_invalid():
        membership.full_clean()
    membership.save()
    return membership


@service
def set_role(
    *,
    tenant: Tenant,
    membership: Membership,
    role: str,
    actor: Actor,
) -> Membership:
    """Change what somebody may do inside one part of a tenant.

    Audited like every other write, and that is the point: "who made them an
    admin, and when" is the question an incident review opens with. The
    escalation wall applies here exactly as it does to a fresh grant — promoting
    an existing member past your own ceiling is the same act with an extra step.

    **And the ceiling on the role being changed, shared with
    `revoke_membership`.** The wall above bounds the role being *granted*, which
    is only half a ceiling: an `admin` who may not grant `owner` could call this
    with `role="member"` on an `owner` membership instead and take the hat away
    by subtraction — no promotion anywhere, the same result. `revoke_membership`
    has refused that shape since SEC-1's MED-1 ("nobody removes above
    themselves"); this refused nothing until this predicate was shared with it. One predicate —
    `_refuse_taking_back` — one sentence template, one word of it
    changed, because a refusal that said *remove* to somebody who asked to
    demote would describe an act they never attempted.

    **Three walls, in this order, and the order is the point.** The escalation
    wall first: it is the one that refuses an actor holding nothing at this node
    at all, and it is what lets the ceiling quote a role rather than `None`.
    Then the ceiling. Then the ownerless floor, last of the three, because
    telling an `admin` that this is the tenant's last owner would answer a
    question about the owner census for somebody who may not touch the row.
    Planted both ways in `core/tests/test_role_ceiling.py`.

    **And the ownerless floor, shared with `revoke_membership`.** A demotion is
    the other road to a tenant nobody can administer: set the last `owner` to
    `member` and the row is still there, still readable, and there is no longer
    anybody who may invite, promote or close anything. `revoke_membership` has
    refused that state since SEC-1's MED-1; this refused nothing until this guard
    was added here too, and got a `200` instead. One predicate, one sentence —
    `_refuse_orphaning_the_tenant` below, called from both roads, because two
    guards written separately drift and a client that branches on the words
    would get a different answer depending on which road it took.
    """
    # REACH, AND IT IS FIRST (R1-F4): reach before capability. A membership
    # the actor could not have named — another tenant's row, or one in a sibling
    # branch — is `NotFound`, never a wall's sentence: not-there and not-yours are
    # one answer, and a `Forbidden` quoting "no role over that part" about a row
    # they cannot see would confirm the row exists. `revoke_membership` has
    # asked this first since SEC-1's MED-1; this asked it never, so
    # `Membership.objects.get(pk=<another tenant's row>)` + `set_role` wrote
    # that tenant's data (the R1 review's shell sequence).
    if not may_be_named(actor, membership):
        raise NotFound()
    # The escalation wall — a promotion is a grant with an extra step, and the
    # rule is about the role being granted rather than about an object a
    # predicate could inspect. FIRST OF THE WALLS: it is the one that refuses an
    # actor holding nothing at this node, with the sentence that says so.
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=membership.organization,
        role=role,
    )
    # THE CAPABILITY, second: changing what somebody may do here is
    # `membership.update` at the node their membership sits on. Behind the
    # escalation wall for that wall's own reason, and in front of the ceiling so
    # that somebody who may not touch this row at all hears that rather than a
    # sentence quoting the role of the person they reached for.
    require(actor, "membership.update", membership.organization)
    # And the other half of the wall, `revoke_membership`'s own: the role this
    # membership *holds*. Third, never first — `_refuse_escalation` above is
    # what refuses an actor holding nothing here, with the sentence that says
    # so, and this one's sentence quotes the role it found.
    _refuse_taking_back(
        actor=actor,
        tenant=tenant,
        membership=membership,
        verb="demote",
    )
    # THE KEY, AND IT IS THIRD — after both walls and before the floor, which is
    # exactly where the `role in Membership.Role.values` half of the old guard
    # sat. **Standing is judged before the payload is believed**
    # (`test_role_ceiling.py`'s
    # `test_a_role_this_product_does_not_know_does_not_get_you_past_the_ceiling`):
    # an admin reaching for an owner's row hears the ceiling whatever value they
    # put in it, because that answer is about the actor and does not depend on
    # what they sent. And it is BEFORE the floor for the floor's own stated
    # reason — answering `conflict` to a typo would teach a caller that their
    # spelling mistake was a state problem.
    #
    # `""` is refused here: the roleless membership is a state the system
    # reaches through `add_membership`, never one a door sets, and a caller who
    # meant "take one thing away" wants a withhold, not a blank.
    _refuse_unknown_role(tenant=tenant, role=role)
    # THE WRITE, the narrowing kick, the event and the ownerless floor — all
    # four in `_write_role_and_kick`, because the floor now measures the state
    # the write LEAVES and therefore has to sit on the write's own side of the
    # line. The order and the reasons are that function's docstring.
    return _write_role_and_kick(tenant=tenant, membership=membership, role=role, actor=actor)


def _write_role_and_kick(
    *, tenant: Tenant, membership: Membership, role: str, actor: Actor
) -> Membership:
    """Set the role, and hang up on the person if their reads just shrank.

    **Split out of `set_role` so the measurement brackets the write and only
    the write.** `before` is read AFTER the three walls rather than at the top
    of the caller: a refused call must not pay for a comparison nobody will
    make. `after` is read INSIDE the transaction, so the comparison is against
    the row this call actually wrote, and the kick itself is registered on
    commit — a rollback hangs up on nobody.

    Three statements each way whatever the shape of the tree
    (`core.authz.read_kinds_by_node`), and the decision is
    `kick_if_reads_narrowed`'s, which is where the rule is written down.

    **The event and the ownerless floor are here too, and both belong on this
    side of the line.** The event is inside the transaction the write happened
    in (ADR core-26). The floor measures the state the write LEAVES — a caller
    that ran it before the write would be asking about a row that no longer
    exists — so it is the last thing this function does and a `Conflict` from it
    rolls the write back with the service's own transaction.

    **A refused call leaves the caller's instance as it found it.** The
    transaction puts the ROW back; the `Membership` object the caller handed in
    is Python and no transaction reaches it, so a refusal raised after
    `membership.role = role` would hand back an instance claiming a role the
    database never got. Not theoretical tidiness: the next guard the caller runs
    — `revoke_membership`'s floor, which reads `membership.role` — would then
    measure the value of a write that did not happen, and wave through the
    removal of the tenant's last owner.
    """
    previous = str(membership.role)
    before = read_kinds_by_node(membership.user, tenant)
    try:
        membership.role = role
        with as_invalid():
            membership.full_clean()
        membership.save(update_fields=["role", "updated_at"])
        kick_if_reads_narrowed(
            tenant=tenant,
            user_id=membership.user_id,
            before=before,
            after=read_kinds_by_node(membership.user, tenant),
        )
        _publish(
            events.MEMBERSHIP_UPDATED,
            tenant=tenant,
            out=MembershipOut.from_orm(membership),
            actor=actor,
        )
        _refuse_orphaning_the_tenant(tenant=tenant, was_owner=previous == OWNER_ROLE)
    except Exception:
        membership.role = previous
        raise
    return membership


def _refuse_orphaning_the_tenant(*, tenant: Tenant, was_owner: bool) -> None:
    """A tenant with no owner is a tenant nobody can administer. **After the write.**

    The same invariant `apps.accounts.selectors.list_tenants_this_user_alone_owns`
    protects on the erasure path, enforced here because removal is the other
    way to reach the state: no one left who can invite a member, change a role,
    or close it — and nobody notices until they need to do one of those things.

    **It reads the STATE THE CALL LEAVES BEHIND, not the row under the caller's
    hand, and that is the change.** The old guard counted rows whose `role`
    column read `owner` and ran *before* the write, which answered the question
    only while the column was the whole story. It is not: ownership is
    `tenant.own`, a reserved key `owner` alone carries and a `withhold` grant
    can take away. So this asks the question the tenant actually cares about —
    *is there still somebody on the root holding `tenant.own`?* — and asks it
    after the write, inside the service's transaction, so a `Conflict` rolls
    the write back and nothing partial survives.

    **One query, not a resolution per person.** `tenant.own` is reserved: no
    pattern matches it, no `RolePermission` include row may add it and no
    `allow` grant may name it, so `owner` is the only role that carries it and
    the holders are exactly the root memberships with `role = "owner"` and no
    `withhold` of the key. That is the whole algebra, expressed as one
    `exclude(...)` rather than an `effective_permissions` call per membership.

    **On the root, deliberately.** An owner of one branch owns that branch; a
    tenant whose only owner sat under a sub-organization would be a tenant
    nobody could administer at the top, which is the state this refuses. The
    door that can create such an owner is `add_membership` with a node named,
    and it is a legitimate thing to do — this floor simply does not count it.

    **`was_owner` is the trigger, and it is read before the write.** The floor
    refuses a TRANSITION — a tenant that had somebody on top and does not any
    more — never a state it merely found. A tenant with no root owner is a
    legitimate state the system reaches (a tenant mid-setup, a tenant whose tree
    is administered from a branch), and a floor that refused every write in one
    would refuse a demotion that has nothing to do with ownership and cannot
    make anything worse. So the caller says whether the row under its hand was
    an owner, from the value it read before it wrote, and a call that could not
    have removed ownership never asks the question at all.

    Two roads reach it and this is the only guard on either: `set_role` after a
    demotion and `revoke_membership` after a delete, so the code, the sentence
    and the count are one thing rather than two that agree today. The sentence
    reads for both — a demotion *is* the last owner being removed, from
    ownership rather than from the tenant — which is why it is not
    parameterised by the verb.

    **The two services that are NOT callers, said so a reader does not go
    looking.** `create_grant` cannot reach this state: `tenant.own` is reserved,
    so a withhold naming it is `Invalid` before any write. `set_role_collection`
    cannot either: `owner` is refused at its own door, and no other role's
    collection carries the ownership verb. `delete_role` cannot: a role deletion
    names no owner, because `owner` is not a row.
    """
    if not was_owner:
        return
    # Lazily: `core.selectors` imports this module for the root and the key.
    from apps.core.selectors import list_owners_holding_at_root

    if not list_owners_holding_at_root(tenant=tenant).exists():
        raise Conflict(
            "That is the tenant's last owner; promote somebody else before removing them."
        )


@dataclass(frozen=True)
class RevokedMembership:
    """What a withdrawn membership WAS, after the row is gone.

    **A death is exactly what an audit trail exists for** (ADR core-22, the L5
    ruling of 2026-08-26), and `revoke_membership` used to return `None` — so
    the row recording the most consequential act in the hierarchy named no
    object, and the one question a dispute turns on ("whose hat did you take,
    and which one was it") was answerable only from a redacted `input`.

    The pk of a deleted row is still the honest answer to "what did this act on":
    nothing points at it any more, and that is the fact. So `audit_object`
    declares the pair by hand — `core.service._object_of` cannot read it off the
    instance, because there is no instance left to read.

    The person, the branch and the role travel too, because a reader six weeks
    later is asking about a person and a place, not about a primary key.
    """

    membership_id: UUID
    user_id: UUID
    organization_id: UUID
    role: str

    @property
    def audit_object(self) -> tuple[str, UUID]:
        """The `(label, pk)` pair the seam reads. The label is `Membership`'s own."""
        return (Membership._meta.label, self.membership_id)


@service
def revoke_membership(
    *,
    tenant: Tenant,
    membership: Membership,
    actor: Actor,
) -> RevokedMembership:
    """Take somebody's place in a tenant away. **The hat withdrawal.**

    SEC-1's MED-1 found this path missing entirely: nothing outside tests and
    migrations deleted a `Membership`, so the only way to withdraw a person from
    a branch was a raw ORM delete — which is a write outside a service (rule 10),
    skips the escalation wall's mirror image, writes no audit row, and, the
    finding's own point, never reached the person's open sockets.

    **Authorization is ancestor-admin of the node the membership sits on**, the
    same question `add_membership`'s wall asks from the other side and the same
    predicate `organization.create/rename/move` use: taking a hat away is as
    much an administrative act over that branch as handing one out.

    **And a ceiling, mirroring `_refuse_escalation`.** An `admin` may remove an
    `admin` or a `member`, never an `owner`. Without it the wall is decorative:
    an admin who may not *grant* `owner` could simply remove the owner instead,
    which is the same power arriving by subtraction. It lives in
    `_refuse_taking_back` and `set_role` calls it too: the
    demotion road is the same subtraction without the row disappearing, and it
    had no ceiling at all until that predicate was shared.

    **Three refusals, in this order, and the order is the point.**
    `may_be_named` first: a membership in a branch the actor holds no hat over
    is refused `NotFound`, never `Forbidden`, because a refusal that told
    not-there from not-yours apart would confirm that this person holds a
    membership on that branch — rule 26's reachability question, which neither
    tenancy nor the policy asks (the row *is* in the tenant, and the policy is
    about the verb). Then `require`, which is the verb question over a branch
    the actor can already see, so `Forbidden` there reveals nothing. Then the
    ceiling.

    The sockets close on commit (`close_sockets_on_commit`): once the row is
    gone `core.middleware.resolve_org` resolves no hat for this person in this
    tenant, so every org group their connection joined at handshake time is a
    branch they may no longer read — and the connection would have kept
    delivering that branch's full `Out` bodies for its whole life. This is the
    first of MED-1's two real halves.
    """
    if not may_be_named(actor, membership):
        raise NotFound()
    require(actor, "membership.delete", membership.organization)
    _refuse_taking_back(actor=actor, tenant=tenant, membership=membership, verb="remove")
    user_id = membership.user_id
    # Read BEFORE the delete: `membership.pk` is set to None by Django's own
    # `Model.delete()`, so a result assembled afterwards would name nothing —
    # which is the defect this return value closes, arriving by a different road.
    died = RevokedMembership(
        membership_id=membership.pk,
        user_id=user_id,
        organization_id=membership.organization_id,
        role=membership.role,
    )
    was_owner = died.role == OWNER_ROLE
    membership.delete()
    # THE OWNERLESS FLOOR, after the delete for `_refuse_orphaning_the_tenant`'s
    # own stated reason: it reads the state this call leaves behind, and a
    # `Conflict` here rolls the delete back with the whole service transaction.
    _refuse_orphaning_the_tenant(tenant=tenant, was_owner=was_owner)
    close_sockets_on_commit(user_id=user_id, reason=KICK_MEMBERSHIP_REVOKED)
    return died


from apps.core.services.grants import _publish  # noqa: E402
from apps.core.services.sockets import (  # noqa: E402
    KICK_MEMBERSHIP_REVOKED,
    close_sockets_on_commit,
    kick_if_reads_narrowed,
)
