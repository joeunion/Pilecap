# Planted: a REST door composing its own refusal body — a sentence and a
# status no registry holds, which the other door never says.
from ninja.errors import HttpError


def canary_door_literal_refusal() -> None:
    """Refuse with a body of the door's own."""
    raise HttpError(403, "nope")
