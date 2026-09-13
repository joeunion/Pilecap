#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made. Measured on this tree:
#
#   zsh scripts/queue_cited.sh   exit 2 blaming the TREE ("this is not a
#                                checkout root") for zsh's word-splitting
#   zsh scripts/kill_mine.sh     an ordinary-looking census of nothing
#   sh  scripts/sweep.sh         "lifecycle.sh: line 152: syntax error"
#
# A wrong shell here does not crash. It ANSWERS, and the answer looks like the
# tree's fault.
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart (SHELLOPTS carries
# `posix`). On Linux `/bin/sh` is dash and the first test is the one that
# fires. Neither test alone covers both machines.
#
# A SOURCED library must never carry this. There the interpreter is the
# caller's ON PURPOSE and an `exit` would kill the caller's shell — the
# argument is scripts/db.sh's, at scripts/db.sh:50-57, and it is why db.sh is
# the one executable in this tree deliberately without a belt.
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
# THE ONE CENSUS, AND THE ONE BROOM, for everything a checkout leaves behind.
#
#   ./scripts/sweep.sh                              census: every declared class
#   ./scripts/sweep.sh --roots <dir>                ...with clones under <dir> as evidence
#   ./scripts/sweep.sh --class schedule             one class
#   ./scripts/sweep.sh --only <identity-prefix>     one checkout's machinery
#   ./scripts/sweep.sh --class schedule --only X --assert-none
#                                                   exit 1 if anything is in scope
#   ./scripts/sweep.sh --list-classes               the registry, one name per line
#   ./scripts/sweep.sh --registry                   the registry, all seven columns
#
#   ./scripts/sweep.sh --sweep                      destroy THIS CHECKOUT's disposable leftovers
#   ./scripts/sweep.sh --sweep --hot-path --perf    ...its warm caches too
#   ./scripts/sweep.sh --sweep --force-foreign --roots <dir>
#                                                   ...and what nobody under <dir>
#                                                   can vouch for. --roots is
#                                                   REQUIRED here: without it,
#                                                   "nobody can vouch for it"
#                                                   means "nobody was asked".
#
# WHAT IT IS. `scripts/lifecycle.sh` declares the machinery classes, the one
# live-checkout enumerator and the four verdicts; this is the entry point that
# walks them. Read that file first — every sentence about WHY lives there, and
# is deliberately not repeated here so the two cannot drift.
#
# THE CENSUS IS THE POINT, and `--sweep` is the afterthought. A machine's
# leftovers are not a tidiness problem: an infinitely durable Temporal Schedule
# keyed to a checkout that was deleted last Tuesday goes on starting workflows
# nothing will ever poll, forever, and the only thing that makes that visible is
# somebody asking the servers what exists. Run this; read it; then decide.
#
# WHO MAY BE DESTROYED, and it is a short list:
#
#   * THIS CHECKOUT'S OWN LEFTOVERS. `--sweep` alone reaches an instance only
#     when BOTH halves hold: this checkout's own forward derivation vouches for
#     the identity, AND the instance's CLASS is declared `disposable` in
#     `scripts/lifecycle.sh` — a test database, a warm cache, a restore-drill
#     scratch, a schedule the worker re-declares at startup.
#   * WHAT NOBODY UNDER A NAMED ROOT CAN VOUCH FOR, by hand.
#     `--sweep --force-foreign --roots <dir>` adds the FOREIGN residue, and
#     prints every name with its reason BEFORE acting, so an operator reading
#     the transcript sees the claim first and can stop at the first surprise.
#     `--roots` is not optional there: it is the evidence the operator is
#     claiming to have, and without it FOREIGN means only that nothing was
#     asked (the refusal, and what it cost, are beside the flag parsing below).
#
# OWNING A THING IS NOT A LICENCE TO DESTROY IT, and that sentence once cost a
# real database. `--sweep` used to reach EVERYTHING this checkout owned,
# because the `live` verdict fell straight through into the destroy path: the
# owner's first real sweep printed `live … (THIS CHECKOUT)` and then `DESTROYED`
# one line later, for the main checkout's live development database and for one
# of its RUNNING workflow executions. `live` answers WHOSE a thing is; whether
# it is a leftover or a working set is a different question, it belongs to the
# class, and it is now declared there and asked by one function
# (`lc_destroy_decision`) that both the printed line and the act consult.
#
# And who may not, ever: another visible checkout's (`live` — it is running, or
# it is between two runs, and neither is mine to touch), anything with positive
# evidence of use right now (`IN USE`), anything outside the derivation entirely
# (`REFUSED` — `djb_main`, `djb_verify`, `postgres`, a schedule keyed to a
# hand-pinned queue name), and **anything of mine whose class is not
# disposable** — this checkout's own database and its own running executions
# among them.
#
# WHO OWNS THE MACHINE-STATE LAYER, and it is this file. A survey once
# found fifteen Temporal Schedules in the dev namespace, every one of
# them keyed to a path hash from before the repository was renamed or to a
# checkout that has since been deleted, none of them naming a queue any worker
# polls — still firing on a cadence, stranding runs behind them. Its closing
# observation was that nothing owned the layer BETWEEN the checkouts and the
# containers. So, said once, here:
#
#   THE SWEEP OWNS IT, because a deleted checkout cannot self-clean. An earlier
#   rung gave the create half a self-clean (ADR platform-lifecycle-1): a worker starting in
#   `process` lifetime deletes the legacy Schedules ITS OWN queue owns. That
#   covers exactly one population — a LIVE checkout's own legacy — and it is
#   structurally incapable of covering any other, because the code that would do
#   the cleaning was deleted along with the checkout that would have run it. The
#   machinery outlives the code that made it; only something OUTSIDE any one
#   checkout can see it, and this census is the only thing that looks.
#
#   THE CENSUS OWNS THE LOOKING; THE OWNER OWNS THE DESTROYING. That split is not
#   timidity, it is the same lesson's bill: this run cannot tell a dead checkout's leftovers
#   from a sibling clone's working set, only that nothing here can vouch for
#   either (FOREIGN). So the instrument enumerates, attributes, dates and prints
#   — and `--sweep --force-foreign --roots <dir>` is a sentence a person types
#   after reading what it is about to do, with the root naming the evidence they
#   looked at. Typed without the root it is refused, because then it is not a
#   judgement about a machine; it is a judgement about the part of the machine
#   this run happened to be standing in.
#
# WHICH IS WHY THE CENSUS CARRIES CLOCKS. A verdict says WHOSE a thing is.
# The clocks say WHAT IT IS DOING: when a schedule last fired and when it fires
# next, how old a stranded run is, how deep the backlog behind a queue with no
# pollers has grown. `FOREIGN` alone reads like paperwork; `FOREIGN, fires every
# 5m, 3 tasks backed up 9h16m, nothing polling` is the finding, and it is the
# same row.
#
# WARM CACHES ARE NEVER IN THE DEFAULT BROOM. The hot-path probe cache (rule 35)
# and the seeded perf world (ADR perf-1) are stable, reused, expensive to
# rebuild, and dropping one out from under a running harness fails that harness.
# They are SHOWN in every census as `warm` and reached only by `--hot-path` /
# `--perf`. There is deliberately no way to reach them by accident, and that
# holds for `--force-foreign` too.
#
# AN UNRECOGNIZED SHAPE IS EXIT 2, NOT A PASS. An instance carrying a
# checkout-derived identity — so it is demonstrably ours — that no declared class
# claims means the registry has gone stale and this run cannot say what it just
# looked at. Could-not-judge outranks a pass, so machinery class N+1 reddens the
# census the day it first exists. The fix is a declaration in
# `scripts/lifecycle.sh`, never a widened pattern here.
#
# WHERE THIS TIGHTENS A DELEGATE, said out loud rather than discovered:
#
#   * `scripts/temporal_sweep.sh --sweep` stops an orphaned test server on the
#     strength of its PARENTAGE proof alone (parent pid 1 = the owner died).
#     Here that same process reads FOREIGN — no identity, nothing visible owns
#     it — so `sweep.sh` needs `--force-foreign` to reach it. The frame destroys
#     nothing on an absence of evidence; the delegate, which has a positive
#     death proof, still does, and the gate still runs it directly.
#   * `--only` narrows the POPULATION, including the unrecognized-shape check.
#     A class N+1 instance outside the filter is not looked at, and a narrowed
#     run therefore vouches for nothing outside its own scope — which is why the
#     unscoped census is the one that gets read. `--only` DOES NOT license a
#     `--force-foreign`: a smaller blast radius is not evidence about who owns
#     what is inside it, and the refusal below counts it as none.
#
# DECLARED BLIND SPOTS.
#
#   1. A KIND NOBODY DECLARED IS INVISIBLE. The unrecognized-shape refusal fires
#      on an instance of a KNOWN kind (a database, a schedule, an open
#      execution) that no class claims. A genuinely new kind of server-side
#      object — a Nexus endpoint, a Temporal namespace, a Redis key family — is
#      not enumerated at all until a class declares how, and nothing here can
#      notice its own silence. The registry's `enumerate` column is the map of
#      what is being asked; what is not on it is not being asked.
#   2. REDIS IS DECLARED EXEMPT, not swept, and the reason is in
#      `scripts/lifecycle.sh`'s Redis section — with the finding it produced.
#   3. LIVENESS IS ONLY EVER POSITIVE. A poller, a session, a live parent. Their
#      ABSENCE proves nothing: every checkout between two runs has no poller and
#      no session, which is exactly why `--sweep` alone will not touch a FOREIGN
#      identity however dead it looks.
#   4. THE DERIVED NAME CANNOT BE INVERTED. A checkout that MOVED on disk derives
#      a new identity and its old machinery is a true orphan — and reads FOREIGN,
#      indistinguishable from a sibling clone's. Correct, and correctly humble.
#   5. `--roots` IS DELIBERATENESS, NOT PROOF — and the refusal that requires it
#      beside `--force-foreign` buys exactly that and no more. The test is that
#      at least one root was named and is a directory; it is not, and cannot be,
#      a test that the root is the RIGHT one. So an EMPTY directory is legal
#      evidence — it says "I looked there and found no checkout", which is true,
#      and which promotes nothing — and this repository's own drive
#      (`scripts/tests/test_sweep.sh`) uses that shape deliberately, so the
#      population it acts on stays FOREIGN. At the other end, `--roots /`
#      vouches for the whole machine at the bounded scan depth and this frame
#      believes it. What the refusal closes is the operator who never thought
#      about roots at all; what it cannot close is the operator who thought
#      about them and named the wrong one. Read the census the root produced
#      before authorising anything — that reading is the actual evidence, and
#      the flag is only what forces it to exist.
#
# --assert-none TURNS THE CENSUS INTO AN ASSERTION, for a caller that has
# already decided nothing should be in scope: exit 1 when the scope is not empty,
# with everything it found printed above. It is refused with --sweep, because a
# run that destroyed and then reported on what it destroyed could always make its
# own assertion true. It fires AFTER the unrecognized refusal, because "I found
# nothing" and "I could not tell what I found" are different answers.
#
# AND IT EXEMPTS THIS CHECKOUT'S OWN WORKING SET, NAMED AND PRINTED.
#
# THE FALSE RED THIS CLOSES, which a consumer of this template met on their own
# product and not on this template. Their product had a parked deal's return
# timer open on their own queue with TWO WORKERS POLLING IT, and
# `--assert-none` failed them for it. The census had already judged that row
# correctly one line above: `live … (THIS CHECKOUT)`, then
# `kept — … it is a WORKING SET, not a leftover`. The assertion then counted the
# very row the verdict had just excused, because it counted `FOUND` and `FOUND`
# is every row the census printed. An instrument that says "this is your working
# set" and fails you for having one is an instrument a product turns off.
#
# THE EXEMPT POPULATION IS THREE CONDITIONS AT ONCE, and each is load-bearing:
#
#   1. THIS CHECKOUT OWNS IT — verdict `live` and the owner is our own derived
#      base. Another checkout's is not ours to excuse.
#   2. ITS CLASS IS DECLARED NOT DISPOSABLE — `lc_destroy_decision` hands out no
#      licence precisely because the class says the instance IS the working set
#      (a checkout database, a running execution, the queue they ride on). A
#      class declared disposable is a LEFTOVER by its own declaration and is
#      never exempt: this checkout's leaked Schedule stays a finding, which is
#      the gate's schedule leg (ADR platform-lifecycle-1).
#   3. THERE IS POSITIVE EVIDENCE IT IS IN USE RIGHT NOW — sessions on the
#      database, pollers on the queue. THE SAME positive-only liveness this
#      file's blind spot 3 declares, read at the same moment the verdict is.
#
# WHY CONDITION 3 IS NOT OPTIONAL, and it is the whole difference between this
# and a hole. Ownership alone would have exempted every open execution on this
# checkout's own queue — which is exactly the population the gate's
# open-execution leg exists to redden, and 1,061 stranded runs accumulated
# under a census that could not see them. An owned run with NOTHING POLLING is
# not a working set; it is a strand, and it is indistinguishable from a leftover
# by construction. Absence of evidence is never an exemption here, exactly as it
# is never a licence to destroy anywhere else in this file.
#
# AND IT IS PRINTED, per row and in a block before the verdict: what was
# exempted, which checkout owns it, which declaration excuses it and what the
# evidence was. An exemption nobody can read is an assertion quietly weakened,
# and the reviewer's job is to disagree with the exemption, which they can only
# do if it is on the page.
#
# EXIT (the house semantics):
#   0  the census was taken, or the sweep completed
#   1  something that should have been destroyed was not, or --assert-none found
#      something in a scope that was supposed to be empty
#   2  COULD NOT LOOK — no docker, no python3, an unknown flag, an empty
#      live-checkout set, or an UNRECOGNIZED shape. 2 outranks a pass.
set -uo pipefail

cd "$(dirname "$0")/.."

# shellcheck source=scripts/lifecycle.sh
. scripts/lifecycle.sh

SWEEP=0
FORCE_FOREIGN=0
HOT_PATH=0
PERF=0
ONLY=""
ONE_CLASS=""
ASSERT_NONE=0
USAGE="sweep.sh takes --sweep, --force-foreign (only with --roots <dir>), --hot-path, --perf, --roots <dir>, --only <prefix>, --class <name>, --assert-none, --list-classes, --registry"

cannot_look() {
    echo "!! sweep: $*" >&2
    echo "   Nothing has been judged. A census that could not look has not cleared" >&2
    echo "   anything (exit 2 outranks a pass)." >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
    --sweep) SWEEP=1 ;;
    --force-foreign) FORCE_FOREIGN=1 ;;
    --hot-path) HOT_PATH=1 ;;
    --perf) PERF=1 ;;
    --assert-none) ASSERT_NONE=1 ;;
    --roots)
        shift || true
        if [ -z "${1:-}" ]; then
            echo "!! --roots needs a directory: ${USAGE}" >&2
            exit 2
        fi
        if [ ! -d "$1" ]; then
            # Exit 2, not a shrug. A root that is not there was scanned by
            # nobody, and a live set silently missing a root is how a sibling
            # clone becomes FOREIGN when the operator believed it proven.
            echo "!! --roots ${1} is not a directory. Nothing was scanned, so no instance" >&2
            echo "   can be shown to belong to a checkout under it — and this frame must" >&2
            echo "   not be asked to reason from a search that never happened." >&2
            exit 2
        fi
        LC_ROOTS+=("$1")
        ;;
    --only)
        shift || true
        ONLY="${1:-}"
        if [ -z "$ONLY" ]; then
            # An empty --only would narrow nothing while reading as a narrowing,
            # and a scope an operator believes is small is a scope they read
            # less carefully. (It is no longer the thing that makes a
            # --force-foreign safe to aim — nothing but --roots is, and the
            # refusal below says so — but a flag that silently means its
            # opposite is a defect in its own right.)
            echo "!! --only needs an identity prefix. An empty one narrows nothing while" >&2
            echo "   reading like a narrowing, and a scope you believe is small is a scope" >&2
            echo "   you read less carefully." >&2
            exit 2
        fi
        ;;
    --class)
        shift || true
        ONE_CLASS="${1:-}"
        if [ -z "$ONE_CLASS" ]; then
            echo "!! --class needs a class name; ./scripts/sweep.sh --list-classes names them" >&2
            exit 2
        fi
        ;;
    --list-classes)
        lc_classes
        exit 0
        ;;
    --registry)
        printf '%-24s %-14s %s\n' "class" "kind" "identity · enumerate · liveness · destroy · warm · disposable"
        for name in $(lc_classes); do
            printf '%-24s %-14s %s\n' "$name" "$(lc_field "$name" 2)" "$(lc_field "$name" 3)"
            printf '%-24s %-14s   enumerate: %s\n' "" "" "$(lc_field "$name" 4)"
            printf '%-24s %-14s   liveness:  %s\n' "" "" "$(lc_field "$name" 5)"
            printf '%-24s %-14s   destroy:   %s\n' "" "" "$(lc_field "$name" 6)"
            printf '%-24s %-14s   warm:      %s\n' "" "" "$(lc_field "$name" 7)"
            printf '%-24s %-14s   disposable:%s\n' "" "" " $(lc_field "$name" 8)"
        done
        exit 0
        ;;
    *)
        echo "!! unknown argument '$1': ${USAGE}" >&2
        exit 2
        ;;
    esac
    shift
