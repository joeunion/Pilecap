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
# drives: .github/workflows/ci.yml config/settings/test.py deploy/iam/verifier_bootstrap.sh deploy/policy_summary.py deploy/provision.sh docs/product scripts/archaeology_lib.sh scripts/check.sh scripts/docs_legs.sh scripts/gate_ledger.sh scripts/gate_refuse.sh scripts/goalpost_scan.py scripts/loop_health.py scripts/publish.sh scripts/queue_index.py scripts/secrets_scan.sh scripts/tests/test_publish.sh scripts/tests/test_verifier_image.sh
# The drive for the four `--fast` census bodies in `scripts/docs_legs.sh`:
# `adr-census`, `dangling-docs`, `loop-names` and `ci-env`.
#
#   ./scripts/tests/test_fast_censuses.sh          run every case
#   ./scripts/tests/test_fast_censuses.sh --list   name them and stop
#
# WHY IT EXISTS. Two of the four bodies were EXTRACTED from `scripts/publish.sh`
# so that one implementation answers the question at two scopes — the whole
# exported artifact at release, the active rung's changed files at every commit.
# An extraction is exactly the operation that silently changes an output, and
# the release-time half's printed lines are a published contract
# (`scripts/tests/test_publish.sh` greps them). So the first thing this drive
# proves is that the extraction changed nothing: the ORIGINAL bodies are kept
# here verbatim as a reference implementation and run against the same scratch
# artifact as the library's, and the two transcripts are diffed. The other two
# bodies are new and had no home at all.
#
# IT BUILDS ITS OWN VICTIMS, always. Every plant is a file this drive created in
# a scratch directory under `mktemp -d`, or a scratch COPY of a real file —
# never a real file moved aside and put back, which is the class that deleted a
# consumer's tracked file when the restore never ran.
#
# IT NEVER SHELLS OUT TO THE GATE. The per-checkout gate lock refuses a nested
# `./scripts/check.sh`, so a case that ran the gate to prove a leg would go red
# for the lock and not for the property. Every case calls the leg BODY.
#
# THE PLANTS ARE ASSEMBLED FROM HALVES, the discipline `scripts/publish.sh` and
# `scripts/archaeology_lib.sh` both use: this file SHIPS, and a ghost ADR id or
# a pointer to a file that does not exist, spelled here in full, would be caught
# by the very censuses it is driving — on its own author.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#   * THE CHANGED-FILE DERIVATION ITSELF. `secrets_scan_changed_files`' branches,
#     merge-base arithmetic and unborn-HEAD edges are `test_secrets_scan.sh`'s.
#     This drive uses the simplest of them (unborn HEAD, staged only) because
#     the question here is the SCANS, not the narrowing.
#   * THE LEG WIRING IN `scripts/check.sh`. That each body is reached by a `leg`
#     call, in the `--fast` tier, with the announced banner, is proven by a
#     static read of the file — the cases below name the lines they read. What
#     a real `--fast` run prints is the gate's own transcript, not this drive's.
#   * VALUES. `ci-env` reads KEYS. A workflow that supplies every key with a
#     wrong endpoint or a stale credential is green here and red on the runner.
#   * TIMING AS AN ASSERTION. The bodies are sub-second on this tree and the
#     gate prints each leg's wall; a threshold here would be a flake on a loaded
#     shared box, which teaches the next reader to ignore the drive.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_fast_censuses: scripts/tests/drive_preamble.sh is not in this tree." >&2
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
    echo "!! test_fast_censuses: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_[A-Za-z0-9_]*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_fast_censuses.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
for f in scripts/docs_legs.sh scripts/secrets_scan.sh scripts/check.sh scripts/publish.sh \
    scripts/archaeology_lib.sh; do
    [ -f "$f" ] || cannot_look "$f is not in this tree"
done
ROOT="$PWD"
# shellcheck source=scripts/secrets_scan.sh
. "$ROOT/scripts/secrets_scan.sh"
# The SHIP/SKELETON/TRIM classifier the two per-rung bodies narrow with. Sourced
# BEFORE the library, exactly as scripts/check.sh and scripts/publish.sh do it —
# the bodies refuse rather than scan unfiltered when it is missing, and a drive
# that did not source it would prove that refusal and nothing else.
# shellcheck source=scripts/archaeology_lib.sh
. "$ROOT/scripts/archaeology_lib.sh"
# shellcheck source=scripts/docs_legs.sh
. "$ROOT/scripts/docs_legs.sh"
for fn in docs_adr_census docs_dangling_docs docs_adr_census_loop \
    docs_dangling_docs_loop docs_loop_names_leg docs_ci_env_leg bucket_for_path; do
    command -v "$fn" >/dev/null 2>&1 ||
        cannot_look "scripts/docs_legs.sh defines no $fn — the body is gone"
done

WORK=$(mktemp -d "${TMPDIR:-/tmp}/djb-test-fastcensus.XXXXXX") || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

# --- the assembled plants ---------------------------------------------------
# Halves no pattern can join. `PLANT_ADR` is an id whose home has never heard of
# it; `PLANT_REF` is a markdown path under the docs tree that exists nowhere.
# Neither is written out whole anywhere in this file.
_d="docs/product/"
_adr="ADR "
PLANT_ADR="${_adr}zzz-99"
PLANT_REF="${_d}zzz_nowhere.md"
REAL_ADR="${_adr}zzz-1"
# The FORWARD id: the shape a ledger legitimately carries before the decision is
# written. Same grammar as PLANT_ADR, a different number, so neither case below
# can be satisfied by the other's fixture.
FORWARD_ADR="${_adr}zzz-98"
unset _d _adr

RUN_OUT=""
RC=0
show_out() { sed 's/^/             | /' "$RUN_OUT"; }

# ---------------------------------------------------------------------------
# A scratch git repository in the UNBORN-HEAD shape: nothing committed, so
# `secrets_scan_changed_files` reports every staged file as changed. That is the
# simplest of its branches and the only one these cases need.
# ---------------------------------------------------------------------------
REPO=""
fresh_repo() {
    REPO="${WORK}/repo-$$-$RANDOM"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/apps/example" "$REPO/scripts" "$REPO/docs/product"
    (cd "$REPO" && git init -q -b main)
    # The two ADR homes, with one id each, so the census has somewhere to
    # resolve to and never refuses for an empty home.
    printf '# architecture\n\n%s is decided here.\n' "$REAL_ADR" \
        >"$REPO/docs/product/architecture.md"
    printf '# ingredients\n\nnothing yet.\n' \
        >"$REPO/docs/product/adrs-ingredients.md"
}

