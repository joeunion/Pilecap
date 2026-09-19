"""A fixture-world module. Collected by the drives; never run by the suite."""

from django.apps import apps as django_apps


def test_world_beta_tests_lifecycle() -> None:
    models = list(django_apps.get_models())
    assert models is not None
