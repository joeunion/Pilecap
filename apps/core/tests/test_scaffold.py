# census: cross-app population=apps/**/*.py for the golden fences every app carries
"""`manage.py scaffold`: the fence grammar, the listing, the extracts and the refusals."""

# does-not-cover: whether a copy builds — `quality/tests/test_golden_copy.py` builds every one.
# does-not-cover: black at 88 — the scaffold formats with the tree's own ruff; black never runs.

# names, never reads: docs/sdk/shapes.md docs/product/architecture.md — the child refusal's sentence names the page (rule 90); the decision page is a scratch product's, under tmp_path  # noqa: E501

from __future__ import annotations

import ast
import io
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands.scaffold import STUBBED
from apps.core.scaffold import anchors, copier
from apps.core.scaffold.arms._common import DROP
from apps.core.scaffold.shapes import ADOPT, FENCE_SHAPES, SHAPES, adopt_verbs
from apps.core.tests.platform_tree import platform_tree
from apps.core.tests.tree_census import source_lines, source_text

ROOT = Path(__file__).resolve().parents[3]
VERBS = adopt_verbs(ROOT)


@pytest.fixture(autouse=True)
def _the_platforms_frozen_families(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cases scaffold onto the platform's tree: no product drawer's family is frozen."""
    from apps.core.api import frozen_families

    monkeypatch.setattr(frozen_families, "FROZEN_FAMILIES", frozen_families.CORE_FAMILIES)


def _scaffold(*argv: str) -> str:
    """`manage.py scaffold <argv>`'s standard output."""
    out = io.StringIO()
    call_command("scaffold", *argv, stdout=out)
    return out.getvalue()


# --- A1 · the grammar ----------------------------------------------------------------------------


def test_a_shape_and_a_name_parse() -> None:
    fence = copier.parse_fence("    # golden: field due_at begin", VERBS)
    assert fence == copier.Fence("begin", ("field.due_at",))
    assert copier.parse_fence("// golden: webhook-in onboarding end", VERBS) == copier.Fence(
        "end", ("webhook-in.onboarding",)
    )
    assert copier.parse_fence("# golden: noun begin", VERBS) == copier.Fence("begin", ("noun",))


@pytest.mark.parametrize(
    "line",
    [
        "# golden: Field begin",
        "# golden: gizmo begin",
        "# golden: field Due begin",
        "# golden: field due_at extra begin",
        "# golden: archive gizmo begin",
        "# golden: begin",
    ],
)
def test_a_capital_an_unregistered_shape_or_a_bad_name_is_a_fence_error(line: str) -> None:
    with pytest.raises(copier.FenceError):
        copier.parse_fence(line, VERBS)


def test_the_verb_list_form_is_unchanged() -> None:
    fence = copier.parse_fence("# golden: version move bulk end", VERBS)
    assert fence == copier.Fence("end", ("adopt.version", "adopt.move", "adopt.bulk"))
    assert copier.parse_fence("# golden: a person's field is personal().", VERBS) is None
    assert copier.parse_fence("// golden: bulk+merge end", VERBS) == copier.Fence(
        "end", ("adopt.bulk+merge",)
    )
    assert copier.parse_fence("{/* golden: face begin */}", VERBS) == copier.Fence(
        "begin", ("face",)
    )
    with pytest.raises(copier.FenceError):
        copier.parse_fence("// golden: bulk+bulk end", VERBS)


def test_every_registered_fence_word_is_no_verb() -> None:
    assert FENCE_SHAPES and not FENCE_SHAPES & set(VERBS)


def test_every_existing_fence_still_matches() -> None:
    read: dict[str, int] = {}
    for path in sorted((ROOT / "apps").rglob("*.py")):
        if copier.SKIP_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(source_lines(path), 1):
            if copier.parse_fence(line, VERBS, f"{rel}:{number}: ") is not None:
                read[rel] = read.get(rel, 0) + 1
    assert any(rel.startswith("apps/example/") for rel in read), read
    assert any(rel.startswith("apps/example_portal/") for rel in read), read


@pytest.mark.parametrize(
    ("line", "fence"),
    [
        ("  // golden: face begin", copier.Fence("begin", ("face",))),
        ("// golden: archive end", copier.Fence("end", ("adopt.archive",))),
        ("// golden: portal begin", copier.Fence("begin", ("portal",))),
        ("// golden: bulk+merge begin", copier.Fence("begin", ("adopt.bulk+merge",))),
        ("  /* golden: bulk begin */", copier.Fence("begin", ("adopt.bulk",))),
        ("/* golden: version end */", copier.Fence("end", ("adopt.version",))),
        ("    {/* golden: face end */}", copier.Fence("end", ("face",))),
    ],
)
def test_every_face_fence_form_matches(line: str, fence: copier.Fence) -> None:
    """The face's comment forms, planted; the live face is read outside the partition."""
    assert copier.parse_fence(line, VERBS) == fence


# --- A3 · the listing ----------------------------------------------------------------------------


def test_list_prints_every_registered_shape_with_its_extract_or_pending() -> None:
    lines = _scaffold("--list").splitlines()
    goldens = copier.index(ROOT)
    for shape in SHAPES:
        mine = [line for line in lines if line.split()[0] == shape.key]
        if shape.key == ADOPT:
            assert [line.split()[1] for line in mine] == list(VERBS)
            for line, verb in zip(mine, VERBS, strict=True):
                assert f"{copier.GOLDENS}/{ADOPT}.{verb}/" in line, line
            continue
        assert len(mine) == 1, (shape.key, mine)
        drawn = [k for k in goldens if k == shape.golden or k.partition(".")[0] == shape.fence]
        if drawn:
            assert f"{copier.GOLDENS}/{drawn[0]}/" in mine[0]
        elif shape.key == "migration":
            assert mine[0].endswith(STUBBED), mine[0]
        else:
            assert mine[0].endswith("golden pending — no fence on this tree"), mine[0]
    assert len(lines) == len(SHAPES) - 1 + len(VERBS)


# --- A4 · the extracts regenerate byte-identical -------------------------------------------------


def test_the_extracts_are_what_the_fences_say() -> None:
    assert copier.drift(ROOT, face=False) == [], (
        "the extracts differ from the fences — run `./scripts/pm_fold.sh --only goldens`"
    )


def test_every_verb_regenerates_its_fences_byte_for_byte() -> None:
    for verb in VERBS:
        assert "regenerates byte-for-byte" in _scaffold(ADOPT, verb, "example", "Widget", "--check")


def test_the_noun_regenerates_its_fences_byte_for_byte() -> None:
    assert "regenerates byte-for-byte" in _scaffold("noun", "example", "Widget", "--check")


def test_the_surface_and_its_role_regenerate_their_fences_byte_for_byte() -> None:
    said = _scaffold("surface", "example_portal", "customer", "--role", "customer", "--check")
    assert "`surface customer` regenerates byte-for-byte" in said


def test_the_role_regenerates_its_fence_byte_for_byte() -> None:
    assert "`role customer` regenerates byte-for-byte" in _scaffold(
        "role", "example_portal", "customer", "--check"
    )


def test_a_roles_kinds_are_read_from_models_py_as_the_registry_derives_them() -> None:
    from django.apps import apps

    from apps.core.authz import kind_of
    from apps.core.scaffold.arms.surface import _kinds_of

    compared = 0
    for config in apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        models = [m for m in config.get_models() if m.__module__ == f"{config.name}.models"]
        live = list(dict.fromkeys(k for m in models if (k := kind_of(m))))
        assert _kinds_of(ROOT, config.label) == live, config.label
        compared += bool(live)
    assert compared, "no installed app has a kind, so the comparison proved nothing"


def test_the_noun_replaces_only_what_newapp_wrote_untouched(tmp_path: Path) -> None:
    from apps.core.scaffold.arms._common import newapp_stubs

    call_command("newapp", "gizmos", directory=str(tmp_path), stdout=io.StringIO())
    written = {
        p.relative_to(tmp_path / "gizmos").as_posix(): p.read_text()
        for p in (tmp_path / "gizmos").rglob("*.py")
    }
    assert written == newapp_stubs("gizmos")


#: The test modules the noun golden carries; every other module of the example's is another's.
NOUN_TESTS = frozenset(
    {
        "test_admin.py",
        "test_api.py",
        "test_mcp.py",
        "test_noun_authz.py",
        "test_services.py",
        "test_doors_over_the_wire.py",
    }
)


def test_the_noun_golden_carries_the_example_tests_no_verb_fence_claims() -> None:
    tests = ROOT / "apps/example/tests"
    keys = {
        p.name: copier.keys_of(source_text(p), VERBS, p.name) for p in sorted(tests.glob("*.py"))
    }
    verbs = {name for name, found in keys.items() if any(k.startswith(f"{ADOPT}.") for k in found)}
    nouns = {name for name, found in keys.items() if "noun" in found}
    extract = copier.index(ROOT)["noun"]
    assert verbs and not verbs & nouns, sorted(verbs & nouns)
    assert nouns == NOUN_TESTS == {f.removeprefix("tests/") for f in extract.files if "/" in f}


def test_every_key_the_noun_golden_polices_names_its_default_roles() -> None:
    """A key no `DEFAULT_ROLES` names falls to the residue, where `defaults_for` disagrees."""
    tree = ast.parse(source_text(ROOT / copier.GOLDENS / "noun/policies.py-tpl"))
    tables = {
        node.target.id: {ast.literal_eval(key) for key in node.value.keys if key is not None}
        for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and isinstance(node.value, ast.Dict)
    }
    assert tables["POLICIES"] and tables["POLICIES"] <= tables["DEFAULT_ROLES"], sorted(
        tables["POLICIES"] - tables["DEFAULT_ROLES"]
    )


# --- A5 · the extracts are a formatter fixed point -----------------------------------------------


def test_the_fences_are_a_fixed_point() -> None:
    extracts = sorted(
        p
        for p in (ROOT / copier.GOLDENS).rglob(f"*.py{copier.SUFFIX}")
        if not anchors.additive(p.relative_to(ROOT / copier.GOLDENS).parts[0])
    )
    assert len(extracts) >= len(VERBS)
    moved = [
        p.relative_to(ROOT).as_posix()
        for p in extracts
        if copier.formatted(source_text(p), ROOT, p.name) != source_text(p)
    ]
    assert moved == []


# --- A6 · the refusals, exit 2 before any write --------------------------------------------------


@pytest.mark.parametrize(
    ("argv", "says", "label"),
    [
        ((ADOPT, "archive", "example", "Gizmo"), "platform app", "example"),
        (("field", "gizmos", "Gizmo", "size:int"), "rule 22", "gizmos"),
        (("field", "gizmos", "Gizmo", "size:int=3"), "nullable fields only", "gizmos"),
        (("field", "gizmos", "Gizmo", "size:float?"), "closed types", "gizmos"),
        (("field", "gizmos", "Gizmo", "size:int?"), "scaffold the noun first", "gizmos"),
        (("filter", "gizmos", "Gizmo", "size=in"), "closed lookups", "gizmos"),
        (("filter", "gizmos", "Gizmo", "size=exact"), "scaffold field first", "gizmos"),
        (("ordering", "gizmos", "Gizmo", "size"), "never a relation", "gizmos"),
        (("verb", "gizmos", "Gizmo", "ping"), "rule 16", "gizmos"),
        (("verb", "gizmos", "Gizmo", "confirm"), "scaffold the noun first", "gizmos"),
        (("event", "gizmos", "Gizmo", "Close"), "no verb", "gizmos"),
        (("enum", "gizmos", "Gizmo", "stage", "OPEN,SHUT"), "boolean", "gizmos"),
        (("enum", "gizmos", "Gizmo", "stage", "OPEN,SHUT,GONE"), "noun first", "gizmos"),
        (("migration", "gizmos", "backfill"), "house rule 22", "gizmos"),
        (("import", "gizmos"), "import takes <app> <Noun>", "gizmos"),
        ((ADOPT, "archive", "../config", "Gizmo"), "no app under apps/", "config"),
        (("workflow", "gizmos", "Gizmo"), "workflow takes <app> <Noun> <process>", "gizmos"),
        (("workflow", "gizmos", "Gizmo", "Review"), "lower-case verb", "gizmos"),
        (("workflow", "gizmos", "Gizmo", "update"), "derived key", "gizmos"),
        (("workflow", "gizmos", "Gizmo", "archive"), "family verb", "gizmos"),
        (("workflow", "gizmos", "Gizmo", "split"), "past tense", "gizmos"),
        (
            ("workflow", "gizmos", "Gizmo", "review", "--schedule", "6h"),
            "the workflow golden is per-row (its run takes GizmoReviewing); a schedule starts a "
            "sweep with no row and no tenant",
            "gizmos",
        ),
        (("webhook-in", "gizmos", "Gizmo"), "webhook-in takes <app> <Noun> <provider>", "gizmos"),
        (("webhook-in", "gizmos", "Gizmo", "Acme"), "rule 16", "gizmos"),
        (("webhook-in", "gizmos", "Gizmo", "acme-pay"), "rule 16", "gizmos"),
        (
            ("webhook-in", "gizmos", "Gizmo", "acme"),
            "`receivers.py` is mounted by nothing",
            "gizmos",
        ),
        (("workflow", "gizmos", "Gizmo", "review"), "noun first", "gizmos"),
        (("workflow", "example", "Widget", "review"), "already has a `workflows.py`", "example"),
        (("stat", "gizmos", "Gizmo"), "stat takes <app> <Noun> <key>", "gizmos"),
        (("stat", "gizmos", "Gizmo", "Total"), "lower snake case", "gizmos"),
        (("stat", "gizmos", "Gizmo", "total"), "noun first", "gizmos"),
        (("stat", "example", "Widget", "total"), "already has `widget_stats`", "example"),
        (("stat", "example", "Widget", "name"), "already has a `name`", "example"),
        (("policy", "gizmos"), "policy takes <app> <Noun>Policy", "gizmos"),
        (("policy", "gizmos", "Gizmo"), "no `<Noun>Policy`", "gizmos"),
        (("policy", "gizmos", "Policy"), "no `<Noun>Policy`", "gizmos"),
        (("policy", "gizmos", "gizmoPolicy"), "no `<Noun>Policy`", "gizmos"),
        (("policy", "gizmos", "GizmoPolicy"), "noun first", "gizmos"),
        (("policy", "example", "WidgetPolicy"), "already declares `WidgetPolicy`", "example"),
        (("search", "gizmos", "Gizmo"), "search takes <app> <Noun> <fields>", "gizmos"),
        (("search", "gizmos", "Gizmo", ""), "no field list", "gizmos"),
        (("search", "gizmos", "Gizmo", "name,,notes"), "no field list", "gizmos"),
        (("search", "gizmos", "Gizmo", "Name"), "no field list", "gizmos"),
        (("search", "gizmos", "Gizmo", "name,name"), "named twice", "gizmos"),
        (("search", "gizmos", "Gizmo", "a,b,c,d,e"), "at most four", "gizmos"),
        (("search", "gizmos", "Gizmo", "name"), "noun first", "gizmos"),
        (("search", "example", "Widget", "owner"), "no text column", "example"),
        (("search", "example", "Widget", "name"), "already declares `search_vector`", "example"),
        (("child", "gizmos", "Gizmo"), "child takes <app> <Parent> <Child>", "gizmos"),
        (("child", "gizmos", "Gizmo", "Lines"), "rule 16", "gizmos"),
        (("child", "gizmos", "Gizmo", "line"), "rule 16", "gizmos"),
        (("child", "gizmos", "Gizmo", "Line"), "scaffold noun gizmos Gizmo", "gizmos"),
        (("child", "example", "Widget", "Entry"), "already declares `WidgetEntry`", "example"),
        (("child", "example", "Widget", "Note"), "already has a `notes`", "example"),
        ((ADOPT, "archive", "gizmo", "Gizmo"), "rule 16", "gizmo"),
        ((ADOPT, "archive", "gizmos", "Gizmos"), "rule 16", "gizmos"),
        ((ADOPT, "archive", "gizmos", "Widget"), "rule 83", "gizmos"),
        ((ADOPT, "archive", "gadgets", "Gadget"), "rule 32", "gadgets"),
        (("shape-nobody-registered",), "no registered shape", "shape-nobody-registered"),
        (
            ("surface", "example_portal", "customer", "--role", "member", "--check"),
            "one surface",
            "x",
        ),
        (("surface", "example_portal", "customer"), "--role <name>", "example_portal"),
        (("role", "example_portal", "customer"), "platform app", "example_portal"),
    ],
)
def test_a_refusal_is_exit_2_names_its_rule_and_writes_nothing(
    argv: tuple[str, ...], says: str, label: str
) -> None:
    from apps.core.tests.tree_census import VANISHER_PREFIX

    # Another xdist worker's tree-census plant comes and goes mid-scan; it is never this write.
    def listing() -> list[str]:
        apps = (ROOT / "apps").iterdir()
        return sorted(p.name for p in apps if not p.name.startswith(VANISHER_PREFIX))

    before = listing()
    with pytest.raises(CommandError) as refused:
        _scaffold(*argv)
    assert refused.value.returncode == 2
    assert says in str(refused.value), str(refused.value)
    assert listing() == before


def test_rule_32s_refusal_names_the_page_and_an_accepted_pair_from_the_callers_words() -> None:
    """The stranger's first guess (`jobs` holding `Job`) is refused with a pair that is accepted."""
    with pytest.raises(CommandError) as refused:
        _scaffold("noun", "jobs", "Job", "--dry-run")
    said = str(refused.value)
    assert refused.value.returncode == 2 and "house rule 32" in said, said
    assert (
        "next: name the app for the collection the Job rows belong to — e.g. "
        "`newapp job_records`, then `roads shape noun job_records Job`; the naming rule is "
        "docs/sdk/the-one-path.md step 2 (`newapp`)."
    ) in said.splitlines(), said
    assert "would migrate apps/job_records/" in _scaffold("noun", "job_records", "Job", "--dry-run")


# --- the noun's length: every golden holds the longest noun the arm admits ------------------------


def test_every_golden_holds_the_longest_noun_inside_the_line_length() -> None:
    from apps.core.scaffold.arms._common import LONGEST_NOUN

    nouns = ("Sprocket" + "a" * (LONGEST_NOUN - 8), "Sprocketassembly")
    goldens = copier.index(ROOT)
    long = [
        line
        for noun in nouns
        for key, golden in sorted(goldens.items())
        if key not in ("portal", copier.FACE) and not anchors.additive(key)
        for line in copier.overlong(
            ROOT, copier.from_golden(ROOT, golden, "inventories", noun), "inventories"
        )
    ]
    assert {len(noun) for noun in nouns} == {LONGEST_NOUN} and long == []


def test_every_road_example_a_copy_carries_resolves_on_the_tree_it_lands_in(
    tmp_path: Path,
) -> None:
    """`roads` vouches every example a copy keeps on a product tree that deleted `apps/example*`."""
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    dangling: list[str] = []
    for key, golden in sorted(copier.index(ROOT).items()):
        if key in ("portal", copier.FACE):
            continue
        if anchors.additive(key):
            files = _inserted(noun, key, lambda line: line)
        else:
            files = copier.from_golden(ROOT, golden, "gizmos", "Gizmo").files
        dangling += _dangling(tmp_path / key, key, files)
    assert dangling == []


def test_no_copy_names_the_worked_example_a_product_may_delete() -> None:
    """A copy renames every spelling of its source app, so nothing in it points at the template."""
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    named: list[str] = []
    for key, golden in sorted(copier.index(ROOT).items()):
        if key in ("portal", copier.FACE):
            continue
        if anchors.additive(key):
            files = _inserted(noun, key, lambda line: line)
        else:
            files = copier.from_golden(ROOT, golden, "gizmos", "Gizmo").files
        named += [
            f"{key}/{rel}:{number}"
            for rel, text in files.items()
            for number, line in enumerate(text.splitlines(), 1)
            if "apps/example" in line or "apps.example" in line
        ]
    assert named == []


def _dangling(product: Path, key: str, files: dict[str, str]) -> list[str]:
    """Every road example in `files`, landed as the gizmos app, that would not resolve there."""
    from apps.core.management.commands.roads import _engine, resolve_example

    is_worked_example = _engine("djb.rituals.divergence").is_worked_example
    for rel, text in files.items():
        (product / "apps/gizmos" / rel).parent.mkdir(parents=True, exist_ok=True)
        (product / "apps/gizmos" / rel).write_text(text)
    dangling: list[str] = []
    for rel, text in files.items():
        for found in copier.EXAMPLE.finditer(text):
            example = f"{found['path']}::{found['symbol']}"
            if is_worked_example(found["path"]):
                dangling.append(f"{key}/{rel}: {example} is in the tree a product may delete")
                continue
            own = found["path"].startswith("apps/gizmos/")
            if why := resolve_example(product if own else ROOT, example):
                dangling.append(f"{key}/{rel}: {why}")
    return dangling


def test_a_road_example_the_copy_does_not_carry_drops_its_marker() -> None:
    """Planted: one carried, one not — the carried one is renamed, the other's marker is dropped."""
    original = (
        '@road("widget_a", example="apps/example/tests/t.py::test_a_widget")\n'
        "def widget_a(): ...\n"
        "@road(\n"
        '    "widget_b",\n'
        '    example="apps/example/tests/t.py::test_b_widget",\n'
        ")\n"
        "def widget_b(): ...\n"
    )
    renamed = original.replace("widget", "gear").replace("apps/example/", "apps/gizmoes/")
    files = {"tests/t.py": "def test_a_gear(\n"}
    assert copier.carried_examples(original, renamed, files, "gizmoes").splitlines() == [
        '@road("gear_a", example="apps/gizmoes/tests/t.py::test_a_gear")',
        "def gear_a(): ...",
        "def gear_b(): ...",
    ]


def test_an_additive_fragment_drops_the_marker_of_an_example_it_does_not_carry() -> None:
    """Planted: the fragment carries one cited test, not the other; only the carried one stays."""
    original = [
        '@road("widget_a", example="apps/example/tests/t.py::test_a_widget")',
        "def widget_a(): ...",
        '@road("widget_b", example="apps/example/tests/t.py::test_b_widget")',
        "def widget_b(): ...",
    ]
    moved = [
        line.replace("widget", "gear").replace("apps/example/", "apps/gizmos/") for line in original
    ]
    read = {"api.py": [anchors.Piece(anchors.Anchor((), "end"), original)]}
    found = {
        "api.py": [anchors.Piece(anchors.Anchor((), "end"), moved)],
        "tests/t.py": [anchors.Piece(anchors.Anchor((), "end"), ["def test_a_gear(): ..."])],
    }
    read["tests/t.py"] = [anchors.Piece(anchors.Anchor((), "end"), ["def test_a_widget(): ..."])]
    anchors.carried(read, found, {}, "gizmos")
    assert found["api.py"][0].lines == [
        '@road("gear_a", example="apps/gizmos/tests/t.py::test_a_gear")',
        "def gear_a(): ...",
        "def gear_b(): ...",
    ]


def test_a_copy_into_the_worked_app_keeps_every_marker_as_written() -> None:
    """The template's own copy cites its own tests: nothing is dropped where the example lives."""
    original = '@road("widget_b", example="apps/example/tests/t.py::test_b_widget")\ndef b(): ...\n'
    assert copier.carried_examples(original, original, {}, "example") == original


def test_a_noun_past_the_longest_is_refused_naming_the_line() -> None:
    with pytest.raises(CommandError) as refused:
        _scaffold("noun", "inventories", "Sprocketassemblyline")
    assert refused.value.returncode == 2
    assert "E501" in str(refused.value) and "apps/inventories/" in str(refused.value)


# --- the additive shapes: fragments re-inserted at their anchors ---------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ("field", "example", "Widget", "due_at:datetime?"),
        ("filter", "example", "Widget", "name=icontains"),
        ("ordering", "example", "Widget", "due_at"),
        ("verb", "example", "Widget", "touch"),
        ("event", "example", "Widget", "touch"),
        ("enum", "example", "Widget", "status", "DRAFT,ACTIVE,RETIRED"),
    ],
)
def test_an_additive_shape_reinserts_its_fences_line_for_line(argv: tuple[str, ...]) -> None:
    assert "re-inserts line-for-line" in _scaffold(*argv, "--check")


