

# The shape the rule asks for: the one discovery road, and an ordinary import.
def neg_frobs_through_the_road() -> list[object]:
    """Every app's `FROBS`, through the discovery road."""
    from importlib import import_module

    from apps.core.discovery import declared

    import_module("json")
    return [value for _config, value in declared("frobs", "FROBS")]
