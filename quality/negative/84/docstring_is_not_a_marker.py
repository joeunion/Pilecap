# Planted: prose that SPELLS both marker forms, beside a real road for the same
# job. If a docstring could carry a marker this would be a second road; it is
# prose, so the one real marker stands alone and nothing fires.
from apps.core.roads import road


@road("frobnicate", example="apps/zzz_canary/services.py::frobnicate_once")
def frobnicate_once() -> None:
    """The one way to frob."""


def explain_the_frob() -> None:
    """How a road is declared, in words.

    @road("frobnicate", example="apps/zzz_canary/services.py::explain_the_frob")
# road: frobnicate — a second teller of the frob · example: apps/zzz_canary/services.py::explain_the_frob
    """
