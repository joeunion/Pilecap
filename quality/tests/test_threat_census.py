"""The threat census refuses a missing door or noun row, a dead citation, an empty HIPAA row."""

# does-not-cover: a real model planted in apps/ — the planted noun rides the introspect document.

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from quality.djb import registry as R
from quality.djb.rituals import publish

ROOT = Path(__file__).resolve().parents[2]


def _census() -> ModuleType:
    """`scripts/threat_census.py`, imported — the shipped census, never a copy."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        return importlib.import_module("threat_census")
    finally:
        sys.path.remove(str(ROOT / "scripts"))


census = _census()

LEDGER = ROOT / census.LEDGER
SKELETON = ROOT / publish.SKELETONS / "threat-model.md"
MARKER = "<!-- worked example: replace with your noun -->"


@pytest.fixture(scope="module")
def dump(tmp_path_factory: pytest.TempPathFactory) -> Path:
    done = subprocess.run(
        [str(ROOT / ".venv/bin/python"), "manage.py", "introspect"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    path = tmp_path_factory.mktemp("threat") / "introspect.json"
    path.write_text(done.stdout)
    return path


def _run(capsys: pytest.CaptureFixture[str], dump: Path, ledger: Path = LEDGER) -> tuple[int, str]:
    rc = census.main(["--root", str(ROOT), "--ledger", str(ledger), "--introspect", str(dump)])
    said = capsys.readouterr()
    return rc, said.out + said.err


def _edited(tmp_path: Path, old: str, new: str) -> Path:
    text = LEDGER.read_text()
    assert old in text, old
    path = tmp_path / "threat-model.md"
    path.write_text(text.replace(old, new, 1))
    return path


def test_the_shipped_ledger_is_green(capsys: pytest.CaptureFixture[str], dump: Path) -> None:
    rc, said = _run(capsys, dump)
    assert rc == 0, said
    assert "does_not_cover:" in said


def test_a_planted_model_without_a_row_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    doc = json.loads(dump.read_text())
    doc["models"].append({"app": "example", "name": "PlantedNoun", "fields": []})
    planted = tmp_path / "introspect.json"
    planted.write_text(json.dumps(doc))
    rc, said = _run(capsys, planted)
    assert rc == 2, said
    assert "noun `example.PlantedNoun` has no row in § Nouns" in said


def test_a_dead_citation_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    first = census._CITE.search(LEDGER.read_text())
    assert first is not None
    path = first.group(1)
    ledger = _edited(tmp_path, first.group(0), f"`{path}:999999`")
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert f"{path}:999999 cites past {path}'s end" in said


def test_a_cite_without_an_extension_is_resolved(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    # V-LS-THREAT1 F1: `deploy/Caddyfile:71` was decorative — the census closed on `:9999`.
    assert census._CITE.search("`deploy/Caddyfile:71`") is not None
    ledger = _edited(tmp_path, "`deploy/Caddyfile:71`", "`deploy/Caddyfile:999999`")
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert "deploy/Caddyfile:999999 cites past deploy/Caddyfile's end" in said


def test_a_citation_of_a_file_that_is_gone_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    first = census._TEST.search(LEDGER.read_text())
    assert first is not None
    ledger = _edited(tmp_path, first.group(0), f"`{first.group(1)}::test_nobody_wrote_this`")
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert "::test_nobody_wrote_this is defined nowhere in" in said


def test_a_mechanism_on_a_blank_line_is_exit_2_naming_the_cell(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    # critique-security F2: a cell that landed on the blank line before its def closed green.
    rows = (ROOT / "apps/core/service.py").read_text().splitlines()
    blank = next(n for n, row in enumerate(rows, 1) if not row.strip())
    ledger = _edited(tmp_path, "`deploy/Caddyfile:71`", f"`apps/core/service.py:{blank}`")
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert f"apps/core/service.py:{blank} lands on a blank line" in said


def test_a_named_mechanism_that_resolves_nowhere_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    ledger = _edited(
        tmp_path, "`apps/core/service.py::write_audit`", "`apps/core/service.py::write_nothing`"
    )
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert "apps/core/service.py::write_nothing is defined nowhere in apps/core/service.py" in said


def test_a_door_without_a_row_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    row = next(ln for ln in LEDGER.read_text().splitlines() if ln.startswith("| sockets |"))
    ledger = _edited(tmp_path, row + "\n", "")
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert "door `sockets` has no STRIDE row" in said


def test_an_empty_hipaa_row_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    row = next(ln for ln in LEDGER.read_text().splitlines() if ln.startswith("| (b) "))
    ledger = _edited(tmp_path, row, "| (b) audit controls | | | |")
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert "HIPAA 164.312(b) leaves a cell empty" in said


def test_a_classification_that_drops_a_personal_field_is_exit_2(
    capsys: pytest.CaptureFixture[str], dump: Path, tmp_path: Path
) -> None:
    row = next(ln for ln in LEDGER.read_text().splitlines() if ln.startswith("| `example.Widget` "))
    ledger = _edited(tmp_path, row, row.replace("`owner_email`", "owner email"))
    rc, said = _run(capsys, dump, ledger)
    assert rc == 2, said
    assert "does not name its personal field(s) owner_email (WidgetOut marks them)" in said


@pytest.mark.template_only(reason="the skeleton sources exist only in the template")
def test_the_skeleton_differs_from_the_ledger_only_in_the_marker() -> None:
    skeleton = SKELETON.read_text()
    assert skeleton.count(MARKER) == 1
    marked = next(ln for ln in skeleton.splitlines() if MARKER in ln)
    assert marked.startswith("| `example.Widget` ")
    assert re.sub(rf"\s*{re.escape(MARKER)}", "", skeleton) == LEDGER.read_text()


def test_the_leg_runs_the_census_in_the_full_static_unit_only() -> None:
    leg = R.discover()
    found = next(g for g in leg if g.name == "threat-census")
    assert found.unit == "static"
    assert found.modes == frozenset({"full"})
    assert found.argv == (("<checkout python>", "scripts/threat_census.py"),)


def test_a_citation_judge_git_cannot_list_quotes_git(tmp_path: Path) -> None:
    from quality.could_not_look import CouldNotLook

    (tmp_path / ".git").write_text("gitdir: /nonexistent/djb-not-a-repo\n")
    with pytest.raises(CouldNotLook) as refused:
        census.citations(tmp_path, "`" + "docs" + "/nowhere.md`")
    assert "\n   the tool said: fatal: not a git repository" in str(refused.value)
