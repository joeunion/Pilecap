"""The run ledger's read door, and the two things a person may do to a run.

Until this file existed, `WorkflowRun` was reachable only from the Django admin
and a Python shell (ADR workflows-6): the product kept a careful record of every
durable thing it did on somebody's behalf and then offered them no way to look
at it. Four routes close that — list, get, **replay** and **cancel**.

**Replay and cancel are mirror images and they are both the actor's own runs
only.** Replay takes a run that failed and runs it again; cancel takes a run
that is still going and asks it to stop. They put up the same four walls in the
same order and give the same not-found answer to a run that is not yours — and
they differ in exactly one place: replay writes the row back to `running`
before it dispatches, and **cancel writes nothing at all**, because a
cancellation is a request and the row may only say `cancelled` once somebody
has witnessed the execution stop (ADR workflows-7).

**Replay is a Temporal reset, and it is the actor's own runs only.** The server
re-executes the input its own history already witnessed, which is what rule 9's
determinism buys and what makes "run it again" possible without asking a client
to remember an argument it may never have held. Signalling and retry-tuning
stay operator-only — a deliberate ruling — because this layer can
see a tenant and an id and cannot see what a run is *about*, and "may this
person end that wait" is only answerable one layer up, in the domain service
that owns the wait.

The routes never say 404 for a missing row themselves: `selectors.get_run` and
`services.start_replay` raise `NotFound` and `config/api.py` is the only module
that turns that into a number, so the MCP tools over the same functions refuse
identically without repeating the rule.
"""

# NOTE: no `from __future__ import annotations` in this module, and that is
# deliberate. ninja builds a Pydantic model out of a route's signature at import
# time; with postponed evaluation every annotation is a string, and a
# `FilterSchema` parameter comes out as an unresolvable forward reference.

from uuid import UUID

from django.db.models import QuerySet
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.pagination import paginate

from apps.accounts.auth import API_AUTH
from apps.core.actor import Actor, actor_from_request
from apps.core.api import CursorPagination, ordered_by
from apps.core.api.docs import Tag
from apps.core.models import Tenant
from apps.core.requests import TenantRequest
from apps.workflows.models import WorkflowRun
from apps.workflows.schemas import WorkflowRunFilter, WorkflowRunOut
from apps.workflows.selectors import get_run, list_runs
from apps.workflows.services import cancel_run, start_replay

# **The root of `/api/v1/`** (ADR api-2, the owner's 2026-08-24 ruling): the
# first path segment names a RESOURCE, never an app. The resource here is
# `runs` — the workflow is the code, and code is not addressable over HTTP —
# and the route paths already say so, so flattening is an empty PREFIX and not
# a route rewrite. `/api/v1/runs/` is what a caller asks for; `workflows` was
# the name of the module that happens to serve it. House rule 32 refuses the
# regression.
PREFIX = ""

# What `?ordering=` may name, and nothing else. Straight into `.order_by()` it
# would let a client sort by any column and traverse any relation — including
# `started_by__password`.
ORDERING = ("started_at", "finished_at", "created_at", "updated_at", "status", "type")

# What each tag on this app's routers is FOR, in the app that owns the tag.
# `config/api.py` collects these by discovery into the OpenAPI document's `tags`
# section, so a reader meets the group before the routes in it (ADR api-1); an
# undescribed tag is a house-rule-41 violation, not a blank heading.
TAGS = {
    "runs": Tag(
        "Background jobs",
        "Background jobs. Work this API does not finish while you wait — sending "
        "a message, syncing an integration, onboarding a record — is started as a "
        "background job, and every one of them appears here: what it was, who "
        "started it, whether it is still running, and why it failed if it did. A "
        "job of your own that failed can be restarted from the beginning with the "
        "input it was originally given. There is no endpoint here for nudging a "
        "job that is waiting on something, or for changing how hard it retries: "
        "those belong to whichever endpoint started the job.",
        plane="everyday",
        plane_note=(
            "the background jobs: work the API started rather than finished while you waited. "
            "Anybody in the tenant can read the ledger; you can replay a run you started "
            "yourself."
        ),
    ),
}

# `auth` is restated here rather than inherited from the API default, so that
# reading this one file tells you what it takes to call these routes.
router = Router(tags=["runs"], auth=API_AUTH)


