"""The gate's leg table: `quality/djb/legs/<x>.py::LEG` discovered, the drives from their table."""

# Invariant: standard library only, Python 3.9 at run time — `--list-legs` needs no venv.
# does-not-cover: what a product's drawer leg or drive does — only that it is declared and found.
# does-not-cover: whether a body runs the `argv` it declares — test_legs.py's pin is that net.

from __future__ import annotations

import importlib
import math
import os
import pkgutil
import platform
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook
from quality.djb import env as environment
from quality.djb.drive_table import DRIVES
from quality.djb.ledger import durations, module_durations

#: The shell gate whose still-shell legs this table reads; once it is the shim, none.
GATE = "scripts/check.sh"
#: The package every discovered leg lives in.
LEGS_PACKAGE = "quality.djb.legs"
#: The modes a leg may run in; a full run is `full`.
LEG_MODES = ("fast", "loop", "full")
#: The selftest unit's floor per shard, `check.sh`'s `SELFTEST_SHARD_FLOOR_S`.
SHARD_FLOOR_S = 300
#: The ceiling a planned piece is cut under: the next-longest unit's CI wall (pytest-x2, ~10 min).
SHARD_CEILING_S = 600
#: The member the selftest shard population always opens with (`selftest_shard_population`).
ENGINE_MEMBER = "house-rules-engine"
#: The separator in a split member's piece name, `gate-tests#2`.
PIECE = "#"
#: The per-rule walls row the selftest leg appends, and its two ids that are no rule's.
RULE_ROW = "rule-walls/1"
RULE_FIXED = "@fixed"
#: The per-module walls row a split leg's pieces append: `module-walls/1 <module> <s> <part>`.
MODULE_ROW = "module-walls/1"
RULE_WHOLE = "@whole"
#: The engine's rule ids in plan order, one per line: the per-rule column's population.
RULE_IDS_READER = """\
import sys
sys.argv = ["gate"]
from quality.engine.world import RULES
print("\\n".join(str(rule["id"]) for rule in RULES))
"""
#: The walls table and its drawer (`scripts/gate_ledger.sh`'s two homes).
WALLS_HOMES = ("scripts/gate_member_durations.json", "scripts/local/gate_member_durations.ci.json")
#: The machine column CI's shard count is priced from.
CI_MACHINE = "ubuntu-latest"
#: The product drawers: its own legs, then its own drives (`DJB_LOCAL_LEGS_DIR`, `_DRIVES_DIR`).
DRAWERS = ("scripts/local/legs", "scripts/local/drives")
#: A drawer leg's header sentinels; v1 is the one version read.
LEG_HEADER = ("# >>> leg v1 >>>", "# <<< leg <<<")
#: A drawer leg's header fields: the three it must declare, then the three it may.
LEG_REQUIRED = ("unit", "needs", "tier")
LEG_OPTIONAL = ("touches", "inputs", "env")
#: The prefix every drawer member is printed under.
LOCAL = "local:"

#: The drive table's names, in its order.
DRIVE_NAMES: tuple[str, ...] = tuple(drive.name for drive in DRIVES)

#: The unit a loop-only leg names: it runs in `--loop` alone and is in no row of the listing.
LOOP_ONLY = "-"
#: The loop-only legs' order after the static legs (`check.sh`'s `--loop` block).
LOOP_ORDER = ("secrets", "always-on", "pytest")

_REGISTERED = re.compile(r"^[ \t]*gate_run_body ([a-z0-9-]+) ([A-Za-z0-9_]+) ([a-z0-9-]+) ")
_DRIVE_LINE = re.compile(r"^\./(?:scripts|deploy)/tests/test_([a-z_]+)\.sh$")
_UNIT_LINE = re.compile(r"^gate_unit ([a-z0-9-]+) ")
_LEG_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DRIVE_NAME = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_PREAMBLE = re.compile(r"^[ \t]*(?:\.|source)[ \t]+\S*drive_preamble\.sh", re.MULTILINE)


class RegistryError(ValueError):
    """The table does not validate; the dispatcher turns it into exit 2."""


@dataclass(frozen=True)
class Unit:
    """One runner's share of the full gate: what it needs and whether it shards."""

    name: str
    needs: tuple[str, ...]
    shards: str


