"""Writes for the run ledger, and the seams a service starts, signals, replays and cancels with.

Ids are deterministic: `<tenant>:<app>:<noun>:<key>`, or `platform:…` for nobody's run (ADR
workflows-3); asking twice for the same work is a retry, decided by `input_digest` (workflows-4).
Every Temporal call goes out on the caller's commit, so a rolled-back caller asked for nothing.
why-not `@service` on the two starters: `record_run` is their one write, and it is audited.
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
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.asyncdb import run_async, run_db
from apps.core.authz import holds, refusal_sentence, require
from apps.core.context import ContextUnbound
from apps.core.exceptions import Conflict, Forbidden, NotFound, as_invalid
from apps.core.log import get_logger
from apps.core.models import Organization, Tenant
from apps.core.policies import ADMINISTERS_THE_NODE
from apps.core.roads import road
from apps.core.service import redact, service, write_audit
from apps.core.services import root_organization
from apps.core.types import Swept
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
# `closed_as` and `previous_error` are the re-ask receipt's two facts: the
# status the row held before it was re-opened, and the error text that was
# cleared off it. Both are this app's own words about its own row —
# the same class as `status` and `error` beside them — and both are useless
# `[redacted]`, which is what a receipt that named nothing would be.
LOG_KEYS: frozenset[str] = frozenset(
    {
        "workflow_id",
        "workflow_type",
        "status",
        "error",
        "signal",
        "closed_as",
        "previous_error",
        # What the caller ASKED FOR, on the one path where nothing else records
        # it. `@service` files the refused call's audit row from the arguments
        # alone — there is no return value on that path — so a redacted flag
        # made the wall's `outcome=error` row unable to tell a caller who set
        # it deliberately and hit the `completed` wall from one who never asked
        # at all. Those are the same refusal with different intent behind them,
        # and only one of them is a bug in the caller. A boolean the caller
        # typed is not a fact about a person; the allow-list protects values,
        # and this one has nothing in it to protect.
        "reask_after_failure",
    }
)

# The statuses that mean a run **finished without delivering** — the population
# `record_run`'s fifth answer re-opens when a start site asks for it.
#
# Derived from the model's own enum rather than listed, and the derivation is
# the subtraction rather than the addition: everything that is not RUNNING (not
# finished at all) and not COMPLETED (finished, and delivered). A terminal
# status added to `WorkflowRun.Status` tomorrow therefore joins this population
# by default, which is the safe direction — the alternative is a new way for a
# run to end that silently keeps the lockout the fifth answer exists to end.
REASKABLE_STATUSES: tuple[str, ...] = tuple(
    status
    for status in WorkflowRun.Status.values
    if status not in (WorkflowRun.Status.RUNNING, WorkflowRun.Status.COMPLETED)
)

# What the re-ask receipt is filed under. Not `workflows.record_run`: that
# action is the row being written, and this is the separate fact that a
# previous attempt's closure was discarded to write it.
REASK_AUDIT_ACTION = "workflows.reask_run"

# The four keys this app's doors authorize, and all four name the kind
# `WorkflowRun` derives — `workflow_run`. They were `workflow.signal` and
# `workflowrun.{read,replay,cancel}` until P7.8; the old words still answer
# through `policies.py`'s `RENAMED_PERMISSIONS`, and that file says what naming
# a kind the registry does not have was costing.
#
# Module-level string CONSTANTS rather than literals at the call sites, which is
# a shape rule 13 reads by resolving the name to its constant: one spelling, and
# a rename that cannot half-land across four call sites.

# The action `signal_workflow` authorizes. `policies.py` answers it; see the
# note there about which half of the question this layer can actually answer.
SIGNAL_ACTION = "workflow_run.signal"

# The two actions the run ledger's own doors authorize (ADR workflows-6). Read
# is tenant-wide and replay is not — the narrowing that makes replay the
# actor's own is `started_by`, checked in the service and not in the policy,
# because a policy that reached for the acting user would be answering a
# question about the ROW rather than about the person's standing.
READ_ACTION = "workflow_run.read"
REPLAY_ACTION = "workflow_run.replay"

# And the third (ADR workflows-7). Narrowed to the actor's own by `started_by`
# in `cancel_run`, for exactly the reason replay is: the policy is handed the
# row and could compare it, but `require` raises `Forbidden` and a `Forbidden`
# on somebody else's run confirms the run exists.
CANCEL_ACTION = "workflow_run.cancel"

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


@road("workflow_id", example="apps/example/tests/test_attach_import.py::_run_id")
# rule-16: a marked road rule 18 reads by name; the run's column and a wire field share it
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


def _reask_receipt(
    run: WorkflowRun,
    *,
    tenant: Tenant | None,
    closed_as: str,
    previous_error: str,
    user: AbstractBaseUser | None,
) -> None:
    """What the re-opened row can no longer say, written where it cannot be lost.

    **The problem this closes is that `_reopen` is a rewrite.** `status`,
    `error`, `finished_at` and `run_id` are cleared in place, so a second later
    nothing in the ledger says the previous attempt ever failed, or why. For
    the *supersede* quadrant that is honest — the work changed, and the old
    answer was about different work — but for a re-ask it is the opposite: the
    whole reason the caller is here is that the last attempt broke, and losing
    that is losing the only record of a run that did not deliver.

    So the fact goes to `AuditEntry`, which declares `append_only = True`
    (house rule 20): once written, nothing in the tree may update or delete it.
    The visibility row stays visibility; the ledger keeps the history. Both
    land in `record_run`'s transaction — this is called from inside it — so a
    caller that rolls back leaves neither the re-open nor its receipt.

    **Not a `@service`, and `write_audit` directly, for two reasons.** It is a
    private branch of one decision rather than a capability anybody may ask
    for — the same argument `_reopen` makes about itself one function down —
    and the two facts it records are *derived from the row*, not arguments
    anybody passed, so there is no signature the `@service` seam could redact
    them out of. `core.services.bootstrap_tenant` is the standing precedent for
    a caller that assembles its own row rather than a second copy of this
    function's body.

    The payload still goes through `redact` against this app's `LOG_KEYS`,
    which is what makes the allow-list load-bearing here rather than decorative:
    a key this app has not declared comes out `[redacted]` in a receipt exactly
    as it would in a service's own row.
    """
    write_audit(
        action=REASK_AUDIT_ACTION,
        tenant=tenant,
        # `record_run` takes no actor — it is the write seam beneath the
        # starters and rule 49 records the absence — so the person is named the
        # way the row itself names them: by the id the starter threaded here.
        actor=None,
        payload=redact(
            {
                "workflow_id": run.workflow_id,
                "workflow_type": run.type,
                "closed_as": closed_as,
                "previous_error": previous_error,
                "user_id": str(user.pk) if user is not None else "",
            },
            LOG_KEYS,
        ),
        outcome="ok",
        result=run,
    )


def _reopen(
    run: WorkflowRun,
    *,
    workflow_type: str,
    input_digest: str,
    user: AbstractBaseUser | None,
    tenant: Tenant | None = None,
    reasked: bool = False,
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

    **`reasked` is the fifth answer coming through the same door.**
    The mutation below is identical either way — a re-opened row is a re-opened
    row — and what differs is what was thrown away to get it: the supersede
    discards an answer about *different* work, which the new digest already
    records, while a re-ask discards the record of a run that BROKE, which
    nothing else in the tree would then hold. So that branch, and only that
    branch, files `_reask_receipt` above before it returns. The facts are read
    off the row **before** the mutation, because after it they are gone.
    """
    closed_as = run.status
    previous_error = run.error
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
    if reasked:
        _reask_receipt(
            run,
            tenant=tenant,
            closed_as=closed_as,
            previous_error=previous_error,
            user=user,
        )
    return run


