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
# THE EXECUTABLE-DOCS DRIVE — `docs/runbooks/deploy.md`'s webhook recipes, run
# as printed against a live receiver, and
# `docs/runbooks/capacity.md`'s connection-census and envelope-line recipes, run
# as printed against a real Postgres (rung OPS-1, P11).
#
#   ./scripts/tests/test_runbook_recipes.sh          run every case
#   ./scripts/tests/test_runbook_recipes.sh --list   name them and stop
#
# WHY IT EXISTS, and why the third careful edit was not the fix. The runbook's
# "Signing a status webhook by hand" section exists because a field test
# could not send one: the recipes lived only in two test modules, which is not
# where an operator looks. The section was written, and reviewed, and shipped —
# and the very next field test found the same class inside it: the recipes never
# said WHOSE id `message_id` is, so a body naming our row id verified perfectly,
# stored, answered 202, and recorded nothing for ever. That was fixed carefully
# too, and one rung later the click half of the same section was found writing a
# legal row with an empty link because the key is `click_url` and not `url`.
#
# Three careful edits, three misses, one class: **a recipe nobody runs is prose
# that looks like code.** So this drive runs them. An earlier link census
# proved the doc's targets EXIST; this proves the doc's recipes BEHAVE.
#
# THE RECIPES ARE LIFTED OUT OF THE DOCUMENT AT RUN TIME and are nowhere in this
# tree twice. Each fenced block in `deploy.md` sits under an HTML comment naming
# it (`<!-- recipe: house-v2 -->`); `scripts/tests/render_recipe.py` finds the
# marker, copies the block byte for byte, and applies a DECLARED substitution
# table. Nothing is reformatted. `case_the_drive_holds_no_copy_of_the_recipes`
# is the tooth on that promise: this file and the harness beside it are read as
# text and must contain none of the signing arithmetic, while the blocks lifted
# out of the document must contain all of it. An edit to a recipe that breaks
# the drive therefore fails WITHOUT ANYBODY SYNCING A COPY, which is the whole
# design — the alternative is a second copy that agrees today.
#
# WHAT IS SUBSTITUTED, exhaustively, and nothing else is:
#
#   https:// -> http://     THE ONE SUBSTITUTION THE RECIPE DOES NOT NAME. A
#                           laptop receiver has no certificate, and `curl` and
#                           `urllib` are both right to refuse a self-signed one.
#                           Declared here rather than hidden: the scheme is
#                           swapped, the host, the path, the headers, the body
#                           and every byte of the signing arithmetic are not.
#   <host>                  the address this drive's receiver is listening on.
#   <connection-id>         the connection recipe 1 created, one case earlier.
#   the webhook_secret      the secret recipe 1 was given, so recipes 2 and 3
#     placeholder           sign with the secret recipe 1 stored.
#   the message_id          the `provider_message_id` of a message the harness
#     placeholder           sent. This is the exact value an earlier escalation
#                           was about, which is why the drive substitutes the
#                           PROVIDER's handle and nothing else: a drive that
#                           substituted our row id would reproduce the defect
#                           and call it a pass.
#   bounced -> opened       ONE VARIANT ONLY, and only in the engagement cases.
#                           The recipes print `bounced`; the vocabulary table
#                           three paragraphs above them declares the value set
#                           the key takes, `opened` and `clicked` included, and
#                           the engagement half is what that field test never
#                           saw arrive. So each house recipe is driven TWICE:
#                           once exactly as printed (asserting the message row
#                           moves to bounced) and once with the one word swapped
#                           (asserting the engagement row lands). The word is
#                           swapped in the body and in the `X-Event-Type` header
#                           together, because the recipe prints it in both.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE TWO VENDOR-SIGNED RECIPES ARE NOT DRIVEN, ONLY BOUND. `recipe: svix`
#      and `recipe: twilio` are executed — so an import that moved, a renamed
#      SDK method or a signature call that stopped returning a string is caught
#      — and their output is never posted at anything. Driving them would need
#      an Anymail ESP configured (Svix) and a real account token plus a
#      byte-identical public callback URL (Twilio), neither of which a drive can
#      conjure. What is proven for those two is that the code binds its symbols
#      and produces a signature; what is NOT proven is that the receiver accepts
#      it. Two recipes out of five, named.
#   2. THE THREE-MOVE SEQUENCE'S MIDDLE MOVE. Recipe 1's step 2 is "in the
#      provider's dashboard, add an endpoint" — an account-owner action in
#      somebody else's console, which the runbook itself says a machine cannot
#      do. The drive runs step 1 and asserts the row; it cannot subscribe
#      anything to anything.
#   3. TLS, AND THEREFORE EVERY TLS-SHAPED FAILURE. See the substitution table:
#      the scheme is swapped. A recipe that only fails against a real
#      certificate — a proxy rewriting the host, an SNI mismatch — passes here.
#   4. THE PROSE. Only the fenced blocks are executed. The vocabulary table, the
#      401 diagnosis list and the "202 and then nothing" paragraph are read by
#      nothing, and a wrong sentence beside a right recipe is invisible to this
#      drive exactly as it was to every reviewer.
#   5. A RECIPE THE DOCUMENT GREW AND NOBODY MARKED. The population is the five
#      markers named below, and it is a list, not a derivation: a sixth recipe
#      added without a marker is not driven and nothing here notices. The
#      cheapest guard available — that every marker in the document is in this
#      drive's list and vice versa — IS taken
#      (`case_every_marker_in_the_document_is_driven`), so an unmarked block is
#      the only remaining hole.
#   6. WHICH INTERPRETER RUNS WHICH RECIPE, because the two answers say
#      different things. The house-scheme recipes run on the system `python3`
#      and `bash` — stdlib, `curl` and `openssl`, exactly what an operator on a
#      jump box has — so a recipe that quietly depended on this project's venv
#      would fail here. The two vendor recipes run under `uv run` because they
#      import this project's own dependencies (`svix`, `twilio`) and there is
#      nowhere else for those to come from. Neither is asserted; both are stated
#      so that a green run is not read as "the recipes need nothing installed".
#   7. THE DELIVERY WORKFLOW. The receiver's 202 means accepted and handed on;
#      what this drive then reads is the row the synchronous inbound handler
#      wrote. Anything Temporal does afterwards is not driven and not asserted.
#   8. THE CAPACITY CHAPTER'S REVIEW-TIER SECTIONS, which are the majority of
#      it. `docs/runbooks/capacity.md` carries seven sections and this drive
#      lifts recipes out of two of them. The resize sequence and its DNS step
#      act on AWS; the reboot-resilience result was proven by hand on a real
#      box; the neighbour A/B and the concurrency ladder are paid performances
#      against a deployed box. None of those can be a document test, and the
#      chapter's own closing section says which is which — the same
#      bound-not-driven split blind spot 1 declares for the two vendor recipes.
#   9. EVERY NUMBER IN THE CAPACITY CHAPTER. What its census recipes are driven
#      for is SHAPE — the query is legal against a real server, the columns it
#      names exist, the principals come back attributed inside one read. The
#      development Postgres this drive reaches is not the staging box and holds
#      none of its neighbours, so no bound, no budget line and no envelope
#      number is asserted here. A green run means the recipe an operator would
#      paste still executes; it means nothing whatsoever about capacity.
#
# IT BUILDS ITS OWN DATABASE and drops it. `test_<this checkout's name>_rbk`,
# which is inside the `test_djb_*` population `scripts/db_sweep.sh` already
# brooms, so a drive killed mid-run leaves something a broom can reach rather
# than something nobody named. It never touches this checkout's own database.
#
# AND IT TERMINATES THE RUNS IT STARTS, which for a year it did not. Seeding the
# world starts a Temporal execution per message and per emitted event, onto the
# queue this run's scratch DATABASE derives — a queue no worker anywhere polls,
# whose name dies with the database at exit. Fifteen executions per run stayed
# RUNNING for ever; a machine's dev namespace was holding over a thousand of
# them, all from this file, before anybody counted. The database was always
# dropped and the executions were the half nobody owned, which is a LIFETIME
# CLASS MISMATCH minted at creation and not a missing broom
# (`scripts/lifecycle.sh` argues that in full).
#
# The scope of the cleanup is both halves at once — THIS checkout's derived task
# queue AND a workflow id under the harness's own tenant slug — and it runs on
# every exit path including a killed one, which is what section 6 of
# `drive_preamble.sh` was written for. `kill -9` is untrappable and is the
# declared hole. `scripts/sweep.sh --class open-execution` is what finds a
# strand this file failed to reach.
#
# COST. ~35s: the migration chain into a fresh scratch database is nearly all of
# it, the server start and the five recipes are most of the rest, and
# terminating fifteen executions one at a time is about three seconds.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_runbook_recipes: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death
# hands the EXIT trap a status of 0, so a drive that dies halfway reads as a
# PASS to check.sh. This drive boots a server and a database; it has more ways
# to die halfway than most.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_runbook_recipes: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    # Definitions only — `^case_` alone also matches the call sites at the foot
    # of the file and prints every name twice.
    grep -nE '^case_[a-z0-9_]+\(\) \{' "$0" | sed 's/() {.*//; s/^/  /'
    # `--list` is a complete run of nothing, and the finished sentinel has to
    # say so: without it the epilogue reads this exit as a drive that died
    # (section 5 of the preamble).
    drive_finished
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_runbook_recipes.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

