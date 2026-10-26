"""The threat-model census: every door and every noun owns a row, every citation resolves."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quality.checks.rule_36 import _schema_modules  # noqa: E402
from quality.checks.rule_93 import _calls_the_mark  # noqa: E402
from quality.could_not_look import CouldNotLook, tool_said  # noqa: E402

LEDGER = "docs/product/threat-model.md"
PARTITION = "quality/partition.yaml"
#: The five doors of `CLAUDE.md` § "The stack, and the doors", webhooks split by direction.
DOORS = ("REST", "MCP", "sockets", "webhooks in", "webhooks out", "workflows")
THREATS = (
    "spoofing",
    "tampering",
    "repudiation",
    "information disclosure",
    "denial of service",
    "elevation of privilege",
)
#: The 45 CFR 164.312 technical safeguards the map answers, by paragraph.
HIPAA = ("(a)(1)", "(b)", "(c)(1)", "(d)", "(e)(1)")
SECTIONS = (
    "§ Trust boundaries",
    "§ STRIDE per door",
    "§ Nouns",
    "§ HIPAA 164.312",
    "§ Pentest brief",
)
DOES_NOT_COVER = (
    "does_not_cover: whether a cell is true — a row can be present, cited and wrong",
    "does_not_cover: threats across doors (webhook → workflow → socket frame) — no cell holds one",
    "does_not_cover: threats outside the six STRIDE columns (supply chain, operator console)",
    "does_not_cover: whether an open:/gap: row id is booked — only that one is named",
)

# A cite is a path with an extension OR a slashed path without one (`deploy/Caddyfile:71`).
_CITE = re.compile(r"`([A-Za-z0-9_./-]+?(?:\.[A-Za-z0-9]+|/[A-Za-z0-9_-]+)):(\d+)(?:-(\d+))?`")
_TEST = re.compile(r"`([A-Za-z0-9_./-]+\.py)::(test_[A-Za-z0-9_]+)`")
#: A mechanism named by its definition: `path::name` or `path::Cls.member`, never a test.
_NAMED = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)::(?!test_)([A-Za-z_][A-Za-z0-9_.]*)`")
_ROW_ID = re.compile(r"\b(?:open|gap):\s*(?:N\d+|LS-[A-Z]+-\d+)")
_COMMENT = re.compile(r"<!--.*?-->")
_NAME = re.compile(r"`([a-z_]+)`")


@dataclass
class Table:
    """One section's first table: its header cells and its rows, comments stripped."""

    header: list[str]
    rows: list[list[str]] = field(default_factory=list)


def cells(line: str) -> list[str]:
    """A markdown table row's cells, stripped, HTML comments removed."""
    body = _COMMENT.sub("", line).strip().strip("|")
    return [c.strip() for c in body.split("|")]


def sections(text: str) -> dict[str, str]:
    """Each `## ` heading's body, keyed by the heading text."""
    out: dict[str, str] = {}
    name: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if name is not None:
                out[name] = "\n".join(lines)
            name, lines = line[3:].strip(), []
        elif name is not None:
            lines.append(line)
    if name is not None:
        out[name] = "\n".join(lines)
    return out


def table(body: str) -> Table | None:
    """The first markdown table in `body`, or None."""
    rows = [ln for ln in body.splitlines() if ln.lstrip().startswith("|")]
    if len(rows) < 2:
        return None
    found = Table(cells(rows[0]))
    for line in rows[1:]:
        row = cells(line)
        if all(set(c) <= set("-: ") for c in row):
            continue
        found.rows.append(row)
    return found


def key(cell: str) -> str:
    """A row's first cell as a name: backticks and bold dropped."""
    return cell.replace("`", "").replace("*", "").strip()


def platform_apps(root: Path) -> set[str]:
    """`quality/partition.yaml`'s `platform_apps` list, read without a YAML library."""
    try:
        text = (root / PARTITION).read_text()
    except OSError as exc:
        raise CouldNotLook(f"{PARTITION} could not be read: {exc}") from exc
    found: set[str] = set()
    inside = False
    for line in text.splitlines():
        if line.startswith("platform_apps:"):
            inside = True
            continue
        if inside:
            item = re.match(r"^\s+-\s+([a-z_]+)\s*$", line)
            if item:
                found.add(item.group(1))
            elif line.strip() and not line.startswith(" "):
                break
    if not found:
        raise CouldNotLook(f"{PARTITION} names no platform_apps")
    return found


