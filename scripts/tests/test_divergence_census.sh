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
# cites: .github/workflows .github/workflows/ci.yml .github/workflows/nightly-proof.yml scripts/pm_fold.sh docs/product/build-contract.md docs/product/design docs/product/design/patterns.md docs/product/design/patterns.local.md scripts/queue_cited.sh scripts/kill_mine.sh scripts/sweep.sh scripts/check.sh scripts/publish.sh scripts/tests/test_gate_lease.sh scripts/tests/test_publish.sh scripts/tests/drive_preamble.sh TEMPLATE_VERSION docs/product/instruments.md docs/product/architecture.md apps/core/roles.py apps/core/api/frozen_families.py pyproject.toml docs/product/queue.md apps/core/services.py quality/gate.py scripts/local/template-base scripts/local/legs CHANGELOG.md apps/core
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
    # The pattern book, template-owned, so an edit to it can be compared with
    # the base; its drawer is written by a case below and is never in the base.
    mkdir -p "$d/docs/product/design"
    printf '# the pattern book\n' >"$d/docs/product/design/patterns.md"
    printf '[project]\n' >"$d/pyproject.toml"
    # The template's two workflows, so an edit to either is a divergence the
    # base can be compared with; a product's own workflow is written by a
    # case below and is never in the base.
    mkdir -p "$d/.github/workflows"
    printf 'name: ci\n' >"$d/.github/workflows/ci.yml"
    printf 'name: nightly-proof\n' >"$d/.github/workflows/nightly-proof.yml"
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

# --- (d) THE PLATFORM-APP LIST IS MATCHED BY WHOLE NAME, AT ANY POSITION ----
# `build_repo` writes a ONE-entry `platform_apps` list, and a one-entry list
# is a world too small to falsify the match: the census held its names one per
# line and tested them space-delimited, so against the REAL list every
# platform app read `product` and an edit to `apps/core/services.py` was silent
# while the one-entry case above stayed green. So this case's world carries the
# real `quality/partition.yaml` — the population derived, never typed — and
# probes an edge of it: a middle name (`core`), the LAST name read with the
# census's own awk, and a product app that is in no list at all.
case_a_platform_app_edit_is_seen_against_the_real_partition_list() {
    local w="$WORK/realpartition"
    build_repo "$w" || {
        bad "the real-partition fixture would not build"
        return 0
    }
    cp "$ROOT/quality/partition.yaml" "$w/quality/partition.yaml"
    gitq "$w" add quality/partition.yaml
    gitq "$w" commit -q -m "the template at v0.1.0, with its real platform-app list"
    gitq "$w" tag -f -a v0.1.0 -m v0.1.0 HEAD >/dev/null
    local last
    last=$(awk '/^platform_apps:/{f=1;next} f&&/^[a-z_]+:/{exit} f&&/^  - /{print $2}' \
        "$w/quality/partition.yaml" | tail -n 1)
    if [ -z "$last" ] || [ "$last" = core ]; then
        bad "the real partition list reads no last name distinct from core ('$last') — this world cannot probe the edge"
        rm -rf "$w"
        return 0
    fi
    local saved=${DJB_TEMPLATE_BASE-}
    export DJB_TEMPLATE_BASE=v0.1.0

    printf '# our patch to the platform app\n' >>"$w/apps/core/services.py"
    gitq "$w" add apps/core/services.py
    gitq "$w" commit -q -m "edit a platform app"
    run "$w"
    if [ "$RC" = 1 ] && grep -q "^   divergence: apps/core/services.py" "$OUT" &&
        grep -qE "^census: .* diverged=1 unnamed=1$" "$OUT"; then
        ok "against the real platform_apps list an edit to apps/core/services.py is a divergence (diverged=1 unnamed=1)"
    else
        bad "real-list platform app edit: exit $RC, want 1 with a divergence row for apps/core/services.py and diverged=1 unnamed=1"
        sed 's/^/         /' "$OUT"
    fi

    printf '\ndivergence: apps/core/services.py — probe\n' >>"$w/docs/product/architecture.md"
    gitq "$w" add docs/product/architecture.md
    gitq "$w" commit -q -m "name the divergence"
    run "$w"
    if [ "$RC" = 0 ] && grep -q "named-divergence: apps/core/services.py" "$OUT"; then
        ok "and named in architecture.md it is a NAMED divergence, exit 0"
    else
        bad "real-list named platform divergence: exit $RC, want 0 with named-divergence: apps/core/services.py"
        sed 's/^/         /' "$OUT"
    fi

    mkdir -p "$w/apps/$last"
    printf '# a probe under the last platform app\n' >"$w/apps/$last/zzz_probe.py"
    gitq "$w" add "apps/$last/zzz_probe.py"
    gitq "$w" commit -q -m "edit the last platform app"
    run "$w"
    if [ "$RC" = 1 ] && grep -q "^   divergence: apps/$last/zzz_probe.py" "$OUT"; then
        ok "the list's LAST name ($last) is matched too — apps/$last/zzz_probe.py is a divergence"
    else
        bad "last platform app ($last): exit $RC, want 1 with a divergence row for apps/$last/zzz_probe.py"
        sed 's/^/         /' "$OUT"
    fi
    gitq "$w" rm -q "apps/$last/zzz_probe.py"
    gitq "$w" commit -q -m "undo"

    printf '# the product changed this\n' >>"$w/apps/zzz_product_app/models.py"
    gitq "$w" add apps/zzz_product_app/models.py
    gitq "$w" commit -q -m "product change"
    run "$w"
    if [ "$RC" = 0 ] && ! grep -q "divergence: apps/zzz_product_app/models.py" "$OUT"; then
        ok "and an app in no list is still the product's — apps/zzz_product_app/models.py is silent"
    else
        bad "product app against the real list: exit $RC, want 0 with no row for apps/zzz_product_app/models.py"
        sed 's/^/         /' "$OUT"
    fi

    if [ -n "$saved" ]; then export DJB_TEMPLATE_BASE="$saved"; else unset DJB_TEMPLATE_BASE; fi
    rm -rf "$w"
}

