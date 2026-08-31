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
# The census and the broom for LEFT-BEHIND TEST DATABASES.
#
#   ./scripts/db_sweep.sh                    census: this checkout's test databases
#   ./scripts/db_sweep.sh --all              census: every checkout's on this server
#   ./scripts/db_sweep.sh --sweep            drop this checkout's, if nothing holds them
#   ./scripts/db_sweep.sh --sweep --all      drop every checkout's, same refusals
#   ./scripts/db_sweep.sh --sweep --name X   one name, both refusals still applied
#   ./scripts/db_sweep.sh --sweep --hot-path ALSO drop the hot-path probe caches
#   ./scripts/db_sweep.sh --perf             census: this checkout's seeded perf world
#   ./scripts/db_sweep.sh --sweep --perf     ALSO drop it (0.6 GB per world)
#
#   ./scripts/db_sweep.sh --all-checkouts --orphans          census: the reaper
#   ./scripts/db_sweep.sh --all-checkouts --orphans --roots <dir>   ...+ clones under <dir>
#   ./scripts/db_sweep.sh --all-checkouts --orphans --sweep --force-foreign
#                                                            drop what it could not vouch for
#
# THREE POPULATIONS, AND THEY ARE NOT THE SAME KIND OF THING.
#
#   `test_djb_*[_gwN]` — a TEST DATABASE. Per run, per worker, disposable: the
#   next run creates and migrates its own. Left behind, it accumulates,
#   so it is what `--sweep` drops.
#
#   `djb_*_hp` — the HOT-PATH PROBE CACHE that rule 35 measures against
#   (`quality/hotpaths.py::probe_database_name`). ONE per checkout, stable,
#   reused, recreated on demand — it does not accumulate and it is not a leak.
#   It is a WARM CACHE, and dropping one while a gate is running fails that
#   run. So the census SHOWS it — it used to be invisible, which is the reason
#   this section exists — and only `--sweep --hot-path` will drop it. It is
#   never in the default broom, and there is deliberately no way to reach it by
#   accident.
#
#   `djb_*_perf` — the SEEDED PERF WORLD (`scripts/perf.sh`, ADR perf-1). Also
#   one per checkout, also a warm cache, and it is the EXPENSIVE one: ~0.6 GB
#   of disk each, and fourteen of them once filled a machine's disk. So it gets
#   the same treatment as `_hp` and for the same
#   reason — visible in every census as `warm`, dropped only by `--sweep --perf`
#   — because re-seeding one costs minutes and dropping one out from under a
#   running harness fails that harness. Visible is the fix; automatic is not.
#
# WHY IT EXISTS. A worker's test database is `test_<DATABASE_NAME>[_gwN]`
# (`scripts/db.sh` derives DATABASE_NAME per checkout; pytest-django adds the
# `_gwN` under `-n auto`). If a thread still holds a connection when the suite
# ends, Postgres refuses the drop, pytest-django downgrades that to a warning,
# and the database stays on disk — silently, per checkout, run after run.
# `apps/conftest.py` closes that at the source; this is the census that PROVES
# it stays closed, and the broom for what accumulated before it did.
#
# THE CENSUS IS THE POINT. Run it before and after a suite run: a leak shows as
# a name that was not there before. Zero new names is the property; this script
# is how you read it.
#
# THE DEFAULT CENSUS IS THIS CHECKOUT'S, NOT THIS MACHINE'S. "0 found"
# means this checkout has no leftover test database on this server; it says
# NOTHING about the eleven a peer worktree may be holding. `--all` is the
# machine-wide read, and it is a flag on purpose. This line exists because
# "0 found" was read as a machine-wide all-clear once, and a census whose
# scope has to be remembered is a census that will be misread again.
#
# THE ENUMERATOR AND THE FOUR VERDICTS NOW LIVE IN `scripts/lifecycle.sh`.
# This file wrote both, and still uses both — it is now one of two consumers
# rather than the owner. The live-checkout derivation (`lc_live_bases`,
# `lc_owning_checkout`, `lc_derived_shape`) and the verdict vocabulary moved
# there verbatim so that `scripts/sweep.sh` and this reaper cannot come to
# disagree about whether a checkout is alive: two copies of a liveness
# derivation is two answers to one question, and the second one is the one
# nobody read. Everything below about WHY the derivation works the way it does
# is still true and is kept here because this is where it was learned; the code
# that does it is one `source` away.
#
# THE REAPER — `--all-checkouts --orphans`.
# A database whose CHECKOUT NO LONGER EXISTS can never be reached by the scoped
# broom above: the scope is derived from the checkout, and the checkout is gone.
# Fourteen of them, one per deleted worktree, is how the disk filled. So this
# mode inverts the derivation: it asks which checkouts exist, derives the
# database name EACH of them would use, and then asks of every other
# derived-shaped name — WHOSE IS IT?
#
#   THE ANSWER IS OFTEN "I DO NOT KNOW", AND THAT IS NOW A VERDICT OF ITS OWN.
#   This mode used to have three answers and the middle one lied. It called
#   every derived-shaped name it did not recognise an ORPHAN and offered to
#   drop it — but the only thing it had actually established was that THIS
#   checkout's `git worktree list` does not derive it, and a SEPARATE CLONE of
#   this repository can never appear in that list. This was caught on a real
#   machine: `djb_main_e991ab50` was a live verifier clone's database and the
#   reaper printed `ORPHAN — --sweep drops it`. The old header even declared
#   the blind spot — and got it wrong twice, scoping it to "another machine"
#   and calling `--sweep` the guard, when `--sweep` is precisely the thing that
#   would have dropped it.
#
#   THE NAME CANNOT BE INVERTED, and that is the whole difficulty. A derived
#   name embeds an 8-hex SHA-256 prefix of the checkout's absolute path
#   (`scripts/db.sh::db_name`), one way. Given `djb_main_e991ab50` there is no
#   arithmetic that yields the directory. Liveness can only ever be established
#   FORWARD — hash a path you can see, and compare. So the question a reaper
#   can honestly answer is not "is this an orphan?" but "can I SEE a checkout
#   that derives this?", and everything else is an absence of evidence.
#
#   FOUR VERDICTS, and only one of them is droppable — by an explicit flag:
#
#     live     the name begins with a base some checkout THIS RUN COULD SEE
#              derives — every worktree of this repository, plus every checkout
#              found under a `--roots` directory. Its test databases, its `_hp`
#              cache, its `_perf` world, all of them. Never touched.
#     IN USE   something is connected to it right now (`pg_stat_activity`).
#              Independent, positive proof of liveness that needs no path at
#              all: a clone mid-test-run is protected even if nothing on disk
#              was scanned. Never touched. (A connection proves life; the
#              absence of one proves nothing — an idle clone is the normal
#              case, and it is exactly the case that was once caught here.)
#     FOREIGN  derivation-shaped, nothing this run could see derives it, nobody
#              is connected. It may be a sibling clone's, another machine's, or
#              a genuinely dead checkout's — AND THIS SCRIPT CANNOT TELL WHICH.
#              `--sweep` alone will NOT drop it. `--sweep --force-foreign`
#              will, after printing every name it is about to drop, because an
#              operator who knows their machine can decide what a hash cannot.
#     REFUSED  everything else, BY NAME. `djb_main`, `djb_verify`, `postgres`,
#              `zitadel` and anything a human named have no `_<8 hex>` tail, so
#              they are not derived names and this mode will not touch them
#              however old they look.
#
#   "I cannot prove it is an orphan" is not "it is an orphan" — the sentence
#   was in this header from the start, and the code did not keep it. It does
#   now: the word ORPHAN is gone, because the script was never in a position to
#   say it.
#
#   EVIDENCE CAN BE ADDED, and that is what `--roots <dir>` is for. Point it at
#   wherever clones of this repository live on this machine and every checkout
#   under it (bounded depth; a directory holding `manage.py` and `.git`, and
#   each one's own worktrees) joins the live set — so a name that was FOREIGN
#   becomes `live` by POSITIVE PROOF rather than by timidity. It is opt-in and
#   there is no default scan: the default path stays exactly as fast and as
#   predictable as it was, and a filesystem walk nobody asked for is not
#   something a broom should do on its own initiative.
#
#   The two flags are required TOGETHER and neither means anything alone (exit
#   2 if one is given without the other): `--all-checkouts` is a scope and
#   `--orphans` is a filter, and a scope that wide with the filter mistyped
#   away would be the widest broom in this repository. `--orphans` keeps its
#   name because it names the INTENT — hunt for orphans — not the verdict.
#
#   DECLARED BLIND SPOTS. (1) A checkout this run could not see is FOREIGN, and
#   FOREIGN is not a finding — it is an absence of one. A machine with clones
#   scattered anywhere but a `--roots` directory will show a wall of FOREIGN,
#   and that is the honest reading: the reaper does not know. `--force-foreign`
#   is the operator's judgement, not the script's, which is why it prints the
#   list first. (2) A checkout that MOVED on disk derives a new name and its old
#   database is a true orphan — and reads FOREIGN, indistinguishable from a
#   sibling clone's. Correct, and now correctly humble. (3) The hashed long form
#   of the probe cache (`<base[:50]>_<8 hex>_hp`, `quality/hotpaths.py::
#   probe_database_name`) is matched by the 50-byte prefix test below; it is
#   unreachable from a derived name anyway, because `scripts/db.sh` caps a base
#   at 51 bytes and the hashing only starts past 60. (4) `--roots` reads the
#   filesystem at a bounded depth; a checkout nested deeper than that under a
#   named root is not found, and is FOREIGN rather than missed silently — the
#   depth is printed with the scope.
#
# TWO REFUSALS, both load-bearing:
#
#   1. A NAME NOT MATCHING A DECLARED PATTERN IS NEVER TOUCHED. There are two,
#      one per population — `test_djb_*` (Django's `test_` prefix on a name
#      `scripts/db.sh` derived) and `djb_*_hp` (the gate's probe cache) — AND
#      the name has to be a name: `[A-Za-z0-9_]`, at most 63 bytes
#      (`db_valid_name`). `djb_main`, `postgres`, `zitadel` and anything a human
#      named are outside both and the script says so and stops. A `--sweep`
#      builds its list from the patterns; a name passed by hand is re-checked
#      against them and against `db_valid_name`.
#   2. A DATABASE WITH A LIVE CONNECTION IS NEVER DROPPED. `pg_stat_activity` is
#      consulted per name, immediately before the drop, and a name with even one
#      session is SKIPPED and reported. This is what stops the broom from
#      manufacturing the cross-talk `db.sh` exists to prevent: another checkout
#      running its suite right now holds its own test database, and holding it
#      is how it says so.
#
# DECLARED RESIDUAL RISK, `--all` only: a checkout that is between two runs
# holds nothing, so its LEFT-BEHIND database and its NOT-YET-USED one look the
# same. Nothing is lost either way — a test database is derived, migrated and
# disposable, and the next run recreates it — but a `--sweep --all` may make
# another checkout's next run pay one database creation. The default scope is
# this checkout precisely so that the wide sweep is a choice somebody made.
#
# There is no `--force`. A live connection is not an obstacle to route around.
#
# BOTH REFUSALS USED TO HOLD BY ACCIDENT (a LOW finding). A name was pasted
# into SQL, so a name carrying a quote composed its own statements, and what
# stopped SEC-1's `--name '... " ; DROP DATABASE "victim'` was not this script
# but `psql -c` wrapping a multi-statement string in one transaction, where
# `DROP DATABASE` refuses to run. SEC-R3 proved the same hole executing a
# `CREATE TABLE` through the `pg_stat_activity` count, which no accident stops.
# Every name now goes to psql as a VARIABLE — `:'name'` for a literal, `:"name"`
# for an identifier — and through `db_valid_name` before that. `scripts/db.sh`
# holds both, and the reasoning.
set -uo pipefail

