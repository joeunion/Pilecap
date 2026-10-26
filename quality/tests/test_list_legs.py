"""The gate's unit table and `--list-legs`: each mode's announced legs, each refusal at load."""

# deleted: case_the_registered_population_has_one_writer — dies with the shim
# pin: test_the_registered_drives_are_the_registrys_one_reading (registry.shell_drives)
# deleted: case_a_unit_with_no_needs_declaration_is_exit_2 — dies with the shim
# pin: test_every_unit_declares_its_needs_and_a_shards_word (registry.UNITS)
# deleted: case_list_legs_precedes_the_lease — dies with the shim
# pin: test_the_listing_takes_no_lock (cli.main)
# deleted: case_a_ci_view_that_asks_the_listing_for_its_rows_does_not_recurse — dies with the shim
# pin: test_the_ci_listing_is_one_pass_over_the_table (registry.list_legs)
# deleted: case_the_usage_header_names_the_listing — dies with the shim
# pin: test_the_usage_names_the_listing (cli.usage)
# deleted: case_leg_pytest_x2_takes_a_slot — dies with the shim
# pin: test_the_suite_takes_one_slot_and_a_bank_takes_every_slot (legs.pytest_x2)
# deleted: case_a_typed_seed_reaches_both_passes — dies with the shim
# pin: test_a_typed_seed_is_used_and_an_unparsable_one_refused (legs.pytest_x2)
# deleted: case_an_unparsable_seed_is_exit_2 — dies with the shim
# pin: test_a_typed_seed_is_used_and_an_unparsable_one_refused (legs.pytest_x2)
# deleted: case_shard_k_of_n_passes_split_and_group_to_both_passes_under_one_seed — the shim
# pin: test_shard_k_of_n_passes_split_and_group_to_both_passes_under_one_seed (legs.pytest_x2)
# deleted: case_the_shard_census_reads_the_gates_own_flags — dies with the shim
# pin: test_shard_k_of_n_splits_and_groups_and_one_of_one_is_whole (legs.pytest_x2)
# deleted: case_an_empty_shard_is_exit_2 — dies with the shim
# pin: test_a_pass_one_that_collected_nothing_is_2_and_a_red_one_1 (legs.pytest_x2)
# deleted: case_the_pass_two_verdict_quotes_pytests_summary_not_its_captured_log — the shim
# pin: test_a_red_pass_two_names_the_inherited_state_and_its_summary (legs.pytest_x2)
# deleted: case_a_shard_forces_the_partition_to_measure_and_banks_nothing — dies with the shim
# pin: test_a_shard_measures_the_whole_collection_unnarrowed (legs.pytest_x2)
# deleted: case_the_loop_leg_carries_no_split — dies with the shim
# pin: test_shard_k_of_n_splits_and_groups_and_one_of_one_is_whole (legs.pytest_x2)
# deleted: case_the_full_gate_leg_carries_no_split — dies with the shim
# pin: test_shard_k_of_n_splits_and_groups_and_one_of_one_is_whole (legs.pytest_x2)
# deleted: case_a_durations_path_outside_the_rootdir_is_exit_2 — dies with the shim
# pin: test_a_durations_path_outside_the_rootdir_or_through_dotdot_is_refused (legs.pytest_x2)
# narrowed: passes_1_runs_one_pass_and_says_so — the extracted pytest_x2_passes argv halves
# moved: case_a_dry_sharded_selftest_prints_its_plan_with_the_flags_k — test_registry.py
# moved: case_leg_static_announces_its_legs_and_no_other — test_registry.py
# moved: case_leg_takes_no_lease_no_lock_and_writes_no_verdict — test_registry.py
# moved: case_leg_needs_no_sanction — test_registry.py
# moved: case_an_unknown_unit_is_exit_2_naming_the_listing — test_registry.py
# moved: case_shard_on_a_non_pytest_unit_is_exit_2 — test_registry.py
# moved: case_a_malformed_shard_pair_is_exit_2 — test_registry.py
# moved: case_passes_outside_a_shard_or_malformed_is_exit_2 — test_registry.py
# moved: case_passes_1_runs_one_pass_and_says_so — test_registry.py
# moved: case_composed_of_names_the_pass_count — test_registry.py
# moved: case_list_legs_carries_no_pass_count — test_registry.py
# moved: case_collectstatic_is_a_leg_in_the_static_unit — test_registry.py
# moved: case_clone_into_gets_a_main_from_either_source_shape — test_registry.py
# narrowed: every_drive_is_in_exactly_one_drives_unit — the extracted shell body's k/K partition
# narrowed: a_drive_that_appears_in_no_unit_or_two_is_exit_2 — the registry places every drive
# narrowed: list_legs_ci_derives… — the override is planted under the CI column, not another label
# narrowed: a_missing_durations_file_still_partitions_and_says_so — the leg's own note line
# narrowed: the_shards_partition_the_pr_scope_too — the one-assembly read of X2_PASS_ARGS
# typed: the split flags once, as `split` — gate_pytest_split_args dies with the shim
# does-not-cover: what the leg bodies do — every dry run announces legs and runs no body.
# does-not-cover: a body that exits early and skips a later leg; the bank's transcript is that.
# does-not-cover: the `--pr` and `--bank` variants' own narrowing (test_loop_scope.sh's).
# does-not-cover: a drive file registered nowhere; the instrument census asks that.

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from collections.abc import Callable, Mapping
from pathlib import Path
from xml.etree import ElementTree

