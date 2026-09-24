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
# drives: README.md apps/ config/ scripts/divergence_census.sh scripts/pm_fold.sh docs/product/in-flight.md docs/product/queue.md docs/product/readouts.md quality/ scripts/archaeology_lib.sh scripts/check.sh scripts/db.sh scripts/docs_legs.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/githooks scripts/kill_mine.sh scripts/loop_health.py scripts/loop_tier.sh scripts/pm_push.sh scripts/publish.sh scripts/queue_cited.sh scripts/rung_start.sh scripts/secrets_scan.sh scripts/sweep.sh scripts/test.sh scripts/tests scripts/verify_start.sh
# cites: uv.lock CHANGELOG.md TEMPLATE_VERSION CLAUDE.md scripts/test_impact.json scripts/local/legs docs/product/instruments.local.md apps/conftest_local.py

# The drive for the `--loop` LEDGER — the key, the environment fingerprint with
# its deriver-declared exclusions, and the fail-closed direction of every doubt
# (`scripts/gate_ledger.sh`, loop-ledger section).
#
# AND, SINCE R3's F3x AND F4x, THE TWO PLACES THE **FULL** LEDGER IS CONSULTED:
# the legs field its lookup compares, and `scripts/githooks/pre-push`, the belt
# that reads it. They live here rather than in a drive of their own because the
# two ledgers are one file with one set of properties — `gate_has_green` is the
# consult both belts make, and a verdict cache's failure mode is the same on
# either side of the file. Each has its own section, below its own argument.
#
#   ./scripts/tests/test_loop_ledger.sh          run every case
#   ./scripts/tests/test_loop_ledger.sh --list   name them
#
# WHY IT EXISTS. A verdict cache is the one instrument in this repository whose
# failure mode is a GREEN RUN THAT MEASURED NOTHING. Every other refusal here
# costs somebody minutes; a cache that hits when it should have missed costs a
# rung its gate, silently, and looks exactly like speed. So the whole drive is
# written from the miss side: each case sets up a reason to doubt and asserts
# that the ledger doubts.
#
# THE THREE-LINE KEY IS THE SUBJECT. Tree, environment, scope — and the SCOPE
# line is the one the active rung added and the one worth the most cases. A `--loop`
# verdict is not a claim about a tree, it is a claim about a SELECTION over a
# tree; without the scope in the key, a verdict banked while grading a one-app
# rung would be honoured by a rung that touched `core`, and the second rung
# would have run nothing at all.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE END-TO-END REUSE THROUGH `scripts/check.sh`. Banking a real verdict
#     needs a provisioned checkout, a database and a complete green `--loop`;
#     that is minutes per case and it is measured by the builder and recorded in
#     the rung's report, not here. What IS covered here is the wiring read out
#     of `check.sh`'s source: that the consult exists, that recording happens
#     only after the green, and that the key is re-derived and compared at the
#     end. A drive that re-implemented the leg would be proving a copy of it.
#   * A REAL PARTIAL INSTALL. The failing-sync branch is driven through a fake
#     `uv` that writes one distribution, prints an error and exits non-zero —
#     which proves the DISPOSITION (the status stays the legs', uv's output is
#     printed, and the end-of-run refusal can still name `dists:`). What no
#     case here reaches is a real `uv sync --frozen` dying halfway through a
#     real resolve: a half-written wheel, a corrupt cache entry, a venv uv
#     itself considers broken. Those are uv's failure modes and the drive would
#     be measuring uv; the belt is that this branch cannot turn any of them
#     into a gate verdict.
#   * The trust class. This is a cache and never a security boundary — a local
#     file an agent could echo a line into, exactly as `git push --no-verify` is
#     one flag away. No case here pretends to defend against a forged row; the
#     cases prove that a row the ledger cannot VOUCH for is not honoured, which
#     is a different property and the only one a cache can have.
#   * Clock skew, concurrent writers and file locking. Rows are appended and the
#     lookup takes the last match; two writers interleaving a line is possible
#     and the consequence is a miss, which is the safe direction.
#   * WHETHER A DECLARED DERIVED PATH IS REALLY UNREAD. The derived-path
#     exclusion is legal on exactly one claim: nothing the gate measures reads
#     the excluded bytes back. The cases below assert that a declaration is
#     OBEYED, that it is one repository-relative subtree, that an unreadable one
#     excludes NOTHING and says so, and that a path nothing tracks is refused —
#     they CANNOT assert the claim itself, because "no check anywhere reads this
#     path" is not a property a shell drive can see. It is a reviewer's, and the
#     sentence naming that duty belongs beside the declaration rather than here.
#     This repository declares nothing today, so every member these cases
#     measure is one they planted.

set -euo pipefail

cd "$(dirname "$0")/../.."

# --- the drive preamble, and it comes before the first git command -----------
[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_loop_ledger: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   It carries the only thing keeping this drive's git commands inside its" >&2
    echo "   own scratch directory. Refusing to run without it." >&2
    exit 2
}
. scripts/tests/drive_preamble.sh

DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_loop_ledger: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_loop_ledger.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
# EITHER SPELLING, because the machine is now part of the subject. `shasum -a
# 256` is macOS's and `sha256sum` is a minimal Linux's; the library under test
# resolves both, so a drive that could only run where one of them lives would
# be unrunnable on exactly the box this case exists for.
command -v shasum >/dev/null 2>&1 || command -v sha256sum >/dev/null 2>&1 ||
    cannot_look "neither shasum nor sha256sum is on PATH — every digest here is one"
[ -f scripts/gate_ledger.sh ] || cannot_look "scripts/gate_ledger.sh is not in this tree"
[ -f scripts/db.sh ] || cannot_look "scripts/db.sh is not in this tree — it declares a derived key"
[ -f scripts/rung_start.sh ] || cannot_look "scripts/rung_start.sh is not in this tree — it declares a derived key"
[ -f scripts/check.sh ] || cannot_look "scripts/check.sh is not in this tree — the wiring cannot be read"

ROOT="$PWD"

# shellcheck source=scripts/gate_ledger.sh
. scripts/gate_ledger.sh
command -v loop_ledger_key >/dev/null 2>&1 ||
    cannot_look "scripts/gate_ledger.sh defines no loop_ledger_key — the loop ledger is gone"
command -v loop_env_fingerprint >/dev/null 2>&1 ||
    cannot_look "scripts/gate_ledger.sh defines no loop_env_fingerprint"
command -v loop_env_derived_keys >/dev/null 2>&1 ||
    cannot_look "scripts/gate_ledger.sh defines no loop_env_derived_keys"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-loop-ledger-drive.XXXXXX")" ||
    cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'chmod -R u+rwX "$WORK" 2>/dev/null || true; rm -rf "$WORK"'

# EVERY CASE WRITES INTO A SCRATCH LEDGER. Unset, `loop_ledger_path` answers the
# real common git dir, and this drive would be planting verdicts in the tree it
# is testing.
export DJB_LOOP_LEDGER="${WORK}/ledger"
: >"$DJB_LOOP_LEDGER"

CURRENT=""
RC=0
OUT=""
N=0

ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    if [ -n "$OUT" ] && [ -f "$OUT" ]; then
        sed 's/^/             | /' "$OUT" | tail -25
    fi
    FAILED=$((FAILED + 1))
}
is() {
    local got="$1" want="$2" what="$3"
    if [ "$got" = "$want" ]; then
        ok "${what} is '${want}'"
    else
        bad "${what}: wanted '${want}', got '${got}'"
    fi
}
differs() {
    local a="$1" b="$2" what="$3"
    if [ "$a" != "$b" ]; then
        ok "${what}"
    else
        bad "${what}: both answered '${a}' — the input this case moved is NOT in the key"
    fi
}
same() {
    local a="$1" b="$2" what="$3"
    if [ "$a" = "$b" ]; then
        ok "${what}"
    else
        bad "${what}: '${a}' vs '${b}' — the input this case moved should not have been in the key"
    fi
}

# A scratch checkout with a `.env`, a fake venv census and a `main` to fork from
# — everything `loop_env_fingerprint` reads.
REPO=""
fresh_checkout() {
    N=$((N + 1))
    REPO="${WORK}/checkout${N}"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/scripts" "$REPO/.venv/lib/python3.12/site-packages/thing-1.0.dist-info"
    git -C "$REPO" init -q 2>/dev/null || git init -q "$REPO"
    git -C "$REPO" symbolic-ref HEAD refs/heads/main
    git -C "$REPO" config user.email drive@example.invalid
    git -C "$REPO" config user.name "loop ledger drive"
    {
        echo "DATABASE_NAME=djb_checkout_one"
        # A BUCKET NAME, not a credential. detect-secrets reads it as a Base64
        # high-entropy string because it is a hyphenated slug of the right
        # length and has no way to know what the key means; the fixture needs a
        # per-checkout-shaped value precisely so the fingerprint has something
        # to differ on, so shortening it to please the scanner would weaken the
        # case. Marked, with the reason, at the site.
        echo "AWS_STORAGE_BUCKET_NAME=djb-checkout-one" # pragma: allowlist secret
        echo "SECRET_KEY=not-a-real-key" # pragma: allowlist secret
        echo "DEBUG=1"
    } >"$REPO/.env"
    # The DERIVERS, carrying their sentinel declarations. Copied from the real
    # ones rather than invented: the parser under test reads `scripts/*.sh` in
    # the current directory, so the scratch tree needs the real declarations to
    # be the thing being parsed.
    cp "$ROOT/scripts/db.sh" "$REPO/scripts/db.sh"
    cp "$ROOT/scripts/rung_start.sh" "$REPO/scripts/rung_start.sh"
    echo "base" >"$REPO/README.md"
    git -C "$REPO" add -A >/dev/null 2>&1
    git -C "$REPO" commit -q -m "base"
}

in_repo() {
    local dir="$1"
    shift
    (cd "$dir" && "$@")
}

# --- the row's two new fields, and the attribution they buy -------------------
#
# WHY THE FIELDS EXIST. A key is a digest of three lines, so a reader holding a
# key and a miss cannot say WHICH line moved — and "the bank missed" with no
# reason is exactly what leaves a verifier's `loop:` field empty and the round's
# readout unable to say whether the cache is working. The row carries the two
# inputs that cannot be recovered from the key; the scope was already there.

# A 64-hex digest from a seed, so a crafted row is shaped exactly like a real
# one and the malformed-component read below has something to be satisfied by.
# RESOLVED HERE AND NOT THROUGH `sha256_of`, deliberately: this is the drive's
# own reference implementation, and a case that compared the library's answer
# with the library's answer would assert nothing at all.
hex64() {
    if command -v shasum >/dev/null 2>&1; then
        printf '%s' "$1" | shasum -a 256 | awk '{print $1}'
    else
        printf '%s' "$1" | sha256sum | awk '{print $1}'
    fi
}
# A 40-hex commit-shaped value, likewise.
sha40() { hex64 "$1" | cut -c1-40; }

# The five components a case hands the recorder or the attributor, in the fixed
# field order. Every crafted row in this drive is built through this, so a case
# that means to move ONE component moves exactly one.
#
# `$6` is `env-reads`, appended to the PARAMETER list so no existing caller
# moved, and printed in the FIELD order `LOOP_ENV_COMPONENT_FIELDS` declares —
# the two orders are different on purpose and only the printed one is read.
crafted_components() {
    printf 'env-file=%s excluded=%s dists=%s env-reads=%s head=%s merge-base=%s' \
        "${1:-$(hex64 envfile)}" "${2:-AWS_STORAGE_BUCKET_NAME,DATABASE_NAME}" \
        "${3:-$(hex64 dists)}" "${6:-$(hex64 reads)}" \
        "${4:-$(sha40 head)}" "${5:-$(sha40 base)}"
}

case_the_row_carries_tree_and_env_appended_after_passes() {
    fresh_checkout
    local key row want
    key=$(in_repo "$REPO" loop_ledger_key treeone "mode=fast scope=- always=abc")
    # THE COMPONENTS COME FROM THE GLOBAL, so the case sets the global — which
    # is what `check.sh` does by calling `loop_env_fingerprint` plainly before
    # it records, and is the only way the components can be guaranteed to
    # belong to the same composition as the `env=` digest beside them.
    LOOP_ENV_COMPONENTS=$(crafted_components)
    echo "  PLANT TOOK · components for the row: ${LOOP_ENV_COMPONENTS}"
    in_repo "$REPO" loop_ledger_record "$key" "mode=fast scope=- always=abc" 1 \
        aaaabbbb ccccdddd ||
        cannot_look "could not record the row this case is about"
    row=$(in_repo "$REPO" loop_ledger_lookup "$key")
    LOOP_ENV_COMPONENTS=""
    CURRENT="the row carries tree= and env=, after passes="
    case "$row" in
    *" passes=1 tree=aaaabbbb env=ccccdddd "*) ok "the two fields follow passes=, in that order" ;;
    *) bad "the row does not carry 'passes=1 tree=... env=...': '${row}'" ;;
    esac
    # THE COMPONENTS ARE NO LONGER THE END OF THE LINE, and that is the append
    # precedent working rather than breaking: `waited=` and `took=` were added
    # after them exactly as they were added after `env=`, which was added after
    # `passes=`, which was added after `scope=`. What this half of the case is
    # actually about is that the five components sit in the field ORDER, after
    # `env=`, contiguously — so it asserts the run of fields rather than the end
    # of the string, and the half below names what may legally follow.
    CURRENT="and the five components are appended after env=, in the field order"
    want=" passes=1 tree=aaaabbbb env=ccccdddd $(crafted_components)"
    case "$row" in
    *"$want"*) ok "env-file= excluded= dists= head= merge-base= follow env=, in that order" ;;
    *) bad "the row does not carry '${want}': '${row}'" ;;
    esac
    CURRENT="and the cost fields are what follows them"
    case "$row" in
    *"${want} waited="*" took="*) ok "waited= and took= are appended after the components" ;;
    *) bad "the row does not end in the cost fields: '${row}'" ;;
    esac
    CURRENT="a recorder with no components appends none"
    local bare_key bare_row
    bare_key=$(in_repo "$REPO" loop_ledger_key treetwo "mode=fast scope=- always=abc")
    in_repo "$REPO" loop_ledger_record "$bare_key" "mode=fast scope=- always=abc" 1 \
        eeeeffff 11112222 ||
        cannot_look "could not record the componentless row this case is about"
    bare_row=$(in_repo "$REPO" loop_ledger_lookup "$bare_key")
    case "$bare_row" in
    *" passes=1 tree=eeeeffff env=11112222 waited="*)
        ok "an underived fingerprint appends nothing rather than empty fields — env= is followed straight by the cost fields"
        ;;
    *) bad "the componentless row is not the expected shape: '${bare_row}'" ;;
    esac
}

case_both_verdict_rows_record_what_the_run_COST() {
    # A VERDICT ROW SAID WHAT WAS MEASURED AND NEVER WHAT IT COST. "The gate is
    # slow" and "the gate spent nine minutes queued behind somebody else's push"
    # are different complaints with different answers, and neither was
    # answerable from the ledger: the wait was announced to a terminal that
    # scrolled away, and the suite's wall was printed by the leg and then thrown
    # away. Two fields make every banked row a datum.
    fresh_checkout
    local key row
    key=$(in_repo "$REPO" loop_ledger_key costtree "mode=fast scope=- always=abc")
    # The globals the two libraries set. `--loop` takes no exclusive lease, so
    # the lease half is 0 on every real loop row and the slot half is the whole
    # of the wait — which is exactly the fact a reader needs and could not get.
    GATE_LEASE_WAITED=0
    GATE_SLOT_WAITED=94
    GATE_PYTEST_TOOK=212
    in_repo "$REPO" loop_ledger_record "$key" "mode=fast scope=- always=abc" 1 \
        costtree envdigest ||
        cannot_look "could not record the row this case is about"
    row=$(in_repo "$REPO" loop_ledger_lookup "$key")
    GATE_LEASE_WAITED=0
    GATE_SLOT_WAITED=0
    GATE_PYTEST_TOOK=0
    CURRENT="the loop row records the wait and the suite's wall"
    case "$row" in
    *" waited=94 took=212"*) ok "waited=94 took=212 — the two guards' wait summed, and the pytest leg's wall" ;;
    *) bad "the row carries no cost fields: '${row}'" ;;
    esac

    CURRENT="a run with no suite and no wait records zeroes, not silence"
    local zkey zrow
    zkey=$(in_repo "$REPO" loop_ledger_key zerotree "mode=fast scope=- always=abc")
    in_repo "$REPO" loop_ledger_record "$zkey" "mode=fast scope=- always=abc" ||
        cannot_look "could not record the componentless zero row"
    zrow=$(in_repo "$REPO" loop_ledger_lookup "$zkey")
    case "$zrow" in
    *" waited=0 took=0"*) ok "absent globals read as 0 — 'this run did not wait' and 'this run started no suite' are both true and both said" ;;
    *) bad "an unset global produced something other than 0: '${zrow}'" ;;
    esac
}

case_a_row_without_the_cost_fields_is_still_a_hit() {
    # THE APPEND CONTRACT, DRIVEN. Every row in every ledger on the day this
    # ships was written without these two fields, and a verdict cache that
    # stopped honouring its own history would silently re-measure every tree it
    # had already vouched for — which reads as nothing at all, just a gate that
    # got slower.
    fresh_checkout
    local key row
    key=$(in_repo "$REPO" loop_ledger_key pretree "mode=fast scope=- always=abc")
    printf 'loop-v1 %s loop 2026-09-01T00:00:00Z caller=unstated scope=mode=fast_scope=-_always=abc passes=1 tree=pretree env=envdigest\n' \
        "$key" >>"$(in_repo "$REPO" loop_ledger_path)"
    CURRENT="a row written before the cost fields existed"
    RC=0
    row=$(in_repo "$REPO" loop_ledger_lookup "$key") || RC=$?
    is "$RC" "0" "the lookup of a pre-cost row"
    case "$row" in
    *" tree=pretree env=envdigest") ok "it comes back verbatim, ending exactly where it always did" ;;
    *) bad "the pre-cost row did not round-trip: '${row}'" ;;
    esac
    case "$row" in
    *waited=*) bad "the lookup invented a cost field that was never written" ;;
    *) ok "and nothing was invented onto it" ;;
    esac
}

case_a_row_written_before_those_fields_existed_still_hits() {
    fresh_checkout
    # THE APPENDING PRECEDENT, PINNED. `passes=` went after `scope=` so that
    # pre-existing lines kept parsing; `tree=`/`env=` go after `passes=` for the
    # same reason, and this case is the thing that would notice if a future
    # field went in the MIDDLE instead. The row below is written by hand in the
    # old shape on purpose.
    local key path
    key=$(in_repo "$REPO" loop_ledger_key treeone "mode=fast scope=- always=abc")
    path="$DJB_LOOP_LEDGER"
    printf 'loop-v1 %s loop 2026-09-07T00:00:00Z caller=drive scope=mode=fast_scope=-_always=abc passes=1\n' \
        "$key" >>"$path"
    CURRENT="a row from before the fields existed"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$key" >/dev/null 2>&1 || RC=$?
    is "$RC" "0" "the lookup on an old-shape row"
}

# Plant one row and SAY SO. A plant that did not take is a case asserting
# against an empty ledger, which passes for the wrong reason; the line printed
# here is what a reader checks the assertion against.
plant_row() {
    local canon=$1 t=$2 e=$3 comp=${4:-}
    printf 'loop-v1 loop-v1:%064d loop 2026-09-07T00:00:00Z caller=drive scope=%s passes=1 tree=%s env=%s%s\n' \
        1 "$canon" "$t" "$e" "${comp:+ $comp}" >>"$DJB_LOOP_LEDGER"
    echo "  PLANT TOOK · ${DJB_LOOP_LEDGER##*/}: scope=${canon} tree=${t} env=${e}${comp:+ ${comp}}"
}

# Line 1 of the attributor's stdout — the TOKEN. `sed -n '1p'` rather than
# `head -n1`: sed reads its input to the end, so it can never close the pipe
# under a producer that is still writing.
attr_token() {
    in_repo "$REPO" loop_ledger_attribute "$1" "$2" "$3" | sed -n '1p'
}

case_the_attributor_names_which_of_the_three_lines_moved() {
    fresh_checkout
    local scope="mode=fast_scope=-_always=abc" path
    path="$DJB_LOOP_LEDGER"
    : >"$path"
    LOOP_ENV_COMPONENTS=""

    CURRENT="an empty ledger"
    is "$(attr_token T E "mode=fast scope=- always=abc")" \
        "no-ledger" "the attribution"

    plant_row "$scope" TREEA ENVA

    CURRENT="same scope, same env, a different tree"
    is "$(attr_token TREEB ENVA "mode=fast scope=- always=abc")" \
        "tree" "the attribution"

    CURRENT="same scope, same tree, a different environment"
    is "$(attr_token TREEA ENVB "mode=fast scope=- always=abc")" \
        "env" "the attribution"

    CURRENT="same tree and environment, a different scope"
    is "$(attr_token TREEA ENVA "mode=fast scope=core always=abc")" \
        "scope" "the attribution"

    CURRENT="nothing in common with any row"
    is "$(attr_token TREEZ ENVZ "mode=fast scope=zzz always=abc")" \
        "unmatched" "the attribution"

    CURRENT="a row with no components says so in its detail line"
    if in_repo "$REPO" loop_ledger_attribute TREEB ENVA "mode=fast scope=- always=abc" |
        grep -F "banked row carries no components (recorded before they were)" >/dev/null; then
        ok "the detail names the row's age rather than implying a comparison nobody made"
    else
        bad "a pre-components row was attributed without saying its components are missing"
    fi

    # IT NAMES THE COMPONENT NOW — the sentence that stood here said the
    # opposite and was true while the row carried only the env digest. Described
    # rather than re-spelled: a censused string counts wherever it appears.
    CURRENT="the attributor's declared reach"
    if grep -F "IT NAMES THE COMPONENT NOW, BECAUSE THE ROW CARRIES ONE" "${ROOT}/scripts/gate_ledger.sh" >/dev/null; then
        ok "the reach is written down beside the function"
    else
        bad "the attributor no longer declares that it names the component"
    fi
    CURRENT="and the superseded claim is gone, not left standing"
    is "$(grep -cF "NAMES THE LINE, NOT THE COMPONENT" "${ROOT}/scripts/gate_ledger.sh" || true)" "0" \
        "the count of the retired sentence in gate_ledger.sh"
    is "$(grep -cF "a component name refines miss(env)" "${ROOT}/scripts/check.sh" || true)" "0" \
        "the count of the retired by-eye instruction in check.sh"
}

case_the_attributor_reads_the_rows_components_most_specific_first() {
    fresh_checkout
    local scope="mode=fast_scope=-_always=abc" want="mode=fast scope=- always=abc"
    local E D H0 B0 H1 B1 base
    E=$(hex64 envfile)
    D=$(hex64 dists)
    H0=$(sha40 head-banked)
    B0=$(sha40 base-banked)
    H1=$(sha40 head-now)
    B1=$(sha40 base-now)
    base=$(crafted_components "$E" "" "$D" "$H0" "$B0")

    # THE DOCS-DRIFT CASE, which is the whole reason this work exists: main
    # gained a ledger commit, so the union's tree moved AND the two revision
    # components moved with it, while every input the suite stands on held
    # still. The baseline attributor answers `unmatched` here.
    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" TREEA ENVA "$base"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$H1" "$B1")
    CURRENT="env-file/excluded/dists equal, head and merge-base moved with the tree"
    is "$(attr_token TREEB ENVB "$want")" "tree" "the attribution"

    CURRENT="an identical tree with only head= moved — an amend, named"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$H1" "$B0")
    is "$(attr_token TREEA ENVB "$want")" "env:head" "the attribution"

    CURRENT="an identical tree with only merge-base= moved — a rebase, named"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$H0" "$B1")
    is "$(attr_token TREEA ENVB "$want")" "env:merge-base" "the attribution"

    CURRENT="an identical tree with a different .env"
    LOOP_ENV_COMPONENTS=$(crafted_components "$(hex64 other-envfile)" "" "$D" "$H0" "$B0")
    is "$(attr_token TREEA ENVB "$want")" "env:env-file" "the attribution"

    CURRENT="an identical tree with a different distribution census"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$(hex64 other-dists)" "$H0" "$B0")
    is "$(attr_token TREEA ENVB "$want")" "env:dists" "the attribution"

    CURRENT="an identical tree with a different exclusion list"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "DATABASE_NAME" "$D" "$H0" "$B0")
    is "$(attr_token TREEA ENVB "$want")" "env:excluded" "the attribution"

    CURRENT="two components moved — both named, in the fixed field order"
    LOOP_ENV_COMPONENTS=$(crafted_components "$(hex64 other-envfile)" "" "$(hex64 other-dists)" "$H0" "$B0")
    is "$(attr_token TREEA ENVB "$want")" "env:env-file,dists" "the attribution"

    # THE HONEST `unmatched`, kept honest. A dependency delta arriving on a docs
    # drift is TWO things moving; calling it `tree` would send the reader to
    # fold main and re-measure for a reason that was never the tree.
    CURRENT="the tree moved AND a non-revision component moved"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$(hex64 other-dists)" "$H1" "$B1")
    is "$(attr_token TREEB ENVB "$want")" "unmatched" "the attribution"

    CURRENT="and the token carries the banked row's own components beside it"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$H1" "$B1")
    if in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" |
        grep -F "banked row: tree=TREEA" >/dev/null; then
        ok "the detail names the row the token came from"
    else
        bad "the token names a component without printing the row it was read from"
    fi
    LOOP_ENV_COMPONENTS=""
}

case_the_tree_token_says_what_moved_and_whether_it_was_only_docs() {
    fresh_checkout
    local scope="mode=fast_scope=-_always=abc" want="mode=fast scope=- always=abc"
    local E D banked_head
    E=$(hex64 envfile)
    D=$(hex64 dists)

    mkdir -p "$REPO/docs/product"
    echo "the queue" >"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "a docs file to move"
    banked_head=$(git -C "$REPO" rev-parse HEAD)
    echo "  PLANT TOOK · banked head is $(git -C "$REPO" log -1 --oneline)"

    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" TREEA ENVA \
        "$(crafted_components "$E" "" "$D" "$banked_head" "$banked_head")"

    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    echo "  PLANT TOOK · one docs-only commit on top: $(git -C "$REPO" log -1 --oneline)"

    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" \
        "$(git -C "$REPO" rev-parse HEAD)" "$(git -C "$REPO" rev-parse HEAD)")
    N=$((N + 1))
    OUT="${WORK}/docsdrift${N}.log"
    in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" >"$OUT" 2>&1

    CURRENT="the token, on a docs-only drift"
    is "$(sed -n '1p' "$OUT")" "tree" "line 1"
    CURRENT="and the detail counts the paths and calls it docs-only"
    if grep -E "^since banked head [0-9a-f]{8}: 1 path\(s\) changed; docs-only: yes$" "$OUT" >/dev/null; then
        ok "the detail line is the counter's own shape"
    else
        bad "the detail line is not 'since banked head <short>: 1 path(s) changed; docs-only: yes'"
    fi

    CURRENT="a NON-docs commit on top flips the answer"
    printf 'a source change\n' >>"$REPO/README.md"
    git -C "$REPO" add README.md >/dev/null
    git -C "$REPO" commit -q -m "a source change"
    echo "  PLANT TOOK · a non-docs commit on top: $(git -C "$REPO" log -1 --oneline)"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" \
        "$(git -C "$REPO" rev-parse HEAD)" "$(git -C "$REPO" rev-parse HEAD)")
    in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" >"$OUT" 2>&1
    if grep -F "docs-only: no" "$OUT" >/dev/null; then
        ok "a path outside docs/ makes it 'no' — the prefix is the whole test and it is doing work"
    else
        bad "docs-only did not flip to 'no' when a non-docs path moved"
    fi
    OUT=""
    LOOP_ENV_COMPONENTS=""
}

# CROSS-ROW PRECEDENCE — the arm the criteria specified row by row and never
# said what to do when TWO DIFFERENT rows match TWO DIFFERENT arms. That is not
# a corner: it is the state every `verify_start` clone is in, seeded with
# twenty-odd rows from other branches. Measured in the field on 2026-09-08: the
# same inputs read `env:env-file` against the fixture's own row alone and `tree`
# against the clone's real 24 rows, because the attributor captured the first
# tree-arm match in FILE ORDER and returned before it ever looked for an
# equal-tree row. A foreign row pre-empted the clone's own.
#
# Ruled: over rows of equal `scope=`, an EQUAL-`tree` row always outranks a
# differing-`tree` row, and within one arm the row whose `head=` is NEAREST
# `HEAD` wins. Both halves are asserted here, and both are asserted with the
# losing row planted FIRST — a case where file order and the rule agree proves
# nothing about which of the two the code is following.
case_an_equal_tree_row_outranks_a_differing_tree_row_whatever_the_file_order() {
    fresh_checkout
    local scope="mode=fast_scope=-_always=abc" want="mode=fast scope=- always=abc"
    local E D HF BF H0 B0 mine

    E=$(hex64 envfile)
    D=$(hex64 dists)
    HF=$(sha40 head-foreign)
    BF=$(sha40 base-foreign)
    H0=$(sha40 head-mine)
    B0=$(sha40 base-mine)

    # (i) THE FIELD SHAPE. A foreign row FIRST — equal env-file/excluded/dists,
    # a tree of its own, revision components of its own — and the run's OWN row
    # second, on the run's exact tree with one component (the `.env`) moved. The
    # honest answer is `env:env-file`: the run's own tree is banked, and what
    # kept the key from matching is the environment.
    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" TREEFOREIGN ENVF "$(crafted_components "$E" "" "$D" "$HF" "$BF")"
    plant_row "$scope" TREEMINE ENVM \
        "$(crafted_components "$(hex64 other-envfile)" "" "$D" "$H0" "$B0")"
    mine=$(crafted_components "$E" "" "$D" "$H0" "$B0")
    LOOP_ENV_COMPONENTS="$mine"
    CURRENT="a foreign different-tree row first, the run's own equal-tree row second"
    is "$(attr_token TREEMINE ENVX "$want")" "env:env-file" "the attribution"

    # AND THE TOKEN DOES NOT DEPEND ON ROW ORDER — the declared absent. Same two
    # rows, reversed; a rule that is really a rule answers identically.
    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" TREEMINE ENVM \
        "$(crafted_components "$(hex64 other-envfile)" "" "$D" "$H0" "$B0")"
    plant_row "$scope" TREEFOREIGN ENVF "$(crafted_components "$E" "" "$D" "$HF" "$BF")"
    CURRENT="the same two rows in the opposite file order"
    is "$(attr_token TREEMINE ENVX "$want")" "env:env-file" "the attribution"

    # (ii) WITHIN ONE ARM, THE NEARER HEAD WINS. Two rows both qualifying for
    # the tree arm; the FAR one planted first so file order and the rule
    # disagree. Real commits, because `merge-base --is-ancestor` is the ruling's
    # own instrument and a crafted sha would measure nothing.
    local far near
    echo "far" >>"$REPO/README.md"
    git -C "$REPO" add README.md >/dev/null
    git -C "$REPO" commit -q -m "the far banked head"
    far=$(git -C "$REPO" rev-parse HEAD)
    echo "near" >>"$REPO/README.md"
    git -C "$REPO" add README.md >/dev/null
    git -C "$REPO" commit -q -m "a commit between the two"
    echo "nearer" >>"$REPO/README.md"
    git -C "$REPO" add README.md >/dev/null
    git -C "$REPO" commit -q -m "the near banked head"
    near=$(git -C "$REPO" rev-parse HEAD)
    echo "  PLANT TOOK · far head ${far} · near head ${near} · HEAD $(git -C "$REPO" rev-parse HEAD)"

    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" TREEFAR ENVF "$(crafted_components "$E" "" "$D" "$far" "$far")"
    plant_row "$scope" TREENEAR ENVN "$(crafted_components "$E" "" "$D" "$near" "$near")"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" \
        "$(git -C "$REPO" rev-parse HEAD)" "$(git -C "$REPO" rev-parse HEAD)")
    N=$((N + 1))
    OUT="${WORK}/nearest${N}.log"
    in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" >"$OUT" 2>&1

    CURRENT="two rows in the tree arm, the far one first in file order"
    is "$(sed -n '1p' "$OUT")" "tree" "line 1"
    CURRENT="and the detail names the NEARER row, not the first one"
    if grep -F "banked row: tree=TREENEAR" "$OUT" >/dev/null; then
        ok "the nearest banked head is the row the token was read from"
    else
        bad "the token came from a row that is not the nearest banked head"
    fi
    CURRENT="and the since-line is measured from that nearer head"
    if grep -F "since banked head $(printf '%s' "$near" | cut -c1-8): 0 path(s) changed" "$OUT" >/dev/null; then
        ok "the counter measures from the row the precedence rule picked"
    else
        bad "the since-line does not measure from the nearest banked head"
    fi

    # (iii) THE CRIT-6 CONSTRUCTION OVER A SEEDED LEDGER — the whole point. The
    # docs-only drift is the case the `tree` token exists for, and until the
    # precedence rule landed it was measured against the FIRST foreign row in a
    # seeded clone, which is how the field read `20 path(s) changed; docs-only:
    # no` on a drift of one docs commit.
    local banked
    mkdir -p "$REPO/docs/product"
    echo "the queue" >"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "a docs file to move"
    banked=$(git -C "$REPO" rev-parse HEAD)

    : >"$DJB_LOOP_LEDGER"
    local i
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
        printf 'loop-v1 loop-v1:%064d loop 2026-09-07T00:00:00Z caller=drive scope=%s passes=1 tree=FOREIGN%s env=ENVF%s %s\n' \
            "$i" "$scope" "$i" "$i" \
            "$(crafted_components "$E" "" "$D" "$far" "$far")" >>"$DJB_LOOP_LEDGER"
    done
    plant_row "$scope" TREEBANKED ENVBANKED \
        "$(crafted_components "$E" "" "$D" "$banked" "$banked")"
    echo "  PLANT TOOK · seeded ledger: $(grep -c '^loop-v1 ' "$DJB_LOOP_LEDGER") rows, the own row LAST"

    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    echo "  PLANT TOOK · one docs-only commit on top: $(git -C "$REPO" log -1 --oneline)"

    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" \
        "$(git -C "$REPO" rev-parse HEAD)" "$(git -C "$REPO" rev-parse HEAD)")
    N=$((N + 1))
    OUT="${WORK}/seededdrift${N}.log"
    in_repo "$REPO" loop_ledger_attribute TREEDRIFTED ENVDRIFTED "$want" >"$OUT" 2>&1

    CURRENT="a docs-only drift attributed over a ledger seeded with 20 foreign rows"
    is "$(sed -n '1p' "$OUT")" "tree" "line 1"
    if grep -E "^since banked head [0-9a-f]{8}: 1 path\(s\) changed; docs-only: yes$" "$OUT" >/dev/null; then
        ok "the counter's own shape survives a seeded ledger — the foreign rows did not pre-empt"
    else
        bad "the detail line is not 'since banked head <short>: 1 path(s) changed; docs-only: yes'"
    fi

    # AND THE RULE IS WRITTEN DOWN BESIDE THE CODE, not only in a criteria file
    # nobody reads from here. A precedence rule that lives only in the arm order
    # of a `while` loop is a rule the next editor swaps back without noticing.
    CURRENT="the precedence rule is declared in the attributor's header"
    if grep -F "AN EQUAL-\`tree\` ROW ALWAYS" "${ROOT}/scripts/gate_ledger.sh" >/dev/null &&
        grep -F "THE NEAREST BANKED HEAD WINS" "${ROOT}/scripts/gate_ledger.sh" >/dev/null; then
        ok "both halves of the 2026-09-08 ruling are stated where the code is"
    else
        bad "the attributor's header does not state the cross-row precedence rule"
    fi
    CURRENT="and the banner says which row the token was read from"
    if grep -F "never the first row in the" "${ROOT}/scripts/check.sh" >/dev/null; then
        ok "the miss banner points the reader at the 'banked row:' line and the rule behind it"
    else
        bad "the miss banner still implies the token came from an unranked row"
    fi

    # THE CONSULT PATH STILL CANNOT EXIT NON-ZERO through any of the above.
    RC=0
    in_repo "$REPO" loop_ledger_attribute TREEDRIFTED ENVDRIFTED "$want" >/dev/null 2>&1 || RC=$?
    CURRENT="the exit status of the attributor over a seeded ledger"
    is "$RC" "0" "the status"

    OUT=""
    LOOP_ENV_COMPONENTS=""
}