cd "$(dirname "$0")/.."

# shellcheck source=scripts/db.sh
. scripts/db.sh
# shellcheck source=scripts/lifecycle.sh
. scripts/lifecycle.sh

SWEEP=0
SCOPE_ALL=0
HOT_PATH=0
PERF=0
ALL_CHECKOUTS=0
ORPHANS=0
FORCE_FOREIGN=0
# `LC_ROOTS` and `LC_ROOT_SCAN_DEPTH` belong to the frame (`scripts/lifecycle.sh`)
# — the roots this run was pointed at ARE the evidence its enumerator reasons
# from, so they are held where the enumerator is.
ONE_NAME=""
USAGE="db_sweep.sh takes --sweep, --all, --hot-path, --perf, --name <db>, --all-checkouts --orphans [--roots <dir>] [--force-foreign]"
while [ "$#" -gt 0 ]; do
    case "$1" in
    --sweep) SWEEP=1 ;;
    --all) SCOPE_ALL=1 ;;
    --hot-path) HOT_PATH=1 ;;
    --perf) PERF=1 ;;
    --all-checkouts) ALL_CHECKOUTS=1 ;;
    --orphans) ORPHANS=1 ;;
    --force-foreign) FORCE_FOREIGN=1 ;;
    --roots)
        shift || true
        if [ -z "${1:-}" ]; then
            echo "!! --roots needs a directory: ${USAGE}" >&2
            exit 2
        fi
        if [ ! -d "$1" ]; then
            # Exit 2, not a shrug. A root that is not there was scanned by
            # nobody, and a live set silently missing a root is how a sibling
            # clone becomes FOREIGN when the operator believed it was proven.
            echo "!! --roots ${1} is not a directory. Nothing was scanned, so no name can be" >&2
            echo "   shown to belong to a checkout under it — and this mode must not be asked" >&2
            echo "   to reason from a search that never happened." >&2
            exit 2
        fi
        LC_ROOTS+=("$1")
        ;;
    --name)
        shift || true
        ONE_NAME="${1:-}"
        if [ -z "$ONE_NAME" ]; then
            echo "!! --name needs a database name" >&2
            exit 2
        fi
        ;;
    *)
        echo "!! unknown argument '$1': ${USAGE}" >&2
        exit 2
        ;;
    esac
    shift
