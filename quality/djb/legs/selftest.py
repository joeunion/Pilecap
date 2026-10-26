"""The `selftest` leg: the engine's own selftest, then every registered drive, composed once."""

# Invariant: nothing between members exits — `compose` is the leg's one verdict, 2 outranking 1.

from __future__ import annotations

import hashlib
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook, tool_said
from quality.djb import ledger, scope
from quality.djb import registry as R
from quality.djb.drive_table import DRIVES
from quality.djb.legs._run import LIBRARIES, say
from quality.djb.registry import Ctx, Leg

ENGINE = (("uv", "run", "python", "-m", "quality.gate", "--selftest"),)
#: The engine's own read set, the paths its member is keyed on (`selftest_engine_drive_file`).
INPUTS = ("uv", "run", "python", "-m", "quality.gate", "--selftest-inputs")
ARGV = (*ENGINE, INPUTS)
#: The line a product tree's run prints instead of the engine's selftest; satisfied, never 2.
ENGINE_ON_A_PRODUCT = (
    f"{R.ENGINE_MEMBER}: the platform's engine selftest — not a product's to pay for; the"
    " template's CI vouches for it (SDK program, 2026-10-11)"
)
#: The engine's synthesized drive file and the preamble `drive_key` wants beside it.
ENGINE_FILE = f"test_{R.ENGINE_MEMBER}.sh"
ENGINE_PREAMBLE = "# the engine drive file has no preamble to source — it is keyed, never run.\n"
#: Where a drive lives, in the order a name is looked for.
HOMES = ("scripts/tests", "deploy/tests")
#: The drive whose banked green is never reused for a sharded whole run (`SELFTEST_CONSULT_SKIP`).
WHOLE_RUN_DRIVE = "drive_preamble"
#: What the engine member holding piece 1 carries besides its rules (`--whole`).
WHOLE_CLAUSE = "; and the whole run's own parts (legs, seam, budget canary, censuses)"
#: A red member's FAILED lines kept for the closing list.
FAILED_CAP = 10
GENERIC_RED = "its own output above names the case that did not hold."
#: Each registered drive's red sentence, from the drive table; a scratch drive has the generic.
RED = {d.name: d.red for d in DRIVES}
_FAILED = re.compile(r"^[ \t]*FAILED[ \t]")
#: The engine's per-rule seconds line (`quality/engine/selftest.py`).
_RULE_WALL = re.compile(r"^  rule-wall (\S+): ([0-9]+(?:\.[0-9]+)?) s(?: |$)")

#: Keys every drive once against the measured tree: one `drive` row per name, or one `cannot`.
KEYS = r"""
tree="${MEASURED_START:-}"
[ -n "$tree" ] || tree=$(gate_measured_tree) || tree=""
[ -n "$tree" ] || { printf 'cannot\tthe measured tree could not be read\n'; exit 0; }
listing=$(mktemp "${TMPDIR:-/tmp}/djb-drive-listing.XXXXXX") || exit 2
if ! git ls-tree -r "$tree" >"$listing" 2>/dev/null || [ ! -s "$listing" ]; then
    rm -f "$listing"; printf 'cannot\tthe measured tree could not be read\n'; exit 0
fi
drive_machine_digest >/dev/null || {
    rm -f "$listing"; printf 'cannot\tthis machine could not be digested\n'; exit 0
}
drive_judge_digest "$listing" >/dev/null || {
    rm -f "$listing"
    printf "cannot\tthe drives' judge could not be read from the measured tree\n"
    exit 0
}
printf 'tree\t%s\t%s\n' "$tree" "$DRIVE_KEY_SCHEMA"
while IFS='	' read -r name file; do
    [ -n "$name" ] || continue
    keyout=$(drive_key "$file" "$tree" "$listing") || true
    row=""
    last=""
    case "$keyout" in
    "ok ${DRIVE_KEY_SCHEMA}:"*)
        row=$(drive_ledger_lookup "$(printf '%s\n' "$keyout" | awk '{print $2}')") || row=""
        [ -n "$row" ] || last=$(drive_ledger_last_for "$name") || last=""
        ;;
    esac
    printf 'drive\t%s\t%s\t%s\t%s\n' "$name" "$keyout" "$row" "$last"
done <"$DJB_SELFTEST_ROWS"
rm -f "$listing"
"""
#: Banks one green drive under its key (`drive_ledger_record`).
RECORD = 'drive_ledger_record "$K" "$N" "$T" "$TREE" "$P"'


#: The signals that end the leg with a killed member's output so far printed (SIGINT already does).
DELIVERED = (signal.SIGTERM, signal.SIGHUP)


class Killed(BaseException):
    """A delivered signal, raised so `run_member` prints the output so far before the leg dies."""

    def __init__(self, signum: int) -> None:
        super().__init__(signum)
        self.signum = signum


def _raise_killed(signum: int, _frame: object) -> None:
    raise Killed(signum)


@dataclass
class Key:
    """A drive's key against the measured tree, and what the ledger said about it."""

    key: str = ""
    parts: str = ""
    cites: str = ""
    machine: str = ""
    error: str = ""
    banked: str = ""
    last: str = ""


@dataclass
class Tally:
    """Every member's verdict, in run order, and the FAILED lines of each red one."""

    green: int = 0
    red: list[str] = field(default_factory=list)
    cannot: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    seconds: dict[str, int] = field(default_factory=dict)
    recorded: dict[str, int] | None = None


