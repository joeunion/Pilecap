#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The
# shebang above is honoured by `./this`; `sh this` and `zsh this` IGNORE it,
# and neither of them fails where the mistake was made.
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
# drives: deploy/stage.sh deploy/release.sh deploy/ship.sh deploy/provision.sh scripts/loop_tier.sh scripts/gate_refuse.sh scripts/gate_ledger.sh
# cites: README.md
# The drive for `deploy/stage.sh` — the KEYS, which is the whole of what that
# script adds over typing its five acts by hand.
#
#   ./deploy/tests/test_stage.sh          run every case
#   ./deploy/tests/test_stage.sh --list   name them and stop
#
# WHY IT EXISTS. A keyed sequence fails in the one direction nothing notices:
# an act that SKIPS when its input moved. The transcript still prints six acts,
# the exit status is still 0, and the box is running old code, an unmigrated
# schema or an unreconciled alert route under a tag that says otherwise. The
# opposite failure — an act that runs when it did not need to — is merely slow
# and is visible in the seconds. So every case here plants exactly ONE input
# and asserts BOTH halves: the acts that must have run, and the acts that must
# have said `skipped` and named the input they were keyed on.
#
# IT BUILDS ITS OWN WORLD AND STAGES THAT. Every case runs against a throwaway
# git checkout under `mktemp -d` carrying a COPY of `stage.sh`, a copy of the
# real `scripts/loop_tier.sh` (the docs-only short circuit calls its
# classifier, and a stub of it would be this drive agreeing with itself), stub
# `provision.sh` and `ship.sh`, and a STUB `ssh` first on PATH that records
# every remote command line and answers from the case's own knobs. No box is
# contacted, no registry is asked, no container runtime is used, and the real
# repository is untouched — `scripts/tests/drive_preamble.sh` §1 and §3 are
# what make that last clause a fact rather than an intention.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE REAL BOX. Whether `provision.sh up` pulls, whether `release.sh`
#     migrates, whether the prober answers: none of that is here, and the
#     acceptance for it is one timed run on the stage box, pasted.
#   * WHAT THE ACTS DO. The stub `ssh` records a command line and exits with a
#     code the case chose. These cases prove the KEYING and the ORDER: which
#     acts run, which say `skipped`, which input each one names, and that
#     nothing after a failed act runs. What `release.sh` does when it runs is
#     `deploy/tests/test_release.sh`'s, and what `ship.sh` does is
#     `deploy/tests/test_ship.sh`'s.
#   * A COPY, NOT THE FILE ITSELF, IS WHAT RUNS — `test_release.sh`'s declared
#     limit and its reason: the script derives its siblings from its own
#     directory, so the scratch deployment has to contain it. The copy is `cp`
#     from this tree in every case, so it is the same bytes.
#   * THE REGISTRY'S OWN ANSWER. `image-digest` is stubbed to a knob, so "the
#     registry has this tag" is asserted as a branch and never as a fact about
#     a registry.
#   * A MIGRATION WHOSE LEAF DID NOT MOVE BUT WHOSE BYTES DID.
#     `django-linear-migrations` refuses that upstream; the key here is the
#     path set under `apps/*/migrations/`, exactly as the criteria name it.
set -euo pipefail

cd "$(dirname "$0")/../.."

[ -r scripts/tests/drive_preamble.sh ] || {
    echo "!! test_stage: scripts/tests/drive_preamble.sh is not in this tree." >&2
    echo "   This drive builds throwaway git checkouts, which is exactly the shape" >&2
    echo "   that wrote into the real repository from the pre-push hook the one time" >&2
    echo "   it was done without the preamble. Refusing to run without it." >&2
    exit 2
}
# shellcheck source=scripts/tests/drive_preamble.sh
. scripts/tests/drive_preamble.sh

# Section 5 of the preamble: on macOS's bash 3.2 a `set -u` death hands the EXIT
# trap a status of 0, so a drive that never reached its own summary reports
# success. Opting in makes that could-not-look instead.
DRIVE_OPTED_IN_TO_FINISH=1

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_stage: $*" >&2
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
    echo "!! unknown argument '$1': test_stage.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH — every case builds a throwaway checkout"
[ -f deploy/stage.sh ] || cannot_look "deploy/stage.sh is not in this tree — there is nothing to drive"
[ -f scripts/loop_tier.sh ] || cannot_look "scripts/loop_tier.sh is not in this tree — the docs-only short circuit calls its classifier and this drive copies it rather than modelling it"
[ -f scripts/gate_refuse.sh ] || cannot_look "scripts/gate_refuse.sh is not in this tree — scripts/loop_tier.sh sources it beside itself and a scratch world without it dies on a missing file"
[ -f scripts/gate_ledger.sh ] || cannot_look "scripts/gate_ledger.sh is not in this tree — the prod refusal reads its gate_nightly_read and this drive copies it rather than modelling it"

ROOT="$PWD"
SOURCE="$ROOT/deploy/stage.sh"
CLASSIFIER="$ROOT/scripts/loop_tier.sh"
# `loop_tier.sh` sources the refusal seam beside itself, so the scratch world
# carries that too: copying one half of a library pair is a world that dies on
# a missing file rather than the world under drive.
REFUSE_SEAM="$ROOT/scripts/gate_refuse.sh"
LEDGER="$ROOT/scripts/gate_ledger.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-stage-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
drive_require_scratch WORK "${WORK:-}"
drive_at_exit 'rm -rf "$WORK"'

CURRENT=""
ok() {
    echo "  ok       ${CURRENT} — $1"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   ${CURRENT} — $1"
    FAILED=$((FAILED + 1))
    [ -z "${STAGE_OUT:-}" ] || sed 's/^/             | /' "$STAGE_OUT" | tail -25
}

# --- the world ----------------------------------------------------------------
#
# One per case, so a case can never read the ssh log another case wrote.
N=0
CASE_DIR=""
REPO=""
SSH_LOG=""
SHIP_LOG=""
STAGE_OUT=""
STAGE_EXIT=0
BOX_TAG=""
STAGING_SSH_LOG=""
# The staging box a promotion to prod reads. The stub ssh answers this
# destination out of `<case>/staging/` and logs it apart from the prod box.
STAGING_DEST="ec2-user@staging.invalid"

# The registry's default answers. Build-once/promote-by-digest makes "the
# registry has the image this tree names" a precondition of every stage, so an
# ordinary case needs a registry that says yes; the refusal cases blank them.
DIGEST_A="sha256:1111111111111111111111111111111111111111111111111111111111111111"
DIGEST_B="sha256:2222222222222222222222222222222222222222222222222222222222222222"
DRIVE_REGISTRY="000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens"

