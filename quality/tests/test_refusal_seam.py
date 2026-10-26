"""The refusal seam's three words, its belt, and the censuses that keep every script on them."""

# does-not-cover: a caller that prints its own `!!` and exits 2 without gate_die.
# does-not-cover: a caller that should have said finding and said could-not-look instead.
# does-not-cover: a pipe guard below its caller's parser — each caller is driven with --help only.
# does-not-cover: a Python script printing its own `!!` line — the class census reads classes.
# does-not-cover: the git hooks and deploy/ for the belt; a shell this machine lacks is not run.
# does-not-cover: a symlinked script — BASH_SOURCE is read unresolved.
# does-not-cover: an exit computed (`exit "$rc"`) or a `return` after a banner; Python banners.
# does-not-cover: a pipe test spelled other than `-p /dev/fd/1` — it reads as no guard at all.
# does-not-cover: a could-not-look class saying so in neither its name nor its docstring's line 1.
# does-not-cover: whether an allow-list row's reason is still true — a file and a reason only.
# does-not-cover: a real database server — perf's db.sh is a stand-in answering one planted world.
# does-not-cover: any restore_drill refusal after the source check.

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook

pytestmark = pytest.mark.drives("scripts/", "deploy/")

ROOT = Path(__file__).resolve().parents[2]
BELT_LINE = '. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2'
SEAM = "scripts/gate_refuse.sh"
# Sites another consolidation holds today; removing a row is the PR that moves the site.
_DEPLOY = "the deploy scripts take the seam with the deployment's own consolidation"
ALLOW_LIST: tuple[tuple[str, str], ...] = (
    ("deploy/release.sh", _DEPLOY),
    ("deploy/stage.sh", _DEPLOY),
    ("deploy/teardown.sh", _DEPLOY),
    ("deploy/ship.sh", _DEPLOY),
    ("deploy/verifier/bake.sh", _DEPLOY),
    ("deploy/iam/verifier_bootstrap.sh", _DEPLOY),
    (
        "quality/partition.py",
        "its Broken (exit 2) is the partition reader's own; the quality engine's "
        "consolidation takes the shared class",
    ),
    (
        "quality/tools/split_module.py",
        "its Refused (exit 2) is the split tool's own, a standard-library-only tool; "
        "taking the shared class is an edit to the tool",
    ),
)
ALLOWED = frozenset(path for path, _ in ALLOW_LIST)

# (a)'s reader: each `!!` banner followed by a literal exit other than 2, quoted text blanked.
BANNER_AWK = r"""
function unquote(s) { gsub(/\\"/, "", s); gsub(/"[^"]*"/, "\"\"", s); gsub(/\047[^\047]*\047/, "\047\047", s); return s }
function judge(rest,   m) {
    rest = unquote(rest)
    if (match(rest, /(^|[^A-Za-z0-9_$])exit[ \t]+[0-9]+/)) { m = substr(rest, RSTART, RLENGTH); sub(/.*exit[ \t]+/, "", m); return m }
    if (match(rest, /(^|[^A-Za-z0-9_])exit[ \t]*($|;|\))/)) return "0 (bare)"
    if (match(rest, /(^|[^A-Za-z0-9_])exit[ \t]+["$]/)) return "computed"
    if (match(rest, /(^|[^A-Za-z0-9_])return([ \t]|$|;)/)) return "return"
    return ""
}
function verdict(v) { if (v != "2" && v != "return" && v != "computed") printf "%s:%d: a `!!` banner followed by exit %s\n", FILENAME, bl, v }
FNR == 1 { open = 0 }
{
    line = $0
    if (line ~ /^[ \t]*#/) next
    if (open) {
        if (line ~ /^[ \t]*(echo|printf)[ \t]/) { } else {
            v = judge(line)
            if (v != "") { verdict(v); open = 0 }
            else if (line ~ /^}|^[ \t]*(fi|else|elif|;;|esac|done)([ \t;]|$)/) open = 0
        }
    }
    if (line ~ /(echo|printf)[ \t]+(-[en]+[ \t]+)?["\047]( |\\n)*!!/) {
        bl = FNR
        v = judge(line)
        if (v != "") { verdict(v); open = 0 } else open = 1
    }
}"""  # noqa: E501
MEANS = re.compile(r"cannot|could ?not|refus|exit 2", re.I)


@dataclass(frozen=True)
class Ran:
    """One run: its exit, and its stdout and stderr read back from their own files."""

    rc: int
    out: str
    err: str