def drive_file(root: Path, name: str, scratch: str | None = None) -> Path | None:
    """The drive called `name`: under `scratch` when given, else the first home holding it."""
    homes = (scratch,) if scratch else HOMES
    for home in homes:
        path = root / home / f"test_{name}.sh"
        if path.is_file():
            return path
    return None


def not_run(root: Path, registered: set[str] | frozenset[str]) -> list[str]:
    """Every drive file in either home whose name no selftest member registers, sorted."""
    return sorted(
        f"{home}/{p.name}"
        for home in HOMES
        for p in (root / home).glob("test_*.sh")
        if p.is_file() and p.stem[len("test_") :] not in registered
    )


def say_not_run(root: Path, table: R.Table) -> None:
    """The `NOT RUN BY THIS LEG` block; silent when every drive on disk is a member."""
    unrun = not_run(root, set(table.unit("selftest")[1]))
    if not unrun:
        return
    print("", flush=True)
    print(
        f"  NOT RUN BY THIS LEG — {len(unrun)} drive file(s) registered in no selftest member:",
        *(f"    {path}" for path in unrun),
        "  A drive is registered by its row in quality/djb/drive_table.py; until it has one",
        "  it is run by hand, and test_selftest_compose.py's population test is red.",
        sep="\n",
        flush=True,
    )


def drives(ctx: Ctx, table: R.Table) -> list[tuple[str, Path]]:
    """The selftest unit's drives in the table's order, or the scratch set under its env."""
    scratch = ctx.env.get("DJB_SELFTEST_DRIVES_DIR")
    if scratch:
        found = sorted(Path(scratch).glob("test_*.sh")) if Path(scratch).is_absolute() else []
        found = found or sorted((ctx.root / scratch).glob("test_*.sh"))
        planted = [(p.stem[len("test_") :], p) for p in found if p.is_file()]
        return [*planted, *table.local_drives]
    legs = {g.name for g in table.legs}
    local = dict(table.local_drives)
    out: list[tuple[str, Path]] = []
    for name in table.unit("selftest")[1]:
        if name in legs:
            continue
        path = local.get(name) or drive_file(ctx.root, name)
        if path is None:
            raise R.RegistryError(f"drive '{name}' is registered and no test_{name}.sh exists")
        out.append((name, path))
    return out


def plan(
    ctx: Ctx,
    names: Sequence[str],
    k: int,
    n: int,
    pieces: Mapping[str, int] | None = None,
    units: Mapping[str, Sequence[str]] | None = None,
) -> tuple[dict[str, int], str]:
    """Each member's (or piece's) shard by LPT over the walls table; round-robin with none."""
    homes = [ctx.root / h for h in R.WALLS_HOMES]
    raw = R.walls_view(homes, R._machine(), only=False)
    narrowed = scope.read_plan(ctx.env)
    if raw and narrowed is not None:
        raw = scope.narrowed_walls(ctx.root, narrowed, raw)
    if not raw:
        robin = {name: i % n for i, name in enumerate(names)}
        robin[R.ENGINE_MEMBER] = 0
        return robin, (
            f"  selftest shard {k + 1}/{n}: the index round-robin (no durations table — each file "
            f"is a HINT and its absence means unmeasured, never a refusal; house-rules-engine runs "
            f"in shard 1)"
        )
    median = R.median_wall(raw, [R.ENGINE_MEMBER, *names])
    parts = R.member_parts(homes, R._machine(), units or {})
    walls, population = R.pieced(raw, [R.ENGINE_MEMBER, *names], pieces or {}, parts)
    alone = R.alone(raw, pieces or {}, parts)
    weight = {m: walls.get(m, median) for m in population}
    load, count, guessed = [0.0] * n, [0] * n, [0] * n
    table: dict[str, int] = {}
    for m in sorted(population, key=lambda m: (-weight[m], population.index(m))):
        s = min(range(n), key=lambda t: (load[t], t))
        table[m] = s
        load[s] += weight[m]
        count[s] += 1
        guessed[s] += 0 if m in walls else 1
    return table, (
        f"  selftest shard {k + 1}/{n}: {count[k]} members, predicted {int(load[k])} s (LPT over "
        f"the walls table, {R._machine()}'s column; {guessed[k]} unmeasured at the median "
        f"{median} s; {R.ceiling_line(weight, population, alone)})"
    )


def engine_held(taken: Mapping[str, int], k: int) -> tuple[int, list[int]]:
    """`(n, pieces)`: the engine's member count and the one-based members shard `k` holds."""
    prefix = f"{R.ENGINE_MEMBER}{R.PIECE}"
    n = sum(1 for m in taken if m.startswith(prefix))
    if not n:
        return 1, [1] if taken.get(R.ENGINE_MEMBER, 0) == k else []
    return n, [i for i in range(1, n + 1) if taken.get(R.piece_name(R.ENGINE_MEMBER, i)) == k]


