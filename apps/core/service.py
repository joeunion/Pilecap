"""`@service` — what makes a write in this repository a write.

House rule 13: **every function in a `services.py` carries this decorator.**
It is not a convenience wrapper; it is the enforcement point for four things
that are otherwise "remember to", and "remember to" is exactly what fails at 2am
in the eleventh service somebody wrote in a hurry:

1. **Keyword-only arguments**, checked *at import time*. A positional
   `create_widget(tenant, owner)` is a call site that silently swaps two
   arguments of the same type the day the signature changes. This raises
   `TypeError` when the module is imported, so the mistake cannot reach a test,
   let alone production.
2. **One transaction.** The body runs inside `transaction.atomic()`, so a
   service that touches three tables either did or did not.
3. **One span and two log lines.** `<app>.<service>` as an OTel span,
   `<app>.<service>.called` and `.failed` through `core.log`, with the door's
   bound context on both — so "which services did this request run, and which
   one was slow" is one query rather than a reading exercise. The redacted
   arguments ride under one key, `service_input` (see `INPUT_KEY`), so no
   parameter name can ever collide with structlog's own `event`.
4. **One audit row**, whenever the service *declares* a `tenant` (that is:
   whenever it writes something a tenant owns, **or something the deployment
   itself owns**). Written inside the transaction on success — atomic with the
   change it describes — and outside it on failure, because a rolled-back audit
   row is the record of the failure disappearing with the failure. Which
   services those are, and what `tenant=None` means in each: `_declares_tenant`,
   below.

**Redaction is by allow-list, not by blocklist.** An app declares
`LOG_KEYS: frozenset[str]` at the top of its `services.py`; anything not named
comes out as `[redacted]`. A blocklist ("hide `password`, `ssn`, …") is a list
somebody has to extend every time the product learns a new fact about a person,
and the day it is not extended is the day the field is in the logs forever.
The default allow-list is deliberately almost nothing: keys ending `_id`, plus
`name`.
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
from collections.abc import Callable
from contextvars import ContextVar
from functools import wraps
from typing import Any, cast, overload
from uuid import UUID

from django.db import models, transaction
from opentelemetry import trace

from apps.core import context
from apps.core.actor import Actor
from apps.core.exceptions import DomainError
from apps.core.log import REDACTED, get_logger
from apps.core.roads import road
from apps.core.surfaces import STAFF

log = get_logger("apps.core.service")

# What an app's `services.py` may log when it declares no `LOG_KEYS` of its own.
# Foreign keys and a display name: enough to find the row again, not enough to
# be a copy of it.
DEFAULT_LOG_KEYS: frozenset[str] = frozenset({"name"})

# The one key the redacted arguments are logged under.
#
# **Not spread flat across the log line, and this is not a style choice.** A
# `BoundLogger` method's own first parameter is called `event`, and structlog
# reserves `level` and `timestamp` for its processors; a service with a
# parameter of any of those names — `emit(*, name, ...)`'s sibling
# `record_event(*, event=...)`, a scheduler's `level`, anything — would spread
# into `log.info("x.called", event={...})` and raise `TypeError: got multiple
# values for argument 'event'` at the first call. Nesting makes the collision
# structurally impossible for *every* reserved name, present and future,
# instead of teaching each service to avoid three words. The line still carries
# everything it did: `service_input` is one JSON object in the sink, and
# `service_input.widget_id` is what a ClickStack query names.
INPUT_KEY = "service_input"


def _app_label(module: str) -> str:
    """`apps.example.services` -> `example`. The first half of a service's name."""
    parts = module.split(".")
    return parts[1] if len(parts) > 2 and parts[0] == "apps" else parts[0]


def _require_keyword_only(fn: Callable[..., Any]) -> None:
    """Refuse a positional parameter, at import time."""
    offenders = [
        parameter.name
        for parameter in inspect.signature(fn).parameters.values()
        if parameter.kind
        in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        )
    ]
    if offenders:
        raise TypeError(
            f"{fn.__module__}.{fn.__qualname__} takes positional arguments "
            f"({', '.join(offenders)}). A service is keyword-only: put a bare `*` "
            "before the first parameter. Two arguments of the same type in the "
            "wrong order is the bug this refuses."
        )


