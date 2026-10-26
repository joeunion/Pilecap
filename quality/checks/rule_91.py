"""Rule 91: a comment is the contract line."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

from apps.core.scaffold.copier import FENCE_LINE
from quality.checks._hub import CheckResult, _app_dirs, _exempt, _parse, _read
from quality.checks.rule_41_clause import _is_route_decorator
from quality.could_not_look import CouldNotLook

# --- rule 91: a comment is the contract line ------------------------------------

#: The members whose floors are not an app's: each root, and the skip it adds.
COMMENT_PLATFORM_MEMBERS: tuple[str, ...] = ("config", "quality", "scripts", "deploy", "pilecap")
#: The member that owns every module under `apps/` outside an app (`_app_dirs`'s predicate).
# does-not-cover: a directory whose `apps.py` declares no `AppConfig` is still read as an app.
COMMENT_APPS_ROOT = "apps_root"
COMMENT_SKIP: frozenset[str] = frozenset(
    {"__pycache__", "migrations", "node_modules", "canary", "negative"}
)
#: The product's drawers under the platform roots (`quality/local/`, `scripts/local/`).
COMMENT_DRAWER = "local"
_CITATION = r"(?:house\s+)?rules?\s+\d+(?:\s*[–-]\s*\d+)?|ADR\s+[A-Za-z][\w.]*-\d+[a-z]?"
#: A line that only cites decisions by id — the doctrine's one free line kind.
CITATION_LINE = re.compile(
    rf"^[\s(`*-]*(?:(?:see|per|cf\.?)\s+)?(?:{_CITATION})"
    rf"(?:\s*(?:,|;|·|/|and)\s*(?:{_CITATION}))*[\s.)`]*$",
    re.IGNORECASE,
)
#: A marker comment — a lower-case token and a colon opening it: an instrument, not prose.
MARKER_COMMENT = re.compile(r"^#\s*[a-z][\w-]*:\s")
#: A why-not line — the doctrine's second free kind, one line; its continuation is a tail.
WHY_NOT_LINE = re.compile(r"^why-not\b:?", re.IGNORECASE)
_COMMENT_MESSAGES = {
    "docstring-tail": "docstring line(s) past the contract line",
    "module-tail": "module-docstring line(s) past the contract line",
    "block-tail": "`#` block line(s) past the first",
    "narrative": "line(s) of narration (history, dates, scars) in a comment or docstring",
}


#: The class a file the floors never recorded is judged in: no floor exists for it, so zero.
NEW_FILE = "new-file"
#: The class a recorded path that carries no tail is reported in: the population is down-only.
STALE = "stale-population"


def read_population(root: Path, rule: dict) -> tuple[str, dict[str, set[str]]]:
    """(home, member → the recorded paths) from the rule's `population:`; an absent file is none."""
    home = str(rule.get("population") or "")
    path = root / home
    if not home or not path.is_file():
        return home, {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        raise CouldNotLook(f"rule 91's population {home} could not be read: {error}") from None
    if not isinstance(document, dict) or not all(
        isinstance(paths, list) and all(isinstance(p, str) for p in paths)
        for paths in document.values()
    ):
        raise CouldNotLook(f"rule 91's population {home} is not a mapping of member → paths")
    return home, {str(member): set(paths) for member, paths in document.items()}


def _free_line(text: str) -> bool:
    """Blank, a citation, a why-not or a declared blind spot: not counted against the budget."""
    body = text.strip().lstrip("#").strip()
    return (
        not body
        or bool(CITATION_LINE.match(body))
        or bool(WHY_NOT_LINE.match(body))
        or body.lower().startswith("does-not-cover:")
    )


def _contract_lines(node: ast.AST, lines: list[str]) -> int:
    """How many of `lines` are contract: the title, and a route's first description line."""
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return 1
    if not any(_is_route_decorator(dec) for dec in node.decorator_list):
        return 1
    for index, line in enumerate(lines[1:], 1):
        if line.strip():
            return index + 1
    return 1


def _comment_members(root: Path) -> list[tuple[str, Path, bool]]:
    """(member, root, recursive) for every app directory, then the platform's own members."""
    out: list[tuple[str, Path, bool]] = []
    base = root / "apps"
    if base.is_dir():
        out.extend((app.name, app, True) for app in _app_dirs(root))
        out.append((COMMENT_APPS_ROOT, base, True))
    for name in COMMENT_PLATFORM_MEMBERS:
        if (root / name).is_dir():
            out.append((name, root / name, True))
    return out


def _comment_files(member: str, base: Path, recursive: bool) -> list[Path]:
    paths = sorted(base.rglob("*.py")) if recursive else sorted(base.glob("*.py"))
    apps = {app.name for app in _app_dirs(base.parent)} if member == COMMENT_APPS_ROOT else set()
    out: list[Path] = []
    for path in paths:
        parts = path.relative_to(base).parts
        if COMMENT_SKIP & set(parts[:-1]):
            continue
        if len(parts) > 1 and (parts[0] in apps or parts[0].startswith(".")):
            continue
        if member in COMMENT_PLATFORM_MEMBERS and parts[0] == COMMENT_DRAWER:
            continue
        out.append(path)
    return out


def comment_census(path: Path, narrative: re.Pattern[str]) -> dict[str, tuple[int, int]]:
    """One module's four counts: class → (lines counted, first line counted)."""
    tree = _parse(path)
    if tree is None:
        return {}
    counts: dict[str, list[int]] = {}

    def add(klass: str, line: int, n: int = 1) -> None:
        if n <= 0:
            return
        entry = counts.setdefault(klass, [0, line])
        entry[0] += n
        entry[1] = min(entry[1], line)

    inside_strings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=True)
            if doc is None:
                continue
            first = node.body[0].lineno if node.body else 1
            lines = doc.splitlines()
            klass = "module-tail" if isinstance(node, ast.Module) else "docstring-tail"
            contract = _contract_lines(node, lines)
            add(klass, first, sum(1 for line in lines[contract:] if not _free_line(line)))
            add("narrative", first, sum(1 for line in lines if narrative.search(line)))
        elif isinstance(node, (ast.Constant, ast.JoinedStr)):
            end = getattr(node, "end_lineno", None) or node.lineno
            if end > node.lineno and (
                isinstance(node, ast.JoinedStr) or isinstance(node.value, str)
            ):
                inside_strings.update(range(node.lineno + 1, end + 1))
    depth = 0
    for number, line in enumerate(_read(path).splitlines(), 1):
        text = line.strip()
        if not text.startswith("#") or number in inside_strings:
            depth = 0
            continue
        if number <= 2 and (text.startswith("#!") or "coding" in text):
            continue
        if FENCE_LINE.match(text):
            depth = 0
            continue
        if narrative.search(text):
            add("narrative", number)
        if depth and not MARKER_COMMENT.match(text) and not _free_line(text):
            add("block-tail", number)
        depth += 1
    return {klass: (n, line) for klass, (n, line) in counts.items()}


