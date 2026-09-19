#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh.
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
# drives: docs/product/in-flight.md docs/product/queue.md scripts/archaeology_lib.sh scripts/check.sh scripts/secrets_scan.sh
# The drive for `archaeology_loop` (scripts/archaeology_lib.sh) — the
# `--loop` per-rung `archaeology` leg body.
#
#   ./scripts/tests/test_archaeology_loop.sh          run every case
#   ./scripts/tests/test_archaeology_loop.sh --list   name them and stop
#
# WHY IT EXISTS. `publish.sh`'s release-time archaeology-census is proven by
# `test_publish.sh` already; this drive is the per-rung leg's OWN proof,
# because the leg is not merely "the same six patterns" — it is those six
# patterns PLUS a narrowing (changed files, not the whole tree) PLUS a
# classifier (bucket SHIP only) that publish.sh's leg does not carry at all.
# The classifier is the hazard this drive exists to make checkable: the wave's
# hand-up named it explicitly — "the bucket classifier is NON-optional" — and
# a classifier nobody drives can be narrowed to nothing by a later edit
# without a single case here noticing.
#
# IT BUILDS ITS OWN REPOSITORY, `test_secrets_scan.sh`'s trick and for its
# reason: `archaeology_loop` calls `secrets_scan_changed_files`, whose whole
# subject is branches, merge-bases and diffs, none of which can be arranged
# in this checkout without moving somebody's rung. Every case runs against a
# throwaway git repository under `mktemp -d`, in the UNBORN-HEAD shape
# (nothing committed, only staged) — the simplest of `secrets_scan_changed_
# files`' branches and the one every case here actually needs, since the
# question under test is the SIX PATTERNS and the BUCKET FILTER, not the
# changed-file derivation itself (that derivation's own edge cases are
# test_secrets_scan.sh's).
#
# THE NEGATIVE CASE IS THE ONE THAT MATTERS MOST (`case_skeleton_bucket_
# stays_silent`): a changed SKELETON file — the shape every PM ledger update
# actually is — FULL of finding ids and rung tokens must not redden. Every
# commit this very platform's own PM loop makes to docs/product/queue.md or
# docs/product/in-flight.md is exactly this shape, so a classifier that
# regressed here would redden the per-rung gate on literally every ledger
# commit going forward.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#   * THE CHANGED-FILE DERIVATION ITSELF — its branches, its merge-base
#     arithmetic, its unborn-HEAD and empty-diff edge cases are
#     test_secrets_scan.sh's, driven once there rather than a second time
#     here.
#   * THE FULL-TREE SCAN. `archaeology_scan_tree` (publish.sh's own leg) is
#     test_publish.sh's "leg archaeology-census" section.
#   * TIMING AS AN ASSERTION. This drive PRINTS the wall time of a
#     representative run (criterion 5's "sub-second" claim); it does not
#     fail a case on a threshold, because a shared, loaded box turns a timing
#     assertion into a flake that teaches the next reader to ignore it.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_archaeology_loop: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0
CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}
cannot_look() {
    echo "!! test_archaeology_loop: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_archaeology_loop.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/archaeology_lib.sh ] || cannot_look "scripts/archaeology_lib.sh is not in this tree"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree"
ROOT="$PWD"
# shellcheck source=scripts/archaeology_lib.sh
. "$ROOT/scripts/archaeology_lib.sh"
# shellcheck source=scripts/secrets_scan.sh
. "$ROOT/scripts/secrets_scan.sh"
command -v archaeology_loop >/dev/null 2>&1 || cannot_look "scripts/archaeology_lib.sh defines no archaeology_loop — the body is gone"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-arch-loop.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

REPO=""
fresh_repo() {
    REPO="${WORK}/repo-$$-$RANDOM"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/apps/example" "$REPO/scripts" "$REPO/docs/product"
    (cd "$REPO" && git init -q -b main)
}

RUN_OUT=""
run_loop() {
    RUN_OUT="${WORK}/run-$$-$RANDOM.log"
    set +e
    (cd "$REPO" && archaeology_loop) >"$RUN_OUT" 2>&1
    RC=$?
    set -e
}

show_out() { sed 's/^/             | /' "$RUN_OUT"; }

# assembled halves, exactly the discipline archaeology_lib.sh itself uses —
# this drive is a shipped file (bucket R3) and archaeology_scan_files reads
# the whole tree including its own author's fixtures.
PLANT_N="N""347"
PLANT_RUNG="P""9-2"
PLANT_NARRATIVE="PROVE""-1"
PLANT_PRIVATE="Att""icus"
PLANT_BRAND="Django""Bootstrap"
PLANT_COORD="pilecap""-staging"

# --- cases 1-6: each pattern fires on a changed bucket-SHIP file ------------
for spec in \
    "finding-id:$PLANT_N" \
    "rung-token:$PLANT_RUNG" \
    "narrative:$PLANT_NARRATIVE" \
    "private-name:$PLANT_PRIVATE" \
    "former-brand:$PLANT_BRAND" \
    "deploy-coordinate:$PLANT_COORD"; do
    label=${spec%%:*}
    token=${spec#*:}
    CURRENT="pattern $label fires on a changed SHIP file"
    fresh_repo
    printf '# a plant: %s\n' "$token" >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "1" ] &&
        grep -qE "archaeology-census: scripts/plant\.sh:[0-9]+  $label" "$RUN_OUT" &&
        grep -qF "\"$token\"" "$RUN_OUT"; then
        ok "exit 1, naming scripts/plant.sh and \"$token\""
    else
        bad "exit $RC, want 1 naming scripts/plant.sh and \"$token\""
        show_out
    fi
done

# --- case 7: allow-listed forms stay silent ---------------------------------
case_allowlisted_forms_stay_silent() {
    CURRENT="allow-listed forms"
    fresh_repo
    {
        printf 'Pilecap ships its own name.\n'
        printf 'the stack is `name: %s`\n' "django""bootstrap"
    } >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0, no VIOLATION line"
    else
        bad "exit $RC, want 0 and silent"
        show_out
    fi
}

# --- case 8: THE BUCKET CLASSIFIER IS NOT OPTIONAL --------------------------
case_skeleton_bucket_stays_silent() {
    CURRENT="a changed SKELETON file full of finding ids and rung tokens"
    fresh_repo
    printf '| %s | %s | done | %s |\n' "$PLANT_N" "$PLANT_RUNG" "$PLANT_NARRATIVE" \
        >"$REPO/docs/product/queue.md"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "0" ] && grep -q "NOTHING TO SCAN" "$RUN_OUT"; then
        ok "exit 0 — a PM ledger row citing a finding id is expected vocabulary, not archaeology"
    else
        bad "exit $RC, want 0 (NOTHING TO SCAN) — the bucket classifier must exclude SKELETON files"
        show_out
    fi
}

