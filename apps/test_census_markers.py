"""Every declared cross-app census walks something, and every walker declares itself.

WHAT THIS IS FOR. `apps/conftest.py`'s always-on set decides which tests survive
a `--loop` scope. Two of its three ways in are DERIVED from what a module reads
through a Django registry; the third is DECLARED by the module itself, because a
census that walks the source tree BY PATH reads no registry and no token can see
it. A declaration is a claim a human wrote, and a claim a human wrote goes stale
in both directions:

  FORWARD — a marker on a module that walks nothing. The module joins the
  always-on set and every scope pays for it forever, and nobody notices because
  the only symptom is a slightly slower loop.

  REVERSE — a walker with no marker. The module is deselected by every scope
  that does not contain its app, which is to say by every scope except the one
  whose app the census was least likely to be about. That is not a narrowing,
  it is a hole, and its only symptom is a green loop.

Both halves are checked here, over the SAME population — the modules a nested
`pytest --collect-only -q` actually collects — so a module that stopped being
collected at all cannot sit in either answer.

THE POPULATION IS COLLECTED, NEVER GLOBBED, and that is the expensive choice
made deliberately: the set this is about is the set the scope deselects from,
and that is pytest's collection, not a directory listing. The nested collection
costs the wall of one `--collect-only` (measured ~8 s on the platform's Mac,
2026-09-18) and it is paid on every `--loop`, because this module sits at the
apps root and is therefore always-on by construction.

WHAT IT DOES NOT COVER, declared rather than discovered:

  * A WALKER SPELLED WITH A TOKEN OUTSIDE `DJB_WALK_TOKENS`. The reverse half
    re-derives only what that hand list can see, so a census that walks the tree
    through, say, `os.walk` or a `Path.iterdir` recursion escapes both halves
    identically. The list is the blind spot; a fifth token joins it the day a
    miss names one.
  * WHETHER A REASON IS TRUE. The grammar makes a reason mandatory and this
    makes a token mandatory; neither can read a sentence. A reason that
    describes the wrong population is a reviewer's finding, and the reason is in
    the module's first lines so that a reviewer has one place to look.
  * WHETHER AN ALWAYS-ON MODULE PASSES. Nothing here runs a test; the loop and
    the full gate do that.
  * THE COST. That the marked set is worth its seconds is measured in the rung
    report, not asserted here.
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import types
from typing import Any

import pytest

from apps.conftest import (
    DJB_CENSUS_MARKER,
    DJB_CENSUS_POPULATION,
    DJB_REACH_KINDS_KEY,
    DJB_REACH_TOKENS,
    DJB_WALK_TOKENS,
    _always_on_banner,
    _census_banner,
    _census_population_or_refuse,
    _census_verdict,
    _drawer_reach_kinds,
    _drawer_unknown_keys,
    _impact_selection,
    _module_census_population,
    _module_census_reason,
    _module_reach,
    _way_in,
)

#: The checkout root. `apps/test_census_markers.py` -> the directory above `apps`.
REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Every token that makes a module always-on WITHOUT a marker, plus every token
#: a marker is allowed to stand on. Derived from the two declarations in the
#: sentinel block so that this file holds no second copy of either.
MARKER_EVIDENCE: tuple[str, ...] = tuple(
    sorted(
        {token for tokens in DJB_REACH_TOKENS.values() for token in tokens} | set(DJB_WALK_TOKENS)
    )
)


class _CollectedModules:
    """A nested run's collected MODULES, recorded rather than parsed off stdout.

    `--collect-only -q` prints one line per item and the module is the head of
    the nodeid; reading `session.items` asks the same question of the same run
    without a text format in between.
    """

    def __init__(self) -> None:
        self.paths: list[pathlib.Path] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        self.paths = sorted({pathlib.Path(str(item.path)) for item in session.items})


def _collected_modules(root: pathlib.Path, target: pathlib.Path) -> list[str]:
    """Every module a nested `pytest --collect-only -q` collected, `root`-relative.

    AN UNREADABLE INPUT IS COULD-NOT-LOOK, never an empty population: a nested
    collection that refused would otherwise read as a tree with no censuses in
    it, and both halves below would pass by having nothing to look at.
    `pytest.exit(..., returncode=4)` is how a test says that here — pytest's own
    usage-error status, which `scripts/check.sh` maps to exit 2 along with 3 and
    5.

    THE NESTED RUN'S OUTPUT IS HELD, NOT DISCARDED. `--collect-only -q` prints
    one line per collected item — four thousand of them on this tree — into the
    OUTER test's captured stdout, where they are reprinted under every failure
    that has nothing to do with them. It goes into a buffer instead, and the
    tail of that buffer is pasted into the refusal above, which is the one place
    a reader needs it.
    """
    recorder = _CollectedModules()
    held = io.StringIO()
    with contextlib.redirect_stdout(held), contextlib.redirect_stderr(held):
        status = pytest.main(
            [
                "--collect-only",
                "-q",
                "-p",
                "no:randomly",
                "-p",
                "no:cacheprovider",
                str(target),
            ],
            plugins=[recorder],
        )
    if int(status) != 0:
        tail = "\n".join(held.getvalue().splitlines()[-20:])
        pytest.exit(
            f"apps/test_census_markers.py could not collect {target} "
            f"(nested pytest exited {int(status)}). Nothing was asserted about the "
            f"census markers: an underived population is not an empty one.\n{tail}",
            returncode=4,
        )
    return sorted(path.relative_to(root).as_posix() for path in recorder.paths)


def _is_apps_root_module(module: str) -> bool:
    """`apps/test_x.py` — owned by no app, so always-on by construction.

    The same shape `apps/conftest.py::_population_members` reads, asked of a
    path rather than of a nodeid so that a planted world under `tmp_path` is
    judged by exactly the rule the real tree is.
    """
    parts = module.split("/")
    return len(parts) == 2 and parts[0] == "apps" and parts[1].startswith("test_")


def _census(root: pathlib.Path, modules: list[str]) -> tuple[list[str], list[str], int, int]:
    """(forward offences, reverse offences, marked, walkers) over `modules`."""
    forward: list[str] = []
    reverse: list[str] = []
    marked = 0
    walkers = 0
    for module in modules:
        path = root / module
        source = path.read_text(encoding="utf-8")
        reason = _module_census_reason(str(path))
        walks = any(token in source for token in DJB_WALK_TOKENS)
        if reason:
            marked += 1
            if not any(token in source for token in MARKER_EVIDENCE):
                forward.append(
                    f"{module} declares itself a cross-app census ({reason!r}) and its "
                    "source names no population token at all — remove the marker, or "
                    "name the population it walks"
                )
        if walks:
            walkers += 1
            if reason or _module_reach(str(path)) or _is_apps_root_module(module):
                continue
            reverse.append(
                f"{module} walks the source tree and is always-on at NO scope. Paste "
                f"this at column zero in its first lines:\n"
                f"        {DJB_CENSUS_MARKER} <what population it walks>"
            )
    return forward, reverse, marked, walkers


def _announce(capsys: Any, line: str) -> None:
    """One line a reader of a serial run sees, and NOT through `print`.

    House rule 19's census (`apps/core/tests/test_observability.py`) skips
    `/tests/` and `/migrations/` and nothing else, so an apps-root module — this
    one — is inside its population and a `print(` here is a house-rule
    violation. The rule is about production logging and this is a reader's note
    in a test, so the note goes out the one way that is neither a logger nor a
    print. Under xdist a worker's stdout does not reach the run's log; the
    reader-facing copy of this list is the `--loop` banner, which
    `scripts/check.sh` prints from `loop_scope__declared_censuses`.
    """
    with capsys.disabled():
        sys.stdout.write(f"\n{line}\n")


@pytest.fixture(scope="module")
def tree_modules() -> list[str]:
    """The real tree's collected modules — collected ONCE for both halves."""
    return _collected_modules(REPO_ROOT, REPO_ROOT / "apps")


