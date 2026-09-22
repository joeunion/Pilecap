#!/usr/bin/env bash
# The `--loop` pytest tier's OWN-APP derivation, and the SCOPE it narrows to.
# Sourced by scripts/check.sh and by scripts/tests/test_loop_tier.sh and
# scripts/tests/test_loop_scope.sh.
# BASH ONLY, for the reason gate_ledger.sh states: sourced into an interactive
# zsh, `local path` ties to $PATH and every helper dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION, not an oversight: this file
# reports no verdict of its own. It hands a list of app labels and one sentence
# to whoever sourced it, and the caller owns the exit status. It is a library
# beside gate_ledger.sh, db.sh and secrets_scan.sh, not an instrument beside
# them.
#
# ---------------------------------------------------------------------------
# WHAT IT DECIDES. `--loop` runs the FAST TIER, narrowed to THE ACTIVE RUNG'S
# SCOPE, plus an ALWAYS-ON set of cross-app tripwires. The fast/slow split is
# derived inside pytest, from organ-fixture reach and nothing else
# (`apps/conftest.py`); this file answers the other half — which apps are the
# active rung's, and which apps its change can reach.
#
# THE TESTS-ONLY ROW, AND WHY IT IS NOT THE CLOSURE. A change under an app's own
# test tree and nowhere else cannot break another app's CODE. What it CAN break
# is a cross-app TEST import — a census helper, a shared fixture module — and
# those are real here (24 modules name `apps.comms.tests` today). So the row
# widens by the IMPORTERS, derived from the collected modules' own source in
# `apps/conftest.py`, and not by the declarations: the reverse closure of the
# app that holds the census helpers is every app in the tree, which is exactly
# the 92% a consumer measured and the reason this row exists. The trade is
# declared on every such run, in the note below and in build-contract.md.
#
# IT REUSES THE SECRET SCAN'S DERIVATION AND DOES NOT GROW A SECOND ONE.
# `secrets_scan_changed_files` already answers "what did the active rung
# change" — merge-base with the local `refs/heads/main`, plus everything
# staged and uncommitted, with its edge cases (an unborn HEAD, no local main,
# on main itself, a linked worktree's merge-base) argued and DRIVEN in
# `scripts/tests/test_secrets_scan.sh`. Two derivations of "the active rung's
# files" would be two things to keep in step, and the second one would drift
# first. So this is a MAPPING over that set, not a derivation beside it. **A
# second changed-files derivation in this file is a refusal in review**, not a
# preference — this sentence is the amendment, written where the next author
# will be standing.
#
# WHAT IT THEREFORE INHERITS, said plainly. That set filters DELETIONS out (a
# path handed to a scanner has to exist), so a rung whose ONLY change in an app
# is a deleted file derives no own app for it and that app's organ tests wait
# for the push. Inherited on purpose rather than patched here: forking the
# derivation to fix a corner is exactly what the amendment forbids, and a rung
# that only deletes a file in an app and changes nothing else in it is not the
# case this tier exists to serve.
#
# A RUNG WITH NO OWN APP IS THE NORMAL CASE HERE, NOT AN ERROR. Every rung of
# this cycle is a system-layer rung: `scripts/`, `quality/`, a skill. The rule
# for that case is the always-on set alone, and `--loop` PRINTS it every run — a
# silent scope is an unfalsifiable one.
#
# ---------------------------------------------------------------------------
# THE RULE SPLITS AT "NO OWN APP" (a follow-up ruling that overrules this
# file's first answer). "No own app" was read as one case and it
# is two, and the first version of this file took the cheap one for both:
#
#   * A rung that changed nothing under `apps/` at all — `scripts/`, `quality/`,
#     a skill, a document. Blast radius on the suite: none. The ALWAYS-ON SET,
#     alone (it used to be the whole fast tier; see THE SCOPE below).
#   * A rung that changed SHARED TEST INFRASTRUCTURE — a file that belongs to no
#     app but that every app's tests stand on. Blast radius: the whole suite, BY
#     CONSTRUCTION. That is the change class where loop-time discovery is worth
#     most, and it is rare enough that the full suite costs almost nothing
#     across a cycle. FULL SUITE in `--loop`.
#
# WHAT COUNTS AS SHARED TEST INFRASTRUCTURE, enumerated, because a rule nobody
# can read is a rule nobody can argue with. Four shapes, four arguments:
#
#   1. A `conftest.py` THAT NO APP OWNS — `apps/conftest.py`, a root
#      `conftest.py`, `perf/conftest.py`. These are fixtures every test below
#      them inherits; changing one changes what an arbitrary test does without
#      that test's file being touched. This is the ruling's own worked example.
#      **An app's own `apps/<x>/tests/conftest.py` is NOT in this class** and
#      must not be: it belongs to `<x>`, it is the commonest fixture edit in the
#      tree, and sweeping it in here would make the ordinary case pay for the
#      whole suite.
#   2. A TEST MODULE AT THE `apps/` ROOT — `apps/test_temporal_guard.py`,
#      `apps/test_gate_liveness.py`, `apps/test_absent_world.py`. Not a fixture,
#      and the sharpest argument of the four: they name the real-Temporal entry
#      point, so they derive into the SLOW tier, and under the old rule a rung
#      editing one of them had its own changed test DESELECTED and never ran it
#      in the rung at all.
#   3. `scripts/tests/**` — the gate's own drives and their preamble. Their
#      pytest blast radius is NIL and that is said out loud rather than papered
#      over: no shell drive can change what a Python test does. They are in for
#      the other half of the ruling's principle — a rung that changes the
#      machinery deciding whether things pass should not be graded by a narrowed
#      run of that machinery. The cost is one full `--loop` on a rung that
#      changes a drive, which is rarer than a conftest edit.
#   4. THE SELECTION MACHINERY ITSELF. The reflexive case: a rung that changes
#      how the tier decides must not be graded by the tier it changed. It was
#      this file alone while this file was the whole of the decision. It is now
#      the four files that between them choose what `--loop` runs and whether a
#      previous verdict may stand in for running it: `scripts/loop_tier.sh`
#      (the scope), `scripts/check.sh` (the leg and the banner),
#      `scripts/secrets_scan.sh` (the basis every scope is mapped over) and
#      `scripts/gate_ledger.sh` (the verdict that can replace a run entirely).
#      A rung that widened the reflexive shape and then graded itself with the
#      narrow one would be the first thing this shape exists to refuse.
#
# THE SHARED HALF OUTRANKS THE APP HALF. A rung that touched both has not made
# the shared change smaller by touching an app beside it.
#
# ---------------------------------------------------------------------------
# THE SCOPE, and why the tier grew one.
#
# The tier above answers "which apps run IN FULL". It never answered the
# cheaper question beside it: which apps need to run AT ALL. Before this, a
# rung touching `frontend/` alone still collected and ran every fast-tier test
# in every app — a whole backend suite to grade a change no backend test can
# see. So the tier now also derives a SCOPE, and everything outside it is
# deselected.
#
# THE SCOPE IS DERIVED, NEVER TYPED, and the derivation is two steps:
#
#   1. THE TOUCHED APPS. `apps/<x>/…` in the changed-file set puts `<x>` in.
#      Unchanged from the own-app mapping this file already did.
#   2. THE REVERSE-TRANSITIVE CLOSURE over `AppConfig.depends_on`, read from
#      the app declarations themselves through `config/settings/discovery.py`
#      — the same static read that builds `INSTALLED_APPS`. If `files` is
#      touched, every app that declares `files` joins, and every app that
#      declares one of THOSE, transitively.
#
# FORWARD EDGES ARE NOT WIDENED, and that is an argument, not an omission. If
# `exports` declares `depends_on = ("files", …)`, then `files` may not import
# `exports` — the DAG says so and house rule 7 enforces it. A dependency
# therefore cannot be broken by its dependent, and its tests cannot reach the
# dependent's code except through a census that quantifies over the whole
# registry — which is precisely the always-on set below, and always-on means
# it never needed the scope to carry it. Widening forward would double the
# scope of every rung to buy a population that is already unconditional.
#
# NO FLAG, ENV VAR OR FILE NAMES AN APP INTO OR OUT OF SCOPE. The whole value
# of a derived scope is that it cannot be argued with at the moment somebody
# wants a green run; a "just this once" flag is that argument with a keyboard.
# The ONE legal override is `DJB_LOOP_SCOPE_ALSO`, and it can only WIDEN: every
# label it names is added and none is removed, so the worst it can do is run
# more. It is printed in the banner whenever it is set. It is unchanged by the
# census seeds below: those are DERIVED from the changed paths, and an override
# is something a person types.
#
# ---------------------------------------------------------------------------
# CENSUS-SEEDED FILES: THE CORE CENSUSES THAT READ OTHER APPS' DECLARATIONS
#
# THE HOLE THIS CLOSES, and it was paid for. The closure this file walks is the
# REVERSE `depends_on` one: for a change in `apps/<x>`, the apps that depend on
# `<x>`. `core` is a DEPENDENCY of every app and a dependant of none, so
# `core`'s tests are never pulled in by another app's change — which is right
# for nearly all of them, and wrong for the handful that quantify over EVERY
# app's declarations. A rung that adds a permission key to its own
# `policies.py` moves a census that lives in `core`, and no `--loop` anywhere
# ran it. It was found at a bank, by a hotfix.
#
# SO THE RULE IS: a changed file that DECLARES something a core census reads
# seeds that census's test MODULE into the selection — and nothing else. Not
# the `core` app, not `core`'s organ tests, not a closure: one module, through
# the same `--djb-changed-test` seam an edited test module already uses, so the
# footer's `selected=` count for a declarations-only change grows by that
# module's tests and by nothing at all besides. The cost of an unrelated rung
# must not move, and this is what keeps that true.
#
# THE POPULATION IS DERIVED AND THIS FILE NAMES NO APP AND NO MODULE. A census
# that wants to be run says so IN ITS OWN SOURCE — `CENSUS_SEEDED_BY = (...)` at
# column zero in a test module, naming the declaration modules it quantifies
# over — and `loop_scope__census_modules` walks `apps/*/tests/test_*.py` for
# that marker. So the map from a changed declaration to the census that reads it
# is read off the tree, the way `selftest_registered_drives` reads the drive
# order off `check.sh`, and a product's own census joins the day it writes the
# line.
#
# IT USED TO BE A PATTERN WITH `apps/core` TYPED INTO IT, and that was a defect
# the standing case `the table names no app` exists to refuse: `core` reaches
# everything because everything DECLARES it, and the same must be true of the
# censuses `core` holds. Nothing in this file may name an app.
#
# THE ONE MEMBER ON THIS TREE, derived rather than listed here — run
# `loop_scope__census_modules` to see today's — is the permission vocabulary's,
# over `policies` and `roles`: the two modules
# `apps.core.authz._declarations` walks, in ONE discovery walk.
#
# does_not_cover — checked, and deliberately NOT seeded, each with its reason:
#
#   * THE KINDS HALF of the same census (`apps/*/models.py` -> a kind per
#     first-party model). Not seeded: `models.py` is touched by a large share of
#     all rungs, and a seed there would move the cost of nearly every loop —
#     which is the one thing the rule above exists not to do. The trigger to buy
#     it anyway: a models-only rung that reddens the kinds census at a bank.
#     Until then the full gate at push is the belt, as it is for every other
#     coupling that is not an import.
#   * THE DOORS (house rules 17 and 46 — a capability on both doors, and the
#     door-pair parity test). Nothing to seed: these are GATE LEGS, and a gate
#     leg runs at every scope including an empty one. A census that is always-on
#     never needed the scope to carry it.
#   * ADR CITATIONS. Same answer: `adr-census` is a `--fast` leg, so it runs on
#     every `--loop` and every `--fast` whatever the scope derived.
#   * THE APPS-ROOT MODULES (`apps/test_*.py`). Already always-on BY
#     CONSTRUCTION — an item whose nodeid names no app can never be inside any
#     scope (`apps/conftest.py`, `_is_always_on`).
#
# ---------------------------------------------------------------------------
# THE FAN-OUT DECISION TABLE. Every changed path is classified into exactly one
# shape, and the shapes are here rather than at the call site so that the rule
# and the sentence the leg prints for it cannot drift apart.
#
#   shared-test-infra   the four shapes above          -> FULL suite
#   apps-boundary       apps/__init__.py, manage.py    -> FULL suite
#   config              config/**                      -> FULL suite: settings,
#                       the URL conf, the api mapper and the ASGI entry point
#                       are under every test in the tree, and no app owns them.
#   templates           templates/**                   -> FULL suite: no app
#                       owns them and a render reaches them from anywhere.
#   app                 apps/<x>/**                    -> `<x>` and its closure
#   frontend            frontend/**                    -> NO backend scope at
#                       all. The largest win in the table, and the honest one:
#                       there is no import path from `frontend/` into a Python
#                       test. R-c's change-awareness in the `fe` leg is what
#                       grades that change and is untouched here.
#   quality             quality/**                     -> NO pytest widening.
#                       The rules engine has its own canary self-test and a
#                       `quality/**` rung runs the FULL GATE under a typed
#                       sanction (rung-execution §3) — a rule that outranks any
#                       widening this table could do, so doing one here would
#                       buy a second, weaker copy of a wall that already binds.
#                       The banner names that rule every time this shape fires.
#   inert               a known territory with no pytest blast radius: docs,
#                       skills, CI config, deploy, compose, the Dockerfile,
#                       the vendor drop, the editor and git dotfiles, the rest
#                       of `scripts/`. `.gitattributes` is here with
#                       `.gitignore`: git reads it at a MERGE and nothing in
#                       this tree executes it, so the wall on the one line it
#                       carries (`CHANGELOG.md merge=union`) is
#                       `scripts/tests/test_pm_merge.sh` in the selftest leg,
#                       not a pytest widening this table could do.
#   declared-blind-spot `pyproject.toml` and `uv.lock` — see below.
#   UNCLASSIFIABLE      -> EXIT 2, naming the path and this file.
#
# AN UNCLASSIFIABLE PATH IS EXIT 2 AND NEVER A GUESS IN EITHER DIRECTION. A
# silent full run wastes a builder's minutes; a silent narrow one grades a rung
# against a suite that never saw its change. Both are worse than stopping and
# saying which path this table has no row for. The remedy is one line in
# `loop_scope__classify` below, written by whoever added the territory.
#
# WHAT IS DELIBERATELY NOT A WIDENING TRIGGER: `pyproject.toml`, which carries
# pytest's ini options, and `uv.lock` beside it. They are left out because
# "configuration that could affect tests" has no edge — settings, compose, the
# lockfile and the gate itself all qualify on that reading — and a class with no
# edge stops being derivable and becomes a list somebody maintains. The shapes
# above are shapes; these two would be the first entries of a list. They are
# classified `declared-blind-spot` rather than left unclassifiable so the table
# says out loud that it saw them and chose, and the cover for them is a
# different wall: a rung that touches either is a DEPENDENCY rung and runs the
# FULL gate (rung-execution §3).
# ---------------------------------------------------------------------------

