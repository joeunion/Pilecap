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
# drives: apps/ config/ quality/ scripts/check.sh scripts/db.sh scripts/kill_mine.sh scripts/lifecycle.sh scripts/queue_cited.sh scripts/rung_start.sh scripts/setup.sh scripts/sweep.sh scripts/test.sh scripts/tests/test_rung_start.sh
# THE TEMPLATE-DATABASE DRIVE.
#
# WHAT IT DRIVES. `scripts/db.sh` grew a migrated TEMPLATE database: when the
# template matches this checkout's migration set, `db_create` makes the
# checkout's own database with `CREATE DATABASE ... TEMPLATE` — seconds instead
# of the whole migration chain — and when it does not, it creates a plain empty
# database and SAYS SO, leaving the caller's `migrate` to do exactly what it
# always did. Three properties carry the whole mechanism and each has cases
# here:
#
#   1. THE KEY IS DERIVED FROM THE MIGRATION FILES AND NOTHING ELSE. A
#      hand-bumped version is the drift class this repository refuses
#      everywhere (the rules engine's whole argument), so the template's
#      identity is a digest of the migration set: it moves when a migration
#      file is added, changed or removed, and it does NOT move for any other
#      edit. Both halves are asserted, because a key that moves for everything
#      is a template that never hits and a key that moves for nothing is a
#      template that lies.
#
#   2. THE KEY IS THE SAME IN EVERY CHECKOUT. The template is MACHINE-GLOBAL —
#      that is the entire saving, one migrate for every worktree on the box —
#      so two checkouts holding the same migration files at different absolute
#      paths must derive the same key. `db_name` deliberately does the
#      opposite (the name follows the checkout), and these two derivations
#      living in one file is exactly why this case is written down.
#
#   3. THE TEMPLATE IS ITS OWN LIFECYCLE CLASS. `djb_tmpl_<key>` is not a
#      checkout database and must not be claimed as one — a broom that read it
#      as some dead worktree's leftovers would drop the thing every checkout on
#      the machine clones from. The case asks `scripts/lifecycle.sh` what
#      claims the shape and requires the answer to be `migration-template`.
#
# THE LIVE HALF needs the compose Postgres, and says so at exit 2 rather than
# skipping: a template mechanism proved only on strings is a template mechanism
# nobody has watched clone anything. Those cases create their OWN victims —
# scratch database names carrying this drive's marker — and never touch this
# checkout's working database or any template a real refresh published.
#
# WHAT IT DOES NOT COVER, declared:
#
#   1. IT NEVER RUNS `db_template_refresh` AGAINST THE REAL MIGRATION SET.
#      Building the real template costs a full `migrate` and would publish a
#      machine-global object from inside a test run; the live cases build their
#      own tiny template out of one table instead. So this drive proves the
#      CLONE, the REFUSAL and the FALLBACK; it does not prove that a real
#      refresh produces a schema `migrate --check` calls clean. The rung report
#      carries that measurement, and `migrate --check` in every consumer
#      (`scripts/rung_start.sh:477`, `scripts/setup.sh`) is the standing net.
#   2. IT ASSERTS NOTHING ABOUT ELAPSED TIME. The ≤5s claim is db.sh's own
#      printed line, re-measured on a named host; a threshold
#      asserted here would go red on a loaded laptop and teach the next
#      reader to ignore it.
#   3. IT IS NOT WIRED INTO THE GATE'S `selftest` LEG. `scripts/check.sh` was
#      another rung's territory in the same cycle (the same reason
#      `scripts/tests/test_rung_start.sh` records), so the wiring is owed
#      rather than done and this drive is run by hand until it lands.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_db_template: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble, opted into. On bash 3.2 a `set -u` death
# hands the EXIT trap a status of 0, so a drive that dies halfway reads as a
# PASS to check.sh — which is exactly how a drive that ran none of its cases
# reports success. Every case below is worthless without this.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_db_template: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

