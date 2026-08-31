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
# The drive for `scripts/verify_start.sh` — the verifier-start instrument.
#
#   ./scripts/tests/test_verify_start.sh          run every case
#   ./scripts/tests/test_verify_start.sh --list   name them and stop
#
# WHY IT EXISTS. `verify_start.sh` is made of one clone and three guards, and
# every one of the guards is invisible when it is right: the dirty-source
# refusal, the verdict-key refusal, and the rule that the derivation is ASKED
# FOR rather than copied. The verdict-key guard is the one that has to be
# driven hardest, because the thing it refuses — an untracked file nobody
# thought about — is by construction a thing nobody thought about. It has
# already been paid for twice, in two products, in the same week: a sibling's
# verifier scratch files, and this repository's own untracked
# `.claude/settings.json`, which is why a push once went around the merge
# ritual by hand (`docs/product/misses.md`, the push-ritual entry).
#
# IT BUILDS ITS OWN REPOSITORIES, and it plants nothing in this tree. A scratch
# source repository under `mktemp -d` with a `main`, a rung branch, a
# `.gitignore`, an `.env.example` and a copy of `scripts/db.sh` is a checkout as
# far as this instrument is concerned, and the clone it makes is a real clone.
#
# THE STRAY IS PLANTED, NOT FOUND — twice, from two directions:
#
#   * `case_a_planted_stray_in_the_clone_is_refused_by_name` runs the happy
#     path, writes a file into the finished clone the way a verifier writes a
#     scratch note, and requires `--check` to refuse it BY NAME at exit 2.
#   * `case_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4`
#     drives the same guard INLINE, in the run's own step 4, over a source
#     repository whose `.gitignore` is missing the `.env` line. The file the
#     guard names there is the one the script itself just wrote, which is the
#     script's own declared blind spot 4 asserted as behaviour rather than
#     left as a sentence.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE VENV, THE DATABASE AND THE SCHEMA. The instrument does not create
#      them (its header's blind spot 2), so neither does this. What is driven
#      is that the database NAME is derived by the clone's own `scripts/db.sh`
#      and equals what that file independently answers — the seam, not the
#      arithmetic.
#   2. A COPY IS WHAT RUNS, in every case but the two that need no root (the
#      pipe refusal and the unknown-option refusal, which run THIS TREE'S OWN
#      FILE). `verify_start.sh` derives its root from its own location, so
#      driving it against a scratch repository means copying it in. The copy is
#      made from this tree's file at the start of every case, so it cannot
#      drift within a run — but it is a copy, and a reader should know it.
#   3. THE REAL ZITADEL. The carry is driven as a FILE OPERATION with a value
#      this drive invented: the announced key names appear, the value never
#      does, and the value lands in the clone's `.env`. Whether the credential
#      works against a live instance is not this drive's claim and is not the
#      instrument's either (its blind spot 5).
#   4. A HOSTILE `.env`. Lines are carried verbatim. A `ZITADEL_*` line with a
#      newline in it, or a value that is itself an assignment, is outside what
#      is driven here.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_verify_start: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death hands the
# EXIT trap a status of 0, so a drive that dies halfway reads as a PASS to
# check.sh. Every case below is worthless without this.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_verify_start: $*" >&2
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
    echo "!! unknown argument '$1': test_verify_start.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -x scripts/verify_start.sh ] ||
    cannot_look "scripts/verify_start.sh is not an executable file in this tree — there is nothing to drive"
[ -r scripts/db.sh ] ||
    cannot_look "scripts/db.sh is not readable — the derivation seam this instrument consumes is not here"

ROOT="$PWD"
REAL="${ROOT}/scripts/verify_start.sh"
REAL_DB="${ROOT}/scripts/db.sh"

# The step count, ASKED rather than typed. A case that spells the total by hand
# goes vacuous the day a step is added — the exact way `says_not "step 1/4"`
# went vacuous in the sibling drive.
STEP_TOTAL_IN_SCRIPT="$(sed -n 's/^STEP_TOTAL=\([0-9][0-9]*\).*/\1/p' "$REAL" | head -1)"
[ -n "$STEP_TOTAL_IN_SCRIPT" ] ||
    cannot_look "scripts/verify_start.sh declares no STEP_TOTAL — the step banners cannot be read"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-verify-start-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

CURRENT=""
RC=0
OUT=""
N=0
SRC=""
DEST=""

