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
#
# Exit: 0 nothing diverged, or every divergence is NAMED in the product's own
#       `architecture.md` · 1 an unnamed divergence (the path, and the line to
#       add) · 2 COULD NOT LOOK — no checkout, no base, a base that does not
#       resolve, a git read that failed. 2 outranks a pass here the way it does
#       in `scripts/check.sh`, and for the same reason: a census that could not
#       read the base has not found a clean tree, it has found nothing.
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
census_exit() {
    CENSUS_END=1
    exit "$1"
}
census_on_exit() {
    local status=$1
    cleanup
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
while [ "$#" -gt 0 ]; do
    case "$1" in
    --if-declared)
        IF_DECLARED=1
        shift
        ;;
    *)
        echo "!! unknown argument '$1': divergence_census.sh takes nothing or --if-declared" >&2
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
    case " $PLATFORM_APPS " in
    *" $label "*) return 0 ;;
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
    # CI composes one workflow and the product may add its own beside it.
    .github/workflows/ci.yml)
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
    # The six standing documents the contract names, and no others: a product's
    # own `architecture.md` is where it records its decisions AND its
    # divergences, so it cannot be one.
    docs/product/build-contract.md | docs/product/instruments.md | \
        docs/product/partition-closure.md | docs/product/publication-manifest.md | \
        docs/product/api-editorial-standard.md | docs/product/scale-envelope.md)
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
