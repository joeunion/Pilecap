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
# divergence_census.sh — which template-owned files has this product edited?
#
#   ./scripts/divergence_census.sh                the product's hand-run, at every fold
#   ./scripts/divergence_census.sh --if-declared  the gate's form: no base declared is
#                                                 a printed SKIP, never a refusal
#   DJB_TEMPLATE_BASE=<ref> ./scripts/divergence_census.sh
#   ./scripts/divergence_census.sh --against <release ref>
#                                                 the same census, AND the collision
#                                                 census against the release about
#                                                 to be folded (THE COLLISION CENSUS
#                                                 below) — run after `git fetch
#                                                 template --tags`, before the merge
#
# Exit: 0 nothing diverged, or every divergence is NAMED in the product's own
#       `architecture.md` · 1 an unnamed divergence (the path, and the line to
#       add) · 2 COULD NOT LOOK — no checkout, no base, a base that does not
#       resolve, a git read that failed, an `--against` ref that does not
#       resolve — OR, with `--against`, a NAME COLLISION: an app label, table,
#       index, unique constraint, authorization kind, REST mount or router tag
#       of the release that one of the product's own apps already holds, or a
#       product app, mount or tag under the template's reserved prefix. A collision is exit 2 whatever the
#       divergence half concluded:
#       the fold cannot proceed, so the divergence verdict is not a verdict on
#       it. 2 outranks a pass here the way it does in `scripts/check.sh`, and
#       for the same reason: a census that could not read the base has not
#       found a clean tree, it has found nothing.
#
# IT WRITES NOTHING, EVER. No file is created, moved or staged; no ref is
# fetched; no branch moves. Every git call below is a read. That is a property
# of the instrument and not a promise about the operator, which is why the one
# thing it could plausibly want to do — `git fetch template` — it refuses to do
# and tells you to run instead.
#
# Never pipe it: a pipe replaces its exit status with the pipe's, and the exit
# status is the verdict. It refuses one outright (exit 2). Redirect to a file.
#
# ---------------------------------------------------------------------------
# WHY IT EXISTS. The first consumer's fold of v2.1.0 cost 94 merge conflicts,
# 21 of them inside the system layer, and twelve commits whose whole content
# was re-applying local edits to template-owned files. The worst of them was
# silent in the WRONG direction: one 1800-line template file fast-forwarded
# byte-identical and took the product's own edits with it, with no conflict to
# read. Nothing in the tree could answer "which template-owned files have we
# edited, and did we mean to?" — so nobody asked it until the merge did.
#
# THE DECISION THIS INSTRUMENT SERVES is recorded in
# `docs/product/architecture.md` (the extension-point ADR): a product extends
# the system layer by DECLARING BESIDE IT — a `local/` sibling of the directory
# it extends, discovered by the template's own reader and never shipped by the
# template — and an edit to a template-owned path is a DIVERGENCE the product
# records in its own `architecture.md` with the reason. This file is what makes
# the second half falsifiable. `docs/product/build-contract.md` § Ownership is
# the per-path table it reads that decision out of.
#
# WHAT "TEMPLATE-OWNED" IS, AND WHY IT IS DERIVED. The classes come from the
# publication bucket rules in `scripts/archaeology_lib.sh` — the same
# `rules_for` / `bucket_for_rule` pair `scripts/publish.sh` censuses a release
# with — so there is ONE answer to "what class is this path" in this tree
# rather than two that agree today. A new file under a template-owned glob is
# therefore seen the day it lands, with no edit here.
#
# THE DEFAULT LEANS TOWARD THE PRODUCT, deliberately. The build contract's
# table ENUMERATES what the template owns; anything it does not name is the
# product's. A census that guessed the other way would nag a product about
# files the contract never claimed, and a guard that cries wolf is a guard
# people learn to run with their eyes shut.
#
# WHAT IT CANNOT SEE, declared rather than discovered:
#   · A RENAME reads as one deletion and one addition, because the census
#     compares paths and not content-similarity. Both halves are reported and
#     neither is wrong; the pair is not joined for the reader.
#   · A DIVERGENCE INSIDE A PRODUCT-OWNED FILE is invisible by construction —
#     that is the whole point of the partition, and it is why the drawer
#     convention has to be real: a product leg in `scripts/local/` is silence
#     here and a product leg in `scripts/` is a row.
#   · IT JUDGES PATHS, NEVER REASONS. A `divergence:` line naming a path makes
#     that path silent; whether the reason beside it is a good one is a
#     reviewer's question and not a census's, exactly as `instruments.md`'s own
#     census checks that a citation has the SHAPE of a file:line and never that
#     the line says what the cell says.
#   · THE BASE IS TAKEN ON TRUST. If the declared ref is not the release this
#     product actually merged, every number below is measured against the wrong
#     tree. The census can tell that the ref RESOLVES; it cannot tell that it is
#     the right one.
# ---------------------------------------------------------------------------
set -euo pipefail

if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! divergence_census.sh refuses pipes — run it bare or redirect to a file;" >&2
    echo "   the exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/.."
ROOT=$(pwd -P)

# The bucket rules AND the reserved set, shared with `scripts/publish.sh`'s
# release census. See the header: one reader for "what class is this path", and
# one home for "which paths are the drawers", not two of either.
# shellcheck source=scripts/archaeology_lib.sh
. "$ROOT/scripts/archaeology_lib.sh"

# >>> exit-guard >>>
# A CENSUS THAT DIED IS NOT A CENSUS THAT PASSED, and on the bash this repository
# actually runs (GNU bash 3.2.57, macOS) it reads as one: when `set -u` kills the
# shell on an unbound variable, THE EXIT TRAP SEES `$? = 0`. The repro is three
# lines and it is written out in `scripts/tests/drive_preamble.sh` §5;
# `scripts/pm_fold.sh` carries this same guard for the same reason. MEASURED
# here: the first consumer's pre-merge run died on `RULES_FOR: unbound variable`
# and EXITED 0, so the fold read a census that had classified nothing as a tree
# with nothing to declare.
#
# The predicate is therefore NOT the status. It is whether an end this script
# AUTHORED was reached — every one of them goes through `census_exit`, which is
# the only place `exit` is spelled below this line. Neither set, and the shell
# ended the run rather than this script.
CENSUS_END=""
cleanup() { :; }
# THE COLLISION CENSUS OUTRANKS THE DIVERGENCE VERDICT, and this is the one
# place that is decided: every authored end goes through here, so a pair found
# before the divergence half ran makes the whole run exit 2 whatever that half
# concluded. Its scratch directory is removed here too, because `cleanup` is
# redefined below as each divergence file is made.
COLL_PAIRS=0
COLL_TMP=""
census_exit() {
    CENSUS_END=1
    local rc=$1
    if [ "${COLL_PAIRS:-0}" -gt 0 ]; then
        printf '== REFUSED · %s name collision(s) against %s — exit 2 whatever the\n' "$COLL_PAIRS" "$AGAINST"
        printf '   divergence verdict above says: the release'"'"'s migrations would die on\n'
        printf '   them one step after the merge. Rename YOURS, then run this again.\n'
        rc=2
    fi
    exit "$rc"
}
census_on_exit() {
    local status=$1
    cleanup
    [ -z "${COLL_TMP:-}" ] || rm -rf "$COLL_TMP"
    [ -n "${CENSUS_END:-}" ] && return 0
    echo "" >&2
    echo "!! divergence_census: DIED part-way (the shell ended it, status ${status})." >&2
    echo "   The shell exited before any end this census authors. NOTHING THIS RUN" >&2
    echo "   PRINTED IS A VERDICT — the diagnostic bash printed above this line names" >&2
    echo "   the cause. Could-not-look, never a clean census." >&2
    exit 2
}
trap 'census_on_exit $?' EXIT
# <<< exit-guard <<<