run_in_repo() {
    RUN_OUT="${WORK}/run-$$-$RANDOM.log"
    set +e
    (cd "$REPO" && "$@") >"$RUN_OUT" 2>&1
    RC=$?
    set -e
}

# ---------------------------------------------------------------------------
# G7.1 — the two split censuses, per rung
# ---------------------------------------------------------------------------

case_a_planted_unresolvable_adr_cite_in_a_changed_file_reds_fast() {
    CURRENT=case_a_planted_unresolvable_adr_cite_in_a_changed_file_reds_fast
    fresh_repo
    printf '"""A docstring citing %s, which resolves nowhere."""\n' "$PLANT_ADR" \
        >"$REPO/apps/example/plant.py"
    (cd "$REPO" && git add -A)
    run_in_repo docs_adr_census_loop
    if [ "$RC" = "1" ] &&
        grep -qF "adr-census: $PLANT_ADR resolves nowhere" "$RUN_OUT" &&
        grep -qF "apps/example/plant.py" "$RUN_OUT"; then
        ok "exit 1, naming the id and the citing file"
    else
        bad "exit $RC, want 1 naming the ghost id and apps/example/plant.py"
        show_out
    fi

    CURRENT="${CURRENT} (and the id that DOES resolve stays silent)"
    printf '"""A docstring citing %s, which resolves."""\n' "$REAL_ADR" \
        >"$REPO/apps/example/plant.py"
    (cd "$REPO" && git add -A)
    run_in_repo docs_adr_census_loop
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0 — the census is not merely counting citations"
    else
        bad "exit $RC, want 0 and silent"
        show_out
    fi
}

case_a_planted_dangling_docs_pointer_reds_fast() {
    CURRENT=case_a_planted_dangling_docs_pointer_reds_fast
    fresh_repo
    printf '# see %s for the argument\n' "$PLANT_REF" >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_in_repo docs_dangling_docs_loop
    if [ "$RC" = "1" ] &&
        grep -qF "dangling-docs: $PLANT_REF does not exist" "$RUN_OUT" &&
        grep -qF "scripts/plant.sh" "$RUN_OUT"; then
        ok "exit 1, naming the pointer and the file that spells it"
    else
        bad "exit $RC, want 1 naming the dangling pointer and scripts/plant.sh"
        show_out
    fi

    CURRENT="${CURRENT} (and a pointer that resolves stays silent)"
    printf '# see %sarchitecture.md for the argument\n' "docs/product/" \
        >"$REPO/scripts/plant.sh"
    (cd "$REPO" && git add -A)
    run_in_repo docs_dangling_docs_loop
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0 — a live pointer is not a finding"
    else
        bad "exit $RC, want 0 and silent"
        show_out
    fi
}

case_unchanged_files_are_not_scanned_per_rung() {
    CURRENT=case_unchanged_files_are_not_scanned_per_rung
    # THE TIERING, WHICH IS THE WHOLE REASON THERE ARE TWO CALLERS. The same
    # plant, in a file the active rung did NOT touch: the per-rung leg is
    # silent, and the whole-tree body over the same repository finds it.
    fresh_repo
    printf '"""A docstring citing %s."""\n' "$PLANT_ADR" \
        >"$REPO/apps/example/old.py"
    printf '# see %s\n' "$PLANT_REF" >"$REPO/scripts/old.sh"
    (cd "$REPO" && git -c user.name=t -c user.email=t@t add -A &&
        git -c user.name=t -c user.email=t@t commit -q -m base)
    # Now change something ELSE, and commit nothing further: the changed set is
    # the one new uncommitted file.
    printf '# nothing to see\n' >"$REPO/scripts/new.sh"
    (cd "$REPO" && git add -A)

    run_in_repo docs_adr_census_loop
    local adr_rc=$RC adr_out=$RUN_OUT
    run_in_repo docs_dangling_docs_loop
    if [ "$adr_rc" = "0" ] && [ "$RC" = "0" ] &&
        ! grep -q "VIOLATION" "$adr_out" && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "both per-rung legs are silent on a plant in an UNCHANGED file"
    else
        bad "adr exit $adr_rc, dangling exit $RC — want 0 and silent from both"
        show_out
    fi

    CURRENT="${CURRENT} (and the belt — the whole-tree body — finds it)"
    local whole="${WORK}/whole-$$-$RANDOM"
    (cd "$REPO" && git ls-files -z) >"$whole"
    local out="${WORK}/belt-$$-$RANDOM.log"
    set +e
    (cd "$REPO" && docs_adr_census "$REPO" "$whole") >"$out" 2>&1
    local belt_adr=$?
    (cd "$REPO" && docs_dangling_docs "$REPO" "$whole") >>"$out" 2>&1
    local belt_dang=$?
    set -e
    RUN_OUT="$out"
    if [ "$belt_adr" = "0" ] && [ "$belt_dang" = "0" ] &&
        grep -qF "adr-census: $PLANT_ADR resolves nowhere" "$out" &&
        grep -qF "dangling-docs: $PLANT_REF does not exist" "$out"; then
        ok "the whole-set scan prints both findings — publish.sh's scan is the belt"
    else
        bad "adr rc $belt_adr, dangling rc $belt_dang — want both findings printed"
        show_out
    fi
}

# ---------------------------------------------------------------------------
# The bucket filter: a SKELETON ledger's forward citations are vocabulary
# ---------------------------------------------------------------------------

# A scratch repo with BOTH kinds of docs file beside the two ADR homes, so a
# case can put the very same plant in each and read the difference.
bucketed_repo() {
    REPO="${WORK}/bucket-$$-$RANDOM"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/docs/product"
    (cd "$REPO" && git init -q -b main)
    printf '# architecture\n\n%s is decided here.\n' "$REAL_ADR" \
        >"$REPO/docs/product/architecture.md"
    printf '# ingredients\n' >"$REPO/docs/product/adrs-ingredients.md"
    printf '# in flight\n' >"$REPO/docs/product/in-flight.md"
    printf '# the build contract\n' >"$REPO/docs/product/build-contract.md"
}

