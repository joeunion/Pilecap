#!/usr/bin/env bash
# THE gate.
#   ./scripts/check.sh          full: --loop + supply chain (first of the full
#                               legs — the only one that leaves this machine) +
#                               TWO pytest passes under one seed + canary
#                               self-test + full house rules; records a verdict
#                               keyed on the tree hash
#   ./scripts/check.sh --fast   the static legs — what pre-commit runs. No
#                               database, no network, no suite: seconds, not
#                               minutes.
#   ./scripts/check.sh --loop   --fast + check --deploy + detect-secrets over
#                               THE ACTIVE RUNG'S CHANGED FILES ONLY (the
#                               full-tree scan stays at push) + ONE pytest pass,
#                               `-n auto`, fresh seed, TIERED (see below) — the
#                               per-rung gate. The pytest leg is nearly all of it.
#
# HOW LONG IT TAKES IS PRINTED, NOT WRITTEN DOWN HERE. Every leg prints its own
# wall time as it finishes and the mode prints its total, and that is the only
# number about this file that cannot go stale. A hand-written header number is a
# claim about a tree that changes daily and reliably drifts as the suite grows
# underneath the sentence nobody re-measures — this file used to carry one,
# true when ADR gate-1 wrote it and wrong by the time the suite had grown past
# 2600 tests; the printed line is a measurement of the tree in front of you.
# Measured once on a ten-core Apple laptop, quiet
# machine, 2613 tests: the untiered `-n auto` suite is ~80s wall and ~270s of CPU
# across ten workers, of which ~58s of CPU — ten setup entries of 5.5-6.2s, one
# per worker — is the per-worker test database being created and migrated before
# a single assertion runs. Prefer the printed line over any number here.
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
# below run `-n auto` — one worker per core, each with its OWN test database
# (pytest-django suffixes this checkout's derived name: `test_<DATABASE_NAME>
# _gw0..gwN`, so worker isolation nests inside the checkout isolation from
# `scripts/db.sh` and two checkouts still never meet). pytest-randomly shuffles
# collection and prints the seed it used at the top of every run; a red order
# replays exactly with `--randomly-seed=<the printed seed>`.
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
# gates contend for every core (each is `pytest -n auto` twice, plus a real
# Meili, MinIO and Temporal), and the measurement is 607s with two RED tests
# contended against 99s green quiet on the same tree. --fast and --loop take NO
# lease and never wait on one. Its scope, its trust class and its declared limit
# — one machine, never cross-machine CI — are `scripts/gate_lease.sh`'s header.
#
# THE CALLER IS RECORDED: a full run's ledger and run-log lines carry
# `caller=<kind>` from `DJB_GATE_CALLER` — `push-wall` (the pre-push hook sets
# it), `quality-rung`, `pm-bank`, or `unstated` when nobody said. Measurement
# only: no run is refused for its caller. See `scripts/gate_ledger.sh`.
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
case "$MODE" in
"" | --fast | --loop) ;;
*)
    # Not a usage nit: a mistyped flag falling through to a silently different
    # run is enforcement misfiring, and that is an exit 2.
    echo "!! unknown argument '$MODE': check.sh takes nothing, --fast, or --loop" >&2
    exit 2
    ;;
esac
shift || true
if [ "$#" -gt 0 ]; then
    echo "!! unexpected extra arguments: $*" >&2
    exit 2
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
        *) head -n 1 "$f" 2>/dev/null | grep -Eq '^#!.*sh$|^#!.*sh[[:space:]]' && printf '%s\n' "$f" ;;
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

