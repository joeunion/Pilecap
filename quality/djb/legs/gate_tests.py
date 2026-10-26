"""The `gate-tests` leg: the gate's own pytest modules under `quality/tests`, in the full gate."""

# does-not-cover: `--loop`, whose always-on runs the harness's two modules by name from `check.sh`.

from __future__ import annotations

import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from xml.etree import ElementTree

from quality.could_not_look import CouldNotLook
from quality.djb import registry as R
from quality.djb import scope
from quality.djb.legs import selftest
from quality.djb.legs._run import checkout_python, say, tool
from quality.djb.registry import Ctx, Leg

#: This leg's name: one member of the selftest unit, planned as its pieces, never one per shard.
NAME = "gate-tests"
#: The suite's home, a product's own (its drawer's), and the drive runner: params are shell members.
HOME = "quality/tests"
PRODUCT_HOME = "quality/local/tests"
DRIVE_RUNNER = "quality/tests/test_drives.py"
#: The `mypy` leg's population, listed first: a cold cache then analyses apps in that leg's order.
MYPY_FIRST = ("apps", "config")
#: The fixture worlds: data a test copies or reads, never a module of this member.
WORLDS = "quality/tests/fixtures/"
#: The worlds' Python that mypy never reads as the harness's own (a world's `apps.*` is not ours).
WORLDS_MYPY = r"^quality/tests/fixtures/(collection_world|golden_copy|runbook)/"
ARGV = (
    (
        "<checkout python>",
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
        "-v",
        "-n",
        "auto",
        HOME,
        f"--ignore={DRIVE_RUNNER}",
    ),
    ("<checkout python>", "-m", "mypy", "--strict", "--exclude", WORLDS_MYPY, *MYPY_FIRST, HOME),
)


#: The line a product tree's run prints instead of the platform's suite; satisfied, never 2.
ON_A_PRODUCT = (
    f"{NAME}: the platform's own tests — not a product's to pay for; the template's CI vouches"
    " for them (SDK program, 2026-10-11)"
)


def product_of(root: Path) -> str | None:
    """The `rule_id_namespace:` the checkout's drawer declares; None on the template."""
    from quality.djb import boundary

    drawer = root / boundary.DRAWER
    return boundary.namespace_in(drawer.read_text() if drawer.is_file() else None)


#: What pytest runs when the platform partition is skipped: a product's apps, then the nets.
PATHS = ("uv", "run", "python", "-m", "quality.partition", "paths")


class Unnamed(CouldNotLook):
    """The partition's `paths` exited nonzero: its exit and its text, for the caller to print."""

    def __init__(self, rc: int, text: str) -> None:
        super().__init__(
            f"the partition could not name this product's apps (exit {rc}): {text.strip()[-800:]}"
        )
        self.rc, self.text = rc, text


