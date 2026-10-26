from typing import ClassVar

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
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 482,
        "91.docstring-tail": 1433,
        "91.module-tail": 495,
        "91.narrative": 23,
    }

    def ready(self) -> None:
        """Hand `emit` and the inbound verifier to whatever cannot import this app.

        `core` cannot import `events`, and a `core` service that changes
        something a subscriber cares about still has to say so. It calls
        `bridge.get("events.emit")`; this is what fills it, in every process.

        The four inbound names are the same inversion for a sibling:
        `apps.connections` may not import `apps.events`, and its receiver
        verifies with the ONE verifier here rather than a copy of its own.
        """
        from apps.core import bridge
        from apps.events.receivers import (
            signature_matches,
            signature_v2_matches,
            signature_v2_tolerance,
            verify_and_store,
        )
        from apps.events.services import emit

        bridge.register(bridge.EMIT, emit)
        bridge.register(bridge.SIGNATURE_MATCHES, signature_matches)
        bridge.register(bridge.SIGNATURE_V2_MATCHES, signature_v2_matches)
        bridge.register(bridge.SIGNATURE_V2_TOLERANCE, signature_v2_tolerance)
        bridge.register(bridge.VERIFY_AND_STORE, verify_and_store)