done

# --force-foreign is not a census setting. Read the census, then authorise. That
# order IS the flag (`scripts/db_sweep.sh` holds the same refusal for the same
# reason).
if [ "$FORCE_FOREIGN" -eq 1 ] && [ "$SWEEP" -eq 0 ]; then
    echo "!! --force-foreign is a licence to DESTROY and means nothing without --sweep." >&2
    echo "   Run the census first, read which instances come back FOREIGN, and only" >&2
    echo "   then decide." >&2
    exit 2
fi

# --force-foreign NEEDS --roots, AND THIS REFUSAL IS THE EXPENSIVE ONE.
#
# FOREIGN is an absence of evidence, never a licence. A run pointed at no root
# can see only this repository's own worktrees, so EVERY other checkout on the
# machine — a sibling clone, a verifier's tree, another agent's rung — reads
# FOREIGN, and `--force-foreign` then reads that silence as permission for all of
# them. This was a WARNING here until it was a loss: one unrooted run on a
# consumer's box reported `1709 found · 1472 destroyed` and took a live builder's
# checkout database with it. A warning is a sentence somebody reads afterwards.
#
# BEFORE ANYTHING IS LOOKED AT, deliberately: no scope banner, no census, no
# docker, no registry — so the transcript of a refused run cannot be mistaken for
# a run that judged something, and so the refusal cannot depend on a server being
# reachable. It also fires AFTER the --sweep refusal above, so the narrower
# complaint (a licence with nothing to license) still comes first.
#
# --only DOES NOT LIFT IT. A prefix says where to look; it never says who owns
# what is found there. The old reasoning — that `--only` made a --force-foreign
# safe to aim — is what this refusal replaces: it made it SMALLER, which is not
# the same thing, and the operator still had to be right about a population they
# had been given no evidence about.
if [ "$FORCE_FOREIGN" -eq 1 ] && [ "${#LC_ROOTS[@]}" -eq 0 ]; then
    echo "!! REFUSED: --force-foreign needs --roots <dir>, and this run was given none." >&2
    echo "   Nothing was destroyed and nothing was looked at." >&2
    echo "" >&2
    echo "   FOREIGN means this run could not say whose a thing is — an absence of" >&2
    echo "   evidence, never a licence. With no --roots, every checkout of this" >&2
    echo "   repository that is not one of THIS one's worktrees is FOREIGN: a sibling" >&2
    echo "   clone, a verifier's tree, another agent's rung. One such run destroyed" >&2
    echo "   1,472 databases in a single pass, a live builder's among them." >&2
    echo "" >&2
    echo "   Point --roots at wherever clones of this repository live (repeatable)," >&2
    echo "   read the census it gives you, and only then authorise:" >&2
    echo "     ./scripts/sweep.sh --roots <dir>                        the census, first" >&2
    echo "     ./scripts/sweep.sh --sweep --force-foreign --roots <dir>" >&2
    echo "" >&2
    echo "   --only <prefix> does not stand in for it: narrowing is not evidence. It" >&2
    echo "   says where to look, never who owns what is found there." >&2
    exit 2
