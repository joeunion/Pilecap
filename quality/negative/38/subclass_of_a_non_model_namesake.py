# NEGATIVE (rule 38): `Holder` inherits this module's dataclass `Widget`, not the
# org-scoped model of that name, so its app owes `HolderOut` nothing. Must stay silent.
from dataclasses import dataclass


@dataclass
class Widget:
    name: str


class Holder(Widget):
    pass
