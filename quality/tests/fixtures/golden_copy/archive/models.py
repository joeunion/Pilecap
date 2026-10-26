"""The self-case's model block, as a worked example would fence it."""

# golden: archive version begin
# golden-copy-two-verb-fence: one block, fenced for two verbs; the archive copy takes it.
from typing import ClassVar

from django.db import models

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.core.models import Archivable, OrgScopedModel


class Widget(OrgScopedModel, Archivable):
    """A widget: it leaves the book by being archived and comes back by a restore."""

    name = models.CharField(max_length=200)

    lifecycle: ClassVar[Lifecycle] = Lifecycle(kind=LifecycleKind.BOUNDED)

    def __str__(self) -> str:
        return self.name


# golden: archive version end
