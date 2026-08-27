#!/usr/bin/env bash
# The gate's verdict ledger — sourced by check.sh and the pre-push hook. BASH ONLY:
# sourced into an interactive zsh, `local path` ties to $PATH and every helper
# dies silently.
#
# The gate's verdict is a property of a TREE, not of who asked for it. A full
# green run records the content address of what it measured; a later stage
# about to measure identical bytes honours the verdict instead of re-deriving a
# deterministic result. Three properties keep it honest:
#
#  1. THE KEY IS WHAT WAS MEASURED, not what was committed: the working tree's
#     content address (tracked + untracked-non-ignored files), computed through
#     a TEMPORARY index so neither the real index nor the tree is touched. On a
#     clean tree it equals `git rev-parse HEAD^{tree}` — so a verdict earned
#     before a commit vouches for the commit after it.
#  2. A VERDICT IS ONLY EARNED BY A COMPLETE GREEN FULL RUN. Exit 1 records
#     nothing (a red run re-explains itself every time); exit 2 records nothing
#     and never can. --fast and --loop never record: a partial run must never
#     vouch for a tree.
#  3. A VERDICT NAMES A TREE THAT STILL EXISTED WHEN THE RUN ENDED: measured at
#     start AND end; if they differ (agents edit concurrently), the run's pass
#     still prints but earns no carry-forward.
#
# Trust class, stated: this is a local file an agent could echo a line into,
# exactly as `git push --no-verify` is one flag away. The hooks were never a
# security boundary; CI re-runs everything from a fresh checkout.
#
# The run log beside it answers "what happened to a full run that earned no
# verdict" — a red leg, exit 2, a kill at the tool's ten-minute ceiling, or a
# tree edited mid-run — one line per unsettled run, keyed by starting tree, so
# the next agent reads what happened instead of guessing from an exit code.

GATE_LEDGER_SCHEMA=v1

# ---- who asked -------------------------------------------------------
#
# THE QUESTION THE LEDGER COULD NOT ANSWER. The doctrine is one full gate per
# push. The measurement is 330 full runs in six days. Both of those can be true
# — a quality rung must run the full gate, a PM banks a verdict before a merge
# window, a red push re-runs — but until now every recorded line looked
# identical, so the gap between doctrine and population was un-auditable: nobody
# could say which of those 330 were the wall doing its job and which were
# something else. So each full run now records WHO ASKED.
#
# MEASUREMENT, NOT ENFORCEMENT, and deliberately so this cycle. No run is
# refused for its caller, no caller is privileged, and an unrecognised value is
# recorded as `unstated` with a note rather than rejected. First you count the
# population; only then is there anything to argue about refusing.
#
# THE VOCABULARY IS CLOSED, because a free-text field is a field nobody can
# group by:
#
#   push-wall     the pre-push hook ran it. The doctrine's own case.
#   quality-rung  a builder whose rung changes `quality/**` or the dependencies,
#                 where the full gate uniquely binds (rung-execution §3's two
#                 named exceptions).
#   pm-bank       the PM banking a verdict for a tree ahead of a push or a merge
#                 window.
#   unstated      nobody said. The default, and NOT a synonym for "wrong" —
#                 every line written before this field existed is this.
#
# HOW IT IS SET: `DJB_GATE_CALLER=<kind>` in the gate's environment. The
# pre-push hook exports `push-wall` for itself; everything else is the caller
# saying so. It is read at record time, never cached.
#
# WHERE IT IS NOT WRITTEN: `djb-gate-last-full`, which is a duration cache read
# by `gate_run_announce`'s `grep ' green$'` and not part of the population being
# censused. Named here rather than left to be discovered.
GATE_CALLER_KINDS="push-wall quality-rung pm-bank unstated"