case_a_forward_adr_id_in_a_skeleton_ledger_is_set_aside_not_a_finding() {
    CURRENT=case_a_forward_adr_id_in_a_skeleton_ledger_is_set_aside_not_a_finding
    # THE CLASS THIS FILTER EXISTS FOR, measured the first time the leg met an
    # ordinary ledger commit: a ledger the platform ships as a SKELETON carries
    # ids it is PROPOSING. Unfiltered, the leg reddens the hook on every one of
    # them, which is every ledger commit there will ever be.
    local skeleton="in-flight.md"
    if [ "$(bucket_for_path "docs/product/${skeleton}")" != "SKELETON" ]; then
        bad "docs/product/${skeleton} is not SKELETON to the classifier — this case has lost its subject"
        return
    fi
    bucketed_repo
    printf '\n- the next one is %s\n' "$FORWARD_ADR" >>"$REPO/docs/product/${skeleton}"
    (cd "$REPO" && git add -A)
    run_in_repo docs_adr_census_loop
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT" &&
        grep -qE '[0-9]+ ship file\(s\) scanned . [1-9][0-9]* skeleton/trim file\(s\) set aside' "$RUN_OUT"; then
        ok "exit 0, and the basis line COUNTS it: $(grep -oE '[0-9]+ ship file\(s\) scanned . [0-9]+ skeleton/trim file\(s\) set aside' "$RUN_OUT")"
    else
        bad "exit $RC, want 0 with the set-aside count printed"
        show_out
    fi

    CURRENT="${CURRENT} (and dangling-docs narrows the same way)"
    printf '\n- and the plan at %s\n' "$PLANT_REF" >>"$REPO/docs/product/${skeleton}"
    (cd "$REPO" && git add -A)
    run_in_repo docs_dangling_docs_loop
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0 — one classifier, both legs, never two answers to 'is this file SHIP'"
    else
        bad "exit $RC, want 0"
        show_out
    fi
}

case_the_same_forward_adr_id_in_a_ship_file_still_reds() {
    CURRENT=case_the_same_forward_adr_id_in_a_ship_file_still_reds
    # THE CONTROL, and without it the case above is satisfied by a leg that
    # stopped looking at anything. Same plant, same repo shape, a SHIP file.
    local ship="build-contract.md"
    if [ "$(bucket_for_path "docs/product/${ship}")" != "SHIP" ]; then
        bad "docs/product/${ship} is not SHIP to the classifier — this control has lost its subject"
        return
    fi
    bucketed_repo
    printf '\n- the next one is %s\n' "$FORWARD_ADR" >>"$REPO/docs/product/${ship}"
    (cd "$REPO" && git add -A)
    run_in_repo docs_adr_census_loop
    if [ "$RC" = "1" ] &&
        grep -qF "adr-census: $FORWARD_ADR resolves nowhere" "$RUN_OUT" &&
        grep -qF "docs/product/${ship}" "$RUN_OUT"; then
        ok "exit 1 — the narrowing is a bucket, not an off switch"
    else
        bad "exit $RC, want 1 naming the id and docs/product/${ship}"
        show_out
    fi

    CURRENT="${CURRENT} (and an unfiltered caller REFUSES rather than scanning everything)"
    # The classifier hidden from the body, in a subshell so the real one
    # survives: the bodies must say they cannot look, never quietly widen.
    RUN_OUT="${WORK}/nofilter-$$-$RANDOM.log"
    set +e
    (
        unset -f bucket_for_path
        cd "$REPO" && docs_adr_census_loop
    ) >"$RUN_OUT" 2>&1
    RC=$?
    set -e
    if [ "$RC" = "2" ] && grep -q "bucket_for_path is not defined" "$RUN_OUT"; then
        ok "exit 2 naming the absent classifier — a caller that forgot gets a refusal, not a wider scan"
    else
        bad "exit $RC, want 2 naming bucket_for_path"
        show_out
    fi
}

# ---------------------------------------------------------------------------
# G7.1 — THE BYTE-IDENTITY PROOF
#
# `ref_*` below are `scripts/publish.sh`'s ORIGINAL leg bodies, kept verbatim
# (the `say`/`violation` wrappers inlined as the echoes they were) and reading
# an exported-artifact directory the way they always did: a recursive grep over
# the directory, `.git` excluded. `new_*` are what `publish.sh` runs now: the
# library, over the git file list, with this caller printing the counts. Both
# run over the same scratch artifact and the transcripts are diffed.
#
# THIS IS THE FIXTURE. A captured string would go stale the first time somebody
# reworded a count line in one place; the original CODE cannot.
# ---------------------------------------------------------------------------

