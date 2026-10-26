"""The `supply-chain` leg: the shell body's verdicts, its one retry and its order, in Python."""

# does-not-cover: a live advisory source — every network answer here is a planted one.

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from quality.djb import registry as R
from quality.djb.legs import supply_chain as sc
from quality.tests.fixtures import shell_gate

pytestmark = pytest.mark.drives("quality/djb/legs/supply_chain.py")

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
BODY = GATE_TEXT.split("# >>> leg-body: supply-chain >>>", 1)[1].split(
    "gate_run_body supply-chain ", 1
)[0]


class _Planted:
    """`subprocess.run` replaced: each call answered from a queue of (exit, stdout, stderr)."""

    def __init__(self, *answers: tuple[int, str, str]) -> None:
        self.answers = list(answers)
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(list(argv))
        rc, out, err = self.answers.pop(0) if self.answers else (0, "", "")
        for stream, text in ((kw.get("stdout"), out), (kw.get("stderr"), err)):
            if stream is not None and hasattr(stream, "write") and text:
                stream.write(text.encode())
        return subprocess.CompletedProcess(argv, rc, out.encode(), err.encode())


@pytest.fixture
def planted(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def plant(*answers: tuple[int, str, str]) -> _Planted:
        found = _Planted(*answers)
        monkeypatch.setattr(subprocess, "run", found)
        return found

    yield plant


def _ctx(root: Path = ROOT, **env: str) -> R.Ctx:
    return R.Ctx(root, "full", {"PATH": os.environ["PATH"], **env})


def test_the_leg_claims_the_shell_line_of_its_name_in_its_unit_and_runs_in_full_only() -> None:
    table = R.load(ROOT)
    assert table.leg("supply-chain") is sc.LEG
    assert table.unit("supply-chain")[1] == ("supply-chain",)
    assert sc.LEG.modes == frozenset({"full"})
    assert ("supply-chain", "supply-chain") in R.shell_legs(GATE_TEXT)


def test_every_command_the_leg_declares_is_spelled_in_the_shell_body() -> None:
    for argv in sc.ARGV:
        listed = "[" + ", ".join(f'"{w}"' for w in argv) + "]"
        assert " ".join(argv) in BODY or listed in BODY, argv
    assert sc.AUDIT_LEVEL in re.findall(r"^SUPPLY_CHAIN_AUDIT_LEVEL=(\w+)$", BODY, re.M)


@pytest.mark.parametrize(
    ("shell", "mine"),
    [
        ("SUPPLY_CHAIN_NETWORK_RE", sc.NETWORK),
        ("SUPPLY_CHAIN_PIP_FINDING_RE", sc.PIP_FINDING),
        ("SUPPLY_CHAIN_PNPM_FINDING_RE", sc.PNPM_FINDING),
        ("SUPPLY_CHAIN_PNPM_INSTALL_FINDING_RE", sc.PNPM_INSTALL_FINDING),
    ],
)
def test_each_shape_is_the_shells_own_pattern(shell: str, mine: re.Pattern[str]) -> None:
    found = re.search(rf"^{shell}='([^']*)'$", BODY, re.M)
    assert found and found.group(1) == mine.pattern


def test_a_network_failure_twice_is_could_not_look_naming_the_tool(
    planted: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = planted((1, "", "ReadTimeout: pypi"), (1, "", "Connection refused"))
    assert sc.twice(_ctx(), "pip-audit", "its advisory source", sc.judge_pip_audit, ("x",)) == 2
    seen = capsys.readouterr()
    assert "retrying once." in seen.out
    assert "!! SUPPLY CHAIN UNPROVEN — pip-audit could not reach its advisory source" in seen.err
    assert len(calls.calls) == 2


def test_a_network_failure_then_a_clean_answer_is_clean(planted: Any) -> None:
    calls = planted((1, "", "ReadTimeout"), (0, "No known vulnerabilities found\n", ""))
    assert sc.twice(_ctx(), "pip-audit", "src", sc.judge_pip_audit, ("x",)) == 0
    assert len(calls.calls) == 2


def test_a_finding_is_never_retried_even_beside_the_networks_shape(planted: Any) -> None:
    calls = planted((1, "Found 1 known vulnerability\nReadTimeout\n", ""))
    assert sc.twice(_ctx(), "pip-audit", "src", sc.judge_pip_audit, ("x",)) == 1
    assert len(calls.calls) == 1


def test_any_other_failure_answers_the_commands_own_exit(planted: Any) -> None:
    planted((3, "", "usage: pip-audit: unknown flag"))
    assert sc.twice(_ctx(), "pip-audit", "src", sc.judge_pip_audit, ("x",)) == 3


@pytest.mark.parametrize(
    ("reader_rc", "pnpm_rc", "verdict"),
    [(0, 0, "clean"), (0, 1, "unread"), (1, 1, "finding"), (2, 0, "unread"), (4, 1, "clean")],
    ids=["clean", "disagree", "finding", "unread", "all-accepted"],
)
def test_the_pnpm_audit_judge_reads_the_report_before_the_exit(
    reader_rc: int, pnpm_rc: int, verdict: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "reader", lambda *a, **k: (reader_rc, ""))
    assert sc.judge_pnpm_audit(_ctx(), pnpm_rc, "{}", "", tmp_path / "out") == verdict


def test_no_report_and_the_networks_shape_is_a_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sc, "reader", lambda *a, **k: (3, ""))
    assert sc.judge_pnpm_audit(_ctx(), 1, "", "ECONNREFUSED", tmp_path / "o") == "network"
    assert sc.judge_pnpm_audit(_ctx(), 1, "", "nothing", tmp_path / "o") == "unread"


def _audit(tmp_path: Path, doc: object) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(doc))
    return subprocess.run(
        [sys.executable, "-c", sc.GUARD + sc.PNPM_AUDIT, str(path), sc.AUDIT_LEVEL],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "DJB_SUPPLY_CHAIN_POLICY_DIR": str(ROOT / "scripts")},
    )


