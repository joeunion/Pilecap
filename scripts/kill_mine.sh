#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# Stop only what is YOURS — the processes running under THIS checkout.
#
#   ./scripts/kill_mine.sh                census: what this checkout is running
#   ./scripts/kill_mine.sh --kill         stop them: TERM, bounded wait, KILL
#   ./scripts/kill_mine.sh --all-census   census only: also SHOW what is outside
#
# WHY IT EXISTS. A verification pass once ran a `pkill -f` against a name and
# killed a PEER WORKTREE's Temporal worker. A command-line pattern cannot tell your
# worker from somebody else's — both command lines say the same words — and the
# agent that typed it had no way to know it had done any harm. That is the scar
# this script closes, and it closes it by changing what "yours" is measured on:
# not a NAME, but a CHECKOUT.
#
# THE CHECKOUT IS NEVER AN ARGUMENT. It is `git rev-parse --show-toplevel` of
# the directory this script lives in, resolved to a real path. A path argument
# would be the `pkill -f` hazard wearing a flag — one wrong string and the broom
# is pointed at somebody else's tree — so there is no way to point it anywhere.
#
# HOW A PROCESS IS CLAIMED. Two facts the kernel keeps, and nothing else:
#
#   * its WORKING DIRECTORY is under this checkout, or
#   * its EXECUTABLE (the running image) is under this checkout — which is what
#     catches `.venv/bin/python`, `.venv/bin/uvicorn` and anything else run out
#     of this tree's own virtualenv.
#
# Both are read in one pass from:
#
#     lsof -d cwd,txt -F pfn
#
# (`-d cwd,txt` = only the working-directory and text/executable entries;
# `-F pfn` = machine-readable pid / fd / name records.) On a host with no
# `lsof`, the same two facts are `readlink /proc/<pid>/cwd` and
# `readlink /proc/<pid>/exe` over `/proc/[0-9]*` — but this script does NOT
# silently fall back to them, because a broom that quietly changes how it
# decides what is yours is worse than one that stops. No `lsof` is exit 2.
#
# TWO REFUSALS, both restated at the kill (a list is not a licence):
#
#   1. A PROCESS WHOSE CWD **AND** EXECUTABLE ARE BOTH OUTSIDE THIS CHECKOUT IS
#      NEVER TOUCHED — a peer worktree's worker, the owner's editor, another
#      agent's session, a browser. It is not killed, and it is not even LISTED
#      except under `--all-census`, which is a census flag and refuses to kill.
#      A process you cannot name by checkout is not yours to stop: report its
#      pid and what you think it is.
#   2. THIS SCRIPT'S OWN ANCESTRY IS NEVER TOUCHED. The shell that ran it has
#      its cwd here and is a perfectly good candidate by the test above, so it
#      is excluded BY PID — this process, its parent, its parent's parent, up to
#      pid 1 — and printed as SELF. Its own short-lived helpers (`lsof`, `awk`)
#      are gone by the time anything is signalled and are dropped by a liveness
#      re-check, never by their names.
#
# There is no `--force`, and there is no way to match on a name or a command
# line. Those are not missing features.
#
# DECLARED BLIND SPOTS, so they are read rather than discovered:
#
#   * A PROCESS THAT `cd`'d AWAY. Something started from this checkout that then
#     changed directory, and whose executable is not in this tree either, has
#     neither fact pointing here and is INVISIBLE to this script. It was yours
#     and this test cannot say so. Nothing else can either — which is why the
#     rule is "report the pid", not "guess".
#   * SYMLINKS RESOLVE BY THE REAL PATH. `lsof` reports the resolved path of the
#     running image and of the working directory, so a symlink OUTSIDE pointing
#     in is seen as inside, and a symlink inside pointing OUT is seen as
#     outside. The real path wins, both ways.
#   * CONTAINERS ARE NOT IN THIS PROCESS TABLE BY CHECKOUT. `docker compose -p
#     djangobootstrap` is ONE stack shared by every checkout by design
#     (CLAUDE.md), so a compose organ is nobody's checkout's to stop. This
#     script never touches containers. Use `docker compose` deliberately.
#   * TWO AGENTS IN ONE CHECKOUT. If two agents ever shared a checkout, this
#     script could not tell their processes apart and would stop both. The
#     standing rule — two agents never share a checkout — is what keeps that
#     hypothetical, and this script cannot enforce it.
#
# KILLING A GATE IN THIS CHECKOUT IS LEGAL and leaves no lie behind: the full
# gate's TERM trap writes its own run-log line naming the leg it died on
# (`scripts/gate_ledger.sh:168-172`), and the lock it held clears itself on
# the next run because the holder pid is gone (`quality/djb/hold.py::holder_of`).
#
# Exit: 0 census taken / kills done · 1 a pid survived TERM and KILL · 2 no
# `lsof`, not a git checkout, or an unknown flag. 2 outranks a pass: a broom
# that cannot see the floor must never report a clean one.
set -uo pipefail

MODE=census
while [ "$#" -gt 0 ]; do
    case "$1" in
    --kill) MODE=kill ;;
    --all-census) MODE=all-census ;;
    *)
        echo "!! unknown argument '$1': kill_mine.sh takes --kill or --all-census" >&2
        echo "   There is no --force, no --name and no path argument. The checkout is" >&2
        echo "   derived from this script's own location, and that is the whole point." >&2
        exit 2
        ;;
    esac
    shift
done

if ! command -v lsof >/dev/null 2>&1; then
    echo "!! NO lsof ON PATH — this script cannot see any process's working directory" >&2
    echo "   or executable, which is the only way it knows what is yours. Nothing was" >&2
    echo "   signalled and nothing here is a census: install lsof, or stop your" >&2
    echo "   processes by hand from the pids you started." >&2
    exit 2
