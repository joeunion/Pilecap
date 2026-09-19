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

from dataclasses import dataclass, field
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
    #: **The permission memo, and it is a cache with a declared contract.**
    #:
    #: * **Source of truth** — the three tables `core.authz.effective_permissions`
    #:   reads: this person's `Membership` rows in this tenant, the `Grant` rows
    #:   on them, and the `RolePermission` delta rows for the role keys they
    #:   name. The RAW rows are what is held, never a resolved answer, because
    #:   the rows are `at`-independent (the chain filter is Python) and one
    #:   fetch therefore answers the question at every node.
    #: * **Key** — this actor INSTANCE, and inside it the one identity the
    #:   instance is about: `(user.pk, tenant.pk)`. A question about anybody
    #:   else — the TARGET of a hand-out, the person a wall is measuring — misses
    #:   and reads the tables, which is what keeps a wall reading the truth
    #:   rather than the granter's warm rows.
    #: * **TTL** — the instance's lifetime, which is one request, one activity,
    #:   one command. Doors build a fresh `Actor` per request
    #:   (`actor_from_request`), so nothing outlives the call that made it.
    #: * **Invalidation** — `forget_permissions()`, and nothing else.
    #: * **Failure** — a miss is the three statements. A miss never widens.
    #: * **Stampede** — none: one actor, one thread, one request.
    #:
    #: **THE STALE WINDOW, said rather than hidden, and it has two halves.**
    #:
    #: 1. **This person narrows themselves.** A write that changes what the
    #:    ACTING person may do, made inside a request that has already asked —
    #:    an owner withholding a key from their own membership and then acting
    #:    again in the same request — is answered from the pre-write rows until
    #:    the request ends. A service that must see its own narrowing
    #:    immediately calls `forget_permissions()` after the write.
    #: 2. **SOMEBODY ELSE narrows this person, concurrently.** Another request,
    #:    another process, an activity: nothing in *this* process holds the
    #:    actor instance, so no service can call `forget_permissions()` for it
    #:    and the answer is the pre-write one until this actor dies. **The bound
    #:    is one actor instance** — a request, an activity, a command — and the
    #:    remedies are the socket kick (`core.services.kick_if_reads_narrowed`,
    #:    which closes the sockets of a person whose reads just shrank) and the
    #:    next request, which reads the tables again.
    #:
    #: A write about somebody else's set is never stale *here*: a question about
    #: another identity misses the memo entirely (`core.authz._memo_box`).
    #:
    #: **`init=False`, and that is a wall rather than tidiness.**
    #: `dataclasses.replace(actor, user=other)` copies every `init=True` field
    #: into the new instance, so a memo that arrived through `__init__` would
    #: travel into a REBASED actor and pass the identity gate on that actor's
    #: own identity — the old person's rows answering for the new person, with
    #: nothing to see at the call site. `init=False` gives every constructed
    #: actor, replaced ones included, its own empty box.
    _permission_rows: dict[str, Any] = field(
        default_factory=dict, init=False, compare=False, repr=False
    )

    def forget_permissions(self) -> None:
        """Drop the memoised rows; the next question pays the three statements.

        The one invalidation, called by a service that narrowed the acting
        person's own set and must not answer the rest of the request from what
        it just changed. It is a `clear()` rather than a reassignment because
        an `Actor` is frozen: the slot is a container the instance owns, and
        emptying it is not mutating the statement the actor makes about a call.
        """
        self._permission_rows.clear()

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
