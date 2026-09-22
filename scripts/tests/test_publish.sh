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
# drives: .secrets.baseline README.md TEMPLATE_VERSION apps/example/models.py docs/product docs/runbooks/deploy.md scripts/archaeology_lib.sh scripts/backup.sh scripts/check.sh scripts/db.sh scripts/docs_legs.sh scripts/kill_mine.sh scripts/loop_tier.sh scripts/publish.sh scripts/queue_cited.sh scripts/sweep.sh scripts/tests
# cites: CHANGELOG.md manage.py scripts/test_impact.json scripts/pytest_durations.json scripts/gate_member_durations.json
# The refusal-and-property drive for `scripts/publish.sh`.
#
# Exit: 0 every case held · 1 a refusal did not fire or a property did not hold
#       · 2 COULD NOT LOOK (no git, no detect-secrets, a fixture that would not
#       build). 2 outranks a pass here for the reason it does everywhere.
#
# WHY IT EXISTS. `publish.sh` is made almost entirely of refusals — an unplaced
# path, a dirty source, an orphan skeleton, a target it cannot prove it wrote —
# and every one of them was true exactly once, on the day it was written. That
# is the state `scripts/backup.sh` and `scripts/sweep.sh` were each in before
# their own drives existed, and it is the class `scripts/check.sh`'s selftest leg exists to
# end. It also drives the two properties nothing else can see: that the census
# actually TRIMS (the artifact has no archaeology in it) and that the export is
# IDEMPOTENT (two runs at one source sha, one exported tree hash).
#
# IT BUILDS ITS OWN REPOSITORY. Every case runs against a throwaway tree under
# `mktemp -d` carrying a copy of publish.sh and a minimal file per bucket rule,
# so nothing in this checkout is read, published or deleted, and the drive's
# verdict does not move when the real tree does. No docker and no database — so
# unlike its backup/sweep siblings it can never degrade to could-not-look on a
# bare machine, provided detect-secrets is installed (the secrets leg's own
# dependency, and its absence is honestly a could-not-look).
#
# WIRED INTO `scripts/check.sh`'s selftest leg. It was a declared debt for one
# cycle rather than a decision — the drive list lives in `scripts/check.sh`,
# which was another rung's exclusive territory in the wave that wrote this file
# — and the rung that next owned that file paid it. **BY HAND IS A PROMISE; A
# LEG IS A MEASUREMENT** — the same sentence check.sh uses about every drive
# that spent a cycle unwired.
set -euo pipefail

if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! this drive refuses pipes — its exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before anything asks git a question ----
#
# THIS DRIVE IS THE INCIDENT'S OWN SHAPE. `scripts/tests/drive_preamble.sh`
# exists because a drive that builds throwaway repositories and talks to them
# with `git -C "$SCRATCH" ...` writes into the REAL repository instead whenever
# it inherits an absolute `GIT_DIR` — which it does when it is run from the
# pre-push hook. Everything below builds fixtures exactly that way, and the
# release cases go further still: they tag, reset and clone. A stray
# `git -C "$PUB" tag -a v0.1.0` under an inherited `GIT_DIR` is a release tag
# in this repository's own refs.
#
# It was the last drive under `scripts/tests/` not sourcing this file, and the
# EXIT trap it carried instead was a bare one — so it had no registered
# cleanups, no real-repository tripwire and no died-before-reporting check,
# which the plant runs for the release cases demonstrated by ending at git's
# own exit 128 with the `passed · failed` line never printed.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_publish: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the neutralisation that keeps every fixture repository" >&2
    echo "   below out of the real one. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

# AFTER the source, never before: the preamble assigns this variable 0 itself
# itself (drive_preamble.sh, `DRIVE_OPTED_IN_TO_FINISH=0`), so an opt-in written above the source line is
# silently overwritten and the death check never arms. Caught by planting an
# unbound variable before the summary and watching the drive exit 0 anyway —
# which is the exact failure the check exists to prevent, wearing the check's
# own clothes.
DRIVE_OPTED_IN_TO_FINISH=1

ROOT=$(pwd -P)
PUBLISH="$ROOT/scripts/publish.sh"
[ -x "$PUBLISH" ] || {
    echo "!! $PUBLISH is not executable — nothing to drive" >&2
    exit 2
}
command -v git >/dev/null 2>&1 || {
    echo "!! no git" >&2
    exit 2
}
if [ -x "$ROOT/.venv/bin/detect-secrets-hook" ]; then
    PATH="$ROOT/.venv/bin:$PATH"
    export PATH
fi
command -v detect-secrets-hook >/dev/null 2>&1 || {
    echo "!! detect-secrets-hook is not installed — publish.sh's secrets leg cannot" >&2
    echo "   run, so this drive cannot clear it. That is a could-not-look." >&2
    exit 2
}
command -v detect-secrets >/dev/null 2>&1 || {
    echo "!! detect-secrets is not installed — the fixture cannot build a baseline" >&2
    exit 2
}

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-publish.XXXXXX") || exit 2
# The scratch belt, then the cleanup REGISTERED rather than trapped: the
# preamble owns the EXIT trap so the real-repository tripwire runs last on
# every exit path, and a bare `trap ... EXIT` here would silently remove it.
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

# --- the fixture -------------------------------------------------------------
# One tracked file per bucket rule, and no more: the census's job is to place
# every tracked path, so the smallest tree that exercises every rule is also the
# clearest statement of what the rules are.
LEDGERS="north-star queue queue-detail readouts misses in-flight goal-posts design-agreements pilot-readiness rep-day"

# THE PATHS BELOW ARE ASSEMBLED, NEVER SPELLED. This drive is a shipped file
# (bucket R3), and `publish.sh`'s `dangling-docs` leg counts `docs/**.md`
# strings WHEREVER THEY APPEAR — a docstring, a comment, a fixture. A literal
# `docs/product/cycles/<plan>.md` written here would therefore make the drive
# itself a dead pointer in every artifact it helps publish: the guard counting
# its own author. Same class as a censused marker spelled in prose, same fix —
# name it in pieces the pattern cannot join.
PROD="docs/product"
CY="$PROD/cycles"
SK="$PROD/skeletons"
PLAN="plan.md"
# Same hazard, `adr-census`'s side of it: an `ADR <app>-<n>` spelled here is a
# citation IN THE ARTIFACT, and the fixture's ids resolve only in the fixture.
ADR_REAL="core-1"
ADR_SECOND="search-1"
ADR_GHOST="ghost-9"
HANDOFF="pm-handoff-2026-03-01.md"
MARKER='<!-- worked example — replace with your product'"'"'s first real entry -->'

