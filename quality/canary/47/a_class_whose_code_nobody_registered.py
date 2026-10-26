# Planted: a refusal class declaring a code the live registry never holds — the
# tree's reader of the registry (`code = "..."` on the class) and the import's
# reader (`core.exceptions.REFUSALS`) disagree by exactly this code.
from apps.core.exceptions import Forbidden


class ZzzCanaryUnregistered(Forbidden):
    """A refusal whose code was never registered beside it."""

    code = "zzz_canary_unregistered"
