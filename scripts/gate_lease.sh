#!/usr/bin/env bash
# THE MACHINE-WIDE FULL-GATE LEASE. Sourced by
# `scripts/check.sh` and by `scripts/tests/test_gate_lease.sh`.
#
# BASH ONLY, for the reason `gate_ledger.sh` and `loop_tier.sh` both state:
# sourced into an interactive zsh, `local path` ties to `$PATH` and every helper
# below dies silently.
#
# NOT EXECUTABLE, AND THAT IS THE DECLARATION rather than an oversight — the
# sentence `scripts/loop_tier.sh` already writes for itself. This file reports no
# verdict of its own. It hands the caller a lease and a sentence; the caller owns
# the exit status. It is a library beside `gate_ledger.sh`, `db.sh`,
# `secrets_scan.sh` and `loop_tier.sh`, not an instrument beside them.
#
# ---------------------------------------------------------------------------
# WHAT IT IS FOR, and the measurement that convicted the class.
#
# Once measured: a full gate run while another full gate was running on the
# same laptop took 607s and went RED on two tests; the same tree on a quiet
# machine took 99s
# and went green. The red was not a defect in the tree — it was the OTHER GATE'S
# LOAD arriving as a timeout. Two full gates on one machine each run `-n auto`
# (one pytest worker per core, twice), a real Meilisearch, a real MinIO and a
# real time-skipping Temporal server. They do not share a checkout, they do not
# share a database, and they contend for every core on the box.
#
# THE SHAPE WAS RULED, and the losing candidate is named so nobody re-proposes
# it. Per-checkout Meilisearch containers fix ONE organ and leave the CPU half
# open; the contended-vs-quiet evidence convicts CONTENTION, not only Meili. The
# lease closes the whole class, it is `check.sh`'s existing per-checkout lock
# ONE LEVEL UP — an already-proven pattern with already-proven stale
# semantics — and the chaos drill inherits exclusivity from it for free.
#
# HOW IT DIFFERS FROM THE PER-CHECKOUT LOCK, because they are two guards and not one:
#
#   * SCOPE. The per-checkout lock is per CHECKOUT (`git rev-parse --git-dir`).
#     It stops a `--fast`/`--loop` in the SAME checkout reading a tree the
#     self-test is briefly rewriting. This lease is per MACHINE. Both are held
#     by a full run; neither replaces the other.
#   * BEHAVIOUR ON CONTENTION. The per-checkout lock REFUSES (exit 2): two full gates in
#     one checkout plant canaries over each other and there is nothing to wait
#     for that would make that safe. This lease WAITS: the second gate's tree is
#     fine, it simply must not run NOW, and a refusal would hand the caller a
#     chore where a wait hands them a queue. **A wait that says nothing is
#     indistinguishable from a hang**, so every wait announces itself, names the
#     holder, and re-announces while it lasts.
#   * WHO TAKES ONE. Only the full gate. `--fast` and `--loop` take NO lease and
#     never wait on one — they plant nothing, they are the per-rung tier, and
#     making a builder queue behind somebody else's push would be the friction
#     this repository keeps deleting.
#
# ---------------------------------------------------------------------------
# THE DECLARED LIMIT, written here because a guard whose edge is not written
# down gets read as covering more than it does:
#
#   **THE LEASE SERIALIZES FULL GATES ON ONE MACHINE.** It is a file in a
#   machine-wide directory and a pid on the local kernel. Two runners in CI, two
#   laptops, or one laptop and one runner do not see each other's lease and must
#   not — cross-machine CI runners were never this lease's scope. The finding was two
#   agents on ONE box; the fix is exactly that wide, and no wider. A CI runner
#   is a fresh machine with its own `/tmp`, so it takes an uncontended lease in
#   microseconds and nothing there changes.
#
# THE OTHER LIMITS, in the same spirit:
#
#   * TRUST CLASS, same as the verdict ledger's and the per-checkout lock's:
#     this is a local file, and `rm` is one command away. `DJB_GATE_LEASE_DIR` is one
#     export away. It stops casual overlap, not sabotage — the hooks were never
#     a security boundary and CI re-runs everything from a fresh checkout.
#   * A LEASE RECORDED BY ANOTHER HOST IS NEVER SELF-CLEARED. `kill -0 <pid>`
#     asks THIS kernel about a pid, so on a shared `/tmp` (an NFS mount, a
#     container bind) a foreign pid number could be alive here and dead there,
#     or the reverse. The holder line therefore carries the host, and the
#     stale-clear only fires when the host matches. A foreign-host lease is
#     waited on and then hits the ceiling, which is a loud stop rather than a
#     silent overlap or a wrong deletion.
#   * IT IS NOT A FAIR QUEUE. Waiters race for the file when it frees; whoever
#     wins the `noclobber` create goes next. Ordering was never the property —
#     exclusivity was.
#   * IT SAYS NOTHING ABOUT ANY OTHER LOAD ON THE BOX. A `pytest` a human
#     started by hand, a compose stack rebuild, a `uv sync` — the lease does not
#     see them and does not claim to.

