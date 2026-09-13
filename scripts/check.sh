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
--census)
    GATE_CENSUS=1
    ;;
*)
    # Not a usage nit: a mistyped flag falling through to a silently different
    # run is enforcement misfiring, and that is an exit 2.
    echo "!! unknown argument '$MODE': check.sh takes nothing, --fast, --loop, --loop --mine, --census, --bank, or --pr --base <sha>" >&2
    exit 2
    ;;
esac
shift || true
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
instrument_census() {
    local rc
    set +e
    python3 scripts/goalpost_scan.py --census
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
. scripts/db.sh
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
# The --loop `fe` leg: the tri-state (absent/untouched/full) over frontend/,
# proven by scripts/tests/test_fe_leg.sh's fixture worlds rather than by this
# tree's own current state (this template ships with no frontend/ at all).
. scripts/fe_gate.sh

# In run order. supply-chain moved ahead of pytest-x2; see the ordering note at
# that leg. `full-house-rules` was missing for a while: the leg ran on every
# full gate and the ledger line never said so, so every recorded verdict
# under-reported what green had meant.
FULL_LEGS=ruff,mypy,import-linter,djb-checks,house-rules,migrations,goalpost-census,db-pin,deploy-check,supply-chain,temporal-census,partition,pytest-x2,own-tree-census,selftest,full-house-rules
MEASURED_START=""
T_MODE_START=$(date +%s)

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
# lease and one pytest slot to find out. It is also why the scope PRINTS before
# any leg has run — a red gate still discloses the scope it graded at, which is
# the property the `--loop` banner has for the same reason.
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
    # AND IT DROPS THE `--pr` COUNTS DIRECTORY, because this trap is the only
    # thing every exit path goes through: the directory used to be removed where
    # the partition's verdict would have been banked, which a red leg, a refused
    # lease and a SIGTERM all exit above. Empty on every run that is not `--pr`,
    # and the guard is what keeps `rm -rf ""` from being the thing that runs.
    trap 'RC=$?; trap "" PIPE; { command -v heartbeat_stop >/dev/null 2>&1 && heartbeat_stop; } || true; gate_lock_release; gate_slot_release; gate_lease_release; [ -z "${GATE_PR_COUNTS_DIR:-}" ] || rm -rf "$GATE_PR_COUNTS_DIR"; gate_run_finish "$RC" || true' EXIT
    gate_lock_acquire
    trap 'gate_run_killed' TERM INT HUP
    # Measured BEFORE the first leg reads a byte, so the key names the content
    # the gate actually saw. `|| true`: failing to measure costs a verdict,
    # never a gate run.
    MEASURED_START=$(gate_measured_tree || true)
    # What made this run legal, handed to the ledger BEFORE it announces, so the
    # header line and the verdict row carry the identical phrase.
    GATE_RUN_SANCTION="$GATE_SANCTIONED_BY"
    gate_run_start "${MEASURED_START:-unknown-tree}"
    gate_run_announce
else
    gate_lock_refuse_if_held
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
LOOP_COUNTS_DIR=""
LOOP_MISS_CENSUS=""

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
    if [ -z "${DJB_LOOP_VERBOSE:-}" ]; then
        echo "  key         ${LOOP_LEDGER_KEY:-(none — the key could not be derived)}   (DJB_LOOP_VERBOSE=1 for the detail, the tree, the env components and the ledger census)"
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
# It is a FUNCTION for the same reason `loop_miss_narrative` is: the drive reads
# this definition out of this file and runs it over the real state it built.
loop_counts_refuse_if_short() {
    local reported=${1:-0} expected=${2:-0}
    case "$reported" in '' | *[!0-9]*) reported=0 ;; esac
    case "$expected" in '' | *[!0-9]*) expected=0 ;; esac
    # An unknown population cannot be short of itself: when the leg did not say
    # how many collectors it started there is nothing to compare, and inventing
    # a number here would be the second derivation this refuses to have.
    [ "$expected" -gt 0 ] || return 0
    [ "$reported" -lt "$expected" ] || return 0
    echo "!! ${reported} of ${expected} collectors reported — a collector died and the suite that ran is not the suite that was asked for; nothing is judged" >&2
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

