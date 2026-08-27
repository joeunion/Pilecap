"""Who a workflow is running for, and how that survives the trip.

Temporal hands work between processes: a client starts a workflow, a worker
picks it up, an activity runs somewhere else again. `request.tenant` does not
survive any of those hops, so the tenant and the acting user travel as Temporal
**headers**, stamped by an outbound interceptor and unpacked by an inbound one
into the contextvars below.

**This module imports no Django.** It is loaded inside the workflow sandbox,
where importing the ORM would be both slow and wrong; the one function that
needs a model (`current_tenant`) imports it inside its own body, and only an
activity ever calls it.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from temporalio.api.common.v1 import Payload
from temporalio.client import Interceptor as ClientInterceptor
from temporalio.client import OutboundInterceptor, StartWorkflowInput
from temporalio.converter import default as default_converter
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    SignalChildWorkflowInput,
    SignalExternalWorkflowInput,
    StartActivityInput,
    StartChildWorkflowInput,
    StartLocalActivityInput,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
    WorkflowOutboundInterceptor,
)
from temporalio.worker import (
    Interceptor as WorkerInterceptor,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import Organization, Tenant

TENANT_HEADER = "djb-tenant-id"
ORG_HEADER = "djb-org-id"
USER_HEADER = "djb-user-id"
CORRELATION_HEADER = "djb-correlation-id"
CAUSATION_HEADER = "djb-causation-id"

_current_tenant_id: ContextVar[str | None] = ContextVar("djb_tenant_id", default=None)
_current_org_id: ContextVar[str | None] = ContextVar("djb_org_id", default=None)
_current_user_id: ContextVar[str | None] = ContextVar("djb_user_id", default=None)
_current_correlation_id: ContextVar[str | None] = ContextVar("djb_correlation_id", default=None)
_current_causation_id: ContextVar[str | None] = ContextVar("djb_causation_id", default=None)


@dataclass(frozen=True)
class WorkflowPrincipal:
    """Whose work this is, and which business chain it belongs to.

    The correlation pair rides along with the tenant because a workflow is
    exactly where a chain would otherwise break: the request that started it
    finished hours ago, and without these two ids the delivery a workflow makes
    tomorrow joins to nothing.
    """

    tenant_id: str | None
    user_id: str | None
    #: The acting hat, carried across the hop for the same reason the tenant is
    #: — a workflow that woke up a week later has no request to read it from,
    #: and an activity that guessed would write into the wrong branch.
    org_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None


def current_tenant_id() -> str | None:
    """The acting tenant's primary key, as a string. Safe inside a workflow."""
    return _current_tenant_id.get()


def current_org_id() -> str | None:
    """The acting organization's primary key, as a string. Safe in a workflow."""
    return _current_org_id.get()


def current_user_id() -> str | None:
    """The acting user's primary key, as a string. Safe inside a workflow."""
    return _current_user_id.get()


def current_correlation_id() -> str | None:
    """The business chain this work belongs to. Safe inside a workflow."""
    return _current_correlation_id.get()


def current_causation_id() -> str | None:
    """The immediate parent of this work. Safe inside a workflow."""
    return _current_causation_id.get()


def current_principal() -> WorkflowPrincipal:
    return WorkflowPrincipal(
        tenant_id=current_tenant_id(),
        user_id=current_user_id(),
        org_id=current_org_id(),
        correlation_id=current_correlation_id(),
        causation_id=current_causation_id(),
    )


def current_tenant() -> Tenant | None:
    """The acting tenant, as a row. **Activities only** — this reads the database."""
    from apps.core.models import Tenant

    tenant_id = current_tenant_id()
    if tenant_id is None:
        return None
    return Tenant.objects.filter(pk=tenant_id).first()


def current_org() -> Organization | None:
    """The acting organization, as a row. **Activities only** — this reads the database."""
    from apps.core.models import Organization

    org_id = current_org_id()
    if org_id is None:
        return None
    return Organization.objects.filter(pk=org_id).first()


