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
# drives: quality/ frontend scripts/divergence_census.sh scripts/archaeology_lib.sh docs/product/architecture.md docs/product/build-contract.md docs/product/api-editorial-standard.md TEMPLATE_VERSION pyproject.toml uv.lock
# cites: apps/accounts/tests scripts/local/template-base scripts/db.sh scripts/check.sh scripts/tests/test_divergence_census.sh scripts/tests/test_selftest_leg.sh docs/product/instruments.md
# The engine's self-test, judged on a CONSUMER'S shape rather than this one.
#
# Exit: 0 every case held · 1 a case did not hold · 2 COULD NOT LOOK (no git,
#       no uv, a world that would not build, an interpreter that would not
#       start, an ENGINE that exited 2 without judging a single rule — a plan
#       refused before anything was planted). 2 outranks a pass here for the
#       reason it does everywhere. An engine exit 2 that DID judge the rules —
#       a canary dead, a negative fired, a plant refused on this shape — is the
#       red this drive exists to show, and is its exit 1.
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
#   the release  the world's own release, committed first: a SYNTHETIC version
#                `0.0.0-shapes-<8 hex>` written into the world's TEMPLATE_VERSION
#                and tagged `v0.0.0-shapes-<8 hex>` in a throwaway upstream. It is
#                synthetic because this drive also runs on a PRODUCT's box, whose
#                checkout already carries the real `v<TEMPLATE_VERSION>` tag it
#                fetched to fold — a tag this drive must never collide with. The
#                commit is the base both worlds declare.
#   W-T         that commit as it stands — no base declared, the TEMPLATE's own
#               shape — with an uncommitted edit to scripts/db.sh, a template-
#               owned file no plant touches. Rule 60's base-planting forms
#               declare `needs_clean_tree: template-owned`, so `--selftest --rule
#               60` must read COULD NOT LOOK naming the file (exit 2), never a
#               FALSE-POSITIVE about the builder's own edit; committed, 4/4 · 4/4
#               (the plan's floors). The commit is taken back out afterwards.
#   W-C-remote  the consumer's measured shape: the base declared ONLY through a
#               `template` remote carrying that tag (the census's third reader),
#               no scripts/local/template-base, the product files a Next product
#               has (below), and one product-owned edit named as a divergence so
#               the world's census reads unnamed=0. Committed.
#   W-C-file    the same, plus scripts/local/template-base holding the
#               pre-product sha — the census's second reader, which outranks
#               the remote. Committed on top.
#
# THE PRODUCT FILES ARE PLANTED ONLY WHERE ABSENT, and the transcript names
# which it planted and which it found. On the template's tree every one is
# planted; on a product's box the product's OWN file is what the world carries,
# which is the better world. The set: a root page (`frontend/src/app/page.tsx`),
# a token sheet (`frontend/src/tokens/theme.css`), an env module
# (`frontend/app/env.ts`), and a barrel (`frontend/src/components/index.ts`)
# with the drawer ratchet that pays for it (`quality/local/rules.yaml`,
# `ratchets: {"52": {barrel: 3}}`) — the barrel and its drawer are planted
# together or not at all, because a product's drawer is the product's.
#
# In each it runs the NARROWED self-test, `--selftest --rule 51 --rule 60`,
# stdout to a file, and asserts the judged-shape line, both rule lines, the
# absence of every refusal class and of the literal `$(`. The recorded
# populations are read from the world's own plan, through the engine's own
# loader, never typed here.
#
# THE WHOLE RUN — EVERY RULE ON THE CONSUMER'S SHAPE. In W-C-remote the drive
# can run the engine's WHOLE `--selftest` instead of the narrowed one, once, and
# then asserts EVERY rule's line in HC3.2's shape: `canaries a/a · negatives
# c/c — ok`, a and c the plan's own floors (or, on a line that carries a
# declared lowering — a form not in this world, a form not producible on this
# shape — the floor less exactly the forms that clause counts, with the clause's
# `recorded` numbers equal to the plan's). It is the engine's largest member, so
# it runs ONLY where the selftest unit is sharded across boxes:
#
#   --whole-run                       typed by hand (a box, never a laptop)
#   DJB_SELFTEST_SHAPES_WHOLE_RUN     set by scripts/check.sh's registration when
#                                     the leg runs as `--leg selftest --shard k/N`
#
# Anything else — a `--loop`, a Mac's unsharded full gate, a bare run — is the
# narrowed run, and the transcript's `mode:` line says which it was and why. The
# member keeps its name, and its durations row holds the NARROWED wall only: no
# sharded run can write the durations file (`gate_member_record` returns under
# any `--leg`, and `--store-durations` refuses a shard), so the partition
# balances on the narrowed cost, never the whole run's. The registration decides
# the mode before the leg's consult and never reuses a banked green for a whole
# run.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * IT MEASURES HEAD, NOT THE WORKING TREE. The world is a clone; an
#     uncommitted edit in this checkout is invisible to it.
#   * EVERY RULE ONLY UNDER A SHARD. A narrowed run (every `--loop`, every
#     unsharded gate) judges rules 51 and 60 on this shape and no others; the
#     whole run is the sharded bank's, and a red it finds blocks that bank.
#   * THE WHOLE RUN JUDGES ONE WORLD. W-C-remote gets every rule; W-C-file
#     stays narrowed.
#   * NEITHER THE MODE NOR THE TREE IS IN THE DRIVE'S KEY. The selftest leg
#     keys this member on `drive_key` (this file, its `# drives:` blobs, the
#     machine), so a NARROWED run can be REUSED from any banked green at that
#     key — a change the key does not read (`apps/`, `config/`, most of
#     `scripts/`) is not re-judged narrowed. A WHOLE run is never reused: the
#     registration in scripts/check.sh decides the mode before the leg's consult
#     and skips the lookup for it, printing `not consulted`; its green still
#     banks, and a later narrowed run may read it back.
#   * TWO BASE READERS, NOT THREE. A base typed in DJB_TEMPLATE_BASE is the
#     same shape as the remote to the self-test and is not separately driven.
#   * FOUR PRODUCT FILES, TRANSCRIBED. A product's tree carries far more than
#     the world does (a drawer with thirty rules, screens, panels); what the
#     world does not carry is not asked whether a plant collides with it.
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

