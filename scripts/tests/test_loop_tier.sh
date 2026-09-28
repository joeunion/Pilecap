#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. Measured on this tree:
#
#   zsh scripts/queue_cited.sh   exit 2 blaming the TREE ("this is not a
#                                checkout root") for zsh's word-splitting
#   zsh scripts/kill_mine.sh     an ordinary-looking census of nothing
#   sh  scripts/sweep.sh         "lifecycle.sh: line 152: syntax error"
#
# A wrong shell here does not crash. It ANSWERS, and the answer looks like the
# tree's fault.
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
#
# A SOURCED library must never carry this. There the interpreter is the
# caller's ON PURPOSE and an `exit` would kill the caller's shell — the
# argument is scripts/db.sh's, at scripts/db.sh:50-57, and it is why db.sh is
# the one executable in this tree deliberately without a belt.
[ -n "${BASH_VERSION:-}" ] || {
    echo "${0##*/}: must run under bash — not sh, not zsh. Try \`bash ${0}\`." >&2
    exit 2
}
case ":${SHELLOPTS:-}:" in
*:posix:*)
    echo "${0##*/}: bash is in POSIX mode — which is what \`sh ${0}\` does on a" >&2
    echo "  machine whose /bin/sh is bash. Try \`bash ${0}\`." >&2
    exit 2
    ;;
esac
# drives: apps/ config/ deploy/tests/test_stage.sh perf/conftest.py quality/ scripts/check.sh scripts/db.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/kill_mine.sh scripts/loop_tier.sh scripts/queue_cited.sh scripts/secrets_scan.sh scripts/sweep.sh scripts/tests
# The drive for the `--loop` pytest TIER — the derived slow tier in
# `apps/conftest.py` and the own-app mapping in `scripts/loop_tier.sh`.
#
#   ./scripts/tests/test_loop_tier.sh          run every case
#   ./scripts/tests/test_loop_tier.sh --list   name them and stop
#
# WHY IT EXISTS. The per-rung gate no longer runs the whole suite: it runs the
# fast tier plus the active rung's own app, and the slow tier — every test that
# reaches a real organ — waits for the push. That narrowing is exactly as
# defensible as its derivation, and every failure mode of the derivation is
# SILENT:
#
#   * a private pytest attribute renamed, so no fixture closure resolves and
#     the tier deselects nothing (a slow `--loop` nobody diagnoses) or
#     everything (a fast green that vouches for nothing);
#   * an `@organ(...)` decorator lost in a merge, so a whole organ's tests
#     quietly stop being run in the rung AND stop being counted as slow;
#   * a module-source read that started failing, same shape;
#   * the own-app mapping stopping at the wrong path component, so a builder
#     working in `apps/exports` stops paying for its own organ tests.
#
# None of those redden anything. So each rule is driven in BOTH directions —
# what must be in the slow tier and what must not — the leg's honesty banners
# are asserted as text, and THE CENSUS TOOTH IS A PLANT: a real test file that
# requests a real organ fixture is written into this tree, and the derivation
# must put it in the slow tier WITH NO LIST EDIT ANYWHERE. That is the property
# the whole design rests on, and it is the one a hand-marked list would fail.
#
# IT PLANTS IN THIS TREE and removes what it planted, like its sibling
# `test_secrets_scan.sh` and for the same reason: the thing being proven is that
# the REAL derivation, over the REAL conftests, reaches a file nobody told it
# about. A scratch repository would prove that a copy of the derivation reaches
# a copy of the tree.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE DESELECTED TESTS STILL PASS. This drive collects; it never
#     runs a test. The full gate at push runs all of them, twice, and that is
#     the only thing that ever proved them.
#   * THE COST CLAIM. That `--loop` is faster is measured in the rung report and
#     re-measured independently; nothing here asserts a second.
#   * WHETHER AN ORGAN FIXTURE WAS DECLARED AT ALL. If somebody adds a fixture
#     that opens a real socket and does not decorate it, its tests run in the
#     fast tier and this drive is happy. The floors catch a derivation that
#     stopped seeing a KIND; nothing catches a kind nobody declared. That is the
#     residual risk of the whole design and it is named here rather than left
#     for a reader to discover.
#   * THE REFUSAL'S TEXT UNDER `-n auto`. The floors raise inside the xdist
#     WORKERS, and xdist reports a worker that died during collection as an
#     INTERNALERROR with the worker's own message dropped — MEASURED, by
#     severing `_fixtureinfo` and running the real `--loop`: the gate
#     exited 2, correctly, and the sentence explaining why was nowhere in the
#     log. THE EXIT STATUS IS WHAT IS PROVEN, here and in the gate; the
#     sentence is asserted in the SERIAL collection this drive runs, and
#     check.sh's could-not-look branch tells a reader the serial command that
#     shows it. A tier whose refusal is unreadable is a poor refusal; a tier
#     whose refusal is silent would be no refusal at all, and it is not that.
#   * THE FULL GATE'S OWN PYTEST LEGS. `case_the_full_gate_leg_carries_no_tier`
#     reads check.sh as TEXT to prove the two push-side passes take no tier
#     flag; it cannot run the real gate from inside the gate's own selftest leg
#     (the per-checkout lock — see `test_db_pin.sh`'s identical note).
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
# An inherited absolute `GIT_DIR` overrides `-C`, and the own-app cases
# below build throwaway repositories exactly the way the drive that escaped did.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_loop_tier: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death hands the
# EXIT trap a status of 0, so a drive that dies halfway reads as a PASS — which
# is exactly what this file did on its first red run of the follow-up ruling,
# before the guard existed. Every case below is worthless without it.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_loop_tier: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_loop_tier.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
command -v uv >/dev/null 2>&1 || cannot_look "no uv on PATH — the derivation lives inside pytest"
[ -f apps/conftest.py ] || cannot_look "apps/conftest.py is not in this tree — the derivation is gone"
[ -f scripts/loop_tier.sh ] || cannot_look "scripts/loop_tier.sh is not in this tree"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the wiring cannot be read"

ROOT="$PWD"

# The real files, sourced. The own-app mapping calls the secret scan's
# derivation, so both come in, in the order check.sh sources them.
# shellcheck source=scripts/secrets_scan.sh
. scripts/secrets_scan.sh
# shellcheck source=scripts/loop_tier.sh
. scripts/loop_tier.sh
command -v loop_tier_own_apps >/dev/null 2>&1 ||
    cannot_look "scripts/loop_tier.sh defines no loop_tier_own_apps — the mapping is gone"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-loop-tier-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

CURRENT=""
RC=0
OUT=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -25
    fi
    FAILED=$((FAILED + 1))
}
exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}
says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

# --- the plants ---------------------------------------------------------------
#
# Three real test files in three real apps, written into THIS tree and removed
# on every exit path. Nothing runs them: every derivation below is
# `--collect-only`.
PLANT_ORGAN="apps/files/tests/test_djb_loop_tier_plant.py"
PLANT_TEMPORAL="apps/example/tests/test_djb_loop_tier_plant.py"
PLANT_PLAIN="apps/usage/tests/test_djb_loop_tier_plant.py"
#: The DECLARED cross-app census plant — a module in an app no scope below will
#: contain, which survives every scope only because it says so itself.
PLANT_CENSUS="apps/files/tests/test_djb_loop_tier_census_plant.py"

remove_plants() {
    rm -f "${ROOT}/${PLANT_ORGAN}" "${ROOT}/${PLANT_TEMPORAL}" "${ROOT}/${PLANT_PLAIN}" \
        "${ROOT}/${PLANT_CENSUS}"
}
drive_at_exit 'remove_plants'
remove_plants

plant_them() {
    # A test that REACHES the MinIO organ, through the ordinary fixture request
    # and nothing else. No marker, no list, no registration.
    cat >"${ROOT}/${PLANT_ORGAN}" <<'PLANT'
"""Planted by scripts/tests/test_loop_tier.sh. Removed by it. Never run."""


def test_a_planted_test_that_reaches_the_minio_organ(bucket: str) -> None:
    assert bucket
PLANT
    # A test whose MODULE names the real-Temporal entry point, which is how this
    # tree opts a module into a real server (there is no fixture to reach).
    {
        echo '"""Planted by scripts/tests/test_loop_tier.sh. Removed by it. Never run."""'
        echo
        # Assembled rather than written whole: a drive that spelled the entry
        # point in one piece would put the symbol into ITS OWN source, and this
        # file is read by nothing that would care today — but the class (a guard
        # counting a marker it finds in prose) has bitten this repository before.
        echo "from temporalio.testing import Workflow${TEMPORAL_SUFFIX}"
        echo
        echo
        echo "def test_a_planted_test_whose_module_names_the_temporal_entry_point() -> None:"
        echo "    assert Workflow${TEMPORAL_SUFFIX} is not None"
    } >"${ROOT}/${PLANT_TEMPORAL}"
    # A test that reaches nothing at all.
    cat >"${ROOT}/${PLANT_PLAIN}" <<'PLANT'
"""Planted by scripts/tests/test_loop_tier.sh. Removed by it. Never run."""


def test_a_planted_test_that_reaches_no_organ() -> None:
    assert True
PLANT
}
TEMPORAL_SUFFIX="Environment"
#: The walk token the declared-census plant stands on, assembled for the same
#: reason the Temporal entry point above is: a drive that spelled it whole would
#: put a population token into its own source.
WALK_SUFFIX=".rglob("

# --- the derivation runs ------------------------------------------------------
#
# `--collect-only` with the manifest: the classification of every collected
# test, one line each, with no test executed and no database touched.
MANIFEST=""
derive() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/derive${N}.log"
    MANIFEST="${WORK}/manifest${N}.tsv"
    RC=0
    (
        cd "$ROOT" &&
            uv run pytest --collect-only -q -p no:randomly \
                --djb-tier-manifest="$MANIFEST" "$@"
    ) >"$OUT" 2>&1 || RC=$?
}

tier_of() {
    # `<tier>\t<organs>\t<nodeid>` — the nodeid is the third field and the only
    # one with a `::` in it, so an exact match on the whole line's tail is what
    # is asked for rather than a substring anywhere.
    awk -F'\t' -v want="$1" '$3 == want {print $1; found=1} END {if (!found) print "(absent)"}' \
        "$MANIFEST"
}
organs_of() {
    awk -F'\t' -v want="$1" '$3 == want {print $2; found=1} END {if (!found) print "(absent)"}' \
        "$MANIFEST"
}
is() {
    local got="$1" want="$2" what="$3"
    if [ "$got" = "$want" ]; then
        ok "${what} is ${want}"
    else
        bad "${what}: wanted '${want}', got '${got}'"
    fi
}

# --- the cases: the derived slow tier -----------------------------------------

case_every_declared_organ_kind_is_derived_on_this_tree() {
    # THE FLOOR, PROVEN LIVE. Not "the code contains floors" — the real tree,
    # collected, derives at least one test for each kind. A derivation that
    # stopped seeing a kind is the failure this whole file exists for.
    derive "the baseline derivation on this tree"
    exits 0
    local kind n
    for kind in minio meili temporal; do
        n=$(awk -F'\t' -v k="$kind" '$1 == "slow" && $2 ~ k {c++} END {print c + 0}' "$MANIFEST")
        if [ "$n" -ge 1 ]; then
            ok "organ '${kind}' derived on ${n} test(s)"
        else
            bad "organ '${kind}' derived on NO test — the derivation has stopped seeing a kind"
        fi
    done
    n=$(awk -F'\t' '$1 == "fast" {c++} END {print c + 0}' "$MANIFEST")
    if [ "$n" -ge 1 ]; then
        ok "the fast tier is not empty (${n} tests)"
    else
        bad "the fast tier is EMPTY — every test derived as organ-reaching"
    fi
}

case_a_planted_organ_fixture_test_joins_the_slow_tier_with_no_list_edit() {
    # THE CENSUS TOOTH. A file nothing has ever heard of asks for `bucket`, and
    # the slow-tier population grows by exactly that test. Nothing was marked,
    # nothing was listed, no other file changed.
    plant_them
    derive "a planted organ-fixture test"
    exits 0
    is "$(tier_of "${PLANT_ORGAN}::test_a_planted_test_that_reaches_the_minio_organ")" \
        "slow" "the planted MinIO test's tier"
    is "$(organs_of "${PLANT_ORGAN}::test_a_planted_test_that_reaches_the_minio_organ")" \
        "minio" "the planted MinIO test's derived organ"
}

