"""A workflow that waits until somebody stops it, over the real finish seam.

Not a `test_*.py` module, so pytest does not collect it — like `childwork.py`
it exists to be **imported into the workflow sandbox**, and holds nothing but
`temporalio.workflow`, the app's own deterministic seam and stdlib.

It exists because nothing in the tree waits. `EchoWorkflow` returns inside one
activity, `SendEmailWorkflow` and `MoveOrganizationWorkflow` are one activity
each, and a run that has already finished cannot be cancelled — so there was no
execution a cancel test could point at. This is the smallest one there is: it
waits on a condition that is never true, wrapped in the **production**
`run_to_finish`, which is the whole point. A test workflow with a hand-written
cancellation branch would prove the branch this file wrote; this one proves the
branch `apps/core/determinism.py` ships, which is the seam every real
workflow in the app goes through (ADR workflows-7).

`owns_no_run` is deliberately absent: this run DOES own a `WorkflowRun` row —
the test records one — and the whole assertion is about what that row says
afterwards.
"""

from __future__ import annotations

from temporalio import workflow

from apps.core.determinism import run_to_finish


@workflow.defn(name="WaitForeverWorkflow")
class WaitForeverWorkflow:
    """Wait for a condition that never comes, and let `run_to_finish` do the rest."""

    @workflow.run
    async def run(self, note: str) -> str:
        async def wait() -> str:
            await workflow.wait_condition(lambda: False)
            return note

        echoed, _tenant_slug = await run_to_finish(wait)
        return echoed
