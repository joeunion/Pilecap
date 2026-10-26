# The road that STANDS for the planted job: lexically first by path, so the
# marker in `services.py` is the second road the canary expects named.
from apps.core.roads import road


@road("frobnicate", example="apps/zzz_canary/services.py::canary_frobnicate_second")
def canary_frobnicate_first() -> None:
    """The one builder of the frob."""