case_a_planted_module_naming_the_temporal_entry_point_joins_the_slow_tier() {
    # The second derivation basis, driven on its own: no fixture is requested
    # here at all, and the module still joins.
    is "$(tier_of "${PLANT_TEMPORAL}::test_a_planted_test_whose_module_names_the_temporal_entry_point")" \
        "slow" "the planted Temporal module's tier"
    is "$(organs_of "${PLANT_TEMPORAL}::test_a_planted_test_whose_module_names_the_temporal_entry_point")" \
        "temporal" "the planted Temporal module's derived organ"
}

case_a_planted_test_reaching_nothing_stays_fast() {
    # The other direction, and it is not decoration: a derivation that answered
    # "slow" for everything would pass every case above.
    is "$(tier_of "${PLANT_PLAIN}::test_a_planted_test_that_reaches_no_organ")" \
        "fast" "the planted plain test's tier"
    is "$(organs_of "${PLANT_PLAIN}::test_a_planted_test_that_reaches_no_organ")" \
        "-" "the planted plain test's derived organs"
}

case_the_plants_leave_when_they_are_removed() {
    # A population that only ever grows is a list with extra steps.
    remove_plants
    derive "the plants removed"
    exits 0
    is "$(tier_of "${PLANT_ORGAN}::test_a_planted_test_that_reaches_the_minio_organ")" \
        "(absent)" "the removed MinIO plant"
    is "$(tier_of "${PLANT_TEMPORAL}::test_a_planted_test_whose_module_names_the_temporal_entry_point")" \
        "(absent)" "the removed Temporal plant"
}

case_the_fast_tier_deselects_the_slow_one_and_says_so() {
    CURRENT="the fast tier deselects and announces"
    N=$((N + 1))
    OUT="${WORK}/fast${N}.log"
    RC=0
    # NOT `-q` here, unlike every other derivation run in this file, and the
    # reason is the assertion two lines down: `-q` suppresses pytest's SESSION
    # HEADER, which is where the declaration that survives `-n auto` lives. A
    # case that asserted the banner under `-q` would be asserting the half the
    # gate never prints.
    (cd "$ROOT" && uv run pytest --collect-only -p no:randomly --djb-tier=fast) \
        >"$OUT" 2>&1 || RC=$?
    exits 0
    says "djb tier: FAST"
    says "organ-reaching test(s) deselected"
    says "deselected"
    # The session HEADER carries the declaration too, and that copy is the one
    # that survives `-n auto`: under xdist the workers collect and the
    # controller only compares their lists, so the collection-finish line never
    # reaches the terminal. Measured, not assumed — and asserted here so the
    # day it stops being true is a red case rather than a quiet loss.
    says "are DESELECTED"
    # The rule for a rung with no own app is DECLARED and PRINTED, not chosen in
    # silence. This drive passes no --djb-own-app, which is that case.
    says "NO own app"
    says "the FULL gate at push runs every one of them"
}

case_an_own_app_keeps_its_own_organ_tests_in_the_rung() {
    # The promotion, driven in both directions on ONE planted test.
    # THE WHOLE SUITE IS COLLECTED, not just the planted file, and that is not
    # an accident of convenience: the organ floors are asserted over the WHOLE
    # collection, so `--djb-tier=fast` over one file legitimately refuses (see
    # `case_an_unmet_floor_refuses…`, which arranges exactly that). `--loop`
    # always collects everything, which is the only shape the tier is for.
    plant_them
    CURRENT="an own app keeps its organ tests"
    N=$((N + 1))
    OUT="${WORK}/own${N}.log"
    RC=0
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly \
        --djb-tier=fast --djb-own-app=files) >"$OUT" 2>&1 || RC=$?
    exits 0
    if grep -q "test_a_planted_test_that_reaches_the_minio_organ" "$OUT"; then
        ok "the planted MinIO test is COLLECTED when its app is the rung's own"
    else
        bad "the planted MinIO test was deselected even though --djb-own-app=files was given"
    fi

    N=$((N + 1))
    OUT="${WORK}/own${N}.log"
    RC=0
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly \
        --djb-tier=fast --djb-own-app=exports) >"$OUT" 2>&1 || RC=$?
    exits 0
    if grep -q "test_a_planted_test_that_reaches_the_minio_organ" "$OUT"; then
        bad "the planted MinIO test survived --djb-own-app=exports — the promotion is not per app"
    else
        ok "another app's promotion does NOT keep it"
    fi
    remove_plants
}

case_an_unmet_floor_refuses_rather_than_running_a_tier_it_cannot_vouch_for() {
    # THE BLINDING. Collect a subtree that reaches no organ at all: the floors
    # go unmet, and the honest answer is a refusal, not a very fast pass.
    # pytest's usage-error exit is 4, and check.sh maps 3/4/5 to could-not-look.
    CURRENT="an unmet organ floor"
    N=$((N + 1))
    OUT="${WORK}/floor${N}.log"
    RC=0
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly \
        --djb-tier=fast apps/usage) >"$OUT" 2>&1 || RC=$?
    exits 4
    says "organ derivation is not answering"
    says "Nothing was deselected"
}

case_the_default_tier_touches_nothing() {
    # The full gate's two passes take this path. A tier that quietly deselected
    # something here would make the recorded verdict vouch for less than it says
    # it does.
    CURRENT="the default tier"
    N=$((N + 1))
    OUT="${WORK}/default${N}.log"
    RC=0
    (cd "$ROOT" && uv run pytest --collect-only -q -p no:randomly) >"$OUT" 2>&1 || RC=$?
    exits 0
    if grep -q "deselected" "$OUT"; then
        bad "the DEFAULT collection deselected something — the full gate would run less than it claims"
    else
        ok "nothing is deselected by default"
    fi
    if grep -q "djb tier" "$OUT"; then
        bad "the default run prints a tier banner — it ran the tier code it must not"
    else
        ok "no tier banner on a default run"
    fi
}

# --- the cases: the own-app mapping -------------------------------------------

REPO=""
fresh_checkout() {
    N=$((N + 1))
    REPO="${WORK}/checkout${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "loop tier drive"
    mkdir -p "$REPO/apps/core" "$REPO/apps/exports/tests" "$REPO/apps/comms" \
        "$REPO/scripts/tests" "$REPO/perf"
    echo "base" >"$REPO/README"
    echo "x = 1" >"$REPO/apps/core/models.py"
    echo "y = 0" >"$REPO/apps/exports/services.py"
    # EVERY FIXTURE APP DECLARES ITSELF, because the own-app derivation now
    # ACCOUNTS FOR the labels it derives: a path under `apps/<x>/` whose
    # `apps.py` declares no `AppConfig` is exit 2 naming that file, not a
    # silently narrowed rung (`loop_tier.sh:449-453`). Before the closure
    # landed, a bare directory was enough for these cases; it is not any more,
    # and the refusal is the correct half of that pair — a label the
    # declarations cannot account for is a walk that did not answer. No
    # `depends_on` on any of them: these cases pin the OWN-app mapping, so the
    # closure is deliberately the identity here and the fan-out is
    # `test_loop_scope.sh`'s subject. `comms` is created in the base commit for
    # the untracked-file case to add a file INTO — its own `apps.py` is
    # committed and unchanged there, so the "derives nothing until it is
    # staged" half still reads an empty set.
    for one in core exports comms; do
        printf 'from django.apps import AppConfig\n\n\nclass %sConfig(AppConfig):\n    name = "apps.%s"\n' \
            "$one" "$one" >"$REPO/apps/$one/apps.py"
    done
    # THE SHARED-INFRA FILES EXIST IN THE BASE COMMIT, and that is the point
    # rather than setup noise: on main every one of these is a tracked file, so
    # a rung TOUCHING one is a modification. Creating them fresh inside a case
    # would make them untracked, and an untracked never-staged file is invisible
    # to the changed-file set this maps over — which is exactly what the first run of
    # these cases proved, by failing every positive assertion at once. A case
    # that arranges its subject wrongly and asserts an empty result is a case
    # that passes for the wrong reason forever.
    echo "# shared fixtures" >"$REPO/apps/conftest.py"
    echo "# root fixtures" >"$REPO/conftest.py"
    echo "# perf fixtures" >"$REPO/perf/conftest.py"
    echo "def test_guard(): pass" >"$REPO/apps/test_guard.py"
    echo "# app fixtures" >"$REPO/apps/exports/tests/conftest.py"
    echo "echo drive" >"$REPO/scripts/tests/test_thing.sh"
    echo "# tier" >"$REPO/scripts/loop_tier.sh"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
}

own_apps_in() {
    local dir="$1" here
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/own-apps${N}.log"
    here="$PWD"
    cd "$dir"
    RC=0
    loop_tier_own_apps >"$OUT" 2>&1 || RC=$?
    cd "$here"
}

# The tier REASON is what the leg prints, so it is asserted as text like every
# other honesty banner in this repository's drives: a rule chosen silently is an
# unfalsifiable one, and a rule printed wrong is worse than one printed short.
reason_says() {
    case "$LOOP_TIER_REASON" in
    *"$1"*) ok "the printed reason says \"$1\"" ;;
    *) bad "the printed reason does not say \"$1\" — it says '${LOOP_TIER_REASON}'" ;;
    esac
}

case_a_change_under_an_app_derives_that_app() {
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "x = 2" >"$REPO/apps/core/models.py"
    own_apps_in "$REPO" "an uncommitted change in apps/core"
    exits 0
    is "$LOOP_TIER_OWN_APPS" "core" "the derived own app"
    if [ -n "$LOOP_TIER_BASIS" ]; then
        ok "the basis sentence is set"
    else
        bad "the basis sentence is empty — the leg would print nothing to falsify"
    fi
}

case_two_apps_both_derive() {
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "x = 2" >"$REPO/apps/core/models.py"
    echo "y = 1" >"$REPO/apps/exports/services.py"
    own_apps_in "$REPO" "changes in two apps"
    exits 0
    case " $LOOP_TIER_OWN_APPS " in
    *" core "*) ok "core derived" ;;
    *) bad "core missing from '${LOOP_TIER_OWN_APPS}'" ;;
    esac
    case " $LOOP_TIER_OWN_APPS " in
    *" exports "*) ok "exports derived" ;;
    *) bad "exports missing from '${LOOP_TIER_OWN_APPS}'" ;;
    esac
}

case_an_untracked_new_file_derives_nothing_until_it_is_staged() {
    # THE INHERITED PROPERTY, pinned in both directions rather than left to be
    # discovered. `secrets_scan_changed_files` reads git's diffs, and an
    # untracked never-staged file is in none of them — the same blind spot the
    # push-side scan has over `git ls-files`, inherited on purpose because this
    # is a mapping over that set and not a second derivation of it. The moment
    # the file is STAGED it is the active rung's, and the app is derived.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    mkdir -p "$REPO/apps/comms"
    echo "n = 1" >"$REPO/apps/comms/services.py"
    own_apps_in "$REPO" "a brand new file nobody has staged"
    exits 0
    is "$LOOP_TIER_OWN_APPS" "" "the derived own app set"

    git -C "$REPO" add apps/comms/services.py
    own_apps_in "$REPO" "the same file, staged"
    exits 0
    is "$LOOP_TIER_OWN_APPS" "comms" "the derived own app"
}

case_a_committed_change_on_a_branch_derives_too() {
    # The other half of the changed-file set: what the active rung COMMITTED
    # since the merge-base, not only what is still uncommitted.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "z = 1" >"$REPO/apps/exports/models.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "the rung"
    own_apps_in "$REPO" "a committed change on a branch"
    exits 0
    is "$LOOP_TIER_OWN_APPS" "exports" "the derived own app"
}

case_a_system_layer_rung_derives_no_own_app() {
    # NO apps/ CHANGE AT ALL, and no shared test infrastructure either: the
    # declared rule is the fast tier alone, and it is not an error. Most rungs
    # of the V1 cycle were this case.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "echo hi" >"$REPO/scripts/thing.sh"
    own_apps_in "$REPO" "a rung that changed only scripts/"
    exits 0
    is "$LOOP_TIER_MODE" "fast" "the tier mode"
    is "$LOOP_TIER_OWN_APPS" "" "the derived own app set"
    is "$LOOP_TIER_SHARED_HITS" "" "the shared test-infra hits"
    reason_says "no file under apps/"
}

