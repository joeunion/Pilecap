"""The shell population's two censuses: the local-main dependents and the instrument documents."""

# census: cross-app population=scripts/ every script under scripts/ is its subject

# does-not-cover: a dependency on a local main spelled through a variable or a fifth spelling.
# does-not-cover: whether a classification is right — every member HAS one.
# does-not-cover: whether the instrument census's population is complete — its --selftest's.
# does-not-cover: an instruments cell's meaning — the split is proven, not the row.

from __future__ import annotations

import importlib
import re
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

pytestmark = pytest.mark.drives(
    "docs/product/instruments.md", "scripts/", "quality/djb/box/bake.py", "quality/djb/scope.py"
)

ROOT = Path(__file__).resolve().parents[2]
#: The four spellings of a dependency on a local `main`; the last two each found a member.
PATTERN = re.compile(r"refs/heads/main|branch main|--hard main|rev-parse main")
VERDICTS = {
    "setup.sh": "CREATES — the only step in the tree that makes the ref",
    "verify_start.sh": "CREATES — at the verified sha, in its own clone",
    "secrets_scan.sh": "ASSUMES — merge-base basis, SECRETS_SCAN_BASE_REF overridable",
    "gate_ledger.sh": "ASSUMES — guarded: rev-parse first, then 'no-merge-base'",
    "rung_start.sh": "ASSUMES — `git reset --hard main` unguarded; act_failed carries git's status",
    "pm_main_loop.sh": "REFUSES — exit 2 before anything is launched with no local main",
}
PRIMITIVES = re.compile(
    r"^(now_ms|now_epoch|fmt_ms|clock_ms|clock_s|clock_fmt|step|step_begin|step_end|step_close"
    r"|say|die)\(\) "
)
STEP_PRINTERS = {"step", "step_begin", "step_end", "step_close", "say"}
DIRTY_READ = re.compile(r'git( -C "[^"]+")? (status --porcelain|diff --name-only)')


def members(scripts: Path) -> list[str]:
    """Every `scripts/*.sh` under `scripts` spelling a dependency on a local main, sorted."""
    return sorted(
        p.name
        for p in scripts.glob("*.sh")
        if PATTERN.search(p.read_text(encoding="utf-8", errors="replace"))
    )


def unclassified(scripts: Path) -> list[str]:
    """The members no verdict decides about; empty is the only green answer."""
    return [name for name in members(scripts) if name not in VERDICTS]


def primitive_copies(root: Path) -> list[str]:
    """`<file>:<line> <what>` for each shared primitive spelled outside its one home."""
    found: list[str] = []
    for path in sorted((root / "scripts").glob("*.sh")):
        base, file = path.name, f"scripts/{path.name}"
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, start=1):
            if line.lstrip().startswith("#"):
                continue
            defined = PRIMITIVES.match(line)
            if defined:
                name = defined.group(1)
                home = (base == "gate_refuse.sh" and name.startswith("clock_")) or (
                    base == "steps.sh" and name in STEP_PRINTERS
                )
                if not home:
                    found.append(f"{file}:{number} defines {name}")
            if "command -v shasum" in line and base not in ("gate_refuse.sh", "db.sh"):
                found.append(f"{file}:{number} a shasum ladder")
            if (
                DIRTY_READ.search(line)
                and base not in ("gate_refuse.sh", "secrets_scan.sh")
                and "--diff-filter=U" not in line
                and "`git status --porcelain" not in line
            ):
                found.append(f"{file}:{number} reads the dirty tree itself")
    return found


