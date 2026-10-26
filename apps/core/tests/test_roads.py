"""The road marker: what `@road` refuses, what it records, and what it imports.

The marker is the only hand-written part of the roads index, so its refusals
are the index's first tooth: a job key the census would refuse, an example
that names nothing, or a target whose docstring cannot be the contract are all
refused at import, before anything is registered.
"""

from __future__ import annotations

import ast
import importlib
import io
import json
import subprocess
import sys
import textwrap
import types
from collections.abc import Callable
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import override_settings

from apps.core import roads
from apps.core.management.commands.roads import _engine, import_road, resolve_example
from apps.core.roads import REGISTRY, road

ROOT = Path(__file__).resolve().parents[3]


def _module_with(source: str) -> types.ModuleType:
    """A throwaway module whose definitions are module-level, as a road must be."""
    module = types.ModuleType("apps_core_roads_probe")
    code = compile(textwrap.dedent(source), "<road probe>", "exec")
    exec(code, module.__dict__)  # noqa: S102 — the probe's own literal source, nothing read in
    return module


def test_a_marked_function_with_a_docstring_registers_once() -> None:
    before = len(REGISTRY)
    try:
        probe = _module_with(
            """
            from apps.core.roads import road

            @road("frobnicate", example="apps/core/tests/test_roads.py::test_frobnicate")
            def frobnicate():
                \"\"\"Frobnicate the one way this platform frobnicates.\"\"\"
            """
        )
        assert probe.frobnicate.__road__ == {
            "job": "frobnicate",
            "example": "apps/core/tests/test_roads.py::test_frobnicate",
        }
        assert REGISTRY[before:] == [("frobnicate", probe.frobnicate)]
    finally:
        del REGISTRY[before:]


def test_a_target_with_no_docstring_is_refused_naming_it() -> None:
    before = len(REGISTRY)
    probe = _module_with("def undocumented():\n    pass\n")
    marker = road("frobnicate", example="apps/core/tests/test_roads.py::test_frobnicate")
    with pytest.raises(ValueError, match="undocumented: the target has no docstring"):
        marker(probe.undocumented)
    assert len(REGISTRY) == before
    assert not hasattr(probe.undocumented, "__road__")


def test_a_nested_target_is_refused_as_not_module_level() -> None:
    """A static reader cannot see a road defined inside a function, so it is not one."""
    before = len(REGISTRY)
    marker = road("frobnicate", example="apps/core/tests/test_roads.py::test_frobnicate")

    def nested() -> None:
        """Documented, and still not a road: it lives inside a function."""

    with pytest.raises(
        ValueError, match=r"a road is a module-level definition: .*<locals>\.nested"
    ):
        marker(nested)
    assert len(REGISTRY) == before
    assert not hasattr(nested, "__road__")


@pytest.mark.parametrize(
    ("job", "example", "names"),
    [
        ("Refuse", "apps/core/exceptions.py::wire_refusal", "job key"),
        ("refuse", "", "example"),
    ],
)
def test_an_illegal_job_or_an_empty_example_is_refused_before_decorating(
    job: str, example: str, names: str
) -> None:
    before = len(REGISTRY)
    with pytest.raises(ValueError, match=names):
        road(job, example=example)
    assert len(REGISTRY) == before