done

# The reaper's two flags are one mode. Half of it is never a narrower run of the
# other half — it is the widest scope in this file with its filter missing — so
# it is exit 2 rather than a helpful guess.
if [ "$ALL_CHECKOUTS" -ne "$ORPHANS" ]; then
    echo "!! --all-checkouts and --orphans are one mode and must be given together." >&2
    echo "   --all-checkouts is a scope (every checkout's database on this server) and" >&2
    echo "   --orphans is the filter that makes it safe (only names no live checkout" >&2
    echo "   derives). One without the other is a broom with no handle." >&2
    exit 2
fi
if [ "$ORPHANS" -eq 0 ] && { [ "$FORCE_FOREIGN" -eq 1 ] || [ "${#LC_ROOTS[@]}" -gt 0 ]; }; then
    # Both are answers to a question only the reaper asks. Accepting them
    # elsewhere would let somebody type --force-foreign at the scoped broom and
    # believe they had authorised something; they would have authorised nothing,
    # which is the kind of silence this file refuses everywhere else.
    echo "!! --roots and --force-foreign belong to --all-checkouts --orphans and mean" >&2
    echo "   nothing without it. The scoped brooms above have their own flags." >&2
    exit 2
fi
if [ "$FORCE_FOREIGN" -eq 1 ] && [ "$SWEEP" -eq 0 ]; then
    # --force-foreign is not a census setting. Read the census, then authorise.
    echo "!! --force-foreign is a licence to DROP and means nothing without --sweep." >&2
    echo "   Run the census first, read which names come back FOREIGN, and only then" >&2
    echo "   decide. That order is the whole point of the flag." >&2
    exit 2
