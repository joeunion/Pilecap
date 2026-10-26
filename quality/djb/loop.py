"""`--loop`: off-box refused, the scope derived once, the ledger consulted, the legs, one row."""

# Invariant: the off-box refusal comes before the lock, the scope, the key and any slot.
# does-not-cover: the loop-only legs' own bodies — `secrets`, `always-on`, `pytest` are legs.

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import cli, drawer, gate_args, hold, ledger, scope
from quality.djb import env as environment
from quality.djb import registry as R
from quality.djb.gate_args import Refusal, Request
from quality.djb.legs import loop_pytest
from quality.djb.legs._run import LIBRARIES
from quality.djb.modes import Clock, run_members

#: `gate_ledger.sh`'s state file a run's starting snapshot of the tree lives in.
SNAPSHOT = "djb-loop-snapshot"
#: The mode inputs the loop-only legs read, set once here from the one derivation.
SCOPE_INPUTS = (
    "GATE_LOOP_PYTEST_ARGS",
    "GATE_LOOP_MINE",
    "GATE_LOOP_REUSE_TREE",
    "GATE_LOOP_TOUCHED",
    "GATE_LOOP_CANONICAL",
)


def _say(*lines: str) -> None:
    for line in lines:
        print(line, flush=True)


def _err(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr, flush=True)