DOC="docs/runbooks/deploy.md"
CAPDOC="docs/runbooks/capacity.md"
RENDER="scripts/tests/render_recipe.py"
HARNESS="scripts/tests/runbook_receiver.py"

# The population, blind spot 5. Space-separated because bash 3.2 has no arrays
# worth the trouble here.
MARKERS="connection-create house-v2 house-legacy svix-sign twilio-sign"
# The capacity chapter's half of the population, and the same list-not-a-
# derivation caveat applies: blind spot 5 covers both documents.
CAP_MARKERS="pg-census pg-census-steady envelope-line-example envelope-line-check"

[ -r "$DOC" ] || cannot_look "${DOC} is not readable — there are no recipes to drive"
[ -r "$CAPDOC" ] || cannot_look "${CAPDOC} is not readable — there are no capacity recipes to drive"
[ -r "$RENDER" ] || cannot_look "${RENDER} is not in this tree — nothing can lift a recipe out of the document"
[ -r "$HARNESS" ] || cannot_look "${HARNESS} is not in this tree — there is no receiver to drive the recipes at"
[ -r manage.py ] || cannot_look "no manage.py here — this is not a checkout root"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH"
command -v curl >/dev/null 2>&1 || cannot_look "no curl on PATH — two of the recipes ARE curl"
command -v openssl >/dev/null 2>&1 || cannot_look "no openssl on PATH — the legacy recipe signs with it"
command -v uv >/dev/null 2>&1 || cannot_look "no uv on PATH — the receiver runs on this checkout's venv"

. scripts/db.sh
# `lc_temporal` and nothing else: the ONE way anything in this tree reaches the
# Temporal CLI, which lives in the compose container and not on the host. This
# drive terminates the executions it starts (see THE RUNS THIS DRIVE STARTS
# above) and a second copy of `docker compose exec -T temporal temporal` here
# would be a second answer to "how do we talk to the server".
. scripts/lifecycle.sh

ROOT="$PWD"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-runbook-recipes.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"

RECEIVER_PID=""
SCRATCH_DB=""

# --- the runs this drive starts, and terminating them -------------------------
#
# THE DRIVE TERMINATES WHAT IT STARTS. Seeding two messages through `send()`
# and posting three webhooks at the receiver starts Temporal executions — a
# `DeliverMessageWorkflow` per message and a `DispatchEventWorkflow` per emitted
# event — onto the queue this checkout's scratch DATABASE derives. On this
# template nothing polls that queue: the drive runs no worker, and the queue name
# dies with the scratch database at exit. So every one of those executions stayed
# RUNNING for ever, fifteen per run, and a machine's dev namespace had
# accumulated over a thousand of them by the time anybody counted. The database
# was always dropped; the executions were the half nobody owned.
#
# THAT SENTENCE IS ABOUT THIS TEMPLATE AND NOT ABOUT EVERY CONSUMER, which is a
# correction a consumer bought for us (its queue row). `TEMPORAL_TASK_QUEUE`
# wins outright over the derivation (`config/settings/base.py`), so a product
# that pins it hands this drive a queue its own worker is polling — where the
# seeded runs COMPLETE instead of stranding. Nothing about the cleanup changes:
# terminating a run that has already finished is a no-op, and the terminator is
# still right. What changed is the CASE that asserts it, which used to read the
# incidental population as its positive half and now supplies its own probe —
# see `case_the_drive_terminates_the_runs_it_started`.
#
# THE SCOPE IS BOTH HALVES AT ONCE and it is deliberately narrow: the task queue
# THIS checkout derived, AND a workflow id starting with the harness's own
# tenant slug. Either alone would be wider than this drive's business — a queue
# name is a checkout, not a drive, and the slug is shared by every checkout's
# copy of this drive on the same machine — and their conjunction is exactly
# "runs this process caused". Both values are ASKED FOR (`runbook_receiver.py
# world`) rather than derived here; its docstring says why.
#
# IT RUNS ON EVERY EXIT PATH, including a killed one: `drive_at_exit` puts it in
# the preamble's epilogue, which bash reaches for TERM, INT and HUP as well as
# for a pass, a fail and a could-not-look (section 6 of the preamble carries the
# measurement and the announcement). `kill -9` is untrappable and is the
# declared hole, there and here.
DRIVE_QUEUE=""
DRIVE_SLUG=""