@pytest.mark.parametrize(
    "argv",
    [
        ("import", "example", "Widget"),
        ("stat", "example", "Widget", "count"),
        ("workflow", "example", "Widget", "onboard"),
        ("policy", "example", "WidgetPolicy"),
        ("search", "example", "Widget", "name,notes"),
        ("child", "example", "Widget", "Entry"),
        ("webhook-in", "example", "Widget", "onboarding"),
    ],
)
def test_a_process_shape_is_a_no_op_check_on_the_template(argv: tuple[str, ...]) -> None:
    said = _scaffold(*argv, "--check")
    assert "regenerates byte-for-byte" in said or "re-inserts line-for-line" in said, said


def _inserted(
    files: dict[str, str], key: str | copier.Golden, lines: Callable[[str], str]
) -> dict[str, str]:
    """`files` with the extract `key`'s lines put in, renamed for `gizmos`/`Gizmo`."""
    from apps.core.management.commands.scaffold import Command
    from apps.core.scaffold.arms.webhook_in import ready_registered

    golden = key if isinstance(key, copier.Golden) else copier.index(ROOT)[key]
    moves = copier.relocations(golden.app, "gizmos", "Gizmo")
    out = dict(files)
    fragments = [rel for rel in golden.files if rel != anchors.APP_CONFIG]
    if anchors.APP_CONFIG in golden.files:
        method = "".join(
            Command.renamed(lines(line), moves) + "\n"
            for line in source_text(ROOT / golden.path(anchors.APP_CONFIG)).splitlines()
        )
        out[anchors.APP_CONFIG] = ready_registered(out.get(anchors.APP_CONFIG, _CONFIG), method)[0]
    reads = {rel: anchors.read(source_text(ROOT / golden.path(rel))) for rel in fragments}
    found = {rel: anchors.renamed(read, (), moves) for rel, read in reads.items()}
    for pieces in found.values():
        for piece in pieces:
            said = [copier.rename(lines(line), moves, {}) for line in piece.lines]
            piece.lines = [one for line in said for one in line.split("\n") if one != DROP]
    anchors.carried(reads, found, files, "gizmos")
    for rel, pieces in found.items():
        out[rel], landed = anchors.insert(out.get(rel, ""), pieces)
        ast.parse(out[rel])
        assert len(landed) == len(pieces), rel
    return out