# ---------------------------------------------------------------------------
# THE LIBRARY AND THIS SCRIPT SHIP TOGETHER, AND THIS IS WHERE THAT IS CHECKED.
#
# `ownership_of` below calls `rules_for "$p" >/dev/null` and reads `$RULES_FOR`
# — the no-fork idiom `scripts/archaeology_lib.sh` gained in the same release
# this census did, for the reason the note beside `RULES_FOR` gives. An OLDER
# library's `rules_for` only echoes, so the read is an unbound variable, `set
# -u` kills the shell mid-classification, and (see the guard above) the death
# used to exit 0.
#
# That is not a hypothetical pairing. Item 1 of the release notes tells a
# product to run this census BEFORE it merges — which is precisely the tree
# where the new script sits beside the old library. So the pairing is probed
# once, here, with one call, and a mismatch is a could-not-look that names BOTH
# files to take rather than a `line NNN: RULES_FOR: unbound variable` blamed on
# the tree.
# ---------------------------------------------------------------------------
# THE TAG IS A PLACEHOLDER, AND NOTHING HERE DERIVES IT. The version file in the
# checkout is the obvious reader and it is the WRONG one, measured: this refusal
# only ever fires on a tree that has NOT merged yet — running the census before
# the fold is the whole supported order — so that file names the release the
# product is already ON, which is exactly the release whose library lacks the
# idiom. It would hand somebody the wrong tag with total confidence. A blank is
# worse-looking and better: it is a blank they can fill in, because it is the
# tag they came here to merge.
RELEASE_REF='v<the release you are folding>'
rules_for scripts/check.sh >/dev/null 2>&1 || true
if [ -z "${RULES_FOR+set}" ]; then
    echo "!! THIS CENSUS AND scripts/archaeology_lib.sh DID NOT SHIP TOGETHER." >&2
    echo "   \`rules_for\` in scripts/archaeology_lib.sh did not set \$RULES_FOR, which is" >&2
    echo "   the idiom this census classifies every path with. That library is older" >&2
    echo "   than this script; the two are one release and were taken apart." >&2
    echo "   TAKE BOTH FILES FROM THE TAG, never one — the tag is the release you are" >&2
    echo "   MERGING, not the one this checkout is on:" >&2
    echo "     git show ${RELEASE_REF}:scripts/divergence_census.sh > scripts/divergence_census.sh" >&2
    echo "     git show ${RELEASE_REF}:scripts/archaeology_lib.sh   > scripts/archaeology_lib.sh" >&2
    echo "   Could-not-look, never a clean census." >&2
    census_exit 2
fi

IF_DECLARED=0
AGAINST=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --if-declared)
        IF_DECLARED=1
        shift
        ;;
    --against)
        [ -n "${2:-}" ] || {
            echo "!! --against needs the release ref you are about to fold (a tag, after" >&2
            echo "   \`git fetch template --tags\`) — a collision census against nothing is not one" >&2
            census_exit 2
        }
        AGAINST=$2
        shift 2
        ;;
    *)
        echo "!! unknown argument '$1': divergence_census.sh takes nothing, --if-declared" >&2
        echo "   or --against <release ref>" >&2
        census_exit 2
        ;;
    esac
done

say() { printf '%s\n' "$*"; }

git rev-parse --git-dir >/dev/null 2>&1 || {
    echo "!! not a git checkout — this census reads git and nothing else" >&2
    census_exit 2
}

# ---------------------------------------------------------------------------
# THE RESERVED GLOBS — the drawers. Product-owned wherever they appear, ahead
# of every other rule, because that is the promise the convention makes: a
# product's own leg, rule, fold step or instrument row lives in the drawer and
# is never a divergence. `scripts/publish.sh`'s R0 is the other half — the
# template never SHIPS one — and the two together are what make a drawer
# conflict-free at a merge.
# ---------------------------------------------------------------------------
DRAWER_GLOBS='**/local/** *.local.md apps/conftest_local.py'
# DERIVED FROM THE LIST, never typed beside it. The gate's floor for this rule
# binds this number, so a member deleted from the line above has to trip the
# floor rather than quietly narrow the reserved set. Three today: two globs
# and one exact path.
#
# `set -f` AROUND IT, AND THAT IS NOT TIDINESS. `set --` splits AND GLOBS its
# arguments, and every member of this list is a pathname pattern that the
# shell will happily expand against the tree it is standing in. MEASURED on
# the first consumer's checkout: with `quality/local/` and `scripts/local/`
# present, `**/local/**` and `*.local.md` expanded to their own directories'
# contents and the count read 6 instead of 3. Rule 60's `drawer_globs`
# floor reads that number, so the floor was being satisfied by THE FILESYSTEM
# rather than by the list — silent, and silent in the passing direction: a
# member deleted from the line above could be covered by a drawer that happened
# to hold three files. The list is a list of PATTERNS; it is counted as text.
set -f
set -- $DRAWER_GLOBS
DRAWER_GLOB_COUNT=$#
set --
set +f

