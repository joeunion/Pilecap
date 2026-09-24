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
# drives: .github/workflows/ci.yml CLAUDE.md compose.yaml docs/product/build-contract.md manage.py scripts/check.sh scripts/db.sh scripts/kill_mine.sh scripts/queue_cited.sh scripts/setup.sh scripts/sweep.sh scripts/tests/test_pm_merge.sh
# cites: .env.example
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
SKIPPED=0
SKIP_REASONS=""

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

# THE COMPOSE FILE, PINNED BY PATH, and it is not a nicety. `db_psql` runs
# `docker compose exec -T db psql`, and `docker compose` finds its project by
# looking in the CURRENT DIRECTORY — which, for every case here, is a scratch
# checkout under mktemp with no compose.yaml in it. Without this the existence
# probe fails from the scratch cwd for a reason that has nothing to do with the
# database, and the live cases read `could not look` forever. The same pin
# `test_db_zsh.sh` puts on its zsh child, for the same reason. An operator who
# already set COMPOSE_FILE keeps it.
export COMPOSE_FILE="${COMPOSE_FILE:-${ROOT}/compose.yaml}"

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
#
# THE THIRD ARGUMENT IS THE LEG'S MODE, AND IT DEFAULTS TO `fast` ON PURPOSE.
# Every case above the existence block is about the PIN COMPARISON, which needs no
# database, no docker and no network — which is exactly what `fast` binds. So
# the pin cases keep running the way this drive has always run (a laptop with
# the stack down clears them), and the four cases that are about EXISTENCE name
# their mode explicitly. A default of `loop` would have made every one of the
# twenty pin cases depend on the compose Postgres.
run_leg_in() {
    local dir="$1" here mode="${3:-fast}" saved_name="${DATABASE_NAME:-}"
    local saved_source="${DATABASE_NAME_SOURCE:-}" saved_source_set="${DATABASE_NAME_SOURCE+set}"
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    here="$PWD"
    cd "$dir"
    # `$DATABASE_NAME` IS MADE TO AGREE WITH THIS CHECKOUT, and that is fidelity
    # rather than convenience. A shell standing in this scratch checkout would
    # have `DATABASE_NAME` equal to its derivation — that is precisely what rule
    # 1 does on the first source. The DRIVE's own `DATABASE_NAME` belongs to the
    # REAL checkout it was launched from, and leaving that in place makes every
    # case below look like an operator who exported somebody else's name: the
    # leg's derivation check fires, every case reports `DATABASE_NAME exported`,
    # and the cases that are about something else stop being about it.
    #
    # It is set, not re-sourced: sourcing db.sh again would also re-run its
    # source-time pin note, which prints on stderr and would land in the capture
    # that `silent` reads.
    #
    # AND THE PROVENANCE TRAVELS WITH THE NAME, because `scripts/db.sh:216`
    # exports the two AS A PAIR and `db_pin_effective_name`
    # (`scripts/db.sh:708`) branches on the LABEL before it looks at anything
    # else. Setting the name alone left the label this drive was LAUNCHED with
    # in place — and that is a property of the launcher, not of the scratch
    # checkout the line above is standing in.
    #
    # WHAT THAT DID: `.github/workflows/ci.yml:391` writes `DATABASE_NAME` into
    # `$GITHUB_ENV`, so on a runner every drive's first source of db.sh takes
    # rule 1 and labels it `DATABASE_NAME exported`. The label then won here,
    # the leg took the scratch derivation as an operator's override instead of
    # the `.env` pin the case wrote, and looked up a database nothing had
    # created:
    #
    #     FAILED  a present database under loop — wanted exit 0, got 2
    #            | !! this checkout's database djb_main_3c6f9b9a does not exist
    #            |    (DATABASE_NAME exported)
    #
    # Three red assertions on a laptop-green drive, over a leg that had not
    # moved. `derived` is what a shell standing in this scratch checkout would
    # carry, which is the same fidelity argument as the name itself.
    DATABASE_NAME="$(db_name)"
    DATABASE_NAME_SOURCE="derived"
    RC=0
    db_pin_leg "$mode" >"$OUT" 2>&1 || RC=$?
    DATABASE_NAME="$saved_name"
    # Restored the way it was found, and an UNSET label is restored to unset:
    # `db_pin_effective_name` reads `${DATABASE_NAME_SOURCE:-derived}`, so an
    # empty string and an absent variable mean the same thing to it today and
    # a drive should not be the reason that stays true.
    if [ -n "$saved_source_set" ]; then
        DATABASE_NAME_SOURCE="$saved_source"
    else
        unset DATABASE_NAME_SOURCE
    fi
    cd "$here"
}

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}

# A case that could not be POSED — never one that was inconvenient. The only
# poser here is the compose Postgres: three of the existence cases ask whether a
# name opens a real database, and there is no way to ask that of a server that
# is not running. It is COUNTED and its reason is REPRINTED at the end, so a
# green summary can never quietly mean "nothing was asked" — the same shape
# `test_db_zsh.sh` uses for its no-zsh and --no-live paths. In the gate's
# selftest leg the stack is always up (the pytest legs need it), so these cases
# skip on a laptop and run where the verdict is banked.
skip() {
    echo "  SKIP     ${CURRENT} — $1"
    SKIPPED=$((SKIPPED + 1))
    SKIP_REASONS="${SKIP_REASONS}
     ${CURRENT} — $1"
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

# SILENT ABOUT THE PIN — which is what the `# pinned` marker buys, and what it
# has always bought. The assertion is narrowed here rather than dropped, and the
# narrowing has a reason with a name: the leg now prints ONE line on
# every run saying which mode it is bound in (`db-pin mode: …`), because a leg
# that asks the existence question under `loop` and not under `fast` and never
# says which it is in has a green that means one of two things without saying
# which (misses § P19 row 7). That line is the LEG announcing itself, not the
# leg being noisy about a pin a checkout already declared deliberate — so it is
# excluded by name, and ANY OTHER output still fails the case. A blanket
# `[ -s "$OUT" ]` here would have forced the mode line off the pinned path,
# which is the one path where a reader most needs to know whether the database
# behind that deliberate name was checked.
silent() {
    local residue
    residue="$(grep -v '^  db-pin mode: ' "$OUT" 2>/dev/null || true)"
    if [ -n "$residue" ]; then
        bad "printed something besides the mode line and must not — $(printf '%s' "$residue" | tr '\n' ' ')"
    elif ! grep -q '^  db-pin mode: ' "$OUT"; then
        bad "printed nothing at all — the mode line is owed on EVERY run, this one included"
    else
        ok "silent but for the leg's own mode line"
    fi
}

# --- the stack, and the two ways to take it away ------------------------------
#
# THE LEG'S EXISTENCE PROBE IS `docker compose exec -T db psql` (db.sh::db_psql),
# so "the stack is down" is simulated HERE by putting a `docker` on PATH that
# refuses and logs — the brief's first option, and the one that exercises the
# real call path rather than a hook the production code would have to carry for
# the drive's benefit. The shim lives under $WORK, outside the checkout, so it
# is not an untracked executable the instrument census has to have an opinion
# about (rung-execution §3, THE ONE SCRATCH LOCATION).
#
# The log is the second half: a case that asserts the question was NOT asked
# needs to see that nothing was called, and an empty log is that evidence.
#
# `SHIM_DIR` AND `SHIM_LOG` ARE GLOBALS SET IN PLACE, and the helper prints
# nothing: a first draft returned the directory through `$( … )` and every
# assignment it made died with the command substitution's subshell, so
# `[ -s "$SHIM_LOG" ]` read `[ -s "" ]` and the case that asserts the leg DID
# try to look was satisfied by a leg that had not.
SHIM_DIR=""
SHIM_LOG=""
make_docker_shim() {
    local shimdir="${WORK}/shim${N}"
    N=$((N + 1))
    mkdir -p "$shimdir"
    SHIM_DIR="$shimdir"
    SHIM_LOG="${shimdir}/docker-calls.log"
    : >"$SHIM_LOG"
    # Every argument, one line per call, then a failing status — which is what a
    # box with no docker daemon produces.
    {
        echo '#!/bin/sh'
        echo "printf '%s\\n' \"\$*\" >>\"${SHIM_LOG}\""
        echo 'exit 1'
    } >"${shimdir}/docker"
    chmod +x "${shimdir}/docker"
}

# `run_leg_in`, with the shim first on PATH for the length of the call and the
# caller's PATH restored byte-identical afterwards. git stays reachable: the
# shim directory is PREPENDED and holds one file.
# --- the OTHER reader of the name: rule 1's escape ----------------------------
#
# `scripts/db.sh` rule 1 — an exported `DATABASE_NAME` WINS over the derivation,
# and it is the documented escape (`db.sh:16-18`; CLAUDE.md § The schema
# discipline calls it "the only escape"). The reproduction is NOT simulated by
# setting a label by hand: that would be a second copy of the precedence living
# in the drive, and a drive carrying its own copy of the rule cannot catch the
# rule changing. Instead the case does what an operator does — exports the name
# and SOURCES db.sh — so rule 1's own line is what resolves it, and the label the
# leg prints is the one that line recorded.
#
# The subshell also `cd`s to the real checkout before sourcing, because that is
# where an operator stands: the derivation `db.sh` computes at source time is the
# REAL checkout's, while the leg, run from the scratch checkout, derives the
# scratch name. Those being different is what makes the assertion sharp — the
# leg has two names available and must report the one the run will open.
run_leg_in_with_exported_name() {
    local dir="$1" mode="$3" exported="$4"
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$ROOT"
        export DATABASE_NAME="$exported"
        unset DATABASE_NAME_SOURCE
        # shellcheck source=scripts/db.sh
        . scripts/db.sh
        cd "$dir"
        db_pin_leg "$mode"
    ) >"$OUT" 2>&1 || RC=$?
}

