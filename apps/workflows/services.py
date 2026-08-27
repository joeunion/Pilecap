"""Writes for the workflows app, and the two ways a workflow is started.

**`start_workflow_on_commit` is the one a service calls.** It is synchronous,
because services are: a route, a management command and an admin action all run
on a thread with no event loop, and a service that demanded `await` would push
async up through every caller for no gain. It writes the visibility row inside
the caller's transaction and registers a `transaction.on_commit` hook that
starts the run — so a transaction that rolls back starts nothing, and a service
that is retried does not leave a workflow running for a row that never existed.
That on-commit hook is the only synchronous caller of the async client, and it
goes through `apps.core.asyncdb.run_async`, which gives the coroutine its own
event loop and refuses to run inside somebody else's.

`start_workflow` stays for callers that are already async — the worker itself,
another activity, and the workflow tests, which hold the test environment's
client and must use it rather than connecting to a dev server.

**Workflow ids are deterministic and required**, in the shape
`<tenant_slug>:<app>:<noun>:<key>` — or `platform:<app>:<noun>:<key>` for a run
the deployment owns rather than a tenant (ADR workflows-3; `check_workflow_id`
requires the reserved first segment **iff** `tenant is None`, so neither
population can wear the other's id). `workflow_id()` builds a tenant one and
**both** starters refuse anything else: `start_workflow`'s `id` lost its `uuid4`
default, because a random id would make a retried service start a second run of
the same work, which is the exact failure Temporal's id reuse policy exists to
prevent.

And because the id is deterministic, **asking for it twice is a retry, not a
collision** — provided it is asking for the *same work*. That proviso is
`input_digest`: a sha256 over the run's `arg` through Temporal's own payload
converter, computed **inside the starters** so that no caller can opt in or
out, and passed to `record_run`, whose answer is a 2x2 (ADR workflows-4). Its
docstring carries that contract in full.

**`signal_workflow` is the other half of the seam.** `start_workflow_on_commit`
is how a service says "begin"; this is how one says "the thing you were waiting
for has happened". Without it the only way to end a wait is the Temporal CLI —
which means the product cannot finish its own work, and the widget onboarding
in `apps/example` sat for a week waiting for a signal no door could send.

It puts up four walls, in this order, and each refuses something different:

1. **The id.** `check_workflow_id` refuses an id that is not the house shape or
   does not start with this tenant's slug, raising `ValueError` rather than a
   domain refusal for the same reason `start_workflow_on_commit` does: no door
   hands this id in from a client. A calling service builds it with
   `workflow_id()` from a row it has already read, so a wrong one is a bug in
   the caller and not an answer owed to anybody.
2. **The tenant.** The row is read through `for_tenant`, and a run this tenant
   does not own is `NotFound` — the same answer as one that never existed,
   because a refusal that distinguished them would say that somebody else's run
   exists.
3. **The membership.** `require(actor, "workflow.signal", run)`. What that can
   and cannot decide is `policies.py`'s subject; the short version is that
   object-level authorization belongs to the domain service in front of this
   one, because `WorkflowRun` does not know what the run is about.
4. **Liveness.** A run that has already finished is `Conflict`, not a silently
   dropped signal. Temporal would answer a signal to a completed execution with
   an RPC error inside an `on_commit` hook nobody is watching; the row already
   knows, so the caller is told now.

The signal itself goes out on `transaction.on_commit`, exactly as a start does:
a caller whose transaction rolls back has not approved anything, and a signal is
not something you can take back. Signals are **idempotent from this layer's
point of view** — a workflow that sets a flag twice is in the state it was in
after the first — so a retried caller is safe, which is why sending the same
signal twice while a run is still going is an `ok` and not a refusal.

It is a `@service` because it is a decision about somebody's tenant that has to
be authorized and audited, even though the only row it touches it touches for
reading.

**`start_replay` is the third half of the seam** (ADR workflows-6). `start` says
begin, `signal` says the thing you waited for happened, and this one says *do
that again* — a Temporal **reset** of a FAILED run back to its first workflow
task, so the server re-executes the input its own history already witnessed.

The input is never re-supplied by a client, and could not be: the row is the
thing that knows, and re-invoking the origin door would ask a caller to
remember an argument they may never have held. What makes a reset legal at all
is house rule 9 — workflow code that is deterministic replays identically —
and what makes it *safe* is the idempotency contract behind it, because a reset re-runs
the activities and therefore re-does their side effects.

It is called `start_replay` and not `replay_run` for one reason, said here
rather than left as a puzzle: **`replay` is not a verb in house rule 16's
declared lexicon**, that list lives in `quality/rules.yaml`, and editing
anything under `quality/` is out of scope here. Starting a replay
is a start, so the honest name inside the lexicon is the one it wears; the MCP
tool and the route are `replay_run` / `run-replay`, which is rule 17's naming
and not rule 16's. The delta needed is one line — `replay` in
`service_verbs` — and the rename is one commit the day it lands.

It puts up walls in this order, and the order is the refusal grammar:

1. **The tenant.** The row is read through `for_tenant`; another tenant's run
   is `NotFound`.
2. **The membership.** `require(actor, "workflowrun.replay", run)`.
3. **Whose run it is.** A run this actor did not start is `NotFound` — the
   *same* answer as one that does not exist, on purpose: a `Forbidden`
   here would confirm that somebody else in the tenant has a run under that id.
   A row with no recorded starter (`started_by IS NULL` — written before the
   column existed, or a platform run) is nobody's own run and answers the same.
4. **The state.** RUNNING is a `Conflict` (it has not failed yet), COMPLETED is
   a `Conflict` in `record_run`'s own words — re-running completed work is a
   new key, not a retry — and FAILED proceeds.
5. **The history.** A reset needs history to reset *to*, and Temporal's
   namespace retention deletes it on a clock nothing in this row can see. A run
   older than `HISTORY_RETENTION` is a `Conflict` that says so, decided from the
   row's own `started_at` rather than from an RPC, so no door waits on the
   network to be refused.

Then the row goes back to RUNNING inside the caller's transaction and the reset
itself goes out on `transaction.on_commit(..., robust=True)` — the
`signal_workflow` shape exactly, and for the same two reasons: a caller whose
transaction rolled back has not asked for anything, and an unreachable Temporal
must not take the hooks queued behind it down with it.

**`cancel_run` is the fourth** (ADR workflows-7), and it is the one that writes
nothing. `start` says begin, `signal` says the thing you waited for happened,
`start_replay` says do that again — and this one says *stop*. It puts up
`start_replay`'s first four walls in `start_replay`'s order, refuses a run that
is not RUNNING with a `Conflict` naming the status, and then registers the
Temporal cancel on commit and hands back the row **untouched**.

The untouched part is the decision. A cancellation is a request and not an
outcome: the execution stops when Temporal says so, the workflow gets to run
its cleanup, and the row closes as `cancelled` only when somebody witnessed it
— the finish seam from inside the cancelled workflow, or the reconciler reading
`CANCELED` off the server for a run that never got that far. A service that
stamped the row on the way past would have the ledger asserting an outcome
because somebody asked for one, which is the failure mode this whole table
exists to not have.

The three row-writing functions carry `@service`. The two `start_*` do not, and
for a reason worth stating: `start_workflow` is `async`, and `@service` opens a
synchronous transaction; `start_workflow_on_commit` is an orchestrator whose
only write is `record_run`, which is audited. Wrapping it too would write a
second audit row for the same fact.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.db import transaction
from django.utils import timezone
from temporalio.client import Client
from temporalio.converter import default as default_converter
from temporalio.exceptions import WorkflowAlreadyStartedError

from apps.core import context
from apps.core.actor import Actor
from apps.core.asyncdb import run_async, run_db
from apps.core.authz import require
from apps.core.exceptions import Conflict, NotFound, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.service import service
from apps.workflows.context import reset_principal, set_principal
from apps.workflows.models import WorkflowRun

log = get_logger(__name__)

ID_SEPARATOR = ":"
ID_SEGMENTS = 4

# The reserved first segment of a run the **deployment** owns rather than a
# tenant (ADR workflows-3). `create_tenant` refuses this slug, so no tenant can
# ever mint an id that collides with the platform's.
PLATFORM_SEGMENT = "platform"

# What may appear un-redacted in this app's log lines and audit `input`. A
# workflow id, type and signal name are structural, not personal — and they are
# the things you search on when a run has gone missing. The `arg` a signal
# carries is not on the list: it is the caller's payload and could be anything.
LOG_KEYS: frozenset[str] = frozenset({"workflow_id", "workflow_type", "status", "error", "signal"})

# The action `signal_workflow` authorizes. `policies.py` answers it; see the
# note there about which half of the question this layer can actually answer.
SIGNAL_ACTION = "workflow.signal"

# The two actions the run ledger's own doors authorize (ADR workflows-6). Read
# is tenant-wide and replay is not — the narrowing that makes replay the
# actor's own is `started_by`, checked in the service and not in the policy,
# because a policy that reached for the acting user would be answering a
# question about the ROW rather than about the person's standing.
READ_ACTION = "workflowrun.read"
REPLAY_ACTION = "workflowrun.replay"

# And the third (ADR workflows-7). Narrowed to the actor's own by `started_by`
# in `cancel_run`, for exactly the reason replay is: the policy is handed the
# row and could compare it, but `require` raises `Forbidden` and a `Forbidden`
# on somebody else's run confirms the run exists.
CANCEL_ACTION = "workflowrun.cancel"

# How far back a run can still be replayed. **Temporal's default namespace
# retention**, and a reset needs history to reset to: past this, the events the
# server would re-execute have been deleted and the RPC would fail somewhere no
# door is listening. Deciding it from `started_at` is what lets the refusal be
# a `Conflict` at the door rather than a hook's log line an hour later.
#
# A module constant rather than a setting, deliberately and with a trigger: a
# deployment whose namespace retention differs from the CLI dev server's and
# the Temporal Cloud default is the day this becomes configuration, and it will
# want `.env.example` and `config/settings/base.py` — both of which are outside
# this module's territory (apps/workflows/**), so shipping a settings read here
# would have shipped a variable nobody declared.
HISTORY_RETENTION = timedelta(days=30)


def workflow_id(*, tenant: Tenant, app: str, noun: str, key: str) -> str:
    """Build a workflow id in the house shape: `<tenant_slug>:<app>:<noun>:<key>`.

    Four segments, in widening order of specificity, so a human reading the
    Temporal UI can tell whose work a run is, which app owns it and what it is
    about, without decoding anything — and so a prefix search finds every run
    for a tenant. `key` is whatever makes the run unique and *repeatable*: a
    row's primary key, an invoice number, a date. Never a random value.
    """
    parts = {"tenant.slug": tenant.slug, "app": app, "noun": noun, "key": key}
    for name, part in parts.items():
        text = str(part).strip()
        if not text or ID_SEPARATOR in text:
            raise ValueError(
                f"A workflow id segment must be non-empty and contain no "
                f"{ID_SEPARATOR!r}; {name} was {part!r}."
            )
    return ID_SEPARATOR.join(str(part).strip() for part in parts.values())


def check_workflow_id(*, id: str, tenant: Tenant | None) -> str:
    """Refuse a workflow id that is not the house shape, for this population.

    Two populations, one fence: a tenant's run starts with that tenant's slug,
    and a **platform** run — one the deployment owns, started with
    `tenant=None` — starts with `PLATFORM_SEGMENT`. The requirement runs both
    ways, which is the half that makes null a declared population rather than
    a loosening: a tenant may not borrow `platform:`, and a platform run may
    not wear a tenant-slug-shaped id.
    """
    segments = id.split(ID_SEPARATOR)
    if len(segments) != ID_SEGMENTS or not all(segment.strip() for segment in segments):
        raise ValueError(
            f"A workflow id is <tenant_slug>{ID_SEPARATOR}<app>{ID_SEPARATOR}<noun>"
            f"{ID_SEPARATOR}<key>; got {id!r}. Build one with workflow_id()."
        )
    wanted = tenant.slug if tenant is not None else PLATFORM_SEGMENT
    if segments[0] != wanted:
        whose = f"tenant {tenant.slug!r}" if tenant is not None else "a platform run"
        raise ValueError(f"A workflow id starts with {wanted!r} for {whose}; got {segments[0]!r}.")
    return id


def hash_run_input(arg: Any) -> str:
    """A sha256 hex digest of what a run would actually carry. **The starters' job.**

    Serialised through **Temporal's own default payload converter**, so the
    bytes hashed are the bytes the run would be started with: two `arg`s that
    Temporal cannot tell apart hash the same, and two it can, do not. Hashing a
    `repr` or a `dict` would have been a second, subtly different notion of
    "the same work".

    The metadata is folded in sorted, and the data after it, so a protobuf map
    whose iteration order is not guaranteed cannot move the digest.

    Callers never call this. It is invoked inside `start_workflow` and
    `start_workflow_on_commit` for **every** run, because a digest a caller had
    to opt into would be a grammar shipped as an optional parameter — and the
    callers that forgot would be exactly the ones that needed it.
    """
    payload = default_converter().payload_converter.to_payload(arg)
    digest = hashlib.sha256()
    for key in sorted(payload.metadata):
        digest.update(key.encode())
        digest.update(b"\x00")
        digest.update(payload.metadata[key])
        digest.update(b"\x00")
    digest.update(payload.data)
    return digest.hexdigest()


def _run_under(*, tenant: Tenant | None, workflow_id: str) -> WorkflowRun | None:
    """The one row a population holds under this id — a tenant's, or the platform's.

    **Never `for_tenant(None)`.** That call means "an unresolved tenant" and
    keeps answering with nothing, which is what makes every tenant door blind
    to the platform's runs by construction. Asking for the platform's runs is a
    different question, and this is the one place in the app that asks it.
    """
    if tenant is None:
        # rule-8: the platform population is the declared null-tenant one (ADR
        # workflows-3); for_tenant stays fail-closed and can never reach it.
        return WorkflowRun.objects.for_platform().filter(workflow_id=workflow_id).first()
    return WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=workflow_id).first()


def check_org_agreement(*, tenant: Tenant | None, org: Organization | None) -> None:
    """Refuse a hat that does not belong to the tenant the run is for.

    `ValueError` at the caller-bug tier, the same tier and for the same reason
    as `check_workflow_id`: no door hands these in. A service resolved the
    tenant from the request and the hat from `X-Org`, both from rows, so a pair
    that disagrees is a bug in the code between them — and the cost of not
    saying so here is an activity acting under a cross-tenant hat, stamped by
    the very seam that exists to prevent it.
    """
    if org is None:
        return
    if tenant is None:
        raise ValueError(
            f"A platform run acts for no tenant and so wears no hat; got org {org.slug!r}."
        )
    if org.tenant_id != tenant.pk:
        raise ValueError(
            f"The acting organization {org.slug!r} belongs to another tenant than "
            f"{tenant.slug!r}; a run cannot be started under a hat its tenant does not own."
        )


def _reopen(
    run: WorkflowRun,
    *,
    workflow_type: str,
    input_digest: str,
    user: AbstractBaseUser | None,
) -> WorkflowRun:
    """The fourth quadrant: a finished row asked for again, with different work.

    The row re-opens — RUNNING, the new type and digest, `run_id`,
    `finished_at` and `error` cleared, a fresh `started_at` — and Temporal's
    default id-reuse policy then starts a new execution under the same id.

    Without this, the first completed run of a deterministic key would fossilise
    that key forever, which is exactly the interlock ADR workflows-5 creates: an
    organization whose move workflow now closes its own row could never be moved
    a second time. The row is visibility, not an append-only ledger — it
    declares no `append_only` — so supersession is its honest lifecycle rather
    than a rewrite of history.

    **`started_by` moves with it** (ADR workflows-6). The row now describes
    somebody else's job under a key the first person's job has finished with, so
    leaving the old starter on it would make the ledger answer "your run" about
    work that is not yours — and would hand that person a replay door onto it.
    The supersession is the moment ownership changes, exactly as `started_at`
    is the moment the clock restarts.

    Not a `@service` of its own: it is one branch of `record_run`, and a second
    audit row for one decision would say a thing that did not happen.
    """
    run.type = workflow_type
    run.status = WorkflowRun.Status.RUNNING
    run.input_digest = input_digest
    run.run_id = ""
    run.error = ""
    run.finished_at = None
    run.started_at = timezone.now()
    run.started_by = user  # type: ignore[assignment]  # AUTH_USER_MODEL is not typed here
    run.save(
        update_fields=[
            "type",
            "status",
            "input_digest",
            "run_id",
            "error",
            "finished_at",
            "started_at",
            "started_by",
            "updated_at",
        ]
    )
    return run


# door: the ledger's own write seam, and giving it a door would be the bug. A
# caller that could ask for a WorkflowRun row could mint visibility for a run
# nobody started, or claim an id a real start then collides with; the row exists
# to describe what the starters did, so the starters are the only callers.
# Reachable from every door in the tree through them (rule 42 counts direct
# calls, and that is the finding it is designed to make, not one here).
@service
def record_run(
    *,
    tenant: Tenant | None,
    workflow_id: str,
    workflow_type: str,
    input_digest: str = "",
    user: AbstractBaseUser | None = None,
) -> WorkflowRun:
    """Write the visibility row for a run that is about to be started.

    **Asking for the same id twice is not a refusal — asking for different work
    under it is.** A deterministic id exists so that a retried service asks for
    the *same* run rather than a second one, and until this returned the row it
    already had, the ordinary shape of a retry — a client that resent, a queue
    that redelivered, a person who clicked twice — was answered with `Invalid`
    off the per-tenant unique constraint. But "the same id" is not "the same
    job", and answering a caller who changed the work with somebody else's run
    dropped their intent in silence.

    So the row this population already holds under that id decides, over two
    questions — is it live, and is it the same work — and there are exactly
    four answers (ADR workflows-4):

    * **running, and the same type and digest** — that row is returned,
      unchanged, and the caller goes on to start the run it describes. The
      start is *attempted* rather than skipped: `_start_recorded` swallows
      Temporal's `WorkflowAlreadyStartedError`, so asking again is a no-op when
      the run is really there and a **heal** when it is not — a row whose
      process died between the commit and the client call gets its execution on
      the second ask instead of waiting forever for one nobody started.
    * **running, and a different type or digest** — `Conflict`. The id is live
      and this is a second job wearing it; handing back the wrong run, or
      quietly discarding the new intent, is worse than refusing.
    * **already finished, and the same digest** — `Conflict`. Re-running
      completed work is a decision about a new key, and this layer will not
      make it silently.
    * **already finished, and a different digest** — **supersede**: `_reopen`,
      below, which carries that quadrant's reasoning.

    **An empty digest is unknown, never a mismatch.** Rows written before the
    column existed hold `""` and pass every comparison, because a backfill
    nobody can compute would be a guess wearing the authority of a fact. New
    starts always compute one, so the population converges forward.

    `user` is **who asked** — the same user both starters already thread onto
    the workflow's headers and memo, threaded one place further so the row can
    answer it too (ADR workflows-6). It is a parameter of this function and
    never of a door: a caller that could name a starter could hand themselves
    somebody else's replay right. `None` is unknown and stays unknown, the
    `input_digest` convergence pattern verbatim.
    """
    existing = _run_under(tenant=tenant, workflow_id=workflow_id)
    if existing is not None:
        # Unknown on either side is not a mismatch: see the docstring.
        same_work = (
            not input_digest or not existing.input_digest or existing.input_digest == input_digest
        )
        if existing.status == WorkflowRun.Status.RUNNING:
            if existing.type != workflow_type:
                raise Conflict(f"That id is already running {existing.type}, not {workflow_type}.")
            if not same_work:
                raise Conflict(
                    f"A {existing.type} job with that id is already running and was given "
                    "different input. That is a second job: give it its own id."
                )
            return existing
        if same_work:
            raise Conflict(
                f"A {existing.type} job with that id has already {existing.status}. "
                "Running the same work again is a new job, not a repeat of that one."
            )
        return _reopen(existing, workflow_type=workflow_type, input_digest=input_digest, user=user)
    run = WorkflowRun(
        tenant=tenant,
        workflow_id=workflow_id,
        type=workflow_type,
        status=WorkflowRun.Status.RUNNING,
        started_at=timezone.now(),
        input_digest=input_digest,
        # `Actor.user` and both starters carry the base class every user model
        # derives from; the column is the concrete one. The narrowing is real
        # at runtime and unprovable here, which is what the ignore says.
        started_by=user,  # type: ignore[misc]  # AbstractBaseUser vs the swapped model
    )
    with as_invalid():
        # The row was just read and was not there, so the uniqueness question is
        # already answered for everything but a true race — and a race is the
        # database's to arbitrate: the loser gets an `IntegrityError` off the
        # constraint, which the door answers 409, rather than the `Invalid` this
        # function has stopped giving a duplicate start.
        run.full_clean(validate_unique=False)
    run.save()
    return run


# door: there is nothing here for anybody to ask for. This attaches an
# identifier the TEMPORAL SERVER assigned, and the only callers that can hold
# one are the two places that made the call that returned it (`_start_recorded`
# and the reset hook below). A door onto it would be a door onto writing an
# execution id nobody executed.
@service
def record_run_id(*, run: WorkflowRun, run_id: str) -> WorkflowRun:
    """Attach Temporal's run id once the server has assigned one."""
    run.run_id = run_id
    run.save(update_fields=["run_id", "updated_at"])
    return run


