"""The product's fixture drawer — `apps/conftest_local.py`, discovered by the root conftest.

**What this proves and why it exists.** `apps/conftest.py` is template-owned
(`quality/partition.yaml` class C2), and it is the only conftest a product-wide
fixture can live in: `apps/<x>/tests/conftest.py` is scoped by directory
ancestry, so a fixture every app's tests need has nowhere else to go. The first
consumer of this template therefore added 609 lines to the template's own
file. The drawer is the seam: `apps/conftest.py` declares
`pytest_plugins = ["apps.conftest_local"]` **iff** that module exists, the
module is product-owned, and the template never ships one. C2 names that path
as a member: a plugin is loaded for the whole session, so an `autouse=True`
fixture in a drawer runs inside the platform's own tests, and a product's
drawer therefore does move the partition key — honestly, because it can change
what the platform suite answers.

**Every case here runs a CHILD pytest**, because plugin loading and fixture
resolution both happen at collection time: a test that plants the drawer in its
own session is a test whose session decided what it could see before the plant
existed. The child is the only shape that measures the thing that ships.

**And every child runs over a PRIVATE tree, never this one.** A drawer is not
like `apps/zzz_probe/` or the `meters.py` planted in `apps/example/`, the two planters that came
before: it is loaded as a pytest PLUGIN for a whole session, so for as long as
it exists on disk it belongs to every process that starts pytest in the
checkout. `_private_tree` carries the measurement of what that cost, and it is
the reason this drive plants into a symlink farm instead.

The broken-drawer case is an ImportError rather than a SyntaxError. Both are
loud and both name the file, and ImportError is the one that actually
discriminates the two guard shapes — a bare
`try: import ... except ImportError: pass` swallows exactly it — while an
unparseable module is a finding for every tree census that walks `apps/**`
(`tree_census.source_tree` does not catch `SyntaxError`, deliberately). The
SyntaxError half is real and was driven by hand; it is not worth a plant that
only a private tree makes safe and that proves the weaker of the two.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from django.conf import settings

APPS_DIR = Path(settings.BASE_DIR) / "apps"

#: The drawer's one true path, and the ONE name this drive answers for. It is
#: read here only to name the file and to ask whether THIS deployment has one;
#: nothing is ever written to it (`_private_tree`).
DRAWER = APPS_DIR / "conftest_local.py"

FIXTURE_NAME = "the_products_own_fixture"
FIXTURE_VALUE = "out of the drawer"

WORKING_DRAWER = f'''"""A product's own fixtures, planted by {__name__}."""

import pytest


@pytest.fixture
def {FIXTURE_NAME}() -> str:
    return "{FIXTURE_VALUE}"
'''

#: A drawer that exists and cannot be imported. The module it names does not
#: exist and will not: the point is an ImportError raised INSIDE the drawer,
#: which is what a real product's broken drawer raises and what a swallowing
#: `except ImportError` would turn into silence.
BROKEN_DRAWER = '''"""A drawer that raises on import, planted by a drive."""

import a_module_this_tree_does_not_have_and_never_will  # noqa: F401
'''

PROBE = f'''def test_the_drawer_fixture_resolves({FIXTURE_NAME}: str) -> None:
    assert {FIXTURE_NAME} == "{FIXTURE_VALUE}"
