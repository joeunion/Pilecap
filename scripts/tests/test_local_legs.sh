#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh.
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
# drives: .github/workflows/ci.yml scripts/check.sh scripts/gate_ledger.sh scripts/pm_push.sh
# cites: docs/product/build-contract.md scripts/tests/test_list_legs.sh
# The drive for THE PRODUCT-LEG DRAWER — `scripts/local/legs/<name>.sh`.
#
#   ./scripts/tests/test_local_legs.sh          run every case
#   ./scripts/tests/test_local_legs.sh --list   name them and stop
#
# WHY IT EXISTS. This repository is a template, and a product that clones it
# grows legs of its own. Before the drawer the only place to put one was inside
# `scripts/check.sh`, and the first consumer's v2.1.0 fold measured the price:
# 94 conflicts, 21 in `scripts/ quality/ .github/`, and `check.sh` itself
# FAST-FORWARDED byte-identical — 1826 lines of their legs gone with no conflict
# at all. Every property below is one half of the replacement: a leg DECLARED
# beside the gate is discovered, named, run, refused when malformed, and
# INVISIBLE when the drawer is not there.
#
# THE NEGATIVE IS THE ONE THAT MATTERS MOST, and it is asserted by DIFFING two
# runs rather than by reading a paragraph: with no drawer, this gate's listing
# is byte-for-byte the listing of a tree that has never heard of the drawer.
# A seam a product can adopt is only free if it costs the template nothing.
#
# IT BUILDS ITS OWN VICTIMS, always. A plant is either a scratch directory
# handed to the reader through `DJB_LOCAL_LEGS_DIR` or a drawer inside a
# `git clone` of this checkout under `mktemp -d`. Nothing here writes into the
# checkout the gate is measuring — an untracked executable in it reds the
# instrument census by design, and an untracked file in it moves the tree every
# verdict is keyed on.
#
# TWO INSTRUMENTS, AND THE SPLIT IS DELIBERATE.
#   1. THE FENCE, SOURCED. `check.sh` marks the reader with
#      `# >>> local-legs >>>` sentinels; most cases extract that block into the
#      scratch directory and call the functions directly. A drive may not run a
#      nested `./scripts/check.sh` inside a gate — the per-checkout lock refuses
#      it — so calling the BODY is the rule here as everywhere.
#   2. THE GATE, IN A CLONE. A clone is a different checkout with its own lock,
#      so the cases whose subject is the whole flow — the listing, `--leg`, the
#      full gate's announced position — run the real gate there.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#   * WHETHER A PRODUCT LEG IS CORRECT. Nothing here asks what a product's leg
#     asserts, only that it was found, declared, run, named and composed. That
#     is the product's own business and it is the point of the seam.
#   * A LEG THAT MUST RUN INSIDE THE PYTEST PROCESS. A product fixture or a
#     conftest plugin is not expressible as a leg at all; it has its own seam
#     and this drive is silent about it.
#   * THE LIVE BANK. `case_the_bank_plan_takes_a_local_unit_from_the_listing`
#     drives `bank_boxes_plan` — the function that turns the listing into one
#     row per box — over a planted listing. Whether real boxes come up, run
#     `--leg local` and compose `local:<name>` into a real verdict row is one
#     live bank, and it is `pm_push.sh`'s own.
#   * WALL TIME AS AN ASSERTION, except for the listing, where "the drawer
#     costs nothing when it is absent" is the property.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_local_legs: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0
CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
}
cannot_look() {
    echo "!! test_local_legs: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

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
# <<< one case, by name <<<
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
        echo "!! --case: test_local_legs.sh defines no case named '${2}'; --list names them" >&2
        exit 2
    }
    ONLY_CASE="$2"
    ;;
*)
    echo "!! unknown argument '$1': test_local_legs.sh takes nothing, --list or --case <name>" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the drawer this drive exists for has no reader"
grep -q '^# >>> local-legs >>>$' scripts/check.sh ||
    cannot_look "scripts/check.sh carries no '# >>> local-legs >>>' block — the drawer reader this drive exists for is not there"
grep -q '^gate_leg_local_legs() {' scripts/check.sh ||
    cannot_look "scripts/check.sh defines no gate_leg_local_legs — the drawer runner this drive exists for is not there"

ROOT="$PWD"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-locallegs.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# --- the fence, extracted once -----------------------------------------------
#
# THE SAME SHAPE `test_gate_lease.sh` USES FOR THE HEARTBEAT, and for the same
# reason: the functions live in the gate rather than in a library, because a
# library sourced by drives that run no leg must not carry a leg runner. If the
# sentinels go, this is could-not-look and says so, rather than a set of cases
# that quietly stopped driving anything.
FENCE="${WORK}/local-legs.sh"
awk '
    /^# >>> local-legs >>>$/ { on = 1; next }
    /^# <<< local-legs <<<$/ { on = 0 }
    on
' scripts/check.sh >"$FENCE"
[ -s "$FENCE" ] || cannot_look "the extracted local-legs block is empty"

# fence_run <script> — run a snippet with the fence sourced, in a subshell, with
# the two derivation inputs PLANTED so the block is sourceable without the gate
# around it. Output on stdout, exit status the snippet's.
fence_run() {
    (
        set +e
        cd "$ROOT" || exit 2
        FULL_LEGS_TEMPLATE="ruff,mypy,selftest"
        DJB_LOCAL_LEGS_KNOWN_NAMES="$(printf 'ruff\nmypy\nselftest\nlist_legs\n')"
        DJB_LOCAL_LEGS_TEMPLATE_UNITS="$(printf 'static\npytest-x2\nselftest\n')"
        export FULL_LEGS_TEMPLATE DJB_LOCAL_LEGS_KNOWN_NAMES DJB_LOCAL_LEGS_TEMPLATE_UNITS
        # shellcheck source=/dev/null
        . "$FENCE"
        eval "$1"
    )
}

# plant_leg <dir> <name> <body-exit> [<header overrides, one per line>] — a leg
# in a drawer, executable, with a v1 header. The overrides REPLACE a field of
# the same name, so a case spells only what it is about.
plant_leg() {
    local dir=$1 name=$2 code=$3 over=${4:-}
    local unit=local needs=none tier=full twomeans=broken touches="" inputs="" envn=""
    local line f v
    mkdir -p "$dir"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        f=${line%%:*}
        v=${line#*:}
        v=${v# }
        case "$f" in
        unit) unit=$v ;;
        needs) needs=$v ;;
        tier) tier=$v ;;
        two-means) twomeans=$v ;;
        touches) touches=$v ;;
        inputs) inputs=$v ;;
        env) envn=$v ;;
        *) cannot_look "plant_leg was handed an override for '${f}', which is not a header field" ;;
        esac
    done <<EOF
