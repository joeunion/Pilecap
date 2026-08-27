

def _neg_purge_ordinary(*, tenant, before):
    return CanaryOrdinaryEntry.objects.filter(created_at__lt=before).delete()
