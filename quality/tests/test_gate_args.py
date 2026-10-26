"""`quality.djb.gate_args` refuses every argv `check.sh` refused, in the shell's own bytes."""

# Invariant: the shell is read at `SHELL_AT`, the last commit whose `check.sh` is the shell gate.
# does-not-cover: a refusal that needs a live lease, lock or box — test_cli's cases are those.

from __future__ import annotations

import os
import subprocess
import tarfile
from collections.abc import Iterator, Sequence
from io import BytesIO
from pathlib import Path

import pytest

from quality.djb import gate_args
from quality.djb.gate_args import Refusal, Request

pytestmark = pytest.mark.drives("quality/djb/gate_args.py")

ROOT = Path(__file__).resolve().parents[2]
#: The last commit whose `scripts/check.sh` is the shell gate this grammar is measured against.
SHELL_AT = "478358bf"

#: Every argv the grammar refuses before a unit table is read.
PARSE_REFUSED = (
    ("--bogus",),
    ("--fast", "--mine"),
    ("--fast", "--store-durations"),
    ("--loop", "--store-durations"),
    ("--census", "--store-durations"),
    ("--loop", "extra"),
    ("--loop", "--mine", "extra"),
    ("--list-legs", "--bogus"),
    ("--fast", "--shard", "1/2"),
    ("--pr",),
    ("--pr", "--base"),
    ("--bank", "--mine"),
    ("--store-durations", "--mine"),
)
#: Every argv refused against the unit table.
UNIT_REFUSED = (
    ("--leg",),
    ("--leg", "nope"),
    ("--leg", "static", "--shard", "1/2"),
    ("--leg", "pytest-x2", "--shard", "x"),
    ("--leg", "pytest-x2", "--shard=3/2"),
    ("--leg", "pytest-x2", "--shard", "0/2"),
    ("--leg", "pytest-x2", "--shard", "1/0"),
    ("--leg", "pytest-x2", "--passes", "3"),
    ("--leg", "static", "--passes", "1"),
    ("--leg", "pytest-x2", "--passes", "1", "--store-durations"),
    ("--leg", "pytest-x2", "--passes=1"),
    ("--leg", "static", "--store-durations"),
    ("--leg", "pytest-x2", "--shard", "1/2", "--store-durations"),
    ("--leg", "pytest-x2", "--shard"),
)