def rule_ids(ctx: Ctx) -> list[str]:
    """The engine's rule ids in plan order; `ValueError` when the engine did not answer."""
    sys.stdout.flush()
    try:
        done = subprocess.run(
            ["uv", "run", "python", "-c", R.RULE_IDS_READER],
            cwd=ctx.root,
            env=dict(ctx.env),
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise ValueError(f"the engine's rule ids could not be read — {exc}") from exc
    ids = [x.strip() for x in done.stdout.splitlines() if x.strip()]
    if done.returncode or not ids:
        raise ValueError(
            f"the engine's rule ids did not answer (exit {done.returncode}){tool_said(done.stderr)}"
        )
    try:
        narrowed = scope.read_plan(ctx.env)
    except CouldNotLook as exc:
        raise ValueError(str(exc)) from exc
    if narrowed is None or narrowed.rules is None:
        return ids
    return [r for r in ids if r in narrowed.rules]


def consumed(env: Mapping[str, str]) -> dict[str, str]:
    """`env` without the plan: the leg has read it, so no member or child narrows by it again."""
    return {k: v for k, v in env.items() if k != scope.PLAN_ENV}


def every_rule(ctx: Ctx) -> list[str]:
    """The engine's rule ids, the plan's narrowing set aside."""
    return rule_ids(Ctx(ctx.root, ctx.mode, consumed(ctx.env)))


def carrier(ctx: Ctx, ids: Sequence[str]) -> str:
    """The cheapest rule to carry the whole parts when a narrowed plan re-keyed none."""
    secs = ledger.rule_durations([ctx.root / h for h in R.WALLS_HOMES], R._machine())
    return min(ids, key=lambda r: (secs.get(r, float("inf")), ids.index(r)))


def engine_lists(ctx: Ctx, ids: Sequence[str], n: int) -> tuple[list[list[str]], str]:
    """The `n` members' rule lists — LPT over the per-rule column, by count without one."""
    homes = [ctx.root / h for h in R.WALLS_HOMES]
    secs = ledger.rule_durations(homes, R._machine())
    measured = [secs[r] for r in ids if r in secs]
    if not measured:
        return [list(ids[i::n]) for i in range(n)], "by count (no per-rule column)"
    median = sorted(measured)[len(measured) // 2]
    load = [secs.get(R.RULE_WHOLE, 0.0)] + [0.0] * (n - 1)
    lists: list[list[str]] = [[] for _ in range(n)]
    order = {r: i for i, r in enumerate(ids)}
    for rid in sorted(ids, key=lambda r: (-secs.get(r, median), order[r])):
        s = min(range(n), key=lambda t: (load[t], t))
        lists[s].append(rid)
        load[s] += secs.get(rid, median)
    lists = [sorted(m, key=order.__getitem__) for m in lists]
    unmeasured = len(ids) - len(measured)
    return lists, f"LPT over the per-rule column ({unmeasured} unmeasured at the median)"


def partition_gap(ids: Sequence[str], lists: Sequence[Sequence[str]]) -> str:
    """'' when every rule id is in exactly one member's list, else what is missing or doubled."""
    held = [r for m in lists for r in m]
    twice = sorted({r for r in held if held.count(r) > 1})
    missing = [r for r in ids if r not in held]
    extra = sorted(set(held) - set(ids))
    found = (("in two members:", twice), ("in no member:", missing), ("no rule:", extra))
    parts = [f"{label} {' '.join(rs)}" for label, rs in found if rs]
    return "; ".join(parts)


def unit_plan(ctx: Ctx, table: R.Table, k: int, n: int) -> tuple[dict[str, int], str]:
    """The unit's one shard plan: the engine, every drive, and each Python leg after this one."""
    names = [*(name for name, _ in drives(ctx, table)), *after_legs(table)]
    return plan(ctx, names, k, n, table.pieces(), table.units(ctx.root))


def after_legs(table: R.Table) -> list[str]:
    """The selftest unit's Python legs after this one, each one indivisible member of the plan."""
    legs = {g.name for g in table.legs}
    return [m for m in table.unit("selftest")[1] if m in legs and m != "selftest"]


def bash(ctx: Ctx, script: str, env: Mapping[str, str]) -> tuple[int, str]:
    """`script` in bash over the gate's libraries; its exit and its stdout, stderr passed on."""
    prelude = "".join(f". {lib} || exit 2\n" for lib in LIBRARIES)
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        done = subprocess.run(
            ["bash", "-c", f"{prelude}gate_refuse_reset\nset +e\n{script}"],
            cwd=ctx.root,
            env={**ctx.env, **env},
            stdout=subprocess.PIPE,
        )
    except OSError as exc:
        return 2, f"cannot\tbash could not be started: {exc}\n"
    return done.returncode, done.stdout.decode(errors="replace")


def keys(ctx: Ctx, named: Sequence[tuple[str, Path]]) -> tuple[str, dict[str, Key]]:
    """Every drive keyed against the measured tree; `(tree, keys)` or `("", {})` with a cause."""
    # Invariant: a drive under the root is handed relative — `drive_key` covers `$file` as given.
    with tempfile.NamedTemporaryFile("w", prefix="djb-selftest-rows.", delete=False) as rows:
        rows.write("".join(f"{name}\t{_under(ctx.root, path)}\n" for name, path in named))
    try:
        rc, out = bash(ctx, KEYS, {"DJB_SELFTEST_ROWS": rows.name})
    finally:
        os.unlink(rows.name)
    tree, schema, found = "", "", {}
    for line in out.splitlines():
        cells = line.split("\t")
        if cells[0] == "cannot":
            return "", {"": Key(error=cells[1] if len(cells) > 1 else "keying failed")}
        if cells[0] == "tree" and len(cells) >= 3:
            tree, schema = cells[1], cells[2]
        elif cells[0] == "drive" and len(cells) >= 5:
            found[cells[1]] = parse_key(cells[2], schema, cells[3], cells[4])
    if rc != 0 or not tree:
        return "", {"": Key(error=f"the drive keying exited {rc} and named no measured tree")}
    return tree, found


def _under(root: Path, path: Path) -> Path:
    """`path` relative to `root` when it lies under it, else as given."""
    for base in (root, root.resolve()):
        if path.is_absolute() and path.is_relative_to(base):
            return path.relative_to(base)
    return path


def parse_key(keyout: str, schema: str, banked: str, last: str) -> Key:
    """`drive_key`'s answer read into its four fields, or its `err` sentence."""
    words = keyout.split()
    if len(words) < 3 or words[0] != "ok" or not words[1].startswith(f"{schema}:"):
        return Key(error=keyout[4:] if keyout.startswith("err ") else keyout or "no answer")
    machine = words[4][len("machine=") :] if len(words) > 4 else ""
    return Key(words[1], words[2], words[3] if len(words) > 3 else "", machine, "", banked, last)


def moved(old: str, new: str) -> str:
    """The first key component whose digest moved between two `parts=` lists."""
    split = [dict(p.rsplit(":", 1) for p in x.split(",") if ":" in p) for x in (old, new)]
    for k, v in split[1].items():
        if split[0].get(k) != v:
            return k
    return next((k for k in split[0] if k not in split[1]), "")


def engine_dir(ctx: Ctx) -> Path | None:
    """Where the engine's drive file is written: the scratch set's `engine/`, else the git dir."""
    scratch = ctx.env.get("DJB_SELFTEST_DRIVES_DIR")
    if scratch:
        return (ctx.root / scratch) / "engine"
    done = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"],
        cwd=ctx.root,
        env=dict(ctx.env),
        capture_output=True,
        text=True,
    )
    found = done.stdout.strip()
    return Path(found) / "djb-engine-inputs" if done.returncode == 0 and found else None


def cover(tree: Sequence[str], inputs: Sequence[str]) -> list[str]:
    """The exact cover of `inputs` in `tree`: each wholly-listed directory as `d/`, else by name."""
    held = set(tree)
    total: dict[str, int] = {}
    for path in tree:
        for d in _ancestors(path):
            total[d] = total.get(d, 0) + 1
    listed = list(dict.fromkeys(p for p in inputs if p in held))
    got: dict[str, int] = {}
    for path in listed:
        for d in _ancestors(path):
            got[d] = got.get(d, 0) + 1
    full = {d for d, n in total.items() if got.get(d) == n}
    out = {f"{d}/" for d in full if "/" not in d or d.rsplit("/", 1)[0] not in full}
    out |= {p for p in listed if not any(d in full for d in _ancestors(p))}
    return sorted(out, key=lambda x: x.encode())


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[: i + 1]) for i in range(len(parts) - 1)]