def _declares_tenant(fn: Callable[..., Any]) -> bool:
    """Whether this service is about a tenant's rows — read off its signature.

    **The audit population, and why it is the signature and not the call.**
    Until ADR core-8 the branch read `"tenant" in kwargs and tenant is not
    None`, which answered two questions at once and got the second one wrong: a
    service with nothing to do with tenancy (`create_user`, `create_tenant`
    itself) declares no `tenant` and is deliberately not
    audited here, but a service that *does* declare one and was handed None was
    silently dropped too — and those are precisely the deployment's own
    actions, the ones a compliance trail exists for.

    Reading the **declaration** separates the two cleanly. A service either says
    "I am about a tenant's rows" by taking the parameter, or it does not; what
    the parameter resolved to on one call decides *which population* the row
    joins, never *whether* there is a row. Presence in `kwargs` alone would have
    left `sync_workforce_identity_config(actor=...)` — which the ADR names as a
    member of the hole — unaudited, because its caller relies on the default.

    **The population, measured before the flip** (every `@service` in the tree
    whose `tenant` can arrive None, and what None means in each):

    * `accounts.erase_user` — `Tenant | None = None`. None is "erased by the
      deployment, not by a workspace": the nomad's path, and the one that closed the gap.
    * `accounts.issue_token` — `Tenant | None` (required). None is a token
      pinned to no workspace, which is a real product state, not an absence.
    * `accounts.revoke_token` — `Tenant | None` (required), since ADR core-22.
      The same value its mint was given, passed by both doors as `token.tenant`
      and refused by the service when it disagrees, so a credential's death row
      is always beside its birth row and never under another workspace.
    * `accounts.sync_workforce_identity_config` — `Tenant | None = None`. Always
      None in practice: the workforce Google door is the installation's, and
      belongs to no customer.
    * `workflows.record_run` / `workflows.finish_run` — `Tenant | None`
      (required). None is ADR workflows-3's declared platform run, the shape
      this ADR mirrors.

    Everything else in the tree either requires a `Tenant` (audited, tenanted,
    unchanged) or declares no `tenant` at all (`create_user`,
    `record_zitadel_identity`, `create_tenant`, `record_run_id` — unaudited
    before and unaudited now (a sweep declares `tenant: None`: rule 49); a service
    that never claims to be about a tenant's rows is not made into one by this).

    `deactivate_user` was on that list until it was given an `actor` and a
    `tenant`, which moved it into the audited population. **`revoke_token` left
    it at ADR core-22** (2026-08-26), and it left for the reason this paragraph
    warns about rather than by accident: the exemption rested on "not about a
    tenant's rows", which is false for a credential pinned to one, and the
    asymmetry it produced — a trail recording every token's birth and no
    token's death — stood undetected until somebody probed for the row and
    found none. The list is prose and nothing checks it, which is
    exactly how it went stale — a reader who finds a name wrong here should
    trust `inspect.signature` below, which is what actually decides.
    """
    return any(
        parameter.name == "tenant" and parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in inspect.signature(fn).parameters.values()
    )


def _allowed_keys(module_name: str) -> frozenset[str]:
    """The app's `LOG_KEYS`, or the default.

    A `services/` package's members share the package's keys, so the parent is asked second.
    """
    for name in (module_name, module_name.rpartition(".")[0]):
        declared = getattr(sys.modules.get(name), "LOG_KEYS", None)
        if isinstance(declared, (frozenset, set, tuple, list)):
            return frozenset(str(key) for key in declared)
    return DEFAULT_LOG_KEYS


