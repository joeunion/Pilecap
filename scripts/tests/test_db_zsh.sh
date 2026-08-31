#!/usr/bin/env bash
# THE SOURCED-LIBRARY DRIVE — `scripts/db.sh` under a REAL zsh.
#
# WHY IT EXISTS, and it is one incident. `scripts/db.sh` is the only file in
# this repository that is SOURCED rather than run: its `#!/usr/bin/env bash` is
# inert decoration, and the interpreter is always whatever shell the caller is
# standing in. On macOS — this box, and every laptop a product clones this
# template onto since Catalina — a human's login shell is zsh, so
# `. scripts/db.sh && db_create` at a prompt runs this library under zsh. It had
# never once been driven there.
#
# WHAT THAT COST. zsh has TIED parameters, and `local` does not untie them:
# inside a function, `local path=fallback` does not make a private string, it
# sets the caller's PATH to `fallback` for the length of the call.
# `db_create_the_checkouts_own` opened with exactly that line. Under zsh, on a
# box with docker on PATH and the compose Postgres up, it printed
#
#     db_psql:1: command not found: docker
#     created database djb_zshprobe_red01
#     db.sh: db_create djb_zshprobe_red01 path=fallback elapsed=
#     ...
#     ABSENT — the 'created database' line above was a LIE
#
# and returned 0. Every tool the function reached for — docker, awk, date —
# disappeared mid-function because PATH had become the six letters `fallback`,
# and the one line every caller of `db_create` reads said the work was done.
# That is the shape this drive is pointed at: not "does it error", but "does the
# database the line claims exist actually exist".
#
# THE FOUR CASES, and what each is for:
#
#   1. THE STATIC AUDIT — no zsh needed, so it runs everywhere including a
#      Linux runner. db.sh declares no variable named `path`, `status`,
#      `options` or `fignore`. This is the regression tooth: the rename is one
#      edit and the next one is one edit away.
#   2. THE DERIVATIONS AGREE — every pure function db.sh exports produces
#      byte-identical output under bash and under zsh. A library whose NAME
#      derivation forked by shell would give one checkout two databases, which
#      is the disease db.sh's own header is written against.
#   3. CREATE REALLY CREATES — the live tooth. A scratch checkout on a branch
#      called `zshprobe` derives `djb_zshprobe_<hash>`; zsh sources db.sh, runs
#      `db_create`, and then THIS process — a bash process that never had its
#      PATH touched — asks Postgres whether the database is there. It also
#      requires the child's transcript to carry no `command not found` at all.
#   4. THE PLANT — the fix is reverted in a scratch COPY of db.sh (`sed
#      creation_path -> path`), and the false green is required to come back.
#      A case that cannot fail is not a case; this is what keeps case 3 honest,
#      and the day the reproduction stops reproducing this drive says so
#      instead of quietly passing.
#
# ONE THING THIS DRIVE LEARNED THE HARD WAY, written down because the obvious
# assertion is the wrong one: you CANNOT see this bug by comparing PATH before
# and after the call. zsh's `local` restores a tied parameter on return, so the
# caller's PATH is byte-identical in both directions — the first draft of case 4
# asserted `PATH-survived=no` and went red against a perfectly reproduced
# defect. The damage lives entirely inside the function body and its only trace
# is the shell's own `command not found` while the body runs. That is what both
# live cases assert, in opposite directions.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   1. THE OTHER SHELLS. dash, ksh and busybox ash are not driven here. db.sh
#      is POSIX-ish and would probably survive them; "probably" is exactly the
#      word that preceded this incident, and the claim is not made.
#   2. THE EXECUTABLES. Every other script under `scripts/` runs under its own
#      `#!/usr/bin/env bash` shebang and is only reachable by a wrong shell
#      through `sh scripts/x.sh`. The BASH_VERSION belt for that is deliberately
#      NOT here — it touches every script in the tree and lands with rung C1 in
#      wave 2 (cycle P17 §S-C criterion 3).
#   3. THE UNCHECKED `CREATE`. On the fallback path db.sh runs
#      `db_query 'CREATE DATABASE ...' >/dev/null` and does not test the exit
#      status, so with the SERVER unreachable — as opposed to PATH broken —
#      `db_create` still prints `created database` and returns 0 to a caller
#      that has not set `-e`. Every script consumer here sets `-euo pipefail`
#      and dies correctly; an interactive `. scripts/db.sh` does not. That is a
#      second false-green of the same family, it is NOT this drive's subject, and it is
#      handed up in the S-C report rather than fixed quietly beside the rename.
#   4. TIMING, AND ANY OTHER SERVER. The live cases need this repository's own
#      compose Postgres and say so at exit 2 rather than skipping — a
#      false-green tooth proven without a server is the weak reproduction this
#      drive exists to replace.
#   5. IT IS NOT WIRED INTO THE GATE'S `selftest` LEG. `scripts/check.sh` is
#      another rung's territory in this same cycle (G1), so the wiring is OWED
#      and recorded, not done — the same note `test_db_template.sh` carries.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_db_zsh: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into: on bash 3.2 a `set -u` death hands the
# EXIT trap a status of 0, so a drive that dies halfway reads as a PASS.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0
SKIPPED=0