fi

# --assert-none ASKS A QUESTION; --sweep ANSWERS ONE. A run that both destroyed
# and then reported on what it had destroyed would always be able to make its
# own assertion true, which is not an assertion at all.
if [ "$ASSERT_NONE" -eq 1 ] && [ "$SWEEP" -eq 1 ]; then
    echo "!! --assert-none and --sweep are opposites. --assert-none asks whether anything" >&2
    echo "   is in scope and fails when something is; --sweep destroys what is in scope," >&2
    echo "   and would make the answer true by acting on it. Run the assertion, read it," >&2
    echo "   then sweep." >&2
    exit 2
fi

lc_registry_check || cannot_look "the lifecycle registry is malformed — see above"

if [ -n "$ONE_CLASS" ]; then
    if ! lc_field "$ONE_CLASS" 1 >/dev/null; then
        echo "!! no class named '${ONE_CLASS}'. ./scripts/sweep.sh --list-classes names them." >&2
        exit 2
    fi
fi

command -v python3 >/dev/null 2>&1 ||
    cannot_look "no python3 on PATH; the Temporal scans parse the CLI's JSON with it"
command -v docker >/dev/null 2>&1 ||
    cannot_look "no docker on PATH; both servers are asked inside the compose stack"

# THIS CHECKOUT'S OWN IDENTITY — the one thing `--sweep` alone vouches for.
#
# THE DERIVATION, NOT `$DATABASE_NAME`. `scripts/db.sh` rule 1 says an
# exported `DATABASE_NAME` WINS over the derivation, which is the documented
# escape and which CI takes: `.github/workflows/ci.yml` pins `djb_main`. This
# value is compared — at `judge` and again at `still_licensed` — against what
# `lc_owning_checkout` returns, and that is always a DERIVED base. Read off the
# pin, the two can never be equal on a pinned run, so `mine` was permanently 0
# there and the `live … (THIS CHECKOUT)` line could not fire at all. It also let
# the pin decide whose machinery `--sweep` alone reaps: an operator who exported
# another checkout's derived base would have handed this broom that checkout's
# disposables. Ownership here is the forward derivation and nothing else, which
# is the same sentence `scripts/db.sh` makes one layer down: a pin is a name to
# connect with, never a claim about who owns what.
#
# Nothing is lost on a pinned run. The pinned name's own machinery is not
# derivation-shaped, so every instance of it reads REFUSED and is protected by
# the refusal (`case_a_refused_shape_survives_force_foreign` drives that).
OUR_BASE="$(db_name)"
db_valid_name "$OUR_BASE" || cannot_look "this checkout's derived identity (${OUR_BASE}) is not a name"

lc_load_live_bases
if [ "${#LC_LIVE_BASES[@]}" -eq 0 ]; then
    # Nothing to derive liveness FROM is not "nothing is alive". It is the frame
    # unable to look, and that is exit 2, before anything is destroyed.
    cannot_look "git worktree list named no checkout, so no instance can be shown to have one.
   Liveness is derived by hashing checkout paths this run can see; with none to
   hash, every identity would read FOREIGN and --force-foreign would take the
   machine. That is the one answer it must never give by accident."
fi

# --- the scope, said before anything is judged --------------------------------

echo "sweep: the checkout-machinery census (scripts/lifecycle.sh declares the classes)"
echo "  this checkout   ${OUR_BASE}"
if [ "${DATABASE_NAME}" != "${OUR_BASE}" ]; then
    # Said, not silently reconciled: a reader whose environment pins one name and
    # whose census names another would otherwise think the instrument lost track
    # of them.
    echo "  note            DATABASE_NAME is pinned to ${DATABASE_NAME}; ownership here is"
    echo "                  the DERIVATION and never the pin, so the pinned name's own"
    echo "                  machinery reads REFUSED and is protected by that refusal"