${over}
EOF
    {
        echo '#!/usr/bin/env bash'
        echo '# >>> leg v1 >>>'
        echo "# unit: ${unit}"
        echo "# needs: ${needs}"
        echo "# tier: ${tier}"
        echo "# two-means: ${twomeans}"
        [ -z "$touches" ] || echo "# touches: ${touches}"
        [ -z "$inputs" ] || echo "# inputs: ${inputs}"
        [ -z "$envn" ] || echo "# env: ${envn}"
        echo '# <<< leg <<<'
        echo "echo \"${name}: this is a planted product leg\""
        echo "exit ${code}"
    } >"${dir}/${name}.sh"
    chmod +x "${dir}/${name}.sh"
}

# clone_into <dir> — a scratch checkout of this repository, with a local `main`.
# The reasoning is `test_list_legs.sh`'s `clone_into` and is not repeated here.
clone_into() {
    local sha have
    git clone --quiet --shared --no-hardlinks "$ROOT" "$1" >/dev/null 2>&1 ||
        cannot_look "could not clone this checkout into $1 — every gate case plants in a clone"
    sha=$(git -C "$ROOT" rev-parse --verify -q main 2>/dev/null || git -C "$1" rev-parse HEAD)
    if have=$(git -C "$1" rev-parse --verify -q main 2>/dev/null); then
        [ "$have" = "$sha" ] ||
            cannot_look "the clone in $1 arrived with a local main at ${have} — this checkout's main is ${sha}"
    else
        git -C "$1" branch main "$sha" >/dev/null 2>&1 ||
            cannot_look "could not create a local main in $1"
    fi
}

# THE ONE CLONE, MADE ONCE AND REUSED. A `git clone` of this checkout is the
# single biggest thing this drive does, and five of them was most of its wall.
# The cases that need a real gate are sequential and each one empties the
# drawer first, so one clone is one clone's worth of truth for all of them —
# and `fresh_drawer` is what makes "the drawer this case planted" a fact rather
# than an assumption about what the last case left.
CLONE=""
clone_shared() {
    [ -z "$CLONE" ] || return 0
    CLONE="${WORK}/clone"
    clone_into "$CLONE"
}
#: Set by `fresh_drawer`. A VARIABLE AND NOT A PRINTED PATH, because every
#: caller would read a printed one through `$( )` — a subshell, where the lazy
#: `CLONE` would be set and then thrown away. That is not hypothetical: it made
#: the dry-sequence case run the gate in an empty string and pass its own
#: not-found as a sequence.
DRAWER=""
fresh_drawer() {
    clone_shared
    rm -rf "${CLONE}/scripts/local"
    mkdir -p "${CLONE}/scripts/local/legs"
    DRAWER="${CLONE}/scripts/local/legs"
}

# gate_in <dir> <outfile> <args...> — run the gate in a clone, unpiped, into a
# file. Prints nothing; sets GATE_RC.
GATE_RC=0
gate_in() {
    local dir=$1 out=$2
    shift 2
    GATE_RC=0
    (
        cd "$dir" &&
            DJB_GATE_LEASE_DIR="${WORK}/lease" \
                ./scripts/check.sh "$@"
    ) >"$out" 2>&1 || GATE_RC=$?
}
mkdir -p "${WORK}/lease"

# --- the cases ---------------------------------------------------------------

case_an_absent_drawer_is_byte_identical() {
    # THE NEGATIVE, AND IT IS THE FIRST CASE ON PURPOSE. Every other property
    # here is a thing the drawer ADDS; this one is the promise that a template
    # which ships no drawer pays nothing for the seam. It is a DIFF of two real
    # listings — the checkout's own, which has no `scripts/local/`, against one
    # taken with the reader pointed at an empty directory — because the only
    # honest form of "byte-identical" is a byte comparison.
    CURRENT="an absent drawer leaves the listing byte-identical"
    local a b empty
    a="${WORK}/listing-absent.tsv"
    b="${WORK}/listing-empty.tsv"
    empty="${WORK}/empty-drawer"
    mkdir -p "$empty"
    ./scripts/check.sh --list-legs >"$a" 2>"${WORK}/listing-absent.err" ||
        cannot_look "this checkout's own --list-legs exited non-zero — there is no baseline to compare against"
    (DJB_LOCAL_LEGS_DIR="$empty" ./scripts/check.sh --list-legs) >"$b" 2>&1 ||
        cannot_look "--list-legs over an empty drawer exited non-zero"
    if cmp -s "$a" "$b"; then
        ok "no drawer and an empty drawer print the same listing, byte for byte"
    else
        bad "an empty drawer changed the listing (diff: $(diff "$a" "$b" | awk 'NR <= 3' | tr '\n' ' '))"
    fi
    # A UNIT ROW AND NOT THE WORD. `local_legs` — this drive — is a member of
    # the selftest unit, so the substring is in the baseline and always will
    # be; what must not be there is a UNIT whose name comes from a drawer.
    if awk -F'\t' 'NF && $4 ~ /(^|,)local:/ { found = 1 } END { exit(found ? 0 : 1) }' "$a"; then
        bad "this checkout's listing already names a local: member — the baseline is not a no-drawer tree"
    else
        ok "the baseline listing names no local: member at all"
    fi
}

case_a_declared_leg_joins_the_listing_as_its_own_unit() {
    # THE DISCOVERY ITSELF. One leg in the drawer, and the listing grows one
    # row: the unit the header names, the union of its legs' needs, `0` shards
    # (a product leg is one command and there is no k/N for this gate to hand
    # it), and `local:<name>` as its member.
    CURRENT="a declared leg joins the listing as its own unit"
    local d out row
    d="${WORK}/drawer-listing"
    plant_leg "$d" canary 1
    plant_leg "$d" typecheck 0 "$(printf 'unit: frontend\nneeds: node,network\ntier: fast\n')"
    out="${WORK}/listing-with.tsv"
    (DJB_LOCAL_LEGS_DIR="$d" ./scripts/check.sh --list-legs) >"$out" 2>&1 ||
        cannot_look "--list-legs over a two-leg drawer exited non-zero (see ${out})"
    row=$(awk -F'\t' '$1 == "local" { print }' "$out")
    if [ "$row" = "$(printf 'local\tnone\t0\tlocal:canary')" ]; then
        ok "the drawer's own unit is 'local  none  0  local:canary'"
    else
        bad "the local row is '${row}'"
    fi
    row=$(awk -F'\t' '$1 == "frontend" { print }' "$out")
    if [ "$row" = "$(printf 'frontend\tnetwork,node\t0\tlocal:typecheck')" ]; then
        ok "a leg naming a NEW unit makes one, carrying its own declared needs"
    else
        bad "the frontend row is '${row}'"
    fi
}

