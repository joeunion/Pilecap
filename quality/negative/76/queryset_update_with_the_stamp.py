

# The legal shape: a queryset update that moves the stamp itself.


class ZzzVersionedBin(OrgScopedModel, Versioned):  # noqa: F821
    name = "a noun whose writes carry the version they were made against"


def zzz_rename_bins(pk: object, name: str, now: object) -> None:
    ZzzVersionedBin.objects.filter(pk=pk).update(name=name, updated_at=now)
