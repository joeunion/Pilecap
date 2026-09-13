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
set -euo pipefail

# The drive for two sentinel-fenced steps of `scripts/setup.sh`: the environment
# step (`env_sync_from_example` and its two helpers) and the services step
# (`services_up`, which pulls before it starts and refuses when the pull fails).
# Both are fenced for the same reason — the rest of that script brings up docker,
# syncs a venv and talks to an identity provider, and a drive that needed any of
# that would be could-not-look on the machine that most needs it.
#
#   ./scripts/tests/test_setup_env.sh          run every case
#   ./scripts/tests/test_setup_env.sh --list   name them and stop
#
# WHY IT EXISTS. The per-rung ledger keys a banked verdict partly on a digest of
# `.env` — every line of it, in file order, comments and blanks included, minus
# the keys a deriver declares (`loop_env_fingerprint`, `scripts/gate_ledger.sh`).
# A verifier's clone builds its `.env` from `.env.example` and substitutes the
# derived database name and the identity carry in place, so a builder's checkout
# reuses that clone's verdict only while its own `.env` is the same skeleton.
# The environment step used to leave an existing `.env` alone, so every checkout
# drifted one line further from the example on every merge that touched it, and
# a consult that should have cost a second re-measured the whole suite instead
# (measured on this box, 2026-09-07: 162s against 1s, and 592 lines of
# difference in prose alone).
#
# So the step now REGENERATES the file, and every failure mode of a regeneration
# is expensive in a different direction:
#
#   * a value silently lost — the checkout's database name, its identity
#     credential, anything a human typed. The drive asserts the whole result
#     byte-for-byte against a file written out in full below, and asserts
#     separately that a value carrying an `=` and a value carrying a `#` come
#     through unchanged: those are the two shapes a key/value split gets wrong.
#   * a key the example has since dropped, dropped with it. The drive asserts
#     the kept block, by name and position.
#   * a VALUE ON STDOUT. The report block names keys and counts them; the first
#     key this file carries is a machine credential and a setup log gets pasted
#     into reports. The drive greps the whole block for `=` and fails on a hit.
#   * a run that is not idempotent — a kept block appended twice, a line moved —
#     which would make every second `setup.sh` a fresh digest and put the miss
#     straight back.
#
# IT NEVER RUNS `setup.sh`, AND IT NEVER TALKS TO A REAL DAEMON. It EXTRACTS the
# fenced blocks — between the `env-sync` sentinels, and between the `services`
# ones — and sources them into a scratch directory with `make_tmp` stubbed and,
# for the services cases, a `docker` script first on PATH. The extraction is the
# precedent `scripts/loop_tier.sh` set reading `apps/conftest.py`: the real text
# runs, and a sentinel that is gone is could-not-look rather than a green run
# over a function nobody defined.
#
# WHY THE SERVICES STEP IS DRIVEN AT ALL (measured 2026-09-12). `compose.yaml`
# pinned `minio/minio:RELEASE.2025-09-07T16-13-09Z`; Docker Hub stopped serving
# that tag; `setup.sh` — the first thing a stranger runs — went straight to
# `docker compose up -d` and the failure arrived in compose's vocabulary, or as
# `wait_healthy` counting to 180 against a container that could not exist. The
# step now pulls first and a failed pull is exit 2 naming the image and its
# registry. A registry that has stopped serving a tag cannot be arranged on the
# box running this drive, so the shim is not a convenience: it is the only way
# this refusal can be driven anywhere.
#
# THE FIXTURES ARE BUILT HERE and live under `mktemp -d`. Nothing plants in this
# checkout's own `.env`, which is the one file in a worktree whose loss costs a
# human their afternoon.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE REST OF `setup.sh`. The call site is asserted as text — that the step
#     calls the function and that the mode-600 line still follows it — and
#     nothing here runs the step in a real checkout.
#   * THE REAL DIGEST. The digest case below holds a COPY of the drop-by-key
#     `awk` and the `shasum -a 256` that `gate_ledger.sh` uses, because sourcing
#     that file would drag in a venv census, git and a working tree. The copy is
#     a MODEL: it proves the agreement property (identical files agree, a kept
#     key differs) and it is anchored by one case that asserts the shipped
#     digest still has the same shape. A rule change in `gate_ledger.sh` that
#     kept that shape and changed the meaning would pass here.
#   * WHETHER `.env.example` IS ITSELF RIGHT. The regeneration trusts the
#     example's own syntax; a line the example gets wrong is copied wrong, and
#     that is deliberate — the example is the contract.
#   * A KEY A HUMAN SET BY HAND THAT THE EXAMPLE LACKS. It is kept, and it is an
#     honest permanent difference against any clone until the example grows the
#     key. The kept block names it; nothing here calls that a defect.
#   * THE COMMENTS A HUMAN ADDED to their own `.env`. They are not kept, on
#     purpose — the example owns the prose — and no case asserts otherwise.
#   * WHETHER A REAL REGISTRY SERVES A REAL TAG. The shim answers; nothing here
#     dials quay.io or Docker Hub. That a pin RESOLVES is a `docker manifest
#     inspect` on a box with network, run by hand and pasted — never a case,
#     because a case that needed the internet would be red on an aeroplane and
#     green nowhere useful.
#   * WHETHER `docker compose config --images` ANSWERS THE WAY THE SHIM DOES.
#     The shim reads the scratch compose file's `image:` lines, which is what
#     that subcommand answers for a file with no build stanzas and no variable
#     substitution. A compose file whose image came from a `${VAR}` or a build
#     would be rendered by real compose and copied verbatim by the shim.
#   * THE REAL PULL, AND WHAT IT COSTS. Nothing here measures the wall clock a
#     `compose pull` adds to a fresh `setup.sh`, nor the reuse path on a box
#     where one service of seven is unhealthy (there the step pulls all seven).

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_setup_env: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's scratch work inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_setup_env: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    # A mistyped flag is never a silently different run.
    echo "!! unknown argument '$1': test_setup_env.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v shasum >/dev/null 2>&1 || cannot_look "no shasum on PATH — the digest case cannot be computed"
