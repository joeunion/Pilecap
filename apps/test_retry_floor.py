"""Every activity retry policy starts at the deployment's floor, not a literal.

`TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS` exists because the time-skipping test
server skips *workflow* timers and does NOT skip activity retry backoff: five
attempts at the SDK's one-second default is fifteen real seconds inside one
test, and four tests in this tree were paying it. The knob turns that into
milliseconds under `test` while a deployment keeps the SDK's own value.

**A knob nothing asserts is a knob that grows literals back.** The failure this
module exists to catch is silent by construction: someone writes
`initial_interval=timedelta(seconds=1)` at one policy, every assertion in the
suite still passes, every row still reads `failed` or `completed`, and the only
symptom is a wall clock nobody is reading. So each policy that opted in is
named here, with the arithmetic that ties it to the setting.

**No database, no server, no worker.** These are module constants built at
import; the whole module is a settings read and some equality.

It sits at `apps/test_retry_floor.py`, beside the other cross-app tripwires, and
not inside any one app: the property is one property — *there is one floor* —
so four copies would be four places to forget it, and a copy parked in
`apps/workflows/tests/` breaks the layer contract outright, because
`apps.workflows` may not import `apps.events` and the assertion has to name all
four (import-linter, `pyproject.toml`, "The fixed layers hold"). A tripwire
about several apps belongs above all of them.
"""

from __future__ import annotations

import pathlib
from datetime import timedelta

import pytest
from django.conf import settings
from temporalio.common import RetryPolicy

from apps.events import workflows as events_workflows
from apps.exports import workflows as exports_workflows
from apps.files import workflows as files_workflows
from apps.search import workflows as search_workflows

#: This checkout's top level — `apps/` is one directory down.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: The four modules that read the floor, and the constant each reads it into.
#: Named as modules rather than imported constants so the assertion below is
#: about *the module's* `RETRY_INITIAL_INTERVAL` — a module that dropped the
#: read entirely fails here with an `AttributeError` that says which one.
FLOOR_READERS = (
    ("apps.exports.workflows", exports_workflows),
    ("apps.files.workflows", files_workflows),
    ("apps.search.workflows", search_workflows),
    ("apps.events.workflows", events_workflows),
)

#: Every policy whose first interval IS the floor, unmultiplied.
#: `(<where>, <the policy>)`.
AT_THE_FLOOR: tuple[tuple[str, RetryPolicy], ...] = (
    ("exports BUILD_RETRY", exports_workflows.BUILD_RETRY),
    ("exports FINISH_RETRY", exports_workflows.FINISH_RETRY),
    ("files VERIFY_RETRY", files_workflows.VERIFY_RETRY),
    ("files RECORD_RETRY", files_workflows.RECORD_RETRY),
    ("files FINISH_RETRY", files_workflows.FINISH_RETRY),
    ("search RECONCILE_RETRY", search_workflows.RECONCILE_RETRY),
)


def test_every_reader_takes_its_interval_from_the_one_setting() -> None:
    """The four modules read the setting, and read it into the same shape.

    A `timedelta` built from the setting's seconds — so a module that started
    dividing, rounding or defaulting is a different value here and says so.
    """
    expected = timedelta(seconds=settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS)
    assert expected > timedelta(0), "a zero floor would make the arithmetic below vacuous"
    for name, module in FLOOR_READERS:
        assert module.RETRY_INITIAL_INTERVAL == expected, (
            f"{name}.RETRY_INITIAL_INTERVAL is {module.RETRY_INITIAL_INTERVAL!r}, not the "
            f"{expected!r} that TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS declares"
        )


@pytest.mark.parametrize(("where", "policy"), AT_THE_FLOOR, ids=[w for w, _ in AT_THE_FLOOR])
def test_a_policy_at_the_floor_starts_at_the_floor(where: str, policy: RetryPolicy) -> None:
    """Six policies, one number. A literal written back here is red on this line."""
    expected = timedelta(seconds=settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS)
    assert policy.initial_interval == expected, (
        f"{where}.initial_interval is {policy.initial_interval!r} — a hard-coded literal, not "
        f"TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS ({expected!r}). Read the floor, not a number."
    )


def test_the_index_retry_is_twice_the_floor_and_its_ceiling_cannot_sink_below_it() -> None:
    """`apps/events`' INDEX_RETRY is the one deliberate multiple, and it is 2x.

    An index that just refused a write is usually mid-settle rather than down,
    so the ratio is that policy's own judgement while the floor underneath it is
    the deployment's. `maximum_interval` is a CEILING: with the floor turned down
    to milliseconds a literal five minutes is still above it, but the invariant
    that actually has to hold is "never below the interval it caps", and that is
    what is asserted rather than the five minutes.
    """
    floor = timedelta(seconds=settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS)
    policy = events_workflows.INDEX_RETRY
    assert policy.initial_interval == 2 * floor, (
        f"INDEX_RETRY.initial_interval is {policy.initial_interval!r}, not twice the floor "
        f"({2 * floor!r})"
    )
    assert policy.maximum_interval is not None, "a policy that names no ceiling names no bound"
    assert policy.maximum_interval >= policy.initial_interval, (
        f"INDEX_RETRY caps at {policy.maximum_interval!r}, below the "
        f"{policy.initial_interval!r} it is capping — the ceiling sank under the floor"
    )


def test_the_search_ceiling_cannot_sink_below_its_own_interval_either() -> None:
    """The same invariant, on the only other policy here that names a ceiling."""
    policy = search_workflows.RECONCILE_RETRY
    assert policy.maximum_interval is not None, "a policy that names no ceiling names no bound"
    assert policy.maximum_interval >= policy.initial_interval


def test_the_test_settings_floor_is_milliseconds_and_the_base_default_is_the_sdks() -> None:
    """The two values, asserted where a reader will look for them.

    Not a tautology against `settings`: the DEPLOYMENT default is the SDK's one
    second while the value this suite runs under is a hundredth of it, and the
    seam is only worth anything while both halves are true — loosen the first
    and a deployment gets a test knob, loosen the second and every gate run pays
    real backoff again.

    `base.py` is read as TEXT, not imported, and that is the layer contract's
    doing rather than fussiness: `apps` may not import `config`
    (`pyproject.toml`, "config mounts apps"), and the exemption there is written
    for `apps.*.tests.*` — which this cross-app module is deliberately not.
    Reading the declaration is also the idiom `apps/core/tests/test_settings.py`
    already uses on `TEMPORAL_TASK_QUEUE`.
    """
    declaration = "TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS: float = 1.0"
    base_py = REPO_ROOT / "config" / "settings" / "base.py"
    assert declaration in base_py.read_text(), (
        f"{base_py} must declare `{declaration}` — the Temporal SDK's own default. A deployment's "
        "backoff is not a test knob, and turning the base value down would hide real backoff "
        "behind a green suite."
    )
    assert settings.TEMPORAL_RETRY_INITIAL_INTERVAL_SECONDS <= 0.05, (
        "the suite's floor is milliseconds — anything slower is real backoff on every gate run"
    )
