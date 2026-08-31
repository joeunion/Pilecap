#!/usr/bin/env bash
# THE MACHINE-WIDE GATE GUARDS — TWO OF THEM, and they are not the same guard.
# Sourced by `scripts/check.sh` and by `scripts/tests/test_gate_lease.sh`.
#
#   1. THE FULL-GATE LEASE (this file's original half, everything down to
#      `gate_lease_acquire`). EXCLUSIVE, one holder on the machine, taken by the
#      FULL gate only. It is what stops two full gates overlapping.
#   2. THE PYTEST SLOT SEMAPHORE (the second half, from THE COUNTING SEMAPHORE
#      below). COUNTING, N holders on the machine, taken by every pytest leg —
#      `--loop`'s and the full gate's alike. It is what stops eleven `--loop`
#      runs each starting `pytest -n auto` on the same ten cores.
#
# Each announces WHICH guard it is in every line it prints, because a reader
# watching a wait has to be able to tell "somebody else is pushing" from "the
# box is full". The lock order between them is fixed and asserted — see
# THE LOCK ORDER below.
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
#     see them and does not claim to. (The semaphore below narrows this by
#     exactly one class — pytest legs STARTED THROUGH check.sh — and no wider:
#     a bare `uv run pytest` still takes no slot.)

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

#: Nominal full-gate length, used ONLY to turn the holder's elapsed time into
#: the "~N min" a waiter is told to expect. It is an estimate, the line that
#: prints it says so, and nothing decides anything on it. Same number and same
#: provenance as `GATE_SLOT_NOMINAL_FULL` in the semaphore below: the full
#: gate's two whole-suite passes are the better part of a quarter hour. Declared
#: here rather than read from there because this half of the file is sourced and
#: used on its own, and a variable that is only sometimes defined is worse than
#: a number written twice with the reason beside both.
GATE_LEASE_NOMINAL_FULL=900

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
# Fields, in order and space-separated:
#   pid mode started-utc host started-epoch checkout
# The checkout is the last field on purpose: it is the only one with a real
# chance of containing something surprising, and a reader parsing the first four
# with awk is unaffected by it. THE EPOCH IS FIELD 5 for `gate_slot_line`'s
# reason, and it joined this record for `gate_lease_estimate` below: a waiter's
# "~N min" should be arithmetic, not date parsing, and the UTC stamp beside it
# is for a human rather than for a script.
#
# AN OLDER RECORD STILL PARSES. A lease written before this field existed has
# the checkout path in position 5; every reader here either takes fields 1 and 4
# (`gate_lease_holder`) or requires field 5 to be all digits before using it
# (`gate_lease_estimate`), so an old line loses the estimate and nothing else.
gate_lease_line() {
    printf '%s %s %s %s %s %s\n' \
        "$$" "full" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$(hostname -s 2>/dev/null || echo host)" \
        "$(date +%s)" \
        "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
}