@pytest.mark.parametrize(
    ("kind", "lookup"),
    [
        ("str", "icontains"),
        ("text", "exact"),
        ("int", "gte"),
        ("bool", "exact"),
        ("date", "lte"),
        ("decimal", "gte"),
        ("uuid", "exact"),
        ("datetime", "lte"),
    ],
)
def test_a_field_and_its_filter_land_in_a_copied_noun_and_parse(kind: str, lookup: str) -> None:
    from apps.core.scaffold.arms._common import FIELD_TYPES
    from apps.core.scaffold.arms.field import field_lines
    from apps.core.scaffold.arms.filter import filter_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    fielded = _inserted(
        noun, "field.due_at", lambda line: field_lines(line, "size", FIELD_TYPES[kind])
    )
    filtered = _inserted(
        fielded, "filter.name", lambda line: filter_lines(line, "size", lookup, kind)
    )
    assert "size" in fielded["models.py"] and 'FilterLookup(q="size' in filtered["schemas.py"]
    ordered = _inserted(filtered, "ordering.due_at", lambda line: line.replace("due_at", "size"))
    assert 'ORDERING += ("size",)' in ordered["api.py"]


#: Nouns past the six letters an anchor line used to hold, the four inflections and the longest.
LENGTHS = ("Gadget", "Spindle", "Sprocket", "Flywheelrim", "Company", "Category", "Box", "Batch")