# --- THE COLLISION CENSUS: a release's app against the product's own --------
# `--against <ref>` reads every app the RELEASE carries and every app the
# product owns, and a name both sides spell in one class — the app label, a
# table, an index, a unique constraint — is a pair the release's migrations
# would die on one step after the merge. Each case below builds its own world:
# a product at v0.1.0 whose template ships a platform app with a membership
# model (the base-inherited recency index added the way the real tree adds it,
# by `AddIndex`), and a release v0.2.0 on a branch that adds a platform app with
# a note model. The product's own apps are planted into the working tree, which
# is the side the census reads for YOURS.
plant_app() { # plant_app <repo> <dir> — an apps.py whose label is its directory
    mkdir -p "$1/apps/$2"
    printf 'from django.apps import AppConfig\n\n\nclass ZzzConfig(AppConfig):\n    name = "apps.%s"\n' \
        "$2" >"$1/apps/$2/apps.py"
}

# plant_initial <repo> <dir> <model> <index name> [<unique name>] [<db_table>]
# — a first migration in the shape `makemigrations` writes: the model's name
# first, a field tuple that spells `"name"`, a foreign key whose `related_name`
# is not a name, the options block with the index, the unique constraint and a
# check constraint whose name is shared by every plant (check constraints are
# per-table in Postgres, so an equal one is never a pair).
plant_initial() {
    local repo=$1 app=$2 model=$3 index=$4 unique=${5:-} table=${6:-}
    mkdir -p "$repo/apps/$app/migrations"
    : >"$repo/apps/$app/migrations/__init__.py"
    {
        printf 'from django.db import migrations, models\n\n\n'
        printf 'class Migration(migrations.Migration):\n    initial = True\n\n    dependencies = []\n\n'
        printf '    operations = [\n        migrations.CreateModel(\n            name="%s",\n' "$model"
        printf '            fields=[\n'
        printf '                ("id", models.BigAutoField(primary_key=True)),\n'
        printf '                ("name", models.CharField(max_length=10)),\n'
        printf '                (\n                    "owner",\n                    models.ForeignKey(\n'
        printf '                        on_delete=models.PROTECT,\n'
        printf '                        related_name="%%(app_label)s_%%(class)s_set",\n'
        printf '                        to="core.membership",\n                    ),\n                ),\n'
        printf '            ],\n            options={\n                "verbose_name": "zzz",\n'
        [ -z "$table" ] || printf '                "db_table": "%s",\n' "$table"
        printf '                "indexes": [\n'
        printf '                    models.Index(fields=["id"], name="%s"),\n' "$index"
        printf '                ],\n                "constraints": [\n'
        [ -z "$unique" ] || printf '                    models.UniqueConstraint(fields=("name",), name="%s"),\n' "$unique"
        printf '                    models.CheckConstraint(\n'
        printf '                        condition=models.Q(("name", ""), _negated=True),\n'
        printf '                        name="zzz_check_shared_by_every_plant",\n'
        printf '                    ),\n                ],\n            },\n        ),\n    ]\n'
    } >"$repo/apps/$app/migrations/0001_initial.py"
}

