"""Planted: a raw ModelAdmin on a scoped model."""

from django.contrib import admin

from apps.zzz_canary.models import CanaryScoped


@admin.register(CanaryScoped)
class CanaryScopedAdmin(admin.ModelAdmin):
    pass
