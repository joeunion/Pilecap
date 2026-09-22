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
# drives: apps/example/models.py docs/product/queue.md quality/worlds.py scripts/fe_gate.sh scripts/goalpost_scan.py scripts/secrets_scan.sh
# The 10-case leg-machinery harness for scripts/fe_gate.sh — the `fe` leg's
# tri-state (absent/untouched/full) and the mode that decides which of them
# is reachable.
#
#   ./scripts/tests/test_fe_leg.sh          run every case
#   ./scripts/tests/test_fe_leg.sh --list   name them and stop
#
# WHY IT EXISTS, AND WHY IT IS FIXTURE-ONLY. This template ships with no
# frontend/ at all — that is the steady state the tri-state exists to make
# free, not a defect — so on the real tree `fe_leg_run` almost always takes
# the `absent` branch. A mechanism whose every live run takes the same branch
# is a mechanism nothing has proven can take the other two, and this drive is
# the proof: every case below builds its own scratch `frontend/`-shaped
# directory under `mktemp -d` and points `FE_FRONTEND_DIR` at it, so the
# three states — and the could-not-look cells inside `full` — are each
# demonstrated on purpose rather than waited for.
#
# THE FIRST NINE CASES, and why there are exactly nine of them: one for
# `absent`, one for `untouched` (proving pnpm is never even invoked there),
# and seven for `full` — because "the toolchain is present and the tree is
# well-formed" is not one fact, it is four (manifest exists, lockfile exists,
# the lockfile satisfies the manifest, the declared test script exits 0) and
# this drive demonstrates every one of the ways that chain can fail before it
# demonstrates the chain holding:
#
#   1. absent                                              -> exit 0, absent
#   2. present + untouched                                 -> exit 0, untouched, pnpm never invoked
#   3. present + touched, toolchain absent                 -> exit 2 (could-not-look)
#   4. present + touched, toolchain present, no manifest    -> exit 2 (could-not-look)
#   5. present + touched, toolchain present, no lockfile    -> exit 2 (could-not-look)
#   6. present + touched, lockfile MISMATCHES the manifest  -> exit 1 (criterion 3's target class)
#   7. present + touched, clean lockfile, no test script    -> exit 0, full
#   8. present + touched, clean lockfile, test script PASSES -> exit 0, full
#   9. present + touched, clean lockfile, test script FAILS  -> exit 1
#
# ALL NINE ARE ABOUT THE CHANGE-AWARE MODES, and every one of them calls
# `fe_leg_run` with ONE argument — which is that function's contract for an
# omitted mode. The TENTH case is about the mode itself: the
# `untouched`/`suspect` fast path is `--loop`'s and `--fast`'s alone, and
# under the full gate's `""` or one of its `--leg` shards the leg runs whole,
# because a bank writes a verdict row naming `fe` as a leg that ran. It is
# the one case here that drives a pnpm STUB rather than the real tool, and it
# says why at its own head.
#
# NEEDS A REAL pnpm for cases 6-9 (frozen-lockfile is driven against the real
# tool, not a shim of it — the target class is pnpm's own refusal, and a shim
# that merely returns the right exit code would prove this drive's plumbing
# and nothing about the actual check). Its absence here is a could-not-look,
# the same as it would be for the leg itself.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#   * WHETHER pnpm's OWN frozen-lockfile DETECTION IS CORRECT. That is pnpm's
#     business; this drives which DIRECTORY and which FLAGS the leg hands it,
#     and case 6 proves the leg is still wired to a real refusal rather than
#     that pnpm's detector is any good.
#   * A REAL package-manager SCRIPT WRAPPER's shape (a `pnpm-scripts`
#     instrument at mode 644 the goalpost census cannot see on its own — see
#     scripts/goalpost_scan.py's printed blind spot). Out of scope here: this
#     drive is the fe leg's tri-state, not the instrument census.
#   * THE LIVE TREE EVER TAKING THE `full` BRANCH. Declared in the module
#     header this drive tests: every case here is a fixture world.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_fe_leg: scripts/tests/drive_preamble.sh is not in this tree." >&2
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
    echo "!! test_fe_leg: $*" >&2
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
    echo "!! unknown argument '$1': test_fe_leg.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -f scripts/fe_gate.sh ] || cannot_look "scripts/fe_gate.sh is not in this tree — there is nothing to drive"
