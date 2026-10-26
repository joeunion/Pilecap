# A NAME THAT ENDS `_finish` AND CLOSES NOTHING. A suffix read honoured it: the
# run method calls `self._finish`, and `_finish` never reaches the finish
# activity, so the row says RUNNING for ever. The seam is a derived name.
@workflow.defn(name="CanarySuffixOnlyWorkflow")
class CanarySuffixOnlyWorkflow:
    """Calls a method named like the seam that is not the seam."""

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        announced: str = await workflow.execute_activity(
            "announce_widget",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        await self._finish(status="completed")
        return announced

    async def _finish(self, *, status: str) -> None:
        workflow.logger.info("finished as %s", status)


WORKFLOWS = [WidgetOnboardingWorkflow, CanarySuffixOnlyWorkflow]
