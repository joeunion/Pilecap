"""Everything that happens between "somebody is signing in" and a session.

Three doors meet in this module, and they meet here rather than in three views
because the rules they share — who may sign in at all, what an identity provider
is trusted to assert, what a new account is granted — must not be able to differ
between them:

* **the platform** (`SocialAccountAdapter._platform_login`) — Zitadel, which
  hosts every interactive authentication including the passwords of local users
  (ADR ident-4), and which is where the `User.zitadel_sub` join is written;
* **workforce** (`SocialAccountAdapter._workforce_login`) — Google Workspace,
  restricted to the organisation's own domains. The domain restriction stays
  ours (ADR ident-6): W2-R5 materialises the same credentials as a Zitadel
  org-level IdP so the platform door offers the same button, and
  `GOOGLE_WORKSPACE_DOMAINS` is still checked here, because a restriction
  expressed only in somebody else's console is one we cannot test;
* **customers** (`SocialAccountAdapter._customer_login`) — a tenant's own
  OpenID Connect provider, with just-in-time provisioning. **It is no longer a
  door of its own** (ADR ident-6, W2-R5): Zitadel fronts every customer IdP, the
  assertion arrives through the platform provider like everybody else's, and
  `SsoDomain` — the row that always held the routing decision — is what says
  which connection a given address belongs to. The per-connection allauth apps
  (`list_apps`) and their provider ids are retired; what survives untouched is
  the part that mattered, `provision_sso_identity` and its three refusals.

**The local password door is gone** (`SOCIALACCOUNT_ONLY`, and
`config/settings/base.py` says what that removes). `AccountAdapter` survives for
two jobs that outlived the form: it is the hook allauth's social adapter
delegates the user write to — which is where a pending invitation becomes a
membership — and it still carries the `enforced` refusal, which no longer has a
password path to stand in front of and is kept as the belt for a product that
reopens one. Nothing in this tree reaches it otherwise, and the tests say so.

**None of them grants anything.** An IdP answers *who*; `Membership.role` and
each app's `policies.py` answer what they may do (`architecture.md`, "Auth &
identity"). The single place a role is ever set from an assertion is
`SsoConnection.default_role`, applied to a *new* membership only.

The fourth thing here is how arriving joins the tenant that invited you.

**This is where a signal would have gone, and a signal is forbidden** (house
rule 4). A `post_save` receiver on `User` is logic hidden in a file nobody
reads, it fires for every user a test or a management command ever creates, and
it has no way to tell "somebody just arrived through the front door" from
"somebody made a fixture". allauth's hooks are the actual arrival, and they are
*here* — where the arrival happens.

The rule they implement is small: a person who arrives with an address that has
a live invitation gets the membership that invitation names. **Arriving is not
only signing up**: somebody invited into a second tenant already has an
account, so the hook that fires when allauth WRITES a row never fires for them,
and the join runs on every platform sign-in for exactly that reason. A person
who arrives with no invitation gets an account and no tenant — and, tenancy
failing closed, sees nothing until somebody invites them. That is the right
default: self-service tenant creation is a product decision, not a template's.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialAccount
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from apps.accounts.models import User, domain_of
from apps.accounts.selectors import (
    get_connection_for_email,
    get_platform_provider_id,
    is_workforce_email,
    sso_enforced_for,
)
from apps.accounts.services import (
    INACTIVE_SENTENCE,
    provision_sso_identity,
    record_zitadel_identity,
)
from apps.core import context
from apps.core.actor import actor_for, system_actor
from apps.core.exceptions import DomainError
from apps.core.log import get_logger
from apps.core.services import accept_invitation, pending_invitations_for

log = get_logger(__name__)

# allauth's own id for the Google provider. Named once so the two places that
# branch on it cannot disagree.
GOOGLE_PROVIDER = "google"


def _may_be_introduced_by_address(candidate: User | None, subject: str) -> bool:
    """May this assertion proceed, when our column does not hold its subject?

    Reached only on the branch where `User.zitadel_sub` knows nobody by this
    subject. `candidate` is whoever holds the asserted ADDRESS, and may be
    `None` — nobody does, so the assertion is on its way to becoming a new
    person. Both cases ask the same two tables, which is why they are one
    function and not two.

    * **our column** — a `zitadel_sub` already set on the candidate means this
      person is known to the platform under a different subject, and an
      assertion carrying a new one is a claim on their account.
      `record_zitadel_identity` refuses it too; asking here as well is what
      turns a 500-shaped refusal into the page the door owns, and what keeps the
      refusal ahead of every write.
    * **allauth's row** — **ANY `SocialAccount` holding this subject refuses the
      assertion, whoever it belongs to and whatever address was asserted.** That
      row is not advisory: allauth's own `(provider, uid)` lookup runs AFTER
      this adapter and signs the bearer in as its owner without consulting
      anything here. So a row this door does not refuse is a session this door
      did not decide. Two shapes reach it — a row from before the column
      existed, and one an operator's `unlink_identity` left behind (R2F2; the
      service now deletes those, and this is the belt that does not depend on
      it) — and the fatal variant carried an address NOBODY holds, where there
      was no candidate to vote on at all and the new-person branch handed
      allauth the decision.
    * a subject held by the candidate's OWN row and by no column of ours is
      refused too, and that is deliberate rather than collateral: we cannot tell
      it apart from the survivor of a cut join, and the operator's road back
      (`unlink_identity`, which now takes those rows with it) is one command.

    Three tables can name a subject — `User.zitadel_sub`, `SocialAccount.uid`
    and `SsoIdentity.subject`. The first two must agree, and this is where they
    are made to; the third is per-connection and is `provision_sso_identity`'s,
    deliberately separate (one subject through two connections is two isolated
    identities, and that is the design).

    The subject is compared **as asserted**, unstripped, because that is the
    string allauth would match its own row on. `record_zitadel_identity`
    normalises before it writes, so an assertion differing from a stored subject
    only by whitespace passes here and meets the writer's refusal instead —
    which is the one road left into `_platform_login`'s last refusal.
    """
    if candidate is not None and candidate.zitadel_sub:
        return False
    return not SocialAccount.objects.filter(
        provider=get_platform_provider_id(), uid=subject
    ).exists()


def accept_pending_invitations(user: User) -> None:
    """Turn every live invitation for this address into the membership it names.

    **One implementation, reached from all THREE places a person arrives** —
    `AccountAdapter.save_user`, which allauth's social adapter delegates the
    user write to when there is a form; `SocialAccountAdapter._platform_login`,
    which is what runs for somebody who already exists; and
    `SocialAccountAdapter.save_user`, the IdP path's own signup hook, which
    calls it directly because the delegation above does not happen when there is
    no form. Three, counted here rather than remembered: this docstring said
    "both hooks" and named two for a cycle after the third was added, which is
    the staleness a reader trusts. It is a function rather than a method because the property
    it carries ("an invited address lands in the invited tenant at the invited
    role") belongs to *arriving*, not to any one of the doors it can happen
    through, and W2-R3 moved the door out from under it.

    **Signing up is no longer the only way in.** The signup hook alone
    was the whole of this for as long as an invitation could only ever precede
    an account; a person invited into a SECOND tenant already has one, so the
    hook that fires when allauth writes a row never fires for them and the
    invitation stood until it expired. It runs on every platform sign-in now,
    which is safe rather than doubled for the same reason calling it from both
    adapters was: accepting moves the row out of `PENDING`, so the next pass
    finds nothing.

    **This is where a signal would have gone, and a signal is forbidden** (house
    rule 4). A `post_save` on `User` fires for every user a test or a management
    command ever creates and cannot tell that apart from somebody arriving.

    An invitation that expired or was withdrawn between the email and the login
    simply does not apply: `pending_invitations_for` filters on both, and the
    person still gets their account. Everything is written through the service,
    so it gets the same validation, authorization and audit row a membership
    added any other way gets.
    """
    for invitation in pending_invitations_for(email=user.email):
        try:
            accept_invitation(
                tenant=invitation.tenant,
                invitation=invitation,
                user=user,
                # There is a person and there is no request: this runs at the
                # instant they arrive — as the account comes into existence, or
                # as the assertion that just proved who they are becomes a
                # session. `kind="human"` is the true statement in both, and it
                # is the whole of ADR core-22's L2 ruling.
                actor=actor_for(user=user, tenant=invitation.tenant, kind="human"),
            )
        except DomainError as exc:
            # **An offer that no longer applies does not apply, and does not
            # cost anybody their sign-in.** Two of them can reach here and both
            # became reachable the day this ran for a person who already holds
            # things: a place they are already in (`invite_member` does not
            # refuse an address that is already a member — two branches may each
            # have an offer out to one person), and a role that stopped existing
            # between the offer and the click. The service is right to refuse
            # both; what would be wrong is turning either into a 500 on the
            # front door, for a person whose identity was just proven.
            #
            # Narrow on purpose: `DomainError` is the refusal family, so
            # anything that is genuinely broken still surfaces as itself.
            log.warning(
                "accounts.invitation.not_applied",
                tenant_id=str(invitation.tenant_id),
                invitation_id=str(invitation.pk),
                code=exc.code,
            )
            continue
        log.info(
            "accounts.invitation.accepted",
            tenant_id=str(invitation.tenant_id),
            invitation_id=str(invitation.pk),
            role=invitation.role,
        )


# reason: no-stubs — django-allauth ships no type information, so mypy sees its
# base class as `Any` and refuses the subclass under `--strict`. The alternative
# is not writing an adapter, and the adapter is what keeps this out of a signal.
class AccountAdapter(DefaultAccountAdapter):  # type: ignore[misc]
    """allauth's signup hook wired to `core.services`, and the password refusal."""

    error_messages = {
        **DefaultAccountAdapter.error_messages,
        "sso_enforced": (
            "Your organisation requires you to sign in through its identity "
            "provider. Use the single sign-on link instead of a password."
        ),
    }

    def pre_authenticate(self, request: HttpRequest, **credentials: Any) -> None:
        """Refuse a password when the address's tenant has turned SSO on.

        **Unreachable in this deployment, and kept deliberately.** With
        `SOCIALACCOUNT_ONLY` on, a POST to the login view raises
        `PermissionDenied` before a form is ever bound, so nothing calls this —
        `test_password_door_retired.py` pins that. It stays because the property
        it carries is a customer's ("this account is out of password reach") and
        because deleting the belt is what makes reopening local accounts a
        security change nobody notices. W2-R5 materialises the same `enforced`
        flag as a Zitadel login policy, which is where it becomes load-bearing
        again.

        **Before the password is checked, not after.** Checking it first and
        then refusing would make this endpoint answer "that password was right"
        for an account the customer has deliberately taken out of password
        reach — which is most of what they turned `enforced` on to prevent.

        This is `pre_authenticate` rather than a form validator because it has to
        cover every path that reaches allauth's authentication, and because
        `super()` here is also allauth's login rate limiter: it runs first, so a
        refusal still costs an attempt.

        The message says an identity provider is required and nothing else. It
        does not name the connection or the tenant — this endpoint is open to
        the internet and a message that named a customer would turn a login form
        into a directory.
        """
        super().pre_authenticate(request, **credentials)
        email = str(credentials.get("email") or credentials.get("username") or "")
        if not email:
            return
        connection = sso_enforced_for(email)
        if connection is None:
            return
        log.info(
            "accounts.password.refused",
            reason="sso_enforced",
            tenant_id=str(connection.tenant_id),
            connection_id=str(connection.pk),
        )
        raise self.validation_error("sso_enforced")

    def save_user(
        self,
        request: HttpRequest,
        user: User,
        form: Any,
        commit: bool = True,
    ) -> User:
        """Create the account, then honour whatever it was invited to.

        `super()` writes the user; the memberships are added afterwards, through
        the service, so they get the same validation, authorization and audit
        row as a membership added any other way.

        **This runs on the IdP path now, not a signup form** (ADR ident-4).
        allauth's `SocialAccountAdapter.save_user` delegates the user write to
        this method, so the same hook fires for the same event it always fired
        for — a person arriving for the first time — with the form gone. The
        signup URL that used to reach it no longer exists (`SOCIALACCOUNT_ONLY`),
        which is exactly why the invitation join had to move *here* rather than
        stay on a view: this is the hook, not the door.
        """
        saved: User = super().save_user(request, user, form, commit=commit)
        if not commit:
            return saved
        accept_pending_invitations(saved)
        return saved


# --- The identity providers ---------------------------------------------------
# Everything below runs *between* an identity provider saying "this is who they
# are" and this product deciding whether that becomes a session. It is the one
# place both doors — the workforce's Google Workspace and a customer's own IdP —
# are gated, so the two cannot drift apart.


def asserted_email(sociallogin: Any) -> tuple[str, bool]:
    """The address the provider asserted, and whether it says it verified it.

    Two sources, deliberately in this order. `sociallogin.email_addresses` is
    what the provider's own extractor built, and it is where the verified flag
    lives for every provider allauth ships; `extra_data` is the raw claims, read
    only as a fallback for a provider whose extractor gave us nothing.

    **A missing flag is `False`.** An IdP that does not say an address is
    verified has not said it — reading silence as "probably fine" is exactly the
    step that turns a profile field somebody typed into a way into somebody
    else's account.
    """
    for address in getattr(sociallogin, "email_addresses", []) or []:
        if address.email:
            return str(address.email).strip().lower(), bool(address.verified)
    extra: dict[str, Any] = getattr(sociallogin.account, "extra_data", {}) or {}
    email = str(extra.get("email") or "").strip().lower()
    verified = bool(extra.get("email_verified", extra.get("verified_email", False)))
    return email, verified


def refusal_response(request: HttpRequest, reason: str) -> HttpResponse:
    """The page somebody sees when their sign-in is refused.

    A rendered page and not a redirect to the login form: a bounce back to
    "sign in" with nothing said is the failure mode where a person tries the
    same button six times. `reason` is written for them, and never names a
    tenant, a connection or whether an account exists.
    """
    return render(
        request,
        "accounts/sso_refused.html",
        {"reason": reason},
        status=HTTPStatus.FORBIDDEN,
    )


# reason: no-stubs — as above; django-allauth ships no type information.
class SocialAccountAdapter(DefaultSocialAccountAdapter):  # type: ignore[misc]
    """The gate on every assertion, for both doors.

    Two responsibilities, and they are both refusals or resolutions — never
    grants:

    1. **`pre_social_login`** decides whether this assertion becomes a session at
       all, and for an address a customer's connection claims performs the
       just-in-time provisioning through `services.provision_sso_identity`.
    2. **`is_open_for_signup`** is the second lock on the same door, for the
       signup path specifically.

    **`list_apps` is gone** (ADR ident-6, W2-R5). It built an unsaved
    `SocialApp` per `SsoConnection` so that a tenant's IdP was a row rather than
    a deploy — and it is retired because the row is now materialised *inside
    Zitadel* instead, by `sync_identity_config` and one activity, which is the
    same promise kept one layer further out: still a row, still no deploy, and
    now one place holding every customer's client secret instead of two.
    """

    def is_open_for_signup(self, request: HttpRequest, sociallogin: Any) -> bool:
        """The second lock, on the signup half of the flow.

        `pre_social_login` has already refused everything it is going to refuse,
        so in a correct flow this only ever says yes to a workforce address. It
        is here because "already refused" is a claim about control flow, and a
        control-flow claim is the kind that stops being true when somebody adds
        a branch.

        A customer's person never signs up through allauth's own path either —
        `_platform_login` has already created and connected them through
        `services.provision_sso_identity`, with its three refusals — so by the
        time this is reached for a claimed address there is nothing left to sign
        up. Any other provider id answers `False`: a flow that arrived here
        through one has a bug rather than a new user.
        """
        provider_id = str(sociallogin.account.provider)
        if provider_id == GOOGLE_PROVIDER:
            email, _ = asserted_email(sociallogin)
            return is_workforce_email(email)
        if provider_id == get_platform_provider_id():
            # Zitadel is where everybody signs in now (ADR ident-4), so this is
            # the ordinary signup path rather than an exception to it. It still
            # answers on the assertion rather than unconditionally: an address
            # the IdP has not marked verified never becomes an account, and
            # `_platform_login` has already refused that flow before this runs.
            _, verified = asserted_email(sociallogin)
            return verified
        return False

    def pre_social_login(self, request: HttpRequest, sociallogin: Any) -> None:
        """Decide whether this assertion becomes a session, before anything is written.

        The one place both doors meet. Everything it can do is refuse
        (`ImmediateHttpResponse`, so allauth returns the page rather than
        continuing) or resolve an existing person; the only row it creates, it
        creates through a service.
        """
        provider_id = str(sociallogin.account.provider)
        if provider_id == get_platform_provider_id():
            self._platform_login(request, sociallogin)
            return
        if provider_id == GOOGLE_PROVIDER:
            self._workforce_login(request, sociallogin)
            return
        # **And nothing else is ours** (ADR ident-6). Until W2-R5 a third branch
        # resolved a `SsoConnection` from the provider id, because each one was
        # its own allauth app; now every customer's IdP sits behind Zitadel and
        # arrives on the platform branch above. A provider id this deployment
        # does not register is a login it has no opinion about.

    # --- The platform: Zitadel, where everybody signs in ---------------------

    def _platform_login(self, request: HttpRequest, sociallogin: Any) -> None:
        """One assertion from the deployment's own IdP, turned into a session.

        Three things happen here and they are in this order for a reason:

        1. **an unverified address is refused, and no `User` row is written.**
           The refusal is before allauth's signup step, which is the only thing
           that would have created one. This is the A9 property on the RP path:
           linking on an address alone would mean whoever can make an IdP assert
           an address owns the local account at that address, and the verified
           flag is how we know this particular assertion is not that;
        2. **an existing local account is linked**, not duplicated — the seeded
           owner, somebody invited last month, a superuser made by
           `createsuperuser`. All of them predate this door and none of them
           should end up with a second account the first time they use it;
        3. **the subject is recorded**, through `services.record_zitadel_identity`
           and nowhere else. For a person who already exists it happens here; for
           a person who does not, it happens in `save_user`, after allauth has
           written the row — the same service, called from the one place that
           knows the user exists yet.

        **THE RESOLUTION RULE, and it is the one thing to read before changing
        anything here: two identifiers we hold that disagree are REFUSED, never
        merged.** The subject resolves the person; the address only ever
        *introduces* one. A subject we know signs its owner in even when the
        platform has since changed their address — but if that address belongs
        to a different account of ours, the assertion names two of our people at
        once and there is no reading of it that is safe to act on. Likewise a
        subject we do not know may be linked to the account at its address only
        while nothing already speaks for either: not our column, and not
        allauth's own row. Resolving by address first is what let a fresh
        subject carrying somebody's verified address walk into their account,
        and it is the shape this order exists to make impossible.

        **AND ALLAUTH NEVER DECIDES ALONE.** A `SocialAccount` holding the
        asserted subject while our column holds it for nobody is refused
        *whatever address the assertion carried* — including an address no
        account here holds, which is the case that used to fall through this
        method untouched and be resolved by allauth's own `(provider, uid)`
        lookup on the way past, signing the bearer in as that row's owner
        (V-R2F, driven: 302, a session as the owner). This door either decides a
        sign-in or refuses it; a branch that declines to decide has handed the
        decision to a library that has never heard of any of the rules above.

        There are two more, and neither is a grant this door decided. The
        **third** is a customer's connection claiming the address's domain,
        which W2-R5 added; the **fourth** is an invitation already standing for
        this address, which `accept_pending_invitations` turns into the
        membership it names. A login with neither lands with no
        `Membership` at all and, tenancy failing closed, sees nothing until
        somebody invites them. An IdP answers *who*, never *what they may do*;
        a `SsoConnection`'s `default_role` is the one place a *role* is ever
        read from configuration, and it applies to a new membership only.
        """
        subject = str(sociallogin.account.uid or "")
        email, verified = asserted_email(sociallogin)

        if not verified:
            log.warning("accounts.platform.refused", reason="email_not_verified")
            raise ImmediateHttpResponse(
                refusal_response(
                    request,
                    "Your identity provider did not confirm that this email address "
                    "is verified, so it cannot be used to sign in here.",
                )
            )

        # **The router, and it is still ours** (ADR ident-6). Zitadel asserted
        # who this is; `SsoDomain` says whose person they are. The lookup is by
        # the address's domain rather than by anything in the assertion, because
        # an assertion that carried the routing decision would be an identity
        # provider deciding which customer a person belongs to.
        connection = get_connection_for_email(email)
        if connection is not None:
            self._customer_login(request, sociallogin, connection)
            return

        # **THE SUBJECT RESOLVES THE PERSON; THE ADDRESS ONLY INTRODUCES ONE.**
        # This used to be a single lookup by address, and that made the account
        # the address's rather than the subject's: anybody who could make the
        # trusted issuer assert a chosen verified address under a FRESH subject
        # was handed the session standing at that address, and our column was
        # re-pointed on the way past. An org-level customer IdP behind the
        # platform is a party that mints exactly that assertion.
        #
        # Three steps, and the order is the whole fix:
        at_this_address = User.objects.filter(email=email).first()
        existing = User.objects.filter(zitadel_sub=subject).first()
        if existing is not None:
            # (1) THE SUBJECT KNOWS THIS PERSON. Their address at the platform
            # may since have changed and they are still them — that is the whole
            # reason the join is keyed here and not on the address, and this
            # rung does not copy the new address onto our row (a sign-in is not
            # a writer of a field `update_user` owns; the trigger for changing
            # that is a product that wants the platform authoritative for
            # addresses).
            #
            # **Unless our two identifiers disagree about WHO.** An address that
            # belongs to a DIFFERENT account here is not a rename — it is one
            # assertion naming two of our people at once, and there is no
            # reading of it that is safe to act on. Refusing an ambiguity is the
            # same posture as the rest of this door: we are never told which of
            # the two facts is the wrong one, and guessing is how somebody
            # inherits an account.
            if at_this_address is not None and at_this_address.pk != existing.pk:
                log.warning("accounts.platform.refused", reason="subject_address_disagree")
                raise ImmediateHttpResponse(
                    refusal_response(
                        request,
                        "That identity is already linked to a different account.",
                    )
                )
        else:
            # (2) OUR COLUMN KNOWS NOBODY BY THIS SUBJECT. The address may
            # introduce a person who predates the join — and only when nothing
            # already speaks for this subject or for them.
            #
            # **Asked even when the address matches nobody**, which is the half
            # this branch was missing: with no candidate the old form skipped
            # the question entirely, fell through to the new-person branch, and
            # allauth's own `(provider, uid)` lookup then signed the bearer in
            # as whoever held the surviving `SocialAccount`. A session nobody
            # here decided is the one outcome this door exists to prevent.
            existing = at_this_address
            if not _may_be_introduced_by_address(existing, subject):
                log.warning("accounts.platform.refused", reason="subject_mismatch")
                raise ImmediateHttpResponse(
                    refusal_response(
                        request,
                        "That identity is already linked to a different account.",
                    )
                )
        if existing is None:
            # A new person. allauth's signup step creates the row and
            # `save_user` records the subject on it — this branch has nothing to
            # link and deliberately writes nothing. A person who does not exist
            # yet cannot be switched off, so the refusal below is on the other
            # branch only and its absence here is a statement.
            return

        if not existing.is_active:
            # **BEFORE THE FIRST WRITE, and that is the whole point.** allauth
            # does refuse an inactive account — at the end, with
            # `/accounts/inactive/`, after this method has recorded the subject,
            # connected a `SocialAccount` and honoured every standing
            # invitation. The person gets no session, so it looks like the wall
            # held; what actually happened is that a switched-off account grew a
            # membership and an identity join on the strength of a login that
            # was refused. Deactivation is how an administrator ENDS somebody's
            # access, and an invitation accepted afterwards is access granted
            # after the ending.
            log.warning("accounts.platform.refused", reason="inactive")
            raise ImmediateHttpResponse(refusal_response(request, INACTIVE_SENTENCE))

        try:
            record_zitadel_identity(
                user=existing, subject=subject, tenant=None, actor=system_actor(tenant=None)
            )
        except DomainError as exc:
            # The subject belongs to somebody else's account. Refusing is the
            # whole point: silently re-pointing the join is an account takeover
            # with an extra step.
            log.warning("accounts.platform.refused", reason="subject_already_linked")
            raise ImmediateHttpResponse(refusal_response(request, exc.detail)) from exc

        sociallogin.connect(request, existing)
        log.info("accounts.platform.linked", user_id=str(existing.pk))
        # **The offer standing in a SECOND tenant.** Everything above is
        # about *this* account existing; the join below is about where it
        # belongs, and until now it only ever ran for an account that did not
        # exist a moment ago — `AccountAdapter.save_user`, which allauth calls
        # when it WRITES a `User` row. A person who already had one and was
        # invited somewhere new therefore signed in, every day, past an
        # invitation nobody could accept for them, while the mail that carried
        # it said "sign in and you will land in …". The link in that mail is the
        # login page and carries no token, so signing in is the only act there
        # is: this is where it has to be honoured.
        #
        # **After the subject is recorded, deliberately.** If the assertion
        # cannot be turned into an identity — a subject that belongs to somebody
        # else's account — the refusal above has already left, and no membership
        # is written on the strength of a login that did not happen.
        accept_pending_invitations(existing)

    def save_user(self, request: HttpRequest, sociallogin: Any, form: Any = None) -> User:
        """allauth has just created the row; record what the IdP called them.

        The other half of the one writer. `super()` runs
        `AccountAdapter.save_user` — which is where a pending invitation becomes
        a membership — and then the subject lands on the row that now exists.

        Only the platform provider writes the join: a customer connection's
        people are keyed on `SsoIdentity.subject` against *their* IdP, and the
        Google door's are not Zitadel subjects either. Both of those are handled
        before allauth ever reaches here, and neither belongs in this column.
        """
        user: User = super().save_user(request, sociallogin, form=form)
        # **The invitation join lives here, not only on the account adapter.**
        # allauth delegates the user write to `AccountAdapter.save_user` only
        # when there is a *form*, and the IdP path is auto-signup with none — so
        # a hook that sat only there would fire for a door this deployment no
        # longer has. Calling it from both is safe rather than doubled: accepting
        # moves the row out of `PENDING`, so the second call finds nothing.
        accept_pending_invitations(user)
        if str(sociallogin.account.provider) == get_platform_provider_id():
            record_zitadel_identity(
                user=user,
                subject=str(sociallogin.account.uid or ""),
                tenant=None,
                actor=system_actor(tenant=None),
            )
        return user

    # --- Workforce: Google Workspace, restricted to the org's own domains ----

    def _workforce_login(self, request: HttpRequest, sociallogin: Any) -> None:
        """Google authenticates the people who build this product. It grants nothing.

        Two refusals and one link, in that order:

        * an address outside `GOOGLE_WORKSPACE_DOMAINS` is refused outright, and
          **no `User` row is written** — the refusal happens before allauth's
          signup step, which is the only thing that would have created one. An
          empty domain list refuses everything, because empty means the provider
          is off (`config/settings/base.py`);
        * an address Google has not marked verified is refused even when the
          domain matches, because the linking below turns "the IdP says this is
          their address" into "this is that local account", and an unverified
          assertion is not a fact;
        * an address that already has a local account is **linked** to it, so
          somebody who signed up with a password before the workforce door
          existed does not end up with a second account.

        What does not happen here is any membership. A fresh workforce login
        lands with no `Membership` at all and — tenancy failing closed, with no
        superuser exemption — sees nothing until somebody invites them. That is
        the contract: an IdP answers *who*, never *what they may do*.

        **And neither refusal writes an audit row. That is a decision**, and
        it is the same precedent applied to this door: door refusals leave
        no audit row BY DESIGN. `@service` is the
        audit population's one writer, and a refusal here is a door turning
        somebody away *before any write exists* — there is no service call to
        audit and no row for one to be about. Auditing it would mean a second
        writer of `AuditEntry`, which is the thing ADR core-8 exists to prevent.
        What a refused login leaves instead is its structured log line
        (`accounts.workforce.refused`, house rule 19) with the request's bound
        context — door, request id, correlation id — already on it, which is
        where a refusal that nobody was refused *anything* belongs. The reasons
        are `domain_not_allowed` and `email_not_verified`; the domain rides on
        the first because it is a fact about the assertion and not about a
        person, and the address never rides on either.
        """
        email, verified = asserted_email(sociallogin)

        if not is_workforce_email(email):
            # Deliberately says nothing about which domains are allowed: this
            # page is reachable by anybody with a Google account.
            log.warning(
                "accounts.workforce.refused",
                reason="domain_not_allowed",
                domain=domain_of(email),
                # `door` and the correlation ids are already bound by
                # `core.middleware.ContextMiddleware` — this login lands on an
                # ordinary HTTP path, so the line carries `door="rest"`.
            )
            # **Not an `AuditEntry`**: no, by design, same precedent as above.
            # The reasoning is in this method's docstring rather than repeated
            # here, because it
            # is a property of the door and not of this one branch.
            raise ImmediateHttpResponse(
                refusal_response(
                    request,
                    "That Google account is not part of this organisation, so it "
                    "cannot be used to sign in here.",
                )
            )

        if not verified:
            log.warning("accounts.workforce.refused", reason="email_not_verified")
            raise ImmediateHttpResponse(
                refusal_response(
                    request,
                    "Google did not confirm that this email address is verified, so "
                    "it cannot be used to sign in here.",
                )
            )

        existing = User.objects.filter(email=email).first()
        if existing is not None:
            if not existing.is_active:
                # BEFORE THE LINK. allauth refuses an inactive account of its
                # own accord — at the END, after every write this method and the
                # signup step make. A wall that holds only after the damage is a
                # wall somebody walked through.
                log.warning("accounts.workforce.refused", reason="inactive")
                raise ImmediateHttpResponse(refusal_response(request, INACTIVE_SENTENCE))
            # **Verified-email trust, and why the check above is not optional.**
            # Linking on address alone would mean: whoever can make an IdP assert
            # an address owns the local account at that address. Google verifies
            # the addresses in a Workspace domain it controls, which is what
            # makes the link sound — and the `verified` flag is how we know this
            # particular assertion is one of those.
            sociallogin.connect(request, existing)
            log.info("accounts.workforce.linked", user_id=str(existing.pk))

    # --- Customers: one tenant, one IdP, just-in-time provisioning -----------

    def _customer_login(self, request: HttpRequest, sociallogin: Any, connection: Any) -> None:
        """One assertion for an address a customer's connection claims.

        **Not a door of its own since W2-R5** (ADR ident-6): `_platform_login`
        calls this once `SsoDomain` has said whose person the address is. The
        assertion is Zitadel's, the subject is Zitadel's, and the customer's own
        IdP sits behind it as a Zitadel external provider — which is why nothing
        in here reads the connection's issuer or its client secret any more.

        Everything that gets written is written by
        `services.provision_sso_identity`, with a **system** actor: the person
        being provisioned does not exist yet, so they cannot be the actor that
        created themselves, and the honest answer to "who did this" is "the
        product, because an IdP asserted it" (`core.actor.system_actor`).

        Both refusals the service raises — an unverified address, an address
        outside the connection's claimed domains — arrive here as `SsoRefused`
        and become a page. They are audited on the way, because a customer
        connection *does* have a tenant to scope the row to. The domain refusal
        is now unreachable *through this path* and kept anyway: the service is
        called by tests and could be called by a command, and a service that
        trusted its caller to have done the check is a service one refactor away
        from not doing it at all.
        """
        subject = str(sociallogin.account.uid or "")
        email, verified = asserted_email(sociallogin)
        tenant = connection.tenant

        with context.bound(tenant_id=str(tenant.pk), actor_kind="system"):
            try:
                identity = provision_sso_identity(
                    tenant=tenant,
                    actor=system_actor(tenant),
                    connection=connection,
                    subject=subject,
                    email=email,
                    email_verified=verified,
                )
            except DomainError as exc:
                raise ImmediateHttpResponse(refusal_response(request, exc.detail)) from exc

        # The platform join, for a customer's person too: they signed in through
        # Zitadel like everybody else, so the one column that says which Zitadel
        # subject they are gets written by the one writer. A subject already
        # claimed by a different account refuses here exactly as it does on the
        # ordinary platform path — a silent re-point is an account takeover with
        # an extra step.
        try:
            record_zitadel_identity(
                user=identity.user, subject=subject, tenant=None, actor=system_actor(tenant=None)
            )
        except DomainError as exc:
            log.warning("accounts.sso.refused", reason="subject_already_linked")
            raise ImmediateHttpResponse(refusal_response(request, exc.detail)) from exc

        sociallogin.connect(request, identity.user)
        log.info(
            "accounts.sso.signed_in",
            tenant_id=str(tenant.pk),
            connection_id=str(connection.pk),
            identity_id=str(identity.pk),
        )