def test_the_lifted_audit_reader_counts_without_records_as_a_finding(tmp_path: Path) -> None:
    doc = {"advisories": {}, "metadata": {"vulnerabilities": {"high": 2}}}
    ran = _audit(tmp_path, doc)
    assert ran.returncode == 1
    assert "advisories reported by count and not by record: high=2" in ran.stdout


def test_the_lifted_audit_reader_is_clean_on_an_empty_report(tmp_path: Path) -> None:
    doc = {"advisories": {}, "metadata": {"vulnerabilities": {}, "totalDependencies": 7}}
    ran = _audit(tmp_path, doc)
    assert ran.returncode == 0, ran.stderr
    assert "clean at moderate and above (7 dependencies;" in ran.stdout


def test_the_lifted_audit_reader_on_an_error_object_is_no_report(tmp_path: Path) -> None:
    assert _audit(tmp_path, {"error": {"code": "ECONNREFUSED"}}).returncode == 3


@pytest.mark.parametrize(
    ("rc", "text", "want"),
    [
        (0, "", 0),
        (1, "ERROR: Potential secrets about to be committed to git repo!", 1),
        (123, "Traceback: something else", 2),
    ],
    ids=["clean", "finding", "unread"],
)
def test_the_whole_tree_secret_scan(
    rc: int, text: str, want: int, planted: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = planted((0, "a.py\0b.py\0", ""), (rc, text, ""))
    assert sc.secrets(_ctx()) == want
    assert calls.calls[0] == ["git", "ls-files", "-z"]
    assert calls.calls[1] == ["xargs", "-0", *sc.SECRETS]
    if want == 2:
        assert "detect-secrets-hook reported no finding" in capsys.readouterr().err


def test_no_frontend_lock_is_said_and_not_measured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sc.frontend_audit(_ctx(tmp_path)) == (0, "")
    assert "no frontend/pnpm-lock.yaml" in capsys.readouterr().out


def test_a_frontend_lock_with_no_pnpm_is_could_not_look(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend/pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    assert sc.frontend_audit(_ctx(tmp_path, FE_PNPM="djb-no-such-pnpm"))[0] == 2
    assert "no pnpm is on PATH" in capsys.readouterr().err


def test_the_python_sentence_stands_alone_without_a_frontend(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert sc.frontend_licences(_ctx(), "", "licenses clean (3 packages)") == 0
    assert capsys.readouterr().out == "licenses clean (3 packages)\n"


def test_the_first_red_step_ends_the_leg_and_nothing_after_it_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran: list[str] = []
    monkeypatch.setattr(sc, "policy_pair", lambda ctx: _record(ran, "pair", 0))
    monkeypatch.setattr(sc, "twice", lambda *a, **k: _record(ran, a[1], 1))
    monkeypatch.setattr(sc, "secrets", lambda ctx: _record(ran, "secrets", 0))
    assert sc.run(_ctx()) == 1
    assert ran == ["pair", "pip-audit"]


def test_a_broken_policy_pair_is_2_before_any_package(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc, "reader", lambda *a, **k: (2, ""))
    monkeypatch.setattr(sc, "twice", lambda *a, **k: pytest.fail("pip-audit ran"))
    assert sc.run(_ctx()) == 2


def _record(into: list[Any], item: Any, value: Any) -> Any:
    """Append `item` and answer `value`: a stand-in that notes it ran."""
    into.append(item)
    return value
