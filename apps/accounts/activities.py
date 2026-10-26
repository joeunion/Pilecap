"""Where the identity-config workflow is allowed to touch the world.

Everything `workflows.py` may not do lives here: the ORM, the network, the
credential. The shape is the house one and it is three steps — **restore the
principal, read the row through the tenant's manager, call a service** — plus
the one thing that makes this app's activity different from the worked example's:
it also talks to somebody else's API, and that is the whole reason the work is a
workflow rather than a line in the service.

**This module is one of the allow-listed importers of `apps.accounts.zitadel`**,
and house rule 27 is what keeps that population closed. WHICH modules are on the
allow-list is the rule's own answer — `python -m quality.gate --explain 27`
prints it — and listing them here would be a second copy that goes stale the run
after a shell door is added. A module OFF the list may still import the client
by carrying rule 27's comment valve with its reason on the line; `manage.py
zitadel_reconcile` is the one that does, for `configured()` and `ZitadelError`,
and it makes no management call at all. It is not
a style preference: a management call carries a credential and can hang, and the
places that may do it are the places where hanging is a retry rather than a
request nobody gets an answer to.

**Plain `def`**, like every activity in this repository: the ORM is synchronous
and the worker runs these in its thread pool. The one thing a sync activity owes
that pool is `close_old_connections` at both ends — there is no request cycle out
here to do it, and a connection left open per thread is a connection leaked
forever.

**Idempotent**, because Temporal guarantees at-least-once and the retry policy in
`workflows.py` makes retries the normal case rather than the exception. The
idempotence is real and not hopeful: `ensure_oidc_identity_provider` is given the
id our own row already recorded, so the second attempt updates the object the
first attempt made instead of creating a twin of it.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import close_old_connections
from temporalio import activity

from apps.accounts import realms, services, zitadel
from apps.accounts.models import STAFF_REALM, IdentityBranding, SsoConnection, User
from apps.accounts.realm import LoginPolicy, ProviderRef
from apps.accounts.selectors import get_realm_ref, get_tenant_realm, get_workforce_domains
from apps.accounts.types import (
    KIND_IDENTITY_BRANDING,
    KIND_IDENTITY_REVOCATION,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
    IdentityConfigApplied,
    IdentityConfigSync,
    IdentityHomeApplied,
    IdentityHomeAsk,
    InvitedIdentity,
    InvitedPerson,
)
from apps.core import bridge
from apps.core.actor import system_actor
from apps.core.context import current_actor
from apps.core.exceptions import NotFound
from apps.core.log import get_logger
from apps.core.models import Invitation, Tenant
from apps.core.surfaces import surface_for_role
from apps.core.time import now

log = get_logger(__name__)


class RealmNotReady(RuntimeError):
    """The tenant's realm is not made yet; the run retries until the home run lands it.

    Not a `DomainError`: nobody asked a door for anything, so there is no caller
    to refuse — it is the same retry-until-it-lands shape as the platform being
    briefly unreachable, and Temporal's retry policy owns it.
    """


def _login_policy(*, enforced: bool) -> LoginPolicy:
    """What a realm's sign-in says: the password, or — while `enforced` — the provider only."""
    return LoginPolicy(password_allowed=not enforced, provider_required=enforced)


@activity.defn(name="ensure_identity_home", no_thread_cancel_exception=True)
def ensure_identity_home(payload: IdentityHomeAsk) -> IdentityHomeApplied:
    """Make one tenant's realm, grant it the platform, set its policy, and record it.

    **Every step idempotent through the realm port**, so a retry — the normal
    case under Temporal — leaves one realm, one grant and one policy: the port
    searches before it creates. **A platform run** (`_platform_scope`): the
    realm is the deployment's identity configuration, so the tenant is named in
    the payload and read here, and a tenant-stamped invocation is refused.

    The policy is the tenant's current intent: the password, unless one of its
    connections already enforces with its provider landed — which is only ever
    true for a tenant whose realm was lost and is being made again.
    """
    close_old_connections()
    try:
        _platform_scope("identity_home")
        tenant = Tenant.objects.filter(slug=payload.tenant_slug).first()
        if tenant is None:
            raise NotFound(f"No tenant {payload.tenant_slug!r} to make a realm for.")
        port = realms.current()
        realm = port.ensure_realm(tenant=tenant)
        port.grant_platform(realm=realm)
        enforcing = (
            SsoConnection.objects.for_tenant(tenant)
            .filter(
                status=SsoConnection.Status.ACTIVE,
                enforced=True,
                sync_state=SsoConnection.SyncState.APPLIED,
            )
            .exists()
        )
        port.set_login_policy(realm=realm, policy=_login_policy(enforced=enforcing))
        services.sync_identity_home(tenant=tenant, actor=system_actor(tenant), realm_id=realm.id)
        log.info("accounts.identity_home.materialised", tenant=tenant.slug, realm_id=realm.id)
        return IdentityHomeApplied(tenant_slug=tenant.slug, realm_id=realm.id)
    finally:
        close_old_connections()


