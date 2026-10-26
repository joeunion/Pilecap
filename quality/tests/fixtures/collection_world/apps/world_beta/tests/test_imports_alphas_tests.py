"""A fixture-world module. Collected by the drives; never run by the suite."""

from apps.world_alpha.tests import test_lifecycle


def test_world_beta_imports_world_alphas_test_package() -> None:
    assert test_lifecycle is not None
