# Planted: a road only a type checker would ever see. Under `if TYPE_CHECKING:`
# the decorated definition never runs, so import produces no road while a static
# reader shows one — rule 84 refuses it by where it sits: a road is unconditional.
from typing import TYPE_CHECKING

from apps.core.roads import road

if TYPE_CHECKING:

    @road("frob_typed", example="apps/zzz_canary/services.py::canary_frob_typed")
    def canary_frob_typed() -> None:
        """A road that exists for the type checker alone."""