# gate_lease_estimate <holder line> — a "~N min" for the waiter, from the
# holder's elapsed time against the nominal full-gate length. An estimate,
# printed as one; nothing decides anything on it. `gate_slot_estimate`'s
# arithmetic exactly, over one holder instead of N, because the exclusive lease
# has exactly one.
#
# WHY IT EXISTS. The slot wait printed an estimate and the lease wait did not,
# and the lease is the LONGER of the two waits by construction — a full gate is
# what is being waited on either way, and the exclusive one has no second slot
# to free early. A silent wait is indistinguishable from a hang, which is the
# sentence this file already opens the announcement with; "and it will be
# roughly this long" is the half that tells a reader whether to wait or to go
# and do something else.
gate_lease_estimate() {
    local line=$1 now started left
    now=$(date +%s)
    started=$(awk '{print $5}' <<<"$line")
    case "$started" in
    '' | *[!0-9]*) return 1 ;;
    esac
    left=$((GATE_LEASE_NOMINAL_FULL - (now - started)))
    [ "$left" -ge 0 ] || left=0
    printf '%s\n' "$(((left + 59) / 60))"
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
    local path held rc max poll announce next est
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
            echo "   holder: $held  (pid mode started-utc host started-epoch checkout)"
            echo "   Two full gates on one machine contend for every core on it: each runs"
            echo "   pytest -n auto TWICE, a real Meilisearch, a real MinIO and a real"
            echo "   Temporal server. Measured: 607s and two RED tests contended"
            echo "   against 99s and green quiet, on the same tree. So this run waits for"
            echo "   the machine rather than reporting the other gate's load as your defect."
            echo "   Nothing is skipped by waiting; --fast and --loop take no lease and are"
            echo "   unaffected, here and in every other checkout."
            if est=$(gate_lease_estimate "$held"); then
                echo "   Rough estimate from the holder's elapsed time: ~${est} min. An estimate,"
                echo "   not a promise — nothing here decides anything on it."
            fi
            echo "   Ceiling: ${max}s, after which this run REFUSES (exit 2) rather than overlapping."
        elif [ "$GATE_LEASE_WAITED" -ge "$next" ]; then
            if est=$(gate_lease_estimate "$held"); then
                echo "  ... still waiting for the full-gate lease (${GATE_LEASE_WAITED}s of ${max}s, ~${est} min left) — holder: $held"
            else
                echo "  ... still waiting for the full-gate lease (${GATE_LEASE_WAITED}s of ${max}s) — holder: $held"
            fi
            next=$((GATE_LEASE_WAITED + announce))
        fi

        if [ "$GATE_LEASE_WAITED" -ge "$max" ]; then
            echo "!! REFUSING: waited ${GATE_LEASE_WAITED}s for the machine-wide full-gate lease and it is still held." >&2
            echo "   holder: $held  (pid mode started-utc host started-epoch checkout)" >&2
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

# ===========================================================================
# THE COUNTING SEMAPHORE — N PYTEST LEGS AT A TIME, PER MACHINE.
#
# WHAT IT IS FOR, and the measurement that convicted the class. The lease above
# closes the two-FULL-GATES case and says so in its own header. It says nothing
# about `--fast`/`--loop`, deliberately and in writing: "--fast and --loop take
# NO lease and never wait on one." That sentence was right about the lease and
# wrong about the box. A cycle dispatched five-plus builders at once and every
# one of them ran `--loop`, whose pytest leg is `-n auto` — one worker per core,
# ON TEN CORES, FIVE TIMES OVER. Measured: load average 162, wall clock 5-8x
# its quiet figure, and two runs killed at the harness's ceiling having judged
# nothing. Not one of those was a full gate, so not one of them was in any way
# irregular; the guard simply did not cover the case that arrived.
#
# THE SECOND WITNESS, and it is the owner's own, unprompted, while this file was
# being written: "we've been overlapping our agent QA and verification runs with
# the other running PM, and the computer CPU is crushed" — reported alongside a
# directive to STOP DISPATCHING and hold all work for fifteen minutes. Two
# things in it that the builders' load-162 measurement could not say. First,
# the cost is not paid in a log somebody reads later; it is paid by the human
# watching the machine, and it was severe enough to buy a pause. Second, and
# this is why the slots live in a MACHINE-WIDE directory rather than a
# per-repository one: the crush was OURS OVERLAPPING SOMEBODY ELSE'S — a second
# PM, a different checkout, its own builders, no shared queue and no shared
# ledger. Neither side was misbehaving and neither side could see the other.
# Nothing inside one repository's own dispatch discipline can close that; only
# a counter both sides take a number from can, which is the whole reason this
# is a filesystem semaphore on the box and not a variable in the gate.
#
# WHY A SEMAPHORE AND NOT A SECOND LEASE. Serializing per-rung gates would be
# the friction this repository keeps deleting: eleven builders queueing one
# behind another turns a parallel wave into a sequential one. What the box
# cannot survive is not CONCURRENCY, it is OVERSUBSCRIPTION — N runs each
# claiming every core. So the box gets N slots, a slot holder runs
# `-n <cores/N>` instead of `-n auto`, and the arithmetic is closed: however
# many gates are live, the workers they have started total the core count.
#
# WHO TAKES ONE:
#   * `--loop`'s pytest leg — the case the measurement convicted;
#   * the full gate's `pytest-x2` leg — it is `-n auto` twice and is the
#     heaviest single consumer on the box;
#   * `--fast` NEVER. It has no suite. It stays the tier nothing queues behind,
#     which is what lets pre-commit keep running it on every commit.
#
# THE LOCK ORDER, and it is fixed rather than conventional: THE EXCLUSIVE LEASE
# IS ALWAYS TAKEN BEFORE A SLOT. The full gate takes its lease before its first
# leg and its slot at `pytest-x2`; `--loop` takes a slot and never wants a
# lease. So no holder of a slot is ever waiting for the lease, and the cycle
# that would deadlock the machine cannot be formed. That is not left to whoever
# edits `check.sh` next: a caller that has declared itself a full run
# (`GATE_SLOT_LEASE_FIRST=1`) and reaches `gate_slot_acquire` WITHOUT the lease
# in hand is refused, exit 2, naming the order it broke.
#
# THE LIMITS, in the lease's spirit:
#
#   * SAME MACHINE ONLY, same directory, same argument. Two CI runners do not
#     see each other's slots and must not.
#   * SAME TRUST CLASS. `rm -rf` is one command away and `DJB_GATE_SLOTS` is one
#     export away. It stops oversubscription, not sabotage.
#   * A BARE `pytest` TAKES NO SLOT. `uv run pytest`, `./scripts/test.sh` run by
#     hand, a test a builder starts in an editor — the semaphore does not see
#     them, exactly as the lease does not see a compose rebuild. It counts
#     pytest legs STARTED THROUGH check.sh and claims nothing else.
#   * IT IS NOT A FAIR QUEUE, for the lease's reason: waiters race for a freed
#     slot and whoever wins the `mkdir` goes next.
#   * A FOREIGN HOST'S SLOT IS NEVER CLEARED HERE, for the lease's reason —
#     `kill -0` asks THIS kernel. It is waited on and then refused out loud.
#   * THE MKDIR/HOLDER WINDOW. A slot is claimed by `mkdir` (atomic on every
#     filesystem, which `>` with `noclobber` is not) and its holder record is
#     written microseconds later. A process killed inside that window leaves a
#     directory with no holder record, which nothing can attribute to a pid. It
#     is reclaimed once it has been holderless for over two minutes, out loud;
#     until then it counts as held. Declared rather than pretended away.

