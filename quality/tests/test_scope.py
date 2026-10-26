"""The `--loop` scope and tier: `scope.py`, the loop legs and the pytest door, case for case."""

# deleted: case_a_banner_with_no_recorded_cause_is_exit_2 — dies with the shim
# pin: test_a_substitution_callees_refusal_surfaces_as_cause (modes.pr_scope)
# deleted: case_the_tier_is_wired_into_the_loop_leg — dies with the shim
# pin: test_the_loop_leg_asks_the_fast_tier_for_the_own_apps (registry `Leg.modes`)
# deleted: case_the_full_gate_leg_carries_no_tier — dies with the shim
# pin: test_the_full_gate_passes_carry_no_tier (pytest_x2.passes)
# deleted: case_the_always_on_leg_is_wired_into_the_loop — dies with the shim
# pin: test_the_registry_claims_the_loop_only_leg_after_secrets (test_legs_always_on.py)
# deleted: case_the_box_guard_is_wired_above_everything_it_would_cost — dies with the shim
# pin: test_a_loop_off_a_box_is_refused_in_the_shells_words_above_every_hold (test_modes.py)
# narrowed: case_a_dying_collector_leaves_a_named_absence_not_silence — less check.sh's call order
# narrowed: case_a_typed_slot_share_is_the_workers_number_and_no_clamp_fires — less gate_lease.sh
# narrowed: case_a_typed_share_above_the_slot_is_refused_naming_both — less gate_lease.sh's order
# narrowed: case_the_mine_arm_in_the_placement_case_matches_the_flags_check_sh_passes — less text
# narrowed: case_mine_runs_own_apps_only_and_never_banks — less check.sh's key guard
# narrowed: case_a_dying_collector_under_the_full_gate_leg_body_is_exit_2_and_banks_nothing  # noqa: E501
# narrowed: case_a_dying_collector_under_pr_is_exit_2_and_writes_no_narrowed_run_note — less order
# narrowed: case_census_runs_the_instrument_census_alone_without_a_slot — less check.sh's arm order
# narrowed: case_a_tree_miss_prints_three_lines_every_other_miss_two_and_the_detail_on_request  # noqa: E501
# narrowed: case_pr_narrows_pytest_and_nothing_else — less check.sh's --pr block
# narrowed: case_the_measurement_flag_belongs_to_the_full_mode_alone — less the cut parser arm
# narrowed: case_every_registered_drive_member_resolves_to_a_file — less the planted ghost walk
# narrowed: case_the_loop_banner_names_each_declared_census — less check.sh's calls
# does-not-cover: the bank's real `-n` at every core — the real run is `BANK_RUN` workers.
# does-not-cover: a verbose miss's components block — the Python miss prints the attributor's lines.

# moved: test_sweep_runs_on_any_shell_change — this module, renamed

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import cli, gate_args, hold, ledger, loop, modes, scope
from quality.djb import registry as R
from quality.djb.legs import always_on as ao
from quality.djb.legs import loop_pytest, pytest_x2
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.checkout import add_checkout, remove_checkout
from quality.tests.fixtures.interpreter import untouched
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives(
    "quality/djb/scope.py",
    ".gitignore",
    "apps/*.py",
    "apps/*/apps.py",
    "apps/*/tests/",
    "apps/testing/",
    "config/**",
    "deploy/tests/**",
    "docs/product/build-contract.md",
    "perf/conftest.py",
    "pyproject.toml",
    "quality/partition.yaml",
    "scripts/gate_lease.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_refuse.sh",
    "scripts/goalpost_scan.py",
    "scripts/test.sh",
)

HOME = scope.HOME
MAP_LEAF_TESTS = 4
MAP_TESTS = 300


def _git(root: Path, *argv: str) -> str:
    done = subprocess.run(["git", "-C", str(root), *argv], capture_output=True, text=True)
    assert done.returncode == 0, f"git {' '.join(argv)}: {done.stderr}"
    return done.stdout.strip()


def _app(root: Path, label: str, deps: str) -> None:
    folder = root / "apps" / label
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "__init__.py").write_text("")
    (folder / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\n"
        f"class {label.capitalize()}Config(AppConfig):\n"
        f'    name = "apps.{label}"\n'
        f"    depends_on: tuple[str, ...] = ({deps})\n"
    )


#: A fixture docs path in halves: the pointer census reads a whole one as a pointer.
DOCS_NOTE = "/".join(("docs", "note.md"))

BASE_FILES = (
    "README.md",
    "config/settings.py",
    "quality/rules.yaml",
    "frontend/src/app.tsx",
    DOCS_NOTE,
    "templates/base.html",
    "pyproject.toml",
    "apps/conftest.py",
    "apps/test_root.py",
    "scripts/tests/test_thing.sh",
    "scripts/check.sh",
    "apps/mid/services.py",
    "apps/leaf/services.py",
    "apps/aside/services.py",
    "apps/core/models.py",
    "apps/mid/conftest.py",
    "apps/mid/tests/test_thing.py",
    "apps/mid/tests/conftest.py",
    "apps/core/tests/test_core_thing.py",
    "apps/core/migrations/0001_initial.py",
    "apps/core/services.py",
)


@pytest.fixture
def world(scratch_repo: Callable[..., Path]) -> Path:
    """The four-app graph core <- mid <- leaf, core <- aside, every later-changed path committed."""
    root = scratch_repo("world", "loop scope drive")
    _app(root, "core", "")
    _app(root, "mid", '"core",')
    _app(root, "leaf", '"mid",')
    _app(root, "aside", '"core",')
    for rel in BASE_FILES:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    return root


def touch(root: Path, *paths: str) -> None:
    for rel in paths:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as sink:
            sink.write("changed\n")


def derive(root: Path, **kwargs: object) -> scope.Scope:
    return scope.derive(root, **kwargs)  # type: ignore[arg-type]


def notes(s: scope.Scope) -> str:
    return "\n".join(s.notes)


def commit_all(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    if _git(root, "status", "--porcelain"):
        _git(root, "commit", "-q", "-m", message)


# --- the scope a collapsed checkout cannot derive for itself -------------------


def test_a_collapsed_checkout_derives_the_same_scope_when_the_base_is_carried(
    world: Path, scratch: Path
) -> None:
    """A depth-1 box clone derives nothing alone, and the same scope once the base is carried."""
    _git(world, "checkout", "-q", "-b", "rung")
    touch(world, "apps/mid/services.py")
    commit_all(world, "rung work in mid")
    base = _git(world, "merge-base", "rung", "main")
    want = derive(world)
    assert (want.touched, want.apps) == (["mid"], ["leaf", "mid"])
    box = scratch / "box"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "rung", f"file://{world}", str(box)],
        check=True,
        capture_output=True,
    )
    _git(box, "branch", "-q", "-f", "main", "HEAD")
    _git(box, "checkout", "-q", "main")
    alone = derive(box)
    assert (alone.touched, alone.apps) == ([], [])
    _git(world, "update-ref", "refs/djb/base", base)
    _git(box, "fetch", "-q", "--depth", "1", f"file://{world}", "+refs/djb/base:refs/djb/base")
    carried = derive(box, carried="refs/djb/base")
    assert (carried.touched, carried.apps) == (want.touched, want.apps)
    assert carried.canonical == want.canonical
    assert "CARRIED fork point" in carried.basis


# --- the fan-out decision table, one case per row ------------------------------


def test_a_core_touch_reaches_every_app_through_the_closure_alone(world: Path) -> None:
    """A core touch reaches every app because every app declares core, not by a special case."""
    touch(world, "apps/core/models.py")
    s = derive(world)
    assert (s.mode, s.touched, s.apps) == ("fast", ["core"], ["aside", "core", "leaf", "mid"])
    assert (s.widened, s.own) == (["aside", "leaf", "mid"], ["core"])
    code = [
        line.split("#", 1)[0] for line in (HOME / "quality/djb/scope.py").read_text().splitlines()
    ]
    assert not [line for line in code if "apps/core" in line]


def test_the_transitive_step_is_walked_not_one_hop(world: Path) -> None:
    """core's closure reaches leaf, two declarations away."""
    touch(world, "apps/mid/services.py")
    assert derive(world).apps == ["leaf", "mid"]
    assert "leaf" in scope.closure(world / "apps", ["core"])


def test_forward_edges_are_not_widened(world: Path) -> None:
    """aside declares core, and touching aside does not drag core in."""
    touch(world, "apps/aside/services.py")
    assert derive(world).apps == ["aside"]
    assert "forward edges are not widened" in (HOME / "quality/djb/scope.py").read_text()


def test_config_is_the_full_suite_with_its_sentence(world: Path) -> None:
    touch(world, "config/settings.py")
    s = derive(world)
    assert (s.mode, s.narrow, s.shared_hits) == ("full", False, ["config/settings.py"])
    assert "FULL suite" in s.reason


def test_templates_are_the_full_suite(world: Path) -> None:
    touch(world, "templates/base.html")
    assert derive(world).mode == "full"


def test_quality_widens_no_pytest_scope_and_names_the_rule_that_outranks(world: Path) -> None:
    touch(world, "quality/rules.yaml")
    s = derive(world)
    assert (s.mode, s.apps) == ("fast", [])
    assert "FULL GATE under a typed DJB_GATE_SANCTION" in notes(s)


def test_a_frontend_only_touch_derives_an_empty_backend_scope(world: Path) -> None:
    touch(world, "frontend/src/app.tsx")
    s = derive(world)
    assert (s.mode, s.apps, s.narrow) == ("fast", [], True)
    assert "no import path from frontend/ into a Python test" in notes(s)
    assert "always-on cross-app set runs alone" in s.reason


@pytest.mark.parametrize(
    "shape",
    [
        "apps/conftest.py",
        "apps/test_root.py",
        "scripts/tests/test_thing.sh",
    ],
)
def test_the_shared_shapes_outrank_an_app_touched_beside_them(world: Path, shape: str) -> None:
    touch(world, shape, "apps/mid/services.py")
    s = derive(world)
    assert (s.mode, s.apps) == ("full", [])


def test_the_reflexive_shape_covers_the_whole_selection_machinery() -> None:
    """The three files that decide what `--loop` runs are shared; an app's own conftest is not."""
    for path in (
        "scripts/check.sh",
        "scripts/secrets_scan.sh",
        "scripts/gate_ledger.sh",
    ):
        assert scope.is_shared_test_infra(path), path
    assert not scope.is_shared_test_infra("apps/mid/tests/conftest.py")


def test_the_declared_blind_spot_widens_nothing_and_says_so(world: Path) -> None:
    touch(world, "pyproject.toml")
    s = derive(world)
    assert (s.mode, s.apps) == ("fast", [])
    assert "DEPENDENCY rung" in notes(s)


def test_an_unclassifiable_path_is_exit_2_naming_the_path_and_the_table(world: Path) -> None:
    (world / "newterritory").mkdir()
    (world / "newterritory/thing.py").write_text("base\n")
    commit_all(world, "a territory the table has no row for")
    touch(world, "newterritory/thing.py")
    with pytest.raises(scope.Unclassified) as refused:
        derive(world)
    for phrase in (
        "newterritory/thing.py",
        "classify",
        "NO ROW",
        "silent full run",
        "silent narrow one",
    ):
        assert phrase in str(refused.value)


def test_the_one_legal_override_only_widens(world: Path) -> None:
    touch(world, "apps/mid/services.py")
    s = derive(world, also="aside")
    assert s.apps == ["aside", "leaf", "mid"]
    assert "can only ADD" in notes(s)
    assert not re.search(
        r"\bexcept_|\bonly_apps|\bminus\b", (HOME / "quality/djb/scope.py").read_text()
    )


def test_a_tests_only_touch_seeds_no_closure_and_is_not_own(world: Path) -> None:
    touch(world, "apps/core/tests/test_core_thing.py")
    s = derive(world)
    assert (s.mode, s.tests_only, s.touched, s.apps, s.own, s.narrow) == (
        "fast",
        ["core"],
        [],
        [],
        [],
        True,
    )
    assert s.changed_tests == ["apps/core/tests/test_core_thing.py"]
    assert "coupling that is not an import" in notes(s)
    assert "tests under apps/" in s.reason


def test_one_non_test_path_makes_the_app_an_ordinary_touch(world: Path) -> None:
    touch(world, "apps/core/tests/test_core_thing.py", "apps/core/services.py")
    s = derive(world)
    assert (s.tests_only, s.touched, s.apps) == ([], ["core"], ["aside", "core", "leaf", "mid"])


def test_a_core_tests_edit_beside_a_leaf_touch_walks_the_leafs_closure_only(world: Path) -> None:
    touch(world, "apps/core/tests/test_core_thing.py", "apps/leaf/services.py")
    s = derive(world)
    assert (s.tests_only, s.touched, s.apps, s.own) == (["core"], ["leaf"], ["leaf"], ["leaf"])


def test_a_migration_touch_widens_by_the_import_graph_not_by_tests(world: Path) -> None:
    touch(world, "apps/core/migrations/0001_initial.py")
    s = derive(world)
    assert (s.tests_only, s.touched) == ([], ["core"])
    _git(world, "checkout", "-q", "--", ".")
    touch(world, "apps/core/services.py")
    assert derive(world).apps == s.apps
    assert "reverse-transitive depends_on closure" in s.reason


def test_an_apps_root_conftest_is_an_ordinary_touch_not_tests_only(world: Path) -> None:
    touch(world, "apps/mid/conftest.py")
    s = derive(world)
    assert (s.tests_only, s.touched, s.apps) == ([], ["mid"], ["leaf", "mid"])
    _git(world, "checkout", "-q", "--", ".")
    touch(world, "apps/mid/tests/conftest.py")
    s = derive(world)
    assert (s.tests_only, s.apps) == (["mid"], [])


def test_the_fixture_drawer_is_shared_test_infra(world: Path) -> None:
    (world / "apps/conftest_local.py").write_text("base\n")
    commit_all(world, "the fixture drawer, present in the base")
    touch(world, "apps/conftest_local.py")
    s = derive(world)
    assert (s.mode, s.apps, s.tests_only) == ("full", [], [])
    assert not scope.is_shared_test_infra("apps/mid/conftest_local.py")


def _drawer_paths(column: str) -> list[str]:
    col = column.replace("<name>", "probe").replace("<nn>", "10")
    found = re.fullmatch(r"([^<>]*)<([^<>]*)>([^<>]*)", col)
    if found:
        head, members, tail = found.groups()
        assert "," in members, f"a drawer path this case cannot turn into a file: {column}"
        out = []
        for member in (m.strip() for m in members.split(",")):
            if member:
                out.append(f"{head}{member + 'probe' if member.endswith('/') else member}{tail}")
        return out
    assert "<" not in col and ">" not in col, (
        f"a drawer path this case cannot turn into a file: {column}"
    )
    return [f"{col}probe" if col.endswith("/") else col]


def test_every_drawer_path_the_build_contract_prescribes_has_a_row() -> None:
    """Every live `drawers` row's path classifies: a product filling a drawer is never exit 2."""
    text = (HOME / "docs/product/build-contract.md").read_text()
    block = re.search(r"^```drawers[ \t]*\n(.*?)^```", text, re.MULTILINE | re.DOTALL)
    if block is None:
        raise CouldNotLook("the build contract has no drawers block")
    rows = [line for line in block.group(1).splitlines() if line.startswith("live |")]
    if not rows:
        raise CouldNotLook("the drawers block has no live rows")
    paths = [p for row in rows for p in _drawer_paths(row.split(" | ")[2].strip())]
    assert paths
    for path in paths:
        assert scope.classify(path)


def test_also_outranks_tests_only(world: Path) -> None:
    touch(world, "apps/mid/tests/test_thing.py")
    s = derive(world, also="mid")
    assert (s.tests_only, s.touched, s.apps) == ([], ["mid"], ["leaf", "mid"])
    assert "can only ADD" in notes(s)


def test_the_canonical_key_differs_between_a_tests_only_and_an_own_app_run(world: Path) -> None:
    touch(world, "apps/mid/tests/test_thing.py")
    tests_only = derive(world).canonical
    assert "tests=mid" in tests_only
    _git(world, "checkout", "-q", "--", ".")
    touch(world, "apps/mid/services.py")
    own = derive(world).canonical
    assert own != tests_only
    assert re.search(r"always=.* tests=", own)


def test_a_path_under_apps_the_table_cannot_place_is_exit_2(world: Path) -> None:
    (world / "apps/stray_module.py").write_text("base\n")
    commit_all(world, "a module under apps/ that belongs to no app")
    touch(world, "apps/stray_module.py")
    with pytest.raises(scope.Unclassified) as refused:
        derive(world)
    for phrase in ("apps/stray_module.py", "classify", "silent full run", "silent narrow one"):
        assert phrase in str(refused.value)


def test_an_absent_local_main_is_a_refusal_not_a_thin_basis(world: Path) -> None:
    _git(world, "checkout", "-q", "-b", "rung/thing")
    touch(world, "apps/mid/services.py")
    commit_all(world, "the rung's own work")
    _git(world, "branch", "-D", "main")
    with pytest.raises(CouldNotLook) as refused:
        derive(world)
    for phrase in (
        "NO local refs/heads/main",
        "git branch main",
        "A thin basis is not a small answer",
        "linked worktree",
    ):
        assert phrase in str(refused.value)


def test_on_main_the_uncommitted_only_basis_stays_legal_and_prints_itself(world: Path) -> None:
    touch(world, "apps/mid/services.py")
    assert "on main itself" in derive(world).basis


def test_an_undiscoverable_app_is_exit_2_naming_its_apps_py(world: Path) -> None:
    (world / "apps/ghost").mkdir()
    (world / "apps/ghost/services.py").write_text("base\n")
    commit_all(world, "a directory under apps/ that declares no AppConfig")
    touch(world, "apps/ghost/services.py")
    with pytest.raises(CouldNotLook) as refused:
        derive(world)
    assert "apps/ghost/apps.py" in str(refused.value)
    assert "declares no AppConfig" in str(refused.value)


def test_a_broken_changed_file_derivation_is_the_inherited_exit_2(scratch: Path) -> None:
    outside = scratch / "not-a-repo"
    outside.mkdir()
    with pytest.raises(CouldNotLook, match="could not read a git directory"):
        derive(outside)


# --- the seeds: a census over other apps, a literal reader of an inert path ---


def _literal_world(root: Path) -> None:
    (root / "TEMPLATE_VERSION").write_text("0.0.1\n")
    (root / "apps/core/tests/test_zzz_version_reader.py").write_text(
        '"""Reads the version file by name."""\n\nVERSION_FILE = "TEMPLATE_VERSION"\n'
    )
    (root / "apps/mid/tests/test_zzz_notes_reader.py").write_text(
        '"""Reads the changelog by name."""\n\nLOG = "zzz_notes.md"\n'
    )
    (root / "apps/mid/tests/test_zzz_prose_only.py").write_text(
        '"""Mentions `TEMPLATE_VERSION` in prose and never opens it."""\n'
    )
    (root / "zzz_notes.md").write_text("# notes\n")
    commit_all(root, "the literal readers")


def test_a_version_or_markdown_change_seeds_the_tests_that_quote_it(world: Path) -> None:
    _literal_world(world)
    touch(world, "TEMPLATE_VERSION")
    s = derive(world)
    reader = "apps/core/tests/test_zzz_version_reader.py"
    assert (s.apps, s.seeded_tests) == ([], [reader])
    assert f"literal-read seeded by TEMPLATE_VERSION: {reader}" in notes(s)
    assert "gate_docs_only_literal_reads" in notes(s)
    assert [a for a in scope.pytest_args(s) if a.startswith("--djb-changed-test=")] == [
        f"--djb-changed-test={reader}"
    ]
    assert f"seeded={reader} " in s.canonical
    _git(world, "checkout", "-q", "--", ".")
    touch(world, "zzz_notes.md")
    assert derive(world).seeded_tests == ["apps/mid/tests/test_zzz_notes_reader.py"]
    _git(world, "checkout", "-q", "--", ".")
    touch(world, "README.md")
    assert derive(world).seeded_tests == []


def _scratch_census(root: Path, *names: str) -> str:
    module = "apps/core/tests/test_scratch_census.py"
    decls = ", ".join(f'"{n}"' for n in names)
    (root / module).write_text(
        f'"""A scratch census over other apps declarations."""\n\nCENSUS_SEEDED_BY = ({decls},)\n'
    )
    return module


def test_a_policies_touch_census_seeds_the_vocabulary_module(world: Path) -> None:
    census = _scratch_census(world, "policies", "roles")
    (world / "apps/mid/policies.py").write_text("POLICIES = {}\n")
    _git(world, "add", "apps/mid/policies.py")
    s = derive(world)
    assert (s.seeded_tests, s.seeded_by, s.touched) == ([census], ["apps/mid/policies.py"], ["mid"])
    assert "core" not in s.apps
    assert [a for a in scope.pytest_args(s) if a.startswith("--djb-changed-test=")] == [
        f"--djb-changed-test={census}"
    ]
    assert f"census-seeded by apps/mid/policies.py: {census}" in notes(s)
    assert f"seeded={census}" in s.canonical


def test_roles_seed_the_same_census_and_ordinary_files_seed_nothing(world: Path) -> None:
    census = _scratch_census(world, "policies", "roles")
    (world / "apps/leaf/roles.py").write_text("ROLES = {}\n")
    _git(world, "add", "apps/leaf/roles.py")
    assert derive(world).seeded_tests == [census]
    _git(world, "rm", "-q", "--cached", "apps/leaf/roles.py")
    (world / "apps/leaf/roles.py").unlink()
    touch(world, "apps/leaf/services.py")
    s = derive(world)
    assert s.seeded_tests == [] and "seeded=-" in s.canonical
    _git(world, "checkout", "-q", "--", ".")
    (world / "apps/core/policies.py").write_text("POLICIES = {}\n")
    _git(world, "add", "apps/core/policies.py")
    s = derive(world)
    assert (s.seeded_tests, s.touched) == ([], ["core"])


def test_the_always_on_digest_survives_a_machine_with_no_shasum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The digest is hashlib's: an empty PATH changes nothing about it."""
    normal = scope.harness_digest(HOME)
    assert re.fullmatch(r"[0-9a-f]{64}", normal)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert scope.harness_digest(HOME) == normal


# --- the test-impact map ---------------------------------------------------------


def _entry(files: list[str]) -> list[str]:
    return files


def _plant_map(root: Path, shape: str = "whole") -> None:
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    tests: dict[str, list[str]] = {}
    for i in range(1, MAP_LEAF_TESTS + 1):
        if shape == "dropped-test" and i == 1:
            continue
        files = ["apps/core/services.py", "apps/conftest.py"]
        if shape != "no-leaf":
            files.insert(0, "apps/leaf/services.py")
        tests[f"apps/leaf/tests/test_leaf.py::test_leaf_{i}"] = files
    for i in range(MAP_LEAF_TESTS + 1, MAP_TESTS + 1):
        tests[f"apps/mid/tests/test_mid.py::test_mid_{i}"] = [
            "apps/mid/services.py",
            "apps/core/services.py",
            "apps/conftest.py",
        ]
    doc = {
        "generated": {
            "at": "2026-09-18T00:00:00+00:00",
            "pytest": MAP_TESTS,
            "tree": f"tree:{tree}",
        },
        "tests": tests,
        "unmapped": {},
    }
    (root / scope.MAP_PATH).write_text(json.dumps(doc, indent=2) + "\n")
    _git(root, "add", scope.MAP_PATH)
    _git(root, "commit", "-q", "-m", "the fixture map")