import pytest

from quality.could_not_look import CouldNotLook
from quality.djb import cli, ledger
from quality.djb import registry as R
from quality.tests.fixtures import shell_gate
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.checkout import add_checkout, remove_checkout
from quality.tests.fixtures.collection_world import (
    WORLD_FLOOR,
    WORLD_NARROWED_FLOOR,
    World,
    world_labels,
)

pytestmark = pytest.mark.drives(
    ".github/workflows/ci.yml",
    "docs/product/build-contract.md",
    "scripts/check.sh",
    "scripts/gate_ledger.sh",
    "scripts/gate_member_durations.json",
    "scripts/db.sh",
    "apps/conftest.py",
    "config/",
    "quality/tests/fixtures/collection_world/",
)

ROOT = Path(__file__).resolve().parents[2]
GATE_TEXT = shell_gate.text()
FIXTURE_FAST = (
    "db-pin ruff sdk-reference mypy import-linter djb-checks house-rules migrations"
    " goalpost-census queue-index"
    " ledger-check archaeology adr-census dangling-docs ci-env collection-census"
).split()
FIXTURE_LOOP = [
    *FIXTURE_FAST,
    *"deploy-check plant-collisions fe secrets always-on pytest".split(),
]
FIXTURE_FULL = [
    *FIXTURE_FAST,
    *(
        "deploy-check plant-collisions fe collectstatic threat-census"
        " supply-chain pytest-x2 selftest"
    ).split(),
    *R.DRIVE_NAMES,
    *"gate-tests full-house-rules".split(),
]
DRY = {
    "DJB_GATE_LEGS_DRY": "1",
    "DJB_LOOP_HERE": "test_list_legs: a DRY sequence census — no body runs, nothing measured",
    "DJB_GATE_SANCTION": "test_list_legs: the dry sequence census — every leg announced, no body",
}
ANNOUNCED = re.compile(r"^  leg: ([a-z0-9_-]+) \(DJB_GATE_LEGS_DRY", re.MULTILINE)
CONTRACT = "docs/product/build-contract.md"
SIBLING = CONTRACT.removesuffix(".md") + ".local.md"
_RUNS: dict[tuple[str, ...], str] = {}


def dry(gate: Callable[..., object], clone: Path, *args: str) -> str:
    """The transcript of a dry `check.sh <args>` in `clone`, once per module."""
    if args not in _RUNS:
        env = {**DRY, "DJB_GATE_LEASE_DIR": str(clone.parent / "lease")}
        ran = gate(*args, cwd=clone, env=env)
        assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
        _RUNS[args] = ran.text()  # type: ignore[attr-defined]
    return _RUNS[args]