# Both halves, in Temporal's own list-filter grammar. Empty when this run never
# learned where its work lands, which every caller checks before using it.
our_runs_query() {
    [ -n "$DRIVE_QUEUE" ] && [ -n "$DRIVE_SLUG" ] || return 1
    printf 'TaskQueue="%s" AND ExecutionStatus="Running" AND WorkflowId STARTS_WITH "%s:"' \
        "$DRIVE_QUEUE" "$DRIVE_SLUG"
}

# One workflow id per line, or a non-zero exit if the server could not be asked.
# A document that did not parse is NOT an empty population — an empty answer
# there would read as "nothing to clean" and leave everything behind.
our_running_ids() {
    local query
    query="$(our_runs_query)" || return 1
    lc_temporal workflow list --query "$query" -o json 2>/dev/null |
        python3 -c 'import json, sys
try:
    docs = json.load(sys.stdin)
except Exception:
    raise SystemExit(2)
for doc in docs:
    print(doc["execution"]["workflowId"])
'
}

# Terminate every one of them, ONE AT A TIME BY ID rather than as a batch over
# the query. `temporal workflow terminate --query` starts an asynchronous batch
# job and returns before it has done anything, so the assertion that follows it
# would be racing the server; terminating by id is synchronous, and at ~0.2s a
# call against fifteen runs it costs about three seconds.
#
# Three rounds, because the list and the terminates are not one atomic act: an
# execution that started between them would survive a single pass. In practice
# the receiver is already dead by the time this runs and round two finds
# nothing.
terminate_the_runs_this_drive_started() {
    local round ids id
    for round in 1 2 3; do
        ids="$(our_running_ids)" || return 1
        [ -n "$ids" ] || return 0
        for id in $ids; do
            lc_temporal workflow terminate --workflow-id "$id" \
                --reason "test_runbook_recipes: the drive that started it has finished" \
                >/dev/null 2>&1 || true
        done
    done
    ids="$(our_running_ids)" || return 1
    [ -z "$ids" ]
}

teardown() {
    if [ -n "$RECEIVER_PID" ]; then
        # By pid, never by name: `pkill -f` has killed other agents' gates twice.
        kill "$RECEIVER_PID" 2>/dev/null || true
        wait "$RECEIVER_PID" 2>/dev/null || true
    fi
    # AFTER the receiver is dead, so nothing is still starting work, and before
    # the database goes: the two are independent but this order reads as the
    # story it is. A failure here is one line on stderr and never a verdict —
    # the cleanup is not a case, and a drive that asserted 38 things correctly
    # did not stop being right because docker was not there to be asked.
    if [ -n "$DRIVE_QUEUE" ]; then
        terminate_the_runs_this_drive_started ||
            echo "!! test_runbook_recipes: could not terminate this drive's Temporal runs on ${DRIVE_QUEUE} — they are stranded, and scripts/sweep.sh is what finds them." >&2
    fi
    if [ -n "$SCRATCH_DB" ]; then
        db_drop "$SCRATCH_DB" >/dev/null 2>&1 || true
    fi
    rm -rf "$WORK"
}
drive_at_exit 'teardown'

CURRENT=""
OUT=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -30
    fi
    FAILED=$((FAILED + 1))
}

# --- lifting a recipe out of the document -------------------------------------
#
# `render_recipe.py` refuses at exit 2 when a marker is missing, doubled, or not
# followed by a fenced block. A refusal here is a could-not-look for the case,
# never a silent empty file.
render() {
    local marker="$1" out="$2" table="$3"
    render_from "$DOC" "$marker" "$out" "$table"
}

# The same lift, out of a NAMED document. `render_recipe.py` already took the
# document as its first argument; only this drive had one hard-coded. Two
# documents share one extractor rather than growing a second one, which is the
# no-copy discipline applied to the lifting machinery itself.
render_from() {
    local doc="$1" marker="$2" out="$3" table="$4"
    python3 "$RENDER" "$doc" "$marker" "$out" "$table"
}

# The substitution table, built once per call so every case declares the same
# one. `python3` composes the JSON rather than this file quoting it by hand: the
# secret and the host both contain characters a shell here-string would eat.
table_for() {
    local event="$1" handle="$2"
    python3 - "$event" "$handle" "${HOST:-}" "${CONNECTION_ID:-}" "${WHSEC:-}" <<'PY'
import json, sys

event, handle, host, connection_id, secret = sys.argv[1:6]
table = {
    "https://": "http://",
    "<host>": host,
    "<connection-id>": connection_id,
    "…the connection's webhook_secret…": secret,
    '"message_id": "…"': f'"message_id": "{handle}"',
    '"message_id":"…"': f'"message_id":"{handle}"',
}
if event != "bounced":
    table["bounced"] = event
print(json.dumps(table))
PY
}

facts() {
    (cd "$ROOT" && DATABASE_NAME="$SCRATCH_DB" uv run python "$HARNESS" facts) 2>/dev/null
}

# =============================================================================

