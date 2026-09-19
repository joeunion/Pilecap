"""The valve, with a reason: a machine read that no person is behind.

Some reads genuinely have no actor to ask about — a pre-auth lookup on the way
to deciding who is asking, a provider's webhook resolving its own row, an
activity reading as the system. Clause (d) does not forbid them; it demands the
sentence, and counts every one on the rule's status line.
"""

from django.db.models import QuerySet

from .models import Gadget


def get_gadget_by_token_hash(*, token_hash: str) -> QuerySet[Gadget]:
    """A pre-auth lookup on the way to resolving an actor.

    # read-open: reached before anybody is authenticated — this read is how the
    # request's own credential is resolved, so there is no actor to ask about
    # yet and asking would be asking the caller to vouch for themselves.
    """
    return Gadget.objects.filter(token_hash=token_hash)
