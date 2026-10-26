"""The gate's argument grammar and its pre-run refusals, in `check.sh`'s own sentences."""

# Invariant: stdlib only; every refusal is exit 2 before a lease, a lock, a slot or a leg.
# does-not-cover: whether a sanction's reason is true — the typed line is the owner's authority.

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.reason_floor import MIN_REASON

#: Every mode word the gate takes, as the unknown-argument refusal names them.
UNKNOWN = (
    "!! unknown argument '{word}': check.sh takes nothing, --fast, --loop, --loop --mine, "
    "--census, --list-legs, --leg <unit>, --store-durations, --bank, or --pr --base <sha>"
)
NOTHING = "   Nothing was judged: no lease was taken, no slot, no leg was run."
STORE_AT_FULL = (
    "!! --store-durations without --leg measures the WHOLE gate, so it belongs to",
    "   the full mode: ./scripts/check.sh --store-durations",
    "   Under a unit it is the suite's own timing flag: "
    "./scripts/check.sh --leg pytest-x2 --store-durations",
)
MINE_ELSEWHERE = "!! --mine narrows --loop and nothing else: ./scripts/check.sh --loop --mine"
HERE_ELSEWHERE = (
    "!! --here says why a --loop runs on this machine, and nothing else: "
    './scripts/check.sh --loop --here "<rung-id>: <reason>"'
)
HERE_NO_REASON = (
    '!! --here needs its reason: ./scripts/check.sh --loop --here "<rung-id>: <reason>"',
    "   Nothing was judged.",
)
PR_NO_BASE = (
    "!! --pr needs --base <sha>: the commit the proposed change forks from.",
    "   Without it there is no diff to take, and this gate does not guess one:",
    "       ./scripts/check.sh --pr --base <sha>",
    NOTHING,
)
PR_UNRESOLVED = (
    "!! --pr --base '{base}': git cannot resolve that to a commit here.",
    "   An impact map cannot be computed from a base this checkout does not have,",
    "   and a base it cannot see is never a reason to run less.",
    NOTHING,
)
PR_NOT_ANCESTOR = (
    "!! --pr --base '{base}' is NOT an ancestor of HEAD.",
    "   base: {sha}",
    "   HEAD: {head}",
    "   The changed set is <base>...HEAD, which from a non-ancestor is taken at a",
    "   merge-base nobody named — a smaller and different set than the one the",
    "   caller asked about. Rebase, or name the base this branch actually forks",
    "   from.",
    NOTHING,
)
PR_DIRTY = (
    "!! --pr refuses a DIRTY TREE.",
    "   The proposed change is <base>...HEAD — commits. An uncommitted file is in",
    "   neither half of it, so it would be graded by a run whose banner names a",
    "   commit range it is not in. Commit it, or stash it, and ask again.",
)
UNSANCTIONED = (
    "!! REFUSING an unsanctioned FULL gate.",
    "   A full run is the most expensive thing on this machine — two whole-suite",
    "   passes, a real Meilisearch, MinIO and Temporal — and every other full gate",
    "   on the box waits behind it. So it needs a reason that outlives the run.",
    "   ONE of these, and they are the whole list:",
    "     * the pre-push hook (it sets DJB_GATE_CALLER=push-wall for itself)",
    "     * ./scripts/check.sh --bank   from the primary checkout or pm-push",
    '     * DJB_GATE_SANCTION="<rung-id>: <reason>" ./scripts/check.sh',
    "   The per-rung gate is ./scripts/check.sh --loop and is untouched by this.",
    NOTHING,
)
BANK_NO_GIT = (
    "!! --bank could not ask git which checkout this is.",
    "   The flag is legal from the primary checkout or from pm-push and nowhere",
    "   else, and a test that could not run has cleared nothing. Nothing was judged.",
)
BANK_LINKED = (
    "!! --bank from a LINKED worktree: {top}",
    "   git-dir:        {git_dir}",
    "   git-common-dir: {common}",
    "   HEAD:           {head}",
    "   They differ, so this is not the primary checkout — and it is not the",
    "   '{push}' worktree either, which is DETACHED (pm_push.sh pins it that way on",
    "   every push) and named that. A worktree sitting on a branch is a rung",
    "   worktree whatever its directory is called.",
    "   A bank is a claim about the tree that is about to be",
    "   pushed; a rung worktree is by construction not that tree.",
    "   If you MEANT to run the full gate here — a quality/** or dependency rung,",
    "   where it uniquely binds — say why:",
    '       DJB_GATE_SANCTION="<rung-id>: <reason>" ./scripts/check.sh',
    "   Nothing was judged.",
)
LOOP_HERE_SHAPE = (
    "!! DJB_LOOP_HERE is set but is not a reason.",
    "   got:  {got}",
    '   want: DJB_LOOP_HERE="<rung-id>: <reason>"',
    '         e.g. DJB_LOOP_HERE="x-1: no AWS credentials in this session"',
    "   A valve that does not name who is asking and why is not a reason.",
    "   Nothing was judged.",
)
OFF_BOX = (
    "!! REFUSING a --loop on a machine that is not a verifier box.",
    "   The per-rung gate is the loop's highest-volume run and this box carries",
    "   every one of them at once. A member measured at 3 s on a quiet machine",
    "   took 83 s here under five lanes; the boxes were built for this.",
    "   THE RECIPE, from this worktree, each command's output to its own file:",
    "       ./scripts/verifier_box.sh up --for <rung>",
    "       ./scripts/verifier_box.sh loop <id> --log loop-<rung>",
    "       ./scripts/verifier_box.sh wait <id> loop-<rung>",
    "       ./scripts/verifier_box.sh down <id>     # always, before you report",
    "   IF IT HAS TO RUN HERE — no credentials, a network that is down, a rung",
    "   about this laptop — say who and why:",
    '       DJB_LOOP_HERE="<rung-id>: <reason>" ./scripts/check.sh --loop',
    "   The reason prints in this run's banner and beside its banked verdict.",
    "   --fast (the pre-commit hook) and --census are untouched by this.",
    NOTHING,
)
LOOP_HERE_FLAG_SHAPE = (
    "!! --here is given but is not a reason.",
    "   got:  {got}",
    '   want: ./scripts/check.sh --loop --here "<rung-id>: <reason>"',
    '         e.g. --here "x-1: no AWS credentials in this session"',
    *LOOP_HERE_SHAPE[-2:],
)
#: The refusal as the gate says it: the shell era's bytes, the valve a flag, the product's road.
OFF_BOX_SAID = (
    *OFF_BOX[:-4],
    '       ./scripts/check.sh --loop --here "<rung-id>: <reason>"',
    "   (DJB_LOOP_HERE in the environment is the same valve; the flag wins over it.)",
    OFF_BOX[-3],
    "   On a product's road: docs/sdk/the-one-path.md gives the laptop's form.",
    *OFF_BOX[-2:],
)
LEG_NO_UNIT = (
    "!! --leg needs a unit: ./scripts/check.sh --leg <unit>",
    "   The units are the gate's own and ./scripts/check.sh --list-legs is what",
    "   names them. Nothing was judged.",
)
LEG_UNKNOWN = (
    "!! --leg '{unit}': no such unit.",
    "   The units are the gate's own, and ./scripts/check.sh --list-legs is what",
    "   names them — never a list typed into a runner:",
)
SHARD_INDIVISIBLE = (
    "!! --leg {unit} --shard {shard}: that unit is indivisible (shards: {shards}).",
    "   ./scripts/check.sh --list-legs carries the shards field of every unit and",
    "   only an N-capable one takes a k/N.",
    NOTHING,
)
SHARD_SHAPE = (
    "!! --shard '{shard}' is not a k/N pair of integers.",
    "   The form is 1-based, as the listing's grammar is: --shard 1/3 is the",
    "   first of three. A pair this gate cannot parse is never a smaller run.",
    "   Nothing was judged.",
)
SHARD_RANGE = (
    "!! --shard {shard} is outside 1..{n} of {n}.",
    "   Every k in 1..N runs a part and the N parts are the whole; a k outside",
    "   that range names a part of the unit that does not exist.",
    "   Nothing was judged.",
)
PASSES_SHAPE = (
    "!! --passes '{passes}': the suite leg runs 1 or 2 whole passes.",
    "   2 is the default and the belt: pass 2 proves the suite left nothing",
    "   behind for itself. 1 drops it, and is legal only on a shard whose",
    "   proof runs elsewhere. A count this gate cannot parse is never a run.",
    NOTHING,
)
PASSES_NO_SUITE = (
    "!! --passes 1 on unit '{unit}': that unit runs no suite.",
    "   The pass count is the suite leg's own, and a unit with no suite has",
    "   no passes to drop one of.",
    NOTHING,
)
PASSES_AND_STORE = (
    "!! --passes 1 with --store-durations: two ways to say pass 2 is not run.",
    "   A measurement run already stops after pass 1, and it vouches for",
    "   nothing; --passes 1 is a VERDICT over one pass whose belt runs on",
    "   another box. One argv cannot be both.",
    "   Nothing was judged.",
)
PASSES_NO_SHARD = (
    "!! --passes 1 without --shard: the whole-suite two-pass belt is this unit's own;",
    "   one pass is legal only for a shard whose proof runs elsewhere.",
    "   Under ./scripts/pm_push.sh --bank --on-boxes N that elsewhere is the",
    "   acceptance box's whole-suite two passes under one seed, composed into the",
    "   verdict row's leak-proof= field; a whole unit asking for one pass is",
    "   asking to drop the belt and name no replacement.",
    NOTHING,
)
STORE_NO_SUITE = (
    "!! --store-durations on unit '{unit}': that unit runs no suite.",
    "   The durations file is what the pytest split balances by, and only the",
    "   unit that runs the suite can measure it.",
)
STORE_ON_SHARD = (
    "!! --store-durations with --shard {shard}: a shard times a PART of the suite.",
    "   Writing that file from one shard would describe 1/{n} of the",
    "   collection as if it were all of it, and the next split would balance by it.",
    "   Nothing was judged.",
)
#: The suite unit: the one that runs pytest, takes `--passes` and `--store-durations`.
SUITE = "pytest-x2"
_SANCTION_SHAPE = re.compile(r"^[^:]+: .+$")
_SHARD = re.compile(r"^([0-9]+)/([0-9]+)$")


