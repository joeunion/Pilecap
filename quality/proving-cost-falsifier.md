# The proving-cost floor: falsified, and NOT shipped

Cycle 1, rung 4 (quality batch), 2026-08-19/20.

**Verdict: the leg does not ship. It needs a different cycle.**

The rung's own instruction was to falsify before recording anything: five runs
of the suite on an unchanged tree, and *"spread must be <10% of median or the
leg does NOT ship and the report returns 'needs a different cycle' with the
five numbers."* It does not. It is off by a factor of three on the quiet
measurement and by a factor of eleven on the noisy one, and — the part worth
carrying forward — **the normalisation the design rests on makes the number
*less* stable, not more.**

Nothing was recorded. There is no `quality/proving.yaml`, no `proving-cost` leg
in `scripts/check.sh`, no plugin registered from a root `conftest.py`, and no
new dependency. What exists is this file: the design, the numbers, the
diagnosis, and what a next attempt would have to do differently.

---

## What was built and measured

`quality/proving_cost.py` (a pytest plugin, since removed — its source is at
the bottom of this file) measured, per session:

- **calibration** — seconds for one `sha256` over 20MB of deterministic bytes,
  median of three, taken at `pytest_sessionstart` before any test ran;
- **suite_seconds** — wall time from that point to `pytest_sessionfinish`;
- **per-test durations** — `setup + call + teardown` per nodeid.

and derived the three numbers the design would have recorded as ceilings:

```
suite_cost_normalized    = suite_seconds       / calibration
per_test_p95_normalized  = p95(per-test)       / calibration
per_test_max_normalized  = max(per-test)       / calibration
```

The whole point of the denominator is that a ceiling in raw seconds is either
so loose it catches nothing or so tight it fails on somebody else's machine. A
ratio to a CPU probe measured minutes earlier, in the same process, was meant
to move with the machine and not with the tree.

**Tree**: `5ab58a9` plus the plugin and the root `conftest.py`, nothing else.
606 tests, green on every run. **Machine**: Darwin/arm64, Python 3.12.14, the
one shared compose stack (Postgres 16, Redis 7), own database
(`djb_worktree_agent_af347f3f89dc0f283`).

Each set is six runs: run 0 is the discarded warm-up, runs 1–5 are the
falsifier's five. Spread is `(max − min) / median`.

## Set A — five runs (light editing on the machine alongside)

| run | calibration s | suite s | suite_cost_norm | p95_norm | max_norm |
|---|---|---|---|---|---|
| 0 (warm-up) | 0.008003 | 58.261 | 7279.5 | 39.2 | 902.9 |
| 1 | 0.006864 | 53.323 | 7768.7 | 50.9 | 1055.0 |
| 2 | 0.006956 | 53.575 | 7702.4 | 46.7 | 1040.6 |
| 3 | 0.008098 | 57.495 | 7100.3 | 45.5 | 914.9 |
| 4 | 0.008902 | 49.221 | 5529.4 | 35.4 | 816.9 |
| 5 | 0.006966 | 50.494 | 7248.5 | 46.1 | 1083.1 |

| metric | median | min | max | **spread** |
|---|---|---|---|---|
| `suite_cost_normalized` | 7248.5 | 5529.4 | 7768.7 | **30.9%** |
| `per_test_p95_normalized` | 46.1 | 35.4 | 50.9 | **33.6%** |
| `per_test_max_normalized` | 1040.6 | 816.9 | 1083.1 | **25.6%** |
| `suite_seconds` (raw) | 53.3 | 49.2 | 57.5 | 15.5% |
| `calibration_seconds` | 0.00697 | 0.00686 | 0.00890 | **29.3%** |

## Set B — five more runs, machine otherwise quiet

Run for exactly one reason: to be sure Set A was not an artefact of measuring
while doing something else.

| run | calibration s | suite s | suite_cost_norm | p95_norm | max_norm |
|---|---|---|---|---|---|
| 0 (warm-up) | 0.006920 | 53.811 | 7776.2 | 50.4 | 1055.4 |
| 1 | 0.008848 | 57.938 | 6548.2 | 45.1 | 821.8 |
| 2 | 0.006993 | 54.657 | 7816.0 | 50.2 | 1047.2 |
| 3 | 0.007072 | 52.697 | 7451.0 | 49.7 | 1034.9 |
| 4 | 0.006920 | **104.866** | 15154.6 | 103.9 | 1214.5 |
| 5 | 0.008295 | 63.809 | 7692.3 | 55.3 | 891.6 |

