"""Writes for the accounts app.

Services own every write. Views, routes, MCP tools, admin actions and
management commands call these functions; nothing else calls `.save()` on a
user, a token or an SSO row.

Every write here is `@service`. The exceptions are named rather than left to be
noticed:

* `hash_token` is a pure function of its argument;
* `touch_token` and `authenticate_token` are the read path every authenticated
  machine request takes — wrapping the hottest read in the API in a transaction,
  a span and an audit row would cost more than the fact it records;
* `tenants_this_user_alone_owns` is a read `erase_user` consults before it
  refuses;
* `close_sockets` writes nothing at all — it asks the socket app, through
  `core.bridge`, to hang up on somebody whose credential has just been taken
  away, and the write that took it away has already happened. It is re-exported
  from `core.services` rather than defined here: SEC-1's MED-1 needed the same
  act on `core`'s authorization writes, and `core` may not import this app, so
  the seam was promoted rather than copied (see "The socket seam", below);
* `_clean_domains`, `_apply_domains`, `_metadata` and
  `_refuse_role_above_the_configurer` are private helpers of the SSO services
  below and always run inside one of their transactions;
* `_refuse_a_person_outside_this_actors_tenant` is the second half of
  `erase_user`'s guard, extracted when the socket kick took that service past
  its recorded length ceiling — a refusal, inside the erasure's transaction.

The **reads** an SSO login needs — home-realm discovery, "is password login
still allowed for this address", "is this a workforce address" — live in
`selectors.py`, where reads live.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, NamedTuple

from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.conf import settings
from django.utils import timezone

from apps.accounts.models import (
    CLIENT_ID_KEY,
    CLIENT_SECRET_KEY,
    ISSUER_KEY,
    ApiToken,
    SsoConnection,
    SsoDomain,
    SsoIdentity,
    User,
    domain_of,
    normalise_domain,
)
from apps.accounts.types import (
    KIND_IDENTITY_REVOCATION,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
    IdentityConfigApplied,
    IdentityConfigSync,
)
from apps.core import authz, bridge
from apps.core.actor import Actor, system_actor
from apps.core.exceptions import Conflict, Invalid, NotFound, Remedy, as_invalid
from apps.core.ids import uuid7
from apps.core.log import get_logger
from apps.core.middleware import resolve_tenant
from apps.core.models import Membership, Tenant
from apps.core.service import service
from apps.core.services import (
    _refuse_escalation,
    add_membership,
    redact_invitations,
    root_organization,
)

# Re-exported under their own names — the redundant alias is the explicit
# re-export form `mypy --strict` requires (implicit re-export is off), and it
# is what keeps `apps.accounts.services.close_sockets` a real name for the
# callers A1 wrote: `activities.py`'s identity revocation, and this module's
# own erasure and token revocation.
from apps.core.services import close_sockets as close_sockets
from apps.core.services import close_sockets_on_commit as close_sockets_on_commit
from apps.core.time import now

log = get_logger(__name__)

TOKEN_PREFIX = "djb"
TOKEN_BYTES = 32

# `.invalid` is reserved by RFC 2606 and guaranteed never to resolve, so an
# erased address cannot be delivered to by any mail host, ever, however hard
# somebody tries. A real-looking domain would eventually get an email.
#
# Two labels rather than a bare `invalid`, because Django's `EmailValidator`
# refuses a single-label domain and `full_clean()` would reject the very row the
# erasure is trying to write.
ERASED_EMAIL_DOMAIN = "erased.invalid"

# What may appear un-redacted in this app's log lines and audit `input`. An
# email address is a person, so it is not on the list; a token's `name` is a
# label its owner chose for it, so it is.
#
# The SSO additions are all facts about a *tenant's configuration*, not about a
# person: which protocol, which issuer, which domains it claims, what role a new
# member lands at, whether password login is still allowed. Deliberately absent:
# `subject` (a pseudonymous person), `client_id` and `client_secret` (halves of
# a credential — and `client_secret` would be the whole of one).
LOG_KEYS: frozenset[str] = frozenset(
    {
        "name",
        "is_staff",
        "is_superuser",
        "is_active",
        "protocol",
        "issuer",
        "email_domains",
        "default_role",
        "enforced",
        "reason",
    }
)


# --- The socket seam ----------------------------------------------------------
# **The implementation moved; the vocabulary did not.** P3-A1 wrote
# `close_sockets` and `close_sockets_on_commit` here, when the only callers were
# credential withdrawals. SEC-1's MED-1 found the other half — *authorization*
# withdrawal (a membership removed, a subtree re-parented) never reached an open
# socket — and those writes live in `apps.core`, which may not import this app
# (rule 7).
#
# So the pair was **promoted to `apps.core.services`** rather than copied into
# it. Two hand-kept copies of one act is the exact root cause P2's SEC-R1b had
# to seal when `SENDABLE` existed twice and the retry path drifted from the
# wall; a second `close_sockets` in `core` would have rebuilt that shape on a
# security seam. `accounts` imports `core` — the layer contract already runs
# that way — and re-exports the two names here so every caller, test and
# docstring that says `apps.accounts.services.close_sockets` still means the one
# function. The reasons below stay in this app because a reason is the free text
# on the kick's log line, and the app that made the decision is the app somebody
# will grep for it in.
KICK_TOKEN_REVOKED = "accounts.token.revoked"
KICK_USER_ERASED = "accounts.user.erased"
KICK_USER_DEACTIVATED = "accounts.user.deactivated"
KICK_IDENTITY_REVOKED = "accounts.identity.revoked"


class Authenticated(NamedTuple):
    """What a valid bearer token resolves to: a user, a tenant, and the row itself.

    The token row is part of the answer because the audit trail needs it: "this
    person did it" and "an integration this person installed did it" are
    different facts about the same user, and only the token tells them apart.
    """

    user: User
    tenant: Tenant | None
    token: ApiToken


@service
def create_user(
    *,
    email: str,
    password: str | None = None,
    is_staff: bool = False,
    is_superuser: bool = False,
    is_active: bool = True,
) -> User:
    """Create a user. The one write path onto the user table."""
    with as_invalid():
        if is_superuser:
            return User.objects.create_superuser(
                email=email,
                password=password,
                is_active=is_active,
            )
        return User.objects.create_user(
            email=email,
            password=password,
            is_staff=is_staff,
            is_active=is_active,
        )


@service
def deactivate_user(*, user: User, actor: Actor, tenant: Tenant | None) -> User:
    """Take a person's access away without erasing anything.

    The reversible half of `erase_user`, and the one to reach for first. It sets
    `is_active` false and nothing else: the email address, the password, the
    memberships and the token rows all stay exactly as they are, so a
    deactivation undone by an operator is a person who signs back in and finds
    their workspace where they left it. **There is no service that undoes it
    today** — that is the honest state, and reactivation is a door this template
    has not grown yet.

    What stops immediately, and why each one does:

    * **the session**, because Django's auth backend re-reads `is_active` on
      every request and hands back no user when it is false;
    * **every API token they hold**, because `authenticate_token` checks the
      same flag before it resolves one — the rows are left alone, so nothing has
      to be re-minted if the deactivation is undone;
    * **every socket they have open**, because none of the above reaches a
      connection that was authenticated an hour ago. That is the SEC-R1 kick
      seam, the same one `erase_user` uses, and it is the difference between a
      revoked person's socket closing and a revoked person's socket eventually
      noticing.

    **Who may:** `policies.themselves_or_administers_the_whole_tenant` — you, or
    an `admin` or better at your tenant's root. Deactivating somebody in another
    tenant is `NotFound`, not `Forbidden`, for the reason every cross-tenant
    refusal here is: a 403 would confirm the account exists.

    Pass `tenant` — the tenant the deactivation is being performed in — so the
    audit row lands in that tenant's ledger; `None` is the deployment's own
    operator and joins the platform population (ADR core-8).

    ---

    **The signature grew an `actor` and a `tenant` in P5-B-ACCT, and both were
    load-bearing.** It used to be `deactivate_user(*, user)`: no actor, so
    nothing authorized — an admin door was free to call it on anybody, and rule
    13 stayed quiet because the rule only asks a service that *resolves* an
    actor to authorize; and no declared `tenant`, so `@service` filed no audit
    row at all (`core.service._declares_tenant`), which meant the one act that
    takes a person's access away left less trail than issuing them a token does.
    Giving it a door is what made both visible: a door cannot carry the wall
    itself without breaking C7 from the door side, and "who deactivated whom"
    with no audit row is a question nobody could answer afterwards.

    Both parameters are additions rather than replacements, and every existing
    call site kept compiling — `tenant` defaults, `actor` is the one thing a
    caller now has to say. `apps/core/service.py`'s `_declares_tenant`
    docstring names this function in its list of services that declare no
    `tenant`; that sentence is stale and the correction is core's to make,
    not this app's (territory).
    """
    authz.require(actor, "accounts.user.deactivate", user)
    _refuse_a_person_outside_this_actors_tenant(user=user, actor=actor)
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    close_sockets_on_commit(user_id=user.pk, reason=KICK_USER_DEACTIVATED)
    return user


def tenants_this_user_alone_owns(*, user: User) -> list[Tenant]:
    """Tenants where this person is the only owner. A read, not a write.

    A tenant with no owner is a tenant nobody can administer: no one can invite
    a member, change a role, or close it. That is not a state an erasure is
    allowed to create, and it is not a state anybody notices until they need to
    do one of those things.
    """
    owned = Membership.objects.filter(user_id=user.pk, role=Membership.Role.OWNER)
    alone = []
    for membership in owned.select_related("tenant"):
        others = Membership.objects.filter(
            tenant_id=membership.tenant_id, role=Membership.Role.OWNER
        ).exclude(user_id=user.pk)
        if not others.exists():
            alone.append(membership.tenant)
    return alone


# CONTEXTUAL REMEDIES, BECAUSE THE REGISTERED ONES ARE WRONG HERE.
# `conflict`'s registered defaults are "re-read the row and retry against what is
# true now" and "send an Idempotency-Key to get the first answer back". Both are
# excellent advice about a *race*; both are false about this one. Nothing has
# changed underneath the caller, and retrying refuses identically until somebody
# does the single thing that helps. A remedy that cannot change the answer is
# worse than no remedy — it sends the caller round a loop — and this is the drift
# ADR core-5 exists to stop, because an assistant reads these out loud. Passing
# `remedies=` REPLACES the registry's list rather than joining it, which is what
# the raise site wants here: the generic advice was not incomplete, it was wrong.
LAST_OWNER_REMEDIES = (
    Remedy("Make somebody else an owner of that tenant first", "self:membership"),
    Remedy("See who else holds a role there", "docs:openapi"),
)


@service
def erase_user(*, user: User, actor: Actor, tenant: Tenant | None) -> User:
    """Anonymise a person, keep their row, and record that it happened.

    **The row stays, and that is the whole design.** Deleting it would cascade
    or block across every foreign key that points at it, and the audit trail is
    exactly the thing that must survive: "who approved this refund" cannot
    become "user 4f2c, deleted". What is erased is the *person*, not the record.

    What goes:

    * the email address, replaced by `erased+<uuid>@invalid` — unique, so the
      unique constraint holds, and in the reserved `.invalid` TLD, so nothing
      can ever deliver to it by accident;
    * the password, set unusable — which also invalidates every live session,
      because Django's session auth hash is derived from it;
    * every API token, revoked, so no machine keeps acting as them;
    * staff and superuser, dropped, because an erased person must not keep a
      key to the admin;
    * every socket they have open, closed (ADR realtime-2 d) — everything above
      stops the *next* request and none of it reaches a live connection.

    **And the rest of the account's footprint goes with it** (ADR ident-5).
    `_erase_the_account_footprint` below enumerates it table by table and by
    mechanism — allauth's `EmailAddress` and `SocialAccount` rows deleted,
    `SsoIdentity.email` and every `Invitation` holding the address redacted.
    This paragraph used to claim the `User` row WAS the whole footprint, and the
    person survived in four other tables. What keeps the enumeration true is not
    the enumeration: `test_erasure_residue.py` sweeps every text and JSON column
    in the model registry, so a fifth residue table fails the day it lands.

    **What is kept is kept with a reason**: memberships, which make the audit
    trail readable ("an owner of Acme did this") and grant nothing once the
    account cannot be used; `AuditEntry` rows; `Event` payloads written before
    the erasure, the witnessed record of what was emitted rather than a copy of
    the person (ADO-4); and `zitadel_sub`, an opaque subject kept as the fence
    that refuses a re-link of this Zitadel account to anybody else's row. A
    product that adds a profile model erases it in its own service.

    **Who may:** `policies.themselves_or_administers_the_whole_tenant` — you, or
    an `admin` or better at the tenant's **root**, which says why root is the unit.

    **It refuses to orphan a tenant.** If this person is the only owner of any
    tenant, the erasure is a `Conflict` and the caller has to make somebody else
    an owner first — including, and especially, when the person erasing is
    themselves: the alternative is a tenant nobody can administer, discovered
    weeks later by whoever tries to invite someone.

    Pass `tenant` — the tenant the erasure is being performed in — so that the
    audit row lands in that tenant's ledger. **An erasure with no tenant at all
    is audited too** (ADR core-8): null is a declared population, `@service` is
    its one writer, and an operator acting for the deployment leaves the row
    every customer's erasure leaves, readable through `for_platform()` alone.
    """
    # An explicit predicate, not the role fallback: nothing used to name
    # this action, so `allows` answered "is this membership privileged", which
    # is true of an admin of one branch — and a branch admin could erase the
    # branch next door. See `policies.administers_the_whole_tenant`.
    authz.require(actor, "accounts.user.erase", user)
    _refuse_a_person_outside_this_actors_tenant(user=user, actor=actor)

    orphaned = tenants_this_user_alone_owns(user=user)
    if orphaned:
        raise Conflict(
            "That person is the only owner of "
            + ", ".join(sorted(one.slug for one in orphaned))
            + ". Make somebody else an owner first, or the tenant is left with nobody "
            "who can administer it.",
            remedies=LAST_OWNER_REMEDIES,  # see the note above this function
        )

    address = user.email
    ApiToken.objects.filter(user_id=user.pk, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    )
    _revoke_identity_platform_access(user=user, actor=actor)
    _erase_the_account_footprint(user=user, address=address, actor=actor, tenant=tenant)

    user.email = f"erased+{uuid7()}@{ERASED_EMAIL_DOMAIN}"
    user.set_unusable_password()
    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    with as_invalid():
        user.full_clean(exclude=["password"])
    user.save(
        update_fields=["email", "password", "is_active", "is_staff", "is_superuser", "updated_at"]
    )
    close_sockets_on_commit(user_id=user.pk, reason=KICK_USER_ERASED)
    return user


# --- The account's footprint, and why the sweep is DELETE for two and REDACT ---
# for two.
#
# ADR ident-5. The long-form reasoning lives out here rather than in the
# docstring below for the reason `core.services.redact_invitations` gives about
# its own: a docstring is inside the function and `service_function_length`
# counts it.
#
# **Two are deleted and two are redacted, and the split is not a judgement
# call.** A row whose entire content is "this address belongs to this account"
# has nothing left to say once the address is gone, so it goes; a row that also
# carries history — an SSO identity's `last_seen_at`, an invitation's record
# that an offer was made and taken — keeps the row and loses the address. It is
# the same split `redact_invitations` makes one table over, and the same one
# `erase_user` makes about the `User` row itself.
#
# **Why the enumeration is not the guarantee.** P5-R1 found the person in four
# tables this service never touched, and found them with a DB-level sweep rather
# than by reading the code — because a service says nothing about the tables it
# does not touch, and neither does a comment. What keeps the list at four is
# `apps/accounts/tests/test_erasure_residue.py`, which walks the model registry
# and asks the database: the fifth residue table fails the day it lands, whoever
# adds it and whatever they call it.


def _erase_the_account_footprint(
    *, user: User, address: str, actor: Actor, tenant: Tenant | None
) -> None:
    """Take the person out of every table this app's sign-in path put them in.

    Runs inside `erase_user`'s transaction, so there is no half-erased person to
    discover later — a failure anywhere in here takes the whole erasure back,
    which `test_erasure_residue.py` plants and proves.

    Table by table, and by what happens to it:

    * **allauth `EmailAddress`** — DELETED. The row IS the address. Its
      `EmailConfirmation` children cascade.
    * **allauth `SocialAccount`** — DELETED, `extra_data` and all. Whatever the
      IdP asserted at login lives in that JSON, and the link the row records is
      one Zitadel has already been asked to revoke by
      `_revoke_identity_platform_access`. Its `SocialToken` children cascade.
    * **`SsoIdentity.email`** — REDACTED to the `erased+<uuid>@invalid` form the
      `User` row gets, across every tenant the person has an identity in. The
      row stays: `subject` is what a later assertion is matched against, and
      `last_seen_at` is a fact about a login rather than about a person.
    * **`Invitation.email`** — through `core.redact_invitations`, which voids
      the pending ones and redacts them all, PLATFORM-WIDE. Core's table, so
      this is a service call and never a write into another app's model (house
      rule 10), and platform-wide because nobody knows which tenants hold a
      standing offer to an address — that is what an invitation to somebody
      with no account IS.

    Reached through `user.sso_identities` rather than `SsoIdentity.objects`, and
    that is the honest read rather than a way around rule 8: the rows wanted are
    exactly the ones pointing at this person, in whatever tenants those turn out
    to be, and a scoped read would need a tenant nobody in this call has.
    """
    EmailAddress.objects.filter(user_id=user.pk).delete()
    SocialAccount.objects.filter(user_id=user.pk).delete()
    for identity in user.sso_identities.all():
        identity.email = f"erased+{uuid7()}@{ERASED_EMAIL_DOMAIN}"
        identity.save(update_fields=["email", "updated_at"])
    redact_invitations(email=address, actor=actor, tenant=tenant)


def _refuse_a_person_outside_this_actors_tenant(*, user: User, actor: Actor) -> None:
    """The second half of "may you erase this one", extracted so `erase_user` fits.

    `authz.require` has already answered "does this actor administer a whole
    tenant"; this answers "is this person *in* it". An owner of one tenant does
    not get to erase somebody else's person.

    `NotFound` and not `Forbidden`, for the same reason every other cross-tenant
    refusal is: a 403 here would confirm the account exists. Tenant-level is
    exactly right — whoever got past `require` administers this tenant's root,
    so their reach *is* the tenant.

    A `None` tenant on the actor is the deployment's own operator, who is not
    inside anybody's tenant and is not being asked to be.
    """
    if actor.tenant is None:
        return
    if not Membership.objects.filter(user_id=user.pk, tenant=actor.tenant).exists():
        raise NotFound()


def _revoke_identity_platform_access(*, user: User, actor: Actor) -> str | None:
    """Ask for this person's Zitadel account to be deactivated and unlinked.

    **The half `erase_user` was missing** (ADR ident-6): the tokens are ours and
    the session is ours, but the *credential* is Zitadel's, and so is the next
    login. An erasure that anonymised our row and left the identity platform's
    account live is an erasure the person signs straight back through — and
    `SOCIALACCOUNT_ONLY` means that is now the only way anybody signs in at all.

    A workflow rather than a call, for the reason every other management call is
    one: an external call inside the erasing transaction means a Zitadel hiccup
    rolls back a legitimate erasure, and this transaction is the one that must
    not be rolled back by somebody else's server. The run is deterministic on the
    person's primary key (house rule 18), so erasing twice asks for the same run
    rather than a second one.

    **One honest skip**, logged rather than swallowed: a person with no
    `zitadel_sub` has never signed in through the platform, so there is no
    account to deactivate.

    **The second skip is gone.** It used to
    read: a person with no tenant anywhere leaves nowhere to record the run, so
    log `accounts.identity.not_revoked` and move on — which meant the one class
    of person most likely to have no membership left (an operator, a contractor,
    somebody whose last workspace already removed them) kept a live Zitadel
    account after being erased, and `SOCIALACCOUNT_ONLY` makes that account the
    only way anybody signs in. ADR workflows-3 made `WorkflowRun` the
    platform-wide run ledger, so there is somewhere to record it now: the run is
    started with `tenant=None` under a `platform:` id, and the revocation
    happens for everybody.

    **Every revocation is a platform run** (ADR ident-7). It used to depend
    on who the person was: a nomad got a platform run and anybody with a
    membership had theirs recorded in a *borrowed* tenant, picked by
    `_a_tenant_of` — a helper whose own docstring declared the blind spot and
    named this successor. The borrow made a tenant's audit ledger claim a
    revocation of a credential it never owned, which is a trail that lies; and
    the credential is Zitadel's, not a tenant's, which settles the matter. The
    only thing holding it in place was A9 row 20's frozen pin, since re-pointed.

    So the `tenant` this erasure is happening in is deliberately **not** a
    parameter here. There is nothing for it to decide.

    Returns the run key, or `None` when it skipped — which is what the tests
    assert on rather than reaching into the log.
    """
    subject = str(user.zitadel_sub or "").strip()
    if not subject:
        return None
    run_key = str(user.pk)
    try:
        _start_identity_run(
            tenant=None,
            actor=actor,
            kind=KIND_IDENTITY_REVOCATION,
            key=run_key,
            noun="identity_revocation",
            run_key=run_key,
        )
    except Conflict:
        # The same person, erased again. One run per person is the contract the
        # deterministic id states; asking twice is not two revocations.
        log.info("accounts.identity.revocation_already_asked", user_id=str(user.pk))
    return run_key


def hash_token(plaintext: str) -> str:
    """The stored form of a token.

    SHA-256 without a salt is right here and wrong for passwords: the secret is
    32 random bytes, so there is no dictionary to attack, and a lookup has to be
    a single indexed read rather than a scan over every row.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