class Refusal(CouldNotLook):
    """An argv or a context the gate refuses before judging anything; the lines go to stderr."""

    def __init__(self, lines: Sequence[str], code: int = 2) -> None:
        super().__init__("\n".join(lines))
        self.lines = tuple(lines)
        self.code = code


@dataclass(frozen=True)
class Request:
    """One parsed invocation: the mode (`""` is full) and every modifier, as `check.sh` set them."""

    mode: str = ""
    bank: bool = False
    pr: bool = False
    pr_base: str = ""
    census: bool = False
    list_legs: bool = False
    list_ci: bool = False
    unit: str = ""
    shard: str = ""
    shard_given: bool = False
    passes: str = ""
    passes_given: bool = False
    store_durations: bool = False
    store_members: bool = False
    mine: bool = False
    here: str = ""


def parse(argv: Sequence[str]) -> Request:
    """`check.sh`'s two `case` blocks and its modifier loop; a mistyped word is `Refusal`."""
    args = list(argv)
    word = args[0] if args else ""
    req = Request()
    if word == "--here" or word.startswith("--here="):
        raise Refusal([HERE_ELSEWHERE])
    if word in ("", "--fast", "--loop"):
        req = replace(req, mode=word)
    elif word == "--bank":
        req = replace(req, bank=True)
    elif word == "--pr":
        req = replace(req, pr=True)
    elif word == "--store-durations":
        req = replace(req, store_members=True)
    elif word == "--census":
        req = replace(req, mode=word, census=True)
    elif word == "--list-legs":
        req = replace(req, mode=word, list_legs=True)
        if len(args) > 1 and args[1] == "--ci":
            req = replace(req, list_ci=True)
            del args[1]
    elif word == "--leg":
        req = replace(req, mode=word, unit=args[1] if len(args) > 1 else "")
        del args[1:2]
    else:
        raise Refusal([UNKNOWN.format(word=word)])
    del args[:1]
    if req.mode == "--leg":
        while args:
            head = args[0]
            if head == "--shard" or head.startswith("--shard="):
                value = args[1] if head == "--shard" and len(args) > 1 else head[8:]
                del args[: 2 if head == "--shard" else 1]
                req = replace(req, shard=value, shard_given=True)
            elif head == "--passes" or head.startswith("--passes="):
                value = args[1] if head == "--passes" and len(args) > 1 else head[9:]
                del args[: 2 if head == "--passes" else 1]
                req = replace(req, passes=value, passes_given=True)
            elif head == "--store-durations":
                del args[0]
                req = replace(req, store_durations=True)
            elif head == "--pr":
                del args[0]
                req = replace(req, pr=True)
            else:
                break
    if req.pr and args:
        head = args[0]
        if head == "--base":
            req = replace(req, pr_base=args[1] if len(args) > 1 else "")
            del args[:2]
        elif head.startswith("--base="):
            req = replace(req, pr_base=head[7:])
            del args[0]
    if req.mode == "--loop":
        req, args = _loop_modifiers(req, args)
    elif any(a == "--here" or a.startswith("--here=") for a in args):
        raise Refusal([HERE_ELSEWHERE])
    if args and args[0] == "--store-durations":
        if req.mode:
            raise Refusal(STORE_AT_FULL)
        req = replace(req, store_members=True)
        del args[0]
    elif args and args[0] == "--mine":
        if req.mode != "--loop":
            raise Refusal([MINE_ELSEWHERE])
        req = replace(req, mine=True)
        del args[0]
    if args:
        raise Refusal([f"!! unexpected extra arguments: {' '.join(args)}"])
    return req