CASES="case_a_dirty_template_owned_path_is_could_not_look_on_rule_60 case_the_remote_declared_base_is_green case_the_file_declared_base_is_green_on_rules_51_and_60 case_one_rule_that_could_not_look_is_named_could_not_look"
MODE=narrowed
MODE_WHY="the default: every --loop and every unsharded gate — the whole run is the sharded bank's (--leg selftest --shard k/N)"
case "${1:-}" in
--list)
    for c in $CASES; do printf '%s\n' "$c"; done
    exit 0
    ;;
--whole-run)
    MODE=whole
    MODE_WHY="--whole-run was typed"
    ;;
"") ;;
*)
    echo "!! test_selftest_shapes: unknown argument '$1' (takes --list, --whole-run or nothing)" >&2
    exit 2
    ;;
esac
if [ -n "${DJB_SELFTEST_SHAPES_WHOLE_RUN:-}" ]; then
    MODE=whole
    MODE_WHY="$DJB_SELFTEST_SHAPES_WHOLE_RUN"
fi

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
CNL=0
ok() {
    PASS=$((PASS + 1))
    printf '   ok    %s\n' "$*"
}
bad() {
    FAIL=$((FAIL + 1))
    printf '   FAIL  %s\n' "$*"
}
# cnl — ONE RULE THE ENGINE COULD NOT LOOK AT, inside a run that judged the
# rest. Neither a pass nor a finding about the world: a probe whose environment
# was missing (a database, a stack) is not "a form collides with a file a
# product has", and the drive's exit says which of the two it saw
# (`shapes_verdict`).
cnl() {
    CNL=$((CNL + 1))
    printf '   could not look  %s\n' "$*"
}
now() { date +%s; }

# --- the world ---------------------------------------------------------------
T0=$(now)
git clone --quiet --shared --no-hardlinks "$ROOT" "$WORLD" >/dev/null 2>&1 ||
    drive_cannot_look "could not clone this checkout into $WORLD"
git -C "$WORLD" config user.email consumer@example.com
git -C "$WORLD" config user.name Consumer
ORIG=$(git -C "$WORLD" rev-parse HEAD) || drive_cannot_look "the clone has no HEAD"
CHECKOUT_VERSION=$(tr -d '[:space:]' <"$WORLD/TEMPLATE_VERSION" 2>/dev/null || true)
case "$CHECKOUT_VERSION" in
[0-9]*.[0-9]*.[0-9]*) ;;
*) drive_cannot_look "TEMPLATE_VERSION does not read as <major>.<minor>.<patch>: '$CHECKOUT_VERSION'" ;;
esac
# The world's first `uv run` provisions its venv and says so on stderr; warmed
# here so every capture below is the engine's answer and nothing else.
(cd "$WORLD" && uv run python -c 'pass') >"$WORK/warm.log" 2>&1 || {
    sed 's/^/         /' "$WORK/warm.log" >&2
    drive_cannot_look "the clone's interpreter would not start — \`uv run\` failed in $WORLD"
}