@service
def issue_token(
    *,
    user: User,
    tenant: Tenant | None,
    name: str,
    actor: Actor,
    scopes: Sequence[str] | None = None,
) -> tuple[ApiToken, str]:
    """Mint a token. The plaintext is returned once and never stored.

    `scopes` is the ceiling the token carries, and `None` means it carries
    none — the token can do whatever its person can. That is the meaning every
    row minted before ceilings existed has, so it is also what this service
    does when nobody says otherwise.

    **The two doors do not leave it out.** Both the HTTP mint and the shell
    mint require the caller to say, because a token handed to somebody else's
    software should be as narrow as the job needs and a default is how it ends
    up as wide as the person. What the doors send here has already been checked
    against this deployment's vocabulary; a non-`None` list is checked again
    here anyway, so a caller that reached this service another way cannot store
    a ceiling naming a family that does not exist.

    **`actor` is required and never defaulted** (ADR core-22). It is not
    an argument this function reads — it is the row's answer to AU-3's
    "identity of associated individuals", which `@service` takes from the actor
    it was given and from nowhere else. Before it existed, a credential's birth
    certificate recorded the workspace, the moment and the door, and not who
    minted it; and a *defaulted* actor would have been the same hole wearing a
    signature, exactly as ADR core-8's `sync_workforce_identity_config` was.
    The REST door passes `actor_from_request(request)` — `human` for the
    session that is the only way to mint over the wire, so `actor_user` is set
    — and the shell door passes `system_actor(tenant=…)`, which is core-22's
    absence (iv): a command's row is honestly `kind=system, actor_user` None,
    because ssh owns who held the shell and this table does not duplicate an
    authority it cannot verify.

    Note the actor is **not** necessarily `user`: at the shell, an operator
    mints a credential for somebody else, and "for whom" and "by whom" are two
    facts the row keeps apart.
    """
    # authz: minting is not a capability to grant — a token can never do more
    # than the person it is minted for (`_ceiling` here, `effective_scopes` at
    # every use), so there is no privilege here for `require` to measure. What
    # decides whether a mint may happen at all is reachability, and each door
    # owns it: the REST door refuses a token-authenticated caller outright and
    # resolves the person and tenant through `_acting`, and the shell door is
    # the box's own access audit. The actor is kept for the audit row, which is
    # rule 13's own recorded shape for this (`apps/usage/policies.py`).
    plaintext = f"{TOKEN_PREFIX}_{secrets.token_urlsafe(TOKEN_BYTES)}"
    token = ApiToken(
        user=user,
        tenant=tenant,
        name=name.strip(),
        key_hash=hash_token(plaintext),
        scopes=_ceiling(scopes),
    )
    with as_invalid():
        token.full_clean()
    token.save()
    return token, plaintext


