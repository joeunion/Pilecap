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
# more. It is printed in the banner whenever it is set.
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
#                       of `scripts/`.
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

#: The digest of the always-on derivation's DECLARATION — the sentinel-delimited
#: block in `apps/conftest.py`. Part of the canonical scope, because changing
#: which tests are unconditional changes what a green loop meant.
LOOP_SCOPE_ALWAYS_DIGEST=""

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
    printf '%s' "$block" | shasum -a 256 | awk '{print $1}'
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
    LOOP_SCOPE_ALWAYS_DIGEST=""

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
        # THE SAME FIELD SHAPE AS THE FAST BRANCH, so the two are read the same
        # way and neither can be mistaken for the other: `mode=full` already
        # makes this key distinct from every scoped one, and keeping the field
        # list identical means a reader parses one format rather than two.
        LOOP_SCOPE_CANONICAL="mode=full own=- scope=- always=${LOOP_SCOPE_ALWAYS_DIGEST} tests=-"
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
    LOOP_SCOPE_CANONICAL="mode=${key_mode} own=${LOOP_SCOPE_TOUCHED:--} scope=${LOOP_SCOPE_APPS:--} always=${LOOP_SCOPE_ALWAYS_DIGEST} tests=${LOOP_SCOPE_TESTS_ONLY:--}"

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
loop_scope__pytest_args() {
    local counts=${1:-} label path
    [ "$LOOP_TIER_MODE" != "full" ] || return 0
    [ -n "$LOOP_SCOPE_NARROW" ] || return 0
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
