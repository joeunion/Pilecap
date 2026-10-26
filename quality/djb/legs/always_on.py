"""The loop-only `always-on` leg: the full-only members a loop affords, each consulted first."""

# does-not-cover: a product's legs drawer — the registry refuses a tree carrying one.
# does-not-cover: the loop's walls table rows (`loop_walls_note`) — the `--loop` mode prints them.
# does-not-cover: a race between two parallel drives on one tree — the `# serial:` arm only.

from __future__ import annotations

import itertools
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook, tool_said
from quality.djb import hold, ledger, scope
from quality.djb import registry as R
from quality.djb.legs import selftest
from quality.djb.legs._run import checkout_python, say
from quality.djb.registry import Ctx, Leg

#: The measured half's ceiling in seconds; a member under it joins every loop.
FLOOR = 10
#: The drive runner every queued drive goes through, and the harness's own two modules first.
RUNNER = "quality/tests/test_drives.py"
HARNESS = ("quality/tests/test_harness.py", "quality/tests/test_fixtures.py")
#: The platform's suite, and a product's own gate tests beside it (the one half a product runs).
PLATFORM_TESTS, PRODUCT_TESTS = "quality/tests/", "quality/local/tests/"
#: The platform's drive homes (`_HOMES`); a product's own drives live anywhere else.
PLATFORM_DRIVES = ("scripts/tests/", "deploy/tests/")
#: The line a product tree's loop prints for the platform members it left out; said, never red.
ON_A_PRODUCT = (
    "loop: a product tree — {n} platform test module(s) and {m} platform drive(s) not collected:"
    " a product never pays for the platform's tests"
)
#: The tier the loop never runs: a gate test marked `full_gate` is the gate-tests leg's alone.
LOOP_DESELECT = ("-m", "not full_gate")
PYTEST = (
    "-m",
    "pytest",
    "-p",
    "no:django",
    "-p",
    "no:randomly",
    "-p",
    "no:cacheprovider",
    "-W",
    "ignore::pytest.PytestConfigWarning",
    "-q",
)
ARGV = (("<checkout python>", *PYTEST),)
#: Where a drive keeps its `# serial:` line: within its first 60 lines.
SERIAL_LINES = 60
_HOMES = re.compile(r"^(?:scripts|deploy)/tests/test_[^/]*\.sh$")
_DRIVES_MARKER = re.compile(r"^#[ \t]*drives:")
_SOURCED = re.compile(r"^[ \t]*\.[ \t]+(scripts/[A-Za-z0-9_./-]*\.sh)")


@dataclass
class Member:
    """One selected member: its kind, name, the suffix its lines carry and its drive file."""

    kind: str
    name: str
    suffix: str = ""
    path: Path | None = None
    key: selftest.Key = field(default_factory=selftest.Key)


@dataclass
class Tally:
    """Every member's verdict, the member wall and the fence findings."""

    green: int = 0
    red: list[str] = field(default_factory=list)
    cannot: list[str] = field(default_factory=list)
    wall: int = 0
    findings: int = 0


# --- the drive set and the walls table -----------------------------------------------------------


#: Where the census test modules live and their name shape; the marker is `scope.CENSUS_MARKER`.
CENSUS_HOME = ("apps", "test_*.py")


def census_population(root: Path) -> list[str]:
    """Every test module under `apps/` carrying the census marker: always-on at every scope."""
    return [path for path, _ in scope.declared_censuses(root, *CENSUS_HOME)]


def census_line(population: Sequence[str]) -> str:
    """The floor's printed line over a derived population: `always-on: <n> census modules`."""
    return f"always-on: {len(population)} census modules"


def joined_line(joined: Sequence[str], population: Sequence[str]) -> str:
    """The scope's line: how many censuses joined, and how many populations did not move."""
    n, k = len(population), len(joined)
    return f"always-on: {k} of {n} census modules joined — {n - k} populations unmoved"


