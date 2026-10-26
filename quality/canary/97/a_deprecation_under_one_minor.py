"""Planted: a deprecation served for less than one minor release."""

from pilecap._deprecated import Deprecation

__all__: list[str] = []

DEPRECATED = {"zz_old": Deprecation(since="2.5.0", until="2.5.1", instead="Actor", kind="renamed")}