fi

HERE=$(cd "$(dirname "$0")" && pwd -P)
ROOT=$(cd "$HERE" && git rev-parse --show-toplevel 2>/dev/null) || ROOT=""
if [ -z "$ROOT" ]; then
    echo "!! $HERE IS NOT INSIDE A GIT CHECKOUT — there is no checkout to scope to," >&2
    echo "   so there is no such thing as 'mine' here. Nothing was signalled." >&2
    exit 2
fi
ROOT=$(cd "$ROOT" && pwd -P)

if [ "$MODE" = "all-census" ]; then
    : # stated again where it matters: --all-census never signals anything.
fi

# --- refusal 2, as a pid set ------------------------------------------------
# This process and every ancestor of it. Built by walking ppid, so it is a
# structural fact and never a name.
SELF_PIDS=" $$ "
_walk=$$
while [ "$_walk" != "1" ] && [ -n "$_walk" ]; do
    _walk=$(ps -o ppid= -p "$_walk" 2>/dev/null | tr -d ' ')
    [ -n "$_walk" ] || break
    SELF_PIDS="$SELF_PIDS$_walk "
done

is_self() {
    case "$SELF_PIDS" in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
    esac
}

# --- the one pass over the process table ------------------------------------
# One line per (pid, kind, path) where kind is `cwd` or `txt`. Refusal 1 lives
# here — the filter is on the PATH, never on a command line — and is restated
# at the kill below.
snapshot() {
    lsof -d cwd,txt -F pfn 2>/dev/null | awk -v root="$ROOT" '
        /^p/ { pid = substr($0, 2); next }
        /^f/ { fd  = substr($0, 2); next }
        /^n/ {
            name = substr($0, 2)
            inside = (name == root || index(name, root "/") == 1)
            if (fd == "cwd" || fd == "txt") {
                print pid, fd, (inside ? "in" : "out"), name
            }
        }
    '
}

SNAP=$(mktemp "${TMPDIR:-/tmp}/djb-kill-mine.XXXXXX")
trap 'rm -f "$SNAP"' EXIT
snapshot >"$SNAP"

if [ ! -s "$SNAP" ]; then
    echo "!! lsof RETURNED NOTHING — it ran, and this script cannot tell an empty" >&2
    echo "   machine from a refused one. Nothing was signalled." >&2
    exit 2
fi

# pids with at least one path INSIDE the checkout, and the reason, deduped.
MINE=$(awk '$3 == "in" && !seen[$1]++ { print $1, $2 }' "$SNAP")
# every pid lsof saw at all — used only by --all-census.
ALL=$(awk '!seen[$1]++ { print $1 }' "$SNAP")

echo "kill_mine: checkout $ROOT"
echo "           mode: $MODE"

found=0
skipped=0
failed=0
stopped=0

# --- the census / the kill ---------------------------------------------------
while read -r pid why; do
    [ -n "${pid:-}" ] || continue
    # A helper this script spawned has already exited by now; a liveness check
    # drops it without anyone naming it.
    kill -0 "$pid" 2>/dev/null || continue
    if is_self "$pid"; then
        echo "  SELF     pid ${pid} — this script or one of its ancestors; never touched"
        skipped=$((skipped + 1))
        continue
    fi
    found=$((found + 1))
    # Refusal 1, restated: re-read this pid's own rows from the snapshot and
    # confirm at least one path is still inside. A list is not a licence.
    if ! awk -v p="$pid" '$1 == p && $3 == "in" { hit = 1 } END { exit hit ? 0 : 1 }' "$SNAP"; then
        echo "  REFUSED  pid ${pid} — nothing about it is under this checkout"
        skipped=$((skipped + 1))
        continue
    fi
    label="$why under this checkout"
    if [ "$MODE" != "kill" ]; then
        echo "  MINE     pid ${pid} — ${label}"
        continue
    fi
    kill -TERM "$pid" 2>/dev/null
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
    done
    if kill -0 "$pid" 2>/dev/null; then
        kill -KILL "$pid" 2>/dev/null
        sleep 0.5
    fi
    if kill -0 "$pid" 2>/dev/null; then
        echo "  FAILED   pid ${pid} — still running after TERM and KILL (${label})"
        failed=$((failed + 1))
    else
        echo "  STOPPED  pid ${pid} — ${label}"
        stopped=$((stopped + 1))
    fi
done <<EOF
$MINE
EOF

if [ "$found" -eq 0 ]; then
    echo "  (none)"
fi

if [ "$MODE" = "all-census" ]; then
    echo ""
    echo "  --- everything else lsof saw (NEVER a kill candidate; shown so a pid you"
    echo "      are wondering about can be named rather than guessed at) ---"
    outside=0
    while read -r pid; do
        [ -n "${pid:-}" ] || continue
        if awk -v p="$pid" '$1 == p && $3 == "in" { hit = 1 } END { exit hit ? 0 : 1 }' "$SNAP"; then
            continue
        fi
        cwd=$(awk -v p="$pid" '$1 == p && $2 == "cwd" { $1=""; $2=""; $3=""; sub(/^   /, ""); print; exit }' "$SNAP")
        echo "  OUTSIDE  pid ${pid} — cwd ${cwd:-<unreadable>}"
        outside=$((outside + 1))
    done <<EOF
$ALL
EOF
    echo "  outside this checkout: ${outside} process(es), none of them this script's business"
fi

echo "kill_mine: ${found} mine · ${stopped} stopped · ${failed} failed · ${skipped} refused or self"
[ "$failed" -eq 0 ] || exit 1
exit 0