def engine_drive_file(ctx: Ctx, tree: str) -> tuple[str, str]:
    """`(path, "")` of the engine's drive file over `--selftest-inputs`, or `("", why)`."""
    home = engine_dir(ctx)
    if home is None:
        return "", "this checkout has no git dir to write the engine drive file into"
    try:
        home.mkdir(parents=True, exist_ok=True)
    except OSError:
        return "", f"{home} could not be created"
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        done = subprocess.run(INPUTS, cwd=ctx.root, env=dict(ctx.env), capture_output=True)
    except OSError as exc:
        return "", f"`--selftest-inputs` could not be started — {exc}"
    try:
        (home / "inputs.txt").write_bytes(done.stdout)
        (home / "inputs.err").write_bytes(done.stderr)
    except OSError:
        return "", f"{home / 'inputs.txt'} could not be written"
    said = [*done.stdout.decode(errors="replace").splitlines()]
    said += done.stderr.decode(errors="replace").splitlines()
    if done.returncode:
        why = next((line.strip().lstrip("!").strip() for line in said if "!!" in line), "")
        return "", (
            f"`--selftest-inputs` exited {done.returncode} — {why or 'it named no cause'}"
            f" (all of it: {home / 'inputs.err'}){tool_said(done.stderr)}"
        )
    if not done.stdout:
        return "", (
            "`--selftest-inputs` exited 0 and printed no path — an engine that reads nothing is "
            "not an engine"
        )
    inputs = done.stdout.decode(errors="replace").splitlines()
    try:
        held = [e.path for e in ledger.listing(ctx.root, tree)]
    except (ledger.Mismatch, OSError, subprocess.SubprocessError):
        return "", "the measured tree could not be read"
    decls = cover(held, inputs)
    if not decls:
        return "", (
            f"none of the {len(inputs)} path(s) --selftest-inputs printed is in the measured tree"
        )
    file = home / ENGINE_FILE
    try:
        file.write_text(
            f"# drives: {' '.join(decls)} \n"
            "# the house-rules engine, keyed from outside itself. Derived, never edited.\n"
            f"# inputs-digest {hashlib.sha256(done.stdout).hexdigest()}\n"
        )
        (home / "drive_preamble.sh").write_text(ENGINE_PREAMBLE)
    except OSError:
        return "", f"{file} could not be written"
    return str(file), ""


def engine_keyed(ctx: Ctx) -> tuple[str, str, str]:
    """`(tree, file, why)`: the measured tree and the engine drive file, or why there is none."""
    tree = ctx.env.get("MEASURED_START", "")
    if not tree:
        try:
            tree = ledger.measured_tree(ctx.root)
        except (ledger.Mismatch, OSError, subprocess.SubprocessError, CouldNotLook):
            return "", "", "the measured tree could not be read"
    file, why = engine_drive_file(ctx, tree)
    return tree, file, why


