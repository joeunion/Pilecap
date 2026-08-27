"""Negative: the scoped model's admin inherits ServiceModelAdmin."""

from django.contrib import admin

from apps.core.admin import ServiceModelAdmin
from apps.zzz_canary.models import GoodScoped


@admin.register(GoodScoped)
class GoodScopedAdmin(ServiceModelAdmin):
    pass