fi
echo "  checkouts       ${#LC_LIVE_BASES[@]} this run can see (the live set every verdict is read against)"
if [ "${#LC_ROOTS[@]}" -gt 0 ]; then
    for root in "${LC_ROOTS[@]}"; do
        echo "  scanned         ${root} (depth ${LC_ROOT_SCAN_DEPTH})"
    done
else
    echo "  scanned         nothing — only this repository's own worktrees. A sibling"
    echo "                  clone elsewhere on this machine reads FOREIGN until --roots"
    echo "                  <dir> is pointed at it."
fi
[ -n "$ONLY" ] && echo "  --only          ${ONLY} — nothing outside this identity prefix was looked at"
[ -n "$ONE_CLASS" ] && echo "  --class         ${ONE_CLASS} — no other class was looked at"
if [ "$SWEEP" -eq 1 ]; then
    echo "  MODE            SWEEP — this checkout's own machinery will be destroyed"
    [ "$FORCE_FOREIGN" -eq 1 ] &&
        echo "                  --force-foreign — FOREIGN instances too, printed first"
    [ "$HOT_PATH" -eq 0 ] &&
        echo "  note            hot-path probe caches are shown but NOT swept (--hot-path)"
    [ "$PERF" -eq 0 ] &&
        echo "  note            seeded perf worlds are shown but NOT swept (--perf)"
else
    echo "  MODE            census — nothing is destroyed"
fi
# The WARNING that used to stand here is gone, and its absence is the fix: the
# combination it described — --force-foreign with no --roots — is now REFUSED at
# flag parse, above, long before this line. A warning printed on the way past is
# read after the destroy; a refusal is read instead of it.
echo ""

# --- the walk -----------------------------------------------------------------

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

FOUND=0
DESTROYED=0
LEFT=0
FOREIGN_COUNT=0
UNRECOGNIZED=0
FAILED=0
WOULD=0
# The --assert-none exemption: this checkout's own working set, in use right now.
# See --assert-none in the header for the three conditions and why the third one
# is what keeps this from being a hole.
EXEMPT=0
: >"${WORK}/exempt"

wanted_class() {
    [ -z "$ONE_CLASS" ] || [ "$ONE_CLASS" = "$1" ]
}

# What the clocks said about the row about to be judged. Set by the caller
# immediately before `judge`, printed by `judge` under the verdict, and cleared
# there — never read anywhere else.
EVIDENCE=""
_EV=""
say_evidence() {
    [ -n "$_EV" ] || return 0
    echo "                     ${_EV}"
}

# THE LIVE-USE COUNT the verdict was computed from, and the noun for it. Set by
# the caller immediately before `judge`, exactly as `EVIDENCE` is, and consumed
# and cleared in the same move for the same reason: a caller that forgets to set
# one must not be able to excuse this row on the previous row's evidence.
#
# IT IS THE COUNT, NOT THE PHRASE. `EVIDENCE` above is a sentence for a human;
# this is the number `lc_verdict` was handed, and the --assert-none exemption
# turns on it being POSITIVE. Two fields rather than one because the noun
# differs by kind — sessions on a database, pollers on a queue — and an
# exemption that could not say WHICH evidence it rested on would be an exemption
# nobody can check.
LIVE_EVIDENCE=0
LIVE_EVIDENCE_WHAT=""
_LIVE=0
_LIVE_WHAT=""

# Every queue's `<pollers>|<backlog>|<backlog age>`, asked once. Two hundred open
# executions on twenty queues is twenty questions, not two hundred:
# `DescribeTaskQueue` is a round trip into the compose container, and a census
# slow enough to be skipped is a census that reports nothing.
#
# ONE ROUND TRIP CARRIES ALL THREE NUMBERS. The liveness read and the
# harm read come out of the same `DescribeTaskQueue` answer, so adding the
# backlog to the census cost no extra call — and asking twice would have meant
# two answers about one queue taken a second apart.
mkdir -p "${WORK}/pollers"
stats_for() {
    local queue="$1" safe file
    safe="$(printf '%s' "$queue" | tr -c 'A-Za-z0-9_.-' '_')"
    file="${WORK}/pollers/${safe}"
    [ -f "$file" ] || lc_queue_stats "$queue" >"$file" 2>/dev/null
    cat "$file"
}

# The liveness field, and ONLY that field, for the verdict to read. A backlog is
# not evidence of use — see `lifecycle.sh::lc_queue_stats` — and separating the
# two reads here is what keeps a piling-up queue from ever being mistaken for a
# worked one.
pollers_for() {
    local stats
    stats="$(stats_for "$1")"
    printf '%s' "${stats%%|*}"
}

# `N open run(s), oldest X` for one queue, off the ages accumulated while the
# execution scan was read. Silent about what it did not look at: when the
# open-execution scan did not run, the honest phrase is that nobody counted.
open_runs_phrase() {
    local queue="$1" count oldest
    count="$(awk -F'\t' -v q="$queue" '$1 == q {n++} END {print n + 0}' "${WORK}/exec_ages")"
    if [ "$count" -eq 0 ]; then
        printf 'no open run on it'
        return 0
    fi
    oldest="$(awk -F'\t' -v q="$queue" '$1 == q && $2 + 0 > m {m = $2 + 0} END {print m + 0}' "${WORK}/exec_ages")"
    printf '%s open run(s), oldest %s' "$count" "$(lc_duration "$oldest")"
}

# `pollers N · backlog B (oldest A)` — the queue's state, as one phrase, for the
# evidence line of every row that names it.
queue_phrase() {
    local stats pollers backlog age rest
    stats="$(stats_for "$1")"
    pollers="${stats%%|*}"
    rest="${stats#*|}"
    backlog="${rest%%|*}"
    age="${rest#*|}"
    if [ "${pollers:-0}" != "0" ]; then
        printf 'pollers %s' "$pollers"
        return 0
    fi
    if [ "${backlog:-0}" = "0" ]; then
        printf 'NOTHING POLLING, backlog empty'
        return 0
    fi
    if [ "${age:--1}" = "-1" ]; then
        # The server gave a depth and no age. Said as two facts, because
        # `backed up unknown` reads like an age and is not one.
        printf 'NOTHING POLLING, %s task(s) backed up, age not reported' "$backlog"
        return 0
    fi
    printf 'NOTHING POLLING, %s task(s) backed up %s' "$backlog" "$(lc_duration "$age")"
}

# --only, applied to the IDENTITY and never to the display string: a workflow id
# names a tenant and a noun, and matching a prefix against one of those would
# narrow by something that is not a checkout at all.
# `lc_queue_base` without the subshell: it ASSIGNS `identity` rather than
# printing it, because a command substitution forks and this runs once per open
# execution — 136 of them on this machine on a quiet evening. Same arithmetic as
# the frame's function, which stays the readable one for callers that want a
# value; when the two ever disagree the frame's is right.
identity_from_queue() {
    case "${1:-}" in
    djb-*) identity="djb_${1#djb-}" ;;
    *) identity="" ;;
    esac
}

in_scope() {
    local identity="${1:-}"
    [ -n "$ONLY" ] || return 0
    [ -n "$identity" ] || return 1
    case "$identity" in
    "$ONLY"*) return 0 ;;
    esac
    return 1
}

# A class's warm flag, and whether its gate was opened this run.
warm_open() {
    case "$1" in
    hot-path-cache) [ "$HOT_PATH" -eq 1 ] ;;
    perf-world) [ "$PERF" -eq 1 ] ;;
    *) return 0 ;;
    esac
}

warm_flag_of() {
    case "$1" in
    hot-path-cache) printf -- '--hot-path' ;;
    perf-world) printf -- '--perf' ;;
    esac
}