build_collision_world() { # build_collision_world <dir>; leaves main checked out
    local w=$1
    build_repo "$w" || return 1
    plant_app "$w" core
    mkdir -p "$w/apps/core/migrations"
    : >"$w/apps/core/migrations/__init__.py"
    printf 'from django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n    initial = True\n\n    dependencies = []\n\n    operations = [\n        migrations.CreateModel(\n            name="Membership",\n            fields=[("id", models.BigAutoField(primary_key=True))],\n        ),\n    ]\n' \
        >"$w/apps/core/migrations/0001_initial.py"
    printf 'from django.db import migrations, models\n\n\nclass Migration(migrations.Migration):\n    dependencies = [("core", "0001_initial")]\n\n    operations = [\n        migrations.AddIndex(\n            model_name="membership",\n            index=models.Index(fields=["id"], name="membership_recency"),\n        ),\n    ]\n' \
        >"$w/apps/core/migrations/0002_membership_recency.py"
    gitq "$w" add -A
    gitq "$w" commit -q -m "the template at v0.1.0, with a platform app's schema"
    gitq "$w" tag -f -a v0.1.0 -m v0.1.0 HEAD >/dev/null
    gitq "$w" checkout -q -b zzz_release
    plant_app "$w" zzz_notes
    plant_initial "$w" zzz_notes Note note_recency note_zzz_unique
    gitq "$w" add -A
    gitq "$w" commit -q -m "the release adds a platform app"
    gitq "$w" tag -a v0.2.0 -m v0.2.0 HEAD
    gitq "$w" checkout -q main
    [ ! -e "$w/apps/zzz_notes" ] || return 1
    # The product's own app gets its schema in the PRODUCT's history, after
    # the base — the release never carries it, exactly as in a real product.
    plant_app "$w" zzz_product_app
    plant_initial "$w" zzz_product_app Ledger ledger_recency
    gitq "$w" add -A
    gitq "$w" commit -q -m "the product's own app makes its first migration"
}

# run_against <world> <args...> — the census with the fixture's own base
# declared, so the divergence half runs and is clean, and whatever the exit
# says is the collision half's.
run_against() {
    local w=$1
    shift
    local saved=${DJB_TEMPLATE_BASE-}
    export DJB_TEMPLATE_BASE=v0.1.0
    run "$w" "$@"
    if [ -n "$saved" ]; then export DJB_TEMPLATE_BASE="$saved"; else unset DJB_TEMPLATE_BASE; fi
}

REMEDY="remedy: rename YOURS — CHANGELOG.md § [2.4.1] › What a product does at the merge › the rename road; the template's name is the release's"
KIND_REMEDY='remedy: give YOUR model a kind of its own — one line on its class, authz_kind = "<its own word>"'

case_a_release_app_sharing_your_label_table_index_and_constraint_is_exit_2_per_pair() {
    local w="$WORK/collide-all"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    # The product's OWN app, in the directory the release is about to add, with
    # the release's model name and the base's inherited index name.
    plant_app "$w" zzz_notes
    plant_initial "$w" zzz_notes Note note_recency
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: label zzz_notes — apps/zzz_notes (yours) vs apps/zzz_notes (v0.2.0)" "$OUT" &&
        grep -qF "collision: table zzz_notes_note — yours (apps/zzz_notes/migrations/0001_initial.py) vs v0.2.0 (apps/zzz_notes/migrations/0001_initial.py)" "$OUT" &&
        grep -qF "collision: index note_recency — yours (apps/zzz_notes/migrations/0001_initial.py) vs v0.2.0 (apps/zzz_notes/migrations/0001_initial.py)" "$OUT" &&
        grep -qF "collision: kind note — yours (apps/zzz_notes · Note) vs v0.2.0 (apps/zzz_notes · Note)" "$OUT" &&
        grep -qF "collisions: labels=1 tables=1 indexes=1 constraints=0 kinds=1" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 4 ] &&
        [ "$(grep -cF "$REMEDY" "$OUT")" = 3 ] && [ "$(grep -cF "$KIND_REMEDY" "$OUT")" = 1 ]; then
        ok "a product app with the release's label, model and index: exit 2, label/table/index/kind lines, a remedy each, labels=1 tables=1 indexes=1 constraints=0 kinds=1"
    else
        bad "label/table/index/kind collision: exit $RC, want 2 with four lines, their remedies and the trailer"
        sed 's/^/         /' "$OUT"
    fi
    # AND THE FOURTH CLASS: the same app with the release's unique constraint.
    plant_initial "$w" zzz_notes Note note_recency note_zzz_unique
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: constraint note_zzz_unique — yours (apps/zzz_notes/migrations/0001_initial.py) vs v0.2.0 (apps/zzz_notes/migrations/0001_initial.py)" "$OUT" &&
        grep -qF "collisions: labels=1 tables=1 indexes=1 constraints=1 kinds=1" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 5 ]; then
        ok "all five classes at once: five collision lines, constraints=1 — and the shared check-constraint name is no pair"
    else
        bad "five-class collision: exit $RC, want 2 with five collision lines and constraints=1"
        sed 's/^/         /' "$OUT"
    fi
    if grep -q "zzz_check_shared_by_every_plant" "$OUT"; then
        bad "a check constraint's name was read as a pair — it is per-table in Postgres"
    else
        ok "the check constraint both sides spell is not in the population"
    fi
    rm -rf "$w"
}

