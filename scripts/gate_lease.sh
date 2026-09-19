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
# THE REFUSAL SEAM — scripts/gate_refuse.sh, sourced by this library's own
# directory and guarded against a second source. The lease and slot refusals
# below go through `gate_refuse` so the two `no pytest slot — see above.` banners in
# scripts/check.sh can name which of them fired.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

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
        gate_refuse "DJB_GATE_LEASE_DIR is relative ('$dir'). The full-gate lease needs an"
        echo "   absolute machine-wide directory; a relative one resolves against" >&2
        echo "   whatever directory the caller left behind." >&2
        return 1
        ;;
    esac
    [ -d "$dir" ] || {
        gate_refuse "DJB_GATE_LEASE_DIR ('$dir') is not a directory — no lease can be taken there."
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

# ---- THE HOLDER, IN WORDS ----------------------------------------------
#
# WHY THIS EXISTS. Both wait loops already printed the holder's RECORD, and a
# record is six space-separated fields ending in a path: everything a parser
# needs and nothing a reader can act on. The question an agent watching a wait
# actually has is "how much longer, and is this even the kind of run I think it
# is" — and the three facts that answer it (the holder's MODE, the time it
# STARTED, the arithmetic between that and the nominal for its mode) were all
# already IN the record and none of them was legible. A wait line that a reader
# has to decode by hand is most of the way back to a silent one.
#
# ONE FORMATTER, TWO RECORD SHAPES. The lease record is
# `pid mode started-utc host started-epoch checkout`; a `gate_slot_holders` line
# is that with `slot-N` in front. The two wrappers below differ only in which
# field number each fact sits at, so the phrasing cannot drift apart between the
# exclusive lease's wait and the semaphore's.
#
# AN OLD RECORD LOSES THE CLAUSE AND NOTHING ELSE — the contract
# `gate_lease_estimate` already keeps. A record written before the epoch field
# existed carries the checkout PATH at position 5, so it prints the start time
# alone and no arithmetic; a line that is not a holder record at all (the
# `slot-N (starting — no holder record yet)` shape) comes back verbatim.

# gate_holder_note <started-utc> <started-epoch> <nominal-seconds> — the human
# half of a holder record as ONE appendable clause, on stdout:
#     , started 14:02Z (~9 min of a nominal 15 left)
gate_holder_note() {
    local utc=$1 epoch=$2 nominal=$3 hhmm left now
    case "$utc" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:*) ;;
    *) return 0 ;;
    esac
    hhmm=${utc#*T}
    hhmm="${hhmm%:*}Z"
    printf ', started %s' "$hhmm"
    case "$epoch" in
    '' | *[!0-9]*) return 0 ;;
    esac
    now=$(date +%s)
    left=$((nominal - (now - epoch)))
    [ "$left" -ge 0 ] || left=0
    printf ' (~%s min of a nominal %s left)' \
        "$(((left + 59) / 60))" "$(((nominal + 59) / 60))"
}

# gate_lease_holder_phrase <lease record> — `pid 4123 full, started 14:02Z
# (~9 min of a nominal 15 left)`.
gate_lease_holder_phrase() {
    local line=$1 pid mode utc epoch
    pid=$(awk '{print $1}' <<<"$line")
    case "$pid" in
    '' | *[!0-9]*)
        printf '%s' "$line"
        return 0
        ;;
    esac
    mode=$(awk '{print $2}' <<<"$line")
    utc=$(awk '{print $3}' <<<"$line")
    epoch=$(awk '{print $5}' <<<"$line")
    printf 'pid %s %s%s' "$pid" "$mode" \
        "$(gate_holder_note "$utc" "$epoch" "$GATE_LEASE_NOMINAL_FULL")"
}

