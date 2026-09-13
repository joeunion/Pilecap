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

# The drive for the `--loop` LEDGER — the key, the environment fingerprint with
# its deriver-declared exclusions, and the fail-closed direction of every doubt
# (`scripts/gate_ledger.sh`, loop-ledger section).
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
command -v shasum >/dev/null 2>&1 || cannot_look "no shasum on PATH — every digest here is one"
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
hex64() { printf '%s' "$1" | shasum -a 256 | awk '{print $1}'; }
# A 40-hex commit-shaped value, likewise.
sha40() { hex64 "$1" | cut -c1-40; }

# The five components a case hands the recorder or the attributor, in the fixed
# field order. Every crafted row in this drive is built through this, so a case
# that means to move ONE component moves exactly one.
crafted_components() {
    printf 'env-file=%s excluded=%s dists=%s head=%s merge-base=%s' \
        "${1:-$(hex64 envfile)}" "${2:-AWS_STORAGE_BUCKET_NAME,DATABASE_NAME}" \
        "${3:-$(hex64 dists)}" "${4:-$(sha40 head)}" "${5:-$(sha40 base)}"
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
    plant_row "$scope" TREEA ENVA "env-file=${E} excluded=X dists=${D} head=$(sha40 h)"
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
    n=$(grep -cE '^\./scripts/test\.sh .*--randomly-seed="\$PYTEST_SEED"' "$ROOT/scripts/check.sh")
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

# --- the cases, in the order they should run ---------------------------------

case_the_declarations_are_read_from_the_derivers_not_a_list
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
case_the_merge_base_is_used_and_not_mains_tip
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