#: Values a caller may override. Read at CALL time, never cached.
#:
#:   DJB_GATE_SLOTS           how many pytest legs may run at once on this box.
#:                            Default: cores / GATE_SLOT_CORES_PER_SLOT, floor,
#:                            never below 1 — 2 on the ten-core box the
#:                            measurement was taken on. A value that is not a
#:                            positive whole number is EXIT 2, never a silent
#:                            default: a mistyped ceiling that quietly became
#:                            the default is the unbounded run this exists to
#:                            stop.
#:   DJB_GATE_LEASE_DIR       the slots live in `<that dir>/djb-gate-slots`, so
#:                            a drive pointing the lease at a scratch directory
#:                            moves the slots with it and there is one opinion
#:                            about where machine-wide state lives.
#:   DJB_GATE_SLOT_MAX_WAIT   seconds a leg waits for a slot before refusing.
#:   DJB_GATE_LEASE_POLL      seconds between attempts (shared with the lease).
#:   DJB_GATE_LEASE_ANNOUNCE  seconds between "still waiting" lines (shared).
GATE_SLOT_CORES_PER_SLOT=5
GATE_SLOT_DEFAULT_MAX_WAIT=3600

#: Nominal leg lengths, used ONLY to turn a holder's elapsed time into the
#: "~N min" a waiter is told to expect. They are estimates and the line says so;
#: nothing decides anything on them. Provenance: the untiered suite is ~80s of
#: wall clock quiet (`scripts/check.sh`'s header), so a `--loop` leg is minutes
#: and the full gate's two whole-suite passes are the better part of a quarter
#: hour.
GATE_SLOT_NOMINAL_LOOP=240
GATE_SLOT_NOMINAL_FULL=900

#: The slot directory this process holds, or empty.
GATE_SLOT=""
#: Seconds this process spent waiting for a slot. 0 is the normal case.
GATE_SLOT_WAITED=0
#: Resolved by `gate_slot_acquire`: how many slots this box has, and the `-n`
#: a holder must run. The caller PRINTS both — a worker count nobody can see is
#: a worker count nobody notices going wrong.
GATE_SLOT_TOTAL=""
GATE_SLOT_WORKERS=""
#: Set to 1 by a caller that holds (or must hold) the exclusive lease first.
#: See THE LOCK ORDER above.
GATE_SLOT_LEASE_FIRST=""

