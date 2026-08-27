"""The scan-vs-plant race, driven deterministically, and the census that keeps it closed.

**The defect.** `test_observability.py`'s house-rule-19 census walks every source
file under `apps/`; on another xdist worker, `test_settings.py`'s `probe_app`
fixture removed `apps/zzz_probe/` between that walk's directory listing and its
`open()`, and the census raised `FileNotFoundError` — read by the full gate as
"pass one left state behind" and used to refuse a push. Pass 1 green, pass 2
red, on schedule reshuffling alone — and it recurred more than once.

**The class, not the instance.** Two tests plant a real file inside `apps/` and
neither can move (`tree_census.py` says why), so *every* census that walks the
tree is exposed and always will be. The fix is one tolerant read — the seam in
`apps.core.tests.tree_census` — and the belt is the census at the bottom of this
module, which fails when a new test module walks a directory of sources and
reads what it found without going through the seam.

**The drive is real, not mocked, and it lives BESIDE each census.**
`tree_census.vanishing_source_file()` plants an inert module at
`apps/zzz_vanisher_<hex>.py` and removes it *at the instant a scanner opens it* —
the race with its timing pinned instead of hoped for. Each tree-wide census
carries a one-line falsifier using it, in its own module, because one central
drive importing every app's tests would be `apps.core` reaching upward and the
layer contract refuses that. Today they are in `test_observability.py`,
`test_scope_readers.py`, `test_addressing_headers.py`, `test_scopes.py`,
`test_storage_fence.py` and `test_services.py`; that makes
`vanishing_source_file` the tree's THIRD planter, named per call for the reason
its own docstring records. The plant is inert on
purpose — no `print`, no logger, no scope literal, no SDK import — so a scanner
that survives it survives because it tolerated the vanish, never because the
file was uninteresting to it.

**DOES NOT COVER — declared.** The censuses whose glob names one file per app
(`apps/*/api.py`, `apps/*/services.py`, `apps/comms/*.py`) carry no drive: a
top-level plant is outside their glob, and planting over a real door module
would clobber the tree. They read through the seam for uniformity and are held
there by the belt below, not by a falsifier. Also uncovered: a plant that a
census *counts* rather than reads — that is `without_transient_apps`, whose
drive is `test_settings.py`'s own suite and `test_optional_apps.py`'s.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from django.conf import settings

from apps.core.tests.tree_census import (
    TRANSIENT_APP_MODULES,
    source_lines,
    source_text,
    source_tree,
    without_transient_apps,
)

ROOT = Path(settings.BASE_DIR)
APPS_DIR = ROOT / "apps"

#: Inert content for the `tmp_path` plants below.
PLANTED_SOURCE = "VALUE = 1\n"


# --- the seam, both directions ------------------------------------------------


def test_the_bare_read_is_what_raises_and_the_seam_is_what_does_not(tmp_path: Path) -> None:
    """The race in four lines: list, vanish, read.

    `Path.rglob` names the file; the planting worker's teardown removes it; the
    census opens it. The bare read raises — which is the defect — and the seam
    answers "no source", which is the truth about a file that is not there.
    """
    planted = tmp_path / "vanisher.py"
    planted.write_text(PLANTED_SOURCE, encoding="utf-8")
    assert sorted(tmp_path.rglob("*.py")) == [planted]

    planted.unlink()  # the other worker's teardown, at the one instant that hurts

    with pytest.raises(FileNotFoundError):
        planted.read_text(encoding="utf-8")

    assert source_text(planted) == ""
    assert source_lines(planted) == []
    parsed = [n for n in ast.walk(source_tree(planted)) if not isinstance(n, ast.Module)]
    assert parsed == []


def test_the_walk_itself_survives_a_directory_that_vanishes(tmp_path: Path) -> None:
    """The measured half of the diagnosis: `rglob` is not where the race bites.

    It enumerates through `os.scandir`, so a directory removed mid-walk simply
    yields nothing more. That is why the tolerance belongs on the read and
    nowhere else — a census wrapping its *walk* in a try would be guarding a
    window that does not exist.
    """
    (tmp_path / "first").mkdir()
    (tmp_path / "first" / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "second").mkdir()
    (tmp_path / "second" / "b.py").write_text("", encoding="utf-8")

    walk = tmp_path.rglob("*.py")
    first = next(walk)
    for doomed in (tmp_path / "first", tmp_path / "second"):
        for child in doomed.iterdir():
            child.unlink()
        doomed.rmdir()

    assert first.suffix == ".py"
    assert list(walk) == []  # no exception: the walk just runs out


def test_only_a_vanished_file_is_tolerated(tmp_path: Path) -> None:
    """Not a bare `except`: a file that is THERE and unreadable is still a finding."""
    undecodable = tmp_path / "undecodable.py"
    undecodable.write_bytes(b"\xff\xfe\x00 not utf-8")
    with pytest.raises(UnicodeDecodeError):
        source_text(undecodable)

    unparseable = tmp_path / "unparseable.py"
    unparseable.write_text("def (:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        source_tree(unparseable)


def test_a_discovery_count_drops_the_probe_and_nothing_else() -> None:
    """The other half: a census that COUNTS apps takes the transient one out by name."""
    assert without_transient_apps(["apps.core", "apps.zzz_probe", "apps.example"]) == [
        "apps.core",
        "apps.example",
    ]
    assert "apps.zzz_probe" in TRANSIENT_APP_MODULES


# --- the belt: nobody walks and reads without the seam ------------------------

#: Attributes whose call means "enumerate a directory".
WALKS = {"glob", "rglob", "iterdir"}
#: Attributes whose call means "open what the walk named".
READS = {"read_text", "read_bytes", "open"}

#: Test modules that walk a directory of files but do NOT open what the walk
#: named — so the seam has nothing to do for them. The judgement is pinned; the
#: POPULATION is derived off the walk, so a new census lands in neither list and
#: fails below until somebody classifies it.
NOT_A_SOURCE_CENSUS: dict[str, str] = {
    "apps/core/tests/test_plant_sites.py": (
        "walks `apps/` for DIRECTORY NAMES only — `(d / 'apps.py').exists()`, which is "
        "False for a vanished entry and needs no tolerance. Its reads are "
        "`quality/rules.yaml`, which no test plants"
    ),
    "apps/core/tests/test_tree_census.py": (
        "this module — it has to say the names to count them, and everything it opens "
        "is either a `tmp_path` fixture it wrote itself or read through the seam"
    ),
}

# NOT exemptions, because they never enter the population: `test_settings.py` and
# `test_optional_apps.py` walk `apps/` only THROUGH `discover_local_apps`, whose
# read is production code that already catches `OSError`
# (`config/settings/discovery.py::_read`). What bit them is the other half of the
# race — a COUNT that included the transient probe — and both now go through
# `without_transient_apps`.

#: `read_text` / `open` on a path a walk produced is the call the seam replaces.
#: A module in the population that still makes one has not been converted.
DIRECT_READS = {"read_text", "read_bytes", "open"}


def _calls(path: Path) -> list[str]:
    return [
        node.func.attr
        for node in ast.walk(source_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]


def _walks(path: Path) -> bool:
    """True when this module enumerates a directory. Read off the CALL, never off
    the text: a docstring that spells `rglob` is prose, not a census."""
    return any(name in WALKS for name in _calls(path))


def _reads_directly(path: Path) -> bool:
    return any(name in DIRECT_READS for name in _calls(path))


SEAM = "apps.core.tests.tree_census"


def _imports_the_seam(path: Path) -> bool:
    """All three spellings, because a check that saw only one would be a check
    a converted module could fail: `from X.tree_census import ...`,
    `from apps.core.tests import tree_census`, and `import X.tree_census`."""
    for node in ast.walk(source_tree(path)):
        if isinstance(node, ast.ImportFrom):
            if node.module == SEAM:
                return True
            if node.module == SEAM.rsplit(".", 1)[0] and any(
                alias.name == "tree_census" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import) and any(alias.name == SEAM for alias in node.names):
            return True
    return False


def _population() -> list[str]:
    """Every test module under `apps/` that enumerates a directory, exemptions out."""
    return sorted(
        {
            path.relative_to(ROOT).as_posix()
            for path in APPS_DIR.rglob("*.py")
            if "tests" in path.parts
            and path.relative_to(ROOT).as_posix() not in NOT_A_SOURCE_CENSUS
            and _walks(path)
        }
    )


def test_every_test_module_that_walks_the_tree_goes_through_the_seam() -> None:
    """The belt. A new census that opens what it walked fails here, by name.

    This is what makes the fix a fix for the CLASS: the seam closes today's
    censuses, and this closes tomorrow's. The population is DERIVED — a call to
    `glob`/`rglob`/`iterdir` anywhere in a test module under `apps/` — so
    nothing has to be remembered; only the exemptions are typed, each with its
    reason, and `test_every_exemption_is_still_a_walker` keeps those honest.

    **DOES NOT COVER — declared.** It cannot tell WHICH path a `read_text` is
    called on, so a module that imports the seam and still opens one walked file
    by hand passes here. That is review's, and the drive above is what actually
    proves the tree-wide censuses tolerate a vanish.
    """
    population = _population()
    assert len(population) > 5, "the census found almost nothing — it would pass vacuously"

    offenders = {
        relative: "opens what it walked without the tolerant read"
        for relative in population
        if _reads_directly(ROOT / relative) and not _imports_the_seam(ROOT / relative)
    }
    assert offenders == {}, (
        "read through apps.core.tests.tree_census — a file listed by the walk and gone "
        f"by the open() is SKIPPED, not a FileNotFoundError: {offenders}"
    )


def test_every_exemption_is_still_a_walker() -> None:
    """The other direction: an exemption for a module that no longer walks is a stale fence."""
    for relative in NOT_A_SOURCE_CENSUS:
        path = ROOT / relative
        assert path.exists(), f"{relative} is exempted and does not exist"
        assert _walks(path), f"{relative} no longer walks a directory — drop the exemption"