#: Values a caller may override. Each is read at CALL time, never cached, so a
#: drive can point one run at its own scratch directory without disturbing the
#: real one.
#:
#:   DJB_GATE_LEASE_DIR       where the lease file lives. Default `/tmp`, which
#:                            on macOS and Linux alike is the one directory every
#:                            process on the machine agrees about. NOT
#:                            `$TMPDIR`: on macOS that is per-user and per-boot
#:                            (`/var/folders/…`), which is a machine-wide
#:                            location right up until it quietly is not.
#:   DJB_GATE_LEASE_MAX_WAIT  seconds a full gate will wait before refusing.
#:   DJB_GATE_LEASE_POLL      seconds between attempts while waiting.
#:   DJB_GATE_LEASE_ANNOUNCE  seconds between "still waiting" lines.
GATE_LEASE_DEFAULT_DIR="/tmp"
GATE_LEASE_DEFAULT_MAX_WAIT=3600
GATE_LEASE_DEFAULT_POLL=5
GATE_LEASE_DEFAULT_ANNOUNCE=60

#: The path this process holds, or empty. Only a non-empty value is ever
#: released, and only when the recorded pid is this one.
GATE_LEASE=""

#: Seconds this process spent waiting for the lease. Read by the caller for its
#: own announcement; 0 is the uncontended case and is the normal one.
GATE_LEASE_WAITED=0

