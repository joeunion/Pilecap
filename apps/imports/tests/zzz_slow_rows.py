"""The kill drive's one plant: a pause before each row settles. **Its own module, on purpose.**

The drive needs an apply slow enough to kill a worker in the middle of, and it
must measure the REAL importer while it does — so the pause is not planted
under an importer's name (a module the discovery walk would read instead of the
product's `importers.py`, which is what the earlier plant did: the drive went
green over a double whose header the real importer would have refused whole).
It wraps the imports app's OWN per-row service, `services.apply_import_row`, in
this process only: the apply activity looks the service up on the module at
call time, so every row still settles through the real service, the real
importer and the noun's real services, a pause earlier.

Test code, never imported by anything shipped; `zzz_` so no real module is ever
named like it.
"""

from __future__ import annotations

import functools
import time
from typing import Any

from apps.imports import services


def slow_rows(seconds: float) -> None:
    """Sleep `seconds` before each row settles, in this process. Zero plants nothing."""
    if seconds <= 0:
        return
    real = services.apply_import_row

    @functools.wraps(real)
    def paused(**kwargs: Any) -> Any:
        time.sleep(seconds)
        return real(**kwargs)

    services.apply_import_row = paused