LIVE=1
case "${1:-}" in
"") ;;
--no-live) LIVE=0 ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_db_template.sh takes nothing, --no-live or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/db.sh ] || cannot_look "scripts/db.sh is not in this tree — there is nothing to drive"
[ -f scripts/lifecycle.sh ] || cannot_look "scripts/lifecycle.sh is not in this tree — the class question cannot be asked"

ROOT="$PWD"

# shellcheck source=scripts/db.sh
. scripts/db.sh
for fn in db_migration_key db_template_name db_template_refresh db_create; do
    command -v "$fn" >/dev/null 2>&1 ||
        cannot_look "scripts/db.sh defines no ${fn} — the mechanism this drive exists for is not there"
done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-db-template-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"

# The live cases' own victims, named so nothing else on this server can be
# mistaken for one. Dropped on the way out whatever happened.
DRIVE_TAG="drv$$"
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
differs() {
    if [ "$2" != "$3" ]; then ok "$1"; else bad "$1 — both are '$2'"; fi
}

# --- a scratch checkout carrying migration files -------------------------------
#
# `db_migration_key` reads the migration files under a checkout's top level, so
# a repository with two of them in it is the whole fixture. No venv: the key's
# third-party half is absent here and the case says what it is asserting.
# Sets REPO. NOT a command substitution — `N` has to survive the call, and a
# subshell would also swallow git's own chatter into the returned path, which is
# how the first draft of this drive built one checkout six times.
REPO=""
fresh_checkout() {
    N=$((N + 1))
    REPO="${WORK}/checkout${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/apps/widgets/migrations"
    git -C "$REPO" init -q
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "db template drive"
    printf 'class Migration:\n    dependencies = []\n' >"$REPO/apps/widgets/migrations/0001_initial.py"
    printf '' >"$REPO/apps/widgets/migrations/__init__.py"
    printf 'WIDGET = 1\n' >"$REPO/apps/widgets/models.py"
    git -C "$REPO" add -A
    git -C "$REPO" commit -q -m base
}

key_in() {
    (cd "$1" && db_migration_key)
}

# --- the cases -----------------------------------------------------------------

case_a_new_migration_moves_the_key() {
    CURRENT=case_a_new_migration_moves_the_key
    OUT=""
    local before after
    fresh_checkout
    before="$(key_in "$REPO")"
    if [ -z "$before" ]; then
        bad "db_migration_key derived nothing over a checkout with a migration in it"
        return 0
    fi
    ok "a checkout with migrations derives a key (${before})"
    printf 'class Migration:\n    dependencies = [("widgets", "0001_initial")]\n' \
        >"$REPO/apps/widgets/migrations/0002_more.py"
    after="$(key_in "$REPO")"
    differs "adding a migration file moves the key" "$before" "$after"
}

case_editing_a_migration_moves_the_key() {
    CURRENT=case_editing_a_migration_moves_the_key
    OUT=""
    local before after
    fresh_checkout
    before="$(key_in "$REPO")"
    printf 'class Migration:\n    dependencies = []\n    atomic = False\n' \
        >"$REPO/apps/widgets/migrations/0001_initial.py"
    after="$(key_in "$REPO")"
    differs "changing a migration file's CONTENT moves the key" "$before" "$after"
}

case_removing_a_migration_moves_the_key() {
    CURRENT=case_removing_a_migration_moves_the_key
    OUT=""
    local before after
    fresh_checkout
    printf 'class Migration:\n    dependencies = []\n' >"$REPO/apps/widgets/migrations/0002_more.py"
    before="$(key_in "$REPO")"
    rm "$REPO/apps/widgets/migrations/0002_more.py"
    after="$(key_in "$REPO")"
    differs "removing a migration file moves the key" "$before" "$after"
}