@service
def finish_run(
    *,
    tenant: Tenant | None,
    workflow_id: str,
    status: str,
    error: str = "",
) -> WorkflowRun | None:
    """Close out a run. Reads through the scoped manager like every other read.

    `tenant=None` is the **platform** population (ADR workflows-3), read through
    `for_platform()` — not `for_tenant(None)`, which means "unresolved" and
    keeps answering with nothing.
    """
    run = _run_under(tenant=tenant, workflow_id=workflow_id)
    if run is None:
        return None
    run.status = status
    run.error = error
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error", "finished_at", "updated_at"])
    return run


# door: signals stay behind the DOMAIN service that owns the wait
# (ADR workflows-6: the read door and replay ship; signal
# and retry stay operator-only). `policies.py` says why in full: this layer can
# see a tenant and an id and cannot see what the run is about, so "may this
# person end that wait" is only answerable one layer up, where the row is.
# `example.approve_widget` is that layer, and it has a door; a `runs.signal`
# tool would let an agent end any wait in the tenant with no domain check in
# front of it.
@service
def signal_workflow(
    *,
    tenant: Tenant,
    actor: Actor,
    workflow_id: str,
    signal: str,
    arg: Any = None,
) -> WorkflowRun:
    """Deliver a signal to a running workflow. **The other half of the seam.**

    Four walls, then the send: the id (`ValueError` — a caller bug, never a
    client's input), the tenant (`NotFound`, with no existence oracle), the
    membership (`Forbidden`, via `policies.py`) and liveness (`Conflict` on a
    run that has already finished). Why each one is shaped that way, and why
    signalling twice is an `ok` rather than a refusal, is in the module
    docstring above.

    `workflow_id` shadows the module-level function of the same name inside this
    body, deliberately: it is the parameter's honest name at every call site,
    and this function has no reason to build an id — it is given one.
    """
    check_workflow_id(id=workflow_id, tenant=tenant)
    run = WorkflowRun.objects.for_tenant(tenant).filter(workflow_id=workflow_id).first()
    if run is None:
        raise NotFound()
    require(actor, SIGNAL_ACTION, run)
    if run.status != WorkflowRun.Status.RUNNING:
        raise Conflict(f"That run is {run.status} and can no longer be signalled.")

    def _dispatch() -> None:
        async def _go() -> None:
            from apps.workflows.client import get_client

            client = await get_client()
            handle = client.get_workflow_handle(workflow_id)
            if arg is None:
                await handle.signal(signal)
            else:
                await handle.signal(signal, arg)

        run_async(_go)

    # `robust=True`: Django runs a transaction's hooks in order and a hook that
    # raises takes every hook behind it down with it. This one talks to
    # Temporal, which is the least reliable thing in any such list — an
    # unreachable server used to cancel the invitation email registered after
    # it. The failure is now contained to the hook that had it, logged by
    # Django, and swept by the reconciler that reads the row this signal was
    # about. (The survey shows these two lines are
    # the only production `on_commit` registrations in the tree.)
    transaction.on_commit(_dispatch, robust=True)
    return run


