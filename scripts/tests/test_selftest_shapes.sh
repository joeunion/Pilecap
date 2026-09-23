#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made: a wrong shell here
# does not crash, it ANSWERS, and the answer looks like the tree's fault.
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
# drives: quality/ frontend/src scripts/divergence_census.sh scripts/archaeology_lib.sh docs/product/architecture.md docs/product/build-contract.md docs/product/api-editorial-standard.md TEMPLATE_VERSION pyproject.toml uv.lock
# cites: apps/accounts/tests scripts/local/template-base scripts/check.sh scripts/tests/test_divergence_census.sh scripts/tests/test_selftest_leg.sh docs/product/instruments.md
# The engine's self-test, judged on a CONSUMER'S shape rather than this one.
#
# Exit: 0 every case held · 1 a case did not hold · 2 COULD NOT LOOK (no git,
#       no uv, a world that would not build, an interpreter that would not
#       start). 2 outranks a pass here for the reason it does everywhere.
#
# WHY IT EXISTS. `python -m quality.gate --selftest` plants every rule's forms
# into the tree it runs on, and the only tree this repository ever ran it on is
# the TEMPLATE'S own — a world too small to falsify "this canary is live on a
# product". Twice a consumer folded a release and found the next layer at
# their own bank: a form planted `mode: create` onto a file every Next product
# has (`frontend/src/app/page.tsx`), and a control that fires the moment a base
# is declared through the `template` remote. Both red the engine's self-test,
# which the selftest leg carries, so their full gate exited 2 by construction.
# This drive is the first bank-time measurement on the other shape.
#
# IT BUILDS ITS OWN PRODUCT. One `git clone --shared --no-hardlinks` of this
# checkout at HEAD (the drawer-world move `test_selftest_leg.sh` makes, for the
# same reason: the engine's ROOT is derived from its own file, so pointing it at
# another tree means running another copy of it), under `mktemp -d`, then two
# worlds in order on that one clone:
#
#   W-C-remote  the consumer's measured shape: the base declared ONLY through a
#               `template` remote carrying the tag v<TEMPLATE_VERSION> (the
#               census's third reader), no scripts/local/template-base, a real
#               frontend/src/app/page.tsx, and one product-owned edit named as a
#               divergence so the world's census reads unnamed=0. Committed.
#   W-C-file    the same, plus scripts/local/template-base holding the
#               pre-product sha — the census's second reader, which outranks
#               the remote. Committed on top.
#
# In each it runs the NARROWED self-test, `--selftest --rule 51 --rule 60`,
# stdout to a file, and asserts the judged-shape line, both rule lines, the
# absence of every refusal class and of the literal `$(`. The recorded
# populations are read from quality/rules.yaml in the world, never typed here.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * IT MEASURES HEAD, NOT THE WORKING TREE. The world is a clone; an
#     uncommitted edit in this checkout is invisible to it.
#   * TWO RULES, NOT SIXTY-ONE. The other rules' forms are not judged on this
#     shape; widening the narrowed run is priced by the durations this drive
#     prints, and a world that reds on a rule nobody has fixed blocks the bank.
#   * TWO BASE READERS, NOT THREE. A base typed in DJB_TEMPLATE_BASE is the
#     same shape as the remote to the self-test and is not separately driven.
#   * ONE PRODUCT FILE. The world carries page.tsx and nothing else a Next
#     product plausibly has (a theme.css, a panel.tsx, frontend/app/env.ts),
#     so rules 50 and 53's plants are not asked whether they collide.
#   * THE WORLD IS TRANSCRIBED from the consumer's transcript; their tree was
#     not read.
set -euo pipefail

if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! this drive refuses pipes — its exit status is the verdict" >&2
    exit 2
fi

cd "$(dirname "$0")/../.."

