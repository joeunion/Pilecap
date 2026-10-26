# The seam's other name: `finish_run`, called LAST by the run method itself. A
# suffix read (`*_finish`) never saw it; the derived seam names do.
from apps.core.determinism import COMPLETED, finish_run  # noqa: E402


@workflow.defn(name="NegFinishRunWorkflow")
class NegFinishRunWorkflow:
    """Does its work, then closes its run through the seam module's `finish_run`."""

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        announced: str = await workflow.execute_activity(
            "announce_widget",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        await finish_run(status=COMPLETED)
        return announced


WORKFLOWS = [WidgetOnboardingWorkflow, NegFinishRunWorkflow]