case_the_fingerprint_globals_survive_the_call_that_sets_them() {
    # THE SUBSHELL TRAP, and it is here because it BIT on the active rung's own first
    # green run: `loop_ledger_key` computes the fingerprint, but every caller
    # invokes it as `$(...)`, so the globals it sets belong to a subshell that
    # exits immediately. The gate recorded `env=unstated` and went green — a
    # verdict row missing the field the whole attribution rests on, with nothing
    # red to show for it. Two halves, because either alone would still pass:
    CURRENT="the function sets its globals in the CALLER's shell"
    LOOP_ENV_FINGERPRINT=""
    LOOP_ENV_COMPONENTS=""
    loop_env_fingerprint >/dev/null 2>&1 || true
    case "$LOOP_ENV_FINGERPRINT" in
    [0-9a-f]*) ok "called plainly, the fingerprint global is set in this shell" ;;
    *) bad "the fingerprint global is '${LOOP_ENV_FINGERPRINT}' after a plain call" ;;
    esac
    case "$LOOP_ENV_COMPONENTS" in
    *"env-file="*"dists="*"merge-base="*) ok "the components global carries all five parts" ;;
    *) bad "the components global is '${LOOP_ENV_COMPONENTS}'" ;;
    esac

    CURRENT="a substitution's copy does NOT reach this shell — the trap, demonstrated"
    LOOP_ENV_FINGERPRINT=""
    _discard=$(loop_ledger_key sometree "mode=fast scope=- always=abc" || true)
    if [ -z "$LOOP_ENV_FINGERPRINT" ]; then
        ok "deriving the key in \$(...) leaves this shell's global EMPTY — which is why the caller sets it itself"
    else
        bad "the substitution somehow set the caller's global — this case's premise is gone and the guard below is unnecessary"
    fi

    CURRENT="and check.sh sets it in its own shell before it records"
    if grep -F 'loop_env_fingerprint >/dev/null 2>&1 || true' "${ROOT}/scripts/check.sh" >/dev/null; then
        ok "check.sh calls loop_env_fingerprint outside a substitution"
        # Twice: once at the consult, once before the record.
        is "$(grep -cF 'loop_env_fingerprint >/dev/null 2>&1 || true' "${ROOT}/scripts/check.sh")" "2" \
            "the number of plain calls (consult and record)"
    else
        bad "check.sh never calls loop_env_fingerprint outside a substitution — every env= it writes will be unstated"
    fi
}

case_the_census_counts_rows_and_reports_a_seed() {
    fresh_checkout
    local path
    path="$DJB_LOOP_LEDGER"
    : >"$path"
    CURRENT="an empty ledger, never seeded"
    case "$(in_repo "$REPO" loop_ledger_census)" in
    "0 rows (0 seeded"*) ok "says 0 rows and 0 seeded" ;;
    *) bad "the census reads '$(in_repo "$REPO" loop_ledger_census)'" ;;
    esac

    printf 'loop-v1 loop-v1:%064d loop 2026-09-07T00:00:00Z caller=drive scope=s passes=1 tree=T env=E\n' 1 >>"$path"
    printf 'loop-v1 loop-v1:%064d loop 2026-09-07T00:00:01Z caller=drive scope=s passes=1 tree=T env=E\n' 2 >>"$path"
    printf 'seeded=2 from=/somewhere/else/.git/djb-loop-verdicts\n' >"${path}-seed"
    CURRENT="two rows, both seeded, with a note beside them"
    case "$(in_repo "$REPO" loop_ledger_census)" in
    "2 rows (2 seeded from /somewhere/else/.git/djb-loop-verdicts)") ok "says the count and names the source" ;;
    *) bad "the census reads '$(in_repo "$REPO" loop_ledger_census)'" ;;
    esac
    rm -f "${path}-seed"
}

case_a_seeded_row_is_no_hit_once_the_tree_has_moved() {
    # CRITERION 5, AT THE KEY LEVEL — which is the level it is about. A live
    # `--loop` cannot run here (no venv: this drive's declared blind spot), so
    # what is driven is the property the live case would demonstrate: a row
    # seeded from somewhere else is honoured only for the tree it was banked
    # on, and one changed byte is a different tree.
    fresh_checkout
    local scope="mode=fast scope=- always=abc" seeded_key moved_key
    # A row seeded from a checkout that banked it before the components
    # existed — so this case stays the three-line property it has always been,
    # and the component pass is proven separately.
    LOOP_ENV_COMPONENTS=""
    seeded_key=$(in_repo "$REPO" loop_ledger_key thebuilderstree "$scope")
    in_repo "$REPO" loop_ledger_record "$seeded_key" "$scope" 1 thebuilderstree ENVA ||
        cannot_look "could not seed the row this case is about"

    CURRENT="the seeded row hits on the tree it was banked on"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$seeded_key" >/dev/null 2>&1 || RC=$?
    is "$RC" "0" "the lookup on the banked tree"

    CURRENT="one changed byte later, it is not a hit"
    moved_key=$(in_repo "$REPO" loop_ledger_key thebuilderstreX "$scope")
    differs "$seeded_key" "$moved_key" "the key moved with the tree"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$moved_key" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the lookup on the moved tree"

    CURRENT="and the miss is attributable as the TREE line"
    is "$(attr_token thebuilderstreX ENVA "$scope")" "tree" "the attribution"
}

# --- the deriver-declared exclusions -----------------------------------------

case_the_declarations_are_read_from_the_derivers_not_a_list() {
    CURRENT="the exclusions come from sentinel blocks beside each deriver"
    local keys
    keys=$(in_repo "$ROOT" loop_env_derived_keys | tr '\n' ' ' | sed 's/ $//')
    is "$keys" "AWS_STORAGE_BUCKET_NAME DATABASE_NAME" "the declared derived keys"
    CURRENT="the ledger holds no list of its own"
    # THE PROPERTY, ASSERTED: `gate_ledger.sh` must not name a key. A list here
    # would be right on the day it was written.
    if grep -qE '^[^#]*\b(DATABASE_NAME|AWS_STORAGE_BUCKET_NAME)\b' "$ROOT/scripts/gate_ledger.sh" |
        grep -v derived-env-keys; then
        bad "scripts/gate_ledger.sh names a derived key in code — the declaration has moved away from the deriver"
    else
        ok "no key name appears in the ledger's own code"
    fi
    CURRENT="a paragraph cannot accidentally declare a key"
    # The em-dash form is load-bearing: the first parser read `WHERE` out of the
    # prose sentence "A property of WHERE this tree is".
    case " $keys " in
    *" WHERE "*) bad "the parser read a prose word as a key name" ;;
    *) ok "prose inside a sentinel block declares nothing" ;;
    esac
}

case_a_declared_key_changing_does_not_move_the_key() {
    fresh_checkout
    local before after
    before=$(in_repo "$REPO" loop_env_fingerprint)
    # The per-checkout derived value moves — a different directory, a different
    # database. That must NOT move the fingerprint, or no verdict is ever reused
    # anywhere.
    printf 'DATABASE_NAME=djb_checkout_two\nAWS_STORAGE_BUCKET_NAME=djb-checkout-two\nSECRET_KEY=not-a-real-key\nDEBUG=1\n' >"$REPO/.env" # pragma: allowlist secret
    after=$(in_repo "$REPO" loop_env_fingerprint)
    CURRENT="a DECLARED derived key changing leaves the fingerprint alone"
    same "$before" "$after" "the fingerprint survives a per-checkout derived value moving"
}

case_an_undeclared_key_changing_does_move_the_key() {
    fresh_checkout
    local before after
    before=$(in_repo "$REPO" loop_env_fingerprint)
    printf 'DATABASE_NAME=djb_checkout_one\nAWS_STORAGE_BUCKET_NAME=djb-checkout-one\nSECRET_KEY=not-a-real-key\nDEBUG=0\n' >"$REPO/.env" # pragma: allowlist secret
    after=$(in_repo "$REPO" loop_env_fingerprint)
    CURRENT="an UNDECLARED key changing moves the fingerprint"
    differs "$before" "$after" "a configuration change the derivers never claimed is in the key"
}

case_zero_declarations_is_a_broken_read_and_hashes_the_whole_file() {
    fresh_checkout
    # THE SENTINELS GONE. Not "no keys declared" — the convention itself absent,
    # which is indistinguishable from a correct read that found nothing and must
    # therefore be treated as the broken read it is.
    rm -f "$REPO/scripts/db.sh" "$REPO/scripts/rung_start.sh"
    CURRENT="zero declarations is a broken read, not an empty answer"
    local keys before after
    keys=$(in_repo "$REPO" loop_env_derived_keys)
    is "${keys:-none}" "none" "the discovered declarations"
    before=$(in_repo "$REPO" loop_env_fingerprint)
    printf 'DATABASE_NAME=djb_checkout_two\nAWS_STORAGE_BUCKET_NAME=djb-checkout-two\nSECRET_KEY=not-a-real-key\nDEBUG=1\n' >"$REPO/.env" # pragma: allowlist secret
    after=$(in_repo "$REPO" loop_env_fingerprint)
    # With no verifiable exclusion list the WHOLE file hashes, so the derived
    # per-checkout values are back in the key and every cross-checkout reuse is
    # a MISS. A miss costs a re-run; a hit on an exclusion nobody could verify
    # costs a verdict about the wrong configuration.
    differs "$before" "$after" "with no declaration the whole .env hashes, so a derived value moving is a MISS"
}

case_an_empty_distribution_census_is_could_not_look() {
    fresh_checkout
    rm -rf "$REPO/.venv"
    CURRENT="zero installed distributions is could-not-look, not an empty environment"
    N=$((N + 1))
    OUT="${WORK}/dists${N}.log"
    RC=0
    in_repo "$REPO" loop_env_fingerprint >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "the exit status"
    if grep -qF "not answer" "$OUT"; then
        ok "it says the read did not answer"
    else
        bad "it does not say the read did not answer"
    fi
}

case_the_merge_base_is_used_and_not_mains_tip() {
    fresh_checkout
    git -C "$REPO" checkout -q -b rung/thing
    echo "the rung's own work" >>"$REPO/README.md"
    git -C "$REPO" add -A >/dev/null 2>&1
    git -C "$REPO" commit -q -m "the rung"
    local before after
    before=$(in_repo "$REPO" loop_env_fingerprint)
    # MAIN'S TIP MOVES, unrelated to the active rung — exactly what a merge into local
    # main does, continuously, in this loop. Keyed on the tip, every banked loop
    # verdict in every worktree dies here and the cache never hits once.
    git -C "$REPO" checkout -q main
    echo "somebody else's merge" >>"$REPO/README.md"
    git -C "$REPO" add -A >/dev/null 2>&1
    git -C "$REPO" commit -q -m "an unrelated commit on main"
    git -C "$REPO" checkout -q rung/thing
    after=$(in_repo "$REPO" loop_env_fingerprint)
    CURRENT="an unrelated commit on main does not invalidate the active rung's verdict"
    same "$before" "$after" "the fingerprint carries the MERGE-BASE, not main's tip"
}

# --- the environment the suite STANDS ON, not the file that configures it -----
#
# R3's F2. The fingerprint hashed the `.env` FILE, and `read_env(overwrite=False)`
# — `config/settings/base.py`'s own call — SETDEFAULTS: an exported name wins
# over the file and never touches it. So a terminal that exported a
# suite-affecting variable derived a key byte-identical to one that had not, and
# a narrower green was reusable as a wider one. The full gate has had
# `quality/partition.py::bent_environment()` for this class since the partition
# landed; the loop had nothing.
#
# THE NAMES HAVE ONE OWNER AND IT IS NOT A SHELL SCRIPT.
# `quality/partition.py::suite_environment_names()` derives them from
# `config/settings/**` and subtracts the pins and the tolerated harness knobs;
# `loop_env_reads` asks for them. The cases below drive the two halves
# separately — the VALUE FOLDING in a scratch checkout, over a planted name list
# (a scratch checkout has no `quality/` tree, which is what `DJB_LOOP_ENV_READS`
# is for and the same seam `DJB_LOOP_LEDGER` already is), and the OWNERSHIP on
# this repository's own tree, where the real census is the subject.
#
# `does_not_cover`, DECLARED WITH THE FIX (R3's F2x.4):
#
#   * THE HARNESS KNOBS ARE OUT OF THE KEY ON PURPOSE, and they are not listed
#     here — they are `quality/partition.yaml` §3's `environment.tolerated`,
#     each with the argument for it written beside it, and the full gate's
#     `bent_environment()` subtracts the same four. The class is: a name whose
#     value provably cannot change a verdict ABOUT CODE — which database the
#     suite migrates into, which template it clones, which bucket it names, who
#     called the gate. They are set to a non-default on every honest run in
#     every worktree, so folding them would key every verdict to one directory
#     and no verdict would ever be reused anywhere. That is the dividend
#     deleted rather than protected, and it is the same argument the `.env`
#     digest's DERIVED-KEY exclusions already stand on. The cost is real and
#     stated: a name wrongly tolerated is a name the loop is blind to, and the
#     belt under it is that the list is short, reasoned, and in a diff a human
#     reads.
#   * `config/settings/test.py`'s PINS, likewise subtracted and likewise not
#     listed: what that file pins, the ambient environment cannot reach the
#     suite through at all, so folding it would move the key over a value the
#     suite never sees.
#   * WHAT A NAME'S VALUE MEANS. The fold is a digest: it sees that a value
#     moved, never whether the move could have changed an outcome. Two spellings
#     of the same truth (`1` and `true`) are two keys. That is the fail-closed
#     direction — a re-measure, never a reuse — and it is the reason this is a
#     fingerprint and not a judgment.
#   * COLLECTION-TIME READS OUTSIDE `config/settings/**`. The census is an AST
#     read of the settings package; a name read only by `apps/conftest.py` and
#     never by settings would be invisible to it. Today the population that
#     matters is reached anyway, because the settings layer reads it too — but
#     that is a fact about this tree, not a property of the census.

#: A names file for the scratch checkout, and the one place these cases say a
#: name out loud. Two names, and they are placed rather than picked: one that a
#: planted `.env` also carries (so the precedence half has something to
#: disagree about) and one it does not.
plant_env_reads() {
    N=$((N + 1))
    DJB_LOOP_ENV_READS="${WORK}/env-reads${N}"
    printf '%s\n' "$@" >"$DJB_LOOP_ENV_READS"
    export DJB_LOOP_ENV_READS
    echo "  PLANT TOOK · ${DJB_LOOP_ENV_READS##*/}: $*"
}

#: A key derived in `$REPO` with names exported for that derivation only. Never
#: a prefix assignment on the function call: bash's persistence rules for those
#: differ between POSIX mode and not, and a case whose plant outlives its own
#: line would quietly plant for every case after it.
key_with_env() {
    local assignment
    (
        cd "$REPO" || exit 1
        for assignment in "$@"; do
            export "${assignment?}"
        done
        loop_ledger_key treeone "mode=fast scope=- always=abc"
    )
}

case_an_exported_suite_variable_moves_the_key() {
    fresh_checkout
    local plain exported empty offcensus
    plant_env_reads DRIVE_SUITE_KNOB DRIVE_ABSENT_KNOB

    CURRENT="an exported name the census returns moves the key"
    plain=$(key_with_env)
    exported=$(key_with_env DRIVE_SUITE_KNOB=narrower)
    differs "$plain" "$exported" "the key under an exported suite variable"

    # THE SETDEFAULT SUBTLETY, AND IT IS THE WHOLE REASON THE FOLD SPELLS AN
    # UNSET NAME AS `<unset>` RATHER THAN AS EMPTY. `read_env` SETDEFAULTS, so
    # an exported EMPTY value is SET and wins over the file exactly as a
    # non-empty one does — a fold that read it as absent would be blind to the
    # one case where a name being present at all is the entire difference.
    CURRENT="an exported EMPTY value is not the same as an unset name"
    empty=$(key_with_env DRIVE_SUITE_KNOB=)
    differs "$plain" "$empty" "the key under an exported empty value"

    CURRENT="a name the census does NOT return moves nothing"
    offcensus=$(key_with_env DRIVE_OFF_CENSUS_KNOB=whatever)
    same "$plain" "$offcensus" "the key under a name outside the census"

    unset DJB_LOOP_ENV_READS
}

case_the_process_environment_wins_over_the_env_file() {
    # `read_env(overwrite=False)`'s precedence, driven rather than described:
    # the file is the FALLBACK and the process is the answer. Both halves are
    # asserted, because a fold that ignored the file would pass the half above
    # and be blind to every laptop that configures the suite with `.env` alone.
    fresh_checkout
    local from_file moved_file shadowed_before shadowed_after
    plant_env_reads DRIVE_SUITE_KNOB

    # THE VALUES ARE `one`, `two`, `three` AND NOTHING LONGER, which is not
    # laziness: a hyphenated slug of the right length after a `NAME=` is a
    # Base64 high-entropy string to `detect-secrets`, and the first draft of
    # this case reddened the `--loop` secrets leg three times over. What the
    # case needs is values that DIFFER; nothing here needs them to look real.
    printf 'DRIVE_SUITE_KNOB=one\n' >>"$REPO/.env"
    from_file=$(key_with_env)

    CURRENT="the .env value is the fallback, and moving it moves the key"
    printf 'DRIVE_SUITE_KNOB=two\n' >>"$REPO/.env"
    moved_file=$(key_with_env)
    differs "$from_file" "$moved_file" "the key after the .env value moved"

    CURRENT="and an exported value SHADOWS the file rather than joining it"
    # Two `.env` files that disagree, one exported value over both: the READ-SET
    # component must not move, which is what "the process wins" means and what a
    # digest of the file alone could never say. The whole KEY still moves,
    # because the `.env` digest is its own component and the file did change —
    # so the comparison is made on the component, not on the key.
    shadowed_before=$(
        cd "$REPO" && export DRIVE_SUITE_KNOB=exported && loop_env_reads
    )
    printf 'DRIVE_SUITE_KNOB=three\n' >>"$REPO/.env"
    shadowed_after=$(
        cd "$REPO" && export DRIVE_SUITE_KNOB=exported && loop_env_reads
    )
    is "$shadowed_after" "$shadowed_before" \
        "the read-set digest over two different .env files under one exported value"

    unset DJB_LOOP_ENV_READS
}

case_the_read_set_census_has_one_owner_and_this_file_names_nothing() {
    # THE OWNERSHIP HALF, ON THIS REPOSITORY'S OWN TREE. The scratch cases above
    # drive the folding over a planted list; this one drives the LIST, because a
    # fold of the wrong names is a fold of nothing.
    local owner="$ROOT/quality/partition.py" names digest spelled name
    [ -f "$owner" ] ||
        cannot_look "quality/partition.py is not in this tree — the census has no owner to drive"
    [ -x "$ROOT/.venv/bin/python" ] ||
        cannot_look "this checkout has no .venv/bin/python — the owner cannot be asked"

    CURRENT="the owner prints a census, and it is not empty"
    N=$((N + 1))
    OUT="${WORK}/env-reads-owner${N}.log"
    RC=0
    (cd "$ROOT" && ./.venv/bin/python -m quality.partition env-reads) >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the owner's exit status"
    names=$(cat "$OUT")
    if [ "$(printf '%s\n' "$names" | wc -l | tr -d ' ')" -gt 10 ]; then
        ok "the census returns a real population ($(printf '%s\n' "$names" | wc -l | tr -d ' ') names)"
    else
        bad "the census returned $(printf '%s\n' "$names" | wc -l | tr -d ' ') names — config/settings/** reads dozens"
    fi
    OUT=""

    CURRENT="and on THIS tree the fingerprint folds it rather than declaring no census"
    digest=$(cd "$ROOT" && loop_env_reads) || digest=""
    case "$digest" in
    no-census) bad "loop_env_reads says no-census in the checkout that OWNS the census" ;;
    "") bad "loop_env_reads could not look on this tree" ;;
    *)
        if printf '%s' "$digest" | grep -E '^[0-9a-f]{64}$' >/dev/null; then
            ok "the read-set component is a digest of the live census"
        else
            bad "the read-set component is not a digest: '${digest}'"
        fi
        ;;
    esac

    # PRINCIPLE 9, MADE CHECKABLE. A name spelled in the shell is a second list
    # with extra steps — right on the day it is typed, unmaintained after, and
    # read as authoritative by whoever finds it. The population is asked of the
    # owner, so this cannot go stale either.
    CURRENT="no name the census returns is spelled anywhere in scripts/gate_ledger.sh"
    spelled=""
    while IFS= read -r name; do
        [ -n "$name" ] || continue
        if grep -F "$name" "$ROOT/scripts/gate_ledger.sh" >/dev/null 2>&1; then
            spelled="${spelled}${spelled:+, }${name}"
        fi
    done <<EOF
$names
EOF
    is "$spelled" "" "the census names gate_ledger.sh spells (comments included)"
}

case_a_moved_read_set_is_attributed_by_name() {
    # THE FIFTH MISS REASON. `env:env-reads` has to reach the banner, or a
    # reader holding a miss on an identical tree cannot tell the new component
    # from the four that were always there — which is the exact legibility the
    # components were added for.
    fresh_checkout
    local scope="mode=fast_scope=-_always=abc" want="mode=fast scope=- always=abc"
    local E D H token
    E=$(hex64 envfile)
    D=$(hex64 dists)
    H=$(sha40 head)
    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" SAMETREE ENVA "$(crafted_components "$E" "" "$D" "$H" "$H" "$(hex64 reads-as-banked)")"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$H" "$H" "$(hex64 reads-as-now)")

    CURRENT="an identical tree whose read-set moved is attributed to env-reads"
    token=$(attr_token SAMETREE ENVB "$want")
    is "$token" "env:env-reads" "the token"

    CURRENT="and the four it has always named still name themselves"
    LOOP_ENV_COMPONENTS=$(crafted_components "$(hex64 other)" "" "$D" "$H" "$H" "$(hex64 reads-as-banked)")
    is "$(attr_token SAMETREE ENVB "$want")" "env:env-file" "the token when the .env digest moved"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$(hex64 other)" "$H" "$H" "$(hex64 reads-as-banked)")
    is "$(attr_token SAMETREE ENVB "$want")" "env:dists" "the token when the distribution census moved"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$(sha40 elsewhere)" "$H" "$(hex64 reads-as-banked)")
    is "$(attr_token SAMETREE ENVB "$want")" "env:head" "the token when HEAD moved"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$H" "$(sha40 elsewhere)" "$(hex64 reads-as-banked)")
    is "$(attr_token SAMETREE ENVB "$want")" "env:merge-base" "the token when the merge-base moved"
    LOOP_ENV_COMPONENTS=""
}

case_a_checkout_with_no_census_says_so_and_a_broken_read_refuses() {
    # THE THREE ANSWERS, AND THEY ARE DIFFERENT THINGS. A scratch checkout is
    # NOT this tree and every one of them answers `no-census`, deterministically
    # — which is what lets every other case in this drive keep a stable key. An
    # owner that is HERE and could not be read is could-not-look: no key, no
    # reuse, the same disposition the distribution census takes.
    fresh_checkout
    CURRENT="a checkout with no quality/partition.py declares the absence"
    is "$(cd "$REPO" && loop_env_reads)" "no-census" "the read-set component"

    CURRENT="and the declared absence is a legal component, not a malformation"
    is "$(loop_components_malformed "$(crafted_components "" "" "" "" "" no-census)")" "" \
        "the malformed-field report for a no-census row"
    if [ -z "$(loop_components_malformed "$(crafted_components "" "" "" "" "" "not-a-digest")")" ]; then
        bad "a read-set component that is neither a digest nor no-census reads as well-formed"
    else
        ok "anything else in the field is refused by name: $(loop_components_malformed "$(crafted_components "" "" "" "" "" "not-a-digest")")"
    fi

    CURRENT="a seam file that is empty is a read that did not answer"
    N=$((N + 1))
    DJB_LOOP_ENV_READS="${WORK}/env-reads-empty${N}"
    : >"$DJB_LOOP_ENV_READS"
    export DJB_LOOP_ENV_READS
    RC=0
    (cd "$REPO" && loop_env_reads) >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "loop_env_reads' exit status on an empty census"
    CURRENT="and no key is derived when the census could not answer"
    RC=0
    (cd "$REPO" && loop_ledger_key treeone "mode=fast scope=- always=abc") >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "loop_ledger_key's exit status"
    unset DJB_LOOP_ENV_READS
}

# --- the key, and the scope field --------------------------------------------

case_the_same_tree_at_two_scopes_is_two_keys() {
    fresh_checkout
    local narrow wide
    narrow=$(in_repo "$REPO" loop_ledger_key deadbeef "mode=fast own=usage scope=usage always=abc")
    wide=$(in_repo "$REPO" loop_ledger_key deadbeef "mode=fast own=usage scope=usage files always=abc")
    CURRENT="the same tree at two scopes is two keys"
    differs "$narrow" "$wide" "a wider scope derives a different key"
}

case_a_wider_scope_never_reads_a_narrower_verdict() {
    fresh_checkout
    : >"$DJB_LOOP_LEDGER"
    local narrow wide
    narrow=$(in_repo "$REPO" loop_ledger_key deadbeef "mode=fast own=usage scope=usage always=abc")
    wide=$(in_repo "$REPO" loop_ledger_key deadbeef "mode=fast own=usage scope=core usage always=abc")
    in_repo "$REPO" loop_ledger_record "$narrow" "mode=fast own=usage scope=usage always=abc" ||
        cannot_look "could not record the narrow verdict the case needs"
    CURRENT="the narrow verdict is a hit for the narrow scope"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$narrow" >/dev/null 2>&1 || RC=$?
    is "$RC" "0" "the narrow lookup"
    CURRENT="a WIDER scope gets no reuse from it"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$wide" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the wider lookup"
}

case_the_tree_and_the_environment_are_both_in_the_key() {
    fresh_checkout
    local a b c
    a=$(in_repo "$REPO" loop_ledger_key treeone "mode=fast scope=- always=abc")
    b=$(in_repo "$REPO" loop_ledger_key treetwo "mode=fast scope=- always=abc")
    CURRENT="the measured tree is in the key"
    differs "$a" "$b" "a different tree derives a different key"
    printf 'DATABASE_NAME=djb_checkout_one\nSECRET_KEY=different\nDEBUG=1\n' >"$REPO/.env" # pragma: allowlist secret
    c=$(in_repo "$REPO" loop_ledger_key treeone "mode=fast scope=- always=abc")
    CURRENT="the environment is in the key"
    differs "$a" "$c" "a different environment derives a different key"
}

case_an_unreadable_always_on_declaration_is_refused_on_write() {
    fresh_checkout
    : >"$DJB_LOOP_LEDGER"
    local key
    key=$(in_repo "$REPO" loop_ledger_key deadbeef "mode=fast scope=- always=UNDECLARED")
    CURRENT="a scope whose always-on declaration could not be read is refused on WRITE"
    N=$((N + 1))
    OUT="${WORK}/undeclared${N}.log"
    RC=0
    in_repo "$REPO" loop_ledger_record "$key" "mode=fast scope=- always=UNDECLARED" >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"
    if grep -qF "could not be read" "$OUT"; then
        ok "it names the unreadable declaration"
    else
        bad "it does not name the unreadable declaration"
    fi
    CURRENT="and so it can never be a hit"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$key" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the lookup for a key that was never allowed to be written"
}

# --- the fail-closed direction -----------------------------------------------

case_every_doubt_is_a_miss_and_never_an_exit_2_on_the_consult_path() {
    fresh_checkout
    local key
    key=$(in_repo "$REPO" loop_ledger_key deadbeef "mode=fast scope=- always=abc")

    CURRENT="no ledger file is a miss"
    rm -f "$DJB_LOOP_LEDGER"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$key" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the lookup with no ledger at all"

    CURRENT="a malformed key is a miss on read"
    : >"$DJB_LOOP_LEDGER"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "not-a-key" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the lookup for a key that is not a key"

    CURRENT="a malformed key is a REFUSAL on write"
    N=$((N + 1))
    OUT="${WORK}/malformed${N}.log"
    RC=0
    in_repo "$REPO" loop_ledger_record "not-a-key" "mode=fast scope=- always=abc" >"$OUT" 2>&1 || RC=$?
    is "$RC" "2" "the exit status"

    CURRENT="a row tagged with a schema this build does not know is not a hit"
    printf 'loop-v999 %s loop 2026-01-01T00:00:00Z caller=unstated scope=x\n' "$key" >"$DJB_LOOP_LEDGER"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$key" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the lookup against a future-schema row"

    CURRENT="a corrupt ledger is a miss, never a gate"
    printf 'this is not a row at all\n' >"$DJB_LOOP_LEDGER"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$key" >/dev/null 2>&1 || RC=$?
    # NEVER EXIT 2 ON THE CONSULT PATH. A cache that can break a gate is worse
    # than no cache: the whole point of the fail-closed direction is that every
    # doubt costs a re-measure and nothing else.
    if [ "$RC" = "2" ]; then
        bad "a corrupt ledger exited 2 on the CONSULT path — a broken cache must cost a re-run, never a gate"
    else
        is "$RC" "1" "the lookup against a corrupt ledger"
    fi

    # THE ATTRIBUTOR IS ON THE SAME PATH AND HAS THE SAME DEAL. It now reads
    # five fields off a row and runs `git` against the head it finds there —
    # two more ways to be handed nonsense, and neither of them may become a
    # status.
    local scope="mode=fast_scope=-_always=abc" want="mode=fast scope=- always=abc"
    local E D
    E=$(hex64 envfile)
    D=$(hex64 dists)

    CURRENT="a row whose components are malformed is unmatched, and the field is named"
    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" TREEA ENVA "env-file=not-a-digest excluded=X dists=${D} head=$(sha40 h) merge-base=$(sha40 b)"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$(sha40 h)" "$(sha40 b)")
    N=$((N + 1))
    OUT="${WORK}/malformedrow${N}.log"
    RC=0
    in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    is "$(sed -n '1p' "$OUT")" "unmatched" "the token"
    if grep -F "env-file (not a digest)" "$OUT" >/dev/null; then
        ok "the detail names the malformed field"
    else
        bad "the detail does not name the malformed field"
    fi

    CURRENT="a row missing a component is unmatched, and the field is named"
    : >"$DJB_LOOP_LEDGER"
    # EVERY FIELD BUT THE LAST ONE, so the case keeps naming the field it says
    # it names. `loop_components_malformed` reports the FIRST field it cannot
    # read, in `LOOP_ENV_COMPONENT_FIELDS` order, so a row that omitted an
    # earlier one would go on passing while asserting about a different field —
    # which is what this line stopped doing when `env-reads` was inserted ahead
    # of `head` (R3's F2x).
    plant_row "$scope" TREEA ENVA \
        "env-file=${E} excluded=X dists=${D} env-reads=$(hex64 reads) head=$(sha40 h)"
    N=$((N + 1))
    OUT="${WORK}/missingfield${N}.log"
    RC=0
    in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    is "$(sed -n '1p' "$OUT")" "unmatched" "the token"
    if grep -F "merge-base (missing)" "$OUT" >/dev/null; then
        ok "the detail names the missing field"
    else
        bad "the detail does not name the missing field"
    fi

    CURRENT="a banked head this repository has never heard of is a NAMED absence, not a failure"
    : >"$DJB_LOOP_LEDGER"
    # THE UNKNOWN HEAD IS ASSEMBLED, NEVER SPELLED. Forty hex characters in a
    # row is a high-entropy string to every scanner in this tree, and a fixture
    # that must carry one keeps it out of the file's TEXT rather than spending a
    # pragma on it — the idiom is `archaeology_patterns`'s in
    # scripts/archaeology_lib.sh, and the secrets leg found this line the first
    # time it was written out in full.
    local unknown_head
    unknown_head="$(printf '0123456789abcdef%.0s' 1 2)01234567"
    plant_row "$scope" TREEA ENVA \
        "$(crafted_components "$E" "" "$D" "$unknown_head" "$(sha40 b)")"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" "$(sha40 hnow)" "$(sha40 b)")
    N=$((N + 1))
    OUT="${WORK}/unknownhead${N}.log"
    RC=0
    in_repo "$REPO" loop_ledger_attribute TREEB ENVB "$want" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status"
    is "$(sed -n '1p' "$OUT")" "tree" "the token"
    if grep -F "since banked head: not derivable (01234567 is not a commit in this repository)" "$OUT" >/dev/null; then
        ok "the detail says which head it could not resolve, and why"
    else
        bad "the unresolvable head did not produce a named absence"
    fi
    OUT=""
    LOOP_ENV_COMPONENTS=""
}