fi
if [ "$ORPHANS" -eq 1 ] && { [ -n "$ONE_NAME" ] || [ "$SCOPE_ALL" -eq 1 ]; }; then
    echo "!! --all-checkouts --orphans derives its own population; it cannot be combined" >&2
    echo "   with --name or --all. Run it on its own, read it, then sweep." >&2
    exit 2
fi

# The scope itself is derived from a name, so a name that cannot be one at all
# is refused here rather than reaching a query (the same LOW finding; the gate and
# the reasoning are in `scripts/db.sh`).
if ! db_valid_name "$DATABASE_NAME"; then
    db_refuse_name "$DATABASE_NAME"
    exit 2
fi

# Rule 1, as one function. Anything the broom is ever pointed at goes through it.
#
# TWO conditions, not one. The pattern says which population a name belongs to;
# `db_valid_name` says it is a name at all. SEC-1's injection string
# (`test_djb_..._bait" ; DROP DATABASE "..._victim`) satisfies the *pattern* —
# it starts with `test_djb_` — which is exactly how it reached the server, so a
# refusal built only on the glob is a refusal with a hole in it.
sweepable_name() {
    db_valid_name "$1" || return 1
    case "$1" in
    test_djb_*) return 0 ;;
    *) return 1 ;;
    esac
}