def _acting(request: TenantRequest) -> tuple[Actor, Tenant]:
    """The actor and tenant a replay or a cancel happens as.

    Authentication has already guaranteed the user; nothing has guaranteed the
    tenant. A write with no tenant is refused rather than guessed at.

    **Whether the actor may replay or cancel is not decided here** — each
    service calls `authz.require` and then checks whose run it is. A permission
    check in this function would be a second copy of the rule, one per door.
    """
    if request.tenant is None:
        raise HttpError(403, "No tenant for this request.")
    return actor_from_request(request), request.tenant


@router.get("/runs/", response=list[WorkflowRunOut], url_name="run-list")
@paginate(CursorPagination)
def list_runs_route(
    request: TenantRequest,
    filters: Query[WorkflowRunFilter],
    mine: bool = True,
    ordering: str = "-started_at",
) -> QuerySet[WorkflowRun]:
    """List background jobs

    List the background jobs started in the tenant you are acting in, newest
    first.

    A background job is any piece of work the API does not finish while you
    wait — sending a message, syncing an integration, onboarding a record. Each
    one gets a row here the moment it is started, and the row is updated as the
    job progresses.

    By default you get **only the jobs you started yourself**. Send
    `mine=false` to see everything anybody in this tenant started, including your
    colleagues' jobs. A few jobs have no recorded starter — jobs begun before
    this endpoint existed, and jobs the platform runs for itself — and those
    appear only when `mine=false`.

    Filter with `status` (`running`, `completed` or `failed`) and `type` (the
    job's name, for example `WidgetOnboardingWorkflow`). Sort with `ordering`,
    which accepts `started_at`, `finished_at`, `created_at`, `updated_at`,
    `status` or `type`, each optionally prefixed with `-` to reverse it;
    anything else is rejected with `invalid`. Walk it with `?cursor=` and
    `?limit=`; `count` arrives only with `?include_count=true`.

    Each row tells you `status`, when it `started_at` and `finished_at`, who
    started it (`started_by_email`), and — when it failed — `error`, which is
    the underlying failure, not a generic wrapper. `run_id` is the identifier
    the job has in the execution engine; it is briefly empty for a job that has
    just been started and not yet handed over.

    Refusals you can get here:

    * `400 invalid` — `?ordering=` named a field this list does not accept, or
      a filter value was malformed. The response says what you may sort by.
    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    `mine` is a route parameter rather than a `FilterSchema` field because it
    needs the acting user, which a schema does not have. The selector applies
    it, and the same argument exists on the MCP twin so the two doors default
    identically.
    """
    runs: QuerySet[WorkflowRun] = list_runs(
        tenant=request.tenant, actor=actor_from_request(request), mine=mine
    )
    runs = filters.filter(runs)
    return ordered_by(runs, ordering, allowed=ORDERING, default="-started_at")


@router.get("/runs/{run_id}/", response=WorkflowRunOut, url_name="run-detail")
def retrieve_run(request: TenantRequest, run_id: UUID) -> WorkflowRun:
    """Retrieve a background job

    Fetch one background job by its `id`.

    You can fetch any job started in this tenant, not only your own — so a
    job id from a colleague's list works here too.

    A job id that does not exist, and one belonging to another tenant,
    both answer `not_found`. That is deliberate: the two are indistinguishable
    on purpose, so nobody can use this endpoint to find out whether an id is
    real.

    Refusals you can get here:

    * `404 not_found` — no job of this tenant's has that id. A guessed id and
      another tenant's job answer identically.
    * `403 forbidden` — the request resolved no tenant. Send `X-Tenant` naming
      one you belong to.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    `selectors.get_run` raises the refusal and `config/api.py` turns it into a
    status code, so the MCP twin over the same selector refuses identically
    without repeating the rule.
    """
    return get_run(tenant=request.tenant, actor=actor_from_request(request), run_id=run_id)


