"""A fixture-world module. Collected by the drives; never run by the suite."""

import os


def test_world_gamma_reads_the_absent_world() -> None:
    assert os.environ.get("DJB_DISABLED_APPS", "") is not None