# The second population, by the same two conditions. `djb_main` and anything a
# human named are outside it because they do not end `_hp`, and the `_hp`
# suffix is the gate's own (`quality/hotpaths.py::probe_database_name`), not a
# shape a person picks by accident.
hot_path_name() {
    db_valid_name "$1" || return 1
    case "$1" in
    djb_*_hp) return 0 ;;
    *) return 1 ;;
    esac
}

# The third population, same two conditions. `_perf` is `scripts/perf.sh`'s own
# suffix and that script refuses to point at a name without it, so nothing else
# in this repository wears it.
perf_name() {
    db_valid_name "$1" || return 1
    case "$1" in
    djb_*_perf) return 0 ;;
    *) return 1 ;;
    esac
}

# `_` is a LIKE wildcard and every name here is full of them, so every pattern
# escapes it: the scope must be the names it says, not the names it rhymes with.
escaped_database_name() {
    printf '%s' "${DATABASE_NAME:0:$1}" | sed 's/_/\\_/g'
}

like_pattern() {
    if [ "$SCOPE_ALL" -eq 1 ]; then
        printf 'test\\_djb\\_%%'
    else
        printf 'test\\_%s%%' "$(escaped_database_name 63)"
    fi
}

# `<base>_hp`, and the hashed long form `<base[:50]>_<8 hex>_hp` that
# `probe_database_name` falls back to — so the scoped pattern is the first 50
# bytes of this checkout's name, then anything, then `_hp`.
hot_path_like_pattern() {
    if [ "$SCOPE_ALL" -eq 1 ]; then
        printf 'djb\\_%%\\_hp'
    else
        printf '%s%%\\_hp' "$(escaped_database_name 50)"
    fi
}

# `<base>_perf`, the one `perf.sh` derives. Same shape as the probe cache's.
perf_like_pattern() {
    if [ "$SCOPE_ALL" -eq 1 ]; then
        printf 'djb\\_%%\\_perf'
    else
        printf '%s\\_perf' "$(escaped_database_name 63)"
    fi
}

matching() {
    db_query "SELECT datname FROM pg_database WHERE datname LIKE :'pattern' ORDER BY datname" \
        -v pattern="$1" -tA
}

candidates() {
    if [ -n "$ONE_NAME" ]; then
        printf '%s\n' "$ONE_NAME"
        return
    fi
    if [ "$ORPHANS" -eq 1 ]; then
        matching 'djb\_%'
        matching 'test\_djb\_%'
        return
    fi
    matching "$(like_pattern)"
    matching "$(hot_path_like_pattern)"
    matching "$(perf_like_pattern)"
}