fresh_world() {
    N=$((N + 1))
    CASE_DIR="${WORK}/case${N}"
    REPO="${CASE_DIR}/repo"
    SSH_LOG="${CASE_DIR}/ssh.log"
    SHIP_LOG="${CASE_DIR}/ship.log"
    STAGING_SSH_LOG="${CASE_DIR}/staging-ssh.log"
    mkdir -p "${REPO}/deploy/observability/alerts" "${REPO}/apps/core/migrations" \
        "${REPO}/scripts" "${CASE_DIR}/bin" "${CASE_DIR}/box" "${CASE_DIR}/staging"
    # Created empty, so "nothing was sent to the box" is an empty file rather
    # than a missing one: an absent file and zero invocations read the same to
    # `wc`, and only one of them is the property being asserted.
    : >"$SSH_LOG"
    : >"$SHIP_LOG"
    : >"$STAGING_SSH_LOG"
    : >"${CASE_DIR}/staging/TREE"
    : >"${CASE_DIR}/staging/LIVE"

    cp "$SOURCE" "${REPO}/deploy/stage.sh"
    chmod +x "${REPO}/deploy/stage.sh"
    cp "$CLASSIFIER" "${REPO}/scripts/loop_tier.sh"
    cp "$REFUSE_SEAM" "${REPO}/scripts/gate_refuse.sh"
    # THE NIGHTLY READER IS THE LEDGER'S OWN, copied rather than modelled: the
    # prod refusal reads `gate_nightly_read`, and a stub of it here would be
    # this drive agreeing with itself about the three forms.
    cp "$LEDGER" "${REPO}/scripts/gate_ledger.sh"

    # THE STUB provision.sh. `image-tag` is derived FROM GIT, the way the real
    # one derives it, because every key in the script under drive is a
    # comparison against that answer — a knob there would let a case pass while
    # the derivation was broken. The two image arms answer from case knobs, so
    # a case drives the registry without a registry.
    cat >"${REPO}/deploy/provision.sh" <<'PROVISION'
#!/usr/bin/env bash
here="$(cd -- "$(dirname -- "$0")" && pwd)"
service="${2:-}"
upper="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
case "${1:-}" in
image-tag)
    printf 'tree-%s\n' "$(cd "$here/.." && git rev-parse --short=12 'HEAD^{tree}')"
    ;;
image-repo)
    printf '%s/djb-%s\n' "${DJB_DRIVE_REGISTRY:?}" "$service"
    ;;
image-digest)
    eval "answer=\${DJB_DRIVE_DIGEST_${upper}:-}"
    if [ -z "$answer" ]; then
        echo "stub provision: the registry has no djb-${service} at that tag" >&2
        exit 2
    fi
    printf '%s\n' "$answer"
    ;;
*) echo "stub provision: unexpected $*" >&2; exit 2 ;;
esac
PROVISION
    chmod +x "${REPO}/deploy/provision.sh"

    # THE STUB ship.sh. It records that it was called, with its arguments, and
    # exits with the case's code. What a real ship does is test_ship.sh's.
    cat >"${REPO}/deploy/ship.sh" <<'SHIP'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_SHIP_LOG"
echo "stub ship: shipped"
exit "${DJB_DRIVE_SHIP_RC:-0}"
SHIP
    chmod +x "${REPO}/deploy/ship.sh"

    # THE BOX, as a file. `stage.sh`'s first remote read is `cat <ns>/TREE`,
    # and the stub ssh answers that one command out of this file — so "the box
    # holds tree X, pinned at digests Y and Z" is one artifact a case writes.
    : >"${CASE_DIR}/box/TREE"

    # THE STUB ssh, first on PATH. It records every remote command line in
    # order — the log IS the sequence, which is what lets a case assert that
    # nothing after a failed act ran — and answers the two reads the script
    # makes.
    #
    # TWO BOXES, TWO LOGS. A promotion to prod reads the STAGING box (its
    # `TREE` marker and its readyz) before it may touch the prod one, so the
    # stub tells them apart by the destination and keeps a log for each: "the
    # prod box was never contacted" is then an empty file, and the staging box
    # answering anything but those two reads is exit 97 — a promotion that
    # ACTED on staging is a defect this drive must see.
    cat >"${CASE_DIR}/bin/ssh" <<'SSH'
#!/usr/bin/env bash
# The last argument is the remote command; the one before it is the
# destination; everything before that is ssh's own.
cmd="${!#}"
dest="${@: -2:1}"
if [ -n "${DJB_DRIVE_STAGING_DEST:-}" ] && [ "$dest" = "$DJB_DRIVE_STAGING_DEST" ]; then
    printf '%s\n' "$cmd" >>"$DJB_DRIVE_STAGING_SSH_LOG"
    case "$cmd" in
    cat*TREE*)
        if [ -s "$DJB_DRIVE_STAGING_TREE" ]; then
            cat "$DJB_DRIVE_STAGING_TREE"
        else
            echo "cat: no such file or directory" >&2
            exit 1
        fi
        ;;
    cat*LIVE*)
        if [ -s "$DJB_DRIVE_STAGING_LIVE" ]; then
            cat "$DJB_DRIVE_STAGING_LIVE"
        else
            echo "cat: no such file or directory" >&2
            exit 1
        fi
        ;;
    *readyz-prober*) printf '%s' "${DJB_DRIVE_STAGING_READYZ_CODE:-200}"; exit "${DJB_DRIVE_STAGING_READYZ_RC:-0}" ;;
    *) echo "stub ssh: the STAGING box was asked to act: $cmd" >&2; exit 97 ;;
    esac
    exit 0
fi
printf '%s\n' "$cmd" >>"$DJB_DRIVE_SSH_LOG"
case "$cmd" in
cat*TREE*)
    if [ -s "$DJB_DRIVE_BOX_TREE" ]; then
        cat "$DJB_DRIVE_BOX_TREE"
    else
        echo "cat: no such file or directory" >&2
        exit 1
    fi
    ;;
# THE LIVE MARKER, as a file beside the box's TREE: withdrawn before an act
# changes the box, written only after the readyz answers.
rm\ -f*LIVE*) rm -f "$DJB_DRIVE_BOX_LIVE"; exit "${DJB_DRIVE_LIVE_RM_RC:-0}" ;;
echo\ \'live\ *LIVE*)
    line="${cmd#echo \'}"
    printf '%s\n' "${line%%\'*}" >"$DJB_DRIVE_BOX_LIVE"
    exit "${DJB_DRIVE_LIVE_RC:-0}"
    ;;
