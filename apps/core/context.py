"""The ambient facts about the work in hand, bound once at the door.

Three questions have to be answerable from any row and any log line, days
later, across process restarts (`architecture.md`, "Traceability"):

* **which request** — `request_id`, and the OTel `trace_id`/`span_id` beside it;
* **which session** — `session_id`: a hashed Django session key, an MCP session
  id, a socket connection id; one query then reconstructs a session end to end;
* **which business chain** — `correlation_id` minted at the door and
  `causation_id`, the immediate parent, carried onto every `AuditEntry`,
  `Event`, `WorkflowRun` and outbound webhook.

Plus **`door`** (`rest | mcp | socket | workflow | webhook | admin | shell`),
because "the same service, called from the admin" is the question that keeps
coming up, and `tenant_id` / `org_id` (the acting hat — which part of the
tenant's tree this work is being done as) / `user_id` / `actor_kind`.

**Bound per door, never below one** (house rule 20). A service does not mint a
`correlation_id`: if it did, one business chain would get a fresh id at every
hop and the join key would join nothing. The doors that bind are
`core.middleware` (rest/admin), `config.mcp` (mcp), `core.asgi_middleware`
(socket), the Temporal interceptor (workflow) and `core.management.BaseCommand`
(shell).

The storage is `contextvars`, so it survives `await`, is per-task rather than
per-thread, and cannot leak between two requests being served concurrently.
`structlog`'s `merge_contextvars` processor is what puts these on every log
line, and `bind()` writes into structlog's own context so that one processor
does the whole job.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Literal

import structlog

Door = Literal["rest", "mcp", "socket", "workflow", "webhook", "admin", "shell"]

# The keys a door binds. Anything else a caller binds rides along too — this is
# the documented set, not a filter.
KEYS: tuple[str, ...] = (
    "request_id",
    "session_id",
    "tenant_id",
    "org_id",
    "user_id",
    "actor_kind",
    "correlation_id",
    "causation_id",
    "door",
)


def new_id() -> str:
    """A fresh opaque id for a request or a correlation chain."""
    return uuid.uuid4().hex


def new_correlation_id() -> str:
    """Mint a correlation id. **Called at a door and nowhere else.**

    House rule 20: a correlation id minted below a door would restart the chain
    it exists to join. A door either accepts the one it was handed
    (`X-Correlation-Id`, a Temporal header) or mints exactly one here.
    """
    return new_id()


def hash_session(raw: str | None) -> str | None:
    """The stored form of a session identifier.

    A Django session key is a bearer credential: anyone holding it is that
    user. It is exactly what you want on a log line for correlation and exactly
    what you must not put there in the clear, so what is bound is the SHA-256 —
    stable across a session, useless to whoever reads the logs.
    """
    if not raw:
        return None
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def bind(**values: Any) -> None:
    """Bind context for the current task. `None` values are dropped, not stored."""
    structlog.contextvars.bind_contextvars(**{k: v for k, v in values.items() if v is not None})


def unbind(*keys: str) -> None:
    """Remove specific keys from the current context."""
    structlog.contextvars.unbind_contextvars(*keys)


def get() -> dict[str, Any]:
    """Everything bound for the current task."""
    return dict(structlog.contextvars.get_contextvars())


def value(key: str) -> Any:
    """One bound value, or None."""
    return get().get(key)


def clear() -> None:
    """Drop the whole context. A door does this when its unit of work ends."""
    structlog.contextvars.clear_contextvars()


@contextmanager
def bound(**values: Any) -> Iterator[None]:
    """Bind for the duration of a block, then put back exactly what was there.

    Used by anything that runs one unit of work inside another — a management
    command, an activity, a test — where `clear()` would take the caller's
    context with it.
    """
    previous = get()
    bind(**values)
    try:
        yield
    finally:
        clear()
        bind(**previous)


def child_of_current() -> dict[str, Any]:
    """The correlation pair for work caused by the work in hand.

    The current `correlation_id` continues (that is the chain), and the current
    `correlation_id` becomes the new `causation_id` (that is the parent). This
    is what an outbound webhook header and a started workflow carry.
    """
    current = get()
    correlation_id = current.get("correlation_id") or new_correlation_id()
    return {"correlation_id": correlation_id, "causation_id": current.get("correlation_id")}


def from_headers(headers: Mapping[str, str]) -> dict[str, Any]:
    """The context a caller handed us, in the shape `bind()` takes.

    A missing request id is minted; a missing correlation id starts a new chain.
    Both are accepted from the caller so that a trace that began in another
    service stays one trace.
    """
    lowered = {str(k).lower(): v for k, v in headers.items()}
    return {
        "request_id": lowered.get("x-request-id") or new_id(),
        "correlation_id": lowered.get("x-correlation-id") or new_correlation_id(),
        "causation_id": lowered.get("x-causation-id"),
    }
