#!/usr/bin/env bash
# publish.sh — export the template as a product would inherit it.
#
#   ./scripts/publish.sh                 census + export + verify (default target)
#   ./scripts/publish.sh --to <dir>      census + export + verify into <dir>
#   ./scripts/publish.sh --census        the census ALONE — no export, no target touched
#
# Exit: 0 clean · 1 the artifact was built and a verification leg found violations
#       · 2 ENFORCEMENT BROKEN (the census could not place a path, a derivation
#       could not be read, a leg could not look). 2 outranks a pass, everywhere,
#       the way `scripts/check.sh` means it.
#
# Never pipe this script: a pipe replaces its exit status with the pipe's. It
# refuses one outright (exit 2). Redirect to a file instead.
#
# ---------------------------------------------------------------------------
# WHAT IT IS. `docs/product/publication-manifest.md` is the design; this file is
# the design executed. The manifest's spine is that publication is **a census by
# rule over `git ls-files`, never a hand list of paths**: every tracked path must
# match EXACTLY ONE bucket rule, and a path matching none — or two — is exit 2
# rather than a file that ships by accident or vanishes silently. A file class
# added to the tree next month fails loudly here until somebody decides what it
# is. That is the closed-question-over-a-discoverable-population discipline, and
# it is the whole reason this is a script rather than a hand-copy.
#
# THE THREE BUCKETS. SHIP (verbatim) · TRIM (the platform build's archaeology,
# which the platform repo keeps as the archive of record) · SKELETON (a ledger
# that ships as its contract header plus ONE marked worked example).
#
# THE TWO INVARIANTS, from the manifest, outranking any per-file preference:
#   1. Anything the gate READS ships byte-identical — `quality/**` whole and
#      `docs/product/instruments.md`. The learning layer is the product OF the
#      history and ships with it: rules.yaml's paid-for canaries, negatives,
#      floors, MOVE-TRIGGER annotations and `does_not_cover` clauses, budgets'
#      measured ceilings. Leg `byte-identity` is that clause made falsifiable.
#   2. No decision is lost at publish. Every ADR id cited in a shipped file must
#      resolve inside `architecture.md` or `adrs-ingredients.md`
#      (`docs/product/architecture.md` § The ADR home). Leg `adr-census` is that
#      one; leg `dangling-docs` is its sibling for ordinary `docs/` pointers.
#   3. The platform's construction history does not ship. Finding ids, rung and
#      cycle tokens, the narrative instance-forms of the method's vocabulary and
#      a closed deny-list of private names each resolve nowhere for a stranger
#      who was in none of the cycles that built this — and beside them two
#      classes that resolve to something WORSE than nothing: the template's
#      former name in the TitleCase form the brand carried, which tells a
#      stranger the wrong thing about what they cloned, and the deployment
#      coordinates of the account this platform is developed in, which name
#      somebody else's real resources. Leg `archaeology-census` is that clause,
#      and it carries its own allow-list with reasons.
#
# UNTRACKED RESIDUE NEVER EXPORTS, BY CONSTRUCTION rather than by a broom: the
# export is `git archive HEAD`, so `.rung/`, gate-verdict ledgers, `*.log`,
# worktree droppings and `.env` are not in scope at all. Nothing here has to
# remember to exclude them.
#
# WHY IT REFUSES A DIRTY TREE. The artifact's identity is its TREE HASH, and the
# idempotence claim ("two runs at the same source sha produce the same exported
# tree hash") is only falsifiable if the source is a commit. A working tree is
# not a source anyone can re-derive. Commit first; publish measures a commit.
#
# WHAT THIS INSTRUMENT CANNOT SEE, declared rather than discovered:
#   - It censuses TRACKED files. A load-bearing untracked file is invisible to
#     it (none known). The fresh-clone gate drive on the artifact is the belt.
#   - Skeleton CONTENT quality is a reviewer's judgment, not a census's. This
#     script proves each skeleton is present and carries its marker; it cannot
#     tell whether the skeleton still describes the ledger's contract.
#   - `adr-census` and `dangling-docs` test RESOLVABILITY, not truth: an id that
#     appears in `architecture.md` resolves even if the entry there says
#     something else entirely, exactly as `instruments.md`'s own census checks
#     that a citation has the SHAPE of a file:line and never that the line says
#     what the cell says.
#   - `archaeology-census` reads a CLOSED set of literal shapes. A narration
#     rephrased around every one of them is invisible to it, and so is a private
#     name nobody has added to its deny-list. Its own `does_not_cover` block
#     sits beside the leg, and names the one class it deliberately leaves
#     unscanned and why.
#   - It does not run the gate on the artifact. The fresh-clone verification
#     drive does, and that is the point of keeping them separate: an instrument that graded
#     its own output would be the only reader of it.
# ---------------------------------------------------------------------------
set -euo pipefail

# --- the instrument refuses to be piped -------------------------------------
# Same guard, same reason and the same detection as `scripts/check.sh:67-92`: a
# pipe replaces this script's exit status with the filter's, and the exit status
# is the verdict. CI is exempt for check.sh's reason (GitHub Actions captures
# every step's stdout through a pipe).
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! publish.sh refuses pipes — run it bare or redirect to a file; the exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/.."
ROOT=$(pwd -P)

# --- arguments: strict, because a mistyped flag must never mean a quiet run ---
MODE=full
TARGET=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --census)
        MODE=census
        shift
        ;;
    --to)
        [ "$#" -ge 2 ] || {
            echo "!! --to needs a directory" >&2
            exit 2
        }
        TARGET=$2
        shift 2
        ;;
    *)
        echo "!! unknown argument '$1': publish.sh takes nothing, --census, or --to <dir>" >&2
        exit 2
        ;;
    esac