async def _reset_point(handle: Any) -> int:
    """The event id a reset to the **first workflow task** finishes at.

    Temporal resets to the event that *completed* a workflow task, so "run it
    again from the beginning" is the first `WorkflowTaskCompleted` in the
    history — everything the workflow decided after it is discarded and
    re-decided. The SDK ships no helper for it (the CLI computes the same thing
    for `--type FirstWorkflowTask`), so it is computed here off the history the
    server already holds, and the events are walked lazily so a long history
    costs the first page and no more.

    A history with no completed workflow task at all is a run that never got as
    far as a decision. There is nothing to reset it to, and saying so is better
    than guessing at event 3 and having the server refuse in a hook nobody
    reads.
    """
    from temporalio.api.enums.v1 import EventType

    async for event in handle.fetch_history_events():
        if event.event_type == EventType.EVENT_TYPE_WORKFLOW_TASK_COMPLETED:
            return int(event.event_id)
    raise RuntimeError(
        f"{handle.id} has no completed workflow task in its history, so there is "
        "no first workflow task to reset to."
    )


def _refuse_unless_replayable(run: WorkflowRun) -> None:
    """Walls four and five of `start_replay`: **is this row in a state to replay?**

    Split out of `start_replay` when a fourth state was added (ADR
    workflows-7) and the ceiling in `quality/budgets.yaml` said so. It is a
    coherent unit rather than a slice taken to fit a number: walls one to three
    are about *who is asking* and read the actor, and these two are about *what
    the row says* and never look at one. Each has its own sentence because each
    is a different fact, and a caller who branches on `conflict` reads which:

    * **RUNNING** — it has not failed yet; there is nothing to replay.
    * **CANCELLED** — somebody stopped it on purpose, and a deliberate stop is
      not a failure. Its own branch rather than the COMPLETED sentence, which is
      about work that SUCCEEDED and would read here as a mistake.
    * **COMPLETED** (and any state not FAILED) — re-running finished work is a
      new job under a new key, which is `record_run`'s own words.
    * **too old** — a reset needs history to reset *to*, and Temporal's
      namespace retention deletes it on a clock nothing in this row can see.
      Decided from the row's own `started_at` rather than an RPC, so the refusal
      arrives at the door instead of inside a hook nobody is watching.
    """
    if run.status == WorkflowRun.Status.RUNNING:
        raise Conflict("That run is still running; there is nothing to replay yet.")
    if run.status == WorkflowRun.Status.CANCELLED:
        raise Conflict(
            f"That job was {run.status} on purpose, and a deliberate stop is not a "
            "failure — there is nothing to restart. Start the work again where it "
            "was started before."
        )
    if run.status != WorkflowRun.Status.FAILED:
        raise Conflict(
            f"That job has already {run.status}. Running the same work again is a new "
            "job, not a repeat of that one — start it where it was started before."
        )
    if run.started_at < timezone.now() - HISTORY_RETENTION:
        raise Conflict(
            f"That job started more than {HISTORY_RETENTION.days} days ago and the "
            "record of what it was asked to do is no longer kept, so it cannot be "
            "restarted. Start the work again where it was started before."
        )


