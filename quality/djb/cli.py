"""The Python door for the modes the registry owns: `--fast`, `--list-legs`, `--census`, `hook`."""

# Invariant: an unknown word is exit 2 before any leg; only the listing and the census read a pipe.
# does-not-cover: `--loop`, the full gate and `--leg` — `scripts/check.sh` runs them.

from __future__ import annotations

import fnmatch
import os
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from quality.could_not_look import CouldNotLook, exit_could_not_look
from quality.djb import env as environment
from quality.djb.legs._run import LIBRARIES, tool
from quality.djb.legs.goalpost_census import census
from quality.djb.registry import Ctx, RegistryError, Table, list_legs, load, local_tier

#: This checkout: the door runs from the root it lives in, as `check.sh` cds to its own.
ROOT = Path(__file__).resolve().parents[2]
#: The refusal while a full gate holds this checkout's lock (`gate_lock_refuse_if_held`).
LOCK_HELD = (
    "!! REFUSING: a FULL gate is already running in THIS checkout.",
    "   holder: {holder}  (pid mode started-utc)",
    "   Its self-test plants canary files into this tree and restores them, and its",
    "   pytest passes own this checkout's database. Running now would read a tree that",
    "   is briefly not the tree, and could restore over your edits.",
    "   Wait for it, or run in your own worktree — another checkout is unaffected.",
)
#: Who holds the lock, by the shell's one reader of a hold.
HOLDER = 'gate_hold_holder "$(git rev-parse --absolute-git-dir)/djb-gate-lock" "gate lock"'


@dataclass(frozen=True)
class Mode:
    """One mode: its flag, its modifiers, whether a pipe may read it, and what it runs."""

    flag: str
    modifiers: tuple[str, ...]
    piped: bool
    summary: str
    run: Callable[[Path, Sequence[str]], int]
    operands: bool = False


def refuse_if_piped(root: Path) -> None:
    """Exit 2 when stdout is a pipe, through the shell's one guard so the sentence is its own."""
    rc = tool(
        Ctx(root, "fast"),
        ("bash", "-c", ". scripts/gate_refuse.sh || exit 2\nrefuse_if_piped check.sh"),
    )
    if rc:
        raise SystemExit(2)


def refuse_if_locked(root: Path) -> None:
    """Exit 2 when a full gate holds this checkout's lock."""
    prelude = "".join(f". {lib} || exit 2\n" for lib in LIBRARIES[:3])
    held = subprocess.run(
        ["bash", "-c", prelude + HOLDER], cwd=root, capture_output=True, text=True
    )
    if held.returncode not in (0, 1):
        exit_could_not_look(f"the gate lock could not be read: {held.stderr.strip()}")
    sys.stderr.write(held.stderr)
    holder = held.stdout.strip()
    if holder:
        print("\n".join(LOCK_HELD).format(holder=holder), file=sys.stderr)
        raise SystemExit(2)