# THE OTHER ORDER, AND IT IS A DIFFERENT DEFECT. Above, the name is exported
# BEFORE db.sh is sourced — rule 1 sees it and labels it `exported`. Here the
# shell sources db.sh FIRST (so the label is written as `derived`) and only then
# re-exports a different name, which is what an operator does at an interactive
# prompt while debugging. The label stays `derived` because nothing re-sources
# db.sh, and a leg that trusts the label reports on a name that is no longer in
# the variable. No script in this tree does this; a human at a prompt does.
run_leg_in_with_reexported_name() {
    local dir="$1" mode="$3" reexported="$4"
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        # SOURCED IN THE CHECKOUT THE LEG WILL RUN IN, not in $ROOT. A verifier
        # found the old shape sourcing db.sh at $ROOT and running the leg at
        # $dir, so `$DATABASE_NAME` held the REAL checkout's derivation while the
        # leg derived the scratch one — two names that differ for a reason no
        # case is about, which hides the very mismatch these cases exist to
        # drive. Sourcing here makes `$DATABASE_NAME` the scratch derivation, so
        # an untouched shell agrees with the leg and any disagreement is the
        # thing the case planted.
        cd "$dir"
        unset DATABASE_NAME DATABASE_NAME_SOURCE
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh"
        # …and NOW the operator types this, with db.sh already sourced.
        export DATABASE_NAME="$reexported"
        db_pin_leg "$mode"
    ) >"$OUT" 2>&1 || RC=$?
}

# A database this drive CREATES, so that a fixture can pose "the derived name is
# there and the exported one is not" instead of leaving both absent. Every name
# is remembered and dropped at exit — the drive owns what it makes, and it makes
# only scratch names no checkout derives.
DRIVE_DBS=""
make_database() {
    db_create "$1" >/dev/null 2>&1 || return 1
    DRIVE_DBS="${DRIVE_DBS} $1"
}
drive_at_exit 'for __d in $DRIVE_DBS; do db_drop "$__d" >/dev/null 2>&1 || true; done'

# The same shape with NO export at all, posed deterministically rather than
# inherited: the gate's environment is not this drive's to assume, and a case
# that asserts "the label reads derived" must make sure nothing upstream set
# DATABASE_NAME before deciding that the leg got it wrong.
run_leg_in_without_export() {
    local dir="$1" mode="$3"
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        # Sourced in the SAME checkout the leg runs in — see the note in
        # `run_leg_in_with_reexported_name`. This is the control every
        # label case leans on, so it has to be the honest shape: nothing
        # exported, and `$DATABASE_NAME` equal to what the leg derives.
        cd "$dir"
        unset DATABASE_NAME DATABASE_NAME_SOURCE
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh"
        db_pin_leg "$mode"
    ) >"$OUT" 2>&1 || RC=$?
}

run_leg_in_without_docker() {
    local saved_search
    make_docker_shim
    saved_search="$PATH"
    PATH="${SHIM_DIR}:${PATH}"
    run_leg_in "$1" "$2" "$3"
    PATH="$saved_search"
}

# Is the compose Postgres there for this drive to ask about? The probe is spelled
# out here rather than borrowed from `db_reachable` DELIBERATELY: `db_reachable`
# is part of what the existence half added, and a drive whose skip decision depends on the
# code under test skips silently on the baseline instead of going red there —
# which is the one run where the red has to be legible (rung-execution §2).
STACK=""
if db_query 'SELECT 1' -tA >/dev/null 2>&1; then
    STACK=1
fi

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

# --- setup.sh's pin block, run for real against the leg ------------------------
#
# THE LOOP THIS SECTION EXISTS FOR. An unmarked `.env` pin that differs from the
# derivation, with the SAME name exported in the shell (a shell that sourced
# db.sh before the checkout moved — setup.sh's own closing block tells an
# operator to source it). setup.sh used to write the exported name back over the
# pin and migrate it, while the leg refused the same `.env` naming setup.sh as
# the remedy: each instrument pointed at the other. The cases below run
# setup.sh's REAL block — extracted from the file, from its `db_pin_decide` call
# to the `db_create` that follows it — in a scratch checkout, and then run the
# REAL leg on the same checkout.
#
# WHAT IS NOT setup.sh's OWN TEXT, declared: `env_set` is extracted from
# setup.sh too, but its `make_tmp` (the registry of setup's EXIT trap) is a
# two-line stand-in here — a mktemp under $WORK — because arming setup's trap
# inside this drive would replace the drive's own. And `db_create` is not run:
# the block's job is to settle the NAME, and the extraction stops at the line
# that would create it. Whether the settled name is created and migrated is
# setup.sh's next two lines, read as text by `case_setup_creates_after_the_name_is_settled`.
SETUP_BLOCK=""
SETUP_ENV_SET=""
setup_extract() {
    local setup="${ROOT}/scripts/setup.sh"
    SETUP_BLOCK="$(awk '/^db_pin_decide$/ { on = 1 } on && /^db_create$/ { exit } on { print }' "$setup")"
    SETUP_ENV_SET="$(awk '/^env_set\(\) \{$/ { on = 1 } on { print } on && /^}$/ { exit }' "$setup")"
    [ -n "$SETUP_BLOCK" ] || cannot_look "setup.sh has no column-zero db_pin_decide … db_create block to run"
    [ -n "$SETUP_ENV_SET" ] || cannot_look "setup.sh defines no env_set() at column zero"
}

