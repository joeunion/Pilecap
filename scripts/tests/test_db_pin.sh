#!/usr/bin/env bash
# The drive for the gate's `db-pin` leg — `db_pin_leg` in `scripts/db.sh`, the
# refusal that stands between a stale `.env` pin and a checkout quietly running
# two databases.
#
#   ./scripts/tests/test_db_pin.sh          run every case
#   ./scripts/tests/test_db_pin.sh --list   name them and stop
#
# WHY IT EXISTS. `scripts/db.sh` derives this checkout's database name from the
# checkout's own path; `.env` is what a bare `manage.py` reads. When those two
# disagree the scripts migrate, seed and gate one database while every
# `manage.py` a human types reaches another — which is how a PM debugging a 500
# migrated and minted tokens into the OWNER'S live development database, with
# every individual step of it legal and none of it visible.
#
# THE PREVIOUS FIX WAS A NOTE, AND THE NOTE DID NOT WORK. db.sh has printed the
# disagreement on stderr on every source for a while; a later census
# then found the MAIN checkout's pin still stale a full day later, with 63
# stale worktree pins beside it. So the disagreement now has an exit status,
# in `--fast`, where pre-commit meets it. A refusal that decides whether a
# commit lands is a refusal that has to be driven — the same argument already
# made for `backup.sh` and `sweep.sh`.
#
# IT BUILDS ITS OWN CHECKOUTS. `db_pin_leg` asks git for a top level and reads
# the `.env` beside it; nothing else. So a throwaway repository under
# `mktemp -d` with a two-line `.env` in it IS a checkout as far as the leg is
# concerned, and every case is arranged that way. THE FILE ITSELF IS WHAT RUNS
# — `scripts/db.sh` is sourced, not copied — so there is no stub to drift.
#
# NOTHING IS PLANTED IN THIS TREE, unlike its sibling `test_secrets_scan.sh`,
# and that is deliberate rather than a shortcut: the only thing a real-tree
# plant would add here is a `.env` overwrite in a checkout whose `.env` holds
# the Zitadel PAT, and a copy of that file under `mktemp -d` is a worse leak
# than the coverage is worth. The scratch checkouts exercise the identical
# function.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * WHETHER THE GATE HONOURS THE LEG'S EXIT STATUS AT RUNTIME. The full gate
#     holds a per-checkout lock while the selftest leg runs, and `--fast`
#     REFUSES while that lock is held (check.sh's lock section), so this driver
#     cannot run the real gate from inside itself the way it would like to.
#     `case_the_leg_is_wired_into_the_fast_tier` reads check.sh as TEXT instead
#     — the call site, the FULL_LEGS entry, and the one property the whole rung
#     rests on: that the call sits ABOVE the `--fast` early exit. That is a
#     weaker proof than running it and it is named as one.
#   * WHICH OF THE TWO NAMES IS RIGHT. The leg reports a disagreement, never a
#     wrongness; intent is not a thing a script can read. Nothing here asserts
#     otherwise.
#   * A `DATABASE_NAME` FROM ANYWHERE BUT THE CHECKOUT ROOT'S `.env` — a shell
#     profile's export, or a `DJANGO_SETTINGS_MODULE` pointing at its own
#     environment file. Both are outside the leg by design and outside this
#     driver with it.
#   * THE DERIVATION ITSELF. `db_name`'s branch sanitising, its 38-byte cap and
#     its path hash are another file's subject; every case here asks `db_name`
#     what it says and drives the COMPARISON against that answer.
set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
#
# A drive run from the pre-push hook inherits an absolute `GIT_DIR` from
# `git -C <linked worktree> push`, and an inherited `GIT_DIR` OVERRIDES `-C`.
# That is how `scripts/tests/test_pm_merge.sh` built its scenario in the REAL
# repository three pushes running. This drive's `fresh_checkout` is the same
# `git -C "$REPO" init` construction, and `db_pin_leg` itself asks git for a
# top level — which an inherited `GIT_DIR` answers with the pushing worktree,
# not the scratch checkout the case built. The preamble unsets that
# environment, guards the scratch paths, and fingerprints this checkout.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_db_pin: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_db_pin: $*" >&2
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
    echo "!! unknown argument '$1': test_db_pin.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/db.sh ] || cannot_look "scripts/db.sh is not in this tree — there is nothing to drive"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the wiring cannot be read"