[ -f scripts/setup.sh ] || cannot_look "scripts/setup.sh is not in this tree — there is nothing to drive"
[ -f scripts/gate_ledger.sh ] || cannot_look "scripts/gate_ledger.sh is not in this tree — the digest anchor cannot be read"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the wiring cannot be read"

ROOT="$PWD"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-setup-env-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- THE EXTRACTION, and the drive's honest could-not-look --------------------
#
# The sentinels are assembled rather than written at the head of a line, so a
# reader grepping the tree for the fence finds `setup.sh` and not this file too.
SENT_OPEN="# >>> env-sync >>>"
SENT_CLOSE="# <<< env-sync <<<"
EXTRACT="${WORK}/env_sync.sh"

sed -n "/^${SENT_OPEN}\$/,/^${SENT_CLOSE}\$/p" scripts/setup.sh >"$EXTRACT" 2>/dev/null || true

grep -qxF "$SENT_OPEN" "$EXTRACT" 2>/dev/null ||
    cannot_look "scripts/setup.sh has no line reading exactly \`${SENT_OPEN}\` — the env-sync fence is gone (or was never there, which is what a baseline tree looks like). Every case below sources the text between that sentinel and \`${SENT_CLOSE}\`, so there is no function to drive."
grep -qxF "$SENT_CLOSE" "$EXTRACT" 2>/dev/null ||
    cannot_look "scripts/setup.sh opens the env-sync fence with \`${SENT_OPEN}\` and never closes it with \`${SENT_CLOSE}\`. The extraction ran to the end of the file."
grep -q '^env_sync_from_example() {' "$EXTRACT" ||
    cannot_look "the env-sync fence in scripts/setup.sh defines no env_sync_from_example — the function this drive exists for is not inside its own sentinels."

# `make_tmp` is `setup.sh`'s, and it is not inside the fence: it owns a
# process-wide registry and an EXIT trap that a drive must not inherit. The stub
# has the one property the fenced code relies on — it ASSIGNS to the variable
# named by its argument and prints nothing (a `$(...)` form would run in a
# subshell and the assignment would not survive it).
make_tmp() {
    local __t="$1"
    printf -v "$__t" '%s' "$(mktemp "${WORK}/tmp.XXXXXXXX")"
}

# shellcheck source=/dev/null
. "$EXTRACT"
command -v env_sync_from_example >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted fence defined no env_sync_from_example"

# --- THE SECOND FENCE: the services step --------------------------------------
#
# Same mechanism, same reason. The services step pulls before it starts and
# REFUSES when the pull fails, which is a thing that can only be driven with a
# docker that is not this box's — so the step lives inside its own sentinels and
# the cases below source it beside a shim.
SENT_SVC_OPEN="# >>> services >>>"
SENT_SVC_CLOSE="# <<< services <<<"
EXTRACT_SVC="${WORK}/services.sh"

sed -n "/^${SENT_SVC_OPEN}\$/,/^${SENT_SVC_CLOSE}\$/p" scripts/setup.sh >"$EXTRACT_SVC" 2>/dev/null || true

grep -qxF "$SENT_SVC_OPEN" "$EXTRACT_SVC" 2>/dev/null ||
    cannot_look "scripts/setup.sh has no line reading exactly \`${SENT_SVC_OPEN}\` — the services fence is gone (or was never there, which is what a baseline tree looks like). The pull-failure cases below source the text between that sentinel and \`${SENT_SVC_CLOSE}\`, so there is no step to drive."
grep -qxF "$SENT_SVC_CLOSE" "$EXTRACT_SVC" 2>/dev/null ||
    cannot_look "scripts/setup.sh opens the services fence with \`${SENT_SVC_OPEN}\` and never closes it with \`${SENT_SVC_CLOSE}\`. The extraction ran to the end of the file."
grep -q '^services_up() {' "$EXTRACT_SVC" ||
    cannot_look "the services fence in scripts/setup.sh defines no services_up — the step this drive exists to refuse for is not inside its own sentinels."

# The three names the fence stands on and does not define. They are `setup.sh`'s
# and they are OUTSIDE the fence on purpose — `SERVICES` is the contract about
# what a fresh clone needs up, and the two health helpers talk to a real daemon.
# `service_health` is a COPY of setup.sh's, minus its pipe: the shim answers one
# line anyway and a copy that reads the same first line is enough for a stub.
SERVICES=(db minio)
service_health() {
    local out
    out="$(docker compose ps --format '{{.Health}}' "$1" 2>/dev/null)"
    printf '%s\n' "${out%%$'\n'*}"
}
stack_is_healthy() {
    local service
    for service in "${SERVICES[@]}"; do
        [ "$(service_health "$service")" = "healthy" ] || return 1
    done
    return 0
}
# The stub SAYS SO when it is entered, because "wait_healthy is never entered"
# is half of what the refusal case asserts and an absence nobody can see is not
# an assertion.
wait_healthy() {
    echo "wait_healthy ENTERED for $1"
    return 0
}