case_a_non_migration_edit_does_not_move_the_key() {
    CURRENT=case_a_non_migration_edit_does_not_move_the_key
    OUT=""
    local before after
    fresh_checkout
    before="$(key_in "$REPO")"
    printf 'WIDGET = 2\nEXTRA = "a whole new model, no migration yet"\n' >"$REPO/apps/widgets/models.py"
    printf 'a service\n' >"$REPO/apps/widgets/services.py"
    printf 'a doc\n' >"$REPO/README.md"
    after="$(key_in "$REPO")"
    same "an edit outside migrations/ leaves the key alone" "$after" "$before"
}

case_the_key_is_the_same_wherever_the_checkout_lives() {
    CURRENT=case_the_key_is_the_same_wherever_the_checkout_lives
    OUT=""
    local one two k1 k2
    fresh_checkout
    one="$REPO"
    fresh_checkout
    two="$REPO"
    k1="$(key_in "$one")"
    k2="$(key_in "$two")"
    same "two checkouts, same migration files, different paths — one key" "$k2" "$k1"
    # And the contrast that makes the case worth having: db_name deliberately
    # differs between them, so this is not two functions agreeing by luck.
    differs "db_name still differs between the same two checkouts" \
        "$(cd "$one" && db_name)" "$(cd "$two" && db_name)"
}

case_a_checkout_with_no_migrations_derives_no_key() {
    CURRENT=case_a_checkout_with_no_migrations_derives_no_key
    OUT=""
    local repo rc
    repo="${WORK}/bare"
    drive_require_scratch repo "${repo:-}"
    mkdir -p "$repo"
    git -C "$repo" init -q
    git -C "$repo" config user.email drive@example.invalid
    git -C "$repo" config user.name "db template drive"
    rc=0
    (cd "$repo" && db_migration_key >/dev/null 2>&1) || rc=$?
    if [ "$rc" -ne 0 ]; then
        ok "no migration files at all is a REFUSAL (exit ${rc}), not an empty digest every tree would share"
    else
        bad "a checkout with no migrations derived a key — every such tree would share one template"
    fi
}

case_the_template_name_is_the_key_and_a_legal_database_name() {
    CURRENT=case_the_template_name_is_the_key_and_a_legal_database_name
    OUT=""
    local key name
    fresh_checkout
    key="$(key_in "$REPO")"
    name="$(cd "$REPO" && db_template_name)"
    same "db_template_name is djb_tmpl_ plus the key" "$name" "djb_tmpl_${key}"
    if db_valid_name "$name"; then
        ok "the template name passes db_valid_name"
    else
        bad "the template name is not a name this file will put in SQL"
    fi
}

case_the_template_is_its_own_lifecycle_class() {
    CURRENT=case_the_template_is_its_own_lifecycle_class
    OUT=""
    local claimed name build
    name="djb_tmpl_0123456789abcdef"
    build="djb_tmpl_0123456789abcdef_mkab12cd"
    claimed="$(
        set +u
        # shellcheck source=scripts/lifecycle.sh
        . "${ROOT}/scripts/lifecycle.sh" >/dev/null 2>&1 || true
        lc_class_of database "$name" 2>/dev/null
    )"
    same "a published template is claimed by the migration-template class" "$claimed" "migration-template"
    claimed="$(
        set +u
        . "${ROOT}/scripts/lifecycle.sh" >/dev/null 2>&1 || true
        lc_class_of database "$build" 2>/dev/null
    )"
    same "the build scratch is claimed by the same class" "$claimed" "migration-template"
    # The half that matters for the broom: it must NOT read as a checkout
    # database, or a machine-wide sweep would offer to drop it as some dead
    # worktree's leftovers.
    if ( set +u; . "${ROOT}/scripts/lifecycle.sh" >/dev/null 2>&1 || true; lc_claim_checkout_database "$name" ); then
        bad "the checkout-database class claims the template — a broom would drop what every checkout clones from"
    else
        ok "the checkout-database class does NOT claim the template"
    fi
}

# --- the live cases ------------------------------------------------------------
#
# Their own victims: a tiny template built by hand out of one table, and clone
# targets carrying this drive's tag. Nothing here touches the real template or
# this checkout's working database.

live_ready() {
    db_query 'SELECT 1' -tA >/dev/null 2>&1
}

