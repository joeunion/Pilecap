#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made.
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
# drives: .secrets.baseline compose.yaml docs/product/build-contract.md docs/product/instruments.md scripts/check.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/tests/ scripts/verifier_box.sh
# cites: deploy/tests
# The drive for THE SELFTEST LEG ITSELF — `selftest_drives_leg` in
# `scripts/check.sh`, the leg that runs every shell refusal drive in this
# repository and composes one exit out of all of them.
#
#   ./scripts/tests/test_selftest_leg.sh          run every case
#   ./scripts/tests/test_selftest_leg.sh --list   name them and stop
#
# WHAT IT REPLACED, which is the reason it exists. The leg used to be inline
# code and every drive block ended in its own `exit`: the FIRST red drive ended
# the leg, and every drive after it never ran. A builder paying a 25-minute full
# gate learned exactly one red per run, and the selftest-only classes surface one
# per bank — the measurement behind it is a sanctioned full gate where one tail
# in `test_loop_scope.sh` hid the whole rest of the set, and a later hand-run of
# every drive found the full red list at once.
#
# HOW IT DRIVES THE LEG, and why it is not a gate inside a gate. It extracts the
# text between `scripts/check.sh`'s `selftest-leg` sentinels into a scratch
# directory and SOURCES it there — `test_setup_env.sh` drives `setup.sh`'s
# env-sync step exactly this way — then calls `selftest_drives_leg` with
# `DJB_SELFTEST_DRIVES_DIR` pointing at a scratch set of tiny planted drives it
# wrote itself. The real drive set is never the victim: a nested
# `./scripts/check.sh` is refused by the per-checkout gate lock anyway
# (rung-execution §2), and a plant in `scripts/tests/` would be a destructive
# demonstration aimed at found state.
#
# WHAT IS UNDER DRIVE:
#   the COMPOSITION — every drive runs; two reds are BOTH named and the leg is
#                     1; a could-not-look outranks a red and the leg is 2 with
#                     both named; an all-green set prints one line per drive and
#                     the summary
#   the ENGINE      — a red `quality.gate --selftest` no longer stops the drives:
#                     it is recorded as could-not-look, every drive still runs,
#                     and the leg is 2
#   the CENSUSES    — every literal `scripts/tests/test_<x>.sh` invocation line
#                     and every drive sentinel is still INSIDE the function, so
#                     `test_drive_preamble.sh`'s registration census and
#                     `instruments.md` still read what they always read
#   the BANNER      — the deploy-layer blind-spot block below the leg is
#                     byte-unchanged by the move
#   the WIRING      — the gate calls the function and owns the leg's one exit
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE SCRATCH SET IS TINY DRIVES, NOT THE REAL ONES. Every case drives the
#      composition over planted `exit N` scripts. It therefore proves nothing
#      about whether any REAL drive still passes — that is the leg's own job on
#      the full gate, and the per-rung belt is the hand-run the plan's standing
#      clause 12 requires of any `scripts/tests/**` rung.
#   2. THE ENGINE IS SHIMMED. `uv` is replaced on PATH, so the cases prove how
#      the leg TREATS the engine's status, never that `quality.gate --selftest`
#      itself is right. The canaries are the engine's own instrument.
#   3. SHARED STATE BETWEEN DRIVES IS NOT DRIVEN. Now that every drive runs, a
#      red drive that corrupts state a later drive reads can produce SECONDARY
#      reds in the composed list. That is a declared price of the whole list
#      (the leg's summary says so); no case here plants a drive that corrupts a
#      sibling, because the planted set shares nothing.
#   4. THE BANNER CASE IS A DIGEST, not a diff against a second copy of the
#      text: a copy in this file would be a thing that drifts. A legitimate
#      future edit to that block is expected to update the constant here and to
#      say so — that is the block being declared unchanged, which is the point.
#   5. ORDER IS THE DIRECTORY'S in the scratch branch (a glob, sorted) and the
#      FILE's in the real branch (the literal lines, top to bottom). No case
#      asserts the real branch's order; the registration census asserts the SET.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_selftest_leg: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's scratch work inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble: on macOS's bash 3.2 a `set -u` death hands the EXIT
# trap a status of 0, so a drive that never reached its own summary reports
# success. Opting in makes that could-not-look instead.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_selftest_leg: $*" >&2
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
    echo "!! unknown argument '$1': test_selftest_leg.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the leg this drive exists for has no home"

ROOT="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-selftest-leg-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# THE EXTRACTION. The sentinels are assembled rather than written at the head of
# a line, so this file cannot itself be mistaken for the fence it is looking for
# — `test_setup_env.sh`'s idiom, for its reason.
SENT_OPEN="# >>> selftest-""leg >>>"
SENT_CLOSE="# <<< selftest-""leg <<<"
EXTRACT="${WORK}/selftest_leg_body.sh"
sed -n "/^${SENT_OPEN}\$/,/^${SENT_CLOSE}\$/p" scripts/check.sh >"$EXTRACT" 2>/dev/null || true
if [ ! -s "$EXTRACT" ]; then
    cannot_look "scripts/check.sh has no line reading exactly \`${SENT_OPEN}\` — the selftest-leg fence is gone (or was never there, which is what a baseline tree looks like). Every case below sources the text between that sentinel and \`${SENT_CLOSE}\`, so there is no leg body to drive."
fi

# THE SECOND FENCE THIS BODY STANDS ON, and it lives INSIDE the first.
# `selftest_member_end` hands every member's seconds to `gate_member_record`,
# which sits in the `always-on-leg` fence: the measurement the `--loop`
# always-on set is derived from covers legs and drives through one accumulator,
# so a drive is timed by the same clock a leg is. Sourcing the selftest body
# WITHOUT it would drive a leg whose last act on every member is a command that
# does not exist — green, because the failure is one line on stderr nobody
# reads.
ALWAYS_OPEN="# >>> always-on-""leg >>>"
ALWAYS_CLOSE="# <<< always-on-""leg <<<"
EXTRACT_DUR="${WORK}/always_on_leg.sh"
sed -n "/^${ALWAYS_OPEN}\$/,/^${ALWAYS_CLOSE}\$/p" scripts/check.sh >"$EXTRACT_DUR" 2>/dev/null || true
if [ ! -s "$EXTRACT_DUR" ]; then
    cannot_look "scripts/check.sh has no line reading exactly \`${ALWAYS_OPEN}\` — the always-on fence is gone. The selftest leg's own body calls into it on every member, so the body below cannot be driven as it ships."
fi
if ! grep -q '^gate_member_record() {' "$EXTRACT_DUR"; then
    cannot_look "the always-on fence in scripts/check.sh defines no gate_member_record — the function every member's seconds are handed to is not inside its own sentinels."
fi
if ! grep -q '^selftest_drives_leg() {' "$EXTRACT"; then
    cannot_look "the selftest-leg fence in scripts/check.sh defines no selftest_drives_leg — the function this drive exists for is not inside its own sentinels."
fi

# THE SHIMMED ENGINE. `selftest_drives_leg` runs `uv run python -m quality.gate
# --selftest` first; every case below replaces `uv` on PATH rather than running
# the real engine, which is somebody else's instrument and costs ~30s.
#
# IT HAS TWO READERS NOW, AND THE SHIM TELLS THEM APART. The leg
# also asks the engine what it READS (`--selftest-inputs`) and keys the
# member on that listing, so a shim answering one status to both would either
# make every case could-not-look (an empty listing) or make the self-test's own
# status unreadable. `DJB_FAKE_INPUTS` is the listing to print and
# `DJB_FAKE_INPUTS_RC` its status; `DJB_FAKE_UV_RC` still belongs to
# `--selftest` alone.
SHIM_BIN="${WORK}/bin"
mkdir -p "$SHIM_BIN"
cat >"${SHIM_BIN}/uv" <<'SHIM'
#!/bin/sh
for a in "$@"; do
    if [ "$a" = "--selftest-inputs" ]; then
        [ -z "${DJB_FAKE_INPUTS:-}" ] || cat "${DJB_FAKE_INPUTS}"
        exit "${DJB_FAKE_INPUTS_RC:-0}"
    fi
done
exit "${DJB_FAKE_UV_RC:-0}"
SHIM
chmod +x "${SHIM_BIN}/uv"

# THE ENGINE'S DEFAULT INPUT LISTING, and why it names real tracked files. A
# declared path is CHECKOUT-RELATIVE and is resolved through the MEASURED TREE,
# so a listing naming paths this checkout does not hold keys nothing. These two
# are tracked, are in every measured tree of this repository, and no case below
# moves a byte in either: the cases that move an input plant their own subject
# (`plant_in_checkout`, below) exactly as the drive-subject cases already do.
ENGINE_INPUTS_DEFAULT="${WORK}/engine-inputs-default.txt"
cat >"$ENGINE_INPUTS_DEFAULT" <<'INPUTS'
docs/product/build-contract.md
scripts/tests/drive_preamble.sh
INPUTS

# THE TWO SPELLINGS, RESOLVED RATHER THAN ASSUMED. `shasum -a 256` is macOS's
# and `sha256sum` is a minimal Linux's, and this drive runs on both: a bare
# `shasum` here was `command not found` on the first verifier box this drive
# ever ran on, which under this file's `set -e` is exit 127 — the drive dead,
# nothing asserted, and a loop that says 2 for a tool rather than for a
# property. It deliberately does NOT call the shipped `sha256_of`: a model that
# borrows the implementation it is modelling asserts nothing
# (`test_setup_env.sh`'s `digest_stdin` carries the same two lines for the same
# reason).
banner_digest() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 | awk '{print $1}'
    else
        sha256sum | awk '{print $1}'
    fi
}

CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}

# A SCRATCH DRIVE SET, built per case. Each argument is `<name>:<exit status>`;
# the drives are written in the order given and the glob sorts them, so the names
# carry a numeric prefix where order is asserted.
#
# EVERY PLANTED DRIVE CARRIES A `# drives:` MARKER, because the leg refuses a
# drive it cannot key (A.4) and a set with no markers would be a set of
# could-not-looks. `PLANT_DECL` is what they declare; the default is a path that
# is in this tree and never moves during a case. `PLANT_BODY_EXTRA` is a line
# appended to the body, which is how the floor's "a path spelled but not
# declared" plant is made.
#
# AND THE SET CARRIES ITS OWN `drive_preamble.sh`. The key always includes the
# preamble BESIDE the drive (the real set's is `scripts/tests/drive_preamble.sh`),
# so a scratch set needs one of its own — which is also the only way to move a
# preamble byte without planting into a tracked file of this checkout.
PLANT_DECL="scripts/tests/drive_preamble.sh"
PLANT_BODY_EXTRA=""
plant_drive_set() {
    local dir="$1"
    shift
    local spec name rc
    rm -rf "$dir"
    mkdir -p "$dir"
    printf '# a scratch drive set preamble — never sourced, always keyed\n' \
        >"${dir}/drive_preamble.sh"
    for spec in "$@"; do
        name="${spec%%:*}"
        rc="${spec##*:}"
        cat >"${dir}/test_${name}.sh" <<PLANT
#!/bin/sh
# drives: ${PLANT_DECL}
echo "planted drive ${name} speaking"
${PLANT_BODY_EXTRA}
exit ${rc}
PLANT
        chmod +x "${dir}/test_${name}.sh"
    done
}