case_the_full_gate_announces_the_drawer_after_the_house_rules() {
    # THE POSITION IS THE PROPERTY. A product's leg runs AFTER the template's
    # own enforcement, because a red house rule is this system's verdict about
    # the tree and the two must not race for which red a reader sees first. The
    # sequence is read off a DRY run — every leg announced, no body run — in a
    # clone, which is the same instrument `test_list_legs.sh` uses and for the
    # same reason: a static reading of the file is a second implementation of
    # its control flow.
    CURRENT="the full gate announces local-legs after full-house-rules"
    local clone out seq
    fresh_drawer
    plant_leg "$DRAWER" canary 1
    clone="$CLONE"
    out="${WORK}/dry-full.out"
    (
        cd "$clone" &&
            DJB_GATE_LEGS_DRY=1 \
                DJB_GATE_LEASE_DIR="${WORK}/lease" \
                DJB_GATE_SANCTION="test_local_legs: the dry sequence — every leg announced, no body run" \
                ./scripts/check.sh
    ) >"$out" 2>&1 ||
        cannot_look "a dry full gate in the clone exited non-zero (see ${out})"
    seq=$(sed -n 's/^  leg: \([a-z0-9-]*\) (DJB_GATE_LEGS_DRY.*/\1/p' "$out" | tr '\n' ' ')
    case "$seq" in
    *"full-house-rules local-legs "*)
        ok "the dry sequence ends '… full-house-rules local-legs'"
        ;;
    *)
        bad "the dry sequence does not put local-legs after full-house-rules: '${seq}'"
        ;;
    esac
    if grep -q '^FULL_LEGS=.*local:canary' "${clone}/scripts/check.sh"; then
        bad "the drawer was written into the clone's FULL_LEGS assignment — it must grow at RUNTIME, never in the file"
    else
        ok "the clone's FULL_LEGS assignment is untouched — the drawer grows the string at runtime"
    fi
}

case_a_red_local_leg_reds_the_gate_naming_it() {
    # A PRODUCT LEG THAT EXITS 1 REDS THE GATE LIKE ANY LEG, and the name on the
    # failing line is `local:<name>` — not the runner's, and not a file path.
    # The unit is run rather than the whole gate because a unit IS the gate's
    # own partition of itself: `--leg local` takes no lease, no lock and no
    # slot, and it announces and runs exactly the drawer.
    CURRENT="a local leg that exits 1 reds the gate, naming local:<name>"
    local clone out
    fresh_drawer
    plant_leg "$DRAWER" canary 1
    clone="$CLONE"
    out="${WORK}/leg-local-red.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "1" ]; then
        ok "--leg local exited 1"
    else
        bad "--leg local exited ${GATE_RC} (see ${out})"
    fi
    if grep -q 'local:canary: exit 1' "$out"; then
        ok "the failing line names local:canary"
    else
        bad "no 'local:canary: exit 1' line in the transcript (see ${out})"
    fi
    if grep -q 'canary: this is a planted product leg' "$out"; then
        ok "the red leg's own output is replayed"
    else
        bad "the red leg's output was swallowed"
    fi
}

case_the_verdict_row_names_each_local_leg() {
    # THE ROW IS WHAT A BANK VOUCHES WITH, and a leg the row does not name is a
    # leg every reuse silently drops. `gate_full_legs` is the one function both
    # sides of that comparison read — the writer (`gate_ledger_record`) and the
    # reader (`gate_ledger_lookup`) — and it now derives from the LISTING rather
    # than from a `sed` over the `FULL_LEGS=` text, because the text is not the
    # leg set any more.
    CURRENT="the verdict row's leg set is derived from the listing"
    local d out
    d="${WORK}/drawer-row"
    plant_leg "$d" canary 0
    out=$(
        set +e
        cd "$ROOT" || exit 2
        DJB_LOCAL_LEGS_DIR="$d" bash -c '. scripts/gate_ledger.sh; gate_full_legs'
    )
    case ",${out}," in
    *",local:canary,"*) ok "gate_full_legs names local:canary when the drawer holds it" ;;
    *) bad "gate_full_legs did not name local:canary (got '${out}')" ;;
    esac
    out=$(
        set +e
        cd "$ROOT" || exit 2
        bash -c '. scripts/gate_ledger.sh; gate_full_legs'
    )
    case ",${out}," in
    *",local:"*) bad "gate_full_legs names a local leg with no drawer in the tree (got '${out}')" ;;
    *",full-house-rules,"*) ok "with no drawer it is the template's own leg set and nothing else" ;;
    *) bad "gate_full_legs read empty with no drawer — the comparison would be switched off" ;;
    esac
    # AND WITH NO DRAWER IT COSTS NO GATE. This function sits on the pre-push
    # hook's consult path, whose whole point is that honouring a banked row
    # costs a lookup and not a gate run; a subprocess here on every template
    # checkout would be a cost the drawer's absence is supposed to spare it.
    if [ "$out" = "$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh | sed -n 1p)" ]; then
        ok "with no drawer the answer is the assignment itself — no listing is run at all"
    else
        bad "with no drawer the answer is not check.sh's own FULL_LEGS line"
    fi
    out=$(
        set +e
        cd "$ROOT" || exit 2
        DJB_LOCAL_LEGS_DIR="$d" bash -c '. scripts/gate_ledger.sh; gate_full_legs'
    )
    if [ "$out" = "$(sed -n 's/^FULL_LEGS=//p' scripts/check.sh | sed -n 1p)" ]; then
        bad "with a drawer the answer is still the text constant — the listing is not being read"
    else
        ok "with a drawer the answer comes from the listing, not from the text constant"
    fi
}

