"""The fixture world's own organ fixtures.

The organ tier is derived from the `@organ(...)` attribute a fixture
carries, so a world that must satisfy the organ floors declares its own
rather than reaching into an app the drives no longer collect.
"""

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