# gate_slot_cores — this machine's core count, or 2 having said why.
#
# Falls back rather than refusing: an exotic box that answers neither `getconf`
# nor `sysctl` is an environment quirk, and the lease's own `/dev/fd` note takes
# the same direction — failing open beats refusing to enforce. The fallback is
# announced so it is never mistaken for a measurement.
gate_slot_cores() {
    local n=""
    n=$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)
    [ -n "$n" ] || n=$(sysctl -n hw.ncpu 2>/dev/null || true)
    [ -n "$n" ] || n=$(nproc 2>/dev/null || true)
    case "$n" in
    '' | *[!0-9]*)
        echo "  note: this machine's core count could not be read — assuming 2 for the gate semaphore" >&2
        n=2
        ;;
    esac
    [ "$n" -ge 1 ] || n=1
    printf '%s\n' "$n"
}

# gate_slots_total — how many pytest legs may run at once. Exit 2 on a
# DJB_GATE_SLOTS this cannot read as a positive whole number.
gate_slots_total() {
    local want=${DJB_GATE_SLOTS:-} cores n
    if [ -n "$want" ]; then
        case "$want" in
        *[!0-9]*)
            echo "!! DJB_GATE_SLOTS='$want' is not a positive whole number." >&2
            echo "   A ceiling this cannot read is a ceiling that would silently become the" >&2
            echo "   default, which is the unbounded run the semaphore exists to stop." >&2
            return 2
            ;;
        esac
        if [ "$want" -lt 1 ]; then
            echo "!! DJB_GATE_SLOTS='$want' — a box with no slots can run no suite at all." >&2
            echo "   Set it to at least 1, or unset it and take the derived default." >&2
            return 2
        fi
        printf '%s\n' "$want"
        return 0
    fi
    cores=$(gate_slot_cores)
    n=$((cores / GATE_SLOT_CORES_PER_SLOT))
    [ "$n" -ge 1 ] || n=1
    printf '%s\n' "$n"
}

# gate_slot_workers <total> — the `-n` a slot holder runs: cores split N ways,
# never below 1 and NEVER `auto`. This is the whole arithmetic of the design:
# N legs x cores/N workers = the core count, whatever N is.
gate_slot_workers() {
    local total=$1 cores n
    cores=$(gate_slot_cores)
    n=$((cores / total))
    [ "$n" -ge 1 ] || n=1
    printf '%s\n' "$n"
}

# gate_slots_dir — where the slots live. Derived from `gate_lease_path` so the
# absolute/existing checks on DJB_GATE_LEASE_DIR are inherited rather than
# re-stated: two opinions about a machine-wide directory is one too many.
gate_slots_dir() {
    local p
    p=$(gate_lease_path) || return 1
    printf '%s\n' "${p%/*}/djb-gate-slots"
}

# gate_slot_line <mode> — the holder record. Fields, in order:
#   pid mode started-utc host started-epoch checkout
# The checkout is last for the lease's reason (it is the field most likely to
# contain something surprising); the epoch is field 5 so the waiter's estimate
# is arithmetic rather than date parsing.
gate_slot_line() {
    printf '%s %s %s %s %s %s\n' \
        "$$" "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        "$(hostname -s 2>/dev/null || echo host)" \
        "$(date +%s)" \
        "$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
}