def announced(text: str) -> list[str]:
    return ANNOUNCED.findall(text)


def rows(text: str) -> dict[str, list[str]]:
    return {line.split("\t")[0]: line.split("\t") for line in text.splitlines() if line}


def listing(ci: bool = False) -> str:
    return R.list_legs(R.load(ROOT), ci=ci, root=ROOT)


def population() -> set[str]:
    table = R.load(ROOT)
    return {*ledger.full_legs(ROOT), *R.DRIVE_NAMES, *(g.name for g in table.legs if g.unit != "-")}


def planted(after: str, line: str, *, replace: bool = False, text: str = GATE_TEXT) -> str:
    """`text` with `line` beside (or instead of) the first line starting `after`."""
    lines = text.split("\n")
    at = next(i for i, x in enumerate(lines) if x.startswith(after))
    lines[at : at + 1] = [line] if replace else [line, lines[at]]
    return "\n".join(lines)


def test_an_empty_capture_is_could_not_look(scratch: Path) -> None:
    empty = scratch / "empty.out"
    empty.write_text("")
    with pytest.raises(CouldNotLook, match="empty or absent"):
        Captured(0, empty).text()
    with pytest.raises(CouldNotLook, match="empty or absent"):
        Captured(0, scratch / "absent.out").text()
    full = scratch / "listing.out"
    full.write_text("unit\tneeds\tshards\tlegs\n")
    assert Captured(2, full).text().startswith("unit")