case_the_banner_takes_line_one_as_the_token_and_indents_the_rest() {
    # THE STDOUT CONTRACT, READ OUT OF check.sh RATHER THAN RE-IMPLEMENTED.
    # The attributor's first line is the token and the rest is detail; a banner
    # that printed the whole thing inside `miss(...)` would put a git-derived
    # sentence in the place a ledger row's typed cell is copied from.
    CURRENT="check.sh splits the attribution into a token and a detail"
    if grep -F 'LOOP_MISS_TOKEN=${LOOP_MISS_WHY%%' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the token is the first line of the attributor's stdout"
    else
        bad "check.sh does not take the attributor's first line as the token"
    fi
    CURRENT="and the banner prints miss(<token>), never miss(<the whole answer>)"
    if grep -F 'MISSED: miss(${LOOP_MISS_TOKEN})' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the banner interpolates the token alone"
    else
        bad "the banner does not interpolate LOOP_MISS_TOKEN"
    fi
    CURRENT="and the detail lines are printed under it"
    if grep -F 'printf '"'"'%s\n'"'"' "$LOOP_MISS_DETAIL"' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the rest of the attribution is printed rather than dropped"
    else
        bad "check.sh derives a detail it never prints — the git-derived counter would reach nobody"
    fi
    CURRENT="the by-eye instruction is replaced by the sentence the token earns"
    if grep -F "The token names the component" "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the banner says the token names the component"
    else
        bad "the banner still sends the reader to a second banner as the only way"
    fi
}

case_a_recorded_row_round_trips() {
    fresh_checkout
    : >"$DJB_LOOP_LEDGER"
    local key scope
    scope="mode=fast scope=usage always=abc"
    key=$(in_repo "$REPO" loop_ledger_key deadbeef "$scope")
    in_repo "$REPO" loop_ledger_record "$key" "$scope" ||
        cannot_look "could not record a well-formed verdict"
    CURRENT="a well-formed verdict round-trips"
    N=$((N + 1))
    OUT="${WORK}/roundtrip${N}.log"
    RC=0
    in_repo "$REPO" loop_ledger_lookup "$key" >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the lookup"
    if grep -qF "$key" "$OUT"; then
        ok "the row carries the key"
    else
        bad "the row does not carry the key"
    fi
    CURRENT="the row records the SCOPE it was earned at"
    if grep -qF "scope=" "$OUT"; then
        ok "the row records its scope, so a reader can see what green meant"
    else
        bad "the row does not record its scope"
    fi
    # THE SEED-2 INTAKE. "Green" means one pass here and two at the full gate,
    # and the day either changes every older row silently starts meaning
    # something else. The row says which.
    #
    # `passes=` WAS THE LAST FIELD AND IS NOW THE THIRD-FROM-LAST, and that is
    # the precedent working rather than breaking: `tree=` and `env=` were
    # appended AFTER it by the c1 rider, exactly as `passes=` was appended after
    # `scope=`, so every line written before either change still parses. What
    # this case is actually about is that the row SAYS WHAT RAN — so it asserts
    # the field is there and that nothing but the two appended fields follows
    # it, which is the property "appended last" was ever a proxy for.
    CURRENT="the row records HOW MANY PASSES earned it, and only appended fields follow"
    # The appended set has grown twice now — `tree=`/`env=` by the c1 rider, then
    # `waited=`/`took=` — so the assertion names the fields that may follow
    # rather than the one that must be last. What "appended last" was ever a
    # proxy for is this: nothing INSERTS itself between `passes=` and the end.
    if grep -qE 'passes=[0-9]+( tree=[^ ]+ env=[^ ]+)?( waited=[0-9]+ took=[0-9]+)?$' "$OUT"; then
        ok "the row carries passes=<n>, followed only by the appended tree=/env= and waited=/took="
    else
        bad "the row does not carry passes=<n> in the appended-field shape — a verdict that does not say what ran cannot be audited later"
    fi
    CURRENT="and this leg records ONE pass, because it runs one"
    if grep -qF "passes=1" "$OUT"; then
        ok "passes=1, matching scripts/test.sh's single pytest invocation"
    else
        bad "the recorded pass count is not 1"
    fi
}

case_the_local_loop_really_is_one_pass() {
    # THE PREMISE THE ROW ABOVE ASSERTS, checked against the code rather than
    # remembered. `scripts/test.sh` ends in exactly one `uv run pytest`, and
    # check.sh's two `--loop` invocations are the arms of ONE if/else — so a
    # second local pass appearing anywhere makes `passes=1` a lie.
    CURRENT="scripts/test.sh makes exactly one pytest invocation"
    local n
    n=$(grep -cE '^[[:space:]]*uv run pytest' "$ROOT/scripts/test.sh")
    is "$n" "1" "the number of pytest invocations in test.sh"
    CURRENT="the full gate's two passes are still the full gate's"
    n=$(grep -cE '^[[:space:]]*\./scripts/test\.sh .*--randomly-seed="\$PYTEST_SEED"' "$ROOT/scripts/check.sh")
    is "$n" "2" "the number of seeded whole-suite passes (the pytest-x2 leg)"
}

# --- the wiring, and the superseded sentence ---------------------------------

case_the_leg_consults_before_it_measures_and_records_only_after_green() {
    CURRENT="check.sh consults the loop ledger before the first leg"
    if grep -q "loop_ledger_lookup" "$ROOT/scripts/check.sh"; then
        ok "the consult is wired"
    else
        bad "nothing in check.sh consults the loop ledger — the cache is write-only"
    fi
    CURRENT="check.sh records only after a complete green --loop"
    # The record call must sit AFTER the leg's own success line, not before it.
    local ok_line record_line
    # ANCHORED TO A CALL, NOT A MENTION. `loop_ledger_record` is named in prose
    # elsewhere in check.sh — a comment saying which global a recorder reads is
    # not a recording, and an unanchored grep read the earliest COMMENT as the
    # record site and reported the ordering broken.
    ok_line=$(grep -n 'ok: loop checks passed' "$ROOT/scripts/check.sh" | head -1 | cut -d: -f1)
    record_line=$(grep -nE '^[[:space:]]*(if )?loop_ledger_record ' "$ROOT/scripts/check.sh" | head -1 | cut -d: -f1)
    if [ -n "$ok_line" ] && [ -n "$record_line" ] && [ "$record_line" -gt "$ok_line" ]; then
        ok "the record (line ${record_line}) comes after the green (line ${ok_line})"
    else
        bad "the record does not sit after the leg's green line: green=${ok_line:-?} record=${record_line:-?}"
    fi
    CURRENT="the key is re-derived and compared at the end of the run"
    if grep -q 'LOOP_LEDGER_KEY_END' "$ROOT/scripts/check.sh"; then
        ok "the end-of-run key is derived and compared — a tree that moved mid-run banks nothing"
    else
        bad "nothing re-derives the key at the end: a run that started on one tree and finished on another would bank a verdict about neither"
    fi
}

case_the_superseded_sentence_was_superseded_in_the_same_commit() {
    CURRENT="the ledger no longer claims --loop writes nothing anywhere"
    # THE DRIFT CLASS, PRE-EMPTED. The sentence was true until the active rung made it
    # false; a superseded sentence left standing is a lie the next reader trusts.
    if grep -qF -- "--fast and --loop write nothing anywhere" "$ROOT/scripts/gate_ledger.sh"; then
        bad "gate_ledger.sh still says '--fast and --loop write nothing anywhere', which the loop ledger makes false"
    else
        ok "the superseded sentence is gone"
    fi
    CURRENT="and it says what is true instead"
    if grep -qF "superseded" "$ROOT/scripts/gate_ledger.sh"; then
        ok "the replacement names itself as a supersession rather than quietly editing"
    else
        bad "nothing records that the sentence was superseded"
    fi
    CURRENT="--fast still writes nothing"
    if grep -qF '\`--fast\` writes nothing anywhere' "$ROOT/scripts/gate_ledger.sh" ||
        grep -qF "fast\` writes nothing anywhere" "$ROOT/scripts/gate_ledger.sh"; then
        ok "the half of the sentence that is still true is still said"
    else
        bad "the new sentence does not say that --fast still writes nothing"
    fi
}

case_no_pipeline_tail_in_this_territory_still_uses_grep_q() {
    # GQ-1'S RIDER, PINNED HERE SO IT CANNOT REGROW. `producer | grep -q P`
    # under `set -o pipefail`: grep exits on the first match, the pipe closes
    # under the producer, a producer with more than the 64KiB pipe buffer left
    # to write takes SIGPIPE and dies 141, and pipefail reports a MATCH as a
    # failure. Deterministic above the buffer size.
    local f hits=""
    for f in scripts/check.sh scripts/gate_ledger.sh scripts/loop_tier.sh scripts/secrets_scan.sh; do
        if grep -nE '\|[[:space:]]*grep[[:space:]]+(-[A-Za-z]*q[A-Za-z]*[[:space:]])' "$ROOT/$f" >/dev/null 2>&1; then
            hits="${hits}${hits:+ }$f"
        fi
    done
    CURRENT="no '| grep -q' at a pipeline tail in the selection machinery"
    if [ -n "$hits" ]; then
        bad "still present in: ${hits} — convert to '| grep PATTERN >/dev/null', flags preserved"
    else
        ok "every converted site uses '| grep PATTERN >/dev/null'"
    fi
    # AND THE FIX IS REAL, not a deletion: the sites still match what they
    # matched, which is what a flags-preserved conversion means.
    CURRENT="the converted sites kept their flags and their redirect"
    if grep -qF "grep -E \"\$PARTITION_KEY_RE\" >/dev/null" "$ROOT/scripts/gate_ledger.sh"; then
        ok "gate_ledger.sh's partition-key check kept -E and gained the redirect"
    else
        bad "gate_ledger.sh's partition-key check is not in the converted form"
    fi
}

case_the_pipe_race_is_real_above_the_buffer_and_the_new_form_survives_it() {
    # RED-FIRST, on this machine, with a PADDED PRODUCER. The two sites this
    # rung converted both have tiny producers and could never reach the buffer,
    # so the reproduction is built rather than found: the class is shown to be
    # real, and the shipped form is shown to survive it.
    local red=0 green=0
    set +e
    (
        set -o pipefail
        # 200KiB of output, well past the 64KiB pipe buffer, with the match at
        # the very start so `-q` exits immediately and the producer is still
        # writing.
        {
            echo "MATCH"
            "$ROOT/.venv/bin/python" -c "print('x' * 200000)"
        } | grep -q MATCH
    )
    red=$?
    (
        set -o pipefail
        {
            echo "MATCH"
            "$ROOT/.venv/bin/python" -c "print('x' * 200000)"
        } | grep MATCH >/dev/null
    )
    green=$?
    set -e
    CURRENT="the pipe race reproduces above the 64KiB buffer"
    if [ "$red" = "0" ]; then
        # HONEST NON-REPRODUCTION rather than a silent pass: on some greps and
        # some shells the match is late enough or the producer small enough that
        # SIGPIPE never arrives. The conversion is a belt either way and this
        # says which it was.
        ok "NOT REPRODUCED on this machine (grep -q returned 0 even padded) — the conversion is belt, not repair, and this case records that honestly"
    else
        ok "reproduced: '| grep -q' under pipefail returned ${red} on a MATCH"
    fi
    CURRENT="the shipped form survives the same producer"
    is "$green" "0" "'| grep PATTERN >/dev/null' on the same padded producer"
}

# --- the tracked paths a leg DERIVES -----------------------------------------
#
# THE CLASS, IN ONE SENTENCE: a leg that WRITES into the tracked tree on a green
# run moves the very hash the verdict is keyed on, so the gate passes every leg
# and then banks nothing. The sibling platform's visual leg publishes one
# machine-dependent picture per (fixture x width) into a committed directory and
# paid it in full — `ok: all checks passed (1014s)` and then `no verdict
# recorded — the tree changed while the gate ran`: seventeen minutes of green
# vouching for nothing, and the next stage measuring the whole thing again.
#
# THIS TREE HAS NO SUCH LEG TODAY, and these cases say so out loud rather than
# implying a population: `case_an_empty_derived_declaration_leaves_the_key_unchanged`
# asserts the discovered set here is EMPTY, and every other case below PLANTS
# the member it measures. So the first real declaration will be the first time
# the mechanism meets a member nobody planted — a declared blind spot, not a
# silence.
#
# WHAT THIS DRIVE CANNOT SEE, stated where the cases are rather than at the top:
# whether a declared path is really UNREAD. The exclusion is legal on exactly one
# claim — nothing the gate measures reads the excluded bytes back — and these
# cases assert that a declaration is OBEYED, that it is one repository-relative
# subtree, that an unreadable one excludes NOTHING, and that a path nothing
# tracks is refused. "No check anywhere reads this path" is not a property a
# shell drive can see; it is a reviewer's, and the sentence naming that duty
# belongs beside the declaration rather than here.

# tree_in <repo> — the FULL gate's own key, `gate_measured_tree`, computed
# inside the fixture. The `--loop` key carries it as one component, so a case
# that only ever asserted `loop_verdict_key` would leave the tier where this
# defect actually bites — the full gate's bank — unasserted.
tree_in() { in_repo "$1" gate_measured_tree 2>/dev/null; }

# tree_without_exclusion <repo> — the key exactly as `gate_measured_tree`
# computed it before this mechanism existed: read-tree, add -A, write-tree, and
# no exclusion step at all. A deliberate second copy, and it has one job: the
# equality in `case_an_empty_derived_declaration_leaves_the_key_unchanged`. With
# nothing declared the new key must be the OLD key, byte for byte, or every
# verdict banked before the exclusion existed silently stopped being a hit.
tree_without_exclusion() {
    local repo="$1" idx tree
    idx=$(mktemp "${WORK}/pre-exclusion-index.XXXXXX") || return 1
    rm -f "$idx"
    if ! GIT_INDEX_FILE="$idx" git -C "$repo" read-tree HEAD >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    if ! GIT_INDEX_FILE="$idx" git -C "$repo" add -A >/dev/null 2>&1; then
        rm -f "$idx"
        return 1
    fi
    tree=$(GIT_INDEX_FILE="$idx" git -C "$repo" write-tree 2>/dev/null)
    rm -f "$idx"
    [ -n "$tree" ] || return 1
    printf '%s\n' "$tree"
}

# plant_derived_leg <repo> <entry>... — a leg in the scratch checkout that
# declares, in the sentinel shape, BESIDE ITSELF. It is written into `scripts/`
# because that is one of the globs the reader scans, and a declaration somewhere
# the reader does not look is not a declaration.
plant_derived_leg() {
    local repo="$1" entry
    shift
    {
        echo "#!/usr/bin/env bash"
        echo "# A planted leg. It republishes derived/ on every green run, and the"
        echo "# bytes differ per box. Nothing measured reads them back."
        echo "# >>> derived-tree-paths >>>"
        for entry in "$@"; do echo "# ${entry}"; done
        echo "# <<< derived-tree-paths <<<"
    } >"${repo}/scripts/planted_leg.sh"
}

# plant_derived_member <repo> — the artefact itself, TRACKED and COMMITTED
# exactly as the real one is (that is the whole premise: a committed path whose
# bytes churn per box), plus `derived.txt` BESIDE it — a path carrying the
# declared path as a name prefix, which an exclusion done by string prefix
# rather than by subtree would swallow, and a swallowed path is a false hit.
plant_derived_member() {
    local repo="$1"
    mkdir -p "${repo}/derived"
    printf 'the accepted look, as this box draws it\n' >"${repo}/derived/planted.png"
    printf 'measured: yes\n' >"${repo}/derived.txt"
    git -C "$repo" add -A >/dev/null 2>&1 || return 1
    git -C "$repo" commit -q -m "the derived artefact, committed as the real one is"
}

# declared_in <repo> — the discovered declaration as one space-separated line,
# or the empty string. Reads stdout only: a refusal's note goes to stderr and a
# case that swallowed it would be asserting against the wrong stream.
declared_in() {
    local out=""
    # A REFUSAL AND A MISSING READER BOTH READ AS NOTHING DECLARED, on purpose:
    # this drive runs under `set -euo pipefail`, and a reader that is not there
    # yet must produce a FAILED assertion rather than kill the drive on line one
    # of the red run.
    out=$(in_repo "$1" gate__derived_tree_paths 2>/dev/null) || out=""
    printf '%s' "$out" | tr '\n' ' ' | sed 's/ *$//'
}

# unreadable <what> — the reader run against the scratch checkout as it stands,
# asserting the three things a refusal owes: a non-zero status, NOTHING on
# stdout (an exclusion nobody could verify is never applied), and a line on
# stderr saying the key now measures the whole tree.
unreadable() {
    local what="$1" rc=0 err
    N=$((N + 1))
    OUT="${WORK}/derived-decl${N}.out"
    err="${WORK}/derived-decl${N}.err"
    in_repo "$REPO" gate__derived_tree_paths >"$OUT" 2>"$err" || rc=$?
    CURRENT="$what"
    is "$rc" "1" "the reader's exit status"
    is "$(awk 'END {print NR + 0}' <"$OUT")" "0" "the number of paths it excluded"
    if grep -q 'WHOLE tree' "$err" 2>/dev/null; then
        ok "and it SAYS SO: $(sed -n 's/^ *note: //p' "$err" | tr '\n' ' ' | sed 's/ *$//')"
    else
        OUT="$err"
        bad "the refusal was silent — a narrower key nobody was told about is the one outcome this must never have"
    fi
}

# plant_stray_derived_leg <repo> <relative path> <entry> — the SAME declaration
# `plant_derived_leg` writes, in a file the caller places. Used to put one
# inside a glob the reader scans and one outside it, with nothing else differing.
plant_stray_derived_leg() {
    local repo="$1" where="$2" entry="$3"
    mkdir -p "$(dirname "${repo}/${where}")"
    {
        echo "#!/usr/bin/env bash"
        echo "# A planted leg that declares in the wrong place."
        echo "# >>> derived-tree-paths >>>"
        echo "# ${entry}"
        echo "# <<< derived-tree-paths <<<"
    } >"${repo}/${where}"
    git -C "$repo" add -A >/dev/null 2>&1 || return 1
    git -C "$repo" commit -q -m "a declaration at ${where}"
}

# stray_read <what> — the reader over the scratch checkout, keeping stdout and
# stderr apart. The note this case is about goes to stderr, and a case that let
# the two streams merge would be asserting against the wrong one.
STRAY_ERR=""
STRAY_RC=0
stray_read() {
    STRAY_RC=0
    N=$((N + 1))
    CURRENT="$1"
    OUT="${WORK}/stray-decl${N}.out"
    STRAY_ERR="${WORK}/stray-decl${N}.err"
    in_repo "$REPO" gate__derived_tree_paths >"$OUT" 2>"$STRAY_ERR" || STRAY_RC=$?
}

case_a_declaration_outside_the_reader_sources_is_named() {
    # B4.5. `GATE_TREE_DECL_SOURCES` is three globs, and it is where a deriver
    # MAY declare itself — not a promise that a declaration anywhere else will be
    # found. A deriver that declares in, say, `scripts/tests/` declares into a
    # VOID: the reader never opens the file, nothing is excluded, the verdict key
    # is exactly what it was, and until this criterion nothing said a word. That
    # is the one failure here that is silent in the direction of a wasted
    # re-measure rather than a false hit, which is precisely why it could sit
    # unnoticed for a cycle.
    fresh_checkout
    plant_derived_member "$REPO" || cannot_look "the fixture would not commit its derived artefact"
    plant_stray_derived_leg "$REPO" "scripts/tests/planted_leg.sh" \
        "derived — republished on every green run; nothing measured reads it back" ||
        cannot_look "the fixture would not commit its stray declaration"

    local before after
    stray_read "a declaration outside the reader's sources is NAMED"
    # A NOTE, NOT A REFUSAL. Nothing was excluded, so the key is the key it
    # always was; turning one misplaced comment into an exit status would let it
    # stop every gate on the box.
    is "$STRAY_RC" "0" "the reader's exit status"
    is "$(awk 'END {print NR + 0}' <"$OUT")" "0" "the number of paths it excluded"
    if grep -qF -e "is not in a source the reader scans" "$STRAY_ERR" 2>/dev/null; then
        ok "the note fired: $(sed -n 's/^ *note: //p' "$STRAY_ERR" | tr '\n' ' ' | sed 's/ *$//')"
    else
        OUT="$STRAY_ERR"
        bad "the stray declaration was silent — a deriver that declared into a void would never learn it had"
    fi
    CURRENT="and the note NAMES the file, so the deriver can find its own mistake"
    if grep -qF -e "scripts/tests/planted_leg.sh" "$STRAY_ERR" 2>/dev/null; then
        ok "it names scripts/tests/planted_leg.sh"
    else
        OUT="$STRAY_ERR"
        bad "the note does not name the declaring file"
    fi

    # AND NOTHING WAS EXCLUDED, proven the only way that counts: a churn inside
    # the path the stray declaration NAMED still moves the key. An assertion that
    # only read the note would go green against a reader that printed the note
    # AND excluded the path anyway.
    CURRENT="the key is unchanged — a churn in the stray-declared path still moves it"
    before=$(tree_in "$REPO")
    printf 'antialiasing moved on this box\n' >"${REPO}/derived/planted.png"
    after=$(tree_in "$REPO")
    if [ -n "$before" ] && [ -n "$after" ] && [ "$before" != "$after" ]; then
        ok "the key moved, as it does for any undeclared path"
    else
        bad "the key did not move ('${before:-<none>}' -> '${after:-<none>}') — the stray declaration excluded something after all"
    fi
}

case_a_declaration_inside_the_reader_sources_prints_no_stray_note() {
    # THE CONTROL for the case above, and it is the half that makes the note
    # falsifiable: the identical file, the identical entry, moved into a glob the
    # reader does scan. No note, and the path really is excluded.
    fresh_checkout
    plant_derived_member "$REPO" || cannot_look "the fixture would not commit its derived artefact"
    plant_stray_derived_leg "$REPO" "scripts/planted_leg.sh" \
        "derived — republished on every green run; nothing measured reads it back" ||
        cannot_look "the fixture would not commit its declaration"

    stray_read "the same declaration INSIDE a scanned source prints no such note"
    is "$STRAY_RC" "0" "the reader's exit status"
    is "$(declared_in "$REPO")" "derived" "the declared derived paths"
    if grep -qF -e "is not in a source the reader scans" "$STRAY_ERR" 2>/dev/null; then
        OUT="$STRAY_ERR"
        bad "a declaration the reader DID open was reported as a stray one — the note cannot tell the two apart"
    else
        ok "no stray note"
    fi
}

case_a_planted_churn_in_a_declared_derived_path_does_not_move_the_key() {
    fresh_checkout
    plant_derived_leg "$REPO" \
        "derived — republished by the planted leg on every green run; the bytes are machine-dependent and nothing measured reads them back"
    plant_derived_member "$REPO" || cannot_look "the fixture would not commit its derived artefact"

    CURRENT="the planted declaration is discovered, and it is the only one"
    is "$(declared_in "$REPO")" "derived" "the declared derived paths"

    local before after
    CURRENT="a REWRITTEN file inside the declared path leaves the verdict key where it was"
    before=$(tree_in "$REPO")
    printf 'antialiasing moved on this box\n' >"${REPO}/derived/planted.png"
    after=$(tree_in "$REPO")
    same "$before" "$after" "the key survives a rewrite of a declared derived file"

    # THE UNBOUNDED HALF. The set a green run republishes is not a named pair: a
    # box publishes a file another box does not, so a NEW file inside the
    # declared subtree must be as invisible as a rewritten one. The canary that
    # an untracked file ELSEWHERE does move the key already stands in this
    # drive, which is what makes this an assertion about the declaration rather
    # than about untracked-ness.
    CURRENT="a NEW file inside the declared path is as invisible as a rewritten one"
    before="$after"
    printf 'a fixture this box publishes and another does not\n' >"${REPO}/derived/planted-390.png"
    after=$(tree_in "$REPO")
    same "$before" "$after" "the key survives a new untracked file inside the declared path"

    CURRENT="and the key is still a git object id, not an empty refusal wearing equality"
    is "$(printf '%s' "$after" | grep -cE '^[0-9a-f]{40,64}$')" "1" "the key's shape"

    # THE FILES ARE STILL THERE. The exclusion is a property of a throwaway
    # index, never of the working tree: the artefact stays tracked, committed
    # and reviewable, and only the KEY stops seeing it.
    CURRENT="the declared path is still tracked — only the key stopped seeing it"
    is "$(in_repo "$REPO" git ls-files derived | awk 'END {print NR + 0}')" "1" "tracked files under the declared path"

    CURRENT="a file BESIDE the declared path, carrying its name as a prefix, still moves the key"
    before="$after"
    printf 'measured: no\n' >"${REPO}/derived.txt"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "an exclusion done by name prefix rather than by subtree would be a false hit"

    CURRENT="an ordinary source byte still moves the key"
    before="$after"
    printf 'moved\n' >"${REPO}/README.md"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "the exclusion has not eaten the tree"

    # THE ANTI-COINCIDENCE. Without this the equalities above are satisfiable by
    # an exclusion that never read the declaration at all.
    CURRENT="with the declaration gone, the SAME churn moves the key again"
    rm -f "${REPO}/scripts/planted_leg.sh"
    is "$(declared_in "$REPO")" "" "the declarations discovered after the deletion"
    before=$(tree_in "$REPO")
    printf 'churn, visible again\n' >"${REPO}/derived/planted.png"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "this is the defect the declaration answers"
}

case_a_churn_in_an_undeclared_path_still_moves_the_key() {
    fresh_checkout
    plant_derived_leg "$REPO" \
        "derived — republished by the planted leg on every green run; nothing measured reads it back"
    plant_derived_member "$REPO" || cannot_look "the fixture would not commit its derived artefact"

    local before after
    CURRENT="the SAME churn on an UNDECLARED tracked file moves the key"
    before=$(tree_in "$REPO")
    printf 'a tracked file the declaration never named\n' >"${REPO}/README.md"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "a declaration excludes what it names and nothing else"

    CURRENT="an untracked file outside the declared path moves it too"
    before="$after"
    printf 'a scratch file nobody declared\n' >"${REPO}/stray-artefact.png"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "the exclusion is not 'artefacts', it is one declared subtree"

    CURRENT="a file whose NAME matches inside an undeclared directory moves it"
    before="$after"
    mkdir -p "${REPO}/elsewhere/derived"
    printf 'the same basename, somewhere nobody declared\n' >"${REPO}/elsewhere/derived/planted.png"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "the exclusion is anchored at the repository root, not matched anywhere"
}

case_an_unreadable_derived_declaration_excludes_nothing_and_says_so() {
    fresh_checkout
    plant_derived_leg "$REPO" \
        "derived — republished on every green run; nothing measured reads it back"
    plant_derived_member "$REPO" || cannot_look "the fixture would not commit its derived artefact"

    local before after

    # (a) OPENED AND NEVER CLOSED. The shape a bad merge or a truncated edit
    # leaves behind, and the one where a reader that simply kept going would
    # swallow the whole rest of the file as declarations.
    {
        echo "#!/usr/bin/env bash"
        echo "# >>> derived-tree-paths >>>"
        echo "# derived — republished on every green run"
        echo "# and then the block was never closed"
    } >"${REPO}/scripts/planted_leg.sh"
    unreadable "a declaration opened and never closed excludes NOTHING"

    CURRENT="and the key is computed over the WHOLE tree while it is unreadable"
    before=$(tree_in "$REPO")
    printf 'churn under an unreadable declaration\n' >"${REPO}/derived/planted.png"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "an unreadable declaration is a re-measure, never a hit on an exclusion nobody could verify"

    # (b) NOT PLAINLY ONE SUBTREE. `.`, `/` and a `..` escape are what a typo
    # or a copy-paste produces, and obeying one would make every verdict a false
    # hit about a tree nothing measured.
    plant_derived_leg "$REPO" ". — the whole tree, by typo"
    unreadable "a declaration of '.' excludes NOTHING"
    plant_derived_leg "$REPO" "/ — the filesystem, by typo"
    unreadable "a declaration of '/' excludes NOTHING"
    plant_derived_leg "$REPO" "../outside — an escape out of the checkout"
    unreadable "a '..' escape excludes NOTHING"
    plant_derived_leg "$REPO" "/var/tmp/elsewhere — an absolute path"
    unreadable "an absolute path excludes NOTHING"

    # (c) PROSE. The em-dash entry form is the same one the derived-env-key
    # declaration stands on, and for the same measured reason: a declaration a
    # paragraph can accidentally satisfy is not a declaration. Here the
    # paragraph is REFUSED rather than skipped, because a block holding prose is
    # a block somebody wrote wrong, and the safe answer is to exclude nothing
    # and say so.
    plant_derived_leg "$REPO" "A property of WHERE this tree is, never of what is in it"
    unreadable "prose inside the sentinel block excludes NOTHING"

    # (d) A PATH NOTHING TRACKS. The premise of the whole mechanism is a
    # COMMITTED artefact whose bytes churn; a declaration naming a path no
    # commit holds is a declaration about something else, and it is refused
    # rather than quietly applied to whatever appears there later.
    plant_derived_leg "$REPO" "never-committed — a path no commit holds"
    unreadable "a declared path nothing tracks excludes NOTHING"

    # AND THE WAY BACK. A readable declaration after all of those is obeyed —
    # so the refusals above are the reader judging its input, not a mechanism
    # that fell over and stayed down.
    plant_derived_leg "$REPO" \
        "derived — republished on every green run; nothing measured reads it back"
    CURRENT="a readable declaration after the unreadable ones is obeyed again"
    is "$(declared_in "$REPO")" "derived" "the declared derived paths"
    before=$(tree_in "$REPO")
    printf 'and the churn is invisible once more\n' >"${REPO}/derived/planted.png"
    after=$(tree_in "$REPO")
    same "$before" "$after" "the reader recovered"
}

case_an_empty_derived_declaration_leaves_the_key_unchanged() {
    # ZERO MEMBERS IS LEGAL, AND THIS IS WHERE IT IS PRINTED. No leg in this
    # repository publishes a committed derived artefact today, so the discovered
    # population is empty — and an empty population must leave the key exactly
    # where it was, or every verdict banked before the exclusion existed stops
    # hitting.
    CURRENT="this repository declares no derived paths today"
    local declared
    declared=$(declared_in "$ROOT")
    is "$declared" "" "the declared derived paths on the real tree"

    CURRENT="and the reader says so with a 0 status, not a refusal"
    local rc=0
    N=$((N + 1))
    OUT="${WORK}/real-decl${N}.log"
    in_repo "$ROOT" gate__derived_tree_paths >"$OUT" 2>&1 || rc=$?
    is "$rc" "0" "the reader's exit status on the real tree"

    CURRENT="so the real tree's key is byte-identical to the pre-exclusion key"
    is "$(tree_in "$ROOT")" "$(tree_without_exclusion "$ROOT")" "gate_measured_tree against the key as it was computed before this mechanism"

    # And in the fixture, where a dirty tree can be arranged on purpose: the
    # same equality with untracked and modified files present, which is the
    # state a gate actually measures.
    fresh_checkout
    printf 'an untracked file\n' >"${REPO}/untracked.txt"
    printf 'a modified one\n' >"${REPO}/README.md"
    CURRENT="and so is a DIRTY tree's, with nothing declared"
    is "$(tree_in "$REPO")" "$(tree_without_exclusion "$REPO")" "the fixture's key with untracked and modified files present"

    CURRENT="and on a clean tree it is still HEAD's own tree object"
    fresh_checkout
    is "$(tree_in "$REPO")" "$(in_repo "$REPO" git rev-parse 'HEAD^{tree}')" "the ledger header's first property"

    # AND THE READER'S OWN SENTINEL CONSTANTS DECLARE NOTHING. The library holds
    # both sentinel strings, in a file the scan reads, so "the real tree
    # declares nothing" is only honest if a sentinel in CODE opens no block. It
    # is pinned here rather than left to the two assignments happening to sit on
    # consecutive lines, which is a property the next edit to that file can lose
    # without noticing.
    fresh_checkout
    {
        echo "#!/usr/bin/env bash"
        echo "DECL_BEGIN='>>> derived-tree-paths >>>'"
        echo "planted=derived"
        echo "DECL_END='<<< derived-tree-paths <<<'"
    } >"${REPO}/scripts/planted_leg.sh"
    plant_derived_member "$REPO" || cannot_look "the fixture would not commit its derived artefact"
    CURRENT="a sentinel in CODE rather than in a comment opens no declaration"
    is "$(declared_in "$REPO")" "" "the declarations discovered"
    local rc_code=0
    N=$((N + 1))
    OUT="${WORK}/code-sentinel${N}.log"
    in_repo "$REPO" gate__derived_tree_paths >"$OUT" 2>&1 || rc_code=$?
    is "$rc_code" "0" "the reader's exit status — no block was opened, so there is nothing to refuse"
    local before after
    before=$(tree_in "$REPO")
    printf 'churn nobody declared\n' >"${REPO}/derived/planted.png"
    after=$(tree_in "$REPO")
    differs "$before" "$after" "and the churn still moves the key, because nothing was declared"
}