# --- the cases: SHARED TEST INFRASTRUCTURE RUNS THE FULL SUITE ----------------
#
# The lead's ruling, overruling this file's first answer. A
# rung whose change belongs to no app is not a rung with a small blast radius —
# a shared fixture is read by every app's tests BY CONSTRUCTION, and that change
# class is precisely where loop-time discovery is worth most. It is also rare,
# so the full suite costs almost nothing across a cycle. The old answer (fast
# tier alone) was the cheap read of "no own app" and it was wrong.
#
# BOTH BRANCHES ARE PINNED HERE, in both directions: a shared-infra change must
# go FULL, and a change that merely has no own app must still go FAST. A rule
# that only ever said "full" would pass every case below the first.

case_a_shared_conftest_change_runs_the_full_suite() {
    # `apps/conftest.py` is the fixture file every app's tests inherit. This is
    # the ruling's own worked example.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "# shared, edited" >"$REPO/apps/conftest.py"
    own_apps_in "$REPO" "a change to apps/conftest.py"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
    is "$LOOP_TIER_OWN_APPS" "" "the derived own app set"
    is "$LOOP_TIER_SHARED_HITS" "apps/conftest.py" "the shared test-infra hits"
    reason_says "shared test infrastructure"
}

case_a_root_conftest_change_runs_the_full_suite() {
    # A `conftest.py` at the repository root. There is none today; the rule is
    # written by SHAPE so the day one appears it is covered, rather than the day
    # after somebody notices.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "# root, edited" >"$REPO/conftest.py"
    own_apps_in "$REPO" "a change to a root conftest.py"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
    is "$LOOP_TIER_SHARED_HITS" "conftest.py" "the shared test-infra hits"
}

case_a_conftest_outside_apps_runs_the_full_suite() {
    # `perf/conftest.py` — outside `testpaths`, so its real blast radius on the
    # default suite is nil. It is in ANYWAY, and that is the rule choosing not
    # to be clever: "which conftests really matter" is a judgement that drifts,
    # "a conftest no app owns" is a shape that does not. Over-inclusion costs
    # one rare full `--loop`; under-inclusion is a silent hole.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "# perf, edited" >"$REPO/perf/conftest.py"
    own_apps_in "$REPO" "a change to perf/conftest.py"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
}

case_an_apps_root_test_module_runs_the_full_suite() {
    # `apps/test_temporal_guard.py` and `apps/test_gate_liveness.py` sit at the
    # apps root and belong to no app. THIS ONE IS NOT ABOUT FIXTURES — it is the
    # hole that argues loudest: both name the Temporal entry point, so both
    # derive into the SLOW tier, and under the old rule a rung editing one of
    # them had its own changed test deselected and never ran it.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "def test_guard(): pass  # edited" >"$REPO/apps/test_guard.py"
    own_apps_in "$REPO" "a change to a test module at the apps root"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
    is "$LOOP_TIER_SHARED_HITS" "apps/test_guard.py" "the shared test-infra hits"
}

case_a_gate_drive_change_runs_the_full_suite() {
    # `scripts/tests/**`. Its pytest blast radius is NIL and that is said out
    # loud in loop_tier.sh: no shell drive can change what a test does. It is in
    # for the other half of the ruling's principle — a rung that changes the
    # machinery deciding whether things pass should not be graded by a narrowed
    # run of that machinery.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "echo drive  # edited" >"$REPO/scripts/tests/test_thing.sh"
    own_apps_in "$REPO" "a change to a gate drive"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
}

case_the_tiers_own_derivation_runs_the_full_suite() {
    # The reflexive case. A rung that changes how the tier decides must not be
    # graded by the tier it changed — which is this very rung, and every rung
    # that ever touches this file again.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "# tier, edited" >"$REPO/scripts/loop_tier.sh"
    own_apps_in "$REPO" "a change to scripts/loop_tier.sh"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
}

case_an_apps_own_conftest_is_not_shared() {
    # THE NEGATIVE THAT MATTERS MOST. `apps/exports/tests/conftest.py` is a
    # conftest, and it belongs to `exports`. A rule that swept every conftest
    # into the full suite would make the commonest fixture edit in the tree pay
    # for the whole thing, and that is what this case has always refused.
    #
    # WHAT THE TESTS-ONLY ROW MOVED, AND WHAT IT DID NOT. The file is inside
    # `exports`' test tree, so it is now TESTS-ONLY rather than own: exports'
    # test tree runs at the fast tier, its organ tests wait for the push, and
    # nothing widens through the declarations. Narrower than before, and in the
    # same direction. What this case exists to pin is unchanged and is asserted
    # below: it is not SHARED infrastructure, and it is not the full suite.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "# app fixtures, edited" >"$REPO/apps/exports/tests/conftest.py"
    own_apps_in "$REPO" "a change to an app's own tests/conftest.py"
    exits 0
    is "$LOOP_TIER_MODE" "fast" "the tier mode"
    is "$LOOP_TIER_SHARED_HITS" "" "the shared test-infra hits"
    is "$LOOP_SCOPE_TESTS_ONLY" "exports" "the tests-only set"
    is "$LOOP_TIER_OWN_APPS" "" "the derived own app (a test-tree edit is not an own app)"
}

case_shared_infra_outranks_an_app_change() {
    # Both at once. The blast radius of the shared half does not shrink because
    # an app was touched beside it, so `full` wins and the own-app list is
    # irrelevant — there is nothing left for it to promote.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "x = 2" >"$REPO/apps/core/models.py"
    echo "# shared, edited" >"$REPO/apps/conftest.py"
    own_apps_in "$REPO" "an app change AND a shared conftest change"
    exits 0
    is "$LOOP_TIER_MODE" "full" "the tier mode"
    is "$LOOP_TIER_SHARED_HITS" "apps/conftest.py" "the shared test-infra hits"
}

case_an_app_change_alone_still_gets_the_fast_tier() {
    # The unchanged branch, asserted after all of the above so a rule that
    # started answering "full" to everything is a red case rather than a
    # slightly slower loop nobody notices.
    fresh_checkout
    git -C "$REPO" checkout -q -b rung
    echo "x = 2" >"$REPO/apps/core/models.py"
    own_apps_in "$REPO" "an app change and nothing shared"
    exits 0
    is "$LOOP_TIER_MODE" "fast" "the tier mode"
    is "$LOOP_TIER_OWN_APPS" "core" "the derived own app"
    reason_says "own app"
}

case_no_git_is_could_not_look() {
    # An underived set is not an empty set. If git cannot answer, the mapping
    # says so and check.sh turns that into exit 2 rather than a fast tier.
    local outside="${WORK}/not-a-repo"
    drive_require_scratch outside "${outside:-}"
    mkdir -p "$outside"
    # `git rev-parse --git-dir` walks UPWARDS, so a directory under $TMPDIR is
    # only outside a repository if nothing above it is one. That is the case on
    # every platform this runs on; if it ever stops being, this case reads as a
    # pass it did not earn, so it asserts the precondition first.
    if (cd "$outside" && git rev-parse --git-dir >/dev/null 2>&1); then
        cannot_look "the scratch directory ${outside} is inside a git repository, so the no-git case cannot be arranged"
    fi
    own_apps_in "$outside" "a directory that is not a repository"
    exits 2
    is "$LOOP_TIER_OWN_APPS" "" "the derived own app set"
}

# --- the cases: the wiring ----------------------------------------------------

case_the_tier_is_wired_into_the_loop_leg() {
    CURRENT="the wiring in check.sh"
    OUT=""
    if grep -q '^\. scripts/loop_tier\.sh$' "${ROOT}/scripts/check.sh"; then
        ok "check.sh sources scripts/loop_tier.sh"
    else
        bad "check.sh does not source scripts/loop_tier.sh — the mapping is not wired"
    fi
    if grep -q 'djb-tier=fast' "${ROOT}/scripts/check.sh"; then
        ok "the --loop pytest leg asks for the fast tier"
    else
        bad "no --djb-tier=fast in check.sh — the loop leg still runs the whole suite"
    fi
    if grep -q 'loop_tier_own_apps' "${ROOT}/scripts/check.sh"; then
        ok "the own-app derivation is called"
    else
        bad "loop_tier_own_apps is never called — every rung would lose its own app"
    fi
    if grep -q 'the pytest tier COULD NOT DERIVE' "${ROOT}/scripts/check.sh"; then
        ok "a could-not-derive is exit 2, not a fast tier"
    else
        bad "no could-not-look branch on the tier derivation"
    fi
    # The full branch has to be REACHABLE from the leg, not merely derivable in
    # the library: a mode nothing branches on is a mode that does not exist.
    if grep -q 'LOOP_TIER_MODE' "${ROOT}/scripts/check.sh"; then
        ok "the leg branches on the derived tier mode"
    else
        bad "check.sh never reads LOOP_TIER_MODE — the shared-infra full-suite branch is unreachable"
    fi
    if grep -q 'LOOP_TIER_REASON' "${ROOT}/scripts/check.sh"; then
        ok "the leg prints the derived tier reason"
    else
        bad "check.sh never prints LOOP_TIER_REASON — the tier rule would be chosen silently"
    fi
}

case_the_full_gate_leg_carries_no_tier() {
    # The push-side passes must go on running everything. Read as text, for the
    # reason this file's header gives.
    CURRENT="the full gate's pytest leg"
    OUT=""
    local boundary last_tier
    boundary=$(grep -n '^# --- the full legs' "${ROOT}/scripts/check.sh" | head -1 | cut -d: -f1)
    if [ -z "$boundary" ]; then
        bad "check.sh no longer has a '# --- the full legs' marker — the halves cannot be told apart"
        return
    fi
    ok "the full-gate legs begin at check.sh:${boundary}"
    # EVERY mention of the tier must sit ABOVE that line, which is to say inside
    # the `--loop` block that exits before it. A tier flag below it would narrow
    # the push-side passes, and the recorded verdict would start vouching for
    # less than it always has.
    last_tier=$(grep -n 'djb-tier\|djb-own-app\|TIER_ARGS' "${ROOT}/scripts/check.sh" |
        tail -1 | cut -d: -f1)
    if [ -z "$last_tier" ]; then
        bad "check.sh mentions no tier at all — the --loop leg still runs the whole suite"
    elif [ "$last_tier" -lt "$boundary" ]; then
        ok "every tier mention (last at :${last_tier}) is inside the --loop block"
    else
        bad "a tier mention at check.sh:${last_tier} is BELOW the full-legs boundary — the push-side passes have been narrowed"
    fi
}

# --- the cases: the DECLARED cross-app censuses -------------------------------
#
# The third way into the always-on set, and the only one a human writes. The two
# derived ways are driven above through the organ manifest; this one is driven
# through the SCOPE, because being unconditional is the whole of what it buys.

#: The marker, assembled from the constant the gate reads rather than spelled —
#: a drive that spelled it would be a module carrying the marker in a file that
#: `loop_scope__declared_censuses` never reads and a future shell census might.
census_plant_head() {
    printf '%s %s\n' "$LOOP_SCOPE_CENSUS_MARKER" "$1"
}

#: The `always-on` field of the scope report line, or the empty string.
always_on_count() {
    awk 'match($0, /\([0-9]+ in scope, [0-9]+ always-on\)/) {
        s = substr($0, RSTART, RLENGTH)
        sub(/.*, /, "", s)
        sub(/ always-on\)/, "", s)
        print s
        exit
    }' "$1"
}

# collect_narrow <label> [<extra pytest flags>...]
#
# The loop's own pytest door, narrowed, and NOT `-q`: the scope report line this
# reads lives in the collection-finish block, which `-q` suppresses.
collect_narrow() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/narrow${N}.log"
    RC=0
    (cd "$ROOT" && uv run pytest --collect-only -p no:randomly --djb-scope-narrow "$@") \
        >"$OUT" 2>&1 || RC=$?
}

