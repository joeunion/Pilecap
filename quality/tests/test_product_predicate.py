"""Every invocation a product's gate reaches asks the product predicate first, or says why not."""

# does-not-cover: an invocation spelled through a name this walk does not know (a new runner verb).
# does-not-cover: control flow — "first" is a predicate call on an earlier line of the function.

from __future__ import annotations

import ast
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from quality.djb import scope

pytestmark = pytest.mark.drives(
    "quality/djb/legs/gate_tests.py",
    "quality/djb/legs/selftest.py",
    "quality/djb/scope.py",
)

ROOT = Path(__file__).resolve().parents[2]
WALKED = "quality/djb"
#: The predicate's own readers; a function calling one of them (transitively) is one too.
PREDICATES = frozenset({"product_of", "product_apps", "namespace_in", "declared_namespace"})
#: The scope module's decisions: which tests and which units a change runs.
DECISIONS = frozenset({"touched", "selection", "lane"})
#: The verbs that start a process, a gate tool or a selftest member.
RUNNERS = frozenset(
    {"tool", "run_member", "run", "Popen", "check_output", "check_call", "call"}
    | {"_streamed", "_captured", "_suite"}
)
#: What an invocation's own text (or a module constant it names) says it runs.
INVOKES = re.compile(r"pytest|--selftest|census|test\.sh|TEST_SH|test_sh")

#: (module, function) → why the site is the platform's on a product too.
PLATFORM_ONLY_INVOCATIONS: dict[tuple[str, str], str] = {
    ("quality/djb/scope.py", "tax"): (
        "prices a diff's unowned harness modules from the walls table for the lane's report;"
        " it runs no module"
    ),
    ("quality/djb/scope.py", "product_census"): (
        "rule 94's census of the selection itself: it asserts a product path selects only its"
        " owners, so it must ask the unfiltered selection"
    ),
    ("quality/djb/rituals/fold.py", "prune_map"): (
        "the post-merge fold collects the suite (`--collect-only`, no test runs) to prune the"
        " harness map the template ships"
    ),
    ("quality/djb/legs/goalpost_census.py", "census"): (
        "the instrument census reads every executable in the tree, a product's own"
        " `scripts/local/` included — whole-tree by declaration"
    ),
    ("quality/djb/legs/selftest.py", "engine_drive_file"): (
        "`--selftest-inputs` lists the engine's read set to key its member; it plants no canary"
    ),
    ("quality/djb/legs/selftest.py", "engine_members"): (
        "the engine self-test in pieces: a product's drawer rules are self-tested by the same"
        " member, and the house-rules legs are whole-tree by declaration"
    ),
    ("quality/djb/rituals/push.py", "proof"): (
        "`pm_push --proof` is the template's two-pass coverage proof that writes the harness map;"
        " a product moves main by `--pr`"
    ),
    ("quality/djb/legs/selftest.py", "members"): (
        "the engine self-test and the drives (the drive preamble is the tripwire every product"
        " drive stands on); the house-rules legs are whole-tree by declaration"
    ),
}

#: (module, function) → the function of the same module that asks the predicate, then reaches it.
GATED_BY_CALLER: dict[tuple[str, str], str] = {
    ("quality/djb/legs/pytest_x2.py", "passes"): "run",
    ("quality/djb/legs/pytest_x2.py", "grants_pass"): "run",
    ("quality/djb/legs/always_on.py", "session"): "queue_run",
    ("quality/djb/legs/selftest.py", "drawer_engine"): "members",
    ("quality/djb/scope.py", "touched"): "touched",
}

#: The day the dated rows below were written; the rung that closes a row deletes it.
KNOWN_SINCE = "2026-10-19"
#: Known reds the product-path rung closes; a row this walk finds reached reds until deleted.
KNOWN_UNGATED: dict[tuple[str, str], str] = {}
#: The behavioural reds on a product-shaped copy, dated `KNOWN_SINCE`.
KNOWN_SELECTING: frozenset[str] = frozenset()