case_distinct_labels_and_model_names_are_no_collision() {
    local w="$WORK/collide-none"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    plant_app "$w" zzz_orders
    plant_initial "$w" zzz_orders Order order_recency order_zzz_unique
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && grep -qF "collisions: none against v0.2.0" "$OUT" &&
        grep -qF "collisions: labels=0 tables=0 indexes=0 constraints=0" "$OUT" &&
        ! grep -q '^collision: ' "$OUT" && grep -q "^== CLEAN" "$OUT"; then
        ok "distinct labels and model names: 'collisions: none against v0.2.0', and the divergence verdict stands (exit 0, CLEAN)"
    else
        bad "no-collision world: exit $RC, want 0 with 'collisions: none against v0.2.0'"
        sed 's/^/         /' "$OUT"
    fi
    # THE POPULATION WAS READ, not skipped: the release's two apps and the
    # product's two were parsed, and the platform app the product carries is
    # the template's, never YOURS.
    if grep -qE "release v0.2.0 parsed=2 unparsed=0 · yours parsed=2 unparsed=0" "$OUT"; then
        ok "and the trailer says what it read — release parsed=2, yours parsed=2 (the platform app is not yours)"
    else
        bad "the trailer does not read release parsed=2 and yours parsed=2"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_a_db_table_spelled_onto_a_release_table_is_a_table_pair() {
    local w="$WORK/collide-table"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    plant_app "$w" zzz_other
    plant_initial "$w" zzz_other Other other_recency "" zzz_notes_note
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: table zzz_notes_note — yours (apps/zzz_other/migrations/0001_initial.py) vs v0.2.0 (apps/zzz_notes/migrations/0001_initial.py)" "$OUT" &&
        grep -qF "collisions: labels=0 tables=1 indexes=0 constraints=0" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 1 ]; then
        ok "a db_table spelled onto the release's table is one table pair — the literal replaces <label>_<model>"
    else
        bad "db_table collision: exit $RC, want 2 with one table line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_an_inherited_index_name_collides_with_the_release_platform_app() {
    local w="$WORK/collide-index"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    # The base names every recency index after the CLASS, so a product model
    # named like a platform model inherits the platform's index name.
    plant_app "$w" zzz_people
    plant_initial "$w" zzz_people Membership membership_recency
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: index membership_recency — yours (apps/zzz_people/migrations/0001_initial.py) vs v0.2.0 (apps/core/migrations/0002_membership_recency.py)" "$OUT" &&
        grep -qF "collision: kind membership — yours (apps/zzz_people · Membership) vs v0.2.0 (apps/core · Membership)" "$OUT" &&
        grep -qF "collisions: labels=0 tables=0 indexes=1 constraints=0 kinds=1" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 2 ]; then
        ok "a product model named like a platform model: one index pair against the platform app's AddIndex, and the kind it derives from the same class name"
    else
        bad "inherited index collision: exit $RC, want 2 with one index line naming apps/core's 0002 and one kind line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

# AN INDEX SUBCLASS NAMES AN INDEX TOO. `GinIndex`, `GistIndex`, `BTreeIndex`
# and the rest carry a `name=` that is schema-global exactly like a plain
# `models.Index`'s, so a product's GIN index spelling a release index's name is
# the same pair. The release side here adds its GIN index the way the real
# tree does — `AddIndex` with the dotted postgres path, the name on the next
# line — and the product's spells the class bare.
case_an_index_subclass_name_is_in_the_population() {
    local w="$WORK/collide-gin"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    gitq "$w" checkout -q zzz_release
    printf 'import django.contrib.postgres.indexes\nfrom django.db import migrations\n\n\nclass Migration(migrations.Migration):\n    dependencies = [("zzz_notes", "0001_initial")]\n\n    operations = [\n        migrations.AddIndex(\n            model_name="note",\n            index=django.contrib.postgres.indexes.GinIndex(\n                fields=["name"], name="note_name_gin_zzz"\n            ),\n        ),\n    ]\n' \
        >"$w/apps/zzz_notes/migrations/0002_note_name_gin.py"
    gitq "$w" add apps/zzz_notes/migrations/0002_note_name_gin.py
    gitq "$w" commit -q -m "the release adds a GIN index"
    gitq "$w" tag -f -a v0.2.0 -m v0.2.0 HEAD >/dev/null
    gitq "$w" checkout -q main
    plant_app "$w" zzz_search
    plant_initial "$w" zzz_search Document document_recency
    printf 'from django.contrib.postgres.indexes import GinIndex\nfrom django.db import migrations\n\n\nclass Migration(migrations.Migration):\n    dependencies = [("zzz_search", "0001_initial")]\n\n    operations = [\n        migrations.AddIndex(\n            model_name="document",\n            index=GinIndex(fields=["name"], name="note_name_gin_zzz"),\n        ),\n    ]\n' \
        >"$w/apps/zzz_search/migrations/0002_document_name_gin.py"
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: index note_name_gin_zzz — yours (apps/zzz_search/migrations/0002_document_name_gin.py) vs v0.2.0 (apps/zzz_notes/migrations/0002_note_name_gin.py)" "$OUT" &&
        grep -qF "collisions: labels=0 tables=0 indexes=1 constraints=0 kinds=0" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 1 ]; then
        ok "a GinIndex name on both sides — dotted on one, bare on the other — is one index pair"
    else
        bad "GinIndex collision: exit $RC, want 2 with one index line for note_name_gin_zzz"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