case_a_marked_census_is_always_on_at_an_empty_scope() {
    # THE PROPERTY, DRIVEN BOTH WAYS. A module in `apps/files` that declares
    # itself a cross-app census survives a scope that contains no app at all and
    # a scope that contains somebody else's — and the always-on COUNT goes back
    # to where it was when the plant leaves, so the case cannot pass by the
    # derivation having grown a second opinion about something else.
    remove_plants
    collect_narrow "an empty scope, no plant"
    exits 0
    local before with after
    before=$(always_on_count "$OUT")
    if [ -n "$before" ]; then
        ok "the scope report line carries an always-on count (${before})"
    else
        bad "no '(<n> in scope, <n> always-on)' line — the report stopped counting"
        return
    fi

    {
        census_plant_head "walks every *.py under apps/ — planted by test_loop_tier.sh"
        echo '"""Planted by scripts/tests/test_loop_tier.sh. Removed by it. Never run."""'
        echo
        echo "import pathlib"
        echo
        echo "WALKED = sorted(pathlib.Path(\"apps\")${WALK_SUFFIX}\"*.py\"))"
        echo
        echo
        echo "def test_a_planted_declared_cross_app_census() -> None:"
        echo "    assert WALKED is not None"
    } >"${ROOT}/${PLANT_CENSUS}"

    collect_narrow "an empty scope, the plant declared"
    exits 0
    if grep -q "test_a_planted_declared_cross_app_census" "$OUT"; then
        ok "the declared census is COLLECTED at a scope holding no app at all"
    else
        bad "the declared census was deselected at an empty scope — the marker buys nothing"
    fi
    with=$(always_on_count "$OUT")
    if [ "$with" = "$((before + 1))" ]; then
        ok "the always-on count counted it (${before} -> ${with})"
    else
        bad "always-on went ${before} -> ${with}; the plant is kept by something other than the marker"
    fi

    # Somebody ELSE'S app in scope — the case a scope narrowing is actually for.
    collect_narrow "another app's scope, the plant declared" --djb-own-app=usage
    exits 0
    if grep -q "test_a_planted_declared_cross_app_census" "$OUT"; then
        ok "and at a scope holding another app (usage)"
    else
        bad "the declared census was deselected when the rung's own app was usage"
    fi

    remove_plants
    collect_narrow "an empty scope, the plant removed"
    exits 0
    after=$(always_on_count "$OUT")
    is "$after" "$before" "the always-on count with the plant gone"
    if grep -q "test_a_planted_declared_cross_app_census" "$OUT"; then
        bad "the removed plant is STILL collected — the population only ever grows"
    else
        ok "the plant left when it was removed"
    fi
}

case_the_always_digest_moves_with_the_rule_not_with_a_marker() {
    # THE COST OF THE MARKER, STATED AS A TEST. The vocabulary is inside
    # the sentinels, so the digest moved ONCE and every banked loop verdict
    # missed once. What must NOT happen afterwards is a digest that moves every
    # time somebody marks a module: the block is the RULE, and the marked set is
    # derived at the door.
    CURRENT="the always-on digest"
    OUT=""
    local real marked outside inside copy
    real=$(loop_scope__always_digest "${ROOT}/apps/conftest.py")
    if [ -n "$real" ] && [ "$real" != "UNDECLARED" ]; then
        ok "the sentinel block digests (${real})"
    else
        bad "the sentinel block did not digest: '${real}'"
        return
    fi

    # A MARKER ON A MODULE. Planted for real, in the tree, and the digest is
    # taken again: nothing about `apps/conftest.py` changed, so nothing about the
    # key may.
    {
        census_plant_head "walks every *.py under apps/ — planted by test_loop_tier.sh"
        echo '"""Planted by scripts/tests/test_loop_tier.sh. Removed by it. Never run."""'
        echo
        echo
        echo "def test_a_planted_declared_cross_app_census() -> None:"
        echo "    assert True"
    } >"${ROOT}/${PLANT_CENSUS}"
    marked=$(loop_scope__always_digest "${ROOT}/apps/conftest.py")
    remove_plants
    is "$marked" "$real" "the digest with a newly marked module in the tree"

    # A BYTE OUTSIDE THE SENTINELS — also not the rule.
    copy="${WORK}/conftest_outside.py"
    cp "${ROOT}/apps/conftest.py" "$copy"
    printf '\n# a byte outside the sentinels, planted by test_loop_tier.sh\n' >>"$copy"
    outside=$(loop_scope__always_digest "$copy")
    is "$outside" "$real" "the digest with a byte changed OUTSIDE the block"

    # A BYTE INSIDE THEM — the rule itself. This one MUST move.
    copy="${WORK}/conftest_inside.py"
    awk -v m="DJB_CENSUS_MARKER = " '
        index($0, m) == 1 { print m "\"# census: planted-by-the-drive\""; next }
        { print }
    ' "${ROOT}/apps/conftest.py" >"$copy"
    inside=$(loop_scope__always_digest "$copy")
    if [ "$inside" != "$real" ] && [ "$inside" != "UNDECLARED" ]; then
        ok "the digest MOVES when the rule inside the block moves"
    else
        bad "the digest did not move on a changed rule: '${inside}' — a banked verdict would survive it"
    fi
}

case_the_loop_banner_names_each_declared_census() {
    # THE BANNER'S DERIVATION, driven over a scratch apps tree so the assertions
    # are about the reader and not about today's marked set.
    CURRENT="the declared-census listing"
    OUT=""
    local world got rc
    world="${WORK}/census-world"
    mkdir -p "${world}/apps/alpha/tests" "${world}/apps/beta/tests"
    {
        census_plant_head "walks every *.py under apps/ for the drive's sake"
        echo '"""A scratch module."""'
    } >"${world}/apps/alpha/tests/test_marked.py"
    echo '"""A scratch module with nothing to declare."""' >"${world}/apps/beta/tests/test_plain.py"

    OUT="${WORK}/census-list.log"
    rc=0
    loop_scope__declared_censuses "${world}/apps" >"$OUT" 2>&1 || rc=$?
    RC=$rc
    exits 0
    got=$(wc -l <"$OUT" | tr -d ' ')
    is "$got" "1" "the number of declared censuses in the scratch world"
    says "apps/alpha/tests/test_marked.py"
    says "walks every *.py under apps/ for the drive's sake"
    if grep -q "test_plain" "$OUT"; then
        bad "an UNMARKED module was listed — the reader is not reading the marker"
    else
        ok "the unmarked module is not listed"
    fi

    # A BARE MARKER IS COULD-NOT-LOOK, never an absent one.
    census_plant_head "" >"${world}/apps/beta/tests/test_plain.py"
    OUT="${WORK}/census-bare.log"
    RC=0
    loop_scope__declared_censuses "${world}/apps" >"$OUT" 2>&1 || RC=$?
    exits 2
    says "NO REASON"
    rm -f "${world}/apps/beta/tests/test_plain.py"

    # AN EMPTY SET IS A TREE, NOT A BROKEN READ.
    rm -f "${world}/apps/alpha/tests/test_marked.py"
    OUT="${WORK}/census-empty.log"
    RC=0
    loop_scope__declared_censuses "${world}/apps" >"$OUT" 2>&1 || RC=$?
    exits 0
    got=$(wc -c <"$OUT" | tr -d ' ')
    is "$got" "0" "the bytes printed for a world with nothing declared"

    # A DIRECTORY THAT IS NOT THERE IS EXIT 2.
    OUT="${WORK}/census-absent.log"
    RC=0
    loop_scope__declared_censuses "${world}/nowhere" >"$OUT" 2>&1 || RC=$?
    exits 2
    says "is not a directory"

    # THE ONE GRAMMAR, SPELLED TWICE. The shell's constant and the sentinel
    # block's must be the same three words, or the banner lists a population the
    # door does not keep.
    OUT=""
    local python_marker python_lines
    python_marker=$(awk -F'"' '/^DJB_CENSUS_MARKER = /{print $2; exit}' "${ROOT}/apps/conftest.py")
    is "$python_marker" "$LOOP_SCOPE_CENSUS_MARKER" "the marker apps/conftest.py declares"
    python_lines=$(awk -F'= ' '/^DJB_CENSUS_MARKER_LINES = /{print $2; exit}' "${ROOT}/apps/conftest.py")
    is "$python_lines" "$LOOP_SCOPE_CENSUS_LINES" "the header depth apps/conftest.py declares"
    # AND THE CLAUSE INSIDE THE LINE. The population is the half a loop ACTS on,
    # so a shell that spelled it differently would list a census as unbounded
    # while the door narrowed it — the two grammars agreeing is the only thing
    # that makes the banner a reading of the door's own rule.
    local python_population
    python_population=$(awk -F'"' '/^DJB_CENSUS_POPULATION = /{print $2; exit}' \
        "${ROOT}/apps/conftest.py")
    is "$python_population" "${LOOP_SCOPE_CENSUS_POPULATION:-<unset>}" \
        "the population clause apps/conftest.py declares"

    # AND THE WIRING: the leg has to CALL it and PRINT it, or the listing exists
    # in the library and nowhere a reader looks.
    if grep -q 'loop_scope__declared_censuses' "${ROOT}/scripts/check.sh"; then
        ok "check.sh calls loop_scope__declared_censuses"
    else
        bad "check.sh never calls loop_scope__declared_censuses — the banner lists nothing"
    fi
    if grep -q 'always-on censuses (declared)' "${ROOT}/scripts/check.sh"; then
        ok "the --loop banner names the declared censuses"
    else
        bad "no 'always-on censuses (declared)' line in check.sh"
    fi
    if grep -q '(none declared)' "${ROOT}/scripts/check.sh"; then
        ok "an empty set is PRINTED as such, not as silence"
    else
        bad "check.sh prints nothing for an empty declared set — silence reads as 'not looked'"
    fi
}

case_a_declared_population_reaches_the_banner_and_an_empty_one_refuses() {
    # THE POPULATION, THROUGH THE SHELL'S HALF OF THE GRAMMAR. The pytest door
    # decides with it (`apps/conftest.py::_census_verdict`); this reader only has
    # to carry it to the banner unbroken and refuse the half-written form — the
    # same two jobs it already has for the reason.
    CURRENT="the declared population"
    OUT=""
    local world got
    world="${WORK}/population-world"
    mkdir -p "${world}/apps/alpha/tests"
    {
        census_plant_head "${LOOP_SCOPE_CENSUS_POPULATION:-population=}apps/alpha/** walks alpha"
        echo '"""A scratch module."""'
    } >"${world}/apps/alpha/tests/test_bounded.py"

    OUT="${WORK}/population-list.log"
    RC=0
    loop_scope__declared_censuses "${world}/apps" >"$OUT" 2>&1 || RC=$?
    exits 0
    got=$(wc -l <"$OUT" | tr -d ' ')
    is "$got" "1" "the number of declared censuses in the bounded world"
    says "apps/alpha/** walks alpha"

    # A `population=` WITH NO GLOBS IS COULD-NOT-LOOK, exactly as a marker with
    # no reason is: read as an absent population, it would make the census
    # unconditional at the very moment its author meant to bound it.
    {
        census_plant_head "${LOOP_SCOPE_CENSUS_POPULATION:-population=} walks alpha"
        echo '"""A scratch module."""'
    } >"${world}/apps/alpha/tests/test_bounded.py"
    OUT="${WORK}/population-empty.log"
    RC=0
    loop_scope__declared_censuses "${world}/apps" >"$OUT" 2>&1 || RC=$?
    exits 2
    says "EMPTY POPULATION"

    # AND THE REAL TREE'S DECLARATIONS REACH THE BANNER WITH THEIRS.
    OUT="${WORK}/population-tree.log"
    RC=0
    loop_scope__declared_censuses "${ROOT}/apps" >"$OUT" 2>&1 || RC=$?
    exits 0
    says "${LOOP_SCOPE_CENSUS_POPULATION:-population=}"
}

# --- the cases: the ALWAYS-ON leg ---------------------------------------------
#
# The fourth way a test runs at every scope, and the only one on the SHELL side:
# `--loop` now runs a derived set of members that used to be full-only. Two
# halves, two derivations, one leg — the declared censuses (a drive's own
# marker) and the measured members (the committed durations file, under a
# floor).
#
# THE LEG BODY IS EXTRACTED AND SOURCED, never reached through a nested gate:
# the per-checkout gate lock refuses one, so a drive that shelled out to
# `check.sh` would go red for the lock and not for the property
# (rung-execution §2). The sentinels are assembled rather than written at the
# head of a line, so this file cannot be mistaken for the fence it looks for —
# `test_setup_env.sh`'s idiom, for its reason.
ALWAYS_SENT_OPEN="# >>> always-on-""leg >>>"
ALWAYS_SENT_CLOSE="# <<< always-on-""leg <<<"
ALWAYS_BODY="${WORK}/always_on_leg_body.sh"

