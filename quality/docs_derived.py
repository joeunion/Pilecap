"""Derived blocks: a Markdown region whose body a registered generator writes (ADR docs-1)."""

# Invariant: stdlib + `yaml` only, never Django — it runs on the system python and in `--fast`.
# does-not-cover: the prose around a block — a block makes a fact current, never its sentence.
# does-not-cover: a fence line inside a code fence — skipped, so a page may quote the grammar.

from __future__ import annotations

import ast
import fnmatch
import importlib.util
import os
import re
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from quality.could_not_look import CouldNotLook

#: The opening fence: the whole line, indented as the region's body is.
OPEN = re.compile(r"^(?P<indent>[ \t]*)<!-- derived: (?P<name>[a-z0-9][a-z0-9-]*) -->$")
#: The closing fence.
CLOSE = re.compile(r"^[ \t]*<!-- /derived -->$")
#: A Markdown code fence, inside which a fence line is text.
CODE = re.compile(r"^[ \t]*(```|~~~)")
#: The door files a discovered app may ship, in the order the doors paragraph names them.
DOORS = ("api.py", "mcp.py", "consumers.py", "receivers.py", "workflows.py")
#: Directories a default walk never enters.
PRUNE = {".git", ".venv", "node_modules", "vendor", "worktrees", "__pycache__", ".rung"}
#: Where the worked example's label glob is declared.
WORKED_HOME = "quality/sdk/census.py"
#: The alert census, whose total line the `alert-census` block carries.
ALERT_CENSUS = "deploy/observability/alerts/census.py"
#: The deploy runbook, its step openers (`**12. …`, `**19a. …`) and its parts.
DEPLOY_RUNBOOK = "docs/runbooks/deploy.md"
STEP = re.compile(r"^\*\*\d+[a-z]?\. ", re.M)
PART = re.compile(r"^## Part \d+ · ", re.M)


@dataclass(frozen=True)
class Block:
    """One fenced region: its file, its opening line (1-based), its generator and its body."""

    path: Path
    line: int
    name: str
    indent: str
    body: tuple[str, ...]


def _module(root: Path, rel: str) -> ast.Module:
    """`rel` under `root`, parsed; unreadable or unparsable is could-not-look."""
    try:
        return ast.parse((root / rel).read_text(), filename=rel)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{rel}: {exc}") from exc


def _yaml(root: Path, rel: str) -> dict[str, object]:
    """`rel` under `root`, loaded as a YAML mapping."""
    try:
        loaded = yaml.safe_load((root / rel).read_text())
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{rel}: {exc}") from exc
    if not isinstance(loaded, dict):
        raise CouldNotLook(f"{rel}: not a mapping")
    return loaded


def _binding(node: ast.AST) -> tuple[ast.expr | None, ast.expr | None]:
    """A single-target assignment's (target, value); `(None, None)` for anything else."""
    if isinstance(node, ast.AnnAssign):
        return node.target, node.value
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        return node.targets[0], node.value
    return None, None


def _depends_on(root: Path, app: str) -> tuple[str, ...]:
    """The `depends_on` tuple an app's `AppConfig` declares, read by `ast`."""
    rel = f"apps/{app}/apps.py"
    for node in ast.walk(_module(root, rel)):
        target, expr = _binding(node)
        if isinstance(target, ast.Name) and target.id == "depends_on" and expr is not None:
            try:
                value = ast.literal_eval(expr)
            except ValueError as exc:
                raise CouldNotLook(f"{rel}:{expr.lineno}: depends_on is not a literal") from exc
            if isinstance(value, tuple) and all(isinstance(v, str) for v in value):
                return value
            raise CouldNotLook(f"{rel}:{expr.lineno}: depends_on is not a tuple of names")
    raise CouldNotLook(f"{rel}: declares no depends_on")


def _worked_glob(root: Path) -> str:
    """The worked example's label glob, `WORKED_EXAMPLE` in its owner's module."""
    for node in _module(root, WORKED_HOME).body:
        target, value = _binding(node)
        if isinstance(target, ast.Name) and target.id == "WORKED_EXAMPLE":
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    raise CouldNotLook(f"{WORKED_HOME}: declares no WORKED_EXAMPLE string")