# gate_slot_holder_phrase <gate_slot_holders line> — the same, one field over,
# and with the nominal chosen by the holder's own mode: a `--loop` holder is a
# four-minute wait and a `full` holder is a fifteen-minute one, and telling a
# waiter which it is waiting behind is most of the value of the line.
gate_slot_holder_phrase() {
    local line=$1 slot pid mode utc epoch nominal
    slot=$(awk '{print $1}' <<<"$line")
    pid=$(awk '{print $2}' <<<"$line")
    case "$pid" in
    '' | *[!0-9]*)
        printf '%s' "$line"
        return 0
        ;;
    esac
    mode=$(awk '{print $3}' <<<"$line")
    utc=$(awk '{print $4}' <<<"$line")
    epoch=$(awk '{print $6}' <<<"$line")
    case "$mode" in
    # A BANK IS A FULL GATE that took every slot, so a waiter behind one is
    # behind a full gate's nominal — the same reason `full` is here.
    full | bank) nominal=$GATE_SLOT_NOMINAL_FULL ;;
    *) nominal=$GATE_SLOT_NOMINAL_LOOP ;;
    esac
    printf 'pid %s %s (%s)%s' "$pid" "$mode" "$slot" \
        "$(gate_holder_note "$utc" "$epoch" "$nominal")"
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
    # F7, as above: the path refusal happens in a subshell and the cause would
    # otherwise be the previous refusal's, or nothing.
    gate_capture path gate_lease_path || return 2

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
            # THE RE-ANNOUNCEMENT IS THE LINE A READER ACTUALLY WATCHES — the
            # first one scrolls away — so it is the one that has to answer
            # "behind what, since when, how much longer" on its own. It used to
            # print the raw record and a bare "~N min left"; it now says whose
            # run it is, what KIND of run, when it started and how much of that
            # kind's nominal is left.
            echo "  ... still waiting for the full-gate lease: ${GATE_LEASE_WAITED}s of ${max}s — holder $(gate_lease_holder_phrase "$held")"
            next=$((GATE_LEASE_WAITED + announce))
        fi

        if [ "$GATE_LEASE_WAITED" -ge "$max" ]; then
            gate_refuse "REFUSING: waited ${GATE_LEASE_WAITED}s for the machine-wide full-gate lease and it is still held."
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
#:   DJB_GATE_SLOT_WORKERS    the `-n` a slot holder runs, when a caller wants
#:                            fewer workers than its share. AT OR BELOW the
#:                            share only: above it is EXIT 2 naming both
#:                            numbers, and an unreadable value is exit 2 as
#:                            DJB_GATE_SLOTS is. Honoured here because
#:                            scripts/test.sh and apps/conftest.py's ceiling
#:                            already read it — see `gate_slot_worker_count`.
#:                            IT IS ALSO WRITTEN HERE: the resolved share is
#:                            EXPORTED under this name (a bank's is the whole
#:                            box's cores) so those two readers take the number
#:                            the gate started the leg with instead of deriving a
#:                            second one, and `gate_slot_release` unsets it again
#:                            — the share belongs to the slot.
#:   DJB_BANK_SHARES_SLOTS    set to anything: a `--bank` run takes ONE slot and
#:                            one share instead of the whole box. The escape from
#:                            `bank` mode below, for a builder who cannot wait out
#:                            a bank's pytest wall — and the run that takes it
#:                            PRINTS it (principle 20: an exception is recorded,
#:                            never implied). Unset is the default, and the
#:                            default is the whole box.
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

