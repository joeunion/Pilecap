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

from apps.accounts.events import IDENTITY_HOME_CREATED
from apps.accounts.models import (
    CLIENT_ID_KEY,
    CLIENT_SECRET_KEY,
    ISSUER_KEY,
    STAFF_REALM,
    ApiToken,
    FirstAdminVouch,
    IdentityBranding,
    IdentityHome,
    SsoConnection,
    SsoDomain,
    SsoIdentity,
    User,
    domain_of,
    normalise_domain,
)
from apps.accounts.schemas import IdentityHomeOut
from apps.accounts.selectors import (
    DIRECT_GOOGLE_PROVIDER,
    get_direct_google_links,
    get_first_admin_vouch,
    get_platform_provider_id,
    list_tenants_this_user_alone_owns,
)
from apps.accounts.types import (
    KIND_IDENTITY_BRANDING,
    KIND_IDENTITY_REVOCATION,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
    IdentityConfigApplied,
    IdentityConfigSync,
    IdentityHomeAsk,
)
from apps.core import authz, bridge
from apps.core.actor import Actor, system_actor
from apps.core.authz import OWNER_ROLE, default_role_key, role_declarations
from apps.core.exceptions import Conflict, Invalid, NotFound, Remedy, as_invalid, register_refusal
from apps.core.ids import uuid7
from apps.core.log import get_logger
from apps.core.middleware import resolve_tenant
from apps.core.models import Membership, Role, Tenant
from apps.core.schemas import event_payload
from apps.core.service import service
from apps.core.services import (
    _refuse_escalation,
    add_membership,
    redact_invitations,
    root_organization,
)

# Re-exported under their own names: the redundant alias is `mypy --strict`'s explicit form.
from apps.core.services import close_sockets as close_sockets
from apps.core.services import close_sockets_on_commit as close_sockets_on_commit
from apps.core.surfaces import Surface, surface_for_role
from apps.core.time import now

log = get_logger(__name__)

TOKEN_PREFIX = "djb"  # noqa: S105 — the public prefix every minted API token starts with
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
# **The implementation moved; the vocabulary did not.** An earlier rung wrote
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
KICK_TOKEN_REVOKED = "accounts.token.revoked"  # noqa: S105 — the event name a revoked token's socket kick carries
KICK_USER_ERASED = "accounts.user.erased"
KICK_USER_DEACTIVATED = "accounts.user.deactivated"
KICK_IDENTITY_REVOKED = "accounts.identity.revoked"
# A join cut on purpose, which is not a revocation and not a deactivation: the
# account is untouched and the person simply has to prove who they are again.
KICK_USER_IDENTITY_UNLINKED = "accounts.user.identity_unlinked"

# THE ONE SENTENCE A SWITCHED-OFF ACCOUNT READS, at whichever of the three doors
# it arrives at. One constant because three branches say it and a wall that says
# three different things is three walls; and it names no tenant and no
# connection, because the page it reaches is public — "this account is off" is
# all a refused caller is owed, and anything more answers questions about the
# deployment for anybody who can start a login.
INACTIVE_SENTENCE = (
    "This account has been switched off, so it cannot be used to sign in. "
    "Ask an administrator of your workspace."
)


class Authenticated(NamedTuple):
    """What a valid bearer token resolves to: a user, a tenant, and the row itself.

    The token row is part of the answer because the audit trail needs it: "this
    person did it" and "an integration this person installed did it" are
    different facts about the same user, and only the token tells them apart.
    """

    user: User
    tenant: Tenant | None
    token: ApiToken