# --- case 9: a SHIP file beside the SKELETON one is still scanned -----------
case_ship_file_beside_skeleton_still_scanned() {
    CURRENT="a SHIP file changed alongside a SKELETON file"
    fresh_repo
    printf '| %s |\n' "$PLANT_N" >"$REPO/docs/product/queue.md"
    printf 'this %s\n' "rung" >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "1" ] && grep -q "archaeology-census: scripts/plant.sh" "$RUN_OUT" &&
        ! grep -q "queue.md" "$RUN_OUT"; then
        ok "exit 1 naming only scripts/plant.sh — the SKELETON file never appears in the finding"
    else
        bad "exit $RC — want 1 naming scripts/plant.sh and never queue.md"
        show_out
    fi
}

# --- case 10: nothing changed at all ----------------------------------------
case_nothing_changed() {
    CURRENT="no changed files"
    fresh_repo
    printf '# nothing archaeological here\n' >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m base)
    run_loop
    if [ "$RC" = "0" ] && grep -q "NOTHING TO SCAN" "$RUN_OUT"; then
        ok "exit 0 (NOTHING TO SCAN) — a committed, unchanged tree has nothing for this leg to read"
    else
        bad "exit $RC, want 0 (NOTHING TO SCAN)"
        show_out
    fi
}

# --- case 11: could-not-look — the changed-file derivation itself refuses --
case_could_not_look_no_git() {
    CURRENT="not a git checkout"
    REPO="${WORK}/not-a-repo-$$-$RANDOM"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    run_loop
    if [ "$RC" = "2" ]; then
        ok "exit 2 — an underived changed-file set is not an empty one"
    else
        bad "exit $RC, want 2"
        show_out
    fi
}