# --- the docs-only pytest reuse, and the rider that made it a default line ----
#
# THE PROPERTY THESE CASES ARE ABOUT. A `--loop` that misses on `tree` alone,
# over a delta that is entirely under `docs/`, spends 200-250 s re-deriving a
# pytest result no path in the delta can have moved. The mechanism lets the
# banked pytest verdict stand in for that ONE pass while every other leg runs —
# and the whole of the risk is in when it must NOT, so most of what follows is
# refusals: a mixed delta, a dirty tree, a docs path some module under `apps/`
# spells, and every belt that is not `--loop`.
#
# WHAT THEY DO NOT COVER, in the register of this drive's own header: the
# END-TO-END reuse through a real `scripts/check.sh` run, which needs a
# provisioned checkout, a database and a complete green `--loop` — minutes per
# case. That is the BUILDER's measurement and it is pasted in the rung's report.
# What is covered here is the decision function driven over real git state, and
# the WIRING read out of `check.sh`'s source: that the pytest invocations are
# inside the guard, that the REUSED line exists, and that no belt but `--loop`
# can reach the decision at all.
#
# AND ONE MORE, DECLARED BY THE FIX THAT ADDED IT (R3's F1x.4): A DIRTY PORTION
# THAT IS ITSELF DOCS-ONLY. The basis check refuses any bank whose `tree=` is
# not its head's committed tree, and it refuses it WITHOUT LOOKING AT WHAT WAS
# DIRTY — so a bank taken with nothing uncommitted but a `docs/` edit, which the
# reuse's own argument would have been happy to inherit, is refused exactly as a
# bank taken over a half-finished `apps/` change is. That is the fail-closed
# direction and it is deliberate: the row records ONE hash and no inventory, so
# "which paths were dirty when this was banked" is not a question the ledger can
# answer, and a reuse that guessed at it would be guessing in the direction that
# hands out a green. The cost is a re-measure the round could in principle have
# skipped; the alternative is a check that has to trust a bank to describe its
# own dirt. If that cost is ever measured to matter, the honest fix is upstream —
# a `--loop` that refuses to BANK a dirty tree at all, which is a different rung
# and a much louder change than this one.

check_sh_function() {
    # Copy one function DEFINITION out of scripts/check.sh and source it, so a
    # case drives the bytes check.sh ships rather than a re-implementation of
    # them. check.sh itself cannot be sourced — it IS the gate, and sourcing it
    # would start one — and a drive may not run a nested gate either, because
    # the per-checkout lock refuses it. The function is the seam. The same
    # helper, for the same reason, as `scripts/tests/test_loop_scope.sh`'s.
    local name="$1" out
    out="${WORK}/fn-${name}.sh"
    awk -v want="${name}() {" '
        index($0, want) == 1 { on = 1 }
        on { print }
        on && $0 == "}" { exit }
    ' "${ROOT}/scripts/check.sh" >"$out"
    grep -q "^${name}() {" "$out" ||
        cannot_look "scripts/check.sh no longer defines ${name}() — the case cannot drive bytes it cannot find"
    grep -q '^}$' "$out" ||
        cannot_look "the ${name}() definition in scripts/check.sh has no closing brace at column 1 — the extraction cannot be trusted"
    # shellcheck source=/dev/null
    . "$out"
}

# Run `loop_docs_only_reuse` IN THIS SHELL with the working directory moved to a
# scratch checkout. Never `in_repo`: that is a subshell, and this function's
# whole answer is three globals a subshell would take with it — which is the
# same trap `check.sh` spells out beside its fingerprint call, so a helper that
# hid it here would be driving a shape the gate does not have.
REUSE_RC=0
reuse_in() {
    local dir="$1" saved="$PWD"
    shift
    REUSE_RC=0
    cd "$dir"
    loop_docs_only_reuse "$@" || REUSE_RC=$?
    cd "$saved"
}

# A scratch checkout with an `apps/` tree that spells no docs path, one banked
# head, and whatever commits the case puts on top. Returns with `BANKED_HEAD`
# set. `apps/` must EXIST: the refusal greps it, and a case whose `apps/` is
# missing would pass for the wrong reason.
BANKED_HEAD=""
reuse_checkout() {
    fresh_checkout
    mkdir -p "$REPO/apps/zzz_probe/tests" "$REPO/docs/product"
    printf '"""A module that names no docs path at all."""\n' \
        >"$REPO/apps/zzz_probe/tests/test_nothing.py"
    echo "the queue" >"$REPO/docs/product/queue.md"
    git -C "$REPO" add apps docs >/dev/null
    git -C "$REPO" commit -q -m "a tree with apps/ and docs/"
    BANKED_HEAD=$(git -C "$REPO" rev-parse HEAD)
    echo "  PLANT TOOK · banked head is $(git -C "$REPO" log -1 --oneline)"
}

# The attributor's own answer for a scratch checkout whose banked row sits at
# `BANKED_HEAD`. Driving the REAL attributor rather than crafting a detail by
# hand is the point: the reuse reads `reuse-basis:`, and a case that typed that
# line itself would never notice the day the attributor stopped printing it.
REUSE_TOKEN=""
REUSE_DETAIL=""
#: The tree the banked row carries, and the one every case that does not say
#: otherwise banks. It is `BANKED_HEAD`'s own COMMITTED tree — which is what a
#: bank taken on a clean working tree records, and what the docs-only reuse
#: requires of the row it rests on (R3's F1x). Before that requirement existed
#: every case here planted the literal `BANKEDTREE`, a token no `git rev-parse`
#: would ever answer, and the reuse was happy with it: the cases could not tell
#: a bank that measured its own head from one that measured a builder's
#: half-finished checkout, because nothing asked. Planting the real tree makes
#: "their banks are clean-tree by construction" a fact the cases ASSERT rather
#: than a sentence about them.
BANKED_TREE=""
attribute_for_reuse() {
    local scope="mode=fast_scope=-_always=abc" want="mode=fast scope=- always=abc"
    local E D answer banked
    BANKED_TREE=$(git -C "$REPO" rev-parse "${BANKED_HEAD}^{tree}") ||
        cannot_look "the scratch checkout has no committed tree at ${BANKED_HEAD}"
    # `$1` is the tree to bank, for the ONE case that means to bank a dirty one.
    banked="${1:-$BANKED_TREE}"
    E=$(hex64 envfile)
    D=$(hex64 dists)
    : >"$DJB_LOOP_LEDGER"
    plant_row "$scope" "$banked" ENVA \
        "$(crafted_components "$E" "" "$D" "$BANKED_HEAD" "$BANKED_HEAD")"
    LOOP_ENV_COMPONENTS=$(crafted_components "$E" "" "$D" \
        "$(git -C "$REPO" rev-parse HEAD)" "$(git -C "$REPO" rev-parse HEAD)")
    answer=$(in_repo "$REPO" loop_ledger_attribute NEWTREE ENVA "$want")
    REUSE_TOKEN=${answer%%$'\n'*}
    REUSE_DETAIL=${answer#*$'\n'}
    LOOP_ENV_COMPONENTS=""
}

case_a_miss_prints_the_docs_only_line_by_default() {
    # THE V-I2 RIDER. A verifier's `--loop` missed on `tree`, the whole delta
    # was two ledger files, and the DEFAULT banner offered `DJB_LOOP_VERBOSE=1`
    # instead of saying so — so 2302 s were spent re-measuring and the
    # transcript could not tell anyone it need not have been. The line prints on
    # every `miss(tree)` now, and this drives check.sh's own printer.
    check_sh_function loop_miss_narrative
    LOOP_LEDGER_KEY="loop-v1:planted0000000000000000000000000000000000000000000000000000"
    LOOP_LEDGER_TREE="planted-tree"
    LOOP_MISS_CENSUS="7 rows (0 seeded — planted by the drive)"
    local why
    why=$(printf '%s\n%s\n%s\n%s\n' "tree" "banked row: a planted row" \
        "since banked head abcd1234: 2 path(s) changed; docs-only: yes" \
        "reuse-basis: head=abcd1234 tree=BANKEDTREE")

    CURRENT="a miss(tree) says whether the miss was docs-only, with no flag set"
    N=$((N + 1))
    OUT="${WORK}/docsline-default${N}.log"
    RC=0
    (unset DJB_LOOP_VERBOSE; loop_miss_narrative "$why") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the printer's exit status"
    is "$(wc -l <"$OUT" | tr -d ' ')" "3" "the number of lines a miss(tree) prints by default"
    if grep -F "since banked head abcd1234: 2 path(s) changed; docs-only: yes" "$OUT" >/dev/null; then
        ok "the docs-only line is in the DEFAULT banner"
    else
        bad "the default banner still hides the docs-only line behind DJB_LOOP_VERBOSE=1"
    fi
    if grep -F "MISSED: miss(tree)" "$OUT" >/dev/null &&
        grep -F "DJB_LOOP_VERBOSE=1" "$OUT" >/dev/null; then
        ok "the two lines it always printed are still the first two"
    else
        bad "the token line or the key line went missing"
    fi

    CURRENT="the 'not derivable' forms reach the default banner too"
    why=$(printf '%s\n%s\n%s\n' "tree" "banked row: a planted row" \
        "since banked head: not derivable (the row carries no usable head=)")
    N=$((N + 1))
    OUT="${WORK}/docsline-nd${N}.log"
    RC=0
    (unset DJB_LOOP_VERBOSE; loop_miss_narrative "$why") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the printer's exit status on a named absence"
    if grep -F "since banked head: not derivable (the row carries no usable head=)" "$OUT" >/dev/null; then
        ok "a named absence is printed rather than silently dropped"
    else
        bad "the 'not derivable' form does not reach the default banner"
    fi

    CURRENT="a token that is not 'tree' gains no third line"
    why=$(printf '%s\n%s\n' "env:env-file" "banked row: a planted row")
    N=$((N + 1))
    OUT="${WORK}/docsline-env${N}.log"
    RC=0
    (unset DJB_LOOP_VERBOSE; loop_miss_narrative "$why") >"$OUT" 2>&1 || RC=$?
    is "$(wc -l <"$OUT" | tr -d ' ')" "2" "the number of lines an env: miss prints by default"
    OUT=""
}

case_a_docs_only_commit_reuses_the_pytest_verdict_and_banks_a_reuse_row() {
    reuse_checkout
    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    echo "  PLANT TOOK · one docs-only commit on top: $(git -C "$REPO" log -1 --oneline)"
    attribute_for_reuse

    CURRENT="the attributor says tree, and hands the reuse its untruncated basis"
    is "$REUSE_TOKEN" "tree" "the token"
    if printf '%s\n' "$REUSE_DETAIL" | grep -F "reuse-basis: head=${BANKED_HEAD} tree=${BANKED_TREE}" >/dev/null; then
        ok "the detail carries the WHOLE banked head and tree, not the reader's 8 and 12 characters"
    else
        bad "the attributor prints no reuse-basis line — the reuse can only rest on a row it cannot name"
    fi

    CURRENT="a docs-only delta from a banked green is REUSABLE"
    if ! command -v loop_docs_only_reuse >/dev/null 2>&1; then
        bad "scripts/gate_ledger.sh defines no loop_docs_only_reuse — there is no reuse to decide"
    else
        reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
        is "$REUSE_RC" "0" "the decision"
        is "$LOOP_REUSE_TREE" "$BANKED_TREE" "the tree the reuse rests on"
        is "$LOOP_REUSE_N" "1" "the size of the docs-only delta"
        is "$LOOP_REUSE_WHY" "" "the refusal sentence (there is none to print)"
    fi

    # F1x.3, ASSERTED RATHER THAN ASSUMED. This case's bank is clean-tree BY
    # CONSTRUCTION — it was taken at `BANKED_HEAD` with nothing uncommitted —
    # and that is now a precondition of the reuse rather than an accident of the
    # fixture, so the case says it in its own voice. Without this line, the
    # basis check could be deleted tomorrow and this case would go on passing.
    CURRENT="and this case's own bank measured its head's COMMITTED tree"
    is "$LOOP_REUSE_TREE" "$(git -C "$REPO" rev-parse "${BANKED_HEAD}^{tree}")" \
        "the banked tree, against the banked head's committed tree"

    CURRENT="and the row it banks SAYS it is a reuse, and is itself a legal hit"
    local key scope row
    scope="mode=fast scope=- always=abc"
    : >"$DJB_LOOP_LEDGER"
    key=$(in_repo "$REPO" loop_ledger_key NEWTREE "$scope")
    in_repo "$REPO" loop_ledger_record "$key" "$scope" 1 NEWTREE ENVA BANKEDTREE ||
        cannot_look "loop_ledger_record would not take a reuse marker"
    row=$(in_repo "$REPO" loop_ledger_lookup "$key") || row=""
    if [ -n "$row" ]; then
        ok "the reuse row is itself reusable — a later --loop on these bytes hits it"
    else
        bad "the reuse row is not a legal hit: a reuse that cannot be reused is a re-measure with extra steps"
    fi
    case "$row" in
    *" reuse=BANKEDTREE"*) ok "the row names the banked tree its pytest verdict rests on" ;;
    *) bad "the row does not say what it rests on: 'reuse=' is absent, so a reuse is recorded as a measurement" ;;
    esac
    case "$row" in
    "loop-v1 ${key} loop "*) ok "the row's third field is still the literal 'loop' — verify_start.sh's LOOP SEED can still inherit it" ;;
    *) bad "the row's third field moved: scripts/verify_start.sh's seed matches '^loop-v1 loop-v1:<64> loop ' and would drop every reuse row" ;;
    esac

    CURRENT="check.sh prints the REUSED line, and runs no pytest on that path"
    if grep -F 'pytest: REUSED from the banked verdict on' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the REUSED line exists in the leg"
    else
        bad "check.sh never announces a reuse — a leg that silently did not run is the failure this whole mechanism must not have"
    fi
    # THE "NO PYTEST INVOCATION" PROOF, READ STATICALLY OUT OF THE LEG. Running
    # the leg would mean running a gate inside a gate, which the per-checkout
    # lock refuses by design — so the assertion is that EVERY `./scripts/test.sh`
    # line in the `--loop` pytest leg sits inside the reuse guard's `else` arm.
    # A pytest invocation outside it is a reuse that measures anyway.
    local outside
    outside=$(awk '
        /# >>> loop-docs-only-reuse >>>/ { inguard = 1 }
        inguard && /^    else$/ { inelse = 1 }
        /# <<< loop-docs-only-reuse <<</ { inguard = 0; inelse = 0 }
        # An INVOCATION, never a mention: the line must BEGIN with the command.
        # `check.sh` names `./scripts/test.sh` in a dozen comments and a
        # censusing grep that counts those is a census of prose.
        { line = $0; sub(/^[[:space:]]+/, "", line) }
        line !~ /^\.\/scripts\/test\.sh/ { next }
        line ~ /--randomly-seed/ { next }
        !inelse { print FNR ": " line }
    ' "$ROOT/scripts/check.sh")
    # The two seeded whole-suite passes are the FULL gate's and are excluded by
    # name above; what is left is the `--loop` leg's own invocations.
    if [ -z "$outside" ]; then
        ok "every --loop pytest invocation is inside the reuse guard's else arm"
    else
        bad "a --loop pytest invocation sits outside the reuse guard: ${outside}"
    fi
}

case_a_mixed_delta_measures_in_full() {
    reuse_checkout
    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    printf '\n# a source change\n' >>"$REPO/apps/zzz_probe/tests/test_nothing.py"
    git -C "$REPO" add docs apps >/dev/null
    git -C "$REPO" commit -q -m "one docs path and one apps path"
    attribute_for_reuse
    CURRENT="one path outside docs/ and the whole delta measures"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "1" "the decision"
    is "$LOOP_REUSE_TREE" "" "the tree the reuse would have rested on"
    is "$LOOP_REUSE_WHY" "" "the sentence — an ordinary mixed delta is not news and must not print on every miss"
}

case_a_dirty_tree_is_never_docs_only() {
    reuse_checkout
    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    attribute_for_reuse
    CURRENT="the same delta is reusable while the working tree is clean"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "0" "the decision on a clean tree — the control"
    CURRENT="and an uncommitted byte anywhere refuses it, by name"
    printf 'a half-finished change nobody can name\n' >>"$REPO/apps/zzz_probe/tests/test_nothing.py"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "1" "the decision on a dirty tree"
    is "$LOOP_REUSE_TREE" "" "the tree the reuse would have rested on"
    case "$LOOP_REUSE_WHY" in
    *"WORKING TREE is not clean"*) ok "the refusal says the working tree is what refused it" ;;
    *) bad "a dirty tree refused silently, or did not refuse: '${LOOP_REUSE_WHY}'" ;;
    esac
}

# --- a run may not vouch for bytes it wrote itself ---------------------------
#
# THE MEASURED SHAPE. A product leg re-takes tracked evidence images on every
# run. A `--loop` whose START already carried the last run's re-take ends on the
# same bytes, the key re-derives, and the row banks a tree no HEAD carries. The
# key's own start/end comparison cannot see it; the snapshot the run takes of
# its own dirty set at the start is what can (`loop_tree_snapshot`,
# `loop_tree_rewrites`, scripts/gate_ledger.sh).
#: The re-taken artefact, under a top-level directory no tree carries. NOT the
#: consumer's frontend path: this drive's key floor judges every checkout path
#: its body spells that exists in the tree, so spelling a product's real
#: evidence path here would make this drive un-keyable on exactly the product
#: it was written for (measured: the BL.2 world, where it did).
REWRITE_PATH="zzz_rewritten/evidence.png"
rewrite_checkout() {
    fresh_checkout
    mkdir -p "$REPO/${REWRITE_PATH%/*}"
    printf 'the committed evidence\n' >"$REPO/$REWRITE_PATH"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a tracked evidence file"
    REWRITE_SNAP="${WORK}/rewrite-snapshot-${N}"
}

# A write the filesystem can tell from the snapshot's own stamp. One second is
# the coarsest mtime any filesystem this runs on keeps.
rewrite_after_the_stamp() {
    sleep 1
    printf '%s\n' "$2" >"$REPO/$1"
}

rewrites_in() {
    REWRITES_RC=0
    REWRITES=$(in_repo "$REPO" loop_tree_rewrites "$REWRITE_SNAP" 2>/dev/null) || REWRITES_RC=$?
}

case_a_run_that_rewrites_a_path_the_key_reads_names_it() {
    CURRENT="the snapshot and its reader exist"
    if command -v loop_tree_snapshot >/dev/null 2>&1 && command -v loop_tree_rewrites >/dev/null 2>&1; then
        ok "scripts/gate_ledger.sh defines loop_tree_snapshot and loop_tree_rewrites"
    else
        bad "scripts/gate_ledger.sh has no snapshot of the run's own starting tree — a leg's rewrite banks unseen"
        return
    fi

    rewrite_checkout
    CURRENT="a clean start and a leg that re-takes the evidence"
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write in the scratch checkout"
    rewrite_after_the_stamp "$REWRITE_PATH" "re-taken by the leg"
    rewrites_in
    is "$REWRITES_RC" "0" "the reader's status"
    is "$REWRITES" "$REWRITE_PATH" "the paths the run itself changed"

    CURRENT="a DIRTY start — the last run's re-take — and the same bytes re-taken again"
    # THE SHAPE THAT BANKED ON MAIN: start and end are the same bytes, so the
    # key re-derives to itself; only the fresh write says the run made them.
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write on a dirty start"
    rewrite_after_the_stamp "$REWRITE_PATH" "re-taken by the leg"
    rewrites_in
    is "$REWRITES_RC" "0" "the reader's status"
    is "$REWRITES" "$REWRITE_PATH" "the re-take on a dirty start is named"

    CURRENT="the NEXT run, which writes nothing (its leg's verdict reused), still carries the bytes"
    # MEASURED ON A BOX: run 2 reused the leg's drive verdict, so nothing was
    # written during it, and on main it banked the re-take. The refused run
    # remembers what it refused; the carried bytes are asked about again.
    in_repo "$REPO" loop_tree_remember "$REWRITE_SNAP" "$REWRITES" || cannot_look "loop_tree_remember would not write"
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write"
    rewrites_in
    is "$REWRITES_RC" "0" "the reader's status"
    is "$REWRITES" "$REWRITE_PATH" "the carried re-take is named with nothing written"

    CURRENT="and once the author moves those bytes, the memory no longer matches"
    printf 'an author edit\n' >"$REPO/$REWRITE_PATH"
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write"
    rewrites_in
    is "$REWRITES" "" "an author's own bytes are not a run's"
    in_repo "$REPO" loop_tree_remember "$REWRITE_SNAP" "" || cannot_look "loop_tree_remember would not forget"
    [ ! -e "${REWRITE_SNAP}.rewrites" ] && ok "a run that banks forgets what it carried" ||
        bad "an empty remember left ${REWRITE_SNAP}.rewrites behind"

    CURRENT="the control: a dirty start the run never wrote to is nobody's business"
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write"
    rewrites_in
    is "$REWRITES_RC" "0" "the reader's status"
    is "$REWRITES" "" "the paths the run changed (none — the builder's own edit stands)"

    CURRENT="an untracked, unignored file the run made is in the key too"
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write"
    rewrite_after_the_stamp made-by-a-leg.txt "a new file"
    rewrites_in
    is "$REWRITES" "made-by-a-leg.txt" "the new file is named"
    rm -f "$REPO/made-by-a-leg.txt"

    CURRENT="a snapshot that is gone is could-not-look, never an empty list"
    rm -f "$REWRITE_SNAP" "${REWRITE_SNAP}.stamp"
    rewrites_in
    is "$REWRITES_RC" "2" "the reader's status with no snapshot"
}

case_a_rewrite_the_leg_declares_is_subtracted_and_the_key_is_heads() {
    rewrite_checkout
    {
        echo '#!/usr/bin/env bash'
        echo "# $GATE_TREE_DECL_BEGIN"
        echo "# ${REWRITE_PATH} — re-taken by this leg on every run"
        echo "# $GATE_TREE_DECL_END"
    } >"$REPO/scripts/rewrite_leg.sh"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "the leg declares what it re-takes"
    CURRENT="a declared re-take is not the run's to answer for"
    in_repo "$REPO" loop_tree_snapshot "$REWRITE_SNAP" || cannot_look "loop_tree_snapshot would not write"
    rewrite_after_the_stamp "$REWRITE_PATH" "re-taken by the leg"
    rewrites_in
    is "$REWRITES_RC" "0" "the reader's status"
    is "$REWRITES" "" "the declared path is subtracted, exactly as the key subtracts it"
    CURRENT="and the key the run would bank is HEAD's measured tree"
    local end head
    end=$(in_repo "$REPO" gate_measured_tree 2>/dev/null) || end=""
    head=$(in_repo "$REPO" gate_measured_tree_of "HEAD^{tree}" 2>/dev/null) || head=""
    [ -n "$head" ] || cannot_look "gate_measured_tree_of would not answer"
    is "$end" "$head" "the measured working tree after the re-take"
}

# first_line_in <file> <fixed string> [at-start] → the first line number that
# carries the string (at column one with `at-start`). One awk, no pipe.
first_line_in() {
    awk -v s="$2" -v start="${3:-}" '
        (start == "" && index($0, s) > 0) || (start != "" && index($0, s) == 1) { print NR; exit }
    ' "$1"
}

case_the_bank_asks_before_the_key_re_derives() {
    # WIRING, READ FROM THE FILE: the snapshot is taken where the key takes its
    # tree, and the question is asked BEFORE the key re-derives — after it, a
    # re-take on a dirty start has already re-derived to itself.
    CURRENT="check.sh takes the snapshot beside the key and asks before the re-derivation"
    local snap key ask rederive
    snap=$(first_line_in "$ROOT/scripts/check.sh" 'loop_tree_snapshot "$LOOP_TREE_SNAPSHOT"')
    key=$(first_line_in "$ROOT/scripts/check.sh" '    LOOP_LEDGER_TREE=$(gate_measured_tree' at-start)
    ask=$(first_line_in "$ROOT/scripts/check.sh" 'loop_tree_rewrites "$LOOP_TREE_SNAPSHOT"')
    rederive=$(first_line_in "$ROOT/scripts/check.sh" 'LOOP_LEDGER_TREE_END=$(gate_measured_tree')
    if [ -n "$snap" ] && [ -n "$key" ] && [ "$snap" -lt "$key" ]; then
        ok "the snapshot (check.sh:${snap}) is taken before the key's tree (check.sh:${key})"
    else
        bad "the snapshot is not taken beside the key: snapshot='${snap}' key='${key}'"
    fi
    if [ -n "$ask" ] && [ -n "$rederive" ] && [ "$ask" -lt "$rederive" ]; then
        ok "the bank asks (check.sh:${ask}) before the key re-derives (check.sh:${rederive})"
    else
        bad "the bank does not ask before the re-derivation: ask='${ask}' rederive='${rederive}'"
    fi
    # THE SENTENCE HAS ONE HOME, and the bank calls it.
    if [ -n "$(awk -v a="${ask:-1}" 'NR >= a && NR < a + 40 && /loop_tree_refusal "\$LOOP_TREE_MOVED"/ { print NR; exit }' "$ROOT/scripts/check.sh")" ]; then
        ok "the bank refuses through loop_tree_refusal"
    else
        bad "the bank does not refuse through loop_tree_refusal"
    fi
    CURRENT="the refusal names each path's arm and the escapes that work"
    local said
    said=$(loop_tree_refusal "$(printf 'a.py\tchanged\nb.png\tcarried\n')" 2>&1 >/dev/null) || true
    case "$said" in
    *"a.py — changed during this run"*"b.png — carried from a refused run"*) ok "each path carries the arm that named it" ;;
    *) bad "the arms are not named per path: ${said}" ;;
    esac
    case "$said" in
    *"git checkout -- <path>"*"change its bytes"*"$GATE_TREE_DECL_BEGIN"*) ok "the escapes that clear a path, and the declaration form, are printed" ;;
    *) bad "the refusal does not print the working escapes: ${said}" ;;
    esac
    case "$said" in
    *"still tree"*) bad "the refusal still offers 're-run on a still tree', which the carried arm refuses again" ;;
    *) ok "no 're-run on a still tree' — the remedy that was measured false is gone" ;;
    esac
}

# bank_memory_wiring <check.sh> — 0 when the bank REMEMBERS what it refused
# (`loop_tree_remember` between the question and the snapshot's removal) and
# that removal spares the memory: exactly the two files, nothing wider. Prints
# the first thing that is wrong.
bank_memory_wiring() {
    awk '
        index($0, "loop_tree_rewrites \"$LOOP_TREE_SNAPSHOT\"") && !ask { ask = NR; next }
        ask && !rem && index($0, "loop_tree_remember \"$LOOP_TREE_SNAPSHOT\"") { rem = NR; next }
        ask && !rm && $0 ~ /^[ \t]*rm -f / && index($0, "LOOP_TREE_SNAPSHOT") { rm = NR; line = $0 }
        END {
            if (!ask) { print "no question asked of the snapshot"; exit 1 }
            if (!rem) { print "the bank never calls loop_tree_remember after the question"; exit 1 }
            if (!rm) { print "the bank never removes the snapshot"; exit 1 }
            if (rem > rm) { print "the memory is written after the snapshot is removed"; exit 1 }
            sub(/^[ \t]+/, "", line); sub(/[ \t]+$/, "", line)
            want = "rm -f \"$LOOP_TREE_SNAPSHOT\" \"${LOOP_TREE_SNAPSHOT}.stamp\""
            if (line != want) { print "the removal is not exactly the two files — it reads: " line; exit 1 }
        }
    ' "$1"
}

case_the_bank_remembers_what_it_refused_and_its_rm_spares_the_memory() {
    CURRENT="check.sh wires loop_tree_remember at the refusal, and the bank's rm spares .rewrites"
    local why planted
    if why=$(bank_memory_wiring "$ROOT/scripts/check.sh"); then
        ok "remember sits between the question and the rm, and the rm names exactly the snapshot and its stamp"
    else
        bad "the carried arm's memory is not wired, or is swept: ${why}"
    fi
    # THE TOOTH, PROVED ON A PLANTED COPY: a widened rm must red this reader.
    CURRENT="a widened rm (the snapshot and every sibling) is caught"
    planted="${WORK}/check-widened-rm.sh"
    awk -v old='"${LOOP_TREE_SNAPSHOT}.stamp"' -v new='"${LOOP_TREE_SNAPSHOT}".*' '
        !done && index($0, "rm -f \"$LOOP_TREE_SNAPSHOT\" " old) {
            i = index($0, old)
            $0 = substr($0, 1, i - 1) new substr($0, i + length(old))
            done = 1
        }
        { print }
    ' "$ROOT/scripts/check.sh" >"$planted"
    if cmp -s "$planted" "$ROOT/scripts/check.sh"; then
        cannot_look "the widened-rm plant did not take — the bank's rm line was not found"
    fi
    if why=$(bank_memory_wiring "$planted"); then
        bad "a widened rm that sweeps .rewrites passed the wiring check"
    else
        ok "the widened rm reds: ${why}"
    fi
    CURRENT="and a bank that forgets to remember is caught"
    awk '!/loop_tree_remember "\$LOOP_TREE_SNAPSHOT"/' "$ROOT/scripts/check.sh" >"$planted"
    if why=$(bank_memory_wiring "$planted"); then
        bad "a bank with no loop_tree_remember passed the wiring check"
    else
        ok "the missing remember reds: ${why}"
    fi
}

case_a_bank_measured_on_a_dirty_tree_is_no_basis_for_a_docs_only_reuse() {
    # R3's F1, DRIVEN. A `--loop` verdict is keyed on the MEASURED WORKING TREE
    # (`gate_measured_tree` reads through `git add -A`), and a builder's working
    # tree is routinely dirty — so a banked row can name a head whose COMMITTED
    # tree nothing ever measured. The reuse asked three questions (ancestry, a
    # docs-only committed delta, and THIS run's clean tree) and never the fourth,
    # so the reviewer's sequence came out green: commit a red test, leave the
    # uncommitted edit that greens it, `--loop` banks `head=C tree=T'`, restore
    # the red bytes, put a `docs/` commit on top — and the next `--loop` reuses
    # green over a red COMMITTED suite, banking a reusable reuse row on top of it.
    #
    # THE VICTIM IS BUILT HERE AND NEVER FOUND. `T'` is a real
    # `gate_measured_tree` reading of a real uncommitted edit in a scratch
    # checkout, taken and then restored, so the hash the planted row carries is
    # the hash the gate would genuinely have banked — not a token chosen to be
    # unequal, which is a case that proves the comparison and not the property.
    reuse_checkout
    local dirty red saved
    red="$REPO/apps/zzz_probe/tests/test_nothing.py"
    N=$((N + 1))
    saved="${WORK}/committed-bytes${N}.py"
    cp "$red" "$saved"
    printf '\n# the uncommitted edit that greens the committed red\n' >>"$red"
    dirty=$(in_repo "$REPO" gate_measured_tree) ||
        cannot_look "gate_measured_tree would not read the scratch checkout — the dirty bank cannot be built"
    cp "$saved" "$red"
    echo "  PLANT TOOK · dirty-tree bank ${dirty} at head $(git -C "$REPO" rev-parse --short HEAD)"

    CURRENT="the planted bank is genuinely a dirty-tree bank"
    differs "$dirty" "$(git -C "$REPO" rev-parse "${BANKED_HEAD}^{tree}")" \
        "the measured tree under one uncommitted edit is not the head's committed tree"
    is "$(git -C "$REPO" status --porcelain)" "" "the checkout after the restore"

    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    attribute_for_reuse "$dirty"

    CURRENT="a basis row whose tree is not its head's measured tree is refused"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "1" "the decision"
    is "$LOOP_REUSE_TREE" "" "the tree the reuse would have rested on"
    case "$LOOP_REUSE_WHY" in
    *"the banked verdict was measured on a tree that is not its head's measured tree"*)
        ok "the refusal names the BASIS row as what refused it, in the criterion's own words"
        ;;
    *) bad "a dirty-tree bank was reused, or refused without saying so: '${LOOP_REUSE_WHY}'" ;;
    esac

    # THE NEGATIVE, IN THE SAME CASE AND OVER THE SAME DELTA, because the two
    # differ in exactly one input: what the basis row's `tree=` says. A refusal
    # proved against a delta the control never ran is a refusal that might have
    # been bought by the delta.
    CURRENT="and the SAME delta over a clean-tree bank still reuses"
    attribute_for_reuse
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "0" "the decision on a bank that measured its own head"
    is "$LOOP_REUSE_TREE" "$BANKED_TREE" "the tree the reuse rests on"
    is "$LOOP_REUSE_WHY" "" "the refusal sentence (there is none to print)"
}

