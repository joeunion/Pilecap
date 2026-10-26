"""The fixture world's own organ fixtures."""

import pytest

from apps.conftest import organ


@pytest.fixture
@organ("minio")
def world_bucket() -> str:
    return "a fixture-world bucket that no test ever reaches"


@pytest.fixture
@organ("meili")
def world_index() -> str:
    return "a fixture-world index that no test ever reaches"