def _ceiling(scopes: Sequence[str] | None) -> list[str] | None:
    """The ceiling as it is stored, refusing a name this deployment does not have.

    `None` in, `None` out — no ceiling, said by saying nothing. Anything else
    goes through the same check both mint doors use, so the three ways into
    this service cannot come to disagree about what a scope name is.

    The import is inside the function rather than at the top of the module for
    the reason `apps/core/api/docs.py` gives about the machine door: the module
    it reaches for is a door module, this one sits below the doors, and naming
    a higher module at import is how a cycle is spelled. Reading it here costs
    a dictionary lookup on the rare path where a token is minted.
    """
    if scopes is None:
        return None
    from apps.core.api.scopes import ceiling_from_request

    return ceiling_from_request(list(scopes))


@service
def revoke_token(*, token: ApiToken, tenant: Tenant | None, actor: Actor) -> ApiToken:
    """Stop a token working, keeping the row so the audit trail survives.

    **The credential's death is audited beside its birth** (ADR core-22).
    `tenant` is here to be *declared*: `@service` reads the audited population
    off the signature (`core.service._declares_tenant`), so before this
    parameter existed a mint wrote an `AuditEntry` and a revocation wrote none —
    a compliance trail that recorded who was given the ability to act as
    somebody and never who ended it, which is the one question such a trail
    exists to answer. ADR core-8 exempted this service on the grounds that it is
    "not about a tenant's rows"; that is false for a credential pinned to one,
    and the reversal is recorded rather than quietly made.

    **Both `tenant` and `actor` are required, and never defaulted**, for one
    reason. The decorator reads the population from the declaration but writes
    the row from the *call*, so a defaulted parameter is a service that looks
    audited and files every row under `None` — exactly how
    `sync_workforce_identity_config` went unaudited under core-8. Both doors
    pass `token.tenant`.

    **The token's own pin decides the population**, mirroring the mint exactly.
    A token pinned to no workspace is a real product state, not an absence: its
    birth row is in the platform (null-tenant) population declared by ADR
    core-8(b), and its death row belongs beside it. No new population shape is
    invented and nothing is refused from audit.

    **And the parameter cannot lie**: a `tenant` disagreeing with `token.tenant`
    is refused rather than filed, so a revocation can never be recorded under a
    workspace the credential was not pinned to. That is C9's derive-from
    principle applied one level up — the row it is *about* already knows the
    answer, so the argument is a claim to be checked, not a fact to be trusted.

    **A second revocation is a no-op, not a refusal.** The REST door is
    `DELETE`, idempotent by HTTP law and answering `204` on a re-delete since it
    landed; a `409` would change the client contract more than the defect
    warrants. What the defect actually was is this method overwriting
    `revoked_at` unconditionally — moving a recorded moment, which is an audit
    fact, on a call that changed nothing else. So an already-revoked token comes
    straight back: no write, no timestamp move, and no socket kick, because the
    kick rides the commit of a write that did not happen. The call is still
    audited — a no-op is not a non-event, and "somebody asked again" is exactly
    what a trail is read for afterwards. The shell command's own IS-NULL
    refusal ("already revoked at <ts>", non-zero exit) stands unchanged at its
    own layer: a person at a shell asked a question and deserves an answer, and
    a script's exit status is not an HTTP contract.

    **And close the sockets it left behind** (ADR realtime-2 d). Revoking used
    to stop the *next* request and nothing else: a socket opened with this token
    an hour ago had already been authenticated, and it went on receiving until
    the client hung up. The revocation now reaches the connection instead of the
    connection eventually noticing.

    Every socket the person has open, not only the ones this token opened, and
    that is `user_group`'s deliberate shape rather than an over-reach here: the
    channel layer knows which person a connection belongs to and nothing else,
    and a kick that closed some of them would be a revocation the client could
    simply ignore by using its other tab.

    On commit, so that a revocation which rolls back disconnects nobody.

    **And `actor` says who ended it** (ADR core-22) — the last quarter of
    the sentence above, which no column used to answer. REST passes
    `actor_from_request(request)`; the shell passes `system_actor(tenant=…)`,
    honestly `kind=system` (core-22's absence iv).
    """
    # authz: the door owns reachability and this service could not re-derive
    # it — REST resolves the row through `_own_tokens(request)` (yours, or
    # 404), the shell is the box's own access audit — and revoking reaches
    # nothing anyway: it only stops a credential. The actor is kept for the
    # audit row (rule 13's recorded valve; `apps/usage/policies.py`).
    #
    # Compared by primary key rather than by instance: two `Tenant` objects for
    # one row are not `==` in every path a caller can reach this from, and the
    # question is which row the credential is pinned to, not which object the
    # caller happens to be holding.
    if (tenant.pk if tenant is not None else None) != token.tenant_id:
        raise Invalid(
            {
                "tenant": [
                    "This token is not pinned to that tenant. A revocation is "
                    "recorded under the workspace the credential belonged to."
                ]
            }
        )

    if token.revoked_at is not None:
        # A no-op. Nothing to write, so nothing to announce: returning here is what
        # keeps the recorded moment the fact it is.
        return token

    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at", "updated_at"])
    close_sockets_on_commit(user_id=token.user_id, reason=KICK_TOKEN_REVOKED)
    return token