build_fixture() {
    local d=$1
    rm -rf "$d"
    mkdir -p "$d/apps/example" "$d/config" "$d/quality" "$d/scripts" \
        "$d/frontend" "$d/$CY" "$d/$SK" "$d/docs/runbooks"
    cp "$PUBLISH" "$d/scripts/publish.sh"
    chmod +x "$d/scripts/publish.sh"
    # publish.sh sources this — the bucket rules and the archaeology-census
    # scan, shared with scripts/check.sh's `archaeology` leg. Without
    # it in the fixture, every run here would die at the `.` line rather than
    # exercising the census this drive is testing.
    cp "$ROOT/scripts/archaeology_lib.sh" "$d/scripts/archaeology_lib.sh"
    # AND THE SEAM THAT LIBRARY ITSELF SOURCES. `archaeology_lib.sh` opens with
    # `. "${BASH_SOURCE[0]%/*}/gate_refuse.sh"`, so a fixture that hand-copies
    # the library WITHOUT this file dies at that line — every case here exited 1
    # with `scripts/archaeology_lib.sh: line 46: .../gate_refuse.sh: No such
    # file or directory` the night the seam landed. The library is deliberately
    # NOT tolerant of an absent seam (a tolerant library would hide exactly this
    # class), so the copy list is what has to stay honest: a fixture copies a
    # seam library WITH its seam. The population is pinned by
    # case_every_fixture_that_copies_a_seam_library_copies_the_seam in
    # scripts/tests/test_gate_lease.sh.
    cp "$ROOT/scripts/gate_refuse.sh" "$d/scripts/gate_refuse.sh"
    # AND THE SECOND LIBRARY publish.sh SOURCES, for the first one's reason
    # exactly. The `adr-census` and `dangling-docs` bodies moved into
    # `scripts/docs_legs.sh` so that `scripts/check.sh` could run them per rung
    # over the changed files while this file keeps running them over the whole
    # artifact — one body, two callers. A fixture without it dies at the `.`
    # line, which is what the copy list above exists to prevent; it is a seam
    # library too, and its seam is already here.
    cp "$ROOT/scripts/docs_legs.sh" "$d/scripts/docs_legs.sh"
    echo "# a model" >"$d/apps/example/models.py"
    # R11's one member. The rule is a GLOB over the whole client directory, so
    # one file inside it is the whole arm: without this the rule's row prints 0
    # and every green run of this drive says nothing about the client layer's
    # disposition. It is a scaffold manifest rather than a source file because
    # that is the member the rule's own comment names first.
    echo '{"name":"scaffold"}' >"$d/frontend/package.json"
    echo "# settings" >"$d/config/settings.py"
    echo "# manage" >"$d/manage.py"
    echo "rules: []" >"$d/quality/rules.yaml"
    echo "| Instrument | a | b | c | d |" >"$d/docs/product/instruments.md"
    echo "# the gate" >"$d/scripts/check.sh"
    # A FLAG LITERAL IN THE FIXTURE'S OWN GATE, for `changelog-flags` to
    # resolve a green claim against. One line, and it is the whole of what
    # that leg reads: a flag is a literal in the named script, or it is not.
    echo "# --loop is this fixture gate's one declared flag" >>"$d/scripts/check.sh"
    # R12's three members. THE ARM IS DECORATION WITHOUT THEM — exactly R11's
    # lesson one rule over: a bucket rule whose row prints 0 is as untested as
    # a rule that is missing, and R12's whole point is that these three files
    # do NOT reach the artifact. They are planted with real-shaped content
    # (the writers' own top-level keys) so that a case reading the artifact
    # for them is reading for the thing a consumer would actually inherit.
    printf '{"generated":{"tree":"tree:%s","pytest":3},"tests":{}}\n' \
        "0000000000000000000000000000000000000000" >"$d/scripts/test_impact.json"
    printf '{"a::b": 0.5}\n' >"$d/scripts/pytest_durations.json"
    printf '{"measured_at":"tree:0000000","machine":"fixture","members":{}}\n' \
        >"$d/scripts/gate_member_durations.json"
    echo "[project]" >"$d/pyproject.toml"
    printf '*.log\n' >"$d/.gitignore"
    echo "# the guide" >"$d/CLAUDE.md"
    echo "# readme" >"$d/README.md"
    echo "# deploy" >"$d/docs/runbooks/deploy.md"
    # R5's one non-glob path. `publish.sh` SPELLS it in its own rule, so the
    # same self-citation hazard the R9 block below carries applies here: a
    # fixture without this file reddens `dangling-docs` on the instrument
    # citing itself.
    echo "# standards" >"$d/docs/standards.md"
    echo "0.1.0" >"$d/TEMPLATE_VERSION"
    echo "# changelog" >"$d/CHANGELOG.md"
    echo "# architecture — ADR $ADR_REAL says so" >"$d/docs/product/architecture.md"
    echo "# ingredients — ADR $ADR_SECOND" >"$d/docs/product/adrs-ingredients.md"
    # The rest of R9's explicit per-file dispositions. They are here because
    # `publish.sh` SPELLS each of these paths in its own rule, and leg
    # `dangling-docs` reads `docs/**.md` strings wherever they appear — so a
    # fixture missing them would redden on the instrument citing itself, which
    # is a fixture defect and not a finding.
    for f in api-editorial-standard build-contract \
        operating-protocol partition-closure scale-envelope publication-manifest; do
        echo "# $f" >"$d/docs/product/$f.md"
    done
    echo "# a cycle plan, trimmed" >"$d/$CY/$PLAN"
    echo "# a dated handoff, trimmed" >"$d/$PROD/$HANDOFF"
    for name in $LEDGERS; do
        printf '# %s\n\n%s\n\n> example row\n' "$name" "$MARKER" >"$d/docs/product/$name.md"
    done
    # ONE ledger substituted from a committed skeleton, EIGHT already skeletal:
    # both halves of the derivation are exercised in every clean run.
    printf '# queue — the skeleton\n\n%s\n\n> example row\n' "$MARKER" >"$d/$SK/queue.md"
    (
        cd "$d"
        detect-secrets scan >.secrets.baseline 2>/dev/null
        git init -q -b main
        git -c user.name=t -c user.email=t@t add -A
        git -c user.name=t -c user.email=t@t -c commit.gpgsign=false commit -q -m fixture
    )
}

run() { # run <dir> <args...> ; prints output to $OUT, sets RC
    local d=$1
    shift
    OUT="$WORK/out.$$"
    set +e
    (cd "$d" && ./scripts/publish.sh "$@") >"$OUT" 2>&1
    RC=$?
    set -e
}

FIX="$WORK/fixture"
build_fixture "$FIX" || {
    echo "!! the fixture would not build" >&2
    exit 2
}