ref_legs() {
    local TARGET=$1 h HOMES CITED DOCREFS line id file ref adr_bad dang_bad
    echo ""
    echo "-- adr-census: every ADR id cited in the artifact resolves in the artifact"
    HOMES=$(mktemp "${TMPDIR:-/tmp}/djb-ref-homes.XXXXXX")
    for h in $DOCS_ADR_HOMES; do
        [ -f "$TARGET/$h" ] || {
            echo "!! $h is not in the artifact" >&2
            rm -f "$HOMES"
            return 2
        }
        grep -hoE "$DOCS_ADR_RE" "$TARGET/$h" || true
    done | LC_ALL=C sort -u >"$HOMES"
    if [ ! -s "$HOMES" ]; then
        rm -f "$HOMES"
        return 2
    fi
    CITED=$(mktemp "${TMPDIR:-/tmp}/djb-ref-cited.XXXXXX")
    (cd "$TARGET" && grep -rIoE "$DOCS_ADR_RE" --exclude-dir=.git . || true) |
        sed 's|^\./||' | LC_ALL=C sort -u >"$CITED"
    adr_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        id=${line#*:}
        file=${line%%:*}
        if ! grep -qxF "$id" "$HOMES"; then
            echo "   VIOLATION  adr-census: $id resolves nowhere in the artifact — cited in $file"
            adr_bad=$((adr_bad + 1))
        fi
    done <"$CITED"
    echo "   $(LC_ALL=C sort -u -t: -k2 "$CITED" | wc -l | tr -d ' ') citation sites read · $(wc -l <"$HOMES" | tr -d ' ') ids resolvable in the two homes"
    [ "$adr_bad" -eq 0 ] && echo "   ok — no decision is lost at publish"
    rm -f "$HOMES" "$CITED"

    echo ""
    echo "-- dangling-docs: every docs/ pointer spelled in the artifact resolves in it"
    DOCREFS=$(mktemp "${TMPDIR:-/tmp}/djb-ref-docrefs.XXXXXX")
    (cd "$TARGET" && grep -rIoE "$DOCS_REF_RE" --exclude-dir=.git . || true) |
        sed 's|^\./||' | LC_ALL=C sort -u >"$DOCREFS"
    dang_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        ref=${line#*:}
        file=${line%%:*}
        [ -f "$TARGET/$ref" ] && continue
        echo "   VIOLATION  dangling-docs: $ref does not exist in the artifact — spelled in $file"
        dang_bad=$((dang_bad + 1))
    done <"$DOCREFS"
    echo "   $(wc -l <"$DOCREFS" | tr -d ' ') pointer sites read"
    [ "$dang_bad" -eq 0 ] && echo "   ok — every docs/ pointer in the artifact resolves inside it"
    rm -f "$DOCREFS"
    return 0
}

new_legs() {
    local TARGET=$1 ART_FILES ADR_OUT DANG_OUT line adr_bad dang_bad rc
    ART_FILES=$(mktemp "${TMPDIR:-/tmp}/djb-new-artfiles.XXXXXX")
    git -C "$TARGET" ls-files -z >"$ART_FILES"

    echo ""
    echo "-- adr-census: every ADR id cited in the artifact resolves in the artifact"
    ADR_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-new-adrout.XXXXXX")
    set +e
    docs_adr_census "$TARGET" "$ART_FILES" >"$ADR_OUT"
    rc=$?
    set -e
    [ "$rc" = "2" ] && {
        rm -f "$ART_FILES" "$ADR_OUT"
        return 2
    }
    adr_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "   VIOLATION  $line"
        adr_bad=$((adr_bad + 1))
    done <"$ADR_OUT"
    echo "   $DOCS_ADR_SITES citation sites read · $DOCS_ADR_IDS ids resolvable in the two homes"
    [ "$adr_bad" -eq 0 ] && echo "   ok — no decision is lost at publish"
    rm -f "$ADR_OUT"

    echo ""
    echo "-- dangling-docs: every docs/ pointer spelled in the artifact resolves in it"
    DANG_OUT=$(mktemp "${TMPDIR:-/tmp}/djb-new-dangout.XXXXXX")
    set +e
    docs_dangling_docs "$TARGET" "$ART_FILES" >"$DANG_OUT"
    rc=$?
    set -e
    [ "$rc" = "2" ] && {
        rm -f "$ART_FILES" "$DANG_OUT"
        return 2
    }
    dang_bad=0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        echo "   VIOLATION  $line"
        dang_bad=$((dang_bad + 1))
    done <"$DANG_OUT"
    echo "   $DOCS_DANGLING_SITES pointer sites read"
    [ "$dang_bad" -eq 0 ] && echo "   ok — every docs/ pointer in the artifact resolves inside it"
    rm -f "$ART_FILES" "$DANG_OUT"
    return 0
}

scratch_artifact() {
    # A scratch ARTIFACT: a committed git tree, the shape `publish.sh` exports.
    # It carries a clean half and a dirty half, so the diff is over a transcript
    # with violations in it rather than over two "ok" lines.
    REPO="${WORK}/artifact-$$-$RANDOM"
    drive_require_scratch REPO "${REPO:-}"
    mkdir -p "$REPO/apps/example" "$REPO/scripts" "$REPO/docs/product"
    (cd "$REPO" && git init -q -b main)
    printf '# architecture\n\n%s is decided here.\n' "$REAL_ADR" \
        >"$REPO/docs/product/architecture.md"
    printf '# ingredients\n' >"$REPO/docs/product/adrs-ingredients.md"
    printf '"""cites %s and %s."""\n' "$REAL_ADR" "$PLANT_ADR" \
        >"$REPO/apps/example/a.py"
    printf '# points at %sarchitecture.md and at %s\n' "docs/product/" "$PLANT_REF" \
        >"$REPO/scripts/b.sh"
    (cd "$REPO" && git add -A &&
        git -c user.name=t -c user.email=t@t commit -q -m artifact)
}

case_publish_output_is_byte_identical_after_the_extraction() {
    CURRENT=case_publish_output_is_byte_identical_after_the_extraction
    scratch_artifact
    local before="${WORK}/bi-before-$$-$RANDOM.txt"
    local after="${WORK}/bi-after-$$-$RANDOM.txt"
    local rc_b rc_a
    DOCS_LEGS_SCOPE_NOUN="the artifact"
    set +e
    ref_legs "$REPO" >"$before" 2>&1
    rc_b=$?
    new_legs "$REPO" >"$after" 2>&1
    rc_a=$?
    set -e
    RUN_OUT="$after"
    if [ "$rc_b" != "0" ] || [ "$rc_a" != "0" ]; then
        bad "reference rc $rc_b, library rc $rc_a — want 0 from both"
        show_out
        return
    fi
    # A transcript with nothing in it would make the diff vacuous.
    if ! grep -q "VIOLATION" "$before"; then
        bad "the reference transcript carries no VIOLATION — the fixture proves nothing"
        sed 's/^/             | /' "$before"
        return
    fi
    if diff -u "$before" "$after" >"${WORK}/bi-diff.txt" 2>&1; then
        ok "$(grep -c . "$before") line(s), the original bodies and the library byte-for-byte equal"
    else
        bad "the extraction moved publish.sh's output:"
        sed 's/^/             | /' "${WORK}/bi-diff.txt"
    fi
}

# ---------------------------------------------------------------------------
# G7.2 — the LOOP_* name census
# ---------------------------------------------------------------------------

case_a_read_but_unassigned_loop_name_reds_fast() {
    CURRENT=case_a_read_but_unassigned_loop_name_reds_fast
    local dir="${WORK}/loopnames-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    mkdir -p "$dir/scripts"
    cp "$ROOT/scripts/check.sh" "$dir/scripts/check.sh"
    cp "$ROOT/scripts/loop_tier.sh" "$dir/scripts/loop_tier.sh"
    cp "$ROOT/scripts/gate_ledger.sh" "$dir/scripts/gate_ledger.sh"
    # THE SEAM TRAVELS WITH THE LIBRARY. `scripts/gate_ledger.sh` sources
    # `scripts/gate_refuse.sh` from beside itself and is deliberately intolerant
    # of its absence, so a scratch `scripts/` holding one without the other is a
    # fixture that dies at its own source line rather than at the property under
    # test — the class `test_gate_lease.sh`'s seam census exists to name.
    cp "$ROOT/scripts/gate_refuse.sh" "$dir/scripts/gate_refuse.sh"
    # THE PLANT IS THIS DRIVE'S OWN, in a COPY of check.sh — never the real one.
    local name="LOOP_""SCOPE_ZZZ"
    printf '\necho "$%s"\n' "$name" >>"$dir/scripts/check.sh"
    RUN_OUT="${WORK}/loopnames-$$-$RANDOM.log"
    set +e
    (cd "$dir" && docs_loop_names_leg) >"$RUN_OUT" 2>&1
    RC=$?
    set -e
    if [ "$RC" = "1" ] && grep -qF "$name is read by scripts/check.sh" "$RUN_OUT"; then
        ok "exit 1, naming the read-but-unassigned name and the three files that should set it"
    else
        bad "exit $RC, want 1 naming $name"
        show_out
    fi

    CURRENT="${CURRENT} (and a DEFAULTED read of the same name is silent)"
    cp "$ROOT/scripts/check.sh" "$dir/scripts/check.sh"
    printf '\necho "${%s:-fallback}"\n' "$name" >>"$dir/scripts/check.sh"
    set +e
    (cd "$dir" && docs_loop_names_leg) >"$RUN_OUT" 2>&1
    RC=$?
    set -e
    if [ "$RC" = "0" ]; then
        ok "exit 0 — a defaulted read cannot die under set -u, and is not a violation"
    else
        bad "exit $RC, want 0 — the exclusion that makes the census honest is gone"
        show_out
    fi
}

case_the_platforms_own_tree_has_no_such_name() {
    CURRENT=case_the_platforms_own_tree_has_no_such_name
    RUN_OUT="${WORK}/loopnames-real-$$-$RANDOM.log"
    set +e
    docs_loop_names_leg >"$RUN_OUT" 2>&1
    RC=$?
    set -e
    if [ "$RC" = "0" ] && grep -q "READ − ASSIGNED is empty" "$RUN_OUT"; then
        ok "exit 0 on the platform's own tree — $(sed -n '1s/^  //p' "$RUN_OUT")"
    else
        bad "exit $RC, want 0 — this platform must not ship the class the census names"
        show_out
    fi
}

case_the_naive_two_file_form_is_false_on_this_tree() {
    CURRENT=case_the_naive_two_file_form_is_false_on_this_tree
    # THE ROW THAT COMMISSIONED THE LEG PROPOSED A DIFFERENT INSTRUMENT, and it
    # is wrong here: the names in check.sh minus the names in loop_tier.sh is a
    # long list of variables check.sh assigns itself. Pinned so nobody restores
    # it thinking the corrected form is a needless complication.
    local naive assigned
    naive=$(LC_ALL=C comm -13 \
        <(grep -o 'LOOP_[A-Z_]*' "$ROOT/scripts/loop_tier.sh" | LC_ALL=C sort -u) \
        <(grep -o 'LOOP_[A-Z_]*' "$ROOT/scripts/check.sh" | LC_ALL=C sort -u) |
        grep -c .)
    RUN_OUT="${WORK}/naive-$$-$RANDOM.log"
    set +e
    docs_loop_names_leg >"$RUN_OUT" 2>&1
    RC=$?
    set -e
    if [ "$naive" -gt 0 ] && [ "$RC" = "0" ]; then
        ok "the two-file form names $naive residual name(s) here; the corrected READ − ASSIGNED form names none"
    else
        bad "the two-file form named $naive and the corrected form exited $RC — one of the two changed"
        show_out
    fi
}

# ---------------------------------------------------------------------------
# G7.3 — the ci-env census
# ---------------------------------------------------------------------------

# A scratch settings/example/workflow trio, so no case reads or writes the real
# ones. `ci_world <dir>` builds the healthy shape; a case then plants in it.
ci_world() {
    local dir=$1
    mkdir -p "$dir/config/settings" "$dir/.github/workflows"
    cat >"$dir/config/settings/base.py" <<'PY'
AWS_STORAGE_BUCKET_NAME: str = env.str("AWS_STORAGE_BUCKET_NAME", default="")
AWS_S3_REGION_NAME: str = env.str("AWS_S3_REGION_NAME", default="")
AWS_S3_ENDPOINT_URL: str | None = env.str("AWS_S3_ENDPOINT_URL", default="") or None
AWS_S3_CUSTOM_DOMAIN: str | None = env.str("AWS_S3_CUSTOM_DOMAIN", default="") or None
AWS_ACCESS_KEY_ID: str = env.str("AWS_ACCESS_KEY_ID", default="")
AWS_SECRET_ACCESS_KEY: str = env.str("AWS_SECRET_ACCESS_KEY", default="")
AWS_QUERYSTRING_AUTH: bool = env.bool("AWS_QUERYSTRING_AUTH", default=True)
PY
    cat >"$dir/.env.example" <<'ENV'
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=us-east-1
AWS_S3_ENDPOINT_URL=http://127.0.0.1:9000
AWS_S3_CUSTOM_DOMAIN=
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin
AWS_QUERYSTRING_AUTH=1
ENV
    printf 'AWS_STORAGE_BUCKET_NAME = ""\n' >"$dir/config/settings/test.py"
    cat >"$dir/.github/workflows/ci.yml" <<'YML'
name: gate
on: [push]
env:
  DATABASE_URL: postgres://x
  AWS_S3_ENDPOINT_URL: http://127.0.0.1:9000
  AWS_S3_REGION_NAME: us-east-1
  AWS_ACCESS_KEY_ID: minioadmin
  AWS_SECRET_ACCESS_KEY: minioadmin
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - run: ./scripts/check.sh
YML
}

run_ci_env() {
    local dir=$1
    RUN_OUT="${WORK}/cienv-$$-$RANDOM.log"
    set +e
    (cd "$dir" && docs_ci_env_leg) >"$RUN_OUT" 2>&1
    RC=$?
    set -e
}

case_the_population_carries_the_digit_class() {
    CURRENT=case_the_population_carries_the_digit_class
    # THE CHARACTER CLASS IS THE FINDING. `AWS_[A-Z_]+` stops dead at the digit
    # and yields a token that is not a name, blind to every S3 key. This case
    # asserts the population the leg PRINTS carries the full names and that the
    # digit-blind grep really does truncate on the same file.
    local dir="${WORK}/cienv-digits-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    run_ci_env "$dir"
    local blind
    blind=$(grep -oE 'AWS_[A-Z_]+' "$dir/config/settings/base.py" | LC_ALL=C sort -u | grep -cx 'AWS_S' || true)
    if [ "$RC" = "0" ] &&
        grep -q "population (4): AWS_ACCESS_KEY_ID AWS_S3_ENDPOINT_URL AWS_S3_REGION_NAME AWS_SECRET_ACCESS_KEY" "$RUN_OUT" &&
        [ "$blind" = "1" ]; then
        ok "the population names the S3 keys in full, while the digit-blind class yields the bogus truncated token"
    else
        bad "exit $RC, digit-blind truncation seen $blind time(s) — want the four full names and 1"
        show_out
    fi
}

case_a_missing_aws_key_in_ci_env_reds_fast() {
    CURRENT=case_a_missing_aws_key_in_ci_env_reds_fast
    local dir="${WORK}/cienv-missing-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    # THE PLANTED DELETION IS THE ENDPOINT KEY, on purpose: it is the one a
    # digit-blind population never had in it, so a census that reds here is a
    # census whose character class is right.
    grep -v 'AWS_S3_ENDPOINT_URL' "$dir/.github/workflows/ci.yml" >"$dir/ci.tmp"
    mv "$dir/ci.tmp" "$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "1" ] && grep -q "ci-env: AWS_S3_ENDPOINT_URL is read from the environment" "$RUN_OUT"; then
        ok "exit 1 naming AWS_S3_ENDPOINT_URL — the key a digit-blind census cannot see"
    else
        bad "exit $RC, want 1 naming AWS_S3_ENDPOINT_URL"
        show_out
    fi

    CURRENT="${CURRENT} (and the credential key too)"
    ci_world "$dir"
    grep -v 'AWS_SECRET_ACCESS_KEY' "$dir/.github/workflows/ci.yml" >"$dir/ci.tmp"
    mv "$dir/ci.tmp" "$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "1" ] && grep -q "ci-env: AWS_SECRET_ACCESS_KEY is read from the environment" "$RUN_OUT"; then
        ok "exit 1 naming AWS_SECRET_ACCESS_KEY — the no-credentials shape"
    else
        bad "exit $RC, want 1 naming AWS_SECRET_ACCESS_KEY"
        show_out
    fi
}

case_no_workflow_file_is_a_printed_skip() {
    CURRENT=case_no_workflow_file_is_a_printed_skip
    local dir="${WORK}/cienv-nowf-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    rm -f "$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "0" ] && grep -q "SKIP:" "$RUN_OUT" &&
        grep -q "runs no GitHub Actions" "$RUN_OUT"; then
        ok "exit 0 with the skip PRINTED — a product without Actions, said out loud"
    else
        bad "exit $RC, want 0 with a printed SKIP line"
        show_out
    fi
}

case_a_secrets_valued_key_satisfies_the_census() {
    CURRENT=case_a_secrets_valued_key_satisfies_the_census
    local dir="${WORK}/cienv-secret-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    # A product whose runner takes its credentials from the repository's secret
    # store: the KEY is there, the value is an expression. The census reads keys.
    local expr='${{ secrets.AWS_SECRET_ACCESS_KEY }}'
    sed "s|AWS_SECRET_ACCESS_KEY: minioadmin|AWS_SECRET_ACCESS_KEY: ${expr}|" \
        "$dir/.github/workflows/ci.yml" >"$dir/ci.tmp"
    mv "$dir/ci.tmp" "$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0 — a secret-store expression is a value, and this leg reads keys"
    else
        bad "exit $RC, want 0 — the escape for a product that names no credential in its YAML"
        show_out
    fi
}

case_a_test_settings_pin_of_a_supplied_key_reds() {
    CURRENT=case_a_test_settings_pin_of_a_supplied_key_reds
    # THE MIRROR LENS. A key the workflow supplies that the test settings then
    # pin is an `env:` line doing nothing at all, while every criterion about
    # the block passes. This world is the OLDER shape (the workflow supplies,
    # the test settings pin only the bucket), so the case plants a pin.
    local dir="${WORK}/cienv-pin-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    printf 'AWS_S3_ENDPOINT_URL = "http://elsewhere"\n' >>"$dir/config/settings/test.py"
    run_ci_env "$dir"
    if [ "$RC" = "1" ] && grep -q "pins AWS_S3_ENDPOINT_URL" "$RUN_OUT"; then
        ok "exit 1 — the pin wins, so the workflow line is inert and says so"
    else
        bad "exit $RC, want 1 naming the inert key"
        show_out
    fi

    CURRENT="${CURRENT} (and the negative: a pin of a key the workflow does NOT supply is silent)"
    ci_world "$dir"
    run_ci_env "$dir"
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0 — the bucket name is pinned and deliberately absent from the workflow"
    else
        bad "exit $RC, want 0 — this is the shape the platform's own tree is in"
        show_out
    fi
}

# THE ONE-AUTHORITY SHAPE — the platform's own tree since the store credential
# moved: the test settings pin the store's endpoint, region and published pair
# (and the session token absent), the workflow env carries no AWS_ key, and the
# step after a credential exporter clears the three exported names with `""`.
ci_world_one_authority() {
    local dir=$1
    ci_world "$dir"
    cat >"$dir/config/settings/test.py" <<'PY'
AWS_STORAGE_BUCKET_NAME = ""
AWS_S3_ENDPOINT_URL = "http://127.0.0.1:9000"
AWS_S3_REGION_NAME = "us-east-1"
AWS_ACCESS_KEY_ID = "minioadmin"
AWS_SECRET_ACCESS_KEY = "minioadmin"  # pragma: allowlist secret — the published compose credential
AWS_SESSION_TOKEN: str | None = None
PY
    cat >"$dir/.github/workflows/ci.yml" <<'YML'
name: gate
on: [push]
env:
  DATABASE_URL: postgres://x
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
      - name: the gate
        env:
          AWS_ACCESS_KEY_ID: ""
          AWS_SECRET_ACCESS_KEY: ""
          AWS_SESSION_TOKEN: ""
        run: ./scripts/check.sh
YML
}

case_one_authority_is_clean_and_an_empty_pin_is_no_supply() {
    CURRENT=case_one_authority_is_clean_and_an_empty_pin_is_no_supply
    local dir="${WORK}/cienv-one-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world_one_authority "$dir"
    run_ci_env "$dir"
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT" &&
        grep -q "cleared: AWS_SESSION_TOKEN at .github/workflows/ci.yml:14" "$RUN_OUT" &&
        [ "$(grep -c '^  exempt: ' "$RUN_OUT")" = "4" ]; then
        ok "exit 0 — the four population names are pinned by the test settings, and the step's empty pins are printed as clearings, not supplies"
    else
        bad "exit $RC, want 0 with four exemptions and the clearings printed"
        show_out
    fi
}

case_a_second_authority_planted_back_names_both_file_lines() {
    CURRENT=case_a_second_authority_planted_back_names_both_file_lines
    local dir="${WORK}/cienv-two-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world_one_authority "$dir"
    # THE PLANT IS THE ENDPOINT, back in the workflow env — the digit-class name,
    # and the one whose second authority would redirect every S3 call.
    sed 's|^  DATABASE_URL: postgres://x$|  DATABASE_URL: postgres://x\
  AWS_S3_ENDPOINT_URL: http://127.0.0.1:9000|' "$dir/.github/workflows/ci.yml" >"$dir/ci.tmp"
    mv "$dir/ci.tmp" "$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "1" ] &&
        grep -q "AWS_S3_ENDPOINT_URL has TWO authorities — config/settings/test.py:2 and .github/workflows/ci.yml:5" "$RUN_OUT"; then
        ok "exit 1 naming both authorities as file:line"
    else
        bad "exit $RC, want 1 naming config/settings/test.py:2 and .github/workflows/ci.yml:5"
        show_out
    fi

    CURRENT="${CURRENT} (and an EMPTY value planted there instead is a clearing, silent)"
    ci_world_one_authority "$dir"
    sed 's|^  DATABASE_URL: postgres://x$|  DATABASE_URL: postgres://x\
  AWS_S3_ENDPOINT_URL: ""|' "$dir/.github/workflows/ci.yml" >"$dir/ci.tmp"
    mv "$dir/ci.tmp" "$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT"; then
        ok "exit 0 — an empty value decides nothing about the store, so it is no second authority"
    else
        bad "exit $RC, want 0 — an empty pin is not a supply"
        show_out
    fi
}

case_the_platforms_own_tree_has_one_authority() {
    CURRENT=case_the_platforms_own_tree_has_one_authority
    RUN_OUT="${WORK}/cienv-own-$$-$RANDOM.log"
    set +e
    (cd "$ROOT" && docs_ci_env_leg) >"$RUN_OUT" 2>&1
    RC=$?
    set -e
    if [ "$RC" = "0" ] && ! grep -q "VIOLATION" "$RUN_OUT" &&
        [ "$(grep -c '^  exempt: ' "$RUN_OUT")" -ge 4 ]; then
        ok "exit 0 on this tree — the store's names are the test settings' alone"
    else
        bad "exit $RC on this tree, want 0 with every population name exempt by the pin"
        show_out
    fi
}

case_an_unparsable_workflow_is_exit_2() {
    CURRENT=case_an_unparsable_workflow_is_exit_2
    local dir="${WORK}/cienv-tab-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    printf '\tAWS_ACCESS_KEY_ID: x\n' >>"$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "2" ]; then
        ok "exit 2 — a file nobody could parse is not a file with nothing in it"
    else
        bad "exit $RC, want 2 (could-not-look) on a tab-indented workflow"
        show_out
    fi

    CURRENT="${CURRENT} (and a workflow with no env: map at all is exit 2)"
    ci_world "$dir"
    printf 'name: x\non: [push]\njobs:\n  a:\n    runs-on: ubuntu-latest\n' \
        >"$dir/.github/workflows/ci.yml"
    run_ci_env "$dir"
    if [ "$RC" = "2" ]; then
        ok "exit 2 — no env: map is could-not-look, never 'every key is missing'"
    else
        bad "exit $RC, want 2"
        show_out
    fi
}