def touch_token(*, token: ApiToken) -> None:
    """Record that a token was used, at most once per touch window.

    `last_used_at` answers one question — "is this token still in use" — and it
    answers it just as well at five-minute resolution. Writing it on every
    request turns the hottest read in the API into a read plus a write, and
    serialises concurrent machine traffic on one row for nothing.

    Deliberately not `@transaction.atomic`: it is one statement, and it must not
    enlarge the caller's transaction.
    """
    window = timedelta(seconds=int(settings.ACCOUNTS_TOKEN_TOUCH_SECONDS))
    now = timezone.now()
    if token.last_used_at is not None and now - token.last_used_at < window:
        return
    ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)


def authenticate_token(
    *,
    plaintext: str,
    requested_slug: str | None = None,
) -> Authenticated | None:
    """Resolve a bearer token to the user, tenant and token row it acts as.

    **Authentication only. It answers WHO, never WHERE-you-may-act** — that is
    the addressing-header law's half, and it lives in one place for every door
    (`core.middleware.addressing_refusal`; ADR core-21).

    A token pinned to a tenant acts in that tenant and nowhere else, so this
    returns the pin whatever `X-Tenant` asked for, and the door then refuses a
    request that asked for a different one. It used to return `None` here — the
    credential simply *failing* — and the wire said **401 "We could not tell who
    is making this request"** over a live, unrevoked token belonging to a real
    active user. That fact was false, which E9's
    grammar refuses; the truthful answer is authenticated-then-refused, and it
    can only be given by something that authenticated first.

    A token without a pin resolves the tenant the same way a signed-in request
    does, from the user's memberships — so the machine door and the human door
    cannot disagree about who can see what.
    """
    if not plaintext:
        return None
    token = (
        ApiToken.objects.select_related("user", "tenant")
        .filter(key_hash=hash_token(plaintext), revoked_at__isnull=True)
        .first()
    )
    if token is None or not token.user.is_active:
        return None
    if token.tenant is not None:
        # The pin, whatever was asked for. A request that asked for another
        # tenant is refused at the door by `addressing_refusal`, in the
        # product's own envelope, and the token IS touched because it really was
        # used: a credential that authenticated and was then refused for where
        # it pointed is not the same event as a credential that did not work.
        touch_token(token=token)
        return Authenticated(token.user, token.tenant, token)
    touch_token(token=token)
    return Authenticated(
        token.user,
        resolve_tenant(user=token.user, requested_slug=requested_slug),
        token,
    )


# --- Customer SSO ------------------------------------------------------------
# Three services a tenant's owner or admin calls, and one the login flow calls
# for them. The first three are ordinary tenant-owned writes: keyword-only,
# authorized, audited. The fourth — `provision_sso_identity` — is the one the
# adapter runs with a `system` actor, because the person it is creating does not
# exist yet and therefore cannot be the actor that created them.

# What a domain has to look like before it is stored. Deliberately loose — the
# authority on whether a domain resolves is DNS, and this is not DNS — but tight
# enough to refuse the four things somebody actually types by mistake: an email
# address, a URL, a bare label, and whitespace.
_DOMAIN_PATTERN = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9-]+)+$")


def _clean_domains(values: Sequence[str]) -> list[str]:
    """Normalise, validate and de-duplicate a set of claimed domains."""
    cleaned: list[str] = []
    for value in values:
        domain = normalise_domain(value)
        if not domain:
            continue
        if not _DOMAIN_PATTERN.match(domain):
            raise Invalid(
                {"email_domains": [f"{value!r} is not an email domain."]},
                detail=(
                    f"{value!r} is not an email domain. Give the part after the @, like acme.com."
                ),
            )
        if domain not in cleaned:
            cleaned.append(domain)
    if not cleaned:
        raise Invalid(
            {"email_domains": ["Claim at least one email domain."]},
            detail=(
                "An SSO connection has to claim at least one email domain, or "
                "nothing can ever be routed to it."
            ),
        )
    return cleaned