# A DRIVE WITH NO MARKER AT ALL — A.4's first plant, and the one shape
# `plant_drive_set` cannot make, because it always writes one.
plant_unmarked_drive() {
    local dir="$1" name="$2"
    mkdir -p "$dir"
    printf '#!/bin/sh\necho "unmarked drive %s speaking"\nexit 0\n' "$name" \
        >"${dir}/test_${name}.sh"
    chmod +x "${dir}/test_${name}.sh"
}

# THE SCRATCH LEDGER. Every case that banks or consults a drive verdict aims
# `DJB_GATE_LEDGER` at a file under `$WORK`: the real `djb-gate-verdicts` is
# SHARED across every worktree of this repository (`gate_ledger_path` resolves
# through `--git-common-dir`), so a drive writing rows into it would be a
# destructive demonstration aimed at found state.
# EVERY CASE GETS ITS OWN, AND THERE IS NO PATH TO THE REAL ONE FROM HERE. The
# default below is set before the first case runs and `run_leg` REFUSES an empty
# one: a case that forgot to call `new_ledger` would otherwise drive the leg
# against the checkout family's shared `djb-gate-verdicts` — which banks rows for
# planted drives and then REUSES them on the next run, so the composition cases
# would go red for a reason that has nothing to do with the composition. That is
# not hypothetical; it is how this line came to be written.
LEDGER="${WORK}/verdicts-default"
new_ledger() {
    LEDGER="${WORK}/verdicts-$1"
    rm -f "$LEDGER"
    : >"$LEDGER"
}
new_ledger default
ledger_drive_rows() {
    [ -s "$LEDGER" ] || return 0
    awk '$3 == "drive"' "$LEDGER"
}
# COUNTED WITH awk AND NEVER `grep -c`: `grep -c .` exits 1 on zero matches, and
# under this file's `set -e` a bare assignment from it kills the drive at the one
# moment a case most wants to report — the moment nothing was banked.
ledger_drive_count() {
    ledger_drive_rows | awk 'END { print NR + 0 }'
}

# THE ENGINE BANKS A ROW TOO, NOW THAT IT IS KEYED, and it is not one of the planted
# drives. Every case below that asks "did MY drives bank" counts the planted
# ones BY EXCLUDING THE ENGINE BY NAME rather than by bumping a literal: a case
# whose expected number had quietly absorbed the engine's row would stop
# noticing a planted drive that stopped banking, which is the one thing those
# counts are there for.
ledger_planted_count() {
    ledger_drive_rows | awk '$5 != "house-rules-engine" { n++ } END { print n + 0 }'
}
ledger_planted_rows() {
    ledger_drive_rows | awk '$5 != "house-rules-engine"'
}
ledger_engine_rows() {
    ledger_drive_rows | awk '$5 == "house-rules-engine"'
}
ledger_engine_count() {
    ledger_engine_rows | awk 'END { print NR + 0 }'
}
# AND THE SAME EXCLUSION ON THE LEG'S OWN OUTPUT. A case that moved a byte in a
# PLANTED drive's subject and then grepped the whole leg for the word REUSED
# would read the ENGINE's own — correct — reuse and call it a failure: the
# engine's inputs did not move, so its verdict rightly stands. Every question
# below about "did MY drives reuse" is asked of the planted members by name.
planted_reused_count() {
    sed -n 's/^  drive \([^:]*\): REUSED.*/\1/p' "$LEG_OUT" |
        awk '$1 != "house-rules-engine" { n++ } END { print n + 0 }'
}

# THE PLANTS THAT HAVE TO BE IN THE CHECKOUT, and why there is no other place
# for them. A declared path is CHECKOUT-RELATIVE and is resolved through the
# measured tree, so a subject whose bytes a case moves has to be a file in this
# checkout. Both are files nothing else in this repository has ever had, both
# are non-executable (an untracked EXECUTABLE in the checkout reds the
# instrument census by design), and both are removed on every exit path.
CHECKOUT_PLANTS=""
plant_in_checkout() {
    local rel="$1" text="$2"
    printf '%s\n' "$text" >"${ROOT}/${rel}"
    case " $CHECKOUT_PLANTS " in
    *" $rel "*) ;;
    *) CHECKOUT_PLANTS="${CHECKOUT_PLANTS}${CHECKOUT_PLANTS:+ }${rel}" ;;
    esac
}
unplant_checkout() {
    local rel
    for rel in $CHECKOUT_PLANTS; do rm -f "${ROOT}/${rel}"; done
    CHECKOUT_PLANTS=""
}
drive_at_exit 'unplant_checkout'

# RUN THE LEG BODY over a planted set. Everything happens in a subshell so the
# body's own `set -e`/`set +e` pairs cannot reach this drive's shell.
#
# THE TWO LIBRARIES ARE SOURCED BESIDE THE BODY. `scripts/check.sh` sources
# `gate_refuse.sh` and `gate_ledger.sh` before it defines this leg, and the leg
# reads a drive's verdict through them; extracting the body without them would
# drive a leg that cannot exist.
LEG_SHARD=""
LEG_NO_REUSE=""
LEG_MODE=""
LEG_UNIT="x"
LEG_INPUTS=""
LEG_INPUTS_RC=""
# THE MACHINE THE LEG BELIEVES IT IS ON. A drive key's machine half is
# `/etc/djb/image-id` where that file exists and bash/git/uname where it does
# not (`scripts/gate_ledger.sh`, `drive_machine_digest`), and
# `DJB_DRIVE_MACHINE_FILE` is the one seam that points it somewhere a case can
# write. Empty means "this machine", which is every case that was here before.
LEG_MACHINE_FILE=""
run_leg() {
    local dir="$1"
    local uv_rc="${2:-0}"
    local t0
    LEG_OUT="${WORK}/leg.out"
    LEG_RC=0
    [ -n "$LEDGER" ] ||
        cannot_look "no scratch ledger is set — refusing to drive the leg against the shared djb-gate-verdicts"
    t0=$(date +%s)
    (
        set +e
        PATH="${SHIM_BIN}:${PATH}"
        export PATH
        DJB_FAKE_UV_RC="$uv_rc"
        export DJB_FAKE_UV_RC
        DJB_FAKE_INPUTS="${LEG_INPUTS:-$ENGINE_INPUTS_DEFAULT}"
        export DJB_FAKE_INPUTS
        DJB_FAKE_INPUTS_RC="${LEG_INPUTS_RC:-0}"
        export DJB_FAKE_INPUTS_RC
        DJB_SELFTEST_DRIVES_DIR="$dir"
        export DJB_SELFTEST_DRIVES_DIR
        DJB_GATE_LEDGER="$LEDGER"
        export DJB_GATE_LEDGER
        # THE MEMO IS CLEARED ON EVERY RUN. `drive_machine_digest` memoises
        # through the ENVIRONMENT so one leg pays one read; inherited from a
        # previous run in this drive's own shell it would answer for the
        # previous case's machine, and every arm below would pass whatever the
        # code did.
        unset DRIVE_MACHINE_DIGEST DRIVE_MACHINE_LABEL
        if [ -n "$LEG_MACHINE_FILE" ]; then
            DJB_DRIVE_MACHINE_FILE="$LEG_MACHINE_FILE"
            export DJB_DRIVE_MACHINE_FILE
        fi
        if [ -n "$LEG_NO_REUSE" ]; then
            DJB_SELFTEST_NO_REUSE=1
            export DJB_SELFTEST_NO_REUSE
        fi
        . scripts/gate_refuse.sh
        . scripts/gate_ledger.sh
        . "$EXTRACT_DUR"
        . "$EXTRACT"
        # THE RECORDER'S OWN GUARD, honoured rather than bypassed: it records
        # only on a bare full run (`MODE` empty, no unit), because seconds from
        # a `--loop` or a `--leg` would be a measurement of a subset written
        # into the file the whole set is derived from. A case that wants the
        # accumulator filled sets these the way a full run does.
        MODE="$LEG_MODE"
        GATE_LEG_UNIT="$LEG_UNIT"
        # shellcheck disable=SC2086
        selftest_drives_leg $LEG_SHARD
    ) >"$LEG_OUT" 2>&1 || LEG_RC=$?
    LEG_WALL=$(($(date +%s) - t0))
}

# --- the composition ----------------------------------------------------------

