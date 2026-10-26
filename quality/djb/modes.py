"""The gate's door: one argv parsed, refused or run — the full gate, `--leg`, `--pr`, the rest."""

# Invariant: a run that is not the full gate's whole table banks nothing (`registry` + `ledger`).
# does-not-cover: `--loop` — `quality/djb/loop.py` runs it.

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook, exit_could_not_look
from quality.djb import cli, drawer, gate_args, hold, ledger
from quality.djb import env as environment
from quality.djb import registry as R
from quality.djb.gate_args import Refusal, Request, Sanctioned
from quality.djb.legs import pytest_x2

#: Legs whose body honours `DJB_GATE_LEGS_DRY` itself: the selftest leg announces its drives.
DRY_AWARE = frozenset({"selftest"})
#: The modes a pipe may read (GP:88; `ci.yml` reads the listing); every other mode refuses one.
PIPE_READABLE = frozenset({"--list-legs", "--census"})
#: The modes that bank nothing whatever their legs answer (`ledger.NO_BANK_CALLERS`).
NO_BANK = {"pr": "--pr", "leg": "--leg", "store-durations": "--store-durations"}


def _say(*lines: str) -> None:
    for line in lines:
        print(line, flush=True)


def _err(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr, flush=True)


@dataclass
class Clock:
    """One run's legs in order: who ran, how long each took, and which one is running now."""

    t0: float = field(default_factory=time.monotonic)
    current: str = ""
    seconds: dict[str, int] = field(default_factory=dict)

    def wall(self) -> int:
        """Seconds since the run began."""
        return int(time.monotonic() - self.t0)


def run_members(table: R.Table, members: Sequence[str], ctx: R.Ctx, clock: Clock) -> int:
    """Each member in order, a shell-carried one exit 2, 2 > 1 > 0; `loop` runs past a red leg."""
    bodies = {g.name: g for g in table.legs}
    drives = set(drive_members(table))
    claimed = {c for g in table.legs for c in g.claims}
    local = [m for m in members if m in {g.name for g in table.local}]
    reds: list[tuple[str, int]] = []
    rc = _members(table, members, ctx, clock, bodies, drives, claimed, local, reds)
    if rc or not reds:
        return rc
    _say(f"- every red leg: {' · '.join(f'{name} exit {code}' for name, code in reds)}")
    return max(code for _, code in reds)


def _members(
    table: R.Table,
    members: Sequence[str],
    ctx: R.Ctx,
    clock: Clock,
    bodies: dict[str, R.Leg],
    drives: set[str],
    claimed: set[str],
    local: list[str],
    reds: list[tuple[str, int]],
) -> int:
    """`run_members`' walk: a red stops it, except under `loop`, which collects it in `reds`."""
    keep_going = ctx.mode == "loop"
    worst = 0
    for name in members:
        if name in drives or name in claimed or name in local[1:]:
            continue
        dry = ctx.env.get("DJB_GATE_LEGS_DRY")
        if local and name == local[0]:
            _say(
                f"- local-legs: the product's own legs ({', '.join(local)}) — every tier, every leg"
            )
            clock.current = "local-legs"
            t0 = time.monotonic()
            if dry:
                _say("  leg: local-legs (DJB_GATE_LEGS_DRY — announced, body not run)")
            rc = 0 if dry else drawer.run(table, "full", ctx.env, narrowed=False, only=local)
            clock.seconds["local-legs"] = int(time.monotonic() - t0)
            if rc and keep_going:
                reds.append(("local-legs", rc if rc in (1, 2) else 2))
            elif rc:
                return rc
            continue
        leg = bodies.get(name)
        if (leg is None or leg.body is None) and dry:
            _say(f"- {name}", f"  leg: {name} (DJB_GATE_LEGS_DRY — shell-carried, body not run)")
            continue
        if leg is None or leg.body is None:
            _err(
                f"!! leg '{name}' has no Python body under {R.LEGS_PACKAGE} — this door cannot"
                " run it, and a gate that skipped it would vouch for less than it says.",
            )
            return 2
        one_pass = name == pytest_x2.LEG.name and ctx.env.get("GATE_PASSES") == "1"
        _say(f"- {pytest_x2.BANNER_ONE_PASS if one_pass else leg.banner}")
        clock.current = name
        t0 = time.monotonic()
        if dry:
            _say(f"  leg: {name} (DJB_GATE_LEGS_DRY — announced, body not run)")
        rc = leg.body(ctx) if not dry or name in DRY_AWARE else 0
        took = int(time.monotonic() - t0)
        clock.seconds[name] = took
        _say(f"  ({name}: {took}s)")
        if rc and keep_going:
            reds.append((name, rc if rc in (1, 2) else 2))
            continue
        if rc:
            return rc if rc in (1, 2) else 2
        worst = max(worst, rc)
    clock.current = ""
    return worst


