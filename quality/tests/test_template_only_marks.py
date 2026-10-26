"""The template-only mark under `quality/tests`: typed, honoured, and worn by every reader."""

# does-not-cover: a read through a fixture, another module's helper, or a non-literal path.

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from quality.djb.rituals import publish
from quality.tests import conftest, harness

pytestmark = pytest.mark.drives(
    "quality/tests/harness.py",
    "quality/tests/conftest.py",
    "apps/testing/template_only.py",
    "scripts/archaeology_lib.sh",
)

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "quality" / "tests"
#: The publication manifest's buckets a product never receives at their own path (R8's, R10's).
ABSENT_ON_A_PRODUCT = frozenset({"TRIM", "SKELETON-SOURCE"})
CLASSIFY_SH = (
    'for p in "$@"; do rules_for "$p" >/dev/null;'
    ' printf "%s\\t%s\\t%s\\n" "$p" "$RULES_FOR" "$(bucket_for_rule "$RULES_FOR")"; done\n'
)
Nested = Callable[..., tuple[int, str]]
WHY = "the skeleton sources exist only in the template"


def _is_the_mark(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "template_only"
        and isinstance(node.value, ast.Attribute)
        and node.value.attr == "mark"
        and isinstance(node.value.value, ast.Name)
        and node.value.value.id == "pytest"
    )


def _string_reason(decorator: ast.expr) -> str | None:
    if not isinstance(decorator, ast.Call) or decorator.args:
        return None
    for keyword in decorator.keywords:
        value = keyword.value
        if keyword.arg == "reason" and isinstance(value, ast.Constant):
            return str(value.value).strip() or None if isinstance(value.value, str) else None
    return None


def _modules() -> Iterator[tuple[str, ast.Module]]:
    for path in sorted(TESTS.rglob("test_*.py")):
        if "fixtures" in path.relative_to(TESTS).parts:
            continue
        yield path.relative_to(ROOT).as_posix(), ast.parse(path.read_text(), str(path))