case_an_empty_population_is_exit_2() {
    CURRENT=case_an_empty_population_is_exit_2
    # A GREEN OVER NOTHING is the one verdict this leg may never print.
    local dir="${WORK}/cienv-empty-$$-$RANDOM"
    drive_require_scratch dir "${dir:-}"
    ci_world "$dir"
    printf '# no AWS reads at all\n' >"$dir/config/settings/base.py"
    run_ci_env "$dir"
    if [ "$RC" = "2" ] && grep -q "population is EMPTY" "$RUN_OUT"; then
        ok "exit 2 — a census with nothing in its population refuses rather than passing"
    else
        bad "exit $RC, want 2 naming the empty population"
        show_out
    fi
}

# ---------------------------------------------------------------------------
# The wiring: each body is reached by a `leg` call in the `--fast` tier.
# Static, because a nested gate run is refused by the checkout lock.
# ---------------------------------------------------------------------------

case_all_four_legs_are_wired_into_the_fast_tier() {
    CURRENT=case_all_four_legs_are_wired_into_the_fast_tier
    local fast_at leg_at name missing=""
    fast_at=$(grep -n '^if \[ "\$MODE" = "--fast" \]; then$' "$ROOT/scripts/check.sh" | sed -n '1p' | cut -d: -f1)
    if [ -z "$fast_at" ]; then
        bad "the --fast exit branch is not in scripts/check.sh — this case cannot place a leg"
        return
    fi
    for name in adr-census dangling-docs loop-names ci-env; do
        leg_at=$(grep -n "^leg ${name} " "$ROOT/scripts/check.sh" | sed -n '1p' | cut -d: -f1)
        if [ -z "$leg_at" ] || [ "$leg_at" -ge "$fast_at" ]; then
            missing="${missing}${name}(${leg_at:-none}) "
        fi
    done
    if [ -z "$missing" ]; then
        ok "all four leg call sites precede the --fast exit at line ${fast_at}"
    else
        bad "not announced in the --fast tier: ${missing}"
    fi
}

