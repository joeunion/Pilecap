"""Rule 89: no plan coordinate in the code."""

from __future__ import annotations

import re
from pathlib import Path

from quality import loop_key as LK
from quality.checks._hub import CheckResult, _exempt
from quality.worlds import comment_reason

# --- rule 89: no plan coordinate in the code ----------------------------------
#
# A plan coordinate — a queue row, a rung, a rider, a survey item, a cycle —
# names a document the code does not ship with and a reader cannot open. A
# comment that says WHY carries the reason; one that says WHO ASKED points at a
# plan nobody reading the code has. The grammar is the plans' own id families
# (the statement lists each), read as words: not after a letter, digit, `.`,
# `$`, `-`, `{` or `/`, and not followed by a letter, digit, `=`, `}` or `-`, so
# a variable, a path segment and an identifier are not coordinates. A shell
# declaration line (`local`, `declare`, `readonly`, `typeset`) is code naming
# variables and is not read. Counted per owner (`<app>.coordinate`,
# `quality.coordinate`, `scripts.coordinate`, `frontend.coordinate`), recorded
# at the measured count and down to zero.

#: Each family, with the plan grammar it comes from (the statement repeats them).
COORDINATE_FAMILIES: tuple[str, ...] = (
    r"N\d{3,4}",  # a queue row
    r"R[DI]-\d+",  # a defects-lane or roads-index rung
    r"S\d*-\d+",  # a survey item, or a surfaces rung
    r"S\d+\.\d",  # a surfaces design section
    r"P\d\d",  # a cycle
    r"W\d-R\d",  # a wave's rung
    r"FE-\d",  # a face rung
    r"B-CORE-\d",  # a batch rung
    r"HC\d",  # a hygiene-check item
    r"RACE-\d",  # a race finding
    r"F-\d+",  # a verifier's finding
    r"H\d+",  # a review's high finding
    r"W\d",  # a wave
    r"C-[A-Z]+-[A-Za-z0-9]+",  # a consolidation rung
    r"item \d+ of the builder's seven|the builder's seven, item \d+",  # a plan list's item
)
COORDINATE_RE = re.compile(r"(?<![\w.$\-{/])(?:" + "|".join(COORDINATE_FAMILIES) + r")(?![\w=}\-])")
#: The roots the census reads — the code a product ships and a reader opens.
COORDINATE_ROOTS: tuple[str, ...] = ("apps", "quality", "scripts", "frontend/src")
#: Directories never read: fixtures are planted wrongness, and the browser
#: tree's build and dependency output is nobody's prose.
COORDINATE_SKIP: frozenset[str] = frozenset(
    {"__pycache__", "canary", "negative", "node_modules", ".next", ".turbo", "dist", "build"}
)
#: The line-comment token a valve is written with, by suffix; a file of any
#: other suffix has no valve and its coordinate is fixed, never excused.
_COORDINATE_COMMENT = {
    ".py": "#",
    ".sh": "#",
    ".yaml": "#",
    ".yml": "#",
    ".toml": "#",
    ".ts": "//",
    ".tsx": "//",
    ".js": "//",
    ".jsx": "//",
    ".mjs": "//",
    ".cjs": "//",
}
_SHELL_DECLARATION = re.compile(r"^\s*(?:local|declare|readonly|typeset)\s")
#: A linter's codes after `noqa:` are the linter's vocabulary, never a plan's.
_NOQA_CODES = re.compile(r"noqa:\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*")
#: A declared blind spot names its trigger, and the ledger row is its trigger's home.
_DOES_NOT_COVER = re.compile(r"(?:#|//)\s*does-not-cover:")


def _coordinate_owner(rel: str) -> str:
    parts = rel.split("/")
    if parts[0] == "apps" and len(parts) > 2:
        return parts[1]
    return "frontend" if parts[0] == "frontend" else parts[0]