cannot_look() {
    echo "!! test_db_zsh: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

LIVE=1
case "${1:-}" in
"") ;;
--no-live) LIVE=0 ;;
--list)
    # `() {` and not a bare `^case_`: the run block at the bottom calls each
    # case by name at the line start too, so the looser pattern lists every
    # case twice. And `drive_finished` before the exit, because the preamble's
    # section-5 check turns any opted-in exit 0 that did not reach it into a
    # could-not-look 2 — which is exactly what `--list` did until this line.
    grep -nE '^case_[A-Za-z0-9_]+\(\) \{' "$0" | sed 's/() {.*//; s/^/  /'
    drive_finished
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_db_zsh.sh takes nothing, --no-live or --list" >&2
    exit 2
    ;;
esac

[ -f scripts/db.sh ] || cannot_look "scripts/db.sh is not in this tree — there is nothing to drive"

ROOT="$PWD"

# shellcheck source=scripts/db.sh
. scripts/db.sh
for fn in db_name db_create db_exists db_create_the_checkouts_own; do
    command -v "$fn" >/dev/null 2>&1 ||
        cannot_look "scripts/db.sh defines no ${fn} — the mechanism this drive exists for is not there"
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-db-zsh-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"

# This drive's own victims, dropped on the way out whatever happened. Every one
# of them is a `djb_zshprobe_*` name derived from a scratch checkout under
# $WORK, so nothing on this server that anybody else made can be mistaken for
# one.
LIVE_DBS=()
live_cleanup() {
    local db
    for db in ${LIVE_DBS[@]+"${LIVE_DBS[@]}"}; do
        db_query 'DROP DATABASE IF EXISTS :"name" WITH (FORCE)' -v name="$db" >/dev/null 2>&1 || true
    done
}
drive_at_exit 'live_cleanup; chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

CURRENT=""
OUT=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    [ -n "$OUT" ] && [ -f "$OUT" ] && sed 's/^/             | /' "$OUT" | tail -25
    FAILED=$((FAILED + 1))
}
same() {
    if [ "$2" = "$3" ]; then ok "$1"; else bad "$1 — wanted '$3', got '$2'"; fi
}
skip() {
    echo "  SKIPPED  ${CURRENT} — $1"
    SKIPPED=$((SKIPPED + 1))
}

# --- what this box can reach ---------------------------------------------------
#
# zsh absent is a SKIP with its reason, never a silent pass and never a vacuous
# one: case 1 asserts the audit with no shell but this one, so a run without zsh
# still asserts something and says exactly what it did not.
HAVE_ZSH=0
if command -v zsh >/dev/null 2>&1; then
    HAVE_ZSH=1
    ZSH_VERSION_SEEN="$(zsh --version 2>/dev/null | head -1 || true)"
else
    ZSH_VERSION_SEEN="(none)"
fi

# --- the scratch checkout the live cases derive their name from ----------------
#
# The branch is `zshprobe` because `db_name` puts the branch in the name: the
# database this drive creates is `djb_zshprobe_<8 hex of this scratch path>`,
# which is self-labelling to an operator reading `psql -l` and cannot collide
# with any checkout's real derivation. No `apps/` in it, deliberately — with no
# migration set to digest, `db_create` takes the plain fallback path and never
# clones a template into the probe.
REPO=""
fresh_probe_checkout() {
    N=$((N + 1))
    REPO="${WORK}/probe${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/zshprobe
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "db zsh drive"
    printf 'probe\n' >"$REPO/README"
    git -C "$REPO" add README
    git -C "$REPO" commit -q -m base
}

