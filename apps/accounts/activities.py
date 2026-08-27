"""Where the identity-config workflow is allowed to touch the world.

Everything `workflows.py` may not do lives here: the ORM, the network, the
credential. The shape is the house one and it is three steps — **restore the
principal, read the row through the tenant's manager, call a service** — plus
the one thing that makes this app's activity different from the worked example's:
it also talks to somebody else's API, and that is the whole reason the work is a
workflow rather than a line in the service.

**This module and the two `zitadel_*` commands are the only importers of
`apps.accounts.zitadel`**, and house rule 27 is what keeps that true. It is not
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

from apps.accounts import services, zitadel
from apps.accounts.models import SsoConnection, User
from apps.accounts.types import (
    KIND_IDENTITY_REVOCATION,
    KIND_SSO_CONNECTION,
    KIND_WORKFORCE_PROVIDER,
    IdentityConfigApplied,
    IdentityConfigSync,
    InvitedIdentity,
    InvitedPerson,
)
from apps.core import bridge
from apps.core.actor import system_actor
from apps.core.exceptions import NotFound
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.time import now

log = get_logger(__name__)


@activity.defn(name="apply_identity_config")
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
    micro-optimisation** (ADR workflows-3; rung W7). Two of the three kinds are
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
        if payload.kind != KIND_SSO_CONNECTION:
            raise ValueError(
                f"apply_identity_config does not know the config kind {payload.kind!r}. "
                "The vocabulary is apps/accounts/types.py's KIND_* constants."
            )
        # Through the bridge, for the same reason the service starts the run
        # through it: `apps.workflows` sits above `apps.accounts`, and an
        # upward import here would be the layer violation the bridge exists to
        # invert. THREE values — tenant, user id and the acting hat.
        tenant, _user_id, org = bridge.get(bridge.WORKFLOW_CONTEXT)()
        return _apply_sso_connection(payload, tenant=tenant, org=org)
    finally:
        close_old_connections()


def _platform_scope(kind: str) -> tuple[Any, Any, Any]:
    """A platform kind's scope, resolved — **and a stamped tenant refused, loudly**.

    Both callers are runs the *deployment* owns: `tenant=None`, a `platform:`
    workflow id, no acting hat (`_start_identity_run` passes `org=None` and
    `check_org_agreement` refuses one beside a null tenant). Until ADR core-9
    they resolved nothing, because the accessor that answers this question lives
    in `apps.workflows`, which sits **above** this app — so rung W7's builder
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
    org: Organization | None,
) -> IdentityConfigApplied:
    """One customer's identity provider, materialised as a Zitadel external IdP."""
    connection = SsoConnection.objects.for_tenant(tenant).filter(pk=UUID(payload.key)).first()
    if connection is None:
        raise NotFound("This SSO connection no longer exists.")

    if connection.is_active:
        resource = zitadel.ensure_oidc_identity_provider(
            name=_idp_name(connection),
            issuer=connection.issuer,
            client_id=connection.client_id,
            client_secret=connection.client_secret,
            existing_id=connection.zitadel_idp_id,
        )
    else:
        # **A disabled row materialises as a deactivated provider**, and this is
        # the half W2-R5 owed: before it, `disable_sso_connection` stopped our
        # own callback and left Zitadel perfectly willing to sign the same people
        # in. The object and its links stay, for the reason the service gives
        # about the row — a customer mid-migration who re-enables tomorrow must
        # not find everybody unlinked.
        resource = zitadel.deactivate_identity_provider(idp_id=connection.zitadel_idp_id)
    applied = IdentityConfigApplied(
        kind=payload.kind,
        key=payload.key,
        resource_id=resource.id,
        created=resource.created,
    )
    # The write-back goes through the service, like every other write in this
    # repository (house rule 10). The activity learned a fact; the service is
    # what is allowed to record it, audit it and log it.
    services.sync_identity_config(
        tenant=connection.tenant,
        # Nobody clicked this. Attributing it to whoever created the
        # connection last week would make the audit trail read plausibly and
        # be false. The hat still rides on it, so the audit row says which
        # part of the network the work was done for.
        actor=system_actor(connection.tenant, org),
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
    """
    client_id = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
    client_secret = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRET", "") or "").strip()
    resource = zitadel.ensure_google_identity_provider(
        name=str(getattr(settings, "GOOGLE_WORKFORCE_IDP_NAME", WORKFORCE_IDP_NAME)),
        client_id=client_id,
        client_secret=client_secret,
    )
    log.info(
        "accounts.workforce.materialised",
        resource_id=resource.id,
        created=resource.created,
    )
    return IdentityConfigApplied(
        kind=payload.kind,
        key=payload.key,
        resource_id=resource.id,
        created=resource.created,
    )


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

    A user with no `zitadel_sub` is a person who never signed in through the
    platform: there is nothing to deactivate, and reporting that as an empty
    resource id is the truth rather than a failure.
    """
    user = User.objects.filter(pk=UUID(payload.key)).first()
    if user is None:
        raise NotFound("That person's row no longer exists.")
    subject = str(user.zitadel_sub or "").strip()
    if not subject:
        return IdentityConfigApplied(kind=payload.kind, key=payload.key, resource_id="")
    # Links first, then the account. The other order leaves a window in which a
    # deactivated account still carries live federation links, and the whole
    # point of this run is that no window is left open.
    removed = zitadel.remove_identity_provider_links(user_id=subject)
    resource = zitadel.deactivate_user(user_id=subject)
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
        deactivated=resource.created,
    )
    return IdentityConfigApplied(
        kind=payload.kind,
        key=payload.key,
        resource_id=resource.id,
        created=resource.created,
    )