def _loop_modifiers(req: Request, args: list[str]) -> tuple[Request, list[str]]:
    """`--loop`'s `--mine` and `--here <reason>`, in either order; the rest is the caller's."""
    while args:
        head = args[0]
        if head == "--mine":
            req = replace(req, mine=True)
            del args[0]
        elif head == "--here":
            if len(args) < 2 or args[1].startswith("--"):
                raise Refusal(HERE_NO_REASON)
            req = replace(req, here=args[1])
            del args[:2]
        elif head.startswith("--here="):
            req = replace(req, here=head[7:])
            del args[0]
        else:
            break
    return req, args


def _git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)


def check_pr_base(root: Path, req: Request, dirt: Sequence[str] = ()) -> str:
    """The `--pr --base` commit; refused when absent, unknown, not an ancestor, or dirty."""
    if not req.pr:
        return ""
    if not req.pr_base:
        raise Refusal(PR_NO_BASE)
    sha = _git(root, "rev-parse", "-q", "--verify", f"{req.pr_base}^{{commit}}").stdout.strip()
    if not sha:
        raise Refusal([line.format(base=req.pr_base) for line in PR_UNRESOLVED])
    if _git(root, "merge-base", "--is-ancestor", sha, "HEAD").returncode != 0:
        head = _git(root, "rev-parse", "HEAD").stdout.strip() or "(unreadable)"
        raise Refusal(
            [line.format(base=req.pr_base, sha=sha, head=head) for line in PR_NOT_ANCESTOR]
        )
    if dirt:
        raise Refusal([*PR_DIRTY, *(f"     {d}" for d in dirt), NOTHING])
    return sha