| metric | median | min | max | **spread** |
|---|---|---|---|---|
| `suite_cost_normalized` | 7692.3 | 6548.2 | 15154.6 | **111.9%** |
| `per_test_p95_normalized` | 50.2 | 45.1 | 103.9 | **117.1%** |
| `per_test_max_normalized` | 1034.9 | 821.8 | 1214.5 | **37.9%** |
| `suite_seconds` (raw) | 57.9 | 52.7 | 104.9 | 90.0% |
| `calibration_seconds` | 0.00707 | 0.00692 | 0.00885 | **27.3%** |

Run 4 took **104.9 seconds for the identical tree that took 52.7 seconds one
run earlier** — a clean 2× on nothing. Discarding it as an outlier is the most
generous reading available, and the four that remain still spread **16.5%** on
`suite_cost_normalized` and **21%** on raw seconds. Ten measured runs across
two sets; the best number any of them supports is 16.5%, and the bar is 10%.

## The diagnosis — the denominator is the problem

Three things, in order of how much they matter.

**1. The probe is noisier than the thing it normalises.** In both sets the
calibration's own spread (27–29%) is *larger* than the raw wall-clock spread it
exists to cancel (15–20%). Dividing a 15%-noisy numerator by a 28%-noisy
denominator produces a 31%-noisy ratio. Every normalised column above is worse
than the raw column beside it. That is not a tuning problem; it is the design
being upside down.

**2. 7 milliseconds is far too short a sample on a heterogeneous-core
machine.** `sha256` over 20MB takes ~7ms here. On Apple silicon a 7ms burst
lands wherever the scheduler puts it, and a performance core and an efficiency
core differ by more than the whole measurement. The anti-correlation is visible
in the data: Set A run 4 has the **slowest** probe (8.9ms) and the **fastest**
suite (49.2s), which is the opposite of what a valid denominator does.

Measured directly, twelve back-to-back probes in one quiet process spread
**3.4%** on one attempt and **11.2%** on the next. A denominator that is itself
±10% cannot certify a numerator to <10% — before pytest is even involved.
Making the probe ten times bigger does not fix it: 200MB × 3 spread **9.8%**.

**3. The suite's own wall-clock is not stable to 10% on this machine anyway.**
15.5% (Set A), 90% with the outlier / 21% without (Set B). So the honest
finding is broader than "normalisation failed": **no cost-based leg with a 10%
stability requirement can ship this cycle**, normalised or not. The 25% growth
allowance the design proposed is *smaller than the run-to-run noise*, which
means the leg would have failed green trees — the one failure mode a gate must
never have.

## What a different cycle would have to do differently

Not a to-do list — the options, with what each costs. The next attempt should
pick one deliberately rather than re-deriving these.

- **A denominator that is a real workload, not a microbenchmark.** Something
  that runs for seconds, not milliseconds, and touches the same resources the
  suite does (a fixed number of trivial database round-trips is the obvious
  candidate, since the suite is database-bound). Cost: it makes the probe part
  of the suite's own cost, and it can fail for reasons that are not about time.
- **Statistics instead of a single run.** Record the median of N runs and
  compare medians, not one number against one ceiling. Cost: N× the gate's
  wall time, which is the whole reason the full gate is already the slow one.
- **Count work, not time.** Query counts, test counts, collected-item counts,
  fixture set-up counts — all are exactly reproducible and none of them needs a
  denominator. This is what `quality/budgets.yaml` already does for two other
  subjects, and it is the direction with the least new machinery. It does not
  catch "the same queries got slower", which is the thing wall-clock was for.