#: The units in the full gate's order; the golden pin is the proof this typing lost nothing.
UNITS: tuple[Unit, ...] = (
    Unit("static", ("db",), "0"),
    Unit("supply-chain", ("network",), "0"),
    Unit("pytest-x2", ("db", "redis", "temporal", "minio", "meilisearch"), "N-capable"),
    # `network`: the supply-chain drive's advisory case reaches the npm registry.
    Unit("selftest", ("db", "docker", "temporal", "zitadel", "mailpit", "network"), "N-capable"),
    Unit("full-house-rules", ("none",), "0"),
)


@dataclass(frozen=True)
class Ctx:
    """What a leg body is handed: the checkout, the mode it runs under and its environment."""

    root: Path
    mode: str
    env: Mapping[str, str] = field(default_factory=environment.environ)


@dataclass(frozen=True)
class Leg:
    """One leg: name, unit, banner, body, the leg it follows, its modes and the commands it runs."""

    name: str
    unit: str
    banner: str
    body: Callable[[Ctx], int] | None = None
    after: str | None = None
    modes: frozenset[str] = frozenset(LEG_MODES)
    argv: tuple[tuple[str, ...], ...] = ()
    claims: tuple[str, ...] = ()
    pieces: int = 1
    units: Callable[[Path], list[str]] | None = None

    @property
    def carried_by_shell(self) -> bool:
        """Whether `check.sh` still carries this leg's body."""
        return self.body is None


@dataclass(frozen=True)
class LocalLeg:
    """One product leg from the drawer: `local:<stem>`, its header's six fields and its file."""

    name: str
    unit: str
    needs: tuple[str, ...]
    tier: str
    path: Path
    touches: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()
    env: tuple[str, ...] = ()


@dataclass(frozen=True)
class Table:
    """The validated table: each unit's members in order, the Python legs, the drawer's legs."""

    rows: tuple[tuple[Unit, tuple[str, ...]], ...]
    legs: tuple[Leg, ...]
    local: tuple[LocalLeg, ...] = ()
    local_drives: tuple[tuple[str, Path], ...] = ()

    def unit(self, name: str) -> tuple[Unit, tuple[str, ...]]:
        """The unit called `name` and its members; `RegistryError` for a unit nobody declared."""
        for row in self.rows:
            if row[0].name == name:
                return row
        raise RegistryError(
            f"no unit '{name}' — the units are {', '.join(u.name for u, _ in self.rows)}"
        )

    def leg(self, name: str) -> Leg:
        """The Python leg called `name`; `RegistryError` when none is."""
        for leg in self.legs:
            if leg.name == name:
                return leg
        raise RegistryError(f"no leg '{name}' has a body under {LEGS_PACKAGE}")

    def mode_legs(self, mode: str) -> tuple[Leg, ...]:
        """The Python legs a run in `mode` executes, in the table's order."""
        if mode not in LEG_MODES:
            raise RegistryError(f"no mode '{mode}' — the modes are {', '.join(LEG_MODES)}")
        order = [m for _, members in self.rows for m in members]
        listed = sorted(
            (g for g in self.legs if mode in g.modes and g.unit != LOOP_ONLY),
            key=lambda g: order.index(g.name),
        )
        rank = {name: i for i, name in enumerate(LOOP_ORDER)}
        loop_only = sorted(
            (g for g in self.legs if mode in g.modes and g.unit == LOOP_ONLY),
            key=lambda g: rank.get(g.name, len(rank)),
        )
        return (*listed, *loop_only)

    def pieces(self) -> dict[str, int]:
        """Each leg the selftest unit's plan splits, by its declared floor (`pieces_of` counts)."""
        return {g.name: g.pieces for g in self.legs if g.pieces > 1}

    def units(self, root: Path) -> dict[str, list[str]]:
        """Each split leg's indivisible units (its test modules) in the checkout at `root`."""
        return {g.name: g.units(root) for g in self.legs if g.pieces > 1 and g.units}

    def check_modules(self, unit: str = "static") -> frozenset[str]:
        """The `scripts/<module>` files a leg of `unit` runs as `<module> --check`."""
        return check_modules(self.legs, unit)


def check_modules(legs: Iterable[Leg], unit: str = "static") -> frozenset[str]:
    """The `scripts/<module>` files a leg of `unit` declares it runs as `<module> --check`."""
    found: set[str] = set()
    for leg in legs:
        if leg.unit != unit:
            continue
        for argv in leg.argv:
            for i, word in enumerate(argv[:-1]):
                if word.startswith("scripts/") and argv[i + 1] == "--check":
                    found.add(word)
    return frozenset(found)