@activity.defn(name="apply_identity_config", no_thread_cancel_exception=True)
def apply_identity_config(payload: IdentityConfigSync) -> IdentityConfigApplied:
    """Make Zitadel agree with one configuration row, and record what it became.

    A row deleted while the run was queued raises `NotFound`. Temporal retries,
    it keeps raising, and the run fails saying so — which is the honest outcome,
    rather than quietly succeeding at nothing.

    The client secret is read from the row's encrypted `metadata` **here**, at
    the last possible moment, and never travels in the workflow argument: a
    secret in a workflow argument is a secret in Temporal's history, readable in
    the web UI by anybody who can open a run.

    **The scope is resolved per kind, and that is the shape rather than a
    micro-optimisation** (ADR workflows-3). Two of the three kinds are
    **platform** runs — the deployment's workforce door, and the revocation of
    an erased person's Zitadel credential — started with `tenant=None` under a
    `platform:` id, and neither has a tenant to restore or a row scoped to one
    to read. `workflow_context()` raises when the tenant header is absent, which
    is exactly right for a run that is *missing* a tenant and exactly wrong for
    one that legitimately has none; asking for a tenant before knowing whether
    this run has one would make every platform run fail on its first line. So
    the tenanted kind asks `WORKFLOW_CONTEXT`, and the two platform kinds ask
    `PLATFORM_CONTEXT` — which they could not reach until ADR core-9 put it on
    the bridge, and so **asserted nothing at all**. See `_platform_scope`.
    """
    close_old_connections()
    try:
        if payload.kind == KIND_WORKFORCE_PROVIDER:
            _platform_scope(payload.kind)
            return _apply_workforce_provider(payload)
        if payload.kind == KIND_IDENTITY_REVOCATION:
            _platform_scope(payload.kind)
            return _apply_identity_revocation(payload)
        if payload.kind == KIND_IDENTITY_BRANDING:
            _platform_scope(payload.kind)
            return _apply_identity_branding(payload)
        if payload.kind != KIND_SSO_CONNECTION:
            raise ValueError(
                f"apply_identity_config does not know the config kind {payload.kind!r}. "
                "The vocabulary is apps/accounts/types.py's KIND_* constants."
            )
        tenant, _user_id, _org = bridge.get(bridge.WORKFLOW_CONTEXT)()
        return _apply_sso_connection(payload, tenant=tenant)
    finally:
        close_old_connections()


def _platform_scope(kind: str) -> tuple[Any, Any, Any]:
    """A platform kind's scope, resolved — **and a stamped tenant refused, loudly**.

    Both callers are runs the *deployment* owns: `tenant=None`, a `platform:`
    workflow id, no acting hat (`_start_identity_run` passes `org=None` and
    `check_org_agreement` refuses one beside a null tenant). Until ADR core-9
    they resolved nothing, because the accessor that answers this question lives
    in `apps.workflows`, which sits **above** this app — so the builder
    reported the gap rather than smuggling an upward import, and these two ran
    under whatever headers they happened to arrive with, checking neither.

    The bridge inverts that call, and the assertion travels with it. **The
    refusal has to live here and not in the accessor**: `platform_context()` is
    a plain read of the contextvars the interceptor set and hands a stamped
    tenant straight back — it has no way to know whether its caller is platform
    scoped, and `apps/workflows/tests/test_platform_context_bridge.py` pins that
    as found. This function is the caller that *does* know.

    `RuntimeError` and not a `DomainError`: nobody asked for this and there is no
    door to render a refusal to. It is the same shape and the same reasoning as
    `workflow_context()`'s own refusal — a cross-scoped run is a bug in how the
    run was started, and Temporal retrying it until somebody looks is the right
    outcome. Proceeding would be W4-2's silence, one app over: a platform run
    doing the deployment's work while wearing one customer's hat.
    """
    tenant, user_id, org = bridge.get(bridge.PLATFORM_CONTEXT)()
    if tenant is not None or org is not None:
        raise RuntimeError(
            f"The platform config kind {kind!r} arrived tenant-stamped "
            f"(tenant={getattr(tenant, 'slug', tenant)!r}, "
            f"org={getattr(org, 'slug', org)!r}). A run started through "
            "apps.accounts.services for a platform kind carries no tenant and no "
            "hat; one that does was started wrong, and running it here would do "
            "the deployment's work under one customer's scope."
        )
    return tenant, user_id, org