case_all_green_prints_one_line_per_drive_and_the_summary() {
    CURRENT=case_all_green_prints_one_line_per_drive_and_the_summary
    new_ledger green
    local dir="${WORK}/set-green"
    plant_drive_set "$dir" 1_alpha:0 2_bravo:0 3_charlie:0
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "an all-green set gave exit ${LEG_RC}; the leg's output was: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local missing=""
    local n
    for n in 1_alpha 2_bravo 3_charlie; do
        grep -qE "^  drive ${n}: exit 0 \([0-9]+s\)\$" "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "no \`drive <name>: exit 0 (Ns)\` line for:${missing}"
        return
    fi
    # The engine is counted the same way, and it is one of the green members.
    if ! grep -qE "^  drive house-rules-engine: exit 0 \([0-9]+s\)\$" "$LEG_OUT"; then
        bad "the engine's own selftest is not printed as a member"
        return
    fi
    if ! grep -q "selftest: 4 drive(s) green · 0 red · 0 could-not-look" "$LEG_OUT"; then
        bad "no summary line naming 4 green (3 planted + the engine); got: $(grep -c . "$LEG_OUT") line(s)"
        return
    fi
    ok "three planted drives and the engine each printed one line, and the summary counted four"
}

case_two_red_drives_are_both_named_and_the_leg_is_exit_1() {
    CURRENT=case_two_red_drives_are_both_named_and_the_leg_is_exit_1
    new_ledger tworeds
    local dir="${WORK}/set-two-red"
    plant_drive_set "$dir" 1_alpha:0 2_bravo:1 3_charlie:0 4_delta:1 5_echo:0
    run_leg "$dir"
    if [ "$LEG_RC" != "1" ]; then
        bad "wanted exit 1 for two red drives, got ${LEG_RC}"
        return
    fi
    # THE PROPERTY THE ROW WAS OPENED FOR: the drives AFTER the first red ran.
    local missing=""
    local n
    for n in 3_charlie 4_delta 5_echo; do
        grep -q "drive ${n}: exit " "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "the leg stopped at the first red — no line for:${missing}"
        return
    fi
    if ! grep -q '^!! RED:' "$LEG_OUT"; then
        bad "no composed RED line naming the red drives"
        return
    fi
    local red_line
    red_line="$(grep '^!! RED:' "$LEG_OUT")"
    case "$red_line" in
    *2_bravo*) ;;
    *)
        bad "the RED line does not name 2_bravo: ${red_line}"
        return
        ;;
    esac
    case "$red_line" in
    *4_delta*) ;;
    *)
        bad "the RED line does not name 4_delta: ${red_line}"
        return
        ;;
    esac
    if ! grep -q "selftest: 4 drive(s) green · 2 red · 0 could-not-look" "$LEG_OUT"; then
        bad "the summary does not count 4 green (3 planted + the engine) and 2 red"
        return
    fi
    ok "both reds named on one line, every later drive ran, exit 1"
}

case_a_could_not_look_drive_outranks_a_red_one_and_both_are_named() {
    CURRENT=case_a_could_not_look_drive_outranks_a_red_one_and_both_are_named
    new_ledger cannot
    local dir="${WORK}/set-two-and-one"
    plant_drive_set "$dir" 1_alpha:1 2_bravo:2 3_charlie:0
    run_leg "$dir"
    if [ "$LEG_RC" != "2" ]; then
        bad "wanted exit 2 (2 outranks 1), got ${LEG_RC}"
        return
    fi
    if ! grep -q "drive 3_charlie: exit 0" "$LEG_OUT"; then
        bad "the drive after the could-not-look never ran"
        return
    fi
    local cannot_line red_line
    cannot_line="$(grep '^!! COULD NOT LOOK:' "$LEG_OUT" || true)"
    red_line="$(grep '^!! and RED:' "$LEG_OUT" || true)"
    case "$cannot_line" in
    *2_bravo*) ;;
    *)
        bad "the COULD NOT LOOK line does not name 2_bravo: '${cannot_line}'"
        return
        ;;
    esac
    case "$red_line" in
    *1_alpha*) ;;
    *)
        bad "the red drive is not named beside the could-not-look one: '${red_line}'"
        return
        ;;
    esac
    if ! grep -q "selftest: 2 drive(s) green · 1 red · 1 could-not-look" "$LEG_OUT"; then
        bad "the summary does not count 1 red and 1 could-not-look"
        return
    fi
    ok "2 outranked 1, both names printed, the later drive still ran"
}

case_a_red_engine_selftest_still_runs_every_drive_and_the_leg_is_exit_2() {
    CURRENT=case_a_red_engine_selftest_still_runs_every_drive_and_the_leg_is_exit_2
    new_ledger enginered
    local dir="${WORK}/set-engine-red"
    plant_drive_set "$dir" 1_alpha:0 2_bravo:0
    run_leg "$dir" 1
    if [ "$LEG_RC" != "2" ]; then
        bad "a red engine selftest gave exit ${LEG_RC}; a dead canary outranks any pass"
        return
    fi
    if ! grep -q "ENFORCEMENT ITSELF IS BROKEN" "$LEG_OUT"; then
        bad "the engine's own red sentence is gone"
        return
    fi
    local missing=""
    local n
    for n in 1_alpha 2_bravo; do
        grep -q "drive ${n}: exit 0" "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "a red engine selftest still stops the drives — no line for:${missing}"
        return
    fi
    if ! grep -q "selftest: 2 drive(s) green · 0 red · 1 could-not-look" "$LEG_OUT"; then
        bad "the engine's red is not counted as the one could-not-look"
        return
    fi
    ok "the engine reddened, was recorded as could-not-look, and every drive still ran"
}

case_every_exit_in_the_leg_body_is_inside_a_drive_subshell() {
    CURRENT=case_every_exit_in_the_leg_body_is_inside_a_drive_subshell
    # THE STATIC TOOTH, and it is the one that is red on the tree the
    # composition replaced: there, the leg was inline code and every drive
    # block's `exit` ended the LEG, which is exactly what made one red hide the
    # rest. The blocks still carry those exits, byte for byte — what changed is
    # that each one now runs inside a subshell the leg opens around it, so the
    # exit ends the block and the leg reads it as a status. So the property is
    # not "no exit"; it is "no exit the leg itself would die of".
    local stray
    stray="$(awk '
        /^\($/                             { depth = 1; next }
        /^\) \|\| SELFTEST_BLOCK_RC=\$\?$/ { depth = 0; next }
        depth == 0 && /^[[:space:]]*exit / { print NR ": " $0 }
    ' "$EXTRACT")"
    if [ -n "$stray" ]; then
        bad "the leg body exits outside a drive subshell, so a drive after it would never run: $(printf '%s' "$stray" | tr '\n' '|')"
        return
    fi
    # And the wrapper is not lopsided: one open, one close and one recorded
    # status per drive.
    local opens closes ends invocations
    opens="$(grep -cx '(' "$EXTRACT" || true)"
    closes="$(grep -cF ') || SELFTEST_BLOCK_RC=$?' "$EXTRACT" || true)"
    ends="$(grep -cF 'selftest_member_end "$SELFTEST_BLOCK_RC"' "$EXTRACT" || true)"
    # BOTH DRIVE DIRECTORIES. The leg registers every drive under
    # `scripts/tests/` and exactly one under `deploy/tests/`
    # (`selftest_registered_drives` is where that one path is argued), so a
    # count that read only the first directory would find one wrapper more
    # than it found invocations and call a correctly wired leg lopsided.
    invocations="$(grep -oE './(scripts|deploy)/tests/test_[a-z_]+\.sh' "$EXTRACT" | sort -u | grep -c . || true)"
    if [ "$opens" != "$closes" ] || [ "$opens" != "$ends" ] || [ "$opens" != "$invocations" ]; then
        bad "one wrapper per drive does not hold: ${opens} open, ${closes} close, ${ends} recorded, ${invocations} drive(s) invoked"
        return
    fi
    if ! grep -q 'selftest_compose' "$EXTRACT"; then
        bad "the body has no composition step at all"
        return
    fi
    ok "${opens} drive subshell(s), one per invocation, each recorded; no exit outside one; the leg's own exit is the gate's, after the composition"
}

# --- the censuses the move must not break -------------------------------------

case_every_registered_drive_line_and_sentinel_survives_the_function() {
    CURRENT=case_every_registered_drive_line_and_sentinel_survives_the_function
    # `test_drive_preamble.sh` and `docs/product/instruments.md` both read these
    # out of `scripts/check.sh`. If the move had turned them into a loop over a
    # directory glob the set would be derived and the census that pins it would
    # be blind — the plan's G6.2, in one case.
    local in_dir in_fence
    in_dir="$(ls scripts/tests/test_*.sh | xargs -n1 basename | sort)"
    in_fence="$(grep -oE './scripts/tests/test_[a-z_]+\.sh' "$EXTRACT" | xargs -n1 basename | sort -u)"
    local only_dir
    only_dir="$(comm -23 <(printf '%s\n' "$in_dir") <(printf '%s\n' "$in_fence"))"
    if [ -n "$only_dir" ]; then
        bad "drive(s) under scripts/tests/ with no invocation line inside the leg body: $(printf '%s' "$only_dir" | tr '\n' ' ')"
        return
    fi
    local only_fence
    only_fence="$(comm -13 <(printf '%s\n' "$in_dir") <(printf '%s\n' "$in_fence"))"
    if [ -n "$only_fence" ]; then
        bad "the leg body invokes drive(s) that are not in scripts/tests/: $(printf '%s' "$only_fence" | tr '\n' ' ')"
        return
    fi
    local sent_all sent_fence
    sent_all="$(grep -c '^# >>> drive: ' scripts/check.sh || true)"
    sent_fence="$(grep -c '^# >>> drive: ' "$EXTRACT" || true)"
    if [ "$sent_all" != "$sent_fence" ]; then
        bad "${sent_all} drive sentinel(s) in check.sh but ${sent_fence} inside the leg body — one moved out of the fence"
        return
    fi
    if [ "$sent_fence" = "0" ]; then
        bad "no drive sentinels inside the leg body at all"
        return
    fi
    ok "$(printf '%s\n' "$in_dir" | grep -c .) drive(s) in the directory, the same set invoked inside the function, ${sent_fence} sentinel(s) intact"
}

case_the_deploy_blind_spot_banner_is_unchanged() {
    CURRENT=case_the_deploy_blind_spot_banner_is_unchanged
    # Recorded from the tree the composition was built on. The banner is OUTSIDE
    # the leg's function on purpose and is declared untouched by the move; a
    # later change that edits it edits this constant in the same commit, which
    # is what makes the declaration mean something.
    #
    # RE-PINNED A SECOND TIME, DELIBERATELY (2026-09-18). The block gained a
    # one-line exclusion so that a deploy-layer drive THE LEG NOW RUNS stops
    # being counted as a gap: the first of them to carry `drive_preamble.sh`
    # was wired into the leg, and without the exclusion the same page carried
    # its `drive stage: exit 0` line and a banner saying it was not run. The
    # exclusion is derived from check.sh's own column-zero invocation lines,
    # so the block goes on naming every sibling that is still unrun and stops
    # naming the one that is not. Same licence as the re-pin below, exercised
    # the same way: the constant moved in the same commit as the block.
    #
    # RE-PINNED ONCE, DELIBERATELY (2026-09-16, the gate lane's G10 rider). The
    # banner gained a `case` guard on `GATE_LEG_UNIT_LEGS` so that it prints
    # under the unit that actually ran the drives and not under every
    # `--leg <unit>`: a blind-spot notice about drives, in a transcript holding
    # no drives, reads as a claim about the unit in front of it. The whole-gate
    # transcript is unchanged — the guard's default is the unguarded behaviour —
    # and the constant moved in the same commit as the block, which is the
    # licence this case has always granted and the only one it grants.
    # The constant below is a SHA-256 of a COMMENT BLOCK in scripts/check.sh, not
    # a credential: it is recomputed from the tree a few lines down and the only
    # thing it can unlock is this case's verdict. The scanner reads any 64 hex
    # characters as high entropy, so the pragma rides the value's own line —
    # detect-secrets reads it there and nowhere else.
    local want_sha="449ef9596d10a19ac18ef903e3f2a5b8ee13ebad06edec757a7e9f7ca7230de2" # pragma: allowlist secret
    local want_lines=100
    local banner="${WORK}/banner.txt"
    awk '/^# --- WHAT THIS LEG DOES NOT RUN, SAID OUT LOUD/{f=1} /^leg full-house-rules/{f=0} f' \
        scripts/check.sh >"$banner"
    if [ ! -s "$banner" ]; then
        bad "the deploy-layer blind-spot banner is not in scripts/check.sh at all"
        return
    fi
    local got_lines got_sha
    got_lines="$(wc -l <"$banner" | tr -d ' ')"
    # THE TWO SPELLINGS, RESOLVED IN THIS FILE. A bare `shasum` is a mac thing:
    # this line exited 127 on the first verifier box this drive ever ran on —
    # `set -e`, the whole drive dead six cases in, which is why no on-box bank
    # had ever cleared the selftest leg's own drive. Sourcing `gate_refuse.sh`
    # in a subshell and calling the shipped `sha256_of` would also work and was
    # weighed; `banner_digest` is kept because it is the form this repository
    # has already codified for a drive that must run on both machines
    # (`test_setup_env.sh::digest_stdin`, with the argument beside it: a model
    # that borrows the implementation it is modelling asserts nothing), and one
    # spelling of one thing beats two.
    got_sha="$(banner_digest <"$banner")"
    if [ "$got_sha" != "$want_sha" ]; then
        bad "the banner moved: ${got_lines} line(s), sha ${got_sha} — wanted ${want_lines} line(s), sha ${want_sha}"
        return
    fi
    ok "the banner is byte-identical to the baseline (${got_lines} lines, sha ${got_sha:0:12}…)"
}

case_the_gate_calls_the_function_and_owns_its_one_exit() {
    CURRENT=case_the_gate_calls_the_function_and_owns_its_one_exit
    # The weaker text proof `test_db_pin.sh` and `test_loop_tier.sh` both declare
    # for the same reason: the wiring cannot be driven without running the gate.
    if ! grep -qE '^selftest_drives_leg \|\| SELFTEST_LEG_RC=\$\?$' scripts/check.sh; then
        bad "scripts/check.sh does not call selftest_drives_leg in the errexit-safe form"
        return
    fi
    if ! grep -qE '^    exit "\$SELFTEST_LEG_RC"$' scripts/check.sh; then
        bad "the gate does not exit on the leg's composed status"
        return
    fi
    local call_line def_line
    call_line="$(grep -n '^selftest_drives_leg || SELFTEST_LEG_RC=\$?$' scripts/check.sh | sed -n '1s/:.*//p')"
    def_line="$(grep -n '^selftest_drives_leg() {$' scripts/check.sh | sed -n '1s/:.*//p')"
    if [ -z "$call_line" ] || [ -z "$def_line" ] || [ "$def_line" -ge "$call_line" ]; then
        bad "the function is not defined before it is called (def ${def_line:-none}, call ${call_line:-none})"
        return
    fi
    ok "defined at :${def_line}, called at :${call_line}, and the gate exits on the composed status"
}

# --- the drive verdicts ------------------------------------------------------
#
# WHAT THESE EIGHT CASES ARE ABOUT. The leg re-drove all thirty drives on every
# full gate, whatever had moved — 1663 s of the selftest leg's 1887 s on BANK-8.
# A drive's verdict is now BANKED against a key derived from what the drive
# DECLARES it drives (`# drives:` in its first forty lines) plus the bytes of
# every declared path in the measured tree, and a banked drive is not re-driven.
#
# EVERY ONE OF THEM IS ABOUT A GREEN THAT COULD LIE. A reuse that survives a
# moved byte, a drive that banks while red, a key nobody could decide reported
# as a pass — each is a green vouching for bytes nobody drove, and none of them
# is visible from inside a green gate. So the cases plant the move and require
# the refusal, rather than asserting that the happy path still prints.

case_a_banked_drive_is_reused_and_named() {
    CURRENT=case_a_banked_drive_is_reused_and_named
    local dir="${WORK}/set-reuse"
    new_ledger reuse
    plant_drive_set "$dir" 1_alpha:0 2_bravo:0
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "the first (banking) run was not green: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if grep -q 'REUSED' "$LEG_OUT"; then
        bad "the FIRST run reused something — nothing was banked before it"
        return
    fi
    if [ "$(ledger_planted_count)" != "2" ]; then
        bad "the first run banked $(ledger_planted_count) drive row(s), wanted 2"
        return
    fi
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "the second run was not green: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local missing="" n
    for n in 1_alpha 2_bravo; do
        # EITHER LABEL, because this drive runs on a verifier box as well as on
        # a laptop and the machine half is the IMAGE there — a `host:`-only
        # pattern was red on the first box it ever met, for the drive's
        # assumption and not the leg's. WHICH label belongs on WHICH machine is
        # `test_loop_ledger.sh`'s question, asked of `drive_key` with the
        # machine planted both ways.
        grep -qE "^  drive ${n}: REUSED from drive-v1:[0-9a-f]{64} \(banked [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z\) machine=(host:[0-9a-f]{12}|image:[A-Za-z0-9_.-]+)\$" \
            "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "no \`drive <name>: REUSED from drive-v1:<key> (banked <date>) machine=host:<12 hex>|image:<ami>\` line for:${missing} — got: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    # A REUSED drive is counted GREEN, or the summary stops adding up.
    if ! grep -q "selftest: 3 drive(s) green · 0 red · 0 could-not-look" "$LEG_OUT"; then
        bad "a reused drive is not counted green (2 planted + the engine): $(grep 'selftest:' "$LEG_OUT" || true)"
        return
    fi
    if [ "$LEG_WALL" -ge 5 ]; then
        bad "the second run took ${LEG_WALL}s — a leg that reused everything drove something"
        return
    fi
    ok "both drives REUSED by name and key, counted green, the whole second leg in ${LEG_WALL}s"
}

case_a_moved_driven_byte_refuses_the_reuse() {
    CURRENT=case_a_moved_driven_byte_refuses_the_reuse
    local dir="${WORK}/set-moved"
    local subject="scripts/scratch_subject.sh"

    # PLANT ONE: a byte in a DECLARED SUBJECT.
    new_ledger moved
    plant_in_checkout "$subject" '# a scratch subject nothing else in this tree reads'
    PLANT_DECL="$subject"
    plant_drive_set "$dir" 1_alpha:0
    PLANT_DECL="scripts/tests/drive_preamble.sh"
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ] || [ "$(ledger_planted_count)" != "1" ]; then
        bad "the banking run over a declared scratch subject did not bank: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local first_key
    first_key="$(ledger_planted_rows | awk 'NR==1{print $2}')"
    printf '# one more comment byte\n' >>"${ROOT}/${subject}"
    run_leg "$dir"
    if [ "$(planted_reused_count)" != "0" ]; then
        bad "a moved byte in ${subject} was REUSED anyway — the key does not see the subject"
        return
    fi
    if ! grep -qE "^  drive 1_alpha: exit 0 \([0-9]+s\)\$" "$LEG_OUT"; then
        bad "the drive did not RUN after its subject moved: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qF "miss: ${subject} moved since ${first_key}" "$LEG_OUT"; then
        bad "the miss does not name ${subject} and the key it moved from: $(grep -F 'miss:' "$LEG_OUT" || echo '<no miss line>')"
        return
    fi
    ok "a byte in a declared subject refused the reuse and the miss named the path and the old key"

    # PLANT TWO: a byte in the DRIVE FILE itself.
    new_ledger moved-self
    plant_drive_set "$dir" 1_alpha:0
    run_leg "$dir"
    if [ "$(ledger_planted_count)" != "1" ]; then
        bad "the drive-file plant did not bank a row first"
        return
    fi
    first_key="$(ledger_planted_rows | awk 'NR==1{print $2}')"
    printf '# one more comment byte\n' >>"${dir}/test_1_alpha.sh"
    run_leg "$dir"
    if [ "$(planted_reused_count)" != "0" ]; then
        bad "a moved byte in the DRIVE FILE was REUSED anyway"
        return
    fi
    if ! grep -qF "moved since ${first_key}" "$LEG_OUT"; then
        bad "no miss naming the old key after the drive file moved: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -F "miss:" "$LEG_OUT" | grep -F 'test_1_alpha.sh' >/dev/null; then
        bad "the miss does not name the drive file: $(grep -F 'miss:' "$LEG_OUT" || echo '<no miss line>')"
        return
    fi
    ok "a byte in the drive file refused the reuse and the miss named the drive file"

    # PLANT THREE: a byte in the PREAMBLE beside the drive.
    new_ledger moved-preamble
    plant_drive_set "$dir" 1_alpha:0
    run_leg "$dir"
    if [ "$(ledger_planted_count)" != "1" ]; then
        bad "the preamble plant did not bank a row first"
        return
    fi
    first_key="$(ledger_planted_rows | awk 'NR==1{print $2}')"
    printf '# one more comment byte\n' >>"${dir}/drive_preamble.sh"
    run_leg "$dir"
    if [ "$(planted_reused_count)" != "0" ]; then
        bad "a moved byte in drive_preamble.sh was REUSED anyway"
        return
    fi
    if ! grep -F "miss:" "$LEG_OUT" | grep -F 'drive_preamble.sh' >/dev/null; then
        bad "the miss does not name the preamble: $(grep -F 'miss:' "$LEG_OUT" || echo '<no miss line>')"
        return
    fi
    ok "a byte in the preamble beside the drive refused the reuse and the miss named it"
    unplant_checkout
}

# --- the rows that TRAVEL -----------------------------------------------------
#
# WHAT THESE TWO ARE ABOUT. A drive row's machine half is the IMAGE on a
# verifier box, so a row banked on one box of an image is a row every box of
# that image may honour — and the carrier that moves it is
# `scripts/verifier_box.sh`: `cmd_push` drops this checkout's `drive` rows at
# `~/verify/<rung>/ledger.in`, and `box_ledger_ingest` composes the one line
# `cmd_loop` and `cmd_leg` prepend to the gate's command line over there. The
# REAL function is extracted and run here rather than a copy of it written
# beside it, which is why this drive declares that file.
#
# THE FAILURE THEY EXIST FOR is a green that lies in the expensive direction:
# an ingest that appended a row twice, or a ledger that filled and a leg that
# reused nothing anyway, both look exactly like a working carrier from the
# outside — the bank simply costs what it always cost.
case_an_ingested_row_reuses_on_the_same_image() {
    CURRENT=case_an_ingested_row_reuses_on_the_same_image
    local dir="${WORK}/set-ingest" img="${WORK}/ingest-image-id"
    printf 'ami-0ing3st0ing3st000\n' >"$img"

    # ONE BOX BANKS. The leg runs over a scratch set with the image planted, so
    # the two rows it banks carry `machine:` = the digest of `image <ami>`.
    new_ledger ingest-source
    LEG_MACHINE_FILE="$img"
    plant_drive_set "$dir" 1_alpha:0 2_bravo:0
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ] || [ "$(ledger_planted_count)" != "2" ]; then
        LEG_MACHINE_FILE=""
        bad "the banking run on the planted image did not bank two rows: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local out_rows
    out_rows="${WORK}/ledger.in"
    # ONE MORE DRIVE ROW THIS LEG WILL NEVER KEY, so "the ingest carries what
    # it was given" is a claim about more rows than the ones it banked. The
    # rows it banked are THREE, not two: the engine is keyed like every other
    # member now and banks beside the two planted drives, and the carrier
    # carries whatever drive rows the ledger holds — modelling anything
    # narrower here would be modelling a carrier nobody ships.
    {
        ledger_drive_rows
        # A LITERAL 64-HEX KEY, not a digest computed here. `shasum` is a mac
        # thing and a verifier box has `sha256sum`; this row's key only has to
        # be a key no leg will ever compute, and reaching for a digest tool by
        # hand is the very habit `sha256_of` exists to stop — it exited 127 on
        # the box the first time this case ran there.
        printf 'v1 drive-v1:%s drive 2026-09-18T09:00:00Z 9_foreign exit=0 took=3 tree=deadbeef parts=x:000000000000\n' \
            "f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0f0"
    } >"$out_rows"
    local sent
    sent="$(awk 'END { print NR + 0 }' "$out_rows")"
    if [ "$sent" != "4" ]; then
        LEG_MACHINE_FILE=""
        bad "the carrier file holds ${sent} row(s), wanted 4 (1_alpha, 2_bravo, house-rules-engine, 9_foreign)"
        return
    fi

    # THE BOX'S OWN LEDGER, holding ONE of the four already plus two rows of
    # other kinds — so the count after the ingest is arithmetic a reader can
    # check rather than a number this case chose.
    local boxdir boxledger
    boxdir="${WORK}/boxside"
    rm -rf "$boxdir"
    mkdir -p "$boxdir/.git"
    boxledger="${boxdir}/.git/djb-gate-verdicts"
    {
        sed -n '1p' "$out_rows"
        printf 'v1 fullkeyaaa full 2026-09-18T08:00:00Z ruff,mypy exit=0 took=900 tree=aaaa\n'
        printf 'loop-v1 loop-v1:bbb loop 2026-09-18T08:30:00Z caller=unstated tree=bbbb\n'
    } >"$boxledger"

    # THE REAL INGEST, EXTRACTED FROM THE WRAPPER. `box_ledger_ingest` composes
    # the line; the line is what a box's shell runs, so it is run here by a
    # shell with `~` pointing at a scratch home.
    local ingest_fn ingest_line boxhome
    ingest_fn="${WORK}/box_ledger_ingest.sh"
    sed -n '/^box_ledger_ingest() {/,/^}/p' "${ROOT}/scripts/verifier_box.sh" >"$ingest_fn"
    if [ ! -s "$ingest_fn" ]; then
        LEG_MACHINE_FILE=""
        bad "scripts/verifier_box.sh defines no box_ledger_ingest — the carrier's ingest is gone"
        return
    fi
    boxhome="${WORK}/boxhome"
    rm -rf "$boxhome"
    mkdir -p "${boxhome}/verify/a-rung"
    cp "$out_rows" "${boxhome}/verify/a-rung/ledger.in"
    ingest_line="$(
        # shellcheck disable=SC1090
        . "$ingest_fn"
        box_ledger_ingest "$boxdir" a-rung
    )"
    run_ingest() { HOME="$boxhome" bash -c "cd '$boxdir' && ${ingest_line}"; }
    run_ingest
    local after
    after="$(awk 'END { print NR + 0 }' "$boxledger")"
    if [ "$after" != "6" ]; then
        LEG_MACHINE_FILE=""
        unset -f run_ingest
        bad "after the ingest the box ledger holds ${after} line(s), wanted 6 (4 carried, 1 of them already there, + 2 of other kinds)"
        return
    fi
    ok "the ingest carried 4 rows into a ledger that already held 1 of them and 2 others — 6 lines"
    local before_second
    before_second="$(cat "$boxledger")"
    run_ingest
    unset -f run_ingest
    if [ "$before_second" != "$(cat "$boxledger")" ]; then
        LEG_MACHINE_FILE=""
        bad "a SECOND ingest changed the box ledger — at-least-once is the assumption and a row written twice must be one row"
        return
    fi
    ok "a second ingest is byte-identical — the carrier is idempotent by line"

    # AND THE LEG REUSES WHAT ARRIVED. Same image, same drive set, a ledger this
    # leg never wrote a row into.
    LEDGER="$boxledger"
    run_leg "$dir"
    LEG_MACHINE_FILE=""
    if [ "$LEG_RC" != "0" ]; then
        bad "the leg over the ingested ledger was not green: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local missing="" n
    for n in 1_alpha 2_bravo; do
        grep -qE "^  drive ${n}: REUSED from drive-v1:[0-9a-f]{64} \(banked [0-9T:Z-]+\) machine=image:ami-0ing3st0ing3st000\$" \
            "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "no \`REUSED … machine=image:<ami>\` line for:${missing} — got: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "both ingested rows REUSED on the same image, each line naming machine=image:ami-0ing3st0ing3st000"

    # AND A DIFFERENT IMAGE IS A MISS. Without this the case above would be
    # green if the machine half had quietly left the key altogether.
    printf 'ami-0n0tth3sam3imag3\n' >"${WORK}/other-image-id"
    LEG_MACHINE_FILE="${WORK}/other-image-id"
    run_leg "$dir"
    LEG_MACHINE_FILE=""
    LEDGER="${WORK}/verdicts-ingest-source"
    if grep -q 'REUSED' "$LEG_OUT"; then
        bad "a DIFFERENT image reused rows banked on the first one: $(grep REUSED "$LEG_OUT")"
        return
    fi
    if ! grep -qE '^  miss: machine moved since drive-v1:[0-9a-f]{64} machine=image:ami-0n0tth3sam3imag3$' "$LEG_OUT"; then
        bad "the miss on another image does not name the machine and the machine it is now on: $(grep -F 'miss:' "$LEG_OUT" || echo '<no miss line>')"
        return
    fi
    ok "a box of ANOTHER image misses, and the miss names \`machine\` as the component that moved"
}

case_an_unreadable_machine_file_cannot_key() {
    CURRENT=case_an_unreadable_machine_file_cannot_key
    # A MACHINE THAT HAS THE FILE AND WILL NOT SHOW IT IS UNDECIDED, and an
    # undecided key that fell back to the host digest would be a Mac row and a
    # box row colliding under one label — the one failure the image half exists
    # to prevent. So it composes to could-not-look, which is exit 2, and never
    # to a run and never to a pass.
    local dir="${WORK}/set-badmachine" locked="${WORK}/locked-image-id"
    printf 'ami-0l0ck3d0l0ck3d000\n' >"$locked"
    chmod 000 "$locked"
    new_ledger badmachine
    plant_drive_set "$dir" 1_alpha:0
    LEG_MACHINE_FILE="$locked"
    run_leg "$dir"
    LEG_MACHINE_FILE=""
    chmod 644 "$locked"
    if ! grep -qF '  drive 1_alpha: could not key — this machine could not be digested' "$LEG_OUT"; then
        bad "the leg does not say the machine could not be digested: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if [ "$LEG_RC" != "2" ]; then
        bad "a drive whose machine could not be digested composed exit ${LEG_RC}, wanted 2 (could-not-look)"
        return
    fi
    if [ "$(ledger_drive_count)" != "0" ]; then
        bad "$(ledger_drive_count) row(s) were banked over a machine nothing could name"
        return
    fi
    ok "an unreadable machine file is could-not-look, exit 2, and banks nothing — never the host key"
}

case_an_unbanked_drive_runs() {
    CURRENT=case_an_unbanked_drive_runs
    local dir="${WORK}/set-unbanked"
    new_ledger unbanked
    plant_drive_set "$dir" 1_alpha:0 2_bravo:0 3_charlie:0
    run_leg "$dir"
    if grep -q 'REUSED' "$LEG_OUT"; then
        bad "a fresh ledger reused something: $(grep REUSED "$LEG_OUT")"
        return
    fi
    local missing="" n
    for n in 1_alpha 2_bravo 3_charlie; do
        grep -qE "^  drive ${n}: exit 0 \([0-9]+s\)\$" "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "against an empty ledger these drives did not run:${missing}"
        return
    fi
    ok "an empty ledger drove every member and reused none"
}

case_an_undecidable_key_is_exit_2() {
    CURRENT=case_an_undecidable_key_is_exit_2
    local dir="${WORK}/set-nokey"

    # PLANT ONE: no marker at all.
    new_ledger nokey
    plant_drive_set "$dir" 1_alpha:0
    plant_unmarked_drive "$dir" 2_unmarked
    run_leg "$dir"
    if [ "$LEG_RC" != "2" ]; then
        bad "a drive with no \`# drives:\` line gave exit ${LEG_RC}, wanted 2 — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qE "^  drive 2_unmarked: could not key — " "$LEG_OUT"; then
        bad "no \`could not key\` line for the unmarked drive: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep '^!! COULD NOT LOOK:' "$LEG_OUT" | grep '2_unmarked' >/dev/null; then
        bad "the composed COULD NOT LOOK line does not name the unmarked drive"
        return
    fi
    ok "a drive with no marker is could-not-look, named, and the leg is 2"

    # PLANT TWO: a marker naming a path that is not in the tree.
    new_ledger nokey-absent
    PLANT_DECL="scripts/there_is_no_such_file_here.sh"
    plant_drive_set "$dir" 1_absent:0
    PLANT_DECL="scripts/tests/drive_preamble.sh"
    run_leg "$dir"
    if [ "$LEG_RC" != "2" ]; then
        bad "a marker naming an absent path gave exit ${LEG_RC}, wanted 2"
        return
    fi
    if ! grep -E "^  drive 1_absent: could not key — " "$LEG_OUT" |
        grep 'there_is_no_such_file_here.sh' >/dev/null; then
        bad "the refusal does not name the path that expanded to nothing: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "a declared path expanding to nothing is could-not-look and names the path"

    # PLANT THREE: a body spelling a checkout path the marker does not cover.
    new_ledger nokey-uncovered
    plant_in_checkout "scripts/other.sh" '# a scratch subject the marker will not cover'
    PLANT_BODY_EXTRA='# reaches scripts/other.sh without declaring it'
    plant_drive_set "$dir" 1_uncovered:0
    PLANT_BODY_EXTRA=""
    run_leg "$dir"
    if [ "$LEG_RC" != "2" ]; then
        bad "a body spelling an undeclared checkout path gave exit ${LEG_RC}, wanted 2"
        return
    fi
    if ! grep -E "^  drive 1_uncovered: could not key — " "$LEG_OUT" |
        grep 'scripts/other.sh' >/dev/null; then
        bad "the floor did not name the uncovered path: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "a path the body spells and the marker does not cover is could-not-look, named"
    unplant_checkout
}

case_the_floor_reaches_every_top_level_the_tree_has() {
    CURRENT=case_the_floor_reaches_every_top_level_the_tree_has
    # THE FLOOR USED TO READ THREE TYPED PREFIXES — `scripts/<x>.(sh|py)`,
    # `quality/` and `apps/` — so a drive could read a doc, a compose file or
    # the secrets baseline undeclared and be REUSED over their changed bytes.
    # Three such sites were standing when the grammar was widened. The prefix
    # list is now derived from the measured tree, so this case asks the floor
    # about one path per SHAPE the old grammar could not see: a doc, a
    # top-level file, and a dotfile at the top level.
    local dir="${WORK}/set-toplevel" spelled
    for spelled in docs/product/build-contract.md compose.yaml .secrets.baseline; do
        new_ledger "toplevel-$(printf '%s' "$spelled" | tr -c 'a-zA-Z0-9' '_')"
        PLANT_BODY_EXTRA="# reaches ${spelled} without declaring it"
        plant_drive_set "$dir" 1_toplevel:0
        PLANT_BODY_EXTRA=""
        run_leg "$dir"
        if [ "$LEG_RC" != "2" ]; then
            bad "a body spelling ${spelled} undeclared gave exit ${LEG_RC}, wanted 2 — the floor still cannot see this top level"
            return
        fi
        # READ WHOLE, THEN MATCHED (the pipefail census): a quiet reader at a
        # pipeline tail closes the pipe and takes its producer's status with
        # it over 64 KiB.
        grep -E "^  drive 1_toplevel: could not key — " "$LEG_OUT" >"${WORK}/toplevel-key.out" 2>&1 || true
        if ! grep -qF "$spelled" "${WORK}/toplevel-key.out"; then
            bad "the floor refused but did not name ${spelled}: $(tr '\n' '|' <"$LEG_OUT")"
            return
        fi
        ok "${spelled} spelled and undeclared is could-not-look, named"
    done

    # THE NEGATIVE, in the same shape: declared, it keys and banks. Without
    # this the case above would pass for a floor that refused everything.
    new_ledger toplevel-declared
    PLANT_DECL="docs/product/build-contract.md"
    PLANT_BODY_EXTRA="# reaches docs/product/build-contract.md and says so"
    plant_drive_set "$dir" 1_toplevel:0
    PLANT_BODY_EXTRA=""
    PLANT_DECL="scripts/tests/drive_preamble.sh"
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ] || [ "$(ledger_planted_count)" != "1" ]; then
        bad "a DECLARED top-level path did not key and bank: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "the same path declared keys cleanly and banks — the floor is a floor, not a refusal of everything"
}

case_a_declaration_of_the_gate_carries_its_sourced_libraries() {
    CURRENT=case_a_declaration_of_the_gate_carries_its_sourced_libraries
    # `scripts/check.sh` IS TEN FILES. It sources nine libraries, and a drive
    # that declares the gate is driving all ten — so a byte moved in one of
    # them has to refuse the reuse. Keyed on check.sh alone it did not: the key
    # was identical and the leg vouched for bytes the run had never seen.
    #
    # THE VICTIM IS THE REAL `scripts/gate_refuse.sh`, because the claim is
    # about the SHIPPED expansion of a real declaration; a scratch copy would
    # prove that this case can write a file. One comment line, appended and
    # restored from saved bytes here and again on every exit path.
    local dir="${WORK}/set-sourced" lib="scripts/gate_refuse.sh"
    local saved="${WORK}/gate_refuse.saved"

    CURRENT="the reader names the libraries the gate sources"
    # SOURCED HERE, because `run_leg` sources the ledger inside its own
    # subshell and this half of the case asks the reader directly.
    local sourced
    # shellcheck source=scripts/gate_refuse.sh
    . "${ROOT}/scripts/gate_refuse.sh"
    # shellcheck source=scripts/gate_ledger.sh
    . "${ROOT}/scripts/gate_ledger.sh"
    sourced="$(drive_check_sh_sources "${ROOT}/scripts/check.sh")" || sourced=""
    if [ -z "$sourced" ]; then
        bad "drive_check_sh_sources read no library out of scripts/check.sh — the expansion has no subject"
        return
    fi
    printf '%s\n' "$sourced" >"${WORK}/sourced-libs.txt"
    if ! grep -qx "$lib" "${WORK}/sourced-libs.txt"; then
        bad "the sourced set does not name ${lib}: $(printf '%s' "$sourced" | tr '\n' ' ')"
        return
    fi
    ok "$(printf '%s\n' "$sourced" | awk 'END { print NR + 0 }') librarie(s) derived from the gate, ${lib} among them"

    CURRENT=case_a_declaration_of_the_gate_carries_its_sourced_libraries
    new_ledger sourced
    PLANT_DECL="scripts/check.sh"
    plant_drive_set "$dir" 1_alpha:0
    PLANT_DECL="scripts/tests/drive_preamble.sh"
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ] || [ "$(ledger_planted_count)" != "1" ]; then
        bad "the banking run over a drive declaring the gate did not bank: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local first_key
    first_key="$(ledger_planted_rows | awk 'NR==1{print $2}')"

    cp "${ROOT}/${lib}" "$saved"
    drive_at_exit "cp \"$saved\" \"${ROOT}/${lib}\" 2>/dev/null || true"
    printf '# one more comment byte, restored by this case\n' >>"${ROOT}/${lib}"
    run_leg "$dir"
    cp "$saved" "${ROOT}/${lib}"
    if [ "$(planted_reused_count)" != "0" ]; then
        bad "a moved byte in ${lib} was REUSED anyway — a declaration of the gate is not carrying what the gate sources"
        return
    fi
    grep -F "miss:" "$LEG_OUT" >"${WORK}/sourced-miss.out" 2>&1 || true
    if ! grep -qF "$lib" "${WORK}/sourced-miss.out"; then
        bad "the miss does not name ${lib} (banked at ${first_key}): $(cat "${WORK}/sourced-miss.out")"
        return
    fi
    ok "a byte in a library the gate sources refused the reuse, and the miss named the library rather than check.sh"
}

case_two_drives_with_identical_content_do_not_share_a_verdict() {
    CURRENT=case_two_drives_with_identical_content_do_not_share_a_verdict
    # THE KEY IS CONTENT PLUS THE NAME, and this is why the name is in it.
    # Everything else the key holds is content — the marker, the drive and
    # preamble bytes, the declared blobs, the machine — so two drives whose
    # content happens to be identical keyed identically and every member after
    # the first came back REUSED under its own name, reporting a verdict for a
    # run that never happened. `plant_drive_set` writes byte-identical bodies
    # apart from the name it echoes, so this is one `sed` away from being the
    # real shape; the plant below removes even that difference.
    local dir="${WORK}/set-twins" name
    new_ledger twins
    rm -rf "$dir"
    mkdir -p "$dir"
    printf '# a scratch drive set preamble — never sourced, always keyed\n' \
        >"${dir}/drive_preamble.sh"
    for name in 1_alpha 2_bravo 3_charlie; do
        cat >"${dir}/test_${name}.sh" <<'TWIN'
#!/bin/sh
# drives: scripts/tests/drive_preamble.sh
echo "a planted twin speaking"
exit 0
TWIN
        chmod +x "${dir}/test_${name}.sh"
    done
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "the leg over three byte-identical drives exited ${LEG_RC}: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if [ "$(planted_reused_count)" != "0" ]; then
        bad "a twin was REUSED on the FIRST run — three drives with one content are sharing one verdict: $(grep -F 'REUSED' "$LEG_OUT" | tr '\n' '|')"
        return
    fi
    local banked
    banked="$(ledger_planted_count)"
    if [ "$banked" != "3" ]; then
        bad "three green drives banked ${banked} row(s) — one key for three drives is one row for three drives"
        return
    fi
    if [ "$(ledger_planted_rows | awk '{print $2}' | LC_ALL=C sort -u | awk 'END { print NR + 0 }')" != "3" ]; then
        bad "three rows, fewer than three distinct keys — the name is not in the key"
        return
    fi
    ok "three byte-identical drives key three ways, run three times and bank three rows"

    # AND THE SECOND RUN REUSES ALL THREE, each under its own key: the name
    # separates them without making a reuse impossible.
    run_leg "$dir"
    if [ "$(planted_reused_count)" != "3" ]; then
        bad "the second run reused $(planted_reused_count) of 3 — separating the keys must not cost the reuse"
        return
    fi
    ok "the second run REUSES all three, each from its own key"
}

case_a_cited_path_is_subtracted_from_the_floor_and_from_no_key() {
    CURRENT=case_a_cited_path_is_subtracted_from_the_floor_and_from_no_key
    # A CITATION IS NOT A SUBJECT. The floor reads paths the body SPELLS, and a
    # drive that explains itself spells paths it never opens — so a declaration
    # was the only way to key, and every rung that moved a byte in a cited file
    # re-drove a drive that never reads it. `# cites:` tells the floor the
    # difference, and it is a VALVE: subtracted from the floor, added to no key,
    # counted and printed beside the drive.
    local dir="${WORK}/set-cites" subject="scripts/scratch_cited.sh" first_key second_key
    new_ledger cites
    plant_in_checkout "$subject" '# a scratch path this drive only talks about'

    # (1) SPELLED AND NEITHER DECLARED NOR CITED: could-not-look, as before.
    PLANT_BODY_EXTRA="# talks about ${subject} and neither declares nor cites it"
    plant_drive_set "$dir" 1_cited:0
    PLANT_BODY_EXTRA=""
    run_leg "$dir"
    if [ "$LEG_RC" != "2" ]; then
        bad "a spelled, undeclared, uncited path gave exit ${LEG_RC}, wanted 2 — the valve has widened the floor"
        return
    fi
    ok "spelled and neither declared nor cited is still could-not-look"

    # (2) CITED: it keys, the count is printed, and it banks.
    new_ledger cites-declared
    plant_drive_set "$dir" 1_cited:0
    printf '%s\n' "# cites: ${subject}" >>"${dir}/test_1_cited.sh"
    # The marker has to be in the first forty lines; the planted body is four.
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "a CITED path did not key: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qF "1 path(s) CITED, in no key" "$LEG_OUT"; then
        bad "the leg did not print the citation count — a valve nobody sees is an off switch: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "a cited path keys, and the leg prints the count beside the drive"
    first_key="$(ledger_planted_rows | awk 'NR==1{print $2}')"

    # (3) AND A BYTE IN IT DOES NOT RE-KEY — which is the whole purpose, and the
    # whole declared cost: a drive that cites a file it really reads is reused
    # over that file's changed bytes.
    printf '# one more comment byte\n' >>"${ROOT}/${subject}"
    run_leg "$dir"
    if [ "$(planted_reused_count)" = "0" ]; then
        bad "a byte in a CITED path refused the reuse — the citation is in the key after all: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "a byte in a cited path does not re-key: the citation is in no key, stated and printed"

    # (4) BUT THE CITATION LINE ITSELF IS IN THE KEY: moving a path out of
    # `# cites:` is a claim that the drive started reading it, and a claim that
    # left the key unchanged would be a reuse over a changed subject.
    new_ledger cites-moved
    plant_drive_set "$dir" 1_cited:0
    printf '%s\n' "# cites: ${subject}" >>"${dir}/test_1_cited.sh"
    run_leg "$dir"
    first_key="$(ledger_planted_rows | awk 'NR==1{print $2}')"
    plant_drive_set "$dir" 1_cited:0
    printf '%s\n' "# cites: ${subject} scripts/tests/drive_preamble.sh" >>"${dir}/test_1_cited.sh"
    run_leg "$dir"
    second_key="$(ledger_planted_rows | awk 'END{print $2}')"
    if [ "$first_key" = "$second_key" ]; then
        bad "the citation line moved and the key did not — a drive can change what it claims to read without re-keying"
        return
    fi
    ok "the citation LINE is in the key text, so a changed claim re-keys"
    unplant_checkout
}

case_only_a_green_drive_banks() {
    CURRENT=case_only_a_green_drive_banks
    local dir="${WORK}/set-onlygreen"
    new_ledger onlygreen
    plant_drive_set "$dir" 1_red:1 2_cannot:2 3_green:0
    run_leg "$dir"
    if [ "$LEG_RC" != "2" ]; then
        bad "wanted exit 2 (a could-not-look beside a red), got ${LEG_RC}"
        return
    fi
    local banked
    banked="$(ledger_planted_rows | awk '{print $5}' | tr '\n' ' ')"
    case " $banked " in
    *" 1_red "* | *" 2_cannot "*)
        bad "a non-green drive banked a row: ${banked}"
        return
        ;;
    esac
    run_leg "$dir"
    local missing="" n
    for n in 1_red 2_cannot; do
        grep -qE "^  drive ${n}: exit [12] \([0-9]+s\)\$" "$LEG_OUT" || missing="${missing} ${n}"
    done
    if [ -n "$missing" ]; then
        bad "a non-green drive was not re-driven on the second run:${missing}"
        return
    fi
    if ! grep -q "drive 3_green: REUSED" "$LEG_OUT"; then
        bad "the green drive beside them did not bank — the case proves nothing about only-green"
        return
    fi
    ok "the red and the could-not-look banked nothing and both ran again; the green beside them was reused"
}

