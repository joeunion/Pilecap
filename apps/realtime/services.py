"""The socket ticket: minted by a service, cached 60 s, taken once."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.core.cache import cache

from apps.accounts.models import ApiToken, User
from apps.core.actor import Actor
from apps.core.exceptions import DomainError, NoActingScope, Remedy, register_refusal
from apps.core.middleware import AUTHORIZATION_HEADER
from apps.core.models import Tenant
from apps.core.service import service
from apps.core.time import now

__all__ = [
    "TICKET_TTL",
    "IssuedTicket",
    "SocketCredentialInUrl",
    "issue_socket_ticket",
    "redeem_socket_ticket",
]

TICKET_TTL = timedelta(seconds=60)
TICKET_CACHE_PREFIX = "realtime:ticket:"
TICKET_ROUTE = "POST /api/v1/socket-tickets/"


register_refusal(
    code="socket_credential_in_url",
    boundary="door",
    remedy=(
        "A socket handshake carried a bearer as ?token=, and a URL is written into access "
        "logs and browser history. The socket takes the bearer in the Authorization header, "
        "or a one-use ticket minted over REST and presented as ?ticket=."
    ),
    fact=(
        "This socket does not read a credential from its URL. Mint a ticket and open the "
        "socket with it, or send the bearer in the Authorization header."
    ),
    remedies=(
        Remedy(
            "Mint a socket ticket and open the socket with ?ticket=", "route:socket_ticket-create"
        ),
        Remedy("Send the bearer in the Authorization header", f"header:{AUTHORIZATION_HEADER}"),
    ),
    status=400,
)


class SocketCredentialInUrl(DomainError):
    """A handshake that sent its bearer as `?token=`."""

    code = "socket_credential_in_url"
    default_detail = (
        f"This socket does not read a bearer from ?token=; mint a ticket with {TICKET_ROUTE} "
        "and open the socket with ?ticket=, or send the bearer in the Authorization header."
    )


@dataclass(frozen=True)
class IssuedTicket:
    """A minted ticket's plaintext and the instant it dies."""

    ticket: str
    expires_at: datetime


def _key(ticket: str) -> str:
    return f"{TICKET_CACHE_PREFIX}{hashlib.sha256(ticket.encode('utf-8')).hexdigest()}"


@service
def issue_socket_ticket(*, tenant: Tenant, actor: Actor) -> IssuedTicket:
    """Mint a one-use, 60-second socket ticket bound to this actor's person, token and tenant."""
    # authz: the caller's own credential moved off the URL — it opens no more than what minted it
    if actor.user is None:
        raise NoActingScope()
    ticket = secrets.token_urlsafe(32)
    expires_at = now() + TICKET_TTL
    cache.set(
        _key(ticket),
        {
            "user_id": str(actor.user.pk),
            "tenant_id": str(tenant.pk),
            "token_id": str(actor.token.pk) if actor.token is not None else None,
            "expires_at": expires_at.isoformat(),
        },
        int(TICKET_TTL.total_seconds()),
    )
    return IssuedTicket(ticket=ticket, expires_at=expires_at)


def _take(ticket: str) -> dict[str, str | None] | None:
    """Take a parked ticket once: of two racing handshakes only the winning delete consumes it."""
    key = _key(ticket)
    stored = cache.get(key)
    if not cache.delete(key) or not isinstance(stored, dict):
        return None
    if now() >= datetime.fromisoformat(str(stored["expires_at"])):
        return None
    return stored


# rule-16: redeeming spends a ticket for its principal; no lexicon verb says take-once-and-read
def redeem_socket_ticket(*, ticket: str) -> tuple[User, Tenant, ApiToken | None] | None:
    """The live principal a ticket names, taken once; `None` once spent, expired or revoked."""
    stored = _take(ticket) if ticket else None
    if stored is None:
        return None
    user = User.objects.filter(pk=UUID(str(stored["user_id"])), is_active=True).first()
    tenant = Tenant.objects.filter(pk=UUID(str(stored["tenant_id"]))).first()
    if user is None or tenant is None or not tenant.is_active:
        return None
    token: ApiToken | None = None
    if stored.get("token_id"):
        token = ApiToken.objects.filter(
            pk=UUID(str(stored["token_id"])), user=user, revoked_at__isnull=True
        ).first()
        if token is None:
            return None
    return user, tenant, token