done
if [ "$MODE" = census ] && [ -n "$TARGET" ]; then
    echo "!! --census takes no target: it exports nothing" >&2
    exit 2
fi

say() { printf '%s\n' "$*"; }
step() {
    say ""
    say "== $*"
}

VIOLATIONS=0
violation() {
    VIOLATIONS=$((VIOLATIONS + 1))
    say "   VIOLATION  $*"
}

# ---------------------------------------------------------------------------
# THE LEDGER POPULATION (manifest R7). These nine files are the product's own
# state; a clone inherits each as a skeleton, never as this platform's record.
#
# The SUBSTITUTION SET IS DERIVED, not listed: a ledger with a committed
# `docs/product/skeletons/<name>.md` is substituted from it; a ledger without
# one must ALREADY be in skeleton form, which this script proves by requiring
# the marker below. Both states are legal and neither is a second copy of the
# other — writing a skeletons/ file for a ledger that is already a skeleton
# would be exactly the second-copy-that-agrees-today miss the census exists to
# refuse. Adding a skeleton file is therefore the whole act of converting one;
# no edit here is needed, and a skeletons/ file naming a NON-ledger is exit 2.
# ---------------------------------------------------------------------------
LEDGERS="north-star queue readouts misses in-flight goal-posts design-agreements pilot-readiness rep-day"
MARKER='<!-- worked example — replace with your product'"'"'s first real entry -->'