def test_every_declared_census_names_a_population_it_walks(
    tree_modules: list[str], capsys: Any
) -> None:
    """FORWARD. A marker with no census behind it is a permanent scope tax."""
    forward, _reverse, marked, walkers = _census(REPO_ROOT, tree_modules)
    _announce(capsys, f"census markers: {marked} marked, {walkers} walkers")
    assert forward == [], "\n    " + "\n    ".join(forward)


def test_every_walker_declares_itself(tree_modules: list[str]) -> None:
    """REVERSE. A census with no marker is a hole every scope falls through."""
    _forward, reverse, _marked, _walkers = _census(REPO_ROOT, tree_modules)
    assert reverse == [], "\n    " + "\n    ".join(reverse)


# --- the canaries: three planted worlds, collected the same way ---------------
#
# THE PLANTS BUILD THEIR OWN VICTIMS, under `tmp_path`, shaped like `apps/<x>/`
# so that `_is_apps_root_module` and `_module_reach` judge them by the same rules
# they judge the real tree by. Nothing is planted in the checkout: this module is
# read by the reverse half above, and a plant beside it would be a census of the
# test that is censusing it.

_PLANT_TEST = "\n\ndef test_a_planted_module() -> None:\n    assert True\n"

#: A source line that WALKS, assembled from the declaration rather than spelled.
#: Spelled whole it would put a walk token into this module's own source, and
#: this module is inside the population the reverse half reads — a guard counting
#: a token it finds in a fixture is the class `scripts/tests/test_loop_tier.sh`
#: assembles its Temporal plant to avoid.
_PLANT_WALK = '"""A plant."""\n\nimport pathlib\n\nWALKED = list(pathlib.Path("apps")' + (
    DJB_WALK_TOKENS[1] + '"*.py"))\n'
)


