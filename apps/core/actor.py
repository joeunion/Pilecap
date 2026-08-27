"""Who a piece of work is being done by, and on whose behalf.

`request.user` answers half of it. The other half is the half that matters in
an audit trail: **was this a person, a machine acting as a person, or the
system acting for nobody** — and which token, if a token was involved. A row
that only records `user_id` cannot tell a support agent's click from an
integration's overnight sync, and those are different facts about the same
person.

    Actor(user=..., token=None, kind="human",  tenant=...)   # a session
    Actor(user=..., token=<row>, kind="agent", tenant=...)   # a bearer token
    Actor(user=None, token=None, kind="system", tenant=...)  # a workflow, a command

Frozen, because an actor is a statement about a call and not a variable: a
service that could reassign `actor.tenant` halfway through would be a service
that authorised against one tenant and wrote into another.

**`core` sits below `accounts`**, so the token is typed as the row it is
(`models.Model`) rather than as `ApiToken`, and `AuditEntry.actor_token` names
`"accounts.ApiToken"` as a lazy string reference — the same way `Membership.user`
already points at `settings.AUTH_USER_MODEL`. Django points downward without
importing upward; so does this.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.http import HttpRequest

from apps.core.models import Organization, Tenant

ActorKind = Literal["human", "agent", "system"]

# Where `apps.accounts.auth.ApiTokenAuth` leaves what it resolved. Declared
# here, in the layer below, so both sides name the same string once.
TOKEN_AUTH_ATTR = "authenticated_by_token"
TOKEN_ATTR = "api_token"


@dataclass(frozen=True)
class Actor:
    """The acting principal for one call."""

    user: AbstractBaseUser | None
    token: models.Model | None
    kind: ActorKind
    tenant: Tenant | None
    #: The **acting hat**: which organization in the tenant this call is being
    #: made as. Resolved by the door (`X-Org`, the MCP principal, the workflow
    #: headers) and revalidated every request — never chosen by the caller and
    #: never remembered from the last one. `None` means no hat was resolved,
    #: and every org-scoped read made with it returns nothing (`visible_to`).
    org: Organization | None = None

    @property
    def user_id(self) -> Any | None:
        return self.user.pk if self.user is not None else None

    @property
    def org_id(self) -> Any | None:
        return self.org.pk if self.org is not None else None

    @property
    def token_id(self) -> Any | None:
        return self.token.pk if self.token is not None else None

    @property
    def is_authenticated(self) -> bool:
        """True when somebody, human or machine, is behind this call.

        A `system` actor is *not* authenticated in this sense: nobody asked for
        it. Authorisation treats that separately — see `core.authz`.
        """
        return self.user is not None


def actor_from_request(request: HttpRequest) -> Actor:
    """The actor a door resolved for this request.

    A bearer token makes the call an `agent` even though it acts as a person:
    the person authorised the machine once, months ago, and "a human clicked
    this" is not true of it. A session makes it `human`. Neither makes it
    `system` — that one is reserved for work nobody asked for directly.
    """
    user = getattr(request, "user", None)
    if user is not None and not user.is_authenticated:
        user = None
    by_token = bool(getattr(request, TOKEN_AUTH_ATTR, False))
    return Actor(
        user=user,
        token=getattr(request, TOKEN_ATTR, None),
        kind="agent" if by_token else "human",
        tenant=getattr(request, "tenant", None),
        org=getattr(request, "org", None),
    )


def actor_for(
    *,
    user: AbstractBaseUser | None,
    tenant: Tenant | None,
    kind: ActorKind = "human",
    token: models.Model | None = None,
    org: Organization | None = None,
) -> Actor:
    """Build an actor from parts. For the admin door, tests, and seeding."""
    return Actor(user=user, token=token, kind=kind, tenant=tenant, org=org)


def system_actor(tenant: Tenant | None = None, org: Organization | None = None) -> Actor:
    """The product acting for itself: a workflow, a schedule, a command.

    It has no user, and that is the honest answer — attributing an overnight
    reconciliation to whoever happened to trigger the process last week is how
    an audit trail becomes fiction.
    """
    return Actor(user=None, token=None, kind="system", tenant=tenant, org=org)
