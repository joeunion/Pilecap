"""The colliding name again, on the silent side.

Same file as the canary's `vendor.py`: a vendor client function that is not a
service. It is here so the negative plants the identical two-module shape and
differs from the canary in exactly one thing — the door also calls the real
service.
"""

from __future__ import annotations


def deactivate_user(email: str) -> None:
    """Tell the identity platform. Writes no row of ours; it is not a service."""