case_tier_decides_which_modes_run_a_leg() {
    # THE TIER IS THE CHEAPEST MODE THAT RUNS IT, AND EVERY MODE ABOVE RUNS IT
    # TOO. Two plants, one `loop` and one `full`, read through
    # `always_on__legs` — the derivation the `--loop` always-on leg selects its
    # members from — so the answer comes from the reader the loop actually uses
    # and not from a second opinion about it.
    CURRENT="tier decides which modes run a leg"
    local d out
    d="${WORK}/drawer-tier"
    plant_leg "$d" cheap 0 "$(printf 'tier: loop\n')"
    plant_leg "$d" dear 0 "$(printf 'tier: full\n')"
    plant_leg "$d" early 0 "$(printf 'tier: fast\n')"
    out=$(DJB_LOCAL_LEGS_DIR="$d" fence_run 'local_legs_scan >/dev/null 2>&1; for t in fast loop full; do printf "%s: %s\n" "$t" "$(local_legs_tier_any "$t")"; done')
    if [ "$(printf '%s\n' "$out" | sed -n 's/^fast: //p')" = "local:early" ]; then
        ok "--fast runs the fast-tier leg alone"
    else
        bad "the fast tier selected '$(printf '%s\n' "$out" | sed -n 's/^fast: //p')'"
    fi
    if [ "$(printf '%s\n' "$out" | sed -n 's/^loop: //p')" = "local:cheap local:early" ]; then
        ok "--loop runs the loop-tier and fast-tier legs and not the full-tier one"
    else
        bad "the loop tier selected '$(printf '%s\n' "$out" | sed -n 's/^loop: //p')'"
    fi
    if [ "$(printf '%s\n' "$out" | sed -n 's/^full: //p')" = "local:cheap local:dear local:early" ]; then
        ok "the full gate runs all three"
    else
        bad "the full tier selected '$(printf '%s\n' "$out" | sed -n 's/^full: //p')'"
    fi
    out=$(DJB_LOCAL_LEGS_DIR="$d" fence_run 'local_legs_scan >/dev/null 2>&1; LOCAL_LEGS_TABLE="$LOCAL_LEGS_TABLE" awk -F"\t" "NF { print (\$4 == \"full\" ? \"full\" : \"loop\"), \"local:\" \$1 }" <<<"$LOCAL_LEGS_TABLE"')
    # ONE READER THAT RUNS TO EOF, and it is not style. A quiet grep at the
    # tail of a pipeline exits on its first match and SIGPIPEs its producer;
    # under `pipefail` — which this drive runs under — that is a NONZERO
    # pipeline, and over 64 KiB (one pipe buffer) it reports the wrong answer
    # on every run. `awk` consumes its whole input and decides at END.
    if printf '%s\n' "$out" | awk '
        $0 == "loop local:cheap" { a = 1 }
        $0 == "full local:dear" { b = 1 }
        END { exit(a && b ? 0 : 1) }
    '; then
        ok "the always-on derivation lists 'loop local:cheap' and 'full local:dear'"
    else
        bad "the always-on derivation printed '${out}'"
    fi
}

case_touches_skips_under_a_narrowed_mode_and_never_under_full() {
    # THE N820a RULE, ONE DRAWER OVER. A narrowed mode is allowed to skip a leg
    # whose declared paths nothing in the active scope touched — and it says so on a
    # line, because a leg that went quiet without one is a leg nobody misses.
    # The FULL gate is not allowed to: it is the run every verdict rests on.
    CURRENT="touches skips under a narrowed mode and never under full"
    local d out clone
    d="${WORK}/drawer-touch"
    plant_leg "$d" fescan 0 "$(printf 'tier: loop\ntouches: frontend\n')"
    out=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_CHANGED_FILES="apps/nowhere/nothing.py" fence_run 'local_legs_scan >/dev/null 2>&1; local_legs_touched "$(local_legs_field local:fescan 6)" "$(local_legs_changed_files)"; echo "rc=$?"')
    if [ "$out" = "rc=1" ]; then
        ok "a changed set with nothing under frontend/ does not touch the leg"
    else
        bad "the touch reader answered '${out}' for a non-matching changed set"
    fi
    out=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_CHANGED_FILES="frontend/app/page.tsx" fence_run 'local_legs_scan >/dev/null 2>&1; local_legs_touched "$(local_legs_field local:fescan 6)" "$(local_legs_changed_files)"; echo "rc=$?"')
    if [ "$out" = "rc=0" ]; then
        ok "a changed file under frontend/ touches it"
    else
        bad "the touch reader answered '${out}' for a matching changed set"
    fi
    out=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_CHANGED_FILES="" fence_run 'local_legs_scan >/dev/null 2>&1; local_legs_touched "$(local_legs_field local:fescan 6)" "$(local_legs_changed_files)"; echo "rc=$?"')
    if [ "$out" = "rc=2" ]; then
        ok "a changed set that could not be read is could-not-look, so the leg runs"
    else
        bad "an unreadable changed set answered '${out}' — skipping on one would be silent"
    fi
    fresh_drawer
    plant_leg "$DRAWER" fescan 0 "$(printf 'tier: loop\ntouches: frontend\n')"
    clone="$CLONE"
    out="${WORK}/leg-touch.out"
    gate_in "$clone" "$out" --leg local
    if grep -q 'local:fescan: exit 0' "$out"; then
        ok "--leg local runs it whatever it touches"
    else
        bad "--leg local skipped a leg by touches (see ${out})"
    fi
    if grep -q 'SKIPPED' "$out"; then
        bad "--leg local printed a SKIPPED line — a whole unit may not narrow itself"
    else
        ok "--leg local printed no SKIPPED line"
    fi
}

case_two_means_says_what_an_exit_2_from_a_product_tool_means() {
    # EXIT 2 IN THIS GATE MEANS ENFORCEMENT IS BROKEN AND OUTRANKS A PASS. A
    # product's tool may spell an ordinary finding 2, so the leg DECLARES which
    # it is — guessing either way is a red that means the wrong thing.
    CURRENT="two-means says what an exit 2 from a product tool means"
    local clone out
    fresh_drawer
    plant_leg "$DRAWER" broke 2 "$(printf 'two-means: broken\n')"
    clone="$CLONE"
    out="${WORK}/two-broken.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "2" ] && grep -q 'COULD NOT LOOK' "$out"; then
        ok "two-means: broken makes an exit 2 a could-not-look, and the unit exits 2"
    else
        bad "a broken-declaring leg exiting 2 gave rc=${GATE_RC} (see ${out})"
    fi
    rm -f "${clone}/scripts/local/legs/broke.sh"
    plant_leg "${clone}/scripts/local/legs" finds 2 "$(printf 'two-means: finding\n')"
    out="${WORK}/two-finding.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "1" ] && grep -q 'LOCAL LEGS RED' "$out"; then
        ok "two-means: finding makes the same exit 2 an ordinary red, and the unit exits 1"
    else
        bad "a finding-declaring leg exiting 2 gave rc=${GATE_RC} (see ${out})"
    fi
    # AND THE OTHER HALF OF THE DECLARED GRAMMAR, which is the first
    # consumer's own: a tool that reserves 2 for findings and exited PAST it
    # did not do the job, so 3 or above is could-not-look and never a red
    # about the tree.
    rm -f "${clone}/scripts/local/legs/finds.sh"
    plant_leg "${clone}/scripts/local/legs" wrecked 4 "$(printf 'two-means: finding\n')"
    out="${WORK}/two-finding-4.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "2" ] && grep -q 'COULD NOT LOOK' "$out"; then
        ok "two-means: finding reads an exit 4 as could-not-look — past its own findings code, the tool failed"
    else
        bad "a finding-declaring leg exiting 4 gave rc=${GATE_RC} (see ${out})"
    fi
    # AND `broken` KEEPS ITS ORDINARY REDS ORDINARY.
    rm -f "${clone}/scripts/local/legs/wrecked.sh"
    plant_leg "${clone}/scripts/local/legs" plainred 1 "$(printf 'two-means: broken\n')"
    out="${WORK}/two-broken-1.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "1" ] && grep -q 'LOCAL LEGS RED' "$out"; then
        ok "two-means: broken still reads an exit 1 as an ordinary red"
    else
        bad "a broken-declaring leg exiting 1 gave rc=${GATE_RC} (see ${out})"
    fi
}