case_a_reused_drive_keeps_its_shard_index() {
    CURRENT=case_a_reused_drive_keeps_its_shard_index
    local all="${WORK}/set-shard-all"
    local two="${WORK}/set-shard-two"
    new_ledger shard
    # The same two drives, byte-identical, in a set of their own: the key is the
    # drive's CONTENT and what it declares, never where it sits, so banking them
    # here banks them for the five-member set below.
    plant_drive_set "$all" 1_alpha:0 2_bravo:0 3_charlie:0 4_delta:0 5_echo:0
    plant_drive_set "$two" 1_alpha:0 2_bravo:0
    run_leg "$two"
    if [ "$(ledger_planted_count)" != "2" ]; then
        bad "the two-member banking run banked $(ledger_planted_count) row(s)"
        return
    fi
    local k seen_reused="" seen_ran="" seen_skipped=""
    for k in 0 1; do
        LEG_SHARD="$k 2"
        run_leg "$all"
        LEG_SHARD=""
        if [ "$LEG_RC" != "0" ]; then
            bad "shard ${k}/2 was not green: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
            return
        fi
        seen_reused="${seen_reused} $(sed -n 's/^  drive \([0-9a-z_]*\): REUSED.*/\1/p' "$LEG_OUT" | tr '\n' ' ')"
        seen_ran="${seen_ran} $(sed -n 's/^  drive \([0-9a-z_]*\): exit .*/\1/p' "$LEG_OUT" | tr '\n' ' ')"
        seen_skipped="${seen_skipped} $(sed -n 's/^  drive \([0-9a-z_]*\): not in shard.*/\1/p' "$LEG_OUT" | tr '\n' ' ')"
    done
    local n took
    for n in 1_alpha 2_bravo 3_charlie 4_delta 5_echo; do
        took=0
        case " $seen_reused " in *" $n "*) took=$((took + 1)) ;; esac
        case " $seen_ran " in *" $n "*) took=$((took + 1)) ;; esac
        if [ "$took" != "1" ]; then
            bad "${n} was taken ${took} time(s) across the two shards — reused:${seen_reused} ran:${seen_ran}"
            return
        fi
    done
    case " $seen_reused " in
    *" 1_alpha "* | *" 2_bravo "*) ;;
    *)
        bad "neither banked member was REUSED inside its shard — reused:${seen_reused}"
        return
        ;;
    esac
    if [ -z "$(printf '%s' "$seen_skipped" | tr -d ' ')" ]; then
        bad "no \`not in shard\` line at all — the shard printed nothing about what it did not run"
        return
    fi
    ok "each of the five members was taken exactly once across 0/2 and 1/2; the banked ones REUSED in their own shard"
}