echo "== publish.sh refusal + property drive"

# --- refusals ----------------------------------------------------------------
set +e
(cd "$FIX" && ./scripts/publish.sh --census | cat) >/dev/null 2>&1
rc=$?
set -e
[ "$rc" = 2 ] && ok "a piped stdout is refused (exit 2)" || bad "piped stdout: exit $rc, want 2"

run "$FIX" --nonsense
[ "$RC" = 2 ] && ok "an unknown flag is exit 2, never a quietly different run" || bad "unknown flag: exit $RC, want 2"

# --- every bucket rule fires on something ------------------------------------
# THE FIXTURE IS THE PROOF, AND AN ARM WITH NO MEMBER PROVES NOTHING. The rule
# ids are DERIVED now (publish.sh reads them out of `bucket_for_rule`'s own
# source rather than carrying a typed list), which closed the gap where a rule
# added to the bucket table got no row in the printed census. It did not close
# the other one: a rule can have its row, print `0`, and be as untested as a
# rule that is missing — the arm is reached by no tracked path in this tree, so
# nothing here would notice if its disposition changed or its clause was
# deleted. R11 is the live instance: it sends the client layer to SHIP, and this
# fixture had no client layer at all, so the arm was decoration in every green
# run of this drive.
run "$FIX" --census
if [ "$RC" = 0 ] && grep -E '^ +R11 +SHIP +[1-9]' "$OUT" >/dev/null; then
    ok "R11 places the client layer in SHIP, and the fixture has one for it to place"
else
    bad "R11's row is not a nonzero SHIP in the census — the arm is reached by no path in the fixture, so a green here asserts nothing about it. Census rows:
$(grep -E '^ +R[0-9]+' "$OUT" | sed 's/^/             /')"
fi

# R12 — THE MEASURED FILES, and the same argument as R11's above: the arm is
# proven by a fixture that has members for it to place, never by the rule
# existing. The row must be a NONZERO TRIM, because a zero row and a deleted
# clause read identically in a green run.
if [ "$RC" = 0 ] && grep -E '^ +R12 +TRIM +3$' "$OUT" >/dev/null; then
    ok "R12 places the three measured files in TRIM, and the fixture has all three"
else
    bad "R12's row is not \`TRIM 3\` in the census — the three measured files are the
             whole population of that rule, so anything else means the arm is
             unreached or the fixture lost a member. Census rows:
$(grep -E '^ +R[0-9]+' "$OUT" | sed 's/^/             /')"
fi

run "$FIX" --census --to "$WORK/x"
[ "$RC" = 2 ] && ok "--census with a target is refused (it exports nothing)" || bad "--census --to: exit $RC, want 2"

# --- case_r12_equals_the_readers_defaults ------------------------------------
# R12 IS THE ONE HAND LIST IN THE BUCKET RULES, AND THIS IS WHAT RE-DERIVES IT.
# The three names are typed in `rules_for` because there is no glob that means
# "the files our own boxes measured" — `scripts/*.json` would sweep up a
# configuration file the next rung writes. A hand list is legal here only
# because the population has an independent derivation: every one of the three
# is some reader's DEFAULT path, spelled at that reader's own `:-` fallback.
# So this case greps the readers and compares the two sets. A fourth measured
# file — a new default with no R12 row — reds here rather than shipping.
#
# IT READS THE REAL CHECKOUT, not the fixture, and that is deliberate: the
# derivation being pinned is a property of THIS tree's readers, and a fixture
# copy of them would only ever agree with itself.
r12_rule=$(awk '/hit="\$hit R12"/ {print}' "$ROOT/scripts/archaeology_lib.sh" |
    grep -oE 'scripts/[a-z_]+\.json' | LC_ALL=C sort -u || true)
r12_readers=$( {
    grep -ohE 'DJB_GATE_DURATIONS_PATH:-scripts/[a-z_]+\.json' "$ROOT/scripts/check.sh"
    grep -ohE 'DJB_GATE_MEMBER_DURATIONS:-scripts/[a-z_]+\.json' "$ROOT/scripts/check.sh"
    grep -ohE 'LOOP_SCOPE_MAP_PATH="scripts/[a-z_]+\.json"' "$ROOT/scripts/loop_tier.sh"
} | grep -oE 'scripts/[a-z_]+\.json' | LC_ALL=C sort -u || true)
if [ -z "$r12_rule" ] || [ -z "$r12_readers" ]; then
    bad "case_r12_equals_the_readers_defaults could not look: rule set '$r12_rule', reader set '$r12_readers' — one of the two greps found nothing, so nothing was compared"
elif [ "$r12_rule" = "$r12_readers" ]; then
    ok "R12's names ARE the three readers' own defaults ($(echo "$r12_rule" | tr '\n' ' '))"
else
    bad "R12 and the readers' defaults disagree — a measured file with no bucket row ships, or a row names a file nobody reads.
             R12:     $(echo "$r12_rule" | tr '\n' ' ')
             readers: $(echo "$r12_readers" | tr '\n' ' ')"
fi

echo "dirt" >"$FIX/untracked-thing"
run "$FIX" --census
if [ "$RC" = 2 ] && grep -q "working tree is dirty" "$OUT"; then
    ok "a dirty source is refused — publish measures a commit"
else
    bad "dirty tree: exit $RC, want 2 naming the dirt"
fi
rm -f "$FIX/untracked-thing"

# --- the census's own refusals ----------------------------------------------
echo "who am i" >"$FIX/UNPLACEABLE.txt"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m unplaced)
run "$FIX" --census
if [ "$RC" = 2 ] && grep -q "UNPLACEABLE.txt" "$OUT"; then
    ok "a tracked path matching no rule is exit 2, named"
else
    bad "unplaced path: exit $RC, want 2 naming UNPLACEABLE.txt"
fi
(cd "$FIX" && git rm -q UNPLACEABLE.txt && git -c user.name=t -c user.email=t@t commit -q -m undo)