case_every_marker_in_the_document_is_driven() {
    CURRENT="every marker in the document is driven, and every driven marker is in it"
    N=$((N + 1))
    OUT="${WORK}/markers${N}.log"

    grep -oE '^<!-- recipe: [A-Za-z0-9_-]+ -->$' "$DOC" |
        sed 's/^<!-- recipe: //; s/ -->$//' | LC_ALL=C sort >"${WORK}/in-doc.txt"
    printf '%s\n' $MARKERS | LC_ALL=C sort >"${WORK}/in-drive.txt"

    if diff -u "${WORK}/in-drive.txt" "${WORK}/in-doc.txt" >"$OUT" 2>&1; then
        ok "the document and this drive name the same five recipes"
    else
        bad "the document and this drive disagree about which recipes exist"
    fi

    # And each one resolves to exactly one block. `render_recipe.py` owns the
    # three refusals; this asserts it found something for every marker.
    local marker
    for marker in $MARKERS; do
        OUT="${WORK}/render-${marker}.log"
        if render "$marker" "${WORK}/${marker}.txt" '{}' >"$OUT" 2>&1 &&
            [ -s "${WORK}/${marker}.txt" ]; then
            ok "recipe: ${marker} lifts out of ${DOC} as a non-empty block"
        else
            bad "recipe: ${marker} did not lift out of ${DOC}"
        fi
    done
}

# THE SAME TOOTH, ON THE SECOND DOCUMENT. The criterion the capacity chapter
# was dispatched under says it in as many words: a recipe marked drivable that
# this drive cannot lift is a FAIL naming the marker. So the marker sets are
# compared both ways here too — a block marked in the chapter and absent from
# `CAP_MARKERS` is silently undriven prose, which is the whole class this file
# exists to abolish.
case_every_marker_in_the_capacity_chapter_is_driven() {
    CURRENT="every marker in the capacity chapter is driven, and every driven marker is in it"
    N=$((N + 1))
    OUT="${WORK}/capmarkers${N}.log"

    grep -oE '^<!-- recipe: [A-Za-z0-9_-]+ -->$' "$CAPDOC" |
        sed 's/^<!-- recipe: //; s/ -->$//' | LC_ALL=C sort >"${WORK}/cap-in-doc.txt"
    printf '%s\n' $CAP_MARKERS | LC_ALL=C sort >"${WORK}/cap-in-drive.txt"

    if diff -u "${WORK}/cap-in-drive.txt" "${WORK}/cap-in-doc.txt" >"$OUT" 2>&1; then
        ok "the chapter and this drive name the same recipes"
    else
        bad "the chapter and this drive disagree about which recipes exist"
    fi

    local marker
    for marker in $CAP_MARKERS; do
        OUT="${WORK}/render-${marker}.log"
        if render_from "$CAPDOC" "$marker" "${WORK}/${marker}.txt" '{}' >"$OUT" 2>&1 &&
            [ -s "${WORK}/${marker}.txt" ]; then
            ok "recipe: ${marker} lifts out of ${CAPDOC} as a non-empty block"
        else
            bad "recipe: ${marker} did not lift out of ${CAPDOC}"
        fi
    done
}

# THE TOOTH ON "THE DOC IS THE TEST". If this drive contained the signing
# arithmetic, a recipe could rot in the document while the drive went on passing
# against its own copy — which is the failure mode this whole rung exists to
# make impossible. The needles are assembled at run time so that neither string
# appears contiguously in this file, which is the same discipline the censused
# markers get (rung-execution §5).
case_the_drive_holds_no_copy_of_the_recipes() {
    CURRENT="the drive holds no copy of the recipes"
    N=$((N + 1))
    OUT="${WORK}/nocopy${N}.log"

    local hmac_needle openssl_needle
    hmac_needle="hmac$(printf '.new(')"
    openssl_needle="openssl$(printf ' dgst')"

    # Positive half FIRST: an assertion that the recipes carry the arithmetic,
    # so the negative half below cannot pass because the extraction returned
    # nothing.
    if grep -qF -- "$hmac_needle" "${WORK}/house-v2.txt"; then
        ok "the v2 recipe in the document computes its own digest"
    else
        bad "the v2 recipe lifted out of the document does not compute a digest — extraction is broken"
    fi
    if grep -qF -- "$openssl_needle" "${WORK}/house-legacy.txt"; then
        ok "the legacy recipe in the document computes its own digest"
    else
        bad "the legacy recipe lifted out of the document does not compute a digest — extraction is broken"
    fi

    local file
    for file in "$0" "$HARNESS"; do
        if grep -F -- "$hmac_needle" "$file" >"$OUT" 2>&1 ||
            grep -F -- "$openssl_needle" "$file" >>"$OUT" 2>&1; then
            bad "${file} computes a signature of its own — that is the second copy"
        else
            ok "${file} computes no signature of its own"
        fi
    done
}

# THE SAME TOOTH, ON THE CAPACITY CHAPTER. Needles assembled at run time for
# the reason the case above states: a guard that counts a string cannot spell
# it, or the guard is its own violation (rung-execution §5). The positive half
# runs FIRST here too — if extraction silently returned nothing, the negative
# half would pass for the wrong reason.
case_the_drive_holds_no_copy_of_the_capacity_recipes() {
    CURRENT="the drive holds no copy of the capacity recipes"
    N=$((N + 1))
    OUT="${WORK}/capnocopy${N}.log"

    local catalog_needle bound_needle
    catalog_needle="pg_stat$(printf '_activity')"
    bound_needle="ERR_BOUND$(printf '_PCT')"

    if grep -qF -- "$catalog_needle" "${WORK}/pg-census.txt" &&
        grep -qF -- "$catalog_needle" "${WORK}/pg-census-steady.txt"; then
        ok "both census recipes in the chapter read the catalogue themselves"
    else
        bad "a census recipe lifted out of the chapter names no catalogue — extraction is broken"
    fi
    if grep -qF -- "$bound_needle" "${WORK}/envelope-line-check.txt"; then
        ok "the envelope checker in the chapter carries its own validity bound"
    else
        bad "the envelope checker lifted out of the chapter carries no bound — extraction is broken"
    fi

    local file
    for file in "$0" "$HARNESS"; do
        if grep -F -- "$catalog_needle" "$file" >"$OUT" 2>&1 ||
            grep -F -- "$bound_needle" "$file" >>"$OUT" 2>&1; then
            bad "${file} carries a copy of the capacity arithmetic — that is the second copy"
        else
            ok "${file} carries no copy of the capacity arithmetic"
        fi
    done
}