case_no_reuse_runs_everything_and_banks() {
    CURRENT=case_no_reuse_runs_everything_and_banks
    local dir="${WORK}/set-novalve"
    new_ledger novalve
    plant_drive_set "$dir" 1_alpha:0 2_bravo:0
    run_leg "$dir"
    local before
    before="$(ledger_planted_count)"
    if [ "$before" != "2" ]; then
        bad "the banking run banked ${before} row(s), wanted 2"
        return
    fi
    LEG_NO_REUSE=1
    run_leg "$dir"
    LEG_NO_REUSE=""
    if [ "$LEG_RC" != "0" ]; then
        bad "the valve run was not green: exit ${LEG_RC}"
        return
    fi
    if grep -q 'REUSED' "$LEG_OUT"; then
        bad "DJB_SELFTEST_NO_REUSE=1 still reused a verdict: $(grep REUSED "$LEG_OUT")"
        return
    fi
    if ! grep -qF '== drive verdicts NOT consulted: DJB_SELFTEST_NO_REUSE is set ==' "$LEG_OUT"; then
        bad "the valve did not say so in the banner: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    local after
    after="$(ledger_planted_count)"
    if [ "$after" -le "$before" ]; then
        bad "the valve run banked nothing (${before} rows before, ${after} after) — a forced green is newer evidence for the same key"
        return
    fi
    # AND THE ENGINE IS ONE OF THEM. It is keyed like every other member now,
    # so the valve has to reach it too: a forced run that quietly reused the
    # engine's verdict would leave the one member nobody re-measured on the
    # machine the valve was typed for.
    if ! grep -qE "^  drive house-rules-engine: exit 0 \([0-9]+s\)\$" "$LEG_OUT"; then
        bad "DJB_SELFTEST_NO_REUSE=1 did not run the engine: $(grep -F 'house-rules-engine' "$LEG_OUT" | tr '\n' '|')"
        return
    fi
    if [ "$(ledger_engine_count)" -lt "1" ]; then
        bad "the valve run banked no engine row"
        return
    fi
    ok "the valve ran both drives AND the engine, said so, and still banked (${before} rows → ${after})"
}