# shellcheck source=/dev/null
. "$EXTRACT_SVC"
command -v services_up >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted services fence defined no services_up"
command -v image_registry_host >/dev/null 2>&1 ||
    cannot_look "sourcing the extracted services fence defined no image_registry_host — the refusal cannot name a registry it cannot read"

# --- the assertions -----------------------------------------------------------
CURRENT=""
RC=0
OUT=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -25
    fi
    FAILED=$((FAILED + 1))
}

exits() {
    if [ "$RC" -eq "$1" ]; then
        ok "exit ${RC}"
    else
        bad "wanted exit $1, got ${RC}"
    fi
}

says() {
    if grep -qF -- "$1" "$OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

files_match() {
    # $1 what · $2 got · $3 wanted
    if cmp -s "$2" "$3"; then
        ok "$1 is byte-identical"
    else
        bad "$1 differs — diff (got | wanted) follows"
        diff "$2" "$3" | sed 's/^/             | /' | head -40 || true
    fi
}

file_has_line() {
    # $1 file · $2 the exact line
    if grep -qxF -- "$2" "$1"; then
        ok "${1##*/} carries the line \"$2\""
    else
        bad "${1##*/} does not carry the line \"$2\""
    fi
}

# --- the scratch world --------------------------------------------------------
#
# One directory per case, so a case can never read another's leftovers, and each
# one PRINTS what it planted: a fixture nobody saw arrive is a fixture that may
# not have arrived.
CASE_DIR=""
new_case_dir() {
    N=$((N + 1))
    CASE_DIR="${WORK}/case${N}"
    drive_require_scratch CASE_DIR "${CASE_DIR:-}"
    mkdir -p "$CASE_DIR"
}

plant() {
    # $1 filename (relative to CASE_DIR) · remaining args: the lines
    local name="$1"
    shift
    if [ "$#" -eq 0 ]; then
        : >"${CASE_DIR}/${name}"
    else
        printf '%s\n' "$@" >"${CASE_DIR}/${name}"
    fi
    echo "           planted ${CASE_DIR##*/}/${name} — $(wc -l <"${CASE_DIR}/${name}" | tr -d ' ') line(s)"
}

run_sync() {
    CURRENT="$1"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    local here="$PWD"
    cd "$CASE_DIR"
    RC=0
    env_sync_from_example >"$OUT" 2>&1 || RC=$?
    cd "$here"
    echo "           block:"
    sed 's/^/             > /' "$OUT"
}

# THE FIXTURE the criteria name: an example of six lines — three keys, two
# comments and one blank — and an environment holding two of those keys, one of
# them with a different value, plus one key the example does not have, in a
# different order.
plant_the_fixture() {
    new_case_dir
    plant .env.example \
        '# the first key' \
        'ALPHA=one' \
        'BETA=two' \
        '' \
        '# the third key' \
        'GAMMA=three'
    plant .env \
        'GAMMA=three' \
        'DELTA=kept-value' \
        'ALPHA=changed'
}

# THE EXPECTED RESULT, written out in full rather than computed: a drive that
# builds its expectation with the same rules as the code under it agrees with
# that code by construction and proves nothing.
plant_the_expectation() {
    printf '%s\n' \
        '# the first key' \
        'ALPHA=changed' \
        'BETA=two' \
        '' \
        '# the third key' \
        'GAMMA=three' \
        '' \
        '# --- kept from a previous .env: not in .env.example ---' \
        'DELTA=kept-value' >"${WORK}/expected.env"
}

case_the_result_is_the_example_with_the_values_carried_over() {
    plant_the_fixture
    plant_the_expectation
    cp "${CASE_DIR}/.env" "${WORK}/original.env"
    run_sync "a drifted .env is regenerated"
    exits 0
    files_match ".env" "${CASE_DIR}/.env" "${WORK}/expected.env"
}

case_the_changed_value_sits_at_the_examples_position() {
    # Line 2 of the example is ALPHA; line 2 of the result must be ALPHA with
    # the file's value. Asserted as a POSITION, because "the value survived
    # somewhere" is what an append-the-missing-keys shape would also satisfy,
    # and that shape is exactly what does not hit the digest.
    CURRENT="the carried value keeps the example's position"
    local got
    got="$(sed -n '2p' "${CASE_DIR}/.env")"
    if [ "$got" = "ALPHA=changed" ]; then
        ok "line 2 is the example's ALPHA line carrying the file's value"
    else
        bad "line 2 is \"${got}\" and should be the example's ALPHA line"
    fi
}

case_the_extra_key_sits_after_the_marker() {
    CURRENT="a key the example lacks is kept under the marker"
    local marker_line delta_line
    marker_line="$(grep -nxF '# --- kept from a previous .env: not in .env.example ---' "${CASE_DIR}/.env" | cut -d: -f1 || true)"
    delta_line="$(grep -nxF 'DELTA=kept-value' "${CASE_DIR}/.env" | cut -d: -f1 || true)"
    if [ -n "$marker_line" ] && [ -n "$delta_line" ] && [ "$delta_line" -gt "$marker_line" ]; then
        ok "the marker is at line ${marker_line} and the kept key at ${delta_line}"
    else
        bad "marker at \"${marker_line:-none}\", kept key at \"${delta_line:-none}\""
    fi
}

case_the_block_counts_one_added_one_preserved_one_kept() {
    CURRENT="the report block counts what it did"
    says "1 key(s) added from .env.example: BETA"
    says "1 value(s) preserved in place: ALPHA"
    says "1 key(s) not in .env.example kept at the end: DELTA"
    says ".env.previous written"
}

case_the_block_never_prints_a_value() {
    # The criterion, and the reason it is a criterion: the first key a real
    # `.env` carries here is a machine credential, and this block goes into
    # terminals, logs and pasted reports. Any `=` at all is a leak — there is no
    # legitimate `=` in a block that prints names and counts.
    CURRENT="the report block prints names, never values"
    if grep -q '=' "$OUT"; then
        bad "the block contains an \"=\" — a value reached stdout"
        sed 's/^/             | /' "$OUT"
    else
        ok "no \"=\" anywhere in the block"
    fi
}

case_the_previous_file_is_the_original() {
    CURRENT=".env.previous is the file that was there before"
    files_match ".env.previous" "${CASE_DIR}/.env.previous" "${WORK}/original.env"
    local mode
    mode="$(ls -l "${CASE_DIR}/.env.previous" 2>/dev/null | cut -c1-10 || true)"
    if [ "$mode" = "-rw-------" ]; then
        ok "mode is owner-only (${mode})"
    else
        bad "mode is ${mode} and should be -rw------- : that file is a whole copy of the environment"
    fi
}

case_a_second_run_changes_nothing_and_says_so() {
    cp "${CASE_DIR}/.env" "${WORK}/after-first-run.env"
    run_sync "a second run on the result"
    exits 0
    files_match ".env after a second run" "${CASE_DIR}/.env" "${WORK}/after-first-run.env"
    files_match ".env.previous after a second run" "${CASE_DIR}/.env.previous" "${CASE_DIR}/.env"
    says ".env already matches .env.example's shape — nothing to do"
}

case_a_value_holding_an_equals_or_a_hash_survives() {
    # The two shapes a key/value split gets wrong, and both are ordinary in a
    # real `.env`: a URL with a query string, and a value with a `#` in it that
    # a comment-stripper would truncate.
    new_case_dir
    # The example carries a comment the environment does not, so the file is
    # genuinely rewritten here rather than found already correct — otherwise
    # this case would assert three lines that were never re-emitted.
    plant .env.example \
        '# the doors' \
        'URL=https://example.invalid/x' \
        'NOTE=plain' \
        'PLAIN=same'
    plant .env \
        'URL=https://example.invalid/x?a=b&c=d' \
        'NOTE=has # a hash and = an equals' \
        'PLAIN=same'
    run_sync "values carrying = and #"
    exits 0
    file_has_line "${CASE_DIR}/.env" 'URL=https://example.invalid/x?a=b&c=d'
    file_has_line "${CASE_DIR}/.env" 'NOTE=has # a hash and = an equals'
    file_has_line "${CASE_DIR}/.env" 'PLAIN=same'
    CURRENT="values carrying = and #"
    if [ "$(wc -l <"${CASE_DIR}/.env" | tr -d ' ')" = "4" ]; then
        ok "the result is the example's four lines and nothing appended"
    else
        bad "the result has $(wc -l <"${CASE_DIR}/.env" | tr -d ' ') lines, wanted 4"
    fi
}

case_no_env_at_all_copies_the_example() {
    new_case_dir
    plant .env.example \
        '# a comment' \
        'ALPHA=one' \
        'BETA=two'
    run_sync "a checkout with no .env"
    exits 0
    files_match ".env" "${CASE_DIR}/.env" "${CASE_DIR}/.env.example"
    says "0 value(s) preserved in place"
    says ".env.previous not written"
    CURRENT="a checkout with no .env"
    if [ -e "${CASE_DIR}/.env.previous" ]; then
        bad ".env.previous exists and there was no previous file to keep"
    else
        ok "no .env.previous, and the block says so rather than staying silent"
    fi
}

case_no_example_is_a_refusal_that_touches_nothing() {
    new_case_dir
    plant .env \
        'ALPHA=mine' \
        'BETA=also-mine'
    cp "${CASE_DIR}/.env" "${WORK}/untouched.env"
    run_sync "a checkout with no .env.example"
    exits 1
    says ".env.example"
    says "was not written and was not touched"
    files_match ".env" "${CASE_DIR}/.env" "${WORK}/untouched.env"
    CURRENT="a checkout with no .env.example"
    if [ -e "${CASE_DIR}/.env.previous" ]; then
        bad ".env.previous was written by a run that refused"
    else
        ok "nothing was written"
    fi
}

# --- the two states the function's own header argues about --------------------
#
# Both of these are ARGUED in the fence's header and neither was driven: the
# header is the only thing standing behind them, and a header is not an
# instrument. They are the mirror of the cases above — same fixtures, the two
# inputs the awk is shaped around rather than the ones a happy path produces.

case_an_empty_env_is_a_truncated_file_and_not_an_empty_environment() {
    # `env_sync_classify` keys its first-file test on `FILENAME == envfile`
    # rather than the usual `FNR == NR`, and the header says why in as many
    # words: an EMPTY first file yields no records, so `FNR == NR` would be true
    # for the SECOND file's first line and the example would be read as the
    # environment — silently classifying every key as "kept" and rebuilding the
    # file with the whole example appended under the marker. A zero-byte `.env`
    # is a real state here (a killed write, a truncating redirect), so the
    # outcome the header argues for is asserted: every key ADDED, none kept, the
    # result the example's own bytes, and the empty file still kept beside it.
    new_case_dir
    plant .env.example \
        '# the doors' \
        'ALPHA=one' \
        'BETA=two' \
        '' \
        'GAMMA=three'
    plant .env
    CURRENT="the planted .env is zero bytes"
    if [ ! -s "${CASE_DIR}/.env" ] && [ -f "${CASE_DIR}/.env" ]; then
        ok "the fixture is a file of 0 bytes, not an absent file"
    else
        bad "the fixture is not a zero-byte file — this case would drive the no-.env path instead"
    fi
    run_sync "a truncated .env of zero bytes"
    exits 0
    files_match ".env" "${CASE_DIR}/.env" "${CASE_DIR}/.env.example"
    says "3 key(s) added from .env.example: ALPHA BETA GAMMA"
    says "0 value(s) preserved in place"
    says "0 key(s) not in .env.example kept at the end"
    says ".env.previous written"
    CURRENT="a truncated .env of zero bytes"
    if grep -qxF '# --- kept from a previous .env: not in .env.example ---' "${CASE_DIR}/.env"; then
        bad "the marker is in the result — the example was read as the environment"
    else
        ok "no kept-block marker: the example was not mistaken for the environment"
    fi
    # NOTHING IS LOST: the truncated file is still the file `.env.previous`
    # holds, so the one step of reversibility the fence promises survives the
    # state where there was nothing to reverse to.
    if [ -f "${CASE_DIR}/.env.previous" ] && [ ! -s "${CASE_DIR}/.env.previous" ]; then
        ok ".env.previous is the zero-byte original, kept rather than skipped"
    else
        bad ".env.previous is missing or is not the zero-byte original"
    fi
    # NOTHING BY VALUE: the block names three keys and counts them, and the
    # empty-file path must not become the one place a value reaches stdout.
    if grep -q '=' "$OUT"; then
        bad "the block contains an \"=\" — a value reached stdout"
        sed 's/^/             | /' "$OUT"
    else
        ok "no \"=\" anywhere in the block"
    fi
}

case_a_key_present_twice_collapses_to_its_last_value() {
    # The header declares dotenv's own last-wins rule, applied where the file is
    # REBUILT rather than read: a key the file carries twice collapses to its
    # last value, ONCE, at the example's position. Every half of that is a way
    # to be wrong — first-wins, both lines emitted, or the duplicate demoted to
    # the kept block — and all three still look like a working sync.
    new_case_dir
    plant .env.example \
        '# the doors' \
        'ALPHA=one' \
        'BETA=two'
    plant .env \
        'ALPHA=first' \
        'BETA=two' \
        'ALPHA=last'
    run_sync "a key present twice with two values"
    exits 0
    says "1 value(s) preserved in place: ALPHA"
    says "0 key(s) added from .env.example"
    says "0 key(s) not in .env.example kept at the end"
    CURRENT="a key present twice with two values"
    local got count
    got="$(sed -n '2p' "${CASE_DIR}/.env")"
    if [ "$got" = "ALPHA=last" ]; then
        ok "line 2 is the example's ALPHA line carrying the LAST value"
    else
        bad "line 2 is \"${got}\" and should be ALPHA=last"
    fi
    count="$(grep -c '^ALPHA=' "${CASE_DIR}/.env" || true)"
    if [ "$count" = "1" ]; then
        ok "ALPHA appears exactly once in the result"
    else
        bad "ALPHA appears ${count} time(s) in the result, wanted 1"
    fi
    if grep -qxF 'ALPHA=first' "${CASE_DIR}/.env"; then
        bad "the first value survived — the rule is last-wins, not first-wins"
    else
        ok "the first value is gone"
    fi
    if [ "$(wc -l <"${CASE_DIR}/.env" | tr -d ' ')" = "3" ]; then
        ok "the result is the example's three lines and nothing appended"
    else
        bad "the result has $(wc -l <"${CASE_DIR}/.env" | tr -d ' ') lines, wanted 3"
    fi
}

# --- the digest ---------------------------------------------------------------
#
# A MODEL OF `loop_env_fingerprint`'s env-file component, not the function
# itself: the same drop-by-key `awk` and the same `shasum -a 256`. The case
# below it anchors the model against the shipped text, so a rewritten rule is at
# least visible here rather than silently modelled by the old one.
env_file_digest() {
    # $1 file · $2 newline-separated keys to drop
    DJB_LOOP_ENV_KEYS="$2" awk '
        BEGIN {
            n = split(ENVIRON["DJB_LOOP_ENV_KEYS"], k, "\n")
            for (i = 1; i <= n; i++) if (k[i] != "") drop[k[i]] = 1
        }
        {
            line = $0
            name = line
            sub(/=.*$/, "", name)
            gsub(/[ \t]/, "", name)
            if (name in drop) next
            print line
        }
    ' "$1" | shasum -a 256 | awk '{print $1}'
}

case_the_digest_agrees_when_the_files_agree() {
    CURRENT="the env-file digest over a regenerated file and its own clone"
    new_case_dir
    plant .env.example \
        '# the identity carry' \
        'ZITADEL_PAT=' \
        'DATABASE_NAME=djb_example' \
        '' \
        'ALPHA=one'
    plant .env \
        'ALPHA=one' \
        'ZITADEL_PAT=a-machine-credential' \
        'DATABASE_NAME=djb_the_builders_own'
    run_sync "the builder's file regenerated"
    exits 0

    # (b) the CLONE: the example with the same two lines substituted in place —
    # which is exactly what `verify_start.sh` writes.
    printf '%s\n' \
        '# the identity carry' \
        'ZITADEL_PAT=a-machine-credential' \
        'DATABASE_NAME=djb_the_clones_own' \
        '' \
        'ALPHA=one' >"${WORK}/clone.env"

    local a b c
    a="$(env_file_digest "${CASE_DIR}/.env" 'DATABASE_NAME')"
    b="$(env_file_digest "${WORK}/clone.env" 'DATABASE_NAME')"
    CURRENT="the env-file digest over a regenerated file and its own clone"
    if [ "$a" = "$b" ]; then
        ok "the builder's regenerated file and the clone's digest to the same value"
    else
        bad "the two digests differ — the regeneration does not produce the clone's skeleton"
        diff "${CASE_DIR}/.env" "${WORK}/clone.env" | sed 's/^/             | /' || true
    fi

    # (c) THE HONEST MISS: one key the example does not have. It is kept, it
    # changes the file, and the digest must SEE it — a digest that agreed here
    # would be a digest that had stopped reading the file.
    cp "${WORK}/clone.env" "${WORK}/clone-plus.env"
    printf '\n%s\n%s\n' '# --- kept from a previous .env: not in .env.example ---' 'MINE=set-by-hand' >>"${WORK}/clone-plus.env"
    c="$(env_file_digest "${WORK}/clone-plus.env" 'DATABASE_NAME')"
    CURRENT="the env-file digest over a file carrying a kept key"
    if [ "$c" != "$b" ]; then
        ok "a kept key the example lacks is a DIFFERENT digest — an honest, permanent miss until the example grows the key"
    else
        bad "a file with an extra key digests the same as one without it"
    fi
}

case_the_digest_model_still_matches_the_shipped_digest() {
    CURRENT="the digest model is anchored against gate_ledger.sh"
    local missing=""
    grep -qF 'if (name in drop) next' scripts/gate_ledger.sh || missing="${missing} the drop-by-key line"
    grep -qF 'sub(/=.*$/, "", name)' scripts/gate_ledger.sh || missing="${missing} the key split"
    grep -qF 'shasum -a 256' scripts/gate_ledger.sh || missing="${missing} shasum -a 256"
    if [ -z "$missing" ]; then
        ok "gate_ledger.sh still splits the key, drops the declared ones and hashes with shasum -a 256"
    else
        bad "the shipped digest no longer carries:${missing} — the model above is stale and the agreement case proves less than it claims"
    fi
}

# --- the services step: a pull failure is a refusal ---------------------------
#
# THE SHIM IS THE POINT. A registry that has stopped serving a pinned tag cannot
# be arranged on the box running this drive, and a case that waited for one
# would be could-not-look on every machine. So `docker` is a script first on
# PATH that RECORDS every invocation in order — the log IS the sequence, which
# is what lets a case assert that `up` never ran after a failed pull — and
# answers by knob. The shape is `deploy/tests/test_release.sh`'s stub docker.
DOCKER_LOG=""

plant_the_shim() {
    mkdir -p "${CASE_DIR}/bin"
    cat >"${CASE_DIR}/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"
case "$*" in
*"compose ps"*)
    printf '%s\n' "${DJB_DRIVE_HEALTH:-}"
    ;;
*"compose config --images"*)
    # What `docker compose config --images` answers: one fully-resolved image
    # reference per line, read here out of the scratch compose file the case
    # wrote rather than invented, so the census names what the case pinned.
    sed -n 's/^ *image: *//p' "$DJB_DRIVE_COMPOSE"
    ;;