@service
def start_replay(*, tenant: Tenant, actor: Actor, run_id: UUID) -> WorkflowRun:
    """Run a failed run again, from its first workflow task. **The actor's own.**

    A **Temporal reset**, not a second start: the server re-executes the input
    its own history already witnessed, under the same deterministic id (rule
    18), so nobody has to remember or re-supply an argument a door may never
    have held. Rule 9's determinism is what makes that legal at all, and the
    idempotency contract is what makes it safe — a reset re-runs the activities,
    so everything the failed run had already done happens again.

    **The five walls, in the order below, are the module docstring's subject**
    and are not repeated here — walls four and five stand in
    `_refuse_unless_replayable`, which says which states may replay and why. The
    one worth having twice: not-this-tenant's and not-yours are the *same*
    `NotFound`, because a refusal that told them apart would confirm that
    somebody else has a run under that id.

    ---

    The row goes back to RUNNING inside the caller's transaction and the reset
    goes out on `transaction.on_commit(..., robust=True)`, exactly as a start
    and a signal do. Temporal's new execution id comes back from the RPC and is
    written by `record_run_id` — the same seam `_start_recorded` uses, which is
    why that function has no door of its own and does not want one.

    `request_id` on the reset is derived from the row and the execution it is
    replacing rather than minted at random, so a hook that runs twice — a
    retried caller, a redelivered ask — asks the server for the *same* reset
    instead of a second one.
    """
    # Locked, because everything below is a read-modify-write on one row: two
    # replays arriving together would both read FAILED and both ask Temporal to
    # reset one execution. Serialised, the loser meets the RUNNING branch below.
    run = WorkflowRun.objects.for_tenant(tenant).select_for_update().filter(pk=run_id).first()
    if run is None:
        raise NotFound()
    require(actor, REPLAY_ACTION, run)
    if run.started_by_id is None or run.started_by_id != actor.user_id:
        raise NotFound()
    _refuse_unless_replayable(run)

    # Captured before the row is reopened: the hook has to name the execution it
    # is replacing, and the row is about to stop holding it.
    workflow_id = run.workflow_id
    failed_run_id = run.run_id
    request_id = f"replay:{run.pk}:{failed_run_id}"

    run.status = WorkflowRun.Status.RUNNING
    run.error = ""
    run.finished_at = None
    run.run_id = ""
    run.save(update_fields=["status", "error", "finished_at", "run_id", "updated_at"])

    def _dispatch() -> None:
        async def _go() -> None:
            from django.conf import settings
            from temporalio.api.common.v1 import WorkflowExecution
            from temporalio.api.workflowservice.v1 import ResetWorkflowExecutionRequest

            from apps.workflows.client import get_client

            client = await get_client()
            handle = client.get_workflow_handle(workflow_id, run_id=failed_run_id or None)
            response = await client.workflow_service.reset_workflow_execution(
                ResetWorkflowExecutionRequest(
                    namespace=str(settings.TEMPORAL_NAMESPACE),
                    workflow_execution=WorkflowExecution(
                        workflow_id=workflow_id, run_id=failed_run_id
                    ),
                    reason=f"replay requested through the run ledger ({request_id})",
                    workflow_task_finish_event_id=await _reset_point(handle),
                    request_id=request_id,
                )
            )
            log.info("workflow.replay.reset", workflow_id=workflow_id, status="running")
            await run_db(record_run_id, run=run, run_id=response.run_id)

        run_async(_go)

    # `robust=True` — the same reasoning as `signal_workflow`'s hook above, and
    # the row is already committed as RUNNING, so a reset that could not be
    # dispatched is swept by the reconciler that reads it rather than lost.
    transaction.on_commit(_dispatch, robust=True)
    return run


