"""A real third-party `lifecycle.py`, for proving the discovery walk.

Not a test module and never collected (no `test_` prefix): it is the *subject*
of `test_lifecycle.py::test_a_third_party_module_is_discovered_and_read`, which
points the discovery walk at `apps.core.tests` by doubling one app config and
lets everything else — `find_spec`, `import_module`, `register(registry)` — be
the real thing.

It sits here rather than in an app because no app in this tree owns a
third-party table **yet**: allauth's two are `apps/accounts/lifecycle.py`'s and
`django_session` is `apps/workflows/lifecycle.py`'s, both still ahead in the
build. When those exist, this module has done its job and the walk is proven
by production code.

Rule 11 does not see it: `check_canonical_shape` globs `*.py` at an app's top
level and never descends into `tests/`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.sites.models import Site

from apps.core.lifecycle import Lifecycle, LifecycleKind

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.lifecycle import LifecycleRegistry

#: `django.contrib.sites` is the one third-party table in this tree that no
#: real app has a claim on, which is what makes it safe to use as a probe: the
#: fan-out will never come along and declare it for real underneath this file.
PROBE_MODEL = Site

PROBE_LIFECYCLE = Lifecycle(
    kind=LifecycleKind.UNBOUNDED,
    reason="a probe declaration, read by test_lifecycle.py and by nothing else",
    trigger="2026-08-24 — the first real apps/<x>/lifecycle.py, which retires this file",
)


def register(registry: LifecycleRegistry) -> None:
    """The whole contract a third-party declaration module has to meet."""
    registry.declare(PROBE_MODEL, PROBE_LIFECYCLE, source=__name__)
