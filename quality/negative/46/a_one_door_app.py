"""An app with one door owes no parity test, and must be told nothing.

There is no pair here: one rendering of a capability cannot disagree with
itself. `apps/connections` is the real instance today, and a rule that demanded
a parity test of a single door would be demanding a test with nothing on the
other side of it — which is how a census comes to be answered with an empty file
carrying a marker.
"""

from __future__ import annotations

from typing import Any

PREFIX = "probes"

router: Any = None
