#!/usr/bin/env bash
# The `--loop` pytest tier's OWN-APP derivation.
# Sourced by scripts/check.sh and by scripts/tests/test_loop_tier.sh.
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
# WHAT IT DECIDES. `--loop` runs the FAST TIER plus THE RUNG'S OWN APP IN FULL.
# The fast/slow split is derived inside pytest, from organ-fixture reach and
# nothing else (`apps/conftest.py`); this file answers the other half — which
# apps are the active rung's, so that a builder working in `apps/exports` still
# pays for its real-MinIO tests in the rung rather than discovering them at push.
#
# IT REUSES THE SECRET SCAN'S DERIVATION AND DOES NOT GROW A SECOND ONE.
# `secrets_scan_changed_files` already answers "what did the active rung
# change" — merge-base with the local `refs/heads/main`, plus everything
# staged and uncommitted, with its edge cases (an unborn HEAD, no local main,
# on main itself, a linked worktree's merge-base) argued and DRIVEN in
# `scripts/tests/test_secrets_scan.sh`. Two derivations of "the active rung's
# files" would be two things to keep in step, and the second one would drift
# first. So this is a MAPPING over that set, not a derivation beside it.
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
# for that case is the fast tier alone, and `--loop` PRINTS it every run — a
# silent tier choice is an unfalsifiable one.
#
# ---------------------------------------------------------------------------
# THE RULE SPLITS AT "NO OWN APP" (a follow-up ruling that overrules this
# file's first answer). "No own app" was read as one case and it
# is two, and the first version of this file took the cheap one for both:
#
#   * A rung that changed nothing under `apps/` at all — `scripts/`, `quality/`,
#     a skill, a document. Blast radius on the suite: none. FAST TIER, alone.
#     Unchanged.
#   * A rung that changed SHARED TEST INFRASTRUCTURE — a file that belongs to no
#     app but that every app's tests stand on. Blast radius: the whole suite, BY
#     CONSTRUCTION. That is the change class where loop-time discovery is worth
#     most, and it is rare enough that the full suite costs almost nothing
#     across a cycle. FULL SUITE in `--loop`.
#
# WHAT COUNTS AS SHARED TEST INFRASTRUCTURE, enumerated, because a rule nobody
# can read is a rule nobody can argue with. Four members, three arguments:
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
#      `apps/test_gate_liveness.py`. Not a fixture, and the sharpest argument of
#      the four: both name the real-Temporal entry point, so both derive into
#      the SLOW tier, and under the old rule a rung editing one of them had its
#      own changed test DESELECTED and never ran it in the rung at all.
#   3. `scripts/tests/**` — the gate's own drives and their preamble. Their
#      pytest blast radius is NIL and that is said out loud rather than papered
#      over: no shell drive can change what a Python test does. They are in for
#      the other half of the ruling's principle — a rung that changes the
#      machinery deciding whether things pass should not be graded by a narrowed
#      run of that machinery. The cost is one full `--loop` on a rung that
#      changes a drive, which is rarer than a conftest edit.
#   4. THIS FILE. The reflexive case: a rung that changes how the tier decides
#      must not be graded by the tier it changed.
#
# WHAT IS DELIBERATELY NOT IN IT: `pyproject.toml`, which carries pytest's ini
# options and therefore has a real whole-suite blast radius. It is left out
# because "configuration that could affect tests" has no edge — settings,
# compose, the lockfile and the gate itself all qualify on that reading — and a
# class with no edge stops being derivable and becomes a list somebody
# maintains. The four above are shapes; `pyproject.toml` would be the first
# entry of a list. Named here rather than left to be discovered.
#
# THE SHARED HALF OUTRANKS THE APP HALF. A rung that touched both has not made
# the shared change smaller by touching an app beside it.
# ---------------------------------------------------------------------------

#: `fast` (the derived fast tier, plus any own apps) or `full` (every test).
LOOP_TIER_MODE="fast"

#: Space-separated app labels, set by loop_tier_own_apps. Legitimately empty,
#: and meaningless when the mode is `full` — there is nothing left to promote.
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
    # (4) this file.
    scripts/loop_tier.sh) return 0 ;;
    esac
    return 1
}

# loop_tier_own_apps
#
# Exit: 0 the set was derived (it may legitimately be EMPTY) · 2 git could not
# answer, which is could-not-look and outranks a pass everywhere in the gate.
loop_tier_own_apps() {
    local list path label seen
    LOOP_TIER_MODE="fast"
    LOOP_TIER_OWN_APPS=""
    LOOP_TIER_SHARED_HITS=""
    LOOP_TIER_REASON=""
    LOOP_TIER_BASIS=""

    list=$(mktemp "${TMPDIR:-/tmp}/djb-loop-tier.XXXXXX") || return 2
    if ! secrets_scan_changed_files "$list"; then
        rm -f "$list"
        return 2
    fi
    LOOP_TIER_BASIS="$SECRETS_SCAN_BASIS"

    seen=" "
    while IFS= read -r -d '' path; do
        # SHARED FIRST. A path can be both an app's and shared only if the
        # enumeration is wrong; asking this first means the answer never depends
        # on which arm happened to be written above the other.
        if loop_tier__is_shared_test_infra "$path"; then
            case " $LOOP_TIER_SHARED_HITS " in
            *" $path "*) ;;
            *) LOOP_TIER_SHARED_HITS="${LOOP_TIER_SHARED_HITS}${LOOP_TIER_SHARED_HITS:+ }$path" ;;
            esac
            continue
        fi
        case "$path" in
        apps/*/*)
            label=${path#apps/}
            label=${label%%/*}
            ;;
        *) continue ;;
        esac
        [ -n "$label" ] || continue
        case "$seen" in
        *" $label "*) continue ;;
        esac
        seen="$seen$label "
        LOOP_TIER_OWN_APPS="${LOOP_TIER_OWN_APPS}${LOOP_TIER_OWN_APPS:+ }$label"
    done <"$list"

    rm -f "$list"

    # The three branches, each with the sentence the leg prints for it. Written
    # here and not at the call site so the rule and its declaration cannot drift
    # apart: whoever changes the rule is holding its wording.
    if [ -n "$LOOP_TIER_SHARED_HITS" ]; then
        # The own-app list is discarded rather than reported: under `full` there
        # is nothing left to promote, and printing it would invite the reader to
        # think it still decided something.
        LOOP_TIER_MODE="full"
        LOOP_TIER_OWN_APPS=""
        LOOP_TIER_REASON="the active rung changed shared test infrastructure — a file no app owns, which every app's tests stand on — so --loop runs the FULL suite, not the fast tier"
    elif [ -n "$LOOP_TIER_OWN_APPS" ]; then
        LOOP_TIER_MODE="fast"
        LOOP_TIER_REASON="the fast tier, plus the active rung's own app(s) in full: ${LOOP_TIER_OWN_APPS}"
    else
        LOOP_TIER_MODE="fast"
        LOOP_TIER_REASON="the active rung changed no file under apps/<x>/ and no shared test infrastructure, so the fast tier runs alone"
    fi

    return 0
}