def redact(values: dict[str, Any], allowed: frozenset[str]) -> dict[str, Any]:
    """The service's arguments, safe to store and to ship to the sink.

    A key survives if the app named it, or if it ends `_id` — an identifier is
    the thing that makes a row findable again and is the one class of value
    that is safe by construction. Model instances become their label and
    primary key, because dumping a whole row into the audit `input` would make
    the audit a second copy of the database.

    **A `models.Model` argument survives whatever its parameter is called**
    (ADR core-22), and the reason is that `_plain` renders
    it as `<app_label>.<Model>:<pk>` and nothing else: a primary key is not a
    secret, and the row's own columns are never present by construction, so
    there is nothing for the allow-list to protect. What the allow-list is for
    is *values* — an email address, a client secret, a subject — and a model
    instance is a reference, not a value.

    It matters on the failure path. `@service` writes an `outcome=error` row
    from the arguments alone (there is no return value to read), so before this
    a refused `revoke_token(token=…, …)` filed a row saying that a
    revocation was refused and never which credential — `token` is neither
    `_id`-suffixed nor in `accounts`' `LOG_KEYS`, so it came out `[redacted]`.
    AU-3's "identity of associated … objects"
    is answered by `object_type`/`object_id` on a successful call and by this
    on a refused one.
    """
    out: dict[str, Any] = {}
    for key, value in values.items():
        if isinstance(value, models.Model) or key.endswith("_id") or key in allowed:
            out[key] = _plain(value)
        else:
            out[key] = REDACTED
    return out


def _plain(value: Any) -> Any:
    """A JSON-safe rendering that never carries a whole row along."""
    if isinstance(value, models.Model):
        return f"{value._meta.label}:{value.pk}"
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


def trace_id() -> str:
    """The current span's trace as 32 hex characters, or `""` outside a span."""
    span_context = trace.get_current_span().get_span_context()
    return format(span_context.trace_id, "032x") if span_context.is_valid else ""


#: What a service declares on its result when the row it acted on cannot be the
#: return value itself. Either a `models.Model`, or a `(label, pk)` pair whose
#: `pk` may be `None` — the population shape a sweep files under (ADR core-22,
#: the L6 ruling): the swept model's label, no id, and the count in the payload.
AUDIT_OBJECT_ATTR = "audit_object"


def _declared_object(result: Any) -> tuple[str, UUID | None] | None:
    """The `audit_object` a result declares, or None if it declares nothing.

    **A blank label is a violation and is refused here**, loudly, rather than
    written. A row whose `object_type` is the empty string names nothing, which
    is the exact defect this convention closes; and the label at a declaration
    site is always a constant (`Delivery._meta.label`), so a blank one can only
    be a programming error a test will meet long before a deployment does. The
    same tier `core.exceptions.register_refusal` refuses a malformed refusal at
    import: a declaration that cannot mean anything is not stored and then
    puzzled over.
    """
    declared = getattr(result, AUDIT_OBJECT_ATTR, None)
    if declared is None:
        return None
    if isinstance(declared, models.Model):
        pk = declared.pk
        return declared._meta.label, pk if isinstance(pk, UUID) else None
    if isinstance(declared, tuple) and len(declared) == 2:
        label, pk = declared
        if not isinstance(label, str) or not label.strip():
            raise ValueError(
                f"{type(result).__name__}.{AUDIT_OBJECT_ATTR} declares a blank label. "
                "An audit row whose object_type is empty names nothing, which is the "
                "defect this declaration exists to close: give it the swept model's "
                "`_meta.label`."
            )
        return label, pk if isinstance(pk, UUID) else None
    raise ValueError(
        f"{type(result).__name__}.{AUDIT_OBJECT_ATTR} is neither a models.Model nor a "
        "(label, pk) pair. Those are the two shapes ADR core-22 declares, and there "
        "is no third."
    )


def _first_model(fields: Any) -> models.Model | None:
    """The first `models.Model` in an iterable of values, or None."""
    return next((item for item in fields if isinstance(item, models.Model)), None)


