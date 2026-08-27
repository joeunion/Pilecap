"""Negative: search.py is canonical in every app .

`apps/<x>/search.py` is the filename `apps.search.registry`'s discovery seam
requires of an adopting app (`registry.DECLARATION_MODULE`), so an app that
declares what it makes findable must be able to carry this file WITHOUT an
entry in rule 11's `extra_modules`. Before the promotion this fixture fired
djb.E011 and the documented adoption path was boot-refused.

The declaration list is empty on purpose: this fixture proves the FILENAME is
allowed, and a probe app declaring a real model would be asserting the
registry's job instead of rule 11's.
"""

from apps.search.types import Searchable

SEARCHABLES: list[Searchable] = []