# --- R0: a reserved path is refused, and the refusal NAMES it ----------------
# THE DRAWER IS THE PRODUCT'S. A `local/` sibling of a template directory, and
# a `.local.md` sibling of a template document, are where a product extends the
# system layer without editing it (the extension-point decision) — which works only
# because the template never ships one, so a release cannot conflict with a
# drawer. Before R0 this fixture published a tracked drawer file CLEAN: bucket
# R3's `scripts/*` glob placed it in SHIP, every leg agreed, and the artifact
# carried it. The bucket rules were not wrong; the path was, and nothing read
# the path.
#
# BOTH SHAPES, because they are two globs and either can rot alone: a `local/`
# directory segment anywhere, and a `.local.md` document beside its template
# original. The second is planted under the docs tree the manifest actually
# reserves it in, and its name is ASSEMBLED for this drive's standing reason —
# a literal would be a pointer in every artifact this file helps publish.
#
# AND THE THIRD SHAPE IS AN EXACT PATH, WHICH IS WHY IT NEEDS ITS OWN CASE.
# The fixtures drawer is a `conftest.py` sibling pytest collects by name, so
# it cannot live under `apps/local/` and match the first glob — and R1 ships
# `apps/*` whole, so before R0 named it a tracked one shipped in silence.
# A shape that no glob reaches is the shape a glob-only drive cannot notice.
R0_DRAWER="scripts/local/legs/x.sh"
R0_DOC="$PROD/instruments"".local.md"
R0_FIXTURES="apps/conftest""_local.py"
for r0_path in "$R0_DRAWER" "$R0_DOC" "$R0_FIXTURES"; do
    mkdir -p "$FIX/$(dirname "$r0_path")"
    printf '# a product-owned extension\n' >"$FIX/$r0_path"
    (cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m reserved)
    run "$FIX" --census
    if [ "$RC" = 2 ] && grep -qF "$r0_path" "$OUT" && grep -q "RESERVED PATH IS TRACKED" "$OUT"; then
        ok "R0: a tracked $r0_path is exit 2, named — the template ships no drawer"
    else
        bad "R0 reserved path $r0_path: exit $RC, want 2 naming it"
        sed 's/^/         /' "$OUT"
    fi
    (cd "$FIX" && git rm -q "$r0_path" && git -c user.name=t -c user.email=t@t commit -q -m undo)
done
run "$FIX" --census
if [ "$RC" = 0 ] && grep -q "R0   reserved        none tracked" "$OUT"; then
    ok "R0 stays silent with no drawer tracked, and SAYS it looked"
else
    bad "R0 with no reserved path: exit $RC, want 0 with the census line printed"
fi

printf '# nothing\n' >"$FIX/$SK/not-a-ledger.md"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m orphan)
run "$FIX" --census
if [ "$RC" = 2 ] && grep -q "ORPHAN SKELETON" "$OUT"; then
    ok "a skeleton naming no ledger is exit 2 — the export would ignore it silently"
else
    bad "orphan skeleton: exit $RC, want 2"
fi
(cd "$FIX" && git rm -q "$SK/not-a-ledger.md" && git -c user.name=t -c user.email=t@t commit -q -m undo)

printf '# misses — no marker anywhere\n' >"$FIX/docs/product/misses.md"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m unmarked)
run "$FIX" --census
if [ "$RC" = 2 ] && grep -q "NEITHER" "$OUT"; then
    ok "a ledger neither substituted nor marked is exit 2 — a product would inherit real state"
else
    bad "unmarked ledger: exit $RC, want 2"
fi
printf '# misses\n\n%s\n\n> example row\n' "$MARKER" >"$FIX/docs/product/misses.md"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m restore)

# --- the clean run, and what it must be true of ------------------------------
ART="$WORK/artifact"
run "$FIX" --to "$ART"
if [ "$RC" = 0 ]; then
    ok "the clean fixture publishes: exit 0, every leg green"
else
    bad "clean publish: exit $RC, want 0"
    sed 's/^/         /' "$OUT"
fi
TREE1=$(git -C "$ART" rev-parse HEAD^{tree} 2>/dev/null || echo none)

[ -f "$ART/$CY/$PLAN" ] &&
    bad "the trim did not trim: cycles/plan.md is in the artifact" ||
    ok "TRIM holds — no cycle plan reached the artifact"
# --- case_the_measured_files_are_trimmed -------------------------------------
# R12's WHOLE POINT, asserted over the artifact rather than over the census.
# The census row above says what the rule DECIDED; this says what the export
# DID, and the two are different claims — the trim loop reads the census's own
# TRIM list, so a rule that classified correctly and a file that actually left
# are still two facts. Step 3's file-set leg green in the clean run above is
# the third: the artifact is exactly the ship-set, so a trimmed file that
# somehow survived would have reddened there too.
m_left=""
for m in scripts/test_impact.json scripts/pytest_durations.json scripts/gate_member_durations.json; do
    [ -e "$ART/$m" ] && m_left="$m_left $m"
    git -C "$ART" ls-files --error-unmatch "$m" >/dev/null 2>&1 && m_left="$m_left $m(indexed)"
done
if [ -z "$m_left" ]; then
    ok "the three MEASURED files are not in the artifact — on disk or in its index"
else
    bad "the measured files reached the artifact:$m_left"
fi

[ -d "$ART/docs/product/skeletons" ] &&
    bad "the skeleton SOURCES shipped at their own path" ||
    ok "the skeleton sources are consumed, not shipped"
if grep -q "the skeleton" "$ART/docs/product/queue.md" 2>/dev/null; then
    ok "the substituted ledger is the skeleton, not the live file"
else
    bad "queue.md in the artifact is not the committed skeleton"
fi
if [ "$(git -C "$ART" rev-list --count HEAD 2>/dev/null)" = 1 ]; then
    ok "the artifact starts at commit one — no platform history rides along"
else
    bad "the artifact carries more than one commit"
fi
if [ -e "$ART/.publish-artifact" ] && ! git -C "$ART" ls-files --error-unmatch .publish-artifact >/dev/null 2>&1; then
    ok "the target stamp exists on disk and is not in the product's first commit"
else
    bad "the target stamp is missing, or it reached the artifact's index"
fi

# --- idempotence, the claim that makes this a repeatable instrument ----------
run "$FIX" --to "$ART"
TREE2=$(git -C "$ART" rev-parse HEAD^{tree} 2>/dev/null || echo none)
if [ "$RC" = 0 ] && [ "$TREE1" = "$TREE2" ] && [ "$TREE1" != none ]; then
    ok "idempotent: two runs at one source sha, one exported tree hash ($TREE1)"
else
    bad "idempotence: run1 $TREE1 run2 $TREE2 (exit $RC)"
fi

# --- the destruction guard ---------------------------------------------------
FOREIGN="$WORK/foreign"
mkdir -p "$FOREIGN"
echo "somebody's work" >"$FOREIGN/precious.txt"
run "$FIX" --to "$FOREIGN"
if [ "$RC" = 2 ] && [ -f "$FOREIGN/precious.txt" ]; then
    ok "a target it cannot prove it wrote is refused, and nothing was deleted"
else
    bad "destruction guard: exit $RC, precious.txt $([ -f "$FOREIGN/precious.txt" ] && echo kept || echo GONE)"
fi