@service
def cancel_run(*, tenant: Tenant, actor: Actor, run_id: UUID) -> WorkflowRun:
    """Ask a running job to stop. **The actor's own, and it stamps nothing.**

    The four walls are `start_replay`'s, in the same order and with the same
    answers — tenant (`NotFound`), membership (`Forbidden`, through
    `policies.py`), ownership (`NotFound`, never `Forbidden`, because a refusal
    that told not-yours from not-there would confirm the run exists) and state
    (`Conflict` naming the status). What is different is the fifth thing replay
    has and this does not: **no row is written here at all.**

    That is the whole shape (ADR workflows-7). A cancellation is a *request*,
    not an outcome: Temporal decides when the execution actually stops, the
    workflow gets to run its cleanup, and the row closes as `cancelled` only
    when somebody witnessed it — the finish seam (`workflows._finish`, which
    marks the row from inside the cancelled workflow) or the reconciler
    (`activities.reconcile_runs`, which reads `CANCELED` off the server for a
    run that never reached its own seam). A service that stamped `cancelled`
    here would be the ledger saying a thing had happened because somebody asked
    for it, which is exactly the lie the run ledger exists to not tell — and it
    would be unrecoverable, because a workflow that ignored the cancel and ran
    to completion would then have a `cancelled` row and a `completed` history.

    So the door answers with the row **as it is** — still `running` — and the
    contract sentence tells the caller to poll it. There is no `select_for_update`
    for the same reason: with nothing to write, two cancels arriving together are
    two identical requests to Temporal, which is idempotent about them.

    The cancel itself goes out on `transaction.on_commit(..., robust=True)`,
    the `signal_workflow` and `start_replay` shape exactly: a caller whose
    transaction rolled back has not asked for anything, and an unreachable
    Temporal must not take the hooks queued behind it down with it. A cancel
    that could not be dispatched leaves a row that is honestly still `running`,
    which is the state it is in.

    It is a `@service` because it is an authorized, audited decision about
    somebody's tenant, even though the only row it touches it touches for
    reading.
    """
    run = WorkflowRun.objects.for_tenant(tenant).filter(pk=run_id).first()
    if run is None:
        raise NotFound()
    require(actor, CANCEL_ACTION, run)
    if run.started_by_id is None or run.started_by_id != actor.user_id:
        raise NotFound()
    if run.status != WorkflowRun.Status.RUNNING:
        raise Conflict(
            f"That job has already {run.status} and can no longer be stopped. "
            "There is nothing left to cancel."
        )

    # Captured before the hook closes over the row: the hook names an execution,
    # and reading `run` from inside it would read whatever the row says by then.
    workflow_id = run.workflow_id
    execution_id = run.run_id

    def _dispatch() -> None:
        async def _go() -> None:
            from apps.workflows.client import get_client

            client = await get_client()
            handle = client.get_workflow_handle(workflow_id, run_id=execution_id or None)
            await handle.cancel()
            log.info("workflow.cancel.requested", workflow_id=workflow_id, status=run.status)

        run_async(_go)

    transaction.on_commit(_dispatch, robust=True)
    return run


