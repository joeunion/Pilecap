# Planted: a road defined inside a function. Its decorator runs only when the
# outer function is called, never at import, so the census reads a marker the
# registry never holds — rule 84 refuses it by where it sits: a road is
# unconditional and module-level.
from apps.core.roads import road


def canary_frob_factory() -> object:
    """Build the frob on demand."""

    @road("frob_nested", example="apps/zzz_canary/services.py::canary_frob_factory")
    def canary_frob_inner() -> None:
        """A road that exists only once its factory is called."""

    return canary_frob_inner