# How many tables a database holds. `|| true` and not bare, because this drive
# runs under `set -e` and a psql that cannot answer is a FAILED assertion with
# the count it saw, never a run that stops mid-case with no verdict.
public_table_count() {
    local out=""
    out="$(printf "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';" |
        docker compose exec -T db psql -tA -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" 2>/dev/null |
        tr -d '[:space:]')" || true
    printf '%s' "${out:-unreadable}"
}

SRC=""
build_scratch_template() {
    SRC="djb_tmpl_ffffffffffffffff_mk${DRIVE_TAG}"
    SRC="${SRC:0:63}"
    db_valid_name "$SRC" || cannot_look "the drive's own template name is not a legal one: ${SRC}"
    LIVE_DBS+=("$SRC")
    db_query 'DROP DATABASE IF EXISTS :"name" WITH (FORCE)' -v name="$SRC" >/dev/null 2>&1 || true
    db_query 'CREATE DATABASE :"name" OWNER :"owner"' -v name="$SRC" -v owner="$POSTGRES_USER" >/dev/null
    printf 'CREATE TABLE the_proof (id int primary key); INSERT INTO the_proof VALUES (1),(2),(3);' |
        docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$SRC" >/dev/null
    # Published templates allow no connections — that is what makes a concurrent
    # clone impossible to refuse (see db.sh's TEMPLATE block).
    db_query 'ALTER DATABASE :"name" ALLOW_CONNECTIONS false' -v name="$SRC" >/dev/null
}

case_a_no_connections_template_clones() {
    CURRENT=case_a_no_connections_template_clones
    OUT="${WORK}/clone.log"
    local target rows rc
    target="djb_tmplclone_${DRIVE_TAG}"
    LIVE_DBS+=("$target")
    rc=0
    db_clone_database "$target" "$SRC" >"$OUT" 2>&1 || rc=$?
    if [ "$rc" -ne 0 ]; then
        bad "db_clone_database exited ${rc}"
        return 0
    fi
    ok "db_clone_database cloned a template that allows no connections"
    rows="$(printf 'SELECT count(*) FROM the_proof;' |
        docker compose exec -T db psql -tA -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$target" 2>/dev/null | tr -d '[:space:]')"
    same "the clone carries the template's rows" "$rows" "3"
}

case_concurrent_clones_of_one_template_all_succeed_uncorrupted() {
    CURRENT=case_concurrent_clones_of_one_template_all_succeed_uncorrupted
    OUT="${WORK}/concurrent.log"
    local i n=6 rc target rows failed=0
    : >"$OUT"
    for i in $(seq 1 "$n"); do
        target="djb_tmplrace${i}_${DRIVE_TAG}"
        LIVE_DBS+=("$target")
        (
            db_clone_database "$target" "$SRC" >>"$OUT" 2>&1
            echo "clone${i} exit=$?" >>"$OUT"
        ) &
    done
    wait
    for i in $(seq 1 "$n"); do
        grep -q "clone${i} exit=0" "$OUT" || failed=$((failed + 1))
    done
    if [ "$failed" -eq 0 ]; then
        ok "${n} checkouts cloning one template at once — every clone succeeded"
    else
        bad "${failed} of ${n} concurrent clones failed"
        return 0
    fi
    rc=0
    for i in $(seq 1 "$n"); do
        target="djb_tmplrace${i}_${DRIVE_TAG}"
        rows="$(printf 'SELECT count(*) FROM the_proof;' |
            docker compose exec -T db psql -tA -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$target" 2>/dev/null | tr -d '[:space:]')"
        [ "$rows" = "3" ] || rc=$((rc + 1))
    done
    if [ "$rc" -eq 0 ]; then
        ok "and every one of the ${n} carries the template's rows — none corrupted, none half-copied"
    else
        bad "${rc} of ${n} concurrent clones came out with the wrong contents"
    fi
}

