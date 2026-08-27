"""A parent and a child workflow, and the shape they carry between them.

Not a `test_*.py` module, so pytest does not collect it — it exists to be
**imported into the workflow sandbox**, which is why it holds nothing but
stdlib dataclasses, `timedelta` and `temporalio.workflow`, exactly as a
production `workflows.py` must (house rule 9).

It exists because nothing in the tree starts a child workflow yet, and the
finding is precisely about children: `_WorkflowOutbound` stamped the tenant,
hat and correlation chain onto an outbound **activity** and onto nothing else,
so a child workflow — and a signal to one — shed all three in silence. Silence
is the bad part: a child that lost its tenant does not fail, it reads
`for_tenant(None)` and finds nothing.

The pair here is the smallest thing that can catch that: a parent started with
a tenant and a hat, a child that does no work of its own, and one activity that
says what it can see from inside the child.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow

REPORT_TIMEOUT = timedelta(seconds=30)


@dataclass
class SeenContext:
    """What an activity could see of the principal, as plain strings.

    Slugs and ids rather than rows, because this crosses a Temporal history.
    Empty string means "the activity saw nothing", which is the failure this
    fixture exists to make visible.
    """

    tenant_slug: str
    org_slug: str
    correlation_id: str


@workflow.defn(name="ChildContextWorkflow")
class ChildContextWorkflow:
    """The child: it asks an activity what the principal looks like from here."""

    #: No service asked for this run and no `WorkflowRun` row describes it — it
    #: is started by its parent. House rule 28's marker (ADR workflows-5).
    owns_no_run = True

    @workflow.run
    async def run(self, note: str) -> SeenContext:
        seen: SeenContext = await workflow.execute_activity(
            "report_workflow_context",
            note,
            start_to_close_timeout=REPORT_TIMEOUT,
            result_type=SeenContext,
        )
        return seen


@workflow.defn(name="ParentContextWorkflow")
class ParentContextWorkflow:
    """The parent: it starts the child and hands back what the child saw."""

    owns_no_run = True

    @workflow.run
    async def run(self, child_id: str) -> SeenContext:
        seen: SeenContext = await workflow.execute_child_workflow(
            "ChildContextWorkflow",
            "from the parent",
            id=child_id,
            result_type=SeenContext,
        )
        return seen