def test_the_marker_imports_no_django() -> None:
    """The quality engine carries the marker without a settings module."""
    probe = (
        "import sys, apps.core.roads; "
        "leaked = sorted(m for m in sys.modules if m.split('.')[0] == 'django'); "
        "assert not leaked, leaked"
    )
    result = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
        [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert roads.__file__ is not None


# --- The door: `manage.py roads` ------------------------------------------------
#
# The scratch trees below are what the census reads (`--root`); imports stay this
# process's, so a Python road planted in a scratch tree is made importable by
# placing its module in `sys.modules` — a real import by name, with no file in
# the checkout.

ROAD_KEYS = {
    "job",
    "partition",
    "carrier",
    "kind",
    "path",
    "line",
    "import",
    "symbol",
    "contract",
    "example",
    "kept_beside",
}


def _door(*args: str, **options: object) -> tuple[int, str, str]:
    """Run the door; answer (exit status, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    try:
        call_command("roads", *args, stdout=out, stderr=err, **options)
    except SystemExit as stop:
        return int(stop.code or 0), out.getvalue(), err.getvalue()
    return 0, out.getvalue(), err.getvalue()


def _plant(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def _probe_module(monkeypatch: pytest.MonkeyPatch, dotted: str, **objects: object) -> None:
    """Make `dotted` importable by name, holding `objects`, for this test only."""
    module = types.ModuleType(dotted)
    for name, obj in objects.items():
        setattr(module, name, obj)
    monkeypatch.setitem(sys.modules, dotted, module)


def _live(job: str) -> Callable[[], None]:
    """A function carrying the attribute the marker sets — without registering it."""

    def frobnicate() -> None:
        """Frobnicate the one way this platform frobnicates."""

    frobnicate.__road__ = {"job": job, "example": "x"}  # type: ignore[attr-defined]  # the marker's attribute
    return frobnicate


PROBE = """
from apps.core.roads import road


@road("frobnicate", example="apps/zzz_probe/services.py::{example}")
def frobnicate():
    \"\"\"Frobnicate the one way this platform frobnicates.\"\"\"
"""


def _product_column(product_roads: int) -> str:
    """The door's `product` column, from `settings.LOCAL_APPS` outside the partition's apps."""
    door = importlib.import_module("apps.core.management.commands.roads")
    installed = {name.removeprefix("apps.") for name in settings.LOCAL_APPS}
    if product_roads:
        return str(product_roads)
    if installed - set(_engine("partition").platform_apps()):
        return "none"
    assert door.TEMPLATE_PRODUCT == "none — this is the template"
    return str(door.TEMPLATE_PRODUCT)


def test_the_door_prints_every_road_this_tree_marks() -> None:
    """The header's counts are the census's, derived here — never typed.

    Every rung that marks a road moves them; a number written into this test
    would be one more file each of those rungs had to edit.
    """
    engine = _engine("roads")
    markers = engine.census(ROOT)
    stands = engine.standing(markers)
    jobs = len({m.job for m in markers})
    platform = sum(1 for m in stands.values() if m.partition == "platform")
    assert jobs >= 1, "a population of zero cannot assert"

    status, out, _ = _door()
    assert status == 0
    header, *lines = out.splitlines()
    column = _product_column(len(stands) - platform)
    assert header.startswith(
        f"roads · {jobs} jobs · {len(stands)} roads (platform {platform} · product {column}) ·"
    )
    assert "unmarked " in header and "(see --explain 84)" in header
    at = next(i for i, line in enumerate(lines) if line.split()[:1] == ["refuse"])
    assert lines[at].split() == ["refuse", "apps.core.exceptions", "platform", "py", "module"]
    assert "`wire_refusal` is the only builder of a body" in lines[at + 1]
    assert lines[at + 2].split()[0] == "example"


def test_one_job_prints_its_block_and_an_unknown_job_prints_the_vocabulary() -> None:
    status, out, _ = _door("refuse")
    assert status == 0
    assert "apps.core.exceptions" in out

    status, out, err = _door("frobnicate")
    assert status == 2
    assert out == ""
    assert "no job 'frobnicate'" in err and "refuse" in err


def test_the_json_document_is_closed() -> None:
    status, out, _ = _door(json=True)
    assert status == 0
    document = json.loads(out)
    assert set(document) == {"schema", "tree", "platform_apps", "roads", "kept", "unmarked"}
    assert document["schema"] == "roads/1"
    assert document["roads"], "a population of zero cannot assert"
    for row in document["roads"]:
        assert set(row) == ROAD_KEYS
    assert set(document["unmarked"]) == {"measured", "reason", "total", "classes"}
    assert document["unmarked"]["total"] == sum(document["unmarked"]["classes"].values())


def test_the_product_column_reads_the_installed_apps_road_never_the_registry() -> None:
    """The door walks no app registry, and a planted product app moves its `product` column.

    Walking the registry is the partition census's discovery-seam shape, and the
    door declares no population of its own; the installed labels are the
    `installed_apps` road's answer as settings holds it.
    """
    door = importlib.import_module("apps.core.management.commands.roads")
    assert door.__file__ is not None
    tree = ast.parse(Path(door.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not {name for name in imported if name.split(".")[:2] == ["django", "apps"]}
    # Both readers: the tolerant walk itself (a vanished file is skipped, so it
    # cannot flake) holds the stronger property — a CLAIMED walker would still
    # pass the census, and the door must not be a walker at all.
    assert door.__name__ not in _engine("partition")._walking_modules()
    assert door.__name__ not in _engine("partition").seam_census()

    stands = _engine("roads").standing(_engine("roads").census(ROOT)).values()
    product_roads = sum(1 for m in stands if m.partition != "platform")
    status, out, _ = _door()
    assert status == 0
    assert f"· product {_product_column(product_roads)}) ·" in out.splitlines()[0]

    with override_settings(LOCAL_APPS=[*settings.LOCAL_APPS, "apps.zzz_probe"]):
        status, out, _ = _door()
        planted = _product_column(product_roads)
    assert status == 0
    assert planted != "none — this is the template"
    assert f"· product {planted}) ·" in out.splitlines()[0]


def test_the_seam_census_skips_a_module_gone_between_its_listing_and_its_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A file the walk listed and could not open is no discovery walk, and no exception.

    Both planted modules call both halves of the walk shape, so the only way the
    vanished one is absent from the answer is that the census skipped it; the one
    that stays proves the walk went on past the skip. The census is driven through
    its `root` seam, the one its own canary uses, over a scratch tree.
    """
    walks = """
        from django.apps import apps
        import importlib.util
        def seam():
            for config in apps.get_app_configs():
                importlib.util.find_spec(f"{config.name}.api")
    """
    _plant(tmp_path, "apps/stays.py", walks)
    _plant(tmp_path, "apps/vanishes.py", walks)
    planted = tmp_path / "apps" / "vanishes.py"
    real_read_text = Path.read_text

    def read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == planted:
            self.unlink()
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", read_text)
    walking = _engine("partition")._walking_modules(root=tmp_path)

    assert not planted.exists(), "the census never opened the plant — this drove nothing"
    assert walking == ["apps.stays"]


def test_an_example_naming_a_missing_symbol_is_exit_2(tmp_path: Path) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="nothing_here"))
    status, _, err = _door(root=str(tmp_path))
    assert status == 2
    assert "apps/zzz_probe/services.py::nothing_here" in err