# gate_caller — the caller kind for this run, always exactly one token from the
# closed set above, on stdout.
gate_caller() {
    local want=${DJB_GATE_CALLER:-}
    [ -n "$want" ] || {
        printf 'unstated\n'
        return 0
    }
    case " $GATE_CALLER_KINDS " in
    *" $want "*)
        printf '%s\n' "$want"
        return 0
        ;;
    esac
    # Loud, and still recorded. An unknown caller IS unstated — but a typo that
    # silently became `unstated` would be a measurement quietly losing a run.
    echo "  note: DJB_GATE_CALLER='$want' is not one of: $GATE_CALLER_KINDS — recording 'unstated'" >&2
    printf 'unstated\n'
}

# Shared across worktrees on purpose: --git-common-dir is the ONE .git for the
# checkout family, so a verdict earned in one worktree is honoured by another
# measuring identical bytes. Never committed — git does not track its own dir.
gate_local_path() {
    local common
    common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
    case "$common" in
    /*) ;;
    *) common="$(git rev-parse --show-toplevel)/$common" ;;
    esac
    printf '%s\n' "$common/$1"
}

gate_ledger_path() { gate_local_path djb-gate-verdicts; }
gate_runs_path() { gate_local_path djb-gate-runs; }
gate_last_full_path() { gate_local_path djb-gate-last-full; }

# The content address of the working state. GIT_INDEX_FILE points `git add` at
# a scratch index, so the real index is untouched; `git add -A` honours
# .gitignore, which makes the key "the content the gate can read" rather than
# "the content plus every build artefact".
gate_measured_tree() {
    local idx tree
    idx=$(mktemp "${TMPDIR:-/tmp}/djb-gate-index.XXXXXX") || return 1
    rm -f "$idx" # git wants to create it, not inherit an empty one
    if ! GIT_INDEX_FILE="$idx" git read-tree HEAD >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    if ! GIT_INDEX_FILE="$idx" git add -A >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    tree=$(GIT_INDEX_FILE="$idx" git write-tree 2>/dev/null)
    rm -f "$idx"
    [ -n "$tree" ] || return 1
    printf '%s\n' "$tree"
}

# gate_ledger_record <tree> <legs-csv> — one line, appended, schema first.
#
# `caller=` is APPENDED, at the end, on purpose: `gate_ledger_lookup` matches
# `" <tree> full "` and `^v1 `, and `gate_run_lookup` reads field 4, so every
# line written before this field existed goes on being read exactly as it was.
# The schema tag stays `v1` because nothing that could already parse a line
# stopped being able to.
gate_ledger_record() {
    local tree=$1 legs=$2 path
    path=$(gate_ledger_path) || return 1
    printf '%s %s full %s %s caller=%s\n' \
        "$GATE_LEDGER_SCHEMA" "$tree" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$legs" \
        "$(gate_caller)" >>"$path"
}

# gate_ledger_lookup <tree> → most recent matching line on stdout, exit 0;
# exit 1 when the tree has no verdict.
gate_ledger_lookup() {
    local tree=$1 path line
    path=$(gate_ledger_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " $tree full " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# gate_has_green <tree> → exit 0 iff a full green run measured this tree.
gate_has_green() { gate_ledger_lookup "$1" >/dev/null; }

# ---- the partition's verdicts -----------------------------------------
#
# ONE MORE CONSUMER OF THE SAME PATTERN, and it lives here rather than in
# `quality/partition.py` for the reason the header states about this whole file:
# a verdict is a property of what was measured, and the rules for banking one
# have exactly one home. The partition's key is not a tree hash — it is
# `<closure hash>:<discovery digest>` (docs/product/partition-closure.md §4),
# both parts, because the closure's FILES are not the partition's whole input:
# platform behaviour reaches through discovery, so the population the walks
# return is part of the key or the skip is unsound.
#
# THE SAME THREE PROPERTIES HOLD. A row is only written by a complete green full
# run (`scripts/check.sh` records it after the second pytest pass); a stale key
# is a miss and never a partial match; and a key this file cannot parse is
# EXIT 2, not a miss — a mistyped invocation is never a silent skip.
#
# `DJB_PARTITION_LEDGER` points these at a scratch file, which is how §8's
# canaries forge a stale row without the forge ever being able to become a
# banked verdict.

#: `<64 hex>:<64 hex>` and nothing else. A row that is not this shape is not a
#: row this gate wrote, and reading it as an ordinary miss would turn a corrupt
#: ledger into a silent full run — which is the tolerable direction, but it is
#: also the direction in which nobody ever finds out.
PARTITION_KEY_RE='^[0-9a-f]{64}:[0-9a-f]{64}$'

partition_ledger_path() {
    if [ -n "${DJB_PARTITION_LEDGER:-}" ]; then
        printf '%s\n' "$DJB_PARTITION_LEDGER"
        return 0
    fi
    gate_local_path djb-partition-verdicts
}

# partition_ledger_record <key> — one line, appended, schema first.
partition_ledger_record() {
    local key=$1 path
    printf '%s' "$key" | grep -Eq "$PARTITION_KEY_RE" || {
        echo "partition_ledger_record: '$key' is not a partition key" >&2
        return 2
    }
    path=$(partition_ledger_path) || return 1
    printf '%s %s partition %s caller=%s\n' \
        "$GATE_LEDGER_SCHEMA" "$key" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(gate_caller)" >>"$path"
}

# partition_ledger_lookup <key> → the most recent matching line on stdout,
# exit 0; exit 1 when this key has no verdict; exit 2 when the ledger holds a
# line whose key is not a key.
partition_ledger_lookup() {
    local key=$1 path line bad
    path=$(partition_ledger_path) || return 1
    [ -f "$path" ] || return 1
    # The unparseable clause first, and over the WHOLE file: a corrupt row is a
    # statement about this ledger's health, not about the key being asked for,
    # so it outranks both the hit and the miss.
    bad=$(awk -v schema="$GATE_LEDGER_SCHEMA" '$1==schema && $3=="partition" && $2 !~ /^[0-9a-f]{64}:[0-9a-f]{64}$/ {print; exit}' "$path")
    if [ -n "$bad" ]; then
        echo "partition_ledger_lookup: the ledger holds a row whose key cannot be parsed: $bad" >&2
        return 2
    fi
    line=$(grep -F " $key partition " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    printf '%s\n' "$line"
}

# ---- the run log ------------------------------------------------------------

GATE_RUN_TREE=""    # what the run started on
GATE_RUN_LEG=""     # the leg now running, as gate_leg last named it
GATE_RUN_T0=""      # epoch seconds at start
GATE_RUN_SETTLED="" # set once this run's one line (or its verdict) is written
GATE_RUN_ARMED=""   # set by gate_run_start; every helper no-ops without it
GATE_RUN_CALLER="unstated" # resolved ONCE at start, so the note is printed
#                          # once and a trap firing after a kill cannot re-derive
#                          # a different answer than the line the run announced.

# Only the FULL gate calls this; --fast and --loop write nothing anywhere.
gate_run_start() {
    GATE_RUN_TREE=${1:-unknown-tree}
    GATE_RUN_T0=$(date +%s)
    GATE_RUN_CALLER=$(gate_caller)
    GATE_RUN_ARMED=1
}

gate_leg() {
    GATE_RUN_LEG=$1
    echo "- $2"
}

# One line, appended, once — idempotent by the settled flag, so a killed run
# whose EXIT trap then fires cannot relabel itself red.
gate_run_note() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    [ -z "$GATE_RUN_SETTLED" ] || return 0
    GATE_RUN_SETTLED=1
    local path
    path=$(gate_runs_path) || path="<no git directory>"
    if ! printf '%s %s %s %s caller=%s\n' "$GATE_LEDGER_SCHEMA" "$GATE_RUN_TREE" \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" "$GATE_RUN_CALLER" >>"$path"; then
        printf 'run log could not be written to %s: %s is unrecorded\n' "$path" "$1" >&2 || true
    fi
}

gate_run_verdict_written() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    GATE_RUN_SETTLED=1
}

# The duration of a COMPLETED full run, for the next run's announcement.
gate_run_last_full() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    [ -n "$GATE_RUN_T0" ] || return 0
    local path
    path=$(gate_last_full_path) || return 0
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$(($(date +%s) - GATE_RUN_T0))" "$1" >>"$path" || true
}

# From the full gate's EXIT trap: decide the outcome when the gate has not
# already said. 129/130/143 without a settlement is a KILL that hit a leg's
# child — it must never be relabelled red.
gate_run_finish() {
    [ -n "$GATE_RUN_ARMED" ] || return 0
    local rc=${1:-0}
    case "$rc" in
    0) gate_run_note "unsettled" ;;
    2) gate_run_note "exit-2:${GATE_RUN_LEG:-before-first-leg}" ;;
    129 | 130 | 143) gate_run_note "killed:${GATE_RUN_LEG:-before-first-leg}" ;;
    *) gate_run_note "red:${GATE_RUN_LEG:-before-first-leg}" ;;
    esac
    case "$rc" in
    0) gate_run_last_full green ;;
    2) gate_run_last_full exit-2 ;;
    129 | 130 | 143) : ;; # a killed run's length is the killer's choice
    *) gate_run_last_full red ;;
    esac
}

# From the full gate's TERM/INT/HUP trap: name the leg, write the line, exit
# 143 so the EXIT trap still runs. PIPE ignored first — after a kill the reader
# is usually already gone.
gate_run_killed() {
    trap '' PIPE
    gate_run_note "killed:${GATE_RUN_LEG:-before-first-leg}"
    exit 143
}

# gate_run_lookup <tree> → the OUTCOME word of the most recent run-log line for
# that tree, so a reader can tell a red run from a killed one.
gate_run_lookup() {
    local tree=$1 path line
    path=$(gate_runs_path) || return 1
    [ -f "$path" ] || return 1
    line=$(grep -F " $tree " "$path" | grep "^$GATE_LEDGER_SCHEMA " | tail -1)
    [ -n "$line" ] || return 1
    awk '{print $4}' <<<"$line"
}

# Printed by the full gate before its first leg: what happened to the previous
# run on THIS tree, and a measured time estimate.
gate_run_announce() {
    local path secs line prior
    # The caller this run will record, said out loud before the first leg.
    # A field nobody can see at the time it is written is a field nobody
    # notices going wrong.
    if [ "$GATE_RUN_CALLER" = "unstated" ]; then
        echo "- caller: unstated (set DJB_GATE_CALLER to one of: $GATE_CALLER_KINDS)"
    else
        echo "- caller: $GATE_RUN_CALLER (DJB_GATE_CALLER)"
    fi
    if [ -n "$GATE_RUN_TREE" ] && prior=$(gate_run_lookup "$GATE_RUN_TREE"); then
        case "$prior" in
        killed:*) echo "- the previous run on this tree was KILLED during ${prior#killed:} — no verdict, no red; nothing was judged" ;;
        tree-changed) echo "- the previous run on this tree passed but the tree changed mid-run — no verdict" ;;
        red:*) echo "- the previous run on this tree went red in ${prior#red:}" ;;
        exit-2:*) echo "- the previous run on this tree found ENFORCEMENT BROKEN in ${prior#exit-2:}" ;;
        unsettled) echo "- the previous run on this tree passed and never settled its record — a gate wiring bug, not your change" ;;
        *) echo "- the previous run on this tree ended: $prior" ;;
        esac
    fi
    path=$(gate_last_full_path) || return 0
    line=""
    [ -f "$path" ] && line=$(grep ' green$' "$path" | tail -1 || true)
    if [ -n "$line" ]; then
        secs=$(awk '{print $2}' <<<"$line")
        echo "- full gate — the last green run here took $((secs / 60))m$((secs % 60))s"
    fi
}
