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
# drives: quality/partition.yaml scripts/archaeology_lib.sh scripts/divergence_census.sh scripts/gate_refuse.sh
# cites: scripts/pm_fold.sh docs/product/build-contract.md scripts/queue_cited.sh scripts/kill_mine.sh scripts/sweep.sh scripts/check.sh scripts/publish.sh scripts/tests/test_gate_lease.sh scripts/tests/test_publish.sh scripts/tests/drive_preamble.sh TEMPLATE_VERSION docs/product/instruments.md docs/product/architecture.md apps/core/roles.py apps/core/api/frozen_families.py pyproject.toml docs/product/queue.md apps/core/services.py quality/gate.py scripts/local/template-base scripts/local/legs
# The refusal-and-property drive for `scripts/divergence_census.sh`.
#
# Exit: 0 every case held · 1 a case did not hold · 2 COULD NOT LOOK (no git, a
#       fixture that would not build). 2 outranks a pass here for the reason it
#       does everywhere.
#
# WHY IT EXISTS. The census answers a question NOBODY IN THIS REPOSITORY CAN
# ASK: the template has no template, so every interesting state of this
# instrument — a base, a divergence, a named divergence — is one this checkout
# by construction cannot be in. A guard whose whole subject is invisible from
# the tree it lives in is a guard nobody has ever watched fire, and that is the
# class this drive exists to end. Every case below is a PRODUCT's tree, built
# here from nothing.
#
# IT BUILDS ITS OWN PRODUCT. Each case runs against a throwaway repository
# under `mktemp -d` carrying a copy of the census, the classifier it sources
# and a minimal file per ownership class — so nothing in this checkout is read
# or written, and the drive's verdict does not move when the real tree does.
# The fixture's TEMPLATE_VERSION is 0.x on purpose: a reader can never mistake
# a line of this output for a statement about the real template's releases.
#
# THE ONE THING IT CANNOT DRIVE: whether `scripts/check.sh` runs this drive at
# all. That file was another rung's exclusive territory in the wave that wrote
# this one, so registration is a DECLARED DEBT reported rather than taken —
# the same debt `scripts/tests/test_publish.sh` carried for a cycle, booked in
# `docs/product/instruments.md` beside it. By hand is a promise; a leg is a
# measurement.
set -euo pipefail

if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! this drive refuses pipes — its exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/../.."

# The preamble, before anything asks git a question: this drive builds
# throwaway repositories and talks to them with `git -C "$REPO" …`, which
# writes into the REAL repository instead whenever it inherits an absolute
# `GIT_DIR` — which it does when it is run from the pre-push hook.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_divergence_census: scripts/tests/drive_preamble.sh is not in this" >&2
    echo "   tree. It carries the neutralisation that keeps every fixture repository" >&2
    echo "   below out of the real one. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
# AFTER the source, never before: the preamble assigns this variable 0 itself.
DRIVE_OPTED_IN_TO_FINISH=1

