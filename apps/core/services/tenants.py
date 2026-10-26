"""Tenant configuration."""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.contrib.auth.base_user import AbstractBaseUser

from apps.core.actor import Actor, system_actor
from apps.core.authz import require
from apps.core.exceptions import Conflict, Invalid, as_invalid
from apps.core.flags import FLAGS_KEY
from apps.core.models import Tenant
from apps.core.service import service, write_audit
from apps.core.services._hub import create_tenant, root_organization
from apps.core.time import now

# --- Tenant configuration ----------------------------------------------------


@service
def update_tenant_settings(
    *,
    tenant: Tenant,
    values: dict[str, Any] | None = None,
    timezone: str | None = None,
    locale: str | None = None,
    actor: Actor,
) -> Tenant:
    """Change a tenant's own configuration.

    `values` is **merged** at the top level rather than replacing the column: a
    caller that meant to set one key and sent one key would otherwise silently
    delete every other. A key is removed by sending it as `None`.

    The timezone is validated against the real zone database here, because a
    typo'd `"Europe/Lisbn"` stored happily becomes a `ZoneInfoNotFoundError` at
    render time, in whichever request first tries to show somebody a date.

    **`actor` arrived with the door**: nothing outside the tree could
    reach this service before, so authorizing nobody was not reachable either.
    Measured at the tenant's **root**, not the hat — configuring the
    tenant is configuring the whole tenant, and a branch admin administers a
    branch. A `system` actor is the product acting for itself — the same
    reading `_refuse_escalation` gives, keyed on the KIND since ADR core-22's
    L1 ruling rather than on an actor that happened to be missing.
    """
    if actor.kind != "system":
        require(actor, "tenant.update", root_organization(tenant=tenant))
    changed: list[str] = []
    if values is not None:
        merged = dict(tenant.settings or {})
        for key, value in values.items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = value
        tenant.settings = merged
        changed.append("settings")
    if timezone is not None:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise Invalid({"timezone": [f"{timezone!r} is not a known time zone."]}) from exc
        tenant.timezone = timezone
        changed.append("timezone")
    if locale is not None:
        tenant.locale = locale
        changed.append("locale")
    if not changed:
        return tenant
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=[*changed, "updated_at"])
    return tenant


@service
def set_flag(*, tenant: Tenant, name: str, enabled: bool | None, actor: Actor) -> Tenant:
    """Turn a feature on or off for one tenant.

    `enabled=None` clears the tenant's opinion so it inherits the
    deployment-wide default again — which is what finishing a rollout looks
    like, and is a different thing from turning the feature off.

    The `actor` is handed straight to `update_tenant_settings`, which is where
    the authorization lives: a flag IS a settings key, and two checks over one
    write would be two places to get it wrong. Note that this therefore writes
    **two** audit rows, `core.set_flag` and `core.update_tenant_settings`, and
    that is the honest record — one call, two writes, both by the same actor.
    """
    flags = dict((tenant.settings or {}).get(FLAGS_KEY, {}))
    if enabled is None:
        flags.pop(name, None)
    else:
        flags[name] = bool(enabled)
    # authz: delegated, deliberately. A flag IS a settings key, and the write
    # below is the one that lands it — `update_tenant_settings` asks
    # `tenant.configure` against the tenant's root. Asking the same question
    # twice over one write would be two places to get it wrong, and the second
    # one would be the one nobody updates.
    return update_tenant_settings(tenant=tenant, values={FLAGS_KEY: flags}, actor=actor)


# --- The first tenant --------------------------------------------------------