def _paths(argv: Sequence[str], root: Path) -> tuple[int, str]:
    done = subprocess.run(list(argv), cwd=root, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def product_apps(
    root: Path, run: Callable[[Sequence[str]], tuple[int, str]] | None = None
) -> tuple[str, ...]:
    """A product tree's own app directories, as the partition names them; `Unnamed` on doubt."""
    rc, text = run(PATHS) if run is not None else _paths(PATHS, root)
    if rc != 0:
        raise Unnamed(rc, text)
    return tuple(p for p in text.split() if (root / p / "apps.py").is_file())


#: The member's piece FLOOR; the plan cuts its measured wall under the ceiling (`R.pieces_of`).
FLOOR = 3


def modules(root: Path, *, narrowed: bool = True) -> list[str]:
    """The member's test modules, sorted, the drive runner out; a narrowed plan's selection."""
    home = root / HOME
    found = (p.relative_to(root).as_posix() for p in home.rglob("test_*.py"))
    every = sorted(
        m
        for m in found
        if m != DRIVE_RUNNER and "__pycache__" not in m and not m.startswith(WORLDS)
    )
    plan = scope.read_plan() if narrowed else None
    if plan is None or plan.modules is None:
        return every
    return [m for m in every if m in plan.modules]


def piece(every: Sequence[str], k: int, n: int) -> list[str]:
    """Piece `k` (zero-based) of `n`: every n-th module of the sorted list, from the k-th."""
    return list(every[k::n])


def split(root: Path) -> R.Split:
    """The member's pieces as the plan prices them: LPT over the module column, by count without."""
    homes = [root / h for h in R.WALLS_HOMES]
    machine = R._machine()
    wall = R.walls_view(homes, machine, only=False).get(NAME, 0)
    parts = R.member_parts(homes, machine, {NAME: modules(root)})
    return R.split_member(wall, FLOOR, parts[NAME])


def held(ctx: Ctx) -> tuple[tuple[int, ...], int] | None:
    """`(pieces, n)`: the zero-based pieces of `n` this shard holds; None on an unsharded run."""
    shard = selftest.shard_of(ctx)
    if shard is None:
        return None
    taken, _ = selftest.unit_plan(ctx, R.load(ctx.root), *shard)
    n = sum(1 for m in taken if m.startswith(f"{NAME}{R.PIECE}"))
    if not n:
        return ((0,) if taken.get(NAME, 0) == shard[0] else ()), 1
    return tuple(i for i in range(n) if taken[R.piece_name(NAME, i + 1)] == shard[0]), n


def chosen(ctx: Ctx, mine: Sequence[int], of: int) -> list[str]:
    """The modules of the pieces held; `ValueError` when the split and the plan disagree on `n`."""
    cut = split(ctx.root)
    if cut.n != of:
        raise ValueError(f"the plan holds {of} pieces and the module split cuts {cut.n}")
    return sorted(m for i in mine for m in cut.lists[i])


def harness(ctx: Ctx) -> int:
    """`--pr`'s form: the modules the diff selects (`scope.touched`), `-m not full_gate`; 0/1/2."""
    from quality.djb import scope
    from quality.djb.legs import always_on

    try:
        changed = scope.changed_files(ctx.root, ctx.env.get("GATE_PR_BASE") or None)
        found = scope.touched(ctx.root, scope.charged(ctx.root, changed.paths, changed.base))
    except CouldNotLook as exc:
        say(f"!! {NAME}: the diff's harness selection could not be derived — {exc}")
        return 2
    selected = [m for m in found if m != DRIVE_RUNNER]
    if not selected and product_of(ctx.root):
        print(f"  {ON_A_PRODUCT}", flush=True)
        return 0
    print(f"  {NAME} (--pr): {' '.join(selected) or 'no module'} — the diff's own selection")
    if not selected:
        return 0
    py = checkout_python(ctx.root)
    if py is None:
        say(f"!! {NAME}: {ctx.root}/.venv/bin/python is absent — run ./scripts/setup.sh")
        return 2
    return tool(ctx, (str(py), *ARGV[0][1:-2], *selected, *always_on.LOOP_DESELECT))


def product_modules(root: Path) -> list[str]:
    """A product's own gate test modules under its drawer, sorted, as paths from the checkout."""
    home = root / PRODUCT_HOME
    found = home.rglob("test_*.py") if home.is_dir() else ()
    return sorted(p.relative_to(root).as_posix() for p in found if "__pycache__" not in p.parts)


def on_a_product(ctx: Ctx) -> int:
    """A product's run: its own drawer tests (`--pr`: the diff's), never the platform's; 0/1/2."""
    if ctx.env.get("GATE_PR"):
        return harness(ctx)
    try:
        shard = selftest.shard_of(ctx)
    except ValueError as exc:
        say(f"!! {NAME}: {exc}")
        return 2
    own = product_modules(ctx.root) if shard is None or shard[0] == 0 else []
    print(f"  {ON_A_PRODUCT}", flush=True)
    if not own:
        return 0
    py = checkout_python(ctx.root)
    if py is None:
        say(f"!! {NAME}: {ctx.root}/.venv/bin/python is absent — run ./scripts/setup.sh")
        return 2
    print(f"  {NAME}: the product's own {len(own)} module(s) under {PRODUCT_HOME}", flush=True)
    return tool(ctx, (str(py), *ARGV[0][1:-2], *own))


def run(ctx: Ctx) -> int:
    """`mypy --strict` and this shard's pieces in one session; a product: its own tests."""
    try:
        if product_of(ctx.root):
            return on_a_product(ctx)
    except (CouldNotLook, OSError) as exc:
        say(f"!! {NAME}: this tree's drawer could not be read — {exc}")
        return 2
    if ctx.env.get("GATE_PR"):
        return harness(ctx)
    try:
        plan = held(ctx)
    except (ValueError, R.RegistryError, CouldNotLook, OSError) as exc:
        say(f"!! {NAME}: this shard's plan could not be read — {exc}")
        return 2
    k, n = selftest.shard_of(ctx) or (0, 1)
    mine, of = plan if plan is not None else (None, 1)
    if mine == ():
        print(f"  {NAME}: not in shard {k + 1}/{n}", flush=True)
        return 0
    py = checkout_python(ctx.root)
    if py is None:
        say(
            f"!! the gate's own tests could not run: {ctx.root}/.venv/bin/python is absent — run "
            f"./scripts/setup.sh"
        )
        return 2
    tests: tuple[str, ...] = ARGV[0][1:]
    held_modules = modules(ctx.root)
    try:
        narrowed = scope.read_plan(ctx.env)
    except CouldNotLook as exc:
        say(f"!! {NAME}: the plan could not be read — {exc}")
        return 2
    if narrowed is not None and narrowed.modules is not None:
        print(f"  {NAME}: narrowed by the plan — {len(held_modules)} modules, whole", flush=True)
        tests = (*ARGV[0][1:-2], *held_modules)
    if mine is not None and len(mine) < of:
        try:
            held_modules = chosen(ctx, mine, of)
        except (ValueError, CouldNotLook, OSError) as exc:
            say(f"!! {NAME}: this shard's modules could not be cut — {exc}")
            return 2
        names = ", ".join(f"{i + 1}/{of}" for i in mine)
        print(
            f"  {NAME}: pieces {names} in shard {k + 1}/{n} — {len(held_modules)} modules",
            flush=True,
        )
        tests = (*ARGV[0][1:-2], *held_modules)
    sink = ctx.env.get("DJB_MEMBER_WALLS_OUT")
    member = Ctx(ctx.root, ctx.mode, selftest.consumed(ctx.env))
    xml = Path(tempfile.mkstemp(prefix="djb-gate-tests.", suffix=".xml")[1]) if sink else None
    started = time.monotonic()
    verdict = 0
    if mine is None or 0 in mine:
        verdict = tool(member, (str(py), *ARGV[1][1:]))
    if verdict in (0, 1) and narrowed is not None and narrowed.modules is not None:
        if not held_modules:
            print(f"  {NAME}: no selected module in these pieces — pytest not run", flush=True)
            tests = ()
    if verdict in (0, 1) and tests:
        junit = (f"--junitxml={xml}",) if xml else ()
        ran = tool(member, (str(py), *tests, *junit))
        verdict = max(verdict, ran) if ran in (0, 1) else 2
    elif verdict not in (0, 1):
        verdict = 2
    took = str(int(time.monotonic() - started))
    part = f"{k + 1}/{n}"
    secs = module_walls(xml, held_modules) if xml else {}
    rows = [f"{R.MODULE_ROW}\t{m}\t{s:.1f}\t{part}" for m, s in secs.items()]
    selftest.walls_append(ctx, row_name(mine, of), str(verdict), took, part, rows)
    if xml:
        xml.unlink(missing_ok=True)
    return verdict


def module_walls(xml: Path, held_modules: Sequence[str]) -> dict[str, float]:
    """Each held module's summed test seconds from pytest's junit xml; {} when it did not write."""
    try:
        root = ElementTree.parse(xml).getroot()  # noqa: S314 — the junit file this leg's own pytest run just wrote
    except (OSError, ElementTree.ParseError):
        return {}
    by_dots = {m.removesuffix(".py").replace("/", "."): m for m in held_modules}
    out = dict.fromkeys(held_modules, 0.0)
    cases = list(root.iter("testcase"))
    for case in cases:
        dotted = case.get("classname", "")
        while dotted and dotted not in by_dots:
            dotted = dotted.rpartition(".")[0]
        if dotted:
            out[by_dots[dotted]] += float(case.get("time") or 0)
    return out if cases else {}


def row_name(mine: tuple[int, ...] | None, of: int) -> str:
    """The walls row's member: the whole name, or `gate-tests#<ks>/<n>` for the pieces held."""
    if mine is None or len(mine) == of:
        return NAME
    return f"{NAME}{R.PIECE}{','.join(str(i + 1) for i in mine)}/{of}"


LEG = Leg(
    NAME,
    "selftest",
    "the gate's own tests — mypy --strict over quality/tests, then every module but the drive"
    " runner in one pytest session",
    run,
    "selftest",
    frozenset({"full"}),
    ARGV,
    pieces=FLOOR,
    units=modules,
)