@pytest.fixture
def scan() -> ModuleType:
    """`scripts/goalpost_scan.py`, imported — the shipped census, never a copy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module("goalpost_scan")
    finally:
        sys.path.remove(str(ROOT / "scripts"))


def test_the_siblings_census_names_every_script_that_depends_on_a_local_main() -> None:
    found = members(ROOT / "scripts")
    assert found, "the census matched no script — a grep that found nothing is not an empty tree"
    print("census:", " ".join(found))
    assert unclassified(ROOT / "scripts") == [], "decide whether each refuses, creates or assumes"
    assert "rung_start.sh" in found, "the pattern has narrowed back past `--hard main`"
    bake = (ROOT / "quality/djb/box/bake.py").read_text()
    assert "refs/heads/main" in bake and "NO_LOCAL_MAIN" in bake, (
        "the bake's local-main refusal left the box client"
    )
    assert PATTERN.search("git rev-parse main"), "the bake's own spelling left the pattern"


def test_every_shared_primitive_has_one_home(scratch: Path) -> None:
    assert primitive_copies(ROOT) == []
    (scratch / "scripts").mkdir()
    for path in (ROOT / "scripts").glob("*.sh"):
        shutil.copy(path, scratch / "scripts" / path.name)
    planted = scratch / "scripts" / "kill_mine.sh"
    with planted.open("a") as sink:
        sink.write("now_ms() {\n    date +%s\n}\n")
    line = len(planted.read_text().splitlines()) - 2
    assert primitive_copies(scratch) == [f"scripts/kill_mine.sh:{line} defines now_ms"]


def test_an_unclassified_dependent_reds(scratch: Path) -> None:
    for path in (ROOT / "scripts").glob("*.sh"):
        shutil.copy(path, scratch / path.name)
    assert unclassified(scratch) == [], "the copy is unclassified before the plant"
    plant = scratch / "zz_planted_dependent.sh"
    plant.write_text("#!/usr/bin/env bash\n# a planted dependent\ngit reset --hard main\n")
    assert unclassified(scratch) == ["zz_planted_dependent.sh"]
    plant.unlink()
    assert unclassified(scratch) == []


def test_the_marker_is_the_one_grammar_the_loop_reads() -> None:
    reader = (ROOT / "quality/djb/scope.py").read_text(encoding="utf-8")
    declared = re.search(r'^CENSUS_MARKER = "([^"]+)"', reader, re.MULTILINE)
    assert declared, "quality/djb/scope.py declares no CENSUS_MARKER"
    head = Path(__file__).read_text(encoding="utf-8").splitlines()[:40]
    assert any(line.startswith(declared.group(1) + " ") for line in head)


def test_the_product_census_document_is_read_beside_the_templates(
    scan: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mechanism, over the template's own population: a product's drawer never reaches it."""
    doc = scan._read(scan.CENSUS)
    cite = "(x/y.sh:1)"
    template = [
        m.group(1)
        for cells in scan.read_table(doc, "Instrument", "instruments.md")
        if (m := re.search(r"`([^`]+)`", cells[0]))
    ]
    monkeypatch.setattr(scan, "population", lambda: template)

    def rows(path: str) -> str:
        head = (
            "| Instrument | Fails loud? | Says what it saw? | States its blind spots? | Finding |"
        )
        row = f"| `{path}` | yes {cite} | loud {cite} | yes {cite} | none |"
        return f"{head}\n|---|---|---|---|---|\n{row}\n"

    code, lines = scan.census(doc, rows("zz/not/a/file.sh"))
    text = "\n".join(lines)
    assert code == 2 and "censused but not an instrument" in text and "zz/not/a/file.sh" in text
    assert f"1 product row(s) in {scan.CENSUS_LOCAL.name}" in text
    first = scan.read_table(doc, "Instrument", "instruments.md")[0][0]
    claimed = re.search(r"`([^`]+)`", first)
    assert claimed, first
    with pytest.raises(scan.CannotLook) as refused:
        scan.census(doc, rows(claimed.group(1)))
    assert claimed.group(1) in str(refused.value) and scan.CENSUS.name in str(refused.value)
    absent = scan.census(doc)
    assert absent == scan.census(doc, None)
    assert not any(scan.CENSUS_LOCAL.name in line for line in absent[1])