[ -f scripts/secrets_scan.sh ] || cannot_look "scripts/secrets_scan.sh is not in this tree — fe_leg_run needs its changed-file shape"
# shellcheck source=scripts/fe_gate.sh
. scripts/fe_gate.sh
command -v fe_leg_run >/dev/null 2>&1 || cannot_look "scripts/fe_gate.sh defines no fe_leg_run — the body is gone"
command -v pnpm >/dev/null 2>&1 || cannot_look "no pnpm on PATH — cases 6-9 drive the real frozen-lockfile refusal"

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-fe-leg.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# changed_list <path...> — writes a NUL-separated changed-file list, the
# exact shape secrets_scan_changed_files hands the leg.
CHANGED=""
changed_list() {
    CHANGED="${WORK}/changed-$$-$RANDOM"
    : >"$CHANGED"
    local p
    for p in "$@"; do
        printf '%s\0' "$p" >>"$CHANGED"
    done
}

# A minimal real pnpm project: one dependency, satisfied by its lockfile.
build_clean_frontend() {
    local dir=$1
    rm -rf "$dir"
    mkdir -p "$dir"
    cat >"$dir/package.json" <<'JSON'
{
  "name": "fe-leg-fixture",
  "private": true,
  "version": "0.0.0",
  "dependencies": {
    "left-pad": "1.3.0"
  }
}
JSON
    (cd "$dir" && pnpm install --lockfile-only --reporter=silent) >"${WORK}/pnpm-setup.log" 2>&1 ||
        cannot_look "could not build the clean fixture's lockfile — pnpm install --lockfile-only failed: $(cat "${WORK}/pnpm-setup.log")"
}

RUN_OUT=""
run_fe() {
    RUN_OUT="${WORK}/run-$$-$RANDOM.log"
    set +e
    fe_leg_run "$CHANGED" >"$RUN_OUT" 2>&1
    RC=$?
    set -e
}

# run_fe_mode <mode> — the same call WITH check.sh's own `$MODE` handed over,
# which is what the gate does. `run_fe` above passes ONE argument on purpose:
# an omitted mode is the change-aware contract the nine cases are about, and
# two other drives (`test_rung_tidy.sh`, `test_pm_fold.sh`) call it that way
# too. The distinction between an ABSENT second argument and an EMPTY one is
# load-bearing here — `""` IS a mode, the full gate's — so this helper always
# passes one.
run_fe_mode() {
    local mode=$1
    RUN_OUT="${WORK}/run-$$-$RANDOM.log"
    set +e
    fe_leg_run "$CHANGED" "$mode" >"$RUN_OUT" 2>&1
    RC=$?
    set -e
}

show_out() {
    sed 's/^/             | /' "$RUN_OUT"
}

# --- case 1: absent -----------------------------------------------------
case_absent() {
    CURRENT="absent"
    export FE_FRONTEND_DIR="${WORK}/no-such-frontend"
    rm -rf "$FE_FRONTEND_DIR"
    changed_list "apps/example/models.py"
    run_fe
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "absent" ] && grep -q "ABSENT" "$RUN_OUT"; then
        ok "exit 0, FE_LEG_STATE=absent, ABSENT printed"
    else
        bad "exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}, want exit 0 and absent"
        show_out
    fi
}

# --- case 2: present + untouched, pnpm never invoked ---------------------
case_untouched_pnpm_never_invoked() {
    CURRENT="present+untouched"
    export FE_FRONTEND_DIR="${WORK}/fe-untouched"
    build_clean_frontend "$FE_FRONTEND_DIR"
    changed_list "apps/example/models.py" "docs/product/queue.md"
    local marker="${WORK}/pnpm-was-called"
    rm -f "$marker"
    cat >"${WORK}/pnpm-tripwire" <<SH
#!/usr/bin/env bash
touch "$marker"
exit 1
SH
    chmod +x "${WORK}/pnpm-tripwire"
    export FE_PNPM="${WORK}/pnpm-tripwire"
    run_fe
    unset FE_PNPM
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "untouched" ] && [ ! -f "$marker" ]; then
        ok "exit 0, FE_LEG_STATE=untouched, the toolchain tripwire never fired"
    else
        bad "exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}, tripwire-fired=$([ -f "$marker" ] && echo yes || echo no)"
        show_out
    fi
}

