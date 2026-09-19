"""Reading the run ledger. Two questions, one scoping rule, no writes.

`WorkflowRun` is `TenantScopedModel` and not `OrgScopedModel` — a run has a
tenant and an id and no idea which part of the tenant its work was about, which
is the same fact `policies.py` is built on — so the read is `for_tenant(...)`
and there is no `visible_to` half to chain (rule 24 governs org-scoped models;
this one is not, and pretending otherwise would put a hat on a row that has
none).

**These selectors authorize**, which was unusual when the ledger was built —
every other read in the tree was gated by the tenant wall alone — and is the
house shape since ADR core-27: a read is a permission, the check lives in the
selector once (§C6), and every door pays it. The key is `workflow_run.read`, the
derived read of the row these two hand back; `workflowrun.read` still answers as
an alias for one release (`policies.py`). `require` reads; it writes nothing, so
rule 12's line holds.

**The order is the grammar** (§C8, reach before capability): `get_run` fetches
through `for_tenant` FIRST and asks second, so another tenant's run is
`not_found` — the answer it always gave — and a run inside the tenant that this
person may not read is `forbidden`. Asking first would make both of them
`forbidden`, which tells a caller that somebody else's id exists; that is the
existence oracle the scoping was there to close, and it would still look like a
working read gate from every door.
"""

from __future__ import annotations

from uuid import UUID

from django.db.models import QuerySet

from apps.core.actor import Actor
from apps.core.authz import require
from apps.core.exceptions import NotFound
from apps.core.models import Tenant
from apps.workflows.models import WorkflowRun
from apps.workflows.services import READ_ACTION


def list_runs(*, tenant: Tenant | None, actor: Actor, mine: bool = True) -> QuerySet[WorkflowRun]:
    """This tenant's runs, newest first — the caller's own unless asked wider.

    `mine` defaults to True because "what did *I* start, and how did it go" is
    the question a person opens this door with, and a ledger that answered with
    the whole company's work by default would bury it. `mine=False` widens to
    the tenant, which is the other question a ledger exists for — *who started
    that sync* — and is the same policy either way.

    A row with no recorded starter is nobody's own run, so it appears only in
    the wide read. That is the honest reading of `NULL` (unknown), not a
    filter that quietly claims those runs for whoever is asking.

    `select_related("started_by")` because `WorkflowRunOut` reports
    `started_by_email`: a property is a fine place to put a name and a terrible
    place to hide a query per row.
    """
    # hat-scoped: a `WorkflowRun` is TENANT-scoped and carries no organization
    # column, so there is no node below the tenant for this question to be asked
    # at — the ledger is tenant-wide by ADR workflows-6 and `policies.py` says so
    # in full. The acting hat is therefore the right and only node here, and the
    # narrowing that matters is `started_by` below, not a subtree.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, READ_ACTION)
    runs = WorkflowRun.objects.for_tenant(tenant).select_related("started_by")
    if mine:
        # By id rather than by instance: `Actor.user` is the base class every
        # user model derives from, and the column is the concrete one.
        runs = runs.filter(started_by_id=actor.user_id)
    return runs.order_by("-started_at")


def get_run(*, tenant: Tenant | None, actor: Actor, run_id: UUID) -> WorkflowRun:
    """One run by id. A run in another tenant is `not_found`, not `forbidden`.

    Deliberately **not** narrowed to the caller's own: a person who can see a
    colleague's run in the list can open it, which is what makes the ledger
    answerable. What their own-ness gates is replay, in `start_replay`.

    **Fetch, then ask, with the row** (PR4.i): `obj=run` rather than `obj=None`.
    A `WorkflowRun` is tenant-scoped and carries no organization, so `where_of`
    falls back to the acting hat and the ANSWER is the same either way — what
    changes is the grammar, and the grammar is the point. The module docstring
    above has the argument; the assertion is
    `tests/test_reads_ask.py::test_the_scoped_fetch_answers_before_the_capability`,
    which drives the two refusal classes as a difference rather than reading
    this order off the source.
    """
    run = (
        WorkflowRun.objects.for_tenant(tenant)
        .select_related("started_by")
        .filter(pk=run_id)
        .first()
    )
    if run is None:
        raise NotFound()
    # hat-scoped: the same tenant-wide kind the list above asks for — no
    # organization column, so `run` is handed over for the POLICY to read and
    # never as a node to resolve at. Reach is already answered ABOVE this line
    # by the tenant-scoped fetch that raised `NotFound` — reachability before
    # capability, house rule 26's order — which is what makes a foreign run
    # `not_found` rather than `forbidden`.
    # DATED, 2026-09-17, the v2.1 stopgap: reads of a tenant-wide kind are the
    # hat's on every door until v2.2 gives these kinds a home, and the rung that
    # homes this model deletes this valve
    # (the universal-homing proposal, 2026-09-17 — every record homed at a node).
    require(actor, READ_ACTION, run)
    return run