case_inputs_and_env_are_folded_into_the_reuse_key() {
    # A PRODUCT LEG'S VERDICT IS REUSED ON THE SAME TERMS THE TEMPLATE'S DRIVES
    # ARE. The key is the leg's own bytes, the CONTENT of its declared
    # `inputs:`, and the VALUES of its declared `env:` names — so a leg whose
    # input moved re-runs and one whose inputs are all still there does not.
    # The first consumer wrote 140 lines into `gate_ledger.sh` to get this by
    # hand; it is a header field now.
    CURRENT="inputs and env are folded into the reuse key"
    local d k1 k2 k3
    d="${WORK}/drawer-key"
    plant_leg "$d" keyed 0 "$(printf 'inputs: scripts/gate_ledger.sh\nenv: DJB_LOCAL_LEGS_PROBE\n')"
    k1=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_PROBE=a fence_run '. scripts/gate_ledger.sh; local_legs_scan >/dev/null 2>&1; local_leg_key local:keyed' | awk '{print $2}')
    k2=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_PROBE=a fence_run '. scripts/gate_ledger.sh; local_legs_scan >/dev/null 2>&1; local_leg_key local:keyed' | awk '{print $2}')
    k3=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_PROBE=b fence_run '. scripts/gate_ledger.sh; local_legs_scan >/dev/null 2>&1; local_leg_key local:keyed' | awk '{print $2}')
    if [ -n "$k1" ] && [ "$k1" = "$k2" ]; then
        ok "the key is stable across two reads of the same leg and the same environment"
    else
        bad "two reads gave '${k1}' and '${k2}'"
    fi
    if [ -n "$k3" ] && [ "$k1" != "$k3" ]; then
        ok "a declared env name whose VALUE moved moves the key"
    else
        bad "the key did not move when a declared env value moved ('${k1}' vs '${k3}')"
    fi
    k2=$(DJB_LOCAL_LEGS_DIR="$d" DJB_LOCAL_LEGS_PROBE=a fence_run 'sed -i.bak "s/^exit 0/exit 0 # a byte/" '"${d}"'/keyed.sh; . scripts/gate_ledger.sh; local_legs_scan >/dev/null 2>&1; local_leg_key local:keyed' | awk '{print $2}')
    if [ -n "$k2" ] && [ "$k1" != "$k2" ]; then
        ok "a byte in the leg itself moves the key"
    else
        bad "the key did not move when the leg's own bytes moved"
    fi
    k2=$(DJB_LOCAL_LEGS_DIR="$d" fence_run '. scripts/gate_ledger.sh; local_legs_scan >/dev/null 2>&1; local_leg_key local:keyed' | awk 'NR == 1')
    case "$k2" in
    "ok drive-v1:"*) ok "the key is printed in drive_key's own grammar, so one reader parses both" ;;
    *) bad "the key line is '${k2}'" ;;
    esac
}

case_a_new_local_unit_provisions_once_before_its_legs() {
    # ONE `_provision-<unit>.sh` PER LOCAL UNIT, RUN ONCE. A unit with organs of
    # its own (`node`, `network`) needs something brought up before its legs,
    # and it is the one thing a leg may not do for itself: N legs would each pay
    # it. The underscore is what keeps the provisioner out of the leg
    # population without a second list saying so.
    CURRENT="a local unit provisions once before its legs"
    local clone d out
    fresh_drawer
    d="$DRAWER"
    clone="$CLONE"
    plant_leg "$d" one 0
    plant_leg "$d" two 0
    printf '#!/usr/bin/env bash\necho "PROVISIONED local"\nexit 0\n' >"${d}/_provision-local.sh"
    chmod +x "${d}/_provision-local.sh"
    out="${WORK}/prov.out"
    gate_in "$clone" "$out" --leg local
    if [ "$(grep -c 'PROVISIONED local' "$out")" = "1" ]; then
        ok "the provisioner ran exactly once for two legs of one unit"
    else
        bad "the provisioner ran $(grep -c 'PROVISIONED local' "$out") time(s) (see ${out})"
    fi
    if grep -q 'local:_provision-local' "$out"; then
        bad "the provisioner was treated as a leg"
    else
        ok "the provisioner is not a leg"
    fi
    printf '#!/usr/bin/env bash\nexit 3\n' >"${d}/_provision-local.sh"
    out="${WORK}/prov-red.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "2" ] && grep -q 'did not provision' "$out"; then
        ok "a provisioner that failed makes its unit's legs could-not-look, never a pass"
    else
        bad "a failed provisioner gave rc=${GATE_RC} (see ${out})"
    fi
}

case_a_failed_provisioner_stops_every_leg_of_its_unit() {
    # THE ONCE-ONLY MARK IS A PROMISE ABOUT SUCCESS, AND IT WAS MADE ABOUT THE
    # ATTEMPT. Marked before the run, a failed provisioner made only the FIRST
    # leg of its unit could-not-look and every later leg of that unit RAN —
    # unprovisioned, against organs nothing had brought up, reporting whatever
    # such a run reports. Silent from every direction: the unit still exits 2,
    # so the only visible trace is a leg saying something about a world that
    # was never built.
    CURRENT="a failed provisioner stops EVERY leg of its unit, not just the first"
    local clone d out
    fresh_drawer
    d="$DRAWER"
    clone="$CLONE"
    plant_leg "$d" one 0
    plant_leg "$d" two 0
    plant_leg "$d" three 0
    printf '#!/usr/bin/env bash\necho "PROVISION ATTEMPTED"\nexit 3\n' >"${d}/_provision-local.sh"
    chmod +x "${d}/_provision-local.sh"
    out="${WORK}/prov-all.out"
    gate_in "$clone" "$out" --leg local
    if [ "$GATE_RC" = "2" ]; then
        ok "the unit exits 2"
    else
        bad "the unit exited ${GATE_RC} (see ${out})"
    fi
    if [ "$(grep -c 'could not look — unit' "$out")" = "3" ]; then
        ok "all three legs are could-not-look, not one"
    else
        bad "$(grep -c 'could not look — unit' "$out") of 3 legs were could-not-look (see ${out})"
    fi
    if grep -q ': exit 0 (' "$out"; then
        bad "a leg of an unprovisioned unit RAN — that is the defect this case exists for"
    else
        ok "no leg of the unit ran at all"
    fi
    if [ "$(grep -c 'PROVISION ATTEMPTED' "$out")" = "3" ]; then
        ok "the provisioner was re-attempted per leg — a failure is a state every leg has to meet"
    else
        bad "the failed provisioner was attempted $(grep -c 'PROVISION ATTEMPTED' "$out") time(s)"
    fi
}

