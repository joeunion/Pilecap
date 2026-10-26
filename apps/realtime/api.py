"""The socket door's REST half: the ticket a client trades for a socket, never a URL credential."""

from __future__ import annotations

from ninja import Router, Status

from apps.accounts.auth import API_AUTH
from apps.core.api.acting import acting
from apps.core.api.docs import Tag
from apps.core.requests import TenantRequest
from apps.realtime import services
from apps.realtime.schemas import TICKET_FAMILY, SocketTicketOut
from apps.realtime.services import TICKET_TTL

TAGS = {
    TICKET_FAMILY: Tag(
        "Live updates",
        "The event socket at `ws/events/`, and the one-use ticket a client presents to open "
        "it. A credential never travels in the socket's URL: a browser signed in by cookie "
        "opens the socket as it is, and every other client mints a ticket here first.",
        plane="everyday",
        plane_note="the one-use ticket that opens this tenant's event socket.",
    ),
}

PREFIX = TICKET_FAMILY

router = Router(tags=[TICKET_FAMILY], auth=API_AUTH)


@router.post("/", response={201: SocketTicketOut}, url_name="socket_ticket-create")
def create_socket_ticket_route(request: TenantRequest) -> Status[SocketTicketOut]:
    """Mint a socket ticket

    A one-use ticket, good for 60 seconds, that opens this tenant's socket as `ws/events/?ticket=`.
    """
    actor, tenant = acting(request)
    issued = services.issue_socket_ticket(tenant=tenant, actor=actor)
    return Status(
        201,
        SocketTicketOut(
            ticket=issued.ticket,
            expires_in=int(TICKET_TTL.total_seconds()),
            expires_at=issued.expires_at,
        ),
    )
