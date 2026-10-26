"""The engine's readers, trailer, memo, budget, drawer and census cases, in a clone of HEAD."""

# does-not-cover: the `§`/`—` glyphs around the trailer's ASCII keys — a reword between them.
# does-not-cover: one rule with findings of two kinds end to end — asserted in process.
# does-not-cover: a stale `doc:` anchor or `does_not_cover` — the trailer prints what the yaml says.
# does-not-cover: an uncommitted edit — the world is a clone of HEAD; commit `quality/**` first.
# does-not-cover: whether a recorded budget ceiling is right — only which modules are subjects.

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured, run_to
from quality.tests.fixtures.env_strip import STRIPPED
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives("quality/engine/explain.py", "quality/gate.py")

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
JS_PROBE_DIR = "frontend/src/components/zzz_probe_gate_explain"
JS_TARGET = f"{JS_PROBE_DIR}/index.ts"
PROBE_APP_DIR = "apps/zzz_probe_newapps"
RED_TARGET = "apps/example/selectors.py"


def _env(extra: Mapping[str, str] | None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in STRIPPED}
    return {**env, **(extra or {})}


#: Every world database this process named; dropped, with its `_hp` form, by `drop_world_databases`.
WORLD_DATABASES: set[str] = set()


def world_database(root: Path, worker: str) -> str:
    """The world's own `DATABASE_NAME`: its xdist worker and its root, never the checkout's."""
    token = hashlib.sha256(f"{worker}\0{root}".encode()).hexdigest()[:8]
    return f"djb_world_{worker}_{token}"


def drop_world_databases() -> None:
    """Drop every world database this process named, and the `_hp` probe database beside it."""
    while WORLD_DATABASES:
        name = WORLD_DATABASES.pop()
        for each in (f"{name}_hp", name):
            done = subprocess.run(
                ["bash", "-c", 'source scripts/db.sh >/dev/null 2>&1 && db_drop "$1"', "db", each],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=_env(None),
            )
            if done.returncode != 0:
                raise CouldNotLook(f"could not drop the world database {each}: {done.stderr}")


@dataclass(frozen=True)
class Ran:
    """One engine run in the world: its exit, its capture's text and where the capture is."""

    rc: int
    out: str
    path: Path

    def why(self, claim: str) -> str:
        """The failure message: the claim, the exit, and the capture's last lines."""
        tail = "\n".join(self.out.splitlines()[-40:])
        return f"{claim} (exit {self.rc}, {self.path}):\n{tail}"


@dataclass
class World:
    """A clone of HEAD under scratch."""

    root: Path
    logs: Path
    env: dict[str, str] = field(default_factory=dict)
    count: list[int] = field(default_factory=lambda: [0])

    def run(self, argv: list[str], env: Mapping[str, str] | None = None) -> Ran:
        """`argv` in the world to a numbered capture; an empty capture is could-not-look."""
        self.count[0] += 1
        sink = self.logs / f"run-{self.count[0]}.out"
        own = world_database(self.root, os.environ.get("PYTEST_XDIST_WORKER", "main"))
        WORLD_DATABASES.add(own)
        merged = {"DATABASE_NAME": own, **self.env, **(env or {})}
        done: Captured = run_to(sink, argv, self.root, _env(merged))
        return Ran(done.rc, done.text(), sink)

    def gate(self, *args: str, env: Mapping[str, str] | None = None) -> Ran:
        """`python -m quality.gate <args>` in the world, the Django leg skipped as the drive did."""
        return self.run(
            [PY, "-m", "quality.gate", *args], {"GATE_SKIP_DJANGO_LEG": "1", **(env or {})}
        )

    def forge(self, script: str, env: Mapping[str, str] | None = None) -> Ran:
        """A rule forged in memory over the world's engine: `python -c <script>`."""
        return self.run([PY, "-c", script], env)

    def with_env(self, **env: str) -> World:
        """The same world, every run carrying `env` too."""
        return World(self.root, self.logs, {**self.env, **env}, self.count)

    def git(self, *args: str) -> str:
        """A git command in the world; `CouldNotLook` when git refuses."""
        done = subprocess.run(
            ["git", "-C", str(self.root), *args], capture_output=True, text=True, env=_env(None)
        )
        if done.returncode != 0:
            raise CouldNotLook(f"git {' '.join(args)} in {self.root}: {done.stderr.strip()}")
        return done.stdout


def clone_world(home: Path, name: str) -> World:
    """A `--shared` clone of this checkout's HEAD at `home/name`, with this checkout's `.env`."""
    dest = home / name
    done = subprocess.run(
        ["git", "clone", "--quiet", "--shared", "--no-hardlinks", str(ROOT), str(dest)],
        capture_output=True,
        text=True,
        env=_env(None),
    )
    if done.returncode != 0:
        raise CouldNotLook(f"could not clone {ROOT} into {dest}: {done.stderr.strip()}")
    for key, value in (("user.email", "world@example.invalid"), ("user.name", "World")):
        subprocess.run(["git", "-C", str(dest), "config", key, value], check=True, env=_env(None))
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", dest / ".env")
    if (dest / "quality" / "local").exists():
        # Invariant: a product's own drawer leaves the world in a commit; these cases plant one.
        for argv in (["rm", "-rq", "quality/local"], ["commit", "-qm", "world: no drawer"]):
            subprocess.run(["git", "-C", str(dest), *argv], check=True, env=_env(None))
    if not (dest / "quality" / "gate.py").is_file() or (dest / "quality" / "local").exists():
        raise CouldNotLook(f"{dest} carries no engine, or carries a drawer these cases plant")
    logs = home / f"{name}-logs"
    logs.mkdir()
    return World(dest, logs)


def digest(root: Path) -> str:
    """HEAD, the porcelain status, the diff and every untracked file's bytes, hashed."""
    h = hashlib.sha256()
    for args in (
        ["rev-parse", "HEAD"],
        ["status", "--porcelain", "--untracked-files=all"],
        ["diff", "HEAD", "--binary"],
    ):
        h.update(
            subprocess.run(
                ["git", "-C", str(root), *args], capture_output=True, env=_env(None)
            ).stdout
        )
    untracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard", "-z"],
        capture_output=True,
        env=_env(None),
    ).stdout
    for rel in sorted(p for p in untracked.decode().split("\0") if p):
        h.update(rel.encode() + b"\0" + (root / rel).read_bytes())
    return h.hexdigest()


def moved_paths(root: Path, before: str) -> list[str]:
    """`moved: <path>` for every path the status names when the digest moved; [] when it held."""
    if digest(root) == before:
        return []
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        env=_env(None),
    ).stdout
    return [f"moved: {line[3:]}" for line in status.splitlines()] or ["moved: HEAD or bytes"]


@pytest.fixture(scope="session")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[World]:
    """The session's one clone; read-only between cases — every plant is restored in its case."""
    home = require_scratch(tmp_path_factory.mktemp("engine-explain"), ROOT)
    built = clone_world(home, "world")
    before = digest(built.root)
    built.env["DJB_WORLD_DIGEST"] = before
    yield built
    drop_world_databases()
    moved = moved_paths(built.root, before)
    if moved:
        raise CouldNotLook(f"the world {built.root} was left moved: " + "; ".join(moved))


@pytest.fixture
def memo_world(world: World, scratch: Path) -> World:
    """The world with `DJB_RULES_MEMO_DIR` at a fresh directory of this test's own."""
    home = scratch / "memo"
    home.mkdir()
    return world.with_env(DJB_RULES_MEMO_DIR=str(home))


@contextmanager
def created(root: Path, rel: str, text: str) -> Iterator[Path]:
    """Create `rel` and its missing directories."""
    target = root / rel
    if target.exists() or (target.parent.exists() and target.parent.name.startswith("zzz_")):
        raise CouldNotLook(
            f"the plant's path is already taken: {rel} in {Path(rel).parent} — a plant is "
            "created, never written over what is there"
        )
    made: list[Path] = []
    parent = target.parent
    while not parent.exists():
        made.append(parent)
        parent = parent.parent
    for d in reversed(made):
        d.mkdir()
    target.write_text(text)
    try:
        yield target
    finally:
        target.unlink(missing_ok=True)
        for d in made:
            if d.exists() and not any(d.iterdir()):
                d.rmdir()


@contextmanager
def appended(root: Path, rel: str, text: str) -> Iterator[Path]:
    """Append `text` to `rel`, restoring its saved bytes on the way out."""
    target = root / rel
    saved = target.read_bytes()
    target.write_bytes(saved + text.encode())
    try:
        yield target
    finally:
        target.write_bytes(saved)


JS_BARREL = (
    "// a re-export of a sibling directory: the shape rule 52 refuses\n"
    'export * from "./deal-card";\n'
)

READERS = r"""
import os
import re
import pathlib
import sys

import yaml

sys.argv = ["gate"]
from quality import gate

out = pathlib.Path(os.environ["DJB_READERS_DIR"])
probes = [
    ("explain-13", ["--explain", "13"]),
    ("explain-54", ["--explain", "54"]),
    ("explain-55", ["--explain", "55"]),
    ("explain-91", ["--explain", "91"]),
    ("explain-98", ["--explain", "98"]),
    ("explain-999", ["--explain", "999"]),
    ("listing-explain", ["--explain"]),
    ("listing-rules", ["--rules"]),
    ("unknown-flag", ["--tesre"]),
    ("fold-map-bare", ["--fold-map"]),
    ("fold-map-flag-next", ["--fold-map", "--rules"]),
    ("fold-map-self", ["--fold-map", "quality/rules.yaml"]),
    ("fold-map-second-missing", ["--fold-map", "quality/rules.yaml", "no-such-template.yaml"]),
    ("template-tree-orphan", ["--template-tree", "."]),
    ("fold-map-with-tree", ["--fold-map", "quality/rules.yaml", "--template-tree", "."]),
]
for name, argv in probes:
    rc, text = gate._captured(list(argv))
    (out / (name + ".log")).write_text(text, encoding="utf-8")
    (out / (name + ".rc")).write_text(str(rc), encoding="utf-8")
print("captured %d reader probes" % len(probes))
"""


@dataclass(frozen=True)
class Readers:
    """The reader probes, captured once in one process."""

    home: Path
    rule_count: int
    listed_count: int

    def __call__(self, name: str) -> Ran:
        """One probe's capture, as if `gate` had just run it."""
        rc = self.home / f"{name}.rc"
        if not rc.is_file():
            raise CouldNotLook(f"the reader capture left no status for {name}")
        log = self.home / f"{name}.log"
        return Ran(int(rc.read_text()), Captured(0, log).text(), log)


@pytest.fixture(scope="session")
def readers(world: World, tmp_path_factory: pytest.TempPathFactory) -> Readers:
    """`--explain`, the listing, `--fold-map` and an unknown flag."""
    home = tmp_path_factory.mktemp("readers")
    ran = world.forge(READERS, {"DJB_READERS_DIR": str(home)})
    if ran.rc != 0:
        raise CouldNotLook(ran.why("the reader capture did not complete"))
    doc = yaml.safe_load((world.root / "quality" / "rules.yaml").read_text())
    drawer = world.root / "quality" / "local" / "rules.yaml"
    local = yaml.safe_load(drawer.read_text()) if drawer.is_file() else None
    extra = len((local or {}).get("rules") or []) if isinstance(local, dict) else 0
    return Readers(home, len(doc["rules"]), len(doc["rules"]) + extra)


# -- the field --------------------------------------------------------------


def test_every_rule_declares_a_valve(world: World, readers: Readers) -> None:
    """Every rule in the yaml declares a valve."""
    text = (world.root / "quality" / "rules.yaml").read_text()
    declared = sum(1 for line in text.splitlines() if line.startswith("    valve:"))
    assert declared == readers.rule_count, (
        f"{declared} valve declarations for {readers.rule_count} rules — a rule that cannot say "
        "how to record a legitimate exception prints a red nobody can act on"
    )


# -- the world's own database ------------------------------------------------

DATABASE_PROBE = "import os; print(os.environ.get('DATABASE_NAME', ''))"


def test_two_worlds_on_two_workers_never_share_a_database(tmp_path: Path) -> None:
    """Two workers, or two worlds on one worker, derive two names; each `_hp` form is legal."""
    one, two = tmp_path / "one", tmp_path / "two"
    names = {
        world_database(one, "gw0"),
        world_database(one, "gw1"),
        world_database(two, "gw0"),
        world_database(two, "gw1"),
    }
    assert len(names) == 4, f"two worlds shared a database name: {sorted(names)}"
    assert os.environ.get("DATABASE_NAME") not in names, "a world named the checkout's database"
    assert all(re.fullmatch(r"[a-z0-9_]{1,60}", n) for n in names), sorted(names)


def test_the_world_runs_against_its_own_database(world: World) -> None:
    """Rule 35's probe in the world reaches the world's database, never the checkout's."""
    ran = world.forge(DATABASE_PROBE)
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    assert ran.rc == 0, ran.why("the probe did not run")
    assert ran.out.strip() != os.environ.get("DATABASE_NAME"), ran.why(
        "the world inherited the checkout's database, which every worker's world shares"
    )
    assert ran.out.strip() == world_database(world.root, worker), ran.why(
        f"the world ran against {ran.out.strip()!r}, not its own database"
    )


# -- the trailer ------------------------------------------------------------


@pytest.fixture(scope="session")
def red_plant(world: World) -> Ran:
    """The planted rule-1 red, scanned once; both trailer cases read this one scan."""
    plant = "\nfrom django.contrib.auth.models import User  # test_engine_explain plant\n"
    with appended(world.root, RED_TARGET, plant):
        return world.gate()


def test_a_red_carries_its_trailer_once_after_its_findings(red_plant: Ran) -> None:
    """Doc, valve, blind, next — four ASCII keys, once, after the finding."""
    assert red_plant.rc == 1, red_plant.why("a planted rule-1 import did not exit 1")
    lines = red_plant.out.splitlines()
    missing = [
        k
        for k in ("doc:", "valve:", "blind:", "next:")
        if not any(ln.lstrip().startswith(k) and ln.startswith(" ") for ln in lines)
    ]
    assert not missing, red_plant.why(f"the red's block is missing: {missing}")
    trailers = [ln for ln in lines if ln.strip() == "next:   python -m quality.gate --explain 1"]
    assert len(trailers) == 1, red_plant.why(f"the rule printed {len(trailers)} trailers, not one")


def test_the_trailers_valve_is_the_marker_a_reader_can_paste(red_plant: Ran) -> None:
    """The python finding is handed the hash form of its rule's marker."""
    assert any(
        ln.startswith(" ")
        and ln.strip().startswith("valve:")
        and ln.split("valve:", 1)[1].strip().startswith("# rule-1: <reason>")
        for ln in red_plant.out.splitlines()
    ), red_plant.why(
        "the valve line does not carry the pasteable marker for this finding's file kind"
    )


def test_a_frontend_finding_prints_the_slash_valve_token(world: World) -> None:
    """A frontend finding is handed `// rule-52`, and only that."""
    with created(world.root, JS_TARGET, JS_BARREL):
        ran = world.gate()
    assert ran.rc == 1, ran.why("a planted barrel did not exit 1")
    lines = [ln.strip() for ln in ran.out.splitlines() if ln.startswith(" ")]
    assert any(ln.startswith(f"x rule 52: {JS_TARGET}:") for ln in lines), ran.why(
        f"rule 52's finding does not name {JS_TARGET}"
    )
    valves = [ln.split("valve:", 1)[1].strip() for ln in lines if ln.startswith("valve:")]
    assert any(v.startswith("// rule-52: <reason>") for v in valves), ran.why("no // token")
    assert not any(v.startswith("# rule-52: <reason>") for v in valves), ran.why(
        "rule 52 printed a hash-token valve line for findings that are all .ts"
    )


def test_the_plant_refuses_a_path_that_already_exists(world: World) -> None:
    """An occupied plant path is could-not-look naming the file and the directory."""
    with created(world.root, JS_TARGET, JS_BARREL):
        with pytest.raises(CouldNotLook) as refused:
            with created(world.root, JS_TARGET, JS_BARREL):
                pass
        assert (world.root / JS_TARGET).read_text() == JS_BARREL
    said = str(refused.value)
    assert "already taken" in said and JS_TARGET in said and JS_PROBE_DIR in said, said


def test_the_drive_creates_no_frontend_tree_on_a_tree_that_has_none(scratch: Path) -> None:
    """The whole created chain is removed: a tree with no `frontend/` still has none."""
    with created(scratch, JS_TARGET, JS_BARREL) as made:
        assert made.is_file()
    assert not (scratch / "frontend").exists(), sorted(str(p) for p in scratch.rglob("*"))


