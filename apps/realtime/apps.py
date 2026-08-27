from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    """The socket door: one consumer per tenant group, and the bridge that pushes to it.

    `depends_on` names `accounts` because the socket door authenticates a
    bearer token with the very same `authenticate_token` service the REST and
    MCP doors use — one token, one user, one tenant, three doors.

    **`ready()` fills the two bridge names this app provides.**
    `architecture.md` rules that upward — and sideways — calls invert through
    `core.bridge`: a higher app fills a runtime registry from its
    `AppConfig.ready()` and the caller looks the entry up by name.
    `apps.events` fans a dispatched event out to whoever is connected and may
    not import this app (`import-linter` holds the platform apps independent),
    so it asks the registry for `bridge.REALTIME_PUSH` and gets what is
    registered here.

    What is registered is `push_from_spine` rather than `push_event` itself,
    and the difference is the caller's, not this app's: the caller is a plain
    `def` activity on the worker's thread pool with no loop to await on, and it
    cannot build this app's `EventMessage` because the two apps are siblings.
    `bridge.py` says both in full; `push_event` remains the async in-app API.

    **`bridge.KICK` is the second name** (ADR realtime-2). Socket auth is
    resolved once, at the handshake, so a token revoked an hour into a
    connection kept delivering until the client happened to hang up.
    `apps.accounts` is where revocation and erasure happen and it sits *below*
    this app, so it cannot import the closer any more than the spine can import
    the pusher — the same inversion, registered here for the same reason.

    `ready()` is the hook that runs in every process — the web server, the
    Temporal worker, `manage.py`, pytest — which is exactly the property a
    registry needs. The imports are inside it because `apps.py` is read by
    `config.settings.discovery` before Django exists.
    """

    name = "apps.realtime"
    verbose_name = "Realtime"
    depends_on: tuple[str, ...] = ("core", "accounts")

    def ready(self) -> None:
        from apps.core import bridge
        from apps.realtime.bridge import kick_from_spine, push_from_spine

        bridge.register(bridge.REALTIME_PUSH, push_from_spine)
        bridge.register(bridge.KICK, kick_from_spine)