def drives(ctx: Ctx, table: R.Table | None) -> list[tuple[str, Path]]:
    """The drives the leg may run: the planted set under its env, else the selftest unit's."""
    scratch = ctx.env.get("DJB_SELFTEST_DRIVES_DIR")
    if scratch:
        home = Path(scratch) if Path(scratch).is_absolute() else ctx.root / scratch
        return [(p.stem[len("test_") :], p) for p in sorted(home.glob("test_*.sh")) if p.is_file()]
    assert table is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    return selftest.drives(ctx, table)


@dataclass
class Walls:
    """The walls table as this leg reads it: its label, stamp, machine and member seconds."""

    label: str
    at: str
    machine: str
    seconds: dict[str, int]


def walls(ctx: Ctx) -> Walls | None:
    """The durations file named by `DJB_GATE_MEMBER_DURATIONS`, else this machine's view."""
    import json

    named = ctx.env.get("DJB_GATE_MEMBER_DURATIONS")
    if named:
        path = Path(named) if Path(named).is_absolute() else ctx.root / named
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if doc.get("schema") == "member-walls/2":
            return _view(ctx, [path], named)
        members = doc.get("members") or {}
        seconds = {k: int(v) for k, v in members.items() if isinstance(v, int)}
        if not seconds:
            return None
        return Walls(named, str(doc.get("measured_at", "")), str(doc.get("machine", "")), seconds)
    homes = [ctx.root / h for h in R.WALLS_HOMES]
    return _view(
        ctx, homes, f"{R.WALLS_HOMES[0]} (the {R._machine()} column, merged with any drawer)"
    )


def _view(ctx: Ctx, homes: Sequence[Path], label: str) -> Walls | None:
    machine = R._machine()
    seconds = ledger.durations(ctx.root, machine, homes=list(homes), say=lambda line: None)
    if not seconds:
        return None
    _, ats = ledger._walls_read(homes, lambda line: None)
    order = ledger._WALLS_ORDER.get(machine, [machine])
    at = next((ats[m] for m in order if m in ats), "")
    return Walls(label, at, machine, seconds)


def floor(ctx: Ctx) -> int:
    """The measured half's floor: `DJB_ALWAYS_ON_FLOOR` when a whole number, else `FLOOR`."""
    typed = ctx.env.get("DJB_ALWAYS_ON_FLOOR", "")
    return int(typed) if typed.isdigit() else FLOOR


def measured(
    ctx: Ctx,
    table: R.Table | None,
    names: Sequence[str],
    declared: Sequence[str],
) -> tuple[int, list[str], dict[str, int]]:
    """The members the walls table puts under the floor; `(2, …)` on a name nothing announces."""
    found = walls(ctx)
    if found is None:
        print("  always-on (measured): no durations file — the first --store-durations writes it")
        return 0, [], {}
    under = floor(ctx)
    print(
        f"  always-on (measured): {found.label} — measured_at {found.at or 'unstated'} on "
        f"{found.machine or 'an unstated machine'}, floor {under}s"
    )
    known = set(names)
    full_only: list[str] = []
    if table is not None:
        loop = {g.name for g in table.mode_legs("loop")}
        drive_set = set(names)
        for _, members in table.rows:
            for m in members:
                if m in drive_set:
                    continue
                known.add(m)
                if m not in loop:
                    full_only.append(m)
        known.add(R.ENGINE_MEMBER)
    for name in found.seconds:
        if name not in known:
            say(
                f"!! {found.label} records a member this gate does not have: '{name}'.",
                "   That file is a MEASUREMENT of this gate's own legs and drives, so a",
                "   name nothing announces is a typo or a member that was removed — and",
                "   either way some OTHER member is silently missing from the set.",
                "   Re-measure with ./scripts/check.sh --store-durations.",
            )
            return 2, [], found.seconds
    for name in full_only:
        secs = found.seconds.get(name)
        recorded = f" ({secs} s recorded)" if secs is not None else ""
        print(
            f"  always-on (measured): leg {name} stays full-only — its leg is not declared for "
            f"the loop mode, so this leg cannot call it{recorded}"
        )
    # The selftest unit's `network` need is one drive's advisory case, not every drive's.
    joins: list[str] = []
    for name in names:
        if name in declared:
            continue
        secs = found.seconds.get(name)
        if secs is None:
            print(
                f"  always-on (measured): {name} unmeasured — joins after the next "
                f"--store-durations"
            )
        elif secs >= under:
            print(f"  always-on (measured): {name} above the floor ({secs} s)")
        else:
            joins.append(name)
    if joins:
        print(f"  always-on (measured): joins this loop — {' '.join(joins)}")
    else:
        print(f"  always-on (measured): no member is under the {under}s floor")
    return 0, joins, found.seconds