def _workflow_type(workflow: str | Any) -> str:
    return workflow if isinstance(workflow, str) else str(workflow.__name__)


async def _start_recorded(
    *,
    run: WorkflowRun,
    workflow: str | Any,
    arg: Any,
    tenant: Tenant | None,
    user: AbstractBaseUser | None,
    org: Organization | None,
    client: Client,
    task_queue: str | None,
) -> WorkflowRun:
    """Start the run the visibility row is already describing.

    The tenant and user are set on the contextvars before the client call so the
    outbound interceptor can stamp them onto the workflow's headers, and they are
    repeated in the memo so a human reading the Temporal UI can see whose work a
    run is without decoding anything.

    **`WorkflowAlreadyStartedError` is a success here** — the other half of
    `record_run`'s idempotent return, and the only way to tell a live run from
    a row whose execution never started, which is what makes this call a heal.
    """
    from apps.workflows.client import task_queue as default_task_queue

    # The chain continues rather than restarting: the door's correlation id
    # rides along, and the door's id becomes this run's causation id, so a
    # delivery this workflow makes tomorrow still joins to the request that
    # asked for it.
    chain = context.child_of_current()
    tokens = set_principal(
        tenant_id=str(tenant.pk) if tenant is not None else None,
        user_id=str(user.pk) if user is not None else None,
        org_id=str(org.pk) if org is not None else None,
        correlation_id=chain["correlation_id"],
        causation_id=chain["causation_id"],
    )
    try:
        handle = await client.start_workflow(
            workflow,
            arg,
            id=run.workflow_id,
            task_queue=task_queue or default_task_queue(),
            # A platform run carries empty tenant fields rather than a
            # borrowed or invented one: the Temporal UI should say "nobody's
            # tenant" out loud, because that is what is true.
            memo={
                "tenant_id": str(tenant.pk) if tenant is not None else "",
                "tenant_slug": tenant.slug if tenant is not None else "",
                "org_slug": org.slug if org is not None else "",
                "user_id": str(user.pk) if user is not None else "",
            },
        )
    except WorkflowAlreadyStartedError as live:
        # The run id comes off the error, so the row still names its execution.
        log.info("workflow.start.already_running", workflow_id=run.workflow_id)
        return await run_db(record_run_id, run=run, run_id=live.run_id or run.run_id)
    finally:
        reset_principal(tokens)

    return await run_db(record_run_id, run=run, run_id=handle.result_run_id or "")


