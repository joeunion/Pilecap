"""`manage.py`-free census printers for the token ceiling (ADR ident-7).

The numbers the quality batch will ratchet from, produced by the same functions
the tests assert on rather than by a second walk that could disagree with them.
Run it as a module when you want the measurement rather than the verdict:

    uv run python -m apps.core.tests.scope_census

It is under `tests/` because that is where the two censuses it prints already
live, and it imports the mount the way a test may (the import-linter contract
exempts `apps.*.tests.*` for exactly this: reading a mount to report what it
found, rather than testing a stand-in for it).
"""

from __future__ import annotations


def print_census() -> None:
    """Both censuses, on stdout.

    Everything is imported inside the function: this module is run as a script
    against a settings module, so the app registry is not ready at import time
    and anything reaching the ORM from module scope would die before `setup()`.
    """
    import django

    django.setup()
    from apps.core.mcp import tool_scopes
    from apps.core.tests.test_scope_readers import DECLARED_READERS, measured_readers
    from config.mcp import server

    scopes = tool_scopes(server)
    declared = sorted(name for name, scope in scopes.items() if scope is None)
    print(f"tools registered:            {len(scopes)}")
    print(f"  derived a required scope:  {len(scopes) - len(declared)}")
    print(f"  declared no capability:    {len(declared)}  {declared}")
    print()

    readers = measured_readers()
    print(f"modules reading the ceiling: {len(readers)}")
    for name in sorted(readers):
        why = DECLARED_READERS.get(name, "UNDECLARED")
        print(f"  {name}  — {why}")
        for read in readers[name]:
            print(f"      {read}")


if __name__ == "__main__":  # pragma: no cover - a reporting entry point
    print_census()