- **Measure on one machine class only.** A CI-runner-only leg has a much
  narrower hardware distribution than "any laptop". Cost: a developer's local
  gate stops enforcing it, and the declared blind spot ("proving-cost has never
  seen a CI runner") becomes the whole design instead of a footnote.

The instrument itself — the session/per-test timing harness and the JSON record
— was fine, and is preserved verbatim below so the next attempt starts from a
working measurement rather than from a description of one.

## Declared blind spots of this falsifier

- One machine, one architecture, one afternoon. A Linux CI runner may well be
  far more stable; nothing here measured one, and the rung's own blind-spot
  list already said so.
- Set A was measured while the same machine did light text editing. Set B was
  not, and Set B is *worse* — but neither set is a controlled environment, and
  a controlled environment is not what a gate runs in either.
- Ten runs is a small sample for a claim about a distribution. It is more than
  enough for the claim actually made, which is "this does not reach 10%".
- The probe was not tried on a quiesced machine with CPU affinity pinned; that
  would likely improve it, and is also not something a gate can require.

---

## Appendix — the instrument, verbatim

Removed from the tree with the leg (a module nothing imports is a wish). Drop
it back at `quality/proving_cost.py` and add `pytest_plugins =
("quality.proving_cost",)` to a root `conftest.py` to re-run the measurement.
It writes `quality/.proving_cost.json` after every pytest session.

```python
"""Proving cost — what it costs to prove this tree, in units of this machine."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RECORD_PATH = ROOT / "quality" / ".proving_cost.json"

PROBE_BYTES = 20 * 1024 * 1024
PROBE_ROUNDS = 3
RUN_TOKEN_ENV = "DJB_PROVING_RUN"


def calibrate(rounds: int = PROBE_ROUNDS, size: int = PROBE_BYTES) -> float:
    """Seconds for one sha256 over `size` deterministic bytes, median of `rounds`.

    The blob is built OUTSIDE the timed section: allocating 20MB is a memory
    benchmark, and this wants to be a CPU one.
    """
    blob = bytes(range(256)) * (size // 256)
    samples: list[float] = []
    for _ in range(rounds):
        start = time.perf_counter()
        hashlib.sha256(blob).digest()
        samples.append(time.perf_counter() - start)
    samples.sort()
    return samples[len(samples) // 2]


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank percentile — no interpolation, so the number is a real test."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


class ProvingCost:
    """Times the session and every test in it, and writes one JSON record.

    Nothing here may raise: measurement that can break the thing it measures is
    worse than no measurement. The worst it does is write no record.
    """

    def __init__(self) -> None:
        self.calibration = 0.0
        self.started = 0.0
        self.durations: dict[str, float] = {}

    def pytest_sessionstart(self, session: Any) -> None:
        try:
            self.calibration = calibrate()
        except Exception:
            self.calibration = 0.0
        self.started = time.perf_counter()

    def pytest_runtest_logreport(self, report: Any) -> None:
        try:
            # setup + call + teardown: what the test cost, not what its body did.
            self.durations[report.nodeid] = self.durations.get(report.nodeid, 0.0) + float(
                report.duration
            )
        except Exception:
            pass

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        try:
            self.write(float(exitstatus))
        except Exception:
            pass

    def write(self, exitstatus: float) -> None:
        elapsed = time.perf_counter() - self.started
        per_test = list(self.durations.values())
        unit = self.calibration or 0.0
        slowest = max(self.durations.items(), key=lambda kv: kv[1], default=("", 0.0))

        def normalized(seconds: float) -> float:
            return round(seconds / unit, 3) if unit > 0 else 0.0

        record = {
            "recorded_at": time.time(),
            "run_token": os.environ.get(RUN_TOKEN_ENV, ""),
            "exitstatus": int(exitstatus),
            "tests": len(per_test),
            "calibration_seconds": round(unit, 6),
            "suite_seconds": round(elapsed, 3),
            "suite_cost_normalized": normalized(elapsed),
            "per_test_p95_normalized": normalized(percentile(per_test, 0.95)),
            "per_test_max_normalized": normalized(slowest[1]),
            "per_test_max_nodeid": slowest[0],
            "machine": f"{platform.system()}/{platform.machine()}/py{platform.python_version()}",
        }
        RECORD_PATH.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")


def pytest_configure(config: Any) -> None:
    """Entry point when this module is loaded as a plugin (root conftest.py)."""
    config.pluginmanager.register(ProvingCost(), "djb-proving-cost")
```

The checker half — which read this record against a `quality/proving.yaml` of
recorded ceilings, exit 0 clean / 1 growth / 2 record missing, malformed, from
a red or empty suite, or from a different run than the one that just happened —
was written and is deliberately not preserved: it enforces the metric this file
rejects, and a next attempt with a different metric will want a different one.