def test_an_empty_capture_is_could_not_look(scratch: Path) -> None:
    """An empty capture is could-not-look naming the exit; a capture with bytes is judged."""
    empty = scratch / "empty.out"
    empty.write_text("")
    with pytest.raises(CouldNotLook, match=r"empty or absent \(exit 1\)"):
        Captured(1, empty).text()
    with pytest.raises(CouldNotLook, match="nothing was captured"):
        Captured(0, scratch / "absent.out").text()
    said = scratch / "said.out"
    said.write_text("the engine said something\n")
    assert Captured(1, said).text() == "the engine said something\n"


SESSION_MOVES = """
import subprocess
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


@pytest.fixture(scope="session")
def moved(tmp_path_factory):
    yield
    raise CouldNotLook("the world was left moved: moved: owned.txt")


def test_case(moved):
    {body}
"""


@pytest.mark.parametrize(
    ("body", "case"),
    [("assert True", "a green session"), ("assert False", "a red session")],
)
def test_the_exit_census_never_lowers_the_drives_own_status(
    nested_pytest: Callable[..., tuple[int, str]], body: str, case: str
) -> None:
    """A world left moved is could-not-look at teardown."""
    rc, out = nested_pytest({"test_moved.py": SESSION_MOVES.format(body=body)})
    assert rc == 2, f"{case}: exit {rc}\n{out}"
    assert "moved: owned.txt" in out, f"{case}: the teardown did not name the path\n{out}"


def test_the_drive_leaves_the_working_tree_as_it_found_it(
    world: World, scratch_repo: Callable[..., Path]
) -> None:
    """The world is as the session found it, and a deleted tracked file is named as moved."""
    assert not moved_paths(world.root, world.env["DJB_WORLD_DIGEST"]), moved_paths(
        world.root, world.env["DJB_WORLD_DIGEST"]
    )
    control = scratch_repo("control")
    (control / "owned.txt").write_text("a product ships this\n")
    subprocess.run(["git", "-C", str(control), "add", "owned.txt"], check=True)
    subprocess.run(["git", "-C", str(control), "commit", "-q", "-m", "seed"], check=True)
    before = digest(control)
    (control / "owned.txt").unlink()
    assert moved_paths(control, before) == ["moved: owned.txt"], moved_paths(control, before)


# -- the budget subject -----------------------------------------------------

PROBE_SERVICES = '"""Write operations for the probe app."""\n'
PROBE_FUNCTION = "\n\ndef create_probe(*, name: str) -> str:\n    return name\n"


def test_a_function_less_services_module_is_not_a_budget_subject(world: World) -> None:
    """No top-level def, no subject, no line to paste — the tree stays green."""
    with created(world.root, f"{PROBE_APP_DIR}/services.py", PROBE_SERVICES):
        ran = world.gate()
    assert ran.rc == 0, ran.why("a services.py holding no top-level def became a subject anyway")
    assert f"{PROBE_APP_DIR}/services.py" not in ran.out, ran.why("the engine named the module")


@pytest.fixture(scope="session")
def probe_function(world: World) -> Ran:
    """The probe app with one top-level def, scanned once; two cases read it."""
    with created(world.root, f"{PROBE_APP_DIR}/services.py", PROBE_SERVICES + PROBE_FUNCTION):
        return world.gate()


def test_one_function_is_a_subject_and_still_reds_without_a_ceiling(probe_function: Ran) -> None:
    """One def is one subject, named by function, and it fails until a human records it."""
    assert probe_function.rc == 1, probe_function.why("an unrecorded subject with a value passed")
    assert f"has no recorded ceiling for {PROBE_APP_DIR}/services.py — create_probe (lines " in (
        probe_function.out
    ), probe_function.why("the red does not name the module AND the function")


def test_a_new_function_subject_prints_its_paste_line(probe_function: Ran) -> None:
    """The remedy is a line the reader pastes into `quality/budgets.yaml`."""
    assert probe_function.rc == 1, probe_function.why("the remedy line was never printed")
    assert "The line to paste under `service_function_length:` in quality/budgets.yaml:" in (
        probe_function.out
    ), probe_function.why("the refusal stopped saying where the number goes")
    want = f"{PROBE_APP_DIR}/services.py: "
    assert any(
        ln.startswith(" ") and ln.strip().startswith(want) and ln.strip()[len(want) :].isdigit()
        for ln in probe_function.out.splitlines()
    ), probe_function.why("the pasteable line is not a `<key>: <measured>`")


FENCED_LENGTH = (
    "import sys\n"
    "from quality.engine.run import _measure_budgets_detailed, check_budgets\n"
    f'key = "{PROBE_APP_DIR}/services.py"\n'
    'print(_measure_budgets_detailed()["service_function_length"][key][0])\n'
    'problems = check_budgets({"service_function_length": {key: 3}, "out_schema_fields": {}})\n'
    "print(any(key in p and 'grew to' in p for p in problems))\n"
)
FENCED_BODY = "    b = a\n    # golden: noun end\n    # golden: noun begin\n    return b\n"


@pytest.mark.parametrize(
    ("body", "measured", "refused"),
    [
        ("    b = a\n    return b\n", "3", "False"),
        (FENCED_BODY, "3", "False"),
        ("    b = a\n    c = b\n    return c\n", "4", "True"),
    ],
)
def test_a_fence_line_inside_a_service_is_no_line_of_it(
    world: World, body: str, measured: str, refused: str
) -> None:
    """A `golden:` fence is a marker, as rule 91 reads it; a real line past the ceiling reds."""
    text = PROBE_SERVICES + "\n\ndef create_probe(*, a: int) -> int:\n" + body
    with created(world.root, f"{PROBE_APP_DIR}/services.py", text):
        ran = world.forge(FENCED_LENGTH)
    assert ran.out.split()[-2:] == [measured, refused], ran.why("the fence lines were counted")


# -- the readers ------------------------------------------------------------


def test_explain_prints_the_rules_own_declaration(readers: Readers) -> None:
    """The statement, the mechanism, the valve and the blind spot, read from the yaml."""
    ran = readers("explain-13")
    assert ran.rc == 0, ran.why("--explain 13 did not answer")
    for want in (
        "statement:",
        "valve:",
        "Every public write in services.py is @service",
        "does_not_cover:",
    ):
        assert want in ran.out, ran.why(f"--explain 13 did not print {want!r}")


def _floors_by_hand(root: Path, rid: str, counts: tuple[str, ...]) -> tuple[int, int]:
    """(lines, members) of `rid`'s floors in `counts`, summed from the two homes' own text."""
    held: dict[str, int] = {}
    for config in sorted(root.glob("apps/*/apps.py")):
        for key, value in re.findall(rf'"{rid}\.([\w-]+)": (\d+)', config.read_text()):
            if key in counts and int(value):
                held[config.parent.name] = held.get(config.parent.name, 0) + int(value)
    platform = yaml.safe_load((root / "quality/ratchet_floors.yaml").read_text())[rid] or {}
    for klass, value in platform.items():
        member, _, key = str(klass).partition(".")
        if key in counts and int(value):
            held[member] = held.get(member, 0) + int(value)
    return sum(held.values()), len(held)


@pytest.mark.parametrize(
    ("rid", "counts"),
    [
        ("91", ("docstring-tail", "module-tail", "block-tail", "narrative")),
        ("98", ("lines",)),
    ],
)
def test_explain_names_a_ratchet_over_debt_by_its_own_sum(
    world: World, readers: Readers, rid: str, counts: tuple[str, ...]
) -> None:
    """`--explain 91`/`98` say they are ratchets over debt, in the figure the floors add to."""
    ran = readers(f"explain-{rid}")
    lines, members = _floors_by_hand(world.root, rid, counts)
    want = f"a ratchet over recorded debt: {lines} lines across {members} members, down-only since "
    assert ran.rc == 0 and want in ran.out, ran.why(f"--explain {rid} did not say {want!r}")
    assert "a standard for NEW files" in ran.out, ran.why("the line stopped naming what it binds")


def test_explain_of_an_unknown_id_is_exit_2_naming_the_listing(readers: Readers) -> None:
    """An unknown id is could-not-look, and says where the ids are."""
    ran = readers("explain-999")
    assert ran.rc == 2 and "listing" in ran.out, ran.why("--explain 999 did not name the listing")


def test_the_listing_is_the_same_under_both_names(readers: Readers) -> None:
    """One line per rule, byte-identical under `--explain` and `--rules`."""
    bare, rules = readers("listing-explain"), readers("listing-rules")
    assert bare.rc == 0 and rules.rc == 0, rules.why(f"the listing exited {bare.rc}/{rules.rc}")
    assert bare.out == rules.out, rules.why("bare --explain and --rules printed different things")
    listed = sum(1 for line in rules.out.splitlines() if line)
    assert listed == readers.listed_count, rules.why(
        f"the listing printed {listed} lines for {readers.listed_count} rules "
        f"({readers.rule_count} template + {readers.listed_count - readers.rule_count} drawer)"
    )


def test_explain_prints_a_remedy_per_finding_class(readers: Readers) -> None:
    """Rule 54 prints three remedies (nonconforming, role-value."""
    ran = readers("explain-54")
    remedies = [ln for ln in ran.out.splitlines() if ln.startswith("remedies: ")]
    assert ran.rc == 0 and len(remedies) == 3, ran.why(f"{len(remedies)} remedies lines, not 3")
    for klass, form in (
        ("nonconforming", "RENAMED_PERMISSIONS"),
        ("role-value", "holds(actor"),
        ("read", "require(actor"),
    ):
        assert any(ln.startswith(f"remedies: {klass} ") and form in ln for ln in remedies), ran.why(
            f"no {klass} remedy naming {form}"
        )
    ran = readers("explain-55")
    remedies = [ln for ln in ran.out.splitlines() if ln.startswith("remedies: ")]
    assert ran.rc == 0 and len(remedies) == 1 and remedies[0].startswith("remedies: * "), ran.why(
        "rule 55's per-app classes share exactly one remedy"
    )


def test_an_unknown_flag_is_still_exit_2(readers: Readers) -> None:
    """A mistyped flag is never a silently different run."""
    ran = readers("unknown-flag")
    assert ran.rc == 2 and "unknown argument" in ran.out, ran.why("--tesre became a smaller gate")


def test_the_refusal_names_every_argument_the_engine_takes(readers: Readers) -> None:
    """The unknown-argument sentence names all eight arguments."""
    ran = readers("unknown-flag")
    flags = (
        "--selftest",
        "--selftest-inputs",
        "--diff",
        "--fold-map",
        "--terse",
        "--explain",
        "--rules",
        "--backlog",
    )
    missing = [f for f in flags if f not in ran.out]
    assert not missing, ran.why(f"the grammar sentence does not name {missing}")


def test_fold_map_with_no_argument_refuses_with_the_grammar(readers: Readers) -> None:
    """A bare `--fold-map` is exit 2 carrying the command that produces the file it needs."""
    ran = readers("fold-map-bare")
    assert ran.rc == 2, ran.why("a bare --fold-map was not refused")
    for want in (
        "PREVIOUS quality/rules.yaml",
        "git show <your pre-merge sha>:quality/rules.yaml",
        "--fold-map <previous rules.yaml>",
    ):
        assert want in ran.out, ran.why(f"the refusal does not carry {want!r}")


def test_fold_map_does_not_eat_the_next_flag_as_a_path(readers: Readers) -> None:
    """`--fold-map` refuses a following flag rather than reading it as a path."""
    ran = readers("fold-map-flag-next")
    assert ran.rc == 2 and "PREVIOUS quality/rules.yaml" in ran.out, ran.why(
        "a flag became a filename"
    )


def test_fold_map_of_this_tree_against_itself_has_nothing_to_do(readers: Readers) -> None:
    """The template maps onto itself: every rule unchanged, no fixture out of place."""
    ran = readers("fold-map-self")
    assert ran.rc == 0 and " → " not in ran.out, ran.why("the self-map renamed something")
    assert "unchanged; nothing to renumber" in ran.out, ran.why("no 'nothing to renumber' line")
    assert "every template fixture on this tree is at the path it ships at" in ran.out, ran.why(
        "a fixture is out of place"
    )


def test_the_grammar_names_the_two_argument_fold_map(readers: Readers) -> None:
    """The grammar names the template side as an argument and `--template-tree` beside it."""
    ran = readers("unknown-flag")
    assert "--fold-map <previous rules.yaml> [<template rules.yaml>]" in ran.out, ran.why(
        "no two-argument --fold-map"
    )
    assert "--template-tree <dir>" in ran.out, ran.why("no --template-tree <dir>")


def test_fold_map_second_argument_that_is_not_a_file_is_exit_2(readers: Readers) -> None:
    """A template side nobody can read is exit 2 naming the file."""
    ran = readers("fold-map-second-missing")
    assert ran.rc == 2 and "COULD NOT LOOK" in ran.out and "no-such-template.yaml" in ran.out, (
        ran.why("an unreadable second path was not refused by name")
    )


def test_template_tree_inside_fold_map_is_the_road_it_exists_for(readers: Readers) -> None:
    """`--fold-map <previous> --template-tree <dir>` runs: the flag is reachable from the CLI."""
    ran = readers("fold-map-with-tree")
    assert ran.rc == 0 and "only meaningful" not in ran.out, ran.why(
        "--template-tree is dead from the CLI"
    )


def test_template_tree_without_fold_map_is_exit_2(readers: Readers) -> None:
    """`--template-tree` outside `--fold-map` is refused rather than ignored."""
    ran = readers("template-tree-orphan")
    assert ran.rc == 2 and "only meaningful with --fold-map" in ran.out, ran.why(
        "an orphan --template-tree ran"
    )


# -- --terse, the standing section, the backlog ------------------------------


@dataclass(frozen=True)
class Scans:
    """The plain and the `--terse` live scans of the world, taken once."""

    plain: Ran
    terse: Ran


@pytest.fixture(scope="session")
def scans(world: World) -> Scans:
    """Two memo-off live scans of the unplanted world, so case order cannot move their lines."""
    cold = {"DJB_RULES_NO_MEMO": "1"}
    return Scans(world.gate(env=cold), world.gate("--terse", env=cold))


def test_terse_keeps_the_count_and_drops_only_the_ok_lines(scans: Scans) -> None:
    """The difference is exactly the ok rows and the standing valve rows — nothing else."""
    import re

    assert scans.plain.rc == scans.terse.rc, scans.terse.why(
        f"--terse changed the exit from {scans.plain.rc}"
    )
    assert re.search(
        r"^House rules: \d+ rules · \d+ ok · \d+ RED · \d+ skipped", scans.terse.out, re.M
    ), scans.terse.why("--terse dropped the count line")
    kept = set(scans.terse.out.splitlines())
    only_plain = [ln for ln in scans.plain.out.splitlines() if ln not in kept]
    row = re.compile(r": ok \(|^  [a-z][a-z0-9-]* [^ ]+:[0-9]+ — ")
    stray = [ln for ln in only_plain if not row.search(ln)]
    assert only_plain and not stray, scans.terse.why(f"--terse also dropped {stray[:5]}")


FROZEN_LINE = (
    r"^frozen: [0-9]+ class\(es\) · [0-9]+ recorded · base "
    r"([0-9a-f]{7} \((origin/main|main|origin/main, main|HEAD only)\)"
    r"|[0-9a-f]{7} \(origin/main\), [0-9a-f]{7} \(main\)|none \(no commit yet\))$"
)


def test_the_standing_section_prints_declared_backlog_and_frozen(scans: Scans) -> None:
    """`declared:`."""
    import re

    for mode, ran in (("plain", scans.plain), ("terse", scans.terse)):
        lines = ran.out.splitlines()
        heads = [
            i
            for i, ln in enumerate(lines)
            if re.fullmatch(r"valves \(standing\): rule-<id> [0-9]+", ln)
        ]
        assert heads, ran.why(f"{mode}: no rule-<id> token line")
        block = lines[heads[-1] + 1 : heads[-1] + 4]
        assert len(block) == 3 and re.fullmatch(r"declared: [0-9]+", block[0]), ran.why(
            f"{mode}: {block}"
        )
        assert re.fullmatch(
            r"backlog: [0-9]+ \(ratchet [0-9]+ · dated-past [0-9]+ · coordinate [0-9]+ · "
            r"memo-pending [0-9]+ · frozen-rerecord [0-9]+\)",
            block[1],
        ), ran.why(f"{mode}: {block[1]!r}")
        assert re.fullmatch(FROZEN_LINE[1:-1], block[2]), ran.why(f"{mode}: {block[2]!r}")
        assert sum(" · base " in ln for ln in lines) == 1, ran.why(
            f"{mode}: the base is not printed once"
        )