def introspect(root: Path, dump: Path | None) -> dict[str, object]:
    """The `manage.py introspect` document: read from `dump`, else run under the checkout."""
    if dump is not None:
        try:
            loaded = json.loads(dump.read_text())
        except (OSError, ValueError) as exc:
            raise CouldNotLook(f"the introspect dump {dump} could not be read: {exc}") from exc
        return dict(loaded)
    venv = root / ".venv" / "bin" / "python"
    python = str(venv) if os.access(venv, os.X_OK) else sys.executable
    done = subprocess.run(
        [python, "manage.py", "introspect"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode:
        raise CouldNotLook(f"manage.py introspect exited {done.returncode}: {done.stderr.strip()}")
    try:
        return dict(json.loads(done.stdout))
    except ValueError as exc:
        raise CouldNotLook(f"manage.py introspect printed no JSON: {exc}") from exc


def nouns(root: Path, doc: dict[str, object]) -> list[str]:
    """`app.Model` for every introspected model whose app is a platform app or lives in `apps/`."""
    labels = platform_apps(root) | {p.parent.name for p in (root / "apps").glob("*/apps.py")}
    models = doc.get("models")
    if not isinstance(models, list) or not models:
        raise CouldNotLook("the introspect document carries no models")
    return sorted(f"{m['app']}.{m['name']}" for m in models if m.get("app") in labels)


def personal_fields(root: Path) -> dict[str, set[str]]:
    """Each `Out` schema's fields carrying a `personal(...)` mark, by schema class name."""
    found: dict[str, set[str]] = {}
    for path in _schema_modules(root):
        try:
            tree = ast.parse(path.read_text())
        except (OSError, SyntaxError) as exc:
            raise CouldNotLook(f"{path} could not be parsed: {exc}") from exc
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and node.name.endswith("Out")):
                continue
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and _calls_the_mark(stmt.value)
                ):
                    found.setdefault(node.name, set()).add(stmt.target.id)
    return found


