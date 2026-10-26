"""Rule 46: every door pair owes a parity test."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse, api_modules

# --- rule 46: every door pair owes a parity test -------------------------------
#
# . Rule 17 diffs two REGISTRIES and proves a capability exists on both
# doors; it cannot see one consumer answering two credentials two ways,
# and it cannot see two doors serialising one row differently . Both of
# those were caught by a test in the owning app, and the family had exactly one
# member with nothing making a new door pair grow one. This is the census that
# makes it grow: the POPULATION is derived from the door modules that exist, and
# the ANSWER is a module-level `DOOR_PAIR` marker in that app's tests.

# : The module-level name a parity test claims its pair with.
_DOOR_PAIR_MARKER = "DOOR_PAIR"


def _door_pairs_owed(app: Path) -> list[tuple[tuple[str, str], Path]]:
    """The pairs this app owes a parity test for, DERIVED from the doors it has.

    Two kinds, and both are read off files rather than off any list: an app with
    a REST door and an `mcp.py` owes `(rest, mcp)`, because those are two
    renderings of one capability and rule 17 compares the registries and not the
    wire; an app with a `consumers.py` owes `(session, bearer)`, because the
    socket door has no second registry to diff and the credential is the axis
    came in on.
    """
    owed: list[tuple[tuple[str, str], Path]] = []
    rest = bool(api_modules(app))
    mcp = app / "mcp.py"
    if rest and mcp.is_file():
        owed.append((("rest", "mcp"), mcp))
    consumers = app / "consumers.py"
    if consumers.is_file():
        owed.append((("session", "bearer"), consumers))
    return owed


def _door_pairs_claimed(app: Path) -> list[tuple[tuple[str, str], Path, int]]:
    """`(pair, path, line)` for every `DOOR_PAIR` marker in this app's tests.

    Read by AST off a module-level assignment, never by grep: a marker inside a
    function or a docstring is not a claim about the module. Both shapes are
    accepted — one pair, or a sequence of them for a module that answers two —
    and anything else is reported as a malformed claim rather than ignored.
    """
    claimed: list[tuple[tuple[str, str], Path, int]] = []
    tests = app / "tests"
    if not tests.is_dir():
        return claimed
    for path in sorted(tests.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = _parse(path)
        if tree is None:
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if _DOOR_PAIR_MARKER not in names:
                continue
            for pair in _pairs_in(node.value):
                claimed.append((pair, path, node.lineno))
    return claimed


def _pairs_in(value: ast.expr) -> list[tuple[str, str]]:
    """Every `("a", "b")` a `DOOR_PAIR` marker's right-hand side holds."""
    if not isinstance(value, (ast.Tuple, ast.List)):
        return []
    elements = list(value.elts)
    if all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in elements):
        if len(elements) == 2:
            return [(str(elements[0].value), str(elements[1].value))]  # type: ignore[attr-defined]
        return []
    out: list[tuple[str, str]] = []
    for element in elements:
        out.extend(_pairs_in(element))
    return out


def door_pair_parity(root: Path, rule: dict) -> CheckResult:
    """Rule 46. Every door pair an app has owes a named parity test in that app.

    The population is derived; the answer is claimed. A pair is answered by a
    module-level `DOOR_PAIR = ("rest", "mcp")` in the owning app's `tests/`, and
    the census is the difference. A marker claiming a pair the app does not own
    is a lie in the other direction and fires as one — an app can otherwise
    answer its backlog by writing the marker into any file.

    MEASURED BEFORE ENFORCED (the retired door-parity-measurement.md): the backlog is
    ratcheted per APP, so a new app's first door pair is a violation from birth
    while the five apps that predate the rule are a standing backlog that may
    shrink and never grow.
    """
    out = CheckResult()
    for app in _app_dirs(root):
        label = app.name
        owed = _door_pairs_owed(app)
        claimed = _door_pairs_claimed(app)
        out.count("apps_scanned", 1)
        out.count("door_pairs_owed", len(owed))
        answered = {pair for pair, _, _ in claimed}
        owed_pairs = {pair for pair, _ in owed}

        for pair, module in owed:
            if pair in answered:
                out.count("door_pairs_answered", 1)
                continue
            out.hit(
                module,
                1,
                f"`{label}` has both halves of the ({pair[0]}, {pair[1]}) door pair and no "
                f"test in `apps/{label}/tests/` claims it. Rule 17 diffs the two REGISTRIES "
                "and proves the capability exists on both; it cannot see the two doors "
                "answering it differently — a serialization that differs by rendering "
                "or a credential that resolves a different hat, both of which were "
                "found by a test of exactly this shape and by nothing else. Write the parity "
                f"test and mark it `{_DOOR_PAIR_MARKER} = ({pair[0]!r}, {pair[1]!r})` at "
                "module level",
                root=root,
                klass=label,
            )
        for pair, path, line in claimed:
            if pair in owed_pairs:
                continue
            out.hit(
                path,
                line,
                f"this module claims the ({pair[0]}, {pair[1]}) door pair for `{label}` and "
                f"`{label}` does not own that pair — the doors it would be about are not "
                "there. A marker is how an app says a pair is answered, so a marker for a "
                "pair nobody owes retires a debt that was never taken on. Drop it, or name "
                "the pair this module really tests",
                root=root,
                klass="claim",
            )
    return out