# The belt's own question, asked at the act: from ownership derived RIGHT NOW,
# does the one decision function still hand out the same licence?
#
#   $1 class · $2 identity · $3 the licence the caller is about to act on
#
# ONE DECLARED EXEMPTION: `test-server-process` has no checkout identity at all
# — the registry's identity column says so in as many words — so there is
# nothing here to re-derive. Its wall is parentage (parent pid 1 = the owner
# died), and `scripts/temporal_sweep.sh` re-checks that itself in its own kill
# path, which is where that check belongs.
still_licensed() {
    local class="$1" identity="$2" licence="$3" verdict_now mine_now owner_now
    [ "$class" = "test-server-process" ] && return 0
    owner_now="$(lc_owning_checkout "$identity" || true)"
    mine_now=0
    [ -n "$owner_now" ] && [ "$owner_now" = "$OUR_BASE" ] && mine_now=1
    # Evidence 0 deliberately: an IN USE instance never reaches the act (it
    # returns at the verdict), so the only thing being re-derived here is
    # OWNERSHIP, which is the half the breach got wrong.
    verdict_now="$(lc_verdict "$identity" 0)"
    case "$(lc_destroy_decision "$class" "$verdict_now" "$mine_now")" in
    "${licence}|"*) return 0 ;;
    esac
    return 1
}

# One row of the census, and the decision that follows from it.
#
#   $1 class · $2 verdict · $3 identity · $4 display · $5 owner (or "")
#   $6.. the destroy command
judge() {
    local class="$1" verdict="$2" identity="$3" display="$4" owner="$5"
    shift 5
    FOUND=$((FOUND + 1))
    local mine=0
    [ -n "$owner" ] && [ "$owner" = "$OUR_BASE" ] && mine=1

    # THE EVIDENCE LINE, TAKEN AND CLEARED IN ONE MOVE. A caller sets
    # `EVIDENCE` for the row it is about to judge — what the clocks said about
    # that schedule, that run, that queue. It is consumed HERE and blanked
    # immediately, so a caller that forgets to set one cannot print the previous
    # row's evidence under this row's name, which is the one way a dating
    # instrument could lie about the thing it is dating.
    _EV="$EVIDENCE"
    EVIDENCE=""

    # The live-use count, taken and cleared in the same one move and for the same
    # reason. Sanitised here rather than trusted: a non-numeric value must read
    # as NO evidence, because this number is what the --assert-none exemption
    # turns on and "I could not read the evidence" is not "it is in use".
    _LIVE="$LIVE_EVIDENCE"
    _LIVE_WHAT="$LIVE_EVIDENCE_WHAT"
    LIVE_EVIDENCE=0
    LIVE_EVIDENCE_WHAT=""
    case "${_LIVE:-}" in
    '' | *[!0-9]*) _LIVE=0 ;;
    esac
    [ -n "$_LIVE_WHAT" ] || _LIVE_WHAT="live-use evidence"

    # THE ONE DECISION. Asked here, once, and consulted again — not
    # re-derived — at the act. It used to be implicit: the `live` arm printed a
    # line and fell out of the `case` into the destroy path, so "this checkout
    # owns it" silently meant "destroy it", including when the thing owned was
    # the checkout's working database or a workflow that was running.
    local decision licence why
    decision="$(lc_destroy_decision "$class" "$verdict" "$mine")"
    licence="${decision%%|*}"
    why="${decision#*|}"
    # A class may declare NO destroy verb (`task-queue`: a queue is not an
    # object). Known here, before anything is offered, so such an instance never
    # appears in the would-destroy list promising something no verb can deliver.
    local has_verb=1
    [ "$#" -eq 0 ] && has_verb=0

    case "$verdict" in
    REFUSED)
        echo "  REFUSED  ${display}"
        say_evidence
        echo "                     ${identity:-(no identity)} is not something this repository"
        echo "                     derives, so nothing here can say whose it is"
        LEFT=$((LEFT + 1))
        return 0
        ;;
    "IN USE")
        echo "  IN USE   ${display} — in use right now, left alone"
        say_evidence
        LEFT=$((LEFT + 1))
        return 0
        ;;
    live)
        if [ "$mine" -ne 1 ]; then
            echo "  live     ${display} — ${owner} is a checkout this run can see; never touched"
            say_evidence
            LEFT=$((LEFT + 1))
            return 0
        fi
        echo "  live     ${display} — ${owner} (THIS CHECKOUT)"
        say_evidence
        # NO FALL-THROUGH. Owning a thing is not a licence to destroy it: the
        # class has to have declared it disposable as well, and most have not.
        if [ "$licence" != "own" ]; then
            echo "           kept — ${why}"
            # THE --assert-none EXEMPTION, recorded exactly here and nowhere
            # else: this is the one branch that has already said, in the line
            # above, that the instance IS a working set. The third condition —
            # positive evidence it is in use right now — is asked here, because
            # an owned instance with NOTHING using it is a strand and the whole
            # point of the assertion (see --assert-none in the header).
            if [ "$_LIVE" -gt 0 ]; then
                EXEMPT=$((EXEMPT + 1))
                printf '%s\t%s\t%s %s\n' "$class" "$display" "$_LIVE" "$_LIVE_WHAT" >>"${WORK}/exempt"
                if [ "$ASSERT_NONE" -eq 1 ]; then
                    echo "           exempt from --assert-none — in use right now (${_LIVE} ${_LIVE_WHAT})"
                fi
            elif [ "$ASSERT_NONE" -eq 1 ]; then
                # Said out loud, because this is the row a reader will expect to
                # have been excused and it was not. The reason is the whole
                # difference between the exemption and a hole.
                echo "           NOT exempt from --assert-none — nothing is using it right now,"
                echo "           and an owned instance nobody is using is a strand, not a working set"
            fi
            LEFT=$((LEFT + 1))
            return 0
        fi
        ;;
    FOREIGN)
        FOREIGN_COUNT=$((FOREIGN_COUNT + 1))
        # ALWAYS PRINTED, including on the run about to destroy it: the header
        # promises this frame names what it destroys BEFORE destroying it, and a
        # line after the fact is not that promise.
        echo "  FOREIGN  ${display}"
        say_evidence
        echo "                     no checkout this run could see derives ${identity}, and"
        echo "                     nothing proves it in use. It may be a sibling clone's,"
        echo "                     another machine's, or a dead checkout's — this run"
        echo "                     cannot tell which."
        if [ "$has_verb" -eq 0 ]; then
            echo "                     nothing to destroy: this class declares no destroy verb"
            LEFT=$((LEFT + 1))
            return 0
        fi
        # The warm-cache fence applies to a FOREIGN instance too, and it has to be
        # said HERE — a FOREIGN warm cache would otherwise be offered to
        # --force-foreign with no mention that it is a warm cache at all, and the
        # promise is that warm is never reachable by accident.
        if ! warm_open "$class"; then
            echo "  warm     ${display} — ${class}; --sweep --force-foreign --roots <dir> $(warm_flag_of "$class") destroys it"
            LEFT=$((LEFT + 1))
            return 0
        fi
        if [ "$SWEEP" -eq 0 ] || [ "$FORCE_FOREIGN" -eq 0 ]; then
            echo "                     --roots <dir> to prove it live; --sweep --force-foreign to destroy (also needs --roots)"
            WOULD=$((WOULD + 1))
            printf 'FOREIGN\t%s\t%s\n' "$class" "$display" >>"${WORK}/would"
            LEFT=$((LEFT + 1))
            return 0
        fi
        echo "                     --force-foreign given: DESTROYING it on the operator's word"
        ;;
    esac

    # The warm-cache fence, after the verdict and before any destroy: a warm
    # cache is not a leak, and one dropped out from under a running gate fails
    # that gate.
    if ! warm_open "$class"; then
        echo "  warm     ${display} — ${class}; --sweep $(warm_flag_of "$class") destroys it"
        LEFT=$((LEFT + 1))
        return 0
    fi

    if [ "$has_verb" -eq 0 ]; then
        # `task-queue`: a queue is not an object, and saying so is more honest
        # than an offer nothing can keep.
        echo "           (no destroy verb — a task queue is gone when its last schedule"
        echo "            and execution are; see the registry)"
        LEFT=$((LEFT + 1))
        return 0
    fi

    if [ "$SWEEP" -eq 0 ]; then
        WOULD=$((WOULD + 1))
        printf 'own\t%s\t%s\n' "$class" "$display" >>"${WORK}/would"
        echo "           --sweep would destroy this"
        return 0
    fi
    # THE BELT. A candidate list is not a licence. Everything above
    # decided from a verdict computed some lines earlier; this asks the ONE
    # decision function again, from ownership re-derived here and now, and
    # refuses if the answer is not the same licence it acted on. It costs
    # nothing — `lc_verdict` reads the live-base array and forks no process —
    # and it is the check that would have turned the breach into a loud refusal
    # instead of two destroyed rows.
    if ! still_licensed "$class" "$identity" "$licence"; then
        echo "!! REFUSED AT THE ACT: ${display}" >&2
        echo "   The candidate list said this was destroyable as '${licence}', and asking" >&2
        echo "   again at the moment of destruction says it is not. That disagreement is" >&2
        echo "   itself the finding: nothing is destroyed on a stale answer." >&2
        FAILED=$((FAILED + 1))
        return 0
    fi
    if "$@" >"${WORK}/destroy.log" 2>&1; then
        echo "  DESTROYED ${display}"
        DESTROYED=$((DESTROYED + 1))
    else
        echo "  FAILED   ${display} — the destroy verb refused:"
        sed 's/^/                     | /' "${WORK}/destroy.log" | tail -6
        FAILED=$((FAILED + 1))
    fi
}