# ---------------------------------------------------------------------------
# THE BUCKET RULES (manifest § Bucket rules). `rules_for <path>` echoes every
# rule id the path matches. Exactly one is the contract; the caller enforces it.
# The rules are written to be mutually exclusive BY CONSTRUCTION, and the
# double-match refusal is what proves they still are.
# ---------------------------------------------------------------------------
rules_for() {
    local p=$1 hit="" _cy=""
    case "$p" in
    apps/* | config/* | manage.py) hit="$hit R1" ;;
    esac
    case "$p" in
    quality/* | docs/product/instruments.md) hit="$hit R2" ;;
    esac
    case "$p" in
    scripts/* | deploy/* | perf/* | compose.yaml | compose/* | Dockerfile | .dockerignore | .devcontainer/* | .github/*) hit="$hit R3" ;;
    esac
    case "$p" in
    pyproject.toml | uv.lock | .python-version | .env.example | .gitignore | .editorconfig | .secrets.baseline | vendor/* | templates/*) hit="$hit R4" ;;
    esac
    case "$p" in
    .claude/skills/* | CLAUDE.md | README.md | docs/runbooks/* | docs/standards.md) hit="$hit R5" ;;
    esac
    case "$p" in
    TEMPLATE_VERSION | CHANGELOG.md) hit="$hit R6" ;;
    esac
    case "$p" in
    docs/product/north-star.md | docs/product/queue.md | docs/product/readouts.md | docs/product/misses.md | docs/product/in-flight.md | docs/product/goal-posts.md | docs/product/design-agreements.md | docs/product/pilot-readiness.md | docs/product/rep-day.md) hit="$hit R7" ;;
    esac
    # R8S BEFORE R8's GLOB. `case` takes the FIRST matching pattern, so the two
    # format-teaching files under cycles/ are mutually exclusive with the
    # archaeology glob BY CONSTRUCTION rather than by care — the same property
    # every other rule pair here has, and the double-match refusal still proves
    # it. They ship because four shipped files (the primer, the PM skill, this
    # script and its drive) call cycles/ the contract's home, and a home with no
    # example and no README is a pointer at an empty room.
    #
    # THE TWO PATHS ARE ASSEMBLED, NEVER SPELLED — the manifest's BUILT item 3,
    # "R8's dated-handoff clause is a GLOB, not a filename". This file
    # ships (R3) and leg `dangling-docs` counts `docs/**.md` strings wherever
    # they appear, INCLUDING inside this script when it runs against somebody
    # else's tree: `scripts/tests/test_publish.sh` copies this file into a
    # fixture, and every path R9 spells is a path that fixture must carry or the
    # drive reddens on the instrument citing itself. Naming the pieces costs the
    # fixture nothing.
    #
    # ONE `case`, TWO ARMS — not two blocks. Every other rule here is its own
    # block because the rules are disjoint across blocks and `hit` accumulates;
    # these two OVERLAP by design, and only a shared block's first-match rule
    # separates them. Split them and every R8S path double-matches into exit 2.
    _cy=docs/product/cycles
    case "$p" in
    "$_cy"/EXAMPLE-cycle-plan.md | "$_cy"/README.md) hit="$hit R8S" ;;
    "$_cy"/* | docs/product/archive/* | docs/product/retro/* | docs/product/drafts/* | docs/product/proposals/* | docs/product/pm-handoff-*.md) hit="$hit R8" ;;
    esac
    case "$p" in
    docs/product/adrs-ingredients.md | docs/product/api-editorial-standard.md | docs/product/architecture.md | docs/product/build-contract.md | docs/product/operating-protocol.md | docs/product/partition-closure.md | docs/product/scale-envelope.md | docs/product/publication-manifest.md) hit="$hit R9" ;;
    esac
    case "$p" in
    docs/product/skeletons/*) hit="$hit R10" ;;
    esac
    printf '%s' "${hit# }"
}

bucket_for_rule() {
    case "$1" in
    R1 | R2 | R3 | R4 | R5 | R6 | R9) printf 'SHIP' ;;
    # R8S: the two format-teaching files inside an otherwise-trimmed directory.
    # They are FORMAT, not archaeology — the plan template and the directory's
    # own contract — and four shipped files send a first PM there.
    R8S) printf 'SHIP' ;;
    R7) printf 'SKELETON' ;;
    # R8's last clause is a GLOB, not the dated filename it replaced, and that
    # is load-bearing rather than tidy: leg `dangling-docs` below counts
    # `docs/**.md` strings wherever they appear — a rule that SPELLED a trimmed
    # path would make this file cite a pointer its own artifact cannot resolve.
    # A marker spelled in the thing that defines the marker is a phantom, and
    # the fix is always to name the class rather than the instance.
    R8) printf 'TRIM' ;;
    R10) printf 'SKELETON-SOURCE' ;;
    *) printf 'UNKNOWN' ;;
    esac
}

# --- the source must be a commit --------------------------------------------
git rev-parse --git-dir >/dev/null 2>&1 || {
    echo "!! not a git checkout — the census reads git and nothing else" >&2
    exit 2
}
SRC_SHA=$(git rev-parse HEAD 2>/dev/null) || {
    echo "!! HEAD does not resolve — publish measures a commit" >&2
    exit 2
}
DIRT=$(git status --porcelain)
if [ -n "$DIRT" ]; then
    echo "!! the working tree is dirty — publish measures a COMMIT, not a tree." >&2
    echo "   The idempotence claim (two runs, one exported tree hash) is only" >&2
    echo "   falsifiable against a source anyone else can re-derive. Commit first." >&2
    printf '%s\n' "$DIRT" | sed 's/^/     /' >&2
    exit 2
fi

say "== publish · $ROOT"
say "   source     $(git log -1 --format='%h  %s' HEAD)"

# ---------------------------------------------------------------------------
step "step 1/5 · the census — every tracked path in exactly one bucket"
# ---------------------------------------------------------------------------
SHIP_LIST=$(mktemp "${TMPDIR:-/tmp}/djb-publish-ship.XXXXXX")
TRIM_LIST=$(mktemp "${TMPDIR:-/tmp}/djb-publish-trim.XXXXXX")
SKEL_LIST=$(mktemp "${TMPDIR:-/tmp}/djb-publish-skel.XXXXXX")
SRC_LIST=$(mktemp "${TMPDIR:-/tmp}/djb-publish-src.XXXXXX")
UNPLACED=$(mktemp "${TMPDIR:-/tmp}/djb-publish-unplaced.XXXXXX")
CENSUS=$(mktemp "${TMPDIR:-/tmp}/djb-publish-census.XXXXXX")
EXPECTED=$(mktemp "${TMPDIR:-/tmp}/djb-publish-expected.XXXXXX")
cleanup() {
    rm -f "$SHIP_LIST" "$TRIM_LIST" "$SKEL_LIST" "$SRC_LIST" "$UNPLACED" \
        "$CENSUS" "$EXPECTED"
}
trap cleanup EXIT

# BASH 3.2, deliberately: the shell on a stock macOS is 3.2 and has no
# associative arrays. The per-rule tally is therefore a file the loop writes and
# `grep -c` reads, which is also the more auditable of the two — the census's
# own working is on disk for the duration rather than in shell state.
RULE_IDS="R1 R2 R3 R4 R5 R6 R7 R8 R8S R9 R10"
n_total=0

while IFS= read -r p; do
    n_total=$((n_total + 1))
    hits=$(rules_for "$p")
    set -- $hits
    if [ "$#" -eq 0 ]; then
        printf 'unplaced      %s\n' "$p" >>"$UNPLACED"
        continue
    elif [ "$#" -gt 1 ]; then
        printf 'placed twice  %s  (%s)\n' "$p" "$hits" >>"$UNPLACED"
        continue
    fi
    rule=$1
    printf '%s %s\n' "$rule" "$p" >>"$CENSUS"
    case "$(bucket_for_rule "$rule")" in
    SHIP) printf '%s\n' "$p" >>"$SHIP_LIST" ;;
    TRIM) printf '%s\n' "$p" >>"$TRIM_LIST" ;;
    SKELETON) printf '%s\n' "$p" >>"$SKEL_LIST" ;;
    SKELETON-SOURCE) printf '%s\n' "$p" >>"$SRC_LIST" ;;
    esac
done <<EOF
$(git ls-files)
EOF

if [ "$n_total" -eq 0 ]; then
    echo "!! the census saw no tracked files at all — this reader is looking at the" >&2
    echo "   wrong tree, and that is a could-not-look, never an empty ship-list." >&2
    exit 2
fi

for r in $RULE_IDS; do
    printf '   %-4s %-16s %5d\n' "$r" "$(bucket_for_rule "$r")" \
        "$(grep -c "^$r " "$CENSUS" || true)"
done
say "   ----------------------------------"
say "   $(printf '%-21s %5d' 'SHIP' "$(wc -l <"$SHIP_LIST" | tr -d ' ')")"
say "   $(printf '%-21s %5d' 'SKELETON' "$(wc -l <"$SKEL_LIST" | tr -d ' ')")"
say "   $(printf '%-21s %5d' 'TRIM' "$(wc -l <"$TRIM_LIST" | tr -d ' ')")"
say "   $(printf '%-21s %5d' 'SKELETON-SOURCE' "$(wc -l <"$SRC_LIST" | tr -d ' ')")"
say "   $(printf '%-21s %5d' 'tracked total' "$n_total")"

if [ -s "$UNPLACED" ]; then
    say ""
    echo "!! THE CENSUS CANNOT PLACE EVERY TRACKED PATH. A file class this manifest" >&2
    echo "   does not know about must fail loudly here — shipping it by accident and" >&2
    echo "   trimming it silently are the same defect wearing different clothes." >&2
    echo "   Decide its bucket in docs/product/publication-manifest.md, then add the" >&2
    echo "   rule to rules_for() above." >&2
    sed 's/^/     /' "$UNPLACED" >&2
    exit 2
fi
say "   every tracked path landed in exactly one bucket"

# --- the skeleton derivation, proven both ways ------------------------------
say ""
say "   ledgers (R7) — substituted from docs/product/skeletons/, or already skeletal:"
skel_missing=0
for name in $LEDGERS; do
    live="docs/product/$name.md"
    src="docs/product/skeletons/$name.md"
    if [ -f "$ROOT/$src" ]; then
        printf '     %-24s substituted from %s\n' "$name" "$src"
    elif grep -qF "$MARKER" "$ROOT/$live" 2>/dev/null; then
        printf '     %-24s already skeletal (carries the marker)\n' "$name"
    else
        printf '     %-24s NEITHER: no %s, and %s carries no worked-example marker\n' "$name" "$src" "$live" >&2
        skel_missing=$((skel_missing + 1))
    fi
done
# A skeletons/ file that names nothing in the ledger population is a file the
# export would silently ignore — the same class as an unplaced path.
while IFS= read -r p; do
    [ -n "$p" ] || continue
    base=${p##*/}
    base=${base%.md}
    case " $LEDGERS " in
    *" $base "*) ;;
    *)
        printf '     ORPHAN SKELETON: %s names no ledger in the R7 population\n' "$p" >&2
        skel_missing=$((skel_missing + 1))
        ;;
    esac