# --- the interpreter every shipped python file runs under --------------------
#
# THE RULE, in one sentence so the census can be read against it: A PYTHON FILE
# THIS REPOSITORY SHIPS RUNS ON THE CHECKOUT'S OWN INTERPRETER. An inline
# `python3 -c` or `python3 - <<PY` program does not — it is stdlib on any Python
# 3, it is guarded by its own `command -v python3` where absence would matter,
# and converting those would be churn with no property behind it.
#
# WHAT IT COST TO LEARN. `python3` off PATH is some other environment's Python.
# On this Mac it is a 3.12 or a 3.13 and the difference never showed. On Amazon
# Linux 2023 — the verifier boxes' base — it is the system 3.9, and the first
# off-box gate run died at the queue-index leg: `scripts/queue_index.py` reached
# `zip(expected, got, strict=True)`, got `TypeError: zip() takes no keyword
# arguments`, and the gate reported `docs/product/queue.md is not what
# queue_index.py generates` — the wrong finding, about the wrong file, in the
# one document every other document defers to for order. `.venv/bin/python` two
# directories away was 3.12.14.
#
# WHY A CENSUS AND NOT A LIST OF FIXED SITES. The files that break under 3.9
# today are two (`scripts/queue_index.py`, `scripts/loop_health.py` — both
# `zip(strict=)`); the rest are tolerated by accident and nothing keeps them so.
# A census over the population is the only form that stays true when the
# eleventh file grows a 3.12 feature.
#
# DECLARED BLIND SPOTS, taken where they are paid:
#   * `deploy/` is not scanned. Those scripts run on a deployment host and on
#     the owner Mac, not in a gate leg, and `deploy/provision.sh` already
#     resolves its own interpreter. The ONE file there that runs a repository
#     python file — `deploy/iam/verifier_bootstrap.sh`, which summarises the
#     policy with `deploy/policy_summary.py` — is asserted by its own drive
#     instead (`scripts/tests/test_verifier_image.sh`), because it resolves
#     `.venv/bin/python` from its own location rather than through the gate's
#     sourced seam, and this census reads call text rather than behaviour.
#   * An invocation built at runtime (a name in a variable this census cannot
#     follow) is invisible to it.
#   * It reads CALL TEXT with comments and quoted runs stripped, so a bare
#     `python3` inside a quoted string is stripped with the sentence around it.
case_no_shipped_python_file_is_run_by_a_bare_python3() {
    CURRENT=case_no_shipped_python_file_is_run_by_a_bare_python3
    local f offenders="" hits
    for f in "$ROOT"/scripts/*.sh "$ROOT"/scripts/githooks/* "$ROOT"/scripts/tests/*.sh; do
        [ -f "$f" ] || continue
        # COMMENTS STRIPPED AND QUOTED RUNS KEPT, which is the opposite of the
        # digest census next door and for a reason worth the line: every
        # interesting call here is `python3 "$SOMETHING"`, so stripping
        # quoted runs would strip the whole population. What replaces the
        # stripping is a NARROW second half — the next token must be a
        # variable reference or a path ending `.py`, which is what `python3 -c`,
        # `python3 - <<PY`, `command -v python3` and every English sentence
        # about python3 are not.
        hits=$(sed 's/#.*//' "$f" |
            grep -nE '(^|[^-[:alnum:]_./])python3[[:space:]]+("?\$\{?[A-Za-z_]|"?[A-Za-z0-9_./-]*\.py)' || true)
        [ -z "$hits" ] || offenders="${offenders} $(basename "$f"):$(printf '%s' "$hits" | head -n 1 | cut -d: -f1)"
    done
    if [ -z "$offenders" ]; then
        ok "no shell file under scripts/ runs a repository .py file with a bare python3"
    else
        bad "these run a shipped python file on whatever python3 is first on PATH:${offenders}"
    fi
}