def _answer_for_the_row_already_there(
    existing: WorkflowRun,
    *,
    tenant: Tenant | None,
    workflow_type: str,
    input_digest: str,
    user: AbstractBaseUser | None,
    reask_after_failure: bool,
) -> WorkflowRun:
    """The five answers, as code. `record_run`'s docstring is the contract.

    A private branch rather than a second seam: it is reachable only from
    `record_run`, whose transaction, audit row and published prose cover every
    answer it can give. It lives one `def` out because the function-length
    budget is the house's way of saying a service has grown a second job, and
    "write the row" and "decide what the row that is already there means" are
    honestly two — which is why the split falls here and not somewhere that
    would leave half a decision on each side.
    """
    # Unknown on either side is not a mismatch: see `record_run`'s docstring.
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
    # The fifth answer and the supersede re-open the same way; what differs is
    # what was discarded, which is why only the re-ask files a receipt.
    reasked = same_work and reask_after_failure and existing.status in REASKABLE_STATUSES
    if same_work and not reasked:
        raise Conflict(
            f"A {existing.type} job with that id has already {existing.status}. "
            "Running the same work again is a new job, not a repeat of that one."
        )
    return _reopen(
        existing,
        workflow_type=workflow_type,
        input_digest=input_digest,
        user=user,
        tenant=tenant,
        reasked=reasked,
    )


