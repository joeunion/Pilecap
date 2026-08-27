"""A real `integrations.py`, in a real package, for the census tooth to find.

**The subject of the no-list-edit criterion**, and it is a real module rather
than a stub for `apps/core/tests/lifecycle.py`'s reason: `find_spec`,
`import_module` and `register(registry)` are all the production path over this
file, and only the app-config list is doubled. A hand-built double would prove
the assertions and not the walk.

Not collected by pytest — no `test_` prefix — and rule 11 does not descend into
`tests/`, so this filename costs no app anything.

The day a real app declares an integration through this seam, that app's module
proves the walk and this one can go, exactly as the lifecycle plant's docstring
says of itself. Until then the four surfaces have never actually met an
integration they were not shipped with, and a census that has only ever seen its
own declarations is a census nobody has tested.
"""

from __future__ import annotations

from apps.core.integrations import (
    PROBE_DECLARED,
    Integration,
    IntegrationRegistry,
    IntegrationStatus,
)

SOURCE = "apps/core/tests/integrations.py"

#: A deliberately absurd integration, so that finding this string anywhere it
#: does not belong is unambiguous. It is `FAKE` rather than `NOT_CONFIGURED`
#: because `FAKE` is the status the whole census exists for — the stand-in that
#: succeeds — and a tooth should plant the case that matters.
PLANTED = Integration(
    key="planted-telegraph",
    title="The planted telegraph",
    status=IntegrationStatus.FAKE,
    detail="there is no telegraph; this row exists so the census can be caught missing one.",
    remedy="delete apps/core/tests/integrations.py — it is a test fixture, not a deployment.",
    probe=PROBE_DECLARED,
)


def register(registry: IntegrationRegistry) -> None:
    """The discovered hook, with the production signature and nothing else."""
    registry.declare(PLANTED, source=SOURCE)
