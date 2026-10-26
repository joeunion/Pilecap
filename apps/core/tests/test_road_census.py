"""The road census's grammar, driven over trees the tests build.

`quality/roads.py` is the one static reader of the marker grammar — house rule
84, `manage.py roads` and the fold all read it — so what it counts as a marker,
and what it refuses to read, is pinned here against `tmp_path`, never against
the working tree a concurrent gate's verdict is keyed on.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import pytest

#: Reached through `importlib` for the reason `test_drawer_seam.py` states: a
#: plain import of `quality` from a module under `apps/` drags the engine into
#: mypy's `--strict` graph.
_ROADS = importlib.import_module("quality.roads")

MODULE_ROAD = '''"""register declares a code; wire is the only builder of a body."""

from __future__ import annotations

import sys

from apps.core.roads import road

ROAD = road("refuse", example="apps/core/tests/test_x.py::test_y")(sys.modules[__name__])
'''

#: The valve is assembled rather than typed: a line in this file that OPENED
#: with it would be counted by the standing override census as a real one.
VALVE = "# rule" + "-84: our refusal body predates the platform one and our clients branch on it"

KEPT_ROAD = '''from apps.core.roads import road


VALVE_LINE
@road("refuse", example="apps/acme_orders/api.py::create_order")
def acme_refusal() -> None:
    """Our own refusal body."""


def explain() -> None:
    """Prose that spells the marker is not one.

    @road("refuse", example="apps/acme_orders/services.py::explain")
    """
'''.replace("VALVE_LINE", VALVE)

SHELL_ROADS = (
    """#!/usr/bin/env bash
x=1
"""
    + "\n" * 50
    + """
# road: could_not_look — two bangs are exit 2 and nothing else · example: scripts/tests/t.sh::case_a
gate_refuse() {
    :
}

