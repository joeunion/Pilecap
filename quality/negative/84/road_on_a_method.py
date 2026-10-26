# Planted: a road on a method directly inside a module-level class — the one
# nesting a road may have, because import defines it exactly once.
from apps.core.roads import road


class CanaryFrobber:
    """The frob's owner."""

    @road("frob_method", example="apps/zzz_canary/services.py::CanaryFrobber.frob")
    def frob(self) -> None:
        """Frob the one way this product frobs, from its owner."""
