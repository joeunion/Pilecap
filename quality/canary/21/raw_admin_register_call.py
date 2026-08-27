

from apps.zzz_canary.models import CanaryLedger


class CanaryLedgerAdmin(admin.ModelAdmin):
    pass


admin.site.register(CanaryLedger, CanaryLedgerAdmin)