ROOT=$(pwd -P)
CENSUS="$ROOT/scripts/divergence_census.sh"
[ -x "$CENSUS" ] || {
    echo "!! $CENSUS is not executable — nothing to drive" >&2
    exit 2
}
command -v git >/dev/null 2>&1 || {
    echo "!! no git" >&2
    exit 2
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-divergence.XXXXXX") || exit 2
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

PASS=0
FAIL=0
ok() {
    PASS=$((PASS + 1))
    printf '   ok    %s\n' "$*"
}
bad() {
    FAIL=$((FAIL + 1))
    printf '   FAIL  %s\n' "$*"
}

REPO="$WORK/product"

# --- the fixture: a PRODUCT, one tracked file per ownership class ------------
# THE SMALLEST TREE THAT EXERCISES EVERY CLASS is also the clearest statement
# of what the classes are. One template-owned script, one template-owned
# platform app, one product app, one shared file, one ledger, one standing
# document — and the census's own two inputs, copied rather than stubbed so a
# case here is driving the real classifier.
gitq() {
    local d=$1
    shift
    git -C "$d" -c user.name=t -c user.email=t@t \
        -c commit.gpgsign=false -c tag.gpgsign=false "$@"
}

build_repo() {
    local d=$1
    rm -rf "$d"
    mkdir -p "$d/scripts/tests" "$d/quality" "$d/docs/product" \
        "$d/apps/core/api" "$d/apps/zzz_product_app" "$d/config" "$d/deploy"
    cp "$CENSUS" "$d/scripts/divergence_census.sh"
    chmod +x "$d/scripts/divergence_census.sh"
    # The classifier the census sources, and the seam THAT library sources. A
    # fixture that copies a seam library without its seam dies at the `.` line
    # — the population is pinned by
    # case_every_fixture_that_copies_a_seam_library_copies_the_seam in
    # scripts/tests/test_gate_lease.sh.
    cp "$ROOT/scripts/archaeology_lib.sh" "$d/scripts/archaeology_lib.sh"
    cp "$ROOT/scripts/gate_refuse.sh" "$d/scripts/gate_refuse.sh"
    # The partition closure, reduced to the one thing the census reads out of
    # it: which apps the template owns. `zzz_product_app` is deliberately NOT
    # in it — it is the product's own app, and everything under it is theirs.
    #
    # WHY THE NAME CARRIES `zzz_`, AND WHY THIS PARAGRAPH NAMES NO REAL APP.
    # The fixture app used to be called after an ordinary business noun, and
    # the first consumer's bank is what renamed it: a fixture app name is a
    # path this drive SPELLS, the drive-keying floor judges every spelled path
    # the measured tree really has, and that noun was one of their own apps.
    # So a fixture name a product might ship made this drive refuse to key on
    # that product and nowhere else. The convention is the plant convention
    # `test_gate_explain.sh` already uses one directory over: a `zzz_` name no
    # product can own — and the old name is described here rather than typed,
    # because typing it would reintroduce exactly the path this rename removed.
    printf 'schema: v1\n\nplatform_apps:\n  - core\n\nclosure_classes: []\n' \
        >"$d/quality/partition.yaml"
    printf '0.1.0\n' >"$d/TEMPLATE_VERSION"
    printf '# architecture — the product'"'"'s own decisions\n\n**Status: standing.**\n' \
        >"$d/docs/product/architecture.md"
    printf '# the gate\n' >"$d/scripts/check.sh"
    printf '# a template-owned script\n' >"$d/scripts/x.sh"
    printf '# settings\n' >"$d/config/settings.py"
    printf '# the platform app\n' >"$d/apps/core/services.py"
    printf 'ROLES = {}\n' >"$d/apps/core/roles.py"
    printf 'FAMILIES = {}\n' >"$d/apps/core/api/frozen_families.py"
    printf '# the product'"'"'s own app\n' >"$d/apps/zzz_product_app/models.py"
    printf '# queue — the product'"'"'s ledger\n' >"$d/docs/product/queue.md"
    printf '# the build contract\n' >"$d/docs/product/build-contract.md"
    printf '[project]\n' >"$d/pyproject.toml"
    (
        cd "$d"
        git init -q -b main
        gitq "$d" add -A
        gitq "$d" commit -q -m "the template at v0.1.0"
        gitq "$d" tag -a v0.1.0 -m v0.1.0 HEAD
    )
}

run() { # run <dir> <args...>; output to $OUT, status to $RC
    local d=$1
    shift
    OUT="$WORK/out.$$"
    set +e
    (cd "$d" && ./scripts/divergence_census.sh "$@") >"$OUT" 2>&1
    RC=$?
    set -e
}

commit_all() { gitq "$REPO" add -A && gitq "$REPO" commit -q -m "$1"; }

# >>> one case, by name >>>
# `--case <name>` runs exactly that case and nothing else. The seam exists so
# rule 60's drawer census can prove ONE PLANT PER DRAWER through the drive that
# already owns the property, rather than re-implementing the drawer's reader —
# a second implementation of a reader is a second opinion about it. A name this
# file does not define is exit 2, never a silent run of nothing.
ONLY_CASE=""
run_case() {
    [ -z "$ONLY_CASE" ] || [ "$1" = "$ONLY_CASE" ] || return 0
    "$@"
}
case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
--case)
    [ -n "${2:-}" ] || {
        echo "!! --case needs a case name; --list names them" >&2
        exit 2
    }
    grep -q "^${2}() {" "$0" || {
        echo "!! --case: test_divergence_census.sh defines no case named '${2}'; --list names them" >&2
        exit 2
    }
    ONLY_CASE="$2"
    ;;