case_a_declaring_product_still_reuses_a_docs_only_loop_verdict() {
    # THE LAST RAW-VS-MEASURED COMPARE, and it sat in the same file as the fix
    # that closed the other three. A `--loop` row's `tree=` is written from
    # `gate_measured_tree`; this equality held it up against a RAW
    # `<head>^{tree}`. Identical wherever nothing is declared — which is why
    # this drive was green through the whole of the wall's fix — and NEVER
    # equal on a product that declares a derived path, so the `--loop`
    # docs-only reuse was shut to exactly the products the road was widened
    # for. ABSENT: rc 1 with "not its head's measured tree".
    reuse_checkout
    plant_derived_leg "$REPO" \
        "derived — a per-box artefact; nothing measured reads it back"
    plant_derived_member "$REPO" ||
        cannot_look "the derived artefact would not commit in the reuse world"
    BANKED_HEAD=$(git -C "$REPO" rev-parse HEAD)
    local measured raw
    raw=$(git -C "$REPO" rev-parse "${BANKED_HEAD}^{tree}")
    measured=$(in_repo "$REPO" gate_measured_tree 2>/dev/null) || measured=""
    [ -n "$measured" ] ||
        cannot_look "gate_measured_tree would not read the declaring reuse world"

    CURRENT="the planted bank is a DECLARING product's bank"
    # THE PREMISE, ASSERTED. A world where the two readings agreed would let
    # every line below pass while proving nothing at all.
    differs "$raw" "$measured" \
        "the measured tree of a declaring checkout is not its head's raw tree"
    is "$(git -C "$REPO" status --porcelain)" "" "the checkout the bank was taken on"

    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    # The row a real `--loop` would have banked here: keyed on the MEASURED
    # tree, because that is the only key `check.sh` ever writes.
    attribute_for_reuse "$measured"

    CURRENT="a docs-only delta on a DECLARING product reuses its loop verdict"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "0" "the decision"
    is "$LOOP_REUSE_TREE" "$measured" "the tree the reuse rests on"
    is "$LOOP_REUSE_N" "1" "the size of the delta"
    is "$LOOP_REUSE_WHY" "" "the refusal sentence (there is none)"

    # AND THE GUARD THE EQUALITY EXISTS TO BE IS UNTOUCHED, proved on THIS
    # world rather than asserted about it: measured-working equals
    # measured-committed if and only if the tree was clean, so one uncommitted
    # byte in `apps/` still refuses — a declaration subtracts the paths it
    # names and nothing else.
    CURRENT="and one uncommitted byte still refuses it on the same declaring world"
    printf 'a half-finished change nobody can name\n' \
        >>"$REPO/apps/zzz_probe/tests/test_nothing.py"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "1" "the decision on a dirty tree"
    is "$LOOP_REUSE_TREE" "" "the tree the reuse would have rested on"
    case "$LOOP_REUSE_WHY" in
    *"WORKING TREE is not clean"*) ok "the refusal says the working tree is what refused it" ;;
    *) bad "a dirty declaring tree was reused, or refused without saying so: '${LOOP_REUSE_WHY}'" ;;
    esac
}

case_a_docs_path_spelled_under_apps_forces_a_measure() {
    # RENAMED 2026-09-15 to what it asserts. The old name said "a docs path a
    # test READS", and the mechanism is wider and fail-closed: the question is
    # whether the path is SPELLED in any module under `apps/` — the first hit
    # wins, it need not be a test (`apps/core/integrations.py` is a real one),
    # and a mention in a docstring refuses exactly as a real read does. A name
    # that claims the narrower thing is a claim nothing proved.
    reuse_checkout
    # THE POPULATION IS DERIVED, SO THE CASE PLANTS A MEMBER OF IT. A module
    # under `apps/` that spells the changed path is the whole refusal; the
    # CONTROL is the case above, where nothing under `apps/` names it.
    printf '"""Reads %s for a census."""\n' "docs/product/queue.md" \
        >"$REPO/apps/zzz_probe/tests/test_reads_docs.py"
    printf 'one more row\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add apps docs >/dev/null
    git -C "$REPO" commit -q -m "a docs commit under a path a test reads"
    # The delta must be docs-only, so the module that reads it is committed in
    # the SAME commit as the banked head's tree would have had it. Rebuild the
    # basis on top of a head that already carries the reader.
    BANKED_HEAD=$(git -C "$REPO" rev-parse HEAD)
    printf 'and one more\n' >>"$REPO/docs/product/queue.md"
    git -C "$REPO" add docs/product/queue.md >/dev/null
    git -C "$REPO" commit -q -m "queue row rowed [docs-only]"
    attribute_for_reuse
    CURRENT="a docs path a module under apps/ spells refuses the reuse"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "1" "the decision"
    is "$LOOP_REUSE_TREE" "" "the tree the reuse would have rested on"
    case "$LOOP_REUSE_WHY" in
    "docs-only delta touches a path spelled in a module under apps/: docs/product/queue.md (named in apps/zzz_probe/tests/test_reads_docs.py) — measuring")
        ok "the refusal names the path AND the module, in the criterion's own words"
        ;;
    *) bad "the refusal sentence is not the one the criterion names: '${LOOP_REUSE_WHY}'" ;;
    esac
}

case_mine_and_pr_never_reuse_on_a_docs_only_delta() {
    # THE BELTS, READ OUT OF check.sh. `--mine` derives NO key (so it never
    # consults, never attributes and never reaches the decision); `--pr` and the
    # full gate never enter the `--loop` block at all. The assertion is
    # structural because the property is: there is no second guard to get wrong.
    CURRENT="the reuse decision is called from inside the --loop block only"
    if awk '/^if \[ "\$MODE" = "--loop" \]; then/ { on = 1 }
        on && /^fi$/ { on = 0 }
        /loop_docs_only_reuse "\$LOOP_MISS_TOKEN"/ { called = 1; inloop = on }
        END { exit (called && inloop) ? 0 : 1 }' "$ROOT/scripts/check.sh"; then
        ok "the only call site is inside check.sh's --loop block: --pr and the full gate cannot reach it"
    else
        bad "loop_docs_only_reuse is called outside the --loop block, or not at all"
    fi
    CURRENT="--mine derives no key, so it never consults and never reuses"
    if grep -F '[ -z "$GATE_MINE" ]; then' "$ROOT/scripts/check.sh" >/dev/null &&
        grep -F 'LOOP_LEDGER_KEY=$(loop_ledger_key' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the key derivation is guarded on GATE_MINE being empty — the one mechanism, unchanged"
    else
        bad "--mine's no-key guard is gone: the reuse would become reachable from a narrowed run"
    fi
    CURRENT="the reuse is decided in the MISS arm, which --mine does not enter"
    if awk '/== the --loop ledger was NOT consulted: --mine ==/ { mine = 1; next }
        # The --mine ARM ends at the next `elif`, which is where the MISS arm
        # (the one that decides a reuse) begins. Clearing on anything later
        # would read the miss arm as part of --mine and this case would be
        # asserting the opposite of what it says.
        /^    elif / { mine = 0 }
        mine && /loop_docs_only_reuse/ { found = 1 }
        END { exit found ? 1 : 0 }' "$ROOT/scripts/check.sh"; then
        ok "the --mine arm reaches no reuse decision"
    else
        bad "the --mine arm can reach the reuse decision"
    fi
    CURRENT="the full gate's ledger section is still a different section"
    if grep -F 'loop_ledger_record' "$ROOT/scripts/check.sh" >/dev/null &&
        ! grep -F 'gate_ledger_record "$LOOP' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "no --loop row is ever written by, or read by, the full path"
    else
        bad "the two ledgers' sections have been crossed"
    fi
}

case_loop_health_reads_a_reuse_row() {
    # THE READOUTS READER MUST NOT CHOKE ON THE NEW CELL FORM. `loop:` cells are
    # typed by verifiers into the round's ledger rows and read back by
    # `scripts/loop_health.py`; a form the reader cannot parse would take the
    # health verdict down with it, which is the one instrument that says whether
    # the loop is working at all.
    # THE CHECKOUT'S OWN INTERPRETER, and the skip is about THAT rather than
    # about `python3` off PATH. `scripts/loop_health.py` is this repository's
    # file and it uses `zip(…, strict=True)`, which a 3.9 — a verifier box's
    # system python — refuses with `TypeError: zip() takes no keyword
    # arguments`. A run under it would report the reader as broken.
    if [ ! -x "$ROOT/.venv/bin/python" ]; then
        echo "  SKIPPED  ${CURRENT:-loop_health} — this checkout has no .venv/bin/python"
        return 0
    fi
    [ -f "$ROOT/docs/product/readouts.md" ] ||
        cannot_look "docs/product/readouts.md is not in this tree — the reader has nothing to read"
    N=$((N + 1))
    local plain="${WORK}/readouts-plain${N}.md" marked="${WORK}/readouts-reuse${N}.md"
    cp "$ROOT/docs/product/readouts.md" "$plain"
    # The new cell form, planted into the board the reader actually parses.
    {
        cat "$plain"
        echo
        echo "V-ZZZ: loop: docs-only reuse of 0123456789abcdef0123456789abcdef01234567"
    } >"$marked"
    local rc_plain=0 rc_marked=0
    OUT="${WORK}/loophealth-plain${N}.log"
    (cd "$ROOT" && "$ROOT/.venv/bin/python" scripts/loop_health.py "$plain") >"$OUT" 2>&1 || rc_plain=$?
    OUT="${WORK}/loophealth-marked${N}.log"
    (cd "$ROOT" && "$ROOT/.venv/bin/python" scripts/loop_health.py "$marked") >"$OUT" 2>&1 || rc_marked=$?
    CURRENT="loop_health reads a board carrying the new cell form"
    is "$rc_marked" "$rc_plain" "the verdict, against the same board without the cell"
    if grep -qE 'Traceback|CANNOT JUDGE' "$OUT"; then
        bad "loop_health could not read the board once the new cell form was on it"
    else
        ok "the reader takes 'docs-only reuse of <tree>' in its stride"
    fi
    OUT=""
}

case_the_two_ledger_files_that_bought_a_2302s_remeasure_are_a_reuse() {
    # V-I2's RIDER, DRIVEN. The verifier's 2302-second re-measure was bought
    # entirely by `docs/product/in-flight.md` and the cycle plan — two files
    # nothing under `apps/` reads. This is that exact delta, and it asserts the
    # reuse rather than describing it.
    reuse_checkout
    # THE FIXTURE'S NAME IS ASSEMBLED, and the suffix is why. A literal
    # `docs/<…>.md` anywhere in this file is a POINTER to the `dangling-docs`
    # censuses, which ask that every one of them resolve — in the tree at every
    # commit, and in the published ARTIFACT at release. The cycle plans are
    # build history the artifact does not carry, and this world's plan is not a
    # file at all; spelling either whole would be a dead pointer for the next
    # reader. Split here, the path is only a path where it is used.
    local plan="docs/product/cycles/the-cycle-plan"
    mkdir -p "$REPO/docs/product/cycles"
    echo "in flight" >"$REPO/docs/product/in-flight.md"
    echo "the plan" >"$REPO/$plan.md"
    git -C "$REPO" add docs >/dev/null
    git -C "$REPO" commit -q -m "the two ledger files [docs-only]"
    attribute_for_reuse
    CURRENT="the delta V-I2 paid 2302 s for is a reuse"
    reuse_in "$REPO" "$REUSE_TOKEN" "$REUSE_DETAIL"
    is "$REUSE_RC" "0" "the decision"
    is "$LOOP_REUSE_N" "2" "the number of paths in the delta"
    is "$LOOP_REUSE_TREE" "$BANKED_TREE" "the tree the reuse rests on"
    # F1x.3's second named case, asserting its own precondition for the same
    # reason the first does: this bank measured its head's committed tree.
    is "$LOOP_REUSE_TREE" "$(git -C "$REPO" rev-parse "${BANKED_HEAD}^{tree}")" \
        "the banked tree, against the banked head's committed tree"
    # AND THE SAME TWO PATHS ON THE REAL TREE, because the population is this
    # repository's own and a scratch checkout cannot speak for it. If a module
    # under `apps/` ever spells either path, this case goes red and the rider's
    # own example stops being a reuse — which is the correct outcome and the
    # reason the assertion is here rather than in prose.
    #
    # THE CYCLE-PLAN PATH IS THE WORLD'S OWN FIXTURE NAME, and deliberately so:
    # the cycle plans live in a directory the published artifact does not carry
    # (`publish.sh`'s bucket census sets them aside), so a drive that spelled a
    # real plan's filename would be a pointer into trimmed history for every
    # consumer reading this file — the `dangling-docs` defect. The world above
    # writes `$plan.md`, this census asks about `$plan.md`, and the property
    # the case asserts is unchanged: a docs-only delta is not spelled by a
    # module under `apps/`.
    CURRENT="and neither path is spelled by any module under apps/ on THIS tree"
    local hit
    hit=$(cd "$ROOT" && grep -rlF 'docs/product/in-flight.md' apps/ --include='*.py' 2>/dev/null) || hit=""
    is "$hit" "" "the modules naming docs/product/in-flight.md"
    hit=$(cd "$ROOT" && grep -rlF "$plan.md" apps/ --include='*.py' 2>/dev/null) || hit=""
    is "$hit" "" "the modules naming the cycle plan"
}

# --- the DOCS-ONLY PUSH path: the source, the list and the readers -----------
#
# WHY IT IS HERE AND NOT IN A DRIVE OF ITS OWN. The decision is three reads of
# the FULL ledger — the nearest ancestor's row, the `from=` it may name, and
# the legs and leak-proof it carries — and this file already owns "what the
# full ledger says and when it may be believed". The half that RUNS the readers
# and writes the row is `scripts/pm_push.sh`'s and is driven there.
#
# EVERY PATH THESE CASES SPELL IS A FIXTURE NAME THAT EXISTS IN NO TREE, with
# one deliberate exception: the four real top-level names the declared list
# rules IN and OUT (`CHANGELOG.md`, `TEMPLATE_VERSION`, `CLAUDE.md`,
# `scripts/test_impact.json`) are the SUBJECT of the list case and are
# therefore spelled. They are declared on this file's `cites:` line, which is
# what that valve is for: this drive names them, and opens none of them.
#
# WHAT THESE CASES DO NOT COVER, declared rather than discovered:
#
#   * WHETHER A DERIVED READER REALLY IS THE ONLY THING THAT READS A PATH.
#     The derivation asks the tree three questions (a literal read under
#     `apps/`, `config/` or `quality/`, and a drive's own declaration). A
#     module that builds a docs path from parts, walks a directory or globs for
#     it is invisible to all three — the declared blind spot, whose belt is the
#     next push that is not docs-only.
#   * THE REAL LEGS. `--leg static` and `--leg full-house-rules` are NAMES
#     here; that they are the legs that read `docs/` is `scripts/check.sh`'s
#     claim and the builder's measurement, not this drive's.
#   * THE TRUST CLASS, which is this file's throughout: a row is a cache line
#     an agent could echo into the file, exactly as `--no-verify` is one flag
#     away. What is asserted is that a row the ledger cannot VOUCH for does not
#     become a reuse.

#: THE FIXTURE DOC'S PATH IS COMPOSED, NEVER SPELLED. The dangling-docs leg
#: refuses a `docs/` pointer with an .md suffix that is in no tree — correctly,
#: since a pointer into trimmed history is the defect it exists to catch — and
#: every doc these cases move is a fixture that lives only inside a scratch
#: repository. So the DIRECTORY (which carries no suffix and is nobody's
#: pointer) is spelled and the file name is joined to it here. The same
#: reason, and the same shape, as the cycle-plan fixture one section up.
DOCSONLY_DIR="docs/fixtures"
DOCSONLY_DOC="${DOCSONLY_DIR}/rows.md"

#: The leg set the scratch gates in this section declare, so `gate_full_legs`
#: has something for `gate_ledger_lookup` to compare a row against.
DOCSONLY_LEGS="ruff,mypy,pytest-x2,selftest"

#: The measured commit and its tree — M, in the criterion's own letter.
DOCSONLY_M=""
DOCSONLY_MTREE=""

# A scratch checkout with the four populations the derivation reads: an `apps/`
# and a `config/` that open nothing, a `quality/` that opens nothing, a
# a fixture docs directory to move, and a `scripts/tests/` holding two drives — one that
# declares a docs directory and one that declares nothing of ours. `M` is
# committed and ROWED, so every case starts from a measured tree.
docs_only_world() {
    fresh_checkout
    mkdir -p "$REPO/apps" "$REPO/config" "$REPO/quality" "${REPO}/${DOCSONLY_DIR}" \
        "$REPO/scripts/tests"
    printf '#!/usr/bin/env bash\nFULL_LEGS=%s\n' "$DOCSONLY_LEGS" >"$REPO/scripts/check.sh"
    chmod +x "$REPO/scripts/check.sh"
    printf '"""A module that opens nothing at all."""\n' >"$REPO/apps/quiet.py"
    printf '"""Settings that open nothing at all."""\n' >"$REPO/config/quiet.py"
    printf 'rules: []\n' >"$REPO/quality/quiet.yaml"
    printf 'the rows\n' >"${REPO}/${DOCSONLY_DOC}"
    # THE MARKER LINE IS ASSEMBLED, never typed at column zero. A literal
    # `<hash> drives:` at the start of a line in THIS file's own first forty
    # lines would be a phantom declaration; writing it through printf keeps the
    # drive's own declaration the only one this file carries.
    {
        echo '#!/usr/bin/env bash'
        printf '# %s %s scripts/check.sh\n' 'drives:' "$DOCSONLY_DIR"
        echo 'exit 0'
    } >"$REPO/scripts/tests/test_reads_docs.sh"
    {
        echo '#!/usr/bin/env bash'
        printf '# %s scripts/check.sh\n' 'drives:'
        printf '# %s %s\n' 'cites:' "$DOCSONLY_DOC"
        echo 'exit 0'
    } >"$REPO/scripts/tests/test_cites_docs.sh"
    chmod +x "$REPO/scripts/tests/test_reads_docs.sh" "$REPO/scripts/tests/test_cites_docs.sh"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a tree with apps/, config/, quality/, docs/ and two drives"
    DOCSONLY_M=$(git -C "$REPO" rev-parse HEAD)
    DOCSONLY_MTREE=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    plant_full_row "$REPO" "$DOCSONLY_MTREE" "$DOCSONLY_LEGS"
    echo "  PLANT TOOK · M is $(git -C "$REPO" log -1 --oneline) tree=${DOCSONLY_MTREE}"
}

# Move M forward over whatever the case has just written, and row the new
# tree. A case whose SUBJECT is a module that reads a docs path needs that
# module INSIDE the measured tree: committed after M it is part of the delta,
# and the delta would then refuse for the module rather than for the read.
docs_only_rebase_m() {
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "$1"
    DOCSONLY_M=$(git -C "$REPO" rev-parse HEAD)
    DOCSONLY_MTREE=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    plant_full_row "$REPO" "$DOCSONLY_MTREE" "$DOCSONLY_LEGS"
}

# One docs-only commit on top, by path and content.
docs_only_commit() {
    local path="$1" text="$2" dir
    dir="${REPO}/${path%/*}"
    [ "$dir" = "$REPO/$path" ] || mkdir -p "$dir"
    printf '%s\n' "$text" >>"${REPO}/${path}"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a docs-only commit touching ${path}"
}

# Run `gate_docs_only_plan` IN THIS SHELL with the working directory moved to
# the scratch checkout. Never `in_repo`: that is a subshell, and this
# function's whole answer is six globals a subshell would take with it —
# `reuse_in`'s rule, one mechanism over.
PLAN_RC=0
plan_in() {
    local dir="$1" saved="$PWD"
    shift
    PLAN_RC=0
    cd "$dir"
    gate_docs_only_plan "$@" || PLAN_RC=$?
    cd "$saved"
}

case_the_docs_only_source_is_the_nearest_MEASURED_ancestor() {
    CURRENT="the functions exist at all"
    # THE RED-FIRST CASE, and it is the criterion's own "Absent: no function".
    # On the baseline tree there is nothing to call and this drive says so
    # instead of passing over a mechanism that is not there.
    if command -v gate_docs_only_plan >/dev/null 2>&1 &&
        command -v gate_docs_only_source >/dev/null 2>&1 &&
        command -v gate_docs_only_admits >/dev/null 2>&1; then
        ok "scripts/gate_ledger.sh defines the docs-only source, list and plan"
    else
        bad "scripts/gate_ledger.sh defines no gate_docs_only_plan — there is no docs-only road to decide"
        return
    fi

    docs_only_world
    docs_only_commit "$DOCSONLY_DOC" "one more row"

    CURRENT="R1 = M + one docs commit: the source is M's MEASURED tree"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    is "$GATE_DOCS_ONLY_SOURCE" "$DOCSONLY_MTREE" "the source tree"
    is "$GATE_DOCS_ONLY_N" "1" "the size of the delta"
    is "$GATE_DOCS_ONLY_LEGS" "$DOCSONLY_LEGS" "the legs field, copied from the source row"
    is "$GATE_DOCS_ONLY_WHY" "" "the refusal sentence (there is none)"

    CURRENT="R2 = R1 + one more docs commit: the source is STILL M, and the delta is against M"
    # R1's own row, as the road writes it: an ordinary full row whose sanction
    # names the measured tree it rests on.
    local r1tree
    r1tree=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    plant_full_row "$REPO" "$r1tree" "$DOCSONLY_LEGS" \
        " sanction=docs-only from=${DOCSONLY_MTREE} paths=1 readers=static waited=0 took=0"
    docs_only_commit "$DOCSONLY_DOC" "a second row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    is "$GATE_DOCS_ONLY_SOURCE" "$DOCSONLY_MTREE" "the source tree — followed through from=, never R1's own"
    is "$GATE_DOCS_ONLY_N" "1" "the delta, taken against M and not against R1"

    CURRENT="a FORGED from= is caught by the diff it forces, not by trusting the row"
    # R1 says `from=M` and its tree differs from M by an `apps/` path. The road
    # diffs against M, so the `apps/` path is IN the delta and the bank is full.
    # A road that diffed against R1 would never see it.
    docs_only_world
    printf 'print("a source change nobody measured")\n' >"$REPO/apps/loud.py"
    printf 'one more row\n' >>"${REPO}/${DOCSONLY_DOC}"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a commit that is NOT docs-only, rowed as though it were"
    r1tree=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    plant_full_row "$REPO" "$r1tree" "$DOCSONLY_LEGS" \
        " sanction=docs-only from=${DOCSONLY_MTREE} paths=1 readers=static waited=0 took=0"
    docs_only_commit "$DOCSONLY_DOC" "and a docs row on top of it"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    case "$GATE_DOCS_ONLY_WHY" in
    *"apps/loud.py is not a docs-only path"*) ok "the refusal names the source path the forged row hid" ;;
    *) bad "the forged chain was admitted, or refused without naming the path: '${GATE_DOCS_ONLY_WHY}'" ;;
    esac

    CURRENT="a loop row and a drive row on the ancestor are no source"
    docs_only_world
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    local r1
    r1=$(git -C "$REPO" rev-parse HEAD)
    r1tree=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    # A DRIVE row keyed on a TREE — the shape this drive plants on purpose one
    # section over — and a LOOP row at the same tree. Neither is a full verdict
    # and neither may be followed.
    in_repo "$REPO" drive_ledger_record "$r1tree" test_reads_docs.sh 1 "$r1tree" "x:1" ||
        cannot_look "drive_ledger_record would not write into the scratch ledger"
    docs_only_commit "$DOCSONLY_DOC" "a second row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    is "$GATE_DOCS_ONLY_SOURCE" "$DOCSONLY_MTREE" "the source tree — the drive row at ${r1} is not one"
    is "$GATE_DOCS_ONLY_N" "1" "the delta against M — one PATH, moved by two commits"

    CURRENT="a source row that is NOT HONOURED refuses, and does not walk past itself"
    docs_only_world
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    r1tree=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    # One leg short of what this scratch gate declares — the row exists, the
    # lookup refuses it, and the road must refuse with it rather than reach
    # back to M, which is an older answer than the one the gate last gave.
    plant_full_row "$REPO" "$r1tree" "ruff,mypy"
    docs_only_commit "$DOCSONLY_DOC" "a second row"
    N=$((N + 1))
    OUT="${WORK}/docsonly-nothonoured${N}.log"
    plan_in "$REPO" HEAD 2>"$OUT"
    is "$PLAN_RC" "1" "the decision"
    case "$GATE_DOCS_ONLY_WHY" in
    *"nearest banked ancestor's row is not honoured"*) ok "the refusal names the row it would not stand on" ;;
    *) bad "a short-legs source row was admitted, or refused silently: '${GATE_DOCS_ONLY_WHY}'" ;;
    esac
    if grep -F "missing 'pytest-x2'" "$OUT" >/dev/null; then
        ok "the lookup's own note is printed beside it — the reader is told WHICH leg"
    else
        bad "the lookup's note was swallowed: a refusal nobody can act on"
    fi
    OUT=""

    CURRENT="no honoured row anywhere on the line is a refusal that says so"
    docs_only_world
    : >"$(cd "$REPO" && gate_ledger_path)"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    case "$GATE_DOCS_ONLY_WHY" in
    *"no honoured full row"*"full bank"*) ok "an empty ledger is a named refusal and a full bank" ;;
    *) bad "an empty ledger did not refuse by name: '${GATE_DOCS_ONLY_WHY}'" ;;
    esac
}

case_the_docs_only_road_admits_a_declaring_product() {
    # THE OTHER SIDE OF THE SAME WALL. The docs-only road reads
    # HEAD's tree RAW in two places — the ancestor walk in
    # `gate_docs_only_source`, and the equality in `gate_docs_only_plan` that
    # asks whether the key and the delta are about the same bytes. On a
    # declaring product both reads answer a tree no row is ever keyed on, so
    # the road refuses and the product pays a FULL BANK for a documentation
    # push, every time, for the rest of its life.
    CURRENT="the docs-only road can be asked at all"
    if command -v gate_docs_only_plan >/dev/null 2>&1; then
        ok "gate_docs_only_plan is defined"
    else
        bad "there is no docs-only road here to admit anybody"
        return
    fi

    docs_only_world
    plant_derived_leg "$REPO" \
        "derived — a per-box artefact; nothing measured reads it back"
    plant_derived_member "$REPO" ||
        cannot_look "the derived artefact would not commit in the docs-only world"
    DOCSONLY_M=$(git -C "$REPO" rev-parse HEAD)
    DOCSONLY_MTREE=$(git -C "$REPO" rev-parse "HEAD^{tree}")
    local measured
    measured=$(in_repo "$REPO" gate_measured_tree 2>/dev/null) || measured=""
    [ -n "$measured" ] ||
        cannot_look "gate_measured_tree would not answer in the declaring docs-only world"
    [ "$measured" != "$DOCSONLY_MTREE" ] ||
        cannot_look "the planted declaration did not move the key — both readings are ${measured}"
    # THE ROW A FULL GATE WOULD HAVE WRITTEN, keyed where a full gate keys it:
    # on the MEASURED tree. Planting it on the raw tree instead would be
    # writing a row this product's own gate never writes.
    plant_full_row "$REPO" "$measured" "$DOCSONLY_LEGS"
    docs_only_commit "$DOCSONLY_DOC" "one more row"

    CURRENT="a docs-only commit on a DECLARING product takes the docs-only road"
    plan_in "$REPO" HEAD
    # rc 0 is exactly what makes `pm_push.sh --bank` print `docs-only? yes`;
    # rc 1 is the "… — full bank" sentence in GATE_DOCS_ONLY_WHY below.
    is "$PLAN_RC" "0" "the decision"
    is "$GATE_DOCS_ONLY_WHY" "" "the refusal sentence (there is none)"
    is "$GATE_DOCS_ONLY_SOURCE" "$measured" "the source tree — the ancestor's MEASURED tree"
    is "$GATE_DOCS_ONLY_N" "1" "the size of the delta"
    is "$GATE_DOCS_ONLY_LEGS" "$DOCSONLY_LEGS" "the legs field, copied from the source row"

    CURRENT="and a non-docs path in the delta still refuses on a declaring product"
    # THE NEGATIVE THAT KEEPS THE ROAD FROM WIDENING. Subtracting the declared
    # path must not subtract anything else: an `apps/` change on top of the
    # same declaring world is a full bank, named, exactly as it is anywhere.
    printf 'print("a change nothing measured")\n' >"$REPO/apps/loud.py"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "an apps/ change on the declaring product"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    case "$GATE_DOCS_ONLY_WHY" in
    *"apps/loud.py is not a docs-only path"*) ok "the refusal names the path that closed the road" ;;
    *) bad "an apps/ change was admitted, or refused without naming the path: '${GATE_DOCS_ONLY_WHY}'" ;;
    esac
}

# --- the docs-only road: a QUOTE is what the judge proves, and a module may say it is no read --
#
# THE MEASURED SHAPE. `apps/core/tests/test_drawer_seam.py` quotes
# `docs/product/queue.md` as a STRING handed to the engine over `tmp_path` and
# opens no file; the road called that "read literally" and refused every ledger
# push. The three cases below are its three answers: a declared quote takes the
# road, an undeclared one still refuses and says only what was proven, and a
# declaration that outlived its quote is refused, naming its own line.
#
# THE MARKER IS ASSEMBLED, never typed whole in this file, so the only
# declarations any census could read are the ones a case writes into its world.
NONREAD_MARK="names, never reads:"

case_a_quote_the_module_declares_a_non_read_takes_the_road() {
    CURRENT="a quoted docs path its module declares a non-read is admitted"
    docs_only_world
    {
        printf '# %s %s — a string handed to an engine, never opened\n' "$NONREAD_MARK" "$DOCSONLY_DOC"
        printf 'PATH = "%s"\n' "$DOCSONLY_DOC"
    } >"$REPO/apps/a.py"
    docs_only_rebase_m "a module that QUOTES a docs path and declares it no read"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    is "$GATE_DOCS_ONLY_WHY" "" "the refusal sentence (a declared quote is none)"
    case "$GATE_DOCS_ONLY_READERS" in
    static | static,*) ok "the readers are derived as on any docs-only push: ${GATE_DOCS_ONLY_READERS}" ;;
    *) bad "a declared quote derived no readers: '${GATE_DOCS_ONLY_READERS}'" ;;
    esac

    CURRENT="the declaration covers ITS OWN module only — the same quote next door refuses"
    printf 'OTHER = "%s"\n' "$DOCSONLY_DOC" >"$REPO/apps/b.py"
    docs_only_rebase_m "a second module quoting the same path, declaring nothing"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    is "$GATE_DOCS_ONLY_WHY" \
        "docs-only? no — ${DOCSONLY_DOC} is quoted at apps/b.py:1 and nothing declares the quote a non-read — full bank" \
        "the refusal names the undeclared module, not the declaring one"
}

case_an_undeclared_quote_refuses_and_names_a_quote_not_a_read() {
    CURRENT="an undeclared quote still refuses — the loud direction is kept"
    docs_only_world
    {
        printf '"""A docstring quoting '"'"'%s'"'"' and opening nothing."""\n' "$DOCSONLY_DOC"
    } >"$REPO/apps/a.py"
    docs_only_rebase_m "a module that quotes a docs path and declares nothing"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    is "$GATE_DOCS_ONLY_WHY" \
        "docs-only? no — ${DOCSONLY_DOC} is quoted at apps/a.py:1 and nothing declares the quote a non-read — full bank" \
        "the refusal says QUOTED — what the judge proved — never 'read'"
    case "$GATE_DOCS_ONLY_WHY" in
    *"read literally"*) bad "the refusal still names a read it never proved" ;;
    *) ok "the refusal names no cause it has not proven" ;;
    esac

    CURRENT="a declaration naming ANOTHER path does not cover this quote"
    {
        printf '# %s %s — a different path\n' "$NONREAD_MARK" "${DOCSONLY_DIR}/elsewhere.md"
        printf 'ELSEWHERE = "%s"\n' "${DOCSONLY_DIR}/elsewhere.md"
        printf 'PATH = "%s"\n' "$DOCSONLY_DOC"
    } >"$REPO/apps/a.py"
    docs_only_rebase_m "a module declaring one path and quoting two"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    is "$GATE_DOCS_ONLY_WHY" \
        "docs-only? no — ${DOCSONLY_DOC} is quoted at apps/a.py:3 and nothing declares the quote a non-read — full bank" \
        "the refusal names the uncovered quote's own line"
}

case_a_stale_non_read_declaration_is_refused_naming_its_line() {
    CURRENT="a declaration naming a path its module never quotes is refused"
    docs_only_world
    {
        printf '"""A module that quotes nothing at all."""\n'
        printf '# %s %s — the quote this excused was deleted\n' "$NONREAD_MARK" "${DOCSONLY_DIR}/gone.md"
    } >"$REPO/config/stale.py"
    docs_only_rebase_m "a module whose declaration outlived its quote"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    is "$GATE_DOCS_ONLY_WHY" \
        "docs-only? no — config/stale.py:2 declares ${DOCSONLY_DIR}/gone.md a non-read and the module never quotes it — a stale declaration — full bank" \
        "the refusal names the stale line"

    CURRENT="a PROSE mention does not keep a declaration alive — only a quote does"
    {
        printf '"""Mentions `%s` in backticks, which is prose."""\n' "${DOCSONLY_DIR}/gone.md"
        printf '# %s %s — the quote this excused was deleted\n' "$NONREAD_MARK" "${DOCSONLY_DIR}/gone.md"
    } >"$REPO/config/stale.py"
    docs_only_rebase_m "the stale declaration beside a prose mention"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    case "$GATE_DOCS_ONLY_WHY" in
    *"config/stale.py:2 declares ${DOCSONLY_DIR}/gone.md"*"stale declaration"*) ok "still stale: ${GATE_DOCS_ONLY_WHY}" ;;
    *) bad "a prose mention kept a stale declaration alive: '${GATE_DOCS_ONLY_WHY}'" ;;
    esac
}

case_a_path_outside_the_declared_list_is_a_full_bank() {
    docs_only_world
    printf 'one more row\n' >>"${REPO}/${DOCSONLY_DOC}"
    printf 'a lock line\n' >>"$REPO/uv.lock"
    git -C "$REPO" add -A >/dev/null
    git -C "$REPO" commit -q -m "a docs row and a lock file"

    CURRENT="one path off the declared list and the whole delta is a full bank"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    is "$GATE_DOCS_ONLY_WHY" \
        "docs-only? no — uv.lock is not a docs-only path — full bank" \
        "the refusal"
    is "$GATE_DOCS_ONLY_READERS" "" "the readers (none were derived)"

    CURRENT="the declared list is exactly what was ratified, in and out"
    local p
    for p in docs/product/queue.md README.md CLAUDE.md \
        .claude/skills/fixture/SKILL.md scripts/test_impact.json; do
        if in_repo "$REPO" gate_docs_only_admits "$p"; then
            ok "${p} is on the list"
        else
            bad "${p} is NOT on the declared list and the ratified list says it is"
        fi
    done
    # OUT, AND OUT BY MEASUREMENT: pytest reads both, so a release still pays
    # one bank. A green here the day somebody widens the list is the whole
    # point of asserting the negative side.
    for p in CHANGELOG.md TEMPLATE_VERSION uv.lock scripts/check.sh; do
        if in_repo "$REPO" gate_docs_only_admits "$p"; then
            bad "${p} is on the declared list and the ratification says it is OUT"
        else
            ok "${p} is not on the list"
        fi
    done
}

