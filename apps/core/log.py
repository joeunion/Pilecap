"""The only logger.

House rule 19: every log line in this repository is structured and goes through
here. No `print`, no bare `logging.getLogger`, no f-string or `%` formatting in
a log call — because the destination is ClickStack over OTLP, and a line
assembled into prose is a line nobody can query.

    from apps.core.log import get_logger

    log = get_logger(__name__)
    log.info("example.widget.created", widget_id=str(widget.pk))

The event name is the first argument and it is a *name*, not a sentence:
`<app>.<noun>.<verb>`, stable across releases, the thing a dashboard groups by.
Everything else is a keyword — key/value pairs that survive as fields.

The bound context (`request_id`, `tenant_id`, `correlation_id`, `door`, …) and
the current `trace_id`/`span_id` are added by processors configured in
`core/observability.py`, so no caller passes them and no caller can forget.
"""

from __future__ import annotations

from typing import cast

import structlog

# What a redacted value is replaced with. An app's `LOG_KEYS` in its
# `services.py` is the allow-list; everything outside it comes out as this.
REDACTED = "[redacted]"


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """The logger for a module. `get_logger(__name__)`, always."""
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))