# door: no door reaches it - the seed command and a first SSO sign-in's account make people
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

    **The signature grew an `actor` and a `tenant` when the doors landed, and both were
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
    # hat-scoped: the third argument is the ROW because the predicate reads it —
    # "themselves, or administers the whole tenant". The NODE is resolved inside
    # `themselves_or_administers_the_whole_tenant`, which measures the tenant's
    # ROOT (ADR ident-6) and not the acting hat, so a branch administrator's `*`
    # never reaches here. Rule 55's own `does_not_cover` names this predicate as
    # the code half it cannot see into; this is the sentence it asks for.
    authz.require(actor, "user.deactivate", user)
    _refuse_a_person_outside_this_actors_tenant(user=user, actor=actor)
    user.is_active = False
    user.save(update_fields=["is_active", "updated_at"])
    close_sockets_on_commit(user_id=user.pk, reason=KICK_USER_DEACTIVATED)
    return user


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

    * the email address, replaced by `erased+<uuid>@erased.invalid` — unique, so the
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
    the person (ADO-4); and the identity join's rows, opaque subjects kept as the
    fence that refuses a re-link of those platform accounts to anybody else's row. A
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
    # hat-scoped: the third argument is the ROW because the predicate reads it —
    # "themselves, or administers the whole tenant". The NODE is resolved inside
    # `themselves_or_administers_the_whole_tenant`, which measures the tenant's
    # ROOT (ADR ident-6) and not the acting hat, so a branch administrator's `*`
    # never reaches here. Rule 55's own `does_not_cover` names this predicate as
    # the code half it cannot see into; this is the sentence it asks for.
    authz.require(actor, "user.erase", user)
    _refuse_a_person_outside_this_actors_tenant(user=user, actor=actor)

    orphaned = list_tenants_this_user_alone_owns(user=user)
    if orphaned:
        raise Conflict(
            "That person is the only owner of "
            + ", ".join(sorted(one.slug for one in orphaned))
            + ". Make somebody else an owner first, or the tenant is left with nobody "
            "who can administer it.",
            remedies=LAST_OWNER_REMEDIES,  # see the note above this function
        )

    address = user.email
    # authz-kind: the rows written are `ApiToken`s and the key asked is
    # `user.erase`, deliberately. An erasure is one act on one person, and every
    # credential that person holds dies with them — a caller who could erase the
    # account but not revoke its tokens would leave live keys behind a dead
    # account, which is the exact residue erasure exists to remove. The tokens
    # are not a second decision with a second wall; they are the first one
    # reaching everything the person had. `api_token.revoke` is the key for
    # revoking ONE token on a living account, and it has its own service.
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
# **Why the enumeration is not the guarantee.** A probe found the person in four
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
    * **`SsoIdentity.email`** — REDACTED to the `erased+<uuid>@erased.invalid` form the
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
    if not Membership.objects.for_tenant(actor.tenant).filter(user_id=user.pk).exists():
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

    **One honest skip**, logged rather than swallowed: a person with no subject
    in the identity join has never signed in through the platform, so there is
    no account to deactivate. **Every subject they hold is revoked, per realm**
    — a person in two tenants is two platform accounts, and the run deactivates
    each in its own realm through the realm port.

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
    if not user.sso_identities.filter(connection__isnull=True).exists():
        return None
    run_key = str(user.pk)
    try:
        _start_identity_run(
            tenant=None,
            actor=actor,
            arg=IdentityConfigSync(kind=KIND_IDENTITY_REVOCATION, key=run_key),
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
    surface: Surface | None = None,
) -> Authenticated | None:
    """Resolve a bearer token to the user, tenant and token row it acts as.

    **Authentication only. It answers WHO, never WHERE-you-may-act** — that is
    the addressing-header law's half, and it lives in one place for every door
    (`core.middleware.addressing_refusal`; ADR core-21).

    A token pinned to a tenant acts in that tenant and nowhere else **while that
    tenant is ACTIVE**: a pinned token to a suspended or closed tenant
    authenticates — it is a real credential, presented by a real person, and the
    touch below records that it was used — and resolves NOWHERE, which the door
    then says in its own words (ADR core-21). Suspension is an operator's act
    that takes a tenant dark; a credential that kept working into it would make
    the act a suggestion. The status is read through `Tenant.is_active`, the one
    predicate that spells `ACTIVE`, so there is never a second spelling of it
    here. **And while the door's surface admits the person there**: a pin is a
    tenant, never a role, so a customer's token pinned to her tenant resolves
    nowhere at the staff host — as her session does — and an owner's resolves
    nowhere at the customer host (`_admits_the_pin`).

    So this returns the pin whatever `X-Tenant` asked for, and the door then
    refuses a request that asked for a different one. It used to return `None` here — the
    credential simply *failing* — and the wire said **401 "We could not tell who
    is making this request"** over a live, unrevoked token belonging to a real
    active user. That fact was false, which E9's
    grammar refuses; the truthful answer is authenticated-then-refused, and it
    can only be given by something that authenticated first.

    A token without a pin resolves the tenant the same way a signed-in request
    does, from the user's memberships under the SURFACE the door resolved — its
    tenant rule and the roles it admits — so the machine door and the human door
    cannot disagree about who can see what, on any host.
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
        pinned = token.tenant if token.tenant.is_active else None
        if pinned is not None and not _admits_the_pin(surface, user=token.user, tenant=pinned):
            pinned = None
        return Authenticated(token.user, pinned, token)
    touch_token(token=token)
    return Authenticated(
        token.user,
        resolve_tenant(user=token.user, requested_slug=requested_slug, surface=surface),
        token,
    )


def _admits_the_pin(surface: Surface | None, *, user: User, tenant: Tenant) -> bool:
    """Whether the door's surface admits this person in the pinned tenant — the session's law.

    A surface admits the roles that belong to it (`core.surfaces.surface_for_role`:
    a role belongs to one surface), so a pinned token acts in its tenant here only
    when its person holds a membership there in a role this surface admits —
    exactly the membership `resolve_tenant` would have counted for their session.
    No surface resolved (a door driven below the stack) is today's answer: the pin.
    """
    if surface is None:
        return True
    held = Membership.objects.for_tenant(tenant).filter(user_id=user.pk)
    roles = held.values_list("role", flat=True)
    return any(surface_for_role(role).key == surface.key for role in roles)


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


def _refused_mail_domains() -> frozenset[str]:
    """The public mail providers no tenant may claim, from settings.

    Read at call time rather than frozen at import so a deployment's own list —
    and a test's `settings` fixture — is the one that answers. The list is
    `SSO_REFUSED_MAIL_DOMAINS` in `config/settings/base.py`, where its own
    comment says why it is a courtesy and not the wall: a claim routes nobody
    until an operator verifies it (a domain claim routes nothing until it is verified), so a
    consumer domain missing
    from this list is a reserved claim that answers nobody, not a capture.
    """
    return frozenset(
        str(domain).strip().lower().lstrip("@")
        for domain in getattr(settings, "SSO_REFUSED_MAIL_DOMAINS", [])
        if str(domain).strip()
    )


def _clean_domains(values: Sequence[str]) -> list[str]:
    """Normalise, validate and de-duplicate a set of claimed domains."""
    cleaned: list[str] = []
    refused = _refused_mail_domains()
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
        if domain in refused:
            # **Caught where the mistake is made.** Somebody typing their own
            # address's domain into "which domains does your identity provider
            # own" is the common shape of this, and the honest place to say so
            # is the response to that request — not a reserved claim nobody
            # notices until an operator is asked to verify a domain the tenant
            # plainly does not own.
            raise Invalid(
                {
                    "email_domains": [
                        f"{domain} is a public mail provider, not an organisation's domain."
                    ]
                },
                detail=(
                    f"{domain} is a public mail provider, not an organisation's domain. "
                    "An identity provider claims the domains its organisation owns."
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

    **And the key is checked against the roles that EXIST, before the wall.**
    `SsoConnection.default_role` used to be a three-value enum, so the column
    itself refused a word no role answered to; roles are rows a tenant owns now
    and the enum is gone (`models.py`), which would have left a connection able
    to store `default_role="auditr"` and mint memberships at a role nobody
    declared — a membership holding nothing, discovered by the person who could
    not do their job. So the key is validated here, where a human is typing it,
    against the three places a role can come from: the reserved `owner`, the
    roles this deployment DECLARES (`apps/*/roles.py`), and the `core.Role` rows
    this tenant owns. `Invalid`, not `Forbidden` — this is a malformed field and
    not a refused act, and the two read differently to the person reading them.

    The validation runs BEFORE the ceiling for the reason every validator runs
    first: "there is no such role" and "you may not grant that role" are
    different sentences, and a caller who typed a name nobody has should not be
    told they lack the authority for it.
    """
    if role is None:
        return
    known = (
        {OWNER_ROLE}
        | set(role_declarations())
        | set(Role.objects.for_tenant(tenant).values_list("key", flat=True))
    )
    if role not in known:
        raise Invalid(
            {"default_role": [f"There is no role {role!r} in this tenant."]},
            detail=(
                "A connection's default role has to be a role that exists: the "
                "tenant's owner, a role this deployment declares, or a role this "
                "tenant made."
            ),
        )
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
    default_role: str = "",
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

    **RECORDED, not fixed.** An unsaid `default_role` resolves to
    `default_role_key()`. A product whose `roles.py` marks NO role
    `is_default_for_new_members` gets `""` from it, and
    `_refuse_role_above_the_configurer` then refuses with *"There is no role
    ''"*. That is failing closed — the alternative is a connection minting
    roleless memberships on every SSO login — but the sentence names the empty
    string rather than the missing declaration, which is a worse sentence than
    the situation deserves. The fix is a refusal that says *this deployment
    declares no default role*, and it belongs with `roles.py`'s own census
    rather than in this app.
    """
    # **AT THE ROOT, not at the acting hat.** A connection is the tenant's
    # identity: its claims route every address at its domains and its
    # `default_role` lands a membership on the root. Asked at the hat, an
    # administrator of one branch held it — and renamed, re-claimed,
    # enforced and deleted the owner's connection over the wire. The shape
    # is `update_tenant_settings`' (`core/services.py`), for the same reason.
    authz.require(actor, "sso_connection.create", root_organization(tenant=tenant))
    # An unsaid `default_role` is "whatever this deployment says a new member
    # is" — `default_role_key()`, the one answer `add_membership` would have
    # reached for anyway — and never the word `member` spelled here. A product
    # whose declared default is `viewer` used to get `member` out of this
    # signature, which is a role its `roles.py` may not even declare.
    default_role = default_role or default_role_key()
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


# `enforced` switched on over a connection whose identity provider has not
# reached the identity platform: the wall would stand with no door in it. E9's
# grammar — the fact, the remedy for the reader of the registry, the remedies a
# caller can press — declared beside the raise site.
register_refusal(
    code="enforced_without_provider",
    boundary="service",
    remedy=(
        "The connection's identity provider has not been materialised at the identity "
        "platform yet (no provider id, or its last sync is not applied), so a login "
        "policy requiring it would lock every person it covers out. Let the sync land — "
        "an operator runs manage.py zitadel_reconcile if it failed — then set enforced."
    ),
    fact=(
        "This identity provider is not set up at the identity platform yet, so requiring "
        "it would leave the people it covers with no way to sign in. Nothing was changed."
    ),
    remedies=(
        Remedy("Read the provider back until it says it is applied", "route:sso-connection-list"),
        Remedy("Require it once it is applied", "route:sso-connection-update"),
    ),
    status=409,
)


class EnforcedWithoutProvider(Conflict):
    """`enforced` asked of a connection with no provider materialised to require."""

    code = "enforced_without_provider"
    default_detail = (
        "This identity provider is not set up at the identity platform yet, so it cannot "
        "be required."
    )


def _refuse_enforcing_without_a_provider(
    *, connection: SsoConnection, enforced: bool | None
) -> None:
    """The flip to `enforced` needs a provider that already landed; the flip is refused first.

    Only the switch ON is asked: turning `enforced` off, or sending it true again
    over a connection that already enforces, takes nothing away from anybody.
    """
    if not enforced or connection.enforced:
        return
    landed = bool(connection.zitadel_idp_id) and (
        connection.sync_state == SsoConnection.SyncState.APPLIED
    )
    if not landed:
        raise EnforcedWithoutProvider()


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
    # At the root: this row is the tenant's, not a branch's (see `create`).
    authz.require(actor, "sso_connection.update", root_organization(tenant=tenant))
    _refuse_role_above_the_configurer(tenant=tenant, actor=actor, role=default_role)
    _refuse_enforcing_without_a_provider(connection=connection, enforced=enforced)
    before = _identity_config_key(connection)

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
    _materialise(tenant=tenant, actor=actor, connection=connection, before=before)
    # The caller's prefetched `domains` predate `_apply_domains`; answer the stored row.
    connection.refresh_from_db()
    return connection


@service
def disable_sso_connection(
    *, tenant: Tenant, actor: Actor, connection: SsoConnection
) -> SsoConnection:
    """Stop this identity provider being able to sign anybody in.

    **The row and its domain claims stay.** Deleting them would free the domain
    for another tenant to claim while this one is mid-migration, and would take
    the `SsoIdentity` rows — the record of who arrived through it — with them.
    Its verified claims still confine their people to the tenant's realm
    (`get_dormant_claim_tenant`), and `enforced` stops applying: they sign in there by password.
    """
    # At the root: this row is the tenant's, not a branch's (see `create`).
    authz.require(actor, "sso_connection.disable", root_organization(tenant=tenant))
    before = _identity_config_key(connection)
    connection.status = SsoConnection.Status.DISABLED
    connection.disabled_at = now()
    connection.save(update_fields=["status", "disabled_at", "updated_at"])
    # **And Zitadel is told.** Without this, disabling stopped our own callback and
    # left the identity platform perfectly willing to sign the same people in —
    # which, once Zitadel fronts every IdP, is the whole of the door still open.
    _materialise(tenant=tenant, actor=actor, connection=connection, before=before)
    return connection


# door: `manage.py verify_sso_domain` is its door, at the deployment operator's
# altitude — the same place `bootstrap_tenant` and `unlink_identity` stand. A
# route onto this would be a tenant confirming its own claim, which is the
# entire question this service exists to ask somebody else; the wall below is
# written anyway (C7) so that the day a product ships self-serve verification
# behind a real check, the seam and its refusal already exist.
@service
# rule-16: "verify" is the verb and it is the exact one — this CONFIRMS a claim
# an administrator made and nothing else; `approve` is a judgement about
# content, `confirm` is the second half of a two-phase write the first half
# started, `check` is a predicate that answers rather than writes, and `mark`
# describes the column instead of the act. Widening `service_verbs` for the
# whole template is the other road and it belongs to whoever owns `quality/`
# (R2-E1's rung), not to a fix rung in `accounts`.
def verify_sso_domain(
    *, tenant: Tenant, actor: Actor, connection: SsoConnection, domain: str
) -> SsoDomain:
    """Record that an operator confirmed this tenant owns this domain.

    **The act that makes a claim route** (a domain claim routes nothing until it is verified).
    Claiming a domain is
    something any administrator of any tenant can do and it reserves a name;
    ROUTING the platform's sign-in for everybody at that domain is something
    else entirely, and until this service has run, `for_domain` sends those
    people exactly where an unclaimed address goes.

    **An operator's act, deliberately, and not the tenant's own.** The tenant
    asking to be trusted cannot be the party that says it is trusted; the
    deployment's operator is the trust root, `manage.py verify_sso_domain` is
    the door they stand at, and the audit row is the trail. DNS TXT proof is
    the obvious successor and is deliberately NOT here: it buys a resolver
    dependency, a workflow and a token column for a population of zero, and the
    trigger to build it is the first product that wants tenants to verify
    themselves — at which point this service is the seam that activity calls,
    unchanged.

    **Not there is not yours.** A domain this connection does not claim is
    `NotFound` whoever holds it — the same answer for "nobody claims it" and
    "another tenant does", because a verification door that distinguished them
    would answer "does anybody claim this domain" for anyone who can reach it.

    **Idempotent, and audited every time.** A second call returns the row
    unchanged and still files its receipt: "an operator asserted this domain
    again" is a fact the ledger is being asked for, which is
    `record_identity`'s precedent exactly. The row is locked while it is
    read and written so two operators verifying at once serialize rather than
    race (E8).
    """
    # At the root, at the same height as the three keys above: a verified
    # claim routes the whole tenant's sign-in.
    authz.require(actor, "sso_domain.verify", root_organization(tenant=tenant))
    cleaned = normalise_domain(domain)
    row = (
        SsoDomain.objects.for_tenant(tenant)
        .select_for_update()
        .filter(connection=connection, domain=cleaned)
        .first()
    )
    if row is None:
        raise NotFound(f"{cleaned or domain} is not one of this connection's claimed domains.")
    if row.verified_at is not None:
        return row
    row.verified_at = now()
    row.save(update_fields=["verified_at", "updated_at"])
    log.info(
        "accounts.sso_domain.verified",
        tenant_id=str(tenant.pk),
        connection_id=str(connection.pk),
    )
    return row


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


def _with_observed(key: str, observed: str) -> str:
    """The run key, plus a digest of WHAT WAS SEEN when the ask came from a reader.

    **Why a key needs this at all.** A workflow id is deterministic (house rule
    18) and keyed on the intent, so asking twice for the same intent is one run
    — which is exactly right until the thing that changed is not our intent but
    Zitadel's copy of it. A console edit leaves the intent byte-identical, so
    the key is byte-identical, so `record_run` refuses the ask as a repeat of
    the run that already landed ("running the same work again is a new job, not
    a repeat of that one"). Correct in general, and fatal to a reconciler: the
    one caller whose whole job is to re-ask for an intent nobody changed.

    So the reconciler hands over the OBSERVATION — the audit's own line about
    what Zitadel said — and it joins the key. What follows is the pair of
    properties the reconciler needs and nothing more: **the same observation
    twice is one run** (an operator running it again because they were not sure
    the first one took is not a second ask), and **a different observation is a
    second run** (this week's console edit is not last week's).

    **A digest, never the sentence.** An observed line carries whatever somebody
    else's console wrote, and Temporal's history is not the place for an
    unbounded foreign string — the same reasoning that keeps a client secret out
    of `_identity_config_key`'s output. Twelve hex characters, and a hyphen,
    which is the separator every key in this family already uses.

    **An empty observation changes nothing, byte for byte.** Every existing
    caller passes one by not passing it, so the key they build has to be the key
    they have always built; the reconciler is the only caller that says anything.
    """
    if not observed:
        return key
    return f"{key}-{hashlib.sha256(observed.encode()).hexdigest()[:12]}"


def _identity_config_key(
    connection: SsoConnection, *, observed: str = "", generation: str = ""
) -> str:
    """One sync's run key: the row, a digest of its intent, and the write's generation if given.

    The same intent twice is the same run (rule 18); the secret enters the digest and never leaves.
    """
    intent = "|".join(
        [
            str(connection.pk),
            connection.issuer,
            connection.client_id,
            connection.client_secret,
            # Status and `enforced` both materialise, so each is part of the intent.
            connection.status,
            str(connection.enforced),
        ]
    )
    key = f"{connection.pk}-{hashlib.sha256(intent.encode()).hexdigest()[:12]}"
    if generation:
        key = f"{key}-{hashlib.sha256(generation.encode()).hexdigest()[:12]}"
    return _with_observed(key, observed)


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


# door: never a door's own call - the realm activity, zitadel_reconcile, the SSO connection writes
@service
def sync_identity_config(
    *,
    tenant: Tenant,
    actor: Actor,
    connection: SsoConnection,
    observed: str = "",
    generation: str = "",
    applied: IdentityConfigApplied | None = None,
) -> SsoConnection:
    """Make our row and Zitadel agree about this connection's identity config.

    No `applied`: record the intent and start the run on commit (ADR ident-2). With `applied`
    (the activity only): record the outcome and start nothing.
    `observed` is the reconciler's argument; `generation` is a write's whose intent moved.
    """
    # The wall behind `update_sso_connection`'s own ask: the same key at the root,
    # asked only when a change reaches the identity platform's configuration.
    authz.require(actor, "sso_connection.update", root_organization(tenant=tenant))

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
        arg=IdentityConfigSync(kind=KIND_SSO_CONNECTION, key=str(connection.pk)),
        noun="identity_config",
        run_key=_identity_config_key(connection, observed=observed, generation=generation),
    )
    connection.sync_state = SsoConnection.SyncState.PENDING
    connection.save(update_fields=["sync_state", "updated_at"])
    return connection


def _start_identity_run(
    *,
    tenant: Tenant | None,
    actor: Actor | None,
    arg: Any,
    noun: str,
    run_key: str,
    workflow: str = SYNC_IDENTITY_CONFIG_WORKFLOW,
) -> Any:
    """Start one identity run, on commit, under a deterministic id.

    `SyncIdentityConfigWorkflow` unless `workflow` names the other one this app
    starts from a service — `EnsureTenantIdentityHomeWorkflow`, whose argument
    is the tenant rather than a configuration row. One starter for both, so the
    id's four segments and the re-ask policy are written once.

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
        workflow=workflow,
        arg=arg,
        tenant=tenant,
        user=actor.user if actor is not None else None,
        org=actor.org if tenant is not None and actor is not None else None,
        id=run_id,
        # **The honest retry, for all three kinds at once.** A materialisation
        # that FAILED — Zitadel down, a PAT expired, a credential rotated —
        # leaves a finished run under the intent's own deterministic key, and
        # without this the only way to ask again is to change the intent, which
        # is the opposite of what the operator wants. Identity configuration is
        # idempotent by construction (`ensure_*` is given the id our row already
        # recorded), so re-running it is safe and the receipt `record_run` files
        # says what the re-ask replaced. A COMPLETED run is still a `Conflict`
        # — this is a re-ask after failure, not a licence to re-run work that
        # landed; `observed` is what asks about landed work.
        reask_after_failure=True,
    )