def consult(ctx: Ctx, tally: Tally, name: str, key: Key, part: str, skip: str = "") -> bool:
    """True to run the member; False once it is counted — REUSED green, or could not key."""
    if key.error:
        print(f"  drive {name}: could not key — {key.error}", flush=True)
        tally.cannot.append(name)
        return False
    if key.cites and key.cites != "cites=0":
        print(
            f"  drive {name}: {key.cites[len('cites=') :]} path(s) CITED, in no key "
            "(# cites:) — a citation is not a subject",
            flush=True,
        )
    if skip:
        print(
            f"  drive {name}: not consulted — whole mode ({skip}): a banked green is keyed on "
            f"neither the tree nor the mode, so it is never reused for a whole run; it runs, "
            f"and a green still banks",
            flush=True,
        )
        return True
    if ctx.env.get("DJB_SELFTEST_NO_REUSE"):
        return True
    if key.banked:
        banked = key.banked.split()[3] if len(key.banked.split()) > 3 else "?"
        print(
            f"  drive {name}: REUSED from {key.key} (banked {banked}) "
            f"machine={key.machine or 'unstated'}",
            flush=True,
        )
        walls_append(ctx, name, "reused", "-", part)
        tally.green += 1
        return False
    if key.last:
        old = next((w[len("parts=") :] for w in key.last.split() if w.startswith("parts=")), "")
        what = moved(old, key.parts) if old else ""
        if what:
            since = key.last.split()[1] if len(key.last.split()) > 1 else "?"
            print(f"  miss: {what} moved since {since} machine={key.machine or 'unstated'}")
    return True


def bank(ctx: Ctx, name: str, key: Key, took: int, tree: str) -> None:
    """One green member's row under its key (`drive_ledger_record`); a dry run banks nothing."""
    if key.key and not ctx.env.get("DJB_GATE_LEGS_DRY"):
        bash(ctx, RECORD, {"K": key.key, "N": name, "T": str(took), "TREE": tree, "P": key.parts})


def run_member(ctx: Ctx, name: str, argv: Sequence[str], env: Mapping[str, str]) -> tuple[int, str]:
    """One member with both streams captured, then printed; a kill prints its output so far."""
    started = time.monotonic()
    with tempfile.TemporaryFile() as out:
        sys.stdout.flush()
        sys.stderr.flush()
        try:
            rc = subprocess.run(
                list(argv),
                cwd=ctx.root,
                env={**consumed(ctx.env), **env},
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
            ).returncode
        except OSError as exc:
            out.write(f"!! {argv[0]} could not be started: {exc}\n".encode())
            rc = 2
        except BaseException:
            out.seek(0)
            took = int(time.monotonic() - started)
            print(f"  drive {name}: killed after {took}s — its output so far:", flush=True)
            sys.stdout.write(out.read().decode(errors="replace"))
            sys.stdout.flush()
            raise
        out.seek(0)
        text = out.read().decode(errors="replace")
    sys.stdout.write(text)
    sys.stdout.flush()
    return rc, text


def judge(rc: int, text: str, own: str) -> tuple[int, str]:
    """A drive's verdict from its exit AND its one summary line (`quality/tests/drives.py`)."""
    from quality.tests.drives import verdict

    return verdict(rc, text, own)


def failed_lines(name: str, text: str) -> list[str]:
    """A red member's FAILED lines for the closing list, at most `FAILED_CAP` of them."""
    hits = [line.strip() for line in text.splitlines() if _FAILED.match(line)]
    if not hits:
        return [f"   {name}: printed no FAILED line — read its own output above"]
    more = f", the first {FAILED_CAP} below" if len(hits) > FAILED_CAP else ""
    kept = [f"   {name}: {len(hits)} FAILED line(s){more}"]
    kept += [f"     {line}" for line in hits[:FAILED_CAP]]
    if len(hits) > FAILED_CAP:
        kept.append(
            f"     ... and {len(hits) - FAILED_CAP} more FAILED line(s), above in its own output"
        )
    return kept


def walls_append(
    ctx: Ctx, name: str, rc: str, took: str, part: str, more: Sequence[str] = ()
) -> None:
    """One `member-walls/1` row, and the member's `more` rows, to `DJB_MEMBER_WALLS_OUT`."""
    sink = ctx.env.get("DJB_MEMBER_WALLS_OUT")
    if not sink:
        return
    try:
        with open(sink, "a", encoding="utf-8") as fh:
            fh.write(f"member-walls/1\t{name}\t{rc}\t{took}\t{part}\n")
            fh.writelines(f"{row}\n" for row in more)
    except OSError:
        print(
            f"  member-walls: could not append {name}'s row to {sink} — the harvest will find "
            f"this run incomplete and leave the committed table standing",
            flush=True,
        )


def rule_walls(text: str) -> dict[str, float]:
    """Each `rule-wall` line's seconds by rule id, as the engine printed them."""
    found: dict[str, float] = {}
    for line in text.splitlines():
        hit = _RULE_WALL.match(line)
        if hit:
            found[hit[1]] = float(hit[2])
    return found