# THE FOUR-PART LINE, MADE A RULE RATHER THAN A HABIT. The chapter prints one
# worked envelope line and one checker; this drives the checker AT the example,
# so a format that stops parsing fails a test instead of ageing quietly.
#
# The negative is built by DROPPING THE LAST FIELD of the lifted example — not
# by writing a broken line here. That is deliberate: a hand-written negative
# would have to name a field, and naming a field is the second copy again. The
# drive knows only that the line has fields and that removing one must be
# refused.
case_the_envelope_line_checker_accepts_the_chapters_own_example() {
    CURRENT="the envelope-line checker accepts the chapter's own worked example"
    N=$((N + 1))
    OUT="${WORK}/envelope-ok${N}.log"

    if python3 "${WORK}/envelope-line-check.txt" --knee \
        <"${WORK}/envelope-line-example.txt" >"$OUT" 2>&1; then
        ok "the worked example is a valid envelope line, and claims its knee legally"
    else
        bad "the chapter's own worked example does not satisfy the chapter's own checker"
    fi
}

case_the_envelope_line_checker_refuses_an_incomplete_line() {
    CURRENT="the envelope-line checker refuses a line missing a part"
    N=$((N + 1))
    OUT="${WORK}/envelope-bad${N}.log"

    python3 - "${WORK}/envelope-line-example.txt" >"${WORK}/envelope-short.txt" <<'PY'
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    fields = handle.read().strip().split(" | ")
# One field short of an envelope line. Which one is not this drive's business.
print(" | ".join(fields[:-1]))
PY

    if python3 "${WORK}/envelope-line-check.txt" --knee \
        <"${WORK}/envelope-short.txt" >"$OUT" 2>&1; then
        bad "a line one part short PASSED — the checker cannot fail, so it proves nothing"
    else
        ok "a line one part short is refused (the checker can fail)"
    fi
}

# SHAPE, NEVER STAGING NUMBERS (blind spot 9). What is asserted: the recipe an
# operator would paste is legal SQL against a real server, and the read comes
# back ATTRIBUTED — the reading session's own database and login appear in one
# row of one execution, which is the same-read discipline the chapter states.
# The development Postgres holds none of staging's neighbours and no bound is
# checked against it.
case_the_census_recipes_are_legal_and_attribute_in_one_read() {
    CURRENT="the census recipes run against a real server and attribute in one read"
    N=$((N + 1))
    OUT="${WORK}/census${N}.log"

    # An unreachable server is COULD-NOT-LOOK, never a failing recipe — the
    # distinction this whole file is built on, and the one the chapter's own
    # census discipline states in as many words.
    db_query "SELECT 1" -tA >"${WORK}/censusping.log" 2>&1 ||
        cannot_look "no Postgres to drive the census recipes at — is the compose stack up? (scripts/setup.sh) — see ${WORK}/censusping.log"

    if db_psql -tA -F'|' <"${WORK}/pg-census.txt" >"$OUT" 2>&1; then
        ok "the census recipe is legal SQL against a live server"
    else
        bad "the census recipe did not execute — the columns it names may have moved"
        return 0
    fi
    # The reading session is itself a client backend, so this row must exist on
    # any server that answered at all: the recipe attributes the connection it
    # is asking through. A read that came back with no principals is a read
    # that grouped nothing.
    if grep -q "^postgres|${POSTGRES_USER}|" "$OUT"; then
        ok "the read names its own database and principal together, in one execution"
    else
        bad "the census came back unattributed — datname+usename did not both land"
    fi

    OUT="${WORK}/censussteady${N}.log"
    if db_psql -tA -F'|' <"${WORK}/pg-census-steady.txt" >"$OUT" 2>&1; then
        ok "the steady-touchers recipe is legal SQL against a live server"
    else
        bad "the steady-touchers recipe did not execute"
        return 0
    fi
    # Five fields: the state and the last query ride the same row as the
    # principal, which is what makes an unexplained connection attributable
    # rather than merely counted.
    if awk -F'|' -v user="$POSTGRES_USER" \
        '$1 == "postgres" && $2 == user && NF >= 5 { found = 1 } END { exit found ? 0 : 1 }' \
        "$OUT"; then
        ok "the steady read carries state and last-query beside the principal"
    else
        bad "the steady read did not carry the attribution columns beside the principal"
    fi
}

case_the_connection_recipe_creates_the_connection() {
    CURRENT="recipe 1 creates the connection, as printed"
    N=$((N + 1))
    OUT="${WORK}/recipe1.log"

    render connection-create "${WORK}/recipe1.sh" "$(table_for bounced x)" >"$OUT" 2>&1 ||
        cannot_look "could not lift recipe 1 out of ${DOC} — see ${OUT}"

    # Exported because the recipe names them: `$HOST`, `$TOKEN`, `$WHSEC` are
    # the recipe's own variables and this drive fills them, which is the whole
    # of the contract between a runbook and somebody following it.
    export HOST TOKEN WHSEC
    ( bash "${WORK}/recipe1.sh" ) >"$OUT" 2>&1 || true

    CONNECTION_ID="$(python3 - "$OUT" <<'PY'
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(json.load(handle).get("id", ""))
except Exception:
    print("")
PY
)"

    if [ -n "$CONNECTION_ID" ]; then
        ok "the recipe answered a connection id (${CONNECTION_ID})"
    else
        bad "the recipe did not answer a connection id"
        return 0
    fi

    # One read of the world, three questions asked of it: every `facts` call is
    # a Django start, and a case that pays for three of them is a case somebody
    # eventually deletes for being slow.
    OUT="${WORK}/facts-recipe1.log"
    facts >"$OUT" 2>&1 || true

    local want got
    want="$( (cd "$ROOT" && DATABASE_NAME="$SCRATCH_DB" uv run python "$HARNESS" digest "$WHSEC") 2>/dev/null )"
    got="$(awk -v id="$CONNECTION_ID" '$1 == "connection" && $2 == id { print $5 }' "$OUT")"
    if [ -n "$want" ] && [ "$want" = "$got" ]; then
        ok "the row holds the secret the recipe was given"
    else
        bad "the stored webhook_secret does not match what the recipe posted"
    fi
    if grep -q "^connection ${CONNECTION_ID} comms-email Resend " "$OUT"; then
        ok "the row is a comms-email connection named Resend, as the recipe asked"
    else
        bad "the connection row is not the one the recipe described"
    fi
}

