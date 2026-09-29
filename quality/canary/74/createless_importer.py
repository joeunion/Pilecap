"""Planted: an importer for a noun with no create road — an import is creates."""

from typing import Any

from apps.core.schemas import StrictIn
from apps.core.verbs import Importer


class CanaryWareRow(StrictIn):
    """One planted row."""

    label: str


def _natural_key(*, tenant: Any, row: CanaryWareRow) -> Any:
    return None


def _apply(*, tenant: Any, actor: Any, row: CanaryWareRow) -> tuple[Any, str]:
    return None, "unchanged"


IMPORTERS: dict[str, Importer] = {
    "canary_ware": Importer(row=CanaryWareRow, natural_key=_natural_key, apply=_apply),
}
