"""The one tolerant read for every census that walks the source tree.

A file listed by the walk and unlinked by another worker before `open()` reads as no source.
Only `FileNotFoundError` is tolerated: an undecodable or unparseable file is still a finding.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings


def source_text(path: Path) -> str:
    """Every byte of `path` — or nothing at all, if it vanished mid-census.

    See this module's docstring for the race and for why an empty answer is the
    honest one rather than a swallowed error.
    """
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        # SKIPPED: listed by the walk, gone by the time it was opened — another
        # xdist worker's plant. A file that does not exist cannot violate a
        # rule, so "no source" is the answer, not an exception.
        return ""


def source_lines(path: Path) -> list[str]:
    """`source_text` split into lines — `[]` for a file that vanished."""
    return source_text(path).splitlines()


def source_tree(path: Path) -> ast.Module:
    """`path` parsed — an EMPTY module for a file that vanished mid-census.

    `ast.walk` over an empty module yields the module and nothing else, so
    every census keyed on finding nodes gets its honest "nothing here".
    A `SyntaxError` is deliberately NOT caught: a file that exists and does not
    parse is a finding, and the two planters both make their file appear
    atomically (a rename into place, an `os.replace` over the name) so a census
    can never see a half-written one.
    """
    return ast.parse(source_text(path), filename=str(path))


# --- the drive, so a census can prove it tolerates rather than claim it -------

#: Prefix of the inert module `vanishing_source_file` plants at the top of
#: `apps/`, where every tree-wide census enumerates it.
VANISHER_PREFIX = "zzz_vanisher_"
VANISHER_SOURCE = "VALUE = 1\n"


@contextmanager
def vanishing_source_file() -> Iterator[Path]:
    """Plant an inert module under `apps/` and remove it *as a census opens it*.

    The race, with its timing pinned instead of hoped for: `Path.read_text`
    unlinks the file before delegating, so the census has already listed it and
    has not yet read it. A census run inside this block either tolerates the
    vanish or raises `FileNotFoundError` — there is no third outcome, because
    the plant holds nothing any census could have an opinion about.

    Used as a one-line falsifier BESIDE each census rather than from one central
    drive: a single module importing every app's tests would be `apps.core`
    reaching upward, which the layer contract refuses, and the census's own
    module is where the next person writing one will look anyway.

        def test_the_census_tolerates_a_vanishing_file() -> None:
            with vanishing_source_file() as planted:
                my_census()
                assert not planted.exists()

    The name is unique per call: a shared name races itself across xdist workers.
    """
    planted = Path(settings.BASE_DIR) / "apps" / f"{VANISHER_PREFIX}{uuid.uuid4().hex[:8]}.py"
    planted.write_text(VANISHER_SOURCE, encoding="utf-8")
    real_read_text = Path.read_text

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == planted:
            self.unlink(missing_ok=True)
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    Path.read_text = read_text  # type: ignore[method-assign]
    try:
        yield planted
    finally:
        Path.read_text = real_read_text  # type: ignore[method-assign]
        planted.unlink(missing_ok=True)
