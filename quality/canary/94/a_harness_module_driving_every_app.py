"""A harness module whose declaration covers every app — a product's code among them."""

import pytest

pytestmark = pytest.mark.drives("apps/")


def test_it_reads_one_app() -> None:
    assert True
