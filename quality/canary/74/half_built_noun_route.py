

# Planted: the half of the archive road that got drawn. `canary_bin-archive` is
# here and `canary_bin-restore` is not — the noun leaves the book one way and
# has no way back, which is the half a person needs on the day they need it.

from pydantic import Field as _Field74

from apps.core.schemas import ArchivedOut as _ArchivedOut74
from apps.core.schemas import example as _example74


class CanaryBinOut(_ArchivedOut74):
    """A bin, as the probe app would return one."""

    label: str = _Field74(json_schema_extra=_example74("spare parts"))


@router.post("/bins/{bin_id}/archive/", response=CanaryBinOut, url_name="canary_bin-archive")
def canary_bin_archive(request, bin_id: str):
    """Archive a bin

    Take one bin out of the book. It stays readable, and nothing restores it.
    """
    return CanaryBinOut(label="spare parts")