# THE RECORDED POPULATIONS, read from the plan the world carries THROUGH THE
# ENGINE'S OWN LOADER — the template's rules and a drawer's alike, and the
# floor each one records — so a drive that typed "5/5" cannot pass the day a
# form was deleted along with its floor. Tab-separated, one `floor` row a rule.
FLOORS="$WORK/floors.txt"
(cd "$WORLD" && uv run python - >"$FLOORS" 2>&1) <<'PY' || { sed 's/^/         /' "$FLOORS" >&2; drive_cannot_look "the world's plan would not read through quality.gate's own loader"; }
import quality.gate as g

for rule in g.RULES:
    f = g.selftest_floor(rule)
    print(
        "floor",
        rule["id"],
        rule.get("name", ""),
        "on" if rule.get("enabled", True) else "off",
        int(f["canaries"]),
        int(f["negatives"]),
        sep="\t",
    )
PY
floor_of() { # floor_of <rid> — sets F_NAME F_CAN F_NEG from the plan
    F_NAME=""
    F_CAN=""
    F_NEG=""
    local tag rid name on can neg
    while IFS=$'\t' read -r tag rid name on can neg; do
        [ "$tag" = floor ] && [ "$rid" = "$1" ] || continue
        F_NAME=$name
        F_CAN=$can
        F_NEG=$neg
    done <"$FLOORS"
    [ -n "$F_NEG" ] || drive_cannot_look "the world's plan names no rule $1: $(cat "$FLOORS")"
}
floor_of 51
NAME51=$F_NAME CAN51=$F_CAN NEG51=$F_NEG
floor_of 60
NAME60=$F_NAME CAN60=$F_CAN NEG60=$F_NEG

# THE WORLD'S OWN RELEASE. A synthetic version and a synthetic tag, committed
# before anything a product adds, so the tag names the base and a product box
# carrying the real `v<TEMPLATE_VERSION>` tag has nothing here to collide with.
HEX=$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')
case "$HEX" in
[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) ;;
*) drive_cannot_look "could not draw 8 hex digits for the world's synthetic release: '$HEX'" ;;
esac
VERSION="0.0.0-shapes-$HEX"
printf '%s\n' "$VERSION" >"$WORLD/TEMPLATE_VERSION"
git -C "$WORLD" add -- TEMPLATE_VERSION
# The remote world declares its base through the remote ALONE. A product box's
# own file declaration is taken out of the world (never out of the product's
# tree — this is a clone), and the transcript says so.
if [ -e "$WORLD/scripts/local/template-base" ]; then
    git -C "$WORLD" rm -q -- scripts/local/template-base ||
        drive_cannot_look "could not take the checkout's own scripts/local/template-base out of the world"
    echo "   world: found scripts/local/template-base — taken out of the world, so W-C-remote declares its base through the remote alone"
fi
git -C "$WORLD" commit -q -m "world: the synthetic release v$VERSION (the base both worlds declare)" ||
    drive_cannot_look "could not commit the world's synthetic release"
PRE=$(git -C "$WORLD" rev-parse HEAD) || drive_cannot_look "the world's release has no sha"

# --- the runs ----------------------------------------------------------------
OUT=""
RC=0
narrowed() { # narrowed <label> [<rule id>…] — the engine's narrowed self-test in the world, to a file
    local label=$1 t args="" ids=""
    shift
    [ "$#" -gt 0 ] || set -- 51 60
    for id in "$@"; do
        args="$args --rule $id"
        ids="${ids:+$ids, }$id"
    done
    OUT="$WORK/selftest-$label.log"
    t=$(now)
    set +e
    # shellcheck disable=SC2086 # `--rule <id>` pairs, ids are plain integers
    (cd "$WORLD" && uv run python -m quality.gate --selftest $args) >"$OUT" 2>&1
    RC=$?
    set -e
    echo "   $label: quality.gate --selftest${args} — exit $RC ($(($(now) - t))s)"
    engine_looked "$label"
}
# engine_looked <label> — the engine's exit 2 is THIS drive's exit 2 when the
# engine never reached a rule's judgment. The self-test answers exit 2 for two
# different things: a form that was JUDGED and failed (a canary dead, a negative
# fired, a plant refused on this shape — the red this drive exists to show, its
# exit 1), and an engine that COULD NOT LOOK at all (a plan refused at
# `consistency()` before anything was planted, a tree it would not plant into).
# The second never prints the by-rule block; turning it into a FAIL would call
# enforcement that never ran a red on the consumer's shape. Any exit outside
# 0/1/2 is the same: an engine that did not finish is not an answer.
engine_looked() {
    local first
    case "$RC" in
    0 | 1) return 0 ;;
    2) grep -qF 'selftest, by rule (fired/recorded · silent/recorded):' "$OUT" && return 0 ;;
    esac
    sed 's/^/         /' "$OUT" >&2
    first=$(grep -m1 '^  !! ' "$OUT" || true)
    drive_cannot_look "$1: the engine could not look (exit $RC) and judged no rule — its first line: ${first#  !! }"
}
has_line() { grep -qxF -- "$1" "$OUT"; }
# rule_line <rid> — the one line the engine printed for that rule, or nothing.
rule_line() { awk -v p="  rule $1 " 'index($0, p) == 1 { print; exit }' "$OUT"; }

