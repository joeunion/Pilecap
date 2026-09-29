"""`isolated_apps` — Django's `isolate_apps`, plus the one teardown it lacks.

**The defect this closes.** A model built under `isolate_apps` lives in a
throwaway registry, but its relation graph is written onto REAL classes. When
Django builds a model's reverse relations (`Options._populate_directed_relation_
graph`) it walks `self.apps.get_models()` — the ISOLATED registry — and stores
the result in `_relation_tree` on EVERY model that registry holds. A test that
registers the real user model into the isolated registry (so a planted
`Archivable` noun's `archived_by` resolves) therefore rewrites
`User._meta._relation_tree` to only the planted model's foreign keys.
`isolate_apps` restores `Options.default_apps` on the way out and expires
nothing, so the rewritten tree outlives the test: the next time anything
recomputes `User._meta.fields_map`, the user model has lost `memberships` and
every other reverse relation — `FieldError: Cannot resolve keyword
'memberships'` — in whichever unrelated test runs next on that worker.

**Why it is order- and worker-dependent rather than always red.** The tree is
consulted only when `fields_map` is RECOMPUTED. Defining the planted model
expires the user model's reverse caches; if something reads them again before
the planted model's graph is built, the correct map is cached and the poisoned
tree is never read. Whether that read happens first depends on which fixtures
and tests that worker ran before, so a serial pairwise run can pass while an
xdist worker under one seed fails.

**The fix.** On the way out, clear the GLOBAL registry's cache, which expires
`_relation_tree`, `fields_map` and `related_objects` on every real model, so
the next read rebuilds them from the real registry. A drop-in: the same
arguments, the same decorator and context-manager forms.
"""

from __future__ import annotations

from django.apps import apps as global_apps
from django.test.utils import isolate_apps


class isolated_apps(isolate_apps):  # noqa: N801 — a drop-in for Django's lower-case class
    """`isolate_apps` that rebuilds every real model's relation caches on the way out."""

    def disable(self) -> None:
        super().disable()
        global_apps.clear_cache()


# --- the registry-integrity guard's two readers ------------------------------
#
# The guard itself is the module-scoped autouse fixture in `apps/conftest.py`
# (`_no_module_rewrites_the_real_registry`); its readers live here so core's own
# tests can canary them without importing the apps-root conftest, which the
# layer contract forbids core to reach.


def registry_field_names() -> dict[str, tuple[str, ...]]:
    """`{label: sorted field names}` over the real registry, from each tree AS FOUND.

    Reading one model's fields can rebuild EVERY model's relation tree: a model
    whose tree was expired (defining a model with a foreign key to it expires
    it) recomputes the whole graph from the real registry and writes it onto
    all of them — which would heal the poisoned tree before the guard reached
    it. So the trees are read in three steps: note what each model holds, let
    the models holding none rebuild (a missing tree is a correct one waiting to
    be computed), put every noted tree back, and only then read the names.
    """
    population = global_apps.get_models()
    found = {model: model._meta.__dict__.get("_relation_tree") for model in population}
    for model in population:
        if found[model] is None:
            # The read IS the rebuild; the stubs do not declare Django's private seam.
            model._meta._relation_tree  # type: ignore[attr-defined]  # noqa: B018
    for model, tree in found.items():
        if tree is not None:
            model._meta.__dict__["_relation_tree"] = tree

    shape: dict[str, tuple[str, ...]] = {}
    for model in population:
        opts = model._meta
        # The get_fields() memo only; the stubs do not declare Django's private seam.
        opts._expire_cache(forward=False, reverse=False)  # type: ignore[attr-defined]
        shape[opts.label] = tuple(sorted(field.name for field in opts.get_fields()))
    return shape


def registry_difference(
    before: dict[str, tuple[str, ...]], after: dict[str, tuple[str, ...]]
) -> list[str]:
    """One line per model whose field names moved: `label · lost a, b · gained c`.

    Over the models the session STARTED with, and a line for every model that
    joined the global registry since and is still in it at the module's end —
    a class a test defined bare, which no teardown takes out, so every registry
    reader after it on that worker counts a model no product has.
    """
    lines = [f"{label} · joined the registry" for label in sorted(set(after) - set(before))]
    for label in sorted(before):
        if label not in after:
            lines.append(f"{label} · left the registry")
            continue
        lost = sorted(set(before[label]) - set(after[label]))
        gained = sorted(set(after[label]) - set(before[label]))
        if lost or gained:
            parts = [label]
            if lost:
                parts.append(f"lost {', '.join(lost)}")
            if gained:
                parts.append(f"gained {', '.join(gained)}")
            lines.append(" · ".join(parts))
    return lines
