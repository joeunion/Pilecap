from apps.zzz_other.selectors import listing


# Legal: another product app is rule 7's business, never this rule's.
def borrowed() -> object:
    return listing