*)
    echo "!! unknown argument '$1': test_divergence_census.sh takes nothing, --list or --case <name>" >&2
    exit 2
    ;;
esac

# --- THE DRAWER CASE, named because rule 60's table names it ----------------
# The one block of this drive that is a `drawers` row's `case` column
# (`docs/product/build-contract.md` § The drawers), which is why it is a
# function with a name while the rest of this linear drive is not:
# the engine's drawer census — `quality/gate.py::drawers_leg`, run by
# `python -m quality.gate --selftest` — runs exactly the cases that column
# names, and a block with no name cannot be named. It uses the fixture the
# prelude builds, so `--case` pays that build and nothing else.
case_the_declared_base_is_read_from_the_product_drawer() {
    unset DJB_TEMPLATE_BASE
    mkdir -p "$REPO/scripts/local"
    printf '%s\n' "$BASE" >"$REPO/scripts/local/template-base"
    run "$REPO"
    # ONE NEEDLE, BOTH HALVES. The source label alone was the whole assertion
    # and it is not enough: a census that read the drawer and then compared
    # against some OTHER ref would print that label and pass. The line the
    # census writes is `base <ref>  (from <source>)`, so the ref and its source
    # are asserted together, spacing and all.
    if [ "$RC" = 0 ] && grep -qE "base +${BASE} +\(from scripts/local/template-base\)" "$OUT"; then
        ok "the base is read from the drawer — and the ref compared against is the one the drawer declares"
    else
        bad "drawer declaration: exit $RC, want 0 and 'base ${BASE}  (from scripts/local/template-base)'"
        sed 's/^/         /' "$OUT"
    fi
    : >"$REPO/scripts/local/template-base"
    run "$REPO"
    if [ "$RC" = 2 ] && grep -q "is empty" "$OUT"; then
        ok "an EMPTY declaration is exit 2 — a declaration that names no ref is not one"
    else
        bad "empty declaration: exit $RC, want 2"
    fi
    rm -rf "$REPO/scripts/local"
}