# The carried value. It is this drive's invention and it never leaves the
# scratch directory; what the cases assert about it is that the instrument
# PRINTS THE KEY NAME AND NOT THIS STRING.
CARRY_VALUE="drive-invented-not-a-credential-0000"

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

# --- the scratch source repository -------------------------------------------
#
# `main` with two commits, a rung branch with one of its own, and main moved on
# afterwards so the union is a REAL merge rather than a fast-forward. The
# `.gitignore` is this template's own Env and run-log lines, because the
# instrument's blind spot 4 is precisely about a repository that lacks them —
# and one case below builds exactly that repository on purpose.
#
#   $1 — "ignores-dotenv" (the normal shape) or "bare-gitignore" (blind spot 4)
#        or "no-gitignore" (nothing ignored at all).
fresh_source() {
    local shape="${1:-ignores-dotenv}"
    N=$((N + 1))
    SRC="${WORK}/src${N}"
    drive_require_scratch SRC "${SRC:-}"
    mkdir -p "${SRC}/scripts"
    git -C "$SRC" init -q
    git -C "$SRC" symbolic-ref HEAD refs/heads/main
    git -C "$SRC" config user.email drive@example.invalid
    git -C "$SRC" config user.name "verify start drive"
    # The real files, copied in — see blind spot 2.
    cp "$REAL" "${SRC}/scripts/verify_start.sh"
    chmod +x "${SRC}/scripts/verify_start.sh"
    cp "$REAL_DB" "${SRC}/scripts/db.sh"
    case "$shape" in
    ignores-dotenv)
        printf '.env\n.env.*\n!.env.example\n*.log\n' >"${SRC}/.gitignore"
        git -C "$SRC" add .gitignore
        ;;
    bare-gitignore)
        # `*.log` ignored, `.env` NOT — the instrument's declared blind spot 4.
        printf '*.log\n' >"${SRC}/.gitignore"
        git -C "$SRC" add .gitignore
        ;;
    no-gitignore) ;;
    esac
    # The scanner reads this whole literal as one high-entropy base64 run
    # because of the escapes. It is a two-line fixture `.env.example` whose
    # identity key is DELIBERATELY EMPTY — an empty value is the negative case
    # two cases below depend on, so there is nothing here to leak.
    printf 'DATABASE_NAME=djb_placeholder\nZITADEL_PAT=\n' >"${SRC}/.env.example" # pragma: allowlist secret
    echo "one" >"${SRC}/tracked.txt"
    git -C "$SRC" add scripts/verify_start.sh scripts/db.sh .env.example tracked.txt
    git -C "$SRC" commit -q -m "base"
    git -C "$SRC" checkout -q -b rung-x
    echo "what the rung built" >"${SRC}/rung.txt"
    git -C "$SRC" add rung.txt
    git -C "$SRC" commit -q -m "the rung"
    git -C "$SRC" checkout -q main
    echo "two" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "main moved on afterwards"
}

# The primary's `.env` — the thing the ZITADEL carry reads. Never committed:
# a `.env` in a repository is the disease, not the fixture.
source_env() {
    printf '%s\n' "$@" >"${SRC}/.env"
}

# Run the COPY, from inside the scratch source repository, capturing both
# streams. The destination is always outside the source.
run_it() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    DEST="${WORK}/clone${N}"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh "$@" "$DEST") >"$OUT" 2>&1 || RC=$?
}

# Run the copy with an explicit argument list and NO appended destination.
run_raw() {
    CURRENT="$1"
    shift
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh "$@") >"$OUT" 2>&1 || RC=$?
}

# =============================================================================

# Runs THIS TREE'S OWN FILE: the pipe refusal fires before the script derives a
# root or reads an argument, so it needs no scratch repository at all.
case_a_piped_stdout_is_refused() {
    CURRENT="a piped stdout is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    # The pipe is the point. `cat` is the filter whose exit status would
    # otherwise become the verdict, and PIPESTATUS is how this driver reads the
    # status the pipe would have swallowed.
    set +e
    "$REAL" 2>&1 | cat >"$OUT"
    RC=${PIPESTATUS[0]}
    set -e
    exits 2
    says "refuses pipes"
    says "The exit status is the verdict"
}