def drive_members(table: R.Table) -> list[str]:
    """The selftest unit's members that are drives, not legs: the selftest leg runs those."""
    legs = {g.name for g in table.legs}
    try:
        members = table.unit("selftest")[1]
    except R.RegistryError:
        return []
    return [m for m in members if m not in legs]


def pr_scope(root: Path, base: str) -> tuple[str, str]:
    """`--pr`'s pytest arguments over `base...HEAD` and the counts directory they write into."""
    from quality.djb import scope

    _say(f"- --pr scope: {base}...HEAD, through the one changed-file derivation")
    try:
        derived = scope.derive(root, base_ref=base)
    except CouldNotLook as exc:
        _err(
            "!! --pr COULD NOT DERIVE THE IMPACT MAP — see above.",
            f"   cause: {exc}",
            "   The two pytest passes would have to be pointed at something, and an",
            "   underived scope is not an empty one: pointing them at the always-on set",
            "   would run LESS than this gate claims, silently.",
            "   Nothing was judged: no lease was taken, no slot, no leg ran a test.",
        )
        raise SystemExit(2) from exc
    _say(
        f"  scope   basis: {base}...HEAD",
        f"          {derived.basis}",
        f"  scope   touched: {' '.join(derived.touched) or '-'}",
        f"  scope   tests-only: {' '.join(derived.tests_only) or '-'}",
        f"  scope   closure: {' '.join(derived.widened) or '-'}",
        f"  scope   own: {' '.join(derived.own) or '-'}",
        "  scope   tier: all — the organ tier is NOT applied under --pr; every test in",
        "          the scope runs, organ-reaching or not, exactly as it does at push",
        f"  scope   rule: {derived.reason}",
        *(f"  note:   {line}" for line in derived.notes),
    )
    args = scope.pytest_args(derived)
    if not args:
        _say(
            "  scope   narrows NOTHING — both passes run the whole suite, as a bare full",
            "          gate does. An empty selection is printed, never silent.",
        )
        return "", ""
    if derived.product is not None:
        return " ".join(args), ""
    counts = tempfile.mkdtemp(prefix="djb-pr-counts.")
    return " ".join([*args, f"--djb-scope-counts={counts}"]), counts


def dirt(root: Path) -> list[str]:
    """The working tree's uncommitted paths, `git status --porcelain`'s lines."""
    done = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return [line for line in done.stdout.splitlines() if line.strip()]


def leg_env(req: Request, run: gate_args.UnitRun | None) -> dict[str, str]:
    """The `GATE_*` mode inputs a leg body reads (`pytest_x2.Run.of`, `selftest.shard`)."""
    out = {"GATE_BANK": "1" if req.bank else "", "GATE_PR": "1" if req.pr else ""}
    if run is not None:
        out["GATE_LEG_UNIT"] = run.unit
        out["GATE_PASSES"] = run.passes
        out["GATE_STORE_DURATIONS"] = "1" if req.store_durations else ""
        if run.k:
            out["GATE_SHARD_K"], out["GATE_SHARD_N"] = str(run.k), str(run.n)
    return out


def run_leg(root: Path, req: Request, table: R.Table) -> int:
    """One unit of the gate: no lease, no lock, no sanction, no verdict."""
    run = gate_args.check_unit(req, R.list_legs(table, ci=False))
    cli.refuse_if_locked(root)
    _say(*gate_args.unit_banner(req, run))
    extra = leg_env(req, run)
    counts = ""
    if req.pr:
        extra["GATE_PR_PYTEST_ARGS"], counts = pr_scope(root, req.pr_base)
        extra["GATE_PR_COUNTS_DIR"] = counts
        extra["GATE_PR_BASE"] = req.pr_base
    ctx = R.Ctx(root, "full", {**environment.environ(), **extra})
    clock = Clock()
    try:
        rc = run_members(table, run.members, ctx, clock)
    finally:
        if counts:
            shutil.rmtree(counts, ignore_errors=True)
    if rc:
        return rc
    tree = _measured(root) or "unreadable"
    shard = f" shard {req.shard}" if req.shard else ""
    _say(
        f"ok: all checks passed ({clock.wall()}s)",
        f"  ...of ONE UNIT: {run.unit}{shard}. The other units of this",
        "  gate were neither announced nor run — ./scripts/check.sh --list-legs names them.",
        f"  no verdict recorded — --leg {run.unit}{' --shard ' + req.shard if req.shard else ''}:"
        " one unit of the gate",
        f"  is a targeted drive and vouches for no tree. The tree it ran on was {tree}.",
    )
    return 0