async def start_workflow(
    *,
    workflow: str | Any,
    arg: Any,
    tenant: Tenant | None,
    user: AbstractBaseUser | None = None,
    org: Organization | None = None,
    id: str,
    client: Client,
    task_queue: str | None = None,
) -> WorkflowRun:
    """Start a workflow for a tenant and record it. **For async callers.**

    A service calls `start_workflow_on_commit` instead; this one exists for code
    that already has a client and a running loop — the worker, an activity, and
    the workflow tests, which must drive the time-skipping environment's own
    client rather than connect to a server.

    **`id` is required and validated here exactly as it is on the sync path.**
    It used to default to `f"{type}-{uuid4()}"`, which quietly turned every
    caller that forgot it into a caller with no idempotency at all: two asks,
    two runs, and a deterministic-id rule that this module was itself exempt
    from. `tenant=None` is the platform population and takes a `platform:`
    id (ADR workflows-3).
    """
    check_workflow_id(id=id, tenant=tenant)
    check_org_agreement(tenant=tenant, org=org)
    workflow_type = _workflow_type(workflow)
    run = await run_db(
        record_run,
        tenant=tenant,
        workflow_id=id,
        workflow_type=workflow_type,
        input_digest=hash_run_input(arg),
        user=user,
    )
    return await _start_recorded(
        run=run,
        workflow=workflow,
        arg=arg,
        tenant=tenant,
        user=user,
        org=org,
        client=client,
        task_queue=task_queue,
    )