# ---------------------------------------------------------------------------
# THE SHARED SET — one file each, adjudicated BY HAND at a merge, and never a
# divergence. These are the files both sides legitimately write: the product
# adds its roles, its dependencies, its services and its environment keys, and
# the template moves underneath. A conflict here is the contract working, so a
# census row would be noise on every single fold.
#
# It is a LIST rather than a derivation because it is a list: eight named files
# and two globs, each one a decision somebody made. The build contract's
# § Ownership table is the authority and this is the executable copy of its
# third row; if the two disagree, the table wins and the disagreement is a
# finding.
# ---------------------------------------------------------------------------
is_shared() {
    case "$1" in
    apps/core/roles.py | apps/core/api/frozen_families.py) return 0 ;;
    pyproject.toml | uv.lock | compose.yaml | .env.example) return 0 ;;
    quality/budgets.yaml) return 0 ;;
    deploy/tests/*) return 0 ;;
    # The three MEASURED files: a map of THIS tree's apps and timings. A
    # product regenerates them at its first bank rather than reconciling ours.
    scripts/test_impact.json | *pytest_durations.json | *gate_member_durations.json) return 0 ;;
    esac
    return 1
}

# `platform_apps` from the partition closure — the apps the template owns. An
# app absent from that list is the PRODUCT'S app and everything under it is
# theirs, which is the whole reason a rung names its app.
PLATFORM_APPS=$(
    awk '/^platform_apps:/{f=1;next} f&&/^[a-z_]+:/{exit} f&&/^  - /{print $2}' \
        "$ROOT/quality/partition.yaml" 2>/dev/null || true
)

is_platform_app_path() {
    local label=${1#apps/}
    label=${label%%/*}
    # NEWLINE-DELIMITED, because the awk above prints one name per line: a
    # space-delimited test matched only a one-entry list. No pipe, no
    # IFS, no globbing — the same whole-line form `is_named` uses below.
    local nl=$'\n'
    case "${nl}${PLATFORM_APPS}${nl}" in
    *"${nl}${label}${nl}"*) return 0 ;;
    esac
    return 1
}

# ---------------------------------------------------------------------------
# ownership_of <path> — `template`, `product` or `shared`.
#
# ORDER IS THE ARGUMENT, and it reads top to bottom: the drawers first (the
# promise), the shared set second (the adjudicated files), then the bucket
# rules, then the enumerated carve-outs the build contract names. Everything
# the contract does not claim falls through to `product`.
# ---------------------------------------------------------------------------
OWNERSHIP=""
ownership_of() {
    local p=$1
    case "$p" in
    local/* | */local/* | *.local.md)
        OWNERSHIP=product
        return 0
        ;;
    # THE ONE EXACT PATH IN THE RESERVED SET, and it is here for the reason it
    # is in `publish.sh`'s: a `conftest.py` sibling is collected by pytest BY
    # NAME inside the package it belongs to, so the fixtures drawer cannot be
    # spelled `apps/local/…` without leaving the directory pytest looks in.
    # The two readers carry the same three members because the reserved set is
    # ONE decision read twice — R0 refuses to ship one, this refuses to call
    # one a divergence — and a member in one list and not the other is the
    # drift the whole census discipline exists to refuse.
    apps/conftest_local.py)
        OWNERSHIP=product
        return 0
        ;;
    esac
    if is_shared "$p"; then
        OWNERSHIP=shared
        return 0
    fi
    # The carve-outs, BEFORE the bucket arms that would otherwise swallow them:
    # `.github/*` and `docs/product/*.md` are single bucket rules covering paths
    # the contract splits between the two owners.
    case "$p" in
    # The template ships TWO workflows and the product may add its own beside
    # them: `ci.yml` (the gate, sharded) and `nightly-proof.yml` (the leak
    # proof the bank no longer runs, and the map the fold harvests). An edit
    # to either is the template's file drifting under a product; every other
    # file under `.github/workflows/` is the product's.
    .github/workflows/ci.yml | .github/workflows/nightly-proof.yml)
        OWNERSHIP=template
        return 0
        ;;
    .github/workflows/*)
        OWNERSHIP=product
        return 0
        ;;
    # The product's README is the product's front door.
    README.md)
        OWNERSHIP=product
        return 0
        ;;
    # The six standing documents the contract names, and the design directory
    # — and no others: a product's own `architecture.md` is where it records
    # its decisions AND its divergences, so it cannot be one. The design
    # directory is the SAME GLOB the publish census's R9 arm ships
    # (`rules_for` in archaeology_lib.sh), so a second file the template adds
    # beside the pattern book is the template's the day it lands, never a
    # silent product file the publish census ships as SHIP. The drawer beside
    # the book, `patterns.local.md`, never reaches this arm: the reserved
    # drawer arm above matches it first, and it is the product's.
    docs/product/build-contract.md | docs/product/instruments.md | \
        docs/product/partition-closure.md | docs/product/publication-manifest.md | \
        docs/product/api-editorial-standard.md | docs/product/scale-envelope.md | \
        docs/product/design/*)
        OWNERSHIP=template
        return 0
        ;;
    docs/product/*)
        OWNERSHIP=product
        return 0
        ;;
    esac
    # `>/dev/null` AND `$RULES_FOR`, never `$(rules_for …)`: this function is
    # called once per path in the tree, and a command substitution forks a
    # subshell each time. See the note beside `RULES_FOR` in archaeology_lib.sh.
    rules_for "$p" >/dev/null
    set -- $RULES_FOR
    if [ "$#" -ne 1 ]; then
        # Ambiguous or unplaced is the publication census's refusal to make,
        # not this one's: it reads the same classifier and would only be a
        # second opinion about it. Product, so the census stays quiet about a
        # path somebody else's leg is already shouting about.
        OWNERSHIP=product
        return 0
    fi
    case "$1" in
    R2 | R3 | R5 | R9) OWNERSHIP=template ;;
    R1)
        case "$p" in
        config/* | manage.py) OWNERSHIP=template ;;
        apps/*)
            if is_platform_app_path "$p"; then OWNERSHIP=template; else OWNERSHIP=product; fi
            ;;
        *) OWNERSHIP=product ;;
        esac
        ;;
    *) OWNERSHIP=product ;;
    esac
}

# ---------------------------------------------------------------------------
# THE BASE — three readers, one function, and the precedence is PRINTED on
# every run so a wrong answer is traceable to which reader gave it.
#
#   1. `DJB_TEMPLATE_BASE` — the typed override, for a one-off question and for
#      this census's own drive. An environment value wins for `scripts/db.sh`'s
#      reason: the person typing it is standing right there.
#   2. `scripts/local/template-base` — the product's written declaration, one
#      line, one ref. It lives in the DRAWER on purpose: the census's own
#      configuration uses the convention the census exists to defend, and the
#      template can never ship a file that would conflict with it (publish R0).
#   3. The `template` remote's `v<TEMPLATE_VERSION>` tag — derived, so a
#      product that added the remote and merged a tag needs no configuration at
#      all. The remote is what makes this a product rather than the template:
#      the template has no template.
#
# NONE OF THEM IS A DEFAULT. A tree with no base declared has no base, and this
# census says so rather than guessing at one — a census measured against a
# guessed base is worse than no census, because it reads as an answer.
# ---------------------------------------------------------------------------
BASE=""
BASE_FROM=""
declare_base() {
    if [ -n "${DJB_TEMPLATE_BASE:-}" ]; then
        BASE=$DJB_TEMPLATE_BASE
        BASE_FROM="DJB_TEMPLATE_BASE"
        return 0
    fi
    if [ -f "$ROOT/scripts/local/template-base" ]; then
        BASE=$(tr -d '[:space:]' <"$ROOT/scripts/local/template-base")
        BASE_FROM="scripts/local/template-base"
        [ -n "$BASE" ] || {
            echo "!! scripts/local/template-base is empty — a declaration that names no" >&2
            echo "   ref is not a declaration. Write the release ref you merged, or delete" >&2
            echo "   the file and let the remote derive it." >&2
            census_exit 2
        }
        return 0
    fi
    # READ WHOLE, THEN SLICE. `git remote | grep -qx template` is a reader that
    # short-circuits its own producer at the tail of a pipeline under
    # `pipefail`: `grep -q` exits at the first match and git dies of SIGPIPE,
    # and past 64 KiB of output that reports the wrong answer EVERY run. The
    # census's own drive caught it here; `is_named` above is written the same
    # way for the same reason.
    local remotes
    remotes=$(git remote 2>/dev/null || true)
    case "
$remotes
" in
    *"
template
"*)
        local version
        version=$(tr -d '[:space:]' <"$ROOT/TEMPLATE_VERSION" 2>/dev/null || true)
        case "$version" in
        [0-9]*.[0-9]*.[0-9]*) ;;
        *)
            echo "!! a 'template' remote is configured and TEMPLATE_VERSION does not read" >&2
            echo "   as <major>.<minor>.<patch>: \"$version\". The base tag is derived from" >&2
            echo "   it, and a derivation that cannot be read is a could-not-look." >&2
            census_exit 2
            ;;
        esac
        BASE="v$version"
        BASE_FROM="the 'template' remote, derived from TEMPLATE_VERSION"
        return 0
        ;;
    esac
    return 1
}

say "== divergence census · $ROOT"

# ---------------------------------------------------------------------------
# THE COLLISION CENSUS — `--against <release ref>`, before the merge.
#
# A release that adds a platform app adds an app LABEL, the TABLES its models
# create, the INDEX and UNIQUE-CONSTRAINT names its migrations spell, the
# AUTHORIZATION KIND each model's class name derives, the REST MOUNT its router
# answers at and the router TAGS that are its scope families — and every one of
# those is one namespace: the first four in the product's database, the fifth
# in its grant vocabulary, the sixth on its wire and the seventh in its tokens. A product whose own app already holds one of them does
# not get a merge conflict; it gets a merge that succeeds and a `migrate` (or
# a `check`) that dies one step later. So the question is asked of both trees
# BEFORE the merge, and a pair is exit 2.
#
# ONE PARSER, TWO READERS. `census_names` is the only reader of an app's
# names, and it is handed a reader: `tree` (the working tree — YOURS, the tree
# the fold is about to hand to a merge) or a ref (the release, read with
# `git ls-tree` and `git show`, so nothing is checked out or fetched). The two
# sides therefore cannot be parsed differently.
#
# THE POPULATION, per app:
#   label       the `label = "…"` literal in apps.py if one is typed, else the
#               last segment of `name = "apps.…"`
#   table       every `CreateModel` → `<label>_<lower(name)>`, replaced by the
#               `"db_table": "…"` literal when that CreateModel's options carry one
#   index       every `name="…"` inside a call whose name ends in `Index(` —
#               `models.Index` and every subclass (`GinIndex`, `GistIndex`,
#               `BTreeIndex`, `BrinIndex`, `HashIndex`, `SpGistIndex`), dotted
#               or bare; an operation (`migrations.AddIndex(`) is read as the
#               operation it is, never as the index inside it — the scoped base's
#               `%(class)s_recency` is rendered as a literal in a migration, so
#               an inherited recency index IS in the population
#   constraint  every `name="…"` inside a `UniqueConstraint(`
#   kind        every `CreateModel`'s name in snake case, the authorization kind
#               `apps/core/authz.py` derives from the class name — unless that
#               class's body in `models.py` types `authz_kind = "…"` (the word
#               replaces it), `authz_kind = None` (no kind) or a non-None
#               `authz_kind_of` (a child, authorized under its parent's kind)
#   mount       the first path segment the app's router answers at, read from
#               `api.py` and `api/*.py` (`census_mounts`): `PREFIX = "<x>"` when
#               spelled non-empty; the label when no `PREFIX =` line is spelled;
#               under `PREFIX = ""`, the first literal segment of every route
#               decorator and every `add_router("/<seg>/…`. Two apps on one
#               mount are two routers on one path: the wire answers with the one
#               discovered first and the document describes the other, and
#               nothing refuses it until `check` runs AFTER the merge (house
#               rule 83, `djb.E083`) — this is the reader before it
#   tag         every string literal in a `tags=[…]` list in those files — a
#               router's or a route's own. A tag is a scope family. The `TAGS`
#               dict's keys are NOT read: rule 41 holds each `TAGS` key to a
#               router tag and each router tag to a `TAGS` key, so one side is
#               both sides
# the schema classes are read from `migrations/*.py` — the tree's own record
# of what created the schema — and never from `models.py`: an abstract model
# creates nothing. The
# one thing read from `models.py` is the kind's override, because it lives
# nowhere else. Django's own `models.E030` refuses two equal index names at
# `check` time: that is the belt behind this census, and it fires only AFTER
# the merge.
#
# YOURS IS WHAT THE PARTITION DOES NOT CLAIM. The product's side is its apps
# absent from `platform_apps` — the same reader the ownership table above uses
# — so a platform app the product already carries is the template's own and is
# never compared with its next release. The release's side is every app the
# ref carries.
#
# WHAT IT CANNOT SEE, declared rather than discovered:
#   · A NAME CHANGED AFTER CREATION — `RenameModel`, `AlterModelTable`,
#     `RenameIndex`, `RemoveIndex` after the `CreateModel` or `AddIndex`. The
#     name is read where it is created, so a renamed table is read by its old
#     name.
#   · A REMOVAL SPELLED WITHOUT ITS MODULE READ AS A CREATION — a bare
#     `RemoveIndex(name="…")` (no `migrations.` before it) ends in `Index(`, so
#     the name it removes is read as an index the app creates: a false pair,
#     loud (exit 2 naming the file), never a silent one. `makemigrations`
#     always writes the prefix.
#   · CHECK-CONSTRAINT NAMES, by design: they are per-table in Postgres and
#     two equal ones never collide.
#   · AUTO-GENERATED foreign-key and index names — hashed with the table, so a
#     table that does not collide cannot carry one that does.
#   · A `db_table` COMPUTED rather than spelled — this reads text and runs no
#     Django on either side (the release's apps are not installed in this
#     checkout), so a name built by code is invisible rather than falsely clean.
#   · A KIND OVERRIDE NOT TYPED IN THE CLASS'S OWN BODY — one inherited from an
#     intermediate class, or computed rather than spelled as a string literal,
#     is read as the class name's derivation. A `DeleteModel` does not take a
#     model out of the population.
#   · A `name=` BETWEEN A CALL AND ITS OWN NAME. This reads text: the first
#     `name="…"` after `Index(`, `UniqueConstraint(` or `CreateModel(` is taken
#     as that call's name, so a hand-written operation that places another
#     keyword spelled `name=` (inside a nested call) before the call's own is
#     misread. `makemigrations` never writes that shape.
#   · A MOUNT OR A TAG NOT SPELLED AS A LITERAL — a `PREFIX` or a route path
#     computed (an f-string, a variable, a constant imported from elsewhere), a
#     `tags=` list built from a variable or spread over several lines, a route
#     registered by `add_api_operation` rather than a decorator, a sub-router
#     whose `add_router` literal lives in a file the two globs do not read. A
#     sub-router added by a line the reader does not parse (its path not a
#     literal, or the call over several lines) has its own route segments read
#     as root segments — which can only add a false pair, loud, never hide one.
#   · A SEGMENT SHADOWED BY A PARAMETER — `/x/links/` beside `/x/{id}/` — is no
#     pair here (only first segments are read), and it is house rule 83's
#     declared blind spot too.
#   · MODELS OUTSIDE `apps/` — a vendored app's tables, or anything a product's
#     `local/` drawer creates; rule 60's census has the same blind spot.
#   · THE RELEASE MUST BE FETCHED. A ref this checkout cannot resolve is exit 2
#     naming the fetch, never a clean census of nothing.
# ---------------------------------------------------------------------------
COLL_REMEDY="remedy: rename YOURS — CHANGELOG.md § [2.4.1] › What a product does at the merge › the rename road; the template's name is the release's"
# A kind is fixed on the PRODUCT's side, and in one line: the release's kinds
# are the platform contract every product's grants and roles are written
# against, so it is the product's model that takes a word of its own.
COLL_KIND_REMEDY="remedy: give YOUR model a kind of its own — one line on its class, authz_kind = \"<its own word>\"; the release's kind is the platform contract every product grants against, and it does not move"
# A mount and a tag are fixed on the PRODUCT's side too: the release's mount is
# the platform's path, and its tag is a scope family tokens already name.
COLL_MOUNT_REMEDY="remedy: mount YOURS elsewhere — PREFIX = \"<its own word>\" in your api.py (or the route path's first segment, when PREFIX is \"\"); the release's mount is the platform's"
COLL_TAG_REMEDY="remedy: tag YOURS with a word of its own — Router(tags=[\"<its own word>\"]) and the matching TAGS key; a tag is a scope family, and one key across two apps is one token ceiling that reaches both"

# census_read <reader> <path> — the file's bytes, from the working tree or a ref.
census_read() {
    if [ "$1" = tree ]; then
        cat "$ROOT/$2"
    else
        git show "$1:$2"
    fi
}

# census_mounts <reader> <app dir> <label> — the app's REST mounts and router
# tags, read as text from `<app>/api.py` and `<app>/api/*.py` (a package, as
# core's is) with the same reader as every other class. One line each,
# `mount\t<first path segment>\t<api file>` and `tag\t<key>\t<api file>`.
#
# The mount is what `config/api.py` binds: `PREFIX = "<x>"` when one is spelled
# non-empty (its first segment); the LABEL when no `PREFIX =` line is spelled
# and a `Router(` is; and, when `PREFIX = ""`, the first literal segment of
# every route decorator `@<router>.<get|post|patch|put|delete>("/<seg>/…` —
# its path on the decorator's line or the line after — and of every
# `<router>.add_router("/<seg>/", <sub>)`, whose `<sub>`'s own decorators are
# then nested under that segment and name no mount of their own (a sub-router
# added at `""` is at the root, and its decorators count). A route at `"/"`
# under an empty prefix is the root and names nothing; a first segment that is
# a `{parameter}` names nothing. The tags are every string literal inside a
# `tags=[…]` keyword on one line — a `Router(…)` or a route decorator; an
# assignment spelled `tags = […]` is a variable, never a keyword, and is not
# read.
census_mounts() {
    local reader=$1 appdir=$2 label=$3 apifiles f
    if [ "$reader" = tree ]; then
        apifiles=$(
            cd "$ROOT" || exit 2
            for f in "$appdir/api.py" "$appdir"/api/*.py; do
                if [ -f "$f" ]; then printf '%s\n' "$f"; fi
            done
        ) || return 2
    else
        apifiles=$(git ls-tree -r --name-only "$reader" -- "$appdir/api.py" "$appdir/api/") || return 2
    fi
    [ -n "$apifiles" ] || return 0
    while IFS= read -r f; do
        [[ "$f" == *.py ]] || continue
        # The api package's own subdirectories are not the module's.
        case "${f#"$appdir"/}" in api/*/*) continue ;; esac
        printf '@@census-file %s\n' "$f"
        census_read "$reader" "$f" || exit 2
        printf '\n'
    done <<<"$apifiles" | awk -v label="$label" '
        function first(path,  n, seg) {
            sub(/^\/+/, "", path)
            n = split(path, seg, "/")
            if (n == 0 || seg[1] == "" || seg[1] ~ /^\{/) return ""
            return seg[1]
        }
        function emit(class, value, file) {
            if (value == "" || ((class, value, file) in seen)) return
            seen[class, value, file] = 1
            printf "%s\t%s\t%s\n", class, value, file
        }
        function route(owner, path, file,  s) {
            s = first(path)
            if (s != "") { nroute++; rowner[nroute] = owner; rseg[nroute] = s; rfile[nroute] = file }
        }
        function owner_of(line,  o) {
            o = line; sub(/^[ \t]*@?/, "", o); sub(/\..*$/, "", o)
            return o
        }
        /^@@census-file / { file = substr($0, 15); pending = ""; next }
        pending != "" {
            if (match($0, /^[ \t]*["\047]\/[^"\047]*/)) {
                v = substr($0, RSTART, RLENGTH); sub(/^[ \t]*["\047]/, "", v); route(pending, v, file)
            }
            pending = ""
        }
        /^[ \t]*#/ { next }
        /^PREFIX[ \t]*(:[^=]*)?=[ \t]*["\047]/ {
            v = $0; sub(/^[^"\047]*["\047]/, "", v); sub(/["\047].*$/, "", v)
            spelled = 1
            gsub(/^\/+|\/+$/, "", v)
            if (v == "") empty = 1
            else emit("mount", first(v), file)
        }
        /^[A-Za-z_][A-Za-z0-9_]*[ \t]*(:[^=]*)?=[ \t]*Router\(/ && routerfile == "" { routerfile = file }
        {
            line = $0
            if (match(line, /^[ \t]*@[A-Za-z_][A-Za-z0-9_]*\.(get|post|patch|put|delete)\([ \t]*$/)) pending = owner_of(line)
            else if (match(line, /^[ \t]*@[A-Za-z_][A-Za-z0-9_]*\.(get|post|patch|put|delete)\([ \t]*["\047]\/[^"\047]*/)) {
                v = substr(line, RSTART, RLENGTH); sub(/^[^"\047]*["\047]/, "", v); route(owner_of(line), v, file)
            }
            if (match(line, /^[ \t]*[A-Za-z_][A-Za-z0-9_]*\.add_router\([ \t]*["\047][^"\047]*["\047][ \t]*,[ \t]*[A-Za-z_][A-Za-z0-9_]*/)) {
                v = substr(line, RSTART, RLENGTH); sub(/^[^"\047]*["\047]/, "", v)
                sub_ = v; sub(/^.*,[ \t]*/, "", sub_)
                sub(/["\047].*$/, "", v)
                if (first(v) != "") { nested[sub_] = 1; route(owner_of(line), v, file) }
            }
            while (match(line, /(^|[(, \t])tags=\[[^]]*\]/)) {
                t = substr(line, RSTART, RLENGTH)
                line = substr(line, RSTART + RLENGTH)
                while (match(t, /"[^"]*"|\047[^\047]*\047/)) {
                    emit("tag", substr(t, RSTART + 1, RLENGTH - 2), file)
                    t = substr(t, RSTART + RLENGTH)
                }
            }
        }
        END {
            if (!spelled && routerfile != "") emit("mount", label, routerfile)
            if (empty) for (i = 1; i <= nroute; i++) if (!(rowner[i] in nested)) emit("mount", rseg[i], rfile[i])
        }
    '
}

# census_names <reader> <apps.py path> <migrations dir> — one line per name,
# `<class>\t<value>\t<path it was read from>`; an app with no migrations
# directory prints `unparsed\t<app dir>\t-` after its label, never nothing.
census_names() {
    local reader=$1 appspy=$2 migdir=$3 appdir label body files f
    appdir=${appspy%/apps.py}
    body=$(census_read "$reader" "$appspy") || return 2
    label=$(printf '%s\n' "$body" | awk '
        /^[ \t]+label[ \t]*=[ \t]*["\047]/ { v = $0; sub(/^[^"\047]*["\047]/, "", v); sub(/["\047].*$/, "", v); lbl = v }
        /^[ \t]+name[ \t]*=[ \t]*["\047]/ && nm == "" { v = $0; sub(/^[^"\047]*["\047]/, "", v); sub(/["\047].*$/, "", v); nm = v }
        END { if (lbl != "") print lbl; else if (nm != "") { n = split(nm, p, "."); print p[n] } }
    ')
    # An apps.py that spells neither is read as Django would default it for a
    # module at that path: the directory's name.
    [ -n "$label" ] || label=${appdir##*/}
    printf 'label\t%s\t%s\n' "$label" "$appdir"
    census_mounts "$reader" "$appdir" "$label" || return 2
    if [ "$reader" = tree ]; then
        if [ ! -d "$ROOT/$migdir" ]; then
            printf 'unparsed\t%s\t-\n' "$appdir"
            return 0
        fi
        files=$(
            cd "$ROOT" || exit 2
            for f in "$migdir"/*.py; do
                if [ -f "$f" ]; then printf '%s\n' "$f"; fi
            done
        ) || return 2
    else
        files=$(git ls-tree --name-only "$reader" -- "$migdir/") || return 2
        if [ -z "$files" ]; then
            printf 'unparsed\t%s\t-\n' "$appdir"
            return 0
        fi
    fi
    printf 'parsed\t%s\t-\n' "$appdir"
    # Two statements: `local a=… b=$a` expands `$a` before `a` is assigned.
    local nl=$'\n' mig overrides mfiles
    local IFS=$nl
    mig=$(for f in $files; do
        [[ "$f" == *.py ]] || continue
        body=$(census_read "$reader" "$f") || exit 2
        printf '%s\n' "$body" | awk -v label="$label" -v file="$f" '
            function flush(  t) {
                if (model != "") {
                    t = (dbt != "") ? dbt : label "_" tolower(model)
                    printf "table\t%s\t%s\n", t, file
                    printf "model\t%s\t%s\n", model, file
                }
                model = ""; dbt = ""; inmodel = 0
            }
            /^[ \t]*#/ { next }
            {
                line = $0
                while (match(line, /migrations\.[A-Za-z]+\(|UniqueConstraint\(|CheckConstraint\(|[A-Za-z0-9_]*Index\(|[^A-Za-z0-9_]name *= *"[^"]*"|^name *= *"[^"]*"|"db_table" *: *"[^"]*"/)) {
                    tok = substr(line, RSTART, RLENGTH)
                    line = substr(line, RSTART + RLENGTH)
                    if (tok ~ /^migrations\./) {
                        flush()
                        if (tok ~ /CreateModel\($/) { inmodel = 1; want = "model" } else want = ""
                    } else if (tok ~ /UniqueConstraint\($/) {
                        want = "constraint"
                    } else if (tok ~ /CheckConstraint\($/) {
                        want = "check"
                    } else if (tok ~ /Index\($/) {
                        want = "index"
                    } else if (tok ~ /^"db_table"/) {
                        if (inmodel) { v = tok; sub(/^"db_table" *: *"/, "", v); sub(/"$/, "", v); dbt = v }
                    } else {
                        v = tok; sub(/^.*name *= *"/, "", v); sub(/"$/, "", v)
                        if (want == "model") model = v
                        else if (want == "index") printf "index\t%s\t%s\n", v, file
                        else if (want == "constraint") printf "constraint\t%s\t%s\n", v, file
                        want = ""
                    }
                }
            }
            END { flush() }
        '
    done) || return 2
    if [ -n "$mig" ]; then printf '%s\n' "$mig"; fi

    # THE AUTHORIZATION KINDS. A concrete model's kind is its class name in
    # snake case (`apps/core/authz.py`, `_own_kind`: `WidgetEntry` →
    # `widget_entry`) unless the class body says otherwise — `authz_kind =
    # "<word>"` replaces it, `authz_kind = None` opts it out, and a non-None
    # `authz_kind_of` makes it a child authorized under its parent's kind with
    # none of its own. Two models claiming one kind is a deployment whose
    # `check` refuses to derive the vocabulary at all, however different their
    # labels and tables are. The POPULATION is the migrations' `CreateModel`
    # names read above — what exists, never an abstract class — and the
    # overrides are read from the class bodies in `models.py`.
    if [ "$reader" = tree ]; then
        mfiles=$(
            cd "$ROOT" || exit 2
            for f in "$appdir/models.py" "$appdir"/models/*.py; do
                if [ -f "$f" ]; then printf '%s\n' "$f"; fi
            done
        ) || return 2
    else
        mfiles=$(git ls-tree -r --name-only "$reader" -- "$appdir/models.py" "$appdir/models/") || return 2
    fi
    overrides=$(for f in $mfiles; do
        [[ "$f" == *.py ]] || continue
        body=$(census_read "$reader" "$f") || exit 2
        printf '%s\n' "$body" | awk '
            /^class [A-Za-z_][A-Za-z0-9_]*[(:]/ { cls = $2; sub(/[(:].*$/, "", cls); next }
            /^[^ \t#]/ { cls = "" }
            cls != "" && /^    authz_kind[ \t]*(:[^=]*)?=/ {
                v = $0; sub(/^[^=]*=[ \t]*/, "", v); sub(/[ \t]*(#.*)?$/, "", v)
                if (v == "None") printf "override\t%s\t@none\n", cls
                else if (v ~ /^"[^"]*"$/ || v ~ /^\047[^\047]*\047$/) printf "override\t%s\t%s\n", cls, substr(v, 2, length(v) - 2)
            }
            cls != "" && /^    authz_kind_of[ \t]*(:[^=]*)?=/ {
                v = $0; sub(/^[^=]*=[ \t]*/, "", v); sub(/[ \t]*(#.*)?$/, "", v)
                if (v != "None") printf "override\t%s\t@child\n", cls
            }
        '
    done) || return 2
    printf '%s\n%s\n' "$overrides" "$mig" | awk -F'\t' -v app="$appdir" '
        function snake(s,  i, c, o) {
            o = ""
            for (i = 1; i <= length(s); i++) {
                c = substr(s, i, 1)
                if (i > 1 && c ~ /[A-Z]/) o = o "_"
                o = o tolower(c)
            }
            return o
        }
        $1 == "override" { if (!($2 in ov) || $3 == "@child") ov[$2] = $3; next }
        $1 == "model" {
            if ($2 in seen) next
            seen[$2] = 1
            k = ($2 in ov) ? ov[$2] : snake($2)
            if (k == "@none" || k == "@child") next
            printf "kind\t%s\t%s · %s\n", k, app, $2
        }
    '
}

if [ -z "$AGAINST" ]; then
    say "collisions: not measured (no --against <release ref>)"
else
    if ! git rev-parse -q --verify "$AGAINST^{commit}" >/dev/null 2>&1; then
        echo "!! --against $AGAINST does not resolve to a commit in this checkout." >&2
        echo "   A release you have not fetched cannot be compared with. Fetch it and re-run:" >&2
        echo "     git fetch template --tags" >&2
        echo "   This census writes nothing, so it will not fetch for you. Could-not-look," >&2
        echo "   never a clean collision census." >&2
        census_exit 2
    fi
    COLL_TMP=$(mktemp -d "${TMPDIR:-/tmp}/djb-divergence-collisions.XXXXXX") || census_exit 2
    say ""
    say "-- collisions: the release's app names against yours ($AGAINST)"

    # THE RELEASE'S APPS, read whole and then sliced — `git ls-tree -r` of the
    # apps directory, filtered to `apps/<app>/apps.py` exactly.
    rel_listing=$(git ls-tree -r --name-only "$AGAINST" -- apps/) || {
        echo "!! git could not list apps/ at $AGAINST — could-not-look" >&2
        census_exit 2
    }
    : >"$COLL_TMP/release"
    for p in $(printf '%s\n' "$rel_listing" | awk -F/ 'NF == 3 && $1 == "apps" && $3 == "apps.py"'); do
        census_names "$AGAINST" "$p" "${p%/apps.py}/migrations" >>"$COLL_TMP/release" || {
            echo "!! a git read of $p (or its migrations) at $AGAINST failed — could-not-look" >&2
            census_exit 2
        }
    done
    # YOURS: every app in the working tree the partition does not claim.
    : >"$COLL_TMP/yours"
    for p in "$ROOT"/apps/*/apps.py; do
        [ -f "$p" ] || continue
        p=${p#"$ROOT"/}
        is_platform_app_path "$p" && continue
        census_names tree "$p" "${p%/apps.py}/migrations" >>"$COLL_TMP/yours" || {
            echo "!! $p (or its migrations) could not be read — could-not-look" >&2
            census_exit 2
        }
    done

    # THE PAIRS, one line each and a remedy under each. A label pair names the
    # two app directories; every other class names the two migration files.
    awk -F'\t' -v ref="$AGAINST" -v remedy="$COLL_REMEDY" -v kremedy="$COLL_KIND_REMEDY" \
        -v mremedy="$COLL_MOUNT_REMEDY" -v tremedy="$COLL_TAG_REMEDY" -v out="$COLL_TMP/counts" '
        FNR == NR {
            if ($1 == "label" || $1 == "table" || $1 == "index" || $1 == "constraint" || $1 == "kind" || $1 == "mount" || $1 == "tag")
                if (!(($1, $2) in rel)) rel[$1, $2] = $3
            next
        }
        ($1 == "mount" || $1 == "tag") && $2 ~ /^djb_/ {
            printf "collision: reserved prefix djb_ — %s %s in %s (yours); djb_ is the template%cs namespace for its platform apps\n", $1, $2, $3, 39
            printf "   %s\n", ($1 == "mount") ? mremedy : tremedy
            n["reserved"]++
            next
        }
        ($1 == "mount" || $1 == "tag") && (($1, $2) in rel) {
            printf "collision: %s %s — yours (%s) vs %s (%s)\n", $1, $2, $3, ref, rel[$1, $2]
            printf "   %s\n", ($1 == "mount") ? mremedy : tremedy
            n[$1]++
            next
        }
        $1 == "kind" && (($1, $2) in rel) {
            printf "collision: kind %s — yours (%s) vs %s (%s)\n", $2, $3, ref, rel[$1, $2]
            printf "   %s\n", kremedy
            n["kind"]++
            next
        }
        $1 == "label" && $2 ~ /^djb_/ {
            printf "collision: reserved prefix djb_ — %s (yours); djb_ is the template%cs namespace for its platform apps\n", $3, 39
            printf "   %s\n", remedy
            n["reserved"]++
        }
        ($1 == "label" || $1 == "table" || $1 == "index" || $1 == "constraint") && (($1, $2) in rel) {
            if ($1 == "label")
                printf "collision: label %s — %s (yours) vs %s (%s)\n", $2, $3, rel[$1, $2], ref
            else
                printf "collision: %s %s — yours (%s) vs %s (%s)\n", $1, $2, $3, ref, rel[$1, $2]
            printf "   %s\n", remedy
            n[$1]++
        }
        $1 == "unparsed" { printf "   unparsed: %s (yours) — no migrations/ directory: its label was read, its tables, indexes and constraints were not\n", $2 }
        END {
            printf "%d %d %d %d %d %d %d %d\n", n["label"], n["table"], n["index"], n["constraint"], n["kind"], n["reserved"], n["mount"], n["tag"] > out
        }
    ' "$COLL_TMP/release" "$COLL_TMP/yours"
    [ -s "$COLL_TMP/counts" ] || {
        echo "!! the collision pairing wrote no counts — could-not-look" >&2
        census_exit 2
    }
    read -r c_label c_table c_index c_constraint c_kind c_reserved c_mount c_tag <"$COLL_TMP/counts"
    awk -F'\t' '$1 == "unparsed" { printf "   unparsed: %s (%s) — no migrations/ directory\n", $2, "release" }' "$COLL_TMP/release"
    rel_parsed=$(awk -F'\t' '$1 == "parsed"' "$COLL_TMP/release" | wc -l | tr -d ' ')
    rel_unparsed=$(awk -F'\t' '$1 == "unparsed"' "$COLL_TMP/release" | wc -l | tr -d ' ')
    your_parsed=$(awk -F'\t' '$1 == "parsed"' "$COLL_TMP/yours" | wc -l | tr -d ' ')
    your_unparsed=$(awk -F'\t' '$1 == "unparsed"' "$COLL_TMP/yours" | wc -l | tr -d ' ')
    COLL_PAIRS=$((c_label + c_table + c_index + c_constraint + c_kind + c_reserved + c_mount + c_tag))
    printf 'collisions: labels=%s tables=%s indexes=%s constraints=%s kinds=%s reserved=%s mounts=%s tags=%s · release %s parsed=%s unparsed=%s · yours parsed=%s unparsed=%s\n' \
        "$c_label" "$c_table" "$c_index" "$c_constraint" "$c_kind" "$c_reserved" "$c_mount" "$c_tag" \
        "$AGAINST" "$rel_parsed" "$rel_unparsed" "$your_parsed" "$your_unparsed"
    if [ "$rel_parsed" -eq 0 ]; then
        echo "!! the release at $AGAINST carries not one app with migrations — this reader is" >&2
        echo "   looking at something that is not a release of this template. Could-not-look." >&2
        COLL_PAIRS=0
        census_exit 2
    fi
    if [ "$COLL_PAIRS" -eq 0 ]; then
        say "collisions: none against $AGAINST"
    fi
    rm -rf "$COLL_TMP"
    COLL_TMP=""
fi

if ! declare_base; then
    if [ "$IF_DECLARED" = 1 ]; then
        say "   base       none declared — SKIPPED"
        say "   A tree with no declared base is not a tree with no divergences. This"
        say "   is the template's own shape: it has no template. A product declares"
        say "   its base in scripts/local/template-base, or by adding a git remote"
        say "   named 'template', or by typing DJB_TEMPLATE_BASE."
    else
        echo "!! NO BASE IS DECLARED, so there is nothing to compare this tree against." >&2
        echo "   Declare one of the three, in this order of precedence:" >&2
        echo "     DJB_TEMPLATE_BASE=<ref> $0" >&2
        echo "     echo <ref> > scripts/local/template-base" >&2
        echo "     git remote add template <url> && git fetch template --tags" >&2
        echo "       (then the tag v<TEMPLATE_VERSION> is the base)" >&2
        echo "   Could-not-look, not a clean tree." >&2
    fi
fi

# --- the owned set, derived over the whole tree -----------------------------
OWNED=$(mktemp "${TMPDIR:-/tmp}/djb-divergence-owned.XXXXXX") || census_exit 2
SEEN=$(mktemp "${TMPDIR:-/tmp}/djb-divergence-seen.XXXXXX") || census_exit 2
cleanup() { rm -f "$OWNED" "$SEEN"; }

# TRACKED PLUS UNTRACKED-AND-NOT-IGNORED, which is the set the gate itself
# measures (`git add -A`, scripts/gate_ledger.sh). A product's new leg dropped
# into `scripts/` is a divergence the moment it exists, not the moment somebody
# remembers to commit it — and a `*.log` or a `.env` is ignored here exactly as
# it is ignored everywhere else.
{
    git ls-files
    git ls-files --others --exclude-standard
} | LC_ALL=C sort -u >"$SEEN" || {
    echo "!! git could not list this tree — could-not-look, never an empty census" >&2
    census_exit 2
}
[ -s "$SEEN" ] || {
    echo "!! the census saw no paths at all — this reader is looking at the wrong" >&2
    echo "   tree, and that is a could-not-look, never an empty owned set." >&2
    census_exit 2
}

# THE REDIRECT IS ON THE LOOP, NOT ON THE `printf`. A `>>` inside the body
# opens and closes the file once per matching path — 754 of them on this tree,
# and the census spent five of its six seconds there. One open, one close.
n_owned=0
while IFS= read -r p; do
    [ -n "$p" ] || continue
    ownership_of "$p"
    if [ "$OWNERSHIP" = template ]; then
        printf '%s\n' "$p"
        n_owned=$((n_owned + 1))
    fi
done <"$SEEN" >"$OWNED"

say "   owned      $n_owned template-owned paths (derived: the publication bucket"
say "              rules in scripts/archaeology_lib.sh, less the drawers and the"
say "              shared set; docs/product/build-contract.md § Ownership is the table)"
say "   drawers    $DRAWER_GLOB_COUNT reserved paths are the product's wherever they appear ($DRAWER_GLOBS)"

if [ "$n_owned" -eq 0 ]; then
    echo "!! not one template-owned path in this tree. The classifier is reading" >&2
    echo "   something that is not a checkout of this template — could-not-look," >&2
    echo "   never a clean census." >&2
    printf 'census: owned=0 drawers=%s base=none diverged=0 unnamed=0\n' "$DRAWER_GLOB_COUNT"
    census_exit 2
fi

if [ -z "$BASE" ]; then
    printf 'census: owned=%s drawers=%s base=none diverged=0 unnamed=0\n' \
        "$n_owned" "$DRAWER_GLOB_COUNT"
    if [ "$IF_DECLARED" = 1 ]; then
        say "== SKIPPED · no base declared · $n_owned template-owned paths were classified"
        census_exit 0
    fi
    census_exit 2
fi

say "   base       $BASE  (from $BASE_FROM)"
if ! git rev-parse -q --verify "$BASE^{commit}" >/dev/null 2>&1; then
    echo "!! the declared base does not resolve to a commit in this checkout: $BASE" >&2
    echo "   (declared by $BASE_FROM)" >&2
    echo "   A tag you have not fetched is not a base. Fetch it and re-run:" >&2
    echo "     git fetch template --tags" >&2
    echo "   This census writes nothing, so it will not fetch for you." >&2
    printf 'census: owned=%s drawers=%s base=unresolved diverged=0 unnamed=0\n' \
        "$n_owned" "$DRAWER_GLOB_COUNT"
    census_exit 2
fi

# --- the named divergences, out of the product's own architecture.md --------
# THE GRAMMAR IS ONE LINE: `divergence: <path> — <reason>`. Greppable on
# purpose, the way the ADR grammar in that same file is: a reader looking for
# "what have we changed and why" finds every answer with one search, and this
# census finds them with the same one.
NAMED=""
ARCH="$ROOT/docs/product/architecture.md"
if [ -f "$ARCH" ]; then
    NAMED=$(sed -n 's/.*divergence:[[:space:]]*`\{0,1\}\([^`[:space:]]*\)`\{0,1\}.*/\1/p' "$ARCH" |
        LC_ALL=C sort -u || true)
fi
is_named() {
    case "
$NAMED
" in
    *"
$1
"*) return 0 ;;
    esac
    return 1
}
# --- the comparison ---------------------------------------------------------
# IT DIFFS THE WHOLE TREE AND FILTERS AFTERWARDS, rather than handing git the
# owned list as a pathspec. The owned set is several hundred paths, and a
# pathspec that long is an ARG_MAX bet on somebody else's machine and a
# word-splitting bet on a path with a space in it. Filtering the OUTPUT through
# the same classifier the count above used is one reader, unbounded in the size
# of the tree, and it cannot disagree with the count.
#
# `git diff <base>` reads the WORKING TREE against the base, which is the tree
# the gate measures (`git add -A`) and the tree a fold is about to hand to a
# merge. At a fold those are the same thing — everything is committed — and
# between commits the working tree is the honest answer; reading HEAD there
# would vouch for bytes nobody has.
#
# `--no-renames`, deliberately: a rename is reported as the deletion and the
# addition it is, which is the declared blind spot at the head of this file
# rather than a silent similarity score.
say ""
say "-- divergences: a template-owned path whose content is not the base's"
DIFF_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-divergence-diff.XXXXXX") || census_exit 2
FOUND=$(mktemp "${TMPDIR:-/tmp}/djb-divergence-found.XXXXXX") || census_exit 2
cleanup() { rm -f "$OWNED" "$SEEN" "$DIFF_OUT" "$FOUND"; }

set +e
git diff --numstat --no-renames "$BASE" >"$DIFF_OUT" 2>/dev/null
diff_rc=$?
set -e
if [ "$diff_rc" -ne 0 ]; then
    echo "!! git diff against $BASE failed (exit $diff_rc) — could-not-look, never a" >&2
    echo "   clean census." >&2
    printf 'census: owned=%s drawers=%s base=%s diverged=0 unnamed=0\n' \
        "$n_owned" "$DRAWER_GLOB_COUNT" "$BASE"
    census_exit 2
fi
while IFS=$'\t' read -r added removed path; do
    [ -n "$path" ] || continue
    ownership_of "$path"
    [ "$OWNERSHIP" = template ] || continue
    printf '%s\t%s\t%s\n' "$added" "$removed" "$path"
done <"$DIFF_OUT" >"$FOUND"

# AN UNTRACKED OWNED PATH IS A DIVERGENCE `git diff` CANNOT SEE: it is not in
# the index, so there is nothing for the base to be compared with, and it drops
# out of every numstat silently. "A file the template does not have, in a
# directory the template owns" is the exact shape the drawer exists to take out
# of the system layer, so it is reported with no line count rather than lost.
while IFS= read -r path; do
    [ -n "$path" ] || continue
    ownership_of "$path"
    [ "$OWNERSHIP" = template ] || continue
    printf 'new\t-\t%s\n' "$path"
done < <(git ls-files --others --exclude-standard) >>"$FOUND"

n_div=0
n_unnamed=0
if [ -s "$FOUND" ]; then
    while IFS=$'\t' read -r added removed path; do
        [ -n "$path" ] || continue
        n_div=$((n_div + 1))
        last=$(git log -1 --format='%h %s' -- "$path" 2>/dev/null || true)
        [ -n "$last" ] || last="(no commit yet — untracked in this checkout)"
        # A NEW FILE HAS NO ±, and printing one would be a number nobody
        # measured. `-  -` is numstat's own answer for a binary file, and it
        # is left exactly as numstat gave it for the same reason.
        if [ "$added" = new ]; then
            delta="a file the base does not have"
        else
            delta="+$added-$removed"
        fi
        if is_named "$path"; then
            printf '   named-divergence: %s · %s · %s\n' "$path" "$delta" "$last"
        else
            n_unnamed=$((n_unnamed + 1))
            printf '   divergence: %s · %s · %s\n' "$path" "$delta" "$last"
        fi
    done <"$FOUND"
else
    say "   none"
fi

printf 'census: owned=%s drawers=%s base=%s diverged=%s unnamed=%s\n' \
    "$n_owned" "$DRAWER_GLOB_COUNT" "$BASE" "$n_div" "$n_unnamed"

if [ "$n_unnamed" -gt 0 ]; then
    say ""
    say "== $n_unnamed UNNAMED DIVERGENCE(S) · $n_div diverged of $n_owned template-owned paths"
    say "   A template-owned file carries no product edits. Either move the change"
    say "   into the drawer beside it — a local/ sibling the template's own reader"
    say "   discovers and never ships — or record it in docs/product/architecture.md"
    say "   as the deliberate divergence it is, one line each:"
    while IFS=$'\t' read -r _a _r path; do
        [ -n "$path" ] || continue
        is_named "$path" || say "     divergence: $path — <why this product needs it>"
    done <"$FOUND"
    census_exit 1
fi
say ""
if [ "$n_div" -gt 0 ]; then
    say "== CLEAN · $n_div divergence(s), every one of them named in architecture.md"
else
    say "== CLEAN · no template-owned file in this tree differs from $BASE"
fi
census_exit 0
