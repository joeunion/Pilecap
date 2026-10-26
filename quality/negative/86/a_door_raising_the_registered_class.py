# The shape the rule asks for: the door raises the registered class and the one
# composer writes the body both doors send.
from apps.core.exceptions import Forbidden


def neg_door_registered_refusal() -> None:
    """Refuse through the registry."""
    raise Forbidden()