# run_setup_block <dir> <case> <exported name or empty> — the block, in a
# subshell standing in the scratch checkout, with db.sh sourced there the way
# setup.sh sources it (so rule 1 resolves the export, not this drive). Output
# to $OUT; the name the block leaves in DATABASE_NAME is its last line.
run_setup_block() {
    local dir="$1" exported="$3"
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$dir"
        unset DATABASE_NAME DATABASE_NAME_SOURCE
        if [ -n "$exported" ]; then
            export DATABASE_NAME="$exported"
        fi
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh" 2>/dev/null
        make_tmp() { eval "$1=\"\$(mktemp \"${WORK}/envset.XXXXXX\")\""; }
        eval "$SETUP_ENV_SET"
        eval "$SETUP_BLOCK"
        echo "block-left-DATABASE_NAME=${DATABASE_NAME}"
    ) >"$OUT" 2>&1 || RC=$?
}

env_line() {
    grep -E '^DATABASE_NAME=' "$REPO/.env" | tail -1
}

# THE ENVIRONMENT STEP, THEN THE PIN BLOCK — setup.sh's own order. The env-sync
# fence rebuilds `.env` from `.env.example` BEFORE the pin block reads it, so a
# marker the rebuild drops is a marker the pin block never sees: the block then
# overrides the name and tells the reader to add the line that was just erased.
# Driving the block alone (above) cannot see that; this runs both, extracted
# from setup.sh, in the order setup.sh runs them.
SETUP_ENV_FENCE=""
setup_extract_env_fence() {
    SETUP_ENV_FENCE="$(sed -n '/^# >>> env-sync >>>$/,/^# <<< env-sync <<<$/p' "${ROOT}/scripts/setup.sh")"
    case "$SETUP_ENV_FENCE" in
    *"env_sync_from_example() {"*) ;;
    *) cannot_look "setup.sh's env-sync fence defines no env_sync_from_example" ;;
    esac
}

run_setup_env_then_block() {
    local dir="$1"
    CURRENT="$2"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$dir"
        unset DATABASE_NAME DATABASE_NAME_SOURCE
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh" 2>/dev/null
        make_tmp() { eval "$1=\"\$(mktemp \"${WORK}/envset.XXXXXX\")\""; }
        eval "$SETUP_ENV_FENCE"
        env_sync_from_example
        eval "$SETUP_ENV_SET"
        eval "$SETUP_BLOCK"
        echo "block-left-DATABASE_NAME=${DATABASE_NAME}"
    ) >"$OUT" 2>&1 || RC=$?
}

case_setup_keeps_a_pinned_line_through_the_environment_step() {
    setup_extract
    setup_extract_env_fence
    fresh_checkout
    printf '%s\n' '# the database' 'DATABASE_URL=' 'DATABASE_NAME=' 'DEBUG=0' >"$REPO/.env.example"
    write_env '# the database' 'DATABASE_URL=' '# pinned' 'DATABASE_NAME=djb_stale' 'DEBUG=1'
    cp "$REPO/.env" "${WORK}/pinned-through-sync-before.env"
    run_setup_env_then_block "$REPO" "setup's environment step, then its pin block, over a # pinned stale pin"
    exits 0
    says "DATABASE_NAME left alone"
    says_not "overridden"
    if cmp -s "$REPO/.env" "${WORK}/pinned-through-sync-before.env"; then
        ok ".env is byte-identical after both steps"
    else
        bad ".env changed: $(diff "${WORK}/pinned-through-sync-before.env" "$REPO/.env" | tr '\n' ' ')"
    fi
}

case_setup_adopts_the_derivation_over_an_unmarked_exported_stale_pin() {
    setup_extract
    fresh_checkout
    write_env "DEBUG=1" "DATABASE_NAME=djb_stale"
    run_setup_block "$REPO" "setup over an unmarked stale pin exported in the shell" djb_stale
    exits 0
    says "DATABASE_NAME: the unmarked .env pin djb_stale (also exported in this shell) was overridden by the derivation ${DERIVED}; add \"# pinned\" above it to keep it"
    says "unset DATABASE_NAME"
    says "block-left-DATABASE_NAME=${DERIVED}"
    if [ "$(env_line)" = "DATABASE_NAME=${DERIVED}" ]; then
        ok ".env now carries the derivation"
    else
        bad ".env carries '$(env_line)', not DATABASE_NAME=${DERIVED}"
    fi
    # AND THE LEG, ON THE SAME CHECKOUT, HAS NOTHING TO SAY — the other half of
    # the loop. Full mode is the mode the incident refused in; the existence
    # half needs the stack, so full runs where it is up and fast (the whole pin
    # comparison, no database) runs everywhere.
    run_leg_in "$REPO" "the leg after setup reconciled" fast
    exits 0
    says_not "DISAGREE"
    if [ -n "$STACK" ]; then
        make_database "$DERIVED" || cannot_look "could not create ${DERIVED} for the full-mode leg"
        run_leg_in "$REPO" "the leg after setup reconciled, full mode" full
        exits 0
        says_not "DISAGREE"
    else
        CURRENT="the leg after setup reconciled, full mode"
        skip "the compose Postgres is not reachable — full mode asks whether ${DERIVED} exists"
    fi
}

case_setup_names_only_the_pin_when_nothing_is_exported() {
    setup_extract
    fresh_checkout
    write_env "DATABASE_NAME=djb_stale"
    run_setup_block "$REPO" "setup over an unmarked stale pin, nothing exported" ""
    exits 0
    says "DATABASE_NAME: the unmarked .env pin djb_stale was overridden by the derivation ${DERIVED}; add \"# pinned\" above it to keep it"
    says_not "also exported"
    says "block-left-DATABASE_NAME=${DERIVED}"
}

case_setup_leaves_a_pinned_line_alone() {
    # `# pinned` present → unchanged behaviour: the pin stays byte-identical,
    # the run keeps what db.sh resolved, and the old sentence is printed.
    setup_extract
    fresh_checkout
    write_env "# pinned" "DATABASE_NAME=djb_stale"
    cp "$REPO/.env" "${WORK}/pinned-before.env"
    run_setup_block "$REPO" "setup over a # pinned stale pin exported in the shell" djb_stale
    exits 0
    says "DATABASE_NAME left alone"
    says_not "overridden"
    says "block-left-DATABASE_NAME=djb_stale"
    if cmp -s "$REPO/.env" "${WORK}/pinned-before.env"; then
        ok ".env is byte-identical"
    else
        bad ".env changed under # pinned"
    fi
}

case_setup_and_the_leg_read_one_decision_table() {
    # ONE RESOLVER. A second copy of the table in either reader is the defect
    # this section closes, so the readers are held to calling db_pin_decide and
    # to asking none of its ingredients themselves.
    CURRENT="setup.sh, rung_start.sh and db_pin_leg read one decision table"
    OUT="${WORK}/one-table.log"
    : >"$OUT"
    local leg_body
    # setup.sh AND rung_start.sh — the second carried its own copy of setup's
    # pin block, and every builder runs it before anything else.
    local reader
    for reader in setup.sh rung_start.sh; do
        if grep -q '^db_pin_decide$' "${ROOT}/scripts/${reader}"; then
            ok "${reader} calls db_pin_decide at column zero"
        else
            bad "${reader} never calls db_pin_decide — its pin block decides some other way"
        fi
        if grep -nE 'db_pin_marked|db_pin_line_has_inline_comment|db_env_file_pin|DB_PIN_MARKER_ERE|#\[\[:space:\]\]\*pinned' "${ROOT}/scripts/${reader}" | grep -v '^[0-9]*:[[:space:]]*#' | grep -v 'DB_PIN_MARKER_ERE="\$DB_PIN_MARKER_ERE"\|DB_PIN_MARKER_ERE:-\|ENVIRON\["DB_PIN_MARKER_ERE"\]' >"$OUT"; then
            bad "${reader} asks an ingredient of the table itself — a second decision table: $(tr '\n' ' ' <"$OUT")"
        else
            ok "${reader} asks no ingredient of the table itself"
        fi
    done
    leg_body="$(awk '/^db_pin_leg\(\) \{$/ { on = 1 } on { print } on && /^}$/ { exit }' "${ROOT}/scripts/db.sh")"
    case "$leg_body" in
    *"db_pin_decide"*) ok "db_pin_leg calls db_pin_decide" ;;
    *) bad "db_pin_leg never calls db_pin_decide" ;;
    esac
    if grep -v '^[[:space:]]*#' <<<"$leg_body" | grep -E 'db_pin_marked|db_pin_line_has_inline_comment|db_env_file_pin' >/dev/null; then
        bad "db_pin_leg asks an ingredient of the table itself — a second decision table"
    else
        ok "db_pin_leg asks no ingredient of the table itself"
    fi
}