# THE REFUSAL SEAM. Every `!!` headline below goes through `gate_refuse`, which
# prints exactly what it printed before AND records it, so the banner in
# scripts/check.sh that says "see above" can say what the above was. Sourced by
# this file's own directory rather than by the caller's cwd, because the drives
# source this library from wherever they happen to be standing, and guarded so a
# gate that sources six libraries sources the seam once.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

#: `fast` (the derived fast tier, narrowed to the scope) or `full` (every test).
LOOP_TIER_MODE="fast"

#: Space-separated app labels, set by loop_tier_own_apps. Legitimately empty,
#: and meaningless when the mode is `full` — there is nothing left to promote.
#:
#: THE TOUCHED APPS ONLY, NEVER THE CLOSURE, and the distinction is a
#: measurement rather than a preference. "Own app" means RUN IN FULL, organ
#: tests included, so that a builder working in `apps/exports` pays for its
#: real-MinIO tests in the rung instead of meeting them at push. That is right
#: for an app the active rung EDITED. It is wrong for an app the closure pulled in:
#: the closure's claim is "your change might break this", which the fast tier
#: answers, and promoting all of it would make an `apps/core` touch run every
#: organ test in the tree — SLOWER than the tier it replaced. The two roles are
#: therefore two lists: this one drives the organ rule, LOOP_SCOPE_APPS drives
#: the narrowing.
LOOP_TIER_OWN_APPS=""

#: Space-separated shared-test-infrastructure paths that forced `full`. Empty
#: whenever the mode is `fast`. The leg PRINTS these: a full suite nobody can
#: see the cause of is as unfalsifiable as a silent fast tier.
LOOP_TIER_SHARED_HITS=""

#: One sentence naming the rule that was applied and why. The leg prints it on
#: every single run.
LOOP_TIER_REASON=""

#: The sentence naming what was compared against what — the secret scan's own
#: basis, because it is the same question asked once.
LOOP_TIER_BASIS=""

#: 1 when the pytest leg should narrow to the scope, empty when it must not.
#: `full` never narrows; neither does a derivation that refused.
LOOP_SCOPE_NARROW=""

#: The derived scope: sorted, space-separated app labels. Legitimately empty.
LOOP_SCOPE_APPS=""

#: The apps the changed-file set named DIRECTLY, before the closure widened it.
LOOP_SCOPE_TOUCHED=""

#: The apps the closure ADDED, i.e. LOOP_SCOPE_APPS minus LOOP_SCOPE_TOUCHED.
#: Printed separately so the banner can spell the widening out rather than
#: presenting a set nobody can trace back to a change.
LOOP_SCOPE_WIDENED=""

#: The shapes this run's changed paths classified into, sorted and deduped.
LOOP_SCOPE_SHAPES=""

#: Extra sentences the banner prints — one per shape that has something to
#: disclose (quality/**, frontend-only, config/**, the declared blind spot).
LOOP_SCOPE_NOTES=""

#: The canonical scope string that goes into the loop ledger's key. Same tree,
#: two scopes -> two keys, so a verdict banked at one scope can never vouch for
#: a wider one. See gate_ledger.sh's loop-ledger section.
LOOP_SCOPE_CANONICAL=""

#: The CALLER'S request for `--mine`: 1 when `check.sh --loop --mine` asked for
#: the own apps alone. Read here and set nowhere in this file — `check.sh` owns
#: the flag, this library owns what it MEANS to the derivation, and the meaning
#: is exactly one subtraction: the reverse-transitive `depends_on` closure is
#: not walked into the scope. Everything else about the derivation — the shared-
#: infrastructure outranking, the tests-only row, the always-on set, every
#: refusal — is unchanged, because a mode that quietly relaxed a refusal as well
#: as a scope would be two narrowings wearing one flag.
LOOP_MINE="${LOOP_MINE:-}"

#: The app labels whose ONLY changed paths are under `apps/<x>/tests/`. They are
#: NOT in the closure walk and NOT own: each runs its own test tree at the fast
#: tier, plus every collected module whose source names `apps.<x>.tests`, which
#: `apps/conftest.py` derives from the modules themselves (contract A.1).
LOOP_SCOPE_TESTS_ONLY=""

#: The `test_*.py` modules a tests-only app actually changed, repo-relative.
#: They run whatever tier they are in — an organ-reaching module the rung EDITED
#: is the one organ test a per-rung gate has a reason to run.
LOOP_SCOPE_CHANGED_TESTS=""
#: The core census MODULES the active rung's changed declarations seeded, and the
#: files that seeded them. Two sets rather than one because the note names both
#: halves: a reader of `census-seeded by X: Y` can check X against their own
#: diff, and a seed with no seeder beside it is a line nobody can falsify.
LOOP_SCOPE_SEEDED_TESTS=""
LOOP_SCOPE_SEEDED_BY=""

#: The digest of the always-on derivation's DECLARATION — the sentinel-delimited
#: block in `apps/conftest.py`. Part of the canonical scope, because changing
#: which tests are unconditional changes what a green loop meant.
LOOP_SCOPE_ALWAYS_DIGEST=""

#: The digest of the `--loop` ALWAYS-ON LEG'S INPUTS — the committed member
#: durations and the set of drives declaring themselves cross-app. Part of the
#: canonical scope for the same reason the line above is: changing which
#: full-only members the loop runs changes what a green loop meant, and neither
#: input is visible anywhere else in the key.
LOOP_SCOPE_ALWAYS_ON_DIGEST=""

# --- THE TEST-IMPACT MAP, CONSULTED ------------------------------------------
#
# The scope above answers "which apps can this change reach", from the app
# declarations. The map answers the question underneath it — WHICH TESTS
# EXECUTED THIS FILE — from one acceptance run's per-test coverage contexts
# (`scripts/test_impact.py` writes it; its header is the authority on what it
# is and what it cannot see). A changed file the map has SEEN therefore selects
# the tests that reach it and nothing else, and the closure becomes the
# FALLBACK rather than the rule.
#
# IT IS A PROJECTION AND NEVER TRUTH (principle 9), so every reader owes a
# fallback and this one owes four:
#
#   1. A CHANGED FILE THE MAP HAS NEVER RECORDED — a template, a fixture, a
#      migration, `quality/rules.yaml`, a brand-new module — falls the WHOLE
#      run back to today's closure scope, printed with the path and its class.
#      Coverage sees executed Python lines and nothing else, so everything a
#      test reads by path is invisible here BY CONSTRUCTION.
#   2. AN ABSENT OR UNREADABLE MAP is the closure scope, printed, and never
#      exit 2: a product that has not run an acceptance box yet has no map, and
#      a loop that refused would be a loop nobody could run.
#   3. A STALE MAP is the closure scope, printed. Stale is measured, not
#      assumed: the map names the tree it was MEASURED on (its predecessor —
#      committing the map moves the tree), and when this checkout's history can
#      account for that tree the map is fresh, and when it can account for the
#      history and NOT the tree the map belongs to a tree this base never had.
#   4. A SEEDED CENSUS MODULE THE MAP HOLDS NO TEST FROM is the closure scope:
#      a selection that silently dropped a census the scope seeded would be a
#      narrowing nobody asked for.
#
# AND THE ONE CASE THAT IS NOT A FALLBACK, because it cannot be answered: a
# SHALLOW checkout (the verifier box's depth-1 mirror, `verifier_box.sh push`)
# holds the rung's own commits and the carried fork point and no history behind
# them, so the map's measured tree is not there to find and its ABSENCE means
# nothing. That is printed as `age=unverifiable (shallow history)` and the
# selection proceeds — because reading an undecidable question as "stale" would
# un-narrow every run on the one machine this loop is measured on, and because
# nothing that makes a selection SAFE depends on the age: the never-seen rule
# above covers a file the map has not got, `apps/conftest.py`'s orphan refusal
# covers a nodeid the collection has not got, the map's sha is in the loop key
# so a verdict never crosses two maps, and the wave's bank runs everything.
# THE AGE IS A PRINTED NUMBER FOR A PERSON, NEVER A REFUSAL.
#
# WHAT THE SELECTION IS, exactly: the union over every SEEN changed file of the
# tests the map records against it, plus every test the map holds from a module
# the scope SEEDED (an edited test module is already a changed file, and a test
# module is one of its own tests' source files, so it needs no second rule).
# It is handed to pytest as `--djb-impact-select=<file>` — one nodeid per line,
# `apps/conftest.py`'s seam, which adds the always-on set and refuses an orphan
# — and the scope flags are DROPPED: a selection is the whole question, and a
# `--djb-scope=` beside it would only widen back what the map was asked to
# narrow.
#
# `--djb-changed=<path>` RIDES ON BOTH PATHS, selection and fallback alike. It
# narrows nothing by itself: it is what lets a DECLARED cross-app census with a
# `population=` clause sit out a run whose changed files are all outside it
# (`apps/conftest.py`'s population clause). The fallback run gets it for the same
# reason the selecting one does — the census population is not a projection and
# owes no staleness argument.
#
# THE VALVE IS `DJB_LOOP_NO_IMPACT`, AND IT ONLY WIDENS. Typed, it skips the
# consultation and runs today's closure scope, prints that it did, and keys the
# run `map=bypassed` — its own value, so a wide run can never be handed a
# verdict banked by a narrow one. It is the measurement's other half (a rung
# reports the same change with and without it), not a way to argue with a red.