def _selection(s: scope.Scope) -> list[str]:
    return Path(s.impact.select).read_text().splitlines() if s.impact.select else []


def test_a_seen_leaf_file_selects_only_its_tests(world: Path) -> None:
    _plant_map(world)
    touch(world, "apps/leaf/services.py")
    s = derive(world, asked_impact=True)
    assert (s.impact.seen, s.impact.tests, s.impact.fallback) == ("1", str(MAP_LEAF_TESTS), "")
    chosen = _selection(s)
    assert "apps/leaf/tests/test_leaf.py::test_leaf_1" in chosen
    assert not [one for one in chosen if "test_mid_" in one]
    assert s.apps == ["leaf"]
    args = scope.pytest_args(s)
    assert f"--djb-impact-select={s.impact.select}" in args
    assert "--djb-changed=apps/leaf/services.py" in args
    assert "--djb-scope=leaf" not in args and "--djb-scope-narrow" not in args
    assert re.search(r" map=\S", s.canonical)


@pytest.mark.parametrize(
    "plant",
    [
        "templates/x.html",
        ".env.example",
        "apps/leaf/fixtures/a.json",
        "quality/rules.yaml",
        "apps/leaf/migrations/0002_x.py",
    ],
)
def test_a_never_seen_file_falls_back_and_says_so(world: Path, plant: str) -> None:
    path = world / plant
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("base\n")
    commit_all(world, "the plant, in the base")
    _plant_map(world)
    touch(world, plant)
    s = derive(world, asked_impact=True)
    assert s.impact.select == ""
    assert plant in s.impact.fallback and "never recorded by the map" in s.impact.fallback
    assert re.search(r" map=\S", s.canonical)
    args = scope.pytest_args(s)
    if s.mode == "full":
        assert "--djb-scope-narrow" not in args
    else:
        assert "--djb-scope-narrow" in args
        assert not [a for a in args if a.startswith("--djb-impact-select")]


def test_a_root_file_selects_everything_it_touches(world: Path) -> None:
    _plant_map(world)
    touch(world, "apps/core/services.py")
    s = derive(world, asked_impact=True)
    assert (s.impact.tests, s.impact.fallback) == (str(MAP_TESTS), "")


def test_a_removed_entry_falls_back_and_a_dropped_test_is_the_declared_hole(world: Path) -> None:
    _plant_map(world, "no-leaf")
    touch(world, "apps/leaf/services.py")
    s = derive(world, asked_impact=True)
    assert s.impact.select == "" and "apps/leaf/services.py" in s.impact.fallback
    args = scope.pytest_args(s)
    assert "--djb-scope=leaf" in args
    assert not [a for a in args if a.startswith("--djb-impact-select")]
    _git(world, "checkout", "-q", "--", ".")
    _plant_map(world, "dropped-test")
    touch(world, "apps/leaf/services.py")
    s = derive(world, asked_impact=True)
    assert s.impact.tests == str(MAP_LEAF_TESTS - 1)
    assert "apps/leaf/tests/test_leaf.py::test_leaf_1" not in _selection(s)


def test_an_absent_map_is_the_closure_scope(world: Path) -> None:
    touch(world, "apps/leaf/services.py")
    s = derive(world, asked_impact=True)
    assert (s.impact.sha, s.impact.select) == ("-", "")
    assert "absent or unreadable" in s.impact.fallback
    assert "--djb-scope=leaf" in scope.pytest_args(s)
    assert s.canonical.endswith(" map=-")


def test_an_unreadable_map_is_the_closure_scope_and_not_exit_2(world: Path) -> None:
    (world / scope.MAP_PATH).write_text("{ not json\n")
    commit_all(world, "a broken map")
    touch(world, "apps/leaf/services.py")
    s = derive(world, asked_impact=True)
    assert s.impact.select == ""
    assert "could not be read as a map" in s.impact.fallback
    assert re.search(r" map=[0-9a-f]{12}$", s.canonical)


def test_the_map_sha_is_in_the_loop_key(world: Path) -> None:
    _plant_map(world)
    touch(world, "apps/leaf/services.py")
    before = derive(world, asked_impact=True).canonical
    _git(world, "checkout", "-q", "--", ".")
    _plant_map(world, "dropped-test")
    touch(world, "apps/leaf/services.py")
    after = derive(world, asked_impact=True).canonical
    assert before != after
    assert before.rsplit(" map=", 1)[0] == after.rsplit(" map=", 1)[0]


def test_the_valve_widens_and_keys_itself(world: Path) -> None:
    _plant_map(world)
    touch(world, "apps/leaf/services.py")
    s = derive(world, asked_impact=True, no_impact=True)
    assert (s.impact.sha, s.impact.select) == ("bypassed", "")
    assert s.canonical.endswith(" map=bypassed")
    assert "--djb-scope-narrow" in scope.pytest_args(s)


def test_mine_and_pr_do_not_consult_the_map_and_still_carry_it(world: Path) -> None:
    _plant_map(world)
    touch(world, "apps/leaf/services.py")
    for s in (derive(world, mine=True), derive(world)):
        assert s.impact.select == ""
        assert "did not ask for the map" in s.impact.fallback
        assert re.search(r" map=[0-9a-f]{12}$", s.canonical)


# --- the tier's own derivation (`test_loop_tier.sh`) ------------------------------


def test_the_default_tier_touches_nothing(world: Path, mirror: Path) -> None:
    """No change derives nothing; a flagless collection deselects nothing and prints no tier."""
    s = derive(world)
    assert (s.mode, s.own, s.changed) == ("fast", [], [])
    run = collect(mirror)
    assert run.rc == 0 and "deselected" not in run.out and "djb tier" not in run.out


def test_a_change_under_an_app_derives_that_app(world: Path) -> None:
    touch(world, "apps/leaf/services.py")
    assert derive(world).own == ["leaf"]


def test_two_apps_both_derive(world: Path) -> None:
    touch(world, "apps/leaf/services.py", "apps/aside/services.py")
    assert derive(world).own == ["aside", "leaf"]


def test_an_untracked_new_file_derives_nothing_until_it_is_staged(world: Path) -> None:
    (world / "apps/leaf/new.py").write_text("x\n")
    assert derive(world).own == []
    _git(world, "add", "apps/leaf/new.py")
    assert derive(world).own == ["leaf"]


def test_a_committed_change_on_a_branch_derives_too(world: Path) -> None:
    _git(world, "checkout", "-q", "-b", "rung")
    touch(world, "apps/aside/services.py")
    commit_all(world, "committed on the rung")
    s = derive(world)
    assert s.own == ["aside"]
    assert "committed on 'rung'" in s.basis


def test_a_system_layer_rung_derives_no_own_app(world: Path) -> None:
    touch(world, "quality/rules.yaml", "README.md")
    s = derive(world)
    assert (s.mode, s.own) == ("fast", [])


#: A product tree's own apps, as the partition would name them in the world.
PRODUCT_APPS = ("apps/aside", "apps/leaf", "apps/mid")


@pytest.fixture
def product(world: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The world with a drawer that declares a namespace: a product tree."""
    from quality.djb.legs import gate_tests

    (world / "quality/local").mkdir(parents=True)
    (world / "quality/local/rules.yaml").write_text("rule_id_namespace: acme\n")
    commit_all(world, "the drawer")
    monkeypatch.setattr(gate_tests, "product_apps", lambda root: PRODUCT_APPS)
    return world


@pytest.mark.parametrize("mapped", [False, True], ids=["no-map", "map"])
def test_a_product_trees_loop_runs_its_changed_app_and_no_platform_test(
    product: Path, mapped: bool
) -> None:
    if mapped:
        _plant_map(product)
    touch(product, "apps/leaf/services.py")
    s = derive(product, asked_impact=True)
    assert loop_pytest.tier_args(s) == ["apps/leaf"]
    assert s.canonical.startswith("mode=product own=leaf scope=apps/leaf ")


@pytest.mark.parametrize("path", ["frontend/src/app.tsx", "config/settings.py"])
def test_a_product_change_outside_its_apps_runs_all_of_its_apps_never_the_suite(
    product: Path, path: str
) -> None:
    touch(product, path)
    assert loop_pytest.tier_args(derive(product)) == list(PRODUCT_APPS)


def test_the_drawer_the_stdlib_floor_looks_for_is_the_engines() -> None:
    from quality.djb import boundary

    assert scope.DRAWER == boundary.DRAWER


def test_a_product_prs_pytest_args_are_its_changed_apps_and_mint_no_counts(
    product: Path,
) -> None:
    touch(product, "apps/leaf/services.py")
    commit_all(product, "the change")
    assert scope.pytest_args(derive(product, base_ref="HEAD~1")) == ["apps/leaf"]
    assert modes.pr_scope(product, "HEAD~1") == ("apps/leaf", "")


def test_a_drawer_whose_reader_cannot_import_is_exit_2(
    product: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from quality.djb.legs import gate_tests

    def unreadable(root: Path) -> str | None:
        raise ImportError("No module named 'yaml'")

    monkeypatch.setattr(gate_tests, "product_of", unreadable)
    touch(product, "apps/leaf/services.py")
    with pytest.raises(CouldNotLook, match="cannot import its reader"):
        derive(product)


def test_the_template_tree_derives_no_product_targets(world: Path) -> None:
    touch(world, "apps/leaf/services.py")
    s = derive(world)
    assert s.product is None and loop_pytest.tier_args(s)[0] == "--djb-tier=fast"


def _shared_change(world: Path, path: str) -> None:
    """One shared shape of `test_loop_tier.sh`: the full suite, no own app."""
    target = world / path
    if not target.exists():
        target.write_text("base\n")
        commit_all(world, f"{path}, in the base")
    touch(world, path)
    s = derive(world)
    assert (s.mode, s.own) == ("full", []), path


def test_a_shared_conftest_change_runs_the_full_suite(world: Path) -> None:
    _shared_change(world, "apps/conftest.py")


def test_a_root_conftest_change_runs_the_full_suite(world: Path) -> None:
    _shared_change(world, "conftest.py")


def test_a_conftest_outside_apps_runs_the_full_suite(world: Path) -> None:
    _shared_change(world, "config/conftest.py")


def test_an_apps_root_test_module_runs_the_full_suite(world: Path) -> None:
    _shared_change(world, "apps/test_root.py")


def test_a_gate_drive_change_runs_the_full_suite(world: Path) -> None:
    _shared_change(world, "scripts/tests/test_thing.sh")


def test_an_apps_own_conftest_is_not_shared(world: Path) -> None:
    touch(world, "apps/mid/tests/conftest.py")
    assert derive(world).mode == "fast"


def test_shared_infra_outranks_an_app_change(world: Path) -> None:
    touch(world, "apps/conftest.py", "apps/leaf/services.py")
    s = derive(world)
    assert (s.mode, s.own) == ("full", [])


def test_an_app_change_alone_still_gets_the_fast_tier(world: Path) -> None:
    touch(world, "apps/leaf/services.py")
    assert derive(world).mode == "fast"


def test_no_git_is_could_not_look(scratch: Path) -> None:
    with pytest.raises(CouldNotLook):
        derive(scratch)


# --- the always-on block, the declared censuses, the canonical inputs ----------


def _harness(root: Path, block: str, marker_line: str = "") -> None:
    (root / "apps/testing").mkdir(parents=True, exist_ok=True)
    (root / "apps/testing/tier.py").write_text(
        f"# >>> always-on-derivation >>>\n{block}\n# <<< always-on-derivation <<<\n{marker_line}\n"
    )
    commit_all(root, "the harness")


def test_the_always_digest_moves_with_the_rule_not_with_a_marker(world: Path) -> None:
    """A byte inside the block moves the digest; a byte outside it does not."""
    _harness(world, "RULE = 1")
    first = scope.harness_digest(world)
    _harness(world, "RULE = 1", "OUTSIDE = 2")
    assert scope.harness_digest(world) == first
    _harness(world, "RULE = 2")
    assert scope.harness_digest(world) != first


def test_a_harness_module_edit_moves_the_digest_like_the_conftest_does(world: Path) -> None:
    """SCF.5: the population is every tracked `apps/testing/*.py`, derived by git, never typed."""
    _harness(world, "RULE = 1")
    first = scope.harness_digest(world)
    (world / "apps/testing/fixtures.py").write_text(
        "# >>> always-on-derivation >>>\nMORE = 1\n# <<< always-on-derivation <<<\n"
    )
    assert scope.harness_digest(world) == first
    _git(world, "add", "apps/testing/fixtures.py")
    assert scope.harness_digest(world) != first
    assert [p.name for p in scope.harness_files(world)] == ["conftest.py", "fixtures.py", "tier.py"]


def test_the_sentinels_are_read_from_the_module_that_carries_them() -> None:
    """SCF.5: the block's begin and end lines are read from the harness, never re-typed here."""
    marks = scope.sentinels(scope.harness_files(HOME))
    assert marks is not None
    begin, end = marks
    source = (HOME / "quality/djb/scope.py").read_text()
    assert begin not in source and end not in source
    assert any(begin in p.read_text() for p in scope.harness_files(HOME))


def test_an_undeclared_block_is_undeclared(world: Path) -> None:
    assert scope.harness_digest(world) == "UNDECLARED"


def test_a_declared_population_reaches_the_banner_and_an_empty_one_refuses(world: Path) -> None:
    folder = world / "apps/core/tests"
    (folder / "test_walker.py").write_text(
        f"{scope.CENSUS_MARKER} population=apps/** walks alpha\n"
    )
    rows = scope.declared_censuses(world)
    assert rows == [("apps/core/tests/test_walker.py", "population=apps/** walks alpha")]
    (folder / "test_walker.py").write_text(f"{scope.CENSUS_MARKER} population= walks alpha\n")
    with pytest.raises(CouldNotLook, match="EMPTY POPULATION"):
        scope.declared_censuses(world)
    (folder / "test_walker.py").write_text(f"{scope.CENSUS_MARKER}\n")
    with pytest.raises(CouldNotLook, match="NO REASON"):
        scope.declared_censuses(world)


def test_the_canonical_scope_carries_the_always_on_inputs(world: Path) -> None:
    """A marked drive and the walls table both move `alwayson=`; an unmarked drive does not."""
    touch(world, "apps/leaf/services.py")
    first = derive(world).canonical
    (world / "scripts/tests/test_other.sh").write_text("#!/usr/bin/env bash\n")
    assert derive(world).canonical == first
    (world / "scripts/tests/test_census.sh").write_text(
        f"{scope.CENSUS_MARKER} walks every script\n"
    )
    marked = derive(world).canonical
    assert marked != first
    (world / "scripts/gate_member_durations.json").write_text(
        json.dumps({"measured_at": "2026-10-06", "machine": "darwin", "members": {"census": 3}})
    )
    assert derive(world).canonical != marked


# --- the loop key, its environment fingerprint, reuse across a docs-only delta -------------------

ENV_SHELL = (
    '. "$1/scripts/gate_refuse.sh"; . "$1/scripts/gate_ledger.sh"; fp=$(loop_env_fingerprint)'
    ' || exit 3; loop_env_fingerprint >/dev/null; printf "%s\\n%s\\n" "$fp" "$LOOP_ENV_COMPONENTS";'
    ' loop_ledger_key "$2" "$3"'
)


@pytest.fixture
def env_world(scratch_repo: Callable[..., Path]) -> Path:
    """A checkout with a fenced derived key, a `.env`, three dists and a read-set file."""
    root = scratch_repo("envworld", "loop env")
    site = root / ".venv/lib/python3.12/site-packages"
    for dist in ("aiohttp_retry-2.9.1", "aiohttp-3.14.3", "Zope-1.0"):
        (site / f"{dist}.dist-info").mkdir(parents=True)
    (root / ".venv/lib/python3.12/site-packages/deep/deeper").mkdir(parents=True)
    (root / ".venv/lib/python3.12/site-packages/deep/deeper/hidden-1.dist-info").mkdir()
    (root / "scripts").mkdir()
    begin, end = scope.ENV_DECL
    (root / "scripts/db.sh").write_text(
        f"{begin}\n# DATABASE_NAME — derived per checkout\n# NOTANAME derived\n{end}\n"
    )
    (root / ".env").write_text(
        'DATABASE_NAME=djb_x\nZZ_PLANTED_SECRET="abc"\n# A=1\nZZ_PLANTED_PLAIN = two words \n'
    )
    (root / "reads.txt").write_text("ZZ_PLANTED_SECRET\nZZ_PLANTED_PLAIN\nZZ_PLANTED_NEVER\n")
    (root / "kept.txt").write_text("base\n")
    _git(root, "add", "kept.txt", "scripts/db.sh")
    _git(root, "commit", "-q", "-m", "base")
    return root


def test_the_env_fingerprint_and_the_loop_key_equal_the_shells_byte_for_byte(
    env_world: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tree = _git(env_world, "rev-parse", "HEAD^{tree}")
    canonical = "mode=fast own=- scope=- always=x tests=- seeded=- alwayson=y map=-"
    reads = str(env_world / "reads.txt")
    done = subprocess.run(
        ["bash", "-c", ENV_SHELL, "_", str(HOME), tree, canonical],
        cwd=env_world,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C", "DJB_LOOP_ENV_READS": reads},
    )
    assert done.returncode == 0, done.stderr
    from quality.djb import ledger

    for name in ("ZZ_PLANTED_SECRET", "ZZ_PLANTED_PLAIN", "ZZ_PLANTED_NEVER"):
        monkeypatch.delenv(name, raising=False)
    print_ = scope.env_fingerprint(env_world, reads)
    key = ledger.loop_key(ledger.loop_key_tree(env_world, tree), print_.digest, canonical)
    assert f"{print_.digest}\n{print_.components}\n{key}\n" == done.stdout
    assert "excluded=DATABASE_NAME " in print_.components


def test_the_dists_are_sorted_by_bytes_never_by_locale(env_world: Path) -> None:
    assert scope._dists(env_world) == [
        "Zope-1.0.dist-info",
        "aiohttp-3.14.3.dist-info",
        "aiohttp_retry-2.9.1.dist-info",
    ]


def test_zero_dists_is_could_not_look_never_an_empty_environment(env_world: Path) -> None:
    import shutil

    shutil.rmtree(env_world / ".venv")
    with pytest.raises(CouldNotLook, match="Zero distributions is a read that did not answer"):
        scope.env_fingerprint(env_world, str(env_world / "reads.txt"))


def test_a_symlinked_venv_is_not_walked_as_the_shells_find_does_not(env_world: Path) -> None:
    (env_world / ".venv").rename(env_world / "real-venv")
    (env_world / ".venv").symlink_to(env_world / "real-venv")
    with pytest.raises(CouldNotLook, match="Zero distributions"):
        scope.env_fingerprint(env_world, str(env_world / "reads.txt"))


def test_an_empty_read_set_is_could_not_look(env_world: Path) -> None:
    (env_world / "reads.txt").write_text("")
    with pytest.raises(CouldNotLook, match="read-set is empty"):
        scope.env_reads(env_world, str(env_world / "reads.txt"))


def _basis(root: Path) -> str:
    from quality.djb import ledger

    head = _git(root, "rev-parse", "HEAD")
    return f"tree={ledger.measured_tree_of(root, head)} env=e scope=s head={head} merge-base=m"


@pytest.fixture
def reuse_world(scratch_repo: Callable[..., Path]) -> tuple[Path, str]:
    """A banked basis at HEAD, then one docs-only commit on top of it."""
    root = scratch_repo("reuse", "loop reuse")
    (root / "apps/mid").mkdir(parents=True)
    (root / "apps/mid/services.py").write_text("X = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    basis = _basis(root)
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "docs")
    return root, basis


def test_loop_reuses_pytest_across_a_docs_only_delta_from_an_ancestor_head(
    reuse_world: tuple[Path, str],
) -> None:
    root, basis = reuse_world
    got = scope.loop_reuse(root, basis)
    assert (got.tree, got.count, got.why) == (scope._component(basis, "tree"), 1, "")


def test_a_dirty_tree_is_measured_and_says_why(reuse_world: tuple[Path, str]) -> None:
    root, basis = reuse_world
    (root / "apps/mid/services.py").write_text("X = 2\n")
    got = scope.loop_reuse(root, basis)
    assert not got.tree and "the WORKING TREE is not clean" in got.why


def test_a_code_delta_is_never_reused(reuse_world: tuple[Path, str]) -> None:
    root, basis = reuse_world
    (root / "apps/mid/services.py").write_text("X = 3\n")
    _git(root, "commit", "-q", "-am", "code")
    assert scope.loop_reuse(root, basis) == scope.Reuse()


def test_a_docs_path_an_app_module_spells_is_measured(scratch_repo: Callable[..., Path]) -> None:
    root = scratch_repo("reuse-spelled", "loop reuse")
    (root / "apps/mid").mkdir(parents=True)
    (root / "apps/mid/reader.py").write_text('GUIDE = "' + "docs/" + 'guide.md"\n')
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "base")
    basis = _basis(root)
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "docs")
    assert scope.loop_reuse(root, basis).why == (
        "docs-only delta touches a path spelled in a module under apps/: "
        + "docs/"
        + "guide.md (named in apps/mid/reader.py) — measuring"
    )


def test_a_basis_whose_tree_is_not_its_heads_is_measured(reuse_world: tuple[Path, str]) -> None:
    root, basis = reuse_world
    forged = basis.replace(scope._component(basis, "tree"), "0" * 40)
    assert "not its head's measured tree" in scope.loop_reuse(root, forged).why


# --- the always-on set, and its two layers of floors (a real collection) --------

#: One fast test every collection can be cut down to by keyword, the drive's `-k`.
ONE_TEST = "test_the_namer_unwraps_and_never_reaches_for_repr"
DRAWER = "apps/conftest_local.py"
#: What a nested collection must not inherit from the run that starts it.
_STRIPPED = ("PYTEST_", "DJB_GATE_", "DJB_LOOP_", "DJB_DRIVE_")


def _lend_venv(dest: Path) -> None:
    """This checkout's interpreter in `dest/.venv/`, a directory `.gitignore` already ignores."""
    venv = dest / ".venv"
    venv.mkdir()
    for part in ("bin", "lib"):
        (venv / part).symlink_to(HOME / ".venv" / part)
    shutil.copy(HOME / ".venv/pyvenv.cfg", venv / "pyvenv.cfg")