def workflow_context() -> tuple[Tenant, str | None, Organization | None]:
    """The acting tenant, user id **and hat** for the work in hand. **Activities only.**

    The one accessor an activity needs:
    `tenant, user_id, org = workflow_context()`, then pass them to a service as
    keyword arguments. Nothing reads any of the three from a global and nothing
    takes them as activity arguments — they arrive on the workflow's Temporal
    headers and are unpacked by the interceptor below, which is what makes it
    impossible for a caller to write into somebody else's tenant, or as
    somebody else's branch, by passing the wrong id.

    The hat is the third element because it is the third question a networked
    product has to answer: whose data, whose part of it, and on whose behalf. An
    activity that restored the tenant but not the org would read the whole
    tenant, which is exactly the leak `visible_to` exists to close.

    **It raises rather than handing back `None`.** A missing tenant
    used to travel one more hop and become `for_tenant(None)` — which is empty,
    not refused — so an activity running for nobody read an empty table and
    every assertion after it passed. Empty-instead-of-refused is the one failure
    shape tenancy must never take, so the tenant is now a `Tenant` in the
    signature and a `RuntimeError` naming the header when it is absent.

    A caller that legitimately has no tenant uses `platform_context()`, which is
    the declared opt-out and not a synonym.

    It reads the database (for the `Tenant` and `Organization` rows), so it
    belongs in an activity and never inside a `workflows.py`. The id-only
    accessors above are the ones that are safe in workflow code.
    """
    tenant_id = current_tenant_id()
    if tenant_id is None:
        raise RuntimeError(
            f"This activity ran with no {TENANT_HEADER!r} header, so it acts for no tenant. "
            "A run started through apps.workflows.services always stamps one; a run that "
            "legitimately has none is the platform population (ADR workflows-3) and its "
            "activity reads platform_context() instead. Returning None here would become "
            "for_tenant(None), which is empty rather than refused."
        )
    tenant, user_id, org = platform_context()
    if tenant is None:
        raise RuntimeError(
            f"The {TENANT_HEADER!r} header names tenant {tenant_id!r}, and no such row exists. "
            "The run outlived its tenant; it is refused rather than run for nobody."
        )
    return tenant, user_id, org


def platform_context() -> tuple[Tenant | None, str | None, Organization | None]:
    """The same three values, for the population that legitimately has no tenant.

    **The declared opt-out from `workflow_context()`'s guard, and the only one.**
    `WorkflowRun` is the platform-wide run ledger and null is a declared
    population (ADR workflows-3): revoking the identity of a person who belongs
    to no tenant, syncing workforce identity, sweeping every population's dead
    runs. Those activities are not missing a tenant — they have none, and there
    is a difference between the two that a single accessor could not express.

    So this one may answer `None`, and a caller that uses it is making a claim
    about itself that a reader can check. `mark_run_finished` is the first
    member: it closes rows for both populations, so demanding a tenant would
    break the platform half of the very ledger this valve exists for.
    """
    return current_tenant(), current_user_id(), current_org()