#: The map this library consults. A positional default rather than an env var:
#: `loop_scope__always_on_digest` sets the precedent one section up, and a knob
#: that could NAME a different map is a knob that could narrow a run with one
#: nobody can see.
LOOP_SCOPE_MAP_PATH="scripts/test_impact.json"

#: The first 12 hex of the SHA-256 of the map file — `-` when there is none,
#: `bypassed` under the valve. LAST in the canonical scope, so the loop key
#: moves with the map and a verdict measured under one selection can never be
#: reused under another.
LOOP_SCOPE_MAP_SHA=""

#: The first 8 hex of the tree the map was MEASURED on (`generated.tree`), and
#: `-` when the map could not be read. The full sha beside it is what the
#: freshness walk compares; only the short form is ever printed.
LOOP_SCOPE_MAP_TREE=""
LOOP_SCOPE_MAP_TREE_FULL=""

#: `select` or `fallback`, as the map reader itself reported it. Absent is a
#: fallback: see loop_scope__impact.
LOOP_SCOPE_IMPACT_STATUS=""

#: How far the base has moved since the map's own commit, in commits, for a
#: person: a number, `unverifiable` in a shallow checkout, `-` when there is no
#: map. Printed, never enforced.
LOOP_SCOPE_MAP_AGE=""

#: The file holding the selected nodeids, one per line. EMPTY is the fallback:
#: every reader of this variable treats "no selection" and "today's closure" as
#: the same thing, so a derivation that could not answer cannot become a narrow
#: run by omission.
LOOP_SCOPE_IMPACT_SELECT=""

#: How many tests the selection holds, and how many changed files it came from.
LOOP_SCOPE_IMPACT_TESTS=""
LOOP_SCOPE_IMPACT_SEEN=""

#: Why there is no selection, in one sentence naming the file and its class.
#: Empty exactly when a selection was made.
LOOP_SCOPE_IMPACT_FALLBACK=""

#: Every changed path, in the classification order, for `--djb-changed`. The
#: TSV beside it is the same set with each path's SHAPE in front of it, one
#: `<shape><TAB><path>` line each, so the map reader can name a never-seen
#: file's class without classifying anything a second time.
LOOP_SCOPE_CHANGED_FILES=""
LOOP_SCOPE_CHANGED_TSV=""

#: The CALLER'S request for the map, read here and set nowhere in this file —
#: the same division `LOOP_MINE` is under: `check.sh` owns the flag, this
#: library owns what it means. Only the ordinary `--loop` sets it. `--pr`
#: grades a whole proposed change and must not be narrowed by one run's
#: measurement of a different tree; `--mine` is a claim about an app, and a
#: selection that reached into a DEPENDANT of that app to run one test would be
#: a third thing wearing the flag's name.
LOOP_IMPACT="${LOOP_IMPACT:-}"

#: The repository this library lives in, so the closure can be read with this
#: checkout's own interpreter even when the tree under test is somewhere else.
LOOP_TIER_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)

