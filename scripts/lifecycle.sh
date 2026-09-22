#!/usr/bin/env bash
# THE CHECKOUT-MACHINERY LIFECYCLE REGISTRY, and the one live-checkout
# enumerator every class reads liveness from.
#
#   source scripts/lifecycle.sh
#
# This file is SOURCED. It is not an instrument; it is what the instruments
# (`scripts/sweep.sh`, `scripts/db_sweep.sh`, `scripts/temporal_sweep.sh`) agree
# about, in one place, so that they cannot come to disagree.
#
# WHY IT EXISTS. The leak this file diagnosed is not a missing reaper: it is a
# LIFETIME-CLASS MISMATCH minted at creation. A Temporal Schedule is infinitely
# durable by construction; the worker keys it to an identity that is ephemeral
# by construction (the checkout-path hash in the queue name). Durable object,
# mortal identity. `apps/workflows` fixes the creation half. This is
# the destroy half, and its first duty is to be able to SAY WHAT EXISTS —
# because a broom whose population is a list somebody typed goes stale the day
# a tenth kind of thing is created, silently, exactly like the ninth did.
#
# SO THE REGISTRY IS THE POPULATION. House rule 20's logic, applied to
# machinery: a class is not a name in a comment, it is a DECLARATION, and the
# census is derived from the declarations rather than from anybody's memory.
# Every class declares six things:
#
#   name             what it is called, here and in every transcript
#   identity         HOW THE CHECKOUT APPEARS IN IT — the branch and the 8-hex
#                    path digest `scripts/db.sh::db_name` derives, and where in
#                    the string they sit
#   enumerate        the SERVER-SIDE pattern scan that finds every instance.
#                    Server-side, never a local list: a thing this checkout
#                    forgot it made is exactly the thing being hunted
#   liveness         the POSITIVE evidence that something is using it now
#   destroy          the verb, and who owns it
#   warm             whether it is a WARM CACHE — never in the default broom
#
# A class with an empty field is refused (`lc_registry_check`): a declaration
# that does not say how to enumerate its class is a class nothing enumerates.
#
# THE ONE ENUMERATOR. Every verdict in every class is read off ONE answer to
# one question — WHICH CHECKOUTS CAN THIS RUN SEE? — computed once here from
# `git worktree list` (which, from any linked worktree, reports the main clone
# and all its siblings) plus whatever `--roots <dir>` was pointed at. It moved
# here from `scripts/db_sweep.sh`, which wrote it and still uses it: two copies
# of a liveness derivation is two answers to "is this alive", and the second one
# is the one nobody read.
#
# THE DERIVATION CANNOT BE INVERTED, which is the whole difficulty and is
# `db_sweep.sh`'s finding, restated because everything here rests on it. A
# derived name embeds the first 8 hex digits of the SHA-256 of the checkout's
# absolute path, one way. Given `djb_main_e991ab50` there is no arithmetic that
# yields the directory. Liveness is therefore only ever established FORWARD —
# hash a path this run can SEE, and compare — so the honest question is never
# "is this an orphan?" but "can I see a checkout that derives this?", and
# everything else is an absence of evidence.
#
# FOUR VERDICTS, frame-wide, promoted from `db_sweep.sh`'s reaper because every
# class has exactly the same epistemic situation:
#
#   live     a checkout THIS RUN CAN SEE derives the identity. Never destroyed
#            unless it is THIS checkout's own (`sweep.sh` prints which).
#   IN USE   positive, independent proof of use RIGHT NOW — a `pg_stat_activity`
#            session, a task-queue poller, a live parent pid. Needs no path at
#            all, and outranks the absence of one. Never destroyed.
#            (Presence proves life; ABSENCE PROVES NOTHING — an idle checkout is
#            the normal case.)
#   FOREIGN  identity-shaped, no visible checkout derives it, nothing proves it
#            in use. It may be a sibling clone's, another machine's, or a
#            genuinely dead checkout's — AND NOTHING HERE CAN TELL WHICH.
#            `--sweep` alone will not touch it; `--sweep --force-foreign` will,
#            after printing every name.
#   REFUSED  not an identity this repository derives at all — `djb_main`,
#            `djb_verify`, `postgres`, `events-purge-expired:djb-provefinal`,
#            anything a human named. Never touched however old it looks.
#
# AND A FIFTH OUTCOME THAT IS NOT A VERDICT: UNRECOGNIZED, exit 2. An instance
# that carries a checkout-derived identity — so it is demonstrably OURS — and
# that no declared class claims. Could-not-judge outranks a pass, so machinery
# class N+1 reddens the census the day it first exists rather than accumulating
# invisibly for a cycle. That is the property this whole file is for.
#
# THE SEAM IS THE PATTERN, NOT THE CODE. Nothing here imports `apps/workflows`
# or `apps/events`, and it must not: the census has to be able to see machinery
# left behind by a checkout that no longer exists, whose code is gone. Every
# enumerator is a server-side scan by pattern — `pg_catalog`, `temporal schedule
# list`, `temporal workflow list`, the process table.

# Sourcing twice is stable: the second source is a no-op. `db_sweep.sh` sources
# this and `sweep.sh` sources both, and a second pass through `scripts/db.sh`'s
# pin-disagreement notice would print the same warning twice.
if [ -n "${DJB_LIFECYCLE_SOURCED:-}" ]; then
    return 0 2>/dev/null || true
fi
DJB_LIFECYCLE_SOURCED=1

# `scripts/db.sh` owns `db_path_hash`, `db_valid_name`, `db_query` and the
# reasoning behind all three.
#
# THE GUARD IS "IS THE FUNCTION HERE", NOT "IS DATABASE_NAME SET". Those are not
# the same question and the difference is a real bug that was here for an hour:
# `db.sh` EXPORTS `DATABASE_NAME` and `POSTGRES_USER`, so a child process of
# anything that sourced it inherits both while inheriting none of the functions
# — and a guard reading the variables skipped the source and left every caller
# with `db_valid_name: command not found`. Sourcing again is safe by `db.sh`'s
# own rule 1: a name already in the environment wins, so the second source
# honours the first one's export.
if ! declare -F db_valid_name >/dev/null 2>&1; then
    # shellcheck source=scripts/db.sh
    . "$(dirname "${BASH_SOURCE[0]}")/db.sh"
fi

# --- the one live-checkout enumerator ----------------------------------------

# How deep a `--roots` scan looks for a checkout. Three is enough for the shapes
# that occur — `<root>/<clone>`, `<root>/<group>/<clone>`, and a clone's own
# `.claude/worktrees/<x>` is reached through its worktree list rather than by
# the walk — and a bound is what keeps a mistyped `--roots /` from walking the
# disk. It is printed with the scope so a miss is readable, not silent.
LC_ROOT_SCAN_DEPTH="${DJB_SWEEP_ROOT_DEPTH:-3}"