*secrets-fetch*) exit "${DJB_DRIVE_SECRETS_RC:-0}" ;;
*"docker login"*) exit "${DJB_DRIVE_LOGIN_RC:-0}" ;;
*provision.sh\ up*) exit "${DJB_DRIVE_UP_RC:-0}" ;;
*release.sh*)
    # The release's own transcript, as the box cats it back. Its migrate wall
    # is the line the closing line reads; a knob set EMPTY is a release that
    # printed none.
    printf '%s\n' "${DJB_DRIVE_RELEASE_OUT-release: migrate: 7s}"
    exit "${DJB_DRIVE_RELEASE_RC:-0}"
    ;;
*readyz-prober*) printf '%s' "${DJB_DRIVE_READYZ_CODE:-200}"; exit "${DJB_DRIVE_READYZ_RC:-0}" ;;
*) echo "stub ssh: unexpected remote command: $cmd" >&2; exit 97 ;;
esac
SSH
    chmod +x "${CASE_DIR}/bin/ssh"

    # The starting tree — the one the box is holding. Every plant below is a
    # commit on top of it, so the delta the script computes is a real git
    # delta between two real trees.
    printf 'first\n' >"${REPO}/apps/core/migrations/0001_initial.py"
    printf 'route\n' >"${REPO}/deploy/observability/alerts/apply.py"
    printf 'readme\n' >"${REPO}/README.md"
    printf 'note\n' >"${REPO}/notes.md"
    printf 'code\n' >"${REPO}/apps/core/services.py"
    git -C "$REPO" init -q
    git -C "$REPO" config user.email drive@drive.invalid
    git -C "$REPO" config user.name "stage drive"
    git -C "$REPO" add -A
    git -C "$REPO" -c commit.gpgsign=false commit -q -m base
    BOX_TAG="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    {
        printf '%s\n' "$BOX_TAG"
        printf 'digest web %s\n' "$DIGEST_A"
        printf 'digest worker %s\n' "$DIGEST_B"
    } >"${CASE_DIR}/box/TREE"
}

commit_plant() {
    git -C "$REPO" add -A
    git -C "$REPO" -c commit.gpgsign=false commit -q -m "$1"
}

