"""The note: a piece of prose about one row of some other noun.

One model. Its subject is a polymorphic pointer — a kind from the
authorization vocabulary and the subject row's id — and its organization is
the subject's (see `services.create_note`), so the note is visible to exactly
the hats that can see what it is about.
"""

from __future__ import annotations

from typing import ClassVar

from django.conf import settings
from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import Archivable, OrgScopedModel

#: The separator between a subject's kind and its id on the wire:
#: `widget:3f0c…`. One character, and never one a kind can contain (kinds are
#: snake_case identifiers).
SUBJECT_SEPARATOR = ":"


class Note(OrgScopedModel, Archivable):
    """Prose one person wrote about one row of another noun.

    **Archived, never deleted.** A note leaves the book by being archived
    (`Archivable`), and there is no delete: a note may be the only record of why
    something was done, and an administrator taking it out of view is a
    different act from destroying it.

    **Edited by its author alone** (`policies.is_author`), and not versioned:
    the only party a note's edit can race is the same person in another tab.
    """

    #: ADR core-13, the reasoned kind. Notes are archived rather than deleted,
    #: so the table only grows.
    lifecycle: ClassVar[Lifecycle] = Lifecycle(
        kind=LifecycleKind.UNBOUNDED,
        reason=(
            "a note is somebody's record of why something was done, and it leaves the "
            "book by being archived, never deleted — so the table grows with the "
            "product's own history, one row per thing a person chose to write down."
        ),
        trigger=(
            "2026-09-27 — the first of: a product that hard-deletes a subject noun "
            "(its notes are then orphans a purge reacting to that noun's `deleted` "
            "event must remove, with its `ScheduleDeclaration` in the same commit), "
            "or a stated retention obligation on notes."
        ),
    )

    #: The subject's kind — the authorization vocabulary's word for its model
    #: (`core.authz.kind_of`), resolved through `core.authz.kind_registry()`.
    subject_kind = models.CharField(max_length=64)
    #: The subject row's primary key. Not a foreign key, on purpose — see the
    #: app's docstring for the price and why it is paid.
    subject_id = models.UUIDField()
    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Who wrote this. The one person who may edit it.",
    )

    class Meta(OrgScopedModel.Meta):
        verbose_name = "note"
        verbose_name_plural = "notes"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(subject_kind=""),
                name="note_subject_kind_not_empty",
            ),
        ]
        # DECLARING `indexes` HERE SHADOWS THE ABSTRACT BASE'S (house rule 37),
        # so the tenant-leading recency composite is re-added by hand, under the
        # name the base would have given it.
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="note_recency"),
            # The one read road: every list is "the notes of THIS subject".
            models.Index(
                fields=["tenant", "subject_kind", "subject_id", "-created_at"],
                name="note_subject_recency",
            ),
        ]

    def __str__(self) -> str:
        return f"note on {self.subject}"

    @property
    def subject(self) -> str:
        """The pointer as the wire spells it: `<kind>:<id>`."""
        return f"{self.subject_kind}{SUBJECT_SEPARATOR}{self.subject_id}"

    @property
    def author_email(self) -> str:
        """Who wrote this, without the caller fetching the author. Selected by every read."""
        return str(self.author.email)