always_extract() {
    sed -n "/^${ALWAYS_SENT_OPEN}\$/,/^${ALWAYS_SENT_CLOSE}\$/p" \
        "${ROOT}/scripts/check.sh" >"$ALWAYS_BODY" 2>/dev/null || true
    [ -s "$ALWAYS_BODY" ] || return 1
    grep -q '^always_on_leg() {' "$ALWAYS_BODY" || return 1
    return 0
}

# A SCRATCH MEMBER SET, built per case. Each argument is `<name>:<exit status>`,
# and `ALWAYS_PLANT_MARK` names the one member (if any) that carries the
# cross-app marker. Every planted drive carries a `# drives:` line, because a
# member the leg cannot key is one it RUNS with a printed reason — a legal
# answer, and not the one most cases are about.
ALWAYS_PLANT_MARK=""
always_plant_members() {
    local dir="$1"
    shift
    local spec name rc
    rm -rf "$dir"
    mkdir -p "$dir"
    printf '# a scratch member set preamble — never sourced, always keyed\n' \
        >"${dir}/drive_preamble.sh"
    for spec in "$@"; do
        name="${spec%%:*}"
        rc="${spec##*:}"
        {
            printf '#!/bin/sh\n'
            [ "$name" != "$ALWAYS_PLANT_MARK" ] ||
                census_plant_head "a planted cross-app census; no organs"
            printf '# drives: scripts/tests/drive_preamble.sh\n'
            printf 'echo "planted member %s speaking"\n' "$name"
            printf 'exit %s\n' "$rc"
        } >"${dir}/test_${name}.sh"
        chmod +x "${dir}/test_${name}.sh"
    done
}

# A DURATIONS FILE, planted. `<name>:<seconds>` per argument; the header fields
# are fixed so the banner can be asserted as text.
always_plant_durations() {
    local path="$1"
    shift
    local spec first=1
    {
        printf '{\n'
        printf '  "measured_at": "planted0000000000000000000000000000000000",\n'
        printf '  "machine": "Scratch 0.0",\n'
        printf '  "members": {\n'
        for spec in "$@"; do
            [ "$first" = "1" ] || printf ',\n'
            first=0
            printf '    "%s": %s' "${spec%%:*}" "${spec##*:}"
        done
        [ "$first" = "1" ] || printf '\n'
        printf '  }\n'
        printf '}\n'
    } >"$path"
}

# RUN THE LEG BODY over a planted set, in a subshell so its `set +e`/`set -e`
# pairs cannot reach this drive's shell. The two ledger libraries come in beside
# the body because the leg consults a drive verdict through them — extracting
# the body without them would drive a leg that cannot exist.
ALWAYS_LEDGER=""
ALWAYS_NO_DURATIONS=""
always_run_leg() {
    local dir="$1" durations="${2:-}"
    ALWAYS_OUT="${WORK}/always-leg.out"
    ALWAYS_RC=0
    [ -n "$ALWAYS_LEDGER" ] ||
        cannot_look "no scratch ledger is set — refusing to drive the leg against the shared djb-gate-verdicts"
    (
        set +e
        cd "$ROOT" || exit 2
        DJB_SELFTEST_DRIVES_DIR="$dir"
        export DJB_SELFTEST_DRIVES_DIR
        DJB_GATE_LEDGER="$ALWAYS_LEDGER"
        export DJB_GATE_LEDGER
        if [ -n "$durations" ]; then
            DJB_GATE_MEMBER_DURATIONS="$durations"
            export DJB_GATE_MEMBER_DURATIONS
        fi
        . scripts/gate_refuse.sh
        . scripts/gate_ledger.sh
        . scripts/loop_tier.sh
        . "$ALWAYS_BODY"
        MEASURED_START=$(gate_measured_tree 2>/dev/null || true)
        export MEASURED_START
        always_on_leg
    ) >"$ALWAYS_OUT" 2>&1 || ALWAYS_RC=$?
}

always_new_ledger() {
    ALWAYS_LEDGER="${WORK}/always-verdicts-$1"
    rm -f "$ALWAYS_LEDGER"
    : >"$ALWAYS_LEDGER"
}

always_says() {
    if grep -qF -- "$1" "$ALWAYS_OUT"; then
        ok "the leg says \"$1\""
    else
        bad "the leg does not say \"$1\"; it said: $(tr '\n' '|' <"$ALWAYS_OUT")"
    fi
}
always_silent_about() {
    if grep -qF -- "$1" "$ALWAYS_OUT"; then
        bad "the leg said \"$1\" and should not have; it said: $(tr '\n' '|' <"$ALWAYS_OUT")"
    else
        ok "the leg says nothing about \"$1\""
    fi
}

case_the_always_on_leg_derives_its_members_from_the_durations_file() {
    CURRENT="the always-on leg's derivation"
    OUT=""
    if ! always_extract; then
        bad "scripts/check.sh has no \`${ALWAYS_SENT_OPEN}\` fence defining always_on_leg — the leg this case drives does not exist (which is what the baseline looks like)"
        return
    fi
    ok "the leg body extracted from scripts/check.sh between its own sentinels"
    always_new_ledger derive
    local dir="${WORK}/always-derive" durations="${WORK}/always-derive.json"
    ALWAYS_PLANT_MARK=""
    always_plant_members "$dir" cheap:0 pricey:0 nameless:0
    always_plant_durations "$durations" cheap:3 pricey:11
    always_run_leg "$dir" "$durations"
    if [ "$ALWAYS_RC" != "0" ]; then
        bad "an all-green set gave exit ${ALWAYS_RC}: $(tr '\n' '|' <"$ALWAYS_OUT")"
        return
    fi
    # The file it read, and the two facts that make a stale one readable.
    always_says "measured_at planted0000000000000000000000000000000000"
    always_says "on Scratch 0.0"
    # A member under the floor RUNS.
    if grep -qE '^  member cheap: exit 0 \([0-9]+s\)$' "$ALWAYS_OUT"; then
        ok "the 3 s member ran and printed its own seconds"
    else
        bad "no \`member cheap: exit 0 (Ns)\` line: $(tr '\n' '|' <"$ALWAYS_OUT")"
    fi
    # A member at or above it does not, and SAYS SO.
    always_says "pricey above the floor (11 s)"
    always_silent_about "member pricey: exit"
    # A member the file does not name does not, and says why.
    always_says "nameless unmeasured — joins after the next --store-durations"
    always_silent_about "member nameless: exit"
}

case_a_full_only_red_reds_the_loop() {
    CURRENT="a full-only member's red is now a loop red"
    OUT=""
    always_extract || {
        bad "no always-on fence in scripts/check.sh"
        return
    }
    local dir="${WORK}/always-red" durations="${WORK}/always-red.json"
    ALWAYS_PLANT_MARK=""
    always_new_ledger red
    always_plant_members "$dir" quiet:0 stray:1
    always_plant_durations "$durations" quiet:2 stray:6
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "1" "the leg's exit with one red member"
    always_says "RED: stray"
    # The member's own output is REPLAYED — a red nobody can read is a red
    # nobody can fix.
    always_says "planted member stray speaking"

    # AND 2 OUTRANKS 1, the same rule the selftest leg composes by.
    always_new_ledger cannot
    always_plant_members "$dir" quiet:0 blind:2
    always_plant_durations "$durations" quiet:2 blind:6
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "2" "the leg's exit with a could-not-look member"
    always_says "COULD NOT LOOK: blind"
}

case_no_durations_file_runs_only_the_declared_censuses() {
    CURRENT="no durations file"
    OUT=""
    always_extract || {
        bad "no always-on fence in scripts/check.sh"
        return
    }
    local dir="${WORK}/always-nofile"
    always_new_ledger nofile
    ALWAYS_PLANT_MARK=marked
    always_plant_members "$dir" marked:0 plain:0
    ALWAYS_PLANT_MARK=""
    always_run_leg "$dir" "${WORK}/there-is-no-such-file.json"
    is "$ALWAYS_RC" "0" "the leg's exit with no durations file"
    always_says "no durations file — the first --store-durations writes it"
    # THE DECLARED HALF IS UNCONDITIONAL — it is not derived from the file at
    # all, so it runs with no file, at every scope, whatever its price.
    always_says "census marked: exit 0"
    always_says "a planted cross-app census; no organs"
    always_silent_about "member plain: exit"
}

case_an_unknown_member_in_the_file_is_exit_2() {
    CURRENT="a durations file naming a member this gate does not have"
    OUT=""
    always_extract || {
        bad "no always-on fence in scripts/check.sh"
        return
    }
    local dir="${WORK}/always-unknown" durations="${WORK}/always-unknown.json"
    always_new_ledger unknown
    ALWAYS_PLANT_MARK=""
    always_plant_members "$dir" cheap:0
    always_plant_durations "$durations" cheap:3 not_a_member_of_this_gate:2
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "2" "the leg's exit on an unknown member name"
    always_says "not_a_member_of_this_gate"
    always_silent_about "member cheap: exit"
}

case_a_marked_drive_runs_in_the_loop_at_every_scope() {
    CURRENT="a marked drive is always-on whatever the measurement says"
    OUT=""
    always_extract || {
        bad "no always-on fence in scripts/check.sh"
        return
    }
    local dir="${WORK}/always-marked" durations="${WORK}/always-marked.json"
    always_new_ledger marked
    ALWAYS_PLANT_MARK=slowcensus
    always_plant_members "$dir" slowcensus:0 plain:0
    ALWAYS_PLANT_MARK=""
    # The marked member is recorded WAY above the floor and the unmarked one is
    # not measured at all: neither would join through the measured half, and the
    # marked one runs anyway. That is what the marker buys.
    always_plant_durations "$durations" slowcensus:600
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "0" "the leg's exit with one marked member"
    always_says "census slowcensus: exit 0"
    always_silent_about "slowcensus above the floor"
    always_silent_about "member plain: exit"

    # AND A MARKED MEMBER'S RED IS THE LEG'S RED, like any other member's.
    always_new_ledger markedred
    ALWAYS_PLANT_MARK=slowcensus
    always_plant_members "$dir" slowcensus:1
    ALWAYS_PLANT_MARK=""
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "1" "the leg's exit when the marked member reds"
    always_says "RED: slowcensus"
}

case_a_banked_member_is_reused_and_a_moved_input_is_not() {
    CURRENT="the drive-verdict consult in front of every member"
    OUT=""
    always_extract || {
        bad "no always-on fence in scripts/check.sh"
        return
    }
    local dir="${WORK}/always-reuse" durations="${WORK}/always-reuse.json"
    always_new_ledger reuse
    ALWAYS_PLANT_MARK=""
    always_plant_members "$dir" cheap:0
    always_plant_durations "$durations" cheap:3
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "0" "the first run's exit"
    if grep -qE '^  member cheap: exit 0 \([0-9]+s\)$' "$ALWAYS_OUT"; then
        ok "the first run DROVE the member"
    else
        bad "the first run did not drive it: $(tr '\n' '|' <"$ALWAYS_OUT")"
    fi
    if awk '$3 == "drive" && $5 == "cheap" { found = 1 } END { exit(found ? 0 : 1) }' "$ALWAYS_LEDGER"; then
        ok "a green member banked its own row"
    else
        bad "no drive row for the green member — nothing would ever be reused"
    fi

    # THE SECOND RUN ON THE SAME INPUTS IS A HIT, and it is printed exactly as
    # the bank prints one.
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "0" "the second run's exit"
    always_says "member cheap: REUSED from drive-v1:"
    always_silent_about "member cheap: exit 0"

    # A MOVED INPUT IS NOT A HIT. The member's own bytes are in its key, so
    # changing them re-keys it and the member runs.
    printf 'echo "and one more line"\n' >>"${dir}/test_cheap.sh"
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "0" "the third run's exit after an input moved"
    if grep -qE '^  member cheap: exit 0 \([0-9]+s\)$' "$ALWAYS_OUT"; then
        ok "a moved input refused the reuse and the member RAN"
    else
        bad "a moved input still hit the banked row: $(tr '\n' '|' <"$ALWAYS_OUT")"
    fi

    # A RED NEVER BANKS. It has cleared nothing, so a row for it would be a
    # verdict vouching for bytes nobody drove.
    always_new_ledger reusered
    always_plant_members "$dir" stray:1
    always_plant_durations "$durations" stray:3
    always_run_leg "$dir" "$durations"
    is "$ALWAYS_RC" "1" "the red run's exit"
    if awk '$3 == "drive" && $5 == "stray" { found = 1 } END { exit(found ? 1 : 0) }' "$ALWAYS_LEDGER"; then
        ok "the red member banked nothing"
    else
        bad "a RED member banked a row — the next loop would reuse it as a green"
    fi
}