# THE ENGAGEMENT HALF — a field test once followed this section literally and
# got a 202 and an empty engagement list for ever. That is the assertion.
drive_house_recipe() {
    local marker="$1" runner="$2" event="$3" handle="$4" label="$5"
    N=$((N + 1))
    OUT="${WORK}/${marker}-${event}.log"

    render "$marker" "${WORK}/${marker}-${event}.run" "$(table_for "$event" "$handle")" \
        >"$OUT" 2>&1 || {
        bad "could not lift ${marker} out of ${DOC}"
        return 0
    }

    export HOST SECRET CONNECTION_ID
    ( "$runner" "${WORK}/${marker}-${event}.run" ) >"$OUT" 2>&1 || true

    # Anchored: `202` unanchored also matches the year in a traceback path, and
    # a case that passes on a stack trace is worse than one that fails.
    if grep -qE '^202$' "$OUT"; then
        ok "${label}: the receiver answered 202"
    else
        bad "${label}: the receiver did not answer 202"
    fi
}

case_the_v2_recipe_lands_an_engagement() {
    CURRENT="the X-Signature-V2 recipe lands an engagement row"
    drive_house_recipe house-v2 python3 opened "$HANDLE_V2" "v2 · opened"
    OUT="${WORK}/facts-v2-opened.log"
    facts >"$OUT" 2>&1 || true
    if grep -q "^engagement ${HANDLE_V2} opened " "$OUT"; then
        ok "an opened engagement is recorded against the provider handle"
    else
        bad "no engagement row landed — this is the 202-and-then-nothing shape exactly"
    fi
}

case_the_v2_recipe_as_printed_bounces_the_message() {
    CURRENT="the X-Signature-V2 recipe as printed bounces the message"
    drive_house_recipe house-v2 python3 bounced "$HANDLE_V2" "v2 · as printed"
    OUT="${WORK}/facts-v2-bounced.log"
    facts >"$OUT" 2>&1 || true
    if grep -q "^message ${HANDLE_V2} bounced$" "$OUT"; then
        ok "the message row reads bounced"
    else
        bad "the message row did not move to bounced"
    fi
}

case_the_legacy_recipe_lands_an_engagement() {
    CURRENT="the X-Signature recipe lands an engagement row"
    drive_house_recipe house-legacy bash opened "$HANDLE_LEGACY" "legacy · opened"
    OUT="${WORK}/facts-legacy-opened.log"
    facts >"$OUT" 2>&1 || true
    if grep -q "^engagement ${HANDLE_LEGACY} opened " "$OUT"; then
        ok "an opened engagement is recorded against the provider handle"
    else
        bad "no engagement row landed for the legacy scheme"
    fi
}

case_the_legacy_recipe_as_printed_bounces_the_message() {
    CURRENT="the X-Signature recipe as printed bounces the message"
    drive_house_recipe house-legacy bash bounced "$HANDLE_LEGACY" "legacy · as printed"
    OUT="${WORK}/facts-legacy-bounced.log"
    facts >"$OUT" 2>&1 || true
    if grep -q "^message ${HANDLE_LEGACY} bounced$" "$OUT"; then
        ok "the message row reads bounced"
    else
        bad "the message row did not move to bounced"
    fi
}

# BLIND SPOT 1 IS THIS CASE'S SUBJECT. Neither vendor recipe is posted at
# anything; both are executed, and each must leave a signature behind. That
# catches an import that moved and an SDK method that was renamed — which is
# every way these two have actually rotted — and it catches nothing about
# whether a receiver would accept the result.
case_the_vendor_signed_recipes_bind_their_symbols() {
    CURRENT="the vendor-signed recipes bind their symbols"
    N=$((N + 1))

    # `recipe_` PREFIX, and it is load-bearing rather than tidy: Python puts a
    # script's own directory first on `sys.path`, so a rendered file called
    # `svix.py` shadows the `svix` package the recipe imports and the case fails
    # with "svix is not a package" — the drive breaking the recipe rather than
    # the recipe being broken. Found on this drive's first run.
    OUT="${WORK}/svix.log"
    render svix-sign "${WORK}/recipe_svix.py" \
        '{"whsec_…": "whsec_c3VwZXJzZWNyZXRzaWduaW5na2V5MTIz"}' >"$OUT" 2>&1 ||
        cannot_look "could not lift the svix recipe out of ${DOC}"
    printf '\nassert isinstance(signature, str) and signature, "no signature"\nprint("svix ok", len(signature))\n' \
        >>"${WORK}/recipe_svix.py"
    if (cd "$ROOT" && uv run python "${WORK}/recipe_svix.py") >"$OUT" 2>&1 && grep -q 'svix ok' "$OUT"; then
        ok "the svix recipe runs and produces a signature"
    else
        bad "the svix recipe no longer binds — its imports or the SDK have moved"
    fi

    # The 32 hex digits are the SHAPE Twilio's `RequestValidator` requires of an
    # auth token, not a token: `compute_signature` needs something to key the
    # HMAC on, and this authenticates nothing, anywhere, ever. On its own line
    # so the reason and the allowance sit together.
    local twilio_table
    twilio_table='{"<the account auth_token>": "0123456789abcdef0123456789abcdef", "<host>": "example.invalid", "<connection-id>": "00000000-0000-0000-0000-000000000000"}' # pragma: allowlist secret

    OUT="${WORK}/twilio.log"
    render twilio-sign "${WORK}/recipe_twilio.py" "$twilio_table" \
        >"$OUT" 2>&1 || cannot_look "could not lift the twilio recipe out of ${DOC}"
    printf '\nassert isinstance(signature, str) and signature, "no signature"\nprint("twilio ok", len(signature))\n' \
        >>"${WORK}/recipe_twilio.py"
    if (cd "$ROOT" && uv run python "${WORK}/recipe_twilio.py") >"$OUT" 2>&1 && grep -q 'twilio ok' "$OUT"; then
        ok "the twilio recipe runs and produces a signature"
    else
        bad "the twilio recipe no longer binds — its imports or the SDK have moved"
    fi
}

