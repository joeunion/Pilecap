"""Registry integrity: no module leaves the real models' relations rewritten."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from apps.core.tests.isolation import registry_difference, registry_field_names

# --- registry integrity: no module leaves the real models' relations rewritten --
#
# A model built in a throwaway registry writes its reverse-relation graph onto
# the REAL classes that registry holds (`apps/core/tests/isolation.py` has the
# mechanism), and nothing expires it on the way out. The damage surfaces in
# whichever unrelated test next recomputes a real model's field map, on
# whichever worker, under whichever seed — `FieldError: Cannot resolve keyword
# 'memberships'` a thousand tests away from the module that caused it. Or it
# surfaces nowhere: a fixture that happens to define a related model expires the
# poisoned tree first, and the suite is green over a registry that was wrong.
#
# So the PROPERTY is tested, not a spelling: every real model's field names are
# snapshotted once per session and recomputed at every test MODULE's teardown,
# and a difference fails THAT module, naming the model and the field. Every road
# that rewrites the registry is caught — `isolate_apps` under any import alias,
# a hand-built `Apps`, a model defined mid-run with a relation to a real one —
# because the guard reads the result, never the road. The source census
# (`apps/core/tests/test_isolation_discipline.py`) closes the common spelling
# cheaply; this is the net behind it.
#
# What the recompute does and does not disturb: it resets each model's
# `get_fields()` memo ONLY (`_expire_cache(forward=False, reverse=False)`), so
# the answer is rebuilt from `_relation_tree` AS FOUND — expiring the tree too,
# or letting another model's rebuild overwrite it first, would rebuild it from
# the real registry and heal the very poison it is looking for (measured: the
# first version of this guard read `core.Tenant` before `accounts.User`, and
# Tenant's expired tree rebuilt User's). After a failure the guard heals
# (`apps.clear_cache()`), so one poisoner is one red, not a cascade through
# every module the worker runs next.
#
# DOES NOT COVER: a rewrite that a later statement in the SAME module repairs
# before the module ends (nothing is left to find, and nothing is left to harm);
# a rewrite confined to a model's forward fields that leaves `get_fields()` names
# unchanged (a field swapped for a same-named one); a model that is not in the
# global registry at all (an isolated registry's own planted models, which die
# with it). A model defined into the GLOBAL registry mid-run that changes no
# real model's field names — a proxy defined bare in a test body, measured: it
# added a `<kind>.read` key to every registry census that ran after it on that
# worker — IS covered: a label the session did not start with is a red naming
# it (`joined the registry`), and the heal takes it back out. The granularity
# is the MODULE, like every other finding here: the red names the module whose
# teardown found the class, never the test function inside it that defined it.
#
# The two readers (`registry_field_names`, `registry_difference`) live in
# `apps/core/tests/isolation.py`, beside the drop-in they back, so the guard's
# canary in core's own tests can import them without importing this file.


@pytest.fixture(scope="session")
def _djb_registry_at_session_start() -> dict[str, tuple[str, ...]]:
    """The real registry's field names, before any test module ran."""
    return registry_field_names()


@pytest.fixture(scope="module", autouse=True)
def _no_module_rewrites_the_real_registry(
    request: pytest.FixtureRequest, _djb_registry_at_session_start: dict[str, tuple[str, ...]]
) -> Iterator[None]:
    """Fail the MODULE that left a real model's relations rewritten, by name."""
    yield
    after = registry_field_names()
    moved = registry_difference(_djb_registry_at_session_start, after)
    if not moved:
        return
    from django.apps import apps as global_apps

    from apps.core import authz

    for label in set(after) - set(_djb_registry_at_session_start):
        app_label, _, name = label.partition(".")
        global_apps.all_models[app_label].pop(name.lower(), None)
    global_apps.clear_cache()
    authz.reset_policies()  # the kind registry is cached; a joiner may be in it
    # Re-read after the heal, so a damage the heal cannot undo (a model that
    # left) is reported once, by the module that did it, and not again by
    # every module this worker runs next.
    healed = registry_field_names()
    for label in list(_djb_registry_at_session_start):
        if label in healed:
            _djb_registry_at_session_start[label] = healed[label]
        else:
            del _djb_registry_at_session_start[label]
    pytest.fail(
        f"REGISTRY REWRITTEN by {request.node.nodeid}: the real models' field names "
        "differ from the session's start after this module ran —\n    "
        + "\n    ".join(moved)
        + "\n  A model built in a throwaway registry wrote its relation graph onto a "
        "real class and nothing expired it, or a model class defined in a test body "
        "joined the real registry and nothing took it out. Build it under "
        "`apps.core.tests.isolation.isolated_apps`, which keeps the class out of the "
        "real registry and rebuilds every real model's relation caches on the way out. "
        "(The registry was healed after this report, so no other module reds for it.)",
        pytrace=False,
    )