case_an_unknown_option_is_refused() {
    CURRENT="an unknown option is refused"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    set +e
    "$REAL" --force >"$OUT" 2>&1
    RC=$?
    set -e
    exits 2
    says "unknown option"
    # The step banner, spelled with the CURRENT total read out of the script.
    says_not "step 1/${STEP_TOTAL_IN_SCRIPT}"
}

case_no_branch_at_all_is_refused() {
    fresh_source
    run_raw "no branch at all is refused"
    exits 2
    says "needs the rung branch"
    says_not "step 1/${STEP_TOTAL_IN_SCRIPT}"
}

case_a_branch_this_checkout_does_not_have_is_refused() {
    fresh_source
    run_it "a branch this checkout does not have is refused" "rung-that-never-existed"
    exits 2
    says "no local branch 'rung-that-never-existed'"
    if [ -e "$DEST" ]; then
        bad "the destination was created anyway: $DEST"
    else
        ok "nothing was created at the destination"
    fi
}

# THE HAPPY PATH, end to end: clone, a real merge, the derived name, the carry,
# and a clean verdict key.
case_the_happy_path_clones_merges_derives_and_ends_clean() {
    fresh_source
    source_env "ZITADEL_PAT=${CARRY_VALUE}" "ZITADEL_ISSUER=http://localhost:8081"
    local branch_tip main_tip
    branch_tip="$(git -C "$SRC" rev-parse rung-x)"
    main_tip="$(git -C "$SRC" rev-parse main)"

    run_it "the happy path clones, merges, derives and ends clean" "rung-x"
    exits 0
    says "== READY"
    says "step 4/${STEP_TOTAL_IN_SCRIPT}"

    if [ -d "${DEST}/.git" ]; then
        ok "the clone exists at ${DEST}"
    else
        bad "no clone at ${DEST}"
        return
    fi

    # THE UNION, asserted as ancestry rather than read off the transcript: both
    # tips are in, which is the whole claim step 2 makes.
    if git -C "$DEST" merge-base --is-ancestor "$branch_tip" HEAD; then
        ok "the rung branch tip is an ancestor of the clone's HEAD"
    else
        bad "the rung branch tip ${branch_tip} is NOT in the clone's history"
    fi
    if git -C "$DEST" merge-base --is-ancestor "$main_tip" HEAD; then
        ok "main's tip is an ancestor of the clone's HEAD — the merge really happened"
    else
        bad "main's tip ${main_tip} is NOT in the clone's history — the union was not built"
    fi
    if [ "$(git -C "$DEST" rev-parse HEAD)" = "$branch_tip" ]; then
        bad "the clone's HEAD is still the bare branch tip — nothing was merged"
    else
        ok "the clone's HEAD is past the bare branch tip"
    fi

    # THE VERDICT KEY, re-measured by this drive rather than believed.
    if [ -z "$(git -C "$DEST" status --porcelain)" ]; then
        ok "\`git status --porcelain\` in the clone is empty"
    else
        bad "the clone is not clean: $(git -C "$DEST" status --porcelain | tr '\n' ' ')"
    fi

    # The .env exists, is not tracked, and carries what was announced.
    if [ -f "${DEST}/.env" ]; then
        ok "the clone has a .env"
    else
        bad "the clone has no .env"
    fi
}

