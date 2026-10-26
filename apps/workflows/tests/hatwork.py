"""A run that acts twice, with a wait between, so a hat can be taken away mid-run.

Not a `test_*.py` module, so pytest does not collect it — it exists to be
**imported into the workflow sandbox**, which is why it holds nothing but
stdlib, `temporalio.workflow` and this app's own sandbox-safe workflow module,
exactly as a production `workflows.py` must (house rule 9).

The property it makes visible: the acting hat rides on the run's headers from
the moment the run starts, and a person can lose that hat while the run is
waiting. The first activity acts under a hat the person still holds; the test
revokes it; the signal lets the second activity go. Whatever the second
activity does is what the product does to a person who no longer holds a role.
"""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

from apps.core.determinism import run_to_finish

ACT_TIMEOUT = timedelta(seconds=30)


@workflow.defn(name="RevokedHatWorkflow")
class RevokedHatWorkflow:
    """Act, wait for `proceed`, act again — and close the run row whichever way."""

    def __init__(self) -> None:
        self._proceed = False

    @workflow.run
    async def run(self, note: str) -> str:
        async def act_twice() -> str:
            first: str = await workflow.execute_activity(
                "act_under_the_hat",
                f"{note}:first",
                start_to_close_timeout=ACT_TIMEOUT,
                result_type=str,
            )
            await workflow.wait_condition(lambda: self._proceed)
            second: str = await workflow.execute_activity(
                "act_under_the_hat",
                f"{note}:second",
                start_to_close_timeout=ACT_TIMEOUT,
                result_type=str,
            )
            return f"{first},{second}"

        acted, _tenant_slug = await run_to_finish(act_twice)
        return acted

    @workflow.signal(name="proceed")
    def proceed(self) -> None:
        """Let the second activity go. Setting a flag is all a handler does."""
        self._proceed = True
