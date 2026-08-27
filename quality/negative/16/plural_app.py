from django.apps import AppConfig


class GizmosConfig(AppConfig):  # negative: plural, and not on any exemption list
    name = "apps.gizmos"
    depends_on: tuple[str, ...] = ("core",)
