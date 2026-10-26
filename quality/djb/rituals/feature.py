"""The feature road: migrate, tidy, gate, the app's own tests — one block, one `next:`."""

# does-not-cover: what the red means — the line is the gate's own; the log has the rest.
# does-not-cover: a product's own legs beyond the gate's — `--loop` runs them as the gate does.

from __future__ import annotations

import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
USAGE = """\
usage: feature.sh <app> [--loop [--here "<app>: <why>"]] [--drive <Noun>]

  makemigrations <app> · rung_tidy.sh --client --budgets · check.sh --fast ·
  migrate (this checkout's database) · test.sh apps/<app>, one block, then
  `next:` — or the first red line, its file first. Green means the checkout is
  migrated and the app's own tests pass. --loop gates with the per-rung loop
  instead of --fast and test.sh, every leg run and every red named; --here says
  why that loop runs on this machine and not a verifier box; --drive <Noun> first
  runs drive_doors.sh <Noun> --preflight, then after the gate drives its doors.

exit: 0 green · 1 a step is red · 2 refused, or a step could not look.
"""
LOCATED = re.compile(
    r"(?P<at>(?:[\w.@-]+/)*[\w.@-]+\.(?:py|pyi|ts|tsx|js|mjs|sh|ya?ml|json|toml|md|txt|html)"
    r"(?::\d+)+)"
)
RED = re.compile(r"^\s*(?:x |!!|FAILED|ERROR|VIOLATION |-->)|\berror(?: TS\d+)?:|^[A-Z]+\d+ ")
RAISED = re.compile(r"^(?:[\w.]+\.)?[A-Z]\w*(?:Error|Exception): \S")
ABSENT = re.compile(r'FATAL:\s+database "(?P<name>[^"]+)" does not exist')
EVERY_RED = "- every red leg:"
#: A step's own could-not-look line, its remedy after `— next:`: the summary says it as written.
STUCK = re.compile(r"^could not (?:drive|look): (?P<what>.+?)(?: — next: (?P<remedy>.+))?$")
VERDICT = "doors agree"
LOWER = re.compile(r"\brule [\w-]+ ratchet:|\bLower it to\b")
LABEL = re.compile(r"^[a-z][a-z0-9_]*$")


def out(text: str = "") -> None:
    print(text, flush=True)


def err(text: str) -> None:
    print(text, file=sys.stderr, flush=True)


def piped() -> bool:
    if os.environ.get("CI"):
        return False
    try:
        return stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        return False


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class Ran:
    code: int
    seconds: int
    log: Path
    text: str


Runner = Callable[[Path, Step, str], Ran]


