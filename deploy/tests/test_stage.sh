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
# drives: deploy/stage.sh deploy/release.sh deploy/ship.sh deploy/provision.sh scripts/loop_tier.sh scripts/gate_refuse.sh
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

ROOT="$PWD"
SOURCE="$ROOT/deploy/stage.sh"
CLASSIFIER="$ROOT/scripts/loop_tier.sh"
# `loop_tier.sh` sources the refusal seam beside itself, so the scratch world
# carries that too: copying one half of a library pair is a world that dies on
# a missing file rather than the world under drive.
REFUSE_SEAM="$ROOT/scripts/gate_refuse.sh"

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
    mkdir -p "${REPO}/deploy/observability/alerts" "${REPO}/apps/core/migrations" \
        "${REPO}/scripts" "${CASE_DIR}/bin" "${CASE_DIR}/box"
    # Created empty, so "nothing was sent to the box" is an empty file rather
    # than a missing one: an absent file and zero invocations read the same to
    # `wc`, and only one of them is the property being asserted.
    : >"$SSH_LOG"
    : >"$SHIP_LOG"

    cp "$SOURCE" "${REPO}/deploy/stage.sh"
    chmod +x "${REPO}/deploy/stage.sh"
    cp "$CLASSIFIER" "${REPO}/scripts/loop_tier.sh"
    cp "$REFUSE_SEAM" "${REPO}/scripts/gate_refuse.sh"

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
    cat >"${CASE_DIR}/bin/ssh" <<'SSH'
#!/usr/bin/env bash
# The last argument is the remote command; everything before it is ssh's own.
cmd="${!#}"
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
*secrets-fetch*) exit "${DJB_DRIVE_SECRETS_RC:-0}" ;;
*"docker login"*) exit "${DJB_DRIVE_LOGIN_RC:-0}" ;;
*provision.sh\ up*) exit "${DJB_DRIVE_UP_RC:-0}" ;;
*release.sh*) exit "${DJB_DRIVE_RELEASE_RC:-0}" ;;
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
