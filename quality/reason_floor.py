"""Instruments run in worlds with no `apps/`, so the valve's reason floor lives here, stdlib only.

`quality/gate.py` imports `apps.core.roads` and, through `quality.worlds`,
`config.settings`, so a runner under `quality/runners/` that imported the
engine for this one number could not run in a world that copies `frontend/`
and `quality/` alone (the golden-face drive's copy world). The number lives
here, with no imports at all; the engine imports it and keeps the name
`quality.gate.MIN_REASON`, so every existing reader and the `valve` road are
unchanged, and a runner imports it from this module.
"""

from __future__ import annotations

MIN_REASON = 12  # long enough to force a clause; short enough that a real reason clears it
