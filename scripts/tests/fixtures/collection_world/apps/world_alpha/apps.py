"""A fixture-world app. Collected by the drives; never run by the suite."""

from django.apps import AppConfig


class WorldAlphaConfig(AppConfig):
    """A scratch app the collection drives install, collect and remove."""

    name = "apps.world_alpha"
    verbose_name = "WorldAlpha"
    depends_on: tuple[str, ...] = ()
