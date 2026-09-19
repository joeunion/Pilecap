"""A fixture-world app. Collected by the drives; never run by the suite."""

from django.apps import AppConfig


class WorldGammaConfig(AppConfig):
    """A scratch app the collection drives install, collect and remove."""

    name = "apps.world_gamma"
    verbose_name = "WorldGamma"
    depends_on: tuple[str, ...] = ("world_beta",)