# The child script both live cases run. $1 is the db.sh to source — the real one
# for case 3, the reverted copy for case 4 — so the plant differs from the tooth
# by one argument and nothing else.
write_child() {
    cat >"${WORK}/child.zsh" <<'CHILD'
# Run under `zsh -f`: no rc files, nothing this box's owner configured.
# Deliberately NO `set -e`: an interactive `. scripts/db.sh` has none, and the
# false green this drive is pointed at is exactly what a caller without it saw.
emulate -L zsh
print -r -- "child: shell=$ZSH_VERSION"
print -r -- "child: docker-before=$(command -v docker || print none)"
path_before=$PATH
. "$1"
print -r -- "child: derived=${DATABASE_NAME}"
db_create
print -r -- "child: rc=$?"
if [[ "$PATH" == "$path_before" ]]; then
    print -r -- "child: PATH-survived=yes"
else
    print -r -- "child: PATH-survived=no"
fi
print -r -- "child: docker-after=$(command -v docker || print none)"
CHILD
}

live_reachable() {
    db_query 'SELECT 1' -tA >/dev/null 2>&1
}

# --- the cases -----------------------------------------------------------------

case_db_sh_declares_no_zsh_tied_variable() {
    CURRENT=case_db_sh_declares_no_zsh_tied_variable
    OUT=""
    local hits
    # Only the DECLARATION forms, and only outside full-line comments: a shell
    # variable in db.sh is set by `local`/`export`/`typeset`/`readonly` or by a
    # line-leading `NAME=`. Nothing else here sets one, and matching more than
    # that would flag `printf '... path=%s ...'`, which is the instrument's
    # PRINTED token and is contract, not a variable (test_db_template.sh:471
    # greps it).
    hits="$(grep -vE '^[[:space:]]*#' scripts/db.sh |
        grep -nE '^[[:space:]]*(local|typeset|declare|export|readonly)[[:space:]].*[[:space:]](path|status|options|fignore)=|^[[:space:]]*(path|status|options|fignore)=' || true)"
    if [ -z "$hits" ]; then
        ok "no variable named path, status, options or fignore — the four zsh-tied names db.sh's header audits"
    else
        bad "db.sh declares a zsh-tied variable; under zsh \`local\` does not untie it:
$(printf '%s\n' "$hits" | sed 's/^/             | /')"
    fi
    # And the tooth has a tooth: the pattern must actually match the shape it
    # is looking for, or a green case means nothing.
    if printf '    local name="$1" t0 path=fallback\n' |
        grep -qE '^[[:space:]]*(local|typeset|declare|export|readonly)[[:space:]].*[[:space:]](path|status|options|fignore)='; then
        ok "the audit pattern fires on the exact line the rename removed"
    else
        bad "the audit pattern does not match the original defect — a green above asserts nothing"
    fi
}

case_the_derivations_agree_between_bash_and_zsh() {
    CURRENT=case_the_derivations_agree_between_bash_and_zsh
    OUT=""
    if [ "$HAVE_ZSH" != "1" ]; then
        skip "no zsh on PATH — bash-vs-zsh agreement of db_name/db_path_hash/db_migration_key was NOT asserted"
        return 0
    fi
    local probe="${WORK}/derive.sh" a="${WORK}/derive-bash.txt" b="${WORK}/derive-zsh.txt"
    cat >"$probe" <<PROBE
cd "${ROOT}"
. scripts/db.sh >/dev/null 2>&1
printf 'db_name=%s\n' "\$(db_name)"
printf 'db_path_hash=%s\n' "\$(db_path_hash /a/b 8)"
printf 'db_path_hash16=%s\n' "\$(db_path_hash /a/b 16)"
printf 'db_checkout_root=%s\n' "\$(db_checkout_root)"
printf 'db_migration_key=%s\n' "\$(db_migration_key)"
printf 'db_template_name=%s\n' "\$(db_template_name)"
printf 'db_env_file_pin=%s\n' "\$(db_env_file_pin)"
db_valid_name ok_1; printf 'valid_good=%s\n' "\$?"
db_valid_name 'bad-name'; printf 'valid_bad=%s\n' "\$?"
db_template_wanted "\$(db_name)"; printf 'template_wanted=%s\n' "\$?"
PROBE
    OUT="$a"
    env -u DATABASE_NAME bash "$probe" >"$a" 2>&1 || true
    env -u DATABASE_NAME zsh -f "$probe" >"$b" 2>&1 || true
    if [ ! -s "$a" ]; then
        bad "the bash side produced nothing — the probe itself is broken"
        return 0
    fi
    if diff -u "$a" "$b" >"${WORK}/derive.diff" 2>&1; then
        ok "every derivation db.sh exports is byte-identical under bash and under zsh ($(grep -c . "$a") values)"
    else
        OUT="${WORK}/derive.diff"
        bad "a derivation forks by shell — one checkout would have two databases"
    fi
    # Non-vacuous: the probe has to have produced real values, not empty ones.
    if grep -qE '^db_name=djb_[A-Za-z0-9_]+$' "$a"; then
        ok "the probe derived a real name, so the agreement above is over content"
    else
        OUT="$a"
        bad "the probe derived no db_name — the diff above compared two empties"
    fi
}