def test_backlog_lists_one_line_per_held_finding(world: World, scans: Scans) -> None:
    """`--backlog` prints one shaped line per ratchet-held finding, exits as the plain run."""
    import re

    held = re.search(r"^backlog: [0-9]+ \(ratchet ([0-9]+) ", scans.plain.out, re.M)
    ran = world.gate("--backlog", env={"DJB_RULES_NO_MEMO": "1"})
    assert ran.rc == scans.plain.rc, ran.why(
        f"--backlog exited where the plain run exited {scans.plain.rc}"
    )
    lines = [ln for ln in ran.out.splitlines() if ln.startswith("rule ")]
    shaped = [ln for ln in lines if re.match(r"^rule [^ ]+ · [^ ]+ · [^ ]+:[0-9]+ · .+", ln)]
    assert held and len(lines) == int(held.group(1)) == len(shaped), ran.why(
        f"{len(lines)} line(s), {len(shaped)} shaped, "
        f"where backlog: counts ratchet {held and held.group(1)}"
    )
    short = world.forge(
        "import sys\nfrom quality import gate\ngate.HELD_FINDINGS.clear()\ngate.broken.clear()\n"
        "gate.backlog_listing(1)\nprint(gate.broken[0] if gate.broken else 'NOTHING REFUSED')\n"
        "sys.exit(0 if gate.broken else 1)\n"
    )
    assert short.rc == 0, short.why("a --backlog listing shorter than its census was not refused")


# -- the freeze, in a repository of the test's own ----------------------------

FROZEN_PICK = r"""
import pathlib
import sys

import yaml

want = sys.argv[1]
sys.argv = ["gate"]
from quality import gate

HOME = "quality/rules.yaml"
path = pathlib.Path(gate.ROOT) / HOME
text = path.read_text(encoding="utf-8")
items = {}
top = yaml.compose(text, Loader=yaml.SafeLoader)
for item in next(v for k, v in top.value if k.value == "rules").value:
    ident = next((v.value for k, v in item.value if k.value == "id"), None)
    items[str(ident)] = item
recorded, unrecorded = [], []
for rule in gate.RULES:
    rid = str(rule["id"])
    if gate.is_local_rule(rid) or gate.is_member_rule(rule):
        continue
    for klass in sorted(gate.frozen_classes(rule)):
        if gate.frozen_file(rid, klass) != HOME:
            continue
        entry = gate.recorded_number(text, HOME, rid, klass)
        if entry:
            recorded.append((rid, klass, entry[0], entry[1]))
            continue
        key, block = next(
            ((k, v) for k, v in items[rid].value if k.value == "ratchets"), (None, None)
        )
        if isinstance(block, yaml.MappingNode) and block.value and not block.flow_style:
            column = block.value[0][0].start_mark.column
            unrecorded.append((rid, klass, column, key.start_mark.line + 1))
        elif isinstance(block, yaml.ScalarNode) and block.value in ("", "~", "null"):
            unrecorded.append((rid, klass, key.start_mark.column + 2, key.start_mark.line + 1))
lines = text.splitlines(keepends=True)
planted = 0
if want == "recorded" and not recorded and unrecorded:
    rid, klass, indent, at = unrecorded[0]
    lines.insert(at, " " * indent + f"{klass}: 1\n")
    recorded, planted = [(rid, klass, 1, at + 1)], 1
elif want == "unrecorded" and not unrecorded and recorded:
    rid, klass, number, at = recorded[0]
    indent = len(lines[at - 1]) - len(lines[at - 1].lstrip())
    del lines[at - 1]
    unrecorded, planted = [(rid, klass, indent, at - 1)], 1
pool = recorded if want == "recorded" else unrecorded
if not pool:
    raise SystemExit(f"no frozen class with a {HOME} home on a template rule")
if planted:
    path.write_text("".join(lines), encoding="utf-8")
print(*pool[0], planted)
"""


@dataclass
class Frozen:
    """One frozen class picked in a repository of the test's own."""

    world: World
    rule: str
    klass: str
    value: int
    line: int
    planted: bool

    @property
    def rules(self) -> Path:
        """The repository's `quality/rules.yaml`."""
        return self.world.root / "quality" / "rules.yaml"

    def edit_line(self, edit: Callable[[str], str]) -> None:
        """Rewrite the class's own line (1-based) of `quality/rules.yaml`."""
        lines = self.rules.read_text().splitlines(keepends=True)
        lines[self.line - 1] = edit(lines[self.line - 1])
        self.rules.write_text("".join(lines))


def repo_world(scratch_repo: Callable[..., Path], scratch: Path, world: World, name: str) -> World:
    """A `scratch_repo` holding the world's HEAD as its second commit, on `main`."""
    repo = scratch_repo(name)
    tar = scratch / f"{name}.tar"
    with tar.open("wb") as sink:
        subprocess.run(["git", "-C", str(world.root), "archive", "HEAD"], stdout=sink, check=True)
    with tarfile.open(tar) as archive:
        archive.extractall(repo, filter="tar")
    tar.unlink()
    built = World(repo, scratch / f"{name}-logs")
    built.logs.mkdir()
    built.git("add", "-A")
    built.git("commit", "-q", "-m", "the world's tree")
    return built


def pick_frozen(repo: World, want: str) -> Frozen:
    """The first frozen class `want` (recorded / unrecorded)."""
    ran = repo.run([PY, "-c", FROZEN_PICK, want])
    words = ran.out.split()
    if ran.rc != 0 or len(words) != 5:
        raise CouldNotLook(ran.why("the frozen-class reader did not print five words"))
    rid, klass, value, line, planted = words
    if planted == "1":
        repo.git("commit", "-q", "-m", f"plant: frozen {klass} {rid}", "--", "quality/rules.yaml")
    return Frozen(repo, rid, klass, int(value), int(line), planted == "1")


@pytest.fixture
def frozen_repo(scratch_repo: Callable[..., Path], scratch: Path, world: World) -> World:
    """The world's tree committed into a `scratch_repo` — the freeze's git cases plant there."""
    return repo_world(scratch_repo, scratch, world, "frozen")


def test_a_drawer_recording_a_frozen_class_is_exit_2(frozen_repo: World) -> None:
    """A drawer recording a frozen class is exit 2 naming the class."""
    picked = pick_frozen(frozen_repo, "recorded")
    (frozen_repo.root / "quality" / "local").mkdir()
    (frozen_repo.root / "quality" / "local" / "rules.yaml").write_text(
        f'ratchets:\n  "{picked.rule}": {{ {picked.klass}: 1 }}\n'
    )
    ran = frozen_repo.gate("--terse")
    assert ran.rc == 2 and f"class '{picked.klass}' is frozen on rule {picked.rule}" in ran.out, (
        ran.why("a drawer lifted a frozen class")
    )


def test_a_raised_frozen_number_is_exit_2(frozen_repo: World) -> None:
    """A frozen number raised in the working tree is exit 2 naming the class and both numbers."""
    import re

    picked = pick_frozen(frozen_repo, "recorded")
    was = picked.value
    picked.edit_line(
        lambda ln: re.sub(rf"^(\s*{re.escape(picked.klass)}:\s*){was}\b", rf"\g<1>{was + 1}", ln)
    )
    ran = frozen_repo.gate("--terse")
    want = (
        f"frozen class '{picked.klass}' is recorded at {was + 1} in quality/rules.yaml, "
        f"above the {was}"
    )
    assert ran.rc == 2 and want in ran.out, ran.why("a raised frozen number was accepted")


def test_a_returned_frozen_line_is_exit_2(frozen_repo: World) -> None:
    """A frozen class at zero coming back at 1 is exit 2 naming the class."""
    picked = pick_frozen(frozen_repo, "unrecorded")
    picked.edit_line(lambda ln: ln + " " * picked.value + f"{picked.klass}: 1\n")
    ran = frozen_repo.gate("--terse")
    want = (
        f"frozen class '{picked.klass}' is recorded at 1 in quality/rules.yaml, "
        "and HEAD records no line for it"
    )
    assert ran.rc == 2 and want in ran.out, ran.why("a returned frozen line was accepted")


def test_a_committed_frozen_raise_is_exit_2(frozen_repo: World) -> None:
    """A frozen number raised in a commit is exit 2 against the fold base."""
    import re

    picked = pick_frozen(frozen_repo, "recorded")
    pre = frozen_repo.git("rev-parse", "HEAD").strip()
    frozen_repo.git("checkout", "-q", "--detach")
    frozen_repo.git("update-ref", "refs/remotes/origin/main", pre)
    frozen_repo.git("update-ref", "refs/heads/main", pre)
    was = picked.value
    picked.edit_line(
        lambda ln: re.sub(rf"^(\s*{re.escape(picked.klass)}:\s*){was}\b", rf"\g<1>{was + 1}", ln)
    )
    frozen_repo.git("commit", "-q", "-m", f"raise {picked.klass}", "--", "quality/rules.yaml")
    ran = frozen_repo.gate("--terse")
    tail = (
        f"and the fold base {pre[:12]} records no line for it"
        if picked.planted
        else f"above the {was} it held at the fold base {pre[:12]}"
    )
    want = f"frozen class '{picked.klass}' is recorded at {was + 1} in quality/rules.yaml, {tail}"
    assert ran.rc == 2 and want in ran.out, ran.why("a committed frozen raise was accepted")


def test_a_repository_with_no_commit_prints_base_none(frozen_repo: World, scratch: Path) -> None:
    """No commit yet: `base none` printed, no frozen could-not-look, the committed tree's exit."""
    import re

    born = frozen_repo.gate("--terse")
    unborn_root = scratch / "unborn"
    shutil.copytree(frozen_repo.root, unborn_root, ignore=shutil.ignore_patterns(".git"))
    subprocess.run(["git", "-C", str(unborn_root), "init", "-q"], check=True, env=_env(None))
    unborn = World(unborn_root, frozen_repo.logs, count=frozen_repo.count)
    ran = unborn.gate("--terse")
    assert ran.rc == born.rc, ran.why(
        f"the unborn tree exited where the committed one exited {born.rc}"
    )
    assert re.search(
        r"^frozen: [0-9]+ class\(es\) · [0-9]+ recorded · base none \(no commit yet\)$",
        ran.out,
        re.M,
    ), ran.why("no `base none (no commit yet)` line")
    assert "FROZEN COULD NOT LOOK" not in ran.out, ran.why(
        "a repository with no commit could not look"
    )


# -- the memo's window, in the world ------------------------------------------

MEMO_RULE_1 = r"""
import sys
sys.argv = ["gate"]
from quality import gate

gate.memo_reset()
kept, targets, skip = gate.run_rule(gate.RULES_BY_ID["1"])
gate.memo_report()
for finding in kept:
    print("finding: %s" % finding)
for problem in gate.broken:
    print("!! %s" % problem)
sys.exit(2 if gate.broken or skip else (1 if kept else 0))
"""

MEMO_PROBE = """#!/bin/sh
[ "$1" = "1" ] || exit 0
cat quality/canary/1/import_user.py >>apps/example/services.py
"""


def test_a_tree_that_moves_between_keying_and_scanning_banks_nothing(
    memo_world: World, scratch: Path
) -> None:
    """A scan that read a plant made after its key reds honestly, banks nothing and says why."""
    probe = scratch / "memo-probe"
    probe.write_text(MEMO_PROBE)
    probe.chmod(0o755)
    home = Path(memo_world.env["DJB_RULES_MEMO_DIR"])
    try:
        first = memo_world.forge(MEMO_RULE_1, {"DJB_RULES_MEMO_PROBE_AFTER_KEY": str(probe)})
    finally:
        memo_world.git("checkout", "-q", "--", "apps/example/services.py")
    banked = sorted((home / "1").glob("*.json")) if (home / "1").is_dir() else []
    second = memo_world.forge(MEMO_RULE_1)
    assert first.rc == 1, first.why("the moved scan did not red")
    assert "apps/example/services.py:" in first.out and "auth" in first.out, first.why(
        "no rule-1 finding"
    )
    assert "rule 1: memo write refused — the tree moved during the scan (" in first.out, first.why(
        "the refusal was not printed"
    )
    assert " refused) · " in first.out, first.why("the memo line does not count the refusal")
    assert not banked, f"a finding from a moved tree was banked: {banked}"
    assert second.rc == 0, second.why("the unplanted tree's next run is not green")


# -- forged in memory over the world's engine -----------------------------


def test_a_rule_with_no_valve_is_enforcement_broken(world: World) -> None:
    """Consistency() names the rule that declared neither form."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
rid = str(victim["id"])
victim.pop("valve", None)
gate.broken.clear()
gate.consistency()
hits = [b for b in gate.broken if b.startswith("rule " + rid + ": no valve")]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a rule with no valve did not become ENFORCEMENT BROKEN naming itself"
    )


def test_a_none_valve_with_no_sentence_is_enforcement_broken(world: World) -> None:
    """A none-form claim under the reason floor is exit 2, not a quieter trailer."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
victim["valve"] = {"none": "nope"}
gate.broken.clear()
gate.consistency()
hits = [b for b in gate.broken if "none:" in b and str(victim["id"]) in b]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a one-word none-form reason passed — the claim that nothing can excuse a rule is "
        "exactly the claim owing a sentence"
    )


def test_a_valve_declaring_both_forms_is_enforcement_broken(world: World) -> None:
    """A reader is never told there is no valve and handed one."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
victim["valve"] = {"none": "there is nothing at all to excuse here", "marker": "# x: <reason>"}
gate.broken.clear()
gate.consistency()
hits = [b for b in gate.broken if "AND a marker" in b]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
"""
    )
    assert ran.rc == 0, ran.why("a valve declaring the none form and a marker at once was accepted")


def test_the_budget_trailer_names_the_budget_file(world: World) -> None:
    """A budget violation says where its number lives instead of faking a rules.yaml entry."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
lines = gate.trailer_for("")
print("\n".join(lines))
sys.exit(0 if len(lines) == 1 and "quality/budgets.yaml" in lines[0] else 1)
"""
    )
    assert ran.rc == 0, ran.why("a violation with no rule id did not get the budget trailer")


def test_a_rule_whose_trailer_lost_a_key_is_enforcement_broken(world: World) -> None:
    """A fired canary whose rule cannot explain its red is exit 2, naming the key."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
victim = gate.RULES[0]
victim["does_not_cover"] = ""
gate.broken.clear()
gate.trailer_census([str(victim["id"])])
hits = [b for b in gate.broken if "RED WITHOUT A TRAILER" in b and "blind:" in b]
print("\n".join(gate.broken))
sys.exit(0 if hits else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a rule with an empty does_not_cover produced a trailer the census accepted"
    )


def test_a_rule_with_findings_in_two_kinds_prints_both_valve_tokens(world: World) -> None:
    """One rule, two finding kinds, two valve lines — one each, neither duplicated."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
lines = gate.rule_trailer(gate.RULES_BY_ID["52"], {"#", "//"})
valves = [ln for ln in lines if ln.strip().startswith("valve:")]
print("\n".join(lines))
hash_form = [ln for ln in valves if "# rule-52: <reason>" in ln]
slash_form = [ln for ln in valves if "// rule-52: <reason>" in ln]
sys.exit(0 if len(valves) == 2 and len(hash_form) == 1 and len(slash_form) == 1 else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a rule whose findings span two kinds did not print one pasteable marker per kind"
    )


def test_the_trailer_and_cli_censuses_print_and_are_asserted(world: World) -> None:
    """Both censuses say they ran, and deleting either call is red here."""
    ran = world.forge(
        r"""
import ast, contextlib, inspect, io, pathlib, sys
sys.argv = ["gate"]
from quality import gate

def called_in_selftest(source):
    tree = ast.parse(source)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "selftest"
    )
    return {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }

source = pathlib.Path(inspect.getsourcefile(gate.selftest)).read_text()
problems = []
wired = called_in_selftest(source)
for name in ("trailer_census", "cli_census"):
    if name not in wired:
        problems.append(name + ": selftest() does not call it — the instrument is not wired in")

buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    gate.trailer_census(["1"])
    gate.cli_census()
printed = buf.getvalue()
# The probe count is the recorded engine number (`engine: cli: probes` in
# quality/rules.yaml), read rather than typed, so the drive and the leg agree.
cli_probes = gate.engine_number("cli", "probes")
for claim in (
    "trailer census: 1 rule(s) with findings, every one carried its four lines",
    f"cli census: --explain/--rules answered {cli_probes} of {cli_probes} probes",
):
    if claim not in printed:
        problems.append("not printed on success: " + claim)

# THE CONTROL. An assertion that cannot see the deletion it exists to catch is
# not an assertion: the same call-site read, over a copy of the source with the
# call removed, has to come back empty.
for name in ("trailer_census", "cli_census"):
    without = "\n".join(
        line for line in source.splitlines()
        if not line.strip().startswith(name + "(")
    )
    if name in called_in_selftest(without):
        problems.append("the control: " + name + " was deleted and the case still passed")

print(printed)
print("\n".join(problems))
sys.exit(1 if problems else 0)
"""
    )
    assert ran.rc == 0, ran.why(
        "a census ran silently, or its call could be deleted without this case noticing"
    )