# --- case 3: present + touched, toolchain absent --------------------------
case_touched_toolchain_absent() {
    CURRENT="present+touched, toolchain absent"
    export FE_FRONTEND_DIR="${WORK}/fe-full"
    build_clean_frontend "$FE_FRONTEND_DIR"
    changed_list "$FE_FRONTEND_DIR/package.json"
    export FE_PNPM="${WORK}/no-such-pnpm-binary"
    run_fe
    unset FE_PNPM
    if [ "$RC" = "2" ]; then
        ok "exit 2 (could-not-look) — the same cell quality/worlds.py's tree_verdict names broken"
    else
        bad "exit $RC, want 2"
        show_out
    fi
}

# --- case 4: full, no manifest ---------------------------------------------
case_full_no_manifest() {
    CURRENT="full, no package.json"
    export FE_FRONTEND_DIR="${WORK}/fe-no-manifest"
    rm -rf "$FE_FRONTEND_DIR"
    mkdir -p "$FE_FRONTEND_DIR"
    changed_list "$FE_FRONTEND_DIR/anything"
    run_fe
    if [ "$RC" = "2" ]; then
        ok "exit 2 (could-not-look) — no package.json to read"
    else
        bad "exit $RC, want 2"
        show_out
    fi
}

# --- case 5: full, no lockfile ----------------------------------------------
case_full_no_lockfile() {
    CURRENT="full, no pnpm-lock.yaml"
    export FE_FRONTEND_DIR="${WORK}/fe-no-lock"
    rm -rf "$FE_FRONTEND_DIR"
    mkdir -p "$FE_FRONTEND_DIR"
    echo '{"name":"x","private":true,"version":"0.0.0"}' >"$FE_FRONTEND_DIR/package.json"
    changed_list "$FE_FRONTEND_DIR/package.json"
    run_fe
    if [ "$RC" = "2" ]; then
        ok "exit 2 (could-not-look) — a manifest with no lockfile ships an unfrozen dependency set"
    else
        bad "exit $RC, want 2"
        show_out
    fi
}

# --- case 6: the frozen-lockfile TARGET CLASS (criterion 3) -----------------
case_frozen_lockfile_mismatch() {
    CURRENT="full, lockfile no longer satisfies the manifest"
    export FE_FRONTEND_DIR="${WORK}/fe-stale-lock"
    build_clean_frontend "$FE_FRONTEND_DIR"
    # A TEXTUALLY-CLEAN lockfile (it parses, it is committed-shaped) that no
    # longer satisfies package.json: bump the manifest's dependency version
    # without touching the lockfile that was frozen against the old one.
    python3 -c '
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["dependencies"]["left-pad"] = "9.9.9"
json.dump(d, open(p, "w"))
' "$FE_FRONTEND_DIR/package.json"
    changed_list "$FE_FRONTEND_DIR/package.json"
    run_fe
    if [ "$RC" = "1" ]; then
        ok "exit 1 — pnpm install --frozen-lockfile refused the stale lockfile"
    else
        bad "exit $RC, want 1"
        show_out
    fi
}

# --- case 7: full, clean, no test script ------------------------------------
case_full_clean_no_test_script() {
    CURRENT="full, clean lockfile, no test script"
    export FE_FRONTEND_DIR="${WORK}/fe-clean-no-test"
    build_clean_frontend "$FE_FRONTEND_DIR"
    changed_list "$FE_FRONTEND_DIR/package.json"
    run_fe
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "full" ] && grep -q 'no "test" script declared' "$RUN_OUT"; then
        ok "exit 0, FE_LEG_STATE=full, the absent test script is printed rather than run"
    else
        bad "exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}"
        show_out
    fi
}