# A KILLED DRIVE STILL OWES ITS CLEANUPS, and that is a property of the
# preamble rather than of any one case here. It is asserted in THIS file because
# this is the drive that pays for it: an interrupted run left its Temporal
# executions behind exactly as a finished one did — not because the exit path
# was skipped (bash runs an EXIT trap on TERM, INT and HUP by itself; the
# measurement is in section 6 of `drive_preamble.sh`) but because nothing on
# that path had ever been asked to terminate them.
#
# WHAT IS DRIVEN IS THE MECHANISM, NOT A KILLED COPY OF THIS DRIVE, and the
# reason is a collision rather than a cost: the scratch database name is derived
# from the CHECKOUT, so a nested self-run would create and drop the very
# database the outer run is using. So the case builds the smallest thing that
# has the property — a script that sources the preamble, registers a cleanup and
# waits — kills it with TERM, and asserts the cleanup ran and the status is the
# shell's `128 + 15`.
case_a_killed_drive_still_runs_its_cleanups() {
    CURRENT="a killed drive still runs the cleanups it registered"
    N=$((N + 1))
    OUT="${WORK}/killed${N}.log"

    local script sentinel started pid rc waited
    script="${WORK}/killable.sh"
    sentinel="${WORK}/killable.cleaned"
    started="${WORK}/killable.started"

    cat >"$script" <<SH
#!/usr/bin/env bash
set -euo pipefail
cd "${ROOT}"
. scripts/tests/drive_preamble.sh
drive_at_exit "touch '${sentinel}'"
touch "${started}"
# Short sleeps rather than one long one: bash runs a trap for a signal received
# during a foreground command only after that command returns, and this case is
# about the trap, not about bash's wait semantics (declared in section 6).
while :; do sleep 0.2; done
SH

    bash "$script" >"$OUT" 2>&1 &
    pid=$!

    waited=0
    while [ ! -e "$started" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            bad "the killable script died before it was ready — see ${OUT}"
            return 0
        fi
        waited=$((waited + 1))
        if [ "$waited" -ge 100 ]; then
            kill "$pid" 2>/dev/null || true
            bad "the killable script never became ready"
            return 0
        fi
        sleep 0.1
    done

    if [ -e "$sentinel" ]; then
        bad "the cleanup had already run before anything was killed — this case cannot fail"
        kill "$pid" 2>/dev/null || true
        return 0
    fi

    kill -TERM "$pid" 2>/dev/null || true
    rc=0
    wait "$pid" || rc=$?

    if [ -e "$sentinel" ]; then
        ok "a TERM'd drive ran its registered cleanup"
    else
        bad "a TERM'd drive skipped its registered cleanup — this is the class exactly"
    fi
    # 128 + SIGTERM. A killed drive must not be able to read as a pass.
    if [ "$rc" = "143" ]; then
        ok "it exited 143, so a caller still sees a killed drive as killed"
    else
        bad "a TERM'd drive exited ${rc}, not 143"
    fi
    # THE HALF THAT IS ACTUALLY SECTION 6'S. Bash runs an EXIT trap on these
    # signals by itself — section 6's own header carries the measurement — so
    # the two assertions above would pass with the signal traps deleted. What
    # would NOT survive is a killed drive SAYING it was killed, which is the
    # only thing that tells a transcript ending mid-drive from a drive that
    # hung.
    if grep -q 'killed by SIGTERM' "$OUT"; then
        ok "and it named the signal, so a transcript that stops here says why"
    else
        bad "a TERM'd drive died silently — a truncated transcript is unreadable"
    fi
}

# THE CRITERION THIS RUNG EXISTS FOR, asserted against the real server rather
# than against a promise. Positive half FIRST, as the no-copy cases do it: if
# nothing was running, the negative half below would pass because there was
# nothing to terminate, which is the shape of a green that proves nothing.
#
# THE PREMISE THIS CASE CARRIED, AND THE PROBE THAT REPLACES IT (its queue row).
# The positive half used to be satisfied by INCIDENTAL population: the two
# seeded sends and the three posted webhooks start a `DeliverMessageWorkflow`
# and a `DispatchEventWorkflow` each, and they stay Running because — in this
# drive's own words, one screen up — "nothing ever polls that queue". That is
# true on this workerless template, where `DRIVE_QUEUE` is derived from a
# scratch database nobody has a worker for. It is NOT a property of the drive:
# `TEMPORAL_TASK_QUEUE` wins outright over that derivation
# (`config/settings/base.py`), so a product running its local build with that
# pinned hands this drive a queue its own worker IS polling — every seeded run
# then completes in a second or two, `before` is 0, and the case reports
# "nothing of this drive's was running" on a drive that behaved perfectly.
#
# SO IT SUPPLIES ITS OWN PROBE. One execution this case starts itself, under the
# same task queue and the same tenant slug the terminator's query selects on, so
# the positive half is guaranteed by construction in BOTH worlds instead of by
# the absence of a worker. A workflow type nothing registers stays OPEN whether
# or not anybody is polling — a worker that meets one fails the workflow task
# and retries it, which is an open execution either way — so the probe is
# exactly as present in a polled world as in a dead one. The terminator ends it
# along with everything else, because it matches the same query; nothing here
# leaks a probe it planted.
DRIVE_PROBE=""
case_the_drive_terminates_the_runs_it_started() {
    CURRENT="the drive terminates the Temporal runs it started"
    N=$((N + 1))
    OUT="${WORK}/ourruns${N}.log"

    local before after pollers
    # THE WORLD, PRINTED. Positive evidence only, exactly as
    # `scripts/lifecycle.sh` declares this liveness: a poller is proof a worker
    # is up, and its absence proves nothing except that this run saw none.
    pollers="$(lc_queue_pollers "$DRIVE_QUEUE" 2>/dev/null)"
    case "${pollers:-}" in
    '' | *[!0-9]*) pollers=0 ;;
    esac
    if [ "$pollers" = "0" ]; then
        echo "  ...      ${CURRENT} — world: nothing polls ${DRIVE_QUEUE} (the workerless template)"
    else
        echo "  ...      ${CURRENT} — world: ${pollers} poller(s) on ${DRIVE_QUEUE} (a product running its local build)"
        echo "             the seeded runs may already have completed here; the probe below is"
        echo "             what makes the positive half true in this world too"
    fi

    # THE PROBE, supplied rather than assumed. Both halves of the terminator's
    # query — the task queue and the slug prefix — because a probe outside that
    # conjunction would be planted and never cleaned.
    DRIVE_PROBE="${DRIVE_SLUG}:rbkprobe:terminator:own"
    lc_temporal workflow start --workflow-id "$DRIVE_PROBE" --task-queue "$DRIVE_QUEUE" \
        --type "RunbookDriveProbeNeverRuns" >/dev/null 2>&1

    before="$(our_running_ids | wc -l | tr -d ' ')" ||
        cannot_look "could not ask Temporal what this drive left running — is the compose stack up? (scripts/setup.sh)"

    if [ "${before:-0}" -gt 0 ]; then
        ok "this drive has ${before} execution(s) running on ${DRIVE_QUEUE}, one of them the probe it planted"
    else
        bad "not even this case's own probe is running — the assertion below would pass for the wrong reason"
        return 0
    fi

    if terminate_the_runs_this_drive_started; then
        ok "every one of them is terminated"
    else
        our_running_ids >"$OUT" 2>&1 || true
        bad "runs remained after the terminator ran — see ${OUT}"
        return 0
    fi

    after="$(our_running_ids | wc -l | tr -d ' ')" || after="?"
    if [ "$after" = "0" ]; then
        ok "the server agrees: nothing of this drive's is still running"
    else
        bad "the server still lists ${after} of this drive's runs as Running"
    fi

    # THE WIRING, and not only the function. The two assertions above would go on
    # passing if somebody deleted the call from the exit cleanup, and then only
    # a drive that FINISHED would clean up — which is most of them, and not the
    # ones that matter. The live function body is what is read, never this file.
    if declare -f teardown | grep 'terminate_the_runs_this_drive_started' >/dev/null; then
        ok "the registered exit cleanup calls the terminator, so a drive that dies here still cleans"
    else
        bad "teardown does not call the terminator — only a drive that reaches this case would clean up"
    fi
}