# CRITERION: the derived name is db.sh's, not a second copy of its arithmetic.
case_the_database_name_is_asked_for_and_matches_db_sh() {
    fresh_source
    run_it "the database name is asked for and matches db.sh" "rung-x"
    exits 0

    local printed independent
    printed="$(sed -n 's/^   database     \(djb_.*\)$/\1/p' "$OUT" | head -1)"
    if [ -n "$printed" ]; then
        ok "the run printed a derived name: ${printed}"
    else
        bad "the run printed no derived database name"
        return
    fi

    # THE SHAPE, per the derivation `scripts/db.sh` documents: djb_<branch>_<8
    # hex of the SHA-256 of the checkout's absolute top level>.
    if printf '%s' "$printed" | grep -qE '^djb_rung_x_[0-9a-f]{8}$'; then
        ok "the shape is djb_<sanitised-branch>_<8 hex>"
    else
        bad "the shape is not djb_rung_x_<8 hex>: '${printed}'"
    fi

    # THE SEAM. Asked independently, from the clone, with the environment's own
    # DATABASE_NAME emptied exactly as the instrument does. Equality here is
    # what proves the instrument re-implemented nothing.
    independent="$(cd "$DEST" && DATABASE_NAME='' bash -c '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"')"
    if [ "$printed" = "$independent" ]; then
        ok "it equals what the clone's own scripts/db.sh answers"
    else
        bad "the instrument printed '${printed}' where db.sh answers '${independent}'"
    fi

    # It must be the CLONE's name, never the source's — that is the whole
    # reason the derivation is run inside the clone.
    local source_name
    source_name="$(cd "$SRC" && DATABASE_NAME='' bash -c '. ./scripts/db.sh 2>/dev/null; printf "%s" "${DATABASE_NAME:-}"')"
    if [ "$printed" != "$source_name" ]; then
        ok "it is the CLONE's name, not the source checkout's (${source_name})"
    else
        bad "the clone was given the SOURCE checkout's database name — two checkouts, one database"
    fi

    # And it reaches the file a bare `manage.py` reads.
    if grep -qx "DATABASE_NAME=${printed}" "${DEST}/.env"; then
        ok "the clone's .env pins DATABASE_NAME=${printed}"
    else
        bad "the derived name never reached the clone's .env"
    fi
}

# CRITERION: a DATABASE_NAME in the caller's shell must NOT win here.
case_an_exported_database_name_does_not_reach_the_clone() {
    fresh_source
    CURRENT="an exported DATABASE_NAME does not reach the clone"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    DEST="${WORK}/clone${N}"
    RC=0
    (cd "$SRC" && DATABASE_NAME=djb_the_callers_own ./scripts/verify_start.sh rung-x "$DEST") >"$OUT" 2>&1 || RC=$?
    exits 0
    says "is set in this shell and is IGNORED here"
    if grep -q 'DATABASE_NAME=djb_the_callers_own' "${DEST}/.env" 2>/dev/null; then
        bad "the caller's exported name was written into the clone's .env — two checkouts, one database"
    else
        ok "the caller's exported name is not in the clone's .env"
    fi
}

# CRITERION 3: the ZITADEL carry, announced by KEY NAME and never by value.
case_the_zitadel_carry_announces_names_and_never_values() {
    fresh_source
    source_env \
        "ZITADEL_PAT=${CARRY_VALUE}" \
        "ZITADEL_ISSUER=http://localhost:8081" \
        "ZITADEL_ORG_NAME=" \
        "DATABASE_URL=postgres://not-a-zitadel-key/"
    run_it "the zitadel carry announces names and never values" "rung-x"
    exits 0
    says "carried 2 key(s)"
    says "ZITADEL_PAT"
    says "ZITADEL_ISSUER"
    # THE POINT OF THE CASE. The value is in the file and never in the output.
    if grep -qF -- "$CARRY_VALUE" "$OUT"; then
        bad "the carried VALUE was printed — the announcement is by name only"
    else
        ok "the carried value never appears in the output"
    fi
    if grep -qxF "ZITADEL_PAT=${CARRY_VALUE}" "${DEST}/.env"; then
        ok "the value reached the clone's .env"
    else
        bad "the value did not reach the clone's .env — the carry did nothing"
    fi
    # THE CLOSED POPULATION. Nothing but ZITADEL_* moves.
    if grep -q '^DATABASE_URL=postgres://not-a-zitadel-key/' "${DEST}/.env"; then
        bad "a non-ZITADEL line was carried — the population is not closed"
    else
        ok "the non-ZITADEL line was not carried"
    fi
    # An empty key is reported rather than silently dropped.
    says "ZITADEL_ORG_NAME"
}

# The empty-primary negative case: present, blank, nothing carried, said.
case_an_empty_primary_carries_nothing_and_says_so() {
    fresh_source
    source_env "ZITADEL_PAT=" "ZITADEL_ISSUER="
    run_it "an empty primary carries nothing and says so" "rung-x"
    exits 0
    says "nothing carried"
    says "is empty"
    says_not "carried 1 key(s)"
}

case_a_primary_with_no_env_at_all_says_so() {
    fresh_source
    rm -f "${SRC}/.env"
    run_it "a primary with no .env at all says so" "rung-x"
    exits 0
    says "no .env to carry from"
}

