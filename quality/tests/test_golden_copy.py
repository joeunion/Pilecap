"""Each `golden:` block of the worked example, copied by `scaffold`, builds in a throwaway app."""

# narrowed: case_all_every_verb_in_one_run — the population equality; the verb arm runs each copy
# does-not-cover: whether the worked example is GOOD — only that its fenced text is self-sufficient.
# does-not-cover: a fragment landing inside an unreachable branch, or wrong only by ORDER.
# does-not-cover: a fragment after a call that never returns (`sys.exit`, a `NoReturn` callee).
# does-not-cover: whether a block is right for every verb its list names — that verb's copy says.
# does-not-cover: the real worked example, in the self cases — the verb arm vouches for it.
# does-not-cover: a fence in an app the marker does not name (example_portal) — main's full lane.

from __future__ import annotations

import ast
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pytest

from apps.core.scaffold import copier
from apps.core.scaffold.shapes import ADOPT, NON_ROAD_VERBS, adopt_verbs, road_verbs
from quality.checks import rule_5, rule_46, rule_84
from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured, run_to

pytestmark = pytest.mark.drives(
    "apps/*/apps.py",
    "apps/*/migrations/",
    "apps/accounts/",
    "apps/conftest.py",
    "apps/core/",
    "apps/example/",
    "apps/core/scaffold/",
    "apps/core/management/commands/scaffold.py",
    "apps/testing/",
    "config/",
    "templates/",
    "manage.py",
    "pyproject.toml",
    "scripts/archaeology_lib.sh",
    "scripts/gate_refuse.sh",
    "quality/tests/fixtures/golden_copy/",
    "quality/partition.yaml",
    "quality/checks/rule_5.py",
    "quality/checks/rule_46.py",
    "quality/checks/rule_84.py",
)

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv/bin/python"
APP = "zzz_gadgets"
FIXTURES = ROOT / "quality/tests/fixtures/golden_copy"
DECOY = "golden-copy-unfenced-decoy"
OTHER_VERB_DECOY = "golden-copy-other-verb-decoy"
TERMINAL = {ast.Return: "return", ast.Raise: "raise", ast.Continue: "continue", ast.Break: "break"}
RUN = secrets.token_hex(4)


class FenceError(CouldNotLook):
    """A fence the grammar cannot read: an unknown word, a nest, an unmatched edge."""


def app_cases(known: tuple[str, ...]) -> dict[str, str]:
    """`{shape: app}` for every app beside the example whose fences name one shape."""
    cases: dict[str, str] = {}
    for app in sorted(p for p in (ROOT / "apps").iterdir() if p.is_dir()):
        if app.name == "example" or app.name.startswith(("_", ".")):
            continue
        keys: set[str] = set()
        for path in copier.sources(app):
            try:
                keys |= copier.keys_of(path.read_text(), known, f"apps/{app.name}/{path.name}")
            except copier.FenceError as error:
                raise CouldNotLook(f"the fences could not be read: {error}") from error
        shapes = {key.partition(".")[0] for key in keys}
        if shapes:
            if len(shapes) != 1 or any(k.startswith(f"{ADOPT}.") for k in keys):
                raise CouldNotLook(f"apps/{app.name} fences {sorted(keys)} — one shape, no verb")
            cases[shapes.pop()] = app.name
    return cases


KNOWN = adopt_verbs(ROOT)
CASES = app_cases(KNOWN)
COMPLETE = KNOWN[-1]


@cache
def road_url_names() -> dict[str, list[str]]:
    """Each road's url names for the noun `gadget`, as its own `Road.url_names` answers."""
    script = (
        "import django, json\ndjango.setup()\nfrom apps.core.verbs import ROADS\n"
        "print(json.dumps({v: list(r.url_names('gadget')) for v, r in ROADS.items()}))"
    )
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"}
    env["DJB_DISABLED_APPS"] = "example"
    done = subprocess.run(
        [str(PY), "-c", script], cwd=ROOT, env=env, capture_output=True, text=True
    )
    if done.returncode != 0:
        raise CouldNotLook(f"apps/core/verbs.py's ROADS would not import: {done.stderr}")
    return dict(json.loads(done.stdout.strip().splitlines()[-1]))