case_the_readers_are_derived_per_path_and_a_literal_read_refuses() {
    CURRENT="a docs path a module under apps/ really OPENS is a full bank, named"
    docs_only_world
    printf 'PATH = "%s"\n' "$DOCSONLY_DOC" >"$REPO/apps/a.py"
    docs_only_rebase_m "a module that opens a docs path"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "1" "the decision"
    case "$GATE_DOCS_ONLY_WHY" in
    *"apps/a.py:1"*"full bank"*) ok "the refusal names the file and the line: '${GATE_DOCS_ONLY_WHY}'" ;;
    *) bad "the literal read was admitted, or refused without a coordinate: '${GATE_DOCS_ONLY_WHY}'" ;;
    esac

    CURRENT="the SAME path in a comment or in backticks is prose, and is admitted"
    docs_only_world
    {
        printf '# the rows live in %s and nothing here opens them\n' "$DOCSONLY_DOC"
        printf '"""A docstring naming `%s` and opening nothing."""\n' "$DOCSONLY_DOC"
    } >"$REPO/apps/a.py"
    docs_only_rebase_m "a module that MENTIONS a docs path"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    is "$GATE_DOCS_ONLY_WHY" "" "the refusal sentence (prose is not a read)"

    CURRENT="a YAML file: value under quality/ runs the house-rules engine"
    docs_only_world
    printf 'rules:\n  - id: x\n    doc: { file: %s, contains: "a row" }\n' "$DOCSONLY_DOC" \
        >"$REPO/quality/quiet.yaml"
    docs_only_rebase_m "a rule whose doc: names a docs path"
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    case ",${GATE_DOCS_ONLY_READERS}," in
    *,full-house-rules,*) ok "the engine is a derived reader: ${GATE_DOCS_ONLY_READERS}" ;;
    *) bad "a quality/ literal read derived no engine run: ${GATE_DOCS_ONLY_READERS}" ;;
    esac

    CURRENT="static is ALWAYS a reader, and a drive that declares the directory is one too"
    docs_only_world
    docs_only_commit "$DOCSONLY_DOC" "one more row"
    plan_in "$REPO" HEAD
    is "$PLAN_RC" "0" "the decision"
    case "$GATE_DOCS_ONLY_READERS" in
    static | static,*) ok "static leads the list: ${GATE_DOCS_ONLY_READERS}" ;;
    *) bad "static is not a derived reader: ${GATE_DOCS_ONLY_READERS}" ;;
    esac
    case ",${GATE_DOCS_ONLY_READERS}," in
    *,scripts/tests/test_reads_docs.sh,*) ok "the drive declaring the docs DIRECTORY is listed" ;;
    *) bad "a drive declaring the docs directory was not derived for a file under it: ${GATE_DOCS_ONLY_READERS}" ;;
    esac
    # A CITATION IS NOT A SUBJECT. The second drive names the very file that
    # moved, on its `cites:` line, and must NOT be re-driven for it.
    case ",${GATE_DOCS_ONLY_READERS}," in
    *,scripts/tests/test_cites_docs.sh,*) bad "a cited path selected a drive — a citation is not a subject" ;;
    *) ok "the drive that only CITES the path is not a reader" ;;
    esac
}

# --- the FULL ledger's legs field, which nobody read (R3's F3) ----------------

#: A scratch checkout whose `scripts/check.sh` DECLARES a leg set, so
#: `gate_full_legs` has something to read. `$1` is the declaration.
legs_checkout() {
    fresh_checkout
    printf '#!/usr/bin/env bash\nFULL_LEGS=%s\n' "$1" >"$REPO/scripts/check.sh"
    chmod +x "$REPO/scripts/check.sh"
}

#: One full-ledger row with the legs field set, planted into the scratch repo's
#: own verdict ledger — the file `gate_ledger_path` resolves through
#: `--git-common-dir`, so this forges nothing anywhere else.
#:
#: `$4` is APPENDED VERBATIM after `caller=drive`, and it is how the leak-proof
#: cases plant a ` leak-proof=…` field (the row's last token pair) without a
#: second plant helper that could drift from this one. Absent — every caller
#: that existed before that field — plants exactly the row it always did.
plant_full_row() {
    local repo="$1" tree="$2" legs="$3" extra="${4:-}" path
    path=$(cd "$repo" && gate_ledger_path) ||
        cannot_look "gate_ledger_path would not answer in the scratch checkout"
    printf 'v1 %s full 2026-09-16T00:00:00Z %s caller=drive%s\n' "$tree" "$legs" "$extra" >>"$path"
    echo "  PLANT TOOK · full row: tree=${tree} legs=${legs}${extra}"
}

case_a_banked_row_whose_legs_do_not_cover_this_gate_is_not_honoured() {
    # THE REVIEW'S OWN FINDING, DRIVEN. The row said which legs ran and the
    # lookup matched tree and `full` only, so a SHORTER set was honoured
    # exactly as a complete one. Not
    # unsound on this tree — `check.sh` is inside the measured tree and `--leg`
    # banks nothing — which is why nothing could reach this state without a
    # plant, and why the plant is how it has to be shown.
    # THE TREE IS ASSEMBLED, NEVER SPELLED — the drive's own rule, one case
    # over: forty hex characters in a row after a `=` is a high-entropy string
    # to every scanner in this tree, and the `--loop` secrets leg said so.
    local tree
    tree=$(sha40 legs-row)
    legs_checkout "ruff,mypy,pytest-x2,selftest"

    CURRENT="a row naming fewer legs than the gate declares is not a hit"
    plant_full_row "$REPO" "$tree" "ruff,mypy"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "1" "gate_has_green on a short-legs row"

    CURRENT="and the refusal says which leg the row does not cover"
    N=$((N + 1))
    OUT="${WORK}/shortlegs${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || true
    if grep -F "missing 'pytest-x2'" "$OUT" >/dev/null; then
        ok "the note names the first leg the row does not cover"
    else
        bad "the lookup refused without saying what it refused for"
    fi
    OUT=""

    CURRENT="a row naming exactly the declared set IS a hit"
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2,selftest"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green on a complete row"

    CURRENT="and a row naming MORE is a hit too — a superset is a stronger claim"
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2,selftest,something-new"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green on a superset row"
}

case_a_checkout_with_no_gate_declares_no_leg_set_and_compares_nothing() {
    # THE DECLARED GAP, ASSERTED SO IT IS VISIBLE RATHER THAN IMPLIED. The leg
    # set is a property of the gate in this checkout; a directory with no
    # `scripts/check.sh` declares none, so there is nothing to compare against
    # and the lookup is what it always was. `scripts/tests/test_gate_lease.sh`
    # consults exactly such a repo, with a two-leg row from before the caller
    # field existed, and that row must go on being honoured.
    local tree
    tree=$(sha40 no-gate-row)
    fresh_checkout
    rm -f "$REPO/scripts/check.sh"

    CURRENT="a checkout with no gate reads no declaration"
    is "$(cd "$REPO" && gate_full_legs)" "" "the declared leg set"

    CURRENT="so a two-leg row from the ledger's own history is still honoured"
    plant_full_row "$REPO" "$tree" "ruff,mypy"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green where nothing declares a leg set"
}

# --- the LEAK PROOF: written last, read as a condition on one pass ----------
#
# WHY THE FIELD EXISTS. Under `pm_push.sh --bank --on-boxes N` the sharded
# `pytest-x2` unit runs ONE pass and the whole-suite two-pass leak proof runs on
# the acceptance box (ADR gate-1, amended 2026-09-18). A row that ran one pass
# and names `pytest-x2` is a green vouching for more than ran, so the row
# carries the proof it stood on — `leak-proof=acceptance:<box-id> rc=<n>`, the
# LAST field, appended exactly as `sanction=`/`waited=`/`took=` were and with
# the schema tag unmoved — and the reader honours a `<leg>/1` member only when
# that proof is present and green.
#
# `does_not_cover`, declared beside the cases rather than discovered:
#
#   * WHETHER THE ACCEPTANCE BOX'S PROOF WAS HONEST. A local row is a local
#     line — the ledger's standing trust class, `scripts/gate_ledger.sh:31-33`.
#     These cases prove that a one-pass row WITHOUT a green proof is refused,
#     which is a different property and the only one a local file can have.
#   * WHETHER THE BOX-ID IN THE FIELD NAMES A BOX THAT EXISTED. The grammar is
#     checked; the instance is not looked up, here or anywhere.
#   * THE COMPOSITION THAT SETS THE GLOBAL. `GATE_RUN_LEAK_PROOF` is written by
#     `scripts/pm_push.sh`'s bank and read here; these cases set it by hand,
#     so a bank that computed the wrong value would write a well-formed row
#     saying the wrong thing and nothing below would see it.
#   * A SECOND UNIT EVER EARNING THE ONE-PASS EXEMPTION. Which unit may run a
#     single pass is pinned BY NAME to `pytest-x2` — ADR gate-1's amendment
#     sanctions the sharded pytest unit alone, and a case below proves a green
#     pytest proof buys nothing for a one-pass `selftest`. What is not covered
#     is the day a second two-pass unit is added: that means editing the name
#     in `gate_ledger_lookup`, and nothing here would notice it had not been.

#: The last FULL row in a repo's own verdict ledger, or nothing.
last_full_row() {
    local repo="$1" path
    path=$(cd "$repo" && gate_ledger_path) ||
        cannot_look "gate_ledger_path would not answer in the scratch checkout"
    [ -f "$path" ] || return 0
    grep -F ' full ' "$path" | tail -1
}

#: How many FULL rows the repo's ledger holds. "Writes NOTHING" is a count, and
#: a refusal that wrote a half-row would pass a substring assertion.
full_row_count() {
    local repo="$1" path n
    path=$(cd "$repo" && gate_ledger_path) ||
        cannot_look "gate_ledger_path would not answer in the scratch checkout"
    [ -f "$path" ] || {
        echo 0
        return 0
    }
    n=$(grep -c -F ' full ' "$path") || n=0
    echo "$n"
}

case_the_leak_proof_field_is_appended_last_or_the_row_is_refused() {
    # THE WRITER (b.1). The field is LAST — after `took=` — one space-separated
    # token pair; newlines are stripped exactly as `sanction`'s are, so a value
    # carrying one can never become two rows; a value that does not match
    # `acceptance:<id> rc=<digits>` is REFUSED and writes nothing, because a row
    # nothing can parse is worse than a row that says nothing; and an empty
    # value writes today's row, which is every row ever banked before now.
    local tree row before after
    tree=$(sha40 leak-proof-writer)
    fresh_checkout

    CURRENT="a well-formed proof is appended LAST, after took="
    (cd "$REPO" && GATE_PYTEST_TOOK=7 GATE_RUN_LEAK_PROOF="acceptance:i-0123abc rc=0" \
        gate_ledger_record "$tree" "ruff,pytest-x2/1") ||
        bad "gate_ledger_record refused a well-formed leak proof"
    row=$(last_full_row "$REPO")
    case "$row" in
    *" waited=0 took=7 leak-proof=acceptance:i-0123abc rc=0")
        ok "the row ends ' waited=0 took=7 leak-proof=acceptance:i-0123abc rc=0'"
        ;;
    *) bad "the row does not end with the proof: ${row}" ;;
    esac

    CURRENT="and the row is still one line, and still a hit for its own tree"
    is "$(full_row_count "$REPO")" "1" "the ledger's full-row count"
    RC=0
    (cd "$REPO" && gate_ledger_lookup "$tree" >/dev/null) 2>/dev/null || RC=$?
    is "$RC" "0" "gate_ledger_lookup on the row it just wrote"

    CURRENT="a newline in the value is stripped, never allowed to make two rows"
    before=$(full_row_count "$REPO")
    (cd "$REPO" && GATE_PYTEST_TOOK=7 GATE_RUN_LEAK_PROOF="acceptance:i-0123abc rc=0
" gate_ledger_record "$tree" "ruff,pytest-x2/1") ||
        bad "a trailing newline made the recorder refuse a well-formed proof"
    after=$(full_row_count "$REPO")
    is "$((after - before))" "1" "rows added by a value with a trailing newline"
    row=$(last_full_row "$REPO")
    case "$row" in
    *"leak-proof=acceptance:i-0123abc rc=0")
        ok "the stripped value is what reached the row"
        ;;
    *) bad "the newline reached the row or the value did not: ${row}" ;;
    esac

    CURRENT="a value whose newline would forge a second row is malformed, and refused"
    before=$(full_row_count "$REPO")
    N=$((N + 1))
    OUT="${WORK}/leakproof-forge${N}.log"
    RC=0
    (cd "$REPO" && GATE_RUN_LEAK_PROOF="acceptance:i-0123abc rc=0
v1 forged full 2026-09-18T00:00:00Z everything caller=nobody" \
        gate_ledger_record "$tree" "ruff,pytest-x2/1") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "gate_ledger_record's status on a value carrying a second row"
    is "$(full_row_count "$REPO")" "$before" "the ledger's full-row count after the refusal"
    OUT=""

    CURRENT="every malformed shape is refused, writes nothing, and says so on stderr"
    local badvalue
    for badvalue in \
        "i-0123abc rc=0" \
        "acceptance:i-0123abc" \
        "acceptance:i-0123abc rc=" \
        "acceptance:i-0123abc rc=x" \
        "acceptance: rc=0" \
        "acceptance:i 0123abc rc=0" \
        "acceptance:i-0123abc rc=0 and more" \
        "acceptance:i-0123abc rc=00" \
        "acceptance:i-0123abc rc=01"; do
        # THE LAST TWO ARE THE WRITER MEETING THE READER'S GRAMMAR. The reader
        # honours exactly `rc=0`, so a writer that took `rc=00` would bank a
        # row whose green the reader reads as red — a disagreement neither end
        # can flag, refused at the only end that can still fix it.
        before=$(full_row_count "$REPO")
        N=$((N + 1))
        OUT="${WORK}/leakproof-bad${N}.log"
        RC=0
        (cd "$REPO" && GATE_RUN_LEAK_PROOF="$badvalue" \
            gate_ledger_record "$tree" "ruff,pytest-x2/1") >"$OUT" 2>&1 || RC=$?
        if [ "$RC" = "1" ] && [ "$(full_row_count "$REPO")" = "$before" ]; then
            ok "'${badvalue}' → exit 1, nothing written"
        else
            bad "'${badvalue}' → exit ${RC}, rows ${before} → $(full_row_count "$REPO")"
        fi
        if grep -F "leak-proof" "$OUT" >/dev/null; then
            ok "'${badvalue}' → the note on stderr names the field"
        else
            bad "'${badvalue}' → refused without saying what it refused for"
        fi
        OUT=""
    done

    CURRENT="an EMPTY value writes today's row — no field, byte-for-byte"
    fresh_checkout
    tree=$(sha40 leak-proof-empty)
    (cd "$REPO" && GATE_PYTEST_TOOK=7 GATE_RUN_LEAK_PROOF="" \
        gate_ledger_record "$tree" "ruff,pytest-x2") ||
        bad "the recorder refused an empty leak proof — every row banked before this field existed carries one"
    row=$(last_full_row "$REPO")
    case "$row" in
    *"leak-proof"*) bad "an empty value still wrote a field: ${row}" ;;
    *" waited=0 took=7") ok "the row ends ' waited=0 took=7', exactly as it did before the field existed" ;;
    *) bad "the row is not today's shape: ${row}" ;;
    esac
}

case_a_one_pass_row_is_honoured_only_with_a_green_leak_proof() {
    # THE READER (b.2), AND IT IS THE ONE CHANGE TO THE COVER RULE. A required
    # leg is covered when a row member IS the leg name (today), OR when it is
    # `<leg>/1` AND the row carries a green `leak-proof=acceptance:<id> rc=0`.
    #
    # THE TREE IS ASSEMBLED, NEVER SPELLED — the drive's own rule, two cases
    # over: forty hex characters after a `=` is a high-entropy string to every
    # scanner in this tree, and the `--loop` secrets leg said so.
    local tree
    legs_checkout "ruff,mypy,pytest-x2,selftest"

    CURRENT="(i) a one-pass member WITH a green proof is honoured"
    tree=$(sha40 onepass-green)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/1,selftest" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green on a one-pass row with a green proof"

    CURRENT="(ii) a one-pass member whose proof is RED is not honoured"
    tree=$(sha40 onepass-red)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/1,selftest" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=1"
    RC=0
    N=$((N + 1))
    OUT="${WORK}/onepass-red${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "gate_ledger_lookup on a one-pass row whose proof is red"
    if grep -F "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof (leak-proof=acceptance:i-0f1e2d3c rc=1)" "$OUT" >/dev/null; then
        ok "the note names the proof it refused and quotes it"
    else
        bad "the note does not name the red proof"
    fi
    OUT=""

    CURRENT="(iii) a one-pass member with NO proof at all is not honoured"
    tree=$(sha40 onepass-none)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/1,selftest"
    RC=0
    N=$((N + 1))
    OUT="${WORK}/onepass-none${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "gate_ledger_lookup on a one-pass row with no proof"
    if grep -F "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof (leak-proof=none)" "$OUT" >/dev/null; then
        ok "the note says the field is absent rather than implying it was read"
    else
        bad "the note does not say the proof is absent"
    fi
    OUT=""

    CURRENT="(iii·b) a one-pass member whose proof is MALFORMED is not honoured"
    tree=$(sha40 onepass-malformed)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/1,selftest" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "1" "gate_has_green on a one-pass row whose proof will not parse"

    CURRENT="(iv) today's two-pass row, with no field, is unchanged — the negative"
    tree=$(sha40 twopass-today)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2,selftest"
    RC=0
    N=$((N + 1))
    OUT="${WORK}/twopass-today${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "gate_ledger_lookup on today's complete row"
    if grep -F "leak-proof" "$OUT" >/dev/null; then
        bad "a row with no proof drew a note about one"
    else
        ok "no note — a row that needed no proof is read exactly as it was"
    fi
    OUT=""

    CURRENT="(v) a proof on a TWO-pass row is honoured anyway, and SAID — never silently taken"
    tree=$(sha40 twopass-extra-proof)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2,selftest" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=1"
    RC=0
    N=$((N + 1))
    OUT="${WORK}/twopass-extra${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "gate_ledger_lookup on a two-pass row carrying an unneeded proof"
    if grep -F "leak-proof ignored: the row ran two passes" "$OUT" >/dev/null; then
        ok "the reader prints the field it did not need — the valve rule"
    else
        bad "a red proof rode along on a honoured row and nothing said so"
    fi
    OUT=""

    CURRENT="(vi) '<leg>/2' is the leg, spelled with its pass count"
    tree=$(sha40 twopass-spelled)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/2,selftest"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green on a row spelling 'pytest-x2/2'"

    CURRENT="(vi·b) and a two-digit pass count is still a pass count"
    tree=$(sha40 tenpass-spelled)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/10,selftest"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green on a row spelling 'pytest-x2/10'"

    # THE SUFFIX IS A DECIMAL, AND A GLOB IS NOT. A `<leg>/*` pattern honours
    # every one of these — two of which claim LESS than one pass, one of which
    # is empty and one of which is not a pass count at all — while the rule's
    # own prose promises "at or above the default". A cover rule wider than its
    # sentence is a green nothing argued for, so each shape is planted and each
    # must fall through to the generic missing-leg refusal: a member this
    # reader cannot interpret is not a member it may honour.
    local shape
    for shape in "pytest-x2/0" "pytest-x2/" "pytest-x2/x" "pytest-x2/1/1"; do
        CURRENT="(vi·c) a '${shape}' member is not a pass count and is not honoured"
        tree=$(sha40 "suffix-${shape}")
        plant_full_row "$REPO" "$tree" "ruff,mypy,${shape},selftest" \
            " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
        RC=0
        N=$((N + 1))
        OUT="${WORK}/suffix${N}.log"
        (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
        is "$RC" "1" "gate_ledger_lookup on a row whose member is '${shape}'"
        if grep -F "missing 'pytest-x2'" "$OUT" >/dev/null; then
            ok "'${shape}' → the note names the leg the row does not cover"
        else
            bad "'${shape}' → refused without naming the leg, or was honoured"
        fi
        OUT=""
    done

    CURRENT="(vii) ONE PASS IS SANCTIONED FOR ONE UNIT — a pytest proof does not vouch for 'selftest'"
    # ADR gate-1's amendment bends the two-pass rule for the SHARDED PYTEST
    # UNIT and nothing else. The acceptance box runs a whole-suite two-pass
    # PYTEST run, so it has nothing to say about what a one-pass `selftest`
    # left behind; a generic rule would let one leg's proof buy another leg's
    # second pass, which is the exact claim this ledger exists to refuse.
    tree=$(sha40 onepass-wrong-unit)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2,selftest/1" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
    RC=0
    N=$((N + 1))
    OUT="${WORK}/wrongunit${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "gate_ledger_lookup on a one-pass 'selftest' carrying a GREEN pytest proof"
    if grep -F "missing 'selftest' — the row ran ONE pass of a leg that is not 'pytest-x2', and one pass is sanctioned for that unit alone" "$OUT" >/dev/null; then
        ok "the note says WHICH unit may run one pass, rather than blaming the proof"
    else
        bad "a green pytest proof bought a second pass for another leg, or the note does not say why not"
    fi
    OUT=""

    CURRENT="and a SUPERSET of the declared set still hits, proof or no proof"
    tree=$(sha40 onepass-superset)
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2/1,selftest,something-new" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green on a one-pass superset row with a green proof"

    CURRENT="and a row still SHORT of the declared set is refused as it always was"
    tree=$(sha40 onepass-short)
    plant_full_row "$REPO" "$tree" "ruff,mypy" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
    RC=0
    N=$((N + 1))
    OUT="${WORK}/onepass-short${N}.log"
    (cd "$REPO" && gate_ledger_lookup "$tree") >"$OUT" 2>&1 || RC=$?
    is "$RC" "1" "gate_ledger_lookup on a short row carrying a green proof"
    if grep -F "missing 'pytest-x2'" "$OUT" >/dev/null; then
        ok "a green proof does not buy a leg the row never names"
    else
        bad "the short-row refusal lost its note"
    fi
    OUT=""
}

#: One DRIVE row — the ledger's second kind, third field `drive` — planted into
#: scratch repo's own verdict ledger. Its key is handed in, so a case can make it
#: equal a tree sha and ask whether the full belt can be made to read it.
plant_drive_row() {
    local repo="$1" key="$2" name="$3" path
    path=$(cd "$repo" && gate_ledger_path) ||
        cannot_look "gate_ledger_path would not answer in the scratch checkout"
    printf 'v1 %s drive 2026-09-18T00:00:00Z %s exit=0 took=7 tree=%s\n' \
        "$key" "$name" "$key" >>"$path"
    echo "  PLANT TOOK · drive row: key=${key} name=${name}"
}

case_a_drive_row_is_never_a_full_verdict() {
    # THE ONE FILE, AND THE ONE RULE THAT MAKES IT SAFE. The drive verdicts are a
    # KIND in `djb-gate-verdicts` rather than opening a second file, which is the
    # shape the partition's separate ledger argues against. The whole safety of
    # that decision is this: `gate_ledger_lookup` matches ` <tree> full ` and a
    # drive row's third field is `drive`, so no drive row can ever be honoured as
    # a full verdict — not even one whose KEY is, by construction, exactly a tree
    # sha. That is the adversarial case, and it is the only way to show the
    # property rather than assert it.
    local tree
    tree=$(sha40 drive-row-not-a-full-verdict)
    legs_checkout "ruff,mypy,pytest-x2,selftest"

    CURRENT="a drive row whose key IS a tree sha is not a full verdict for that tree"
    plant_drive_row "$REPO" "$tree" "sweep"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "1" "gate_has_green where the only row for the tree is a drive row"

    CURRENT="and a real full row for the same tree still is one"
    plant_full_row "$REPO" "$tree" "ruff,mypy,pytest-x2,selftest"
    RC=0
    (cd "$REPO" && gate_has_green "$tree") 2>/dev/null || RC=$?
    is "$RC" "0" "gate_has_green once a full row exists beside the drive row"
}

# --- the machine half of a drive key -----------------------------------------
#
# WHY IT IS HERE AND NOT IN THE SELFTEST LEG'S DRIVE. This is a property of
# `drive_key` — one function in `scripts/gate_ledger.sh` — and it is asked of it
# directly, with the machine planted, rather than through a leg that would have
# to run a whole drive set to show one digest. The LEG's half (the REUSED line,
# the ingest, the could-not-look) is `test_selftest_leg.sh`'s.
#
# THE DEFECT IT CLOSES, measured on main before it: the machine half was
# `bash --version`/`git --version`/`uname -sr`, so a row banked on this laptop
# keyed `drive-v1:088c3cc6…` and the SAME drive over the SAME inputs on a Linux
# box keyed `drive-v1:e156a225…`. Correct — a Darwin verdict is not a Linux
# verdict — and it also meant a fresh verifier box arrived with an empty ledger
# and re-drove all thirty drives, every bank. Two boxes cut from ONE IMAGE are
# the same machine in every way this key cares about; the image id is one token
# that says so, and it is a stronger claim than three version strings rather
# than a weaker one.
case_the_machine_half_is_the_image_on_a_box_and_the_host_elsewhere() {
    local dir="${WORK}/machine-half"
    rm -rf "$dir"
    mkdir -p "$dir/set" "$dir/shim"

    # A SCRATCH DRIVE SET AND A FABRICATED LISTING, so the only thing that moves
    # between the arms below is the machine. The declared path is one this tree
    # really has, and the listing is the three fields `git ls-tree -r` prints.
    printf '# a scratch drive set preamble — never sourced, always keyed\n' \
        >"$dir/set/drive_preamble.sh"
    printf '#!/bin/sh\n# drives: scripts/gate_ledger.sh\nexit 0\n' \
        >"$dir/set/test_machinehalf.sh"
    printf '100644 blob %s\tscripts/gate_ledger.sh\n' "$(sha40 machine-half-blob)" \
        >"$dir/listing"

    # A `bash` THAT ANSWERS A DIFFERENT VERSION, on PATH and nothing else. It is
    # what makes "two boxes of one image agree" a claim rather than a tautology:
    # without it the two arms would be the same machine twice.
    printf '#!/bin/sh\necho "GNU bash, version 9.9.9(1)-release"\n' >"$dir/shim/bash"
    chmod +x "$dir/shim/bash"

    printf 'ami-0aaaa1111aaaa1111\n' >"$dir/image-a"
    printf 'ami-0bbbb2222bbbb2222\n' >"$dir/image-b"

    # "NO MACHINE FILE" IS PLANTED TOO, AND THAT IS NOT BELT-AND-BRACES. This
    # drive runs on a verifier box as well as on a laptop, and a box HAS
    # `/etc/djb/image-id` — so an arm that meant "the host digest" by simply
    # not setting the seam measured the box's own image there and the case
    # failed on the one machine the mechanism is for. It paid for itself on the
    # first box run: two arms red, for the drive's assumption and not the code's.
    : >"$dir/absent-marker"
    rm -f "$dir/absent-marker"

    # EVERY ARM IN ITS OWN SUBSHELL WITH THE MEMO UNSET. `drive_machine_digest`
    # memoises through the ENVIRONMENT so a leg pays one read; a case that
    # planted a second machine in the same shell would be reading the first
    # one's answer and would pass whatever the code did.
    keyof() {
        (
            unset DRIVE_MACHINE_DIGEST DRIVE_MACHINE_LABEL
            export DJB_DRIVE_MACHINE_FILE="${1:-$dir/absent-marker}"
            [ -z "${2:-}" ] || export PATH="$2:$PATH"
            drive_key "$dir/set/test_machinehalf.sh" fake-tree "$dir/listing" 2>&1
        )
    }

    local host_out imga_out imga_shim_out imgb_out
    host_out="$(keyof "" "")"
    imga_out="$(keyof "$dir/image-a" "")"
    imga_shim_out="$(keyof "$dir/image-a" "$dir/shim")"
    imgb_out="$(keyof "$dir/image-b" "")"

    local host_key imga_key imga_shim_key imgb_key
    host_key="$(printf '%s\n' "$host_out" | awk '{print $2}')"
    imga_key="$(printf '%s\n' "$imga_out" | awk '{print $2}')"
    imga_shim_key="$(printf '%s\n' "$imga_shim_out" | awk '{print $2}')"
    imgb_key="$(printf '%s\n' "$imgb_out" | awk '{print $2}')"

    CURRENT="a planted image-id is the machine half"
    case "$imga_out" in
    "ok drive-v1:"*" machine=image:ami-0aaaa1111aaaa1111") ok "the key line ends \`machine=image:<ami>\`" ;;
    *) bad "the key line does not name the image: ${imga_out}" ;;
    esac

    CURRENT="and with no machine file the label is the host"
    case "$host_out" in
    "ok drive-v1:"*" machine=host:"*) ok "the key line ends \`machine=host:<12 hex>\`" ;;
    *) bad "the key line does not name the host: ${host_out}" ;;
    esac

    CURRENT="two boxes of ONE image share a key"
    same "$imga_key" "$imga_shim_key" \
        "the same image id under a different \`bash --version\` keys identically"

    CURRENT="two images never do"
    differs "$imga_key" "$imgb_key" "a different ami is a different key"

    CURRENT="and a box never shares a key with this laptop"
    differs "$imga_key" "$host_key" "the image key and the host key"
    differs "$imgb_key" "$host_key" "the other image key and the host key"

    # THE CANARY. A drive that only asserted the three equalities above would
    # still be green if the machine half stopped being in the key at all — the
    # arms would agree for the wrong reason. This is the plant that fires.
    CURRENT="the machine half is IN the key at all"
    local shim_only_key
    shim_only_key="$(printf '%s\n' "$(keyof "" "$dir/shim")" | awk '{print $2}')"
    differs "$host_key" "$shim_only_key" \
        "with NO machine file, a different \`bash --version\` still re-keys — the host digest is live"

    CURRENT="an unreadable machine file cannot key"
    printf 'ami-0cccc3333cccc3333\n' >"$dir/image-locked"
    chmod 000 "$dir/image-locked"
    local locked_out locked_rc=0
    locked_out="$(keyof "$dir/image-locked" "")" || locked_rc=$?
    chmod 644 "$dir/image-locked"
    is "$locked_rc" "1" "drive_key's status over a machine file it cannot read"
    case "$locked_out" in
    "err this machine could not be digested"*)
        ok "and it says so — never the host key, which would be a Mac row and a box row under one label"
        ;;
    *) bad "an unreadable machine file did not refuse: ${locked_out}" ;;
    esac

    CURRENT="a RELATIVE machine file is refused, like DJB_GATE_LEDGER"
    local rel_out rel_rc=0
    rel_out="$(keyof "not/absolute/image-id" "")" || rel_rc=$?
    is "$rel_rc" "1" "drive_key's status over a relative DJB_DRIVE_MACHINE_FILE"
    case "$rel_out" in
    *"is relative — refusing it"*)
        ok "and the note names the variable and the value"
        ;;
    *) bad "a relative machine file was not refused by name: ${rel_out}" ;;
    esac

    unset -f keyof
}

# --- a RESERVED DRAWER path is judged as if it were in the tree --------------
#
# THE DEFECT IT CLOSES, measured on the first consumer's bank and not here.
# `drive__uncovered` skips a spelled path the MEASURED TREE does not carry,
# and the argument for that (this section's header) is plant names inside a
# throwaway clone. A reserved DRAWER path breaks it: `scripts/local/legs` is
# absent on the template and present on every product that uses the seam, so
# the floor judged their tree and not ours. Ten drives keyed clean here and
# seven of them exited 2 at their bank, on bytes nobody had changed — the
# template could not see its own defect, which is the whole class this
# repository exists to end. A drawer path is therefore judged EVERYWHERE, and
# the cost is one `# cites:` token per drive.
#
# THE GLOBS ARE READ FROM THEIR ONE HOME rather than typed here or in
# `gate_ledger.sh` — `scripts/divergence_census.sh`'s `DRAWER_GLOBS`, which
# says in its own comment that there is one home for which paths are the
# drawers. The last two arms are what make that a derivation instead of a
# copy: every member of the list is exercised, and a home that cannot be read
# is a refusal rather than a floor that judges nothing.
case_a_reserved_drawer_path_is_judged_even_where_the_tree_has_none() {
    local dir="${WORK}/drawer-floor"
    rm -rf "$dir"
    mkdir -p "$dir/set"

    # A FABRICATED LISTING THAT CARRIES NO DRAWER — the template's own shape.
    # `git ls-tree -r`'s three fields, one real path so the top-level prefix
    # list the floor derives is not empty.
    printf '# a scratch drive set preamble — never sourced, always keyed\n' \
        >"$dir/set/drive_preamble.sh"
    {
        printf '100644 blob %s\tscripts/gate_ledger.sh\n' "$(sha40 drawer-floor-a)"
        printf '100644 blob %s\tapps/example/models.py\n' "$(sha40 drawer-floor-b)"
        printf '100644 blob %s\tdocs/product/queue.md\n' "$(sha40 drawer-floor-c)"
        printf '100644 blob %s\tquality/rules.yaml\n' "$(sha40 drawer-floor-d)"
    } >"$dir/listing"

    # keyof <file> — `drive_key` over one scratch drive, output and status.
    keyof() {
        KEYOF_RC=0
        KEYOF_OUT="$(cd "$ROOT" && drive_key "$1" fake-tree "$dir/listing" 2>&1)" || KEYOF_RC=$?
    }

    plant_drive() {
        printf '#!/bin/sh\n# drives: scripts/gate_ledger.sh\n%s# a body that spells %s\nexit 0\n' \
            "${2:-}" "$1" >"$dir/set/test_drawerfloor.sh"
    }

    CURRENT="an undeclared drawer path cannot key, on a tree that has no drawer"
    plant_drive "scripts/local/legs"
    keyof "$dir/set/test_drawerfloor.sh"
    is "$KEYOF_RC" "1" "drive_key's status over an undeclared drawer path"
    case "$KEYOF_OUT" in
    "err its body spells scripts/local/legs and"*)
        ok "and it names the path — the refusal the product would have met is the refusal the template meets"
        ;;
    *) bad "a drawer path absent from the listing was not judged: ${KEYOF_OUT}" ;;
    esac

    CURRENT='and a `# cites:` line is what clears it'
    plant_drive "scripts/local/legs" "# cites: scripts/local/legs
