
from typing import ClassVar as _CanaryMissingClassVar

from apps.core.lifecycle import Lifecycle as _CanaryMissingLifecycle
from apps.core.lifecycle import LifecycleKind as _CanaryMissingKind
from apps.core.models import BaseModel as _CanaryMissingBase


# The declaration passes every check the primitive can make at import: the kind
# is one of the four, `purged_by` is present and it is DOTTED, so
# `Lifecycle.__post_init__` lets it through. It names nothing that exists.
#
# A separate canary from the stranded one because it is a separate REPAIR — a
# path that does not resolve is a typo or a module that moved, and a path that
# resolves with no schedule behind it is a machine somebody forgot to declare.
# A rule that answered both with one sentence would send the second reader
# looking for a typo that is not there.
class CanaryPurgeIntoTheVoid(_CanaryMissingBase):
    """Declared purged, naming a callable that does not exist."""

    lifecycle: _CanaryMissingClassVar[_CanaryMissingLifecycle] = _CanaryMissingLifecycle(
        kind=_CanaryMissingKind.PURGED,
        purged_by="apps.example.nowhere_at_all.purge_the_canary",
    )

    expires_at = models.DateTimeField()