ROOT="$PWD"

# The real file, sourced. Sourcing it also runs its source-time note, which is
# harmless here and is itself one of the cases below.
# shellcheck source=scripts/db.sh
. scripts/db.sh
command -v db_pin_leg >/dev/null 2>&1 || cannot_look "scripts/db.sh defines no db_pin_leg — the leg body is gone"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-db-pin-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# --- the assertions ----------------------------------------------------------
CURRENT=""
RC=0
OUT=""
N=0

# --- the scratch checkout ------------------------------------------------------
# A repository with nothing in it but a commit: db_pin_leg reads a top level and
# the `.env` beside it, and cares about nothing else in the tree.
REPO=""
DERIVED=""
fresh_checkout() {
    N=$((N + 1))
    REPO="${WORK}/checkout${N}"
    # THE BELT, and it comes before the `mkdir` as well as before the
    # first git command. `git -C "" ...` is a no-op chdir, not a refusal: every
    # command after it lands on whatever repository this process is standing in.
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "db pin drive"
    echo "a checkout" >"$REPO/README"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m "base"
    # What the leg will derive here. Asked, never assumed: the derivation's own
    # rules are scripts/db.sh's subject, not this driver's.
    DERIVED="$(cd "$REPO" && db_name)"
    [ -n "$DERIVED" ] || cannot_look "db_name derived nothing in a scratch checkout"
}

write_env() {
    printf '%s\n' "$@" >"$REPO/.env"
}

# Run the real leg with the scratch checkout as the working directory. Not a
# subshell for the exit status alone — the output is half of what is asserted,
# so both are kept.
run_leg_in() {
    local dir="$1" here
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    here="$PWD"
    cd "$dir"
    RC=0
    db_pin_leg >"$OUT" 2>&1 || RC=$?
    cd "$here"
}

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -n "$OUT" ] && [ -f "$OUT" ] && sed 's/^/             | /' "$OUT" | tail -25
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