# loop_tier__is_shared_test_infra <path>
#
# 0 when the path is shared test infrastructure by one of the four shapes above.
# Kept as its own function so the drive can reason about one path at a time and
# so the enumeration sits in exactly one place.
loop_tier__is_shared_test_infra() {
    local path=$1
    case "$path" in
    # (1) a conftest an app owns — checked FIRST, because it is the negative
    # that the rest of the conftest shape would otherwise swallow.
    apps/*/*conftest.py) return 1 ;;
    # (1) every other conftest.py, at any depth outside `apps/<x>/`.
    conftest.py | */conftest.py) return 0 ;;
    # (2) a test module at the `apps/` root, owned by no app.
    apps/test_*.py) return 0 ;;
    # (3) the gate's own drives and their preamble.
    scripts/tests/*) return 0 ;;
    # (4) the selection machinery itself — the reflexive shape.
    scripts/loop_tier.sh | scripts/check.sh | scripts/secrets_scan.sh | scripts/gate_ledger.sh) return 0 ;;
    esac
    return 1
}

# loop_tier__is_app_tests_path <path>
#
# 0 when the path is `apps/<x>/tests/…` — the app's OWN test tree, and nothing
# else. This is the whole of the "tests-only" shape (contract A.1), and it is a
# function rather than a case pattern because `*` SPANS `/` in a bash case
# pattern: `apps/*/tests/*` also matches `apps/a/b/tests/c.py`, whose label is
# `a` and whose second segment is not `tests` at all.
#
# THE APP-ROOT `apps/<x>/conftest.py` IS DELIBERATELY NOT THIS SHAPE. It is a
# fixture every module of <x> stands on, so touching it is an ordinary change to
# <x> — the closure and all. The first draft of the rule had it the other way
# and the difference is recorded rather than discovered.
loop_tier__is_app_tests_path() {
    local rest
    case "$1" in
    apps/*) ;;
    *) return 1 ;;
    esac
    rest=${1#apps/}
    rest=${rest#*/}
    case "$rest" in
    tests/*) return 0 ;;
    esac
    return 1
}

# loop_scope__classify <path>
#
# Prints ONE shape name on stdout. Exit 0 classified · 1 unclassifiable.
# Every row of the decision table above is a case here, in the table's order,
# and the order is load-bearing where two rows could both match.
loop_scope__classify() {
    local path=$1
    if loop_tier__is_shared_test_infra "$path"; then
        printf 'shared-test-infra\n'
        return 0
    fi
    case "$path" in
    # The `apps` package boundary and the entry point: no app owns them and
    # every test stands on them.
    apps/__init__.py | manage.py)
        printf 'apps-boundary\n'
        return 0
        ;;
    # THE TESTS-ONLY ROW, and it is checked BEFORE the app row it narrows.
    # A change inside an app's own test tree cannot break another app's CODE:
    # the only coupling it CAN break is a cross-app TEST import, and that is
    # derived from the collected modules' own source rather than walked through
    # the declarations. So this row seeds no closure — which is the whole point:
    # the reverse closure of the app that holds the shared census helpers is
    # every app in the tree, and a one-token edit to one of those tests used to
    # buy exactly that.
    apps/*/tests/*)
        if loop_tier__is_app_tests_path "$path"; then
            printf 'app-tests\n'
            return 0
        fi
        printf 'app\n'
        return 0
        ;;
    apps/*/*)
        printf 'app\n'
        return 0
        ;;
    config/*)
        printf 'config\n'
        return 0
        ;;
    templates/*)
        printf 'templates\n'
        return 0
        ;;
    frontend/*)
        printf 'frontend\n'
        return 0
        ;;
    quality/*)
        printf 'quality\n'
        return 0
        ;;
    pyproject.toml | uv.lock)
        printf 'declared-blind-spot\n'
        return 0
        ;;
    # Known-inert territories, each one a place a change cannot reach a Python
    # test from. Enumerated rather than defaulted: the default is exit 2.
    docs/* | .claude/* | .github/* | .devcontainer/* | deploy/* | compose/* | \
        perf/* | vendor/* | scripts/* | templates | frontend | Dockerfile | \
        .dockerignore | compose.yaml | .editorconfig | .gitignore | \
        .gitattributes | \
        .python-version | .secrets.baseline | .env.example | TEMPLATE_VERSION | \
        *.md)
        printf 'inert\n'
        return 0
        ;;
    esac
    return 1
}

# loop_scope__note <sentence> — append one disclosure sentence, deduped.
loop_scope__note() {
    case "
$LOOP_SCOPE_NOTES" in
    *"
$1"*) return 0 ;;
    esac
    LOOP_SCOPE_NOTES="${LOOP_SCOPE_NOTES}${LOOP_SCOPE_NOTES:+
}$1"
}

# loop_scope__add <var-name> <label> — append a label to a space-separated set,
# deduped. bash 3.2 has no associative arrays and macOS ships bash 3.2.
loop_scope__add() {
    local var=$1 label=$2 current
    eval "current=\${$var}"
    case " $current " in
    *" $label "*) return 0 ;;
    esac
    eval "$var=\"\${$var}\${$var:+ }\$label\""
}

# loop_scope__census_modules
#
# EVERY TEST MODULE THAT DECLARES ITSELF A CENSUS over other apps' declarations,
# one `<declaration module>\t<path>` line per name it declares. Derived, the way
# `selftest_registered_drives` is derived: nothing here knows a module path or an
# app, and a product's own census joins the day it writes the marker.
#
# THE MARKER IS THE CENSUS'S OWN. A module says `CENSUS_SEEDED_BY = ("policies",
# "roles")` at column zero, meaning: those are the declaration modules I
# quantify over, so a rung that changes one of them in ANY app has moved what I
# assert about. `apps/core/tests/test_vocabulary.py` is the first; the walk is
# over `apps/*/tests/test_*.py` and names none of them.
#
# ONE `grep -l` AND THEN A READ PER HIT, because the alternative is a `sed` per
# test module on every single `--loop`. The `|| true` is the no-hit case: an
# empty population is legal here (a product with no such census) and is NOT the
# could-not-look the closure walk has — nothing is being narrowed on the
# strength of it.
loop_scope__census_modules() {
    local path decls decl
    for path in $(grep -l '^CENSUS_SEEDED_BY' apps/*/tests/test_*.py 2>/dev/null || true); do
        decls=$(sed -n 's/^CENSUS_SEEDED_BY[^=]*=[[:space:]]*(\(.*\))[[:space:]]*$/\1/p' "$path" | sed -n 1p)
        [ -n "$decls" ] || continue
        for decl in $(printf '%s' "$decls" | tr ',' ' ' | tr -d "\"'"); do
            [ -n "$decl" ] || continue
            printf '%s\t%s\n' "$decl" "$path"
        done
    done
}

# loop_scope__census_seed <changed path>
#
# THE CENSUS-SEEDED FILES, DERIVED. See the CENSUS-SEEDED FILES section of this
# file's header for the class, what is seeded and what is deliberately not.
# NOTHING HERE NAMES AN APP OR A MODULE: the changed path's own basename is
# matched against the declaration names the censuses above publish, and the
# module that gets seeded is the one that published the name.
#
# THE DECLARING APP'S OWN CENSUS IS NOT SEEDED, and that is the derived form of
# a rule that used to be spelled `apps/core/*`: when the changed file and the
# census module are in the SAME app, that app is already a touched app and its
# whole test tree — the census included — is already in the selection. Seeding
# it again would put a note in front of a reader about a module that was never
# at risk. Read off the two paths, so it holds for whichever app a product puts
# its own census in.
#
# Returns 0 always. A path that seeds nothing is the overwhelming majority.
loop_scope__census_seed() {
    local path=$1 base decl module changed_app census_app
    case "$path" in
    apps/*/*.py) ;;
    *) return 0 ;;
    esac
    base=${path##*/}
    base=${base%.py}
    changed_app=${path#apps/}
    changed_app=${changed_app%%/*}
    while IFS=$(printf '\t') read -r decl module; do
        [ -n "$module" ] || continue
        [ "$decl" = "$base" ] || continue
        census_app=${module#apps/}
        census_app=${census_app%%/*}
        [ "$census_app" != "$changed_app" ] || continue
        loop_scope__add LOOP_SCOPE_SEEDED_TESTS "$module"
        loop_scope__add LOOP_SCOPE_SEEDED_BY "$path"
    done <<EOF
$(loop_scope__census_modules)
EOF
    return 0
}

# loop_scope__sorted <space-separated set> — the same set, sorted, on stdout.
loop_scope__sorted() {
    local one out=""
    for one in $1; do
        out="${out}${one}
"
    done
    [ -n "$out" ] || return 0
    printf '%s' "$out" | sort | tr '\n' ' ' | sed 's/ $//'
}

# loop_scope__python — the interpreter that can read this repo's own modules.
#
# THE VENV, AND NOTHING ELSE. `uv run` would work and is deliberately not the
# fallback: it re-resolves on the gate's cheap path, and in a checkout with no
# venv it would SYNC one — minutes of surprise side effect inside a derivation
# that is supposed to answer a question about git.
#
# SO AN UNPROVISIONED CHECKOUT IS COULD-NOT-LOOK, and that costs nothing real:
# every leg of this gate runs under `uv run`, so a checkout with no venv cannot
# run the suite either and this is never the first thing its owner meets.
# Measured in a `verify_start` clone, which does not `uv sync` by design
# (`scripts/verify_start.sh:127`) — there the honest answer is exit 2 until
# `./scripts/setup.sh` has run, exactly as it is for every other leg.
loop_scope__python() {
    if [ -x "$LOOP_TIER_ROOT/.venv/bin/python" ]; then
        printf '%s\n' "$LOOP_TIER_ROOT/.venv/bin/python"
        return 0
    fi
    return 1
}

# loop_scope__closure <apps-dir> <label>...
#
# The reverse-transitive closure over `AppConfig.depends_on`, on stdout, one
# label per line, sorted. Exit 0 derived · 2 could not look, or a label the
# declarations cannot account for.
#
# THE DECLARATION IS READ, NEVER A LIST HERE. `config/settings/discovery.py` is
# the same static AST read that builds `INSTALLED_APPS`, so the edges this walks
# are the edges the app registry itself is built from. A copy of the graph in
# this file would be right on the day it was written.
loop_scope__closure() {
    local apps_dir=$1 py
    shift
    py=$(loop_scope__python) || {
        gate_refuse "the --loop scope could not find an interpreter to read the app"
        echo "   declarations with (${LOOP_TIER_ROOT}/.venv/bin/python is not executable)." >&2
        echo "   An underived closure is not an empty one." >&2
        return 2
    }
    DJB_SCOPE_APPS_DIR="$apps_dir" DJB_SCOPE_ROOT="$LOOP_TIER_ROOT" \
        "$py" - "$@" <<'PY'
import os
import pathlib
import sys

sys.path.insert(0, os.environ["DJB_SCOPE_ROOT"])

try:
    from config.settings.discovery import discover_apps
except Exception as exc:  # the reader itself is broken: could-not-look
    sys.stderr.write(
        "!! the --loop scope could not import config.settings.discovery "
        f"({exc}). The closure is read from the app declarations through that "
        "module and from nothing else.\n"
    )
    raise SystemExit(2)

apps_dir = pathlib.Path(os.environ["DJB_SCOPE_APPS_DIR"])
if not apps_dir.is_dir():
    sys.stderr.write(f"!! the --loop scope found no apps directory at {apps_dir}.\n")
    raise SystemExit(2)

try:
    discovered = discover_apps(apps_dir)
except Exception as exc:
    sys.stderr.write(
        f"!! the --loop scope could not read the app declarations under {apps_dir} "
        f"({exc}).\n"
    )
    raise SystemExit(2)

declared = {one.label: tuple(one.depends_on) for one in discovered}

# The REVERSE edges: dependent -> dependency becomes dependency -> dependent.
reverse: dict[str, set[str]] = {label: set() for label in declared}
for label, deps in declared.items():
    for dep in deps:
        # A dependency this tree cannot see is the app declarations disagreeing
        # with themselves; house rule 7 owns that verdict, not this walk.
        reverse.setdefault(dep, set()).add(label)

seeds = list(sys.argv[1:])
missing = [one for one in seeds if one not in declared]
if missing:
    for one in sorted(missing):
        sys.stderr.write(
            f"!! the --loop scope derived the app label '{one}' from a changed path "
            f"and the declarations do not know it: {apps_dir / one / 'apps.py'} "
            "declares no AppConfig, or is not there.\n"
        )
    raise SystemExit(2)

seen: set[str] = set()
queue = list(seeds)
while queue:
    label = queue.pop()
    if label in seen:
        continue
    seen.add(label)
    queue.extend(sorted(reverse.get(label, ())))

for label in sorted(seen):
    print(label)
PY
}

#: The sentinels that delimit the always-on DECLARATION in `apps/conftest.py`.
#: The digest is taken over exactly those bytes, so a change to which tests are
#: unconditional changes the loop ledger's key and no banked verdict survives it.
LOOP_SCOPE_ALWAYS_BEGIN='# >>> always-on-derivation >>>'
LOOP_SCOPE_ALWAYS_END='# <<< always-on-derivation <<<'

# loop_scope__always_digest <conftest path>
#
# The digest on stdout. `UNDECLARED` when the sentinel block cannot be found —
# which is a BROKEN READ, not an empty answer, and the loop ledger refuses to
# WRITE a key carrying it (gate_ledger.sh), so it can never become a hit on a
# derivation nobody could verify.
loop_scope__always_digest() {
    local path=$1 block
    [ -f "$path" ] || {
        printf 'UNDECLARED\n'
        return 0
    }
    block=$(awk -v b="$LOOP_SCOPE_ALWAYS_BEGIN" -v e="$LOOP_SCOPE_ALWAYS_END" '
        index($0, b) { on = 1; next }
        index($0, e) { on = 0; next }
        on { print }
    ' "$path")
    if [ -z "$block" ]; then
        printf 'UNDECLARED\n'
        return 0
    fi
    printf '%s' "$block" | sha256_of
}

# --- the DECLARED cross-app censuses, for the banner -------------------------
#
# WHY THE SHELL READS A MARKER THE PYTHON SIDE ALREADY READS. It reads it for a
# different reader. `apps/conftest.py` reads the marker to DECIDE — a marked
# module survives every scope. This reads it to SAY SO: a builder watching a
# `--loop` narrow a 4000-test suite to two apps has no way to tell which
# unconditional tests came with it, and an always-on set nobody can enumerate is
# an always-on set nobody audits. The decision stays in one place; only the
# sentence is here.
#
# THE MARKER IS ONE GRAMMAR, SPELLED TWICE AND DRIVEN ONCE. The string below and
# `DJB_CENSUS_MARKER` in the sentinel block are the same three words in two
# languages, which is a copy — so `scripts/tests/test_loop_tier.sh`'s
# `case_the_loop_banner_names_each_declared_census` asserts the two agree, and a
# rung that rewords one and not the other reds there rather than in a banner
# that quietly lists nothing.
LOOP_SCOPE_CENSUS_MARKER='# census: cross-app'

#: How far into a module the marker is looked for — `DJB_CENSUS_MARKER_LINES`'s
#: twin, and asserted against it by the same case.
LOOP_SCOPE_CENSUS_LINES=40

#: The optional clause inside the line: `<marker> population=<glob>[,<glob>]
#: <reason>`. `DJB_CENSUS_POPULATION`'s twin, asserted against it by the same
#: case, and here for the same one reason the marker is — the BANNER. The
#: population is the half a `--loop` acts on, so a reader who can see which
#: censuses came with the scope and not which files each one is about can audit
#: the set's membership and not its price. The DECISION stays in
#: `apps/conftest.py`; what is here is the sentence, and the refusal below that
#: keeps a half-written clause from reading as an absent one.
LOOP_SCOPE_CENSUS_POPULATION='population='

# loop_scope__declared_censuses [<dir>] [<filename pattern>]
#
# One `<module><TAB><reason>` line per DECLARED cross-app census, sorted, on
# stdout. An EMPTY SET IS A LEGITIMATE ANSWER and prints nothing at exit 0: a
# tree with no census to declare is a tree, not a broken read.
#
# TWO POPULATIONS, ONE READER, AND THAT IS THE WHOLE OF THE SECOND ARGUMENT.
# A cross-app census exists in two languages here — a pytest module under
# `apps/` read by `apps/conftest.py`'s always-on derivation, and a shell drive
# under `scripts/tests/` read by the `--loop` always-on leg. The MARKER GRAMMAR
# is one grammar (the marker at column zero in the first
# `LOOP_SCOPE_CENSUS_LINES` lines, followed by a reason), so it gets one reader:
# a second function would be a second place for the refusal below to be
# forgotten. The caller says which files to walk; nothing else differs.
#
# Exit: 0 the set was derived · 2 the directory is not there, or a module
# carries the marker with NO REASON after it, or with a `population=` and NO
# GLOBS after that — the same two refusals
# `apps/conftest.py::_module_census_declaration` makes, and for the same reason:
# read as an absent marker or an absent population, a half-written declaration
# changes what the always-on set holds and says nothing.
loop_scope__declared_censuses() {
    local dir=${1:-apps} pattern=${2:-'test_*.py'} path rest spec globs reason
    [ -d "$dir" ] || {
        printf '!! loop_scope__declared_censuses: %s is not a directory. The declared\n' "$dir" >&2
        printf '   cross-app censuses could not be read; nothing was listed.\n' >&2
        return 2
    }
    while IFS= read -r path; do
        # THE `FOUND:` PREFIX IS LOAD-BEARING. Without it a marker followed by
        # NOTHING and a module with no marker at all reach this loop as the same
        # empty string, and the refusal below would never fire — which is the
        # exact failure the refusal exists to prevent.
        rest=$(awk -v m="$LOOP_SCOPE_CENSUS_MARKER" -v n="$LOOP_SCOPE_CENSUS_LINES" '
            NR > n { exit }
            index($0, m) != 1 { next }
            {
                rest = substr($0, length(m) + 1)
                # `<marker>lication` is a different word, not this marker.
                if (rest != "" && rest !~ /^[ \t]/) next
                print "FOUND:" rest
                exit
            }
        ' "$path") || return 2
        case "$rest" in
        FOUND:*) rest=${rest#FOUND:} ;;
        *) continue ;;
        esac
        # Leading whitespace off, the sentence kept whole.
        rest=${rest#"${rest%%[![:space:]]*}"}
        # THE POPULATION COMES FIRST AND IT IS ONE WORD — `partition(" ")` in
        # the Python twin, `%% ` here. Split off so the REASON can be judged on
        # its own: a line that declared a population and then said nothing would
        # otherwise pass this reader and fail the door's.
        reason=$rest
        case "$rest" in
        "$LOOP_SCOPE_CENSUS_POPULATION"*)
            spec=${rest#"$LOOP_SCOPE_CENSUS_POPULATION"}
            globs=${spec%% *}
            [ -n "$globs" ] || {
                printf '!! %s declares an EMPTY POPULATION.\n' "$path" >&2
                printf '   The grammar is `%s %s<glob>[,<glob>] <reason>` (apps/conftest.py,\n' \
                    "$LOOP_SCOPE_CENSUS_MARKER" "$LOOP_SCOPE_CENSUS_POPULATION" >&2
                printf '   the sentinel block). A population nobody can match against is not a\n' >&2
                printf '   narrowing — it is a census every scope would deselect.\n' >&2
                return 2
            }
            reason=${spec#"$globs"}
            reason=${reason#"${reason%%[![:space:]]*}"}
            ;;
        esac
        [ -n "$reason" ] || {
            printf '!! %s carries the census marker and gives NO REASON.\n' "$path" >&2
            printf '   The grammar is the marker at column zero followed by one line saying\n' >&2
            printf '   what population the module walks (apps/conftest.py, the sentinel\n' >&2
            printf '   block). A declaration nobody can disagree with is not a declaration.\n' >&2
            return 2
        }
        printf '%s\t%s\n' "$path" "$rest"
    done < <(find "$dir" -type f -name "$pattern" | sort)
}

# --- the ALWAYS-ON set's own digest, for the banked loop key ------------------
#
# WHY A BANKED `--loop` VERDICT HAS TO CARRY THIS. The always-on leg runs a set
# that is DERIVED from two files that are not the tree the verdict is keyed on
# in any way a reader can see: the committed member-durations measurement, and
# the set of drives that declare themselves cross-app. Re-measure the durations
# and a member leaves the set; add a marker and one joins. Both move what the
# loop RAN without moving anything the key already carried, so a row banked
# before the move would be reused by a run that would have measured more — the
# one failure mode a verdict cache must not have.
#
# IT IS THE FILE'S BYTES AND THE MARKED SET'S TEXT, not the derived membership.
# Deriving the membership here would be a second implementation of the leg's own
# selection (the leg's is the one that runs), and the two would fall out of step
# in exactly the direction that makes a stale row reusable. Bytes are cheaper
# and strictly more conservative: a comment edit in the durations file re-keys a
# run that would have selected identically, which costs one loop and vouches for
# nothing it should not.
#
# AN ABSENT DURATIONS FILE IS A VALUE, NOT A REFUSAL. `no-durations` is what a
# tree before the first `--store-durations` looks like, and the leg says so on
# every run; keying it as its own value is what makes the first measurement
# re-key every banked row exactly once.
#
# Exit: 0 with the digest on stdout · 1 the marked set could not be read, which
# the caller turns into `UNDECLARED` exactly as `loop_scope__always_digest`'s
# broken read is — never a digest over a set nobody could enumerate.
#
# THE PARTS ARE ASSEMBLED INTO A VARIABLE AND THEN HASHED, never piped from a
# brace group: a `return` inside `{ ... } | sha256_of` returns from the
# pipeline's subshell and the function goes on to exit 0 with a digest over a
# half-read set. That is this file's own `loop_scope__closure` lesson (the one
# subshell callee, and the comment beside it) in miniature.
loop_scope__always_on_digest() {
    local durations=${1:-scripts/gate_member_durations.json}
    local drives=${2:-scripts/tests}
    local body marked
    if [ -r "$durations" ]; then
        body=$(cat "$durations") || return 1
    else
        body="no-durations"
    fi
    # THE MARKED SET, READ THROUGH THE ONE READER. A grep here would be a
    # second grammar for the marker; `loop_scope__declared_censuses` is the
    # reader the leg itself uses, and its refusal (a marker with no reason)
    # reaches this digest as a non-zero exit rather than as a silently
    # shorter list.
    if [ -d "$drives" ]; then
        marked=$(loop_scope__declared_censuses "$drives" 'test_*.sh') || return 1
    else
        marked="no-drives-dir"
    fi
    printf '%s\n%s\n' "$body" "$marked" | sha256_of
}

# loop_scope__map_fresh <tree sha>
#
# Exit: 0 this checkout's history accounts for the tree the map was measured on
# · 1 it accounts for the history and NOT for that tree (STALE) · 2 it cannot
# answer (a shallow mirror, no fork point, a scan that hit its ceiling).
#
# THE THREE ANSWERS ARE THREE, and collapsing the third into either of the
# others is the whole reason this is a function. Read as fresh, an undecidable
# answer would narrow a run on a map from another tree; read as stale, it would
# un-narrow every run on the verifier box, whose mirror is depth-1 BY DESIGN
# (scripts/verifier_box.sh) and therefore holds no tree older than the carried
# fork point. The caller prints which of the three it got.
loop_scope__map_fresh() {
    local tree=$1 base scan limit found=1
    [ -n "$tree" ] && [ "$tree" != "-" ] || return 2
    [ "$(git rev-parse --is-shallow-repository 2>/dev/null || printf 'true')" = "false" ] || return 2
    base=$(git merge-base HEAD "${SECRETS_SCAN_BASE_REF:-refs/heads/main}" 2>/dev/null) || base=""
    [ -n "$base" ] || return 2
    limit=${DJB_LOOP_MAP_SCAN:-800}
    scan=$(mktemp "${TMPDIR:-/tmp}/djb-loop-mapscan.XXXXXX") || return 2
    # WRITTEN WHOLE, THEN READ — never `git rev-list … | grep -q`, which closes
    # the pipe on the first hit and hands a producer with thousands of lines
    # left a SIGPIPE that `set -o pipefail` reports as a failure. The same
    # class every reader in scripts/check.sh is written for.
    if ! git rev-list --max-count="$limit" --format=%T "$base" >"$scan" 2>/dev/null; then
        rm -f "$scan"
        return 2
    fi
    grep -Fx -- "$tree" "$scan" >/dev/null && found=0
    rm -f "$scan"
    return "$found"
}

# loop_scope__map_age <map path>
#
# How many commits the base has taken since the one that last wrote the map, on
# stdout: a number, or `unverifiable` where the history cannot answer. It is a
# NUMBER FOR A PERSON — the PM deciding whether a wave owes a re-measurement —
# and nothing in this file branches on it.
loop_scope__map_age() {
    local path=$1 base commit age
    base=$(git merge-base HEAD "${SECRETS_SCAN_BASE_REF:-refs/heads/main}" 2>/dev/null) || base=""
    if [ -z "$base" ] ||
        [ "$(git rev-parse --is-shallow-repository 2>/dev/null || printf 'true')" != "false" ]; then
        printf 'unverifiable\n'
        return 0
    fi
    commit=$(git log -1 --format=%H "$base" -- "$path" 2>/dev/null) || commit=""
    if [ -z "$commit" ]; then
        printf 'unverifiable\n'
        return 0
    fi
    age=$(git rev-list --count "${commit}..${base}" 2>/dev/null) || age=""
    printf '%s\n' "${age:-unverifiable}"
}

# loop_scope__impact [<map path>]
#
# THE CONSULTATION. Sets LOOP_SCOPE_MAP_SHA / _TREE / _AGE and either
# LOOP_SCOPE_IMPACT_SELECT (a selection) or LOOP_SCOPE_IMPACT_FALLBACK (one
# sentence saying why there is none). This file's TEST-IMPACT MAP section is
# the rule and its four fallbacks; this is the arithmetic.
#
# RETURNS 0 ALWAYS, and that is the declaration: it decides how much to RUN,
# never whether the tree is good. Every way it can fail to answer is a BIGGER
# run with a printed reason — there is no input that makes the loop narrower
# than today's closure by accident, which is why it has no refusal.
loop_scope__impact() {
    local map=${1:-$LOOP_SCOPE_MAP_PATH} py out changed modules line key value fresh
    LOOP_SCOPE_MAP_SHA="-"
    LOOP_SCOPE_MAP_TREE="-"
    LOOP_SCOPE_MAP_TREE_FULL=""
    LOOP_SCOPE_MAP_AGE="-"
    LOOP_SCOPE_IMPACT_SELECT=""
    LOOP_SCOPE_IMPACT_TESTS=""
    LOOP_SCOPE_IMPACT_SEEN=""
    LOOP_SCOPE_IMPACT_FALLBACK=""
    LOOP_SCOPE_IMPACT_STATUS=""

    if [ -n "${DJB_LOOP_NO_IMPACT:-}" ]; then
        LOOP_SCOPE_MAP_SHA="bypassed"
        LOOP_SCOPE_IMPACT_FALLBACK="DJB_LOOP_NO_IMPACT is set — the map was NOT consulted and this run is today's closure scope. The valve only widens, and it keys itself map=bypassed so no verdict crosses between the two."
        return 0
    fi
    if [ ! -r "$map" ]; then
        LOOP_SCOPE_IMPACT_FALLBACK="${map} is absent or unreadable — closure scope. A tree whose acceptance box has never written a map is a tree, not a broken read."
        return 0
    fi
    LOOP_SCOPE_MAP_SHA=$(sha256_of "$map" 2>/dev/null | cut -c1-12) || LOOP_SCOPE_MAP_SHA=""
    if [ -z "$LOOP_SCOPE_MAP_SHA" ]; then
        LOOP_SCOPE_MAP_SHA="-"
        LOOP_SCOPE_IMPACT_FALLBACK="${map} could not be digested — closure scope. A map nobody can key a verdict on must not narrow one."
        return 0
    fi
    if [ -z "${LOOP_IMPACT:-}" ]; then
        # THE CALLER DID NOT ASK. `--pr` and `--mine` reach here; the sha is
        # already in hand and goes into the key — a `--mine` row says which map
        # the tree carried — and nothing else happens.
        LOOP_SCOPE_IMPACT_FALLBACK="the caller did not ask for the map (only the ordinary --loop consults it) — today's closure scope, unchanged."
        return 0
    fi
    if [ -z "$LOOP_SCOPE_CHANGED_FILES" ]; then
        LOOP_SCOPE_IMPACT_FALLBACK="the active rung changed no file this derivation can see, so there is nothing to select for — the scope is what it was and the always-on set runs alone."
        return 0
    fi

    py=$(loop_scope__python) || {
        LOOP_SCOPE_IMPACT_FALLBACK="this checkout has no interpreter to read the map with (${LOOP_TIER_ROOT}/.venv/bin/python is not executable) — closure scope."
        return 0
    }
    out=$(mktemp "${TMPDIR:-/tmp}/djb-loop-impact.XXXXXX") || {
        LOOP_SCOPE_IMPACT_FALLBACK="the selection file could not be created under ${TMPDIR:-/tmp} — closure scope."
        return 0
    }
    # THE INPUTS GO THROUGH THE ENVIRONMENT, ONE PER LINE, rather than argv: a
    # changed-file set is unbounded, and a rung that touched three hundred
    # files would meet the argument-list ceiling inside a derivation — the
    # worst place in the gate to meet it.
    changed="$LOOP_SCOPE_CHANGED_TSV"
    modules=""
    for line in $LOOP_SCOPE_SEEDED_TESTS; do
        modules="${modules}${line}
"
    done
    DJB_IMPACT_MAP="$map" DJB_IMPACT_OUT="$out" \
        DJB_IMPACT_CHANGED="$changed" DJB_IMPACT_MODULES="$modules" \
        "$py" - >"${out}.report" 2>&1 <<'PY'
import json
import os
import pathlib


def emit(key: str, value: object) -> None:
    print(f"{key}\t{value}")


map_path = os.environ["DJB_IMPACT_MAP"]
out_path = os.environ["DJB_IMPACT_OUT"]
changed = [
    line.split("\t", 1)
    for line in os.environ.get("DJB_IMPACT_CHANGED", "").splitlines()
    if "\t" in line
]
modules = [line for line in os.environ.get("DJB_IMPACT_MODULES", "").splitlines() if line.strip()]

try:
    doc = json.loads(pathlib.Path(map_path).read_text(encoding="utf-8"))
    tests = doc["tests"]
    if not isinstance(tests, dict) or not tests:
        raise ValueError("the map records no test")
    generated = doc.get("generated") or {}
except Exception as exc:  # an unreadable map is a bigger run, never a refusal
    emit("tree", "-")
    emit("status", "fallback")
    emit("reason", f"{map_path} could not be read as a map ({exc}) — closure scope")
    raise SystemExit(0)

# `tree:<sha>` is the writer's own label (scripts/test_impact.py) and the half
# after the colon is the sha; a value with no label is taken as the sha itself.
emit("tree", str(generated.get("tree", "-")).rsplit(":", 1)[-1] or "-")
emit("pytest", len(tests))

known: set[str] = set()
for files in tests.values():
    known.update(files)

unseen = [(shape, path) for shape, path in changed if path not in known]
if unseen:
    shape, path = unseen[0]
    more = f", and {len(unseen) - 1} more it has not" if len(unseen) > 1 else ""
    emit("status", "fallback")
    emit("reason", f"{path} ({shape}) never recorded by the map{more} — closure scope")
    raise SystemExit(0)

seen = {path for _shape, path in changed}
selected = {nodeid for nodeid, files in tests.items() if not seen.isdisjoint(files)}
for module in modules:
    held = {nodeid for nodeid in tests if nodeid.split("::", 1)[0] == module}
    if not held:
        emit("status", "fallback")
        emit(
            "reason",
            f"{module} is seeded into the selection and the map holds no test from "
            "it — closure scope",
        )
        raise SystemExit(0)
    selected |= held

pathlib.Path(out_path).write_text("".join(f"{one}\n" for one in sorted(selected)), encoding="utf-8")
emit("status", "select")
emit("selected", len(selected))
emit("seen", len(seen))
PY
    # THE REPORT IS READ AS KEY/VALUE AND NEVER EVALUATED, and a report with no
    # `status` line — an interpreter that died mid-write, a traceback where the
    # answer should be — falls back by DEFAULT rather than by a branch somebody
    # remembered to write.
    while IFS=$(printf '\t') read -r key value; do
        case "$key" in
        tree)
            LOOP_SCOPE_MAP_TREE_FULL="$value"
            LOOP_SCOPE_MAP_TREE=$(printf '%s' "$value" | cut -c1-8)
            ;;
        status) LOOP_SCOPE_IMPACT_STATUS="$value" ;;
        reason) LOOP_SCOPE_IMPACT_FALLBACK="$value" ;;
        selected) LOOP_SCOPE_IMPACT_TESTS="$value" ;;
        seen) LOOP_SCOPE_IMPACT_SEEN="$value" ;;
        esac
    done <"${out}.report"
    LOOP_SCOPE_MAP_AGE=$(loop_scope__map_age "$map")

    if [ "$LOOP_SCOPE_IMPACT_STATUS" != "select" ]; then
        [ -n "$LOOP_SCOPE_IMPACT_FALLBACK" ] ||
            LOOP_SCOPE_IMPACT_FALLBACK="the map reader did not answer ($(sed -n 1p "${out}.report" 2>/dev/null)) — closure scope"
        rm -f "$out" "${out}.report"
        return 0
    fi

    fresh=0
    loop_scope__map_fresh "$LOOP_SCOPE_MAP_TREE_FULL" || fresh=$?
    case "$fresh" in
    1)
        LOOP_SCOPE_IMPACT_FALLBACK="the map was measured on tree:${LOOP_SCOPE_MAP_TREE} and this checkout's history does not hold that tree — a map from a tree this base never had is STALE, and a stale map is a slower run, never a wrong one."
        rm -f "$out" "${out}.report"
        return 0
        ;;
    2) LOOP_SCOPE_MAP_AGE="unverifiable" ;;
    esac

    if [ "$LOOP_TIER_MODE" = "full" ]; then
        # THE TABLE OUTRANKS THE MAP, and it is said here rather than by not
        # asking: the sentence above this one may already name a plant the map
        # has never seen, and a reader of a full run is owed BOTH halves.
        LOOP_SCOPE_IMPACT_FALLBACK="mode=full — the active rung changed a file every test in the tree stands on, and the FULL suite outranks any selection a map could make."
        rm -f "$out" "${out}.report"
        return 0
    fi

    rm -f "${out}.report"
    LOOP_SCOPE_IMPACT_SELECT="$out"
    return 0
}

# loop_tier_own_apps
#
# Exit: 0 the set was derived (it may legitimately be EMPTY) · 2 git could not
# answer, an unclassifiable path was met, or the closure could not be read —
# all of which are could-not-look and outrank a pass everywhere in the gate.
loop_tier_own_apps() {
    local list path label seen shape shapes closure touched rc tests_touched kept
    tests_touched=""
    kept=""
    LOOP_TIER_MODE="fast"
    LOOP_TIER_OWN_APPS=""
    LOOP_TIER_SHARED_HITS=""
    LOOP_TIER_REASON=""
    LOOP_TIER_BASIS=""
    LOOP_SCOPE_NARROW=""
    LOOP_SCOPE_APPS=""
    LOOP_SCOPE_TOUCHED=""
    LOOP_SCOPE_WIDENED=""
    LOOP_SCOPE_SHAPES=""
    LOOP_SCOPE_NOTES=""
    LOOP_SCOPE_CANONICAL=""
    LOOP_SCOPE_TESTS_ONLY=""
    LOOP_SCOPE_CHANGED_TESTS=""
    LOOP_SCOPE_SEEDED_TESTS=""
    LOOP_SCOPE_SEEDED_BY=""
    LOOP_SCOPE_ALWAYS_DIGEST=""
    LOOP_SCOPE_ALWAYS_ON_DIGEST=""
    LOOP_SCOPE_CHANGED_FILES=""
    LOOP_SCOPE_CHANGED_TSV=""
    LOOP_SCOPE_MAP_SHA=""
    LOOP_SCOPE_MAP_TREE=""
    LOOP_SCOPE_MAP_AGE=""
    LOOP_SCOPE_IMPACT_SELECT=""
    LOOP_SCOPE_IMPACT_FALLBACK=""

    # THE BASIS MUST BE A BASIS. `secrets_scan_changed_files` has a legal case
    # for a checkout with no local `refs/heads/main`: it derives the uncommitted
    # changes ALONE and says so. That is the right answer for a secret scan —
    # scanning fewer files is only ever a smaller claim. It is the WRONG answer
    # for a selection: everything the active rung committed becomes invisible, the
    # scope comes back empty, and the run grades the rung with the always-on set
    # as if that were the whole of it. Measured in a `verify_start` clone, which
    # is where it actually happens.
    #
    # THIS IS NOT A SECOND CHANGED-FILES DERIVATION and the distinction is the
    # amendment's own: nothing here computes a file set. It asks one yes/no
    # question about a precondition, and refuses. The `on main itself`
    # uncommitted-only basis stays legal and prints itself — there the
    # merge-base IS this HEAD and nothing committed is being hidden.
    #
    # IT ASKS AFTER THE INHERITED DERIVATION, NOT BEFORE, and the order is a
    # finding the active rung's own drive made: asked first, a directory that is not a
    # git repository at all answers "no refs/heads/main" and gets THIS refusal —
    # a message about a missing fork point, for a tree that has no git. The
    # inherited could-not-look has to win, so this question is only asked once
    # the derivation it qualifies has already answered.
    list=$(mktemp "${TMPDIR:-/tmp}/djb-loop-tier.XXXXXX") || return 2
    if ! secrets_scan_changed_files "$list"; then
        rm -f "$list"
        return 2
    fi
    LOOP_TIER_BASIS="$SECRETS_SCAN_BASIS"

    # THE SAME FORK POINT THE DERIVATION ABOVE USED, asked about by name. A
    # caller that moved it (`SECRETS_SCAN_BASE_REF` — a `--pr` run against a
    # named base commit) must have its precondition asked about ITS ref: asking
    # about `refs/heads/main` there would refuse a clone that legitimately has
    # none, and pass a clone whose `main` exists while the base it was actually
    # handed does not.
    if ! git rev-parse -q --verify "${SECRETS_SCAN_BASE_REF:-refs/heads/main}" >/dev/null 2>&1; then
        rm -f "$list"
        gate_refuse "this checkout has NO local ${SECRETS_SCAN_BASE_REF:-refs/heads/main}, so the --loop scope has no"
        echo "   fork point to derive the active rung from." >&2
        echo "   What that would silently mean: everything the active rung COMMITTED becomes" >&2
        echo "   invisible to the derivation, the scope comes back empty, and the run" >&2
        echo "   grades the rung against the always-on set as if that were the whole" >&2
        echo "   suite. A thin basis is not a small answer; it is the wrong one." >&2
        echo "   The two legal moves:" >&2
        echo "     1. create the ref at this clone's fork point:" >&2
        echo "          git branch main <the sha this branch was cut from>" >&2
        echo "        (scripts/verify_start.sh now does exactly this at clone time," >&2
        echo "        set to the MAIN_SHA it already verifies)" >&2
        echo "     2. run the gate in a checkout of the family that HAS one — the" >&2
        echo "        primary, or any linked worktree of it, whose refs live in the" >&2
        echo "        common git dir." >&2
        return 2
    fi

    seen=" "
    shapes=""
    touched=""
    while IFS= read -r -d '' path; do
        shape=$(loop_scope__classify "$path") || {
            rm -f "$list"
            gate_refuse "the --loop scope has NO ROW for this changed path: $path"
            echo "   The fan-out decision table is scripts/loop_tier.sh," >&2
            echo "   function loop_scope__classify. A path it cannot classify is" >&2
            echo "   exit 2 rather than a guess: a silent full run wastes a" >&2
            echo "   builder's minutes and a silent narrow one grades a rung" >&2
            echo "   against a suite that never saw its change." >&2
            echo "   The remedy is one case line, written by whoever added the" >&2
            echo "   territory." >&2
            return 2
        }
        loop_scope__add shapes "$shape"
        # THE PATH AND ITS SHAPE, KEPT. Both readers downstream are about the
        # FILE rather than about its app: `--djb-changed` hands every changed
        # path to the declared censuses' population test, and the map reader
        # names a never-seen file with the shape this line already derived.
        # Accumulated here so neither derives a second answer to a question
        # this loop has just asked (the amendment at the top of this file).
        LOOP_SCOPE_CHANGED_FILES="${LOOP_SCOPE_CHANGED_FILES}${LOOP_SCOPE_CHANGED_FILES:+ }$path"
        LOOP_SCOPE_CHANGED_TSV="${LOOP_SCOPE_CHANGED_TSV}${shape}	${path}
"
        # BEFORE THE SHAPE SWITCH, AND PATH-DRIVEN. The `app` arm below skips a
        # label it has already seen, so a second declaring file in one app would
        # never reach a seed placed inside it — and the question here is about
        # the PATH, not about the app.
        loop_scope__census_seed "$path"
        case "$shape" in
        shared-test-infra)
            case " $LOOP_TIER_SHARED_HITS " in
            *" $path "*) ;;
            *) LOOP_TIER_SHARED_HITS="${LOOP_TIER_SHARED_HITS}${LOOP_TIER_SHARED_HITS:+ }$path" ;;
            esac
            ;;
        apps-boundary | config | templates)
            case " $LOOP_TIER_SHARED_HITS " in
            *" $path "*) ;;
            *) LOOP_TIER_SHARED_HITS="${LOOP_TIER_SHARED_HITS}${LOOP_TIER_SHARED_HITS:+ }$path" ;;
            esac
            ;;
        app)
            label=${path#apps/}
            label=${label%%/*}
            [ -n "$label" ] || continue
            case "$seen" in
            *" $label "*) continue ;;
            esac
            seen="$seen$label "
            touched="${touched}${touched:+ }$label"
            ;;
        app-tests)
            label=${path#apps/}
            label=${label%%/*}
            [ -n "$label" ] || continue
            loop_scope__add tests_touched "$label"
            # The EDITED modules, kept by path. `test_*.py` is `pyproject.toml`'s
            # own `python_files`, so a helper under `tests/` widens the app's
            # test tree without claiming to be a module pytest will collect.
            case "${path##*/}" in
            test_*.py) loop_scope__add LOOP_SCOPE_CHANGED_TESTS "$path" ;;
            esac
            ;;
        esac
    done <"$list"

    rm -f "$list"

    LOOP_SCOPE_SHAPES=$(loop_scope__sorted "$shapes")

    # The disclosure sentences, one per shape that has something to say. Written
    # here so the shape and its sentence cannot drift apart.
    case " $LOOP_SCOPE_SHAPES " in
    *" quality "*)
        loop_scope__note "quality/** was touched and widens NO pytest scope: a quality/** rung runs the FULL GATE under a typed DJB_GATE_SANCTION (rung-execution §3), and that rule outranks any widening this table could do."
        ;;
    esac
    case " $LOOP_SCOPE_SHAPES " in
    *" declared-blind-spot "*)
        loop_scope__note "pyproject.toml / uv.lock was touched and widens NO scope — the declared blind spot, re-declared: a rung touching either is a DEPENDENCY rung and runs the FULL gate (rung-execution §3), which is the wall that covers it."
        ;;
    esac
    case " $LOOP_SCOPE_SHAPES " in
    *" frontend "*)
        loop_scope__note "frontend/** was touched and derives NO backend scope: there is no import path from frontend/ into a Python test. The fe leg's own change-awareness is what grades that change."
        ;;
    esac

    if [ -n "$LOOP_TIER_SHARED_HITS" ]; then
        # SHARED INFRASTRUCTURE OUTRANKS `--mine`, and it says so. `--mine`
        # subtracts a closure from a scope; this branch has no scope to subtract
        # from — the change is under a file every test in the tree stands on, so
        # there is no "own app" the run could honestly be narrowed to. A flag
        # that narrowed here would be a full-suite question answered by one app.
        if [ -n "${LOOP_MINE:-}" ]; then
            loop_scope__note "--mine narrowed NOTHING: the active rung changed shared test infrastructure, which outranks the flag — there is no own-app scope to subtract a closure from, so this run is the FULL suite."
        fi
        # The own-app list is discarded rather than reported: under `full` there
        # is nothing left to promote, and printing it would invite the reader to
        # think it still decided something.
        LOOP_TIER_MODE="full"
        LOOP_TIER_OWN_APPS=""
        LOOP_SCOPE_APPS=""
        LOOP_SCOPE_NARROW=""
        LOOP_TIER_REASON="the active rung changed shared test infrastructure or a file no app owns that every test stands on — so --loop runs the FULL suite, not a scope"
        LOOP_SCOPE_ALWAYS_DIGEST=$(loop_scope__always_digest "apps/conftest.py")
        LOOP_SCOPE_ALWAYS_ON_DIGEST=$(loop_scope__always_on_digest) ||
            LOOP_SCOPE_ALWAYS_ON_DIGEST=UNDECLARED
        # THE MAP IS CONSULTED HERE TOO, AND IT SELECTS NOTHING. The full
        # suite outranks any selection (the fan-out table), so this call can
        # only ever come back a fallback — and it is made anyway, for two
        # reasons a reader of a full run is owed: the sentence names the plant
        # the map has never seen when there is one, and `map=` carries the
        # same value it would on a fast run, so one field shape is parsed
        # rather than two.
        loop_scope__impact
        # THE SAME FIELD SHAPE AS THE FAST BRANCH, so the two are read the same
        # way and neither can be mistaken for the other: `mode=full` already
        # makes this key distinct from every scoped one, and keeping the field
        # list identical means a reader parses one format rather than two.
        LOOP_SCOPE_CANONICAL="mode=full own=- scope=- always=${LOOP_SCOPE_ALWAYS_DIGEST} tests=- seeded=- alwayson=${LOOP_SCOPE_ALWAYS_ON_DIGEST} map=${LOOP_SCOPE_MAP_SHA:--}"
        return 0
    fi

    LOOP_SCOPE_TOUCHED=$(loop_scope__sorted "$touched")

    # THE ONE LEGAL OVERRIDE, and it only widens. Applied to the SEEDS, so a
    # named app brings its own closure with it rather than arriving as an
    # unexplained member of the answer.
    if [ -n "${DJB_LOOP_SCOPE_ALSO:-}" ]; then
        for label in $DJB_LOOP_SCOPE_ALSO; do
            loop_scope__add touched "$label"
        done
        LOOP_SCOPE_TOUCHED=$(loop_scope__sorted "$touched")
        loop_scope__note "DJB_LOOP_SCOPE_ALSO widened the seeds with: ${DJB_LOOP_SCOPE_ALSO}. The override can only ADD — nothing it names can leave the scope."
    fi

    # THE TESTS-ONLY SET IS WHAT SURVIVES THE SUBTRACTION, and the subtraction is
    # the definition: for app `x`, EVERY changed path under `apps/x/` matches
    # `apps/x/tests/**`. One path that does not — a model, a migration, the
    # app-root conftest — and `x` is an ordinary touch with its closure, because
    # a tests-only claim about an app whose CODE also moved is a claim about a
    # change nobody made.
    #
    # COMPUTED AFTER THE OVERRIDE, so DJB_LOOP_SCOPE_ALSO wins WIDER: an app the
    # override seeded is in `touched`, so it drops out here and runs as own. The
    # override could only ever ADD, and this keeps that true.
    for label in $tests_touched; do
        case " $LOOP_SCOPE_TOUCHED " in
        *" $label "*) continue ;;
        esac
        loop_scope__add LOOP_SCOPE_TESTS_ONLY "$label"
    done
    LOOP_SCOPE_TESTS_ONLY=$(loop_scope__sorted "$LOOP_SCOPE_TESTS_ONLY")

    if [ -n "$LOOP_SCOPE_TESTS_ONLY" ]; then
        # ACCOUNTED FOR, NOT WALKED. The tests-only labels take no closure —
        # that is the row — but a label the declarations cannot account for is
        # still a derivation that did not answer, and it must not become a
        # narrowing nobody can explain. The SAME reader answers, and its answer
        # is discarded: one declaration reader, one refusal, no second list.
        loop_scope__closure "$PWD/apps" $LOOP_SCOPE_TESTS_ONLY >/dev/null || {
            gate_refuse "the --loop scope derived a tests-only app the declarations cannot"
            echo "   account for — see above. An unaccountable label is not an empty" >&2
            echo "   one, and a tests-only row is still a narrowing." >&2
            return 2
        }
        # The edited modules are kept only for the apps that are actually
        # tests-only: an app whose code moved runs IN FULL and needs no
        # per-module exemption.
        for path in $LOOP_SCOPE_CHANGED_TESTS; do
            label=${path#apps/}
            label=${label%%/*}
            case " $LOOP_SCOPE_TESTS_ONLY " in
            *" $label "*) kept="${kept}${kept:+ }$path" ;;
            esac
        done
        LOOP_SCOPE_CHANGED_TESTS="$kept"
        loop_scope__note "a cross-app coupling that is not an import and not a test import is not in this selection; the push runs everything"
    else
        LOOP_SCOPE_CHANGED_TESTS=""
    fi

    # THE CENSUS SEEDS, ANNOUNCED. Outside the tests-only branch above, and
    # deliberately: a seed has nothing to do with whether an app changed only
    # its tests — it is about a DECLARATION the active rung moved that a core census
    # reads. It survives every branch of the block above for the same reason.
    if [ -n "$LOOP_SCOPE_SEEDED_TESTS" ]; then
        LOOP_SCOPE_SEEDED_TESTS=$(loop_scope__sorted "$LOOP_SCOPE_SEEDED_TESTS")
        LOOP_SCOPE_SEEDED_BY=$(loop_scope__sorted "$LOOP_SCOPE_SEEDED_BY")
        loop_scope__note "census-seeded by ${LOOP_SCOPE_SEEDED_BY}: ${LOOP_SCOPE_SEEDED_TESTS} — a core census that reads OTHER apps' declarations, which the reverse depends_on closure can never reach (core is everyone's dependency and nobody's dependant). The module is added, never the core app or its organ tests."
    fi

    if [ -n "$LOOP_SCOPE_TOUCHED" ]; then
        # THE ONE SUBSHELL CALLEE IN THIS FILE, AND REVIEW F7'S WHOLE CLASS.
        # `$(...)` is a subshell: `loop_scope__closure` can print, but every
        # assignment it makes dies with it — `gate_refuse`'s global included — and its
        # deepest refusal (the unknown-label one) is written by an embedded
        # Python reader that cannot call a shell function at all. So the child's
        # stderr is captured to a FILE (never into the substitution, which would
        # fold the refusal into the closure being computed), replayed where it
        # would have appeared, and its first `!!` line becomes the cause the
        # banner in scripts/check.sh prints. See scripts/gate_refuse.sh.
        rc=0
        gate_capture closure loop_scope__closure "$PWD/apps" $LOOP_SCOPE_TOUCHED || rc=$?
        if [ "$rc" != "0" ]; then
            # THE CHILD'S CAUSE IS ALREADY CARRIED, and the sentence below stays
            # an ordinary `echo` on purpose: routing it through `gate_refuse` would
            # OVERWRITE the cause `gate_capture` just brought out of the subshell
            # with this file's own "see above" — the pointer rather than the
            # thing pointed at.
            echo "!! the --loop scope could not derive the depends_on closure — see above." >&2
            echo "   An underived closure is not an empty one: narrowing on the strength" >&2
            echo "   of a walk that did not answer would grade the active rung against a suite" >&2
            echo "   that never saw its change." >&2
            return 2
        fi
        LOOP_SCOPE_APPS=$(printf '%s' "$closure" | tr '\n' ' ' | sed 's/ $//')
        for label in $LOOP_SCOPE_APPS; do
            case " $LOOP_SCOPE_TOUCHED " in
            *" $label "*) ;;
            *) loop_scope__add LOOP_SCOPE_WIDENED "$label" ;;
            esac
        done
        LOOP_SCOPE_WIDENED=$(loop_scope__sorted "$LOOP_SCOPE_WIDENED")
    fi

    # `--mine`: THE OWN APPS IN FULL, AND THE CLOSURE SUBTRACTED AGAIN.
    #
    # The walk above still RAN — it is the same walk, with the same refusals, so
    # a rung whose declarations cannot be read is exit 2 under `--mine` exactly
    # as it is under the ordinary `--loop`. What `--mine` drops is the walk's
    # RESULT: the widened apps leave the scope, and what remains is the set the
    # changed files named directly, which run in full (they are `own`).
    #
    # SUBTRACTED HERE RATHER THAN SKIPPED ABOVE, deliberately: a mode that never
    # walked could not tell a closure it chose not to run from a closure it
    # could not derive, and those are a narrowing and a refusal. The cost is one
    # static read of every `apps/*/apps.py`, which is the cheap half.
    #
    # The always-on set is untouched — it is derived at the pytest door, outside
    # every scope, and `--mine` is the smallest scope there is, which is exactly
    # when a cross-app tripwire is worth most.
    if [ -n "${LOOP_MINE:-}" ] && [ -n "$LOOP_SCOPE_APPS" ]; then
        LOOP_SCOPE_APPS="$LOOP_SCOPE_TOUCHED"
        LOOP_SCOPE_WIDENED=""
        loop_scope__note "--mine: the depends_on closure was NOT walked into the scope — [${LOOP_SCOPE_TOUCHED}] run IN FULL and nothing else does; a regression in a DEPENDANT of those apps surfaces at the ordinary --loop, which is the run to make at your last boundary."
    fi

    LOOP_TIER_OWN_APPS="$LOOP_SCOPE_TOUCHED"
    LOOP_SCOPE_NARROW=1
    LOOP_SCOPE_ALWAYS_DIGEST=$(loop_scope__always_digest "apps/conftest.py")
    # THE SECOND ALWAYS-ON SET, AND IT IS A SECOND FIELD RATHER THAN A WIDER
    # FIRST ONE. `always=` is the digest of the pytest door's derivation RULE;
    # `alwayson=` is the digest of the `--loop` always-on leg's INPUTS. Folding
    # them into one value would make `UNDECLARED` — the broken read the ledger
    # refuses to bank — unreachable, because a readable durations file would
    # hash it away.
    LOOP_SCOPE_ALWAYS_ON_DIGEST=$(loop_scope__always_on_digest) ||
        LOOP_SCOPE_ALWAYS_ON_DIGEST=UNDECLARED
    # BOTH LISTS ARE IN THE KEY, because both decide what ran: `own` decides
    # which apps run their organ tests and `scope` decides which apps run at
    # all. A verdict keyed on only one of them would be reused by a run that
    # selected differently.
    #
    # `tests=` IS APPENDED AFTER `always=`, the append precedent this tree
    # already uses for the ledger's own fields: a verdict banked with the
    # tests-only rule never vouches for a run without it, and a reader parsing
    # the old four fields still parses this line.
    #
    # `mode=mine` IS ITS OWN VALUE, AND IT IS A BELT. `check.sh` neither
    # consults nor banks under `--mine`, so nothing reads this string on such a
    # run today; writing `mode=fast` there anyway would leave a `--mine` scope
    # spellable as an ordinary one, and the first line that ever forgets the
    # guard would reuse a closure-less verdict for a closure-walked run. The
    # field makes that impossible by construction rather than by memory.
    local key_mode=fast
    [ -z "${LOOP_MINE:-}" ] || key_mode=mine
    # THE SEED IS IN THE KEY, AND THAT IS NOT DECORATION. The banked verdict is
    # keyed on what the run SELECTED; a tree whose seeds differ selected a
    # different set, so it must not hit a row banked without them — and a
    # verifier's plain `--loop` on the same tree derives the same seeds and
    # therefore the same key, which is the property that makes a hit meaningful.
    # `seeded=` is appended AFTER `tests=`, the append precedent this file
    # already set one field earlier, so an older row simply misses rather than
    # being misread.
    #
    # `alwayson=` IS APPENDED LAST, the same append precedent `tests=` and
    # `seeded=` set before it: an older row simply misses rather than being
    # misread, and every row written from here on names the always-on inputs it
    # was measured with.
    # THE MAP, CONSULTED LAST, because it reads what everything above derived:
    # the changed paths with their shapes, and the census modules the seeds
    # added. It sets no scope and removes no app — it either produces a
    # SELECTION that replaces the narrowing at the pytest door, or a printed
    # sentence saying why this run is the closure scope it was before.
    loop_scope__impact
    if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ]; then
        loop_scope__note "the TEST-IMPACT MAP answered: ${LOOP_SCOPE_IMPACT_TESTS} test(s) selected for ${LOOP_SCOPE_IMPACT_SEEN} changed file(s) it has seen, so the closure above is NOT what runs — the scope flags are dropped and the selection is handed to pytest whole. A test the map attributes elsewhere is the declared hole, bounded by the wave's bank."
    else
        loop_scope__note "the TEST-IMPACT MAP did NOT narrow this run: ${LOOP_SCOPE_IMPACT_FALLBACK}"
    fi
    # `map=` IS APPENDED LAST, the same append precedent every field since
    # `tests=` has taken: an older row simply misses rather than being
    # misread, and the loop key now MOVES WITH THE MAP — a tree measured
    # against one selection can never be vouched for by a verdict banked
    # against another. `bypassed` is its own value for the same reason
    # `mode=mine` is: the valve's wide run must not be handed a narrow row.
    LOOP_SCOPE_CANONICAL="mode=${key_mode} own=${LOOP_SCOPE_TOUCHED:--} scope=${LOOP_SCOPE_APPS:--} always=${LOOP_SCOPE_ALWAYS_DIGEST} tests=${LOOP_SCOPE_TESTS_ONLY:--} seeded=${LOOP_SCOPE_SEEDED_TESTS:--} alwayson=${LOOP_SCOPE_ALWAYS_ON_DIGEST} map=${LOOP_SCOPE_MAP_SHA:--}"

    if [ -n "$LOOP_SCOPE_APPS" ]; then
        # "own app" IS THE HOUSE'S WORD FOR IT and this sentence keeps it. The
        # tier's own drive asserts this banner as text, which is the right thing
        # for a drive to do about an honesty banner — and it is also what
        # catches a rung rewording the rule out from under a reader who learned
        # the old vocabulary.
        if [ -n "${LOOP_MINE:-}" ]; then
            LOOP_TIER_REASON="--mine: the fast tier narrowed to the active rung's OWN app(s) [${LOOP_SCOPE_TOUCHED}], which run IN FULL, with the reverse-transitive depends_on closure NOT walked into the scope — plus the always-on cross-app set"
        else
            LOOP_TIER_REASON="the fast tier NARROWED to the active rung's scope — its own app(s) [${LOOP_SCOPE_TOUCHED}], which run IN FULL, plus the reverse-transitive depends_on closure [${LOOP_SCOPE_WIDENED:--}], which runs its fast tier — plus the always-on cross-app set"
        fi
        if [ -n "$LOOP_SCOPE_TESTS_ONLY" ]; then
            LOOP_TIER_REASON="${LOOP_TIER_REASON} — and [${LOOP_SCOPE_TESTS_ONLY}] changed ONLY tests under apps/<x>/tests/, so they seeded NO closure: their test trees run at the fast tier, the edited modules run whatever tier they are in, and so does every collected module that names one of those test packages"
        fi
    elif [ -n "$LOOP_SCOPE_TESTS_ONLY" ]; then
        # THE LEVER, SAID IN THE BANNER. This is the case the whole row exists
        # for: a rung whose only change under apps/ is a test edit. Today that
        # seeded the closure, and `closure(core)` is every app.
        LOOP_TIER_REASON="the active rung changed only tests under apps/<x>/tests/ [${LOOP_SCOPE_TESTS_ONLY}], so NO closure was walked — those apps' test trees run at the fast tier, the edited modules run whatever tier they are in, every collected module that names one of those test packages runs its fast tier, plus the always-on cross-app set"
    else
        LOOP_TIER_REASON="the active rung changed no file under apps/<x>/ and no shared test infrastructure, so the scope is EMPTY and the always-on cross-app set runs alone"
    fi

    return 0
}

# loop_scope__pytest_args [<counts-dir>]
#
# The pytest flags that narrow a run to the scope `loop_tier_own_apps` just
# derived, WITHOUT the organ tier — one flag per line, so a caller on bash 3.2
# reads them into an array with `while read` and never word-splits a path.
#
# WHY THE TIER IS ABSENT AND THAT IS THE POINT. `--loop` narrows twice: to the
# scope (which apps run at all) and to the FAST tier (which tests inside them
# run). The two narrowings answer different questions, and only the first one is
# about what the change can reach — the second is about what a builder should
# wait for. A run that is grading a whole proposed change rather than a rung in
# progress wants the first and not the second: every test in the scope, organ-
# reaching or not. So this emits `--djb-scope-narrow` and the scope, and no
# `--djb-tier`, whose default is `all` (apps/conftest.py's own option default) —
# and `--djb-own-app` with it, because own-app means only "run this app's organ
# tests anyway", which is already true of every app here.
#
# THE FULL-SUITE CASE EMITS NOTHING, deliberately: when the derivation came back
# `full` (shared test infrastructure moved) there is no scope to narrow to, and
# a caller that appended a `--djb-scope-narrow` with an empty scope would run
# the always-on set alone while believing it ran everything.
#
# AND WHEN THE MAP ANSWERED, THE SCOPE FLAGS ARE NOT EMITTED AT ALL. A
# selection and a scope are two answers to the same question, and the one this
# emits is the narrower: `--djb-impact-select` plus the always-on set pytest
# derives for itself. The three flags that ride on both paths ride for reasons
# the map has no opinion about — `--djb-own-app` (which apps run their organ
# tests, emitted by the caller), `--djb-changed-test` (a module the rung
# edited or a census the declarations seeded) and `--djb-changed` (the
# population test above).
loop_scope__pytest_args() {
    local counts=${1:-} label path
    [ "$LOOP_TIER_MODE" != "full" ] || return 0
    [ -n "$LOOP_SCOPE_NARROW" ] || return 0
    # THE CHANGED FILES THEMSELVES, ON BOTH OF THE ORDINARY LOOP'S PATHS.
    # `--djb-changed` narrows nothing on its own: it is what lets a DECLARED
    # cross-app census with a `population=` clause sit out a run whose changed
    # files are all outside it. A selecting run and a fallback run both owe it,
    # because a census population is a declaration about files and not a
    # projection of one measurement.
    #
    # BEHIND THE SAME ONE SWITCH AS THE MAP, deliberately: `--pr` and `--mine`
    # emit exactly the flags they emitted before this section existed, so
    # the ordinary `--loop` is the only belt whose selection moved, and it is
    # the only one that was measured.
    if [ -n "${LOOP_IMPACT:-}" ]; then
        for path in $LOOP_SCOPE_CHANGED_FILES; do
            printf -- '--djb-changed=%s\n' "$path"
        done
    fi
    if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ]; then
        # THE SELECTION IS THE WHOLE QUESTION. No `--djb-scope-narrow` and no
        # `--djb-scope=` beside it: those would widen back exactly what the map
        # was asked to narrow, and a caller that handed over a list of nodeids
        # did not ask for the closure as well. The own-app and edited-module
        # flags below still ride, because they answer the OTHER question — the
        # organ tier — which the map has no opinion about.
        printf -- '--djb-impact-select=%s\n' "$LOOP_SCOPE_IMPACT_SELECT"
        for path in $LOOP_SCOPE_CHANGED_TESTS; do
            printf -- '--djb-changed-test=%s\n' "$path"
        done
        for path in $LOOP_SCOPE_SEEDED_TESTS; do
            printf -- '--djb-changed-test=%s\n' "$path"
        done
        [ -z "$counts" ] || printf -- '--djb-scope-counts=%s\n' "$counts"
        return 0
    fi
    printf '%s\n' "--djb-scope-narrow"
    for label in $LOOP_SCOPE_APPS; do
        printf -- '--djb-scope=%s\n' "$label"
    done
    for label in $LOOP_SCOPE_TESTS_ONLY; do
        printf -- '--djb-tests-only=%s\n' "$label"
    done
    for path in $LOOP_SCOPE_CHANGED_TESTS; do
        printf -- '--djb-changed-test=%s\n' "$path"
    done
    # THE SAME FLAG THE EDITED TEST MODULES USE, and that is the point rather
    # than a shortcut: `--djb-changed-test=<module>` already means exactly "keep
    # this ONE module in the selection and do not deselect it for the organ
    # tier" (`apps/conftest.py`, `is_changed_test`). A second flag would be a
    # second answer to one question. What differs is where the path came from —
    # the rung edited that one, and a declaration seeded this one.
    for path in $LOOP_SCOPE_SEEDED_TESTS; do
        printf -- '--djb-changed-test=%s\n' "$path"
    done
    [ -z "$counts" ] || printf -- '--djb-scope-counts=%s\n' "$counts"
}

# loop_scope__prerun_absence <collectors that reported> <collectors expected>
#
# THE BANNER'S ABSENCE, NAMED. The pre-run scope banner rides
# `pytest_xdist_node_collection_finished`, which the controller calls once per
# node and which prints only when EVERY node has reported
# (apps/conftest.py). A worker that dies during collection therefore leaves the
# banner silently absent — and silence reads exactly like a banner that was
# never wired, which is the one thing a reader cannot tell apart afterwards.
#
# IT IS A PRINTED ABSENCE, NOT A VERDICT, and the distinction is the whole
# design: this printer decides nothing. What decides is the RECONCILIATION that
# follows it — a collector disagreement is exit 2, as it always was, and a
# collector SHORTFALL is now exit 2 too (`loop_counts_refuse_if_short`), with no
# verdict banked.
#
# THAT SECOND HALF REPLACES A SENTENCE THAT WAS MEASURED FALSE. This paragraph
# used to say the dead worker was already the failure and already had its own
# exit. It did not: a collector that dies once xdist's restart budget is spent
# leaves pytest able to exit 0 with `no tests ran` and one counts file where two
# were asked for — a GREEN run that ran nothing, whose only tell was this line
# in the middle of a passing transcript. The shortfall refusal is the exit the
# sentence assumed existed, and it exists now; this line's job is to say WHICH
# collectors were missing, next to it.
#
# Returns 0 always, and prints nothing when every expected collector reported.
loop_scope__prerun_absence() {
    local reported=${1:-0} expected=${2:-0}
    case "$reported" in '' | *[!0-9]*) reported=0 ;; esac
    case "$expected" in '' | *[!0-9]*) expected=0 ;; esac
    [ "$expected" -gt 0 ] || return 0
    [ "$reported" -lt "$expected" ] || return 0
    echo "  the pre-run banner did not fire (${reported} of ${expected} collectors reported)"
    echo "  It prints only once every collector has reported its counts, so a worker"
    echo "  that died during collection takes it with it. The counts below are the"
    echo "  survivors', and this line is an absence NAMED, not a verdict of its own —"
    echo "  the verdict for a short collection is the shortfall refusal's"
    echo "  (loop_counts_refuse_if_short, exit 2, no verdict banked), never pytest's."
    return 0
}
