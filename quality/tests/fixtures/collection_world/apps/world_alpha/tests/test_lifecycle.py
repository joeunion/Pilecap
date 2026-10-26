"""A fixture-world module. Collected by the drives; never run by the suite."""

from django.apps import apps as django_apps

OPENAPI_READER = "get_openapi_schema("  # openapi_document_readers
INTROSPECT_READER = "management.commands.introspect"  # introspect_registry_readers


def test_world_alpha_tests_lifecycle() -> None:
    models = list(django_apps.get_models())
    assert models is not None