if [ "$MODE" = "--loop" ]; then
    # THE FLAG IS CHECK.SH'S, THE MEANING IS THE LIBRARY'S. `--mine` is parsed
    # at the top of this file and handed to the derivation as one input; what it
    # subtracts (the closure, and only the closure) is declared beside the
    # derivation in scripts/loop_tier.sh, where the rest of the scope rules live.
    LOOP_MINE="$GATE_MINE"
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
    if [ -n "$LOOP_SCOPE_NOTES" ]; then
        printf '%s\n' "$LOOP_SCOPE_NOTES" | sed 's/^/  note:       /'
    fi
    # THE HONESTY BANNER, BEFORE THE FIRST LEG. It prints here rather than beside
    # the verdict for the reason every banner in this file prints early: a reader
    # deciding whether to trust a run should not have to reach the end of it, and
    # a RED `--mine` discloses its narrowing exactly as a green one does.
    [ -z "$GATE_MINE" ] || loop_mine_banner open "$LOOP_TIER_MODE" "$LOOP_TIER_OWN_APPS"
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
}

leg() {
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
uv run ruff check .
uv run ruff format --check --quiet .

leg mypy "mypy --strict (apps, config)"
uv run mypy

leg import-linter "import-linter (layer contracts)"
uv run lint-imports

leg djb-checks "django system checks, tag djb (settings=test, no database)"
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check --tag djb

leg house-rules "house rules (quality/rules.yaml — live scan + diff vs HEAD)"
# The djb leg above already ran; the engine skips its own copy of it.
set +e
GATE_SKIP_DJANGO_LEG=1 uv run python -m quality.gate --diff HEAD $([ "$MODE" = "--loop" ] && echo --terse) # unquoted on purpose: empty must be NO argument
GATE_RC=$?
set -e
if [ "$GATE_RC" = "2" ]; then
    echo "!! ENFORCEMENT ITSELF IS BROKEN — this outranks any pass." >&2
    exit 2
elif [ "$GATE_RC" != "0" ]; then
    exit "$GATE_RC"
fi

leg migrations "makemigrations --check (+ linear migrations: one leaf per app)"
# The one-leaf/merge/max_migration checks are house rule 6 and already ran in
# the leg above; this catches the model change whose migration was never made.
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py makemigrations --check --dry-run

leg goalpost-census "instrument census (every executable git knows about outside apps/ and config/ owes a row in instruments.md)"
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
# IN `--fast`, AND THAT IS AFFORDABLE ON PURPOSE: it reads `git ls-files`, some
# mode bits and one markdown table — no database, no network, no Django import.
# ~0.1s on this tree, which is why it can sit in the tier pre-commit runs
# rather than in the one nobody feels.
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

leg queue-index "the queue's index vs its record — the generated index is what queue_index.py generates, every anchor has one index row and back, both ratchets hold"
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
set +e
python3 scripts/queue_index.py --check
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
    echo "   \`python3 scripts/queue_index.py --index\`. A hand-edited index is two" >&2
    echo "   truths in the one file every other document defers to for order." >&2
    exit "$QUEUE_INDEX_RC"
fi

leg db-pin "DATABASE_NAME: this checkout's .env pin vs the derivation"
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
db_pin_leg
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
leg archaeology "archaeology-census over THE ACTIVE RUNG'S CHANGED SHIP-BUCKET FILES ONLY — publish.sh's full-artifact scan stays the belt at release"
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

if [ "$MODE" = "--fast" ]; then
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

    # THE ARCHAEOLOGY LEG USED TO SIT HERE. It is now one tier down, among the
    # `--fast` legs this mode runs before it reaches this line, for the reason
    # written beside it there: the hook is what let the id through, and the hook
    # runs `--fast`. This mode still runs the census exactly once, and the leg's
    # text, patterns, classifier and allow-list did not change.

    # --- the fe leg: three states, none of them inferred from a duration ----
    # ABSENT — no frontend/ on this tree. This template's steady state, and a
    # rule about a tree nobody has must not cost a Python-only product a red
    # gate forever: a printed skip, never silence, because a skip that prints
    # nothing is indistinguishable from a pass.
    # UNTOUCHED — frontend/ exists and the active rung changed nothing under
    # it. The fast path: nothing under frontend/ derives differently than it
    # did before the active rung's changes, so nothing frontend-shaped is re-run, mirroring
    # the own-app tiering the pytest leg above already applies one door over.
    # FULL — frontend/ exists and the active rung touched it: the
    # frozen-lockfile check runs, and the declared test script (if any) runs.
    # TOOLCHAIN ABSENT while frontend/ is present AND touched is exit 2, not
    # a skip — the same tree-present/toolchain-absent cell
    # `quality/worlds.py`'s `tree_verdict` names `broken` for a rules.yaml
    # runner rule. One decision table, two homes (this leg is check.sh's own
    # gate leg; that one is a rules.yaml rule's live-scan decision), kept in
    # lockstep by citation since neither imports the other across a
    # territory line — a rung that let the two disagree is the finding this
    # comment exists to make checkable.
    leg fe "the fe leg — three states (absent/untouched/full) over frontend/, deferring to the same tree-present/toolchain-absent could-not-look cell quality/worlds.py's tree_verdict names for a runner rule"
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
    fe_leg_run "$FE_CHANGED"
    FE_RC=$?
    set -e
    rm -f "$FE_CHANGED"
    if [ "$FE_RC" = "2" ]; then
        exit 2
    elif [ "$FE_RC" != "0" ]; then
        exit "$FE_RC"
    fi

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
    echo "  workers:    -n ${GATE_SLOT_WORKERS} (this box's cores split ${GATE_SLOT_TOTAL} ways — one share per pytest slot)"
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
        if [ -n "$LOOP_SCOPE_NARROW" ]; then
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
    if [ -n "$LOOP_COUNTS_DIR" ]; then
        LOOP_COUNT_FILES=$(find "$LOOP_COUNTS_DIR" -type f 2>/dev/null | sort)
        if [ -z "$LOOP_COUNT_FILES" ]; then
            echo "!! the --loop scope banner has NO counts file to read: not one collector" >&2
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
                    echo "!! THE COLLECTORS DISAGREE ABOUT THE SCOPE." >&2
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
                loop_counts_refuse_if_short "$LOOP_COUNT_N" "${GATE_SLOT_WORKERS:-0}"
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
                sed 's/^/  /' "$LOOP_COUNT_FIRST"
                echo "  (reconciled across $(printf '%s\n' "$LOOP_COUNT_FILES" | wc -l | tr -d ' ') collector file(s) — compared, never summed)"
                echo "  A REGRESSION IN A DESELECTED APP SURFACES AT THE WAVE BANK, NOT AT"
                echo "  THIS RUNG. That is the trade this narrowing makes, and it is printed"
                echo "  beside the number it was made for rather than written down elsewhere."
            fi
        fi
        rm -rf "$LOOP_COUNTS_DIR"
    fi
    if [ "$LOOP_BANNER_RC" != "0" ]; then
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
    if [ -n "$LOOP_LEDGER_KEY" ]; then
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
            if loop_ledger_record "$LOOP_LEDGER_KEY" "$LOOP_SCOPE_CANONICAL" 1 \
                "$LOOP_LEDGER_TREE_END" "${LOOP_ENV_FINGERPRINT:-unstated}"; then
                echo "  banked: this --loop verdict, keyed on tree + environment + scope."
                echo "          ${LOOP_LEDGER_KEY}"
                echo "          tree=${LOOP_LEDGER_TREE_END}"
                echo "          env=${LOOP_ENV_FINGERPRINT:-unstated}"
                echo "          scope=${LOOP_SCOPE_CANONICAL}"
                echo "          A later --loop on identical bytes at THIS scope reuses it;"
                echo "          a WIDER scope is a different key and re-measures."
            fi
        else
            echo "  no verdict banked — the key did not re-derive to the same value at the"
            echo "  end of the run, so something moved while the gate ran. Nothing was"
            echo "  wrong with this run; it simply vouches for no single tree."
        fi
    elif [ -n "$GATE_MINE" ]; then
        loop_mine_banner close "$LOOP_TIER_MODE" "$LOOP_TIER_OWN_APPS"
    fi
    exit 0
fi

# --- the full legs -----------------------------------------------------------

# ORDERING: supply chain runs FIRST among the full legs — ahead of the two
# pytest passes — because pip-audit is the only leg in the whole gate that
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
temporal_census pre-suite
TEMPORAL_PRE_SEEN=$TEMPORAL_SEEN

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

leg pytest-x2 "pytest (twice, both passes under ONE seed and ONE OF THIS MACHINE'S PYTEST SLOTS, nothing in between — the second run proves the first left nothing behind)"

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
gate_refuse_reset
set +e
gate_slot_acquire full
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
    echo "  both passes run ONLY: ${PARTITION_TARGETS:-<nothing outside the partition>}"
else
    echo "  PLATFORM PARTITION RUNNING — no banked verdict for $PARTITION_KEY"
    echo "  both passes run the WHOLE suite"
fi

# ONE SEED, BOTH PASSES (ADR gate-1). This leg's meaning is narrow and it has
# to stay narrow: run 1 passed, run 2 did not, therefore run 1 LEFT SOMETHING
# BEHIND — the dev Temporal server, Mailpit, Redis, a file in the tree (the
# test databases are per-run, so they are never the answer). pytest-randomly
# picks a fresh seed per run by default, which would quietly widen that meaning
# to "run 2 failed for one of two reasons and you cannot tell which" — the
# order differed, or the state did. So the seed is fixed here and fed to both,
# and the worker count — one slot's share of this box's cores, held across both
# passes — is the same on both, which pins the worker assignment too. What
# differs between the two passes is then exactly one thing.
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
        summary=$(awk '/^(FAILED|ERROR) /{ if (++shown <= 20) print "     " $0 }' "$out")
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
        echo "   Both passes ran seed $seed at the same worker count, so the collection order" >&2
        echo "   and the worker assignment were IDENTICAL: this is not an ordering difference." >&2
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

PYTEST_SEED=$(((RANDOM << 15) | RANDOM))
echo "  both passes run --randomly-seed=$PYTEST_SEED (replay a red order with it)"
echo "  workers:    -n ${GATE_SLOT_WORKERS} (this box's cores split ${GATE_SLOT_TOTAL} ways — one share per pytest slot)"
echo "              NOT -n auto, and the same number on BOTH passes, which is what pins"
echo "              the worker assignment and keeps this leg's meaning narrow."
gate_pytest_nominal "$GATE_SLOT_NOMINAL_FULL" GATE_SLOT_NOMINAL_FULL \
    "$(gate_ledger_path 2>/dev/null || true)"
# ONE TICKER ACROSS BOTH PASSES, relabelled rather than restarted: the slot is
# held across both, so the elapsed arithmetic is continuous and the only thing
# that changes between them is the word.
heartbeat_start "pass 1" "$GATE_PYTEST_NOMINAL" "$GATE_PYTEST_NOMINAL_PROV"

set +e
# UNQUOTED ON PURPOSE: `$PARTITION_TARGETS` is a path LIST that has to word-split
# into pytest arguments, and it is empty when the whole suite runs.
# shellcheck disable=SC2086
./scripts/test.sh -n "$GATE_SLOT_WORKERS" --randomly-seed="$PYTEST_SEED" $PARTITION_TARGETS
TEST_RC=$?
set -e
if [ "$TEST_RC" != "0" ]; then
    echo "!! pass 1 is red — the suite fails on its own, before idempotency is in question." >&2
    exit 1
fi
echo "  pytest pass 1: green (seed $PYTEST_SEED)"
# The ticker's subject changes here and nowhere else. Pass 2's output is
# captured whole, so this is the ONLY thing that will be printed between now and
# the end of the leg — which is the silence this instrument exists for.
heartbeat_label "pass 2"

# Pass 2's output is CAPTURED to a file and printed whole afterwards, the same
# shape the supply-chain leg uses for pip-audit and for the same reason: the leg
# has to READ what it is about to make a claim about, and reading it through a
# pipe would replace pytest's exit status with the reader's — the one thing
# neither script may do. The cost is that pass 2 prints at the end instead of as
# it goes; the alternative is a leg that names a cause it never looked at.
echo "  pytest pass 2 running (output is captured and printed whole when it ends)..."
PASS2_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-pytest-pass2.XXXXXX")
set +e
# shellcheck disable=SC2086
./scripts/test.sh -n "$GATE_SLOT_WORKERS" --randomly-seed="$PYTEST_SEED" $PARTITION_TARGETS >"$PASS2_OUT" 2>&1
TEST_RC=$?
set -e
heartbeat_stop
cat "$PASS2_OUT"
if [ "$TEST_RC" != "0" ]; then
    pytest_x2_verdict "$PASS2_OUT" "$PYTEST_SEED"
    rm -f "$PASS2_OUT"
    exit 1
fi
rm -f "$PASS2_OUT"
echo "  pytest pass 2: green (seed $PYTEST_SEED)"
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

# --- the second half of the temporal-census leg ------------------------------
leg temporal-census "temporal test-server census, AFTER the suite — the property is a DIFFERENCE: an orphan that was not on this machine in any state before the suite ran"
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

leg selftest "house-rules self-test (every canary planted through the real scope must fire; every negative must stay silent) + every shell refusal drive under scripts/tests/"
set +e
uv run python -m quality.gate --selftest
SELF_RC=$?
set -e
if [ "$SELF_RC" != "0" ]; then
    echo "!! ENFORCEMENT ITSELF IS BROKEN — a dead canary outranks any pass." >&2
    exit 2
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
# It costs about a minute, nearly all of it docker round trips (a schedule
# created and deleted, a workflow started and terminated, four databases created
# and dropped). That is the price of the only thing in this repository that
# drives a destroy path end to end, and it is paid at push rather than per rung.
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
# planted test touches one. ~2 minutes.
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

# The ledger drive touches no database and no network: it forges rows into a
# scratch file through DJB_LOOP_LEDGER, so nothing it writes can ever become a
# banked verdict in this checkout. Seconds.
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

# `test_db_zsh.sh` drives `scripts/db.sh` under the shell it is actually sourced
# by. That library is the one file here that is SOURCED rather than run, so its
# shebang is inert and the interpreter is the caller's — which on this platform
# is routinely zsh, where a tied parameter used as a local emptied PATH mid-call
# and `db_create` printed `created database` over a database it had not made.
# It SKIPS rather than passes when it cannot find the shell, and says so. Needs
# zsh and the compose Postgres for the live tooth; ~4s.
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

# `test_publish.sh` drives the export instrument — the one that decides what a
# consuming product receives. Every case is a refusal or a census, and once a
# consumer has merged a release, history can never be re-cut: the per-publish
# census is the only wall left. It builds its own throwaway repository and reads
# nothing in this checkout, so its verdict does not move when this tree does.
# No docker, no database; ~12s.
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
DEPLOY_DRIVES=()
for DEPLOY_DRIVE in deploy/tests/test_*.sh; do
    [ -f "$DEPLOY_DRIVE" ] || continue
    DEPLOY_DRIVES+=("$DEPLOY_DRIVE")
done
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

leg_done
echo "ok: all checks passed ($(($(date +%s) - T_MODE_START))s)"

# --- the verdict, recorded ---------------------------------------------------
# Only the FULL path earns one: a partial run must never vouch for a tree.
# Reaching this line at all means exit 0.
MEASURED_END=$(gate_measured_tree || true)
if [ -n "$GATE_PR" ]; then
    # A NARROWED RUN VOUCHES FOR NO TREE. The ledger's rows are consulted by the
    # pre-push hook, which reads them as "a full gate has passed these bytes";
    # this run passed a SCOPE of them. A row nobody may read is a row nobody
    # writes.
    echo "  no verdict recorded — narrowed run (--pr banks nothing: no full verdict row,"
    echo "  no partition row). The tree it measured was $MEASURED_END."
    gate_run_note narrowed-run
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
elif gate_ledger_record "$MEASURED_START" "$FULL_LEGS"; then
    echo "  verdict recorded for tree $MEASURED_START"
    gate_run_verdict_written
else
    echo "  no verdict recorded — the ledger could not be written"
    gate_run_note ledger-unwritable
fi