@dataclass(frozen=True)
class Sanctioned:
    """Who sanctioned a full run: the banner's words and the row's `kind`/`who`/`why`."""

    said: str
    kind: str
    who: str
    why: str


def sanction(root: Path, req: Request, env: Mapping[str, str]) -> Sanctioned | None:
    """The full gate's sanction in `check.sh`'s order; `None` outside the full mode."""
    if req.mode:
        return None
    typed = env.get("DJB_GATE_SANCTION", "")
    if env.get("CI"):
        why = "exempt, as at the pipe guard"
        return Sanctioned(f"CI ({why})", "ci", "CI", why)
    if env.get("DJB_GATE_CALLER") == "push-wall":
        return Sanctioned(
            "the push wall (DJB_GATE_CALLER=push-wall)",
            "push-wall",
            "pre-push",
            "DJB_GATE_CALLER=push-wall",
        )
    if typed:
        who, _, why = typed.partition(":")
        return Sanctioned(f"DJB_GATE_SANCTION={typed}", "typed", who, why[1:])
    if req.bank:
        return bank_sanction(root, env)
    raise Refusal(UNSANCTIONED)


def bank_sanction(root: Path, env: Mapping[str, str]) -> Sanctioned:
    """`--bank`'s checkout rule: the primary checkout, or the detached `pm-push` worktree."""
    git_dir = _git(root, "rev-parse", "--git-dir").stdout.strip()
    common = _git(root, "rev-parse", "--git-common-dir").stdout.strip()
    top = _git(root, "rev-parse", "--show-toplevel").stdout.strip()
    if not git_dir or not common:
        raise Refusal(BANK_NO_GIT)
    push = env.get("DJB_PUSH_WORKTREE") or "pm-push"
    detached = _git(root, "symbolic-ref", "-q", "HEAD").returncode != 0
    if os.path.samefile(root / git_dir, root / common):
        said = f"--bank from the PRIMARY checkout ({top})"
        return Sanctioned(said, "bank", "check.sh", said)
    if Path(top).name == push and detached:
        said = f"--bank from the {push} worktree, detached ({top})"
        return Sanctioned(said, "bank", "check.sh", said)
    head = _git(root, "symbolic-ref", "-q", "HEAD").stdout.strip() or "(detached)"
    raise Refusal(
        [
            line.format(top=top or root, git_dir=git_dir, common=common, head=head, push=push)
            for line in BANK_LINKED
        ]
    )


