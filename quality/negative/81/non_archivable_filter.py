

# A column named like the archive's on a class that never declared `Archivable`:
# rule 74's bare-column clause owns that shape, and this rule stays silent.
def _negative81_not_archivable(tenant):  # noqa: ANN001, ANN202
    return WidgetEntry.objects.for_tenant(tenant).filter(archived_at__isnull=False)  # noqa: F821