# --- case 8: full, clean, test script PASSES --------------------------------
case_full_clean_test_passes() {
    CURRENT="full, clean lockfile, test script passes"
    export FE_FRONTEND_DIR="${WORK}/fe-clean-pass"
    build_clean_frontend "$FE_FRONTEND_DIR"
    python3 -c '
import json
p = "'"$FE_FRONTEND_DIR"'/package.json"
d = json.load(open(p))
d["scripts"] = {"test": "exit 0"}
json.dump(d, open(p, "w"))
'
    changed_list "$FE_FRONTEND_DIR/package.json"
    run_fe
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "full" ]; then
        ok "exit 0, FE_LEG_STATE=full, the declared test script ran and passed"
    else
        bad "exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}"
        show_out
    fi
}

# --- case 9: full, clean, test script FAILS ---------------------------------
case_full_clean_test_fails() {
    CURRENT="full, clean lockfile, test script fails"
    export FE_FRONTEND_DIR="${WORK}/fe-clean-fail"
    build_clean_frontend "$FE_FRONTEND_DIR"
    python3 -c '
import json
p = "'"$FE_FRONTEND_DIR"'/package.json"
d = json.load(open(p))
d["scripts"] = {"test": "exit 1"}
json.dump(d, open(p, "w"))
'
    changed_list "$FE_FRONTEND_DIR/package.json"
    run_fe
    if [ "$RC" = "1" ]; then
        ok "exit 1 — the declared test script's own failure reaches the leg's exit status"
    else
        bad "exit $RC, want 1"
        show_out
    fi
}