def start_workflow_on_commit(
    *,
    workflow: str | Any,
    arg: Any,
    tenant: Tenant | None,
    user: AbstractBaseUser | None = None,
    org: Organization | None = None,
    id: str,
    task_queue: str | None = None,
) -> WorkflowRun:
    """Start a workflow when the caller's transaction commits. **The service door.**

    Synchronous, and the ordering is the point:

    1. the visibility row is written *in the caller's transaction*, so it is
       atomic with the business write it describes and disappears with it if the
       transaction rolls back;
    2. the client call is deferred to `transaction.on_commit`, so nothing durable
       is started for a row that never landed.

    `id` is required and must be the house shape (see `workflow_id`), and it is
    what makes **this call idempotent**: asking twice for the same live id with
    the same `arg` returns the same row and starts one run. Asking with a
    *different* `arg` is a `Conflict` — `record_run`'s docstring holds the whole
    2x2, and the digest that drives it is computed here rather than by any
    caller.

    `org` is the **acting hat** the run is started under. It rides on the
    workflow's headers to every activity, so an activity acting for a branch
    reads and writes as that branch rather than as the whole tenant. A start
    with no org is a tenant-wide run, which is what a flat product and every
    platform workflow (email, dispatch) is — and a hat belonging to *another*
    tenant is refused here rather than stamped onto the headers.
    """
    check_workflow_id(id=id, tenant=tenant)
    check_org_agreement(tenant=tenant, org=org)
    run = record_run(
        tenant=tenant,
        workflow_id=id,
        workflow_type=_workflow_type(workflow),
        input_digest=hash_run_input(arg),
        user=user,
    )

    def _dispatch() -> None:
        async def _go() -> None:
            from apps.workflows.client import get_client

            client = await get_client()
            await _start_recorded(
                run=run,
                workflow=workflow,
                arg=arg,
                tenant=tenant,
                user=user,
                org=org,
                client=client,
                task_queue=task_queue,
            )

        run_async(_go)

    # `robust=True` — the same reasoning as `signal_workflow`'s hook above: a
    # start that cannot reach Temporal is a run that did not start, and must
    # never also be an email that was never sent. The row is already committed,
    # so the ask is not lost either.
    transaction.on_commit(_dispatch, robust=True)
    return run


# --- Housekeeping ------------------------------------------------------------

#: How long a closed run stays in the ledger (ADR core-13's declaration on
#: `WorkflowRun` is what makes this number a promise rather than a habit).
#:
#: **180 days is ratified, not measured.** No deployment of this template has
#: run long enough to have an opinion about how far back a person actually
#: reads their own run history, so this is the number the plan settled on and
#: the declaration is what makes it revisitable: the window lives here, in one
#: named constant, with the model's declaration pointing at the callable that
#: applies it. A product that knows better changes this line and says why.
#:
#: A module constant rather than a setting, for the reason `RECONCILE_AFTER`
#: gives one file over: this is the shape of the ledger's own housekeeping and
#: not a per-deployment tuning knob. A product that needs it to be one is
#: adding a setting deliberately, in a diff a reviewer reads.
FINISHED_RUN_RETENTION = timedelta(days=180)

#: The two terminal statuses a purge may take, spelled once.
#:
#: `RUNNING` is absent because those rows are the reconciler's population;
#: `FAILED` is absent because a failure is the record of something that did not
#: work and deleting it is deleting the finding. `WorkflowRun.lifecycle`'s
#: comment carries the whole argument — this tuple is where it becomes code.
PURGEABLE_STATUSES: tuple[str, ...] = (
    WorkflowRun.Status.COMPLETED,
    WorkflowRun.Status.CANCELLED,
)


@service
# rule-13: this service has no `tenant=` to take, and must not grow one. It is
# deployment housekeeping that crosses EVERY population by design — one
# `for_tenant` per tenant plus the platform rows no tenant owns — so a `tenant=`
# parameter would be a lie about its scope and would make the wrapper write one
# audit row naming whichever tenant the caller happened to pass. The same shape
# and the same reason as `apps.events.services.purge_dispatched_outbox`. What
# it did is on the schedule's run and in `workflows.purge.runs`, where an
# operator reads a sweep; an audit row is for a decision somebody took about
# somebody's rows, and nobody took one here.
def purge_finished_runs(*, before: datetime) -> int:
    """Drop runs that closed cleanly before `before`. Returns how many went.

    **Only `completed` and `cancelled`.** A `running` row belongs to
    `activities.reconcile_runs` — sweeping one would delete a promise the
    reconciler was about to keep, which is rule 28's fear with the evidence
    removed — and a `failed` row is the record of something that broke, which
    is the thing somebody comes to the ledger to find. Both survive every
    window, for ever, and that is a deliberate consequence stated on the
    declaration rather than a gap.

    Idempotent by construction: it deletes by age, so a second run in the same
    window removes nothing.

    **Read through each population's own path** (house rule 8), exactly as
    `activities.stranded_runs` is: one `for_tenant` per tenant, then
    `for_platform()` for the rows no tenant owns. That is one statement per
    tenant on a daily cadence, which is the honest cost of a rule that says a
    scoped model is read scoped — and the platform half is not optional, since
    `for_tenant` fails closed and can never reach the deployment's own runs.

    # authz: deployment housekeeping, run by a schedule as the system. It is
    # scoped by age and by terminal status, resolves no actor, and answers to
    # nobody's request — the same posture as
    # `apps.events.services.purge_dispatched_outbox`.
    """
    deleted = 0
    for tenant in Tenant.objects.all().iterator():
        removed, _ = (
            WorkflowRun.objects.for_tenant(tenant)
            .filter(status__in=PURGEABLE_STATUSES, finished_at__lt=before)
            .delete()
        )
        deleted += int(removed)
    removed, _ = (
        # rule-8: the platform population is the declared null-tenant one (ADR
        # workflows-3), and `for_tenant` stays fail-closed and can never reach
        # it. Without this half the deployment's own closed runs — every
        # identity revocation, every workforce sync — would be the one part of
        # the ledger no window ever applied to.
        WorkflowRun.objects.for_platform()
        .filter(status__in=PURGEABLE_STATUSES, finished_at__lt=before)
        .delete()
    )
    deleted += int(removed)
    return deleted