# road: prose — a comment line that sits above no definition, past the header
x=2
"""
)


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _by(markers: list[Any]) -> dict[tuple[str, str], Any]:
    return {(m.job, m.path): m for m in markers}


def test_both_carriers_are_read_and_prose_is_not(tmp_path: Path) -> None:
    _write(tmp_path, "apps/core/exceptions.py", MODULE_ROAD)
    _write(tmp_path, "apps/acme_orders/services.py", KEPT_ROAD)
    _write(tmp_path, "scripts/gate_refuse.sh", SHELL_ROADS)
    markers = _ROADS.census(tmp_path)
    found = _by(markers)
    assert set(found) == {
        ("refuse", "apps/core/exceptions.py"),
        ("refuse", "apps/acme_orders/services.py"),
        ("could_not_look", "scripts/gate_refuse.sh"),
    }, sorted(found)
    module = found[("refuse", "apps/core/exceptions.py")]
    assert (module.carrier, module.kind, module.import_path, module.symbol) == (
        "py",
        "module",
        "apps.core.exceptions",
        None,
    )
    assert module.contract.startswith("register declares a code")
    shell = found[("could_not_look", "scripts/gate_refuse.sh")]
    assert (shell.carrier, shell.kind, shell.symbol, shell.import_path) == (
        "sh",
        "function",
        "gate_refuse",
        None,
    )
    assert shell.contract == "two bangs are exit 2 and nothing else"
    assert shell.example == "scripts/tests/t.sh::case_a"


def test_the_platform_road_stands_and_a_valved_second_is_kept_beside_it(tmp_path: Path) -> None:
    _write(tmp_path, "apps/core/exceptions.py", MODULE_ROAD)
    _write(tmp_path, "apps/acme_orders/services.py", KEPT_ROAD)
    markers = _ROADS.census(tmp_path)
    first, second = markers
    assert (first.partition, first.kept_beside, first.valve) == ("platform", None, None)
    assert second.partition == "product"
    assert second.kept_beside == "apps.core.exceptions"
    assert second.valve and second.valve.startswith("our refusal body predates")
    assert set(second.as_json()) == {
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


@pytest.mark.parametrize(
    ("rel", "text", "said"),
    [
        (
            "apps/zzz/services.py",
            'from x import road\n\n\n@road("Refuse", example="a::b")\ndef f():\n    """F."""\n',
            "is not one lowercase word",
        ),
        (
            "apps/zzz/services.py",
            'from x import road\n\n\n@road("refuse", example="a::b")\ndef f():\n    pass\n',
            "has no contract",
        ),
        (
            "apps/zzz/services.py",
            'from x import road\n\nJOB = "refuse"\n\n\n'
            '@road(JOB, example="a::b")\ndef f():\n    """F."""\n',
            "is not a string literal",
        ),
        (
            "scripts/x.sh",
            "# road: refuse, with no dash and no example\nf() {\n    :\n}\n",
            "does not read as",
        ),
    ],
)
def test_a_marker_that_cannot_be_read_is_could_not_look(
    tmp_path: Path, rel: str, text: str, said: str
) -> None:
    _write(tmp_path, rel, text)
    with pytest.raises(_ROADS.CensusError) as refused:
        _ROADS.census(tmp_path)
    assert said in str(refused.value) and rel in str(refused.value), str(refused.value)


def test_the_census_reads_files_and_never_the_app_registry() -> None:
    source = (Path(__file__).resolve().parents[3] / "quality" / "roads.py").read_text()
    assert "get_app_configs" not in source and "find_spec" not in source


# --- where a marker sits: every statement block is read ------------------------

#: One marker per place a definition can hide, each naming the statement it
#: sits inside — and the two places a road may stand, which name none.
WHERE = '''from typing import TYPE_CHECKING

from apps.core.roads import road

if TYPE_CHECKING:

    @road("under_if", example="a::b")
    def under_if():
        """Guarded."""

try:

    @road("under_try", example="a::b")
    def under_try():
        """Tried."""

except ImportError:

    @road("under_except", example="a::b")
    def under_except():
        """Handled."""

with open(__file__):

    @road("under_with", example="a::b")
    def under_with():
        """Opened."""

for _ in ():

    @road("under_for", example="a::b")
    def under_for():
        """Looped."""

while False:

    @road("under_while", example="a::b")
    def under_while():
        """Waited."""

match 1:
    case 1:

        @road("under_match", example="a::b")
        def under_match():
            """Matched."""


def factory():
    """Builds on demand."""

    @road("in_a_function", example="a::b")
    def inner():
        """Nested."""

    return inner


class Owner:
    """Owns the frob."""

    @road("on_a_method", example="a::b")
    def frob(self):
        """A method directly inside a module-level class stands."""

    class Inner:
        """A class inside a class."""

        @road("in_a_nested_class", example="a::b")
        def deep(self):
            """Too deep to stand."""


@road("at_module_level", example="a::b")
def top():
    """Stands."""
'''


def test_every_statement_block_is_read_and_names_where_a_marker_sits(tmp_path: Path) -> None:
    _write(tmp_path, "apps/zzz/services.py", WHERE)
    found = {m.job: m for m in _ROADS.census(tmp_path)}
    assert {job: m.enclosure for job, m in found.items()} == {
        "under_if": "`if TYPE_CHECKING` (line 5)",
        "under_try": "`try` (line 11)",
        "under_except": "`try` (line 11)",
        "under_with": "`with open(__file__)` (line 23)",
        "under_for": "`for _ in ()` (line 29)",
        "under_while": "`while False` (line 35)",
        "under_match": "`match 1` (line 41)",
        "in_a_function": "`def factory` (line 49)",
        "on_a_method": None,
        "in_a_nested_class": "`class Inner` (line 66)",
        "at_module_level": None,
    }
    # The import path is the one import would produce, `<locals>` included, so
    # the census and the registry can be compared marker for marker.
    assert found["in_a_function"].import_path == "apps.zzz.services.factory.<locals>.inner"
    assert found["on_a_method"].import_path == "apps.zzz.services.Owner.frob"
    assert found["under_if"].import_path == "apps.zzz.services.under_if"
    assert "enclosure" not in found["under_if"].as_json()


def test_a_module_road_under_a_guard_is_read_and_conditional(tmp_path: Path) -> None:
    guarded = MODULE_ROAD.replace("ROAD = road(", "if True:\n    ROAD = road(")
    _write(tmp_path, "apps/core/exceptions.py", guarded)
    (marker,) = _ROADS.census(tmp_path)
    assert (marker.job, marker.kind, marker.enclosure) == ("refuse", "module", "`if True` (line 9)")


def test_an_unconditional_road_stands_over_a_conditional_one(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "apps/aaa/services.py",
        "from apps.core.roads import road\n\nif True:\n\n"
        '    @road("frob", example="a::b")\n    def early():\n        """Guarded."""\n',
    )
    _write(
        tmp_path,
        "apps/zzz/services.py",
        "from apps.core.roads import road\n\n\n"
        '@road("frob", example="a::b")\ndef late():\n    """Stands."""\n',
    )
    markers = _ROADS.census(tmp_path)
    assert [m.path for m in markers] == ["apps/zzz/services.py", "apps/aaa/services.py"]
    assert _ROADS.standing(markers)["frob"].path == "apps/zzz/services.py"


def test_rule_84_refuses_a_conditional_road_and_names_the_statement(tmp_path: Path) -> None:
    checks = importlib.import_module("quality.checks")
    _write(tmp_path, "apps/zzz/services.py", WHERE)
    result = checks.road_uniqueness(tmp_path, {"id": "84", "ratchets": {}})
    conditional = {f.line: f.msg for f in result.findings if f.klass == "conditional_road"}
    assert len(conditional) == 9, sorted(conditional)
    assert all("a road is unconditional" in msg for msg in conditional.values())
    assert "`if TYPE_CHECKING` (line 5)" in conditional[7]
    assert not [f for f in result.findings if f.klass == "second_road"]


# --- the partition: the apps root is the template's, but for its one drawer ----


@pytest.mark.parametrize(
    ("rel", "partition"),
    [
        ("apps/conftest.py", "platform"),
        ("apps/test_census_markers.py", "platform"),
        ("apps/conftest_local.py", "product"),
        ("apps/core/services/__init__.py", "platform"),
        ("apps/acme_orders/services.py", "product"),
        ("apps/core/local/services.py", "product"),
        ("scripts/local/drives/x.sh", "product"),
        ("scripts/gate_refuse.sh", "platform"),
        ("quality/gate.py", "platform"),
    ],
)
def test_the_partition_reads_the_apps_root_by_its_drawer(rel: str, partition: str) -> None:
    platform = frozenset({"core", "accounts"})
    assert _ROADS.partition_of(rel, platform) == partition


# --- what `--explain 84` prints: the population, derived -----------------------


def test_the_population_names_every_class_the_rule_records(tmp_path: Path) -> None:
    gate = importlib.import_module("quality.gate")
    rule = gate.RULES_BY_ID["84"]
    lines = _ROADS.population(tmp_path, rule)
    text = "\n".join(lines)
    for constant in (*_ROADS.PY_ROOTS, *_ROADS.TEXT_ROOTS, str(_ROADS.HEADER_WINDOW)):
        assert constant in text, constant
    for klass in rule.get("ratchets") or {}:
        (line,) = [one for one in lines if one.startswith(f"class {klass}: ")]
        assert "NO GRAMMAR" not in line, line
    assert "read here:    0 markers" in text


# --- the counted shapes: where the one reason floor lives -----------------------


def test_the_reason_floor_s_home_is_the_road_and_a_copy_is_told_to_import_it(
    tmp_path: Path,
) -> None:
    checks = importlib.import_module("quality.checks")
    home = importlib.import_module("quality.reason_floor")
    root = Path(str(home.__file__)).parents[1]
    assert Path(str(home.__file__)).relative_to(root).as_posix() == checks._REASON_ROAD
    _write(tmp_path, checks._REASON_ROAD, "MIN_REASON = 12\n")
    _write(tmp_path, "quality/runners/frob.py", "MIN_REASON = 12\n")
    result = checks.road_uniqueness(tmp_path, {"id": "84", "ratchets": {}})
    found = [f for f in result.findings if f.klass == "reason_literal"]
    assert [f.path for f in found] == ["quality/runners/frob.py"], found
    assert "import `quality.reason_floor.MIN_REASON`" in found[0].msg


def test_a_link_built_from_the_settings_base_is_counted_and_the_seam_is_not(
    tmp_path: Path,
) -> None:
    checks = importlib.import_module("quality.checks")
    name = checks._HAND_URL
    seam = (
        "from apps.core.roads import road\n\n\n"
        f'@road("{checks._URL_JOB}", example="a::b")\n'
        f'def link():\n    """One link."""\n    return settings.{name}\n'
    )
    _write(tmp_path, "apps/core/links.py", seam)
    _write(tmp_path, "apps/acme/schemas.py", f"URL = settings.{name}\n")
    _write(tmp_path, "apps/acme/tests/test_links.py", f"URL = settings.{name}\n")
    _write(tmp_path, "config/settings/base.py", f"{name} = 'https://x'\n")
    result = checks.road_uniqueness(tmp_path, {"id": "84", "ratchets": {}})
    found = [(f.path, f.line) for f in result.findings if f.klass == "hand_url"]
    assert found == [("apps/acme/schemas.py", 1)], found


def test_the_lifecycle_reason_floor_is_the_valves_floor() -> None:
    """`core.lifecycle.MIN_REASON` is the valve's reason floor, the number and not a copy of it.

    The valve road's floor lives in `quality/reason_floor.py`, stdlib only; the
    lifecycle declaration's floor in `core.lifecycle` was typed beside it with
    the same reasoning. Until core imports the one floor, this pins the two
    equal, so a change to either reds here naming both rather than leaving two
    escape hatches with two widths.
    """
    from apps.core import lifecycle

    floor = importlib.import_module("quality.reason_floor").MIN_REASON
    assert lifecycle.MIN_REASON == floor, (
        f"apps/core/lifecycle.py says {lifecycle.MIN_REASON}, quality/reason_floor.py says {floor}"
    )