def _coordinate_files(root: Path) -> list[Path]:
    """Every file under the census's roots, minus the skipped directories."""
    out: list[Path] = []
    for sub in COORDINATE_ROOTS:
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if COORDINATE_SKIP & set(path.relative_to(base).parts):
                continue
            out.append(path)
    return out


def no_plan_coordinates(root: Path, rule: dict) -> CheckResult:
    """Rule 89. No plan coordinate in the code under the census roots.

    A line carrying a word of `COORDINATE_FAMILIES` is one finding, counted
    under its owner's `coordinate` class, unless the line (or the contiguous
    comment block above it) carries `<comment> coordinate: <reason>`. The
    readers of the grammar — the queue instruments and the dated-trigger
    census — are `scope.exemptions`, each with its reason.
    """
    out = CheckResult()
    for path in _coordinate_files(root):
        rel = path.relative_to(root).as_posix()
        if _exempt(rule, rel):
            out.count("readers_exempt")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out.count("files_scanned")
        comment = _COORDINATE_COMMENT.get(path.suffix)
        lines = text.splitlines()
        shell = path.suffix == ".sh"
        for number, line in enumerate(lines, 1):
            if _DOES_NOT_COVER.search(line):
                continue
            found = COORDINATE_RE.search(_NOQA_CODES.sub("", line))
            if found is None:
                continue
            if shell and _SHELL_DECLARATION.match(line):
                continue
            if comment is not None:
                pattern = re.compile(re.escape(comment) + r"\s*coordinate:\s*(.*)$")
                valve = comment_reason(lines, number, pattern, comment=comment)
                if valve is not None and valve.holds:
                    out.count("coordinate_valves")
                    continue
            out.hit(
                rel,
                number,
                f"`{found.group(0)}` is a plan coordinate — it names a document the code "
                "does not ship with; say the reason in words, or record "
                "`coordinate: <reason>` on the line when the id itself is the subject",
                klass=f"{_coordinate_owner(rel)}.coordinate",
            )
    return out


def loop_key_exclusions_are_derived(root: Path, rule: dict) -> CheckResult:
    """Rule 90. The loop key's excluded paths are derived: no typed list, no stale non-read.

    The census (`quality/loop_key.py`) honours a module's non-read declarations,
    so one that outlived its quote would hide the next quote written there.
    """
    out = CheckResult()
    typed, scanned = LK.typed_exclusions(root)
    out.count("assignment_modules", scanned)
    for site in typed:
        if _exempt(rule, site.path):
            continue
        out.hit(
            site.path,
            site.line,
            f"`{site.subject}` assigns a typed list of docs paths under the loop key's name — "
            "the key's excluded paths are `quality.loop_key.prose_paths()`, derived from what "
            "the legs quote; delete the list and call the census",
            klass="typed-exclusion",
        )
    stale, declared = LK.stale_declarations(root)
    out.count("declarations_read", declared)
    out.count("reader_roots", sum((root / name).is_dir() for name in LK.READER_ROOTS))
    for site in stale:
        out.hit(
            site.path,
            site.line,
            f"declares `{site.subject}` a non-read and the module never quotes it — a stale "
            "declaration; delete the path from the line, or the line",
            klass="stale-declaration",
        )
    stale_measured, unrun, measured = LK.measured_findings(root)
    out.count("measured_declarations", measured)
    for site in stale_measured:
        out.hit(
            site.path,
            site.line,
            f"declares `{site.subject}` measured at the commit and the module never quotes it — "
            "a stale declaration; delete the path from the line, or the line",
            klass="stale-measured",
        )
    for site in unrun:
        out.hit(
            site.path,
            site.line,
            f"declares `{site.subject}` measured at the commit, and no `static` leg of "
            f"`{LK.GATE}` runs this module as `<module> --check` from directly under `scripts/` — "
            "the declaration is not honoured; delete the line",
            klass="unrun-measured",
        )
    return out