def _apply_domains(*, connection: SsoConnection, domains: Sequence[str]) -> None:
    """Make this connection's claims exactly `domains`, and nobody else's.

    A claim held by another connection is a `Conflict` with the domain named:
    the person configuring this is an admin of a tenant that genuinely owns the
    domain, and "example.com is already claimed" is the sentence that lets them
    go and find who claimed it. It says nothing about *which* tenant holds it,
    which would be an existence oracle over the customer list.
    """
    wanted = _clean_domains(domains)
    for domain in wanted:
        existing = SsoDomain.objects.claim(domain)
        if existing is not None and existing.connection_id != connection.pk:
            raise Conflict(
                f"{domain} is already claimed by another SSO connection. "
                "An email domain routes to exactly one identity provider."
            )
    current = {
        row.domain: row
        for row in SsoDomain.objects.for_tenant(connection.tenant).filter(connection=connection)
    }
    for domain, row in current.items():
        if domain not in wanted:
            row.delete()
    for domain in wanted:
        if domain in current:
            continue
        row = SsoDomain(tenant=connection.tenant, connection=connection, domain=domain)
        with as_invalid():
            row.full_clean()
        row.save()


def _refuse_role_above_the_configurer(*, tenant: Tenant, actor: Actor, role: str | None) -> None:
    """**The escalation wall, applied to a standing instruction.**

    A connection's `default_role` is not a field like `name`: it is a grant that
    `ensure_membership` will execute later, as the system, with no granter left
    to measure. Before this guard, any privileged actor — including an admin of
    one branch — could write `default_role="owner"` and the next sign-in from a
    claimed domain minted an owner they could never have granted by hand
    (`add_membership` would have refused them on the spot). Two write paths with
    different ceilings is the shape the wall exists to close.

    So the ceiling is read **here**, where a person is acting, through the one
    grammar the wall already speaks — `core.services._refuse_escalation`, the
    same two refusals `add_membership` and `set_role` raise, with the same
    `forbidden` code and the same remedies envelope. There is no second rank
    comparison in this repository and there must not be one.

    **Measured at the tenant's root**, because that is where the grants land:
    `ensure_membership` names no organization, so a JIT membership sits on the
    root, and a branch admin — who holds no role there — may configure no
    connection at all rather than one that grants beneath them.

    `role=None` is "leave it alone" on the patch door and is not a grant.
    A `system` actor is the product configuring itself (a seed, a workflow):
    `_refuse_escalation` returns on `kind == "system"`, which since ADR
    core-22's L1 ruling is a NAMED audited altitude the row records, rather
    than the old accident of a granter who happened to have no user.
    """
    if role is None:
        return
    _refuse_escalation(
        actor=actor,
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        role=role,
    )


def _metadata(*, issuer: str, client_id: str, client_secret: str) -> dict[str, str]:
    return {
        ISSUER_KEY: issuer.strip().rstrip("/"),
        CLIENT_ID_KEY: client_id.strip(),
        CLIENT_SECRET_KEY: client_secret.strip(),
    }


@service
def create_sso_connection(
    *,
    tenant: Tenant,
    actor: Actor,
    name: str,
    issuer: str,
    client_id: str,
    client_secret: str,
    email_domains: Sequence[str],
    protocol: str = SsoConnection.Protocol.OIDC,
    default_role: str = Membership.Role.MEMBER,
    enforced: bool = False,
) -> SsoConnection:
    """Give a tenant its own identity provider.

    Owner or admin only (`policies.py`), because a connection decides who may
    become a member of this tenant and at what role — it is the most powerful
    row in the product after `Membership` itself.

    **And `default_role` is bounded by the configurer's own effective role at
    the tenant's root** (`_refuse_role_above_the_configurer`): a connection is a
    grant with a delay, and an admin who could configure one that mints owners
    would be an admin who becomes an owner as soon as somebody signs in.

    **SAML is refused here**, not silently accepted and then found not to work.
    `config/settings/base.py` carries the reason and the exact steps to turn it
    on; until they are taken, a customer who asks for SAML gets a sentence
    rather than a connection that never authenticates.
    """
    authz.require(actor, "sso_connection.create", tenant)
    _refuse_role_above_the_configurer(tenant=tenant, actor=actor, role=default_role)

    if protocol != SsoConnection.Protocol.OIDC:
        raise Invalid(
            {"protocol": ["Only 'oidc' is supported today."]},
            detail=(
                "Only OpenID Connect is supported today. SAML is a recorded "
                "escalation — see config/settings/base.py, 'SAML'."
            ),
        )
    if not issuer.strip() or not client_id.strip() or not client_secret.strip():
        raise Invalid(
            {"metadata": ["issuer, client_id and client_secret are all required."]},
            detail=(
                "An OpenID Connect connection needs an issuer, a client id and a client secret."
            ),
        )

    connection = SsoConnection(
        tenant=tenant,
        name=name.strip(),
        protocol=protocol,
        default_role=default_role,
        enforced=enforced,
        metadata=_metadata(issuer=issuer, client_id=client_id, client_secret=client_secret),
    )
    with as_invalid():
        connection.full_clean()
    connection.save()
    _apply_domains(connection=connection, domains=email_domains)
    _materialise(tenant=tenant, actor=actor, connection=connection)
    return connection


@service
def update_sso_connection(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: SsoConnection,
    name: str | None = None,
    issuer: str | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
    email_domains: Sequence[str] | None = None,
    default_role: str | None = None,
    enforced: bool | None = None,
) -> SsoConnection:
    """Change a connection. Every argument is optional; `None` means "leave it".

    `default_role` is bounded exactly as it is on the way in — see
    `create_sso_connection`. Raising an existing connection's role past your own
    ceiling is the same act with an extra step.

    `client_secret` is the one field with no way back: it is write-only, so
    "leave it" is the only thing an omitted secret can mean, and re-sending the
    connection without one must never blank it. Passing an empty string is
    therefore also "leave it" — an admin who wants the connection to stop
    working disables it, which says so in the audit trail.
    """
    authz.require(actor, "sso_connection.update", connection)
    _refuse_role_above_the_configurer(tenant=tenant, actor=actor, role=default_role)

    if name is not None:
        connection.name = name.strip()
    if default_role is not None:
        connection.default_role = default_role
    if enforced is not None:
        connection.enforced = enforced

    metadata = dict(connection.metadata or {})
    if issuer:
        metadata[ISSUER_KEY] = issuer.strip().rstrip("/")
    if client_id:
        metadata[CLIENT_ID_KEY] = client_id.strip()
    if client_secret:
        metadata[CLIENT_SECRET_KEY] = client_secret.strip()
    connection.metadata = metadata

    with as_invalid():
        connection.full_clean()
    connection.save()
    if email_domains is not None:
        _apply_domains(connection=connection, domains=email_domains)
    _materialise(tenant=tenant, actor=actor, connection=connection)
    return connection


@service
def disable_sso_connection(
    *, tenant: Tenant, actor: Actor, connection: SsoConnection
) -> SsoConnection:
    """Stop this identity provider being able to sign anybody in.

    **The row and its domain claims stay.** Deleting them would free the domain
    for another tenant to claim while this one is mid-migration, and would take
    the `SsoIdentity` rows — the record of who arrived through it — with them.
    A disabled connection resolves to nothing in
    `SsoConnectionManager.by_provider_id`, so an in-flight callback is refused
    rather than honoured, and `enforced` stops applying, so the people it
    covered can use a password again instead of being locked out.
    """
    authz.require(actor, "sso_connection.disable", connection)
    connection.status = SsoConnection.Status.DISABLED
    connection.disabled_at = now()
    connection.save(update_fields=["status", "disabled_at", "updated_at"])
    # **And Zitadel is told.** Before W2-R5 this stopped our own callback and
    # left the identity platform perfectly willing to sign the same people in —
    # which, once Zitadel fronts every IdP, is the whole of the door still open.
    _materialise(tenant=tenant, actor=actor, connection=connection)
    return connection


