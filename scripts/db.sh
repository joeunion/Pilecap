#!/usr/bin/env bash
# Per-CHECKOUT database naming and helpers.
#
#   source scripts/db.sh          # exports DATABASE_NAME
#   db_name · db_create · db_drop · db_exists
#   db_template_refresh           # publish the migrated template
#
# Every checkout gets its own database on the one compose Postgres, so a tree's
# gate measures its own tree and nothing else.
#
# The name follows the CHECKOUT, not the branch. Two clones of `main` in
# two directories used to derive djb_main and share it — with the owner's live
# development database — and exporting DATABASE_NAME first was no escape,
# because this file set it unconditionally. Both halves are fixed here:
#
#   1. A DATABASE_NAME already in the environment WINS, and nothing is derived.
#      That is the escape: `DATABASE_NAME=djb_custom ./scripts/test.sh`, or an
#      export before sourcing, reaches every consumer through this one variable.
#   2. Otherwise the name is djb_<branch>_<hash>, where <hash> is the first 8
#      hex digits of the SHA-256 of the checkout's absolute top-level path
#      (git's, so it is the same however you cd into the tree). The branch keeps
#      the name readable at a glance; the path hash is what makes it this
#      checkout's and nobody else's.
#
# Identifier arithmetic — Postgres allows 63 bytes, and it TRUNCATES rather
# than refusing, so two names that differ only past byte 63 become one database.
# The budget now has a fourth term: djb_(4) + branch(<=38) + _(1) + hash(8) =
# 51, Django's `test_` prefix takes that to 56, and pytest-xdist's per-worker
# suffix (`_gw0`..`_gw999`, up to 6) takes it to 62 — one byte spare.
#
# The branch cap is 38 and not 40 because of that last term (ADR gate-1 landed
# the workers): at 40 the test name reached 58 and `_gw100` truncated to
# `_gw10`, so worker 100 and worker 10 would share one database and produce
# failures nobody could reproduce. Two bytes bought the whole `_gwN` range.
#
# Two consequences, both accepted and stated: a checkout MOVED on disk derives
# a new name and leaves its old database behind, and names derived before this
# scheme existed (djb_main, djb_worktree_agent_*) are not the names derived
# now. Nothing here drops or renames a database to catch up — another
# checkout's data is not this script's to touch. A checkout that wants to keep
# an old-scheme database keeps it by pre-setting DATABASE_NAME, which is rule 1
# above and now works.
#
# This file is meant to be sourced. It sets no shell options of its own so it
# cannot change the caller's behaviour.

# First N hex digits of the SHA-256 of $1 (N defaults to 8), with fallbacks down
# to a POSIX one, because this must not need a tool a fresh laptop might not
# have. The length argument arrived with the template key, which wants 16
# — a machine-global name where a collision would hand one checkout another
# migration set's schema, which 8 hex digits is too short to promise.
db_path_hash() {
    local input="$1" want="${2:-8}" digest=""
    if command -v shasum >/dev/null 2>&1; then
        digest="$(printf '%s' "$input" | shasum -a 256 | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
        digest="$(printf '%s' "$input" | sha256sum | awk '{print $1}')"
    elif command -v openssl >/dev/null 2>&1; then
        # `SHA2-256(stdin)= <hex>` — the digest is the last field.
        digest="$(printf '%s' "$input" | openssl dgst -sha256 | awk '{print $NF}')"
    else
        # cksum is in POSIX and separates two paths, which is the whole job.
        digest="$(printf '%08x' "$(printf '%s' "$input" | cksum | awk '{print $1}')")"
    fi
    printf "%.${want}s" "$digest"
}

db_name() {
    local branch sanitised root
    branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true)"
    if [ -z "$branch" ] || [ "$branch" = "HEAD" ]; then
        branch="main"
    fi
    sanitised="$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_')"
    # 38, not 40: the header's arithmetic — `test_` plus xdist's `_gw999`.
    sanitised="${sanitised:0:38}"
    if [ -z "$sanitised" ]; then
        sanitised="main"
    fi
    # The checkout's own top level: a linked worktree reports itself, not the
    # repository it is linked to, so a worktree and its parent differ here even
    # on the same branch. Outside a repository there is no top level, and then
    # the working directory is the checkout.
    root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    if [ -z "$root" ]; then
        root="$PWD"
    fi
    printf 'djb_%s_%s' "$sanitised" "$(db_path_hash "$root")"
}

# Rule 1: a name already in the environment wins. `:-` and not `-`, so an empty
# DATABASE_NAME derives rather than exporting nothing. Sourcing twice is
# therefore stable — the second source honours the first one's export — and so
# is a script that sources this file and then calls another one that does too.
DATABASE_NAME="${DATABASE_NAME:-$(db_name)}"
export DATABASE_NAME

