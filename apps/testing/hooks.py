"""The worker ceiling: a typed `-n` cannot exceed this box's slot share."""

from __future__ import annotations

import os
import pathlib
import sys
from collections.abc import Sequence
from typing import Any

import pytest

# --- the worker ceiling: a typed `-n` cannot exceed this box's slot share -----
#
# THE DEFECT THIS CLOSES. The gate splits this machine's cores into pytest
# SLOTS and every slot holder runs its share (`scripts/gate_lease.sh`,
# `gate_slot_workers`; `scripts/check.sh` runs `-n $GATE_SLOT_WORKERS`). A
# direct `uv run pytest … -n 10` holds no slot and read no ceiling, so it ran
# ten workers beside two gates running five each and minted ten
# `test_<db>_gwN` databases on the way — the shared-box contention that put a
# sibling platform's Postgres into recovery. `scripts/test.sh` now refuses
# `-n auto`; this is the belt for every other way a number gets typed,
# including a bare `uv run pytest`, because the runner is not the only door.
#
# ONE NUMBER, AND WHERE IT COMES FROM. An inherited `DJB_GATE_SLOT_WORKERS` or
# `DJB_PYTEST_MAX_WORKERS` wins outright — that is the caller handing down the
# share it already took, and this must never second-guess it. Only when nothing
# was handed down is the share DERIVED, and then it is derived exactly as
# `scripts/gate_lease.sh` derives it (cores ÷ slots, slots = cores ÷ 5 or
# `DJB_GATE_SLOTS`). That derivation is a SECOND copy of a shell constant and it
# is named as one: `quality/tests/test_scope.py`'s
# `case_the_python_clamp_and_the_shell_share_are_the_same_number` runs both and
# asserts they agree, so the copy cannot drift in silence.
#
# AND EVERY GATE LEG NOW HANDS IT DOWN, which is what closes the one case the
# derivation above cannot get right. A `--bank` run holds EVERY pytest slot, so
# its share is the whole box's cores rather than one slot's — a number this file
# has no way to reach, because "how many slots is this holder holding" is the
# semaphore's state and not the box's. It derived one slot's share anyway,
# clamped the bank's `-n 10` to 5, and left the collector census expecting ten
# collectors from a five-worker run: `5 of 10 collectors reported`, exit 2,
# nothing banked (bank-2349.log, 2026-09-16). `gate_slot_worker_count`
# (scripts/gate_lease.sh) exports the resolved share under the first name above
# and `gate_slot_release` unsets it, so under any gate leg the branch below takes
# the hand-down and the derivation is what a BARE `uv run pytest` gets — which is
# the door the ceiling was built for.
#
# THE ESCAPE IS TYPED: `DJB_PYTEST_UNCAPPED=1`. A ceiling with no way past it
# gets worked around by leaving the runner, which is the one place nobody can
# see the number at all.
_DJB_GATE_SLOT_CORES_PER_SLOT = 5  # scripts/gate_lease.sh: GATE_SLOT_CORES_PER_SLOT


def _djb_positive_int(raw: str) -> int | None:
    text = raw.strip()
    return int(text) if text.isdigit() and int(text) >= 1 else None