# --- Identity configuration as code ------------------------------------------
#
# The workflow's registered name, as a string, because `workflows` sits above
# `accounts`: this module may not import the class any more than it may import
# the starter. It matches `@workflow.defn(name=...)` in
# `apps/accounts/workflows.py`, and `apps/accounts/tests/test_workflows.py`
# drives the real discovered worker, so a name that stopped matching would fail
# a test rather than a run.
SYNC_IDENTITY_CONFIG_WORKFLOW = "SyncIdentityConfigWorkflow"

# The first segment of a workflow id the **deployment** owns rather than a
# tenant (ADR workflows-3). `WorkflowRun` is the platform-wide run ledger: its
# `tenant` is nullable, null is a declared population, and `check_workflow_id`
# requires this segment **iff** `tenant is None` — so neither population can
# wear the other's id.
#
# The value is repeated here rather than imported for the same reason
# `core.services.RESERVED_TENANT_SLUGS` repeats it: `apps.workflows` sits above
# this app and may not be imported (`core.bridge` is why the starter arrives by
# name). Two things keep the repeat honest — `check_workflow_id` refuses a
# platform start whose id does not begin with the real segment, so a drifted
# copy fails at the starter rather than mints a bad row, and
# `test_federation.py` pins this constant against
# `apps.workflows.services.PLATFORM_SEGMENT` directly.
PLATFORM_RUN_SEGMENT = "platform"


def _identity_config_key(connection: SsoConnection) -> str:
    """What makes one sync of this connection unique, and repeatable.

    The row's primary key **and a digest of the intent**, because a workflow id
    is deterministic (house rule 18) and `record_run` answers the three ways a
    repeated id can arrive: the same live id is the same run, and a *finished*
    one is a `Conflict` — "re-running completed work is a decision about a new
    key, and this layer will not make it silently".

    So the key has to say which intent this is. The primary key alone would mean
    a connection could be synced exactly once in its life; a timestamp would
    mean a retried service started a second run, which is the whole thing rule
    18 exists to prevent. A digest of what is actually being materialised —
    issuer, client id, client secret — gives both: **the same configuration
    twice is the same run, and changed configuration is a new one.** It is the
    shape `core.mail.send_mail`'s docstring names and declines for email, for
    the opposite reason: two identical reminders a week apart really are two
    sends, and two identical syncs really are one.

    The secret goes into the hash and never comes out of it: what lands in the
    workflow id is twelve hex characters, and Temporal's history is not a place
    to keep a customer's client secret.

    **A re-sync of unchanged, already-applied configuration is therefore
    refused**, with the `Conflict` `record_run` composes. That is not an
    oversight: repairing drift somebody made in the console is the
    auto-repairing reconciler ADR ident-2 deliberately did not build, with its
    trigger named. `manage.py zitadel_audit` is what makes such drift visible
    until then.
    """
    intent = "|".join(
        [
            str(connection.pk),
            connection.issuer,
            connection.client_id,
            connection.client_secret,
            # **Status is in the digest because W2-R5 made it materialise.**
            # Disabling a connection now deactivates the Zitadel provider, so
            # "active with these credentials" and "disabled with these
            # credentials" are two different things to say to Zitadel — and two
            # different things need two ids, or the second one is refused as a
            # repeat of the first.
            connection.status,
        ]
    )
    return f"{connection.pk}-{hashlib.sha256(intent.encode()).hexdigest()[:12]}"


#
#
# ADR ident-2, in one sentence: **the row is the intent, Zitadel is the
# materialisation.** The console is a window, not a door — a person can look
# through it, and nothing this product depends on is written there. What is
# written there is written by `apply_identity_config`, from what a service put
# on a row, and the resource id it got back comes home to the same row.
#
# Why this is one service and not two. "Record what we want" and "record what it
# became" are the two halves of one question about one row — *are we and Zitadel
# saying the same thing about this connection* — and splitting them into
# `sync_` and `record_` would put the row's state machine in two places, where
# the second one is the one somebody forgets. `applied` is which half is being
# spoken, and it is the activity's word: no door passes it.


@service
def sync_identity_config(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: SsoConnection,
    applied: IdentityConfigApplied | None = None,
) -> SsoConnection:
    """Make our row and Zitadel agree about this connection's identity config.

    Called with no `applied` — by a door, a command, or `create_sso_connection`'s
    caller — this records the *intent*: the row goes to `pending` and
    `SyncIdentityConfigWorkflow` is started **on commit**, never inside the
    transaction. That ordering is C2's classic and it is not negotiable: a
    management call inside the transaction means a Zitadel hiccup rolls back a
    legitimate row, and a rolled-back service leaves no run at all.

    Called with `applied` — by `apply_identity_config`, and by nothing else —
    this records the *outcome*: the Zitadel resource id lands on the row and the
    state becomes `applied`. It starts no run, which is what keeps the activity
    from re-entering the workflow that is running it.

    The workflow id is deterministic (`workflow_id`, house rule 18), keyed on
    this connection, so syncing the same row twice before the first run finishes
    is the same run rather than a second one racing it.

    **The start goes through `core.bridge`, not through an import.** `workflows`
    sits *above* `accounts` in the fixed layer contract, so naming it here would
    be the upward import that contract exists to refuse — the same inversion
    `core.mail` and `apps.events` already use, with the dependency still declared
    on this app's `AppConfig.depends_on`.
    """
    authz.require(actor, "sso_connection.update", connection)

    if applied is not None:
        connection.zitadel_idp_id = applied.resource_id
        connection.sync_state = SsoConnection.SyncState.APPLIED
        connection.save(update_fields=["zitadel_idp_id", "sync_state", "updated_at"])
        return connection

    # **The run is claimed before the row is moved**, and the order is
    # load-bearing: `record_run` is what refuses a repeat, and a refusal that
    # arrived after `sync_state` had already been written would leave a row
    # saying `pending` about a run nobody ever started. Both writes are in this
    # service's one transaction, so a refusal leaves the row exactly as it was.
    _start_identity_run(
        tenant=tenant,
        actor=actor,
        kind=KIND_SSO_CONNECTION,
        key=str(connection.pk),
        noun="identity_config",
        run_key=_identity_config_key(connection),
    )
    connection.sync_state = SsoConnection.SyncState.PENDING
    connection.save(update_fields=["sync_state", "updated_at"])
    return connection


def _start_identity_run(
    *,
    tenant: Tenant | None,
    actor: Actor,
    kind: str,
    key: str,
    noun: str,
    run_key: str,
) -> Any:
    """Start one `SyncIdentityConfigWorkflow`, on commit, under a deterministic id.

    **It returns the `WorkflowRun` row it wrote**, and the docstring below used
    to claim it wrote nothing of ours. That was wrong (AUDIT-2c's L9 check):
    `start_workflow_on_commit` writes the run's visibility row synchronously —
    only the Temporal client call is deferred to `transaction.on_commit` — so
    this helper has always left a row behind. The claim is corrected here rather
    than left to be believed, and the row is handed back so the caller's audit
    entry can name it. Typed `Any` because `core` sits below this app and the
    bridge slot is resolved by name at call time.

    The three services that materialise anything call this, so the workflow's
    name, its argument shape and the four segments of its id are written once.
    A second copy of these six lines is how one caller comes to build an id the
    others cannot find.

    **`tenant=None` is the platform population, not a missing tenant** (ADR
    workflows-3). Two of the three kinds this starts are the deployment's own
    work and belong to no customer: the workforce Google door is one instance's
    configuration, and revoking an erased person's credential is about an
    account Zitadel holds, not about any workspace they happened to be in. Those
    runs are recorded with a null tenant, under a `platform:` id, and every
    tenant door stays blind to them by construction — `for_tenant` fails closed
    and can never reach the null population.

    **And a platform run wears no hat.** `check_org_agreement` refuses an `org`
    beside a null tenant, and it is right to: an acting organization belongs to
    a tenant, so carrying the operator's branch onto a run that acts for the
    deployment would stamp a cross-population hat onto the headers the seam
    exists to keep honest.

    **Not a service and deliberately not one**: it writes nothing of ours, it is
    private to this module, and it always runs inside the transaction of the
    `@service` that called it. `_clean_domains` and `_metadata` are the same
    shape and the module docstring names all three.
    """
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    build_id = bridge.get(bridge.WORKFLOW_ID)
    if tenant is None:
        # Four segments in the house shape, with the reserved one in front.
        # `workflow_id()` builds a tenant's id from `tenant.slug` and has no
        # null to build from; `check_workflow_id` is what validates this one.
        run_id = f"{PLATFORM_RUN_SEGMENT}:accounts:{noun}:{run_key}"
    else:
        run_id = build_id(tenant=tenant, app="accounts", noun=noun, key=run_key)
    return start(
        workflow=SYNC_IDENTITY_CONFIG_WORKFLOW,
        arg=IdentityConfigSync(kind=kind, key=key),
        tenant=tenant,
        user=actor.user,
        org=actor.org if tenant is not None else None,
        id=run_id,
    )