done <"$SRC_LIST"
if [ "$skel_missing" -gt 0 ]; then
    echo "!! the skeleton derivation does not close. Every R7 ledger is either" >&2
    echo "   substituted from a committed skeleton or already carries the marker;" >&2
    echo "   anything else would publish this platform's own state as a product's." >&2
    exit 2
fi

# the artifact's expected file set: every SHIP path, plus the nine ledgers
{
    cat "$SHIP_LIST"
    for name in $LEDGERS; do printf 'docs/product/%s.md\n' "$name"; done
} | LC_ALL=C sort >"$EXPECTED"

if [ "$MODE" = census ]; then
    say ""
    say "== CENSUS ONLY · nothing was exported · $(wc -l <"$EXPECTED" | tr -d ' ') paths would ship"
    exit 0
fi

# ---------------------------------------------------------------------------
step "step 2/5 · export — the ship-set into a fresh init, no platform history"
# ---------------------------------------------------------------------------
if [ -z "$TARGET" ]; then
    # Derived from the checkout, exactly as `scripts/db.sh` derives a database
    # name: two checkouts of one branch never collide, and two agents never
    # publish into each other's artifact.
    hash8=$(printf '%s' "$ROOT" | shasum -a 256 2>/dev/null | cut -c1-8) ||
        hash8=$(printf '%s' "$ROOT" | sha256sum | cut -c1-8)
    branch=$(git rev-parse --abbrev-ref HEAD | tr -c 'a-zA-Z0-9' '-')
    TARGET="${TMPDIR:-/tmp}/djb-publish-${branch}-${hash8}"
