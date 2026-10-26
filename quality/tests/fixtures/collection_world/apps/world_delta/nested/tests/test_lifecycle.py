"""A fixture-world module. Collected by the drives; never run by the suite."""

from django.apps import apps as django_apps

DOOR_PAIR = ("rest", "mcp")  # door_parity_census
OPENAPI_READER = "get_openapi_schema("  # openapi_document_readers


def test_world_delta_nested_tests_lifecycle() -> None:
    models = list(django_apps.get_models())
    assert models is not None