def discover(package: str = LEGS_PACKAGE) -> tuple[Leg, ...]:
    """Every `LEG` the package's modules declare; a `_`-prefixed module is a helper."""
    try:
        home = importlib.import_module(package)
    except ImportError as exc:
        raise RegistryError(f"the leg package {package} would not import: {exc}") from exc
    legs: list[Leg] = []
    for info in sorted(pkgutil.iter_modules(home.__path__), key=lambda i: i.name):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{package}.{info.name}")
        leg = getattr(module, "LEG", None)
        if not isinstance(leg, Leg):
            raise RegistryError(
                f"{package}.{info.name} declares no `LEG = Leg(...)` — a module here is a leg"
            )
        if leg.body is None:
            raise RegistryError(f"{package}.{info.name}: leg '{leg.name}' has no body")
        legs.append(leg)
    return tuple(legs)


def shell_legs(text: str) -> list[tuple[str, str]]:
    """`(name, unit)` per `gate_run_body` registration, first sighting, `-` units out."""
    seen: dict[str, str] = {}
    for line in text.splitlines():
        found = _REGISTERED.match(line)
        if found and found.group(1) not in seen:
            seen[found.group(1)] = found.group(3)
    return [(name, unit) for name, unit in seen.items() if unit != "-"]


def shell_drives(text: str) -> list[str]:
    """The selftest drives `check.sh` registers by their column-zero invocation lines, in order."""
    names: list[str] = []
    for line in text.splitlines():
        found = _DRIVE_LINE.match(line)
        if found:
            if found.group(1) in names:
                raise RegistryError(f"drive '{found.group(1)}' is registered twice in {GATE}")
            names.append(found.group(1))
    return names


def shell_units(text: str) -> list[str]:
    """The unit names `check.sh`'s `gate_unit` lines declare, in order."""
    return [m.group(1) for m in map(_UNIT_LINE.match, text.splitlines()) if m]


def _chain(unit: str, legs: Sequence[Leg]) -> list[Leg]:
    """A unit's Python legs ordered by `after`; one head, one successor each, nothing unreached."""
    names = {g.name for g in legs}
    heads = [g for g in legs if g.after is None]
    if len(heads) != 1:
        raise RegistryError(
            f"unit '{unit}' has {len(heads)} Python legs with no `after` "
            f"({', '.join(g.name for g in heads) or 'none'}) — exactly one leads"
        )
    following: dict[str, Leg] = {}
    for g in legs:
        if g.after is None:
            continue
        if g.after not in names:
            raise RegistryError(
                f"leg '{g.name}' follows '{g.after}', which is no Python leg of unit '{unit}'"
            )
        if g.after in following:
            raise RegistryError(
                f"legs '{following[g.after].name}' and '{g.name}' both follow '{g.after}'"
            )
        following[g.after] = g
    order = [heads[0]]
    while order[-1].name in following:
        order.append(following[order[-1].name])
    if len(order) != len(legs):
        stray = sorted(names - {g.name for g in order})
        raise RegistryError(
            f"unit '{unit}': legs {', '.join(stray)} are in a cycle the head never reaches"
        )
    return order