def _object_of(result: Any) -> tuple[str, UUID | None]:
    """What the service acted on, taken from what it returned.

    A service returns the object it wrote (house rule 13), so the return value
    is the honest answer and no caller has to declare it twice. **Three
    branches, tried in this order, and there is no fourth** (ADR core-22, the
    L7 ruling of 2026-08-26):

    1. **An explicit `audit_object` on the result** — a `models.Model`, or a
       `(label, pk)` pair for the case where there is no single row: a sweep
       files the swept model's label with a NULL id and its count in the
       payload, which is a population and says so. `_declared_object` refuses a
       blank label rather than writing one.
    2. **Otherwise the first `models.Model` in a tuple OR IN A DATACLASS.** A
       handful of services owe the caller something that is not a row and can
       never be re-derived — `accounts.issue_token` returns
       `(token, plaintext)` because the plaintext exists exactly once,
       `core.invite_member` returns `(invitation, secret)` for the same reason
       — and another handful return a small frozen dataclass because the answer
       genuinely has parts: `files.UploadTicket` (the document, the version and
       a signed URL that must never become a column), `comms.StepOutcome` (the
       message and how long the wall held it). Every one of those puts the row
       FIRST, so reading the first model covers all four with **zero edits to
       the types themselves**.
    3. **Otherwise nothing** — `("", None)`, which is what a service that
       genuinely acted on no row should record.

    **Reading an attribute off a result is NOT the shape core-22 rejected.**
    What was rejected was a *second return path* — reshaping a
    service's signature so the audit could find its row, which multiplies
    signatures across both doors' unpacking for one column. A declaration the
    seam reads changes no caller and no door: `UploadTicket`'s own docstring
    had already escalated exactly this ("teaching `core.service._object_of` to
    read a declared attribute off a non-model result… is `apps/core`'s
    decision"), and this is that decision.

    Only the top level is read, in every branch. A nested tuple is not
    searched, because a service whose row is buried two levels down in its
    return value has a shape problem this function must not paper over.
    """
    declared = _declared_object(result)
    if declared is not None:
        return declared
    if isinstance(result, tuple):
        result = _first_model(result)
    elif dataclasses.is_dataclass(result) and not isinstance(result, type):
        result = _first_model(getattr(result, field.name) for field in dataclasses.fields(result))
    if isinstance(result, models.Model):
        pk = result.pk
        return result._meta.label, pk if isinstance(pk, UUID) else None
    return "", None


def write_audit(
    *,
    action: str,
    tenant: Any,
    actor: Actor | None,
    payload: dict[str, Any],
    outcome: str,
    error_code: str = "",
    result: Any = None,
) -> None:
    """One row, or none.

    **Public for exactly one caller, and the reason is a chicken and an egg.**
    The wrapper below takes an audit row's tenant from the CALL — `kwargs
    ["tenant"]` — which is right for every service in the product except the one
    that *produces* the tenant its own row is about. `core.services
    .bootstrap_tenant` has no tenant to be handed: at the moment it is called
    there are none, and the row it owes is the new tenant's birth certificate
    (ADR core-17, ADO-5). Auditing it into the platform population instead was
    considered and rejected — the row is about a tenant that now exists.

    So that one service calls this directly rather than assembling a second
    audit row by hand, which would be a second copy of every field below and the
    place the two would drift.

    **Who** comes from the `actor` the service was given, and from nowhere
    else. The bound context has a `user_id` on it and it is deliberately not
    used for this: context is observability data — ambient, inherited, and
    occasionally stale — while an audit row is a claim about who did something.
    A service that was not told who is acting records that it was not told,
    which is the true answer. `door` and the correlation ids do come from the
    context, because those are exactly what context is for.
    """
    from apps.core.audit import AuditEntry

    object_type, object_id = _object_of(result)
    bound = context.get()
    kind = actor.kind if actor is not None else str(bound.get("actor_kind") or "system")
    AuditEntry(
        tenant=tenant,
        # The hat, from the actor and from nowhere else — the same reasoning
        # `actor_user` follows. The bound context carries an `org_id` too and it
        # is deliberately not used: context is ambient observability data, and
        # an audit row is a claim about who acted and as what.
        acting_org_id=actor.org_id if actor is not None else None,
        actor_user_id=actor.user_id if actor is not None else None,
        actor_token_id=actor.token_id if actor is not None else None,
        actor_kind=kind,
        action=action,
        object_type=object_type,
        object_id=object_id,
        door=str(bound.get("door") or ""),
        # The surface the door bound beside `door` — context, for `door`'s
        # reason: it is where the call came in, which is what context is for.
        surface=str(bound.get("surface") or STAFF),
        outcome=outcome,
        error_code=error_code,
        input=payload,
        request_id=str(bound.get("request_id") or ""),
        session_id=str(bound.get("session_id") or ""),
        correlation_id=str(bound.get("correlation_id") or ""),
        causation_id=str(bound.get("causation_id") or ""),
        trace_id=trace_id(),
    ).save()


