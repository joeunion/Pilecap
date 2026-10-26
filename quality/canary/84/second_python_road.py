# Planted: a SECOND Python road for one job. Its twin (planted beside it in
# `selectors.py`) marks the same job first by path, so this one — in
# `services.py` — is the second road, and rule 84 must name both. Self-contained
# on purpose: a canary keyed on a sibling rung's marker is dead on whichever
# tree merges first.
from apps.core.roads import road


@road("frobnicate", example="apps/zzz_canary/selectors.py::canary_frobnicate_first")
def canary_frobnicate_second() -> None:
    """A second builder of the frob, beside the one that stands."""