# door: no door reaches it; only this tree's own hands do — `manage.py bootstrap_tenant`
@service
# rule-13: this service has no `tenant=` to take, and cannot. It is the one
# write in the product that PRODUCES the tenant its own audit row is about — at
# the moment it is called there are none — so the wrapper, which reads a row's
# tenant from the call, has nothing to read. The row is written explicitly
# below, onto the tenant this creates (ADR core-17, ADO-5); auditing into the
# platform population instead was considered and rejected, because the row is
# about a tenant that now exists.
def create_first_tenant(*, user: AbstractBaseUser, name: str, slug: str) -> Tenant:
    """Make the FIRST tenant of an installation, and hand it to one owner.

    ADR core-17. Before this, a real environment's first tenant was made by
    hand-driving services in a shell — `seed --force` is dev data by contract
    and refuses outside DEBUG — so the one step every deployment must take was
    the one step nothing wrote down.

    Three rows, one transaction: the tenant, its root organization, and one
    OWNER membership for `user`. All three come out of `create_tenant`, which
    already makes the root and already makes the first membership an owner
    (somebody has to be able to add the second one).

    **It refuses if ANY tenant exists**, and that is the whole safety of it. A
    command that quietly made a second tenant on a live box would be a footgun
    with a friendly name: "bootstrap" reads like "set this up", and an operator
    running it twice must get a refusal rather than a surprise.

    **The audit row rides the tenant this creates** — the birth certificate
    (ADO-5). It is written here rather than by the `@service` wrapper because
    the wrapper reads the row's tenant from the call, and this call has none to
    give: the tenant is the output. Auditing into the platform population
    instead was rejected, because the row is about a tenant that now exists.
    `create_tenant` stays unaudited, exactly as it was.

    **The name.** `manage.py bootstrap_tenant` is the ratified command name and
    it has not moved; this function is `create_first_tenant` because house rule
    16 reads a service's first word against a declared lexicon and `bootstrap`
    is not in it. Adding it would mean changing `quality/rules.yaml`, which is
    not authorised here, so the lexicon won and the command kept its name.

    `user` is resolved by the caller, as every door resolves its rows. This
    service does not create one: `accounts.create_user` is the one write path
    onto the user table and `core` may not import `accounts` (the fixed layer
    direction). On a real environment the person is already there — they signed
    in through the workforce IdP, which is what made the row — and naming
    somebody who is not is a refusal at the door, not a silent second user.
    """
    if Tenant.objects.exists():
        raise Conflict(
            "This installation already has a tenant, so there is no first one to make. "
            "Add further tenants through the product rather than through the shell."
        )
    tenant = create_tenant(name=name, slug=slug, owner=user, actor=system_actor())
    write_audit(
        action="core.create_first_tenant",
        tenant=tenant,
        actor=None,
        payload={"user_id": str(user.pk), "slug": tenant.slug},
        outcome="ok",
        result=tenant,
    )
    return tenant


# --- Tenant lifecycle --------------------------------------------------------


# door: an operator act; its door is `TenantAdmin`'s action, which rule 42 does not read
@service
def suspend_tenant(*, tenant: Tenant, reason: str = "", actor: Actor) -> Tenant:
    """Stop a tenant working, reversibly. Nothing is deleted.

    Suspension is what a missed invoice or an abuse report leads to, and it has
    to be undoable in one call — so it is a status and a timestamp, never a
    cascade of deletes. Every row stays exactly where it is.


    # authz: an operator act with no predicate — no role inside a tenant is above the platform;
    # the staff door bounds it, and the audit row names the staff member (ADR core-22).
    """
    tenant.status = Tenant.Status.SUSPENDED
    tenant.suspended_at = now()
    if reason:
        tenant.settings = {**(tenant.settings or {}), "suspension_reason": reason}
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=["status", "suspended_at", "settings", "updated_at"])
    # **And the sockets already open are hung up on** (R4 F2, house rule 36).
    # A suspension is refused at the next HANDSHAKE and nowhere else, so
    # without this every live connection went on hearing for the life of the
    # connection while the REST door answered 403 to the same credential.
    close_tenant_sockets_on_commit(tenant_id=tenant.pk, reason=KICK_TENANT_SUSPENDED)
    return tenant


# door: an operator act; its door is `TenantAdmin`'s action, which rule 42 does not read
@service
def resume_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    """Undo a suspension.

    # authz: an operator act with no predicate — no role inside a tenant is above the platform;
    # the staff door bounds it, and the audit row names the staff member (ADR core-22).
    """
    if tenant.status == Tenant.Status.CLOSED:
        raise Conflict("A closed tenant is not resumed; that is a new decision and a new service.")
    tenant.status = Tenant.Status.ACTIVE
    tenant.suspended_at = None
    remaining = dict(tenant.settings or {})
    remaining.pop("suspension_reason", None)
    tenant.settings = remaining
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=["status", "suspended_at", "settings", "updated_at"])
    return tenant


# door: an operator act; its door is `TenantAdmin`'s action, which rule 42 does not read
@service
def close_tenant(*, tenant: Tenant, actor: Actor) -> Tenant:
    """End a tenant. Terminal, and still not a delete.

    The rows stay. An audit trail, an invoice history and a retention obligation
    all outlive the customer relationship, and erasure is a separate operation
    with its own rules. Closing is the *business* fact; deleting is a different
    one, and conflating them loses the first.


    # authz: an operator act with no predicate — no role inside a tenant is above the platform;
    # the staff door bounds it, and the audit row names the staff member (ADR core-22).
    """
    tenant.status = Tenant.Status.CLOSED
    tenant.closed_at = now()
    with as_invalid():
        tenant.full_clean()
    tenant.save(update_fields=["status", "closed_at", "updated_at"])
    # The terminal half of the same sentence (R4 F2, house rule 36). Closing
    # is the one act after which it must never be the case that somebody is
    # still receiving, and a sibling service calling the seam does not make
    # this one call it.
    close_tenant_sockets_on_commit(tenant_id=tenant.pk, reason=KICK_TENANT_CLOSED)
    return tenant


from apps.core.services.sockets import (  # noqa: E402
    KICK_TENANT_CLOSED,
    KICK_TENANT_SUSPENDED,
    close_tenant_sockets_on_commit,
)