# In run order. supply-chain moved ahead of pytest-x2; see the ordering note at
# that leg. `full-house-rules` was missing for a while: the leg ran on every
# full gate and the ledger line never said so, so every recorded verdict
# under-reported what green had meant.
FULL_LEGS=ruff,mypy,import-linter,djb-checks,house-rules,migrations,goalpost-census,db-pin,deploy-check,supply-chain,temporal-census,partition,pytest-x2,own-tree-census,selftest,full-house-rules
MEASURED_START=""
T_MODE_START=$(date +%s)

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
    # THE ORDER OF THE TWO GUARDS IS LOAD-BEARING. The machine-wide lease is
    # taken FIRST and the per-checkout lock second, because the lease is the one
    # that WAITS: a gate that took the checkout lock and then queued would make
    # every `--fast`/`--loop` in its own checkout refuse for the whole wait,
    # which is the friction the lease exists to remove, one checkout over.
    #
    # The EXIT trap is installed IMMEDIATELY AFTER the lease is taken and covers
    # both releases — `gate_lock_release` is a no-op while `GATE_LOCK` is empty
    # — so no line between here and the first leg can exit holding either.
    set +e
    gate_lease_acquire
    LEASE_RC=$?
    set -e
    if [ "$LEASE_RC" != "0" ]; then
        # Could-not-look: this run judged nothing. Never a red tree.
        exit 2
    fi
    trap 'RC=$?; trap "" PIPE; gate_lock_release; gate_lease_release; gate_run_finish "$RC" || true' EXIT
    gate_lock_acquire
    trap 'gate_run_killed' TERM INT HUP
    # Measured BEFORE the first leg reads a byte, so the key names the content
    # the gate actually saw. `|| true`: failing to measure costs a verdict,
    # never a gate run.
    MEASURED_START=$(gate_measured_tree || true)
    gate_run_start "${MEASURED_START:-unknown-tree}"
    gate_run_announce
else
    gate_lock_refuse_if_held
fi

LEG_T0=$(date +%s)
leg() {
    # Announce a leg and print the previous leg's wall time. Timing is printed
    # per leg so a slow gate names its slow leg instead of being argued about.
    local now
    now=$(date +%s)
    if [ -n "${LEG_NAME:-}" ]; then
        echo "  (${LEG_NAME}: $((now - LEG_T0))s)"
    fi
    LEG_NAME=$1
    LEG_T0=$now
    gate_leg "$1" "$2"
}
leg_done() {
    local now
    now=$(date +%s)
    echo "  (${LEG_NAME}: $((now - LEG_T0))s)"
    LEG_NAME=""
}

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
GATE_SKIP_DJANGO_LEG=1 uv run python -m quality.gate --diff HEAD
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
set +e
python3 scripts/goalpost_scan.py --census
CENSUS_RC=$?
set -e
if [ "$CENSUS_RC" != "0" ]; then
    echo "!! the instrument census and the tree disagree." >&2
    echo "   Every executable git knows about outside apps/, config/, .venv/ and .git/" >&2
    echo "   owes a row in docs/product/instruments.md answering the three honesty" >&2
    echo "   questions with a file:line each. A new instrument that ships uncensused is" >&2
    echo "   a doc that went stale with nobody able to see it (ADR gate-3)." >&2
    exit 2
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
set +e
db_pin_leg
DB_PIN_RC=$?
set -e
if [ "$DB_PIN_RC" = "2" ]; then
    echo "!! the db-pin leg COULD NOT LOOK — see above. An unread .env is not an" >&2
    echo "   absent one: nothing was compared, so this is neither a finding nor a pass." >&2
    exit 2