# Run the copy of the script under the case's world. Output to a file, never a
# pipe: the exit status is the verdict, and the script under drive refuses a
# pipe anyway.
stage() {
    local label="$1" want="$2"
    shift 2
    CURRENT="$label"
    STAGE_OUT="${CASE_DIR}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    set +e
    (
        cd "$REPO" || exit 99
        PATH="${CASE_DIR}/bin:$PATH" \
            DJB_DRIVE_SSH_LOG="$SSH_LOG" \
            DJB_DRIVE_SHIP_LOG="$SHIP_LOG" \
            DJB_DRIVE_BOX_TREE="${CASE_DIR}/box/TREE" \
            DJB_DRIVE_REGISTRY="$DRIVE_REGISTRY" \
            DJB_DRIVE_DIGEST_WEB="${DIGEST_WEB_NOW-$DIGEST_A}" \
            DJB_DRIVE_DIGEST_WORKER="${DIGEST_WORKER_NOW-$DIGEST_B}" \
            DJB_DRIVE_STAGING_DEST="$STAGING_DEST" \
            DJB_DRIVE_STAGING_SSH_LOG="$STAGING_SSH_LOG" \
            DJB_DRIVE_STAGING_TREE="${CASE_DIR}/staging/TREE" \
            DJB_DRIVE_STAGING_LIVE="${CASE_DIR}/staging/LIVE" \
            DJB_DRIVE_BOX_LIVE="${CASE_DIR}/box/LIVE" \
            DJB_DRIVE_UP_RC="${UP_RC_NOW:-0}" \
            DJB_DRIVE_STAGING_READYZ_CODE="${STAGING_READYZ_NOW-200}" \
            DJB_DRIVE_RELEASE_OUT="${RELEASE_OUT_NOW-release: migrate: 7s}" \
            DJB_DEPLOY_NAMESPACE=drivens \
            ./deploy/stage.sh "$@"
    ) >"$STAGE_OUT" 2>&1
    STAGE_EXIT=$?
    set -e
    if [ "$STAGE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${STAGE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${STAGE_EXIT}"
        sed 's/^/             | /' "$STAGE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    fi
}

says() {
    if grep -qF -- "$1" "$STAGE_OUT"; then
        ok "says \"$1\""
    else
        bad "does not say \"$1\""
    fi
}

says_not() {
    if grep -qF -- "$1" "$STAGE_OUT"; then
        bad "says \"$1\" and must not"
    else
        ok "does not say \"$1\""
    fi
}

# The act line, asserted whole: an act's state and the input it names are one
# sentence, and half of it is not the property.
act_says() {
    local want="stage: [$1] $2 — $3"
    if grep -qF -- "$want" "$STAGE_OUT"; then
        ok "prints \"${want}\""
    else
        bad "does not print \"${want}\""
    fi
}

remote_count() { grep -c . "$SSH_LOG" || true; }

remote_has() {
    if grep -qF -- "$1" "$SSH_LOG"; then
        ok "the box was asked: \"$1\""
    else
        bad "the box was never asked: \"$1\" (it was asked: $(tr '\n' '|' <"$SSH_LOG"))"
    fi
}

remote_has_not() {
    if grep -qF -- "$1" "$SSH_LOG"; then
        bad "the box WAS asked \"$1\" and must not have been"
    else
        ok "the box was never asked \"$1\""
    fi
}

ships() {
    local want="$1" got
    got="$(grep -c . "$SHIP_LOG" || true)"
    if [ "$got" = "$want" ]; then
        ok "ship.sh called ${got} time(s)"
    else
        bad "ship.sh called ${got} time(s), wanted ${want}"
    fi
}

# =============================================================================

case_each_act_is_keyed_on_its_own_input() {
    # FOUR PLANTS, EACH MOVING ONE INPUT. The property is BOTH halves at once:
    # the acts the moved input keys, and the acts that said `skipped` naming
    # the input they were keyed on.

    # --- (a) a migration leaf moved ------------------------------------------
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    stage "a_migration_moved" 0 ec2-user@box.invalid --env staging
    act_says "5/6" release "ran: migrate+grants (a migration leaf moved)"
    says "--without-alerts"
    ships 1
    remote_has "release.sh --without-alerts"
    remote_has "readyz-prober"

    # --- (b) deploy/observability/ moved -------------------------------------
    fresh_world
    printf 'route v2\n' >"${REPO}/deploy/observability/alerts/apply.py"
    commit_plant "an alert route"
    stage "observability_moved" 0 ec2-user@box.invalid --env staging
    act_says "5/6" release "ran: alerts (deploy/observability/ moved)"
    says_not "--without-alerts"
    remote_has "readyz-prober"

    # --- (c) the image digest moved, and the tree did not --------------------
    fresh_world
    DIGEST_WEB_NOW="sha256:3333333333333333333333333333333333333333333333333333333333333333"
    stage "the_digest_moved" 0 ec2-user@box.invalid --env staging
    unset DIGEST_WEB_NOW
    act_says "1/6" ship "skipped: the tree tag (${BOX_TAG}) unchanged"
    act_says "2/6" secrets "skipped: the tree on the box (no ship, so its deploy/.env is still there) unchanged"
    act_says "5/6" release "ran: recreate (the web image digest moved)"
    ships 0
    remote_has "provision.sh up"
    remote_has_not "secrets-fetch"

    # --- (d) the tag alone ---------------------------------------------------
    # A tree file that keys nothing: not a migration, not the alert route, and
    # the registry's digests did not move with it. Ship, secrets, login and up
    # run because the box is holding the wrong tree; release does not, and it
    # names all three of the inputs it was asked about.
    fresh_world
    printf 'code v2\n' >"${REPO}/apps/core/services.py"
    commit_plant "ordinary code"
    stage "the_tag_alone" 0 ec2-user@box.invalid --env staging
    act_says "1/6" ship "ran: ${BOX_TAG} → tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    act_says "5/6" release "skipped: the migration leaves, deploy/observability/ and both image digests unchanged"
    ships 1
    remote_has "secrets-fetch"
    remote_has "provision.sh up"
    remote_has_not "release.sh"
    remote_has "readyz-prober"
}

case_a_docs_only_tree_deploys_nothing() {
    fresh_world
    # A MARKDOWN FILE AND NOT A `docs/` ONE, deliberately: the gate's
    # dangling-docs census reads every `docs/…` path a changed file spells and
    # requires it to exist in THIS tree, and a scratch world's path does not.
    printf 'note v2\n' >"${REPO}/notes.md"
    printf 'readme v2\n' >"${REPO}/README.md"
    commit_plant "docs only"
    stage "a_docs_only_tree" 0 ec2-user@box.invalid --env staging
    says "nothing to deploy — docs-only delta (2 path(s))"
    says_not "[1/6]"
    # ONE remote command, and it is the READ of the box's own marker. Zero
    # would be a script that decided without looking; two would be an act.
    local n
    n="$(remote_count)"
    if [ "$n" = "1" ] && grep -qF 'TREE' "$SSH_LOG"; then
        ok "the box was read once (its TREE marker) and acted on zero times"
    else
        bad "the box saw ${n} remote command(s): $(tr '\n' '|' <"$SSH_LOG")"
    fi
    ships 0
}

case_an_unknown_box_state_acts_nothing() {
    # --- no TREE marker ------------------------------------------------------
    fresh_world
    : >"${CASE_DIR}/box/TREE"
    printf 'code v2\n' >"${REPO}/apps/core/services.py"
    commit_plant "ordinary code"
    stage "no_tree_marker" 2 ec2-user@box.invalid --env staging
    says "!! stage: the box cannot say which tree it holds — ship first"
    says "Nothing was staged; no act ran."
    ships 0
    local n
    n="$(remote_count)"
    if [ "$n" = "1" ]; then
        ok "the box was read once and acted on zero times"
    else
        bad "the box saw ${n} remote command(s): $(tr '\n' '|' <"$SSH_LOG")"
    fi

    # --- the registry does not have this tree's image ------------------------
    fresh_world
    printf 'code v2\n' >"${REPO}/apps/core/services.py"
    commit_plant "ordinary code"
    # AN EMPTY DIGEST KNOB *IS* "the registry has no such tag": the stub exits
    # 2 the way the real `image-digest` does, and that refusal is the one
    # `release.sh` performs before its own act 1, reached here before the ship.
    DIGEST_WEB_NOW=""
    stage "the_registry_lacks_the_tag" 2 ec2-user@box.invalid --env staging
    unset DIGEST_WEB_NOW
    says "the registry does not have this tree's web image"
    says "THE BOX DOES NOT BUILD (ADR deploy-4)."
    # AND IT NAMES THE CAUSE THAT IS ACTUALLY FIRST NOW. The image is built by
    # the bank on its acceptance box (ADR deploy-4a); a refusal here that sent
    # the reader to look for a green CI run would send them to the machine that
    # did not build it. The two causes and the fallback are pinned, because
    # prose nobody asserts is prose that goes stale the next time the build
    # moves — which is exactly what happened to the sentence this replaces.
    says "THE BANK'S IMAGE STEP did"
    says "this box is pointed at the wrong registry."
    says "CI's images job is the fallback"
    says "Nothing was staged; no act ran."
    ships 0
}

case_a_second_stage_of_one_tree_is_readyz_only() {
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    stage "first_stage" 0 ec2-user@box.invalid --env staging
    # The box now holds this tree, released onto these digests — which is what
    # a real first stage leaves behind, and what the second one is keyed on.
    {
        printf 'tree-%s\n' "$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
        printf 'digest web %s\n' "$DIGEST_A"
        printf 'digest worker %s\n' "$DIGEST_B"
    } >"${CASE_DIR}/box/TREE"
    : >"$SSH_LOG"
    : >"$SHIP_LOG"
    stage "second_stage" 0 ec2-user@box.invalid --env staging
    act_says "1/6" ship "skipped: the tree tag (tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')) unchanged"
    act_says "5/6" release "skipped: the migration leaves, deploy/observability/ and both image digests unchanged"
    act_says "6/6" readyz "ran: HTTP 200"
    ships 0
    remote_has_not "release.sh"
    remote_has_not "provision.sh up"
    remote_has "readyz-prober"
}

case_the_registry_coordinate_is_derived_and_carried() {
    # THE COORDINATE IS IN NEITHER THE VAULT NOR THE ENV FILE, so `up` and
    # `release.sh` refuse on the box until it is in their environment. It is
    # derived here from `image-repo web` minus the repository name, and it has
    # to REACH both remote commands or the deploy refuses on the box with the
    # tree already shipped.
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    stage "the_coordinate_travels" 0 ec2-user@box.invalid --env staging
    says "registry     ${DRIVE_REGISTRY}"
    remote_has "DJB_IMAGE_REGISTRY='${DRIVE_REGISTRY}' ./deploy/provision.sh up"
    remote_has "DJB_IMAGE_REGISTRY='${DRIVE_REGISTRY}' ./deploy/release.sh"
    # AND THE LOGIN PRECEDES THE UP. The box's own role holds the pull grant,
    # so an `up` before the login pulls nothing and the order is the property.
    local login_at up_at
    login_at="$(grep -n 'docker login' "$SSH_LOG" | sed -n '1s/:.*//p')"
    up_at="$(grep -n 'provision.sh up' "$SSH_LOG" | sed -n '1s/:.*//p')"
    if [ -n "$login_at" ] && [ -n "$up_at" ] && [ "$login_at" -lt "$up_at" ]; then
        ok "the login is remote command ${login_at} and the up is ${up_at}"
    else
        bad "the login/up order does not hold (login ${login_at:-never}, up ${up_at:-never})"
    fi
    # The region is read off the host rather than named a second time.
    says "(ECR, region us-east-1)"
    remote_has "aws ecr get-login-password --region 'us-east-1'"
}

case_a_failed_act_stops_the_sequence_naming_itself() {
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    CURRENT="a_failed_up_stops_the_sequence"
    STAGE_OUT="${CASE_DIR}/failed_up.log"
    set +e
    (
        cd "$REPO" || exit 99
        PATH="${CASE_DIR}/bin:$PATH" \
            DJB_DRIVE_SSH_LOG="$SSH_LOG" \
            DJB_DRIVE_SHIP_LOG="$SHIP_LOG" \
            DJB_DRIVE_BOX_TREE="${CASE_DIR}/box/TREE" \
            DJB_DRIVE_BOX_LIVE="${CASE_DIR}/box/LIVE" \
            DJB_DRIVE_REGISTRY="$DRIVE_REGISTRY" \
            DJB_DRIVE_DIGEST_WEB="$DIGEST_A" \
            DJB_DRIVE_DIGEST_WORKER="$DIGEST_B" \
            DJB_DRIVE_UP_RC=3 \
            DJB_DEPLOY_NAMESPACE=drivens \
            ./deploy/stage.sh ec2-user@box.invalid --env staging
    ) >"$STAGE_OUT" 2>&1
    STAGE_EXIT=$?
    set -e
    if [ "$STAGE_EXIT" = "1" ]; then
        ok "a failed act is exit 1, never the 2 that means nothing was attempted"
    else
        bad "wanted exit 1 from a failed act, got ${STAGE_EXIT}"
    fi
    says "!! stage: STOPPED at act 4/6 — up (exit 3)."
    says "No act after this one ran."
    remote_has_not "release.sh"
    remote_has_not "readyz-prober"
}

case_it_refuses_a_piped_stdout_and_an_unknown_flag() {
    fresh_world
    CURRENT="a_piped_stdout"
    set +e
    (
        cd "$REPO" || exit 99
        PATH="${CASE_DIR}/bin:$PATH" DJB_DEPLOY_NAMESPACE=drivens CI="" \
            ./deploy/stage.sh ec2-user@box.invalid --env staging | cat
    ) >"${CASE_DIR}/piped.log" 2>&1
    set -e
    STAGE_OUT="${CASE_DIR}/piped.log"
    says "!! stage refuses pipes"
    says_not "stage: [1/6]"

    stage "an_unknown_flag" 2 ec2-user@box.invalid --env staging --force
    says "!! stage: unknown argument '--force'."

    stage "no_destination" 2 --env staging
    says "!! stage: no destination"

    stage "no_environment" 2 ec2-user@box.invalid
    says "no environment named"
}

case_a_dry_run_reads_the_box_and_touches_nothing() {
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    stage "a_dry_run" 0 ec2-user@box.invalid --env staging --dry-run
    says "WOULD RUN"
    says "DRY RUN — the box's TREE marker was read and nothing was touched."
    says_not " — ran"
    ships 0
    local n
    n="$(remote_count)"
    if [ "$n" = "1" ] && grep -qF 'TREE' "$SSH_LOG"; then
        ok "the box was read once (its TREE marker) and acted on zero times"
    else
        bad "the box saw ${n} remote command(s): $(tr '\n' '|' <"$SSH_LOG")"
    fi
}

case_the_docs_only_classes_are_the_classifiers_and_not_a_list() {
    # THE NEGATIVE OF THE SHORT CIRCUIT, and the reason it is not just "every
    # path is inert". `loop_scope__classify` answers `inert` for
    # `deploy/observability/` — it is asking whether a path can reach a Python
    # test — while that directory is the alerts act's whole input. A short
    # circuit written as "all inert" would report nothing to deploy for a tree
    # that moved the alert route, which is the one failure this drive is for.
    fresh_world
    printf 'route v2\n' >"${REPO}/deploy/observability/alerts/apply.py"
    commit_plant "an alert route, which is inert to the classifier"
    # shellcheck source=scripts/loop_tier.sh
    local shape
    shape="$(cd "$REPO" && . scripts/loop_tier.sh && loop_scope__classify deploy/observability/alerts/apply.py)"
    if [ "$shape" = "inert" ]; then
        ok "the classifier does call deploy/observability/ inert, so the negative is live"
    else
        bad "the classifier calls deploy/observability/ '${shape}', so this case is no longer the negative it was written as"
    fi
    stage "an_inert_path_that_keys_an_act" 0 ec2-user@box.invalid --env staging
    says_not "nothing to deploy"
    act_says "5/6" release "ran: alerts (deploy/observability/ moved)"
}

# =============================================================================
# The walls, and the promotion to prod
# =============================================================================

# The closing line, read back whole: `stage: <tag> live in <n>s (migrate <m>)`.
# The total is a wall clock and so a pattern; the migrate half is the release's
# own number, carried rather than re-measured, and so a literal.
closing_says() {
    local tag="$1" migrate="$2" line
    line="$(tail -n 1 "$STAGE_OUT")"
    # A HERE-STRING, NEVER `printf | grep -q`: under pipefail an early-exiting
    # reader can SIGPIPE its producer and turn a match into a failure.
    if grep -Eq "^stage: ${tag} live in [0-9]+s \\(migrate ${migrate}\\)\$" <<<"$line"; then
        ok "closes on \"${line}\""
    else
        bad "the last line is \"${line}\", not \"stage: ${tag} live in <n>s (migrate ${migrate})\""
    fi
}

case_the_closing_line_carries_both_walls() {
    # --- the release ran, and its transcript carried the migrate wall ---------
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    local tag
    tag="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    RELEASE_OUT_NOW="release: migrate: 42s"
    stage "the_closing_line_after_a_release" 0 ec2-user@box.invalid --env staging
    unset RELEASE_OUT_NOW
    closing_says "$tag" "42s"

    # --- no release ran: the migrate half says so, never a zero --------------
    fresh_world
    printf 'code v2\n' >"${REPO}/apps/core/services.py"
    commit_plant "ordinary code"
    tag="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    stage "the_closing_line_with_no_release" 0 ec2-user@box.invalid --env staging
    closing_says "$tag" "skipped"

    # --- the release ran and printed no wall: unmeasured, never invented ------
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    tag="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    RELEASE_OUT_NOW=""
    stage "the_closing_line_with_an_unmeasured_migrate" 0 ec2-user@box.invalid --env staging
    unset RELEASE_OUT_NOW
    closing_says "$tag" "unmeasured"
}

# The epoch → the leak-proof record's stamp. BSD `date -r` on the Mac, GNU
# `date -d @` on a box; the reader under drive does the same.
stamp_of() {
    date -u -r "$1" +%Y%m%dT%H%M%SZ 2>/dev/null || date -u -d "@$1" +%Y%m%dT%H%M%SZ
}

# A downloaded `nightly-leak-proof` artifact, as the prod job would hand it:
# `nightly_artifact <seconds ago> <rc>` writes `<case>/nightly/leak_proof.txt`.
nightly_artifact() {
    local ago="$1" rc="$2" at
    at="$(stamp_of "$(($(date -u +%s) - ago))")"
    mkdir -p "${CASE_DIR}/nightly"
    printf 'schema=leak-proof/1 at=%s commit=%s tree=%s seed=4242 pass1=ok pass2=ok map=written rc=%s run=7 attempt=1 where=nightly\n' \
        "$at" "$(printf 'c%.0s' $(seq 1 40))" "$(printf 'e%.0s' $(seq 1 40))" "$rc" >"${CASE_DIR}/nightly/leak_proof.txt"
}

# The staging box holds THIS tree (the case repo's HEAD), released.
staging_holds_this_tree() {
    {
        printf 'tree-%s\n' "$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
        printf 'digest web %s\n' "$DIGEST_A"
        printf 'digest worker %s\n' "$DIGEST_B"
    } >"${CASE_DIR}/staging/TREE"
    # …and PROVED it: the LIVE marker a stage writes only after its readyz.
    printf 'live tree-%s 20260927T120000Z\n' "$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')" >"${CASE_DIR}/staging/LIVE"
}

# A prod world whose four preconditions are ALL green: a migration to promote,
# staging holding this tree and answering 200, a nightly an hour old and green.
# Each refusal case below turns exactly one of them red.
prod_world() {
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    staging_holds_this_tree
    nightly_artifact 3600 0
}

SANCTION_OK="release-captain: promote the migration staging has served since this morning"

# NOTHING TOUCHED: the prod box saw no command at all, the ship never ran, and
# staging was only READ. The refusal is exit 2 before the prod box is contacted.
prod_untouched() {
    local n
    n="$(grep -c . "$SSH_LOG" || true)"
    if [ "$n" = "0" ]; then
        ok "the prod box was never contacted"
    else
        bad "the prod box saw ${n} remote command(s): $(tr '\n' '|' <"$SSH_LOG")"
    fi
    ships 0
    if grep -qvE "^cat .*/(TREE|LIVE)'$|readyz-prober" "$STAGING_SSH_LOG"; then
        bad "the staging box was asked something other than its markers and its readyz: $(tr '\n' '|' <"$STAGING_SSH_LOG")"
    else
        ok "the staging box was only read"
    fi
}

case_prod_refuses_without_a_sanction() {
    # THE BARE FORM IS THE ONE THAT MATTERS MOST: `--env prod` and nothing else
    # must not be a deploy to prod.
    prod_world
    stage "prod_bare" 2 ec2-user@prod.invalid --env prod
    says "!! stage: REFUSED — a promotion to prod"
    says "no sanction"
    prod_untouched

    # THE TEETH ARE NOT A SPELLING. Every environment that is not on the
    # declared non-prod list is prod, so a capital letter, a longer word or a
    # region suffix is refused exactly as `prod` is — never deployed bare.
    local spelling
    for spelling in PROD Production prod-eu; do
        prod_world
        stage "prod_bare_${spelling}" 2 ec2-user@prod.invalid --env "$spelling"
        says "!! stage: REFUSED — a promotion to prod"
        says "no sanction"
        prod_untouched
    done

    prod_world
    stage "prod_no_sanction" 2 ec2-user@prod.invalid --env prod \
        --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "no sanction"
    prod_untouched

    prod_world
    stage "prod_ill_formed_sanction" 2 ec2-user@prod.invalid --env prod \
        --sanction "ship it" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "the sanction 'ship it' is not '<who>: <why>'"
    prod_untouched

    # A sanction is ONE line a human typed: a control character in either half
    # (a newline smuggling a second line into the record, a tab, an escape) is
    # refused, and so is a reason that is only whitespace.
    local label bad_sanction
    for label in newline_in_reason newline_in_who tab_in_reason blank_reason blank_who; do
        case "$label" in
        newline_in_reason) bad_sanction=$'release-captain: promote\nand something else' ;;
        newline_in_who) bad_sanction=$'release\ncaptain: promote the staged tree' ;;
        tab_in_reason) bad_sanction=$'release-captain: promote\tthe staged tree' ;;
        blank_reason) bad_sanction='release-captain:    ' ;;
        blank_who) bad_sanction='   : promote the staged tree' ;;
        esac
        prod_world
        stage "prod_sanction_${label}" 2 ec2-user@prod.invalid --env prod \
            --sanction "$bad_sanction" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
        case "$label" in
        newline_in_reason | newline_in_who | tab_in_reason) says "the sanction carries a control character" ;;
        *) says "is not '<who>: <why>'" ;;
        esac
        prod_untouched
    done
}