# The preamble, before anything asks git a question: this drive builds a
# throwaway clone and talks to it with `git -C "$WORLD" …`, which writes into
# the REAL repository instead whenever it inherits an absolute `GIT_DIR` —
# which it does when it is run from the pre-push hook.
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_selftest_shapes: scripts/tests/drive_preamble.sh is not in this" >&2
    echo "   tree. It carries the neutralisation that keeps the world clone below" >&2
    echo "   out of the real repository. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
# AFTER the source, never before: the preamble assigns this variable 0 itself.
DRIVE_OPTED_IN_TO_FINISH=1

CASES="case_the_remote_declared_base_is_green_on_rules_51_and_60 case_the_file_declared_base_is_green_on_rules_51_and_60"
case "${1:-}" in
--list)
    for c in $CASES; do printf '%s\n' "$c"; done
    exit 0
    ;;
"") ;;
*)
    echo "!! test_selftest_shapes: unknown argument '$1' (takes --list or nothing)" >&2
    exit 2
    ;;
esac

ROOT=$(pwd -P)
command -v git >/dev/null 2>&1 || drive_cannot_look "no git on PATH"
command -v uv >/dev/null 2>&1 || drive_cannot_look "no uv on PATH — the engine runs under \`uv run\`"
# The census reads its base from the environment first; an inherited value
# would make every world here the DJB_TEMPLATE_BASE shape.
unset DJB_TEMPLATE_BASE

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-selftest-shapes.XXXXXX") || exit 2
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'
WORLD="$WORK/world"
UPSTREAM="$WORK/upstream"
drive_require_scratch WORLD "$WORLD"
drive_require_scratch UPSTREAM "$UPSTREAM"

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
now() { date +%s; }

# --- the world ---------------------------------------------------------------
T0=$(now)
git clone --quiet --shared --no-hardlinks "$ROOT" "$WORLD" >/dev/null 2>&1 ||
    drive_cannot_look "could not clone this checkout into $WORLD"
git -C "$WORLD" config user.email consumer@example.com
git -C "$WORLD" config user.name Consumer
PRE=$(git -C "$WORLD" rev-parse HEAD) || drive_cannot_look "the clone has no HEAD"
VERSION=$(tr -d '[:space:]' <"$WORLD/TEMPLATE_VERSION" 2>/dev/null || true)
case "$VERSION" in
[0-9]*.[0-9]*.[0-9]*) ;;
*) drive_cannot_look "TEMPLATE_VERSION does not read as <major>.<minor>.<patch>: '$VERSION'" ;;
esac
# The world's first `uv run` provisions its venv and says so on stderr; warmed
# here so every capture below is the engine's answer and nothing else.
(cd "$WORLD" && uv run python -c 'pass') >"$WORK/warm.log" 2>&1 || {
    sed 's/^/         /' "$WORK/warm.log" >&2
    drive_cannot_look "the clone's interpreter would not start — \`uv run\` failed in $WORLD"
}

# THE RECORDED POPULATIONS, read from the plan the world carries — a drive that
# typed "5/5" would pass the day a form was deleted along with its floor.
FLOORS="$WORK/floors.txt"
(cd "$WORLD" && uv run python - >"$FLOORS" 2>&1) <<'PY' || drive_cannot_look "quality/rules.yaml's selftest floors for rules 51 and 60 would not read"
import yaml

rules = {str(r["id"]): r for r in yaml.safe_load(open("quality/rules.yaml"))["rules"]}
for rid in ("51", "60"):
    f = rules[rid]["selftest_floor"]
    print(rid, rules[rid]["name"], int(f["canaries"]), int(f["negatives"]))
PY
read -r _ NAME51 CAN51 NEG51 < <(awk '$1 == "51"' "$FLOORS")
read -r _ NAME60 CAN60 NEG60 < <(awk '$1 == "60"' "$FLOORS")
[ -n "${NEG51:-}" ] && [ -n "${NEG60:-}" ] || drive_cannot_look "the floors file named no rule 51 or 60: $(cat "$FLOORS")"