def set_principal(
    *,
    tenant_id: str | None,
    user_id: str | None,
    org_id: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> tuple[Any, ...]:
    """Set the contextvars, returning the tokens that undo it."""
    return (
        _current_tenant_id.set(tenant_id),
        _current_user_id.set(user_id),
        _current_org_id.set(org_id),
        _current_correlation_id.set(correlation_id),
        _current_causation_id.set(causation_id),
    )


def reset_principal(tokens: tuple[Any, ...]) -> None:
    for var, token in zip(
        (
            _current_tenant_id,
            _current_user_id,
            _current_org_id,
            _current_correlation_id,
            _current_causation_id,
        ),
        tokens,
        strict=False,
    ):
        var.reset(token)


_HEADER_FOR = {
    TENANT_HEADER: current_tenant_id,
    ORG_HEADER: current_org_id,
    USER_HEADER: current_user_id,
    CORRELATION_HEADER: current_correlation_id,
    CAUSATION_HEADER: current_causation_id,
}


def _encode(headers: Mapping[str, Payload]) -> dict[str, Payload]:
    """Add the current principal to a set of outbound Temporal headers."""
    converter = default_converter().payload_converter
    stamped = dict(headers)
    for header, read in _HEADER_FOR.items():
        value = read()
        if value is not None:
            stamped[header] = converter.to_payload(value)
    return stamped


def _decode(headers: Mapping[str, Payload]) -> WorkflowPrincipal:
    converter = default_converter().payload_converter

    def read(header: str) -> str | None:
        payload = headers.get(header)
        return converter.from_payload(payload, str) if payload else None

    return WorkflowPrincipal(
        tenant_id=read(TENANT_HEADER),
        user_id=read(USER_HEADER),
        org_id=read(ORG_HEADER),
        correlation_id=read(CORRELATION_HEADER),
        causation_id=read(CAUSATION_HEADER),
    )


class _ClientOutbound(OutboundInterceptor):
    async def start_workflow(self, input: StartWorkflowInput) -> Any:
        input.headers = _encode(input.headers)
        return await super().start_workflow(input)


class _ActivityInbound(ActivityInboundInterceptor):
    """The workflow door: restores the principal, and binds the logging context.

    An activity is the only place in a workflow that touches the world, so it is
    the only place the observability context belongs. `apps.core.context` is
    imported inside the method rather than at module scope because this module
    is also loaded inside the workflow sandbox, where a Django-adjacent import
    is at best slow and at worst refused.
    """

    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        from apps.core import context as observability_context

        principal = _decode(input.headers)
        tokens = set_principal(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            org_id=principal.org_id,
            correlation_id=principal.correlation_id,
            causation_id=principal.causation_id,
        )
        previous = observability_context.get()
        observability_context.clear()
        observability_context.bind(
            request_id=observability_context.new_id(),
            correlation_id=principal.correlation_id,
            causation_id=principal.causation_id,
            tenant_id=principal.tenant_id,
            org_id=principal.org_id,
            user_id=principal.user_id,
            actor_kind="system",
            door="workflow",
        )
        try:
            return await super().execute_activity(input)
        finally:
            observability_context.clear()
            observability_context.bind(**previous)
            reset_principal(tokens)


class _WorkflowOutbound(WorkflowOutboundInterceptor):
    """Everything a workflow sends outwards carries the principal with it.

    **All five, not just the activities.** Previously only the two
    activity calls were stamped, so a child workflow and a signal to another
    workflow left with empty headers — and the receiving side did not fail, it
    restored `None` for the tenant, the hat and the correlation chain and read
    `for_tenant(None)`, which is empty rather than refused. A child that
    quietly sees nothing is the worst shape this bug can take, because every
    assertion downstream of it passes.

    Each override is the same two lines on purpose: the day a sixth outbound
    call appears in the SDK, the omission should be visible as a missing member
    of an obvious set rather than hidden in a clever loop.
    """

    def start_activity(self, input: StartActivityInput) -> Any:
        input.headers = _encode(input.headers)
        return super().start_activity(input)

    def start_local_activity(self, input: StartLocalActivityInput) -> Any:
        input.headers = _encode(input.headers)
        return super().start_local_activity(input)

    async def start_child_workflow(self, input: StartChildWorkflowInput) -> Any:
        input.headers = _encode(input.headers)
        return await super().start_child_workflow(input)

    async def signal_child_workflow(self, input: SignalChildWorkflowInput) -> None:
        input.headers = _encode(input.headers)
        return await super().signal_child_workflow(input)

    async def signal_external_workflow(self, input: SignalExternalWorkflowInput) -> None:
        input.headers = _encode(input.headers)
        return await super().signal_external_workflow(input)


class _WorkflowInbound(WorkflowInboundInterceptor):
    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        super().init(_WorkflowOutbound(outbound))

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        principal = _decode(input.headers)
        set_principal(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            org_id=principal.org_id,
            correlation_id=principal.correlation_id,
            causation_id=principal.causation_id,
        )
        return await super().execute_workflow(input)


class TenantContextInterceptor(ClientInterceptor, WorkerInterceptor):
    """One object, both sides: it stamps headers going out and unpacks them coming in."""

    def intercept_client(self, next: OutboundInterceptor) -> OutboundInterceptor:
        return _ClientOutbound(next)

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ActivityInbound(next)

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor]:
        return _WorkflowInbound