def test_an_example_that_only_calls_its_symbol_is_exit_2(tmp_path: Path) -> None:
    """A file that calls `print()` does not define `print`: a call is not a definition."""
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    _plant(tmp_path, "x/uses_print.py", 'def report():\n    print("hello")\n')
    text = (tmp_path / "apps/zzz_probe/services.py").read_text(encoding="utf-8")
    (tmp_path / "apps/zzz_probe/services.py").write_text(
        text.replace("apps/zzz_probe/services.py::frobnicate", "x/uses_print.py::print"),
        encoding="utf-8",
    )
    status, _, err = _door(root=str(tmp_path))
    assert status == 2
    assert "x/uses_print.py::print" in err and "found a call at line 2" in err


def _removed(n: int) -> str:
    """The door's one line for `n` examples a product's deleted worked example took with it."""
    return f"worked example removed: {n} road example(s) under apps/example*/ are not on this tree"


def test_a_removed_worked_example_is_one_line_and_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`git rm` leaves the bytecode behind: a directory of only `__pycache__` holds no app."""
    _plant(tmp_path, "apps/example/__pycache__/services.cpython-312.pyc", "")
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    text = (tmp_path / "apps/zzz_probe/services.py").read_text(encoding="utf-8")
    (tmp_path / "apps/zzz_probe/services.py").write_text(
        text.replace("apps/zzz_probe/services.py", "apps/example/tests/test_gone.py"),
        encoding="utf-8",
    )
    _probe_module(monkeypatch, "apps.zzz_probe.services", frobnicate=_live("frobnicate"))
    status, out, err = _door(root=str(tmp_path))
    assert (status, err) == (0, "")
    assert out.count("worked example removed") == 1 and _removed(1) in out
    assert "apps/example/tests/test_gone.py::frobnicate" in out  # the road is still listed


def test_a_worked_example_missing_beside_its_app_is_still_exit_2(tmp_path: Path) -> None:
    """The tree that holds the worked example is held to it: a dangling example there is named."""
    _plant(tmp_path, "apps/example/models.py", "")
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    text = (tmp_path / "apps/zzz_probe/services.py").read_text(encoding="utf-8")
    (tmp_path / "apps/zzz_probe/services.py").write_text(
        text.replace("apps/zzz_probe/services.py", "apps/example/tests/test_gone.py"),
        encoding="utf-8",
    )
    status, out, err = _door(root=str(tmp_path))
    assert status == 2 and "worked example removed" not in out
    assert "apps/example/tests/test_gone.py does not exist" in err


def test_a_dangling_example_outside_the_worked_example_is_exit_2(tmp_path: Path) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    text = (tmp_path / "apps/zzz_probe/services.py").read_text(encoding="utf-8")
    (tmp_path / "apps/zzz_probe/services.py").write_text(
        text.replace("apps/zzz_probe/services.py", "apps/zzz_probe/tests/test_gone.py"),
        encoding="utf-8",
    )
    status, out, err = _door(root=str(tmp_path))
    assert status == 2 and "worked example removed" not in out
    assert "apps/zzz_probe/tests/test_gone.py does not exist" in err


def test_a_product_that_deleted_the_worked_example_lists_every_road_and_says_so(
    tmp_path: Path,
) -> None:
    """This tree with `apps/example*` gone: every road printed, the gone examples counted."""
    is_worked_example = _engine("djb.rituals.divergence").is_worked_example
    listed = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `git`, no shell
        ["git", "ls-files", "-z", "--", "apps", "config", "quality", "scripts", "deploy"]
        + ["frontend/src"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    for rel in listed:
        if rel and not rel.startswith("apps/example") and (ROOT / rel).is_file():
            (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / rel).write_bytes((ROOT / rel).read_bytes())
    markers = _engine("roads").census(tmp_path)
    gone = [
        m
        for m in markers
        if is_worked_example(m.example.partition("::")[0])
        and not (tmp_path / m.example.partition("::")[0]).exists()
    ]
    assert gone, "no road cites the worked example — this case would pass with nothing removed"
    status, out, err = _door(root=str(tmp_path))
    assert (status, err) == (0, "")
    jobs = len(_engine("roads").standing(markers))
    assert out.startswith(f"roads · {jobs} jobs") and _removed(len(gone)) in out


RESOLVER_FILES = {
    "x/m.py": "def caller():\n    helper()\n",
    "x/c.py": (
        "class Other:\n    def method(self):\n        pass\n\n"
        "class Klass:\n    def own(self):\n        pass\n\n"
        "async def later():\n    pass\n"
    ),
    "x/n.py": "def outer():\n    def inner():\n        pass\n",
    "x/s.sh": "run() {\n  helper\n  helper() { :; }\n}\n",
    "x/ok.sh": "helper() {\n  :\n}\ncase_refusal_is_exit_2() {\n  :\n}\n",
}


@pytest.mark.parametrize(
    ("example", "why"),
    [
        ("x/m.py::helper", "helper is not defined there (found a call at line 2)"),
        (
            "x/c.py::Klass.method",
            "not a def directly inside class Klass (found `method` at line 2)",
        ),
        (
            "x/c.py::method",
            "not a module-level def, class or assignment (found `method` at line 2)",
        ),
        ("x/c.py::Missing.own", "there is no module-level class Missing"),
        ("x/n.py::inner", "not a module-level def, class or assignment (found `inner` at line 2)"),
        ("x/s.sh::helper", "not a column-zero `helper() {` definition (found line 2"),
        ("x/ok.sh::absent", "absent is not defined there (found nothing by that name)"),
    ],
)
def test_the_example_resolver_refuses_what_is_not_a_definition(
    tmp_path: Path, example: str, why: str
) -> None:
    for rel, text in RESOLVER_FILES.items():
        _plant(tmp_path, rel, text)
    answer = resolve_example(tmp_path, example)
    assert answer is not None and why in answer, answer


@pytest.mark.parametrize(
    "example",
    [
        "x/c.py::Other.method",
        "x/c.py::Klass.own",
        "x/c.py::Klass",
        "x/c.py::later",
        "x/m.py::caller",
        "x/ok.sh::helper",
        "x/ok.sh::refusal_is_exit_2",
    ],
)
def test_the_example_resolver_accepts_the_four_definition_forms(
    tmp_path: Path, example: str
) -> None:
    for rel, text in RESOLVER_FILES.items():
        _plant(tmp_path, rel, text)
    assert resolve_example(tmp_path, example) is None


def test_an_example_in_a_file_no_marker_carries_is_refused_naming_its_suffix(
    tmp_path: Path,
) -> None:
    """A marker's carriers are `.py` and `.sh`: a shell-shaped definition in a `.md` is not one."""
    _plant(tmp_path, "x/d.md", "foo() {\n  :\n}\n")
    answer = resolve_example(tmp_path, "x/d.md::foo")
    assert answer is not None and "x/d.md is a '.md' file" in answer, answer
    assert "an example is carried by .py, .sh, .ts or .tsx" in answer