# An instance of a known kind that carries a checkout-derived identity and that
# no class claims. The registry has gone stale; this run cannot say what it is
# looking at, and that is exit 2 rather than a pass.
unrecognized() {
    local kind="$1" instance="$2"
    UNRECOGNIZED=$((UNRECOGNIZED + 1))
    echo "!! UNRECOGNIZED ${kind}: ${instance}" >&2
    echo "   It carries a checkout-derived identity, so this repository made it — and no" >&2
    echo "   class in scripts/lifecycle.sh claims it. Declare the class there (name," >&2
    echo "   identity, enumerate, liveness, destroy, warm); do not widen a pattern." >&2
}

# --- kind: database ------------------------------------------------------------

# The database classes, in the order a census prints them. `migration-template`
# is first because it is the most specific shape (specificity order — see the
# registry's header), and it is HERE AT ALL because `lc_class_of` claiming a
# shape is not the same thing as a census showing it: a class the registry knows
# and this list does not is invisible in every transcript while being exempt
# from the UNRECOGNIZED check that exists to catch exactly that. It was in that
# state for the length of one probe, which is how the line got written.
DB_CLASSES="migration-template checkout-database test-database hot-path-cache perf-world restore-drill-database"

DB_WANTED=0
for class in $DB_CLASSES; do
    wanted_class "$class" && DB_WANTED=1
done
if [ "$DB_WANTED" -eq 1 ]; then
    : >"${WORK}/databases"
    if ! lc_scan_databases >"${WORK}/databases" 2>"${WORK}/databases.err"; then
        sed 's/^/   | /' "${WORK}/databases.err" >&2
        cannot_look "pg_catalog could not be read; the database classes were not censused"
    fi

    # THE UNRECOGNIZED PASS RUNS ONCE, OVER THE WHOLE KIND, and before any class
    # is printed — not inside the per-class loop, where it would fire five times
    # for one stale shape, and would not fire at all under a `--class` that
    # happens to exclude whichever class was hosting the check.
    : >"${WORK}/unclaimed"
    while IFS='|' read -r name sessions; do
        [ -n "${name:-}" ] || continue
        in_scope "${name#test_}" || continue
        lc_class_of database "$name" >/dev/null && continue
        if lc_derived_shape "$name"; then
            unrecognized database "$name"
        else
            # NOT unrecognized: it carries no checkout-derived identity at all,
            # so this repository did not derive it and nothing here reasons about
            # it. It is still PRINTED — a census that silently omits what it
            # refused is a census whose scope has to be remembered.
            printf '%s\n' "$name" >>"${WORK}/unclaimed"
        fi
    done <"${WORK}/databases"

    for class in $DB_CLASSES; do
        wanted_class "$class" || continue
        echo "class: ${class} — $(lc_field "$class" 3)"
        shown=0
        while IFS='|' read -r name sessions; do
            [ -n "${name:-}" ] || continue
            # `--only` FIRST, and only then the class question. Attribution is
            # the expensive half — nine claim functions per name, five times over
            # for the five database classes — and a narrowed run has no business
            # paying it for names it is not going to print. Pure ordering: both
            # tests read the name and nothing else.
            identity="${name#test_}"
            in_scope "$identity" || continue
            claimed="$(lc_class_of database "$name" || true)"
            [ "$claimed" = "$class" ] || continue
            shown=1
            verdict="$(lc_verdict "$identity" "${sessions:-0}")"
            owner="$(lc_owning_checkout "$identity" || true)"
            # The same count the verdict was computed from, handed to `judge` for
            # the --assert-none exemption. Set beside the verdict on purpose:
            # two reads a few lines apart is two answers about one instance.
            LIVE_EVIDENCE="${sessions:-0}"
            LIVE_EVIDENCE_WHAT="session(s) on it"
            case "$class" in
            test-database)
                judge "$class" "$verdict" "$identity" "$name" "$owner" \
                    ./scripts/db_sweep.sh --sweep --name "$name"
                ;;
            hot-path-cache)
                judge "$class" "$verdict" "$identity" "$name" "$owner" \
                    ./scripts/db_sweep.sh --sweep --hot-path --name "$name"
                ;;
            perf-world)
                judge "$class" "$verdict" "$identity" "$name" "$owner" \
                    ./scripts/db_sweep.sh --sweep --perf --name "$name"
                ;;
            *)
                judge "$class" "$verdict" "$identity" "$name" "$owner" \
                    db_query 'DROP DATABASE :"name"' -v name="$name"
                ;;
            esac
        done <"${WORK}/databases"
        [ "$shown" -eq 0 ] && echo "  (none)"
        echo ""
    done
    if [ -z "$ONE_CLASS" ] && [ -s "${WORK}/unclaimed" ]; then
        echo "outside every declared class — never touched, however old they look"
        while IFS= read -r name; do
            [ -n "$name" ] || continue
            FOUND=$((FOUND + 1))
            LEFT=$((LEFT + 1))
            echo "  REFUSED  ${name} — no _<8 hex> tail, so it is not a name this"
            echo "                     repository derives and no class claims it"
        done <"${WORK}/unclaimed"
        echo ""
    fi
fi

# --- kind: schedule ------------------------------------------------------------

: >"${WORK}/queues"
: >"${WORK}/sched_queues"
: >"${WORK}/exec_ages"
if wanted_class schedule || wanted_class task-queue; then
    : >"${WORK}/schedules"
    if ! lc_scan_schedules >"${WORK}/schedules" 2>"${WORK}/schedules.err"; then
        sed 's/^/   | /' "${WORK}/schedules.err" >&2
        cannot_look "temporal schedule list could not be read; the schedule class was not censused"
    fi
fi
# What a schedule is DOING, as one phrase: when it last fired, what became of
# that action, when it fires next, and the state of the queue it fires into.
# This is the sentence a per-row view could not say by itself.
schedule_phrase() {
    local last="$1" nxt="$2" wtype="$3" status="$4" queue="$5" phrase
    phrase="starts ${wtype}"
    if [ "$last" != "-1" ]; then
        phrase="${phrase} · last fired $(lc_duration "$last") ago"
        [ "$status" != "-" ] && phrase="${phrase} (${status})"
    else
        phrase="${phrase} · no fire this run could date"
    fi
    if [ "$nxt" != "-1" ] && [ "$nxt" -ge 0 ] 2>/dev/null; then
        phrase="${phrase} · fires again in $(lc_duration "$nxt")"
    fi
    printf '%s · queue %s' "$phrase" "$(queue_phrase "$queue")"
}