*"compose pull"*)
    if [ "${DJB_DRIVE_PULL_RC:-0}" -ne 0 ]; then
        echo "${DJB_DRIVE_PLANTED_REF} Pulling"
        echo "Error response from daemon: manifest for ${DJB_DRIVE_PLANTED_REF} not found: manifest unknown" >&2
        exit "${DJB_DRIVE_PULL_RC}"
    fi
    echo "${DJB_DRIVE_PLANTED_REF} Pulled"
    ;;
esac
exit 0
DOCKER
    chmod +x "${CASE_DIR}/bin/docker"
    echo "           planted ${CASE_DIR##*/}/bin/docker — the shim, first on PATH"
}

plant_the_scratch_compose() {
    # $1 the minio reference this case pins. Two services, because a census that
    # only ever sees one line cannot show that it names each one's registry.
    plant compose.yaml \
        'services:' \
        '  db:' \
        '    image: postgres:17' \
        '  minio:' \
        "    image: $1"
}

run_services() {
    # $1 the case name · $2 the health the shim reports · $3 the pull rc ·
    # $4 the reference the shim names when it fails
    CURRENT="$1"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    DOCKER_LOG="${CASE_DIR}/docker.log"
    : >"$DOCKER_LOG"
    RC=0
    (
        export PATH="${CASE_DIR}/bin:$PATH"
        export DJB_DRIVE_DOCKER_LOG="$DOCKER_LOG"
        export DJB_DRIVE_COMPOSE="${CASE_DIR}/compose.yaml"
        export DJB_DRIVE_HEALTH="$2"
        export DJB_DRIVE_PULL_RC="$3"
        export DJB_DRIVE_PLANTED_REF="$4"
        services_up
    ) >"$OUT" 2>&1 || RC=$?
    echo "           output:"
    sed 's/^/             > /' "$OUT"
    echo "           every docker invocation, in order:"
    sed 's/^/             $ docker /' "$DOCKER_LOG"
}

