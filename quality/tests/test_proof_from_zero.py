"""The proof from zero's shapes are registered, its dry run names them, its record parses."""

# does-not-cover: the run itself — a clone and `setup.sh` are the ritual's, never a test's.
# does-not-cover: a shape's golden moved by a loop-lane diff — the scaffold's own drives judge it.

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from quality.djb import ledger
from quality.djb.rituals import proof_from_zero as proof

pytestmark = pytest.mark.drives(
    "quality/djb/rituals/proof_from_zero.py",
    "quality/djb/rituals/publish.py",
    "scripts/proof_from_zero.sh",
    ".github/workflows/proof-from-zero.yml",
)

ROOT = Path(__file__).resolve().parents[2]
STAMP = "20261011T235959Z"
HEX = "0123456789abcdef" * 2 + "01234567"
SDK = ["2.4.1", "green", "0", "3", "agree,agree,agree", "-"]


def test_each_feature_is_a_shape_the_scaffold_lists(tmp_path: Path) -> None:
    said = tmp_path / "list.log"
    with said.open("w") as sink:
        rc = subprocess.run(
            [str(ROOT / ".venv/bin/python"), "manage.py", "scaffold", "--list"],
            cwd=ROOT,
            stdout=sink,
            stderr=sink,
        ).returncode
    listed = {line.split()[0] for line in said.read_text().splitlines() if line.strip()}
    assert rc == 0, said.read_text()
    assert {one.words[0] for one in proof.FEATURES} <= listed, sorted(listed)
    assert all(one.words[1:3] == (proof.APP, proof.NOUN) for one in proof.FEATURES)


def test_the_dry_run_prints_the_steps_and_the_three_shapes(tmp_path: Path) -> None:
    said = tmp_path / "dry.log"
    with said.open("w") as sink:
        rc = subprocess.run(
            ["./scripts/proof_from_zero.sh", "--dry-run"], cwd=ROOT, stdout=sink, stderr=sink
        ).returncode
    text = said.read_text()
    assert rc == 0, text
    for one in proof.FEATURES:
        assert f"manage.py scaffold {' '.join(one.words)}" in text
    assert all(step.split()[0] in text for step in proof.STEPS)
    assert f".env += {proof.SHAPE}" in text


def _world(root: Path) -> Path:
    (root / "quality").mkdir(parents=True)
    (root / "quality/partition.yaml").write_text("platform_apps:\n  - core\n")
    (root / "TEMPLATE_VERSION").write_text("9.9.9\n")
    (root / "apps/core").mkdir(parents=True)
    (root / "apps/core/apps.py").write_text('"""An app."""\n')
    (root / ".env").write_text("DEBUG=1\n")
    for argv in (
        ["init", "-q", "-b", "main"],
        ["add", "--", "quality", "apps", "TEMPLATE_VERSION"],
    ):
        subprocess.run(["git", *argv], cwd=root, check=True)
    _commit(root, "the template")
    return root


def _commit(root: Path, message: str) -> int:
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
    return subprocess.run(
        ["git", *ident, "commit", "-q", "--allow-empty", "-m", message], cwd=root
    ).returncode


def test_the_proof_declares_through_the_command_a_product_runs(tmp_path: Path) -> None:
    dest = _world(tmp_path / "clone")
    asked: list[tuple[str, ...]] = []

    def manage(name: str, *words: str) -> tuple[int, str]:
        asked.append(words)
        if words[0] == "newapp":
            (dest / "apps" / words[1]).mkdir(parents=True)
            (dest / "apps" / words[1] / "apps.py").write_text('"""An app."""\n')
        if words[0] != "declare":
            return 0, ""
        argv = [str(ROOT / ".venv/bin/python"), "manage.py", *words, "--root", str(dest)]
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True)
        return done.returncode, done.stdout + done.stderr

    def run_logged(name: str, argv: list[str], **_env: str) -> tuple[int, str, float]:
        return _commit(dest, argv[-1]), "", 0.0

    run = proof.Proof.__new__(proof.Proof)
    run.args, run.dest, run.out_dir, run.findings = Namespace(plant=None), dest, tmp_path, []
    run.manage, run.run_logged = manage, run_logged  # type: ignore[method-assign, assignment]
    run.tidy, run.changed = lambda tag: None, lambda: []  # type: ignore[method-assign]
    run.declare()
    run.product()
    committed = run.git("show", "--name-only", "--format=", "HEAD~1")
    assert committed.split() == ["quality/local/rules.yaml", "scripts/local/template-base"]
    assert (
        (dest / "quality/local/rules.yaml")
        .read_text()
        .startswith(f"rule_id_namespace: {proof.NAMESPACE}\ntemplate_rule_ids_through: ")
    )
    assert (dest / ".env").read_text() == f"DEBUG=1\n{proof.SHAPE}\n"
    assert [w[0] for w in asked] == ["declare", "newapp", "declare", "scaffold"]
    assert run.findings == []