# What the workforce provider is called inside Zitadel. A constant rather than a
# derived name because there is exactly one of these per instance and its name is
# the only handle `ensure_google_identity_provider` has to find it by — the
# deployment has no row to record an id on. Overridable by a setting so two
# deployments against one Zitadel instance do not collide, the same reason
# `ZITADEL_PROJECT_NAME` is a setting.
WORKFORCE_IDP_NAME = "Workforce Google"


def _idp_name(connection: SsoConnection) -> str:
    """What this connection is called inside Zitadel.

    The tenant's slug and the connection's primary key, because the name is the
    second net `ensure_oidc_identity_provider` falls back to when our recorded
    id is gone — and a name derived from anything renamable would stop matching
    the day somebody renamed it, silently creating a second provider. The
    connection's display name is not in it for exactly that reason.
    """
    return f"{connection.tenant.slug}:{connection.pk}"


@activity.defn(name="provision_invited_identity")
def provision_invited_identity(payload: InvitedPerson) -> InvitedIdentity:
    """Give an invited person an account they can set a password on. **Both calls.**

    The second activity in this app that reaches the identity platform, and it
    reaches it the only way anything may (house rule 27): through
    `accounts.zitadel`, from an activity, where a management failure is a
    Temporal retry rather than a request nobody gets an answer to.

    Two calls and deliberately one activity. Splitting them would put a retry
    boundary between "the account exists" and "the account has a code", and the
    second half is the half that is not idempotent — a retry of a
    `create_invite_code` activity mints a second code and supersedes the first,
    so a run that succeeded at minting and failed at recording would email a
    code that a retry had already invalidated. Together, they retry as a unit:
    `ensure_invited_user` finds the account the previous attempt made, and the
    fresh code is the one that goes out.

    **Touches no model of ours, and needs none.** Everything it is told is in
    the payload, and everything it learns goes back in the return value — so
    unlike this module's other activity there is no row to read, no principal to
    restore for a query, and no `close_old_connections` to owe the pool. That is
    an absence worth stating rather than a line missing: the invitation row is
    already written and committed by the time this runs.

    **The code is never logged.** The one log line names the account and the
    branch taken; `set_credentials_url` embeds the code and does not appear in
    it. `tests/test_invited_provisioning.py` asserts that over the captured
    records rather than trusting this paragraph.
    """
    first_name, last_name = _invited_person_names(payload.email)
    user = zitadel.ensure_invited_user(
        email=payload.email,
        first_name=first_name,
        last_name=last_name,
    )
    try:
        code = zitadel.create_invite_code(user_id=user.id)
    except zitadel.ZitadelError as error:
        if not zitadel.is_already_initialized(error):
            raise
        # Not a failure: they already sign in here. The email will say so.
        log.info(
            "accounts.invitation.identity_already_initialized",
            invitation_id=payload.invitation_id,
            zitadel_user_id=user.id,
        )
        return InvitedIdentity(
            zitadel_user_id=user.id,
            created=user.created,
            already_initialized=True,
        )
    lifetime = zitadel.invite_code_lifetime()
    log.info(
        "accounts.invitation.identity_provisioned",
        invitation_id=payload.invitation_id,
        zitadel_user_id=user.id,
        created=user.created,
    )
    return InvitedIdentity(
        zitadel_user_id=user.id,
        created=user.created,
        set_credentials_url=zitadel.invite_url(user_id=user.id, code=code),
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


ACTIVITIES: list[Callable[..., Any]] = [apply_identity_config, provision_invited_identity]