#: The face's carrier: a column-zero TypeScript definition (the marker that sits
#: above one is the TS road reader's business) — `mintIntent` is the planted shape
#: the TS road reader was proved on.
TS_CLIENT = (
    "export function mintIntent(): string {\n"
    "    return crypto.randomUUID();\n"
    "}\n"
    "export const ROUTE = 1;\n"
    "const caller = mintIntent();\n"
    "helper(caller);\n"
)


@pytest.mark.parametrize("suffix", [".ts", ".tsx"])
def test_a_typescript_example_resolves_at_its_definition(tmp_path: Path, suffix: str) -> None:
    """The door shows a TS road's example: a definition resolves, a call does not."""
    _plant(tmp_path, f"x/client{suffix}", TS_CLIENT)
    assert resolve_example(tmp_path, f"x/client{suffix}::mintIntent") is None
    assert resolve_example(tmp_path, f"x/client{suffix}::ROUTE") is None
    refused = resolve_example(tmp_path, f"x/client{suffix}::helper")
    assert refused is not None and "not a column-zero definition" in refused, refused
    missing = resolve_example(tmp_path, f"x/client{suffix}::absent")
    assert missing is not None and "found nothing by that name" in missing, missing


def test_a_road_that_does_not_import_is_exit_2(tmp_path: Path) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    status, _, err = _door(root=str(tmp_path))
    assert status == 2
    assert "does not import as apps.zzz_probe.services.frobnicate" in err