#: The slot directory this process holds, or empty. A BANK holds more than one
#: (see `bank` mode below); this stays the FIRST one it took, so every existing
#: reader of it — the "slot-k of N" line, a caller's own record — keeps meaning
#: what it meant.
GATE_SLOT=""
#: Every slot directory this process holds, one per line, in the order taken.
#: One slot for every mode but `bank`, where it is the whole box. `GATE_SLOT` is
#: always its first line; `gate_slot_release` walks this.
GATE_SLOTS_HELD=""
#: Seconds this process spent waiting for a slot. 0 is the normal case.
GATE_SLOT_WAITED=0
#: Resolved by `gate_slot_acquire`: how many slots this box has, and the `-n`
#: a holder must run. The caller PRINTS both — a worker count nobody can see is
#: a worker count nobody notices going wrong.
GATE_SLOT_TOTAL=""
GATE_SLOT_WORKERS=""
#: Where `GATE_SLOT_WORKERS` came from, in one phrase — `derived` for the
#: ordinary share, or the typed sentence `gate_slot_worker_count` prints. A
#: transcript that shows the number without its provenance cannot tell a share
#: from a knob, which is the whole of the false red below.
GATE_SLOT_WORKERS_PROV=""
#: THE ONE SENTENCE A PYTEST LEG PRINTS BESIDE THE NUMBER, set here because this
#: is where the number is decided. The leg used to carry its own parenthetical
#: ("this box's cores split N ways"), which is FALSE with the knob set and false
#: again under a bank — two sentences about one number, one of them wrong, on the
#: line a reader uses to check the number.
GATE_SLOT_WORKERS_PHRASE=""
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
            gate_refuse "DJB_GATE_SLOTS='$want' is not a positive whole number."
            echo "   A ceiling this cannot read is a ceiling that would silently become the" >&2
            echo "   default, which is the unbounded run the semaphore exists to stop." >&2
            return 2
            ;;
        esac
        if [ "$want" -lt 1 ]; then
            gate_refuse "DJB_GATE_SLOTS='$want' — a box with no slots can run no suite at all."
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

