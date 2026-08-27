

def _canary_purge_ledger(*, tenant, before):
    return CanaryLedgerEntry.objects.filter(created_at__lt=before).delete()
