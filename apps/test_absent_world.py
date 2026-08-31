"""The absent-app suite — the world a product runs before it flips the flag.

`DJB_DISABLED_APPS=example uv run pytest --collect-only` exited **2 with 23
collection errors** on the tree before this, 15 of them outside `apps/example`:
the one subtraction `config/settings/discovery.py` invites a product to make was
a configuration in which not a single test could run. The derivation that fixed
it is `apps/conftest.py`, section "the absent-app world"; these are its
falsifiers, and the convention it establishes is one named invocation:

    DJB_DISABLED_APPS=example uv run pytest

**Why this module sits at the root of `apps/` and not in `apps/core/tests/`.**
The mechanism belongs to no app — it is the shared conftest's — and a test of it
has to import `apps.conftest`, which imports `apps.accounts` and
`apps.workflows`. From `apps/core/tests/` that is `core` reaching upward, which
the layer contract refuses by name (`pyproject.toml`, "The fixed layers hold")
and which no exemption should be written for, because the refusal is correct.
`apps/test_temporal_guard.py` and `apps/test_gate_liveness.py` are here for the
same reason: `apps/conftest.py::_app_label` reads a nodeid at this level as
belonging to no app, deliberately.

**What is NOT asserted here, and is not an oversight.** The absent-app suite
COLLECTS clean; it does not yet PASS clean on the template's own tree. The
derivation reads imports, and a large family of tests reaches the worked example
through a hardcoded URL instead — `apps/core/tests/test_addressing_headers.py:75`
is the shape (`LIST_URL = "/api/v1/widgets/"`). Those are left loud on purpose:
each one is a real coupling to the app somebody is about to remove, and a string
scan that swallowed them would turn a suite which names its couplings into a
green that hides them.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from apps.conftest import DJB_ABSENT_APP_SUITE, AbsentWorld, _plan_the_absent_world
from apps.core.tests.tree_census import vanishing_source_file

#: The tree, from this file rather than from settings, so the paths compared
#: below are the ones the plan actually resolved.
ROOT = pathlib.Path(__file__).resolve().parent.parent
APPS = ROOT / "apps"


def test_the_absent_app_suite_is_named_where_an_operator_will_meet_it() -> None:
    """One invocation, spelled once, carried verbatim by the file people copy.

    `.env.example` is where somebody reads what `DJB_DISABLED_APPS` means before
    setting it, so that is where the suite has to be named. Pinned against the
    constant rather than retyped, because a documented command that has drifted
    from the mechanism is worse than no documentation — it is a green somebody
    trusted.
    """
    shipped = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert DJB_ABSENT_APP_SUITE == "DJB_DISABLED_APPS=example uv run pytest"
    assert DJB_ABSENT_APP_SUITE in shipped


def test_the_absent_app_suite_collects_with_no_errors() -> None:
    """The headline property, driven in a child that really has the app removed.

    It cannot be asserted in-process: `INSTALLED_APPS` is read once while
    settings are imported, so the only honest form is a fresh collection under
    the flag. This test runs in the ORDINARY world, which is what makes it the
    tripwire — nothing else in the default suite, and nothing in CI, would
    notice the absent world becoming uncollectable again.
    """
    ran = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:randomly", "--collect-only", "-q"],
        cwd=str(ROOT),
        env={**os.environ, "DJB_DISABLED_APPS": "example"},
        capture_output=True,
        text=True,
        check=False,
    )
    tail = "\n".join(ran.stdout.splitlines()[-40:]) + ran.stderr[-4000:]

    assert ran.returncode == 0, tail
    assert "error" not in tail.lower(), tail
    assert "tests collected" in ran.stdout


def test_the_absent_world_costs_the_ordinary_world_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No flag, no plan: no file read, nothing withheld, nothing printed.

    The claim the whole mechanism rests on — every dev run and both gate passes
    take this branch — and the one that would rot invisibly, because a plan that
    quietly started withholding things in the ordinary world looks exactly like
    a suite that got smaller.
    """
    for spelling in ("", "  ", ",", " , "):
        monkeypatch.setenv("DJB_DISABLED_APPS", spelling)
        assert _plan_the_absent_world() == AbsentWorld(ignore=[], tests={}, report=[]), spelling

    monkeypatch.delenv("DJB_DISABLED_APPS", raising=False)
    assert _plan_the_absent_world() == AbsentWorld(ignore=[], tests={}, report=[])


