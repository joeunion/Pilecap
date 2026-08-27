from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.zzz_canary"
    depends_on: tuple[str, ...] = ("core", "accounts")