def rules_append(ctx: Ctx, text: str, took: int, part: str) -> None:
    """One `rule-walls/1` row per rule the engine timed, and its `@fixed` rest, when asked."""
    sink = ctx.env.get("DJB_MEMBER_WALLS_OUT")
    walls = rule_walls(text)
    if not sink or not walls:
        return
    rest = max(0.0, took - sum(walls.values()))
    rows = [*walls.items(), (R.RULE_FIXED, rest)]
    try:
        with open(sink, "a", encoding="utf-8") as fh:
            fh.writelines(f"{R.RULE_ROW}\t{rid}\t{secs:.1f}\t{part}\n" for rid, secs in rows)
    except OSError:
        print(
            f"  rule-walls: could not append the engine's {len(walls)} rule rows to {sink} — the "
            f"harvest will find no per-rule column for this run",
            flush=True,
        )


def crossing(ctx: Ctx, tally: Tally, name: str, took: int) -> None:
    """A drive's crossed floor, said on a full run that writes walls rows (`gate_member_record`)."""
    if (
        ctx.mode != "full"
        or ctx.env.get("GATE_LEG_UNIT")
        or not ctx.env.get("DJB_MEMBER_WALLS_OUT")
    ):
        return
    from quality.djb.legs import always_on

    if tally.recorded is None:
        walls = always_on.walls(ctx)
        tally.recorded = walls.seconds if walls else {}
    recorded = tally.recorded.get(name)
    if recorded is None:
        return
    floor = always_on.floor(ctx)
    if took >= floor > recorded:
        side, act = "above", "leaves the always-on set"
    elif took < floor <= recorded:
        side, act = "below", "joins the always-on set"
    else:
        return
    print(f"  member {name}: {took} s live vs {recorded} s recorded — {side} the loop floor;")
    print(f"                  {act} at the next --store-durations", flush=True)


def end(tally: Tally, name: str, rc: int, took: int, text: str, *, outrank: bool = False) -> None:
    """Count one member's verdict; a red keeps its FAILED lines for the closing list."""
    print(f"  drive {name}: exit {rc} ({took}s)", flush=True)
    tally.seconds[name] = took
    if rc == 0:
        tally.green += 1
    elif rc == 2 or outrank:
        tally.cannot.append(name)
    else:
        tally.red.append(name)
        tally.failed += failed_lines(name, text)


def compose(tally: Tally) -> int:
    """The leg's one verdict: 2 when any member could not look, else 1 when any is red, else 0."""
    print("", flush=True)
    print(
        f"  selftest: {tally.green} drive(s) green · {len(tally.red)} red · "
        f"{len(tally.cannot)} could-not-look"
        " (the house-rules engine's own selftest counted as one)",
        flush=True,
    )
    if tally.cannot:
        say(f"!! COULD NOT LOOK: {' '.join(tally.cannot)}")
        if tally.red:
            say(f"!! and RED: {' '.join(tally.red)}", *tally.failed)
        say(
            "   2 outranks 1: a driver that could not run its cases has not cleared",
            "   them, whatever the rest of the set did. Read the FIRST name above",
            "   first — every drive ran, so a later name can be a SECONDARY red left",
            "   by state an earlier one moved.",
        )
        return 2
    if tally.red:
        say(
            f"!! RED: {' '.join(tally.red)}",
            *tally.failed,
            "   Every drive ran and every red is named above — that is what this leg",
            "   is for. Read the FIRST one first: a red drive can leave state a later",
            "   drive trips on, so a later name can be a secondary.",
        )
        return 1
    return 0


def engine_members(ctx: Ctx, tally: Tally, n: int, pieces: Sequence[int], part: str) -> None:
    """This shard's engine members as one `--member` run over their rule lists, never banked."""
    ks = ",".join(map(str, pieces))
    label = f"{R.ENGINE_MEMBER} {ks}/{n}"
    try:
        ids = rule_ids(ctx)
    except ValueError as exc:
        say(f"!! {label}: {exc} — the members cannot be cut, so none ran.")
        tally.cannot.append(label)
        return
    lists, how = engine_lists(ctx, ids, n)
    gap = partition_gap(ids, lists)
    if gap:
        say(f"!! {label}: the {n} members' lists do not partition the {len(ids)} rules — {gap}")
        tally.cannot.append(label)
        return
    rules = [r for k in pieces for r in lists[k - 1]]
    whole = 1 in pieces
    if not rules and not whole:
        print(f"  {label}: the plan re-keyed no rule in these members — nothing to run", flush=True)
        return
    if not rules:
        rules = [carrier(ctx, every_rule(ctx))]
        print(
            f"  {label}: the plan re-keyed no rule; {rules[0]} carries the whole parts", flush=True
        )
    print(
        f"  {label}: {len(rules)} of {len(ids)} rules, {how}"
        f"{WHOLE_CLAUSE if whole else ''} — not consulted and "
        "never banked: a member's green is not the engine's",
        flush=True,
    )
    argv = [*ENGINE[0], "--member", *(["--whole"] if whole else [])]
    argv += [w for r in rules for w in ("--rule", r)]
    started = time.monotonic()
    rc, text = run_member(ctx, label, argv, {})
    took = int(time.monotonic() - started)
    end(tally, label, rc, took, text, outrank=True)
    walls_append(ctx, f"{R.ENGINE_MEMBER}{R.PIECE}{ks}/{n}", str(rc), str(took), part)
    rules_append(ctx, text, took, part)
    if rc:
        say(
            "!! ENFORCEMENT ITSELF IS BROKEN — a dead canary outranks any pass.",
            f"   {label} is recorded as could-not-look; the drives below STILL RUN.",
        )