# The base database name every worktree of ONE repository derives, one per line.
# It is `scripts/db.sh::db_name`'s arithmetic applied to a path and a branch this
# process did not `cd` into — the same 38-byte branch cap, the same path hash —
# so a name derived here and a name derived there are the same name.
#
# `git -C` and not a `cd`: this is called once for this repository and once for
# every clone a `--roots` scan turned up, and a function that changed the working
# directory would be a different function on its second call.
lc_bases_for_repo() {
    local repo="$1" path="" branch="" sanitised
    while IFS= read -r line; do
        case "$line" in
        "worktree "*)
            path="${line#worktree }"
            branch=""
            ;;
        "branch refs/heads/"*)
            branch="${line#branch refs/heads/}"
            ;;
        "detached") branch="" ;;
        "")
            [ -n "$path" ] || continue
            # A detached checkout derives `main`, exactly as db_name does.
            [ -n "$branch" ] || branch="main"
            sanitised="$(printf '%s' "$branch" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_' '_')"
            sanitised="${sanitised:0:38}"
            [ -n "$sanitised" ] || sanitised="main"
            printf 'djb_%s_%s\n' "$sanitised" "$(db_path_hash "$path")"
            path=""
            branch=""
            ;;
        esac
    done < <(git -C "$repo" worktree list --porcelain 2>/dev/null)
}

# Every CHECKOUT OF THIS REPOSITORY under a `--roots` directory. A
# checkout is a directory holding both `manage.py` and a `.git` — the same pair
# `deploy/observability/alerts/census.py::repo_root` uses to recognise this tree,
# and the same pair `git rev-parse --show-toplevel` will agree with.
#
# WHY A SCAN AT ALL, when the derived name cannot be inverted: because the hash
# is one-way in only one direction. Hashing a path this run can SEE and matching
# it forward is cheap, and it is the only way a FOREIGN identity can be promoted
# to `live` by evidence rather than by assumption.
lc_checkouts_under() {
    local root="$1" manage top
    while IFS= read -r manage; do
        top="$(dirname "$manage")"
        [ -e "$top/.git" ] || continue
        # Its own idea of where it starts, so a symlinked root and a real one
        # hash to the same string db.sh would have derived in that tree.
        top="$(git -C "$top" rev-parse --show-toplevel 2>/dev/null || true)"
        [ -n "$top" ] && printf '%s\n' "$top"
    done < <(find "$root" -maxdepth "$LC_ROOT_SCAN_DEPTH" -name manage.py -type f 2>/dev/null)
}

# The whole live set: this repository's worktrees, plus every worktree of every
# checkout found under each declared root. Duplicates are harmless — the set is
# only ever asked "does any base own this identity?".
#
# Roots arrive in LC_ROOTS, set by the caller's flag parsing.
LC_ROOTS=()
lc_live_bases() {
    lc_bases_for_repo .
    local root top
    for root in ${LC_ROOTS+"${LC_ROOTS[@]}"}; do
        while IFS= read -r top; do
            lc_bases_for_repo "$top"
        done < <(lc_checkouts_under "$root")
    done
}

# Computed ONCE per run into LC_LIVE_BASES. Every class asks this array; nothing
# re-derives it. An empty answer is exit 2 at the caller, never "nothing is
# alive" — see `lc_require_live_bases`.
LC_LIVE_BASES=()
lc_load_live_bases() {
    local base
    LC_LIVE_BASES=()
    while IFS= read -r base; do
        [ -n "$base" ] && LC_LIVE_BASES+=("$base")
    done < <(lc_live_bases)
}

# Does this name have the SHAPE `scripts/db.sh` derives — `djb_<branch>_<8 hex>`,
# with or without a suffix after it? A name without that tail was not derived by
# this repository and nothing here reasons about whose it is.
#
# (Under LC_ALL=C in a subshell: a glob range under a UTF-8 collation matches
# letters nobody typed, and this file may not change the caller's environment.
# Same reasoning as `db_valid_name`.)
lc_derived_shape() {
    local name="${1#test_}"
    (
        LC_ALL=C
        case "$name" in
        djb_*_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) exit 0 ;;
        djb_*_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]_*) exit 0 ;;
        esac
        exit 1
    )
}

# Whose is it? An identity belongs to a live checkout when it BEGINS with that
# checkout's derived base — which covers the base itself, `test_<base>`, the
# `_gwN` workers, `<base>_hp`, `<base>_perf` and `<base>_drill` without this
# function having to know that list. The 50-byte prefix is the hashed long form
# of the probe cache (`quality/hotpaths.py::probe_database_name`).
lc_owning_checkout() {
    local name="${1#test_}" base
    for base in ${LC_LIVE_BASES+"${LC_LIVE_BASES[@]}"}; do
        case "$name" in
        "$base"*)
            printf '%s' "$base"
            return 0
            ;;
        esac
        case "$name" in
        "${base:0:50}"*)
            printf '%s' "$base"
            return 0
            ;;
        esac
    done
    return 1
}

# A Temporal task queue is the database name with `djb_` swapped for `djb-`
# (`config/settings/base.py::TEMPORAL_TASK_QUEUE`), so one function maps a queue
# back onto the identity every other class is judged by. A queue that is not
# `djb-*` was not derived here and is refused rather than guessed at.
lc_queue_base() {
    case "${1:-}" in
    djb-*) printf 'djb_%s' "${1#djb-}" ;;
    *) return 1 ;;
    esac
}

# --- the four verdicts, once ---------------------------------------------------
#
# Order is `db_sweep.sh`'s and is load-bearing: REFUSED before anything (a name
# outside the derivation is never reasoned about), then `live` (a path this run
# hashed), then IN USE (independent positive proof), and FOREIGN last as the
# residue — the absence of evidence, never a finding.
#
# $1 identity · $2 count of live-use evidence (0 or more)
lc_verdict() {
    local identity="$1" inuse="${2:-0}"
    if ! db_valid_name "${identity#test_}" || ! lc_derived_shape "$identity"; then
        printf 'REFUSED'
        return 0
    fi
    if lc_owning_checkout "$identity" >/dev/null; then
        printf 'live'
        return 0
    fi
    if [ "$inuse" != "0" ]; then
        printf 'IN USE'
        return 0
    fi
    printf 'FOREIGN'
}

