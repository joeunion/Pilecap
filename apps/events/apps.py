from django.apps import AppConfig


class EventsConfig(AppConfig):
    """The event spine: `emit`, the outbox, signed deliveries, the inbound door.

    `depends_on` names `workflows` even though nothing here imports it: the
    dependency is real — emitting starts the dispatch workflow — and it is made
    through `core.bridge`, because `import-linter` holds the platform apps
    independent of one another. Declaring it is the honest answer; hiding it
    behind the bridge without declaring it would be the dependency the tooling
    cannot see that the bridge exists to avoid.
    """

    name = "apps.events"
    verbose_name = "Events"
    depends_on: tuple[str, ...] = ("core", "accounts", "workflows")

    def ready(self) -> None:
        """Hand `emit` to whatever sits below this app.

        `core` cannot import `events`, and a `core` service that changes
        something a subscriber cares about still has to say so. It calls
        `bridge.get("events.emit")`; this is what fills it, in every process.
        """
        from apps.core import bridge
        from apps.events.services import emit

        bridge.register(bridge.EMIT, emit)