def _materialise(
    *, tenant: Tenant, actor: Actor, connection: SsoConnection, before: str = ""
) -> None:
    """Ask for this connection's configuration to be materialised: one run per intent change.

    A write whose intent moved keys its run on the intent plus the write's own moment, so a
    change back to an earlier intent is a new run, never a ride on a live or landed one.
    A write that changed nothing Zitadel can see asks nothing.
    """
    if before and before == _identity_config_key(connection):
        log.info(
            "accounts.identity_config.unchanged",
            connection_id=str(connection.pk),
            tenant_id=str(tenant.pk),
        )
        return
    sync_identity_config(
        tenant=tenant,
        actor=actor,
        connection=connection,
        generation=connection.updated_at.isoformat() if before else "",
    )


def _workforce_config_key(*, observed: str = "") -> str:
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
    return _with_observed(f"workforce-{hashlib.sha256(intent.encode()).hexdigest()[:12]}", observed)


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


# door: only this tree's own hands reach it - sync_workforce_idp and zitadel_reconcile
@service
def sync_workforce_identity_config(
    *, actor: Actor, tenant: Tenant | None, observed: str = ""
) -> WorkforceConfigAsked:
    """Make Zitadel hold the workforce Google door this deployment is configured for.

    The sibling of `sync_identity_config`, for the provider that is nobody's
    customer: the people who build and run this product. It is here, in the same
    family, driving the same workflow through the same activity, because ADR
    ident-6's whole claim is that there is **one way** identity
    configuration reaches Zitadel — and a workforce door seeded by hand in the
    console would be the exception that made the claim untrue.

    **An empty `GOOGLE_WORKSPACE_DOMAINS` refuses**, and it refuses rather than
    materialising a provider with no restriction on it. Empty means the workforce
    door is off (`config/settings/base.py`, and `selectors.get_workforce_domains`
    reads it that way); a Google IdP live in Zitadel with our side refusing every
    address it asserts is a door that looks open and is not, which is the worst
    of the three states. Fail closed, out loud.

    **Except when the caller says it has LOOKED, and that is the take-down
    road.** The refusal above reads an empty domain list as "you forgot to
    configure this", which is the right reading of a bare ask — nobody asks a
    materialiser to materialise nothing. It is the wrong reading of an ask that
    arrives carrying an `observed` line, because the only caller that carries
    one is `manage.py zitadel_reconcile`, and it has just read the instance:
    empty here beside a live provider there is not a missing configuration, it
    is the door this deployment has switched OFF and Zitadel has not been told
    about. The ownership table calls this "env wins BOTH ways", and until this
    rung only one of the two ways had a road — the audit has reported the other
    as drift since the workforce section landed, and nothing could act on the
    report. So an observed ask with an empty domain list skips both credential
    refusals (taking a door down needs no credentials) and the activity
    deactivates the provider rather than ensuring one.

    **Who may ask.** `deployment.configure` (`policies.py`), which is a
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
    authz.require(actor, "deployment.configure", tenant)

    # The take-down road: an ask from a caller that has read the instance,
    # against a deployment whose door is switched off. See the docstring.
    taking_down = bool(observed) and not settings.GOOGLE_WORKSPACE_DOMAINS

    if not taking_down:
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

    run_key = _workforce_config_key(observed=observed)
    # `tenant=None`, always — the argument above is the audit anchor and never
    # the run's scope. Passing it through here would be exactly the borrowing above.
    run = _start_identity_run(
        tenant=None,
        actor=actor,
        arg=IdentityConfigSync(kind=KIND_WORKFORCE_PROVIDER, key=run_key),
        noun="identity_config",
        run_key=run_key,
    )
    return WorkforceConfigAsked(run=run, key=run_key)


# --- The deployment's own look ------------------------------------------------


# door: only this tree's own hands reach it — `apply_identity_config`'s
# activity (recording an outcome) and `manage.py zitadel_brand` (asking for
# one), the shell door the stage-2 criteria named. A REST/MCP door is the
# recorded per-tenant-branding trigger (ADR ident-2's amendment), deliberately
# not built here: one shared LabelPolicy has no tenant to scope a route to.
@service
def set_identity_branding(
    *,
    actor: Actor,
    tenant: Tenant | None,
    branding: IdentityBranding | None = None,
    product_name: str = "",
    accent: str = "",
    background_color: str = "",
    font_color: str = "",
    background_color_dark: str = "",
    font_color_dark: str = "",
    logo_url: str = "",
    is_watermark_disabled: bool | None = None,
    observed: str = "",
    applied: IdentityConfigApplied | None = None,
) -> IdentityBranding:
    """Say what the hosted sign-in screen should look like, and go and make it so.

    **The row is the intent; the console is a window, not a door** (house rule
    27). This is the only way branding reaches Zitadel: the row is written here,
    inside a transaction, and the management call happens later, in an activity,
    on a run started **on commit**. That ordering is C2's classic and it is not
    negotiable here for the same reason it is not negotiable for
    `sync_identity_config` — a management call inside the transaction means a
    Zitadel hiccup rolls back a legitimate row, and a rolled-back service leaves
    no run at all.

    **The defaults are DERIVED from the one declared source.** An unset
    `product_name` or `accent` falls back to `settings.PRODUCT_NAME` and
    `settings.BRAND_ACCENT` — the same two values the entrance token block reads
    (`apps/accounts/templatetags/entrance.py`). Every OTHER unset field keeps
    what the live row already says, so a caller changing one colour does not
    silently blank the other five; on the first-ever row there is nothing to
    keep and the two declared settings are what fill it. That is the
    one-declared-value law: the page before the hosted step and the page after
    it match by construction rather than because somebody kept two values in
    step, which is how the hosted step's own styling regime collapses into the
    entrance's. A deployment that has never set `BRAND_ACCENT` gets the shipped
    restrained neutral on both sides, identically. `_branding_field_values` is
    where this merge happens.

    **Who may ask.** `deployment.configure` (`policies.py`) — the same
    permission the workforce door needs, and for the same reason: this is the
    deployment's own configuration, and an owner of one customer's workspace has
    no business changing the screen everybody signs in through.

    **The run is the platform's** (ADR workflows-3): one instance, one login
    screen, always started with `tenant=None`, under a `platform:` id — the
    caller's own `tenant` (keyword-only, no default, per ADR core-8: a
    defaulted `tenant` is a service that looks attributed and silently is not)
    survives only as the audit anchor, naming the workspace the operator
    happened to be acting in, exactly as `sync_workforce_identity_config`
    documents.

    **Supersede, never overwrite.** A second call deactivates the current row
    BEFORE validating the new one, not after: the partial unique index's own
    condition (`is_active=True`) is what `IdentityBranding.full_clean()` checks
    the new row against, and it checks the LIVE database — deactivating first
    is what keeps that check honest instead of a guaranteed
    `identitybranding_one_active` violation on every second call. Both writes
    are still inside this service's one transaction, so a validation refusal
    rolls the deactivation back along with everything else, and what the screen
    used to look like stays answerable in the row that lived before it.

    Called with `applied` — by `apply_identity_config`, and by nothing else —
    this records the *outcome* instead: the state becomes `applied` and no run
    is started, which is what keeps the activity from re-entering the workflow
    that is running it. The shape is `sync_identity_config`'s, deliberately.

    **Called with `observed` — by `manage.py zitadel_reconcile`, and by nothing
    else — this RE-ASKS the live row and writes no new one**, because a
    reconciler is not stating a new intent. `_re_ask_the_standing_screen` is
    that branch and carries the argument for it.
    """
    authz.require(actor, "deployment.configure", tenant)

    if applied is not None:
        return _record_the_screen_as_applied(branding or _active_branding())

    if observed:
        row = _the_standing_screen(branding or _active_branding())
    else:
        current = branding or _active_branding()
        row = IdentityBranding(
            **_branding_field_values(
                current,
                product_name=product_name,
                accent=accent,
                background_color=background_color,
                font_color=font_color,
                background_color_dark=background_color_dark,
                font_color_dark=font_color_dark,
                logo_url=logo_url,
                is_watermark_disabled=is_watermark_disabled,
            )
        )
        if current is not None:
            current.is_active = False
            current.save(update_fields=["is_active", "updated_at"])
        with as_invalid():
            row.full_clean()
        # authz-kind: the row is an `IdentityBranding` and the key is
        # `deployment.configure` — the branding IS this deployment's sign-in
        # screen, which is what the virtual kind exists to name (see the
        # docstring's "Who may ask"); no tenant owns the row.
        row.save()
    # **The run is claimed after the row exists and before the transaction
    # closes**, so its key can name the row. `start_workflow_on_commit`
    # defers only the Temporal client call; the visibility row is written
    # here, in this transaction, and a rollback takes both. **One starter for
    # both asking modes**: the supersede and the re-ask differ in which row
    # they hand over and in whether the key carries an observation, and nothing
    # else — a second copy of these six keywords is how one mode comes to build
    # an id the other cannot find.
    _start_identity_run(
        tenant=None,
        actor=actor,
        arg=IdentityConfigSync(kind=KIND_IDENTITY_BRANDING, key=str(row.pk)),
        noun="identity_config",
        run_key=_branding_run_key(row, observed=observed),
    )
    return row


#: What a branding row says the screen should look like: what a run about it is about.
BRANDING_STATED_FIELDS = (
    "product_name",
    "accent",
    "background_color",
    "font_color",
    "background_color_dark",
    "font_color_dark",
    "logo_url",
    "is_watermark_disabled",
)


def _record_the_screen_as_applied(row: IdentityBranding | None) -> IdentityBranding:
    """`set_identity_branding`'s outcome mode, one `def` out.

    **Not a service and deliberately not one**, and the shape is
    `_start_identity_run`'s: private to this module, one caller, always inside
    that caller's `@service` transaction, so the authorization, the audit row
    and the log line are the caller's, one frame up. It is out here because the
    function-length budget is the house's way of saying a service has grown a
    second job, and this service now has three modes — state a new intent, ask
    again about the standing one, record what a run made of it.
    """
    if row is None:
        raise NotFound("There is no active identity branding to record against.")
    row.sync_state = SsoConnection.SyncState.APPLIED
    row.save(update_fields=["sync_state", "updated_at"])
    return row


def _the_standing_screen(row: IdentityBranding | None) -> IdentityBranding:
    """The live intent row, moved back to `pending` for a re-ask. Same shape as above.

    **It writes no new row, and that is the whole difference from a supersede.**
    Supersede is right for a caller stating a new intent; a reconciler is not
    stating one — it is saying Zitadel's copy of the STANDING intent has
    drifted, so a new row would be a second identical intent in the ledger for
    every reconcile anybody ever runs.

    `pending` because that is what the row is: a run is in flight for it again,
    and a reader of `zitadel_audit` should meet the same word they would meet
    for a connection mid-sync.
    """
    if row is None:
        raise NotFound(
            "There is no active identity branding to re-ask for. Nothing states an "
            "intent for the sign-in screen, so there is no drift to close — set one "
            "with `manage.py zitadel_brand` first."
        )
    row.sync_state = SsoConnection.SyncState.PENDING
    row.save(update_fields=["sync_state", "updated_at"])
    return row


def _branding_run_key(row: IdentityBranding, *, observed: str = "") -> str:
    """What makes one materialisation of the sign-in screen unique, and repeatable.

    **A digest of the stated fields, which is the same shape its two siblings
    have.** `_identity_config_key` digests a connection's issuer, credentials
    and status; `_workforce_config_key` digests the three `GOOGLE_*` values. The
    branding key used to be the row's primary key alone, and that was the one
    key in this family that said WHICH ROW rather than WHICH INTENT — so two
    calls asking for identical colours were two runs, which is precisely the
    thing `_identity_config_key`'s docstring argues against ("the same
    configuration twice is the same run"). Digesting the intent makes the three
    consistent (principle 13) and makes an unchanged restyle one run.

    The consequence is stated rather than discovered: `zitadel_brand` run twice
    with the same colours now asks once, and a second ask after that run
    finished is the family's ordinary `Conflict` — "running the same work again
    is a new job, not a repeat of that one". A caller who genuinely wants the
    screen re-materialised without changing a colour is the reconciler, and it
    says what it saw.
    """
    intent = "|".join(str(getattr(row, field, "") or "") for field in BRANDING_STATED_FIELDS)
    return _with_observed(f"branding-{hashlib.sha256(intent.encode()).hexdigest()[:12]}", observed)


def _active_branding() -> IdentityBranding | None:
    """The live intent row, or `None` when nobody has ever set one.

    Not a selector and deliberately not one: it is private to this module, it is
    one filter, and every caller of it is inside a service's transaction. The
    same shape and the same reasoning as `_identity_config_key` above.
    """
    return IdentityBranding.objects.filter(is_active=True).first()


def _branding_field_values(
    current: IdentityBranding | None,
    *,
    product_name: str,
    accent: str,
    background_color: str,
    font_color: str,
    background_color_dark: str,
    font_color_dark: str,
    logo_url: str,
    is_watermark_disabled: bool | None,
) -> dict[str, Any]:
    """The new row's field values: asked-for, else the live row's, else — name
    and accent only — the one declared settings source (see
    `set_identity_branding`'s one-declared-value paragraph).

    Private and pure: `set_identity_branding` is the only caller, inside its own
    transaction, and this touches no row. Extracted from it so that function's
    OWN length stays about authorizing, superseding and starting the run — the
    three things that function is for — rather than about six colour columns'
    fallback arithmetic.
    """
    watermark = (
        current.is_watermark_disabled
        if is_watermark_disabled is None and current is not None
        else bool(is_watermark_disabled)
    )
    return {
        "product_name": (
            product_name or (current.product_name if current else "") or str(settings.PRODUCT_NAME)
        ),
        "accent": accent or (current.accent if current else "") or str(settings.BRAND_ACCENT),
        "background_color": background_color or (current.background_color if current else ""),
        "font_color": font_color or (current.font_color if current else ""),
        "background_color_dark": (
            background_color_dark or (current.background_color_dark if current else "")
        ),
        "font_color_dark": font_color_dark or (current.font_color_dark if current else ""),
        "logo_url": logo_url or (current.logo_url if current else ""),
        "is_watermark_disabled": watermark,
        "sync_state": SsoConnection.SyncState.PENDING,
    }


# --- Just-in-time provisioning -----------------------------------------------


class SsoRefused(Conflict):
    """An assertion this product will not turn into a session.

    A `Conflict` subclass rather than `Forbidden`, and the difference matters at
    the door: nobody was *denied permission* — the assertion itself was not
    something we accept (an unverified address, a domain this connection does
    not claim). `config/api.py` maps it to 409 through the ordinary MRO walk,
    and the browser flow renders it as a page.
    """


def _verified_claims(*, tenant: Tenant, connection: SsoConnection) -> set[str]:
    """The domains this connection claims **and an operator has verified**.

    **The second belt, and the reason it is a second one** (a domain claim routes nothing until it
    is verified).
    `SsoDomainManager.for_domain` already refuses to route an unverified claim,
    so in the login flow this question has been asked once already — but
    `provision_sso_identity` is reachable from a test, a command and any door a
    later rung gives it, and a service that trusted its caller to have checked
    is one refactor away from not checking at all.

    An unverified claim is therefore indistinguishable here from a domain the
    connection never claimed, which is why the caller's refusal keeps its
    existing sentence: from the person's side that is exactly what it is.

    A function rather than two lines inside the service, because the service is
    at its length ceiling and because the concept is worth a name: "claimed" and
    "claimed and verified" are different sets, and every reader of this module
    now has to know which one a site means.
    """
    rows = SsoDomain.objects.for_tenant(tenant).filter(
        connection=connection, verified_at__isnull=False
    )
    return {row.domain for row in rows}


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

    **Five refusals now, and two of them are about WHEN.** The first three are
    about the assertion; the two the deactivation review added are about the
    person, and they sit before the first write on each of the two paths
    through this function — `last_seen_at` and `ensure_membership` on the
    identity-found path, `ensure_membership` on the address-found path — so a
    login this service is about to refuse has moved nothing on its way to the
    refusal. A person who does not exist here yet cannot be switched off
    (`create_user` sets the default), which is why the new-account branch
    carries no such check and its absence there is a statement rather than an
    oversight.

    **An account this function creates has no password**, and that is the
    point: an account that only ever exists because an IdP asserted it must not
    also have a second way in that the IdP cannot revoke.

    **Its key is asked at the acting hat and not at the root, unlike the four
    keys a PERSON uses to configure a connection** (R1). This one is only ever
    reached as the `system` actor the login flow calls with, and `allows()`
    answers a system actor before any node is asked — so passing the root would
    buy a query per sign-in and change no answer. The valve on the `require`
    line says so in the one place a census can count it.

    The three about the assertion, in order:

    1. **The IdP must say the address is verified.** An IdP that asserts an
       address it has not verified is asserting whatever the person typed into
       their profile — and this product links that address to a local account.
       Without the verified flag, `alice@acme.com` at the IdP is a claim, not a
       fact, and honouring it is account takeover with extra steps.
    2. **The address must be in a domain this connection claims AND AN OPERATOR
       HAS VERIFIED** (`_verified_claims` below). Otherwise a
       tenant's own IdP could mint an identity for `someone@other-customer.com`,
       authenticating for a domain it does not own — and, before the second
       half of that sentence existed, a tenant could simply CLAIM the domain
       through the API and be asked nothing further.
    3. **An address already belonging to somebody in another tenant** is not
       taken over. Domains are unique across tenants, so this can only happen
       when a claim moved; the refusal is loud rather than silent.

    What it does **not** do is grant anything beyond `connection.default_role`.
    Roles are data and the connection's data says one role; a product that wants
    group-to-role mapping writes it as a service in its own app, over the claims
    it has decided to trust — and no more than `connection.default_role` says,
    which `_refuse_role_above_the_configurer` bounded when a person wrote it.
    """
    authz.require(actor, "sso_identity.create", connection)  # hat-scoped: system-only caller

    address = (email or "").strip().lower()
    if not email_verified:
        raise SsoRefused(
            "Your identity provider did not confirm that this email address is verified, "
            "so this product will not create or link an account with it."
        )
    if not address:
        raise SsoRefused("Your identity provider asserted no email address.")

    if domain_of(address) not in _verified_claims(tenant=tenant, connection=connection):
        raise SsoRefused(
            "That email address is outside the domains this identity provider is configured for."
        )

    existing = SsoIdentity.objects.for_subject(connection=connection, subject=subject)
    if existing is not None:
        if not existing.user.is_active:
            raise SsoRefused(INACTIVE_SENTENCE)
        existing.email = address
        existing.last_seen_at = now()
        existing.save(update_fields=["email", "last_seen_at", "updated_at"])
        ensure_membership(user=existing.user, tenant=tenant, role=connection.default_role)
        return existing

    user = User.objects.filter(email=address).first()
    if user is None:
        user = create_user(email=address, password=None)
    elif not user.is_active:
        raise SsoRefused(INACTIVE_SENTENCE)
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
    membership = Membership.objects.for_tenant(tenant).filter(user_id=user.pk).first()
    if membership is not None:
        return membership
    is_first = not Membership.objects.of(user).exists()
    return add_membership(
        user=user, tenant=tenant, is_default=is_first, role=role, actor=system_actor(tenant=tenant)
    )


# --- The identity home --------------------------------------------------------
#
# Identity option B: every tenant has a realm of its own at the identity
# platform, made when the tenant is. `core.create_tenant` asks through
# `core.bridge` (core learns no identity); the pending row is written here, in
# the creating transaction, and `EnsureTenantIdentityHomeWorkflow` makes the
# realm on commit and writes it back through `sync_identity_home`.

#: The workflow's registered name — a string for `SYNC_IDENTITY_CONFIG_WORKFLOW`'s
#: reason: `workflows` sits above this app.
IDENTITY_HOME_WORKFLOW = "EnsureTenantIdentityHomeWorkflow"


def _ask_for_identity_home(*, tenant: Tenant) -> None:
    """What `core.bridge.ENSURE_IDENTITY_HOME` is filled with: a new tenant's realm, asked for."""
    _ask_for_a_realm(tenant=tenant)


def _ask_for_a_realm(*, tenant: Tenant, observed: str = "") -> None:
    """Write the tenant's `pending` home and start its realm run on commit.

    What `core.bridge.ENSURE_IDENTITY_HOME` is filled with, so it runs inside
    `create_tenant`'s transaction — not a `@service` of its own for the reason
    `create_tenant`'s root organisation is not: it is part of the tenant being
    born, the tenant row is the record of it, and a rolled-back creation takes
    the home and the run's row with it.

    **A platform run** (`platform:accounts:identity_home:<slug>`, house rule 18):
    the realm is the deployment's identity configuration, not any tenant's row,
    so the run carries no tenant on its headers and names its tenant in the
    payload. `observed` is the reconciler's, as it is for every identity run: it
    lets a tenant whose realm went missing be asked for again after its first
    run finished.
    """
    home = IdentityHome.objects.for_tenant(tenant).first()
    if home is None:
        IdentityHome(tenant=tenant).save()
    _start_identity_run(
        tenant=None,
        actor=None,
        arg=IdentityHomeAsk(tenant_slug=tenant.slug),
        noun="identity_home",
        run_key=_with_observed(tenant.slug, observed),
        workflow=IDENTITY_HOME_WORKFLOW,
    )


# door: the shell — `manage.py zitadel_reconcile` asks it for every tenant the
# audit finds without a realm. A tenant is homed at creation; there is no route
# for asking again, because asking again is an operator's repair.
@service
def start_identity_home(*, tenant: Tenant, actor: Actor, observed: str = "") -> IdentityHome:
    """Ask for a tenant's realm again — the reconciler's road for a tenant with none.

    The same pending row and the same run `create_tenant` asks for, under the
    same id; a tenant created before realms existed is homed by this exactly as
    a new one is. A run already asked and still live is the same run; one that
    finished needs `observed`, the audit's line about what it saw.
    """
    # authz: the reconciler is the deployment's operator acting as the system,
    # and this grants nothing — it asks for the realm the tenant already should
    # have. There is no tenant-level key for it because no tenant door reaches it.
    _ask_for_a_realm(tenant=tenant, observed=observed)
    home: IdentityHome = IdentityHome.objects.for_tenant(tenant).get()
    return home


# door: `apps/accounts/activities.py::ensure_identity_home` — the run's own
# write-back, and nothing else. A route onto it would let a caller say which
# realm a tenant's people sign in at.
@service
def sync_identity_home(*, tenant: Tenant, actor: Actor, realm_id: str) -> IdentityHome:
    """Record that the tenant's realm exists: the home becomes `own_org`, naming it.

    **Said once, as an event**: `accounts.identity_home.created` when the home
    first gets its realm, and again only when it is given a different one (a
    realm deleted at the platform and made again by the reconciler). The same
    realm reported twice — a retried activity — writes nothing new and says
    nothing.
    """
    # authz: written by the realm activity alone, as the system actor, about a
    # realm it has just made; nobody asks for this and there is nothing to grant.
    home = IdentityHome.objects.for_tenant(tenant).select_for_update().first()
    if home is None:
        home = IdentityHome(tenant=tenant)
    changed = home.realm_id != realm_id or home.state != IdentityHome.State.OWN_ORG
    if not changed:
        return home
    home.realm_id = realm_id
    home.state = IdentityHome.State.OWN_ORG
    with as_invalid():
        home.full_clean()
    home.save()
    emit = bridge.listener(bridge.EMIT)
    if emit is None:
        log.info("accounts.event.unpublished", event_name=IDENTITY_HOME_CREATED)
    else:
        emit(
            name=IDENTITY_HOME_CREATED,
            tenant=tenant,
            payload=event_payload(IdentityHomeOut.from_orm(home)),
            actor=actor,
        )
    return home


# door: `manage.py zitadel_seed` — the deployment's shell door, where the staff
# realm is the organisation the seed already owns. Nothing a tenant reaches.
@service
def record_staff_realm(*, actor: Actor, tenant: Tenant | None, realm_id: str) -> IdentityHome:
    """Record which realm is the deployment's own: the home with no tenant.

    The staff realm is the identity platform's organisation this deployment
    already had — its operators and its workforce sign in there — and a sign-in
    that names no tenant's realm names this one. Idempotent: the same realm
    twice is the row it was; a different one moves it (a re-seeded platform).
    `tenant` is `None`, always: the row is the deployment's, and its audit row
    lands in the platform population.
    """
    # authz: the seed is the deployment operator at the shell, recording a fact
    # it just read off the platform; no tenant owns this row to ask about it.
    # rule-8: the staff realm's home is the one row with NO tenant.
    home = IdentityHome.objects.staff()
    if home is None:
        home = IdentityHome(tenant=None)
    if home.realm_id == realm_id and home.state == IdentityHome.State.OWN_ORG:
        return home
    home.realm_id = realm_id
    home.state = IdentityHome.State.OWN_ORG
    with as_invalid():
        home.full_clean(validate_constraints=False)
    home.save()
    return home


# --- The platform identity join ----------------------------------------------
#
# ADR ident-4, widened by identity option B. Zitadel hosts every interactive
# authentication, so everybody who signs in has a subject there — ONE PER
# REALM, since a person in two tenants is a person in two realms — and the
# `SsoIdentity` rows with no connection are the join from each of those
# subjects to this product's one `User`.


@service
# rule-13: still not a tenant-owned write. A person's subject is a fact about
# them and not about any customer — `tenant` below is an audit-population
# SELECTOR (the realm's tenant, or `None` for the staff realm), never a filter,
# exactly as it is on `erase_user` and `redact_invitations`.
#
# door: `apps/accounts/adapter.py` — the allauth social-login callback — is its
# door, and it is the same unconventional mount `provision_sso_identity` sits
# behind. A door of its own would be worse than none: `subject` is the column
# that decides which platform account signs in as which of our people, so a
# route that accepted one would be a route for claiming somebody else's identity.
def record_identity(
    *,
    user: User,
    realm: str,
    subject: str,
    tenant: Tenant | None,
    actor: Actor,
    issuer: str = "",
) -> User:
    """Record which subject this person is in `realm`. **The one writer of the join.**

    Called from `accounts.adapter.SocialAccountAdapter` at the moment the
    platform asserts an identity, and from nowhere else: a second writer is how
    a join between two identity systems comes to disagree with itself.

    **Keyed `(realm, subject)`, never on the address**, for the reason
    `SsoIdentity` gives: an address is a label an employer can reassign. The
    four states, per realm, and only one of them writes:

    * no subject for this person in this realm, the subject free → **written**;
    * this person's subject in this realm IS the subject → **no-op**;
    * this person holds a DIFFERENT subject in this realm → **`Conflict`**;
    * the subject is held in this realm by another account → **`Conflict`**.

    A subject in ANOTHER realm is not a conflict: it is the same person in a
    second tenant, which is the whole reason the join is keyed by realm. Cutting
    a join on purpose is `unlink_zitadel_identity`, an operator's audited act.

    The audit row is one per call, no-op included — "the platform asserted this
    identity again" is the fact the ledger is asked for — and it is about the
    PERSON (the person is what this returns), while the `subject` never reaches
    it: it is not in this app's `LOG_KEYS`.
    """
    cleaned = str(subject or "").strip()
    if not cleaned:
        raise Invalid(
            {"subject": ["An identity provider must assert a subject."]},
            detail="That sign-in carried no subject, so it cannot be joined to an account.",
        )
    # rule-8: the realm and the subject are the join's whole key, asked
    # before the sign-in knows whose person the subject is.
    held = SsoIdentity.objects.in_realm(realm=realm, subject=cleaned)
    if held is not None and held.user_id == user.pk:
        return user
    # BOTH DIRECTIONS, AND THE SAME SENTENCE FOR EACH: it says nothing about
    # which account, on a page anybody who can start a sign-in can reach.
    if held is not None:
        raise Conflict("That identity is already linked to a different account.")
    if user.sso_identities.filter(connection__isnull=True, realm=realm).exists():
        raise Conflict("That identity is already linked to a different account.")
    identity = SsoIdentity(
        tenant=tenant,
        connection=None,
        user=user,
        realm=realm,
        subject=cleaned,
        issuer=issuer,
        email=user.email,
    )
    with as_invalid():
        identity.full_clean(validate_constraints=False)
    identity.save()
    return user


# door: an operator's reconcile at the shell (`zitadel_reconcile`); no persona owns the copy.
@service
def retire_stale_staff_join(*, identity: SsoIdentity, actor: Actor, tenant: None) -> str:
    """Delete one `staff` join row whose subject a tenant's realm row now holds; answer the subject.

    Refused unless the realm row exists: the realm row is the person's, the `staff` copy is not.
    """
    # hat-scoped: a staff join row belongs to no tenant and no node; the operator acts at the shell.
    authz.require(actor, "sso_identity.delete")
    held = (
        # rule-8: the join is platform-wide; the realm row is found by its subject, not a tenant.
        SsoIdentity.objects.filter(connection__isnull=True, subject=identity.subject)
        .exclude(realm=STAFF_REALM)
        .exists()
    )
    if identity.realm != STAFF_REALM or identity.connection_id is not None or not held:
        raise Conflict("This join row is not a stale staff copy; nothing was retired.")
    subject = identity.subject
    identity.delete()
    log.info("accounts.identity.stale_staff_join_retired", user_id=str(identity.user_id))
    return subject


# door: the shell, and only the shell. `manage.py unlink_identity` is the door,
# at the deployment operator's altitude — the same place `bootstrap_tenant` and
# `zitadel_first_admin` stand. A route onto this would be a way to cut somebody
# else's identity join on request, which is the shape the refusal in
# `record_identity` exists to close.
@service
# rule-16: "unlink" is the verb, and it is the exact one — this cuts a join
# somebody made, and `remove`/`revoke`/`delete` each claim something it does not
# do (no row is removed, no credential is revoked, nothing is deleted). Widening
# `service_verbs` for the whole template is the other road and it belongs to
# whoever owns `quality/`, not to a fix rung in `accounts`.
def unlink_zitadel_identity(
    *, user: User, actor: Actor, tenant: Tenant | None, reason: str
) -> User:
    """Cut the join between a person here and their subject at the platform.

    **The road that makes the refusal above survivable.** Once a differing
    standing subject is refused, anything that legitimately changes subjects —
    swapping the issuer, re-seeding the deployment's identity platform,
    rebuilding one person's platform account — would lock out everybody it
    touched with no way back. This is the way back, and it is deliberately an
    operator's act at the shell door rather than a flag on the sign-in road: a
    door that re-points a join because the request asked it to is the hole the
    refusal closes, wearing a switch.

    **It cuts every handle on the platform side, not just our rows.** Three
    places can name a subject — the identity join (ours: `SsoIdentity` rows with
    no connection, one per realm), `SocialAccount.uid` (allauth's) and a
    per-connection `SsoIdentity.subject` (a customer IdP's) — and this service
    clears the first two, in every realm the person holds a subject in. **The allauth row is NOT
    "replaced by the next successful sign-in"**; that sentence stood here for a
    cycle and was false: a sign-in adds a second row, and the old one stays a
    live handle on this account. allauth resolves `(provider, uid)` itself,
    AFTER the adapter has had its say, so whoever the identity platform later
    hands the old subject to signs in as this person — driven end to end and
    measured at 302 with a session as the owner (V-R2F). A join an operator cut
    that still lets somebody in is not cut.

    **Only the platform provider's rows** — `provider=get_platform_provider_id()`.
    A workforce (Google) row is a different door's join to a different issuer
    and has nothing to do with the subject being cut; erasure is the service
    that takes every provider's row, because erasure is about the person rather
    than about one identity platform. Deleting a `SocialAccount` takes its
    `SocialToken`s with it by cascade, which is the same act: the credential the
    row carried is exactly what must stop working.

    `SsoIdentity` still belongs to `provision_sso_identity` and is deliberately
    untouched — it is per-connection, keyed on a customer IdP's own subject, and
    reaching into it from here would be the second writer this app's identity
    design is shaped around not having.

    **How many rows went is counted and logged** (`accounts.identity.unlinked`),
    and deliberately not on the audit row's `input`: `@service` builds that
    payload from the CALL's keyword arguments before the body runs
    (`core.service.call`), so a number the body computes has no seam into it.
    Carrying it there would take a result-declared audit-input hook in
    `apps/core/service.py`, beside `AUDIT_OBJECT_ATTR`, which is a decision for
    whoever owns `apps/core` and not for a caller of it.

    **Who may:** `policies.themselves_or_administers_the_whole_tenant`, the same
    wall `deactivate_user` stands behind, so a door can carry this verb the day
    a product wants one; a `system` actor passes as it does everywhere, which is
    what the command below calls as.

    The sockets close, because a person whose join was cut has to prove who they
    are again before anything else they hold means anything — the same seam and
    the same argument as a deactivation's.

    `reason` is required and rides the audit row: "every subject changed" and
    "this one person's platform account was rebuilt" are different acts, and six
    months later the ledger is the only place that difference still exists.
    """
    # hat-scoped: the third argument is the ROW because the predicate reads it —
    # "themselves, or administers the whole tenant". The NODE is resolved inside
    # `themselves_or_administers_the_whole_tenant`, which measures the tenant's
    # ROOT (ADR ident-6) and not the acting hat, so a branch administrator's `*`
    # never reaches here. Rule 55's own `does_not_cover` names this predicate as
    # the code half it cannot see into; this is the sentence it asks for.
    authz.require(actor, "user.unlink", user)
    _refuse_a_person_outside_this_actors_tenant(user=user, actor=actor)
    rows = SocialAccount.objects.filter(user_id=user.pk, provider=get_platform_provider_id())
    # Counted before the delete rather than read off its return value: that
    # value totals every row the cascade took, `SocialToken`s included, and the
    # number this reports is rows on the platform provider.
    removed = rows.count()
    rows.delete()
    user.sso_identities.filter(connection__isnull=True).delete()
    log.info(
        "accounts.identity.unlinked",
        user_id=str(user.pk),
        social_accounts_removed=removed,
    )
    close_sockets_on_commit(user_id=user.pk, reason=KICK_USER_IDENTITY_UNLINKED)
    return user


# --- The retired direct Google road's leftovers -------------------------------


# door: only this tree's own hands reach it — `manage.py
# retire_direct_google_links`, an operator's one-time step in a product's move
# off the retired direct Google road. It is a deployment's cleanup, not a
# capability a tenant's person or client needs a route or a tool for.
@service
def retire_direct_google_links(*, actor: Actor, tenant: Tenant | None) -> int:
    """Delete the direct Google road's `SocialAccount` rows, once nobody needs them.

    The workforce's Google is an identity provider inside Zitadel now, and the
    allauth Google provider those rows were written by is no longer installed —
    so a leftover `SocialAccount(provider="google")` is a row no provider
    serves: it signs nobody in, allauth's connections page under
    `/accounts/3rdparty/` leaves it out without saying so, and any code that
    asks it for its provider account (`get_provider_account()`) gets an error.
    (`str()` of it still works — it is the person's address.) This takes them
    away.

    **Only for people who already carry a Zitadel identity, and all or none.**
    A person with a direct-road row and no subject in the identity join has not signed in
    through Zitadel yet; their row is the only trace of how they used to arrive,
    and the fold's order is that their first Zitadel sign-in comes first. So a
    single such person REFUSES the whole run, naming them — an operator reads
    the list, has those people sign in once (or unlinks them by hand), and runs
    it again. A template never deletes a product's identity rows silently, which
    is also why this is a command an operator runs and not a migration.

    **Who may:** `deployment.configure` — a platform operator; these rows are
    about the installation's own door, not any tenant's. `tenant` is the audit
    anchor and nothing else, as it is for `grant_staff`.

    Returns how many rows went (their `SocialToken`s go with them by cascade).
    """
    # authz-kind: the rows removed are allauth's `SocialAccount`s and the key
    # asked is `deployment.configure`, deliberately — they are the retired
    # workforce door's links, a fact about the deployment's identity
    # configuration, not about any one person their tenant owns.
    authz.require(actor, "deployment.configure", tenant)
    census = get_direct_google_links()
    if census.unjoined:
        raise Conflict(
            "These people hold a link from the retired direct Google sign-in and "
            "have not signed in through the identity platform yet, so removing "
            "their link would leave no record of how they arrive: "
            f"{', '.join(census.unjoined)}. Have each of them sign in once through "
            "the identity platform's Google button, then run this again.",
        )
    rows = SocialAccount.objects.filter(provider=DIRECT_GOOGLE_PROVIDER)
    # `int(...)`: allauth ships no type information, so its manager's count is `Any`.
    removed = int(rows.count())
    rows.delete()
    log.info("accounts.direct_google.retired", social_accounts_removed=removed)
    return removed


# --- The admin's key, and why it is a service at all --------------------------
#
# ADR ident-4. Django's answer to "make this person staff" is
# `createsuperuser`, and it is the wrong answer here three times over: it prompts
# for a password and writes it into `User.password` — the second credential store
# the ADR closed — it hands out `is_superuser` as well as `is_staff`, and it
# leaves no record that anybody did it. `is_staff` is what opens `/admin/`, which
# is a door onto every tenant's rows, so who holds it and who handed it over is
# exactly the class of fact the audit ledger exists for (house rule 13).
#
# **`create_user`'s `is_staff=` keyword survives**, deliberately: it is the
# fixture road (`apps/conftest.py`, the admin suites) and the shape the allauth
# adapter provisions with, and both are creation rather than a later grant. What
# this service owns is the GRANT — the act somebody performs on somebody else's
# account after the fact — and that is the act with a policy and a row.
#
# **There is no `revoke_staff` and that is not an oversight.** `deactivate_user`
# and `erase_user` both clear `is_staff` already, and those are the two acts a
# product reaches for when somebody should stop being able to open the admin. A
# third verb that clears the flag alone is a service with no caller; the recorded
# trigger for one is a product that wants to demote a person without switching
# their account off.
#
# door: only this tree's own hands reach it — `manage.py grant_staff`, the shell
# door, and no route, tool or consumer. `is_staff` opens the admin onto every
# tenant's rows, and the persona who grants it is somebody with ssh on the
# deployment rather than a caller holding a credential: a REST or MCP door here
# would make "can reach every tenant" a thing a token could hand out over the
# wire, which is the opposite of what `deployment.configure` being
# `is_superuser` and not a role is for (`policies.py`). The recorded trigger for
# a door is a product that grows a deployment-operator console of its own.
@service
def grant_staff(*, user: User, actor: Actor, tenant: Tenant | None) -> User:
    """Let this person open `/admin/` — the one audited road to `is_staff`.

    **Who may:** `deployment.configure` (`policies.py`), which is a
    platform operator and not a tenant's owner. The admin reaches every tenant's
    rows, so an owner of one workspace handing out a key to all of them is not a
    bigger version of their own permission; it is a different one.

    **`tenant` is the audit anchor and nothing else.** Being staff is a fact
    about the deployment, so the row lands in the platform population with
    `tenant` NULL — readable through `AuditEntry.objects.for_platform()` and
    through no customer's ledger — and the parameter is declared (never
    defaulted) because that declaration is what makes `@service` audit at all
    (`core.service._declares_tenant`, ADR core-8).

    **Asking twice is one fact.** The flag is already set on the second call, so
    the write is skipped and the row still lands: an operator who ran the command
    again wanted to know the person is staff, and two ok rows for one state is
    the honest record of two asks.
    """
    authz.require(actor, "deployment.configure", tenant)
    if not user.is_active:
        raise Conflict(
            "That account is switched off, so it cannot sign in at all and being "
            "staff would change nothing about what it can reach. Switch it back "
            "on first, or grant this to somebody who can use it.",
        )
    if user.is_staff:
        return user
    user.is_staff = True
    # authz-kind: the row written is a `User` and the key asked is
    # `deployment.configure`, deliberately. `is_staff` is not a fact about
    # this person that their tenant owns — it is a fact about THE DEPLOYMENT's
    # admin, which reaches every tenant's rows — so a `user.*` key would put the
    # grant behind the wall `user.deactivate` stands behind, where the
    # person themselves and any root-level admin of their own workspace pass. The
    # column is on `User` because that is where Django keeps it; the capability
    # being handed over is the deployment's identity configuration.
    user.save(update_fields=["is_staff", "updated_at"])
    return user


#: How long the operator's day-zero vouch stands before the first sign-in must have happened.
FIRST_ADMIN_VOUCH_TTL = timedelta(days=7)


# door: `manage.py zitadel_first_admin`, the operator at the box before any tenant exists.
@service
def issue_first_admin_vouch(*, email: str, tenant: Tenant | None, actor: Actor) -> FirstAdminVouch:
    """Record the address the operator invited as the deployment's first human.

    Invariant: a re-run renews an unspent vouch's expiry; a spent one is never reopened.
    """
    # authz: the operator at the box's shell, via `zitadel_first_admin`, before any tenant.
    address = email.strip().lower()
    vouch, _created = FirstAdminVouch.objects.get_or_create(
        email=address, defaults={"expires_at": now() + FIRST_ADMIN_VOUCH_TTL}
    )
    if vouch.consumed_at is None:
        vouch.expires_at = now() + FIRST_ADMIN_VOUCH_TTL
        vouch.save(update_fields=["expires_at", "updated_at"])
    return vouch


# door: the sign-in adapter's signup, the one place the vouch it admitted can be spent.
@service
def mark_first_admin_vouch_spent(
    *, user: User, tenant: Tenant | None, actor: Actor
) -> FirstAdminVouch:
    """Spend the day-zero vouch `user`'s first sign-in arrived on; `NotFound` if none stands."""
    # authz: the sign-in adapter, as the system, at the signup the wall admitted on this vouch.
    live = get_first_admin_vouch(email=user.email)
    if live is None:
        raise NotFound()
    vouch = FirstAdminVouch.objects.select_for_update().get(pk=live.pk)
    if vouch.consumed_at is not None:
        raise NotFound()
    vouch.consumed_at = now()
    vouch.consumed_by = user
    vouch.save(update_fields=["consumed_at", "consumed_by", "updated_at"])
    return vouch