# --- the touched half ---------------------------------------------------------------------------


def changed(ctx: Ctx) -> list[str]:
    """`DJB_ALWAYS_ON_CHANGED_FILES` when set (even empty), else the active rung's changed set."""
    if "DJB_ALWAYS_ON_CHANGED_FILES" in ctx.env:
        return ctx.env["DJB_ALWAYS_ON_CHANGED_FILES"].split()
    carried = ctx.env.get("DJB_LOOP_SCOPE_BASE") or None
    return scope.changed_files(ctx.root, None, carried).paths


def _tracked(ctx: Ctx, paths: Sequence[str]) -> list[str]:
    if not paths:
        return []
    done = subprocess.run(
        ["git", "ls-files", "--", *paths],
        cwd=ctx.root,
        env=dict(ctx.env),
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"git ls-files could not answer: {done.stderr.strip()}")
    return sorted(set(done.stdout.split()))


def marker_words(path: Path) -> list[str] | None:
    """The words of a drive's `# drives:` line in its first lines, or None when it has none."""
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            for _, line in enumerate(itertools.islice(lines, ledger.DRIVE_MARKER_LINES)):
                if _DRIVES_MARKER.match(line):
                    return line.split("drives:", 1)[1].split()
    except OSError:
        return None
    return None


def measured_entries(ctx: Ctx) -> list[ledger.Entry]:
    """The measured tree's listing (`MEASURED_START` when the mode handed one down)."""
    tree = ctx.env.get("MEASURED_START") or ledger.measured_tree(ctx.root)
    entries = ledger.listing(ctx.root, tree)
    if not entries:
        raise CouldNotLook(f"the measured tree {tree} lists no file")
    return entries


def covers(ctx: Ctx, path: Path, keys: Sequence[str]) -> list[str]:
    """The keys a drive's declared paths, its file and its preamble cover (`always_on__covers`)."""
    decls = marker_words(path) or []
    if {"scripts/check.sh", "scripts/", "scripts"} & set(decls):
        try:
            text = (ctx.root / R.GATE).read_text(encoding="utf-8", errors="replace")
            decls += sorted({m.group(1) for m in map(_SOURCED.match, text.splitlines()) if m})
        except OSError:
            pass
    rel = _rel(ctx, path)
    preamble = f"{rel.rsplit('/', 1)[0]}/drive_preamble.sh" if "/" in rel else "drive_preamble.sh"
    entries = [ledger.Entry("0", k) for k in keys]
    hit = {
        line.split(" ", 1)[1] for d in (*decls, rel, preamble) for line in ledger.expand(entries, d)
    }
    return sorted(hit)


def _rel(ctx: Ctx, path: Path) -> str:
    try:
        return path.relative_to(ctx.root).as_posix()
    except ValueError:
        return str(path)