# --- W-T: the template's own shape, dirty on a template-owned path ------------
# Run BEFORE the remote exists, on the world's release commit: no base declared,
# which is the template's shape (a product box's own file base was taken out of
# the world above). HC2 § 8c F1: rule 60's base-planting forms plant `HEAD` as the
# base, so an uncommitted edit to ANY template-owned file used to read as their
# FALSE-POSITIVE. They declare `needs_clean_tree: template-owned`; the line must
# now be COULD NOT LOOK naming the file, exit 2, and — once committed — ok.
case_a_dirty_template_owned_path_is_could_not_look_on_rule_60() {
    echo "-- W-T: the template's shape, an uncommitted edit to scripts/db.sh (outside every plant)"
    local before=$FAIL line cause
    [ -f "$WORLD/scripts/db.sh" ] || drive_cannot_look "the world has no scripts/db.sh to dirty"
    printf '\n# W-T: an uncommitted edit, the builder'"'"'s own and no product'"'"'s\n' >>"$WORLD/scripts/db.sh"
    narrowed w-t-dirty 60
    cause="the tree is dirty on a template-owned path outside the plants: scripts/db.sh — commit or stash it; a base-planting form cannot tell your edit from a product's"
    if [ "$RC" = 2 ]; then ok "W-T dirty: the narrowed self-test exits 2 (could not look)"; else bad "W-T dirty: exited $RC, want 2"; fi
    line=$(rule_line 60)
    case "$line" in
    "  rule 60 $NAME60: canaries "*" — COULD NOT LOOK ($cause)")
        ok "W-T dirty: rule 60's line is COULD NOT LOOK naming scripts/db.sh and the remedy"
        ;;
    *) bad "W-T dirty: rule 60's line is '$line', want '… — COULD NOT LOOK ($cause)'" ;;
    esac
    if grep -qF 'FALSE-POSITIVE' "$OUT"; then
        bad "W-T dirty: a FALSE-POSITIVE line was printed — the form judged your edit as its own finding"
    else
        ok "W-T dirty: no FALSE-POSITIVE line — the form was not planted over your edit"
    fi
    if grep -qF "  !! rule 60: COULD NOT LOOK — " "$OUT"; then
        ok "W-T dirty: the ENFORCEMENT BROKEN block names rule 60's could-not-look"
    else
        bad "W-T dirty: no '!! rule 60: COULD NOT LOOK — …' line under ENFORCEMENT BROKEN"
    fi
    git -C "$WORLD" add -- scripts/db.sh
    git -C "$WORLD" commit -q -m "W-T: the edit, committed" || drive_cannot_look "could not commit the W-T edit"
    narrowed w-t-committed 60
    if [ "$RC" = 0 ]; then ok "W-T committed: the narrowed self-test exits 0"; else bad "W-T committed: exited $RC, want 0"; fi
    if has_line "selftest: template base — none declared (the template's own shape)"; then
        ok "W-T committed: judged on the template's own shape"
    else
        bad "W-T committed: not judged on the template's own shape"
    fi
    if has_line "  rule 60 $NAME60: canaries $CAN60/$CAN60 · negatives $NEG60/$NEG60 — ok"; then
        ok "W-T committed: rule 60 judged every form — $CAN60/$CAN60 · $NEG60/$NEG60"
    else
        bad "W-T committed: rule 60 is '$(rule_line 60)', want '$CAN60/$CAN60 · $NEG60/$NEG60 — ok'"
    fi
    [ "$FAIL" = "$before" ] || sed 's/^/         /' "$OUT"
    git -C "$WORLD" reset -q --hard "$PRE" || drive_cannot_look "could not take the W-T commit back out of the world"
}
case_a_dirty_template_owned_path_is_could_not_look_on_rule_60