def _apply_sso_connection(
    payload: IdentityConfigSync,
    *,
    tenant: Tenant | None,
) -> IdentityConfigApplied:
    """One customer's identity provider, materialised inside the tenant's own realm.

    **In the tenant's realm, through the realm port** (identity option B): the
    provider is made there and linked to that realm's login policy, and the
    realm's policy says what `enforced` means — the password off and the
    provider the one way in while it is on, the password back while it is off.
    Every other realm, the staff realm included, is untouched: nobody else's
    password goes anywhere.

    **Refused while the tenant has no realm yet** — a `pending` home — and
    Temporal retries until it lands: a provider made anywhere else would be a
    provider in the wrong population.

    **The second wall.** A connection that enforces is only written as
    provider-required once the realm reads the provider back as linked; if it
    does not, the run FAILS naming it rather than locking the realm's people out
    behind a door that is not there.

    **A disabled row is a provider taken off the realm's sign-in**, and the
    realm's password back: the pinned build has no deactivation for the
    provider templates this tree makes (measured: the legacy
    `/idps/{id}/_deactivate` answers `400 Errors.Org.IDPConfig.NotActive` on an
    ACTIVE one, and `/idps/templates/{id}/_deactivate` answers 404), so the
    realm port's `detach_provider` — the provider unlinked from the realm's
    login policy — is the release. The object and its user links stay, so a
    customer who re-enables tomorrow does not find everybody unlinked.
    """
    connection = SsoConnection.objects.for_tenant(tenant).filter(pk=UUID(payload.key)).first()
    if connection is None:
        raise NotFound("This SSO connection no longer exists.")
    realm = get_tenant_realm(connection.tenant)
    if realm is None:
        raise RealmNotReady(
            f"Tenant {connection.tenant.slug!r} has no realm of its own yet, so there is "
            "nowhere to put its identity provider; the identity-home run has to land first."
        )
    port = realms.current()
    if connection.is_active and not connection.enforced:
        # The policy first: a provider is only linked on a realm that owns its
        # login policy, and this one says the password stays.
        port.set_login_policy(realm=realm, policy=_login_policy(enforced=False))
        resource_id = port.attach_provider(realm=realm, connection=connection).id
    elif connection.is_active:
        # The provider first, then the wall — never the wall before its door.
        provider = port.attach_provider(realm=realm, connection=connection)
        if provider.id not in {one.id for one in port.facts(realm=realm).providers}:
            raise NotFound(
                "This connection's identity provider is not on its realm's sign-in, so "
                "requiring it would leave nobody able to sign in; nothing was enforced."
            )
        port.set_login_policy(realm=realm, policy=_login_policy(enforced=True))
        resource_id = provider.id
    else:
        if connection.zitadel_idp_id:
            port.detach_provider(realm=realm, provider=ProviderRef(id=connection.zitadel_idp_id))
        port.set_login_policy(realm=realm, policy=_login_policy(enforced=False))
        resource_id = connection.zitadel_idp_id
    applied = IdentityConfigApplied(kind=payload.kind, key=payload.key, resource_id=resource_id)
    services.sync_identity_config(
        tenant=connection.tenant,
        actor=current_actor(kind="system"),
        connection=connection,
        applied=applied,
    )
    return applied