case_the_loop_half_provisions_its_unit_too() {
    # ONE UNIT, TWO ANSWERS, AND THE CHEAP ONE WAS WRONG. `always_on__run` is
    # the shared member runner and knows nothing about units, so a loop-tier
    # product leg ran UNPROVISIONED under every `--loop` while the full gate
    # brought its organs up — a green loop and a red bank over one tree, which
    # is the class the always-on leg exists to close rather than to open.
    #
    # DRIVEN THROUGH THE LEG'S OWN SELECTION, not through a `--loop`: a
    # `--loop` refuses on any machine that is not a verifier box, and the
    # property here is that the loop half calls the provisioner at all.
    CURRENT="the --loop half provisions its unit before running a loop-tier leg"
    # CAPTURED ONCE, THEN TESTED TWICE, for the reason above and for a second
    # one: two `grep -A24` scans of a 8,000-line file to ask two questions of
    # the same twenty-four lines is two readings that can disagree.
    local loophalf
    loophalf=$(grep -A24 'for name in \$locals; do' scripts/check.sh) || loophalf=""
    if [ -z "$loophalf" ]; then
        cannot_look "scripts/check.sh has no 'for name in \$locals' loop — the always-on leg's local half is not there to ask about"
    fi
    case "$loophalf" in
    *local_legs_provision*)
        ok "the always-on leg's local half calls local_legs_provision before always_on__run"
        ;;
    *)
        bad "the always-on leg's local half runs a member with no provisioning at all"
        ;;
    esac
    case "$loophalf" in
    *'ALWAYS_ON_CANNOT=$((ALWAYS_ON_CANNOT + 1))'*)
        ok "and a unit that did not provision is counted could-not-look there, never skipped"
        ;;
    *)
        bad "a unit that did not provision is not counted in the loop half"
        ;;
    esac
    # AND THE MARK IS THE SHARED STATE BOTH HALVES READ, so a unit provisioned
    # for the full path is not provisioned twice and one provisioned in the
    # loop half is not re-run by a later member.
    local d out
    d="${WORK}/drawer-prov-once"
    mkdir -p "$d"
    plant_leg "$d" a 0
    plant_leg "$d" b 0
    printf '#!/usr/bin/env bash\necho ONCE\nexit 0\n' >"${d}/_provision-local.sh"
    chmod +x "${d}/_provision-local.sh"
    out=$(DJB_LOCAL_LEGS_DIR="$d" fence_run 'local_legs_scan >/dev/null 2>&1; local_legs_provision local; local_legs_provision local; local_legs_provision local')
    if [ "$(printf '%s\n' "$out" | grep -c ONCE)" = "1" ]; then
        ok "three calls for one successfully provisioned unit run it once"
    else
        bad "a successful provisioner ran $(printf '%s\n' "$out" | grep -c ONCE) time(s) across three calls"
    fi
}

