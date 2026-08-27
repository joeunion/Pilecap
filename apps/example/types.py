"""The shapes that cross this app's workflow boundary.

Plain dataclasses in a module that imports nothing but the standard library,
because everything here is serialised into Temporal's history and replayed from
it — possibly years later, by a worker running code nobody has looked at since.
A workflow argument that was a `Widget` could not be replayed at all: the row
may have changed, or gone.

The ids are strings rather than `UUID`s for the same reason: what comes back out
of history is JSON, and a string that is parsed once, in the activity, at the
edge of the database, is one conversion in one place instead of a converter
somebody has to keep registered for the life of the product.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RunFinished:
    """What `mark_run_finished` is told when this app's workflow ends.

    The activity belongs to `apps.workflows` and is invoked **by name**, which
    is how every activity is invoked (house rule 9) — so the shape crosses the
    boundary and the class does not. It is restated here rather than imported
    for the same reason `apps.core.bridge` exists: a workflow module may import
    its own `types.py` and nothing else, and `apps.events` may not import
    `apps.workflows` at all. Keep the three fields matching
    `apps.workflows.types.MarkRunFinished`; the worker deserialises into that.
    """

    workflow_id: str
    status: str
    error: str = ""


@dataclass
class WidgetOnboarding:
    """What `WidgetOnboardingWorkflow` is started with.

    The tenant is deliberately not here: it rides on the workflow's headers
    (`apps.workflows.context`) and is restored inside the activity, so no caller
    can name somebody else's tenant by putting the wrong id in a payload.
    """

    widget_id: str


@dataclass
class WidgetAnnouncement:
    """What the announcing activity is told: which widget, and how it ended."""

    widget_id: str
    approved: bool


@dataclass
class WidgetOnboarded:
    """What the workflow returns: the durable facts about the run.

    `approved` is `False` when nobody signalled in time. That is an outcome, not
    an error — a widget nobody approved is still onboarded, and the difference is
    exactly what the event payload carries to whoever is listening.
    """

    widget_id: str
    onboarded_at: str
    approved: bool