case_setup_creates_after_the_name_is_settled() {
    # The block may override a stale exported name; a db_create above it would
    # prepare the name the run no longer uses.
    CURRENT="setup.sh creates the database after the name is settled"
    OUT="${WORK}/create-order.log"
    : >"$OUT"
    local decide create
    decide="$(grep -n '^db_pin_decide$' "${ROOT}/scripts/setup.sh" | head -1 | cut -d: -f1 || true)"
    create="$(grep -n '^db_create$' "${ROOT}/scripts/setup.sh" | head -1 | cut -d: -f1 || true)"
    if [ -n "$decide" ] && [ -n "$create" ] && [ "$create" -gt "$decide" ]; then
        ok "db_create (line ${create}) follows db_pin_decide (line ${decide})"
    else
        bad "db_create (line ${create:-none}) does not follow db_pin_decide (line ${decide:-none})"
    fi
}

case_a_pinned_line_passes_silently() {
    # The marker is the checkout saying it meant this name. A pin is legal
    # (db.sh rule 1); what the marker buys is silence, so the leg can never
    # become noise a deliberate checkout learns to skip.
    #
    # THE MARKER IS ON ITS OWN LINE, ABOVE A BARE VALUE. This case used to
    # write `DATABASE_NAME=djb_main  # pinned` and is re-pointed: that inline
    # form is now refused, because django-environ and docker --env-file read
    # the comment INTO the name (db.sh, "THE MARKER'S GRAMMAR").
    fresh_checkout
    write_env "# pinned" "DATABASE_NAME=djb_main" "DEBUG=1"
    run_leg_in "$REPO" "a pinned line"
    exits 0
    silent
}

case_the_marker_carries_a_reason_and_still_passes() {
    # The own-line form's one gain worth having: the marker can say WHY, and
    # the reason is on the same line as the word. A grammar that refused this
    # would push the reason somewhere no reader of the pin would find it.
    fresh_checkout
    write_env "# pinned — the owner's live development database" \
        "DATABASE_NAME=djb_main" "DEBUG=1"
    run_leg_in "$REPO" "a marker carrying its reason"
    exits 0
    silent
}

case_the_marker_must_be_directly_above_the_database_name_line() {
    # `# pinned` somewhere else in the file is not this line's marker. The old
    # grammar anchored on "the DATABASE_NAME line"; the new one anchors on
    # ADJACENCY, and it has to be as strict, or a file that merely CONTAINS the
    # word silences the leg for every checkout that copied that .env.
    fresh_checkout
    write_env "# pinned — a comment about something else entirely" \
        "REDIS_URL=redis://localhost" "DATABASE_NAME=djb_main"
    run_leg_in "$REPO" "a marker two lines up"
    exits 1
    says "$DERIVED"

    # And the marker belongs to the line the pin is READ from — the last one,
    # matching django-environ's last-wins reading. A marker over an earlier,
    # overridden DATABASE_NAME line silences nothing.
    fresh_checkout
    write_env "# pinned" "DATABASE_NAME=${DERIVED}" "DATABASE_NAME=djb_stale_second"
    run_leg_in "$REPO" "a marker over the overridden first line"
    exits 1
    says "djb_stale_second"
}

case_the_inline_form_is_refused() {
    # THE RUNG'S SEAM, IN THE REFUSING DIRECTION. The form this file itself
    # prescribed until now is a corruption, and the leg has to say so rather
    # than quietly keep passing it.
    fresh_checkout
    write_env "DATABASE_NAME=djb_main  # pinned" "DEBUG=1"
    run_leg_in "$REPO" "the old inline marker form"
    exits 1
    says "INLINE COMMENT"
    # The two-line rewrite, printed — a refusal a reader can act on without
    # going and reading db.sh's header.
    says "# pinned"
    says "DATABASE_NAME=djb_main"
    # ...and printed CLEAN: the suggested line must not carry the whitespace
    # that separated the value from the comment it just removed.
    if grep -qE '^ *DATABASE_NAME=djb_main +$' "$OUT"; then
        bad "the suggested rewrite has trailing whitespace — it hands the reader a second corrupt line"
    else
        ok "the suggested rewrite is trimmed"
    fi
}

case_an_inline_comment_that_agrees_is_still_refused() {
    # THE FALSE GREEN THIS RUNG CLOSES, and the strongest case here. Before
    # this change `db_env_file_pin` cut the comment off before comparing, so a
    # line whose value MATCHED the derivation passed the leg in silence — while
    # a bare `manage.py`, reading through django-environ, opened a database
    # called `<derivation>  # pinned`. Agreement was the disguise, not the
    # safety.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}  # pinned"
    run_leg_in "$REPO" "an inline comment on a value that agrees"
    exits 1
    says "INLINE COMMENT"
    says_not "agree"
}

case_any_inline_comment_is_refused_not_only_the_marker() {
    # The corruption is the `#`, not the word after it. A line commented for
    # any reason at all resolves to a name with the comment inside it.
    fresh_checkout
    write_env "DATABASE_NAME=djb_main # temporary, see the runbook"
    run_leg_in "$REPO" "an inline comment that is not the marker"
    exits 1
    says "INLINE COMMENT"
}

read_env_three_ways() {
    # Prints one line per reader that could be posed: "<reader> [<value>]".
    # A reader that is not available prints "<reader> SKIP <reason>" — declared,
    # never silently dropped, so a green run can be told from a vacuous one.
    local envfile="$1" py
    printf 'shell [%s]\n' \
        "$(
            set -a
            # shellcheck disable=SC1090
            . "$envfile"
            set +a
            printf '%s' "${DATABASE_NAME:-}"
        )"
    py="${ROOT}/.venv/bin/python"
    if [ -x "$py" ] && "$py" -c 'import environ' >/dev/null 2>&1; then
        printf 'environ [%s]\n' "$("$py" -c '
import os, sys, environ
os.environ.pop("DATABASE_NAME", None)
environ.Env.read_env(sys.argv[1], overwrite=True)
sys.stdout.write(os.environ.get("DATABASE_NAME", "<unset>"))
' "$envfile")"
    else
        printf 'environ SKIP no .venv python with django-environ in this tree\n'
    fi
    if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 &&
        docker run --rm --env-file "$envfile" alpine:3 true >/dev/null 2>&1; then
        printf 'docker [%s]\n' \
            "$(docker run --rm --env-file "$envfile" alpine:3 printenv DATABASE_NAME 2>/dev/null || true)"
    else
        printf 'docker SKIP no usable docker (or alpine:3 unavailable) on this machine\n'
    fi
}