def _plant(tmp_path: pathlib.Path, name: str, head: str) -> pathlib.Path:
    """One planted module under `tmp_path/apps/planted/tests/`, and the root."""
    root = tmp_path / name
    where = root / "apps" / "planted" / "tests"
    where.mkdir(parents=True, exist_ok=True)
    (where / f"test_{name}.py").write_text(head + _PLANT_TEST, encoding="utf-8")
    return root


def test_a_planted_marker_with_no_census_behind_it_is_caught(tmp_path: pathlib.Path) -> None:
    """The forward half's canary: marked, and its source walks nothing."""
    root = _plant(tmp_path, "marked_empty", f"{DJB_CENSUS_MARKER} walks the whole tree, honest")
    modules = _collected_modules(root, root / "apps")
    assert modules, "the planted world collected nothing — the canary cannot fire"
    forward, reverse, marked, walkers = _census(root, modules)
    assert len(forward) == 1, f"the forward half did not catch the plant: {forward}"
    assert "names no population token" in forward[0]
    assert (reverse, marked, walkers) == ([], 1, 0)


def test_a_planted_census_with_no_marker_is_caught(tmp_path: pathlib.Path) -> None:
    """The reverse half's canary: it walks, and it says nothing."""
    root = _plant(tmp_path, "walker_unmarked", _PLANT_WALK)
    modules = _collected_modules(root, root / "apps")
    forward, reverse, marked, walkers = _census(root, modules)
    assert len(reverse) == 1, f"the reverse half did not catch the plant: {reverse}"
    assert "walks the source tree and is always-on at NO scope" in reverse[0]
    assert DJB_CENSUS_MARKER in reverse[0], "the failure does not print the line to paste"
    assert (forward, marked, walkers) == ([], 0, 1)


def test_a_planted_census_that_declares_itself_is_green(tmp_path: pathlib.Path) -> None:
    """The third direction, and it is not decoration: a census that answered
    "offence" for everything would pass both cases above."""
    head = (
        f"{DJB_CENSUS_MARKER} walks every module under apps/ for the plant's sake\n" + _PLANT_WALK
    )
    root = _plant(tmp_path, "walker_marked", head)
    modules = _collected_modules(root, root / "apps")
    forward, reverse, marked, walkers = _census(root, modules)
    assert (forward, reverse, marked, walkers) == ([], [], 1, 1)