def discovered_apps(root: Path) -> list[str]:
    """Every `apps/<label>/` carrying an `apps.py`, the population `INSTALLED_APPS` derives from."""
    base = root / "apps"
    if not base.is_dir():
        raise CouldNotLook("apps/: not a directory")
    return sorted(p.parent.name for p in base.glob("*/apps.py"))


def app_map(root: Path) -> list[str]:
    """The app map: each discovered app, its `depends_on`, its door files, its partition."""
    platform = _yaml(root, "quality/partition.yaml").get("platform_apps")
    if not isinstance(platform, list):
        raise CouldNotLook("quality/partition.yaml: platform_apps is not a list")
    worked = _worked_glob(root)
    lines = [
        "| app | depends_on | door files | partition |",
        "|---|---|---|---|",
    ]
    for app in discovered_apps(root):
        deps = ", ".join(f"`{d}`" for d in _depends_on(root, app)) or "—"
        doors = " · ".join(f"`{d}`" for d in DOORS if (root / "apps" / app / d).is_file()) or "—"
        if app not in platform:
            kind = "product"
        elif fnmatch.fnmatchcase(app, worked):
            kind = "platform · worked example"
        else:
            kind = "platform"
        lines.append(f"| `{app}` | {deps} | {doors} | {kind} |")
    return lines


def rule_count(root: Path) -> list[str]:
    """How many house rules the engine holds: `rules.yaml`'s plus the product drawer's."""
    rules = _yaml(root, "quality/rules.yaml").get("rules")
    if not isinstance(rules, list):
        raise CouldNotLook("quality/rules.yaml: rules is not a list")
    local: object = []
    if (root / "quality/local/rules.yaml").is_file():
        local = _yaml(root, "quality/local/rules.yaml").get("rules") or []
    if not isinstance(local, list):
        raise CouldNotLook("quality/local/rules.yaml: rules is not a list")
    return [f"{len(rules) + len(local)} house rules — `python -m quality.gate --rules` lists them."]


def alert_census(root: Path) -> list[str]:
    """The alert census's own total line, as `deploy/observability/alerts/census.py` prints it."""
    spec = importlib.util.spec_from_file_location("_alert_census", root / ALERT_CENSUS)
    if spec is None or spec.loader is None or not (root / ALERT_CENSUS).is_file():
        raise CouldNotLook(f"{ALERT_CENSUS}: not a module")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        printed = module.render(module.census(root)).splitlines()
    except Exception as exc:  # noqa: BLE001 — any failure of the census is could-not-look
        raise CouldNotLook(f"{ALERT_CENSUS}: {exc}") from exc
    total = [line.strip() for line in printed if line.startswith("ALERTS = ")]
    if len(total) != 1:
        raise CouldNotLook(f"{ALERT_CENSUS}: printed {len(total)} `ALERTS = ` lines, not one")
    return [f"`{total[0]}`"]


def deploy_steps(root: Path) -> list[str]:
    """The deploy runbook's step census: its numbered step openers and its parts."""
    try:
        text = (root / DEPLOY_RUNBOOK).read_text()
    except OSError as exc:
        raise CouldNotLook(f"{DEPLOY_RUNBOOK}: {exc}") from exc
    steps = len(STEP.findall(text))
    parts = len(PART.findall(text))
    return [f"There are **{steps}** numbered steps, in **{parts}** parts."]


#: Every generator a block may name.
GENERATORS: dict[str, Callable[[Path], list[str]]] = {
    "alert-census": alert_census,
    "app-map": app_map,
    "deploy-steps": deploy_steps,
    "rule-count": rule_count,
}