case_the_two_docs_legs_name_the_checkouts_interpreter() {
    CURRENT=case_the_two_docs_legs_name_the_checkouts_interpreter
    local missing=""
    # The two legs the box actually met, asserted by their call text rather than
    # by the census above — that one proves an absence, these prove a presence.
    grep -qF '"$py" scripts/goalpost_scan.py --census' "$ROOT/scripts/check.sh" ||
        missing="${missing} goalpost-census"
    grep -qF '"$QUEUE_INDEX_PY" scripts/queue_index.py --check' "$ROOT/scripts/check.sh" ||
        missing="${missing} queue-index"
    grep -qE '^checkout_python\(\)' "$ROOT/scripts/gate_refuse.sh" ||
        missing="${missing} checkout_python-definition"
    # AND THE SEAM IS REACHABLE FROM `--census`, which exits long before the
    # library block: an early guarded source is what makes the mode work at all.
    grep -qF 'GATE_REFUSE_SOURCED:-}" ] || . scripts/gate_refuse.sh' "$ROOT/scripts/check.sh" ||
        missing="${missing} the-early-seam-source"
    if [ -z "$missing" ]; then
        ok "both docs legs run on checkout_python, and --census can reach it"
    else
        bad "not wired to the checkout interpreter:${missing}"
    fi
}

