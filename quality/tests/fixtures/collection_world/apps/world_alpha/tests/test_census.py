# census: cross-app it walks the fixture world's own source tree by path
"""A fixture-world module. Collected by the drives; never run by the suite."""

import pathlib

CENSUS_SEEDED_BY = ("policies",)


def test_world_alpha_walks_the_source_tree() -> None:
    here = pathlib.Path(__file__).parent
    assert list(here.rglob("*.py"))