case_the_canonical_scope_carries_the_always_on_inputs() {
    # A BANKED LOOP VERDICT MUST NOT VOUCH FOR MEMBERS IT DID NOT RUN. Both
    # inputs of the always-on set are outside every other field of the key, so
    # moving either has to move the key.
    CURRENT="the always-on inputs in the canonical scope"
    OUT=""
    local world="${WORK}/alwayson-digest" a b c
    mkdir -p "${world}/tests"
    printf '{"members": {}}\n' >"${world}/durations.json"
    a=$(loop_scope__always_on_digest "${world}/durations.json" "${world}/tests") || a=""
    if [ -z "$a" ]; then
        bad "loop_scope__always_on_digest printed nothing for a readable world"
        return
    fi
    ok "a world with a durations file and no marked drive digests to ${a:0:12}…"
    printf '{"members": {"x": 1}}\n' >"${world}/durations.json"
    b=$(loop_scope__always_on_digest "${world}/durations.json" "${world}/tests") || b=""
    if [ "$a" = "$b" ]; then
        bad "a re-measured durations file left the digest where it was — a banked row would vouch for a set that moved"
    else
        ok "a re-measurement moves the digest (${a:0:12}… → ${b:0:12}…)"
    fi
    {
        census_plant_head "a planted cross-app census; no organs"
        printf 'exit 0\n'
    } >"${world}/tests/test_planted.sh"
    c=$(loop_scope__always_on_digest "${world}/durations.json" "${world}/tests") || c=""
    if [ "$b" = "$c" ]; then
        bad "marking a drive cross-app left the digest where it was — a banked row would vouch for a census it never ran"
    else
        ok "a newly marked drive moves the digest (${b:0:12}… → ${c:0:12}…)"
    fi
    # A DIGEST OVER A SET NOBODY COULD ENUMERATE IS NOT A DIGEST. A marker with
    # no reason is the reader's own refusal, and it has to reach this caller.
    census_plant_head "" >"${world}/tests/test_planted.sh"
    if loop_scope__always_on_digest "${world}/durations.json" "${world}/tests" >/dev/null 2>&1; then
        bad "a marker with NO REASON still produced a digest — the refusal is swallowed"
    else
        ok "a marker with no reason refuses rather than digesting a half-read set"
    fi
    rm -f "${world}/tests/test_planted.sh"

    # AND THE FIELD IS IN THE KEY the ledger writes, not only in the library.
    if grep -q 'alwayson=' "${ROOT}/scripts/loop_tier.sh"; then
        ok "LOOP_SCOPE_CANONICAL carries an alwayson= field"
    else
        bad "no alwayson= field in the canonical scope — a re-measurement would be reused"
    fi
}

case_the_always_on_leg_is_wired_into_the_loop() {
    # The leg has to be REACHED by the mode, above the pytest leg, and it must
    # not be announced on the full path — where every one of its members
    # already runs, and running them twice is the one thing this leg must not
    # do. Read as text, for the reason this file's header gives.
    CURRENT="the always-on leg's wiring in check.sh"
    OUT=""
    local file="${ROOT}/scripts/check.sh" loop_at leg_at pytest_at boundary
    loop_at=$(grep -n '^if \[ "\$MODE" = "--loop" \]; then$' "$file" | sed -n '1p' | cut -d: -f1)
    leg_at=$(grep -n '^    gate_run_body always-on gate_leg_always_on$' "$file" | sed -n '1p' | cut -d: -f1)
    pytest_at=$(grep -n '^    gate_run_body pytest gate_leg_pytest$' "$file" | sed -n '1p' | cut -d: -f1)
    boundary=$(grep -n '^# --- the full legs' "$file" | sed -n '1p' | cut -d: -f1)
    if [ -z "$loop_at" ] || [ -z "$leg_at" ] || [ -z "$pytest_at" ] || [ -z "$boundary" ]; then
        bad "the --loop branch (${loop_at:-none}), the always-on call (${leg_at:-none}), the pytest call (${pytest_at:-none}) or the full-legs boundary (${boundary:-none}) is not in check.sh"
        return
    fi
    if [ "$leg_at" -gt "$loop_at" ] && [ "$leg_at" -lt "$boundary" ]; then
        ok "the always-on leg is called at :${leg_at}, inside the --loop block (:${loop_at}-:${boundary})"
    else
        bad "the always-on leg is called at :${leg_at}, outside the --loop block (:${loop_at}-:${boundary})"
    fi
    if [ "$leg_at" -lt "$pytest_at" ]; then
        ok "it runs BEFORE the pytest leg (:${pytest_at}) — a cheap red lands before the slot is taken"
    else
        bad "it runs after the pytest leg (:${pytest_at}): every red would wait for the suite"
    fi
    # ONE CALL SITE. Two would be the leg running twice under one name.
    is "$(grep -c '^    gate_run_body always-on gate_leg_always_on$' "$file" | tr -d ' ')" "1" \
        "the number of always-on call sites"
}

case_the_measurement_writes_a_file_its_own_reader_can_read() {
    # THE ROUND TRIP, AND WHY IT IS ITS OWN CASE. The writer and the reader are
    # two pieces of text about one file format, and their disagreement is
    # SILENT IN THE SAFE DIRECTION: an unparsable file is not a refusal — it is
    # "no durations file", which is the right answer for a tree before its
    # first measurement and the wrong answer forever after a writer change
    # nobody noticed. So the writer's output is fed to the reader here, and the
    # seconds have to come back.
    CURRENT="the durations file round trip"
    OUT=""
    always_extract || {
        bad "no always-on fence in scripts/check.sh"
        return
    }
    local times="${WORK}/round-times" out="${WORK}/round.json" got
    printf 'ruff 0\nselftest 1887\nqueue_index 2\nruff 0\n' >"$times"
    OUT="${WORK}/round.log"
    RC=0
    (
        set +e
        cd "$ROOT" || exit 2
        . scripts/gate_refuse.sh
        . "$ALWAYS_BODY"
        GATE_MEMBER_TIMES="$times"
        gate_member_durations_write "$out" "planted" || exit 1
        if always_on__read_durations "$out"; then
            printf 'measured_at=%s\n' "$ALWAYS_ON_MEASURED_AT"
            printf 'machine=%s\n' "$ALWAYS_ON_MACHINE"
            printf 'queue_index=%s\n' "$(always_on__recorded queue_index)"
            printf 'selftest=%s\n' "$(always_on__recorded selftest)"
            printf 'ruff=%s\n' "$(always_on__recorded ruff)"
            printf 'absent=[%s]\n' "$(always_on__recorded nothing_like_this)"
            printf 'rows=%s\n' "$(awk 'END { print NR + 0 }' "$ALWAYS_ON_TABLE")"
        else
            printf 'READ FAILED\n'
            exit 1
        fi
    ) >"$OUT" 2>&1 || RC=$?
    exits 0
    says "measured_at=tree:planted"
    says "queue_index=2"
    says "selftest=1887"
    says "ruff=0"
    says "absent=[]"
    # DE-DUPLICATED AND SORTED: the accumulator is appended to per member and a
    # member named twice must be one row, or two measurements of one file are
    # not comparable by diff.
    says "rows=3"
    got=$(awk 'NR == 1 { print; exit }' "$out")
    is "$got" "{" "the first line of the written file"
    # NO TRAILING COMMA on the last member: a file this reader is tolerant
    # about is still a file a human and `jq` read.
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$out" >/dev/null 2>&1; then
            ok "what the writer wrote parses as JSON"
        else
            bad "the writer produced something that is not JSON: $(tr '\n' '|' <"$out")"
        fi
    fi
    # AND AN EMPTY ACCUMULATOR WRITES NOTHING. A run that timed no member must
    # not replace a real measurement with an empty one.
    : >"$times"
    RC=0
    (
        set +e
        cd "$ROOT" || exit 2
        . scripts/gate_refuse.sh
        . "$ALWAYS_BODY"
        GATE_MEMBER_TIMES="$times"
        gate_member_durations_write "${WORK}/never-written.json" "tree:planted"
    ) >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the writer's exit with nothing measured"
    if [ -e "${WORK}/never-written.json" ]; then
        bad "an empty accumulator still wrote a file — a run that timed nothing would erase the measurement"
    else
        ok "an empty accumulator wrote no file at all"
    fi
}