case_publish_sources_the_library_and_names_no_second_body() {
    CURRENT=case_publish_sources_the_library_and_names_no_second_body
    local sourced copies
    sourced=$(grep -c 'scripts/docs_legs\.sh' "$ROOT/scripts/publish.sh" || true)
    # The extracted greps must live in ONE file. A second spelling of either
    # expression in publish.sh is the duplication the extraction removed.
    copies=$(grep -cE "grep -rIoE '(ADR|docs/)" "$ROOT/scripts/publish.sh" || true)
    if [ "$sourced" -ge 1 ] && [ "$copies" = "0" ]; then
        ok "publish.sh sources the library and carries no second copy of either expression"
    else
        bad "sourced ${sourced} time(s), ${copies} inline copies of the scan expressions"
    fi
}

case_a_planted_unresolvable_adr_cite_in_a_changed_file_reds_fast
case_a_planted_dangling_docs_pointer_reds_fast
case_a_forward_adr_id_in_a_skeleton_ledger_is_set_aside_not_a_finding
case_the_same_forward_adr_id_in_a_ship_file_still_reds
case_unchanged_files_are_not_scanned_per_rung
case_publish_output_is_byte_identical_after_the_extraction
case_a_read_but_unassigned_loop_name_reds_fast
case_the_platforms_own_tree_has_no_such_name
case_the_naive_two_file_form_is_false_on_this_tree
case_the_population_carries_the_digit_class
case_a_missing_aws_key_in_ci_env_reds_fast
case_no_workflow_file_is_a_printed_skip
case_a_secrets_valued_key_satisfies_the_census
case_a_test_settings_pin_of_a_supplied_key_reds
case_one_authority_is_clean_and_an_empty_pin_is_no_supply
case_a_second_authority_planted_back_names_both_file_lines
case_the_platforms_own_tree_has_one_authority
case_an_unparsable_workflow_is_exit_2
case_an_empty_population_is_exit_2
case_all_four_legs_are_wired_into_the_fast_tier
case_publish_sources_the_library_and_names_no_second_body
case_no_shipped_python_file_is_run_by_a_bare_python3
case_the_two_docs_legs_name_the_checkouts_interpreter

echo
echo "test_fast_censuses: ${PASSED} passed, ${FAILED} failed"
drive_finished
[ "$FAILED" -eq 0 ] || exit 1
exit 0