def build(
    legs: Sequence[Leg],
    gate_text: str,
    units: Sequence[Unit] = UNITS,
    drives: Sequence[str] = DRIVE_NAMES,
    local: Sequence[LocalLeg] = (),
    local_drives: Sequence[tuple[str, Path]] = (),
) -> Table:
    """The validated table: claiming legs, chained, at their first shell place; the drawer last."""
    unit_names = [u.name for u in units]
    if shell_units(gate_text) and shell_units(gate_text) != unit_names:
        raise RegistryError(
            f"{GATE} declares the units {shell_units(gate_text)} and the registry {unit_names} — "
            f"one table"
        )
    by_name: dict[str, Leg] = {}
    for g in legs:
        if g.name in by_name:
            raise RegistryError(f"two legs are named '{g.name}'")
        if g.unit == LOOP_ONLY and set(g.modes) != {"loop"}:
            raise RegistryError(
                f"leg '{g.name}' is in no unit and runs in {sorted(g.modes)} — only a loop-only"
                " leg is outside the listing"
            )
        if g.unit not in unit_names and g.unit != LOOP_ONLY:
            raise RegistryError(
                f"leg '{g.name}' names unit '{g.unit}', which is not one of {unit_names}"
            )
        stray = set(g.modes) - set(LEG_MODES)
        if stray:
            raise RegistryError(
                f"leg '{g.name}' names modes {sorted(stray)} — the modes are {list(LEG_MODES)}"
            )
        by_name[g.name] = g
    shell = shell_legs(gate_text)
    for name, unit in shell:
        if unit not in unit_names:
            raise RegistryError(
                f"{GATE} registers leg '{name}' in unit '{unit}', which the registry does not "
                f"declare"
            )
        if name in by_name and by_name[name].unit != unit:
            raise RegistryError(
                f"leg '{name}' is in unit '{by_name[name].unit}' here and '{unit}' in {GATE} — a "
                f"leg in two units"
            )
    shell_named = shell_drives(gate_text)
    if shell_named and shell_named != list(drives):
        raise RegistryError(
            f"{GATE} registers the drives {shell_named} and the drive table {list(drives)} — one"
            " population"
        )
    rows: list[tuple[Unit, tuple[str, ...]]] = []
    claimed = {name for name, _ in shell}
    for u in units:
        members = [name for name, unit in shell if unit == u.name]
        mine = [g for g in legs if g.unit == u.name]
        if mine:
            chain = [g.name for g in _chain(u.name, mine)]
            held = [n for n in chain if n in claimed]
            at = min(members.index(n) for n in held) if held else len(members)
            members = [m for m in members if m not in chain]
            members[at:at] = chain
        if u.name == "selftest":
            at = members.index("selftest") + 1 if "selftest" in members else len(members)
            members[at:at] = [d for d in drives if d not in members]
            members += [name for name, _ in local_drives]
        if not members:
            raise RegistryError(f"unit '{u.name}' has no leg — no runner would be handed anything")
        if len(set(members)) != len(members):
            raise RegistryError(f"unit '{u.name}' names a member twice: {members}")
        rows.append((u, tuple(members)))
    for unit, needs in local_units(local):
        rows.append((Unit(unit, needs, "0"), tuple(g.name for g in local if g.unit == unit)))
    for mode in LEG_MODES:
        if legs and not any(mode in g.modes for g in legs):
            raise RegistryError(f"mode '{mode}' names no leg")
    return Table(tuple(rows), tuple(legs), tuple(local), tuple(local_drives))


def drawer(root: Path, which: int) -> Path:
    """The leg drawer (0) or the drive drawer (1): its `DJB_LOCAL_*_DIR`, else `DRAWERS[which]`."""
    name = ("DJB_LOCAL_LEGS_DIR", "DJB_LOCAL_DRIVES_DIR")[which]
    home = Path(environment.read(name) or DRAWERS[which])
    return home if home.is_absolute() else root / home


def template_names(legs: Sequence[Leg] | None = None) -> frozenset[str]:
    """Every leg and drive name this gate carries before a drawer: one a product may not take."""
    found = discover() if legs is None else legs
    return frozenset(
        {g.name for g in found} | {c for g in found for c in g.claims} | set(DRIVE_NAMES)
    )


def _refuse(path: Path, why: str) -> RegistryError:
    return RegistryError(
        f"local leg {path}: {why} — a product leg is DECLARED: a header this gate cannot read is"
        " exit 2 at the listing and never a silently smaller gate"
    )


