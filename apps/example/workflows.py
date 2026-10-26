# golden: workflow onboard begin
# golden: workflow remind begin
"""Durable work: one run waits for a human, one for a moment the row names."""

from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

from apps.example.types import (
    WidgetAnnouncement,
    WidgetMoment,
    WidgetOnboarded,
    WidgetOnboarding,
    WidgetReminded,
    WidgetReminder,
)
from pilecap.determinism import run_to_finish

#: One attempt at any activity: a short database read or write.
ACTIVITY_TIMEOUT = timedelta(seconds=30)

# golden: workflow remind end
#: How long somebody has to approve; a wait with no deadline never says nobody did.
APPROVAL_DEADLINE = timedelta(days=7)


@workflow.defn(name="WidgetOnboardingWorkflow")
class WidgetOnboardingWorkflow:
    """Mark a widget onboarded, wait for approval, then say what happened."""

    def __init__(self) -> None:
        self._approved = False

    @workflow.run
    async def run(self, onboarding: WidgetOnboarding) -> WidgetOnboarded:
        async def onboard() -> WidgetOnboarded:
            return await self._onboard(onboarding)

        onboarded, _tenant_slug = await run_to_finish(onboard)
        return onboarded

    async def _onboard(self, onboarding: WidgetOnboarding) -> WidgetOnboarded:
        """The work itself; `run_to_finish` closes the run's row around it (ADR workflows-7)."""
        onboarded_at: str = await workflow.execute_activity(
            "mark_widget_onboarded",
            onboarding,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )

        try:
            await workflow.wait_condition(lambda: self._approved, timeout=APPROVAL_DEADLINE)
        except TimeoutError:
            # Nobody approving is an outcome the announcement carries, never a failure.
            pass

        await workflow.execute_activity(
            "announce_widget_onboarded",
            WidgetAnnouncement(widget_id=onboarding.widget_id, approved=self._approved),
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return WidgetOnboarded(
            widget_id=onboarding.widget_id,
            onboarded_at=onboarded_at,
            approved=self._approved,
        )

    @workflow.signal(name="approve")
    def approve(self) -> None:
        """Somebody approved this widget; the deciding happens in `run`, where the history is."""
        self._approved = True


# golden: workflow onboard end
# golden: workflow remind begin
#: How long before the row's moment the reminder fires; `timedelta(0)` is at the moment itself.
REMIND_BEFORE = timedelta(0)


@workflow.defn(name="WidgetReminderWorkflow")
class WidgetReminderWorkflow:
    """Sleep until `due_at` less `REMIND_BEFORE`; remind once; close."""

    @workflow.run
    async def run(self, reminder: WidgetReminder) -> WidgetReminded:
        async def remind() -> WidgetReminded:
            return await self._remind(reminder)

        reminded, _tenant_slug = await run_to_finish(remind)
        return reminded

    async def _remind(self, reminder: WidgetReminder) -> WidgetReminded:
        """The work itself; `run_to_finish` closes the run's row around it (ADR workflows-7)."""
        while True:
            moment: WidgetMoment = await workflow.execute_activity(
                "read_widget_due_at",
                reminder,
                start_to_close_timeout=ACTIVITY_TIMEOUT,
                result_type=WidgetMoment,
            )
            if moment.until is None:
                return WidgetReminded(widget_id=reminder.widget_id, reminded_at="")
            wait = timedelta(seconds=moment.until - workflow.now().timestamp()) - REMIND_BEFORE
            if wait <= timedelta(0):
                break
            await workflow.sleep(wait)
        reminded_at: str = await workflow.execute_activity(
            "mark_widget_reminded",
            moment,
            start_to_close_timeout=ACTIVITY_TIMEOUT,
            result_type=str,
        )
        return WidgetReminded(widget_id=reminder.widget_id, reminded_at=reminded_at)


# golden: workflow remind end
# golden: workflow onboard begin
# golden: workflow remind begin
WORKFLOWS: list[type] = [
    # golden: workflow remind end
    WidgetOnboardingWorkflow,
    # golden: workflow onboard end
    # golden: workflow remind begin
    WidgetReminderWorkflow,
    # golden: workflow onboard begin
]
# golden: workflow remind end
# golden: workflow onboard end