case_db_create_under_zsh_really_creates_the_database() {
    CURRENT=case_db_create_under_zsh_really_creates_the_database
    OUT="${WORK}/create.log"
    if [ "$HAVE_ZSH" != "1" ]; then
        skip "no zsh on PATH — the false-green tooth (db_create under zsh) was NOT asserted"
        return 0
    fi
    if [ "$LIVE" != "1" ]; then
        skip "--no-live — the false-green tooth needs the compose Postgres to ask whether the database is really there"
        return 0
    fi
    local target rc
    fresh_probe_checkout
    target="$(cd "$REPO" && env -u DATABASE_NAME bash -c '. "'"$ROOT"'/scripts/db.sh" >/dev/null 2>&1; db_name')"
    case "$target" in
    djb_zshprobe_*) ok "the scratch checkout derives a self-labelling probe name (${target})" ;;
    *)
        bad "the scratch checkout derived '${target}', which is not a djb_zshprobe_* name — refusing to create it"
        return 0
        ;;
    esac
    LIVE_DBS+=("$target")
    write_child
    rc=0
    # COMPOSE_FILE, because `docker compose` resolves its file from the working
    # directory and the scratch checkout has none — the Postgres has to be this
    # repository's.
    (cd "$REPO" && env -u DATABASE_NAME COMPOSE_FILE="${ROOT}/compose.yaml" \
        zsh -f "${WORK}/child.zsh" "${ROOT}/scripts/db.sh") >"$OUT" 2>&1 || rc=$?
    same "the zsh child exits 0" "$rc" "0"
    if grep -q "child: derived=${target}" "$OUT"; then
        ok "zsh derived the same name bash did"
    else
        bad "zsh derived a different name from bash"
    fi
    if grep -q "created database ${target}" "$OUT"; then
        ok "db_create printed the line every caller reads"
    else
        bad "db_create did not print 'created database ${target}'"
    fi
    # THE TOOTH. Asked from THIS process — a bash process whose PATH was never
    # touched — because the whole defect was a function lying about its own work.
    if db_exists "$target"; then
        ok "AND THE DATABASE IS REALLY THERE — the false green is gone"
    else
        bad "'created database ${target}' was printed and the database does not exist — the false green is BACK"
    fi
    # THE MECHANISM, and it is NOT "PATH differs afterwards": zsh's `local`
    # RESTORES the tied parameter when the function returns, so the caller's
    # PATH is intact either way and an after-the-fact comparison can never see
    # this bug. The damage is confined to the function BODY, and the only trace
    # it leaves is the shell's own `command not found` while the body runs.
    # Case 4 below proves that trace appears when the defect is planted back.
    if grep -q "command not found" "$OUT"; then
        bad "the child lost a command mid-call:
$(grep 'command not found' "$OUT" | sed 's/^/             | /')"
    else
        ok "nothing went missing inside the call — no 'command not found' anywhere in the child's transcript"
    fi
    if grep -q "child: docker-after=/" "$OUT"; then
        ok "docker is still resolvable in the child after db_create returned"
    else
        bad "docker stopped resolving in the child — PATH did not come back intact"
    fi
    if grep -qE "db\.sh: db_create ${target} path=fallback elapsed=[0-9]" "$OUT"; then
        ok "the instrument line is unchanged: the PRINTED token is still 'path=' (its readers' contract)"
    else
        bad "the 'path=... elapsed=...' instrument line changed shape — test_db_template.sh:471 reads it"
    fi
}