says_not() {
    if grep -qF -- "$1" "$OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}

silent() {
    if [ -s "$OUT" ]; then
        bad "printed something and must be silent — $(tr '\n' ' ' <"$OUT")"
    else
        ok "silent"
    fi
}

# --- the cases ----------------------------------------------------------------

case_a_stale_pin_is_refused() {
    # THE SEAM. An unmarked pin that is not the derivation: two databases, one
    # checkout, and until this leg existed nothing that had to be answered.
    fresh_checkout
    write_env "DATABASE_NAME=djb_main" "DEBUG=1"
    run_leg_in "$REPO" "a stale, unmarked pin"
    exits 1
    # BOTH names, because a refusal that names one of them is a puzzle: the
    # reader has to know which name they are looking at to pick a fix.
    says "djb_main"
    says "$DERIVED"
    # BOTH fixes, because the leg does not know which one is meant.
    says "# pinned"
    says "./scripts/setup.sh"
}

case_the_refusal_says_what_the_disagreement_costs() {
    # A refusal a reader can act on without going and reading db.sh's header.
    fresh_checkout
    write_env "DATABASE_NAME=djb_stale_pin"
    run_leg_in "$REPO" "the refusal's sentence"
    says "DISAGREE"
    says "manage.py"
    says "TWO databases"
}

case_a_pinned_line_passes_silently() {
    # The marker is the checkout saying it meant this name. A pin is legal
    # (db.sh rule 1); what the marker buys is silence, so the leg can never
    # become noise a deliberate checkout learns to skip.
    fresh_checkout
    write_env "DATABASE_NAME=djb_main  # pinned" "DEBUG=1"
    run_leg_in "$REPO" "a pinned line"
    exits 0
    silent
}

case_the_marker_must_be_on_the_database_name_line() {
    # `# pinned` somewhere else in the file is not this line's marker. Without
    # this case the marker grep could lose its anchor and silence every
    # checkout whose .env happens to carry the word.
    fresh_checkout
    write_env "# pinned — a comment about something else entirely" \
        "DATABASE_NAME=djb_main" "REDIS_URL=redis://localhost"
    run_leg_in "$REPO" "the marker on another line"
    exits 1
    says "$DERIVED"
}

case_no_env_file_at_all_passes() {
    # No file, no second opinion: the derivation is the only name in play, so
    # there is nothing to disagree with. A fresh clone is in this state and
    # must not be refused for it.
    fresh_checkout
    rm -f "$REPO/.env"
    run_leg_in "$REPO" "no .env at all"
    exits 0
    says "no .env"
}

case_an_env_with_no_database_name_line_passes() {
    fresh_checkout
    write_env "DEBUG=1" "REDIS_URL=redis://localhost"
    run_leg_in "$REPO" "an .env that pins no name"
    exits 0
    says "pins no DATABASE_NAME"
}

case_a_pin_that_agrees_passes() {
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    run_leg_in "$REPO" "a pin equal to the derivation"
    exits 0
    says "agree"
}

case_a_pin_that_agrees_and_is_marked_passes() {
    # The state `setup.sh` leaves a checkout in that reconciled AND then pinned:
    # agreement is checked before the marker, so this passes on the agreement
    # and the marker changes nothing.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}  # pinned"
    run_leg_in "$REPO" "a marked pin that also agrees"
    exits 0
}

case_a_quoted_pin_that_agrees_passes() {
    # django-environ strips a surrounding quote pair, so a hand-written
    # `DATABASE_NAME="djb_x"` resolves to djb_x and the leg must compare the
    # same way. The quote-stripping in `db_env_file_pin` was written with
    # `'*'` as a case pattern — the literal three characters — and therefore
    # matched nothing; this case is why it is now `\'*\'`, and is what keeps it
    # that way.
    fresh_checkout
    write_env "DATABASE_NAME=\"${DERIVED}\""
    run_leg_in "$REPO" "a double-quoted pin that agrees"
    exits 0
    says "agree"
    fresh_checkout
    write_env "DATABASE_NAME='${DERIVED}'"
    run_leg_in "$REPO" "a single-quoted pin that agrees"
    exits 0
    says "agree"
}

case_the_last_database_name_line_wins() {
    # django-environ's reading, and `backup.sh::env_value`'s: last wins. A
    # first-wins reading would clear a checkout whose live pin is stale.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DATABASE_NAME=djb_stale_second"
    run_leg_in "$REPO" "a stale LAST line under a good first one"
    exits 1
    says "djb_stale_second"

    fresh_checkout
    write_env "DATABASE_NAME=djb_stale_first" "DATABASE_NAME=${DERIVED}"
    run_leg_in "$REPO" "a good LAST line under a stale first one"
    exits 0
    says "agree"
}

case_an_unreadable_env_cannot_look() {
    # An .env that exists and cannot be read is NOT an absent one: nothing was
    # compared, so it is neither a finding nor a pass, and the gate turns it
    # into exit 2. Root can read anything, so there the case cannot be posed.
    if [ "$(id -u)" = "0" ]; then
        CURRENT="an unreadable .env"
        OUT=""
        ok "not driven as root — chmod cannot pose the case (declared, not skipped quietly)"
        return 0
    fi
    fresh_checkout
    write_env "DATABASE_NAME=djb_main"
    chmod 000 "$REPO/.env"
    run_leg_in "$REPO" "an unreadable .env"
    chmod 600 "$REPO/.env"
    exits 2
    says "cannot be read"
}

case_the_source_time_note_points_at_the_leg() {
    # The note is the DEMOTED half now. It still fires — a script run
    # outside the gate deserves the heads-up — but it must send the reader to
    # the thing with an exit status rather than restate the fixes, so there is
    # exactly one place that spells them out.
    fresh_checkout
    write_env "DATABASE_NAME=djb_main"
    CURRENT="the source-time note"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$REPO"
        unset DATABASE_NAME
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh"
    ) >"$OUT" 2>&1 || RC=$?
    exits 0
    says "note: DATABASE_NAME pinned to djb_main"
    says "db-pin leg"
    says "check.sh"
}