# THE AUTHORIZATION KIND is derived from the model's CLASS name, so a product
# model named like a release model claims the release's kind however different
# the label and the table are — and the deployment's `check` refuses to derive
# the vocabulary at all. The product's own word on its class silences it.
case_a_model_named_like_a_release_model_collides_on_its_kind() {
    local w="$WORK/collide-kind"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    plant_app "$w" zzz_crm
    plant_initial "$w" zzz_crm Note crm_note_recency
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: kind note — yours (apps/zzz_crm · Note) vs v0.2.0 (apps/zzz_notes · Note)" "$OUT" &&
        grep -qF "collisions: labels=0 tables=0 indexes=0 constraints=0 kinds=1" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 1 ] && grep -qF "$KIND_REMEDY" "$OUT"; then
        ok "a product Note in its own app — distinct label, table and index — still collides on the kind note, with the remedy on the product's side"
    else
        bad "kind collision: exit $RC, want 2 with one kind line and the kind remedy"
        sed 's/^/         /' "$OUT"
    fi
    printf 'class Note(TenantScopedModel):\n    authz_kind = "crm_note"\n' >"$w/apps/zzz_crm/models.py"
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && grep -qF "collisions: none against v0.2.0" "$OUT"; then
        ok "and authz_kind = \"crm_note\" typed on the class silences it"
    else
        bad "kind override: exit $RC, want 0 with 'collisions: none against v0.2.0'"
        sed 's/^/         /' "$OUT"
    fi
    printf 'class Note(TenantScopedModel):\n    authz_kind: ClassVar[str] = "crm_note"  # its own word\n' >"$w/apps/zzz_crm/models.py"
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && grep -qF "collisions: none against v0.2.0" "$OUT"; then
        ok "and so does the annotated ClassVar form, comment and all"
    else
        bad "annotated kind override: exit $RC, want 0"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_no_against_prints_not_measured_and_changes_no_verdict() {
    local w="$WORK/collide-unasked"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    plant_app "$w" zzz_notes
    plant_initial "$w" zzz_notes Note note_recency note_zzz_unique
    run_against "$w"
    if [ "$RC" = 0 ] && grep -qF "collisions: not measured (no --against <release ref>)" "$OUT" &&
        ! grep -q '^collision: ' "$OUT" && grep -q "^== CLEAN" "$OUT"; then
        ok "no --against: 'collisions: not measured', and the census's own verdict is untouched (exit 0, CLEAN) over a world that would collide"
    else
        bad "no --against: exit $RC, want 0 with the not-measured line and no collision line"
        sed 's/^/         /' "$OUT"
    fi
    # The gate's form, on a tree with no base: still the SKIP, still exit 0.
    run "$w" --if-declared
    if [ "$RC" = 0 ] && grep -q "SKIPPED" "$OUT" &&
        grep -qF "collisions: not measured (no --against <release ref>)" "$OUT"; then
        ok "and --if-declared with no base is the same SKIP at exit 0 — rule 60's reading passes nothing new"
    else
        bad "--if-declared, no --against: exit $RC, want 0 SKIPPED with the not-measured line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_an_unresolvable_against_is_exit_2_naming_the_ref() {
    local w="$WORK/collide-unresolved"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    run_against "$w" --against zzz_nope
    if [ "$RC" = 2 ] && grep -qF "zzz_nope" "$OUT" && grep -qF "git fetch template --tags" "$OUT" &&
        ! grep -q "collisions: none" "$OUT"; then
        ok "an --against that does not resolve is exit 2, naming the ref and the fetch to type"
    else
        bad "unresolvable --against: exit $RC, want 2 naming zzz_nope and the fetch"
        sed 's/^/         /' "$OUT"
    fi
    run_against "$w" --against
    [ "$RC" = 2 ] && ok "and --against with no ref is exit 2, never a run against nothing" ||
        bad "--against with no ref: exit $RC, want 2"
    rm -rf "$w"
}

