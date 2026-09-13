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

remove_plants() {
    rm -f "${ROOT}/${PLANT_ORGAN}" "${ROOT}/${PLANT_TEMPORAL}" "${ROOT}/${PLANT_PLAIN}"
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