#: Paths only a product writes: its app, its drawer, its own scripts and tests.
PRODUCT_PATHS = (
    "apps/bookings/models.py",
    "quality/local/rules.yaml",
    "scripts/local/x.sh",
    "quality/local/tests/test_x.py",
)
BOOKINGS_APP = (
    "from django.apps import AppConfig\n\n\n"
    "class BookingsConfig(AppConfig):\n"
    '    name = "apps.bookings"\n'
    '    depends_on = ("core",)\n'
)


def _name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def _asks(call: ast.Call, local: frozenset[str] | set[str]) -> bool:
    """A predicate reader by any spelling, or this module's own function that calls one."""
    name = _name(call)
    return name in PREDICATES or (isinstance(call.func, ast.Name) and name in local)


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _modules() -> dict[str, tuple[str, ast.Module]]:
    out: dict[str, tuple[str, ast.Module]] = {}
    for path in sorted((ROOT / WALKED).rglob("*.py")):
        text = path.read_text()
        out[path.relative_to(ROOT).as_posix()] = (text, ast.parse(text))
    return out


def _predicates(tree: ast.Module) -> frozenset[str]:
    """The predicate readers, and every function of this module that calls one, to a fixpoint."""
    known = set(PREDICATES)
    while True:
        grown = {
            fn.name
            for fn in _functions(tree)
            if fn.name not in known
            and any(isinstance(c, ast.Call) and _asks(c, known) for c in ast.walk(fn))
        }
        if not grown:
            return frozenset(known)
        known |= grown


def _constants(text: str, tree: ast.Module) -> dict[str, str]:
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = ast.get_source_segment(text, node.value) or ""
    return out


def _locals(text: str, fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, str]:
    """Each name the function assigns → the text of every value it is given."""
    out: dict[str, str] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    said = ast.get_source_segment(text, node.value) or ""
                    out[target.id] = f"{out.get(target.id, '')} {said}"
    return out


def _module_asks(call: ast.Call, by_stem: dict[str, frozenset[str]]) -> bool:
    """`<module>.<function>` where that walked module's function asks the predicate."""
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.attr in by_stem.get(func.value.id, frozenset())
    )


def sites() -> dict[tuple[str, str], bool]:
    """(module, function) → whether every invocation in it follows a predicate call."""
    out: dict[tuple[str, str], bool] = {}
    modules = _modules()
    by_stem = {Path(m).stem: _predicates(tree) for m, (_text, tree) in modules.items()}
    for module, (text, tree) in modules.items():
        predicates = _predicates(tree)
        constants = _constants(text, tree)
        for fn in _functions(tree):
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
            assigned = _locals(text, fn)
            asked = [c.lineno for c in calls if _asks(c, predicates) or _module_asks(c, by_stem)]
            for call in calls:
                name = _name(call)
                scoped = module == "quality/djb/scope.py" or (
                    isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "scope"
                )
                if name in DECISIONS and scoped:
                    hit = True
                elif name in RUNNERS:
                    said = ast.get_source_segment(text, call) or ""
                    args = {n.id for a in call.args for n in ast.walk(a) if isinstance(n, ast.Name)}
                    said = " ".join([said, *(assigned.get(n, "") for n in sorted(args))])
                    named = re.findall(r"\b[A-Z][A-Z_]{2,}\b", said)
                    hit = name == "run_member" or bool(
                        INVOKES.search(" ".join([said, *(constants.get(n, "") for n in named)]))
                    )
                else:
                    hit = False
                if hit:
                    reached = (
                        any(n < call.lineno for n in asked)
                        or _asks(call, predicates)
                        or _module_asks(call, by_stem)
                    )
                    key = (module, fn.name)
                    out[key] = out.get(key, True) and reached
    return out