case_reverting_the_rename_brings_the_false_green_back() {
    CURRENT=case_reverting_the_rename_brings_the_false_green_back
    OUT="${WORK}/plant.log"
    if [ "$HAVE_ZSH" != "1" ]; then
        skip "no zsh on PATH — the plant that proves the tooth above can fail was NOT run"
        return 0
    fi
    if [ "$LIVE" != "1" ]; then
        skip "--no-live — the plant asserts a database is ABSENT, which needs the server to ask"
        return 0
    fi
    local target rc planted="${WORK}/db-reverted.sh"
    # The victim is a COPY. Nothing in the checkout is edited, and the revert is
    # the exact inverse of the one rename that closed the defect.
    sed 's/creation_path/path/g' scripts/db.sh >"$planted"
    if grep -qE '^[[:space:]]*local .*[[:space:]]path=fallback' "$planted"; then
        ok "the plant reconstructs the original defect line"
    else
        bad "the revert did not reproduce \`local ... path=fallback\` — this case is asserting nothing"
        return 0
    fi
    fresh_probe_checkout
    target="$(cd "$REPO" && env -u DATABASE_NAME bash -c '. "'"$ROOT"'/scripts/db.sh" >/dev/null 2>&1; db_name')"
    case "$target" in
    djb_zshprobe_*) ;;
    *)
        bad "the scratch checkout derived '${target}', not a djb_zshprobe_* name"
        return 0
        ;;
    esac
    # Registered for cleanup even though the whole point is that it will not be
    # created: if the defect somehow creates it, the drive still leaves nothing.
    LIVE_DBS+=("$target")
    write_child
    rc=0
    (cd "$REPO" && env -u DATABASE_NAME COMPOSE_FILE="${ROOT}/compose.yaml" \
        zsh -f "${WORK}/child.zsh" "$planted") >"$OUT" 2>&1 || rc=$?
    if grep -q "created database ${target}" "$OUT"; then
        ok "the reverted copy still prints 'created database ${target}'"
    else
        bad "the reverted copy did not print the claim — the reproduction has moved and case 3's green means less than it says"
    fi
    if db_exists "$target"; then
        bad "the reverted copy actually created the database — the defect no longer reproduces, so case 3 proves nothing"
    else
        ok "AND THE DATABASE IS NOT THERE: the false green reproduces on demand, so the tooth above can fail"
    fi
    # The tied-parameter mechanism itself, demonstrated rather than argued. It
    # cannot be seen from OUTSIDE the call — `local` restores PATH on return,
    # so `child: PATH-survived` reads `yes` in both directions and is worth
    # nothing here. What it leaves is the shell's own words while the body runs:
    # docker, and every other tool the function reaches for, stops existing.
    if grep -q "command not found: docker" "$OUT"; then
        ok "the reverted copy lost docker MID-CALL — PATH became the six letters \`fallback\` inside the function"
    else
        bad "no 'command not found: docker' in the transcript — this box's zsh does not tie \`path\`, and the plant proves nothing here"
    fi
    if grep -q "child: docker-after=/" "$OUT"; then
        ok "and PATH came back on return, which is why this bug is invisible from outside the call"
    else
        bad "PATH did not come back — the plant broke something other than the tied parameter"
    fi
}

# --- run -----------------------------------------------------------------------

echo "== test_db_zsh — scripts/db.sh under a real zsh"
echo "   zsh:  ${ZSH_VERSION_SEEN}"
echo "   live: $([ "$LIVE" = 1 ] && echo yes || echo 'no (--no-live)')"
echo

if [ "$LIVE" = "1" ] && ! live_reachable; then
    cannot_look "the compose Postgres is not reachable (\`docker compose exec -T db psql\`).
   The live cases ask the SERVER whether a database db_create claimed to make is
   really there, and that question is the whole drive. Bring the stack up
   (\`docker compose up -d db\`) or run with --no-live and read the skips."
fi

case_db_sh_declares_no_zsh_tied_variable
case_the_derivations_agree_between_bash_and_zsh
case_db_create_under_zsh_really_creates_the_database
case_reverting_the_rename_brings_the_false_green_back

echo
echo "== ${PASSED} passed, ${FAILED} failed, ${SKIPPED} skipped"
if [ "$SKIPPED" -gt 0 ]; then
    echo "   A SKIP is not a pass. Each line above says what was not asserted and why."
fi
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
