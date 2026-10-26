"""A harness module whose declaration names the one app it reads."""

import pytest

pytestmark = pytest.mark.drives("apps/example/**")


def test_it_reads_the_example() -> None:
    assert True