case_a_malformed_leg_is_exit_2_naming_the_file_and_the_field() {
    # BROKEN IS EXIT 2 AT THE LISTING, AND IT NAMES BOTH. A silently ignored
    # leg is the one failure this drawer must never have: the product would
    # believe its gate ran something it did not.
    #
    # TWO SHAPES THROUGH THE REAL LISTING AND THE REST THROUGH ITS READER, and
    # the split is a wall-clock one with a stated cost. Every `--list-legs` is
    # a whole shell startup of a 7,600-line gate (~2.5 s here), so eleven of
    # them is most of this drive. The two below prove the refusal reaches the
    # DOOR — that `--list-legs` exits 2 and prints the sentence — and the rest
    # prove the reader behind that door refuses each shape; the door has one
    # reader and `local_legs_scan` is it, so what the fence cases cannot see is
    # a door that stopped consulting it, which is exactly what the two gate
    # cases are for.
    CURRENT="a malformed leg is exit 2 at the listing, naming the file and the field"
    local d out rc want
    run_listing() {
        out="${WORK}/refuse-$1.err"
        rc=0
        (DJB_LOCAL_LEGS_DIR="$2" ./scripts/check.sh --list-legs) >/dev/null 2>"$out" || rc=$?
    }
    # run_scan <tag> <dir> — the same question of the reader the listing calls.
    run_scan() {
        out="${WORK}/scan-$1.err"
        rc=0
        (DJB_LOCAL_LEGS_DIR="$2" fence_run 'local_legs_scan') >/dev/null 2>"$out" || rc=$?
    }

    d="${WORK}/ref-nox"
    plant_leg "$d" canary 0
    chmod -x "${d}/canary.sh"
    run_listing nox "$d"
    if [ "$rc" = "2" ] && grep -q 'not executable' "$out" && grep -q 'canary.sh' "$out"; then
        ok "THROUGH THE LISTING: a leg with no +x is exit 2 naming the file"
    else
        bad "a non-executable leg gave rc=${rc} at the listing (see ${out})"
    fi

    d="${WORK}/ref-collide"
    plant_leg "$d" ruff 0
    run_listing collide "$d"
    if [ "$rc" = "2" ] && grep -q "already a leg or a drive" "$out"; then
        ok "THROUGH THE LISTING: a name colliding with a leg or a drive this gate has is exit 2"
    else
        bad "a colliding name gave rc=${rc} at the listing (see ${out})"
    fi

    d="${WORK}/ref-noneeds"
    plant_leg "$d" canary 0
    sed '/^# needs:/d' "${d}/canary.sh" >"${d}/canary.new" && mv "${d}/canary.new" "${d}/canary.sh" && chmod +x "${d}/canary.sh"
    run_scan noneeds "$d"
    if [ "$rc" = "2" ] && grep -q "declares no 'needs:'" "$out"; then
        ok "a missing required field is exit 2 naming the field"
    else
        bad "a header with no needs: gave rc=${rc} (see ${out})"
    fi

    for want in unit tier two-means; do
        d="${WORK}/ref-no-${want}"
        plant_leg "$d" canary 0
        sed "/^# ${want}:/d" "${d}/canary.sh" >"${d}/canary.new" && mv "${d}/canary.new" "${d}/canary.sh" && chmod +x "${d}/canary.sh"
        run_scan "no-${want}" "$d"
        if [ "$rc" = "2" ] && grep -q "declares no '${want}:'" "$out"; then
            ok "a header with no ${want}: is exit 2 naming it"
        else
            bad "a header with no ${want}: gave rc=${rc} (see ${out})"
        fi
    done

    d="${WORK}/ref-v2"
    plant_leg "$d" canary 0
    sed 's/leg v1/leg v2/' "${d}/canary.sh" >"${d}/canary.new" && mv "${d}/canary.new" "${d}/canary.sh" && chmod +x "${d}/canary.sh"
    run_scan v2 "$d"
    if [ "$rc" = "2" ] && grep -q "version 'v2'" "$out"; then
        ok "an unknown header version is exit 2 naming the version"
    else
        bad "a v2 header gave rc=${rc} (see ${out})"
    fi

    d="${WORK}/ref-unit"
    plant_leg "$d" canary 0 "$(printf 'unit: selftest\n')"
    run_scan unit "$d"
    if [ "$rc" = "2" ] && grep -q "unit: 'selftest' is a unit THIS GATE declares" "$out"; then
        ok "a unit: naming one of this gate's own units is exit 2"
    else
        bad "unit: selftest gave rc=${rc} (see ${out})"
    fi

    d="${WORK}/ref-field"
    plant_leg "$d" canary 0
    sed 's/^# tier: full/# tier: full\n# colour: blue/' "${d}/canary.sh" >"${d}/canary.new" && mv "${d}/canary.new" "${d}/canary.sh" && chmod +x "${d}/canary.sh"
    run_scan field "$d"
    if [ "$rc" = "2" ] && grep -q "unknown header field 'colour'" "$out"; then
        ok "an unknown header field is exit 2 naming it"
    else
        bad "an unknown field gave rc=${rc} (see ${out})"
    fi

    d="${WORK}/ref-tier"
    plant_leg "$d" canary 0 "$(printf 'tier: sometimes\n')"
    run_scan tier "$d"
    if [ "$rc" = "2" ] && grep -q "tier: 'sometimes'" "$out"; then
        ok "an unknown tier is exit 2 naming it"
    else
        bad "tier: sometimes gave rc=${rc} (see ${out})"
    fi

    d="${WORK}/ref-two"
    plant_leg "$d" canary 0 "$(printf 'two-means: maybe\n')"
    run_scan two "$d"
    if [ "$rc" = "2" ] && grep -q "two-means: 'maybe'" "$out"; then
        ok "an unknown two-means is exit 2 naming it"
    else
        bad "two-means: maybe gave rc=${rc} (see ${out})"
    fi

    d="${WORK}/ref-nohdr"
    mkdir -p "$d"
    printf '#!/usr/bin/env bash\nexit 0\n' >"${d}/canary.sh"
    chmod +x "${d}/canary.sh"
    run_scan nohdr "$d"
    if [ "$rc" = "2" ] && grep -q 'carries no' "$out"; then
        ok "a leg with no header at all is exit 2"
    else
        bad "a headerless leg gave rc=${rc} (see ${out})"
    fi

    d="${WORK}/ref-twice"
    plant_leg "$d" canary 0
    sed 's/^# tier: full/# tier: full\n# tier: loop/' "${d}/canary.sh" >"${d}/canary.new" && mv "${d}/canary.new" "${d}/canary.sh" && chmod +x "${d}/canary.sh"
    run_scan twice "$d"
    if [ "$rc" = "2" ] && grep -q "declared twice" "$out"; then
        ok "a field declared twice is exit 2 — a field with two values has none"
    else
        bad "a doubled field gave rc=${rc} (see ${out})"
    fi
}

case_cis_matrix_takes_the_unit_with_no_yaml_edit() {
    # CI ADDS A COUNT AND NEVER A NAME, and this is the case that proves the
    # drawer needs no `ci.yml` edit at all. The derive block is EXTRACTED from
    # the workflow and run over a planted listing, so what is being driven is
    # the YAML this repository actually ships and not a transcription of it.
    CURRENT="CI's matrix takes the local unit with no ci.yml edit"
    command -v jq >/dev/null 2>&1 || cannot_look "no jq on PATH — CI's own derive block is jq, so there is nothing to run"
    local d listing derive got
    d="${WORK}/drawer-ci"
    plant_leg "$d" canary 0
    plant_leg "$d" typecheck 0 "$(printf 'unit: frontend\nneeds: node\n')"
    listing="${WORK}/units.tsv"
    (DJB_LOCAL_LEGS_DIR="$d" ./scripts/check.sh --list-legs) >"$listing" 2>&1 ||
        cannot_look "--list-legs over the CI drawer exited non-zero"
    derive="${WORK}/derive.sh"
    awk '
        /\.\/scripts\/check\.sh --list-legs > units\.tsv/ { on = 1; next }
        /echo "matrix=\$matrix"/ { on = 0 }
        on { sub(/^          /, ""); print }
    ' .github/workflows/ci.yml >"$derive"
    [ -s "$derive" ] ||
        cannot_look ".github/workflows/ci.yml carries no derive block between its --list-legs line and its matrix output — the case has no subject"
    grep -q 'read -r unit needs shards' "$derive" ||
        cannot_look "the extracted block does not read the listing's columns — it is not the derive block"
    got=$(
        cd "$WORK" && SHARDS=3 bash -c "set -euo pipefail; matrix='[]'; $(cat "$derive"); printf '%s' \"\$matrix\" | jq -c '.[] | select(.unit==\"local\" or .unit==\"frontend\")'"
    )
    got=$(printf '%s\n' "$got" | grep '^{')
    if [ "$(printf '%s\n' "$got" | grep -c .)" = "2" ]; then
        ok "the workflow's own derive block emitted one row per local unit"
    else
        bad "the derive block emitted '${got}'"
    fi
    case "$got" in
    *'"unit":"frontend","needs":"node","shard":""'*)
        ok "the row carries the unit's declared needs and no shard"
        ;;
    *)
        bad "the frontend row is '$(printf '%s\n' "$got" | grep frontend)'"
        ;;
    esac
    # THE MATRIX MUST DERIVE THE DRAWER, NEVER BE TOLD ABOUT IT — and since the
    # EP3 amendment (P21 team F § 7c) `ci.yml` carries ONE optional job that
    # DOES name a drawer: `local`, which runs `scripts/local/ci/*.sh` behind
    # the verdict. That job is not the matrix and reaches no leg; a product's
    # legs still arrive through the listing alone. So the tooth narrows from
    # "the file never says it" to the two things it was always about: the
    # derive block does not name it, and nothing OUTSIDE that one optional job
    # does either.
    if grep -q 'scripts/local' "$derive"; then
        bad "the workflow's derive block names the drawer — the matrix must derive it, never be told about it"
    else
        ok "the derive block never names the drawer"
    fi
    local named_outside
    named_outside=$(awk '
        /^  local:$/ { inlocal = 1; next }
        inlocal && /^  [a-z]/ { inlocal = 0 }
        !inlocal && /scripts\/local/ { print FILENAME ":" NR }
    ' .github/workflows/ci.yml)
    if [ -n "$named_outside" ]; then
        bad "ci.yml names the drawer outside its one optional local job: $(printf '%s' "$named_outside" | tr '\n' ' ')"
    else
        ok "ci.yml names the drawer nowhere but inside its one optional local job"
    fi
}