def _header(path: Path) -> dict[str, str]:
    """A drawer leg's `# <field>: <value>` block between the v1 sentinels, refused by field."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    opening, closing = LEG_HEADER
    if opening not in lines:
        got = next((ln.split()[3:4] for ln in lines if ln.startswith("# >>> leg ")), None)
        if got is not None:
            raise _refuse(
                path,
                f"its header declares version '{(got or ['?'])[0]}' and this gate implements v1"
                f" only — the opening line is exactly '{opening}'",
            )
        raise _refuse(
            path,
            f"it carries no '{opening}' header block — a leg declares its unit, its needs, its"
            " tier and what its exit 2 means",
        )
    start = lines.index(opening) + 1
    end = lines.index(closing, start) if closing in lines[start:] else len(lines)
    fields: dict[str, str] = {}
    for line in lines[start:end]:
        if not line:
            continue
        if not line.startswith("#"):
            raise _refuse(
                path,
                f"the header line '{line}' is not a comment — every line between the sentinels"
                " is '# <field>: <value>'",
            )
        body = line[1:].removeprefix(" ")
        if not body:
            continue
        if ":" not in body:
            raise _refuse(path, f"the header line '{body}' carries no '<field>: <value>' colon")
        name, value = body.split(":", 1)
        value = value.removeprefix(" ")
        if name == "two-means":
            raise _refuse(
                path,
                f"it declares the retired 'two-means' field (value '{value}') — 2 means could not"
                " look everywhere; exit 1 for a finding. Delete the field and have the leg exit 1"
                " where its tool reports a finding",
            )
        if name not in (*LEG_REQUIRED, *LEG_OPTIONAL):
            raise _refuse(
                path,
                f"unknown header field '{name}' — this gate reads"
                f" {' '.join(LEG_REQUIRED)} {' '.join(LEG_OPTIONAL)}",
            )
        if name in fields:
            raise _refuse(
                path, f"header field '{name}' is declared twice — a field with two values has none"
            )
        if not value:
            raise _refuse(
                path,
                f"header field '{name}:' is empty — an empty declaration says nothing; write the"
                " value",
            )
        fields[name] = value
    for name in LEG_REQUIRED:
        if name not in fields:
            raise _refuse(
                path,
                f"its header declares no '{name}:' — the required fields are"
                f" {' '.join(LEG_REQUIRED)}",
            )
    return fields


def local_legs(
    home: Path,
    known: Iterable[str] | None = None,
    units: Sequence[Unit] = UNITS,
) -> tuple[LocalLeg, ...]:
    """The drawer's legs in byte order, each `local:<stem>`; a malformed one is `RegistryError`."""
    if not home.is_dir():
        return ()
    taken = template_names() if known is None else frozenset(known)
    template_units = {u.name for u in units}
    found: list[LocalLeg] = []
    for path in sorted(home.glob("*.sh")):
        if not path.is_file() or path.name.startswith("_"):
            continue
        stem = path.name[: -len(".sh")]
        if not _LEG_NAME.match(stem):
            raise _refuse(
                path,
                "the file name is not a leg name — lower-case letters, digits, '-' and '_',"
                " starting with a letter or a digit",
            )
        if not os.access(path, os.X_OK):
            raise _refuse(
                path,
                "it is not executable — a leg this gate cannot run is a leg it would silently"
                " skip (chmod +x)",
            )
        head = _header(path)
        unit, needs, tier = head["unit"], head["needs"], head["tier"]
        if not re.fullmatch(r"[a-z0-9-]+", unit):
            raise _refuse(
                path, f"unit: '{unit}' is not a unit name — lower-case letters, digits and '-'"
            )
        if unit in template_units:
            raise _refuse(
                path,
                f"unit: '{unit}' is a unit THIS GATE declares — a product leg may not join one and"
                " inherit its organs, its shards and its pass count. Use 'local', or a new name of"
                " your own",
            )
        if tier not in LEG_MODES:
            raise _refuse(
                path,
                f"tier: '{tier}' — the tiers are fast, loop and full (the CHEAPEST mode that runs"
                " it; every mode above it runs it too)",
            )
        if not re.fullmatch(r"[a-z0-9,-]+", needs):
            raise _refuse(path, f"needs: '{needs}' — comma-joined organ names, or 'none'")
        env = head.get("env", "")
        if not re.fullmatch(r"[A-Za-z0-9_ ]*", env):
            raise _refuse(path, f"env: '{env}' — space-joined variable NAMES, never values")
        if stem in taken:
            raise _refuse(
                path,
                f"'{stem}' is already a leg or a drive this gate has — one name, two members, and"
                " the verdict row would name it once",
            )
        found.append(
            LocalLeg(
                f"{LOCAL}{stem}",
                unit,
                tuple(n for n in needs.split(",") if n),
                tier,
                path,
                tuple(head.get("touches", "").split()),
                tuple(head.get("inputs", "").split()),
                tuple(env.split()),
            )
        )
    return tuple(found)


