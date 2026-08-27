"""The one tolerant read for every census that walks the source tree.

**A census that walks `apps/**` is racing every other xdist worker's fixtures.**
Two tests plant a real file inside `apps/` on purpose, because what they prove
is that a *directory listing* is the registration:

* `apps/core/tests/test_settings.py` builds and removes `apps/zzz_probe/`, so
  discovery can be asked whether a new directory is a new app;
* `apps/usage/tests/conftest.py` writes and unlinks `apps/example/meters.py`,
  so the meter registry can be asked whether it finds somebody else's file.

Neither plant can move: the claim under test is about the real `apps/`
directory, and a plant under `tmp_path` would prove the opposite of what the
test says. So the tolerance belongs on the reading side, and it belongs here
rather than once per census.

**What actually races, measured.** `Path.rglob` is safe: it enumerates through
`os.scandir` and a directory that vanishes mid-walk simply yields nothing more
(checked on the CPython 3.12.14 this tree pins). The window is between the
*listing* and the `open()` — `rglob` names a file, the planting worker's
teardown removes it, and `read_text()` raises `FileNotFoundError`. Measured at
the full gate's second pytest pass, seed 376820410, on
`apps/zzz_probe/__init__.py`, where the exception was read as an earlier pass
having left state behind and used to refuse a push; measured again later, in
`test_observability.py`, after a test-count change reshuffled the schedule.

**Why an empty answer is the honest one, and not a swallowed error.** A file
that no longer exists holds no call sites, no imports and no hook
registrations, so it cannot be in violation of anything — there is nothing
there to be in violation. Returning "no source" is what the census always
meant. Only `FileNotFoundError` is tolerated: a permission error, a decoding
error or a syntax error is still a finding and still raises, so this is never a
bare `except` wearing the shape of a fix.

Excluding one planter's directory by name would close only that planter. This
closes the CLASS — every census in the tree, and every planter that arrives
later.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

#: Modules a test plants inside `apps/` and removes again. A *discovery* census
#: — one that counts apps rather than reading files — has to take them out by
#: name, because the alternative is asserting about the test suite instead of
#: about the tree. That is a different job from the tolerant read below and is
#: kept separate deliberately: the read tolerates ANY vanishing file, named or
#: not, while this list is the small set a count has to know about.
TRANSIENT_APP_MODULES: frozenset[str] = frozenset({"apps.zzz_probe"})


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


def without_transient_apps(names: Iterable[str]) -> list[str]:
    """A discovery census's answer with the throwaway probe apps taken out.

    **The xdist race, found by E1 under seed 362519638** (1 failed / 1325
    passed, not reproducible on re-run). `test_settings.py` creates a real
    directory under `apps/` on the real disk, and every test that counts that
    directory runs on some other worker at the same time — so a count can
    legitimately see an app that `settings.LOCAL_APPS`, computed once at
    startup, has never heard of.

    **Why filtering and not serialising.** Putting the tests on one worker needs
    `xdist_group`, which only binds under `--dist loadgroup`; the gate runs
    plain `-n auto` (`scripts/check.sh`), so buying this would mean changing the
    distribution mode for the entire suite. And the probe is not a real app — it
    is a test artifact that exists for a few milliseconds — so a count that
    included it would be asserting about the test suite rather than about the
    tree. Excluding it by name is what these assertions always meant.
    """
    return [name for name in names if name not in TRANSIENT_APP_MODULES]


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

    **The name is unique per call, and that is not decoration.** A single shared
    name made this a planter racing itself: under `-n 10` one worker re-planted
    between another's listing and its `assert not planted.exists()`, and the
    drive reported "the census never opened the plant" on a census that had
    opened it. Measured 2026-08-25, on RACE-1's first `-n 10` run — the class
    biting the instrument written to close it.
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