# gate_slot_holders — one line per HELD slot, `slot-<n> <holder record>`.
# Reclaims this host's dead holders and long-orphaned mkdir windows as a side
# effect, out loud; never touches a foreign host's record.
gate_slot_holders() {
    local dir total me i slot pid host
    dir=$(gate_slots_dir) || return 0
    [ -d "$dir" ] || return 0
    total=$(gate_slots_total) || return 0
    me=$(hostname -s 2>/dev/null || echo host)
    i=0
    while [ "$i" -lt "$total" ]; do
        i=$((i + 1))
        slot="$dir/slot-$i"
        [ -d "$slot" ] || continue
        if [ ! -f "$slot/holder" ]; then
            # The mkdir/holder window. Held while it is fresh; reclaimed once it
            # is plainly not a window any more. See THE LIMITS above.
            if [ -n "$(find "$slot" -maxdepth 0 -mmin +2 2>/dev/null || true)" ]; then
                echo "  note: reclaimed an ORPHAN gate slot — $slot has carried no holder record for over two minutes" >&2
                rm -rf "$slot"
            else
                printf 'slot-%s (starting — no holder record yet)\n' "$i"
            fi
            continue
        fi
        pid=$(awk 'NR==1{print $1}' "$slot/holder" 2>/dev/null || true)
        host=$(awk 'NR==1{print $4}' "$slot/holder" 2>/dev/null || true)
        if [ -n "$host" ] && [ "$host" != "$me" ]; then
            printf 'slot-%s %s\n' "$i" "$(head -1 "$slot/holder")"
            continue
        fi
        if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
            echo "  note: cleared a STALE gate slot — pid ${pid:-<none>} is not running ($slot)" >&2
            rm -rf "$slot"
            continue
        fi
        printf 'slot-%s %s\n' "$i" "$(head -1 "$slot/holder")"
    done
}

# gate_slot_try <mode> — take a slot without waiting.
# Exit: 0 taken (GATE_SLOT set) · 1 the box is full · 2 could not look.
#
# `mkdir` is the claim and it is atomic on every filesystem, including the NFS
# and bind mounts where an O_EXCL create historically was not — which is why the
# slots are directories and the lease one file over is not.
gate_slot_try() {
    local mode=$1 dir total i slot
    dir=$(gate_slots_dir) || return 2
    mkdir -p "$dir" 2>/dev/null || {
        echo "!! the gate slot directory ('$dir') could not be created — no slot can be taken there." >&2
        return 2
    }
    total=$(gate_slots_total) || return 2
    i=0
    while [ "$i" -lt "$total" ]; do
        i=$((i + 1))
        slot="$dir/slot-$i"
        if mkdir "$slot" 2>/dev/null; then
            gate_slot_line "$mode" >"$slot/holder" 2>/dev/null || true
            GATE_SLOT=$slot
            return 0
        fi
    done
    return 1
}

# gate_slot_release — give it back, if and only if this process holds it.
gate_slot_release() {
    [ -n "$GATE_SLOT" ] || return 0
    local pid
    pid=$(awk 'NR==1{print $1}' "$GATE_SLOT/holder" 2>/dev/null || true)
    if [ "$pid" = "$$" ]; then
        rm -rf "$GATE_SLOT"
    fi
    GATE_SLOT=""
    return 0
}

# gate_slot_estimate <holders> — a "~N min" for the waiter, from the OLDEST
# holder's elapsed time against the nominal for its mode. An estimate, printed
# as one; nothing decides anything on it.
gate_slot_estimate() {
    local holders=$1 now line mode started nominal left best=""
    now=$(date +%s)
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        mode=$(awk '{print $3}' <<<"$line")
        started=$(awk '{print $6}' <<<"$line")
        case "$started" in
        '' | *[!0-9]*) continue ;;
        esac
        case "$mode" in
        full) nominal=$GATE_SLOT_NOMINAL_FULL ;;
        *) nominal=$GATE_SLOT_NOMINAL_LOOP ;;
        esac
        left=$((nominal - (now - started)))
        [ "$left" -ge 0 ] || left=0
        if [ -z "$best" ] || [ "$left" -lt "$best" ]; then best=$left; fi
    done <<<"$holders"
    [ -n "$best" ] || return 1
    printf '%s\n' "$(((best + 59) / 60))"
}

