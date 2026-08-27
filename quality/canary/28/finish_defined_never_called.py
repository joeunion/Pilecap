

# The subtle half, and the reason the question is asked of the `@workflow.run`
# method rather than of the class body: this workflow HAS the seam. It defines
# `_finish` exactly the way the four domain apps do — correct, careful, with
# the bounded retry — and `run()` never calls it. A scanner that searched the
# whole class would read the definition as a reference and pass a workflow
# whose rows are every bit as stuck as one with no seam at all.
@workflow.defn(name="CanaryDefinedNotCalledWorkflow")
class CanaryDefinedNotCalledWorkflow:
    """Has a finish seam. Never reaches it."""

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        announced: str = await workflow.execute_activity(
            "announce_widget",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return announced

    async def _finish(self, *, status: str, error: str = "") -> None:
        await workflow.execute_activity(
            FINISH_ACTIVITY,
            RunFinished(
                workflow_id=workflow.info().workflow_id,
                status=status,
                error=error,
            ),
            start_to_close_timeout=FINISH_TIMEOUT,
            retry_policy=FINISH_RETRY,
        )


WORKFLOWS = [WidgetOnboardingWorkflow, CanaryDefinedNotCalledWorkflow]