# --- Rule 1 stops being SILENT about itself ---------------------------
#
# THE SPLIT-BRAIN. `.env` is read by django-environ at settings import, so a
# bare `manage.py` resolves whatever `.env` pins. This file is sourced by the
# scripts, and it derives. When those two disagree, one checkout has TWO
# databases and nothing says so: once, the main checkout's `.env`
# pinned the old-scheme flat `djb_main` (the owner's live development database)
# while every script exported `djb_main_700aaf41`, which had never been
# migrated — so `serve.sh` 500ed on any table read while `manage.py` worked
# fine, and a PM debugging it migrated and minted tokens into the OWNER'S
# database. Every part of that was legal. None of it was visible.
#
# SO THE RULE IS UNCHANGED AND THE SILENCE IS NOT. A pin still wins — the
# owner may pin deliberately, and refusing here would fight rule 1's recorded
# semantics (and break every `DATABASE_NAME=x ./scripts/test.sh` in the
# repository). What changes is that a disagreement now says so, once, on every
# source. A pin stays legal; a STALE pin stops being invisible.
#
# AND THAT NOTE IS ONLY THE SECONDARY HALF. Saying so was not enough:
# a later census found the main checkout's pin still stale a day after this
# note shipped, and 63 stale worktree pins beside it. The primary enforcement
# is now `db_pin_leg` below — the gate's `db-pin` leg, in `--fast`, which a
# commit has to answer. The note stays as a heads-up for a script run outside
# the gate and points at the leg rather than restating its fixes.
#
# ON STDERR, and never on stdout: this file is sourced by scripts whose stdout
# is data — `gen_client.sh` writes a schema, `backup.sh` writes a dump through
# a redirect, `db_sweep.sh`'s census is read by eye and by grep. A notice on
# stdout would corrupt the first and be mistaken for a finding in the last.
#
# SILENT WHEN THEY AGREE, which is the normal case and every gate run: this
# prints only on an actual disagreement, so it can never become noise a reader
# learns to skip.
#
# WHAT IT DOES NOT SEE, declared: it compares against `.env` in the CHECKOUT
# ROOT only — a `DJANGO_SETTINGS_MODULE` pointing somewhere with its own
# environment file, or a value exported by a shell profile, is outside it. And
# it reports a DISAGREEMENT, never a wrongness: which of the two names is the
# right one is a judgement about intent that no script can make.
db_env_file_pin() {
    # The last `DATABASE_NAME=` line in the checkout's .env, unquoted — the
    # same "last wins" reading `backup.sh::env_value` uses, and the same one
    # django-environ ends up with. Prints nothing when there is no pin.
    local root line
    root="$(db_checkout_root)"
    [ -f "${root}/.env" ] || return 0
    line="$(grep -E '^DATABASE_NAME=' "${root}/.env" 2>/dev/null | tail -1 || true)"
    [ -n "$line" ] || return 0
    line="${line#DATABASE_NAME=}"
    # Strip a trailing marker comment before the value is compared, so
    # `DATABASE_NAME=djb_x  # pinned` compares as `djb_x` (setup.sh reads the
    # marker itself; here it is only noise on the value).
    line="${line%%#*}"
    line="${line%"${line##*[![:space:]]}"}"
    # Strip a surrounding quote pair, the way django-environ does, so a
    # hand-written `DATABASE_NAME="djb_x"` compares as `djb_x`. The escapes are
    # load-bearing: `'*'` as a case pattern is the literal three characters
    # quote-star-quote, so the branches below matched nothing but a value that
    # WAS a single `*` until this was written properly (found while building
    # the db-pin leg, which would have read a quoted pin as a disagreement).
    case "$line" in
    \'*\') line="${line#\'}"; line="${line%\'}" ;;
    \"*\") line="${line#\"}"; line="${line%\"}" ;;
    esac
    printf '%s' "$line"
}

# The checkout root, or $PWD outside a repository. One definition, because the
# pin, the marker and the derivation must all be read out of the SAME tree.
db_checkout_root() {
    git rev-parse --show-toplevel 2>/dev/null || printf '%s' "$PWD"
}

# Does the .env DATABASE_NAME line carry the `# pinned` marker? This is the
# same one-grep escape `setup.sh` reads before deciding whether to rewrite the
# line (scripts/setup.sh's pin-reconcile block), and it means the same thing in
# both places: a human put this name here on purpose.
db_pin_marked() {
    grep -qE '^DATABASE_NAME=.*#[[:space:]]*pinned' "$(db_checkout_root)/.env" 2>/dev/null
}

# --- THE LEG ----------------------------------------------
#
# THE NOTE BELOW WAS SILENCE WITH EXTRA STEPS. `db_announce_pin_disagreement`
# has printed this disagreement on stderr on every single script run for a
# long stretch, and a census found the MAIN CHECKOUT'S pin still stale a
# full day later — with 63 stale worktree pins beside it. A note nobody has to
# answer is a note nobody answers; this class had already written to the
# owner's real database once before the note existed, and the note did not stop
# the second checkout from drifting.
#
# So the disagreement gets an EXIT STATUS. This function is the body of the
# `db-pin` leg in `scripts/check.sh` — a `--fast` leg, which means pre-commit
# runs it, and `--loop` and the full gate inherit it. A stale pin now stops a
# commit instead of scrolling past one.
#
# THE PIN STAYS LEGAL. Rule 1 above is untouched: a name in the environment
# still wins, and a `# pinned` .env line still keeps its name. What the marker
# buys now is SILENCE — the leg passes without a word, because a checkout that
# said it meant it has answered the question. A pin with no marker has not.
#
#   exit 0  no .env · no DATABASE_NAME line · the pin agrees · `# pinned`
#   exit 1  a pin disagreeing with the derivation, unmarked
#   exit 2  could not look — an .env in the tree that cannot be read
#
# WHAT IT DOES NOT SEE, unchanged from the note it replaces and declared here
# because a leg is read as broader than a note: it compares against `.env` in
# the CHECKOUT ROOT only. A `DJANGO_SETTINGS_MODULE` pointing at somewhere with
# its own environment file, and a `DATABASE_NAME` exported by a shell profile,
# are both outside it — and both of those override .env for a bare `manage.py`
# too, so a green leg means "the file agrees", never "the process will".
db_pin_leg() {
    local root pin derived
    root="$(db_checkout_root)"
    if [ ! -f "${root}/.env" ]; then
        # No file, no second opinion: the derivation is the only truth here.
        echo "  no .env in this checkout — the derivation is the only name ($(db_name))"
        return 0
    fi
    if [ ! -r "${root}/.env" ]; then
        echo "!! ${root}/.env exists and cannot be read — the pin could not be compared." >&2
        return 2
    fi
    pin="$(db_env_file_pin)"
    if [ -z "$pin" ]; then
        echo "  .env pins no DATABASE_NAME — the derivation is the only name ($(db_name))"
        return 0
    fi
    derived="$(db_name)"
    if [ "$pin" = "$derived" ]; then
        echo "  .env and the derivation agree: ${derived}"
        return 0
    fi
    if db_pin_marked; then
        # Declared deliberate. Silent by design — see the block above.
        return 0
    fi
    echo "!! DATABASE_NAME: this checkout's .env and its derivation DISAGREE." >&2
    echo "     .env pins:  ${pin}" >&2
    echo "     derivation: ${derived}" >&2
    echo "   A bare \`manage.py\` resolves the pin; every script here sources scripts/db.sh" >&2
    echo "   and resolves the derivation. One checkout, TWO databases — which is how a" >&2
    echo "   migrate and a token mint landed in the owner's live database once already," >&2
    echo "   with every step of it legal and none of it visible." >&2
    echo "   Two fixes, and this leg does not choose between them:" >&2
    echo "     * KEEP THE PIN — add \`# pinned\` to that line in ${root}/.env." >&2
    echo "       The name stays, setup.sh stops rewriting it, and this leg goes silent." >&2
    echo "     * RECONCILE — re-run ./scripts/setup.sh, which rewrites the line to the" >&2
    echo "       derivation and prepares that database." >&2
    return 1
}

# The note that used to be the whole enforcement. It stays, DEMOTED: the leg
# above is what has to be answered, and a script running outside the gate still
# deserves a one-line heads-up rather than a surprise. It points at the leg
# instead of restating the fixes, so there is exactly one place that spells
# them out and it is the one with an exit status.
db_announce_pin_disagreement() {
    local pin derived
    pin="$(db_env_file_pin)"
    [ -n "$pin" ] || return 0
    derived="$(db_name)"
    [ "$pin" != "$derived" ] || return 0
    if db_pin_marked; then
        printf 'note: DATABASE_NAME pinned to %s by .env (# pinned); derivation says %s\n' \
            "$pin" "$derived" >&2
    else
        printf 'note: DATABASE_NAME pinned to %s by .env; derivation says %s — the gate'"'"'s db-pin leg refuses this (./scripts/check.sh --fast says what to do)\n' \
            "$pin" "$derived" >&2
    fi
}
db_announce_pin_disagreement

POSTGRES_USER="${POSTGRES_USER:-djb}"
export POSTGRES_USER

# Run psql inside the compose container. There is no psql on the host.
db_psql() {
    docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres "$@"
}

# --- Names are not strings (P3-SEC-1, LOW-5) ----------------------------------
#
# A database name reaching this file is OPERATOR input — `DATABASE_NAME` out of
# the environment, or an argument — and it used to be pasted into SQL with
# `"${name}"`. A name carrying a quote therefore composed statements: SEC-1
# proved it, and SEC-R3 proved it again by making `db_exists` run a `CREATE
# TABLE` that landed in the server. Nothing here is a privilege boundary — the
# caller already has the psql socket — but a tool whose refusals are described
# in its own header as load-bearing must refuse by CONSTRUCTION, not by luck:
# both of `db_sweep.sh`'s survived only because `psql -c` wraps a multi-statement
# string in one transaction and `DROP DATABASE` will not run in one.
#
# Two layers, and each is sufficient on its own:
#
#   1. `db_valid_name` — a name is `[A-Za-z0-9_]{1,63}` or it is refused before
#      any SQL is built. Every name this repository derives is already that
#      (`db_name` above, Django's `test_` prefix, xdist's `_gwN`), so the gate
#      costs a legitimate caller nothing and turns an injection attempt into a
#      sentence rather than a puzzling Postgres error.
#   2. psql VARIABLES — `:'x'` for a literal, `:"x"` for an identifier. psql
#      does the quoting, so a value is a value however it is spelled. The
#      statement arrives on stdin because `psql -c` sends its argument to the
#      server unparsed and interpolates nothing; `db_query` is that plumbing.
#
# THE SAME CLASS, IN PYTHON:
# `quality/hotpaths.py::guarded_identifier` is this function's twin, byte for
# byte — `[A-Za-z0-9_]`, at most 63 bytes — and `quality/hotpath_probe.py`'s
# `CREATE DATABASE` composes its identifier with `psycopg.sql.Identifier`, which
# is layer 2 on that side. It was found protected by the SAME accident this
# header describes (a multi-statement DDL string cannot run in psycopg's
# implicit transaction either), which is why it is now guarded rather than
# lucky. Two languages, one rule: change it here and there, and nowhere else.
db_valid_name() {
    local name="${1:-}"
    [ -n "$name" ] || return 1
    [ "${#name}" -le 63 ] || return 1
    # In a subshell with the C locale: a glob range under a UTF-8 collation can
    # match letters nobody typed, and this file may not change the caller's env.
    (
        LC_ALL=C
        case "$name" in
        *[!A-Za-z0-9_]*) exit 1 ;;
        esac
        exit 0
    )
}

db_refuse_name() {
    printf '!! refusing the database name %s\n' "$(printf '%q' "${1:-}")" >&2
    printf '   a database name here is [A-Za-z0-9_], at most 63 bytes — the shape this\n' >&2
    printf '   repository derives. Nothing legitimate is outside it (scripts/db.sh).\n' >&2
}

# Send SQL on stdin so psql interpolates the `:'x'` / `:"x"` variables in it.
db_query() {
    local sql="$1"
    shift
    printf '%s' "$sql" | db_psql "$@"
}

db_exists() {
    local name="${1:-$DATABASE_NAME}"
    local found
    if ! db_valid_name "$name"; then
        db_refuse_name "$name"
        return 2
    fi
    found="$(db_query "SELECT 1 FROM pg_database WHERE datname = :'name'" \
        -v name="$name" -tA 2>/dev/null || true)"
    [ "$found" = "1" ]
}

db_create() {
    local name="${1:-$DATABASE_NAME}"
    if ! db_valid_name "$name"; then
        db_refuse_name "$name"
        return 2
    fi
    if db_exists "$name"; then
        echo "database ${name} already exists"
        return 0
    fi
    # THE ONE NAME THAT GETS THE TEMPLATE — see THE TEMPLATE DATABASE below for
    # why it is one name and not all of them. Every other name falls through to
    # the plain CREATE this function has always done, byte for byte.
    if db_template_wanted "$name"; then
        db_create_the_checkouts_own "$name"
        return $?
    fi
    db_query 'CREATE DATABASE :"name" OWNER :"owner"' \
        -v name="$name" -v owner="$POSTGRES_USER" >/dev/null
    echo "created database ${name}"
}

db_drop() {
    local name="${1:-$DATABASE_NAME}"
    if ! db_valid_name "$name"; then
        db_refuse_name "$name"
        return 2
    fi
    if ! db_exists "$name"; then
        echo "database ${name} does not exist"
        return 0
    fi
    db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$name" >/dev/null
    echo "dropped database ${name}"
    # Django's test database for this checkout, if it was left behind.
    if db_exists "test_${name}"; then
        db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="test_${name}" >/dev/null
        echo "dropped database test_${name}"
    fi
}

# =============================================================================
# THE TEMPLATE DATABASE
# =============================================================================
#
# WHAT IT IS FOR. Every worktree on this machine used to pay the whole migration
# chain to get an empty schema — measured at 17.00s in this checkout's own
# `rung_start.sh` run, and paid again by every one of the nine worktrees a wave
# spawns. The schema is IDENTICAL in all of them, because it is a pure function
# of the migration set. So it is built once, into a machine-global template, and
# every checkout after that gets its database with
#
#     CREATE DATABASE <mine> TEMPLATE djb_tmpl_<key>
#
# which is a file copy: seconds, no Django, no Python.
#
# THE KEY IS DERIVED AND NEVER TYPED. `djb_tmpl_<16 hex>` where the hex is a
# digest of the MIGRATION FILES THEMSELVES — this checkout's `apps/*/migrations/`
# and the third-party ones in its own `.venv` — so it moves when a migration is
# added, changed or removed and for nothing else. A hand-bumped version number
# is the drift class the whole rules engine exists against: somebody forgets to
# bump it and every checkout on the machine quietly gets last week's schema.
# `scripts/tests/test_db_template.sh` drives both directions of that iff.
#
# THE KEY IS THE SAME IN EVERY CHECKOUT, and this is the one place in this file
# where that is the goal. `db_name` above deliberately does the opposite: the
# name follows the CHECKOUT so two clones never share a database. The
# template is the other kind of object: it is shared ON PURPOSE, it is read-only
# by construction, and a key that varied by path would give every worktree its
# own template and save nobody anything. The digest is taken over paths
# normalised to `apps/...` and `site-packages/...`, which is what makes two
# checkouts at different absolute paths agree.
#
# ONE NAME GETS IT, AND ONLY ONE. `db_create` uses the template ONLY for the
# database this checkout DERIVES for itself — `name = db_name`. Every other
# caller is creating a database it is about to fill itself and a populated one
# would break it outright: `scripts/restore_drill.sh` pg_restores a dump into
# what `db_create` hands back (`--exit-on-error` over existing relations), and
# `scripts/perf.sh` creates its `_perf` world. Their output does not change
# either — the `path=` line below is printed only on the one name. That is also
# why the rule is DERIVED (a name equal to `db_name`) rather than a list of
# names to skip: a list is a thing that goes stale when a seventh caller arrives.
#
# A MISS IS LOUD AND IS NOT AN ERROR. No template for this migration set means a
# plain empty database and the caller's `migrate` running the whole chain —
# exactly what happened before this block existed. It says so, names the one
# command that publishes the template, and exits 0. Nothing here ever refuses to
# create a database because a template was missing.
#
# CONCURRENCY, DRIVEN RATHER THAN ARGUED. Postgres refuses
# `CREATE DATABASE ... TEMPLATE t` while any session is connected to `t`:
#
#     ERROR:  source database "djb_probe_open" is being accessed by other users
#     DETAIL:  There is 1 other session using the database.
#
# So a published template ALLOWS NO CONNECTIONS (`ALTER DATABASE ...
# ALLOW_CONNECTIONS false`) — the same construction `template0` uses. With no
# session able to exist, the refusal has nothing to count: six concurrent clones
# of one no-connections template were driven and all six succeeded
# with identical contents (`scripts/tests/test_db_template.sh::case_concurrent_
# clones_of_one_template_all_succeed_uncorrupted`). `db_clone_database` still
# retries that exact refusal and still falls back loudly, because the template
# can also be dropped or superseded between the existence check and the clone,
# and a mechanism whose safety rests on one ALTER having been run is a mechanism
# with a single point of silence.
#
# PUBLICATION IS ATOMIC, so a half-migrated template cannot be observed. The
# refresh migrates a uniquely named SCRATCH database and then publishes it with
# one `CREATE DATABASE djb_tmpl_<key> TEMPLATE <scratch>`. Two checkouts
# refreshing at once each build their own scratch; the first to publish wins and
# the second is told so and uses the winner's. The published name only ever
# comes into existence fully migrated.
#
# WHAT THIS DOES NOT SEE, declared:
#
#   1. The key digests MIGRATION FILES, not the schema. `INSTALLED_APPS`, the
#      settings module, and a `RunPython` whose behaviour depends on something
#      outside its own file are all outside it. The net is unchanged and it is
#      the caller's: every consumer runs `migrate` after `db_create` and
#      `rung_start.sh` then runs `migrate --check`, so a template that is behind
#      is caught and topped up rather than trusted.
#   2. It cannot notice a template that is AHEAD — a schema carrying a migration
#      this tree no longer has. The key moves when a migration file is removed,
#      so the only way in is two different trees whose migration files digest
#      the same, which is what the 16 hex digits are for.
#   3. `db_template_refresh` PRUNES the superseded templates it can see. On a
#      machine where two checkouts on different branches both refresh, they will
#      take turns dropping each other's template and both will fall back loudly
#      until one stops. That is the deliberate trade against an unbounded
#      population of machine-global databases nothing sweeps, and the refresh is
#      the merge path's — which runs on one branch.
#   4. A checkout whose `DATABASE_NAME` is PINNED (rule 1 above) never takes the
#      template path, because the pin is not `db_name`. A pinned checkout keeps
#      exactly the behaviour it had.

# The clock. Prefixed and lazy: this file is sourced by every script here and
# must cost nothing at source time, and `now_ms`/`CLOCK` are names its callers
# already own (`scripts/rung_start.sh:216`) — redefining those from underneath a
# caller is precisely what this file's header promises not to do.
db_now_ms() {
    if [ -z "${DB_CLOCK:-}" ]; then
        if [ -n "${EPOCHREALTIME:-}" ]; then
            DB_CLOCK=bash5
        elif case "$(date +%s%3N 2>/dev/null || echo x)" in '' | *[!0-9]*) false ;; *) true ;; esac; then
            DB_CLOCK=gnudate
        elif command -v python3 >/dev/null 2>&1; then
            DB_CLOCK=python3
        else
            DB_CLOCK=seconds
        fi
    fi
    case "$DB_CLOCK" in
    bash5)
        local us=${EPOCHREALTIME/./}
        printf '%s' "${us%???}"
        ;;
    gnudate) date +%s%3N ;;
    python3) python3 -c 'import time; print(int(time.time()*1000))' ;;
    *) printf '%s000' "$(date +%s)" ;;
    esac
}