# W-C-remote: the base is declared ONLY through the `template` remote.
git clone --quiet --shared --no-hardlinks "$WORLD" "$UPSTREAM" >/dev/null 2>&1 ||
    drive_cannot_look "could not clone the upstream the 'template' remote names"
git -C "$UPSTREAM" -c user.email=template@example.com -c user.name=Template \
    tag -a "v$VERSION" -m base "$PRE" || drive_cannot_look "could not tag v$VERSION in the upstream"
git -C "$WORLD" remote add template "$UPSTREAM"
git -C "$WORLD" fetch -q template --tags || drive_cannot_look "could not fetch the template remote's tags"
[ ! -e "$WORLD/scripts/local/template-base" ] || drive_cannot_look "the clone already declares scripts/local/template-base — the remote world must declare its base through the remote alone"
mkdir -p "$WORLD/frontend/src/app"
[ ! -e "$WORLD/frontend/src/app/page.tsx" ] || drive_cannot_look "this checkout already has frontend/src/app/page.tsx — the world plants its own"
# A LEGAL Next root page: `app` reaching `api` is the one door rule 51 opens,
# so the world's baseline gains no rule-51 finding of its own.
cat >"$WORLD/frontend/src/app/page.tsx" <<'TSX'
import { redirect } from "next/navigation";

import { listOrganizations } from "@/api/client";

export default function RootPage(): never {
    void listOrganizations;
    redirect("/welcome");
}
TSX
# One product-owned edit to a template-owned directory, NAMED as a divergence,
# so the world's own census reads unnamed=0 and rule 60's baseline is clean.
cat >"$WORLD/apps/accounts/tests/test_door_pair_parity.py" <<'PY'
"""The consumer's (rest, mcp) parity test for accounts — the debt, paid."""

DOOR_PAIR = ("rest", "mcp")


def test_the_pair_is_claimed() -> None:
    assert DOOR_PAIR == ("rest", "mcp")
PY
printf '\ndivergence: apps/accounts/tests/test_door_pair_parity.py — pays the (rest, mcp) debt\n' \
    >>"$WORLD/docs/product/architecture.md"
git -C "$WORLD" add -- frontend/src/app/page.tsx apps/accounts/tests/test_door_pair_parity.py docs/product/architecture.md
git -C "$WORLD" commit -q -m "consumer: the product's own tree (W-C-remote)" ||
    drive_cannot_look "could not commit the remote world"
T1=$(now)
echo "   world: a clone of HEAD $(git -C "$ROOT" rev-parse --short HEAD) with the 'template' remote at v$VERSION, built in $((T1 - T0))s"

# --- the cases ---------------------------------------------------------------
OUT=""
RC=0
narrowed() { # narrowed <label> — the engine's narrowed self-test in the world, to a file
    OUT="$WORK/selftest-$1.log"
    local t
    t=$(now)
    set +e
    (cd "$WORLD" && uv run python -m quality.gate --selftest --rule 51 --rule 60) >"$OUT" 2>&1
    RC=$?
    set -e
    echo "   $1: quality.gate --selftest --rule 51 --rule 60 — exit $RC ($(($(now) - t))s)"
}
has_line() { grep -qxF -- "$1" "$OUT"; }
common_asserts() { # common_asserts <label> <judged-shape line>
    local label=$1 shape=$2 refusals
    if [ "$RC" = 0 ]; then ok "$label: the narrowed self-test exits 0"; else bad "$label: the narrowed self-test exited $RC, want 0"; fi
    if has_line "$shape"; then ok "$label: judged shape — '$shape'"; else bad "$label: no line '$shape'"; fi
    if has_line "selftest: narrowed to rule(s) 51, 60 — the legs, the seam, the budget canary and the censuses were not run; this is not the gate's verdict"; then
        ok "$label: the run says it is narrowed and not the gate's verdict"
    else
        bad "$label: no narrowed-run sentence"
    fi
    if has_line "  rule 51 $NAME51: canaries $CAN51/$CAN51 · negatives $NEG51/$NEG51 — ok"; then
        ok "$label: rule 51 judged every form — $CAN51/$CAN51 · $NEG51/$NEG51"
    else
        bad "$label: rule 51 is not '$CAN51/$CAN51 · $NEG51/$NEG51 — ok'"
    fi
    refusals=$(grep -cE 'PLANT REFUSED|CANARY DEAD|FALSE-POSITIVE|COULD NOT LOOK|POPULATION SHORT' "$OUT" || true)
    if [ "$refusals" = 0 ]; then ok "$label: no plant refused, no canary dead, no negative fired, nothing unjudged"; else bad "$label: $refusals refusal line(s)"; fi
    if grep -qF '$(' "$OUT"; then bad "$label: the transcript carries the literal \$( — a derivation printed as notation"; else ok "$label: no literal \$( anywhere in the transcript"; fi
}