elif [ "$DB_PIN_RC" != "0" ]; then
    exit "$DB_PIN_RC"
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
    set +e
    secrets_scan_loop
    SECRETS_RC=$?
    set -e
    if [ "$SECRETS_RC" = "2" ]; then
        echo "!! the secret scan COULD NOT DERIVE the active rung's changed files — see above." >&2
        echo "   An underived set is not an empty set: nothing was judged, so this is" >&2
        echo "   neither a finding nor a pass." >&2
        exit 2
    elif [ "$SECRETS_RC" != "0" ]; then
        exit "$SECRETS_RC"
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
    leg pytest "pytest (ONE pass, -n auto, a FRESH random seed — the fast tier plus the active rung's own app, or the WHOLE suite when the active rung changed shared test infrastructure; the full gate at push runs two whole-suite passes under one seed, which is where idempotency is proven)"
    set +e
    loop_tier_own_apps
    TIER_RC=$?
    set -e
    if [ "$TIER_RC" != "0" ]; then
        echo "!! the pytest tier COULD NOT DERIVE the active rung's changed files — see above." >&2
        echo "   An underived set is not an empty set: choosing a tier on the strength" >&2
        echo "   of a derivation that did not answer would run LESS than the leg claims," >&2
        echo "   silently." >&2
        exit 2
    fi
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
    set +e
    if [ "$LOOP_TIER_MODE" = "full" ]; then
        ./scripts/test.sh -n auto
    else
        TIER_ARGS=(--djb-tier=fast)
        for TIER_APP in $LOOP_TIER_OWN_APPS; do
            TIER_ARGS+=("--djb-own-app=$TIER_APP")
        done
        ./scripts/test.sh -n auto "${TIER_ARGS[@]}"
    fi
    PYTEST_RC=$?
    set -e
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

leg pytest-x2 "pytest (twice, -n auto, both passes under ONE seed, nothing in between — the second run proves the first left nothing behind)"

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
# and `-n auto` is the same on both, which pins the worker assignment too. What
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
        summary=$(awk '/^(FAILED|ERROR) /{print "     " $0}' "$out" | head -20)
    fi

    echo "" >&2
    if [ -n "$harness" ]; then
        echo "!! PASS 2 DID NOT COME UP — no inference about idempotency is possible." >&2
        echo "   This leg saw: ${harness%; }." >&2
        echo "   A harness that does not come up produces failures of its own, so nothing" >&2
        echo "   here says anything about what pass 1 left behind. Fix the harness, then" >&2
        echo "   re-run: ./scripts/test.sh -n auto --randomly-seed=$seed" >&2
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

set +e
# UNQUOTED ON PURPOSE: `$PARTITION_TARGETS` is a path LIST that has to word-split
# into pytest arguments, and it is empty when the whole suite runs.
# shellcheck disable=SC2086
./scripts/test.sh -n auto --randomly-seed="$PYTEST_SEED" $PARTITION_TARGETS
TEST_RC=$?
set -e
if [ "$TEST_RC" != "0" ]; then
    echo "!! pass 1 is red — the suite fails on its own, before idempotency is in question." >&2
    exit 1
fi
echo "  pytest pass 1: green (seed $PYTEST_SEED)"

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
./scripts/test.sh -n auto --randomly-seed="$PYTEST_SEED" $PARTITION_TARGETS >"$PASS2_OUT" 2>&1
TEST_RC=$?
set -e
cat "$PASS2_OUT"
if [ "$TEST_RC" != "0" ]; then
    pytest_x2_verdict "$PASS2_OUT" "$PYTEST_SEED"
    rm -f "$PASS2_OUT"
    exit 1
fi
rm -f "$PASS2_OUT"
echo "  pytest pass 2: green (seed $PYTEST_SEED)"

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
if [ "$PARTITION_MODE" != "skip" ]; then
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
else
    # THE ASSERTION IS THE INSTRUMENT'S, NOT THIS LEG'S. `--assert-none` exits 1
    # when anything is in scope and 2 when it could not look, so this leg reads a
    # STATUS rather than grepping a summary line it does not own — which is the
    # coupling that rots the day somebody rewords a count.
    set +e
    ./scripts/sweep.sh --class schedule --only "$DATABASE_NAME" --assert-none
    SCHED_RC=$?
    set -e
    if [ "$SCHED_RC" = "2" ]; then
        echo "!! THE SCHEDULE CENSUS COULD NOT BE TAKEN — see above. Nothing was asserted." >&2
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
if [ -z "$MEASURED_START" ] || [ -z "$MEASURED_END" ]; then
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