def test_an_escaped_pipe_is_a_pipe_inside_one_cell(scan: ModuleType) -> None:
    cells = scan._cells("| `x.sh` | yes (x.sh:1) | loud: `a \\| b` (x.sh:2) | yes (x.sh:3) | why |")
    assert len(cells) == 5
    assert cells[2] == "loud: `a | b` (x.sh:2)"


def _row(path: str) -> str:
    cite = "(x/y.sh:1)"
    return f"| `{path}` | yes {cite} | loud {cite} | yes {cite} | none |"


def _table(*rows: str) -> str:
    head = "| Instrument | Fails loud? | Says what it saw? | States its blind spots? | Finding |"
    return f"{head}\n|---|---|---|---|---|\n" + "".join(f"{r}\n" for r in rows)


@pytest.fixture
def tree(scan: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git tree carrying the engine and one product drawer executable, untracked."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for rel in ("quality/gate.py", "scripts/local/x.sh"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("#!/usr/bin/env bash\necho hi\n")
        (tmp_path / rel).chmod(0o755)
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    monkeypatch.setattr(scan, "CENSUS_PINS", ())
    return tmp_path


def test_a_drawer_executable_owes_its_row_in_the_products_document(
    scan: ModuleType, tree: Path
) -> None:
    code, lines = scan.census(_table(_row("quality/gate.py")))
    text = "\n".join(lines)
    assert code == 2, text
    assert lines[0] == "census: 1 instruments derived, 1 rows in instruments.md", lines[0]
    named = [ln for ln in lines if "uncensused: scripts/local/x.sh" in ln]
    assert named and all(scan.CENSUS_LOCAL.name in ln for ln in named), named
    assert "docs/product/instruments.local.md" in text and "| Instrument |" in text
    assert "owes a row in docs/product/instruments.md" not in text, text


def test_a_drawer_executable_with_its_local_row_is_clean(scan: ModuleType, tree: Path) -> None:
    code, lines = scan.census(_table(_row("quality/gate.py")), _table(_row("scripts/local/x.sh")))
    assert code == 0, "\n".join(lines)
    assert lines[0] == "census: 1 instruments derived, 1 rows in instruments.md", lines[0]


def test_a_drawer_executable_with_a_template_row_is_in_the_wrong_document(
    scan: ModuleType, tree: Path
) -> None:
    code, lines = scan.census(_table(_row("quality/gate.py"), _row("scripts/local/x.sh")))
    text = "\n".join(lines)
    assert code == 2 and scan.CENSUS_LOCAL.name in text, text


def test_a_template_executable_still_owes_the_templates_document(
    scan: ModuleType, tree: Path
) -> None:
    (tree / "scripts/y.sh").write_text("#!/usr/bin/env bash\n")
    (tree / "scripts/y.sh").chmod(0o755)
    code, lines = scan.census(_table(_row("quality/gate.py")), _table(_row("scripts/local/x.sh")))
    text = "\n".join(lines)
    assert code == 2 and "uncensused: scripts/y.sh" in text, text
    assert "owes a row in docs/product/instruments.md" in text, text


def test_the_templates_own_census_counts_one_row_per_derived_instrument(
    scan: ModuleType,
) -> None:
    code, lines = scan.census(scan._read(scan.CENSUS), scan._census_local_text())
    counts = re.match(
        r"census: (\d+) instruments derived, (\d+) rows in instruments\.md$", lines[0]
    )
    assert counts and counts.group(1) == counts.group(2), lines[0]
    assert code == 0, "\n".join(lines)


def test_a_census_git_cannot_list_quotes_git(
    scan: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".git").write_text("gitdir: /nonexistent/djb-not-a-repo\n")
    monkeypatch.setattr(scan, "ROOT", tmp_path)
    with pytest.raises(scan.CannotLook) as refused:
        scan.tracked_and_new()
    assert "\n   the tool said: fatal: not a git repository" in str(refused.value)