def test_a_live_marker_naming_another_job_is_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    _probe_module(monkeypatch, "apps.zzz_probe.services", frobnicate=_live("frobnicate"))
    assert _door(root=str(tmp_path))[0] == 0  # the same tree, agreeing, is printed

    _probe_module(monkeypatch, "apps.zzz_probe.services", frobnicate=_live("defrobnicate"))
    status, _, err = _door(root=str(tmp_path))
    assert status == 2
    assert "'frobnicate'" in err and "'defrobnicate'" in err


def test_an_imported_object_with_no_marker_attribute_is_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    _probe_module(monkeypatch, "apps.zzz_probe.services", frobnicate=lambda: None)
    status, _, err = _door(root=str(tmp_path))
    assert status == 2
    assert "carries no __road__" in err


SHELL = """
#!/usr/bin/env bash
{valve}# road: frobnicate_sh — frobnicate from a shell · example: scripts/{name}.sh::{name}
{name}() {{
  :
}}
"""


def test_two_roads_for_one_job_with_no_valve_is_exit_2(tmp_path: Path) -> None:
    _plant(tmp_path, "scripts/frob_a.sh", SHELL.format(valve="", name="frob_a"))
    _plant(tmp_path, "scripts/frob_b.sh", SHELL.format(valve="", name="frob_b"))
    status, _, err = _door(root=str(tmp_path))
    assert status == 2
    assert "scripts/frob_b.sh" in err and "scripts/frob_a.sh::frob_a" in err


