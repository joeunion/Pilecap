

# Planted: a queryset `.update(...)` on a `Versioned` noun — `auto_now` does not
# run on a queryset update, so every row it changes keeps its old version.


class ZzzVersionedBin(OrgScopedModel, Versioned):  # noqa: F821
    name = "a noun whose writes carry the version they were made against"


def zzz_rename_bins(pk: object, name: str) -> None:
    ZzzVersionedBin.objects.filter(pk=pk).update(name=name)