case_the_new_form_reads_identically_for_every_reader() {
    # THE RUNG'S SEAM, IN THE PASSING DIRECTION, and the only case here that
    # asks the actual readers rather than db.sh's model of them. `.env` is read
    # three ways in this repository — a shell `. .env`, django-environ (every
    # bare `manage.py`), and `docker --env-file` (compose) — and the marker's
    # whole job is to mean the same thing to all of them.
    CURRENT="the three readers, new form"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    local envfile want line reader value seen
    envfile="${WORK}/three-readers-new.env"
    want="djb_three_readers"
    printf '# pinned\nDATABASE_NAME=%s\n' "$want" >"$envfile"
    read_env_three_ways "$envfile" >"$OUT" 2>&1
    seen=0
    while IFS= read -r line; do
        reader="${line%% *}"
        value="${line#* }"
        case "$value" in
        SKIP*)
            ok "${reader} — ${value} (declared)"
            continue
            ;;
        esac
        seen=$((seen + 1))
        if [ "$value" = "[${want}]" ]; then
            ok "${reader} reads ${value} — the clean value"
        else
            bad "${reader} reads ${value} and must read [${want}] — the own-line marker is not neutral to this reader"
        fi
    done <"$OUT"
    if [ "$seen" -lt 2 ]; then
        bad "only ${seen} reader could be posed — this case proves agreement and cannot do it with one"
    else
        ok "${seen} readers posed (a one-reader run would be vacuous and is refused)"
    fi
}

case_the_old_form_still_splits_the_readers() {
    # THE DISEASE, KEPT ON THE RECORD. The inline form is refused by the leg;
    # this is WHY, measured rather than asserted from memory. If this case ever
    # goes green-by-agreement it is not a failure of the fix — it means a
    # reader changed its mind about trailing comments, and the refusal's
    # reasoning needs re-reading before anybody relaxes it.
    CURRENT="the three readers, old inline form"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    local envfile want line reader value clean dirty
    envfile="${WORK}/three-readers-old.env"
    want="djb_three_readers"
    printf 'DATABASE_NAME=%s  # pinned\n' "$want" >"$envfile"
    read_env_three_ways "$envfile" >"$OUT" 2>&1
    clean=0
    dirty=0
    while IFS= read -r line; do
        reader="${line%% *}"
        value="${line#* }"
        case "$value" in
        SKIP*) continue ;;
        esac
        if [ "$value" = "[${want}]" ]; then
            clean=$((clean + 1))
            echo "           | ${reader} strips the comment: ${value}"
        else
            dirty=$((dirty + 1))
            echo "           | ${reader} keeps the comment IN THE NAME: ${value}"
        fi
    done <"$OUT"
    if [ "$dirty" -gt 0 ]; then
        ok "the inline form splits the readers (${clean} strip, ${dirty} keep the comment in the name) — which is what db_pin_leg refuses"
    else
        bad "every reader posed stripped the comment — the premise of the inline-form refusal has moved and db.sh's reasoning needs re-reading before it is relaxed"
    fi
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
    write_env "# pinned" "DATABASE_NAME=${DERIVED}"
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

# --- the second question, and the mode that decides whether it is asked -------

case_under_loop_an_absent_database_is_exit_2_naming_setup() {
    # THE SEAM. The P19 bank ran ten green minutes and then refused at the
    # selftest leg because the primary checkout's database was gone. The pin had
    # agreed the whole time — this is the leg asking the other half of the
    # question, nine legs earlier.
    #
    # THE VICTIM IS BUILT, NOT FOUND (rung-execution §2): a scratch checkout
    # under mktemp derives its own djb_main_<hash of that path> by the path-hash
    # derivation db.sh documents, and nothing has ever created it. No database in this drive is
    # created, opened or dropped.
    if [ "$STACK" != "1" ]; then
        CURRENT="an absent database under loop"
        OUT=""
        skip "the compose Postgres did not answer — an ABSENT database cannot be told from an ABSENT SERVER without one"
        return 0
    fi
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    run_leg_in "$REPO" "an absent database under loop" loop
    exits 2
    says "does not exist"
    says "$DERIVED"
    says "./scripts/setup.sh"
    # And the leg says which mode bound it — the line that makes a green mean
    # one thing instead of two.
    says "db-pin mode: loop"
    # It must NOT blame docker: the server answered, so this is a finding about
    # the database and not a could-not-look about the stack.
    says_not "COULD NOT LOOK"
}

case_under_full_the_same_refusal() {
    # The full gate binds it identically — and `--pr` and `--bank` reach here
    # too, because check.sh normalises both to the full mode before this leg.
    if [ "$STACK" != "1" ]; then
        CURRENT="an absent database under full"
        OUT=""
        skip "the compose Postgres did not answer — the same reason as the case above"
        return 0
    fi
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    run_leg_in "$REPO" "an absent database under full" full
    exits 2
    says "does not exist"
    says "$DERIVED"
    says "./scripts/setup.sh"
    says "db-pin mode: full"
}

case_under_loop_a_present_database_says_so() {
    # The other direction, and without it the two cases above are satisfied by a
    # leg that refuses unconditionally. The name asked about is THIS checkout's
    # own database, which `rung_start.sh`/`setup.sh` created and which the gate
    # is standing in while it reads this — pinned into the scratch checkout's
    # .env with the marker, so the pin comparison passes deliberately and the
    # existence question is the only one left.
    if [ "$STACK" != "1" ]; then
        CURRENT="a present database under loop"
        OUT=""
        skip "the compose Postgres did not answer — a PRESENT database cannot be demonstrated without one"
        return 0
    fi
    fresh_checkout
    write_env "# pinned — this checkout's real database, so the leg has something to find" \
        "DATABASE_NAME=${DATABASE_NAME}"
    run_leg_in "$REPO" "a present database under loop" loop
    exits 0
    says "database ${DATABASE_NAME} exists"
    says_not "does not exist"
}

case_under_fast_existence_is_not_asked_and_says_so() {
    # `--fast` NEEDS NO DATABASE — `docs/product/build-contract.md` § Interfaces,
    # the `--fast` row: "No services needed beyond what mypy/django needs to
    # import settings." Pre-commit runs `--fast` on every laptop, and a laptop
    # with docker closed is the ordinary case, not the exception. So the
    # question is not asked, the leg SAYS it is not asking, and the proof that
    # it did not ask is the shim's empty log — `docker` was on PATH, refusing
    # and recording, and was never reached.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    run_leg_in_without_docker "$REPO" "an absent database under fast" fast
    exits 0
    says "existence not checked (--fast needs no database)"
    says_not "does not exist"
    says_not "COULD NOT LOOK"
    if [ -s "$SHIM_LOG" ]; then
        bad "the docker shim WAS called under fast: $(tr '\n' ' ' <"$SHIM_LOG")"
    else
        ok "the docker shim recorded nothing — no exec, no psql, no stack"
    fi
    if grep -q 'exec' "$SHIM_LOG" 2>/dev/null; then
        bad "the shim log carries an 'exec' — the existence probe ran under fast"
    else
        ok "no 'exec' in the shim log"
    fi
}

case_an_unreachable_stack_under_loop_is_could_not_look() {
    # §I, and the half of it that is easy to get wrong: an unreadable input is
    # exit 2, NEVER a judgment on the readable part. The pin here is perfect and
    # was compared successfully; what could not be read is whether the name opens
    # anything. Reporting that as `does not exist` would send a reader to
    # setup.sh for a docker problem, and reporting it as a pass would vouch for a
    # database nobody managed to ask about. It is a could-not-look, it names
    # docker, and it is exit 2.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    run_leg_in_without_docker "$REPO" "an unreachable stack under loop" loop
    exits 2
    says "COULD NOT LOOK"
    says "docker"
    says "db-pin mode: loop"
    says_not "does not exist"
    if [ -s "$SHIM_LOG" ]; then
        ok "the leg did try to look — the shim recorded $(wc -l <"$SHIM_LOG" | tr -d ' ') call(s)"
    else
        bad "the shim recorded nothing, so the refusal was reached without ever asking — the case is asserting the wrong thing"
    fi
}