def test_a_valved_second_road_is_printed_as_kept(tmp_path: Path) -> None:
    valve = "# rule-84: our frobnicator predates the platform's and every caller branches on it\n"
    _plant(tmp_path, "scripts/frob_a.sh", SHELL.format(valve="", name="frob_a"))
    _plant(tmp_path, "scripts/frob_b.sh", SHELL.format(valve=valve, name="frob_b"))
    status, out, _ = _door(root=str(tmp_path))
    assert status == 0
    assert "kept  frobnicate_sh  scripts/frob_b.sh:3 beside scripts/frob_a.sh::frob_a" in out

    status, out, _ = _door(root=str(tmp_path), json=True)
    document = json.loads(out)
    assert [row["path"] for row in document["roads"]] == ["scripts/frob_a.sh"]
    assert document["kept"] == [
        {
            "job": "frobnicate_sh",
            "path": "scripts/frob_b.sh",
            "line": 3,
            "reason": "our frobnicator predates the platform's and every caller branches on it",
            "platform_road": "scripts/frob_a.sh::frob_a",
        }
    ]


def test_the_partition_column_is_the_lockfiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    _probe_module(monkeypatch, "apps.zzz_probe.services", frobnicate=_live("frobnicate"))
    _plant(
        tmp_path,
        "apps/core/exceptions.py",
        '''
        """The only builder of a refusal body."""
        import sys

        from apps.core.roads import road

        ROAD = road("refuse", example="apps/core/exceptions.py::wire_refusal")(
            sys.modules[__name__]
        )


        def wire_refusal():
            """Compose."""
        ''',
    )
    status, out, _ = _door(root=str(tmp_path), json=True)
    assert status == 0
    partitions = {row["job"]: row["partition"] for row in json.loads(out)["roads"]}
    assert partitions == {"frobnicate": "product", "refuse": "platform"}

    status, out, _ = _door(root=str(tmp_path))
    assert "(platform 1 · product 1)" in out.splitlines()[0]


def test_a_road_in_an_app_this_world_disabled_is_annotated_not_imported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _plant(tmp_path, "apps/zzz_probe/services.py", PROBE.format(example="frobnicate"))
    # The world's answer, not the variable it reads: this test is about the door.
    monkeypatch.setattr(_engine("worlds"), "disabled_app_labels", lambda: frozenset({"zzz_probe"}))
    status, out, _ = _door(root=str(tmp_path))
    assert status == 0
    assert "(optional app, disabled in this world)" in out


def test_without_rule_84_the_door_says_not_measured() -> None:
    gate = _engine("gate")
    # In place: every engine module holds the one list, so a rebinding would reach none of them.
    saved = gate.RULES[:]
    gate.RULES[:] = [r for r in saved if str(r.get("id")) != "84"]
    try:
        status, out, _ = _door()
    finally:
        gate.RULES[:] = saved
    assert status == 0
    assert out.splitlines()[0].endswith("unmarked: not measured (rule 84 absent)")


# --- The live registry equals the static census ---------------------------------


def _live_name(obj: object) -> str:
    if isinstance(obj, types.ModuleType):
        return obj.__name__
    return f"{getattr(obj, '__module__', '')}.{getattr(obj, '__qualname__', '')}"


def _disagreement(static: set[tuple[str, str | None]], live: set[tuple[str, str]]) -> str:
    """How the census and the registry disagree, in words; empty when they do not."""
    if live == static:
        return ""
    return (
        f"seen by the census and not imported: {sorted(static - live, key=str)}; "
        f"registered at import and not in the files: {sorted(live - static)}"
    )