def _measured(root: Path) -> str:
    try:
        return ledger.measured_tree(root)
    except ledger.Mismatch:
        return ""


def caller_of(req: Request) -> str:
    """The run's caller kind: a no-bank mode's own word, else `DJB_GATE_CALLER`'s."""
    if req.pr:
        return "pr"
    if req.store_members:
        return "store-durations"
    return ledger.caller_kind(environment.read("DJB_GATE_CALLER"), lambda line: None)


def announce(root: Path, tree: str, who: Sanctioned) -> None:
    """The full gate's header: caller, sanction, the previous run on this tree, the last wall."""
    named = environment.read("DJB_GATE_CALLER") or ""
    if named in ledger.CALLER_KINDS:
        _say(f"- caller: {named} (DJB_GATE_CALLER)")
    else:
        _say(f"- caller: unstated (set DJB_GATE_CALLER to one of: {' '.join(ledger.CALLER_KINDS)})")
    _say(f"- sanction: {who.kind}:{who.who}:{who.why}")
    prior = ledger.run_lookup(root, tree) if tree else None
    if prior:
        _say(f"- the previous run on this tree ended: {prior}")
    wall = ledger.last_wall(root)
    if wall is not None:
        _say(f"- full gate — the last green run here took {wall // 60}m{wall % 60}s")


def member_walls(sink: Path) -> dict[str, int]:
    """The drives' seconds the selftest leg appended as `member-walls/1` rows."""
    out: dict[str, int] = {}
    try:
        lines = sink.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        cols = line.split("\t")
        if len(cols) >= 4 and cols[0] == "member-walls/1" and cols[3].isdigit():
            out[cols[1]] = int(cols[3])
    return out


def store(root: Path, clock: Clock, sink: Path, tree: str) -> int:
    """`--store-durations`: this machine's column of the walls table rewritten; nothing banked."""
    home = Path(environment.read("DJB_GATE_MEMBER_DURATIONS") or R.WALLS_HOMES[0])
    home = home if home.is_absolute() else root / home
    seconds = {**clock.seconds, **member_walls(sink)}
    machine = R._machine()
    try:
        ledger.store_durations(home, machine, f"tree:{tree or 'unmeasured'}", seconds)
    except (ledger.Refused, OSError) as exc:
        _err(
            f"!! --store-durations: nothing was written to {home}.",
            f"   {exc}",
            "   The always-on set goes on deriving from whatever is committed there.",
        )
        return 2
    _say(
        f"  --store-durations: {home} — the {machine} column REWRITTEN from this run's own clock",
        f"                     ({len(seconds)} member(s), measured_at {tree or 'unmeasured'})",
        "  It is a MEASUREMENT and not a verdict: nothing was banked, and the file",
        "  is committed by whoever ran this, as the measurement it is.",
    )
    return 0


def settle(
    root: Path, req: Request, who: Sanctioned, caller: str, clock: Clock, start: str, sink: Path
) -> int:
    """After a green run: store, note or bank — exactly one, by the mode that ran."""
    end = _measured(root)
    if req.store_members:
        return store(root, clock, sink, start)
    if req.pr:
        _say(
            "  no verdict recorded — narrowed run (--pr banks nothing: no full verdict row,",
            f"  no partition row). The tree it measured was {end}.",
        )
        state = "narrowed-run"
    elif environment.read("DJB_GATE_LEGS_DRY"):
        _say("  no verdict recorded — DJB_GATE_LEGS_DRY: every leg was announced and none ran")
        return 0
    elif not start or not end:
        _say("  no verdict recorded — the tree could not be measured")
        state = "unmeasured"
    elif start != end:
        _say(
            "  no verdict recorded — the tree changed while the gate ran",
            f"    started on {start}",
            f"    ended on   {end}",
        )
        state = "tree-changed"
    else:
        legs = ",".join(m for _, members in table_of(root).rows for m in members)
        try:
            ledger.record_full(
                root,
                tree=start,
                legs=legs,
                caller=caller,
                sanction=ledger.Sanction(who.kind, who.who, who.why),
                took=clock.seconds.get("pytest-x2", 0),
                wall=clock.wall(),
            )
        except (ledger.Refused, OSError) as exc:
            _say(f"  no verdict recorded — the ledger could not be written ({exc})")
            state = "ledger-unwritable"
        else:
            _say(f"  verdict recorded for tree {start}")
            return 0
    _note(root, start or end, state, caller, clock)
    return 0