# gate_slot_worker_count <total> — the `-n` this holder will run, WITH its
# provenance. Sets `GATE_SLOT_WORKERS` and `GATE_SLOT_WORKERS_PROV`; prints the
# typed line when the number did not come from the share; exit 2 when a typed
# `DJB_GATE_SLOT_WORKERS` cannot be honoured. Never takes a slot and starts
# nothing, which is what lets a drive ask it the question the gate asks.
#
# THE DEFECT IT CLOSES. `DJB_GATE_SLOT_WORKERS` is a DOCUMENTED knob:
# `scripts/test.sh` reads it as the share, and `apps/conftest.py`'s ceiling
# reads it FIRST of all. The gate did not, so with it set there were two
# numbers — the gate started `-n <derived share>`, pytest clamped itself down to
# the typed value, and the collector-shortfall refusal compared the survivors
# against the PRE-CLAMP number. A clean suite with no plant at all then printed
# `2 of 5 collectors reported — a collector died`, exit 2, nothing banked
# (measured on a field test's control run with the knob set and no plant at
# all). The knob is honoured HERE,
# at the one place the number is derived, so `-n`, the clamp's ceiling and the
# refusal's expected population are ONE number by construction rather than three
# that happen to agree (principle 9: the worker count has one owner).
#
# AND IT ONLY EVER NARROWS. A typed value ABOVE this slot's share is refused,
# not clamped: N slots x cores/N workers = this machine's cores is the whole
# arithmetic the semaphore keeps, and a knob that WIDENS one slot spends the
# share of every gate that is still believing in its own. Exit 2 naming both
# numbers, because a silent lowering would teach the knob's reader that the
# value they typed is the value that ran.
#
# THE OPTIONAL SECOND ARGUMENT is this holder's share when it is not one slot's:
# a BANK holds every slot, so its share is the whole box's cores, and the ceiling
# the typed knob is measured against has to move with it or a bank could never
# be told to run fewer workers than the box. One argument, one meaning: "the most
# this holder may run". Everything below is unchanged by it.
#
# AND THE NUMBER IS HANDED DOWN, which is the half that was missing and the half
# that cost the first live merge-train bank. The gate derived the bank's whole-box
# share here, started `-n 10` — and `apps/conftest.py`'s worker ceiling, finding
# NOTHING in its environment, derived a number of its OWN (this box's cores ÷ its
# slots = one slot's 5), clamped the leg down to it, and let 5 workers run a suite
# the collector census was expecting 10 collectors from: `5 of 10 collectors
# reported — a collector died`, exit 2, nothing banked, nothing pushed, on a suite
# that had just passed 3653 tests (bank-2349.log, 2026-09-16). Two mechanisms held
# different numbers for one run.
#
# `export`, not a `local`: `apps/conftest.py`'s ceiling reads
# `DJB_GATE_SLOT_WORKERS` FIRST OF ALL and its own comment already calls that "the
# caller handing down the share it already took, and this must never second-guess
# it" — the channel existed, the gate simply never wrote to it. `scripts/test.sh`
# reads the same name first and passes it through. So the share is derived ONCE,
# here, and the three readers — this leg's `-n`, the python ceiling, and the
# census's expected population — are one number by construction rather than three
# derivations that happen to agree on every box but a bank's (principle 9: the
# worker count has one owner).
#
# IT IS THE SLOT'S, AND `gate_slot_release` GIVES IT BACK. A bank's share is the
# whole box only while the bank holds the whole box; leaving it exported past the
# release would hand a number that is true of nothing to everything that runs
# after the suite — the self-test leg's drives measure the DERIVED ceiling, and
# they run after `gate_slot_release`.
gate_slot_worker_count() {
    local total=$1 share want
    share=${2:-}
    [ -n "$share" ] || share=$(gate_slot_workers "$total")
    want=${DJB_GATE_SLOT_WORKERS:-}
    if [ -z "$want" ]; then
        GATE_SLOT_WORKERS=$share
        GATE_SLOT_WORKERS_PROV="derived"
        GATE_SLOT_WORKERS_PHRASE="this box's cores split ${total} ways — one share per pytest slot"
        export DJB_GATE_SLOT_WORKERS="$GATE_SLOT_WORKERS"
        return 0
    fi
    case "$want" in
    *[!0-9]*)
        gate_refuse "DJB_GATE_SLOT_WORKERS='$want' is not a positive whole number."
        echo "   The gate runs -n <this value> and apps/conftest.py's worker ceiling reads" >&2
        echo "   the same variable, so a value neither of them can read is two different" >&2
        echo "   worker counts — which is the false red this knob was measured causing." >&2
        echo "   Unset it and take this slot's derived share of ${share}." >&2
        return 2
        ;;
    esac
    if [ "$want" -lt 1 ]; then
        gate_refuse "DJB_GATE_SLOT_WORKERS='$want' — a pytest leg with no workers runs no suite at all."
        echo "   Set it to at least 1, or unset it and take this slot's derived share of ${share}." >&2
        return 2
    fi
    if [ "$want" -gt "$share" ]; then
        gate_refuse "DJB_GATE_SLOT_WORKERS=${want} is ABOVE this slot's share of ${share}."
        echo "   This slot is one of ${total} on a box with $(gate_slot_cores) cores, and the arithmetic" >&2
        echo "   the semaphore keeps is N slots x cores/N workers = this machine's cores." >&2
        echo "   A knob that WIDENS a slot spends the share of every other gate that is" >&2
        echo "   still running its own, which is the oversubscription the semaphore exists" >&2
        echo "   to stop. Lower it to ${share} or below, or raise DJB_GATE_SLOTS if this box" >&2
        echo "   should hand out fewer, larger slots." >&2
        echo "   Nothing was judged: no slot was taken and no suite started." >&2
        return 2
    fi
    GATE_SLOT_WORKERS=$want
    GATE_SLOT_WORKERS_PROV="typed: DJB_GATE_SLOT_WORKERS, at or below this slot's share of ${share}"
    GATE_SLOT_WORKERS_PHRASE="$GATE_SLOT_WORKERS_PROV"
    # HANDED DOWN ON THIS PATH TOO, and it is not a no-op: a typed value reaches
    # this function through a command PREFIX (`DJB_GATE_SLOT_WORKERS=2
    # gate_slot_worker_count 2`), which bash pops on return. Exporting it is what
    # makes the honoured number survive into the suite the caller is about to
    # start, on the typed path exactly as on the derived one.
    export DJB_GATE_SLOT_WORKERS="$GATE_SLOT_WORKERS"
    # PRINTED AT THE SOURCE, in the `workers:` grammar the two pytest legs print
    # their own line in. The number below IS the number those lines show; this
    # line is the only place the transcript says where it came from, and a
    # derived run prints nothing extra because its own line already says.
    echo "  workers:    -n ${want} (${GATE_SLOT_WORKERS_PROV})"
    return 0
}