def test_a_finding_of_a_remedied_rule_names_its_fix_form(world: World) -> None:
    """A finding of a rule that declares remedies ends with 'fix form: --explain 54'."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate

gate.record_violation("54", "apps/acme/selectors.py:12: asks no gadget.read")
with_remedy = gate.violations[-1]
gate.record_violation("13", "apps/acme/services.py:3: a write outside a service")
without = gate.violations[-1]
print("54:", with_remedy)
print("13:", without)
sys.exit(
    0
    if with_remedy.endswith("fix form: --explain 54") and "fix form" not in without
    else 1
)
"""
    )
    assert ran.rc == 0, ran.why(
        "the fix-form pointer is missing from a remedied rule's finding, or was added to a "
        "rule that has no remedies"
    )


def test_an_unmeasured_class_prints_the_line_to_paste(world: World) -> None:
    """A class keyed on an app outside the partition with no entry is still exit 1 and prints."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import Finding

hit = Finding("apps/acme/selectors.py", 12, "asks no gadget.read", "acme.read")
unrecorded = gate.apply_ratchets({"id": "54", "ratchets": {}}, [hit])
headers = [f for f in unrecorded if f.path == "quality/rules.yaml"]
kept = [f for f in unrecorded if f.path != "quality/rules.yaml"]
recorded = gate.apply_ratchets({"id": "54", "ratchets": {"acme.read": 1}}, [hit])
template_app = gate.apply_ratchets(
    {"id": "54", "ratchets": {}},
    [Finding("apps/core/selectors.py", 12, "asks no gadget.read", "core.read")],
)
paste = "acme.read: 1  # recorded-at %s [fold]" % gate.recording_sha()
print("headers:", [f.msg for f in headers])
print("kept:", [str(f) for f in kept])
print("after recording:", [str(f) for f in recorded])
print("template app:", [str(f) for f in template_app])
ok = (
    len(headers) == 1
    and paste in headers[0].msg
    and "apps/acme" in headers[0].msg
    and "platform_apps" in headers[0].msg
    and "quality/local/rules.yaml" in headers[0].msg
    and chr(34) + "54" + chr(34) + ":" in headers[0].msg
    and len(kept) == 1
    and not recorded
    and not [f for f in template_app if f.path == "quality/rules.yaml"]
    and len(template_app) == 1
)
sys.exit(0 if ok else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "the unmeasured branch did not print the line to paste, softened the violation, or "
        "offered a template app a recording"
    )


def test_a_kept_road_is_silent_and_counted_in_both_carriers(world: World) -> None:
    """A declared second road is silent in BOTH carriers and the standing override census gains."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate

rule = gate.RULES_BY_ID["84"]
canary = gate.fixture_home("canary", "84")
negative = gate.fixture_home("negative", "84")
# Assembled, so this drive does not itself carry a valve the census would count.
valve = "# rule" + "-84: this product kept its own teller and every caller of ours reads it\n"
before = [row for row in gate.all_overrides() if row[0] == "84"]
plant = gate.Plant()
rc = 1
try:
    services = "apps/zzz_canary/services.py"
    plant.put(negative / "kept_road_with_valve.py", services, "append", rid="84")
    plant.put(negative / "kept_road_twin.py", "apps/zzz_canary/selectors.py", "append", rid="84")
    twin = "scripts/zzz_canary/a_road.sh"
    plant.put(canary / "second_shell_road_twin.sh", twin, "create", rid="84")
    plant.put(canary / "second_shell_road.sh", "scripts/zzz_canary/road.sh", "create", rid="84")
    target = gate.ROOT / "scripts/zzz_canary/road.sh"
    text = target.read_text()
    marker = text.index("# road:")
    target.write_text(text[:marker] + valve + text[marker:])
    kept, _t, why = gate.run_rule(rule, floors=False, ratchets=False)
    after = [row for row in gate.all_overrides() if row[0] == "84"]
finally:
    plant.restore()
second = [str(f) for f in kept if f.klass == "second_road"]
added = sorted(r[1] for r in after if r not in before)
print("second_road findings:", second)
print("valves added:", added, "why:", repr(why))
want = ["apps/zzz_canary/services.py", "scripts/zzz_canary/road.sh"]
rc = 0 if (not second and not why and added == want) else 1
sys.exit(rc)
"""
    )
    assert ran.rc == 0, ran.why(
        "a kept road fired, or its valve was not counted in the standing census"
    )


def test_a_product_valve_suppresses_and_is_counted(world: World) -> None:
    """Under a declared namespace a rule-acme-1 valve suppresses the product rule's own finding."""
    ran = world.forge(
        r"""
import copy
import pathlib
import shutil
import sys
sys.argv = ["gate"]
from quality import gate

# THE FORGED ID IS ONE THIS TREE DOES NOT OWN. A product whose
# namespace is `acme` numbers its first drawer rule acme-1, and a typed id
# then collided with that rule and with its fixture directory.
RID = next(
    f"acme-{n}"
    for n in range(1, 1000)
    if f"acme-{n}" not in gate.RULES_BY_ID
    and not any(
        (d / f"acme-{n}").exists()
        for d in (
            gate.CANARY_DIR, gate.NEGATIVE_DIR, gate.LOCAL_CANARY_DIR, gate.LOCAL_NEGATIVE_DIR
        )
    )
)
rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = RID
# THE HOME IS ASKED FOR, NEVER SPELLED. `fixture_home` is the ONE resolver
# — a rule loaded from the product drawer lives under the drawer, a rule in
# the template document under the template tree — and a drive that typed
# either would be one more place teaching a product where its fixtures go.
# This forged rule is appended to the list the TEMPLATE document declares,
# rather than loaded from the drawer, so the resolver answers the template
# tree for it;
# a real product rule comes out of the drawer, and the case that plants one
# there is case_a_drawer_rule_is_a_rule_end_to_end.
made = []
for kind in ("canary", "negative"):
    dst = gate.fixture_home(kind, RID)
    shutil.copytree(gate.fixture_home(kind, "1"), dst)
    made.append(dst)
through = max(int(r["id"]) for r in gate.RULES if gate.is_template_id(str(r["id"])))
entry = rule["canaries"][0]
rc = 1
try:
    with gate._as_product_tree("acme", through):
        plant = gate.Plant()
        try:
            plant.put(
                gate.fixture_home("canary", RID) / entry["fixture"],
                entry["plant_at"],
                entry["mode"],
            )
            bare, _t, _why = gate.run_rule(rule, floors=False)
            if not bare:
                raise SystemExit(1)
            target = pathlib.Path(gate.ROOT) / bare[0].path
            lines = target.read_text().splitlines()
            index = bare[0].line - 1
            valve = "  # rule-" + RID + ": the product excuses its own rule here"
            lines[index] = lines[index] + valve
            target.write_text("\n".join(lines) + "\n")
            valved, _t2, _why2 = gate.run_rule(rule, floors=False)
            counted = [
                row
                for row in gate.all_overrides()
                if row[0] == RID and row[1] == bare[0].path
            ]
        finally:
            plant.restore()
    print("unvalved:", [str(f) for f in bare])
    print("valved:", [str(f) for f in valved])
    print("counted:", counted)
    rc = 0 if (not valved and len(counted) == 1) else 1
finally:
    for d in made:
        shutil.rmtree(d, ignore_errors=True)
sys.exit(rc)
"""
    )
    assert ran.rc == 0, ran.why(
        "a product's valve did not suppress its own rule end to end, or was suppressed without"
        " being counted"
    )


def test_the_standing_section_counts_every_declared_marker(world: World) -> None:
    """Every declared marker has a standing line summing to the total."""
    ran = world.forge(
        r"""
import pathlib
import re
import shutil
import sys
sys.argv = ["gate"]
from quality import gate

def section():
    standing = [row for row in gate.standing_valves() if len(row[3]) >= gate.MIN_REASON]
    lines = gate.standing_section_lines(standing, terse=True)
    total = int(re.fullmatch(r"valves \(standing\): (\d+)", lines[0]).group(1))
    per = {}
    for line in lines[1:]:
        token, n = re.fullmatch(r"valves \(standing\): (\S+) (\d+)", line).groups()
        per[token] = int(n)
    return total, per

named = gate.named_valve_tokens()
total, per = section()
print("before:", total, per)
problems = []
if sum(per.values()) != total:
    problems.append(f"the total {total} is not the sum of its token lines {sum(per.values())}")
missing = sorted(set(named) - set(per))
if missing:
    problems.append(f"declared tokens with no line: {missing}")
for token in ("authz", "reach"):
    if token not in per:
        problems.append(f"no `{token}` line — the token is declared and uncounted")
probe = pathlib.Path(gate.ROOT) / "apps" / "zzz_probe_standing_valves"
if probe.exists():
    raise SystemExit(f"the probe path {probe} is already taken; nothing was planted")
probe.mkdir()
try:
    services = probe / "services.py"
    services.write_text(
        "def probe(*, x: str) -> str:\n"
        "    note = \"# reach: inside a string literal is prose, never a valve\"\n"
        "    return x + note\n"
    )
    _t, inert = section()
    services.write_text(
        "# reach: the drive plants exactly one standing valve here\n"
        "def probe(*, x: str) -> str:\n"
        "    return x\n"
    )
    total2, per2 = section()
finally:
    shutil.rmtree(probe)
print("string:", inert.get("reach"), "comment:", per2.get("reach"), total2)
if inert.get("reach") != per.get("reach"):
    problems.append("a marker inside a string literal moved the reach line")
if per2.get("reach") != per.get("reach", 0) + 1 or total2 != total + 1:
    problems.append("a planted reach comment did not move the reach line and the total by one")
for rule in gate.RULES:
    marker = str((rule.get("valve") or {}).get("marker") or "")
    if marker and not any("(counted and printed)" in l for l in gate.valve_lines(rule)):
        problems.append(
            "rule " + str(rule.get("id")) + ": the trailer does not say its valve is counted"
        )
slash = gate.valve_lines(gate.RULES_BY_ID["56"], {"//"})
if not any("// rule-56:" in l for l in slash):
    problems.append(f"rule 56 does not render the file token: {slash}")
print("\n".join(problems) or "all held")
sys.exit(1 if problems else 0)
"""
    )
    assert ran.rc == 0, ran.why(
        "the standing section did not count every declared marker as one reader reads it"
    )


def test_a_dated_past_valve_is_backlog_and_a_reasoned_one_is_declared(world: World) -> None:
    """A planted reach valve past its date moves dated-past and backlog by one."""
    ran = world.forge(
        r"""
import pathlib
import shutil
import sys
sys.argv = ["gate"]
from quality import gate

def census():
    standing = [row for row in gate.standing_valves() if len(row[3]) >= gate.MIN_REASON]
    return gate.backlog_census(standing, held={})

probe = pathlib.Path(gate.ROOT) / "apps" / "zzz_probe_backlog_census"
if probe.exists():
    raise SystemExit(f"the probe path {probe} is already taken; nothing was planted")
before = census()
probe.mkdir()
try:
    services = probe / "services.py"
    services.write_text(
        "# reach: the drive plants a valve whose trigger has passed — until 2001-01-01\n"
        "def probe(*, x: str) -> str:\n"
        "    return x\n"
    )
    dated = census()
    services.write_text(
        "# reach: the drive plants a valve whose trigger is an event — until the vendor ships v2\n"
        "def probe(*, x: str) -> str:\n"
        "    return x\n"
    )
    reasoned = census()
finally:
    shutil.rmtree(probe)
print("before:", before)
print("dated:", dated)
print("reasoned:", reasoned)
ok = (
    dated.dated == before.dated + 1
    and dated.backlog == before.backlog + 1
    and dated.declared == before.declared
    and reasoned.declared == before.declared + 1
    and reasoned.backlog == before.backlog
)
sys.exit(0 if ok else 1)
"""
    )
    assert ran.rc == 0, ran.why("the census did not read the trigger tail through the reach token")


def test_terse_prints_enforcement_broken_in_full(world: World) -> None:
    """Exit 2 outranks a flag whose job is to print less."""
    ran = world.forge(
        r"""
import io, contextlib, sys
sys.argv = ["gate"]
from quality import gate
gate.RULES[0].pop("valve", None)
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc = gate.main(["--terse"])
text = buf.getvalue()
print(text)
sys.exit(0 if rc == 2 and "ENFORCEMENT BROKEN" in text and "no valve" in text else 1)
"""
    )
    assert ran.rc == 0, ran.why("--terse suppressed, or softened, the ENFORCEMENT BROKEN block")


def test_a_memoised_rule_is_not_rescanned(memo_world: World) -> None:
    """Three consults on one tree ran the check once, and the run says how many it memoized."""
    ran = memo_world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_memo"] = stub