def _run(
    scratch: Path,
    name: str,
    argv: Sequence[str],
    cwd: Path = ROOT,
    env: Mapping[str, str] | None = None,
) -> Ran:
    """`argv` with stdout and stderr each to its own file under `scratch`, never a pipe."""
    out, err = scratch / f"{name}.out", scratch / f"{name}.err"
    with out.open("wb") as o, err.open("wb") as e:
        done = subprocess.run(
            list(argv), cwd=cwd, stdout=o, stderr=e, stdin=subprocess.DEVNULL, env=env
        )
    return Ran(done.returncode, out.read_text(errors="replace"), err.read_text(errors="replace"))


def _bash(scratch: Path, name: str, script: str, cwd: Path = ROOT) -> Ran:
    return _run(scratch, name, ["bash", "-c", script, "_", str(ROOT)], cwd)


def _ls(*args: str) -> list[str]:
    done = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise CouldNotLook(f"git {' '.join(args)} could not list the tree: {done.stderr}")
    return done.stdout.splitlines()


def script_population() -> list[str]:
    """Every tracked `.sh` under scripts/ and deploy/, their tests/ excepted."""
    return [p for p in _ls("ls-files", "--", "scripts/*.sh", "deploy/*.sh") if "/tests/" not in p]


def belt_population() -> list[str]:
    """Mode-755 `.sh` under scripts/, its tests excepted."""
    found = []
    for line in _ls("ls-files", "-s", "--", "scripts/*.sh"):
        mode, path = line.split()[0], line.split("\t", 1)[1]
        if mode == "100755" and not path.startswith("scripts/tests/"):
            found.append(path)
    return found