case_a_template_in_use_is_retried_and_then_refused_out_loud() {
    CURRENT=case_a_template_in_use_is_retried_and_then_refused_out_loud
    OUT="${WORK}/inuse.log"
    local open target rc
    # A source that DOES allow connections, with a session held on it, is the
    # refusal Postgres actually raises. The drive holds the session itself so
    # the refusal is produced rather than described.
    open="djb_tmplopen_${DRIVE_TAG}"
    target="djb_tmplopenc_${DRIVE_TAG}"
    LIVE_DBS+=("$open" "$target")
    db_query 'DROP DATABASE IF EXISTS :"name" WITH (FORCE)' -v name="$open" >/dev/null 2>&1 || true
    db_query 'CREATE DATABASE :"name" OWNER :"owner"' -v name="$open" -v owner="$POSTGRES_USER" >/dev/null
    docker compose exec -T db psql -U "$POSTGRES_USER" -d "$open" -c "SELECT pg_sleep(20);" >/dev/null 2>&1 &
    local hold=$!
    sleep 2
    rc=0
    DB_TEMPLATE_CLONE_ATTEMPTS=2 DB_TEMPLATE_CLONE_BACKOFF=1 \
        db_clone_database "$target" "$open" >"$OUT" 2>&1 || rc=$?
    kill "$hold" 2>/dev/null || true
    wait "$hold" 2>/dev/null || true
    if [ "$rc" -ne 0 ]; then
        ok "a template with a session on it is refused (exit ${rc}), not silently skipped"
    else
        bad "cloning from an in-use template returned 0 — the refusal was not seen"
        return 0
    fi
    if grep -q "being accessed by other users" "$OUT"; then
        ok "the refusal Postgres raised is printed verbatim, not paraphrased"
    else
        bad "the caller cannot see WHY the clone failed"
    fi
    if grep -q "retrying" "$OUT"; then
        ok "it retried before giving up — a momentary overlap is not a fallback"
    else
        bad "no retry: a one-second overlap between two checkouts would cost a full migrate"
    fi
}

case_a_migration_set_with_no_template_falls_back_out_loud() {
    CURRENT=case_a_migration_set_with_no_template_falls_back_out_loud
    OUT="${WORK}/fallback.log"
    local target rc
    # THE FALLBACK, DRIVEN BY MOVING THE MIGRATION STATE and not by an escape.
    # A scratch checkout with its own one-line migration file has a migration
    # set no template on this server was ever built for, which is exactly the
    # state a builder is in the moment they add a migration — and it is the
    # state the loud line exists for.
    fresh_checkout
    target="$(cd "$REPO" && db_name)"
    if [ -z "$target" ]; then
        bad "db_name derived nothing in the scratch checkout"
        return 0
    fi
    LIVE_DBS+=("$target")
    rc=0
    # COMPOSE_FILE, because the derivation has to be read from the scratch
    # checkout and the Postgres has to be THIS repository's: `docker compose`
    # resolves its file from the working directory, and a scratch checkout has
    # none — which the first draft of this case discovered by asserting the
    # right lines over a database that had never been created.
    (cd "$REPO" && COMPOSE_FILE="${ROOT}/compose.yaml" DATABASE_NAME="$target" db_create) >"$OUT" 2>&1 || rc=$?
    same "db_create exits 0 on the fallback path — a missing template is not an error" "$rc" "0"
    if grep -q "created database ${target}" "$OUT"; then
        ok "the line every caller has read is unchanged, and it comes first"
    else
        bad "db_create stopped saying 'created database <name>' — its CLI moved"
    fi
    if grep -qE "db\.sh: db_create ${target} path=fallback elapsed=[0-9]" "$OUT"; then
        ok "it names the path it took and the elapsed time — the line a later verification pass re-reads"
    else
        bad "no 'path=... elapsed=...' line: the ≤5s claim would have no instrument"
    fi
    if grep -q "TEMPLATE MISS" "$OUT" && grep -q "db_template_refresh" "$OUT"; then
        ok "the miss is LOUD and names the one command that fixes it"
    else
        bad "the miss is quiet — a builder paying a full migrate would never learn why"
    fi
    # And the database it made is EMPTY: a fallback that half-populated one
    # would be worse than no template at all.
    same "the fallback database is empty, for the caller's own migrate to fill" \
        "$(public_table_count "$target")" "0"
}

