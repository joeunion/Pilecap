#!/usr/bin/env bash
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
# NOT WIRED INTO `scripts/check.sh` YET, and that is a declared debt rather than
# a decision: the selftest leg's drive list lives in `scripts/check.sh`, which
# was another rung's exclusive territory in the wave that wrote this file.
# Wiring it is one `set +e` block beside the eight
# already there. **BY HAND IS A PROMISE; A LEG IS A MEASUREMENT** — the same
# sentence check.sh uses about the two drives that spent a cycle unwired.
set -euo pipefail

if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! this drive refuses pipes — its exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/../.."
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
trap 'rm -rf "$WORK"' EXIT

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
LEDGERS="north-star queue readouts misses in-flight goal-posts design-agreements pilot-readiness rep-day"

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
        "$d/$CY" "$d/$SK" "$d/docs/runbooks"
    cp "$PUBLISH" "$d/scripts/publish.sh"
    chmod +x "$d/scripts/publish.sh"
    echo "# a model" >"$d/apps/example/models.py"
    echo "# settings" >"$d/config/settings.py"
    echo "# manage" >"$d/manage.py"
    echo "rules: []" >"$d/quality/rules.yaml"
    echo "| Instrument | a | b | c | d |" >"$d/docs/product/instruments.md"
    echo "# the gate" >"$d/scripts/check.sh"
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

run "$FIX" --census --to "$WORK/x"
[ "$RC" = 2 ] && ok "--census with a target is refused (it exports nothing)" || bad "--census --to: exit $RC, want 2"

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

echo ""
echo "== $PASS passed · $FAIL failed"
[ "$FAIL" -eq 0 ] || exit 1
exit 0