log_says() {
    if grep -qF -- "$1" "$DOCKER_LOG"; then
        ok "docker was invoked with \"$1\""
    else
        bad "no docker invocation carries \"$1\""
    fi
}

log_never_says() {
    if grep -qF -- "$1" "$DOCKER_LOG"; then
        bad "docker WAS invoked with \"$1\" — and this case exists to prove it was not"
        sed 's/^/             $ docker /' "$DOCKER_LOG"
    else
        ok "docker was never invoked with \"$1\""
    fi
}

says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "never says \"$1\""
    fi
}

case_a_pull_failure_is_could_not_look_naming_the_image() {
    new_case_dir
    plant_the_scratch_compose 'minio/minio:RELEASE.9999-01-01T00-00-00Z'
    plant_the_shim
    run_services "a pull that fails is a refusal, not a start" \
        "" 1 "minio/minio:RELEASE.9999-01-01T00-00-00Z"
    exits 2
    says "COULD NOT LOOK"
    says "minio/minio:RELEASE.9999-01-01T00-00-00Z"
    # The registry host, derived rather than spelled: `minio/minio` has no host
    # segment, so it is Docker Hub — which is the whole of the finding.
    says "(registry docker.io)"
    says "NOTHING WAS STARTED"
    log_says "compose pull"
    log_never_says "compose up"
    says_not "wait_healthy ENTERED"
}

