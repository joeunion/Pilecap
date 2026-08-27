

# The ordinary shape rule 28 exists for, and the one the platform app itself
# shipped for months: a workflow that does its work and returns. The service
# that started it wrote a `WorkflowRun` row saying `running`; nothing here ever
# says otherwise; the row says `running` for ever, and no reader — not the
# admin, not a selector, not W4's reconciler — can tell it from a live one.
@workflow.defn(name="CanaryUnclosedWorkflow")
class CanaryUnclosedWorkflow:
    """Registered on the worker, closes nothing."""

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        announced: str = await workflow.execute_activity(
            "announce_widget",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return announced


WORKFLOWS = [WidgetOnboardingWorkflow, CanaryUnclosedWorkflow]
