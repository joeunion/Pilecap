

# The declaration half, tested for meaning rather than for presence: the
# attribute is there and it says False. A check that looked for the NAME
# `owns_no_run` — or for the string in the file — would pass this, and the
# valve would be open to anybody who typed the word once. It is `= True` that
# is the declaration; anything else is a workflow that owns a run row and does
# not close it.
@workflow.defn(name="CanaryFalseDeclarationWorkflow")
class CanaryFalseDeclarationWorkflow:
    """Says owns_no_run — and says False."""

    owns_no_run = False

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        announced: str = await workflow.execute_activity(
            "announce_widget",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return announced


WORKFLOWS = [WidgetOnboardingWorkflow, CanaryFalseDeclarationWorkflow]
