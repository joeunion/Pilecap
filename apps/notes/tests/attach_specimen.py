"""The attach hook core's conformance tests import: write one note about a subject.

`attach(*, tenant, actor, subject)` writes THIS app's row about `subject` through
the service that really writes it (`create_note`), as `actor`, and answers the
row — so core's repointer and landing-law conformance tests can plant a note on
any noun without knowing how notes are made. The subject's model must already
take notes (`attachments` lists `"notes"`); the caller declares that, not this
hook. The actor must be a person: a note is somebody's words.
"""

from __future__ import annotations

from typing import Any

from apps.core.actor import Actor
from apps.core.authz import kind_of
from apps.core.models import Tenant
from apps.notes.models import Note
from apps.notes.services import create_note

#: The words every specimen note carries.
SPECIMEN_BODY = "Specimen"


def attach(*, tenant: Tenant, actor: Actor, subject: Any) -> Note:
    """Write the specimen note about `subject` as `actor`; answer the note."""
    pointer = f"{kind_of(type(subject))}:{subject.pk}"
    return create_note(tenant=tenant, actor=actor, subject=pointer, body=SPECIMEN_BODY)