def blocks(path: Path) -> Iterator[Block]:
    """Every fenced region in one Markdown file; an unclosed or nested fence is could-not-look."""
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"{path}: {exc}") from exc
    in_code = False
    opened: tuple[int, str, str] | None = None
    body: list[str] = []
    for number, text in enumerate(lines, 1):
        if CODE.match(text):
            in_code = not in_code
        if in_code:
            if opened:
                body.append(text)
            continue
        start, end = OPEN.match(text), CLOSE.match(text)
        if start and opened:
            raise CouldNotLook(
                f"{path}:{number}: a fence opens inside the block at line {opened[0]}"
            )
        if start:
            opened, body = (number, start["name"], start["indent"]), []
        elif end and opened:
            yield Block(path, opened[0], opened[1], opened[2], tuple(body))
            opened = None
        elif end:
            raise CouldNotLook(f"{path}:{number}: a closing fence with no block open")
        elif opened:
            body.append(text)
    if opened:
        raise CouldNotLook(f"{path}:{opened[0]}: block {opened[1]!r} is never closed")


def expected(block: Block, root: Path) -> tuple[str, ...]:
    """The body the block's generator writes at the fence's indent; an unknown name cannot look."""
    generate = GENERATORS.get(block.name)
    if generate is None:
        raise CouldNotLook(
            f"{block.path}:{block.line}: block {block.name!r} names no generator "
            f"(registered: {', '.join(sorted(GENERATORS))})"
        )
    return tuple(f"{block.indent}{line}" if line else "" for line in generate(root))


def markdown_files(root: Path) -> list[Path]:
    """Every `*.md` under `root`, the pruned directories left out."""
    found: list[Path] = []
    for here, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in PRUNE)
        found.extend(Path(here) / f for f in sorted(files) if f.endswith(".md"))
    return found


def stale(block: Block, want: tuple[str, ...]) -> str | None:
    """The first differing line as a finding, or None when the body is current."""
    if block.body == want:
        return None
    for offset in range(max(len(block.body), len(want))):
        have = block.body[offset] if offset < len(block.body) else "<the block ends>"
        need = want[offset] if offset < len(want) else "<the block ends>"
        if have != need:
            return (
                f"{block.path}:{block.line + 1 + offset}: derived block {block.name!r} is stale — "
                f"found {have!r}, the generator writes {need!r}"
            )
    return None


def write(path: Path, root: Path) -> bool:
    """Regenerate every block in one file in place; True when the file changed."""
    found = list(blocks(path))
    if not found:
        return False
    lines = path.read_text().splitlines()
    for block in reversed(found):
        lines[block.line : block.line + len(block.body)] = expected(block, root)
    text = "\n".join(lines) + "\n"
    if text == path.read_text():
        return False
    path.write_text(text)
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """`--check` (0 current · 1 stale · 2 could not look) or `--write`, over paths or the tree."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd()
    if "--root" in args:
        at = args.index("--root")
        root = Path(args[at + 1]).resolve()
        del args[at : at + 2]
    modes = [a for a in args if a in ("--check", "--write")]
    unknown = [a for a in args if a.startswith("-") and a not in ("--check", "--write")]
    if len(modes) != 1 or unknown:
        print("‼ docs-derived: exactly one of --check / --write, then paths (or none for the tree)")
        return 2
    paths = [root / a for a in args if not a.startswith("-")] or markdown_files(root)
    findings: list[str] = []
    seen = 0
    try:
        for path in paths:
            if modes[0] == "--write":
                if write(path, root):
                    print(f"  wrote {path.relative_to(root)}")
                continue
            for block in blocks(path):
                seen += 1
                finding = stale(block, expected(block, root))
                if finding:
                    findings.append(finding.replace(f"{root}{os.sep}", "", 1))
    except CouldNotLook as exc:
        print(f"‼ docs-derived COULD NOT LOOK: {str(exc).replace(f'{root}{os.sep}', '', 1)}")
        return 2
    if modes[0] == "--write":
        return 0
    for finding in findings:
        print(f"  VIOLATION  {finding}")
    if findings:
        print("  remedy: python3 -m quality.docs_derived --write — a derived block is never typed")
        return 1
    print(f"  ok — {seen} derived block(s) current across {len(paths)} Markdown file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