def _djb_slot_share() -> int | None:
    """This run's worker ceiling, or None when nobody can say what it is."""
    for name in ("DJB_GATE_SLOT_WORKERS", "DJB_PYTEST_MAX_WORKERS"):
        handed_down = _djb_positive_int(os.environ.get(name, ""))
        if handed_down is not None:
            return handed_down
    cores = os.cpu_count() or 0
    if cores < 1:
        # A ceiling nobody can derive is no ceiling: refusing here would turn an
        # unreadable core count into a failed test run, and the gate's own
        # derivation falls back the same way rather than guessing small.
        return None
    declared = os.environ.get("DJB_GATE_SLOTS", "").strip()
    if declared:
        slots = _djb_positive_int(declared)
        if slots is None:
            return None
    else:
        slots = max(cores // _DJB_GATE_SLOT_CORES_PER_SLOT, 1)
    return max(cores // slots, 1)


def pytest_configure(config: pytest.Config) -> None:
    """Lower a typed `-n` to the slot share, and say so on one line."""
    typed = getattr(config.option, "numprocesses", None)
    if os.environ.get("DJB_PYTEST_UNCAPPED", "").strip():
        # THE ESCAPE PRINTS, AND THAT IS THE HALF THAT MAKES IT AN ESCAPE RATHER
        # THAN A HOLE. A ceiling with a silent override is a ceiling nobody can
        # tell they are outside: the transcript of an uncapped run and the
        # transcript of a capped one differed nowhere, so `-n 10` on a five-share
        # box read exactly like `-n 5` to every later reader of the log.
        #
        # It says the number that was TYPED and the share it is running past, so
        # the line answers both questions a reader has — how many workers this
        # box is about to carry, and how many it would have carried. An
        # underivable share says so rather than printing a guess.
        if isinstance(typed, int) and typed >= 1:
            share = _djb_slot_share()
            basis = (
                f"the slot share on this box is {share}"
                if share is not None
                else "the slot share on this box could not be derived"
            )
            sys.stderr.write(f"uncapped: -n {typed} (DJB_PYTEST_UNCAPPED=1 — {basis})\n")
        return
    # `auto`/`logical` are still strings here on the bare-pytest path (xdist
    # resolves them in its own `pytest_cmdline_main`, which has already run);
    # scripts/test.sh refuses those outright, and a run that reaches here with
    # one has no number to compare.
    if not isinstance(typed, int) or typed < 1:
        return
    share = _djb_slot_share()
    if share is None or typed <= share:
        return
    config.option.numprocesses = share
    # xdist builds one `tx` entry per worker in `pytest_cmdline_main`, BEFORE
    # this hook, and `NodeManager` reads that list rather than the number — so
    # lowering the number alone would print a clamp and still start every
    # worker. Measured, not assumed: the drive asserts the worker count.
    spec = getattr(config.option, "tx", None)
    if isinstance(spec, list) and len(spec) > share:
        config.option.tx = spec[:share]
    sys.stderr.write(
        f"clamped -n {typed} → {share} (DJB_PYTEST_UNCAPPED=1 to override)\n"
        f"  this box's cores are shared between the gate's pytest slots; "
        f"{share} is one slot's share (scripts/gate_lease.sh, gate_slot_workers).\n"
    )


def pytest_report_header(config: pytest.Config) -> list[str]:
    """The tier CHOICE, printed before collection — which is the only place it
    survives `-n auto`.

    MEASURED, not assumed: under xdist the WORKERS collect and the controller
    only compares their lists, so `pytest_collection_modifyitems` (and the
    counts it knows) runs in the workers and its report line never reaches the
    terminal. The session header does — the controller prints it — so the
    declaration lives here and the counts live below, where a serial run and
    the census drive can both see them. `--loop` prints its own basis, own apps
    and rule beside this, at the leg (`scripts/check.sh`).
    """
    if str(config.getoption("--djb-tier")) != "fast":
        return list(_DJB_ABSENT_REPORT)
    own = [str(label) for label in config.getoption("--djb-own-app")]
    if own:
        where = "everywhere except " + ", ".join(f"apps/{label}" for label in sorted(own))
        where += ", which are in scope and run IN FULL"
    else:
        where = "everywhere — no app is in scope under apps/<x>/, so there is no own app"
    scope_line: list[str] = []
    if bool(config.getoption("--djb-scope-narrow")):
        scoped = sorted(set(str(label) for label in config.getoption("--djb-scope")) | set(own))
        scope_line = [
            "djb scope: NARROWED — every app outside "
            + (", ".join(f"apps/{label}" for label in scoped) or "(an empty scope)")
            + " is DESELECTED except the derived always-on cross-app set. The scope "
            "is the active rung's touched apps plus the reverse-transitive depends_on "
            "closure (quality/djb/scope.py); a regression in a deselected app "
            "surfaces at the wave bank, not at the active rung."
        ]
    return [
        *_DJB_ABSENT_REPORT,
        "djb tier: FAST — organ-reaching tests (real MinIO, a real Temporal server, "
        f"real Meili) are DESELECTED {where}. The full gate at push runs every one "
        "of them, twice.",
        *scope_line,
    ]


#: The environment variable naming the file a collection refusal is also written to.
DJB_REFUSAL_FILE_ENV = "DJB_LOOP_REFUSAL_FILE"
#: The `workeroutput` key a worker hands its collection refusal to the controller under.
DJB_WORKER_REFUSAL_KEY = "djb_collection_refusal"
_DJB_WORKER_REFUSALS: list[str] = []


def _record_refusal(sentences: Sequence[str]) -> None:
    """Write the refusal's sentences to the file `DJB_LOOP_REFUSAL_FILE` names, if any."""
    target = os.environ.get(DJB_REFUSAL_FILE_ENV, "")
    if target:
        pathlib.Path(target).write_text("\n".join(sentences) + "\n", encoding="utf-8")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Refuse a collection by its sentence; a worker hands it on, since its raise is a crashitem."""
    try:
        _select_items(config, items)
    except pytest.UsageError as refusal:
        if not hasattr(config, "workerinput"):
            _record_refusal([str(arg) for arg in refusal.args])
            raise
        handed: dict[str, Any] = getattr(config, "workeroutput", {})
        handed[DJB_WORKER_REFUSAL_KEY] = [str(arg) for arg in refusal.args]
        config.hook.pytest_deselected(items=list(items))
        items[:] = []


def pytest_testnodedown(node: Any, error: Any) -> None:
    """The controller's seam: keep the collection refusal a worker handed on."""
    _DJB_WORKER_REFUSALS.extend(getattr(node, "workeroutput", {}).get(DJB_WORKER_REFUSAL_KEY, ()))


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """The controller raises the workers' refusal once, as a serial run raises its own."""
    if hasattr(session.config, "workerinput") or not _DJB_WORKER_REFUSALS:
        return
    sentences = list(dict.fromkeys(_DJB_WORKER_REFUSALS))
    _DJB_WORKER_REFUSALS.clear()
    _record_refusal(sentences)
    raise pytest.UsageError(*sentences)


def _select_items(config: pytest.Config, items: list[pytest.Item]) -> None:
    """The tier, the scope and the impact selection, or a `pytest.UsageError`."""
    # The absent-app world first, and unconditionally: what a smaller deployment
    # cannot run is not a tier choice, and the tier's early return below is
    # allowed to skip work only because it changes nothing.
    _withhold_the_absent_world(items)
    # The template-only honour, as unconditionally and for the same reason: a
    # property of the TEMPLATE's own tree is not a tier choice either.
    _withhold_template_only(items)
    tier = str(config.getoption("--djb-tier"))
    manifest = str(config.getoption("--djb-tier-manifest"))
    narrow = bool(config.getoption("--djb-scope-narrow"))
    counts_dir = str(config.getoption("--djb-scope-counts"))
    # THE IMPACT SEAM. `--djb-impact-select` is a selection and narrows on its
    # own; `--djb-changed` is a MODIFIER and narrows nothing by itself — it can
    # only subtract from the declared censuses of a run that was already
    # narrowing, which is why it is absent from the early return below.
    impact_select = str(config.getoption("--djb-impact-select"))
    changed = frozenset(str(path).lstrip("./") for path in config.getoption("--djb-changed"))
    _DJB_TIER_REPORT.clear()
    if tier == "all" and not manifest and not narrow and not impact_select:
        # THE WHOLE-SUITE BRANCH, AND IT STILL PAYS NOTHING. No source read, no
        # closure walk, no deselection, no behaviour change — the one thing it
        # does now is SAY HOW MANY TESTS THIS COLLECTOR HELD, and only when a
        # caller asked for counts at all.
        #
        # WHY IT HAS TO. The counts file is the only evidence that a collector
        # reached the end of collecting, and the reconciliation in
        # `scripts/check.sh` is what turns a missing one into a refusal. It was
        # written under `--loop` alone, so the full gate's two passes wrote none
        # — and a worker that dies during collection with xdist's restart budget
        # exhausted leaves pytest able to exit **0** with `no tests ran`, which
        # the full gate reads as a clean tree and banks. Nothing is
        # deselected on this branch, so the file says `selected=<everything>`
        # and `deselected=0`: a population, not a scope.
        #
        # AND IT ASSERTS THE FLOORS WHEN IT HOLDS THE WHOLE TREE. A `--loop` whose
        # rung changed shared test infrastructure runs the WHOLE suite on this
        # branch — and adding an apps-root module IS that change — so a floor
        # read only under narrowing was never read by the one loop that grew its
        # population (measured: a seventh apps-root module, a whole-suite loop,
        # green). One cached source read per collected module per collector.
        if _collects_the_whole_tree(config):
            _assert_the_floors(*_reach_and_populations(items), whole=True)
        if counts_dir:
            _write_scope_counts(
                config,
                counts_dir,
                frozenset(),
                frozenset(),
                frozenset(),
                0,
                0,
                0,
                0,
                0,
                len(items),
                0,
            )
        return

    own_apps = frozenset(str(label) for label in config.getoption("--djb-own-app"))
    # The rung's OWN apps are always inside its scope — it edited them. Stated
    # as a union rather than assumed, so a caller that named an own app and
    # forgot the scope flag narrows nothing it should have kept.
    scope_apps = frozenset(str(label) for label in config.getoption("--djb-scope")) | own_apps
    # THE TESTS-ONLY SET, which is neither of the two above and must not be
    # folded into either: an app here is NOT own (its organ tests stay
    # push-side) and NOT in scope (nothing widened to it through the
    # declarations). It brings its own test tree, the modules the rung edited,
    # and the modules that import its test package — and nothing else.
    tests_only = frozenset(str(label) for label in config.getoption("--djb-tests-only"))
    changed_tests = frozenset(str(path) for path in config.getoption("--djb-changed-test"))
    classified = [(item, _item_organs(item)) for item in items]

    reached: dict[str, int] = {}
    for _item, organs in classified:
        for name in organs:
            reached[name] = reached.get(name, 0) + 1
    unmet = sorted(
        f"{kind} (floor {floor}, derived {reached.get(kind, 0)})"
        for kind, floor in DJB_ORGAN_FLOORS.items()
        if reached.get(kind, 0) < floor
    )
    if unmet:
        raise pytest.UsageError(
            "the --loop tier's organ derivation is not answering: "
            + "; ".join(unmet)
            + ". Nothing was deselected. A derivation that stopped seeing an organ "
            "kind reads exactly like a suite that no longer has one, so this refuses "
            "instead of running a fast tier nobody can trust. If you asked for "
            "--djb-tier=fast over a NARROW path, this is that refusal working: the "
            "floors are asserted over the whole collection, and `--loop` always "
            "collects the whole suite. Narrow a run with a path and leave the tier "
            "alone — it defaults to `all`."
        )

    # THE ALWAYS-ON DERIVATION AND ITS TWO LAYERS OF FLOORS, asserted BEFORE a
    # single item is deselected. Derived whenever narrowing is asked for, so the
    # refusal cannot be dodged by a scope that happens to be empty.
    always_on: set[str] = set()
    always_on_ways: dict[str, str] = {}
    declared_censuses: dict[str, tuple[str, ...]] = {}
    if narrow or impact_select:
        reached_kinds: dict[str, set[str]] = {}
        populations: dict[str, set[str]] = {}
        for item in items:
            path = str(getattr(item, "path", "") or "")
            reach = _module_reach(path) if path else frozenset()
            module = _module_of(item.nodeid)
            for kind in reach:
                reached_kinds.setdefault(kind, set()).add(module)
            for name in _population_members(path, item.nodeid):
                populations.setdefault(name, set()).add(module)
            if path and _app_label(item.nodeid) is not None and _module_census_reason(path):
                declared_censuses[module] = _census_population_or_refuse(path, DJB_REPO_ROOT)
            if _is_always_on(item, reach, changed):
                always_on.add(item.nodeid)
                always_on_ways.setdefault(module, _way_in(item.nodeid, reach))

        _assert_the_floors(reached_kinds, populations, _collects_the_whole_tree(config))
    elif _collects_the_whole_tree(config):
        _assert_the_floors(*_reach_and_populations(items), whole=True)

    if manifest and not hasattr(config, "workerinput"):
        lines = []
        for item, organs in classified:
            where = "slow" if organs else "fast"
            lines.append(f"{where}\t{','.join(sorted(organs)) or '-'}\t{item.nodeid}")
        pathlib.Path(manifest).write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")

    if tier != "fast" and not narrow and not impact_select:
        return

    # THE SELECTION, READ BEFORE ANYTHING IS DESELECTED, for the reason the
    # floors above are asserted there: a selection file this could not read must
    # never reach the loop below as an empty set.
    selected: frozenset[str] = frozenset()
    impact_line = ""
    if impact_select:
        selected, impact_line = _impact_selection(
            [item.nodeid for item in items],
            _read_impact_select(impact_select),
            frozenset(always_on),
        )

    keep: list[pytest.Item] = []
    dropped: list[pytest.Item] = []
    n_in_scope = 0
    n_always_on = 0
    n_tests_only = 0
    importer_modules: set[str] = set()
    always_on_modules = {_module_of(nodeid) for nodeid in always_on}
    for item, organs in classified:
        label = _app_label(item.nodeid)
        module = _module_of(item.nodeid)
        in_scope = label in scope_apps
        is_own = label in own_apps
        # THE THREE WAYS A TESTS-ONLY APP REACHES AN ITEM, each its own claim.
        in_tests_tree = label in tests_only and _is_app_tests_module(module)
        is_changed_test = module in changed_tests
        imports_tests = (
            _module_test_imports(str(getattr(item, "path", "") or ""), tests_only)
            if tests_only
            else frozenset()
        )
        if imports_tests and not in_tests_tree:
            importer_modules.add(module)
        tests_only_keeps_it = in_tests_tree or is_changed_test or bool(imports_tests)
        if impact_select and item.nodeid not in selected:
            # THE MAP ANSWERED. A selection is the whole question — the scope
            # rules below would only ever widen it back, which is the one thing
            # a caller that handed over a list did not ask for.
            dropped.append(item)
            continue
        if narrow and not in_scope and item.nodeid not in always_on and not tests_only_keeps_it:
            # Outside the scope and not a cross-app tripwire: the active rung's change
            # cannot reach it, by the declarations the closure walked.
            dropped.append(item)
            continue
        if tier == "fast" and organs and not is_own and not is_changed_test:
            # Organ-reaching outside the rung's OWN apps — the organ tier's rule,
            # unchanged, and still push-time. It applies to an in-scope app the
            # closure pulled in and to an always-on member alike: neither being
            # reachable nor being unconditional earns a test a real MinIO in a
            # per-rung gate. THE ONE EXEMPTION is a module the rung EDITED: a
            # test somebody just changed is the one organ test this gate has a
            # reason to run, and it is named by path, not by app.
            dropped.append(item)
            continue
        keep.append(item)
        if in_scope:
            n_in_scope += 1
        elif tests_only_keeps_it and item.nodeid not in always_on:
            n_tests_only += 1
        else:
            n_always_on += 1
    if dropped:
        config.hook.pytest_deselected(items=dropped)
        items[:] = keep

    # THE FOURTH WAY IN, AND IT IS NOT UNCONDITIONAL: a census the scope SEEDED
    # because the change touched a declaration module it quantifies over
    # (`CENSUS_SEEDED_BY`, derived by `quality/djb/scope.py`). It arrives as a
    # changed-test path, so it is named here only when it is kept and carries
    # the declaration — an edited module is not a census.
    #
    # AND THE LIST IS WHAT RAN: a member the organ tier took out whole (an
    # organ-reaching census outside the rung's own apps, under `--djb-tier=fast`)
    # is not printed as if it had run.
    kept_modules = {_module_of(item.nodeid) for item in keep}
    dropped_whole = sum(1 for module in always_on_ways if module not in kept_modules)
    always_on_ways = {m: way for m, way in always_on_ways.items() if m in kept_modules}
    for item in keep:
        module = _module_of(item.nodeid)
        if module in always_on_ways or module not in changed_tests:
            continue
        path = str(getattr(item, "path", "") or "")
        if path and _module_seeds_a_census(path):
            always_on_ways[module] = "seeded"

    if counts_dir:
        _write_scope_counts(
            config,
            counts_dir,
            own_apps,
            scope_apps,
            tests_only,
            n_in_scope,
            n_always_on,
            n_tests_only,
            len(always_on_modules),
            len(importer_modules),
            len(keep),
            len(dropped),
            always_on_ways,
            dropped_whole,
            impact_line,
        )

    census = ", ".join(f"{kind}={reached[kind]}" for kind in sorted(reached)) or "none"
    if narrow or impact_select:
        # THE ALWAYS-ON SET, ENUMERATED. A set nobody can enumerate is one
        # nobody audits — the argument `scripts/check.sh`'s declared-census
        # listing is printed for, and this is its narrowing half.
        _DJB_TIER_REPORT.extend(
            _always_on_banner(always_on_ways, len(always_on_modules), dropped_whole)
        )
        _DJB_TIER_REPORT.extend(_census_banner(declared_censuses, changed))
        _DJB_TIER_REPORT.append(
            f"  {impact_line}" if impact_line else "  impact: not consulted (seam only)"
        )
    if narrow:
        _DJB_TIER_REPORT.append(
            f"djb scope: {len(dropped)} test(s) deselected, {len(keep)} running "
            f"({n_in_scope} in scope, {n_always_on} always-on) — derived organ "
            f"reach: {census}."
        )
    elif impact_select:
        # NOT "FAST" AND NOT "SCOPE": a selection is a third basis, and printing
        # one of the other two here would tell a reader the run narrowed by a
        # rule it did not use.
        _DJB_TIER_REPORT.append(
            f"djb impact: {len(dropped)} test(s) deselected, {len(keep)} running — "
            f"the selection came from {impact_select}, plus the always-on set. "
            f"Derived organ reach: {census}."
        )
    else:
        _DJB_TIER_REPORT.append(
            f"djb tier: FAST — {len(dropped)} organ-reaching test(s) deselected, "
            f"{len(keep)} running (derived reach: {census})."
        )
    if own_apps:
        _DJB_TIER_REPORT.append(
            "  own app(s), run IN FULL including organ tests: " + ", ".join(sorted(own_apps))
        )
    else:
        _DJB_TIER_REPORT.append(
            "  no app is in scope under apps/, so there is NO own app: the rule for "
            "that case is the always-on set alone, and it is declared here rather "
            "than chosen silently."
        )
    _DJB_TIER_REPORT.append(
        "  the deselected tests are NOT skipped forever — the FULL gate at push runs "
        "every one of them, twice."
    )


def _write_scope_counts(
    config: pytest.Config,
    counts_dir: str,
    own_apps: frozenset[str],
    scope_apps: frozenset[str],
    tests_only: frozenset[str],
    in_scope: int,
    always_on: int,
    tests_only_tests: int,
    always_on_modules: int,
    importer_modules: int,
    selected: int,
    deselected: int,
    always_on_ways: dict[str, str] | None = None,
    always_on_dropped_whole: int = 0,
    impact_line: str = "",
) -> None:
    """One counts file per COLLECTOR, named for the collector.

    RECONCILE, NEVER SUM. Under xdist every worker performs its own full
    collection and then runs its share, so all N workers derive the SAME three
    counts and a sum multiplies them by N. The caller compares the files and
    refuses on disagreement — a disagreement means two collectors saw different
    suites, and a verdict banked under a scope one of them disowned is a verdict
    about nothing.

    AND EVERY FILE CARRIES THE POPULATION IT BELONGS TO. `workers=` is the
    worker count pytest actually CREATED for this run — the number xdist prints
    as `created: N/N workers` — and it is here because the census in
    `scripts/check.sh` (`loop_counts_refuse_if_short`) has to answer "how many
    collectors should have reported" and the only honest source for that is the
    run itself. It used to answer with the `-n` the leg ASKED for, so a leg whose
    `-n` was lowered inside pytest read its own survivors as casualties:
    `5 of 10 collectors reported — a collector died`, exit 2, on a suite that had
    just passed 3653 tests. Identical in every worker, so the file-vs-file
    comparison above is unchanged by it.

    AND IT IS `workerinput["workercount"]`, NOT `numprocesses`. Measured, not
    assumed: a WORKER's own config carries no `-n` at all — `numprocesses` there
    is 0, so a file written from the number the controller was given records
    `workers=0` and the census silently learns nothing (it did, on the first
    green run of this drive). `workercount` is what the controller hands each
    worker when it creates it, so it is the created population by construction.
    The controller/serial path has no `workerinput` and falls back to its own
    `numprocesses`, which is that path's true population.
    """
    workerinput = getattr(config, "workerinput", {})
    worker = workerinput.get("workerid", "controller")
    created = int(workerinput.get("workercount", 0) or 0) or int(
        getattr(config.option, "numprocesses", 0) or 0
    )
    target = pathlib.Path(counts_dir)
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / str(worker)).write_text(
            f"workers={created}\n"
            f"in_scope={in_scope}\n"
            f"always_on={always_on}\n"
            f"tests_only_tests={tests_only_tests}\n"
            f"always_on_modules={always_on_modules}\n"
            f"importers={importer_modules}\n"
            f"selected={selected}\n"
            f"deselected={deselected}\n"
            f"own={','.join(sorted(own_apps)) or '-'}\n"
            f"scope={','.join(sorted(scope_apps)) or '-'}\n"
            f"tests_only={','.join(sorted(tests_only)) or '-'}\n"
            f"always_on_dropped_whole={always_on_dropped_whole}\n"
            # THE MAP'S OWN LINE, so a stale entry reaches the log under `-n`
            # too: the controller collects nothing and prints this file.
            + (f"{DJB_IMPACT_FIELD}={impact_line}\n" if impact_line else "")
            # THE ALWAYS-ON SET BY MODULE, one line each, so the leg that runs
            # under `-n` — whose controller collects nothing — prints the same
            # enumeration the serial report does. Sorted, so every collector's
            # file stays byte-identical to its siblings'.
            + "".join(
                f"{DJB_ALWAYS_ON_FIELD}={module} {way}\n"
                for module, way in sorted((always_on_ways or {}).items())
            ),
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - the caller turns absence into 2
        raise pytest.UsageError(
            f"the --loop scope could not write its counts file into {counts_dir} "
            f"({exc}). The banner reconciles those files; a missing one is a "
            "collector whose scope nobody can read."
        ) from exc


def pytest_report_collectionfinish(config: pytest.Config) -> list[str]:
    return list(_DJB_TIER_REPORT)


# --- the PRE-RUN banner, and why it can exist at all --------------------------
#
# The counts are known only once something has COLLECTED, and under xdist the
# WORKERS collect — which is why this banner used to print after the run, beside
# the verdict, where a reader asking "did it even run my test?" had already
# waited for the whole leg to find out.
#
# THE ORDERING IS A FACT, NOT A BET. A worker writes its counts file in
# `pytest_collection_modifyitems` (above); pytest runs that BEFORE
# `pytest_collection_finish`, which is what sends the worker's `collectionfinish`
# event (xdist/remote.py:236,257). The controller answers that event in
# `worker_collectionfinish`, whose FIRST act is to call
# `pytest_xdist_node_collection_finished` (xdist/dsession.py:287) — so the file
# this reads is complete — and which schedules no test at all until EVERY node
# has reported (`sched.collection_is_completed`, :297-305). Waiting for the last
# node therefore still lands before the first test runs, and it is what lets the
# banner say `reconciled across N collectors` and mean it.
#
# RECONCILE, NEVER SUM, here as in the after-run banner: every collector
# performs its own full collection, so the files must be identical. A
# disagreement is `scripts/check.sh`'s refusal (exit 2) and NOT a second one
# here — a banner that refused would refuse before the leg it is describing.
_DJB_PRERUN_NODES: set[str] = set()
_DJB_PRERUN_PRINTED: list[bool] = [False]


def _djb_prerun_banner(config: pytest.Config, counts_dir: str, collectors: int) -> None:
    """Print one line per selection decision, before the first test runs."""
    _DJB_PRERUN_PRINTED[0] = True
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:  # pragma: no cover - -p no:terminal
        return
    try:
        files = sorted(path for path in pathlib.Path(counts_dir).iterdir() if path.is_file())
        texts = {path.read_text(encoding="utf-8") for path in files}
    except OSError:  # pragma: no cover - the after-run reconciliation is the refusal
        return
    if not texts:
        return
    if len(texts) > 1:
        reporter.write_line(
            "scope   THE COLLECTORS DISAGREE — the counts are not printed here; "
            "the after-run reconciliation in scripts/check.sh is the refusal."
        )
        return
    fields = dict(line.split("=", 1) for line in next(iter(texts)).splitlines() if "=" in line)
    if fields.get(DJB_IMPACT_FIELD):
        # THE MAP'S LINE FIRST, and on every shape of run below: a stale map
        # entry is a fact about the selection whatever the tier said.
        reporter.write_line(f"scope   {fields[DJB_IMPACT_FIELD]}")
    if str(config.getoption("--djb-tier")) == "all" and not bool(
        config.getoption("--djb-scope-narrow")
    ):
        # THE WHOLE-SUITE LINE. Under the full gate — and under a `--pr` whose
        # scope narrowed nothing — there is no scope to describe: every
        # collector collected the tree. The one thing in question is the one
        # this says, before the first test runs: how many collectors reported.
        # The after-run reconciliation in `scripts/check.sh` is the refusal;
        # this is its pre-run half, and the counts-dir plumbing is shared.
        reporter.write_line(f"collectors: {collectors} of {collectors} reported (the whole suite)")
        return
    lines: list[str] = []
    labels = fields.get("tests_only", "-")
    if labels and labels != "-":
        lines.append(
            f"scope   tests-only: {labels.replace(',', ', ')} — their test trees at the "
            "FAST tier, the edited module(s) whatever tier they are in, and every "
            "collected module naming one of those test packages; NO closure walked"
        )
        lines.append(
            f"scope   importers: {fields.get('importers', '?')} module(s) outside those "
            "test trees name one of those test packages (derived from the modules' own "
            "source, never a list)"
        )
    lines.append(
        f"scope   always-on: {fields.get('always_on', '?')} test(s) in "
        f"{fields.get('always_on_modules', '?')} module(s) — the cross-app tripwires, "
        "floors met"
    )
    listed = [
        line.split("=", 1)[1]
        for line in next(iter(texts)).splitlines()
        if line.startswith(f"{DJB_ALWAYS_ON_FIELD}=")
    ]
    ways = dict(entry.split(" ", 1) for entry in listed)
    lines.append(
        "scope   "
        + _always_on_headline(
            ways,
            int(fields.get("always_on_modules", "0") or 0),
            int(fields.get("always_on_dropped_whole", "0") or 0),
        )
    )
    lines += [f"scope     {entry}" for entry in listed]
    lines.append(
        f"scope   selected {fields.get('selected', '?')} · deselected "
        f"{fields.get('deselected', '?')}    (reconciled across {collectors} collectors)"
    )
    for line in lines:
        reporter.write_line(line)


def pytest_xdist_node_collection_finished(node: Any, ids: Any) -> None:
    """The controller's seam — the only place the counts exist before the run."""
    config = getattr(node, "config", None)
    if config is None or _DJB_PRERUN_PRINTED[0]:
        return
    counts_dir = str(config.getoption("--djb-scope-counts", "") or "")
    if not counts_dir:
        return
    gateway = getattr(node, "gateway", None)
    _DJB_PRERUN_NODES.add(str(getattr(gateway, "id", None) or len(_DJB_PRERUN_NODES)))
    expected = int(getattr(config.option, "numprocesses", 0) or 0)
    if expected and len(_DJB_PRERUN_NODES) < expected:
        return
    _djb_prerun_banner(config, counts_dir, max(len(_DJB_PRERUN_NODES), 1))


def pytest_collection_finish(session: pytest.Session) -> None:
    """The serial seam. Under xdist the controller collects nothing and the hook
    above is the one that fires; this is the `-p no:xdist` / `-n 0` path, and the
    one the drives' `--collect-only` invocations take."""
    config = session.config
    if hasattr(config, "workerinput") or _DJB_PRERUN_PRINTED[0]:
        return
    if int(getattr(config.option, "numprocesses", 0) or 0) > 0:
        return
    counts_dir = str(config.getoption("--djb-scope-counts", "") or "")
    if not counts_dir:
        return
    _djb_prerun_banner(config, counts_dir, 1)


from apps.testing.absent_world import _DJB_ABSENT_REPORT, _withhold_the_absent_world  # noqa: E402
from apps.testing.impact import (  # noqa: E402
    _collects_the_whole_tree,
    _impact_selection,
    _is_always_on,
    _is_app_tests_module,
    _module_test_imports,
    _population_members,
    _reach_and_populations,
    _read_impact_select,
)
from apps.testing.template_only import _withhold_template_only  # noqa: E402
from apps.testing.tier import (  # noqa: E402
    _DJB_TIER_REPORT,
    DJB_ALWAYS_ON_FIELD,
    DJB_IMPACT_FIELD,
    DJB_ORGAN_FLOORS,
    DJB_REPO_ROOT,
    _always_on_banner,
    _always_on_headline,
    _app_label,
    _assert_the_floors,
    _census_banner,
    _census_population_or_refuse,
    _item_organs,
    _module_census_reason,
    _module_of,
    _module_reach,
    _module_seeds_a_census,
    _way_in,
)