# --- may this be destroyed? ONE function, and everything asks it ---------
#
# THE DEFECT THIS EXISTS TO CLOSE. The verdict was computed once and correctly,
# printed correctly — `live … (THIS CHECKOUT)` — and then the destroy path made
# its OWN decision a few lines further down, out of the same `case` arm, by
# falling through. Two decisions, one of them implicit and none of them written
# anywhere a reader could check. Two of the owner's first real sweep's 119 kills
# were a live checkout's working database and one of its running executions.
#
# So the decision is a FUNCTION now, it is the only one, and both the line that
# is printed and the act that follows read the same answer from it.
#
#   $1 class · $2 verdict · $3 mine (1 when this checkout derives the identity)
#
# Prints `<licence>|<reason>`:
#
#   own|      destroyable by `--sweep` — this checkout's own, and its class is
#             declared disposable
#   foreign|  destroyable by `--sweep --force-foreign` — nobody visible owns it
#   none|why  not destroyable by anything this run can type
#
# The licence is what may be destroyed AT ALL. Whether the caller ASKED for it —
# `--sweep`, `--force-foreign`, `--hot-path`, `--perf` — is the caller's own gate
# on top, and never a way around this one.
lc_destroy_decision() {
    local class="$1" verdict="$2" mine="${3:-0}"
    case "$verdict" in
    REFUSED)
        printf 'none|it is not an identity this repository derives, so nothing can say whose it is'
        ;;
    "IN USE")
        printf 'none|something is using it right now'
        ;;
    FOREIGN)
        printf 'foreign|'
        ;;
    live)
        if [ "$mine" != "1" ]; then
            printf 'none|another checkout this run can see owns it'
            return 0
        fi
        # `yes*` and not `yes`: the column carries its reason after the colon,
        # exactly as the warm column does, so the declaration reads as a
        # sentence and the test stays on the first word.
        case "$(lc_field "$class" 8)" in
        yes*) printf 'own|' ;;
        *) printf 'none|this checkout owns it, and %s is declared NOT disposable — it is a working set, not a leftover' "$class" ;;
        esac
        ;;
    *)
        printf 'none|%s is not a verdict this frame knows' "$verdict"
        ;;
    esac
}

# --- the registry ---------------------------------------------------------------
#
# One record per class, nine fields: the seven declared columns, plus the KIND
# (which server-side scan produces it) and the CLAIM function (does this class
# recognise this instance's shape). Order within a kind is specificity order —
# the first class that claims an instance owns it — so `test_djb_x_hp` is a test
# database and not a probe cache.
#
# THE SEVENTH COLUMN, `disposable`, WAS BOUGHT WITH A REAL DATABASE.
# `live` answers WHOSE a thing is. It does not answer whether the thing is a
# LEFTOVER or a WORKING SET, and for a while nothing did: the own-tree broom
# reached everything this checkout owned, so `--sweep` from the main checkout
# destroyed that checkout's live development database and one of its running
# workflow executions — both correctly printed `live … (THIS CHECKOUT)` one line
# before they died. Whose it is and whether it is recreatable are two questions,
# and the second one belongs to the CLASS, declared here, next to everything
# else the class declares:
#
#   yes  an instance is derived, disposable and recreated on demand — a test
#        database, a warm cache, a restore-drill scratch, a schedule the worker
#        re-declares at startup. This checkout's own may be swept.
#   no   an instance IS the working set — the checkout's own database, a
#        running execution. Nothing sweeps one while its checkout is alive.
#
# It gates the `live`-and-mine path ONLY. A FOREIGN instance belongs to a
# checkout nobody can see, and a dead checkout's working database is garbage by
# definition — `--force-foreign` still takes it.
#
# NINE PARALLEL ARRAYS AND NOT ONE `|`-JOINED STRING, and the reason is
# measured. The joined form meant every field read was a `printf | cut`,
# which is two forks; `lc_class_of` did three of them per class per instance, so
# one census of this machine — 82 databases against nine classes, then 136 open
# executions — spent about twenty of its twenty-six seconds forking `cut`. A
# gate leg is not allowed to cost that, and neither is a census people are meant
# to run before every wave. Parallel arrays index in the shell, fork nothing,
# and bash 3.2 (macOS) has no associative arrays to do it more prettily.
LC_CLASS_NAME=()
LC_CLASS_KIND=()
LC_CLASS_IDENTITY=()
LC_CLASS_ENUMERATE=()
LC_CLASS_LIVENESS=()
LC_CLASS_DESTROY=()
LC_CLASS_WARM=()
LC_CLASS_DISPOSABLE=()
LC_CLASS_CLAIM=()
# A TENTH PARALLEL ARRAY AND IT IS NOT A COLUMN. Where the declaration came
# from — empty for the built-ins below, the drawer file's path for a product's.
# It is never a field a declaration can set, because the whole value of it is
# that a refusal can name a file whose author is not in this repository, and a
# declaration that could name its own source could name the wrong one.
LC_CLASS_SOURCE=()
LC_CLASS_DECLARED_IN=""

lc_class() {
    LC_CLASS_NAME+=("$1")
    LC_CLASS_KIND+=("$2")
    LC_CLASS_IDENTITY+=("$3")
    LC_CLASS_ENUMERATE+=("$4")
    LC_CLASS_LIVENESS+=("$5")
    LC_CLASS_DESTROY+=("$6")
    LC_CLASS_WARM+=("$7")
    LC_CLASS_DISPOSABLE+=("$8")
    LC_CLASS_CLAIM+=("$9")
    LC_CLASS_SOURCE+=("${LC_CLASS_DECLARED_IN}")
}

# lc_class_where <class> — "the built-in registry", or the drawer file that
# declared it. One sentence, for a refusal to end with.
lc_class_where() {
    local want="$1" i=0
    while [ "$i" -lt "${#LC_CLASS_NAME[@]}" ]; do
        if [ "${LC_CLASS_NAME[$i]}" = "$want" ]; then
            if [ -n "${LC_CLASS_SOURCE[$i]}" ]; then
                printf '%s' "${LC_CLASS_SOURCE[$i]}"
            else
                printf '%s' "the built-in registry (scripts/lifecycle.sh)"
            fi
            return 0
        fi
        i=$((i + 1))
    done
    printf '%s' "nowhere this run can name"
}

lc_classes() {
    local i=0
    while [ "$i" -lt "${#LC_CLASS_NAME[@]}" ]; do
        printf '%s\n' "${LC_CLASS_NAME[$i]}"
        i=$((i + 1))
    done
}