def test_every_invocation_asks_the_product_predicate_first_or_is_declared_the_platforms() -> None:
    found = sites()
    ungated = sorted(
        f"{m}::{f}"
        for (m, f), ok in found.items()
        if not ok
        if (m, f) not in {**PLATFORM_ONLY_INVOCATIONS, **GATED_BY_CALLER, **KNOWN_UNGATED}
    )
    assert not ungated, (
        "an invocation a product's gate reaches runs before the product predicate"
        " (`gate_tests.product_of`/`product_apps`) is asked, and no `PLATFORM_ONLY_INVOCATIONS`"
        f" row says why it is the platform's: {ungated}"
    )


def test_every_declared_row_names_a_live_site_and_a_known_red_is_still_red() -> None:
    found = sites()
    declared = {*PLATFORM_ONLY_INVOCATIONS, *GATED_BY_CALLER, *KNOWN_UNGATED}
    gone = sorted(f"{m}::{f}" for m, f in declared - set(found))
    closed = sorted(f"{m}::{f}" for (m, f) in KNOWN_UNGATED if found.get((m, f)))
    assert not gone, f"a declared row names no invocation site any more — delete it: {gone}"
    assert not closed, (
        f"a known red (dated {KNOWN_SINCE}) now asks the predicate first — delete its row: {closed}"
    )


def _reaches(tree: ast.Module, start: str, goal: str) -> bool:
    """`start` calls `goal` by bare name, directly or through this module's own functions."""
    calls = {
        fn.name: {_name(c) for c in ast.walk(fn) if isinstance(c, ast.Call)}
        for fn in _functions(tree)
    }
    seen, todo = set(), [start]
    while todo:
        name = todo.pop()
        if name == goal:
            return True
        if name not in seen:
            seen.add(name)
            todo.extend(calls.get(name, ()))
    return False


def test_a_site_gated_by_its_caller_is_reached_from_a_caller_that_asks() -> None:
    modules = _modules()
    wrong = []
    for (module, fn), caller in GATED_BY_CALLER.items():
        tree = modules[module][1]
        if caller not in _predicates(tree) - PREDICATES or not _reaches(tree, caller, fn):
            wrong.append(f"{module}::{fn} ← {caller}")
    assert not wrong, (
        f"a declared caller does not ask the predicate or never reaches the site: {wrong}"
    )