def drawer_engine(ctx: Ctx, tally: Tally, namespace: str) -> None:
    """A product's engine member: its drawer's own rules alone, one `--member` run, never banked."""
    print(f"  {ENGINE_ON_A_PRODUCT}", flush=True)
    label = f"{R.ENGINE_MEMBER} {namespace}"
    try:
        ids = rule_ids(ctx)
    except ValueError as exc:
        say(f"!! {label}: {exc} — the drawer's rules could not be named, so none ran.")
        tally.cannot.append(label)
        return
    own = [r for r in ids if r.startswith(f"{namespace}-")]
    if not own:
        return
    print(f"  {label}: the drawer's {len(own)} rule(s) self-tested alone, never banked", flush=True)
    argv = [*ENGINE[0], "--member", *(w for r in own for w in ("--rule", r))]
    started = time.monotonic()
    rc, text = run_member(ctx, label, argv, {})
    end(tally, label, rc, int(time.monotonic() - started), text, outrank=True)
    if rc:
        say("!! ENFORCEMENT ITSELF IS BROKEN — a dead canary in the drawer outranks any pass.")


def shard_of(ctx: Ctx) -> tuple[int, int] | None:
    """`(k, n)` zero-based from `GATE_SHARD_K`/`GATE_SHARD_N` on the selftest unit's run."""
    k, n = ctx.env.get("GATE_SHARD_K"), ctx.env.get("GATE_SHARD_N")
    if not k or ctx.env.get("GATE_LEG_UNIT") != "selftest":
        return None
    if not (k.isdigit() and (n or "").isdigit()):
        raise ValueError(f"'{k}' '{n}' is not a k/N pair of integers")
    return int(k) - 1, int(n or 0)


def run(ctx: Ctx, shard: tuple[int, int] | None = None) -> int:
    """The leg under SIGTERM/SIGHUP handlers; one delivered is re-delivered once the log has it."""
    try:
        held = {sig: signal.signal(sig, _raise_killed) for sig in DELIVERED}
    except ValueError:
        return members(ctx, shard)
    try:
        return members(ctx, shard)
    except Killed as killed:
        for sig in DELIVERED:
            signal.signal(sig, signal.SIG_DFL)
        sys.stdout.flush()
        sys.stderr.flush()
        os.kill(os.getpid(), killed.signum)
        raise
    finally:
        for sig, old in held.items():
            signal.signal(sig, old)


