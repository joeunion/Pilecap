"""Where a DRAWER rule's fixtures live, asserted against the engine, not prose.

THE DEFECT THIS CLOSES was a doc/code contradiction, and it was silent in the
worst direction. `quality/gate.py::fixture_home` plants a drawer rule's
fixtures from `LOCAL_CANARY_DIR` and `LOCAL_NEGATIVE_DIR` — the drawer, which
the divergence census already reserves under `**/local/**`. Three places that
TEACH the four-places rule (ADR gate-5) named the same two kind directories
with the drawer segment left out, which is the TEMPLATE's own fixture tree and
holds integer ids only. The wrong string is not spelled anywhere in this file,
docstring included: a census that taught what it forbids would be the defect
wearing the guard's clothes, and this file is not inside its own scope. A product that believed
them put its canaries in a tree the engine never looks in for a namespaced id:
the canary is then never planted, never fires, and NOTHING SAYS SO — a dead
canary reading as a pass, which is the one shape this whole engine is built to
refuse. The first consumer read the sentence, planted 261 fixture files where
the prose said, and found out at a fold.

So the sentence is derived here from the engine's own constant and compared
with what the prose says, and the next drift is a red rather than somebody's
evening.

DECLARED SCOPE, and the ledgers are deliberately OUTSIDE it: the queue, the
in-flight ledger and the cycle plans RECORD what was believed and what was
found, including the wrong sentence as the consumer reported it. Rewriting a
ledger to make a census green would falsify the record. What this reads is the
three files a product LEARNS the shape from — the engine's own header, the
rule text's header and the release notes — plus the ownership contract, which
already carried the right form and is here so that the population cannot shrink
to nothing without anyone noticing.
"""

from __future__ import annotations

import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

#: Reached through `importlib` for the reason `test_audit_rule_seam.py` states:
#: a plain `from quality import gate` in a module under `apps/` drags the whole
#: `quality/` tree into mypy's `--strict` graph for the first time.
_GATE = importlib.import_module("quality.gate")

#: DERIVED FROM THE ENGINE. `LOCAL_CANARY_DIR` is `<root>/quality/local/canary`
#: and its parent is the drawer; the sentence every teaching file owes is that
#: drawer with the two kinds and the product id shape.
DRAWER = _GATE.LOCAL_CANARY_DIR.parent.relative_to(ROOT).as_posix()
RIGHT = f"{DRAWER}/{{canary,negative}}/<ns>-<n>/"

#: The same sentence with the drawer segment dropped — which is the template's
#: OWN fixture tree, correct for an integer id and wrong for every `<ns>-<n>`
#: one. Derived from `RIGHT` rather than typed, so the pair cannot drift apart.
WRONG = RIGHT.replace(f"{DRAWER}/", f"{DRAWER.split('/', 1)[0]}/")

#: What a product learns the shape from. Not the ledgers (see the docstring).
TEACHING_FILES = (
    "quality/gate.py",
    "quality/rules.yaml",
    "CHANGELOG.md",
    "docs/product/build-contract.md",
)

#: A floor, for the reason every floor here exists: a census that found no
#: sentence at all would pass by reading nothing, and the sentence moving to a
#: fifth file is a thing somebody should have to notice.
MIN_SENTENCES = 3


def test_every_teaching_file_names_the_drawer_as_the_product_fixture_home() -> None:
    """The prose says what `fixture_home` does, in every file that teaches it."""
    assert RIGHT != WRONG, (RIGHT, WRONG)
    wrong_in: list[str] = []
    right_in: list[str] = []
    for rel in TEACHING_FILES:
        path = ROOT / rel
        assert path.is_file(), f"{rel} is not in this tree — the census is reading nothing"
        text = path.read_text()
        if WRONG in text:
            wrong_in.append(rel)
        if RIGHT in text:
            right_in.append(rel)
    assert not wrong_in, (
        f"{wrong_in} spell `{WRONG}` as a product rule's fixture directory. "
        f"quality/gate.py::fixture_home plants a drawer rule's fixtures from "
        f"`{RIGHT}` — a product that believes the prose plants canaries where the "
        "engine never looks, and a canary that is never planted never fires."
    )
    assert len(right_in) >= MIN_SENTENCES, (
        f"only {right_in} name `{RIGHT}`; at least {MIN_SENTENCES} of "
        f"{list(TEACHING_FILES)} must, or this census is passing by reading nothing."
    )