# gate_slot_acquire <mode> — take a slot, WAITING (out loud) up to the ceiling.
# <mode> is `loop` or `full`; it is recorded and it is what the estimate above
# reads.
#
# Exit: 0 held · 2 the ceiling was reached, the slot directory cannot be used,
# DJB_GATE_SLOTS is unreadable, or the lock order was broken. 2 and not 1
# throughout: a suite that never ran has judged nothing, and could-not-look
# outranks a pass everywhere in this gate.
gate_slot_acquire() {
    local mode=${1:-loop} rc max poll announce next holders est total
    GATE_SLOT_WAITED=0

    # THE LOCK ORDER, mechanically. A full run that reached here without its
    # exclusive lease could sit on a slot while waiting for the lease that a
    # slot-waiting gate is holding — the cycle. Refused rather than documented.
    if [ -n "${GATE_SLOT_LEASE_FIRST:-}" ] && [ -z "${GATE_LEASE:-}" ]; then
        echo "!! LOCK ORDER BROKEN: a FULL gate reached the pytest slot without holding the" >&2
        echo "   machine-wide exclusive lease. The order is LEASE FIRST, THEN SLOT — always," >&2
        echo "   on every path — so that no slot holder is ever waiting for the lease and the" >&2
        echo "   deadlock cycle cannot be formed (scripts/gate_lease.sh, THE LOCK ORDER)." >&2
        echo "   Nothing was judged." >&2
        return 2
    fi

    total=$(gate_slots_total) || return 2
    GATE_SLOT_TOTAL=$total
    GATE_SLOT_WORKERS=$(gate_slot_workers "$total")

    max=${DJB_GATE_SLOT_MAX_WAIT:-$GATE_SLOT_DEFAULT_MAX_WAIT}
    poll=${DJB_GATE_LEASE_POLL:-$GATE_LEASE_DEFAULT_POLL}
    announce=${DJB_GATE_LEASE_ANNOUNCE:-$GATE_LEASE_DEFAULT_ANNOUNCE}

    next=$announce
    while :; do
        rc=0
        gate_slot_try "$mode" || rc=$?
        case "$rc" in
        0)
            if [ "$GATE_SLOT_WAITED" -gt 0 ]; then
                echo "- pytest SLOT ACQUIRED after ${GATE_SLOT_WAITED}s of waiting (${GATE_SLOT##*/} of ${total}, pid $$)"
            else
                echo "- pytest slot held: ${GATE_SLOT##*/} of ${total} on this MACHINE (pid $$)"
            fi
            return 0
            ;;
        2) return 2 ;;
        esac

        # Full. `gate_slot_holders` reclaims dead and orphaned slots as a side
        # effect, so an empty answer means one just freed and the loop retries.
        holders=$(gate_slot_holders) || true
        if [ -z "$holders" ]; then
            continue
        fi

        if [ "$GATE_SLOT_WAITED" -eq 0 ]; then
            echo "- WAITING for a pytest SLOT (all ${total} are held). This is not a hang."
            echo "   This is the COUNTING semaphore, not the exclusive full-gate lease:"
            echo "   somebody else's suite is running, not necessarily somebody else's push."
            echo "$holders" | sed 's/^/   holder: /'
            echo "   (slot  pid mode started-utc host started-epoch checkout)"
            echo "   Every pytest leg on this box takes one of ${total} slots and runs"
            echo "   -n $(gate_slot_workers "$total") instead of -n auto, so the workers all the live gates have"
            echo "   started total this machine's cores. Without that ceiling a wave of"
            echo "   builders measured load average 162, 5-8x wall clock, and two runs"
            echo "   killed at the harness ceiling having judged nothing."
            if est=$(gate_slot_estimate "$holders"); then
                echo "   Rough estimate from the holders' elapsed time: ~${est} min. An estimate,"
                echo "   not a promise — nothing here decides anything on it."
            fi
            echo "   Ceiling: ${max}s, after which this run REFUSES (exit 2) rather than"
            echo "   oversubscribing the box."
        elif [ "$GATE_SLOT_WAITED" -ge "$next" ]; then
            echo "  ... still waiting for a pytest slot (${GATE_SLOT_WAITED}s of ${max}s)"
            echo "$holders" | sed 's/^/   holder: /'
            next=$((GATE_SLOT_WAITED + announce))
        fi

        if [ "$GATE_SLOT_WAITED" -ge "$max" ]; then
            echo "!! REFUSING: waited ${GATE_SLOT_WAITED}s for one of ${total} pytest slots and the box is still full." >&2
            echo "$holders" | sed 's/^/   holder: /' >&2
            echo "   slots:  $(gate_slots_dir 2>/dev/null || echo '<unknown>')" >&2
            echo "   Nothing was judged. This is could-not-look, not a red tree." >&2
            echo "   If those holders are gone, the pid check should have reclaimed their" >&2
            echo "   slots — unless they were recorded by another host, which this never" >&2
            echo "   clears on purpose (scripts/gate_lease.sh, THE LIMITS)." >&2
            return 2
        fi

        sleep "$poll"
        GATE_SLOT_WAITED=$((GATE_SLOT_WAITED + poll))
    done
}
