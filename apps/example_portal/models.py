"""The customer's one noun: a request about a widget.

One model. It lands at the acting hat — the customer's own node — and names the
widget it is about by a foreign key that PROTECTs, so a widget somebody asked
about cannot vanish from under the question.
"""

from __future__ import annotations

# golden: portal begin
from typing import ClassVar

from django.conf import settings
from django.db import models

from pilecap import Lifecycle, LifecycleKind, OrgScopedModel


class PortalRequest(OrgScopedModel):
    """Something a customer asked about one widget, in their own words.

    **Homed at the asker's hat**, never at the widget's node: a request is the
    customer's record and lands where the customer acts, which is the placement
    law for a row that chooses its own (ADR core-20) — so the customer reads it
    back from where they stand, and a staff reader above that node reads it too.

    **The widget is named, never owned.** `PROTECT`, because "which widget was
    this about" must stay answerable for as long as the request exists; the
    widget is read through `apps.example.selectors.get_widget`, never through
    this relation, so the portal learns nothing of the staff noun's shape.
    """

    #: ADR core-13, the reasoned kind. A request is never deleted.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a request is what a customer asked, and the record of it is the product's "
            "answer to 'when did they tell us' — the table grows with the conversation, "
            "one row per question a person chose to send."
        ),
        trigger=(
            "2026-09-30 — the first of: a product that closes or resolves requests (a "
            "state column, and a retention rule for the closed ones with its "
            "`ScheduleDeclaration` in the same commit), or a stated retention "
            "obligation on customer correspondence."
        ),
    )

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        NORMAL = "normal", "Normal"
        HIGH = "high", "High"

    widget = models.ForeignKey(
        "example.Widget",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="The widget this request is about.",
    )
    note = models.TextField(help_text="What the customer asked, in their own words.")
    priority = models.CharField(
        max_length=8,
        choices=Priority.choices,
        default=Priority.NORMAL,
        help_text="How soon the customer needs an answer.",
    )
    #: Who asked. `PROTECT` for the reason every author field here gives:
    #: erasure anonymises a person and keeps the row, so the reference stays
    #: valid; a hard delete that would orphan the question is refused.
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="The person who asked.",
    )

    class Meta(OrgScopedModel.Meta):
        verbose_name = "portal request"
        verbose_name_plural = "portal requests"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(note=""),
                name="example_portal_portalrequest_note_not_empty",
            ),
        ]

    def __str__(self) -> str:
        return f"request about widget {self.widget_id}"

    @property
    def requester_email(self) -> str:
        """Who asked, without the caller fetching the person. Selected by every read."""
        return str(self.requester.email)


# golden: portal end