def test_an_empty_world_is_green_and_says_how_empty(tmp_path: pathlib.Path, capsys: Any) -> None:
    """The instrument-absent case: nothing marked, nothing walking, and it says so."""
    root = _plant(tmp_path, "nothing", '"""A plant that reaches nothing."""\n')
    modules = _collected_modules(root, root / "apps")
    forward, reverse, marked, walkers = _census(root, modules)
    _announce(capsys, f"census markers: {marked} marked, {walkers} walkers")
    assert (forward, reverse, marked, walkers) == ([], [], 0, 0)


def test_a_marker_with_no_reason_is_could_not_look(tmp_path: pathlib.Path) -> None:
    """The grammar's own refusal, driven where it is cheap to drive.

    A bare marker is not an absent marker: read as one, a census would drop out
    of the always-on set at the exact moment somebody half-wrote its
    declaration. `apps/conftest.py` raises `pytest.UsageError`, which is pytest's
    exit 4 and the gate's exit 2.
    """
    module = tmp_path / "test_bare_marker.py"
    module.write_text(f"{DJB_CENSUS_MARKER}\n{_PLANT_TEST}", encoding="utf-8")
    with pytest.raises(pytest.UsageError, match="gives NO REASON"):
        _module_census_reason(str(module))


# --- the POPULATION half: which censuses a change is allowed to skip ----------
#
# A marker makes a module always-on at every scope, which is the right answer
# for a census and the wrong price for every loop that could not possibly have
# moved what the census walks. The population is the module's own answer to
# "which files am I about" — declared in the same line, checked here in both
# the directions the reason already is: a population that names nothing on the
# tree is could-not-look, and a population that names something is honoured
# only for the files it names.
#
# THE DECISION IS DRIVEN WHERE IT IS MADE. `apps/conftest.py` owns the verdict
# (`_census_verdict`) and the banner (`_census_banner`); the plants below hand
# those functions a world they built, exactly as the halves above hand `_census`
# one. A nested `pytest.main` cannot be the driver here: the planted world under
# `tmp_path` is outside `apps/`, so the nested run loads none of the plugin
# whose flags the assertion is about.

#: The three states one population has to be able to be in, spelled once.
_PLANT_POPULATION = "apps/alpha/**"


def _planted_census(
    tmp_path: pathlib.Path, name: str, declaration: str
) -> tuple[str, pathlib.Path]:
    """A planted marked module: its repo-relative module path and its real path."""
    root = _plant(tmp_path, name, f"{DJB_CENSUS_MARKER} {declaration}\n" + _PLANT_WALK)
    module = f"apps/planted/tests/test_{name}.py"
    return module, root / module


def test_a_population_narrows_only_the_censuses_it_names(tmp_path: pathlib.Path) -> None:
    """b2.1. Three states, forced in one test, over one planted declaration.

    A change the population does not name deselects it; a change it does name
    keeps it; NO changed-file list at all keeps it, because nothing narrows by
    default — the same rule `--djb-scope-narrow` states for the scope.
    """
    module, path = _planted_census(
        tmp_path, "narrowed", f"{DJB_CENSUS_POPULATION}{_PLANT_POPULATION} walks apps/alpha only"
    )
    assert _module_census_reason(str(path)) == "walks apps/alpha only"
    globs = _module_census_population(str(path))
    assert globs == (_PLANT_POPULATION,)

    outside = _census_verdict(module, globs, frozenset({"apps/beta/x.py"}))
    assert outside == (
        f"{module}: population {_PLANT_POPULATION} does not contain the change — deselected"
    ), outside
    assert _census_verdict(module, globs, frozenset({"apps/alpha/y.py"})) is None
    assert _census_verdict(module, globs, frozenset()) is None