# --- the verification legs each fire ----------------------------------------
echo "# see ADR $ADR_GHOST for why" >>"$FIX/apps/example/models.py"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m ghost-adr)
run "$FIX" --to "$ART"
if [ "$RC" = 1 ] && grep -q "adr-census: ADR $ADR_GHOST" "$OUT"; then
    ok "adr-census fires: an id resolving nowhere is exit 1, id and citing file named"
else
    bad "adr-census: exit $RC, want 1 naming the ghost id"
fi
(cd "$FIX" && git checkout -q HEAD~1 -- apps/example/models.py && git -c user.name=t -c user.email=t@t commit -q -am undo)

echo "See $CY/$PLAN for the rationale." >>"$FIX/README.md"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m dangler)
run "$FIX" --to "$ART"
if [ "$RC" = 1 ] && grep -q "dangling-docs: $CY/$PLAN" "$OUT"; then
    ok "dangling-docs fires: a pointer into trimmed history is exit 1, named"
else
    bad "dangling-docs: exit $RC, want 1 naming the trimmed plan"
fi
(cd "$FIX" && git checkout -q HEAD~1 -- README.md && git -c user.name=t -c user.email=t@t commit -q -am undo)

# --- leg archaeology-census: the four classes fire, the allow-listed forms do not
# EVERY PLANT TOKEN IS ASSEMBLED, for the reason the fixture paths above are:
# this drive is a shipped file (R3), and `archaeology-census` reads the SHAPES
# below wherever they appear — including inside this script, sitting in the very
# artifact it helps publish. A literal here would make the guard red on its own
# author. Split in two, no pattern can join them; the fixture receives the
# joined string, which is the thing under test.
ARCH_N="N""347"
ARCH_RUNG="P""9-2"
ARCH_NARRATIVE="PROVE""-1"
ARCH_THIS="this ""rung"
ARCH_PRIVATE="Att""icus"
ARCH_NOQA="N""802"
# The platform's own deployment domain. Pattern 4 has denied this shape since
# the leg was born and NOTHING HAS EVER WATCHED IT FIRE — the loop planted the
# sibling-product half of the same alternation and no more, so the domain half
# was a deny-list entry taken on trust. A guard nobody has seen fire is a
# guard nobody can say is wired to anything.
ARCH_DOMAIN="pilecap"".dev"
# The template's FORMER name, in the TitleCase form the brand carried. Case is
# the whole discriminator: every surviving lowercase site is infrastructure
# identity the owner's ruling kept (the compose project, the `DJB_`/`djb_`
# prefixes, the Zitadel logins), so a case-SENSITIVE deny separates the brand
# that moved from the namespace that did not.
ARCH_BRAND="Django""Bootstrap"
# A deployment coordinate of the owner's real AWS account: the slug joined to
# an environment by `-` (IAM roles, S3 buckets, EC2 tags) or by `/` (the
# Secrets Manager prefix). The brand-form slug alone is legal and ships — it is
# the product name — so the COORDINATE shape is what the pattern names.
ARCH_COORD="pilecap""-staging"

for arch_case in \
    "finding-id:$ARCH_N" \
    "rung-token:$ARCH_RUNG" \
    "narrative:$ARCH_NARRATIVE" \
    "narrative:$ARCH_THIS" \
    "private-name:$ARCH_PRIVATE" \
    "private-name:$ARCH_DOMAIN" \
    "former-brand:$ARCH_BRAND" \
    "deploy-coordinate:$ARCH_COORD"; do
    arch_label=${arch_case%%:*}
    arch_token=${arch_case#*:}
    printf '# the reason it is shaped this way, as it was found in %s\n' "$arch_token" \
        >>"$FIX/apps/example/models.py"
    (cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m arch-plant)
    run "$FIX" --to "$ART"
    if [ "$RC" = 1 ] &&
        grep -qE "archaeology-census: apps/example/models\.py:[0-9]+  $arch_label" "$OUT" &&
        grep -qF "\"$arch_token\"" "$OUT"; then
        ok "archaeology-census fires on $arch_label — exit 1, file:line and the matched string"
    else
        bad "archaeology-census $arch_label: exit $RC, want 1 naming apps/example/models.py and \"$arch_token\""
    fi
    (cd "$FIX" && git checkout -q HEAD~1 -- apps/example/models.py &&
        git -c user.name=t -c user.email=t@t commit -q -am undo)
done

# The other half, and the half a deny-list is usually missing: the forms that
# LOOK like the patterns and are legitimate. A guard nobody has watched stay
# silent is a guard nobody can trust to be quiet about the right things.
{
    printf '\n## PROVE verdict\n\n'
    printf 'Stage 6 PROVE. Pilecap ships its own name. See house rule 7 and ADR %s.\n' "$ADR_REAL"
    # The two forms the NEW patterns are shaped to walk past, and the reason
    # each one is legal: the compose project name is the infrastructure
    # identity the owner's ruling kept (lowercase, so the case-sensitive
    # former-brand deny must not see it), and the identity-platform example
    # value carries the BRAND, which ships — only the coordinate shape that
    # joins that slug to an environment is denied.
    # ASSEMBLED for a second reason, and this one is not about self-reddening:
    # the lowercase survivors of the former name are a CLOSED enumeration that
    # a verifier matches against the artifact, and a literal here would add a
    # twentieth site to a list of nineteen. The fixture receives the joined
    # string, which is the thing under test; the drive's own source does not
    # grow a member of somebody else's census.
    printf 'The stack is `name: %s` and the example env sets ZITADEL_ORG_NAME=Pilecap.\n' \
        "django""bootstrap"
    printf '%s\n' "$MARKER"
} >>"$FIX/docs/runbooks/deploy.md"
printf 'def do_POST(self) -> None:  # noqa: %s - the linter code, not a finding id\n' "$ARCH_NOQA" \
    >>"$FIX/apps/example/models.py"
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m arch-allowed)
run "$FIX" --to "$ART"
# The leg PRINTS its own name on every run, so the assertion is about the
# VIOLATION lines and never about the leg's header — a grep for the leg's name
# alone would fail on a clean run, which is the shape of a case that can only
# ever be red.
if [ "$RC" = 0 ] && ! grep -q "VIOLATION  archaeology-census" "$OUT"; then
    ok "archaeology-census stays silent on the allow-listed forms (exit 0, no violation)"
else
    bad "archaeology-census reddened on an allow-listed form: exit $RC"
    grep "VIOLATION" "$OUT" | sed 's/^/         /'
fi
(cd "$FIX" && git checkout -q HEAD~1 -- docs/runbooks/deploy.md apps/example/models.py &&
    git -c user.name=t -c user.email=t@t commit -q -am undo)