def extract(
    source: Path,
    destination: Path,
    verb: str,
    label: str = "",
    own: str = APP,
    prefix: tuple[tuple[str, str], ...] = (),
) -> list[str] | None:
    """`verb`'s blocks under `source` copied by the engine into `destination`; None if none."""
    key = verb if verb in CASES else f"{ADOPT}.{verb}"
    try:
        found = copier.collect(source, key, KNOWN)
    except copier.FenceError as error:
        raise FenceError(str(error)) from error
    if not found:
        return None
    copy = copier.render(found, copier.relocations("example", APP, "Gadget", prefix), label)
    copier.write_app(destination, own, copy)
    return copy.report()


def placement(root: Path, report: list[str], app: str = APP) -> list[str]:
    """Every copied statement that follows a return/raise/continue/break in its block."""
    line_re = re.compile(r"^copied (\S+) \((\d+) lines\) from (.+)$")
    span_re = re.compile(r"^(\S+):(\d+)-(\d+)$")
    walked, findings = 0, []
    for entry in report:
        match = line_re.match(entry)
        if match is None:
            continue
        relative, total = match.group(1), int(match.group(2))
        spans = []
        for span in match.group(3).split(", "):
            parsed = span_re.match(span)
            if parsed is None:
                raise CouldNotLook(
                    f"the copied line for {relative} names an unreadable span {span!r}"
                )
            spans.append((parsed.group(1), int(parsed.group(2)), int(parsed.group(3))))
        starts, at = [], 1
        for _, begin, end in spans:
            starts.append(at)
            at += max(end - begin - 1, 1) + 2
        if at - 3 != total:
            raise CouldNotLook(
                f"{relative}: the spans account for {at - 3} lines, the copy {total}"
            )
        text = (root / relative).read_text()
        try:
            tree = ast.parse(text)
        except SyntaxError as error:
            raise CouldNotLook(f"apps/{app}/{relative} does not parse: {error}") from error
        walked += 1
        lines = text.splitlines()
        for node in ast.walk(tree):
            for _, value in ast.iter_fields(node):
                if not (
                    isinstance(value, list)
                    and value
                    and all(isinstance(v, ast.stmt) for v in value)
                ):
                    continue
                for before, statement in zip(value, value[1:], strict=False):
                    word = TERMINAL.get(type(before))
                    if word is None:
                        continue
                    at = statement.lineno
                    origin = _origin(spans, starts, at)
                    findings.append(
                        f"dead: apps/{app}/{relative}:{at} · {origin} · "
                        f"follows `{word}` at :{before.lineno} — {lines[at - 1].strip()}"
                    )
                    break
    if walked == 0:
        raise CouldNotLook("no `copied` line to walk — the placement step was handed no copy")
    return sorted(findings)


def _origin(spans: list[tuple[str, int, int]], starts: list[int], number: int) -> str:
    for (source, begin, end), start in reversed(list(zip(spans, starts, strict=True))):
        if number >= start:
            return f"from {source}:{begin}-{end} (its line {begin + 1 + number - start})"
    return "from no fence"


@dataclass
class World:
    """A scratch copy of the tracked tree, the database its copy runs against, and its logs."""

    root: Path
    database: str
    logs: list[str] = field(default_factory=list)

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.test",
            "DATABASE_NAME": self.database,
            "DATABASE_URL": "",
            "DJB_DISABLED_APPS": "example",
        }

    def run(self, *argv: str) -> tuple[int, str]:
        done = subprocess.run(
            [str(PY), *argv], cwd=self.root, env=self.env(), capture_output=True, text=True
        )
        out = done.stdout + done.stderr
        self.logs.append(f"$ {' '.join(argv)} → {done.returncode}\n{out[-4000:]}")
        return done.returncode, out


