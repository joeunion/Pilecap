from typing import ClassVar

from django.apps import AppConfig


class ConnectionsConfig(AppConfig):
    """The platform app for talking to systems this product does not own.

    A per-tenant `Connection` (provider, encrypted credentials, status), the
    `httpx` client factory every outbound call goes through, the OAuth-callback
    pattern, and the one signature-verified inbound webhook receiver.

    `events` is named in `depends_on` because this app verifies an inbound
    webhook with the event spine's one verifier and hands it to the spine — but
    it does so **through `core.bridge`, not by import** (the names
    `apps/events/apps.py` registers). The layer contract in `pyproject.toml`
    makes the platform apps siblings, which is deliberate. Declaring the label
    here makes the coupling reviewable rather than invisible, which is what
    `depends_on` is for; nothing in this app imports `apps.events`.
    """

    name = "apps.connections"
    verbose_name = "Connections"
    depends_on: tuple[str, ...] = ("core", "accounts", "events")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 295,
        "91.docstring-tail": 752,
        "91.module-tail": 256,
        "91.narrative": 11,
    }

    def ready(self) -> None:
        """Declare the signed inbound receiver before any request arrives."""
        from apps.connections.api import _takes_no_address
        from apps.core.middleware import declare_signed_door

        declare_signed_door(url_name="api:connection-webhook", refusal=_takes_no_address)
