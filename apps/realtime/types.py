"""The socket door's stdlib-only shapes: the query-credential names and their log filter."""

from __future__ import annotations

import logging
import re

__all__ = [
    "CREDENTIAL_QUERY_PARAMS",
    "SOCKET_PATH_PREFIX",
    "TICKET_QUERY_PARAM",
    "TOKEN_QUERY_PARAM",
    "RedactSocketCredentials",
]

SOCKET_PATH_PREFIX = "/ws/"
TOKEN_QUERY_PARAM = "token"  # noqa: S105 — the refused query parameter's name, never a value
TICKET_QUERY_PARAM = "ticket"
CREDENTIAL_QUERY_PARAMS = (TOKEN_QUERY_PARAM, TICKET_QUERY_PARAM)
REDACTED = "[redacted]"

_CREDENTIAL = re.compile(r"(?P<lead>[?&](?:" + "|".join(CREDENTIAL_QUERY_PARAMS) + r")=)[^&\s\"]*")


class RedactSocketCredentials(logging.Filter):
    """Rewrite a `/ws/` line's `token=`/`ticket=` values to `[redacted]`; pass every other line."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Always keep the record; rewrite it when it is a socket line naming a credential."""
        message = record.getMessage()
        if SOCKET_PATH_PREFIX not in message:
            return True
        redacted = _CREDENTIAL.sub(lambda m: m.group("lead") + REDACTED, message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True