# --- the engine's own verdict ------------------------------------------------
#
# WHAT IS UNDER DRIVE HERE, and what is not. These cases prove how the LEG
# treats the engine's inputs: that it keys the member on the listing the engine
# prints, banks a row named `house-rules-engine` on a green, reuses it by name
# and key, refuses the reuse when a listed path's bytes move, and is
# could-not-look — never a silent run and never a silent reuse — when the
# listing cannot be had. The engine itself is still shimmed (declared blind
# spot 2 above): nothing here says `quality.gate --selftest` is right, and
# nothing here says the REAL listing names the right paths. That is
# `--selftest-inputs`' own drive, and the engine's canaries.

case_the_engine_banks_on_its_inputs() {
    CURRENT=case_the_engine_banks_on_its_inputs
    new_ledger engine
    local dir="${WORK}/set-engine"
    plant_drive_set "$dir" 1_alpha:0
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "the banking run was not green: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qE "^  drive house-rules-engine: exit 0 \([0-9]+s\)\$" "$LEG_OUT"; then
        bad "the engine did not RUN on an empty ledger: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if [ "$(ledger_engine_count)" != "1" ]; then
        bad "a green engine banked $(ledger_engine_count) row(s), wanted exactly 1"
        return
    fi
    local row key
    row="$(ledger_engine_rows | tail -1)"
    key="$(printf '%s\n' "$row" | awk '{print $2}')"
    case "$key" in
    drive-v1:????????????????????????????????????????????????????????????????) ;;
    *)
        bad "the engine's row is not keyed \`drive-v1:<64 hex>\`: ${key}"
        return
        ;;
    esac
    # THE ROW IS THE SAME ROW EVERY DRIVE WRITES — same kind, same fields, same
    # ledger. A second grammar for one member would be the first tree where two
    # answers to one question disagreed.
    # READ TO EOF AND REDIRECTED, never `-q`: a quiet reader at the tail of a
    # pipeline under `pipefail` kills its own producer with SIGPIPE, and over
    # 64 KiB that reports the wrong answer every run (the census and its
    # measurements are in `test_sweep.sh`, `quiet_tail_sites`).
    if ! printf '%s\n' "$row" | grep -E ' drive [0-9T:Z-]+ house-rules-engine exit=0 took=[0-9]+ ' >/dev/null; then
        bad "the engine's row is not a \`drive\` row named house-rules-engine: ${row}"
        return
    fi
    if ! printf '%s\n' "$row" | grep -F 'docs/product/build-contract.md:' >/dev/null; then
        bad "the row's parts do not name a path the engine said it reads: ${row}"
        return
    fi
    ok "a green engine banked one drive-v1 row named house-rules-engine, keyed on what it reads"

    # AND THE SECOND RUN DOES NOT RUN IT.
    run_leg "$dir"
    if [ "$LEG_RC" != "0" ]; then
        bad "the reusing run was not green: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qE "^  drive house-rules-engine: REUSED from ${key} \(banked [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]+Z\) machine=" "$LEG_OUT"; then
        bad "no \`drive house-rules-engine: REUSED from ${key} (banked <date>) machine=<m>\` line: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if grep -qE "^  drive house-rules-engine: exit " "$LEG_OUT"; then
        bad "the engine RAN anyway after being reused: $(grep -F 'house-rules-engine' "$LEG_OUT" | tr '\n' '|')"
        return
    fi
    if ! grep -q "selftest: 2 drive(s) green · 0 red · 0 could-not-look" "$LEG_OUT"; then
        bad "a reused engine is not counted green: $(grep 'selftest:' "$LEG_OUT" || true)"
        return
    fi
    if [ "$(ledger_engine_count)" != "1" ]; then
        bad "the reusing run banked another engine row ($(ledger_engine_count) in all)"
        return
    fi
    ok "the second run REUSED the engine by name and key, did not run it, and counted it green"
}