def _apply_workforce_provider(payload: IdentityConfigSync) -> IdentityConfigApplied:
    """The deployment's Google Workspace door, materialised as an org-level IdP.

    **A platform run** (ADR workflows-3): started with `tenant=None` under a
    `platform:` id, because the provider is the installation's and belongs to no
    customer. There is nothing tenant-shaped to read, and `_platform_scope` has
    already refused the caller if this run somehow arrived carrying a tenant.

    **Nothing is written back, and that is the honest shape.** This run's intent
    is the environment (`GOOGLE_*`), not a row: there is no tenant-scoped table a
    deployment-wide provider belongs in, and inventing one nobody owns would be
    worse than saying so. The idempotence therefore rests entirely on
    `ensure_google_identity_provider`'s search by name, which is the same second
    net every other `ensure_*` already falls back to, and `zitadel_audit` is what
    makes drift visible.

    The credentials are read here, in the activity, for the reason every other
    secret in this module is: a client secret in a workflow argument is a client
    secret in Temporal's history.

    **And the environment wins in BOTH directions** (the reconciler's ownership
    table). An empty `GOOGLE_WORKSPACE_DOMAINS` is the door switched OFF, and a
    live Google provider over an off door is worse than a missing one: it looks
    open, Zitadel signs people in through it, and this product refuses every
    address it asserts. So the same intent — the environment — materialises as a
    DEACTIVATION when the door is off. Deactivated and not deleted, for the
    reason `_apply_sso_connection` gives about a disabled connection: the object
    and its links stay, so a deployment that turns the door back on tomorrow
    does not find everybody unlinked. A door that is off on both sides is a
    no-op with an empty resource id, which is the honest answer to "there was
    nothing to take down".

    The switch is read HERE rather than carried in the payload because the
    environment is this kind's intent, and a run that carried a copy of it would
    be materialising what the environment said when the ask was made rather than
    what it says now.
    """
    if not get_workforce_domains():
        return _take_the_workforce_door_down(payload)

    client_id = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
    client_secret = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
    resource = zitadel.ensure_google_identity_provider(
        name=zitadel.workforce_idp_name(),
        client_id=client_id,
        client_secret=client_secret,
    )
    log.info(
        "accounts.workforce.materialised",
        resource_id=resource.id,
        created=resource.created,
    )
    return IdentityConfigApplied(kind=payload.kind, key=payload.key, resource_id=resource.id)


def _take_the_workforce_door_down(payload: IdentityConfigSync) -> IdentityConfigApplied:
    """The other direction of the same intent: the door is off, so shut Zitadel's.

    Its own function rather than a branch inside `_apply_workforce_provider`
    because the two do different things to somebody else's API and a reader
    deciding whether a run was safe should not have to follow a negation through
    an `ensure_*` call. The idempotence is `deactivate_identity_provider`'s —
    it swallows Zitadel's own already-in-that-state refusal — plus the search by
    name, which is the only handle either side has on this provider.
    """
    name = zitadel.workforce_idp_name()
    provider = zitadel.find_identity_provider(name=name)
    if provider is None:
        log.info("accounts.workforce.already_absent", name=name)
        return IdentityConfigApplied(kind=payload.kind, key=payload.key, resource_id="")
    resource = zitadel.deactivate_identity_provider(idp_id=str(provider.get("id", "")))
    log.info("accounts.workforce.deactivated", resource_id=resource.id, name=name)
    return IdentityConfigApplied(
        kind=payload.kind,
        key=payload.key,
        resource_id=resource.id,
    )