# The secrets leg reads the ARTIFACT, so the plant goes in a SHIPPED file and
# the baseline is deliberately not refreshed — that is the whole shape of the
# leg: the published tree is what a stranger clones, and history hid this.
printf '%s KEY-----\nMIIEowIBAAKCAQEAx\n' "-----BEGIN RSA PRIVATE" >>"$FIX/config/settings.py" # pragma: allowlist secret
(cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m plant)
run "$FIX" --to "$ART"
if [ "$RC" = 1 ] && grep -q "VIOLATION  secrets" "$OUT"; then
    ok "the full-tree secret scan runs against the ARTIFACT and reddens on a plant"
else
    bad "artifact secret scan: exit $RC, want 1"
fi
(cd "$FIX" && git checkout -q HEAD~1 -- config/settings.py && git -c user.name=t -c user.email=t@t commit -q -am undo)

run "$FIX" --to "$ART"
[ "$RC" = 0 ] && ok "and the plants restore: the fixture is clean again (exit 0)" ||
    bad "after restoring every plant the fixture is still exit $RC"

# =============================================================================
# RELEASE MODE — the child-commit publish, driven against a SCRATCH published
# repository this drive builds and throws away.
#
# NOTHING HERE GOES NEAR A REAL PUBLISHED REPOSITORY, and that is a property of
# the drive rather than a promise about the operator: `$PUB` below is a
# directory under `mktemp -d`, created by this script's own default publish and
# then tagged, which is exactly the shape the real one has (a root cut once,
# releases as children after that). The reason to insist is that this is the one
# mode whose mistakes cannot be taken back — a release commit a consumer has
# merged is in their history forever — so THE PUBLISH must not be the first time
# any of it runs.
#
# THE FIXTURE'S VERSIONS ARE 0.x ON PURPOSE. They are the fixture's own numbers
# and resemble nothing in this repository's TEMPLATE_VERSION, so a reader can
# never mistake a line of this drive's output for a statement about the real
# template's releases.
# =============================================================================
PUB="$WORK/published"
CONS="$WORK/consumer"

gitq() { # gitq <dir> <args...> — git with a fixture identity and no signing
    local d=$1
    shift
    git -C "$d" -c user.name=t -c user.email=t@t \
        -c commit.gpgsign=false -c tag.gpgsign=false "$@"
}
# --- leg changelog-flags: the release section's flag claims ------------------
# DRIVEN AT THE BODY, NOT THROUGH THE GATE, for the reason every drive in this
# tree states: the body is `docs_changelog_flags` in `scripts/docs_legs.sh`,
# publish.sh is one of its callers, and a case that can plant a CHANGELOG and
# read the finding line is a case that can say WHICH span was judged. The
# WIRING — that release mode calls it at all — is its own case further down,
# beside the other release cases, because that is a property of publish.sh.
. "$ROOT/scripts/gate_refuse.sh"
. "$ROOT/scripts/docs_legs.sh"
CLR="$WORK/clroot"
clroot() { # clroot <changelog-section-body>
    rm -rf "$CLR"
    mkdir -p "$CLR/scripts" "$CLR/apps/thing/management/commands"
    printf '# a gate\n# the flags it really has: --loop --fast\n' >"$CLR/scripts/gate.sh"
    printf '"""a command"""\n# it really takes --email\n' >"$CLR/apps/thing/management/commands/dothing.py"
    {
        printf '# Changelog\n\n## [9.9.9]\n\n'
        printf '%s\n' "$1"
        printf '\n## [9.9.8]\n\n- and this section is HISTORY: `./scripts/gate.sh --gone`\n'
    } >"$CLR/CHANGELOG.md"
}
clflags() { # clflags <version> ; output to $CLOUT, status in $CLRC
    CLOUT="$WORK/clflags.out"
    set +e
    docs_changelog_flags "$CLR" "$1" >"$CLOUT" 2>"$WORK/clflags.err"
    CLRC=$?
    set -e
}

# case_a_flag_no_script_declares_reds
clroot '- run `./scripts/gate.sh --nosuchflag` at every boundary.'
clflags 9.9.9
if [ "$CLRC" = 1 ] && grep -q 'changelog-flags: --nosuchflag is not a literal in scripts/gate.sh' "$CLOUT"; then
    ok "case_a_flag_no_script_declares_reds: a flag the named script does not carry is exit 1, flag and script named"
else
    bad "case_a_flag_no_script_declares_reds: exit $CLRC, want 1. Output:
$(sed 's/^/             /' "$CLOUT")"
fi

# case_an_unscripted_span_is_counted_not_judged
# THE MEASURED SHAPE, not an invented one: a subcommand and a flag in one span
# with the script named only in the PROSE around it. The prose makes the script
# obvious to a human and this leg still refuses to infer it, because inferring
# is naming a cause it has not proven. It must be COUNTED, and the count must
# be printed, so the size of what was not judged is visible.
clroot '- `./scripts/gate.sh` is the gate; the recipe is printed by `gate --nosuchflag` first.'
clflags 9.9.9
if [ "$CLRC" = 0 ] && [ "$DOCS_CHANGELOG_UNRESOLVED" = 1 ] && [ "$DOCS_CHANGELOG_CLAIMS" = 0 ]; then
    ok "case_an_unscripted_span_is_counted_not_judged: a flag span naming no script is counted (1), judged never, exit 0"
else
    bad "case_an_unscripted_span_is_counted_not_judged: exit $CLRC, claims $DOCS_CHANGELOG_CLAIMS, unresolved $DOCS_CHANGELOG_UNRESOLVED; want 0, 0, 1. Output:
$(sed 's/^/             /' "$CLOUT")"
fi

# case_a_declared_flag_is_green — both resolvers, in one section
clroot '- `./scripts/gate.sh --loop` at every boundary, and `manage.py dothing --email <a>`.'
clflags 9.9.9
if [ "$CLRC" = 0 ] && [ "$DOCS_CHANGELOG_CLAIMS" = 2 ] && [ ! -s "$CLOUT" ]; then
    ok "case_a_declared_flag_is_green: a script flag and a command flag that both exist are exit 0, 2 claims, no finding"
else
    bad "case_a_declared_flag_is_green: exit $CLRC, claims $DOCS_CHANGELOG_CLAIMS. Output:
$(sed 's/^/             /' "$CLOUT")"
fi

# OLDER SECTIONS ARE HISTORY AND ARE NOT READ. Every fixture above carries a
# `## [9.9.8]` section whose span names a flag `scripts/gate.sh` does not have.
# It has been silent in all three cases; this asserts that rather than leaving
# it as a thing nobody looked at — and it is the property that keeps an
# instrument from ever being the reason a shipped release note is rewritten.
clroot '- nothing to say.'
clflags 9.9.9
if [ "$CLRC" = 0 ] && ! grep -q -- '--gone' "$CLOUT"; then
    ok "an older section's stale flag claim is NOT read — the leg judges the section being released and no other"