# lc_classes_of_kind <kind> — the classes of one kind, in declaration order
# (which is specificity order). It exists so a census that walks one kind walks
# THE REGISTRY rather than a second list beside it: `scripts/sweep.sh` kept one,
# and its own comment says what that costs — "a class the registry knows and
# this list does not is invisible in every transcript while being exempt from
# the UNRECOGNIZED check that exists to catch exactly that". A product's class
# arrives in the registry and in no hand list anywhere, so the second list stops
# being a maintenance risk and becomes a guarantee that the drawer does nothing.
lc_classes_of_kind() {
    local want="$1" i=0
    while [ "$i" -lt "${#LC_CLASS_NAME[@]}" ]; do
        [ "${LC_CLASS_KIND[$i]}" != "$want" ] || printf '%s\n' "${LC_CLASS_NAME[$i]}"
        i=$((i + 1))
    done
}

# lc_field <class> <1..9>: name kind identity enumerate liveness destroy warm
#                          disposable claim
lc_field() {
    local want="$1" index="$2" i=0
    while [ "$i" -lt "${#LC_CLASS_NAME[@]}" ]; do
        if [ "${LC_CLASS_NAME[$i]}" = "$want" ]; then
            case "$index" in
            1) printf '%s' "${LC_CLASS_NAME[$i]}" ;;
            2) printf '%s' "${LC_CLASS_KIND[$i]}" ;;
            3) printf '%s' "${LC_CLASS_IDENTITY[$i]}" ;;
            4) printf '%s' "${LC_CLASS_ENUMERATE[$i]}" ;;
            5) printf '%s' "${LC_CLASS_LIVENESS[$i]}" ;;
            6) printf '%s' "${LC_CLASS_DESTROY[$i]}" ;;
            7) printf '%s' "${LC_CLASS_WARM[$i]}" ;;
            8) printf '%s' "${LC_CLASS_DISPOSABLE[$i]}" ;;
            9) printf '%s' "${LC_CLASS_CLAIM[$i]}" ;;
            *) return 1 ;;
            esac
            return 0
        fi
        i=$((i + 1))
    done
    return 1
}

# lc_claim_matches <claim> <instance> — the claim column, applied.
#
# TWO FORMS, AND THE SECOND ONE IS WHAT MAKES A DRAWER POSSIBLE. A built-in
# names a FUNCTION, because a built-in's claim is real reasoning — `db_valid_name`
# first, then a shape, in specificity order. A product's class arrives in a
# drawer that is DECLARATION-ONLY (`lc_local_declaration_only` below refuses a
# function definition in it, and the reason is written there), so it cannot
# bring a function with it; it declares `glob:<pattern>` instead and the pattern
# is matched by the shell.
#
# THE PATTERN IS DELIBERATELY UNQUOTED in the `case` below — that is what makes
# it a pattern rather than a literal, and it is the whole point of the form. It
# is read from a file in this checkout, by a library this checkout sources; a
# product that can write that file can already write anything else in
# `scripts/local/`, so this is not a new trust boundary, and `case` expands no
# command substitution in any event.
lc_claim_matches() {
    local claim="$1" instance="$2" pattern
    case "$claim" in
    glob:*)
        pattern="${claim#glob:}"
        [ -n "$pattern" ] || return 1
        # shellcheck disable=SC2254
        case "$instance" in
        $pattern) return 0 ;;
        esac
        return 1
        ;;
    esac
    "$claim" "$instance"
}

# Which class claims this instance? Prints the class name, or nothing.
# $1 kind · $2 instance identity string
lc_class_of() {
    local kind="$1" instance="$2" i=0
    while [ "$i" -lt "${#LC_CLASS_NAME[@]}" ]; do
        if [ "${LC_CLASS_KIND[$i]}" = "$kind" ] && lc_claim_matches "${LC_CLASS_CLAIM[$i]}" "$instance"; then
            printf '%s' "${LC_CLASS_NAME[$i]}"
            return 0
        fi
        i=$((i + 1))
    done
    return 1
}

# Every declaration says all seven things, or the registry is refused. A class
# that does not say how it is enumerated is a class nothing enumerates, and a
# census built on one is a census with a hole nobody can see.
lc_registry_check() {
    local i=0 j value name broken=0 line
    # A DRAWER FILE THIS RUN REFUSED TO SOURCE IS A REGISTRY DEFECT, reported
    # here and nowhere else. It cannot be an `exit` at source time: this file is
    # a LIBRARY and the instruments that source it own their exit statuses
    # (`scripts/sweep.sh` calls this at its own precondition and turns a false
    # into its own could-not-look). A refusal that killed the caller's shell
    # from inside a `source` would take the decision away from the one place
    # that is allowed to make it.
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "!! lifecycle registry: ${line}" >&2
        broken=1
    done <<EOF
${LC_LOCAL_DEFECTS:-}
EOF
    while [ "$i" -lt "${#LC_CLASS_NAME[@]}" ]; do
        name="${LC_CLASS_NAME[$i]}"
        for j in 1 2 3 4 5 6 7 8 9; do
            value="$(lc_field "$name" "$j")"
            if [ -z "$value" ]; then
                echo "!! lifecycle registry: class '${name}' declares nothing in column ${j} — declared in $(lc_class_where "$name")." >&2
                broken=1
            fi
        done
        value="${LC_CLASS_CLAIM[$i]}"
        case "$value" in
        glob:?*) ;;
        glob:*)
            echo "!! lifecycle registry: class '${name}' declares an empty claim pattern — declared in $(lc_class_where "$name")." >&2
            broken=1
            ;;
        *)
            if ! declare -F "$value" >/dev/null 2>&1; then
                echo "!! lifecycle registry: class '${name}' names claim function '${value}', which does not exist — declared in $(lc_class_where "$name")." >&2
                broken=1
            fi
            ;;
        esac
        i=$((i + 1))
    done
    [ "$broken" -eq 0 ]
}

# --- the claim functions -------------------------------------------------------
#
# A claim answers ONE question — "is this MY KIND of thing" — and never "whose
# is it". The two are separate on purpose: `djb_main_hp` IS a hot-path probe
# cache (claimed) whose identity this repository cannot derive (REFUSED), and
# collapsing the two questions is how a legacy name would end up either
# unrecognised or swept.

lc_claim_test_database() {
    db_valid_name "$1" || return 1
    case "$1" in
    test_djb_*) return 0 ;;
    esac
    return 1
}

lc_claim_hot_path_cache() {
    db_valid_name "$1" || return 1
    case "$1" in
    djb_*_hp) return 0 ;;
    esac
    return 1
}

lc_claim_perf_world() {
    db_valid_name "$1" || return 1
    case "$1" in
    djb_*_perf) return 0 ;;
    esac
    return 1
}

lc_claim_restore_drill_database() {
    db_valid_name "$1" || return 1
    case "$1" in
    djb_*_drill) return 0 ;;
    esac
    return 1
}