def _landed(files: dict[str, str], key: str, lines: Callable[[str], str], noun: str) -> None:
    """`files` with the extract `key` put in for `noun` and tidied, as the arm writes it."""
    golden = copier.index(ROOT)[key]
    moves = copier.relocations(golden.app, "inventories", noun)
    reads = {rel: anchors.read(source_text(ROOT / golden.path(rel))) for rel in golden.files}
    found = {rel: anchors.renamed(read, (), moves) for rel, read in reads.items()}
    for pieces in found.values():
        for piece in pieces:
            said = [copier.rename(lines(line), moves, {}) for line in piece.lines]
            piece.lines = [one for line in said for one in line.split("\n") if one != DROP]
    anchors.carried(reads, found, files, "inventories")
    for rel, pieces in found.items():
        text, _ = anchors.insert(files[rel], pieces)
        files[rel] = copier.tidied(text, ROOT, rel, "inventories")


@pytest.mark.parametrize("noun", [*LENGTHS, "Sprocketassembly"])
def test_every_additive_shape_lands_in_a_noun_of_any_admitted_length(noun: str) -> None:
    from apps.core.scaffold.arms._common import FIELD_TYPES, LONGEST_NOUN
    from apps.core.scaffold.arms.enum import enum_lines
    from apps.core.scaffold.arms.field import field_lines
    from apps.core.scaffold.arms.filter import filter_lines
    from apps.core.scaffold.arms.verb import verb_lines

    assert len(noun) <= LONGEST_NOUN
    copy = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "inventories", noun)
    files = copy.files
    _landed(
        files, "field.due_at", lambda line: field_lines(line, "color", FIELD_TYPES["str"]), noun
    )
    _landed(files, "filter.name", lambda line: filter_lines(line, "color", "exact", "str"), noun)
    _landed(files, "ordering.due_at", lambda line: line.replace("due_at", "color"), noun)
    _landed(files, "verb.touch", lambda line: verb_lines(line, "close"), noun)
    _landed(files, "enum.status", lambda line: enum_lines(line, "stage", ("OPEN", "SHUT")), noun)
    assert copier.overlong(ROOT, copy, "inventories") == []
    assert f"def close_{copier.snake(noun)}(" in files["services.py"]


@pytest.mark.parametrize(
    ("noun", "plural"),
    [("Company", "companies"), ("Category", "categories"), ("Box", "boxes"), ("Batch", "batches")],
)
def test_the_noun_copy_says_every_plural_as_the_platform_does(noun: str, plural: str) -> None:
    from apps.core.verbs import plural as platform_plural

    assert platform_plural(noun.lower()) == plural
    files = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "inventories", noun).files
    text = "".join(files.values())
    assert f'name="list_{plural}"' in files["mcp.py"]
    assert f"{noun.lower()}s" not in text.lower()


# --- rule 91 over a write: a new tail is a line to delete, never a floor --------------------------


def test_a_write_that_grows_a_class_says_delete_and_records_no_floor() -> None:
    from apps.core.scaffold import floors

    said = floors.said("gizmos", {"docstring-tail": 300, "block-tail": 40}, {"docstring-tail": 307})
    assert said == [
        "rule 91: apps/gizmos gained 7 docstring-tail line(s) — a new tail is judged at zero "
        "and no floor is recorded for it (`inflow: refused`): delete them"
    ]
    assert not hasattr(floors, "moved")


def test_a_write_that_adds_no_tail_says_nothing() -> None:
    from apps.core.scaffold import floors

    assert floors.said("gizmos", {"narrative": 2}, {"narrative": 1}) == []
    assert floors.said("gizmos", {}, {}) == []


def test_a_field_on_a_duplicable_noun_joins_its_resets_and_a_plain_noun_is_left() -> None:
    from apps.core.scaffold.arms._common import with_reset

    example = source_text(ROOT / "apps/example/models.py")
    reset = with_reset(example, "color")
    assert reset is not None
    text, line = reset
    block = text[text.index("resets=(") :].split("),")[0]
    assert block.rstrip().endswith('"color",') and text.splitlines()[line - 1].strip() == '"color",'
    assert with_reset(text, "color") is None
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    assert with_reset(noun["models.py"], "color") is None


KINDS_MODELS = """
from apps.core.models import OrgScopedModel
from pilecap import Archivable
from django.db import models


class Crate(OrgScopedModel):
    pass


class Lid(OrgScopedModel):
    authz_kind_of = "crate"
    crate = models.ForeignKey(Crate, on_delete=models.CASCADE)


class Label(OrgScopedModel):
    authz_kind_of = "pallet"
    pallet = models.ForeignKey("shipping.Pallet", on_delete=models.CASCADE)


class Strap(OrgScopedModel):
    authz_kind = "crate"


class Seal(Archivable):
    pass
"""


def test_the_role_reads_kinds_from_models_py_and_says_its_holes_in_its_foot() -> None:
    from apps.core.scaffold.arms.surface import KINDS_READ, _kinds_in

    assert _kinds_in(KINDS_MODELS) == ["crate"]
    for hole in ("another module", "another app", "a base other than", "give it once"):
        assert hole in KINDS_READ


def test_the_scaffold_refuses_a_tree_with_no_quality_before_anything(
    tmp_path: Path, settings: Any
) -> None:
    (tmp_path / "apps").mkdir()
    settings.BASE_DIR = tmp_path
    with pytest.raises(CommandError) as refused:
        _scaffold("noun", "gizmos", "Gizmo")
    assert refused.value.returncode == 2 and "source checkout" in str(refused.value)
    assert [p.name for p in tmp_path.iterdir()] == ["apps"]


def _product(tmp_path: Path) -> Path:
    """The platform's tree through links, declaring a namespace in its own `quality/local/`."""
    return platform_tree(tmp_path, "zzzk6r")


def test_the_scratch_tree_carries_no_product_app_the_checkout_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Planted: `example` read as a product's app is left out of the tree a case scaffolds into."""
    import quality.partition

    platform = tuple(label for label in quality.partition.platform_apps() if label != "example")
    monkeypatch.setattr(quality.partition, "platform_apps", lambda: platform)
    apps_dir = platform_tree(tmp_path, None) / "apps"
    assert not (apps_dir / "example").exists()
    assert (apps_dir / "core").is_symlink() and (apps_dir / "example_portal").is_symlink()
    assert not (apps_dir.parent / "quality/local/rules.yaml").exists()