def _paths_reader() -> ModuleType:
    """`scripts/dangling_paths.py` beside this file: the one judge of a cited path, name or line."""
    path = Path(__file__).resolve().parent / "dangling_paths.py"
    spec = importlib.util.spec_from_file_location("djb_dangling_paths", path)
    if spec is None or spec.loader is None:
        raise CouldNotLook(f"the citation judge {path} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except (OSError, SyntaxError) as exc:
        raise CouldNotLook(f"the citation judge {path} could not be loaded: {exc}") from exc
    return module


def citations(root: Path, text: str) -> list[str]:
    """One refusal per `path`, `path::name` or `path:line` in the ledger that resolves nowhere."""
    reader = _paths_reader()
    try:
        judge = reader.Judge(root, set(), set())
    except (OSError, subprocess.CalledProcessError) as exc:
        said = tool_said(getattr(exc, "stderr", None))
        raise CouldNotLook(f"the citation judge could not list {root}: {exc}{said}") from exc
    _sites, found = reader.cited(judge, LEDGER, text, "the tree")
    return [str(line) for line in found]


def mechanism(cell: str) -> bool:
    """Whether a cell cites a `path::name`, a file:line, or names an open row."""
    return bool(_NAMED.search(cell) or _CITE.search(cell) or _ROW_ID.search(cell))


def judge(root: Path, ledger_text: str, doc: dict[str, object]) -> list[str]:
    """Every refusal the ledger earns against the derived populations; empty when it closes."""
    found = sections(ledger_text)
    out = [f"the ledger has no `## {name}` section" for name in SECTIONS if name not in found]
    if out:
        return out
    tables = {name: table(found[name]) for name in SECTIONS[:4]}
    for name, tab in tables.items():
        if tab is None or not tab.rows:
            out.append(f"`## {name}` holds no table")
    if out:
        return out

    stride = tables["§ STRIDE per door"]
    assert stride is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    seen: set[str] = set()
    for row in stride.rows:
        door = key(row[0])
        if door not in DOORS:
            out.append(f"STRIDE row `{door}` is no door — the doors are {', '.join(DOORS)}")
            continue
        seen.add(door)
        if len(row) != 1 + len(THREATS):
            out.append(f"STRIDE row `{door}` has {len(row) - 1} threat cells, not {len(THREATS)}")
            continue
        for threat, cell in zip(THREATS, row[1:], strict=True):
            if not mechanism(cell):
                out.append(
                    f"STRIDE `{door}` × {threat} cites no mechanism (path::name or file:line)"
                    " and names no open row"
                )
    out += [f"door `{d}` has no STRIDE row" for d in DOORS if d not in seen]

    noun_tab = tables["§ Nouns"]
    assert noun_tab is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    population = nouns(root, doc)
    marks = personal_fields(root)
    rows = {key(r[0]): r for r in noun_tab.rows}
    for noun in population:
        cited = rows.get(noun)
        if cited is None:
            out.append(f"noun `{noun}` has no row in § Nouns")
            continue
        if len(cited) < 5 or not all(c for c in cited[1:5]):
            out.append(
                f"noun `{noun}`'s row leaves a cell empty (classification, doors, authz, audit)"
            )
            continue
        named = set(_NAME.findall(cited[1]))
        model = noun.split(".", 1)[1]
        missing = sorted(marks.get(f"{model}Out", set()) - named)
        if missing:
            out.append(
                f"noun `{noun}`'s classification does not name its personal field(s) "
                f"{', '.join(missing)} ({model}Out marks them)"
            )
    out += [
        f"§ Nouns row `{n}` names no model introspect reports — a stale row"
        for n in rows
        if n not in population
    ]

    hipaa = tables["§ HIPAA 164.312"]
    assert hipaa is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    marked: dict[str, list[str]] = {}
    for line in hipaa.rows:
        para = key(line[0]).split()[0] if key(line[0]) else ""
        marked[para] = line
    for para in HIPAA:
        entry = marked.get(para)
        if entry is None:
            out.append(f"HIPAA 164.312{para} has no row")
            continue
        if len(entry) < 4 or not all(c for c in entry[1:4]):
            out.append(f"HIPAA 164.312{para} leaves a cell empty (control, mechanism, test)")
            continue
        if not mechanism(entry[2]):
            out.append(
                f"HIPAA 164.312{para} cites no mechanism (path::name or file:line) and says no gap:"
            )
        if not (_TEST.search(entry[3]) or _ROW_ID.search(entry[3])):
            out.append(f"HIPAA 164.312{para} names no pinning test and says no gap:")

    if not found["§ Pentest brief"].strip():
        out.append("`## § Pentest brief` is empty")
    out += citations(root, ledger_text)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    """Judge the ledger; print each refusal and the declared blind spots; 0 closes, 2 does not."""
    parser = argparse.ArgumentParser(prog="threat_census.py", description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--ledger", type=Path, default=None)
    parser.add_argument("--introspect", type=Path, default=None)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    ledger = args.ledger or root / LEDGER
    try:
        text = ledger.read_text()
    except OSError as exc:
        print(f"!! threat-census: the ledger {ledger} could not be read: {exc}", file=sys.stderr)
        return 2
    try:
        refusals = judge(root, text, introspect(root, args.introspect))
    except CouldNotLook as exc:
        print(f"!! threat-census COULD NOT LOOK: {exc}", file=sys.stderr)
        return 2
    for line in DOES_NOT_COVER:
        print(f"  {line}")
    if refusals:
        for line in refusals:
            print(f"!! threat-census: {line}", file=sys.stderr)
        print(
            f"!! the threat model does not close: {len(refusals)} refusal(s) above — write the row "
            f"or fix the citation in {LEDGER}",
            file=sys.stderr,
        )
        return 2
    print(f"  threat-census: {LEDGER} closes over its doors, nouns and HIPAA rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