def touched(
    ctx: Ctx,
    rows: Sequence[tuple[str, Path]],
    paths: Sequence[str],
    declared: Sequence[str],
    joined: Sequence[str],
) -> list[str]:
    """The drives this run's changes reach, each said; `CouldNotLook` when underivable."""
    shell = _tracked(ctx, [p for p in paths if p.endswith(".sh")])
    named_words = {w for _, path in rows for w in (marker_words(path) or [])}
    named = _tracked(ctx, [p for p in paths if p and not p.endswith(".sh") and p in named_words])
    judge: list[str] = []
    quality = [p for p in paths if p.startswith("quality/")]
    if quality:
        judged = {e.path for e in ledger.judge_paths(ctx.root, measured_entries(ctx))}
        judge = sorted({p for p in quality if p in judged}, key=quality.index)
    keys = sorted(set(shell) | set(named) | set(judge))
    if not keys:
        return []
    lines: list[tuple[str, str]] = []
    for name, path in rows:
        if path.is_file():
            lines += [(name, p) for p in covers(ctx, path, keys)]
    if judge:
        lines += [(name, p) for name, _ in rows for p in judge]
        lines = list(dict.fromkeys(lines))
    for p in keys:
        print(f"  always-on (touched): {sum(1 for _, q in lines if q == p)} drives cover {p}")
    chosen: list[str] = []
    for name in dict.fromkeys(n for n, _ in lines):
        covered = [p for n, p in lines if n == name]
        more = f" (and {len(covered) - 1} more)" if len(covered) > 1 else ""
        head = f"  always-on (touched): {name}: touched: {covered[0]}{more}"
        if name in declared:
            print(f"{head} — already selected (declared); runs once there")
        elif name in joined:
            print(f"{head} — already selected (measured); runs once there")
        else:
            print(head)
            chosen.append(name)
    return chosen


def fence_finding(ctx: Ctx, name: str, path: Path) -> int:
    """1 when the drive's fence in `check.sh` invokes it with arguments or never bare; said."""
    fence = ctx.env.get("DJB_ALWAYS_ON_FENCE_FILE") or R.GATE
    try:
        text = (ctx.root / fence).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    rel = _rel(ctx, path)
    odd: list[str] = []
    on = fenced = bare = False
    for raw in text.splitlines():
        if raw == f"# >>> drive: {name} >>>":
            on = fenced = True
            continue
        if raw == f"# <<< drive: {name} <<<":
            on = False
            continue
        if not on:
            continue
        line = raw.lstrip(" \t")
        for p in (f"./{rel}", rel):
            if line.startswith(p):
                rest = line[len(p) :]
                if rest == "":
                    bare = True
                elif rest[0] in " \t":
                    odd.append(line)
                break
    if fenced and not bare:
        odd.append("(no bare invocation in the fence)")
    for one in odd:
        print(
            f"  touched {name}: FINDING — its fence in {fence} invokes '{one}', which is not the "
            f"bare self-case; the leg runs the self-case bare (the fence is the defect)"
        )
    return 1 if odd else 0


# --- running the members -------------------------------------------------------------------------


def keyed(ctx: Ctx, members: Sequence[Member]) -> tuple[str, str]:
    """Key every member against the measured tree in one call; `(tree, "")` or `("", why)`."""
    if ctx.env.get("DJB_SELFTEST_NO_REUSE") or not members:
        return "", ""
    tree, keys = selftest.keys(ctx, [(m.name, m.path) for m in members if m.path is not None])
    if not tree:
        return "", "the measured tree could not be read"
    for m in members:
        m.key = keys.get(m.name, selftest.Key(error="no key was answered"))
    return tree, ""


def consult(ctx: Ctx, m: Member, why: str, tally: Tally) -> bool:
    """Whether `m` still runs: a banked key is counted green and said, an unkeyed one is said."""
    if ctx.env.get("DJB_SELFTEST_NO_REUSE"):
        return True
    if why:
        print(f"  {m.kind} {m.name}: not consulted — {why}; running it{m.suffix}")
        return True
    if m.key.error:
        print(f"  {m.kind} {m.name}: not consulted — {m.key.error}; running it{m.suffix}")
        return True
    if m.key.banked:
        stamp = (m.key.banked.split() + [""] * 4)[3]
        print(f"  {m.kind} {m.name}: REUSED from {m.key.key} (banked {stamp}){m.suffix}")
        tally.green += 1
        return False
    return True