'''


@contextmanager
def _private_tree(drawer: str | None) -> Iterator[tuple[Path, Path]]:
    """A throwaway checkout of this tree, with the drawer planted in IT.

    Yields `(root, probe)`. `drawer=None` plants only the probe, which is the
    falsifier: the same probe, the same child, no drawer.

    **NOTHING IS EVER PLANTED IN THE REAL `apps/`, and that is the correction
    the gate made twice.** The first shape planted `apps/conftest_local.py` in
    the working tree the way `apps/zzz_probe/` and the planted `apps/example/` `meters.py`
    already do, and a drawer is not like those two: it is loaded as a pytest
    PLUGIN for a whole session, so while it exists it belongs to every process
    that starts pytest in this checkout. Both failures were measured, neither
    was in this module's own assertions:

      * the second pytest pass — three cases on three xdist workers, one
        planting while another measured absence (`hasplugin` False,
        `DRAWER.exists()` True);
      * the box loop — `apps/test_absent_world.py` spawns its own child
        `pytest`, and the broken-drawer plant was on disk when it did, so a
        test with nothing to do with drawers collected an ImportError.

    The second one is the general case and no amount of care inside this module
    closes it: any test anywhere that shells out to pytest is a victim while a
    broken drawer exists. So the plant moves out of the shared tree.

    The tree is a farm of symlinks — every top-level entry linked, then `apps/`
    rebuilt as a real directory of links to its own entries — so it costs a few
    dozen inodes rather than a copy of the repository, and `pyproject.toml`
    comes along, which is what makes the child's rootdir the scratch root and
    `apps/conftest.py` an INITIAL conftest there. The deployment's own drawer is
    deliberately NOT linked: this drive answers for the file it plants.
    """
    with tempfile.TemporaryDirectory(prefix="djb-drawer-") as scratch:
        real = Path(settings.BASE_DIR)
        root = Path(scratch) / "tree"
        root.mkdir()
        for entry in real.iterdir():
            if entry.name != "apps":
                (root / entry.name).symlink_to(entry)
        apps = root / "apps"
        apps.mkdir()
        for entry in (real / "apps").iterdir():
            if entry.name != DRAWER.name:
                (apps / entry.name).symlink_to(entry)
        if drawer is not None:
            (apps / DRAWER.name).write_text(drawer, encoding="utf-8")
        probe = apps / "zzz_drawer_probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        yield root, probe


def _child(root: Path, probe: Path) -> subprocess.CompletedProcess[str]:
    """One serial pytest in its own process, over the private tree.

    `-p no:randomly` because these cases assert about ONE named item, and
    `-p no:cacheprovider` because a child writing a `.pytest_cache` is a child
    changing what somebody's `--lf` would say.
    """
    return subprocess.run(  # noqa: S603 — argv list built here from constants and paths; no shell
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-q",
            str(probe.relative_to(root)),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_fixture_drawer(request: pytest.FixtureRequest, subtests: Any) -> None:
    """All three drawer states, in ONE test, because the path has ONE owner.

    **Why this is not three test functions, measured.** It was, and the full
    gate's second pytest pass caught them racing each other: xdist distributes
    per test, so the planted-drawer case and the absent-drawer case ran on two
    workers at once, and the absent case saw the other's `apps/conftest_local.py`
    on disk — `hasplugin` False while `DRAWER.exists()` was True. Same seed,
    same worker count, green in pass 1 and red in pass 2. That is the class
    `tree_census.vanishing_source_file`'s docstring already records under "the
    name is unique per call": a planter racing itself. A unique name cannot fix
    it here, because the drawer's whole meaning is its ONE conventional path —
    so the path gets one owner instead, and `subtests` keeps a failing phase
    named.

    The equivalence below runs before any plant, and it is an EQUIVALENCE rather
    than "no plugin is registered": a drawer is registered exactly when a drawer
    exists. In this tree both sides are false; in a product that uses the drawer
    both are true. Asserting the template's half alone made this a permanently
    red platform test in any product with a drawer.

    The question is put to the plugin manager rather than to `apps.conftest`'s
    module object on purpose: `apps.core` may not import the root conftest (the
    fixed layer contract — the conftest reaches `apps.accounts` and
    `apps.workflows`, and `apps.core` sits under both), and what is being
    asserted is pytest's state, not a module attribute.
    """
    assert request.config.pluginmanager.hasplugin("apps.conftest_local") == DRAWER.exists(), (
        "the drawer plugin is registered exactly when the drawer module exists"
    )

    with subtests.test("planted — the drawer's fixture reaches a test"):
        # The whole ask: a product drops one file and its fixtures are everywhere.
        with _private_tree(WORKING_DRAWER) as (root, probe):
            ran = _child(root, probe)
        assert ran.returncode == 0, ran.stdout + ran.stderr
        assert "1 passed" in ran.stdout, ran.stdout

    with subtests.test("absent — the same probe cannot resolve the fixture"):
        # The falsifier, and the absent half of "absent is byte-identical".
        with _private_tree(None) as (root, probe):
            ran = _child(root, probe)
        assert ran.returncode != 0, ran.stdout
        assert f"fixture '{FIXTURE_NAME}' not found" in ran.stdout, ran.stdout

    with subtests.test("broken — a loud error naming the file"):
        # The case the `find_spec` guard exists for. A
        # `try: import apps.conftest_local except ImportError: pass` cannot tell
        # "no drawer" from "the drawer raised on line 3", so a product whose
        # fixtures quietly stopped loading would read every one of its tests as
        # `fixture not found` with nothing naming the cause.
        with _private_tree(BROKEN_DRAWER) as (root, probe):
            ran = _child(root, probe)
        output = ran.stdout + ran.stderr
        assert ran.returncode != 0, output
        assert "ImportError" in output, output
        assert "apps.conftest_local" in output or "conftest_local.py" in output, output
