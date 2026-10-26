from typing import ClassVar

from django.apps import AppConfig


class CommsConfig(AppConfig):
    """The one door out of this product to a person: `comms.send()` is the only legal sender.

    `depends_on` sits above the spine (ADR comms-1): events, workflows and connections are called.
    """

    name = "apps.comms"
    verbose_name = "Communications"
    depends_on: tuple[str, ...] = ("core", "accounts", "events", "workflows", "connections")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 1625,
        "91.docstring-tail": 4378,
        "91.module-tail": 891,
        "91.narrative": 32,
    }

    def ready(self) -> None:
        """Claim this app's inbound status deliveries: the whole registration (ADR comms-3)."""
        from apps.comms.models import Channel
        from apps.comms.providers import (
            SMS_STATUS_PROVIDER,
            STATUS_PROVIDER,
            register_status_provider,
            verify_sms_webhook,
            verify_status_webhook,
        )

        register_status_provider(STATUS_PROVIDER, Channel.EMAIL.value, verify_status_webhook)
        register_status_provider(SMS_STATUS_PROVIDER, Channel.SMS.value, verify_sms_webhook)
