

from ninja.errors import HttpError as _CanaryHttpError


def _canary_refuse():
    raise _CanaryHttpError(403, "planted")
