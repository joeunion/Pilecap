"""Reading the run ledger. Two questions, one scoping rule, no writes.

`WorkflowRun` is `TenantScopedModel` and not `OrgScopedModel` — a run has a
tenant and an id and no idea which part of the tenant its work was about, which
is the same fact `policies.py` is built on — so the read is `for_tenant(...)`
and there is no `visible_to` half to chain (rule 24 governs org-scoped models;
this one is not, and pretending otherwise would put a hat on a row that has
none).

**These selectors authorize, and that is unusual enough to say why.** Every
other read in the tree is gated by the tenant wall alone. The run ledger is the
product's record of what it did on people's behalf, ADR workflows-6 gates it on
`workflowrun.read`, and the check has to live below the doors or the REST route,
the MCP tool and whatever comes next each get their own copy of it — which is
exactly the drift `core.authz`'s docstring opens with. `require` reads; it
writes nothing, so rule 12's line holds.
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
    """
    require(actor, READ_ACTION)
    run = (
        WorkflowRun.objects.for_tenant(tenant)
        .select_related("started_by")
        .filter(pk=run_id)
        .first()
    )
    if run is None:
        raise NotFound()
    return run
