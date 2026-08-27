"""The colliding name: a vendor client function, not a service.

`apps/accounts/zitadel.py` is the real one. It exists here so the census has a
first-party module to resolve `vendor.deactivate_user` TO — which is the whole
of the fix: the call resolves to `apps.zzz_canary.vendor`, and a service in
`apps.zzz_canary.services` is a different qualified name.
"""

from __future__ import annotations


def deactivate_user(email: str) -> None:
    """Tell the identity platform. Writes no row of ours; it is not a service."""