# =============================================================================

echo "== test_runbook_recipes — driving ${DOC}'s and ${CAPDOC}'s recipes as printed"
echo "   scratch: ${WORK}"

case_every_marker_in_the_document_is_driven
case_the_drive_holds_no_copy_of_the_recipes
case_every_marker_in_the_capacity_chapter_is_driven
case_the_drive_holds_no_copy_of_the_capacity_recipes
case_the_envelope_line_checker_accepts_the_chapters_own_example
case_the_envelope_line_checker_refuses_an_incomplete_line
# Needs nothing but the preamble and a shell, so it sits above every world this
# drive builds: the property it asserts is what makes those worlds cleanable.
case_a_killed_drive_still_runs_its_cleanups
# Needs the compose Postgres, which every case below here needs too. It sits
# above the scratch-database block deliberately: this one reads the cluster, it
# creates nothing, and a failure here is about the recipe rather than about
# this drive's own world.
case_the_census_recipes_are_legal_and_attribute_in_one_read

# --- the world the rest of the cases need ------------------------------------
#
# Everything below here needs a receiver. Its absence is could-not-look, never a
# pass: a drive that reported "2 passed" over a server that never started is
# exactly the shape a field test once spent a session on.
# Derived from this checkout's path, like every other database name here, and
# short by construction rather than by luck: `db_name` on a long branch plus a
# suffix can reach the 63-byte ceiling `db_valid_name` refuses at, and a drive
# that refuses on a long branch name is a drive that stops running for a reason
# nobody connects to the branch they cut. `test_djb_` is the prefix
# `scripts/db_sweep.sh` already brooms, so a killed run leaves nothing orphaned.
SCRATCH_DB="test_djb_rbk_$(db_path_hash "$ROOT" 12)"
db_valid_name "$SCRATCH_DB" || cannot_look "the derived scratch database name is not a name: ${SCRATCH_DB}"

# BEFORE the database exists, deliberately: this reads settings, not rows, and
# asking now means the exit cleanup knows where this run's work lands even if
# every line below it fails. See `runbook_receiver.py::_world` for why the two
# values are asked for rather than derived in this file.
WORLDFILE="${WORK}/world.env"
if (cd "$ROOT" && DATABASE_NAME="$SCRATCH_DB" uv run python "$HARNESS" world) >"$WORLDFILE" 2>"${WORK}/world.log"; then
    # shellcheck disable=SC1090
    . "$WORLDFILE"
fi
[ -n "$DRIVE_QUEUE" ] ||
    cannot_look "the harness would not say which Temporal task queue this run's work lands on — see ${WORK}/world.log. Without it this drive cannot clean up after itself, and running it anyway is how a thousand executions accumulated."

echo "   queue:    ${DRIVE_QUEUE} (this drive terminates what it starts on it)"
echo "   database: ${SCRATCH_DB} (created here, dropped at exit)"
db_create "$SCRATCH_DB" >"${WORK}/db.log" 2>&1 ||
    cannot_look "could not create ${SCRATCH_DB} — is the compose stack up? (scripts/setup.sh) — see ${WORK}/db.log"
DATABASE_NAME="$SCRATCH_DB" uv run python manage.py migrate --noinput >"${WORK}/migrate.log" 2>&1 ||
    cannot_look "could not migrate ${SCRATCH_DB} — see ${WORK}/migrate.log"

ENVFILE="${WORK}/receiver.env"
DATABASE_NAME="$SCRATCH_DB" uv run python "$HARNESS" serve "$ENVFILE" >"${WORK}/receiver.log" 2>&1 &
RECEIVER_PID=$!

WAITED=0
while [ ! -s "$ENVFILE" ]; do
    if ! kill -0 "$RECEIVER_PID" 2>/dev/null; then
        sed 's/^/     | /' "${WORK}/receiver.log" | tail -30 >&2
        cannot_look "the receiver died before it was listening — transcript above"
    fi
    WAITED=$((WAITED + 1))
    [ "$WAITED" -lt 120 ] || cannot_look "the receiver did not come up within 60s"
    sleep 0.5
done
# shellcheck disable=SC1090
. "$ENVFILE"
[ "${RECEIVER_READY:-}" = "1" ] || cannot_look "the receiver wrote an env file it did not finish"
echo "   receiver: http://${HOST} (pid ${RECEIVER_PID})"

# The secret the drive gives recipe 1 and then signs with. Published here and
# therefore worth nothing: it lives in one scratch database for thirty seconds.
WHSEC="whsec_cnVuYm9va2RyaXZlc2NyYXRjaHNlY3JldA"  # pragma: allowlist secret — a scratch database, dropped at exit
SECRET="$WHSEC"
CONNECTION_ID=""

case_the_connection_recipe_creates_the_connection
case_the_v2_recipe_lands_an_engagement
case_the_v2_recipe_as_printed_bounces_the_message
case_the_legacy_recipe_lands_an_engagement
case_the_legacy_recipe_as_printed_bounces_the_message
case_the_vendor_signed_recipes_bind_their_symbols
# LAST, and it has to be: it asserts against everything the cases above started.
case_the_drive_terminates_the_runs_it_started

echo
echo "== ${PASSED} passed, ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
