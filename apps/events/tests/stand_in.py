"""The resolver pytest's settings name: every host is one public address, and nothing dials DNS."""

from __future__ import annotations

#: What every stood-in host resolves to: a public address, so a test's subscriber is deliverable.
PUBLIC_ADDRESS = "93.184.215.14"


def resolve_public(host: str) -> list[str]:
    """`[PUBLIC_ADDRESS]` for any `host`."""
    return [PUBLIC_ADDRESS]