"
    keyof "$dir/set/test_drawerfloor.sh"
    is "$KEYOF_RC" "0" "drive_key's status once the drawer path is cited"
    case "$KEYOF_OUT" in
    "ok drive-v1:"*) ok "the cited drawer keys clean — and a citation never joins the key, so a product's own leg never re-drives it" ;;
    *) bad "a cited drawer path still did not key: ${KEYOF_OUT}" ;;
    esac

    # THE NEGATIVE, AND IT IS THE ONE THAT KEEPS THE FIRST EXCLUSION ALIVE. An
    # ORDINARY path the listing does not carry is still not judged: most drives
    # spell plant names inside a throwaway clone, and demanding a declaration
    # that expands to nothing is a deadlock rather than a belt.
    CURRENT="an ordinary absent path is still not judged"
    plant_drive "apps/zzz_a_plant_no_tree_has/models.py"
    keyof "$dir/set/test_drawerfloor.sh"
    is "$KEYOF_RC" "0" "drive_key's status over an ordinary path the listing does not carry"

    # EVERY MEMBER OF THE LIST, ONE ARM EACH. A floor that only drove
    # `**/local/**` would be green with the other two members deleted from the
    # home — which is the shape `DRAWER_GLOBS`' own count floor exists to
    # refuse, asserted here about the reader instead of the list.
    CURRENT="every reserved glob is judged, not only the first"
    local spelled
    for spelled in docs/product/instruments.local.md apps/conftest_local.py; do
        plant_drive "$spelled"
        keyof "$dir/set/test_drawerfloor.sh"
        is "$KEYOF_RC" "1" "drive_key's status over an undeclared ${spelled}"
    done

    # AND THE HOME IS READ, NEVER ASSUMED. `drive_drawer_globs` reads the
    # census's own assignment; where the census is not there the answer is a
    # REFUSAL, because judging no path as a drawer is the silently-passing
    # direction.
    CURRENT="a home it cannot read is a refusal and never a narrower set"
    local globs_out globs_rc=0
    globs_out="$(cd "$ROOT" && drive_drawer_globs)" || globs_rc=$?
    is "$globs_rc" "0" "drive_drawer_globs' status in this checkout"
    case "$globs_out" in
    *"local"*) ok "the reserved globs come from scripts/divergence_census.sh: ${globs_out}" ;;
    *) bad "the reserved globs do not name the drawers: ${globs_out}" ;;
    esac
    local homeless_rc=0
    (cd "$dir" && drive_drawer_globs) >/dev/null 2>&1 || homeless_rc=$?
    is "$homeless_rc" "1" "drive_drawer_globs' status where the census is not beside it"

    unset -f keyof plant_drive
    unset KEYOF_RC KEYOF_OUT
}

# --- an ABSORBED derived output keys as `absent` ----------------------------
#
# THE DEADLOCK IT CLOSES, and it was the first consumer's. `scripts/test_impact
# .json` is the bank's own output; the release does not ship it, so on every
# product it is absent until their first green bank writes it. Three drives
# DECLARE it, and a declared path that expanded to nothing was a refusal — so
# the bank could not go green because the drives were exit 2, and the drives
# were exit 2 because the bank had not gone green.
#
# THE CLASS IS THE FOLD'S, NOT A NEW ONE. `FOLD_ABSORBED_PATHS`
# (scripts/pm_fold.sh) already names exactly "a derived file written from
# OUTSIDE this checkout that no step here can regenerate", which is the only
# kind of declared path that can legitimately be missing. Read from there, so
# there is one home and not two.
#
# AND `absent` IS A COMPONENT, NOT A SUBTRACTION — the last arm is the one that
# says so: the same drive over a listing that HAS the map keys differently, so
# the day it appears every verdict banked without it misses.
case_an_absorbed_derived_output_keys_as_absent_and_nothing_else_does() {
    local dir="${WORK}/absorbed"
    rm -rf "$dir"
    mkdir -p "$dir/set"
    printf '# a scratch drive set preamble — never sourced, always keyed\n' \
        >"$dir/set/drive_preamble.sh"
    printf '#!/bin/sh\n# drives: scripts/gate_ledger.sh scripts/test_impact.json\nexit 0\n' \
        >"$dir/set/test_absorbed.sh"
    printf '#!/bin/sh\n# drives: scripts/gate_ledger.sh scripts/loop_tier.sh\nexit 0\n' \
        >"$dir/set/test_notabsorbed.sh"
    # TWO LISTINGS THAT DIFFER BY ONE BLOB: the release's (no map) and a tree
    # that has banked once. Neither carries `scripts/loop_tier.sh`, which is
    # the ordinary declared path the refusal must still fire on.
    printf '100644 blob %s\tscripts/gate_ledger.sh\n' "$(sha40 absorbed-a)" >"$dir/without"
    cp "$dir/without" "$dir/with"
    printf '100644 blob %s\tscripts/test_impact.json\n' "$(sha40 absorbed-b)" >>"$dir/with"

    CURRENT="a release that ships no map still keys"
    local out_without rc=0
    out_without="$(cd "$ROOT" && drive_key "$dir/set/test_absorbed.sh" fake-tree "$dir/without" 2>&1)" || rc=$?
    is "$rc" "0" "drive_key's status on a tree with no scripts/test_impact.json"
    case "$out_without" in
    *"scripts/test_impact.json:absent"*)
        ok "the map is in the key, as \`absent\` — a component and not a subtraction"
        ;;
    *) bad "an absorbed path that expands to nothing did not key as absent: ${out_without}" ;;
    esac

    CURRENT="and the day it appears the key moves"
    local out_with rc_with=0
    out_with="$(cd "$ROOT" && drive_key "$dir/set/test_absorbed.sh" fake-tree "$dir/with" 2>&1)" || rc_with=$?
    is "$rc_with" "0" "drive_key's status once the map is in the tree"
    differs "$(printf '%s\n' "$out_without" | awk '{print $2}')" \
        "$(printf '%s\n' "$out_with" | awk '{print $2}')" \
        "the key with no map, and the key with one"

    # THE NEGATIVE, AND IT IS WHAT KEEPS THE REFUSAL ALIVE. Only the fold's
    # absorbed class is excused; an ORDINARY declared path that expands to
    # nothing is still a silently narrower key and still refuses.
    CURRENT="an ordinary declared path that expands to nothing still refuses"
    local out_other rc_other=0
    out_other="$(cd "$ROOT" && drive_key "$dir/set/test_notabsorbed.sh" fake-tree "$dir/without" 2>&1)" || rc_other=$?
    is "$rc_other" "1" "drive_key's status over an undeclarable ordinary path"
    case "$out_other" in
    "err the declared path scripts/loop_tier.sh expands to nothing"*)
        ok "and it names the path — the excuse is the absorbed list and not 'absent is fine'"
        ;;
    *) bad "an ordinary empty expansion did not refuse: ${out_other}" ;;
    esac

    CURRENT="the absorbed list is READ from the fold and not typed twice"
    local list_out list_rc=0
    list_out="$(cd "$ROOT" && drive_absorbed_paths)" || list_rc=$?
    is "$list_rc" "0" "drive_absorbed_paths' status in this checkout"
    is "$list_out" "scripts/test_impact.json" "the absorbed list, against pm_fold.sh's own assignment"
    local homeless_rc=0
    (cd "$dir" && drive_absorbed_paths) >/dev/null 2>&1 || homeless_rc=$?
    is "$homeless_rc" "1" "drive_absorbed_paths' status where the fold is not beside it"
}

case_the_declaration_is_read_from_check_sh_and_not_kept_here() {
    # THE POPULATION IS THE GATE'S OWN ANSWER. A drive that typed the leg set
    # would be the second list this whole file exists to refuse, and it would
    # pass on the day a leg was added and assert nothing ever after.
    #
    # AND ON THIS TREE THE ASSIGNMENT IS STILL THE ANSWER, because this tree
    # has no product-leg drawer. `gate_full_legs` reads the LISTING instead the
    # moment `scripts/local/legs/` holds one — there the text is wrong, since
    # `check.sh` grows `FULL_LEGS` at runtime with one `local:<name>` per
    # declared leg — and `scripts/tests/test_local_legs.sh` is where that half
    # is driven. What this case holds is the half that belongs to the template:
    # no drawer, no subprocess, and the same answer it has always given.
    #
    # THE NO-DRAWER ARM IS POINTED AT, NOT ASSUMED. On a product that
    # uses `scripts/local/legs/` "this tree has no drawer" is false, and the
    # case compared the product's listing against the text. The drawer is
    # aimed at a path that does not exist — the `[ -d ]` arm a tree with no
    # drawer takes — and the memo is cleared so an earlier answer in this shell
    # cannot stand in for this one. On the template it is the same call.
    CURRENT="gate_full_legs reads this repository's own FULL_LEGS assignment"
    local declared shipped
    declared=$(cd "$ROOT" && GATE_FULL_LEGS_MEMO="" DJB_LOCAL_LEGS_DIR="${WORK}/no-leg-drawer-at-all" gate_full_legs)
    shipped=$(sed -n 's/^FULL_LEGS=//p' "$ROOT/scripts/check.sh")
    shipped=${shipped%%$'\n'*}
    is "$declared" "$shipped" "the declaration, against check.sh's own line"
    if [ -n "$declared" ]; then
        ok "and it is not empty on this tree, so the comparison is live here"
    else
        bad "check.sh declares no FULL_LEGS — the comparison is inert in the repository that owns it"
    fi

    CURRENT="and the verdict for THIS repository's own rows is unaffected by it"
    # THE WRITER AND THE READER ARE ONE FUNCTION, which is the property this
    # case has always held and the only way it can be held now that the set is
    # derived: `scripts/check.sh`'s one `gate_ledger_record` call passes
    # `$(gate_full_legs)` — the same answer `gate_ledger_lookup` compares
    # against — so the comparison can only ever refuse a row this gate did not
    # write.
    if grep -F 'gate_ledger_record "$MEASURED_START" "$(gate_full_legs)"' "$ROOT/scripts/check.sh" >/dev/null; then
        ok "the only recorder passes the same derivation the lookup compares against"
    else
        bad "the recorder no longer writes gate_full_legs — a row this gate writes could now fail its own comparison"
    fi
}

# --- the belt that consults the FULL ledger: the pre-push hook ----------------
#
# R3's F4, and it is the one case in this file about the FULL verdict ledger
# rather than the loop's. It lives here because the two ledgers are one file and
# one set of properties — `gate_has_green` is the consult both belts make — and
# because the alternative was a new drive, which is a `check.sh` registration
# and an instruments row for four cases about a thirty-line hook.
#
# THE DEFECT. `scripts/githooks/pre-push` ignored stdin and consulted the
# verdict for the local WORKING TREE, so from a green-banked `main`,
# `git push <remote> <unmeasured-red-branch>` printed "already measured green …
# verdict honoured" and pushed. `scripts/pm_push.sh` was safe by coincidence
# rather than by construction: its `pm-push` worktree is detached to the SHA it
# pushes, so the two trees happened to agree, and nothing bound them.
#
# THE WORLD IS BUILT, NEVER FOUND. Every case below runs in a throwaway repo
# with a scratch remote and its OWN verdict ledger (`gate_ledger_path` resolves
# through `--git-common-dir`, so the scratch repo's `.git` is the ledger), and
# the gate it would run is a STUB that prints a marker and exits 0 — the drive
# must be able to tell "it measured" from "it honoured a verdict" without
# spending eight minutes, and a real `./scripts/check.sh` inside a drive is
# refused by the per-checkout lock anyway.
#
# `does_not_cover`, declared with the fix (R3's F4x.4):
#
#   * FORCE PUSHES. `--force` changes what the push OVERWRITES, never what it
#     carries: the tree being pushed is the same tree either way, and this hook
#     vouches for what is carried. What a force push destroys on the remote is a
#     different question and no local verdict has ever spoken to it.
#   * MULTI-REF PUSHES ARE HANDLED, NOT DECLARED — every pushed tree must be
#     measured green or the hook does not honour — but the CASE below drives two
#     refs, not N, and the interaction with a partial push failure (some refs
#     accepted, some rejected by the remote) is after this hook's time and is
#     not covered.
#   * WHETHER THE VERDICT WAS HONEST. This is the ledger's standing trust class,
#     one belt over: a row is a local line an agent could write, and the hook
#     asks whether a row EXISTS for the tree being pushed, never whether the run
#     that wrote it was sound.
#   * THE REMOTE'S OWN STATE. A tree measured green here may be a merge that has
#     never existed anywhere; CI re-runs from a fresh checkout for that reason.

#: A throwaway repo with a scratch remote, a stub gate, the real hook and the
#: real ledger library. Sets PUSH_WORK (the pushing checkout), PUSH_REMOTE and
#: PUSH_MAIN_SHA.
#:
#: `PUSH_HOOK` overrides which hook is installed, and it exists for ONE use: a
#: red-first measurement against a hook read out of history —
#: `PUSH_HOOK=$(...shipped copy...) ./scripts/tests/test_loop_ledger.sh` runs the
#: whole section against the old bytes, where the canary below goes red and the
#: three negatives stay green. That is the shape a red-first claim is supposed
#: to have, and it is cheaper than a second script that would drift from this one.
PUSH_WORK=""
PUSH_REMOTE=""
PUSH_MAIN_SHA=""
push_world() {
    N=$((N + 1))
    local base="${WORK}/push${N}"
    PUSH_WORK="${base}/work"
    PUSH_REMOTE="${base}/origin.git"
    drive_require_scratch PUSH_WORK "${PUSH_WORK:-}"
    drive_require_scratch PUSH_REMOTE "${PUSH_REMOTE:-}"
    mkdir -p "$PUSH_WORK/scripts/githooks"
    git init -q --bare "$PUSH_REMOTE"
    git -C "$PUSH_WORK" init -q 2>/dev/null || git init -q "$PUSH_WORK"
    git -C "$PUSH_WORK" symbolic-ref HEAD refs/heads/main
    git -C "$PUSH_WORK" config user.email drive@example.invalid
    git -C "$PUSH_WORK" config user.name "pre-push drive"
    git -C "$PUSH_WORK" config core.hooksPath scripts/githooks
    git -C "$PUSH_WORK" remote add origin "$PUSH_REMOTE"
    cp "$ROOT/scripts/gate_ledger.sh" "$PUSH_WORK/scripts/gate_ledger.sh"
    cp "$ROOT/scripts/gate_refuse.sh" "$PUSH_WORK/scripts/gate_refuse.sh"
    cp "${PUSH_HOOK:-$ROOT/scripts/githooks/pre-push}" "$PUSH_WORK/scripts/githooks/pre-push"
    chmod +x "$PUSH_WORK/scripts/githooks/pre-push"
    # THE STUB GATE. It is the observable difference between "honoured" and
    # "measured", and it is why this drive can exist at all.
    printf '#!/usr/bin/env bash\necho "STUB GATE RAN"\nexit 0\n' \
        >"$PUSH_WORK/scripts/check.sh"
    chmod +x "$PUSH_WORK/scripts/check.sh"
    echo "the measured content" >"$PUSH_WORK/README.md"
    git -C "$PUSH_WORK" add -A >/dev/null
    git -C "$PUSH_WORK" commit -q -m "main, and this is the tree the gate measured"
    PUSH_MAIN_SHA=$(git -C "$PUSH_WORK" rev-parse HEAD)
    # BANK A GREEN VERDICT FOR MAIN'S TREE, through the real recorder in the
    # scratch repo, so the row is shaped exactly as a full gate writes one.
    (cd "$PUSH_WORK" && gate_ledger_record "$(git rev-parse "${PUSH_MAIN_SHA}^{tree}")" "drive-legs") ||
        cannot_look "gate_ledger_record would not write into the scratch repo's ledger"
    echo "  PLANT TOOK · scratch remote + a green verdict for main $(git -C "$PUSH_WORK" rev-parse --short HEAD)"
}

#: A branch whose tree NO verdict names. Returns with PUSH_RED_SHA set.
PUSH_RED_SHA=""
push_unmeasured_branch() {
    local name="${1:-red}"
    git -C "$PUSH_WORK" checkout -q -b "$name"
    printf 'a test that has never been run\n' >"$PUSH_WORK/RED.md"
    git -C "$PUSH_WORK" add RED.md >/dev/null
    git -C "$PUSH_WORK" commit -q -m "bytes no gate has measured"
    PUSH_RED_SHA=$(git -C "$PUSH_WORK" rev-parse HEAD)
    git -C "$PUSH_WORK" checkout -q main
}

case_a_push_of_a_ref_that_is_not_the_measured_tree_is_not_honoured() {
    # THE CANARY. On the shipped hook this case is RED in exactly the shape R3
    # reported: the working tree is green-banked `main`, the ref carries bytes
    # nothing measured, and the hook says "verdict honoured".
    push_world
    push_unmeasured_branch
    N=$((N + 1))
    OUT="${WORK}/prepush-red${N}.log"
    RC=0
    git -C "$PUSH_WORK" push origin "${PUSH_RED_SHA}:refs/heads/red" >"$OUT" 2>&1 || RC=$?

    CURRENT="a push whose ref is not the tree this checkout measured is refused"
    if grep -F "verdict honoured" "$OUT" >/dev/null; then
        bad "the hook honoured main's verdict for a ref main's verdict never measured"
    else
        ok "the hook did not hand the working tree's verdict to another ref"
    fi
    if grep -F "REFUSED — the ref being pushed is not the tree in this checkout" "$OUT" >/dev/null; then
        ok "the refusal names the mismatch"
    else
        bad "the hook neither refused nor named the mismatch"
    fi
    is "$RC" "1" "the push's exit status"
    CURRENT="and the unmeasured ref did not reach the remote"
    RC=0
    git -C "$PUSH_REMOTE" rev-parse -q --verify refs/heads/red >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the remote's lookup of the ref that was refused"
    OUT=""
}

case_pm_pushs_detached_sha_push_is_honoured_in_seconds() {
    # THE NEGATIVE, AND IT IS THE SHAPE THE RITUAL ACTUALLY USES.
    # `scripts/pm_push.sh` ends with `git -C "$PM_PUSH" push <remote>
    # <SHA>:refs/heads/<branch>` from a worktree DETACHED to that SHA. The hook
    # must honour the banked verdict there, and must not run a gate — which the
    # stub makes visible rather than inferable.
    push_world
    local wt="${WORK}/pmpush${N}"
    drive_require_scratch wt "${wt:-}"
    git -C "$PUSH_WORK" worktree add -q --detach "$wt" "$PUSH_MAIN_SHA" ||
        cannot_look "git worktree add refused in the scratch repo"
    N=$((N + 1))
    OUT="${WORK}/prepush-pm${N}.log"
    RC=0
    git -C "$wt" push origin "${PUSH_MAIN_SHA}:refs/heads/shipped" >"$OUT" 2>&1 || RC=$?

    CURRENT="pm_push's detached-SHA push honours the banked verdict"
    is "$RC" "0" "the push's exit status"
    if grep -F "verdict honoured" "$OUT" >/dev/null; then
        ok "the hook honoured the verdict for the tree being pushed"
    else
        bad "the ritual's own push no longer honours a banked verdict"
    fi
    if grep -F "STUB GATE RAN" "$OUT" >/dev/null; then
        bad "the hook ran a gate on a tree that already had a verdict"
    else
        ok "no gate ran — the consult is the whole cost"
    fi
    CURRENT="and the ref reached the remote"
    is "$(git -C "$PUSH_REMOTE" rev-parse refs/heads/shipped)" "$PUSH_MAIN_SHA" "the remote's tip"
    git -C "$PUSH_WORK" worktree remove --force "$wt" >/dev/null 2>&1 || true
    OUT=""
}

case_an_ordinary_push_of_the_measured_branch_is_honoured() {
    push_world
    N=$((N + 1))
    OUT="${WORK}/prepush-plain${N}.log"
    RC=0
    git -C "$PUSH_WORK" push origin main >"$OUT" 2>&1 || RC=$?
    CURRENT="pushing the branch this checkout IS still honours the verdict"
    is "$RC" "0" "the push's exit status"
    if grep -F "verdict honoured" "$OUT" >/dev/null; then
        ok "the everyday push is unchanged and still costs a lookup"
    else
        bad "the everyday push stopped honouring its own verdict: $(sed -n '1,3p' "$OUT")"
    fi
    OUT=""
}

case_a_multi_ref_push_is_vouched_for_only_when_every_tree_is_measured() {
    # ONE GREEN AMONG SEVERAL IS ONE GREEN AMONG SEVERAL. The mixed push carries
    # a measured ref and an unmeasured one; the hook may not let the pair
    # through on the strength of the first.
    push_world
    push_unmeasured_branch
    N=$((N + 1))
    OUT="${WORK}/prepush-multi${N}.log"
    RC=0
    git -C "$PUSH_WORK" push origin \
        "${PUSH_MAIN_SHA}:refs/heads/one" "${PUSH_RED_SHA}:refs/heads/two" >"$OUT" 2>&1 || RC=$?
    CURRENT="a push carrying one measured and one unmeasured tree is not honoured"
    is "$RC" "1" "the push's exit status"
    if grep -F "verdict honoured" "$OUT" >/dev/null; then
        bad "the hook honoured a mixed push on the strength of the measured half"
    else
        ok "the measured half did not vouch for the unmeasured one"
    fi
    CURRENT="and neither ref reached the remote"
    RC=0
    git -C "$PUSH_REMOTE" rev-parse -q --verify refs/heads/one >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the remote's lookup of the measured half"
    OUT=""
}

case_a_deletion_carries_no_tree_and_falls_back_to_the_working_tree() {
    # A DELETE IS AN ALL-ZERO LOCAL SHA: nothing is being pushed, so there is no
    # tree to vouch for, and the hook says which subject it fell back to rather
    # than implying the stronger claim.
    push_world
    # NOT `main`: a bare repository's HEAD points at it, and `receive.denyDeleteCurrent`
    # refuses the deletion at the REMOTE — which is the remote's own policy and
    # not this hook's answer. Measured while writing this case; the first draft
    # read git's refusal as the hook's.
    git -C "$PUSH_WORK" push -q origin "main:refs/heads/scratch" >/dev/null 2>&1 ||
        cannot_look "the scratch remote would not take the first push"
    N=$((N + 1))
    OUT="${WORK}/prepush-delete${N}.log"
    RC=0
    git -C "$PUSH_WORK" push origin :refs/heads/scratch >"$OUT" 2>&1 || RC=$?
    CURRENT="a deletion-only push names the working tree as its subject"
    is "$RC" "0" "the push's exit status"
    if grep -F "no refs on stdin — consulting the verdict for the WORKING tree" "$OUT" >/dev/null; then
        ok "the hook says which subject it consulted"
    else
        bad "a deletion-only push did not name its subject: $(sed -n '1,3p' "$OUT")"
    fi
    OUT=""
}

# --- A DECLARING PRODUCT AT THE WALL -----------------------------------------
#
# THE DEFECT, IN ONE SENTENCE. The hook resolves each pushed ref to its RAW
# commit tree and compares that against `$TREE`, which is `gate_measured_tree`
# — the checkout's tree with every DECLARED derived path SUBTRACTED. On this
# template nothing is declared, so the two readings are the same forty
# characters and the disagreement was invisible. On a product that declares one
# (the consumer's visual-baseline evidence directory under its frontend) they can NEVER
# agree, so EVERY push — to a forge, to a verifier box, of the checkout's own
# `main` — takes the two-tree refusal that exists for pushing somebody ELSE's
# tree. The product's own tree is mistaken for a foreign one, by arithmetic,
# forever.
#
# THE FIX IS ONE READER AND NOT TWO KEYS. `gate_measured_tree_of <tree-ish>`
# answers the same subtraction over a ref instead of the working tree, and it
# shares the ONE subtraction site with `gate_measured_tree` — a copied helper
# would be two keys computed two ways, which is the defect again with a longer
# fuse. The cases below are the three roads a declaring checkout walks.

#: The box wrapper's own throwaway probe, in the shape the hook demands:
#: `<absolute>/.vouch-<digits>/probe.git`. The declaration alone opens nothing
#: — that is what keeps the exemption from ever reaching `origin` — so a case
#: that pushed anywhere else would be measuring the variable and not the wall.
PUSH_PROBE=""
push_probe() {
    local home="${WORK}/.vouch-$$"
    PUSH_PROBE="${home}/probe.git"
    drive_require_scratch PUSH_PROBE "${PUSH_PROBE:-}"
    rm -rf "$home"
    mkdir -p "$home"
    git init -q --bare "$PUSH_PROBE"
}

#: `push_world`, plus a leg that DECLARES a derived path and the tracked,
#: committed artefact it names — the consumer's shape, planted. Sets
#: PUSH_RAW_TREE and PUSH_MEASURED_TREE, and REFUSES if they agree: a world
#: where the two readings happen to match would let every case here pass while
#: proving nothing at all, which is the one outcome a plant must never have.
PUSH_RAW_TREE=""
PUSH_MEASURED_TREE=""
push_world_that_declares_a_derived_path() {
    push_world
    plant_derived_leg "$PUSH_WORK" \
        "derived — the box redraws these bytes on every green run; nothing measured reads them back"
    plant_derived_member "$PUSH_WORK" ||
        cannot_look "the derived artefact would not commit in the scratch checkout"
    PUSH_MAIN_SHA=$(git -C "$PUSH_WORK" rev-parse HEAD)
    PUSH_RAW_TREE=$(git -C "$PUSH_WORK" rev-parse "${PUSH_MAIN_SHA}^{tree}")
    PUSH_MEASURED_TREE=$(in_repo "$PUSH_WORK" gate_measured_tree 2>/dev/null) || PUSH_MEASURED_TREE=""
    [ -n "$PUSH_MEASURED_TREE" ] ||
        cannot_look "gate_measured_tree would not answer in the declaring scratch checkout"
    [ "$PUSH_RAW_TREE" != "$PUSH_MEASURED_TREE" ] ||
        cannot_look "the planted declaration did not move the key — raw and measured both read ${PUSH_RAW_TREE}"
    echo "  PLANT TOOK · a DECLARING checkout: raw ${PUSH_RAW_TREE} vs measured ${PUSH_MEASURED_TREE}"
}

case_one_subtraction_site_serves_both_measured_tree_readers() {
    CURRENT="a ref can be read in the same measured form as the working tree"
    if command -v gate_measured_tree_of >/dev/null 2>&1; then
        ok "scripts/gate_ledger.sh defines gate_measured_tree_of"
    else
        bad "there is no gate_measured_tree_of — a ref can only be read RAW, which is the defect"
        return
    fi
    # ONE SITE, AND THE COUNT IS THE ASSERTION. `git rm -r -f --cached` is the
    # subtraction; a second occurrence is a copied helper, and two copies of a
    # key's definition is two keys the day one of them is edited.
    is "$(grep -c 'rm -r -f --cached' "$ROOT/scripts/gate_ledger.sh")" "1" \
        "the number of subtraction sites in the library"

    push_world_that_declares_a_derived_path
    CURRENT="and the two readers agree wherever they are asked the same question"
    # `gate_measured_tree` reads the WORKING tree; `gate_measured_tree_of HEAD`
    # reads the COMMITTED one. On a clean checkout they are the same forty
    # characters — declared paths or not — and that equality is what every
    # caller below rests on.
    is "$(in_repo "$PUSH_WORK" gate_measured_tree_of HEAD 2>/dev/null)" "$PUSH_MEASURED_TREE" \
        "gate_measured_tree_of HEAD on a clean DECLARING checkout"
    differs "$PUSH_RAW_TREE" "$PUSH_MEASURED_TREE" \
        "the raw tree and the measured tree are different readings of one commit"
    CURRENT="a ref this repository cannot read is a refusal, never an empty answer"
    RC=0
    in_repo "$PUSH_WORK" gate_measured_tree_of \
        "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef^{tree}" >/dev/null 2>&1 || RC=$?
    is "$RC" "1" "the reader's exit status for a ref it cannot resolve"
}

case_a_box_push_of_a_tree_that_declares_a_derived_path_is_exempt() {
    # ABSENT (the shipped hook): `wall refused`, rc 1 — the checkout's own tree,
    # read raw, is not the checkout's measured tree, so the two-tree refusal
    # fires on the one population it was written to let through.
    push_world_that_declares_a_derived_path
    push_probe
    N=$((N + 1))
    OUT="${WORK}/prepush-boxdecl${N}.log"
    RC=0
    DJB_PUSH_DESTINATION=verifier-box \
        git -C "$PUSH_WORK" push --dry-run --force "$PUSH_PROBE" HEAD:refs/heads/main \
        >"$OUT" 2>&1 || RC=$?

    CURRENT="a DECLARING checkout's own tree reaches a verifier box"
    is "$RC" "0" "the vouch's exit status"
    if grep -F "pre-push: wall box-exempt ${PUSH_MEASURED_TREE}" "$OUT" >/dev/null; then
        ok "the sentinel is box-exempt and names the MEASURED tree"
    else
        bad "the wall did not reach box-exempt for the measured tree ${PUSH_MEASURED_TREE}"
    fi
    if grep -F "REFUSED — the ref being pushed is not the tree in this checkout" "$OUT" >/dev/null; then
        bad "the hook refused this checkout's OWN tree as foreign — the raw/measured mismatch"
    else
        ok "the checkout's own tree is not mistaken for somebody else's"
    fi
    if grep -F "STUB GATE RAN" "$OUT" >/dev/null; then
        bad "the Mac's full gate ran for a tree that was only going to a verifier box"
    else
        ok "no gate ran here — the box's own run is the measurement"
    fi
    OUT=""
}

case_a_banked_measured_verdict_honours_a_push_from_a_declaring_checkout() {
    # ABSENT: the consult is keyed on the RAW tree, which no full gate ever
    # banks, so the lookup misses and the raw/measured compare then refuses —
    # a green bank on a declaring product is a row nobody can ever hit.
    push_world_that_declares_a_derived_path
    in_repo "$PUSH_WORK" gate_ledger_record "$PUSH_MEASURED_TREE" "drive-legs" ||
        cannot_look "gate_ledger_record would not write into the scratch repo's ledger"
    N=$((N + 1))
    OUT="${WORK}/prepush-decl-honoured${N}.log"
    RC=0
    git -C "$PUSH_WORK" push origin main >"$OUT" 2>&1 || RC=$?

    CURRENT="a DECLARING checkout's banked verdict is honoured on an ordinary push"
    is "$RC" "0" "the push's exit status"
    if grep -F "pre-push: wall honoured" "$OUT" >/dev/null; then
        ok "the wall honoured the row banked for the measured tree"
    else
        bad "the wall did not honour the row banked for ${PUSH_MEASURED_TREE}"
    fi
    if grep -F "this checkout measures:" "$OUT" >/dev/null; then
        bad "the two-tree refusal fired on the checkout's own tree"
    else
        ok "no two-tree refusal — the pushed tree and the verdict key are one reading"
    fi
    if grep -F "STUB GATE RAN" "$OUT" >/dev/null; then
        bad "the hook measured a tree that already carried a green verdict"
    else
        ok "no gate ran — the consult is the whole cost"
    fi
    CURRENT="and the ref reached the remote"
    is "$(git -C "$PUSH_REMOTE" rev-parse refs/heads/main)" "$PUSH_MAIN_SHA" "the remote's tip"
    OUT=""
}

#: `push_world`, then a stub gate that DECLARES a leg set — committed, so the
#: tree moves and the cover rule has something to compare against. `push_world`
#: alone ships a gate with no `FULL_LEGS=` line, which is a checkout that
#: declares no leg set and therefore compares nothing (the case two sections
#: up); the wall cases need the comparison to be live. Sets WALL_TREE and
#: re-points PUSH_MAIN_SHA at the new commit.
WALL_TREE=""
wall_world_with_a_declared_leg_set() {
    push_world
    printf '#!/usr/bin/env bash\nFULL_LEGS=ruff,pytest-x2\necho "STUB GATE RAN"\nexit 0\n' \
        >"$PUSH_WORK/scripts/check.sh"
    chmod +x "$PUSH_WORK/scripts/check.sh"
    git -C "$PUSH_WORK" add scripts/check.sh >/dev/null
    git -C "$PUSH_WORK" commit -q -m "a stub gate that declares the leg set it would run"
    PUSH_MAIN_SHA=$(git -C "$PUSH_WORK" rev-parse HEAD)
    WALL_TREE=$(git -C "$PUSH_WORK" rev-parse "${PUSH_MAIN_SHA}^{tree}")
    echo "  PLANT TOOK · a gate declaring 'ruff,pytest-x2', and a tree no row names yet"
}

#: One push of the declared-leg-set world's `main` at a fresh remote ref, so
#: every plant meets the hook (a second push of the same ref is "up to date"
#: and the hook never runs). Leaves the transcript in OUT.
wall_push() {
    N=$((N + 1))
    OUT="${WORK}/prepush-wall${N}.log"
    RC=0
    git -C "$PUSH_WORK" push origin "main:refs/heads/wall${N}" >"$OUT" 2>&1 || RC=$?
}