# The checkout's own working database: the derived base and NOTHING after it.
# `db_name`'s output exactly, which is what makes every other database class a
# suffix on this one.
lc_claim_checkout_database() {
    db_valid_name "$1" || return 1
    (
        LC_ALL=C
        case "$1" in
        djb_*_[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) exit 0 ;;
        esac
        exit 1
    )
}

# A durable Schedule is `<some prefix>:<task queue>` — the shape every
# `SCHEDULES` entry in this repository builds (`apps/events/activities.py`,
# `apps/workflows/activities.py`). The class is claimed by the SHAPE and not by
# the prefix list: a fourth periodic sweep is a new INSTANCE of this class, not
# a new class, and the census must not go red for one.
# THE MIGRATION TEMPLATE — and it is a class of its own for one
# reason: it is the only database here that is MACHINE-GLOBAL. `djb_tmpl_<16 hex
# of the migration-set digest>` belongs to no checkout, carries no checkout's
# path hash, and is what every checkout on this box clones its own database
# FROM. A broom that read it as some dead worktree's leftovers would drop the
# one object the whole mechanism rests on, so the shape is claimed here rather
# than left to read as UNRECOGNIZED (exit 2) or, worse, to be swallowed by
# widening `lc_claim_checkout_database`. The build scratch
# (`djb_tmpl_<key>_mk<6 hex>`) is the same class: it is a refresh in flight, and
# a census that could not name it could not say whether to wait or to sweep.
#
# It is DISPOSABLE and it is WARM in the sense that matters: dropping one costs
# the next checkout one slow `migrate` and nothing else, and `db_template_refresh`
# rebuilds it on demand. Nothing in it is data.
lc_claim_migration_template() {
    db_valid_name "${1:-}" || return 1
    case "$1" in
    djb_tmpl_*) return 0 ;;
    esac
    return 1
}

lc_claim_schedule() {
    case "${1:-}" in
    *:djb-*) return 0 ;;
    esac
    return 1
}

# An open execution's identity is the queue it was dispatched to, which arrives
# already separated by the enumerator.
lc_claim_open_execution() {
    case "${1:-}" in
    djb-*) return 0 ;;
    esac
    return 1
}

lc_claim_task_queue() {
    case "${1:-}" in
    djb-*) return 0 ;;
    esac
    return 1
}

# A test-server process carries NO checkout identity — see the declaration.
lc_claim_test_server_process() {
    case "${1:-}" in
    temporal-test-server*) return 0 ;;
    esac
    return 1
}

# --- the declarations ------------------------------------------------------------
#
#         name . kind . identity . enumerate . liveness . destroy . warm . disposable . claim
lc_class "migration-template" "database" "djb_tmpl_<16 hex of the migration-set digest> (machine-global, owned by no checkout), plus a refresh in flight as djb_tmpl_<key>_mk<6 hex>" "pg_catalog: datname LIKE djb\\_tmpl\\_%" "pg_stat_activity sessions on it — a PUBLISHED one allows no connections and can never have any, which is what makes concurrent clones safe; a build scratch can" "scripts/db.sh::db_template_prune, which is db_template_refresh's own housekeeping — no broom here can reach it" "yes: it IS the warm start, and its fence is stronger than a flag — the name carries no checkout path hash, so lc_derived_shape says no, every verdict is REFUSED and lc_destroy_decision hands out 'none' even under --force-foreign (driven and proven)" "yes: dropping one costs the next checkout one slow migrate; scripts/db.sh::db_template_refresh rebuilds it and nothing in it is data" lc_claim_migration_template
lc_class "checkout-database" "database" "djb_<branch>_<8 hex of the checkout path>" "pg_catalog: datname LIKE djb\\_%" "pg_stat_activity sessions on it" "scripts/db.sh::db_drop (DROP DATABASE)" "no" "no: it IS this checkout's working database" lc_claim_checkout_database
lc_class "test-database" "database" "test_ + the derived base + optional _gwN" "pg_catalog: datname LIKE test\\_djb\\_%" "pg_stat_activity sessions on it" "scripts/db_sweep.sh --sweep --name <n>" "no" "yes: per run, per worker; the next run creates and migrates its own" lc_claim_test_database
lc_class "hot-path-cache" "database" "the derived base + _hp (rule 35's probe cache)" "pg_catalog: datname LIKE djb\\_%\\_hp" "pg_stat_activity sessions on it" "scripts/db_sweep.sh --sweep --hot-path --name <n>" "yes: --hot-path" "yes: rule 35 recreates it on demand" lc_claim_hot_path_cache
lc_class "perf-world" "database" "the derived base + _perf (ADR perf-1's seeded world)" "pg_catalog: datname LIKE djb\\_%\\_perf" "pg_stat_activity sessions on it" "scripts/db_sweep.sh --sweep --perf --name <n>" "yes: --perf" "yes: re-seeded by scripts/perf.sh (minutes, not data)" lc_claim_perf_world
lc_class "restore-drill-database" "database" "the derived base + _drill (restore_drill.sh's scratch)" "pg_catalog: datname LIKE djb\\_%\\_drill" "pg_stat_activity sessions on it" "scripts/db.sh::db_drop (DROP DATABASE)" "no" "yes: restore_drill.sh creates and drops it every run" lc_claim_restore_drill_database
lc_class "task-queue" "task-queue" "djb-<branch>_<8 hex> (the base with djb_ swapped for djb-)" "the queues named by every schedule and every open execution (Temporal exposes no ListTaskQueues)" "DescribeTaskQueue pollers (positive only)" "none: a queue is not an object; it is gone when its last schedule and execution are" "no" "no: nothing to dispose of; it has no destroy verb" lc_claim_task_queue
lc_class "schedule" "schedule" "<prefix>:djb-<branch>_<8 hex> in the schedule id" "temporal schedule list" "DescribeTaskQueue pollers on its queue (positive only)" "temporal schedule delete --schedule-id <id>" "no" "yes: the worker re-declares it at startup (ADR platform-lifecycle-1)" lc_claim_schedule
lc_class "open-execution" "open-execution" "djb-<branch>_<8 hex> as the execution's task queue" "temporal workflow list --query ExecutionStatus=Running" "DescribeTaskQueue pollers on its queue (positive only)" "temporal workflow terminate --workflow-id <id>" "no" "no: it is work that is RUNNING, not a leftover" lc_claim_open_execution
lc_class "test-server-process" "process" "NONE — a temporal-test-server process is named by its executable and carries no checkout in it; its owner is its parent pid" "the process table, matched on the executable's basename" "a live parent pid (parent 1 means the owner died)" "scripts/temporal_sweep.sh --sweep (TERM then KILL)" "no" "no: it has no checkout identity, so it can never be this checkout's own" lc_claim_test_server_process