case_the_measurement_flag_belongs_to_the_full_mode_alone() {
    # A MISTYPED FLAG IS NEVER A SILENTLY DIFFERENT RUN, AND THIS CASE NOW
    # WALKS THE ROAD IT USED TO PHOTOGRAPH. `--store-durations` has two senses
    # — the suite's own timing under `--leg`, and the whole gate's member clock
    # at the full mode — and at `--fast` or `--loop` it would be a measurement
    # of a SUBSET written into the file the whole set derives from.
    #
    # IT USED TO READ `scripts/check.sh` AS TEXT: `grep` for a `^--store-durations)`
    # arm, `grep` for `GATE_STORE_MEMBERS=1`, `grep` for the refusal's wording.
    # Every one of those was green on f800ab5b, and on f800ab5b the documented
    # invocation — `./scripts/check.sh --store-durations` — exited 2 with
    # `unknown argument '--store-durations'`, because the arm the grep found
    # was in the SECOND `case`, reachable only with something else in front of
    # it. A drive that greps a script vouches for a road nobody
    # walked, so this case EXECUTES the parser instead.
    #
    # WHAT IS EXECUTED, and it is a section of the real file rather than a copy:
    # `scripts/check.sh` from `MODE=${1:-}` down to the extra-arguments refusal
    # — the same boundaries `scripts/tests/test_gate_lease.sh`'s
    # `case_the_usage_header_and_the_parser_agree` derives — sourced in a
    # subshell with the positional parameters set. Sourcing it RUNS it, and its
    # `exit 2` ends the subshell, which is the behaviour under test with
    # nothing transcribed here to drift. A nested `./scripts/check.sh` is not
    # an option: the per-checkout gate lock refuses one (rung-execution §2).
    CURRENT="the --store-durations parser, executed"
    OUT=""
    local file="${ROOT}/scripts/check.sh" start endif fin

    start=$(awk -v want='MODE=${1:-}' '$0 == want { print NR; exit }' "$file")
    endif=$(awk -v want='if [ "$#" -gt 0 ]; then' '$0 == want { print NR; exit }' "$file")
    if [ -z "$start" ] || [ -z "$endif" ]; then
        bad "the parser section (starts '${start:-<none>}', extra-args check '${endif:-<none>}') is not in check.sh — this case has lost its subject"
        return
    fi
    fin=$(awk -v s="$endif" 'NR >= s && $0 == "fi" { print NR; exit }' "$file")
    if [ -z "$fin" ] || [ "$fin" -le "$start" ]; then
        bad "the extra-arguments refusal at :${endif} has no closing 'fi' at column 1 — the extraction cannot be trusted"
        return
    fi
    PARSER_BODY="${WORK}/parser.sh"
    sed -n "${start},${fin}p" "$file" >"$PARSER_BODY"
    if ! grep -q '^case "\$MODE" in$' "$PARSER_BODY"; then
        bad "the extracted section (check.sh:${start}-${fin}) holds no mode case — nothing to drive"
        return
    fi
    ok "the parser is check.sh:${start}-${fin}, $(awk 'END { print NR }' "$PARSER_BODY") lines, extracted and run (never read)"

    # parser_run <label> <arg...> — source the section with those arguments and
    # print the variables the rest of the gate branches on. RC is the section's
    # own exit status, which for a refusal is the `exit 2` inside it.
    parser_run() {
        local label=$1
        shift
        OUT="${WORK}/parser-${label}.out"
        RC=0
        (
            set -uo pipefail
            cd "$ROOT" || exit 2
            set -- "$@"
            # shellcheck disable=SC1090  # the extracted section, by design
            . "$PARSER_BODY"
            printf 'MODE=[%s]\n' "$MODE"
            printf 'GATE_STORE_MEMBERS=[%s]\n' "$GATE_STORE_MEMBERS"
            printf 'GATE_STORE_DURATIONS=[%s]\n' "$GATE_STORE_DURATIONS"
            printf 'GATE_BANK=[%s]\n' "$GATE_BANK"
            printf 'GATE_LEG_UNIT=[%s]\n' "$GATE_LEG_UNIT"
        ) >"$OUT" 2>&1 || RC=$?
    }

    CURRENT="./scripts/check.sh --store-durations (the documented form)"
    parser_run store-alone --store-durations
    exits 0
    says "MODE=[]"
    says "GATE_STORE_MEMBERS=[1]"
    # AND IT NORMALISES RATHER THAN BECOMING A MODE: the suite's own timing
    # flag must stay clear, or one word would ask for two different
    # measurements.
    says "GATE_STORE_DURATIONS=[]"

    CURRENT="--fast --store-durations still refuses"
    parser_run fast-store --fast --store-durations
    exits 2
    says "--store-durations without --leg measures the WHOLE gate"

    CURRENT="--loop --store-durations still refuses"
    parser_run loop-store --loop --store-durations
    exits 2
    says "--store-durations without --leg measures the WHOLE gate"

    CURRENT="the other sense survives: --leg pytest-x2 --store-durations"
    parser_run leg-store --leg pytest-x2 --store-durations
    exits 0
    says "MODE=[--leg]"
    says "GATE_LEG_UNIT=[pytest-x2]"
    says "GATE_STORE_DURATIONS=[1]"
    says "GATE_STORE_MEMBERS=[]"

    CURRENT="the negative: --bank is untouched by the new arm"
    parser_run bank --bank
    exits 0
    says "MODE=[]"
    says "GATE_BANK=[1]"
    says "GATE_STORE_MEMBERS=[]"

    CURRENT="the negative: an actually unknown flag is still exit 2"
    parser_run bogus --store-duration
    exits 2
    says "unknown argument '--store-duration'"

    # THE PLANT, AND IT IS WHAT MAKES THE GREEN ABOVE WORTH ANYTHING. Cut the
    # new mode arm out of the extracted section and the documented invocation
    # must go back to the refusal it printed on f800ab5b. Its own victim: a
    # copy of the section, never the file.
    CURRENT="and with the mode arm removed the documented form reds again"
    local plant="${WORK}/parser-narrowed.sh"
    python3 - "$PARSER_BODY" "$plant" <<'PY_CUT'
import sys

body = open(sys.argv[1]).read().split("\n")
out, i, cut = [], 0, 0
# The FIRST `--store-durations)` arm is the mode case's. Drop it and its
# arm body, up to and including the `    ;;` that ends it, and leave the
# second (the full-mode arm in the later `case`) alone.
while i < len(body):
    if cut == 0 and body[i] == "--store-durations)":
        cut = 1
        i += 1
        while i < len(body) and body[i] != "    ;;":
            i += 1
        i += 1
        continue
    out.append(body[i])
    i += 1
if cut == 0:
    raise SystemExit("no mode arm to cut — the plant would prove nothing")
open(sys.argv[2], "w").write("\n".join(out))
PY_CUT
    if [ ! -s "$plant" ]; then
        bad "the narrowed parser is empty — the plant cut everything"
    else
        local saved="$PARSER_BODY"
        PARSER_BODY="$plant"
        parser_run narrowed --store-durations
        PARSER_BODY="$saved"
        if [ "$RC" = "2" ] && grep -qF -- "unknown argument '--store-durations'" "$OUT"; then
            ok "exit 2, \"unknown argument '--store-durations'\" — the arm is load-bearing and this case can fail"
        else
            bad "the narrowed parser exited ${RC} and did not refuse — this case is green over an arm that is not what makes the flag work: $(tr '\n' '|' <"$OUT")"
        fi
    fi

    CURRENT="the --store-durations arm"
    # The usage refusal still names the flag, so a reader who mistypes is sent
    # somewhere. Read as text on purpose: this is a claim about a SENTENCE, and
    # the executed run above is the claim about the behaviour.
    if grep -q -- '--store-durations, --bank' "$file"; then
        ok "the unknown-argument refusal lists it, so it is not a flag only the source knows about"
    else
        bad "the usage refusal does not name --store-durations"
    fi
}

case_every_registered_drive_member_resolves_to_a_file() {
    # ONE READER OF BOTH DRIVE HOMES. The always-on leg runs a member
    # by NAME and has to turn that name into a file; `selftest_registered_drives`
    # is the one place that knows where a drive lives, and it registers two
    # homes — every `scripts/tests/test_*.sh` plus the named
    # `deploy/tests/test_stage.sh`. `always_on__drive_file` used to compose
    # `scripts/tests/test_<name>.sh` for all of them, so on f800ab5b:
    #
    #   MISS stage  -> scripts/tests/test_stage.sh (No such file)
    #
    # and that member could only ever report `could not look`, naming a path
    # that has never existed. It was LATENT because the unreachable
    # `--store-durations` mode arm kept the durations
    # file from naming `stage`; the same rung fixes the flag, so the two land
    # together.
    CURRENT="every registered drive resolves to a file"
    OUT=""
    local file="${ROOT}/scripts/check.sh" reg="${WORK}/registry.sh" fn

    # BOTH FUNCTIONS ARE EXTRACTED BY NAME AND RUN — the way test_list_legs.sh
    # reads the registry — so the population and the composition are the
    # gate's own and there is no copy here to drift. Not the whole always-on
    # fence: this case drives two functions and must be able to drive them in
    # a scratch tree that has none of the fence's ledger libraries.
    : >"$reg"
    for fn in selftest_registered_drives always_on__drive_file; do
        awk -v want="${fn}() {" '
            index($0, want) == 1 { on = 1 }
            on { print }
            on && $0 == "}" { exit }
        ' "$file" >>"$reg"
        if ! grep -q "^${fn}() {" "$reg"; then
            bad "scripts/check.sh no longer defines ${fn}() at column 1 — this case has lost its subject"
            return
        fi
    done
    if [ "$(grep -c '^}$' "$reg")" != "2" ]; then
        bad "one of the two extracted functions has no column-1 closing brace — the extraction cannot be trusted"
        return
    fi

    # walk <dir> — every registered name, its composed path, and whether that
    # path is a file. Printed as `<name> <path> <ok|MISSING>` so both the
    # assertion and the failure message read off one transcript.
    walk() {
        local dir=$1 label=$2
        OUT="${WORK}/registry-walk-${label}.out"
        RC=0
        (
            set +e
            cd "$dir" || exit 2
            unset DJB_SELFTEST_DRIVES_DIR
            # shellcheck disable=SC1090  # the extracted registry and composer, by design
            . "$reg"
            selftest_registered_drives | while IFS= read -r name; do
                [ -n "$name" ] || continue
                path=$(always_on__drive_file "$name")
                if [ -f "$path" ]; then
                    printf '%s %s ok\n' "$name" "$path"
                else
                    printf '%s %s MISSING\n' "$name" "$path"
                fi
            done
        ) >"$OUT" 2>&1 || RC=$?
    }

    walk "$ROOT" tree
    local total missing
    total=$(awk 'END { print NR + 0 }' "$OUT")
    missing=$(awk '$3 == "MISSING" { print $1 }' "$OUT" | tr '\n' ' ')
    # A FLOOR THAT NAMES ITS POPULATION, not a reach kind: this tree registers
    # drives in TWO homes, and a walk that found only one home's members would
    # be green by arithmetic. Both are asserted below by name.
    if [ "$total" -lt 2 ]; then
        bad "the registry named ${total} drive(s) — every assertion below would be green over nothing"
        return
    fi
    if [ -z "$missing" ]; then
        ok "${total} registered drive(s), every one of them a file on this tree"
    else
        bad "${total} registered, and these resolve to nothing: ${missing}— the leg can only report could-not-look for them"
    fi

    CURRENT="and the second home is one of them"
    local stage_path
    stage_path=$(awk '$1 == "stage" { print $2; exit }' "$OUT")
    if [ "$stage_path" = "deploy/tests/test_stage.sh" ]; then
        ok "stage -> ${stage_path} (the deploy home, not scripts/tests/)"
    elif [ -z "$stage_path" ]; then
        bad "the registry names no 'stage' member — the deploy-home widening is gone and this case is green over one home"
    else
        bad "stage -> ${stage_path}; wanted deploy/tests/test_stage.sh"
    fi

    CURRENT="and a registered member with no file is SEEN (the plant)"
    # ITS OWN VICTIM: a scratch tree whose `scripts/check.sh` is nothing but
    # three column-zero registration lines. The registry reads `scripts/check.sh`
    # relative to the cwd, so this drives the real functions over a planted
    # population — one member in each home that exists, and one that does not.
    local plant="${WORK}/registry-plant"
    rm -rf "$plant"
    mkdir -p "${plant}/scripts/tests" "${plant}/deploy/tests"
    {
        printf './scripts/tests/test_real.sh\n'
        printf './scripts/tests/test_ghost.sh\n'
        printf './deploy/tests/test_stage.sh\n'
    } >"${plant}/scripts/check.sh"
    : >"${plant}/scripts/tests/test_real.sh"
    : >"${plant}/deploy/tests/test_stage.sh"
    walk "$plant" plant
    local want_ghost want_real want_stage
    want_ghost=$(awk '$1 == "ghost" { print $2, $3; exit }' "$OUT")
    want_real=$(awk '$1 == "real" { print $3; exit }' "$OUT")
    want_stage=$(awk '$1 == "stage" { print $2, $3; exit }' "$OUT")
    if [ "$want_ghost" = "scripts/tests/test_ghost.sh MISSING" ] &&
        [ "$want_real" = "ok" ] &&
        [ "$want_stage" = "deploy/tests/test_stage.sh ok" ]; then
        ok "the plant's ghost is MISSING, its two real members resolve — this case can fail, and it reads both homes"
    else
        bad "the plant read back ghost=[${want_ghost}] real=[${want_real}] stage=[${want_stage}]: $(tr '\n' '|' <"$OUT")"
    fi
    rm -rf "$plant"
}


# --- the cases: the per-rung gate runs on a box -------------------------------
#
# THE GUARD IS STRAIGHT-LINE CODE INSIDE ITS OWN FENCE, so it is driven the way
# the always-on leg is: extracted between its sentinels and SOURCED in a
# subshell with `MODE` set to the mode under test. Sourcing it runs it, and its
# `exit 2` ends the subshell — which is the whole behaviour, with nothing
# copied here to drift.
BOX_SENT_OPEN="# >>> loop-""here >>>"
BOX_SENT_CLOSE="# <<< loop-""here <<<"
BOX_BODY="${WORK}/loop_here.sh"

box_extract() {
    sed -n "/^${BOX_SENT_OPEN}\$/,/^${BOX_SENT_CLOSE}\$/p" \
        "${ROOT}/scripts/check.sh" >"$BOX_BODY" 2>/dev/null || true
    [ -s "$BOX_BODY" ] || return 1
    grep -q '^gate_on_verifier_box() {' "$BOX_BODY" || return 1
    return 0
}

# box_run <mode> <markers> <valve> — source the guard and report what it did.
box_run() {
    BOX_OUT="${WORK}/loop-here.out"
    BOX_RC=0
    (
        set -u
        MODE="$1"
        DJB_GATE_BOX_MARKERS="$2"
        export DJB_GATE_BOX_MARKERS
        if [ -n "$3" ]; then
            DJB_LOOP_HERE="$3"
            export DJB_LOOP_HERE
        fi
        # THE LEDGER THE GUARD CONSULTS IS THE CASE'S, NEVER THE REAL ONE: off a
        # box the guard first asks the loop ledger whether a BOX measured this
        # tree, and the real ledger is shared by every worktree — a box row for
        # this checkout's tree there would turn the refusal below into a hit.
        DJB_LOOP_LEDGER="${BOX_LEDGER:-${WORK}/no-loop-ledger-here}"
        export DJB_LOOP_LEDGER
        . "$BOX_BODY"
        printf 'PERMITTED because=[%s]\n' "$LOOP_HERE_BECAUSE"
    ) >"$BOX_OUT" 2>&1 || BOX_RC=$?
}