def local_drives(
    home: Path, legs_home: Path, known: Iterable[str] = DRIVE_NAMES
) -> tuple[tuple[str, Path], ...]:
    """The drive drawer's `test_<name>.sh` as `(local:<name>, path)`; a malformed one refused."""
    if not home.is_dir():
        return ()
    taken = set(known)
    found: list[tuple[str, Path]] = []
    for path in sorted(home.glob("test_*.sh")):
        if not path.is_file():
            continue
        name = path.name[len("test_") : -len(".sh")]
        if not _DRIVE_NAME.match(name):
            raise RegistryError(
                f"product drive {path}: '{name}' is not a drive name — lower-case letters, digits"
                " and '_', starting with a letter or a digit. The file is named test_<name>.sh."
            )
        if not os.access(path, os.X_OK):
            raise RegistryError(
                f"product drive {path}: it is not executable — a drive this leg cannot run is a"
                " drive it would report as could-not-look on every gate (chmod +x)."
            )
        if not _PREAMBLE.search(path.read_text(encoding="utf-8", errors="replace")):
            raise RegistryError(
                f"product drive {path}: it does not source scripts/tests/drive_preamble.sh — its"
                " section 1 neutralises a push's GIT_DIR and its section 4 strips the CI"
                " exemption; without it a drive can write into the real repository from inside a"
                " green gate."
            )
        if name in taken:
            raise RegistryError(
                f"product drive {path}: '{name}' is already a drive this gate has — one name, two"
                " members, and the verdict row would name it once."
            )
        if (legs_home / f"{name}.sh").exists():
            raise RegistryError(
                f"product drive {path}: '{name}' is also a product LEG ({legs_home}/{name}.sh) —"
                f" both are printed '{LOCAL}{name}', so one label would mean two members."
            )
        taken.add(name)
        found.append((f"{LOCAL}{name}", path))
    return tuple(found)


def local_units(local: Sequence[LocalLeg]) -> list[tuple[str, tuple[str, ...]]]:
    """Each drawer unit in first-declared order, its needs the byte-sorted union of its legs'."""
    out: dict[str, set[str]] = {}
    for g in local:
        out.setdefault(g.unit, set()).update(n for n in g.needs if n != "none")
    return [(u, tuple(sorted(needs)) or ("none",)) for u, needs in out.items()]


def local_tier(local: Sequence[LocalLeg], mode: str) -> list[str]:
    """The drawer legs a run in `mode` executes: a leg's tier is the cheapest mode that runs it."""
    if mode not in LEG_MODES:
        raise RegistryError(f"no mode '{mode}' — the modes are {', '.join(LEG_MODES)}")
    rank = LEG_MODES.index(mode)
    return [g.name for g in local if LEG_MODES.index(g.tier) <= rank]


def local_touched(leg: LocalLeg, changed: Sequence[str]) -> bool:
    """Whether a narrowed mode runs `leg`: no `touches`, or one prefix in the changed set."""
    if not leg.touches:
        return True
    if not changed:
        raise CouldNotLook(
            f"{leg.name}: touches ({' '.join(leg.touches)}) cannot be applied — this run's changed"
            " set could not be read, so the leg runs"
        )
    return any(c == g or c.startswith(f"{g}/") for g in leg.touches for c in changed)