@pytest.mark.parametrize("plant", sorted(proof.PLANTS))
def test_each_plant_finds_its_one_anchor_on_this_tree(plant: str) -> None:
    path, old, new = proof.PLANTS[plant]
    assert (ROOT / path).read_text().count(old) == 1
    assert old != new


def test_a_green_record_is_written_in_the_grammar() -> None:
    fields = [STAMP, HEX, HEX, "3", "loop,loop,loop", "0,0,0", "1,1,1", "201,233,250"]
    line = ledger.proof_line([*fields, "3", "1", *SDK, "0", "38180000000", "ci"])
    assert line.startswith(f"schema=proof-from-zero/3 at={STAMP} source={HEX} tree={HEX} ")
    assert " lane=loop,loop,loop tax=0,0,0 " in line
    assert (
        " sdk=2.4.1 rule96=green valves=0 scaffold=3 drive=agree,agree,agree reference=- " in line
    )
    assert line.endswith(" rc=0 run=38180000000 where=ci")


@pytest.mark.parametrize(
    "where, value",
    [
        (4, "loop,loop"), (5, "0,0,many"), (8, "4"), (18, "nightly"), (0, "yesterday"),
        (10, "v2"), (11, "amber"), (12, "some"), (13, "4"), (14, "agree,agree"), (15, "many"),
    ],
)  # fmt: skip
def test_a_field_out_of_shape_writes_nothing(where: int, value: str) -> None:
    fields = [STAMP, HEX, HEX, "3", "loop,full,-", "0,3.3,-", "1,1,-", "200,-,-"]
    fields += ["3", "1", "2.4.1", "red", "1", "2", "agree,-,-", "12", "1", "0", "local"]
    fields[where] = value
    with pytest.raises(ledger.Refused, match="would not parse"):
        ledger.proof_line(fields)


def test_the_road_reader_takes_each_steps_exit_and_seconds() -> None:
    text = (
        "== feature zzzproofs --loop --drive Proof\n- manage.py makemigrations zzzproofs\n"
        "  exit 0 (2s) · log /tmp/a.log\n- ./scripts/check.sh --loop\n  exit 0 (412s) · log x\n"
        "- ./scripts/drive_doors.sh Proof\n  exit 1 (9s) · log y\nnext: whatever\n"
    )
    steps = proof.read_road(text)
    assert steps["./scripts/check.sh --loop"] == (0, 412)
    assert steps["./scripts/drive_doors.sh Proof"] == (1, 9)


GATE_LOG = """  always-on: 3 member(s) green · 0 red · 1 could-not-look
!! COULD NOT LOOK: quality-tests
  harness quality/tests: exit 2 (31s)
      | COULD NOT LOOK quality/tests/test_db.py::test_db_sh_under_zsh[gw]: COULD NOT LOOK — call: \
no zsh on PATH — db.sh under zsh cannot be driven. The rest is detail.
"""