def _apply_identity_branding(payload: IdentityConfigSync) -> IdentityConfigApplied:
    """The hosted sign-in screen's look, made to agree with the intent row.

    **A platform run** (ADR workflows-3): one instance, one login screen,
    belonging to no customer, so it is started with `tenant=None` under a
    `platform:` id and `_platform_scope` has already refused a tenant-stamped
    invocation.

    **Unlike the workforce door, this one HAS a row**, and that asymmetry is the
    point of the whole rung. `_apply_workforce_provider` writes nothing back
    because its intent is the environment; here the intent is
    `IdentityBranding`, so the run reads it, materialises it, and records that
    it landed — which is what gives `zitadel_audit` something to disagree with
    when somebody repaints the screen in the console.

    A row deleted or deactivated while the run was queued raises `NotFound`.
    Temporal retries, it keeps raising, and the run fails saying so — the same
    honest outcome `apply_identity_config` documents for every other kind,
    rather than quietly succeeding at nothing.

    **The write-back is not through a service, and that is the existing shape.**
    `_apply_sso_connection` records its own materialisation the same way, for
    the reason recorded there: this is the activity recording what it itself
    just did to somebody else's API, not a caller asking for a state change.
    """
    row = IdentityBranding.objects.filter(pk=UUID(payload.key), is_active=True).first()
    if row is None:
        raise NotFound(
            f"identity branding {payload.key} is gone or no longer active; nothing to materialise."
        )
    resource = zitadel.ensure_label_policy(
        accent=row.accent,
        background_color=row.background_color,
        font_color=row.font_color,
        background_color_dark=row.background_color_dark,
        font_color_dark=row.font_color_dark,
        is_watermark_disabled=row.is_watermark_disabled,
    )
    applied = IdentityConfigApplied(
        kind=payload.kind,
        key=payload.key,
        resource_id=resource.id,
    )
    # The write-back goes through the service, like every other write in this
    # repository (house rule 10) and exactly as `_apply_sso_connection` above
    # does it. The activity learned a fact; the service is what is allowed to
    # record it, audit it and log it.
    #
    # `tenant=None` and a hatless actor: this is the deployment's own screen, a
    # platform run by construction, and `_platform_scope` has already refused an
    # invocation carrying either.
    services.set_identity_branding(
        actor=system_actor(),
        tenant=None,
        branding=row,
        applied=applied,
    )
    log.info(
        "accounts.identity_branding.materialised",
        resource_id=resource.id,
        created=resource.created,
    )
    return applied


def _apply_identity_revocation(payload: IdentityConfigSync) -> IdentityConfigApplied:
    """Take an erased person's Zitadel account out of use, and cut its links.

    **A platform run, for everybody** (ADR workflows-3, then ADR ident-7). It is
    started with `tenant=None` under a `platform:` id whoever the person is: the
    credential is Zitadel's and belongs to no workspace, so recording the run in
    a borrowed tenant made a tenant's ledger claim a revocation it never owned.
    It reads no tenant-scoped row either, and `_platform_scope` has already
    refused a tenant-stamped invocation. That is also what lets the tenantless
    erasure this activity exists for reach Zitadel and survive it.

    **Read without the tenant manager, deliberately.** `User` is not a
    tenant-scoped model — a person may hold memberships in several tenants or,
    after `erase_user` has run, be of interest to none — and narrowing this read
    to the run's tenant would mean an erasure performed in one workspace left the
    identity live for a person who belonged to two. The key is our own primary
    key, put there by `erase_user` inside its transaction, so there is no caller
    input to widen.

    A user with no subject in the identity join is a person who never signed in
    through the platform: there is nothing to deactivate, and reporting that as
    an empty resource id is the truth rather than a failure.

    **Every subject the person holds, each in its own realm**, through the
    realm port's `deactivate_person` — a person in two tenants is two platform
    accounts, and one left live is a person erased in one workspace who signs
    in to the other. The staff realm's account also loses its federation links
    first (the deployment-level client call it always made); a tenant realm's
    account is deactivated, which no link can sign in through.
    """
    user = User.objects.filter(pk=UUID(payload.key)).first()
    if user is None:
        raise NotFound("That person's row no longer exists.")
    joined = list(user.sso_identities.filter(connection__isnull=True).order_by("created_at"))
    if not joined:
        return IdentityConfigApplied(kind=payload.kind, key=payload.key, resource_id="")
    port = realms.current()
    removed = 0
    for row in joined:
        if row.realm == STAFF_REALM:
            # Links first, then the account. The other order leaves a window in
            # which a deactivated account still carries live federation links.
            removed += zitadel.remove_identity_provider_links(user_id=row.subject)
        port.deactivate_person(realm=get_realm_ref(row.realm), subject=row.subject)
    subject = joined[0].subject
    # **And the sockets, from here rather than from `workflows.py`** (ADR
    # realtime-2 d; house rule 9). The bridge lookup and the `group_send` behind
    # it are I/O, and a workflow module may not do I/O — it has to replay
    # identically years from now, and a channel layer will not.
    #
    # `erase_user` already asked once, on commit, and this asks again on
    # purpose. That first kick is fire-and-forget inside the erasing request:
    # one attempt, no retry, and a channel layer that was unreachable at that
    # instant closes nothing and tells nobody. This caller is the one that gets
    # to retry — the run is retried until the whole revocation lands — and
    # asking twice is free because RT2 made the primitive idempotent: a
    # `group_send` to an empty group is a no-op, so kicking a person with
    # nothing open closes nothing rather than failing.
    services.close_sockets(user_id=user.pk, reason=services.KICK_IDENTITY_REVOKED)
    log.info(
        "accounts.identity.revoked",
        zitadel_user_id=subject,
        links_removed=removed,
        realms=len(joined),
    )
    return IdentityConfigApplied(kind=payload.kind, key=payload.key, resource_id=subject)