case_the_wall_refuses_a_one_pass_row_without_its_proof() {
    # THE READER'S RULE THROUGH THE REAL HOOK. `scripts/githooks/
    # pre-push` needs NO edit for any of this: it consults `gate_has_green`,
    # and the refusal is `gate_ledger_lookup`'s. That is the claim this case
    # exists to hold — if the hook ever has to learn about passes or proofs,
    # this case is where it will be noticed.
    #
    # The observable difference between "honoured" and "measured" is the STUB
    # GATE, exactly as in the four cases above: a wall that honoured spends a
    # lookup, a wall that measured runs a gate.

    CURRENT="(i) a one-pass row WITH a green proof is honoured at the wall, in seconds"
    wall_world_with_a_declared_leg_set
    plant_full_row "$PUSH_WORK" "$WALL_TREE" "ruff,pytest-x2/1" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=0"
    wall_push
    is "$RC" "0" "the push's exit status"
    if grep -F "pre-push: wall honoured" "$OUT" >/dev/null; then
        ok "the wall honoured a row that ran one pass and proved it"
    else
        bad "the wall did not honour a one-pass row carrying a green leak proof"
    fi
    if grep -F "STUB GATE RAN" "$OUT" >/dev/null; then
        bad "the hook ran a gate on a tree whose row was honourable"
    else
        ok "no gate ran — the consult is the whole cost"
    fi
    OUT=""

    CURRENT="(ii) the same row with a RED proof measures, and the note says why"
    wall_world_with_a_declared_leg_set
    plant_full_row "$PUSH_WORK" "$WALL_TREE" "ruff,pytest-x2/1" \
        " waited=0 took=131 leak-proof=acceptance:i-0f1e2d3c rc=1"
    wall_push
    if grep -F "pre-push: wall measuring" "$OUT" >/dev/null; then
        ok "the wall measured rather than honouring a one-pass row with a red proof"
    else
        bad "the wall did not measure a row whose leak proof was red"
    fi
    if grep -F "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof (leak-proof=acceptance:i-0f1e2d3c rc=1)" "$OUT" >/dev/null; then
        ok "the lookup's note reached the hook's stderr, naming the proof"
    else
        bad "the hook refused the row without the note that says which proof it read"
    fi
    if grep -F "STUB GATE RAN" "$OUT" >/dev/null; then
        ok "the gate ran once — the wall fell back to measuring"
    else
        bad "the wall neither honoured nor measured"
    fi
    OUT=""

    CURRENT="(iii) a one-pass row with NO proof measures, and the note says it is absent"
    wall_world_with_a_declared_leg_set
    plant_full_row "$PUSH_WORK" "$WALL_TREE" "ruff,pytest-x2/1"
    wall_push
    if grep -F "pre-push: wall measuring" "$OUT" >/dev/null; then
        ok "a one-pass row with nothing standing behind it is not a verdict"
    else
        bad "the wall honoured a one-pass row carrying no proof at all"
    fi
    if grep -F "missing 'pytest-x2' — the row ran ONE pass and carries no green leak proof (leak-proof=none)" "$OUT" >/dev/null; then
        ok "the note reached the hook and said the field is absent"
    else
        bad "the hook's stderr does not carry the absent-proof note"
    fi
    if grep -F "STUB GATE RAN" "$OUT" >/dev/null; then
        ok "the gate ran once"
    else
        bad "the wall neither honoured nor measured"
    fi
    OUT=""

    CURRENT="(iv) today's two-pass row is honoured at the wall exactly as it was"
    wall_world_with_a_declared_leg_set
    plant_full_row "$PUSH_WORK" "$WALL_TREE" "ruff,pytest-x2"
    wall_push
    is "$RC" "0" "the push's exit status"
    if grep -F "pre-push: wall honoured" "$OUT" >/dev/null; then
        ok "the negative holds — nothing about a row without the field moved"
    else
        bad "a row shaped exactly as every row banked before this field existed stopped being honoured"
    fi
    OUT=""

    CURRENT="and the hook itself learned nothing about passes or proofs"
    # THE PATTERN IS THE TWO SPELLINGS AND NOT THE ENGLISH WORD. The hook's own
    # first line says a measured green "passes in ~2s"; a bare `passes` here
    # reds on prose that predates the leak-proof field by months, which is a case failing for
    # the wrong reason. What must not appear is the FIELD and the SEAM.
    #
    # AND A GREP THAT COULD NOT LOOK IS NOT A GREP THAT FOUND NOTHING. An
    # absent or unreadable hook makes `grep` exit 1 exactly as a clean one
    # does, so the assertion below would print `ok` about a file it never
    # opened — the silent-pass shape this whole drive is written against.
    local hook="$ROOT/scripts/githooks/pre-push"
    [ -r "$hook" ] ||
        cannot_look "scripts/githooks/pre-push is not readable — the wall's own bytes cannot be asserted"
    if grep -E 'leak-proof|--passes|pytest-x2' "$hook" >/dev/null; then
        bad "scripts/githooks/pre-push now spells the proof — the refusal was supposed to stay the lookup's"
    else
        ok "the hook still only asks gate_has_green; the rule lives in one reader"
    fi
}

# --- the machine's own spelling of SHA-256 -----------------------------------
#
# A PATH WITH NO `shasum` ON IT, BUILT RATHER THAN IMAGINED. `shasum -a 256` is
# a Perl script macOS ships and a minimal Linux does not; that Linux spells the
# same digest `sha256sum`. Every digest in this family was written on a Mac, and
# the first off-box gate run printed `shasum: command not found` at
# `scripts/loop_tier.sh`, censused zero installed distributions, derived no key
# and banked nothing — a verdict cache that could not key itself on a machine
# where nothing was wrong except the name of a program.
#
# THE SHIM IS A DIRECTORY OF SYMLINKS AND IT IS THE WHOLE PATH, not a prefix:
# `command -v shasum` has to FAIL, and a prefix cannot hide what is behind it.
# So the names these functions actually use are linked in one by one and
# `shasum` is the one that is not. A tool this list forgot is a case that fails
# for the wrong reason, which is why the shim asserts its own contents before a
# single assertion is made.
digest_shim_path() {
    local dir="$1" name found d
    mkdir -p "$dir"
    # THE SEARCH IS OVER FIXED DIRECTORIES, not over `command -v`: this drive
    # is bash and the interactive shell that debugs it may not be, and zsh
    # answers `command -v find` with the word `find` where it carries a
    # function of that name — which links a shim to itself.
    for name in awk sed sort find tr cat cut head git env mktemp rm stat comm \
        grep basename dirname date uname xargs wc printf ls sh bash perl \
        sha256sum; do
        found=""
        for d in /usr/bin /bin /usr/sbin /sbin /opt/homebrew/bin /usr/local/bin; do
            if [ -x "$d/$name" ]; then
                found="$d/$name"
                break
            fi
        done
        [ -n "$found" ] || continue
        ln -sf "$found" "$dir/$name"
    done
    [ -x "$dir/sha256sum" ] ||
        cannot_look "this machine has no 'sha256sum' anywhere on the standard paths, so the
   branch a Linux box takes cannot be driven here at all"
    for name in awk sed sort find git grep; do
        [ -x "$dir/$name" ] ||
            cannot_look "the digest shim could not link '$name' — the case would fail for that
   and be read as the digest's failure"
    done
    [ ! -e "$dir/shasum" ] || cannot_look "the digest shim linked 'shasum', which is the one name it exists to withhold"
    printf '%s\n' "$dir"
}

case_the_ledgers_digest_is_the_same_where_only_sha256sum_exists() {
    fresh_checkout
    local shim normal shadowed nf sf
    shim="$(digest_shim_path "${WORK}/shim${N}")" || return 0

    CURRENT="the loop ledger's digest on a machine with no shasum"

    # THE PRECONDITION, ASSERTED AND NOT ASSUMED: under the shim `shasum` is
    # gone and `sha256sum` answers, which is Amazon Linux 2023's shape.
    if in_repo "$REPO" env PATH="$shim" bash -c 'command -v shasum >/dev/null 2>&1'; then
        bad "the shim PATH still resolves shasum — nothing below is about the fallback"
        return 0
    fi
    ok "the shim PATH resolves no shasum and does resolve sha256sum"

    # THE FINGERPRINT — the value the box could not derive at all.
    normal="$(in_repo "$REPO" loop_env_fingerprint 2>/dev/null || true)"
    shadowed="$(in_repo "$REPO" env PATH="$shim" bash -c '. '"$ROOT"'/scripts/gate_ledger.sh && loop_env_fingerprint' 2>/dev/null || true)"
    case "$normal" in
    [0-9a-f]*) ok "the fingerprint derives with shasum present (${normal:0:12}…)" ;;
    *) bad "the fingerprint did not derive with the ordinary PATH: '${normal}'" ;;
    esac
    is "$shadowed" "$normal" "the fingerprint with shasum shadowed off PATH is the SAME key"

    # AND THE HELPER ITSELF, both branches, against this drive's own reference
    # digest rather than against the library's.
    printf 'one line of it\n' >"${WORK}/digest-subject${N}"
    nf="$(in_repo "$REPO" sha256_of "${WORK}/digest-subject${N}" || true)"
    sf="$(in_repo "$REPO" env PATH="$shim" bash -c '. '"$ROOT"'/scripts/gate_refuse.sh && sha256_of "$1"' _ "${WORK}/digest-subject${N}" || true)"
    is "$nf" "$(hex64 'one line of it
')" "sha256_of over a file is the digest of its bytes"
    is "$sf" "$nf" "sha256_of over the same file with only sha256sum present"

    # NEITHER TOOL IS COULD-NOT-LOOK, never an empty answer wearing a digest's
    # name: an empty component in a key is a key that vouches for nothing.
    local empty_dir="${WORK}/no-digest-tool${N}" out rc=0
    mkdir -p "$empty_dir"
    ln -sf "$shim/bash" "$empty_dir/bash" 2>/dev/null || true
    out="$(in_repo "$REPO" env PATH="$empty_dir" bash -c '. '"$ROOT"'/scripts/gate_refuse.sh && sha256_of "$1"' _ "${WORK}/digest-subject${N}" 2>/dev/null)" || rc=$?
    is "$rc" "1" "sha256_of with NEITHER tool on PATH exits 1"
    is "$out" "" "and prints nothing that could be mistaken for a digest"
}

case_no_site_in_this_family_spells_a_digest_tool_by_hand() {
    CURRENT="every digest in the gate family goes through the one helper"
    local f offenders=""
    for f in scripts/gate_ledger.sh scripts/loop_tier.sh scripts/publish.sh \
        scripts/check.sh scripts/docs_legs.sh scripts/archaeology_lib.sh \
        scripts/secrets_scan.sh; do
        [ -f "$ROOT/$f" ] || continue
        # COMMENTS AND QUOTED RUNS STRIPPED, because these files both argue
        # about the tools by name and NAME them in a refusal's remedy text —
        # and neither is a call. What survives the two `sed`s is unquoted
        # command text, which is the only place a digest can actually run.
        # DECLARED BLIND SPOT, taken where it is paid: a call hidden inside a
        # quoted string (`bash -c "… | sha256sum"`) is stripped with the
        # remedy text and would not be seen here.
        if sed -e 's/#.*//' -e "s/'[^']*'//g" -e 's/"[^"]*"//g' "$ROOT/$f" |
            grep -nE 'shasum|sha256sum' >/dev/null; then
            offenders="${offenders} ${f}"
        fi
    done
    if [ -z "$offenders" ]; then
        ok "no bare shasum/sha256sum call in the seven files that reach sha256_of"
    else
        bad "these still spell a digest tool by hand:${offenders} — a Mac-only spelling is what the box met"
    fi
    # AND THE HELPER IS WHERE BOTH LIBRARIES CAN SEE IT. gate_refuse.sh is the
    # one file gate_ledger.sh and loop_tier.sh both source, which is the whole
    # reason it is the home.
    if grep -qE '^sha256_of\(\)' "$ROOT/scripts/gate_refuse.sh"; then
        ok "sha256_of is defined in scripts/gate_refuse.sh, the seam both libraries source"
    else
        bad "scripts/gate_refuse.sh no longer defines sha256_of — the two libraries have no shared home for it"
    fi
}

# --- the environment the LEGS run in, held still ahead of the key ------------
#
# THE DEFECT, measured on three verifier boxes on 2026-09-18 and driven here.
# The fingerprint censuses the installed distributions under `.venv`, because a
# dependency change moves the suite without moving a tracked file. The gate's
# own first `uv run` SYNCS that venv: on a machine whose image predates a
# package joining `uv.lock`, the first leg installed it, the census moved
# between the start key and the end key, and a completely green `--loop` refused
# to bank — with `git status` clean beside it, three times, on three trees.
#
# The three cases below are the cause, the fix and the wiring, in that order.

case_a_package_installed_while_the_gate_runs_moves_the_env_half_of_the_key() {
    fresh_checkout
    OUT=""
    local start end parts0 parts1 here
    # PLAINLY, NOT THROUGH `in_repo`, and that is this drive's own subshell
    # lesson one case up: `in_repo` is `( cd … && "$@" )`, so the COMPONENTS
    # global the printer needs would die with the subshell and both ends would
    # read identical — a case that could not fail.
    here="$PWD"
    cd "$REPO" || cannot_look "could not enter the scratch checkout"
    LOOP_ENV_FINGERPRINT=""
    LOOP_ENV_COMPONENTS=""
    loop_env_fingerprint >/dev/null 2>&1 || true
    start="$LOOP_ENV_FINGERPRINT"
    parts0="$LOOP_ENV_COMPONENTS"
    # THE PLANT IS THE CAUSE ITSELF: a distribution that was not installed when
    # the run began and is installed when it ends. It is made here rather than
    # found, exactly as every destructive demonstration in this tree is.
    mkdir -p "$REPO/.venv/lib/python3.12/site-packages/planted_plugin-1.2.3.dist-info"
    loop_env_fingerprint >/dev/null 2>&1 || true
    end="$LOOP_ENV_FINGERPRINT"
    parts1="$LOOP_ENV_COMPONENTS"
    cd "$here" || cannot_look "could not return to the checkout under test"
    CURRENT="a package installed mid-run moves the environment half of the key"
    differs "$start" "$end" "the start and the end fingerprints"

    CURRENT="and the end-of-run refusal NAMES which component moved"
    if ! command -v loop_key_moved >/dev/null 2>&1; then
        bad "gate_ledger.sh defines no loop_key_moved — the refusal can only say that something moved, which is a whole re-run with no subject"
        return 0
    fi
    N=$((N + 1))
    OUT="${WORK}/moved${N}.log"
    loop_key_moved "atree" "$start" "$parts0" "atree" "$end" "$parts1" "mode=fast" >"$OUT" 2>&1
    if grep -qF "THE ENVIRONMENT" "$OUT"; then
        ok "it names the environment half"
    else
        bad "it does not name the environment half"
    fi
    if grep -qE '^ +dists: ' "$OUT"; then
        ok "and it names the distribution census as the component that moved"
    else
        bad "it does not name the dists= component"
    fi
    if grep -qF "THE TREE" "$OUT"; then
        bad "it blames the tree, which did not move in this case"
    else
        ok "and it does not blame the tree, which did not move"
    fi
}

case_the_sync_installs_ahead_of_the_key_so_the_two_ends_agree() {
    fresh_checkout
    OUT=""
    CURRENT="the loop leg syncs the environment before it derives the key"
    if ! command -v loop_env_sync >/dev/null 2>&1; then
        bad "gate_ledger.sh defines no loop_env_sync — nothing brings the venv to the lockfile before the key is derived, so the first leg's install still moves it"
        return 0
    fi
    # A FAKE `uv` THAT INSTALLS, because what is under test is the ORDER and not
    # uv. A real `uv sync --frozen` in a scratch checkout would be a resolve
    # against the network to prove a sequencing property, which is the wrong
    # instrument at any price.
    local bin saved
    bin="${WORK}/bin${N}"
    mkdir -p "$bin"
    {
        echo "#!/bin/sh"
        echo "[ \"\$1\" = sync ] || { echo \"the sync must be \\\`uv sync\\\`, got: \$*\" >&2; exit 64; }"
        echo "case \" \$* \" in *\" --frozen \"*) ;; *) echo 'the sync must be --frozen: a bare uv sync may rewrite uv.lock, a TRACKED file' >&2; exit 65 ;; esac"
        echo "mkdir -p '${REPO}/.venv/lib/python3.12/site-packages/planted_plugin-1.2.3.dist-info'"
        echo "echo 'Installed 1 package in 30ms'"
    } >"$bin/uv"
    chmod +x "$bin/uv"
    N=$((N + 1))
    OUT="${WORK}/sync${N}.log"
    saved="$PATH"
    PATH="${bin}:${PATH}"
    RC=0
    # `|| RC=$?` AND NEVER `cmd; RC=$?`: `set -e` is on in this drive and a
    # non-zero status kills the shell before the assignment ever runs.
    in_repo "$REPO" loop_env_sync >"$OUT" 2>&1 || RC=$?
    local start end
    start=$(in_repo "$REPO" loop_env_fingerprint)
    # THE FIRST LEG NOW INSTALLS NOTHING, because the sync above already did.
    in_repo "$REPO" uv sync --frozen >/dev/null 2>&1 || true
    end=$(in_repo "$REPO" loop_env_fingerprint)
    PATH="$saved"
    is "$RC" "0" "the sync's exit status"
    same "$start" "$end" "the fingerprint either side of the leg's own sync"
    if grep -qF "Installed 1 package" "$OUT"; then
        ok "it prints uv's own summary of what it installed"
    else
        bad "it does not say what uv did — a run that banks nothing cannot be read backwards"
    fi
    if grep -qE 'uv sync --frozen, [0-9]+s' "$OUT"; then
        ok "and it says what the sync cost in seconds"
    else
        bad "it does not count the seconds the sync took"
    fi

    # THE NO-OP ANSWER IS UV'S TOO, AND ITS WORDING IS NOT OURS TO PREDICT —
    # this tool has renamed that line at least once (`Audited` → `Checked`).
    # A banner that only knows today's words would read as broken on the day
    # it changes, so the LAST line is the fallback and the case drives it with
    # a word this function has never heard of.
    CURRENT="a summary word the banner does not know is still reported, not swallowed"
    {
        echo "#!/bin/sh"
        echo "echo 'Contemplated 156 packages in 1ms'"
    } >"$bin/uv"
    chmod +x "$bin/uv"
    N=$((N + 1))
    OUT="${WORK}/sync${N}.log"
    PATH="${bin}:${PATH}"
    in_repo "$REPO" loop_env_sync >"$OUT" 2>&1 || true
    PATH="$saved"
    if grep -qF "Contemplated 156 packages" "$OUT"; then
        ok "uv's own last line reaches the banner"
    else
        bad "the banner dropped uv's answer because it did not recognise the word"
    fi

    # THE ONE CASE WHERE THIS STEP TAKES SOMETHING AWAY FROM A PERSON. A sync
    # makes the venv MATCH the lockfile, so a hand-patched environment — a
    # debugger, a pinned fork, a wheel built by hand — is reverted by a step
    # designed to be invisible. It owes that reader a sentence AND the way out.
    CURRENT="an UNINSTALL says so and names the valve that would have kept it"
    {
        echo "#!/bin/sh"
        echo "echo 'Uninstalled 1 package in 12ms'"
        echo "echo 'Installed 1 package in 30ms'"
    } >"$bin/uv"
    chmod +x "$bin/uv"
    N=$((N + 1))
    OUT="${WORK}/sync${N}.log"
    PATH="${bin}:${PATH}"
    in_repo "$REPO" loop_env_sync >"$OUT" 2>&1 || true
    PATH="$saved"
    if grep -qF "UNINSTALLED" "$OUT"; then
        ok "the reverted environment is announced rather than quietly restored"
    else
        bad "a hand-patched venv was reverted in silence"
    fi
    if grep -qF "DJB_LOOP_NO_SYNC=1" "$OUT"; then
        ok "and the line names the valve — a warning with no way out is an apology"
    else
        bad "the line does not name DJB_LOOP_NO_SYNC"
    fi
    CURRENT="and an ordinary sync does NOT print that sentence"
    if grep -qF "UNINSTALLED" "${WORK}/sync$((N - 2)).log"; then
        bad "the uninstall sentence prints on a sync that removed nothing"
    else
        ok "it prints only where something was removed"
    fi
}

case_a_sync_that_cannot_run_is_printed_and_never_a_refusal() {
    fresh_checkout
    OUT=""
    CURRENT="the sync never turns a leg's red into a ledger's exit 2"
    if ! command -v loop_env_sync >/dev/null 2>&1; then
        bad "gate_ledger.sh defines no loop_env_sync"
        return 0
    fi
    N=$((N + 1))
    OUT="${WORK}/nosync${N}.log"
    RC=0
    DJB_LOOP_NO_SYNC=1 in_repo "$REPO" loop_env_sync >"$OUT" 2>&1 || RC=$?
    is "$RC" "0" "the exit status with the skip set"
    if grep -qF "NOT synced" "$OUT"; then
        ok "the skip says it skipped"
    else
        bad "the skip is silent — a run that banks nothing then names no reason"
    fi
    # NO `uv` AT ALL: an empty PATH is the checkout that has never been set up,
    # and the legs below it are about to say so in their own words.
    local saved emptybin
    emptybin="${WORK}/empty-bin"
    # MADE BEFORE THE PATH IS CLOBBERED, because afterwards there is no `mkdir`
    # to make it with — which killed this drive once and left its exit trap
    # running without `sort` or `awk`.
    mkdir -p "$emptybin"
    N=$((N + 1))
    OUT="${WORK}/nouv${N}.log"
    RC=0
    saved="$PATH"
    PATH="$emptybin"
    in_repo "$REPO" loop_env_sync >"$OUT" 2>&1 || RC=$?
    PATH="$saved"
    is "$RC" "0" "the exit status with no uv on PATH"
    if grep -qF "no \`uv\` on PATH" "$OUT"; then
        ok "it names the absence rather than refusing"
    else
        bad "it does not name the missing uv"
    fi
}

case_a_sync_that_exits_non_zero_is_the_legs_business_and_the_refusal_still_names_dists() {
    fresh_checkout
    OUT=""
    CURRENT="a sync that failed does not become the gate's verdict"
    if ! command -v loop_env_sync >/dev/null 2>&1; then
        bad "gate_ledger.sh defines no loop_env_sync"
        return 0
    fi
    # A PARTIAL INSTALL THAT THEN FAILS — the one shape where this function
    # leaves the environment neither where it found it nor where the lockfile
    # says it should be. It is the branch that must NOT refuse (the legs below
    # are about to fail in their own words, with their own status) and it is
    # also the branch where the key can still move, so the END-OF-RUN refusal
    # has to stay able to say which component did it.
    local bin saved
    bin="${WORK}/binfail${N}"
    mkdir -p "$bin"
    {
        echo "#!/bin/sh"
        echo "mkdir -p '${REPO}/.venv/lib/python3.12/site-packages/half_landed-0.1.dist-info'"
        echo "echo 'Prepared 2 packages in 500ms'"
        echo "echo 'error: failed to install the second package' >&2"
        echo "exit 2"
    } >"$bin/uv"
    chmod +x "$bin/uv"
    N=$((N + 1))
    OUT="${WORK}/syncfail${N}.log"
    RC=0
    saved="$PATH"
    PATH="${bin}:${PATH}"
    in_repo "$REPO" loop_env_sync >"$OUT" 2>&1 || RC=$?
    PATH="$saved"
    is "$RC" "0" "the failed sync's own exit status"
    if grep -qF "exited 2" "$OUT"; then
        ok "it says uv failed and with what status"
    else
        bad "it does not name uv's exit status"
    fi
    if grep -qF "failed to install the second package" "$OUT"; then
        ok "and it prints uv's own output rather than summarising it"
    else
        bad "uv's output was swallowed — a sync nobody can read is a sync nobody can fix"
    fi

    CURRENT="and the end-of-run refusal still names dists: after a partial sync"
    local start end parts0 parts1 here
    here="$PWD"
    cd "$REPO" || cannot_look "could not enter the scratch checkout"
    LOOP_ENV_FINGERPRINT=""
    LOOP_ENV_COMPONENTS=""
    loop_env_fingerprint >/dev/null 2>&1 || true
    start="$LOOP_ENV_FINGERPRINT"
    parts0="$LOOP_ENV_COMPONENTS"
    # THE FIRST LEG'S OWN `uv run` FINISHES WHAT THE SYNC COULD NOT — which is
    # exactly the original defect, arrived at down the failure path.
    mkdir -p "$REPO/.venv/lib/python3.12/site-packages/the_other_half-0.1.dist-info"
    loop_env_fingerprint >/dev/null 2>&1 || true
    end="$LOOP_ENV_FINGERPRINT"
    parts1="$LOOP_ENV_COMPONENTS"
    cd "$here" || cannot_look "could not return to the checkout under test"
    differs "$start" "$end" "the fingerprint either side of the leg's completion"
    N=$((N + 1))
    OUT="${WORK}/movedfail${N}.log"
    loop_key_moved "atree" "$start" "$parts0" "atree" "$end" "$parts1" "mode=fast" >"$OUT" 2>&1
    if grep -qE '^ +dists: ' "$OUT"; then
        ok "the refusal names the distribution census, so a failed sync is still legible"
    else
        bad "the refusal does not name dists: — a failed sync would leave the reader where three box loops already were"
    fi
}

case_the_sync_is_wired_into_the_loop_leg_ahead_of_the_key() {
    OUT=""
    CURRENT="check.sh syncs the environment before it derives the loop key"
    local sync_line key_line
    # AWK OVER THE WHOLE FILE, NOT `grep -n … | head -1 | cut`. `head` closes
    # the pipe on the first line it wants and a producer with more to write
    # takes SIGPIPE, which `pipefail` reports as a failure — the GQ-1 class this
    # drive pins one case away, and it would have fired here on the only file
    # in the tree big enough to fill the buffer. awk reads to EOF, keeps the
    # FIRST match's line number, and prints `0` for "not there" — so a missing
    # wiring is a VALUE this case reports rather than a status that kills it.
    #
    # THE MATCH IS `index()` ON A FIXED STRING and the comment test beside it,
    # because the call site's regex would need six escapes to survive awk and a
    # pattern nobody can read is a pattern nobody can fix. A prose mention of
    # the function — this file has several — is a comment line and excluded.
    sync_line=$(awk '
        index($0, "loop_env_sync") && $0 !~ /^[[:space:]]*#/ { if (!n) n = FNR }
        END { print n + 0 }
    ' "$ROOT/scripts/check.sh")
    key_line=$(awk '
        index($0, "LOOP_LEDGER_KEY=$(loop_ledger_key") { if (!n) n = FNR }
        END { print n + 0 }
    ' "$ROOT/scripts/check.sh")
    if [ "$sync_line" = 0 ]; then
        bad "nothing in check.sh calls loop_env_sync — the first leg's own \`uv run\` is still what installs, and it does it after the key"
    elif [ "$key_line" != 0 ] && [ "$sync_line" -lt "$key_line" ]; then
        ok "the sync (line ${sync_line}) comes before the key (line ${key_line})"
    else
        bad "the sync does not sit before the key derivation: sync=${sync_line} key=${key_line}"
    fi
    CURRENT="and the start's own environment is kept for the end to compare against"
    if grep -qE '^[[:space:]]*LOOP_LEDGER_ENV=' "$ROOT/scripts/check.sh"; then
        ok "the start fingerprint is captured — the end can say which half moved"
    else
        bad "nothing keeps the START fingerprint: loop_env_fingerprint overwrites its globals at the end, so the refusal can only say that something moved"
    fi
}

# --- the cases, in the order they should run ---------------------------------

case_the_declarations_are_read_from_the_derivers_not_a_list
case_the_ledgers_digest_is_the_same_where_only_sha256sum_exists
case_no_site_in_this_family_spells_a_digest_tool_by_hand
case_the_row_carries_tree_and_env_appended_after_passes
case_a_row_written_before_those_fields_existed_still_hits
case_the_attributor_names_which_of_the_three_lines_moved
case_the_attributor_reads_the_rows_components_most_specific_first
case_the_tree_token_says_what_moved_and_whether_it_was_only_docs
case_an_equal_tree_row_outranks_a_differing_tree_row_whatever_the_file_order
case_the_fingerprint_globals_survive_the_call_that_sets_them
case_the_census_counts_rows_and_reports_a_seed
case_a_seeded_row_is_no_hit_once_the_tree_has_moved
case_a_declared_key_changing_does_not_move_the_key
case_an_undeclared_key_changing_does_move_the_key
case_zero_declarations_is_a_broken_read_and_hashes_the_whole_file
case_an_empty_distribution_census_is_could_not_look
case_a_package_installed_while_the_gate_runs_moves_the_env_half_of_the_key
case_the_sync_installs_ahead_of_the_key_so_the_two_ends_agree
case_a_sync_that_cannot_run_is_printed_and_never_a_refusal
case_a_sync_that_exits_non_zero_is_the_legs_business_and_the_refusal_still_names_dists
case_the_sync_is_wired_into_the_loop_leg_ahead_of_the_key
case_the_merge_base_is_used_and_not_mains_tip
case_an_exported_suite_variable_moves_the_key
case_the_process_environment_wins_over_the_env_file
case_the_read_set_census_has_one_owner_and_this_file_names_nothing
case_a_moved_read_set_is_attributed_by_name
case_a_checkout_with_no_census_says_so_and_a_broken_read_refuses
case_the_same_tree_at_two_scopes_is_two_keys
case_a_wider_scope_never_reads_a_narrower_verdict
case_the_tree_and_the_environment_are_both_in_the_key
case_an_unreadable_always_on_declaration_is_refused_on_write
case_every_doubt_is_a_miss_and_never_an_exit_2_on_the_consult_path
case_a_recorded_row_round_trips
case_the_local_loop_really_is_one_pass
case_the_leg_consults_before_it_measures_and_records_only_after_green
case_the_banner_takes_line_one_as_the_token_and_indents_the_rest
case_the_superseded_sentence_was_superseded_in_the_same_commit
case_no_pipeline_tail_in_this_territory_still_uses_grep_q
case_the_pipe_race_is_real_above_the_buffer_and_the_new_form_survives_it
case_both_verdict_rows_record_what_the_run_COST
case_a_row_without_the_cost_fields_is_still_a_hit
case_an_empty_derived_declaration_leaves_the_key_unchanged
case_a_planted_churn_in_a_declared_derived_path_does_not_move_the_key
case_a_churn_in_an_undeclared_path_still_moves_the_key
case_an_unreadable_derived_declaration_excludes_nothing_and_says_so
case_a_declaration_outside_the_reader_sources_is_named
case_a_declaration_inside_the_reader_sources_prints_no_stray_note
case_a_miss_prints_the_docs_only_line_by_default
case_a_docs_only_commit_reuses_the_pytest_verdict_and_banks_a_reuse_row
case_a_mixed_delta_measures_in_full
case_a_dirty_tree_is_never_docs_only
case_a_run_that_rewrites_a_path_the_key_reads_names_it
case_a_rewrite_the_leg_declares_is_subtracted_and_the_key_is_heads
case_the_bank_asks_before_the_key_re_derives
case_the_bank_remembers_what_it_refused_and_its_rm_spares_the_memory
case_a_bank_measured_on_a_dirty_tree_is_no_basis_for_a_docs_only_reuse
case_a_declaring_product_still_reuses_a_docs_only_loop_verdict
case_a_docs_path_spelled_under_apps_forces_a_measure
case_mine_and_pr_never_reuse_on_a_docs_only_delta
case_loop_health_reads_a_reuse_row
case_the_two_ledger_files_that_bought_a_2302s_remeasure_are_a_reuse
case_the_docs_only_source_is_the_nearest_MEASURED_ancestor
case_the_docs_only_road_admits_a_declaring_product
case_a_quote_the_module_declares_a_non_read_takes_the_road
case_an_undeclared_quote_refuses_and_names_a_quote_not_a_read
case_a_stale_non_read_declaration_is_refused_naming_its_line
case_a_path_outside_the_declared_list_is_a_full_bank
case_the_readers_are_derived_per_path_and_a_literal_read_refuses
case_a_banked_row_whose_legs_do_not_cover_this_gate_is_not_honoured
case_a_checkout_with_no_gate_declares_no_leg_set_and_compares_nothing
case_the_leak_proof_field_is_appended_last_or_the_row_is_refused
case_a_one_pass_row_is_honoured_only_with_a_green_leak_proof
case_a_drive_row_is_never_a_full_verdict
case_the_machine_half_is_the_image_on_a_box_and_the_host_elsewhere
case_a_reserved_drawer_path_is_judged_even_where_the_tree_has_none
case_an_absorbed_derived_output_keys_as_absent_and_nothing_else_does
case_the_declaration_is_read_from_check_sh_and_not_kept_here
case_a_push_of_a_ref_that_is_not_the_measured_tree_is_not_honoured
case_pm_pushs_detached_sha_push_is_honoured_in_seconds
case_an_ordinary_push_of_the_measured_branch_is_honoured
case_a_multi_ref_push_is_vouched_for_only_when_every_tree_is_measured
case_a_deletion_carries_no_tree_and_falls_back_to_the_working_tree
case_one_subtraction_site_serves_both_measured_tree_readers
case_a_box_push_of_a_tree_that_declares_a_derived_path_is_exempt
case_a_banked_measured_verdict_honours_a_push_from_a_declaring_checkout
case_the_wall_refuses_a_one_pass_row_without_its_proof

echo "test_loop_ledger: ${PASSED} passed · ${FAILED} failed"
# Every case ran. Anything below here is a verdict on them, not another case —
# see section 5 of the preamble for why saying so is load-bearing.
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! the --loop LEDGER is not failing closed. A verdict cache is the one" >&2
    echo "   instrument here whose failure mode is a GREEN RUN THAT MEASURED" >&2
    echo "   NOTHING — it costs a rung its gate, silently, and looks like speed." >&2
    exit 1
fi
exit 0
