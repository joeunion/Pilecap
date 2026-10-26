"""The loop-only `pytest` leg: one pass of the scope's tier in one slot, reconciled or refused."""

# does-not-cover: the pass's heartbeat and its measured nominal's pacing — the nominal is printed.
# does-not-cover: banking — the `--loop` mode keys, consults and banks around this leg.

from __future__ import annotations

import filecmp
import os
import shutil
import tempfile
from collections.abc import Sequence
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import hold, ledger, scope
from quality.djb.legs import gate_tests
from quality.djb.legs._run import say, tool
from quality.djb.registry import Ctx, Leg

TEST_SH = "./scripts/test.sh"
ARGV = ((TEST_SH, "-n", "<slot workers>"),)
#: The mode's one derivation handed down: the door's flags, `--mine`, the reuse, the scope.
ARGS = "GATE_LOOP_PYTEST_ARGS"
MINE = "GATE_LOOP_MINE"
REUSE_TREE = "GATE_LOOP_REUSE_TREE"
CANONICAL = "GATE_LOOP_CANONICAL"
#: Where `apps/conftest.py` writes a collection refusal.
REFUSAL_FILE = "DJB_LOOP_REFUSAL_FILE"
_COUNTED = ("--djb-scope-narrow", "--djb-impact-select=")
_NOT_RUN = (3, 4, 5)


def derive(ctx: Ctx) -> scope.Scope:
    """The active rung's scope when no mode handed one down, as `--loop` derives it."""
    mine = bool(ctx.env.get(MINE))
    scan = ctx.env.get("DJB_LOOP_MAP_SCAN", "")
    return scope.derive(
        ctx.root,
        carried=ctx.env.get("DJB_LOOP_SCOPE_BASE") or None,
        mine=mine,
        asked_impact=not mine,
        also=ctx.env.get("DJB_LOOP_SCOPE_ALSO", ""),
        no_impact=bool(ctx.env.get("DJB_LOOP_NO_IMPACT")),
        scan=int(scan) if scan.isdigit() else scope.MAP_SCAN,
    )


def tier_args(found: scope.Scope) -> list[str]:
    """The pytest door's flags for `found`, the counts dir aside; `[]` runs the whole suite."""
    if found.product is not None:
        return list(found.product)
    if found.mode == "full":
        return []
    out = ["--djb-tier=fast"]
    out += [f"--djb-own-app={label}" for label in found.own]
    out += [f"--djb-tests-only={label}" for label in found.tests_only]
    out += [f"--djb-changed-test={p}" for p in (*found.changed_tests, *found.seeded_tests)]
    if found.asked_impact:
        out += [f"--djb-changed={p}" for p in found.changed]
    if found.impact.select:
        out.append(f"--djb-impact-select={found.impact.select}")
    elif found.narrow:
        out += [f"--djb-scope={label}" for label in found.apps]
        out.append("--djb-scope-narrow")
    return out


def counted(args: Sequence[str]) -> bool:
    """Whether the run asks its collectors to write their counts: a narrowed or mapped scope."""
    return any(a.startswith(_COUNTED) for a in args) and not any(
        a.startswith("--djb-scope-counts=") for a in args
    )


def canonical(text: str) -> dict[str, str]:
    """The canonical scope's fields by name (`mode=… own=… scope=…`), each value its words."""
    fields: dict[str, str] = {}
    name = ""
    for word in text.split():
        head, eq, value = word.partition("=")
        if eq and head in ledger.SCOPE_FIELDS:
            name = head
            fields[name] = value
        elif name:
            fields[name] += f" {word}"
    return fields


def _last_took(root: Path) -> list[str]:
    """This checkout's `loop` ledger rows, for the nominal's measured half."""
    try:
        path = ledger.ledger_path(root)
    except ledger.Refused:
        return []
    return [line for _, line in ledger.rows(path) if line.split(" ")[2:3] == ["loop"]]


def preamble(ctx: Ctx, found: scope.Scope | None, taken: hold.Hold, workers: int) -> int:
    """The tier (when derived here), the censuses, the workers and the nominal; 2 on a doubt."""
    if found is not None:
        print(f"  tier basis: {found.basis}")
        print(f"  tier rule:  {found.reason}")
        if found.mode == "full":
            print(
                "  shared test infrastructure the active rung changed: "
                f"{' '.join(found.shared_hits)}"
            )
            print("  (the enumeration and why each member is in it: quality/djb/scope.py)")
    try:
        censuses = scope.declared_censuses(ctx.root, "apps")
    except CouldNotLook as exc:
        say(
            f"!! {exc}",
            "!! the --loop scope COULD NOT READ the declared cross-app censuses — see",
            "   above. Nothing was judged about this tree: a marked module this could",
            "   not read is one the scope would deselect as if it had declared nothing.",
        )
        return 2
    if not censuses:
        print("  always-on censuses (declared): (none declared)")
    for module, reason in censuses:
        print(f"  always-on censuses (declared): {module} — {reason}")
    print(f"  workers:    -n {workers} ({taken.phrase or 'this slot’s share'})")
    print("              NOT -n auto: auto is every core, and it is every core in each of")
    print(
        f"              the {taken.total} gates that may be running. Override the slot count with"
    )
    print("              DJB_GATE_SLOTS.", flush=True)
    hold.nominal(hold.NOMINAL_LOOP, "NOMINAL_LOOP", _last_took(ctx.root))
    return 0