def members(ctx: Ctx, shard: tuple[int, int] | None = None) -> int:
    """Member zero the engine's selftest, then every drive; one composed 0/1/2 and no early exit."""
    if ctx.env.get("GATE_PR"):
        print(
            "  selftest (--pr): not run — the engine's canaries and the drives test the platform,"
            " which a loop-lane diff does not touch; the rules run whole in their own legs",
            flush=True,
        )
        return 0
    try:
        shard = shard if shard is not None else shard_of(ctx)
    except ValueError as exc:
        say(f"!! selftest: {exc}.")
        return 2
    if shard is not None and (shard[1] < 1 or not 0 <= shard[0] < shard[1]):
        say(f"!! selftest: shard {shard[0] + 1}/{shard[1]} is outside 1..{shard[1]}.")
        return 2
    try:
        table = R.load(ctx.root)
        named = drives(ctx, table)
    except (R.RegistryError, CouldNotLook, OSError) as exc:
        say(f"!! selftest: the drive population could not be read — {exc}")
        return 2
    try:
        narrowed = scope.read_plan(ctx.env)
    except CouldNotLook as exc:
        say(f"!! selftest: the plan could not be read — {exc}")
        return 2
    if narrowed is not None:
        print(f"  selftest plan: {narrowed.line()} ({scope.PLAN_ENV})", flush=True)
    tally = Tally()
    part = "1/1"
    taken: dict[str, int] = {}
    if shard is not None:
        k, n = shard
        part = f"{k + 1}/{n}"
        print(f"  shard {k + 1}/{n} of the registered drive order", flush=True)
        taken, line = unit_plan(ctx, table, k, n)
        print(line, flush=True)
        for name in after_legs(table):
            n_of = sum(1 for m in taken if m.startswith(f"{name}{R.PIECE}")) or 1
            for i in range(1, n_of + 1):
                planned = R.piece_name(name, i) if n_of > 1 else name
                held = "in shard" if taken.get(planned, 0) == k else "not in shard"
                print(f"  leg {planned}: {held} {part} (the unit's leg after this one)", flush=True)

    def mine(name: str) -> bool:
        return shard is None or taken.get(name, 0) == shard[0]

    def not_mine(name: str) -> None:
        print(f"  drive {name}: not in shard {part}", flush=True)

    if ctx.env.get("DJB_GATE_LEGS_DRY"):
        for name, _ in named:
            if mine(name):
                print(f"- drive {name}", flush=True)
                print(f"  leg: {name} (DJB_GATE_LEGS_DRY — announced, body not run)", flush=True)
        return 0
    todo = [(name, path) for name, path in named if mine(name)]
    of_n, pieces = engine_held(taken, shard[0]) if shard is not None else (1, [1])
    engine = bool(pieces)
    cut = of_n > 1
    from quality.djb.legs import gate_tests

    try:
        namespace = gate_tests.product_of(ctx.root) if engine else None
    except (CouldNotLook, OSError) as exc:
        say(f"!! {R.ENGINE_MEMBER}: this tree's drawer could not be read — {exc}")
        tally.cannot.append(R.ENGINE_MEMBER)
        namespace = R.ENGINE_MEMBER
    product = bool(namespace)
    keyed_engine = engine and not cut and not product
    tree, engine_file, engine_why = engine_keyed(ctx) if keyed_engine else ("", "", "")
    rows = [(R.ENGINE_MEMBER, Path(engine_file))] if engine_file else []
    keyed_ctx = Ctx(ctx.root, ctx.mode, {**ctx.env, "MEASURED_START": tree}) if tree else ctx
    keyable = [(name, path) for name, path in todo if not name.startswith(R.LOCAL)]
    if rows or keyable:
        tree, keyed = keys(keyed_ctx, [*rows, *keyable])
    else:
        keyed = {}
    cannot_key = keyed.get("", Key()).error
    if ctx.env.get("DJB_SELFTEST_NO_REUSE") and (engine or todo):
        print("  == drive verdicts NOT consulted: DJB_SELFTEST_NO_REUSE is set ==")
        print("     every drive runs and every green still banks — a drive row is keyed")
        print(
            "     on its INPUTS, so a forced green is newer evidence for the same key.", flush=True
        )

    if R.ENGINE_MEMBER in tally.cannot:
        pass
    elif namespace and (not cut or 1 in pieces):
        drawer_engine(ctx, tally, namespace)
    elif product:
        not_mine(R.ENGINE_MEMBER)
    elif not engine:
        not_mine(R.ENGINE_MEMBER)
    elif cut:
        engine_members(ctx, tally, of_n, pieces, part)
    elif narrowed is not None and narrowed.rules is not None:
        engine_members(ctx, tally, 1, [1], part)
    else:
        why = engine_why or cannot_key or "the drive keying named no key for it"
        key = keyed.get(R.ENGINE_MEMBER, Key(error=why))
        if consult(ctx, tally, R.ENGINE_MEMBER, key, part):
            started = time.monotonic()
            rc, text = run_member(ctx, R.ENGINE_MEMBER, ENGINE[0], {})
            took = int(time.monotonic() - started)
            end(tally, R.ENGINE_MEMBER, rc, took, text, outrank=True)
            walls_append(ctx, R.ENGINE_MEMBER, str(rc), str(took), part)
            rules_append(ctx, text, took, part)
            if rc:
                say(
                    "!! ENFORCEMENT ITSELF IS BROKEN — a dead canary outranks any pass.",
                    "   Recorded as could-not-look. The drives below STILL RUN: the leg's",
                    "   exit is composed at the end, and a 25-minute gate should print its",
                    "   whole red list once.",
                )
            else:
                bank(ctx, R.ENGINE_MEMBER, key, took, tree)
    scratch = bool(ctx.env.get("DJB_SELFTEST_DRIVES_DIR"))
    if scratch:
        print(f"  DJB_SELFTEST_DRIVES_DIR is set — driving {ctx.env['DJB_SELFTEST_DRIVES_DIR']}")
        print("  and NOT scripts/tests/. This is the leg's own drive's scratch set.", flush=True)
    env: dict[str, str] = {}
    whole = ""
    if shard is not None and ctx.env.get("GATE_LEG_UNIT") == "selftest":
        whole = f"the selftest unit is sharded (--leg selftest --shard {part})"
        env["DJB_SELFTEST_SHAPES_WHOLE_RUN"] = whole
    elif ctx.env.get("DJB_SELFTEST_SHAPES_WHOLE_RUN"):
        print(
            f"  selftest_shapes: DJB_SELFTEST_SHAPES_WHOLE_RUN="
            f"'{ctx.env['DJB_SELFTEST_SHAPES_WHOLE_RUN']}' was set by hand on an unsharded run — "
            "UNSET; the whole run is a shard's (--leg selftest --shard k/N), so this runs "
            "narrowed",
            flush=True,
        )
    ctx = Ctx(
        ctx.root,
        ctx.mode,
        {k: v for k, v in ctx.env.items() if k != "DJB_SELFTEST_SHAPES_WHOLE_RUN"},
    )
    for name, path in named:
        if not mine(name):
            not_mine(name)
            continue
        product = name.startswith(R.LOCAL)
        key = keyed.get(name, Key(error=cannot_key or "the drive keying named no key for it"))
        skip = whole if whole and name == WHOLE_RUN_DRIVE else ""
        if product:
            print(
                f"  drive {name}: not consulted — a product drive is not keyed or banked; it runs"
                " on every gate",
                flush=True,
            )
        elif not consult(ctx, tally, name, key, part, skip):
            continue
        started = time.monotonic()
        rc, text = run_member(ctx, name, [str(path)], env)
        took = int(time.monotonic() - started)
        verdict, why = judge(rc, text, path.stem)
        if verdict == 2:
            say(
                f"!! the {name} drive COULD NOT LOOK ({why}) — see above.",
                "   A driver that could not run its cases has not cleared them.",
            )
        elif verdict:
            say(f"!! the {name} drive is red ({why}): {RED.get(name, GENERIC_RED)}")
        end(tally, name, verdict, took, text)
        walls_append(ctx, name, str(verdict), str(took), part)
        crossing(ctx, tally, name, took)
        if verdict == 0 and not product:
            bank(ctx, name, key, took, tree)
    rc = compose(tally)
    say_not_run(ctx.root, table)
    return rc


LEG = Leg(
    "selftest",
    "selftest",
    "house-rules self-test (every canary planted through the real scope must fire; every "
    "negative must stay silent) + every shell refusal drive under scripts/tests/",
    run,
    None,
    frozenset({"full"}),
    ARGV,
)