case_an_exported_database_name_is_the_one_asked_about() {
    # THE GAP A VERIFIER MEASURED, AND IT IS THE WHOLE OF THIS CASE. The leg
    # asked about the name the PIN COMPARISON concluded and never about the name
    # rule 1 resolves — so with `DATABASE_NAME` exported it printed
    # `database <derived> exists` and exited 0, vouching for a database the suite
    # would not open. Every script here, `db_exists`/`db_create`/`db_drop`'s own
    # default argument, `backup.sh::db_present` and the pytest run all resolve the
    # exported name; the one reader that did not was the leg reporting on it.
    #
    # THE VICTIM IS BUILT: a name nothing has ever created, exported into a
    # subshell that sources db.sh the way an operator's shell does.
    #
    # AND SO IS THE DECOY, which is the half this case was missing. A verifier
    # measured that three of the six assertions below passed on the BASELINE
    # too — `exits 2`, `says "does not exist"` and the `says_not` — because the
    # scratch checkout's derived name did not exist either, so the old leg
    # refused for the wrong reason and looked right doing it. A case whose red
    # is carried by half its assertions is half a case. So the fixture now
    # CREATES the derived database: on the baseline the leg finds it, says
    # `<derived> exists` and exits 0, and all six assertions carry the red.
    if [ "$STACK" != "1" ]; then
        CURRENT="an exported DATABASE_NAME under loop"
        OUT=""
        skip "the compose Postgres did not answer — an ABSENT database cannot be told from an ABSENT SERVER without one"
        return 0
    fi
    fresh_checkout
    # The .env pins the scratch checkout's OWN derived name, so the pin
    # comparison passes and the only thing left to get wrong is which name the
    # existence question is asked about.
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    if ! make_database "$DERIVED"; then
        CURRENT="an exported DATABASE_NAME under loop"
        OUT=""
        skip "could not create the decoy database ${DERIVED} — without it three of this case's assertions pass vacuously, so it is not run at all"
        return 0
    fi
    run_leg_in_with_exported_name "$REPO" "an exported DATABASE_NAME under loop" loop djb_vg1r_does_not_exist
    exits 2
    says "djb_vg1r_does_not_exist"
    says "does not exist"
    says "DATABASE_NAME exported"
    # AND IT MUST NOT VOUCH FOR THE OTHER NAME. This is the assertion the old
    # leg failed: `<derived> exists` was true and irrelevant.
    says_not "${DERIVED} exists"
    # `setup.sh` is the wrong remedy under an override — it would prepare the
    # DERIVED name and leave the export pointing at nothing.
    says "unset DATABASE_NAME"

    # The control, and without it the case is satisfied by a leg that refuses
    # whenever anything is exported: the SAME export, pointed at a database that
    # really is there, passes and says so.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    run_leg_in_with_exported_name "$REPO" "an exported name that DOES exist" loop "$DATABASE_NAME"
    exits 0
    says "database ${DATABASE_NAME} exists (DATABASE_NAME exported)"
}

case_a_pinned_absent_name_names_the_pin_and_its_remedy() {
    # THE CELL NOBODY DROVE, AND BOTH ITS SENTENCES WERE WRONG. A `# pinned`
    # .env naming a database that is not there used to print
    #
    #   !! this checkout's database djb_x does not exist (.env pin) — run ./scripts/setup.sh
    #      The pin and the derivation agree on the NAME and there is nothing behind it.
    #
    # and BOTH halves were false. A marked pin reaches the existence check only
    # when the pin and the derivation DIFFER — agreement is handled one branch
    # up, under the `derived` label — so "agree on the NAME" was printed
    # directly beneath a leg that only runs when they do not. And the remedy was
    # the wrong command: `setup.sh`'s `db_pin_marked` branch LEAVES the pin
    # alone, prints "DATABASE_NAME left alone", and migrates the DERIVATION
    # (scripts/setup.sh). A reader following it would watch a different database
    # get prepared and come back to the identical refusal.
    if [ "$STACK" != "1" ]; then
        CURRENT="a pinned absent name"
        OUT=""
        skip "the compose Postgres did not answer — an ABSENT database cannot be told from an ABSENT SERVER without one"
        return 0
    fi
    fresh_checkout
    write_env "# pinned — deliberate, and not this checkout's derivation" \
        "DATABASE_NAME=djb_g4f2_pinned_absent"
    run_leg_in_without_export "$REPO" "a pinned absent name" loop
    exits 2
    # The PINNED name, not the derivation — the refusal is about the name a bare
    # `manage.py` will open, which is the whole point of the marker.
    says "djb_g4f2_pinned_absent"
    says ".env pin"
    # It names the derivation too, and says which way the two went.
    says "$DERIVED"
    says "the pin DIFFERS from the derivation"
    # The sentence that was false is gone…
    says_not "The pin and the derivation agree on the NAME"
    # …and the remedy is the one that actually creates this name.
    says "DATABASE_NAME=djb_g4f2_pinned_absent ./scripts/setup.sh"
    says "pinned"
    # A BARE `./scripts/setup.sh` MUST NOT BE OFFERED AS THE FIX. It may still
    # be mentioned as part of the second route (drop the marker, then re-run it),
    # so the assertion is on the refusal HEADLINE, which is the line a reader
    # acts on first and the one the old text put it in.
    if grep -q '^!!.*does not exist.*run \./scripts/setup\.sh' "$OUT"; then
        bad "the headline still sends the reader to a bare ./scripts/setup.sh, which under \`# pinned\` prepares the DERIVATION and not this name"
    else
        ok "the headline does not offer a bare ./scripts/setup.sh"
    fi
}

case_a_re_exported_name_after_sourcing_is_asked_about() {
    # THE LABEL CAN LIE, AND THIS IS HOW. `DATABASE_NAME_SOURCE` is sticky on
    # purpose — a child that inherits a derived name must not be re-labelled
    # "exported" — and sticky is what lets it go stale. A shell that sources
    # db.sh (label written: `derived`) and then types
    # `export DATABASE_NAME=something_else` keeps the old label, and a leg that
    # trusts the label reports on a name that is no longer in the variable.
    #
    # Measured before the fix: parent `DATABASE_NAME=djb_rung_… SOURCE=derived`,
    # child re-exports `djb_vg1r_does_not_exist`, `db_pin_leg loop` printed
    # `database djb_rung_… exists (derived)` and returned 0 — a green vouch for a
    # database the operator's very next command would not open.
    #
    # No script in this tree reaches this; an interactive prompt does, and it is
    # the prompt an operator is standing at precisely when something is already
    # wrong.
    if [ "$STACK" != "1" ]; then
        CURRENT="a re-exported name after sourcing"
        OUT=""
        skip "the compose Postgres did not answer — an ABSENT database cannot be told from an ABSENT SERVER without one"
        return 0
    fi
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    # The decoy again: the derived name EXISTS, so a leg that trusts the stale
    # label finds it and exits 0 — which is exactly the green this case refuses.
    if ! make_database "$DERIVED"; then
        CURRENT="a re-exported name after sourcing"
        OUT=""
        skip "could not create the decoy database ${DERIVED} — the stale-label vouch cannot be posed without something for the leg to vouch FOR"
        return 0
    fi
    run_leg_in_with_reexported_name "$REPO" "a re-exported name after sourcing" loop djb_g4f2_reexported_absent
    exits 2
    says "djb_g4f2_reexported_absent"
    says "DATABASE_NAME exported"
    # It must not vouch for the name the stale label pointed at.
    says_not "${DERIVED} exists"
    # And it says WHY it calls this exported when the operator exported nothing
    # before sourcing — otherwise the label reads as the leg being confused.
    says "does not match this checkout's derivation"
    says "inherited DATABASE_NAME_SOURCE label"

    # THE CONTROL, and it is the one that keeps the cross-check from being
    # "always report exported": an untouched shell, same fixture, same decoy
    # database — the label is honest, the value matches what rule 1 resolved,
    # and the leg reports `derived` with no note at all.
    run_leg_in_without_export "$REPO" "an untouched shell, same fixture" loop
    exits 0
    says "database ${DERIVED} exists (derived)"
    says_not "does not match this checkout's derivation"
}

