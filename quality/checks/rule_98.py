"""Rule 98: the harness fits its budget."""

from __future__ import annotations

import re
from pathlib import Path

from quality.checks._hub import CheckResult, _read
from quality.could_not_look import CouldNotLook

#: The working guide the harness loads into every session.
HARNESS_GUIDE = "CLAUDE.md"
HARNESS_SKILLS = ".claude/skills"
HARNESS_AGENTS = ".claude/agents"
#: The populations a target names: rule 98's `budgets:` keys.
BUDGET_KEYS: tuple[str, ...] = ("claude_md", "skill", "agent")
#: The duplication census's roots besides the guide, the README and the top-level product docs.
DUPLICATE_ROOTS: tuple[str, ...] = (HARNESS_SKILLS, HARNESS_AGENTS, "scripts")
DUPLICATE_SUFFIXES = frozenset({".md", ".sh", ".py", ""})
DUPLICATE_SKIP = frozenset({"__pycache__", "local", "node_modules"})
_BACKTICKED = re.compile(r"`([A-Za-z][\w-]*)`")


def _budgets(rule: dict) -> tuple[dict[str, int], int]:
    """The rule's targets and its bytes-per-token factor; could-not-look when either is missing."""
    budgets = rule.get("budgets") or {}
    per = rule.get("token_bytes")
    if set(budgets) != set(BUDGET_KEYS) or not all(isinstance(v, int) for v in budgets.values()):
        raise CouldNotLook(f"rule 98 `budgets:` must name exactly {', '.join(BUDGET_KEYS)}")
    if not isinstance(per, int) or per < 1:
        raise CouldNotLook("rule 98 declares no `token_bytes:` factor — the estimate reads nothing")
    return {str(k): int(v) for k, v in budgets.items()}, per


def harness_files(root: Path) -> list[tuple[str, str, Path]]:
    """(member, population, path) for the guide, every skill and every agent definition."""
    out: list[tuple[str, str, Path]] = []
    if (root / HARNESS_GUIDE).is_file():
        out.append(("claude_md", "claude_md", root / HARNESS_GUIDE))
    skills = sorted((root / HARNESS_SKILLS).glob("*/SKILL.md"))
    out.extend((f"skills/{path.parent.name}", "skill", path) for path in skills)
    agents = root / HARNESS_AGENTS
    for path in sorted(agents.rglob("*.md")) if agents.is_dir() else []:
        out.append((f"agents/{path.relative_to(agents).with_suffix('').as_posix()}", "agent", path))
    return out


def line_count(path: Path) -> int:
    """A file's lines as `wc -l` reads a file that ends in a newline."""
    return len(_read(path).splitlines())


def frontmatter(text: str) -> str:
    """The `---` block a skill or agent opens with; '' when it has none."""
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---", 3)
    return text[: end + 4] if end != -1 else ""


def named_skills(guide: str) -> set[str]:
    """The backticked names in the guide's opening blockquote: the skills loaded first."""
    names: set[str] = set()
    for line in guide.splitlines()[1:]:
        if line.startswith(">"):
            names.update(_BACKTICKED.findall(line))
        elif names or line.strip():
            break
    return names


def always_loaded(root: Path) -> list[tuple[str, int]]:
    """(path, bytes) loaded every session: the guide, the skills it names, every frontmatter."""
    guide = _read(root / HARNESS_GUIDE)
    named = named_skills(guide)
    out: list[tuple[str, int]] = []
    for _member, population, path in harness_files(root):
        text = _read(path)
        whole = population == "claude_md" or (population == "skill" and path.parent.name in named)
        part = text if whole else frontmatter(text)
        if part:
            out.append((path.relative_to(root).as_posix(), len(part.encode("utf-8"))))
    return out