case_the_reserved_prefix_is_a_pair_in_waiting() {
    local w="$WORK/collide-reserved"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    plant_app "$w" djb_zzz
    plant_initial "$w" djb_zzz Reserved reserved_recency
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: reserved prefix djb_ — apps/djb_zzz (yours); djb_ is the template's namespace for its platform apps" "$OUT"; then
        ok "a product app labelled djb_… is exit 2 on its own line — the prefix is the template's"
    else
        bad "reserved prefix: exit $RC, want 2 with the reserved-prefix line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w/apps/djb_zzz"
    plant_app "$w" zzz_djb
    plant_initial "$w" zzz_djb Reserved reserved_recency
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && ! grep -q "reserved prefix" "$OUT" && grep -qF "collisions: none against v0.2.0" "$OUT"; then
        ok "and zzz_djb — the prefix elsewhere in the label — is silent on the class"
    else
        bad "zzz_djb: exit $RC, want 0 with no reserved-prefix line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_an_app_with_no_migrations_is_counted_unparsed() {
    local w="$WORK/collide-unparsed"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    plant_app "$w" zzz_nomig
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && grep -qF "unparsed: apps/zzz_nomig (yours)" "$OUT" &&
        grep -qE "yours parsed=1 unparsed=1" "$OUT" && grep -qF "collisions: none against v0.2.0" "$OUT"; then
        ok "an app with no migrations/ is printed and counted unparsed — never silently clean — and the exit is unchanged by it"
    else
        bad "unparsed app: exit $RC, want 0 with 'unparsed: apps/zzz_nomig (yours)' and yours unparsed=1"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

# --- THE MOUNTS AND THE TAGS ------------------------------------------------
# A router's mount and its tags are two more names a release's platform app and
# a product's own app can share, and nothing refuses the pair until `check`
# runs after the merge (house rule 83). The census reads both as text from
# `api.py`, the same reader on both sides. The api modules planted here carry
# the literals only: no Django runs on either side, so they need not import.

# plant_api <repo> <dir> <PREFIX or -> <tag or -> [<route path>…] — a minimal
# api.py: a `PREFIX` line unless `-`, one `Router(...)` with the tag unless
# `-`, and one route decorator per path.
plant_api() {
    local repo=$1 app=$2 prefix=$3 tag=$4 path
    shift 4
    mkdir -p "$repo/apps/$app"
    {
        printf 'from ninja import Router\n\n'
        [ "$prefix" = - ] || printf 'PREFIX = "%s"\n\n' "$prefix"
        if [ "$tag" = - ]; then printf 'router = Router()\n'; else printf 'router = Router(tags=["%s"])\n' "$tag"; fi
        for path in "$@"; do
            printf '\n\n@router.get("%s")\ndef zzz_route(request):\n    return {}\n' "$path"
        done
    } >"$repo/apps/$app/api.py"
}

# release_api <world> <PREFIX or -> <tag or -> [<route path>…] — the same file
# on the RELEASE's platform app, committed on its branch and re-tagged.
release_api() {
    local w=$1
    shift
    gitq "$w" checkout -q zzz_release
    plant_api "$w" zzz_notes "$@"
    gitq "$w" add apps/zzz_notes/api.py
    gitq "$w" commit -q -m "the release's platform app mounts a router"
    gitq "$w" tag -f -a v0.2.0 -m v0.2.0 HEAD >/dev/null
    gitq "$w" checkout -q main
}

MOUNT_REMEDY='remedy: mount YOURS elsewhere — PREFIX = "<its own word>" in your api.py'
TAG_REMEDY='remedy: tag YOURS with a word of its own — Router(tags=["<its own word>"]) and the matching TAGS key'

case_a_release_mount_and_tag_your_app_also_spells_is_a_pair_each() {
    local w="$WORK/collide-mount"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    release_api "$w" notes notes /
    plant_app "$w" zzz_crm
    plant_api "$w" zzz_crm notes notes /
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: mount notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)" "$OUT" &&
        grep -qF "collision: tag notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)" "$OUT" &&
        grep -qF "reserved=0 mounts=1 tags=1" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 2 ] &&
        [ "$(grep -cF "$MOUNT_REMEDY" "$OUT")" = 1 ] && [ "$(grep -cF "$TAG_REMEDY" "$OUT")" = 1 ]; then
        ok "a product router on the release's PREFIX and tag: exit 2, one mount line and one tag line, a remedy each on YOUR side, mounts=1 tags=1"
    else
        bad "mount/tag collision: exit $RC, want 2 with a mount line, a tag line, their remedies and mounts=1 tags=1"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_a_root_route_on_the_release_mount_is_a_mount_pair() {
    local w="$WORK/collide-root"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    release_api "$w" notes notes /
    plant_app "$w" zzz_crm
    plant_api "$w" zzz_crm "" crm_notes / /notes/ "/notes/{note_id}/" "/{row_id}/"
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: mount notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)" "$OUT" &&
        grep -qF "reserved=0 mounts=1 tags=0" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 1 ]; then
        ok "PREFIX = \"\" and a route at /notes/: one mount line — the root and a {parameter} first segment name nothing"
    else
        bad "root-mounted route: exit $RC, want 2 with one mount line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_a_sub_router_on_the_release_mount_is_a_mount_pair() {
    local w="$WORK/collide-subrouter"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    release_api "$w" notes notes /
    plant_app "$w" zzz_crm
    printf 'from ninja import Router\n\nPREFIX = ""\n\nlinks = Router(tags=["crm_links"])\nrouter = Router()\nrouter.add_router("/notes/", links)\n' \
        >"$w/apps/zzz_crm/api.py"
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: mount notes — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)" "$OUT" &&
        grep -qF "reserved=0 mounts=1 tags=0" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 1 ]; then
        ok "a sub-router added at /notes/ under an empty prefix: one mount line"
    else
        bad "sub-router: exit $RC, want 2 with one mount line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_an_app_with_no_prefix_mounts_at_its_label() {
    local w="$WORK/collide-label-mount"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    # The release mounts its platform app at a word that is YOUR app's label.
    release_api "$w" zzz_crm notes /
    plant_app "$w" zzz_crm
    plant_api "$w" zzz_crm - crm_notes /
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: mount zzz_crm — yours (apps/zzz_crm/api.py) vs v0.2.0 (apps/zzz_notes/api.py)" "$OUT" &&
        grep -qF "labels=0 " "$OUT" && grep -qF "reserved=0 mounts=1 tags=0" "$OUT" &&
        [ "$(grep -c '^collision: ' "$OUT")" = 1 ]; then
        ok "no PREFIX line: the router mounts at its label, and the release's PREFIX on that word is one mount line (no label pair)"
    else
        bad "label-as-mount: exit $RC, want 2 with one mount line and labels=0"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_a_product_mount_or_tag_under_djb_is_the_reserved_line() {
    local w="$WORK/collide-reserved-mount"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    release_api "$w" notes notes /
    plant_app "$w" zzz_crm
    plant_api "$w" zzz_crm djb_x crm_notes /
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: reserved prefix djb_ — mount djb_x in apps/zzz_crm/api.py (yours)" "$OUT" &&
        grep -qF "reserved=1 mounts=0 tags=0" "$OUT" && grep -qF "$MOUNT_REMEDY" "$OUT"; then
        ok "a product PREFIX = \"djb_x\" is the reserved line, with the mount remedy"
    else
        bad "reserved mount: exit $RC, want 2 with the reserved line for mount djb_x"
        sed 's/^/         /' "$OUT"
    fi
    plant_api "$w" zzz_crm crm-notes djb_x /
    run_against "$w" --against v0.2.0
    if [ "$RC" = 2 ] &&
        grep -qF "collision: reserved prefix djb_ — tag djb_x in apps/zzz_crm/api.py (yours)" "$OUT" &&
        grep -qF "reserved=1 mounts=0 tags=0" "$OUT" && grep -qF "$TAG_REMEDY" "$OUT"; then
        ok "and tags=[\"djb_x\"] is the reserved line, with the tag remedy"
    else
        bad "reserved tag: exit $RC, want 2 with the reserved line for tag djb_x"
        sed 's/^/         /' "$OUT"
    fi
    plant_api "$w" zzz_crm x_djb crm_notes /
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && ! grep -q "reserved prefix" "$OUT" && grep -qF "collisions: none against v0.2.0" "$OUT"; then
        ok "and PREFIX = \"x_djb\" — the prefix elsewhere in the word — is silent on the class"
    else
        bad "x_djb: exit $RC, want 0 with no reserved line"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
}