case_a_moved_engine_input_refuses_the_reuse() {
    CURRENT=case_a_moved_engine_input_refuses_the_reuse
    local dir="${WORK}/set-engine-moved"
    local listed="scripts/scratch_engine_listed.txt"
    local unlisted="scripts/scratch_engine_unlisted.txt"
    local inputs="${WORK}/engine-inputs-moved.txt"

    new_ledger enginemoved
    plant_in_checkout "$listed" '# a scratch path the engine says it reads'
    plant_in_checkout "$unlisted" '# a scratch path the engine says nothing about'
    printf '%s\n' "$listed" "docs/product/build-contract.md" >"$inputs"
    LEG_INPUTS="$inputs"
    plant_drive_set "$dir" 1_alpha:0
    run_leg "$dir"
    LEG_INPUTS=""
    if [ "$LEG_RC" != "0" ] || [ "$(ledger_engine_count)" != "1" ]; then
        bad "the banking run over a scratch input did not bank: exit ${LEG_RC} — $(tr '\n' '|' <"$LEG_OUT")"
        unplant_checkout
        return
    fi
    local first_key
    first_key="$(ledger_engine_rows | tail -1 | awk '{print $2}')"

    # PLANT ONE: A BYTE IN A PATH THE ENGINE SAYS IT READS.
    printf '# one more comment byte\n' >>"${ROOT}/${listed}"
    LEG_INPUTS="$inputs"
    run_leg "$dir"
    LEG_INPUTS=""
    if grep -qE "^  drive house-rules-engine: REUSED" "$LEG_OUT"; then
        bad "a moved byte in ${listed} was REUSED anyway — the key does not see what the engine reads"
        unplant_checkout
        return
    fi
    if ! grep -qE "^  drive house-rules-engine: exit 0 \([0-9]+s\)\$" "$LEG_OUT"; then
        bad "the engine did not RUN after its input moved: $(tr '\n' '|' <"$LEG_OUT")"
        unplant_checkout
        return
    fi
    if ! grep -qF "miss: ${listed} moved since ${first_key}" "$LEG_OUT"; then
        bad "the miss does not name ${listed} and the key it moved from: $(grep -F 'miss:' "$LEG_OUT" || echo '<no miss line>')"
        unplant_checkout
        return
    fi
    ok "a byte in a path the engine reads refused the reuse and the miss named the path and the old key"

    # PLANT TWO: A BYTE OUTSIDE EVERYTHING THE ENGINE READS. It is in the
    # checkout and in the measured tree; it is in no declaration, so it is in
    # no key, so the verdict stands. This is the half that makes the first half
    # mean something: a key that re-keyed on every byte would be no key at all.
    local second_key
    second_key="$(ledger_engine_rows | tail -1 | awk '{print $2}')"
    printf '# one more comment byte\n' >>"${ROOT}/${unlisted}"
    LEG_INPUTS="$inputs"
    run_leg "$dir"
    LEG_INPUTS=""
    if ! grep -qE "^  drive house-rules-engine: REUSED from ${second_key} " "$LEG_OUT"; then
        bad "a byte moved OUTSIDE everything the engine reads refused the reuse: $(grep -F 'house-rules-engine' "$LEG_OUT" | tr '\n' '|')"
        unplant_checkout
        return
    fi
    ok "a byte outside every declared input left the engine's verdict standing"
    unplant_checkout
}