# CRITERION 4: the dirty-source refusal.
case_a_dirty_source_checkout_is_refused_and_nothing_is_cloned() {
    fresh_source
    # THE VICTIM IS THIS CASE'S OWN: a modification and an untracked file it
    # made itself, never found state.
    echo "work in progress nobody committed" >>"${SRC}/tracked.txt"
    echo "a new file nobody has added yet" >"${SRC}/untracked-work.txt"
    run_it "a dirty source checkout is refused and nothing is cloned" "rung-x"
    exits 2
    says "uncommitted work"
    says "untracked-work.txt"
    says "tracked.txt"
    says "Nothing was cloned, merged or written."
    if [ -e "$DEST" ]; then
        bad "the destination was created anyway: $DEST"
    else
        ok "nothing was created at the destination"
    fi
    # And the work is still there — a guard that returns the right code over a
    # destroyed tree is not a guard.
    if grep -q "work in progress nobody committed" "${SRC}/tracked.txt" &&
        [ -f "${SRC}/untracked-work.txt" ]; then
        ok "the uncommitted work is untouched"
    else
        bad "the uncommitted work did not survive the refusal"
    fi
}

# The allowance, driven where it is REAL: a source repository that does not
# ignore `*.log` at all, so the log is genuinely untracked and the refusal has
# to decline to fire.
case_an_untracked_log_in_the_source_is_not_dirt() {
    fresh_source "no-gitignore"
    echo "a gate log, exactly where every agent is told to put one" >"${SRC}/gate-somebody.log"
    run_raw "an untracked log in the source is not dirt" "rung-x" "${WORK}/clone-logcase"
    says_not "uncommitted work"
    says "step 1/${STEP_TOTAL_IN_SCRIPT}"
    if [ -d "${WORK}/clone-logcase/.git" ]; then
        ok "the clone was made — the log did not stop it"
    else
        bad "no clone was made; the log was treated as dirt"
    fi
}

# THE TOOTH, from the direction a verifier meets it: the clone finishes clean,
# the verifier writes a scratch note into it, and the guard refuses BY NAME.
case_a_planted_stray_in_the_clone_is_refused_by_name() {
    fresh_source
    run_it "a planted stray in the clone is refused by name" "rung-x"
    exits 0
    local clone="$DEST"

    # THE PLANT. This case's own file, in this case's own clone.
    echo "verification notes the verifier meant to keep" >"${clone}/verifier-notes.md"

    CURRENT="a planted stray in the clone is refused by name"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$clone") >"$OUT" 2>&1 || RC=$?
    exits 2
    says "STRAY FILES"
    says "verifier-notes.md"
    says "SHIFTS THE KEY"

    # AND THE OTHER DIRECTION: remove the plant, and the same guard goes green.
    # A refusal that cannot be cleared is indistinguishable from a broken one.
    rm -f "${clone}/verifier-notes.md"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$clone") >"$OUT" 2>&1 || RC=$?
    exits 0
    says "CLEAN"

    # And a log in the same place is the one allowance, proven rather than
    # assumed — this clone's .gitignore does ignore it, so the assertion is
    # that the guard is silent, which it must be either way.
    echo "a gate log" >"${clone}/gate-verification.log"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$SRC" && ./scripts/verify_start.sh --check "$clone") >"$OUT" 2>&1 || RC=$?
    exits 0
}

# THE SAME TOOTH, INLINE, in the run's own step 4 — and the file it names is
# the one the instrument itself wrote. This is `verify_start.sh`'s declared
# blind spot 4 asserted as behaviour.
case_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4() {
    fresh_source "bare-gitignore"
    run_it "a repository that does not ignore dotenv is refused at step 4" "rung-x"
    exits 2
    says "step ${STEP_TOTAL_IN_SCRIPT}/${STEP_TOTAL_IN_SCRIPT}"
    says "STRAY FILES"
    says ".env"
    # The clone is still there to be read; the refusal is a verdict, not a
    # cleanup.
    if [ -d "${DEST}/.git" ]; then
        ok "the clone is left in place for the reader"
    else
        bad "the clone was removed — there is nothing left to diagnose"
    fi
}

case_an_occupied_destination_is_refused() {
    fresh_source
    N=$((N + 1))
    local occupied="${WORK}/occupied${N}"
    drive_require_scratch occupied "${occupied:-}"
    mkdir -p "$occupied"
    echo "somebody else's half-finished verification" >"${occupied}/in-progress.txt"
    run_raw "an occupied destination is refused" "rung-x" "$occupied"
    exits 2
    says "the destination is not empty"
    if [ -f "${occupied}/in-progress.txt" ]; then
        ok "what was there is still there"
    else
        bad "the occupied destination was clobbered"
    fi
}

