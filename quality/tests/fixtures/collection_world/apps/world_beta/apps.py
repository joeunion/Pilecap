"""A fixture-world app. Collected by the drives; never run by the suite."""

from django.apps import AppConfig


class WorldBetaConfig(AppConfig):
    """A scratch app the collection drives install, collect and remove."""

    name = "apps.world_beta"
    verbose_name = "WorldBeta"
    depends_on: tuple[str, ...] = ("world_alpha",)