def sanction_shape(env: Mapping[str, str]) -> None:
    """A set `DJB_GATE_SANCTION` must be `<who>: <why>` (the ledger's `gate_sanction_typed`)."""
    typed = env.get("DJB_GATE_SANCTION", "")
    if typed and not _SANCTION_SHAPE.match(typed):
        raise Refusal(
            [
                "!! DJB_GATE_SANCTION is set but is not a sanction.",
                f"   got:  {typed}",
                '   want: DJB_GATE_SANCTION="<rung-id>: <reason>"',
                '         e.g. DJB_GATE_SANCTION="gate-rung: quality/** rung — the canary '
                'self-test is the point"',
                "   A sanction that does not name who is asking and why is not a reason, and",
                "   a full gate is not run on one. Nothing was judged.",
            ]
        )
    if typed:
        sanction_floor(typed.split(":", 1)[0], typed.split(": ", 1)[1])


def sanction_floor(who: str, why: str) -> None:
    """A typed sanction's who and reason as `gate_sanction_set` judges them, above the lease."""
    if not who or ":" in who or "\n" in who:
        raise Refusal(
            [
                f"!! a sanction's who ('{who}') is empty or holds a colon or a newline — it is the",
                "   field the reason is split from. Nothing was judged.",
            ]
        )
    if "\n" in why:
        raise Refusal(
            ["!! a sanction's reason holds a newline — one row is one line. Nothing was judged."]
        )
    if len(why) < MIN_REASON:
        raise Refusal(
            [
                f"!! the sanction's reason is {len(why)} character(s): '{why}'.",
                f"   A typed sanction's reason is at least {MIN_REASON} characters — the valves' "
                "floor",
                "   (quality/reason_floor.py MIN_REASON): long enough to force a clause. Nothing "
                "was judged.",
            ]
        )