box_says() {
    if grep -qF -- "$1" "$BOX_OUT"; then
        ok "it says \"$1\""
    else
        bad "it does not say \"$1\"; it said: $(tr '\n' '|' <"$BOX_OUT")"
    fi
}

case_a_loop_that_is_not_on_a_box_refuses_and_prints_the_recipe() {
    CURRENT="the --loop box guard"
    OUT=""
    if ! box_extract; then
        bad "scripts/check.sh has no \`${BOX_SENT_OPEN}\` fence defining gate_on_verifier_box — the guard does not exist (which is what the baseline looks like, and what a laptop --loop runs on)"
        return
    fi
    ok "the guard extracted from scripts/check.sh between its own sentinels"
    local absent="${WORK}/no-such-marker-anywhere"
    rm -rf "$absent"

    # OFF A BOX, NO VALVE: exit 2, and the reader is told what to run.
    box_run "--loop" "$absent" ""
    is "$BOX_RC" "2" "the exit off a box with no valve"
    box_says "REFUSING a --loop on a machine that is not a verifier box"
    box_says "./scripts/verifier_box.sh up --for <rung>"
    box_says "./scripts/verifier_box.sh loop <id> --log loop-<rung>"
    box_says "./scripts/verifier_box.sh wait <id> loop-<rung>"
    box_says "./scripts/verifier_box.sh down <id>"
    box_says 'DJB_LOOP_HERE="<rung-id>: <reason>"'
    box_says "Nothing was judged"

    # ON A BOX: it runs, with no valve, and NAMES THE MARKER that answered.
    # Neither real marker can be planted on a laptop without root, so this is
    # the one branch nothing else could ever drive — and a guard whose
    # permitting branch has never fired is a guard that may be unable to permit.
    local marker="${WORK}/planted-box-marker"
    : >"$marker"
    box_run "--loop" "$marker" ""
    is "$BOX_RC" "0" "the exit on a box with no valve"
    box_says "PERMITTED because=[a verifier box (${marker})]"

    # THE SECOND MARKER ANSWERS TOO, and the list is walked rather than the
    # first entry read: an image that stops creating a runtime directory must
    # still be able to say what it is.
    box_run "--loop" "${absent} ${marker}" ""
    is "$BOX_RC" "0" "the exit when the SECOND marker is the one that exists"
    box_says "PERMITTED because=[a verifier box (${marker})]"

    # THE VALVE: off a box, with a reason, it runs and the reason is carried.
    box_run "--loop" "$absent" "x-1: no AWS credentials in this session"
    is "$BOX_RC" "0" "the exit off a box with a typed reason"
    box_says "PERMITTED because=[DJB_LOOP_HERE=x-1: no AWS credentials in this session]"

    # A VALVE THAT NAMES NOBODY IS NOT A REASON — the sanction's own grammar,
    # and its own refusal, so a typo is a broken invocation rather than a
    # silent fall-through wearing the generic sentence.
    box_run "--loop" "$absent" "because"
    is "$BOX_RC" "2" "the exit with a shapeless valve"
    box_says "DJB_LOOP_HERE is set but is not a reason"
    box_says 'want: DJB_LOOP_HERE="<rung-id>: <reason>"'
    if grep -qF 'REFUSING a --loop on a machine' "$BOX_OUT"; then
        bad "a shapeless valve fell through to the generic refusal — the typo is hidden behind another sentence"
    else
        ok "a shapeless valve is refused as a typo, not as an absent one"
    fi

    # EVERY OTHER MODE IS UNTOUCHED, and `--fast` is the one that matters: it
    # is the pre-commit hook, which must stay a local thing costing seconds.
    local m
    for m in "--fast" "--census" ""; do
        box_run "$m" "$absent" ""
        if [ "$BOX_RC" != "0" ]; then
            bad "mode '${m:-<full>}' was refused by the loop guard (exit ${BOX_RC})"
            return
        fi
        if ! grep -qF 'PERMITTED because=[]' "$BOX_OUT"; then
            bad "mode '${m:-<full>}' set a reason: $(tr '\n' '|' <"$BOX_OUT")"
            return
        fi
    done
    ok "--fast, --census and the full mode pass through the guard untouched and set no reason"
}

# A BOX MAY ALREADY HAVE MEASURED THESE BYTES. `verifier_box.sh wait` brings a
# green box loop's row home with ` box=<id>`; off a box, the guard asks the loop
# ledger for a BOX row at this checkout's measured tree before it refuses, and a
# hit is exit 0 naming the row. A row with no ` box=` (this machine's own, under
# a valve) is not a box's and the refusal stands; DJB_LOOP_NO_CACHE never
# consults.
case_a_laptop_loop_on_bytes_a_box_measured_prints_the_hit() {
    CURRENT="the laptop's consult by tree"
    OUT=""
    if ! box_extract; then
        bad "scripts/check.sh has no loop-here fence"
        return
    fi
    local absent="${WORK}/no-such-marker-anywhere" tree key
    rm -rf "$absent"
    tree=$( (. scripts/gate_ledger.sh >/dev/null 2>&1 && gate_measured_tree) 2>/dev/null) || tree=""
    [ -n "$tree" ] || cannot_look "gate_measured_tree would not answer in ${ROOT}"
    key="loop-v1:$(printf 'b%.0s' $(seq 1 64))"
    BOX_LEDGER="${WORK}/box-ledger-hit"
    printf 'loop-v1 %s loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1 tree=%s env=x box=i-zzzbox\n' \
        "$key" "$tree" >"$BOX_LEDGER"
    box_run "--loop" "$absent" ""
    is "$BOX_RC" "0" "the exit off a box, over bytes a box measured"
    box_says "ok: --loop VERDICT HELD BY A BOX"
    box_says "  box    i-zzzbox  banked 2026-09-27T10:00:00Z"
    box_says "  key    ${key}"
    if grep -qF 'REFUSING a --loop' "$BOX_OUT"; then
        bad "a hit still printed the refusal"
    else
        ok "a hit prints no refusal"
    fi

    CURRENT="a row with no box= is not a box's"
    BOX_LEDGER="${WORK}/box-ledger-local"
    printf 'loop-v1 %s loop 2026-09-27T10:00:00Z caller=unstated scope=mode=fast passes=1 tree=%s env=x\n' \
        "$key" "$tree" >"$BOX_LEDGER"
    box_run "--loop" "$absent" ""
    is "$BOX_RC" "2" "the exit over a row this machine banked"
    box_says "REFUSING a --loop on a machine that is not a verifier box"

    CURRENT="DJB_LOOP_NO_CACHE never consults"
    BOX_LEDGER="${WORK}/box-ledger-hit"
    DJB_LOOP_NO_CACHE=1 box_run "--loop" "$absent" ""
    is "$BOX_RC" "2" "the exit with DJB_LOOP_NO_CACHE over a box row"
    box_says "REFUSING a --loop on a machine that is not a verifier box"
    BOX_LEDGER=""
}

case_the_box_guard_is_wired_above_everything_it_would_cost() {
    # A GUARD THAT QUEUED FOR AN HOUR AND THEN SAID NO would be an expensive way
    # to learn about a missing marker. It has to sit above the lease, the lock,
    # the slot and the scope derivation — and the reason it permits has to reach
    # a reader, both at the top of the run and beside the banked verdict.
    CURRENT="the box guard's position and its two prints"
    OUT=""
    local file="${ROOT}/scripts/check.sh" guard lock scope banked
    guard=$(grep -n '^if \[ "\$MODE" = "--loop" \]; then$' "$file" | sed -n '1p' | cut -d: -f1)
    lock=$(grep -n '^    gate_lock_refuse_if_held$' "$file" | sed -n '1p' | cut -d: -f1)
    scope=$(grep -n '^# --- the --loop scope, and the verdict' "$file" | sed -n '1p' | cut -d: -f1)
    if [ -z "$guard" ] || [ -z "$lock" ] || [ -z "$scope" ]; then
        bad "the guard (${guard:-none}), the lock refusal (${lock:-none}) or the scope block (${scope:-none}) is not in check.sh"
        return
    fi
    if [ "$guard" -lt "$lock" ] && [ "$guard" -lt "$scope" ]; then
        ok "the guard is at :${guard}, above the lock refusal (:${lock}) and the scope derivation (:${scope})"
    else
        bad "the guard is at :${guard}, below the lock refusal (:${lock}) or the scope derivation (:${scope}) — a refused run would already have paid"
    fi
    if grep -q '^        echo "- loop here: ' "$file"; then
        ok "the reason is printed before the first leg"
    else
        bad "no '- loop here:' banner — a default overridden in silence is an override nobody audits"
    fi
    banked=$(grep -c '          here=\${LOOP_HERE_BECAUSE}' "$file" | tr -d ' ')
    is "$banked" "1" "the number of places the reason is printed beside the banked verdict"
}

case_every_declared_organ_kind_is_derived_on_this_tree
case_a_planted_organ_fixture_test_joins_the_slow_tier_with_no_list_edit
case_a_planted_module_naming_the_temporal_entry_point_joins_the_slow_tier
case_a_planted_test_reaching_nothing_stays_fast
case_the_plants_leave_when_they_are_removed
case_the_fast_tier_deselects_the_slow_one_and_says_so
case_an_own_app_keeps_its_own_organ_tests_in_the_rung
case_an_unmet_floor_refuses_rather_than_running_a_tier_it_cannot_vouch_for
case_the_default_tier_touches_nothing
case_a_change_under_an_app_derives_that_app
case_two_apps_both_derive
case_an_untracked_new_file_derives_nothing_until_it_is_staged
case_a_committed_change_on_a_branch_derives_too
case_a_system_layer_rung_derives_no_own_app
case_a_shared_conftest_change_runs_the_full_suite
case_a_root_conftest_change_runs_the_full_suite
case_a_conftest_outside_apps_runs_the_full_suite
case_an_apps_root_test_module_runs_the_full_suite
case_a_gate_drive_change_runs_the_full_suite
case_the_tiers_own_derivation_runs_the_full_suite
case_an_apps_own_conftest_is_not_shared
case_shared_infra_outranks_an_app_change
case_an_app_change_alone_still_gets_the_fast_tier
case_no_git_is_could_not_look
case_the_tier_is_wired_into_the_loop_leg
case_the_full_gate_leg_carries_no_tier
case_a_marked_census_is_always_on_at_an_empty_scope
case_the_always_digest_moves_with_the_rule_not_with_a_marker
case_the_loop_banner_names_each_declared_census
case_a_declared_population_reaches_the_banner_and_an_empty_one_refuses
case_the_always_on_leg_derives_its_members_from_the_durations_file
case_a_full_only_red_reds_the_loop
case_no_durations_file_runs_only_the_declared_censuses
case_an_unknown_member_in_the_file_is_exit_2
case_a_marked_drive_runs_in_the_loop_at_every_scope
case_a_banked_member_is_reused_and_a_moved_input_is_not
case_the_canonical_scope_carries_the_always_on_inputs
case_the_always_on_leg_is_wired_into_the_loop
case_the_measurement_writes_a_file_its_own_reader_can_read
case_the_measurement_flag_belongs_to_the_full_mode_alone
case_every_registered_drive_member_resolves_to_a_file
case_a_loop_that_is_not_on_a_box_refuses_and_prints_the_recipe
case_a_laptop_loop_on_bytes_a_box_measured_prints_the_hit
case_the_box_guard_is_wired_above_everything_it_would_cost

echo "test_loop_tier: ${PASSED} passed · ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the --loop pytest tier no longer derives — or no longer declares — the" >&2
    echo "   population it skips. Every failure mode of this derivation is silent: a" >&2
    echo "   tier that deselects nothing is a slow loop nobody diagnoses, and a tier" >&2
    echo "   that deselects an organ it stopped seeing is a green loop that vouched" >&2
    echo "   for less than it said." >&2
    exit 1
fi
exit 0
