"""`loop.run` and `loop.bank`: the order the shell leg's text pinned, held by the package."""

# does-not-cover: the bash bodies `loop.shell` calls — `gate_ledger.sh`'s own drives own them.
# does-not-cover: a real `--loop` — the members, the scope and the ledger are fakes here.

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import cli, ledger, loop, modes, scope
from quality.djb import registry as R
from quality.djb.gate_args import Request
from quality.djb.legs import ledger_check

pytestmark = pytest.mark.drives("quality/djb/loop.py")

KEY = "loop-key-1"
#: `loop.bank` itself, before `Fakes` stands a recorder in its place.
BANK = loop.bank


class Fakes:
    """Every collaborator `run` reaches, recording the order it reached them in."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, members_rc: int = 0) -> None:
        self.calls: list[str] = []
        self.members_rc = members_rc
        calls = self.calls

        class FakeKeyed:
            def __init__(self, root: Path, derived: scope.Scope) -> None:
                calls.append("keyed")
                self.tree, self.key, self.digest, self.parts, self.cannot = "t", KEY, "d", "", ""

        def shell(root: Path, script: str, env: dict[str, str] | None = None) -> tuple[int, str]:
            calls.append("shell:" + script.split()[0])
            return 0, ""

        def record(name: str, value: Any = None) -> Any:
            def fake(*args: Any, **kwargs: Any) -> Any:
                calls.append(name)
                return value

            return fake

        def members(*args: Any, **kwargs: Any) -> int:
            calls.append("members")
            return self.members_rc

        table = type("T", (), {"mode_legs": lambda self, mode: [], "local": []})()
        monkeypatch.setattr(loop, "Keyed", FakeKeyed)
        monkeypatch.setattr(loop, "shell", shell)
        monkeypatch.setattr(loop, "where", record("where", "here"))
        monkeypatch.setattr(cli, "refuse_if_locked", record("lock"))
        monkeypatch.setattr(loop, "derive", record("derive", scope.Scope()))
        monkeypatch.setattr(loop, "snapshot", record("snapshot", "/no/such/snap"))
        monkeypatch.setattr(loop, "consult", record("consult", None))
        monkeypatch.setattr(loop, "miss", record("miss", ""))
        monkeypatch.setattr(cli, "table", lambda root: table)
        monkeypatch.setattr(loop, "run_members", members)
        monkeypatch.setattr(scope, "touched", lambda root, changed: [])
        monkeypatch.setattr(loop, "bank", record("bank", 0))
        monkeypatch.delenv("DJB_GATE_LEGS_DRY", raising=False)
        monkeypatch.delenv("DJB_LOOP_NO_CACHE", raising=False)


def test_the_leg_consults_before_it_measures_and_records_only_after_green(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    green = Fakes(monkeypatch)
    assert loop.run(tmp_path, Request(mode="--loop")) == 0
    assert green.calls.index("consult") < green.calls.index("members") < green.calls.index("bank")
    red = Fakes(monkeypatch, members_rc=1)
    assert loop.run(tmp_path, Request(mode="--loop")) == 1
    assert "members" in red.calls and "bank" not in red.calls


def test_an_unfinished_run_is_remembered_at_the_next_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    red = Fakes(monkeypatch, members_rc=1)
    assert loop.run(tmp_path, Request(mode="--loop")) == 1
    assert red.calls[-1] == "shell:loop_tree_mark_end"


def test_the_sync_is_wired_into_the_loop_leg_ahead_of_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fakes = Fakes(monkeypatch)
    loop.run(tmp_path, Request(mode="--loop"))
    assert fakes.calls.index("shell:loop_env_sync") < fakes.calls.index("keyed")
    dry = Fakes(monkeypatch)
    monkeypatch.setenv("DJB_GATE_LEGS_DRY", "1")
    loop.run(tmp_path, Request(mode="--loop"))
    assert "shell:loop_env_sync" not in dry.calls


def test_a_dry_loop_banks_nothing_and_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    Fakes(monkeypatch)
    monkeypatch.setattr(loop, "bank", BANK)
    monkeypatch.setattr(ledger, "loop_key_tree", lambda root, tree: tree)
    scratch = tmp_path / "verdicts"
    scratch.write_text("v1 planted-row\n")
    before = scratch.read_bytes()
    monkeypatch.setenv("DJB_GATE_LEDGER", str(scratch))
    monkeypatch.setenv("DJB_GATE_LEGS_DRY", "1")
    assert loop.run(tmp_path, Request(mode="--loop")) == 0
    assert scratch.read_bytes() == before
    out = capsys.readouterr().out
    assert "no verdict banked — DJB_GATE_LEGS_DRY" in out and "banked: this" not in out


def test_mine_and_pr_never_reuse_on_a_docs_only_delta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mine = Fakes(monkeypatch)
    assert loop.run(tmp_path, Request(mode="--loop", mine=True)) == 0
    assert not {"keyed", "consult", "miss", "bank"} & set(mine.calls)
    assert "NOT consulted: --mine" in capsys.readouterr().out
    assert "loop_reuse" not in inspect.getsource(modes)


def test_a_key_that_could_not_look_names_its_cause(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def cannot(*args: Any, **kwargs: Any) -> str:
        raise CouldNotLook("the planted cause")

    monkeypatch.setattr(ledger, "measured_tree", lambda root: "t")
    monkeypatch.setattr(scope, "env_fingerprint", lambda root, reads: None)
    monkeypatch.setattr(scope, "loop_key", cannot)
    keyed = loop.Keyed(tmp_path, scope.Scope())
    assert keyed.cannot == "the planted cause" and keyed.key == ""
    monkeypatch.setattr(loop, "shell", lambda root, script, env=None: (0, ""))
    start = loop.Keyed.__new__(loop.Keyed)
    start.tree, start.key, start.digest, start.parts, start.cannot = "t", KEY, "d", "", ""
    snap = tmp_path / "snap"
    assert loop.bank(tmp_path, start, scope.Scope(), str(snap), "h", "", modes.Clock()) == 0
    out = capsys.readouterr().out
    assert "the key could not be derived: the planted cause" in out
    assert "something moved" not in out


def test_the_bank_asks_before_the_key_re_derives(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fakes = Fakes(monkeypatch)
    start = loop.Keyed.__new__(loop.Keyed)
    start.tree, start.key, start.digest, start.parts, start.cannot = "t", "other", "d", "", ""
    BANK(tmp_path, start, scope.Scope(), str(tmp_path / "snap"), "h", "", modes.Clock())
    assert fakes.calls[:3] == [
        "shell:loop_tree_mark_end",
        "shell:loop_tree_rewrites",
        "shell:loop_tree_remember",
    ]
    assert fakes.calls[3] == "keyed"


def test_the_bank_remembers_what_it_refused_and_its_rm_spares_the_memory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    snap = tmp_path / "djb-loop-snapshot"
    for suffix in ("", ".stamp", ".end", ".rewrites"):
        Path(f"{snap}{suffix}").write_text("x")
    seen: list[tuple[str, dict[str, str]]] = []

    def shell(root: Path, script: str, env: dict[str, str] | None = None) -> tuple[int, str]:
        seen.append((script, dict(env or {})))
        return (0, "apps/a.py\tcarried\napps/b.py\twritten\n") if "rewrites" in script else (0, "")

    monkeypatch.setattr(loop, "shell", shell)
    start = loop.Keyed.__new__(loop.Keyed)
    start.tree, start.key, start.digest, start.parts, start.cannot = "t", KEY, "d", "", ""
    assert loop.bank(tmp_path, start, scope.Scope(), str(snap), "h", "", modes.Clock()) == 2
    remember = [env for script, env in seen if script.startswith("loop_tree_remember")]
    assert remember == [{"P": str(snap), "M": "apps/a.py\napps/b.py"}]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["djb-loop-snapshot.rewrites"]


def test_a_commit_that_skipped_the_hook_meets_the_leg(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(ledger_check, "checkout_python", lambda root: Path("/bin/true"))
    monkeypatch.setattr(ledger_check, "callee", lambda ctx, argv: (1, ""))
    assert ledger_check.run(R.Ctx(tmp_path, "fast", {})) == 1
    assert "!! the dispatch ledger refused" in capsys.readouterr().err