def settle(ctx: Ctx, tally: Tally, tree: str, m: Member, rc: int, took: int, out: str) -> None:
    """Count one member's verdict and print it; a green one with a key is banked."""
    tally.wall += took
    print(f"  {m.kind} {m.name}: exit {rc} ({took}s){m.suffix}")
    if rc == 0:
        tally.green += 1
        if m.key.key and tree and not ctx.env.get("DJB_GATE_LEGS_DRY"):
            env = {"K": m.key.key, "N": m.name, "T": str(took), "TREE": tree, "P": m.key.parts}
            selftest.bash(ctx, selftest.RECORD, env)
        return
    print("".join(f"      | {line}\n" for line in out.splitlines()), end="")
    (tally.cannot if rc == 2 else tally.red).append(m.name)


def run_file(ctx: Ctx, path: Path) -> tuple[int, int, str]:
    """One member file run alone with both streams captured: its exit, seconds and output."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as out:
        try:
            rc = subprocess.run(
                [str(path)], cwd=ctx.root, env=dict(ctx.env), stdout=out, stderr=subprocess.STDOUT
            ).returncode
        except OSError as exc:
            out.write(f"{path} could not be started: {exc}\n".encode())
            rc = 2
        out.seek(0)
        text = out.read().decode(errors="replace")
    return rc, int(time.monotonic() - started), text


def is_serial(path: Path) -> bool:
    """Whether the drive declares `# serial:` in its first lines (the serial arm's members)."""
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            return any(
                line.startswith("# serial:")
                for _, line in enumerate(itertools.islice(lines, SERIAL_LINES))
            )
    except OSError:
        return False


def box_workers(ctx: Ctx) -> int:
    """The drives session's `-n`: half this box's cores on a verifier box, else 1."""
    marker = ctx.env.get("DJB_GATE_BOX_MARKER", "/etc/djb/image-id")
    if not Path(marker).exists():
        return 1
    return max(1, hold.cores() // 2)


def session(ctx: Ctx, log: Path, results: Path, workers: int, argv: Sequence[str]) -> int:
    """One pytest session over `argv` with its verdicts in `results`; its exit, 2 if unstarted."""
    py = checkout_python(ctx.root)
    if py is None:
        log.write_text("no .venv/bin/python in this checkout\n")
        return 2
    n = workers if workers > 1 else 0
    with log.open("wb") as out:
        cmd = [str(py), *PYTEST, "-n", str(n), "--drives-results", str(results), *argv]
        return subprocess.run(
            cmd, cwd=ctx.root, env=dict(ctx.env), stdout=out, stderr=subprocess.STDOUT
        ).returncode


def doubt(results: Path, name: str, rc: int, names: Sequence[str]) -> str:
    """Why a session's exit says worse than its drives do, or empty when it does not."""
    if rc == 0:
        return ""
    worst = 0
    for n in names:
        done = results / f"{n}.done"
        if done.is_file() and done.stat().st_size:
            word = done.read_text().split()[:1]
            worst = max(worst, int(word[0])) if word and word[0].isdigit() else worst
    outside = results / f"outside.{name}"
    if outside.is_file() and outside.stat().st_size:
        lines = sorted(set(outside.read_text().splitlines()))
        return (
            f"the {name} session exited {rc} with a failed teardown no drive owns: "
            f"{';'.join(lines)};"
        )
    if rc > worst:
        return f"the {name} session exited {rc} and no drive in it says worse than {worst}"
    return ""


def queue_run(
    ctx: Ctx,
    tally: Tally,
    tree: str,
    queue: Sequence[Member],
    seconds: Mapping[str, int],
    gate_tests: Sequence[str] = (),
) -> None:
    """The harness and the touched gate tests, one parallel drives session, the serial arm."""
    results = Path(tempfile.mkdtemp(prefix="djb-always-on-drives."))
    try:
        drives_ = [m for m in queue if m.path is not None and _HOMES.match(_rel(ctx, m.path))]
        modules = list(dict.fromkeys((*HARNESS, *gate_tests))) if drives_ or gate_tests else []
        try:
            modules, queue = collectable(ctx, modules, queue)
            gate_tests = [m for m in gate_tests if m in modules]
        except (CouldNotLook, OSError) as exc:
            say(f"!! always-on: this tree's drawer could not be read — {exc}")
            tally.cannot.append("drawer")
            modules, gate_tests, queue = [], [], []
        drives_ = [m for m in drives_ if m in queue]
        serial = [m for m in drives_ if m.path is not None and is_serial(m.path)]
        parallel = [m for m in drives_ if m not in serial]
        node = f"{RUNNER}::test_drive[{{}}]"
        doubts = {"drives": "", "serial": ""}
        workers = min(box_workers(ctx), len(parallel))
        if modules:
            if gate_tests:
                print(f"  gate tests (touched): {' '.join(gate_tests)}")
            started = time.monotonic()
            rc = session(ctx, results / "harness.log", results, workers, [*modules, *LOOP_DESELECT])
            (results / "outside.lines").unlink(missing_ok=True)
            print(f"  harness quality/tests: exit {rc} ({int(time.monotonic() - started)}s)")
            if rc:
                text = (results / "harness.log").read_text(errors="replace")
                print("".join(f"      | {line}\n" for line in text.splitlines()), end="")
                (tally.red if rc == 1 else tally.cannot).append("quality-tests")
        if drives_:
            print(
                f"  always-on (drives): {len(parallel)} under pytest-xdist -n {workers}, longest "
                f"recorded first; {len(serial)} serial after",
                flush=True,
            )
            order = sorted(parallel, key=lambda m: (-seconds.get(m.name, 0), node.format(m.name)))
            for arm, members, n, extra in (
                ("drives", order, workers, ("--dist", "worksteal")),
                ("serial", serial, 1, ()),
            ):
                if not members:
                    continue
                argv = [*extra, *(node.format(m.name) for m in members)]
                rc = session(ctx, results / f"{arm}.log", results, n, argv)
                if (results / "outside.lines").exists():
                    (results / "outside.lines").rename(results / f"outside.{arm}")
                doubts[arm] = doubt(results, arm, rc, [m.name for m in members])
            for arm, said in doubts.items():
                if not said:
                    continue
                print(f"  always-on (drives): could not look — {said}")
                log = results / f"{arm}.log"
                text = log.read_text(errors="replace") if log.exists() else ""
                for line in text.splitlines():
                    if "COULD NOT LOOK" in line:
                        print(f"      | {line}")
                tally.cannot.append(f"{arm}-session")
            sys.stdout.flush()
        for m in queue:
            out = results / f"{m.name}.out"
            done = results / f"{m.name}.done"
            text = out.read_text(errors="replace") if out.exists() else ""
            if done.is_file() and done.stat().st_size:
                words = done.read_text().split()
                rc, took = int(words[0]), int(words[1]) if len(words) > 1 else 0
                said = doubts["serial" if m in serial else "drives"]
                if rc == 0 and said:
                    rc = 2
                    text += f"its own verdict was green, and {said}\n"
            elif m in drives_:
                rc, took = 2, 0
                logs = "".join(
                    (results / f"{a}.log").read_text(errors="replace")
                    for a in ("drives", "serial")
                    if (results / f"{a}.log").exists()
                )
                text += f"the drives session left no verdict for {m.name}; its log:\n{logs}"
            else:
                assert m.path is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
                rc, took, text = run_file(ctx, m.path)
            settle(ctx, tally, tree, m, rc, took, text)
    finally:
        shutil.rmtree(results, ignore_errors=True)


def platform_tests(modules: Sequence[str]) -> list[str]:
    """The platform's own gate test modules among `modules`; a product's drawer tests are not."""
    return [m for m in modules if m.startswith(PLATFORM_TESTS) and not m.startswith(PRODUCT_TESTS)]


def collectable(
    ctx: Ctx, modules: Sequence[str], queue: Sequence[Member] = ()
) -> tuple[list[str], list[Member]]:
    """The modules and members a product tree may run, the platform's left out and counted."""
    from quality.djb.legs import gate_tests

    if not (modules or queue) or not gate_tests.product_of(ctx.root):
        return list(modules), list(queue)
    left = platform_tests(modules)
    drives_ = [
        m for m in queue if m.path is not None and _rel(ctx, m.path).startswith(PLATFORM_DRIVES)
    ]
    if left or drives_:
        print(f"  {ON_A_PRODUCT.format(n=len(left), m=len(drives_))}", flush=True)
    return [m for m in modules if m not in left], [m for m in queue if m not in drives_]


# --- the leg -------------------------------------------------------------------------------------


def compose(tally: Tally, started: float) -> int:
    """The closing count and the leg's one verdict: 2 outranks 1 outranks 0."""
    print(
        f"  always-on: {tally.green} member(s) green · {len(tally.red)} red · "
        f"{len(tally.cannot)} could-not-look ({tally.wall}s of member wall, "
        f"{int(time.monotonic() - started)}s of leg)"
    )
    if tally.findings:
        print(
            f"  always-on: {tally.findings} fence FINDING(s) above — a fence that does not invoke "
            f"its drive's bare self-case"
        )
    sys.stdout.flush()
    if tally.cannot:
        say(f"!! COULD NOT LOOK: {' '.join(tally.cannot)}")
        if tally.red:
            say(f"!! and RED: {' '.join(tally.red)}")
        say(
            "   2 outranks 1: a member that could not run its cases has not cleared",
            "   them. This is the SAME member the bank runs — meeting it here is the",
            "   whole point of the leg; meeting it at the bank costs a merge.",
        )
        return 2
    if tally.red:
        say(
            f"!! RED: {' '.join(tally.red)}",
            "   A full-only member is red. Before this leg existed that red waited for",
            "   the next bank — seven of nine failed banks in one cycle were exactly",
            "   that. Read the first name first.",
        )
        return 1
    return 0


def leg(ctx: Ctx, paths: Sequence[str] | None = None) -> int:
    """Declared, measured and touched members, each consulted, then run; 0/1/2 composed."""
    started = time.monotonic()
    tally = Tally()
    scratch = bool(ctx.env.get("DJB_SELFTEST_DRIVES_DIR"))
    try:
        table = None if scratch else R.load(ctx.root)
        rows = drives(ctx, table)
    except (CouldNotLook, R.RegistryError) as exc:
        say(f"!! {exc}", "!! the always-on leg could not derive the drive set it may run.")
        return 2
    names = [n for n, _ in rows]
    by_name = dict(rows)
    try:
        census = scope.declared_censuses(
            ctx.root, ctx.env.get("DJB_SELFTEST_DRIVES_DIR") or "scripts/tests", "test_*.sh"
        )
    except CouldNotLook as exc:
        say(
            f"!! {exc}",
            "!! the always-on leg COULD NOT READ the drives that declare themselves",
            "   cross-app — see above. Nothing was judged: a drive this could not read",
            "   is one the leg would skip as if it had declared nothing.",
            f"   cause: {exc}",
        )
        return 2
    declared = [Path(p).name[len("test_") : -len(".sh")] for p, _ in census]
    if not scratch:
        try:
            print(
                f"  {census_line(census_population(ctx.root))} — each joins the pytest scope"
                " its population moves",
                flush=True,
            )
        except CouldNotLook as exc:
            say(f"!! {exc}", "!! the always-on leg could not derive the census modules.")
            return 2
    if not census:
        print("  always-on (declared): no drive declares itself cross-app")
    rc, joined, seconds = measured(ctx, table, names, declared)
    if rc:
        return rc
    try:
        paths = changed(ctx) if paths is None else paths
        picked = touched(ctx, rows, paths, declared, joined)
        gate_tests = touched_tests(ctx, paths)
    except (CouldNotLook, ledger.Mismatch, subprocess.CalledProcessError, OSError) as exc:
        say(
            f"!! {exc}{tool_said(getattr(exc, 'stderr', None))}",
            "!! the always-on leg COULD NOT DERIVE the drives this run's shell changes reach.",
            "   Nothing was judged: an underived selection is not an empty one.",
        )
        return 2
    print(
        f"  always-on: selected — declared {len(census)} · measured {len(joined)} · "
        f"touched {len(picked)}",
        flush=True,
    )
    members = [
        Member("census", Path(p).name[len("test_") : -len(".sh")], f" — {reason}")
        for p, reason in census
    ]
    members += [Member("member", n) for n in joined]
    members += [Member("touched", n) for n in picked]
    for m in members:
        m.path = _drive_file(ctx, by_name, m.name)
    tree, why = keyed(ctx, [m for m in members if m.path is not None and m.path.is_file()])
    queue: list[Member] = []
    for m in members:
        assert m.path is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
        if m.kind == "touched":
            tally.findings += fence_finding(ctx, m.name, m.path)
        if not m.path.is_file():
            print(
                f"  {m.kind} {m.name}: could not look — {_rel(ctx, m.path)} is not in this "
                f"tree{m.suffix}"
            )
            tally.cannot.append(m.name)
        elif consult(ctx, m, why, tally):
            if scratch:
                rc, took, text = run_file(ctx, m.path)
                settle(ctx, tally, tree, m, rc, took, text)
            else:
                queue.append(m)
    if queue or gate_tests:
        try:
            queue_run(ctx, tally, tree, queue, seconds, gate_tests)
        except OSError as exc:
            say(
                f"!! {exc}",
                "!! the always-on leg could not keep its results — nothing queued was judged.",
            )
            return 2
    return compose(tally, started)


def touched_tests(ctx: Ctx, paths: Sequence[str]) -> list[str]:
    """The gate's own test modules the change selects (`GATE_LOOP_TOUCHED`), the runner out."""
    if "GATE_LOOP_TOUCHED" in ctx.env:
        found = ctx.env["GATE_LOOP_TOUCHED"].split()
    elif ctx.env.get("DJB_SELFTEST_DRIVES_DIR"):
        found = []
    else:
        carried = ctx.env.get("DJB_LOOP_SCOPE_BASE") or None
        rows = any(p in scope.ROW_DERIVED for p in paths)
        fork = scope.changed_files(ctx.root, None, carried).base if rows else ""
        found = scope.touched(ctx.root, scope.charged(ctx.root, paths, fork))
    return [m for m in found if m != RUNNER]


def _drive_file(ctx: Ctx, by_name: Mapping[str, Path], name: str) -> Path:
    scratch = ctx.env.get("DJB_SELFTEST_DRIVES_DIR")
    if scratch:
        home = Path(scratch) if Path(scratch).is_absolute() else ctx.root / scratch
        return home / f"test_{name}.sh"
    return by_name.get(name) or ctx.root / "scripts" / "tests" / f"test_{name}.sh"


def run(ctx: Ctx) -> int:
    """The leg over the active rung's changed files (`leg`)."""
    return leg(ctx)


LEG = Leg(
    "always-on",
    "-",
    "the full-only members the loop can afford — drives declaring themselves cross-app (always, "
    "whatever the price), every member the committed measurement puts under the floor, and every "
    "drive whose # drives: line covers a shell file the active rung changed; each consulted "
    "against its banked drive verdict first",
    run,
    None,
    frozenset({"loop"}),
    ARGV,
)