case_a_mount_and_a_tag_of_your_own_are_no_collision() {
    local w="$WORK/collide-own-mount"
    build_collision_world "$w" || {
        bad "the collision world would not build"
        return 0
    }
    release_api "$w" notes notes /
    plant_app "$w" zzz_crm
    plant_api "$w" zzz_crm crm-notes crm_notes /
    run_against "$w" --against v0.2.0
    if [ "$RC" = 0 ] && grep -qF "collisions: none against v0.2.0" "$OUT" &&
        grep -qF "reserved=0 mounts=0 tags=0" "$OUT" && ! grep -q '^collision: ' "$OUT"; then
        ok "PREFIX = \"crm-notes\" and tags=[\"crm_notes\"] beside the release's notes: collisions: none, exit 0"
    else
        bad "own mount and tag: exit $RC, want 0 with collisions: none"
        sed 's/^/         /' "$OUT"
    fi
    rm -rf "$w"
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

# --- the template ships TWO workflows, and the second one is the template's too
# The nightly leak proof (`nightly-proof.yml`) arrived after the census's
# workflow arm was written, and the arm read every workflow but `ci.yml` as the
# product's — so a product's edit to the template's nightly was silent. Both
# directions: the template's workflow edited is a divergence, a product's own
# workflow beside it is not.
for wf in ci.yml nightly-proof.yml; do
    printf '# our tweak\n' >>"$REPO/.github/workflows/$wf"
    commit_all "edit the template's $wf"
    run "$REPO"
    if [ "$RC" = 1 ] && grep -q "divergence: .github/workflows/$wf" "$OUT"; then
        ok "the template's .github/workflows/$wf edited is a divergence — the template ships it"
    else
        bad "template workflow $wf edited: exit $RC, want 1 naming .github/workflows/$wf"
        sed 's/^/         /' "$OUT"
    fi
    gitq "$REPO" checkout -q "$BASE" -- ".github/workflows/$wf"
    commit_all "undo"
done
silent_case "a product's own workflow" ".github/workflows/zzz_product.yml" create

# --- the pattern book is the template's; its drawer is the product's --------
# The book's own header says template-owned, and the census's standing-document
# arm listed six files and sent every other ledger-directory path to the product —
# so a product's edit to the book was silent. Both directions, as the workflows
# above: the book edited is a divergence, the drawer beside it is not.
printf '# our entry, written into the template'"'"'s book\n' >>"$REPO/docs/product/design/patterns.md"
commit_all "edit the template's pattern book"
run "$REPO"
if [ "$RC" = 1 ] && grep -q "divergence: docs/product/design/patterns.md" "$OUT"; then
    ok "the template's pattern book edited is a divergence — the template owns it"
else
    bad "pattern book edited: exit $RC, want 1 naming docs/product/design/patterns.md"
    sed 's/^/         /' "$OUT"
fi
gitq "$REPO" checkout -q "$BASE" -- docs/product/design/patterns.md
commit_all "undo"
silent_case "the pattern book's drawer" "docs/product/design/patterns.local.md" create

# --- a SECOND file in the design directory is the template's too -----------
# The publish census ships `docs/product/design/*` by ONE GLOB (R9), so a
# second file the template adds beside the book ships the day it lands. If
# this census named the book alone, that file would ship as the template's
# and be owned here as the product's — an edit to it silent. So the design
# arm is the same glob, and a second design file planted in the base and then
# edited is a divergence, named; the owned count carries it.
#
# THE PATH IS ASSEMBLED, NEVER SPELLED: this drive ships, and the dangling-docs
# census reads every whole docs path a shipped file spells — a plant name that
# exists only inside this drive's throwaway repository would be a pointer at
# nothing in the tree it ships in.
DESIGN_DIR=docs/product/design
SECOND_DESIGN="$DESIGN_DIR/zzz_notes.md"
printf '# a second design file the template ships\n' >"$REPO/$SECOND_DESIGN"
commit_all "the template grows a second design file"
# The base moves to the commit that carries the file — the template's release
# that grew it — and moves back after, so every later case compares against
# the fixture's own base exactly as before.
export DJB_TEMPLATE_BASE
DJB_TEMPLATE_BASE=$(git -C "$REPO" rev-parse HEAD)
run "$REPO"
OWNED_DESIGN=$(sed -n 's/^census: owned=\([0-9]*\).*/\1/p' "$OUT")
printf '# our edit to it\n' >>"$REPO/$SECOND_DESIGN"
commit_all "edit the second design file"
run "$REPO"
if [ "$RC" = 1 ] && grep -q "divergence: $SECOND_DESIGN" "$OUT" &&
    [ "$OWNED_DESIGN" = "$((OWNED_BASE + 1))" ]; then
    ok "a second design file is the template's — edited, it is a divergence (owned $OWNED_BASE → $OWNED_DESIGN)"
else
    bad "second design file edited: exit $RC, owned $OWNED_BASE → ${OWNED_DESIGN:-?}, want 1 naming $SECOND_DESIGN and +1"
    sed 's/^/         /' "$OUT"
fi
gitq "$REPO" rm -q "$SECOND_DESIGN"
commit_all "undo"
DJB_TEMPLATE_BASE="$BASE"
silent_case "the pattern book's drawer, beside a second design file" "docs/product/design/patterns.local.md" create

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
run_case case_a_platform_app_edit_is_seen_against_the_real_partition_list
run_case case_a_release_app_sharing_your_label_table_index_and_constraint_is_exit_2_per_pair
run_case case_distinct_labels_and_model_names_are_no_collision
run_case case_a_db_table_spelled_onto_a_release_table_is_a_table_pair
run_case case_an_inherited_index_name_collides_with_the_release_platform_app
run_case case_a_model_named_like_a_release_model_collides_on_its_kind
run_case case_an_index_subclass_name_is_in_the_population
run_case case_no_against_prints_not_measured_and_changes_no_verdict
run_case case_an_unresolvable_against_is_exit_2_naming_the_ref
run_case case_the_reserved_prefix_is_a_pair_in_waiting
run_case case_an_app_with_no_migrations_is_counted_unparsed
run_case case_a_release_mount_and_tag_your_app_also_spells_is_a_pair_each
run_case case_a_root_route_on_the_release_mount_is_a_mount_pair
run_case case_a_sub_router_on_the_release_mount_is_a_mount_pair
run_case case_an_app_with_no_prefix_mounts_at_its_label
run_case case_a_product_mount_or_tag_under_djb_is_the_reserved_line
run_case case_a_mount_and_a_tag_of_your_own_are_no_collision

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
# THE DERIVATION IS NAMED, NEVER SPELLED AS SHELL. The base line used to read
# `the 'template' remote's v$(TEMPLATE_VERSION)` — an escaped `$` that printed
# as notation, which the engine's self-test then re-spelled verbatim onto its
# own second line in a product's transcript.
if grep -qF '$(' "$OUT"; then
    bad "derived base: the census prints a literal \$( — a derivation is named, never spelled as shell"
    sed 's/^/         /' "$OUT"
else
    ok "the derived base's line carries no literal \$( — the derivation is named in words"
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