# door: the ledger's own write seam, and giving it a door would be the bug. A
# caller that could ask for a WorkflowRun row could mint visibility for a run
# nobody started, or claim an id a real start then collides with; the row exists
# to describe what the starters did, so the starters are the only callers.
# Reachable from every door in the tree through them (rule 42 counts direct
# calls, and that is the finding it is designed to make, not one here).
@service(witness=False)
def record_run(
    *,
    tenant: Tenant | None,
    workflow_id: str,
    workflow_type: str,
    actor: Actor,
    input_digest: str = "",
    reask_after_failure: bool = False,
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
    questions — is it live, and is it the same work — and there are four
    answers (ADR workflows-4), plus a fifth the START SITE has to ask for:

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

    **The fifth answer: `reask_after_failure=True` and the row finished without
    delivering** — the row re-opens, exactly as the supersede does,
    and the ledger keeps a receipt of what that threw away (`_reask_receipt`).

    It exists because the third answer above is right about `completed` and
    wrong about `failed`. A reconciler whose run broke re-derives the *same*
    intent — that is what makes it a reconciler — under a key derived from the
    row it is reconciling, so it has no second id to offer and the honest retry
    was answered "that is a new job". A morning of it is the lockout the
    consumer measured. The population that re-opens is `REASKABLE_STATUSES`,
    derived from the model's own enum; `completed` is deliberately not in it,
    so the flag can never turn delivered work into a silent second run.

    **And it is off unless asked for**, which is what keeps every other start
    site in the tree byte-identical: the default is `False`, the answer at that
    default is the `Conflict` it always was, and the decision to re-ask belongs
    to the service that knows whether its work is safe to repeat (principle 16)
    rather than to this layer, which cannot know.

    **An empty digest is unknown, never a mismatch.** Rows written before the
    column existed hold `""` and pass every comparison, because a backfill
    nobody can compute would be a guess wearing the authority of a fact. New
    starts always compute one, so the population converges forward.

    `actor` is **who asked**, keyword-only and required (ADR workflows-9): the
    caller's actor, from which the row's `started_by` and this service's own
    audit row both read who — never the bound context, which is observability
    data and not a claim. Both starters build it for the callers that still
    hand them a bare `user`, and a start nobody asked for is the system actor,
    named rather than absent. It is a parameter of this function and never of
    a door: a caller that could name a starter could hand themselves somebody
    else's replay right. A system actor's `started_by` is `None` — unknown
    stays unknown, the `input_digest` convergence pattern verbatim.
    """
    # authz: the ledger's write seam records WHO asked and grants nothing; the
    # starters' callers asked their own question at the door that started the
    # work, and a second one here would ask it of the system actor a schedule
    # names, which passes everything anyway.
    user = actor.user
    existing = _run_under(tenant=tenant, workflow_id=workflow_id)
    if existing is not None:
        return _answer_for_the_row_already_there(
            existing,
            tenant=tenant,
            workflow_type=workflow_type,
            input_digest=input_digest,
            user=user,
            reask_after_failure=reask_after_failure,
        )
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


# door: only this tree's own hands reach it — a run's own finish activity closes its row
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
    # hat-scoped: a `WorkflowRun` has no organization column, so `run` is passed
    # for the POLICY (`belongs_to_the_tenant`) to read and not as a node — the
    # question this layer can answer is "are you somebody in this tenant", and
    # the acting hat is where that is asked. Reach is answered ABOVE this line by
    # the tenant-scoped fetch raising `NotFound` — reachability before capability,
    # house rule 26's order. Object-level authorization belongs to the domain
    # caller, and `policies.py` says why this layer cannot do it.
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

    # `robust=True`: a raising hook takes every hook queued behind it down with it.
    # rule-92: the signal leaves only after the write commits; the reconciler sweeps a lost one
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


def _require_the_tenants_administrator(actor: Actor, tenant: Tenant) -> None:
    """A system-started run is replayed by `organization.update` at the root (ADR comms-4)."""
    try:
        root = root_organization(tenant=tenant)
    except Conflict:
        raise Forbidden(refusal_sentence(ADMINISTERS_THE_NODE)) from None
    if not holds(actor, ADMINISTERS_THE_NODE, at=root):
        raise Forbidden(refusal_sentence(ADMINISTERS_THE_NODE))


@service
def start_replay(*, tenant: Tenant, actor: Actor, run_id: UUID) -> WorkflowRun:
    """Run a failed run again, from its first workflow task. **The actor's own**, or the system's.

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
    require(actor, REPLAY_ACTION, run)  # hat-scoped: no organization on this row; see policies.py
    if run.started_by_id is None:
        _require_the_tenants_administrator(actor, tenant)
    elif run.started_by_id != actor.user_id:
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

    # rule-92: the reset leaves only after the RUNNING row commits; the reconciler sweeps a lost one
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
    when somebody witnessed it — the finish seam (`determinism.run_to_finish`, which
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
    # hat-scoped: `may_cancel_their_own`'s question, not a node's — a
    # `WorkflowRun` carries no organization, so `run` is the policy's argument
    # and the acting hat is the node a tenant-wide ledger asks at. Reach is
    # answered ABOVE this line by the tenant-scoped fetch raising `NotFound` —
    # reachability before capability, house rule 26's order. The ownership half is
    # the `started_by_id` wall below, a `NotFound` for the reason `start_replay`
    # gives verbatim.
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

    # rule-92: the cancel reaches Temporal only after the run's status commits
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


def _starter_actor(
    *,
    tenant: Tenant | None,
    user: AbstractBaseUser | None,
    org: Organization | None = None,
    actor: Actor | None = None,
) -> Actor:
    """The actor a start records its run as: the caller's, or one built from its parts.

    A caller that hands the actor is taken at its word, and a `user` or `org`
    beside it that names somebody else is a caller bug (`ValueError`), never a
    choice between two answers. A caller that hands only the parts gets a
    `human` actor for a person — the starters' existing callers resolve a
    person at a door that clicked — and the system actor for nobody.
    """
    if actor is not None:
        if (user is not None and user.pk != actor.user_id) or (
            org is not None and org.pk != actor.org_id
        ):
            raise ValueError(
                "A start was handed an actor and a user or org that names somebody else; "
                "pass the actor alone."
            )
        return actor
    if user is None:
        return system_actor(tenant, org)
    return actor_for(user=user, tenant=tenant, org=org)


async def start_workflow(
    *,
    workflow: str | Any,
    arg: Any,
    tenant: Tenant | None,
    user: AbstractBaseUser | None = None,
    org: Organization | None = None,
    actor: Actor | None = None,
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
    acting = _starter_actor(tenant=tenant, user=user, org=org, actor=actor)
    user, org = acting.user, acting.org
    check_workflow_id(id=id, tenant=tenant)
    check_org_agreement(tenant=tenant, org=org)
    workflow_type = _workflow_type(workflow)
    run = await run_db(
        record_run,
        tenant=tenant,
        workflow_id=id,
        workflow_type=workflow_type,
        actor=acting,
        input_digest=hash_run_input(arg),
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


#: What a start's on-commit hook lets out: a caller's bug, never Temporal being unreachable.
CALLER_BUGS: tuple[type[BaseException], ...] = (
    ContextUnbound,
    TypeError,
    ValueError,
    LookupError,
    AttributeError,
    NameError,
    ImportError,
    AssertionError,
)


@road("start_workflow", example="apps/example/services.py::create_widget")
def start_workflow_on_commit(
    *,
    workflow: str | Any,
    arg: Any,
    tenant: Tenant | None,
    user: AbstractBaseUser | None = None,
    org: Organization | None = None,
    actor: Actor | None = None,
    id: str,
    task_queue: str | None = None,
    reask_after_failure: bool = False,
) -> WorkflowRun:
    """Record the run in the caller's transaction and start it on commit. **The service door.**

    It is idempotent on `id` for the same `arg` (`record_run`'s 2x2, ADR workflows-4); `org` is
    the hat on the run's headers; `actor` is who asks (ADR workflows-9), the system's by default.
    Temporal unreachable at commit is logged and swept; a `CALLER_BUGS` failure propagates.
    """
    acting = _starter_actor(tenant=tenant, user=user, org=org, actor=actor)
    user, org = acting.user, acting.org
    check_workflow_id(id=id, tenant=tenant)
    check_org_agreement(tenant=tenant, org=org)
    run = record_run(
        tenant=tenant,
        workflow_id=id,
        workflow_type=_workflow_type(workflow),
        actor=acting,
        input_digest=hash_run_input(arg),
        reask_after_failure=reask_after_failure,
    )

    def start_on_commit() -> None:
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

        try:
            run_async(_go)
        except CALLER_BUGS:
            raise
        except Exception as unreached:
            log.exception(
                "workflow.start.not_dispatched",
                workflow_id=run.workflow_id,
                error=type(unreached).__name__,
            )

    # why-not `robust=True`: it would swallow `CALLER_BUGS` too; the hook contains the rest.
    transaction.on_commit(start_on_commit)
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


# door: only this tree's own hands reach it — the retention schedule's sweep of closed runs
@service
def purge_finished_runs(*, before: datetime, tenant: None) -> Swept:
    """Drop runs that closed `completed` or `cancelled` before `before`, in every population.

    `running` rows are the reconciler's and `failed` ones the finding; both survive every window.
    `tenant` selects the platform's audit population and filters nothing (ADR core-22).
    # authz: deployment housekeeping, run by a schedule as the system; scoped by age and status.
    """
    deleted = 0
    for owner in Tenant.objects.all().iterator():
        removed, _ = (
            WorkflowRun.objects.for_tenant(owner)
            .filter(status__in=PURGEABLE_STATUSES, finished_at__lt=before)
            .delete()
        )
        deleted += int(removed)
    removed, _ = (
        # rule-8: the platform population is the declared null-tenant one (ADR
        # workflows-3); a fail-closed `for_tenant` can never reach it.
        WorkflowRun.objects.for_platform()
        .filter(status__in=PURGEABLE_STATUSES, finished_at__lt=before)
        .delete()
    )
    deleted += int(removed)
    return Swept(label=WorkflowRun._meta.label, count=deleted)