case_the_escape_restores_the_old_behaviour_exactly() {
    CURRENT=case_the_escape_restores_the_old_behaviour_exactly
    OUT="${WORK}/escape.log"
    local target rc
    # `DJB_DB_TEMPLATE=off` is not "force the fallback" — it is "pretend this
    # block was never written", which is what an escape has to be to be worth
    # anything when the mechanism is the suspect.
    fresh_checkout
    target="$(cd "$REPO" && db_name)"
    LIVE_DBS+=("$target")
    rc=0
    (cd "$REPO" && COMPOSE_FILE="${ROOT}/compose.yaml" DATABASE_NAME="$target" DJB_DB_TEMPLATE=off db_create) >"$OUT" 2>&1 || rc=$?
    same "db_create exits 0" "$rc" "0"
    if grep -q "path=" "$OUT"; then
        bad "the escape still narrated a path — it is not an escape from the block, only from the clone"
    else
        ok "with the escape set, db_create says exactly what it said before the template existed, and nothing more"
    fi
}

case_a_name_that_is_not_this_checkouts_own_is_never_templated() {
    CURRENT=case_a_name_that_is_not_this_checkouts_own_is_never_templated
    OUT="${WORK}/other.log"
    local target rc
    # restore_drill.sh creates a database and then pg_restores a dump INTO it,
    # and perf.sh creates its `_perf` world; both would break outright if
    # db_create started handing back a populated database. The template path is
    # for this checkout's own DERIVED working database and nothing else.
    target="djb_tmplother_${DRIVE_TAG}"
    LIVE_DBS+=("$target")
    rc=0
    db_create "$target" >"$OUT" 2>&1 || rc=$?
    same "db_create exits 0" "$rc" "0"
    if grep -q "path=" "$OUT"; then
        bad "db_create narrated a path for a name that is not this checkout's own — its output moved for restore_drill and perf"
    else
        ok "a name that is not this checkout's own gets the old behaviour, byte for byte"
    fi
    if db_template_wanted "$target"; then
        bad "db_template_wanted said yes to a name that is not this checkout's derivation"
    else
        ok "db_template_wanted refuses a name that is not this checkout's derivation"
    fi
    if db_template_wanted "$(db_name)"; then
        ok "and says yes to the one that is"
    else
        bad "db_template_wanted refuses this checkout's own derived name — nothing would ever be templated"
    fi
}

# --- the cases: THE SUITE SPENDS THE TEMPLATE --------------------------
#
# An earlier pass published a template and wired it to `db_create` only, so
# the SUITE went on migrating ten times — once per xdist worker, ~5s each, ~49 CPU-seconds a
# pass and paid twice by the full gate, all before a single assertion. A later
# verification pass found the line that spends it (`TEST["TEMPLATE"]`) had been specified in
# `apps/conftest.py` and never written.
#
# WHY THE GUARD IS THE WHOLE SUBJECT HERE. `db_create` misses LOUDLY: no
# template for this migration set, it says so and migrates. **Django has no such
# fallback.** With `TEST["TEMPLATE"]` set it issues `CREATE DATABASE … WITH
# TEMPLATE …` unconditionally, and a template that is absent or superseded kills
# the whole suite at database setup — every worker, before any test. So the name
# reaches settings ONLY when the template really exists, `scripts/test.sh` is
# where that is decided (it holds the socket and is about to run the suite), and
# these cases drive both directions of that decision.
#
# WHAT IS ASSERTED WHERE. The mechanism is here, cheaply: no case below runs a
# test or creates a database — `--collect-only` exercises the real export
# decision and prints the real banner without a single `CREATE DATABASE`. The
# COST claim (the ten setup entries collapsing) and the two whole-suite green
# runs, template present and template absent, are the rung report's, because a
# gate leg cannot afford two suite runs to prove a speed-up.