case_prod_refuses_when_staging_is_not_this_tree() {
    prod_world
    local staged
    staged="$(sed -n 1p "${CASE_DIR}/staging/TREE")"
    # Staging holds the tree BEFORE this one: the promotion would ship bytes
    # nobody staged.
    printf 'code v2\n' >"${REPO}/apps/core/services.py"
    commit_plant "a tree staging never saw"
    local mine
    mine="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    stage "prod_staging_holds_another_tree" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "staging holds ${staged}, and this tree is ${mine}"
    prod_untouched

    prod_world
    : >"${CASE_DIR}/staging/TREE"
    : >"${CASE_DIR}/staging/LIVE"
    stage "prod_staging_has_no_marker" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "staging cannot say which tree it holds"
    prod_untouched

    prod_world
    stage "prod_no_staging_named" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --nightly "${CASE_DIR}/nightly"
    says "no staging box named"
    prod_untouched
}

case_prod_refuses_when_staging_does_not_answer() {
    prod_world
    STAGING_READYZ_NOW=503
    stage "prod_staging_readyz_503" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    unset STAGING_READYZ_NOW
    says "staging's readyz answered '503', not 200"
    prod_untouched
}

case_prod_refuses_every_nightly_that_is_not_green_and_fresh() {
    # --- red ------------------------------------------------------------------
    prod_world
    nightly_artifact 3600 1
    stage "prod_nightly_red" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "the nightly leak proof is RED (rc=1)"
    prod_untouched

    # --- older than 24 h ------------------------------------------------------
    prod_world
    nightly_artifact $((2 * 86400)) 0
    stage "prod_nightly_stale" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "the nightly leak proof is older than 24 h"
    prod_untouched

    # --- none: no artifact handed in ------------------------------------------
    prod_world
    stage "prod_nightly_none" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST"
    says "there is no nightly leak proof (nightly:none)"
    prod_untouched

    # --- unreadable: a directory that holds no record -------------------------
    prod_world
    rm -f "${CASE_DIR}/nightly/leak_proof.txt"
    stage "prod_nightly_unreadable" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "the nightly leak proof is unreadable"
    says "holds no leak_proof.txt"
    prod_untouched
}

