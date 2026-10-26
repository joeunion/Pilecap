

# Planted: a private walk of the installed apps for a module of its own.
def canary_find_frob_modules(labels: list[str]) -> list[str]:
    """Every app shipping a `frobs` module, found by hand."""
    import importlib.util

    return [label for label in labels if importlib.util.find_spec(f"apps.{label}.frobs")]
