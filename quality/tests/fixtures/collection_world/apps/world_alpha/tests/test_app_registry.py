"""A fixture-world module. Collected by the drives; never run by the suite."""

from django.apps import apps as django_apps


def test_world_alpha_reads_the_app_registry() -> None:
    assert list(django_apps.get_app_configs())
