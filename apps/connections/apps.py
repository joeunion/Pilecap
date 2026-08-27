from django.apps import AppConfig


class ConnectionsConfig(AppConfig):
    """The platform app for talking to systems this product does not own.

    A per-tenant `Connection` (provider, encrypted credentials, status), the
    `httpx` client factory every outbound call goes through, the OAuth-callback
    pattern, and the one signature-verified inbound webhook receiver.

    `events` is named in `depends_on` because this app hands a verified inbound
    webhook to the event spine — but it does so by **runtime lookup, not by
    import** (`services._events_callable`). The layer contract in
    `pyproject.toml` makes the platform apps siblings, which is deliberate:
    `connections` must keep working, and its tests must keep passing, in a tree
    where `apps/events` is not there at all. Declaring the label here makes the
    coupling reviewable rather than invisible, which is what `depends_on` is
    for; nothing in this app imports `apps.events` statically.
    """

    name = "apps.connections"
    verbose_name = "Connections"
    depends_on: tuple[str, ...] = ("core", "accounts", "events")