@pytest.fixture(scope="module")
def mirror(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A detached worktree of HEAD in scratch with this checkout's `.env` and `.venv`."""
    dest = require_scratch(tmp_path_factory.mktemp("mirror"), HOME) / "checkout"
    add_checkout(HOME, dest)
    if (HOME / ".env").is_file():
        shutil.copy(HOME / ".env", dest / ".env")
    _lend_venv(dest)
    yield dest
    remove_checkout(HOME, dest)


@dataclass(frozen=True)
class Run:
    """One nested pytest run: its exit and its whole output."""

    rc: int
    out: str

    def count(self) -> int:
        """`679/3409 tests collected` → 679; `3409 tests collected` → 3409."""
        found = re.findall(r"^(\d+)(?:/\d+)? tests? collected", self.out, re.MULTILINE)
        if not found:
            raise CouldNotLook(f"no `tests collected` line in a run that exited {self.rc}")
        return int(found[-1])


_NESTED_RUNS = itertools.count(1)


def nested_database_name(base: str) -> str:
    """A database name of this process's own for one nested run: `<base>_nested<pid>_<n>`."""
    return f"{(base or 'djb')[:32]}_nested{os.getpid()}_{next(_NESTED_RUNS)}"


def pytest_in(where: Path, *argv: str, env: dict[str, str] | None = None) -> Run:
    """`python -m pytest -p no:randomly <argv>` in `where`, its output to a scratch file."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)}
    # Invariant: a nested run's test databases never share a name with the outer run's workers.
    clean["DATABASE_NAME"] = nested_database_name(clean.get("DATABASE_NAME", ""))
    sink = where.parent / f"run-{len(list(where.parent.glob('run-*.out'))) + 1}.out"
    with sink.open("wb") as out:
        done = subprocess.run(
            [sys.executable, "-m", "pytest", "-p", "no:randomly", *argv],
            cwd=where,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**clean, **(env or {})},
        )
    text = sink.read_text(errors="replace")
    if not text:
        raise CouldNotLook(f"pytest {' '.join(argv)} exited {done.returncode} and printed nothing")
    return Run(done.returncode, text)


def test_two_nested_runs_in_one_process_get_distinct_database_names() -> None:
    first, second = nested_database_name("djb_main_abc"), nested_database_name("djb_main_abc")
    assert first != second
    assert first.startswith(f"djb_main_abc_nested{os.getpid()}_")
    assert len(f"test_{first}_gw15") <= 63


def test_a_nested_run_is_handed_its_own_database_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`pytest_in` hands the nested run the name; severing the wiring leaves the outer one."""
    seen: dict[str, str] = {}

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[bytes]:
        seen.update(kw["env"])
        kw["stdout"].write(b"1 test collected\n")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setenv("DATABASE_NAME", "djb_outer")
    monkeypatch.setattr(subprocess, "run", run)
    (tmp_path / "w").mkdir()
    assert pytest_in(tmp_path / "w", "--collect-only").count() == 1
    assert seen["DATABASE_NAME"].startswith(f"djb_outer_nested{os.getpid()}_")


def collect(where: Path, *flags: str) -> Run:
    """The whole suite collected at `flags`, as the drive's `collect_scope` does."""
    return pytest_in(where, "--collect-only", "-q", *flags)


@contextmanager
def planted(where: Path, rel: str, text: str) -> Iterator[Path]:
    """`text` at `rel` (appended when it exists), the bytes put back on the way out."""
    path = where / rel
    before = path.read_bytes() if path.exists() else None
    if path.exists():
        path.write_text(path.read_text() + text)
    else:
        path.write_text(text)
    try:
        yield path
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(before)


@contextmanager
def moved_aside(where: Path, rel: str) -> Iterator[None]:
    """`rel` moved out of the tree for the block, put back on the way out."""
    path = where / rel
    if not path.is_file():
        raise CouldNotLook(f"{rel} is gone — the member this case moves aside")
    hidden = where.parent / f"aside-{path.name}"
    path.rename(hidden)
    try:
        yield
    finally:
        hidden.rename(path)


ROOT_MEMBER = (
    "\nDJB_POPULATION_FLOOR_MEMBERS = {\n"
    '    **globals().get("DJB_POPULATION_FLOOR_MEMBERS", {}),\n'
    '    "apps_root_modules": (*globals().get("DJB_POPULATION_FLOOR_MEMBERS", {})'
    '.get("apps_root_modules", ()), "{path}"),\n'
    "}\n"
)
ROOT_MODULE = '"""A planted apps-root module."""\n\n\ndef test_{name}() -> None:\n    assert True\n'


def _root_member(path: str) -> str:
    return ROOT_MEMBER.replace("{path}", path)


def _root_module(name: str) -> str:
    return ROOT_MODULE.replace("{name}", name)


NARROW = ("--djb-tier=fast", "--djb-scope-narrow")


def test_the_floors_refuse_when_the_cross_app_derivation_returns_nothing(mirror: Path) -> None:
    """Every reach kind severed: both layers refuse, exit 4, before anything is deselected."""
    tier = mirror / "apps/testing/tier.py"
    source = tier.read_text()
    block = re.search(r"^DJB_REACH_TOKENS: .*?^\}$", source, re.MULTILINE | re.DOTALL)
    if block is None:
        raise CouldNotLook("apps/testing/tier.py declares no DJB_REACH_TOKENS block")
    severed = re.sub(r'^(    "\w+": )\(.*\),$', r'\1("__severed__",),', block.group(0), flags=re.M)
    assert severed != block.group(0)
    tier.write_text(source.replace(block.group(0), severed))
    try:
        run = collect(mirror, *NARROW)
    finally:
        tier.write_text(source)
    assert run.rc == 4, run.out[-2000:]
    for phrase in ("LAYER 1 (reach kind)", "LAYER 2 (named population)", "NOTHING was deselected"):
        assert phrase in run.out


def test_a_floor_member_moved_aside_is_a_refusal(mirror: Path) -> None:
    """One member of one population gone reds layer 2 while every layer-1 kind still holds."""
    with moved_aside(mirror, "apps/test_absent_world.py"):
        run = collect(mirror, *NARROW)
    assert run.rc == 4, run.out[-2000:]
    assert "apps_root_modules" in run.out
    assert (
        "declared but not collected: apps/test_absent_world.py (the tree has no such file)"
        in run.out
    )
    assert "LAYER 1 (reach kind)" not in run.out


def test_a_drawer_raised_floor_refuses_a_member_moved_aside_on_a_six_module_tree(
    mirror: Path,
) -> None:
    """A product's extra root module plus its drawer addend: one moved aside is still refused."""
    addend = (
        "\nDJB_POPULATION_FLOOR_ADDENDS = {\n"
        '    **globals().get("DJB_POPULATION_FLOOR_ADDENDS", {}),\n'
        '    "apps_root_modules": globals().get("DJB_POPULATION_FLOOR_ADDENDS", {})'
        '.get("apps_root_modules", 0) + 1,\n'
        "}\n"
    )
    with (
        planted(mirror, "apps/test_zzz_probe_floor.py", _root_module("zzz_probe_floor")),
        planted(mirror, DRAWER, addend),
        moved_aside(mirror, "apps/test_absent_world.py"),
    ):
        run = collect(mirror, *NARROW)
    assert run.rc == 4, run.out[-2000:]
    assert "declared but not collected: apps/test_absent_world.py" in run.out
    assert re.search(
        r"apps_root_modules \(floor \d+ = \d+ in apps/testing/tier\.py \+ \d+ in "
        r"apps/conftest_local\.py",
        run.out,
    )


# --- the floor is an EQUALITY, and the apps root is declared by member ------------


def _floor_numbers(out: str) -> tuple[int, int]:
    found = re.search(
        r"apps_root_modules \(floor (\d+) in apps/testing/tier\.py, derived (\d+) module", out
    )
    if found is None:
        raise CouldNotLook("the refusal names no apps_root_modules floor and derived count")
    return int(found.group(1)), int(found.group(2))


def test_a_member_above_the_floor_is_a_refusal_naming_it(mirror: Path) -> None:
    """An undeclared seventh root module reds narrowed and whole; a path-narrowed run does not."""
    plant = "apps/test_zzz_seventh.py"
    with planted(mirror, plant, _root_module("zzz_seventh")):
        narrowed = collect(mirror, *NARROW)
        whole = collect(mirror)
        by_path = collect(mirror, plant, "apps/core/tests")
    assert narrowed.rc == 4, narrowed.out[-2000:]
    floor, derived = _floor_numbers(narrowed.out)
    assert derived == floor + 1
    for phrase in (
        "LAYER 2 (named population)",
        "ABOVE its declaration",
        f"not declared: {plant}",
        "apps/test_absent_world.py, apps/test_census_markers.py",
        "DJB_POPULATION_FLOOR_MEMBERS / DJB_POPULATION_FLOOR_ADDENDS in apps/conftest_local.py",
    ):
        assert phrase in narrowed.out
    assert whole.rc == 4 and f"not declared: {plant}" in whole.out
    assert by_path.rc == 0, by_path.out[-2000:]


def test_the_drawers_member_declaration_lifts_it(mirror: Path) -> None:
    """The product's road: the drawer names the seventh member and both branches hold."""
    plant = "apps/test_zzz_seventh.py"
    with (
        planted(mirror, plant, _root_module("zzz_seventh")),
        planted(mirror, DRAWER, _root_member(plant)),
    ):
        narrowed = collect(mirror, *NARROW)
        whole = collect(mirror)
    assert narrowed.rc == 0, narrowed.out[-2000:]
    assert whole.rc == 0, whole.out[-2000:]


def test_a_declared_member_absent_from_the_tree_is_a_refusal_naming_the_file(
    mirror: Path,
) -> None:
    """A declared member the tree lacks is named; members for a counted population are refused."""
    with planted(mirror, DRAWER, _root_member("apps/test_zzz_ghost.py")):
        ghost = collect(mirror, *NARROW)
    assert ghost.rc == 4, ghost.out[-2000:]
    found = re.search(
        r"apps_root_modules \(floor (\d+) = (\d+) in apps/testing/tier\.py \+ 1 in "
        r"apps/conftest_local\.py, derived (\d+) module",
        ghost.out,
    )
    assert found and int(found.group(1)) == int(found.group(2)) + 1 == int(found.group(3)) + 1
    assert (
        "declared but not collected: apps/test_zzz_ghost.py (the tree has no such file)"
        in ghost.out
    )
    counted_ = (
        '\nDJB_POPULATION_FLOOR_MEMBERS = {"door_parity_census": ("apps/core/tests/test_x.py",)}\n'
    )
    with planted(mirror, DRAWER, counted_):
        by_count = collect(mirror, *NARROW)
    assert by_count.rc == 4 and "does not declare by member" in by_count.out


# --- the always-on LEG's third source: the drives a shell change reaches ---------


def _members(where: Path, **declared: str) -> list[tuple[str, Path]]:
    """A planted member set: one drive per name, each declaring the one path given."""
    where.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, path in declared.items():
        drive = where / f"test_{name}.sh"
        drive.write_text(f"#!/bin/sh\n# drives: {path}\necho planted member {name}\nexit 0\n")
        rows.append((name, drive))
    return rows


def _leg_ctx(**env: str) -> R.Ctx:
    return R.Ctx(HOME, "loop", env)


def test_a_shell_change_selects_the_drives_that_declare_it(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """The touched drive is selected and said, the untouched one not; an uncovered file says 0."""
    rows = _members(
        scratch / "set",
        reach="scripts/kill_mine.sh",
        aside="scripts/queue_cited.sh",
        sweep="scripts/db.sh",
    )
    ctx = _leg_ctx(DJB_SELFTEST_DRIVES_DIR=str(scratch / "set"))
    picked = ao.touched(ctx, rows, ["scripts/kill_mine.sh", "apps/example/api.py"], [], [])
    said = capfd.readouterr().out
    assert picked == ["reach"]
    assert "always-on (touched): 1 drives cover scripts/kill_mine.sh" in said
    assert "always-on (touched): reach: touched: scripts/kill_mine.sh" in said
    assert "aside: touched" not in said
    assert ao.touched(ctx, rows, ["scripts/secrets_scan.sh"], [], []) == []
    assert "always-on (touched): 0 drives cover scripts/secrets_scan.sh" in capfd.readouterr().out


#: Each narrowed harness module, and one path its narrowed glob still names.
HARNESS_READS = {
    "quality/tests/test_backup.py": "apps/example/migrations/0001_initial.py",
    "quality/tests/test_db.py": "apps/example/apps.py",
    "quality/tests/test_golden_copy.py": "apps/core/verbs.py",
    "quality/tests/test_runbook.py": "apps/example/migrations/0001_initial.py",
    "quality/tests/test_scope.py": "apps/testing/tier.py",
    "quality/tests/test_shards.py": "apps/example/tests/test_api.py",
}


def test_a_product_apps_code_change_selects_none_of_the_narrowed_harness_modules() -> None:
    """A selector edit reaches no harness module; each still answers to a path it does read."""
    picked = scope.touched(HOME, ["apps/example_portal/selectors.py"])
    assert [m for m in HARNESS_READS if m in picked] == []
    for module, path in HARNESS_READS.items():
        assert module in scope.touched(HOME, [path]), (module, path)


def test_the_reap_module_is_selected_on_any_shell_change() -> None:
    """The shell-change floor is `test_reap.py`'s drives marker; apps alone selects it never."""
    reap = "quality/tests/test_reap.py"
    for changed in ("scripts/serve.sh", "deploy/lib.sh", "scripts/local/legs/x.sh"):
        assert reap in scope.touched(HOME, [changed]), changed
    assert reap not in scope.touched(HOME, ["apps/example/api.py"])


def test_a_fence_that_is_not_the_bare_self_case_is_a_finding(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A fence invoking its drive with a flag is a FINDING line; a bare fence is none."""
    rows = dict(_members(scratch / "set", reach="scripts/kill_mine.sh", sweep="scripts/db.sh"))
    fence = scratch / "planted-fence.sh"
    fence.write_text(
        f"# >>> drive: reach >>>\n{rows['reach']} --verb archive\n# <<< drive: reach <<<\n"
        f"# >>> drive: sweep >>>\n{rows['sweep']}\n# <<< drive: sweep <<<\n"
    )
    ctx = _leg_ctx(DJB_ALWAYS_ON_FENCE_FILE=str(fence))
    assert ao.fence_finding(ctx, "reach", rows["reach"]) == 1
    assert ao.fence_finding(ctx, "sweep", rows["sweep"]) == 0
    said = capfd.readouterr().out
    assert (
        f"touched reach: FINDING — its fence in {fence} invokes '{rows['reach']} --verb archive', "
        "which is not the bare self-case"
    ) in said
    assert "touched sweep: FINDING" not in said


# --- the door registry, the banner's ways in, and the drawer's reach kinds --------

PROBE = "zzz_probe"
EXAMPLE_ONLY = (
    "--djb-scope-narrow",
    "--djb-scope=example",
    "--djb-own-app=example",
    "--djb-changed=apps/example/api.py",
)
PARITY = "apps/core/tests/test_door_schema_parity.py"


def _platform_apps() -> list[str]:
    text = (HOME / "quality/partition.yaml").read_text()
    block = re.search(r"^platform_apps:\n((?:[ \t]*(?:- .*|#.*)?\n)*)", text, re.MULTILINE)
    if block is None:
        raise CouldNotLook("quality/partition.yaml declares no platform_apps")
    return re.findall(r"^[ \t]*- (\S+)", block.group(1), re.MULTILINE)


@contextmanager
def probe_app(where: Path, module: str, text: str) -> Iterator[Path]:
    """A throwaway PRODUCT app `apps/zzz_probe/` with one test module, removed on the way out."""
    if PROBE in _platform_apps():
        raise CouldNotLook(
            f"quality/partition.yaml lists {PROBE!r} — the probe must be a product app"
        )
    app = where / "apps" / PROBE
    if app.exists():
        raise CouldNotLook(f"apps/{PROBE} already exists in the mirror")
    (app / "tests").mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "tests/__init__.py").write_text("")
    (app / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\nclass ZzzProbeConfig(AppConfig):\n"
        f'    name = "apps.{PROBE}"\n    depends_on: tuple[str, ...] = ()\n'
    )
    (app / "tests" / module).write_text(text)
    try:
        yield app / "tests" / module
    finally:
        shutil.rmtree(app)


def _probe_collect(where: Path) -> Run:
    return collect(where, *EXAMPLE_ONLY)


def _counts_files(counts: Path) -> list[Path]:
    return sorted(p for p in counts.rglob("*") if p.is_file())


def test_an_example_only_change_keeps_the_door_schema_parity_module(
    mirror: Path, scratch: Path
) -> None:
    """The doors' parity census is kept by its derived reach kind, listed with its way in."""
    run = collect(mirror, *EXAMPLE_ONLY)
    assert run.rc == 0, run.out[-2000:]
    assert f"{PARITY}::" in run.out
    assert f"{PARITY} derived: door_registry" in run.out
    head = re.search(
        r"^  always-on: (\d+) modules ran — \d+ derived before the tier", run.out, re.M
    )
    assert head is not None
    assert " structural" in run.out and " declared" in run.out
    listed = re.findall(
        r"^    apps/\S+\.py (?:structural|derived: [a-z_,]+|declared|seeded)$", run.out, re.M
    )
    assert len(listed) == int(head.group(1))
    seeded = collect(
        mirror,
        *EXAMPLE_ONLY[:3],
        "--djb-changed-test=apps/core/tests/test_vocabulary.py",
    )
    assert seeded.rc == 0 and "apps/core/tests/test_vocabulary.py seeded" in seeded.out
    counts = scratch / "counts-door"
    counts.mkdir()
    parallel = pytest_in(
        mirror, "-q", "-n", "2", *EXAMPLE_ONLY, f"--djb-scope-counts={counts}", "-k", ONE_TEST
    )
    assert parallel.rc == 0, parallel.out[-2000:]
    assert f"scope     {PARITY} derived: door_registry" in parallel.out
    files = _counts_files(counts)
    assert len(files) >= 2
    line = f"always_on_module={PARITY} derived: door_registry"
    assert all(line in f.read_text().splitlines() for f in files)


def test_a_product_app_walking_the_door_registry_is_always_on(mirror: Path) -> None:
    """A product module walking the REST document, no marker and no seed line, is kept."""
    walker = (
        '"""A planted product census over the published REST document."""\n\n'
        "from config.api import api\n\n\n"
        "def test_every_published_path_has_an_operation() -> None:\n"
        "    document = api.get_openapi_schema()\n"
        '    assert all(document["paths"].values())\n'
    )
    addend = (
        "\nDJB_POPULATION_FLOOR_ADDENDS = {\n"
        '    **globals().get("DJB_POPULATION_FLOOR_ADDENDS", {}),\n'
        '    "openapi_document_readers": globals().get("DJB_POPULATION_FLOOR_ADDENDS", {})'
        '.get("openapi_document_readers", 0) + 1,\n'
        "}\n"
    )
    with (
        probe_app(mirror, "test_door_walk.py", walker),
        planted(mirror, DRAWER, addend),
    ):
        run = _probe_collect(mirror)
    module = f"apps/{PROBE}/tests/test_door_walk.py"
    assert run.rc == 0, run.out[-2000:]
    assert f"{module}::test_every_published_path_has_an_operation" in run.out
    assert f"{module} derived: door_registry" in run.out


def test_a_drawer_reach_kind_makes_its_reader_always_on(mirror: Path) -> None:
    """A drawer-declared registry keeps its reader; a misspelt drawer key is refused by name."""
    census = (
        '"""A planted product census over a product-owned registry."""\n\n\n'
        "def list_widgets() -> list[str]:\n"
        '    return ["a"]\n\n\n'
        "def test_every_widget_is_named() -> None:\n"
        "    assert all(list_widgets())\n"
    )
    module = f"apps/{PROBE}/tests/test_widget_census.py"
    with probe_app(mirror, "test_widget_census.py", census):
        bare = _probe_collect(mirror)
        with planted(mirror, DRAWER, '\nDJB_REACH_KINDS = {"acme_registry": ("list_widgets(",)}\n'):
            declared = _probe_collect(mirror)
        with planted(mirror, DRAWER, '\nDJB_REACH_KIND = {"acme_registry": ("list_widgets(",)}\n'):
            misspelt = _probe_collect(mirror)
    assert bare.rc == 0 and f"{module}::" not in bare.out
    assert declared.rc == 0, declared.out[-2000:]
    assert f"{module}::test_every_widget_is_named" in declared.out
    assert f"{module} derived: acme_registry" in declared.out
    assert misspelt.rc == 4 and "declares DJB_REACH_KIND, which no reader" in misspelt.out


def test_counts_field_answers_nothing_for_no_counts_file(scratch: Path) -> None:
    """The leg's counts reader answers empty for an empty or missing path, never stdin."""
    assert loop_pytest._lines("") == []
    assert loop_pytest._lines(str(scratch / "no-such-counts-file")) == []
    real = scratch / "counts-field-file"
    real.write_text("workers=2\nalways_on=5\nalways_on_modules=3\n")
    assert "always_on=5" in loop_pytest._lines(str(real))


def test_the_always_on_set_survives_the_real_parallel_invocation(
    mirror: Path, scratch: Path
) -> None:
    """Under a real `-n 2` every worker writes identical counts, and always-on is not empty."""
    counts = scratch / "counts"
    counts.mkdir()
    run = pytest_in(
        mirror, "-q", "-n", "2", *NARROW, f"--djb-scope-counts={counts}", "-k", ONE_TEST
    )
    assert run.rc == 0, run.out[-2000:]
    files = _counts_files(counts)
    assert len(files) >= 2, "a serial approximation: the workers did not each collect"
    assert len({f.read_bytes() for f in files}) == 1
    always = [ln for ln in files[0].read_text().splitlines() if ln.startswith("always_on=")]
    assert always and int(always[0].split("=", 1)[1]) > 0


def test_a_narrower_scope_selects_strictly_less_than_a_wider_one(mirror: Path) -> None:
    """An empty scope still selects the always-on set, and a scope with core selects more."""
    empty = collect(mirror, *NARROW)
    core = collect(mirror, *NARROW, "--djb-scope=core")
    assert empty.rc == 0 and core.rc == 0
    assert 0 < empty.count() < core.count()


# --- the placement rule a product's edge census rides on --------------------------

#: The `--loop --mine` arm for a core touch: what `loop_pytest.tier_args` hands pytest.
MINE_ARM = ("--djb-tier=fast", "--djb-scope-narrow", "--djb-own-app=core", "--djb-scope=core")
LEAF_ARM = (*NARROW, "--djb-own-app=files", "--djb-scope=files", "--djb-scope=exports")
PR_ARM = ("--djb-scope-narrow", "--djb-scope=files", "--djb-scope=exports")


def test_a_planted_apps_root_census_runs_at_every_scope(mirror: Path) -> None:
    """An apps-root module is selected at every scope, and removing it drops each count by one."""
    plant = "apps/test_zzz_edge.py"
    nodeid = f"{plant}::test_zzz_edge"
    shapes = {"empty": NARROW, "mine": MINE_ARM, "leaf": LEAF_ARM, "pr": PR_ARM}
    with (
        planted(mirror, plant, _root_module("zzz_edge")),
        planted(mirror, DRAWER, _root_member(plant)),
    ):
        with_ = {name: collect(mirror, *flags) for name, flags in shapes.items()}
    without = {name: collect(mirror, *flags) for name, flags in shapes.items()}
    for name in shapes:
        assert with_[name].rc == 0 and without[name].rc == 0, name
        assert nodeid in with_[name].out.splitlines(), name
        assert without[name].count() == with_[name].count() - 1, name


# --- `--loop --mine`: the own apps alone, and never a banked verdict --------------


def test_the_mine_arm_in_the_placement_case_matches_the_flags_check_sh_passes(
    mirror: Path,
) -> None:
    """The arm the placement case collects with is the mode's own assembly for a core touch."""
    with planted(mirror, "apps/core/services/__init__.py", "\n"):
        mine = scope.derive(mirror, base_ref="HEAD", mine=True)
    assert (mine.own, mine.apps) == (["core"], ["core"])
    assert not mine.impact.select
    moved = ["apps/core/services/__init__.py"]
    declared = scope.declared_censuses(mirror, *ao.CENSUS_HOME)
    census = [f"--djb-changed-test={p}" for p, d in declared if scope.census_moved(d, moved)]
    assert census and sorted(loop_pytest.tier_args(mine)) == sorted([*MINE_ARM, *census])


def test_mine_runs_own_apps_only_and_never_banks(mirror: Path, scratch: Path) -> None:
    """`--mine` subtracts the closure the ordinary loop walks, keys apart, says it banks none."""
    with planted(mirror, "apps/core/services/__init__.py", "\n"):
        mine = scope.derive(mirror, base_ref="HEAD", mine=True)
        ordinary = scope.derive(mirror, base_ref="HEAD")
    assert (mine.mode, mine.touched, mine.apps, mine.widened, mine.own) == (
        "fast",
        ["core"],
        ["core"],
        [],
        ["core"],
    )
    assert "closure NOT walked" in mine.reason
    assert "ordinary --loop" in notes(mine)
    assert ordinary.touched == ["core"] and ordinary.widened
    assert mine.canonical != ordinary.canonical and mine.canonical.startswith("mode=mine ")
    counts = scratch / "mine-counts"
    counts.mkdir()
    run = collect(mirror, *MINE_ARM, f"--djb-scope-counts={counts}")
    assert run.rc == 0, run.out[-2000:]
    files = _counts_files(counts)
    always = [ln for ln in files[0].read_text().splitlines() if ln.startswith("always_on=")]
    assert always and int(always[0].split("=", 1)[1]) > 0
    opened = "\n".join(loop.mine_banner("open", mine))
    assert "the depends_on closure was NOT walked" in opened and "not banked: --mine" in opened
    full = scope.Scope(mine=True)
    full.mode = "full"
    opened_full = "\n".join(loop.mine_banner("open", full))
    assert "the depends_on closure was NOT walked" not in opened_full
    assert "nothing was narrowed" in opened_full and "not banked: --mine" in opened_full
    assert "claim about [core]" in "\n".join(loop.mine_banner("close", mine))
    closed_full = "\n".join(loop.mine_banner("close", full))
    assert "claim about [-]" not in closed_full and "narrowed nothing" in closed_full


# --- the tests-only SELECTION, on this tree's real modules ------------------------

COMMS_EDIT = "apps/comms/tests/test_mcp.py"
COMMS_ONLY = (*NARROW, "--djb-tests-only=comms", f"--djb-changed-test={COMMS_EDIT}")


@pytest.fixture(scope="module")
def manifest(mirror: Path) -> list[tuple[str, str]]:
    """This tree's organ classification: `(tier, nodeid)` per collected item."""
    out = mirror.parent / "manifest-all.tsv"
    run = collect(mirror, f"--djb-tier-manifest={out}")
    assert run.rc == 0, run.out[-2000:]
    rows = [line.split("\t") for line in out.read_text().splitlines() if line]
    if not rows:
        raise CouldNotLook("the tier manifest came back empty — the classification is gone")
    return [(row[0], row[2]) for row in rows]


@pytest.fixture(scope="module")
def whole(mirror: Path) -> Run:
    """The whole collection, unnarrowed."""
    run = collect(mirror)
    assert run.rc == 0, run.out[-2000:]
    return run


def _naming(where: Path, dotted: str) -> list[str]:
    return sorted(
        p.relative_to(where).as_posix()
        for p in (where / "apps").rglob("*.py")
        if dotted in p.read_text(errors="replace")
    )


def _fast_module(rows: list[tuple[str, str]], module: str) -> bool:
    return any(tier == "fast" and node.startswith(f"{module}::") for tier, node in rows)


def test_a_tests_only_comms_touch_is_not_own_and_widens_to_its_importers(
    mirror: Path, manifest: list[tuple[str, str]], whole: Run
) -> None:
    """A comms test edit: not own, no closure; its fast importers in, its organ tests out."""
    with planted(mirror, COMMS_EDIT, "\n"):
        s = scope.derive(mirror, base_ref="HEAD")
    assert (s.tests_only, s.own, s.apps, s.changed_tests) == (["comms"], [], [], [COMMS_EDIT])
    only = collect(mirror, *COMMS_ONLY)
    assert only.rc == 0, only.out[-2000:]
    assert f"{COMMS_EDIT}::" in only.out
    importers = [
        m
        for m in _naming(mirror, "apps.comms.tests")
        if f"{m}::" in whole.out and _fast_module(manifest, m)
    ]
    assert len(importers) >= 2, "the importer census has emptied"
    assert [m for m in importers if f"{m}::" not in only.out] == []
    slow = [n for t, n in manifest if t == "slow" and n.startswith("apps/comms/")]
    assert slow, "no organ-reaching comms test on this tree — this half cannot falsify"
    assert [n for n in slow if n in only.out] == []
    assert only.count() < whole.count()


def test_the_edited_test_module_runs_whatever_tier_it_is_in(
    mirror: Path, manifest: list[tuple[str, str]]
) -> None:
    """An edited organ-reaching module is selected by the fast tier anyway."""
    victims = sorted(
        {n.split("::")[0] for t, n in manifest if t == "slow" and n.startswith("apps/comms/tests/")}
    )
    if not victims:
        raise CouldNotLook("no organ-reaching module under apps/comms/tests/ — the subject is gone")
    run = collect(mirror, *NARROW, "--djb-tests-only=comms", f"--djb-changed-test={victims[0]}")
    assert run.rc == 0 and f"{victims[0]}::" in run.out


def test_a_files_touch_selects_the_exports_tests_through_the_closure(mirror: Path) -> None:
    """A files touch reaches exports' tests through the reverse depends_on closure."""
    run = collect(mirror, *LEAF_ARM)
    assert run.rc == 0 and re.search(r"^apps/exports/tests/", run.out, re.M)


@pytest.fixture(scope="module")
def prerun(mirror: Path) -> tuple[Run, list[Path]]:
    """One real `-n 2 -v` run at the comms tests-only scope, with its counts files."""
    counts = mirror.parent / "prerun-counts"
    counts.mkdir()
    run = pytest_in(
        mirror, "-v", "-n", "2", *COMMS_ONLY, f"--djb-scope-counts={counts}", "-k", ONE_TEST
    )
    return run, _counts_files(counts)


def test_the_banner_prints_every_decision_before_the_first_test(
    prerun: tuple[Run, list[Path]],
) -> None:
    """The pre-run banner's selected line and its three ways in print before the first result."""
    run, _ = prerun
    assert run.rc == 0, run.out[-2000:]
    lines = run.out.splitlines()
    banner = next(i for i, ln in enumerate(lines) if "scope   selected " in ln)
    first = next(i for i, ln in enumerate(lines) if "PASSED" in ln)
    assert banner < first
    for key in ("scope   tests-only:", "scope   importers:", "scope   always-on:"):
        assert key in run.out


def test_the_pre_run_counts_agree_with_the_reconciliation(
    prerun: tuple[Run, list[Path]],
) -> None:
    """The banner's selected and deselected equal the counts files', across every collector."""
    run, files = prerun
    assert run.rc == 0 and len(files) >= 2
    fields = dict(ln.split("=", 1) for ln in files[0].read_text().splitlines() if "=" in ln)
    said = re.search(r"scope   selected (\d+) · deselected (\d+)", run.out)
    assert said is not None
    assert (said.group(1), said.group(2)) == (fields["selected"], fields["deselected"])
    assert f"reconciled across {len(files)} collectors" in run.out


# --- the importer widening, on a subject that can falsify it -----------------------


def test_a_tests_only_core_touch_widens_to_every_cross_app_importer(
    mirror: Path, manifest: list[tuple[str, str]], whole: Run
) -> None:
    """Every collected fast module outside core naming `apps.core.tests` joins a core test edit."""
    population = [
        m for m in _naming(mirror, "apps.core.tests") if not m.startswith("apps/core/tests/")
    ]
    if not population:
        raise CouldNotLook("no module outside apps/core/tests names apps.core.tests")
    edited = sorted(set(re.findall(r"^(apps/core/tests/test_[a-z_]*\.py)::", whole.out, re.M)))
    if not edited:
        raise CouldNotLook("no collected module under apps/core/tests/")
    only = collect(mirror, *NARROW, "--djb-tests-only=core", f"--djb-changed-test={edited[0]}")
    assert only.rc == 0, only.out[-2000:]
    importers = [m for m in population if f"{m}::" in whole.out and _fast_module(manifest, m)]
    assert importers
    assert [m for m in importers if f"{m}::" not in only.out] == []


# --- the pre-run banner's ABSENCE, named rather than silent -------------------------

DYING = (
    '"""A collector that dies on purpose once the other worker has reported."""\n\n'
    "import os\nimport pathlib\nimport time\n\n"
    '_victims = [v for v in os.environ.get("DJB_DRIVE_KILL_COLLECTOR", "").split(",") if v]\n'
    'if os.environ.get("PYTEST_XDIST_WORKER", "") in _victims:\n'
    '    _witness = pathlib.Path(os.environ.get("DJB_DRIVE_KILL_AFTER", "/nonexistent"))\n'
    "    _deadline = time.time() + 60\n"
    "    while not _witness.exists() and time.time() < _deadline:\n"
    "        time.sleep(0.05)\n"
    "    os._exit(1)\n\n\n"
    "def test_zzz_dying_collector_is_inert_by_default() -> None:\n"
    "    assert True\n"
)


def _reconcile(counts: Path, workers: int, capfd: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capfd.readouterr()
    rc = loop_pytest.reconcile(R.Ctx(HOME, "loop", {}), None, str(counts), workers)
    said = capfd.readouterr()
    return rc, said.out + said.err


def test_a_dying_collector_leaves_a_named_absence_not_silence(
    mirror: Path, scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """One of two collectors dies: no pre-run banner, and the leg names the absence and refuses."""
    counts = scratch / "dying-counts"
    counts.mkdir()
    plant = "apps/test_zzz_dying_collector.py"
    with planted(mirror, plant, DYING), planted(mirror, DRAWER, _root_member(plant)):
        run = pytest_in(
            mirror,
            "-q",
            "-n",
            "2",
            "--max-worker-restart=0",
            *NARROW,
            f"--djb-scope-counts={counts}",
            "-k",
            ONE_TEST,
            env={"DJB_DRIVE_KILL_COLLECTOR": "gw1", "DJB_DRIVE_KILL_AFTER": str(counts / "gw0")},
        )
    assert len(_counts_files(counts)) == 1, run.out[-2000:]
    assert "node down" in run.out
    assert "scope   selected " not in run.out
    rc, said = _reconcile(counts, 2, capfd)
    assert rc == 2
    assert "the pre-run banner did not fire (1 of 2 collectors reported)" in said
    assert (
        "1 of 2 collectors reported — a collector died and the suite that ran is not the suite "
        "that was asked for; nothing is judged"
    ) in said
    assert "No verdict is banked." in said
    whole_ = scratch / "whole-counts"
    whole_.mkdir()
    for name in ("gw0", "gw1"):
        (whole_ / name).write_text("workers=2\nselected=1\n")
    rc, said = _reconcile(whole_, 2, capfd)
    assert rc == 0 and "did not fire" not in said and "collectors reported" not in said


# --- the worker count: ONE derivation, and the documented knob honoured by it -------


def test_a_typed_slot_share_is_the_workers_number_and_no_clamp_fires(
    mirror: Path, scratch: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """A typed share below the slot's is the `-n`, said; pytest's ceiling lowers nothing."""
    monkeypatch.setenv("DJB_GATE_SLOT_WORKERS", "2")
    workers, provenance, _ = hold.worker_count(2, share=4)
    assert workers == 2 and os.environ["DJB_GATE_SLOT_WORKERS"] == "2"
    assert (
        "workers:    -n 2 (typed: DJB_GATE_SLOT_WORKERS, at or below this slot's share of 4)"
        in capfd.readouterr().out
    )
    counts = scratch / "typed-counts"
    counts.mkdir()
    run = pytest_in(
        mirror,
        "-q",
        "-n",
        str(workers),
        *NARROW,
        f"--djb-scope-counts={counts}",
        "-k",
        ONE_TEST,
        env={"DJB_GATE_SLOT_WORKERS": str(workers)},
    )
    assert run.rc == 0, run.out[-2000:]
    assert "clamped -n" not in run.out
    assert len(_counts_files(counts)) == workers
    rc, said = _reconcile(counts, workers, capfd)
    assert rc == 0 and "collectors reported" not in said


def test_a_typed_share_above_the_slot_is_refused_naming_both(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """Above the share, unreadable or zero is refused with its cause; the share itself holds."""
    for typed, cause in (
        ("5", "DJB_GATE_SLOT_WORKERS=5 is ABOVE this slot's share of 4."),
        ("99", "DJB_GATE_SLOT_WORKERS=99 is ABOVE this slot's share of 4."),
        ("two", "DJB_GATE_SLOT_WORKERS='two' is not a positive whole number."),
        ("0", "DJB_GATE_SLOT_WORKERS='0' — a pytest leg with no workers runs no suite at all."),
    ):
        monkeypatch.setenv("DJB_GATE_SLOT_WORKERS", typed)
        with pytest.raises(hold.Refused) as refused:
            hold.worker_count(2, share=4)
        said = capfd.readouterr().err
        assert refused.value.cause == cause and f"!! {cause}" in said
        if "ABOVE" in cause:
            assert "Nothing was judged: no slot was taken and no suite started." in said
    monkeypatch.setenv("DJB_GATE_SLOT_WORKERS", "4")
    assert hold.worker_count(2, share=4)[0] == 4


# --- THE BANK'S SHARE: one number, three readers ------------------------------------

#: The real run's `-n`: the bank's share is asserted on the derivation, the run is kept small.
BANK_RUN = 3


@pytest.fixture(scope="module")
def bank_run(mirror: Path) -> tuple[Run, list[Path], int]:
    """One real `-n` run with the share handed down, as the bank leg runs it."""
    counts = mirror.parent / "bank-counts"
    counts.mkdir()
    run = pytest_in(
        mirror,
        "-n",
        str(BANK_RUN),
        *NARROW,
        f"--djb-scope-counts={counts}",
        "-k",
        ONE_TEST,
        env={"DJB_GATE_SLOT_WORKERS": str(BANK_RUN)},
    )
    return run, _counts_files(counts), BANK_RUN


def test_a_bank_runs_every_slots_share_and_the_census_agrees(
    bank_run: tuple[Run, list[Path], int],
    scratch: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """The bank's `-n` is the box's cores, handed down; the collectors agree; release unsets it."""
    monkeypatch.delenv("DJB_GATE_SLOT_WORKERS", raising=False)
    box = hold.cores()
    workers, provenance, _ = hold.worker_count(2, share=box)
    assert (workers, provenance) == (box, "derived")
    assert os.environ["DJB_GATE_SLOT_WORKERS"] == str(box)
    hold.Hold("slot").release()
    assert "DJB_GATE_SLOT_WORKERS" not in os.environ
    run, files, n = bank_run
    assert run.rc == 0, run.out[-2000:]
    assert "clamped -n" not in run.out
    assert f"created: {n}/{n} workers" in run.out
    assert len(files) == n
    assert f"workers={n}" in files[0].read_text().splitlines()
    for asked in (n, n * 2):
        rc, said = _reconcile(files[0].parent, asked, capfd)
        assert rc == 0 and "collectors reported" not in said, asked


def test_a_dead_collector_under_a_bank_still_refuses(
    bank_run: tuple[Run, list[Path], int], scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """One collector file short of a bank is refused, the survivors' `workers=` naming the whole."""
    _, files, n = bank_run
    short = scratch / "bank-dead"
    short.mkdir()
    for f in files[:-1]:
        shutil.copy(f, short / f.name)
    rc, said = _reconcile(short, n, capfd)
    assert rc == 2
    assert f"{n - 1} of {n} collectors reported — a collector died" in said
    assert "No verdict is banked." in said


# --- the collector population under the gate that BANKS ------------------------------

X2_K = f"{ONE_TEST} or test_zzz_dying_collector_is_inert_by_default"


def _x2_ctx(where: Path, **extra: str) -> R.Ctx:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)}
    return R.Ctx(where, "full", {**clean, "DJB_GATE_SLOT_WORKERS": "2", **extra})


def _dying_passes(
    mirror: Path, scratch: Path, capfd: pytest.CaptureFixture[str], *flags: str
) -> tuple[int, str, Path]:
    counts = scratch / "x2-counts"
    counts.mkdir()
    ledger_ = scratch / "x2-verdicts"
    ledger_.write_text("")
    plant = "apps/test_zzz_dying_collector.py"
    ctx = _x2_ctx(
        mirror,
        DJB_GATE_LEDGER=str(ledger_),
        DJB_DRIVE_KILL_COLLECTOR="gw1",
        DJB_DRIVE_KILL_AFTER=str(counts / "gw0"),
    )
    args = ["--max-worker-restart=0", *flags, f"--djb-scope-counts={counts}", "-k", X2_K]
    capfd.readouterr()
    with planted(mirror, plant, DYING), planted(mirror, DRAWER, _root_member(plant)):
        rc = pytest_x2.passes(ctx, pytest_x2.Run.of({}), 2, 1, args, str(counts))
    said = capfd.readouterr()
    assert ledger_.read_text() == ""
    return rc, said.out + said.err, counts


def test_a_dying_collector_under_the_full_gate_leg_body_is_exit_2_and_banks_nothing(
    mirror: Path, scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A collector dead in pass 1 is could-not-look, never pytest's own status, and banks no row."""
    rc, said, _ = _dying_passes(mirror, scratch, capfd)
    assert rc == 2
    assert "1 of 2 collectors reported" in said
    assert "the two pytest passes could not be RECONCILED — see above." in said
    assert re.search(r"no tests ran|node down", said)


def test_a_dying_collector_under_pr_is_exit_2_and_writes_no_narrowed_run_note(
    mirror: Path, scratch: Path, capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `--pr` pass shape refuses the same way, says no narrowed-run note, mints no counts."""
    narrowed = ("--djb-scope-narrow", "--djb-scope=example", "--djb-own-app=example")
    rc, said, counts = _dying_passes(mirror, scratch, capfd, *narrowed)
    assert rc == 2 and "1 of 2 collectors reported" in said
    assert "no verdict recorded — narrowed run" not in said
    seen = _suite(monkeypatch, scratch, GATE_PR_COUNTS_DIR=str(counts))
    assert seen.dirs == [str(counts)]
    assert not [a for a in seen.args if a.startswith("--djb-scope-counts=")]


def test_the_full_gate_passes_write_counts_and_the_whole_suite_reconciles(
    mirror: Path, scratch: Path, whole: Run, capfd: pytest.CaptureFixture[str]
) -> None:
    """Two clean passes: identical whole-suite counts, nothing deselected, the population said."""
    counts = scratch / "full-clean-counts"
    counts.mkdir()
    args = [f"--djb-scope-counts={counts}", "-k", ONE_TEST]
    capfd.readouterr()
    rc = pytest_x2.passes(_x2_ctx(mirror), pytest_x2.Run.of({}), 2, 1, args, str(counts))
    said = capfd.readouterr().out
    assert rc == 0, said[-2000:]
    assert "pytest pass 1: green" in said and "pytest pass 2: green" in said
    files = _counts_files(counts)
    assert len(files) == 2 and len({f.read_bytes() for f in files}) == 1
    fields = dict(ln.split("=", 1) for ln in files[0].read_text().splitlines() if "=" in ln)
    assert fields["deselected"] == "0"
    assert int(fields["selected"]) == whole.count()
    banner = pytest_in(mirror, "-q", "-n", "2", f"--djb-scope-counts={counts}", "-k", ONE_TEST)
    assert banner.rc == 0
    assert "collectors: 2 of 2 reported (the whole suite)" in banner.out
    assert "scope   selected" not in banner.out


@dataclass
class _Seen:
    args: list[str]
    dirs: list[str]


def _suite(monkeypatch: pytest.MonkeyPatch, scratch: Path, rc: int = 0, **env: str) -> _Seen:
    """`pytest_x2.suite` with its slot, seed, passes and banks stubbed; what passes was handed."""
    seen = _Seen([], [])
    temp = scratch / "temp"
    temp.mkdir(exist_ok=True)
    monkeypatch.setattr(tempfile, "tempdir", str(temp))

    def passes(
        ctx: R.Ctx, run: object, workers: int, seed_: int, args: list[str], counts: str
    ) -> int:
        seen.args[:] = args
        seen.dirs.append(counts)
        return rc

    monkeypatch.setattr(pytest_x2, "slot", lambda ctx, run: hold.Hold("slot", workers=2))
    monkeypatch.setattr(pytest_x2, "seed", lambda env: 1)
    monkeypatch.setattr(pytest_x2, "split_args", lambda ctx, run: [])
    monkeypatch.setattr(pytest_x2, "passes", passes)
    monkeypatch.setattr(pytest_x2, "grants_pass", lambda *a: 0)
    monkeypatch.setattr(pytest_x2, "bank_partition", lambda *a: 0)
    decision = pytest_x2.Decision("measure", "k", (), True)
    pytest_x2.suite(R.Ctx(HOME, "full", env), pytest_x2.Run.of({}), decision)
    return seen


def test_the_full_counts_dir_is_removed_on_an_early_red(
    monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    """The counts directory the full gate mints is gone after a red pass and after a green one."""
    for rc in (1, 0):
        seen = _suite(monkeypatch, scratch, rc=rc)
        made = [d for d in seen.dirs if d]
        assert made and "--djb-scope-counts=" + made[-1] in seen.args
        assert not Path(made[-1]).exists(), f"the counts directory outlived a pass that exited {rc}"


# --- the inner loop: the cache, the first screen, and the worker ceiling -------------

GRANTS_TARGET = (
    "apps/example/tests/test_api.py::test_authenticated_create_returns_201_and_owns_the_row"
)
LEDGER_UPDATE = '    WidgetEntry.objects.filter(widget_id=widget.pk).update(note="")\n'


def _before_return(source: str, lines: str) -> str:
    """`lines` inserted above `create_widget`'s first `return`."""
    head, sep, tail = source.partition("\ndef create_widget(")
    body, ret, rest = tail.partition("\n    return ")
    if not sep or not ret:
        raise CouldNotLook("create_widget has no return line this case can find")
    return f"{head}{sep}{body}\n{lines.rstrip(chr(10))}{ret}{rest}"


def _grants(where: Path) -> tuple[int, str]:
    ctx = R.Ctx(
        where,
        "full",
        {
            **{k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)},
            "DJB_GATE_SLOT_WORKERS": "1",
        },
    )
    assert isinstance(ctx.env, dict)
    ctx.env.pop("CI", None)
    if (where / ".env").is_file():
        # Invariant: the mirror's `.env` names its database when it has one; a runner's does not.
        ctx.env.pop("DATABASE_NAME", None)
    with tempfile.TemporaryFile("w+") as out:
        saved = sys.stdout
        sys.stdout = out
        try:
            rc = pytest_x2.grants_pass(ctx, pytest_x2.Run.of({}), 1, 1, [GRANTS_TARGET])
        finally:
            sys.stdout = saved
        out.seek(0)
        return rc, out.read()


#: What a server says when this world's user may not make the least-privilege role.
ROLE_REFUSED = ("permission denied to create role", "must have createrole")


def _skip_where_the_role_is_refused(rc: int, said: str) -> None:
    """An environment skip, never a red: the server would not let this user make the role."""
    if rc == 2 and any(words in said.lower() for words in ROLE_REFUSED):
        pytest.skip(f"environment: the least-privilege role could not be made here — {said[-300:]}")


def test_the_grants_pass_reds_a_planted_ledger_update_at_the_wire(
    mirror: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A product write to a ledger is green as the owner and red, named, under the grants."""
    services = mirror / "apps/example/services.py"
    source = services.read_text()
    probe = mirror / "apps/core/zz_probe.py"
    try:
        services.write_text(_before_return(source, LEDGER_UPDATE))
        owner = pytest_in(mirror, "-n", "1", GRANTS_TARGET)
        assert owner.rc == 0, owner.out[-2000:]
        rc, said = _grants(mirror)
        said += capfd.readouterr().err
        _skip_where_the_role_is_refused(rc, said)
        assert rc == 1, said[-2000:]
        assert "THE GRANTS PASS IS RED" in said and "example_widgetentry" in said
        services.write_text(source)
        rc, said = _grants(mirror)
        assert rc == 0 and "grants pass: green" in said, said[-2000:]
        probe.write_text(
            '"""A scratch helper that writes to a ledger."""\n\n\n'
            "def zz_touch(widget_pk: int) -> None:\n"
            "    from apps.example.models import WidgetEntry\n\n"
            '    WidgetEntry.objects.filter(widget_id=widget_pk).update(note="")\n'
        )
        services.write_text(
            _before_return(
                source, "    from apps.core.zz_probe import zz_touch\n\n    zz_touch(widget.pk)\n"
            )
        )
        rc, said = _grants(mirror)
        said += capfd.readouterr().err
        assert rc == 1, said[-2000:]
        assert "via apps/core/zz_probe.py:" in said
        assert "(called from apps/example/services.py:" in said
    finally:
        services.write_text(source)
        probe.unlink(missing_ok=True)


LAST_FAILED = (
    '"""One failure and one pass, so `--lf` has something to narrow to."""\n\n\n'
    "def test_zzz_last_failed_is_the_one_that_fails() -> None:\n"
    '    assert False, "the subject of the --lf case"\n\n\n'
    "def test_zzz_last_failed_is_the_one_that_passes() -> None:\n"
    "    assert True\n"
)


def test_last_failed_reruns_only_the_failure(mirror: Path, scratch: Path) -> None:
    """The cache plugin is loaded, so `--lf` collects the failure and not the pass."""
    plant = "apps/test_zzz_last_failed.py"
    cache = f"cache_dir={scratch / 'lf-cache'}"
    with planted(mirror, plant, LAST_FAILED):
        first = pytest_in(mirror, "-q", "-o", cache, plant)
        again = pytest_in(mirror, "-q", "-o", cache, "--lf", "--collect-only", plant)
    assert first.rc == 1
    assert (scratch / "lf-cache/v/cache/lastfailed").is_file()
    assert again.rc == 0
    assert "test_zzz_last_failed_is_the_one_that_fails" in again.out
    assert "test_zzz_last_failed_is_the_one_that_passes" not in again.out


def test_the_cache_directory_cannot_move_a_verdict_key(mirror: Path) -> None:
    """The cache plugin stays loaded, `.pytest_cache/` is ignored, and its files move no tree."""
    addopts = re.search(r"^addopts = .*$", (HOME / "pyproject.toml").read_text(), re.M)
    assert addopts is not None and "no:cacheprovider" not in addopts.group(0)
    ignored = subprocess.run(["git", "-C", str(mirror), "check-ignore", "-q", ".pytest_cache/"])
    assert ignored.returncode == 0
    before = ledger.measured_tree(mirror)
    probe = mirror / ".pytest_cache/djb-probe"
    probe.parent.mkdir(exist_ok=True)
    probe.write_text("a probe\n")
    try:
        assert ledger.measured_tree(mirror) == before
    finally:
        probe.unlink()


def _share() -> int:
    """The share a child derives: this environment less `_STRIPPED`, as the helpers hand it."""
    kept = {k: v for k, v in os.environ.items() if k.startswith(_STRIPPED)}
    for name in kept:
        del os.environ[name]
    try:
        return hold.slot_workers(hold.slots_total())
    finally:
        os.environ.update(kept)


def test_test_sh_refuses_n_auto_and_names_the_share(mirror: Path) -> None:
    """Every spelling of `-n auto` is refused naming the share; the share itself is accepted."""
    share = _share()
    lease = mirror / "scripts/gate_lease.sh"
    aside = lease.read_bytes() if lease.exists() else None
    lease.unlink(missing_ok=True)
    try:
        for spelling in (
            "-n auto",
            "-nauto",
            "--numprocesses auto",
            "--numprocesses=auto",
            "-n logical",
        ):
            run = _test_sh(mirror, *spelling.split(), "--collect-only", "-q", "apps/example")
            assert run.rc == 2, spelling
            assert "REFUSING '-n auto'" in run.out and "Nothing ran." in run.out
            assert f"gate_slot_workers (quality/djb/hold.py) says {share} on this box." in run.out
    finally:
        if aside is not None:
            lease.write_bytes(aside)
    assert _test_sh(mirror, "-n", str(share), "--collect-only", "-q", "apps/example").rc == 0
    header = (HOME / "scripts/test.sh").read_text()
    assert not [ln for ln in header.splitlines() if "-n auto" in ln and "what both" in ln]
    assert "GATE_SLOT_WORKERS" in header


def _test_sh(where: Path, *argv: str) -> Run:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)}
    sink = where.parent / f"test-sh-{len(list(where.parent.glob('test-sh-*.out'))) + 1}.out"
    with sink.open("wb") as out:
        done = subprocess.run(
            ["./scripts/test.sh", *argv],
            cwd=where,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=clean,
        )
    return Run(done.returncode, sink.read_text(errors="replace"))


def test_an_empty_capture_is_could_not_look(scratch: Path) -> None:
    """A reader over an empty capture refuses as could-not-look; a capture with bytes is judged."""
    empty = scratch / "empty.out"
    empty.write_text("")
    with pytest.raises(CouldNotLook, match="nothing was captured"):
        Captured(0, empty).text()
    with pytest.raises(CouldNotLook, match="nothing was captured"):
        Captured(0, scratch / "absent.out").text()
    full = scratch / "full.out"
    full.write_text("the collection said something\n")
    assert Captured(0, full).text() == "the collection said something\n"


def test_a_typed_n_above_the_share_is_clamped_and_printed(mirror: Path) -> None:
    """A bare pytest above the share is clamped and says so; at the share it is silent."""
    share = _share()
    over = share * 2
    clamped = pytest_in(mirror, "-n", str(over), "--collect-only", "-q", "apps/example")
    assert clamped.rc == 0
    assert f"clamped -n {over} → {share} (DJB_PYTEST_UNCAPPED=1 to override)" in clamped.out
    at = pytest_in(mirror, "-n", str(share), "--collect-only", "-q", "apps/example")
    assert at.rc == 0 and "clamped -n" not in at.out
    uncapped = pytest_in(
        mirror,
        "-n",
        str(over),
        "--collect-only",
        "-q",
        "apps/example",
        env={"DJB_PYTEST_UNCAPPED": "1"},
    )
    assert uncapped.rc == 0 and "clamped -n" not in uncapped.out
    one = pytest_in(
        mirror, "-n", "4", "apps/example/tests/test_network.py", env={"DJB_PYTEST_MAX_WORKERS": "1"}
    )
    assert one.rc == 0, one.out[-2000:]
    assert "clamped -n 4 → 1" in one.out and "created: 1/1 worker" in one.out


def test_census_runs_the_instrument_census_alone_without_a_slot(mirror: Path) -> None:
    """`--census` answers 0 clean, 2 naming a planted instrument, and runs nothing else."""
    clean = _census(mirror)
    assert clean.rc == 0, clean.out[-2000:]
    assert "instruments derived" in clean.out and "rows in instruments.md" in clean.out
    for noise in ("pytest slot", "gate lock", "waiting for the", "- ruff"):
        assert noise not in clean.out
    plant = "scripts/djb_drive_uncensused_probe.sh"
    with planted(mirror, plant, '#!/usr/bin/env bash\necho "a planted instrument"\n') as path:
        path.chmod(0o755)
        refused = _census(mirror)
    assert refused.rc == 2
    assert f"uncensused: {plant}" in refused.out
    assert "owes a row in docs/product/instruments.md" in refused.out
    assert _census(mirror).rc == 0


def _census(where: Path) -> Run:
    return _run_module(where, "quality.djb", "--census")


def _run_module(where: Path, module: str, *argv: str, env: dict[str, str] | None = None) -> Run:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)}
    sink = where.parent / f"module-{len(list(where.parent.glob('module-*.out'))) + 1}.out"
    with sink.open("wb") as out:
        done = subprocess.run(
            [sys.executable, "-m", module, *argv],
            cwd=where,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**clean, "PYTHONPATH": str(where), **(env or {})},
        )
    return Run(done.returncode, sink.read_text(errors="replace"))


def test_the_typed_escape_prints_and_lifts_the_clamp(mirror: Path) -> None:
    """The escape says the number it runs past, prints no clamp, and is silent with no `-n`."""
    share = _share()
    over = share * 2
    run = pytest_in(
        mirror,
        "-n",
        str(over),
        "--collect-only",
        "-q",
        "apps/example",
        env={"DJB_PYTEST_UNCAPPED": "1"},
    )
    assert run.rc == 0
    assert (
        f"uncapped: -n {over} (DJB_PYTEST_UNCAPPED=1 — the slot share on this box is {share})"
        in run.out
    )
    assert "clamped -n" not in run.out
    hooks = (HOME / "apps/testing/hooks.py").read_text().splitlines()
    escape = next(i for i, ln in enumerate(hooks) if 'os.environ.get("DJB_PYTEST_UNCAPPED"' in ln)
    assign = next(i for i, ln in enumerate(hooks) if "config.option.numprocesses = share" in ln)
    assert escape < assign
    serial = pytest_in(
        mirror, "--collect-only", "-q", "apps/example", env={"DJB_PYTEST_UNCAPPED": "1"}
    )
    assert serial.rc == 0 and "uncapped: -n" not in serial.out


SHARE_PROBE = (
    "import os, django\n"
    "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.test')\n"
    "django.setup()\n"
    "import apps.conftest as c\n"
    "print(c._djb_slot_share())\n"
)


def test_the_python_clamp_and_the_shell_share_are_the_same_number(mirror: Path) -> None:
    """The pytest door's share is the gate's; a handed-down share outranks the derivation."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)}
    clean.pop("DJB_PYTEST_MAX_WORKERS", None)

    def probe(**env: str) -> str:
        done = subprocess.run(
            [sys.executable, "-c", SHARE_PROBE],
            cwd=mirror,
            capture_output=True,
            text=True,
            env={**clean, **env},
        )
        return done.stdout.strip()

    assert probe() == str(_share())
    assert probe(DJB_GATE_SLOT_WORKERS="3") == "3"


def test_a_tree_miss_prints_three_lines_every_other_miss_two_and_the_detail_on_request(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """A miss is short by default — tree: three lines, any other two — and whole when verbose."""
    keyed = loop.Keyed.__new__(loop.Keyed)
    keyed.tree, keyed.key = "planted-tree", "loop-v1:planted"
    keyed.digest, keyed.parts, keyed.cannot = "planted-env", "env-file=planted", ""
    why = {"text": ""}
    monkeypatch.setattr(loop, "shell", lambda root, script, env=None: (0, why["text"]))
    monkeypatch.delenv("DJB_LOOP_VERBOSE", raising=False)
    why["text"] = "tree\nbanked row: a planted row\nsince banked head: 3 path(s) changed\n"
    capfd.readouterr()
    loop.miss(HOME, keyed, scope.Scope())
    tree = capfd.readouterr().out.splitlines()
    assert len(tree) == 3
    assert "MISSED: miss(tree)" in tree[0] and "since banked head: 3 path(s) changed" in tree[2]
    assert "banked row" not in "\n".join(tree)
    why["text"] = "env:env-file\nbanked row: a planted row\n"
    loop.miss(HOME, keyed, scope.Scope())
    assert len(capfd.readouterr().out.splitlines()) == 2
    monkeypatch.setenv("DJB_LOOP_VERBOSE", "1")
    why["text"] = "tree\nbanked row: a planted row\nsince banked head: 3 path(s) changed\n"
    loop.miss(HOME, keyed, scope.Scope())
    verbose = capfd.readouterr().out
    assert "MISSED: miss(tree)" in verbose and "banked row: a planted row" in verbose


# --- `--pr --base <sha>`: a full-mode variant that narrows pytest and nothing else ----

PR_SANCTION = "loop-scope-port: the --pr refusals, asserted above the lease"


@pytest.fixture
def pr_clone(scratch: Path) -> Path:
    """A `--shared` clone of HEAD on `main`, with this checkout's `.env` and `.venv`."""
    dest = scratch / "pr-clone"
    done = subprocess.run(
        ["git", "clone", "-q", "--shared", "--no-hardlinks", str(HOME), str(dest)],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"could not clone this checkout: {done.stderr.strip()}")
    head = _git(HOME, "rev-parse", "HEAD")
    _git(dest, "checkout", "-q", "-B", "main", head)
    _git(dest, "config", "user.email", "port@example.invalid")
    _git(dest, "config", "user.name", "loop scope port")
    if (HOME / ".env").is_file():
        shutil.copy(HOME / ".env", dest / ".env")
    _lend_venv(dest)
    return dest


def _gate_py(where: Path, *argv: str, **env: str) -> Run:
    """`python -m quality.djb gate <argv>` in `where`, stdout to a file."""
    clean = {k: v for k, v in os.environ.items() if not k.startswith(_STRIPPED)}
    sink = where.parent / f"gate-{len(list(where.parent.glob('gate-*.out'))) + 1}.out"
    with sink.open("wb") as out:
        done = subprocess.run(
            [sys.executable, "-m", "quality.djb", "gate", *argv],
            cwd=where,
            stdout=out,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={**clean, "PYTHONPATH": str(where), **env},
        )
    return Run(done.returncode, sink.read_text(errors="replace"))


def _took_nothing(run: Run) -> None:
    assert not re.search(
        r"full-gate lease (ACQUIRED|held)|gate slot ACQUIRED|WAITING for the machine-wide", run.out
    )
    assert not re.search(r"^- (ruff|mypy|import-linter)", run.out, re.M)


def _commit(where: Path, rel: str, text: str, message: str) -> str:
    path = where / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(path.read_text() + text if path.exists() else text)
    commit_all(where, message)
    return _git(where, "rev-parse", "HEAD")


def test_pr_refuses_an_uncomputable_impact_map_before_taking_the_lease(pr_clone: Path) -> None:
    """No base, an unresolvable one, a non-ancestor and a dirty tree: exit 2 before any hold."""
    base = _git(pr_clone, "rev-parse", "HEAD")
    for argv, words in (
        (("--pr",), "--pr needs --base"),
        (("--pr", "--base", "0" * 40), "cannot resolve that to a commit"),
    ):
        run = _gate_py(pr_clone, *argv)
        assert run.rc == 2 and words in run.out, run.out[-1500:]
        _took_nothing(run)
    aside = _commit(pr_clone, "README.md", "a commit HEAD will never contain\n", "the side commit")
    _git(pr_clone, "reset", "-q", "--hard", base)
    run = _gate_py(pr_clone, "--pr", "--base", aside)
    assert run.rc == 2 and "NOT an ancestor of HEAD" in run.out
    _took_nothing(run)
    (pr_clone / "README.md").write_text("uncommitted\n")
    run = _gate_py(pr_clone, "--pr", "--base", base)
    assert run.rc == 2 and "refuses a DIRTY TREE" in run.out
    _took_nothing(run)


def test_pr_refuses_an_unaccountable_label_above_the_lease(pr_clone: Path) -> None:
    """A committed app with no AppConfig is refused naming its `apps.py`, before the lease."""
    base = _git(pr_clone, "rev-parse", "HEAD")
    _commit(pr_clone, "apps/ghost/services.py", "base\n", "an app with no AppConfig")
    run = _gate_py(
        pr_clone,
        "--pr",
        "--base",
        base,
        DJB_GATE_LEASE_DIR="not/a/real/directory",
        DJB_GATE_SANCTION=PR_SANCTION,
    )
    assert run.rc == 2, run.out[-1500:]
    assert "--pr COULD NOT DERIVE THE IMPACT MAP" in run.out and "apps/ghost/apps.py" in run.out
    _took_nothing(run)


def test_a_substitution_callees_refusal_surfaces_as_cause(pr_clone: Path) -> None:
    """The banner's second line is the reader's own sentence, never another pointer."""
    base = _git(pr_clone, "rev-parse", "HEAD")
    _commit(pr_clone, "apps/phantom/services.py", "base\n", "an app with no AppConfig")
    run = _gate_py(
        pr_clone,
        "--pr",
        "--base",
        base,
        DJB_GATE_LEASE_DIR="not/a/real/directory",
        DJB_GATE_SANCTION=PR_SANCTION,
    )
    assert run.rc == 2
    lines = run.out.splitlines()
    at = next(i for i, ln in enumerate(lines) if "--pr COULD NOT DERIVE THE IMPACT MAP" in ln)
    cause = lines[at + 1]
    assert "cause: " in cause and "apps/phantom/apps.py" in cause
    assert "could not derive the depends_on closure" not in cause
    _took_nothing(run)


def test_pr_removes_its_counts_directory_on_every_path(
    monkeypatch: pytest.MonkeyPatch, scratch: Path
) -> None:
    """The `--pr` counts directory is gone after a refused lease and after a red leg."""
    counts: list[Path] = []

    def pr_scope(root: Path, base: str) -> tuple[str, str]:
        made = Path(tempfile.mkdtemp(dir=scratch))
        counts.append(made)
        return "--djb-scope-narrow", str(made)

    def refused(*a: object, **k: object) -> hold.Hold:
        raise hold.Refused("planted: no lease")

    req = gate_args.parse(["--pr", "--base", "HEAD"])
    who = gate_args.Sanctioned("typed", "typed", "port", "the --pr counts")
    monkeypatch.setattr(gate_args, "sanction", lambda root, req, env: who)
    monkeypatch.setattr(gate_args, "sanction_shape", lambda env: None)
    monkeypatch.setattr(modes, "pr_scope", pr_scope)
    monkeypatch.setattr(modes, "_note", lambda *a, **k: None)
    monkeypatch.setattr(modes, "announce", lambda *a, **k: None)
    monkeypatch.setattr(hold, "hold", refused)
    assert modes.run_full(HOME, req) == 2
    monkeypatch.setattr(hold, "hold", lambda *a, **k: hold.Hold("lease"))
    monkeypatch.setattr(modes, "run_members", lambda *a, **k: 1)
    assert modes.run_full(HOME, req) == 1
    assert len(counts) == 2 and not [c for c in counts if c.exists()]


def test_pr_without_a_sanction_is_the_full_gates_refusal(pr_clone: Path) -> None:
    base = _git(pr_clone, "rev-parse", "HEAD")
    run = _gate_py(pr_clone, "--pr", "--base", base)
    assert run.rc == 2 and "REFUSING an unsanctioned FULL gate" in run.out
    _took_nothing(run)


def test_pr_narrows_pytest_and_nothing_else(pr_clone: Path) -> None:
    """A committed files change: narrowed to its scope, no organ tier, no own app."""
    base = _git(pr_clone, "rev-parse", "HEAD")
    _commit(pr_clone, "apps/files/services.py", "\n", "a files change, committed")
    derived = scope.derive(pr_clone, base_ref=base)
    assert derived.touched == ["files"]
    assert _git(pr_clone, "rev-parse", "--short", base) in derived.basis
    args = scope.pytest_args(derived)
    assert "--djb-scope-narrow" in args and "--djb-scope=files" in args
    assert not [a for a in args if a.startswith(("--djb-tier", "--djb-own-app"))]
    full = [g.name for g in cli.table(HOME).mode_legs("full")]
    assert full[0] == "db-pin" and "pytest-x2" in full


def test_a_files_touch_under_pr_selects_the_exports_tests_and_names_the_closure(
    pr_clone: Path, mirror: Path
) -> None:
    base = _git(pr_clone, "rev-parse", "HEAD")
    _commit(pr_clone, "apps/files/services.py", "\n", "a files change, committed")
    derived = scope.derive(pr_clone, base_ref=base)
    assert "exports" in derived.widened
    run = collect(mirror, *scope.pytest_args(derived))
    assert run.rc == 0 and re.search(r"^apps/exports/tests/", run.out, re.M)


def test_an_organ_test_in_a_closure_added_app_runs_under_pr_and_not_under_loop(
    mirror: Path, manifest: list[tuple[str, str]]
) -> None:
    """An organ-reaching exports test runs under `--pr` and is deselected by `--loop`'s tier."""
    victims = sorted(
        n
        for t, n in manifest
        if t == "slow" and n.startswith("apps/exports/tests/") and "[" not in n
    )
    if not victims:
        raise CouldNotLook("no organ-reaching test under apps/exports/tests/")
    pr = collect(mirror, *PR_ARM)
    leaf = collect(mirror, *LEAF_ARM)
    assert pr.rc == 0 and leaf.rc == 0
    assert victims[0] in pr.out.splitlines()
    assert victims[0] not in leaf.out.splitlines()


def test_pr_with_an_empty_diff_runs_the_always_on_set_and_says_so(
    pr_clone: Path, mirror: Path
) -> None:
    head = _git(pr_clone, "rev-parse", "HEAD")
    derived = scope.derive(pr_clone, base_ref=head)
    assert (derived.touched, derived.apps) == ([], [])
    assert "the scope is EMPTY and the always-on cross-app set runs alone" in derived.reason
    run = collect(mirror, *scope.pytest_args(derived))
    assert run.rc == 0 and run.count() > 0


def test_pr_ignores_a_banked_partition_row(
    mirror: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """A path-narrowed pass under a scope refuses, so `--pr` measures past a banked skip, aloud."""
    narrowed = collect(mirror, "--djb-scope-narrow", "--djb-scope=files", "apps/files")
    assert narrowed.rc == 4
    assert "the floors are asserted over the whole collection" in narrowed.out
    skip = pytest_x2.Decision("skip", "banked-key", ("apps/x",), True)
    monkeypatch.setattr(pytest_x2, "_streamed", lambda ctx, argv, env=None: 0)
    monkeypatch.setattr(pytest_x2, "read_decision", lambda path: skip)
    ctx = R.Ctx(HOME, "full", {"GATE_PR": "1", "GATE_PR_PYTEST_ARGS": "--djb-scope-narrow"})
    rc, decided = pytest_x2.partition(ctx, pytest_x2.Run.of(ctx.env))
    assert rc == 0 and decided is not None
    assert (decided.mode, decided.targets) == ("measure", ("--djb-scope-narrow",))
    assert "--pr IGNORES THE BANKED PARTITION ROW (key banked-key)" in capfd.readouterr().out


def test_pr_writes_no_verdict_row_and_no_partition_row(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    """A green `--pr` notes a narrowed run, records no verdict, and banks no partition row."""
    notes_: list[str] = []

    def never(*a: object, **k: object) -> None:
        raise AssertionError("a --pr run reached a bank")

    monkeypatch.setattr(ledger, "record_full", never)
    monkeypatch.setattr(
        modes, "_note", lambda root, tree, state, caller, clock: notes_.append(state)
    )
    req = gate_args.parse(["--pr", "--base", "HEAD"])
    who = gate_args.Sanctioned("typed", "typed", "port", "the --pr settle")
    assert modes.settle(HOME, req, who, "pr", modes.Clock(), "t", Path("/nonexistent")) == 0
    assert notes_ == ["narrowed-run"]
    assert "no verdict recorded — narrowed run" in capfd.readouterr().out
    monkeypatch.setattr(pytest_x2, "_streamed", never)
    decision = pytest_x2.Decision("measure", "k", (), True)
    assert (
        pytest_x2.bank_partition(
            R.Ctx(HOME, "full", {}), pytest_x2.Run.of({"GATE_PR": "1"}), decision
        )
        == 0
    )
    assert "partition verdict NOT banked: --pr" in capfd.readouterr().out


# --- criterion 9: the planted-miss triple ------------------------------------------

PLANT_APP = "djbplant"


def test_the_planted_miss_triple(pr_clone: Path) -> None:
    """An undeclared coupling: red alone, selected today, missed by the scope, kept by the bank."""
    if PLANT_APP in _platform_apps():
        raise CouldNotLook(f"quality/partition.yaml lists {PLANT_APP!r} as a platform app")
    plant = pr_clone
    (plant / "apps/example/plant_channel.py").write_text('CHANNEL = "v1"\n')
    app = plant / "apps" / PLANT_APP
    (app / "tests").mkdir(parents=True)
    (app / "__init__.py").write_text("")
    (app / "tests/__init__.py").write_text("")
    (app / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\nclass DjbplantConfig(AppConfig):\n"
        f'    name = "apps.{PLANT_APP}"\n    depends_on: tuple[str, ...] = ()\n'
    )
    node = f"apps/{PLANT_APP}/tests/test_undeclared_coupling.py"
    (plant / node).write_text(
        "from apps.example import plant_channel\n\n\n"
        "def test_the_documented_channel_still_answers():\n"
        '    assert plant_channel.CHANNEL == "v1"\n'
    )
    commit_all(plant, "the plant: a product app reaching a platform symbol, undeclared")
    (plant / "apps/example/plant_channel.py").write_text('CHANNEL = "v2"\n')
    derived = scope.derive(plant)
    assert PLANT_APP not in derived.apps
    env = {"DATABASE_NAME": "djb_loop_scope_port_plant"}
    red = pytest_in(plant, "-q", "-rf", node, env=env)
    assert red.rc == 1 and node in red.out
    today = ["--djb-tier=fast", *(f"--djb-own-app={a}" for a in derived.own)]
    a = pytest_in(plant, "--collect-only", "-q", *today, env=env)
    assert a.rc == 0 and node in a.out
    scoped = [*today, *(f"--djb-scope={x}" for x in derived.apps), "--djb-scope-narrow"]
    b = pytest_in(plant, "--collect-only", "-q", *scoped, env=env)
    assert b.rc == 0 and node not in b.out
    paths = _run_module(plant, "quality.partition", "paths", env=env)
    assert paths.rc == 0 and f"apps/{PLANT_APP}" in paths.out


# --- the census seeds -----------------------------------------------------------------


def test_the_seeded_census_goes_red_on_a_planted_nineteenth_key(mirror: Path) -> None:
    """The seed selects the vocabulary census an example declaration moves, and it reds by name."""
    narrow = (*NARROW, "--djb-own-app=example", "--djb-scope=example")
    seed = "--djb-changed-test=apps/core/tests/test_vocabulary.py"
    without = collect(mirror, *narrow)
    with_ = collect(mirror, *narrow, seed)
    assert "test_vocabulary" not in without.out
    assert "apps/core/tests/test_vocabulary.py::" in with_.out
    policies = mirror / "apps/example/policies.py"
    source = policies.read_text()
    anchor = "ACTION_PROSE: dict[str, str] = {"
    if anchor not in source:
        raise CouldNotLook("apps/example/policies.py has no ACTION_PROSE to plant into")
    policies.write_text(
        source.replace(anchor, anchor + '\n    "gizmo.view": "You may not view gizmos.",', 1)
    )
    try:
        red = pytest_in(
            mirror,
            "-q",
            "apps/core/tests/test_vocabulary.py",
            "-k",
            "the_census_refuses_a_nineteenth",
        )
    finally:
        policies.write_text(source)
    assert red.rc == 1, red.out[-2000:]
    assert (
        "FAILED apps/core/tests/test_vocabulary.py::test_the_census_refuses_a_nineteenth" in red.out
    )


# --- `test_loop_tier.sh`: the derived slow tier, on a planted mirror --------------------

PLANT_ORGAN = "apps/files/tests/test_djb_loop_tier_plant.py"
PLANT_TEMPORAL = "apps/example/tests/test_djb_loop_tier_plant.py"
PLANT_PLAIN = "apps/usage/tests/test_djb_loop_tier_plant.py"
ORGAN_NODE = f"{PLANT_ORGAN}::test_a_planted_test_that_reaches_the_minio_organ"
TEMPORAL_NODE = f"{PLANT_TEMPORAL}::test_a_planted_test_whose_module_names_the_temporal_entry_point"
PLAIN_NODE = f"{PLANT_PLAIN}::test_a_planted_test_that_reaches_no_organ"
#: The Temporal entry point, assembled so this module never names it.
TEMPORAL_ENTRY = "Workflow" + "Environment"
PLANTS = {
    PLANT_ORGAN: (
        '"""A planted organ-fixture test."""\n\n\n'
        "def test_a_planted_test_that_reaches_the_minio_organ(bucket: str) -> None:\n"
        "    assert bucket\n"
    ),
    PLANT_TEMPORAL: (
        '"""A planted module naming the Temporal entry point."""\n\n'
        f"from temporalio.testing import {TEMPORAL_ENTRY}\n\n\n"
        "def test_a_planted_test_whose_module_names_the_temporal_entry_point() -> None:\n"
        f"    assert {TEMPORAL_ENTRY} is not None\n"
    ),
    PLANT_PLAIN: (
        '"""A planted test reaching no organ."""\n\n\n'
        "def test_a_planted_test_that_reaches_no_organ() -> None:\n"
        "    assert True\n"
    ),
}


def _manifest(where: Path, *flags: str) -> dict[str, tuple[str, str]]:
    """`nodeid -> (tier, organs)` from one classifying collection."""
    out = where.parent / f"manifest-{len(list(where.parent.glob('manifest-*.tsv'))) + 1}.tsv"
    run = collect(where, f"--djb-tier-manifest={out}", *flags)
    assert run.rc == 0, run.out[-2000:]
    rows = [line.split("\t") for line in out.read_text().splitlines() if line]
    return {row[2]: (row[0], row[1]) for row in rows}


@pytest.fixture(scope="module")
def planted_tiers(mirror: Path) -> dict[str, tuple[str, str]]:
    """The organ classification with the three plants standing, then the plants removed."""
    for rel, text in PLANTS.items():
        (mirror / rel).write_text(text)
    try:
        return _manifest(mirror)
    finally:
        for rel in PLANTS:
            (mirror / rel).unlink()


def test_every_declared_organ_kind_is_derived_on_this_tree(
    manifest: list[tuple[str, str]], mirror: Path
) -> None:
    """Each organ kind is derived on at least one test, and the fast tier is not empty."""
    rows = _manifest(mirror)
    for kind in ("minio", "meili", "temporal"):
        assert [n for n, (t, o) in rows.items() if t == "slow" and kind in o], kind
    assert [n for n, (t, _) in rows.items() if t == "fast"]


def test_a_planted_organ_fixture_test_joins_the_slow_tier_with_no_list_edit(
    planted_tiers: dict[str, tuple[str, str]],
) -> None:
    assert planted_tiers[ORGAN_NODE] == ("slow", "minio")


def test_a_planted_module_naming_the_temporal_entry_point_joins_the_slow_tier(
    planted_tiers: dict[str, tuple[str, str]],
) -> None:
    assert planted_tiers[TEMPORAL_NODE] == ("slow", "temporal")


def test_a_planted_test_reaching_nothing_stays_fast(
    planted_tiers: dict[str, tuple[str, str]],
) -> None:
    assert planted_tiers[PLAIN_NODE] == ("fast", "-")


def test_the_plants_leave_when_they_are_removed(
    planted_tiers: dict[str, tuple[str, str]], mirror: Path
) -> None:
    after = _manifest(mirror)
    assert ORGAN_NODE not in after and TEMPORAL_NODE not in after


def test_the_fast_tier_deselects_the_slow_one_and_says_so(mirror: Path) -> None:
    run = pytest_in(mirror, "--collect-only", "--djb-tier=fast")
    assert run.rc == 0
    for words in (
        "djb tier: FAST",
        "organ-reaching test(s) deselected",
        "are DESELECTED",
        "NO own app",
        "the FULL gate at push runs every one of them",
    ):
        assert words in run.out


def test_an_own_app_keeps_its_own_organ_tests_in_the_rung(mirror: Path) -> None:
    """`--djb-own-app=files` keeps its organ test; another app's promotion does not."""
    with planted(mirror, PLANT_ORGAN, PLANTS[PLANT_ORGAN]):
        own = collect(mirror, "--djb-tier=fast", "--djb-own-app=files")
        other = collect(mirror, "--djb-tier=fast", "--djb-own-app=exports")
    assert own.rc == 0 and "test_a_planted_test_that_reaches_the_minio_organ" in own.out
    assert other.rc == 0 and "test_a_planted_test_that_reaches_the_minio_organ" not in other.out


def test_an_unmet_floor_refuses_rather_than_running_a_tier_it_cannot_vouch_for(
    mirror: Path,
) -> None:
    run = collect(mirror, "--djb-tier=fast", "apps/usage")
    assert run.rc == 4
    assert "organ derivation is not answering" in run.out and "Nothing was deselected" in run.out


def test_a_marked_census_is_always_on_at_an_empty_scope(mirror: Path) -> None:
    """A marked module is kept at an empty scope and another app's, and counted; it leaves."""
    plant = "apps/files/tests/test_djb_loop_tier_census_plant.py"
    walker = (
        f"{scope.CENSUS_MARKER} walks every *.py under apps/ — planted by the port\n"
        '"""A planted declared census."""\n\nimport pathlib\n\n'
        'WALKED = sorted(pathlib.Path("apps")' + ".rglob(" + '"*.py"))\n\n\n'
        "def test_a_planted_declared_cross_app_census() -> None:\n"
        "    assert WALKED is not None\n"
    )

    def always(run: Run) -> int:
        found = re.search(r"\(\d+ in scope, (\d+) always-on\)", run.out)
        if found is None:
            raise CouldNotLook("no '(<n> in scope, <n> always-on)' line")
        return int(found.group(1))

    before = collect(mirror, "--djb-scope-narrow")
    with planted(mirror, plant, walker):
        empty = collect(mirror, "--djb-scope-narrow")
        usage = collect(mirror, "--djb-scope-narrow", "--djb-own-app=usage")
    after = collect(mirror, "--djb-scope-narrow")
    assert before.rc == empty.rc == usage.rc == after.rc == 0
    assert "test_a_planted_declared_cross_app_census" in empty.out
    assert "test_a_planted_declared_cross_app_census" in usage.out
    assert always(empty) == always(before) + 1 == always(after) + 1
    assert "test_a_planted_declared_cross_app_census" not in after.out


def test_the_loop_banner_names_each_declared_census(
    scratch_repo: Callable[..., Path],
    capfd: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Marked modules are listed with their reasons, bare ones refused, an absent home exit 2."""
    world = scratch_repo("census-world")
    (world / "apps/alpha/tests").mkdir(parents=True)
    (world / "apps/beta/tests").mkdir(parents=True)
    (world / "apps/alpha/tests/test_marked.py").write_text(
        f"{scope.CENSUS_MARKER} walks every *.py under apps/ for the port's sake\n"
    )
    (world / "apps/beta/tests/test_plain.py").write_text('"""Nothing to declare."""\n')
    assert scope.declared_censuses(world) == [
        ("apps/alpha/tests/test_marked.py", "walks every *.py under apps/ for the port's sake")
    ]
    (world / "apps/beta/tests/test_plain.py").write_text(f"{scope.CENSUS_MARKER} \n")
    with pytest.raises(CouldNotLook, match="NO REASON"):
        scope.declared_censuses(world)
    (world / "apps/beta/tests/test_plain.py").unlink()
    (world / "apps/alpha/tests/test_marked.py").unlink()
    assert scope.declared_censuses(world) == []
    with pytest.raises(CouldNotLook, match="is not a directory"):
        scope.declared_censuses(world, "nowhere")
    tier = (HOME / "apps/testing/tier.py").read_text()
    assert f'DJB_CENSUS_MARKER = "{scope.CENSUS_MARKER}"' in tier
    assert f"DJB_CENSUS_MARKER_LINES = {scope.CENSUS_LINES}" in tier
    assert f'DJB_CENSUS_POPULATION = "{scope.CENSUS_POPULATION}"' in tier
    monkeypatch.setattr(hold, "nominal", lambda *a, **k: None)
    capfd.readouterr()
    taken = hold.Hold("slot", total=1, workers=1)
    assert loop_pytest.preamble(R.Ctx(world, "loop", {}), None, taken, 1) == 0
    assert "always-on censuses (declared): (none declared)" in capfd.readouterr().out


def _ao_env(
    scratch: Path,
    members: dict[str, int],
    seconds: dict[str, int] | None = None,
    census: tuple[str, ...] = (),
    name: str = "drives",
) -> dict[str, str]:
    """A planted drive set, its walls file and a scratch ledger, as the leg reads them."""
    home = scratch / name
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    (home / "drive_preamble.sh").write_text("# a planted preamble\n")
    for member, rc in members.items():
        head = "#!/bin/sh\n"
        if member in census:
            head += f"{scope.CENSUS_MARKER} a planted cross-app census; no organs\n"
        path = home / f"test_{member}.sh"
        path.write_text(
            f'{head}# drives: scripts/tests/drive_preamble.sh\necho "planted member {member}'
            f' speaking"\nexit {rc}\n'
        )
        path.chmod(0o755)
    ledger_ = scratch / f"{name}-verdicts"
    ledger_.write_text("")
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", str(scratch)),
        "DJB_SELFTEST_DRIVES_DIR": str(home),
        "DJB_GATE_LEDGER": str(ledger_),
        "DJB_ALWAYS_ON_CHANGED_FILES": "",
        "TMPDIR": str(scratch),
    }
    walls = scratch / f"{name}-walls.json"
    if seconds is not None:
        doc = {"measured_at": "planted", "machine": "Scratch 0.0", "members": seconds}
        walls.write_text(json.dumps(doc, indent=2) + "\n")
    env["DJB_GATE_MEMBER_DURATIONS"] = str(walls)
    return env


def _ao(env: dict[str, str], capfd: pytest.CaptureFixture[str]) -> tuple[int, str]:
    capfd.readouterr()
    rc = ao.leg(R.Ctx(HOME, "loop", env))
    seen = capfd.readouterr()
    return rc, seen.out + seen.err


def test_the_always_on_leg_derives_its_members_from_the_durations_file(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """Under the floor runs, above it waits for the full gate, unmeasured joins later."""
    env = _ao_env(scratch, {"cheap": 0, "pricey": 0, "nameless": 0}, {"cheap": 3, "pricey": 11})
    rc, said = _ao(env, capfd)
    assert rc == 0, said
    assert "measured_at planted" in said and "on Scratch 0.0" in said
    assert re.search(r"^  member cheap: exit 0 \(\d+s\)$", said, re.M)
    assert "pricey above the floor (11 s)" in said and "member pricey: exit" not in said
    assert "nameless unmeasured — joins after the next --store-durations" in said
    assert "member nameless: exit" not in said


def test_a_full_only_red_reds_the_loop(scratch: Path, capfd: pytest.CaptureFixture[str]) -> None:
    env = _ao_env(scratch, {"quiet": 0, "stray": 1}, {"quiet": 2, "stray": 6})
    rc, said = _ao(env, capfd)
    assert rc == 1 and "RED: stray" in said and "planted member stray speaking" in said
    env = _ao_env(scratch, {"quiet": 0, "blind": 2}, {"quiet": 2, "blind": 6}, name="blind")
    rc, said = _ao(env, capfd)
    assert rc == 2 and "COULD NOT LOOK: blind" in said


def test_no_durations_file_runs_only_the_declared_censuses(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    env = _ao_env(scratch, {"marked": 0, "plain": 0}, None, census=("marked",))
    rc, said = _ao(env, capfd)
    assert rc == 0, said
    assert "no durations file — the first --store-durations writes it" in said
    assert "census marked: exit 0" in said
    assert "a planted cross-app census; no organs" in said
    assert "member plain: exit" not in said


def test_an_unknown_member_in_the_file_is_exit_2(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    env = _ao_env(scratch, {"cheap": 0}, {"cheap": 3, "not_a_member_of_this_gate": 2})
    rc, said = _ao(env, capfd)
    assert rc == 2 and "not_a_member_of_this_gate" in said and "member cheap: exit" not in said


def test_a_marked_drive_runs_in_the_loop_at_every_scope(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    env = _ao_env(scratch, {"slowcensus": 0, "plain": 0}, {"slowcensus": 600}, ("slowcensus",))
    rc, said = _ao(env, capfd)
    assert rc == 0 and "census slowcensus: exit 0" in said
    assert "slowcensus above the floor" not in said and "member plain: exit" not in said
    env = _ao_env(scratch, {"slowcensus": 1}, {"slowcensus": 600}, ("slowcensus",), "red")
    rc, said = _ao(env, capfd)
    assert rc == 1 and "RED: slowcensus" in said


def test_a_banked_member_is_reused_and_a_moved_input_is_not(
    scratch: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A green member banks and is reused; a moved input re-runs it; a red one banks nothing."""
    env = _ao_env(scratch, {"cheap": 0}, {"cheap": 3})
    rc, said = _ao(env, capfd)
    assert rc == 0 and re.search(r"^  member cheap: exit 0 \(\d+s\)$", said, re.M)
    rows = Path(env["DJB_GATE_LEDGER"]).read_text().splitlines()
    assert [r for r in rows if r.split()[2:3] == ["drive"] and r.split()[4:5] == ["cheap"]]
    rc, said = _ao(env, capfd)
    assert rc == 0 and "member cheap: REUSED from drive-v1:" in said
    assert "member cheap: exit 0" not in said
    drive = Path(env["DJB_SELFTEST_DRIVES_DIR"]) / "test_cheap.sh"
    drive.write_text(drive.read_text() + 'echo "and one more line"\n')
    rc, said = _ao(env, capfd)
    assert rc == 0 and re.search(r"^  member cheap: exit 0 \(\d+s\)$", said, re.M)
    env = _ao_env(scratch, {"stray": 1}, {"stray": 3}, name="stray")
    rc, _ = _ao(env, capfd)
    rows = Path(env["DJB_GATE_LEDGER"]).read_text().splitlines()
    assert rc == 1 and not [r for r in rows if r.split()[4:5] == ["stray"]]


def test_the_measurement_writes_a_file_its_own_reader_can_read(scratch: Path) -> None:
    """The walls writer's file reads back through the leg's reader; nothing measured writes none."""
    home = scratch / "round.json"
    machine = "Scratch 0.0"
    ledger.store_durations(
        home, machine, "tree:planted", {"ruff": 0, "selftest": 1887, "queue_index": 2}
    )
    assert home.read_text().splitlines()[0] == "{"
    json.loads(home.read_text())
    walls = ledger.durations(scratch, machine, homes=[home], say=lambda line: None)
    assert walls == {"ruff": 0, "selftest": 1887, "queue_index": 2}
    _, ats = ledger._walls_read([home], lambda line: None)
    assert ats[machine] == "tree:planted"
    never = scratch / "never-written.json"
    with pytest.raises(ledger.Refused):
        ledger.store_durations(never, machine, "tree:planted", {})
    assert not never.exists()


def test_the_measurement_flag_belongs_to_the_full_mode_alone() -> None:
    """`--store-durations` alone measures the whole gate; with `--fast`/`--loop` it is refused."""
    alone = gate_args.parse(["--store-durations"])
    assert (alone.mode, alone.store_members, alone.store_durations) == ("", True, False)
    for mode in ("--fast", "--loop"):
        with pytest.raises(gate_args.Refusal) as refused:
            gate_args.parse([mode, "--store-durations"])
        assert "--store-durations without --leg measures the WHOLE gate" in "\n".join(
            refused.value.lines
        )
    leg = gate_args.parse(["--leg", "pytest-x2", "--store-durations"])
    assert (leg.mode, leg.unit, leg.store_durations, leg.store_members) == (
        "--leg",
        "pytest-x2",
        True,
        False,
    )
    bank = gate_args.parse(["--bank"])
    assert (bank.mode, bank.bank, bank.store_members) == ("", True, False)
    with pytest.raises(gate_args.Refusal) as refused:
        gate_args.parse(["--store-duration"])
    said = "\n".join(refused.value.lines)
    assert "unknown argument '--store-duration'" in said and "--store-durations, --bank" in said


def test_every_registered_drive_member_resolves_to_a_file() -> None:
    """Every drive the selftest unit registers is a file."""
    ctx = R.Ctx(HOME, "loop", {})
    rows = ao.drives(ctx, cli.table(HOME))
    assert len(rows) >= 1
    assert [name for name, path in rows if not path.is_file()] == []


def test_a_loop_that_is_not_on_a_box_refuses_and_prints_the_recipe(scratch: Path) -> None:
    """Off a box with no valve: the recipe; a marker or a typed reason permits; a typo refuses."""
    said = "\n".join(gate_args.OFF_BOX)
    for words in (
        "REFUSING a --loop on a machine that is not a verifier box",
        "./scripts/verifier_box.sh up --for <rung>",
        "./scripts/verifier_box.sh loop <id> --log loop-<rung>",
        "./scripts/verifier_box.sh wait <id> loop-<rung>",
        "./scripts/verifier_box.sh down <id>",
        'DJB_LOOP_HERE="<rung-id>: <reason>"',
        "Nothing was judged",
    ):
        assert words in said
    assert gate_args.loop_here({}, None) is None
    marker = str(scratch / "planted-box-marker")
    assert gate_args.loop_here({}, marker) == f"a verifier box ({marker})"
    typed = "x-1: no AWS credentials in this session"
    assert gate_args.loop_here({"DJB_LOOP_HERE": typed}, None) == f"DJB_LOOP_HERE={typed}"
    with pytest.raises(gate_args.Refusal) as refused:
        gate_args.loop_here({"DJB_LOOP_HERE": "because"}, None)
    typo = "\n".join(refused.value.lines)
    assert "DJB_LOOP_HERE is set but is not a reason" in typo
    assert 'want: DJB_LOOP_HERE="<rung-id>: <reason>"' in typo
    assert "REFUSING a --loop on a machine" not in typo


def test_a_laptop_loop_on_bytes_a_box_measured_prints_the_hit(
    pr_clone: Path,
    scratch: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """A box's row on this SCRATCH world's tree is a hit; a local row or no-cache is not."""
    tree = ledger.measured_tree(pr_clone)
    key = "loop-v1:" + "b" * 64
    row = (
        f"loop-v1 {key} loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1 "
        f"tree={tree} env=x"
    )
    hit = scratch / "box-ledger-hit"
    hit.write_text(f"{row} box=i-zzzbox\n")
    monkeypatch.setenv("DJB_LOOP_LEDGER", str(hit))
    monkeypatch.delenv("DJB_LOOP_NO_CACHE", raising=False)
    monkeypatch.delenv("DJB_GATE_LEDGER", raising=False)
    capfd.readouterr()
    assert loop.box_held(pr_clone, False) == 0
    said = capfd.readouterr().out
    assert "ok: --loop VERDICT HELD BY A BOX" in said
    assert "  box    i-zzzbox  banked 2026-09-27T10:00:00Z" in said
    assert f"  key    {key}" in said
    local = scratch / "box-ledger-local"
    local.write_text(f"{row}\n")
    monkeypatch.setenv("DJB_LOOP_LEDGER", str(local))
    assert loop.box_held(pr_clone, False) is None
    monkeypatch.setenv("DJB_LOOP_LEDGER", str(hit))
    monkeypatch.setenv("DJB_LOOP_NO_CACHE", "1")
    assert loop.box_held(pr_clone, False) is None


# --- the wiring the shim deletes, pinned on the Python objects -------------------------


def test_the_loop_leg_asks_the_fast_tier_for_the_own_apps() -> None:
    """The `pytest` leg is loop-only and asks the fast tier with the own apps; full asks none."""
    leg = cli.table(HOME).leg("pytest")
    assert set(leg.modes) == {"loop"} and leg.body is loop_pytest.run
    own = scope.Scope(own=["files"], apps=["exports", "files"], narrow=True)
    args = loop_pytest.tier_args(own)
    assert args[0] == "--djb-tier=fast" and "--djb-own-app=files" in args
    full = scope.Scope()
    full.mode = "full"
    assert loop_pytest.tier_args(full) == []


def test_the_full_gate_passes_carry_no_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Both full-gate passes run the arguments handed them, with no tier and no own app."""
    seen: list[list[str]] = []
    monkeypatch.setattr(pytest_x2, "_streamed", lambda ctx, argv, env=None: _record(seen, argv, 0))
    monkeypatch.setattr(
        pytest_x2, "_captured", lambda ctx, argv, env=None: (_record(seen, argv, 0), "")
    )
    ctx = R.Ctx(HOME, "full", {})
    assert pytest_x2.passes(ctx, pytest_x2.Run.of({}), 2, 7, ["apps/x"], "") == 0
    assert len(seen) == 2 and seen[0] == seen[1]
    assert not [a for argv in seen for a in argv if a.startswith(("--djb-tier", "--djb-own-app"))]


def _record(into: list[Any], item: Any, value: Any) -> Any:
    """Append `item` and answer `value`: a stand-in that notes it ran."""
    into.append(item)
    return value


# --- the wrapper files' consumer census (GF-9's reader) --------------------------------

DOCS_GUIDE = "/".join(("docs", "guide.md"))
CONSUMER_WORLD = {
    "scripts/lib.sh": "lib_do() {\n    :\n}\n",
    "scripts/sources.sh": '. "$(dirname -- "$0")/lib.sh" || exit 2\n',
    "scripts/calls.sh": "x=$(lib_do)\n",
    "scripts/comments.sh": "# . scripts/lib.sh, then x=$(lib_do)\necho done\n",
    "quality/runner.py": 'ARGV = (("source", "scripts/lib.sh", "lib_do"),)\n',
    "quality/listing.py": 'LIBS = (\n    "scripts/lib.sh",\n)\n',
    "quality/prose.py": 'MSG = "see scripts/lib.sh. It names lib_do in prose"\n',
    "quality/holder.py": "HOLDER = 'lib_do \"$x\"'\n",
    "quality/verbs.py": '# the verbs scripts/lib.sh exports\nVERBS = {"lib_do": 1}\nlib_do(2)\n',
    "quality/tests/test_lib.py": 'SOURCE = ". scripts/lib.sh || exit 2\\nlib_do"\n',
    DOCS_GUIDE: "`. scripts/lib.sh` then `lib_do`\n",
    "/".join(("docs/product/cycles", "plan.md")): "scripts/lib.sh\n",
}


def test_the_consumer_census_sorts_code_prelude_pins_and_citations(
    scratch_repo: Callable[..., Path],
) -> None:
    """A library's consumers fall into exactly one kind each; history files are never read."""
    root = scratch_repo("consumers", "consumer census")
    for rel, text in CONSUMER_WORLD.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "world")
    assert scope.lib_functions(root, "lib") == ["lib_do"]
    assert scope.consumers(root, "lib") == {
        "code": [
            "quality/holder.py",
            "quality/runner.py",
            "scripts/calls.sh",
            "scripts/sources.sh",
        ],
        "prelude": ["quality/listing.py"],
        "pin": ["quality/tests/test_lib.py"],
        "cite": [DOCS_GUIDE, "quality/prose.py", "quality/verbs.py", "scripts/comments.sh"],
    }


# --- the CI lane: one word a pull request's run is chosen by (MQ1.1, MQ1.2) ---------------------

#: One planted path per forced-full pattern, in the tuple's order: each yields `full` alone.
FORCED_PLANTS = (
    "quality/zzz_planted.py",
    "scripts/zzz_planted.sh",
    ".github/workflows/zzz_planted.yml",
    "deploy/zzz_planted.sh",
    "compose.zzz.yaml",
    "compose/zzz_planted.yaml",
    "pyproject.toml",
    "uv.lock",
)


def _branch(root: Path, *paths: str) -> tuple[str, str]:
    """Commit `paths` touched on a branch off main; `(base, head)` as the two shas."""
    base = _git(root, "rev-parse", "main")
    _git(root, "checkout", "-q", "-b", "rung-lane")
    touch(root, *paths)
    commit_all(root, "the change")
    return base, _git(root, "rev-parse", "HEAD")


def _scope_block(said: str) -> list[str]:
    """The scope block a CLI printed: from `- loop scope:` to the `scope=` line, inclusive."""
    lines = said.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("- loop scope:"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith("  scope=      "))
    return lines[start : end + 1]


def _cli(root: Path, *argv: str, floor: bool = False) -> subprocess.CompletedProcess[str]:
    """The scope CLI as a process; `floor` runs it under `-E -S`, the stdlib alone."""
    flags = ["-E", "-S"] if floor else []
    return subprocess.run(
        [sys.executable, *flags, "-m", "quality.djb.scope", *argv, "--root", str(root)],
        cwd=HOME,
        capture_output=True,
        text=True,
    )


def test_the_lane_reads_the_loops_own_scope_and_the_two_agree(
    world: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """MQ1.1: the lane's scope is `--loop`'s and `--pr`'s on one tree, field for field."""
    base, head = _branch(world, "apps/leaf/services.py")
    lane = scope.lane(world, base, head)
    assert lane.word == "loop", lane.reason
    assert lane.scope is not None
    monkeypatch.setenv("DJB_LOOP_SCOPE_BASE", base)
    looped = loop.derive(world, gate_args.parse(["--loop"]))
    assert lane.scope == looped
    assert lane.scope.canonical == scope.derive(world, base_ref=base).canonical
    picked = _cli(world, "lane", "--base", base, "--head", head)
    plain = _cli(world, "--base", base, "--impact")
    assert (picked.returncode, plain.returncode) == (0, 0), picked.stderr + plain.stderr
    assert picked.stdout.splitlines()[0] == "loop"
    assert _scope_block(picked.stdout) == _scope_block(plain.stdout)


def test_the_forced_full_tuple_is_one_declared_tuple_with_a_plant_per_pattern() -> None:
    """MQ1.2: one tuple, under its non-read declaration, and every pattern has its plant."""
    text = (HOME / "quality/djb/scope.py").read_text(encoding="utf-8").splitlines()
    at = [i for i, ln in enumerate(text) if ln.startswith("FORCED_FULL = (")]
    assert len(at) == 1, "the forced-full list is ONE tuple in scope.py"
    declared = text[at[0] - 1]
    assert declared.startswith("# names, never reads: "), declared
    named = declared.split(": ", 1)[1].split(" — ", 1)[0].split()
    assert named == list(scope.FORCED_FULL)
    assert len(FORCED_PLANTS) == len(scope.FORCED_FULL)
    for plant, name in zip(FORCED_PLANTS, scope.FORCED_FULL, strict=True):
        assert scope.forced_by(plant) == name, plant
    assert [scope.forced_by(p) for p in ("frontend/scripts/x.mjs", "apps/x/deploy.py")] == ["", ""]
    assert "fast" not in scope.CI_LANES


@pytest.mark.parametrize("plant", FORCED_PLANTS)
def test_a_planted_touch_to_each_forced_path_is_the_full_lane(world: Path, plant: str) -> None:
    """MQ1.2: a touch to any forced path is `full`, whatever else the diff holds."""
    base, head = _branch(world, plant, "apps/leaf/services.py")
    lane = scope.lane(world, base, head)
    assert lane.word == "full", lane.reason
    assert (plant, scope.forced_by(plant)) in lane.forced
    said = _cli(world, "lane", "--base", base, "--head", head, floor=True)
    assert said.returncode == 0, said.stderr
    assert said.stdout.splitlines()[0] == "full"
    assert f"  forced:     {plant} ({scope.forced_by(plant)})" in said.stdout.splitlines()


def test_a_deleted_forced_path_is_full_though_the_scope_never_sees_a_deletion(world: Path) -> None:
    """A deletion is dropped by the changed-file reader; the forced list reads it anyway."""
    base = _git(world, "rev-parse", "main")
    _git(world, "checkout", "-q", "-b", "rung-lane")
    _git(world, "rm", "-q", "scripts/check.sh")
    commit_all(world, "a deletion")
    lane = scope.lane(world, base, _git(world, "rev-parse", "HEAD"))
    assert lane.word == "full", lane.reason
    assert ("scripts/check.sh", "scripts/") in lane.forced


WALLS_TABLES = ("scripts/gate_member_durations.json", "scripts/local/gate_member_durations.ci.json")


@pytest.mark.parametrize("walls", WALLS_TABLES)
def test_the_folds_walls_table_beside_an_app_change_is_the_loop_lane(
    world: Path, walls: str
) -> None:
    """The push ritual's derived walls table forces nothing; the change's own lane decides."""
    base, head = _branch(world, "apps/leaf/services.py", walls)
    lane = scope.lane(world, base, head)
    assert lane.forced == [], lane.reason
    assert lane.word == "loop", lane.reason


def _walls(members: dict[str, int], tree: str) -> str:
    rows = ",\n".join(f'    "{name}": {{"ubuntu-latest": {n}}}' for name, n in members.items())
    return (
        f'{{\n  "measured_at": {{\n    "ubuntu-latest": "run:1 tree:{tree}"\n  }},\n'
        f'  "members": {{\n{rows}\n  }}\n}}\n'
    )


#: The live ledger in parts: a whole quote would join it to the loop key.
LIVE_LEDGER = "/".join(("docs", "product", "in-flight" + ".md"))


def test_a_ledger_diff_whose_walls_table_gains_a_row_is_the_docs_lane(world: Path) -> None:
    """The PM's ledger PR: the live ledger plus a fold that harvested a NEW member row."""
    (world / WALLS_TABLES[0]).write_text(_walls({"ruff": 3}, "a" * 40))
    (world / "docs/product").mkdir(parents=True, exist_ok=True)
    (world / LIVE_LEDGER).write_text("# in flight\n")
    commit_all(world, "the walls table and the ledger")
    base = _git(world, "rev-parse", "main")
    _git(world, "checkout", "-q", "-b", "rung-lane")
    (world / WALLS_TABLES[0]).write_text(_walls({"ruff": 4, "gate-tests": 7275}, "b" * 40))
    touch(world, LIVE_LEDGER)
    commit_all(world, "a ledger row and a fold")
    lane = scope.lane(world, base, _git(world, "rev-parse", "HEAD"))
    assert lane.word == "docs", lane.reason


def test_any_other_scripts_path_beside_the_walls_table_is_still_the_full_lane(world: Path) -> None:
    """The exemption names two files; a sibling under `scripts/` still forces `full`."""
    base, head = _branch(world, "apps/leaf/services.py", WALLS_TABLES[0], "scripts/zzz_other.sh")
    lane = scope.lane(world, base, head)
    assert lane.word == "full", lane.reason
    assert lane.forced == [("scripts/zzz_other.sh", "scripts/")]
    assert scope.FORCED_EXEMPT == R.WALLS_HOMES == WALLS_TABLES


PRODUCT_MIGRATION = (
    "apps/leaf/models.py",
    "apps/leaf/migrations/0002_zzz_field.py",
    "apps/leaf/migrations/max_migration.txt",
)


def test_a_product_apps_migration_is_the_loop_lane(world: Path) -> None:
    """A model change with its migration is product code: the app's own lane, nothing forced."""
    base, head = _branch(world, *PRODUCT_MIGRATION)
    lane = scope.lane(world, base, head)
    assert lane.forced == [], lane.reason
    assert lane.word == "loop", lane.reason
    assert lane.scope is not None and lane.scope.touched == ["leaf"]


#: The product-side paths a `--pr` on a product meets; on the template each selects gate tests.
PRODUCT_SIDE = ("scripts/local/x.sh", "apps/bookings/models.py", "quality/local/rules.yaml")


@pytest.fixture
def product_copy(tmp_path: Path) -> Iterator[Path]:
    """A product-shaped tree: the gate tests tracked, a drawer, real dirs a test writes into."""
    root = tmp_path / "copy"
    (root / "quality/local").mkdir(parents=True)
    (root / "scripts/local").mkdir(parents=True)
    for child in (HOME / "scripts").iterdir():
        if child.name != "local":
            (root / "scripts" / child.name).symlink_to(child)
    for child in (HOME / "quality").iterdir():
        if child.name not in ("local", "tests"):
            (root / "quality" / child.name).symlink_to(child)
    shutil.copytree(
        HOME / "quality/tests", root / "quality/tests", ignore=shutil.ignore_patterns("__pycache__")
    )
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: acme\n")
    _git(root, "init", "-q")
    _git(root, "add", "quality/tests", "quality/local")
    with untouched():
        yield root


def test_the_interpreter_guard_fires_on_a_write_through_a_linked_venv(tmp_path: Path) -> None:
    """A stub planted at a linked `.venv/bin/python` lands on its target; the guard says so."""
    target = tmp_path / "shared/python3.12"
    target.parent.mkdir()
    target.write_text("the interpreter\n")
    (tmp_path / "copy/.venv").mkdir(parents=True)
    (tmp_path / "copy/.venv/bin").symlink_to(target.parent)
    with untouched([target]):
        (tmp_path / "copy/.venv/bin/other").write_text("a sibling, not the interpreter\n")
    with pytest.raises(AssertionError, match="the shared interpreter changed"):
        with untouched([target]):
            (tmp_path / "copy/.venv/bin/python3.12").write_text("#!/bin/sh\nexit 0\n")


@pytest.mark.parametrize("path", PRODUCT_SIDE)
def test_a_product_trees_change_selects_no_platform_gate_test(
    product_copy: Path, path: str
) -> None:
    """The template selects gate tests for the path; the same tree with a drawer selects none."""
    assert any(m.startswith("quality/tests/") for m in scope.touched(HOME, [path])), path
    assert scope.touched(product_copy, [path]) == []


PLATFORM_MODULE, OWN_MODULE = "quality/tests/test_x.py", "quality/local/tests/test_x.py"


@pytest.mark.parametrize(
    ("on_a_product", "selected", "harness"),
    [
        (False, [PLATFORM_MODULE], [PLATFORM_MODULE]),
        (True, [PLATFORM_MODULE], []),
        (True, [PLATFORM_MODULE, OWN_MODULE], [OWN_MODULE]),
    ],
    ids=["template", "product-platform-only", "product-own-test"],
)
def test_the_lane_runs_the_selftest_row_for_the_harness_a_product_owns(
    world: Path,
    monkeypatch: pytest.MonkeyPatch,
    on_a_product: bool,
    selected: list[str],
    harness: list[str],
) -> None:
    """The template's selection is its `selftest:1`; a product's row is its own tests alone."""
    from quality.djb.legs import gate_tests

    if on_a_product:
        (world / "quality/local").mkdir(parents=True)
        (world / "quality/local/rules.yaml").write_text("rule_id_namespace: acme\n")
        commit_all(world, "the drawer")
        monkeypatch.setattr(gate_tests, "product_apps", lambda root: PRODUCT_APPS)
    picked = scope.Selection({m: ["self"] for m in selected})
    monkeypatch.setattr(scope, "selection", lambda root, changed, decls=None: picked)
    base, head = _branch(world, "apps/leaf/services.py")
    lane = scope.lane(world, base, head)
    assert lane.word == "loop", lane.reason
    assert lane.harness == harness
    assert ("selftest:1" in lane.units) is bool(harness), lane.units


def _commit_in(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def test_a_product_trees_pr_harness_runs_its_own_drawer_test_and_no_platform_one(
    product_copy: Path, capfd: pytest.CaptureFixture[str]
) -> None:
    """A change beside a product's own gate test selects it; `--pr` runs it and nothing else."""
    from quality.djb.legs import gate_tests

    base = _commit_in(product_copy, "base")
    own = "quality/local/tests/test_acme.py"
    (product_copy / own).parent.mkdir(parents=True)
    (product_copy / own).write_text(
        'import pytest\n\npytestmark = pytest.mark.drives("apps/acme/")\n\n\n'
        "def test_acme() -> None:\n    assert True\n"
    )
    (product_copy / "apps/acme").mkdir(parents=True)
    (product_copy / "apps/acme/models.py").write_text("x = 1\n")
    _commit_in(product_copy, "the change")
    ran = product_copy.parent / "ran"
    py = product_copy / ".venv/bin/python"
    py.parent.mkdir(parents=True)
    py.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"{ran}"\nexit 0\n')
    py.chmod(0o755)
    env = {"PATH": os.environ["PATH"], "GATE_PR": "1", "GATE_PR_BASE": base}
    assert gate_tests.LEG.body is not None
    capfd.readouterr()
    assert gate_tests.LEG.body(R.Ctx(product_copy, "full", env)) == 0
    said = ran.read_text() if ran.exists() else ""
    assert own in said and "quality/tests/" not in said, said
    assert f"  gate-tests (--pr): {own} — the diff's own selection" in capfd.readouterr().out


def test_a_migration_beside_a_quality_change_is_still_the_full_lane(world: Path) -> None:
    """The platform's own paths still force `full` whatever product code rides beside them."""
    base, head = _branch(world, *PRODUCT_MIGRATION, "quality/zzz_planted.py")
    lane = scope.lane(world, base, head)
    assert lane.word == "full", lane.reason
    assert lane.forced == [("quality/zzz_planted.py", "quality/")]


def test_the_product_derived_tuple_is_declared_and_forces_nothing() -> None:
    """One tuple, globs the decider's non-read grammar cannot hold; no derived file is forced."""
    text = (HOME / "quality/djb/scope.py").read_text(encoding="utf-8").splitlines()
    at = [i for i, ln in enumerate(text) if ln.startswith("PRODUCT_DERIVED = (")]
    assert len(at) == 1, "the product-derived list is ONE tuple in scope.py"
    for glob in scope.PRODUCT_DERIVED:
        path = glob.replace("*", "leaf", 1).replace("*", "0002_x")
        assert scope.forced_by(path) == "", path
        assert scope.is_product_path(path, ("core",)), path


def test_a_nouns_authz_baseline_is_named_derived_in_every_app() -> None:
    """The sweep's `<noun>_authz_baseline.json` is derived even in an app the partition owns."""
    for path in (
        "apps/example/tests/widget_authz_baseline.json",
        "apps/example/tests/authz_baseline.json",
    ):
        assert scope.is_product_path(path, ("example",)), path


MIGRATION_READER = "quality/tests/test_zzz_migration_reader.py"
GATE_READER = "quality/tests/test_zzz_gate_reader.py"


def _readers(root: Path) -> None:
    (root / "quality/tests").mkdir(parents=True, exist_ok=True)
    (root / MIGRATION_READER).write_text(
        '"""Reads every migration."""\n\nimport pytest\n\n'
        'pytestmark = pytest.mark.drives("apps/*/migrations/")\n'
    )
    (root / GATE_READER).write_text(
        f'"""Reads the gate."""\n\n{scope.CENSUS_MARKER} population=quality/** the gate\n'
    )
    commit_all(root, "two harness modules")


def test_a_product_diff_pays_no_platform_member_and_says_so(world: Path) -> None:
    """A model, its migration, the leaf and the document: `loop`, tax 0, the migration checks."""
    _readers(world)
    base, head = _branch(world, *PRODUCT_MIGRATION, "frontend/openapi.json")
    lane = scope.lane(world, base, head)
    assert (lane.word, lane.forced) == ("loop", []), lane.reason
    assert lane.harness == [MIGRATION_READER]
    assert lane.scope is not None and lane.scope.touched == ["leaf"]
    assert lane.scope.tax.startswith("tax: 0 min in 0 member(s) the diff did not own — none;")
    assert "selftest:1" in lane.units and "supply-chain" not in lane.units
    said = _cli(world, "lane", "--base", base, "--head", head)
    assert said.returncode == 0, said.stderr
    assert f"  {lane.scope.tax}" in said.stdout.splitlines()
    assert f"  harness:    {MIGRATION_READER}" in said.stdout.splitlines()


def test_every_migration_reader_joins_a_migrations_scope() -> None:
    assert "apps/core/tests/test_audit_contract.py" in ao.census_population(HOME)
    assert "quality/tests/test_shards.py" in scope.touched(HOME, ["apps/testing/hooks.py"])


def test_a_manifest_the_audit_reads_brings_the_supply_chain_row(world: Path) -> None:
    base, head = _branch(world, "apps/leaf/services.py", "frontend/package.json")
    lane = scope.lane(world, base, head)
    assert lane.word == "loop", lane.reason
    assert lane.units == [*scope.LOOP_UNITS, "supply-chain"]


def test_the_harness_row_runs_the_diffs_selection_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--pr` on the selftest unit: no engine selftest, no drive, the harness the diff selects."""
    from quality.djb.legs import gate_tests, selftest

    ran: list[tuple[str, ...]] = []
    monkeypatch.setattr(gate_tests, "tool", lambda ctx, argv: _record(ran, argv, 0))
    pr = {"GATE_PR": "1", "GATE_PR_BASE": "HEAD"}
    for paths, want in (
        (["apps/djb_tags/api.py"], []),
        (["apps/zzz_canary/migrations/0002_x.py"], scope.touched(HOME, ["apps/x/migrations/x.py"])),
    ):
        changed = scope.Changed(paths, "planted", "")
        monkeypatch.setattr(scope, "changed_files", lambda root, base, c=changed: c)
        ran.clear()
        assert gate_tests.run(R.Ctx(HOME, "full", pr)) == 0
        assert [m for a in ran for m in a if m.startswith("quality/tests/")] == want
        assert all(a[-2:] == ao.LOOP_DESELECT for a in ran)
    assert selftest.members(R.Ctx(HOME, "full", pr)) == 0
    assert "selftest (--pr): not run" in capsys.readouterr().out


def test_a_platform_path_is_still_the_full_lane(world: Path) -> None:
    _readers(world)
    base, head = _branch(world, *PRODUCT_MIGRATION, "quality/x.py")
    assert scope.lane(world, base, head).word == "full"


#: A product's change: its own app, its client, its ledger — no gate test reads one.
PRODUCT_ONLY = ("apps/example/services.py", "frontend/src/x.ts", "docs/product/queue.md")
QUOTER = "quality/tests/test_zzz_quoter.py"
QUOTED = "apps/core/tests/test_settings.py"


@pytest.fixture
def whole_suite(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop's own scope answers the whole suite, as shared infrastructure makes it."""
    real, units = scope.derive, scope.ci_units(HOME)

    def whole(root: Path, **kwargs: Any) -> scope.Scope:
        out = real(root, **kwargs)
        out.mode, out.reason = "full", "planted: the whole suite"
        return out

    monkeypatch.setattr(scope, "derive", whole)
    monkeypatch.setattr(scope, "ci_units", lambda root: units)


def _lane_said(world: Path, base: str, head: str, capsys: pytest.CaptureFixture[str]) -> list[str]:
    capsys.readouterr()
    assert scope.lane_main(["--root", str(world), "--base", base, "--head", head]) == 0
    return capsys.readouterr().out.splitlines()


def test_a_product_only_diff_on_the_full_lane_withholds_the_selftest_unit(
    world: Path, whole_suite: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """The SDK ruling's proof: a full lane over product paths alone runs no platform selftest."""
    _app(world, "example", '"core",')
    commit_all(world, "the example app")
    base, head = _branch(world, *PRODUCT_ONLY)
    lane = scope.lane(world, base, head)
    assert (lane.word, lane.selftest) == ("full", "withheld"), lane.reason
    assert "selftest" not in lane.units and lane.units, lane.units
    assert lane.units == [u for u in scope.ci_units(HOME) if u != "selftest"]
    said = _lane_said(world, base, head, capsys)
    assert said[3] == (
        "  selftest:  withheld — none of the 3 changed path(s) is in the selftest closure"
    ), said
    assert f"  units:      {' '.join(lane.units)}" in said
    runs = next(line for line in said if line.startswith("  runs:"))
    assert "no row is narrowed" not in runs and "withheld" in runs, runs


@pytest.mark.parametrize(
    ("paths", "why"),
    [
        pytest.param(("quality/rules.yaml",), "quality/rules.yaml is in the closure (quality/)"),
        pytest.param(("config/urls.py",), "config/urls.py is in the closure (config/)"),
        pytest.param((QUOTED,), f"{QUOTED} is in the closure ({QUOTER})"),
    ],
    ids=["a-forced-root", "config", "a-quoted-apps-path"],
)
def test_a_platform_path_on_the_full_lane_runs_the_selftest_unit_and_says_why(
    world: Path,
    whole_suite: None,
    capsys: pytest.CaptureFixture[str],
    paths: tuple[str, ...],
    why: str,
) -> None:
    (world / QUOTER).parent.mkdir(parents=True, exist_ok=True)
    (world / QUOTER).write_text(f'"""Reads one app test."""\n\nREAD = "{QUOTED}"\n')
    commit_all(world, "a gate test that quotes an app path")
    base, head = _branch(world, *paths)
    lane = scope.lane(world, base, head)
    assert (lane.word, lane.selftest, lane.selftest_why) == ("full", "ran", why), lane.reason
    assert lane.units == [], lane.units
    said = _lane_said(world, base, head, capsys)
    assert said[3] == f"  selftest:  ran — {why}", said
    assert not any(line.startswith("  units:") for line in said), said


def test_a_root_path_a_gate_module_quotes_runs_the_selftest_unit(
    world: Path, whole_suite: None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A path outside apps/ and frontend/ that a gate module quotes is in the closure (F2)."""
    (world / QUOTER).parent.mkdir(parents=True, exist_ok=True)
    (world / QUOTER).write_text('"""Reads the entry point."""\n\nREAD = "manage.py"\n')
    commit_all(world, "a gate test that quotes manage.py")
    base, head = _branch(world, "manage.py")
    lane = scope.lane(world, base, head)
    why = f"manage.py is in the closure ({QUOTER})"
    assert (lane.word, lane.selftest, lane.selftest_why) == ("full", "ran", why), lane.reason
    assert _lane_said(world, base, head, capsys)[3] == f"  selftest:  ran — {why}"


def test_the_real_trees_quoted_root_paths_are_in_the_closure() -> None:
    """On this tree `manage.py` and `conftest.py` are quoted by gate modules: never withheld."""
    for path in ("manage.py", "conftest.py"):
        reach = scope.selftest_reach(HOME, [path])
        assert reach is not None and reach[0] == path, (path, reach)
        assert reach[1].startswith(scope.SELFTEST_CLOSURE.quoters), reach


def test_the_selftest_closure_is_declared_once_and_names_its_blind_spot() -> None:
    text = (HOME / "quality/djb/scope.py").read_text(encoding="utf-8")
    assert text.count("SELFTEST_CLOSURE = Closure(") == 1
    assert set(scope.FORCED_FULL) <= set(scope.SELFTEST_CLOSURE.roots)
    assert {"config/", "templates/"} <= set(scope.SELFTEST_CLOSURE.roots)
    at = text.index("SELFTEST_CLOSURE = Closure(")
    assert "DOES NOT COVER" in text[at - 400 : at] and "glob" in text[at - 400 : at]
    assert scope.selftest_reach(HOME, [f"apps/{'zzz'}_never_quoted/services.py"]) is None
    assert scope.selftest_reach(HOME, [scope.FORCED_EXEMPT[0]]) is None


def test_a_census_on_every_scope_is_charged_by_name_with_no_wall(world: Path) -> None:
    every = "quality/tests/test_zzz_every.py"
    (world / "quality/tests").mkdir(parents=True, exist_ok=True)
    (world / every).write_text(f'"""Every scope."""\n\n{scope.CENSUS_MARKER} it reads all\n')
    commit_all(world, "a census on every scope")
    touch(world, "apps/leaf/services.py")
    said = scope.tax(world, ["apps/leaf/services.py"]).line
    assert said.startswith(f"tax: ? min in 1 member(s) the diff did not own — {every}(?);"), said
    assert said.endswith("(reported, never asserted)")


def test_the_document_alone_is_owned_by_its_two_readers_and_taxes_nothing() -> None:
    document = ["frontend/openapi.json"]
    why = scope.selection(HOME, document).why
    for reader in ("quality/tests/test_fe_leg.py", "quality/tests/test_golden_face.py"):
        assert why.get(reader) == ["drives frontend/openapi.json"], why
    assert scope.tax(HOME, document).line.startswith("tax: 0 min in 0 member(s)")


def test_a_forced_product_root_is_the_rules_finding(monkeypatch: pytest.MonkeyPatch) -> None:
    assert scope.product_census(HOME).findings == []
    monkeypatch.setattr(scope, "FORCED_FULL", (*scope.FORCED_FULL, "apps/"))
    said = [why for _, _, why in scope.product_census(HOME).findings]
    assert "apps/zzz_canary/services.py is a product path and forces the full lane (apps/)" in said


def test_a_deleted_product_path_is_the_loop_lane_and_runs_its_app(world: Path) -> None:
    """A deletion under a product app grades `loop`, and the app's own scope runs."""
    (world / "apps/leaf/old.py").write_text("old\n")
    commit_all(world, "a file to delete")
    base = _git(world, "rev-parse", "main")
    _git(world, "checkout", "-q", "-b", "rung-lane")
    _git(world, "rm", "-q", "apps/leaf/old.py")
    commit_all(world, "a deletion")
    lane = scope.lane(world, base, _git(world, "rev-parse", "HEAD"))
    assert lane.word == "loop", lane.reason
    assert lane.scope is not None and lane.scope.touched == ["leaf"]


BUDGETS = (
    "service_function_length:\n"
    "  apps/core/services.py: 10\n"
    "  apps/leaf/services.py: 12 # the leaf's longest\n"
    "  # the leaf's note, a second line\n"
    "\n"
    "out_schema_fields:\n"
    "  apps/example/schemas.py::WidgetOut: 17\n"
)


@pytest.mark.parametrize(
    ("old", "new", "word"),
    [
        ("apps/leaf/services.py: 12", "apps/leaf/services.py: 13", "loop"),
        ("WidgetOut: 17", "WidgetOut: 18", "loop"),
        ("apps/leaf/services.py: 12", "apps/leaf/services.py: 11", "docs"),
        ("a second line", "a second line, edited", "loop"),
        ("apps/core/services.py: 10", "apps/core/services.py: 9", "full"),
        ("service_function_length:", "service_function_length:  # moved", "full"),
    ],
)
def test_a_budgets_row_diff_is_the_rows_owner(world: Path, old: str, new: str, word: str) -> None:
    """A product's or the example's rows force nothing and charge nothing; any other line forces."""
    (world / "quality/budgets.yaml").write_text(BUDGETS)
    commit_all(world, "the budgets table")
    base = _git(world, "rev-parse", "main")
    _git(world, "checkout", "-q", "-b", "rung-lane")
    (world / "quality/budgets.yaml").write_text(BUDGETS.replace(old, new))
    commit_all(world, "a row")
    lane = scope.lane(world, base, _git(world, "rev-parse", "HEAD"))
    assert lane.word == word, lane.reason
    if word == "loop":
        assert lane.scope is not None and lane.scope.tax.startswith("tax: 0 min in 0 member(s)")


def test_a_wholly_admitted_diff_is_the_docs_lane(world: Path) -> None:
    """`docs` when the docs-only list admits every changed path and nothing quotes one."""
    base, head = _branch(world, DOCS_NOTE, "README.md")
    lane = scope.lane(world, base, head)
    assert lane.word == "docs", lane.reason
    said = _cli(world, "lane", "--base", base, "--head", head, floor=True)
    assert said.returncode == 0, said.stderr
    assert said.stdout.splitlines()[0] == "docs"


def test_an_admitted_path_a_test_quotes_is_the_loop_lane(world: Path) -> None:
    """An admitted path an app test quotes is read: the loop lane runs the reader."""
    reader = world / "apps/mid/tests/test_zzz_docs_reader.py"
    reader.write_text(f'"""Reads a note by name."""\n\nNOTE = "{DOCS_NOTE}"\n')
    commit_all(world, "a reader")
    base, head = _branch(world, DOCS_NOTE)
    lane = scope.lane(world, base, head)
    assert lane.word == "loop", lane.reason
    assert lane.scope is not None
    assert lane.scope.literal_tests == ["apps/mid/tests/test_zzz_docs_reader.py"]


def test_a_full_suite_scope_is_the_full_lane(world: Path) -> None:
    """Shared test infrastructure makes the loop's own scope the whole suite: `full`."""
    base, head = _branch(world, "apps/conftest.py")
    lane = scope.lane(world, base, head)
    assert lane.word == "full", lane.reason
    assert lane.forced == []


# --- CI-THIRD-2: the selftest unit's plan on a `full` lane ---------------------------------------

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def engine_ends() -> tuple[dict[str, str], dict[str, Any], list[dict[str, Any]]]:
    from quality import tree as T

    read = T.read_tree(REPO)
    assert not read.why, read.why
    return (read.blobs, *scope._rules_docs(REPO, None))


def _moved(blobs: dict[str, str], path: str) -> dict[str, str]:
    return {**blobs, path: "0" * 40}


def test_the_plan_narrows_gate_tests_by_the_diffs_selection_and_says_whole_when_shared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2.1: a diff no shared fixture holds selects its modules; a shared one runs them all."""
    row = {"quality/tests/test_ci_derive.py": {"quality/djb/ci_derive.py"}}
    monkeypatch.setattr(scope, "map_rows", lambda root, map_path=scope.MAP_PATH: row)
    picked, of, why = scope.gate_tests_plan(REPO, "HEAD", [".github/workflows/ci.yml"])
    assert picked is not None and "quality/tests/test_ci_derive.py" in picked, why
    assert 0 < len(picked) < of
    plan = scope.SelftestPlan(picked, of, why, (), 96, "")
    head = plan.lines()[0]
    assert head.startswith(f"gate-tests narrowed — {len(picked)} of {of} modules selected ("), head
    picked, of, why = scope.gate_tests_plan(REPO, "HEAD", ["quality/tests/harness.py"])
    assert picked is None and why == "quality/tests/harness.py is shared gate infrastructure"


def test_the_plan_keys_the_engine_by_rule_and_whole_on_its_closure(
    engine_ends: tuple[dict[str, str], dict[str, Any], list[dict[str, Any]]],
) -> None:
    """2.1: the engine's closure is whole; one rule's yaml re-keys that rule; a read re-keys few."""
    blobs, rest, rules = engine_ends
    every = len([r for r in rules if r.get("enabled", True)])
    reader = "quality/engine/readers.py"
    got, of, why = scope.rekeyed_rules(engine_ends, (_moved(blobs, reader), rest, rules), [reader])
    assert (got, of) == (None, every) and why.endswith("(quality/engine/)"), why
    assert scope.SelftestPlan((), 1, "", got, of, why).lines()[1].startswith("engine whole — ")
    first = rules[0]
    reworded = [{**first, "statement": "a reworded statement"}, *rules[1:]]
    got, of, _ = scope.rekeyed_rules(engine_ends, (blobs, rest, reworded), ["quality/rules.yaml"])
    assert got == (str(first["id"]),), got
    line = scope.SelftestPlan((), 1, "", got, of, "").lines()[1]
    assert line == f"engine narrowed — 1 of {of} rules re-keyed ({first['id']})"
    flow = ".github/workflows/ci.yml"
    got, _, _ = scope.rekeyed_rules(engine_ends, (_moved(blobs, flow), rest, rules), [flow])
    assert got is not None and 0 < len(got) < every, got
    got, _, why = scope.rekeyed_rules(
        engine_ends, (blobs, {**rest, "x": {"moved": 1}}, rules), ["quality/rules.yaml"]
    )
    assert got is None and "outside `rules:`" in why


def test_a_map_stamped_at_another_tree_refuses_to_narrow_an_unseen_module(
    scratch_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """2.5: the map predates a module it never saw run, so the plan is whole and says so."""
    repo = scratch_repo()
    stamp = {"generated": {"tree": "tree:" + "a" * 40}, "tests": {"t::x": ["quality/seen.py"]}}
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / scope.MAP_PATH).write_text(json.dumps(stamp))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "a map stamped at another tree")
    assert scope._map_predates(repo, "HEAD", ["quality/new.py"]) == "quality/new.py"
    assert scope._map_predates(repo, "HEAD", ["quality/seen.py", "quality/tests/test_x.py"]) == ""
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    (repo / scope.MAP_PATH).write_text(json.dumps({**stamp, "generated": {"tree": f"tree:{tree}"}}))
    assert scope._map_predates(repo, "HEAD", ["quality/new.py"]) == "", "a map of the fork stands"
    picked, _, why = scope.gate_tests_plan(REPO, "HEAD", ["quality/djb/zzz_never_run.py"])
    assert picked is None and why.startswith(NO_GATE_ROWS), "no gate rows outranks the stamp"
    row = {"quality/tests/test_scope.py": {"quality/djb/scope.py"}}
    monkeypatch.setattr(scope, "map_rows", lambda root, map_path=scope.MAP_PATH: row)
    picked, _, why = scope.gate_tests_plan(REPO, "HEAD", ["quality/djb/zzz_never_run.py"])
    assert picked is None and why.startswith("the map predates quality/djb/zzz_never_run.py"), why


NO_GATE_ROWS = f"the map has no rows for {' or '.join(scope.GATE_TESTS)}"


def test_a_map_with_no_gate_rows_answers_whole_even_stamped_at_the_fork(
    scratch_repo: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """2.5 (V-CI-THIRD-CHAIN 3a): a fork-stamped app-suite map vouches for no gate module."""
    repo = scratch_repo()
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    apps_only = {"tests": {"apps/x/tests/test_y.py::t": ["apps/x/services.py"]}}
    (repo / scope.MAP_PATH).write_text(json.dumps(apps_only))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "an app-suite map")
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    stamped = {**apps_only, "generated": {"tree": f"tree:{tree}"}}
    (repo / scope.MAP_PATH).write_text(json.dumps(stamped))
    assert scope.map_rows(repo) == {}
    assert scope._map_predates(repo, "HEAD", ["quality/djb/scope.py"]) == "", "the stamp is trusted"
    monkeypatch.setattr(scope, "map_rows", lambda root, map_path=scope.MAP_PATH: {})
    monkeypatch.setattr(scope, "_map_predates", lambda root, fork, paths: "")
    picked, of, why = scope.gate_tests_plan(REPO, "HEAD", ["quality/djb/scope.py"])
    assert picked is None and why.startswith(NO_GATE_ROWS), why
    assert (
        scope.SelftestPlan(picked, of, why, None, 1, "")
        .lines()[0]
        .startswith(f"gate-tests whole — {NO_GATE_ROWS}")
    )


def test_a_ci_yml_only_diff_runs_every_module_that_reads_it_on_this_trees_map() -> None:
    """2.5 (V-CI-THIRD-CHAIN 3b): imports and spelled reads are no declaration, so it is whole."""
    picked, _, why = scope.gate_tests_plan(REPO, "HEAD", [".github/workflows/ci.yml"])
    assert scope.map_rows(REPO) == {}, "this tree's map gained gate rows: re-read the proof"
    assert picked is None and why.startswith(NO_GATE_ROWS), why


def test_a_test_module_only_diff_still_selects_itself_without_gate_rows() -> None:
    """2.5: a changed gate test module selects itself; self-selection needs no map."""
    mine = "quality/tests/test_ci_derive.py"
    picked, of, why = scope.gate_tests_plan(REPO, "HEAD", [mine])
    assert picked is not None and mine in picked and len(picked) < of, why


def test_a_full_lane_whose_selftest_narrows_says_so_and_names_its_shards() -> None:
    """2.1/2.3: the lane's word for the unit is `narrowed`, and its `units:` carry the count."""
    head = _git(REPO, "rev-parse", "HEAD")
    mine = ["quality/tests/test_ci_derive.py"]
    picked = scope.Lane("full", "", "HEAD", head, mine, planned=True)
    picked.selftest, picked.selftest_why = "ran", "the closure"
    picked.plan_selftest(REPO)
    assert picked.plan is not None and picked.plan.modules is not None
    assert picked.selftest == "narrowed", picked.selftest_why
    (unit,) = [u for u in picked.units if u.startswith("selftest")]
    assert re.fullmatch(r"selftest:[1-9][0-9]*", unit), picked.units
    assert set(picked.units) - {unit} == set(scope.ci_units(REPO)) - {"selftest"}
    unplanned = scope.Lane("full", "", "HEAD", head, [".github/workflows/ci.yml"])
    unplanned.plan_selftest(REPO)
    assert unplanned.plan is None, "the plan is the venv's: `lane --plan` asks for it"


def test_the_plan_line_round_trips_and_a_bad_one_cannot_look(tmp_path: Path) -> None:
    plan = scope.SelftestPlan(("quality/tests/test_a.py",), 9, "", None, 96, "x")
    line = plan.line()
    assert line == "selftest-plan/1 gate-tests=quality/tests/test_a.py engine=whole"
    back = scope.parse_plan(line)
    assert (back.modules, back.rules, back.narrowed) == (plan.modules, None, True)
    assert scope.parse_plan("selftest-plan/1 gate-tests=whole engine=").rules == ()
    held = tmp_path / "plan.txt"
    held.write_text(line + "\n")
    assert scope.read_plan({scope.PLAN_ENV: str(held)}) == back
    assert scope.read_plan({}) is None
    with pytest.raises(CouldNotLook):
        scope.read_plan({scope.PLAN_ENV: str(tmp_path / "absent.txt")})
    with pytest.raises(CouldNotLook):
        scope.parse_plan("selftest-plan/2 gate-tests=whole engine=whole")


@pytest.mark.parametrize(
    ("paths", "want"),
    [
        ([".github/workflows/ci.yml"], None),
        (["quality/djb/ledger.py", ".github/workflows/ci.yml"], ("quality/djb/ledger.py", "C7")),
        (["config/settings/test.py"], ("config/settings/test.py", "C3")),
        (["uv.lock"], ("uv.lock", "C4")),
        (["apps/example/services.py"], ("apps/example/services.py", "C1")),
        (["pilecap/__init__.py"], ("pilecap/__init__.py", "pilecap/")),
    ],
)
def test_the_app_suites_closure_is_the_lockfiles_classes(
    paths: list[str], want: tuple[str, str] | None
) -> None:
    """CI-THIRD-3 3.1: every class the lockfile declares, the facade, and the quote reader."""
    assert scope.pytest_reach(REPO, paths) == want


def test_a_full_lane_off_the_app_suites_closure_marks_pytest_narrowed() -> None:
    """3.1/3.2: `pytest-x2: narrowed` and `pytest-x2:pr` on the units line; else whole."""
    head = _git(REPO, "rev-parse", "HEAD")
    picked = scope.Lane("full", "", "HEAD", head, [".github/workflows/ci.yml"], planned=True)
    picked.plan_pytest(REPO)
    assert (picked.pytest, f"{scope.PYTEST_UNIT}:pr" in picked.units) == ("narrowed", True)
    assert picked.pytest_why.startswith("none of the 1 changed path(s) is in the app suite's")
    picked = scope.Lane("full", "", "HEAD", head, ["uv.lock"], planned=True)
    picked.plan_pytest(REPO)
    assert (picked.pytest, picked.pytest_why) == (
        "whole",
        "uv.lock is in the app suite's closure (C4)",
    )
    assert not any(u.endswith(":pr") for u in picked.units)


def test_a_head_that_is_not_the_checkout_is_could_not_look(world: Path) -> None:
    """The lane reads this checkout's tree: a `--head` elsewhere is exit 2, never a guess."""
    base, head = _branch(world, "apps/leaf/services.py")
    _git(world, "checkout", "-q", "main")
    with pytest.raises(CouldNotLook, match="not this checkout's HEAD"):
        scope.lane(world, base, head)
    said = _cli(world, "lane", "--base", base, "--head", head, floor=True)
    assert (said.returncode, said.stdout) == (2, "")


def test_an_unclassifiable_path_refuses_the_lane_as_it_refuses_the_loop(world: Path) -> None:
    """A path the fan-out table has no row for is exit 2 for the lane too."""
    base, head = _branch(world, "zzz_unplaced.cfg")
    with pytest.raises(scope.Unclassified):
        scope.lane(world, base, head)


def test_a_marked_census_joins_when_its_population_moved_and_one_left_out_is_exit_2(
    world: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CI-THIRD-3 3.3: a census joins the scope its population moves; left out, exit 2."""
    census = "apps/aside/tests/test_zzz_scratch_walker.py"
    (world / census).parent.mkdir(parents=True, exist_ok=True)
    (world / census).write_text(f"{scope.CENSUS_MARKER} population=apps/aside/** walks aside\n")
    commit_all(world, "a marked census")
    touch(world, "apps/leaf/services.py")
    s = derive(world)
    assert (s.own, s.seeded_tests) == (["leaf"], [])
    assert "always-on: 0 of 1 census modules joined — 1 populations unmoved" in notes(s)
    _git(world, "checkout", "-q", "--", ".")
    touch(world, "apps/aside/apps.py")
    s = derive(world)
    assert census in s.seeded_tests
    assert f"--djb-changed-test={census}" in scope.pytest_args(s)
    assert f"seeded={census} " in s.canonical
    assert "always-on: 1 of 1 census modules joined — 0 populations unmoved" in notes(s)
    assert census in derive(world, mine=True).seeded_tests
    monkeypatch.setattr(ao, "census_population", lambda root: [])
    with pytest.raises(SystemExit) as raised:
        scope.main(["--root", str(world)])
    assert raised.value.code == 2
    assert f"NOT in the always-on census set: {census}" in capsys.readouterr().err


def _shim_world(root: Path, owner: str, stderr: str) -> Path:
    """A root whose owner module exists and whose checkout python only fails, saying `stderr`."""
    (root / owner).parent.mkdir(parents=True, exist_ok=True)
    (root / owner).write_text("")
    python = root / ".venv/bin/python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text(f"#!/bin/sh\nprintf '%s\\n' {stderr!r} >&2\nexit 1\n")
    python.chmod(0o755)
    return root


def test_the_env_reads_probe_carries_the_tools_own_lines(tmp_path: Path) -> None:
    said = "ModuleNotFoundError: No module named 'yaml'"
    root = _shim_world(tmp_path, scope.ENV_READS_OWNER, said)
    with pytest.raises(CouldNotLook) as refused:
        scope.env_reads(root)
    assert f"env-reads exited 1\n   the tool said: {said}" in str(refused.value)
    done = subprocess.run(
        ["bash", "-c", f'. "{HOME}/scripts/gate_ledger.sh" >/dev/null 2>&1; loop_env_reads'],
        cwd=root,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    assert done.returncode == 1, done
    assert f"   the tool said: {said}" in done.stderr, done.stderr