db_elapsed_since() {
    awk -v ms="$(($(db_now_ms) - $1))" 'BEGIN { printf "%.2fs", ms / 1000 }'
}

# The digest tool, one ladder, named so both the per-file pass and the final
# string pass can ask for it. `db_path_hash`'s `cksum` last resort is NOT
# acceptable here — 32 bits over a machine-global schema key is a collision
# waiting to hand somebody the wrong migration set — so no tool is a REFUSAL
# and the refusal lands on the loud fallback path, which is correct and slow.
db_digest_tool() {
    if command -v shasum >/dev/null 2>&1; then
        printf 'shasum'
    elif command -v sha256sum >/dev/null 2>&1; then
        printf 'sha256sum'
    else
        return 1
    fi
}

db_digest_files_0() {
    case "$(db_digest_tool)" in
    shasum) xargs -0 shasum -a 256 ;;
    sha256sum) xargs -0 sha256sum ;;
    *) return 1 ;;
    esac
}

# `<digest>  <normalised path>` for every migration file this checkout would
# load, sorted. Prints nothing and returns 1 when there is no digest tool or no
# migration file at all — an empty digest would be one key every empty tree
# shared, which is the one collision that could actually happen.
db_migration_listing() {
    local root="${1:-$(db_checkout_root)}" tmp
    db_digest_tool >/dev/null || return 1
    tmp="$(mktemp "${TMPDIR:-/tmp}/djb-migset.XXXXXX")" || return 1
    {
        [ -d "${root}/apps" ] && find "${root}/apps" -type f -path '*/migrations/*.py' -print0
        [ -d "${root}/.venv" ] && find "${root}/.venv" -type f -path '*/migrations/*.py' -print0
        true
    } >"$tmp" 2>/dev/null
    if [ ! -s "$tmp" ]; then
        rm -f "$tmp"
        return 1
    fi
    # The two normalisations that make the key checkout-independent, and they
    # are anchored on the two spaces the digest tools put between hash and path
    # so nothing in a directory name can be mistaken for the separator. The
    # checkout root is never interpolated into the expression — a root carrying
    # a `#` would otherwise rewrite the script.
    db_digest_files_0 <"$tmp" |
        sed -e 's#  .*/site-packages/#  site-packages/#' -e 's#  .*/apps/#  apps/#' |
        LC_ALL=C sort
    rm -f "$tmp"
}