# gate_slots_dir — where the slots live. Derived from `gate_lease_path` so the
# absolute/existing checks on DJB_GATE_LEASE_DIR are inherited rather than
# re-stated: two opinions about a machine-wide directory is one too many.
gate_slots_dir() {
    local p
    # F7: `gate_lease_path` refuses in a SUBSHELL here, so its cause reaches the
    # global only through the capture. See scripts/gate_refuse.sh — and note
    # that this function is itself called under `$(...)` by `gate_slot_try`,
    # which is why that call site captures too: one broken link loses the chain.
    gate_capture p gate_lease_path || return 1
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

# gate_slot_holders_render <holders> — the holder list as a WAITER should read
# it: a bank's slots collapse into ONE line naming the bank, and every other
# record comes through verbatim.
#
# WHY A BANK IS COLLAPSED AND NOTHING ELSE IS. The generic table answers "who
# holds a slot", which is the right question when N different runs hold N slots
# and the wrong one when ONE run holds them all: a builder reading two anonymous
# rows with the same pid learns that the box is full and nothing about what to do
# about it. `bank holds 2/2 slots — loops wait` says which run, that it is the
# push, and — with the estimate below it — roughly how long. The escape
# (`--loop --mine`, a targeted pytest) is then theirs to take rather than a kill.
#
# THE MULTI-BANK CASE IS DECLARED, NOT HANDLED: two banks cannot hold slots at
# once (a bank is a full gate and the exclusive lease admits one), so a second
# bank pid would be folded into the first line's count. If that ever happens the
# machine has a broken lease, which is a louder problem than a mis-rendered line.
gate_slot_holders_render() {
    local holders=$1 line mode total rest="" bankpid="" bankutc="" bankcount=0
    total=$(gate_slots_total 2>/dev/null) || total="?"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        mode=$(awk '{print $3}' <<<"$line")
        if [ "$mode" = "bank" ]; then
            bankcount=$((bankcount + 1))
            if [ -z "$bankpid" ]; then
                bankpid=$(awk '{print $2}' <<<"$line")
                bankutc=$(awk '{print $4}' <<<"$line")
            fi
            continue
        fi
        rest="${rest}${line}
"
    done <<EOF
${holders}
EOF
    if [ "$bankcount" -gt 0 ]; then
        printf 'bank holds %s/%s slots — loops wait (pid %s, started %s)\n' \
            "$bankcount" "$total" "$bankpid" "$bankutc"
    fi
    printf '%s' "${rest%$'\n'}"
}

# gate_slot_try <mode> — take a slot without waiting.
# Exit: 0 taken (GATE_SLOT set) · 1 the box is full · 2 could not look.
#
# `mkdir` is the claim and it is atomic on every filesystem, including the NFS
# and bind mounts where an O_EXCL create historically was not — which is why the
# slots are directories and the lease one file over is not.
gate_slot_try() {
    local mode=$1 dir total i slot
    gate_capture dir gate_slots_dir || return 2
    mkdir -p "$dir" 2>/dev/null || {
        gate_refuse "the gate slot directory ('$dir') could not be created — no slot can be taken there."
        return 2
    }
    gate_capture total gate_slots_total || return 2
    i=0
    while [ "$i" -lt "$total" ]; do
        i=$((i + 1))
        slot="$dir/slot-$i"
        if mkdir "$slot" 2>/dev/null; then
            gate_slot_line "$mode" >"$slot/holder" 2>/dev/null || true
            [ -n "$GATE_SLOT" ] || GATE_SLOT=$slot
            GATE_SLOTS_HELD="${GATE_SLOTS_HELD}${slot}
"
            return 0
        fi
    done
    return 1
}

# gate_slot_release — give back EVERY slot this process holds, and only the ones
# it holds. One for every mode but `bank`, which holds the box.
#
# THE PID TEST IS PER SLOT, not once for the set: a leg whose EXIT trap fires
# after somebody else has taken a slot must not delete theirs, and that is as
# true of the second slot as of the first. A release that let go of one slot of a
# bank's N would leave the box permanently smaller after every push, with no tell
# but builders waiting longer for a slot nobody holds.
gate_slot_release() {
    local slot pid seen=""
    # `GATE_SLOT` is walked too, and not only for belt: a caller may have set it
    # by hand (the drive does, to prove a non-holder cannot release), and the pid
    # test below is what answers that case.
    while IFS= read -r slot; do
        [ -n "$slot" ] || continue
        case "${seen}" in
        *"[${slot}]"*) continue ;;
        esac
        seen="${seen}[${slot}]"
        pid=$(awk 'NR==1{print $1}' "$slot/holder" 2>/dev/null || true)
        if [ "$pid" = "$$" ]; then
            rm -rf "$slot"
        fi
    done <<EOF
${GATE_SLOTS_HELD}${GATE_SLOT}
EOF
    GATE_SLOTS_HELD=""
    GATE_SLOT=""
    # THE SHARE BELONGS TO THE SLOT, so it goes back with it. `gate_slot_worker_count`
    # exports the number this holder started its leg with (see the hand-down note
    # there); a bank's is the WHOLE BOX, and a whole-box share left in the
    # environment after the box has been given back is a ceiling that is true of
    # nothing. Everything the full gate runs after the suite would inherit it —
    # the self-test leg's drives among them, which measure the DERIVED ceiling and
    # would each be measuring the released bank's instead.
    unset DJB_GATE_SLOT_WORKERS
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
# <mode> is `loop`, `full` or `bank`; it is recorded and it is what the estimate
# above reads.
#
# Exit: 0 held · 2 the ceiling was reached, the slot directory cannot be used,
# DJB_GATE_SLOTS is unreadable, or the lock order was broken. 2 and not 1
# throughout: a suite that never ran has judged nothing, and could-not-look
# outranks a pass everywhere in this gate.
#
# ---------------------------------------------------------------------------
# `bank` — THE ONE CALLER THAT TAKES THE WHOLE BOX, and why it is not greed.
#
# A `--bank` run is the PM's push: the one run on this machine whose wall clock
# every other agent is waiting on, and the only one whose verdict is banked for
# everybody. It used to take ONE slot like any other full gate and then run its
# two whole-suite passes on a third of the machine beside two `--loop` runs
# (`waited=12 took=613` on a real verdict row; a consumer's pass 1 took forty
# minutes at load 50). That is principle 7 upside down — the critical path
# queueing behind the inner loop.
#
# So `bank` takes EVERY slot: the free ones immediately, the held ones as they
# free, and it returns 0 only holding all of them. `GATE_SLOT_WORKERS` is then
# the whole box's cores rather than one slot's share, because the arithmetic the
# semaphore keeps is unchanged — one holder of N slots runs N shares.
#
# WHY IT CANNOT DEADLOCK, and this is THE LOCK ORDER's argument at the bank's
# width: one full gate at a time holds the machine-wide exclusive lease, and a
# bank is a full gate, so there is never a second bank to wait for. A `--loop`
# holds a slot and NEVER wants the lease. Therefore every slot a bank waits for
# is held by a loop that is running to completion and will give it back, and
# nothing on this box waits on the bank except loops. The cycle needs somebody
# holding a slot while waiting for the lease, and the refusal above is what makes
# that impossible rather than merely unlikely.
#
# WHAT IT COSTS, said out loud rather than discovered: while a bank holds the
# box, every `--loop` that arrives waits for roughly the bank's pytest wall, and
# `DJB_GATE_SLOT_MAX_WAIT` will REFUSE (exit 2, could-not-look) a loop that
# queued longer than the ceiling. `DJB_BANK_SHARES_SLOTS=1` is the escape and it
# is PRINTED by the run that takes it (principle 20: an exception is recorded,
# never implied) — a bank that shares takes one slot and one share, exactly as a
# sanctioned full gate does.
#
# THE REJECTED SHAPES, so nobody re-proposes them. *Wait for the box to be EMPTY
# of loops first*: unbounded — builders keep starting loops, so the bank can
# starve. Taking slots as they free is bounded by the slots held when the bank
# started. *One slot, `-n cores`*: the loops beside it still start their own
# shares, which is exactly the oversubscription the semaphore exists to cap.
gate_slot_acquire() {
    local mode=${1:-loop} rc max poll announce next holders est total
    local hfirst hrest hline shown
    local want share held=0 need=1
    GATE_SLOT_WAITED=0
    GATE_SLOT=""
    GATE_SLOTS_HELD=""

    # THE LOCK ORDER, mechanically. A full run that reached here without its
    # exclusive lease could sit on a slot while waiting for the lease that a
    # slot-waiting gate is holding — the cycle. Refused rather than documented.
    if [ -n "${GATE_SLOT_LEASE_FIRST:-}" ] && [ -z "${GATE_LEASE:-}" ]; then
        gate_refuse "LOCK ORDER BROKEN: a FULL gate reached the pytest slot without holding the"
        echo "   machine-wide exclusive lease. The order is LEASE FIRST, THEN SLOT — always," >&2
        echo "   on every path — so that no slot holder is ever waiting for the lease and the" >&2
        echo "   deadlock cycle cannot be formed (scripts/gate_lease.sh, THE LOCK ORDER)." >&2
        echo "   Nothing was judged." >&2
        return 2
    fi

    gate_capture total gate_slots_total || return 2
    GATE_SLOT_TOTAL=$total

    # THE BANK'S WIDTH, decided before anything is taken. `want=all` is the whole
    # box; the typed escape narrows it back to one slot and SAYS SO, in its own
    # transcript, at the moment it is taken.
    want=one
    share=""
    if [ "$mode" = "bank" ]; then
        if [ -n "${DJB_BANK_SHARES_SLOTS:-}" ]; then
            echo "  bank shares the box: DJB_BANK_SHARES_SLOTS=1 — this bank takes ONE slot and"
            echo "              one share, exactly as a sanctioned full gate does. The loops beside"
            echo "              it keep theirs, and this run measures a box it is sharing."
        else
            want=all
            need=$total
            gate_capture share gate_slot_cores || return 2
        fi
    fi

    # NOT under `$(...)`: the refusal's cause has to reach this shell's global so
    # the caller's banner can print it (scripts/gate_refuse.sh, the subshell
    # rule), and a typed knob is refused HERE — above the slot, above the wait,
    # above any suite — so an unhonourable number never queues for the box.
    gate_slot_worker_count "$total" "$share" || return 2

    max=${DJB_GATE_SLOT_MAX_WAIT:-$GATE_SLOT_DEFAULT_MAX_WAIT}
    poll=${DJB_GATE_LEASE_POLL:-$GATE_LEASE_DEFAULT_POLL}
    announce=${DJB_GATE_LEASE_ANNOUNCE:-$GATE_LEASE_DEFAULT_ANNOUNCE}

    next=$announce
    while :; do
        # TAKE WHAT IS FREE, up to what this mode needs. For every mode but a
        # whole-box bank `need` is 1 and this inner loop runs exactly once, which
        # is the behaviour every non-bank caller had before the bank existed.
        rc=0
        while [ "$held" -lt "$need" ]; do
            rc=0
            gate_slot_try "$mode" || rc=$?
            [ "$rc" = "0" ] || break
            held=$((held + 1))
        done
        [ "$rc" != "2" ] || return 2
        if [ "$held" -ge "$need" ]; then
            if [ "$want" = "all" ]; then
                # The one sentence the leg prints beside `-n`: this holder is not
                # one slot's share of the box, it IS the box.
                GATE_SLOT_WORKERS_PHRASE="bank: every slot — ${held}/${total}; loops wait"
                if [ "$GATE_SLOT_WAITED" -gt 0 ]; then
                    echo "- BANK COMPLETE after ${GATE_SLOT_WAITED}s of waiting: it holds ALL ${held} of ${total} pytest slots (pid $$)"
                else
                    echo "- pytest slots held: this BANK holds ALL ${held} of ${total} on this MACHINE (pid $$)"
                fi
                echo "   Every --loop that arrives now waits for this run, and is told so by name."
                echo "   The escape, for a builder who cannot wait: DJB_BANK_SHARES_SLOTS=1."
            elif [ "$GATE_SLOT_WAITED" -gt 0 ]; then
                echo "- pytest SLOT ACQUIRED after ${GATE_SLOT_WAITED}s of waiting (${GATE_SLOT##*/} of ${total}, pid $$)"
            else
                echo "- pytest slot held: ${GATE_SLOT##*/} of ${total} on this MACHINE (pid $$)"
            fi
            return 0
        fi

        # Full. `gate_slot_holders` reclaims dead and orphaned slots as a side
        # effect, so an empty answer means one just freed and the loop retries.
        holders=$(gate_slot_holders) || true
        if [ -z "$holders" ]; then
            continue
        fi
        # A BANK IS NOT ITS OWN HOLDER. It is standing in the list it is reading —
        # its own taken slots are held, by it — and a wait that reported them
        # would tell the reader the bank is waiting for itself. What it is
        # actually waiting for is everybody ELSE's slots, so those are what it
        # counts, estimates from and prints.
        if [ "$want" = "all" ]; then
            holders=$(awk -v me="$$" '$2 != me' <<<"$holders")
            if [ -z "$holders" ]; then
                continue
            fi
        fi
        # WHAT A WAITER IS SHOWN: a bank's slots as one line naming the bank,
        # every other record verbatim. The raw list is what the estimate reads.
        shown=$(gate_slot_holders_render "$holders") || shown=$holders

        if [ "$GATE_SLOT_WAITED" -eq 0 ]; then
            if [ "$want" = "all" ]; then
                # THE BANK'S OWN HEADLINE. "All N are held" is not what is
                # happening — this run holds some of them — and a bank reading
                # the loop's sentence would be reading somebody else's situation.
                echo "- WAITING for the REST of the box: this BANK holds ${held} of ${total} pytest slots"
                echo "   and is waiting for the rest, taking each as it frees. This is not a hang."
                echo "   A bank runs the whole box on purpose: it is the push everybody's verdict"
                echo "   comes from, and it used to measure a third of the machine while two"
                echo "   builders' loops measured the other two thirds."
            else
                echo "- WAITING for a pytest SLOT (all ${total} are held). This is not a hang."
                echo "   This is the COUNTING semaphore, not the exclusive full-gate lease:"
                echo "   somebody else's suite is running, not necessarily somebody else's push."
            fi
            echo "$shown" | sed 's/^/   holder: /'
            case "$shown" in
            slot-* | *"
"slot-*)
                echo "   (slot  pid mode started-utc host started-epoch checkout)"
                ;;
            esac
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
            # The lease's re-announcement reason, one guard over, with one
            # difference: the semaphore can have N holders, so the FIRST one
            # rides on the headline (which is the whole line in the ordinary
            # one-slot-behind case) and the rest follow it, each phrased the
            # same way. No `sed`, no pipeline: a holder list is small and
            # parameter expansion cannot hand this loop somebody's exit status.
            hfirst=${shown%%$'\n'*}
            hrest=${shown#*$'\n'}
            [ "$hrest" != "$shown" ] || hrest=""
            echo "  ... still waiting for a pytest slot: ${GATE_SLOT_WAITED}s of ${max}s — holder $(gate_slot_holder_phrase "$hfirst")"
            if [ -n "$hrest" ]; then
                while IFS= read -r hline; do
                    [ -n "$hline" ] || continue
                    echo "   holder $(gate_slot_holder_phrase "$hline")"
                done <<<"$hrest"
            fi
            next=$((GATE_SLOT_WAITED + announce))
        fi

        if [ "$GATE_SLOT_WAITED" -ge "$max" ]; then
            if [ "$want" = "all" ]; then
                gate_refuse "REFUSING: this BANK waited ${GATE_SLOT_WAITED}s for the rest of the box and still holds only ${held} of ${total} pytest slots."
                # GIVING BACK WHAT IT TOOK, here rather than only in the caller's
                # EXIT trap: a bank that is not going to run must not sit on a
                # partial box while its caller unwinds, and the belt (the trap)
                # stays where it is.
                gate_slot_release
                echo "   the ${held} slot(s) this run had taken were released." >&2
            else
                gate_refuse "REFUSING: waited ${GATE_SLOT_WAITED}s for one of ${total} pytest slots and the box is still full."
            fi
            echo "$shown" | sed 's/^/   holder: /' >&2
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