# --- THE PRODUCT'S OWN CLASSES: scripts/local/lifecycle.d/<class>.sh ---------
#
# A PRODUCT MINTS MACHINERY THIS TEMPLATE HAS NEVER HEARD OF, and the registry's
# own header says what happens when a census does not know about it: "a broom
# whose population is a list somebody typed goes stale the day a tenth kind of
# thing is created, silently, exactly like the ninth did." Before this drawer
# the only way to add a class was to EDIT THIS FILE — which a template release
# then conflicts with, or fast-forwards over with the product's class silently
# gone. The convention is the one every extension point here uses: a `local/`
# sibling, discovered by path, never shipped by a release, absent = byte-
# identical.
#
# DECLARATION-ONLY, AND IT IS READ RATHER THAN TRUSTED. A file in this drawer
# may hold comments, blank lines and `lc_class` calls, and nothing else. That is
# not tidiness:
#
#   * THIS FILE IS SOURCED BY EVERY BROOM AND BY THE GATE'S OWN CENSUS. A
#     function definition here silently overrides one of the built-ins — a
#     product's `lc_verdict` would change what `--force-foreign` destroys, in
#     every instrument at once, from a file nobody reviews at release time.
#   * A COMMAND HERE RUNS AT SOURCE TIME, inside the gate, inside the pre-push
#     hook, inside `sweep.sh --assert-none`. There is no shape of "ran a
#     command while being sourced by a broom" that is safe by default.
#
# So the file is READ FIRST and sourced only if it is what it claims to be, and
# a file that is not is a REGISTRY DEFECT reported by `lc_registry_check` —
# never an `exit` from inside a library (see that function for why).
#
# THE CLAIM COLUMN IS A `glob:` PATTERN here, because declaration-only means the
# drawer brings no function with it. `lc_claim_matches` above holds both forms.
#
# WHAT THE DRAWER DOES NOT GIVE A PRODUCT, declared rather than discovered: a
# new KIND. A class of an existing kind (`database`, `schedule`, …) is censused,
# attributed and verdicted by the scan that kind already has. A kind nothing
# scans has no enumerator, and an enumerator is code — which is exactly what
# this drawer may not carry. That is a deliberate stop: a product needing a new
# kind is a product needing a platform rung, and a silent empty census would be
# the worse answer.
LC_LOCAL_DIR="${DJB_LIFECYCLE_LOCAL_DIR:-$(dirname "${BASH_SOURCE[0]}")/local/lifecycle.d}"
LC_LOCAL_DEFECTS=""

# lc_local_declaration_only <file> — silent and 0 when the file is comments,
# blank lines and `lc_class` calls AND NOTHING ELSE CAN RUN; otherwise it
# prints `<line>\t<what is wrong>` for the first offence and returns 1.
#
# "STARTS WITH lc_class" IS NOT A TEST, AND THAT IS THE WHOLE OF THIS FUNCTION.
# The first version tested the first word of the joined statement, which three
# one-liners walk straight through — each of them measured against this file:
#
#   lc_class "x" … \                     a continuation, then a second command:
#   ; lc_verdict() { printf OVERRIDDEN; }   the override every broom then uses
#   lc_class "x" "$(touch pwned)" …      command substitution, run while the
#                                          gate and the pre-push hook source us
#   lc_class "x" … && touch pwned        a list, run the same way
#
# So the statement is WALKED, with the shell's own quoting rules, and judged on
# what could still EXECUTE:
#
#   outside quotes   only a bare word may appear. `; & | ( ) { } < > $ ` \ #`
#                    each end the run — they are command separators, lists,
#                    subshells, groups, redirections, expansions and escapes,
#                    which is the complete set of ways one line becomes two.
#   inside "…"       text, but `$` and a backtick still expand, so both are
#                    refused there too. This is the arm the first version had
#                    no way to reach.
#   inside '…'       anything: single quotes expand nothing. This is why the
#                    built-ins' own prose — full of parentheses, `%`, `|` and
#                    backslashes — is legal in a drawer as long as it is
#                    QUOTED, which is what a declaration is made of anyway.
#   unterminated     a quote or a continuation left open is its own refusal,
#                    never a statement that silently vanished.
lc_local_declaration_only() {
    awk '
        function offence(st,   i, c, q, n) {
            q = ""
            n = length(st)
            for (i = 1; i <= n; i++) {
                c = substr(st, i, 1)
                if (q == "'"'"'") { if (c == "'"'"'") q = ""; continue }
                if (q == "\"") {
                    if (c == "\"") { q = ""; continue }
                    if (c == "$") return "`$` expands inside a double-quoted field"
                    if (c == "`") return "a backtick expands inside a double-quoted field"
                    continue
                }
                if (c == "'"'"'" || c == "\"") { q = c; continue }
                if (c == " " || c == "\t") continue
                if (index(";&|(){}<>$`\\#", c) > 0) return "`" c "` outside quotes can run a command"
            }
            if (q != "") return "an unterminated " (q == "\"" ? "double" : "single") " quote"
            return ""
        }
        {
            line = $0
            if (buf == "") {
                sub(/^[ \t]+/, "", line)
                if (line == "" || substr(line, 1, 1) == "#") next
                buf = line
                start = FNR
            } else {
                sub(/^[ \t]+/, "", line)
                buf = buf " " line
            }
            if (buf ~ /\\$/) { sub(/\\$/, "", buf); next }
            if (buf !~ /^lc_class([ \t]|$)/) {
                printf "%d\t%s\n", start, buf
                bad = 1
                exit 1
            }
            rest = buf
            sub(/^lc_class[ \t]*/, "", rest)
            why = offence(rest)
            if (why != "") {
                printf "%d\t%s — in: %s\n", start, why, buf
                bad = 1
                exit 1
            }
            buf = ""
        }
        END {
            if (!bad && buf != "") {
                printf "%d\tline continuation that never ends\n", start
                exit 1
            }
        }
    ' "$1"
}

