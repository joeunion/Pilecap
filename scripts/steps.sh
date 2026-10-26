#!/usr/bin/env bash
# The one step harness, sourced by setup.sh, rung_start.sh and verify_start.sh, on gate_refuse.sh's one clock.
#   step_begin <label>   `== step <n>/<STEP_TOTAL> · <label>`      step_end     `   [<t>] step <n> done`
#   step <name>          `== <name>`, closing the step before it     step_close   `  (<name>: <t>)`, once
#   say <words>          `   <words>`
# RUN_START is the clock at source; a caller's total is `clock_ms` minus it.
# shellcheck source=scripts/gate_refuse.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || return 2

STEP_N=0
STEP_START=0
STEP_NAME=""
RUN_START=$(clock_ms)

step_begin() {
    STEP_N=$((STEP_N + 1))
    STEP_START=$(clock_ms)
    printf '\n== step %d/%d · %s\n' "$STEP_N" "$STEP_TOTAL" "$1"
}

step_end() {
    printf '   [%s] step %d done\n' "$(clock_fmt $(($(clock_ms) - STEP_START)))" "$STEP_N"
}

step() {
    step_close
    printf '\n== %s\n' "$1"
    STEP_NAME="$1"
    STEP_START=$(clock_ms)
}

step_close() {
    [ -n "$STEP_NAME" ] || return 0
    printf '  (%s: %s)\n' "$STEP_NAME" "$(clock_fmt $(($(clock_ms) - STEP_START)))"
    STEP_NAME=""
}

say() { printf '   %s\n' "$*"; }
