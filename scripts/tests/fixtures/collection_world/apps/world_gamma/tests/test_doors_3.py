"""A fixture-world module. Collected by the drives; never run by the suite."""

DOOR_PAIR = ("rest", "mcp")


def test_world_gamma_doors_3_answer_alike() -> None:
    assert DOOR_PAIR == ("rest", "mcp")