fi
case "$TARGET" in
/*) ;;
*) TARGET="$PWD/$TARGET" ;;
esac
say "   target     $TARGET"

# THE DESTRUCTION GUARD. This path is removed and rebuilt on every run, so it
# refuses to touch anything it cannot recognise as a previous artifact of its
# own: absent, empty, or carrying the stamp a previous run left. Nothing else.
STAMP=".publish-artifact"
if [ -e "$TARGET" ]; then
    if [ ! -d "$TARGET" ]; then
        echo "!! target exists and is not a directory: $TARGET" >&2
        exit 2
    elif [ -f "$TARGET/$STAMP" ]; then
        rm -rf "$TARGET"
    elif [ -z "$(ls -A "$TARGET")" ]; then
        rmdir "$TARGET"
    else
        echo "!! target is not empty and carries no $STAMP stamp: $TARGET" >&2
        echo "   This script will not delete a directory it cannot prove it wrote." >&2
        exit 2
    fi
fi
mkdir -p "$TARGET"

git archive --format=tar "$SRC_SHA" | (cd "$TARGET" && tar -xf -)

# Remove what does not ship. The lists are the census's, so nothing here is a
# second opinion about what a path is.
while IFS= read -r p; do [ -n "$p" ] && rm -f "$TARGET/$p"; done <"$TRIM_LIST"
while IFS= read -r p; do [ -n "$p" ] && rm -f "$TARGET/$p"; done <"$SRC_LIST"
# Substitute each ledger that has a committed skeleton.
for name in $LEDGERS; do
    src="$ROOT/docs/product/skeletons/$name.md"
    [ -f "$src" ] && cp "$src" "$TARGET/docs/product/$name.md"
done
find "$TARGET" -type d -empty -delete

# The stamp is written BEFORE the commit and is itself trimmed from the index —
# it exists so the destruction guard above can recognise this directory next
# run, and it must never reach a product's first commit.
#
# IT MUST ALSO NOT LEAVE THE DELIVERED TREE DIRTY. Not committed and not
# ignored is UNTRACKED, and an artifact whose `git status` is not clean hands
# its new owner two problems on day one: a file they did not write and cannot
# explain, and a `publish.sh` of their own that the dirty-tree guard at the top
# of this script refuses before it does anything. Deleting the stamp after the
# commit would fix the status and BREAK THE GUARD — the next run would find a
# non-empty, unstamped directory and refuse to touch it, which is the guard
# working exactly as designed against its own author. So the stamp stays and is
# IGNORED instead, below.
#
# THE IGNORE GOES IN `.git/info/exclude`, NOT IN THE SHIPPED `.gitignore`, and
# that is the whole of the reasoning: the stamp is this script's own artefact,
# so hiding it is this script's own job. A `.gitignore` line would make the
# instrument's correctness depend on a file it SHIPS still saying what it says —
# an invariant it cannot enforce in a product's tree and does not hold in its
# own drive's fixture, which builds a minimal `.gitignore` of its own. Writing
# the exclude here holds for every target this script will ever create,
# including the ones a product publishes from this file, and keeps one opinion
# about the stamp in the one file that knows the stamp exists.
: >"$TARGET/$STAMP"

(
    cd "$TARGET"
    git init -q -b main
    mkdir -p .git/info
    printf '# %s — written by scripts/publish.sh, which needs this file to\n' "$STAMP" >>.git/info/exclude
    printf '# recognise this directory as its own before rebuilding it.\n' >>.git/info/exclude
    printf '%s\n' "$STAMP" >>.git/info/exclude
    git -c core.excludesFile=/dev/null add -f -A -- . ":(exclude)$STAMP"
    git -c user.name=publish -c user.email=publish@localhost \
        -c commit.gpgsign=false commit -q -m "Initial commit — Pilecap template" \
        --author="publish <publish@localhost>"
) || {
    echo "!! the artifact repository could not be initialised — see above" >&2
    exit 2
}

# THE ARTIFACT IS DELIVERED CLEAN, and that is asserted rather than assumed.
# A dirty working tree in the thing we just built is not a violation of a rule
# about content — it is this instrument failing to leave its own output in the
# state it promises, so it is exit 2 with the dirt listed, the way the dirty
# SOURCE refusal at the top of this script is.
ART_DIRT=$(git -C "$TARGET" status --porcelain)
if [ -n "$ART_DIRT" ]; then
    echo "!! the exported artifact's working tree is NOT clean. Everything the" >&2
    echo "   census ships is committed and everything else is ignored — a third" >&2
    echo "   state means the export left a file behind that its new owner would" >&2
    echo "   inherit as unexplained dirt, and whose own publish.sh would then be" >&2
    echo "   refused by the dirty-tree guard. Could-not-look, not a violation." >&2
    printf '%s\n' "$ART_DIRT" | sed 's/^/     /' >&2
    exit 2
fi

TREE=$(git -C "$TARGET" rev-parse HEAD^{tree})
say "   exported   $(git -C "$TARGET" ls-files | wc -l | tr -d ' ') files"
# THE IDEMPOTENCE CLAIM IS ITS OWN LINE. Two runs at the same source sha must
# print the same hash; the commit sha will differ (it carries a timestamp) and
# is deliberately not the claim.
say "   tree       $TREE"

# ---------------------------------------------------------------------------
step "step 3/5 · leg file-set — the artifact is exactly the census's ship-set"
# ---------------------------------------------------------------------------
ACTUAL=$(mktemp "${TMPDIR:-/tmp}/djb-publish-actual.XXXXXX")
git -C "$TARGET" ls-files | LC_ALL=C sort >"$ACTUAL"
if ! diff -u "$EXPECTED" "$ACTUAL" >/dev/null; then
    echo "!! the artifact's file set is not the census's ship-set. The export and the" >&2
    echo "   census disagree, which means one of them is not the derivation it claims" >&2
    echo "   to be — a could-not-look, not a violation." >&2
    diff -u "$EXPECTED" "$ACTUAL" | sed 's/^/     /' >&2
    rm -f "$ACTUAL"
    exit 2
fi
rm -f "$ACTUAL"
say "   ok — $(wc -l <"$EXPECTED" | tr -d ' ') paths, nothing added and nothing lost"

# ---------------------------------------------------------------------------
step "step 4/5 · the verification legs, against the ARTIFACT"
# ---------------------------------------------------------------------------

# --- leg byte-identity (invariant 1) ----------------------------------------
say ""
say "-- byte-identity: quality/** and instruments.md ship verbatim"
bi_n=0
bi_bad=0
while IFS= read -r p; do
    case "$p" in
    quality/* | docs/product/instruments.md) ;;
    *) continue ;;
    esac
    bi_n=$((bi_n + 1))
    a=$(git hash-object "$ROOT/$p")
    b=$(git hash-object "$TARGET/$p" 2>/dev/null || echo missing)
    if [ "$a" != "$b" ]; then
        violation "byte-identity: $p  source $a  artifact $b"
        bi_bad=$((bi_bad + 1))
    fi
done <"$SHIP_LIST"
if [ "$bi_n" -eq 0 ]; then
    echo "!! byte-identity had nothing to compare — the learning layer is not in the" >&2
    echo "   ship-set at all, which is a broken derivation, not a clean run." >&2
    exit 2
fi
[ "$bi_bad" -eq 0 ] && say "   ok — $bi_n gate-read files byte-identical to the source"

# --- leg adr-census (invariant 2) ------------------------------------
say ""
say "-- adr-census: every ADR id cited in the artifact resolves in the artifact"
HOMES=$(mktemp "${TMPDIR:-/tmp}/djb-publish-homes.XXXXXX")
for h in docs/product/architecture.md docs/product/adrs-ingredients.md; do
    [ -f "$TARGET/$h" ] || {
        echo "!! $h is not in the artifact — the ADR home does not ship, so no citation" >&2
        echo "   in it can resolve. That is the ruling broken, not a violation." >&2
        rm -f "$HOMES"
        exit 2
    }
    grep -hoE 'ADR [a-z0-9]+-[a-z0-9]+' "$TARGET/$h" || true
done | LC_ALL=C sort -u >"$HOMES"
if [ ! -s "$HOMES" ]; then
    echo "!! the ADR homes named no ids at all — the grammar this leg reads is" >&2
    echo "   \`ADR <app>-<n>\`, and a home with none of them is this leg looking at the" >&2
    echo "   wrong thing." >&2
    rm -f "$HOMES"
    exit 2
fi
CITED=$(mktemp "${TMPDIR:-/tmp}/djb-publish-cited.XXXXXX")
(cd "$TARGET" && grep -rIoE 'ADR [a-z0-9]+-[a-z0-9]+' --exclude-dir=.git . || true) |
    sed 's|^\./||' | LC_ALL=C sort -u >"$CITED"
adr_bad=0
while IFS= read -r line; do
    [ -n "$line" ] || continue
    id=${line#*:}
    file=${line%%:*}
    if ! grep -qxF "$id" "$HOMES"; then
        violation "adr-census: $id resolves nowhere in the artifact — cited in $file"
        adr_bad=$((adr_bad + 1))
    fi
done <"$CITED"
say "   $(LC_ALL=C sort -u -t: -k2 "$CITED" | wc -l | tr -d ' ') citation sites read · $(wc -l <"$HOMES" | tr -d ' ') ids resolvable in the two homes"
[ "$adr_bad" -eq 0 ] && say "   ok — no decision is lost at publish"
rm -f "$HOMES" "$CITED"

# --- leg dangling-docs (invariant 2's sibling) ------------------------------
# THE SAME QUESTION FOR ORDINARY POINTERS. Trimming is exactly the operation
# that turns a live citation into a dead one, and a first builder reading
# `docs/product/cycles/…` in a docstring finds nothing there and cannot tell
# whether the claim was ever true. Closed question, discoverable population:
# every `docs/**.md` path spelled anywhere in the artifact must exist in it.
say ""
say "-- dangling-docs: every docs/ pointer spelled in the artifact resolves in it"
DOCREFS=$(mktemp "${TMPDIR:-/tmp}/djb-publish-docrefs.XXXXXX")
(cd "$TARGET" && grep -rIoE 'docs/[A-Za-z0-9._/-]+\.md' --exclude-dir=.git . || true) |
    sed 's|^\./||' | LC_ALL=C sort -u >"$DOCREFS"
dang_bad=0
while IFS= read -r line; do
    [ -n "$line" ] || continue
    ref=${line#*:}
    file=${line%%:*}
    [ -f "$TARGET/$ref" ] && continue
    violation "dangling-docs: $ref does not exist in the artifact — spelled in $file"
    dang_bad=$((dang_bad + 1))
done <"$DOCREFS"
say "   $(wc -l <"$DOCREFS" | tr -d ' ') pointer sites read"
[ "$dang_bad" -eq 0 ] && say "   ok — every docs/ pointer in the artifact resolves inside it"
rm -f "$DOCREFS"

# --- leg archaeology-census (invariant 3) -----------------------------------
# THE PLATFORM'S CONSTRUCTION HISTORY IS NOT THE PRODUCT'S. A template is read
# by a stranger who was in none of the cycles that built it. A finding id, a
# rung token, a verification-pass name or a private product name left in a
# shipped file is a citation that resolves nowhere for that reader — the same
# defect `dangling-docs` catches for file pointers, one layer down: at the level
# of VOCABULARY rather than paths, and therefore invisible to every leg above.
#
# Closed question over a discoverable population, exactly like the census
# itself: a closed set of literal shapes, read over every shipped byte. It
# catches the SHAPE it is given and never intent — `does_not_cover` at the foot
# of this leg says so in five clauses, and they are declared here rather than
# discovered later.
#
# THE PATTERNS ARE ASSEMBLED, NEVER SPELLED, wherever a literal would match
# itself. This file SHIPS (R3), so a deny-listed name or a narrative phrase
# written out in full here IS the string the leg refuses, and the guard would
# red on its own author — the same hazard R8's glob and the drive's fixture
# paths are written around, and the same fix: name it in halves no pattern can
# join.
say ""
say "-- archaeology-census: the platform's build history is not in the product's tree"
_ru=rung
_at=icus
_ac=us-crm
_jo=union
_pd='\.dev'
_bs=Bootstrap
_ev='[-/](staging|prod)'
ARCHHITS=$(mktemp "${TMPDIR:-/tmp}/djb-publish-arch.XXXXXX")
arch_bad=0
arch_read=$(wc -l <"$SHIP_LIST" | tr -d ' ')
if [ "${arch_read:-0}" -eq 0 ]; then
    echo "!! archaeology-census had no ship-set to read. A tree nobody looked at is" >&2
    echo "   not a clean tree — could-not-look, not a pass." >&2
    rm -f "$ARCHHITS"
    exit 2
fi
arch_class() { # arch_class <label> <ere> [scrub-noqa]
    local label=$1 pat=$2 scrub=${3:-} rc=0 hit file line text matched
    set +e
    (cd "$TARGET" && grep -rInE "$pat" --exclude-dir=.git .) >"$ARCHHITS" 2>/dev/null
    rc=$?
    set -e
    if [ "$rc" -gt 1 ]; then
        echo "!! archaeology-census: the scan for '$label' could not read the artifact" >&2
        echo "   (grep exited $rc). A tree nobody looked at is not a clean tree." >&2
        rm -f "$ARCHHITS"
        exit 2
    fi
    while IFS= read -r hit; do
        [ -n "$hit" ] || continue
        hit=${hit#./}
        file=${hit%%:*}
        hit=${hit#*:}
        line=${hit%%:*}
        text=${hit#*:}
        if [ -n "$scrub" ]; then
            # ALLOW-LIST, with its reason: a linter rule id inside a `noqa:`
            # directive is a ruff/flake8 code and not a finding id — the two
            # share a shape and nothing else. The directive is scrubbed from
            # the LINE before the pattern is applied, so the code stays legible
            # in the tree where the linter needs it.
            text=$(printf '%s' "$text" |
                sed -E 's/noqa:[[:space:]]*[A-Z]+[0-9]+([[:space:]]*,[[:space:]]*[A-Z]+[0-9]+)*//g')
        fi
        matched=$(printf '%s' "$text" | grep -oE "$pat" | head -1 || true)
        [ -n "$matched" ] || continue
        violation "archaeology-census: $file:$line  $label  \"$matched\""
        arch_bad=$((arch_bad + 1))
    done <"$ARCHHITS"
}
# 1 · finding ids. The queue's row ids, which live in a ledger that ships as a
#     skeleton — so every one of them resolves nowhere in the artifact.
arch_class finding-id '\bN[0-9]{2,3}\b' scrub-noqa
# 2 · rung and cycle tokens. The plan's own coordinates, and cycle plans trim.
arch_class rung-token '\bP[0-9]{1,2}-[0-9]+\b'
# 3 · the NARRATIVE forms of the method's vocabulary, and only those. A named
#     verification pass is an instance of a run nobody outside this repository
#     watched; the bare stage name is shipped vocabulary and stays (below).
arch_class narrative "PROVE-[A-Za-z0-9]+|this $_ru"
# 4 · the private-name deny-list: the sibling product, its repository slug, the
#     owner's account handle, and the platform's own deployment domain.
arch_class private-name "Att$_at|attic$_ac|joe$_jo|pilecap$_pd"
# 5 · the template's FORMER name, in the TitleCase form the brand carried,
#     matched CASE-SENSITIVELY — which is the whole mechanism. The owner's
#     ruling of 2026-08-26 moved the brand and kept the infrastructure
#     namespace, and every surviving site of the old name is lowercase by
#     construction (the compose project, the `DJB_`/`djb_` prefixes, the
#     Zitadel logins — the allow-list below closes that set). So case IS the
#     discriminator between the identity that moved and the namespace that did
#     not, and a case-insensitive scan here could only ever be born red.
arch_class former-brand "Django$_bs"
# 6 · deployment coordinates of the account this platform is developed in: the
#     slug joined to an environment by `-` (IAM roles, S3 buckets, EC2 tags) or
#     by `/` (the secrets-manager prefix). The slug ALONE is the product name
#     and ships; it is the JOIN that names somebody's real resources, which is
#     why the shape rather than the word is what is denied. The deploy scripts
#     compose these from one refuse-unset variable, so a clone that carries no
#     value addresses nothing at all — this leg is the belt on that.
arch_class deploy-coordinate "pilecap$_ev"
rm -f "$ARCHHITS"
#
# THE ALLOW-LIST, each entry with the reason it is allowed. Most of them match
# no pattern above and are recorded here so that nobody ADDS them by
# mistake — a deny-list is only as good as the argument for what it leaves out.
#   · `Pilecap` — ships deliberately. `architecture.md`'s product-name
#     decision makes it the default of one env-backed setting that every
#     showing surface derives from, so a fresh clone is honest about being the
#     template and a product renames it in one place. A name this repository
#     CHOOSES to carry is the opposite of a private one. (The decision is named
#     rather than cited by id, for this file's own standing reason: an `ADR
#     <app>-<n>` spelled here is a citation in every artifact this script
#     publishes, including a fixture whose homes carry no such id — the guard
#     reading its own author, which is what the drive caught when it did.)
#     It is also the shape of the LOWERCASE wire identifiers — the MCP server
#     name and the outbound User-Agent tokens — which are literals rather than
#     derivations, for the reason that row records.
#   · lowercase `djangobootstrap` — the infrastructure namespace, which the
#     owner's ruling of 2026-08-26 kept when the brand above replaced it: the
#     compose project name, the `DJB_` environment prefix and the `djb_`
#     database prefix are what containers, volumes and per-checkout databases
#     key on, and renaming them orphans a running stack and its data. The
#     surviving classes are closed, and every member is lowercase: the compose
#     project name and the two docs that quote it; the Zitadel first-instance
#     LOGINS (the admin username, the dev user's email) and the settings
#     default behind them, which are account identifiers already created; the
#     real container names a chaos-drill docstring stops by name; and the
#     setup, rung-start and kill scripts that key on the project name. Nothing
#     in that list is a display surface, which is why the rename left them
#     standing and this entry names them rather than counting them. Pattern 5
#     is what makes this entry an ALLOW rather than a hope: it denies the
#     TitleCase form only, so the lowercase survivors above are outside its
#     scope by construction rather than by anybody remembering to skip them.
#   · the bare slug `pilecap`, in any case-form that is the BRAND — the
#     product-name default, the package name, the identity-platform example
#     values, the lowercase wire identifiers. Pattern 6 denies only the
#     coordinate SHAPE (the slug joined to an environment), so the name a
#     stranger is supposed to read ships and the account's real resource names
#     do not. `pilecap-connections/…` is the worked case: legal, and silent.
#   · the worked-example marker — NINE ledger skeletons carry it, one each, and
#     the census above is what proves that (the artifact's raw count of the
#     string is higher, because the manifest and this script both name the
#     marker in order to define it). It is the template TELLING a reader that a
#     row is an example: the cure for archaeology, not an instance of it.
#   · the bare stage name `PROVE` — the method's stage 6, in headings such as
#     the verdict block and in the stage list. Shipped vocabulary. Only the
#     INSTANCE form is archaeology, which is why pattern 3 requires the hyphen
#     AND a suffix; two rungs reached that conclusion independently.
#   · `house rule <n>` / `rule <n>` / `ADR <app>-<n>` — the system's permanent
#     numbering, matched by nothing here. Whether such a citation RESOLVES is
#     `adr-census`'s question, running beside this leg, and stays there.
#
# WHAT THIS LEG DOES NOT COVER, declared rather than discovered:
#   · A rephrased incident narration that avoids every literal pattern in the
#     closed set (spelling out "in an earlier cycle we found…" with no id) is
#     invisible. This is a closed-question check over a discoverable population:
#     it catches the shape it is given, never intent.
#   · A new private name not yet on the deny-list is invisible until somebody
#     adds it — the same limitation every allow-list in `quality/rules.yaml`
#     openly carries.
#   · Anything outside the exported ship-set is out of scope BY CONSTRUCTION.
#     It reads only what actually ships.
#   · Pattern 6 knows exactly two environment names. An environment coined
#     later — a `-preview`, a `-sandbox` — is invisible to it until somebody
#     adds the word, which is the same closed-list limitation the deny-list
#     above carries and is declared here rather than found by a leak.
#   · Pattern 5 is deliberately blind to the lowercase form of the former
#     name. That is not a gap in the scan; it is the owner's ruling, and the
#     allow-list above is where the argument for it lives. A lowercase site
#     that is NOT infrastructure identity is therefore something only a reader
#     catches.
#   · Neither new pattern sees a REPHRASING. "the Django bootstrap template",
#     or a coordinate spelled with the environment first, walks past both — the
#     leg catches shapes, never intent, exactly as its header says.
#   · It does not judge whether a permanent-numbering citation it declines to
#     flag is itself dangling into trimmed history — that is `adr-census`'s job,
#     unchanged, running beside it.
#   · BUILD DATES ARE NOT SCANNED, and that is a measured decision rather than
#     an oversight. Two shipped populations REQUIRE a literal date: a rule's
#     `MOVE-TRIGGER` annotation, which `apps/core/tests/test_plant_sites.py`
#     reads back and asserts is dated, and every `Lifecycle` trigger, which
#     house rule 31 requires to be dated. A date scan cannot be born green
#     against a tree whose own tests demand the dates it would refuse. The
#     narration half is real and unpaid; wiring it is a rung of its own, after
#     the strip, and it will need the AWS IAM policy-version literal
#     (`2012-10-17`, an AWS constant carried by the deploy files) excluded as a
#     matched STRING, plus path excludes for the lockfile, the migrations, the
#     secrets baseline, and the example cycle plan whose own format field
#     mandates a fictional date.
say "   $arch_read shipped files read · 6 violation classes"
[ "$arch_bad" -eq 0 ] &&
    say "   ok — no finding id, rung token, narrative instance, private name," &&
    say "        former brand or deployment coordinate ships"