# The template key: 16 hex over that listing. Returns 1 when the listing does.
db_migration_key() {
    local listing
    listing="$(db_migration_listing "$(db_checkout_root)")" || return 1
    [ -n "$listing" ] || return 1
    db_path_hash "$listing" 16
}

db_template_name() {
    local key
    key="$(db_migration_key)" || return 1
    printf 'djb_tmpl_%s' "$key"
}

# Is THIS the name that gets the template? Derived, never listed: the one
# database this checkout makes for itself. `DJB_DB_TEMPLATE=off` is the escape,
# and it is the same shape as `DATABASE_NAME`'s — an environment variable that
# turns a derivation off without editing anything.
db_template_wanted() {
    local name="${1:-}"
    [ "${DJB_DB_TEMPLATE:-on}" != "off" ] || return 1
    [ -n "$name" ] || return 1
    [ "$name" = "$(db_name)" ] || return 1
    return 0
}

# CREATE DATABASE <new> TEMPLATE <src>, retrying the one refusal Postgres raises
# for a template somebody is using. Prints the server's own words on the way out
# — a paraphrase of a Postgres error is how a caller ends up debugging the
# paraphrase.
db_clone_database() {
    local new="${1:-}" src="${2:-}" out=""
    local attempts="${DB_TEMPLATE_CLONE_ATTEMPTS:-5}"
    local backoff="${DB_TEMPLATE_CLONE_BACKOFF:-1}"
    local n=1
    if ! db_valid_name "$new"; then
        db_refuse_name "$new"
        return 2
    fi
    if ! db_valid_name "$src"; then
        db_refuse_name "$src"
        return 2
    fi
    while :; do
        # `if !` and not `set +e`: this file may not change the caller's shell
        # options, and a bare failing command under a caller's `set -e` would
        # take the whole script down inside a function whose entire job is to
        # fail survivably.
        if out="$(db_query 'CREATE DATABASE :"new" TEMPLATE :"src" OWNER :"owner"' \
            -v new="$new" -v src="$src" -v owner="$POSTGRES_USER" 2>&1)"; then
            return 0
        fi
        case "$out" in
        *"being accessed by other users"*)
            if [ "$n" -lt "$attempts" ]; then
                printf 'db.sh: template %s is momentarily in use — retrying (%d/%d)\n' \
                    "$src" "$n" "$attempts" >&2
                sleep "$backoff"
                n=$((n + 1))
                continue
            fi
            ;;
        esac
        printf '%s\n' "$out" >&2
        return 1
    done
}