case_a_conflicting_rung_branch_is_an_exit_1_naming_the_paths() {
    fresh_source
    # Both sides touch the same line of the same file. `fresh_source` already
    # moved main; this moves the rung branch onto the same file.
    git -C "$SRC" checkout -q rung-x
    echo "the rung's own second line" >>"${SRC}/tracked.txt"
    git -C "$SRC" add tracked.txt
    git -C "$SRC" commit -q -m "the rung touches tracked.txt too"
    git -C "$SRC" checkout -q main
    run_it "a conflicting rung branch is an exit 1 naming the paths" "rung-x"
    # 1, not 2: the merge RAN and came back with a real answer.
    exits 1
    says "CONFLICT"
    says "tracked.txt"
    says "left AT THE CONFLICT"
}

# CRITERION 1's other half, read as CODE. The header explains at length why
# this file is never read into a shell, and a grep that cannot tell the
# explanation from the act would make the explanation unwritable — the known
# class where prose spelling a censused thing is counted as the thing. So
# comments are stripped first, and what is left is the executable text.
case_it_never_reads_the_environment_file_into_its_own_shell() {
    CURRENT="it never reads the environment file into its own shell"
    local code="${WORK}/verify_start.code"
    sed 's/#.*//' "$REAL" >"$code"
    OUT="$code"
    if grep -qE '(^|[^a-zA-Z_])(source|\.)[[:space:]]+[^[:space:]]*\.env([^a-zA-Z]|$)' "$code"; then
        bad "the executable text sources the environment file — the one thing this instrument must not do"
        grep -nE '(^|[^a-zA-Z_])(source|\.)[[:space:]]+[^[:space:]]*\.env([^a-zA-Z]|$)' "$code" | sed 's/^/             | /'
    else
        ok "no sourcing of the environment file anywhere in the executable text"
    fi
    # It DOES source db.sh — inside the clone, in a subshell. That is the seam,
    # and losing it would mean the arithmetic came back as a second copy.
    if grep -q 'db\.sh' "$code"; then
        ok "it still consumes scripts/db.sh as the derivation seam"
    else
        bad "it no longer names scripts/db.sh — the derivation has gone somewhere else"
    fi
    # A second copy of the path-hash arithmetic is the thing the seam exists to
    # prevent. Code only, comments already stripped.
    if grep -qE 'shasum|sha256sum|openssl dgst|cksum' "$code"; then
        bad "it has grown its own path-hash arithmetic — that is the second copy db.sh exists to avoid"
    else
        ok "it hashes nothing itself; db.sh's answer is the name"
    fi
    # And the header really does record the cost, which is criterion 1's
    # parenthesis. This one looks at the COMMENTS on purpose.
    if grep -q 'three gate runs\|THREE GATE RUNS' "$REAL"; then
        ok "the header records what sourcing that file cost a sibling product"
    else
        bad "the header no longer records the cost — the rule is back to being an assertion"
    fi
    OUT=""
}

echo "== test_verify_start — driving scripts/verify_start.sh"
echo "   scratch: ${WORK}"

case_a_piped_stdout_is_refused
case_an_unknown_option_is_refused
case_no_branch_at_all_is_refused
case_a_branch_this_checkout_does_not_have_is_refused
case_the_happy_path_clones_merges_derives_and_ends_clean
case_the_database_name_is_asked_for_and_matches_db_sh
case_an_exported_database_name_does_not_reach_the_clone
case_the_zitadel_carry_announces_names_and_never_values
case_an_empty_primary_carries_nothing_and_says_so
case_a_primary_with_no_env_at_all_says_so
case_a_dirty_source_checkout_is_refused_and_nothing_is_cloned
case_an_untracked_log_in_the_source_is_not_dirt
case_a_planted_stray_in_the_clone_is_refused_by_name
case_a_repository_that_does_not_ignore_dotenv_is_refused_at_step_4
case_an_occupied_destination_is_refused
case_a_conflicting_rung_branch_is_an_exit_1_naming_the_paths
case_it_never_reads_the_environment_file_into_its_own_shell

echo
echo "== ${PASSED} passed, ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