# --- case 10: the mode decides whether the fast path is reachable ----------
case_under_a_unit_or_full_run_an_untouched_frontend_still_runs_the_leg() {
    # Ratified by the PM, 2026-09-21. The `untouched` fast path is a
    # RUNG-TIME economy and it had leaked into the sharded full gate: MEASURED
    # on f800ab5b, `./scripts/check.sh --leg static` — one shard of a bank —
    # printed `UNTOUCHED (fast path)` and `(fe: 0s)` over this checkout's real
    # `frontend/`, while the unit's own summary named `fe` among the legs it
    # had run. A verdict row must not name a leg that took a fast path out.
    #
    # THE STUB IS A COUNTER, NOT A SHIM OF pnpm. Cases 6-9 drive the real tool
    # because the frozen-lockfile refusal is pnpm's own; this case is about
    # WHETHER the two commands are reached at all, so a stub that appends a
    # line per invocation answers it exactly and costs nothing.
    CURRENT="mode decides the fast path"
    export FE_FRONTEND_DIR="${WORK}/fe-mode"
    build_clean_frontend "$FE_FRONTEND_DIR"
    # A DECLARED test script, so the second pnpm command is reachable: without
    # one `fe_leg_tests` prints and returns before invoking anything, and this
    # case would be asserting one marker where the ratified cost is two.
    python3 -c '
import json
p = "'"$FE_FRONTEND_DIR"'/package.json"
d = json.load(open(p))
d["scripts"] = {"test": "exit 0"}
json.dump(d, open(p, "w"))
'
    local marker="${WORK}/pnpm-mode-marker"
    cat >"${WORK}/pnpm-counter" <<SH
#!/usr/bin/env bash
echo "\$*" >>"$marker"
exit 0
SH
    chmod +x "${WORK}/pnpm-counter"
    export FE_PNPM="${WORK}/pnpm-counter"

    # THE CHANGED SET IS EMPTY OF FRONTEND PATHS AND OF THE CONTRACT SURFACE:
    # under the change-aware modes this is `untouched`, which is what makes
    # the two whole modes below a claim about the MODE rather than about the
    # list.
    changed_list "apps/example/models.py" "docs/product/queue.md"

    local mode label calls
    for mode in "--leg" ""; do
        label="${mode:-<the full gate>}"
        : >"$marker"
        run_fe_mode "$mode"
        calls=$(awk 'END { print NR + 0 }' "$marker")
        if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "full" ] && [ "$calls" = "2" ]; then
            ok "${label}: exit 0, FE_LEG_STATE=full, 2 pnpm invocations (install --frozen-lockfile, run test)"
        else
            bad "${label}: exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}, pnpm calls=${calls} (want 0/full/2)"
            show_out
        fi
        if grep -q "UNTOUCHED (fast path)" "$RUN_OUT"; then
            bad "${label}: the leg printed UNTOUCHED (fast path) — the rung-time economy is still leaking into the bank"
            show_out
        else
            ok "${label}: no UNTOUCHED fast path in the transcript"
        fi
        # THE RATIFIED PRICE, PRINTED. "Two pnpm commands per bank" is only a
        # cost anybody can watch if the leg says what they took.
        if grep -q "fe leg cost: frozen-lockfile .*tests .*(two pnpm commands)" "$RUN_OUT"; then
            ok "${label}: the leg prints its measured cost — $(grep -o 'fe leg cost:.*' "$RUN_OUT")"
        else
            bad "${label}: no measured cost line; the ratified two-command price is unmeasured"
            show_out
        fi
    done

    CURRENT="mode decides the fast path — and --loop keeps it"
    : >"$marker"
    run_fe_mode "--loop"
    calls=$(awk 'END { print NR + 0 }' "$marker")
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "untouched" ] && [ "$calls" = "0" ]; then
        ok "--loop: exit 0, FE_LEG_STATE=untouched, pnpm never invoked — the builder's inner loop is unchanged"
    else
        bad "--loop: exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}, pnpm calls=${calls} (want 0/untouched/0)"
        show_out
    fi

    CURRENT="mode decides the fast path — and --fast keeps it"
    : >"$marker"
    run_fe_mode "--fast"
    calls=$(awk 'END { print NR + 0 }' "$marker")
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "untouched" ] && [ "$calls" = "0" ]; then
        ok "--fast: exit 0, FE_LEG_STATE=untouched, pnpm never invoked"
    else
        bad "--fast: exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}, pnpm calls=${calls} (want 0/untouched/0)"
        show_out
    fi

    # AND A WHOLE RUN THAT CANNOT LOOK SAYS SO. A bank whose box has no pnpm
    # must not bank a row naming `fe`: the same tree-present/toolchain-absent
    # cell `quality/worlds.py`'s `tree_verdict` calls broken, now reachable
    # under a mode that never touches the frontend.
    CURRENT="mode decides the fast path — a whole run with no toolchain is could-not-look"
    export FE_PNPM="${WORK}/no-such-pnpm-binary"
    run_fe_mode "--leg"
    if [ "$RC" = "2" ]; then
        ok "--leg with no toolchain: exit 2 (could-not-look), not a fast-path 0"
    else
        bad "--leg with no toolchain: exit $RC, want 2"
        show_out
    fi
    unset FE_PNPM

    # AND `absent` STILL SHORT-CIRCUITS UNDER A WHOLE MODE: a tree with no
    # frontend/ has nothing to install, which is this template's steady state.
    CURRENT="mode decides the fast path — absent still short-circuits"
    export FE_FRONTEND_DIR="${WORK}/no-such-frontend-mode"
    rm -rf "$FE_FRONTEND_DIR"
    run_fe_mode ""
    if [ "$RC" = "0" ] && [ "$FE_LEG_STATE" = "absent" ]; then
        ok "the full gate over a tree with no frontend/: exit 0, absent"
    else
        bad "exit $RC, FE_LEG_STATE=${FE_LEG_STATE:-<unset>}, want 0/absent"
        show_out
    fi
}

case_absent
case_untouched_pnpm_never_invoked
case_touched_toolchain_absent
case_full_no_manifest
case_full_no_lockfile
case_frozen_lockfile_mismatch
case_full_clean_no_test_script
case_full_clean_test_passes
case_full_clean_test_fails
case_under_a_unit_or_full_run_an_untouched_frontend_still_runs_the_leg

echo
echo "test_fe_leg: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