def class_population(root: Path) -> list[str]:
    """`scripts/*.py` and `quality/**/*.py` (canaries and negatives aside), the allow-list out."""
    listed = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", "scripts/*.py", "quality/*.py"],
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        raise CouldNotLook(f"git ls-files could not list {root}: {listed.stderr}")
    kept = []
    for path in listed.stdout.split():
        parts = path.split("/")
        top = len(parts) == 2
        deep = parts[0] == "quality" and not re.search(r"/(canary|negative)/", path)
        if (top or deep) and path not in ALLOWED:
            kept.append(path)
    return kept


def could_not_look_strays(root: Path, paths: Sequence[str]) -> list[str]:
    """`file:line: class X(Exception)` for each bare-Exception class that means could-not-look."""
    named = []
    for path in paths:
        if path == "quality/could_not_look.py":
            continue
        try:
            tree = ast.parse((root / path).read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as error:
            named.append(f"{path}: could not parse ({error})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if [b.id for b in node.bases if isinstance(b, ast.Name)] != ["Exception"]:
                continue
            doc = (ast.get_docstring(node) or "").splitlines()[:1]
            if MEANS.search(node.name) or (doc and MEANS.search(doc[0])):
                named.append(f"{path}:{node.lineno}: class {node.name}(Exception)")
    return named


def _python() -> Path:
    py = ROOT / ".venv/bin/python"
    if not os.access(py, os.X_OK):
        raise CouldNotLook("this checkout has no .venv/bin/python")
    return py


# --- the seam's three words -----------------------------------------------------------------------


def test_gate_die_is_exit_2_with_its_trailer(scratch: Path) -> None:
    state = scratch / "die.state"
    run = _bash(
        scratch,
        "die",
        f'. "$1/{SEAM}"\n'
        f'trap \'echo "cause=${{GATE_LAST_REFUSAL}} died=${{GATE_DIED}}" >"{state}"\' EXIT\n'
        "gate_die $'Nothing was touched.\\nAnd it says so twice.' "
        '"probe: the headline" "a further line"\n'
        f'echo returned >"{state}"\n',
    )
    assert run.rc == 2, run
    want = "!! probe: the headline\n   a further line\n   Nothing was touched.\n"
    assert run.err == want + "   And it says so twice.\n", run.err
    assert run.out == ""
    assert state.read_text() == "cause=probe: the headline died=1\n"


def test_gate_finding_is_exit_1_and_never_a_bang(scratch: Path) -> None:
    run = _bash(
        scratch, "finding", f'. "$1/{SEAM}"\ngate_finding "probe: it is wrong" $\'two\\nlines\''
    )
    assert run.rc == 1, run
    assert run.err == "RED: probe: it is wrong\n   two\n   lines\n", run.err


def test_a_piped_stdout_is_refused_with_the_one_sentence(scratch: Path) -> None:
    probe = '. "$1/scripts/gate_refuse.sh"; refuse_if_piped probe "why it matters"; echo passed'
    piped = _bash(scratch, "pipe", f"CI='' bash -c '{probe}' _ \"$1\" | cat")
    lines = piped.err.splitlines()
    assert "!! probe refuses pipes — run it bare or redirect to a file." in lines, piped.err
    assert "   The exit status is the verdict, and a filter replaces it." in lines, piped.err
    assert "   why it matters" in lines and "passed" not in piped.out, piped
    exempt = _bash(scratch, "pipe-ci", f"CI=1 bash -c '{probe}' _ \"$1\" | cat")
    assert "passed" in exempt.out, exempt
    callers = [
        p
        for p in _ls("grep", "-l", "^refuse_if_piped ", "--", "scripts/*.sh")
        if "/tests/" not in p
    ]
    assert callers, "no script calls refuse_if_piped — the population is empty"
    for path in callers:
        name = re.search(r"^refuse_if_piped (\S+)", (ROOT / path).read_text(), re.M)
        assert name is not None, path
        one = _bash(
            scratch,
            "pipe-one",
            f'cd "$1" && {{ env -u CI bash {path} --help </dev/null | cat >/dev/null; '
            'echo "${PIPESTATUS[0]}"; }',
        )
        assert one.out.strip() == "2", f"{path} piped: exit {one.out.strip()}, said: {one.err}"
        assert re.search(rf"^!! {re.escape(name.group(1))} refuses pipes", one.err, re.M), one.err


def test_the_python_mirror_says_it_alike(scratch: Path) -> None:
    mirror = (
        "import sys; sys.path.insert(0, sys.argv[1]); "
        "from quality.could_not_look import exit_could_not_look; "
        'exit_could_not_look("probe: the reason")'
    )
    py = _run(scratch, "py", [str(_python()), "-c", mirror, str(ROOT)], cwd=Path("/"))
    assert py.rc == 2 and py.err == "!! COULD NOT LOOK: probe: the reason\n", py
    sh = _bash(scratch, "sh", f'. "$1/{SEAM}"; gate_die "" "COULD NOT LOOK: probe: the reason"')
    assert sh.rc == 2 and sh.err == py.err, (sh, py)


def test_a_refusal_quotes_the_tools_last_lines() -> None:
    from quality.could_not_look import SAID, SAID_LINES, SAID_WIDTH, tool_said

    said = tool_said(b"Traceback\n\n" + b"".join(f"line {n}\n".encode() for n in range(9)))
    assert said.splitlines()[1:] == [f"{SAID}line {n}" for n in range(9 - SAID_LINES, 9)]
    assert said.startswith("\n") and tool_said(None) == "" and tool_said("  \n") == ""
    assert tool_said("x" * 999) == f"\n{SAID}{'x' * SAID_WIDTH}"


def test_the_tool_said_twins_say_it_alike(scratch: Path) -> None:
    from quality.could_not_look import tool_said

    text = "\n".join(["Traceback", "", *(f"line {n} " + "y" * 400 for n in range(7))]) + "\n"
    (scratch / "said.txt").write_text(text)
    sh = _bash(scratch, "said", f'. "$1/{SEAM}"; gate_tool_said "{scratch / "said.txt"}"')
    assert sh.rc == 0 and sh.err == tool_said(text).lstrip("\n") + "\n", (sh, tool_said(text))
    quiet = _bash(scratch, "quiet", f'. "$1/{SEAM}"; gate_tool_said "{scratch / "absent"}"')
    assert quiet.rc == 0 and quiet.err == "", quiet


# --- the belt -------------------------------------------------------------------------------------


def test_every_executable_refuses_sh_and_zsh_at_its_first_line(scratch: Path) -> None:
    population = [p for p in belt_population() if p not in ALLOWED]
    assert population, "the belt population is empty"
    firsts: dict[str, str] = {}
    for path in population:
        for line in (ROOT / path).read_text().splitlines():
            if line.strip() and not line.lstrip().startswith("#"):
                firsts[path] = line
                break
    assert sorted(p for p, line in firsts.items() if line != BELT_LINE) == []
    assert set(firsts.values()) == {BELT_LINE}
    sentence = r"(must run under bash — not sh, not zsh|bash is in POSIX mode)"
    for shell in ("sh", "dash", "zsh"):
        if shutil.which(shell) is None:
            continue
        for path in population:
            run = _run(scratch, "belt", [shell, str(ROOT / path), "--help"], cwd=Path("/"))
            said = run.err.splitlines()[:1]
            assert run.rc == 2, f"{shell} {path}: exit {run.rc}, said: {said}"
            assert re.search(rf"^{re.escape(Path(path).name)}: {sentence}", run.err, re.M), said
    if shutil.which("zsh") is not None:
        sourced = _run(scratch, "zsh", ["zsh", "-c", f". '{ROOT}/scripts/bash_only.sh'"])
        assert sourced.rc == 2, sourced


def test_the_belt_line_finds_its_file_from_anywhere(scratch: Path) -> None:
    world = scratch / "belt-world"
    (world / "scripts").mkdir(parents=True)
    (world / "elsewhere").mkdir()
    shutil.copy(ROOT / "scripts/bash_only.sh", world / "scripts")
    probe = world / "scripts/probe.sh"
    probe.write_text(
        f"#!/usr/bin/env bash\n{BELT_LINE}\necho ran:$#\nprobe_fn() {{ echo sourced; }}\n"
    )
    run = _run(scratch, "from-root", ["bash", str(probe), "a", "b"], cwd=Path("/"))
    assert run.rc == 0 and run.out == "ran:2\n", run
    caller = world / "elsewhere/caller.sh"
    caller.write_text(f'#!/usr/bin/env bash\n. "{probe}" x\nprobe_fn\n')
    run = _run(scratch, "sourced", ["bash", str(caller)], cwd=Path("/"))
    assert run.rc == 0 and run.out == "ran:1\nsourced\n", run


# --- the censuses ---------------------------------------------------------------------------------


def test_every_bang_banner_exits_2(scratch: Path) -> None:
    population = [p for p in script_population() if p not in ALLOWED]
    assert population, "the script population is empty"
    found: list[str] = []
    for path in population:
        run = _run(scratch, "awk", ["awk", BANNER_AWK, path])
        if run.rc != 0:
            raise CouldNotLook(f"awk could not read {path}: {run.err}")
        found.extend(run.out.splitlines())
    assert found == [], found


def test_every_pipe_guard_is_the_seams() -> None:
    named = [
        p
        for p in script_population()
        if p != SEAM and p not in ALLOWED and "-p /dev/fd/1" in (ROOT / p).read_text()
    ]
    assert named == [], f"a pipe guard of its own, not refuse_if_piped: {named}"


def test_every_could_not_look_class_is_the_one(scratch: Path) -> None:
    copy = scratch / "class-world"
    copy.mkdir()
    for path in ("scripts/plant_probe.py", "quality/deep/plant_probe.py"):
        (copy / path).parent.mkdir(parents=True, exist_ok=True)
        (copy / path).write_text(
            '"""a probe."""\n\n\nclass ProbeCannotLook(Exception):\n    """a plant."""\n'
        )
    subprocess.run(["git", "-C", str(copy), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(copy), "add", "."], check=True)
    planted = could_not_look_strays(copy, class_population(copy))
    assert planted == [
        "quality/deep/plant_probe.py:4: class ProbeCannotLook(Exception)",
        "scripts/plant_probe.py:4: class ProbeCannotLook(Exception)",
    ], planted
    population = class_population(ROOT)
    assert "quality/could_not_look.py" in population and "scripts/test_impact.py" in population
    assert could_not_look_strays(ROOT, population) == []


def test_allow_list_holds() -> None:
    missing = [p for p, reason in ALLOW_LIST if not reason or not (ROOT / p).is_file()]
    assert ALLOW_LIST and missing == [], missing


# --- the two `!!` refusals that exited 1, driven in worlds of their own ---------------------------


def test_perf_refuses_a_second_world_with_exit_2(scratch: Path) -> None:
    world = scratch / "perf-world"
    (world / "scripts").mkdir(parents=True)
    for name in ("perf.sh", "gate_refuse.sh", "bash_only.sh"):
        shutil.copy(ROOT / "scripts" / name, world / "scripts" / name)
    (world / "scripts/db.sh").write_text(
        'DATABASE_NAME="${DATABASE_NAME:-djb_probe_00000000}"\n'
        "db_query() { printf 'djb_planted_marker_perf\\n'; }\n"
    )
    subprocess.run(["git", "-C", str(world), "init", "-q"], check=True)
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_NAME"}
    run = _run(scratch, "perf", ["bash", "scripts/perf.sh"], cwd=world, env=env)
    assert run.rc == 2, run
    assert re.search(r"^!! REFUSING to seed a second perf world", run.err, re.M), run.err
    assert "djb_planted_marker_perf" in run.err, run.err
    assert "Nothing was dropped, created or seeded." in run.err, run.err


def test_restore_drill_refuses_the_source_with_exit_2(scratch: Path) -> None:
    dump = scratch / "same.dump"
    dump.write_text("not really a dump\n")
    (scratch / "same.dump.origin").write_text(
        f"project=djb-same\ndatabase=djb_same\nenv_file={scratch}/same.env\n"
        "taken_at=19700101T000000Z\n"
    )
    argv = ["bash", "scripts/restore_drill.sh", "--into-project", "djb-same", str(dump)]
    run = _run(scratch, "restore", argv)
    assert run.rc == 2, run
    assert re.search(r"^!! REFUSED: the restore target is the source\.", run.err, re.M), run.err
    assert "Nothing was restored." in run.err, run.err