#: Set while a service writes its row: a `witness=False` service it calls writes none (ADR core-29).
_WITNESSED: ContextVar[bool] = ContextVar("djb_service_witnessed", default=False)


@overload
def service[F: Callable[..., Any]](fn: F, /) -> F: ...


@overload
def service[F: Callable[..., Any]](*, witness: bool = True) -> Callable[[F], F]: ...


@road("audit", example="apps/example/services.py::create_widget")
def service(fn: Any = None, /, *, witness: bool = True) -> Any:
    """Wrap a write: its transaction, its audit row and its span (the module docstring says why).

    `witness=False` writes no row under a witnessing service: the door call's row is that one's.
    """
    if fn is None:
        return lambda target: _wrap(target, witness=witness)
    return _wrap(fn, witness=witness)


def _wrap[F: Callable[..., Any]](fn: F, *, witness: bool) -> F:
    """The `@service` wrapper itself; `witness` is read once, at decoration time (ADR core-29)."""
    _require_keyword_only(fn)

    action = f"{_app_label(fn.__module__)}.{fn.__name__}"
    tracer = trace.get_tracer(fn.__module__)
    # Read once, at decoration time, from the declaration rather than the call.
    # ADR core-8, and the reasoning is all in `_declares_tenant`.
    audited = _declares_tenant(fn)

    @wraps(fn)
    def call(*args: Any, **kwargs: Any) -> Any:
        if args:  # pragma: no cover - the signature already refuses this
            raise TypeError(f"{action} is keyword-only.")

        writes = audited and (witness or not _WITNESSED.get())
        allowed = _allowed_keys(fn.__module__)
        payload = redact(kwargs, allowed)
        tenant = kwargs.get("tenant")
        actor = kwargs.get("actor")
        actor = actor if isinstance(actor, Actor) else None

        with tracer.start_as_current_span(action) as span:
            session_id = context.value("session_id")
            if session_id:
                # ClickStack groups a session on this attribute, which is what
                # makes "replay what this person did" one query.
                span.set_attribute("session.id", str(session_id))
            span.set_attribute("service.action", action)

            log.info(f"{action}.called", **{INPUT_KEY: payload})
            token = _WITNESSED.set(True) if writes else None
            try:
                with transaction.atomic():
                    try:
                        result = fn(**kwargs)
                    finally:
                        if token is not None:
                            _WITNESSED.reset(token)
                    if writes:
                        write_audit(
                            action=action,
                            tenant=tenant,
                            actor=actor,
                            payload=payload,
                            outcome="ok",
                            result=result,
                        )
            except DomainError as exc:
                log.warning(
                    f"{action}.failed",
                    code=exc.code,
                    detail=exc.detail,
                    **{INPUT_KEY: payload},
                )
                span.set_attribute("service.error_code", exc.code)
                if writes:
                    write_audit(
                        action=action,
                        tenant=tenant,
                        actor=actor,
                        payload=payload,
                        outcome="error",
                        error_code=exc.code,
                    )
                raise
            except Exception as exc:
                log.exception(f"{action}.failed", code="unhandled")
                if writes:
                    write_audit(
                        action=action,
                        tenant=tenant,
                        actor=actor,
                        payload=payload,
                        outcome="error",
                        error_code=type(exc).__name__,
                    )
                raise
            return result

    call.__dict__["__witness__"] = witness
    return cast(F, call)