def test_the_absent_world_withholds_what_reaches_the_absent_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct, transitive, and by-conftest — and nothing beyond that."""
    monkeypatch.setenv("DJB_DISABLED_APPS", "example")
    plan = _plan_the_absent_world()
    ignored = set(plan.ignore)

    # The app itself, and the three directories whose conftest cannot be
    # imported without it — the largest loss the mechanism causes.
    assert APPS / "example" in ignored
    for app in ("exports", "search", "usage"):
        assert APPS / app / "tests" in ignored, app

    # A module that names it directly...
    assert APPS / "core" / "tests" / "test_pagination.py" in ignored
    # ...and THE falsifier for the closure: this one names nothing of the sort.
    # It imports `apps.core.tests.test_refusal_wire`, which imports
    # `apps.example.mcp`. A one-hop derivation left exactly this module behind,
    # as one collection error, which is how the transitive half came to exist.
    assert APPS / "core" / "tests" / "test_database_unavailable.py" in ignored

    # The negatives: a smaller world is not a licence to stop running things.
    for kept in (
        APPS / "core" / "tests" / "test_tenancy.py",
        APPS / "core" / "tests" / "test_optional_apps.py",
        APPS / "accounts" / "tests" / "test_erasure.py",
        APPS / "conftest.py",
        pathlib.Path(__file__).resolve(),
    ):
        assert kept not in ignored, kept
    assert all(path.exists() for path in plan.ignore), "every withheld path is a real one"


def test_a_test_that_reaches_the_absent_app_is_skipped_and_its_module_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The narrow half: one test out, the rest of its module still in.

    `apps/core/tests/test_tenancy.py` imports the worked example inside a single
    test body. Withholding the whole module instead would cost the absent world
    the tenancy suite, which is precisely the thing it exists to check.
    """
    monkeypatch.setenv("DJB_DISABLED_APPS", "example")
    plan = _plan_the_absent_world()
    tenancy = str(APPS / "core" / "tests" / "test_tenancy.py")

    named = {name for (path, name) in plan.tests if path == tenancy}
    assert named == {"test_visible_to_none_is_empty_and_refuses_a_model_it_cannot_scope"}
    assert all(value == "example" for value in plan.tests.values()), plan.tests


def test_the_plan_tolerates_a_file_that_vanishes_as_it_is_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scan-vs-plant race, driven rather than hoped for.

    This survey walks every `.py` under `apps/` while other xdist workers are
    planting and unlinking real files there on purpose
    (`apps/core/tests/tree_census.py` names them and says why they cannot move).
    Found the expensive way: the R4 loop gate refused with
    `pytest.UsageError` on `apps/zzz_vanisher_*.py` — the plant whose entire job
    is to cause exactly this — while the same tree passed serially, which is the
    shape a race always has.

    A file that no longer exists holds no imports, so an empty answer is the
    honest one; anything else still raises.
    """
    monkeypatch.setenv("DJB_DISABLED_APPS", "example")
    with vanishing_source_file() as planted:
        plan = _plan_the_absent_world()
        assert not planted.exists()

    assert planted not in set(plan.ignore)
    assert plan.report, "the survey still ran and still said what it withheld"


def test_the_absent_world_says_out_loud_what_it_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A world that quietly dropped a third of the suite is a green nobody can read."""
    monkeypatch.setenv("DJB_DISABLED_APPS", "example")
    printed = "\n".join(_plan_the_absent_world().report)

    assert "ABSENT-APP" in printed
    assert DJB_ABSENT_APP_SUITE in printed
    assert "example" in printed
    assert "directory withheld: apps/example" in printed
    assert "directory withheld: apps/exports/tests" in printed
    # The transitive catch is visible in the census, not only in the plan.
    assert "test_database_unavailable" in printed
    assert "individual tests withheld:" in printed