def load(root: Path) -> Table:
    """The table for the checkout at `root`: discovered legs, its `check.sh`, its two drawers."""
    try:
        text = (root / GATE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CouldNotLook(
            f"{GATE} could not be read ({exc}) — its still-shell legs are unknown"
        ) from exc
    found = discover()
    drives = local_drives(drawer(root, 1), drawer(root, 0))
    legs = local_legs(
        drawer(root, 0), template_names(found) | {name[len(LOCAL) :] for name, _ in drives}
    )
    return build(found, text, local=legs, local_drives=drives)


def _machine() -> str:
    """This machine's walls column: `box`, `darwin` or `ubuntu-latest`."""
    if Path(environment.read("DJB_GATE_BOX_MARKER", "/etc/djb/image-id") or "").exists():
        return "box"
    return "darwin" if platform.system() == "Darwin" else "ubuntu-latest"


def walls_view(homes: Iterable[Path], machine: str, *, only: bool) -> dict[str, float]:
    """Each member's wall from the table and its drawer, by `machine`'s column order."""
    return dict(durations(Path("."), machine, only=only, homes=list(homes), say=_silent))


def _silent(line: str) -> None:
    """The listing prints nothing about a walls table that will not read; it adds nothing."""


def shard_count(
    walls: Mapping[str, float],
    population: Sequence[str],
    pieces: Mapping[str, int] | None = None,
    parts: Mapping[str, Parts] | None = None,
) -> int:
    """`ceil(total / max(heaviest, floor))`, raised until no LPT shard passes the ceiling."""
    median = median_wall(walls, population)
    priced, names = pieced(walls, population, pieces or {}, parts)
    weights = [priced.get(n, median) for n in names]
    total, heaviest = sum(weights), max(weights, default=0)
    n = max(1, math.ceil(total / max(heaviest, SHARD_FLOOR_S)))
    while n < len(weights) and lpt_heaviest(weights, n) > max(heaviest, SHARD_CEILING_S):
        n += 1
    return n


def lpt_heaviest(weights: Sequence[float], n: int) -> float:
    """The heaviest load when `weights` go longest-first onto the lightest of `n` shards."""
    load = [0.0] * n
    for w in sorted(weights, reverse=True):
        load[load.index(min(load))] += w
    return max(load, default=0.0)


def median_wall(walls: Mapping[str, float], population: Sequence[str]) -> float:
    """The median measured wall over whole members, pieces never counted; 0 with none."""
    measured = sorted(walls[n] for n in population if n in walls)
    m = len(measured)
    if m == 0:
        return 0
    if m % 2:
        return measured[m // 2]
    return int((measured[m // 2 - 1] + measured[m // 2]) / 2)


def pieces_of(walls: Mapping[str, float], name: str, floor: int) -> int:
    """A split member's piece count: its wall cut under the ceiling, never below `floor`."""
    wall = walls.get(name)
    return max(floor, math.ceil(wall / SHARD_CEILING_S)) if wall else floor


def engine_pieces(walls: Mapping[str, float]) -> int:
    """The engine's member count: its measured wall cut under the ceiling; 1 when unmeasured."""
    return pieces_of(walls, ENGINE_MEMBER, 1)


def ceiling_line(
    walls: Mapping[str, float], names: Sequence[str], alone: Mapping[str, str] | None = None
) -> str:
    """Which bound the plan's heaviest member sits under: the ceiling, or itself above it."""
    heaviest = max(names, key=lambda n: (walls.get(n, 0), n), default="")
    secs = int(walls.get(heaviest, 0))
    if secs <= SHARD_CEILING_S:
        return f"the ceiling {SHARD_CEILING_S} s bound; heaviest member {heaviest} {secs} s"
    held = f" ({alone[heaviest]} alone)" if alone and heaviest in alone else ""
    return (
        f"{heaviest}{held} at {secs} s bound, over the ceiling {SHARD_CEILING_S} s — it is "
        "indivisible here"
    )


#: A split member's units and their measured seconds: `(modules, {module: seconds})`.
Parts = tuple[Sequence[str], Mapping[str, float]]


@dataclass(frozen=True)
class Split:
    """A split member's pieces: each one's units, its priced seconds, and any unit over alone."""

    lists: tuple[tuple[str, ...], ...]
    loads: tuple[float, ...]
    alone: dict[int, str]

    @property
    def n(self) -> int:
        """The piece count."""
        return len(self.loads)


def split_member(wall: float, floor: int, parts: Parts | None = None) -> Split:
    """The pieces: LPT over the unit column priced at the wall's share, by count without one."""
    # Invariant: the count rises until every row over the ceiling is one unit alone in it.
    units, column = parts or ((), {})
    measured = [column[u] for u in units if u in column]
    n = max(floor, math.ceil(wall / SHARD_CEILING_S)) if wall else floor
    if not measured:
        lists = tuple(tuple(units[k::n]) for k in range(n))
        return Split(lists, (wall / n,) * n, {})
    median = sorted(measured)[len(measured) // 2]
    weight = {u: column.get(u, median) for u in units}
    scale = wall / (sum(weight.values()) or 1)
    while True:
        lists, loads = lpt_units(units, weight, n)
        priced = tuple(x * scale for x in loads)
        over = [i for i, x in enumerate(priced) if x > SHARD_CEILING_S]
        if all(len(lists[i]) == 1 for i in over) or n >= len(units):
            return Split(lists, priced, {i: lists[i][0] for i in over if len(lists[i]) == 1})
        n += 1


def lpt_units(
    units: Sequence[str], weight: Mapping[str, float], n: int
) -> tuple[tuple[tuple[str, ...], ...], tuple[float, ...]]:
    """`units` longest-first onto the lightest of `n` lists, each list in sorted order."""
    load = [0.0] * n
    lists: list[list[str]] = [[] for _ in range(n)]
    for u in sorted(units, key=lambda u: (-weight[u], u)):
        s = min(range(n), key=lambda t: (load[t], t))
        lists[s].append(u)
        load[s] += weight[u]
    return tuple(tuple(sorted(x)) for x in lists), tuple(load)


def member_parts(
    homes: Sequence[Path], machine: str, units: Mapping[str, Sequence[str]]
) -> dict[str, Parts]:
    """Each split member's units with the walls tables' per-module column, by column order."""
    column = module_durations(list(homes), machine)
    return {name: (list(found), column) for name, found in units.items()}


def piece_name(name: str, k: int) -> str:
    """The plan's name for piece `k` (one-based) of a member the unit splits."""
    return f"{name}{PIECE}{k}"


def pieced(
    walls: Mapping[str, float],
    population: Sequence[str],
    pieces: Mapping[str, int],
    parts: Mapping[str, Parts] | None = None,
) -> tuple[dict[str, float], list[str]]:
    """The population with each measured split member as its pieces, each at its priced share."""
    # Invariant: `pieces` holds floors (the engine's is 1); `split_member` derives the count.
    priced: dict[str, float] = dict(walls)
    names: list[str] = []
    for name in population:
        if name not in walls or not (name == ENGINE_MEMBER or name in pieces):
            names.append(name)
            continue
        cut = split_member(walls[name], pieces.get(name, 1), (parts or {}).get(name))
        if cut.n < 2:
            names.append(name)
            continue
        for k, load in enumerate(cut.loads, start=1):
            names.append(piece_name(name, k))
            priced[piece_name(name, k)] = load
    return priced, names


def alone(
    walls: Mapping[str, float], pieces: Mapping[str, int], parts: Mapping[str, Parts]
) -> dict[str, str]:
    """Each planned piece that is one unit over the ceiling, by piece name, naming the unit."""
    out: dict[str, str] = {}
    for name, found in parts.items():
        if name in walls and name in pieces:
            cut = split_member(walls[name], pieces[name], found)
            out.update({piece_name(name, i + 1): u for i, u in cut.alone.items()})
    return out


def ci_shard_count(
    root: Path,
    members: Sequence[str],
    pieces: Mapping[str, int] | None = None,
    units: Mapping[str, Sequence[str]] | None = None,
) -> str:
    """The selftest unit's CI shard count, or `N-capable` when no walls table answers."""
    override = environment.read("DJB_GATE_MEMBER_WALLS_CI")
    homes = [Path(override)] if override else [root / h for h in WALLS_HOMES]
    machine = CI_MACHINE
    walls = walls_view(homes, CI_MACHINE, only=not override)
    if not walls:
        mac = environment.read("DJB_GATE_MEMBER_DURATIONS")
        homes = [Path(mac)] if mac else [root / h for h in WALLS_HOMES]
        machine = _machine()
        walls = walls_view(homes, machine, only=False)
    if not walls:
        return "N-capable"
    population = [ENGINE_MEMBER, *(m for m in members if m != "selftest")]
    parts = member_parts(homes, machine, units or {})
    return str(shard_count(walls, population, pieces, parts))


def list_legs(table: Table, *, ci: bool, root: Path | None = None) -> str:
    """The tab-separated unit table `--list-legs [--ci]` prints; `ci` adds the `passes` column."""
    lines: list[str] = []
    for unit, members in table.rows:
        needs, legs = ",".join(unit.needs), ",".join(members)
        if not ci:
            lines.append(f"{unit.name}\t{needs}\t{unit.shards}\t{legs}\n")
            continue
        shards, passes = unit.shards, ""
        if unit.name == "selftest":
            here = root or Path.cwd()
            shards = ci_shard_count(here, members, table.pieces(), table.units(here))
        elif unit.name == "pytest-x2":
            passes = "1"
        lines.append(f"{unit.name}\t{needs}\t{shards}\t{legs}\t{passes}\n")
    return "".join(lines)