if wanted_class schedule; then
    echo "class: schedule — $(lc_field schedule 3)"
    shown=0
    while IFS="$(printf '\t')" read -r sid last nxt wtype status; do
        [ -n "$sid" ] || continue
        if ! lc_claim_schedule "$sid"; then
            # A schedule id with no `djb-` queue in it was not keyed to a checkout
            # at all; it is out of the population, not an unrecognized member of it.
            in_scope "" || continue
            printf '  REFUSED  %s\n' "$sid"
            echo "                     its id names no checkout-derived task queue"
            FOUND=$((FOUND + 1))
            LEFT=$((LEFT + 1))
            shown=1
            continue
        fi
        queue="${sid##*:}"
        printf '%s\n' "$queue" >>"${WORK}/queues"
        printf '%s\n' "$queue" >>"${WORK}/sched_queues"
        identity_from_queue "$queue"
        in_scope "$identity" || continue
        shown=1
        pollers="$(pollers_for "$queue")"
        verdict="$(lc_verdict "$identity" "${pollers:-0}")"
        owner="$(lc_owning_checkout "$identity" || true)"
        EVIDENCE="$(schedule_phrase "${last:--1}" "${nxt:--1}" "${wtype:--}" "${status:--}" "$queue")"
        LIVE_EVIDENCE="${pollers:-0}"
        LIVE_EVIDENCE_WHAT="poller(s) on ${queue}"
        judge schedule "$verdict" "$identity" "$sid" "$owner" \
            lc_temporal schedule delete --schedule-id "$sid"
    done <"${WORK}/schedules"
    [ "$shown" -eq 0 ] && echo "  (none)"
    echo ""
elif wanted_class task-queue; then
    while IFS="$(printf '\t')" read -r sid _rest; do
        case "$sid" in
        *:djb-*)
            printf '%s\n' "${sid##*:}" >>"${WORK}/queues"
            printf '%s\n' "${sid##*:}" >>"${WORK}/sched_queues"
            ;;
        esac
    done <"${WORK}/schedules"
fi

# --- kind: open-execution ------------------------------------------------------

if wanted_class open-execution || wanted_class task-queue; then
    : >"${WORK}/executions"
    if ! lc_scan_open_executions >"${WORK}/executions" 2>"${WORK}/executions.err"; then
        sed 's/^/   | /' "${WORK}/executions.err" >&2
        cannot_look "temporal workflow list could not be read; the open-execution class was not censused"
    fi
    while IFS="$(printf '\t')" read -r queue wid age wtype; do
        # `-` is the enumerator's sentinel for an execution with no task queue;
        # it is not a queue and must not join the task-queue population.
        case "${queue:-}" in djb-*) printf '%s\n' "$queue" >>"${WORK}/queues" ;; esac
        # The per-queue roll-up's raw material: how many runs are open on this
        # queue and how old the oldest of them is. Accumulated HERE, while the
        # scan is being read, so the roll-up costs no second pass and no second
        # round trip.
        case "${queue:-}" in
        djb-*)
            printf '%s\t%s\n' "$queue" "${age:--1}" >>"${WORK}/exec_ages"
            ;;
        esac
    done <"${WORK}/executions"
fi
if wanted_class open-execution; then
    echo "class: open-execution — $(lc_field open-execution 3)"
    shown=0
    while IFS="$(printf '\t')" read -r queue wid age wtype; do
        [ -n "${wid:-}" ] || continue
        if ! lc_claim_open_execution "${queue:-}"; then
            in_scope "" || continue
            printf '  REFUSED  %s (queue %s)\n' "$wid" "${queue:-none}"
            echo "                     its task queue is not one this repository derives"
            FOUND=$((FOUND + 1))
            LEFT=$((LEFT + 1))
            shown=1
            continue
        fi
        identity_from_queue "$queue"
        in_scope "$identity" || continue
        shown=1
        pollers="$(pollers_for "$queue")"
        verdict="$(lc_verdict "$identity" "${pollers:-0}")"
        owner="$(lc_owning_checkout "$identity" || true)"
        EVIDENCE="${wtype:--} · running $(lc_duration "${age:--1}") · queue $(queue_phrase "$queue")"
        LIVE_EVIDENCE="${pollers:-0}"
        LIVE_EVIDENCE_WHAT="poller(s) on ${queue}"
        judge open-execution "$verdict" "$identity" "${wid} (queue ${queue})" "$owner" \
            lc_temporal workflow terminate --workflow-id "$wid" --reason "scripts/sweep.sh: the checkout that owns ${queue} is gone"
    done <"${WORK}/executions"
    [ "$shown" -eq 0 ] && echo "  (none)"
    echo ""
fi

# --- kind: task-queue ----------------------------------------------------------
#
# Temporal exposes no ListTaskQueues, so the population is derived by REFERENCE:
# the queues named by the schedules and the executions above. A queue nothing
# references is already gone, which is why the class declares no destroy verb.

if wanted_class task-queue; then
    echo "class: task-queue — $(lc_field task-queue 3)"
    shown=0
    if [ -s "${WORK}/queues" ]; then
        while IFS= read -r queue; do
            [ -n "$queue" ] || continue
            identity_from_queue "$queue"
            in_scope "$identity" || continue
            shown=1
            pollers="$(pollers_for "$queue")"
            verdict="$(lc_verdict "$identity" "${pollers:-0}")"
            owner="$(lc_owning_checkout "$identity" || true)"
            EVIDENCE="$(queue_phrase "$queue") · $(open_runs_phrase "$queue")"
            LIVE_EVIDENCE="${pollers:-0}"
            LIVE_EVIDENCE_WHAT="poller(s) on it"
            judge task-queue "$verdict" "$identity" "$queue" "$owner"
        done < <(sort -u "${WORK}/queues")
    fi
    [ "$shown" -eq 0 ] && echo "  (none)"
    echo ""
fi

# --- the graveyard roll-up ----------------------------------------------
#
# THE ROWS ABOVE ARE ONE INSTANCE EACH; THIS IS THE SHAPE THEY MAKE. This was
# not found by reading a row — every one of those schedules had been printing
# FOREIGN correctly for days. It was found by noticing that FIFTEEN of them
# pointed at queues NOTHING POLLS, that runs were piling up behind them, and
# that they were all still firing. That is a fact about the population, so the
# census says it in one place instead of leaving it to be assembled by eye.
#
# WHAT COUNTS AS STRANDED, and it is deliberately the narrow reading: a queue
# this run saw named, with ZERO POLLERS, THAT NO VISIBLE CHECKOUT OWNS. Pollers
# are the one piece of positive evidence the frame trusts, and their absence is
# all that is being reported — never "old", never "probably dead".
#
# THE SECOND HALF OF THAT TEST IS WHAT KEEPS THIS QUIET. A `live` queue has no
# poller most of the time: every checkout between two runs looks exactly like
# this, and its own worker's startup self-clean covers it (ADR
# platform-lifecycle-1). Reporting those would put a paragraph headed NOTHING IS
# POLLING into every gate run on this machine, and an alarm that is normally
# true is an alarm people learn to skip. The graveyard is what NOTHING LIVING
# CAN CLEAN — so the roll-up is exactly the FOREIGN and REFUSED residue, and the
# verdict stays printed beside every row.
#
# IT NEEDS BOTH TEMPORAL SCANS, so it prints only on a run that took both — the
# unnarrowed census, or `--class task-queue`. A roll-up assembled from half the
# population would be a number nobody could act on, and a silent one is worse
# than an absent one.
if [ -z "$ONE_CLASS" ] || [ "$ONE_CLASS" = "task-queue" ]; then
    STRANDED_QUEUES=0
    STRANDED_SCHEDULES=0
    STRANDED_RUNS=0
    STRANDED_OLDEST=-1
    : >"${WORK}/stranded"
    if [ -s "${WORK}/queues" ]; then
        while IFS= read -r queue; do
            [ -n "$queue" ] || continue
            identity_from_queue "$queue"
            in_scope "$identity" || continue
            [ "$(pollers_for "$queue")" = "0" ] || continue
            stranded_verdict="$(lc_verdict "$identity" 0)"
            # A queue a visible checkout derives is not a graveyard: that
            # checkout is there to clean up after itself, and it is not mine to
            # report as abandoned.
            [ "$stranded_verdict" != "live" ] || continue
            sched_count="$(awk -v q="$queue" '$0 == q {n++} END {print n + 0}' "${WORK}/sched_queues")"
            run_count="$(awk -F'\t' -v q="$queue" '$1 == q {n++} END {print n + 0}' "${WORK}/exec_ages")"
            oldest="$(awk -F'\t' -v q="$queue" '$1 == q && $2 + 0 > m {m = $2 + 0} END {print m + 0}' "${WORK}/exec_ages")"
            STRANDED_QUEUES=$((STRANDED_QUEUES + 1))
            STRANDED_SCHEDULES=$((STRANDED_SCHEDULES + sched_count))
            STRANDED_RUNS=$((STRANDED_RUNS + run_count))
            [ "$oldest" -gt "$STRANDED_OLDEST" ] && STRANDED_OLDEST="$oldest"
            printf '%s\t%s\t%s\t%s\t%s\n' \
                "$stranded_verdict" "$queue" "$sched_count" "$run_count" "$oldest" \
                >>"${WORK}/stranded"
        done < <(sort -u "${WORK}/queues")
    fi
    echo "stranded: queues NOTHING IS POLLING that no visible checkout owns"
    if [ "$STRANDED_QUEUES" -eq 0 ]; then
        echo "  (none — every queue in this scope is either polled or owned by a checkout"
        echo "   this run can see)"
    else
        while IFS="$(printf '\t')" read -r verdict queue scheds runs oldest; do
            printf '  %-8s %s\n' "$verdict" "$queue"
            printf '           %s schedule(s) still aimed at it · %s open run(s)' "$scheds" "$runs"
            if [ "$runs" != "0" ]; then
                printf ', oldest %s' "$(lc_duration "$oldest")"
            fi
            printf ' · %s\n' "$(queue_phrase "$queue")"
        done <"${WORK}/stranded"
        echo ""
        echo "  ${STRANDED_QUEUES} queue(s) with no poller, carrying ${STRANDED_SCHEDULES} schedule(s) and ${STRANDED_RUNS} open run(s)."
        if [ "$STRANDED_RUNS" != "0" ]; then
            echo "  The oldest of those runs has been open $(lc_duration "$STRANDED_OLDEST")."
        fi
        echo "  A schedule aimed at a queue with no poller goes on firing forever and the"
        echo "  runs it starts go on piling up; no checkout can clean this up for itself,"
        echo "  because the checkouts that made most of it are gone (see this file's header)."
        # THE WORD `DESTROYED` IS NOT SAID HERE, and that is deliberate rather
        # than squeamish: it is the token a reader — and the drive — greps a
        # transcript for to find out whether anything died, and a summary that
        # spent it on a promise would blind the search that matters.
        if [ "$SWEEP" -eq 1 ]; then
            echo "  This run was a --sweep; the rows above say what it reached and what it left."
        else
            echo "  This census TOUCHED NOTHING. Read the verdicts above, then decide by hand:"
            echo "    ./scripts/sweep.sh --class schedule --only <identity> --sweep --force-foreign --roots <dir>"
        fi
    fi
    echo ""
