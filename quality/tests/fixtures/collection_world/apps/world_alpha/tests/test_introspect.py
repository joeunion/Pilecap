"""A fixture-world module. Collected by the drives; never run by the suite."""

import importlib


def test_world_alpha_reads_the_introspect_registry() -> None:
    module = "apps.core.management.commands.introspect"
    assert importlib.util.find_spec(module) is not None
