

# The other real population, declared out loud on the class where a reviewer
# meets it: a workflow started by a Temporal SCHEDULE has no `WorkflowRun` row
# to close, because no service asked for it and nobody is waiting on a
# visibility row for the deployment's own housekeeping. Refusing this shape
# would push the deployment's schedules into writing fake run rows to satisfy a
# rule — a worse lie than the one rule 28 exists to stop.
@workflow.defn(name="NegScheduledHousekeepingWorkflow")
class NegScheduledHousekeepingWorkflow:
    """Schedule-started; owns no run row, and says so."""

    owns_no_run = True

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        swept: str = await workflow.execute_activity(
            "announce_widget",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return swept


WORKFLOWS = [WidgetOnboardingWorkflow, NegScheduledHousekeepingWorkflow]