case_the_note_stays_off_stdout() {
    # db.sh is sourced by scripts whose stdout is DATA — gen_client.sh writes a
    # schema, backup.sh writes a dump through a redirect. A note on stdout
    # would corrupt the first and read as a finding in the second.
    fresh_checkout
    write_env "DATABASE_NAME=djb_main"
    CURRENT="the note's stream"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$REPO"
        unset DATABASE_NAME
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh"
    ) >"$OUT" 2>/dev/null || RC=$?
    if [ -s "$OUT" ]; then
        bad "the note reached stdout — $(tr '\n' ' ' <"$OUT")"
    else
        ok "stdout is clean; the note is on stderr"
    fi
}

case_the_leg_is_wired_into_the_fast_tier() {
    # THE WEAKEST CASE HERE, AND THE ONE THE RUNG RESTS ON. Everything above
    # proves the leg body; this proves the gate calls it, and calls it in the
    # tier that runs at every commit. It reads check.sh as TEXT because the
    # full gate's lock makes `--fast` refuse to run from inside the selftest
    # leg (check.sh's lock section) — named as a weaker proof rather than
    # dressed up as an end-to-end one.
    CURRENT="the wiring in check.sh"
    OUT="${WORK}/wiring.log"
    : >"$OUT"
    local call_line fast_exit_line
    call_line="$(grep -n '^db_pin_leg$' "${ROOT}/scripts/check.sh" | head -1 | cut -d: -f1 || true)"
    fast_exit_line="$(grep -n 'if \[ "\$MODE" = "--fast" \]; then' "${ROOT}/scripts/check.sh" | head -1 | cut -d: -f1 || true)"
    if [ -z "$call_line" ]; then
        bad "check.sh never calls db_pin_leg — the leg body is orphaned"
        return 0
    fi
    ok "check.sh calls db_pin_leg (line ${call_line})"
    if [ -z "$fast_exit_line" ]; then
        bad "check.sh's --fast early exit could not be found — the tier cannot be judged"
        return 0
    fi
    if [ "$call_line" -lt "$fast_exit_line" ]; then
        ok "the call is above the --fast early exit (line ${fast_exit_line}) — pre-commit runs it, and --loop and the full gate inherit it"
    else
        bad "db_pin_leg is called BELOW the --fast early exit — a stale pin would no longer stop a commit, which is the whole rung"
    fi
    if grep -q '^FULL_LEGS=.*[,=]db-pin,' "${ROOT}/scripts/check.sh"; then
        ok "db-pin is in FULL_LEGS, so a recorded verdict says it ran"
    else
        bad "db-pin is missing from FULL_LEGS — the verdict would under-report what green meant"
    fi
    if grep -q 'leg db-pin ' "${ROOT}/scripts/check.sh"; then
        ok "the leg announces itself as db-pin"
    else
        bad "no 'leg db-pin' announcement — the leg would run unnamed and untimed"
    fi
}

case_a_stale_pin_is_refused
case_the_refusal_says_what_the_disagreement_costs
case_a_pinned_line_passes_silently
case_the_marker_must_be_on_the_database_name_line
case_no_env_file_at_all_passes
case_an_env_with_no_database_name_line_passes
case_a_pin_that_agrees_passes
case_a_pin_that_agrees_and_is_marked_passes
case_a_quoted_pin_that_agrees_passes
case_the_last_database_name_line_wins
case_an_unreadable_env_cannot_look
case_the_source_time_note_points_at_the_leg
case_the_note_stays_off_stdout
case_the_leg_is_wired_into_the_fast_tier

echo "test_db_pin: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! the db-pin leg no longer refuses a stale DATABASE_NAME pin — or no longer" >&2
    echo "   passes a deliberate one. Both halves are load-bearing: a leg that stops" >&2
    echo "   refusing puts a checkout back to running two databases in silence, and a" >&2
    echo "   leg that stops passing a \`# pinned\` line is noise every checkout learns" >&2
    echo "   to scroll past, which is the state the earlier note was already in." >&2
    exit 1
fi
exit 0