def table_of(root: Path) -> R.Table:
    """The registry's table; its refusals are exit 2 (`cli.table`)."""
    return cli.table(root)


def _note(root: Path, tree: str, state: str, caller: str, clock: Clock) -> None:
    try:
        ledger.run_note(root, tree, state, caller=caller, wall=clock.wall())
    except (ledger.Refused, OSError) as exc:
        _err(f"run log could not be written: {state} is unrecorded ({exc})")


def run_full(root: Path, req: Request) -> int:
    """The whole table under the lease and the lock, banked by `ledger.record_full` when green."""
    env = environment.environ()
    gate_args.sanction_shape(env)
    who = gate_args.sanction(root, req, env)
    assert who is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    if req.bank and not env.get("DJB_GATE_CALLER"):
        environment.export("DJB_GATE_CALLER", "pm-bank")
    caller = caller_of(req)
    extra = leg_env(req, None)
    counts = ""
    if req.pr:
        extra["GATE_PR_PYTEST_ARGS"], counts = pr_scope(root, req.pr_base)
        extra["GATE_PR_COUNTS_DIR"] = counts
        extra["GATE_PR_BASE"] = req.pr_base
    table = table_of(root)
    clock = Clock()
    lease = host = lock = None
    start = ""
    rc = 2
    sink = Path(tempfile.mkstemp(prefix="djb-member-walls.")[1])
    try:
        try:
            lease = hold.hold("lease", on_contention="wait")
            host = hold.hold(
                "host", on_contention="wait", mode="bank" if req.bank else "full", lease=lease
            )
        except hold.Refused:
            return 2
        lock = hold.hold("checkout", on_contention="refuse")
        start = _measured(root)
        announce(root, start, who)
        extra.update(
            GATE_SLOT_LEASE_FIRST="1",
            GATE_LEASE=str(lease.paths[0]) if lease and lease.paths else "",
            DJB_MEMBER_WALLS_OUT=str(sink),
        )
        ctx = R.Ctx(root, "full", {**environment.environ(), **extra})
        members = [m for _, ms in table.rows for m in ms]
        rc = run_members(table, members, ctx, clock)
        if rc == 0:
            _say(f"ok: all checks passed ({clock.wall()}s)")
            rc = settle(root, req, who, caller, clock, start, sink)
        else:
            word = "exit-2" if rc == 2 else "red"
            _note(root, start, f"{word}:{clock.current or 'before-first-leg'}", caller, clock)
        return rc
    except KeyboardInterrupt:
        _note(root, start, f"killed:{clock.current or 'before-first-leg'}", caller, clock)
        return 130
    finally:
        for taken in (lock, host, lease):
            if taken is not None:
                taken.release()
        if counts:
            shutil.rmtree(counts, ignore_errors=True)
        sink.unlink(missing_ok=True)


def run(argv: Sequence[str], root: Path = cli.ROOT) -> int:
    """`python -m quality.djb gate <argv>`: `check.sh`'s grammar, its refusals, then one mode."""
    args = list(argv)
    try:
        if not args or args[0] not in PIPE_READABLE:
            cli.refuse_if_piped(root)
        req = gate_args.parse(args)
        if req.list_legs:
            return cli.run_list_legs(root, ("--ci",) if req.list_ci else ())
        if req.census:
            return cli.run_census(root, ())
        if req.mode == "--fast":
            return cli.run_fast(root, ())
        if req.pr:
            gate_args.check_pr_base(root, req, dirt(root))
        if req.mode == "--leg":
            return run_leg(root, req, table_of(root))
        if req.mode == "--loop":
            from quality.djb import loop

            return loop.run(root, req)
        return run_full(root, req)
    except Refusal as refusal:
        _err(*refusal.lines)
        return refusal.code
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))


def main(argv: Sequence[str] | None = None) -> int:
    """The process entry: `gate` and its argv; any other first word is `cli`'s."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "gate":
        return run(args[1:])
    return cli.main(args)