case_the_bank_plan_takes_a_local_unit_from_the_listing() {
    # THE BANK PLANS FROM THE LISTING AND FROM NOTHING ELSE, so a product's unit
    # reaches a box with no change to `pm_push.sh`. The function is extracted
    # and driven over a planted listing rather than by running a bank: a bank is
    # nine boxes and half an hour, and what is being asked here is arithmetic.
    CURRENT="the bank plan takes a local unit from the listing"
    local fn listing got need
    fn="${WORK}/plan.sh"
    # TWO FUNCTIONS, BECAUSE THE PLAN SPREADS OVER A ZONE RING. `bank_boxes_plan`
    # gained a fourth argument on main (`listing n passes zones`) and calls
    # `bank_boxes_zone_at` for every row's `az` column; extracting the planner
    # alone made this case exit 2 on "the zone ring is empty" and say nothing
    # about the drawer at all.
    awk '
        /^bank_boxes_plan\(\) \{$/ { on = 1 }
        /^bank_boxes_zone_at\(\) \{$/ { on = 1 }
        on { print }
        on && /^\}$/ { on = 0 }
    ' scripts/pm_push.sh >"$fn"
    [ -s "$fn" ] || cannot_look "scripts/pm_push.sh defines no bank_boxes_plan — the plan this case is about is not there"
    grep -q '^bank_boxes_zone_at() {' "$fn" ||
        cannot_look "scripts/pm_push.sh defines no bank_boxes_zone_at — the plan's zone column has no reader"
    #: A DRIVE-LOCAL RING OF THREE, the shape a real bank is handed. Its
    #: VALUES decide nothing here — what this case is about is whether a
    #: product's unit reaches the plan at all — but a plan with nowhere to
    #: spread to refuses before it ever reads the listing.
    local ring="us-east-1a us-east-1b us-east-1c"
    listing="${WORK}/plan-units.tsv"
    {
        printf 'static\tdb\t0\truff,mypy\n'
        printf 'supply-chain\tnetwork\t0\tsupply-chain\n'
        printf 'pytest-x2\tdb\tN-capable\tpytest-x2\n'
        printf 'selftest\tdb\tN-capable\tselftest\n'
        printf 'full-house-rules\tnone\t0\tfull-house-rules\n'
        printf 'local\tnone\t0\tlocal:canary\n'
    } >"$listing"
    got=$(bash -c "BANK_SUITE_LEG=pytest-x2; $(cat "$fn"); bank_boxes_plan '$listing' 8 2 '$ring'" 2>&1) || {
        bad "bank_boxes_plan refused the listing with a local unit: ${got}"
        return 0
    }
    local localrow
    localrow=$(printf '%s\n' "$got" | awk -F'\t' '$1 == "local" && $2 == "local"')
    if [ -n "$localrow" ]; then
        ok "the plan gives the local unit a box of its own, unsharded"
    else
        bad "the plan has no local row: $(printf '%s' "$got" | tr '\n' '|')"
    fi
    need=$(bash -c "BANK_SUITE_LEG=pytest-x2; $(cat "$fn"); bank_boxes_plan '$listing' 5 2 '$ring'" 2>&1 || true)
    case "$need" in
    *"this gate declares 6 units"*) ok "the floor of boxes is derived from the listing and counts the product's unit" ;;
    *) bad "the floor refusal did not count the local unit: $(printf '%s' "$need" | tr '\n' '|' | cut -c1-160)" ;;
    esac
}

case_the_drawer_is_in_the_measured_trees_declaration_sources() {
    # A LOCAL DERIVER MAY DECLARE ITS OWN WRITES. `GATE_TREE_DECL_SOURCES` is
    # where a deriver is ALLOWED to put a `derived-tree-paths` block, and a
    # product's drawer has exactly the same claim on that as a template script.
    # Two levels and not a `**`: bash 3.2 has no globstar, so a `**` would be
    # one literal `*` wearing two — matching less than it looks like it does,
    # which is the silent direction.
    CURRENT="the product drawers are in GATE_TREE_DECL_SOURCES"
    local got
    got=$(bash -c '. scripts/gate_ledger.sh; printf "%s" "$GATE_TREE_DECL_SOURCES"')
    case " $got " in
    *" scripts/local/*/*.sh "*) ok "a declaration under scripts/local/<drawer>/ is scanned" ;;
    *) bad "GATE_TREE_DECL_SOURCES is '${got}'" ;;
    esac
    case " $got " in
    *" scripts/local/*.sh "*) ok "a declaration directly under scripts/local/ is scanned" ;;
    *) bad "GATE_TREE_DECL_SOURCES is '${got}'" ;;
    esac
    case "$got" in
    *'**'*) bad "GATE_TREE_DECL_SOURCES carries a '**', which bash 3.2 reads as one '*'" ;;
    *) ok "no '**' in the glob list" ;;
    esac
}

echo "test_local_legs: the product-leg drawer (scripts/local/legs/)"
echo

run_case case_an_absent_drawer_is_byte_identical
run_case case_a_declared_leg_joins_the_listing_as_its_own_unit
run_case case_the_full_gate_announces_the_drawer_after_the_house_rules
run_case case_a_red_local_leg_reds_the_gate_naming_it
run_case case_the_verdict_row_names_each_local_leg
run_case case_tier_decides_which_modes_run_a_leg
run_case case_touches_skips_under_a_narrowed_mode_and_never_under_full
run_case case_two_means_says_what_an_exit_2_from_a_product_tool_means
run_case case_inputs_and_env_are_folded_into_the_reuse_key
run_case case_a_new_local_unit_provisions_once_before_its_legs
run_case case_a_failed_provisioner_stops_every_leg_of_its_unit
run_case case_the_loop_half_provisions_its_unit_too
run_case case_a_malformed_leg_is_exit_2_naming_the_file_and_the_field
run_case case_cis_matrix_takes_the_unit_with_no_yaml_edit
run_case case_the_bank_plan_takes_a_local_unit_from_the_listing
run_case case_the_drawer_is_in_the_measured_trees_declaration_sources

echo
echo "test_local_legs: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