fi

# --- kind: process -------------------------------------------------------------

if wanted_class test-server-process; then
    echo "class: test-server-process — $(lc_field test-server-process 3)"
    shown=0
    if [ -n "$ONLY" ]; then
        echo "  (excluded by --only: a test-server process carries no checkout identity"
        echo "   to narrow by — see the registry's identity column)"
    else
        while read -r pid ppid exe; do
            [ -n "${pid:-}" ] || continue
            base="${exe##*/}"
            lc_claim_test_server_process "$base" || continue
            shown=1
            if [ "$ppid" != "1" ]; then
                judge test-server-process "IN USE" "parent ${ppid}" "pid ${pid} (${base}, parent ${ppid})" ""
            else
                judge test-server-process "FOREIGN" "it (a test-server process carries no checkout identity)" \
                    "pid ${pid} (${base}, orphaned)" "" \
                    ./scripts/temporal_sweep.sh --sweep
            fi
        done < <(lc_scan_test_server_processes)
    fi
    [ "$shown" -eq 0 ] && echo "  (none)"
    echo ""
fi

# --- the summary ---------------------------------------------------------------

echo "census: ${FOUND} found · ${DESTROYED} destroyed · ${LEFT} left alone · ${FAILED} failed"
if [ "$FOREIGN_COUNT" -gt 0 ]; then
    echo "        ${FOREIGN_COUNT} FOREIGN — this run could not say whose they are. That is an"
    echo "        absence of evidence, not a finding: point --roots at wherever clones of"
    echo "        this repository live — and only then, having read what that census says,"
    echo "        --sweep --force-foreign --roots <dir> to destroy what is left by hand."
fi
if [ "$SWEEP" -eq 0 ] && [ -s "${WORK}/would" ]; then
    echo ""
    echo "what --sweep WOULD do (${WOULD} instance(s)):"
    while IFS="$(printf '\t')" read -r why class display; do
        case "$why" in
        own) echo "  --sweep                  ${class}  ${display}" ;;
        FOREIGN) echo "  --sweep --force-foreign --roots <dir>  ${class}  ${display}" ;;
        esac
    done <"${WORK}/would"
fi

if [ "$UNRECOGNIZED" -gt 0 ]; then
    echo ""
    echo "!! ${UNRECOGNIZED} UNRECOGNIZED shape(s). This run cannot say what it looked at," >&2
    echo "   so it has cleared nothing — machinery class N+1 exists and the registry" >&2
    echo "   does not know about it (exit 2)." >&2
    exit 2
fi
if [ "$FAILED" -gt 0 ]; then
    exit 1
fi

# --assert-none: the census as an ASSERTION, for a caller that has already
# decided nothing should be here (the gate's own-tree-census leg is the first
# — a checkout in `process` lifetime owns no durable Schedule, so one found is
# a leak).
#
# AFTER the unrecognized refusal and never before it: "I found nothing" and "I
# could not tell what I found" are different answers, and the second one may not
# be reported as the first. Exit 1 is deliberate and distinct from exit 2 — the
# population is a finding about the tree, not a broken instrument.
if [ "$ASSERT_NONE" -eq 1 ]; then
    # THE EXEMPTION, PRINTED BEFORE THE VERDICT AND WHETHER OR NOT IT CHANGED IT.
    # It is on stdout with the rest of the census because it is a census
    # statement, not an error, and because the caller that reads this instrument's
    # STATUS (the gate's own-tree census leg) puts this transcript in front of a
    # human either way. An exemption that only printed when it rescued a run
    # would be invisible on exactly the runs a reviewer wants to audit it on.
    if [ "$EXEMPT" -gt 0 ]; then
        echo ""
        echo "--assert-none: ${EXEMPT} instance(s) EXEMPT — this checkout's own working set,"
        echo "  in use right now. Named here with the evidence, because an exemption nobody"
        echo "  can read is an assertion quietly weakened:"
        while IFS="$(printf '\t')" read -r ex_class ex_display ex_evidence; do
            [ -n "${ex_class:-}" ] || continue
            printf '  exempt   %s\n' "$ex_display"
            printf '           %s owns it · %s is declared NOT disposable — it is a working\n' "$OUR_BASE" "$ex_class"
            printf '           set, not a leftover · in use right now: %s\n' "$ex_evidence"
        done <"${WORK}/exempt"
        echo "  Absence of that evidence is NEVER an exemption: an owned instance nothing is"
        echo "  using is indistinguishable from a leftover, and that is the strand the gate's"
        echo "  open-execution leg exists to catch."
    fi

    IN_SCOPE=$((FOUND - EXEMPT))
    if [ "$IN_SCOPE" -gt 0 ]; then
        echo ""
        echo "!! --assert-none: ${IN_SCOPE} instance(s) are in scope and none should be." >&2
        if [ -n "$ONE_CLASS" ]; then
            echo "   scope: class ${ONE_CLASS}${ONLY:+, identity prefix ${ONLY}}" >&2
        else
            echo "   scope: every declared class${ONLY:+, identity prefix ${ONLY}}" >&2
        fi
        if [ "$EXEMPT" -gt 0 ]; then
            echo "   (${FOUND} found · ${EXEMPT} exempt as this checkout's working set, named above)" >&2
        fi
        echo "   They are listed above with their verdicts. This is exit 1 — a finding about" >&2
        echo "   the tree, not a broken instrument." >&2
        exit 1
    fi
fi
exit 0
