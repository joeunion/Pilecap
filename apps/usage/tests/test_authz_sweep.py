"""P7.7's instrument: this app's authorization matrix did not move, and no line reads a role.

**What a sweep is allowed to change, and what it is not.** P7.7 deleted this
app's own permissions system — `DeclaredPermission`, `declared_permission`,
`ALL_ROLES`, `USAGE_READ_REPORT` — and re-keyed its one capability from
`usage.read_report` to the derived `usage_entry.read`. Every one of those is a
change to HOW the question is asked. None of them may change the ANSWER, and
this module is what makes that a measurement instead of a claim.

**The baseline is derived, and it was derived before the sweep.**
`apps/core/tests/flat_product_baseline.json` is the committed census —
`allows(actor, key, obj=None)` for every key × {owner, admin, member} on a flat
product, written by `permissions_world.write_flat_product_baseline` on a tree
that predates this sweep, with the sha and the command in its own header. This
module re-runs the SAME function over this app's keys on this tree and compares.

*Rejected, and the reason is the lead's own* (P7's rejected-alternatives note,
one layer over): a per-app `authz_baseline.json` derived here. Eight files that
agree with one census is the second-copy class, and the copy this app would
write could only be derived on the swept tree — a pin taken from the thing it
pins. The document that already exists was derived before the sweep, by somebody
else, and is therefore the only honest baseline on the tree.

**The keys are resolved through the rename**, which is the other half of what a
sweep must prove: the baseline names `usage.read_report` because that is what
the key was called, and the cell has to be the same cell. `renamed_permissions()`
is what says the two names are one key, and using it here is what makes "the old
word still answers" a driven fact rather than a table somebody read.
"""

from __future__ import annotations

import ast
import importlib
import json
from pathlib import Path

import pytest
from django.conf import settings

from apps.core.authz import renamed_permissions, vocabulary
from apps.core.tests.permissions_world import census, flat_world

pytestmark = pytest.mark.django_db

#: This app's whole vocabulary after the sweep. One key: a usage report is a
#: total over `UsageEntry`, and reading it is the only thing anybody asks to do
#: here (`policies.py` says why there is no `usage.record`).
APP_KEYS = ("usage_entry.read",)


def _baseline() -> dict[str, dict[str, bool]]:
    document = json.loads(
        (Path(settings.BASE_DIR) / "apps/core/tests/flat_product_baseline.json").read_text()
    )
    answers: dict[str, dict[str, bool]] = document["answers"]
    return answers


def test_the_apps_authorization_matrix_equals_the_baseline() -> None:
    """Every cell this app owns, before and after, on a flat product.

    A moved cell prints `(key, role, before, after)` rather than `assert False`,
    because the interesting failure is *which person stopped being able to do
    what* and a boolean comparison cannot say it.

    The non-vacuity half matters as much here as the equality does: this app has
    exactly one key, so a census that silently found none would compare an empty
    dict with an empty dict and pass. The key count is asserted first.
    """
    baseline = _baseline()
    renames = renamed_permissions()
    old_for = {new: old for old, new in renames.items()}

    pinned = {key: baseline[old_for.get(key, key)] for key in APP_KEYS}
    assert len(pinned) == len(APP_KEYS) == 1, pinned
    assert old_for["usage_entry.read"] == "usage.read_report", old_for

    _tenant, actors = flat_world()
    actual = census(sorted(APP_KEYS), actors)

    moved = [
        (key, role, pinned[key][role], actual[key][role])
        for key in sorted(APP_KEYS)
        for role in sorted(pinned[key])
        if pinned[key][role] != actual[key][role]
    ]
    assert moved == [], moved


def test_the_old_key_and_the_new_one_are_one_cell() -> None:
    """The alias is in the resolution, not in a second row of the census.

    Asserted separately from the matrix because they fail differently: the
    matrix above goes red when an ANSWER moved, and this goes red when the two
    names came apart — a product's stored `Grant` row naming the old word, or a
    caller that never read the release note, quietly falling to a different key.
    """
    _tenant, actors = flat_world()

    assert (
        census(["usage.read_report"], actors)["usage.read_report"]
        == (census(["usage_entry.read"], actors)["usage_entry.read"])
    )
    assert vocabulary()["usage_entry.read"].renamed_from == ("usage.read_report",)


def test_the_apps_policies_read_no_role() -> None:
    """Rule 54 (c) for this app, driven rather than read off the gate's status line.

    **Through the gate's own derivation and not through a grep**, which is the
    difference between the two and the reason it is worth a test of its own: a
    `grep -cE 'ROLE_RANK|rank\\('` over this file answers 2 today and always
    will, because the module docstring SAYS what it deleted — prose spelling a
    name gets counted exactly like code. `_role_value_sites` walks the AST, so
    it sees the file the way the rule does.

    It asserts the app's own number is zero, in the app, so a future edit that
    reaches for a rank table again reds this app's own suite rather than
    somebody else's gate leg a wave later.
    """
    # Reached through `importlib` rather than imported at the top, and the
    # reason is mypy's graph rather than style: `files = ["apps", "config"]`, so
    # a plain `from quality.checks import …` in a module under `apps/` drags the
    # whole `quality/` tree into `--strict` for the first time and surfaces
    # dozens of findings in code the sweep did not touch. The house form is
    # `apps/core/tests/test_audit_rule_seam.py`'s and this matches it.
    role_value_sites = importlib.import_module("quality.checks")._role_value_sites  # noqa: SLF001

    source = (Path(settings.BASE_DIR) / "apps/usage/policies.py").read_text()

    assert role_value_sites(ast.parse(source)) == {}

    # ...and the check really is looking: the same walk over the file as it was
    # BEFORE the sweep finds the one line the sweep deleted.
    before = source.replace(
        "from apps.core.authz import Policy",
        "from apps.core.authz import ROLE_RANK, Policy\n\nALL_ROLES = frozenset(ROLE_RANK)",
    )
    assert role_value_sites(ast.parse(before)) != {}
