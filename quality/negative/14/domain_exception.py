

from apps.core.exceptions import NotFound as _NegNotFound


def _neg_refuse():
    raise _NegNotFound()
