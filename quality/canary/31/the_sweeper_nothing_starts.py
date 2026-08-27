

# The other half of the stranded-purge plant: a real, importable sweeper that no
# activity references and therefore no workflow executes and therefore no
# `ScheduleDeclaration` reaches. Written the way somebody genuinely writes one —
# which is the point: nothing about this function is wrong, and the defect is
# entirely in what is missing beside it.
def purge_canary_stranded_rows(*, before=None) -> int:
    from apps.example.models import CanaryStrandedPurge

    return CanaryStrandedPurge.objects.filter(expires_at__lt=before).delete()[0]
