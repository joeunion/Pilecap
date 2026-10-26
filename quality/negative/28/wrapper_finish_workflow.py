# The PLATFORM app's seam, planted in a domain app: the workflow seam module's
# `run_to_finish`, which takes the work as a callable, runs it first, and marks
# the row after. It never names `mark_run_finished` at this level — the seam
# does, one layer down — so a rule that asked for the activity name would have
# refused `apps/workflows/workflows.py`, which is the module that USES the
# right shape. The seam is recognised by its NAME, derived from the seam
# module, never by a suffix.
from apps.core.determinism import run_to_finish  # noqa: E402


@workflow.defn(name="NegWrapperFinishWorkflow")
class NegWrapperFinishWorkflow:
    """Closes its run through the module-level wrapper."""

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        async def announce() -> str:
            said: str = await workflow.execute_activity(
                "announce_widget",
                onboarding,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                result_type=str,
            )
            return said

        announced, _tenant_slug = await run_to_finish(announce)
        return announced


WORKFLOWS = [WidgetOnboardingWorkflow, NegWrapperFinishWorkflow]
