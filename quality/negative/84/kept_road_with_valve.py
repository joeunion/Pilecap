# Planted: a second road for one job, DECLARED — the valve directly above the
# marker, with its reason. Silent, and the standing override census gains one.
from apps.core.roads import road


# rule-84: our refusal body predates the platform's and every client of ours branches on it
@road("frobnicate", example="apps/zzz_canary/selectors.py::canary_frobnicate_first")
def canary_frobnicate_second() -> None:
    """A second builder of the frob, beside the one that stands."""
