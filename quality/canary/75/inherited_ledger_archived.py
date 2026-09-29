

class ZzzArchivedAuditEntry(AuditEntry, Archivable):  # noqa: F821
    class Meta:
        proxy = True