def test_a_census_with_no_population_runs_always(tmp_path: pathlib.Path) -> None:
    """b2.2. No population is not an empty population — it is the old behaviour,
    and the banner says which censuses are on those terms."""
    module, path = _planted_census(tmp_path, "unbounded", "walks the whole tree, and says so")
    assert _module_census_population(str(path)) == ()
    assert _census_verdict(module, (), frozenset({"apps/beta/x.py"})) is None

    lines = _census_banner({module: ()}, frozenset({"apps/beta/x.py"}))
    assert any(module in line and "(no population — always)" in line for line in lines), lines
    assert any("1 declared, 0 with a population, 1 selected" in line for line in lines), lines


def test_the_banner_counts_the_declared_the_bounded_and_the_selected(
    tmp_path: pathlib.Path,
) -> None:
    """The banner's arithmetic, over a world holding one of each state."""
    kept, _ = _planted_census(
        tmp_path, "kept", f"{DJB_CENSUS_POPULATION}apps/alpha/** walks apps/alpha only"
    )
    lines = _census_banner(
        {kept: ("apps/alpha/**",), "apps/x/tests/test_always.py": ()},
        frozenset({"apps/beta/x.py"}),
    )
    assert any("2 declared, 1 with a population, 1 selected" in line for line in lines), lines
    assert any("does not contain the change — deselected" in line for line in lines), lines


def test_an_empty_population_is_could_not_look(tmp_path: pathlib.Path) -> None:
    """b2.3. A population that names nothing ON THE TREE is a broken declaration.

    An underived population is not an empty one: read as "no files", a glob with
    a typo in it would deselect its census from every loop forever and the only
    symptom would be a green one.
    """
    module, path = _planted_census(
        tmp_path, "nowhere", f"{DJB_CENSUS_POPULATION}apps/nowhere/** walks a subtree that is not"
    )
    with pytest.raises(pytest.UsageError) as caught:
        _census_population_or_refuse(str(path), path.parents[3])
    assert "apps/nowhere/**" in str(caught.value)
    assert module in str(caught.value).replace(str(path.parents[3]) + "/", "")


def test_a_population_with_no_globs_is_could_not_look(tmp_path: pathlib.Path) -> None:
    """The grammar's own half of b2.3: `population=` and then nothing."""
    module = tmp_path / "test_empty_population.py"
    module.write_text(
        f"{DJB_CENSUS_MARKER} {DJB_CENSUS_POPULATION} walks something{_PLANT_TEST}",
        encoding="utf-8",
    )
    with pytest.raises(pytest.UsageError, match="EMPTY POPULATION"):
        _module_census_population(str(module))


def test_every_declared_population_on_this_tree_resolves(tree_modules: list[str]) -> None:
    """The real tree's declarations, run through the same refusal.

    The forward half above asks whether a marked module walks anything at all;
    this asks whether the globs it named are globs this tree still has. A rung
    that moves a subtree and leaves a population behind reds here.
    """
    checked = 0
    bounded = 0
    for module in tree_modules:
        path = REPO_ROOT / module
        if not _module_census_reason(str(path)):
            continue
        checked += 1
        if _census_population_or_refuse(str(path), REPO_ROOT):
            bounded += 1
    assert checked, "no declared census on this tree — the population check saw nothing"
    assert bounded, "no declared census names a population — the grammar reached nothing"


def test_impact_select_keeps_the_named_and_the_always_on() -> None:
    """b2.5. The seam b1 wires: an explicit selection plus the always-on set.

    A named nodeid nothing collected is a STALE MAP — a test renamed,
    parametrized or deleted since the map was measured. It is NAMED on the
    banner line and its module runs whole in its place (the renamed test lives
    in the file its old id named); it is never a `UsageError`, which killed
    every xdist worker and never reached the log.
    """
    nodeids = [f"apps/alpha/tests/test_a.py::test_{index}" for index in range(5)]
    nodeids.append("apps/test_root_census.py::test_the_whole_tree")
    named = frozenset(nodeids[:2])
    always_on = frozenset({nodeids[5]})

    keep, banner = _impact_selection(nodeids, named, always_on)
    assert keep == named | always_on
    assert len(keep) == 3
    assert banner == "impact-select: 2 named, 1 always-on", banner

    renamed = "apps/alpha/tests/test_a.py::test_renamed_since"
    gone = "apps/ghost/tests/test_gone.py::test_x"
    keep, banner = _impact_selection(nodeids, frozenset({nodeids[0], renamed, gone}), always_on)
    assert keep == frozenset(nodeids), keep
    stale = f"impact map: 2 ids no longer collected — {renamed}, {gone} · "
    assert banner.startswith(stale), banner
    assert "1 module(s) run whole in their place: apps/alpha/tests/test_a.py" in banner, banner