case_prod_names_every_red_precondition_at_once() {
    # One run, four causes: an operator fixes them all in one pass rather than
    # discovering them one refusal at a time.
    prod_world
    : >"${CASE_DIR}/staging/TREE"
    : >"${CASE_DIR}/staging/LIVE"
    STAGING_READYZ_NOW=502
    stage "prod_four_red" 2 ec2-user@prod.invalid --env prod --staging "$STAGING_DEST"
    unset STAGING_READYZ_NOW
    says "no sanction"
    says "staging cannot say which tree it holds"
    says "staging's readyz answered '502', not 200"
    says "there is no nightly leak proof (nightly:none)"
    says "4 of 4 preconditions are red"
    prod_untouched
}

case_prod_proceeds_when_all_four_are_green() {
    prod_world
    local tag
    tag="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    stage "prod_all_green" 0 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "stage: prod gate  sanction  ${SANCTION_OK}"
    says "stage: prod gate  staging   ${tag} on ${STAGING_DEST}, readyz 200"
    says "stage: prod gate  nightly   nightly:"
    act_says "5/6" release "ran: migrate+grants (a migration leaf moved)"
    remote_has "release.sh"
    ships 1
    closing_says "$tag" "7s"
}

case_prod_reads_what_staging_proved_not_what_it_shipped() {
    # STAGING'S TREE LINE 1 IS WRITTEN AT ACT 1, before pull, migrate, swap and
    # readyz. So mid-deploy — or after a deploy that failed past act 1 — TREE
    # names the new tree while the OLD containers still answer 200, and a tooth
    # reading TREE would promote a tree staging never proved. The tooth reads
    # the LIVE marker, which only a stage whose readyz answered 200 writes.
    local mine older
    # --- mid-act: TREE already says this tree, no LIVE marker yet -------------
    prod_world
    : >"${CASE_DIR}/staging/LIVE"
    stage "prod_staging_mid_deploy" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "staging cannot say which tree it holds live"
    prod_untouched

    # --- TREE says this tree; LIVE still names the tree before it --------------
    prod_world
    older="$BOX_TAG"
    printf 'live %s 20260927T100000Z\n' "$older" >"${CASE_DIR}/staging/LIVE"
    mine="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    stage "prod_staging_shipped_but_never_proved" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "staging holds ${older}, and this tree is ${mine}"
    prod_untouched

    # --- a marker that is not `live <tag> …` is not a proof --------------------
    prod_world
    printf 'garbage\n' >"${CASE_DIR}/staging/LIVE"
    stage "prod_staging_live_unparseable" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "staging cannot say which tree it holds live"
    prod_untouched
}