@pytest.fixture(scope="module")
def shell(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A scratch git repository holding the tree at `SHELL_AT`, with this checkout's venv."""
    done = subprocess.run(
        ["git", "-C", str(ROOT), "archive", SHELL_AT], capture_output=True, check=False
    )
    if done.returncode != 0:
        pytest.skip(f"the shell gate's commit {SHELL_AT} is not in this repository")
    home = tmp_path_factory.mktemp("shell-gate")
    with tarfile.open(fileobj=BytesIO(done.stdout)) as archive:
        archive.extractall(home, filter="tar")
    git = ["git", "-C", str(home), "-c", "user.email=g@x", "-c", "user.name=g"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
    subprocess.run([*git, "commit", "-qm", "shell", "--no-verify"], check=True)
    (home / ".venv").symlink_to(ROOT / ".venv")
    yield home


def _env(**extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DJB_", "GATE_"))}
    env.pop("CI", None)
    return {**env, **extra}


def _run(home: Path, argv: Sequence[str], env: dict[str, str]) -> tuple[int, str, str]:
    """The shell gate with stdout to a file, as its pipe guard demands."""
    out = home / ".stdout"
    with out.open("w") as sink:
        done = subprocess.run(
            ["bash", "scripts/check.sh", *argv],
            cwd=home,
            stdout=sink,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            check=False,
        )
    return done.returncode, out.read_text(), done.stderr


def _shell(home: Path, argv: Sequence[str], **extra: str) -> tuple[int, str]:
    code, _, err = _run(home, argv, _env(**extra))
    return code, err


def _python(argv: Sequence[str], listing: str) -> tuple[int, str]:
    try:
        req = gate_args.parse(argv)
        gate_args.check_pr_base(ROOT, req)
        if req.mode == "--leg":
            gate_args.check_unit(req, listing)
    except Refusal as refusal:
        return refusal.code, "".join(f"{line}\n" for line in refusal.lines)
    return 0, ""


@pytest.fixture(scope="module")
def listing(shell: Path) -> str:
    code, out, err = _run(shell, ["--list-legs"], _env())
    assert code == 0, err
    return out


@pytest.mark.parametrize("argv", PARSE_REFUSED + UNIT_REFUSED, ids=" ".join)
def test_every_refused_argv_is_refused_in_the_shells_bytes(
    shell: Path, listing: str, argv: tuple[str, ...]
) -> None:
    expected = _shell(shell, argv)
    assert expected[0] == 2, expected
    assert _python(argv, listing) == expected


@pytest.mark.parametrize(
    ("argv", "want"),
    [
        ((), Request()),
        (("--bank",), Request(bank=True)),
        (("--store-durations",), Request(store_members=True)),
        (("--loop", "--mine"), Request(mode="--loop", mine=True)),
        (("--list-legs", "--ci"), Request(mode="--list-legs", list_legs=True, list_ci=True)),
        (("--pr", "--base", "abc"), Request(pr=True, pr_base="abc")),
        (("--pr", "--base=abc"), Request(pr=True, pr_base="abc")),
        (
            ("--leg", "pytest-x2", "--shard", "1/2", "--passes", "1", "--pr", "--base", "a"),
            Request(
                mode="--leg",
                unit="pytest-x2",
                shard="1/2",
                shard_given=True,
                passes="1",
                passes_given=True,
                pr=True,
                pr_base="a",
            ),
        ),
    ],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else "",
)
def test_an_accepted_argv_parses_to_the_shells_variables(
    argv: tuple[str, ...], want: Request
) -> None:
    assert gate_args.parse(argv) == want


def test_the_unsanctioned_full_gate_is_refused_in_the_shells_bytes(shell: Path) -> None:
    code, err = _shell(shell, ())
    with pytest.raises(Refusal) as refused:
        gate_args.sanction(ROOT, Request(), {})
    assert (code, err) == (2, "".join(f"{x}\n" for x in refused.value.lines))


def test_a_shapeless_sanction_is_refused_in_the_shells_bytes(shell: Path) -> None:
    code, err = _shell(shell, (), DJB_GATE_SANCTION="no reason")
    with pytest.raises(Refusal) as refused:
        gate_args.sanction_shape({"DJB_GATE_SANCTION": "no reason"})
    assert (code, err) == (2, "".join(f"{x}\n" for x in refused.value.lines))


def test_the_off_box_refusal_is_the_shells_bytes(shell: Path) -> None:
    marker = str(shell / "no-such-marker")
    got = _shell(shell, ("--loop",), DJB_GATE_BOX_MARKERS=marker, DJB_LOOP_NO_CACHE="1")
    assert gate_args.loop_here({}, None) is None
    assert got == (2, "".join(f"{x}\n" for x in gate_args.OFF_BOX))


def test_a_shapeless_loop_here_is_refused_in_the_shells_bytes(shell: Path) -> None:
    got = _shell(shell, ("--loop",), DJB_LOOP_HERE="because")
    with pytest.raises(Refusal) as refused:
        gate_args.loop_here({"DJB_LOOP_HERE": "because"}, None)
    assert got == (2, "".join(f"{x}\n" for x in refused.value.lines))


def test_a_typed_sanction_names_who_and_why() -> None:
    said = gate_args.sanction(ROOT, Request(), {"DJB_GATE_SANCTION": "gf-5: the canary: point"})
    assert said == gate_args.Sanctioned(
        "DJB_GATE_SANCTION=gf-5: the canary: point", "typed", "gf-5", "the canary: point"
    )


def test_bank_from_a_linked_worktree_is_refused_naming_it(tmp_path: Path) -> None:
    git = ["git", "-c", "user.email=g@x", "-c", "user.name=g"]
    main = tmp_path / "main"
    main.mkdir()
    subprocess.run([*git, "-C", str(main), "init", "-q", "-b", "main"], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    linked = tmp_path / "rung"
    subprocess.run(
        [*git, "-C", str(main), "worktree", "add", "-q", "-b", "rung", str(linked)], check=True
    )
    assert gate_args.bank_sanction(main, {}).kind == "bank"
    with pytest.raises(Refusal) as refused:
        gate_args.bank_sanction(linked, {})
    assert refused.value.lines[0] == f"!! --bank from a LINKED worktree: {linked.resolve()}"


def test_ci_and_the_push_wall_are_sanctions_of_their_own() -> None:
    ci = gate_args.sanction(ROOT, Request(), {"CI": "1"})
    assert ci is not None and (ci.kind, ci.who) == ("ci", "CI")
    wall = gate_args.sanction(ROOT, Request(), {"DJB_GATE_CALLER": "push-wall"})
    assert wall is not None and (wall.kind, wall.who) == ("push-wall", "pre-push")
    assert gate_args.sanction(ROOT, Request(mode="--loop"), {}) is None


@pytest.mark.parametrize(
    ("argv", "want"),
    [
        (("--loop", "--here", "x-1: why"), Request(mode="--loop", here="x-1: why")),
        (("--loop", "--here=x-1: why"), Request(mode="--loop", here="x-1: why")),
        (
            ("--loop", "--mine", "--here", "x-1: why"),
            Request(mode="--loop", mine=True, here="x-1: why"),
        ),
        (
            ("--loop", "--here", "x-1: why", "--mine"),
            Request(mode="--loop", mine=True, here="x-1: why"),
        ),
    ],
    ids=lambda v: " ".join(v) if isinstance(v, tuple) else "",
)
def test_the_loop_valve_parses_as_a_flag_beside_loop(argv: tuple[str, ...], want: Request) -> None:
    assert gate_args.parse(argv) == want


@pytest.mark.parametrize(
    "argv",
    [("--here", "x-1: why"), ("--fast", "--here", "x-1: why"), ("--census", "--here", "x: y")],
    ids=" ".join,
)
def test_the_valve_flag_without_loop_is_refused_by_name(argv: tuple[str, ...]) -> None:
    with pytest.raises(Refusal) as refused:
        gate_args.parse(argv)
    assert refused.value.lines == (gate_args.HERE_ELSEWHERE,)
    assert refused.value.code == 2


def test_a_mistyped_flag_beside_the_valve_still_refuses() -> None:
    with pytest.raises(Refusal) as refused:
        gate_args.parse(("--loopx", "--here", "x-1: why"))
    assert refused.value.lines == (gate_args.UNKNOWN.format(word="--loopx"),)
    with pytest.raises(Refusal):
        gate_args.parse(("--loop", "--here"))


def test_a_bare_id_through_the_flag_is_refused_by_the_one_shape_check() -> None:
    with pytest.raises(Refusal) as refused:
        gate_args.loop_here({}, None, "loop-here")
    said = "\n".join(refused.value.lines)
    assert "--here is given but is not a reason" in said
    assert "got:  loop-here" in said
    assert 'want: ./scripts/check.sh --loop --here "<rung-id>: <reason>"' in said


def test_the_flag_wins_over_the_environment_and_says_so() -> None:
    typed = "loop-here: the valve as a flag"
    assert gate_args.loop_here({}, None, typed) == f"--here {typed}"
    both = gate_args.loop_here({"DJB_LOOP_HERE": "x-1: the env form"}, None, typed)
    assert both == f"--here {typed} (the flag wins over DJB_LOOP_HERE=x-1: the env form)"
    assert gate_args.loop_here({"DJB_LOOP_HERE": "because"}, None, typed) == (
        f"--here {typed} (the flag wins over DJB_LOOP_HERE=because)"
    )
