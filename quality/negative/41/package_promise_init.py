"""A `services/` package that re-exports its member's service by name."""

from apps.zzz_canary.services.doohickeys import create_doohickey

__all__ = ["create_doohickey"]
