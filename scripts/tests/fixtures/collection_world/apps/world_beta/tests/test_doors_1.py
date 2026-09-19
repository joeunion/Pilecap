"""A fixture-world module. Collected by the drives; never run by the suite."""

DOOR_PAIR = ("rest", "mcp")


def test_world_beta_doors_1_answer_alike() -> None:
    assert DOOR_PAIR == ("rest", "mcp")