# W-C-remote: the base is declared ONLY through the `template` remote.
git clone --quiet --shared --no-hardlinks "$WORLD" "$UPSTREAM" >/dev/null 2>&1 ||
    drive_cannot_look "could not clone the upstream the 'template' remote names"
if git -C "$UPSTREAM" rev-parse -q --verify "refs/tags/v$VERSION" >/dev/null 2>&1; then
    drive_cannot_look "the upstream already carries the synthetic tag v$VERSION — nothing this drive writes should"
fi
git -C "$UPSTREAM" -c user.email=template@example.com -c user.name=Template \
    tag -a "v$VERSION" -m base "$PRE" || drive_cannot_look "could not tag v$VERSION in the upstream"
git -C "$WORLD" remote add template "$UPSTREAM"
git -C "$WORLD" fetch -q template "refs/tags/v$VERSION:refs/tags/v$VERSION" ||
    drive_cannot_look "could not fetch the template remote's synthetic tag v$VERSION"

# THE PRODUCT FILES, each planted only where absent.
PLANTED=""
FOUND=""
product_file() { # product_file <path> — body on stdin; planted only where absent
    local path=$1
    if [ -e "$WORLD/$path" ]; then
        cat >/dev/null
        FOUND="$FOUND $path"
        echo "   world: found   $path — the checkout's own, kept"
        return 1
    fi
    mkdir -p "$(dirname "$WORLD/$path")"
    cat >"$WORLD/$path"
    PLANTED="$PLANTED $path"
    echo "   world: planted $path"
    return 0
}
# A LEGAL Next root page: `app` reaching `api` is the one door rule 51 opens,
# so the world's baseline gains no rule-51 finding of its own.
product_file frontend/src/app/page.tsx <<'TSX' || true
import { redirect } from "next/navigation";

import { listOrganizations } from "@/api/client";

export default function RootPage(): never {
    void listOrganizations;
    redirect("/welcome");
}
TSX
# A token sheet at the path rule 53's plants used to take: one token, declared
# and consumed in the same sheet, so the sheet is legal on its own.
product_file frontend/src/tokens/theme.css <<'CSS' || true
:root {
  --product-brand: #1d4ed8;
}

body {
  accent-color: var(--product-brand);
}
CSS
# An env module at the path rule 50's plants used to take: the tree NAMES the
# value and the build environment holds it.
product_file frontend/app/env.ts <<'TS' || true
export const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "";
TS
# A real barrel and the drawer ratchet that pays for it — together or not at
# all: a product's drawer is the product's, and a barrel with no ratchet is a
# finding this world did not come here to make.
if [ -e "$WORLD/frontend/src/components/index.ts" ] || [ -e "$WORLD/quality/local/rules.yaml" ]; then
    for p in frontend/src/components/index.ts quality/local/rules.yaml; do
        if [ -e "$WORLD/$p" ]; then
            FOUND="$FOUND $p"
            echo "   world: found   $p — the checkout's own, kept (the barrel and its drawer ratchet are planted together or not at all)"
        fi
    done
else
    product_file frontend/src/components/index.ts <<'TS' || true
export * from "./deal-card";
export * from "./stage-badge";
export * from "./avatar";
TS
    product_file quality/local/rules.yaml <<'YAML' || true
ratchets:
  "52":
    barrel: 3
YAML
fi
# One product-owned edit to a template-owned directory, NAMED as a divergence,
# so the world's own census reads unnamed=0 and rule 60's baseline is clean. A
# checkout that already has the file has already paid the debt: kept, unnamed
# by this drive, and not a divergence against a base that already carries it.
if product_file apps/accounts/tests/test_door_pair_parity.py <<'PY'; then
"""The consumer's (rest, mcp) parity test for accounts — the debt, paid."""

DOOR_PAIR = ("rest", "mcp")


def test_the_pair_is_claimed() -> None:
    assert DOOR_PAIR == ("rest", "mcp")
PY
    printf '\ndivergence: apps/accounts/tests/test_door_pair_parity.py — pays the (rest, mcp) debt\n' \
        >>"$WORLD/docs/product/architecture.md"
    PLANTED="$PLANTED docs/product/architecture.md"
fi
if [ -n "$PLANTED" ]; then
    # shellcheck disable=SC2086 # a list of repo paths, none with a space
    git -C "$WORLD" add -- $PLANTED
fi
git -C "$WORLD" commit -q --allow-empty -m "consumer: the product's own tree (W-C-remote)" ||
    drive_cannot_look "could not commit the remote world"