# --- (a) THE DRAWER COUNT IS THE LIST, NOT THE FILESYSTEM ------------------
# `DRAWER_GLOBS` is a list of PATTERNS and its length is derived from it with
# `set --`, which splits AND GLOBS. Every member is a pathname pattern, so on
# any tree that actually HAS the drawers — which is every product, and none of
# the template's own checkouts — the shell expanded them against the tree and
# the count read the number of files it found. MEASURED on the first
# consumer's: 6 instead of 3. Rule 60's `drawer_globs` floor reads that
# number, so the floor was being met by the filesystem rather than by the list,
# and it failed SILENT IN THE PASSING DIRECTION: a member deleted from the list
# would still clear a floor that three files in one drawer could satisfy on
# their own. The victim is this case's own — drawers planted into the fixture
# product, which is the state the count has to be right in.
case_the_drawer_count_is_the_list_and_not_the_filesystem() {
    export DJB_TEMPLATE_BASE="$BASE"
    run "$REPO"
    local bare
    bare=$(sed -n 's/^census:.*drawers=\([0-9]*\).*/\1/p' "$OUT")

    # THE DRAWERS, PLANTED — one per pattern, which is what makes the
    # expansion reachable at all.
    mkdir -p "$REPO/quality/local/canary/x-1" "$REPO/scripts/local/legs"
    printf 'rule_id_namespace: acme\n' >"$REPO/quality/local/rules.yaml"
    printf 'rule: x-1 — a drawer rule fixture\n' >"$REPO/quality/local/canary/x-1/plan.md"
    printf '# a product leg\n' >"$REPO/scripts/local/legs/a.sh"
    run "$REPO"
    local withdrawers
    withdrawers=$(sed -n 's/^census:.*drawers=\([0-9]*\).*/\1/p' "$OUT")
    if [ "$RC" = 0 ] && [ "$withdrawers" = "$bare" ] && [ "$withdrawers" = 3 ]; then
        ok "the reserved count is 3 with drawers on the tree and 3 without — the list is counted as text, not expanded against the tree"
    else
        bad "drawer count: exit $RC, $bare without drawers and $withdrawers with, want 3 and 3"
        sed 's/^/         /' "$OUT"
    fi
    # AND THE PATTERNS ARE STILL PATTERNS IN THE PRINTED LINE. The count and
    # the text come from the same variable, so a line that had expanded would
    # name four directories where it should name two globs and a path.
    if grep -q 'reserved paths are the product' "$OUT" &&
        grep -q '(\*\*/local/\*\* \*\.local\.md apps/conftest_local\.py)' "$OUT"; then
        ok "and the line prints the three patterns themselves, not what they happened to match"
    else
        bad "the drawers line does not print the literal patterns"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$REPO/quality/local" "$REPO/scripts/local"
    unset DJB_TEMPLATE_BASE
}