def test_the_full_fast_and_loop_leg_sequences_are_unchanged_by_the_refactor(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    assert announced(dry(gate, dry_clone, "--fast")) == FIXTURE_FAST
    assert announced(dry(gate, dry_clone, "--loop")) == FIXTURE_LOOP
    full = dry(gate, dry_clone)
    assert announced(full) == FIXTURE_FULL
    assert "no verdict recorded — DJB_GATE_LEGS_DRY" in full


def test_an_announced_leg_whose_body_is_not_behind_the_runner_is_exit_2(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "path", [str(scratch), *sys.path])
    home = scratch / "planted_legs_inline"
    home.mkdir()
    (home / "__init__.py").write_text("")
    (home / "zzz_inline.py").write_text(
        textwrap.dedent(
            """\
            from quality.djb.registry import Leg
            LEG = Leg("zzz-inline", "full-house-rules", "an inline leg")
            """
        )
    )
    with pytest.raises(R.RegistryError, match="leg 'zzz-inline' has no body"):
        R.discover("planted_legs_inline")


def test_full_legs_equals_the_announced_full_sequence(
    gate: Callable[..., object], dry_clone: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seen = list(dict.fromkeys(announced(dry(gate, dry_clone))))
    assert seen == ledger.full_legs(ROOT)
    assert cli.main(["--list-legs"]) == 0
    assert capsys.readouterr().out == listing()


def test_an_announced_leg_missing_from_full_legs_is_exit_2() -> None:
    text = planted(
        "gate_run_body full-house-rules ",
        'gate_run_body zzz-probe gate_leg_full_house_rules zzz-nounit "a probe leg"',
    )
    with pytest.raises(R.RegistryError, match="leg 'zzz-probe' in unit 'zzz-nounit'"):
        R.build(R.discover(), text)


def test_the_registered_drives_are_the_registrys_one_reading() -> None:
    drives = list(R.DRIVE_NAMES)
    assert drives, "the registry's drive table names no drive"
    selftest = rows(listing())["selftest"][3].split(",")
    assert selftest[1 : 1 + len(drives)] == drives


def test_every_full_leg_is_in_exactly_one_unit() -> None:
    members = [m for row in rows(listing()).values() for m in row[3].split(",")]
    assert len(members) == len(set(members)), sorted(m for m in members if members.count(m) > 1)
    assert set(members) == population()


def test_a_leg_in_two_units_is_exit_2() -> None:
    first = next(x for x in GATE_TEXT.split("\n") if R.shell_legs(x))
    text = planted(first, 'gate_run_body ruff gate_leg_ruff full-house-rules "ruff again"')
    with pytest.raises(R.RegistryError, match="a leg in two units"):
        R.build(R.discover(), text)


def test_a_leg_in_no_unit_is_exit_2() -> None:
    text = "\n".join(
        x for x in GATE_TEXT.split("\n") if not x.startswith("gate_unit full-house-rules ")
    )
    units = [u for u in R.UNITS if u.name != "full-house-rules"]
    with pytest.raises(R.RegistryError, match="names unit 'full-house-rules', which is not one of"):
        R.build(R.discover(), text, units)


def test_every_unit_declares_its_needs_and_a_shards_word() -> None:
    assert [u.name for u in R.UNITS] == R.shell_units(GATE_TEXT)
    for unit in R.UNITS:
        assert unit.needs and all(unit.needs), unit.name
        assert unit.shards in {"0", "N-capable"}, unit.name


def test_list_legs_prints_one_line_per_unit_in_the_grammar() -> None:
    text = listing()
    table = rows(text)
    assert table, "the listing printed no rows"
    known = population()
    for unit, row in table.items():
        assert len(row) == 4, unit
        assert row[1], unit
        assert row[2] in {"0", "N-capable"}, unit
        assert row[3] and set(row[3].split(",")) <= known, unit
    assert len(text.splitlines()) == len(table)


def test_list_legs_needs_no_venv_and_no_docker(gate: Callable[..., object], checkout: Path) -> None:
    assert not (checkout / ".venv").exists()
    ran = gate("--list-legs", cwd=checkout, env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin"})
    assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
    assert len(rows(ran.text())) == len(R.UNITS)  # type: ignore[attr-defined]


def test_a_disagreeing_pin_does_not_reach_the_listing(
    gate: Callable[..., object], capture: Callable[..., object], checkout: Path
) -> None:
    clean = gate("--list-legs", cwd=checkout)
    (checkout / ".env").write_text("# pinned\nDATABASE_NAME=djb_zzz_list_legs_pin\n")
    pinned = gate("--list-legs", cwd=checkout)
    assert (clean.rc, pinned.rc) == (0, 0)  # type: ignore[attr-defined]
    assert pinned.text() == clean.text()  # type: ignore[attr-defined]
    sourced = capture(["bash", "-c", ". scripts/db.sh"], cwd=checkout)
    assert "note: DATABASE_NAME pinned to djb_zzz_list_legs_pin" in sourced.text()  # type: ignore[attr-defined]


def test_the_listing_takes_no_lock(capsys: pytest.CaptureFixture[str]) -> None:
    git_dir = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "--absolute-git-dir"], text=True
    ).strip()
    lock = Path(git_dir) / "djb-gate-lock"
    before = lock.exists()
    assert cli.main(["--list-legs"]) == 0
    assert capsys.readouterr().out
    assert lock.exists() == before


def test_list_legs_with_an_argument_is_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--list-legs", "zzz"]) == 2
    assert "unexpected extra arguments: zzz" in capsys.readouterr().err


def _count(walls: Mapping[str, float], members: list[str]) -> int:
    """This module's own ceil(sum / max(heaviest, 300)), raised while its LPT passes the bound."""
    seen = sorted(walls[m] for m in members if m in walls)
    mid = len(seen) // 2
    median = 0 if not seen else seen[mid] if len(seen) % 2 else (seen[mid - 1] + seen[mid]) // 2
    weights = [walls.get(m, median) for m in members]
    n = int(max(1, -(-sum(weights) // max(max(weights), 300))))
    while n < len(weights) and _lpt(weights, n) > max(max(weights), 600):
        n += 1
    return n


def _lpt(weights: list[float], n: int) -> float:
    """The heaviest of `n` shards when `weights` go longest-first onto the lightest."""
    load = [0.0] * n
    for w in sorted(weights, reverse=True):
        load[load.index(min(load))] += w
    return max(load)


def test_list_legs_ci_derives_the_selftest_count_and_carries_passes(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bare, ci = rows(listing()), rows(listing(ci=True))
    assert list(bare) == list(ci)
    for unit, row in ci.items():
        assert len(row) == 5, unit
        assert [row[0], row[1], row[3]] == [bare[unit][0], bare[unit][1], bare[unit][3]]
    members = [R.ENGINE_MEMBER if m == "selftest" else m for m in ci["selftest"][3].split(",")]
    homes = [ROOT / h for h in R.WALLS_HOMES]
    walls = R.walls_view(homes, R.CI_MACHINE, only=True)
    assert walls, "the walls table carries no ubuntu-latest column"
    split, units = R.load(ROOT).pieces(), R.load(ROOT).units(ROOT)
    parts = R.member_parts(homes, R.CI_MACHINE, units)
    assert ci["selftest"][2] == str(_count(*R.pieced(walls, members, split, parts)))
    for unit, row in ci.items():
        want = ("N-capable", "1") if unit == "pytest-x2" else (row[2], "")
        assert (row[2], row[4]) == want, unit
        if unit not in {"pytest-x2", "selftest"}:
            assert row[2] == "0", unit
    for plant in ({m: 100 for m in members}, {**{m: 100 for m in members}, R.ENGINE_MEMBER: 5000}):
        path = scratch / "walls.json"
        doc = {"measured_at": "run:1 tree:planted", "machine": R.CI_MACHINE, "members": plant}
        path.write_text(json.dumps(doc))
        monkeypatch.setenv("DJB_GATE_MEMBER_WALLS_CI", str(path))
        planted = R.member_parts([path], R.CI_MACHINE, units)
        assert rows(listing(ci=True))["selftest"][2] == str(
            _count(*R.pieced(plant, members, split, planted))
        )
    for extra in (["--x"], ["--ci", "--x"], ["zzz", "--ci"]):
        assert cli.main(["--list-legs", *extra]) == 2, extra
        assert capsys.readouterr().err.startswith("!! ")


def test_the_ci_listing_is_one_pass_over_the_table(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    loads: list[Path] = []
    real_load = R.load

    def counted(root: Path) -> R.Table:
        loads.append(root)
        return real_load(root)

    def no_child(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"the listing started a process: {args[:1]}")

    monkeypatch.setattr(cli, "load", counted)
    monkeypatch.setattr(subprocess, "Popen", no_child)
    assert cli.main(["--list-legs", "--ci"]) == 0
    out = capsys.readouterr().out
    assert out and all(len(line.split("\t")) == 5 for line in out.splitlines())
    assert len(loads) == 1, f"the table was loaded {len(loads)} times for one listing"


def test_a_refusal_under_ci_is_the_bare_listings_refusal(
    scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (scratch / "scripts").mkdir()
    unit = next(x for x in GATE_TEXT.split("\n") if x.startswith("gate_unit full-house-rules "))
    ghost = f"{unit}\ngate_unit zzz-ghost none 0 no-such-leg"
    (scratch / R.GATE).write_text(GATE_TEXT.replace(unit, ghost, 1))
    said = []
    for extra in ([], ["--ci"]):
        with pytest.raises(SystemExit) as stopped:
            cli.main(["--list-legs", *extra], root=scratch)
        assert stopped.value.code == 2
        out, err = capsys.readouterr()
        assert out == ""
        said.append(err)
    assert said[0] == said[1]
    assert said[0].startswith("!! the leg table does not validate:") and "zzz-ghost" in said[0]


def test_an_unknown_flag_is_still_exit_2_with_the_same_sentence(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    ran = gate("--zzz-not-a-mode", cwd=dry_clone)
    line = ran.text().splitlines()[0]  # type: ignore[attr-defined]
    assert ran.rc == 2  # type: ignore[attr-defined]
    assert line.startswith("!! unknown argument '--zzz-not-a-mode': check.sh takes ")
    assert "--list-legs" in line


def test_the_usage_names_the_listing(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--help"]) == 0
    assert re.search(r"^  --list-legs \[--ci\]", capsys.readouterr().out, re.MULTILINE)


def test_every_drive_is_in_exactly_one_drives_unit() -> None:
    drives = R.shell_drives(GATE_TEXT)
    table = rows(listing())
    holders = [u for u, row in table.items() for d in drives if d in row[3].split(",")]
    assert holders == ["selftest"] * len(drives)
    assert len(drives) == len(set(drives))


def test_a_drive_that_appears_in_no_unit_or_two_is_exit_2() -> None:
    first = next(x for x in GATE_TEXT.split("\n") if R.shell_drives(x))
    twice = planted(first, first)
    with pytest.raises(R.RegistryError, match="is registered twice"):
        R.build(R.discover(), twice)


def contract_misses(root: Path, listed: str) -> tuple[list[str], list[str]]:
    """Units with no byte-identical contract row: (the template's, the product's own)."""
    docs = root / CONTRACT, root / SIBLING
    text = "".join(d.read_text(encoding="utf-8") for d in docs if d.is_file())
    template: list[str] = []
    product: list[str] = []
    for unit, row in rows(listed).items():
        if f"| `{unit}` | {row[1]} | {row[2]} | {row[3]} |" in text.splitlines():
            continue
        local = any(m.startswith("local:") for m in row[3].split(","))
        (product if local else template).append(unit)
    return template, product


def test_the_build_contract_table_equals_the_listing(
    gate: Callable[..., object], dry_clone: Path
) -> None:
    ran = gate("--list-legs", cwd=dry_clone)
    assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
    assert contract_misses(ROOT, ran.text()) == ([], [])  # type: ignore[attr-defined]


def test_a_products_unit_row_lives_in_the_local_sibling(
    gate: Callable[..., object], checkout: Path
) -> None:
    drawer = checkout / "scripts/local/legs"
    drawer.mkdir(parents=True)
    leg = drawer / "x.sh"
    leg.write_text(
        "#!/usr/bin/env bash\n# >>> leg v1 >>>\n# unit: local\n# needs: none\n# tier: full\n"
        '# <<< leg <<<\necho "x: this is a planted product leg"\nexit 0\n'
    )
    leg.chmod(0o755)
    ran = gate("--list-legs", cwd=checkout)
    assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
    assert rows(ran.text())["local"] == ["local", "none", "0", "local:x"]  # type: ignore[attr-defined]
    sibling = checkout / SIBLING
    head = "# The product's units\n\n| unit | needs | shards | composed-of |\n|---|---|---|---|\n"
    expected = "| `local` | none | 0 | local:x |"
    sibling.write_text(f"{head}{expected}\n")
    assert contract_misses(checkout, ran.text()) == ([], [])  # type: ignore[attr-defined]
    sibling.unlink()
    assert contract_misses(checkout, ran.text()) == ([], ["local"])  # type: ignore[attr-defined]
    drives = checkout / "scripts/local/drives"
    drives.mkdir()
    drive = drives / "test_y.sh"
    drive.write_text('#!/usr/bin/env bash\n. scripts/tests/drive_preamble.sh\necho "y"\n')
    drive.chmod(0o755)
    grown = gate("--list-legs", cwd=checkout)
    selftest = rows(grown.text())["selftest"]  # type: ignore[attr-defined]
    assert "local:y" in selftest[3].split(",")
    sibling.write_text(f"{head}{expected}\n")
    assert contract_misses(checkout, grown.text()) == ([], ["selftest"])  # type: ignore[attr-defined]
    row = "| `{}` | {} | {} | {} |".format(*selftest)
    sibling.write_text(f"{head}{expected}\n{row}\n")
    assert contract_misses(checkout, grown.text()) == ([], [])  # type: ignore[attr-defined]


#: `gate_pytest_split_args`' flags, typed once here: the shell reader dies with the shim.
DURATIONS = "scripts/pytest_durations.json"


def split(k: int, n: int, durations: str = DURATIONS) -> list[str]:
    """The flags shard k/n carries; shard 1/1 is the whole unit and carries none."""
    return [] if n == 1 else ["--splits", str(n), "--group", str(k), "--durations-path", durations]


def partition_misses(whole: list[str], shards: list[list[str]]) -> tuple[list[str], ...]:
    """(in two shards, in no shard, not in the whole): all three empty is a partition."""
    union = sorted(x for shard in shards for x in shard)
    dupes = sorted({x for x in union if union.count(x) > 1})
    return dupes, sorted(set(whole) - set(union)), sorted(set(union) - set(whole))


def test_an_empty_fixture_world_is_could_not_look(collection_world: World) -> None:
    short = [t for t in collection_world.targets if t != "apps/world_delta"]
    runs = {"short": ["--randomly-seed=7"], "restored": ["--randomly-seed=7"]}
    got = collection_world.collect({"short": runs["short"]}, targets=short)
    got |= collection_world.collect({"restored": runs["restored"]})
    held = got["short"].ids()
    assert len(held) < WORLD_FLOOR, f"{len(held)} items without world_delta still clear the floor"
    with pytest.raises(CouldNotLook, match=f"under the floor of {WORLD_FLOOR}"):
        got["short"].ids(WORLD_FLOOR)
    assert len(got["restored"].ids(WORLD_FLOOR)) >= WORLD_FLOOR


def test_the_shards_partition_the_collection_for_three_n_and_two_seeds(
    collection_world: World,
) -> None:
    runs: dict[str, list[str]] = {}
    for seed in (7, 4242):
        runs[f"whole-{seed}"] = [f"--randomly-seed={seed}"]
        for n in (1, 3, 7):
            for k in range(1, n + 1):
                runs[f"{seed}-{n}-{k}"] = [f"--randomly-seed={seed}", *split(k, n)]
    got = collection_world.collect(runs)
    for seed in (7, 4242):
        whole = got[f"whole-{seed}"].ids(WORLD_FLOOR)
        for n in (1, 3, 7):
            shards = [got[f"{seed}-{n}-{k}"].ids() for k in range(1, n + 1)]
            assert partition_misses(whole, shards) == ([], [], []), (seed, n)


def test_the_partition_holds_under_the_real_worker_count(collection_world: World) -> None:
    plain = [f"apps/{label}/tests/test_plain.py" for label in world_labels(ROOT)]
    sinks = collection_world.sinks

    def ran(name: str, flags: list[str]) -> list[str]:
        xml = sinks / f"junit-{name}.xml"
        args = ["-n", "2", "-p", "no:cacheprovider", "--randomly-seed=7", *flags]
        done = collection_world.pytest(f"xdist-{name}", [*args, f"--junitxml={xml}", *plain])
        if done.rc != 0:
            raise CouldNotLook(f"the {name} run of the plain modules exited {done.rc}: {done.path}")
        cases = ElementTree.parse(xml).getroot().iter("testcase")  # noqa: S314 — the junit file this test's own pytest run just wrote
        return sorted(f"{c.get('classname')}::{c.get('name')}" for c in cases)

    whole = ran("whole", [])
    assert whole, "the plain modules ran nothing at -n 2 — this case has no subject"
    shards = [ran(f"{k}-of-2", split(k, 2)) for k in (1, 2)]
    assert partition_misses(whole, shards) == ([], [], [])


def test_a_missing_durations_file_still_partitions_and_says_so(collection_world: World) -> None:
    absent = collection_world.sinks / "no-such-durations.json"
    got = collection_world.collect(
        {"nodurations": ["--randomly-seed=7", *split(1, 3, str(absent))]}
    )
    assert got["nodurations"].ids(), "a missing durations file emptied the shard"
    assert "no test durations found" in got["nodurations"].text().lower()


def test_a_durations_file_naming_tests_that_no_longer_exist_still_partitions(
    collection_world: World,
) -> None:
    stale = collection_world.root / ".zzz-stale-durations.json"
    if stale.exists():
        raise CouldNotLook(
            f"{stale} already exists — this case will not overwrite a file it did not make"
        )
    gone = "apps/zzz_gone/tests/test_gone.py"
    stale.write_text(json.dumps({f"{gone}::test_one": 12.5, f"{gone}::test_two": 3.25}))
    try:
        runs = {"stale-whole": ["--randomly-seed=7"]}
        runs |= {f"stale-{k}": ["--randomly-seed=7", *split(k, 3, stale.name)] for k in (1, 2, 3)}
        got = collection_world.collect(runs)
    finally:
        stale.unlink()
    whole = got["stale-whole"].ids(WORLD_FLOOR)
    shards = [got[f"stale-{k}"].ids() for k in (1, 2, 3)]
    assert partition_misses(whole, shards) == ([], [], [])


def test_the_shards_partition_the_pr_scope_too(
    collection_world: World, gate: Callable[..., object], dry_clone: Path
) -> None:
    scope = ["--randomly-seed=7", "--djb-scope-narrow", "--djb-scope=world_alpha"]
    runs = {"pr-whole": scope, **{f"pr-{k}": [*scope, *split(k, 3)] for k in (1, 2, 3)}}
    got = collection_world.collect(runs)
    whole = got["pr-whole"].ids(WORLD_NARROWED_FLOOR)
    assert "deselected" in got["pr-whole"].text(), "the scope flags deselected nothing"
    shards = [got[f"pr-{k}"].ids() for k in (1, 2, 3)]
    assert partition_misses(whole, shards) == ([], [], [])
    ran = gate("--leg", "pytest-x2", "--shard", "1/3", "--pr", cwd=dry_clone)
    assert ran.rc == 2, ran.text()  # type: ignore[attr-defined]
    assert "--pr needs --base" in ran.text()  # type: ignore[attr-defined]


def test_the_dry_loop_derives_a_scope_from_a_source_ahead_of_main(
    gate: Callable[..., object], scratch: Path
) -> None:
    def git(where: Path, *args: str) -> str:
        return subprocess.check_output(["git", "-C", str(where), *args], text=True).strip()

    refs = ("refs/heads/main", "refs/remotes/origin/main")
    base = next(
        (
            r
            for r in refs
            if subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "--verify", "-q", f"{r}^{{commit}}"],
                capture_output=True,
            ).returncode
            == 0
        ),
        None,
    )
    if base is None:
        raise CouldNotLook(f"no base ref in {ROOT} — this case has no sha to fork from")
    probe = "apps/example/services.py"
    src = scratch / "src"
    git(scratch, "clone", "-q", "--shared", "--no-hardlinks", str(ROOT), str(src))
    git(src, "checkout", "-q", "-B", "main", git(ROOT, "rev-parse", f"{base}^{{commit}}"))
    git(src, "checkout", "-q", "-b", "scratch-ahead")
    with (src / probe).open("a") as f:
        f.write("\n# g10f probe\n")
    git(src, "add", probe)
    git(
        src,
        "-c",
        "user.email=drive@example.invalid",
        "-c",
        "user.name=list legs",
        "commit",
        "-q",
        "-m",
        "probe: one app path ahead of main",
    )
    (scratch / "lease").mkdir()
    env = {**DRY, "DJB_GATE_LEASE_DIR": str(scratch / "lease")}
    said = []
    for shape in ("ahead", "onmain"):
        if shape == "onmain":
            git(src, "checkout", "-q", "main")
        clone = add_checkout(src, scratch / shape)
        (clone / ".venv").symlink_to(ROOT / ".venv")
        assert git(clone, "rev-parse", "main") == git(src, "rev-parse", "main")
        ran = gate("--loop", cwd=clone, env=env)
        assert ran.rc == 0, ran.text()  # type: ignore[attr-defined]
        said.append(ran.text())  # type: ignore[attr-defined]
        remove_checkout(src, clone)
    assert "scope   touched: example" in said[0], said[0][-600:]
