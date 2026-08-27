"""The gate's own liveness, and the instrument's own stability.

Three guards that are all one subject: **an instrument that cannot be trusted
to answer is worse than no instrument**, because it is indistinguishable from a
working one right up until a human notices.

* One incident gave the first two. The merge gate once sat 22+ minutes at 96%
  with every xdist worker at 0% CPU, and nothing in the suite said so — a human
  sent SIGABRT and the faulthandler dump named `apps/conftest.py`'s unbounded
  `ps` census, called from an autouse fixture, on a machine under two
  concurrent full suites. So: a ceiling on every test (`pyproject.toml`), and a
  budget on that `ps` (`apps/conftest.py`).
* Another gave the third. `introspect` is what agents read instead of guessing,
  and four of its `urls` entries carried `repr()` memory addresses — so two
  runs of an unchanged tree produced two different documents and nobody could
  diff the instrument without normalising it first.

These tests live at the top of `apps/` beside `test_temporal_guard.py` for the
same reason it does: their subject is the harness itself, not any one app.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from io import StringIO
from typing import Any

import pytest
from django.core.management import call_command

# The conftest pytest already loaded, not a second copy of it. `apps/` is a
# package, so pytest imports its conftest as `apps.conftest` and this is the
# same module object the fixtures are bound to — asserted below, because a
# duplicate import would give this file its own `_servers_started_here` and
# every guard here would be testing a module nothing else uses.
CONFTEST = sys.modules["apps.conftest"]

# The address shape `repr()` memory addresses take. Written out rather than imported so that a
# future normalisation somewhere else cannot silently satisfy it.
ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def test_the_conftest_under_test_is_the_one_pytest_loaded() -> None:
    """The premise of the `ps` guard below, checked rather than assumed."""
    assert CONFTEST.__file__ is not None
    assert CONFTEST.__file__.endswith("apps/conftest.py")
    assert hasattr(CONFTEST, "_test_server_children")


# --- every pytest entry point inherits a ceiling ------------------------------


def test_every_pytest_entry_point_inherits_a_liveness_ceiling(
    pytestconfig: pytest.Config,
) -> None:
    """A hung test must FAIL, and the ceiling that makes it fail must be in the
    one place every entry point reads.

    `[tool.pytest.ini_options]` is that place: the gate's two pytest legs,
    `scripts/test.sh`, `scripts/perf.sh` and a builder's bare `uv run pytest`
    all resolve it from `pyproject.toml`. Putting it in `addopts`, in a gate
    leg or in a conftest would leave at least one entry point running with no
    ceiling at all, which is the state the merge-gate hang above was reported from.
    """
    ceiling = pytestconfig.getini("timeout")
    assert ceiling, "no `timeout` in [tool.pytest.ini_options] — a hung test would freeze the gate"
    assert float(ceiling) > 0


def test_the_ceiling_clears_the_coldest_legitimate_wait_in_the_suite(
    pytestconfig: pytest.Config,
) -> None:
    """The ceiling is set by the slowest thing the suite is ALLOWED to do.

    That is not the slowest ordinary test (14.5-19.3s measured at `-n auto` on
    a quiet machine). Two things bind above it: session teardown attributed to
    whichever test ran last on each xdist worker, measured at 146.8s under real
    machine contention, and `apps/conftest.py`'s `_FIRST_START_SECONDS` — a
    cold checkout downloads a 64 MB Temporal test-server binary INSIDE the
    first start, and pytest-randomly means ANY test asking for a time-skipping
    environment may be the one that pays it. `pyproject.toml` carries all three
    measurements; this pins the one of them that lives in code.

    This test is the coupling, and it is the reason it is worth writing: raise
    that budget past the ceiling and a cold checkout's first Temporal test
    starts failing for doing exactly what it was budgeted to do. The failure
    would arrive on someone else's rung, months later, looking like a flake.
    Here it arrives on the commit that moves the number.
    """
    # `getini` reads `pyproject.toml`, never the CLI: a run launched with
    # `--timeout=5` still measures the configured ceiling here, which is the
    # point — this asserts about the config site, not about today's invocation.
    ceiling = float(pytestconfig.getini("timeout"))
    assert ceiling > CONFTEST._FIRST_START_SECONDS, (
        f"the per-test ceiling ({ceiling}s) is at or under the first Temporal start's own "
        f"budget ({CONFTEST._FIRST_START_SECONDS}s) — a cold checkout would fail the first "
        "test that asks for a time-skipping environment. Raise `timeout` in pyproject."
    )


def test_the_timeout_method_is_the_one_that_survives_xdist(
    pytestconfig: pytest.Config,
) -> None:
    """`signal`, and the choice was measured rather than assumed.

    Under `-n 2` against a planted `subprocess.run` hang — the same call shape
    the merge-gate hang above was caught by — the two methods behave in opposite ways:

      signal  the hung frame arrives as the failure's OWN traceback, the other
              threads' stacks are captured beside it, the worker survives and
              the rest of the suite runs.
      thread  pytest-timeout dumps to the worker's stderr and then `os._exit`s
              the worker; xdist reports only `worker 'gw0' crashed while
              running <test>` and the dump goes with the process.

    So the thread method is the one that LOSES the frame under xdist, which is
    the opposite of the intuition — xdist workers are processes, and the test
    runs in each worker's MAIN thread, which is exactly where SIGALRM lands. A
    change back to `thread` would still fail a hung test and would still exit
    1; it would just stop saying where. That is the regression this pins.
    """
    assert pytestconfig.getini("timeout_method") == "signal"


def test_the_ceiling_covers_fixtures_and_not_just_test_bodies(
    pytestconfig: pytest.Config,
) -> None:
    """`timeout_func_only` stays false, and that is the whole reason.

    The merge-gate freeze was not in a test body. It was in `_test_server_children`,
    called from an autouse fixture, during TEARDOWN. `timeout_func_only = true`
    times the call phase alone — it would have watched that freeze go by and
    reported nothing, which is indistinguishable from the state this guard was
    added to fix. So the flag is pinned rather than left to a default that a
    future pytest-timeout release is free to change.
    """
    assert pytestconfig.getini("timeout_func_only") is False


# --- the reaper cannot hang the reaper -----------------------------------------


def test_a_hung_ps_census_fails_loud_and_names_itself() -> None:
    """The exact hung-census call, refusing instead of waiting forever.

    The census is called from an autouse fixture, so every test in the suite
    passes through it. The failure mode being closed is not "it is slow" — it
    is that an unbounded wait there is indistinguishable from the suite doing
    work, which is how 22 minutes went by with nobody able to say what was
    happening.
    """

    def a_ps_that_never_answers(*args: Any, **kwargs: Any) -> None:
        assert kwargs.get("timeout"), "the census called `ps` with no timeout at all"
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs["timeout"])

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(CONFTEST.subprocess, "run", a_ps_that_never_answers)
        with pytest.raises(RuntimeError) as refused:
            CONFTEST._test_server_children()

    said = str(refused.value)
    assert "ps" in said and "did not answer within" in said
    assert isinstance(refused.value.__cause__, subprocess.TimeoutExpired)


def test_the_hung_census_never_answers_with_an_empty_set() -> None:
    """The silent-broom failure, named on purpose.

    A census that returns `set()` when it could not look reads exactly like a
    census that looked and found nothing — and the caller
    (`_no_test_server_outlives_the_test_that_started_it`) would then declare no
    leak and move on. That is the shape of a real leak, reported as clean. The
    guard is that the helper raises rather than returns, so this test cannot
    pass by the helper quietly succeeding.
    """

    def a_ps_that_never_answers(*args: Any, **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(CONFTEST.subprocess, "run", a_ps_that_never_answers)
        outcome: object
        try:
            outcome = CONFTEST._test_server_children()
        except RuntimeError as refusal:
            outcome = refusal

    assert not isinstance(outcome, set), "the census answered a census it never took"


# --- introspect is process-stable at source ------------------------------------


@pytest.mark.django_db
def test_introspect_emits_no_memory_address_anywhere() -> None:
    """The whole document, not just the `urls` section.

    Scoping this to `urls` would pass the day a new section grows the same
    `repr()` fallback, and the property being claimed is about the document:
    two runs of an unchanged tree produce the same bytes, so a before/after sha
    means what it says without anyone normalising anything first.
    """
    out = StringIO()
    call_command("introspect", stdout=out)
    document = out.getvalue()

    found = ADDRESS.findall(document)
    assert not found, (
        f"introspect emitted {len(found)} memory address(es) ({sorted(set(found))[:3]}): the "
        "document is not comparable across processes. Name the callable through "
        "`_callable_name`, never `repr()`."
    )
    json.loads(document)


@pytest.mark.django_db
def test_a_partial_view_is_named_by_what_it_wraps_and_says_that_it_wraps() -> None:
    """The four `functools.partial` mounts, rendered as a name a reader can use.

    `apps.core.api.docs.llms_txt (partial)` is a name that resolves to a real
    module and function; `functools.functools.partial(<function llms_txt at
    0x125b6e020>, ...)` was neither stable nor resolvable. The `(partial)` mark
    stays because the wrapping is a real fact about the mount — the fix is to
    stop rendering the address, not to stop saying what is there.
    """
    out = StringIO()
    call_command("introspect", stdout=out)
    payload: dict[str, Any] = json.loads(out.getvalue())

    partials = [entry for entry in payload["urls"] if entry["view"].endswith(" (partial)")]
    assert partials, "no partial-mounted view found — has the mount shape changed?"
    for entry in partials:
        dotted = entry["view"].removesuffix(" (partial)")
        module, _, qualname = dotted.rpartition(".")
        assert module and qualname, f"{entry['view']!r} is not a module.qualname"
        assert "<" not in dotted and "0x" not in dotted


def test_the_namer_unwraps_and_never_reaches_for_repr() -> None:
    """The three shapes, driven directly, including the ones the tree has none
    of today — a re-wrapped partial and an object with no `__qualname__`."""
    import functools

    from apps.core.management.commands.introspect import _callable_name

    def a_view(request: object, api: object = None) -> None: ...

    once = functools.partial(a_view, api=object())
    twice = functools.partial(once, api=object())

    assert _callable_name(a_view).endswith("a_view")
    assert _callable_name(once) == f"{_callable_name(a_view)} (partial)"
    # CPython FLATTENS a partial of a partial — `twice.func` is `a_view`, not
    # `once` — so the mark is said once however many times the mount wrapped.
    # Recorded here because the name would otherwise look like it had missed a
    # layer, and the recursion in `_callable_name` is what makes this true for
    # any wrapper that does NOT flatten.
    assert twice.func is a_view
    assert _callable_name(twice) == f"{_callable_name(a_view)} (partial)"

    class Callable:
        def __call__(self) -> None: ...

    named = _callable_name(Callable())
    assert named.endswith(".Callable instance")
    assert not ADDRESS.search(named)