case_a_stage_withdraws_live_before_acting_and_writes_it_after_readyz() {
    # THE WRITER'S HALF, driven through real stages of one box, and then handed
    # to prod as the staging it would read.
    local mine rm_at first_act live_at readyz_at
    # --- a stage that FAILS past act 1 leaves no LIVE marker -------------------
    fresh_world
    printf 'live %s 20260927T090000Z\n' "$BOX_TAG" >"${CASE_DIR}/box/LIVE"
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    mine="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    UP_RC_NOW=3
    stage "staging_fails_at_up" 1 ec2-user@box.invalid --env staging
    unset UP_RC_NOW
    says "!! stage: STOPPED at act 4/6 — up (exit 3)."
    remote_has "rm -f 'drivens/LIVE'"
    if [ -e "${CASE_DIR}/box/LIVE" ]; then
        bad "the failed stage left a LIVE marker: $(cat "${CASE_DIR}/box/LIVE")"
    else
        ok "the failed stage left no LIVE marker"
    fi
    rm_at="$(grep -n "rm -f 'drivens/LIVE'" "$SSH_LOG" | sed -n '1s/:.*//p' || true)"
    first_act="$(grep -n 'secrets-fetch' "$SSH_LOG" | sed -n '1s/:.*//p' || true)"
    if [ -n "$rm_at" ] && [ -n "$first_act" ] && [ "$rm_at" -lt "$first_act" ] &&
        [ "$(grep -c . "$SHIP_LOG" || true)" = "1" ]; then
        ok "the marker was withdrawn (remote ${rm_at}) before the acts that change the box (first on the box: ${first_act})"
    else
        bad "the marker was not withdrawn before the acts (rm ${rm_at:-never}, first act ${first_act:-never})"
    fi
    # …and a promotion reading that staging (the ship ran, so TREE says this
    # tree; the old containers still answer 200) is REFUSED.
    printf '%s\n' "$mine" >"${CASE_DIR}/staging/TREE"
    : >"${CASE_DIR}/staging/LIVE"
    nightly_artifact 3600 0
    : >"$SSH_LOG"
    : >"$SHIP_LOG"
    stage "prod_after_a_failed_staging_deploy" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "staging cannot say which tree it holds live"
    prod_untouched

    # --- a stage whose readyz answers writes `live <this tag> <stamp>` ----------
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    mine="tree-$(git -C "$REPO" rev-parse --short=12 'HEAD^{tree}')"
    stage "staging_goes_live" 0 ec2-user@box.invalid --env staging
    if grep -qE "^live ${mine} [0-9]{8}T[0-9]{6}Z$" "${CASE_DIR}/box/LIVE" 2>/dev/null; then
        ok "the LIVE marker names this tree: $(cat "${CASE_DIR}/box/LIVE")"
    else
        bad "no 'live ${mine} <stamp>' marker after a green stage (got: $(cat "${CASE_DIR}/box/LIVE" 2>/dev/null || echo absent))"
    fi
    live_at="$(grep -n "^echo 'live " "$SSH_LOG" | sed -n '1s/:.*//p' || true)"
    readyz_at="$(grep -n 'readyz-prober' "$SSH_LOG" | sed -n '$s/:.*//p' || true)"
    if [ -n "$live_at" ] && [ -n "$readyz_at" ] && [ "$live_at" -gt "$readyz_at" ]; then
        ok "the marker was written (remote ${live_at}) after the readyz answered (remote ${readyz_at})"
    else
        bad "the marker was not written after the readyz (live ${live_at:-never}, readyz ${readyz_at:-never})"
    fi
    # …and THAT staging promotes.
    staging_holds_this_tree
    cp "${CASE_DIR}/box/LIVE" "${CASE_DIR}/staging/LIVE"
    nightly_artifact 3600 0
    : >"$SSH_LOG"
    : >"$SHIP_LOG"
    stage "prod_after_a_green_staging_deploy" 0 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    says "stage: prod gate  staging   ${mine} on ${STAGING_DEST}, readyz 200"

    # --- a readyz that does not answer 200 writes nothing ----------------------
    fresh_world
    printf 'second\n' >"${REPO}/apps/core/migrations/0002_more.py"
    commit_plant "a migration"
    CURRENT="a_readyz_503_writes_no_live"
    STAGE_OUT="${CASE_DIR}/readyz_503.log"
    set +e
    (
        cd "$REPO" || exit 99
        PATH="${CASE_DIR}/bin:$PATH" DJB_DRIVE_SSH_LOG="$SSH_LOG" DJB_DRIVE_SHIP_LOG="$SHIP_LOG" \
            DJB_DRIVE_BOX_TREE="${CASE_DIR}/box/TREE" DJB_DRIVE_BOX_LIVE="${CASE_DIR}/box/LIVE" \
            DJB_DRIVE_REGISTRY="$DRIVE_REGISTRY" DJB_DRIVE_DIGEST_WEB="$DIGEST_A" \
            DJB_DRIVE_DIGEST_WORKER="$DIGEST_B" DJB_DRIVE_READYZ_CODE=503 DJB_DEPLOY_NAMESPACE=drivens \
            ./deploy/stage.sh ec2-user@box.invalid --env staging
    ) >"$STAGE_OUT" 2>&1
    STAGE_EXIT=$?
    set -e
    if [ "$STAGE_EXIT" = "1" ]; then ok "a readyz of 503 is exit 1"; else bad "a readyz of 503 exited ${STAGE_EXIT}, wanted 1"; fi
    if [ -e "${CASE_DIR}/box/LIVE" ]; then bad "a readyz of 503 left a LIVE marker"; else ok "a readyz of 503 left no LIVE marker"; fi
}