def run_step(root: Path, step: Step, tag: str) -> Ran:
    """`step` from `root` with its output in a log file of its own — every gate refuses a pipe."""
    handle, name = tempfile.mkstemp(prefix=f"{tag}-{step.name}.", suffix=".log")
    t0 = time.monotonic()
    with os.fdopen(handle, "w") as log:
        done = subprocess.run(
            list(step.argv), cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    text = Path(name).read_text(encoding="utf-8", errors="replace")
    return Ran(done.returncode, int(time.monotonic() - t0), Path(name), text)


def first_red(text: str) -> str:
    """The first red line of a log, located `file:line — what` when it names one; else the line."""
    lines = text.splitlines()
    unlocated = ""
    for number, line in enumerate(lines):
        if not RED.search(line):
            continue
        said = line.strip()
        found = LOCATED.search(said)
        if found is None:
            unlocated = unlocated or said
            continue
        if said.startswith("-->"):
            above = next((ln.strip() for ln in reversed(lines[:number]) if ln.strip()), "")
            return f"{found.group('at')} — {above}"
        rest = f"{said[: found.start()].rstrip(' :')} {said[found.end() :].lstrip(' :')}".strip()
        return f"{found.group('at')} — {rest}" if rest else found.group("at")
    return unlocated


def raised(text: str) -> str:
    """The first exception line a Python command printed, or nothing."""
    return next((ln.strip() for ln in text.splitlines() if RAISED.match(ln.strip())), "")


def absent_database(text: str) -> str:
    """Postgres naming a missing database, which outranks the pool error wrapped around it."""
    found = ABSENT.search(text)
    if found is None:
        return ""
    return (
        f"the database {found.group('name')} does not exist; this checkout's .env pin or "
        "scripts/db.sh's derivation named it (./scripts/setup.sh creates it)"
    )


def python(root: Path) -> str:
    venv = root / ".venv/bin/python"
    return str(venv) if venv.is_file() else sys.executable


def steps(root: Path, app: str, loop: bool, noun: str, here: str = "") -> list[Step]:
    """The road's commands in order: the gate, then the database migrated, then the tests."""
    gate = ("--loop", *(("--here", here) if here else ())) if loop else ("--fast",)
    road = [
        *([Step("preflight", ("./scripts/drive_doors.sh", noun, "--preflight"))] if noun else []),
        Step("makemigrations", (python(root), "manage.py", "makemigrations", app)),
        Step("tidy", ("./scripts/rung_tidy.sh", "--client", "--budgets")),
        Step("gate", ("./scripts/check.sh", *gate)),
        Step("migrate", (python(root), "manage.py", "migrate", "--noinput")),
    ]
    if not loop:
        road.append(Step("tests", ("./scripts/test.sh", f"apps/{app}")))
    if noun:
        road.append(Step("doors", ("./scripts/drive_doors.sh", noun)))
    return road


def green(app: str, loop: bool) -> str:
    """What the green road vouches for, said before its `next:`."""
    if loop:
        return f"green: this checkout's database is migrated and the loop passed, apps/{app} in it"
    return (
        f"green: this checkout's database is migrated and apps/{app}'s own tests pass; "
        "the apps that depend on it run in the loop"
    )


def finish(app: str, loop: bool, noun: str) -> str:
    """The green road's `next:`: the loop after `--fast`, the PR road after the loop."""
    here = f'--here "{app}: <why>"'
    if not loop:
        return f"next: ./scripts/feature.sh {app} --loop {here}"
    if not noun:
        return f"next: ./scripts/feature.sh {app} --loop {here} --drive <Noun>, or the PR road"
    return "next: ./scripts/pm_push.sh --pr; then deploy/stage.sh <host> --env staging"


def road(
    root: Path, app: str, loop: bool, noun: str, runner: Runner = run_step, here: str = ""
) -> int:
    """Run the road, one line per step; the first red stops it with its line and `next:`."""
    out(f"== feature {shlex.join(sys_args(app, loop, noun, here))}")
    for step in steps(root, app, loop, noun, here):
        ran = runner(root, step, f"feature-{app}")
        out(f"- {' '.join(step.argv[1:] if step.argv[1:2] == ('manage.py',) else step.argv)}")
        out(f"  exit {ran.code} ({ran.seconds}s) · log {ran.log}")
        if ran.code == 0:
            if verdict := next((ln for ln in ran.text.splitlines() if ln.startswith(VERDICT)), ""):
                out(f"  {verdict}")
            continue
        again = f"./scripts/feature.sh {shlex.join(sys_args(app, loop, noun, here))}"
        stuck = next(filter(None, map(STUCK.match, ran.text.splitlines())), None)
        drove = stuck is not None and stuck.string.startswith("could not drive:")
        if stuck is not None and (drove or (ran.code == 2 and stuck.group("remedy"))):
            out(f"could not look: {stuck.group('what')}")
            out(f"next: {stuck.group('remedy') or 'fix it there'}, then {again}")
            return 2
        summary = next((ln.strip() for ln in ran.text.splitlines() if EVERY_RED in ln), "")
        if summary:
            out(f"  {summary}")
        exception = raised(ran.text)
        absent = absent_database(ran.text)
        red = (
            (absent and f"{step.name} — {absent}")
            or first_red(ran.text)
            or (exception and f"{step.name} — {exception}")
            or "(no red line located — the log has the whole answer)"
        )
        word = "could not look" if ran.code == 2 else "red"
        lowers = [
            first_red(ln) for ln in ran.text.splitlines() if RED.search(ln) and LOWER.search(ln)
        ]
        for line in lowers if len(lowers) > 1 else [red]:
            out(f"{word}: {line}")
        out(f"next: fix it there, then {again}")
        return 2 if ran.code == 2 else 1
    out(green(app, loop))
    out(finish(app, loop, noun))
    return 0


def sys_args(app: str, loop: bool, noun: str, here: str = "") -> list[str]:
    valve = ["--here", here] if here else []
    return [app, *(["--loop", *valve] if loop else []), *(["--drive", noun] if noun else [])]


def parse(argv: Sequence[str]) -> tuple[str, bool, str, str] | None:
    """`(app, loop, noun, here)`, or None for `-h`; anything else unread is a `ValueError`."""
    words = list(argv)
    if any(w in ("-h", "--help") for w in words):
        return None
    loop = "--loop" in words
    words = [w for w in words if w != "--loop"]
    here = ""
    if "--here" in words:
        at = words.index("--here")
        if not loop:
            raise ValueError(
                "--here says why a --loop runs on this machine, and nothing else: "
                './scripts/feature.sh <app> --loop --here "<app>: <why>"'
            )
        if at + 1 >= len(words) or words[at + 1].startswith("--"):
            raise ValueError('--here takes its reason: --loop --here "<app>: <why>"')
        here = words.pop(at + 1)
        words.pop(at)
    noun = ""
    if "--drive" in words:
        at = words.index("--drive")
        if at + 1 >= len(words):
            raise ValueError("--drive takes the noun whose doors it drives")
        noun = words.pop(at + 1)
        words.pop(at)
    if len(words) != 1 or not LABEL.match(words[0]):
        raise ValueError(f"feature.sh takes one app label; got {' '.join(words) or 'none'}")
    return words[0], loop, noun, here


def main(argv: Sequence[str] | None = None, root: Path = ROOT, runner: Runner = run_step) -> int:
    """`feature.sh <app> [--loop [--here <why>]] [--drive <Noun>]`: 0 green · 1 red · 2 refused."""
    if piped():
        err("!! feature.sh refuses pipes — run it bare or redirect to a file.")
        return 2
    try:
        asked = parse(list(sys.argv[1:] if argv is None else argv))
    except ValueError as refused:
        err(f"!! {refused}")
        sys.stderr.write(USAGE)
        return 2
    if asked is None:
        sys.stdout.write(USAGE)
        return 0
    app, loop, noun, here = asked
    if not (root / "apps" / app / "apps.py").is_file():
        err(f"!! apps/{app} is no app on this tree — `manage.py newapp {app}` makes one.")
        return 2
    return road(root, app, loop, noun, runner, here)


if __name__ == "__main__":
    raise SystemExit(main())
