

# The four DOMAIN apps' seam: a `_finish` method on the class, called last on
# both ways out — `failed` with the cause on the exception path, `completed`
# after the work returned. Two shapes are live in this tree and both are right;
# a rule that insisted on one would have made four apps rewrite a seam that
# already works, which is how a house rule turns into a house style.
@workflow.defn(name="NegMethodFinishWorkflow")
class NegMethodFinishWorkflow:
    """Closes its run through its own method."""

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> str:
        try:
            announced: str = await workflow.execute_activity(
                "announce_widget",
                onboarding,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                result_type=str,
            )
        except Exception as error:
            await self._finish(status=RUN_FAILED, error=str(error))
            raise
        await self._finish(status=RUN_COMPLETED)
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


WORKFLOWS = [WidgetOnboardingWorkflow, NegMethodFinishWorkflow]