@router.post("/runs/{run_id}/replay/", response=WorkflowRunOut, url_name="run-replay")
def replay_run_route(request: TenantRequest, run_id: UUID) -> WorkflowRun:
    """Replay a background job

    Run a failed background job again, from the beginning.

    Send no body. The job is restarted with **the same input it was originally
    given** — the execution engine still has it, so you do not need to know
    what it was or to repeat the original request. The job keeps the same `id`
    and the same `workflow_id`.

    You get the job back with `status` set to `running`, `error` cleared and
    `finished_at` empty. `run_id` is briefly empty and fills in once the engine
    has accepted the restart; poll this job's `GET` endpoint to follow it.

    **Restarting re-does everything the job had already done** before it
    failed, including anything it sent or wrote. Jobs in this API are built to
    be safe to run twice, but be aware that a restart is a genuine re-run and
    not a resume from the point of failure.

    You may only restart **jobs you started yourself**.

    Refusals you can get here:

    * `404 not_found` — no such job, a job belonging to another tenant, a job
      one of your colleagues started, or a job with no recorded starter. All
      four give the same answer on purpose, so this endpoint cannot be used to
      discover whether an id is real. If a colleague's job needs restarting,
      ask them to do it.
    * `409 conflict`, *still running* — the job has not failed; there is
      nothing to restart. Wait for it to finish, and restart it only if it
      fails.
    * `409 conflict`, *already finished* — the job succeeded. Running the same
      work again is a new job, not a repeat of that one, so start it through
      whichever endpoint started it the first time.
    * `409 conflict`, *too old* — the job started more than 30 days ago and the
      record of what it was asked to do is no longer kept, so there is nothing
      to restart from. Start the work again from the endpoint that originally
      started it.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    A Temporal reset to the first workflow task, dispatched on commit. The
    walls, their order and why history retention is decided from the row's own
    clock rather than an RPC are in `services.start_replay`.
    """
    actor, tenant = _acting(request)
    return start_replay(tenant=tenant, actor=actor, run_id=run_id)


@router.post("/runs/{run_id}/cancel/", response=WorkflowRunOut, url_name="run-cancel")
def cancel_run_route(request: TenantRequest, run_id: UUID) -> WorkflowRun:
    """Stop a background job

    Ask a background job that is still running to stop.

    Send no body. **This is a request, not an instant result.** The job is told
    to stop; it then gets to finish tidying up whatever it was part-way through,
    and only when it has actually stopped does its record say so. Some jobs stop
    within a second and a few take longer.

    So the job comes back from this call **exactly as it was** — `status` is
    still `running` — and that is not a mistake. Poll this job's `GET` endpoint:
    its `status` becomes `cancelled` once the job has really stopped, and
    `finished_at` fills in at the same moment. A job that had already finished
    the last of its work before your request reached it may still end
    `completed`; nothing is rolled back by stopping a job, so anything it had
    already sent or written stays sent and written.

    A stopped job is **not** a failed one. `cancelled` and `failed` are separate
    words on purpose, and a job you stopped cannot be restarted with the restart
    endpoint — start the work again where it was started the first time.

    You may only stop **jobs you started yourself**.

    Refusals you can get here:

    * `401 unauthenticated` — no usable credential resolved: none was sent, or
      the bearer token was wrong, expired or revoked. Sign in, or send
      `Authorization: Bearer <token>`.
    * `403 insufficient_scope` — the bearer token authenticated but is not
      scoped for this. Mint one that carries the scope named in the response.
    * `403 forbidden` — the request resolved no tenant, or you do not have
      standing to stop background jobs here. Send `X-Tenant` naming a tenant you
      belong to.
    * `404 not_found` — no such job, a job belonging to another tenant, a job
      one of your colleagues started, or a job with no recorded starter. All
      four give the same answer on purpose, so this endpoint cannot be used to
      discover whether an id is real. If a colleague's job needs stopping, ask
      them to stop it.
    * `409 conflict` — the job has already finished, one way or another, so
      there is nothing left to stop. The message names the state it is in.
    * `409 idempotency_key_reuse` / `409 in_progress` — you reused an
      `Idempotency-Key` for a different request, or the first request under it
      has not finished. Resend the identical request, or use a new key.
    * `429 rate_limited` — wait for the `Retry-After` seconds and try again.

    ---

    A Temporal cancellation, dispatched on commit. **The service stamps no row
    fields at all** — the row closes as `cancelled` through the finish seam
    (`workflows._finish`, from inside the cancelled workflow) or through the
    reconciler, which is what makes the ledger's third word a witnessed fact
    rather than a restatement of somebody's request (ADR workflows-7). The
    walls and their order are in `services.cancel_run`.
    """
    actor, tenant = _acting(request)
    return cancel_run(tenant=tenant, actor=actor, run_id=run_id)