T1=$(now)
echo "   world: a clone of HEAD $(git -C "$ROOT" rev-parse --short HEAD) (TEMPLATE_VERSION $CHECKOUT_VERSION) with the 'template' remote at the synthetic v$VERSION, built in $((T1 - T0))s"
echo "   world: planted${PLANTED:- nothing} · found${FOUND:- nothing}"

# --- the W-C cases -----------------------------------------------------------
whole() { # whole <label> — the engine's WHOLE self-test in the world, to a file
    OUT="$WORK/selftest-$1.log"
    local t
    # THE WHOLE RUN NEEDS WHAT THE ENGINE'S OWN MEMBER HAS: a database and the
    # stack. The Django probes, rule 35's hot-path probe and the drawers leg's
    # pytest case all open this checkout's database, and a clone has no `.env`
    # — so the world reads THIS checkout's, copied beside it (ignored by git,
    # so no census and no rule sees it). It is the same database the engine
    # member two members up just used, one run after the other, never at once.
    if [ -f "$ROOT/.env" ] && [ ! -e "$WORLD/.env" ]; then
        cp "$ROOT/.env" "$WORLD/.env" || drive_cannot_look "could not give the world this checkout's .env"
        echo "   world: the whole run reads this checkout's .env (its database and stack) — copied, ignored by git"
    fi
    t=$(now)
    set +e
    (cd "$WORLD" && uv run python -m quality.gate --selftest) >"$OUT" 2>&1
    RC=$?
    set -e
    echo "   $1: quality.gate --selftest (the whole run) — exit $RC ($(($(now) - t))s)"
    engine_looked "$1"
}

# every_rule_asserts <label> — HC3.2's shape for EVERY rule line of a whole run.
# The numbers come from the floors file (the world's plan, read through the
# engine's loader), never from here. A line may carry the engine's declared
# lowerings (` · Nc/Mn not in this world (…; recorded X/Y)`, ` · … not producible
# on this shape (…; recorded X/Y)`): then its X/Y must be the plan's floor and
# the judged numbers the floor less exactly what the clauses count. Anything
# else — a second line, no line, a/b unequal, SHORT, COULD NOT LOOK — is a FAIL
# naming the rule. One `ok`/`FAIL` per rule in the plan.
every_rule_asserts() {
    local label=$1 verdict rid what judged="$WORK/judged-$1.tsv"
    (cd "$WORLD" && uv run python - "$FLOORS" "$OUT" >"$judged" 2>&1) <<'PY' || { sed 's/^/         /' "$judged" >&2; drive_cannot_look "the rule-line judge would not run in the world"; }
import re
import sys

floors = []
for row in open(sys.argv[1], encoding="utf-8"):
    f = row.rstrip("\n").split("\t")
    if f[0] == "floor":
        floors.append((f[1], f[2], f[3], int(f[4]), int(f[5])))
lines = open(sys.argv[2], encoding="utf-8").read().splitlines()
HEAD = re.compile(r"canaries (\d+)/(\d+) · negatives (\d+)/(\d+) — ok")
CLAUSE = re.compile(
    r" · (\d+)c/(\d+)n not (?:in this world|producible on this shape) \(.*?recorded (\d+)/(\d+)\)"
)
for rid, name, on, can, neg in floors:
    prefix = f"  rule {rid} {name}: "
    mine = [ln[len(prefix):] for ln in lines if ln.startswith(prefix)]
    if len(mine) != 1:
        print(f"BAD\t{rid}\tthe transcript carries {len(mine)} line(s) for it, want exactly 1")
        continue
    line = mine[0]
    if on == "off":
        ok = line == "DISABLED — not planted"
        print(f"{'OK' if ok else 'BAD'}\t{rid}\tdisabled in the plan; its line: {line}")
        continue
    m = HEAD.match(line)
    if not m:
        # A RULE THE ENGINE COULD NOT LOOK AT is its own verdict, never a BAD:
        # the engine printed `— COULD NOT LOOK (<why>)` because a form could
        # not be judged here, and calling that a failed form would name a cause
        # (a collision with the product's tree) nothing proved.
        k = re.search(r" — (COULD NOT LOOK \(.*\))", line)
        if k:
            print(f"CNL\t{rid}\t{k.group(1)}")
            continue
        print(f"BAD\t{rid}\tnot an ok line: {line}")
        continue
    a, b, c, d = (int(x) for x in m.groups())
    if a != b or c != d:
        print(f"BAD\t{rid}\tjudged {a}/{b} · {c}/{d}, not every form it expected")
        continue
    rest, lc, ln, why = line[m.end():], 0, 0, ""
    while rest:
        k = CLAUSE.match(rest)
        if not k:
            why = f"an unreadable tail: {rest}"
            break
        if (int(k.group(3)), int(k.group(4))) != (can, neg):
            why = f"a clause records {k.group(3)}/{k.group(4)}, the plan records {can}/{neg}"
            break
        lc, ln, rest = lc + int(k.group(1)), ln + int(k.group(2)), rest[k.end():]
    if why:
        print(f"BAD\t{rid}\t{why}")
    elif b + lc != can or d + ln != neg:
        print(f"BAD\t{rid}\t{a}/{b} · {c}/{d} with {lc}c/{ln}n lowered is not the plan's {can}/{neg}")
    elif lc or ln:
        print(f"OK\t{rid}\t{a}/{b} · {c}/{d}: the plan's {can}/{neg} less the {lc}c/{ln}n its line names")
    else:
        print(f"OK\t{rid}\t{a}/{b} · {c}/{d}: every recorded form")
PY
    while IFS=$'\t' read -r verdict rid what; do
        case "$verdict" in
        OK) ok "$label: rule $rid — $what" ;;
        BAD) bad "$label: rule $rid — $what" ;;
        CNL) cnl "$label: rule $rid — $what" ;;
        *) bad "$label: the rule-line judge printed a row with no verdict: '$verdict $rid $what'" ;;
        esac
    done <"$judged"
}
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
REMOTE_SHAPE="v$VERSION (from the 'template' remote, derived from TEMPLATE_VERSION)"
rule60_lowered() { # the rule-60 line on a remote-declared base: negative 2 not producible
    printf '%s' "  rule 60 $NAME60: canaries $CAN60/$CAN60 · negatives $((NEG60 - 1))/$((NEG60 - 1)) — ok · 0c/1n not producible on this shape (a_product_edit_with_no_base_declared.md needs the template's own shape — no base declared — and this tree declares $REMOTE_SHAPE; recorded $CAN60/$NEG60)"
}