case_a_child_process_with_a_new_name_is_asked_about_that_name() {
    # THE SAME LIE, ONE PROCESS BOUNDARY OVER — and this one is on the path the
    # tree itself recommends. `scripts/setup.sh` ends by telling an operator
    #
    #     Next:
    #       source scripts/db.sh          # export DATABASE_NAME in your shell
    #
    # so a shell with `DATABASE_NAME_SOURCE=derived` in it is the NORMAL state of
    # an operator's terminal, not an exotic one. From there, `DATABASE_NAME=other
    # ./some_script.sh` hands the child the LABEL from the environment and the
    # NAME from the command line; the child sources db.sh, the guard sees a label
    # already set and leaves `derived` in place, and a leg that trusts the label
    # vouches for a database the child will not open.
    #
    # The first fix recorded the resolved value beside the label and compared the
    # two — which this cell walks straight through, because rule 1's block runs
    # in the CHILD as well and re-records the value the child was handed. Nothing
    # the environment carries can authenticate the environment. The check that
    # holds is against `db_name`, a property of where the checkout IS.
    #
    # THE HARNESS HAS TO BE ABLE TO SEE IT. The parent shell is created INSIDE the
    # scratch checkout and sources db.sh there, so the parent's derivation is the
    # scratch name and the only thing that differs in the child is the name on
    # its command line. A parent sourcing at $ROOT would hand the child a
    # mismatch for a second reason — a different checkout — and the case would
    # pass without the cell ever being posed.
    if [ "$STACK" != "1" ]; then
        CURRENT="a child process with a new name"
        OUT=""
        skip "the compose Postgres did not answer — an ABSENT database cannot be told from an ABSENT SERVER without one"
        return 0
    fi
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}" "DEBUG=1"
    # The decoy: the derived name EXISTS, so a leg that believes the inherited
    # label finds it, says so and exits 0 — the green this case refuses.
    if ! make_database "$DERIVED"; then
        CURRENT="a child process with a new name"
        OUT=""
        skip "could not create the decoy database ${DERIVED} — without it the leg has nothing to wrongly vouch FOR"
        return 0
    fi
    local child="${WORK}/child-newname.sh"
    {
        echo '. "${1}/scripts/db.sh"'
        echo 'db_pin_leg loop'
    } >"$child"

    CURRENT="a child process with a new name"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$REPO"
        unset DATABASE_NAME DATABASE_NAME_SOURCE
        # THE PARENT: an operator's shell, doing what setup.sh told it to.
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh"
        # THE CHILD: one command, one new name, a fresh process.
        DATABASE_NAME=djb_g4f3_child_absent bash "$child" "$ROOT"
    ) >"$OUT" 2>&1 || RC=$?
    exits 2
    says "djb_g4f3_child_absent"
    says "DATABASE_NAME exported"
    says_not "${DERIVED} exists"
    says "does not match this checkout's derivation"

    # THE CONTROL, and it is the one that makes the case about the NAME rather
    # than about being a child: the same parent, the same child script, the same
    # decoy — and no name on the command line. The label is honest there, so the
    # leg must report `derived` and pass.
    CURRENT="the same child with no new name"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (
        cd "$REPO"
        unset DATABASE_NAME DATABASE_NAME_SOURCE
        # shellcheck source=scripts/db.sh
        . "${ROOT}/scripts/db.sh"
        bash "$child" "$ROOT"
    ) >"$OUT" 2>&1 || RC=$?
    exits 0
    says "database ${DERIVED} exists (derived)"
    says_not "does not match this checkout's derivation"
}

case_the_existence_line_names_its_source() {
    # A NAME WITHOUT ITS PROVENANCE IS HALF AN ANSWER. Three readers can supply
    # the name this leg reports on, they disagree exactly when something is
    # wrong, and `djb_x exists` reads identically whichever one it came from.
    if [ "$STACK" != "1" ]; then
        CURRENT="the source on the existence line"
        OUT=""
        skip "the compose Postgres did not answer — the existence line is not reached without one"
        return 0
    fi
    # derived: no .env pin at all, nothing exported.
    fresh_checkout
    rm -f "$REPO/.env"
    run_leg_in_without_export "$REPO" "the derived source" loop
    exits 2
    says "(derived)"
    says_not "DATABASE_NAME exported"

    # .env pin: a deliberate `# pinned` name, which is the one case where the
    # leg's own conclusion beats `$DATABASE_NAME` — the scripts derive, a bare
    # `manage.py` opens the pin, and the leg knows which is which.
    fresh_checkout
    write_env "# pinned — a deliberate name" "DATABASE_NAME=${DATABASE_NAME}"
    run_leg_in_without_export "$REPO" "the .env pin source" loop
    exits 0
    says "database ${DATABASE_NAME} exists (.env pin)"

    # ONE PRECEDENCE, AND THE TOOTH THAT KEEPS IT ONE. The rule lives at exactly
    # one line in db.sh; a second `${DATABASE_NAME:-` would be a second answer to
    # "is there an override", and two answers is the split brain this whole file
    # is written against.
    CURRENT="one precedence in db.sh"
    OUT="${WORK}/precedence.log"
    local decisions
    decisions="$(grep -cE '^[[:space:]]*DATABASE_NAME="\$\{DATABASE_NAME:-' "${ROOT}/scripts/db.sh" || true)"
    printf 'decisions=%s\n' "$decisions" >"$OUT"
    if [ "$decisions" = "1" ]; then
        ok "rule 1's precedence is decided in exactly one place in db.sh"
    else
        bad "db.sh decides the DATABASE_NAME precedence in ${decisions} place(s) — the leg would report on whichever one ran last"
    fi
    if grep -q 'DATABASE_NAME_SOURCE' "${ROOT}/scripts/db.sh"; then
        ok "and it records which branch it took, beside the decision"
    else
        bad "nothing records the source beside the decision — the leg would have to re-derive it, which is a second precedence"
    fi
}

case_the_mode_is_printed_on_every_run() {
    # THE MODE LINE, over the whole population of outcomes rather than one of
    # them. A leg whose behaviour forks on a mode and whose transcript does not
    # say which fork ran has a green that means either "the database is there"
    # or "nobody asked", and a reader of the log cannot tell them apart
    # (misses § P19 row 7). Four outcomes, three modes, one line every time.
    fresh_checkout
    write_env "DATABASE_NAME=djb_definitely_stale" "DEBUG=1"
    run_leg_in "$REPO" "the mode line on a refusal" fast
    exits 1
    says "db-pin mode: fast"

    fresh_checkout
    rm -f "$REPO/.env"
    run_leg_in "$REPO" "the mode line with no .env" fast
    exits 0
    says "db-pin mode: fast"

    fresh_checkout
    write_env "# pinned" "DATABASE_NAME=djb_main"
    run_leg_in "$REPO" "the mode line on the silent pinned path" fast
    exits 0
    says "db-pin mode: fast"

    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}"
    run_leg_in_without_docker "$REPO" "the mode line under loop" loop
    says "db-pin mode: loop"
}