def test_a_loop_that_could_not_look_keeps_its_gate_log_and_names_the_case(tmp_path: Path) -> None:
    """The record carries the gate's own log, and its red names the member, the case and why."""
    gate = tmp_path / "feature-zzzproofs-gate.abc.log"
    gate.write_text(GATE_LOG)
    road = (
        "- ./scripts/check.sh --loop\n"
        f"  exit 2 (2388s) · log {gate}\n"
        "  - every red leg: always-on exit 2\n"
        "could not look: !! COULD NOT LOOK: quality-tests\n"
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    kept = proof.keep_gate_log(road, out_dir, "b")
    assert (out_dir / "gate-b.log").read_text() == kept == gate.read_text()
    said = proof.road_refusal(2, road, kept, "b")
    assert said == (
        "--loop could not look — quality-tests: quality/tests/test_db.py::test_db_sh_under_zsh[gw]"
        " — call: no zsh on PATH — db.sh under zsh cannot be driven."
    )


def test_a_road_red_before_the_gate_says_the_roads_own_line(tmp_path: Path) -> None:
    road = "- manage.py makemigrations zzzproofs\n  exit 1 (3s) · log /nowhere.log\nx boom\n"
    assert proof.keep_gate_log(road, tmp_path, "a") == ""
    assert proof.road_refusal(1, road, "", "a") == "feature.sh exited 1: x boom"
    assert not list(tmp_path.iterdir())


def test_a_shape_is_named_by_its_scaffold_line_or_its_shapes_table_row() -> None:
    table = "verb                  apps/core/scaffold/goldens/verb.touch/ (8 modules)\n"
    assert proof.named_on_a_page("verb", table)
    assert proof.named_on_a_page("filter", "- `scaffold filter` takes a declared lookup only")
    assert not proof.named_on_a_page("field", "a field is a column; the fieldset is not\n")


def test_the_clone_reads_its_object_store_credentials_from_its_own_env_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job's empty pin of the cloud identity never reaches the clone over its `.env`."""
    pinned = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"}
    for name in pinned:
        monkeypatch.setenv(name, "")
    assert not pinned & set(proof.child_env()), sorted(pinned & set(proof.child_env()))


def test_the_clone_inherits_no_name_that_steers_a_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The proof's child environment is `env.STEERS`-free: the one source, never a hand list."""
    from quality.djb import env as djb_env

    for name in djb_env.STEERS:
        monkeypatch.setenv(name, "1")
    leaked = set(djb_env.STEERS) & set(proof.child_env())
    assert not leaked, sorted(leaked)


def test_the_lane_reader_takes_the_word_the_touched_apps_and_the_tax() -> None:
    text = (
        "loop\n  lane:       loop — no forced path\n  scope   touched: example\n"
        "  tax: 3.3 min in 2 member(s) the diff did not own — x(1.2); whole: ? (reported)\n"
    )
    assert proof.read_lane(text) == ("loop", ["example"], "3.3")
    assert proof.read_lane("full\n  forced:     quality/x.py (quality/)\n") == ("full", [], "-")


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_proof_runs_on_the_night_the_tag_and_the_hand_and_never_on_a_merge() -> None:
    """CI-THIRD-5 5.1: no `workflow_run` — the nightly, a dispatch, and the release's dispatch."""
    text = (ROOT / ".github/workflows/proof-from-zero.yml").read_text()
    flow = yaml.safe_load(text)
    on = flow[True]
    assert set(on) == {"workflow_dispatch", "schedule"}
    assert on["schedule"] == [{"cron": "53 7 * * *"}]
    assert on["workflow_dispatch"]["inputs"]["ref"]["required"] is True
    gate = flow["jobs"]["proof"]["if"]
    assert "workflow_run" not in gate, gate
    assert gate == "github.event_name == 'workflow_dispatch' || github.event_name == 'schedule'"
    steps = flow["jobs"]["proof"]["steps"]
    runs = " ".join(str(s.get("run", "")) for s in steps)
    assert "python3 -E -S -m quality.djb.rituals.proof_from_zero --inputs" in runs
    assert "python3 -E -S -m quality.djb.ledger proof-consult" in runs
    assert "./scripts/proof_from_zero.sh --ref HEAD --where ci" in runs
    (upload,) = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert upload["if"].startswith("always()") and upload["with"]["name"] == "proof-from-zero"


ZSH_STEP = "the shell the gate's own tests drive — zsh"
WORKFLOWS = ("ci.yml", "proof-from-zero.yml")


def test_the_proof_installs_the_shell_the_gate_legs_install_before_its_loops() -> None:
    """A runner has no zsh; the loop's harness drives `db.sh` under one, as `ci.yml`'s legs do."""
    flows = [yaml.safe_load((ROOT / ".github/workflows" / f).read_text()) for f in WORKFLOWS]
    leg = next(
        s for job in flows[0]["jobs"].values() for s in job["steps"] if s.get("name") == ZSH_STEP
    )
    steps = flows[1]["jobs"]["proof"]["steps"]
    names = [s.get("name") for s in steps]
    assert ZSH_STEP in names, names
    mine = steps[names.index(ZSH_STEP)]
    assert mine["run"] == leg["run"] and mine["env"] == leg["env"]
    assert names.index(ZSH_STEP) < names.index("the proof (./scripts/proof_from_zero.sh)")


LANE_STEP = "the lane — does this merge touch what the proof drives"


@pytest.mark.parametrize(
    ("path", "prove"),
    [
        ("apps/core/scaffold/x.py", "yes"),
        ("pilecap/x.py", "yes"),
        ("scripts/setup.sh", "yes"),
        ("docs" + "/product/q.md", "no"),
        ("quality/rules.yaml", "no"),
    ],
)
@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_proof_follows_its_own_inputs_not_the_lane_word(
    tmp_path: Path, path: str, prove: str
) -> None:
    assert _merge_proves(tmp_path, path) == prove


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_an_apps_only_merge_does_not_prove(tmp_path: Path) -> None:
    """A product-shaped merge (an app's models) moves no input: the night proves that tree."""
    assert _merge_proves(tmp_path, "apps/core/models.py") == "no"


def _merge_proves(tmp_path: Path, path: str) -> str:
    flow = yaml.safe_load((ROOT / ".github/workflows/proof-from-zero.yml").read_text())
    (lane,) = [s for s in flow["jobs"]["proof"]["steps"] if s.get("name") == LANE_STEP]
    repo = tmp_path / "repo"
    git = ["git", "-C", str(repo), "-c", "user.email=d@example.invalid", "-c", "user.name=d"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "seed.txt").write_text("seed\n")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], check=True)
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text("moved\n")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "the merge"], check=True)
    for package in ("quality", "apps"):
        shutil.rmtree(repo / package, ignore_errors=True)
        (repo / package).symlink_to(ROOT / package)
    output = tmp_path / "out"
    done = subprocess.run(
        ["bash", "-c", lane["run"]],
        cwd=repo,
        env={"PATH": "/usr/bin:/bin", "EVENT": "workflow_run", "GITHUB_OUTPUT": str(output)}
        | {"RUNNER_TEMP": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return output.read_text().removeprefix("prove=").strip()


PRODUCT_TREE = "a product tree declares a namespace: the proof from zero is the template's"


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_lane_says_no_in_a_tree_whose_drawer_declares_a_namespace(tmp_path: Path) -> None:
    flow = yaml.safe_load((ROOT / ".github/workflows/proof-from-zero.yml").read_text())
    (lane,) = [s for s in flow["jobs"]["proof"]["steps"] if s.get("name") == LANE_STEP]
    (tmp_path / "quality/local").mkdir(parents=True)
    (tmp_path / "quality/local/rules.yaml").write_text("rule_id_namespace: workbench\n")
    output = tmp_path / "out"
    done = subprocess.run(
        ["bash", "-c", lane["run"]],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "EVENT": "workflow_dispatch", "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert output.read_text() == "prove=no\n"
    assert PRODUCT_TREE in done.stdout


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_lane_reads_an_empty_quoted_namespace_as_no_namespace(tmp_path: Path) -> None:
    flow = yaml.safe_load((ROOT / ".github/workflows/proof-from-zero.yml").read_text())
    (lane,) = [s for s in flow["jobs"]["proof"]["steps"] if s.get("name") == LANE_STEP]
    (tmp_path / "quality/local").mkdir(parents=True)
    (tmp_path / "quality/local/rules.yaml").write_text('rule_id_namespace: ""\n')
    output = tmp_path / "out"
    done = subprocess.run(
        ["bash", "-c", lane["run"]],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "EVENT": "workflow_dispatch", "GITHUB_OUTPUT": str(output)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert output.read_text() == "prove=yes\n"
    assert PRODUCT_TREE not in done.stdout


def test_the_ritual_refuses_in_a_product_tree_before_any_step(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def never(*_: object) -> None:
        raise AssertionError("a step ran in a product tree")

    from quality.engine import rules

    monkeypatch.setattr(rules, "declared_namespace", lambda: "workbench")
    monkeypatch.setattr(proof, "Proof", never)
    assert proof.main(["--ref", "HEAD"]) == 2
    assert PRODUCT_TREE in capsys.readouterr().err


def test_the_template_declares_no_namespace_so_the_ritual_proves() -> None:
    from quality.engine.rules import declared_namespace

    assert declared_namespace() is None


def _listed(path: str) -> bool:
    return any(path == one or (one.endswith("/") and path.startswith(one)) for one in proof.INPUTS)


def unlisted(source: str, root: Path = ROOT) -> list[str]:
    """Every script, `manage.py` command and reference the ritual's source drives, not listed."""
    import ast

    out: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if re.fullmatch(r"\./scripts/[\w.-]+", node.value) and not _listed(node.value[2:]):
                out.append(node.value[2:])
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "manage":
            arg = node.args[1]
            word = str(arg.value) if isinstance(arg, ast.Constant) else "?"
            found = sorted(root.glob(f"apps/*/management/commands/{word}.py"))
            home = found[0].relative_to(root).as_posix() if found else "uv.lock"
            if not _listed(home) or not _listed("manage.py"):
                out.append(f"manage.py {word} ({home})")
    if not _listed(f"{proof.REFERENCE}/x"):
        out.append(proof.REFERENCE)
    return out


def test_every_path_the_ritual_drives_is_in_its_input_list() -> None:
    source = (ROOT / "quality/djb/rituals/proof_from_zero.py").read_text()
    assert unlisted(source) == []
    planted = (
        source
        + '\n\ndef _planted(self):\n    self.run_logged("x", ["./scripts/zzz_unlisted.sh"])\n'
    )
    assert unlisted(planted) == ["scripts/zzz_unlisted.sh"]
    planted = source + '\n\ndef _planted(self):\n    self.manage("x", "zzz_unlisted")\n'
    assert unlisted(planted) == []  # a builtin command resolves to the lock, which is listed
    assert all((ROOT / one.rstrip("/")).exists() for one in proof.INPUTS), proof.INPUTS


def test_the_inputs_print_on_the_stdlib_floor(tmp_path: Path) -> None:
    said = tmp_path / "inputs.log"
    with said.open("w") as sink:
        rc = subprocess.run(
            [sys.executable, "-E", "-S", "-m", "quality.djb.rituals.proof_from_zero", "--inputs"],
            cwd=ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        ).returncode
    assert rc == 0, said.read_text()
    assert said.read_text().splitlines() == list(proof.INPUTS)


@pytest.mark.template_only(
    reason="the proof from zero is the template's own workflow; a product never receives it"
)
def test_the_lane_step_runs_before_any_install() -> None:
    """A run that proves nothing installs nothing: the lane is asked on the runner's own python."""
    flow = yaml.safe_load((ROOT / ".github/workflows/proof-from-zero.yml").read_text())
    steps = flow["jobs"]["proof"]["steps"]
    names = [s.get("name") for s in steps]
    lane = names.index(LANE_STEP)
    assert lane < names.index("Install uv") < names.index("Install dependencies")
    assert "uv " not in steps[lane]["run"] and ".venv" not in steps[lane]["run"]
    assert all(s.get("if", "").startswith("steps.lane.outputs.prove == 'yes'") for s in steps[2:4])


#: The release's `gh`: no proof until `workflow run` dispatches one, whose record is FAKE_PROOF_RC.
RELEASE_GH = """#!/usr/bin/env bash
G=__G__
printf '%s\\n' "$*" >>"$G/calls"
case "$1 ${2:-}" in
"api repos/{owner}/{repo}/commits/"*) printf '%s\\n' "${2##*/}"; exit 0 ;;
"api "*) cat "$G/runs" 2>/dev/null; exit 0 ;;
"run list") cat "$G/runs" 2>/dev/null; exit 0 ;;
"workflow run") echo 41 >>"$G/runs"; cp "$G/dispatched" "$G/record-41"; exit 0 ;;
"run watch") exit "$(cat "$G/watch.rc" 2>/dev/null || echo 0)" ;;
"run download")
    run=$3 dir=""
    while [ "$#" -gt 0 ]; do case "$1" in --dir) dir=$2; shift 2 ;; *) shift ;; esac; done
    [ -f "$G/record-$run" ] || { echo "no artifact matches" >&2; exit 1; }
    mkdir -p "$dir"; cp "$G/record-$run" "$dir/proof_from_zero.txt"; exit 0 ;;
esac
echo "fake gh: no fixture for: $*" >&2
exit 1
"""


def _released(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rc: str) -> tuple[int, str]:
    from quality.djb.rituals import publish

    src = tmp_path / "src"
    flow = src / ".github/workflows/proof-from-zero.yml"
    flow.parent.mkdir(parents=True)
    flow.write_text("name: proof-from-zero\n")
    git = ["git", "-C", str(src), "-c", "user.email=d@example.invalid", "-c", "user.name=d"]
    subprocess.run(["git", "init", "-q", str(src)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "the release's source"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    export_tree = "e" * 40
    fields = [STAMP, "a" * 40, export_tree, "3", "loop,loop,loop", "0,0,0", "1,1,1"]
    fields += ["201,233,250", "3", "1", *SDK, rc, "41", "ci"]
    g = tmp_path / "gh"
    (g / "bin").mkdir(parents=True)
    (g / "dispatched").write_text(ledger.proof_line(fields) + "\n")
    (g / "bin" / "gh").write_text(RELEASE_GH.replace("__G__", str(g)))
    (g / "bin" / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", f"{g / 'bin'}:/usr/bin:/bin")
    monkeypatch.setattr(publish, "PROOF_POLL_S", 0)
    ritual = publish.Publish(src, publish.Args())
    ritual.src_sha, ritual.tree = sha.strip(), export_tree
    ritual.proof()
    return ritual.violations, (g / "calls").read_text()


def test_the_release_refuses_to_tag_a_tree_whose_proof_did_not_return_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """5.1: `publish --release` dispatches the proof on the source and tags only on its green."""
    violations, calls = _released(tmp_path / "red", monkeypatch, rc="1")
    said = capsys.readouterr().out
    assert violations == 1, said
    assert "proof: the export tree eeeeeeeeeeee" in said and "nothing is tagged" in said, said
    assert "workflow run proof-from-zero.yml -f ref=" in calls, calls
    assert calls.index("/commits/") < calls.index("workflow run"), "origin is asked first"
    assert "run watch 41" in calls, calls
    violations, calls = _released(tmp_path / "green", monkeypatch, rc="0")
    said = capsys.readouterr().out
    assert violations == 0, said
    assert "ok — proof-consult: honoured run=41" in said, said


def test_the_proofs_clone_is_the_export_not_the_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    """A path the manifest trims is in the source and absent from the clone the road runs in."""
    from quality.tests.fixtures.scratch import require_scratch
    from quality.tests.test_publish import CY, PLAN, build_fixture

    base = require_scratch(tmp_path, request.config.rootpath)
    source = build_fixture(base / "source")
    assert (source / CY / PLAN).is_file()
    monkeypatch.setattr(proof, "ROOT", source)
    args = Namespace(ref="HEAD", plant="", dest=str(base / "clone"), out=str(base / "out"))
    run = proof.Proof(args)
    run.out_dir.mkdir()
    run.clone()
    assert (run.dest / "manage.py").is_file(), sorted(p.name for p in run.dest.iterdir())
    assert not (run.dest / CY / PLAN).exists(), "the clone holds a trimmed path: it is the source"


CONSULT_GH = """#!/usr/bin/env bash
case "$1 ${2:-}" in
"api "*) printf '%s\\n' 3 2 1; exit 0 ;;
"run download")
    run=$3 dir=""
    while [ "$#" -gt 0 ]; do case "$1" in --dir) dir=$2; shift 2 ;; *) shift ;; esac; done
    [ -f "__RECORDS__/$run" ] || { echo "no artifact matches" >&2; exit 1; }
    mkdir -p "$dir"; cp "__RECORDS__/$run" "$dir/proof_from_zero.txt"; exit 0 ;;
esac
exit 1
"""


def _record(source: str, tree: str, rc: str = "0") -> str:
    fields = [STAMP, source, tree, "3", "loop,loop,loop", "0,0,0", "1,1,1", "201,233,250"]
    return ledger.proof_line([*fields, "3", "1", *SDK, rc, "777", "ci"]) + "\n"


def test_the_consult_honours_the_export_tree_whatever_source_cut_it(tmp_path: Path) -> None:
    """The export tree is the key: another source sha is honoured, a source tree is not."""
    repo = tmp_path / "src"
    git = ["git", "-C", str(repo), "-c", "user.email=d@example.invalid", "-c", "user.name=d"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a.txt").write_text("a\n")
    subprocess.run([*git, "add", "a.txt"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "the source"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True).stdout
    source_tree = subprocess.run(
        [*git, "rev-parse", "HEAD^{tree}"], capture_output=True, text=True
    ).stdout.strip()
    export_tree = "e" * 40
    records, bin_ = tmp_path / "records", tmp_path / "bin"
    records.mkdir()
    bin_.mkdir()
    (bin_ / "gh").write_text(CONSULT_GH.replace("__RECORDS__", str(records)))
    (bin_ / "gh").chmod(0o755)
    gh = str(bin_ / "gh")
    (records / "3").write_text(_record("b" * 40, export_tree, rc="1"))
    (records / "2").write_text(_record(sha.strip(), source_tree))
    line, run = ledger.proof_consult(repo, export_tree, gh=gh)
    assert (run, line.startswith("proof-consult: prove — no completed run")) == ("", True), line
    (records / "1").write_text(_record("a" * 40, export_tree))
    line, run = ledger.proof_consult(repo, export_tree, gh=gh)
    assert (line, run) == (f"proof-consult: honoured run=1 tree={export_tree}", "1")