case_the_remote_declared_base_is_green() {
    echo "-- W-C-remote: the base declared only through the 'template' remote"
    local before=$FAIL want refusals
    if [ "$MODE" = whole ]; then
        whole w-c-remote
        if [ "$RC" = 0 ]; then ok "W-C-remote: the whole self-test exits 0"; else bad "W-C-remote: the whole self-test exited $RC, want 0"; fi
        if has_line "selftest: template base — $REMOTE_SHAPE"; then
            ok "W-C-remote: judged shape — the remote's synthetic tag"
        else
            bad "W-C-remote: no judged-shape line 'selftest: template base — $REMOTE_SHAPE'"
        fi
        if grep -qF 'selftest: narrowed to rule(s)' "$OUT"; then
            bad "W-C-remote: the whole run says it is narrowed"
        else
            ok "W-C-remote: the run is the whole run, not a narrowed one"
        fi
        every_rule_asserts W-C-remote
        refusals=$(grep -cE 'PLANT REFUSED|CANARY DEAD|FALSE-POSITIVE|POPULATION SHORT' "$OUT" || true)
        if [ "$refusals" = 0 ]; then
            ok "W-C-remote: no plant refused, no canary dead, no negative fired"
        else
            bad "W-C-remote: $refusals refusal line(s)"
        fi
        # COULD NOT LOOK and the ENFORCEMENT BROKEN block it lands in are the
        # per-rule `could not look` tally's, above — counted there, not here.
        if [ "$CNL" = 0 ] && grep -qE 'COULD NOT LOOK|ENFORCEMENT BROKEN' "$OUT"; then
            bad "W-C-remote: the transcript says COULD NOT LOOK / ENFORCEMENT BROKEN and no rule line carries it"
        fi
        if grep -qF '$(' "$OUT"; then bad "W-C-remote: the transcript carries the literal \$( — a derivation printed as notation"; else ok "W-C-remote: no literal \$( anywhere in the transcript"; fi
        if has_line "selftest clean: every canary fired, every negative stayed silent · 1 form not producible on this shape."; then
            ok "W-C-remote: the closing line says clean and counts the one lowered form"
        else
            bad "W-C-remote: no closing line 'selftest clean: … · 1 form not producible on this shape.'"
        fi
    else
        narrowed w-c-remote
        common_asserts W-C-remote "selftest: template base — $REMOTE_SHAPE"
    fi
    want=$(rule60_lowered)
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
    [ "$FAIL" = "$before" ] || sed 's/^/         /' "$OUT"
}