def test_a_product_noun_plans_its_families_into_the_drawer_never_the_core(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = _product(tmp_path)
    planned = _scaffold("noun", "gizmoes", "Gear", "--dry-run")
    assert "would append quality/local/frozen_families.yaml:1 gears" in planned
    assert "frozen_families.py" not in planned


def test_a_product_noun_whose_names_a_plant_carries_is_refused_before_any_write(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = platform_tree(tmp_path / "template", None)
    assert "plant collision: the copy would serve" in _scaffold(
        "noun", "inventories", "Doodad", "--dry-run"
    )
    settings.BASE_DIR = _product(tmp_path)
    with pytest.raises(CommandError) as refused:
        _scaffold("noun", "inventories", "Doodad", "--dry-run")
    assert refused.value.returncode == 2
    assert "doodad" in str(refused.value) and "quality/canary/" in str(refused.value)


def _writable_product(tmp_path: Path) -> Path:
    """`_product` with its own `apps/` and `quality/budgets.yaml`, so a noun may be written."""
    root = _product(tmp_path)
    for rel in ("quality/budgets.yaml", "apps/conftest_local.py"):
        if (root / rel).is_symlink():
            (root / rel).unlink()
            (root / rel).write_text((ROOT / rel).read_text())
    return root


def _written(root: Path) -> dict[str, str]:
    """Every file a noun's write or removal may touch, by path, with its text."""
    owned = [root / "apps/gizmoes", root / "quality/local", root / "apps/conftest_local.py"]
    found = {p for top in owned if top.exists() for p in [top, *top.rglob("*")] if p.is_file()}
    found.add(root / "quality/budgets.yaml")
    return {p.relative_to(root).as_posix(): p.read_text() for p in sorted(found)}


def test_a_noun_rewrites_its_apps_map_row_with_the_doors_it_wrote(
    tmp_path: Path, settings: Any
) -> None:
    """`scaffold noun` prints the derived block it rewrote; the hook's derived leg exits 0."""
    from apps.core.tests.test_newapp import derived_blocks_check, own_architecture

    settings.BASE_DIR = root = own_architecture(_writable_product(tmp_path))
    said = _scaffold("noun", "gizmoes", "Gear").splitlines()
    assert (
        "wrote: docs/product/architecture.md derived block 'app-map' — commit it with the app"
        in said
    )
    row = "| `gizmoes` | `core`, `accounts`, `events` | `api.py` · `mcp.py` | product |"
    assert row in (root / "docs/product/architecture.md").read_text().splitlines()
    hook = derived_blocks_check(root)
    assert hook.returncode == 0, hook.stdout + hook.stderr


def test_a_dry_run_removal_plans_every_line_and_writes_nothing(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = root = _writable_product(tmp_path)
    _scaffold("noun", "gizmoes", "Gear")
    before = _written(root)
    planned = _scaffold("noun", "gizmoes", "Gear", "--remove", "--dry-run").splitlines()
    assert _written(root) == before
    assert planned and all(line.startswith("would ") for line in planned)
    assert "would remove apps/gizmoes/models.py" in planned
    assert "would remove apps/gizmoes/ — the copy made it" in planned
    assert "would undo frozen family: quality/local/frozen_families.yaml -= gears" in planned
    _scaffold("noun", "gizmoes", "Gear", "--remove")
    assert not (root / "apps/gizmoes").exists()


def test_a_noun_plans_its_first_migration_and_its_baseline() -> None:
    planned = _scaffold("noun", "inventories", "Gear", "--dry-run").splitlines()
    assert "would migrate apps/inventories/migrations/0001_initial.py" in planned
    assert (
        "would write apps/inventories/tests/gear_authz_baseline.json: the first run of "
        "tests/test_noun_authz.py"
    ) in planned


def _tracked_product(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """The tracked tree copied whole, namespaced, `.env` beside it; the env its commands run in."""
    if shutil.which("tar") is None:
        pytest.skip("no tar on PATH — the tracked tree is copied with it")
    root = tmp_path / "tree"
    root.mkdir()
    copied = subprocess.run(  # noqa: S603 — `bash -c` over a pipeline this test writes; no caller input
        ["bash", "-c", f"git ls-files -z | tar --null -T - -cf - | tar -xf - -C {str(root)!r}"],  # noqa: S607 — `bash` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert copied.returncode == 0, copied.stderr
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", root / ".env")
    (root / "quality/local").mkdir(parents=True, exist_ok=True)
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: zzzk6a\n")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_NAME": f"djb_scaffold_{secrets.token_hex(3)}",
        "DATABASE_URL": "",
    }
    return root, env


def test_a_product_noun_lands_migrated_with_its_baseline_and_leaves_none_on_removal(
    tmp_path: Path,
) -> None:
    root, env = _tracked_product(tmp_path)

    def run(*argv: str) -> str:
        done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, "manage.py", *argv], cwd=root, env=env, capture_output=True, text=True
        )
        assert done.returncode == 0, (argv, done.stdout + done.stderr)
        return done.stdout

    run("newapp", "gizmoes")
    said = run("scaffold", "noun", "gizmoes", "Gear").splitlines()
    assert "migration: apps/gizmoes/migrations/0001_initial.py" in said
    assert (
        "baseline written: apps/gizmoes/tests/gear_authz_baseline.json — read it, commit it; "
        "a later change in a role's answer is a finding here"
    ) in said
    model = (root / "apps/gizmoes/models.py").read_text().splitlines()
    at = next(n for n, line in enumerate(model, 1) if line.startswith("class Gear("))
    assert said[-1] == f"next: edit apps/gizmoes/models.py:{at}; ./scripts/feature.sh gizmoes"
    run("makemigrations", "--check", "--dry-run", "gizmoes")
    removed = run("scaffold", "noun", "gizmoes", "Gear", "--remove").splitlines()
    for made in ("migrations/0001_initial.py", "tests/gear_authz_baseline.json"):
        assert f"removed apps/gizmoes/{made}" in removed
        assert not (root / "apps/gizmoes" / made).exists()


def test_a_filter_the_noun_already_holds_is_refused_naming_it_before_any_write(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = root = _writable_product(tmp_path)
    _scaffold("noun", "gizmoes", "Gear")
    before = _written(root)
    with pytest.raises(CommandError) as refused:
        _scaffold("filter", "gizmoes", "Gear", "name=exact")
    assert refused.value.returncode == 2
    assert "`GearFilter` already filters `name` (apps/gizmoes/schemas.py:" in str(refused.value)
    assert _written(root) == before


def test_a_check_of_a_filter_the_noun_already_holds_says_its_state(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = root = _writable_product(tmp_path)
    _scaffold("noun", "gizmoes", "Gear")
    before = _written(root)
    other = _scaffold("filter", "gizmoes", "Gear", "name=exact", "--check").splitlines()
    same = _scaffold("filter", "gizmoes", "Gear", "name=icontains", "--check").splitlines()
    held = (
        "apps/gizmoes: `GearFilter` already filters `name` by `icontains` \\(schemas\\.py:\\d+\\)"
    )
    assert re.fullmatch(held + r", not `exact` — every fragment in place\.", other[-1]), other
    assert re.fullmatch(held + r" — every fragment in place\.", same[-1]), same
    assert _written(root) == before
    mcp = root / "apps/gizmoes/mcp.py"
    mcp.write_text(mcp.read_text().replace("filters.name = name", "filters.name = None"))
    with pytest.raises(CommandError) as edited:
        _scaffold("filter", "gizmoes", "Gear", "name=icontains", "--check")
    assert edited.value.returncode == 1
    assert "apps/gizmoes/mcp.py lacks `filters.name = name`" in str(edited.value)


def test_a_check_of_a_filter_holding_an_undeclared_lookup_is_refused_naming_it(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = root = _writable_product(tmp_path)
    _scaffold("noun", "gizmoes", "Gear")
    schemas = root / "apps/gizmoes/schemas.py"
    schemas.write_text(schemas.read_text().replace('"name__icontains"', '"name__istartswith"'))
    before = _written(root)
    with pytest.raises(CommandError) as refused:
        _scaffold("filter", "gizmoes", "Gear", "name=icontains", "--check")
    assert refused.value.returncode == 2
    assert re.fullmatch(
        r"`GearFilter` filters `name` by `istartswith` \(apps/gizmoes/schemas\.py:\d+\), "
        r"a lookup the scaffold does not declare — it declares exact icontains gte lte\.",
        str(refused.value),
    ), str(refused.value)
    assert _written(root) == before


def test_an_adoption_onto_a_held_noun_is_refused_naming_both_roads(
    tmp_path: Path, settings: Any
) -> None:
    settings.BASE_DIR = root = _writable_product(tmp_path)
    _scaffold("noun", "gizmoes", "Gear")
    before = _written(root)
    with pytest.raises(CommandError) as refused:
        _scaffold("adopt", "duplicate", "gizmoes", "Gear")
    assert refused.value.returncode == 2
    models = (root / "apps/gizmoes/models.py").read_text().splitlines()
    line = next(n for n, text in enumerate(models, 1) if text.startswith("class Gear("))
    assert str(refused.value) == (
        f"apps/gizmoes/models.py:{line} already holds `Gear` — `adopt duplicate` copies a whole "
        "noun into a fresh `newapp gizmoes`; the noun `scaffold noun` wrote carries archive, "
        "version and history already, `scaffold verb gizmoes Gear <verb>` adds a plain verb to "
        "it, and a family verb is adopted by hand from its recipe "
        "(docs/sdk/the-developers-hand.md § `adopt` vs `verb`), its worked pattern read off the "
        "`adopt duplicate` copy in a fresh app."
    )
    assert _written(root) == before


def test_an_adoption_over_newapp_retires_its_parity_stub_and_its_removal_restores_it(
    tmp_path: Path, settings: Any
) -> None:
    from apps.core.scaffold.arms._common import DOOR_PARITY, PARITY_STUB, newapp_stubs

    settings.BASE_DIR = root = _writable_product(tmp_path)
    stubs = newapp_stubs("gizmoes")
    for rel, text in stubs.items():
        (root / "apps/gizmoes" / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / "apps/gizmoes" / rel).write_text(text)
    stub = root / "apps/gizmoes" / PARITY_STUB

    said = _scaffold("adopt", "archive", "gizmoes", "Gear").splitlines()
    retired = f"removed apps/gizmoes/{PARITY_STUB} — newapp's parity stub; the copy claims "
    assert retired + "the pair in its own module" in said
    assert not stub.exists()
    claim = f"{DOOR_PARITY[1]} = ("
    assert claim in (root / "apps/gizmoes/tests/test_golden_verbs_parity.py").read_text()
    assert f"{DOOR_PARITY[0]} += 1" in "\n".join(said)

    _scaffold("adopt", "archive", "gizmoes", "Gear", "--remove")
    assert stub.read_text() == stubs[PARITY_STUB]
    assert not (root / "apps/gizmoes/tests/test_golden_verbs_parity.py").exists()


def test_an_additive_shape_has_no_removal_road_and_says_so() -> None:
    with pytest.raises(CommandError) as refused:
        _scaffold("filter", "inventories", "Gear", "color=exact", "--remove")
    assert refused.value.returncode == 2 and "remove by hand" in str(refused.value)


# --- the data migration: a stub, its text a fixed point ------------------------------------------

EMPTY = """# Generated by Django 5.2 on 2026-10-12 12:00

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("gizmos", "0001_initial"),
    ]

    operations = []
"""


def test_the_data_migration_stub_pairs_forward_with_reverse() -> None:
    from apps.core.scaffold.arms.migration import data_migration

    stub = data_migration(EMPTY)
    tree = ast.parse(stub)
    assert [n.name for n in tree.body if isinstance(n, ast.FunctionDef)] == ["forward", "reverse"]
    assert "migrations.RunPython(forward, reverse)," in stub
    assert copier.formatted(stub, ROOT, "migrations/0002_backfill.py") == stub


# --- the verb: its word, its past tense, its fragments in a copied noun --------------------------


@pytest.mark.parametrize(
    ("verb", "past"),
    [
        ("touch", "touched"),
        ("close", "closed"),
        ("apply", "applied"),
        ("replay", "replayed"),
        ("dead_letter", "dead_lettered"),
        ("submit", "submitted"),
        ("send", "sent"),
        ("set", "set"),
        ("pick_up", "picked_up"),
        ("drop_off", "dropped_off"),
        ("set_up", "set_up"),
        ("lend", "lent"),
        ("build", "built"),
        ("pay", "paid"),
        ("lend_out", "lent_out"),
    ],
)
def test_a_verb_says_its_event_in_the_past_tense(verb: str, past: str) -> None:
    from apps.core.scaffold.arms._common import has_a_spelled_past, past_tense

    assert past_tense(verb) == past
    assert has_a_spelled_past(verb)


def test_a_verb_adopts_the_line_an_event_of_the_same_verb_wrote() -> None:
    """DRIVE-3 journal 10: `scaffold event` then `scaffold verb` refused its own line."""
    from apps.core.scaffold.arms.verb import adopts_event, event_line

    wrote = event_line("seeds", "Packet", "lent")
    assert wrote == 'PACKET_LENT = "seeds.packet.lent"'
    events = f'{wrote}\nPACKET_ARCHIVED = "seeds.packet.archived"\n'
    assert adopts_event(events, "seeds", "Packet", "lent", "verb") is True
    assert adopts_event("", "seeds", "Packet", "lent", "verb") is False
    with pytest.raises(CommandError, match="already says"):
        adopts_event(events, "seeds", "Packet", "lent", "event")
    renamed = 'PACKET_LOANED = "seeds.packet.lent"\n'
    with pytest.raises(CommandError, match="under another name than `PACKET_LENT`"):
        adopts_event(renamed, "seeds", "Packet", "lent", "verb")


def test_the_event_shape_lists_the_one_module_it_writes() -> None:
    (line,) = [ln for ln in _scaffold("--list").splitlines() if ln.split()[0] == "event"]
    assert "verb.touch/ (its events.py alone" in line, line


def test_a_verb_lands_in_a_copied_noun_as_one_route_and_parses() -> None:
    from apps.core.scaffold.arms.verb import verb_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    done = _inserted(noun, "verb.touch", lambda line: verb_lines(line, "close"))
    assert 'GIZMO_CLOSED = "gizmos.gizmo.closed"' in done["events.py"]
    assert "def close_gizmo(" in done["services.py"]
    route = done["api.py"].index('url_name="gizmo-close"')
    assert done["api.py"].index("def close_gizmo_route(") > route
    assert '@server.tool(name="close_gizmo"' in done["mcp.py"]


def test_a_stat_lands_in_a_copied_noun_under_its_measure_and_parses() -> None:
    from apps.core.scaffold.arms.stat import stat_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    done = _inserted(noun, "stat.count", lambda line: stat_lines(line, "total"))
    assert "total: MeasuredOut" in done["schemas.py"] and "count:" not in done["schemas.py"]
    assert "total=MeasuredOut(" in done["api.py"] and 'formula="live + archived"' in done["api.py"]
    assert done["api.py"].index("def gizmo_stats(") < done["api.py"].index("def gizmo_stats_route(")
    assert '@server.tool(name="get_gizmo_stats"' in done["mcp.py"]
    assert 'STATS_KEYS = frozenset({"total"})' in done["tests/test_doors_over_the_wire.py"]


@pytest.mark.parametrize(
    ("process", "gerund", "past"),
    [
        ("onboard", "onboarding", "onboarded"),
        ("review", "reviewing", "reviewed"),
        ("approve", "approving", "approved"),
        ("submit", "submitting", "submitted"),
        ("verify", "verifying", "verified"),
    ],
)
def test_a_process_says_its_run_in_the_gerund_and_its_mark_in_the_past(
    process: str, gerund: str, past: str
) -> None:
    from apps.core.scaffold.arms._common import past_tense
    from apps.core.scaffold.arms.workflow import gerund_of

    assert (gerund_of(process), past_tense(process)) == (gerund, past)


def test_a_workflow_lands_in_a_copied_noun_under_its_process_and_parses() -> None:
    from apps.core.scaffold.arms.workflow import workflow_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    done = _inserted(
        noun, "workflow.onboard", lambda line: workflow_lines(line, "review", "gizmos")
    )
    added = [
        line
        for rel, text in done.items()
        for line in text.splitlines()
        if line not in noun.get(rel, "").splitlines()
    ]
    assert [line for line in added if "onboard" in line.lower()] == []
    assert '@workflow.defn(name="GizmoReviewingWorkflow")' in done["workflows.py"]
    listed = done["workflows.py"].partition("WORKFLOWS: list[type] = [")[2].partition("]")[0]
    assert listed.split() == ["GizmoReviewingWorkflow,"], listed
    assert '@activity.defn(name="mark_gizmo_reviewed"' in done["activities.py"]
    assert "class GizmoReviewing:" in done["types.py"]
    assert "    reviewed_at = models.DateTimeField(" in done["models.py"]
    assert 'GIZMO_REVIEWED = "gizmos.gizmo.reviewed"' in done["events.py"]
    assert "def mark_gizmo_reviewed(" in done["services.py"]
    assert 'workflow="GizmoReviewingWorkflow"' in done["services.py"]
    assert 'app="gizmos", noun="gizmo"' in done["services.py"]
    assert '"gizmo.review": owns,' in done["policies.py"]
    assert "class GizmoReviewedOut(GizmoOut):" in done["schemas.py"]
    create = done["services.py"].index("def create_gizmo(")
    start = done["services.py"].index("start_workflow_on_commit(\n", create)
    assert start < done["services.py"].index("    return gizmo", create)


def test_a_policy_lands_in_a_copied_noun_under_its_name_and_parses() -> None:
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    done = _inserted(noun, "policy", lambda line: line)
    assert "class GizmoPolicy(InheritedDownward, OrgScopedModel, Archivable):" in done["models.py"]
    assert '        "GizmoPolicy",' in done["models.py"]
    create = done["services.py"].index("def create_gizmo(")
    signature = done["services.py"].index(") -> Gizmo:", create)
    named = done["services.py"].index("policy: GizmoPolicy | None = None,", create)
    assert create < named < signature
    assert 'require(actor, "gizmo_policy.create")' in done["services.py"]
    assert "def get_governing_gizmo_policy(" in done["selectors.py"]
    assert 'url_name="governing_gizmo_policy-detail"' in done["api.py"]
    assert '@server.tool(name="create_gizmo_policy"' in done["mcp.py"]
    assert 'GIZMO_POLICY_ARCHIVED = "gizmos.gizmo_policy.archived"' in done["events.py"]
    assert '"gizmo_policy": policy_named_by_live_gizmos,' in done["archive_blockers.py"]
    assert '"gizmo": gizmo_named_policy_is_archived,' in done["restore_blockers.py"]
    resolution = "def test_the_nearest_policy_on_the_chain_is_the_one_that_governs("
    assert resolution in done["tests/test_network.py"]
    assert "Widget" not in "".join(done.values()) and "widget" not in "".join(done.values())


@pytest.mark.parametrize(
    ("fields", "declared", "vector"),
    [
        (
            ("name", "notes"),
            'fields=[("name", "A"), ("notes", "B")],',
            '            + SearchVector("notes", weight="B", config=SEARCH_CONFIG)',
        ),
        (("notes",), 'fields=[("notes", "A")],', 'SearchVector("notes", weight="A", config='),
    ],
)
def test_a_search_lands_in_a_copied_noun_under_its_fields_and_parses(
    fields: tuple[str, ...], declared: str, vector: str
) -> None:
    from apps.core.scaffold.arms.search import search_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    done = _inserted(noun, "search", lambda line: search_lines(line, fields, "gizmos", moved=False))
    assert declared in done["search.py"] and "model=Gizmo," in done["search.py"]
    assert 'label="gizmos",' in done["search.py"] and "MOVED" not in done["search.py"]
    assert "    search_vector = models.GeneratedField(" in done["models.py"]
    assert vector in done["models.py"]
    assert done["models.py"].count("SearchVector(") == len(fields)
    assert 'name="gizmo_search_vector_gin"' in done["models.py"]
    assert (
        'models.Index(fields=["tenant", "-created_at"], name="gizmo_recency")' in done["models.py"]
    )
    assert done["models.py"].index("search_vector = ") < done["models.py"].index("class Meta(")
    tests = done["tests/test_search_adoption.py"]
    assert f"== {list(fields)!r}".replace("'", '"') in tests
    assert '"app": "gizmos"' in tests and '"gizmos_gizmo" in compiled' in tests
    assert "move_gizmo" not in tests and "ONBOARDED" not in tests
    assert "Widget" not in "".join(done.values()) and "widget" not in "".join(done.values())


def test_a_schedule_is_refused_on_the_per_row_workflow_golden_and_its_help_says_so() -> None:
    from apps.core.management.commands.scaffold import Command

    with pytest.raises(CommandError) as refused:
        _scaffold("workflow", "example", "Widget", "onboard", "--schedule", "6h", "--check")
    assert refused.value.returncode == 2
    assert str(refused.value) == (
        "the workflow golden is per-row (its run takes WidgetOnboarding); a schedule starts a "
        "sweep with no row and no tenant — scaffold the process without --schedule, or wait for "
        "the sweep golden"
    )
    parser = Command().create_parser("manage.py", "scaffold")
    assert "per-row" in str(parser._option_string_actions["--schedule"].help)


def test_a_webhook_lands_in_a_copied_noun_under_its_provider_and_parses() -> None:
    from apps.core.scaffold.arms.webhook_in import webhook_lines

    golden = copier.index(ROOT)["webhook-in.onboarding"]
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    fragments = copier.Golden(
        golden.key, golden.app, tuple(f for f in golden.files if f != "apps.py")
    )
    done = _inserted(noun, fragments, lambda line: webhook_lines(line, "acme"))
    added = [
        line
        for rel, text in done.items()
        for line in text.splitlines()
        if line not in noun.get(rel, "").splitlines()
    ]
    assert [
        line for line in added if "onboarding" in line.lower() or "widget" in line.lower()
    ] == []
    assert "class AcmeProvider:" in done["integrations.py"]
    assert 'ACME_SLUG = "acme"' in done["integrations.py"]
    assert "def register_acme_webhooks() -> None:" in done["integrations.py"]
    assert "    acme_confirmed_at = models.DateTimeField(" in done["models.py"]
    assert 'GIZMO_ACME_CONFIRMED = "gizmos.gizmo.acme_confirmed"' in done["events.py"]
    assert "def confirm_gizmo_acme(" in done["services.py"]
    assert "from apps.gizmos.integrations import ACME_SLUG" in done["tests/test_inbound_webhook.py"]


def test_the_copys_verifier_says_it_replaces_the_receivers_check_and_next_points_at_it() -> None:
    from apps.core.scaffold.arms.webhook_in import verifier_next, webhook_lines

    golden = copier.index(ROOT)["webhook-in.onboarding"]
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    fragments = copier.Golden(
        golden.key, golden.app, tuple(f for f in golden.files if f != "apps.py")
    )
    seam = _inserted(noun, fragments, lambda line: webhook_lines(line, "acme"))["integrations.py"]
    verifier = next(
        n
        for n in ast.parse(seam).body
        if isinstance(n, ast.FunctionDef) and n.name == "verify_acme_delivery"
    )
    assert "replaces the receiver's HMAC check" in (ast.get_docstring(verifier) or "")
    said = verifier_next(seam, "gizmos", "acme")
    assert said.startswith(f"next: edit apps/gizmos/integrations.py:{verifier.lineno} ")
    assert "`verify_acme_delivery`" in said


_CONFIG = 'from django.apps import AppConfig\n\n\nclass GizmosConfig(AppConfig):\n    name = "g"\n'
_TWO = 'from django.apps import AppConfig\n\n\nclass GizmosConfig(AppConfig):\n  name = "g"\n'


@pytest.mark.parametrize(
    "apps_py",
    [
        _CONFIG,
        _CONFIG + '\n    def ready(self) -> None:\n        """Mine."""\n        import json\n',
        _TWO,
        _TWO + '\n  def ready(self) -> None:\n    """Mine."""\n    import json\n',
    ],
    ids=["no-ready", "a-ready", "two-space-no-ready", "two-space-a-ready"],
)
def test_the_registration_lands_in_the_app_configs_ready_either_way(apps_py: str) -> None:
    from apps.core.scaffold.arms.webhook_in import ready_registered

    method = (
        "def ready(self) -> None:\n"
        '    """Register the acme inbound webhook."""\n'
        "    from apps.gizmos.integrations import register_acme_webhooks\n\n"
        "    register_acme_webhooks()\n"
    )
    text, line = ready_registered(apps_py, method)
    tree = ast.parse(text)
    config = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    readies = [n for n in config.body if isinstance(n, ast.FunctionDef) and n.name == "ready"]
    assert len(readies) == 1 and line > 0
    assert ast.unparse(readies[0].body[-1]) == "register_acme_webhooks()"
    assert text.count("def ready(") == 1 and ("import json" in text) == ("import json" in apps_py)
    assert text.splitlines()[line - 1].lstrip().startswith("def ready(")
    end = readies[0].end_lineno or line
    landed = textwrap.dedent("\n".join(text.splitlines()[line - 1 : end]))
    if "Mine." in apps_py:
        tail = method.splitlines()[2:]
        moved = "\n".join(text.splitlines()[end - len(tail) : end])
        assert textwrap.dedent(moved) == textwrap.dedent("\n".join(tail))
    else:
        assert landed == method.rstrip("\n")


def test_an_enum_lands_in_a_copied_noun_as_a_chain_first_to_last() -> None:
    from apps.core.scaffold.arms.enum import enum_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    values = ("OPEN", "PACKED", "SHIPPED", "CLOSED")
    done = _inserted(noun, "enum.status", lambda line: enum_lines(line, "stage", values))
    model = done["models.py"]
    assert [v for v in values if f'{v} = "{v.lower()}"' in model] == list(values)
    assert model.count("Stage.") == 2 * (len(values) - 1) + 2
    assert "default=Stage.OPEN" in model and "STAGE_NEXT" in model and "Status" not in model
    assert "def transition_gizmo(" in done["services.py"]


@pytest.mark.parametrize(
    ("child", "plural"),
    [
        ("Entry", "entries"),
        ("Line", "lines"),
        ("Box", "boxes"),
        ("Batch", "batches"),
        ("Day", "days"),
        ("LineItem", "line_items"),
        ("Wish", "wishes"),
    ],
)
def test_a_child_names_its_rows_in_the_plural(child: str, plural: str) -> None:
    from apps.core.scaffold.arms.child import plural_of

    assert plural_of(copier.snake(child)) == plural


def test_a_child_lands_in_a_copied_noun_under_its_name_and_parses() -> None:
    from apps.core.scaffold.arms.child import child_lines

    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    done = _inserted(noun, "child.entry", lambda line: child_lines(line, "LineItem"))
    added = "".join(
        line
        for rel, text in done.items()
        for line in text.splitlines(keepends=True)
        if line not in noun.get(rel, "").splitlines(keepends=True)
    )
    assert "class GizmoLineItem(OrgScopedModel):" in done["models.py"]
    assert '        related_name="line_items",' in done["models.py"]
    assert "def record_gizmo_line_item(" in done["services.py"]
    assert "def list_gizmo_line_items(" in done["selectors.py"] and "lineage" not in added
    assert 'url_name="gizmo_line_items-list"' in done["api.py"]
    assert '@router.post("/line_items/"' in done["api.py"]
    assert '@server.tool(name="record_gizmo_line_item"' in done["mcp.py"]
    assert '"gizmo_line_item.record": can_record_line_item,' in done["policies.py"]
    assert "class GizmoLineItemPage(ListPage):" in done["schemas.py"]
    assert (
        "def test_line_items_list_query_count_does_not_grow_with_rows(" in done["tests/test_api.py"]
    )
    assert "ntry" not in added.replace("AuditEntry", "") and "ntries" not in added
    assert "Widget" not in "".join(done.values()) and "widget" not in "".join(done.values())


def _child_copy(child: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """The noun `Gizmo`'s copy, and the copy with the child golden put in as `child`."""
    from apps.core.scaffold.arms.child import child_held, child_lines

    golden = copier.index(ROOT)["child.entry"]
    texts = {rel: source_text(ROOT / golden.path(rel)) for rel in golden.files}
    held, said = child_held(texts, child)
    noun = copier.from_golden(ROOT, copier.index(ROOT)["noun"], "gizmos", "Gizmo").files
    return noun, _inserted(noun, golden, lambda line: child_lines(line, child, held)), said


@pytest.mark.parametrize("child", ["Request", "Event", "LineItem"])
def test_a_child_renames_the_goldens_own_tokens_and_never_a_platform_name(child: str) -> None:
    noun, done, _ = _child_copy(child)
    added = "".join(
        line
        for rel, text in done.items()
        for line in text.splitlines(keepends=True)
        if line not in noun.get(rel, "").splitlines(keepends=True)
    )
    assert "`core.AuditEntry`" in done["models.py"]
    assert f"Audit{child}" not in added
    assert "ntry" not in added.replace("AuditEntry", "") and "ntries" not in added
    assert f"class Gizmo{child}(OrgScopedModel):" in done["models.py"]
    assert not re.search(r"\b[Aa]n (request|line_item)\b", added), "a consonant after an"


def test_a_child_whose_word_the_golden_already_spells_takes_its_full_name_where_they_meet() -> None:
    _, done, said = _child_copy("Request")
    api = done["api.py"]
    for node in ast.walk(ast.parse(api)):
        if isinstance(node, ast.FunctionDef) and "request" in {a.arg for a in node.args.args}:
            bound = {
                t.id
                for s in ast.walk(node)
                if isinstance(s, ast.Assign)
                for t in s.targets
                if isinstance(t, ast.Name)
            }
            assert "request" not in bound, f"{node.name} rebinds its own `request`"
    assert "    gizmo_request = record_gizmo_request(" in api
    assert "return GizmoRequestOut.from_orm(gizmo_request)" in api
    assert api.count("request: TenantRequest") >= 2
    assert said and "`request`" in said[0] and "api.py:" in said[0], said


def test_a_child_whose_full_name_is_taken_too_is_refused_naming_both() -> None:
    from apps.core.scaffold.arms.child import ChildClash, child_held

    texts = {"api.py": "def route(request, widget_request):\n    entry = request\n"}
    with pytest.raises(ChildClash) as refused:
        child_held(texts, "Request")
    assert "api.py:1" in str(refused.value) and "`widget_request`" in str(refused.value)


def _route_titles(api: str) -> dict[str, str]:
    """Each `@router` function's title in `api`, as house rule 41 reads it."""
    from apps.core.api.docs import contract_half, title_of

    return {
        node.name: title_of(contract_half(ast.get_docstring(node, clean=False)))
        for node in ast.walk(ast.parse(api))
        if isinstance(node, ast.FunctionDef)
        and any("router." in ast.unparse(d) for d in node.decorator_list)
    }


@pytest.mark.parametrize(
    ("child", "said"),
    [("GerminationTest", "germination test"), ("LineItem", "line item"), ("Line", "line")],
)
def test_a_child_of_any_word_count_is_titled_in_words_house_rule_41_admits(
    child: str, said: str
) -> None:
    from apps.core.api.docs import title_faults
    from apps.core.management.commands.scaffold import Command

    _, done, _ = _child_copy(child)
    titles = _route_titles(done["api.py"])
    assert f"Record a ledger {said}" in titles.values(), titles
    assert any(t.startswith("List ledger ") and said in t for t in titles.values()), titles
    assert all(not title_faults(t) for t in titles.values()), titles
    Command.refuse_titles(done)
    assert f'verbose_name = "gizmo {said}"' in done["models.py"]


def test_a_route_title_rule_41_would_refuse_is_refused_before_any_write() -> None:
    from apps.core.management.commands.scaffold import Command

    api = (
        '@router.post("/x/")\ndef record_x(request):\n'
        '    """Record a ledger germination_test\n\n    Body.\n    """\n'
    )
    with pytest.raises(CommandError) as refused:
        Command.refuse_titles({"api.py": api})
    said = str(refused.value)
    assert "'Record a ledger germination_test'" in said and "nothing was written" in said, said
    assert "djb.E041" in said


def test_a_noun_whose_private_helper_another_app_defines_is_refused_before_any_write() -> None:
    with pytest.raises(CommandError) as refused:
        _scaffold("noun", "inventories", "Request")
    assert refused.value.returncode == 2
    said = str(refused.value)
    assert "_requests_in" in said and "apps/example_portal/selectors.py" in said, said
    assert "house rule 84" in said
    assert not (ROOT / "apps/inventories").exists()


# --- the screen's dry run: the one `would` grammar `roads shape` reads ---------------------------


def test_the_screen_dry_run_plans_in_the_would_grammar_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.core.management.commands.scaffold import Command
    from apps.core.scaffold.arms.screen import LEXICON
    from apps.core.tests.test_scaffold_screen import planted

    document = planted(json.loads((ROOT / "frontend/openapi.json").read_text()), "Gizmo")
    monkeypatch.setattr(Command, "served", lambda self, root, noun: ())
    monkeypatch.setattr(Command, "document", lambda self, root: document)
    lexicon = (ROOT / LEXICON).read_text()
    planned = _scaffold("screen", "Gizmo", "--dry-run").splitlines()
    shaped = io.StringIO()
    call_command("roads", "shape", "screen", "Gizmo", stdout=shaped)
    assert planned and all(line.startswith("would ") for line in planned), planned
    assert any(line.startswith("would write frontend/src/screens/gizmo/") for line in planned)
    assert [line for line in shaped.getvalue().splitlines() if line.startswith("would ")] == planned
    assert not (ROOT / "frontend/src/screens/gizmo").exists()
    assert (ROOT / LEXICON).read_text() == lexicon


def test_every_shape_lists_the_arguments_its_own_refusal_teaches() -> None:
    from apps.core.scaffold.shapes import SHAPES

    source = "".join(
        p.read_text()
        for p in (
            ROOT / "apps/core/management/commands/scaffold.py",
            *sorted((ROOT / "apps/core/scaffold/arms").glob("*.py")),
        )
    )
    listed = _scaffold("--list").splitlines()
    for shape in SHAPES:
        taught = (f"{shape.key} takes", "{shape.key} takes", "{registered.key} takes")
        assert any(f"{t} {shape.args} —" in source for t in taught), shape.key
        assert all(f" {shape.args} " in ln for ln in listed if ln.split()[:1] == [shape.key])


def test_every_flag_an_arm_reads_is_in_its_shapes_listed_arguments() -> None:
    """A flag the parser takes and `--list` (so shapes.md) never names is a shape nobody finds."""
    from apps.core.scaffold.shapes import SHAPES

    args = {shape.key: shape.args for shape in SHAPES}
    unlisted: list[str] = []
    for module in sorted((ROOT / "apps/core/scaffold/arms").glob("*.py")):
        tree = ast.parse(module.read_text())
        keys = next(
            (
                ast.literal_eval(node.value)
                for node in tree.body
                if isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "KEYS"
                and node.value is not None
            ),
            (),
        )
        flags = [
            str(call.args[0].value)
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr == "add_argument"
            and call.args
            and isinstance(call.args[0], ast.Constant)
        ]
        for flag in flags:
            if not any(f"{flag} " in args.get(key, "") for key in keys):
                unlisted.append(f"{module.name}: {flag} is in no listed grammar of {keys}")
    assert unlisted == [], unlisted


def test_a_shape_on_a_noun_aimed_at_a_child_is_refused_in_one_line() -> None:
    from apps.core.management.commands.scaffold import Command

    models = 'class WidgetEntry(OrgScopedModel):\n    derive_org_from = "widget"\n'
    said = Command.refuse_child(models, "example", "WidgetEntry")
    assert said is not None and "is a child" in said and "docs/sdk/shapes.md" in said, said
    assert Command.refuse_child("class Widget(OrgScopedModel):\n    x = 1\n", "e", "Widget") is None