case_a_healthy_stack_is_reused_without_a_pull() {
    new_case_dir
    plant_the_scratch_compose 'quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z'
    plant_the_shim
    run_services "a healthy stack is reused and nothing is fetched" \
        "healthy" 0 "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z"
    exits 0
    says "reusing running stack"
    log_never_says "compose pull"
    log_never_says "compose up"
    says_not "wait_healthy ENTERED"
}

case_a_clean_pull_starts_the_stack_and_then_waits() {
    # The ordinary path, which is the one nobody would notice breaking: pull,
    # then up, then wait — in that order, with the order asserted rather than
    # assumed from the fact that all three happened.
    new_case_dir
    plant_the_scratch_compose 'quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z'
    plant_the_shim
    run_services "a clean pull starts the stack and waits for it" \
        "" 0 "quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z"
    exits 0
    log_says "compose pull"
    log_says "compose up -d"
    says "wait_healthy ENTERED for db"
    says "wait_healthy ENTERED for minio"
    says_not "COULD NOT LOOK"
    local pull_at up_at
    pull_at="$(grep -nF 'compose pull' "$DOCKER_LOG" | sed -n '1s/:.*//p' || true)"
    up_at="$(grep -nF 'compose up' "$DOCKER_LOG" | sed -n '1s/:.*//p' || true)"
    if [ -n "$pull_at" ] && [ -n "$up_at" ] && [ "$pull_at" -lt "$up_at" ]; then
        ok "the pull is invocation ${pull_at} and the up is ${up_at} — the pull comes first"
    else
        bad "pull at \"${pull_at:-none}\", up at \"${up_at:-none}\" — the pull does not precede the up"
    fi
}