def _git(at: Path, *argv: str) -> str:
    done = subprocess.run(["git", "-C", str(at), *argv], capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
    return done.stdout.strip()


@pytest.fixture(scope="module")
def product(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, str]:
    """A clone of this checkout's HEAD with a drawer and one product app: (root, base)."""
    root = tmp_path_factory.mktemp("product") / "copy"
    subprocess.run(["git", "clone", "-q", "--shared", str(ROOT), str(root)], check=True)
    _git(root, "config", "user.email", "canary@example.invalid")
    _git(root, "config", "user.name", "canary")
    (root / "quality/local").mkdir(parents=True)
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: acme\n")
    (root / "apps/bookings").mkdir()
    (root / "apps/bookings/__init__.py").write_text("")
    (root / "apps/bookings/apps.py").write_text(BOOKINGS_APP)
    (root / "apps/bookings/models.py").write_text("x = 1\n")
    _git(root, "add", "quality/local/rules.yaml", "apps/bookings")
    _git(root, "commit", "-qm", "the drawer and an app")
    base = _git(root, "rev-parse", "HEAD")
    (root / "apps/bookings/models.py").write_text("x = 2\n")
    _git(root, "commit", "-qam", "a change to the product's own app")
    return root, base


def test_a_product_path_selects_no_gate_test(product: tuple[Path, str]) -> None:
    root, _base = product
    picked = [m for m in scope.touched(root, list(PRODUCT_PATHS)) if m.startswith("quality/tests/")]
    if "touched" in KNOWN_SELECTING:
        assert picked, "the selection is clean on a product now — drop `touched` from the dates"
        return
    assert not picked, f"a product's own paths select the platform's gate tests: {picked}"


def test_a_product_change_adds_no_selftest_unit_to_the_lane(product: tuple[Path, str]) -> None:
    root, base = product
    units = scope.lane(root, base, "HEAD").units
    if "lane" in KNOWN_SELECTING:
        assert "selftest:1" in units, "the lane is clean on a product now — drop `lane`"
        return
    assert "selftest:1" not in units, f"a product change's CI lane runs the selftest: {units}"


#: A drawer that declares no namespace: the template's own reading of `quality/local/`.
TEMPLATE_DRAWER = "# the drawer's shipped example\n"


def _drawer_lane(at: Path, drawer: str, touched: tuple[str, ...]) -> scope.Lane:
    """The lane of one commit touching `touched` over a clone whose drawer reads `drawer`."""
    root = at / "copy"
    subprocess.run(["git", "clone", "-q", "--shared", str(ROOT), str(root)], check=True)
    _git(root, "config", "user.email", "canary@example.invalid")
    _git(root, "config", "user.name", "canary")
    (root / "quality/local").mkdir(parents=True)
    (root / "quality/local/rules.yaml").write_text(drawer)
    (root / "apps/bookings").mkdir()
    (root / "apps/bookings/__init__.py").write_text("")
    (root / "apps/bookings/apps.py").write_text(BOOKINGS_APP)
    (root / "apps/bookings/models.py").write_text("x = 1\n")
    _git(root, "add", "quality/local/rules.yaml", "apps/bookings")
    _git(root, "commit", "-qm", "the drawer and an app")
    base = _git(root, "rev-parse", "HEAD")
    for path in touched:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        with (root / path).open("a") as fh:
            fh.write("# touched\n")
    _git(root, "add", *touched)
    _git(root, "commit", "-qm", "the change")
    return scope.lane(root, base, "HEAD")


DRAWER_CHANGE = ("quality/local/rules.yaml", "apps/bookings/models.py")


def test_a_products_own_drawer_never_forces_the_full_lane(tmp_path: Path) -> None:
    picked = _drawer_lane(tmp_path, "rule_id_namespace: acme\n", DRAWER_CHANGE)
    assert picked.forced == [], f"a product's drawer forces the full lane: {picked.forced}"
    assert picked.word == "loop", picked.reason


def test_the_same_drawer_change_on_the_template_is_still_forced(tmp_path: Path) -> None:
    picked = _drawer_lane(tmp_path, TEMPLATE_DRAWER, DRAWER_CHANGE)
    assert picked.word == "full", picked.reason
    assert picked.forced == [("quality/local/rules.yaml", "quality/")]


def test_a_product_touching_the_platforms_rules_is_still_forced(tmp_path: Path) -> None:
    touched = ("quality/rules.yaml", "apps/bookings/models.py")
    picked = _drawer_lane(tmp_path, "rule_id_namespace: acme\n", touched)
    assert picked.word == "full", picked.reason
    assert picked.forced == [("quality/rules.yaml", "quality/")]


SCRIPT_CHANGE = ("scripts/local/stamp.sh", "apps/bookings/models.py")


def test_a_products_own_scripts_never_force_the_full_lane(tmp_path: Path) -> None:
    picked = _drawer_lane(tmp_path, "rule_id_namespace: acme\n", SCRIPT_CHANGE)
    assert picked.forced == [], f"a product's own scripts force the full lane: {picked.forced}"
    assert picked.word == "loop", picked.reason


def test_the_same_scripts_change_on_the_template_is_still_forced(tmp_path: Path) -> None:
    picked = _drawer_lane(tmp_path, TEMPLATE_DRAWER, SCRIPT_CHANGE)
    assert picked.word == "full", picked.reason
    assert picked.forced == [("scripts/local/stamp.sh", "scripts/")]