# --- the reaper's derivation: the FRAME's, not this file's any more --------------
#
# `lc_live_bases` / `lc_owning_checkout` / `lc_derived_shape` are in
# `scripts/lifecycle.sh`, sourced above, with the reasoning that used to sit
# here. They are called by name below and nothing here re-derives them.

# `:'name'` and not `'$1'`: the count is asked about a name, and a name that
# closed the quote used to append its own statement to this one — which is the
# form SEC-R3 executed a `CREATE TABLE` through. psql quotes it now.
sessions_on() {
    db_query "SELECT count(*) FROM pg_stat_activity WHERE datname = :'name'" -v name="$1" -tA
}

if [ "$ORPHANS" -eq 1 ]; then
    lc_load_live_bases
    if [ "${#LC_LIVE_BASES[@]}" -eq 0 ]; then
        # Nothing to derive liveness FROM is not "nothing is alive". It is the
        # reaper unable to look, and that is exit 2, before any drop.
        echo "!! git worktree list named no checkout, so no database can be shown to have one." >&2
        echo "   The reaper derives liveness by hashing checkout paths it can see; with none" >&2
        echo "   to hash, every derived name would read as FOREIGN and --force-foreign would" >&2
        echo "   drop the machine. That is the one answer it must never give by accident." >&2
        exit 2
    fi
    echo "scope: every derived-shaped name on this server, asked WHOSE IT IS —"
    echo "       ${#LC_LIVE_BASES[@]} checkout(s) this run can see, and a name none of them derives"
    echo "       is FOREIGN (not an orphan: this script cannot tell those apart)"
    if [ "${#LC_ROOTS[@]}" -gt 0 ]; then
        for root in "${LC_ROOTS[@]}"; do
            echo "       scanned  ${root} (depth ${LC_ROOT_SCAN_DEPTH})"
        done
    else
        echo "       scanned  nothing — only this repository's own worktrees. A sibling"
        echo "                clone elsewhere on this machine reads FOREIGN until --roots"
        echo "                <dir> is pointed at it"
    fi
    for base in "${LC_LIVE_BASES[@]}"; do
        echo "       live  ${base}"
    done
elif [ -n "$ONE_NAME" ]; then
    echo "scope: one name given by hand — ${ONE_NAME}"
elif [ "$SCOPE_ALL" -eq 1 ]; then
    echo "scope: every checkout's on this server — test_djb_*, djb_*_hp and djb_*_perf"
else
    echo "scope: this checkout — test_${DATABASE_NAME}*, ${DATABASE_NAME}*_hp and ${DATABASE_NAME}_perf"
fi
if [ "$SWEEP" -eq 1 ]; then
    [ "$HOT_PATH" -eq 0 ] &&
        echo "note: hot-path probe caches are shown but NOT swept — add --hot-path to drop them"
    [ "$PERF" -eq 0 ] &&
        echo "note: seeded perf worlds are shown but NOT swept — add --perf to drop them"
fi
if [ "$SWEEP" -eq 1 ] && [ "$ORPHANS" -eq 1 ] && [ "$FORCE_FOREIGN" -eq 1 ] && [ "${#LC_ROOTS[@]}" -eq 0 ]; then
    # The exact combination that once produced a real finding, now said out loud
    # instead of discovered afterwards. Not a refusal: an operator who knows
    # their machine holds no other checkout is entitled to say so, and that
    # assertion is what --force-foreign IS. But it is an assertion about the
    # whole machine made from a run that looked at one repository, and the
    # transcript should carry that sentence next to the drops it authorised.
    echo "WARNING: --force-foreign with no --roots. This run can see only this"
    echo "         repository's own worktrees, so every OTHER checkout on this machine —"
    echo "         a sibling clone, a verifier's tree, a colleague's second checkout —"
    echo "         is FOREIGN and is about to be dropped. That is the exact mistake"
    echo "         caught once before (a live clone's database called an orphan)."
    echo "         If any other checkout of this repository exists on this machine,"
    echo "         stop and re-run with --roots <the directory holding it>."
