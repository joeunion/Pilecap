#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/bash_only.sh" || exit 2
# review_pack.sh [<ref>] — per-rule diff slices for a reviewer.
#
# The gate is deterministic and has no LLM leg; model judgement lives in the
# loop's review stages, and this is what makes them cheap: instead of reading a
# whole diff, the reviewer gets the slices each house rule cares about —
# touched services with their decorators, new or changed routes with the tests
# that name them, migration operations, new event names, and every override
# comment the change adds. Plain text on stdout, sections headed by rule id.
#
# It is an AID, NOT a gate leg: it exits 0 whenever it can read the diff, and
# nothing consumes its exit code as a verdict.
#
# Default ref: the merge-base with main (or HEAD on main itself).
set -euo pipefail
# shellcheck source=scripts/gate_refuse.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/gate_refuse.sh" || exit 2
cd "$(dirname "$0")/.."

REF=${1:-}
if [ -z "$REF" ]; then
    BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)
    if [ "$BRANCH" != "main" ] && git rev-parse --verify -q main >/dev/null; then
        REF=$(git merge-base HEAD main)
    else
        REF=HEAD
    fi
fi

CHANGED=$(changed_between "$REF" - 'apps/**' 'config/**' || true)
UNTRACKED=$(git ls-files --others --exclude-standard -- 'apps/**' 'config/**' || true)
ALL_CHANGED=$(printf '%s\n%s\n' "$CHANGED" "$UNTRACKED" | sed '/^$/d' | sort -u)

section() { printf '\n================ %s ================\n' "$1"; }
diff_of() {
    # Unified diff for one file, whether tracked or brand new.
    if git ls-files --error-unmatch "$1" >/dev/null 2>&1; then
        git diff "$REF" -- "$1"
    else
        git diff --no-index /dev/null "$1" || true
    fi
}

echo "review pack — diff vs $REF ($(git rev-parse --short "$REF" 2>/dev/null || echo "$REF"))"
echo "changed files under apps/ and config/:"
if [ -z "$ALL_CHANGED" ]; then
    echo "  (none — nothing for a reviewer here)"
    exit 0
fi
printf '  %s\n' $ALL_CHANGED

# --- rules 10/12/13: touched services, with their decorators -----------------
section "rules 10 · 12 · 13 — services touched (decorators visible; look for @service, authz.require, tenant=)"
FOUND=""
for f in $ALL_CHANGED; do
    case "$f" in
    apps/*/services.py)
        FOUND=1
        diff_of "$f"
        ;;
    esac
done
[ -n "$FOUND" ] || echo "(no services.py touched)"

# --- rule 3/5: routes, and the tests that name them --------------------------
section "rules 3 · 5 — routes added or changed, and the tests naming their url_name"
FOUND=""
for f in $ALL_CHANGED; do
    case "$f" in
    apps/*/api.py | apps/*/mcp.py)
        FOUND=1
        diff_of "$f"
        APP=$(echo "$f" | cut -d/ -f2)
        for name in $(diff_of "$f" | grep -E '^\+' | grep -oE 'url_name="[^"]+"' | cut -d'"' -f2 | sort -u); do
            echo "--- tests naming url_name '$name' in apps/$APP/tests:"
            grep -rn "$name" "apps/$APP/tests" 2>/dev/null || echo "    NONE — the diff layer blocks this"
        done
        ;;
    esac
done
[ -n "$FOUND" ] || echo "(no api.py/mcp.py touched)"

# --- rules 6/22: migration operations ----------------------------------------
section "rules 6 · 22 — migration operations in the change"
FOUND=""
for f in $ALL_CHANGED; do
    case "$f" in
    apps/*/migrations/*.py)
        FOUND=1
        echo "--- $f"
        diff_of "$f"
        ;;
    apps/*/migrations/max_migration.txt)
        FOUND=1
        echo "--- $f"
        diff_of "$f"
        ;;
    esac
done
[ -n "$FOUND" ] || echo "(no migrations touched)"

# --- rule 16: new event names --------------------------------------------------
section "rule 16 — event names added (grammar: <app>.<noun>.<past-verb>, declared in events.py)"
FOUND=""
for f in $ALL_CHANGED; do
    case "$f" in
    apps/*/events.py)
        FOUND=1
        echo "--- $f"
        diff_of "$f" | grep -E '^\+' | grep -vE '^\+\+\+' || true
        ;;
    esac
done
[ -n "$FOUND" ] || echo "(no events.py touched)"

# --- rule 17: schema contract changes -----------------------------------------
section "rule 17 — Out-schema changes (a removed/re-typed field is breaking; needs a v2 router)"
FOUND=""
for f in $ALL_CHANGED; do
    case "$f" in
    apps/*/schemas.py)
        FOUND=1
        diff_of "$f"
        ;;
    esac
done
[ -n "$FOUND" ] || echo "(no schemas.py touched)"

# --- overrides added -----------------------------------------------------------
section "overrides added in this change (# rule-<id>: — every one is a judgement to review)"
FOUND=""
for f in $ALL_CHANGED; do
    HITS=$(diff_of "$f" | grep -E '^\+' | grep -nE '# rule-[0-9]+' || true)
    if [ -n "$HITS" ]; then
        FOUND=1
        echo "--- $f"
        echo "$HITS"
    fi
done
[ -n "$FOUND" ] || echo "(none added)"

echo
echo "end of review pack — the declared blind spots each rule leaves to review are"
echo "the does_not_cover fields in quality/rules.yaml."