# The one name that gets the template path. Always prints the instrument line —
# `path=` and `elapsed=` — whichever way it went, because a mechanism whose
# speed claim is a builder's stopwatch is a claim nobody else can re-measure.
db_create_the_checkouts_own() {
    local name="$1" t0 key tmpl="" path=fallback reason=""
    t0="$(db_now_ms)"
    key="$(db_migration_key 2>/dev/null || true)"
    if [ -z "$key" ]; then
        reason="this checkout's migration set could not be digested (no sha256 tool on PATH, or no migration files under apps/)"
    else
        tmpl="djb_tmpl_${key}"
        if db_exists "$tmpl"; then
            if db_clone_database "$name" "$tmpl"; then
                path=template
            else
                reason="${tmpl} is on this server and could not be cloned — the server's own words are above"
            fi
        else
            reason="no ${tmpl} on this server for this checkout's migration set"
        fi
    fi
    if [ "$path" = fallback ]; then
        db_query 'CREATE DATABASE :"name" OWNER :"owner"' \
            -v name="$name" -v owner="$POSTGRES_USER" >/dev/null
    fi
    # The line every caller reads, unchanged and first.
    echo "created database ${name}"
    printf 'db.sh: db_create %s path=%s elapsed=%s\n' "$name" "$path" "$(db_elapsed_since "$t0")"
    if [ "$path" = template ]; then
        printf 'db.sh: cloned from %s — the migration chain did not run; the caller'\''s\n' "$tmpl"
        printf '       `migrate` has nothing left to apply.\n'
    else
        printf 'db.sh: TEMPLATE MISS — %s.\n' "$reason"
        printf '       This database is EMPTY, the caller'\''s `migrate` runs the whole chain,\n'
        printf '       and that is exactly what happened before the template existed. Nothing\n'
        printf '       is wrong here; it is slow. Publish the template for this migration set\n'
        printf '       once and every checkout on this machine clones it after that:\n'
        printf '         bash -c '\''. scripts/db.sh && db_template_refresh'\''\n'
    fi
    return 0
}

