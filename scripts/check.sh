#!/usr/bin/env bash
# THE gate.
#   ./scripts/check.sh          full: --loop + supply chain (first of the full
#                               legs — the only one that leaves this machine) +
#                               TWO pytest passes under one seed + canary
#                               self-test + full house rules; records a verdict
#                               keyed on the tree hash. SANCTIONED — see THE
#                               FULL GATE IS SANCTIONED below: bare, it is legal
#                               only from the pre-push hook, and anywhere else
#                               it needs --bank (from the ritual checkout) or a
#                               typed DJB_GATE_SANCTION.
#   ./scripts/check.sh --bank   the same full run, asked for deliberately from
#                               the primary checkout or pm-push, to bank a
#                               verdict for a tree about to be pushed. Records
#                               caller=pm-bank unless the caller said otherwise.
#   ./scripts/check.sh --pr --base <sha>
#                               the same full run, in the same order, under the
#                               same lease and slot, with ONE difference: the two
#                               pytest passes are pointed at the closure of what
#                               `<sha>...HEAD` changed, and the organ tier is NOT
#                               applied. Sanctioned like any other full run, and
#                               it BANKS NOTHING. See THE `--pr` VARIANT below.
#   ./scripts/check.sh --fast   the static legs — what pre-commit runs. No
#                               database, no network, no suite: seconds, not
#                               minutes.
#   ./scripts/check.sh --loop   --fast + the Django deploy checks + detect-secrets
#                               over THE ACTIVE RUNG'S CHANGED FILES ONLY (the
#                               full-tree scan stays at push) + ONE pytest pass,
#                               one slot's share of the cores, fresh seed, TIERED
#                               (see below) — the per-rung gate. The pytest leg is
#                               nearly all of it.
#                               TWO VALVES, AND BOTH PRINT WHEN THEY ARE OPEN —
#                               listed together because they are the pair a
#                               builder reaches for and nothing else here had
#                               them side by side:
#                                 DJB_LOOP_NO_CACHE=1  do not consult the loop
#                                   ledger and bank nothing: measure this tree.
#                                 DJB_LOOP_NO_SYNC=1   do not bring `.venv` to
#                                   the lockfile before the key is derived. The
#                                   escape for a hand-patched environment, and
#                                   its price is the defect the sync closes:
#                                   whatever the first `uv run` installs moves
#                                   the key's env half, so a completely green
#                                   run banks nothing (loop_env_sync,
#                                   scripts/gate_ledger.sh).
#   ./scripts/check.sh --loop --mine
#                               `--loop` with ONE narrowing: the touched apps run
#                               in full and the reverse `depends_on` closure is
#                               NOT walked. An inner-loop run — it says so, and it
#                               neither consults nor banks a loop verdict. See
#                               THE `--mine` MODIFIER below.
#   ./scripts/check.sh --census the instrument census and nothing else — no lease,
#                               no lock, no pytest slot, no leg banner — exiting
#                               with the census's own status. See THE INSTRUMENT
#                               CENSUS, AS A FUNCTION AND AS A MODE below.
#   ./scripts/check.sh --list-legs
#                               the gate's own legs, grouped into the UNITS a
#                               runner can be handed one at a time — one
#                               tab-separated line per unit, exit 0. No venv, no
#                               database, no docker, no network, no lease, no
#                               lock, no slot: it reads this file and the unit
#                               declarations in it and prints. See THE UNIT
#                               TABLE, AND `--list-legs` below.
#   ./scripts/check.sh --leg <unit> [--shard k/N] [--passes 1] [--store-durations]
#                               ONE UNIT of the full gate: its legs announced
#                               and run in the full gate's own order, nothing
#                               else announced and nothing else run, under the
#                               full gate's exit contract. It takes NO machine
#                               lease and NO checkout lock, RECORDS NO verdict
#                               of any kind, and needs NO sanction — a unit is a
#                               targeted drive the way the per-rung gate is
#                               (rung-execution §3). A unit whose legs run a
#                               suite takes ONE pytest slot, exactly as the
#                               per-rung gate does. The unit names are
#                               `--list-legs`'s and an unknown one is exit 2
#                               pointing there. `--shard k/N` runs the k-th of N
#                               parts of a unit the listing calls N-capable and
#                               is exit 2 on any other. `--passes 1` runs ONE
#                               whole pass of the suite leg instead of two, and
#                               is legal ONLY beside a `--shard` on a unit that
#                               runs the suite: the second pass is the
#                               idempotency belt, and a shard drops it only
#                               because the whole-suite two-pass leak proof runs
#                               elsewhere — the bank's acceptance box, under
#                               ADR gate-1's amendment. `--passes 2` is the
#                               default and prints nothing new, and every
#                               other value is exit 2.
#                               `--store-durations` rewrites
#                               scripts/pytest_durations.json, the file
#                               the split balances by. It composes with
#                               `--pr --base <sha>`. See RUNNING ONE UNIT below.
#   ./scripts/check.sh --store-durations
#                               THE FULL GATE, RUN TO BE TIMED. Every leg and
#                               every drive as a bare full run does, and at the
#                               end scripts/gate_member_durations.json is
#                               rewritten from this run's own clock. It BANKS
#                               NOTHING — a tracked file written during a run
#                               moves the tree that run would have vouched for
#                               — and the file is committed by whoever ran it,
#                               as the measurement it is. The `--loop`
#                               always-on set is derived from it: see the
#                               `always-on-leg` fence below.
#
# THAT LIST IS THE WHOLE OF WHAT THE PARSER TAKES, and it is checked rather than
# remembered: `scripts/tests/test_gate_lease.sh`'s
# `case_the_usage_header_and_the_parser_agree` extracts the flag tokens from this
# header and from the mode `case` below and asserts the two sets are equal, both
# ways. A header that named a mode the parser refuses would send a reader to an
# exit 2, and a mode the header omits is a mode nobody finds — both were true of
# this file before that case existed, and both were prose nothing measured.
#
# HOW LONG IT TAKES IS PRINTED, NOT WRITTEN DOWN HERE. Every leg prints its own
# wall time as it finishes and the mode prints its total, and that is the only
# number about this file that cannot go stale. A hand-written header number is a
# claim about a tree that changes daily and reliably drifts as the suite grows
# underneath the sentence nobody re-measures — this file used to carry one,
# true when ADR gate-1 wrote it and wrong by the time the suite had grown past
# 2600 tests; the printed line is a measurement of the tree in front of you.
# Measured once on a ten-core Apple laptop, quiet
# machine, 2613 tests: the untiered suite at one worker per core is ~80s wall and
# ~270s of CPU across ten workers, of which ~58s of CPU — ten setup entries of
# 5.5-6.2s, one per worker — is the per-worker test database being created and
# migrated before a single assertion runs. Prefer the printed line over any
# number here.
#
# `--loop` IS TIERED AND THE FULL GATE IS NOT. The per-rung pytest
# leg runs the FAST TIER plus the active rung's own app; the slow tier is every test
# that reaches a real organ (the compose MinIO, a real time-skipping Temporal
# server, the compose Meilisearch), DERIVED from organ-fixture reach and module
# source rather than from any list, and it runs in full at push — twice, like
# everything else. The derivation, its floors and its blind spots are
# `apps/conftest.py`'s; the own-app half is `scripts/loop_tier.sh`'s; both are
# driven case by case by `scripts/tests/test_loop_tier.sh` in the selftest leg.
# The leg PRINTS which tier it ran and why on every single run.
#
# THE SUITE RUNS PARALLEL AND IN RANDOM ORDER (ADR gate-1). Both pytest legs
# below run `-n <one slot's share of this box's cores>` — NEVER `-n auto` any
# more, and that changed for a measured reason: see ONE PYTEST LEG PER SLOT
# below. Each worker gets its OWN test database (pytest-django suffixes this
# checkout's derived name: `test_<DATABASE_NAME>_gw0..gwN`, so worker isolation
# nests inside the checkout isolation from `scripts/db.sh` and two checkouts
# still never meet). pytest-randomly shuffles collection and prints the seed it
# used at the top of every run; a red order replays exactly by handing that seed
# back through pytest-randomly's seed option at the worker count the leg printed
# (`./scripts/test.sh` passes its arguments straight through).
#
# The two legs differ in TWO ways now, and both are the point. The first is the
# seed: `--loop` takes a fresh one every run (discovery, continuously, at the
# most-attended tier), while the full gate's `pytest-x2` feeds ONE seed to BOTH
# passes so that the only
# difference between them is what pass 1 left behind. See that leg. The second
# is the TIER: `--loop` runs the fast one, the full gate runs everything. So a
# green `--loop` is a claim about most of the suite and a green push is a claim
# about all of it, and neither leg lets that be inferred — each says which it is.
#
# ONE GATE AT A TIME PER CHECKOUT: the full run holds a lock in this checkout's
# git directory for its whole duration, and --fast/--loop refuse (exit 2, naming
# the holder) while it is held. A dead holder's lock clears itself. Another
# worktree is another checkout and is never affected. See the lock section below.
#
# ONE FULL GATE AT A TIME PER MACHINE: the full run also holds a LEASE in
# a machine-wide directory, and a second full gate anywhere on this box WAITS for
# it — out loud, naming the holder — rather than running beside it. Two full
# gates contend for every core (each runs the whole suite twice, plus a real
# Meili, MinIO and Temporal), and the measurement is 607s with two RED tests
# contended against 99s green quiet on the same tree. --fast and --loop take NO
# lease and never wait on one. Its scope, its trust class and its declared limit
# — one machine, never cross-machine CI — are `scripts/gate_lease.sh`'s header.
#
# ONE PYTEST LEG PER SLOT, N SLOTS PER MACHINE. A SECOND and different guard,
# and the distinction matters to anybody reading a wait: the lease above is
# EXCLUSIVE and only full gates take it; the SLOT is a COUNTING semaphore and
# EVERY pytest leg takes one — `--loop`'s included. It exists because the load
# that flattened this box was never a second full gate: it was a wave of
# builders each running `--loop`, whose pytest leg took one worker per core —
# five and more times over on ten cores. Measured: load average 162,
# 5-8x wall clock, and two runs killed at the harness ceiling having judged
# nothing. So the box has N slots (cores/5, floor, `DJB_GATE_SLOTS` overrides),
# a slot holder runs `-n cores/N`, and the arithmetic closes: however many gates
# are live, the workers they have started total this machine's cores. `--fast`
# takes no slot and never waits — it has no suite. The lock order is fixed and
# mechanically enforced (LEASE FIRST, THEN SLOT) so the two guards cannot
# deadlock; the limits and the trust class are `scripts/gate_lease.sh`'s header.
#
# THE CALLER IS RECORDED: a full run's ledger and run-log lines carry
# `caller=<kind>` from `DJB_GATE_CALLER` — `push-wall` (the pre-push hook sets
# it), `quality-rung`, `pm-bank`, or `unstated` when nobody said. That field is
# measurement only and no run is refused for it; the REFUSAL is the sanction
# check below, which is a different question (not "which kind" but "why at
# all"), and its answer rides into the same verdict row as `sanction=`. See
# `scripts/gate_ledger.sh`.
#
# Exit: 0 clean · 1 violations · 2 ENFORCEMENT BROKEN. 2 outranks a pass.
# Never pipe this script: a pipe replaces its exit status with the pipe's — and
# it no longer only says so, it refuses (exit 2). Redirect to a file instead.
set -euo pipefail

# --- the gate refuses to be piped -------------------------------------------
# A pipe replaces the gate's exit status with the filter's and hides legs while
# they run; a TTY or a file redirect keeps both, so those stay legal. This sits
# above argument handling so --fast, --loop and the full run all share it, and
# the refusal is exit 2 — a filtered gate is broken enforcement, not a failure.
#
# Detection: `test -p` on the stdout fd. macOS exposes it at /dev/fd/1 (verified
# on darwin 24.6: `| cat` -> -p true, `> file` -> -f true, pty -> -t true) and
# Linux does too, via /proc/self/fd. If neither path exists the test is simply
# false and the gate runs: a missing /dev/fd is an environment quirk, not a
# filtered gate, and failing open beats refusing to enforce.
#
# CI is exempt because GitHub Actions captures every step's stdout through a
# pipe, so the guard would refuse every CI run. Residual risk, accepted: an
# agent exporting CI=1 to get a pipe is deliberate circumvention and is visible
# in the command line. This guard stops casual filtering, not sabotage.
#
# The pre-push hook needs no exemption: git INHERITS its own stdout for the hook
# rather than capturing it (verified on git 2.39.5 — a TTY push gives the hook a
# TTY, `git push > f` gives it a regular file, `git push | cat` gives it a pipe).
# So a bare push runs the gate and only a piped push is refused, which is the
# rule doing its job one level up.
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! the gate refuses pipes — run it bare or redirect to a file; the exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/.."

MODE=${1:-}
#: Set by `--bank`. The flag is the PM's ritual bank — a full run asked for
#: deliberately, from the checkout family's primary or its pm-push worktree, so
#: that the tree about to be pushed has a verdict before the push. It is a
#: SANCTION, not a mode: it normalises to `MODE=""` immediately below and every
#: line after this point runs the identical full gate. See THE FULL GATE IS
#: SANCTIONED below.
GATE_BANK=""
#: Set by `--pr`. Like `--bank` it is NOT a mode: it normalises to `MODE=""`
#: immediately below and every leg after this point is the full gate's, in the
#: full gate's order, under the full gate's lease and slot. What it changes is
#: the TARGET of the two pytest passes and nothing else — see THE `--pr`
#: VARIANT below.
GATE_PR=""
#: The commit `--pr` was handed as the base of the proposed change. Required
#: whenever GATE_PR is set; the refusal is below, above the lease.
GATE_PR_BASE=""
#: The same base, resolved to a full commit sha once, so every later reader —
#: the banner, the derivation's fork point — looks at the object git actually
#: resolved rather than re-resolving a string that could move underneath it.
GATE_PR_BASE_SHA=""
#: Set by `--census`. A MODE, and the narrowest one in this file: it runs the
#: instrument census and nothing else — no lease, no lock, no pytest slot, no
#: leg banner — and exits with the census's own status. See THE `--census` MODE
#: below.
GATE_CENSUS=""
#: Set by `--list-legs`. A MODE, and the only one that runs no leg at all: it
#: prints the unit table and exits. See THE UNIT TABLE, AND `--list-legs` below.
GATE_LIST_LEGS=""
#: Set by `--leg <unit>`. A MODE, and the only one that runs a SUBSET of the
#: full gate's legs. It normalises to `MODE="--leg"` rather than to the full
#: mode, which is what keeps a unit run out of the sanction block, out of the
#: machine lease and out of every ledger: see RUNNING ONE UNIT below.
GATE_LEG_UNIT=""
#: The unit's members, comma-wrapped (`,a,b,`) for a substring membership test.
#: EMPTY ON EVERY OTHER PATH, and that emptiness is the switch: `leg` and
#: `gate_run_body` filter on it and on nothing else, so one variable decides
#: both what is announced and what is run, and there is no second reader to
#: fall out of step with the first.
GATE_LEG_UNIT_LEGS=""
#: Set by `--shard k/N`. Legal only on a unit the listing calls `N-capable`;
#: 1-based, because the listing's grammar is. Whatever the unit's body wants is
#: derived from these two and never re-parsed.
GATE_SHARD=""
GATE_SHARD_K=""
GATE_SHARD_N=""
#: Set the moment `--shard` is SEEN, whatever followed it. It is a separate
#: variable from the value on purpose: `--shard` with nothing after it leaves
#: the value empty, and a run that read only the value would take the flag as
#: absent and run the WHOLE unit — a mistyped modifier answered with a bigger
#: run, which is the same class of defect as a mistyped flag answered with a
#: smaller one.
GATE_SHARD_GIVEN=""
#: Set by `--passes N` under `--leg`. The number of WHOLE PASSES the suite leg
#: runs: `2` (the default, and the only thing that ever ran before ADR gate-1's
#: amendment) or `1`.
#: One pass is legal ONLY on a shard, because the second pass is this unit's
#: idempotency belt and a run that drops it has to say where the belt went —
#: under `pm_push.sh --bank --on-boxes N` it is the acceptance box's whole-suite
#: two-pass run, composed into the verdict row's `leak-proof=` field. A whole
#: unit asking for one pass is asking to drop the belt and name no replacement,
#: which is a refusal (see the `--passes` block under RUNNING ONE UNIT).
GATE_PASSES=""
#: Set the moment `--passes` is SEEN, whatever followed it — `GATE_SHARD_GIVEN`'s
#: argument exactly: `--passes` with nothing after it leaves the value empty, and
#: a run that read only the value would take the flag as absent and run TWO
#: passes. That is the mistyped-modifier hazard in its bigger-run direction, and
#: it is answered here rather than discovered in a bank's wall clock.
GATE_PASSES_GIVEN=""
#: THE TRANSCRIPT'S OWN WORDS FOR HOW MANY PASSES ARE ABOUT TO RUN, and they
#: are variables because a run that prints "both passes" and then prints "pass
#: 2 NOT run" has told a reader two different things about itself — the shard
#: log a bank composes is read by somebody who was not watching, and a line
#: that asserts two passes over one is the same class of defect as a row
#: vouching for more than ran. ONE DECISION SITE flips both (in the `--passes`
#: block under RUNNING ONE UNIT); there are two strings only because English
#: has two verbs here, and the DEFAULT values are byte-identical to what every
#: line printed before the flag existed, which is what keeps a `--passes 2` or
#: absent transcript unchanged.
GATE_PASSES_RUN="both passes run"
GATE_PASSES_CARRY="both passes carry"
#: And the suite leg's own DECLARATION, for the same reason: `leg` prints it
#: verbatim, and "twice" is a claim. Nothing reads this string — `gate_list_legs`,
#: `gate_announced_full_legs`, `gate_unpaired_legs` and the unit census all read
#: the leg NAME (`$2` of a column-zero `leg <name> …`), which is why it is free
#: to say what this run is actually doing.
GATE_PASSES_LEG_TEXT="pytest (twice, both passes under ONE seed and ONE OF THIS MACHINE'S PYTEST SLOTS, nothing in between — the second run proves the first left nothing behind)"
#: Set by `--store-durations`. A MEASUREMENT, not a verdict: it rewrites the
#: durations file the split balances by and vouches for nothing.
GATE_STORE_DURATIONS=""
#: Set by `--store-durations` at the FULL mode, where `--leg` is absent. A
#: SECOND SENSE OF ONE FLAG, and the two are told apart by whether a unit was
#: named, which is stated rather than left to be discovered:
#:
#:   --leg pytest-x2 --store-durations   times the SUITE, rewrites
#:                                       scripts/pytest_durations.json, and
#:                                       stops after pass 1 (the split's input).
#:   --store-durations                   runs the WHOLE gate and rewrites
#:                                       scripts/gate_member_durations.json —
#:                                       every leg's and every drive's seconds,
#:                                       which is what the --loop always-on set
#:                                       is derived from.
#:
#: Both are MEASUREMENTS and neither banks: a tracked file written during a run
#: moves the tree that run would have vouched for, which is exactly why this is
#: a separate run rather than a side effect of a bank.
GATE_STORE_MEMBERS=""
#: Set by `--loop --mine`. A MODIFIER of `--loop`, never a mode of its own: the
#: legs, their order and their exit statuses are `--loop`'s, and what it changes
#: is the SCOPE the pytest leg is pointed at — the touched apps in full, the
#: `depends_on` closure NOT walked. See THE `--mine` MODIFIER below.
GATE_MINE=""
case "$MODE" in
"" | --fast | --loop) ;;
--bank)
    GATE_BANK=1
    MODE=""
    ;;
--pr)
    GATE_PR=1
    MODE=""
    ;;
--store-durations)
    # A MEASUREMENT ASKED FOR AT THE FRONT, AND IT NORMALISES EXACTLY AS
    # `--bank` AND `--pr` DO: `MODE=""`, so every line after this point runs
    # the identical full gate and the member clock is written at the end.
    #
    # WHY IT IS HERE AT ALL, measured 2026-09-21 in the v2.1.1 fold. The header
    # documents `./scripts/check.sh --store-durations`, the unknown-argument
    # refusal lists it, and the always-on `--loop` set derives from the file it
    # writes — and typed exactly as documented it arrived as `$MODE`, matched
    # no arm, and exited 2 with `unknown argument '--store-durations'`. The
    # only way to reach the second `case` below was to put something in front
    # of it, which no reader of this file would ever guess. A flag that is
    # documented, refused-by-name and unreachable is worse than one that does
    # not exist: the measurement everything downstream reads could not be taken.
    #
    # THE OTHER TWO SITES ARE UNCHANGED AND BOTH STILL BIND. Under `--leg` the
    # flag is the SUITE's own timing flag and is consumed in the modifier loop
    # below; at `--fast` or `--loop` it is exit 2 in the second `case` below,
    # because a measurement of a SUBSET written into the file the whole set
    # derives from is the mistyped-flag hazard wearing a measuring tape.
    GATE_STORE_MEMBERS=1
    MODE=""
    ;;
--census)
    GATE_CENSUS=1
    ;;
--list-legs)
    GATE_LIST_LEGS=1
    ;;
--leg)
    # The unit is the NEXT word and it is taken here rather than in the modifier
    # loop below, because `--leg` without one must refuse as `--leg`, naming the
    # listing — not as an unexpected extra argument.
    GATE_LEG_UNIT=${2:-}
    MODE="--leg"
    shift || true
    ;;
*)
    # Not a usage nit: a mistyped flag falling through to a silently different
    # run is enforcement misfiring, and that is an exit 2.
    echo "!! unknown argument '$MODE': check.sh takes nothing, --fast, --loop, --loop --mine, --census, --list-legs, --leg <unit>, --store-durations, --bank, or --pr --base <sha>" >&2
    exit 2
    ;;
esac
shift || true
# --- the modifiers a UNIT run takes, consumed before --base and --mine -------
# ONLY UNDER `--leg`, AND THAT GUARD IS THE POINT. A `--shard` typed at any
# other mode falls through to the extra-arguments refusal below (exit 2) rather
# than being consumed by a mode that would ignore it — a flag silently accepted
# by a run that does not honour it is the mistyped-flag hazard wearing a
# different hat. Under a unit run they may arrive in any order, and `--pr` is
# one of them: on its own it is the mode, under a unit it is a modifier of one.
if [ "$MODE" = "--leg" ]; then
    while [ "$#" -gt 0 ]; do
        case "${1:-}" in
        --shard)
            GATE_SHARD_GIVEN=1
            GATE_SHARD=${2:-}
            shift || true
            shift || true
            ;;
        --shard=*)
            GATE_SHARD_GIVEN=1
            GATE_SHARD=${1#--shard=}
            shift || true
            ;;
        --passes)
            GATE_PASSES_GIVEN=1
            GATE_PASSES=${2:-}
            shift || true
            shift || true
            ;;
        --passes=*)
            GATE_PASSES_GIVEN=1
            GATE_PASSES=${1#--passes=}
            shift || true
            ;;
        --store-durations)
            GATE_STORE_DURATIONS=1
            shift || true
            ;;
        --pr)
            GATE_PR=1
            shift || true
            ;;
        *) break ;;
        esac
    done
fi
if [ -n "$GATE_PR" ]; then
    case "${1:-}" in
    --base)
        GATE_PR_BASE=${2:-}
        shift || true
        shift || true
        ;;
    --base=*)
        GATE_PR_BASE=${1#--base=}
        shift || true
        ;;
    esac
fi
# AT THE TOP LEVEL, AND THE COLUMN IS LOAD-BEARING. `scripts/tests/test_loop_scope.sh`
# arms its `--mine` collection by reading `^--mine)` out of this file — the flag
# existing is the case's own precondition — so this arm stays a top-level `case`
# rather than one nested inside an `if`, where shfmt house style would indent it
# out of that reader's sight.
case "${1:-}" in
--store-durations)
    # AT THE FULL MODE AND NOWHERE ELSE. Under `--leg` it was already consumed
    # above with its other sense; at `--fast` or `--loop` it would be a
    # measurement of a subset written into a file the whole gate is derived
    # from, which is the mistyped-flag hazard wearing a measuring tape.
    #
    # THIS ARM IS THE SECOND HALF OF ONE FLAG, not the only one: typed FIRST
    # (`./scripts/check.sh --store-durations`, the documented form) the mode
    # `case` above normalises it to `MODE=""` and sets the same variable. This
    # arm is what still catches `--fast --store-durations` and
    # `--loop --store-durations`, which is the whole reason it stays.
    if [ -n "$MODE" ]; then
        echo "!! --store-durations without --leg measures the WHOLE gate, so it belongs to" >&2
        echo "   the full mode: ./scripts/check.sh --store-durations" >&2
        echo "   Under a unit it is the suite's own timing flag: ./scripts/check.sh --leg pytest-x2 --store-durations" >&2
        exit 2
    fi
    GATE_STORE_MEMBERS=1
    shift || true
    ;;
--mine)
    if [ "$MODE" != "--loop" ]; then
        # --mine is a narrowing of the per-rung gate and of nothing else. On the
        # full gate it would be a narrowed run wearing a full verdict, which is
        # the one thing the ledger must never be handed.
        echo "!! --mine narrows --loop and nothing else: ./scripts/check.sh --loop --mine" >&2
        exit 2
    fi
    GATE_MINE=1
    shift || true
    ;;
esac
if [ "$#" -gt 0 ]; then
    echo "!! unexpected extra arguments: $*" >&2
    exit 2
fi

# --- THE INSTRUMENT CENSUS, AS A FUNCTION AND AS A MODE ----------------------
#
# ONE BODY, TWO CALLERS, AND THAT IS THE WHOLE DESIGN. The `goalpost-census` leg
# in `--fast` calls this function; `--census` calls the same function and exits
# with its status. A second copy of the census — a separate script, a second
# invocation with its own refusal text — is two answers to "does every
# instrument own a row", and the day they disagree neither is the census.
#
# WHY THE MODE EXISTS AT ALL. The census is the one `--fast` leg a FINISHING
# builder needs on its own: it is the leg that fails when a rung added an
# instrument and has not yet written its row, and the fix is a paragraph in
# `docs/product/instruments.md`. Asking for that answer used to mean running
# `--fast` — every other leg with it, a pre-commit's worth of wall clock — to
# read one line. `--census` is that line.
#
# NO LEASE, NO LOCK, NO SLOT, NO LEG BANNER. It reads `git ls-files`, some mode
# bits and one markdown table: no database, no network, no Django import,
# nothing another gate could be holding. A mode that took the machine's one
# exclusive lease to read a table would cost every queued gate the wait, and the
# reason to reach for it is that it is cheap.
# THE SEAM, SOURCED HERE TOO, AND THE REASON IS THE MODE BELOW. `--census`
# exits long before the library block further down, and the census needs
# `checkout_python` from the seam: a mode that reached for an unbound function
# would die with bash's own `command not found` and no finding at all. The
# source is guarded and the later one is unconditional on purpose — re-sourcing
# is declared harmless in that file's own header, and the block below is where a
# reader looks for the seam.
[ -n "${GATE_REFUSE_SOURCED:-}" ] || . scripts/gate_refuse.sh

instrument_census() {
    local rc py
    # THE CHECKOUT'S OWN INTERPRETER, NEVER `python3` OFF PATH. The census is a
    # file this repository ships, written against the 3.12 the venv holds; a
    # verifier box's system `python3` is 3.9 and is first on PATH there.
    # MEASURED with a `python3` first on PATH that answers 3.9 and refuses the
    # file: this mode exited 2 saying `the instrument census and the tree
    # disagree` — a finding about the census's agreement with the tree, over an
    # interpreter that never read either. The leg two hundred lines down is
    # where the same class was paid for real.
    py=$(checkout_python) || {
        echo "!! the instrument census COULD NOT BE TAKEN: this checkout has no" >&2
        echo "   .venv/bin/python, and scripts/goalpost_scan.py is a file this repository" >&2
        echo "   pins at the version that venv holds. Run ./scripts/setup.sh (or" >&2
        echo "   \`uv sync\`) first. Nothing was censused, and a census that did not" >&2
        echo "   answer is never an empty one." >&2
        return 2
    }
    set +e
    "$py" scripts/goalpost_scan.py --census
    rc=$?
    set -e
    [ "$rc" = "0" ] && return 0
    echo "!! the instrument census and the tree disagree." >&2
    echo "   Every executable git knows about outside apps/, config/, .venv/ and .git/" >&2
    echo "   owes a row in docs/product/instruments.md answering the three honesty" >&2
    echo "   questions with a file:line each. A new instrument that ships uncensused is" >&2
    echo "   a doc that went stale with nobody able to see it (ADR gate-3)." >&2
    return 2
}

if [ -n "$GATE_CENSUS" ]; then
    # EXITS WITH THE CENSUS'S OWN STATUS. There is no exit 1 here for the same
    # reason the leg has none: a tree and its census disagreeing is not a lesser
    # finding, it is the doc no longer describing the tree.
    set +e
    instrument_census
    CENSUS_MODE_RC=$?
    set -e
    exit "$CENSUS_MODE_RC"
fi

# --- THE `--mine` MODIFIER, AND WHAT A `--mine` GREEN IS WORTH ----------------
#
# `--loop --mine` is the per-rung gate with ONE narrowing: the pytest leg's
# scope is the rung's OWN apps, in full, and the reverse-transitive `depends_on`
# closure is NOT walked. Every other leg runs unchanged.
#
# IT IS HONEST ONLY BECAUSE THE ORDINARY `--loop` IS ALREADY CLOSURE-KEYED. The
# ordinary run narrows to own + closure and banks a verdict keyed on that scope;
# `--mine` is one notch narrower than a narrowing that already exists, and it
# says so in its own banner rather than leaving the reader to infer it. A
# regression this run cannot see is a regression in a DEPENDANT of the touched
# app, and the ordinary `--loop` — the one the builder runs at its last
# boundary, before the fold — is where it surfaces.
#
# AND IT NEVER BANKS. The loop ledger's whole contract is that a banked row
# vouches for a tree at a scope; a row banked by a run that skipped the closure
# would be reused by a later ordinary `--loop` on the same bytes, which would
# then never walk the closure either. So `--mine` neither consults nor records:
# it is a builder's fast look, not a verdict, and the run prints that on both
# ends. The consult and the bank are guarded on `$GATE_MINE` below.
#
# THE ALWAYS-ON SET IS OUTSIDE THE NARROWING, here as at every other scope: the
# cross-app tripwires run under `--mine` exactly as they run under an empty
# scope, because a set that narrows with the scope is a set that disappears
# precisely when the scope is at its smallest.

# --- THE `--pr` VARIANT, AND WHAT IT MAY NOT DO ------------------------------
#
# `--pr --base <sha>` is the FULL GATE with one thing changed: the two pytest
# passes are pointed at the scope of `<sha>...HEAD` instead of at the whole
# suite. Every other leg runs unchanged, in the same order, under the same
# exclusive lease and the same pytest slot, and the same sanction rules apply —
# a narrowed full gate is still the most expensive thing on this machine.
#
# WHAT IT IS FOR: grading a whole PROPOSED CHANGE, where the question is "does
# everything this change can reach still pass", not "is the rung in progress
# still green". That is why the organ tier is NOT applied — see
# `loop_scope__pytest_args` in scripts/loop_tier.sh, which is where that
# decision is written down.
#
# EXIT 2, NEVER A SMALLER RUN. Every way the impact map can fail to be
# computable is a refusal here and not a narrower selection: a `--pr` that
# quietly graded less than it claimed would be the exact failure the whole
# scope machinery exists to make impossible. The four this block answers:
#
#   1. no `--base` at all — there is no diff to take;
#   2. a `--base` git cannot resolve;
#   3. a `--base` that is not an ancestor of HEAD — `<sha>...HEAD` would be
#      taken from a merge-base nobody named, over commits the base already has;
#   4. a dirty tree — the changed set is derived from git, and an uncommitted
#      file is in neither half of `<sha>...HEAD`. (The scope derivation DOES
#      read the working tree, so a dirty tree would not be invisible — it would
#      be graded under a banner claiming a commit range. One or the other.)
#
# The two the RUN answers later, for the same reason and with the same status:
# an app label the declarations cannot account for, and an always-on floor that
# does not meet (scripts/loop_tier.sh, apps/conftest.py).
#
# WHERE IT SITS. Above the sanction block, and therefore above the lease and the
# slot: a run that was never going to be legal must not queue for one first. The
# drive asserts exactly that — no `gate lease`, no `pytest slot` line in any of
# the four.
if [ -n "$GATE_PR" ]; then
    if [ -z "$GATE_PR_BASE" ]; then
        echo "!! --pr needs --base <sha>: the commit the proposed change forks from." >&2
        echo "   Without it there is no diff to take, and this gate does not guess one:" >&2
        echo "       ./scripts/check.sh --pr --base <sha>" >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi
    GATE_PR_BASE_SHA=$(git rev-parse -q --verify "${GATE_PR_BASE}^{commit}" 2>/dev/null || true)
    if [ -z "$GATE_PR_BASE_SHA" ]; then
        echo "!! --pr --base '${GATE_PR_BASE}': git cannot resolve that to a commit here." >&2
        echo "   An impact map cannot be computed from a base this checkout does not have," >&2
        echo "   and a base it cannot see is never a reason to run less." >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi
    if ! git merge-base --is-ancestor "$GATE_PR_BASE_SHA" HEAD >/dev/null 2>&1; then
        echo "!! --pr --base '${GATE_PR_BASE}' is NOT an ancestor of HEAD." >&2
        echo "   base: $GATE_PR_BASE_SHA" >&2
        echo "   HEAD: $(git rev-parse HEAD 2>/dev/null || echo '(unreadable)')" >&2
        echo "   The changed set is <base>...HEAD, which from a non-ancestor is taken at a" >&2
        echo "   merge-base nobody named — a smaller and different set than the one the" >&2
        echo "   caller asked about. Rebase, or name the base this branch actually forks" >&2
        echo "   from." >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi
    if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
        echo "!! --pr refuses a DIRTY TREE." >&2
        echo "   The proposed change is <base>...HEAD — commits. An uncommitted file is in" >&2
        echo "   neither half of it, so it would be graded by a run whose banner names a" >&2
        echo "   commit range it is not in. Commit it, or stash it, and ask again." >&2
        git status --porcelain 2>/dev/null | sed 's/^/     /' >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi
fi

# --- THE FULL GATE IS SANCTIONED --------------------------------------------
# WHAT THIS REFUSES, and the measurement behind it. The doctrine is one full
# gate per push. The ledger, once it started recording WHO ASKED, said
# otherwise: hundreds of full runs in days, of which a countable few were the
# push wall and the rest were somebody deciding, in the moment and from
# anywhere, that a full gate was the right next move. A full gate is the most
# expensive thing on this machine — two whole-suite passes, a real Meili, a real
# MinIO, a real Temporal — and while one runs, every OTHER full gate on the box
# waits for the lease. An unaccountable one does not just cost its own minutes;
# it spends everybody else's.
#
# So a full run now needs a REASON THAT SURVIVES THE RUN, and there are exactly
# three ways to have one. The list is closed on purpose: a valve anybody can
# open by inference is a valve that is always open.
#
#   1. THE PUSH WALL. `DJB_GATE_CALLER=push-wall`, which only
#      `scripts/githooks/pre-push` sets. The doctrine's own case, and the one
#      that must never need a human to type anything.
#   2. `--bank` FROM THE RITUAL CHECKOUT. The PM banking a verdict for a tree
#      that is about to be pushed. Legal from the checkout family's PRIMARY
#      worktree or from `pm-push`, and nowhere else — because a bank is a claim
#      about the tree that is going out, and a linked rung worktree is by
#      construction not that tree.
#
#      THE TEST IS MECHANICAL, NEVER A CWD SHAPE. `git rev-parse --git-dir` is
#      `.git` in the primary checkout and `.git/worktrees/<name>` in a linked
#      one, while `--git-common-dir` is the one shared `.git` for the whole
#      family. Equal means primary. Inferring from the PATH ("does it contain
#      /worktrees/?") is the kind of guess that is wrong the first time somebody
#      clones into a directory with that name, and this repository has been
#      bitten by an inherited GIT_DIR once already
#      (`scripts/githooks/pre-push`'s header).
#   3. A TYPED SANCTION. `DJB_GATE_SANCTION="<rung-id>: <reason>"` — the escape
#      valve, and the whole design rests on it being CHEAP and EXPLICIT. A
#      builder whose rung touches `quality/**` or the dependencies must run the
#      full gate (rung-execution §3 names both), and that must stay a one-line
#      thing to do. What it must not stay is INVISIBLE: the sanction is printed
#      in the gate's header and written into the verdict row, so the population
#      of hand-run fulls is readable afterwards instead of inferred.
#
# WHAT IS NOT ENFORCED, declared rather than implied: the QUALITY of the reason.
# `DJB_GATE_SANCTION="X-1: because"` passes the shape check. This guard makes
# the reason exist and makes it durable; whether it was a good one is a PM's
# read of the ledger, which is a judgement no script makes.
#
# CI IS EXEMPT, the same explicit exemption the pipe guard above carries and for
# a related reason: a runner has no ritual checkout, no hook environment and
# nobody to type a sanction, and every CI run is by construction a full run
# somebody asked for in a workflow file. THE RESIDUAL IS THE PIPE GUARD'S,
# declared and accepted: an agent exporting `CI=1` — or `DJB_GATE_CALLER=push-wall`
# — to get past this is deliberate circumvention, it is visible in the command
# line, and this guard stops casual unaccountable fulls rather than sabotage.
#
# WHERE IT SITS, and that is load-bearing: ABOVE the lease and the slot, so a
# refused run takes neither. A gate that queued for an hour and then told the
# caller it was not allowed to run would be an expensive way to learn about a
# missing environment variable.
#
#: What sanctioned this run, in one phrase, for the header and the verdict row.
#: Empty on every `--fast`/`--loop` path — those are never sanctioned because
#: they are never refused.
GATE_SANCTIONED_BY=""
# `-z "$MODE"` rather than `= ""`: the drive reads `check.sh` as text and pins
# the FULL-mode branch by the literal `if [ "$MODE" = "" ]; then`, which must go
# on naming exactly one line — the one that takes the lease.
if [ -z "$MODE" ]; then
    # The sanction's SHAPE is checked first and unconditionally: `<id>: <reason>`
    # — something before the first colon, a colon, a space, then something. A
    # value that is set but shapeless is a broken invocation whoever set it, and
    # letting it fall through to the generic refusal below would hide the typo
    # behind a different sentence.
    if [ -n "${DJB_GATE_SANCTION:-}" ] && ! [[ ${DJB_GATE_SANCTION} =~ ^[^:]+:\ .+$ ]]; then
        echo "!! DJB_GATE_SANCTION is set but is not a sanction." >&2
        echo "   got:  ${DJB_GATE_SANCTION}" >&2
        echo "   want: DJB_GATE_SANCTION=\"<rung-id>: <reason>\"" >&2
        echo "         e.g. DJB_GATE_SANCTION=\"gate-rung: quality/** rung — the canary self-test is the point\"" >&2
        echo "   A sanction that does not name who is asking and why is not a reason, and" >&2
        echo "   a full gate is not run on one. Nothing was judged." >&2
        exit 2
    fi

    if [ -n "${CI:-}" ]; then
        GATE_SANCTIONED_BY="CI (exempt, as at the pipe guard)"
    elif [ "${DJB_GATE_CALLER:-}" = "push-wall" ]; then
        GATE_SANCTIONED_BY="the push wall (DJB_GATE_CALLER=push-wall)"
    elif [ -n "${DJB_GATE_SANCTION:-}" ]; then
        GATE_SANCTIONED_BY="DJB_GATE_SANCTION=${DJB_GATE_SANCTION}"
    elif [ -n "$GATE_BANK" ]; then
        GATE_GIT_DIR=$(git rev-parse --git-dir 2>/dev/null || true)
        GATE_GIT_COMMON=$(git rev-parse --git-common-dir 2>/dev/null || true)
        GATE_TOPLEVEL=$(git rev-parse --show-toplevel 2>/dev/null || true)
        if [ -z "$GATE_GIT_DIR" ] || [ -z "$GATE_GIT_COMMON" ]; then
            echo "!! --bank could not ask git which checkout this is." >&2
            echo "   The flag is legal from the primary checkout or from pm-push and nowhere" >&2
            echo "   else, and a test that could not run has cleared nothing. Nothing was judged." >&2
            exit 2
        elif [ "$GATE_GIT_DIR" -ef "$GATE_GIT_COMMON" ]; then
            GATE_SANCTIONED_BY="--bank from the PRIMARY checkout ($GATE_TOPLEVEL)"
        elif [ "$(basename "${GATE_TOPLEVEL:-}")" = "${DJB_PUSH_WORKTREE:-pm-push}" ] &&
            ! git symbolic-ref -q HEAD >/dev/null 2>&1; then
            # THE SECOND HALF IS THE MECHANICAL ONE, and it is here because the
            # first half alone is INFERENCE FROM A NAME: any linked worktree
            # somebody called `pm-push` was accepted, including a rung worktree.
            # The primary-checkout arm above is mechanical (git-dir against
            # git-common-dir, an identity git computes); this arm had nothing of
            # the kind, and a basename is the class of test that is wrong the
            # first time somebody names a directory after the thing it is not.
            #
            # DETACHED HEAD IS THE PROPERTY, and it is a property of the real
            # pm-push worktree rather than a convention about it: `pm_push.sh`
            # pins it with `git checkout --detach` on every push, and the
            # worktree its own refusal tells you to create is created with
            # `git worktree add --detach`. A RUNG WORKTREE IS ON A BRANCH — that
            # is what a rung worktree is — so `symbolic-ref HEAD` succeeds there
            # and fails here, and the two are now told apart by what git says
            # rather than by what the directory is called.
            #
            # DECLARED RESIDUAL, and it is smaller than the one it replaces: a
            # DETACHED linked worktree that somebody has also named `pm-push`
            # still passes. That is a checkout in the pm-push posture wearing
            # the pm-push name, which is as close to being pm-push as anything
            # outside `git worktree list` can get; the identity of pm-push is
            # its name in that list, and `pm_push.sh` itself finds it the same
            # way (`scripts/pm_push.sh`, "Where pm-push is, asked rather than
            # assumed"). Both files would have to change together to make the
            # name stop being the identity, and nothing here needs that.
            GATE_SANCTIONED_BY="--bank from the ${DJB_PUSH_WORKTREE:-pm-push} worktree, detached ($GATE_TOPLEVEL)"
        else
            echo "!! --bank from a LINKED worktree: ${GATE_TOPLEVEL:-$PWD}" >&2
            echo "   git-dir:        $GATE_GIT_DIR" >&2
            echo "   git-common-dir: $GATE_GIT_COMMON" >&2
            echo "   HEAD:           $(git symbolic-ref -q HEAD 2>/dev/null || echo '(detached)')" >&2
            echo "   They differ, so this is not the primary checkout — and it is not the" >&2
            echo "   '${DJB_PUSH_WORKTREE:-pm-push}' worktree either, which is DETACHED (pm_push.sh pins it that way on" >&2
            echo "   every push) and named that. A worktree sitting on a branch is a rung" >&2
            echo "   worktree whatever its directory is called." >&2
            echo "   A bank is a claim about the tree that is about to be" >&2
            echo "   pushed; a rung worktree is by construction not that tree." >&2
            echo "   If you MEANT to run the full gate here — a quality/** or dependency rung," >&2
            echo "   where it uniquely binds — say why:" >&2
            echo "       DJB_GATE_SANCTION=\"<rung-id>: <reason>\" ./scripts/check.sh" >&2
            echo "   Nothing was judged." >&2
            exit 2
        fi
    else
        echo "!! REFUSING an unsanctioned FULL gate." >&2
        echo "   A full run is the most expensive thing on this machine — two whole-suite" >&2
        echo "   passes, a real Meilisearch, MinIO and Temporal — and every other full gate" >&2
        echo "   on the box waits behind it. So it needs a reason that outlives the run." >&2
        echo "   ONE of these, and they are the whole list:" >&2
        echo "     * the pre-push hook (it sets DJB_GATE_CALLER=push-wall for itself)" >&2
        echo "     * ./scripts/check.sh --bank   from the primary checkout or pm-push" >&2
        echo "     * DJB_GATE_SANCTION=\"<rung-id>: <reason>\" ./scripts/check.sh" >&2
        echo "   The per-rung gate is ./scripts/check.sh --loop and is untouched by this." >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi

    # `--bank` says pm-bank unless the caller has already said something else.
    # The ritual naming itself is the point of the flag: three of this ledger's
    # banked verdicts say `caller=unstated` because nobody remembered to export
    # anything, and a population with a hole in it is not a population.
    if [ -n "$GATE_BANK" ] && [ -z "${DJB_GATE_CALLER:-}" ]; then
        DJB_GATE_CALLER=pm-bank
        export DJB_GATE_CALLER
    fi
fi

# >>> loop-here >>>
# --- THE PER-RUNG GATE RUNS ON A BOX, AND SAYS WHY WHEN IT DOES NOT ---------
#
# THE MEASUREMENT. This Mac runs the whole loop: every builder's `--loop`, the
# verifier's consult and the bank, all on the same ten cores. At five lanes it
# sits at load 40-60, and the arithmetic is not subtle — a member measured at
# 3 s on a quiet box took 83 s here on a busy one, and a suite that costs four
# minutes alone costs a quarter of an hour under contention. The boxes exist
# and were built for exactly this; what was missing was anything that made
# using them the default rather than the thing a builder remembers.
#
# SO THE DEFAULT IS INVERTED, with the same shape the full gate's sanction
# already uses (THE FULL GATE IS SANCTIONED, above): a `--loop` on a machine
# that is not a verifier box REFUSES and prints the recipe, unless somebody
# types a reason that outlives the run. The valve is CHEAP and EXPLICIT on
# purpose — a box is not always the right answer (no AWS credentials, a network
# that is down, a rung whose whole point is what this laptop does) and none of
# those should cost a builder more than one line. What the valve must not be is
# INVISIBLE: the reason is printed in this run's banner and printed again
# beside the banked verdict, so the population of loops that ran here is
# readable afterwards rather than inferred.
#
# A BOX IS TOLD BY A MARKER THE IMAGE CARRIES, never by an environment variable
# and never by a hostname. `deploy/verifier/user-data.yaml.in` installs
# `/run/verifier` on every box at first boot (and writes `boot-at` and
# `last-activity` into it, which the idle reaper reads), so a box has it before
# anything of ours runs there and a laptop never does. `/etc/djb/image-id` is
# the second marker, named here so an image that stops creating a runtime
# directory has somewhere to say what it is.
#
# WHAT IS UNTOUCHED, stated rather than implied: `--fast` (the pre-commit hook,
# which must stay a local thing that costs seconds) and `--census`. And the
# VERIFIER'S CLONE is untouched by construction rather than by exemption — the
# verifier's one consult runs on a box, which is where the wall came from
# (HOTFIX-BOXVOUCH), so the marker is already there.
#
# THE RESIDUAL IS THE SANCTION VALVE'S, declared and accepted: `mkdir
# /run/verifier` gets past this, exactly as `CI=1` gets past the pipe guard and
# the full-gate sanction. This refuses the casual habit, not sabotage.
#
# WHERE IT SITS: above the lease, the lock, the slot AND the scope derivation,
# so a refused run takes nothing and costs a second.

#: The markers an image carries. Two, because an image that stops creating a
#: runtime directory needs somewhere else to say what it is; `-e` and not `-d`
#: so either a directory or a file answers. `DJB_GATE_BOX_MARKERS` exists for
#: exactly one reason — neither marker can be planted on a laptop without root,
#: so the ONE state this guard has that nobody can otherwise reach is "on a
#: box", and a guard whose permitting branch has never been driven is a guard
#: that may be unable to permit. It is read here and nowhere else.
GATE_BOX_MARKERS="${DJB_GATE_BOX_MARKERS:-/run/verifier /etc/djb/image-id}"
#: Which marker answered, for the banner.
GATE_BOX_MARKER=""
gate_on_verifier_box() {
    local m
    GATE_BOX_MARKER=""
    for m in $GATE_BOX_MARKERS; do
        if [ -e "$m" ]; then
            GATE_BOX_MARKER=$m
            return 0
        fi
    done
    return 1
}

#: What let this `--loop` run where it is running, in one phrase, for the
#: banner and for the line beside the banked verdict. Empty on every other
#: mode — they are never refused, so they are never permitted either.
LOOP_HERE_BECAUSE=""
if [ "$MODE" = "--loop" ]; then
    # The valve's SHAPE is checked first and unconditionally — `<who>: <why>`,
    # the sanction's own grammar — so a typo is a broken invocation rather than
    # a silent fall-through to the generic refusal below wearing a different
    # sentence.
    if [ -n "${DJB_LOOP_HERE:-}" ] && ! [[ ${DJB_LOOP_HERE} =~ ^[^:]+:\ .+$ ]]; then
        echo "!! DJB_LOOP_HERE is set but is not a reason." >&2
        echo "   got:  ${DJB_LOOP_HERE}" >&2
        echo "   want: DJB_LOOP_HERE=\"<rung-id>: <reason>\"" >&2
        echo "         e.g. DJB_LOOP_HERE=\"x-1: no AWS credentials in this session\"" >&2
        echo "   A valve that does not name who is asking and why is not a reason." >&2
        echo "   Nothing was judged." >&2
        exit 2
    fi
    if gate_on_verifier_box; then
        LOOP_HERE_BECAUSE="a verifier box (${GATE_BOX_MARKER})"
    elif [ -n "${CI:-}" ]; then
        LOOP_HERE_BECAUSE="CI (exempt, as at the pipe guard and the full-gate sanction)"
    elif [ -n "${DJB_LOOP_HERE:-}" ]; then
        LOOP_HERE_BECAUSE="DJB_LOOP_HERE=${DJB_LOOP_HERE}"
    else
        echo "!! REFUSING a --loop on a machine that is not a verifier box." >&2
        echo "   The per-rung gate is the loop's highest-volume run and this box carries" >&2
        echo "   every one of them at once. A member measured at 3 s on a quiet machine" >&2
        echo "   took 83 s here under five lanes; the boxes were built for this." >&2
        echo "   THE RECIPE, from this worktree, each command's output to its own file:" >&2
        echo "       ./scripts/verifier_box.sh up --for <rung>" >&2
        echo "       ./scripts/verifier_box.sh loop <id> --log loop-<rung>" >&2
        echo "       ./scripts/verifier_box.sh wait <id> loop-<rung>" >&2
        echo "       ./scripts/verifier_box.sh down <id>     # always, before you report" >&2
        echo "   IF IT HAS TO RUN HERE — no credentials, a network that is down, a rung" >&2
        echo "   about this laptop — say who and why:" >&2
        echo "       DJB_LOOP_HERE=\"<rung-id>: <reason>\" ./scripts/check.sh --loop" >&2
        echo "   The reason prints in this run's banner and beside its banked verdict." >&2
        echo "   --fast (the pre-commit hook) and --census are untouched by this." >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi
fi
# <<< loop-here <<<

# --- the gate's own instruments must run where CI runs them ------------------
# GNU mktemp REFUSES a template with fewer than three X's; BSD/macOS mktemp
# accepts one with none. So `mktemp -t djb-pip-audit` is green on every laptop
# in this project and dead on the first Linux runner — which is exactly how CI
# run 32736092503 died at the supply-chain leg, one leg from home, on THIS
# FILE's own line. Fifteen sites across scripts/ and deploy/ carried the shape.
#
# THE CLASS GETS A MOMENT, NOT A MEMORY. This class had been closed twice
# already by enumerating its members, and it regrew both times, because a fix
# by enumeration protects the members it counted and nothing written after.
# The check is the fix that lasts: it runs in --fast, which is every commit,
# and it names the file:line here instead of leaving the tenth for a CI log.
#
# The portable form, valid on BOTH mktemps:
#     tmp=$(mktemp    "${TMPDIR:-/tmp}/djb-thing.XXXXXX")
#     dir=$(mktemp -d "${TMPDIR:-/tmp}/djb-thing.XXXXXX")
#
# EXIT 2, NOT 1: a scratch file an instrument cannot make is that instrument
# not running, and enforcement that cannot run outranks any pass. Reading zero
# shell files is the same 2 — this file is one of them, so a count of zero
# means the scan went blind, never that the tree is clean.
#
# WHAT IT DOES NOT COVER, declared: a template held in a variable
# (`mktemp "$SOMEVAR"` is flagged, since no literal X is visible — a variable
# that does carry them is a false positive worth the noise); a mktemp reached
# through a wrapper, an alias or `xargs`; anything outside scripts/ and
# deploy/; and the rest of the BSD-vs-GNU family (`sed -i`, `date -d`,
# `readlink -f`, `grep -P`, `stat -c`), about which it says nothing at all.
mktemp_selfline_files() {
    local f
    git ls-files -- scripts deploy 2>/dev/null | while IFS= read -r f; do
        [ -f "$f" ] || continue
        case "$f" in
        *.sh) printf '%s\n' "$f" ;;
        # `grep PATTERN >/dev/null` and never `| grep -q`. `-q` exits on the
        # first match, closing the pipe under the producer; a producer with more
        # than the 64KiB pipe buffer left to write dies of SIGPIPE (141) and
        # `set -o pipefail` reports the MATCH as a failure. `head -n 1` can
        # never reach that, so this is the class closed where it lives rather
        # than a bug repaired — the same edit as gate_ledger.sh's, made in the
        # same commit for the same reason. Flags are preserved: -E stays.
        *) head -n 1 "$f" 2>/dev/null | grep -E '^#!.*sh$|^#!.*sh[[:space:]]' >/dev/null && printf '%s\n' "$f" ;;
        esac
    done
}

mktemp_selfline() {
    local files hits
    files=$(mktemp_selfline_files)
    if [ -z "$files" ]; then
        echo "!! THE mktemp SELF-LINE COULD NOT LOOK — it found no shell file under" >&2
        echo "   scripts/ or deploy/. This file is one, so zero means the scan is blind," >&2
        echo "   not that the tree is clean." >&2
        return 2
    fi
    hits=$(printf '%s\n' "$files" | awk '
BEGIN { q = sprintf("%c", 39) }
{
    path = $0
    if (path == "") next
    n = 0
    while ((getline line < path) > 0) {
        n++
        probe = line
        sub(/^[ \t]+/, "", probe)
        if (probe ~ /^#/) continue
        rest = line
        while ((at = index(rest, "mktemp")) > 0) {
            before = substr(rest, 1, at - 1)
            rest = substr(rest, at + 6)
            if (substr(rest, 1, 1) ~ /[A-Za-z0-9_]/) continue
            sub(/[ \t]+$/, "", before)
            # A command, not prose: what precedes it is a substitution or a
            # shell operator, never a word ("builds its scratch under mktemp").
            if (before != "" && before !~ /[($`;&|{=]$/) continue
            args = rest
            sub(/[)|;&<>].*$/, "", args)
            gsub(/"/, "", args)
            gsub(q, "", args)
            tmpl = ""
            k = split(args, a, /[ \t]+/)
            for (i = 1; i <= k; i++) {
                if (a[i] == "") continue
                if (a[i] == "-t") { tmpl = a[i + 1]; i++; continue }
                if (a[i] == "-p" || a[i] == "--tmpdir") { i++; continue }
                if (substr(a[i], 1, 1) == "-") continue
                tmpl = a[i]
            }
            if (tmpl != "" && tmpl !~ /XXX/) print path ":" n
        }
    }
    close(path)
}')
    [ -z "$hits" ] && return 0
    echo "!! NON-PORTABLE mktemp TEMPLATE — GNU mktemp needs at least three X's and" >&2
    echo "   refuses these outright; BSD/macOS mktemp accepts them, which is why they" >&2
    echo "   read green here and kill the leg on the Linux runner:" >&2
    echo "$hits" >&2
    echo "   Write the template so BOTH mktemps accept it:" >&2
    echo '       tmp=$(mktemp    "${TMPDIR:-/tmp}/djb-thing.XXXXXX")' >&2
    echo '       dir=$(mktemp -d "${TMPDIR:-/tmp}/djb-thing.XXXXXX")' >&2
    return 2
}
set +e
mktemp_selfline
MKTEMP_SELFLINE_RC=$?
set -e
[ "$MKTEMP_SELFLINE_RC" = "0" ] || exit "$MKTEMP_SELFLINE_RC"

# THE REFUSAL SEAM, SOURCED FIRST. Every library below it records the first
# `!!` line of its refusals in `GATE_LAST_REFUSAL`, and every banner in this
# file that ends in `— see above.` prints that line as its second. See
# scripts/gate_refuse.sh for the whole argument, including why a callee run
# under `$(...)` cannot use the global and what its caller does instead.
. scripts/gate_refuse.sh
# The verdict ledger + run log. See scripts/gate_ledger.sh for the key, the
# three properties, and the trust class.
. scripts/gate_ledger.sh
# The machine-wide full-gate lease. Sourced for every mode so that
# `--fast`/`--loop` could name a holder if they ever needed to; NEITHER takes
# one, and the only call site that acquires is in the `MODE = ""` branch below.
. scripts/gate_lease.sh
# Per-worktree database name, for the pytest legs.
#
# `--list-legs` sources it with the pin note OFF: the listing's whole output is
# the unit table, and a `note: DATABASE_NAME pinned…` line on stderr landed in
# every reader that captures both streams as a unit row (db.sh, THE NOTE IS NOT
# PRINTED WHERE THE CALLER'S OUTPUT IS A TABLE). Set in this shell, not
# exported, and unset straight after, so no leg and no child inherits it.
# (Spelled as an OR-list and not as `if [ -n "$GATE_LIST_LEGS" ]; then`: that
# line is the listing ARM's landmark, which test_list_legs.sh locates by its
# first column-zero occurrence.)
[ -z "$GATE_LIST_LEGS" ] || DB_PIN_NOTE_OFF=1
. scripts/db.sh
unset DB_PIN_NOTE_OFF
# The --loop secret scan's changed-file derivation. See that leg.
. scripts/secrets_scan.sh
# The --loop pytest tier's own-app derivation, a mapping over the same
# changed-file set. Sourced after it, because it calls it.
. scripts/loop_tier.sh
# The publication bucket rules + the archaeology-census scan, shared with
# scripts/publish.sh so the two never carry two copies of "is this file SHIP"
# that agree today and drift tomorrow. The --loop `archaeology` leg below and
# the --loop `fe` leg's own-tree check both call into it.
. scripts/archaeology_lib.sh
# The four --fast census bodies that ask a closed question of a DOCUMENT rather
# than of the code: `adr-census` and `dangling-docs` (shared with
# scripts/publish.sh, whose release-time whole-artifact scan is the same two
# bodies over a different file set), plus `loop-names` and `ci-env`, which have
# no release-time half. Sourced rather than inlined so the drive can aim each
# body at a scratch tree — a drive cannot run a nested gate, the per-checkout
# lock refuses it, so a case that shelled out to the gate would go red for the
# lock and not for the property.
. scripts/docs_legs.sh
# The --loop `fe` leg: the tri-state (absent/untouched/full) over frontend/,
# proven by scripts/tests/test_fe_leg.sh's fixture worlds rather than by this
# tree's own current state (this template ships with no frontend/ at all).
. scripts/fe_gate.sh

# In run order. supply-chain moved ahead of pytest-x2; see the ordering note at
# that leg. `full-house-rules` was missing for a while: the leg ran on every
# full gate and the ledger line never said so, so every recorded verdict
# under-reported what green had meant.
#
# IT IS NO LONGER MAINTAINED BY HAND, AND THAT IS THE POINT OF THE CENSUS BELOW.
# This string names what a full run announces, and it had drifted by six names:
# `queue-index`, `archaeology`, `adr-census`, `dangling-docs`, `loop-names` and
# `ci-env` were announced on every full gate and recorded on no verdict row, so
# every banked verdict under-reported what green had meant — the identical
# defect `full-house-rules` used to carry, re-grown once per rung that added a
# leg. `--list-legs` derives the announced sequence from this file's own leg
# call sites and refuses (exit 2) when the two disagree, which is what stops the
# next one.
FULL_LEGS=ruff,mypy,import-linter,djb-checks,house-rules,migrations,goalpost-census,queue-index,db-pin,archaeology,adr-census,dangling-docs,loop-names,ci-env,deploy-check,fe,collectstatic,supply-chain,temporal-census,partition,pytest-x2,own-tree-census,selftest,full-house-rules
#: THE TEMPLATE'S OWN SET, UNDER ITS OWN NAME, because `FULL_LEGS` above GROWS.
#: A product's drawer (`scripts/local/legs/`, the local-legs block below)
#: appends one `local:<name>` per declared leg to `FULL_LEGS` at startup, so the
#: string a run announces is not always the string this file types. Everything
#: that means "the legs THIS FILE ships" — the collision check a product leg's
#: name is refused by — reads this one; everything that means "the legs THIS RUN
#: announces" reads `FULL_LEGS`.
FULL_LEGS_TEMPLATE="$FULL_LEGS"
MEASURED_START=""
T_MODE_START=$(date +%s)

# --- THE UNIT TABLE, AND `--list-legs` ---------------------------------------
#
# A UNIT IS WHAT ONE RUNNER CAN BE HANDED. The legs of this gate are not
# independent of each other in cost or in what they assume: eleven of them need
# nothing but the checkout, one leaves the machine, one owns a whole pytest
# suite twice over, and one runs every shell refusal drive in the tree. CI has
# always split them by TYPING A LIST OF LEG NAMES INTO YAML, which is the
# drift this file refuses everywhere else: the moment a leg is named in a second
# place, the second place can go stale silently, and the last time it did the
# house-rules engine went unrun in CI for a whole cycle.
#
# So the table lives HERE, beside the legs, and `--list-legs` is how anything
# else asks. CI adds a COUNT (how many runners); it never adds a NAME.
#
# THE FIELDS.
#   <unit>        the name a runner is handed.
#   <needs>       the organs the unit's legs assume, comma-joined, or `none`. A
#                 DECLARATION, not a guard: the gate is what refuses a unit
#                 whose organ is missing, and it refuses at the leg. Nothing
#                 reads this field to decide whether to bring a stack up.
#   <shards>      `0` — the unit is indivisible — or `N-capable`, meaning the
#                 unit's body takes a `k/N` and runs the k-th of N parts.
#   <composed-of> the unit's legs, comma-joined, in the full gate's own order —
#                 and, for a unit that shards by a registered population, that
#                 population after them (`selftest` names its leg and then every
#                 drive the leg walks, so a reader can see what one shard holds).
#                 IT CARRIES NO PASS COUNT AND THERE IS NO FIFTH FIELD. A run's
#                 own `composed-of:` banner names `pytest-x2/1` when that run
#                 was handed `--passes 1` (the seam grammar `<leg>[/<passes>]`,
#                 absent meaning 2) — because the pass count is a property of
#                 the RUN, not of the unit, and a listing that carried one
#                 would be answering a question it was never asked. Four
#                 fields, and `ci.yml` reads column 3.
#
# WHAT THE TABLE IS CHECKED AGAINST, every time it is printed: the leg call
# sites in this file. A full-gate leg is announced at COLUMN ZERO (`leg <name>`
# at the start of a line); a leg that belongs to one mode's block is announced
# INDENTED, inside that block. That is not a convention this comment is asking
# for — it is the rule `--list-legs` reads the file by, and the listing refuses
# (exit 2) rather than guess when a leg it cannot place appears.
#
# `secrets` and `pytest` ARE NOT IN THIS TABLE: both are announced inside the
# `--loop` block, which the full path skips entirely (`exit 0` at its end).
# They are `--loop`'s legs, they are driven by their own drives, and a unit
# table that listed them would be promising a runner something the full gate
# never runs. `fe` WAS one of those three and is not any more — it moved onto
# the full path, because a tri-state leg that prints `skip` is still a leg that
# ran, and a leg the full gate never announces is one no verdict row names.
# selftest_registered_drives — the drive names, in the order this leg walks them.
#
# TWO DIRECTORIES, AND THE SECOND ONE IS ONE PATH WIDE ON PURPOSE. Every drive
# under `scripts/tests/` is registered here, and so is exactly one under
# `deploy/tests/`: `test_stage.sh`, which is the first deploy-layer drive to
# carry `drive_preamble.sh` and therefore the first one this leg can run
# without the hazard the blind-spot block below still declares for its
# siblings. The widening is a NAMED PATH and not a `deploy/tests/` glob,
# because the reason the other deploy drives are out has not expired: they do
# not source the preamble, and this leg runs inside the pre-push hook.
#
# IT IS ALSO THE ONE READER OF BOTH DRIVE HOMES, and that is `--with-path`'s
# whole job, measured 2026-09-21 in the v2.1.1 fold. The widening above put ONE member
# outside `scripts/tests/`, and the always-on leg's path composer went on
# printf-ing `scripts/tests/test_<name>.sh` for every name this function hands
# it — so `stage` resolved to `scripts/tests/test_stage.sh`, a file that has
# never existed, and the member reported `could not look` forever. It was
# LATENT only because the unreachable `--store-durations` mode arm kept
# the durations file from ever naming `stage`; fixing that flag in the same
# rung unmasks it, which is why both land together. A second place that knows
# where a drive lives is a second answer to "where is this drive", and the
# first tree where they disagreed is this one.
#
#   selftest_registered_drives              the names, one per line — the
#                                           existing contract, byte-identical,
#                                           and what the `selftest` unit row,
#                                           `--list-legs` and the always-on
#                                           member walk all read.
#   selftest_registered_drives --with-path  `name<TAB>path`, the same
#                                           population in the same order, for
#                                           the one caller that needs to OPEN
#                                           the file rather than name it.
#
# AND A THIRD HOME, WHICH IS THE PRODUCT'S AND IS NOT IN THIS FILE AT ALL.
# `scripts/local/drives/test_<name>.sh` is the drive drawer — the same
# platform-extension-1 convention as `scripts/local/legs/`, and here for the
# same measured reason: the first consumer's v2.1.0 fold carried four product
# drives of their own (`test_frontend_legs`, `test_seed2`, `test_criteria_lint`,
# `test_grants_role`), and the only way to have this leg run one was to edit
# THIS FILE, which is the edit that fast-forwarded 1826 lines away. A drawer
# member is named `local:<name>` wherever a drive name is printed, so the
# verdict row, the composed-of and the shard's own line all say which drives are
# the product's — and it comes out of THIS function, because a second reader of
# a third home is the `stage`-resolved-to-a-file-that-never-existed defect one
# home further on.
#
# WHAT A DRAWER DRIVE OWES, and every one of these is exit 2 AT THE LISTING
# naming the file — never a silently smaller drive set:
#
#   `+x`                    a drive this leg cannot execute is one it would
#                           report as a could-not-look forever.
#   the preamble            the file must source `scripts/tests/drive_preamble.sh`.
#                           This is the SAME condition the `deploy/tests/` gap
#                           below this leg is declared on, and for the same two
#                           reasons: §1 neutralises the absolute `GIT_DIR` that
#                           `git -C <linked worktree> push` exports into the
#                           pre-push hook — which is the moment this leg runs in
#                           — and §4 strips the CI exemption. A product drive
#                           without it can write into the real repository from
#                           inside a green gate.
#   a name of its own       lower-case letters, digits and `_`, and not a name
#                           this file's own drives already carry, and not a
#                           name the LEG drawer carries either (both are printed
#                           `local:<name>`, so two homes for one name would be
#                           one label on the verdict row meaning two things).
#
# ABSENT, IT COSTS NOTHING: no drawer, and every line of output below is
# byte-identical to a tree that has never heard of one —
# `scripts/tests/test_selftest_leg.sh` asserts that by `cmp`, not by this
# paragraph.
#
# ONE BODY, TWO SHAPES, and the name-only shape is the default because four
# existing readers take it — including `scripts/tests/test_list_legs.sh`, which
# EXTRACTS this function's text and runs it, so the body also stays
# self-contained (no helper defined elsewhere, no `}` at column 1 inside it).
# That is also why the drawer's directory, the leg drawer's directory and the
# refusal text are all spelled inline here rather than reached through the
# helpers one screen down: extracted standalone, this function has no helpers.
selftest_registered_drives() {
    local with_path="" template="" dir="" legdir="" f="" name="" known=""
    case "${1:-}" in
    "") ;;
    --with-path) with_path=1 ;;
    *)
        echo "!! selftest_registered_drives: unknown argument '$1' (nothing, or --with-path)" >&2
        return 2
        ;;
    esac
    template=$(awk -v with_path="$with_path" '
        /^\.\/scripts\/tests\/test_[a-z_]+\.sh$/ {
            path = $0
            sub(/^\.\//, "", path)
            name = path
            sub(/^scripts\/tests\/test_/, "", name)
            sub(/\.sh$/, "", name)
            print (with_path == "" ? name : name "\t" path)
        }
        /^\.\/deploy\/tests\/test_stage\.sh$/ { print (with_path == "" ? "stage" : "stage\tdeploy/tests/test_stage.sh") }
    ' scripts/check.sh)
    [ -z "$template" ] || printf '%s\n' "$template"
    # THE NAMES THIS FILE ALREADY CARRIES, taken from what was just printed
    # rather than re-derived: one answer, one place. Spaces around each name so
    # `case` matches a whole word and never a substring of one.
    known=" $(printf '%s\n' "$template" | awk -F'	' 'NF { printf "%s ", $1 }')"
    dir="${DJB_LOCAL_DRIVES_DIR:-scripts/local/drives}"
    legdir="${DJB_LOCAL_LEGS_DIR:-scripts/local/legs}"
    [ -d "$dir" ] || return 0
    for f in "$dir"/test_*.sh; do
        [ -f "$f" ] || continue
        name=${f##*/}
        name=${name#test_}
        name=${name%.sh}
        # `LC_ALL=C` AROUND THE CASE, because a bracket range is the locale's
        # and not ASCII's: under `en_US.UTF-8` bash collates case-insensitively
        # and `[!a-z0-9_]` admits `test_Probe.sh`, which then resolves to a
        # `local:Probe` nothing else in this gate spells that way. Set and
        # restored around the test alone, so nothing below inherits it.
        local _drive_lc="${LC_ALL:-}"
        LC_ALL=C
        case "$name" in
        "" | *[!a-z0-9_]* | [!a-z0-9]*)
            LC_ALL="$_drive_lc"
            [ -n "$_drive_lc" ] || unset LC_ALL
            echo "!! product drive ${f}: '${name}' is not a drive name — lower-case letters, digits and '_', starting with a letter or a digit. The file is named test_<name>.sh." >&2
            return 2
            ;;
        esac
        LC_ALL="$_drive_lc"
        [ -n "$_drive_lc" ] || unset LC_ALL
        if [ ! -x "$f" ]; then
            echo "!! product drive ${f}: it is not executable — a drive this leg cannot run is a drive it would report as could-not-look on every gate (chmod +x)." >&2
            return 2
        fi
        # A SOURCE LINE, NOT A MENTION. `grep -q 'drive_preamble\.sh'` admitted
        # `# does not source drive_preamble.sh` — a comment SAYING the file is
        # not sourced registered as sourcing it, which is the whole guard
        # inverted by a sentence the review that found it). The shape is a `.` or a `source`
        # opening the line.
        if ! grep -qE '^[[:space:]]*(\.|source)[[:space:]]+[^[:space:]]*drive_preamble\.sh' "$f"; then
            echo "!! product drive ${f}: it does not source scripts/tests/drive_preamble.sh." >&2
            echo "   That preamble is the same condition the deploy/tests/ gap is declared on:" >&2
            echo "   its section 1 neutralises the absolute GIT_DIR a push exports into the" >&2
            echo "   pre-push hook — which is the moment this leg runs in — and its section 4" >&2
            echo "   strips the CI exemption. Without it a drive can write into the real" >&2
            echo "   repository from inside a green gate, exiting 0 the whole way." >&2
            return 2
        fi
        case "$known" in
        *" ${name} "*)
            echo "!! product drive ${f}: '${name}' is already a drive this gate has — one name, two members, and the verdict row would name it once." >&2
            return 2
            ;;
        esac
        if [ -e "${legdir}/${name}.sh" ]; then
            echo "!! product drive ${f}: '${name}' is also a product LEG (${legdir}/${name}.sh) — both are printed 'local:${name}', so one label on the verdict row would mean two members." >&2
            return 2
        fi
        known="${known}${name} "
        if [ -z "$with_path" ]; then
            printf 'local:%s\n' "$name"
        else
            printf 'local:%s\t%s\n' "$name" "$f"
        fi
    done
}


# >>> local-legs >>>
# THE PRODUCT'S OWN LEGS, AND WHY THEY ARE NOT IN THIS FILE.
#
# WHAT IT IS FOR. This repository is a TEMPLATE: a product clones it and then
# grows legs of its own — a typecheck, a partition census, a seed pass, a
# licence scan. Until now the only place to put one was inside this file, and
# the first consumer's v2.1.0 fold measured what that costs: 94 conflicts, 21
# of them in `scripts/ quality/ .github/`, and `scripts/check.sh` itself
# FAST-FORWARDED byte-identical — 1826 lines of their legs vanished with no
# conflict at all. Silent, and in the wrong direction.
#
# SO A PRODUCT DECLARES BESIDE THIS FILE RATHER THAN EDITING IT (the
# platform-extension-1 ruling). The drawer is `scripts/local/legs/`, the template
# NEVER ships a `scripts/local/` path, and therefore a release can never
# conflict with one. Absent, every line below is a no-op and this gate's
# listing, transcripts and verdict rows are byte-identical to a tree that has
# no drawer at all — which is the negative `scripts/tests/test_local_legs.sh`
# asserts by DIFFING them, not by reading this paragraph.
#
# WHAT A LEG DECLARES, AND WHY EACH FIELD EXISTS RATHER THAN HAVING A DEFAULT.
# The header is a versioned comment block at the top of the file:
#
#     # >>> leg v1 >>>
#     # unit: local
#     # needs: none
#     # tier: loop
#     # two-means: broken
#     # touches: frontend
#     # inputs: frontend/package.json
#     # env: DJB_FE_BASE_URL
#     # <<< leg <<<
#
#   unit:       the unit a runner is handed. `local` is the drawer's own unit;
#               any other name MAKES a new local unit with its own `needs` (the
#               consumer's `frontend node,network` is the worked case). A name
#               this gate already declares is exit 2 — a product may not
#               silently join `pytest-x2` and inherit its organs, its shards
#               and its pass count.
#   needs:      the organs the leg assumes, comma-joined, or `none`. A
#               DECLARATION exactly as `gate_unit`'s is; the unit's field is the
#               union of its legs'. Nothing reads it to bring a stack up.
#   tier:       `fast`, `loop` or `full` — the CHEAPEST mode that runs it, and
#               every mode above it runs it too. A product's typecheck sits in
#               `--fast`; a census sits in `--loop`; a licence scan sits at the
#               bank.
#   two-means:  `broken` or `finding`, and the grammar is the one the first
#               consumer arrived at after their own leg caught it on its first
#               run. This file's convention is "2 is enforcement broken", and
#               in-house instruments honour it — but `tsc` exits 2 for
#               DIAGNOSTICS PRESENT, the most ordinary finding there is, so
#               mapping that to broken plumbing files every type error as a
#               dead canary.
#                 `broken`  — 2 is ENFORCEMENT BROKEN (could-not-look, and it
#                             outranks a pass); any other non-zero is a
#                             finding. For instruments that declare this
#                             contract in their own headers.
#                 `finding` — 2 is a finding (this gate reads it as 1), and
#                             **3 or above is enforcement broken**: a tool
#                             that reserves 2 for findings and went past it is
#                             the tool failing to do the job rather than the
#                             tree failing the check, so nothing was judged.
#               Declared, because guessing either way is a red that means the
#               wrong thing.
#   touches:    optional. Space-joined repository-relative path PREFIXES. Under
#               `--fast` and `--loop` a leg none of whose prefixes is in the
#               rung's changed set is SKIPPED WITH A PRINTED LINE; under the
#               full gate and under `--leg` it ALWAYS runs, whatever it touches
#               (the N820a rule: a narrowed mode may skip, a full one may not).
#   inputs:     optional. Space-joined repository-relative path prefixes whose
#               CONTENT joins the leg's reuse key, so a product leg's verdict is
#               reused on exactly the terms the template's drives are.
#   env:        optional. Environment variable NAMES whose values join the same
#               key.
#
# WHAT IT REFUSES, AND THE REFUSAL IS ALWAYS 2. A file that is not executable,
# a header whose version is not `v1`, a missing required field, an unknown
# field, an unparsable value, a name colliding with a leg or a drive this gate
# already has, two legs with one name, a `unit:` naming a template unit — each
# is exit 2 AT THE LISTING, naming the file and the field. Never a silently
# smaller gate.
#
# WHAT IT DOES NOT COVER, said here rather than discovered: a leg that must run
# INSIDE the pytest process (a product fixture, a conftest plugin) is not
# expressible here and has its own seam; and NOTHING in this file says a
# product's leg is CORRECT — only that it was found, declared, run and named.

#: The drawer. `DJB_LOCAL_LEGS_DIR` exists for the same reason
#: `DJB_SELFTEST_DRIVES_DIR` does: so the leg's own drive can point the reader
#: at a planted set under its scratch directory instead of writing an untracked
#: executable into the checkout the gate is measuring.
local_legs_dir() {
    printf '%s\n' "${DJB_LOCAL_LEGS_DIR:-scripts/local/legs}"
}

#: The header sentinels and the fields. Required first, optional after; the
#: split is what the refusal messages read.
LOCAL_LEG_HEADER_OPEN='# >>> leg v1 >>>'
LOCAL_LEG_HEADER_CLOSE='# <<< leg <<<'
LOCAL_LEG_REQUIRED='unit needs tier two-means'
LOCAL_LEG_OPTIONAL='touches inputs env'

# local_legs__has <name> — 0 when stdin carries that exact line. The fence's
# own copy of the one-line reader, so the extracted block is sourceable by its
# drive without dragging the always-on leg in with it.
local_legs__has() {
    awk -v n="$1" '$0 == n { found = 1 } END { exit(found ? 0 : 1) }'
}

# local_legs__known_names — every member name this gate already has: the
# template's own legs and the drives the selftest leg walks. DERIVED, never
# listed: `DJB_LOCAL_LEGS_KNOWN_NAMES` is the drive's plant point and
# `FULL_LEGS_TEMPLATE` is this file's own assignment one screen up.
local_legs__known_names() {
    if [ -n "${DJB_LOCAL_LEGS_KNOWN_NAMES+x}" ]; then
        printf '%s\n' "$DJB_LOCAL_LEGS_KNOWN_NAMES"
        return 0
    fi
    printf '%s\n' "${FULL_LEGS_TEMPLATE:-}" | tr ',' '\n'
    if command -v selftest_registered_drives >/dev/null 2>&1; then
        selftest_registered_drives
    fi
    return 0
}

# local_legs__template_units — the unit names THIS FILE declares, derived from
# its own `gate_unit` call sites. Read rather than listed: a product may not
# take a name the template already uses, and a hand list here would go stale
# the first time a unit is added.
local_legs__template_units() {
    if [ -n "${DJB_LOCAL_LEGS_TEMPLATE_UNITS+x}" ]; then
        printf '%s\n' "$DJB_LOCAL_LEGS_TEMPLATE_UNITS"
        return 0
    fi
    [ -r scripts/check.sh ] || return 0
    awk '/^gate_unit [a-z0-9-]+ /{ print $2 }' scripts/check.sh
}

#: The scan, memoised for the process. `LOCAL_LEGS_TABLE` is one TAB-separated
#: row per leg — name, unit, needs, tier, two-means, touches, inputs, env,
#: file — and `LOCAL_LEGS_RC` is the scan's own verdict, so a caller can print
#: the refusal once and every later caller gets the same answer.
LOCAL_LEGS_TABLE=""
LOCAL_LEGS_RC=""
LOCAL_LEGS_WHY=""

# local_legs__refuse <file> <sentence> — record and print one refusal.
local_legs__refuse() {
    LOCAL_LEGS_WHY="local leg ${1}: $2"
    # RECORDED, NOT ONLY PRINTED, so the caller's banner can name the cause
    # and a reader with no scrollback is still told what went wrong
    # (`scripts/gate_refuse.sh`, and the banner census in
    # `scripts/tests/test_gate_lease.sh` — which counts the cause line by its
    # literal text, so this paragraph may not spell it). Guarded by
    # `command -v` because this block is EXTRACTED and sourced on its own by
    # its drive, where the refusal library is not there to be called.
    if command -v gate_refuse >/dev/null 2>&1; then
        gate_refuse "$LOCAL_LEGS_WHY"
    else
        echo "!! ${LOCAL_LEGS_WHY}" >&2
    fi
    echo "   A product leg is DECLARED (scripts/check.sh, the local-legs block): a" >&2
    echo "   header this gate cannot read is exit 2 at the listing and never a" >&2
    echo "   silently smaller gate." >&2
    return 2
}

# local_legs__header <file> — the header's field lines, `<field> <value>` per
# line, on stdout. Exit 0 read · 2 refused (message printed).
local_legs__header() {
    local file=$1 block seen="" f v line got
    block=$(awk -v o="$LOCAL_LEG_HEADER_OPEN" -v c="$LOCAL_LEG_HEADER_CLOSE" '
        $0 == o { on = 1; next }
        $0 == c { exit }
        on { print }
    ' "$file")
    if [ -z "$block" ]; then
        # THE VERSION IS PART OF THE OPENING SENTINEL, so an unknown version and
        # a missing header are told apart here rather than left as one message:
        # a product that wrote `# >>> leg v2 >>>` has declared something this
        # gate does not implement, which is a different problem from a file
        # with no header at all.
        if grep -q '^# >>> leg ' "$file" 2>/dev/null; then
            got=$(grep -m1 '^# >>> leg ' "$file" | awk '{print $4}')
            local_legs__refuse "$file" "its header declares version '${got:-?}' and this gate implements v1 only — the opening line is exactly '${LOCAL_LEG_HEADER_OPEN}'"
            return 2
        fi
        local_legs__refuse "$file" "it carries no '${LOCAL_LEG_HEADER_OPEN}' header block — a leg declares its unit, its needs, its tier and what its exit 2 means"
        return 2
    fi
    while IFS= read -r line; do
        case "$line" in
        '') continue ;;
        '#'*) ;;
        *)
            local_legs__refuse "$file" "the header line '${line}' is not a comment — every line between the sentinels is '# <field>: <value>'"
            return 2
            ;;
        esac
        line=${line#\#}
        line=${line# }
        [ -n "$line" ] || continue
        case "$line" in
        *:*) ;;
        *)
            local_legs__refuse "$file" "the header line '${line}' carries no '<field>: <value>' colon"
            return 2
            ;;
        esac
        f=${line%%:*}
        v=${line#*:}
        v=${v# }
        case " $LOCAL_LEG_REQUIRED $LOCAL_LEG_OPTIONAL " in
        *" $f "*) ;;
        *)
            local_legs__refuse "$file" "unknown header field '${f}' — this gate reads ${LOCAL_LEG_REQUIRED} ${LOCAL_LEG_OPTIONAL}"
            return 2
            ;;
        esac
        case " $seen " in
        *" $f "*)
            local_legs__refuse "$file" "header field '${f}' is declared twice — a field with two values has none"
            return 2
            ;;
        esac
        seen="${seen}${seen:+ }${f}"
        if [ -z "$v" ]; then
            local_legs__refuse "$file" "header field '${f}:' is empty — an empty declaration says nothing; write the value"
            return 2
        fi
        printf '%s %s\n' "$f" "$v"
    done <<EOF
${block}
EOF
    for f in $LOCAL_LEG_REQUIRED; do
        case " $seen " in
        *" $f "*) ;;
        *)
            local_legs__refuse "$file" "its header declares no '${f}:' — the required fields are ${LOCAL_LEG_REQUIRED}"
            return 2
            ;;
        esac
    done
    return 0
}

# local_legs__field <header-text> <field> — that field's value, or nothing.
local_legs__field() {
    awk -v want="$2" '$1 == want { $1 = ""; sub(/^ /, ""); print; exit }' <<EOF
${1}
EOF
}

# local_legs_scan — the drawer, read and validated. Exit 0 (zero legs is a
# clean read) · 2 refused, with the refusal printed once.
local_legs_scan() {
    local dir f name header unit needs tier twomeans touches inputs envnames hrc
    local names="" units known rows=""
    [ -z "$LOCAL_LEGS_RC" ] || return "$LOCAL_LEGS_RC"
    LOCAL_LEGS_RC=0
    LOCAL_LEGS_TABLE=""
    dir=$(local_legs_dir)
    [ -d "$dir" ] || return 0
    known=$(local_legs__known_names)
    units=$(local_legs__template_units)
    for f in "$dir"/*.sh; do
        [ -f "$f" ] || continue
        name=${f##*/}
        name=${name%.sh}
        # `_`-LED FILES ARE NOT LEGS. `_provision-<unit>.sh` is a unit's own
        # one-shot provisioner and the underscore is what keeps it out of the
        # population without a second list saying so.
        case "$name" in
        _*) continue ;;
        esac
        case "$name" in
        *[!a-z0-9_-]* | [!a-z0-9]*)
            local_legs__refuse "$f" "the file name is not a leg name — lower-case letters, digits, '-' and '_', starting with a letter or a digit"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        if [ ! -x "$f" ]; then
            local_legs__refuse "$f" "it is not executable — a leg this gate cannot run is a leg it would silently skip (chmod +x)"
            LOCAL_LEGS_RC=2
            return 2
        fi
        # THROUGH `gate_capture`, NOT A BARE `$( )`, and the difference is the
        # caller's cause line. A command substitution is a SUBSHELL, so a
        # `GATE_LAST_REFUSAL` the header reader records inside one dies with
        # it and the drawer banner one screen down prints "the callee set
        # none" about a callee that said exactly what was wrong (the F7 rule,
        # `scripts/gate_refuse.sh`). `command -v` because this block is
        # EXTRACTED and sourced on its own by its drive, where that library is
        # not there to be called.
        hrc=0
        if command -v gate_capture >/dev/null 2>&1; then
            gate_capture header local_legs__header "$f" || hrc=$?
        else
            header=$(local_legs__header "$f") || hrc=$?
        fi
        if [ "$hrc" != "0" ]; then
            LOCAL_LEGS_RC=2
            return 2
        fi
        unit=$(local_legs__field "$header" unit)
        needs=$(local_legs__field "$header" needs)
        tier=$(local_legs__field "$header" tier)
        twomeans=$(local_legs__field "$header" two-means)
        touches=$(local_legs__field "$header" touches)
        inputs=$(local_legs__field "$header" inputs)
        envnames=$(local_legs__field "$header" env)
        case "$unit" in
        *[!a-z0-9-]*)
            local_legs__refuse "$f" "unit: '${unit}' is not a unit name — lower-case letters, digits and '-'"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        if printf '%s\n' "$units" | local_legs__has "$unit"; then
            local_legs__refuse "$f" "unit: '${unit}' is a unit THIS GATE declares — a product leg may not join one and inherit its organs, its shards and its pass count. Use 'local', or a new name of your own"
            LOCAL_LEGS_RC=2
            return 2
        fi
        case "$tier" in
        fast | loop | full) ;;
        *)
            local_legs__refuse "$f" "tier: '${tier}' — the tiers are fast, loop and full (the CHEAPEST mode that runs it; every mode above it runs it too)"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        case "$twomeans" in
        finding | broken) ;;
        *)
            local_legs__refuse "$f" "two-means: '${twomeans}' — exit 2 from this leg is either 'broken' (enforcement itself, which outranks a pass) or 'finding' (an ordinary violation this gate reads as 1)"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        case "$needs" in
        *[!a-z0-9,-]*)
            local_legs__refuse "$f" "needs: '${needs}' — comma-joined organ names, or 'none'"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        case "$envnames" in
        *[!A-Za-z0-9_\ ]*)
            local_legs__refuse "$f" "env: '${envnames}' — space-joined variable NAMES, never values"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        if printf '%s\n' "$known" | local_legs__has "$name"; then
            local_legs__refuse "$f" "'${name}' is already a leg or a drive this gate has — one name, two members, and the verdict row would name it once"
            LOCAL_LEGS_RC=2
            return 2
        fi
        case " $names " in
        *" $name "*)
            local_legs__refuse "$f" "'${name}' is declared twice in the drawer"
            LOCAL_LEGS_RC=2
            return 2
            ;;
        esac
        names="${names}${names:+ }${name}"
        rows="${rows}${name}	${unit}	${needs}	${tier}	${twomeans}	${touches}	${inputs}	${envnames}	${f}
"
    done
    LOCAL_LEGS_TABLE="$rows"
    return 0
}

# local_legs_names — `local:<name>` per leg, in the drawer's own order.
local_legs_names() {
    awk -F'	' 'NF { print "local:" $1 }' <<EOF
${LOCAL_LEGS_TABLE}
EOF
}

# local_legs_field <local:name|name> <column 1-9> — one field of one leg's row.
local_legs_field() {
    local want=${1#local:}
    awk -F'	' -v w="$want" -v c="$2" '$1 == w { print $c; exit }' <<EOF
${LOCAL_LEGS_TABLE}
EOF
}

# local_legs_units — the unit names the drawer declares, first-seen order.
local_legs_units() {
    awk -F'	' 'NF && !($2 in seen) { seen[$2] = 1; print $2 }' <<EOF
${LOCAL_LEGS_TABLE}
EOF
}

# local_legs_unit_needs <unit> — the union of its legs' needs, comma-joined, or
# `none`. `none` is dropped from a union that has a real organ in it: a unit
# that needs a database and nothing-in-particular needs a database.
local_legs_unit_needs() {
    local out
    out=$(awk -F'	' -v u="$1" '$2 == u { print $3 }' <<EOF | tr ',' '\n' | grep -v '^none$' | grep -v '^$' | LC_ALL=C sort -u | tr '\n' ',' | sed 's/,$//'
${LOCAL_LEGS_TABLE}
EOF
)
    printf '%s\n' "${out:-none}"
}

# local_legs_unit_members <unit> — `local:<name>` per leg of that unit.
local_legs_unit_members() {
    awk -F'	' -v u="$1" '$2 == u { print "local:" $1 }' <<EOF
${LOCAL_LEGS_TABLE}
EOF
}

# local_legs_tier_runs <declared tier> <mode tier> — 0 when a leg declaring the
# first is run by a gate in the second. `fast` ⊂ `loop` ⊂ `full`: the tier is
# the CHEAPEST mode that runs it, so every mode above it runs it too.
local_legs_tier_runs() {
    local want=$1 have=$2
    case "$have" in
    full) return 0 ;;
    loop) [ "$want" != "full" ] ;;
    fast) [ "$want" = "fast" ] ;;
    *) return 1 ;;
    esac
}

# local_legs_tier_any <mode tier> — `local:<name>` per leg this mode would run,
# or nothing. The one question a mode's guard asks before announcing the leg at
# all: a `--fast` run with no fast-tier leg in the drawer announces nothing, so
# its transcript is the transcript of a tree with no drawer.
local_legs_tier_any() {
    local row name t out=""
    while IFS= read -r row; do
        [ -n "$row" ] || continue
        name=$(printf '%s' "$row" | cut -f1)
        t=$(printf '%s' "$row" | cut -f4)
        local_legs_tier_runs "$t" "$1" || continue
        out="${out}${out:+ }local:${name}"
    done <<EOF
${LOCAL_LEGS_TABLE}
EOF
    printf '%s\n' "$out"
}

# local_legs_touched <touches> <changed-file list> — 0 when the leg's declared
# prefixes matched something the rung changed, 1 when they matched nothing, 2
# when the changed set could not be read at all.
#
# A SET THIS CANNOT READ MEANS THE LEG RUNS. The whole point of `touches:` is to
# SKIP work on a narrowed run, and skipping on an unreadable set would be a leg
# that went quiet for a reason nobody measured.
local_legs_touched() {
    local globs=$1 changed=$2 g c
    [ -n "$globs" ] || return 0
    [ -n "$changed" ] || return 2
    for g in $globs; do
        for c in $changed; do
            case "$c" in
            "$g" | "$g"/*) return 0 ;;
            esac
        done
    done
    return 1
}
# local_legs_changed_files — the paths this run is narrowed to, space-joined,
# or nothing when the run is not narrowed at all. `DJB_LOCAL_LEGS_CHANGED_FILES` is
# the drive's plant point; `LOOP_SCOPE_CHANGED_FILES` is the `--loop` scope's
# own derivation, computed once above and read here rather than re-derived.
local_legs_changed_files() {
    if [ -n "${DJB_LOCAL_LEGS_CHANGED_FILES+x}" ]; then
        printf '%s\n' "$DJB_LOCAL_LEGS_CHANGED_FILES"
        return 0
    fi
    printf '%s\n' "${LOOP_SCOPE_CHANGED_FILES:-}"
}

# local_leg_key <local:name> [<measured-tree listing>] — the reuse key for one
# product leg, in `drive_key`'s own grammar (`ok <schema>:<digest> <parts>` or
# `err <why>`) so `always_on__consult` reads ONE shape whatever the member is.
#
# WHAT IS IN IT. The leg's own bytes, its declared `inputs:` expanded through
# the measured tree exactly as a drive's `# drives:` paths are, the VALUES of
# its declared `env:` names, and this machine. A product leg's verdict is
# therefore reused on precisely the terms the template's drives are — which is
# the whole of the +140 lines the first consumer had to add to `gate_ledger.sh`
# to get the same thing by hand.
local_leg_key() {
    local name=${1#local:} listing=${2:-} file text parts="" one d digest v
    file=$(local_legs_field "$name" 9)
    [ -n "$file" ] && [ -r "$file" ] || {
        printf 'err the local leg %s is not readable\n' "${file:-local:$name}"
        return 1
    }
    command -v sha256_of >/dev/null 2>&1 || {
        printf 'err no digest reader in this shell\n'
        return 1
    }
    text="${DRIVE_KEY_SCHEMA:-drive-v1}
name local:${name}
header $(local_legs_field "$name" 2)|$(local_legs_field "$name" 3)|$(local_legs_field "$name" 4)|$(local_legs_field "$name" 5)|$(local_legs_field "$name" 6)|$(local_legs_field "$name" 7)|$(local_legs_field "$name" 8)"
    one=$(sha256_of "$file") || {
        printf 'err %s could not be digested\n' "$file"
        return 1
    }
    text="${text}
self ${one}"
    parts="self:$(printf '%s' "$one" | cut -c1-12)"
    for d in $(local_legs_field "$name" 7); do
        if [ -n "$listing" ] && command -v drive__expand >/dev/null 2>&1; then
            one=$(drive__expand "$listing" "$d")
        else
            one=$(git ls-files -s -- "$d" 2>/dev/null || true)
        fi
        if [ -z "$one" ]; then
            printf 'err its declared input %s expands to nothing in the measured tree — never a silently narrower key\n' "$d"
            return 1
        fi
        digest=$(printf '%s\n' "$one" | sha256_of) || {
            printf 'err %s could not be digested\n' "$d"
            return 1
        }
        text="${text}
${d} ${digest}"
        parts="${parts},${d}:$(printf '%s' "$digest" | cut -c1-12)"
    done
    for d in $(local_legs_field "$name" 8); do
        eval "v=\${${d}:-<unset>}"
        digest=$(printf '%s' "$v" | sha256_of) || {
            printf 'err the value of %s could not be digested\n' "$d"
            return 1
        }
        text="${text}
env:${d} ${digest}"
        parts="${parts},env:${d}:$(printf '%s' "$digest" | cut -c1-12)"
    done
    if command -v drive_machine_digest >/dev/null 2>&1; then
        one=$(drive_machine_digest) || {
            printf 'err this machine could not be digested\n'
            return 1
        }
        text="${text}
machine ${one}"
        parts="${parts},machine:$(printf '%s' "$one" | cut -c1-12)"
    fi
    digest=$(printf '%s\n' "$text" | sha256_of) || {
        printf 'err the key could not be digested\n'
        return 1
    }
    printf 'ok %s:%s %s cites=0 machine=%s\n' \
        "${DRIVE_KEY_SCHEMA:-drive-v1}" "$digest" "$parts" \
        "$(drive_machine_label 2>/dev/null || echo unstated)"
}

#: One `_provision-<unit>.sh` per local unit, run ONCE before that unit's first
#: leg and never again — the seam a unit with its own organs needs (`node`,
#: `network`) and the one thing a leg may not do for itself, because N legs
#: would each pay it.
LOCAL_LEGS_PROVISIONED=""
local_legs_provision() {
    local unit=$1 f rc=0
    case " $LOCAL_LEGS_PROVISIONED " in
    *" $unit "*) return 0 ;;
    esac
    f="$(local_legs_dir)/_provision-${unit}.sh"
    if [ ! -f "$f" ]; then
        # NOTHING TO RUN IS A UNIT THAT IS PROVISIONED, and it is marked so the
        # `[ -f ]` is paid once rather than once per leg.
        LOCAL_LEGS_PROVISIONED="${LOCAL_LEGS_PROVISIONED}${LOCAL_LEGS_PROVISIONED:+ }${unit}"
        return 0
    fi
    if [ ! -x "$f" ]; then
        echo "!! ${f} is not executable — a provisioner this gate cannot run is a unit whose legs run unprovisioned." >&2
        return 2
    fi
    echo "  local unit ${unit}: provisioning — ${f}"
    ("$f") || rc=$?
    if [ "$rc" != "0" ]; then
        echo "!! ${f} exited ${rc} — unit '${unit}' is NOT provisioned." >&2
        return "$rc"
    fi
    # THE MARK GOES ON ON SUCCESS AND NOWHERE ELSE. Marked before the run, a
    # FAILED provisioner made only the first leg of its unit could-not-look and
    # every later leg RAN — unprovisioned, against organs nothing brought up,
    # reporting whatever such a run reports. Once-only is a promise about
    # SUCCESSFUL provisioning; a failure is a state every leg of the unit has
    # to meet, and meeting it costs one `[ -f ]` and one re-run of a script
    # that has already said it cannot work.
    LOCAL_LEGS_PROVISIONED="${LOCAL_LEGS_PROVISIONED}${LOCAL_LEGS_PROVISIONED:+ }${unit}"
    return 0
}

# gate_leg_local_legs — the product legs, run. The tier the caller is asking
# about is `LOCAL_LEGS_MODE_TIER` and whether `touches:` may skip one is
# `LOCAL_LEGS_TOUCH_FILTER`; both are set at the call site and neither is
# guessed here, so there is one decision about a narrowed mode and it is made
# where the mode is known.
#
# Exit 0 every selected leg green · 1 one was red · 2 one could not look — and
# WHICH of the last two an exit 2 from a product's own tool means is the leg's
# `two-means:` declaration, never this gate's guess.
gate_leg_local_legs() {
    local tier=${LOCAL_LEGS_MODE_TIER:-full} filter=${LOCAL_LEGS_TOUCH_FILTER:-0}
    local row name unit t touches file rc worst=0 t0 took out changed tou prc twom
    local green=0 red=0 cannot=0 skipped=0 rednames="" cannotnames=""
    changed=$(local_legs_changed_files)
    while IFS= read -r row; do
        [ -n "$row" ] || continue
        name=$(printf '%s' "$row" | cut -f1)
        unit=$(printf '%s' "$row" | cut -f2)
        t=$(printf '%s' "$row" | cut -f4)
        touches=$(printf '%s' "$row" | cut -f6)
        file=$(printf '%s' "$row" | cut -f9)
        local_legs_tier_runs "$t" "$tier" || continue
        # UNDER `--leg <unit>` A LEG OF ANOTHER UNIT IS NOT THIS RUNNER'S. The
        # drawer may declare several units and one runner walks them all, so
        # the unit filter has to be applied per LEG and not per announcement.
        if [ -n "$GATE_LEG_UNIT_LEGS" ]; then
            case "$GATE_LEG_UNIT_LEGS" in
            *",local:${name},"*) ;;
            *) continue ;;
            esac
        fi
        if [ "$filter" = "1" ] && [ -n "$touches" ]; then
            tou=0
            local_legs_touched "$touches" "$changed" || tou=$?
            if [ "$tou" = "1" ]; then
                echo "  local:${name}: SKIPPED — its touches (${touches}) matched nothing this run changed. The full gate runs it regardless."
                skipped=$((skipped + 1))
                continue
            fi
            if [ "$tou" = "2" ]; then
                echo "  local:${name}: touches (${touches}) not applied — this run's changed set could not be read, so the leg runs"
            fi
        fi
        prc=0
        local_legs_provision "$unit" || prc=$?
        if [ "$prc" != "0" ]; then
            echo "  local:${name}: could not look — unit '${unit}' did not provision"
            cannot=$((cannot + 1))
            cannotnames="${cannotnames} local:${name}"
            continue
        fi
        out=$(mktemp "${TMPDIR:-/tmp}/djb-local-leg.XXXXXX") || {
            echo "  local:${name}: could not look — no scratch file for its output"
            cannot=$((cannot + 1))
            cannotnames="${cannotnames} local:${name}"
            continue
        }
        t0=$(date +%s)
        rc=0
        # UNPIPED, TO A FILE, AND READ AFTERWARDS — a reader in the pipeline
        # would replace the leg's exit status with its own.
        ("$file") >"$out" 2>&1 || rc=$?
        took=$(($(date +%s) - t0))
        echo "  local:${name}: exit ${rc} (${took}s)"
        if [ "$rc" = "0" ]; then
            green=$((green + 1))
        else
            sed 's/^/      | /' "$out"
            # THE DECLARED GRAMMAR, BOTH HALVES. `broken` reads 2 as
            # could-not-look; `finding` reads 2 as an ordinary red AND
            # anything at or above 3 as could-not-look, because a tool that
            # reserves 2 for findings and exited past it did not do the job.
            twom=$(printf '%s' "$row" | cut -f5)
            if { [ "$rc" = "2" ] && [ "$twom" = "broken" ]; } ||
                { [ "$twom" = "finding" ] && [ "$rc" -ge 3 ]; }; then
                cannot=$((cannot + 1))
                cannotnames="${cannotnames} local:${name}"
            else
                red=$((red + 1))
                rednames="${rednames} local:${name}"
            fi
        fi
        rm -f "$out"
    done <<EOF
${LOCAL_LEGS_TABLE}
EOF
    echo "  local legs (${tier}): ${green} green · ${red} red · ${cannot} could-not-look · ${skipped} skipped by touches"
    if [ "$cannot" -gt 0 ]; then
        echo "!! LOCAL LEGS COULD NOT LOOK:${cannotnames}" >&2
        [ "$red" = "0" ] || echo "!! and RED:${rednames}" >&2
        echo "   2 outranks 1. A product leg's exit 2 means what its 'two-means:' says." >&2
        worst=2
    elif [ "$red" -gt 0 ]; then
        echo "!! LOCAL LEGS RED:${rednames}" >&2
        worst=1
    fi
    return "$worst"
}
# <<< local-legs <<<

# THE DRIVE DRAWER IS READ HERE, FIRST, AND FOR THE LEG DRAWER'S OWN REASON.
# `local_legs__known_names` below asks the registry what names this gate already
# carries, and the registry now reads `scripts/local/drives/` — so a malformed
# drive drawer met from inside the leg scan would print its refusal in the
# middle of somebody else's message and be swallowed by a `$( )`. Read once,
# here, above everything: a gate that answered `--fast` while it could not read
# its own drive set would be a silently smaller gate, exactly as one that could
# not read its leg set would be.
#
# THROUGH `gate_capture`, NOT A BARE `$( )`, for the always-on leg's reason:
# a command substitution is a subshell, so a refusal recorded inside one dies
# with it and the banner below would print whatever this process saw LAST. The
# capture replays the callee's stderr where it would have printed and carries
# its first `!!` line out as the cause, which is what makes "see above" a
# sentence a reader without the scrollback can still act on.
SELFTEST_DRIVE_NAMES=""
if ! gate_capture SELFTEST_DRIVE_NAMES selftest_registered_drives; then
    gate_cause
    echo "!! the product-drive drawer (${DJB_LOCAL_DRIVES_DIR:-scripts/local/drives}) could not be read — see above." >&2
    echo "   Nothing was judged: no lease, no lock, no slot, no drive." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
fi

# THE DRAWER IS READ HERE, ONCE, AND IT IS WHAT MAKES `FULL_LEGS` A RUNTIME
# STRING. Above the unit table because the table declares a unit per local unit;
# above every mode because a malformed drawer is EXIT 2 AT THE LISTING and at
# every other door too — a gate that answered `--fast` while it could not read
# its own leg set would be a silently smaller gate.
if ! local_legs_scan; then
    gate_cause
    echo "!! the product-leg drawer ($(local_legs_dir)) could not be read — see above." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    echo "   Nothing was judged: no lease, no lock, no slot, no leg." >&2
    exit 2
fi
LOCAL_LEGS_MEMBERS=$(local_legs_names | tr '\n' ',' | sed 's/,$//')
[ -z "$LOCAL_LEGS_MEMBERS" ] || FULL_LEGS="${FULL_LEGS},${LOCAL_LEGS_MEMBERS}"

GATE_UNIT_ROWS=""
gate_unit() {
    local unit=$1 needs=$2 shards=$3 leg legs=""
    shift 3
    for leg in "$@"; do legs="${legs}${legs:+,}${leg}"; done
    GATE_UNIT_ROWS="${GATE_UNIT_ROWS}${unit}	${needs}	${shards}	${legs}
"
}

# `needs db` and not `none`: `db-pin` asks whether this checkout's database
# EXISTS under `loop` and `full` (it did not when this unit was first drawn, and
# a unit whose declaration predates its legs is the hand list this file is
# trying to stop). Everything else in the row needs the checkout and nothing
# more.
gate_unit static db 0 \
    ruff mypy import-linter djb-checks house-rules migrations goalpost-census \
    queue-index db-pin archaeology adr-census dangling-docs loop-names ci-env \
    deploy-check fe collectstatic
# The only leg that leaves this machine.
gate_unit supply-chain network 0 supply-chain
# Before-and-after facts about ONE suite on ONE machine: the temporal census is
# a DIFFERENCE across the two passes and the own-tree census is a claim about
# what the suite left behind, so neither can be run on a different runner from
# the suite it is about. `temporal-census` is announced twice and named once —
# a unit's membership is by leg NAME.
gate_unit pytest-x2 db,redis,temporal,minio,meilisearch N-capable \
    temporal-census partition pytest-x2 own-tree-census
# `0` AND NOT `N-capable`, TODAY, AND THE DIFFERENCE IS THE TRUTH: the drives
# inside this leg are invoked as a straight-line sequence of named blocks — not
# a loop over a directory, deliberately (`scripts/tests/test_selftest_leg.sh`
# asserts it), and each block's `./scripts/tests/test_<name>.sh` line is read at
# COLUMN ZERO by `scripts/tests/test_drive_preamble.sh`. So a `k/K` filter is a
# per-block guard, one edit per drive, and the declaration says `0` until that
# is built rather than promising a runner a split this body cannot do.
# `$SELFTEST_DRIVE_NAMES` AND NOT A SECOND `$(selftest_registered_drives)`: the
# drawer was read once, above, where its refusal is exit 2 rather than a partial
# list inside a command substitution nobody checks.
# shellcheck disable=SC2086 # the names word-split into arguments, as gate_unit takes them
gate_unit selftest db,docker,temporal N-capable selftest $SELFTEST_DRIVE_NAMES
gate_unit full-house-rules none 0 full-house-rules

# THE PRODUCT'S UNITS, ONE PER `unit:` THE DRAWER DECLARES. Indivisible (`0`):
# a product leg is one command and there is no `k/N` for this gate to hand it.
# The `needs` field is the UNION of the unit's legs' declarations, which is the
# same thing the rows above say by hand about legs written in this file.
for LOCAL_UNIT in $(local_legs_units); do
    # shellcheck disable=SC2046 # the members word-split into arguments, as gate_unit takes them
    gate_unit "$LOCAL_UNIT" "$(local_legs_unit_needs "$LOCAL_UNIT")" 0 $(local_legs_unit_members "$LOCAL_UNIT")
done
unset LOCAL_UNIT

# gate_announced_full_legs — the full gate's leg sequence, DERIVED from this
# file rather than remembered: every column-zero `leg <name>` call site, in
# order, de-duplicated on first appearance (`temporal-census` is announced
# before and after the suite and is one leg).
gate_announced_full_legs() {
    # `local-legs` IS ONE CALL SITE AND N MEMBERS, and that is why it is the one
    # name this reader rewrites. The site is guarded by the drawer being
    # non-empty, so a static read of this file would announce a leg an empty
    # drawer never runs; and the leg runs the drawer's legs BY NAME, so what the
    # sequence owes a reader is `local:<name>` per leg and not the name of the
    # runner. Both halves come from the same scan `FULL_LEGS` was grown from, so
    # the two can only disagree if the drawer changes mid-run.
    awk -v members="${LOCAL_LEGS_MEMBERS:-}" '
        /^leg [a-z0-9-]+ / {
            if ($2 in seen) { next }
            seen[$2] = 1
            # ONE CALL SITE, N MEMBERS: see the comment above this function.
            if ($2 == "local-legs") {
                if (members == "") { next }
                out = out (out ? "," : "") members
                next
            }
            out = out (out ? "," : "") $2
        }
        END { print out }
    ' scripts/check.sh
}

# gate_unpaired_legs — every `leg <name>` announcement in this file whose body is
# NOT called through `gate_run_body <name> …`, one per line, in file order.
#
# THE HOLE THIS CLOSES, which a field test found by planting it: an INDENTED
# `leg` whose body sits inline is announced by the gate on every run and is
# invisible to BOTH censuses — the listing reads column-zero call sites only, and
# the dry sequence reads the runner's own line, which such a leg never reaches.
# So the gate announces a leg, the verdict row does not name it, and no runner is
# ever handed it: the exact defect six legs carried, wearing a different hat.
# This census reads every indent, and it is the listing's business because the
# listing is the thing that would otherwise be quietly wrong.
gate_unpaired_legs() {
    awk '
        /^[[:space:]]*leg [a-z0-9-]+ / {
            if (pending != "") { print pending }
            pending = $2
            next
        }
        /^[[:space:]]*gate_run_body [a-z0-9-]+ / {
            if (pending == $2) { pending = "" }
            next
        }
        END { if (pending != "") { print pending } }
    ' scripts/check.sh
}

# >>> always-on-leg >>>
# THE LEG THAT MAKES THE LOOP SEE WHAT THE BANK SEES.
#
# THE MEASUREMENT THAT OPENED IT. Seven of nine failed banks in one cycle were
# red at a member the `--loop` never runs at all — a full-only leg, or a drive
# inside the selftest leg — so the class was discovered at the most expensive
# moment this system has: after a merge, with a PM waiting on a thirty-minute
# gate. Most of those members cost single-digit seconds. The loop was skipping
# them not because they were expensive but because nothing had ever sorted them
# by price.
#
# THE POPULATION IS DERIVED FROM A COMMITTED MEASUREMENT AND NEVER TYPED, and
# that is the design rather than a detail. A typed list of cheap members goes
# stale invisibly: a member that grows to forty seconds goes on being run by
# every loop, and a member that becomes cheap never joins. So the set is read
# out of `scripts/gate_member_durations.json` — written by
# `./scripts/check.sh --store-durations` (a MEASUREMENT run, never a verdict,
# and a separate run precisely so a tracked file is never written during a bank)
# and committed as the measurement it is. Crossing the floor is ANNOUNCED at the
# next full gate and the member LEAVES at the next `--store-durations`; nothing
# drops out silently.
#
# TWO DERIVATION SOURCES, ONE LEG, TWO PRINTED LISTS. The other half is
# DECLARED: a drive that walks the source tree — `scripts/*.sh`, `apps/**` —
# makes a claim about the whole tree, and a scope that narrowed the suite to two
# apps has not narrowed what such a drive is about. Those mark themselves with
# `# census: cross-app <reason>` and run at every scope whatever their price,
# because always-on is what being a census means. They are read through
# `loop_scope__declared_censuses` — the same reader, the same grammar and the
# same refusal the pytest door's marked modules go through.
#
# WHAT IT DOES NOT COVER, said here rather than discovered:
#
#   * ORGAN NEEDS ARE PER UNIT, NOT PER MEMBER. The only declaration this leg
#     can read is `gate_unit`'s, and it excludes exactly one need: `network`
#     (the supply-chain leg, the one leg that leaves this machine — a network
#     hiccup must never redden a per-rung run). A joined drive that wants docker
#     answers 2 here exactly as it answers 2 at the bank on a machine without
#     it: honest, and costly. A `# needs:` header per drive is the follow-up the
#     day a box runs `--loop`.
#   * THE FULL-ONLY LEGS ARE NAMED AND NOT RUN, and the reason is structural:
#     every one of their bodies is defined BELOW the `--loop` block's own exit
#     in this file, so at the moment this leg runs those functions do not exist.
#     They are printed with that reason on every run rather than quietly
#     dropped. Two of the three cheap ones are also POSITIONAL —
#     `temporal-census` and `own-tree-census` are before-and-after DIFFERENCES
#     about a suite that has finished, which is not a property a `--loop` has at
#     all — so moving a definition would not by itself make them loop members.
#   * DURATIONS ARE ONE MACHINE'S. The file records `machine:` and this leg
#     prints it; a file measured on a box and read on the Mac is ANNOUNCED,
#     never refused, because a member's price moving is a reason to re-measure
#     and not a reason to stop looking.

#: The floor, in seconds. A member measured at or above it stays full-only.
#: Overridable ONLY so the leg's own drive can plant either side of it without
#: writing a twelve-second member; nothing in the gate's own path sets it.
ALWAYS_ON_FLOOR=${DJB_ALWAYS_ON_FLOOR:-10}

#: Where the committed measurement lives. `DJB_GATE_MEMBER_DURATIONS` exists for
#: the same reason `DJB_GATE_DURATIONS_PATH` does one file over: so the reader's
#: own refusals can be driven against a planted file.
always_on_durations_path() {
    printf '%s\n' "${DJB_GATE_MEMBER_DURATIONS:-scripts/gate_member_durations.json}"
}

# always_on__legs [<check.sh>] — `<where> <name>` per leg announcement, in file
# order, de-duplicated: `loop` for a leg at or above the `--loop` block's
# closing `fi`, `full` for one below it.
#
# THE BOUNDARY IS THE BLOCK'S OWN `fi` AND NOT A COLUMN, deliberately. Reading
# column-zero call sites only (what `gate_announced_full_legs` does, for its own
# reason) would miss an INDENTED full leg and hand it to this leg as a loop leg
# — the hole `gate_unpaired_legs` exists to close, one question over. The
# `--loop` block's body is indented, so the first column-zero `fi` after its
# `if` is its own.
always_on__legs() {
    local file=${1:-scripts/check.sh}
    [ -r "$file" ] || return 2
    awk -v m='if [ "$MODE" = "--loop" ]; then' '
        index($0, m) == 1 { inloop = 1; next }
        inloop && $0 == "fi" { inloop = 0; past = 1; next }
        /^[[:space:]]*leg [a-z0-9-]+ / {
            if ($2 in seen) { next }
            seen[$2] = 1
            # THE RUNNER OF THE PRODUCT DRAWER IS NOT A MEMBER, ITS LEGS ARE.
            # The `local-legs` call site runs N declared legs, each with its
            # OWN tier, so the name that would land here means nothing to a
            # reader asking "does this member join a --loop". The members are
            # appended below, each under the tier its header declares.
            if ($2 == "local-legs") { next }
            print (past ? "full" : "loop"), $2
        }
    ' "$file"
    # `fast` AND `loop` BOTH READ AS `loop` HERE, and `full` as `full`, because
    # this reader's question is the always-on leg's: does a --loop run it. A
    # fast-tier leg is run by --fast AND by every mode above it, so the answer
    # for both is yes.
    awk -F'\t' 'NF { print ($4 == "full" ? "full" : "loop"), "local:" $1 }' <<EOF
${LOCAL_LEGS_TABLE:-}
EOF
}

# always_on__unit_needs <member> — the `needs` field of the unit that names it,
# or nothing. `GATE_UNIT_ROWS` is this file's own table, built above; a body
# driven standalone has none, and an empty table declares no needs, which is the
# honest answer for a scratch world with no units in it.
always_on__unit_needs() {
    awk -F'	' -v want="$1" '
        NF >= 4 {
            n = split($4, legs, ",")
            for (i = 1; i <= n; i++) if (legs[i] == want) { print $2; exit }
        }
    ' <<EOF
${GATE_UNIT_ROWS:-}
EOF
}

# always_on__names_has <name> — 0 when stdin carries that exact line.
always_on__names_has() {
    awk -v n="$1" '$0 == n { found = 1 } END { exit(found ? 0 : 1) }'
}

#: Filled by `always_on__read_durations`. `ALWAYS_ON_TABLE` is a scratch file of
#: `<name> <seconds>` lines — a file rather than a shell string because bash 3.2
#: has no associative arrays and a member name must never be word-split.
ALWAYS_ON_TABLE=""
ALWAYS_ON_MEASURED_AT=""
ALWAYS_ON_MACHINE=""

# always_on__read_durations <path> — 0 the file was read, 1 there is nothing
# readable there.
#
# A MISSING OR UNPARSABLE FILE IS NOT A REFUSAL, and this is the one place in
# this gate where that is the right answer: a tree before its first
# `--store-durations` has no such file, and refusing would mean the measurement
# could never be taken. The leg PRINTS the absence and runs the declared half
# alone. What IS a refusal is a file that parses and names a member this gate
# does not have — see `always_on_leg` below.
always_on__read_durations() {
    local path=$1 parsed
    ALWAYS_ON_MEASURED_AT=""
    ALWAYS_ON_MACHINE=""
    [ -r "$path" ] || return 1
    ALWAYS_ON_TABLE=$(mktemp "${TMPDIR:-/tmp}/djb-always-on-table.XXXXXX") || return 1
    parsed=$(awk '
        function value(line,   v) {
            v = line
            sub(/^[^:]*:[[:space:]]*"?/, "", v)
            sub(/"?[[:space:]]*,?[[:space:]]*$/, "", v)
            return v
        }
        /"measured_at"[[:space:]]*:/ && !inm { print "at " value($0); next }
        /"machine"[[:space:]]*:/ && !inm { print "mc " value($0); next }
        /"members"[[:space:]]*:[[:space:]]*\{/ { inm = 1; next }
        inm && /^[[:space:]]*\}/ { inm = 0; next }
        inm && match($0, /"[A-Za-z0-9_-]+"[[:space:]]*:[[:space:]]*[0-9]+/) {
            seg = substr($0, RSTART, RLENGTH)
            name = seg; sub(/^"/, "", name); sub(/".*/, "", name)
            secs = seg; sub(/^[^:]*:[[:space:]]*/, "", secs)
            print "mb " name " " secs
        }
    ' "$path") || return 1
    # AN EOF READER, NEVER A PIPE INTO AN EARLY-EXIT awk — the class
    # `scripts/tests/test_pipefail_readers.sh` censuses across this whole
    # population. The producer here could not fill a pipe buffer, and a census
    # that admitted "this one is safe" would be a census nobody can read.
    ALWAYS_ON_MEASURED_AT=$(awk '$1 == "at" { $1 = ""; sub(/^ /, ""); print; exit }' <<EOF
${parsed}
EOF
)
    ALWAYS_ON_MACHINE=$(awk '$1 == "mc" { $1 = ""; sub(/^ /, ""); print; exit }' <<EOF
${parsed}
EOF
)
    printf '%s\n' "$parsed" | awk '$1 == "mb" { print $2, $3 }' >"$ALWAYS_ON_TABLE"
    [ -s "$ALWAYS_ON_TABLE" ] || return 1
    return 0
}

# always_on__recorded <name> — the seconds recorded for it, or nothing.
always_on__recorded() {
    [ -n "$ALWAYS_ON_TABLE" ] && [ -f "$ALWAYS_ON_TABLE" ] || return 0
    awk -v n="$1" '$1 == n { print $2; exit }' "$ALWAYS_ON_TABLE"
}

# always_on__drives — the drive names this leg may run, one per line. The
# scratch branch is `DJB_SELFTEST_DRIVES_DIR`, read here and in the selftest leg
# and nowhere else, so the leg's own drive can hand it a planted set.
always_on__drives() {
    local d name
    if [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ]; then
        for d in "$DJB_SELFTEST_DRIVES_DIR"/test_*.sh; do
            [ -f "$d" ] || continue
            name=$(basename "$d" .sh)
            printf '%s\n' "${name#test_}"
        done
        return 0
    fi
    selftest_registered_drives
}

# always_on__drive_file <name> — where that drive actually lives.
#
# IT ASKS THE REGISTRY; IT DOES NOT COMPOSE A PATH. The one-line
# `printf '%s/test_%s.sh' scripts/tests "$1"` this replaces was a SECOND
# derivation of a population `selftest_registered_drives` already owns, and it
# was wrong for every member that registry places outside `scripts/tests/` —
# `stage` (`deploy/tests/test_stage.sh`) resolved to a file that has never
# existed and the member reported `could not look` with a path nobody could go
# and look at. A composer is only ever right while both homes agree, and the
# registry widened to two homes a cycle ago.
#
# THE SCRATCH BRANCH IS FIRST AND UNCHANGED: `DJB_SELFTEST_DRIVES_DIR` is a
# planted directory, every member in it is `test_<name>.sh` by construction,
# and `always_on__drives` derives the names from the same directory — so the
# registry has nothing to say about a set it did not write.
#
# THE FALLBACK IS THE OLD COMPOSITION, DELIBERATELY. A name the registry does
# not carry is not this function's refusal to make: it hands back the
# conventional path so `always_on__run` can print its own honest
# `could not look — <path> is not in this tree`, naming a path a reader can
# check, which is a better answer than an empty string.
#
# AND THE READER RUNS TO EOF. No `exit` in the awk and no quiet early-exiting
# tail: a consumer that stops at its first hit SIGPIPEs its producer, and under
# `pipefail` — which this gate runs under — that is a nonzero pipeline and a
# `set -e` death at the assignment (`scripts/tests/test_sweep.sh`'s
# `quiet_tail_guard` reds the shape wherever it appears).
always_on__drive_file() {
    # `local:` IS TWO POPULATIONS, AND THE REGISTRY IS ASKED FIRST. A product
    # LEG and a product DRIVE are both printed `local:<name>` — the registry
    # refuses a name that is in both drawers, so at most one of the two answers
    # — and the DRIVE's path is the registry's, because the registry is the one
    # reader of every drive home (that is the whole of `--with-path`'s job). A
    # leg's path is the leg scan's row, which is the only place that knows it.
    # Both are asked before the scratch branch, because a `local:` name can
    # never be a member of a planted drive set either.
    case "$1" in
    local:*)
        local localrows="" localpath=""
        if command -v selftest_registered_drives >/dev/null 2>&1; then
            localrows=$(selftest_registered_drives --with-path) || localrows=""
            localpath=$(printf '%s\n' "$localrows" |
                awk -F'\t' -v n="$1" '$1 == n && !seen { p = $2; seen = 1 } END { print p }')
        fi
        if [ -n "$localpath" ]; then
            printf '%s\n' "$localpath"
            return 0
        fi
        local_legs_field "$1" 9
        return 0
        ;;
    esac
    local name=$1 path="" rows=""
    if [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ]; then
        printf '%s/test_%s.sh\n' "$DJB_SELFTEST_DRIVES_DIR" "$name"
        return 0
    fi
    if command -v selftest_registered_drives >/dev/null 2>&1; then
        rows=$(selftest_registered_drives --with-path) || rows=""
        path=$(printf '%s\n' "$rows" |
            awk -F'\t' -v n="$name" '$1 == n && !seen { p = $2; seen = 1 } END { print p }')
    fi
    printf '%s\n' "${path:-scripts/tests/test_${name}.sh}"
}

# --- THE MEMBER'S VERDICT, CONSULTED BEFORE IT RUNS --------------------------
#
# THE SAME KEY, THE SAME LEDGER, THE SAME FUNCTIONS. `drive_key` and
# `drive_ledger_lookup` (scripts/gate_ledger.sh) are the bank's; a second key
# grammar over the same drives would be two answers to one question, and the
# first tree where they disagreed would be a loop reusing a row the bank would
# not have. So this consult is the selftest leg's consult with two differences,
# both in the direction of running MORE:
#
#   * A MEMBER THIS LEG CANNOT KEY RUNS. It does not become could-not-look. A
#     drive with no `# drives:` line, a tree that will not list, an unreadable
#     file: every one of them ends in the member being DRIVEN, with the reason
#     printed. At the bank a member that could not be keyed has not been cleared
#     and the leg says 2; here the member is about to be run anyway, so a failed
#     consult costs a second and nothing else.
#   * ONLY A GREEN BANKS, exactly as at the bank — a red or a could-not-look has
#     cleared nothing, and a row for it would be a verdict vouching for bytes
#     nobody drove.
#
# WHAT THE REUSE IS WORTH, measured rather than asserted: a hit is one ledger
# read, so the leg's whole price on an unchanged tree is about a second against
# the eighty this set costs when every member runs.
ALWAYS_ON_LISTING=""
ALWAYS_ON_TREE=""
ALWAYS_ON_KEY=""
ALWAYS_ON_PARTS=""

always_on__listing() {
    [ -z "$ALWAYS_ON_LISTING" ] || return 0
    ALWAYS_ON_TREE="${MEASURED_START:-}"
    if [ -z "$ALWAYS_ON_TREE" ]; then
        ALWAYS_ON_TREE=$(gate_measured_tree) || ALWAYS_ON_TREE=""
    fi
    [ -n "$ALWAYS_ON_TREE" ] || return 1
    ALWAYS_ON_LISTING=$(mktemp "${TMPDIR:-/tmp}/djb-always-on-listing.XXXXXX") || return 1
    git ls-tree -r "$ALWAYS_ON_TREE" >"$ALWAYS_ON_LISTING" 2>/dev/null || return 1
    [ -s "$ALWAYS_ON_LISTING" ] || return 1
    drive_machine_digest >/dev/null || return 1
    return 0
}

# always_on__consult <kind> <name> <file> <suffix> — 0 run it, 1 it was REUSED
# (and the line saying so has been printed).
always_on__consult() {
    local kind=$1 name=$2 file=$3 suffix=$4 keyout row
    ALWAYS_ON_KEY=""
    ALWAYS_ON_PARTS=""
    if [ -n "${DJB_SELFTEST_NO_REUSE:-}" ]; then
        return 0
    fi
    if ! command -v drive_key >/dev/null 2>&1; then
        echo "  ${kind} ${name}: not consulted — no drive-verdict reader in this shell; running it${suffix}"
        return 0
    fi
    if ! always_on__listing; then
        echo "  ${kind} ${name}: not consulted — the measured tree could not be read; running it${suffix}"
        return 0
    fi
    # ONE SHAPE, TWO KEY BUILDERS. A drive's key is built from its `# drives:`
    # declaration; a product leg has no such line and declares `inputs:`/`env:`
    # in its own header instead. Both print `ok <schema>:<digest> <parts>`, so
    # everything below this line reads one grammar.
    case "$name" in
    local:*)
        # `local:` IS TWO POPULATIONS AND THEY KEY DIFFERENTLY. A product LEG
        # declares `inputs:`/`env:` in its own header and `local_leg_key` reads
        # them. A product DRIVE has neither, and it cannot borrow `drive_key`:
        # that key REQUIRES a `drive_preamble.sh` beside the drive file
        # (`scripts/gate_ledger.sh`), which is true of `scripts/tests/` and of
        # `deploy/tests/` and false of `scripts/local/drives/` by construction.
        # So a drawer drive is NOT KEYED AND NOT BANKED — it runs on every gate
        # — and this branch says that out loud rather than handing its name to
        # the LEG key, which is a key for a different member the review that found it).
        if command -v selftest_registered_drives >/dev/null 2>&1 &&
            selftest_registered_drives 2>/dev/null |
            awk -v n="$name" '$0 == n { found = 1 } END { exit(found ? 0 : 1) }'; then
            echo "  ${kind} ${name}: not consulted — a product drive carries no drive key (no preamble beside it); it runs on every gate${suffix}"
            return 0
        fi
        keyout=$(local_leg_key "$name" "$ALWAYS_ON_LISTING") || true
        ;;
    *) keyout=$(drive_key "$file" "$ALWAYS_ON_TREE" "$ALWAYS_ON_LISTING") || true ;;
    esac
    case "$keyout" in
    "ok ${DRIVE_KEY_SCHEMA}:"*)
        ALWAYS_ON_KEY=$(printf '%s\n' "$keyout" | awk '{print $2}')
        ALWAYS_ON_PARTS=$(printf '%s\n' "$keyout" | awk '{print $3}')
        ;;
    *)
        echo "  ${kind} ${name}: not consulted — ${keyout#err }; running it${suffix}"
        return 0
        ;;
    esac
    row=$(drive_ledger_lookup "$ALWAYS_ON_KEY") || row=""
    if [ -n "$row" ]; then
        echo "  ${kind} ${name}: REUSED from ${ALWAYS_ON_KEY} (banked $(printf '%s\n' "$row" | awk '{print $4}'))${suffix}"
        ALWAYS_ON_GREEN=$((ALWAYS_ON_GREEN + 1))
        return 1
    fi
    return 0
}

ALWAYS_ON_GREEN=0
ALWAYS_ON_RED=0
ALWAYS_ON_CANNOT=0
ALWAYS_ON_RED_NAMES=""
ALWAYS_ON_CANNOT_NAMES=""
ALWAYS_ON_WALL=0

# always_on__run <kind> <name> [<reason suffix>] — consult, run, count, bank.
always_on__run() {
    local kind=$1 name=$2 suffix=${3:-} file out rc t0 took
    file=$(always_on__drive_file "$name")
    if [ ! -f "$file" ]; then
        echo "  ${kind} ${name}: could not look — ${file} is not in this tree${suffix}"
        ALWAYS_ON_CANNOT=$((ALWAYS_ON_CANNOT + 1))
        ALWAYS_ON_CANNOT_NAMES="${ALWAYS_ON_CANNOT_NAMES} ${name}"
        return 0
    fi
    always_on__consult "$kind" "$name" "$file" "$suffix" || return 0
    out=$(mktemp "${TMPDIR:-/tmp}/djb-always-on-member.XXXXXX") || {
        echo "  ${kind} ${name}: could not look — no scratch file for its output${suffix}"
        ALWAYS_ON_CANNOT=$((ALWAYS_ON_CANNOT + 1))
        ALWAYS_ON_CANNOT_NAMES="${ALWAYS_ON_CANNOT_NAMES} ${name}"
        return 0
    }
    t0=$(date +%s)
    rc=0
    # UNPIPED, TO A FILE, AND READ AFTERWARDS — the rule this whole gate is
    # written by: a reader in the pipeline would replace the member's exit
    # status with its own.
    ("$file") >"$out" 2>&1 || rc=$?
    took=$(($(date +%s) - t0))
    ALWAYS_ON_WALL=$((ALWAYS_ON_WALL + took))
    echo "  ${kind} ${name}: exit ${rc} (${took}s)${suffix}"
    if [ "$rc" = "0" ]; then
        ALWAYS_ON_GREEN=$((ALWAYS_ON_GREEN + 1))
        if [ -n "$ALWAYS_ON_KEY" ] && [ -z "${DJB_GATE_LEGS_DRY:-}" ]; then
            drive_ledger_record "$ALWAYS_ON_KEY" "$name" "$took" "$ALWAYS_ON_TREE" \
                "$ALWAYS_ON_PARTS" || true
        fi
    else
        # THE OUTPUT IS REPLAYED, and only on a non-zero: a red member nobody
        # can read is a red nobody can fix, and a green one's transcript would
        # bury the banner this leg exists to print.
        sed 's/^/      | /' "$out"
        if [ "$rc" = "2" ]; then
            ALWAYS_ON_CANNOT=$((ALWAYS_ON_CANNOT + 1))
            ALWAYS_ON_CANNOT_NAMES="${ALWAYS_ON_CANNOT_NAMES} ${name}"
        else
            ALWAYS_ON_RED=$((ALWAYS_ON_RED + 1))
            ALWAYS_ON_RED_NAMES="${ALWAYS_ON_RED_NAMES} ${name}"
        fi
    fi
    rm -f "$out"
    return 0
}

# always_on_leg — the leg body. Exit 0 clean · 1 a member was red · 2 a member
# could not look, or the durations file names a member this gate does not have.
always_on_leg() {
    local path declared declared_names drives legs known name secs needs where
    local measured="" rc=0 t0 census_rc=0
    t0=$(date +%s)
    ALWAYS_ON_GREEN=0
    ALWAYS_ON_RED=0
    ALWAYS_ON_CANNOT=0
    ALWAYS_ON_RED_NAMES=""
    ALWAYS_ON_CANNOT_NAMES=""
    ALWAYS_ON_WALL=0
    ALWAYS_ON_LISTING=""
    ALWAYS_ON_TREE=""

    drives=$(always_on__drives) || {
        echo "!! the always-on leg could not derive the drive set it may run." >&2
        return 2
    }

    # --- half one: the DECLARED cross-app censuses ---------------------------
    # THROUGH `gate_capture`, NOT A BARE `$( )`, and the difference is the cause
    # line below. A command substitution is a SUBSHELL: a `GATE_LAST_REFUSAL`
    # the callee records inside one dies with it, so the banner would print
    # whatever refusal this process saw LAST — a stale sentence about some other
    # leg, which is worse than none. `gate_capture` replays the callee's stderr
    # where it would have printed (so "see above" still has its above) and
    # carries its first `!!` line out as the cause.
    gate_capture declared loop_scope__declared_censuses \
        "${DJB_SELFTEST_DRIVES_DIR:-scripts/tests}" 'test_*.sh' || census_rc=$?
    if [ "$census_rc" != "0" ]; then
        gate_cause
        echo "!! the always-on leg COULD NOT READ the drives that declare themselves" >&2
        echo "   cross-app — see above. Nothing was judged: a drive this could not read" >&2
        echo "   is one the leg would skip as if it had declared nothing." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        return 2
    fi
    declared_names=$(printf '%s\n' "$declared" | awk -F'	' 'NF {
        n = $1
        sub(/^.*\/test_/, "", n)
        sub(/\.sh$/, "", n)
        print n
    }')
    if [ -z "$declared" ]; then
        echo "  always-on (declared): no drive declares itself cross-app"
    fi

    # --- half two: the MEASURED members under the floor ----------------------
    path=$(always_on_durations_path)
    if always_on__read_durations "$path"; then
        echo "  always-on (measured): ${path} — measured_at ${ALWAYS_ON_MEASURED_AT:-unstated} on ${ALWAYS_ON_MACHINE:-an unstated machine}, floor ${ALWAYS_ON_FLOOR}s"
        legs=""
        [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ] || legs=$(always_on__legs) || legs=""
        known=$(
            printf '%s\n' "$legs" | awk 'NF { print $2 }'
            printf '%s\n' "$drives"
            # THE ONE MEMBER THAT IS NEITHER A LEG NOR A FILE UNDER
            # scripts/tests/, stated here rather than derived because it cannot
            # be: `house-rules-engine` is the canary self-test, run as the
            # selftest leg's first member and timed like every other one, so it
            # appears in the measurement — and it has no drive file, so it can
            # never join the set this leg runs. `selftest_shard_takes` names it
            # the same way and for the same reason.
            [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ] || printf 'house-rules-engine\n'
        )
        # A NAME THIS GATE DOES NOT HAVE IS EXIT 2 AND NEVER A SHRUG. A typo in
        # the file would otherwise drop a member out of the always-on set in
        # silence, which is the one way this whole mechanism can lie.
        while read -r name secs; do
            [ -n "$name" ] || continue
            if ! printf '%s\n' "$known" | always_on__names_has "$name"; then
                echo "!! ${path} records a member this gate does not have: '${name}'." >&2
                echo "   That file is a MEASUREMENT of this gate's own legs and drives, so a" >&2
                echo "   name nothing announces is a typo or a member that was removed — and" >&2
                echo "   either way some OTHER member is silently missing from the set." >&2
                echo "   Re-measure with ./scripts/check.sh --store-durations." >&2
                return 2
            fi
        done <"$ALWAYS_ON_TABLE"

        # THE FULL-ONLY LEGS, NAMED AND NOT RUN. The reason is in this fence's
        # header; it is printed rather than assumed because a member missing
        # from a set nobody prints is a member nobody misses.
        if [ -n "$legs" ]; then
            printf '%s\n' "$legs" | while read -r where name; do
                [ "$where" = "full" ] || continue
                # A PRODUCT LEG IS NOT ONE OF THESE, and the reason below is
                # not true of it: its body is a file, not a function defined
                # past this block. Half three prints its own line, naming its
                # own reason — its header said `tier: full`.
                case "$name" in local:*) continue ;; esac
                secs=$(always_on__recorded "$name")
                echo "  always-on (measured): leg ${name} stays full-only — its body is defined below the --loop block's own exit, so this leg cannot call it${secs:+ (${secs} s recorded)}"
            done
        fi

        # THE DRIVES. Derived, per member, with the reason for every exclusion
        # printed beside it.
        for name in $drives; do
            if printf '%s\n' "$declared_names" | always_on__names_has "$name"; then
                # Already in the declared half — it runs there, unconditionally,
                # whatever its price. Naming it twice would run it twice.
                continue
            fi
            secs=$(always_on__recorded "$name")
            if [ -z "$secs" ]; then
                echo "  always-on (measured): ${name} unmeasured — joins after the next --store-durations"
                continue
            fi
            needs=$(always_on__unit_needs "$name")
            case ",${needs}," in
            *,network,*)
                echo "  always-on (measured): ${name} out by declaration — its unit needs network, and a network hiccup must not redden a per-rung run"
                continue
                ;;
            esac
            if [ "$secs" -ge "$ALWAYS_ON_FLOOR" ]; then
                echo "  always-on (measured): ${name} above the floor (${secs} s)"
                continue
            fi
            measured="${measured} ${name}"
        done
        if [ -z "$measured" ]; then
            echo "  always-on (measured): no member is under the ${ALWAYS_ON_FLOOR}s floor"
        else
            echo "  always-on (measured): joins this loop —${measured}"
        fi
    else
        echo "  always-on (measured): no durations file — the first --store-durations writes it"
        measured=""
    fi

    # --- half three: the PRODUCT LEGS whose tier reaches this mode -----------
    #
    # SELECTED HERE AND RUN BELOW, like the other two halves, and for the same
    # reason: the reasons a member is out are printed beside its name. A
    # product leg's tier is DECLARED rather than measured (its price is the
    # product's, and this file has never measured it), and its `touches:` is
    # the narrowed mode's own permission to skip it — the full gate runs it
    # whatever it touches.
    local locals="" lname ltouches ltier lchanged ltou
    lchanged=$(local_legs_changed_files)
    while read -r where lname; do
        [ -n "$lname" ] || continue
        case "$lname" in local:*) ;; *) continue ;; esac
        [ "$where" = "loop" ] || {
            echo "  always-on (local): ${lname} stays full-only — its header declares tier: full"
            continue
        }
        ltouches=$(local_legs_field "$lname" 6)
        if [ -n "$ltouches" ]; then
            ltou=0
            local_legs_touched "$ltouches" "$lchanged" || ltou=$?
            if [ "$ltou" = "1" ]; then
                echo "  always-on (local): ${lname} SKIPPED — its touches (${ltouches}) matched nothing this run changed; the full gate runs it regardless"
                continue
            fi
        fi
        locals="${locals} ${lname}"
    done <<EOF
$(always_on__legs 2>/dev/null || true)
EOF
    if [ -n "$locals" ]; then
        echo "  always-on (local): joins this loop —${locals}"
    fi

    # --- run them ------------------------------------------------------------
    if [ -n "$declared" ]; then
        while IFS="$(printf '\t')" read -r ALWAYS_ON_PATH ALWAYS_ON_REASON; do
            [ -n "$ALWAYS_ON_PATH" ] || continue
            name=$(basename "$ALWAYS_ON_PATH" .sh)
            always_on__run census "${name#test_}" " — ${ALWAYS_ON_REASON}"
        done <<EOF
${declared}
EOF
    fi
    for name in $measured; do
        always_on__run member "$name"
    done
    for name in $locals; do
        # THE LOOP HALF PROVISIONS TOO, and it did not: `always_on__run` is the
        # shared member runner and knows nothing about units, so a loop-tier
        # leg of a unit with a `_provision-<unit>.sh` ran UNPROVISIONED under
        # every `--loop` while the full gate brought its organs up. One unit,
        # two answers, and the cheap one was the wrong one.
        local lprc=0
        local_legs_provision "$(local_legs_field "$name" 2)" || lprc=$?
        if [ "$lprc" != "0" ]; then
            echo "  local ${name}: could not look — unit '$(local_legs_field "$name" 2)' did not provision"
            ALWAYS_ON_CANNOT=$((ALWAYS_ON_CANNOT + 1))
            ALWAYS_ON_CANNOT_NAMES="${ALWAYS_ON_CANNOT_NAMES} ${name}"
            continue
        fi
        always_on__run local "$name"
    done

    if [ -n "$ALWAYS_ON_LISTING" ]; then
        rm -f "$ALWAYS_ON_LISTING"
        ALWAYS_ON_LISTING=""
    fi
    [ -z "$ALWAYS_ON_TABLE" ] || rm -f "$ALWAYS_ON_TABLE"
    ALWAYS_ON_TABLE=""
    echo "  always-on: ${ALWAYS_ON_GREEN} member(s) green · ${ALWAYS_ON_RED} red · ${ALWAYS_ON_CANNOT} could-not-look (${ALWAYS_ON_WALL}s of member wall, $(($(date +%s) - t0))s of leg)"
    if [ "$ALWAYS_ON_CANNOT" -gt 0 ]; then
        echo "!! COULD NOT LOOK:${ALWAYS_ON_CANNOT_NAMES}" >&2
        [ "$ALWAYS_ON_RED" = "0" ] || echo "!! and RED:${ALWAYS_ON_RED_NAMES}" >&2
        echo "   2 outranks 1: a member that could not run its cases has not cleared" >&2
        echo "   them. This is the SAME member the bank runs — meeting it here is the" >&2
        echo "   whole point of the leg; meeting it at the bank costs a merge." >&2
        rc=2
    elif [ "$ALWAYS_ON_RED" -gt 0 ]; then
        echo "!! RED:${ALWAYS_ON_RED_NAMES}" >&2
        echo "   A full-only member is red. Before this leg existed that red waited for" >&2
        echo "   the next bank — seven of nine failed banks in one cycle were exactly" >&2
        echo "   that. Read the first name first." >&2
        rc=1
    fi
    return "$rc"
}
# >>> member-durations >>>
# EVERY MEMBER'S SECONDS, KEPT — the measurement the `--loop` always-on set is
# derived from, and the announcement that keeps that set honest between
# measurements.
#
# TWO JOBS, ONE CLOCK. Legs are timed by `leg()` above and drives by
# `selftest_member_end` inside the selftest fence; both hand their seconds here
# rather than each growing a writer, so there is one accumulator and one
# comparison and no second thing to keep in step.
#
#   (1) ACCUMULATE. Under `--store-durations` at the full mode the whole set is
#       written out at the end of the run, in one place, once.
#   (2) ANNOUNCE A CROSSING. On EVERY full run a member whose live seconds sit
#       on the other side of the floor from its recorded seconds says so. The
#       file itself does not move — only a measurement run writes it — so the
#       sentence is the warning and the next `--store-durations` is the act. A
#       member that silently grew past the floor and went on being run by every
#       loop is the one failure mode a derived set has, and this is what makes
#       it loud.
#
# ONLY ON A FULL RUN. A `--loop` runs a fraction of the set and a `--leg` runs
# one unit of it; seconds from either would be a measurement of a subset
# written into the file the whole set is derived from.
GATE_MEMBER_TIMES=""
GATE_MEMBER_DURATIONS_READ=""
gate_member_record() {
    local name=$1 secs=$2 recorded
    [ -z "$MODE" ] || return 0
    [ -z "$GATE_LEG_UNIT" ] || return 0
    if [ -z "$GATE_MEMBER_TIMES" ]; then
        GATE_MEMBER_TIMES=$(mktemp "${TMPDIR:-/tmp}/djb-gate-member-times.XXXXXX") || {
            GATE_MEMBER_TIMES=""
            return 0
        }
    fi
    printf '%s %s\n' "$name" "$secs" >>"$GATE_MEMBER_TIMES"
    if [ -z "$GATE_MEMBER_DURATIONS_READ" ]; then
        GATE_MEMBER_DURATIONS_READ=1
        always_on__read_durations "$(always_on_durations_path)" || true
    fi
    recorded=$(always_on__recorded "$name")
    [ -n "$recorded" ] || return 0
    if [ "$secs" -ge "$ALWAYS_ON_FLOOR" ] && [ "$recorded" -lt "$ALWAYS_ON_FLOOR" ]; then
        echo "  member ${name}: ${secs} s live vs ${recorded} s recorded — above the loop floor;"
        echo "                  leaves the always-on set at the next --store-durations"
    elif [ "$secs" -lt "$ALWAYS_ON_FLOOR" ] && [ "$recorded" -ge "$ALWAYS_ON_FLOOR" ]; then
        echo "  member ${name}: ${secs} s live vs ${recorded} s recorded — below the loop floor;"
        echo "                  joins the always-on set at the next --store-durations"
    fi
    return 0
}

# gate_member_durations_write — the file, rewritten from this run's own clock.
# Exit 0 written · 1 there was nothing to write or the path is not writable.
gate_member_durations_write() {
    local path=$1 tree=$2 tmp
    [ -n "$GATE_MEMBER_TIMES" ] && [ -s "$GATE_MEMBER_TIMES" ] || return 1
    tmp=$(mktemp "${TMPDIR:-/tmp}/djb-gate-member-json.XXXXXX") || return 1
    {
        printf '{\n'
        # `tree:` IS PART OF THE VALUE, AND IT IS LOAD-BEARING TWICE. It says
        # what the forty characters after it are — a git TREE sha, not a
        # commit — and it is what keeps `detect-secrets`' Hex High Entropy
        # String plugin from reading a public tree sha as a credential: the
        # plugin takes the whole quoted value and asks whether it is hex, so a
        # bare sha here reds the `--loop` secrets leg on every rung that
        # re-measures, and JSON has no comment to hang a
        # `pragma: allowlist secret` on. Measured, not guessed: this leg's own
        # first run reddened `secrets_scan` and `secrets_baseline_guard` on
        # exactly that line.
        printf '  "measured_at": "tree:%s",\n' "$tree"
        printf '  "machine": "%s",\n' "$(uname -sr)"
        printf '  "members": {\n'
        # SORTED, AND THE LAST MEMBER CARRIES NO COMMA. A sorted file is a file
        # two measurements can be diffed against each other; an unsorted one
        # re-orders itself on every run and every diff is the whole file.
        LC_ALL=C sort -u "$GATE_MEMBER_TIMES" | awk '
            { name[NR] = $1; secs[NR] = $2 }
            END {
                for (i = 1; i <= NR; i++) {
                    printf "    \"%s\": %s%s\n", name[i], secs[i], (i < NR ? "," : "")
                }
            }
        '
        printf '  }\n'
        printf '}\n'
    } >"$tmp" || {
        rm -f "$tmp"
        return 1
    }
    cat "$tmp" >"$path" || {
        rm -f "$tmp"
        return 1
    }
    rm -f "$tmp"
    return 0
}
# <<< member-durations <<<

# <<< always-on-leg <<<

# gate_list_legs — validate the table against the file, then print it. Exit 0
# clean, 2 on any disagreement: a listing that quietly omitted a leg would send
# a runner home believing it had run the gate.
gate_list_legs() {
    local announced unit needs shards legs leg seen="" unpaired drives
    announced=$(gate_announced_full_legs)
    if [ -z "$announced" ]; then
        echo "!! --list-legs found NO column-zero leg call sites in scripts/check.sh — the listing has lost its subject." >&2
        return 2
    fi
    if [ "$announced" != "$FULL_LEGS" ]; then
        echo "!! --list-legs: FULL_LEGS and the legs a full run announces disagree." >&2
        echo "   announced: ${announced}" >&2
        echo "   FULL_LEGS: ${FULL_LEGS}" >&2
        echo "   A leg the ledger does not know about is a leg every banked verdict" >&2
        echo "   under-reports. Fix FULL_LEGS (or the call site), not this message." >&2
        return 2
    fi
    drives=$(selftest_registered_drives)
    unpaired=$(gate_unpaired_legs)
    if [ -n "$unpaired" ]; then
        echo "!! --list-legs: a leg is announced whose body is not run through gate_run_body:" >&2
        printf '   %s\n' $unpaired >&2
        echo "   The gate announces it on every run, no verdict row names it and no" >&2
        echo "   runner is ever handed it — it is invisible to this listing and to the" >&2
        echo "   dry sequence alike. Put the body in a gate_leg_<name> function and" >&2
        echo "   call it \`gate_run_body <name> gate_leg_<name>\`." >&2
        return 2
    fi
    while IFS='	' read -r unit needs shards legs; do
        [ -n "$unit" ] || continue
        if [ -z "$needs" ] || [ -z "$shards" ] || [ -z "$legs" ]; then
            echo "!! --list-legs: unit '${unit}' is missing its needs/shards/legs declaration." >&2
            echo "   \`needs\` is a declaration and an empty one says nothing; write \`none\`." >&2
            return 2
        fi
        for leg in $(printf '%s' "$legs" | tr ',' ' '); do
            # A MEMBER IS A LEG OR A DRIVE, and both populations are derived from
            # this file: the legs from the column-zero `leg` call sites, the
            # drives from the column-zero `./scripts/tests/test_<name>.sh` lines
            # the selftest leg walks. A shardable unit names its shard population
            # so a reader of the listing can see what one shard would hold.
            case ",${FULL_LEGS},|$(printf '%s' "$drives" | tr '\n' '|')|" in
            *",${leg},"* | *"|${leg}|"*) ;;
            *)
                echo "!! --list-legs: unit '${unit}' names '${leg}', which is neither a leg a full run announces nor a drive this file registers." >&2
                return 2
                ;;
            esac
            case " $seen " in
            *" $leg "*)
                echo "!! --list-legs: leg '${leg}' is in more than one unit — a leg run twice by two runners is not a partition." >&2
                return 2
                ;;
            esac
            seen="${seen}${seen:+ }${leg}"
        done
    done <<EOF
$(printf '%s' "$GATE_UNIT_ROWS")
EOF
    for leg in $(printf '%s' "$FULL_LEGS" | tr ',' ' '); do
        case " $seen " in
        *" $leg "*) ;;
        *)
            echo "!! --list-legs: leg '${leg}' is in NO unit — no runner would ever be handed it." >&2
            return 2
            ;;
        esac
    done
    # THE SAME QUESTION, ONE TIER DOWN: a drive in no unit is a drive no shard
    # would ever run, which is how a whole refusal set goes quiet while the leg
    # stays green.
    for leg in $drives; do
        case " $seen " in
        *" $leg "*) ;;
        *)
            echo "!! --list-legs: drive '${leg}' is in NO unit — no shard would ever be handed it." >&2
            return 2
            ;;
        esac
    done
    printf '%s' "$GATE_UNIT_ROWS"
    return 0
}

if [ -n "$GATE_LIST_LEGS" ]; then
    # ABOVE THE LEASE, THE LOCK AND THE SLOT, and that position is asserted by
    # `scripts/tests/test_list_legs.sh` rather than described here: a listing
    # that queued behind somebody else's full gate would be useless to the thing
    # that wants it (a CI job whose whole purpose is to find out what to run).
    set +e
    gate_list_legs
    GATE_LIST_LEGS_RC=$?
    set -e
    exit "$GATE_LIST_LEGS_RC"
fi

# --- RUNNING ONE UNIT --------------------------------------------------------
#
# WHAT `--leg <unit>` IS, AND WHAT IT IS NOT. It is the full gate's legs, in the
# full gate's order, with every leg outside the named unit neither announced nor
# run. It is NOT a smaller full gate: it takes no machine lease, no checkout
# lock and no sanction, and it records nothing in any of the three ledgers,
# because a partition of a run vouches for no tree (`gate_ledger.sh`, property
# 2). A runner handed every unit has between them run the whole gate; each one
# on its own has run a part and says so.
#
# NO SANCTION, AND THE ARGUMENT IS rung-execution §3's. The sanction exists
# because a full gate is the most expensive thing on this machine and every
# other full gate queues behind it. A unit takes no lease, so nothing queues
# behind it, and its cost is the cost of the part somebody asked for. That is
# the same shape `--loop` and `--census` already have, and it is why the mode
# normalises to `MODE="--leg"` rather than to the full mode: every guard in this
# file that reads `MODE` for emptiness is asking "is this the run that banks a
# verdict for a tree", and the honest answer here is no.
#
# THE MEMBERSHIP TEST IS THE LISTING'S OWN. The unit and its legs come out of
# `gate_list_legs` — the same validated table `--list-legs` prints, run here so
# a unit run refuses for a broken table exactly as the listing does, and so
# there is no second reading of the unit declarations to keep in step.
if [ "$MODE" = "--leg" ]; then
    if [ -z "$GATE_LEG_UNIT" ]; then
        echo "!! --leg needs a unit: ./scripts/check.sh --leg <unit>" >&2
        echo "   The units are the gate's own and ./scripts/check.sh --list-legs is what" >&2
        echo "   names them. Nothing was judged." >&2
        exit 2
    fi
    set +e
    GATE_LEG_TABLE=$(gate_list_legs 2>&1)
    GATE_LEG_TABLE_RC=$?
    set -e
    if [ "$GATE_LEG_TABLE_RC" != "0" ]; then
        printf '%s\n' "$GATE_LEG_TABLE" >&2
        echo "!! --leg ${GATE_LEG_UNIT}: the unit table does not validate, so this gate does" >&2
        echo "   not know what one unit is. Nothing was judged." >&2
        exit "$GATE_LEG_TABLE_RC"
    fi
    GATE_LEG_UNIT_SHARDS=$(printf '%s\n' "$GATE_LEG_TABLE" | awk -F'\t' -v u="$GATE_LEG_UNIT" '$1 == u { print $3 }')
    GATE_LEG_UNIT_MEMBERS=$(printf '%s\n' "$GATE_LEG_TABLE" | awk -F'\t' -v u="$GATE_LEG_UNIT" '$1 == u { print $4 }')
    if [ -z "$GATE_LEG_UNIT_MEMBERS" ]; then
        echo "!! --leg '${GATE_LEG_UNIT}': no such unit." >&2
        echo "   The units are the gate's own, and ./scripts/check.sh --list-legs is what" >&2
        echo "   names them — never a list typed into a runner:" >&2
        printf '%s\n' "$GATE_LEG_TABLE" | awk -F'\t' 'NF { print "     " $1 }' >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
        exit 2
    fi
    GATE_LEG_UNIT_LEGS=",${GATE_LEG_UNIT_MEMBERS},"
    if [ -n "$GATE_SHARD_GIVEN" ]; then
        # A SHARD OF AN INDIVISIBLE UNIT IS A REFUSAL AND NEVER A SMALLER RUN.
        # The `shards` field is the listing's answer to "does this unit's body
        # take a k/N", and a runner that split one which does not would be told
        # it had run a part of something with no parts.
        if [ "$GATE_LEG_UNIT_SHARDS" != "N-capable" ]; then
            echo "!! --leg ${GATE_LEG_UNIT} --shard ${GATE_SHARD}: that unit is indivisible (shards: ${GATE_LEG_UNIT_SHARDS})." >&2
            echo "   ./scripts/check.sh --list-legs carries the shards field of every unit and" >&2
            echo "   only an N-capable one takes a k/N." >&2
            echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
            exit 2
        fi
        if ! [[ $GATE_SHARD =~ ^([0-9]+)/([0-9]+)$ ]]; then
            echo "!! --shard '${GATE_SHARD}' is not a k/N pair of integers." >&2
            echo "   The form is 1-based, as the listing's grammar is: --shard 1/3 is the" >&2
            echo "   first of three. A pair this gate cannot parse is never a smaller run." >&2
            echo "   Nothing was judged." >&2
            exit 2
        fi
        GATE_SHARD_K=${BASH_REMATCH[1]}
        GATE_SHARD_N=${BASH_REMATCH[2]}
        if [ "$GATE_SHARD_N" -lt 1 ] || [ "$GATE_SHARD_K" -lt 1 ] || [ "$GATE_SHARD_K" -gt "$GATE_SHARD_N" ]; then
            echo "!! --shard ${GATE_SHARD} is outside 1..${GATE_SHARD_N} of ${GATE_SHARD_N}." >&2
            echo "   Every k in 1..N runs a part and the N parts are the whole; a k outside" >&2
            echo "   that range names a part of the unit that does not exist." >&2
            echo "   Nothing was judged." >&2
            exit 2
        fi
    fi
    if [ -n "$GATE_PASSES_GIVEN" ]; then
        # ONE PASS IS A DROPPED BELT, SO IT IS REFUSED EVERYWHERE THE BELT HAS
        # NO REPLACEMENT. The four refusals below are ordered from the most
        # specific reason to the least, so the sentence a runner reads names
        # what is actually wrong with its argv rather than the first rule the
        # argv happens to break.
        #
        # BEFORE THE `--store-durations` BLOCK, and the order is the criterion:
        # `--passes 1 --store-durations` is two ways to say pass 2 is not run,
        # and if the durations block ran first the runner would be told a shard
        # times a part of the suite — true, and not the thing it got wrong.
        case "$GATE_PASSES" in
        1 | 2) ;;
        *)
            echo "!! --passes '${GATE_PASSES}': the suite leg runs 1 or 2 whole passes." >&2
            echo "   2 is the default and the belt: pass 2 proves the suite left nothing" >&2
            echo "   behind for itself. 1 drops it, and is legal only on a shard whose" >&2
            echo "   proof runs elsewhere. A count this gate cannot parse is never a run." >&2
            echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
            exit 2
            ;;
        esac
        if [ "$GATE_PASSES" = "1" ]; then
            case "$GATE_LEG_UNIT_LEGS" in
            *,pytest-x2,*) ;;
            *)
                echo "!! --passes 1 on unit '${GATE_LEG_UNIT}': that unit runs no suite." >&2
                echo "   The pass count is the suite leg's own, and a unit with no suite has" >&2
                echo "   no passes to drop one of." >&2
                echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
                exit 2
                ;;
            esac
            if [ -n "$GATE_STORE_DURATIONS" ]; then
                echo "!! --passes 1 with --store-durations: two ways to say pass 2 is not run." >&2
                echo "   A measurement run already stops after pass 1, and it vouches for" >&2
                echo "   nothing; --passes 1 is a VERDICT over one pass whose belt runs on" >&2
                echo "   another box. One argv cannot be both." >&2
                echo "   Nothing was judged." >&2
                exit 2
            fi
            if [ -z "$GATE_SHARD" ]; then
                echo "!! --passes 1 without --shard: the whole-suite two-pass belt is this unit's own;" >&2
                echo "   one pass is legal only for a shard whose proof runs elsewhere." >&2
                echo "   Under ./scripts/pm_push.sh --bank --on-boxes N that elsewhere is the" >&2
                echo "   acceptance box's whole-suite two passes under one seed, composed into the" >&2
                echo "   verdict row's leak-proof= field; a whole unit asking for one pass is" >&2
                echo "   asking to drop the belt and name no replacement." >&2
                echo "   Nothing was judged: no lease was taken, no slot, no leg was run." >&2
                exit 2
            fi
        fi
        # `--passes 2` IS THE DEFAULT SPELLED OUT, AND IT PRINTS NOTHING NEW.
        # Normalised to empty here so every site below has one question to ask
        # — "was one pass asked for?" — and so a runner that spells the default
        # gets a transcript byte-identical to one that did not. Two spellings
        # of one run that differ in their output are two runs to compare.
        if [ "$GATE_PASSES" = "2" ]; then
            GATE_PASSES=""
        fi
        # THE ONE DECISION SITE for what this run's transcript calls itself.
        # Everything downstream prints a variable; nothing downstream decides.
        if [ "$GATE_PASSES" = "1" ]; then
            GATE_PASSES_RUN="the one pass runs"
            GATE_PASSES_CARRY="the one pass carries"
            GATE_PASSES_LEG_TEXT="pytest (ONCE — --passes 1, under ONE seed and ONE OF THIS MACHINE'S PYTEST SLOTS; the second run that would prove this one left nothing behind is the acceptance box's)"
        fi
    fi
    if [ -n "$GATE_STORE_DURATIONS" ]; then
        # IT IS A MEASUREMENT OF THE WHOLE, so it refuses the two shapes that
        # would make it a measurement of a part: a shard (a third of the suite
        # would be written as if it were the file), and a unit that runs no
        # suite at all (there would be nothing to time).
        case "$GATE_LEG_UNIT_LEGS" in
        *,pytest-x2,*) ;;
        *)
            echo "!! --store-durations on unit '${GATE_LEG_UNIT}': that unit runs no suite." >&2
            echo "   The durations file is what the pytest split balances by, and only the" >&2
            echo "   unit that runs the suite can measure it." >&2
            exit 2
            ;;
        esac
        if [ -n "$GATE_SHARD" ]; then
            echo "!! --store-durations with --shard ${GATE_SHARD}: a shard times a PART of the suite." >&2
            echo "   Writing that file from one shard would describe 1/${GATE_SHARD_N} of the" >&2
            echo "   collection as if it were all of it, and the next split would balance by it." >&2
            echo "   Nothing was judged." >&2
            exit 2
        fi
    fi
    GATE_LEG_UNIT_NEEDS=$(printf '%s\n' "$GATE_LEG_TABLE" | awk -F'\t' -v u="$GATE_LEG_UNIT" '$1 == u { print $2 }')
    # THE `composed-of:` LINE IS THIS RUN'S, NOT THE LISTING'S, and under
    # `--passes 1` the two differ by design. A row downstream that read
    # `pytest-x2` off a one-pass shard could not tell it from a two-pass one,
    # so the member carries the count it ran in the seam grammar
    # `<leg>[/<passes>]` — absent means 2, which is why nothing changes for
    # every run that did not ask. The LISTING keeps four fields and no count
    # (`--list-legs` is the unit table; the pass count is a property of a RUN),
    # so this rewrite is display-only: `GATE_LEG_UNIT_MEMBERS` — what the
    # announcement filter and `GATE_LEG_UNIT_LEGS` read — is untouched.
    GATE_LEG_MEMBERS_SHOWN=",${GATE_LEG_UNIT_MEMBERS},"
    if [ "$GATE_PASSES" = "1" ]; then
        GATE_LEG_MEMBERS_SHOWN=${GATE_LEG_MEMBERS_SHOWN/,pytest-x2,/,pytest-x2\/1,}
    fi
    GATE_LEG_MEMBERS_SHOWN=${GATE_LEG_MEMBERS_SHOWN#,}
    GATE_LEG_MEMBERS_SHOWN=${GATE_LEG_MEMBERS_SHOWN%,}
    echo "- --leg ${GATE_LEG_UNIT}${GATE_SHARD:+ --shard ${GATE_SHARD}}${GATE_PASSES:+ --passes ${GATE_PASSES}}"
    echo "  needs:       ${GATE_LEG_UNIT_NEEDS} (a DECLARATION — the gate refuses at the leg, never here)"
    echo "  shards:      ${GATE_LEG_UNIT_SHARDS}"
    echo "  composed-of: ${GATE_LEG_MEMBERS_SHOWN}"
    echo "  This run takes NO machine lease, NO checkout lock and records NO verdict:"
    echo "  one unit of the gate vouches for no tree."
fi

# --- the --pr scope: the same derivation, a different fork point --------------
#
# THE SAME DERIVATION, ASKED A DIFFERENT QUESTION. `--loop` asks
# `loop_tier_own_apps` what the ACTIVE RUNG changed — merge-base with the local
# `main`, plus everything uncommitted. `--pr` asks the identical function what
# the PROPOSED CHANGE contains, by moving its fork point to the base the caller
# named (`SECRETS_SCAN_BASE_REF`, scripts/secrets_scan.sh). One derivation, one
# decision table, one closure walk, one set of refusals — and therefore one
# thing to keep in step rather than two.
#
# DERIVED HERE, ABOVE THE LEASE, and the position is the criterion rather than a
# tidiness: an impact map this gate cannot compute is exit 2, and a run that was
# never going to be legal must not first queue for the machine's one exclusive
# lease and the slot or slots its mode takes to find out (one for a `--loop` or
# a sanctioned full gate; every one of them for a bank). It is also why the scope
# PRINTS before any leg has run — a red gate still discloses the scope it graded
# at, which is the property the `--loop` banner has for the same reason.
#
# THE FORK POINT IS SET AROUND THE CALL AND NOWHERE ELSE. Everything later in
# this gate that asks the same question again — the supply-chain leg's own
# scan — is asking about the tree, not about the proposal, and gets the ordinary
# answer, because the variable is set on the one command and not exported.
#: The pytest flags the two passes are pointed at, space-joined — the shape
#: `$PARTITION_TARGETS` already has at those two call sites, and for the same
#: reason: it word-splits into arguments and is legitimately empty. No flag or
#: label in it can contain a space (they are app labels and repo-relative test
#: paths), which is what makes the string form honest here.
GATE_PR_PYTEST_ARGS=""
GATE_PR_COUNTS_DIR=""
if [ -n "$GATE_PR" ]; then
    # NOT A LEG, and deliberately not: `--pr` runs the full gate's legs, the
    # whole list of them and nothing else, and a reader comparing this run's
    # legs against FULL_LEGS must find them equal. This is a preflight that
    # prints, in the grammar the `--loop` scope block above prints in.
    echo "- --pr scope: ${GATE_PR_BASE_SHA}...HEAD, through the one changed-file derivation"
    gate_refuse_reset
    set +e
    SECRETS_SCAN_BASE_REF="$GATE_PR_BASE_SHA" loop_tier_own_apps
    PR_TIER_RC=$?
    set -e
    if [ "$PR_TIER_RC" != "0" ]; then
        gate_cause
        echo "!! --pr COULD NOT DERIVE THE IMPACT MAP — see above." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        echo "   The two pytest passes would have to be pointed at something, and an" >&2
        echo "   underived scope is not an empty one: pointing them at the always-on set" >&2
        echo "   would run LESS than this gate claims, silently." >&2
        echo "   Nothing was judged: no lease was taken, no slot, no leg ran a test." >&2
        exit 2
    fi
    # ONE LINE PER DECISION, BEFORE ANY OF IT IS ACTED ON — the same vocabulary
    # the `--loop` banner uses (touched · tests-only · closure · own · rule), so
    # a reader who learned one banner can read the other.
    echo "  scope   basis: ${GATE_PR_BASE_SHA}...HEAD"
    echo "          ${LOOP_TIER_BASIS}"
    echo "  scope   touched: ${LOOP_SCOPE_TOUCHED:--}"
    echo "  scope   tests-only: ${LOOP_SCOPE_TESTS_ONLY:--}"
    echo "  scope   closure: ${LOOP_SCOPE_WIDENED:--}"
    echo "  scope   own: ${LOOP_TIER_OWN_APPS:--}"
    echo "  scope   tier: all — the organ tier is NOT applied under --pr; every test in"
    echo "          the scope runs, organ-reaching or not, exactly as it does at push"
    echo "  scope   rule: ${LOOP_TIER_REASON}"
    if [ -n "$LOOP_SCOPE_NOTES" ]; then
        printf '%s\n' "$LOOP_SCOPE_NOTES" | sed 's/^/  note:   /'
    fi
    # The counts the pre-run banner prints come out of pytest itself
    # (apps/conftest.py's xdist controller seam), which needs somewhere to write
    # them. Only when there is actually a narrowing to describe: a `--pr` that
    # derived FULL runs the whole suite and has no scope to count.
    PR_ARGS_FILE=$(mktemp "${TMPDIR:-/tmp}/djb-pr-args.XXXXXX")
    loop_scope__pytest_args >"$PR_ARGS_FILE"
    while IFS= read -r PR_ARG; do
        [ -n "$PR_ARG" ] || continue
        GATE_PR_PYTEST_ARGS="${GATE_PR_PYTEST_ARGS}${GATE_PR_PYTEST_ARGS:+ }${PR_ARG}"
    done <"$PR_ARGS_FILE"
    rm -f "$PR_ARGS_FILE"
    if [ -n "$GATE_PR_PYTEST_ARGS" ]; then
        GATE_PR_COUNTS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/djb-pr-counts.XXXXXX")
        # REMOVED ON EVERY PATH, NOT ON THE GREEN ONE. The green path drops it
        # where the partition's verdict would have been banked, which is a line
        # only a run that got that far ever reaches: a red leg, a refused lease,
        # a SIGTERM all exit above it and leave the directory behind. So the
        # removal rides the EXIT trap instead — this one until the full-mode
        # branch installs its own (which carries the same removal), because the
        # lease acquisition between here and there can exit 2 on its own.
        trap 'rm -rf "$GATE_PR_COUNTS_DIR" 2>/dev/null || true' EXIT
        GATE_PR_PYTEST_ARGS="${GATE_PR_PYTEST_ARGS} --djb-scope-counts=${GATE_PR_COUNTS_DIR}"
    else
        echo "  scope   narrows NOTHING — both passes run the whole suite, as a bare full"
        echo "          gate does. An empty selection is printed, never silent."
    fi
fi


# --- one gate at a time, per checkout ------------------------------------
# The full gate's self-test PLANTS canary files into the real tree and restores
# them; the two pytest passes own the checkout's database. Anything else moving
# in the same checkout while that is happening reads a tree that is briefly a
# lie — which is exactly what happened twice: a 955-error double-suite, and
# a merge+commit landing mid-selftest. The prose rule (take turns)
# failed its own author both times, so it becomes a guard.
#
# PER CHECKOUT, deliberately: the lock lives in `git rev-parse --git-dir`, which
# is `.git` in the main checkout and `.git/worktrees/<name>` in a linked one. A
# gate in another worktree is a different tree, a different database and no
# business of this one — parallel rungs stay parallel. (Contrast the verdict
# ledger, which uses --git-common-dir on purpose: a verdict is a property of
# content, and content is shared.)
#
# Trust class, same as the ledger's: this is a local file, and `rm` is one
# command away. It stops casual drift, not sabotage.
#
# TWO WINDOWS ARE OPEN BY CONSTRUCTION, declared here so neither is mistaken for
# coverage:
#   1. --fast and --loop take NO lock. They only REFUSE while a full gate holds
#      one, so two --loop runs in the same checkout still overlap freely — they
#      plant nothing, and the pytest pass they share is the database's problem
#      rather than this file's.
#   2. `uv run python -m quality.gate --selftest` invoked DIRECTLY locks nothing
#      at all — the lock lives in this script, not in the engine — so a hand-run
#      self-test can plant canaries into a tree a full gate is reading. Run the
#      self-test through check.sh when anything else may be running.
GATE_LOCK=""

gate_lock_path() {
    local dir
    dir=$(git rev-parse --git-dir 2>/dev/null) || return 1
    case "$dir" in
    /*) ;;
    *) dir="$PWD/$dir" ;;
    esac
    printf '%s\n' "$dir/djb-gate-lock"
}

# The holder, or empty when there is none and none is stale. Prints nothing and
# clears the file when the recorded pid is gone: a dead holder's lock must never
# be a hang, because the commonest way to leave one is a killed gate, and an
# agent that has to be told to delete a file has been handed the friction back.
gate_lock_holder() {
    local path pid
    path=$(gate_lock_path) || return 0
    [ -f "$path" ] || return 0
    pid=$(awk 'NR==1{print $1}' "$path" 2>/dev/null || true)
    if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
        echo "  note: cleared a STALE gate lock — pid ${pid:-<none>} is not running ($path)" >&2
        rm -f "$path"
        return 0
    fi
    head -1 "$path"
}

gate_lock_refuse_if_held() {
    local held
    held=$(gate_lock_holder) || true
    [ -n "$held" ] || return 0
    echo "!! REFUSING: a FULL gate is already running in THIS checkout." >&2
    echo "   holder: $held  (pid mode started-utc)" >&2
    echo "   Its self-test plants canary files into this tree and restores them, and its" >&2
    echo "   pytest passes own this checkout's database. Running now would read a tree that" >&2
    echo "   is briefly not the tree, and could restore over your edits." >&2
    echo "   Wait for it, or run in your own worktree — another checkout is unaffected." >&2
    exit 2
}

gate_lock_acquire() {
    local path held
    path=$(gate_lock_path) || return 0 # no git dir: fail open; never block a gate
    # noclobber makes the create atomic, so two gates starting together cannot
    # both believe they won.
    if ! (set -o noclobber; printf '%s %s %s %s\n' \
        "$$" "full" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(hostname -s 2>/dev/null || echo host)" \
        >"$path") 2>/dev/null; then
        held=$(gate_lock_holder) || true
        if [ -n "$held" ]; then
            echo "!! REFUSING: a FULL gate is already running in THIS checkout." >&2
            echo "   holder: $held  (pid mode started-utc)" >&2
            echo "   Two full gates in one checkout plant canaries over each other." >&2
            exit 2
        fi
        # The holder was stale and gate_lock_holder cleared it; one retry.
        if ! (set -o noclobber; printf '%s %s %s %s\n' \
            "$$" "full" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            "$(hostname -s 2>/dev/null || echo host)" >"$path") 2>/dev/null; then
            echo "  no gate lock taken — $path could not be written; running anyway" >&2
            return 0
        fi
    fi
    GATE_LOCK=$path
    echo "- gate lock held for this checkout (pid $$) — --fast/--loop here will refuse until it clears"
}

gate_lock_release() {
    [ -n "$GATE_LOCK" ] || return 0
    local pid
    pid=$(awk 'NR==1{print $1}' "$GATE_LOCK" 2>/dev/null || true)
    if [ "$pid" = "$$" ]; then
        rm -f "$GATE_LOCK"
    fi
    GATE_LOCK=""
    return 0
}

# gate_run_start_unless_dry <tree> — see the call site for why this is the one
# guard the dry run needs.
gate_run_start_unless_dry() {
    if [ -n "${DJB_GATE_LEGS_DRY:-}" ]; then
        return 0
    fi
    gate_run_start "$1"
}

if [ "$MODE" = "" ]; then
    # THE ORDER OF THE THREE GUARDS IS LOAD-BEARING, and it is the same order on
    # every path a full gate can take. The machine-wide EXCLUSIVE LEASE is taken
    # FIRST and the per-checkout lock second, because the lease is the one that
    # WAITS: a gate that took the checkout lock and then queued would make every
    # `--fast`/`--loop` in its own checkout refuse for the whole wait, which is
    # the friction the lease exists to remove, one checkout over. The PYTEST
    # SLOT — the counting semaphore, which `--loop` also takes — comes LAST, at
    # the `pytest-x2` leg, so that no holder of a slot is ever waiting for the
    # lease and the deadlock cycle cannot be formed.
    #
    # `GATE_SLOT_LEASE_FIRST=1` is that order made mechanical rather than
    # remembered: `gate_slot_acquire` refuses, exit 2, if this run reaches a slot
    # without the lease in hand. See scripts/gate_lease.sh, THE LOCK ORDER.
    #
    # The EXIT trap is installed IMMEDIATELY AFTER the lease is taken and covers
    # all three releases — `gate_lock_release` and `gate_slot_release` are
    # no-ops while their variables are empty — so no line between here and the
    # first leg can exit holding any of them.
    GATE_SLOT_LEASE_FIRST=1
    set +e
    gate_lease_acquire
    LEASE_RC=$?
    set -e
    if [ "$LEASE_RC" != "0" ]; then
        # Could-not-look: this run judged nothing. Never a red tree.
        exit 2
    fi
    # `heartbeat_stop` is GUARDED because this trap is installed hundreds of
    # lines above the block that defines it: a full run that dies between here
    # and there must report its own cause, not `command not found`.
    #
    # AND IT DROPS BOTH COUNTS DIRECTORIES, because this trap is the only thing
    # every exit path goes through: the directory used to be removed where the
    # partition's verdict would have been banked, which a red leg, a refused
    # lease and a SIGTERM all exit above. `GATE_PR_COUNTS_DIR` is empty on every
    # run that is not `--pr`; `GATE_FULL_COUNTS_DIR` is empty until the
    # `pytest-x2` leg mints one, and only ever one of the two exists. The guards
    # are what keep `rm -rf ""` from being the thing that runs.
    trap 'RC=$?; trap "" PIPE; { command -v heartbeat_stop >/dev/null 2>&1 && heartbeat_stop; } || true; gate_lock_release; gate_slot_release; gate_lease_release; [ -z "${GATE_PR_COUNTS_DIR:-}" ] || rm -rf "$GATE_PR_COUNTS_DIR"; [ -z "${GATE_FULL_COUNTS_DIR:-}" ] || rm -rf "$GATE_FULL_COUNTS_DIR"; gate_run_finish "$RC" || true' EXIT
    gate_lock_acquire
    trap 'gate_run_killed' TERM INT HUP
    # Measured BEFORE the first leg reads a byte, so the key names the content
    # the gate actually saw. `|| true`: failing to measure costs a verdict,
    # never a gate run.
    MEASURED_START=$(gate_measured_tree || true)
    # What made this run legal, handed to the ledger BEFORE it announces, so the
    # header line and the verdict row carry the identical phrase.
    GATE_RUN_SANCTION="$GATE_SANCTIONED_BY"
    # A DRY RUN ARMS NOTHING, AND THAT IS WHERE THE GUARD BELONGS. `gate_run_start`
    # is what arms the run record; every other entry point into it — the note, the
    # verdict, the kill handler and `gate_run_finish` from the EXIT trap — returns
    # immediately while it is unarmed. So one guard here closes all of them, and
    # in particular it closes the DURATION CACHE: `gate_run_finish` appends
    # `<stamp> <seconds> green` to `.git/djb-gate-last-full`, and a one-second dry
    # run wrote `1 green` there, which the next real gate then announced as "the
    # last green run here took 0m1s". A run that judged nothing must not leave a
    # number anybody reads.
    gate_run_start_unless_dry "${MEASURED_START:-unknown-tree}"
    gate_run_announce
else
    gate_lock_refuse_if_held
    # WHAT LET THIS `--loop` RUN WHERE IT IS RUNNING, printed before the first
    # leg, for the same reason the tier rule is printed on every run: a default
    # that was overridden in silence is an override nobody audits. The full
    # gate's own sanction prints in its header one branch up; this is the same
    # sentence one tier down.
    if [ -n "$LOOP_HERE_BECAUSE" ]; then
        echo "- loop here: ${LOOP_HERE_BECAUSE}"
    fi
fi

# --- the --loop scope, and the verdict that can stand in for running it -------
#
# DERIVED HERE RATHER THAN AT THE PYTEST LEG, and the move is the ledger's
# doing: the scope is part of the key (gate_ledger.sh's loop-ledger section), so
# it has to be known before there is anything to consult. It is derived ONCE and
# the pytest leg below reads the same globals — a second derivation would be a
# second answer to keep in step.
#
# THE COST OF DERIVING IT EARLY: a `git diff` and one static read of every
# `apps/*/apps.py`. The cost of NOT consulting: the whole `--loop`, re-spent to
# re-learn a deterministic result on a tree nothing has changed.
LOOP_LEDGER_KEY=""
LOOP_LEDGER_TREE=""
# The run's starting snapshot of its own dirty set, read back at the bank.
LOOP_TREE_SNAPSHOT=""
# THE OTHER TWO THIRDS OF THE KEY, KEPT FROM THE START so the end can say which
# of them moved. The key is a digest of tree + environment + scope and cannot be
# read backwards; a refusal that says only "something moved while the gate ran"
# hands the reader a whole re-run and no subject. These two hold the START's
# environment fingerprint and its printable components, exactly as
# `LOOP_LEDGER_TREE` holds the START's tree.
LOOP_LEDGER_ENV=""
LOOP_LEDGER_ENV_PARTS=""
LOOP_COUNTS_DIR=""
LOOP_MISS_CENSUS=""
LOOP_MISS_DOCSLINE=""
# Set by the consult below when `loop_docs_only_reuse` says the banked pytest
# verdict may stand in for this run's pass. Declared here beside the rest of the
# consult's state because `set -u` is on and the pytest leg reads it whether the
# consult ran or not.
LOOP_PYTEST_REUSE=""

# loop_miss_narrative <the attributor's answer> — the ledger miss, said in two
# lines, with the rest on request.
#
# WHY IT SHRANK. This banner used to open every measuring `--loop` with twelve
# lines about the CACHE — the first screen a builder saw was an explanation of
# why a lookup missed, above the finding they ran the gate for. The facts did
# not stop being worth printing; they stopped being worth printing FIRST. The
# token and the key are what a reader acts on (the token names the component
# that moved; the key is what a verifier compares against a banked row), so
# those two stay, and everything that is context for them moves behind
# `DJB_LOOP_VERBOSE=1` — named on the key line, so the flag is discoverable from
# the short form rather than only from this file.
#
# NOTHING IS SUPPRESSED IN FULL MODE: only `--loop` reaches this printer, and
# the verdict rows, the attribution and the components are unchanged — this is
# what is SHOWN, never what is measured or recorded.
#
# A FUNCTION, AND THAT IS DELIBERATE: `scripts/tests/test_loop_scope.sh` reads
# this definition out of this file and runs it over planted values, so the two
# shapes are driven bytes rather than asserted prose.
loop_miss_narrative() {
    LOOP_MISS_WHY="$1"
    # LINE 1 IS THE TOKEN, every further line is detail — the attributor's
    # stdout contract. Split with parameter expansion rather than a pipe to
    # `head -n1`: the semantics are the same first line, and a consumer that
    # exits on line 1 closes the pipe under its producer, which is the
    # SIGPIPE-under-pipefail class this tree has already paid for twice.
    LOOP_MISS_TOKEN=${LOOP_MISS_WHY%%$'\n'*}
    LOOP_MISS_DETAIL=""
    case "$LOOP_MISS_WHY" in
    *$'\n'*) LOOP_MISS_DETAIL=${LOOP_MISS_WHY#*$'\n'} ;;
    esac
    echo "  == the --loop ledger was consulted and MISSED: miss(${LOOP_MISS_TOKEN}) =="
    # THE DOCS-ONLY LINE PRINTS ON EVERY `miss(tree)`, NOT ONLY UNDER VERBOSE,
    # AND IT COST A 2302-SECOND RE-MEASURE TO LEARN WHY. A verifier missed on
    # `tree`, the whole delta was two ledger files, and the banner offered
    # `DJB_LOOP_VERBOSE=1` instead of the one sentence that would have said so —
    # so the run re-measured and nobody could tell from the transcript that it
    # need not have (V-I2, 2026-09-15). The line is now what decides whether the
    # pytest pass is REUSED below, which makes it the most load-bearing sentence
    # in this banner and the last one that should be behind a flag.
    #
    # IT IS SLICED OUT OF THE DETAIL, NEVER RE-DERIVED. `loop_attribute_head_detail`
    # is the one thing in this repository that answers "what moved since the
    # banked head, and was it only docs"; a second derivation here would be a
    # second answer to keep in step, and the two would disagree on the day one
    # of them is edited.
    LOOP_MISS_DOCSLINE=$(printf '%s\n' "$LOOP_MISS_DETAIL" | sed -n '/^since banked head/p')
    LOOP_MISS_DOCSLINE=${LOOP_MISS_DOCSLINE%%$'\n'*}
    if [ -z "${DJB_LOOP_VERBOSE:-}" ]; then
        echo "  key         ${LOOP_LEDGER_KEY:-(none — the key could not be derived)}   (DJB_LOOP_VERBOSE=1 for the detail, the tree, the env components and the ledger census)"
        if [ "$LOOP_MISS_TOKEN" = "tree" ]; then
            # A NAMED ABSENCE RATHER THAN SILENCE, for the reason every absence
            # in this file is named: a `tree` miss with no line here is
            # indistinguishable from a banner that was never wired, and this is
            # the line a reader now acts on.
            echo "  ${LOOP_MISS_DOCSLINE:-since banked head: not derivable (the attributor produced no such line)}"
        fi
        return 0
    fi
    if [ -n "$LOOP_MISS_DETAIL" ]; then
        printf '%s\n' "$LOOP_MISS_DETAIL" | sed 's/^/    /'
    fi
    echo "  key         ${LOOP_LEDGER_KEY:-(none — the key could not be derived)}"
    echo "  tree=       ${LOOP_LEDGER_TREE}"
    echo "  env=        ${LOOP_ENV_FINGERPRINT:-unstated}"
    echo "  scope=      ${LOOP_SCOPE_CANONICAL}"
    echo "  fingerprint components (the env= line, spelled out):"
    echo "    ${LOOP_ENV_COMPONENTS:-unstated}"
    echo "  ledger:     ${LOOP_MISS_CENSUS:-unreadable}"
    echo "  This run therefore MEASURES. The token names the component; the"
    echo "  components line is printed so a reader can check it, and the"
    echo "  'banked row:' line above names WHICH row it was read from — a row"
    echo "  on this exact tree outranks one on a different tree, and among"
    echo "  equals the nearest banked head wins, never the first row in the"
    echo "  file. A banked row written before the components were recorded is"
    echo "  the one case the token cannot refine, and the detail line above"
    echo "  says when that is what happened."
}

# loop_counts_refuse_if_short <counts files found> <collectors started> — 0 when
# every collector reported, 2 when one of them did not.
#
# THE GREEN RUN THAT RAN NOTHING. A collector that dies once xdist's restart
# budget is exhausted leaves pytest able to exit 0 with `no tests ran` and ONE
# counts file where two were asked for — measured on this tree while driving the
# named-absence line. Until now the absence was PRINTED and the verdict was
# pytest's, which is wrong in the dangerous direction: a `--loop` banked a
# verdict for a suite that did not run, and the only tell was a sentence in the
# middle of a passing transcript.
#
# SO THE SHORTFALL IS THE REFUSAL. `-n` is the population and it is read from
# `GATE_SLOT_WORKERS` — the number this leg actually started — never re-derived
# here, because two answers to "how many collectors" is how a floor stops
# binding. Exit 2, not 1: nothing was judged about this tree, which is neither a
# finding nor a pass, and no verdict is banked because the bank is past the
# refusal.
#
# AND `GATE_SLOT_WORKERS` IS NOW THE POST-KNOB NUMBER. It was not: with the
# documented `DJB_GATE_SLOT_WORKERS` set, the gate started `-n <derived share>`,
# pytest clamped ITSELF to the typed value, and this function compared the
# survivors against the pre-clamp number — so a clean suite with no plant read
# `2 of 5 collectors reported` and banked nothing. The knob is honoured
# at the derivation now (`gate_slot_worker_count`, scripts/gate_lease.sh), which
# is what makes the population here the population that collected.
#
# It is a FUNCTION for the same reason `loop_miss_narrative` is: the drive reads
# this definition out of this file and runs it over the real state it built.
loop_counts_refuse_if_short() {
    local reported=${1:-0} expected=${2:-0} first=${3:-} created=""
    case "$reported" in '' | *[!0-9]*) reported=0 ;; esac
    case "$expected" in '' | *[!0-9]*) expected=0 ;; esac
    # WHAT PYTEST CREATED OUTRANKS WHAT THE LEG ASKED FOR. Every collector writes
    # its own `workers=` — `numprocesses` after apps/conftest.py's ceiling has had
    # its say, the number xdist prints as `created: N/N workers` — so when a
    # counts file is in hand the population is read from the run instead of from
    # the `-n` that was typed at it. A bank's `-n 10` clamped to 5 inside pytest
    # read its own five survivors as five casualties here.
    if [ -n "$first" ] && [ -f "$first" ]; then
        created=$(awk -F= '$1 == "workers" { print $2; exit }' "$first" 2>/dev/null || true)
        case "$created" in '' | *[!0-9]*) : ;; *) [ "$created" -lt 1 ] || expected=$created ;; esac
    fi
    # An unknown population cannot be short of itself: when the leg did not say
    # how many collectors it started there is nothing to compare, and inventing
    # a number here would be the second derivation this refuses to have.
    [ "$expected" -gt 0 ] || return 0
    [ "$reported" -lt "$expected" ] || return 0
    # THROUGH THE SEAM, so the banner above this callee can name the cause where
    # the reader is standing. The text is byte-identical to the `echo` it
    # replaces — drives assert this sentence — and the only new thing is that it
    # is REMEMBERED (scripts/gate_refuse.sh).
    gate_refuse "${reported} of ${expected} collectors reported — a collector died and the suite that ran is not the suite that was asked for; nothing is judged"
    echo "   Every collector performs its own FULL collection and writes its counts, so" >&2
    echo "   a missing file is a collector that never got to the end of collecting." >&2
    echo "   pytest can still exit 0 from that state (it runs what the survivors hold," >&2
    echo "   and 'no tests ran' is not a failure), which is why this is a refusal here" >&2
    echo "   and not a note beside a green verdict. No verdict is banked." >&2
    return 2
}

# loop_mine_banner <open|close> <the derived tier mode> <the own-app list> —
# what a `--mine` run says about itself, at the two ends it says it.
#
# SAID AT BOTH ENDS, because the line a reader carries into a report is the last
# one they read and the line that decides whether they keep reading is the first.
#
# TWO SHAPES, AND THE SECOND IS WHY THIS IS A FUNCTION. `--mine` subtracts a
# closure from a scope; when the derivation came back `full` (the rung changed
# shared test infrastructure) there was no scope to subtract from, the WHOLE
# suite ran, and a banner claiming "the closure was NOT walked" would be a
# narrowing announced by a run that narrowed nothing — an honesty banner lying
# in the one direction nobody would check. The shapes are told apart here, and
# `scripts/tests/test_loop_scope.sh` reads this definition out of this file and
# runs it over both, the way it already does for `loop_miss_narrative` and
# `loop_counts_refuse_if_short`.
loop_mine_banner() {
    local where="$1" mode="${2:-}" own="${3:-}"
    if [ "$where" = "open" ]; then
        if [ "$mode" = "full" ]; then
            echo "  MINE: nothing was narrowed — the note above says why, and this run is the FULL suite"
        else
            echo "  MINE: the depends_on closure was NOT walked — a regression in a dependant surfaces at the ordinary --loop"
        fi
        echo "  not banked: --mine"
        echo "              a --mine green is a claim about one app, and says so. The"
        echo "              ledger is neither consulted nor written on this run, so no"
        echo "              later gate can inherit this run's narrower question."
        return 0
    fi
    if [ "$mode" = "full" ]; then
        echo "  not banked: --mine — the flag narrowed nothing here (the note above"
        echo "  says why), and a --mine run banks no verdict in any case. The"
        echo "  ordinary --loop is what banks the row a verifier consults."
        return 0
    fi
    echo "  not banked: --mine — the closure was not walked, so this green is a"
    echo "  claim about [${own:--}] and the always-on set, and about nothing else."
    echo "  Run the ordinary --loop at your last boundary."
}

# loop_map_banner — the TEST-IMPACT MAP's line, printed on every --loop.
#
# ONE LINE THAT SAYS WHICH MAP, HOW OLD, AND WHAT IT BOUGHT, and a second that
# says what a selection is made of. A narrowing nobody can see the cause of is
# an unfalsifiable one — the argument every banner in this file is printed for
# — and a SELECTION is the narrowing with the fewest readers who already know
# the rule: the scope a reader can check against their own diff, and a list of
# nodeids they cannot.
#
# THE FALLBACK IS THE SAME LINE, NEVER A MISSING ONE. A run that did not
# consult the map, or consulted it and stood down, says so with the sentence
# the derivation recorded — the path and its class for a file the map has
# never recorded, the valve where the valve was typed, `absent` where there is
# no map at all. Silence would read exactly like a map that narrowed nothing.
loop_map_banner() {
    echo "  scope   map: sha=${LOOP_SCOPE_MAP_SHA:--} generated=tree:${LOOP_SCOPE_MAP_TREE:--} age=${LOOP_SCOPE_MAP_AGE:--} commit(s) since"
    if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ]; then
        echo "  scope   impact: ${LOOP_SCOPE_IMPACT_SEEN:-0} changed file(s) the map has SEEN -> ${LOOP_SCOPE_IMPACT_TESTS:-0} test(s) selected; fallback: none"
        echo "          the always-on cross-app set is added at the pytest door, which"
        echo "          prints its own count as \`impact-select: <named>, <always-on>\`;"
        echo "          the closure scope above was NOT what ran."
    else
        echo "  scope   impact: no selection; fallback: ${LOOP_SCOPE_IMPACT_FALLBACK:-the map was not consulted}"
    fi
}

if [ "$MODE" = "--loop" ]; then
    # THE FLAG IS CHECK.SH'S, THE MEANING IS THE LIBRARY'S. `--mine` is parsed
    # at the top of this file and handed to the derivation as one input; what it
    # subtracts (the closure, and only the closure) is declared beside the
    # derivation in scripts/loop_tier.sh, where the rest of the scope rules live.
    LOOP_MINE="$GATE_MINE"
    # THE MAP IS THE ORDINARY LOOP'S, AND THE SWITCH IS HERE FOR THE SAME
    # REASON `--mine`'s is: the flag belongs to this file and the meaning
    # belongs to the library. The ordinary `--loop` consults the test-impact
    # map; `--mine` does not (its claim is about an app, and a selection that
    # reached into a DEPENDANT of that app to run one test would be a third
    # thing wearing the flag's name), and `--pr` does not (it grades a whole
    # proposed change and must not be narrowed by one run's measurement of a
    # different tree). Both still carry `map=` in the canonical scope, so a
    # row can always be read against the map the tree held.
    LOOP_IMPACT=""
    [ -n "$GATE_MINE" ] || LOOP_IMPACT=1
    gate_refuse_reset
    set +e
    loop_tier_own_apps
    TIER_RC=$?
    set -e
    if [ "$TIER_RC" != "0" ]; then
        # THE SENTENCE IS THE ONE THE TIER'S OWN DRIVE PINS, kept verbatim
        # through the active rung's move of the derivation: the refusal is the same
        # refusal, it just fires earlier now, and a drive that asserts an
        # honesty banner as text is asserting exactly the thing a reword would
        # silently break.
        gate_cause
        echo "!! the pytest tier COULD NOT DERIVE the active rung's changed files — see above." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        echo "   The --loop SCOPE is derived from that same set, so it could not be" >&2
        echo "   derived either." >&2
        echo "   An underived set is not an empty set: choosing a selection on the" >&2
        echo "   strength of a derivation that did not answer would run LESS than the" >&2
        echo "   gate claims, silently." >&2
        exit 2
    fi
    echo "- loop scope: ${LOOP_TIER_REASON}"
    echo "  basis:      ${LOOP_TIER_BASIS}"
    # ONE LINE PER DECISION, BEFORE THE FIRST TEST RUNS (contract A.2). These
    # four are the SHELL's half — what the changed files classified as, what the
    # declarations widened to, which apps run in full, and the rule. The counts
    # half cannot be known until something has collected, and `apps/conftest.py`
    # prints it from the xdist controller hook, still before the first test.
    echo "  scope   touched: ${LOOP_SCOPE_TOUCHED:--}"
    echo "  scope   tests-only: ${LOOP_SCOPE_TESTS_ONLY:--}"
    echo "  scope   closure: ${LOOP_SCOPE_WIDENED:--}"
    echo "  scope   own (organ tests in full): ${LOOP_TIER_OWN_APPS:--}"
    echo "  scope   rule: ${LOOP_TIER_REASON}"
    loop_map_banner
    if [ -n "$LOOP_SCOPE_NOTES" ]; then
        printf '%s\n' "$LOOP_SCOPE_NOTES" | sed 's/^/  note:       /'
    fi
    # THE HONESTY BANNER, BEFORE THE FIRST LEG. It prints here rather than beside
    # the verdict for the reason every banner in this file prints early: a reader
    # deciding whether to trust a run should not have to reach the end of it, and
    # a RED `--mine` discloses its narrowing exactly as a green one does.
    [ -z "$GATE_MINE" ] || loop_mine_banner open "$LOOP_TIER_MODE" "$LOOP_TIER_OWN_APPS"
    # THE ENVIRONMENT IS BROUGHT TO THE LOCKFILE BEFORE THE KEY IS DERIVED, and
    # the whole argument is `loop_env_sync`'s own header in scripts/gate_ledger.sh.
    # In one line: the key censuses the installed distributions, the gate's first
    # `uv run` used to install them, and a cold box's completely green `--loop`
    # therefore banked nothing. A DRY RUN INSTALLS NOTHING — it judges nothing
    # and banks nothing, so it has no key to hold still.
    [ -n "${DJB_GATE_LEGS_DRY:-}" ] || loop_env_sync
    # THE RUN'S STARTING STATE, TAKEN WHERE THE KEY TAKES ITS TREE. The env
    # sync above is the last thing this mode does to the checkout before a
    # leg runs, so this is the first moment the tree is the one the key is
    # about. The bank below asks it one question — did the run itself write a
    # path the key reads — and refuses to bank when it did
    # (`loop_tree_snapshot`, scripts/gate_ledger.sh). A snapshot that could
    # not be taken leaves the name empty, and the bank refuses on that too.
    # IN THIS CHECKOUT'S OWN GIT DIRECTORY, under one fixed name: outside the
    # measured tree, never shared with another worktree, overwritten by the
    # next run rather than accumulating one file per red run — and the
    # per-checkout gate lock means one run writes it at a time.
    LOOP_TREE_SNAPSHOT=""
    if LOOP_TREE_SNAPSHOT="$(git rev-parse --absolute-git-dir 2>/dev/null)/djb-loop-snapshot" &&
        [ "$LOOP_TREE_SNAPSHOT" != "/djb-loop-snapshot" ]; then
        loop_tree_snapshot "$LOOP_TREE_SNAPSHOT" || LOOP_TREE_SNAPSHOT=""
    else
        LOOP_TREE_SNAPSHOT=""
    fi
    LOOP_LEDGER_TREE=$(gate_measured_tree || true)
    # IN THIS SHELL, NOT IN A SUBSTITUTION, and that is the whole reason this
    # line exists on its own. `loop_ledger_key` computes the fingerprint too,
    # but it is called as `$(...)` — a SUBSHELL — so the globals it sets there
    # die with it and every `env=` this file printed or recorded came out
    # `unstated`. Measured on the active rung's own first green run: the row banked
    # `env=unstated`, which is exactly the "a miss banner that says only no row"
    # failure the attribution work exists to prevent, wearing a passing gate.
    # The value is identical either way; what differs is which shell keeps it.
    # NO KEY UNDER `--mine`, AND THAT IS THE WHOLE MECHANISM. Every consult and
    # every bank in this file is guarded on `$LOOP_LEDGER_KEY` being non-empty,
    # so declining to derive one here is what makes "--mine neither reuses nor
    # records" a property of the code rather than of two remembered guards.
    if [ -n "$LOOP_LEDGER_TREE" ] && [ -z "${DJB_LOOP_NO_CACHE:-}" ] && [ -z "$GATE_MINE" ]; then
        loop_env_fingerprint >/dev/null 2>&1 || true
        LOOP_LEDGER_KEY=$(loop_ledger_key "$LOOP_LEDGER_TREE" "$LOOP_SCOPE_CANONICAL" || true)
        # THE START'S OTHER TWO THIRDS, CAPTURED HERE AND NOWHERE ELSE. The
        # fingerprint is re-derived at the end and `LOOP_ENV_FINGERPRINT` is
        # overwritten by that call, so the only place the START's value can be
        # kept is the line after the START derives it.
        LOOP_LEDGER_ENV="${LOOP_ENV_FINGERPRINT:-}"
        LOOP_LEDGER_ENV_PARTS="${LOOP_ENV_COMPONENTS:-}"
    fi
    if [ -n "$LOOP_LEDGER_KEY" ] && LOOP_ROW=$(loop_ledger_lookup "$LOOP_LEDGER_KEY"); then
        echo "ok: --loop VERDICT REUSED — nothing was re-measured."
        echo "  key    ${LOOP_LEDGER_KEY}"
        echo "  tree   ${LOOP_LEDGER_TREE}"
        echo "  scope  ${LOOP_SCOPE_CANONICAL}"
        echo "  banked ${LOOP_ROW}"
        echo "  ledger ${LOOP_LEDGER_CENSUS:-$(loop_ledger_census || echo 'unreadable')}"
        echo "  env=   ${LOOP_ENV_FINGERPRINT:-unstated}"
        echo "         ${LOOP_ENV_COMPONENTS:-unstated}"
        echo "  A complete green --loop already measured THESE bytes, in THIS"
        echo "  environment, at THIS scope. The key is all three: the same tree at a"
        echo "  wider scope is a different key and gets no reuse."
        echo "  This is a CACHE and never a security boundary — the trust class"
        echo "  scripts/gate_ledger.sh states for the full ledger, unchanged. Force a"
        echo "  re-measure with DJB_LOOP_NO_CACHE=1."
        exit 0
    fi
    # THE MISS BANNER, AND IT IS NOT OPTIONAL. A consult that missed and said
    # only "no row" leaves the next reader — a verifier filling in a `loop:`
    # field, a PM reading the round's readout — with a re-measure and no reason
    # for it. The three key inputs are printed because the key is a digest of
    # them and cannot be read backwards, and the fingerprint's five components
    # are printed because the env line is itself a digest — this run's side of a
    # comparison the ATTRIBUTOR now makes for the reader, against the components
    # the banked row carries, and names in the token.
    if [ -n "$GATE_MINE" ]; then
        # NOT A MISS, AND IT MUST NOT PRINT AS ONE. A miss banner names the
        # component that moved and invites the reader to compare a key; this run
        # never asked the ledger anything, and saying "MISSED" here would put a
        # cache diagnosis in front of a builder whose run was never eligible for
        # one. The banner above already said what this run is.
        echo "  == the --loop ledger was NOT consulted: --mine =="
    elif [ -n "$LOOP_LEDGER_TREE" ] && [ -z "${DJB_LOOP_NO_CACHE:-}" ]; then
        LOOP_MISS_WHY=$(loop_ledger_attribute \
            "$LOOP_LEDGER_TREE" "${LOOP_ENV_FINGERPRINT:-unstated}" "$LOOP_SCOPE_CANONICAL")
        LOOP_MISS_CENSUS=$(loop_ledger_census || echo 'unreadable')
        loop_miss_narrative "$LOOP_MISS_WHY"
        # --- the one miss that need not cost a pytest pass -------------------
        #
        # PLAINLY, NOT IN A SUBSTITUTION: it sets LOOP_REUSE_TREE and
        # LOOP_REUSE_N, and a subshell's copy of a global is not a value this
        # shell has — the same trap the fingerprint above is spelled out for.
        #
        # AND IT SITS HERE, INSIDE THE MISS ARM, WHICH IS WHAT KEEPS THE REUSE
        # OFF EVERY OTHER BELT. `--mine` reaches the arm above this one and
        # derives no key at all; `--pr` and the full gate never enter this
        # `--loop` block; `DJB_LOOP_NO_CACHE=1` reaches the arm below. None of
        # them can reuse, and none of them needs a guard of its own to say so.
        if loop_docs_only_reuse "$LOOP_MISS_TOKEN" "$LOOP_MISS_DETAIL"; then
            LOOP_PYTEST_REUSE=1
            echo "  docs-only: the pytest pass of this miss is REUSABLE — see the pytest leg."
        elif [ -n "$LOOP_REUSE_WHY" ]; then
            # PRINTED ONLY WHEN THE DELTA WAS DOCS-ONLY AND THE REUSE WAS
            # REFUSED ANYWAY. "This is an ordinary mixed delta" is not news and
            # would add a line to every miss in the tree; "a cheap green was
            # available and declined, for this reason" is the whole point.
            echo "  ${LOOP_REUSE_WHY}"
        fi
    elif [ -n "${DJB_LOOP_NO_CACHE:-}" ]; then
        echo "  == the --loop ledger was NOT consulted: DJB_LOOP_NO_CACHE is set =="
        echo "  This run measures, and it will not bank."
    fi
fi

LEG_T0=$(date +%s)

# THE PYTEST LEG'S WALL, KEPT RATHER THAN PRINTED AND FORGOTTEN. Every leg has
# always printed its own time; the pytest one is the number that decides whether
# a gate is slow, and it died with the terminal. It is captured HERE, where the
# timing arithmetic already happens, so there is exactly one clock and no second
# thing to keep in step — `gate_ledger_record` and `loop_ledger_record` read it
# off this global and append it to the verdict row as `took=`.
#
# IT IS THE LEG'S WALL, WHICH INCLUDES THE SLOT WAIT, and that is stated rather
# than silently corrected: the slot is taken INSIDE the leg (the queue starts
# where the cost is), so a run that queued four minutes records those four
# minutes here too. `waited=` is written beside it on the same row precisely so
# a reader can subtract, and the next run's nominal is an ESTIMATE printed as
# one — never something this gate decides anything on.
GATE_PYTEST_TOOK=0

gate_leg_took() {
    case "$1" in
    pytest | pytest-x2) GATE_PYTEST_TOOK=$2 ;;
    esac
    gate_member_record "$1" "$2"
}

# gate_leg_in_unit <leg name> — 0 when this run is running that leg: either it
# is not a `--leg <unit>` run at all, or the unit holds the leg.
#
# `local-legs` IS THE ONE LEG WHOSE NAME IS NOT ITS OWN MEMBERSHIP. It is the
# RUNNER of the product drawer, and what the listing puts in a unit is the
# drawer's legs — `local:<name>` — never the runner. So a unit that holds one
# of the drawer's LEGS holds the runner too, and a unit that holds none does
# not announce it. Written once and read by both the announcement and the body,
# because the day those two answer differently is the day a unit announces a
# leg no runner was handed, or runs one nobody announced.
#
# AND THE TEST IS THE LEG NAMES, NOT THE `local:` PREFIX. `local:<name>` is
# also how a product DRIVE is printed (the drawer at `scripts/local/drives/`,
# read by `selftest_registered_drives`), and the `selftest` unit's composed-of
# carries every registered drive — so a bare-prefix test made every product
# tree's selftest box announce and RUN the product's legs, whose `needs` that
# unit never declared and whose organs it therefore never provisioned. Measured
# on the first consumer's world: `--leg selftest` announced `local-legs` while
# `--leg static` did not, and the listing said nothing about it. The membership
# question is asked of `LOCAL_LEGS_MEMBERS` — the drawer's legs, and only its
# legs, which is the same string `FULL_LEGS` grows by.
gate_leg_in_unit() {
    [ -n "$GATE_LEG_UNIT_LEGS" ] || return 0
    case "$GATE_LEG_UNIT_LEGS" in
    *",$1,"*) return 0 ;;
    esac
    if [ "$1" = "local-legs" ]; then
        local member
        for member in $(printf '%s' "${LOCAL_LEGS_MEMBERS:-}" | tr ',' ' '); do
            case "$GATE_LEG_UNIT_LEGS" in
            *",${member},"*) return 0 ;;
            esac
        done
    fi
    return 1
}
leg() {
    # UNDER `--leg <unit>`, A LEG OUTSIDE THE UNIT IS NOT ANNOUNCED AT ALL —
    # not announced, not timed, not skipped-with-a-line. A runner handed one
    # unit must be able to read its log as the transcript of that unit; a list
    # of everything it did not run is noise the other N-1 runners are printing
    # too. `GATE_LEG_UNIT_LEGS` is empty on every other path, which is what
    # makes this a no-op everywhere else.
    gate_leg_in_unit "$1" || return 0
    # Announce a leg and print the previous leg's wall time. Timing is printed
    # per leg so a slow gate names its slow leg instead of being argued about.
    local now
    now=$(date +%s)
    if [ -n "${LEG_NAME:-}" ]; then
        echo "  (${LEG_NAME}: $((now - LEG_T0))s)"
        gate_leg_took "$LEG_NAME" "$((now - LEG_T0))"
    fi
    LEG_NAME=$1
    LEG_T0=$now
    gate_leg "$1" "$2"
}
leg_done() {
    local now
    now=$(date +%s)
    echo "  (${LEG_NAME}: $((now - LEG_T0))s)"
    gate_leg_took "$LEG_NAME" "$((now - LEG_T0))"
    LEG_NAME=""
}

# --- THE LEG RUNNER, AND THE ONE VARIABLE THAT MAKES A LEG A NO-OP ------------
#
# EVERY LEG BODY IS A FUNCTION AND THIS CALLS IT. That is the whole of the
# refactor, and it buys exactly one thing that could not be had otherwise: the
# ORDERED LIST OF LEGS A MODE ANNOUNCES can be derived by RUNNING the mode,
# rather than by reading this file and hoping the reading and the flow agree.
# A static reading of a 4500-line script is a second implementation of its
# control flow, and the day the two disagree the reading is the one that is
# green.
#
# `DJB_GATE_LEGS_DRY` IS THE DRIVE'S, AND NOTHING ELSE SETS IT. Set, every leg
# is ANNOUNCED — its name and its banner, through the same `leg` call the real
# run makes — and its body is not called. Nothing else about the mode changes:
# the mode branches, the early exits and the ordering all run as they always
# do, which is what makes the sequence the drive captures the sequence the gate
# would have run.
#
# WHAT A DRY RUN STILL DOES, SAID OUT LOUD rather than left to be discovered:
# it takes the lease, the checkout lock and (in `--loop`) the scope consult,
# because those live outside the legs. The drive therefore runs it in a SCRATCH
# CHECKOUT with its own lease directory — a dry run that queued behind a real
# full gate would be a drive holding the machine — and the two ledger-record
# sites below refuse to bank under it, because a run that judged nothing must
# never leave a verdict saying it did.
#   gate_run_body <leg-name> <body-function>
#
# THE NAME IS AN ARGUMENT AND NOT A LOOKUP, so this is the ONE place in the file
# that reads `DJB_GATE_LEGS_DRY` — the dry line a drive parses and the body it
# skips are decided together, and there is no second reader to fall out of step
# with this one.
gate_run_body() {
    # THE SAME ONE VARIABLE THE ANNOUNCEMENT READS. A body run for a leg the
    # unit does not hold would be the unit running work no runner was handed,
    # and reading a second variable here is how the two halves come apart.
    gate_leg_in_unit "$1" || return 0
    if [ -n "${DJB_GATE_LEGS_DRY:-}" ]; then
        echo "  leg: $1 (DJB_GATE_LEGS_DRY — announced, body not run)"
        return 0
    fi
    "$2"
}

# >>> gate-heartbeat >>>
# THE PYTEST PASSES ARE OTHERWISE SILENT, AND A SILENT LEG IS INDISTINGUISHABLE
# FROM A WEDGED ONE. `--loop` streams pytest's own output but paces silently
# under load; the full gate's pass 2 is CAPTURED WHOLE and printed at the end
# (it has to read what it is about to make a claim about, and reading through a
# pipe would replace pytest's exit status with the reader's) — which is how a
# green run once presented as half an hour of nothing at all. An agent that
# cannot tell a slow suite from a hang kills the gate, and two runs have been
# killed exactly that way, each having judged nothing.
#
# WHAT THE TICKER READS EVERY TICK, AND WHY IT DOES NOT INHERIT IT. A subshell
# forked when the leg starts captures its environment AT FORK, and the pytest
# slot is taken AFTER that — so a ticker that inherited a start time would be
# timing the wrong thing or nothing at all. Each tick therefore reads two things
# off disk: this process's own slot record (the `started-epoch` field, the same
# field `gate_slot_holders` renders) and a label file the parent writes, which
# is how one ticker can say `pass 1` and then `pass 2` without being restarted.
#
# NO SLOT RECORD MEANS THE TICKER PRINTS NOTHING. Before the slot is held the
# wait loop in `gate_lease.sh` is already announcing every interval, and two
# announcers saying different things about the same wait is worse than one. The
# same silence covers the case where a slot is reclaimed underneath a live pass:
# the ticker goes quiet rather than printing arithmetic from a record that is
# no longer there.
#
# IT LIVES IN THIS FILE AND NOT IN `gate_lease.sh` ON PURPOSE. That file is a
# LIBRARY, sourced by drives that start no suite, and a sourced library must not
# fork a writer onto its caller's stdout. The sentinels around this block are
# what let a drive source these functions without sourcing the gate — the same
# shape `gate_ledger.sh`'s derived-env-key declaration uses, and for the same
# reason: the thing that must be readable from outside says so in its own text.
GATE_HB_PID=""
GATE_HB_DIR=""

# gate_hb_slot_started <pid> — that pid's slot record's started-epoch, or
# nothing. A PURE READ: it never reclaims, because a background ticker is the
# last thing in this system that should be deleting another gate's directory.
gate_hb_slot_started() {
    local want=$1 dir holder pid
    dir=$(gate_slots_dir 2>/dev/null) || return 0
    [ -d "$dir" ] || return 0
    for holder in "$dir"/slot-*/holder; do
        [ -f "$holder" ] || continue
        pid=$(awk 'NR==1{print $1}' "$holder" 2>/dev/null || true)
        [ "$pid" = "$want" ] || continue
        awk 'NR==1{print $5}' "$holder" 2>/dev/null || true
        return 0
    done
    return 0
}

# heartbeat_start <label> <nominal-seconds> <provenance>
heartbeat_start() {
    local label=$1 nominal=$2 provenance=$3 announce parent
    # An escape hatch that is off by default in exactly one direction: the
    # heartbeat is ON unless something explicitly turns it off, because a
    # progress line nobody asked for costs a line a minute and a missing one
    # costs a killed gate.
    case "${DJB_GATE_HEARTBEAT:-1}" in
    0 | off | no) return 0 ;;
    esac
    heartbeat_stop
    # No `2>/dev/null` on the template: the portability census reads the LAST
    # bare word before a redirect as the template, so a silenced mktemp reads to
    # it as `mktemp ... 2` and reds the gate. A scratch directory that cannot be
    # made should say so anyway — the heartbeat then simply does not start, and
    # the leg it was watching is unaffected.
    GATE_HB_DIR=$(mktemp -d "${TMPDIR:-/tmp}/djb-gate-hb.XXXXXX") || {
        GATE_HB_DIR=""
        return 0
    }
    printf '%s\n' "$label" >"$GATE_HB_DIR/label"
    announce=${DJB_GATE_LEASE_ANNOUNCE:-$GATE_LEASE_DEFAULT_ANNOUNCE}
    # Taken BEFORE the fork on purpose. `$$` inside a subshell is the parent's
    # pid in bash, but relying on that is relying on a shell detail this file
    # would rather assert than remember.
    parent=$$
    (
        local_started=""
        while :; do
            sleep "$announce"
            # THE TICKER OUTLIVES NOTHING. Two conditions end it without being
            # told: the scratch directory going (a `heartbeat_stop` that got
            # there first) and THE PARENT GATE BEING GONE. The second is the one
            # that matters — `heartbeat_stop` and the EXIT trap cover an orderly
            # end, and neither runs when a gate is SIGKILLed at a harness
            # ceiling, which is how full runs die routinely. A ticker left
            # behind by that would go on printing into a log nobody is reading,
            # for as long as the box is up, and turn up in somebody else's
            # poller census as a process they did not start.
            [ -d "$GATE_HB_DIR" ] || exit 0
            kill -0 "$parent" 2>/dev/null || exit 0
            local_started=$(gate_hb_slot_started "$parent")
            case "$local_started" in
            '' | *[!0-9]*) continue ;;
            esac
            printf '  %s: %sm elapsed, nominal %sm (%s)\n' \
                "$(cat "$GATE_HB_DIR/label" 2>/dev/null || printf 'pytest')" \
                "$((($(date +%s) - local_started) / 60))" \
                "$(((nominal + 59) / 60))" "$provenance"
        done
    ) &
    GATE_HB_PID=$!
}

# heartbeat_label <label> — rename the live ticker's subject without restarting
# it. One ticker spans both passes of the full gate; only the word changes.
heartbeat_label() {
    [ -n "$GATE_HB_DIR" ] || return 0
    printf '%s\n' "$1" >"$GATE_HB_DIR/label" 2>/dev/null || true
}

# heartbeat_stop — idempotent, and SILENT ABOUT A TICKER THAT IS ALREADY DEAD.
# Under `set -e` a non-zero `kill` or `wait` would red the whole gate, which
# would mean a progress instrument could fail a tree it was only watching. Both
# ends are therefore `|| true`, and there is a case for it.
heartbeat_stop() {
    if [ -n "$GATE_HB_PID" ]; then
        kill "$GATE_HB_PID" 2>/dev/null || true
        wait "$GATE_HB_PID" 2>/dev/null || true
        GATE_HB_PID=""
    fi
    [ -z "$GATE_HB_DIR" ] || rm -rf "$GATE_HB_DIR"
    GATE_HB_DIR=""
    return 0
}

# ---- the nominal a pass is measured against ----------------------------
#
# A TYPED NUMBER AND A MEASURED ONE ARE DIFFERENT CLAIMS, SO THE LINE SAYS
# WHICH. A typed 900 s printed against a suite that really takes thirty minutes
# is prose wearing a number; a measured one is a fact about this repository. So
# the leg prints the nominal AND where it came from, every run, and prefers the
# last wall this repository's own ledger recorded over the constant in
# `gate_lease.sh`.
#
# "THIS CHECKOUT'S" IS REALLY "THIS REPOSITORY'S", STATED RATHER THAN IMPLIED:
# both ledgers live under `--git-common-dir`, shared by every worktree of one
# repository, because a verdict is a property of CONTENT. A wall measured in a
# sibling worktree of the same repository on the same box is the best available
# estimate of this one's, and it is printed as an estimate.
GATE_PYTEST_NOMINAL=0
GATE_PYTEST_NOMINAL_WHY=""
GATE_PYTEST_NOMINAL_PROV=""

# gate_last_took <ledger path> — the most recent `took=<seconds>` in that
# ledger, or exit 1 when the file has none (every row written before the field
# existed, which is all of them on the day this ships).
gate_last_took() {
    local path=$1 line
    [ -f "$path" ] || return 1
    line=$(grep -E ' took=[0-9]+' "$path" | tail -1) || return 1
    [ -n "$line" ] || return 1
    line=${line##* took=}
    line=${line%% *}
    case "$line" in
    '' | *[!0-9]*) return 1 ;;
    esac
    [ "$line" -gt 0 ] || return 1
    printf '%s\n' "$line"
}

# gate_pytest_nominal <typed-seconds> <typed-constant-name> <ledger path>
gate_pytest_nominal() {
    local typed=$1 constant=$2 path=$3 took
    if took=$(gate_last_took "$path"); then
        GATE_PYTEST_NOMINAL=$took
        GATE_PYTEST_NOMINAL_PROV="measured"
        GATE_PYTEST_NOMINAL_WHY="this checkout's last banked took="
    else
        GATE_PYTEST_NOMINAL=$typed
        GATE_PYTEST_NOMINAL_PROV="typed"
        # The CONSTANT is cited, not a line number. A line number in shipped
        # output is a citation that goes wrong without this file changing,
        # which is the one kind of staleness nobody ever re-reads.
        GATE_PYTEST_NOMINAL_WHY="typed, gate_lease.sh ${constant}"
    fi
    echo "  nominal:    $(((GATE_PYTEST_NOMINAL + 59) / 60))m (${GATE_PYTEST_NOMINAL_WHY})"
}
# <<< gate-heartbeat <<<

# --- the --fast legs ---------------------------------------------------------

leg ruff "ruff (lint + format check)"
gate_leg_ruff() {
uv run ruff check .
uv run ruff format --check --quiet .
}
gate_run_body ruff gate_leg_ruff

leg mypy "mypy --strict (apps, config)"
gate_leg_mypy() {
uv run mypy
}
gate_run_body mypy gate_leg_mypy

leg import-linter "import-linter (layer contracts)"
gate_leg_import_linter() {
uv run lint-imports
}
gate_run_body import-linter gate_leg_import_linter

leg djb-checks "django system checks, tag djb (settings=test, no database)"
gate_leg_djb_checks() {
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check --tag djb
}
gate_run_body djb-checks gate_leg_djb_checks

leg house-rules "house rules (quality/rules.yaml — live scan + diff vs HEAD)"
# >>> leg-body: house-rules >>>
# EXTRACTED AND SOURCED BY `scripts/tests/test_rung_tidy.sh` between these
# sentinels, which is why they are here: a drive cannot run a nested
# `./scripts/check.sh` (the per-checkout gate lock refuses it), so it drives the
# LEG BODY with a shimmed engine on PATH. Cited by sentinel and never by line
# number — this file moves under its own citations routinely.
gate_leg_house_rules() {
# The djb leg above already ran; the engine skips its own copy of it.
#
# THE OUTPUT IS CAPTURED AND THEN PRINTED, through a REDIRECT and `cat` —
# never a pipe. The OFFER below is a claim about what the engine SAID and this
# leg cannot make it without having read it, so the output has to land in a
# file either way; the question was only whether the file is filled through
# `| tee` or through `>`.
#
# IT WAS `tee`, AND THAT PUT A PIPE ON A GATE LEG. The standing rule is that
# nothing whose exit status the gate trusts is piped (CLAUDE.md; the gate
# refuses a piped stdout of its own for the same reason), and `PIPESTATUS[0]`
# is a second reading of a status the shell had already made ambiguous rather
# than a reason the pipe was safe. `>` then `cat` gives the same two things —
# the transcript on the terminal and the bytes in the file — with `$?` meaning
# the engine and nothing else.
#
# WHAT IT COSTS, DECLARED: the leg no longer STREAMS. A reader watching a full
# gate sees this leg silent for its whole duration and then all of it at once,
# where `tee` printed as the engine went. That is the trade, and it is the
# cheap side of it: the leg is seconds, and a status a reader can trust
# outranks a transcript that arrives sooner.
GATE_HR_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-house-rules.XXXXXX")
set +e
GATE_SKIP_DJANGO_LEG=1 uv run python -m quality.gate --diff HEAD $([ "$MODE" = "--loop" ] && echo --terse) >"$GATE_HR_OUT" 2>&1 # unquoted on purpose: empty must be NO argument
GATE_RC=$?
set -e
cat "$GATE_HR_OUT"
# THE OFFER, AT THE SITE OF THE REFUSAL, AND ONLY WHEN THE SENTENCE IS THERE.
# A `budget:` line ends in the exact number to write into quality/budgets.yaml,
# and every builder who met one used to read the advice, find the file, find
# the key and type the number by hand. The command below does that
# transformation and nothing else, into the WORKING TREE, so the rung's own
# diff carries the decision for a reviewer to see.
#
# NEVER ON EVERY RED. Most house-rules reds have nothing to do with a budget,
# and an offer printed under all of them is an offer nobody reads under the one
# it is for. The condition is the ENGINE'S OWN SENTENCE — `budget:` at the head
# of a line, under the live scan's `x ` marker or bare — and a GREEN leg prints
# no `offer:` line at all, which `test_rung_tidy.sh` asserts as its own case.
if [ "$GATE_RC" != "0" ] && grep -qE '^[[:space:]]*(x )?budget: ' "$GATE_HR_OUT"; then
    echo ""
    echo "  offer: ./scripts/rung_tidy.sh --budgets"
    echo "    It writes the ceiling(s) the line(s) above named into quality/budgets.yaml,"
    echo "    in the working tree, staging nothing. A RAISE is a decision and stays in"
    echo "    the caller's own diff where a reviewer reads it; a LOWERING note is not"
    echo "    applied here — that one is the fold's, at the bank, under its own subject."
fi
rm -f "$GATE_HR_OUT"
if [ "$GATE_RC" = "2" ]; then
    echo "!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass." >&2
    exit 2
elif [ "$GATE_RC" != "0" ]; then
    exit "$GATE_RC"
fi
}
# <<< leg-body: house-rules <<<
gate_run_body house-rules gate_leg_house_rules

leg migrations "makemigrations --check (+ linear migrations: one leaf per app)"
gate_leg_migrations() {
# The one-leaf/merge/max_migration checks are house rule 6 and already ran in
# the leg above; this catches the model change whose migration was never made.
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py makemigrations --check --dry-run
}
gate_run_body migrations gate_leg_migrations

leg goalpost-census "instrument census (every executable git knows about outside apps/ and config/ owes a row in instruments.md)"
gate_leg_goalpost_census() {
# THE CENSUS IS A GATE LEG; THE SCAN IS NOT, and that split is ADR gate-3's,
# not a compromise.
#
#   The SCAN judges the verdict register: is a GREEN older than the last change
#   to what it vouches for? That is a judgement about DATES and about main's
#   history, and a builder's branch is the wrong place to make it — a rung that
#   touches a re-trigger would go red for a staleness nobody can fix from
#   inside the rung. It stays the PM's, at CLOSE.
#
#   The CENSUS judges THIS TREE: does every instrument in it own a row saying
#   what it can and cannot see? That is answerable here, by the person who just
#   added the instrument, and nowhere else — because the moment a new reporter
#   ships uncensused, the doc has gone stale invisibly and no later reader can
#   tell. It is the same reason `makemigrations --check` is a leg.
#
# IN `--fast`, AND THAT IS AFFORDABLE ON PURPOSE: the census reads `git
# ls-files`, some mode bits and one markdown table — no database, no network, no
# Django import, ~0.1s on this tree — which is why it can sit in the tier
# pre-commit runs rather than in the one nobody feels. The leg ALSO keys every
# drive under scripts/tests/ the active rung touched (the clause at the end of
# this body: the changed-file derivation, one measured tree, and `drive_key`
# per touched drive — seconds, and nothing when no drive was touched).
#
# UNPIPED, and its exit status is the gate's: 2 is "the census could not look"
# (no `git ls-files`, a stale pin, an unreadable table) and 2 outranks a pass
# everywhere in this file. There is no exit 1 here — a tree and its census
# disagreeing is not a lesser finding, it is the doc no longer describing the
# tree.
#
# THE BODY IS `instrument_census`, DEFINED ABOVE THE LEASE, and `--census` calls
# that same function with no leg banner around it. One body: a finishing
# builder's `--census` and this leg cannot come to different answers, and the
# refusal text is written once.
set +e
instrument_census
CENSUS_RC=$?
set -e
if [ "$CENSUS_RC" != "0" ]; then
    exit 2
fi
# AND EVERY DRIVE THE ACTIVE RUNG TOUCHED DECLARES WHAT ITS BODY READS. A drive
# is an instrument this leg censuses, and its `# drives:` line is the half of
# its honesty the selftest leg keys it on — so the key is decided HERE, in the
# tier the hook runs, by the one function the selftest leg calls (`drive_key`,
# through `drive_keys_of_touched` in scripts/gate_ledger.sh), refusing in that
# leg's own sentence. It joins this leg rather than being one, so the unit
# table and `--list-legs` do not move. `--census` stays the census alone.
DRIVE_KEYS_CHANGED=$(mktemp "${TMPDIR:-/tmp}/djb-drive-keys-changed.XXXXXX")
gate_refuse_reset
set +e
secrets_scan_changed_files "$DRIVE_KEYS_CHANGED"
DRIVE_KEYS_RC=$?
set -e
if [ "$DRIVE_KEYS_RC" != "0" ]; then
    gate_cause
    rm -f "$DRIVE_KEYS_CHANGED"
    echo "!! the drive-key clause could not derive the active rung's changed files — see above." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
fi
set +e
drive_keys_of_touched "$DRIVE_KEYS_CHANGED"
DRIVE_KEYS_RC=$?
set -e
rm -f "$DRIVE_KEYS_CHANGED"
if [ "$DRIVE_KEYS_RC" != "0" ]; then
    echo "!! a drive the active rung touched COULD NOT KEY — its body spells a checkout" >&2
    echo "   path its \`# drives:\` line does not cover (every such path is named above)." >&2
    echo "   The selftest leg refuses it at exit 2 at the bank; this is that refusal," >&2
    echo "   at commit. Declare what the drive reads, or \`# cites:\` what it only names." >&2
    exit 2
fi
}
gate_run_body goalpost-census gate_leg_goalpost_census

leg queue-index "the queue's index vs its record — the generated index is what queue_index.py generates, every anchor has one index row and back, both ratchets hold"
gate_leg_queue_index() {
# THE DERIVED LEDGER, AND WHY IT IS A LEG RATHER THAN A HABIT. `queue.md` is
# now GENERATED from `queue-detail.md`: the record carries every row verbatim
# under a `### N<id>` anchor, and the index is one line per anchor. That split
# only holds while nothing edits the index by hand — and a hand-edited index is
# INVISIBLE. It renders, it reads correctly, every consumer parses it, and it
# quietly disagrees with the record about what the ordered backlog says. Two
# truths in one ledger is the exact defect the split was built to close, and it
# can be re-opened by one well-meaning edit in a hurry.
#
# IN `--fast`, for `goalpost-census`'s reason one leg up: pre-commit runs
# `--fast`, so every commit in every checkout answers this, and the answer costs
# two file reads and a regeneration in memory — no database, no network, no
# Django import, ~0.01s on this tree at 337 rows. The PM edits this ledger more
# often than anything else in the repository; the leg has to sit in the tier the
# PM's own commits pass through.
#
# THREE STATES, NOT TWO, and the instrument owns the distinction rather than
# this leg. The migration runs ONCE, by hand, at merge, so this check is
# registered on trees where the split has not happened yet. A `[ -f … ]` guard
# here could not tell a tree that was never split from one whose record was
# DELETED — it would answer both by skipping, which is the silent narrowing the
# whole instrument exists to refuse. So the discriminator is derived inside
# `scripts/queue_index.py --check` (the generated header, present or not), it
# prints which of the three states it found, and its exit status is this leg's:
# pre-split is 0 with a NAMED ABSENCE saying nothing was checked, a lost record
# and a half-migrated tree are both 2.
#
# UNPIPED, and 2 outranks a pass here as everywhere in this file. Driven case
# by case by `scripts/tests/test_queue_index.sh` in the selftest leg — including
# all three states above, each fed its own tree.
gate_refuse_reset
# THE CHECKOUT'S OWN INTERPRETER, for the reason `instrument_census` gives
# above: `scripts/queue_index.py` is this repository's file and it is written at
# 3.12. On Amazon Linux 2023 the system `python3` is 3.9, and this leg's first
# off-box run reported `docs/product/queue.md is not what queue_index.py
# generates` over a `TypeError: zip() takes no keyword arguments` — the wrong
# finding, about the wrong file, in the one document every other document defers
# to for order.
QUEUE_INDEX_PY=$(checkout_python) || {
    gate_refuse "the queue index could not be checked: this checkout has no .venv/bin/python"
    echo "   and scripts/queue_index.py is a file this repository pins at the version" >&2
    echo "   that venv holds. Run ./scripts/setup.sh (or \`uv sync\`) first." >&2
    exit 2
}
set +e
"$QUEUE_INDEX_PY" scripts/queue_index.py --check
QUEUE_INDEX_RC=$?
set -e
if [ "$QUEUE_INDEX_RC" = "2" ]; then
    gate_cause
    echo "!! the queue index COULD NOT BE CHECKED — see above." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    echo "   Nothing was judged. An index whose record is gone, or a record beside an" >&2
    echo "   index somebody replaced by hand, is not a clean ledger — it is a ledger" >&2
    echo "   nobody can read against its own source." >&2
    exit 2
elif [ "$QUEUE_INDEX_RC" != "0" ]; then
    echo "!! docs/product/queue.md is not what scripts/queue_index.py generates from" >&2
    echo "   docs/product/queue-detail.md, or the two disagree about a row, or a" >&2
    echo "   ratchet was passed. The index is DERIVED: edit the record and run" >&2
    echo "   \`${QUEUE_INDEX_PY} scripts/queue_index.py --index\` — this checkout's own" >&2
    echo "   interpreter, which is what the generated header names too. A hand-edited" >&2
    echo "   index is two truths in the one file every other document defers to for" >&2
    echo "   order." >&2
    exit "$QUEUE_INDEX_RC"
fi
}
gate_run_body queue-index gate_leg_queue_index

leg db-pin "DATABASE_NAME: this checkout's .env pin vs the derivation"
gate_leg_db_pin() {
# THE SPLIT-BRAIN, WITH AN EXIT STATUS. `scripts/db.sh` derives
# this checkout's database name from the checkout's own path; `.env` is what a
# bare `manage.py` reads. When those two disagree, one checkout has TWO
# databases: the scripts migrate, seed and gate one of them, and every
# `manage.py` a human types reaches the other. That is not a hypothetical —
# it is how a PM debugging a 500 migrated and minted tokens into the OWNER'S
# live development database, with every individual step of it legal.
#
# IT WAS ALREADY BEING SAID, AND SAYING IT DID NOT WORK. db.sh printing a
# stderr note on every source was not enough: a census still found the main
# checkout's pin stale a full day later, with dozens of stale worktree pins
# beside it — proven silence with extra steps. A note is answered when somebody
# feels like it; a leg is answered before the commit lands.
#
# IN `--fast`: pre-commit runs `--fast`,
# so every commit in every checkout answers this, and `--loop` and the full
# gate inherit it by running the fast legs first. It costs one `grep` and one
# `shasum` over a path — no database, no network, no Django import, no docker.
#
# `# pinned` PASSES SILENTLY. A pin is legal (db.sh rule 1) and the marker is
# how a checkout says it meant this one; setup.sh already reads the same marker
# before deciding whether to rewrite the line. A pin without the marker is the
# thing that has never once been deliberate.
#
# The body is `db_pin_leg` in `scripts/db.sh` — a sourced lib, so the drive can
# aim it at a throwaway checkout without a copy or a stub — and it is driven
# case by case by `scripts/tests/test_db_pin.sh` in the selftest leg.
#
# Exit semantics are this file's: 2 is could-not-look (an .env in the tree that
# cannot be read) and outranks a pass; 1 is a stale pin.
gate_refuse_reset
set +e
db_pin_leg "$(if [ "$MODE" = --fast ]; then echo fast; elif [ "$MODE" = --loop ]; then echo loop; else echo full; fi)" # the mode the leg binds existence under (`--pr`/`--bank` normalise to "" above, so they get `full`). An `if` and not a `case`: a `case` pattern's `)` closes the `$(` around it. The operands are UNQUOTED on purpose: `[ "$MODE" = "--fast" ]` is the literal two other drives find this file's `--fast` early exit by (test_gate_lease.sh, test_db_pin.sh), and a second copy of it moves their line number to here.
DB_PIN_RC=$?
set -e
if [ "$DB_PIN_RC" = "2" ]; then
    gate_cause
    echo "!! the db-pin leg COULD NOT LOOK — see above. An unread .env is not an" >&2
    echo "   absent one: nothing was compared, so this is neither a finding nor a pass." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
elif [ "$DB_PIN_RC" != "0" ]; then
    exit "$DB_PIN_RC"
fi
}
gate_run_body db-pin gate_leg_db_pin

# --- the archaeology leg, in the tier the HOOK runs -------------------------
# THE PLATFORM'S CONSTRUCTION HISTORY IS NOT THE PRODUCT'S — the same invariant
# `publish.sh`'s release-time `archaeology-census` leg proves over the whole
# exported artifact, brought forward so a builder meets a finding id, a rung
# token or a private name AT THE COMMIT THAT WRITES IT.
#
# IT LIVES IN `--fast`, AND THE TIER IS THE WHOLE POINT OF THE LEG. It ran in
# `--loop` only, which is the per-rung gate — and the per-rung gate is not what
# stands between a maintainer's shorthand and a commit. Pre-commit runs
# `--fast`, so a `--loop`-only census caught the id AFTER the commit that
# carried it: five of six builders in one wave shipped one, each learning it
# from a several-minute loop run and paying a scrub commit for it. Moving the
# census one tier down answers it at the hook, where the fix is the line the
# author still has in their head.
#
# IT COSTS THIS TIER ALMOST NOTHING, which is why it can sit here at all: it
# reads the SAME narrowed changed-file set the secret scan derives
# (`secrets_scan_changed_files`, no database, no network, no Django import) and
# then narrows FURTHER, to the bucket-SHIP subset — a rung that only touched a
# SKELETON ledger (docs/product/queue.md and its kin, which are FULL of finding
# ids and rung tokens by design) must not redden here, and the bucket
# classifier is what tells the two apart. Sub-second on this tree; the leg
# prints its own wall time like every other.
#
# `--loop` AND THE FULL GATE INHERIT IT by running the fast legs first, so there
# is exactly ONE call site. There was briefly a second, in the `--loop` block,
# and a second call site for a leg whose whole subject is duplication would have
# been the finding it exists to catch. See scripts/archaeology_lib.sh for the
# six patterns, the classifier, and why they are shared with publish.sh rather
# than duplicated.
#
# AND IT IS NOT THE ONLY SPLIT LEG ANY MORE — THE DECLARATION, in full. Three of
# `publish.sh`'s release-time legs now have a per-rung half here, each the SAME
# BODY over a different file set, and the pairing is stated once rather than
# rediscovered per leg:
#
#   leg                per rung (this file)              at publish (publish.sh)
#   -----------------  --------------------------------  ----------------------
#   archaeology        the changed SHIP-bucket files     the whole artifact
#   adr-census         the changed files                 the whole artifact
#   dangling-docs      the changed files                 the whole artifact
#
# In every row the per-rung half is the CHEAP EARLY READER and the publish half
# is the BELT: a dead citation in a file the active rung did not touch is
# invisible to the per-rung leg by design, and is caught at release. The bodies
# are `archaeology_loop` (scripts/archaeology_lib.sh) and `docs_adr_census_loop`
# / `docs_dangling_docs_loop` (scripts/docs_legs.sh); all three narrow through
# the ONE changed-file derivation, `secrets_scan_changed_files`, and all three
# print the basis they derived them from, because a narrowed scan that does not
# say what it narrowed to is a reader taking "no findings" for "the tree is
# clean". `byte-identity` is the fourth publish leg and has NO per-rung half:
# its question is "does the exported artifact match the source", which a tree
# with no artifact in it cannot be asked.
#
# THE TWO LEGS AFTER THEM — `loop-names` and `ci-env` — ARE NOT SPLITS. Neither
# has a release-time half; both are whole-tree closed questions cheap enough to
# ask at every commit, and they are here rather than in `--loop` for the
# archaeology leg's own reason: pre-commit runs `--fast`, and a census that only
# the per-rung gate reads answers AFTER the commit that carried the defect.
leg archaeology "archaeology-census over THE ACTIVE RUNG'S CHANGED SHIP-BUCKET FILES ONLY — publish.sh's full-artifact scan stays the belt at release"
gate_leg_archaeology() {
gate_refuse_reset
set +e
archaeology_loop
ARCH_RC=$?
set -e
if [ "$ARCH_RC" = "2" ]; then
    gate_cause
    echo "!! the archaeology-census leg COULD NOT DERIVE the changed-file set, or a" >&2
    echo "   scan could not read them — see above. Nothing was judged." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
elif [ "$ARCH_RC" != "0" ]; then
    exit "$ARCH_RC"
fi
}
gate_run_body archaeology gate_leg_archaeology

# --- the two split docs censuses, per rung ----------------------------------
# Bodies: `docs_adr_census_loop` and `docs_dangling_docs_loop`
# (scripts/docs_legs.sh). Same narrowing, same basis line and the same exit
# grammar as the archaeology leg above: 0 clean · 1 a finding · 2 could-not-look.
leg adr-census "every ADR id cited in THE ACTIVE RUNG'S CHANGED FILES resolves in the tree's two ADR homes — publish.sh's whole-artifact scan stays the belt"
gate_leg_adr_census() {
gate_refuse_reset
set +e
docs_adr_census_loop
ADR_CENSUS_RC=$?
set -e
if [ "$ADR_CENSUS_RC" = "2" ]; then
    gate_cause
    echo "!! the adr-census leg COULD NOT LOOK — see above. The changed-file set, an" >&2
    echo "   ADR home or the citation scan was unreadable, so nothing was judged: this" >&2
    echo "   is neither a finding nor a pass." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
elif [ "$ADR_CENSUS_RC" != "0" ]; then
    exit "$ADR_CENSUS_RC"
fi
}
gate_run_body adr-census gate_leg_adr_census

leg dangling-docs "every docs/ pointer spelled in THE ACTIVE RUNG'S CHANGED FILES exists in the tree — publish.sh's whole-artifact scan stays the belt"
gate_leg_dangling_docs() {
gate_refuse_reset
set +e
docs_dangling_docs_loop
DANGLING_RC=$?
set -e
if [ "$DANGLING_RC" = "2" ]; then
    gate_cause
    echo "!! the dangling-docs leg COULD NOT LOOK — see above. The changed-file set or" >&2
    echo "   the pointer scan was unreadable. Nothing was judged." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
elif [ "$DANGLING_RC" != "0" ]; then
    exit "$DANGLING_RC"
fi
}
gate_run_body dangling-docs gate_leg_dangling_docs

# --- the LOOP_* name census -------------------------------------------------
# A FORK'S FAILURE MODE, MADE CHEAP. A product that forked the loop scope and
# kept a refusal block reading a `LOOP_*` name this platform no longer sets does
# not die at the line that reads it: it dies minutes later, at the pytest
# banner, under `set -u`, naming a variable nobody has heard of. The first
# consumer spent four `--loop` runs on it. Body: `docs_loop_names_leg`
# (scripts/docs_legs.sh), which also states the one exclusion that makes the
# answer honest — a defaulted read cannot die and is therefore not a violation.
leg loop-names "every LOOP_* name check.sh reads is assigned by check.sh, loop_tier.sh or gate_ledger.sh — a fork that kept a refusal block reading a name the platform no longer sets dies at the pytest banner under set -u"
gate_leg_loop_names() {
gate_refuse_reset
set +e
docs_loop_names_leg
LOOP_NAMES_RC=$?
set -e
if [ "$LOOP_NAMES_RC" = "2" ]; then
    gate_cause
    echo "!! the loop-names leg COULD NOT LOOK — see above. One of the reader or" >&2
    echo "   assigner files is not in this tree, or the reader named no LOOP_* at all;" >&2
    echo "   a grep that found nothing is not a tree with nothing in it." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
elif [ "$LOOP_NAMES_RC" != "0" ]; then
    exit "$LOOP_NAMES_RC"
fi
}
gate_run_body loop-names gate_leg_loop_names

# --- the ci-env census, tri-state -------------------------------------------
# THE RUNNER'S STACK IS THE ONE THE SETTINGS DESCRIBE. One CI run of this very
# repository ended with 110 errors, every one of them botocore's no-credentials
# exception, in the one environment that had a healthy object store on its own
# port — because the workflow's `env:` block named none of the keys the settings
# read. 39 of 40 runs red and nothing said why. Body: `docs_ci_env_leg`
# (scripts/docs_legs.sh); it prints its derived population, the names it left
# out and why, and its own blind spots on every clean run. TRI-STATE: a product
# with no workflow file gets a PRINTED skip, never silence.
leg ci-env "every AWS_* name the settings read from the environment is a key in the workflow's env — the runner's stack is the one the settings describe"
gate_leg_ci_env() {
gate_refuse_reset
set +e
docs_ci_env_leg
CI_ENV_RC=$?
set -e
if [ "$CI_ENV_RC" = "2" ]; then
    gate_cause
    echo "!! the ci-env leg COULD NOT LOOK — see above. The settings file, the" >&2
    echo "   development stack's own values or the workflow's indentation was" >&2
    echo "   unreadable, or the derived population came out empty." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    echo "   A green over nothing is the one verdict this leg may never print." >&2
    exit 2
elif [ "$CI_ENV_RC" != "0" ]; then
    exit "$CI_ENV_RC"
fi
}
gate_run_body ci-env gate_leg_ci_env

if [ "$MODE" = "--fast" ]; then
    # THE PRODUCT'S FAST-TIER LEGS, INSIDE THE FAST BLOCK AND INDENTED. Indented
    # because that is this file's own rule for a leg that belongs to ONE mode:
    # the listing reads column-zero call sites, and a second column-zero
    # `leg local-legs` would put the drawer at the wrong place in the full
    # gate's announced sequence. `--fast` is where a product's typecheck and
    # lint belong, and `touches:` may skip one here because a narrowed mode is
    # allowed to (the full gate is not).
    if [ -n "$LOCAL_LEGS_MEMBERS" ] && [ -n "$(local_legs_tier_any fast)" ]; then
        leg local-legs "the product's own legs (scripts/local/legs/), tier fast — declared beside this file, never in it"
        LOCAL_LEGS_MODE_TIER=fast
        LOCAL_LEGS_TOUCH_FILTER=1
        LOCAL_LEGS_RUN_RC=0
        gate_run_body local-legs gate_leg_local_legs || LOCAL_LEGS_RUN_RC=$?
        [ "$LOCAL_LEGS_RUN_RC" = "0" ] || exit "$LOCAL_LEGS_RUN_RC"
    fi
    leg_done
    echo "ok: fast checks passed ($(($(date +%s) - T_MODE_START))s)"
    echo "  NOT run: check --deploy, pytest, canary self-test, the shell refusal drives,"
    echo "           supply chain (the secret scan runs in --loop, and the --loop"
    echo "           copy reads only the active rung's changed files; the"
    echo "           full-tree scan, pip-audit and licences are all at push),"
    echo "           temporal census, own-tree machinery census."
    echo "  --loop is the per-rung gate; the full gate binds at push."
    exit 0
fi

# --- the --loop legs ---------------------------------------------------------

leg deploy-check "check --deploy (production settings, throwaway env)"
gate_leg_deploy_check() {
# The point is the SETTINGS, not the secrets: throwaway strong values, DEBUG
# off, a real-looking host. --fail-level WARNING is what makes this a gate leg
# — check --deploy reports almost everything as a warning.
DJB_GATE_SECRET="$(uv run python -c 'import secrets; print("gate-only-" + secrets.token_hex(32))')"
DJB_GATE_FERNET="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
# Third throwaway, and it is here for exactly the reason the first two are:
# this worktree's .env carries the published `DATABASE_PASSWORD=djb`, and
# production now refuses to start on it. `check --deploy` opens no connection —
# it reads settings — so any strong value serves, and generating one keeps this
# leg's meaning "the SETTINGS are right" rather than "somebody remembered to
# export a password".
DJB_GATE_DB_PASSWORD="$(uv run python -c 'import secrets; print("gate-only-" + secrets.token_urlsafe(24))')"
DJANGO_SETTINGS_MODULE=config.settings.production \
    DEBUG=0 \
    ALLOWED_HOSTS=example.invalid \
    SECRET_KEY="$DJB_GATE_SECRET" \
    CONNECTIONS_ENCRYPTION_KEY="$DJB_GATE_FERNET" \
    DATABASE_PASSWORD="$DJB_GATE_DB_PASSWORD" \
    uv run python manage.py check --deploy --fail-level WARNING
}
gate_run_body deploy-check gate_leg_deploy_check

# --- the fe leg: ON THE FULL PATH, and it used to be inside the --loop block
# below. A tri-state leg that prints `skip` when there is no client is still a
# leg that RAN, and a leg the full gate never announces is a leg no verdict row
# names and no runner is ever handed. It sits here, above the --loop block, so
# BOTH modes reach it through one call site: two call sites would be two legs
# with one name.
# --- the fe leg: three states, none of them inferred from a duration ----
# ABSENT — no frontend/ on this tree. This template's steady state, and a
# rule about a tree nobody has must not cost a Python-only product a red
# gate forever: a printed skip, never silence, because a skip that prints
# nothing is indistinguishable from a pass.
# UNTOUCHED — frontend/ exists and the active rung changed nothing under
# it. The fast path: nothing under frontend/ derives differently than it
# did before the active rung's changes, so nothing frontend-shaped is re-run, mirroring
# the own-app tiering the pytest leg above already applies one door over.
# AND IT IS `--loop`'s AND `--fast`'s ALONE: at the full mode and
# under `--leg` — one shard of that same full gate — the leg runs WHOLE,
# because a bank writes a verdict row naming `fe` as a leg that ran and the
# push wall reads that row as a full gate having passed these bytes. The
# mode reaches the state machine through the one call site below.
# FULL — frontend/ exists and either the active rung touched it or the mode
# runs it whole: the frozen-lockfile check runs, the declared test script
# (if any) runs, and the pair's measured seconds are printed.
# TOOLCHAIN ABSENT while frontend/ is present AND touched is exit 2, not
# a skip — the same tree-present/toolchain-absent cell
# `quality/worlds.py`'s `tree_verdict` names `broken` for a rules.yaml
# runner rule. One decision table, two homes (this leg is check.sh's own
# gate leg; that one is a rules.yaml rule's live-scan decision), kept in
# lockstep by citation since neither imports the other across a
# territory line — a rung that let the two disagree is the finding this
# comment exists to make checkable.
leg fe "the fe leg — three states (absent/untouched/full) over frontend/, the untouched fast path belonging to --loop and --fast alone while the full gate and its --leg shards run it whole, deferring to the same tree-present/toolchain-absent could-not-look cell quality/worlds.py's tree_verdict names for a runner rule"
gate_leg_fe() {
FE_CHANGED=$(mktemp "${TMPDIR:-/tmp}/djb-fe-changed.XXXXXX")
gate_refuse_reset
set +e
secrets_scan_changed_files "$FE_CHANGED"
FE_DERIVE_RC=$?
set -e
if [ "$FE_DERIVE_RC" != "0" ]; then
    gate_cause
    echo "!! the fe leg could not derive the active rung's changed files — see above." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    rm -f "$FE_CHANGED"
    exit 2
fi
set +e
# THE MODE IS HANDED OVER VERBATIM, and that is the whole of the fix. One
# call site, one leg, four modes: `""` (the full gate, and `--bank`/`--pr`
# which normalise to it) and `--leg` (one shard of that same full gate) run the
# frontend WHOLE; `--loop` and `--fast` keep the change-aware fast path that is
# a builder's inner-loop economy. Before this, every mode got the change-aware
# answer, so a bank on an untouched frontend printed `UNTOUCHED (fast path)`
# and `(fe: 0s)` and then banked a verdict row naming `fe` among the legs it
# had run. `scripts/fe_gate.sh`'s THE MODE block argues it; this line is the
# only place the gate says which mode it is in.
fe_leg_run "$FE_CHANGED" "$MODE"
FE_RC=$?
set -e
rm -f "$FE_CHANGED"
if [ "$FE_RC" = "2" ]; then
    exit 2
elif [ "$FE_RC" != "0" ]; then
    exit "$FE_RC"
fi
}
gate_run_body fe gate_leg_fe

if [ "$MODE" = "--loop" ]; then
    # --- the secret scan, MOVED HERE from the supply-chain leg ------
    # It was push-side until a later measurement showed what that cost:
    # detect-secrets was the window's most productive push-time guard AND its
    # most prolific false-positive producer, and EVERY false positive surfaced
    # at the most expensive moment there is — a push, at the end of a full gate,
    # usually with a merge already made and a PM waiting. A builder meets the
    # `# pragma: allowlist secret` line in-rung instead, where the string is
    # still in their head and the fix costs a minute.
    #
    # ONLY THIS SUB-LEG MOVED. `pip-audit` and the licence scan STAY push-side:
    # pip-audit is the one leg in the gate that leaves this machine (a network
    # hiccup must not be able to redden a per-rung run), and both judge the
    # dependency set, which a rung rarely touches. The secret scan reads only
    # this tree's own files — no network, no database.
    #
    # THE FULL GATE STILL RUNS IT TOO, in the supply-chain leg where it always
    # was. A MOVED LEG IS NOT A REMOVED LEG: the push must go on measuring what
    # it measured before, or the ledger's recorded verdict would quietly start
    # vouching for less than it used to.
    #
    # WHAT IT ACTUALLY COST, measured rather than assumed, and it was not what
    # the retro that ordered the move estimated: **~40s on every per-rung gate**
    # against the retro's "~1s" (measured in a worktree of 864 tracked files:
    # 19s warm, 28s cold, ~99% user CPU — the scan itself, and it scales with
    # the tree, not with the change). The PM decided to narrow the scope rather
    # than let it be patched quietly here.
    #
    # --- THE RULING, IMPLEMENTED --------------------------------
    # THE `--loop` COPY SCANS ONLY THE FILES THE ACTIVE RUNG CHANGED — the merge-base
    # with the local `main`, plus everything staged or uncommitted. The whole
    # ratified benefit survives, because a false positive a rung produces is by
    # construction in a file that rung touched; the price falls from ~40s to
    # about a second. THE FULL-TREE SCAN STAYS AT PUSH, unchanged, in the
    # supply-chain leg — a narrowed leg is not a removed leg, and the recorded
    # verdict goes on vouching for exactly what it vouched for before.
    #
    # The derivation, its edge cases (on main, an empty change set, deletions,
    # a worktree's merge-base) and the sentence it prints live in
    # `scripts/secrets_scan.sh`, driven case by case by
    # `scripts/tests/test_secrets_scan.sh` in the selftest leg. Read that file
    # before changing what this leg claims: the entire risk of the narrowing is
    # a reader taking a green leg to mean the tree is clean when it means six
    # files are, which is why the leg prints its basis and its blind spots every
    # single run instead of only when something is wrong.
    leg secrets "detect-secrets vs .secrets.baseline — THE ACTIVE RUNG'S CHANGED FILES ONLY; the full-tree scan, pip-audit and licences stay push-side"
    gate_leg_secrets() {
    gate_refuse_reset
    set +e
    secrets_scan_loop
    SECRETS_RC=$?
    set -e
    if [ "$SECRETS_RC" = "2" ]; then
        gate_cause
        echo "!! the secret scan COULD NOT DERIVE the active rung's changed files — see above." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        echo "   An underived set is not an empty set: nothing was judged, so this is" >&2
        echo "   neither a finding nor a pass." >&2
        exit 2
    elif [ "$SECRETS_RC" != "0" ]; then
        exit "$SECRETS_RC"
    fi
    }
    gate_run_body secrets gate_leg_secrets

    # --- THE ALWAYS-ON LEG: what the bank sees, at every scope ---------------
    #
    # HERE, ABOVE THE PYTEST LEG, AND THAT IS DELIBERATE. Every member of this
    # set is single-digit seconds or a reused row, and the pytest leg below is
    # the one that queues for a slot: a red found here is found before the
    # expensive thing starts, and the leg holds nothing while it looks. The
    # derivation, the two halves and the declared blind spots are the
    # `always-on-leg` fence above — read that before changing what this claims.
    leg always-on "the full-only members the loop can afford — drives declaring themselves cross-app (always, whatever the price) plus every member the committed measurement puts under the floor; each consulted against its banked drive verdict first"
    gate_leg_always_on() {
    set +e
    always_on_leg
    ALWAYS_ON_RC=$?
    set -e
    if [ "$ALWAYS_ON_RC" != "0" ]; then
        exit "$ALWAYS_ON_RC"
    fi
    }
    gate_run_body always-on gate_leg_always_on

    # THE ARCHAEOLOGY LEG USED TO SIT HERE. It is now one tier down, among the
    # `--fast` legs this mode runs before it reaches this line, for the reason
    # written beside it there: the hook is what let the id through, and the hook
    # runs `--fast`. This mode still runs the census exactly once, and the leg's
    # text, patterns, classifier and allow-list did not change.

    # --- the pytest TIER, derived --------------------------------------
    # `--loop` runs ONE OF TWO THINGS, and it says which every run:
    #
    #   * THE FAST TIER plus the active rung's own app in full — the ordinary case. The
    #     slow tier is every test that reaches a real organ (the compose MinIO, a
    #     real time-skipping Temporal server, the compose Meilisearch), DERIVED
    #     from organ-fixture reach and module source, never from a hand-marked
    #     list (`apps/conftest.py` argues both halves and carries the floors that
    #     refuse rather than pass when the derivation stops answering).
    #   * THE FULL SUITE, when the active rung changed SHARED TEST INFRASTRUCTURE — a
    #     file no app owns that every app's tests stand on. A shared fixture has
    #     whole-suite blast radius by construction, and that change class is
    #     where loop-time discovery is worth most; it is also rare, so it costs
    #     almost nothing across a cycle. The enumeration and its argument are in
    #     `scripts/loop_tier.sh`. In this branch the leg runs the byte-identical
    #     command it ran before the tier existed — no tier flag at all.
    #
    # THE FULL GATE AT PUSH RUNS EVERYTHING, TWICE, UNCHANGED. A tiered leg is
    # not a removed leg; it moves organ-suite discovery from loop-time to
    # push-time, which is the cycle plan's declared trade and the reason the
    # banner below says so on every single run rather than only when something
    # is wrong.
    #
    # The own-app half is a MAPPING over the secret scan's changed-file set,
    # not a second derivation of it — see scripts/loop_tier.sh. It is
    # derived AFTER the leg announces itself, so its cost and any refusal land
    # under the pytest leg's name rather than silently inside the last one's.
    leg pytest "pytest (ONE pass, a FRESH random seed, ONE OF THIS MACHINE'S PYTEST SLOTS — the fast tier plus the active rung's own app, or the WHOLE suite when the active rung changed shared test infrastructure; the full gate at push runs two whole-suite passes under one seed, which is where idempotency is proven)"
    gate_leg_pytest() {
    # THE SLOT, TAKEN HERE AND NOWHERE ELSE IN THIS MODE. `--loop` takes no
    # lease — a builder must never queue behind somebody else's push — but it
    # does take a slot, because the thing that flattened the box was not one
    # gate, it was ELEVEN `--loop` runs each starting `pytest -n auto` on the
    # same ten cores (load 162, 5-8x wall clock, two runs killed having judged
    # nothing). The slot is released by the EXIT trap installed with it, so a
    # killed leg gives it back; the semaphore's stale-clear is the belt.
    #
    # Everything before this line — ruff, mypy, the secret scan — took nothing
    # and waited for nothing. The queue starts where the cost is.
    # >>> loop-docs-only-reuse >>>
    # THE ONE LEG THIS GATE CAN DECLINE TO RUN, AND IT DECLINES ONLY ON THE
    # ANSWER THE CONSULT ALREADY PRINTED. `loop_docs_only_reuse`
    # (scripts/gate_ledger.sh) said the whole delta since the banked head is
    # under `docs/`, that no changed docs path is spelled in any module under
    # `apps/`, and that the working tree is clean — so the banked pytest
    # verdict is a verdict about a suite this delta cannot have moved.
    #
    # EVERY OTHER LEG ALREADY RAN. They are above this line, unguarded: ruff,
    # mypy, the secret scan, the censuses, db-pin, deploy-check. The saving is
    # the 200-250 s pass, never the ~30 s of legs, and the legs are what would
    # catch a docs commit that broke something a census reads.
    #
    # NO SLOT IS TAKEN ON THIS PATH. The queue starts where the cost is, and on
    # this path there is no cost — a reuse that held one of this box's two
    # pytest slots would be charging the wave for a pass it did not run. That
    # is also why the `workers:` line below is inside the `else`: this path
    # derives no worker count, so it must not print a sentence about one.
    if [ -n "$LOOP_PYTEST_REUSE" ]; then
        echo "  pytest: REUSED from the banked verdict on ${LOOP_REUSE_TREE} (docs-only delta: ${LOOP_REUSE_N} path(s), none spelled in a module under apps/)"
        echo "          Every other leg above this one RAN. What is reused is the pytest"
        echo "          pass alone, and only because nothing outside docs/ moved since that"
        echo "          verdict was measured. Force a re-measure with DJB_LOOP_NO_CACHE=1."
        PYTEST_RC=0
    else
        trap 'heartbeat_stop; gate_slot_release' EXIT
        gate_refuse_reset
        set +e
        gate_slot_acquire loop
        SLOT_RC=$?
        set -e
        if [ "$SLOT_RC" != "0" ]; then
            gate_cause
            echo "!! no pytest slot — see above. Nothing was judged about this tree." >&2
            echo "   cause: ${GATE_LAST_REFUSAL}" >&2
            exit 2
        fi
        # THE SCOPE WAS ALREADY DERIVED, above the first leg, because the loop
        # ledger's key needs it before there is anything to consult. It is NOT
        # re-derived here: one derivation, one answer, and no second thing to keep
        # in step. Its refusal (exit 2) fired up there, under its own banner.
        #
        # THE RULE IS PRINTED EVERY RUN, whichever branch it took. A tier chosen in
        # silence is an unfalsifiable one, and that is as true of the full suite as
        # it is of the fast tier — a reader who cannot see WHY the leg ran
        # everything cannot tell a deliberate full run from a broken derivation.
        echo "  tier basis: ${LOOP_TIER_BASIS}"
        echo "  tier rule:  ${LOOP_TIER_REASON}"
        if [ "$LOOP_TIER_MODE" = "full" ]; then
            echo "  shared test infrastructure the active rung changed: ${LOOP_TIER_SHARED_HITS}"
            echo "  (the enumeration and why each member is in it: scripts/loop_tier.sh)"
        fi
        # THE DECLARED CROSS-APP CENSUSES, NAMED WITH THEIR REASONS. A scope
        # narrows the suite and leans on the always-on set for everything that
        # quantifies over the whole tree; two thirds of that set is DERIVED and
        # needs no listing, and the last third is a module's own DECLARATION. A
        # declaration nobody can enumerate is one nobody audits, so the run that
        # leans on it prints it — the same argument the tier rule above is
        # printed for. The reason is the module's own sentence, so a reader who
        # disagrees with one has the module's path in front of them.
        LOOP_CENSUS_RC=0
        LOOP_CENSUS_LIST=$(loop_scope__declared_censuses apps) || LOOP_CENSUS_RC=$?
        if [ "$LOOP_CENSUS_RC" != "0" ]; then
            echo "!! the --loop scope COULD NOT READ the declared cross-app censuses — see" >&2
            echo "   above. Nothing was judged about this tree: a marked module this could" >&2
            echo "   not read is one the scope would deselect as if it had declared nothing." >&2
            exit 2
        fi
        if [ -z "$LOOP_CENSUS_LIST" ]; then
            echo "  always-on censuses (declared): (none declared)"
        else
            # NOT `LOOP_*` NAMES, deliberately: the loop-names leg reads
            # assignments and does not see a `read -r` target, so a `LOOP_`
            # prefix here would be a standing violation of a census that is not
            # this line's to change.
            while IFS="$(printf '\t')" read -r DECLARED_CENSUS_MODULE DECLARED_CENSUS_REASON; do
                echo "  always-on censuses (declared): ${DECLARED_CENSUS_MODULE} — ${DECLARED_CENSUS_REASON}"
            done <<EOF
${LOOP_CENSUS_LIST}
EOF
        fi
        # A fresh seed on purpose, and the one place in the gate that takes one.
        # Ordering couplings are found by *varying* the order, and `--loop` is the
        # tier where a builder is watching, has the tree in their head, and can fix
        # the test rather than pin the order. pytest prints the seed it chose; a red
        # run replays with `./scripts/test.sh --randomly-seed=<that seed>`.
        #
        # THE EXIT STATUS IS MAPPED, AND ONLY UPWARDS. 0 and 1 are pytest's and are
        # passed through byte-for-byte. 3 (internal error), 4 (usage error — which
        # is what the tier's own floors raise) and 5 (nothing collected — which is
        # what a tier that deselected the world would look like) are all "the suite
        # did not run", and this file has one word for that: 2, could-not-look,
        # which outranks a pass. Before this mapping existed they surfaced as bare
        # 3/4/5 from `set -e`, which no reader of this gate has a meaning for.
        #
        # TWO CALL SITES RATHER THAN ONE ARRAY THAT IS SOMETIMES EMPTY, and that is
        # not a style choice: this runs under macOS's bash 3.2, where expanding an
        # EMPTY array as `"${ARR[@]}"` under `set -u` is an unbound-variable death,
        # not an empty expansion. The `full` branch therefore passes NO tier flag at
        # all — which is also the honest thing for it to do, because that is the
        # byte-identical command this leg ran before the tier existed.
        #
        # `-n $GATE_SLOT_WORKERS`, NEVER `-n auto`, and the banner says the number
        # and why on every run. `auto` is one worker per core, which is the right
        # answer for a machine running one suite and the wrong answer for a machine
        # running N. The arithmetic the semaphore keeps: N slots x cores/N workers
        # = this machine's cores, however many gates are live.
        # ONE SENTENCE, FROM WHERE THE NUMBER IS DECIDED — the pytest-x2 leg's line
        # is the same interpolation for the same reason: a parenthetical written here
        # is a second opinion about a number this file did not derive, and it was
        # wrong whenever DJB_GATE_SLOT_WORKERS was typed. The builder watching a
        # `--loop` is the reader most likely to have typed it.
        echo "  workers:    -n ${GATE_SLOT_WORKERS} (${GATE_SLOT_WORKERS_PHRASE})"
        echo "              NOT -n auto: auto is every core, and it is every core in each of"
        echo "              the ${GATE_SLOT_TOTAL} gates that may be running. Override the slot count with"
        echo "              DJB_GATE_SLOTS."
        # The nominal this pass will be measured against, and WHERE IT CAME FROM.
        # Printed at leg start rather than only inside a waiter's estimate, because
        # the reader who needs it most is the one watching this leg, not the one
        # queued behind it.
        gate_pytest_nominal "$GATE_SLOT_NOMINAL_LOOP" GATE_SLOT_NOMINAL_LOOP \
            "$(loop_ledger_path 2>/dev/null || true)"
        heartbeat_start "pytest" "$GATE_PYTEST_NOMINAL" "$GATE_PYTEST_NOMINAL_PROV"
        set +e
        if [ "$LOOP_TIER_MODE" = "full" ]; then
            ./scripts/test.sh -n "$GATE_SLOT_WORKERS"
        else
            # TWO LISTS, TWO CLAIMS. `--djb-own-app` is the rung's TOUCHED apps and
            # means "run this in full, organ tests included" — the existing rule,
            # untouched. `--djb-scope` is that set plus the reverse-transitive
            # closure and means only "do not deselect this". Promoting the closure
            # to own-app would make an `apps/core` touch run every organ test in the
            # tree, which is slower than the tier this replaced.
            TIER_ARGS=(--djb-tier=fast)
            for TIER_APP in $LOOP_TIER_OWN_APPS; do
                TIER_ARGS+=("--djb-own-app=$TIER_APP")
            done
            # THE THIRD LIST, AND IT IS NEITHER OF THE OTHER TWO. A tests-only app
            # is not own (its organ tests stay push-side) and not in scope (nothing
            # widened to it through the declarations): it brings its own test tree,
            # the modules the rung edited, and the modules that import its test
            # package — derived inside pytest from the modules' own source.
            for TIER_APP in $LOOP_SCOPE_TESTS_ONLY; do
                TIER_ARGS+=("--djb-tests-only=$TIER_APP")
            done
            for TIER_TEST in $LOOP_SCOPE_CHANGED_TESTS; do
                TIER_ARGS+=("--djb-changed-test=$TIER_TEST")
            done
            # THE FOURTH LIST, AND IT IS THE ONLY ONE THE RUNG DID NOT NAME. A
            # changed file that DECLARES permission vocabulary seeds the core
            # census that reads it — one module, through the same flag, because
            # the reverse `depends_on` closure can never reach `core` (it is
            # everyone's dependency and nobody's dependant). The patterns and
            # what is deliberately NOT seeded are scripts/loop_tier.sh's header.
            for TIER_TEST in $LOOP_SCOPE_SEEDED_TESTS; do
                TIER_ARGS+=("--djb-changed-test=$TIER_TEST")
            done
            # THE FIFTH LIST, AND IT NARROWS NOTHING BY ITSELF. Every file the
            # active rung changed, so a DECLARED cross-app census that names a
            # `population=` can sit out a run whose changed files are all
            # outside it (apps/conftest.py). Behind the same switch as the map
            # below: `--mine` passes the flags it passed before.
            if [ -n "${LOOP_IMPACT:-}" ]; then
                for TIER_FILE in $LOOP_SCOPE_CHANGED_FILES; do
                    TIER_ARGS+=("--djb-changed=$TIER_FILE")
                done
            fi
            if [ -n "$LOOP_SCOPE_IMPACT_SELECT" ]; then
                # THE MAP ANSWERED, SO THE SCOPE IS NOT PASSED AT ALL. A
                # selection and a scope are two answers to one question and the
                # selection is the narrower; `--djb-scope=` beside it would
                # widen back exactly what the map was asked to narrow. The
                # counts file still rides, because the collector reconciliation
                # below is about whether every collector FINISHED, which is as
                # true of a selection as it is of a scope.
                #
                # THE SAME FLAGS `loop_scope__pytest_args` EMITS, and the two
                # builders differ in exactly one thing — this one asks for the
                # fast tier and the `--pr` one deliberately does not.
                # scripts/tests/test_loop_scope.sh holds them to each other.
                TIER_ARGS+=("--djb-impact-select=$LOOP_SCOPE_IMPACT_SELECT")
                LOOP_COUNTS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/djb-loop-counts.XXXXXX")
                TIER_ARGS+=("--djb-scope-counts=$LOOP_COUNTS_DIR")
            elif [ -n "$LOOP_SCOPE_NARROW" ]; then
                for TIER_APP in $LOOP_SCOPE_APPS; do
                    TIER_ARGS+=("--djb-scope=$TIER_APP")
                done
                LOOP_COUNTS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/djb-loop-counts.XXXXXX")
                TIER_ARGS+=(--djb-scope-narrow "--djb-scope-counts=$LOOP_COUNTS_DIR")
            fi
            ./scripts/test.sh -n "$GATE_SLOT_WORKERS" "${TIER_ARGS[@]}"
        fi
        PYTEST_RC=$?
        set -e
        heartbeat_stop
    fi
    # <<< loop-docs-only-reuse <<<

    # --- THE SCOPE BANNER, BEFORE THE VERDICT DISPATCH -------------------
    #
    # BEFORE, and that is the whole point of where it sits: a RED `--loop` still
    # discloses the scope it graded the rung at. A banner printed only on the
    # green path is a banner that goes missing exactly when a reader is asking
    # "did it even run my test?".
    #
    # RECONCILE, NEVER SUM. Every collector performs its OWN full collection —
    # under xdist the workers collect and the controller only compares their
    # lists — so all N of them derive the same three counts and adding them up
    # multiplies the answer by the worker count. The counts files are compared
    # against each other and a disagreement is EXIT 2: two collectors that saw
    # different suites have not measured one thing, and a verdict banked under a
    # scope one of them disowned is a verdict about nothing.
    LOOP_BANNER_RC=0
    # EVERY REFUSAL IN THIS BLOCK GOES THROUGH THE SEAM, and the reset is what
    # keeps the banner at the bottom from printing a cause belonging to some
    # earlier, already-handled refusal (scripts/gate_refuse.sh).
    gate_refuse_reset
    if [ -n "$LOOP_COUNTS_DIR" ]; then
        LOOP_COUNT_FILES=$(find "$LOOP_COUNTS_DIR" -type f 2>/dev/null | sort)
        if [ -z "$LOOP_COUNT_FILES" ]; then
            gate_refuse "the --loop scope banner has NO counts file to read: not one collector"
            echo "   wrote into ${LOOP_COUNTS_DIR}. The scope was asked for and nothing" >&2
            echo "   reported deriving it, so what ran is unknown." >&2
            LOOP_BANNER_RC=2
        else
            # READ WHOLE, THEN SLICE — never `printf … | head -1`. Under this
            # file's `set -o pipefail` the reader closes the pipe on the first
            # line, the producer takes SIGPIPE on anything past the kernel's
            # 64 KiB pipe buffer, and the pipeline's status becomes 141 with the
            # right value already in hand. A wide `-n` over long app paths
            # reaches that size honestly, so the gate would have died here on a
            # big run and nowhere else. `scripts/tests/test_pipefail_readers.sh`
            # runs THIS line against a padded listing.
            LOOP_COUNT_FIRST=${LOOP_COUNT_FILES%%$'\n'*}
            for LOOP_COUNT_FILE in $LOOP_COUNT_FILES; do
                if ! cmp -s "$LOOP_COUNT_FIRST" "$LOOP_COUNT_FILE"; then
                    gate_refuse "THE COLLECTORS DISAGREE ABOUT THE SCOPE."
                    echo "   ${LOOP_COUNT_FIRST##*/}:" >&2
                    sed 's/^/     /' "$LOOP_COUNT_FIRST" >&2
                    echo "   ${LOOP_COUNT_FILE##*/}:" >&2
                    sed 's/^/     /' "$LOOP_COUNT_FILE" >&2
                    echo "   Every collector performs its own FULL collection, so these must" >&2
                    echo "   be identical. They are not, so this run did not measure one" >&2
                    echo "   thing and no verdict is banked." >&2
                    LOOP_BANNER_RC=2
                    break
                fi
            done
            if [ "$LOOP_BANNER_RC" = "0" ]; then
                # THE PRE-RUN BANNER'S ABSENCE, NAMED BEFORE THE COUNTS THAT
                # SURVIVED IT. The banner prints only once every collector has
                # reported (apps/conftest.py's controller seam), so a worker
                # that died during collection takes it with it — and an absent
                # banner is indistinguishable from one that was never wired.
                # This says which, with its count — and the REFUSAL beside it is
                # what decides the run: a collector short of the number this
                # leg started is a suite that is not the suite that was asked
                # for, whatever pytest's own status says.
                LOOP_COUNT_N=$(printf '%s\n' "$LOOP_COUNT_FILES" | wc -l | tr -d ' ')
                set +e
                loop_counts_refuse_if_short "$LOOP_COUNT_N" "${GATE_SLOT_WORKERS:-0}" "$LOOP_COUNT_FIRST"
                LOOP_COUNTS_RC=$?
                set -e
                loop_scope__prerun_absence "$LOOP_COUNT_N" "${GATE_SLOT_WORKERS:-0}"
                [ "$LOOP_COUNTS_RC" = "0" ] || LOOP_BANNER_RC=2
            fi
            if [ "$LOOP_BANNER_RC" = "0" ]; then
                echo "  == the scope the active rung was graded at =="
                echo "  basis:      ${LOOP_TIER_BASIS}"
                echo "  scope:      ${LOOP_SCOPE_APPS:-(empty — no app is in scope)}"
                echo "  touched:    ${LOOP_SCOPE_TOUCHED:--}"
                echo "  tests-only: ${LOOP_SCOPE_TESTS_ONLY:--} (no closure walked; the edited modules: ${LOOP_SCOPE_CHANGED_TESTS:--})"
                echo "  widened by the reverse-transitive depends_on closure: ${LOOP_SCOPE_WIDENED:--}"
                echo "  shapes:     ${LOOP_SCOPE_SHAPES:--}"
                # THE MAP, BESIDE THE SCOPE IT REPLACED. On a selecting run the
                # three lines above describe a closure that did NOT run, and a
                # reader who saw only those would be reading the wrong scope
                # off a green run.
                loop_map_banner
                sed 's/^/  /' "$LOOP_COUNT_FIRST"
                echo "  (reconciled across $(printf '%s\n' "$LOOP_COUNT_FILES" | wc -l | tr -d ' ') collector file(s) — compared, never summed)"
                echo "  A REGRESSION IN A DESELECTED APP SURFACES AT THE WAVE BANK, NOT AT"
                echo "  THIS RUNG. That is the trade this narrowing makes, and it is printed"
                echo "  beside the number it was made for rather than written down elsewhere."
            fi
        fi
        rm -rf "$LOOP_COUNTS_DIR"
    fi
    # THE SELECTION FILE, REAPED WHERE THE COUNTS DIRECTORY IS. It is the only
    # thing this leg leaves outside the checkout, it is named for nothing a
    # later run reads, and the run it belonged to is over: the flags pytest
    # was handed are in the transcript above, which is the record.
    [ -z "${LOOP_SCOPE_IMPACT_SELECT:-}" ] || rm -f "$LOOP_SCOPE_IMPACT_SELECT"
    if [ "$LOOP_BANNER_RC" != "0" ]; then
        # THE CAUSE, WHERE THE READER IS STANDING. All three ways this block
        # refuses — no counts file, disagreeing collectors, a collector short of
        # the number the leg started — record their first `!!` line through the
        # seam, so this banner names one of them instead of pointing at an
        # "above" a report, a paste or a truncated log may not carry.
        gate_cause
        echo "!! the --loop scope could not be RECONCILED — see above." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        echo "   Nothing was judged about this tree and no verdict is banked: a scope the" >&2
        echo "   collectors did not agree on is not a scope anything can be graded at." >&2
        exit 2
    fi

    case "$PYTEST_RC" in
    0) ;;
    1) exit 1 ;;
    3 | 4 | 5)
        echo "!! the pytest leg DID NOT RUN THE SUITE (pytest exit $PYTEST_RC)." >&2
        echo "   3 internal error · 4 usage error · 5 nothing was collected." >&2
        echo "   Nothing was judged about this tree, which is neither a finding nor a" >&2
        echo "   pass." >&2
        echo "   IF THE TIER IS THE CAUSE, ITS REFUSAL IS SWALLOWED HERE and this is" >&2
        echo "   how to read it: the organ floors raise inside the xdist WORKERS, and" >&2
        echo "   xdist reports a worker that died during collection as an" >&2
        echo "   INTERNALERROR (exit 3) with the worker's own message dropped. Run it" >&2
        echo "   serially to see the sentence:" >&2
        echo "       uv run pytest --collect-only --djb-tier=fast" >&2
        exit 2
        ;;
    *) exit "$PYTEST_RC" ;;
    esac
    }
    gate_run_body pytest gate_leg_pytest
    leg_done
    echo "ok: loop checks passed ($(($(date +%s) - T_MODE_START))s)"
    echo "  NOT run: THE SLOW TIER — every test deriving as organ-reaching outside this"
    echo "           rung's own app (real MinIO, a real Temporal server, real Meili);"
    echo "           the banner above this line says how many and why, and the FULL"
    echo "           gate at push runs every one of them, twice."
    echo "  NOT run: second pytest pass, canary self-test, the shell refusal drives,"
    echo "           THE FULL-TREE SECRET SCAN — the leg above read only the files the"
    echo "           active rung changed; every untouched file is scanned at push,"
    echo "           in the supply-chain leg, over the whole of \`git ls-files\`,"
    echo "           the REST of the supply chain (pip-audit + licences), verdict,"
    echo "           temporal census and own-tree machinery census (full-only: a"
    echo "           leave-behind property is about the machine nobody is watching,"
    echo "           and it is only true once the suite has finished — see the legs)."

    # --- bank this verdict, if it is still about the tree it started on ---
    #
    # RECORDED ONLY AFTER A COMPLETE GREEN `--loop`, and only if the key
    # RE-DERIVES to the same value at the end. Agents edit concurrently; a run
    # that started on one tree and finished on another has measured neither, and
    # the honest answer is to bank nothing and let the next run pay. The full
    # ledger's third property, at this tier, for the same reason.
    if [ -n "${DJB_GATE_LEGS_DRY:-}" ]; then
        # A DRY RUN JUDGED NOTHING — the same rule as the full tail's, one tier
        # down: every leg was announced, no body ran, and a banked `--loop` row
        # is a claim that a pytest pass happened.
        echo "  no verdict banked — DJB_GATE_LEGS_DRY: every leg was announced and none ran"
    elif [ -n "$LOOP_LEDGER_KEY" ]; then
        # THE RUN MAY NOT VOUCH FOR BYTES IT WROTE ITSELF. Asked BEFORE the key
        # re-derives, because a re-take on a dirty start re-derives to the same
        # key and would bank a tree no HEAD carries. Could-not-look (exit 2, no
        # row), naming every path and the declaration that is the remedy.
        LOOP_TREE_MOVED=""
        LOOP_TREE_MOVED_RC=0
        if [ -n "$LOOP_TREE_SNAPSHOT" ]; then
            # `<path>\t<arm>` per path: which arm named it is half the sentence.
            LOOP_TREE_MOVED=$(loop_tree_rewrites "$LOOP_TREE_SNAPSHOT" --arms) || LOOP_TREE_MOVED_RC=$?
            # What is refused now is remembered for the NEXT run, which may
            # start on these bytes and write nothing (the carried arm). The
            # memory lives in `.rewrites` beside the snapshot, and the `rm`
            # below spares it on purpose — widening it forgets every refusal.
            [ "$LOOP_TREE_MOVED_RC" != "0" ] ||
                loop_tree_remember "$LOOP_TREE_SNAPSHOT" "$(printf '%s\n' "$LOOP_TREE_MOVED" | cut -f1)" || true
            rm -f "$LOOP_TREE_SNAPSHOT" "${LOOP_TREE_SNAPSHOT}.stamp"
        else
            LOOP_TREE_MOVED_RC=2
        fi
        if [ "$LOOP_TREE_MOVED_RC" != "0" ]; then
            echo "!! COULD NOT BANK — the run's starting snapshot of this tree could not be" >&2
            echo "   taken or read back, so whether a leg rewrote a path the key reads is" >&2
            echo "   unknown. No verdict banked (exit 2 — could-not-look, never a pass)." >&2
            exit 2
        fi
        if [ -n "$LOOP_TREE_MOVED" ]; then
            # ONE SENTENCE, ONE HOME: per path, the arm that named it and the
            # escapes that clear it (`loop_tree_refusal`, scripts/gate_ledger.sh).
            loop_tree_refusal "$LOOP_TREE_MOVED"
            exit 2
        fi
        LOOP_LEDGER_KEY_END=""
        LOOP_LEDGER_TREE_END=$(gate_measured_tree || true)
        if [ -n "$LOOP_LEDGER_TREE_END" ]; then
            # In THIS shell first — see the note at the consult above. The row
            # about to be written carries this value, and a subshell's copy of
            # it is not a value this shell has.
            loop_env_fingerprint >/dev/null 2>&1 || true
            LOOP_LEDGER_KEY_END=$(loop_ledger_key "$LOOP_LEDGER_TREE_END" "$LOOP_SCOPE_CANONICAL" || true)
        fi
        if [ -n "$LOOP_LEDGER_KEY_END" ] && [ "$LOOP_LEDGER_KEY_END" = "$LOOP_LEDGER_KEY" ]; then
            # `1` is typed rather than assumed: this leg runs ONE pytest pass,
            # the full gate runs two under one seed, and the row now says which
            # of those a reader is looking at. If this leg ever grows a second
            # pass, this literal is where the claim changes.
            # THE TREE AND ENV THE KEY RE-DERIVED TO, not the ones the consult
            # started with — they are equal here by the guard immediately above,
            # and taking them from the END is what keeps that true if the guard
            # is ever loosened.
            # A REUSE IS RECORDED AS A REUSE, NEVER AS A MEASUREMENT — the loop
            # ledger's property 2, at this tier. `reuse=` names the banked tree
            # whose pytest verdict this row rests on, so a reader following a
            # chain of reuses reaches a measurement at the end of it, and the
            # `loop:` cell a verifier types is the sentence printed below
            # rather than a `hit`/`miss(...)` that would hide which it was.
            if loop_ledger_record "$LOOP_LEDGER_KEY" "$LOOP_SCOPE_CANONICAL" 1 \
                "$LOOP_LEDGER_TREE_END" "${LOOP_ENV_FINGERPRINT:-unstated}" \
                "${LOOP_REUSE_TREE}"; then
                echo "  banked: this --loop verdict, keyed on tree + environment + scope."
                # BESIDE THE VERDICT, not in the key. What machine a loop ran
                # on does not change what it measured, so putting it in the
                # key would re-measure every tree twice for nothing; what it
                # changes is whether anybody can read, afterwards, how many
                # loops were run on the shared box and why. The ledger ROW
                # cannot carry it without a field in `gate_ledger.sh`, which is
                # the follow-up; the transcript carries it today.
                echo "          here=${LOOP_HERE_BECAUSE}"
                echo "          ${LOOP_LEDGER_KEY}"
                echo "          tree=${LOOP_LEDGER_TREE_END}"
                echo "          env=${LOOP_ENV_FINGERPRINT:-unstated}"
                echo "          scope=${LOOP_SCOPE_CANONICAL}"
                if [ -n "$LOOP_PYTEST_REUSE" ]; then
                    echo "          loop: docs-only reuse of ${LOOP_REUSE_TREE}"
                    echo "          This row is itself reusable AND says what it rests on: the"
                    echo "          pytest pass was not run here, it was inherited from that tree."
                fi
                echo "          A later --loop on identical bytes at THIS scope reuses it;"
                echo "          a WIDER scope is a different key and re-measures."
            fi
        else
            echo "  no verdict banked — the key did not re-derive to the same value at the"
            echo "  end of the run, so something moved while the gate ran. Nothing was"
            echo "  wrong with this run; it simply vouches for no single tree."
            # AND IT NAMES WHAT MOVED. Without these lines the refusal is a
            # whole re-run with no subject; see `loop_key_moved`.
            loop_key_moved "$LOOP_LEDGER_TREE" "${LOOP_LEDGER_ENV:-unstated}" \
                "${LOOP_LEDGER_ENV_PARTS:-unstated}" \
                "${LOOP_LEDGER_TREE_END:-unreadable}" "${LOOP_ENV_FINGERPRINT:-unstated}" \
                "${LOOP_ENV_COMPONENTS:-unstated}" "$LOOP_SCOPE_CANONICAL"
        fi
    elif [ -n "$GATE_MINE" ]; then
        loop_mine_banner close "$LOOP_TIER_MODE" "$LOOP_TIER_OWN_APPS"
    fi
    exit 0
fi

# --- the full legs -----------------------------------------------------------

# --- collectstatic: A GATE LEG, AND IT USED TO BE A STEP IN YAML -------------
#
# WHAT IT PROVES. Production's staticfiles backend is whitenoise's COMPRESSED
# MANIFEST storage, which post-processes every file and rewrites every reference
# it finds inside them. A reference to a file that is not there is a 500 on the
# admin and on `/api/v1/docs`, and it shows up nowhere else — not in `ruff`, not
# in `check --deploy`, not in the suite — because nothing but building the
# manifest ever resolves it.
#
# WHY IT IS HERE AND NO LONGER IN `ci.yml`. It was a workflow step, which
# `ci.yml`'s own header named as "the one candidate to fold into check.sh". Once
# CI runs UNITS rather than a whole gate, a YAML step conditioned on which unit
# is running would be CI typing a leg name — the exact thing the unit table
# exists to stop. A leg is a leg wherever it is run from.
#
# IT OWNS ITS STATIC_ROOT AND REMOVES IT. `--clear` empties the target first,
# and the target is a scratch directory this leg makes: pointed at the
# checkout's own `staticfiles/`, a gate leg would be deleting a developer's
# build output on every run. The throwaway environment is `deploy-check`'s, for
# the reason written there — the point is the SETTINGS, not the secrets.
leg collectstatic "collectstatic under production settings (the compressed manifest storage resolves every reference), into a scratch STATIC_ROOT this leg owns"
gate_leg_collectstatic() {
DJB_STATIC_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/djb-collectstatic.XXXXXX")
DJB_GATE_SECRET="$(uv run python -c 'import secrets; print("gate-only-" + secrets.token_hex(32))')"
DJB_GATE_FERNET="$(uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
DJB_GATE_DB_PASSWORD="$(uv run python -c 'import secrets; print("gate-only-" + secrets.token_urlsafe(24))')"
set +e
DJANGO_SETTINGS_MODULE=config.settings.production \
    DEBUG=0 \
    ALLOWED_HOSTS=example.invalid \
    SECRET_KEY="$DJB_GATE_SECRET" \
    CONNECTIONS_ENCRYPTION_KEY="$DJB_GATE_FERNET" \
    DATABASE_PASSWORD="$DJB_GATE_DB_PASSWORD" \
    STATIC_ROOT="$DJB_STATIC_ROOT" \
    uv run python manage.py collectstatic --noinput --clear
DJB_STATIC_RC=$?
set -e
rm -rf "$DJB_STATIC_ROOT"
if [ "$DJB_STATIC_RC" != "0" ]; then
    echo "!! collectstatic failed (exit ${DJB_STATIC_RC}) under production settings." >&2
    echo "   The compressed MANIFEST storage resolves every reference inside every" >&2
    echo "   file it post-processes, so this is usually a url() in a stylesheet" >&2
    echo "   naming a file that is not in any STATICFILES_DIRS or app static dir." >&2
    echo "   It is a 500 on the admin in production and it shows up in no other leg." >&2
    exit 1
fi
}
gate_run_body collectstatic gate_leg_collectstatic

# ORDERING: supply chain runs EARLY among the full legs — ahead of the two
# pytest passes, and behind only `collectstatic`, which is seconds of local
# work — because pip-audit is the only leg in the whole gate that
# leaves this machine. Run last, a PyPI hiccup threw away a green ~2h suite
# THREE times inside 24 hours (two pushes and a review sweep, 2026-08-19/20);
# run first, the same hiccup costs seconds. Nothing here depends on a later
# leg's side effects, and nothing later depends on this one's: it reads the
# environment and the tree, and writes neither. The constraints that DID
# pin the order are untouched — djb-checks still precedes both house-rules
# legs (they skip the django leg it already ran), the two pytest passes still
# have nothing between them, and the canary self-test still runs on a tree no
# leg has disturbed.
leg supply-chain "supply chain: pip-audit, licenses (no GPL/AGPL/SSPL), detect-secrets over the WHOLE tree vs baseline (the --loop copy sees only the active rung's changed files)"
gate_leg_supply_chain() {

# pip-audit reaches PyPI, whose default socket timeout here is 15s — and at the
# exit code a read timeout is indistinguishable from a vulnerability. So: a 60s
# timeout, and ONE retry, taken only when the output carries a network-failure
# shape AND carries no finding. A genuine vulnerability report is never retried
# and never relabelled: it keeps its own exit status, first time, untouched.
# Two attempts that both fail on the network exit 2, not 1 — nothing was
# judged about this tree's dependencies, and "unjudged" is not "clean" and is
# not "violation" either.
pip_audit_network_failure() {
    # A report of findings is a verdict whatever else the text says. Checked
    # first so no traceback below a table can talk us into a retry.
    if grep -Eqi 'known vulnerabilit|Fix Versions' "$1"; then
        return 1
    fi
    grep -Eqi \
        'ReadTimeout|ConnectTimeout|ConnectionError|ProxyError|MaxRetryError|SSLError|RemoteDisconnected|Max retries exceeded|timed out|Failed to establish a new connection|Temporary failure in name resolution|Name or service not known|nodename nor servname|Network is unreachable|Connection (refused|reset|aborted)' \
        "$1"
}

PIP_AUDIT_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-pip-audit.XXXXXX")
for attempt in 1 2; do
    set +e
    uv run pip-audit --skip-editable --timeout 60 >"$PIP_AUDIT_OUT" 2>&1
    PIP_AUDIT_RC=$?
    set -e
    cat "$PIP_AUDIT_OUT"
    if [ "$PIP_AUDIT_RC" = "0" ]; then
        break
    fi
    if ! pip_audit_network_failure "$PIP_AUDIT_OUT"; then
        # A finding, a bad flag, a broken tool — anything that is not the
        # network. It is answered as it stands, on the first attempt.
        rm -f "$PIP_AUDIT_OUT"
        exit "$PIP_AUDIT_RC"
    fi
    if [ "$attempt" = "1" ]; then
        echo "  pip-audit failed on the NETWORK, not on a finding — retrying once."
        continue
    fi
    echo "!! SUPPLY CHAIN UNPROVEN — pip-audit could not reach its advisory source" >&2
    echo "   on either attempt: a NETWORK failure, not a vulnerability report. This" >&2
    echo "   tree's dependencies were not judged, so nothing here is a finding and" >&2
    echo "   nothing here is a pass. Re-run when the network is back." >&2
    rm -f "$PIP_AUDIT_OUT"
    exit 2
done
rm -f "$PIP_AUDIT_OUT"

uv run python - <<'LICENSES'
import json
import re
import subprocess
import sys

# LGPL is weak copyleft and allowed; the refusal is the GPL/AGPL family, plus
# SSPL — not OSI-approved, and it is the licence a hosted product trips over.
BANNED = re.compile(r"\b(?<!L)(A?GPL)|\bSSPL\b|Server Side Public License", re.IGNORECASE)
out = subprocess.run(
    ["uv", "run", "pip-licenses", "--format=json"], capture_output=True, text=True, check=True
)
bad = [
    f"{row['Name']} ({row['License']})"
    for row in json.loads(out.stdout)
    if BANNED.search(row["License"]) and "LGPL" not in row["License"]
]
if bad:
    print("copyleft dependencies found:", ", ".join(bad))
    sys.exit(1)
print(f"licenses clean ({len(json.loads(out.stdout))} packages)")
LICENSES
# THE ONLY FULL-TREE SECRET SCAN IN THE GATE, AND IT LIVES HERE. `--loop` above
# runs the same tool over a DIFFERENT QUESTION: the files the active rung
# changed, so a builder meets their own false positive in-rung rather than at a
# push. This line asks the question that one cannot — is there a
# secret anywhere in the tree, including in files nobody has touched for
# months — and it is the question the recorded verdict vouches for. Narrowing
# the per-rung copy is only defensible BECAUSE this stayed whole; if this line
# is ever narrowed too, the verdict starts vouching for less than it says and
# nothing in the gate will notice.
#
# Measured 19s warm over this worktree's 864 tracked files, paid
# once per push and no longer once per rung as well.
git ls-files -z | xargs -0 uv run detect-secrets-hook --baseline .secrets.baseline
}
gate_run_body supply-chain gate_leg_supply_chain

# --- the Temporal test-server census, before and after the suite -------------
#
# WHY IT IS A GATE LEG. A census found ELEVEN orphaned `temporal-test-server` processes on one laptop,
# one of them a day old, and one of them holding the exact port a pass-2 test
# then failed to reach. `apps/conftest.py` is the fix and
# `scripts/temporal_sweep.sh` is the second layer — but a broom nobody runs is a
# class closed on paper. So the gate runs the CENSUS (never `--sweep`: this gate
# reports, it does not tidy up after itself) on both sides of the suite, and the
# property it reads is a difference, not a number: an ORPHAN after the suite
# that was not any kind of candidate before it.
#
# FULL-ONLY, deliberately. `--loop` is the attended tier — a builder is watching,
# has the tree in their head, and a leave-behind that matters will show up as the
# next run's collision. This census is a LEAVE-BEHIND property: it is about what
# the machine looks like when the suite is over and nobody is watching, which is
# the state a push hands to the next agent. That is the full gate's business.
#
# WHAT IT DOES NOT SEE. Everything `temporal_sweep.sh` declares it cannot see,
# inherited unchanged — chiefly the subreaper blind spot: "orphan" is read as
# "parent is pid 1", so under a Linux child-subreaper an orphan is reported as
# parented and this leg never sees it. And a peer agent's suite running right
# now shows as LIVE; LIVE rows never fail this leg, because another checkout's
# running suite is not this gate's finding.
TEMPORAL_SEEN=""
TEMPORAL_ORPHANS=""
TEMPORAL_PRE_SEEN=""

temporal_census() {
    local phase=$1 out rc
    # A dead instrument outranks a pass, and it says so BEFORE any pytest leg
    # runs: an absent or non-executable broom means this gate cannot say the
    # suite left nothing behind, so it does not say it.
    if [ ! -x scripts/temporal_sweep.sh ]; then
        echo "!! THE TEMPORAL CENSUS CANNOT BE TAKEN — scripts/temporal_sweep.sh is" >&2
        echo "   missing or not executable. Nothing here is a finding and nothing here is" >&2
        echo "   a pass: this gate has no way to know whether the suite leaves a test" >&2
        echo "   server behind, which is the whole point of the leg." >&2
        exit 2
    fi
    out=$(mktemp "${TMPDIR:-/tmp}/djb-temporal-census.XXXXXX")
    set +e
    scripts/temporal_sweep.sh >"$out" 2>&1
    rc=$?
    set -e
    echo "  census ($phase):"
    cat "$out"
    if [ "$rc" != "0" ]; then
        echo "!! THE TEMPORAL CENSUS FAILED ($phase, exit $rc) — the instrument itself is" >&2
        echo "   broken, and a broken instrument reporting a clean floor is the class this" >&2
        echo "   leg exists to refuse." >&2
        rm -f "$out"
        exit 2
    fi
    # Every pid the census saw in ANY state — orphaned, live, or refused. A pid
    # already on the machine before the suite is never this gate's finding, and
    # a peer's LIVE server that becomes an orphan mid-run (their suite ended) is
    # not this suite leaving anything behind.
    TEMPORAL_SEEN=$(awk '($1=="ORPHAN"||$1=="LIVE"||$1=="REFUSED") && !s[$3]++ {printf "%s ", $3}' "$out")
    TEMPORAL_ORPHANS=$(awk '$1=="ORPHAN" && !o[$3]++ {printf "%s ", $3}' "$out")
    rm -f "$out"
}

leg temporal-census "temporal test-server census, BEFORE the suite (an orphaned test server outlives its pytest worker forever and holds the port a later pass needs)"
gate_leg_temporal_census_pre() {
temporal_census pre-suite
TEMPORAL_PRE_SEEN=$TEMPORAL_SEEN
}
gate_run_body temporal-census gate_leg_temporal_census_pre

# --- the platform partition's decision ---------------------------------
#
# THE DIVIDEND, AND WHY IT IS A LEG OF ITS OWN. A cloned product pays the
# platform's whole pytest suite on every full gate, forever, even when nothing
# it did could have changed a platform verdict. `quality/partition.py` decides
# whether that portion has to run: it self-tests its canaries, computes a
# two-part key (the input closure's hash + a digest of every DISCOVERED
# population), and consults the partition ledger. A banked green verdict under
# the same key means the platform portion is skipped and the four frozen nets
# run anyway. `docs/product/partition-closure.md` is the design and the
# authority; this leg is its consumer.
#
# THE LEG NEVER LETS "WHICH HAPPENED" BE INFERRED (the design's §11.3, and the
# gate's own N-line discipline). Every full run prints the decision, the key,
# and — when the partition is skipped — the exact paths pytest was given
# instead. A reader of this log never has to work out from a duration whether
# the suite ran.
#
# EXIT SEMANTICS, INHERITED: 2 outranks a pass. A canary that does not fire, an
# unmatchable closure class, a lockfile app the registry cannot find, a ledger
# row whose key cannot be parsed — all exit 2 here, and none of them is ever a
# silent full run OR a silent skip.
#
# `--loop` IS UNTOUCHED. Its tiering already scopes by rung app, it banks
# nothing, and a partial run must never vouch for a tree.
leg partition "the platform partition — self-test its canaries, compute the two-part skip key, consult the ledger, and SAY which of the two happened"
gate_leg_partition() {

PARTITION_DECISION=$(mktemp "${TMPDIR:-/tmp}/djb-partition-decision.XXXXXX")
set +e
uv run python -m quality.partition decide --out "$PARTITION_DECISION"
PARTITION_RC=$?
set -e
case "$PARTITION_RC" in
0) ;;
1)
    echo "!! THE PARTITION FOUND SOMETHING (exit 1) — read the lines above." >&2
    echo "   A negative that fired, or a discovery walk no digest section claims." >&2
    rm -f "$PARTITION_DECISION"
    exit 1
    ;;
*)
    echo "!! THE PARTITION'S ENFORCEMENT IS BROKEN (exit $PARTITION_RC)." >&2
    echo "   A canary that does not fire is exit 2, not a pass, and a partition that" >&2
    echo "   cannot prove its own key moves may not decide whether to skip the suite." >&2
    echo "   Nothing here is a finding about your change." >&2
    rm -f "$PARTITION_DECISION"
    exit 2
    ;;
esac

# Read out of the decision file rather than out of the printed lines: the leg
# above prints for a human and this reads for the shell, and parsing prose would
# make the two able to disagree.
PARTITION_READ='import json,sys; d=json.load(open(sys.argv[1])); print(d[sys.argv[2]] if not isinstance(d[sys.argv[2]], list) else " ".join(d[sys.argv[2]]))'
PARTITION_MODE=$(uv run python -c "$PARTITION_READ" "$PARTITION_DECISION" mode)
PARTITION_KEY=$(uv run python -c "$PARTITION_READ" "$PARTITION_DECISION" key)
PARTITION_TARGETS=$(uv run python -c "$PARTITION_READ" "$PARTITION_DECISION" paths)
PARTITION_BANKABLE=$(uv run python -c "$PARTITION_READ" "$PARTITION_DECISION" bankable)
rm -f "$PARTITION_DECISION"
if [ -z "$PARTITION_MODE" ]; then
    echo "!! THE PARTITION'S DECISION COULD NOT BE READ BACK (exit 2)." >&2
    echo "   It exited 0 and wrote a decision this gate cannot parse, which means the" >&2
    echo "   gate does not know what it is about to run." >&2
    exit 2
fi

# --- `--pr` REPLACES THE PASS TARGET, AND FORCES THE PARTITION TO MEASURE -----
#
# ONE VARIABLE, BECAUSE THERE IS ONE THING THE TWO PASSES ARE POINTED AT.
# `$PARTITION_TARGETS` is that thing: a word-splitting list of pytest arguments,
# legitimately empty, expanded at both call sites below. `--pr` narrows by
# replacing it with the scope flags derived above — which is why nothing at
# those call sites changes, and why a future third way of narrowing has one
# place to land rather than a second expansion to add.
#
# AND IT FORCES A MEASURE. Under a banked partition verdict this variable is a
# PATH LIST and the passes run only those paths. Combined with
# `--djb-scope-narrow` that is exit 2 by construction: the scope's always-on
# floors are asserted over the WHOLE collection (apps/conftest.py), and a
# path-narrowed collection cannot meet them. The two narrowings are not
# composable, and the honest resolution is the one that runs MORE — a `--pr` is
# already the expensive shape, and a skipped platform partition inside one would
# be a second deselection nobody asked for.
#
# SO IT ALSO BANKS NO PARTITION ROW (below, at the banking block): a run that
# deselected most of the suite has learned nothing new about the platform
# portion, and a verdict banked from one would be a claim about tests that did
# not run.
if [ -n "$GATE_PR" ]; then
    if [ "$PARTITION_MODE" = "skip" ]; then
        echo "  --pr IGNORES THE BANKED PARTITION ROW (key $PARTITION_KEY): both passes"
        echo "  collect the whole suite and deselect from it, because the scope's always-on"
        echo "  floors are asserted over the whole collection. A path-narrowed pass under a"
        echo "  scope is exit 2 by construction, never a smaller run."
    fi
    PARTITION_MODE=measure
    PARTITION_TARGETS="$GATE_PR_PYTEST_ARGS"
fi
# --- A SHARD FORCES THE MEASURE TOO, AND FOR THE NEIGHBOURING REASON ---------
#
# `pytest-split` partitions a COLLECTION. Under a banked partition row the
# collection is already a narrowed path list, so shard k of N would be splitting
# a different collection from the one its siblings split on a runner whose
# ledger said something else — and the union of the N shards would be neither
# the suite nor a partition of it. The resolution is the one that runs MORE, as
# it is under `--pr`: the shards split the whole collection.
#
# `--pr` KEEPS THE TARGETS IT SET. When both are in play the scope is the
# proposal's and the split is over that scope — which is exactly what
# `--leg pytest-x2 --shard k/N --pr --base <sha>` is asking for.
#
# `--store-durations` FORCES IT FOR THE SAME REASON, one step earlier: the file
# it writes is what every later shard balances by, and one written under a
# banked partition row would carry timings for the product's tests alone while
# the shards it balances split the whole collection.
if [ -n "$GATE_SHARD" ] || [ -n "$GATE_STORE_DURATIONS" ]; then
    if [ "$PARTITION_MODE" = "skip" ]; then
        echo "  ${GATE_SHARD:+shard ${GATE_SHARD} }IGNORES THE BANKED PARTITION ROW (key $PARTITION_KEY):"
        echo "  the split is over a collection, and a collection one runner's ledger has"
        echo "  already narrowed is not the one the other shards are splitting."
    fi
    PARTITION_MODE=measure
    if [ -z "$GATE_PR" ]; then
        PARTITION_TARGETS=""
    fi
fi
}
gate_run_body partition gate_leg_partition

leg pytest-x2 "$GATE_PASSES_LEG_TEXT"
gate_leg_pytest_x2() {

# THE SLOT, TAKEN HERE AND HELD ACROSS BOTH PASSES. This leg is the heaviest
# single consumer on the box and it is the last of the three guards a full gate
# takes: the exclusive lease is already in hand (LEASE FIRST, THEN SLOT — see
# the full-mode branch above, where GATE_SLOT_LEASE_FIRST makes that mechanical
# rather than remembered), the checkout lock too, and this is the ceiling on how
# much of the machine the suite may claim while `--loop` runs elsewhere.
#
# HELD ACROSS BOTH PASSES DELIBERATELY, and released the moment the second ends:
# releasing between them would let the worker count change underneath the one
# thing this leg proves, and holding it through the self-test would make every
# builder on the box queue behind legs that start no suite at all.
#
# AND THE BANK TAKES ALL OF THEM. `--bank` is the PM's ritual push: the one run
# on this machine whose verdict everybody else's tree is measured against, and
# it used to run its two whole-suite passes on one slot's share while two
# builders' loops held the rest. `bank` mode takes every slot, waiting out loud
# for any that are held; a `--loop` that arrives during it waits, and is told by
# name that it is waiting for the bank. Everything else — a typed-sanction full
# gate, push-wall — still takes ONE slot, which is what the `full` arm below is.
# The escape is `DJB_BANK_SHARES_SLOTS=1` and the run that takes it prints it.
gate_refuse_reset
set +e
if [ -n "$GATE_BANK" ]; then
    gate_slot_acquire bank
else
    gate_slot_acquire full
fi
SLOT_RC=$?
set -e
if [ "$SLOT_RC" != "0" ]; then
    gate_cause
    echo "!! no pytest slot — see above. Nothing was judged about this tree." >&2
    echo "   cause: ${GATE_LAST_REFUSAL}" >&2
    exit 2
fi

# WHAT THE TWO PASSES ARE POINTED AT, said out loud on every run. Empty means
# the whole suite; a path list means the platform partition is skipped under a
# banked verdict and these are the product tests plus §7's four frozen nets.
if [ "$PARTITION_MODE" = "skip" ]; then
    echo "  PLATFORM PARTITION SKIPPED — banked under $PARTITION_KEY"
    echo "  ${GATE_PASSES_RUN} ONLY: ${PARTITION_TARGETS:-<nothing outside the partition>}"
else
    echo "  PLATFORM PARTITION RUNNING — no banked verdict for $PARTITION_KEY"
    echo "  ${GATE_PASSES_RUN} the WHOLE suite"
fi

# ONE SEED, BOTH PASSES (ADR gate-1). This leg's meaning is narrow and it has
# to stay narrow: run 1 passed, run 2 did not, therefore run 1 LEFT SOMETHING
# BEHIND — the dev Temporal server, Mailpit, Redis, a file in the tree (the
# test databases are per-run, so they are never the answer). pytest-randomly
# picks a fresh seed per run by default, which would quietly widen that meaning
# to "run 2 failed for one of two reasons and you cannot tell which" — the
# order differed, or the state did. So the seed is fixed here and fed to both,
# and the worker count — one slot's share of this box's cores, held across both
# passes — is the same on both. The seed fixes the COLLECTION ORDER; it does
# not fix which worker runs which test: `scripts/test.sh` passes no `--dist`,
# so xdist runs its default `--dist load`, which hands tests to whichever worker
# is free — timing-dependent, and free to differ between the two passes. What
# the seed removes is the order as a difference; the worker assignment stays
# one, and `pytest_x2_verdict` says so rather than claiming otherwise.
#
# Generated in the shell, NOT read back out of pass 1's output: reading it back
# means piping ./scripts/test.sh, and a pipe replaces the suite's exit status
# with the filter's — the one thing neither script may do. The seed is echoed
# here and printed again by pytest's own header in each pass, so the log shows
# the pair agreeing.
# WHAT THIS LEG MAY SAY WHEN PASS 2 IS RED.
#
# The old message printed ONE sentence on every pass-2 red: "A test is
# inheriting state from the run before it." That sentence is an INFERENCE, and
# it is only available when pass 2 actually ran tests. When pass 2 never came up
# — a collection error, a Temporal test server that could not start, a harness
# fault — the sentence is a confident statement of a cause this leg has not
# proven, and it sends a builder to fix the wrong thing. It did, twice.
#
# So the leg now READS pass 2's output and says which of three things it saw:
#
#   1. a failed-test summary and no harness fault  -> the idempotency inference,
#      stated as the inference it is;
#   2. any harness / collection / server-start evidence -> pass 2 did not come
#      up, and NO inference about idempotency is possible. This branch wins when
#      both kinds of evidence are present, deliberately: a harness that did not
#      come up manufactures test failures, so a failure list under a harness
#      fault proves nothing about pass 1;
#   3. neither -> it says it cannot tell, and names no cause at all.
#
# The misclassification direction is toward (2) and (3) — toward saying less.
# A cause this leg has not proven is never printed as a fact.
pytest_x2_verdict() {
    local out=$1 seed=$2
    local harness="" failures="" summary=""

    # `ERROR collecting` is xdist's wording and was found by driving this leg:
    # the tidier `N errors during collection` never appeared, and without this
    # alternative a collection failure with no
    # Temporal traces would have fallen through to the idempotency inference.
    if grep -Eqi 'no tests ran|collected 0 items|INTERNALERROR|ERROR collecting|error(s)? during collection|ERROR: usage' "$out"; then
        harness="${harness}zero tests ran, or collection failed; "
    fi
    if grep -Eq 'WorkflowEnvironment|start_time_skipping|temporal-test-server|BindException' "$out"; then
        harness="${harness}Temporal test-server / WorkflowEnvironment traces; "
    fi
    if grep -Eq '^FAILED |[0-9]+ (failed|error)' "$out"; then
        failures=yes
        # THE CAP LIVES INSIDE awk, not behind a `| head -20`. Under this file's
        # `set -o pipefail` the reader closes the pipe at line 20; a run with
        # enough failures to matter pushes past the kernel's 64 KiB pipe buffer,
        # awk takes SIGPIPE, and the pipeline's status is 141 — so the leg whose
        # whole job is to explain a red would die of the explanation, and only
        # on the runs that had the most to explain. Counting matches in awk reads
        # the file to EOF and closes nothing.
        # `scripts/tests/test_pipefail_readers.sh` runs THIS line against 5,000
        # planted failures.
        #
        # AND THE LINES ARE PYTEST'S OWN SUMMARY, NOT A REGEX OVER THE LOG. This
        # used to print every line matching `^(FAILED|ERROR) `, and pytest's
        # CAPTURED-LOG lines match that too — `ERROR    django.db.backends…`,
        # the level name then spaces — so a test whose green run logs an error
        # filled all twenty slots and the real `FAILED` line never showed (the
        # first consumer's FOLD-LEAK-1: twenty copies of an autouse refusal,
        # the failure off the end). So the lines come from the section pytest
        # writes for exactly this — between its `= short test summary info =`
        # banner and the closing `=…=` line — in pytest's order (failures, then
        # errors). A log with no such section (a pass killed before pytest could
        # write one, a run under `-rN`) falls back to the summary grammar alone:
        # the word, ONE space, then a node id — never the level-then-spaces
        # shape of a captured log line. One pass, to EOF, capped inside awk.
        summary=$(awk '/^=+ short test summary info =+$/ { insec = 1; seen = 1; next } insec && /^=/ { insec = 0 } insec { if (++s <= 20) sec = sec "     " $0 "\n"; next } !seen && /^(FAILED|ERROR) [^ ]/ { if (++f <= 20) fb = fb "     " $0 "\n" } END { printf "%s", (seen ? sec : fb) }' "$out")
    fi

    echo "" >&2
    if [ -n "$harness" ]; then
        echo "!! PASS 2 DID NOT COME UP — no inference about idempotency is possible." >&2
        echo "   This leg saw: ${harness%; }." >&2
        echo "   A harness that does not come up produces failures of its own, so nothing" >&2
        echo "   here says anything about what pass 1 left behind. Fix the harness, then" >&2
        echo "   re-run: ./scripts/test.sh -n ${GATE_SLOT_WORKERS} --randomly-seed=$seed" >&2
        if [ -n "$failures" ]; then
            echo "   (Tests are reported failed or errored above. This leg does NOT read them as" >&2
            echo "    state inherited from pass 1 — it cannot tell those apart from the harness.)" >&2
        fi
    elif [ -n "$failures" ]; then
        echo "!! A TEST THAT PASSED IN PASS 1 FAILED IN PASS 2 UNDER THE SAME SEED." >&2
        echo "   Both passes ran seed $seed at the same worker count: the seed fixes the collection order; under xdist's default --dist load the worker assignment is timing-dependent." >&2
        echo "   So the ORDER is not the difference; which worker ran which test may have been." >&2
        echo "   THE INFERENCE — and it is an inference, not a measurement — is that pass 1" >&2
        echo "   left state behind. Clean on the way IN, not on the way out, and not by" >&2
        echo "   resetting the database underneath it." >&2
        if [ -n "$summary" ]; then
            echo "   What pass 2 reported:" >&2
            echo "$summary" >&2
        fi
    else
        echo "!! PASS 2 FAILED AND THIS LEG CANNOT TELL WHY." >&2
        echo "   It found no failed-test summary and no harness or collection fault in pass 2's" >&2
        echo "   output, so it is not going to name a cause. Read the output above." >&2
        echo "   Both passes ran seed $seed at the same worker count." >&2
    fi
}

# --- the collector population, under the gate that banks -----------------------
#
# THE DEFECT, NAMED. `loop_counts_refuse_if_short` bound
# under `--loop` alone: `--djb-scope-counts` was assigned at ONE site, inside the
# `--loop` block, so the full gate's two passes carried no counts directory,
# there were no files to reconcile, and the refusal was never reached. A full
# gate that lost a collector therefore banked a green verdict for a suite that
# had not run — measured on this tree: a worker that exits during collection with
# xdist's restart budget exhausted leaves pytest able to exit **0** with
# `no tests ran`, which is the one status this leg reads as "the tree is clean".
#
# SO BOTH PASSES CARRY ONE, AND WHICHEVER PASS ENDED THE LEG IS RECONCILED —
# pass 2 on the ordinary path, pass 1 when pass 1 was the last thing that ran.
# A shortfall is exit 2 above the bank, above the partition row and above the
# `--pr` narrowed-run note: nothing that reads as a verdict is written by a run
# that cannot say how much of the suite collected.
#
# EMPTIED BETWEEN THE PASSES, and that is not tidiness: both passes write into
# one directory under the same worker ids, so pass 1's files would still be
# there to be counted if pass 2 lost a collector — a shortfall hidden by the
# leftovers of the pass before it.

# pytest_x2_counts_refuse — reconcile the collector population, or 0 when
# nothing was asked for. Reads `GATE_X2_COUNTS_DIR` and `GATE_SLOT_WORKERS`.
#
# THE SHORTFALL ONLY. The `--loop` reconciliation also COMPARES the files
# against each other (two collectors that saw different suites have not measured
# one thing); under the full gate there is no scope to disagree about — every
# collector collected the whole tree — so the population is the question here and
# the comparison is not asked. Declared rather than left to be discovered.
pytest_x2_counts_refuse() {
    local files n
    [ -n "${GATE_X2_COUNTS_DIR:-}" ] || return 0
    files=$(find "$GATE_X2_COUNTS_DIR" -type f 2>/dev/null | sort)
    n=$(printf '%s\n' "$files" | grep -c . || true)
    gate_refuse_reset
    loop_counts_refuse_if_short "$n" "${GATE_SLOT_WORKERS:-0}" "${files%%$'\n'*}" || {
        gate_cause
        echo "!! the two pytest passes could not be RECONCILED — see above." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        echo "   No verdict row, no partition row: a run that cannot say how much of the" >&2
        echo "   suite collected has nothing to bank." >&2
        return 2
    }
    return 0
}

# pytest_x2_passes <flags and paths both passes are pointed at…> — the two
# invocations and the reconciliation between them and the bank.
#
# Exit: 0 both passes green · 1 a pass is red · 2 the collector population was
# short (could-not-look, which outranks both).
#
# A FUNCTION SO A DRIVE CAN CALL IT. A drive may not run a nested
# `./scripts/check.sh` — the per-checkout lock refuses it — so the only honest
# way to measure this leg is to invoke its BODY, which is what
# `scripts/tests/test_loop_scope.sh` does. Reads `GATE_SLOT_WORKERS`,
# `PYTEST_SEED` and `GATE_X2_COUNTS_DIR`; the heartbeat calls are the leg's
# ticker and a drive stubs them, as the EXIT-trap case already stubs its
# neighbours.
pytest_x2_passes() {
    local rc=0 pass2_out=""
    set +e
    ./scripts/test.sh -n "$GATE_SLOT_WORKERS" --randomly-seed="$PYTEST_SEED" "$@"
    rc=$?
    set -e
    if [ "$rc" != "0" ]; then
        heartbeat_stop
        # THE RECONCILIATION FIRST, because a collector that never reported is
        # could-not-look and outranks a finding: "pass 1 is red" would name a
        # cause this leg has not proven when the red IS the missing collector.
        pytest_x2_counts_refuse || return 2
        # THE SAME MAPPING THE PER-RUNG LEG ALREADY HAS, and it belongs here for
        # the same reason: 3 (internal error), 4 (usage error) and 5 (nothing
        # was collected) are all "the suite did not run", and this file has one
        # word for that — 2, could-not-look, which outranks a pass. It matters
        # most to a SHARD: a `k/N` that collects zero tests exits 5, and read as
        # a red it would say the suite fails, while read as a pass it would say
        # a part nobody ran was green. It is neither; it is a shard that judged
        # nothing.
        case "$rc" in
        3 | 4 | 5)
            echo "!! PASS 1 DID NOT RUN THE SUITE (pytest exit ${rc})." >&2
            echo "   3 internal error · 4 usage error · 5 nothing was collected." >&2
            if [ -n "${GATE_SHARD:-}" ]; then
                echo "   THIS RUN IS SHARD ${GATE_SHARD}. A shard that collected nothing has judged" >&2
                echo "   nothing: it is not a green part and it is not a red suite. Check that N is" >&2
                echo "   not larger than the collection, and that the scope this shard split is the" >&2
                echo "   one its siblings split." >&2
            fi
            echo "   Nothing was judged about this tree, which is neither a finding nor a pass." >&2
            return 2
            ;;
        esac
        echo "!! pass 1 is red — the suite fails on its own, before idempotency is in question." >&2
        return 1
    fi
    # AND AFTER A GREEN PASS 1 TOO, which is the case the leg would otherwise
    # pay ten minutes to find out about: pytest exits 0 from a lost collector
    # (`no tests ran` is not a failure), so "pass 1: green" would be printed
    # over a suite that did not run and pass 2 would be spent proving it twice.
    # The criterion asks for the pass that ENDED the leg; reconciling after both
    # covers that and closes the window earlier.
    if ! pytest_x2_counts_refuse; then
        heartbeat_stop
        return 2
    fi
    echo "  pytest pass 1: green (seed $PYTEST_SEED)"
    # A MEASUREMENT RUN STOPS HERE. `--store-durations` exists to rewrite the
    # file the split balances by; the second pass proves idempotency, which is a
    # VERDICT, and this run banks none. Running it would double the wall of the
    # one operation nobody is waiting on for an answer.
    if [ -n "${GATE_STORE_DURATIONS:-}" ]; then
        heartbeat_stop
        echo "  pass 2 NOT run — --store-durations is a measurement, not a verdict."
        echo "  scripts/pytest_durations.json has been rewritten from pass 1's timings."
        return 0
    fi
    # AND A ONE-PASS SHARD STOPS HERE, the precedent above being the shape. The
    # difference is what is being said: `--store-durations` drops pass 2 because
    # it BANKS NOTHING, and this drops it because the belt runs somewhere else
    # and is composed into the row — a verdict over one pass, with its proof
    # named. Pass 1's own status is what the leg exits, through the mapping
    # above: a red pass 1 has already returned 1, a collector that never
    # reported has already returned 2, and the counts reconciliation ran before
    # this line. Refused for anything but a shard at parse time, so there is no
    # whole-unit run that can reach it.
    if [ "${GATE_PASSES:-}" = "1" ]; then
        heartbeat_stop
        echo "  pytest pass 2 NOT run — --passes 1: the leak proof is the acceptance box's (ADR gate-1)"
        return 0
    fi
    # Pass 1's counts are pass 1's. See EMPTIED BETWEEN THE PASSES above.
    if [ -n "${GATE_X2_COUNTS_DIR:-}" ]; then
        find "$GATE_X2_COUNTS_DIR" -type f -exec rm -f {} + 2>/dev/null || true
    fi
    # The ticker's subject changes here and nowhere else. Pass 2's output is
    # captured whole, so this is the ONLY thing that will be printed between now
    # and the end of the leg — which is the silence this instrument exists for.
    heartbeat_label "pass 2"
    # Pass 2's output is CAPTURED to a file and printed whole afterwards, the
    # same shape the supply-chain leg uses for pip-audit and for the same
    # reason: the leg has to READ what it is about to make a claim about, and
    # reading it through a pipe would replace pytest's exit status with the
    # reader's — the one thing neither script may do. The cost is that pass 2
    # prints at the end instead of as it goes; the alternative is a leg that
    # names a cause it never looked at.
    echo "  pytest pass 2 running (output is captured and printed whole when it ends)..."
    pass2_out=$(mktemp "${TMPDIR:-/tmp}/djb-pytest-pass2.XXXXXX")
    set +e
    ./scripts/test.sh -n "$GATE_SLOT_WORKERS" --randomly-seed="$PYTEST_SEED" "$@" >"$pass2_out" 2>&1
    rc=$?
    set -e
    heartbeat_stop
    cat "$pass2_out"
    if ! pytest_x2_counts_refuse; then
        rm -f "$pass2_out"
        return 2
    fi
    if [ "$rc" != "0" ]; then
        pytest_x2_verdict "$pass2_out" "$PYTEST_SEED"
        rm -f "$pass2_out"
        return 1
    fi
    rm -f "$pass2_out"
    echo "  pytest pass 2: green (seed $PYTEST_SEED)"
    return 0
}

# THE SEED CAN BE TYPED IN, AND THE REASON IS THE SHARD. Minted here, every
# shard of one CI run would collect in a DIFFERENT random order, and
# `pytest-split`'s partition is over a collection — so the N shards would be
# splitting N different orderings and their union would be neither the suite nor
# a partition of it. One seed handed to every runner is what makes the shards
# add up. `DJB_GATE_PYTEST_SEED` is that knob; it is printed with its provenance
# on every run, because a seed whose origin is invisible is one nobody can
# replay.
#
# AN UNPARSABLE VALUE IS EXIT 2 AND NEVER A MINTED ONE. Falling back to a fresh
# seed would give a runner the one thing it must not have: a green shard that
# split a collection none of its siblings saw.
# gate_pytest_seed — set PYTEST_SEED and SAY where it came from.
#
# A FUNCTION SO A DRIVE CAN CALL IT, the shape `pytest_x2_passes` below already
# has and for the same reason: the alternative is a drive that re-implements the
# choice it is checking. It is called PLAINLY and never in a substitution — it
# assigns a global and prints a line, and a subshell would keep the assignment.
gate_pytest_seed() {
    if [ -n "${DJB_GATE_PYTEST_SEED:-}" ]; then
        case "$DJB_GATE_PYTEST_SEED" in
        '' | *[!0-9]*)
            echo "!! DJB_GATE_PYTEST_SEED is set and is not a non-negative integer." >&2
            echo "   got: ${DJB_GATE_PYTEST_SEED}" >&2
            echo "   A seed this gate cannot parse is never replaced by a minted one: every" >&2
            echo "   shard of one run has to split the SAME collection order, and a silent" >&2
            echo "   fallback is how two shards come to split two different suites." >&2
            echo "   Nothing was judged." >&2
            exit 2
            ;;
        esac
        PYTEST_SEED=$DJB_GATE_PYTEST_SEED
        echo "  seed: ${PYTEST_SEED} (typed: DJB_GATE_PYTEST_SEED)"
    else
        PYTEST_SEED=$(((RANDOM << 15) | RANDOM))
        echo "  seed: ${PYTEST_SEED} (minted)"
    fi
}
gate_pytest_seed
echo "  ${GATE_PASSES_RUN} --randomly-seed=$PYTEST_SEED (replay a red order with it)"
# ONE SENTENCE, AND IT COMES FROM WHERE THE NUMBER DOES. This line used to carry
# its own parenthetical — "this box's cores split N ways" — which is FALSE when
# DJB_GATE_SLOT_WORKERS is typed (the number is then the knob's) and false again
# under a bank (which holds every slot and runs every share). Two sentences about
# one number, one of them wrong, on the line a reader uses to check the number.
# `gate_slot_worker_count` and `gate_slot_acquire` set the phrase beside the
# value they decide, so the three cases — derived share, typed knob, bank — each
# print the one true sentence here.
echo "  workers:    -n ${GATE_SLOT_WORKERS} (${GATE_SLOT_WORKERS_PHRASE})"
echo "              NOT -n auto, and the same number on BOTH passes, which is what pins"
echo "              the worker assignment and keeps this leg's meaning narrow."
gate_pytest_nominal "$GATE_SLOT_NOMINAL_FULL" GATE_SLOT_NOMINAL_FULL \
    "$(gate_ledger_path 2>/dev/null || true)"
# ONE TICKER ACROSS BOTH PASSES, relabelled rather than restarted: the slot is
# held across both, so the elapsed arithmetic is continuous and the only thing
# that changes between them is the word.
heartbeat_start "pass 1" "$GATE_PYTEST_NOMINAL" "$GATE_PYTEST_NOMINAL_PROV"

# --- the counts directory BOTH passes write into ------------------------------
#
# ONE DIRECTORY, TWO OWNERS, AND NEVER TWO FLAGS. `--pr` already mints one in
# its preflight and has already appended `--djb-scope-counts=<it>` to the flags
# both passes carry, so this leg REUSES it rather than passing the option twice
# and letting the last one win silently. Every other run — a bare full gate, and
# a `--pr` whose scope narrowed nothing — gets one here, and it rides the EXIT
# trap the way the `--pr` one does, for the reason written beside that one: a red
# leg, a refused lease and a SIGTERM all leave by a path no tidy-up line sits on.
GATE_X2_COUNTS_DIR=""
GATE_X2_COUNTS_ARG=""
if [ -n "$GATE_PR_COUNTS_DIR" ]; then
    GATE_X2_COUNTS_DIR="$GATE_PR_COUNTS_DIR"
else
    GATE_FULL_COUNTS_DIR=$(mktemp -d "${TMPDIR:-/tmp}/djb-full-counts.XXXXXX")
    GATE_X2_COUNTS_DIR="$GATE_FULL_COUNTS_DIR"
    GATE_X2_COUNTS_ARG="--djb-scope-counts=$GATE_FULL_COUNTS_DIR"
fi

# UNQUOTED ON PURPOSE: `$PARTITION_TARGETS` is a path LIST that has to word-split
# into pytest arguments, and it is empty when the whole suite runs. The counts
# flag joins it in the same string and for the same reason — no flag or path in
# it can contain a space, which is what makes the string form honest here (the
# `--pr` preflight's own note, one door over).
# --- THE SPLIT, WHEN THIS RUNNER IS HOLDING ONE PART OF THE COLLECTION -------
#
# `1/1` IS THE WHOLE UNIT AND CARRIES NO FLAGS AT ALL. That is not an
# optimisation: it is what makes `--shard 1/1` mean the same thing as no shard,
# on a checkout that has not installed the plugin, which is the declared exit
# from `pytest-split` (one dependency line and one file).
#
# A STALE OR ABSENT DURATIONS FILE ONLY UNBALANCES. The plugin's partition is
# over the collected node ids; the durations are what it balances the groups BY.
# A file naming tests that no longer exist, or no file at all, changes how big
# the groups are and never which tests are in one — every collected test is in
# exactly one group either way. The leg says which of the two it is on every
# run, so a reader never has to infer it from a wall time.
#
# A FUNCTION, FOR `gate_pytest_seed`'s REASON: the flags a shard carries are
# what the shard census has to be handed, and a drive that assembled its own
# would be checking its own arithmetic.
#
# THE DURATIONS PATH IS BOUND TO PYTEST'S ROOTDIR, AND A PATH OUTSIDE IT IS
# REFUSED. Measured, and it is worse than a stale file: handed an ABSOLUTE path
# outside the checkout, `pytest-split` does not warn and does not fail — the
# partition COLLAPSES, and a three-way split of 3,822 items came back as 3, 3
# and 1. A shard that judged three tests and exited 0 is a green nobody can read
# as anything but a pass, which is the worst shape a selection defect can take.
# So the path is resolved against the rootdir (this checkout) and anything that
# escapes it is exit 2 NAMING BOTH — never a smaller run, and never a run whose
# groups are a rounding error.
#
# `DJB_GATE_DURATIONS_PATH` EXISTS SO THE REFUSAL CAN BE DRIVEN, and it is the
# only way to move the file: a caller that wants another one types it, and types
# it inside the tree.
gate_durations_path() {
    local want root real
    want=${DJB_GATE_DURATIONS_PATH:-scripts/pytest_durations.json}
    root=$(pwd -P)
    case "$want" in
    /*) real=$want ;;
    *) real="${root}/${want}" ;;
    esac
    # NO `realpath`/`readlink -f`: neither is portable to both mktemps' platforms
    # (the portability census in this file exists for exactly that class), and
    # the question here is textual — does the resolved path start at the rootdir.
    #
    # A `..` SEGMENT IS REFUSED BEFORE THE PREFIX TEST, because the prefix test
    # alone cannot see one: `<root>/../zzz.json` starts with `<root>/` and is
    # outside the tree. Refusing the segment is stricter than normalising it and
    # needs no normaliser — no legitimate durations path has one.
    case "/${real}/" in
    */../*)
        echo "!! --durations-path '${want}' contains a '..' segment." >&2
        echo "   rootdir:  ${root}" >&2
        echo "   resolved: ${real}" >&2
        echo "   A path that climbs out of the rootdir is refused whether or not it" >&2
        echo "   lands back inside it: see the collapse below. Nothing was judged." >&2
        return 2
        ;;
    esac
    case "$real" in
    "${root}"/*) ;;
    *)
        echo "!! --durations-path '${want}' resolves OUTSIDE pytest's rootdir." >&2
        echo "   rootdir:  ${root}" >&2
        echo "   resolved: ${real}" >&2
        echo "   pytest-split reads that file and then SILENTLY COLLAPSES the partition:" >&2
        echo "   measured, a 3-way split of 3822 items came back as 3, 3 and 1 items, with" >&2
        echo "   no warning and exit 0. A shard that judged three tests is not a smaller" >&2
        echo "   run, it is a green that means nothing. Nothing was judged." >&2
        return 2
        ;;
    esac
    printf '%s\n' "$want"
    return 0
}

GATE_SPLIT_ARGS=""
gate_pytest_split_args() {
    local durations
    GATE_SPLIT_ARGS=""
    if [ -n "$GATE_SHARD" ] || [ -n "$GATE_STORE_DURATIONS" ]; then
        durations=$(gate_durations_path) || exit 2
    fi
    if [ -n "$GATE_SHARD" ]; then
        if [ "$GATE_SHARD_N" = "1" ]; then
            echo "  shard 1/1: the WHOLE unit — no split flags, and therefore no plugin needed."
        else
            if [ -f "$durations" ]; then
                echo "  durations: ${durations} — regenerate with"
                echo "             ./scripts/check.sh --leg pytest-x2 --store-durations"
            else
                echo "  durations: none — unbalanced split (the groups are chunked by count;"
                echo "             every collected test is still in exactly one of them)"
            fi
            GATE_SPLIT_ARGS="--splits ${GATE_SHARD_N} --group ${GATE_SHARD_K} --durations-path ${durations}"
            echo "  shard ${GATE_SHARD_K}/${GATE_SHARD_N}: ${GATE_PASSES_CARRY} ${GATE_SPLIT_ARGS}"
        fi
        # BESIDE THE SHARD LINE, because the pass count is a fact about the
        # same run and a reader of this transcript should not have to reach
        # the end of the leg to learn how many passes it was going to get.
        if [ "${GATE_PASSES:-}" = "1" ]; then
            echo "  passes 1: pass 2 is NOT run here — the leak proof is the acceptance box's (ADR gate-1)"
        fi
    elif [ -n "$GATE_STORE_DURATIONS" ]; then
        GATE_SPLIT_ARGS="--store-durations --durations-path ${durations}"
        echo "  --store-durations: this run REWRITES ${durations}. It is a"
        echo "  MEASUREMENT and not a verdict — pass 2 is not run and nothing is banked."
    fi
}
gate_pytest_split_args
# UNQUOTED FOR THE SAME REASON THE TARGETS ARE, and the same guarantee holds: no
# flag or path in this string can contain a space.
X2_PASS_ARGS="${PARTITION_TARGETS}${GATE_SPLIT_ARGS:+ ${GATE_SPLIT_ARGS}}${GATE_X2_COUNTS_ARG:+ ${GATE_X2_COUNTS_ARG}}"
set +e
# shellcheck disable=SC2086
pytest_x2_passes $X2_PASS_ARGS
TEST_RC=$?
set -e
case "$TEST_RC" in
0) ;;
2) exit 2 ;;
*) exit 1 ;;
esac
# THE SLOT GOES BACK THE MOMENT THE SUITE IS DONE, not at the end of the gate.
# Everything after this line — the census, the self-test, the shell drives, the
# house rules — starts no suite, and a builder waiting for a slot must not be
# waiting on legs that would not have used one. The EXIT trap is the belt if
# anything below exits before this runs.
gate_slot_release

# --- banking the partition's verdict -----------------------------------
#
# ONLY AFTER TWO GREEN WHOLE-SUITE PASSES, and only when the partition actually
# RAN: a skipping run has nothing new to say about the platform portion, and
# re-banking under the key it just consulted would turn one measurement into a
# self-renewing claim.
#
# AND ONLY WHEN THE ENVIRONMENT IS NOT BENT (§4's decision table): a read
# environment variable whose value differs from `.env.example`'s declared one
# means the verdict runs and is NOT banked, with the reason already printed by
# the partition leg above. Banked green under a bent environment is the
# stale-green class with no diff at all.
#
# AND NEVER FROM A NARROWED RUN. `--pr` collected the whole suite and then
# DESELECTED most of it, so the platform portion did not run — a verdict banked
# from it would say "the platform partition passed" about tests nobody ran, and
# the next full gate would skip them on the strength of it. A narrowed run banks
# nothing, anywhere: not this row, and not the full verdict row at the end.
if [ -n "$GATE_PR" ]; then
    echo "  partition verdict NOT banked: --pr is a narrowed run and the platform"
    echo "  portion was deselected, so this run has nothing to say about it."
    # The counts directory is NOT dropped here. It used to be, and that was a
    # leak wearing a tidy-up: this line is reached only by a run that got this
    # far, and every run that does not — a red leg, a refused lease, a
    # SIGTERM — left the directory behind. The EXIT trap owns it now, and one
    # owner is the whole point.
elif [ -n "$GATE_SHARD" ]; then
    echo "  shard ${GATE_SHARD} banks nothing: a part of the collection has nothing to say"
    echo "  about the whole — not here, and not in the verdict ledger at the end."
elif [ -n "$GATE_STORE_DURATIONS" ]; then
    echo "  --store-durations banks nothing: one pass ran, and it ran to be timed."
elif [ "$PARTITION_MODE" != "skip" ]; then
    if [ "$PARTITION_BANKABLE" = "True" ]; then
        uv run python -m quality.partition bank --key "$PARTITION_KEY" || {
            echo "!! the partition verdict could not be banked (exit 2)." >&2
            exit 2
        }
    else
        echo "  partition verdict NOT banked: the environment is bent (reason above)."
    fi
fi
}
gate_run_body pytest-x2 gate_leg_pytest_x2

# --- the second half of the temporal-census leg ------------------------------
leg temporal-census "temporal test-server census, AFTER the suite — the property is a DIFFERENCE: an orphan that was not on this machine in any state before the suite ran"
gate_leg_temporal_census_post() {
temporal_census post-suite
TEMPORAL_NEW=""
for pid in $TEMPORAL_ORPHANS; do
    case " $TEMPORAL_PRE_SEEN " in
    *" $pid "*) ;;
    *) TEMPORAL_NEW="$TEMPORAL_NEW $pid" ;;
    esac
done
if [ -n "$TEMPORAL_NEW" ]; then
    echo "!! THE SUITE LEFT A TEMPORAL TEST SERVER BEHIND." >&2
    echo "   Orphaned after the suite, and not on this machine in any state before it:" >&2
    for pid in $TEMPORAL_NEW; do
        echo "     pid $pid" >&2
    done
    echo "   An orphan listens on nothing, is invisible to a port probe, and lives until" >&2
    echo "   the machine is rebooted — and it holds the port a later pass needs." >&2
    echo "   Stop it with: ./scripts/temporal_sweep.sh --sweep" >&2
    exit 1
fi
echo "  no new orphan: this suite left no test server behind"
}
gate_run_body temporal-census gate_leg_temporal_census_post

# --- the own-tree machinery census -------------------------
#
# THIS LEG LOOKS AT THIS CHECKOUT AND AT NOTHING ELSE, and that is the whole
# design, not a limitation to be fixed later. Every instance it judges is
# narrowed by --only to the identity this checkout derives
# (scripts/db.sh: DATABASE_NAME, the branch plus the 8-hex digest of this
# checkout's path). A peer worktree's abandoned schedule, a deleted checkout's
# stranded executions, a sibling clone's databases — all of it is deliberately
# INVISIBLE here.
#
# WHY: a gate reddened by somebody else's garbage
# trains people to override the gate. My verdict may not be coupled to your
# corpse. Machine-wide is an OPERATOR's job with an operator's judgement
# (FOREIGN is an absence of evidence, never a finding), and it lives in the PM's
# standing pre-wave reap, not here.
#
# WHICH MEANS A REAL LESSON APPLIES TO THIS LEG'S GREEN: "clean" here says
# THIS CHECKOUT left nothing undeclared behind. It says NOTHING about the
# machine. Read the machine with:
#
#     ./scripts/sweep.sh --roots <where clones of this repository live>
#
# and `./scripts/sweep.sh --list-classes` for what the declared classes ARE
# today, with scripts/lifecycle.sh for how each is judged. The count is asked
# for rather than written down here: this line used to name a specific count
# until a class was added and the sentence went stale — the instrument knows,
# and a reader who wants the number can have today's.
#
# THE TWO PROPERTIES, and they fail differently on purpose:
#
#   1. EVERY INSTANCE THIS CHECKOUT MADE BELONGS TO A DECLARED CLASS. An
#      instance carrying a checkout-derived identity that no class claims is
#      sweep.sh's exit 2, naming the shape — could-not-judge outranks a pass, so
#      machinery class N+1 reddens the gate the day it first exists rather than
#      accumulating for a cycle. That is EXIT 2 here too: enforcement does not
#      know what it just looked at.
#   2. IN process LIFETIME THIS QUEUE OWNS NO DURABLE SCHEDULE. ADR
#      platform-lifecycle-1: a dev or test checkout declares MACHINERY_PROCESS
#      and creates no Schedule object ever, running the same sweeps off the live
#      worker instead. The honest local signal is ensure_schedules() returning
#      an empty list; the signal this leg takes is the SERVER's, because a
#      schedule that outlives the process that made it is exactly what nothing
#      in-process can see. One found is EXIT 1: this tree leaked.
#
# THE LIFETIME CLASS IS READ, NEVER ASSUMED. In deployment lifetime a durable
# Schedule for this queue is correct, and a leg that asserted zero regardless
# would be refusing a legitimate production configuration.
leg own-tree-census "checkout-machinery census, AFTER the suite — every instance THIS CHECKOUT created belongs to a declared class (exit 2 names an undeclared shape), and in process lifetime this queue owns no durable Schedule (exit 1: this tree leaked). Machine-wide is NOT in scope — see the leg"
gate_leg_own_tree_census() {

OWN_CENSUS=$(mktemp "${TMPDIR:-/tmp}/djb-own-census.XXXXXX")
set +e
./scripts/sweep.sh --only "$DATABASE_NAME" >"$OWN_CENSUS" 2>&1
OWN_RC=$?
set -e
cat "$OWN_CENSUS"
if [ "$OWN_RC" != "0" ]; then
    # Two different exit-2s wear the same status, so the leg READS the
    # transcript it is about to make a claim about rather than guessing which
    # one it got (the same discipline as pytest_x2_verdict above).
    if grep -q "UNRECOGNIZED" "$OWN_CENSUS"; then
        echo "!! THIS CHECKOUT MADE SOMETHING NO DECLARED CLASS CLAIMS (exit 2)." >&2
        echo "   The shape is named above. It carries a checkout-derived identity, so this" >&2
        echo "   repository built it, and scripts/lifecycle.sh does not know what it is —" >&2
        echo "   which means this census cannot say what it just looked at, and a broom" >&2
        echo "   pointed at this machine would not know whether to touch it." >&2
        echo "   Declare the class in scripts/lifecycle.sh (name, identity, enumerate," >&2
        echo "   liveness, destroy, warm). Do NOT widen an existing pattern to swallow it." >&2
    else
        echo "!! THE OWN-TREE MACHINERY CENSUS COULD NOT BE TAKEN (exit ${OWN_RC})." >&2
        echo "   No docker, no Postgres, no Temporal, or no checkout to derive liveness" >&2
        echo "   from. A census that could not look has not cleared anything, and an" >&2
        echo "   instrument reporting a clean floor it never read is the class this leg" >&2
        echo "   exists to refuse." >&2
    fi
    rm -f "$OWN_CENSUS"
    exit 2
fi
rm -f "$OWN_CENSUS"
echo "  every instance ${DATABASE_NAME} owns belongs to a declared class"

# The declared lifetime class, read from the settings module the worker runs
# under (scripts/worker.sh: config.settings.local), which is also where an
# environment override lands. Imported directly rather than through django.setup
# — the same read apps/workflows/tests/test_machinery_lifetime.py makes, and it
# costs no app registry.
set +e
MACHINERY_CLASS=$(uv run python -c 'import config.settings.local as s; print(s.TEMPORAL_MACHINERY_LIFETIME)' 2>/dev/null)
LIFETIME_RC=$?
set -e
if [ "$LIFETIME_RC" != "0" ] || [ -z "$MACHINERY_CLASS" ]; then
    echo "!! COULD NOT READ TEMPORAL_MACHINERY_LIFETIME from config/settings/local.py." >&2
    echo "   Without it this leg cannot tell a leaked schedule from a legitimate one," >&2
    echo "   and guessing either way is worse than saying so (exit 2)." >&2
    exit 2
fi
if [ "$MACHINERY_CLASS" != "process" ]; then
    echo "  lifetime class is '${MACHINERY_CLASS}': durable Schedules for this queue are"
    echo "  CORRECT here, so the zero-schedules property does not apply (ADR"
    echo "  platform-lifecycle-1). Nothing was asserted about them."
    echo "  Nor does the open-execution property: in deployment lifetime a running"
    echo "  execution on this queue is the product working. Nothing was asserted"
    echo "  about those either."
else
    # THE ASSERTION IS THE INSTRUMENT'S, NOT THIS LEG'S. `--assert-none` exits 1
    # when anything is in scope and 2 when it could not look, so this leg reads a
    # STATUS rather than grepping a summary line it does not own — which is the
    # coupling that rots the day somebody rewords a count.
    gate_refuse_reset
    set +e
    ./scripts/sweep.sh --class schedule --only "$DATABASE_NAME" --assert-none
    SCHED_RC=$?
    set -e
    if [ "$SCHED_RC" = "2" ]; then
        gate_cause
        echo "!! THE SCHEDULE CENSUS COULD NOT BE TAKEN — see above. Nothing was asserted." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        exit 2
    fi
    if [ "$SCHED_RC" != "0" ]; then
        echo "!! THIS TREE LEAKED A DURABLE TEMPORAL SCHEDULE." >&2
        echo "   Lifetime class is 'process' (ADR platform-lifecycle-1), which creates no" >&2
        echo "   Schedule object ever — and the server holds one for this checkout's queue." >&2
        echo "   A Schedule is infinitely durable and this checkout's identity is not: when" >&2
        echo "   the checkout goes, the schedule goes on starting workflows nothing will" >&2
        echo "   ever poll, forever. That is the leak this leg exists to close." >&2
        echo "   Either is a fix: start the worker once (./scripts/worker.sh), whose startup" >&2
        echo "   deletes this checkout's own legacy schedules; or sweep it directly with" >&2
        echo "     ./scripts/sweep.sh --sweep --class schedule --only ${DATABASE_NAME}" >&2
        exit 1
    fi
    echo "  process lifetime: this queue owns no durable Schedule"

    # --- THE SECOND PROPERTY: THIS QUEUE STRANDS NO OPEN EXECUTION -----------
    #
    # WHY THE SCHEDULE ASSERTION ALONE WAS NOT ENOUGH, measured rather than
    # argued. A schedule is one shape of durable-object-on-a-mortal-identity;
    # a RUNNING EXECUTION on the same queue is the other, and it accumulates
    # faster because anything can start one. The drive that started them was
    # fixed in this cycle (it terminates what it starts now) — but a fix in one
    # drive is a promise about one drive, and 1,061 stranded runs had piled up
    # under a census that was green every single time, because the census only
    # ever asked about Schedules. This leg is the BELT: whatever starts a run
    # and walks away, this checkout's own gate says so before the push.
    #
    # LIVE POLLERS ARE WORK, NOT A STRAND, and that distinction is READ from
    # the registry rather than decided here. `scripts/lifecycle.sh` declares
    # this class's liveness as "DescribeTaskQueue pollers on its queue
    # (positive only)", so a worker that is up is positive proof that the open
    # runs on this queue are being worked. A builder with `./scripts/worker.sh`
    # running and a workflow in flight is not leaking anything, and a gate that
    # reddened on that would be the "gate reddened by legitimate work" class
    # this leg's own header refuses one property up.
    #
    # WHY THE LIVENESS QUESTION IS ASKED SEPARATELY rather than left to
    # `--assert-none`: the sweep counts every instance IN SCOPE, and for THIS
    # checkout's own identity the verdict is `live` (a path this run hashed)
    # before pollers are ever consulted — so `--assert-none` alone cannot tell
    # a strand from work in progress. Asking `lc_queue_pollers` first is not a
    # second opinion about the census: it is the same function the census's own
    # verdicts read, called through the file that declares it, in a subshell so
    # that nothing the registry defines leaks into this one.
    #
    # A POLLER COUNT THAT CANNOT BE READ IS NOT A POLLER. `lc_queue_pollers`
    # answers 0 for a queue the server would not describe (its own declared
    # shape: "no pollers, nothing known"), so an unreachable Temporal falls
    # through to the assertion below — which is `--assert-none`'s exit 2, the
    # could-not-look this leg already outranks a pass with.
    OWN_QUEUE="djb-${DATABASE_NAME#djb_}"
    set +e
    OWN_POLLERS=$(
        # shellcheck source=scripts/lifecycle.sh
        . scripts/lifecycle.sh >/dev/null 2>&1 || exit 1
        lc_queue_pollers "$OWN_QUEUE"
    )
    POLLERS_RC=$?
    set -e
    case "${OWN_POLLERS:-}" in
    '' | *[!0-9]*) OWN_POLLERS=0 ;;
    esac
    if [ "$POLLERS_RC" = "0" ] && [ "$OWN_POLLERS" != "0" ]; then
        echo "  ${OWN_POLLERS} poller(s) on ${OWN_QUEUE} right now: open executions here are"
        echo "  WORK, not strands (scripts/lifecycle.sh declares this class's liveness as"
        echo "  pollers on its queue, positive evidence only). Nothing was asserted about"
        echo "  them."
    else
        # Same discipline as the schedule assertion above: the leg reads a
        # STATUS the instrument owns, never a summary line it does not.
        gate_refuse_reset
        set +e
        ./scripts/sweep.sh --class open-execution --only "$DATABASE_NAME" --assert-none
        EXEC_RC=$?
        set -e
        if [ "$EXEC_RC" = "2" ]; then
            gate_cause
            echo "!! THE OPEN-EXECUTION CENSUS COULD NOT BE TAKEN — see above. Nothing was asserted." >&2
            echo "   cause: ${GATE_LAST_REFUSAL}" >&2
            exit 2
        fi
        if [ "$EXEC_RC" != "0" ]; then
            echo "!! THIS TREE STRANDED A RUNNING TEMPORAL EXECUTION." >&2
            echo "   Nothing is polling ${OWN_QUEUE}, and the server is holding open run(s)" >&2
            echo "   on it — named above with how long each has been running. An execution" >&2
            echo "   on a queue with no poller never advances and never ends: it sits in the" >&2
            echo "   namespace forever, and this checkout's identity does not. That is how" >&2
            echo "   1,061 of them accumulated under a green census." >&2
            echo "   Either is a fix: start the worker (./scripts/worker.sh) if that work is" >&2
            echo "   real and should finish; or END EACH RUN NAMED ABOVE BY HAND, with the" >&2
            echo "   destroy verb its own class declares (scripts/lifecycle.sh, open-execution):" >&2
            echo "     bash -c '. scripts/lifecycle.sh && lc_temporal workflow terminate --workflow-id <an id above>'" >&2
            echo "   AND NOT THE BROOM, which is the line that used to be printed here and" >&2
            echo "   which does nothing at all in this exact situation: this checkout's OWN" >&2
            echo "   open executions are declared NOT disposable, so no sweep of any kind" >&2
            echo "   touches one — owning a thing is not a licence to destroy it. That stance" >&2
            echo "   is right and stays: a poller count is a racy thing to kill on (a worker" >&2
            echo "   restarting reads as zero), so nothing gets a flag meaning 'destroy my own" >&2
            echo "   running work'. You name the run instead, one at a time, on purpose." >&2
            echo "   Whatever started them and walked away is the defect; this is the belt." >&2
            exit 1
        fi
        echo "  process lifetime: this queue strands no open execution"
    fi
fi
}
gate_run_body own-tree-census gate_leg_own_tree_census

leg selftest "house-rules self-test (every canary planted through the real scope must fire; every negative must stay silent) + every shell refusal drive under scripts/tests/"
gate_leg_selftest() {

# >>> selftest-leg >>>
# THE LEG IS A FUNCTION, AND IT RUNS EVERY DRIVE BEFORE IT DECIDES.
#
# What it replaced, and what that cost. Until now this leg was inline code and
# every drive block ended in its own `exit`: the FIRST red drive ended the leg
# and every drive after it never ran. A builder paying a 25-minute full gate
# learned exactly one red per run, and the selftest-only classes surface one per
# bank — five banks were spent that way, and a hand-run of all the drives found
# the whole red list at once, which is the measurement that opened the row.
#
# THE COMPOSITION, which is the whole of the change:
#
#   * the engine's own `--selftest` runs first and NO LONGER STOPS THE DRIVES.
#     A dead canary is still 2 and still outranks every pass — it is recorded as
#     could-not-look and the drives run anyway, because a gate that costs 25
#     minutes should print its whole red list once.
#   * every drive runs, in registered order, and NOTHING between them ends the
#     leg. Each prints `drive <name>: exit <rc> (<n>s)`.
#   * the exit composes at the END: 2 if the engine's selftest or ANY drive was
#     2 (a driver that could not look has cleared nothing), else 1 naming every
#     red drive on one line, else 0.
#
# EVERY DRIVE BLOCK IS BYTE-IDENTICAL TO THE ONE IT REPLACED, and that is
# deliberate rather than tidy. Each block keeps its own `set +e`, its own
# literal invocation line, its own `_RC=$?`, its own bespoke red sentences and
# its own `exit 2` / `exit "$_RC"`. What changed is where that `exit` LANDS: the
# block now runs inside a subshell the leg opens around it, so the block's exit
# ends the BLOCK and the leg reads it as a status rather than dying of it. The
# leg reads each drive's exit semantics; it never rewrites them.
#
# THE SUBSHELL IS OUTSIDE THE `# >>> drive: <name> >>>` FENCE on purpose.
# `scripts/tests/test_drive_preamble.sh::case_a_registered_drive_that_cannot_look_is_exit_2_not_a_pass`
# extracts a registration block by those sentinels and runs it STANDALONE,
# requiring 2 to stay 2, 1 to stay 1 and 0 to let the leg carry on. A block with
# the parenthesis inside its own fence would run standalone as a subshell and
# swallow its own refusal, so that census would be measuring a shape nothing
# ships. The fence contains the drive; the leg contains the fence.
#
# THE DRIVE. `scripts/tests/test_selftest_leg.sh` extracts the text between
# these sentinels into a scratch directory and sources it there, the way
# `test_setup_env.sh` drives `setup.sh`'s env-sync step. It hands the function a
# SCRATCH drive set through `DJB_SELFTEST_DRIVES_DIR` — read only when set, and
# never on a gate — because driving this leg with the real drive set as the
# victim would be a gate inside a gate (rung-execution §2: a drive invokes the
# leg BODY, never the gate around it).
#
# THE PRICE, said out loud: a red drive that corrupts shared state can now
# redden drives after it that were green alone, so the composed list may name
# secondaries. The summary says so, and the first name is the one to read first.
# The leg's WALL also grows to the whole set on every red — that is what the
# whole list costs, and it is the trade that was asked for.

selftest_tally_reset() {
    SELFTEST_GREEN=0
    SELFTEST_RED=0
    SELFTEST_CANNOT=0
    SELFTEST_RED_NAMES=""
    SELFTEST_CANNOT_NAMES=""
    SELFTEST_MEMBER=""
    SELFTEST_MEMBER_T0=0
    SELFTEST_BLOCK_RC=0
    SELFTEST_MEMBER_KEY=""
    SELFTEST_MEMBER_PARTS=""
    SELFTEST_DRIVE_TREE=""
    SELFTEST_DRIVE_LISTING=""
    SELFTEST_VALVE_SAID=0
}

# --- A DRIVE'S VERDICT, CONSULTED BEFORE THE DRIVE RUNS -----------------------
#
# The key, the row and the floor are `scripts/gate_ledger.sh`'s; this is the
# wiring. A banked drive is not re-driven, a drive whose key cannot be DECIDED is
# could-not-look and never a silent pass either way, and only a green banks.
#
# THE ENGINE IS INSIDE IT NOW, and it is keyed from OUTSIDE itself exactly as a
# shell drive is. `house-rules-engine` is not a file under `scripts/tests/`, so
# it has no drive file to digest and no `# drives:` line to read — it has
# something better, which is an engine that can print its own read set:
# `python -m quality.gate --selftest-inputs` lists every path on this tree
# whose bytes can change the engine's verdict. `selftest_engine_drive_file`
# below turns that listing into a drive file the ONE key function already
# understands, so the engine's verdict is banked, consulted and refused by the
# same `drive_key`, the same row and the same attributor as every other member.
# The self-test itself stays UNCACHED inside the engine — the per-rule memo
# bypasses it on purpose — so what is keyed here is the WHOLE member, from
# outside, exactly the way a shell drive is keyed.

# selftest_drive_file <name> — where the drive the leg is about to run lives.
# The scratch branch's set is under `DJB_SELFTEST_DRIVES_DIR`, so this is the one
# derivation both branches share.
selftest_drive_file() {
    printf '%s/test_%s.sh\n' "${DJB_SELFTEST_DRIVES_DIR:-scripts/tests}" "$1"
}

# ONE `git ls-tree` PER LEG, not one per declared path per drive. The tree is
# `MEASURED_START` where the gate has one — the same bytes the full verdict is
# keyed on — and is measured here when the body is being driven standalone.
selftest_drive_listing() {
    [ -z "$SELFTEST_DRIVE_LISTING" ] || return 0
    SELFTEST_DRIVE_TREE="${MEASURED_START:-}"
    if [ -z "$SELFTEST_DRIVE_TREE" ]; then
        SELFTEST_DRIVE_TREE=$(gate_measured_tree) || SELFTEST_DRIVE_TREE=""
    fi
    [ -n "$SELFTEST_DRIVE_TREE" ] || return 1
    SELFTEST_DRIVE_LISTING=$(mktemp "${TMPDIR:-/tmp}/djb-drive-listing.XXXXXX") || return 1
    git ls-tree -r "$SELFTEST_DRIVE_TREE" >"$SELFTEST_DRIVE_LISTING" 2>/dev/null || return 1
    [ -s "$SELFTEST_DRIVE_LISTING" ] || return 1
    # FILLED HERE, IN THE LEG'S OWN SHELL, so the exported memo is inherited by
    # every `$(drive_key …)` subshell below. Called inside one it would be four
    # process starts per drive for an answer that cannot change inside a leg.
    #
    # AND IT CAN NOW FAIL FOR A REASON THAT IS NOT THE TREE. The machine half is
    # `/etc/djb/image-id` on a verifier box, and a machine that HAS that file
    # and will not show it is undecided — exit 1 here, could-not-look at the
    # caller. The caller's sentence used to be "the measured tree could not be
    # read" whatever failed, which on a box is a false statement about the one
    # machine nobody can open afterwards, so the reason travels with the status.
    drive_machine_digest >/dev/null || {
        SELFTEST_DRIVE_CANNOT="this machine could not be digested"
        return 1
    }
    return 0
}

selftest_member_cannot() {
    SELFTEST_CANNOT=$((SELFTEST_CANNOT + 1))
    SELFTEST_CANNOT_NAMES="${SELFTEST_CANNOT_NAMES} $1"
}

# --- THE ENGINE'S OWN DRIVE FILE, SYNTHESIZED FROM WHAT THE ENGINE READS ------
#
# WHERE IT LIVES, and why not beside the drives. It is derived state, rewritten
# on every consult, and it must never enter the working tree: an untracked file
# in the checkout moves the very tree the verdict is keyed on (and an untracked
# executable reds the instrument census by design). So it sits in this
# CHECKOUT's own git dir — `--absolute-git-dir`, per worktree rather than per
# family, because two worktrees of one repository share `--git-common-dir` and
# would then share one scratch file. The drive that drives this leg redirects it
# with the redirect it already sets: a SUBDIRECTORY of `DJB_SELFTEST_DRIVES_DIR`,
# which the scratch branch's `test_*.sh` glob does not reach, so the drive never
# writes into the real `.git`.
selftest_engine_dir() {
    local d
    if [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ]; then
        printf '%s/engine\n' "$DJB_SELFTEST_DRIVES_DIR"
        return 0
    fi
    d=$(git rev-parse --absolute-git-dir 2>/dev/null) || return 1
    [ -n "$d" ] || return 1
    printf '%s/djb-engine-inputs\n' "$d"
}

# THE DECLARATION IS THE EXACT COVER OF THE LISTING, never a wider one. The
# engine reads 1,100-odd paths on this tree, and `# drives:` naming every one of
# them would be a 44 KB marker, a `parts=` field five times the whole ledger and
# a key that costs 47 s to compute on a laptop — measured, not feared. So a
# directory whose ENTIRE content in the measured tree is an input is declared as
# the directory (`quality/` is population 1 of `--selftest-inputs` by
# construction, so it always collapses), and every other input is declared by
# name. The cover is EXACT in both directions: a declared directory expands to
# nothing but inputs, and every input is under exactly one declaration —
# `test_selftest_leg.sh::case_the_engines_declaration_covers_exactly_its_inputs`
# asserts that equality rather than trusting this paragraph.
#
# WHY EXACT AND NOT MERELY A SUPERSET. `drive_key`'s header says a superset is
# the safe direction for a drive, and it is — but not here: keying the engine on
# `apps/**` re-keys it on every apps rung, which is the cost this whole member
# exists to remove, and it is the shape the criteria rejected by name.
selftest_engine_cover() {
    awk '
    FNR == NR {
        tab = index($0, "\t")
        if (tab == 0) next
        p = substr($0, tab + 1)
        tree[p] = 1
        n = split(p, a, "/"); acc = ""
        for (i = 1; i < n; i++) { acc = (i == 1 ? a[1] : acc "/" a[i]); tot[acc]++ }
        next
    }
    {
        # A PATH THE MEASURED TREE DOES NOT HOLD IS NOT DROPPED SILENTLY — it is
        # not there to be digested. `plant_paths()` names files the canaries
        # CREATE (`apps/accounts/consumers.py` is one) and the probe app is a
        # directory the engine makes and removes; both are in the listing and in
        # no tree. The day one of them becomes a real file it enters the tree,
        # enters this cover and re-keys, which is the behaviour wanted.
        if (!($0 in tree)) next
        if (seen[$0]++) next
        inp[++m] = $0
        n = split($0, a, "/"); acc = ""
        for (i = 1; i < n; i++) { acc = (i == 1 ? a[1] : acc "/" a[i]); got[acc]++ }
    }
    END {
        for (d in tot) if (tot[d] == got[d]) full[d] = 1
        for (d in full) { q = d; if (sub(/\/[^\/]*$/, "", q) == 0 || !(q in full)) print d "/" }
        for (i = 1; i <= m; i++) {
            p = inp[i]; n = split(p, a, "/"); acc = ""; cov = 0
            for (j = 1; j < n; j++) { acc = (j == 1 ? a[1] : acc "/" a[j]); if (acc in full) { cov = 1; break } }
            if (!cov) print p
        }
    }
    ' "$1" "$2" | LC_ALL=C sort -u
}

# selftest_engine_drive_file <listing> — `ok <path>` on stdout, or `err <reason>`;
# exit 0 or 1. `drive_key`'s own grammar, for `selftest_drive_consult`'s reason:
# the caller reads it through `$(...)`.
#
# EVERY FAILURE HERE IS COULD-NOT-LOOK AND NEVER A SILENT RUN. `--selftest-inputs`
# is exit 2 on any derivation it could not make (a scope expanding to nothing, a
# plant placeholder it could not resolve) and prints NO paths rather than fewer:
# a key over a list that quietly lost a member is a verdict for a tree nobody
# measured. So this returns the engine's own refusal text and the consult counts
# the member could-not-look — the engine does not run, and 2 outranks every pass.
selftest_engine_drive_file() {
    local listing=$1 dir inputs rc=0 decls file preamble digest
    dir=$(selftest_engine_dir) || {
        printf 'err this checkout has no git dir to write the engine drive file into\n'
        return 1
    }
    # NOTHING IS REMOVED HERE, and that is deliberate rather than untidy: every
    # file this function writes is written with `>`, so a stale one cannot
    # survive into a key, and an `rm -rf` over a path a caller's environment
    # helped compute is a blast radius this leg has no reason to own.
    mkdir -p "$dir" 2>/dev/null || {
        printf 'err %s could not be created\n' "$dir"
        return 1
    }
    inputs="${dir}/inputs.txt"
    uv run python -m quality.gate --selftest-inputs >"$inputs" 2>"${dir}/inputs.err" || rc=$?
    if [ "$rc" != "0" ]; then
        printf 'err `--selftest-inputs` exited %s — %s\n' "$rc" \
            "$(awk '/!!/ { sub(/^[[:space:]]*!![[:space:]]*/, ""); print; exit }' \
                "$inputs" "${dir}/inputs.err" 2>/dev/null)"
        return 1
    fi
    if [ ! -s "$inputs" ]; then
        printf 'err `--selftest-inputs` exited 0 and printed no path — an engine that reads nothing is not an engine\n'
        return 1
    fi
    decls="${dir}/declared.txt"
    selftest_engine_cover "$listing" "$inputs" >"$decls" || true
    if [ ! -s "$decls" ]; then
        printf 'err none of the %s path(s) --selftest-inputs printed is in the measured tree\n' \
            "$(awk 'END { print NR + 0 }' "$inputs")"
        return 1
    fi
    # THE RAW LISTING'S OWN DIGEST IS IN THE FILE, and it is not the same thing
    # as the blobs. The cover holds the paths the tree HAS; the list itself can
    # move without any of them moving — a plant target added, a scope narrowed
    # to a file that is not here yet — and a key that could not see that would
    # be reusing a verdict for a derivation nobody ran. The digest spells no
    # path, so the floor has nothing new to cover.
    digest=$(sha256_of "$inputs") || {
        printf 'err the derived input listing could not be digested\n'
        return 1
    }
    file="${dir}/test_house-rules-engine.sh"
    preamble="${dir}/drive_preamble.sh"
    {
        printf '# drives: %s\n' "$(tr '\n' ' ' <"$decls")"
        printf '# the house-rules engine, keyed from outside itself. Derived, never edited.\n'
        printf '# inputs-digest %s\n' "$digest"
    } >"$file" || {
        printf 'err %s could not be written\n' "$file"
        return 1
    }
    printf '# the engine drive file has no preamble to source — it is keyed, never run.\n' \
        >"$preamble" || {
        printf 'err %s could not be written\n' "$preamble"
        return 1
    }
    printf 'ok %s\n' "$file"
}

# selftest_drive_consult <name> — 0 RUN THE DRIVE, 1 do not. A 1 has already
# said why and has already counted the member, in exactly one of two ways:
# REUSED (green) or could-not-key (could-not-look).
selftest_drive_consult() {
    local name=$1 file keyout row oldparts moved synth
    SELFTEST_MEMBER_KEY=""
    SELFTEST_MEMBER_PARTS=""
    SELFTEST_MEMBER_MACHINE=""
    if [ "$name" = "house-rules-engine" ]; then
        # THE ENGINE IS KEYED BEFORE THE TREE IS READ FOR ANYTHING ELSE, and it
        # is the one member whose drive file does not exist until this line
        # writes it. Everything after the `if` is the same code every drive runs.
        SELFTEST_DRIVE_CANNOT=""
        if ! selftest_drive_listing; then
            echo "  drive ${name}: could not key — ${SELFTEST_DRIVE_CANNOT:-the measured tree could not be read}"
            selftest_member_cannot "$name"
            return 1
        fi
        synth=$(selftest_engine_drive_file "$SELFTEST_DRIVE_LISTING") || true
        case "$synth" in
        "ok "*) file=${synth#ok } ;;
        *)
            echo "  drive ${name}: could not key — ${synth#err }"
            selftest_member_cannot "$name"
            return 1
            ;;
        esac
    elif [ "${name#local:}" != "$name" ]; then
        # A PRODUCT DRIVE IS NOT KEYED HERE EITHER, AND FOR THE SAME REASON —
        # `drive_key` wants a `drive_preamble.sh` beside the file and the
        # drawer has none. It used to fall out of this function silently, on a
        # `selftest_drive_file` that composed `scripts/tests/test_local:x.sh`
        # and found nothing; silent is the one thing a member that runs every
        # single gate must not be the review that found it).
        echo "  drive ${name}: not consulted — a product drive is not keyed or banked; it runs on every gate"
        return 0
    else
        file=$(selftest_drive_file "$name")
        [ -f "$file" ] || return 0
        SELFTEST_DRIVE_CANNOT=""
        if ! selftest_drive_listing; then
            echo "  drive ${name}: could not key — ${SELFTEST_DRIVE_CANNOT:-the measured tree could not be read}"
            selftest_member_cannot "$name"
            return 1
        fi
    fi
    keyout=$(drive_key "$file" "$SELFTEST_DRIVE_TREE" "$SELFTEST_DRIVE_LISTING") || true
    case "$keyout" in
    "ok ${DRIVE_KEY_SCHEMA}:"*)
        SELFTEST_MEMBER_KEY=$(printf '%s\n' "$keyout" | awk '{print $2}')
        SELFTEST_MEMBER_PARTS=$(printf '%s\n' "$keyout" | awk '{print $3}')
        # THE CITATION VALVE, COUNTED AND PRINTED. A `# cites:` line tells the
        # floor a spelled path is a CITATION rather than a subject, and a
        # cited path is in no key — so a drive that cited its way out of a file
        # it really reads would be reused over that file's changed bytes. The
        # count is printed beside the drive for the reason every valve here is
        # printed: an allow-list nobody sees is an off switch.
        SELFTEST_MEMBER_CITES=$(printf '%s\n' "$keyout" | awk '{print $4}')
        # WHICH MACHINE THIS ROW BELONGS TO, printed rather than inferred. The
        # machine half of a drive key is the IMAGE on a verifier box and
        # bash/git/uname anywhere else, so a row can now TRAVEL between two
        # boxes of one image and can still never cross between a box and this
        # laptop. `machine=image:<ami>` beside a REUSED is how a reader tells
        # the two apart without opening the ledger — and on a miss it is how
        # "the machine moved" is read at all.
        SELFTEST_MEMBER_MACHINE=$(printf '%s\n' "$keyout" | awk '{sub(/^machine=/, "", $5); print $5}')
        case "${SELFTEST_MEMBER_CITES:-cites=0}" in
        cites=0) ;;
        cites=*)
            echo "  drive ${name}: ${SELFTEST_MEMBER_CITES#cites=} path(s) CITED, in no key (# cites:) — a citation is not a subject"
            ;;
        esac
        ;;
    *)
        echo "  drive ${name}: could not key — ${keyout#err }"
        selftest_member_cannot "$name"
        return 1
        ;;
    esac
    # ONE MEMBER, ONE RUN, NOT CONSULTED — named by its registration block,
    # which decides before this call whether the member's run this time is a
    # different thing from the one its key describes. The key is computed
    # above all the same, so a green from this run still BANKS; it is the
    # LOOKUP that is skipped. The only caller is `selftest_shapes` in whole
    # mode: its key carries neither the tree nor the mode, and drive rows
    # travel between banks, so a banked green would stand in for a whole run
    # over any change the key does not read.
    if [ -n "${SELFTEST_CONSULT_SKIP:-}" ] && [ "$SELFTEST_CONSULT_SKIP" = "$name" ]; then
        echo "  drive ${name}: not consulted — ${SELFTEST_CONSULT_SKIP_WHY:-its registration says so}; it runs, and a green still banks"
        SELFTEST_CONSULT_SKIP=""
        return 0
    fi
    if [ -n "${DJB_SELFTEST_NO_REUSE:-}" ]; then
        if [ "$SELFTEST_VALVE_SAID" = "0" ]; then
            echo "  == drive verdicts NOT consulted: DJB_SELFTEST_NO_REUSE is set =="
            echo "     every drive runs and every green still banks — a drive row is keyed"
            echo "     on its INPUTS, so a forced green is newer evidence for the same key."
            SELFTEST_VALVE_SAID=1
        fi
        return 0
    fi
    row=$(drive_ledger_lookup "$SELFTEST_MEMBER_KEY") || row=""
    if [ -n "$row" ]; then
        echo "  drive ${name}: REUSED from ${SELFTEST_MEMBER_KEY} (banked $(printf '%s\n' "$row" | awk '{print $4}')) machine=${SELFTEST_MEMBER_MACHINE:-unstated}"
        SELFTEST_GREEN=$((SELFTEST_GREEN + 1))
        return 1
    fi
    # THE MISS, ATTRIBUTED. A banked row for this drive at ANOTHER key carries
    # the per-component digests this run just recomputed, so the line can name
    # the input that moved instead of reporting only that something did.
    row=$(drive_ledger_last_for "$name") || row=""
    if [ -n "$row" ]; then
        oldparts=$(drive_row_parts "$row")
        if [ -n "$oldparts" ]; then
            moved=$(drive_moved_component "$oldparts" "$SELFTEST_MEMBER_PARTS")
            if [ -n "$moved" ]; then
                echo "  miss: ${moved} moved since $(printf '%s\n' "$row" | awk '{print $2}') machine=${SELFTEST_MEMBER_MACHINE:-unstated}"
            fi
        fi
    fi
    return 0
}

# Called immediately before a member runs; `_end` is called with its status and
# prints the one line per member this leg promises. The pair exists rather than
# one wrapper function so that every drive's own block stays untouched between
# them.
# --- THE SHARD, AND THE ORDER IT WALKS --------------------------------------
#
# ONE REGISTERED ORDER, DERIVED FROM THE FILE AND NOT TYPED ANYWHERE. The drives
# in this leg are a straight-line sequence of named blocks — deliberately, and
# `scripts/tests/test_selftest_leg.sh` asserts it is not a loop over a directory
# glob, because the set a census pins must be readable out of this file. The
# ORDER is therefore already written down: it is the order of the column-zero
# `./scripts/tests/test_<name>.sh` invocation lines, the same lines
# `scripts/tests/test_drive_preamble.sh` censuses against the directory.
# `selftest_registered_drives` reads exactly those, so the walk and the census
# cannot come apart: there is no second list.
#
# THE SPLIT IS BY DURATION, NOT BY INDEX, AND THE MEASUREMENT BEHIND THAT IS
# BOXBANK-20. The selftest unit took 1457 s on one box while the other five
# units were done by minute 9, and 1457 is the arithmetic SUM of the forty
# drives run one at a time (loop_scope 309 · the engine 238 · gate_explain 190 ·
# list_legs 173 · …). Splitting that sum BY INDEX — drive i runs when
# `i % K == k`, which is what this block did until now — balances the COUNT and
# says nothing about the price: shard 0 drew the engine's own self-test AND
# every index ≡ 0 member, so the split got WORSE past ten boxes (N=12 predicted
# 643 s against N=10's 531). A round-robin over items whose costs differ by two
# orders of magnitude is a count, and the wall is a sum.
#
# SO THE PARTITION IS LPT (longest-processing-time-first), the standard greedy
# for exactly this problem: sort the members by their measured wall, heaviest
# first, and give each one to the shard that is currently lightest. Its bound is
# the one the drive asserts — the heaviest shard is at most `total/S` plus the
# single heaviest member — so a shard can never be worse than one long drive
# above the perfect split, at any S.
#
# THE WEIGHTS ARE READ, NEVER GUESSED, AND THE FILE IS A HINT. They come out of
# `scripts/gate_member_durations.json` through the SAME reader the always-on leg
# uses (`always_on__read_durations`) — one measurement, one parser, no second
# table. A member the file does not name takes the MEDIAN of the rows that do
# exist for this population, which is the cheapest honest guess and is stated on
# the leg's own line. NO FILE AT ALL IS NOT A REFUSAL: absence means unmeasured,
# the leg says so and falls back to the index round-robin this block shipped
# before — a tree before its first `--store-durations` still shards.
#
# THE ENGINE IS A MEMBER LIKE ANY OTHER. `house-rules-engine` is not a drive
# under `scripts/tests/` and has no index, which is why the round-robin had to
# state its shard rather than derive one; under the partition it carries its own
# row (or the median) and lands wherever the balance puts it. It is still run
# exactly once across the S shards, which was the only property the stated
# shard 0 was protecting.
#
# DETERMINISTIC FOR A TABLE AND AN S, because every shard computes the WHOLE
# partition and then reads its own row out of it: same population, same table,
# same S, same assignment on every box. Ties are broken by the registered order
# (the first member wins the heavier slot; the lowest-numbered shard wins the
# lighter load), so there is no clock, no hash and no `sort -R` anywhere in it.
#
# UNSHARDED IS THE DEFAULT AND COSTS NOTHING: with no k/K the gate below returns
# immediately and this leg runs exactly what it always ran, in exactly the order
# it ran it.
SELFTEST_SHARD_K=""
SELFTEST_SHARD_N=""
SELFTEST_DRIVE_INDEX=0
#: The computed partition: a scratch file of `<member> <shard>` lines, or empty
#: when there was no table to balance over (the round-robin fallback below).
SELFTEST_SHARD_MAP=""

# selftest_shard_population — every member this leg is about to walk, in the
# order it walks them: the engine first, then the drives.
#
# IT IS THE LEG'S OWN TWO BRANCHES, IN ONE PLACE. The real branch is the
# registry (`selftest_registered_drives`, which already carries the product's
# drawer as `local:<name>`); the scratch branch is the planted directory the
# leg's own drive hands it, and the drawer runs BESIDE that set — which is
# exactly what `selftest_scratch_drives` followed by `selftest_local_drives`
# does one screen down. A population that disagreed with the walk would be a
# partition naming members nobody runs, so it is derived from the same two
# readers rather than from a third.
selftest_shard_population() {
    local d="" name="" rows=""
    printf '%s\n' house-rules-engine
    if [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ]; then
        for d in "$DJB_SELFTEST_DRIVES_DIR"/test_*.sh; do
            [ -f "$d" ] || continue
            name=${d##*/}
            name=${name#test_}
            printf '%s\n' "${name%.sh}"
        done
    fi
    command -v selftest_registered_drives >/dev/null 2>&1 || return 0
    rows=$(selftest_registered_drives) || return 1
    if [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ]; then
        # THE DRAWER ONLY. The planted set stands in for this file's own drives;
        # the registry's non-`local:` names are those, and printing them here
        # would put a member in the partition that the scratch branch never
        # walks.
        printf '%s\n' "$rows" | awk '/^local:/ { print }'
        return 0
    fi
    printf '%s\n' "$rows"
}

# selftest_shard_plan <k> <S> — fill `SELFTEST_SHARD_MAP` and print the one line
# per shard this leg promises. Never a refusal: every arm that cannot balance
# says so and leaves the map empty, which is the round-robin.
selftest_shard_plan() {
    local k=$1 n=$2 path="" pop="" plan="" mapf="" row="" med="" machine=""
    SELFTEST_SHARD_MAP=""
    if ! command -v always_on__read_durations >/dev/null 2>&1 ||
        ! command -v always_on_durations_path >/dev/null 2>&1; then
        echo "  selftest shard ${k}/${n}: the index round-robin (the durations reader is not in this shell; house-rules-engine runs in shard 0)"
        return 0
    fi
    path=$(always_on_durations_path)
    if ! always_on__read_durations "$path"; then
        echo "  selftest shard ${k}/${n}: the index round-robin (no durations table at ${path} — the file is a HINT and its absence means unmeasured, never a refusal; house-rules-engine runs in shard 0)"
        return 0
    fi
    machine=${ALWAYS_ON_MACHINE:-unstated}
    pop=$(mktemp "${TMPDIR:-/tmp}/djb-selftest-shard-pop.XXXXXX") || pop=""
    plan=$(mktemp "${TMPDIR:-/tmp}/djb-selftest-shard-plan.XXXXXX") || plan=""
    mapf=$(mktemp "${TMPDIR:-/tmp}/djb-selftest-shard-map.XXXXXX") || mapf=""
    if [ -z "$pop" ] || [ -z "$plan" ] || [ -z "$mapf" ]; then
        echo "  selftest shard ${k}/${n}: the index round-robin (no scratch file for the partition; house-rules-engine runs in shard 0)"
        return 0
    fi
    selftest_shard_population >"$pop" || true
    if [ ! -s "$pop" ]; then
        echo "  selftest shard ${k}/${n}: the index round-robin (the member population would not derive; house-rules-engine runs in shard 0)"
        return 0
    fi
    # THE PARTITION, IN ONE awk OVER TWO FILES: the measured table first, the
    # population second. Bash 3.2 has no associative arrays and no `sort -k` by
    # a numeric column that keeps the input order on a tie, so the sort is an
    # insertion sort over forty items inside the same pass that assigns them.
    awk -v n="$n" '
        FNR == NR { secs[$1] = $2 + 0; next }
        { cnt++; name[cnt] = $1 }
        END {
            # THE MEDIAN OF THE ROWS THAT EXIST, and the population it is taken
            # over is THIS leg`s members — not every row in the file. A table
            # naming members this gate no longer has would otherwise move the
            # guess for the members it does have.
            m = 0
            for (j = 1; j <= cnt; j++) {
                if (name[j] in secs) { m++; v[m] = secs[name[j]] }
            }
            for (a = 2; a <= m; a++) {
                x = v[a]
                b = a - 1
                while (b >= 1 && v[b] > x) { v[b + 1] = v[b]; b-- }
                v[b + 1] = x
            }
            med = 0
            if (m == 1) { med = v[1] }
            else if (m > 1) {
                if (m % 2) { med = v[(m + 1) / 2] }
                else { med = int((v[m / 2] + v[m / 2 + 1]) / 2) }
            }
            heaviest = 0
            total = 0
            for (j = 1; j <= cnt; j++) {
                if (name[j] in secs) { w[j] = secs[name[j]]; meas[j] = 1 }
                else { w[j] = med; meas[j] = 0 }
                total += w[j]
                if (w[j] > heaviest) { heaviest = w[j] }
            }
            for (t = 0; t < n; t++) { load[t] = 0; count[t] = 0; guessed[t] = 0 }
            # LPT: the heaviest unassigned member, into the lightest shard.
            # Both ties go to the LOWEST index, which is what makes this
            # deterministic rather than merely balanced.
            for (r = 1; r <= cnt; r++) {
                best = 0
                for (j = 1; j <= cnt; j++) {
                    if (taken[j]) { continue }
                    if (best == 0 || w[j] > w[best]) { best = j }
                }
                if (best == 0) { break }
                taken[best] = 1
                s = 0
                for (t = 1; t < n; t++) { if (load[t] < load[s]) { s = t } }
                load[s] += w[best]
                count[s]++
                if (!meas[best]) { guessed[s]++ }
                print "map", name[best], s
            }
            for (t = 0; t < n; t++) {
                print "shard", t, count[t], load[t], guessed[t]
            }
            print "meta", med, total, heaviest, cnt
        }
    ' "$ALWAYS_ON_TABLE" "$pop" >"$plan"
    awk '$1 == "map" { print $2, $3 }' "$plan" >"$mapf"
    if [ ! -s "$mapf" ]; then
        echo "  selftest shard ${k}/${n}: the index round-robin (the partition came back empty; house-rules-engine runs in shard 0)"
        return 0
    fi
    SELFTEST_SHARD_MAP="$mapf"
    med=$(awk '$1 == "meta" { print $2 }' "$plan")
    row=$(awk -v k="$k" '$1 == "shard" && $2 == k { print $3, $4, $5 }' "$plan")
    # THE LINE SAYS WHICH TABLE IT READ, and that is not decoration: the file
    # committed today was measured on a Mac (`sweep` 395 s there, 45 s on a
    # box), so a shard predicting 400 s may be predicting somebody else's
    # machine. A reader comparing the prediction against the wall needs to know
    # whose clock the prediction came from.
    echo "  selftest shard ${k}/${n}: $(printf '%s' "$row" | awk '{print $1}') members, predicted $(printf '%s' "$row" | awk '{print $2}') s (LPT over ${path} measured on ${machine}; $(printf '%s' "$row" | awk '{print $3}') unmeasured at the median ${med} s)"
    return 0
}

# selftest_shard_takes <member> — 0 to run it, 1 to skip. It INCREMENTS the drive
# index, so it is called exactly once per member and only from member_begin.
selftest_shard_takes() {
    [ -n "$SELFTEST_SHARD_N" ] || return 0
    local i="" assigned=""
    if [ "$1" != "house-rules-engine" ]; then
        i=$SELFTEST_DRIVE_INDEX
        SELFTEST_DRIVE_INDEX=$((SELFTEST_DRIVE_INDEX + 1))
    fi
    if [ -n "$SELFTEST_SHARD_MAP" ] && [ -f "$SELFTEST_SHARD_MAP" ]; then
        assigned=$(awk -v n="$1" '$1 == n { s = $2; seen = 1 } END { if (seen) { print s } }' "$SELFTEST_SHARD_MAP")
        if [ -z "$assigned" ]; then
            # A MEMBER THE PARTITION DOES NOT NAME — the population moved
            # between the plan and the walk. Shard 0 takes it, EVERY shard
            # computes the same partition so exactly one of them does, and the
            # line is printed by all of them so the arithmetic is readable.
            echo "  drive $1: not named by the partition (the population moved under the leg) — shard 0 takes it"
            assigned=0
        fi
        [ "$assigned" = "$SELFTEST_SHARD_K" ]
        return $?
    fi
    if [ -z "$i" ]; then
        [ "$SELFTEST_SHARD_K" = "0" ]
        return $?
    fi
    [ "$((i % SELFTEST_SHARD_N))" = "$SELFTEST_SHARD_K" ]
}

selftest_member_begin() {
    if ! selftest_shard_takes "$1"; then
        # PRINTED, NEVER SILENT: a shard that said nothing about what it did not
        # run is a shard nobody can add up.
        echo "  drive $1: not in shard ${SELFTEST_SHARD_K}/${SELFTEST_SHARD_N}"
        return 1
    fi
    SELFTEST_MEMBER="$1"
    SELFTEST_MEMBER_T0=$(date +%s)
    # THE CONSULT SITS AFTER THE SHARD AND BEFORE THE CLOCK IS READ AGAIN, so a
    # reused member still ADVANCES THE DRIVE INDEX exactly as a driven one does
    # — the split is by index over the registered order and a reuse must not
    # renumber it.
    selftest_drive_consult "$1" || return 1
    return 0
}

selftest_member_end() {
    _SELFTEST_RC="$1"
    _SELFTEST_OUTRANK="${2:-}"
    _SELFTEST_TOOK=$(($(date +%s) - SELFTEST_MEMBER_T0))
    echo "  drive ${SELFTEST_MEMBER}: exit ${_SELFTEST_RC} (${_SELFTEST_TOOK}s)"
    # THE SECONDS GO WHERE EVERY OTHER MEMBER'S SECONDS GO. A drive is a member
    # of the gate exactly as a leg is, and the `--loop` always-on set is derived
    # from one file covering both — see the `member-durations` fence. A REUSED
    # member never reaches this line, which is right: its wall was somebody
    # else's measurement and recording it would say this run timed it.
    gate_member_record "$SELFTEST_MEMBER" "$_SELFTEST_TOOK"
    # ONLY A GREEN BANKS, and only a member whose key this leg could decide. A
    # red or a could-not-look has cleared nothing, so a row for it would be a
    # verdict vouching for bytes nobody drove — the one failure mode of a cache
    # that looks exactly like speed. `DJB_GATE_LEGS_DRY` banks nothing either:
    # under it no body ran at all.
    # `outrank` IS NOT PART OF THIS TEST, and was only ever in it because the one
    # member that passes it — the engine — had no key to bank against. It says
    # what a NON-ZERO status means for that member (could-not-look, never a red),
    # and a zero is a green whoever earned it: a green engine banks exactly as a
    # green drive does, which is the whole of the engine's banked verdict.
    if [ "$_SELFTEST_RC" = "0" ] &&
        [ -n "${SELFTEST_MEMBER_KEY:-}" ] && [ -z "${DJB_GATE_LEGS_DRY:-}" ]; then
        drive_ledger_record "$SELFTEST_MEMBER_KEY" "$SELFTEST_MEMBER" \
            "$_SELFTEST_TOOK" "$SELFTEST_DRIVE_TREE" "$SELFTEST_MEMBER_PARTS" || true
    fi
    SELFTEST_MEMBER_KEY=""
    SELFTEST_MEMBER_PARTS=""
    if [ "$_SELFTEST_RC" = "0" ]; then
        SELFTEST_GREEN=$((SELFTEST_GREEN + 1))
    elif [ "$_SELFTEST_RC" = "2" ] || [ -n "$_SELFTEST_OUTRANK" ]; then
        SELFTEST_CANNOT=$((SELFTEST_CANNOT + 1))
        SELFTEST_CANNOT_NAMES="${SELFTEST_CANNOT_NAMES} ${SELFTEST_MEMBER}"
    else
        SELFTEST_RED=$((SELFTEST_RED + 1))
        SELFTEST_RED_NAMES="${SELFTEST_RED_NAMES} ${SELFTEST_MEMBER}"
    fi
}

# >>> local-drives >>>
# THE PRODUCT'S OWN DRIVES, AND THE SECOND PLACE THIS LEG IS A LOOP ON PURPOSE.
#
# Every registration below is a named straight-line block, deliberately, so the
# set a census pins is readable out of this file — and that argument is about
# THIS FILE's drives. A product's drives are not in this file and cannot be:
# their whole point is that a product grows one by dropping a file into
# `scripts/local/drives/`, the platform-extension-1 convention the leg drawer
# already runs on. So the population is the REGISTRY's, read through the same
# one reader as both of this file's own homes
# (`selftest_registered_drives --with-path`), and this walks exactly what it is
# handed, in the order it is handed it — which is what keeps the shard index,
# the `composed-of` column and the verdict row agreeing about which member is
# which.
#
# IT RUNS AFTER EVERY TEMPLATE DRIVE, and that is the honest order rather than
# an arbitrary one: a product drive is the most likely member to be a SECONDARY
# red left by state an earlier drive moved, so the composition's "read the FIRST
# name first" advice stays true with the product's members last.
#
# IT IS CALLED FROM BOTH BRANCHES, the real one and the scratch one, because
# the drawer is a DIFFERENT population from `DJB_SELFTEST_DRIVES_DIR`'s planted
# set: the scratch branch stands in for this file's own drives, and a leg that
# skipped the product's drawer whenever it was being driven would be a leg whose
# product half no case could ever reach.
#
# THE STATUS VARIABLE IS ITS OWN, AND THIS PARAGRAPH MAY NOT SPELL THE OTHER
# ONE. `test_selftest_leg.sh::case_every_exit_in_the_leg_body_is_inside_a_drive_subshell`
# COUNTS the block wrapper's closing line, literally, once per registration,
# against this file's own invocation lines — so a loop with one body and N
# members must not borrow that spelling, and a COMMENT that quoted it would be
# counted exactly like code (rung-execution §5: a sentence that spells a
# censused marker is a phantom registration). Hence `drive_rc`, and hence this
# sentence naming the case instead of the string.
selftest_local_drives() {
    local rows="" rc=0 name="" file="" drive_rc=0
    # `gate_capture` and not a bare `$( )`: a refusal recorded inside a command
    # substitution dies with the subshell, and the banner would then print some
    # other leg's cause. Same reader, same reason, as the always-on leg's own
    # census capture.
    gate_capture rows selftest_registered_drives --with-path || rc=$?
    if [ "$rc" != "0" ]; then
        gate_cause
        echo "!! the drive registry refused — see above. The product's drive drawer is" >&2
        echo "   read by the same one reader as this file's own drives, so a refusal" >&2
        echo "   there is this leg's could-not-look and never a smaller drive set." >&2
        echo "   cause: ${GATE_LAST_REFUSAL}" >&2
        selftest_member_cannot local-drives
        return 0
    fi
    while IFS='	' read -r name file; do
        case "$name" in
        local:*) ;;
        *) continue ;;
        esac
        if selftest_member_begin "$name"; then
            drive_rc=0
            ("$file") || drive_rc=$?
            if [ "$drive_rc" = "2" ]; then
                echo "!! ${name} COULD NOT LOOK — see above." >&2
                echo "   A driver that could not run its cases has not cleared them." >&2
            elif [ "$drive_rc" != "0" ]; then
                echo "!! ${name} is red. It is the PRODUCT's drive: this gate found it, ran" >&2
                echo "   it and named it, and says nothing about whether it is CORRECT." >&2
                echo "   Read its own output above." >&2
            fi
            selftest_member_end "$drive_rc"
        fi
    done <<LOCAL_DRIVE_ROWS
${rows}
LOCAL_DRIVE_ROWS
    return 0
}
# <<< local-drives <<<

# THE SCRATCH BRANCH — the only loop over a directory in this leg, and it is
# never the real one. `DJB_SELFTEST_DRIVES_DIR` is read here and nowhere else.
selftest_scratch_drives() {
    _SELFTEST_D=""
    _SELFTEST_NAME=""
    _SELFTEST_RC2=0
    echo "  DJB_SELFTEST_DRIVES_DIR is set — driving ${DJB_SELFTEST_DRIVES_DIR}"
    echo "  and NOT scripts/tests/. This is the leg's own drive's scratch set."
    for _SELFTEST_D in "$DJB_SELFTEST_DRIVES_DIR"/test_*.sh; do
        [ -f "$_SELFTEST_D" ] || continue
        _SELFTEST_NAME="$(basename "$_SELFTEST_D" .sh)"
        _SELFTEST_NAME="${_SELFTEST_NAME#test_}"
        # THE RETURN IS READ, and until the drive verdicts arrived it was not:
        # `selftest_member_begin` already answered 1 for a member outside the
        # shard, and this loop ran it anyway. The real branch below has always
        # read it (`if selftest_member_begin …; then`), so the two branches
        # disagreed about the one thing this loop exists to drive.
        if selftest_member_begin "$_SELFTEST_NAME"; then
            _SELFTEST_RC2=0
            ("$_SELFTEST_D") || _SELFTEST_RC2=$?
            selftest_member_end "$_SELFTEST_RC2"
        fi
    done
}

# THE EXIT, composed once, from the whole population rather than from whichever
# member happened to be first.
selftest_compose() {
    if [ -n "${SELFTEST_DRIVE_LISTING:-}" ]; then
        rm -f "$SELFTEST_DRIVE_LISTING"
        SELFTEST_DRIVE_LISTING=""
    fi
    echo ""
    echo "  selftest: ${SELFTEST_GREEN} drive(s) green · ${SELFTEST_RED} red · ${SELFTEST_CANNOT} could-not-look (the house-rules engine's own selftest counted as one)"
    if [ "$SELFTEST_CANNOT" -gt 0 ]; then
        echo "!! COULD NOT LOOK:${SELFTEST_CANNOT_NAMES}" >&2
        if [ "$SELFTEST_RED" -gt 0 ]; then
            echo "!! and RED:${SELFTEST_RED_NAMES}" >&2
        fi
        echo "   2 outranks 1: a driver that could not run its cases has not cleared" >&2
        echo "   them, whatever the rest of the set did. Read the FIRST name above" >&2
        echo "   first — every drive ran, so a later name can be a SECONDARY red left" >&2
        echo "   by state an earlier one moved." >&2
        return 2
    fi
    if [ "$SELFTEST_RED" -gt 0 ]; then
        echo "!! RED:${SELFTEST_RED_NAMES}" >&2
        echo "   Every drive ran and every red is named above — that is what this leg" >&2
        echo "   is for. Read the FIRST one first: a red drive can leave state a later" >&2
        echo "   drive trips on, so a later name can be a secondary." >&2
        return 1
    fi
    return 0
}

# selftest_drives_leg [k K] — every drive, or the k-th of every K of them.
# A malformed pair is exit 2 and never a smaller run: a shard that judged a set
# nobody asked for is worse than a refusal.
selftest_drives_leg() {
    # `--leg selftest --shard k/N` REACHES THIS BODY THROUGH ITS GLOBALS, and it
    # has to: the ONE call site below is pinned character for character by
    # `scripts/tests/test_selftest_leg.sh` (the errexit-safe `|| RC=$?` form), so
    # the shard cannot arrive as an argument there without moving a literal that
    # drive reads. The pair is 1-BASED at the flag and 0-based here — the
    # listing's grammar and this function's own, translated in one place.
    # Extracted standalone by that drive with neither variable set, which is why
    # both are read defensively.
    if [ "$#" = "0" ] && [ -n "${GATE_SHARD_K:-}" ] && [ "${GATE_LEG_UNIT:-}" = "selftest" ]; then
        set -- "$((GATE_SHARD_K - 1))" "${GATE_SHARD_N}"
    fi
    selftest_tally_reset
    SELFTEST_SHARD_K=""
    SELFTEST_SHARD_N=""
    SELFTEST_DRIVE_INDEX=0
    if [ "$#" -gt 0 ] && [ -n "${1:-}" ]; then
        case "${1:-}:${2:-}" in
        *[!0-9]*:* | *:*[!0-9]* | *: | :*)
            echo "!! selftest_drives_leg: '${1:-}' '${2:-}' is not a k/K pair of integers." >&2
            return 2
            ;;
        esac
        if [ "$2" -lt 1 ] || [ "$1" -ge "$2" ]; then
            echo "!! selftest_drives_leg: shard ${1}/${2} is outside 0..$(($2 - 1)) of ${2}." >&2
            return 2
        fi
        SELFTEST_SHARD_K=$1
        SELFTEST_SHARD_N=$2
        echo "  shard ${SELFTEST_SHARD_K}/${SELFTEST_SHARD_N} of the registered drive order"
        echo "  (the order is this file's own ./scripts/tests/test_<name>.sh lines;"
        echo "   the partition below is duration-balanced, not by index)"
        selftest_shard_plan "$SELFTEST_SHARD_K" "$SELFTEST_SHARD_N"
    fi

    if selftest_member_begin house-rules-engine; then
    set +e
    uv run python -m quality.gate --selftest
    SELF_RC=$?
    set -e
    # The engine is counted the same way every drive is, with ONE difference the
    # second argument carries: ANY non-zero from it is could-not-look, because a
    # canary that did not fire is enforcement that stopped looking rather than a
    # rule that failed. That was this block's rule before the move and it stands.
    selftest_member_end "$SELF_RC" outrank
    if [ "$SELF_RC" != "0" ]; then
        echo "!! ENFORCEMENT ITSELF IS BROKEN — a dead canary outranks any pass." >&2
        echo "   Recorded as could-not-look. The drives below STILL RUN: the leg's" >&2
        echo "   exit is composed at the end, and a 25-minute gate should print its" >&2
        echo "   whole red list once." >&2
    fi
    fi

    if [ -n "${DJB_SELFTEST_DRIVES_DIR:-}" ]; then
        selftest_scratch_drives
        selftest_local_drives
        SELFTEST_COMPOSED_RC=0
        selftest_compose || SELFTEST_COMPOSED_RC=$?
        return "$SELFTEST_COMPOSED_RC"
    fi

# THE SHELL REFUSALS BELONG IN THIS LEG AND IN NO OTHER. A canary proves
# a rule still fires; these prove a SCRIPT still refuses — same property, same
# failure mode (a guard silently deleted, the happy path still green), and so
# the same leg. `scripts/backup.sh` and `scripts/restore_drill.sh` are almost
# entirely made of refusals, and until now every one of them had been driven
# exactly once, by hand, on the day it was written.
#
# HERE AND NOT IN `--fast`/`--loop`, deliberately: this driver takes a real
# `pg_dump` of this checkout's database (the `--to-dir` case is the only way to
# prove the copy mechanism `--to-s3` shares), so it needs docker and a migrated
# database — neither of which `--fast` is allowed to need — and it would put
# real seconds on the per-rung tier, which the declared criteria pin. The
# full gate already owns both, and pre-push is where a deleted refusal must not
# get through.
#
# Exit semantics are this file's: 2 is could-not-look (no docker, no database)
# and outranks a pass; 1 is a refusal that did not fire.
if selftest_member_begin backup_restore; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_backup_restore.sh
DRIVE_RC=$?
set -e
if [ "$DRIVE_RC" = "2" ]; then
    echo "!! the backup/restore refusal drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$DRIVE_RC" != "0" ]; then
    echo "!! a backup or restore refusal did not fire. A guard nothing drives is a" >&2
    echo "   guard that can be deleted by accident and stay deleted." >&2
    exit "$DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE SECOND DRIVE, and it belongs here for the identical reason. The
# checkout-machinery frame is made of refusals and one of them is a licence to
# DESTROY: --sweep touches only what a live-checkout derivation vouches for,
# --force-foreign prints every name before it acts, a warm cache is never in the
# default broom, and an identity outside the derivation is refused however loud
# the flags. Every one of those was proven once, by hand, on the day it was
# written — which is exactly the state scripts/backup.sh was in before its own drive existed.
#
# IT CREATES ITS OWN MACHINERY AND SWEEPS THAT. The driver invents a scratch
# identity nothing derives, plants databases, a durable Schedule and an open
# execution under it, aims every destructive case with --only at that identity,
# and tears the rest down in a trap. It REFUSES TO START if a checkout this run
# can see derives the scratch identity. Nothing on this machine that anybody
# owns is inside its reach, which is what makes proving a destroy path possible
# at all on a shared box.
#
# WHAT DOMINATES ITS COST, and no number, because a number here goes stale
# without this file changing: docker round trips (a schedule created and
# deleted, a workflow started and terminated, databases created and dropped),
# and the last case, which runs this whole drive again from two clones at once
# to prove two checkouts cannot destroy each other's machinery. Those two
# children are NARROWED to the clone-isolation chain and name the cases they
# ran — `SWEEP_CHILD_CHAIN` in the drive's own file is where that argument
# lives, and the drive's header is where the rest of it does. It is the price
# of the only thing in this repository that drives a destroy path end to end,
# and it is paid at push rather than per rung.
if selftest_member_begin sweep; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_sweep.sh
SWEEP_DRIVE_RC=$?
set -e
if [ "$SWEEP_DRIVE_RC" = "2" ]; then
    echo "!! the checkout-machinery drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SWEEP_DRIVE_RC" != "0" ]; then
    echo "!! a sweep refusal did not fire, or the registry no longer matches its own" >&2
    echo "   declared population. Both halves are load-bearing: a broom whose refusals" >&2
    echo "   nothing exercises can be widened by accident and stay widened." >&2
    exit "$SWEEP_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE THIRD DRIVE, same leg and the same reason. `pm_merge.sh`
# is the merge window's exit-owning wrapper and it is made almost entirely of
# refusals — a branch name that resolves to nothing, a branch already merged, a
# dirty tree, a piped stdout, a conflict, a foreign checkout. Every one of them
# was proven once, by hand, on the day it was written, which is the state
# `scripts/backup.sh` and `scripts/sweep.sh` were each in before their own drives existed.
#
# IT BUILDS ITS OWN REPOSITORIES. Each case runs against a throwaway git repo
# under `mktemp -d`, carrying a copy of pm_merge.sh and a STUB `check.sh`, so
# nothing in this checkout is merged and the real gate is never re-entered from
# inside itself. It needs no docker and no database — unlike its two siblings
# above it can never degrade to could-not-look on a bare machine — and costs
# ~15s, nearly all of it git process starts.
if selftest_member_begin pm_merge; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_pm_merge.sh
MERGE_DRIVE_RC=$?
set -e
if [ "$MERGE_DRIVE_RC" = "2" ]; then
    echo "!! the pm_merge refusal drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$MERGE_DRIVE_RC" != "0" ]; then
    echo "!! a pm_merge refusal did not fire, or the wrapper stopped owning its exit" >&2
    echo "   status. That wrapper is the only thing standing between a mistyped branch" >&2
    echo "   name and a green gate on an unmerged tree." >&2
    exit "$MERGE_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin pm_fold; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: pm_fold >>>
# THE FOLD'S DRIVE, and it is pm_merge's sibling one door over. NO ORDINAL,
# deliberately: two blocks above call themselves "the third" and "the fourth"
# drive and a count in prose goes stale without the prose changing.
#
# WHY IT BINDS HERE. `scripts/pm_fold.sh` is the only thing in this repository
# that COMMITS UNATTENDED — it runs from inside `pm_push.sh --bank` and
# `pm_merge.sh --bank`, regenerates the derived files, and writes a commit into
# the tree the verdict is about to vouch for. Its four clauses (a dirty tree, a
# write outside the typed list, a raised ceiling, a pipe or an unknown flag) are
# the whole of what makes that safe, and every one of them was proven once, by
# hand, on the day it was written.
#
# IT BUILDS ITS OWN REPOSITORIES and its own stub toolchain: no docker, no
# database, no `uv`, no Node, no network — so like `test_pm_merge.sh` it can
# never degrade to could-not-look on a bare machine.
#
# THIS BLOCK IS THE REGISTRATION `docs/product/instruments.md` CITES, and it
# cites the sentinel above rather than a line number. That is not style: the
# sibling product's own handoff cited its equivalent site at `:2782-2816` and
# the real site was at `:3216-3240` — ~410 lines stale within a day of being
# written.
set +e
./scripts/tests/test_pm_fold.sh
FOLD_DRIVE_RC=$?
set -e
if [ "$FOLD_DRIVE_RC" = "2" ]; then
    echo "!! the pm_fold refusal drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$FOLD_DRIVE_RC" != "0" ]; then
    echo "!! a scripts/pm_fold.sh refusal did not fire, or a property did not hold." >&2
    echo "   That script commits derived files UNATTENDED from inside pm_push --bank and" >&2
    echo "   pm_merge --bank. A fold whose teeth have stopped biting commits whatever a" >&2
    echo "   generator wrote, into the tree the verdict is about to vouch for." >&2
    exit "$FOLD_DRIVE_RC"
fi
# <<< drive: pm_fold <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin rung_tidy; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: rung_tidy >>>
# THE TIDY'S DRIVE, and it is the fold's sibling one door over: `pm_fold.sh`
# commits unattended, and `scripts/rung_tidy.sh` WRITES INTO A BUILDER'S
# WORKING TREE — a budget ceiling, a regenerated client, a re-scanned secret
# baseline — on the strength of an offer a red leg printed. The three most
# dangerous things it could do are all silent: apply a number no refusal named,
# grow a SECOND `detect-secrets scan --baseline` writer, or go quiet when the
# engine's sentence moves and report nothing-to-do over a tree that is
# refusing. Each of the three has a case, and each case asserts both the exit
# status a caller branches on and the sentence a human acts on.
#
# IT BUILDS ITS OWN CHECKOUTS and its own stub toolchain: no docker, no
# database, no Node, no network, and nothing in this tree is tidied. The
# house-rules offer is driven by extracting that leg's body from this file
# between its own sentinels and sourcing it with a shimmed engine, because a
# drive cannot run a nested `./scripts/check.sh` at all — the per-checkout gate
# lock refuses one, and the drive would then be red for the lock rather than
# for the property.
#
# THIS BLOCK IS THE REGISTRATION `docs/product/instruments.md` CITES, and it
# cites the sentinel above rather than a line number, for the reason the fold's
# block states.
set +e
./scripts/tests/test_rung_tidy.sh
TIDY_DRIVE_RC=$?
set -e
if [ "$TIDY_DRIVE_RC" = "2" ]; then
    echo "!! the rung_tidy drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$TIDY_DRIVE_RC" != "0" ]; then
    echo "!! scripts/rung_tidy.sh no longer applies what a refusal named, or no longer" >&2
    echo "   says what it applied. It writes a ceiling, a client or a baseline into a" >&2
    echo "   working checkout from an offer printed by a red leg; a tidy that writes a" >&2
    echo "   number no sentence named raises a ceiling with no reviewer in the loop." >&2
    exit "$TIDY_DRIVE_RC"
fi
# <<< drive: rung_tidy <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin pm_push; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: pm_push >>>
# THE BANK ITSELF, AND THE ONE THAT COMPOSES A CLAIM OUT OF MACHINES NOBODY
# CAN SEE AFTERWARDS. `scripts/pm_push.sh --bank --on-boxes N` earns the full
# verdict row by splitting the gate's own units across N verifier boxes and
# adding the answers up here. Every way that arithmetic can be wrong is silent
# by construction — a shard that measured a different tree, a shard whose leg
# set is short, a shard nobody could read, a box reclaimed mid-flight — and
# each of them would produce a GREEN ROW over bytes no box ran, which is
# exactly the thing `scripts/githooks/pre-push` honours without measuring.
#
# IT BUILDS ITS OWN REPOSITORIES AND ITS OWN WORLD: a throwaway git repository
# per case under `mktemp -d` with a copy of `pm_push.sh`, a stub `check.sh`, a
# stub `pm_fold.sh` and a stub `scripts/verifier_box.sh` that records every
# argv and answers from per-case fixtures. Not one AWS call, not one box, not
# one real gate — and no docker, no database, no network, so like its two
# siblings above it can never degrade to could-not-look on a bare machine.
set +e
./scripts/tests/test_pm_push.sh
PM_PUSH_DRIVE_RC=$?
set -e
if [ "$PM_PUSH_DRIVE_RC" = "2" ]; then
    echo "!! the pm_push bank drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$PM_PUSH_DRIVE_RC" != "0" ]; then
    echo "!! a refusal in the on-box bank did not fire, or its composition stopped" >&2
    echo "   adding up. That composition is the only thing standing between a verdict" >&2
    echo "   row the push hook honours in seconds and a green over bytes no box ran." >&2
    exit "$PM_PUSH_DRIVE_RC"
fi
# <<< drive: pm_push <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE FOURTH DRIVE, same leg, and the closest of the four to a canary.
# `scripts/secrets_scan.sh` decides WHICH FILES the per-rung secret scan
# reads, and it is the one guard in this gate whose failure mode is silence: a
# merge-base that stopped resolving, a diff that started coming back empty, a
# `git ls-files` accidentally reintroduced — every one of them leaves a green,
# fast leg that vouches for nothing, and nothing downstream can tell. So each
# rule of the derivation is driven in BOTH directions (what must be in the set
# and what must not), the leg's own honesty banners are asserted as text, and
# one case plants a real private-key header in a real changed file in THIS tree
# and requires the real leg to redden — the house-rules self-test's method, for
# the house-rules self-test's reason.
#
# It builds throwaway repositories (branches, merge-bases, deletions, renames,
# and a real linked worktree) for everything except that plant. No docker, no
# database; ~10s, nearly all of it git and three `uv run` starts.
if selftest_member_begin secrets_scan; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_secrets_scan.sh
SECRETS_DRIVE_RC=$?
set -e
if [ "$SECRETS_DRIVE_RC" = "2" ]; then
    echo "!! the secret-scan derivation drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SECRETS_DRIVE_RC" != "0" ]; then
    echo "!! the per-rung secret scan no longer derives — or no longer declares — the" >&2
    echo "   set of files it reads. The narrowing here is only defensible while both" >&2
    echo "   hold: an empty set from a broken merge-base reads exactly like a clean rung." >&2
    exit "$SECRETS_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin secrets_baseline_guard; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: secrets_baseline_guard >>>
# `.secrets.baseline` has one legal writer — pm_fold.sh's full-tree re-scan —
# and the command it uses, `detect-secrets scan --baseline`, DROPS the result
# line of every file it is not handed the moment a path is appended: exit 0,
# nothing printed. The per-rung leg one file over runs a partial set on every
# gate and is safe only because it runs `detect-secrets-hook --baseline`, which
# preserves what it did not scan. This drive pins both sides of that
# single-argument difference on the installed version, which it prints.
set +e
./scripts/tests/test_secrets_baseline_guard.sh
BASELINE_GUARD_RC=$?
set -e
if [ "$BASELINE_GUARD_RC" = "2" ]; then
    echo "!! the baseline-rewrite guard COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$BASELINE_GUARD_RC" != "0" ]; then
    echo "!! who may write .secrets.baseline, or what a partial scan does to it, has" >&2
    echo "   changed. A baseline that silently narrows is a scanner that stopped" >&2
    echo "   looking, and no leg anywhere goes red for it." >&2
    exit "$BASELINE_GUARD_RC"
fi
# <<< drive: secrets_baseline_guard <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin setup_env; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: setup_env >>>
# THE ENVIRONMENT STEP'S DRIVE. NO ORDINAL, for the reason the fold's block
# above states: a count in prose goes stale without the prose changing.
#
# WHY IT BINDS HERE. `scripts/setup.sh` is the ONE legal writer of a checkout's
# `.env`, and its environment step now REGENERATES that file from
# `.env.example` rather than leaving it alone — carrying every differing value
# over in place, keeping every key the example lacks under one marker, and
# writing the previous file to `.env.previous` first. That regeneration is what
# puts a builder's env-file digest back in agreement with the clone a verifier
# builds (`gate_ledger.sh`'s env-file component). Without it every consult
# misses on `env:env-file` and re-measures the whole suite instead of reusing a
# green verdict — 293s where a hit costs 1s, measured on this box.
# Its failure modes are silent and expensive in both directions — a value
# dropped is a setting or a credential gone, a value PRINTED is a credential on
# a log, a second run that appends again is a file that grows forever — so each
# is driven, and the block that reports the work is grepped for an `=`.
#
# IT BUILDS ITS OWN FIXTURES: the function is extracted by its sentinels into a
# scratch directory under `mktemp -d` and sourced there, so nothing in this
# checkout's `.env` is read, written or backed up by the drive. No docker, no
# database, no network — like its two siblings above it can never degrade to
# could-not-look on a bare machine, except honestly: no sentinels in
# `setup.sh`, or no `scripts/check.sh` to read the wiring from.
#
# THIS BLOCK IS THE REGISTRATION `docs/product/instruments.md` CITES, and it
# cites the sentinel above rather than a line number — the fold's block states
# the ~410-line reason.
set +e
./scripts/tests/test_setup_env.sh
SETUP_ENV_DRIVE_RC=$?
set -e
if [ "$SETUP_ENV_DRIVE_RC" = "2" ]; then
    echo "!! the env-sync drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SETUP_ENV_DRIVE_RC" != "0" ]; then
    echo "!! scripts/setup.sh's environment step no longer regenerates .env from" >&2
    echo "   .env.example the way a verifier's clone builds its own — or it does, and has" >&2
    echo "   started losing a value, dropping a key, printing one, or rewriting the file" >&2
    echo "   on a second run. The first puts every builder's consult back to re-measuring" >&2
    echo "   the whole suite; the others cost a credential, a setting or an afternoon." >&2
    exit "$SETUP_ENV_DRIVE_RC"
fi
# <<< drive: setup_env <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE CROSS-APP CENSUS OVER THE SHELL POPULATION, and it is registered here for
# the reason every drive is: a drive under `scripts/tests/` that no moment
# invokes is a promise rather than a leg
# (`test_drive_preamble.sh::case_every_drive_under_tests_is_invoked_by_the_gate`).
#
# IT ALSO RUNS IN EVERY `--loop`, AND THAT IS NOT A DUPLICATE. It carries the
# cross-app marker, so the `--loop` always-on leg runs it at every scope — the
# whole point of the marker. This registration is the FULL gate's copy, and a
# member both legs reach is a member banked once and reused by the other: the
# two consult one drive ledger with one key function, so the second of them
# costs a ledger read. A moved leg is not a removed leg, and the push must go
# on measuring what it measured before.
#
# No docker, no database, no `uv`, no Node, no network — one grep over
# `scripts/*.sh` and a scratch copy of it — which is what lets it be always-on
# at all.
if selftest_member_begin scripts_census; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: scripts_census >>>
set +e
./scripts/tests/test_scripts_census.sh
SCRIPTS_CENSUS_DRIVE_RC=$?
set -e
if [ "$SCRIPTS_CENSUS_DRIVE_RC" = "2" ]; then
    echo "!! the scripts-census drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SCRIPTS_CENSUS_DRIVE_RC" != "0" ]; then
    echo "!! a script under scripts/ depends on a local \`main\` that nobody has" >&2
    echo "   decided about — or the census that would have said so has narrowed back." >&2
    echo "   Both failures are silent in the ordinary course: the caller works on" >&2
    echo "   every machine that has the ref." >&2
    exit "$SCRIPTS_CENSUS_DRIVE_RC"
fi
# <<< drive: scripts_census <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE NEXT DRIVE, same leg, same argument, and the per-rung `archaeology`
# leg's own: `archaeology_loop` (scripts/archaeology_lib.sh) narrows the
# same changed-file set the secret scan just derived down to bucket SHIP and
# runs the six archaeology-census patterns against it. Its failure mode is
# the secret scan's, twice over — a merge-base that stopped resolving reads
# as a clean rung either way — PLUS one of its own: a bucket classifier that
# widened or narrowed silently either lets the platform's construction
# history through, or reddens the per-rung gate on every ordinary PM ledger
# commit. `test_archaeology_loop.sh`'s negative case (a changed SKELETON file
# full of finding ids and rung tokens) is the one that matters most.
#
# It builds throwaway repositories, `test_secrets_scan.sh`'s trick, in the
# unborn-HEAD shape only — the question under test is the six patterns and
# the bucket filter, not the changed-file derivation's own edge cases. No
# docker, no database; well under a second, nearly all of it git process
# starts.
if selftest_member_begin archaeology_loop; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_archaeology_loop.sh
ARCH_DRIVE_RC=$?
set -e
if [ "$ARCH_DRIVE_RC" = "2" ]; then
    echo "!! the archaeology-loop drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$ARCH_DRIVE_RC" != "0" ]; then
    echo "!! the per-rung archaeology leg no longer scans what it claims, or its bucket" >&2
    echo "   classifier no longer excludes SKELETON files — either lets the platform's" >&2
    echo "   own construction history back into a shipped file, silently." >&2
    exit "$ARCH_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE NEXT DRIVE, same leg: the fe leg's 9-case tri-state harness
# (scripts/fe_gate.sh). This template ships with no frontend/ at all, so the
# live tree can only ever exercise the `absent` branch — a mechanism nothing
# has proven can take its other two states is exactly the shape a canary-less
# rule already refuses one door over, and this drive is that proof, entirely
# through synthetic fixture directories (`FE_FRONTEND_DIR`, `FE_PNPM`
# overridable). It needs a real pnpm — the frozen-lockfile cases drive pnpm's
# own refusal, not a shim of it — and its absence here is a could-not-look,
# not a skip: this drive is proving the LEG, which is a different question
# from whether THIS checkout happens to have grown a frontend/ yet.
if selftest_member_begin fe_leg; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_fe_leg.sh
FE_DRIVE_RC=$?
set -e
if [ "$FE_DRIVE_RC" = "2" ]; then
    echo "!! the fe-leg drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$FE_DRIVE_RC" != "0" ]; then
    echo "!! the fe leg's tri-state no longer holds — one of absent/untouched/full (or" >&2
    echo "   the frozen-lockfile check inside full) stopped answering the way it claims." >&2
    exit "$FE_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE FIFTH DRIVE, same leg, same argument. `db_pin_leg` in
# `scripts/db.sh` is the `db-pin` leg above — the refusal standing between a
# stale `.env` pin and a checkout silently running two databases. It is a
# refusal that decides whether a commit lands, which is exactly the class of
# guard this leg already drives for `backup.sh` and `sweep.sh`.
#
# BOTH DIRECTIONS ARE LOAD-BEARING HERE, more than in its four siblings. A leg
# that stops REFUSING puts every checkout back to the silence that wrote to the
# owner's real database; a leg that stops PASSING a `# pinned` line is noise on
# every run of every deliberate checkout, and noise is the state the stderr
# note it replaced was already heading toward. The drive asserts silence as
# strictly as it asserts the refusal.
#
# It builds throwaway checkouts under `mktemp -d` — `db_pin_leg` reads a git
# top level and the `.env` beside it and nothing else, so a scratch repository
# with a two-line `.env` is a checkout as far as it is concerned. No docker, no
# database, no `uv` — so like `test_pm_merge.sh` it can never degrade to
# could-not-look on a bare machine. ~5s, nearly all of it `git init` and
# `git commit` process starts, one pair per case.
if selftest_member_begin db_pin; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_db_pin.sh
DB_PIN_DRIVE_RC=$?
set -e
if [ "$DB_PIN_DRIVE_RC" = "2" ]; then
    echo "!! the db-pin drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$DB_PIN_DRIVE_RC" != "0" ]; then
    echo "!! the db-pin leg no longer refuses a stale DATABASE_NAME pin — or no longer" >&2
    echo "   passes a deliberate one. The first puts a checkout back to running two" >&2
    echo "   databases in silence; the second makes the leg noise, which is what the" >&2
    echo "   stderr note it replaced had already become." >&2
    exit "$DB_PIN_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE SIXTH DRIVE, same leg, same argument, and the newest reason for it:
# `--loop` no longer runs the whole suite: it runs the derived FAST TIER
# plus the active rung's own app, and the organ-reaching tests wait for this gate. A
# narrowing is exactly as defensible as its derivation, and EVERY failure mode
# of this one is silent — a private pytest attribute renamed so no fixture
# closure resolves, an `@organ(...)` lost in a merge, a module read that started
# failing, the own-app mapping stopping at the wrong path component. Each leaves
# a green `--loop` that vouched for less than it said, and nothing downstream can
# tell. That is `test_secrets_scan.sh`'s class exactly, one leg over.
#
# THE CENSUS TOOTH IS A PLANT. It writes a real test file into THIS tree that
# requests a real organ fixture, and requires the real derivation to put it in
# the slow tier WITH NO LIST EDIT ANYWHERE — then removes it and requires it to
# leave. That is the property a hand-marked list would fail, and it is the one
# the whole design rests on.
#
# It collects; it never runs a deselected test. No docker and no database — the
# derivation is a fixture-closure walk and a source read — but it does need
# `uv`, because the derivation lives inside pytest. ~25s, nearly all of it
# collection and `uv` starts.
if selftest_member_begin loop_tier; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_loop_tier.sh
TIER_DRIVE_RC=$?
set -e
if [ "$TIER_DRIVE_RC" = "2" ]; then
    echo "!! the --loop tier drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$TIER_DRIVE_RC" != "0" ]; then
    echo "!! the per-rung pytest tier no longer derives — or no longer declares — the" >&2
    echo "   population it skips. A tier that deselects nothing is a slow loop nobody" >&2
    echo "   diagnoses; a tier that deselects an organ it stopped seeing is a green" >&2
    echo "   loop that vouched for less than it said." >&2
    exit "$TIER_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE TWO DRIVES BESIDE IT, and they are beside it because they drive the two
# halves the tier grew: WHICH TESTS `--loop` runs (the scope) and WHETHER IT
# RUNS THEM AT ALL (the verdict it may reuse instead). Both failure modes are
# the same shape as the tier's and worse: a scope that quietly deselected too
# much and a cache that quietly hit are each a GREEN RUN THAT MEASURED NOTHING,
# and both look exactly like speed.
#
# The scope drive collects the real suite several times and runs one real `-n 2`
# invocation — the leg's own parallel shape, because a serial approximation of a
# parallel leg is green either way — plus a throwaway clone carrying a planted
# undeclared cross-app coupling for the miss triple. No database: not one
# planted test touches one.
#
# WHAT DOMINATES ITS COST, and no number, because a number here goes stale
# without this file changing: whole-suite `--collect-only` runs over the real
# tree, and the one real xdist invocation. Where two cases ask one question of
# one unchanged tree the collection is taken once and shared —
# `collect_scope_memo` in the drive's own file names every such group, and its
# header is where the argument for sharing by NAME rather than by argument list
# lives.
if selftest_member_begin loop_scope; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_loop_scope.sh
SCOPE_DRIVE_RC=$?
set -e
if [ "$SCOPE_DRIVE_RC" = "2" ]; then
    echo "!! the --loop scope drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SCOPE_DRIVE_RC" != "0" ]; then
    echo "!! the --loop SCOPE is not behaving as declared. A scope is a claim that" >&2
    echo "   everything it deselected could not have been broken by the active rung," >&2
    echo "   and every way that claim goes wrong is silent and looks like speed." >&2
    exit "$SCOPE_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin fast_censuses; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: fast_censuses >>>
# THE FOUR `--fast` CENSUS BODIES, driven. They are the cheapest legs in the
# gate and they sit in the tier the pre-commit hook runs, which is exactly the
# combination that lets one of them go quietly blind: a census nobody drives
# costs nothing to pass and answers a closed question about a population it may
# have stopped deriving. Two of the four also share ONE implementation with
# `scripts/publish.sh`'s release-time scan, so this drive keeps the original
# bodies verbatim as a reference implementation and diffs the two transcripts
# over one scratch artifact — the extraction is the operation that silently
# moves an output, and publish's printed lines are a contract another drive
# greps.
#
# Every case plants its own victim in a scratch directory or in a scratch COPY
# of a real file, never a real file moved aside and restored, and none of them
# shells out to this gate: the per-checkout lock would refuse a nested run, so a
# case that reached for the gate would redden for the lock instead of for the
# property. Each case calls the leg BODY out of `scripts/docs_legs.sh`.
#
# No docker, no database, no network, no `uv` — git and the shell — so it
# degrades to could-not-look only honestly. Seconds.
set +e
./scripts/tests/test_fast_censuses.sh
FAST_CENSUS_DRIVE_RC=$?
set -e
if [ "$FAST_CENSUS_DRIVE_RC" = "2" ]; then
    echo "!! the fast-censuses drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$FAST_CENSUS_DRIVE_RC" != "0" ]; then
    echo "!! one of the four --fast census bodies no longer reds on a planted absence," >&2
    echo "   or the extraction moved publish.sh's printed transcript. Both failures are" >&2
    echo "   silent at every other leg: a census that stopped seeing its population" >&2
    echo "   passes, and a release-time count that drifted is read by nobody until the" >&2
    echo "   release." >&2
    exit "$FAST_CENSUS_DRIVE_RC"
fi
# <<< drive: fast_censuses <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# The ledger drive touches no database and no network: it forges rows into a
# scratch file through DJB_LOOP_LEDGER, so nothing it writes can ever become a
# banked verdict in this checkout. Seconds.
if selftest_member_begin loop_ledger; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_loop_ledger.sh
LOOP_LEDGER_DRIVE_RC=$?
set -e
if [ "$LOOP_LEDGER_DRIVE_RC" = "2" ]; then
    echo "!! the --loop ledger drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$LOOP_LEDGER_DRIVE_RC" != "0" ]; then
    echo "!! the --loop LEDGER stopped failing closed. A verdict cache that hits when" >&2
    echo "   it should have missed costs a rung its whole gate, silently." >&2
    exit "$LOOP_LEDGER_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE SEVENTH AND EIGHTH DRIVES, and they are here because a deferral outlived
# its reason. Both were written in the same wave — `test_rung_start.sh` for
# `rung_start.sh`'s own instrument, `test_db_template.sh` for the database
# template — and both rows in `instruments.md` said the same thing: not wired
# yet, because `scripts/check.sh` was another rung's territory that week, so run
# it by hand. That other rung then wired one drive, its own. The reason expired
# at that merge and the sentence did not, which is how two instruments end up
# passing 42/42 and 31/31 in a report nobody re-runs. BY HAND IS A PROMISE; A
# LEG IS A MEASUREMENT.
#
# `test_rung_start.sh` builds throwaway repositories and drives the instrument's
# refusals — a dirty tree, a detached HEAD, a branch ahead of main, a missing
# local main — plus the pool diagnosis. No docker and no database.
#
# `test_db_template.sh` needs both: its live half publishes a scratch template,
# clones it concurrently, and proves the SUITE's half of it too — that
# the template name reaches `TEST["TEMPLATE"]` only when the template really
# exists. That guard is the one standing between a fresh clone and a suite that
# dies at database setup for every worker at once, because Django issues
# `CREATE DATABASE … WITH TEMPLATE …` unconditionally and has no fallback where
# `db_create` has a loud miss.
if selftest_member_begin rung_start; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_rung_start.sh
RUNG_START_DRIVE_RC=$?
set -e
if [ "$RUNG_START_DRIVE_RC" = "2" ]; then
    echo "!! the rung-start drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$RUNG_START_DRIVE_RC" != "0" ]; then
    echo "!! a rung_start.sh refusal did not fire. That instrument resets a builder's" >&2
    echo "   worktree to main, so its refusals are the only thing standing between an" >&2
    echo "   unconditional reset and somebody's uncommitted work." >&2
    exit "$RUNG_START_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin db_template; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_db_template.sh
DB_TEMPLATE_DRIVE_RC=$?
set -e
if [ "$DB_TEMPLATE_DRIVE_RC" = "2" ]; then
    echo "!! the db-template drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$DB_TEMPLATE_DRIVE_RC" != "0" ]; then
    echo "!! the template database no longer behaves as designed, or the suite no" >&2
    echo "   longer spends it safely. The guard that matters most: a template name" >&2
    echo "   reaches TEST[TEMPLATE] only when that template EXISTS — Django has no" >&2
    echo "   fallback, and an absent one kills the suite at setup for every worker." >&2
    exit "$DB_TEMPLATE_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE NINTH DRIVE. `scripts/serve.sh` stopped being
# only a process the day it started deriving its port: a fixed port taken by a
# sibling worktree is how a verifier once spent a session verifying somebody
# else's deployment, and a refusal that names the holder is the only thing that
# tells a reader which of the two servers they are looking at. Those are
# behaviours now, and a behaviour nobody drives is a behaviour that can be
# deleted by accident.
#
# It holds ports with python3 rather than starting servers, so it needs no
# docker and no database. This drive was built and wired later than
# `scripts/serve.sh` itself, deliberately held for whoever owned `check.sh`
# rather than editing a shared file in parallel.
if selftest_member_begin serve_port; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_serve_port.sh
SERVE_PORT_DRIVE_RC=$?
set -e
if [ "$SERVE_PORT_DRIVE_RC" = "2" ]; then
    echo "!! the serve-port drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SERVE_PORT_DRIVE_RC" != "0" ]; then
    echo "!! scripts/serve.sh no longer derives its port, or no longer names the holder" >&2
    echo "   of a port it could not take. Both are silent failures by construction: the" >&2
    echo "   first puts two checkouts back on one port, and the second sends a verifier" >&2
    echo "   to drive a sibling worktree's deployment believing it is their own." >&2
    exit "$SERVE_PORT_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE TENTH DRIVE, and the first that drives a DOCUMENT. The
# runbook's webhook recipes had the same defect class found in them three times
# — one rung put them in the runbook at all, then the section's own `message_id`
# trap, then the click half's `click_url` key — and each was fixed by editing
# carefully. A recipe nobody runs is prose that looks like code, and an earlier
# link census had already proved that censusing a document's EXISTENCE claims
# is not the same as proving its BEHAVIOUR.
#
# It lifts each fenced block out of `docs/runbooks/deploy.md` at run time (by an
# HTML-comment marker) and runs it as printed against a live receiver on its own
# scratch database, substituting only the placeholders the recipe names. Nothing
# in this tree is a copy of a recipe, and the drive has a case asserting that of
# itself — so a recipe edit that breaks the drive fails WITHOUT anybody syncing
# a copy, which is the whole point.
#
# It needs a database (a `test_djb_*` scratch one it creates and drops) and `uv`.
# ~30s, nearly all of it the migration chain into the fresh database.
if selftest_member_begin runbook_recipes; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_runbook_recipes.sh
RUNBOOK_DRIVE_RC=$?
set -e
if [ "$RUNBOOK_DRIVE_RC" = "2" ]; then
    echo "!! the runbook-recipe drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$RUNBOOK_DRIVE_RC" != "0" ]; then
    echo "!! a recipe printed in docs/runbooks/deploy.md no longer does what it says." >&2
    echo "   These are the instructions an operator follows when a provider will not" >&2
    echo "   resend a bounce and the only alternative is reading a test suite. The" >&2
    echo "   class has recurred three times; the third careful edit was not the fix." >&2
    exit "$RUNBOOK_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE ELEVENTH DRIVE, same leg, same argument. The
# machine-wide full-gate lease above is the newest guard in this file and every
# one of its failure modes is silent: a wait that stops announcing itself is a
# hang as far as any reader can tell; a stale-clear that stops firing turns the
# FIRST killed gate into a permanent machine-wide block (and the tool's
# ten-minute ceiling kills full runs routinely); a stale-clear that fires too
# eagerly puts two full gates back on one box with nobody told; a lease
# accidentally taken by `--fast`/`--loop` makes every builder queue behind
# somebody else's push. Each of those leaves a green gate.
#
# IT NEVER TOUCHES THE REAL LEASE — every case points `DJB_GATE_LEASE_DIR` at
# its own scratch directory, which is what makes it safe to run from inside the
# gate that is holding the real one. It drives the real file (sourced, never
# copied), it starts and reaps its own sleepers for the live/dead holder cases,
# and it reads `check.sh` as TEXT for the wiring — the weaker proof
# `test_db_pin.sh` and `test_loop_tier.sh` both declare, for the same reason.
#
# No docker, no database, no `uv`. ~10s, most of it the two deliberate waits.
if selftest_member_begin gate_lease; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_gate_lease.sh
LEASE_DRIVE_RC=$?
set -e
if [ "$LEASE_DRIVE_RC" = "2" ]; then
    echo "!! the full-gate lease drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$LEASE_DRIVE_RC" != "0" ]; then
    echo "!! the machine-wide full-gate lease no longer behaves as designed." >&2
    echo "   Two full gates on one box contend for every core: the measurement that" >&2
    echo "   opened that row is 607s and two RED tests contended against 99s green" >&2
    echo "   quiet, on the same tree. A lease that stops waiting puts that back; a" >&2
    echo "   lease that stops CLEARING blocks every full gate on this machine until" >&2
    echo "   somebody is told to delete a file." >&2
    exit "$LEASE_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE TWELFTH, THIRTEENTH AND FOURTEENTH DRIVES, and all three are here for one
# reason that has now been paid for four times in this file: a deferral outlived
# its reason.
#
# Each of these was written in a cycle where `scripts/check.sh` belonged to
# somebody else, so each author did the correct thing — they flagged the wiring
# as owed in their report and in their `instruments.md` row instead of editing a
# file another rung was building in. That is the discipline working. What it
# leaves behind is a drive that passes 78/28/17 in a report nobody re-runs, and
# the note above the seventh and eighth drives is the same sentence twice over:
# BY HAND IS A PROMISE; A LEG IS A MEASUREMENT. The reason expired at those
# merges; this is the file where it stops being owed.
#
# `test_verify_start.sh` drives the verifier-start instrument's three guards —
# the dirty-source refusal, the verdict-key refusal that names a stray untracked
# file (the mechanism that once cost this repository a push made by hand), and
# the rule that the database name is ASKED FOR rather than copied. It builds
# scratch repositories and plants nothing here. No docker, no database; ~14s.
if selftest_member_begin verify_start; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_verify_start.sh
VERIFY_START_DRIVE_RC=$?
set -e
if [ "$VERIFY_START_DRIVE_RC" = "2" ]; then
    echo "!! the verifier-start drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$VERIFY_START_DRIVE_RC" != "0" ]; then
    echo "!! scripts/verify_start.sh no longer refuses what it is there to refuse." >&2
    echo "   Its guards are invisible when they are right: a clone made over somebody's" >&2
    echo "   uncommitted work, or a stray untracked file that shifts the gate's verdict" >&2
    echo "   key so that an eight-minute green run banks nothing at all." >&2
    exit "$VERIFY_START_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# `test_db_zsh.sh` drives `scripts/db.sh` under the shell it is actually sourced
# by. That library is the one file here that is SOURCED rather than run, so its
# shebang is inert and the interpreter is the caller's — which on this platform
# is routinely zsh, where a tied parameter used as a local emptied PATH mid-call
# and `db_create` printed `created database` over a database it had not made.
# It SKIPS rather than passes when it cannot find the shell, and says so. Needs
# zsh and the compose Postgres for the live tooth; ~4s.
if selftest_member_begin db_zsh; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_db_zsh.sh
DB_ZSH_DRIVE_RC=$?
set -e
if [ "$DB_ZSH_DRIVE_RC" = "2" ]; then
    echo "!! the db.sh-under-zsh drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$DB_ZSH_DRIVE_RC" != "0" ]; then
    echo "!! scripts/db.sh no longer behaves the same way under the shell that sources" >&2
    echo "   it. A derivation that forks by shell gives one checkout two databases, and" >&2
    echo "   a create function that returns 0 over work it did not do is a green line" >&2
    echo "   about a database that is not there." >&2
    exit "$DB_ZSH_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# `test_publish.sh` drives the export instrument — the one that decides what a
# consuming product receives. Every case is a refusal or a census, and once a
# consumer has merged a release, history can never be re-cut: the per-publish
# census is the only wall left. It builds its own throwaway repository and reads
# nothing in this checkout, so its verdict does not move when this tree does.
# No docker, no database; ~12s.
if selftest_member_begin publish; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_publish.sh
PUBLISH_DRIVE_RC=$?
set -e
if [ "$PUBLISH_DRIVE_RC" = "2" ]; then
    echo "!! the publish drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$PUBLISH_DRIVE_RC" != "0" ]; then
    echo "!! a scripts/publish.sh refusal or census did not fire. That instrument decides" >&2
    echo "   what leaves this repository, and a consumer that has merged a release cannot" >&2
    echo "   be given a different history afterwards — the census at publish time is the" >&2
    echo "   only wall there is." >&2
    exit "$PUBLISH_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# `test_divergence_census.sh` drives the other half of the same partition
# `test_publish.sh` drives one door up: publish decides what a product
# RECEIVES, and the divergence census decides what a product may CHANGE in
# what it received. It exists because its subject is invisible from here —
# this repository is the template, so it has no template, and a declared base,
# a divergence and a NAMED divergence are all states this checkout by
# construction cannot be in. Every case builds its own throwaway PRODUCT under
# `mktemp -d` and reads nothing in this checkout. No docker, no database; ~3s.
if selftest_member_begin divergence_census; then
SELFTEST_BLOCK_RC=0
(
set +e
./scripts/tests/test_divergence_census.sh
DIVERGENCE_DRIVE_RC=$?
set -e
if [ "$DIVERGENCE_DRIVE_RC" = "2" ]; then
    echo "!! the divergence-census drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$DIVERGENCE_DRIVE_RC" != "0" ]; then
    echo "!! a scripts/divergence_census.sh refusal or silence did not hold. That" >&2
    echo "   instrument is what tells a product which of its edits are deliberate" >&2
    echo "   divergences and which are a merge conflict with a countdown on it, and" >&2
    echo "   its SILENT half — the drawer, the product's own apps, the shared files," >&2
    echo "   the ledgers — is the half a census gets wrong by crying wolf." >&2
    exit "$DIVERGENCE_DRIVE_RC"
fi
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin queue_index; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: queue_index >>>
# THE DERIVED LEDGER'S DRIVE, and the `--fast` leg above is only as honest as
# it is. `scripts/queue_index.py` performs a ONE-WAY, ONE-SHOT migration on the
# file every other document defers to for order: it splits the record out of the
# index, and the record is then the only copy of every row. Both of its failure
# modes are invisible afterwards — a byte lost or reordered in the split cannot
# be missed by anybody who did not already know the row was there, and a derived
# index that drifts from its record is the two-truths defect the split closed,
# re-opened. So every canary in this drive is FED A BROKEN PAIR and expected to
# fire: an index row with no anchor, an anchor with no index row, a head that is
# not the row's own text, a struck row indexed open, a duplicate anchor, a
# record that is gone. It also drives all THREE states the `--fast` leg's exit
# status comes from, each on its own tree, so the pre-split tolerance that keeps
# that leg green before the migration cannot quietly become a skip afterwards.
#
# IT BUILDS ITS OWN VICTIMS under `mktemp -d`; the one case that reads this
# checkout's real ledger COPIES it, and measures the check at real scale. No
# docker, no database, no `uv`, no Node, no network — so like `test_pm_merge.sh`
# it can never degrade to could-not-look on a bare machine. Sub-second.
#
# THIS BLOCK IS THE REGISTRATION `docs/product/instruments.md` CITES, by the
# sentinel above rather than by a line number — `pm_fold`'s block one leg up
# records what a cited line number was worth after a day.
set +e
./scripts/tests/test_queue_index.sh
QUEUE_INDEX_DRIVE_RC=$?
set -e
if [ "$QUEUE_INDEX_DRIVE_RC" = "2" ]; then
    echo "!! the queue-index drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$QUEUE_INDEX_DRIVE_RC" != "0" ]; then
    echo "!! a property of the queue's index/detail split did not hold, or a canary did" >&2
    echo "   not fire. The record is the only copy of every row and the index is the file" >&2
    echo "   everybody reads: a canary that stopped firing here is a disagreement between" >&2
    echo "   the two that nothing downstream can see." >&2
    exit "$QUEUE_INDEX_DRIVE_RC"
fi
# <<< drive: queue_index <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin test_impact; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: test_impact >>>
# THE TEST-IMPACT MAP'S WRITER. `scripts/test_impact.py` turns one acceptance
# run's per-test coverage contexts into `scripts/test_impact.json` — for every
# collected test, the source files it executed — so that the inner loop can run
# the tests a change can REACH instead of the whole dependency closure.
#
# WHY IT IS DRIVEN AND NOT MERELY RUN. A map is read by a SELECTOR, so every
# silent hole in it becomes a test nobody runs, and two holes are silent by
# construction. A test whose only read of the tree is `read_text()` executes no
# measured line: written as `[]` it reads downstream as "touches nothing" and is
# never selected again, for any change, ever — so an empty executed set is a
# DECLARED reason and never an empty list. And a nodeid the collection has and
# the coverage database does not is not a test that touched nothing but a run
# that did not measure it, so it is could-not-look with no file written. The
# census the drive holds it to is closed: every collected nodeid is in `tests`
# or in `unmapped`, never neither and never both.
#
# It builds every coverage database, collected list and output under
# `mktemp -d` through `coverage`'s own API, runs no pytest, needs no docker, no
# database and no network, and never touches this checkout's own map.
# Sub-second.
set +e
./scripts/tests/test_test_impact.sh
TEST_IMPACT_DRIVE_RC=$?
set -e
if [ "$TEST_IMPACT_DRIVE_RC" = "2" ]; then
    echo "!! the test-impact drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$TEST_IMPACT_DRIVE_RC" != "0" ]; then
    echo "!! the test-impact map's census stopped being closed. A map with a hole in" >&2
    echo "   it is not a smaller map: it is a set of tests that will never be selected" >&2
    echo "   again, and nothing downstream can tell that from a test that is genuinely" >&2
    echo "   unaffected." >&2
    exit "$TEST_IMPACT_DRIVE_RC"
fi
# <<< drive: test_impact <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin loop_metrics; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: loop_metrics >>>
# THE VELOCITY READER'S DRIVE. `scripts/loop_metrics.py` derives the
# cost-baseline row — the two velocity clocks, the inner loop by change class,
# the bank census — from the dispatch ledger's stamps, from git and from the
# gate's own logs, so that the row a cycle is judged against has inputs a
# reader can re-read instead of being typed from a screen.
#
# THAT MOVES THE FAILURE MODE RATHER THAN CLOSING IT, and the cases here are
# aimed at where it moved to. A derivation can be wrong in two ways that both
# look exactly like an answer: it can read a stamp that says something
# impossible and print a plausible minute count from it, and it can skip the
# rows that carry no stamps and report a median over the convenient half of
# the ledger. So the drive feeds it a broken clock, a stage reached with the
# stage before it missing, a second time zone, and a ledger whose rows predate
# the grammar entirely — and expects a named refusal for the first three and a
# COUNT for the last, never a silent omission.
#
# It builds every ledger, log and readouts fixture it needs under `mktemp -d`,
# and the one case that reads this checkout's real ledger COPIES it. No docker,
# no database, no `uv`, no Node, no network — so like `test_queue_index.sh` it
# can never degrade to could-not-look on a bare machine. Sub-second.
set +e
./scripts/tests/test_loop_metrics.sh
LOOP_METRICS_DRIVE_RC=$?
set -e
if [ "$LOOP_METRICS_DRIVE_RC" = "2" ]; then
    echo "!! the loop-metrics drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$LOOP_METRICS_DRIVE_RC" != "0" ]; then
    echo "!! a property of the velocity reader did not hold. Every cycle is measured" >&2
    echo "   against the row it derives, and a median taken over the stamped half of" >&2
    echo "   the ledger reads exactly like a median taken over all of it." >&2
    exit "$LOOP_METRICS_DRIVE_RC"
fi
# <<< drive: loop_metrics <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin gate_explain; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: gate_explain >>>
# THE LEGIBLE RED'S OWN DRIVE, and it shipped hand-run for one wave because
# this file belonged to a different territory the day it was written. By hand
# is a promise, not a leg: the engine's `--selftest` above carries the two
# in-process censuses, and this is the process-level proof beside them — the
# four trailer keys off a real planted red, both comment tokens, the two
# readers, `--terse`, and which modules are budget subjects at all.
#
# It needs `uv` (it runs the engine) and it plants into the REAL tree, restoring
# in a trap — which is why it belongs here and not in `--fast`: the full gate
# already owns both, and a plant that a killed run leaves behind is caught by
# this file's own stale-plant refusal.
#
# WHAT DOMINATES ITS COST, and no number, because a number here goes stale
# without this file changing: the LIVE SCANS. Each planted red is a whole
# engine scan of this tree, and they cannot be shared across plants because
# each plant is a different tree. What is shared is two cases reading one
# scan, and the readers — `--explain`, the listing under both names, an
# unknown flag — which return before anything measures and are captured in one
# process. `red_plant_once` and `readers_once` in the drive's own file are
# where those two arguments live.
set +e
./scripts/tests/test_gate_explain.sh
GATE_EXPLAIN_DRIVE_RC=$?
set -e
if [ "$GATE_EXPLAIN_DRIVE_RC" = "2" ]; then
    echo "!! the gate-explain drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$GATE_EXPLAIN_DRIVE_RC" != "0" ]; then
    echo "!! a red can no longer explain itself. The per-rule trailer, --explain, the" >&2
    echo "   listing and --terse are the difference between a builder acting on a" >&2
    echo "   finding and a builder going to look for the rule in a 7,000-line yaml." >&2
    exit "$GATE_EXPLAIN_DRIVE_RC"
fi
# <<< drive: gate_explain <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin drive_preamble; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: drive_preamble >>>
# THE TRIPWIRE THAT WATCHES EVERY OTHER DRIVE, driven itself. Every drive in
# this leg sources `scripts/tests/drive_preamble.sh`, which fingerprints this
# repository before the drive runs and compares afterwards: a drive that wrote
# into the repository it was measuring is exit 2 however green its cases were.
#
# Its two failure directions are both expensive and only one of them is loud.
# Too quiet and the escape it was written for comes back silently. Too loud and
# it convicts a drive of a PEER's ordinary work — refs are shared across every
# worktree of one repository, so a peer's `worktree add`, a peer's boundary
# commit, a merge into `main` and a reap of a merged branch all move a ref
# during this leg — and the remedy for a gate that cries wolf is people passing
# it with --no-verify. This drive builds throwaway repositories and drives both
# directions of every excuse.
#
# No docker, no database, no `uv`, no Node, no network — git alone — so it
# cannot degrade to could-not-look on a bare machine except honestly.
set +e
./scripts/tests/test_drive_preamble.sh
PREAMBLE_DRIVE_RC=$?
set -e
if [ "$PREAMBLE_DRIVE_RC" = "2" ]; then
    echo "!! the drive-preamble drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$PREAMBLE_DRIVE_RC" != "0" ]; then
    echo "!! the real-repository tripwire no longer tells a drive's escape from a" >&2
    echo "   peer's ordinary work. Every other drive in this leg stands on it, so a" >&2
    echo "   tripwire that forgives too much makes all of them vouch for less than" >&2
    echo "   they claim, and one that forgives too little reddens this gate for" >&2
    echo "   somebody else's commit." >&2
    exit "$PREAMBLE_DRIVE_RC"
fi
# <<< drive: drive_preamble <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin pipefail_readers; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: pipefail_readers >>>
# THE READER THAT LEAVES EARLY. Under `set -o pipefail` a `producer | head -1`
# reads the value it wanted correctly and then hands the caller 141 — but only
# once the producer's output passes the kernel's 64 KiB pipe buffer, so it is
# green on every input anybody drove it with and fatal on the first big one.
# Two were in this file: the pass-2 summary (the leg whose job is to explain a
# red would have died of the explanation, and only on the runs with the most to
# explain) and the counts-file comparison behind the `--loop` scope banner.
#
# The drive censuses the scripts whose exit status is a verdict, a merge, a
# release or a backup, and runs two of this file's own lines — read out of it
# rather than copied — against padded input. No docker, no database, no `uv`,
# no network.
set +e
./scripts/tests/test_pipefail_readers.sh
PIPEFAIL_DRIVE_RC=$?
set -e
if [ "$PIPEFAIL_DRIVE_RC" = "2" ]; then
    echo "!! the pipefail-reader drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$PIPEFAIL_DRIVE_RC" != "0" ]; then
    echo "!! a pipeline whose reader leaves early is back in a script whose exit" >&2
    echo "   status is a verdict, a merge, a release or a backup — or one of the two" >&2
    echo "   rewritten lines in this file no longer survives a padded producer." >&2
    exit "$PIPEFAIL_DRIVE_RC"
fi
# <<< drive: pipefail_readers <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi
if selftest_member_begin list_legs; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: list_legs >>>
# THE LIST THAT MUST NOT DRIFT. `FULL_LEGS` is the string every banked verdict
# row carries, and it had grown six names out of date — legs announced on every
# full gate and named on no row. This drive runs each mode with
# `DJB_GATE_LEGS_DRY=1` in a CLONE (the per-checkout lock refuses a nested gate,
# and the subject here is the whole-mode flow rather than any one leg body),
# compares the announced sequence against a fixture read off the pre-refactor
# tree, and plants four separate disagreements the listing must refuse.
#
# No docker, no database, no network; `git`, `python3` and this file.
#
# WHAT DOMINATES ITS COST, and no number, because a number here goes stale
# without this file changing: the shard census, which collects the real suite
# once per (N, k, seed) to prove the shards partition it. Those collections are
# read-only and run CONCURRENTLY, bounded and reaped by pid — `collect_ids_spawn`
# in the drive's own file carries that argument and the one contention it has.
set +e
./scripts/tests/test_list_legs.sh
LIST_LEGS_DRIVE_RC=$?
set -e
if [ "$LIST_LEGS_DRIVE_RC" = "2" ]; then
    echo "!! the list-legs drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$LIST_LEGS_DRIVE_RC" != "0" ]; then
    echo "!! the gate's leg sequence, its FULL_LEGS string or its unit table moved" >&2
    echo "   without the other two — or a refusal the listing owes stopped firing." >&2
    echo "   A verdict row that under-reports what ran is a green that vouched for" >&2
    echo "   less than it says." >&2
    exit "$LIST_LEGS_DRIVE_RC"
fi
# <<< drive: list_legs <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin shard_census; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: shard_census >>>
# THE ONE SHARD-CENSUS QUESTION WHOSE SUBJECT IS THE REAL TREE. The partition
# census next door moved onto a fifty-item fixture world — the shards
# partitioning the collection is a property of pytest-split composed with this
# gate's flags, and a mechanism proven over fifty items is proven — and that is
# what took `apps/` out of `test_list_legs.sh`'s `# drives:` line.
#
# What could not move with it: whether `scripts/pytest_durations.json`, the
# file the `pytest-x2` unit hands `--durations-path`, still names the suite it
# balances. A stale one cannot move the partition; it can only leave
# pytest-split chunking by count, silently, which turns the sharded unit's
# reason for existing into a coin flip. That is a property of THIS tree's
# collection, so this drive declares `apps/` and costs one `--collect-only`.
#
# No docker, no database, no network; `uv`, the suite's collection and this
# file.
set +e
./scripts/tests/test_shard_census.sh
SHARD_CENSUS_DRIVE_RC=$?
set -e
if [ "$SHARD_CENSUS_DRIVE_RC" = "2" ]; then
    echo "!! the shard-census drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SHARD_CENSUS_DRIVE_RC" != "0" ]; then
    echo "!! the durations file the sharded pytest unit balances by is no longer" >&2
    echo "   about this suite. The shards still partition it; they are just no" >&2
    echo "   longer a share of the wall clock." >&2
    exit "$SHARD_CENSUS_DRIVE_RC"
fi
# <<< drive: shard_census <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin verifier_image; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: verifier_image >>>
# THE MONEY GUARD AND THE CREDENTIAL GUARD FOR THE VERIFIER BOXES. The image's
# idle reaper is the only thing that takes a throwaway EC2 box down when the
# session that started it is gone, and it has to pull both ways at once: a
# reaper that stops reaping is a bill with no ceiling, and a reaper that fires
# during a gate is a verdict nobody has. Beside it, the owner's IAM bootstrap
# mints a credential — a bootstrap that opens an ingress rule, mints a key per
# run, or bakes one deployment's name into an account two products share is an
# incident rather than a bug.
#
# IT IS ALL SHIMS AND CREATES NOTHING. `aws`, `who`, `pgrep`, `date`,
# `shutdown` and `logger` are planted on PATH per case and record their argv;
# no AWS resource is created, described or terminated, and no real machine is
# touched. What that buys is the arguments and the refusals; what it cannot
# buy is declared in the drive's own header and is the field test's.
#
# It is under `scripts/tests/` rather than `deploy/tests/` deliberately: the
# deploy-layer drives are a declared blind spot this leg prints and does not
# run, and these guards may not live there.
#
# No docker, no database, no `uv`, no network; `python3`, `bash` and the files
# under deploy/verifier and deploy/iam.
set +e
./scripts/tests/test_verifier_image.sh
VERIFIER_IMAGE_DRIVE_RC=$?
set -e
if [ "$VERIFIER_IMAGE_DRIVE_RC" = "2" ]; then
    echo "!! the verifier-image drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$VERIFIER_IMAGE_DRIVE_RC" != "0" ]; then
    echo "!! a verifier box's reaper, its launch seam, its least-privilege policy or the" >&2
    echo "   owner's bootstrap no longer behaves as designed. Every one of those failures" >&2
    echo "   is silent in production: a box that never reaps bills until somebody" >&2
    echo "   notices, a box reaped mid-gate loses a verdict, and a credential that can" >&2
    echo "   reach an untagged instance can reach an environment box." >&2
    exit "$VERIFIER_IMAGE_DRIVE_RC"
fi
# <<< drive: verifier_image <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin verifier_box; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: verifier_box >>>
# THE WRAPPER THAT SPENDS THE MONEY. `scripts/verifier_box.sh` launches EC2
# instances, terminates them, and pushes this tree onto a machine a verification
# then runs on. Every one of its failure modes is silent in the direction that
# costs: a refusal that launches first and refuses second, a box ceiling that
# becomes on-demand money instead of a refusal, a `down` that reaches an
# instance nobody tagged as ours or another deployment's box in the same
# account, a `loop` that pipes the gate and hands the ledger a lie, a `bake`
# that leaves its builder running. None of those red anything by themselves.
#
# IT CREATES NOTHING. `aws`, `ssh`, `scp`, `git`, `session-manager-plugin` and
# `sleep` are planted on PATH per case and every invocation is recorded twice —
# as an operation for counting and as a whole command line for reading. No AWS
# call leaves this machine and no box exists. What that buys is the arguments
# and the refusals; the rest is the field test's and is declared in the drive's
# own header.
#
# No docker, no database, no `uv`, no network; `python3`, `ssh-keygen` (the real
# one — the key's mode is asserted) and the files under deploy/verifier.
set +e
./scripts/tests/test_verifier_box.sh
VERIFIER_BOX_DRIVE_RC=$?
set -e
if [ "$VERIFIER_BOX_DRIVE_RC" = "2" ]; then
    echo "!! the verifier-box drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$VERIFIER_BOX_DRIVE_RC" != "0" ]; then
    echo "!! the verifier-box wrapper no longer refuses what it is there to refuse, or no" >&2
    echo "   longer launches what it says it launches. It spends money and terminates" >&2
    echo "   machines: a wall that stopped firing is a bill nobody is watching, and a" >&2
    echo "   tag check that stopped firing reaches another deployment's box." >&2
    exit "$VERIFIER_BOX_DRIVE_RC"
fi
# <<< drive: verifier_box <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin local_legs; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: local_legs >>>
# THE PRODUCT'S OWN LEGS. A product that clones this template grows legs of its
# own, and before `scripts/local/legs/` the only place to put one was inside
# this file — which the first consumer's v2.1.0 fold priced at 21 conflicts in
# `scripts/ quality/ .github/` and 1826 of their lines vanishing into a silent
# fast-forward. This drive holds the replacement to its promise from both ends:
# a declared leg is discovered, announced after `full-house-rules`, named
# `local:<name>` on the verdict row, run by the tier and the touches it
# declares, and REFUSED at the listing when its header is wrong; and a tree
# with no drawer prints a byte-identical listing, which is asserted with `cmp`
# and not with a paragraph.
#
# It plants into scratch directories and into one `git clone` of this checkout,
# never into the checkout itself. No docker, no database, no network; git,
# bash, jq and one dry gate.
set +e
./scripts/tests/test_local_legs.sh
LOCAL_LEGS_DRIVE_RC=$?
set -e
if [ "$LOCAL_LEGS_DRIVE_RC" = "2" ]; then
    echo "!! the local-legs drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$LOCAL_LEGS_DRIVE_RC" != "0" ]; then
    echo "!! the product-leg drawer no longer does what a product is told it does." >&2
    echo "   Both directions are silent from inside a green gate here, because this" >&2
    echo "   template ships no drawer: a leg silently skipped is a product believing" >&2
    echo "   its gate ran something it did not, and a drawer that is no longer free" >&2
    echo "   when absent is a cost this repository would never feel." >&2
    exit "$LOCAL_LEGS_DRIVE_RC"
fi
# <<< drive: local_legs <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

# THE SHAPES DRIVE'S MODE IS DECIDED HERE, BEFORE THE CONSULT, because the
# consult is what it changes. Under `--leg selftest --shard k/N` the drive runs
# the WHOLE self-test in the consumer's world, and that run is never replaced by
# a banked green: the drive key reads the drive's own bytes and its `# drives:`
# blobs, not the tree and not the mode, and drive rows travel — every
# `--on-boxes` bank harvests them home and the next boxes are sent them — so a
# green banked at one bank would otherwise stand in for the next bank's whole
# run over any change in `apps/`, `config/` or `scripts/`. The member is still
# keyed, so its green still banks; `selftest_drive_consult` prints that it was
# not consulted.
SELFTEST_SHAPES_WHOLE_RUN=""
if [ -n "${GATE_SHARD_K:-}" ] && [ "${GATE_LEG_UNIT:-}" = "selftest" ]; then
    SELFTEST_SHAPES_WHOLE_RUN="the selftest unit is sharded (--leg selftest --shard ${GATE_SHARD_K}/${GATE_SHARD_N:-?})"
    SELFTEST_CONSULT_SKIP=selftest_shapes
    SELFTEST_CONSULT_SKIP_WHY="whole mode (${SELFTEST_SHAPES_WHOLE_RUN}): a banked green is keyed on neither the tree nor the mode, so it is never reused for a whole run"
fi
if selftest_member_begin selftest_shapes; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: selftest_shapes >>>
# THE ENGINE'S SELF-TEST ON A CONSUMER'S SHAPE. The engine block at the top of
# this leg plants every form into THIS tree, which is the template's own — a
# world too small to falsify "this canary is live on a product", and twice a
# consumer found the next layer at their own bank. This drive clones this
# checkout at HEAD, declares the base the way the consumer does (a `template`
# remote carrying v<TEMPLATE_VERSION>, then scripts/local/template-base on top),
# adds a real frontend/src/app/page.tsx, and runs the NARROWED self-test for
# rules 51 and 60 in each world. It judges HEAD, not the working tree — said in
# its own header.
#
# EVERY RULE, BUT ONLY UNDER A SHARD. When this leg runs as `--leg selftest
# --shard k/N` — the bank's form, one unit spread over boxes — the drive runs
# the engine's WHOLE self-test in the consumer's world and asserts every rule's
# line. That run costs about what the engine's own member does, so it happens
# only where a shard spreads the unit over boxes. The member keeps its name, and
# the `selftest_shapes` row the LPT split reads holds the NARROWED wall only: no
# sharded run can write the durations file (`gate_member_record` returns under
# any `--leg`, and `--store-durations` refuses a shard), so the whole run's cost
# is not what the partition balances on. A `--loop`, an unsharded full gate and
# a Mac never take it; the drive prints which mode it ran and why on its
# `mode:` line. The mode is decided above, before the consult, and a whole run
# is never a reused green.
#
# It plants into one `git clone` under `mktemp -d`, never into the checkout
# itself. The narrowed run needs no docker, no database and no network beyond
# `uv`'s own cache; the WHOLE run opens this checkout's database and stack,
# through a copy of this checkout's `.env`, exactly as the engine's own member
# does.
if [ -n "$SELFTEST_SHAPES_WHOLE_RUN" ]; then
    export DJB_SELFTEST_SHAPES_WHOLE_RUN="$SELFTEST_SHAPES_WHOLE_RUN"
fi
set +e
./scripts/tests/test_selftest_shapes.sh
SELFTEST_SHAPES_DRIVE_RC=$?
set -e
if [ "$SELFTEST_SHAPES_DRIVE_RC" = "2" ]; then
    echo "!! the selftest-shapes drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SELFTEST_SHAPES_DRIVE_RC" != "0" ]; then
    echo "!! the engine's self-test does not hold on a consumer-shaped tree: a form" >&2
    echo "   collides with a file a product has, or a control fires on a declared" >&2
    echo "   base. Silent from inside this green gate — the template's own tree is the" >&2
    echo "   one shape where neither can happen — and exit 2 at every product's bank." >&2
    exit "$SELFTEST_SHAPES_DRIVE_RC"
fi
# <<< drive: selftest_shapes <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi
# A member outside this shard never reached the consult; the skip is for this
# member's one consult and nobody else's.
SELFTEST_CONSULT_SKIP=""

if selftest_member_begin selftest_leg; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: selftest_leg >>>
# THIS LEG'S OWN DRIVE, and it is the last one registered because it is the only
# one whose subject is the thing running it. It does NOT re-enter the gate and
# it does NOT run the real drive set: it extracts the text between this leg's
# `selftest-leg` sentinels into a scratch directory, sources it there, and hands
# `selftest_drives_leg` a scratch set of tiny planted drives through
# `DJB_SELFTEST_DRIVES_DIR` — one red, one could-not-look, the rest green — so
# the composition can be driven in every state a real set can reach without any
# real drive being the victim (rung-execution §2: a drive builds its own victim,
# and it invokes the leg BODY rather than the gate around it).
#
# WHAT IT IS FOR. The leg's exit is COMPOSED from the whole population rather
# than taken from whichever member reddened first, and every way that
# composition can go wrong is silent: a 2 that stopped outranking a 1 is a
# could-not-look reported as a refusal that fired; a red name dropped from the
# list is a drive that ran and was not reported; an engine selftest that goes
# back to stopping the drives puts the leg back to one red per 25-minute gate,
# which is the cost the composition was built to stop paying.
#
# It also carries the censuses the move must not break: every literal drive
# invocation line and every `# >>> drive: <name> >>>` sentinel is still inside
# the function, each drive block is byte-identical to the one it replaced with
# its own `exit` intact inside its own fence, and the deploy-layer blind-spot
# banner below is unchanged.
#
# No docker, no database, no network; it shims `uv` rather than running the
# engine. Seconds.
set +e
./scripts/tests/test_selftest_leg.sh
SELFTEST_LEG_DRIVE_RC=$?
set -e
if [ "$SELFTEST_LEG_DRIVE_RC" = "2" ]; then
    echo "!! the selftest-leg drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$SELFTEST_LEG_DRIVE_RC" != "0" ]; then
    echo "!! this leg no longer composes its own exit from the whole drive set — or" >&2
    echo "   the registrations the move must not break have stopped agreeing with the" >&2
    echo "   directory. Both failures are silent from inside a green gate: the first" >&2
    echo "   puts a builder back to one red per 25-minute run, and the second hides a" >&2
    echo "   drive that is no longer invoked at all." >&2
    exit "$SELFTEST_LEG_DRIVE_RC"
fi
# <<< drive: selftest_leg <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

if selftest_member_begin stage; then
SELFTEST_BLOCK_RC=0
(
# >>> drive: stage >>>
# THE FIRST DEPLOY-LAYER DRIVE THIS LEG RUNS, and the one entry of the declared
# `deploy/tests/` gap that is now closed. `deploy/stage.sh` takes a green tree
# from the registry to a healthy box and KEYS every act on its own input, which
# is a shape that fails in exactly one silent direction: an act that skips when
# its input moved. The transcript still prints six acts, the exit status is
# still 0, and the box serves old code, an unmigrated schema, or an alert route
# reconciled to some other tree — none of which anything else here can see.
#
# WHY THIS ONE AND NOT ITS SIX SIBLINGS. The block below this leg declares the
# gap and states its reason: not one drive under `deploy/tests/` sources
# `scripts/tests/drive_preamble.sh`, and this leg runs inside the pre-push
# hook, where an inherited absolute `GIT_DIR` turns a drive that builds
# throwaway git repositories into a drive that writes into the real one. This
# drive builds throwaway git repositories AND sources the preamble, so the
# stated blocker does not apply to it. The six that still do not source it stay
# printed and unrun, and the block below names them.
#
# It creates nothing: `ssh`, `provision.sh` and `ship.sh` are planted per case,
# every remote command line is recorded, and no box, registry or container
# runtime is reached. No docker, no database, no network; git and bash.
set +e
./deploy/tests/test_stage.sh
STAGE_DRIVE_RC=$?
set -e
if [ "$STAGE_DRIVE_RC" = "2" ]; then
    echo "!! the stage drive COULD NOT LOOK — see above." >&2
    echo "   A driver that could not run its cases has not cleared them." >&2
    exit 2
elif [ "$STAGE_DRIVE_RC" != "0" ]; then
    echo "!! the keyed deploy no longer keys what it says it keys, or no longer" >&2
    echo "   refuses a box that cannot say which tree it holds. Both are silent from" >&2
    echo "   inside a green run: the deploy prints its acts and exits 0 either way," >&2
    echo "   and the box is the only place the difference shows." >&2
    exit "$STAGE_DRIVE_RC"
fi
# <<< drive: stage <<<
) || SELFTEST_BLOCK_RC=$?
selftest_member_end "$SELFTEST_BLOCK_RC"
fi

selftest_local_drives

    SELFTEST_COMPOSED_RC=0
    selftest_compose || SELFTEST_COMPOSED_RC=$?
    return "$SELFTEST_COMPOSED_RC"
}
# <<< selftest-leg <<<

# THE CALL, and the ONE exit this leg has. `|| RC=$?` rather than a bare call:
# it is the idiom that keeps errexit off the leg's own body, so a drive's red
# ends that drive's subshell and nothing else.
SELFTEST_LEG_RC=0
selftest_drives_leg || SELFTEST_LEG_RC=$?
set -e
if [ "$SELFTEST_LEG_RC" != "0" ]; then
    exit "$SELFTEST_LEG_RC"
fi
}
gate_run_body selftest gate_leg_selftest

# --- WHAT THIS LEG DOES NOT RUN, SAID OUT LOUD --------------------------------
#
# THE GAP. Every drive under `scripts/tests/` is invoked above — the population
# and the registrations agree today, and NO COUNT IS WRITTEN HERE: this sentence
# carried "all fourteen of them" while the directory held nineteen, because two
# rungs added drives and neither felt the number under them. Compare the two
# sets rather than trusting a number:
#
#     comm -23 <(ls scripts/tests/test_*.sh | xargs -n1 basename | sort) \
#              <(grep -oE './scripts/tests/test_[a-z_]+\.sh' scripts/check.sh \
#                | xargs -n1 basename | sort -u)
#
# There is a SECOND drive directory in this repository — `deploy/tests/`
# — and NOT ONE of its drives is invoked by any moment: not this leg, not
# `--loop`, not CI. `docs/product/instruments.md` says so of each of them in as
# many words ("nobody's moment invokes it; it is run by hand and its counts are
# pasted into the work report"), and `docs/product/queue.md` carries the row
# that closes it. They pass — measured on this machine while writing this, 379
# assertions and 0 failures across the five, in about 74s — and that is precisely
# the state `scripts/backup.sh` was in before its drive was wired: green every
# time somebody remembered.
#
# WHY THIS BLOCK DECLARES THE GAP INSTEAD OF CLOSING IT, which is the honest
# half. Cost is not the reason; 74s next to this leg's existing minutes would be
# affordable. The reason is that NOT ONE of them sources
# `scripts/tests/drive_preamble.sh`, and that file is not a nicety at THIS
# moment:
#
#   * Its §1 neutralises the ABSOLUTE `GIT_DIR` that
#     `git -C <linked worktree> push` exports into the pre-push hook — which is
#     the moment this leg runs in. Its header records what happened the one time
#     a drive built throwaway git repositories without it: branches, commits and
#     `core.bare true` written into the REAL repository, every command exiting 0.
#     `deploy/tests/test_ship.sh` builds throwaway git repositories.
#   * Its §4 strips `CI`/`GITHUB_ACTIONS`, and it names
#     `deploy/tests/test_release.sh` explicitly as carrying the identical defect
#     at its own piped-stdout case: "the day it is wired, it is red exactly as
#     this one was." The queue row records the same measurement (98/3 under a CI
#     environment).
#
# So wiring them from here would trade a STATED blind spot for an UNSTATED
# hazard, in somebody else's territory (`deploy/`), on the gate every push runs.
# That is a rung of its own. The gap is declared instead — in
# the transcript, where the person reading a green gate is, rather than only in
# a queue row nobody reads at push time.
#
# AND IT IS DERIVED, NEVER TYPED. The list below is the directory, so the sixth
# deploy drive is named here THE DAY IT EXISTS instead of being invisible the way
# these five have been. The preamble question is asked per drive for the same
# reason: when the stated reason expires, the transcript says so itself rather
# than going on reciting a blocker that is gone. It stays a printed notice and
# not a red — a gate that reddened because somebody else improved a drive is the
# "reddened by legitimate work" class this file refuses elsewhere.
#
# IT IS THE SELFTEST LEG'S NOTICE AND IT PRINTS WHERE THAT LEG RAN. A runner
# handed some OTHER unit never ran the drives this block declares a gap beside,
# and a blind-spot notice under a transcript containing no drives at all reads
# as a claim about the unit in front of it. `GATE_LEG_UNIT_LEGS` is empty on
# every path but a unit run, so the guard is a no-op everywhere else and the
# whole-gate transcript is unchanged.
DEPLOY_DRIVES=()
case "${GATE_LEG_UNIT_LEGS:-,selftest,}" in
*,selftest,*)
    for DEPLOY_DRIVE in deploy/tests/test_*.sh; do
        [ -f "$DEPLOY_DRIVE" ] || continue
        # A DRIVE THIS LEG ACTUALLY RUNS IS NOT A GAP, and the exclusion is
        # DERIVED from this file's own invocation lines rather than typed: the
        # first deploy-layer drive to be wired left the block below saying it
        # was not run, on the same page as its own `drive <name>: exit 0` line.
        # `grep -qxF` — the whole line, at column zero, which is the same shape
        # `selftest_registered_drives` reads.
        grep -qxF "./${DEPLOY_DRIVE}" scripts/check.sh && continue
        DEPLOY_DRIVES+=("$DEPLOY_DRIVE")
    done
    ;;
esac
if [ "${#DEPLOY_DRIVES[@]}" -gt 0 ]; then
    echo ""
    echo "  NOT RUN BY THIS LEG — a DECLARED blind spot, not a silent one:"
    echo "  ${#DEPLOY_DRIVES[@]} deploy-layer drive(s) under deploy/tests/, which no moment invokes."
    DEPLOY_READY=0
    for DEPLOY_DRIVE in "${DEPLOY_DRIVES[@]}"; do
        if grep -q "drive_preamble.sh" "$DEPLOY_DRIVE"; then
            echo "    ${DEPLOY_DRIVE} — sources drive_preamble.sh now; its blocker is gone"
            DEPLOY_READY=$((DEPLOY_READY + 1))
        else
            echo "    ${DEPLOY_DRIVE} — no drive_preamble.sh: an inherited GIT_DIR and the"
            echo "        CI/GITHUB_ACTIONS strip are both unhandled in it"
        fi
    done
    echo "  Wiring them here without that preamble is how a drive writes into the real"
    echo "  repository from the pre-push hook (see the note above this block). Until"
    echo "  then they are run BY HAND — ./deploy/tests/<name>.sh, same 0/1/2 semantics"
    echo "  as every drive above — and queue.md carries the row that closes this."
    if [ "$DEPLOY_READY" = "${#DEPLOY_DRIVES[@]}" ]; then
        echo "  ** ALL of them now carry the preamble: the reason printed above has EXPIRED."
        echo "     Wire them into this leg and delete this block (see queue.md). **"
    fi
fi

leg full-house-rules "house rules, full (live scan + diff vs merge-base when on a branch)"
gate_leg_full_house_rules() {
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)
DIFF_ARGS=()
if [ "$BRANCH" != "main" ] && [ "$BRANCH" != "HEAD" ] && git rev-parse --verify -q main >/dev/null; then
    BASE=$(git merge-base HEAD main 2>/dev/null || true)
    [ -n "$BASE" ] && DIFF_ARGS=(--diff "$BASE")
fi
set +e
# ${arr[@]+...} — the empty-array-safe expansion: on main there is no
# merge-base, DIFF_ARGS stays empty, and a bare "${DIFF_ARGS[@]}" dies under
# set -u. Found the first time the full gate ran on main itself (2026-08-20);
# every worktree run had a merge-base and never exercised this line.
GATE_SKIP_DJANGO_LEG=1 uv run python -m quality.gate ${DIFF_ARGS[@]+"${DIFF_ARGS[@]}"}
GATE_RC=$?
set -e
if [ "$GATE_RC" = "2" ]; then
    echo "!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass." >&2
    exit 2
elif [ "$GATE_RC" != "0" ]; then
    exit "$GATE_RC"
fi
}
gate_run_body full-house-rules gate_leg_full_house_rules

# --- the product's own legs, LAST -------------------------------------------
#
# AFTER `full-house-rules` AND NOT BEFORE IT, because the template's own
# enforcement is what a product's leg is standing on: a red house rule is this
# system's verdict about the tree, and running a product's licence scan ahead
# of it would put the two in a race for which red a reader sees first.
#
# THE GUARD IS THE WHOLE NEGATIVE. With no drawer, `LOCAL_LEGS_MEMBERS` is
# empty, nothing is announced, no body runs, and this run's transcript, its
# listing and its verdict row are the ones a tree with no local-legs support at
# all would have printed. `scripts/tests/test_local_legs.sh` asserts that by
# DIFFING two runs rather than by reading this paragraph.
if [ -n "$LOCAL_LEGS_MEMBERS" ]; then
leg local-legs "the product's own legs (scripts/local/legs/) — every tier, every leg, whatever it touches; the verdict row names each one as local:<name>"
LOCAL_LEGS_MODE_TIER=full
LOCAL_LEGS_TOUCH_FILTER=0
LOCAL_LEGS_RUN_RC=0
gate_run_body local-legs gate_leg_local_legs || LOCAL_LEGS_RUN_RC=$?
[ "$LOCAL_LEGS_RUN_RC" = "0" ] || exit "$LOCAL_LEGS_RUN_RC"
fi

leg_done
echo "ok: all checks passed ($(($(date +%s) - T_MODE_START))s)"
if [ -n "$GATE_LEG_UNIT" ]; then
    echo "  ...of ONE UNIT: ${GATE_LEG_UNIT}${GATE_SHARD:+ shard ${GATE_SHARD}}. The other units of this"
    echo "  gate were neither announced nor run — ./scripts/check.sh --list-legs names them."
fi

# --- the verdict, recorded ---------------------------------------------------
# Only the FULL path earns one: a partial run must never vouch for a tree.
# Reaching this line at all means exit 0.
MEASURED_END=$(gate_measured_tree || true)
if [ -n "$GATE_STORE_MEMBERS" ]; then
    # A MEASUREMENT RUN BANKS NOTHING, AND IT WRITES A TRACKED FILE — in that
    # order, and the two facts are the same fact. The file it rewrites is part
    # of the tree a verdict would be keyed on, so a run that both wrote it and
    # banked would vouch for bytes that no longer exist. This is why
    # `--store-durations` is a separate run rather than a flag on a bank.
    GATE_MEMBER_PATH=$(always_on_durations_path)
    if gate_member_durations_write "$GATE_MEMBER_PATH" "${MEASURED_START:-unmeasured}"; then
        echo "  --store-durations: ${GATE_MEMBER_PATH} REWRITTEN from this run's own clock"
        echo "                     ($(LC_ALL=C sort -u "$GATE_MEMBER_TIMES" | awk 'END { print NR + 0 }') member(s), measured_at ${MEASURED_START:-unmeasured} on $(uname -sr))"
        echo "  It is a MEASUREMENT and not a verdict: nothing was banked, and the file"
        echo "  is committed by whoever ran this, as the measurement it is. The --loop"
        echo "  always-on set is derived from it at the next loop."
    else
        echo "!! --store-durations: nothing was written to ${GATE_MEMBER_PATH}." >&2
        echo "   No member reported its seconds, or the path is not writable. The" >&2
        echo "   always-on set goes on deriving from whatever is committed there." >&2
        exit 2
    fi
    [ -z "$GATE_MEMBER_TIMES" ] || rm -f "$GATE_MEMBER_TIMES"
elif [ -n "$GATE_LEG_UNIT" ]; then
    # A UNIT IS A PART, AND A PART VOUCHES FOR NOTHING. Not the full verdict row
    # the pre-push hook reads, not a partition row, not a loop row: every one of
    # them is a claim that a whole gate has passed these bytes, and this run ran
    # one unit of it. The runner that was handed every unit has the whole claim
    # between them, and nothing in this checkout is entitled to assemble it.
    echo "  no verdict recorded — --leg ${GATE_LEG_UNIT}${GATE_SHARD:+ --shard ${GATE_SHARD}}: one unit of the gate"
    echo "  is a targeted drive and vouches for no tree. The tree it ran on was ${MEASURED_END:-unreadable}."
elif [ -n "$GATE_PR" ]; then
    # A NARROWED RUN VOUCHES FOR NO TREE. The ledger's rows are consulted by the
    # pre-push hook, which reads them as "a full gate has passed these bytes";
    # this run passed a SCOPE of them. A row nobody may read is a row nobody
    # writes.
    echo "  no verdict recorded — narrowed run (--pr banks nothing: no full verdict row,"
    echo "  no partition row). The tree it measured was $MEASURED_END."
    gate_run_note narrowed-run
elif [ -n "${DJB_GATE_LEGS_DRY:-}" ]; then
    # A DRY RUN JUDGED NOTHING. Every leg was announced and no body ran, so the
    # one thing that must not happen is a verdict row saying this tree passed.
    echo "  no verdict recorded — DJB_GATE_LEGS_DRY: every leg was announced and none ran"
    gate_run_note legs-dry
elif [ -z "$MEASURED_START" ] || [ -z "$MEASURED_END" ]; then
    echo "  no verdict recorded — the tree could not be measured"
    gate_run_note unmeasured
elif [ "$MEASURED_START" != "$MEASURED_END" ]; then
    # Routine here, not an error: agents edit concurrently. The run passed; it
    # measured a tree that no longer exists, so it vouches for nothing.
    echo "  no verdict recorded — the tree changed while the gate ran"
    echo "    started on $MEASURED_START"
    echo "    ended on   $MEASURED_END"
    gate_run_note tree-changed
elif gate_ledger_record "$MEASURED_START" "$(gate_full_legs)"; then
    echo "  verdict recorded for tree $MEASURED_START"
    gate_run_verdict_written
else
    echo "  no verdict recorded — the ledger could not be written"
    gate_run_note ledger-unwritable
fi