# --- case 12: sub-second, printed rather than asserted ----------------------
case_timing_printed() {
    CURRENT="wall time (printed, not asserted)"
    fresh_repo
    printf '# nothing archaeological\n' >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    local t0 t1
    t0=$(date +%s%N 2>/dev/null || date +%s)
    run_loop
    t1=$(date +%s%N 2>/dev/null || date +%s)
    if [ "${#t0}" -gt 10 ]; then
        echo "  measured: $(((t1 - t0) / 1000000))ms (one changed file, one repo — this drive's own"
        echo "            overhead, not a measurement of the real rung's changed-file count)"
    fi
    if [ "$RC" = "0" ]; then
        ok "ran to completion (see the printed ms line above)"
    else
        bad "exit $RC, want 0"
        show_out
    fi
}

# --- case 13: the tier the HOOK runs -----------------------------------------
case_a_planted_id_in_a_ship_bucket_comment_reds_fast() {
    # THE MISS THIS CASE EXISTS FOR. The census ran one tier up, in the per-rung
    # gate — and the per-rung gate is not what stands between a maintainer's
    # shorthand and a commit. Pre-commit runs the fast tier, so the shorthand
    # went in through the hook, passed, and was met minutes later by a loop run,
    # which is a scrub commit and a re-run per occurrence. Five of six builders
    # in one wave paid it on the same night.
    #
    # THE SHAPE THAT DID IT is exactly this: a maintainer's comment carrying a
    # ledger row id AND the method's narrative vocabulary, in a file that ships.
    # Both patterns must name the file, because a leg that reports one of two
    # findings teaches its reader to scrub once and commit again.
    #
    # WHICH HALF OF THE SHIPPED LEG THIS CASE DOES NOT REACH, said here rather
    # than discovered: it runs the leg BODY the way the fast tier runs it, not
    # `./scripts/check.sh --fast` itself. A nested gate is not available to a
    # drive — the drives run inside the full gate's self-test leg, and a full
    # gate holds the per-checkout lock that makes any other gate in the same
    # checkout refuse (exit 2), so a case invoking it would pass in isolation
    # and could-not-look in the run that matters. The WIRING is what joins body
    # to tier, and the case below is the one that proves it.
    CURRENT="a finding id and a narrative phrase in a changed SHIP file"
    fresh_repo
    printf '# see %s%s and this %s\n' "N" "999" "rung" >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "1" ] &&
        grep -qE "archaeology-census: scripts/plant\.sh:[0-9]+  finding-id" "$RUN_OUT" &&
        grep -qE "archaeology-census: scripts/plant\.sh:[0-9]+  narrative" "$RUN_OUT"; then
        ok "exit 1, naming scripts/plant.sh for BOTH patterns — the shape the hook used to pass"
    else
        bad "exit $RC, want 1 naming scripts/plant.sh for finding-id AND narrative"
        show_out
    fi
}