def _materialise(*, tenant: Tenant, actor: Actor, connection: SsoConnection) -> None:
    """Ask for this connection's configuration to be put into Zitadel. **A no-op
    is not a failure.**

    Called by the three services that change a connection, which is what ADR
    ident-6 means by "re-pointed": the same signatures, the same audit, the same
    refusals — and, now, the materialisation that makes the row true of the
    identity platform rather than only of us.

    The one thing it does that `sync_identity_config` will not is **swallow the
    repeat**. Asked directly — by a door, by a command — re-syncing configuration
    that is already applied and unchanged is a `Conflict`, and that refusal is
    deliberate (ADR ident-2: repairing console drift is the reconciler nobody
    built, with its trigger named). Asked *as a side effect of a write that
    changed nothing Zitadel can see* — a renamed connection, a new default role,
    a re-issued but identical secret — a refusal would turn an ordinary update
    into a 409 for a reason the person editing has no way to understand. So the
    door keeps its refusal and the write keeps its no-op, and the difference is
    one line in a log rather than a second code path.
    """
    try:
        sync_identity_config(tenant=tenant, actor=actor, connection=connection)
    except Conflict:
        log.info(
            "accounts.identity_config.unchanged",
            connection_id=str(connection.pk),
            tenant_id=str(tenant.pk),
        )


def _workforce_config_key() -> str:
    """What makes one sync of the workforce provider unique, and repeatable.

    A digest of the environment, because **the environment is the intent** for
    this one (`apps/accounts/types.py`): there is no row, so there is no primary
    key to open the id with, and the whole key is the twelve hex characters that
    say *which* configuration this run is about. The same `GOOGLE_*` values twice
    is the same run; changed credentials or a changed domain list is a new one.

    The client secret goes in and never comes out, exactly as a connection's
    does: what reaches Temporal's history is a hash.
    """
    domains = sorted(str(one).strip().lower() for one in (settings.GOOGLE_WORKSPACE_DOMAINS or []))
    intent = "|".join(
        [
            str(settings.GOOGLE_OAUTH_CLIENT_ID or "").strip(),
            str(settings.GOOGLE_OAUTH_CLIENT_SECRET or "").strip(),
            ",".join(domains),
        ]
    )
    return f"workforce-{hashlib.sha256(intent.encode()).hexdigest()[:12]}"


@dataclass(frozen=True)
class WorkforceConfigAsked:
    """The workforce door's configuration, asked for. The run, and its key.

    **The L9 branch, stated** (ADR core-22, 2026-08-26). The ruling asked which
    of two things this service is: one that writes or materialises from OUR
    rows, or one that provably writes nothing on our side. It is the first —
    but not in the way the question assumed. There is **no workforce config
    row**: `_workforce_config_key()` is a pure function of three settings, so
    the deployment's own Google door is configuration and not a record. What the
    call does write is the **`WorkflowRun`** — synchronously, inside the
    service's transaction, because `start_workflow_on_commit` defers only the
    Temporal client call and never the visibility row.

    So the run IS the row this act produced, and it goes first: it is the only
    thing that exists afterwards to point at, and it is what an operator opens
    when they ask what became of the request. `core.service._object_of` reads it
    off this dataclass's first model field — no `audit_object` declaration is
    needed, and none is written, because the ordinary convention already covers
    a result whose row comes first.

    `key` is the deterministic segment the command prints and a test finds the
    run by. A bare `str` used to be the whole return value, which is how the
    audit row for the most privileged configuration act in the product came to
    name no object at all.
    """

    run: Any
    key: str


@service
def sync_workforce_identity_config(*, actor: Actor, tenant: Tenant | None) -> WorkforceConfigAsked:
    """Make Zitadel hold the workforce Google door this deployment is configured for.

    The sibling of `sync_identity_config`, for the provider that is nobody's
    customer: the people who build and run this product. It is here, in the same
    family, driving the same workflow through the same activity, because ADR
    ident-6's whole claim is that after W2-R5 there is **one way** identity
    configuration reaches Zitadel — and a workforce door seeded by hand in the
    console would be the exception that made the claim untrue.

    **An empty `GOOGLE_WORKSPACE_DOMAINS` refuses**, and it refuses rather than
    materialising a provider with no restriction on it. Empty means the workforce
    door is off (`config/settings/base.py`, and `selectors.get_workforce_domains`
    reads it that way); a Google IdP live in Zitadel with our side refusing every
    address it asserts is a door that looks open and is not, which is the worst
    of the three states. Fail closed, out loud.

    **Who may ask.** `identity_platform.configure` (`policies.py`), which is a
    platform operator and not a tenant's owner: this is the deployment's own
    configuration, and an owner of one customer's workspace has no business
    changing the door the staff sign in through.

    **The run is the platform's, and no longer a tenant's** (ADR workflows-3).
    It used to borrow one — any tenant would
    do — because `WorkflowRun` was tenant-scoped and a run had to land
    somewhere; the cost was that a customer's ledger carried a row about the
    deployment's own Google credentials, and their audit trail said the
    deployment's work was theirs. `WorkflowRun` is the platform-wide ledger now,
    so the run is recorded with `tenant=None` under
    `platform:accounts:identity_config:<key>` and **no tenant's ledger shows
    it** — `for_tenant` fails closed and cannot reach the null population.

    **`tenant` survives as the audit anchor, and only that.** It is optional, it
    is not where the run lands, and it names the workspace the operator happened
    to be acting in when they asked. It no longer decides *whether* there is an
    audit row, and this paragraph used to say that it did. ADR core-8 made
    `AuditEntry.tenant` nullable (`core` migration 0013) and made `@service`
    audit on the **declaration**: a service taking a keyword-only `tenant`, as
    this one does, leaves a row on every call, and the value decides only which
    population the row joins. So the ask is audited whether or not `--tenant` is
    passed; omit it (which `manage.py sync_workforce_idp` now does by default)
    and the row lands in the platform population — `tenant` NULL, readable
    through `AuditEntry.objects.for_platform()` and through no customer's
    ledger. That is the closure `erase_user`'s docstring records; the gap both
    docstrings used to name is closed, not still open.

    Returns the workflow id, so a command can print it and a test can find the
    run without rebuilding the key.
    """
    authz.require(actor, "identity_platform.configure", tenant)

    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        raise Invalid(
            {"google": ["GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are required."]},
            detail=(
                "This deployment has no Google credentials, so there is no workforce "
                "door to materialise. Set GOOGLE_OAUTH_CLIENT_ID and "
                "GOOGLE_OAUTH_CLIENT_SECRET in .env first."
            ),
        )
    if not settings.GOOGLE_WORKSPACE_DOMAINS:
        raise Invalid(
            {"google": ["GOOGLE_WORKSPACE_DOMAINS must name at least one domain."]},
            detail=(
                "GOOGLE_WORKSPACE_DOMAINS is empty, which means the workforce door is "
                "off. Materialising a Google provider with no domain restriction would "
                "put a door in Zitadel that this product refuses everybody at."
            ),
        )

    run_key = _workforce_config_key()
    # `tenant=None`, always — the argument above is the audit anchor and never
    # the run's scope. Passing it through here would be exactly the borrowing above.
    run = _start_identity_run(
        tenant=None,
        actor=actor,
        kind=KIND_WORKFORCE_PROVIDER,
        key=run_key,
        noun="identity_config",
        run_key=run_key,
    )
    return WorkforceConfigAsked(run=run, key=run_key)


# --- Just-in-time provisioning -----------------------------------------------


class SsoRefused(Conflict):
    """An assertion this product will not turn into a session.

    A `Conflict` subclass rather than `Forbidden`, and the difference matters at
    the door: nobody was *denied permission* — the assertion itself was not
    something we accept (an unverified address, a domain this connection does
    not claim). `config/api.py` maps it to 409 through the ordinary MRO walk,
    and the browser flow renders it as a page.
    """


