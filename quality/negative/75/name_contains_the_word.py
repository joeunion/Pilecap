

class ArchivableView:
    """Not the mixin: a name that merely contains the word."""


class ZzzLedgerWithAView(OrgScopedModel, ArchivableView):  # noqa: F821
    append_only = True
