from django.apps import AppConfig


class GadgetConfig(AppConfig):  # planted: an app named for one thing
    name = "apps.gadget"
    depends_on: tuple[str, ...] = ("core",)