def _lines(path: str) -> list[str]:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def graded(ctx: Ctx, found: scope.Scope | None) -> list[str]:
    """The scope the rung was graded at: from the derivation, else the handed-down canonical."""
    if found is not None:
        return [
            f"  basis:      {found.basis}",
            f"  scope:      {' '.join(found.apps) or '(empty — no app is in scope)'}",
            f"  touched:    {' '.join(found.touched) or '-'}",
            f"  tests-only: {' '.join(found.tests_only) or '-'} (no closure walked; the edited "
            f"modules: {' '.join(found.changed_tests) or '-'})",
            "  widened by the reverse-transitive depends_on closure: "
            f"{' '.join(found.widened) or '-'}",
            f"  shapes:     {' '.join(found.shapes) or '-'}",
            *(
                line
                for line in scope.banner(found)
                if line.startswith(("  scope   map:", "  scope   impact:", "          "))
            ),
        ]
    fields = canonical(ctx.env.get(CANONICAL, ""))
    apps = fields.get("scope", "-")
    return [
        "  basis:      the scope block above (this leg was handed the canonical scope)",
        f"  scope:      {'(empty — no app is in scope)' if apps == '-' else apps}",
        f"  touched:    {fields.get('own', '-')}",
        f"  tests-only: {fields.get('tests', '-')}",
        f"  seeded:     {fields.get('seeded', '-')}",
        f"  scope   map: sha={fields.get('map', '-')}",
    ]


def reconcile(ctx: Ctx, found: scope.Scope | None, counts_dir: str, workers: int) -> int:
    """The collectors' counts compared, never summed, and the graded scope printed; 0 or 2."""
    files = sorted(str(p) for p in Path(counts_dir).rglob("*") if p.is_file())
    if not files:
        say(
            "!! the --loop scope banner has NO counts file to read: not one collector",
            f"   wrote into {counts_dir}. The scope was asked for and nothing",
            "   reported deriving it, so what ran is unknown.",
        )
        return 2
    first = files[0]
    for other in files[1:]:
        if not filecmp.cmp(first, other, shallow=False):
            say("!! THE COLLECTORS DISAGREE ABOUT THE SCOPE.")
            for path in (first, other):
                say(f"   {Path(path).name}:", *(f"     {x}" for x in _lines(path)))
            say(
                "   Every collector performs its own FULL collection, so these must",
                "   be identical. They are not, so this run did not measure one",
                "   thing and no verdict is banked.",
            )
            return 2
    expected = workers
    for line in _lines(first):
        if line.startswith("workers="):
            value = line.split("=", 1)[1]
            expected = int(value) if value.isdigit() and int(value) >= 1 else expected
            break
    if expected > 0 and len(files) < expected:
        say(
            f"!! {len(files)} of {expected} collectors reported — a collector died and the suite "
            f"that ran is not the suite that was asked for; nothing is judged",
            "   Every collector performs its own FULL collection and writes its counts, so",
            "   a missing file is a collector that never got to the end of collecting.",
            "   pytest can still exit 0 from that state (it runs what the survivors hold,",
            "   and 'no tests ran' is not a failure), which is why this is a refusal here",
            "   and not a note beside a green verdict. No verdict is banked.",
        )
        print(f"  the pre-run banner did not fire ({len(files)} of {expected} collectors reported)")
        print("  It prints only once every collector has reported its counts, so a worker")
        print("  that died during collection takes it with it. The counts below are the")
        print("  survivors', and this line is an absence NAMED, not a verdict of its own —")
        print("  the verdict for a short collection is the shortfall refusal's")
        print("  (loop_counts_refuse_if_short, exit 2, no verdict banked), never pytest's.")
        return 2
    print("  == the scope the active rung was graded at ==")
    print("\n".join(graded(ctx, found)))
    for line in _lines(first):
        print(f"  {line}")
    print(f"  (reconciled across {len(files)} collector file(s) — compared, never summed)")
    print("  A REGRESSION IN A DESELECTED APP SURFACES AT THE WAVE BANK, NOT AT")
    print("  THIS RUNG. That is the trade this narrowing makes, and it is printed")
    print("  beside the number it was made for rather than written down elsewhere.", flush=True)
    return 0


def verdict(rc: int) -> int:
    """pytest's exit as the leg's: 0, 1, and 3/4/5 said out loud as could-not-look."""
    if rc in _NOT_RUN:
        say(
            f"!! the pytest leg DID NOT RUN THE SUITE (pytest exit {rc}).",
            "   3 internal error · 4 usage error · 5 nothing was collected.",
            "   Nothing was judged about this tree, which is neither a finding nor a",
            "   pass.",
            "   Not a collection refusal of apps/conftest.py's: that prints its sentence",
            "   above the scope banner and stops there. Read pytest's own output above.",
        )
        return 2
    return rc