def _databases(name: str, drop: bool = False) -> list[str]:
    script = (
        "import sys, django\ndjango.setup()\nfrom django.db import connection\n"
        "with connection._nodb_cursor() as c:\n"
        "    q = 'SELECT datname FROM pg_database WHERE datname LIKE %s'\n"
        "    c.execute(q, [f'%{sys.argv[1]}%'])\n"
        "    names = [n for (n,) in c.fetchall()]\n"
        "    for n in names:\n"
        "        if sys.argv[2] == 'drop': c.execute(f'DROP DATABASE IF EXISTS \"{n}\"')\n"
        "        else: print(n)\n"
    )
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"}
    env.update(DATABASE_NAME=name, DATABASE_URL="", DJB_DISABLED_APPS="example")
    done = subprocess.run(
        [str(PY), "-c", script, name, "drop" if drop else "list"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"no database answers (docker compose up -d db): {done.stderr[-800:]}")
    return done.stdout.split()


@pytest.fixture
def world(scratch: Path) -> Iterator[World]:
    """The tracked tree copied to scratch, `.env` beside it; its databases dropped at teardown."""
    if not os.access(PY, os.X_OK):
        raise CouldNotLook("no virtualenv at .venv — the copy is built with this checkout's python")
    if shutil.which("tar") is None:
        raise CouldNotLook("no tar on PATH — the scratch tree is copied with it")
    partition = (ROOT / "quality/partition.yaml").read_text()
    if re.search(rf"^\s*-\s*{APP}\s*$", partition, re.MULTILINE):
        raise CouldNotLook(f"quality/partition.yaml lists {APP} as a platform app")
    root = scratch / "world"
    root.mkdir()
    copied = subprocess.run(
        ["bash", "-c", f"git ls-files -z | tar --null -T - -cf - | tar -xf - -C {str(root)!r}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if copied.returncode != 0:
        raise CouldNotLook(f"the tracked tree could not be copied: {copied.stderr}")
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", root / ".env")
    database = f"djb_golden_{RUN}{secrets.token_hex(2)}"
    _databases(database)
    yield World(root, database)
    _databases(database, drop=True)


def _archaeology(world: World, app_dir: str) -> tuple[int, str]:
    script = (
        ". scripts/archaeology_lib.sh || exit 2\n"
        f"cd {str(world.root)!r} || exit 2\n"
        f"archaeology_scan_files $(find {app_dir} -name '*.py' -not -path '*/migrations/*')\n"
    )
    done = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def _installed(world: World, present: tuple[str, ...], absent: tuple[str, ...]) -> tuple[int, str]:
    script = (
        "import django, sys\ndjango.setup()\nfrom django.apps import apps\n"
        f"sys.exit(3 if any(apps.is_installed(a) for a in {absent!r}) else "
        f"0 if all(apps.is_installed(a) for a in {present!r}) else 4)"
    )
    return world.run("-c", script)


def _cut(app_dir: Path, verb: str) -> str:
    """Step 5's edit: the road's last route (or the verb's own cut); the name rule 74 must carry."""
    if verb == "attach":
        path = app_dir / "schemas.py"
        text = path.read_text()
        found = [
            s
            for node in ast.walk(ast.parse(text))
            if isinstance(node, ast.ClassDef) and node.name.endswith("DetailOut")
            for s in node.body
            if isinstance(s, ast.AnnAssign)
            and isinstance(s.target, ast.Name)
            and s.target.id == "tags"
        ]
        assert len(found) == 1, f"expected one `tags` field on the copy's detail Out; {len(found)}"
        lines = text.splitlines(keepends=True)
        start, end = found[0].lineno, found[0].end_lineno or found[0].lineno
        path.write_text("".join(lines[: start - 1] + lines[end:]))
        return "gadget-detail"
    name = "gadget-create" if verb == "import" else road_url_names()[verb][-1]
    path = app_dir / "api.py"
    lines = path.read_text().splitlines(keepends=True)
    kept = [line for line in lines if f'url_name="{name}"' not in line]
    assert len(kept) == len(lines) - 1, f"expected one decorator naming {name}"
    path.write_text("".join(kept))
    return name


def _declares(app_dir: Path, verb: str) -> None:
    """What a verb's copy must DECLARE beyond building, checking and passing its own test."""
    models = (app_dir / "models.py").read_text() if (app_dir / "models.py").is_file() else ""
    if verb == "duplicate":
        assert "duplicate = Duplicate(" in models
    elif verb == "merge":
        assert "merge_keeps" in models and '"entries"' in models and "class GadgetEntry" in models
    elif verb == "attach":
        assert re.search(r"attachments: ClassVar\[tuple\[str, \.\.\.\]\] = \(", models)
    elif verb == "import":
        importers = app_dir / "importers.py"
        assert importers.is_file() and "IMPORTERS" in importers.read_text()


def _build(world: World, tests: str, apps: tuple[str, ...]) -> None:
    rc, out = world.run("manage.py", "makemigrations", *apps)
    assert rc == 0 and (world.root / f"apps/{apps[-1]}/migrations/0001_initial.py").is_file(), out
    rc, out = world.run("manage.py", "check", "--tag", "djb")
    assert rc == 0, out
    rc, out = world.run("-m", "pytest", tests, "-q", "-p", "no:randomly", "-p", "no:cacheprovider")
    assert rc == 0, out


def adopt(world: World, verb: str) -> list[str]:
    """`manage.py scaffold adopt <verb>` into the world's copy app; its report lines."""
    rc, out = world.run("manage.py", "scaffold", "adopt", verb, APP, "Gadget")
    if rc == 2:
        raise CouldNotLook(f"`scaffold adopt {verb}` refused (exit 2): {out[-2000:]}")
    assert rc == 0, out
    linted = subprocess.run(
        [copier.ruff(), "check", f"apps/{APP}"], cwd=world.root, capture_output=True, text=True
    )
    assert linted.returncode == 0, linted.stdout + linted.stderr
    report = [line for line in out.splitlines() if line.startswith(("relocated:", "copied "))]
    assert report and report[0].startswith("relocated:"), out
    return report


def adopt_rules(root: Path, app: str = APP) -> list[str]:
    """The house rules an adopted copy meets on a product: 3, 5, 46 and 84, by their own readers."""
    app_dir = root / "apps" / app
    tests = "".join(p.read_text() for p in sorted((app_dir / "tests").rglob("*.py")))
    routes = re.findall(r'url_name\s*=\s*["\']([\w-]+)["\']', (app_dir / "api.py").read_text())
    found = [f"rule 3: route {name!r} named by no test" for name in routes if name not in tests]
    for rule, check in (
        ("5", rule_5.query_budget_tests),
        ("46", rule_46.door_pair_parity),
        ("84", rule_84.road_uniqueness),
    ):
        hits = check(root, {"id": rule}).findings
        found += [
            f"rule {rule}: {hit}" for hit in hits if f"apps/{app}/" in f"{hit.path} {hit.msg}"
        ]
    return found


def cycle(world: World, source: Path | None, verb: str, label: str = "") -> list[str]:
    """Copy → place → copyable → build → check → test → cut → red; the scaffold when no source."""
    app_dir = world.root / "apps" / APP
    if source is None:
        report: list[str] | None = adopt(world, verb)
    else:
        try:
            report = extract(source, app_dir, verb, label)
        except FenceError as error:
            raise CouldNotLook(f"the fences could not be read: {error}") from error
    if report is None:
        raise CouldNotLook(f"no `golden: {verb}` block — nothing to copy is not a copy that works")
    assert placement(app_dir, report) == []
    assert (app_dir / f"tests/test_golden_{verb}.py").is_file(), "the copy carries no test"
    if source is None:
        assert (app_dir / "tests/test_golden_verbs_parity.py").is_file(), "no parity module"
        assert adopt_rules(world.root) == []
    rc, out = _archaeology(world, f"apps/{APP}")
    assert rc == 0 and "archaeology-census:" not in out, out
    rc, out = _installed(world, (f"apps.{APP}",), ("apps.example",))
    assert rc == 0, f"the copy's world is not the one it claims (exit {rc}): {out}"
    _build(world, f"apps/{APP}/tests", (APP,))
    _declares(app_dir, verb)
    named = _cut(app_dir, verb)
    rc, out = world.run("manage.py", "check", "--tag", "djb")
    assert rc == 1 and "djb.E074" in out and named in out, out
    return report


def app_cycle(world: World, word: str) -> None:
    """An app case: the complete noun copied, the app whole beside it, built, its door cut."""
    label, into = CASES[word], f"zzz_{word}"
    adopt(world, COMPLETE)
    where = (
        (f"apps.{label}", f"apps.{into}"),
        (f"apps/{label}/", f"apps/{into}/"),
        (f'"{label}.', f'"{into}.'),
        ('"example"', f'"{APP}"'),
    )
    report = extract(
        ROOT / "apps" / label,
        world.root / "apps" / into,
        word,
        f"apps/{label}/",
        into,
        where,
    )
    if report is None:
        raise CouldNotLook(f"apps/{label} carries no `golden: {word}` block")
    assert placement(world.root / "apps" / into, report, into) == []
    assert (world.root / f"apps/{into}/tests").is_dir()
    table = world.root / "frontend/src/kit/routes.ts"
    if table.is_file():
        fenced = re.compile(rf"(//\s*golden:\s*{word}\s+begin.*?//\s*golden:\s*{word}\s+end)", re.S)
        table.write_text(
            fenced.sub(
                lambda m: m.group(1).replace("Widget", "Gadget").replace("widget", "gadget"),
                table.read_text(),
            )
        )
    rc, out = _archaeology(world, f"apps/{into}")
    assert rc == 0 and "archaeology-census:" not in out, out
    rc, out = _installed(world, (f"apps.{APP}", f"apps.{into}"), ("apps.example", f"apps.{label}"))
    assert rc == 0, f"the world is not the one it claims (exit {rc}): {out}"
    _build(world, f"apps/{into}/tests", (APP, into))
    (world.root / f"apps/{into}/mcp.py").unlink()
    rc, out = world.run("manage.py", "check", "--tag", "djb")
    assert rc == 1 and "djb.E017" in out and f"apps/{into}/api.py" in out, out


def _plant(source: Path, kind: str, verb: str = "archive") -> int:
    """Each fixture under `<verb>/` behind an unfenced decoy line; `build` takes the negatives."""
    planted = 0
    for fixture in sorted((FIXTURES / verb).rglob("*.py")):
        rel = fixture.relative_to(FIXTURES / verb)
        negative = FIXTURES / "negative" / verb / rel
        origin = negative if kind == "build" and negative.is_file() else fixture
        target = source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        decoy = f'raise ImportError("{DECOY}: text outside a fence was copied")\n\n'
        target.write_text(decoy + origin.read_text())
        planted += 1
    if planted == 0:
        raise CouldNotLook(f"no self-case fixtures at {FIXTURES / verb}")
    return planted


def _fenced(root: Path, verb: str) -> int:
    opens = re.compile(rf"golden:( [a-z]+)* {verb}( [a-z]+)* begin")
    return sum(1 for p in root.rglob("*.py") if opens.search(p.read_text()))


def test_self_a_typo_d_verb_in_a_fence_is_refused(scratch: Path) -> None:
    source = scratch / "typo-src"
    source.mkdir()
    shutil.copy(FIXTURES / "typo/models.py", source / "models.py")
    with pytest.raises(FenceError) as refused:
        extract(source, scratch / "typo" / APP, "archive")
    assert "verison" in str(refused.value) and "no verb this grammar knows" in str(refused.value)


def test_self_plants_into_an_empty_source_whose_only_fences_are_the_fixture(scratch: Path) -> None:
    build, canary = scratch / "src", scratch / "canary-src"
    planted = _plant(build, "build")
    assert _plant(canary, "canary") == planted
    assert sorted((FIXTURES / "negative/archive").rglob("*.py")), "no clean negative to build from"
    assert (_fenced(build, "archive"), _fenced(canary, "archive")) == (planted, planted)


def test_self_a_fragment_after_return_reds_placement(scratch: Path) -> None:
    canary = scratch / "canary-src"
    _plant(canary, "canary")
    report = extract(canary, scratch / "canary" / APP, "archive")
    assert report is not None
    found = placement(scratch / "canary" / APP, report)
    assert len(found) == 1, found
    assert re.match(
        rf"^dead: apps/{APP}/services\.py:[0-9]+ · from services\.py:[0-9]+-[0-9]+ "
        r".*require_live\(",
        found[0],
    ), found


def test_self_plants_a_fenced_block_and_the_copy_builds_checks_and_passes(
    world: World, scratch: Path
) -> None:
    source = scratch / "src"
    _plant(source, "build")
    cycle(world, source, "archive")
    copy = world.root / "apps" / APP
    texts = "".join(p.read_text() for p in copy.rglob("*.py"))
    assert DECOY not in texts, "text outside a fence was copied"
    assert OTHER_VERB_DECOY not in texts, "a block fenced for another verb alone was copied"
    assert OTHER_VERB_DECOY in "".join(p.read_text() for p in source.rglob("*.py"))
    assert "golden-copy-two-verb-fence" in texts, "the `archive version` fence was not copied"


ARMS = (*KNOWN, *CASES)
# The verb arm's own globs: the fences and road table it reads; `full_gate` keeps it out of a loop.
VERB_ARM_DRIVES = (
    "apps/example/",
    "apps/example_portal/",
    "apps/core/verbs.py",
    "frontend/src/kit/routes.ts",
)


@pytest.mark.full_gate
@pytest.mark.drives(*VERB_ARM_DRIVES)
@pytest.mark.parametrize("verb", ARMS)
def test_verb_the_worked_example_copies_builds_checks_and_passes(world: World, verb: str) -> None:
    if verb in CASES:
        app_cycle(world, verb)
    else:
        cycle(world, None, verb)


def test_all_every_verb_in_one_run() -> None:
    assert road_verbs(ROOT), "apps/core/verbs.py's ROADS names no road"
    assert list(ARMS) == [*road_url_names(), *NON_ROAD_VERBS, *CASES]


def test_the_cleanup_census_leaves_nothing() -> None:
    for name in (APP, *(f"zzz_{w}" for w in CASES)):
        assert not (ROOT / "apps" / name).exists(), f"apps/{name} exists in the checkout"
    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=all", "--", "apps"],
        capture_output=True,
        text=True,
    )
    assert APP not in status.stdout
    assert _databases(f"djb_golden_{RUN}") == []


FOLD = (
    "import sys; from pathlib import Path; from quality.djb.rituals.fold import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
FENCED = """\
# golden: archive begin
FENCED_FOR_ARCHIVE = 1
# golden: archive end
UNFENCED = 2
"""


@pytest.mark.drives("quality/djb/rituals/fold.py", "pyproject.toml")
def test_fold_goldens_regenerates_is_a_no_op_when_clean_and_restores_a_hand_edit(
    scratch: Path,
) -> None:
    repo = scratch / "fold-goldens"
    for rel in ("apps/core/verbs.py", "pyproject.toml"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, repo / rel)
    (repo / "apps/core/scaffold").mkdir(parents=True)
    (repo / "apps/core/scaffold/__init__.py").write_text("")
    (repo / "apps/example").mkdir(parents=True)
    (repo / "apps/example/models.py").write_text(FENCED)

    def git(*argv: str) -> str:
        done = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def fold(n: int) -> Captured:
        env = {**os.environ, "PYTHONPATH": str(ROOT), "DJB_FOLD_UV": str(scratch / "no-uv")}
        argv = [sys.executable, "-c", FOLD, "--only", "goldens"]
        return run_to(scratch / f"fold-goldens-{n}.out", argv, repo, env)

    git("init", "-q")
    git("config", "user.email", "drive@example.invalid")
    git("config", "user.name", "goldens drive")
    git("config", "commit.gpgsign", "false")
    git("add", "-A")
    git("commit", "-qm", "base")
    first = fold(1)
    assert first.rc == 0, first.text()
    assert git("log", "-1", "--format=%s") == "fold: goldens regenerated", first.text()
    extract = repo / copier.GOLDENS / "adopt.archive/models.py-tpl"
    assert extract.read_text() == "FENCED_FOR_ARCHIVE = 1\n"
    again = fold(2)
    assert again.rc == 0 and "NOTHING TO FOLD" in again.text(), again.text()
    extract.write_text("FENCED_FOR_ARCHIVE = 99\n")
    git("commit", "-qam", "a hand edit to an extract")
    assert copier.drift(repo) == [f"adopt.archive/models.py{copier.SUFFIX}"]
    restored = fold(3)
    assert restored.rc == 0, restored.text()
    assert extract.read_text() == "FENCED_FOR_ARCHIVE = 1\n" and copier.drift(repo) == []