# --- the door registry, the banner's ways in, and the drawer's reach kinds -----


def test_the_door_schema_parity_module_derives_door_registry_reach() -> None:
    """The module that compares the two published documents reads the door
    registry by its own source — no marker, no seed line, no list naming it."""
    path = REPO_ROOT / "apps/core/tests/test_door_schema_parity.py"
    assert "door_registry" in _module_reach(str(path))
    assert _module_census_reason(str(path)) == ""


def test_the_banner_names_every_module_with_its_way_in() -> None:
    """`always-on: <n> modules`, then one line per module, each with its way in."""
    assert _way_in("apps/test_x.py::test_y", frozenset()) == "structural"
    assert (
        _way_in("apps/core/tests/test_x.py::test_y", frozenset({"door_registry", "app_registry"}))
        == "derived: app_registry,door_registry"
    )
    assert _way_in("apps/core/tests/test_x.py::test_y", frozenset()) == "declared"
    ways = {
        "apps/test_x.py": "structural",
        "apps/core/tests/test_door_schema_parity.py": "derived: door_registry",
        "apps/core/tests/test_settings.py": "declared",
        "apps/core/tests/test_vocabulary.py": "seeded",
    }
    lines = _always_on_banner(ways, 5, 2)
    assert lines[0] == (
        "  always-on: 4 modules ran — 5 derived before the tier, 2 dropped whole by the "
        "fast tier (organ-reaching, outside the own apps), 1 seeded by the change"
    ), lines
    assert _always_on_banner({"apps/test_x.py": "structural"}, 1, 0)[0] == (
        "  always-on: 1 modules ran — 1 derived before the tier"
    )
    assert len(lines) == 5, lines
    for module, way in ways.items():
        assert f"    {module} {way}" in lines, lines


def test_a_drawer_reach_kind_joins_the_derivation() -> None:
    """A product's own reach kind, read by its one reader."""
    drawer = types.SimpleNamespace(**{DJB_REACH_KINDS_KEY: {"acme_registry": ("list_widgets(",)}})
    kinds = _drawer_reach_kinds(drawer)
    assert kinds == {"acme_registry": ("list_widgets(",)}
    assert _drawer_unknown_keys(drawer) == []
    assert _drawer_reach_kinds(None) == {}
    assert _drawer_reach_kinds(types.SimpleNamespace()) == {}


def test_a_drawer_key_no_reader_reads_is_refused_by_name() -> None:
    """A typo'd drawer key declares nothing, so it is named rather than ignored."""
    drawer = types.SimpleNamespace(DJB_REACH_KIND={"acme_registry": ("list_widgets(",)})
    assert _drawer_unknown_keys(drawer) == ["DJB_REACH_KIND"]


@pytest.mark.parametrize(
    "declared",
    [
        {"door_registry": ("x(",)},
        {"acme_registry": ()},
        {"acme_registry": ("",)},
        {"acme_registry": "list_widgets("},
        ["acme_registry"],
    ],
)
def test_a_drawer_reach_kind_that_edits_or_declares_nothing_is_refused(declared: Any) -> None:
    """A drawer adds a kind; it never replaces the template's, and never declares an empty one."""
    drawer = types.SimpleNamespace(**{DJB_REACH_KINDS_KEY: declared})
    with pytest.raises(pytest.UsageError, match=DJB_REACH_KINDS_KEY):
        _drawer_reach_kinds(drawer)


def test_the_template_kinds_carry_the_door_registry() -> None:
    """The kind the derivation was missing is declared in the sentinel block."""
    assert DJB_REACH_TOKENS["door_registry"]