# --- leg secrets (rule 23, over the ARTIFACT) -------------------------------
# THE FULL-TREE SCAN RUNS AGAINST THE ARTIFACT AND NOT AGAINST THE SOURCE. The
# trim itself can surface what the source's history hid: a file that only ever
# read as archaeology beside its cycle plan reads differently alone in a public
# template, and the published tree is the thing a stranger clones.
say ""
say "-- secrets: detect-secrets over the WHOLE artifact vs its shipped baseline"
HOOK=""
if [ -x "$ROOT/.venv/bin/detect-secrets-hook" ]; then
    HOOK="$ROOT/.venv/bin/detect-secrets-hook"
elif command -v detect-secrets-hook >/dev/null 2>&1; then
    HOOK=$(command -v detect-secrets-hook)
fi
if [ -z "$HOOK" ]; then
    echo "!! detect-secrets-hook is not installed — the artifact was NOT scanned." >&2
    echo "   A tree nobody looked at is not a clean tree." >&2
    echo "   Fix: run \`uv sync\` in $ROOT (it installs the hook into .venv/bin/)," >&2
    echo "   then re-run this script." >&2
    exit 2
fi
[ -f "$TARGET/.secrets.baseline" ] || {
    echo "!! the artifact carries no .secrets.baseline — the scan has nothing to" >&2
    echo "   compare against, and every finding would be new. Could-not-look." >&2
    exit 2
}
set +e
(cd "$TARGET" && git ls-files -z | xargs -0 "$HOOK" --baseline .secrets.baseline)
SEC_RC=$?
set -e
if [ "$SEC_RC" -eq 0 ]; then
    say "   ok — no unbaselined secret in the published tree"
else
    violation "secrets: detect-secrets exited $SEC_RC over the artifact (output above)"
fi

# ---------------------------------------------------------------------------
step "step 5/5 · the verdict"
# ---------------------------------------------------------------------------
say "   artifact   $TARGET"
say "   source     $SRC_SHA"
say "   tree       $TREE"
if [ "$VIOLATIONS" -gt 0 ]; then
    say ""
    say "== $VIOLATIONS VIOLATION(S) — the artifact was built and is NOT publishable."
    say "   Each line above names the id or the path and the file that cites it."
    exit 1
fi
say ""
say "== CLEAN · re-run and compare the tree line: it is the idempotence claim."
exit 0
