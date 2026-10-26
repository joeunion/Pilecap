

from datetime import timedelta as _canary_timedelta

from temporalio import workflow as _canary_workflow

from apps.example.workflows import WORKFLOWS as _CANARY_WORKFLOWS


# Planted: the workflow a `daily_purge` declaration names, executing the planted sweep's activity.
@_canary_workflow.defn(name="canary_reached_sweep_workflow")
class CanaryReachedSweepWorkflow:
    """Run the planted sweep."""

    owns_no_run = True

    @_canary_workflow.run
    async def run(self, arg: None) -> None:
        """Execute the planted activity."""
        await _canary_workflow.execute_activity(
            "canary_reached_sweep_activity", start_to_close_timeout=_canary_timedelta(minutes=1)
        )


_CANARY_WORKFLOWS.append(CanaryReachedSweepWorkflow)
