"""Planted: the same thing on the third surface, which is canaried separately.

`prompts/get` is not `resources/read` — a different manager, a different
dispatch method, a different half of the specification — and a check that could
only ever demonstrate the two together would demonstrate neither. A product that
ships prompts before it ships resources must meet the same refusal.
"""

from typing import Any


def register(server: Any) -> None:
    @server.prompt(name="summarise_widget")
    def summarise_widget(widget_id: str) -> str:
        return f"Summarise widget {widget_id} for an operator."