def loop_here(env: Mapping[str, str], box_marker: str | None, flag: str = "") -> str | None:
    """Why a `--loop` may run on this machine, or `None` (the caller then tries the box's row)."""
    typed = env.get("DJB_LOOP_HERE", "")
    valve, shape = (flag, LOOP_HERE_FLAG_SHAPE) if flag else (typed, LOOP_HERE_SHAPE)
    if valve and not _SANCTION_SHAPE.match(valve):
        raise Refusal([line.format(got=valve) for line in shape])
    if box_marker:
        return f"a verifier box ({box_marker})"
    if env.get("CI"):
        return "CI (exempt, as at the pipe guard and the full-gate sanction)"
    if flag:
        return f"--here {flag}" + (f" (the flag wins over DJB_LOOP_HERE={typed})" if typed else "")
    if valve:
        return f"DJB_LOOP_HERE={valve}"
    return None


@dataclass(frozen=True)
class UnitRun:
    """A validated `--leg` run: the unit's row, its shard pair and its pass count."""

    unit: str
    needs: str
    shards: str
    members: tuple[str, ...]
    k: int = 0
    n: int = 0
    passes: str = ""


def check_unit(req: Request, listing: str) -> UnitRun:
    """`--leg`'s validation against the `--list-legs` table; every refusal `check.sh` prints."""
    if not req.unit:
        raise Refusal(LEG_NO_UNIT)
    rows = {cols[0]: cols for cols in (ln.split("\t") for ln in listing.splitlines()) if cols[0]}
    if req.unit not in rows:
        raise Refusal(
            [
                *(line.format(unit=req.unit) for line in LEG_UNKNOWN),
                *(f"     {name}" for name in rows),
                NOTHING,
            ]
        )
    _, needs, shards, members = rows[req.unit][:4]
    legs = tuple(members.split(","))
    k = n = 0
    if req.shard_given:
        if shards != "N-capable":
            raise Refusal(
                [
                    ln.format(unit=req.unit, shard=req.shard, shards=shards)
                    for ln in SHARD_INDIVISIBLE
                ]
            )
        pair = _SHARD.match(req.shard)
        if not pair:
            raise Refusal([ln.format(shard=req.shard) for ln in SHARD_SHAPE])
        k, n = int(pair.group(1)), int(pair.group(2))
        if n < 1 or k < 1 or k > n:
            raise Refusal([ln.format(shard=req.shard, n=n) for ln in SHARD_RANGE])
    passes = req.passes
    if req.passes_given:
        if passes not in ("1", "2"):
            raise Refusal([ln.format(passes=passes) for ln in PASSES_SHAPE])
        if passes == "1":
            if SUITE not in legs:
                raise Refusal([ln.format(unit=req.unit) for ln in PASSES_NO_SUITE])
            if req.store_durations:
                raise Refusal(PASSES_AND_STORE)
            if not req.shard:
                raise Refusal(PASSES_NO_SHARD)
        if passes == "2":
            passes = ""
    if req.store_durations:
        if SUITE not in legs:
            raise Refusal([ln.format(unit=req.unit) for ln in STORE_NO_SUITE])
        if req.shard:
            raise Refusal([ln.format(shard=req.shard, n=n) for ln in STORE_ON_SHARD])
    return UnitRun(req.unit, needs, shards, legs, k, n, passes)


def unit_banner(req: Request, run: UnitRun) -> list[str]:
    """The five lines a `--leg` run opens with, `check.sh`'s words."""
    shown = [f"{m}/1" if m == SUITE and run.passes == "1" else m for m in run.members]
    head = f"- --leg {run.unit}"
    if req.shard:
        head += f" --shard {req.shard}"
    if run.passes:
        head += f" --passes {run.passes}"
    return [
        head,
        f"  needs:       {run.needs} (a DECLARATION — the gate refuses at the leg, never here)",
        f"  shards:      {run.shards}",
        f"  composed-of: {','.join(shown)}",
        "  This run takes NO machine lease, NO checkout lock and records NO verdict:",
        "  one unit of the gate vouches for no tree.",
    ]