def test_registry_equals_the_static_census() -> None:
    """Every marker the files show under `apps/` imports, and nothing marks at runtime alone."""
    static = {
        (m.job, m.import_path) for m in _engine("roads").census(ROOT) if m.path.startswith("apps/")
    }
    assert static, "a population of zero cannot assert"
    for _, dotted in static:
        assert dotted is not None
        import_road(dotted)
    live = {(job, _live_name(obj)) for job, obj in REGISTRY if _live_name(obj).startswith("apps.")}
    assert not _disagreement(static, live), _disagreement(static, live)


GUARDED = """
from typing import TYPE_CHECKING

from apps.core.roads import road

if TYPE_CHECKING:

    @road("frobnicate", example="apps/zzz_probe/services.py::frobnicate")
    def frobnicate():
        \"\"\"Frobnicate, for the type checker alone.\"\"\"
"""


def test_a_marker_import_never_defines_is_a_disagreement_the_census_sees(
    tmp_path: Path,
) -> None:
    """The sever plant: a road under `TYPE_CHECKING` is in the files and never in the registry.

    Both halves read the SAME planted source — the census from the file, the
    registry by executing it as the module it names — so the comparison the
    whole-tree test makes is the one that must come out unequal here.
    """
    _plant(tmp_path, "apps/zzz_probe/services.py", GUARDED)
    static = {
        (m.job, m.import_path)
        for m in _engine("roads").census(tmp_path)
        if m.path.startswith("apps/")
    }
    before = len(REGISTRY)
    try:
        module = types.ModuleType("apps.zzz_probe.services")
        source = (tmp_path / "apps/zzz_probe/services.py").read_text()
        exec(compile(source, "<guarded probe>", "exec"), module.__dict__)  # noqa: S102 — the plant above
        live = {(job, _live_name(obj)) for job, obj in REGISTRY[before:]}
    finally:
        del REGISTRY[before:]
    assert static == {("frobnicate", "apps.zzz_probe.services.frobnicate")}, static
    assert live == set(), live
    assert "seen by the census and not imported" in _disagreement(static, live)


# --- The door's `unmarked` is the backlog a product may carry --------------------


def test_unmarked_counts_no_frozen_class_at_zero(tmp_path: Path) -> None:
    """A frozen class at zero has no `ratchets:` line, so the door leaves it out of the backlog.

    The tree holds one road and it is conditional — a `conditional_road`
    finding, and nothing a drawer may record — so the counted backlog is zero
    and the class list is the rule's recorded classes.
    """
    from apps.core.management.commands.roads import unmarked

    gate = _engine("gate")
    rule = next(r for r in gate.RULES if str(r.get("id")) == "84")
    assert gate.is_frozen(rule, "conditional_road"), "the plant below proves nothing unfrozen"
    recorded = rule.get("ratchets") or {}
    assert "conditional_road" not in recorded, "a frozen class at zero has no line"
    _plant(tmp_path, "apps/zzz_probe/services.py", GUARDED)
    found = _engine("checks").road_uniqueness(tmp_path, rule).findings
    assert [f.klass for f in found] == ["conditional_road"], found
    counts = unmarked(tmp_path)
    assert set(counts["classes"]) == {str(k) for k in recorded}, counts
    assert counts["total"] == 0, counts


# --- A declaration-shaped road's example: `path::NAME` on a module-level assignment ---

DECLARED = """
\"\"\"A module whose road is a declaration a door reads.\"\"\"

TAGS = {"zzz": "the probe's own tag"}
LIMIT: int = 3


def reader():
    local_only = 1
    return local_only


class Holder:
    ATTRIBUTE = 2
"""


@pytest.mark.parametrize("example", ["x/k.py::TAGS", "x/k.py::LIMIT"])
def test_the_example_resolver_accepts_a_module_level_assignment(
    tmp_path: Path, example: str
) -> None:
    """`TAGS = …` and `LIMIT: int = …` at module level: the definitions a declaration has."""
    _plant(tmp_path, "x/k.py", DECLARED)
    assert resolve_example(tmp_path, example) is None