# Drop every PUBLISHED template that is not the one being kept. Build scratches
# (`djb_tmpl_<key>_mk<6 hex>`) are deliberately outside the pattern: one of them
# is another checkout's refresh in flight. A drop that Postgres refuses is not a
# failure of this function — the template is in use, which is the one state in
# which not dropping it is right.
db_template_prune() {
    local keep="${1:-}" name
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        [ "$name" != "$keep" ] || continue
        db_valid_name "$name" || continue
        if db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$name" >/dev/null 2>&1; then
            printf 'db.sh: dropped the superseded template %s\n' "$name"
        fi
    done <<EOF
$(db_query "SELECT datname FROM pg_database WHERE datname ~ '^djb_tmpl_[0-9a-f]{16}\$'" -tA 2>/dev/null || true)
EOF
}

# THE REFRESH HOOK. Publish the template for this checkout's migration set, if
# it is not already published. Idempotent, and cheap to call when nothing has
# changed — which is what lets the merge path call it unconditionally.
#
#   exit 0  the template for this migration set is published (by this call or
#           already, or by another checkout that won the race)
#   exit 1  the scratch was built and `migrate` failed against it — nothing was
#           published, and migrate's own transcript is on stderr
#   exit 2  could not look: no digestible migration set, no `uv`, or the scratch
#           could not be created
db_template_refresh() {
    local root listing key tmpl scratch count t0 out
    t0="$(db_now_ms)"
    root="$(db_checkout_root)"
    if ! listing="$(db_migration_listing "$root")" || [ -z "$listing" ]; then
        echo "!! db_template_refresh: this checkout's migration set could not be digested." >&2
        echo "   Either there is no sha256 tool on PATH or there are no migration files" >&2
        echo "   under ${root}/apps. Nothing was created (scripts/db.sh)." >&2
        return 2
    fi
    key="$(db_path_hash "$listing" 16)"
    count="$(printf '%s\n' "$listing" | wc -l | tr -d ' ')"
    tmpl="djb_tmpl_${key}"
    if db_exists "$tmpl"; then
        printf 'db.sh: %s is already published (%s migration files) — nothing to build.\n' "$tmpl" "$count"
        db_template_prune "$tmpl"
        return 0
    fi
    if ! command -v uv >/dev/null 2>&1; then
        echo "!! db_template_refresh: no \`uv\` on PATH, and the template is built by" >&2
        echo "   running this checkout's own \`manage.py migrate\` against a scratch" >&2
        echo "   database. Nothing was created (scripts/db.sh)." >&2
        return 2
    fi
    scratch="djb_tmpl_${key}_mk$(db_path_hash "$$-${RANDOM:-0}-$(date +%s)" 6)"
    if ! db_valid_name "$scratch"; then
        db_refuse_name "$scratch"
        return 2
    fi
    printf 'db.sh: building %s from %s migration files, through a scratch database.\n' "$tmpl" "$count"
    if ! db_query 'CREATE DATABASE :"name" OWNER :"owner"' \
        -v name="$scratch" -v owner="$POSTGRES_USER" >/dev/null 2>&1; then
        echo "!! db_template_refresh: could not create the scratch database ${scratch}." >&2
        return 2
    fi
    # The scratch is migrated through THIS checkout's venv and settings, which is
    # the same `migrate` every consumer would have run for itself. An exported
    # DATABASE_NAME wins over `.env` (django-environ's read_env does not
    # overwrite the environment), which is the same seam
    # `scripts/rung_start.sh:469` and `scripts/perf.sh` already rely on.
    if ! out="$(cd "$root" && DATABASE_NAME="$scratch" uv run python manage.py migrate --no-input 2>&1)"; then
        printf '%s\n' "$out" >&2
        echo "!! db_template_refresh: migrate failed against the scratch ${scratch}." >&2
        echo "   NOTHING WAS PUBLISHED — the template a half-migrated scratch would have" >&2
        echo "   become is the one object on this machine every checkout would then copy." >&2
        db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$scratch" >/dev/null 2>&1 || true
        return 1
    fi
    # PUBLICATION, and it is one statement on purpose (see the block above).
    if db_clone_database "$tmpl" "$scratch"; then
        db_query 'ALTER DATABASE :"name" ALLOW_CONNECTIONS false' -v name="$tmpl" >/dev/null 2>&1 || true
        printf 'db.sh: published %s in %s — every checkout on this machine with this\n' \
            "$tmpl" "$(db_elapsed_since "$t0")"
        printf '       migration set now clones it instead of migrating.\n'
    elif db_exists "$tmpl"; then
        printf 'db.sh: another checkout published %s first — using theirs, dropping mine.\n' "$tmpl"
    else
        echo "!! db_template_refresh: the scratch migrated and could not be published." >&2
        db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$scratch" >/dev/null 2>&1 || true
        return 1
    fi
    db_query 'DROP DATABASE :"name" WITH (FORCE)' -v name="$scratch" >/dev/null 2>&1 || true
    db_template_prune "$tmpl"
    db_exists "$tmpl"
}

# THE MERGE PATH'S CALL. Same refresh, ADVISORY: it never fails, never changes
# a caller's exit status, and says nothing at all when it cannot look. That
# combination is deliberate and each half has a reason.
#
#   * NEVER FAILS, because the caller is `scripts/pm_merge.sh` and a merge that
#     already happened must not be reported red by a cache warmer. The template
#     is an optimisation; the merge is the work.
#   * SAYS NOTHING WHEN IT CANNOT LOOK, because the same script runs inside
#     `scripts/tests/test_pm_merge.sh`'s scratch repositories — no `apps/`, no
#     compose stack, no Postgres — and a warmer that printed a docker error into
#     every one of that drive's cases would be teaching a reader to skip output.
#
# It is called at the MERGE and not at rung start on purpose: a builder mid-rung
# has a migration set that exists only in their worktree, and building a
# machine-global template for it would leave one behind per in-flight rung.
# Merged states are the ones every checkout is about to want.
db_template_refresh_advisory() {
    db_query 'SELECT 1' -tA >/dev/null 2>&1 || return 0
    db_migration_listing "$(db_checkout_root)" >/dev/null 2>&1 || return 0
    command -v uv >/dev/null 2>&1 || return 0
    db_template_refresh || true
    return 0
}