case_the_remote_declared_base_is_green_on_rules_51_and_60() {
    echo "-- W-C-remote: the base declared only through the 'template' remote"
    narrowed w-c-remote
    common_asserts W-C-remote "selftest: template base — v$VERSION (from the 'template' remote, derived from TEMPLATE_VERSION)"
    local want="  rule 60 $NAME60: canaries $CAN60/$CAN60 · negatives $((NEG60 - 1))/$((NEG60 - 1)) — ok · 0c/1n not producible on this shape (a_product_edit_with_no_base_declared.md needs the template's own shape — no base declared — and this tree declares v$VERSION (from the 'template' remote, derived from TEMPLATE_VERSION); recorded $CAN60/$NEG60)"
    if has_line "$want"; then
        ok "W-C-remote: rule 60 lowers exactly the one form that needs the template's shape, and says why"
    else
        bad "W-C-remote: rule 60 is not '$want'"
    fi
    if grep -qF "· 1 forms not producible on this shape (rules: 60)" "$OUT"; then
        ok "W-C-remote: the foot counts the lowered form"
    else
        bad "W-C-remote: the foot does not count one form not producible (rules: 60)"
    fi
    [ "$FAIL" = 0 ] || sed 's/^/         /' "$OUT"
}

case_the_file_declared_base_is_green_on_rules_51_and_60() {
    echo "-- W-C-file: scripts/local/template-base declares the pre-product sha (outranks the remote)"
    local before=$FAIL
    mkdir -p "$WORLD/scripts/local"
    printf '%s\n' "$PRE" >"$WORLD/scripts/local/template-base"
    git -C "$WORLD" add -- scripts/local/template-base
    git -C "$WORLD" commit -q -m "consumer: the declared base (W-C-file)" ||
        drive_cannot_look "could not commit the file world"
    narrowed w-c-file
    common_asserts W-C-file "selftest: template base — $PRE (from scripts/local/template-base)"
    local want="  rule 60 $NAME60: canaries $CAN60/$CAN60 · negatives $((NEG60 - 1))/$((NEG60 - 1)) — ok · 0c/1n not producible on this shape (a_product_edit_with_no_base_declared.md needs the template's own shape — no base declared — and this tree declares v$VERSION (from the 'template' remote, derived from TEMPLATE_VERSION); recorded $CAN60/$NEG60)"
    if has_line "$want"; then
        ok "W-C-file: with the file taken away the remote still declares a base, so the form is lowered the same way"
    else
        bad "W-C-file: rule 60 is not '$want'"
    fi
    [ "$FAIL" = "$before" ] || sed 's/^/         /' "$OUT"
}

case_the_remote_declared_base_is_green_on_rules_51_and_60
case_the_file_declared_base_is_green_on_rules_51_and_60

echo ""
echo "== $PASS passed · $FAIL failed"
drive_finished
[ "$FAIL" -eq 0 ] || exit 1
exit 0