# gate_lease_path — the lease file, or exit 1 having said why.
#
# `DJB_GATE_LEASE_DIR` must be an ABSOLUTE, existing directory. A relative one
# resolves against whatever directory the caller left behind, the same class of
# hazard one file over; an absent one would make every acquire fail open and the
# lease would stop existing without anybody being told.
gate_lease_path() {
    local dir=${DJB_GATE_LEASE_DIR:-$GATE_LEASE_DEFAULT_DIR}
    case "$dir" in
    /*) ;;
    *)
        echo "!! DJB_GATE_LEASE_DIR is relative ('$dir'). The full-gate lease needs an" >&2
        echo "   absolute machine-wide directory; a relative one resolves against" >&2
        echo "   whatever directory the caller left behind." >&2
        return 1
        ;;
    esac
    [ -d "$dir" ] || {
        echo "!! DJB_GATE_LEASE_DIR ('$dir') is not a directory — no lease can be taken there." >&2
        return 1
    }
    printf '%s\n' "$dir/djb-gate-lease"
}

# gate_lease_line — the holder record this process would write.
# Fields, in order and space-separated: pid mode started-utc host checkout.
# The checkout is the last field on purpose: it is the only one with a real
# chance of containing something surprising, and a reader parsing the first four
# with awk is unaffected by it.
gate_lease_line() {
    printf '%s %s %s %s %s\n' \
        "$$" "full" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$(hostname -s 2>/dev/null || echo host)" \
        "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
}

# gate_lease_holder — the holder line, or empty when there is none and none is
# stale. Clears the file when the recorded host is THIS host and the recorded
# pid is gone.
#
# A dead holder's lease must never be a hang: the commonest way to leave one is
# a killed gate (the tool's ten-minute ceiling kills full runs routinely), and an
# agent who has to be told to delete a file has been handed the friction back.
gate_lease_holder() {
    local path pid host me
    path=$(gate_lease_path) || return 0
    [ -f "$path" ] || return 0
    pid=$(awk 'NR==1{print $1}' "$path" 2>/dev/null || true)
    host=$(awk 'NR==1{print $4}' "$path" 2>/dev/null || true)
    me=$(hostname -s 2>/dev/null || echo host)
    if [ -n "$host" ] && [ "$host" != "$me" ]; then
        # Another machine's record on a shared directory. Never cleared here —
        # see THE OTHER LIMITS in this file's header.
        head -1 "$path"
        return 0
    fi
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        echo "  note: cleared a STALE full-gate lease — pid ${pid:-<none>} is not running ($path)" >&2
        rm -f "$path"
        return 0
    fi
    head -1 "$path"
}

# gate_lease_try — take the lease without waiting.
# Exit: 0 taken (GATE_LEASE set) · 1 held by somebody else · 2 could not look.
#
# `noclobber` makes the create atomic, so two gates starting in the same
# millisecond cannot both believe they won.
gate_lease_try() {
    local path
    path=$(gate_lease_path) || return 2
    if (
        set -o noclobber
        gate_lease_line >"$path"
    ) 2>/dev/null; then
        GATE_LEASE=$path
        return 0
    fi
    return 1
}

# gate_lease_release — give it back, if and only if this process holds it.
gate_lease_release() {
    [ -n "$GATE_LEASE" ] || return 0
    local pid
    pid=$(awk 'NR==1{print $1}' "$GATE_LEASE" 2>/dev/null || true)
    if [ "$pid" = "$$" ]; then
        rm -f "$GATE_LEASE"
    fi
    GATE_LEASE=""
    return 0
}

# gate_lease_acquire — take the lease, WAITING (out loud) for as long as it
# takes, up to the ceiling.
#
# Exit: 0 held · 2 the ceiling was reached, or the lease directory cannot be
# used. 2 and not 1: a gate that never ran has not judged the tree, and
# could-not-look outranks a pass everywhere else in this gate.
#
# EVERY WAIT ANNOUNCES ITSELF. The first line goes out before the first sleep,
# names the holder and says what the reader is waiting for; a `still waiting`
# line follows every `DJB_GATE_LEASE_ANNOUNCE` seconds. A silent wait is
# indistinguishable from a hang, and the whole reason the per-checkout lock
# chose refusal over waiting was that nobody had written the announcement.
gate_lease_acquire() {
    local path held rc max poll announce next
    GATE_LEASE_WAITED=0
    max=${DJB_GATE_LEASE_MAX_WAIT:-$GATE_LEASE_DEFAULT_MAX_WAIT}
    poll=${DJB_GATE_LEASE_POLL:-$GATE_LEASE_DEFAULT_POLL}
    announce=${DJB_GATE_LEASE_ANNOUNCE:-$GATE_LEASE_DEFAULT_ANNOUNCE}
    path=$(gate_lease_path) || return 2

    next=$announce
    while :; do
        rc=0
        gate_lease_try || rc=$?
        case "$rc" in
        0)
            if [ "$GATE_LEASE_WAITED" -gt 0 ]; then
                echo "- full-gate lease ACQUIRED after ${GATE_LEASE_WAITED}s of waiting (pid $$)"
            else
                echo "- full-gate lease held for this MACHINE (pid $$) — another full gate here will WAIT, not fail"
            fi
            return 0
            ;;
        2) return 2 ;;
        esac

        # Held. `gate_lease_holder` clears a stale one as a side effect, so an
        # empty answer here means "it just freed" and the loop retries at once.
        held=$(gate_lease_holder) || true
        if [ -z "$held" ]; then
            continue
        fi

        if [ "$GATE_LEASE_WAITED" -eq 0 ]; then
            echo "- WAITING for the machine-wide full-gate lease. This is not a hang."
            echo "   holder: $held  (pid mode started-utc host checkout)"
            echo "   Two full gates on one machine contend for every core on it: each runs"
            echo "   pytest -n auto TWICE, a real Meilisearch, a real MinIO and a real"
            echo "   Temporal server. Measured: 607s and two RED tests contended"
            echo "   against 99s and green quiet, on the same tree. So this run waits for"
            echo "   the machine rather than reporting the other gate's load as your defect."
            echo "   Nothing is skipped by waiting; --fast and --loop take no lease and are"
            echo "   unaffected, here and in every other checkout."
            echo "   Ceiling: ${max}s, after which this run REFUSES (exit 2) rather than overlapping."
        elif [ "$GATE_LEASE_WAITED" -ge "$next" ]; then
            echo "  ... still waiting for the full-gate lease (${GATE_LEASE_WAITED}s of ${max}s) — holder: $held"
            next=$((GATE_LEASE_WAITED + announce))
        fi

        if [ "$GATE_LEASE_WAITED" -ge "$max" ]; then
            echo "!! REFUSING: waited ${GATE_LEASE_WAITED}s for the machine-wide full-gate lease and it is still held." >&2
            echo "   holder: $held  (pid mode started-utc host checkout)" >&2
            echo "   lease:  $path" >&2
            echo "   Nothing was judged. This is could-not-look, not a red tree." >&2
            echo "   If that holder is gone, the lease is stale and the pid check should have" >&2
            echo "   cleared it — unless it was written by another host, which this never" >&2
            echo "   clears on purpose (scripts/gate_lease.sh, THE OTHER LIMITS)." >&2
            return 2
        fi

        sleep "$poll"
        GATE_LEASE_WAITED=$((GATE_LEASE_WAITED + poll))
    done
}
