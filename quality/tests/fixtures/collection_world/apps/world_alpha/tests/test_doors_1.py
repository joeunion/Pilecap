"""A fixture-world module. Collected by the drives; never run by the suite."""

OPENAPI_READER = "get_openapi_schema("  # openapi_document_readers
MCP_READER = "_list_tools("  # mcp_catalogue_readers

DOOR_PAIR = ("rest", "mcp")


def test_world_alpha_doors_1_answer_alike() -> None:
    assert DOOR_PAIR == ("rest", "mcp")