lc_load_local_classes() {
    local f out
    [ -d "$LC_LOCAL_DIR" ] || return 0
    for f in "$LC_LOCAL_DIR"/*.sh; do
        # A literal glob is an EMPTY drawer, which is byte-identical to none.
        [ -e "$f" ] || continue
        if [ ! -r "$f" ]; then
            LC_LOCAL_DEFECTS="${LC_LOCAL_DEFECTS}${f} is not readable, so this run cannot say what it declares
"
            continue
        fi
        if ! out="$(lc_local_declaration_only "$f")"; then
            LC_LOCAL_DEFECTS="${LC_LOCAL_DEFECTS}${f} is not declaration-only — line ${out%%	*} is \`${out#*	}\`, which is not an lc_class declaration. A file in this drawer is SOURCED by every broom and by the gate's own census: a function here overrides a built-in everywhere at once, and a command here runs inside the gate. It was NOT sourced and its class is not registered.
"
            continue
        fi
        LC_CLASS_DECLARED_IN="$f"
        # shellcheck disable=SC1090
        . "$f"
        LC_CLASS_DECLARED_IN=""
    done
}
lc_load_local_classes

# --- REDIS: DECLARED EXEMPT, AND WHY --------------------
#
# The question the design asked: do the cache keys and the channel-layer groups
# join this registry, or are they exempt? THE ANSWER IS EXEMPT — for two
# different reasons, one of which is also a finding.
#
# WHAT IS ACTUALLY THERE. `config/settings/base.py` puts the channel layer on
# `redis://…/0` and the cache on `redis://…/1` of the one compose Redis; the test
# settings replace BOTH with in-memory backends (`config/settings/test.py`:
# `LocMemCache`, `InMemoryChannelLayer`), so a pytest run — which is what
# produces every other class in this registry, by the hundred — writes nothing to
# Redis at all. Measured on this machine while writing this: `db 0` and `db 1`
# both held ZERO keys with thirty-four checkouts on disk, eighty-one databases,
# thirty-six schedules and two hundred and sixty-eight open executions. Redis is
# not where the leak is.
#
# WHY IT IS NOT A LIFECYCLE CLASS ANYWAY, which is the part that would still be
# true if it were full:
#
#   1. THE CHANNEL LAYER'S STATE IS SELF-EXPIRING. `channels_redis` gives every
#      group membership and every message a TTL and reaps its own keys; a
#      consumer's group disappears when the socket closes or the TTL runs out.
#      Nothing accumulates across a checkout's death, so there is nothing for a
#      broom to find, and a class whose census is always empty is a class that
#      teaches people to skip the census.
#   2. THE CACHE IS NOT CHECKOUT-DERIVED AT ALL — it has no identity for the
#      enumerator to read. Every class above is judged by hashing a path and
#      comparing forward; a cache key carries no branch, no path digest, nothing
#      a `git worktree list` could ever vouch for. It could not be given a
#      verdict, only a guess, and a guess is what the four verdicts exist to
#      refuse. Age is not liveness (TTL reapers were rejected for exactly this),
#      and a Redis `FLUSHDB` scoped by nothing is not a broom, it is a hazard.
#
# AND THE FINDING, booked rather than silently absorbed:
#
#   N-ROW CANDIDATE — THE CACHE IS SHARED, UN-PREFIXED, ACROSS EVERY CHECKOUT.
#   `CACHES["default"]` has no `KEY_PREFIX` and `CACHE_URL` defaults to one
#   database on one server for every checkout on the machine, so two worktrees
#   running at once share one key space. Today that is harmless because the test
#   settings never touch it — which is precisely why it is invisible — but the
#   day a product caches a tenant-scoped read under a bare key, two checkouts
#   answer each other's questions and the symptom is a wrong ROW, not a wrong
#   database. It is the same class as two clones of `main` sharing `djb_main`,
#   one layer over, and the fix is the same shape: derive
#   `KEY_PREFIX` from the checkout, in the one place the name is already derived.
#   That is a `config/settings/` change and therefore out of scope here — it is
#   handed up, not absorbed here.

# --- the server-side scans ------------------------------------------------------
#
# Every one of these asks a SERVER what exists. Nothing consults a local list: a
# thing this checkout forgot it made is precisely what is being hunted, and the
# checkout that made most of what is out there does not exist any more.

# The Temporal CLI. There is none on the host; it lives in the compose container,
# exactly as psql does (`scripts/db.sh::db_psql`). Overridable so a driver can
# point the frame at a stub without a server.
#
# `</dev/null` on the docker call, and it is load-bearing: `docker compose exec`
# reads the CALLER's stdin, so one of these inside a `while read` loop eats the
# list the loop is walking and the census silently stops after the first line.
# `scripts/db_sweep.sh` found that hazard from the psql side; this is the same
# hazard on the Temporal side, closed at the source rather than at every call.
lc_temporal() {
    if [ -n "${DJB_TEMPORAL_CLI:-}" ]; then
        # shellcheck disable=SC2086
        $DJB_TEMPORAL_CLI "$@" </dev/null
        return $?
    fi
    docker compose exec -T temporal temporal "$@" </dev/null
}

# Every database whose name begins the way this repository's do, WITH its live
# session count, `<name>|<sessions>` per line.
#
# ONE STATEMENT AND NOT ONE PER NAME. The liveness evidence is asked for in the
# same scan that produces the population — eighty names is eighty `docker compose
# exec` round trips otherwise, which is a census slow enough that people stop
# running it, and a census nobody runs is the thing this whole file exists to
# replace.
#
# Both prefixes escape `_`, which is a LIKE wildcard and which every name here is
# full of: the scope must be the names it says, not the names it rhymes with.
# `|` is an unambiguous separator because `db_valid_name` allows `[A-Za-z0-9_]`
# and nothing else can reach this list.
lc_scan_databases() {
    db_query "SELECT d.datname || '|' || (SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname) FROM pg_database d WHERE d.datname LIKE 'djb\\_%' OR d.datname LIKE 'test\\_djb\\_%' ORDER BY d.datname" -tA
}

lc_sessions_on() {
    # `:'name'` and not `'$1'`: the count is asked ABOUT a name, and a name that
    # closed the quote used to append its own statement to this one (SEC-R3).
    db_query "SELECT count(*) FROM pg_stat_activity WHERE datname = :'name'" -v name="$1" -tA
}

# --- the Temporal scans, and the clock they are read against ------------
#
# Every one of these pipes ONE Temporal document into
# `scripts/lifecycle_temporal.py`, which is the only thing in the frame that
# parses Temporal's JSON or does arithmetic on its clocks. Read its header for
# why it is a file and not three `python3 -c` programs: the ages are the whole
# point, both of Temporal's time formats need normalising before anything can
# subtract them, and two parsers is two answers to "how old is this".
#
# THE PYTHON IS FOUND RELATIVE TO THIS FILE, never to the caller's working
# directory. `sweep.sh` cd's to the repository root and a drive need not, and a
# census that worked from one directory and exited 2 from another would be a
# census people run from one directory.
LC_TEMPORAL_PY="$(dirname "${BASH_SOURCE[0]}")/lifecycle_temporal.py"

# THE REFUSAL SEAM, sourced the way every other library in this directory
# sources it and guarded against a second source. What this file needs from it
# is `checkout_python`.
#
# WHY THE INTERPRETER IS NOT `python3`. `lifecycle_temporal.py` is a file this
# repository ships, written and tested against the 3.12 the venv holds; a
# verifier box's system `python3` is 3.9 and is first on PATH there. It is
# TOLERATED by 3.9 as it stands today — measured, not assumed — and NOTHING
# KEEPS IT SO: one `zip(…, strict=True)` is what took the queue-index leg down
# on that box, in a file that looked just as safe. The reason not to wait for
# that day here is the failure MODE: all three scans below discard stderr, so a
# reader the interpreter refused prints nothing, every verdict built on it is
# `nothing known`, and the census reads as a clean machine with nothing on it —
# which is the one answer this frame must never invent.
# shellcheck source=scripts/gate_refuse.sh
if [ -z "${GATE_REFUSE_SOURCED:-}" ]; then
    case "${BASH_SOURCE[0]:-}" in
    */*) . "${BASH_SOURCE[0]%/*}/gate_refuse.sh" ;;
    *) . scripts/gate_refuse.sh ;;
    esac