# --- case 14: ONE call site, and it is in the fast tier -----------------------
case_fast_wires_the_archaeology_leg_and_loop_does_not_run_it_twice() {
    # A LEG THAT EXISTS AND IS NOT CALLED IS THE FAILURE THE BODY CASES CANNOT
    # SEE. Every case above proves what `archaeology_loop` does; none of them
    # proves that anything runs it, or that it runs in the tier the hook
    # reaches. This case reads check.sh.
    #
    # AND EXACTLY ONE CALL SITE, which is the other half. The per-rung tier runs
    # the fast tier's legs first, so a copy left behind in the per-rung block
    # would scan the same files a second time in the same run — a duplicate, in
    # the one leg whose entire subject is duplicated history.
    CURRENT="the archaeology leg's call site in check.sh"
    local n first fast_at exit_at
    n=$(grep -cE '^[[:space:]]*archaeology_loop[[:space:]]*$' "$ROOT/scripts/check.sh" || true)
    if [ "$n" = "1" ]; then
        ok "exactly one call site (a comment naming the function is not a call, so the count is anchored)"
    else
        bad "${n} call sites for archaeology_loop in check.sh, want exactly 1"
    fi

    CURRENT="and it is inside the fast tier's legs"
    # `|| true` on every one: an anchor that is GONE is a could-not-look, which
    # the check below reports as one. Without it `pipefail` turns a missing
    # anchor into the drive dying mid-case with no verdict at all.
    # `awk` reads its input to the end — no early-exit reader, no SIGPIPE.
    first=$(grep -nE '^[[:space:]]*archaeology_loop[[:space:]]*$' "$ROOT/scripts/check.sh" | awk -F: 'NR==1{print $1}' || true)
    fast_at=$(grep -n '^# --- the --fast legs' "$ROOT/scripts/check.sh" | awk -F: 'NR==1{print $1}' || true)
    exit_at=$(grep -n '^if \[ "\$MODE" = "--fast" \]; then' "$ROOT/scripts/check.sh" | awk -F: 'NR==1{print $1}' || true)
    if [ -z "$first" ] || [ -z "$fast_at" ] || [ -z "$exit_at" ]; then
        cannot_look "check.sh no longer carries the anchors this case reads (call=${first:-none} fast=${fast_at:-none} exit=${exit_at:-none})"
    fi
    if [ "$first" -gt "$fast_at" ] && [ "$first" -lt "$exit_at" ]; then
        ok "the call sits at :${first}, between the fast tier's header (:${fast_at}) and its exit (:${exit_at}) — so the hook runs it"
    else
        bad "the call sits at :${first}, outside the fast tier's legs (:${fast_at}..:${exit_at}) — the hook does not run it"
    fi

    CURRENT="and a could-not-derive is exit 2, not a silent pass"
    if grep -q 'the archaeology-census leg COULD NOT DERIVE' "$ROOT/scripts/check.sh"; then
        ok "an underived changed-file set stops the gate rather than reading as clean"
    else
        bad "no could-not-look branch on the archaeology leg"
    fi
}

case_allowlisted_forms_stay_silent
case_skeleton_bucket_stays_silent
case_ship_file_beside_skeleton_still_scanned
case_nothing_changed
case_could_not_look_no_git
case_timing_printed
# --- case 15: the thin basis is a narrower look, never a refusal -------------
case_fast_on_a_thin_basis_scans_the_uncommitted_set_and_says_so() {
    # THE TIER MOVE PUT THIS LEG IN FRONT OF EVERY COMMIT IN EVERY CHECKOUT,
    # including the ones whose git shape the leg's derivation has the least to
    # work with: a repository with no local `refs/heads/main` to fork from. The
    # derivation has a legal answer for that — scan the uncommitted set and SAY
    # that is all it scanned — and the danger of moving a leg into the hook is
    # that this answer becomes a REFUSAL, which would red every commit in such a
    # checkout for a shape nobody can fix from inside it.
    #
    # AND THE BASIS IS PRINTED, which is the half that keeps the green honest: a
    # narrowed scan that does not say what it narrowed to is a reader taking "no
    # findings" for "the tree is clean".
    CURRENT="no local refs/heads/main"
    REPO="${WORK}/thin-$$-$RANDOM"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/scripts" "$REPO/docs/product"
    (
        cd "$REPO" &&
            git init -q -b elsewhere &&
            printf '# nothing archaeological\n' >scripts/base.sh &&
            git add -A &&
            git -c user.name=t -c user.email=t@t commit -q -m base
    )
    # An UNCOMMITTED change, which is the only thing this basis may see.
    printf '# a plant: %s%s\n' "N" "999" >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "1" ] && grep -q "no local refs/heads/main to fork from" "$RUN_OUT" &&
        grep -q "archaeology-census: scripts/plant.sh" "$RUN_OUT"; then
        ok "exit 1 over the uncommitted set, with the thin basis printed — a narrower look, not a refusal"
    else
        bad "exit $RC — want 1, the basis line, and the plant named"
        show_out
    fi

    CURRENT="and a clean uncommitted set on the same basis is a pass"
    printf '# nothing archaeological\n' >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_loop
    if [ "$RC" = "0" ] && grep -q "no local refs/heads/main to fork from" "$RUN_OUT"; then
        ok "exit 0, and the basis is still printed rather than assumed"
    else
        bad "exit $RC, want 0 with the basis printed"
        show_out
    fi
}

case_a_planted_id_in_a_ship_bucket_comment_reds_fast
case_fast_wires_the_archaeology_leg_and_loop_does_not_run_it_twice
case_fast_on_a_thin_basis_scans_the_uncommitted_set_and_says_so

echo
echo "test_archaeology_loop: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