case_an_unprintable_engine_scope_is_exit_2() {
    CURRENT=case_an_unprintable_engine_scope_is_exit_2
    local dir="${WORK}/set-engine-nokey"
    local refusal="${WORK}/engine-inputs-refused.txt"

    # THE ENGINE'S OWN REFUSAL, in the shape `--selftest-inputs` prints it: the
    # reason on stdout and NO paths at all, because a list that quietly lost a
    # member would key a verdict for a tree nobody measured.
    new_ledger enginenokey
    cat >"$refusal" <<'REFUSED'
‼ --selftest-inputs COULD NOT LOOK (exit 2). A list that quietly lost a member would key a verdict for a tree nobody measured, so nothing is printed:
  !! rule 9: scope path names 'apps/nowhere/*.py', which expands to nothing on this tree
REFUSED
    plant_drive_set "$dir" 1_alpha:0
    LEG_INPUTS="$refusal"
    LEG_INPUTS_RC=2
    run_leg "$dir"
    LEG_INPUTS=""
    LEG_INPUTS_RC=""
    if [ "$LEG_RC" != "2" ]; then
        bad "an engine whose inputs would not print gave exit ${LEG_RC}, wanted 2 — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qE "^  drive house-rules-engine: could not key — .*--selftest-inputs.* exited 2" "$LEG_OUT"; then
        bad "no \`could not key\` line naming the engine's exit 2: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qF "apps/nowhere/*.py" "$LEG_OUT"; then
        bad "the refusal does not carry the engine's own reason: $(grep -F 'could not key' "$LEG_OUT" || true)"
        return
    fi
    if grep -qE "^  drive house-rules-engine: (exit|REUSED)" "$LEG_OUT"; then
        bad "the engine was run or reused after its inputs could not be derived: $(grep -F 'house-rules-engine' "$LEG_OUT" | tr '\n' '|')"
        return
    fi
    if [ "$(ledger_engine_count)" != "0" ]; then
        bad "a could-not-look engine banked $(ledger_engine_count) row(s)"
        return
    fi
    if ! grep -qF '!! COULD NOT LOOK: house-rules-engine' "$LEG_OUT"; then
        bad "the engine is not named in the could-not-look list: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qE "^  drive 1_alpha: exit 0 \([0-9]+s\)\$" "$LEG_OUT"; then
        bad "the drives did not still run after the engine could not be keyed"
        return
    fi
    ok "an engine whose inputs would not print is could-not-look, never run, never reused, never banked"

    # AND AN EMPTY LISTING AT EXIT 0 IS THE SAME ANSWER. An engine that reads
    # nothing is not an engine; keying it on nothing would reuse one verdict
    # for every tree there will ever be.
    new_ledger engineempty
    : >"${WORK}/engine-inputs-empty.txt"
    LEG_INPUTS="${WORK}/engine-inputs-empty.txt"
    run_leg "$dir"
    LEG_INPUTS=""
    if [ "$LEG_RC" != "2" ]; then
        bad "an empty listing at exit 0 gave exit ${LEG_RC}, wanted 2 — $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if ! grep -qF 'an engine that reads nothing is not an engine' "$LEG_OUT"; then
        bad "no refusal naming the empty listing: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    ok "an empty listing at exit 0 is could-not-look too"
}

case_the_engines_declaration_covers_exactly_its_inputs() {
    # WHY THIS CASE EXISTS, and it is the floor under the whole member. The
    # engine reads more than a thousand paths, and declaring each of them by
    # name costs 47 s of key arithmetic and a `parts=` field five times the
    # size of the whole ledger — measured. So the declaration COLLAPSES a
    # directory whose every file in the measured tree is an input. Two ways
    # that can be wrong and neither is visible in a green run: a collapse that
    # swallows a file the engine does NOT read re-keys the member on bytes it
    # never read (the `apps/**` shape the criteria rejected by name), and a
    # collapse that misses an input keys a verdict over bytes nobody measured.
    # So the equality is asserted, both directions, over a world with a real
    # collapse in it.
    CURRENT=case_the_engines_declaration_covers_exactly_its_inputs
    local dir="${WORK}/set-engine-cover"
    local inputs="${WORK}/engine-inputs-cover.txt"
    local collapsible="scripts/tests/fixtures/collection_world/apps/world_alpha/nested"
    mkdir -p "$dir"

    {
        git ls-files -- "$collapsible"
        printf '%s\n' "scripts/tests/drive_preamble.sh"
        printf '%s\n' "apps/nowhere/never_written.py"
    } | LC_ALL=C sort -u >"$inputs"
    if [ "$(awk 'END { print NR + 0 }' "$inputs")" -lt 4 ]; then
        bad "the fixture world is too small to falsify anything: $(tr '\n' ' ' <"$inputs")"
        return
    fi

    local out
    out="$(
        set +e
        PATH="${SHIM_BIN}:${PATH}"
        export PATH
        DJB_FAKE_INPUTS="$inputs"
        export DJB_FAKE_INPUTS
        DJB_SELFTEST_DRIVES_DIR="$dir"
        export DJB_SELFTEST_DRIVES_DIR
        DJB_GATE_LEDGER="$LEDGER"
        export DJB_GATE_LEDGER
        . scripts/gate_refuse.sh
        . scripts/gate_ledger.sh
        . "$EXTRACT_DUR"
        . "$EXTRACT"
        selftest_tally_reset
        selftest_drive_listing || exit 3
        synth="$(selftest_engine_drive_file "$SELFTEST_DRIVE_LISTING")" || exit 4
        file="${synth#ok }"
        # EXPAND EVERY DECLARATION THROUGH THE EXPANDER THE KEY USES, never
        # a second one: what this compares is what the key digests.
        decls="$(head -1 "$file")"
        decls="${decls#*drives:}"
        for d in $decls; do
            drive__expand "$SELFTEST_DRIVE_LISTING" "$d" | awk '{print $2}'
        done | LC_ALL=C sort -u
        printf 'DECLARED %s\n' "$decls"
    )" || true

    local expanded declared_line wanted
    expanded="${WORK}/engine-cover-expanded.txt"
    printf '%s\n' "$out" | grep -v '^DECLARED ' >"$expanded"
    declared_line="$(printf '%s\n' "$out" | sed -n 's/^DECLARED //p')"
    if [ -z "$declared_line" ]; then
        bad "the engine's drive file was never written: $(printf '%s' "$out" | tr '\n' '|')"
        return
    fi
    # The wanted set is the listing MINUS the paths the measured tree does not
    # hold — `plant_paths()` names files the canaries create, and a path that
    # is in no tree has no blob to digest.
    wanted="${WORK}/engine-cover-wanted.txt"
    git ls-files -- "$collapsible" >"$wanted"
    printf '%s\n' "scripts/tests/drive_preamble.sh" >>"$wanted"
    LC_ALL=C sort -u -o "$wanted" "$wanted"
    if ! diff -u "$wanted" "$expanded" >"${WORK}/engine-cover.diff" 2>&1; then
        bad "the declaration does not expand to exactly what the engine reads: $(head -12 "${WORK}/engine-cover.diff" | tr '\n' '|')"
        return
    fi
    case " $declared_line " in
    *" ${collapsible}/ "*) ;;
    *)
        bad "a directory whose every file is an input was not collapsed — the declaration is $(printf '%s' "$declared_line" | wc -w | tr -d ' ') path(s) long"
        return
        ;;
    esac
    ok "the declaration collapsed ${collapsible}/ and expands to exactly the paths the engine reads, no more and no fewer"
}

# --- run ----------------------------------------------------------------------

# --- the member clock -------------------------------------------------------

case_a_drives_seconds_reach_the_member_durations_reader() {
    # WHY THIS CASE EXISTS. The `--loop`'s always-on set is DERIVED from a
    # committed measurement of every member's seconds, and a drive's seconds
    # come from this leg. Two failure modes are silent: the leg could stop
    # handing them over (the set then derives from a file that never learns a
    # drive's real price), and a member that grew past the floor could go on
    # being run by every loop with nobody told. The second is the announcement
    # this case drives, because it is the one a reader sees.
    CURRENT=case_a_drives_seconds_reach_the_member_durations_reader
    new_ledger clock
    local dir="${WORK}/set-clock" durations="${WORK}/clock-durations.json"
    # THE SECONDS ARE TYPED, NEVER BORROWED, and two of them rather than one.
    # This case used to rest on "the planted drive takes about a second": it
    # does on a laptop under load, and on a c7g verifier box it takes 0 s, so
    # the case was red there for the machine's speed rather than for the leg's
    # behaviour. The laptop's own second was an accident too — the FIRST member
    # to consult a verdict paid for `gate_measured_tree`'s `git add -A`, and
    # that member used to be this planted drive; the engine is keyed now and
    # pays for the listing instead. Two seconds is the cheapest thing that is
    # true on every machine. `PLANT_BODY_EXTRA` is a global, so it is put back.
    # Recorded at 0 and measured against a floor of 1, its live seconds land on
    # the other side of the floor from its recorded ones — which is exactly the
    # sentence a member that grew must print at the bank.
    PLANT_BODY_EXTRA='sleep 2'
    plant_drive_set "$dir" 1_alpha:0
    PLANT_BODY_EXTRA=""
    cat >"$durations" <<'JSON'
{
  "measured_at": "plantedtree",
  "machine": "Scratch 0.0",
  "members": {
    "1_alpha": 0
  }
}
JSON
    LEG_MODE=""
    LEG_UNIT=""
    DJB_GATE_MEMBER_DURATIONS="$durations"
    DJB_ALWAYS_ON_FLOOR=1
    export DJB_GATE_MEMBER_DURATIONS DJB_ALWAYS_ON_FLOOR
    run_leg "$dir"
    unset DJB_GATE_MEMBER_DURATIONS DJB_ALWAYS_ON_FLOOR
    LEG_UNIT="x"
    if [ "$LEG_RC" != "0" ]; then
        bad "the green set gave exit ${LEG_RC}: $(tr '\n' '|' <"$LEG_OUT")"
        return
    fi
    if grep -qF 'above the loop floor' "$LEG_OUT" &&
        grep -qF 'leaves the always-on set at the next --store-durations' "$LEG_OUT"; then
        ok "a member whose live seconds crossed the floor is ANNOUNCED, with what happens next"
    else
        bad "no floor-crossing sentence for a member recorded at 0 s that took longer: $(tr '\n' '|' <"$LEG_OUT")"
    fi

    # AND NOT ON A SUBSET RUN. Seconds from a `--loop` or a `--leg` would be a
    # measurement of a part written into the file the whole set derives from,
    # so the recorder declines and says nothing at all.
    new_ledger clockloop
    plant_drive_set "$dir" 1_alpha:0
    PLANT_BODY_EXTRA=""
    LEG_MODE="--loop"
    DJB_GATE_MEMBER_DURATIONS="$durations"
    DJB_ALWAYS_ON_FLOOR=1
    export DJB_GATE_MEMBER_DURATIONS DJB_ALWAYS_ON_FLOOR
    run_leg "$dir"
    unset DJB_GATE_MEMBER_DURATIONS DJB_ALWAYS_ON_FLOOR
    LEG_MODE=""
    if grep -qF 'above the loop floor' "$LEG_OUT"; then
        bad "a subset run announced a floor crossing — its seconds are about a part of the gate and must not reach the measurement"
    else
        ok "a subset run records nothing and announces nothing"
    fi
}

case_all_green_prints_one_line_per_drive_and_the_summary
case_two_red_drives_are_both_named_and_the_leg_is_exit_1
case_a_could_not_look_drive_outranks_a_red_one_and_both_are_named
case_a_red_engine_selftest_still_runs_every_drive_and_the_leg_is_exit_2
case_every_exit_in_the_leg_body_is_inside_a_drive_subshell
case_every_registered_drive_line_and_sentinel_survives_the_function
case_the_deploy_blind_spot_banner_is_unchanged
case_the_gate_calls_the_function_and_owns_its_one_exit
case_a_banked_drive_is_reused_and_named
case_a_moved_driven_byte_refuses_the_reuse
case_an_ingested_row_reuses_on_the_same_image
case_an_unreadable_machine_file_cannot_key
case_an_unbanked_drive_runs
case_an_undecidable_key_is_exit_2
case_the_floor_reaches_every_top_level_the_tree_has
case_a_declaration_of_the_gate_carries_its_sourced_libraries
case_two_drives_with_identical_content_do_not_share_a_verdict
case_a_cited_path_is_subtracted_from_the_floor_and_from_no_key
case_only_a_green_drive_banks
case_a_reused_drive_keeps_its_shard_index
case_no_reuse_runs_everything_and_banks
case_the_engine_banks_on_its_inputs
case_a_moved_engine_input_refuses_the_reuse
case_an_unprintable_engine_scope_is_exit_2
case_the_engines_declaration_covers_exactly_its_inputs
case_a_drives_seconds_reach_the_member_durations_reader

echo "test_selftest_leg: ${PASSED} passed · ${FAILED} failed"
echo "           leg body: $(wc -l <"$EXTRACT" | tr -d ' ') line(s) between the sentinels into ${EXTRACT}"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the selftest leg no longer composes one exit out of its whole drive set." >&2
    echo "   A leg that stops at the first red teaches a builder one failure per" >&2
    echo "   25-minute gate, which is the row this drive was written to close; a leg" >&2
    echo "   whose registrations left the function hides a drive nothing invokes." >&2
    exit 1
fi
exit 0