fi

# lc_python — the interpreter the scans run under, resolved once, RELATIVE TO
# THIS FILE for the reason the path above is: `sweep.sh` cd's to the repository
# root and a drive need not.
#
# AND AN ABSENT ONE IS EMPTY, not a refusal, because this is a library: the
# instruments that source it own their exit statuses, and `sweep.sh` asks this
# question in its own preconditions where a refusal belongs. A scan reached with
# no interpreter prints nothing and every verdict built on it is `nothing
# known`, which is what the shapes below already fall back to.
lc_python() {
    checkout_python "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null || return 1
}
LC_PYTHON="$(lc_python || true)"

# A count of seconds as a human reads it — `3d16h`, `7h52m`, `45s` — or the word
# `unknown` for the `-1` the parser prints when it could not tell. Unknown is
# never `0s`: "it has never fired" and "it fired this second" are different
# facts and a census that printed one for the other would be inventing it.
#
# IN THE SHELL, ARITHMETIC ONLY, AND NO FORK. This runs once per census row and
# there were 136 open executions on this machine on a quiet evening; a `date` or
# a `python3` per row is the difference between a census people run before every
# wave and a census people skip. Two units, largest first: the third one has
# never changed anybody's decision.
lc_duration() {
    local seconds="${1:-}"
    case "$seconds" in
    '' | *[!0-9-]* | -*)
        printf 'unknown'
        return 0
        ;;
    esac
    if [ "$seconds" -lt 60 ]; then
        printf '%ds' "$seconds"
    elif [ "$seconds" -lt 3600 ]; then
        printf '%dm' "$((seconds / 60))"
    elif [ "$seconds" -lt 86400 ]; then
        printf '%dh%dm' "$((seconds / 3600))" "$(((seconds % 3600) / 60))"
    else
        printf '%dd%dh' "$((seconds / 86400))" "$(((seconds % 86400) / 3600))"
    fi
}

# `<schedule id>\t<since last fire>\t<to next fire>\t<type>\t<last outcome>`,
# one row per schedule, the two clocks in seconds.
#
# THE LAST FOUR COLUMNS ANSWER A REAL FINDING. A schedule keyed to a checkout that
# was deleted last Tuesday reads FOREIGN with or without them; what the census
# could not say — and what is the difference between a row and a leak — is that
# it fires every five minutes forever into a queue nothing polls, or that it is
# sitting blocked behind its own last action, which is still RUNNING on that
# queue and always will be.
lc_scan_schedules() {
    # NO INTERPRETER IS NO SCAN, never a scan under somebody else's Python: the
    # three readers below all return 1 and print nothing, and every verdict
    # built on an empty scan is already `nothing known`. `sweep.sh` asks the
    # question in its own preconditions, where a refusal belongs.
    [ -n "${LC_PYTHON:-}" ] || return 1
    lc_temporal schedule list -o json 2>/dev/null | "$LC_PYTHON" "$LC_TEMPORAL_PY" schedules
}

# `<task queue>\t<workflow id>\t<age in seconds>\t<workflow type>` per open
# execution. The QUEUE is the identity — a workflow id says which tenant and
# which noun, never which checkout — and that is what makes a sweep-start
# stranded on a dead queue visible here. The AGE is how stranded it is.
lc_scan_open_executions() {
    [ -n "${LC_PYTHON:-}" ] || return 1
    lc_temporal workflow list --query 'ExecutionStatus="Running"' -o json 2>/dev/null |
        "$LC_PYTHON" "$LC_TEMPORAL_PY" executions
}

# `<pollers>|<backlog>|<backlog age in seconds>` for one queue, out of ONE
# `DescribeTaskQueue` round trip.
#
# THE FIRST FIELD IS LIVENESS AND THE OTHER TWO ARE NOT, and the whole census
# rests on that difference. A poller is positive proof that something is working
# this queue right now. A BACKLOG IS THE OPPOSITE — tasks piling up behind
# nobody — so it can never promote a verdict to IN USE; it rides alongside as
# the evidence of harm that makes a FOREIGN queue legible as a graveyard rather
# than as a name.
lc_queue_stats() {
    local raw
    raw=""
    if [ -n "${LC_PYTHON:-}" ]; then
        raw="$(lc_temporal task-queue describe --task-queue "$1" -o json 2>/dev/null |
            "$LC_PYTHON" "$LC_TEMPORAL_PY" queue 2>/dev/null)"
    fi
    # A queue the server would not describe is `no pollers, nothing known`, which
    # is the shape that proves nothing — never an IN USE by accident.
    case "$raw" in
    [0-9]*'|'[0-9]*'|'*) printf '%s' "$raw" ;;
    *) printf '0|0|-1' ;;
    esac
}

# Pollers on a queue, as a count — the LIVENESS reader every verdict calls.
# POSITIVE EVIDENCE ONLY, and the declaration says so: a worker that is up is
# proof the queue is in use, and a worker that is down proves nothing at all —
# every checkout between two runs has no poller.
lc_queue_pollers() {
    local stats
    stats="$(lc_queue_stats "$1")"
    printf '%s' "${stats%%|*}"
}

# `pid ppid exe`, one candidate per line. The match is on the EXECUTABLE — the
# first argv token's basename — never on a command line that happens to mention
# the name. That is the difference between a census and a `grep` that counts
# itself. (`scripts/temporal_sweep.sh` owns the sweep and restates the same
# refusal in its kill path; this is the frame's read of the same population.)
lc_scan_test_server_processes() {
    ps -Ao pid=,ppid=,args= | awk '{
        exe = $3
        n = split(exe, parts, "/")
        if (parts[n] !~ /^temporal-test-server/) next
        print $1, $2, exe
    }'
}