@pytest.mark.parametrize(
    ("example", "why"),
    [
        (
            "x/k.py::local_only",
            "not a module-level def, class or assignment (found an assignment at line 8)",
        ),
        (
            "x/k.py::ATTRIBUTE",
            "not a module-level def, class or assignment (found an assignment at line 13)",
        ),
    ],
)
def test_the_example_resolver_refuses_an_assignment_that_is_not_at_module_level(
    tmp_path: Path, example: str, why: str
) -> None:
    """A name bound inside a function or a class is not what import defines on the module."""
    _plant(tmp_path, "x/k.py", DECLARED)
    answer = resolve_example(tmp_path, example)
    assert answer is not None and why in answer, answer


def test_the_door_resolves_a_road_whose_example_is_a_declaration(tmp_path: Path) -> None:
    """The door prints a road whose worked example is a module-level constant, exit 0."""
    _plant(tmp_path, "x/k.py", DECLARED)
    _plant(
        tmp_path,
        "scripts/frob_decl.sh",
        "#!/usr/bin/env bash\n"
        "# road: frobnicate_decl — read the declared tags · example: x/k.py::TAGS\n"
        "frob_decl() {\n  :\n}\n",
    )
    status, out, err = _door(root=str(tmp_path))
    assert status == 0, err
    assert "    example  x/k.py::TAGS" in out


# --- Rule 84's grammar, as `--explain 84` prints it -------------------------------

BESIDE = """
from typing import TYPE_CHECKING

from apps.core.roads import road


@road("frobnicate", example="apps/zzz_probe/services.py::frobnicate")
def frobnicate():
    \"\"\"Frobnicate the one way this platform frobnicates.\"\"\"


if TYPE_CHECKING:

    @road("frobnicate", example="apps/zzz_probe/services.py::frobnicate")
    def frobnicate_for_the_checker():
        \"\"\"Frobnicate, for the type checker alone.\"\"\"
"""


def test_a_conditional_marker_beside_an_unconditional_one_is_conditional_road_only(
    tmp_path: Path,
) -> None:
    """The unconditional road stands; its guarded twin is one `conditional_road`, no second road."""
    rule = next(r for r in _engine("gate").RULES if str(r.get("id")) == "84")
    _plant(tmp_path, "apps/zzz_probe/services.py", BESIDE)
    found = _engine("checks").road_uniqueness(tmp_path, rule).findings
    assert [f.klass for f in found] == ["conditional_road"], found
    grammar = dict(
        line.split(": ", 1)
        for line in _engine("roads").population(ROOT, rule)
        if line.startswith("class ")
    )
    assert "is this class ONLY" in grammar["class conditional_road"], grammar


@pytest.mark.parametrize(
    ("form", "rel", "filled"),
    [
        (
            "PY_DECORATOR_FORM",
            "apps/zzz_probe/services.py",
            '{form}\ndef frobnicate():\n    """Frobnicate the one way."""\n',
        ),
        (
            "PY_MODULE_FORM",
            "apps/zzz_probe/services.py",
            '"""Frobnicate the one way."""\nimport sys\n\n{form}\n',
        ),
        ("TEXT_MARKER_FORM", "scripts/frob.sh", "{form}\nfrobnicate() {{\n  :\n}}\n"),
    ],
)
def test_every_form_explain_prints_is_a_marker_the_census_reads(
    tmp_path: Path, form: str, rel: str, filled: str
) -> None:
    """Each marker form `--explain 84` prints, filled in, is read by the census as one road.

    The printed forms are built from the words the readers match, so a reader
    that changed its words and not its printed form (or the reverse) reds here.
    """
    census = _engine("roads")
    printed = {line.split("`")[1] for line in census.population(ROOT, {}) if "`" in line}
    template = getattr(census, form)
    assert template in printed, (template, printed)
    marker = (
        template.replace("<job>", "frobnicate")
        .replace("<contract>", "frobnicate the one way")
        .replace("<path>::<symbol>", f"{rel}::frobnicate")
    )
    _plant(tmp_path, rel, filled.format(form=marker))
    assert [(m.job, m.path) for m in census.census(tmp_path)] == [("frobnicate", rel)]