python_reads_test_template() {
    # What `config/settings/test.py` actually resolves, asked of Django rather
    # than of the file. `TEST` is absent entirely when nothing is exported,
    # which is the state a fresh clone has to have.
    (cd "$ROOT" && uv run python -c '
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()
from django.conf import settings
print(settings.DATABASES["default"].get("TEST", {}).get("TEMPLATE", "<none>"))
' 2>/dev/null | tail -1)
}

case_the_settings_take_the_template_from_the_environment() {
    CURRENT=case_the_settings_take_the_template_from_the_environment
    OUT=""
    local got
    got="$(DJB_TEST_DB_TEMPLATE=djb_tmpl_drive_probe python_reads_test_template)"
    same "the exported name reaches TEST[TEMPLATE]" "$got" "djb_tmpl_drive_probe"
}

case_the_settings_name_no_template_when_the_environment_is_silent() {
    # THE FRESH-CLONE CASE, and the one that keeps a suite alive. Nothing
    # exported must mean no TEMPLATE key at all — not an empty string, which
    # Django would still hand to Postgres.
    CURRENT=case_the_settings_name_no_template_when_the_environment_is_silent
    OUT=""
    local got
    got="$(DJB_TEST_DB_TEMPLATE= python_reads_test_template)"
    same "no environment, no TEST[TEMPLATE]" "$got" "<none>"
    got="$(DJB_TEST_DB_TEMPLATE="   " python_reads_test_template)"
    same "whitespace is not a template name either" "$got" "<none>"
}

case_a_published_template_reaches_the_suite() {
    # The real decision, made by the real script. `--collect-only` runs the
    # export block and then collects; no test runs and no database is created.
    CURRENT=case_a_published_template_reaches_the_suite
    N=$((N + 1))
    OUT="${WORK}/spend-present${N}.log"
    local want
    want="$(cd "$ROOT" && db_template_name 2>/dev/null || true)"
    if [ -z "$want" ] || ! db_exists "$want" >/dev/null 2>&1; then
        # Not a failure: this checkout simply has no template published for its
        # migration set. Say so rather than asserting something that is not true
        # of this machine right now.
        ok "SKIPPED — no template published for this checkout's migration set (${want:-<no key>})"
        return
    fi
    (cd "$ROOT" && ./scripts/test.sh --collect-only -q -p no:randomly) >"$OUT" 2>&1 || true
    if grep -qF "CLONED from ${want}" "$OUT"; then
        ok "test.sh exports the published template (${want}) to the suite"
    else
        bad "test.sh did not name the published template ${want} — the suite would migrate ten times again"
    fi
}

case_a_template_that_is_not_published_is_never_exported() {
    # THE TRAP, DRIVEN. The migration set is perturbed so the derived key moves
    # to one nothing has published — exactly a fresh clone, or a checkout whose
    # migration state moved under a stale template. Nothing may be exported,
    # because what Django does with a TEMPLATE that is not there is kill the
    # suite at setup rather than fall back.
    #
    # THE PERTURBATION IS A COMMENT APPENDED TO A REAL MIGRATION, and restored
    # byte for byte: the key is a digest of migration file CONTENTS
    # (`db_migration_listing`), so one comment moves it, and a comment is the one
    # edit that cannot change what the migration DOES.
    CURRENT=case_a_template_that_is_not_published_is_never_exported
    N=$((N + 1))
    OUT="${WORK}/spend-absent${N}.log"
    local victim before after
    victim="$(cd "$ROOT" && find apps -type f -path '*/migrations/0001_initial.py' | LC_ALL=C sort | head -1)"
    if [ -z "$victim" ]; then
        cannot_look "no migration file to perturb — the absent-template case cannot be arranged"
    fi
    before="$(cd "$ROOT" && db_template_name 2>/dev/null || true)"
    cp "${ROOT}/${victim}" "${WORK}/victim.bak" || cannot_look "could not back up ${victim}"
    printf '\n# djb drive: temporary, removed by scripts/tests/test_db_template.sh\n' \
        >>"${ROOT}/${victim}"
    after="$(cd "$ROOT" && db_template_name 2>/dev/null || true)"
    (cd "$ROOT" && ./scripts/test.sh --collect-only -q -p no:randomly) >"$OUT" 2>&1 || true
    # Restore FIRST, before any assertion can fail out from under it.
    cp "${WORK}/victim.bak" "${ROOT}/${victim}"

    differs "the perturbed migration set derives a different key" "$after" "$before"
    if db_exists "$after" >/dev/null 2>&1; then
        ok "SKIPPED — the perturbed key ${after} happens to be published on this machine"
        return
    fi
    if grep -q "no published template for this migration set" "$OUT"; then
        ok "test.sh says the template is absent instead of exporting a name"
    else
        bad "test.sh did not announce the absent template — a reader cannot tell a fast run from a slow one"
    fi
    if grep -qF "CLONED from" "$OUT"; then
        bad "test.sh exported a template that is NOT on this server — Django would kill the suite at setup, every worker, with no fallback"
    else
        ok "nothing was exported, so Django creates each test database normally"
    fi
}

case_the_perturbed_migration_was_restored() {
    # A drive that plants in the real tree owes this. The file is restored
    # before the assertions above, so this proves the restore rather than
    # performing it.
    CURRENT=case_the_perturbed_migration_was_restored
    OUT=""
    if (cd "$ROOT" && git diff --quiet -- apps 2>/dev/null); then
        ok "apps/ is byte-identical to the index — the perturbation left nothing"
    else
        bad "apps/ still differs from the index after the perturbation was restored"
    fi
}

case_a_new_migration_moves_the_key
case_editing_a_migration_moves_the_key
case_removing_a_migration_moves_the_key
case_a_non_migration_edit_does_not_move_the_key
case_the_key_is_the_same_wherever_the_checkout_lives
case_a_checkout_with_no_migrations_derives_no_key
case_the_template_name_is_the_key_and_a_legal_database_name
case_the_template_is_its_own_lifecycle_class

if [ "$LIVE" -eq 1 ]; then
    command -v docker >/dev/null 2>&1 || cannot_look "no docker on PATH — the live half cannot look"
    live_ready || cannot_look "the compose Postgres is not reachable — the live half cannot look (docker compose up -d db)"
    build_scratch_template
    case_a_no_connections_template_clones
    case_concurrent_clones_of_one_template_all_succeed_uncorrupted
    case_a_template_in_use_is_retried_and_then_refused_out_loud
    case_a_migration_set_with_no_template_falls_back_out_loud
    case_the_escape_restores_the_old_behaviour_exactly
    case_a_name_that_is_not_this_checkouts_own_is_never_templated
    # The suite's half of the template. These need the server (they ask
    # whether a template is really published) but create nothing.
    case_the_settings_take_the_template_from_the_environment
    case_the_settings_name_no_template_when_the_environment_is_silent
    case_a_published_template_reaches_the_suite
    case_a_template_that_is_not_published_is_never_exported
    case_the_perturbed_migration_was_restored
else
    echo "  (--no-live: the clone, the refusal and the two db_create paths were NOT asserted)"
fi

echo "test_db_template: ${PASSED} passed · ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another
# case — see section 5 of the preamble for why saying so is load-bearing.
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the template database no longer behaves as designed. The three" >&2
    echo "   load-bearing halves: the key is DERIVED from the migration files (a" >&2
    echo "   hand-bumped version is the drift class this repository refuses), the" >&2
    echo "   key is the same in every checkout (the template is machine-global —" >&2
    echo "   that is the whole saving), and db_create's old behaviour is untouched" >&2
    echo "   for every name that is not this checkout's own (restore_drill.sh and" >&2
    echo "   perf.sh both create a database and then fill it themselves)." >&2
    exit 1
fi
exit 0