@activity.defn(name="provision_invited_identity", no_thread_cancel_exception=True)
def provision_invited_identity(payload: InvitedPerson) -> InvitedIdentity:
    """Give an invited person an account in the tenant's realm, and the link to set a password.

    **In the tenant's own realm, through the realm port** (identity option B):
    the invited person is one of that tenant's people, so their account is made
    there, and the link that lets them choose a password lands on **the host of
    the surface their role belongs to** (`core.surfaces.surface_for_role`) — a
    customer's mail carries the customer host, a staff member's the staff one.
    The role is read off the invitation row, the one place it is written.

    **Refused while the tenant has no realm yet**, and Temporal retries until the
    identity-home run lands: an account made in any other realm would be an
    account in the wrong population.

    One activity, because the account and its code retry as a unit: the port's
    `provision_person` finds the account the previous attempt made, and the
    fresh code — which supersedes the last on every call — is the one that goes
    out. A person who already set credentials gets no link, and the mail says
    "sign in" instead.

    **The code is never logged.** The one log line names the account and the
    branch taken; `set_credentials_url` embeds the code and does not appear in
    it. `tests/test_invited_provisioning.py` asserts that over the captured
    records rather than trusting this paragraph.
    """
    close_old_connections()
    try:
        tenant, _user_id, _org = bridge.get(bridge.WORKFLOW_CONTEXT)()
        key = UUID(payload.invitation_id)
        # rule-24: this run's own invitation, by the key it was started with, read
        # for its role alone; the row was written by the service that asked for
        # the run, and the hat that wrote it is not on a platform-shaped read.
        invitation = Invitation.objects.for_tenant(tenant).filter(pk=key).first()
        realm = get_tenant_realm(tenant) if tenant is not None else None
        if realm is None:
            raise RealmNotReady(
                "This invitation's tenant has no realm of its own yet, so there is nowhere to "
                "make the person; the identity-home run has to land first."
            )
        surface = surface_for_role(invitation.role if invitation is not None else "")
        person = realms.current().provision_person(
            realm=realm,
            email=payload.email,
            names=_invited_person_names(payload.email),
            surface=surface.key,
        )
    finally:
        close_old_connections()
    if not person.set_credentials_url:
        # Not a failure: they already sign in here. The email will say so.
        log.info(
            "accounts.invitation.identity_already_initialized",
            invitation_id=payload.invitation_id,
            zitadel_user_id=person.subject,
        )
        return InvitedIdentity(zitadel_user_id=person.subject, already_initialized=True)
    lifetime = zitadel.invite_code_lifetime()
    log.info(
        "accounts.invitation.identity_provisioned",
        invitation_id=payload.invitation_id,
        zitadel_user_id=person.subject,
        surface=surface.key,
    )
    return InvitedIdentity(
        zitadel_user_id=person.subject,
        set_credentials_url=person.set_credentials_url,
        link_expires_on=(now() + lifetime).date().isoformat() if lifetime is not None else "",
    )


def _invited_person_names(email: str) -> tuple[str, str]:
    """A given and a family name for somebody we know only by address.

    Zitadel's `AddHumanUser` requires both and will not take blanks, and an
    invitation carries an email and nothing else — so something has to be
    chosen, and the honest choice is one that is obviously derived rather than
    one that looks like knowledge we do not have.

    The local part, split on the separators people actually use in work
    addresses. `ada.lovelace@x` becomes `Ada Lovelace`; `ada@x` becomes
    `Ada Ada`, because a one-word local part gives no family name and a blank is
    refused. The person corrects both the moment they set their password, which
    is the screen this is shown on.
    """
    local = email.partition("@")[0].strip() or email.strip()
    parts = [part for part in re.split(r"[._\-+]+", local) if part]
    if not parts:
        parts = [local]
    first = parts[0].capitalize()
    last = " ".join(part.capitalize() for part in parts[1:]) or first
    return first, last


ACTIVITIES: list[Callable[..., Any]] = [
    apply_identity_config,
    provision_invited_identity,
    ensure_identity_home,
]