def shell(root: Path, script: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    """`script` in bash over the gate's libraries; its exit and its stdout, stderr passed on."""
    prelude = "".join(f". {lib} >/dev/null 2>&1 || exit 2\n" for lib in LIBRARIES)
    sys.stdout.flush()
    done = subprocess.run(
        ["bash", "-c", f"MODE=--loop\n{prelude}set +e\n{script}"],
        cwd=root,
        env={**environment.environ(), **(env or {})},
        stdout=subprocess.PIPE,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout


def box_marker() -> str | None:
    """The first verifier-box marker present on this machine, or `None`."""
    markers = (environment.read("DJB_GATE_BOX_MARKERS") or "").split()
    if not markers:
        markers = [environment.read("DJB_GATE_BOX_MARKER") or "/etc/djb/image-id"]
    return next((m for m in markers if os.path.exists(m)), None)


def box_held(root: Path, mine: bool) -> int | None:
    """Exit 0 with the box's row when a box banked this checkout's tree; else `None`."""
    if mine or environment.read("DJB_LOOP_NO_CACHE"):
        return None
    try:
        tree = ledger.measured_tree(root)
    except ledger.Mismatch:
        return None
    rc, row = shell(root, f'loop_ledger_tree_row "{tree}" box')
    row = row.strip()
    if rc or not row:
        return None
    words = row.split()
    box = next((w[4:] for w in words if w.startswith("box=")), "")
    _say(
        "ok: --loop VERDICT HELD BY A BOX — nothing was measured here, and nothing needed to be.",
        f"  tree   {tree}  (this checkout's measured tree)",
        f"  key    {words[1]}  (the box's: tree + the box image's environment + the scope it"
        " derived)",
        f"  box    {box}  banked {words[3]}",
        f"  banked {row}",
        "  A verifier box ran a complete green --loop over EXACTLY these bytes and",
        "  its row came home with the box's wait. This machine does not re-derive",
        "  the box's key (its environment is not the box's) and measures nothing.",
        "  Force a re-measure on a box: DJB_LOOP_NO_CACHE=1 through the recipe.",
    )
    return 0


def where(root: Path, req: Request) -> str:
    """Why this `--loop` may run here; off a box with no valve, `Refusal` or a box's row."""
    here = gate_args.loop_here(environment.environ(), box_marker(), req.here)
    if here is not None:
        return here
    held = box_held(root, req.mine)
    if held is not None:
        raise SystemExit(held)
    raise Refusal(gate_args.OFF_BOX_SAID)


def derive(root: Path, req: Request) -> scope.Scope:
    """The one scope derivation, its inputs read from the declared names."""
    base = environment.read("DJB_LOOP_SCOPE_BASE") or environment.read("SECRETS_SCAN_BASE_REF")
    scan = environment.read("DJB_LOOP_MAP_SCAN") or ""
    return scope.derive(
        root,
        base_ref=base or None,
        mine=req.mine,
        asked_impact=not req.mine,
        also=environment.read("DJB_LOOP_SCOPE_ALSO") or "",
        no_impact=bool(environment.read("DJB_LOOP_NO_IMPACT")),
        scan=int(scan) if scan.isdigit() else scope.MAP_SCAN,
    )


def mine_banner(where_: str, derived: scope.Scope) -> list[str]:
    """`--mine`'s two banners: what it narrowed when the run opens, why nothing banks at its end."""
    full = derived.mode == "full"
    if where_ == "open":
        head = (
            "  MINE: nothing was narrowed — the note above says why, and this run is the FULL suite"
            if full
            else "  MINE: the depends_on closure was NOT walked — a regression in a dependant"
            " surfaces at the ordinary --loop"
        )
        return [
            head,
            "  not banked: --mine",
            "              a --mine green is a claim about one app, and says so. The",
            "              ledger is neither consulted nor written on this run, so no",
            "              later gate can inherit this run's narrower question.",
        ]
    if full:
        return [
            "  not banked: --mine — the flag narrowed nothing here (the note above",
            "  says why), and a --mine run banks no verdict in any case. The",
            "  ordinary --loop is what banks the row a verifier consults.",
        ]
    return [
        "  not banked: --mine — the closure was not walked, so this green is a",
        f"  claim about [{' '.join(derived.own) or '-'}] and the always-on set, and about"
        " nothing else.",
        "  Run the ordinary --loop at your last boundary.",
    ]


class Keyed:
    """The run's key half: the measured tree, the key, the fingerprint, or why there is none."""

    def __init__(self, root: Path, derived: scope.Scope) -> None:
        self.tree = self.key = self.digest = self.parts = self.cannot = ""
        try:
            self.tree = ledger.measured_tree(root)
        except ledger.Mismatch:
            return
        try:
            fingerprint = scope.env_fingerprint(root, environment.read("DJB_LOOP_ENV_READS"))
            self.key = scope.loop_key(root, self.tree, derived)
        except CouldNotLook as exc:
            self.cannot = str(exc)
            return
        self.digest, self.parts = fingerprint.digest, fingerprint.components


def consult(root: Path, keyed: Keyed, derived: scope.Scope) -> int | None:
    """Exit 0 on a banked key; on a miss, the narrative and a docs-only reuse tree, or `None`."""
    path = ledger.ledger_path(root)
    row = ledger.last(path, "loop", keyed.key) if keyed.key else None
    if row is not None:
        _say(
            "ok: --loop VERDICT REUSED — nothing was re-measured.",
            f"  key    {keyed.key}",
            f"  tree   {keyed.tree}",
            f"  scope  {derived.canonical}",
            f"  banked {ledger.format(row)}",
            f"  env=   {keyed.digest or 'unstated'}",
            f"         {keyed.parts or 'unstated'}",
            "  A complete green --loop already measured THESE bytes, in THIS",
            "  environment, at THIS scope. The key is all three: the same tree at a",
            "  wider scope is a different key and gets no reuse.",
            "  This is a CACHE and never a security boundary. Force a",
            "  re-measure with DJB_LOOP_NO_CACHE=1.",
        )
        return 0
    return None


def miss(root: Path, keyed: Keyed, derived: scope.Scope) -> str:
    """The miss's token and narrative; the docs-only reuse's banked tree, or empty."""
    rc, why = shell(
        root,
        'loop_ledger_attribute "$T" "$E" "$S"',
        {
            "T": keyed.tree,
            "E": keyed.digest,
            "S": derived.canonical,
            "LOOP_ENV_COMPONENTS": keyed.parts,
        },
    )
    lines = why.rstrip("\n").split("\n") if why.strip() else ["unreadable"]
    token, detail = lines[0], lines[1:]
    _say(f"  == the --loop ledger was consulted and MISSED: miss({token}) ==")
    _say(f"  key         {keyed.key or '(none — the key could not be derived)'}")
    if environment.read("DJB_LOOP_VERBOSE"):
        _say(*(f"    {line}" for line in detail), f"  tree=       {keyed.tree}")
    elif token == "tree":  # noqa: S105 — a parsed argv word compared to a keyword, not a credential
        docs = next((ln for ln in detail if ln.startswith("since banked head")), "")
        _say(f"  {docs or 'since banked head: not derivable (the attributor said no such line)'}")
    if token != "tree":  # noqa: S105 — a parsed argv word compared to a keyword, not a credential
        return ""
    basis = next(
        (ln[len("reuse-basis: ") :] for ln in detail if ln.startswith("reuse-basis: ")), ""
    )
    reused = scope.loop_reuse(root, basis) if basis else scope.Reuse()
    if reused.tree:
        _say("  docs-only: the pytest pass of this miss is REUSABLE — see the pytest leg.")
    elif reused.why:
        _say(f"  {reused.why}")
    return reused.tree


def snapshot(root: Path) -> str:
    """This run's starting snapshot of the tree (`loop_tree_snapshot`), or empty when none."""
    git_dir = subprocess.run(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=root, capture_output=True, text=True
    ).stdout.strip()
    if not git_dir:
        return ""
    path = f"{git_dir}/{SNAPSHOT}"
    rc, _ = shell(root, 'loop_tree_snapshot "$P"', {"P": path})
    return path if rc == 0 else ""


def bank(
    root: Path, keyed: Keyed, derived: scope.Scope, snap: str, here: str, reuse: str, clock: Clock
) -> int:
    """The end of a green run: rewrites refused, the key re-derived, one `loop` row written."""
    if not snap:
        _err(
            "!! COULD NOT BANK — the run's starting snapshot of this tree could not be",
            "   taken or read back, so whether a leg rewrote a path the key reads is",
            "   unknown. No verdict banked (exit 2 — could-not-look, never a pass).",
        )
        return 2
    shell(root, 'loop_tree_mark_end "$P"', {"P": snap})
    rc, moved = shell(root, 'loop_tree_rewrites "$P" --arms', {"P": snap})
    if not rc:
        refused = "\n".join(ln.split("\t")[0] for ln in moved.splitlines() if ln.strip())
        shell(root, 'loop_tree_remember "$P" "$M"', {"P": snap, "M": refused})
    for suffix in ("", ".stamp", ".end"):
        Path(snap + suffix).unlink(missing_ok=True)
    if rc:
        return 2
    if moved.strip():
        shell(root, 'loop_tree_refusal "$M"', {"M": moved})
        return 2
    end = Keyed(root, derived)
    if end.cannot:
        _say(f"  no verdict banked — the key could not be derived: {end.cannot}")
        return 0
    if not end.key or end.key != keyed.key:
        _say(
            "  no verdict banked — the key did not re-derive to the same value at the",
            "  end of the run, so something moved while the gate ran. Nothing was",
            "  wrong with this run; it simply vouches for no single tree.",
        )
        return 0
    if "UNDECLARED" in derived.canonical:
        _err("loop: the always-on declaration could not be read — nothing recorded")
        return 2
    caller = ledger.caller_kind(environment.read("DJB_GATE_CALLER"), lambda line: None)
    fields = [
        f"caller={caller}",
        "scope=" + derived.canonical.replace("\n", "_").replace(" ", "_"),
        "passes=1",
        f"tree={end.tree}",
        f"env={end.digest or 'unstated'}",
        *end.parts.split(),
        "waited=0",
        f"took={clock.seconds.get('pytest', 0)}",
    ]
    if reuse:
        fields.append(f"reuse={reuse}")
    key_tree = ledger.loop_key_tree(root, end.tree)
    if key_tree != end.tree:
        fields.append(f"key-tree={key_tree}")
    try:
        ledger.append("loop", keyed.key, fields, path=ledger.ledger_path(root))
    except (ledger.Refused, OSError) as exc:
        _say(f"  no verdict banked — the ledger could not be written ({exc})")
        return 0
    _say(
        "  banked: this --loop verdict, keyed on tree + environment + scope.",
        f"          here={here}",
        f"          {keyed.key}",
        f"          tree={end.tree}",
        f"          env={end.digest}",
        f"          scope={derived.canonical}",
    )
    if reuse:
        _say(
            f"          loop: docs-only reuse of {reuse}",
            "          This row is itself reusable AND says what it rests on: the",
            "          pytest pass was not run here, it was inherited from that tree.",
        )
    _say(
        "          A later --loop on identical bytes at THIS scope reuses it;",
        "          a WIDER scope is a different key and re-measures.",
    )
    return 0


def run(root: Path, req: Request) -> int:
    """The per-rung gate: refusals, scope, consult, the loop legs, and the row."""
    here = where(root, req)
    cli.refuse_if_locked(root)
    _say(f"- loop here: {here}")
    try:
        derived = derive(root, req)
    except CouldNotLook as exc:
        _err(
            "!! --loop COULD NOT DERIVE ITS SCOPE — see above.",
            f"   cause: {exc}",
            "   Nothing was judged: no slot was taken, no leg ran.",
        )
        return 2
    _say(*scope.banner(derived))
    if req.mine:
        _say(*mine_banner("open", derived))
    if not environment.read("DJB_GATE_LEGS_DRY"):
        shell(root, "loop_env_sync")
    snap = snapshot(root)
    try:
        return _measure(root, req, derived, snap, here)
    finally:
        if snap:
            shell(root, 'loop_tree_mark_end "$P"', {"P": snap})


def _measure(root: Path, req: Request, derived: scope.Scope, snap: str, here: str) -> int:
    """From the key to the row; every exit of it leaves the snapshot's end mark (`run`)."""
    cached = not req.mine and not environment.read("DJB_LOOP_NO_CACHE")
    keyed = Keyed(root, derived) if cached else None
    reuse = ""
    if keyed is not None and keyed.cannot:
        _say(f"  == the --loop key could not be derived: {keyed.cannot} ==")
    elif keyed is not None:
        hit = consult(root, keyed, derived)
        if hit is not None:
            return hit
        reuse = miss(root, keyed, derived)
    elif req.mine:
        _say("  == the --loop ledger was NOT consulted: --mine ==")
    else:
        _say(
            "  == the --loop ledger was NOT consulted: DJB_LOOP_NO_CACHE is set ==",
            "  This run measures, and it will not bank.",
        )
    try:
        taken = hold.hold("host", on_contention="wait", mode="loop")
    except hold.Refused:
        return 2
    try:
        return _legs(root, req, derived, snap, here, keyed, reuse)
    finally:
        if taken is not None:
            taken.release()


def _legs(
    root: Path,
    req: Request,
    derived: scope.Scope,
    snap: str,
    here: str,
    keyed: Keyed | None,
    reuse: str,
) -> int:
    table = cli.table(root)
    inputs = {
        "GATE_LOOP_PYTEST_ARGS": " ".join(loop_pytest.tier_args(derived)),
        "GATE_LOOP_MINE": "1" if req.mine else "",
        "GATE_LOOP_REUSE_TREE": reuse,
        "GATE_LOOP_TOUCHED": " ".join(scope.touched(root, derived.changed)),
        "GATE_LOOP_CANONICAL": derived.canonical,
    }
    ctx = R.Ctx(root, "loop", {**environment.environ(), **inputs})
    clock = Clock()
    rc = run_members(table, [g.name for g in table.mode_legs("loop")], ctx, clock)
    if rc:
        return rc
    if R.local_tier(table.local, "loop"):
        _say("- local-legs: the product's own legs, tier loop and below")
        changed = environment.read("DJB_LOCAL_LEGS_CHANGED_FILES")
        rc = drawer.run(
            table,
            "loop",
            ctx.env,
            narrowed=True,
            changed=changed.split() if changed is not None else derived.changed,
        )
        if rc:
            return rc
    _say(f"ok: --loop checks passed ({clock.wall()}s)")
    if environment.read("DJB_GATE_LEGS_DRY") and not req.mine:
        _say("  no verdict banked — DJB_GATE_LEGS_DRY: every leg was announced and none ran")
        return 0
    if keyed is not None and keyed.key and not keyed.cannot:
        return bank(root, keyed, derived, snap, here, reuse, clock)
    if req.mine:
        _say(*mine_banner("close", derived))
    return 0
