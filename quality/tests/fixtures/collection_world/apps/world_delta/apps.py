"""A fixture-world app. Collected by the drives; never run by the suite."""

from django.apps import AppConfig


class WorldDeltaConfig(AppConfig):
    """A scratch app the collection drives install, collect and remove."""

    name = "apps.world_delta"
    verbose_name = "WorldDelta"
    depends_on: tuple[str, ...] = ()