else
    bad "the leg read past its own section: exit $CLRC. Output:
$(sed 's/^/             /' "$CLOUT")"
fi

# THE TWO COULD-NOT-LOOKS. An instrument that cannot look says so.
clflags 4.4.4
if [ "$CLRC" = 2 ] && grep -q 'has no `## \[4.4.4\]` section' "$WORK/clflags.err"; then
    ok "a version with no section in the CHANGELOG is exit 2 — could-not-look, named"
else
    bad "absent section: exit $CLRC, want 2. stderr:
$(sed 's/^/             /' "$WORK/clflags.err")"
fi

clroot '- run `./scripts/absent.sh --whatever` once.'
clflags 9.9.9
if [ "$CLRC" = 2 ] && grep -q 'names scripts/absent.sh, which is not in' "$WORK/clflags.err"; then
    ok "a claim naming a script that is not in the tree is exit 2 — the leg cannot read what the claim is about"
else
    bad "absent script: exit $CLRC, want 2. stderr:
$(sed 's/^/             /' "$WORK/clflags.err")"
fi

clroot '- an unbalanced ` span that never closes.'
clflags 9.9.9
if [ "$CLRC" = 2 ] && grep -q 'ODD number of' "$WORK/clflags.err"; then
    ok "a section with unbalanced backticks is exit 2 — every span after the break is mis-paired"
else
    bad "unbalanced backticks: exit $CLRC, want 2. stderr:
$(sed 's/^/             /' "$WORK/clflags.err")"
fi
rm -rf "$CLR"

fixture_release() { # fixture_release <version> [with-section|with-bad-flag]
    printf '%s\n' "$1" >"$FIX/TEMPLATE_VERSION"
    if [ "${2:-}" = with-section ]; then
        printf '# changelog\n\n## [%s]\n\n- the fixture drop\n' "$1" >"$FIX/CHANGELOG.md"
    elif [ "${2:-}" = with-bad-flag ]; then
        # A SECTION THAT EXISTS AND LIES. The `changelog` leg above is green on
        # it — there IS a section — and only `changelog-flags` can see that the
        # thing it tells a consumer to type does not exist in what ships.
        printf '# changelog\n\n## [%s]\n\n- the fixture drop: `./scripts/check.sh --nosuchflag`\n' \
            "$1" >"$FIX/CHANGELOG.md"
    else
        printf '# changelog\n' >"$FIX/CHANGELOG.md"
    fi
    (cd "$FIX" && git add -A && git -c user.name=t -c user.email=t@t commit -q -m "v$1")
}
pub_commits() { git -C "$PUB" rev-list --count HEAD 2>/dev/null || echo none; }
printed_tree() { awk '/^   tree +[0-9a-f]{40}$/ {print $2; exit}' "$OUT"; }

echo ""
echo "-- release mode (scratch published repository)"

# The published repository as it really is: a root cut once, then tagged. Every
# case below builds on this and nothing below re-cuts it — which is the point.
run "$FIX" --to "$PUB"
if [ "$RC" = 0 ]; then
    gitq "$PUB" tag -a v0.1.0 -m v0.1.0 HEAD
    ok "the scratch published repository exists at v0.1.0 (one root commit, tagged)"
else
    bad "the scratch published repository would not build: exit $RC"
    sed 's/^/         /' "$OUT"
fi
PUB_ROOT=$(git -C "$PUB" rev-parse HEAD)

# --- criterion 3: the root re-cut door is shut -------------------------------
run "$FIX" --to "$PUB"
if [ "$RC" = 2 ] && grep -q "ROOT RE-CUT DOOR IS CLOSED" "$OUT" &&
    [ "$(pub_commits)" = 1 ] && git -C "$PUB" rev-parse -q --verify refs/tags/v0.1.0 >/dev/null; then
    ok "the root re-cut is REFUSED against a repository carrying release tags, untouched"
else
    bad "root re-cut door: exit $RC, commits $(pub_commits), want 2 and 1"
fi

# --- the CHANGELOG contract: exit 1, and nothing is committed ----------------
fixture_release 0.2.0
run "$FIX" --release "$PUB" --to "$ART"
if [ "$RC" = 1 ] && grep -q "VIOLATION  changelog" "$OUT" &&
    [ "$(pub_commits)" = 1 ] && ! git -C "$PUB" rev-parse -q --verify refs/tags/v0.2.0 >/dev/null; then
    ok "a release whose CHANGELOG has no section for the version is exit 1 — no commit, no tag"
else
    bad "changelog leg: exit $RC, commits $(pub_commits), want 1 and 1"
fi

# --- changelog-flags IS WIRED INTO RELEASE MODE ------------------------------
# The body's own cases are above; this is the only thing they cannot say — that
# `publish.sh --release` calls it at all, over the ARTIFACT, after `changelog`,
# and that its finding is a VIOLATION (exit 1, nothing committed) rather than a
# printed remark. Without this case the leg could be deleted from publish.sh
# and every case above would still be green.
fixture_release 0.2.0 with-bad-flag
run "$FIX" --release "$PUB" --to "$ART"
if [ "$RC" = 1 ] && grep -q "VIOLATION  changelog-flags: --nosuchflag is not a literal in scripts/check.sh" "$OUT" &&
    grep -q "ok — ## \[0.2.0\] is in the published CHANGELOG.md" "$OUT" &&
    [ "$(pub_commits)" = 1 ] && ! git -C "$PUB" rev-parse -q --verify refs/tags/v0.2.0 >/dev/null; then
    ok "changelog-flags fires in release mode: the section is there, its flag is not — exit 1, no commit, no tag"
else
    bad "changelog-flags wiring: exit $RC, commits $(pub_commits), want 1 and 1. Transcript:
$(grep -E 'changelog' "$OUT" | sed 's/^/             /')"
fi

# --- the happy path, and the equality that is the whole claim ----------------
fixture_release 0.2.0 with-section
run "$FIX" --release "$PUB" --to "$ART"
REL_TREE=$(printed_tree)
NEW_TIP=$(git -C "$PUB" rev-parse HEAD 2>/dev/null || echo none)
if [ "$RC" = 0 ] && [ "$(pub_commits)" = 2 ]; then
    ok "the release publishes: exit 0, the published repository gained exactly one commit"
else
    bad "release happy path: exit $RC, commits $(pub_commits), want 0 and 2"
    sed 's/^/         /' "$OUT"
fi
if [ "$(git -C "$PUB" rev-parse 'HEAD^' 2>/dev/null)" = "$PUB_ROOT" ]; then
    ok "the release commit is a CHILD of the published tip, not a new root"