case_prod_refuses_a_tree_the_registry_does_not_hold() {
    # THE TAG IS THE RECORD (ADR deploy-4 (b)): CI tags no tree its gate did not
    # pass, so a tree with no digest in the registry is a tree no green verdict
    # vouches for — refused at exit 2 with all four teeth green, before any act,
    # the prod box read (its TREE marker) and never acted on.
    local n
    prod_world
    DIGEST_WEB_NOW=""
    stage "prod_tree_not_in_the_registry" 2 ec2-user@prod.invalid --env prod \
        --sanction "$SANCTION_OK" --staging "$STAGING_DEST" --nightly "${CASE_DIR}/nightly"
    unset DIGEST_WEB_NOW
    says "stage: prod gate  sanction  ${SANCTION_OK}"
    says "!! stage: REFUSED — the registry does not have this tree's web image"
    ships 0
    n="$(remote_count)"
    if [ "$n" = "1" ] && grep -qE "^cat .*/TREE'$" "$SSH_LOG"; then
        ok "the prod box was read once (its TREE marker) and acted on zero times"
    else
        bad "the prod box saw ${n} remote command(s): $(tr '\n' '|' <"$SSH_LOG")"
    fi
}

case_the_prod_flags_mean_nothing_outside_prod() {
    # The non-prod list is declared, and an environment on it is staged without
    # the gate — the negative that keeps the inverted rule honest.
    fresh_world
    printf 'code v2\n' >"${REPO}/apps/core/services.py"
    commit_plant "ordinary code"
    stage "dev_is_on_the_non_prod_list" 0 ec2-user@box.invalid --env dev
    says_not "prod gate"
    says_not "REFUSED"

    fresh_world
    stage "a_sanction_on_staging" 2 ec2-user@box.invalid --env staging --sanction "$SANCTION_OK"
    says "--sanction, --staging and --nightly are the prod gate's and mean nothing for --env staging"
    ships 0
}

# --- run ----------------------------------------------------------------------

case_each_act_is_keyed_on_its_own_input
case_a_docs_only_tree_deploys_nothing
case_an_unknown_box_state_acts_nothing
case_a_second_stage_of_one_tree_is_readyz_only
case_the_registry_coordinate_is_derived_and_carried
case_a_failed_act_stops_the_sequence_naming_itself
case_it_refuses_a_piped_stdout_and_an_unknown_flag
case_a_dry_run_reads_the_box_and_touches_nothing
case_the_docs_only_classes_are_the_classifiers_and_not_a_list
case_the_closing_line_carries_both_walls
case_prod_refuses_without_a_sanction
case_prod_refuses_when_staging_is_not_this_tree
case_prod_refuses_when_staging_does_not_answer
case_prod_refuses_every_nightly_that_is_not_green_and_fresh
case_prod_names_every_red_precondition_at_once
case_prod_proceeds_when_all_four_are_green
case_prod_reads_what_staging_proved_not_what_it_shipped
case_a_stage_withdraws_live_before_acting_and_writes_it_after_readyz
case_prod_refuses_a_tree_the_registry_does_not_hold
case_the_prod_flags_mean_nothing_outside_prod

echo "test_stage: ${PASSED} passed · ${FAILED} failed"
drive_finished
if [ "$FAILED" -gt 0 ]; then
    echo "!! a keyed deploy fails in the one direction nothing notices: an act that" >&2
    echo "   skips when its input moved. The transcript still prints six acts and the" >&2
    echo "   exit status is still 0, while the box serves old code, an unmigrated" >&2
    echo "   schema or an alert route reconciled to some other tree." >&2
    exit 1
fi
exit 0
