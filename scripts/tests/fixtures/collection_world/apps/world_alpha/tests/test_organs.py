"""A fixture-world module. Collected by the drives; never run by the suite."""

from temporalio.testing import WorkflowEnvironment


def test_world_alpha_reaches_the_minio_organ(world_bucket: str) -> None:
    assert world_bucket


def test_world_alpha_reaches_the_meili_organ(world_index: str) -> None:
    assert world_index


def test_world_alpha_names_the_temporal_entry_point() -> None:
    assert WorkflowEnvironment is not None
