# census: cross-app population=apps/**/*.py,config/**/*.py for readers of the scope keys
"""Who is allowed to read a token's ceiling, measured over the whole tree.

ADR ident-7 part 1: scopes are read in the door seams and **nowhere below**. A
service, selector or policy that consulted `token.scopes` would be the second
permission system this design exists to refuse — and a second permission system
does not announce itself, it just slowly starts disagreeing with the first.

This module is the measurement the quality-batch rule will ratchet from. It
fails on the day a new reader appears, which is the day somebody can still be
asked whether they meant it.
"""

from __future__ import annotations

import ast
from pathlib import Path

from apps.core.tests.tree_census import source_tree, vanishing_source_file

#: Everything a reader could be doing: taking the ceiling off a token row, or
#: asking the one predicate about it. Both are walked with `ast` rather than
#: grepped, so a mention inside a docstring or a comment is not a reader.
CEILING_ATTRIBUTE = "scopes"
CEILING_PREDICATES = frozenset({"within_ceiling", "granted_scopes"})

#: The declared population, and every entry says which door it is.
#:
#: The three ENFORCEMENT seams are the ones ADR ident-7 names — one per door
#: that can be handed a token. The MINT doors are readers too and always were:
#: something has to write the ceiling down and echo it back. The vocabulary
#: module owns the predicate itself.
#:
#: Declaring the column (`accounts/models.py`) and its wire shape
#: (`accounts/schemas.py`) is deliberately NOT reading it, and the walk agrees:
#: a field is bound, never fetched, so neither module appears below. That is the
#: distinction worth keeping — "where the ceiling is defined" and "who consults
#: it" are different questions, and only the second one can grow into a second
#: permission system.
#:
#: What must never appear here is a `selectors.py`, a `policies.py`, or a
#: `services.py` that is not the mint — see the shape assertion below, which is
#: the half of this test that keeps meaning something after somebody legitimately
#: adds a fourth door.
DECLARED_READERS: dict[str, str] = {
    "config/api.py": "the REST door's ceiling check, before the view",
    "apps/core/mcp.py": "the MCP door's ceiling check, inside tool_call",
    "apps/realtime/consumers.py": "the socket door's per-frame narrowing",
    "apps/core/api/scopes.py": "the vocabulary and the one predicate",
    "apps/accounts/api.py": "the mint door: writes the ceiling and echoes it",
    "apps/accounts/services.py": "the mint itself: stores what the door validated",
    "apps/accounts/management/commands/issue_token.py": "the shell mint door",
    "apps/accounts/management/commands/seed.py": "the shell mint door, for development",
}


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _sources() -> list[Path]:
    root = _root()
    return [
        source
        for source in [*(root / "apps").rglob("*.py"), *(root / "config").rglob("*.py")]
        if "/tests/" not in str(source) and not source.name.startswith("test_")
    ]


def _reads_the_ceiling(source: Path) -> list[str]:
    """Every place this module reads a ceiling, as `line: what`. `[]` when none.

    Three shapes, because there are three ways to reach the same value: the
    attribute (`token.scopes`), the reflective read (`getattr(x, "scopes")`),
    and a call to the predicate that interprets it.
    """
    tree = source_tree(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == CEILING_ATTRIBUTE:
            found.append(f"{node.lineno}: .{CEILING_ATTRIBUTE}")
        elif isinstance(node, ast.Call):
            callee = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if callee in CEILING_PREDICATES:
                found.append(f"{node.lineno}: {callee}()")
            elif callee == "getattr" and len(node.args) >= 2:
                named = node.args[1]
                if isinstance(named, ast.Constant) and named.value == CEILING_ATTRIBUTE:
                    found.append(f'{node.lineno}: getattr(…, "{CEILING_ATTRIBUTE}")')
        elif isinstance(node, ast.keyword) and node.arg == CEILING_ATTRIBUTE:
            found.append(f"{node.lineno}: {CEILING_ATTRIBUTE}=")
    return found


def measured_readers() -> dict[str, list[str]]:
    """Every module under `apps/` or `config/` that reads a ceiling."""
    root = _root()
    return {
        str(source.relative_to(root)): reads
        for source in _sources()
        if (reads := _reads_the_ceiling(source))
    }


def test_the_ceiling_is_read_only_where_it_is_declared_to_be() -> None:
    """The measurement itself: the population, pinned.

    A pin and not a ceiling-count, because the interesting fact is *which*
    modules and not how many: a service quietly joining the list is the whole
    failure mode, and a number would let it in as long as something else left.
    """
    measured = measured_readers()
    assert measured, "nothing was walked, so this test cannot fail"
    undeclared = sorted(set(measured) - set(DECLARED_READERS))
    assert undeclared == [], (
        "these modules read a token's ceiling and are not declared door seams: "
        + "; ".join(f"{name} ({', '.join(measured[name])})" for name in undeclared)
    )
    # The other direction, so a declaration that stopped being true is noticed
    # rather than quietly kept: a seam nobody reads any more is a stale entry.
    stale = sorted(set(DECLARED_READERS) - set(measured))
    assert stale == [], f"declared as readers and no longer reading: {stale}"


def test_no_reader_sits_below_a_door() -> None:
    """The shape, which is what still holds when the population legitimately grows.

    A product adding a fifth door adds a reader and should. What it must never
    add is a reader in a selector, in a policy, or in a service that is not the
    one minting the credential — because each of those is somewhere the ceiling
    would start deciding what the ROLE is there to decide, and the two would
    then be free to disagree.
    """
    below_the_doors = [
        name
        for name in measured_readers()
        if Path(name).name in {"selectors.py", "policies.py"}
        or (Path(name).name == "services.py" and name != "apps/accounts/services.py")
    ]
    assert below_the_doors == [], (
        "the ceiling is being read below the doors, which is the second permission "
        f"system ADR ident-7 refuses: {below_the_doors}"
    )


def test_the_enforcement_seams_are_the_three_doors() -> None:
    """One check per door a token can be presented at, and no more.

    Named separately from the pin above because this is the sentence the ADR
    actually makes — three doors, three checks — and a reader coming or going at
    a mint is a different kind of event from a fourth enforcement point
    appearing.
    """
    predicate_readers = {
        name
        for name, reads in measured_readers().items()
        if any("within_ceiling()" in read or "granted_scopes()" in read for read in reads)
    }
    assert predicate_readers == {
        "config/api.py",
        "apps/core/mcp.py",
        "apps/realtime/consumers.py",
        "apps/core/api/scopes.py",
    }


def test_the_reader_census_tolerates_a_file_that_vanishes_at_open() -> None:
    """The falsifier for the tolerant read. RED before RACE-1: `FileNotFoundError`.

    The plant reads no ceiling, so a census that survives it survives by
    skipping it.
    """
    with vanishing_source_file() as planted:
        assert measured_readers() is not None
        assert not planted.exists(), "the census never opened the plant — this drove nothing"