def comment_doctrine(root: Path, rule: dict) -> CheckResult:
    """Rule 91. A docstring or a `#` block is its contract line; every further line is counted.

    One finding per module and class, weighted by its line count, so the ratchet reads lines.
    """
    out = CheckResult()
    phrases = [str(p) for p in rule.get("narrative") or []]
    if not phrases:
        raise CouldNotLook("rule 91 declares no `narrative:` phrase list — the class reads nothing")
    narrative = re.compile("|".join(f"(?:{p})" for p in phrases), re.IGNORECASE)
    home, population = read_population(root, rule)
    for member, base, recursive in _comment_members(root):
        files = _comment_files(member, base, recursive)
        recorded = population.get(member)
        if recorded is not None:
            out.count("population_members")
        if not files:
            continue
        is_app = base.parent == root / "apps" and recursive
        out.count("app_members" if is_app else "platform_members")
        seen: set[str] = set()
        for path in files:
            rel = path.relative_to(root).as_posix()
            if _exempt(rule, rel):
                continue
            out.count("files_read")
            seen.add(rel)
            census = comment_census(path, narrative)
            new = recorded is not None and rel not in recorded
            if recorded is not None and rel in recorded and not census:
                _stale(out, member, rel, home, "carries no counted line")
            for klass, (n, line) in sorted(census.items()):
                if new:
                    out.hit(
                        rel,
                        line,
                        f"{n} {_COMMENT_MESSAGES[klass]} in a file the floor never recorded — "
                        f"a new file is judged at zero ({home} lists the recorded ones): delete "
                        "the line(s), or cite the decision by id",
                        klass=f"{member}.{NEW_FILE}",
                        weight=n,
                    )
                    continue
                out.hit(
                    rel,
                    line,
                    f"{n} {_COMMENT_MESSAGES[klass]} — a comment is the contract line; a "
                    "further line is an invariant or a why-not, one each, and a decision is "
                    "cited by id",
                    klass=f"{member}.{klass}",
                    weight=n,
                )
        for rel in sorted((recorded or set()) - seen):
            _stale(out, member, rel, home, "is not on this tree")
    return out


def _stale(out: CheckResult, member: str, rel: str, home: str, why: str) -> None:
    out.hit(
        home,
        0,
        f"{rel} is recorded in {home} under {member} but {why} — delete its line: the "
        "population only falls",
        klass=f"{member}.{STALE}",
    )