fi
if [ "$SWEEP" -eq 1 ] && [ "$ORPHANS" -eq 1 ] && [ "$FORCE_FOREIGN" -eq 0 ]; then
    echo "note: FOREIGN names are shown but NOT swept. This mode drops nothing on its own"
    echo "      any more: it once called a live sibling clone's database an orphan"
    echo "      and offered to drop it. Prove them live with --roots <dir>, or authorise"
    echo "      the drop with --force-foreign after reading the list."
fi

found=0
dropped=0
skipped=0
foreign=0
# Collected BEFORE the loop, deliberately: `docker compose exec` reads the
# caller's stdin, so a psql call inside a `while read` loop eats the list it is
# walking and the sweep silently stops after the first name. (`db_query` now
# feeds psql its statement on stdin, which closes that hazard from the other
# side too — but the collection stays here, because the reason it was written
# is still true of any psql call that does not go through `db_query`.)
names=()
while IFS= read -r line; do
    [ -n "$line" ] && names+=("$line")
done < <(candidates)

for name in ${names+"${names[@]}"}; do
    found=$((found + 1))
    # The refusal lives in the drop path, not only in the query that fed it:
    # `--name` reaches here without passing either pattern, and this is where
    # `djb_main`, `postgres` or anything a human named is turned away.
    kind=""
    foreign_here=0
    if [ "$ORPHANS" -eq 1 ]; then
        # The reaper's three verdicts, and the safe one is the default: a name
        # this file cannot prove is an orphan is refused, not swept.
        if ! db_valid_name "$name" || ! lc_derived_shape "$name"; then
            echo "  REFUSED  ${name} — not a name this repository derives (djb_<branch>_<8 hex>),"
            echo "                     so nothing here can say whose it is"
            skipped=$((skipped + 1))
            continue
        fi
        if owner="$(lc_owning_checkout "$name")"; then
            echo "  live     ${name} — ${owner} is a checkout this run can see; never touched"
            skipped=$((skipped + 1))
            continue
        fi
        # NOT "orphan". Everything established so far is that no checkout this
        # run could SEE derives this name, and a sibling clone is invisible to a
        # run that was not pointed at it. The verdict is the absence of
        # evidence, and it is spelled that way.
        #
        # AND THE POPULATION IS STILL THE POPULATION. A FOREIGN name that
        # is a WARM CACHE is both things at once, and the reaper used to forget
        # the second half: it forced `kind=foreign` and so walked straight past
        # the `_hp` / `_perf` fences, dropping warm caches on a `--force-foreign`
        # that never mentioned `--hot-path` or `--perf`. The frame
        # (`scripts/sweep.sh`) promises warm is never in the default broom; a
        # delegate that quietly disagreed with that promise is exactly the drift
        # one registry exists to stop. So the kind is kept and `foreign_here`
        # carries the verdict alongside it.
        foreign_here=1
        if hot_path_name "$name"; then
            kind="hot-path"
        elif perf_name "$name"; then
            kind="perf"
        else
            kind="foreign"
        fi
    elif sweepable_name "$name"; then
        kind="test-database"
    elif hot_path_name "$name"; then
        kind="hot-path"
    elif perf_name "$name"; then
        kind="perf"
    else
        echo "  REFUSED  ${name} — none of a derived test database (test_djb_*), a hot-path"
        echo "                     probe cache (djb_*_hp) or a perf world (djb_*_perf), or"
        echo "                     not a name ([A-Za-z0-9_])"
        skipped=$((skipped + 1))
        continue
    fi
    live="$(sessions_on "$name")"
    if [ "${live:-0}" != "0" ]; then
        echo "  IN USE   ${name} — ${live} live session(s), left alone"
        skipped=$((skipped + 1))
        continue
    fi
    if [ "$foreign_here" -eq 1 ]; then
        # ALWAYS PRINTED, including on the run that is about to drop it. The
        # header promises this mode names what it destroys BEFORE destroying it,
        # and a DROPPED line after the fact is not that promise: an operator
        # reading a --force-foreign transcript sees the claim and the reason
        # first, then the consequence, and can stop at the first surprise.
        foreign=$((foreign + 1))
        echo "  FOREIGN  ${name} — no checkout this run could see derives it, and nobody is"
        echo "                     connected. It may be a sibling clone's, another machine's,"
        echo "                     or a dead checkout's — this script cannot tell which."
        if [ "$SWEEP" -eq 0 ] || [ "$FORCE_FOREIGN" -eq 0 ]; then
            # The correction this class of finding bought: --sweep alone no longer drops this.
            echo "                     --roots <dir> to prove it live; --sweep --force-foreign to drop"
            case "$kind" in
            hot-path) echo "                     (and it is a WARM CACHE — --hot-path is needed as well)" ;;
            perf) echo "                     (and it is a WARM CACHE — --perf is needed as well)" ;;
            esac
            skipped=$((skipped + 1))
            continue
        fi
        # THE WARM FENCE, BEFORE THE PROMISE AND NOT AFTER IT. Saying
        # "DROPPING it on the operator's word" and then skipping is a transcript
        # that lies about what it did — worse than either outcome on its own.
        if { [ "$kind" = "hot-path" ] && [ "$HOT_PATH" -eq 0 ]; } ||
            { [ "$kind" = "perf" ] && [ "$PERF" -eq 0 ]; }; then
            echo "  warm     ${name} — FOREIGN, and a warm cache; --force-foreign does not"
            echo "                     reach one on its own. Add --hot-path or --perf."
            skipped=$((skipped + 1))
            continue
        fi
        echo "                     --force-foreign given: DROPPING it on the operator's word"
    fi
    if [ "$kind" = "hot-path" ] && { [ "$SWEEP" -eq 0 ] || [ "$HOT_PATH" -eq 0 ]; }; then
        # Visible, and deliberately not dropped: it is a warm cache, not a leak.
        # AFTER the FOREIGN block, not before it: a FOREIGN warm cache owes the
        # reader both sentences, and the claim comes before the fence.
        echo "  warm     ${name} — hot-path probe cache (rule 35); --sweep --hot-path drops it"
        skipped=$((skipped + 1))
        continue
    fi
    if [ "$kind" = "perf" ] && { [ "$SWEEP" -eq 0 ] || [ "$PERF" -eq 0 ]; }; then
        # Same reasoning as the probe cache, and ~0.6 GB more of it.
        echo "  warm     ${name} — seeded perf world (ADR perf-1); --sweep --perf drops it"
        skipped=$((skipped + 1))
        continue
    fi
    if [ "$SWEEP" -eq 0 ]; then
        echo "  idle     ${name}"
        continue
    fi
    if db_query 'DROP DATABASE :"name"' -v name="$name" >/dev/null; then
        echo "  DROPPED  ${name}"
        dropped=$((dropped + 1))
    else
        echo "  FAILED   ${name} — see the psql error above"
        skipped=$((skipped + 1))
    fi
done

if [ "$found" -eq 0 ]; then
    echo "  (none)"
fi
echo "census: ${found} found · ${dropped} dropped · ${skipped} left alone"
if [ "$ORPHANS" -eq 1 ] && [ "$foreign" -gt 0 ]; then
    # Counted and printed, so "left alone" cannot be read as "all accounted
    # for". A FOREIGN name is an open question, and the summary says how many
    # questions are open rather than burying them in the skipped total.
    echo "        ${foreign} FOREIGN — this run could not say whose they are. That is an"
    echo "        absence of evidence, not a finding: point --roots at wherever clones of"
    echo "        this repository live, or --sweep --force-foreign to drop them by hand."
fi