def reused(ctx: Ctx) -> bool:
    """Print the docs-only reuse the mode's consult answered, when it answered one."""
    tree = ctx.env.get(REUSE_TREE, "")
    if not tree:
        return False
    print(
        f"  pytest: REUSED from the banked verdict on {tree} (a docs-only delta, none spelled in "
        "a module under apps/)"
    )
    print("          Every other leg above this one RAN. What is reused is the pytest")
    print("          pass alone, and only because nothing outside docs/ moved since that")
    print(
        "          verdict was measured. Force a re-measure with DJB_LOOP_NO_CACHE=1.", flush=True
    )
    return True


def on_a_product(ctx: Ctx, args: Sequence[str]) -> bool:
    """Say what a product tree's pass runs; True when it has no app of its own to run."""
    if gate_tests.product_of(ctx.root) is None:
        return False
    targets = [a for a in args if not a.startswith("-")]
    if not targets:
        print(
            "  loop: a product tree with no app of its own yet — pytest runs nothing"
            " (the platform's are not a product's to pay for)",
            flush=True,
        )
        return True
    print(
        f"  loop: a product tree — pytest runs the product's own apps: {' '.join(targets)}"
        " (the platform's are not a product's to pay for)",
        flush=True,
    )
    return False


def leg(
    ctx: Ctx, args: Sequence[str], found: scope.Scope | None = None, test_sh: str = TEST_SH
) -> int:
    """One pass with `args` inside one slot, its counts reconciled; the leg's 0/1/2."""
    if reused(ctx) or on_a_product(ctx, args):
        return 0
    try:
        taken = hold.acquire_slot("loop")
    except hold.Refused as exc:
        say(
            "!! no pytest slot — see above. Nothing was judged about this tree.",
            f"   cause: {exc.cause}",
        )
        return 2
    counts_dir = tempfile.mkdtemp(prefix="djb-loop-counts.") if counted(args) else ""
    fd, refusal = tempfile.mkstemp(prefix="djb-loop-refusal.")
    os.close(fd)
    try:
        workers = taken.workers or hold.slot_workers(taken.total or 1)
        rc = preamble(ctx, found, taken, workers)
        if rc:
            return rc
        counts = [f"--djb-scope-counts={counts_dir}"] if counts_dir else []
        env = {"DJB_GATE_SLOT_WORKERS": str(workers), REFUSAL_FILE: refusal}
        rc = tool(ctx, (test_sh, "-n", str(workers), *args, *counts), env)
        said = Path(refusal).read_text(encoding="utf-8", errors="replace")
        if said.strip():
            say(f"!! the pytest leg's collection REFUSED (pytest exit {rc}):")
            say(*(f"   {line}" for line in said.splitlines()))
            say("   Nothing was judged about this tree and no verdict is banked.")
            return 2
        if counts_dir and reconcile(ctx, found, counts_dir, workers):
            say(
                "!! the --loop scope could not be RECONCILED — see above.",
                "   Nothing was judged about this tree and no verdict is banked: a scope the",
                "   collectors did not agree on is not a scope anything can be graded at.",
            )
            return 2
        targets = [a for a in args if not a.startswith("-")]
        if rc == 5 and targets and gate_tests.product_of(ctx.root) is not None:
            print(f"  loop: {' '.join(targets)} has no tests yet — nothing to run", flush=True)
            return 0
        return verdict(rc)
    finally:
        taken.release()
        os.unlink(refusal)
        if counts_dir:
            shutil.rmtree(counts_dir, ignore_errors=True)
        for a in args:
            if a.startswith("--djb-impact-select="):
                Path(a.split("=", 1)[1]).unlink(missing_ok=True)


def run(ctx: Ctx) -> int:
    """The handed-down flags (`GATE_LOOP_PYTEST_ARGS`), else this leg's own derivation."""
    if ARGS in ctx.env:
        return leg(ctx, ctx.env[ARGS].split())
    if ctx.env.get(REUSE_TREE):
        return leg(ctx, [])
    try:
        found = derive(ctx)
    except CouldNotLook as exc:
        say(
            f"!! {exc}",
            "!! the pytest tier COULD NOT DERIVE the active rung's changed files — see above.",
        )
        return 2
    return leg(ctx, tier_args(found), found)


LEG = Leg(
    "pytest",
    "-",
    "pytest (ONE pass, a FRESH random seed, ONE OF THIS MACHINE'S PYTEST SLOTS — the fast tier "
    "plus the active rung's own app, or the WHOLE suite when the active rung changed shared test "
    "infrastructure; the full gate at push runs two whole-suite passes under one seed, which is "
    "where idempotency is proven)",
    run,
    None,
    frozenset({"loop"}),
    ARGV,
)
