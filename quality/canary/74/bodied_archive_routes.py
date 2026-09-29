

# Planted: the archive road, drawn with a required empty body — a bodiless press
# answers 422, a door disagreement with every other adopter.

from apps.core.schemas import ArchivedOut as _ArchivedOut74m
from apps.core.schemas import StrictIn as _StrictIn74m


class CanaryHamperOut(_ArchivedOut74m):
    """A hamper, as the probe app would return one."""


class CanaryHamperPressIn(_StrictIn74m):
    """An empty body the press should never have needed."""


@router.post(
    "/hampers/{hamper_id}/archive/", response=CanaryHamperOut, url_name="canary_hamper-archive"
)
def canary_hamper_archive(request, hamper_id: str, payload: CanaryHamperPressIn):
    """Archive a hamper

    Take one hamper out of the book.
    """
    return CanaryHamperOut()


@router.post(
    "/hampers/{hamper_id}/restore/", response=CanaryHamperOut, url_name="canary_hamper-restore"
)
def canary_hamper_restore(request, hamper_id: str, payload: CanaryHamperPressIn):
    """Restore a hamper

    Put one archived hamper back in the book.
    """
    return CanaryHamperOut()