def _functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def _is_marked(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(
        _is_the_mark(d.func if isinstance(d, ast.Call) else d) for d in function.decorator_list
    )


def _mark_findings() -> tuple[int, list[str]]:
    """(how many tests wear the mark, every mark that is not a literal reasoned decorator)."""
    count, findings = 0, []
    for module, tree in _modules():
        on_a_test: set[int] = set()
        for function in _functions(tree):
            for decorator in function.decorator_list:
                target = decorator.func if isinstance(decorator, ast.Call) else decorator
                if not _is_the_mark(target):
                    continue
                on_a_test.add(id(target))
                if _string_reason(decorator) is None:
                    findings.append(f"{module}::{function.name} wears the mark with no reason=")
                else:
                    count += 1
        findings.extend(
            f"{module}:{getattr(node, 'lineno', '?')} spells the mark off a test's decorator"
            for node in ast.walk(tree)
            if _is_the_mark(node) and id(node) not in on_a_test
        )
    return count, findings


def _path_of(node: ast.AST, known: dict[str, str]) -> str | None:
    """The checkout-relative path a `ROOT / "a" / "b"` chain names, or `None`."""
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _path_of(node.left, known)
        right = node.right
        if left is None or not isinstance(right, ast.Constant) or not isinstance(right.value, str):
            return None
        return f"{left}/{right.value}".strip("/")
    return None


def _anchored(tree: ast.Module) -> dict[str, str]:
    """Module-level names bound to the checkout root (`""`) or to a path under it."""
    known: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if any(isinstance(n, ast.Name) and n.id == "__file__" for n in ast.walk(node.value)):
            if "parents" in ast.unparse(node.value) or "parent" in ast.unparse(node.value):
                known.setdefault(target.id, "")
            continue
        path = _path_of(node.value, known)
        if path:
            known[target.id] = path
    return known


def _reads(tree: ast.Module) -> dict[str, set[str]]:
    """Every function → the anchored paths it names, through the module's own helpers."""
    known = _anchored(tree)
    direct: dict[str, set[str]] = {}
    calls: dict[str, set[str]] = {}
    for function in _functions(tree):
        names: set[str] = set()
        for node in ast.walk(function):
            path = _path_of(node, known)
            if path:
                names.add(path)
        direct[function.name] = names
        calls[function.name] = {
            n.func.id
            for n in ast.walk(function)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
    reach = {name: set(paths) for name, paths in direct.items()}
    changed = True
    while changed:
        changed = False
        for name, callees in calls.items():
            for callee in callees & reach.keys():
                if not reach[callee] <= reach[name]:
                    reach[name] |= reach[callee]
                    changed = True
    return reach


def _absent_on_a_product(paths: set[str]) -> dict[str, str]:
    """Each path → its bucket, kept when a product never receives the path (or a file under it)."""
    probes: dict[str, str] = {}
    for path in sorted(paths):
        listed = publish.git("ls-files", "--", path, cwd=ROOT).stdout.split()
        for file in listed[:1] or [path]:
            probes[file] = path
    done = publish.library(ROOT, CLASSIFY_SH, *probes)
    assert done.returncode == 0, f"the archaeology library exited {done.returncode}"
    absent: dict[str, str] = {}
    for row in done.stdout.splitlines():
        file, rule, bucket = row.split("\t")
        if bucket in ABSENT_ON_A_PRODUCT:
            absent[probes[file]] = f"{rule} {bucket}"
    return absent


def _unmarked_readers() -> list[str]:
    per_module = [(module, tree, _reads(tree)) for module, tree in _modules()]
    every = {path for _m, _t, reach in per_module for paths in reach.values() for path in paths}
    absent = _absent_on_a_product(every)
    findings = []
    for module, tree, reach in per_module:
        for function in _functions(tree):
            if not function.name.startswith("test_") or _is_marked(function):
                continue
            for path in sorted(reach.get(function.name, set()) & absent.keys()):
                findings.append(
                    f"{module}::{function.name} reads {path} ({absent[path]} — a product has "
                    'no such path): mark it @pytest.mark.template_only(reason="…")'
                )
    return findings


def test_every_mark_under_quality_tests_is_a_literal_decorator_with_a_reason() -> None:
    _count, findings = _mark_findings()
    assert findings == [], "\n".join(findings)


def test_every_test_that_reads_a_path_no_product_has_wears_the_mark() -> None:
    findings = _unmarked_readers()
    assert findings == [], "\n".join(findings)


def test_the_reader_census_sees_a_skeleton_read_through_a_helper() -> None:
    skeletons = "/".join(("docs/product", "skeletons"))
    reports = "/".join(("docs/product", "reports"))
    tree = ast.parse(
        "from pathlib import Path\n"
        "ROOT = Path(__file__).resolve().parents[2]\n"
        f"SKELETONS = ROOT / {skeletons!r}\n"
        "def _copy():\n    return SKELETONS / 'queue.md'\n"
        "def test_reads():\n    _copy()\n"
        f"def test_plants(tmp_path):\n    (tmp_path / {skeletons!r}).mkdir()\n"
    )
    reach = _reads(tree)
    assert reach["test_reads"] == {skeletons, f"{skeletons}/queue.md"}
    assert reach["test_plants"] == set()
    absent = _absent_on_a_product(reach["test_reads"])
    assert absent[skeletons] == "R10 SKELETON-SOURCE", absent
    assert _absent_on_a_product({"docs/product/cycles/README.md", "docs/product/queue.md"}) == {}
    assert _absent_on_a_product({reports}) == {reports: "R8 TRIM"}


def test_the_quality_conftest_wires_the_harness_honour() -> None:
    for hook in ("pytest_collection_modifyitems", "pytest_testnodedown"):
        assert getattr(conftest, hook, None) is getattr(harness, hook), hook


# --- the honour, driven ----------------------------------------------------------


class _Item:
    def __init__(self, nodeid: str, path: Path, reason: str | None) -> None:
        self.nodeid = nodeid
        self.path = path
        self._mark = None if reason is None else SimpleNamespace(args=(), kwargs={"reason": reason})
        self.added: list[Any] = []

    def get_closest_marker(self, name: str) -> Any:
        return self._mark if name == "template_only" else None

    def add_marker(self, marker: Any) -> None:
        self.added.append(marker)


def _collect(namespace: str | None, monkeypatch: pytest.MonkeyPatch) -> tuple[list[Any], list[Any]]:
    import quality.engine.rules as rules

    monkeypatch.setattr(rules, "declared_namespace", lambda doc=None: namespace)
    deselected: list[Any] = []
    config = SimpleNamespace(
        rootpath=ROOT,
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    items: list[Any] = [
        _Item("quality/tests/test_a.py::test_marked", TESTS / "test_a.py", WHY),
        _Item("quality/tests/test_a.py::test_plain", TESTS / "test_a.py", None),
        _Item("apps/x/tests/test_b.py::test_marked", ROOT / "apps/x/tests/test_b.py", WHY),
    ]
    monkeypatch.setattr(harness, "_WITHHELD", [])
    harness.pytest_collection_modifyitems(config, items)  # type: ignore[arg-type]
    return items, deselected


def test_a_product_deselects_the_marked_quality_test_naming_the_declaration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    items, deselected = _collect("acme", monkeypatch)
    assert [i.nodeid for i in deselected] == ["quality/tests/test_a.py::test_marked"]
    assert [i.nodeid for i in items] == [
        "quality/tests/test_a.py::test_plain",
        "apps/x/tests/test_b.py::test_marked",
    ]
    assert items[1].added == [], "the apps tree's own honour skips its tests; this one leaves them"
    assert harness._WITHHELD == [
        "deselected quality/tests/test_a.py::test_marked — "
        f"template-only: this tree declares rule_id_namespace acme; {WHY}"
    ]


def test_the_template_deselects_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    items, deselected = _collect(None, monkeypatch)
    assert deselected == [] and len(items) == 3 and harness._WITHHELD == []


PLANTED = {
    "sub/conftest.py": (
        "import quality.engine.rules as rules\n\n"
        "rules.declared_namespace = lambda doc=None: 'acme'\n"
    ),
    "sub/test_pins.py": (
        "import pytest\n\n\n"
        f"@pytest.mark.template_only(reason={WHY!r})\n"
        "def test_pin_one():\n    assert False, 'a product ran a template pin'\n\n\n"
        f"@pytest.mark.template_only(reason={WHY!r})\n"
        "def test_pin_two():\n    assert False, 'a product ran a template pin'\n\n\n"
        "def test_the_rest():\n    assert True\n"
    ),
}


@pytest.mark.parametrize("workers", [0, 2])
def test_a_product_collection_withholds_both_pins_through_the_real_harness(
    nested_pytest: Nested, workers: int
) -> None:
    rc, out = nested_pytest(PLANTED, workers=workers)
    assert rc == 0, out
    assert "harness: 1 passed · 0 failed · 0 could not look" in out, out
    for pin in ("test_pin_one", "test_pin_two"):
        assert (
            f"test_pins.py::{pin} — template-only: this tree declares rule_id_namespace acme; {WHY}"
            in out
        ), out
    if workers == 0:
        assert "1 passed, 2 deselected" in out, out


def test_a_template_collection_runs_both_pins(nested_pytest: Nested) -> None:
    rc, out = nested_pytest({"sub/test_pins.py": PLANTED["sub/test_pins.py"]})
    assert rc == 1, out
    assert "harness: 1 passed · 2 failed · 0 could not look" in out, out


# --- an undeclared release's clone: refused before collection, never 22 reds ------


def test_the_template_source_is_the_manifests_never_shipped_directory() -> None:
    honour = harness._template_only()
    assert honour.TEMPLATE_SOURCE == publish.SKELETONS
    assert (ROOT / honour.DAY_ZERO).is_file()


def test_an_undeclared_tree_with_no_skeleton_sources_is_refused_naming_declare(
    scratch: Path,
) -> None:
    sentence = harness._template_only().undeclared_artifact_refusal(scratch, {})
    assert sentence is not None
    assert "manage.py declare <ns>" in sentence and "docs/sdk/day-zero.md" in sentence
    assert "\n" not in sentence, "the refusal is one line"


def test_a_declared_product_and_the_template_are_never_refused(scratch: Path) -> None:
    honour = harness._template_only()
    assert honour.undeclared_artifact_refusal(scratch, {"rule_id_namespace": "acme"}) is None
    assert honour.undeclared_artifact_refusal(ROOT, {}) is None
    assert honour.undeclared_artifact_refusal() is None, "this checkout is the template's own"


def test_the_harness_refuses_at_configure_with_exit_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    honour = harness._template_only()
    monkeypatch.setattr(harness, "_template_only", lambda: honour)
    monkeypatch.setattr(honour, "undeclared_artifact_refusal", lambda: "template-only: planted")
    with pytest.raises(pytest.exit.Exception) as refused:
        harness.pytest_configure(SimpleNamespace(getoption=lambda *a, **k: ""))  # type: ignore[arg-type]
    assert refused.value.returncode == 2 and str(refused.value.msg) == "template-only: planted"
