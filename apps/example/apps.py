from typing import ClassVar

from django.apps import AppConfig


class ExampleConfig(AppConfig):
    """The worked example. A product deletes this app once it has its own."""

    name = "apps.example"
    verbose_name = "Example"
    # The one app a deployment may leave OUT (`DJB_DISABLED_APPS=example`).
    optional: ClassVar[bool] = True
    # What this app may import (house rule 7).
    depends_on: tuple[str, ...] = ("core", "accounts", "workflows", "search", "djb_tags")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 0,
        "91.docstring-tail": 0,
        "91.module-tail": 0,
        "91.narrative": 0,
    }

    # golden: webhook-in onboarding begin
    def ready(self) -> None:
        """Register the onboarding inbound webhook through `pilecap.connections`."""
        from apps.example.integrations import register_onboarding_webhooks

        register_onboarding_webhooks()

    # golden: webhook-in onboarding end
