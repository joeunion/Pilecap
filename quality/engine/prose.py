"""The prose bound: per root, prose lines over code lines, recorded and down-only (ADR gate-6)."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

from quality import worlds as W
from quality.engine._hub import _DOC, ROOT

#: Each recorded root, the directory it measures; a `local/` drawer is the product's.
PROSE_ROOTS: dict[str, str] = {
    "scripts": "scripts",
    "quality_gate": "quality/djb",
    "quality_tests": "quality/tests",
    "deploy": "deploy",
}
HOME = "quality/rules.yaml `prose: prose_over_code:`"
_SKIP = frozenset({"__pycache__", "local", "node_modules"})
#: The fixture worlds, data and not modules: the set `gate_tests.WORLDS_MYPY` names.
WORLDS = (
    "quality/tests/fixtures/collection_world/",
    "quality/tests/fixtures/golden_copy/",
    "quality/tests/fixtures/runbook/",
)
_SHELL_PROSE = re.compile(r"^\s*(#|$)")


def prose_and_code(path: Path) -> tuple[int, int]:
    """(prose, code) lines: shell is `^\\s*(#|$)` over the rest; Python is docstring + comment rows over the other non-blank rows by `tokenize`."""  # noqa: E501
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if path.suffix == ".sh":
        prose = sum(1 for line in lines if _SHELL_PROSE.match(line))
        return prose, len(lines) - prose
    rows: set[int] = set()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and not lines[tok.start[0] - 1][: tok.start[1]].strip():
                rows.add(tok.start[0])
        for node in ast.walk(ast.parse(text)):
            body = getattr(node, "body", None)
            if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
                doc = body[0].value
                if isinstance(doc, ast.Constant) and isinstance(doc.value, str):
                    rows.update(range(doc.lineno, (doc.end_lineno or doc.lineno) + 1))
    except (SyntaxError, tokenize.TokenError, ValueError):
        return 0, sum(1 for line in lines if line.strip())
    code = sum(1 for n, line in enumerate(lines, 1) if line.strip() and n not in rows)
    return len(rows), code


def prose_files(root: Path, sub: str) -> list[Path]:
    """Every `.sh` and `.py` file under one root, its skipped segments and `WORLDS` left out."""
    base = root / sub
    return [
        path
        for path in sorted(base.rglob("*"))
        if path.is_file()
        and path.suffix in (".sh", ".py")
        and not _SKIP & set(path.relative_to(base).parts)
        and not path.relative_to(root).as_posix().startswith(WORLDS)
    ]


def prose_census(root: Path = ROOT) -> dict[str, tuple[int, list[tuple[int, str]]]]:
    """Per root: the ratio in thousandths, and the worst three files by their own ratio."""
    out: dict[str, tuple[int, list[tuple[int, str]]]] = {}
    for key, sub in PROSE_ROOTS.items():
        prose = code = 0
        files: list[tuple[int, str]] = []
        for path in prose_files(root, sub):
            p, c = prose_and_code(path)
            prose, code = prose + p, code + c
            if c:
                files.append((p * 1000 // c, path.relative_to(root).as_posix()))
        worst = sorted(files, key=lambda pair: (-pair[0], pair[1]))[:3]
        out[key] = (prose * 1000 // max(code, 1), worst)
    return out


def prose_verdicts(
    recorded: dict | None = None, root: Path = ROOT
) -> tuple[list[str], list[str], list[str]]:
    """(the census lines, the violations with their paste line, the room notes)."""
    if recorded is None:
        recorded = (_DOC.get("prose") or {}).get("prose_over_code") or {}
    lines: list[str] = []
    problems: list[str] = []
    notes: list[str] = []
    for key, (measured, worst) in prose_census(root).items():
        named = ", ".join(f"{rel} {n / 1000:.3f}" for n, rel in worst)
        held = recorded.get(key)
        record = "unrecorded" if held is None else f"recorded {int(held) / 1000:.3f}"
        lines.append(f"prose: {key} {measured / 1000:.3f} ({record}) · worst: {named}")
        if held is None:
            problems.append(
                f"prose: {key} has no recorded bound (measured {measured / 1000:.3f}) — a root "
                f"nobody recorded is unread, never clean. The line to paste under {HOME}:\n"
                f"  {key}: {measured}"
            )
            continue
        bound = W.Bound(
            direction="ceiling",
            recorded=int(held),
            measured=measured,
            home=HOME,
            klass=key,
            subject=f"prose over code under {PROSE_ROOTS[key]}/ (thousandths)",
            word="bound",
        )
        if bound.breached:
            problems.append(
                f"prose: {bound.breach_clause()}; the worst files: {named}. Cut the prose, or "
                f"raise the number in a diff a reviewer reads. The line to paste, verbatim:\n"
                f"  {key}: {measured}"
            )
        room = W.room_note(bound)
        if room:
            notes.append(room)
    return lines, problems, notes