rule = {"id": "zzz-drive-memo", "enabled": True, "check": "zzz_drive_memo",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
gate.memo_reset()
gate.memo_consult(rule, "zzz_drive_memo")
gate.memo_consult(rule, "zzz_drive_memo")
gate.memo_consult(rule, "zzz_drive_memo")
gate.memo_report()
print("check ran %d time(s) for %d hit(s)" % (calls["n"], gate.memo_counts["hits"]))
sys.exit(0 if calls["n"] == 1 and gate.memo_counts["hits"] == 2 else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a rule whose every input was byte-identical was rescanned, or the run did not print "
        "its scanned/memoized count"
    )


def test_a_moved_input_misses_one_rule_and_names_it(memo_world: World) -> None:
    """A moved statement re-keys one rule, a moved doc anchor re-keys its rule."""
    ran = memo_world.forge(
        r"""
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate
memo = sys.modules[gate.memo_key.__module__]

real = [r for r in gate.RULES
        if r.get("enabled", True) and r.get("check") and gate.memo_declines(r) is None]
base = {str(r["id"]): gate.memo_key(r)[0] for r in real}

# (i) one byte of the rule STATEMENT -> that rule alone re-keys.
victim = real[0]
vid = str(victim["id"])
moved = dict(victim)
moved["statement"] = str(victim.get("statement", "")) + " "
after = {str(r["id"]): gate.memo_key(moved if str(r["id"]) == vid else r)[0] for r in real}
by_text = sorted(k for k in base if base[k] != after.get(k))

# (ii) one byte of the DOC ANCHOR the rule declares.
doc_moved = dict(victim)
doc_moved["doc"] = dict(victim.get("doc") or {})
doc_moved["doc"]["contains"] = str(doc_moved["doc"].get("contains", "")) + "x"
by_doc = gate.memo_key(doc_moved)[0] != base[vid]

# (iii) one byte inside the WALK the rule reads -> every rule of that kind.
target = pathlib.Path("apps/example/selectors.py")
saved = target.read_bytes()
try:
    target.write_bytes(saved + b"\n# one byte the walk must see\n")
    memo._MEASURED = None
    by_walk = {str(r["id"]): gate.memo_key(r)[0] for r in real}
finally:
    target.write_bytes(saved)
    memo._MEASURED = None
walked = sorted(k for k in base if base[k] != by_walk.get(k))

# and the MISS LINE names the component.
from quality.checks import REGISTRY, CheckResult
REGISTRY["zzz_drive_memo"] = lambda root, rule: CheckResult()
probe = {"id": "zzz-drive-miss", "enabled": True, "check": "zzz_drive_memo",
         "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
gate.memo_reset()
gate.memo_consult(probe, "zzz_drive_memo")
second = dict(probe)
second["statement"] = "a byte the first key never saw"
gate.memo_consult(second, "zzz_drive_memo")
named = [ln for ln in gate.memo_lines if "miss(rule)" in ln]
print("statement moved: %s" % by_text)
print("doc anchor moved the key: %s" % by_doc)
print("a walk byte re-keyed %d of %d rules of that kind" % (len(walked), len(real)))
print("the miss line: %s" % (named or gate.memo_lines))
sys.exit(0 if by_text == [vid] and by_doc and walked and named else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "an input moved without the key moving, or a miss could not say what moved"
    )


def test_a_hit_replays_the_red(memo_world: World) -> None:
    """A hit replays the finding and its targets, byte for byte."""
    ran = memo_world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

def red(root, rule):
    out = CheckResult()
    out.hit("apps/example/selectors.py", 7, "the drive plant: a violation that must survive a hit")
    out.count("modules", 3)
    return out
REGISTRY["zzz_drive_red"] = red
rule = {"id": "zzz-drive-red", "enabled": True, "check": "zzz_drive_red",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
gate.memo_reset()
cold = gate.memo_consult(rule, "zzz_drive_red")
warm = gate.memo_consult(rule, "zzz_drive_red")
same = [str(f) for f in cold.findings] == [str(f) for f in warm.findings]
print("cold: %s" % [str(f) for f in cold.findings])
print("warm: %s" % [str(f) for f in warm.findings])
hits = gate.memo_counts["hits"]
print("targets cold=%s warm=%s hits=%d" % (cold.targets_matched, warm.targets_matched, hits))
sys.exit(0 if same and warm.findings and warm.targets_matched == cold.targets_matched
         and gate.memo_counts["hits"] == 1 else 1)
"""
    )
    assert ran.rc == 0, ran.why("a hit printed ok over a banked violation, or lost its targets")


def test_the_selftest_bypasses_the_memo_and_its_canaries_still_fire(memo_world: World) -> None:
    """A planted false memo entry silences the finding with the memo live and does NOT under the."""
    ran = memo_world.forge(
        r"""
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

# THE PLANT IS A FALSE MEMO ENTRY: it says this rule found nothing, under the
# very key the consult will compute. With the memo live it MUST win — that is
# what makes it a real plant rather than an inert file — and under the
# self-test bypass the check MUST run anyway and its finding MUST come back.
def red(root, rule):
    out = CheckResult()
    out.hit("apps/example/selectors.py", 1, "the canary the false entry must not silence")
    return out
REGISTRY["zzz_drive_canary"] = red
rule = {"id": "zzz-drive-canary", "enabled": True, "check": "zzz_drive_canary",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
home = pathlib.Path(gate.memo_home()[0])
key, components, why = gate.memo_key(rule)
gate.memo_write(home, str(rule["id"]), str(key), components, CheckResult())
warmed = sorted(p.name for p in (home / str(rule["id"])).glob("*.json"))

gate.memo_reset()
gate.memo_state["bypass"] = False
silenced = gate.memo_consult(rule, "zzz_drive_canary")
gate.memo_state["bypass"] = True
fired = gate.memo_consult(rule, "zzz_drive_canary")
after = sorted(p.name for p in (home / str(rule["id"])).glob("*.json"))
print("the false entry, with the memo live: %d finding(s)" % len(silenced.findings))
print("the same entry, under the bypass:    %d finding(s)" % len(fired.findings))
print("memo files before=%s after=%s" % (warmed, after))
sys.exit(0 if not silenced.findings and len(fired.findings) == 1 and warmed == after else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "the self-test bypass is a printed word: either the plant was inert, or the bypass "
        "read or wrote the memo"
    )


def test_memo_no_scans_always_and_needs_a_reason(memo_world: World) -> None:
    """A declining rule scans on every run and is never a hit, and a declaration with no reason."""
    ran = memo_world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
from quality.checks import REGISTRY, CheckResult

calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_declines"] = stub
declining = {"id": "zzz-drive-declines", "enabled": True, "check": "zzz_drive_declines",
             "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {},
             "memo": {"no": "the drive s own scratch rule, declining on purpose"}}
gate.memo_reset()
gate.memo_consult(declining, "zzz_drive_declines")
gate.memo_consult(declining, "zzz_drive_declines")
scanned_always = calls["n"] == 2 and gate.memo_counts["hits"] == 0

refusals = []
for shape in ({"no": ""}, {"no": "too short"}, "no", {False: "a bare yaml no key"}):
    victim = dict(declining)
    victim["memo"] = shape
    gate.broken.clear()
    gate.memo_consistency([victim])
    refusals.append(list(gate.broken))
gate.broken.clear()

# and rule 31 on the real tree declares it, with a reason a reader can weigh.
real = gate.RULES_BY_ID.get("31") or {}
declared = gate.memo_declines(real)

print("the declining rule scanned twice: %s (hits %d)" % (scanned_always, gate.memo_counts["hits"]))
for shape, said in zip(("empty", "short", "scalar", "bare-yaml-no"), refusals):
    print("  %-13s -> %s" % (shape, (said[0][:110] if said else "NOTHING REFUSED")))
print("rule 31 declines with: %s" % ((declared or "")[:80] or "NOTHING"))
sys.exit(0 if scanned_always and all(refusals) and declared else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a memo: no was honoured without a reason, or a declining rule was memoised anyway"
    )


def test_an_undecidable_key_scans(memo_world: World) -> None:
    """A key that cannot be derived scans every time, prints why, and is never a hit."""
    ran = memo_world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
memo = sys.modules[gate.memo_key.__module__]
from quality.checks import REGISTRY, CheckResult

calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_blind"] = stub

# (i) a scope this tree cannot expand. The victim is built here and the doc
#     carries no path literal — a made-up docs path would be a dangling pointer
#     the documentation census reads.
blind = {"id": "zzz-drive-blind", "enabled": True, "check": "zzz_drive_blind",
         "doc": {"file": "quality/rules.yaml", "contains": "rules"},
         "scope": {"allow_import": [{"path": "apps/nowhere/*.py"}]}}
gate.memo_reset()
gate.memo_consult(blind, "zzz_drive_blind")
gate.memo_consult(blind, "zzz_drive_blind")
by_scope = (calls["n"] == 2 and gate.memo_counts["undecidable"] == 2
            and gate.memo_counts["hits"] == 0
            and len([ln for ln in gate.memo_lines if "memo undecidable" in ln]) == 2)
said = list(gate.memo_lines)

# (ii) git itself refusing. The measured tree is what every component is read
#      from, so a git that will not answer is could-not-look for every rule.
saved = memo._MEASURED
ok_key = {"id": "zzz-drive-blind2", "enabled": True, "check": "zzz_drive_blind",
          "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
try:
    memo._MEASURED = ({}, "`git ls-tree` exited 128 — not a git repository")
    gate.memo_reset()
    before = calls["n"]
    gate.memo_consult(ok_key, "zzz_drive_blind")
    by_git = (calls["n"] - before == 1 and gate.memo_counts["undecidable"] == 1
              and gate.memo_counts["hits"] == 0)
    said += gate.memo_lines
finally:
    memo._MEASURED = saved

for line in said:
    print("  %s" % line)
print("by_scope=%s by_git=%s" % (by_scope, by_git))
sys.exit(0 if by_scope and by_git else 1)
"""
    )
    assert ran.rc == 0, ran.why("an undecidable key read the cache, or scanned without saying so")


def test_the_readers_ignore_the_memo(memo_world: World) -> None:
    """--explain, --rules."""
    ran = memo_world.forge(
        r"""
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate

# The four readers return before anything measures, so a warm memo must not
# change one byte of what they print — and must not grow by one file either.
cold = {name: gate._captured(argv) for name, argv in (
    ("explain", ["--explain", "13"]),
    ("rules", ["--rules"]),
    ("inputs", ["--selftest-inputs"]),
    ("fold-map", ["--fold-map", "quality/rules.yaml"]),
)}
home = pathlib.Path(gate.memo_home()[0])
from quality.checks import CheckResult
for rule in gate.RULES:
    if not (rule.get("enabled", True) and rule.get("check")):
        continue
    if gate.memo_declines(rule) is not None:
        continue
    key, components, why = gate.memo_key(rule)
    if key:
        gate.memo_write(home, str(rule["id"]), key, components, CheckResult())
warm = {name: gate._captured(argv) for name, argv in (
    ("explain", ["--explain", "13"]),
    ("rules", ["--rules"]),
    ("inputs", ["--selftest-inputs"]),
    ("fold-map", ["--fold-map", "quality/rules.yaml"]),
)}
banked = len(list(home.rglob("*.json")))
for name in cold:
    print("%-8s identical=%s rc=%d" % (name, cold[name] == warm[name], warm[name][0]))
print("entries banked before the warm read: %d" % banked)
sys.exit(0 if cold == warm and all(rc == 0 for rc, _ in warm.values()) and banked else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a reader's output moved when the memo was warmed, or a reader stopped answering"
    )


def test_a_schema_move_misses_every_entry_once_and_says_so(memo_world: World) -> None:
    """An entry the old writer banked is never read."""
    ran = memo_world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
memo = sys.modules[gate.memo_key.__module__]
from quality.checks import REGISTRY, CheckResult

# AN ENTRY THE OLD WRITER BANKED, under the very components this tree derives:
# only the schema word differs, so a consult that read it would be serving an
# answer from a writer that could bank a tree that moved.
calls = {"n": 0}
def stub(root, rule):
    calls["n"] += 1
    return CheckResult()
REGISTRY["zzz_drive_schema"] = stub
rule = {"id": "zzz-drive-schema", "enabled": True, "check": "zzz_drive_schema",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"}, "scope": {}}
current = memo.MEMO_SCHEMA
memo.MEMO_SCHEMA = "rule-v1"
old_key, components, why = gate.memo_key(rule)
memo.MEMO_SCHEMA = current
home = gate.memo_home()[0]
gate.memo_write(home, str(rule["id"]), str(old_key), components, CheckResult())

gate.memo_reset()
gate.memo_consult(rule, "zzz_drive_schema")
first = list(gate.memo_lines)
first_hits = gate.memo_counts["hits"]
scanned = calls["n"]
gate.memo_reset()
gate.memo_consult(rule, "zzz_drive_schema")
second_hits = gate.memo_counts["hits"]
gate.memo_report()
print("schema now: %s" % current)
print("the first consult said: %s" % first)
print("the second consult scanned again: %s; hit: %s" % (calls["n"] != scanned, bool(second_hits)))
sys.exit(0 if current != "rule-v1" and not first_hits and scanned
         and any(ln.endswith("miss(key)") for ln in first)
         and second_hits and calls["n"] == scanned else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "an entry written under the old memo schema was served, or its miss did not say the "
        "key moved"
    )


def test_a_product_rule_under_its_namespace_loads_and_fires(world: World) -> None:
    """Acme-1 loaded under rule_id_namespace."""
    ran = world.forge(
        r"""
import copy
import shutil
import sys
sys.argv = ["gate"]
from quality import gate

# THE FORGED ID IS ONE THIS TREE DOES NOT OWN. A product whose
# namespace is `acme` numbers its first drawer rule acme-1, and a typed id
# then collided with that rule and with its fixture directory.
RID = next(
    f"acme-{n}"
    for n in range(1, 1000)
    if f"acme-{n}" not in gate.RULES_BY_ID
    and not any(
        (d / f"acme-{n}").exists()
        for d in (
            gate.CANARY_DIR, gate.NEGATIVE_DIR, gate.LOCAL_CANARY_DIR, gate.LOCAL_NEGATIVE_DIR
        )
    )
)
rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = RID
# THE HOME IS ASKED FOR, NEVER SPELLED. `fixture_home` is the ONE resolver
# — a rule loaded from the product drawer lives under the drawer, a rule in
# the template document under the template tree — and a drive that typed
# either would be one more place teaching a product where its fixtures go.
# This forged rule is appended to the list the TEMPLATE document declares,
# rather than loaded from the drawer, so the resolver answers the template
# tree for it;
# a real product rule comes out of the drawer, and the case that plants one
# there is case_a_drawer_rule_is_a_rule_end_to_end.
made = []
for kind in ("canary", "negative"):
    dst = gate.fixture_home(kind, RID)
    shutil.copytree(gate.fixture_home(kind, "1"), dst)
    made.append(dst)
gate.world_module().RULE_ID_NAMESPACE = "acme"
gate.world_module().TEMPLATE_IDS_THROUGH = max(
    int(r["id"]) for r in gate.RULES if gate.is_template_id(str(r["id"]))
)
gate.RULES.append(rule)
gate.RULES_BY_ID[RID] = rule
rc = 1
try:
    gate.broken.clear()
    gate.consistency()
    named = [b for b in gate.broken if RID in b]
    entry = rule["canaries"][0]
    plant = gate.Plant()
    try:
        plant.put(
            gate.fixture_home("canary", RID) / entry["fixture"],
            entry["plant_at"],
            entry["mode"],
        )
        findings, _floors, why = gate.run_rule(rule, floors=False)
    finally:
        plant.restore()
    print("consistency named acme-1:", named)
    print("could-not-look:", repr(why))
    print("findings:", [str(f) for f in findings])
    rc = 0 if (not named and findings and not why) else 1
finally:
    for d in made:
        shutil.rmtree(d, ignore_errors=True)
sys.exit(rc)
"""
    )
    assert ran.rc == 0, ran.why(
        "a product rule under a declared namespace did not load, or its canary did not fire "
        "through the real scope"
    )


def test_a_product_rule_with_an_integer_id_is_refused(world: World) -> None:
    """A bare integer above the folded template release is refused, naming acme-<n>."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
gate.world_module().RULE_ID_NAMESPACE = "acme"
gate.world_module().TEMPLATE_IDS_THROUGH = 59
problem = gate.id_shape_problem("60")
print(problem)
sys.exit(0 if problem and "acme-<n>" in problem and "60" in problem else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a product that typed an integer id was accepted, or the refusal did not name the grammar"
    )


def test_a_namespaced_id_on_a_template_tree_is_refused(world: World) -> None:
    """Acme-1 is refused on a tree that declares no namespace."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
if gate.RULE_ID_NAMESPACE is not None:
    print("this tree declares a namespace; the template case cannot be driven here")
    sys.exit(1)
problem = gate.id_shape_problem("acme-1")
valve = gate.override_re("#").search("# rule-acme-1: a namespace nobody claimed")
print(problem)
print("valve matched:", bool(valve))
sys.exit(0 if problem and "rule_id_namespace" in problem and not valve else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a namespaced id, or a valve naming a namespace nobody claimed, was accepted on the "
        "template"
    )


def test_a_fixture_dir_under_an_unclaimed_namespace_is_exit_2(world: World) -> None:
    """A fixture directory under a namespace the tree never claimed is named."""
    ran = world.forge(
        r"""
import pathlib
import shutil
import sys
import tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-nsdir-case-"))
try:
    (scratch / "canary" / "1").mkdir(parents=True)
    (scratch / "canary" / "other-9").mkdir()
    bases = (("canary", scratch / "canary"),)
    loud = gate.fixture_dir_findings(bases, claimed={"1"}, namespace="acme")
    quiet = gate.fixture_dir_findings(bases, claimed={"1", "other-9"}, namespace="acme")
    print("loud:", loud)
    print("quiet:", quiet)
    named = [line for line in loud if "other-9" in line and "other" in line]
    sys.exit(0 if named and not quiet else 1)
finally:
    shutil.rmtree(scratch, ignore_errors=True)
"""
    )
    assert ran.rc == 0, ran.why(
        "an unclaimed namespaced fixture directory was not named, or a claimed one was "
        "reported anyway"
    )


def test_a_tree_with_no_product_rules_is_unchanged(world: World) -> None:
    """The template tree declares neither key."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate
from quality import worlds as W

template, product = W.split_residence_census(W.residence_census(gate.RULES, gate.OPTIONAL_APPS))
shapes = [gate.id_shape_problem(str(r["id"])) for r in gate.RULES]
dirs = gate.fixture_dir_findings()
findings = gate.residence_findings(gate.RULES)
print("namespace:", gate.RULE_ID_NAMESPACE, "through:", gate.TEMPLATE_IDS_THROUGH)
backlog = gate.RESIDENCE_BACKLOG
print("residence template/product:", len(template), len(product), "backlog:", backlog)
print("id shapes refused:", [s for s in shapes if s])
print("fixture dir findings:", dirs)
print("residence findings:", findings)
ok = (
    gate.RULE_ID_NAMESPACE is None
    and gate.TEMPLATE_IDS_THROUGH is None
    and not product
    and len(template) == gate.RESIDENCE_BACKLOG
    and not [s for s in shapes if s]
    and not dirs
    and not findings
)
sys.exit(0 if ok else 1)
"""
    )
    assert ran.rc == 0, ran.why("the wall moved a number on a tree with no product rules at all")


def test_a_drawer_ratchet_adds_to_a_template_class_and_never_replaces_it(world: World) -> None:
    """A drawer class naming one a TEMPLATE rule DECLARES is accepted and ADDED to the."""
    ran = world.forge(
        r"""
import pathlib
import sys
sys.argv = ["gate"]
from quality import gate

# THE DEFECT THIS CASE EXISTS FOR, IN TWO ACTS. A drawer that named a class
# the TEMPLATE already records used to MERGE — `nonconforming: 0` became
# `nonconforming: 99` — and the only thing printed was a note: the template'"'"'s
# own recorded number was ERASED from a file the template never reads. D1
# closed it by refusing the class outright, and that refusal turned out to be
# too wide: rules 50-53 ratchet per FINDING class, so a product with a real
# backlog in `literal` was told its class was not a directory under `apps/`
# and had nowhere to record it at all (HOTFIX-DRAWER-1, from the first
# consumer'"'"'s fold).
#
# SO THE LAW IS ADDITION. A drawer class that a template rule DECLARES is
# accepted and its count is ADDED to the template'"'"'s; the template'"'"'s own number
# survives, which is the half that was ever actually at stake. A class that is
# neither an app on this tree nor one the rule declares is still refused, and
# still does not move the ceiling.
target = next(str(r["id"]) for r in gate.RULES if (r.get("ratchets") or {}))
rule = gate.RULES_BY_ID[target]
before = dict(rule.get("ratchets") or {})
already = sorted(before)[0]
product_app = "zzz_probe_drawer_app"

def merge(classes):
    gate.LOCAL_DOC["ratchets"] = {target: classes}
    rule["ratchets"] = dict(before)
    out = gate._merge_local_ratchets()
    after = dict(rule.get("ratchets") or {})
    gate.LOCAL_DOC.pop("ratchets", None)
    rule["ratchets"] = dict(before)
    return out, after

declared, after_declared = merge({already: 99})
no_app, after_no_app = merge({"acme_nowhere.read": 3})

made = pathlib.Path(gate.ROOT) / "apps" / product_app
made.mkdir(parents=True, exist_ok=False)
try:
    allowed, after_allowed = merge({f"{product_app}.read": 3})
finally:
    made.rmdir()

print("a class the rule declares:", declared)
print("  ceiling after:", after_declared.get(already), "was", before.get(already))
print("no such app:", no_app)
print("a real product app:", allowed, "->", after_allowed.get(f"{product_app}.read"))
sys.exit(0 if (
    not declared
    and after_declared.get(already) == int(before.get(already, 0)) + 99
    and len(no_app) == 1
    and "acme_nowhere" in no_app[0]
    and "TEMPLATE rule" in no_app[0]
    and already in no_app[0]
    and after_no_app == before
    and not allowed
    and after_allowed.get(f"{product_app}.read") == 3
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "the drawer replaced a template rule's recorded number, or refused a class that rule "
        "declares, or accepted one that is neither"
    )


def test_a_drawer_rule_with_no_namespace_is_enforcement_broken(world: World) -> None:
    """A drawer that carries rules and no rule_id_namespace is refused BY KEY and merges nothing."""
    ran = world.forge(
        r"""
import pathlib
import sys
import tempfile
sys.argv = ["gate"]
from quality import gate

# WHY. `id_shape_problem` accepts a plain integer when the tree declares no
# namespace, because on a template that IS the only legal shape. A drawer
# carrying rules and no `rule_id_namespace:` therefore loaded `60` as a rule of
# its own — an integer minted from the drawer, colliding with the next template
# release, with every refusal ADR gate-5 exists for switched off.
scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-ns-"))
gate.world_module().LOCAL_DIR = scratch
gate.world_module().LOCAL_RULES_PATH = scratch / "rules.yaml"

def read(text):
    gate.world_module().LOCAL_RULES_PATH.write_text(text)
    doc, rules, problems = gate._read_local()
    return rules, problems

body = "rules:\n  - id: \"60\"\n    name: minted-from-the-drawer\n"
nameless, refused = read(body)
named, fine = read("rule_id_namespace: acme\ntemplate_rule_ids_through: 59\n" + body)
empty, quiet = read("rules: []\n")
print("nameless rules loaded:", nameless)
print("refusal:", refused)
print("with a namespace:", len(named), fine)
print("an empty rules list:", empty, quiet)
sys.exit(0 if (
    not nameless
    and len(refused) == 1
    and "rule_id_namespace" in refused[0]
    and "quality/local/rules.yaml" in refused[0]
    and len(named) == 1
    and not fine
    and not empty
    and not quiet
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "the drawer minted a rule under the template's own grammar, or refused a drawer that "
        "declared its namespace"
    )


def test_the_drawers_keys_are_closed_and_the_refusal_names_the_key(world: World) -> None:
    """The drawer takes four keys and no more."""
    ran = world.forge(
        r"""
import pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-keys-"))
gate.world_module().LOCAL_DIR = scratch
gate.world_module().LOCAL_RULES_PATH = scratch / "rules.yaml"

def read(text):
    gate.world_module().LOCAL_RULES_PATH.write_text(text)
    return gate._read_local()[2]

legal = read("rule_id_namespace: acme\ntemplate_rule_ids_through: 59\nrules: []\nratchets: {}\n")
strange = read("rule_id_namespace: acme\ntemplate_rule_ids_through: 59\nscope_kinds:\n  js: {}\n")
broken_yaml = read("rules: [ {id: half\n")
not_a_map = read("- one\n- two\n")
gate.world_module().LOCAL_RULES_PATH.unlink()
absent = gate._read_local()[2]
print("legal:", legal)
print("strange:", strange)
print("broken_yaml:", broken_yaml)
print("not_a_map:", not_a_map)
print("absent:", absent)
sys.exit(0 if (
    not legal
    and any("scope_kinds" in p and "quality/local/rules.yaml" in p for p in strange)
    and any("could not be read as YAML" in p for p in broken_yaml)
    and any("not a mapping" in p for p in not_a_map)
    and not absent
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "the drawer accepted a key that is not its own, or refused a legal one, or read a "
        "malformed file as an empty drawer"
    )


def test_the_namespace_keys_are_refused_in_the_template_file(world: World) -> None:
    """Either namespace key left in the template-owned quality/rules.yaml is refused with the."""
    ran = world.forge(
        r"""
import pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-home-"))
gate.world_module().LOCAL_DIR = scratch
gate.world_module().LOCAL_RULES_PATH = scratch / "rules.yaml"

clean = gate._read_local()[2]
gate._DOC["rule_id_namespace"] = "acme"
gate._DOC["template_rule_ids_through"] = 59
moved = gate._read_local()[2]
del gate._DOC["rule_id_namespace"]
del gate._DOC["template_rule_ids_through"]
print("clean:", clean)
for line in moved:
    print("moved:", line)
names_home = [p for p in moved if "quality/local/rules.yaml" in p and "quality/rules.yaml" in p]
sys.exit(0 if (not clean and len(moved) == 2 and len(names_home) == 2) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a namespace key in the template-owned file was accepted, or its refusal did not name "
        "the move"
    )


def test_a_drawer_check_is_a_registry_name_or_a_drawer_runner(world: World) -> None:
    """One resolver."""
    ran = world.forge(
        r"""
import pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-check-"))
gate.world_module().LOCAL_DIR = scratch
gate.world_module().LOCAL_RUNNER_DIR = scratch / "runners"
gate.world_module().LOCAL_RUNNER_DIR.mkdir(parents=True)

registry_name = sorted(gate.REGISTRY)[0]
rescoped = gate.resolve_check_problem("acme-1", registry_name)
missing = gate.resolve_check_problem("acme-1", "acme_no_widget")
(gate.world_module().LOCAL_RUNNER_DIR / "acme_no_widget.py").write_text("print()\n")
runner = gate.resolve_check_problem("acme-1", "acme_no_widget")
print("re-scoped registry name:", rescoped)
print("neither:", missing)
print("drawer runner:", runner)
sys.exit(0 if (
    rescoped is None
    and runner is None
    and missing
    and "REGISTRY" in missing
    and "quality/local/runners/acme_no_widget.py" in missing
    and "quality/checks/" in missing
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a check: that resolves to nothing was accepted, or a legal one refused, or the "
        "refusal did not name both homes"
    )


def test_a_mute_drawer_runner_is_enforcement_broken(world: World) -> None:
    """A drawer runner that prints nothing is could-not-look."""
    ran = world.forge(
        r"""
import copy, pathlib, sys, tempfile
sys.argv = ["gate"]
from quality import gate

scratch = pathlib.Path(tempfile.mkdtemp(prefix="djb-drawer-mute-"))
gate.world_module().LOCAL_DIR = scratch
gate.world_module().LOCAL_RUNNER_DIR = scratch / "runners"
gate.world_module().LOCAL_RUNNER_DIR.mkdir(parents=True)
mute = gate.world_module().LOCAL_RUNNER_DIR / "acme_mute.py"
mute.write_text("import sys\nsys.exit(0)\n")

rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = "acme-9"
rule["check"] = "acme_mute"
rule.pop("memo", None)
gate.memo_state["bypass"] = True
gate.broken.clear()
findings, _targets, why = gate.run_rule(rule, floors=False)
print("findings:", findings)
print("why:", why)
for line in gate.broken:
    print("broken:", line)
sys.exit(0 if (
    not findings
    and why.startswith(gate.COULD_NOT_LOOK)
    and any("LOCAL RUNNER REFUSED" in b for b in gate.broken)
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a mute drawer runner read as zero findings, which is the cheapest way in the world to"
        " ship a rule that never fires"
    )


def test_a_drawer_ratchet_may_not_name_a_platform_app(world: World) -> None:
    """A drawer ratchet naming a partition.yaml platform app is refused."""
    ran = world.forge(
        r"""
import sys
sys.argv = ["gate"]
from quality import gate

platform = gate.PLATFORM_APPS
if platform is None:
    print(gate._PARTITION_PROBLEM)
    sys.exit(1)
platform = sorted(platform)
product = "acme_billing"
victim = platform[0] if platform[0] != "example" else platform[1]
target = next(str(r["id"]) for r in gate.RULES)

def judge(classes):
    gate.LOCAL_DOC["ratchets"] = {target: classes}
    gate.broken.clear()
    gate.notes.clear()
    gate.local_ratchet_consistency()
    out = list(gate.broken)
    gate.LOCAL_DOC.pop("ratchets", None)
    return out

bare = judge({victim: 3})
dotted = judge({f"{victim}.role-value": 3})
allowed = judge({product: 3})
print("bare platform app:", bare)
print("dotted platform class:", dotted)
print("a product app:", allowed)
sys.exit(0 if (
    len(bare) == 1 and victim in bare[0] and "platform_apps" in bare[0]
    and len(dotted) == 1 and victim in dotted[0]
    and not allowed
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "the drawer raised a platform rule's ceiling from a file the template never reads, or "
        "refused a product app that belongs there"
    )


def test_a_drawer_canary_may_not_plant_into_a_platform_app(world: World) -> None:
    """A drawer canary planting into a template-owned app is refused BY APP NAME."""
    ran = world.forge(
        r"""
import copy, sys
sys.argv = ["gate"]
from quality import gate

platform = gate.PLATFORM_APPS
if platform is None:
    print(gate._PARTITION_PROBLEM)
    sys.exit(1)
platform = sorted(platform)
victim = platform[0] if platform[0] != "example" else platform[1]

rule = copy.deepcopy(gate.RULES_BY_ID["1"])
rule["id"] = "acme-1"
gate.RULES.append(rule)
gate.world_module().LOCAL_RULE_IDS = frozenset({"acme-1"})

def judge(target):
    rule["canaries"] = [{"fixture": "planted.py", "plant_at": target, "mode": "append"}]
    rule["negatives"] = []
    gate.broken.clear()
    gate.local_plant_consistency()
    return list(gate.broken)

into_platform = judge(f"apps/{victim}/models.py")
into_example = judge("apps/example/models.py")
into_product = judge("apps/acme_billing/models.py")
gate.RULES.pop()
print("platform app:", into_platform)
print("apps/example:", into_example)
print("a product app:", into_product)
sys.exit(0 if (
    len(into_platform) == 1
    and victim in into_platform[0]
    and "plant portability" in into_platform[0]
    and not into_example
    and not into_product
) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a drawer rule planted a fixture into an app the next fold overwrites, or the refusal "
        "named no app"
    )


def test_the_drawers_key_moves_only_when_the_drawer_does(world: World) -> None:
    """The drawer's NON-rule keys fold into the engine digest (every rule re-keys)."""
    ran = world.forge(
        r"""
import copy, sys
sys.argv = ["gate"]
from quality import gate
memo = sys.modules[gate.memo_key.__module__]

blobs, trouble = gate.measured_blobs()
if trouble:
    print(trouble)
    sys.exit(1)

def engine():
    memo._ENGINE_DIGEST = None
    return gate._engine_digest(blobs)

base = engine()
same = engine()
# THE EDIT IS DERIVED FROM THE DRAWER THIS TREE HAS: a namespace the
# tree does not already declare, restored to exactly what was there — on the
# template an absent key, on a product its own namespace. A typed "acme" was a
# no-op on a product that IS acme and read as "a drawer edit moved nothing".
MISSING = object()
had = gate.LOCAL_DOC.get("rule_id_namespace", MISSING)
gate.LOCAL_DOC["rule_id_namespace"] = "acme" if had != "acme" else "acmeprobe"
moved = engine()
if had is MISSING:
    gate.LOCAL_DOC.pop("rule_id_namespace")
else:
    gate.LOCAL_DOC["rule_id_namespace"] = had
back = engine()

template = copy.deepcopy(gate.RULES_BY_ID["1"])
local = copy.deepcopy(template)
local["id"] = "acme-1"
one = gate.memo_key(template)[0]
local["statement"] = str(local.get("statement", "")) + " (edited)"
two = gate.memo_key(template)[0]
local_a = gate.memo_key(local)[0]
local["statement"] = str(local["statement"]) + " again"
local_b = gate.memo_key(local)[0]
print("engine base == same:", base == same)
print("engine moved by a non-rule drawer key:", base != moved)
print("engine restored:", base == back)
print("a template rule untouched by another rules text:", one == two)
print("a rules own text moves only its own key:", local_a != local_b)
held = base == same and base != moved and base == back
sys.exit(0 if (held and one == two and local_a != local_b) else 1)
"""
    )
    assert ran.rc == 0, ran.why(
        "a drawer edit either re-keyed nothing or re-keyed everything — the first banks a "
        "verdict for a tree nobody measured, the second throws the memo away"
    )


# -- the traced memo keys ----------------------------------------------------

TRACED_MEMO_RULES = ("26", "37", "42", "43", "46")


def test_a_traced_rules_key_names_every_file_its_check_reads(world: World) -> None:
    """Every file each traced check opens moves its key, and a file it never opens does not."""
    failed = []
    for rid in TRACED_MEMO_RULES:
        ran = world.forge(TRACED_SCRIPT.replace("__RID__", rid))
        if ran.rc != 0:
            failed.append(ran.why(f"rule {rid}"))
    assert not failed, "a traced check reads outside its memo key, or declines:\n" + "\n".join(
        failed
    )


# -- the drawer, end to end, in the world -------------------------------------

NAMESPACE_LEG = 'import sys\nsys.argv = ["gate"]\nfrom quality import gate\ngate.namespace_leg()\n'


def template_through(world: World) -> str:
    """The template's high-water rule id, read off `namespace_leg()`'s own line."""
    import re

    ran = world.forge(NAMESPACE_LEG)
    found = re.findall(r"integers minted through ([0-9]+)", ran.out)
    if not found:
        raise CouldNotLook(ran.why("the template's high-water rule id could not be read"))
    return str(found[-1])


@contextmanager
def drawer(world: World, yaml_text: str, files: Mapping[str, str] = {}) -> Iterator[Path]:
    """A `quality/local/` drawer in the world declaring `acme` through this tree's release."""
    local = world.root / "quality" / "local"
    if local.exists():
        raise CouldNotLook(f"the world already has a drawer at {local}")
    head = f"rule_id_namespace: acme\ntemplate_rule_ids_through: {template_through(world)}\n"
    try:
        for rel, text in files.items():
            (world.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (world.root / rel).write_text(text)
        local.mkdir(exist_ok=True)
        (local / "rules.yaml").write_text(head + yaml_text)
        yield local
    finally:
        shutil.rmtree(local, ignore_errors=True)


def budget_breach(key: str) -> str:
    """A script that records `key`'s ceiling one below its measure and exits on the refusals."""
    return (
        "import sys\n"
        "from quality import worlds as W\n"
        "from quality.engine._hub import ROOT\n"
        "from quality.engine.run import check_budgets, measure_budgets\n"
        f"key = {key!r}\n"
        "recorded = W.read_budgets(ROOT)\n"
        "section = 'out_schema_fields'\n"
        "recorded[section][key] = measure_budgets()[section][key] - 1\n"
        "problems = check_budgets(recorded)\n"
        'print("\\n".join(problems))\n'
        "sys.exit(1 if problems else 0)\n"
    )


def test_an_example_apps_budget_advises_on_the_template_and_on_a_product(world: World) -> None:
    """WidgetOut past its ceiling prints the advisory and exits 0, on the template and a product."""
    script = budget_breach("apps/example/schemas.py::WidgetOut")
    template = world.forge(script)
    with drawer(world, "rules: []\nratchets: {}\n"):
        product = world.forge(script)
    for ran in (template, product):
        assert ran.rc == 0, ran.why("a tree refused on the worked example's ceiling")
        assert "budget advisory: out_schema_fields" in ran.out, ran.why("the advisory is gone")
        assert "the worked example's ceilings advise, never refuse" in ran.out, ran.why("text")


def test_a_platform_apps_budget_still_refuses_on_the_template(world: World) -> None:
    """UserOut past its ceiling refuses, exit 1, with the line to paste."""
    ran = world.forge(budget_breach("apps/accounts/schemas.py::UserOut"))
    key = "apps/accounts/schemas.py::UserOut"
    assert ran.rc == 1 and "past the recorded ceiling" in ran.out, ran.why("no refusal")
    said = [ln for ln in ran.out.splitlines() if key in ln]
    assert any(ln.startswith("budget: out_schema_fields") for ln in said), ran.why("no refusal")
    assert not any(ln.startswith("budget advisory") for ln in said), ran.why(
        "a platform breach was only advised"
    )


def test_a_drawer_fixture_is_not_linted_and_a_drawer_runner_is(world: World) -> None:
    """`ruff check .` names neither drawer fixture but still lints a drawer runner."""
    neg = "quality/local/negative/zzz_probe/bad.py"
    can = "quality/local/canary/zzz_probe/bad.py"
    run = "quality/local/runners/zzz_probe.py"
    ruff = str(Path(PY).parent / "ruff")
    local = world.root / "quality" / "local"
    try:
        for rel, text in (
            (neg, "import os\nx=[1,2 ,3]\n"),
            (can, "import os\nx=[1,2 ,3]\n"),
            (run, "import os\n"),
        ):
            (world.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (world.root / rel).write_text(text)
        check = world.run([ruff, "check", "--output-format=concise", "."])
        fmt_sink = world.logs / "ruff-format.out"
        fmt = run_to(fmt_sink, [ruff, "format", "--check", "--quiet", "."], world.root, _env(None))
    finally:
        shutil.rmtree(local, ignore_errors=True)
    assert neg not in check.out and can not in check.out, check.why(
        "ruff check . reports a drawer FIXTURE"
    )
    assert any(ln.startswith(f"{run}:") and " F401 " in ln for ln in check.out.splitlines()), (
        check.why(f"the drawer runner {run} no longer reports F401")
    )
    said = fmt_sink.read_text()
    assert fmt.rc == 0 and not said, (
        f"ruff format --check is exit {fmt.rc}, want 0 and silent:\n{said}"
    )


def test_a_drawer_rule_is_a_rule_end_to_end(world: World) -> None:
    """A drawer rule loads, fires both canaries over a bound floor, keeps its negative silent."""
    import re

    files = {
        "quality/local/canary/acme-1/import_user.py": (
            world.root / "quality/canary/1/import_user.py"
        ).read_text(),
        "quality/local/canary/acme-1/fk_label.py": (
            world.root / "quality/canary/1/fk_label.py"
        ).read_text(),
        "quality/local/negative/acme-1/get_user_model.py": (
            world.root / "quality/negative/1/get_user_model.py"
        ).read_text(),
    }
    with drawer(world, E2E_DRAWER, files):
        ran = world.forge(E2E_SCRIPT, {"DJB_RULES_NO_MEMO": "1"})
        listing = world.gate("--rules")
        explained = world.gate("--explain", "acme-1")
    assert ran.rc == 0, ran.why("a product rule in the drawer is not a rule end to end")
    assert re.search(r"^acme-1  acme-no-auth-user-import .*\[local\]$", listing.out, re.M), (
        listing.why("--rules does not tag acme-1 [local]")
    )
    assert "home: quality/local/rules.yaml" in explained.out, explained.why(
        "--explain names no drawer home"
    )


def test_a_products_world_sheds_its_own_drawer_and_keeps_the_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a tree that declares a drawer, the world these cases plant into is cloned without it."""
    product = tmp_path / "product"
    for rel, text in (
        ("quality/gate.py", ""),
        ("quality/local/rules.yaml", "rule_id_namespace: zzzk6a\n"),
    ):
        (product / rel).parent.mkdir(parents=True, exist_ok=True)
        (product / rel).write_text(text)
    for argv in (
        ["init", "-q"],
        ["add", "quality"],
        ["-c", "user.email=p@example.invalid", "-c", "user.name=P", "commit", "-qm", "product"],
    ):
        subprocess.run(["git", "-C", str(product), *argv], check=True, env=_env(None))
    monkeypatch.setattr(sys.modules[__name__], "ROOT", product)
    built = clone_world(tmp_path / "home", "world")
    assert (built.root / "quality/gate.py").is_file()
    assert not (built.root / "quality/local").exists()
    assert built.git("status", "--porcelain") == ""


def test_a_product_django_check_fires_under_its_namespace(world: World) -> None:
    """A product's own system check fires both Django canaries through the real leg under its."""
    app = world.root / "apps" / "acme_orders"
    if app.exists():
        raise CouldNotLook(f"the world already has {app}")
    rules = world.root / "quality" / "rules.yaml"
    saved = rules.read_bytes()
    anchor = "      extra_modules:\n"
    text = saved.decode()
    if text.count(anchor) != 1:
        raise CouldNotLook("rule 11's extra_modules anchor moved")
    files = {
        "apps/acme_orders/__init__.py": "",
        "apps/acme_orders/apps.py": DJANGO_APPS_PY,
        "apps/acme_orders/checks.py": DJANGO_CHECKS_PY,
        "quality/local/canary/acme-1/refused_in_checks.py": "ACME_REFUSED = True\n",
        "quality/local/canary/acme-1/refused_in_models.py": "ACME_REFUSED = True\n",
        "quality/local/negative/acme-1/not_refused.py": "ACME_REFUSED = False\n",
    }
    try:
        with drawer(world, DJANGO_DRAWER, files):
            rules.write_text(text.replace(anchor, anchor + "        acme_orders: [checks]\n"))
            ran = world.run(
                [PY, "-m", "quality.gate", "--selftest", "--rule", "acme-1"],
                {
                    "DATABASE_NAME": os.environ.get(
                        "DATABASE_NAME", "djb_drawer_world_never_connected"
                    )
                },
            )
    finally:
        rules.write_bytes(saved)
        shutil.rmtree(app, ignore_errors=True)
    assert ran.rc == 0 and "selftest clean for rule(s) acme-1" in ran.out, ran.why(
        "a product's django check did not fire under its own namespace"
    )
    assert "CANARY DEAD" not in ran.out, ran.why("a canary died")


def test_a_product_scope_kind_points_a_drawer_rule_at_its_own_files(world: World) -> None:
    """A product scope kind joins SCOPE_KINDS, points a drawer rule at docs/."""
    mark = "UNFINISHED" + "-LEDGER-ROW"
    files = {
        "quality/local/runners/ledger_probe.py": KIND_RUNNER,
        "quality/local/canary/acme-2/stale_row.md": f"A ledger row: {mark}\n",
        "quality/local/canary/acme-2/stale_row_in_a_list.md": (
            f"# A plan\n\n- the second form, a row inside a list: {mark}\n"
        ),
        "quality/local/negative/acme-2/named_row.md": (
            "A ledger row, with its artifact: apps/example/models.py\n"
        ),
    }
    with drawer(world, KIND_DRAWER, files):
        ran = world.forge(KIND_SCRIPT, {"DJB_RULES_NO_MEMO": "1"})
        explained = world.gate("--explain", "acme-2")
        inputs = world.run([PY, "-m", "quality.gate", "--selftest-inputs"])
    assert ran.rc == 0, ran.why("a product rule cannot be about the product's own files")
    assert "home: quality/local/rules.yaml" in explained.out, explained.why(
        "--explain names no drawer home"
    )
    assert inputs.rc == 0 and ".env.example" in inputs.out.splitlines(), inputs.why(
        "--selftest-inputs does not carry the kind's file root"
    )


def test_no_drawer_is_byte_identical(world: World) -> None:
    """With no drawer, and with an empty one, `--rules` is byte-identical."""
    before = world.gate("--rules")
    local = world.root / "quality" / "local"
    local.mkdir()
    try:
        after = world.gate("--rules")
    finally:
        local.rmdir()
    assert before.rc == 0 and after.rc == 0, after.why("the listing did not answer")
    assert before.out == after.out, after.why("an EMPTY quality/local/ moved the listing")


# -- the tree census under --explain -------------------------------------------


@pytest.fixture(scope="session")
def census(world: World, tmp_path_factory: pytest.TempPathFactory) -> Readers:
    """The seven census probes, captured once in one process over the world."""
    home = tmp_path_factory.mktemp("census")
    path = tmp_path_factory.mktemp("censuspath")
    (path / "zzz_census_probe.py").write_text(CENSUS_PROBE)
    ran = world.forge(CENSUS_SCRIPT, {"DJB_CENSUS_DIR": str(home), "DJB_CENSUS_PATH": str(path)})
    if ran.rc != 0:
        raise CouldNotLook(ran.why("the census capture did not complete"))
    return Readers(home, 0, 0)


def test_a_declared_census_prints_its_lines_under_explain(census: Readers) -> None:
    """The callable's lines print under 'census (this tree):', after the rule's own declaration."""
    ran = census("with-census")
    lines = ran.out.splitlines()
    assert ran.rc == 0, ran.why("--explain on a rule with a working census failed")
    for want in (
        "census (this tree):",
        "  the first line this tree offered",
        "  the second line this tree offered",
        "negatives:",
    ):
        assert want in lines, ran.why(f"no line {want!r}")


def test_a_rule_with_no_census_explains_byte_identically(census: Readers) -> None:
    """Cut the census block out and the capture is the no-census capture's bytes."""
    ran = census("stripped-matches-plain")
    assert ran.rc == 0, ran.why("a rule declaring no census no longer explains as it did")


def test_a_census_that_does_not_resolve_is_exit_2_naming_it(census: Readers) -> None:
    """A census naming a callable that is not there is enforcement broken, naming it."""
    ran = census("unresolvable")
    assert (
        ran.rc == 2
        and "zzz_census_probe.no_such_callable" in ran.out
        and "does not resolve" in ran.out
    ), ran.why("an unresolvable census did not name itself")


def test_a_census_that_raises_is_a_could_not_look_line(census: Readers) -> None:
    """A stumbling census says so on its own line and the whole declaration still prints."""
    ran = census("raises")
    lines = ran.out.splitlines()
    assert (
        "  could not look: zzz_census_probe.boom raised RuntimeError: this tree would not answer"
        in lines
    ), ran.why("no could-not-look line")
    assert any(ln.startswith("selftest_floor:") for ln in lines) and "statement:" in lines, ran.why(
        "the declaration went down with the census"
    )


def test_rule_59s_census_is_the_per_app_draft_block(census: Readers) -> None:
    """Rule 59's census groups every undecided noun under its app with the EVENT_KINDS line to."""
    ran = census("rule59-planted")
    lines = ran.out.splitlines()
    assert ran.rc == 0 and "census (this tree):" in lines, ran.why("no census block")
    assert "  apps/example/events.py — 1 undecided noun; paste into EVENT_KINDS:" in lines, ran.why(
        "no app line"
    )
    assert any(ln.startswith('      "gizmo": ') for ln in lines), ran.why("no gizmo line to paste")


def test_rule_54s_census_lists_a_silent_read_with_the_line_that_opens_it(census: Readers) -> None:
    """Rule 54's census lists a silent read with its opening, an asking read with its doors."""
    import re

    ran = census("rule54-planted")
    out = ran.out
    assert ran.rc == 0 and "census (this tree):" in out.splitlines(), ran.why("no census block")
    assert re.search(
        r"^  apps/zzz_canary/selectors.py:[0-9]* list_gadgets -> Gadget \(gadget\); asks NOTHING",
        out,
        re.M,
    ), ran.why("the planted silent read is not listed")
    assert 'opening: take `actor: Actor` and call require(actor, "gadget.read"' in out, ran.why(
        "no opening"
    )
    assert (
        "list_memberships -> Membership (membership); asks membership.read at the acting hat" in out
    ), ran.why("the asking row is lost")
    assert re.search(
        r"list_memberships .*door: apps/core/api/routes.py \(route\), apps/core/mcp.py \(tool\)",
        out,
    ), ran.why("the asking row does not name every door")
    assert "asks nothing — `# read-open:" in out and "opening: already open" in out, ran.why(
        "the open reads are not listed"
    )


def test_rule_54s_census_agrees_with_the_rules_own_read_findings(census: Readers) -> None:
    """On the tree and on the planted one the census's silent rows are exactly rule 54's."""
    ran = census("rule54-agrees")
    assert ran.rc == 0, ran.why("the census and rule 54 disagree about this tree")


# -- the scripts and drawers the cases above plant, verbatim from the drive's bodies --

E2E_DRAWER = r"""
rules:
  - id: acme-1
    name: acme-no-auth-user-import
    enabled: true
    statement: >
      The product's own rule, re-scoping a registry check the template ships.
    check: auth_user_import
    doc: { file: docs/product/architecture.md, contains: "`auth.User` is never imported" }
    valve:
      marker: "<comment> rule-acme-1: <reason>"
      where: on the flagged line itself, or in the contiguous comment block directly above it
    scope: {}
    floors: { files_scanned: 90 }
    does_not_cover: >
      whatever rule 1 does not cover; this entry exists to drive the drawer.
    selftest_floor: { canaries: 2, negatives: 1 }
    canaries:
      - fixture: import_user.py
        plant_at: apps/example/services.py
        mode: append
      - fixture: fk_label.py
        plant_at: apps/example/models.py
        mode: append
    negatives:
      - fixture: get_user_model.py
        plant_at: apps/example/services.py
        mode: append
"""


E2E_SCRIPT = r"""
import sys
sys.argv = ["gate"]
from quality import gate

print("namespace:", gate.RULE_ID_NAMESPACE, gate.TEMPLATE_IDS_THROUGH)
print("local ids:", sorted(gate.LOCAL_RULE_IDS))
gate.broken.clear()
gate.consistency()
print("consistency broken:", gate.broken)
rule = gate.RULES_BY_ID["acme-1"]
fired = []
for kind in ("canaries", "negatives"):
    for entry in rule[kind]:
        plant = gate.Plant()
        try:
            plant.put(
                gate.fixture_home(kind, "acme-1") / entry["fixture"],
                entry["plant_at"],
                entry["mode"],
            )
            kept, targets, why = gate.run_rule(rule, floors=True)
        finally:
            plant.restore()
        found = [str(f) for f in kept]
        print(kind, entry["fixture"], "->", found, "targets", targets, "why", repr(why))
        fired.append((kind, bool(kept), targets.get("files_scanned", 0), why))
entry = rule["canaries"][0]
plant = gate.Plant()
try:
    home = gate.fixture_home("canary", "acme-1")
    plant.put(home / entry["fixture"], entry["plant_at"], entry["mode"])
    target = gate.ROOT / entry["plant_at"]
    target.write_text(
        target.read_text().replace(
            "from django.contrib.auth.models import User",
            "from django.contrib.auth.models import User  # rule-acme-1: the drawer own valve",
        )
    )
    kept, _targets, _why = gate.run_rule(rule, floors=False)
    counted = [row for row in gate.all_overrides() if row[0] == "acme-1"]
finally:
    plant.restore()
print("valve suppressed:", not kept, "counted:", counted)
canaries = [f for f in fired if f[0] == "canaries"]
negatives = [f for f in fired if f[0] == "negatives"]
ok = (
    gate.RULE_ID_NAMESPACE == "acme"
    and sorted(gate.LOCAL_RULE_IDS) == ["acme-1"]
    and not gate.broken
    and len(canaries) == 2
    and all(hit and scanned >= 90 and not why for _k, hit, scanned, why in canaries)
    and all(not hit for _k, hit, _s, _w in negatives)
    and not kept
    and len(counted) == 1
)
sys.exit(0 if ok else 1)
"""


DJANGO_APPS_PY = r"""
from django.apps import AppConfig


class AcmeOrdersConfig(AppConfig):
    name = "apps.acme_orders"
    depends_on: tuple[str, ...] = ("core",)

    def ready(self) -> None:
        from apps.acme_orders import checks  # noqa: F401
"""


DJANGO_CHECKS_PY = r'''
import importlib

from django.apps import apps
from django.core import checks


@checks.register("djb")
def refused_flags(app_configs, **kwargs):
    """acme.E001 — an app module that declares ACME_REFUSED."""
    out = []
    for config in apps.get_app_configs():
        for leaf in ("checks", "models"):
            try:
                module = importlib.import_module(f"{config.name}.{leaf}")
            except ImportError:
                continue
            if getattr(module, "ACME_REFUSED", False) is True:
                out.append(
                    checks.Error(f"{config.label}.{leaf} declares ACME_REFUSED", id="acme.E001")
                )
    return out
'''


DJANGO_DRAWER = r"""
rules:
  - id: acme-1
    name: acme-refused-flags
    enabled: true
    memo:
      "no": >-
        this rule reports through the Django system-check leg, whose population
        is assembled at import time
    statement: >
      No app module declares ACME_REFUSED — the product's own system check,
      read by the django leg under the product's namespace.
    check: null
    django_check_ids: [acme.E001]
    floor_proxy: count_mount_surface
    doc: { file: docs/product/architecture.md, contains: "`auth.User` is never imported" }
    valve:
      none: >-
        this rule reports only through the django system-check leg, and those
        findings never pass through apply_overrides
    scope: {}
    floors: { mounted_routers: 1 }
    does_not_cover: >
      everything; this entry exists to drive the django leg under a namespace.
    selftest_floor: { canaries: 2, negatives: 1 }
    canaries:
      - { fixture: refused_in_checks.py, plant_at: apps/zzz_canary/checks.py, mode: create,
          via: django, expect: { id: acme.E001, contains: "zzz_canary.checks declares" } }
      # APPENDED, NEVER CREATED: the probe's `models.py` is one module the
      # whole corpus's Django batch builds, and a narrowed run plants that whole
      # batch (`gate.django_batch`) — the template's own forms create it first,
      # so a product form that also created it was refused as could-not-look.
      - { fixture: refused_in_models.py, plant_at: apps/zzz_canary/models.py, mode: append,
          via: django, expect: { id: acme.E001, contains: "zzz_canary.models declares" } }
    negatives:
      - { fixture: not_refused.py, plant_at: apps/zzz_canary/models.py, mode: append, via: django }
"""


KIND_RUNNER = r'''
"""A product's own rule about its LEDGERS — the drive's product-side runner.

THE SUBJECT IS THE RUNNER'S AND THE ROOTS ARE THE RULE'S, which is the whole
shape the fifth drawer key exists for. This instrument is about `docs/`
wherever it is pointed — exactly like the four in-process checks the first
consumer moved into the drawer — and the engine holds it to the roots its
kind declares. Under a kind rooted at `docs` it answers; under the template's
`py` kind every finding it reports is outside the roots and the whole run is
refused, which is the refusal the case drives from both sides.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MARK = "UNFINISHED" + "-LEDGER-ROW"
SUBJECT = Path("docs")


def main(argv: list[str]) -> int:
    scanned = 0
    findings: list[dict] = []
    for path in sorted(SUBJECT.rglob("*.md")) if SUBJECT.is_dir() else []:
        if not path.is_file():
            continue
        scanned += 1
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if MARK in line:
                findings.append(
                    {
                        "path": str(path),
                        "line": number,
                        "msg": "a ledger row that names no artifact",
                        "klass": "unfinished",
                    }
                )
    json.dump(
        {"protocol": "check-v1", "targets": {"files_scanned": scanned}, "findings": findings},
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
'''


KIND_DRAWER = r"""
scope_kinds:
  ledgers:
    # A DIRECTORY AND A FILE, because the seam claims both and a file root is
    # the one three readers had to be taught (V-HD1 HIGH-1). `comment: "#"` is
    # the token a product really picks for markdown, and it is what turned
    # every `# rule-13:` shaped line of prose in this repository into an
    # override of a TEMPLATE rule until the attribution was narrowed.
    roots: [docs, .env.example]
    suffixes: [".md"]
    comment: "#"
rules:
  - id: acme-2
    name: acme-every-ledger-row-names-its-artifact
    enabled: true
    kind: ledgers
    statement: >
      The product's own rule about the product's own ledgers. Every row names
      the artifact that proves it.
    check: ledger_probe
    doc: { file: docs/product/architecture.md, contains: "house rules" }
    valve:
      marker: "<comment> rule-acme-2: <reason>"
      where: on the flagged line itself, or in the contiguous comment block directly above it
    scope: {}
    floors: { files_scanned: 10 }
    does_not_cover: >
      a row whose artifact is named and does not exist; the probe reads the row,
      never the tree it points at.
    selftest_floor: { canaries: 2, negatives: 1 }
    canaries:
      - fixture: stale_row.md
        plant_at: docs/product/architecture.md
        mode: append
      - fixture: stale_row_in_a_list.md
        plant_at: docs/product/architecture.md
        mode: append
    negatives:
      - fixture: named_row.md
        plant_at: docs/product/architecture.md
        mode: append
"""


KIND_SCRIPT = r"""
import sys
sys.argv = ["gate"]
from quality import gate

print("kinds:", sorted(gate.SCOPE_KINDS))
print("local kinds:", sorted(gate.LOCAL_SCOPE_KINDS))
gate.broken.clear()
gate.consistency()
print("consistency broken:", gate.broken)
clean = not gate.broken

rule = gate.RULES_BY_ID["acme-2"]
fired = []
for kind in ("canaries", "negatives"):
    for entry in rule[kind]:
        plant = gate.Plant()
        try:
            plant.put(
                gate.fixture_home(kind, "acme-2") / entry["fixture"],
                entry["plant_at"],
                entry["mode"],
            )
            kept, targets, why = gate.run_rule(rule, floors=True)
        finally:
            plant.restore()
        paths = sorted({f.path for f in kept})
        print(kind, entry["fixture"], "->", paths, "targets", targets, "why", repr(why))
        fired.append((kind, kept, targets.get("files_scanned", 0), why))

canaries = [row for row in fired if row[0] == "canaries"]
negative = [row for row in fired if row[0] == "negatives"][0]
in_docs = all(
    row[1] and all(f.path.startswith("docs/") for f in row[1]) for row in canaries
)

# THE SAME RULE, POINTED BACK AT A TEMPLATE KIND. This is the refusal the
# consumer pasted, and the half that proves the remedy is reachable: a rule
# about docs/ whose kind is `py` is refused, and the refusal now says which
# declaration widens the roots and which FILE it is written in.
rule["kind"] = "py"
plant = gate.Plant()
try:
    entry = rule["canaries"][0]
    home = gate.fixture_home("canary", "acme-2")
    plant.put(home / entry["fixture"], entry["plant_at"], entry["mode"])
    gate.broken.clear()
    _kept, _targets, why = gate.run_rule(rule, floors=False)
finally:
    plant.restore()
    rule["kind"] = "ledgers"
print("refusal:", why)

# HIGH-2 · THE WALK IS THE UNION, THE ATTRIBUTION IS ONE RULE'"'"'S OWN ROOTS.
# With `comment: "#"` and a root of `docs`, every `# rule-<id>:` shaped line of
# prose in this repository entered the standing-override census; two carried
# "reasons" shorter than MIN_REASON and became findings recorded against
# TEMPLATE rules 13 and 16. A product kind must not be able to red a rule it
# does not own.
target = gate.ROOT / "docs" / "product" / "architecture.md"
kept_text = target.read_text()
try:
    target.write_text(
        kept_text
        + "\n# rule-13: x\n# rule-acme-2: the product own valve on its own ledger rule\n"
    )
    rows = gate.all_overrides()
finally:
    target.write_text(kept_text)
here = "docs/product/architecture.md"
template_rows = [r for r in rows if r[0] == "13" and r[1] == here]
product_rows = [r for r in rows if r[0] == "acme-2" and r[1] == here]
print("template rule rows in docs/:", template_rows)
print("product rule rows in docs/:", product_rows)
attribution = not template_rows and len(product_rows) == 1
refused = (
    "finding-outside-roots" in why
    and "scope_kinds:" in why
    and "quality/local/rules.yaml" in why
)

ok = (
    "ledgers" in gate.SCOPE_KINDS
    and sorted(gate.LOCAL_SCOPE_KINDS) == ["ledgers"]
    and clean
    and len(canaries) == 2
    and in_docs
    and all(row[2] >= 10 and not row[3] for row in canaries)
    and not negative[1]
    and refused
    and attribution
)
sys.exit(0 if ok else 1)
"""


CENSUS_PROBE = r'''
"""A census that answers, and one that stumbles. Never on the checkout."""


def two_lines(root, rule):
    return ["the first line this tree offered", "the second line this tree offered"]


def boom(root, rule):
    raise RuntimeError("this tree would not answer")
'''


CENSUS_SCRIPT = r'''
import copy
import os
import re
import pathlib
import sys

sys.argv = ["gate"]
sys.path.insert(0, os.environ["DJB_CENSUS_PATH"])
from quality import gate

out = pathlib.Path(os.environ["DJB_CENSUS_DIR"])


def keep(name, rc, text):
    (out / (name + ".log")).write_text(text, encoding="utf-8")
    (out / (name + ".rc")).write_text(str(rc), encoding="utf-8")


# The victim is a copy registered under its own id, so the engine's real
# `explain` reads it exactly as it reads every other rule.
plain = copy.deepcopy(gate.RULES_BY_ID["13"])
plain.pop("census", None)
gate.RULES_BY_ID["13"] = plain
rc_plain, text_plain = gate._captured(["--explain", "13"])
keep("no-census", rc_plain, text_plain)

with_census = copy.deepcopy(plain)
with_census["census"] = "zzz_census_probe.two_lines"
gate.RULES_BY_ID["13"] = with_census
keep("with-census", *gate._captured(["--explain", "13"]))

# THE BYTE-IDENTICAL HALF, computed where both captures are in hand: cut the
# census block — the blank line, the header, its indented lines — out of the
# capture that has one, and what is left must be the other capture's bytes. A
# rule that declares no census must explain exactly as it did before the seam
# existed, and "exactly" is a diff, not an eyeball.
lines = (out / "with-census.log").read_text(encoding="utf-8").splitlines(keepends=True)
head = [i for i, line in enumerate(lines) if line.rstrip("\n") == "census (this tree):"]
if len(head) != 1:
    keep("stripped-matches-plain", 1, f"expected one census header, found {len(head)}\n")
else:
    start = head[0] - 1  # the blank line the block opens with
    end = head[0] + 1
    while end < len(lines) and lines[end].startswith("  "):
        end += 1
    stripped = "".join(lines[:start] + lines[end:])
    same = stripped == text_plain
    keep(
        "stripped-matches-plain",
        0 if same else 1,
        "byte-identical\n"
        if same
        else "DIFFERS\n--- with the census block cut out\n"
        + stripped
        + "\n--- the same rule declaring no census\n"
        + text_plain,
    )

unresolvable = copy.deepcopy(plain)
unresolvable["census"] = "zzz_census_probe.no_such_callable"
gate.RULES_BY_ID["13"] = unresolvable
keep("unresolvable", *gate._captured(["--explain", "13"]))

raising = copy.deepcopy(plain)
raising["census"] = "zzz_census_probe.boom"
gate.RULES_BY_ID["13"] = raising
keep("raises", *gate._captured(["--explain", "13"]))

# Rule 59's real census, over a tree carrying rule 59's own undecided-noun
# canary. The plant is the shipped fixture at the shipped site, and it is
# restored whatever happens below.
rule59 = gate.RULES_BY_ID["59"]
entry = rule59["canaries"][3]
plant = gate.Plant()
try:
    plant.put(gate.CANARY_DIR / "59" / entry["fixture"], entry["plant_at"], entry["mode"])
    keep("rule59-planted", *gate._captured(["--explain", "59"]))
finally:
    plant.restore()
from quality import checks as _checks


def _reads_agreement(gate, rule54):
    """(agrees, silent rows, one readable line) for the tree as it stands now.

    The census reads clause (d)'s whole population and says how many of them
    ask nothing; the rule raises a finding for exactly those, classed
    `<app>.read`. Two numbers, ONE walker — a census that had drifted from the
    rule would be a census describing a different tree, which is what the
    one-walker discipline exists to make impossible. The header's population
    count is asserted against the rows actually printed, so a census that
    stopped printing rows cannot pass by counting none of them either.
    """
    result = _checks.authz_vocabulary_shape(gate.ROOT, rule54)
    findings = [f for f in result.findings if f.klass.endswith(".read")]
    lines = _checks.reads_census(gate.ROOT, rule54)
    header = lines[0] if lines else ""
    silent = [line for line in lines[1:] if "asks NOTHING" in line]
    rows = max(len(lines) - 2, 0)
    agrees = (
        f"{len(findings)} ask nothing" in header
        and len(silent) == len(findings)
        and rows > 0
        and f"{rows} public get_/list_ selector(s) over a kind" in header
    )
    return (
        agrees,
        len(silent),
        f"{len(findings)} read-class finding(s), {len(silent)} silent census row(s), "
        f"{rows} row(s) in all · {header}",
    )


# Rule 54's census, over a tree carrying rule 54's OWN clause-(d)
# canary: a public `list_` returning rows of a kind and asking nothing. The
# census has to print that selector WITH the line that opens it, because the
# product meeting the hard read rule at its own door is holding exactly this
# shape and CHANGELOG item 5 names no door.
rule54 = gate.RULES_BY_ID["54"]
entry54 = next(c for c in rule54["canaries"] if c["fixture"] == "list_gadgets_without_require.py")
plant54 = gate.Plant()
try:
    for extra in entry54.get("extra_files", []):
        plant54.put(gate.CANARY_DIR / "54" / extra["fixture"], extra["plant_at"], extra["mode"])
    plant54.put(gate.CANARY_DIR / "54" / entry54["fixture"], entry54["plant_at"], entry54["mode"])
    keep("rule54-planted", *gate._captured(["--explain", "54"]))
    _planted_agreement = _reads_agreement(gate, rule54)
finally:
    plant54.restore()

# AND THE CENSUS AGREES WITH THE RULE, on this tree, unplanted. The census
# reads clause (d)'s whole population and says how many of them ask nothing;
# the rule raises a finding for exactly those, classed `<app>.read`. Two
# numbers, ONE walker: a census that drifted from the rule would be a census
# describing a different tree, which is what the one-walker discipline exists
# to make impossible. Asserted rather than assumed, because the template's own
# answer is ZERO and a census that had stopped looking would print zero too —
# so the header's population count is asserted against the rows it printed.
_bare_agreement = _reads_agreement(gate, rule54)
# BOTH TREES, and the planted one is what makes this able to fail. The
# template's own answer is ZERO silent reads, so an unplanted `0 == 0` is
# satisfied by a census that had stopped looking altogether — the masking shape
# rung-execution §2 names. The planted tree has exactly one, so the pair is
# `0 == 0` and `1 == 1`, and a census that lost the class fails the second.
_agrees = _bare_agreement[0] and _planted_agreement[0] and _planted_agreement[1] == 1
keep(
    "rule54-agrees",
    0 if _agrees else 1,
    "unplanted: " + _bare_agreement[2] + "\nplanted:   " + _planted_agreement[2] + "\n"
    + ("agrees on both trees\n" if _agrees else "DISAGREES — see the two lines above\n"),
)
print("captured 7 census probes and the strip comparison")
'''


TRACED_SCRIPT = r"""
import os, sys
from pathlib import Path
from quality import gate as G

rid = "__RID__"
root = G.ROOT.resolve()
rule = G.RULES_BY_ID[rid]
if G.memo_declines(rule) is not None:
    sys.exit("rule %s declines the memo" % rid)
blobs, why = G.measured_blobs()
key, base, why = G.memo_key(rule)
if not key:
    sys.exit("rule %s: undecidable key: %s" % (rid, why))
opened, listed = set(), set()

def hook(event, args):
    if event not in ("open", "os.listdir", "os.scandir") or not args or isinstance(args[0], int):
        return
    path = Path(os.fsdecode(args[0] if args[0] is not None else "."))
    path = (path if path.is_absolute() else Path.cwd() / path).resolve()
    if path.is_relative_to(root):
        (opened if event == "open" else listed).add(path.relative_to(root).as_posix())

sys.addaudithook(hook)
G.REGISTRY[rule["check"]](G.ROOT, rule)
problems = []
for rel in sorted(p for p in opened if not p.startswith("quality/")):
    moved, w = G.memo_components(rule, measured=({**blobs, rel: "0" * 40}, ""))
    if rel not in blobs or w or moved == base:
        problems.append("reads %s and an edit to it does not move the key" % rel)
roots = [str(r) for r in G.W.scope_kind(rule, G.SCOPE_KINDS).get("roots") or []] + ["quality"]
for rel in sorted(listed):
    if rel != "." and not any(rel == r or rel.startswith(r + "/") for r in roots):
        problems.append("lists %s/, outside every walk root" % rel)
still, w = G.memo_components(rule, measured=({**blobs, "CLAUDE.md": "0" * 40}, ""))
if w or still != base:
    problems.append("an edit to CLAUDE.md, which the check never reads, moved the key")
if not opened:
    problems.append("the trace saw no read, which proves nothing")
for line in problems:
    print("rule %s: %s" % (rid, line))
counts = (rid, len(opened), len(listed), len(problems))
print("rule %s: %d read(s), %d listing(s), %d problem(s)" % counts)
sys.exit(1 if problems else 0)
"""
