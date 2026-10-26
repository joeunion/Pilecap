"""Invitations."""

from __future__ import annotations

import hashlib
import secrets

from django.contrib.auth.base_user import AbstractBaseUser
from django.urls import reverse

# rule-25: invitation mail is core's own; core may not import the comms app (rule 7)
from apps.core import bridge, mail
from apps.core.actor import Actor, system_actor
from apps.core.authz import default_role_key, may_be_named, require
from apps.core.exceptions import Conflict, Invalid, NotFound, Remedy, as_invalid
from apps.core.ids import uuid7
from apps.core.models import Invitation, Membership, Organization, Tenant
from apps.core.service import service
from apps.core.services._hub import INVITATION_DAYS, INVITATION_TOKEN_BYTES, log
from apps.core.surfaces import absolute_url, surface_for_role
from apps.core.time import in_days, is_past, now
from apps.core.types import Swept

# --- Invitations -------------------------------------------------------------


def hash_invitation_token(plaintext: str) -> str:
    """The stored form of an invitation token. Not a service: a pure function."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# Where an invited person is sent to get their account. **The login page, not a
# signup page** (ADR ident-4): the identity platform hosts every
# interactive authentication, so signing up and signing in are one act — they
# follow this link, sign in there, and `accounts.adapter` turns the invitation
# they were sent into the membership it names.
#
# `account_signup` used to be here and no longer exists as a URL at all
# (`SOCIALACCOUNT_ONLY` removes it), so this is not a preference: reversing the
# old name raises. The mail context key keeps its own name — it still says what
# the link is *for*, and two templates and their tests read it.
INVITE_LANDING_URL = "account_login"

# The run that makes the invited person real, named as a string because `core`
# may not import the app that defines it (`apps.accounts.workflows`) — the same
# inversion `MOVE_ORGANIZATION_WORKFLOW` above and `core.mail`'s
# `SEND_EMAIL_WORKFLOW` are, and it arrives the same way, through `core.bridge`.
#
# It replaces the bare `core.mail.send_mail` this service used to call, and the
# email still goes out through exactly that mailer: the run's second activity is
# `apps.workflows.activities.send_email`, which is the activity `send_mail`
# starts. What changed is that the message now waits for the link.
PROVISION_INVITED_PERSON_WORKFLOW = "ProvisionInvitedPersonWorkflow"


# --- `invite_member`, and what happens after the row ---------------------------
#
# Out here rather than in the docstring for the reason `redact_invitations`
# gives at its own block: the docstring is inside the function and
# `service_function_length` counts it (quality/budgets.yaml). None of this is
# about the arguments, so none of it is what a caller reads first.
#
# **The person is provisioned, not just emailed** (ADR accounts-1).
# The row used to be written and a message sent pointing at a login page with no
# form, on a deployment with no door that creates a person: the invitation was
# actionable by a script and a dead end for the human it was addressed to. The
# commit now starts `ProvisionInvitedPersonWorkflow`, which makes them a
# credential-less account in the identity platform, mints the code that lets them
# set their own password, and only then sends the message — through the same
# `core.mail`-shaped payload and the same `send_email` activity as before, so
# rule 25's one sender is unchanged.
#
# **Started, not done, and deferred to commit.** The visibility row is written
# inside the service's transaction and the Temporal call is registered on
# `transaction.on_commit`, so an invitation that rolls back provisions nobody and
# emails nobody, and an identity platform that is down costs a retry rather than
# the write. The workflow id is keyed on the invitation's primary key, which is
# what makes a retried service start one run and not two — and, because "invite
# them again" creates a *new* invitation row, it is also what lets a resend
# actually resend.
#
# **The message still carries none of OUR credentials**: the `plaintext`
# invitation token goes to the caller and never into a payload, because
# `accounts.adapter` joins the membership from the address at sign-in and a
# bearer token of ours in a workflow argument would sit in Temporal's history for
# as long as retention says. What the run *does* put in history is Zitadel's
# invite code, inside the link — a different kind of thing, and ADR accounts-1 is
# where that difference is argued rather than assumed: it is single-use,
# short-lived, superseded by re-issuing, and it opens exactly one screen, the one
# where a person with no password chooses one. It confers no membership; the row
# still does.


def _invited_role(*, tenant: Tenant, role: str | None) -> str:
    """The role key an offer names: the caller's, or whatever a new member gets.

    A function and not a default argument, because a default argument is
    evaluated at import and the role declarations are discovered after the apps
    load. `None` and `""` are different answers and a reader has to be able to
    tell them apart: `None` is "whatever this deployment gives a new member",
    `""` is an offer of a place and no role — which is what a deployment
    declaring no default role has to make, and is refused otherwise.

    The validation is here, before the wall, and not after it as `set_role`'s
    is: the ordering `set_role` keeps is pinned by a test about the CEILING on a
    role somebody already holds, and an invitation has no such row to be above.
    An unknown key here is a malformed offer, and saying so first is the cheaper
    answer.
    """
    resolved = default_role_key() if role is None else role
    _refuse_unknown_role(tenant=tenant, role=resolved, allow_roleless=not default_role_key())
    return resolved


@service
def invite_member(
    *,
    tenant: Tenant,
    email: str,
    role: str | None = None,
    organization: Organization | None = None,
    invited_by: AbstractBaseUser | None = None,
    expires_in_days: int = INVITATION_DAYS,
    actor: Actor,
) -> tuple[Invitation, str]:
    """Offer somebody a place in a tenant. Returns the row and the token, once.

    The token is returned rather than stored, exactly as an API token is: what
    goes in the email is a bearer credential, and a leaked database should not
    hand over every outstanding invitation. Losing it means reissuing.

    **The invitation records where it was sent from** (ADR core-20, the
    placement law). `organization` omitted is the HAT and never the
    tenant's root: an offer made from a branch is an offer of a place in that
    branch. That node is written on the row, and it is where every authority
    question about this offer is asked — may you invite here at all, is the role
    you named within your own ceiling here, which standing offer does this
    supersede, and where does the membership land when it is accepted.

    A pending invitation for the same address **at the same node** is superseded
    rather than refused — "invite them again" is what somebody clicks when the
    first email went to spam, and answering that with a constraint error is a
    support ticket. Superseding tenant-wide, which is what this did until the
    placement law, let one branch silently withdraw another branch's standing
    offer to the same person.

    The person is provisioned rather than merely emailed, and the run that does
    it starts on commit — see the block above this function for both, and for
    why the message carries none of our own credentials.
    """
    # The escalation wall applies to an invitation exactly as it applies to a
    # grant, because that is what an invitation is: a grant with a delay. An
    # admin who could invite an owner would be an admin who becomes an owner as
    # soon as they use a second email address.
    #
    # BOTH QUESTIONS ARE ASKED AT THE LANDING NODE (ADR core-20). They were
    # asked at the tenant's ROOT before, and that was wrong in two
    # directions at once: it refused a branch admin for a node they never named,
    # and it let everybody else place an invitee above the hat they were acting
    # under. Two questions, and the wall below only ever asked one of them: "may
    # you grant THIS ROLE" is a ceiling, and it lets a member invite a member.
    # `require` asks whether you may invite anybody at all.
    where = _placement(tenant=tenant, organization=organization, actor=actor)
    role = _invited_role(tenant=tenant, role=role)
    # `system` is the declared altitude, not an actor nobody supplied (L1).
    if actor.kind != "system":
        require(actor, "invitation.create", where)
    # The wall measures the ACTOR, not `invited_by` (ADR core-22, L1). Both
    # doors pass `invited_by=actor.user`, so they were the same person all
    # along; keying on the actor is what lets `kind == "system"` be the one
    # declared way past, and `invited_by` goes back to being what it is — the
    # column this invitation records.
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=where,
        role=role,
    )
    address = email.strip().lower()
    # Superseded AT THIS NODE, never tenant-wide: two branches may each have a
    # live offer out to one person, because they are offers of two places.
    #
    # BOTH NARROWINGS, and neither is redundant. `visible_to(where)` is house
    # rule 24's seam — the caller cannot withdraw an offer standing outside
    # their own reach, whatever else this filter says — and `organization=where`
    # is the exact node, because `visible_to` is a SUBTREE read and superseding
    # a subtree would let a re-issue at a parent silently withdraw a child
    # branch's standing offer, which is the same "acting outside your context"
    # this guard closes at the other end.
    Invitation.objects.for_tenant(tenant).visible_to(where).filter(
        organization=where, email=address, status=Invitation.Status.PENDING
    ).update(status=Invitation.Status.REVOKED, updated_at=now())

    plaintext = secrets.token_urlsafe(INVITATION_TOKEN_BYTES)
    invitation = Invitation(
        tenant=tenant,
        organization=where,
        email=address,
        role=role,
        token_hash=hash_invitation_token(plaintext),
        expires_at=in_days(expires_in_days),
        invited_by_id=invited_by.pk if invited_by is not None else None,
    )
    with as_invalid():
        invitation.full_clean()
    invitation.save()

    _provision_invited_person(tenant=tenant, invitation=invitation, invited_by=invited_by)
    return invitation, plaintext


def _provision_invited_person(
    *,
    tenant: Tenant,
    invitation: Invitation,
    invited_by: AbstractBaseUser | None,
) -> None:
    """Ask for this invitation's person to be made real, and mailed a live link.

    **Not a service and deliberately not one**: it writes nothing of ours, it is
    private to this module, and it always runs inside the transaction of the
    `@service` that called it — the same shape as `accounts.services`'
    `_start_identity_sync`, for the same reason. It is a function rather than
    six more lines inside `invite_member` because the workflow's name, its
    argument shape and the four segments of its id are one contract, and a
    contract is easier to read when it is not wrapped in an escalation check.

    **The start goes through `core.bridge`, not through an import.**
    `apps.accounts` sits above `core`, so naming its workflow module here would
    be the upward import the layer contract exists to refuse.
    """
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    build_id = bridge.get(bridge.WORKFLOW_ID)
    start(
        workflow=PROVISION_INVITED_PERSON_WORKFLOW,
        arg={
            "invitation_id": str(invitation.pk),
            "email": invitation.email,
            # `message_for` is `core.mail`'s own function, so the shape that
            # crosses the boundary has one author and one test — the run's
            # second activity is the very `send_email` this mailer has always
            # started, and rule 25's allow-listed path is the path the message
            # still travels.
            "message": mail.message_for(
                to=[invitation.email],
                subject=f"You have been invited to {tenant.name}",
                template="invitation",
                context={
                    "tenant_name": tenant.name,
                    "email": invitation.email,
                    # `role_label`, never `Membership.Role(value).label`: the
                    # enum holds three keys and a tenant may have made a fourth,
                    # so the old form raised `ValueError` inside the activity
                    # that sends the mail — a custom role's invitation would
                    # have failed to send with a stack trace and no message.
                    "role": role_label(tenant=tenant, key=invitation.role),
                    "invited_by": (
                        getattr(invited_by, "email", "") if invited_by is not None else ""
                    ),
                    # On the host of the surface the invited ROLE belongs to, so a
                    # customer's link lands on the customer address and a staff
                    # member's on the staff one — the one URL seam, never a base
                    # typed here.
                    "sign_in_url": absolute_url(
                        path=reverse(INVITE_LANDING_URL),
                        surface=surface_for_role(invitation.role),
                    ),
                    # Rendered here rather than in the template: the template is
                    # replayed by a worker with no request and no tenant timezone, and
                    # a date that formats differently on a retry is a message that
                    # differs from the one the test asserted on.
                    "expires_on": invitation.expires_at.date().isoformat(),
                },
            ),
        },
        tenant=tenant,
        user=invited_by,
        # House rule 18, and the reason this service can be retried: the key is
        # the invitation's primary key, so a retried `invite_member` starts one
        # run and not two — and "invite them again", which makes a NEW row,
        # genuinely re-sends.
        id=build_id(tenant=tenant, app="accounts", noun="invite", key=str(invitation.pk)),
    )


def _refuse_a_role_that_stopped_existing(*, tenant: Tenant, invitation: Invitation) -> None:
    """The role an offer named may be gone by the time somebody clicks the link.

    A role is a KEY now and two of its three layers can be withdrawn — a tenant
    deletes a custom `Role` row, a product removes a declaration from its
    `roles.py` and deploys — while this row goes on naming it. Landing the
    membership anyway would put somebody in a tenant holding a role that
    resolves to nothing, which reads to them as a broken account and to an
    administrator as a person who is simply there.

    **`Conflict` and not `Invalid`**: the request is perfectly well-formed and
    the accepter chose none of this. The state changed underneath an offer they
    were handed, and the remedy is somebody re-issuing it — which is what the
    sentence says, because "invalid role" would tell the one person in this
    exchange who typed nothing that they typed something wrong.

    `""` is not this case: an offer that named no role is an offer of a place
    and nothing more, and that is a membership `add_membership` writes.
    """
    if invitation.role == "" or invitation.role in known_role_keys(tenant=tenant):
        return
    raise Conflict(
        "The role this invitation named no longer exists in this organization, so there "
        "is nothing for it to make you. Ask whoever invited you to send a new one.",
        remedies=(Remedy("Ask for a new invitation", "self:invitation"),),
    )


@service
def accept_invitation(
    *,
    tenant: Tenant,
    # reach: the person accepting holds no membership yet — that is what the
    # invitation is FOR — so there is no hat `may_be_named` could measure this
    # row against, and asking would fail closed on every legitimate acceptance.
    # What names the row is the TOKEN: the caller proves reach by holding a
    # single-use secret whose hash is on the row, which is a stronger claim than
    # a subtree read, and the door looks it up by that hash and nothing else.
    # The placement is not the accepter's to choose either — it was decided by
    # whoever invited them, bounded by what THEY could reach (ADR core-20).
    invitation: Invitation,
    user: AbstractBaseUser,
    actor: Actor,
) -> Membership:
    """Turn a pending invitation into a membership.

    **`actor` is required, and it is the invitee** (ADR core-22, the L2 ruling
    of 2026-08-26). Until it existed this row recorded `kind=system` with no
    person — and for an act a person unambiguously performed that is not an
    absence, it is a FALSE STATEMENT: somebody clicked a link in an email and
    the trail said the product did it to itself. The REST door passes
    `actor_from_request(request)`; the arrival path in `accounts.adapter` builds
    `actor_for(user=<the person arriving>, kind="human")`, because at that
    instant there is a person and no request.

    # authz: the TOKEN is the authorization, and it is a stronger claim than
    # any predicate could make here — the caller proved reach by holding a
    # single-use secret whose hash is on the row, and the doors look the row up
    # by that hash and nothing else. A `require` would have to ask a question
    # about a membership the accepter does not have yet, which is what the
    # invitation is FOR, so it would fail closed on every legitimate
    # acceptance. The actor is kept for the audit row (rule 13's valve shape).

    Called from `accounts.adapter` when a person arrives — **not from a signal**
    (house rule 4). A `post_save` receiver on `User` would be logic hidden where
    nobody looks for it, and it would fire for every user a test or a management
    command ever created.

    **The third refusal is the one somebody actually hits**: a person
    who is already in this part of the tenant clicking the invitation link
    again. The row `add_membership` would write collides with the unique
    constraint, `full_clean()` turns that into Django's own
    `ValidationError` under the `__all__` key, and the door answered
    **400 `invalid`** with the sentence *"Membership with this User, Tenant and
    Organization already exists."* — three table names, a framework key, and a
    status code saying the request was malformed when it was perfectly
    well-formed and simply already true. It is a `Conflict`, it is said in
    words, and it is checked here rather than caught below because a service
    that knows the answer should not be finding it out from a constraint.

    A tenant that is not active lands nobody, and the row is judged
    under its lock: of two acceptances of one token, one lands.
    """
    if not tenant.is_active:
        raise Conflict(
            "That workspace is suspended; its invitations cannot be accepted until it is restored."
        )
    invitation = (
        # rule-24: the token is the reach (the `reach:` valve above);
        # this re-reads that one row to lock it.
        Invitation.objects.for_tenant(tenant).select_for_update().get(pk=invitation.pk)
    )
    if not invitation.is_pending:
        raise Conflict("That invitation has already been used or withdrawn.")
    if is_past(invitation.expires_at):
        raise Invalid({"invitation": ["That invitation has expired. Ask for a new one."]})
    _refuse_a_role_that_stopped_existing(tenant=tenant, invitation=invitation)
    # THE NODE THE OFFER NAMED (ADR core-20). An invitation records the hat it
    # was sent from, and the membership lands exactly there — not at the root,
    # which is what this did while the row carried no organization at all. The
    # record is what makes the offer mean something: "a place in this branch" is
    # what the person was offered, and it is what they get.
    where = invitation.organization
    if Membership.objects.for_tenant(tenant).of(user).filter(organization=where).exists():
        raise Conflict(
            f"You are already a member of {tenant.name}, so there is nothing for this "
            "invitation to add. Whoever sent it can already see you on the member list.",
            remedies=(
                Remedy("You are already in — carry on where you left off", "self:membership"),
            ),
        )

    membership = add_membership(
        # The system altitude, named (ADR core-22, L1): nobody is GRANTING here
        # — the placement was decided by whoever invited them, bounded by what
        # THEY could reach, and the accepter cannot grant themselves anything.
        # The wall reads `kind == "system"` and says so on the row; passing the
        # accepter's own actor would ask it to measure a ceiling they do not
        # have and refuse every legitimate acceptance.
        user=user,
        tenant=tenant,
        organization=where,
        is_default=not Membership.objects.of(user).exists(),
        role=invitation.role,
        actor=system_actor(tenant=tenant),
    )
    invitation.status = Invitation.Status.ACCEPTED
    invitation.accepted_at = now()
    invitation.save(update_fields=["status", "accepted_at", "updated_at"])
    return membership


@service
def revoke_invitation(*, tenant: Tenant, invitation: Invitation, actor: Actor) -> Invitation:
    """Withdraw an invitation nobody has accepted.

    **`actor` arrived with the door**, for the reason
    `update_tenant_settings` gives at length: this service refused nobody
    because nothing outside the tree could reach it, and a door is what makes
    that reachable.

    **Measured at the node the offer was sent from** (ADR core-20), because that
    is where its membership lands and therefore where the authority to withdraw
    it is held. It was measured at the tenant's root until the placement law,
    which meant the branch admin who issued an offer could not withdraw their
    own — and the door's read is narrowed to the hat's subtree, so
    somebody else's branch's invitation is `not_found` here rather than
    `forbidden`.

    It is deliberately **not** a state check as well: revoking an invitation
    that is already revoked is the same sentence said twice, and answering the
    second one with a refusal would make a retry look like a failure.
    """
    # Reachability first, then the verb — `revoke_membership`'s order, for its
    # reason (house rule 26). An invitation standing in a branch this actor
    # holds no hat over is `NotFound` and never `Forbidden`: telling not-there
    # from not-yours apart would confirm that somebody has been invited to that
    # branch, which is exactly what the narrowing exists to keep quiet. The
    # doors already resolve the row through `get_invitation` against the hat's
    # own subtree; this is the belt to that brace, beside the write.
    # Keyed on the KIND since ADR core-22's L1 ruling. A system actor holds no
    # hat, so `may_be_named` fails closed on it by construction — which turned
    # every sweep and every command into a `NotFound` the moment `actor` became
    # required. The altitude is named here instead, and the row records it.
    if actor.kind != "system":
        if not may_be_named(actor, invitation):
            raise NotFound()
        require(actor, "invitation.revoke", invitation.organization)
    invitation.status = Invitation.Status.REVOKED
    invitation.save(update_fields=["status", "updated_at"])
    return invitation


# Where a redacted invitation address goes. `.invalid` is reserved by RFC 2606
# and can never resolve, and the two labels are what Django's `EmailValidator`
# needs — the same constant and the same two reasons as
# `apps.accounts.services.ERASED_EMAIL_DOMAIN`, repeated rather than imported
# because the dependency runs the other way (`core` may not import `accounts`).
# `apps/core/tests/test_redact_invitations.py` pins the pair so the repeat
# cannot drift.
REDACTED_EMAIL_DOMAIN = "erased.invalid"


# --- `redact_invitations` ------------------------------------------------------
# why-not the token: `token_hash` is a digest, not an identifier; blanking a unique column collides.
# door: reached via `accounts.services.erase_user` (REST, MCP); rule 42 reads one hop from a door
@service
def redact_invitations(
    *,
    email: str,
    actor: Actor,
    tenant: Tenant | None,
) -> Swept:
    """Take a person's address out of every invitation that holds it. **Platform-wide.**

    **It returns a `Swept`, not the rows** (ADR core-22, L6). Handing back the
    rows it had just redacted was a shape with two problems: an erasure sweep
    that returns its victims is an erasure that hands the address's neighbours
    to whoever called it, and a list is not something `core.service._object_of`
    can read, so the audit row for the most privacy-sensitive sweep in the
    product named no population at all. The typed result answers both — the
    label of what was walked, the count of what went, and nothing about who.

    Called by erasure (`accounts.erase_user`, ADR ident-5): the fourth residue
    table, and the one the erasure sweep could not reach on its own. An
    invitation is written by `core` and belongs to `core`, so accounts asking
    for it is a service call and never a write into another app's model (C3,
    house rule 10).

    **Two different things happen and it matters which is which.**

    * Every invitation holding the address — pending, accepted or revoked — has
      the address *redacted*, replaced by `redacted+<uuid7>@erased.invalid`. A
      unique replacement rather than a shared sentinel, for the reason
      `erase_user` gives about `User.email`: a shared value silently groups rows
      that have nothing to do with each other.
    * Only the ones still **pending** are additionally *voided*
      (`Status.REVOKED`), because only a pending invitation is a standing offer
      somebody could still walk through. An accepted invitation is history, and
      history is not withdrawn — the row stays, saying that an offer was made
      and taken, with nobody's address on it.

    **Platform-wide, and that is the point**: nobody knows which tenants hold an
    offer to this address — that is what an invitation to somebody with no
    account IS. `tenant` is therefore an audit-population selector and not a
    filter. Pass the tenant the erasure is being performed in and the row lands
    in that tenant's ledger; pass nothing and it lands in the platform's,
    readable through `AuditEntry.objects.for_platform()`. Exactly `erase_user`'s
    own shape, and exactly ADR core-8's declared null population.

    DOES NOT COVER — declared:

    * **an alias.** The sweep is an exact match on the normalised address, so an
      invitation sent to `jo+work@example.com` survives an erasure of
      `jo@example.com`. Alias-awareness is a per-deployment mail-routing fact,
      not something a query can know; the closed half is the address as it was
      written down.
    * **an invitation held anywhere but this table** — a product that copies the
      address into its own model erases it in its own service.
    * **the person's other rows.** This service is one residue table's answer,
      not erasure; `erase_user` composes it with the rest.
    """
    # authz: nothing an actor could be measured against exists here. A hat is
    # measured on an organization and this sweep spans every tenant on the
    # deployment by construction, so there is no org that could grant it and
    # none that could withhold it. What authorizes the act is the erasure the
    # caller is performing, checked at ITS own door (`accounts.erase_user` ->
    # `policies.themselves_or_administers_the_whole_tenant`); the actor is
    # carried here so the audit row says who asked, not so this function can
    # re-decide. A `require` here would be theatre with a made-up subject.
    address = email.strip().lower()
    if not address:
        return Swept(label=Invitation._meta.label, count=0)

    # rule-8: the platform-wide half of the invitation table, and the sibling of
    # `selectors.list_pending_invitations_for` — which rules.yaml exempts for this same
    # reason. An offer made to somebody with no account belongs to no tenant the
    # caller knows, so `for_tenant` has nothing to be given: not knowing which
    # tenants hold the address IS the problem this solves. Narrowed by the
    # address being erased, and by nothing else.
    rows = list(Invitation.objects.filter(email=address).order_by("created_at"))

    for invitation in rows:
        fields = ["email", "updated_at"]
        if invitation.status == Invitation.Status.PENDING:
            invitation.status = Invitation.Status.REVOKED
            fields.append("status")
        invitation.email = f"redacted+{uuid7()}@{REDACTED_EMAIL_DOMAIN}"
        invitation.save(update_fields=fields)

    log.info("core.redact_invitations.swept", count=len(rows))
    return Swept(label=Invitation._meta.label, count=len(rows))


from apps.core.services.memberships import (  # noqa: E402
    _placement,
    _refuse_escalation,
    _refuse_unknown_role,
    add_membership,
    known_role_keys,
    role_label,
)