case_a_reference_names_its_registry_the_way_docker_reads_one() {
    # The refusal's census is only worth reading if the host it prints is the
    # host docker would use. Docker's rule: the first path segment is a registry
    # only when it carries a dot or a colon, or is exactly `localhost`.
    CURRENT="image_registry_host reads a reference the way docker does"
    local ref want got
    while IFS='|' read -r ref want; do
        [ -n "$ref" ] || continue
        got="$(image_registry_host "$ref")"
        if [ "$got" = "$want" ]; then
            ok "${ref} → ${got}"
        else
            bad "${ref} → ${got}, wanted ${want}"
        fi
    done <<'REFS'
minio/minio:RELEASE.2025-09-07T16-13-09Z|docker.io
quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z|quay.io
ghcr.io/zitadel/zitadel:v4.17.1|ghcr.io
localhost:5000/thing:1|localhost:5000
postgres:17|docker.io
REFS
}

case_the_minio_pin_names_the_registry_that_serves_it() {
    # The pin itself, as a text census over compose.yaml: one minio image line, and
    # it carries a registry host — a bare `minio/…` is Docker Hub, which stopped
    # serving this tag on 2026-09-12.
    CURRENT="compose.yaml's minio pin"
    local lines count
    lines="$(grep -n 'image: .*minio' compose.yaml || true)"
    count="$(printf '%s\n' "$lines" | grep -c 'image:' || true)"
    if [ "$count" -eq 1 ]; then
        ok "exactly one minio image line: ${lines}"
    else
        bad "wanted exactly one minio image line, found ${count}: ${lines}"
    fi
    # NO PIPELINE HERE, and that is the point rather than a style choice: the
    # earlier shape was `printf … | grep -qF …`, a reader that short-circuits its
    # own producer at the tail of a pipeline under `pipefail` — over 64 KiB the
    # producer takes SIGPIPE and the pipeline's status is the wrong answer, every
    # run. `$lines` is already a shell string, so the membership test needs no
    # process at all.
    case "$lines" in
    *"quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z"*)
        ok "it names quay.io and keeps the release this tree has always pinned"
        ;;
    *)
        bad "it does not name quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z"
        ;;
    esac
    if grep -qF 'newest release published to' compose.yaml; then
        bad "the comment still claims a Docker Hub provenance the pin no longer has"
    else
        ok "the comment beside the pin no longer claims the tag comes from Docker Hub"
    fi
}

# --- the wiring ---------------------------------------------------------------