def table(root: Path) -> Table:
    """The registry's table for `root`; its refusals are exit 2."""
    try:
        return load(root)
    except RegistryError as exc:
        print(f"!! the leg table does not validate: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def run_fast(root: Path, modifiers: Sequence[str]) -> int:
    """Every `fast` leg in order, under a host slot; the first non-zero exit is the run's."""
    refuse_if_locked(root)
    from quality.djb import hold

    try:
        taken = hold.hold("host", on_contention="wait", mode="fast")
    except hold.Refused:
        return 2
    try:
        return _fast(root)
    finally:
        if taken is not None:
            taken.release()


DERIVE_NAME = (
    ". scripts/gate_refuse.sh || exit 2\n. scripts/db.sh || exit 2\n"
    'printf "%s\\n%s\\n" "${DATABASE_NAME:-}" "${DATABASE_NAME_SOURCE:-}"'
)


def fast_environ(root: Path) -> dict[str, str]:
    """The fast legs' environment: `db.sh`'s name and label when no database variable names one."""
    env = environment.environ()
    if env.get("DATABASE_NAME") or env.get("DATABASE_URL"):
        return env
    try:
        done = subprocess.run(
            ["bash", "-c", DERIVE_NAME],
            cwd=root,
            env={**env, "DB_PIN_NOTE_OFF": "1"},
            stdout=subprocess.PIPE,
            text=True,
        )
    except OSError:
        return env
    name, _, label = done.stdout.partition("\n")
    if done.returncode != 0 or not name:
        return env
    return {**env, "DATABASE_NAME": name, "DATABASE_NAME_SOURCE": label.strip() or "derived"}


def _fast(root: Path) -> int:
    legs = table(root)
    started = time.monotonic()
    ctx = Ctx(root, "fast", fast_environ(root))
    dry = environment.read("DJB_GATE_LEGS_DRY")
    for leg in legs.mode_legs("fast"):
        print(f"- {leg.banner}", flush=True)
        t0 = time.monotonic()
        if dry:
            print(f"  leg: {leg.name} (DJB_GATE_LEGS_DRY — announced, body not run)", flush=True)
            continue
        assert leg.body is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
        rc = leg.body(ctx)
        if rc:
            return rc
        print(f"  ({leg.name}: {int(time.monotonic() - t0)}s)", flush=True)
    if local_tier(legs.local, "fast") and dry:
        print("- local-legs: the product's own legs, tier fast", flush=True)
        print("  leg: local-legs (DJB_GATE_LEGS_DRY — announced, body not run)", flush=True)
    elif local_tier(legs.local, "fast"):
        from quality.djb import drawer

        print("- local-legs: the product's own legs, tier fast", flush=True)
        changed = (environment.read("DJB_LOCAL_LEGS_CHANGED_FILES") or "").split()
        rc = drawer.run(legs, "fast", ctx.env, narrowed=True, changed=changed)
        if rc:
            return rc
    skipped = [
        m
        for _, members in legs.rows
        for m in members
        if m not in {g.name for g in legs.mode_legs("fast")}
        and m not in local_tier(legs.local, "fast")
    ]
    print(f"ok: fast checks passed ({int(time.monotonic() - started)}s)")
    print(f"  NOT run: {', '.join(skipped)}.")
    print("  --loop is the per-rung gate; the full gate binds at push.")
    return 0


def run_list_legs(root: Path, modifiers: Sequence[str]) -> int:
    """The unit table, tab-separated; `--ci` adds the shard count and the `passes` column."""
    sys.stdout.write(list_legs(table(root), ci="--ci" in modifiers, root=root))
    return 0


def run_census(root: Path, modifiers: Sequence[str]) -> int:
    """The instrument census alone: no leg banner, no lock, its own exit."""
    return census(Ctx(root, "fast", environment.environ()))


def run_help(root: Path, modifiers: Sequence[str]) -> int:
    """The mode table this door parses, printed from the table itself."""
    print(usage())
    return 0


# --- `hook pre-push`: the wall --------------------------------------------------------------------

#: A verifier box's throwaway probe remote, the one place `DJB_PUSH_DESTINATION` opens.
BOX_PROBE = "/*/.vouch-[0-9]*/probe.git"
ZERO = "0" * 40
#: The one branch nothing pushes to: it moves by a pull request's merge (R10.2).
MAIN = "refs/heads/main"
#: The refusal for a push to `MAIN` the ledger holds no verdict for; no gate is started.
MAIN_REFUSED = (
    "!! pre-push: REFUSED — refs/heads/main moves by a pull request's merge, never by a push.",
    "   pushed tree(s) with no verdict: {unmeasured}",
    "   GitHub merges a pm/* branch's pull request when its required checks are green;",
    "   from the train branch: ./scripts/pm_push.sh --pr",
    "   No gate was started: a Mac full gate is not how main is measured.",
)
#: The one push to `MAIN` the wall lets through unmerged: git's null remote sha, a remote with none.
MAIN_SEEDED = (
    "pre-push: main seeded — the remote had no main; every later move is a pull request's merge"
)
#: The refusal for a pushed tree that is not this checkout's (`pre-push`'s two-tree sentence).
FOREIGN = (
    "!! pre-push: REFUSED — the ref being pushed is not the tree in this checkout.",
    "   pushed tree(s) with no verdict: {unmeasured}",
    "   this checkout measures:          {tree}",
    "   A full gate run here would measure THIS tree and bank a verdict about it,",
    "   which is not the thing being pushed. Push from a checkout of what you are",
    "   pushing — scripts/pm_push.sh detaches a worktree to the SHA for exactly",
    "   this reason — or run the gate there.",
)
#: `FOREIGN`'s porcelain lines, at most this many before `… and N more`.
DIFFERING_SHOWN = 10
#: The sentence after the differing paths: what moves a checkout's tree off HEAD's.
UNTRACKED_MEASURED = (
    "   untracked, not ignored files are part of the measured tree: commit them, or ignore them"
    " (.gitignore or .git/info/exclude), then push again"
)


def _say(line: str) -> None:
    print(line, flush=True)


def _err(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def _differing(root: Path, shas: Sequence[str]) -> list[str]:
    """`git status --porcelain` of the checkout, capped, naming a pushed sha that is not HEAD."""
    done = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    rows = [row for row in done.stdout.splitlines() if row] if done.returncode == 0 else []
    if not rows:
        return []
    lines = ["   the paths that move it off HEAD (git status --porcelain):"]
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    other = next((sha for sha in shas if sha != head), "")
    if other:
        lines.append(
            f"   HEAD is {head[:12]}; the pushed ref is {other[:12]} — the paths below are HEAD's,"
            " not the pushed commit's"
        )
    lines += [f"     {row}" for row in rows[:DIFFERING_SHOWN]]
    if len(rows) > DIFFERING_SHOWN:
        lines.append(f"     … and {len(rows) - DIFFERING_SHOWN} more")
    return [*lines, UNTRACKED_MEASURED]


def _wall(word: str, tree: str) -> None:
    """The sentinel: every terminal decision is preceded by `pre-push: wall <word> <tree>`."""
    _say(f"pre-push: wall {word} {tree or '<unreadable>'}")


def pre_push(root: Path, argv: Sequence[str], refs: Sequence[str]) -> int:
    """Honour a banked tree, refuse main or a foreign one, exempt a box or intent, else measure."""
    from quality.djb import env as djb_env
    from quality.djb import ledger

    url = argv[1] if len(argv) > 1 else ""
    box = False
    if djb_env.read("DJB_PUSH_DESTINATION") == "verifier-box":
        box = fnmatch.fnmatchcase(url, BOX_PROBE)
        if not box:
            _say(
                "pre-push: DJB_PUSH_DESTINATION=verifier-box ignored — the remote is not a"
                " verifier-box probe"
            )
    pushed: list[str] = []
    shas: list[str] = []
    to: list[str] = []
    deletions = 0
    held = False
    for line in refs:
        words = line.split()
        if len(words) < 2:
            continue
        if words[1] == ZERO:
            deletions += 1
            continue
        to.append(words[2] if len(words) > 2 else "<none>")
        shas.append(words[1])
        if to[-1] == MAIN and (len(words) < 4 or words[3] != ZERO):
            held = True
        try:
            tree = ledger.measured_tree_of(root, f"{words[1]}^{{tree}}")
        except ledger.Mismatch:
            _err(f"pre-push: cannot resolve a tree for the pushed ref {words[0]} ({words[1]}).")
            _err("  A ref whose tree this repository cannot read is not a ref this hook can")
            _err("  vouch for. Measuring.")
            pushed = ["UNRESOLVABLE"]
            break
        if tree not in pushed:
            pushed.append(tree)
    try:
        tree = ledger.measured_tree(root)
    except ledger.Mismatch:
        tree = ""
    if deletions and not to:
        _wall("deletion", tree)
        _say(f"pre-push: {deletions} ref deletion(s) and nothing else — a deletion pushes no tree,")
        _say("  so there is nothing to measure and no verdict is consulted")
        return 0
    intent = False
    wanted = djb_env.read("DJB_PUSH_INTENT")
    if wanted:
        if wanted != "ci":
            _say(
                f"pre-push: DJB_PUSH_INTENT='{wanted}' ignored — the one intent this hook reads"
                " is 'ci'"
            )
        elif not to:
            _say(
                "pre-push: DJB_PUSH_INTENT=ci ignored — no ref is being pushed, so there is no"
                " train branch to vouch for"
            )
        else:
            intent = True
            for ref in to:
                if not (ref.startswith("refs/heads/pm/") and len(ref) > len("refs/heads/pm/")):
                    intent = False
                    _say(
                        f"pre-push: DJB_PUSH_INTENT=ci ignored — the push names {ref}, and an"
                        " intent vouches for refs/heads/pm/* only, never for main; the ordinary"
                        " lookup decides"
                    )
                    break
    seeding = MAIN in to and not held

    def through(word: str) -> None:
        if seeding:
            _say(MAIN_SEEDED)
        _wall(word, tree)

    try:
        if not to:
            _say("pre-push: no refs on stdin — consulting the verdict for the WORKING tree")
            if tree and ledger.consult(root, tree) is not None:
                through("honoured")
                _say(
                    f"pre-push: tree {tree} already measured green by a full gate run — verdict"
                    " honoured"
                )
                return 0
            reason = "no verdict for the working tree"
        else:
            unmeasured = [
                t for t in pushed if t == "UNRESOLVABLE" or ledger.consult(root, t) is None
            ]
            if not unmeasured:
                through("honoured")
                _say(
                    f"pre-push: every pushed tree ({' '.join(pushed)}) is measured green by a"
                    " full gate run — verdict honoured"
                )
                return 0
            if held and not box:
                _wall("main-refused", tree)
                for line in MAIN_REFUSED:
                    _err(line.format(unmeasured=" ".join(unmeasured)))
                return 2
            if any(t != tree for t in unmeasured):
                _wall("refused", tree)
                said = [
                    line.format(unmeasured=" ".join(unmeasured), tree=tree or "<unreadable>")
                    for line in FOREIGN
                ]
                for line in [*said[:3], *_differing(root, shas), *said[3:]]:
                    _err(line)
                return 1
            reason = "the pushed tree is this checkout's tree and has no verdict"
        if intent and ledger.intent_lookup(root, tree) is not None:
            through("ci-intent")
            _say(
                f"pre-push: unmeasured tree {tree} leaves for a TRAIN BRANCH ({' '.join(to)}) on"
                " a CI intent — the pull request's run is the measurement and --ci-verdict banks"
                " its row; no verdict is banked here"
            )
            return 0
    except ledger.Unreadable as exc:
        _wall("could-not-look", tree)
        _err(f"!! pre-push: REFUSED — the verdict ledger could not be read: {exc}")
        _err("   A wall that cannot read its ledger vouches for nothing; the push is refused.")
        return 2
    if intent:
        _say(
            "pre-push: DJB_PUSH_INTENT=ci declared and no fresh intent row names tree"
            f" {tree or '<unreadable>'} — measuring"
        )
    if box:
        through("box-exempt")
        _say(
            f"pre-push: unmeasured tree {tree or '<unreadable>'} leaves for a VERIFIER BOX — the"
            " box's own run is the measurement; no verdict is banked here"
        )
        return 0
    through("measuring")
    _say(f"pre-push: {reason} — running the full gate")
    djb_env.export("DJB_GATE_CALLER", "push-wall")
    os.execv(str(root / "scripts" / "check.sh"), ["./scripts/check.sh"])  # noqa: S606 — execs this checkout's own gate script, a fixed path


def run_hook(root: Path, modifiers: Sequence[str]) -> int:
    """`hook pre-push <remote> <url>`, `hook pre-commit` or `hook commit-msg <file>`."""
    if not modifiers or modifiers[0] not in HOOKS:
        print(
            f"!! hook: the hooks are {', '.join(HOOKS)}, not '{' '.join(modifiers)}'",
            file=sys.stderr,
        )
        return 2
    top = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False
    )
    if top.returncode != 0:
        exit_could_not_look(f"hook: not inside a checkout: {top.stderr.strip()}")
    checkout = Path(top.stdout.strip())
    if modifiers[0] != "pre-push":
        from quality.djb import boundary

        return boundary.main(list(modifiers), checkout)
    return pre_push(checkout, modifiers[1:], sys.stdin.read().splitlines())


HOOKS = ("pre-push", "pre-commit", "commit-msg")


MODES: tuple[Mode, ...] = (
    Mode("--fast", (), False, "the static legs a commit runs", run_fast),
    Mode(
        "--list-legs",
        ("--ci",),
        True,
        "the unit table; --ci adds the shard count and passes",
        run_list_legs,
    ),
    Mode("--census", (), True, "the instrument census alone", run_census),
    Mode("--help", (), True, "this table", run_help),
    Mode("hook", HOOKS, True, "the push wall, and the layer step at commit", run_hook, True),
)


def usage() -> str:
    """One line per mode, derived from `MODES`."""
    lines = ["usage: python -m quality.djb.cli <mode>"]
    for mode in MODES:
        flag = " ".join([mode.flag, *(f"[{m}]" for m in mode.modifiers)])
        lines.append(f"  {flag:<22} {mode.summary}")
    return "\n".join(lines)


def known() -> str:
    """The modes, as the unknown-argument refusal names them."""
    return ", ".join(" ".join([m.flag, *(f"[{x}]" for x in m.modifiers)]) for m in MODES)


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """Parse one mode and its modifiers, refuse anything else with exit 2, then run it."""
    args = list(sys.argv[1:] if argv is None else argv)
    word = args[0] if args else ""
    mode = next((m for m in MODES if m.flag == word), None)
    if mode is None:
        print(f"!! unknown argument '{word}': quality.djb.cli takes {known()}", file=sys.stderr)
        return 2
    extra = [a for a in args[1:] if a not in mode.modifiers]
    if not mode.operands and (extra or len(args[1:]) != len(set(args[1:]))):
        print(f"!! unexpected extra arguments: {' '.join(args[1:])}", file=sys.stderr)
        return 2
    if not mode.piped:
        refuse_if_piped(root)
    try:
        return mode.run(root, args[1:])
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))


if __name__ == "__main__":
    sys.exit(main())