# door: the browser SSO login flow is its door, and `apps/accounts/adapter.py`
# is where allauth calls it — a door mounted the way a third-party integration
# mounts one rather than the way the four mounts discover one, which is exactly
# the blind spot rule 42 declares. It must not grow a door of its own: every
# caller of this arrives holding an assertion the IdP just made, and a route
# that took `subject` and `email` as a body would be a route that provisions
# anybody as anybody.
@service
def provision_sso_identity(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: SsoConnection,
    subject: str,
    email: str,
    email_verified: bool,
) -> SsoIdentity:
    """Turn one accepted assertion into a user, an identity and a membership.

    Called by `accounts.adapter.SocialAccountAdapter.pre_social_login` with a
    `system` actor, and by nothing else. It is the whole of JIT provisioning,
    and idempotent: a second login finds the identity, touches `last_seen_at`.

    Three refusals, in order:

    1. **The IdP must say the address is verified.** An IdP that asserts an
       address it has not verified is asserting whatever the person typed into
       their profile — and this product links that address to a local account.
       Without the verified flag, `alice@acme.com` at the IdP is a claim, not a
       fact, and honouring it is account takeover with extra steps.
    2. **The address must be in a domain this connection claims.** Otherwise a
       tenant's own IdP could mint an identity for `someone@other-customer.com`,
       authenticating for a domain it does not own.
    3. **An address already belonging to somebody in another tenant** is not
       taken over. Domains are unique across tenants, so this can only happen
       when a claim moved; the refusal is loud rather than silent.

    What it does **not** do is grant anything beyond `connection.default_role`.
    Roles are data and the connection's data says one role; a product that wants
    group-to-role mapping writes it as a service in its own app, over the claims
    it has decided to trust — and no more than `connection.default_role` says,
    which `_refuse_role_above_the_configurer` bounded when a person wrote it.
    """
    authz.require(actor, "sso_identity.provision", connection)

    address = (email or "").strip().lower()
    if not email_verified:
        raise SsoRefused(
            "Your identity provider did not confirm that this email address is verified, "
            "so this product will not create or link an account with it."
        )
    if not address:
        raise SsoRefused("Your identity provider asserted no email address.")

    claimed = {
        row.domain for row in SsoDomain.objects.for_tenant(tenant).filter(connection=connection)
    }
    if domain_of(address) not in claimed:
        raise SsoRefused(
            "That email address is outside the domains this identity provider is configured for."
        )

    existing = SsoIdentity.objects.for_subject(connection=connection, subject=subject)
    if existing is not None:
        existing.email = address
        existing.last_seen_at = now()
        existing.save(update_fields=["email", "last_seen_at", "updated_at"])
        ensure_membership(user=existing.user, tenant=tenant, role=connection.default_role)
        return existing

    user = User.objects.filter(email=address).first()
    if user is None:
        # No password, and that is the point: an account that only ever exists
        # because an IdP asserted it must not also have a second way in that the
        # IdP cannot revoke.
        user = create_user(email=address, password=None)
    elif Membership.objects.filter(user_id=user.pk).exclude(tenant=tenant).exists() and not (
        Membership.objects.filter(user_id=user.pk, tenant=tenant).exists()
    ):
        raise SsoRefused(
            "That email address already belongs to an account in another workspace. "
            "An administrator has to move it before this identity provider can use it."
        )

    identity = SsoIdentity(
        tenant=tenant,
        connection=connection,
        user=user,
        subject=subject,
        email=address,
        last_seen_at=now(),
    )
    with as_invalid():
        identity.full_clean()
    identity.save()
    ensure_membership(user=user, tenant=tenant, role=connection.default_role)
    return identity


# door: a step of `provision_sso_identity`, inside its transaction, and the one
# service here that must NEVER be given a door. It takes a `role` and no
# granter, because the granter is a connection's `default_role` and there is no
# person to bound it against — which is safe exactly as long as the only caller
# is the login flow that read that role off a connection an owner configured. A
# route or a tool onto this would be a way to grant a membership at any role
# with nobody's ceiling above it: the escalation wall, walked around through the
# front door.
@service
def ensure_membership(*, user: User, tenant: Tenant, role: str) -> Membership:
    """This user's membership of this tenant, created at `role` if there is none.

    **It never changes an existing role**, and that asymmetry is deliberate: a
    person promoted to admin by a human must not be demoted to `member` by their
    next login, and a connection's `default_role` is a statement about *new*
    people. Changing somebody's role is `core.services.set_role`, which says so
    in the audit trail.

    **`add_membership` is called with no `actor`, and that is correct**: nobody
    is granting here — an identity provider asserted an identity — so the
    escalation wall has no granter to measure and short-circuits. The ceiling
    that would otherwise be missing is applied where a person actually acts, on
    the connection itself (`_refuse_role_above_the_configurer`). That is the
    only place in this path where there is a granter at all.
    """
    membership = Membership.objects.filter(user_id=user.pk, tenant=tenant).first()
    if membership is not None:
        return membership
    is_first = not Membership.objects.filter(user_id=user.pk).exists()
    return add_membership(
        user=user, tenant=tenant, is_default=is_first, role=role, actor=system_actor(tenant=tenant)
    )


# --- The platform identity join ----------------------------------------------
#
# ADR ident-4. Zitadel hosts every interactive authentication now, so
# everybody who signs in has a `sub` there — and exactly one column joins that
# fact to this product's `User`.


@service
# rule-13: still not a tenant-owned write. A person's Zitadel subject is a fact
# about them and not about any customer — they may hold memberships in several
# tenants or, on a first login, in none at all — and `tenant` below is therefore
# an audit-population SELECTOR and never a filter, exactly as it is on
# `erase_user` and `redact_invitations`.
#
# **N79b, and what actually changed.** This service used to declare no `tenant`
# at all, which under ADR core-8's mechanism is the declaration "I am not about
# a tenant's rows" — and `@service` reads the signature, so the identity join
# left no audit row anywhere. That was the last gap in the identity ledger: the
# one column that decides which Zitadel account signs in as which of our people
# was written on every login with nothing recording it. Declaring the parameter
# is the whole fix; the value is `None` in practice, because the join belongs to
# the deployment rather than to any customer, and the row lands in the platform
# population readable through `AuditEntry.objects.for_platform()`.
#
# The rule-13 sentence above is why this is a DECLARATION and not a schema
# change: `AuditEntry.tenant` has been nullable since `core` migration 0013 and
# null has been a declared population since ADR core-8. Nothing here was
# forbidden; nobody had asked.
#
# door: `apps/accounts/adapter.py` — the allauth social-login callback — is its
# door, and it is the same unconventional mount `provision_sso_identity` sits
# behind. A door of its own would be worse than none: `subject` is the column
# that decides which Zitadel account signs in as which of our people, so a route
# that accepted one would be a route for claiming somebody else's identity.
def record_zitadel_identity(
    *, user: User, subject: str, tenant: Tenant | None, actor: Actor
) -> User:
    """Record which Zitadel subject this person is. **The one writer.**

    Called from `accounts.adapter.SocialAccountAdapter` at the moment the
    platform IdP asserts an identity, and from nowhere else: a second writer is
    how a join between two identity systems comes to disagree with itself.

    **Keyed on the subject, not the address**, for the reason `SsoIdentity`
    already gives: an address is a label an employer can reassign, and keying on
    it is how somebody inherits their predecessor's access along with their
    desk. The column is unique, so a subject already claimed by somebody else is
    a `Conflict` rather than a silent re-point — that shape is an account
    takeover with an extra step.

    Idempotent: the same subject for the same user is a no-op, which matters
    because this runs on **every** login and not only the first. **The audit row
    is not** — one per call, no-op included, because "the platform asserted this
    identity again" is the fact the ledger is being asked for. The `subject`
    itself never reaches the row: it is not in this app's `LOG_KEYS`, so the
    trail says a join was recorded and for whom, and not what was asserted.
    """
    cleaned = str(subject or "").strip()
    if not cleaned:
        raise Invalid(
            {"subject": ["An identity provider must assert a subject."]},
            detail="That sign-in carried no subject, so it cannot be joined to an account.",
        )
    if user.zitadel_sub == cleaned:
        return user

    claimed = User.objects.filter(zitadel_sub=cleaned).exclude(pk=user.pk).first()
    if claimed is not None:
        raise Conflict("That identity is already linked to a different account.")

    user.zitadel_sub = cleaned
    user.save(update_fields=["zitadel_sub", "updated_at"])
    return user