case_the_step_calls_services_up() {
    CURRENT="setup.sh's services step calls the fenced function"
    local step_line call_line up_line fence_line
    step_line="$(grep -nF 'step "services"' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    call_line="$(grep -nx 'services_up' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    if [ -n "$step_line" ] && [ -n "$call_line" ] && [ "$call_line" -gt "$step_line" ]; then
        ok "the step at line ${step_line} calls services_up at ${call_line}"
    else
        bad "step at \"${step_line:-none}\", call at \"${call_line:-none}\""
    fi
    # THE CONTROL for the replaced shape: the one `up -d` left in the
    # file is inside the fence, below `services_up`. An `up -d` above it is the
    # baseline's unguarded start, back again.
    fence_line="$(grep -nF "$SENT_SVC_OPEN" scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    up_line="$(grep -nF 'docker compose up -d' scripts/setup.sh | sed -n '1s/:.*//p' || true)"
    if [ -n "$fence_line" ] && [ -n "$up_line" ] && [ "$up_line" -gt "$fence_line" ]; then
        ok "the only \`docker compose up -d\` (line ${up_line}) sits inside the services fence (opened at ${fence_line})"
    else
        bad "fence opens at \"${fence_line:-none}\", the first \`docker compose up -d\` is at \"${up_line:-none}\" — a start outside the fence pulls nothing first"
    fi
}

case_the_step_calls_the_function() {
    CURRENT="setup.sh's environment step calls the function"
    local step_line call_line chmod_line
    step_line="$(grep -nF 'step "environment file"' scripts/setup.sh | head -1 | cut -d: -f1 || true)"
    call_line="$(grep -nx 'env_sync_from_example' scripts/setup.sh | head -1 | cut -d: -f1 || true)"
    chmod_line="$(grep -nx 'chmod 600 .env' scripts/setup.sh | head -1 | cut -d: -f1 || true)"
    if [ -n "$step_line" ] && [ -n "$call_line" ] && [ -n "$chmod_line" ] &&
        [ "$call_line" -gt "$step_line" ] && [ "$chmod_line" -gt "$call_line" ]; then
        ok "the step calls it at line ${call_line} and the owner-only chmod still follows at ${chmod_line}"
    else
        bad "step at \"${step_line:-none}\", call at \"${call_line:-none}\", chmod at \"${chmod_line:-none}\""
    fi
}

case_the_superseded_sentence_is_gone() {
    CURRENT="the sentence the step no longer means is gone"
    if grep -qF 'already present, leaving it alone' scripts/setup.sh; then
        bad "setup.sh still says it leaves an existing .env alone, and it does not"
    else
        ok "setup.sh no longer claims to leave an existing .env alone"
    fi
}

case_the_previous_file_is_ignored_by_git() {
    # The file holds a whole copy of the environment, credential included. It is
    # covered by the `.env.*` line rather than a line of its own, and this case
    # is what tells the two apart if that line ever narrows.
    CURRENT=".env.previous is ignored by git"
    if git check-ignore -q .env.previous 2>/dev/null; then
        ok "git ignores .env.previous"
    else
        bad "git does NOT ignore .env.previous — a full copy of the environment is stageable"
    fi
}

case_the_drive_is_registered_in_the_gate() {
    CURRENT="this drive runs in the gate's selftest leg"
    if grep -qF 'scripts/tests/test_setup_env.sh' scripts/check.sh; then
        ok "check.sh calls it"
    else
        bad "check.sh does not call it — an unregistered drive is a drive nobody runs"
    fi
}

echo "test_setup_env: driving the two fences extracted from scripts/setup.sh"
echo "           env-sync: $(wc -l <"$EXTRACT" | tr -d ' ') line(s) between the sentinels into ${EXTRACT}"
echo "           services: $(wc -l <"$EXTRACT_SVC" | tr -d ' ') line(s) between the sentinels into ${EXTRACT_SVC}"

case_the_result_is_the_example_with_the_values_carried_over
case_the_changed_value_sits_at_the_examples_position
case_the_extra_key_sits_after_the_marker
case_the_block_counts_one_added_one_preserved_one_kept
case_the_block_never_prints_a_value
case_the_previous_file_is_the_original
case_a_second_run_changes_nothing_and_says_so
case_a_value_holding_an_equals_or_a_hash_survives
case_no_env_at_all_copies_the_example
case_no_example_is_a_refusal_that_touches_nothing
case_an_empty_env_is_a_truncated_file_and_not_an_empty_environment
case_a_key_present_twice_collapses_to_its_last_value
case_the_digest_agrees_when_the_files_agree
case_the_digest_model_still_matches_the_shipped_digest
case_a_pull_failure_is_could_not_look_naming_the_image
case_a_healthy_stack_is_reused_without_a_pull
case_a_clean_pull_starts_the_stack_and_then_waits
case_a_reference_names_its_registry_the_way_docker_reads_one
case_the_minio_pin_names_the_registry_that_serves_it
case_the_step_calls_services_up
case_the_step_calls_the_function
case_the_superseded_sentence_is_gone
case_the_previous_file_is_ignored_by_git
case_the_drive_is_registered_in_the_gate

echo "test_setup_env: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! EITHER the services step no longer pulls before it starts — so a registry" >&2
    echo "   that has dropped a pinned tag is a timeout inside \`up\` again instead of a" >&2
    echo "   refusal naming the image — the failure that cost a fresh clone its files" >&2
    echo "   store on 2026-09-12" >&2
    echo "   — or it refuses when it should reuse, and every setup.sh in the house now" >&2
    echo "   spends the network on a stack that was already healthy." >&2
    echo "   OR the environment step no longer regenerates .env from .env.example the way a" >&2
    echo "   verifier's clone builds its own — or it does, and has started losing a value," >&2
    echo "   dropping a key, printing one, or rewriting the file on a second run. All four" >&2
    echo "   halves are load-bearing: the first puts every builder's consult back to" >&2
    echo "   re-measuring the whole suite, and the others cost a credential, a setting or" >&2
    echo "   an afternoon." >&2
    exit 1
fi
exit 0
