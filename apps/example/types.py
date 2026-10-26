# golden: workflow onboard begin
# golden: workflow remind begin
"""The shapes that cross the workflow boundary: standard-library dataclasses only (rule 9)."""

from __future__ import annotations

from dataclasses import dataclass

# golden: workflow remind end


@dataclass
class WidgetOnboarding:
    """What `WidgetOnboardingWorkflow` is started with."""

    widget_id: str


@dataclass
class WidgetAnnouncement:
    """What the announcing activity is told: which widget, and how it ended."""

    widget_id: str
    approved: bool


@dataclass
class WidgetOnboarded:
    """What the workflow returns; `approved` is `False` when nobody signalled in time."""

    widget_id: str
    onboarded_at: str
    approved: bool


# golden: workflow onboard end
# golden: workflow remind begin
@dataclass
class WidgetReminder:
    """What `WidgetReminderWorkflow` is started with: the row, never its moment."""

    widget_id: str


@dataclass
class WidgetMoment:
    """The row's `due_at` as epoch seconds; `None` once it is cleared."""

    widget_id: str
    until: float | None


@dataclass
class WidgetReminded:
    """What the reminder returns; `reminded_at` is empty when the moment was cleared first."""

    widget_id: str
    reminded_at: str


# golden: workflow remind end