def harness_budget(root: Path, rule: dict) -> CheckResult:
    """Rule 98. Each harness file's lines over its target, and the always-loaded set's tokens."""
    out = CheckResult()
    budgets, per = _budgets(rule)
    for member, population, path in harness_files(root):
        out.count(f"{population}_files")
        lines, target = line_count(path), budgets[population]
        if lines > target:
            out.hit(
                path.relative_to(root).as_posix(),
                target + 1,
                f"{lines} lines against the {population} target of {target} ({lines - target} "
                "over) — the harness fits its budget: cut toward the target, a long section moving "
                "to the skill's references, and lower the member's floor",
                klass=f"{member}.lines",
                weight=lines - target,
            )
    loaded = always_loaded(root)
    out.count("always_loaded_files", len(loaded))
    total = sum(size for _path, size in loaded)
    if total:
        # why-not a count in the text: a plant is judged by changed text, and every byte moves it.
        names = ["the working guide" if p == HARNESS_GUIDE else p for p, _size in loaded]
        out.hit(
            ".claude",
            0,
            f"the always-loaded set ({', '.join(names)}) is weighted by its estimated tokens, its "
            f"bytes ÷ {per} — every session pays it before its first question",
            klass="always_loaded.tokens",
            weight=-(-total // per),
        )
    return out


def duplicate_files(root: Path) -> list[str]:
    """The prose the duplication census reads: guide, README, product docs, harness, scripts."""
    out = [name for name in (HARNESS_GUIDE, "README.md") if (root / name).is_file()]
    out.extend(p.relative_to(root).as_posix() for p in sorted((root / "docs/product").glob("*.md")))
    for sub in DUPLICATE_ROOTS:
        base = root / sub
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            parts = set(path.relative_to(base).parts[:-1])
            if path.is_file() and path.suffix in DUPLICATE_SUFFIXES and not parts & DUPLICATE_SKIP:
                out.append(path.relative_to(root).as_posix())
    return out


def duplication(root: Path, rule: dict) -> list[tuple[str, str, list[str]]]:
    """(statement, proposed owner, every file stating it) per rule 98 `duplicates:` entry."""
    entries = rule.get("duplicates") or []
    if not entries or not all({"say", "pattern", "owner"} <= set(e) for e in entries):
        raise CouldNotLook("rule 98 `duplicates:` entries each declare say, pattern and owner")
    files = [(rel, _read(root / rel)) for rel in duplicate_files(root)]
    out: list[tuple[str, str, list[str]]] = []
    for entry in entries:
        pattern = re.compile(str(entry["pattern"]), re.IGNORECASE)
        found = [rel for rel, text in files if pattern.search(text)]
        out.append((str(entry["say"]), str(entry["owner"]), found))
    return out


def harness_census(root: Path, rule: dict) -> list[str]:
    """Rule 98's `census:` — each harness file beside its target and ceiling, then duplicates."""
    budgets, per = _budgets(rule)
    recorded = rule.get("ratchets") or {}
    lines = ["budgets (lines · the owner's target · ceiling = target + the member's floor):"]
    for member, population, path in harness_files(root):
        target = budgets[population]
        ceiling = target + int(recorded.get(f"{member}.lines", 0))
        rel = path.relative_to(root).as_posix()
        lines.append(f"  {rel}: {line_count(path)} lines · target {target} · ceiling {ceiling}")
    loaded = always_loaded(root)
    total = sum(size for _path, size in loaded)
    lines.append(
        f"always-loaded: ~{-(-total // per)} tokens ({total} bytes ÷ {per}) · ceiling "
        f"{recorded.get('always_loaded.tokens', 0)} · {', '.join(p for p, _n in loaded)}"
    )
    lines.append("duplication (reported, not refused — one rule, one place):")
    for say, owner, found in duplication(root, rule):
        rest = [rel for rel in found if rel != owner]
        held = "states it" if owner in found else "does not state it"
        lines.append(
            f"  {say!r} — owner {owner} ({held}); restated in {len(rest)} files — delete once "
            "the owner says which owns it"
        )
        lines.extend(f"    {rel}" for rel in rest)
    return lines