else
    bad "the release commit's parent is not the previous tip"
fi
if [ "$(git -C "$PUB" rev-list -n 1 v0.2.0 2>/dev/null)" = "$NEW_TIP" ]; then
    ok "the release is tagged v<TEMPLATE_VERSION>, on the release commit"
else
    bad "v0.2.0 does not point at the release commit"
fi
# The criterion the whole mode turns on: the committed tree IS the tree the
# census verified and the run printed — read back off the commit, not believed.
if [ -n "$REL_TREE" ] && [ "$(git -C "$PUB" rev-parse 'HEAD^{tree}' 2>/dev/null)" = "$REL_TREE" ]; then
    ok "the release commit's tree IS the census-verified tree ($REL_TREE)"
else
    bad "tree equality: printed $REL_TREE, committed $(git -C "$PUB" rev-parse 'HEAD^{tree}' 2>/dev/null)"
fi
if [ -z "$(git -C "$PUB" status --porcelain)" ] &&
    [ "$(tr -d '[:space:]' <"$PUB/TEMPLATE_VERSION")" = 0.2.0 ]; then
    ok "the published working tree is clean and holds the released content"
else
    bad "the published tree is dirty, or does not hold the release"
fi

# --- refusal: the version is already out ------------------------------------
run "$FIX" --release "$PUB" --to "$ART"
if [ "$RC" = 2 ] && grep -q "v0.2.0 already exists" "$OUT" && [ "$(pub_commits)" = 2 ]; then
    ok "re-releasing a version already tagged is exit 2 — a released tree never changes"
else
    bad "tag-exists refusal: exit $RC, commits $(pub_commits), want 2 and 2"
fi

# --- refusal: the published tip is not the last release ----------------------
echo "a hand commit somebody made on the published branch" >"$PUB/README.md"
gitq "$PUB" add README.md
gitq "$PUB" commit -q -m "by hand"
HAND_TIP=$(git -C "$PUB" rev-parse HEAD)
fixture_release 0.3.0 with-section
run "$FIX" --release "$PUB" --to "$ART"
if [ "$RC" = 2 ] && grep -q "tip is NOT its last release" "$OUT" &&
    grep -q "$HAND_TIP" "$OUT" && grep -q "$NEW_TIP" "$OUT"; then
    ok "a published tip that is not the last release is exit 2, naming BOTH shas"
else
    bad "tip-mismatch refusal: exit $RC, want 2 naming $HAND_TIP and $NEW_TIP"
fi
# Fixture housekeeping, and REPORTED rather than assumed: under `set -e` a bare
# restore that cannot find its tag kills the drive with git's own exit 128 and
# takes the `passed · failed` count with it, which is how a red run stops being
# readable exactly when somebody needs to read it. (Found by planting a wrong
# tree into the release commit and watching this line, not the guard, end the
# run.)
gitq "$PUB" reset -q --hard v0.2.0 || bad "could not restore the published fixture to v0.2.0"

# --- refusal: the published tree is dirty ------------------------------------
echo "uncommitted work in the published clone" >"$PUB/SOMEBODYS-WORK.txt"
run "$FIX" --release "$PUB" --to "$ART"
if [ "$RC" = 2 ] && grep -q "release target's working tree is dirty" "$OUT" &&
    [ -f "$PUB/SOMEBODYS-WORK.txt" ]; then
    ok "a dirty published clone is exit 2, and the uncommitted work is still there"
else
    bad "dirty-target refusal: exit $RC, want 2 with the file kept"
fi
rm -f "$PUB/SOMEBODYS-WORK.txt"

# --- refusal: the target is not a repository at all --------------------------
run "$FIX" --release "$WORK/no-such-published-dir"
[ "$RC" = 2 ] && ok "--release naming no directory is exit 2" ||
    bad "--release absent dir: exit $RC, want 2"

run "$FIX" --census --release "$PUB"
[ "$RC" = 2 ] && ok "--census with --release is exit 2 — one exports nothing, the other commits" ||
    bad "--census --release: exit $RC, want 2"

# --- the second release, which is what makes the next case meaningful --------
run "$FIX" --release "$PUB" --to "$ART"
if [ "$RC" = 0 ] && [ "$(pub_commits)" = 3 ] &&
    [ "$(git -C "$PUB" rev-list -n 1 v0.3.0 2>/dev/null)" = "$(git -C "$PUB" rev-parse HEAD)" ]; then
    ok "a second release chains onto the first: three commits, v0.3.0 on the tip"
else
    bad "second release: exit $RC, commits $(pub_commits), want 0 and 3"
    sed 's/^/         /' "$OUT"
fi

# --- THE CUMULATIVE MERGE: a consumer skips an intermediate release ----------
# The property the owner's ruling is FOR, and the one THE PUBLISH must not be
# the first test of: a product sitting on v0.1.0, carrying a local patch,
# merges v0.3.0 ONCE and lands on the released tree — v0.2.0 is in the chain and
# is never merged separately, which is what "skip intermediates for free" means.
if git clone -q "$PUB" "$CONS" 2>/dev/null &&
    gitq "$CONS" reset -q --hard v0.1.0; then
    printf '# a local patch this product carries\n' >"$CONS/PATCHED.md"
    gitq "$CONS" add PATCHED.md
    gitq "$CONS" commit -q -m "our own change"
    set +e
    gitq "$CONS" merge -q --no-edit v0.3.0 >"$WORK/merge.out" 2>&1
    MERGE_RC=$?
    set -e
    DRIFT=$(git -C "$CONS" diff --name-only v0.3.0 HEAD)
    MERGES=$(git -C "$CONS" rev-list --count --merges HEAD)
    if [ "$MERGE_RC" = 0 ] && [ "$DRIFT" = "PATCHED.md" ] && [ "$MERGES" = 1 ] &&
        [ "$(tr -d '[:space:]' <"$CONS/TEMPLATE_VERSION")" = 0.3.0 ]; then
        ok "cumulative merge: v0.1.0 + a local patch merges v0.3.0 ONCE, keeps the patch, lands on the released tree"
    else
        bad "cumulative merge: exit $MERGE_RC, merges $MERGES, drift '$DRIFT'"
        sed 's/^/         /' "$WORK/merge.out"
    fi
else
    bad "the consumer clone would not build at v0.1.0 — could not drive the cumulative merge"
fi

echo ""
echo "== $PASS passed · $FAIL failed"
# Said out loud, because bash hands the EXIT trap a status of 0 when `set -u`
# kills the shell: without this the epilogue cannot tell a run that finished
# from one that died before reaching this line.
drive_finished
[ "$FAIL" -eq 0 ] || exit 1
exit 0