case_a_missing_or_unknown_mode_is_exit_2() {
    # A leg that guesses its own mode is a leg that decides, for its caller,
    # whether a laptop's pre-commit needs docker. `check.sh` passes the word;
    # anything else is enforcement that has come loose, and 2 outranks a pass.
    fresh_checkout
    write_env "DATABASE_NAME=${DERIVED}"
    CURRENT="no mode at all"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$REPO" && db_pin_leg) >"$OUT" 2>&1 || RC=$?
    exits 2
    says "no mode"
    says "fast, loop or full"

    CURRENT="a mode nobody defines"
    N=$((N + 1))
    OUT="${WORK}/out${N}.log"
    RC=0
    (cd "$REPO" && db_pin_leg "--loop") >"$OUT" 2>&1 || RC=$?
    exits 2
    says "unknown mode"
    says "fast, loop or full"
    # And it must not have gone on to judge the pin after refusing the mode.
    says_not "agree"
}

case_the_db_pin_leg_passes_its_mode() {
    # THE GATE'S HALF. It is read out of `check.sh` rather than run through the
    # real gate for the reason `case_the_leg_is_wired_into_the_fast_tier` gives:
    # the full gate's per-checkout lock makes a nested `--fast` refuse, so this
    # drive cannot run the gate from inside the selftest leg.
    #
    # BUT IT IS NOT MERELY READ, AND THAT DISTINCTION COST A GATE RUN. The first
    # version of this case only asserted which TOKENS appear on the call line,
    # and went green on a line that could not run at all: the derivation was
    # written as `$(case "$MODE" in --fast) … esac)`, and a `case` pattern's `)`
    # closes the `$(` around it. Every token was present; bash's parse of the
    # substitution happens at RUNTIME, so `bash -n` was silent too; the real
    # `--fast` gate printed `syntax error near unexpected token` and the leg
    # refused the mangled word as an unknown mode — correctly, and nine legs in.
    # So the line is now EVALUATED here, once per mode, against a stub that
    # records what the leg was actually handed. A grep over tokens is a
    # spell-check; this is the assertion.
    CURRENT="the mode the gate passes"
    OUT="${WORK}/mode-call.log"
    : >"$OUT"
    local call
    call="$(grep -n '^db_pin_leg' "${ROOT}/scripts/check.sh" | head -1 || true)"
    if [ -z "$call" ]; then
        bad "check.sh never calls db_pin_leg — the leg body is orphaned"
        return 0
    fi
    printf '%s\n' "$call" >"$OUT"
    case "$call" in
    *db_pin_leg) bad "check.sh calls db_pin_leg with NO mode — the leg would refuse with exit 2, and the fast tier would red on every laptop" ;;
    *) ok "the call passes an argument: ${call#*:}" ;;
    esac
    # The three words, and the `$MODE` they are derived from. A hard-coded
    # `loop` would bind `--fast` too; a hard-coded `fast` would give the whole
    # rung back.
    local missed=""
    for want in '"$MODE"' '--fast' 'fast' '--loop' 'loop' 'full'; do
        case "$call" in
        *"$want"*) ;;
        *) missed="${missed} ${want}" ;;
        esac
    done
    if [ -z "$missed" ]; then
        ok "the mode is derived from \"\$MODE\": --fast→fast, --loop→loop, anything else→full"
    else
        bad "the call line does not derive the mode from \$MODE — missing:${missed}"
    fi
    # THE LINE, RUN. `db_pin_leg` is shadowed inside each command substitution's
    # own subshell by a stub that prints what it was handed, so the real leg is
    # never invoked and nothing outside the substitution is touched. `""` is the
    # full gate AND is what `--bank` and `--pr` normalise to before this leg;
    # `--census` exits long before it and is driven here anyway, because a mode
    # this line has no branch for must still land on `full` rather than on the
    # empty string.
    local call_text="${call#*:}" pair mode_in want got
    for pair in "--fast=fast" "--loop=loop" "=full" "--census=full"; do
        mode_in="${pair%%=*}"
        want="${pair#*=}"
        got="$(
            MODE="$mode_in"
            db_pin_leg() { printf '%s' "${1:-<nothing>}"; }
            eval "$call_text" 2>&1
        )"
        if [ "$got" = "$want" ]; then
            ok "MODE='${mode_in}' → the leg is handed '${got}'"
        else
            bad "MODE='${mode_in}' should hand the leg '${want}' and hands it '${got}'"
        fi
    done
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
    # `^db_pin_leg` and not `^db_pin_leg$`: the call now carries its mode
    # as an argument, so the anchored-empty form would report the leg orphaned.
    call_line="$(grep -n '^db_pin_leg' "${ROOT}/scripts/check.sh" | head -1 | cut -d: -f1 || true)"
    # ANCHORED AT THE LINE START, and that is not cosmetic: the early exit is a
    # statement in column 1, and an unanchored pattern also matches any
    # line that MENTIONS the test — which now includes the db-pin call
    # itself, four lines below the leg banner. Unanchored, this case reported
    # the leg called below an early exit that was really the call line. The same
    # anchor `test_archaeology_loop.sh` already uses for the same landmark.
    fast_exit_line="$(grep -n '^if \[ "\$MODE" = "--fast" \]; then' "${ROOT}/scripts/check.sh" | head -1 | cut -d: -f1 || true)"
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
case_setup_adopts_the_derivation_over_an_unmarked_exported_stale_pin
case_setup_names_only_the_pin_when_nothing_is_exported
case_setup_leaves_a_pinned_line_alone
case_setup_keeps_a_pinned_line_through_the_environment_step
case_setup_and_the_leg_read_one_decision_table
case_setup_creates_after_the_name_is_settled
case_a_pinned_line_passes_silently
case_the_marker_carries_a_reason_and_still_passes
case_the_marker_must_be_directly_above_the_database_name_line
case_the_inline_form_is_refused
case_an_inline_comment_that_agrees_is_still_refused
case_any_inline_comment_is_refused_not_only_the_marker
case_the_new_form_reads_identically_for_every_reader
case_the_old_form_still_splits_the_readers
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
case_under_loop_an_absent_database_is_exit_2_naming_setup
case_under_full_the_same_refusal
case_under_loop_a_present_database_says_so
case_under_fast_existence_is_not_asked_and_says_so
case_an_unreachable_stack_under_loop_is_could_not_look
case_an_exported_database_name_is_the_one_asked_about
case_a_pinned_absent_name_names_the_pin_and_its_remedy
case_a_re_exported_name_after_sourcing_is_asked_about
case_a_child_process_with_a_new_name_is_asked_about_that_name
case_the_existence_line_names_its_source
case_the_mode_is_printed_on_every_run
case_a_missing_or_unknown_mode_is_exit_2
case_the_db_pin_leg_passes_its_mode

echo "test_db_pin: ${PASSED} passed · ${FAILED} failed · ${SKIPPED} skipped"
if [ "$SKIPPED" -gt 0 ]; then
    # Reprinted at the end, where a reader who scrolled past the case is
    # standing: a summary that says `0 failed` next to a skip nobody read is
    # the vacuous green this drive's header refuses everywhere else.
    echo "   the cases that could not be POSED, and why:${SKIP_REASONS}" >&2
    echo "   (all three need the compose Postgres; \`docker compose up -d db\` poses them.)" >&2
fi
if [ "$FAILED" -gt 0 ]; then
    echo "!! the db-pin leg no longer refuses a stale DATABASE_NAME pin — or no longer" >&2
    echo "   passes a deliberate one. Both halves are load-bearing: a leg that stops" >&2
    echo "   refusing puts a checkout back to running two databases in silence, and a" >&2
    echo "   leg that stops passing a \`# pinned\` line is noise every checkout learns" >&2
    echo "   to scroll past, which is the state the earlier note was already in." >&2
    exit 1
fi
exit 0