case_the_file_declared_base_is_green_on_rules_51_and_60() {
    echo "-- W-C-file: scripts/local/template-base declares the pre-product sha (outranks the remote)"
    local before=$FAIL want
    mkdir -p "$WORLD/scripts/local"
    printf '%s\n' "$PRE" >"$WORLD/scripts/local/template-base"
    git -C "$WORLD" add -- scripts/local/template-base
    git -C "$WORLD" commit -q -m "consumer: the declared base (W-C-file)" ||
        drive_cannot_look "could not commit the file world"
    narrowed w-c-file
    common_asserts W-C-file "selftest: template base — $PRE (from scripts/local/template-base)"
    want=$(rule60_lowered)
    if has_line "$want"; then
        ok "W-C-file: with the file taken away the remote still declares a base, so the form is lowered the same way"
    else
        bad "W-C-file: rule 60 is not '$want'"
    fi
    [ "$FAIL" = "$before" ] || sed 's/^/         /' "$OUT"
}

# shapes_verdict <fail> <could-not-look> — the drive's exit, from its two
# tallies: 1 when a form was JUDGED and failed (whatever else could not look),
# 2 when nothing failed and at least one rule could not be looked at, 0 clean.
# Printed as one line so scripts/check.sh's registration, which reads the exit,
# and a reader of the transcript see the same answer.
shapes_verdict() {
    if [ "$1" -gt 0 ]; then
        echo "   verdict: RED — ${1} judged assertion(s) failed${2:+ (and ${2} rule(s) could not be looked at)}"
        return 1
    fi
    if [ "$2" -gt 0 ]; then
        echo "   verdict: COULD NOT LOOK — ${2} rule(s) could not be judged in this world; nothing judged failed"
        return 2
    fi
    return 0
}

# THE JUDGE'S OWN DRIVE: a planted transcript in which one rule could not look
# and the rest are ok. It must come back `could not look` for that rule, no
# FAIL, and the verdict 2 — never a FAIL naming a collision. Run in a subshell
# so its tallies are its own.
case_one_rule_that_could_not_look_is_named_could_not_look() {
    echo "-- the judge: one rule that could not look inside a judged whole run"
    local floors="$WORK/cnl-floors.txt" out="$WORK/cnl-transcript.log" said rc=0
    printf 'floor\t51\t%s\ton\t%s\t%s\nfloor\t60\t%s\ton\t%s\t%s\n' \
        "$NAME51" "$CAN51" "$NEG51" "$NAME60" "$CAN60" "$NEG60" >"$floors"
    {
        echo "  rule 51 $NAME51: canaries $CAN51/$CAN51 · negatives $NEG51/$NEG51 — ok"
        echo "  rule 60 $NAME60: canaries 0/$CAN60 · negatives 0/$NEG60 — COULD NOT LOOK (the probe's database would not open in this world)"
    } >"$out"
    said=$(
        PASS=0 FAIL=0 CNL=0
        FLOORS=$floors OUT=$out
        every_rule_asserts planted
        shapes_verdict "$FAIL" "$CNL" || echo "exit=$?"
        echo "tally pass=$PASS fail=$FAIL cnl=$CNL"
    ) || rc=$?
    case "$said" in
    *"could not look  planted: rule 60 — COULD NOT LOOK (the probe's database would not open in this world)"*) ok "the rule's line says could not look, with the engine's cause" ;;
    *) bad "the could-not-look rule was not named could not look — the judge said: $(printf '%s' "$said" | tr '\n' '|')" ;;
    esac
    case "$said" in
    *"tally pass=1 fail=0 cnl=1"*) ok "one ok, no FAIL, one could-not-look" ;;
    *) bad "the tally is not 1 ok / 0 FAIL / 1 could-not-look — $(printf '%s' "$said" | tr '\n' '|')" ;;
    esac
    case "$said" in
    *"exit=2"*) ok "the verdict is 2 (could not look), never 1 (a judged red)" ;;
    *) bad "the verdict is not 2 — $(printf '%s' "$said" | tr '\n' '|')" ;;
    esac
    case "$said" in
    *"collides"*) bad "the judge names a collision for a rule that could not look" ;;
    *) ok "no line names a collision" ;;
    esac
}

echo "   mode: $MODE — $MODE_WHY"
case_the_remote_declared_base_is_green
case_the_file_declared_base_is_green_on_rules_51_and_60
case_one_rule_that_could_not_look_is_named_could_not_look

echo ""
echo "== $PASS passed · $FAIL failed · $CNL could not look"
drive_finished
VERDICT_RC=0
shapes_verdict "$FAIL" "$CNL" || VERDICT_RC=$?
exit "$VERDICT_RC"