# --- (b) THE SCRIPT AND THE LIBRARY SHIP TOGETHER ---------------------------
# Item 1 of the release notes tells a product to run this census BEFORE it
# merges — which is the one tree where the new script sits beside the OLD
# library. The first consumer did exactly that and the census died
# `RULES_FOR: unbound variable`, mid-classification, blaming nothing. The
# victim here is this case's own: a repository built from nothing, whose
# library is rewritten into the shape the previous release's really had —
# `rules_for` echoing and setting no variable.
case_a_library_that_sets_no_rules_for_is_exit_2_naming_both_files_to_take() {
    local old="$WORK/oldlib"
    build_repo "$old" || {
        bad "the old-library fixture would not build"
        return 0
    }
    # The previous release's `rules_for`: it printed the answer and kept none.
    # Rewritten out of the real library rather than hand-written, so the case
    # is driving the actual idiom and not a guess at it.
    awk '
        /^    RULES_FOR=\$\{hit# \}$/ { next }
        /^    printf .%s. "\$RULES_FOR"$/ { print "    printf \"%s\" \"${hit# }\""; next }
        { print }
    ' "$old/scripts/archaeology_lib.sh" >"$old/scripts/archaeology_lib.new" &&
        mv "$old/scripts/archaeology_lib.new" "$old/scripts/archaeology_lib.sh"
    if grep -q 'RULES_FOR=' "$old/scripts/archaeology_lib.sh"; then
        bad "the old-library fixture still sets RULES_FOR — the rewrite did not take"
        return 0
    fi
    # THE TAG IS A PLACEHOLDER AND THAT IS THE ASSERTION. The first version of
    # this refusal DERIVED it from the checkout's own version file, which reads
    # well and is wrong every time it fires: the refusal only happens on a tree
    # that has not merged yet, so that file names the release the product is
    # already ON — the one whose library is the problem. The fixture below is
    # v0.1.0 and the refusal must NOT say so.
    local want='v<the release you are folding>'
    run "$old" --if-declared
    if [ "$RC" = 2 ] &&
        grep -q "git show ${want}:scripts/divergence_census.sh" "$OUT" &&
        grep -q "git show ${want}:scripts/archaeology_lib.sh" "$OUT"; then
        ok "a library that sets no \$RULES_FOR is exit 2, naming BOTH files to take at '${want}'"
    else
        bad "old library: exit $RC, want 2 naming both files at '${want}'"
        sed 's/^/         /' "$OUT"
    fi
    if grep -q "v$(tr -d '[:space:]' <"$old/TEMPLATE_VERSION"):scripts/" "$OUT"; then
        bad "the refusal named this checkout's OWN version — on a pre-merge tree that is the release whose library is the problem"
        sed 's/^/         /' "$OUT"
    else
        ok "and it does NOT name this checkout's own version, which on a pre-merge tree is the wrong tag by construction"
    fi
    # AND IT IS A REFUSAL, NOT A DEATH: the shell never ran the classifier, so
    # the census must not also print the exit guard's banner over it.
    if grep -q "DIED part-way" "$OUT"; then
        bad "the pairing refusal reached the exit guard — an authored end must not read as a death"
    else
        ok "the pairing refusal is an authored end, not the guard's banner"
    fi
    rm -rf "$old"
}

# --- (c) AN UNMARKED END IS EXIT 2, WHATEVER THE TRAP SAW -------------------
# MEASURED, and it is why this guard exists: on GNU bash 3.2.57 (macOS, and
# what `/bin/bash` is there) a `set -u` death reaches the EXIT trap with
# `$? = 0`. The consumer's pre-merge run therefore DIED and exited 0, and the
# fold read it as a census with nothing to say. The repro is three lines and it
# is written out in `scripts/tests/drive_preamble.sh` §5; `scripts/pm_fold.sh`
# carries the same guard for the same reason.
case_a_death_part_way_is_exit_2_on_every_bash() {
    local dead="$WORK/deadcensus"
    build_repo "$dead" || {
        bad "the planted-death fixture would not build"
        return 0
    }
    # The victim is this case's own copy, and the plant goes in AFTER the trap
    # is armed and BEFORE any end the script authors — which is the whole
    # window the guard is a guard over.
    awk '
        { print }
        /^trap .census_on_exit \$\?. EXIT$/ { print ": \"$A_VARIABLE_NOTHING_EVER_SETS\"" }
    ' "$dead/scripts/divergence_census.sh" >"$dead/scripts/divergence_census.new" &&
        mv "$dead/scripts/divergence_census.new" "$dead/scripts/divergence_census.sh" &&
        chmod +x "$dead/scripts/divergence_census.sh"
    if ! grep -q 'A_VARIABLE_NOTHING_EVER_SETS' "$dead/scripts/divergence_census.sh"; then
        bad "the death plant did not take"
        rm -rf "$dead"
        return 0
    fi
    run "$dead"
    if [ "$RC" = 2 ] && grep -q "DIED part-way" "$OUT"; then
        ok "a death part-way is exit 2 and says nothing it printed is a verdict ($(bash --version | head -1))"
    else
        bad "planted death: exit $RC, want 2 with the guard's banner"
        sed 's/^/         /' "$OUT"
    fi
    # THE BASH THE MEASUREMENT WAS MADE ON, named explicitly. `/bin/bash` is
    # 3.2.57 on macOS and that is the regime where the trap reads 0; a box
    # whose /bin/bash is 5.x runs the same assertion and passes it for the
    # other reason (wordless non-zero), which is exactly the point of a
    # predicate that is not the status.
    if [ -x /bin/bash ]; then
        OUT="$WORK/out.slashbin"
        set +e
        (cd "$dead" && /bin/bash scripts/divergence_census.sh) >"$OUT" 2>&1
        RC=$?
        set -e
        if [ "$RC" = 2 ] && grep -q "DIED part-way" "$OUT"; then
            ok "and on /bin/bash ($(/bin/bash --version | head -1)) — the regime where the trap reads \$? = 0"
        else
            bad "/bin/bash planted death: exit $RC, want 2"
            sed 's/^/         /' "$OUT"
        fi
    fi
    rm -rf "$dead"
}

build_repo "$REPO" || {
    echo "!! the fixture would not build" >&2
    exit 2
}
BASE=$(git -C "$REPO" rev-parse HEAD)

# THE NAMED CASE ALONE, and then out: the rest of this drive is one linear
# sequence over a shared fixture, so there is nothing else `--case` could
# select without running everything before it anyway.
if [ -n "$ONLY_CASE" ]; then
    run_case "$ONLY_CASE"
    echo ""
    echo "== $PASS passed · $FAIL failed"
    drive_finished
    [ "$FAIL" -eq 0 ] || exit 1
    exit 0
fi

echo "== divergence_census.sh refusal + property drive"

# --- the base: three readers, and no default --------------------------------
run "$REPO"
if [ "$RC" = 2 ] && grep -q "NO BASE IS DECLARED" "$OUT"; then
    ok "no base declared is exit 2 — a census with nothing to compare against looked at nothing"
else
    bad "no base: exit $RC, want 2 naming the three declarations"
    sed 's/^/         /' "$OUT"
fi

run "$REPO" --if-declared
if [ "$RC" = 0 ] && grep -q "SKIPPED" "$OUT" && grep -q "census: owned=" "$OUT"; then
    ok "--if-declared with no base is exit 0 and SAYS it skipped — the template's own shape"
else
    bad "--if-declared, no base: exit $RC, want 0 with a printed SKIP"
    sed 's/^/         /' "$OUT"
fi

run "$REPO" --nonsense
[ "$RC" = 2 ] && ok "an unknown flag is exit 2, never a quietly different run" ||
    bad "unknown flag: exit $RC, want 2"

set +e
(cd "$REPO" && DJB_TEMPLATE_BASE="$BASE" ./scripts/divergence_census.sh | cat) >/dev/null 2>&1
rc=$?
set -e
[ "$rc" = 2 ] && ok "a piped stdout is refused (exit 2)" || bad "piped stdout: exit $rc, want 2"

# --- the clean product: nothing diverged ------------------------------------
export DJB_TEMPLATE_BASE="$BASE"
run "$REPO"
if [ "$RC" = 0 ] && grep -q "^== CLEAN" "$OUT"; then
    ok "a product that changed nothing is exit 0"
else
    bad "clean product: exit $RC, want 0"
    sed 's/^/         /' "$OUT"
fi
OWNED_BASE=$(sed -n 's/^census: owned=\([0-9]*\).*/\1/p' "$OUT")

# --- the owned set is DERIVED: a new path under an owned glob is seen -------
# The whole reason the classifier is shared with `scripts/publish.sh` rather
# than typed here: a file class that lands next month is classified the day it
# lands, with no edit to this census. `deploy/` is bucket R3 exactly as
# `scripts/` is, and nothing in the census names it.
printf '# a product stage step\n' >"$REPO/deploy/provision_extra.sh"
commit_all "a new R3 path"
run "$REPO"
OWNED_NOW=$(sed -n 's/^census: owned=\([0-9]*\).*/\1/p' "$OUT")
if [ "$RC" = 1 ] && grep -q "divergence: deploy/provision_extra.sh" "$OUT" &&
    [ "$OWNED_NOW" = "$((OWNED_BASE + 1))" ]; then
    ok "the owned set is derived: a new R3 path joins it ($OWNED_BASE → $OWNED_NOW) and is a divergence"
else
    bad "derived owned set: exit $RC, owned $OWNED_BASE → $OWNED_NOW, want 1 and +1"
    sed 's/^/         /' "$OUT"
fi
gitq "$REPO" rm -q deploy/provision_extra.sh
commit_all "undo"

# --- a product edit in a template-owned script ------------------------------
printf '# our own leg, re-applied every release\n' >>"$REPO/scripts/x.sh"
commit_all "our edit"
EDIT_SHA=$(git -C "$REPO" rev-parse --short HEAD)
run "$REPO"
if [ "$RC" = 1 ] && grep -q "divergence: scripts/x.sh" "$OUT" && grep -q "$EDIT_SHA" "$OUT"; then
    ok "an edit in a template-owned script is exit 1, naming the path AND the commit"
else
    bad "template-owned edit: exit $RC, want 1 naming scripts/x.sh and $EDIT_SHA"
    sed 's/^/         /' "$OUT"
fi
if grep -q "divergence: scripts/x.sh — " "$OUT"; then
    ok "the refusal prints the LINE TO ADD, not only the complaint"
else
    bad "the refusal does not print the architecture.md line to add"
fi

# --- and naming it in architecture.md makes it a decision, not a defect -----
printf '\ndivergence: `scripts/x.sh` — our stage leg, until the template grows the drawer.\n' \
    >>"$REPO/docs/product/architecture.md"
commit_all "name the divergence"
run "$REPO"
if [ "$RC" = 0 ] && grep -q "named-divergence: scripts/x.sh" "$OUT"; then
    ok "a divergence NAMED in architecture.md is exit 0 — still listed, no longer a finding"
else
    bad "named divergence: exit $RC, want 0 listing it as named"
    sed 's/^/         /' "$OUT"
fi
gitq "$REPO" checkout -q "$BASE" -- scripts/x.sh docs/product/architecture.md
commit_all "undo"

# --- THE SILENT HALF: what is NOT a divergence ------------------------------
# A guard nobody has watched stay quiet is a guard nobody can trust to be quiet
# about the right things — and here the silent half IS the design: the drawer,
# the product's own app, the shared files and the ledgers are the four ways a
# product is supposed to be able to change this tree without a conversation.
silent_case() { # silent_case <label> <path> <how>
    local label=$1 path=$2 how=$3
    mkdir -p "$REPO/$(dirname "$path")"
    if [ "$how" = append ]; then
        printf '# the product changed this\n' >>"$REPO/$path"
    else
        printf '# the product wrote this\n' >"$REPO/$path"
    fi
    commit_all "product change: $path"
    run "$REPO"
    if [ "$RC" = 0 ] && ! grep -q "divergence: $path" "$OUT"; then
        ok "$label — $path is the product's, and the census is silent about it"
    else
        bad "$label: exit $RC, want 0 with no row for $path"
        sed 's/^/         /' "$OUT"
    fi
    if [ "$how" = append ]; then
        gitq "$REPO" checkout -q "$BASE" -- "$path"
    else
        gitq "$REPO" rm -q -r --ignore-unmatch "$path"
    fi
    commit_all "undo"
}

silent_case "the drawer" "scripts/local/legs/x.sh" create
silent_case "the product's own app" "apps/zzz_product_app/models.py" append
silent_case "the shared roles file" "apps/core/roles.py" append
silent_case "the shared frozen families" "apps/core/api/frozen_families.py" append
silent_case "a shared dependency manifest" "pyproject.toml" append
silent_case "a ledger" "docs/product/queue.md" append

# --- and the platform app IS template-owned, which is the other half --------
printf '# our patch to the platform app\n' >>"$REPO/apps/core/services.py"
commit_all "edit a platform app"
run "$REPO"
if [ "$RC" = 1 ] && grep -q "divergence: apps/core/services.py" "$OUT"; then
    ok "a platform app's code IS template-owned — the partition closure is what says which"
else
    bad "platform app edit: exit $RC, want 1 naming apps/core/services.py"
    sed 's/^/         /' "$OUT"
fi
gitq "$REPO" checkout -q "$BASE" -- apps/core/services.py
commit_all "undo"

# --- an UNTRACKED file in an owned directory --------------------------------
# `git diff` cannot see it — it is not in the index, so there is nothing for
# the base to be compared with, and it drops out of numstat silently. It is the
# exact shape the drawer exists to take out of the system layer.
printf '# not committed yet\n' >"$REPO/scripts/not_yet_committed.sh"
run "$REPO"
if [ "$RC" = 1 ] && grep -q "divergence: scripts/not_yet_committed.sh" "$OUT" &&
    grep -q "a file the base does not have" "$OUT"; then
    ok "an UNTRACKED file under an owned glob is a divergence git diff alone cannot see"
else
    bad "untracked owned path: exit $RC, want 1 naming it"
    sed 's/^/         /' "$OUT"
fi
rm -f "$REPO/scripts/not_yet_committed.sh"

# --- the base that does not resolve -----------------------------------------
set +e
(cd "$REPO" && DJB_TEMPLATE_BASE=v9.9.9 ./scripts/divergence_census.sh) >"$WORK/out.unres" 2>&1
rc=$?
set -e
if [ "$rc" = 2 ] && grep -q "does not resolve" "$WORK/out.unres"; then
    ok "a declared base that does not resolve is exit 2 — a tag you have not fetched is not a base"
else
    bad "unresolved base: exit $rc, want 2"
    sed 's/^/         /' "$WORK/out.unres"
fi

run_case case_the_declared_base_is_read_from_the_product_drawer
run_case case_the_drawer_count_is_the_list_and_not_the_filesystem
run_case case_a_library_that_sets_no_rules_for_is_exit_2_naming_both_files_to_take
run_case case_a_death_part_way_is_exit_2_on_every_bash

# --- the derived reader: a 'template' remote and TEMPLATE_VERSION -----------
UPSTREAM="$WORK/upstream"
git clone -q "$REPO" "$UPSTREAM" >/dev/null 2>&1 || bad "the upstream clone would not build"
gitq "$REPO" remote add template "$UPSTREAM"
run "$REPO"
if [ "$RC" = 0 ] && grep -q "v0.1.0" "$OUT" && grep -q "template' remote" "$OUT"; then
    ok "with a 'template' remote the base is DERIVED from TEMPLATE_VERSION — no configuration at all"
else
    bad "derived base: exit $RC, want 0 naming v0.1.0 and the remote"
    sed 's/^/         /' "$OUT"
fi
printf 'not-a-version\n' >"$REPO/TEMPLATE_VERSION"
run "$REPO"
if [ "$RC" = 2 ] && grep -q "TEMPLATE_VERSION does not read" "$OUT"; then
    ok "a TEMPLATE_VERSION that will not read is exit 2 — a derivation nobody can read is not a default"
else
    bad "unreadable TEMPLATE_VERSION: exit $RC, want 2"
fi
gitq "$REPO" checkout -q "$BASE" -- TEMPLATE_VERSION
gitq "$REPO" remote remove template

# --- the property the whole instrument rests on: IT WRITES NOTHING ----------
# Asserted rather than promised. A census that fetched, staged or regenerated
# anything would be a thing you cannot run at a fold without thinking about it,
# and the whole point is that you can.
export DJB_TEMPLATE_BASE="$BASE"
printf '# a divergence to make it do work\n' >>"$REPO/scripts/x.sh"
BEFORE=$(git -C "$REPO" status --porcelain; git -C "$REPO" rev-parse HEAD; git -C "$REPO" tag --list)
run "$REPO"
AFTER=$(git -C "$REPO" status --porcelain; git -C "$REPO" rev-parse HEAD; git -C "$REPO" tag --list)
if [ "$BEFORE" = "$AFTER" ] && [ "$RC" = 1 ]; then
    ok "the census writes nothing: status, HEAD and tags are byte-identical across a run that found work"
else
    bad "the census moved something: before/after differ, or exit $RC"
    printf '%s\n' "$BEFORE" | sed 's/^/         before /'
    printf '%s\n' "$AFTER" | sed 's/^/         after  /'
fi
gitq "$REPO" checkout -q -- scripts/x.sh
unset DJB_TEMPLATE_BASE

echo ""
echo "== $PASS passed · $FAIL failed"
drive_finished
[ "$FAIL" -eq 0 ] || exit 1
exit 0
