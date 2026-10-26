

# Planted: the same walk spelled as an import of each app's module.
def canary_import_frob_modules(labels: list[str]) -> list[object]:
    """Every app's `frobs` module, imported by hand."""
    from importlib import import_module

    return [import_module(f"apps.{label}.frobs") for label in labels]
