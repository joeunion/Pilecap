#!/usr/bin/env bash
# From a green tree to a healthy stage box, with every act keyed on its input.
#
#   deploy/stage.sh ec2-user@1.2.3.4 --env staging               stage HEAD
#   deploy/stage.sh ec2-user@1.2.3.4 --env staging --key ~/k.pem with an identity file
#   deploy/stage.sh ec2-user@1.2.3.4 --env staging --dry-run     say what would run, touch nothing
#
# WHY THIS EXISTS. A deploy to the stage box was five hand-typed commands in
# three runbook parts — `ship.sh`, runbook step 31, a registry login, step 34's
# `provision.sh up`, then `release.sh` — walked by hand and timed. Each one of
# them is already a script that owns its exit status, so what was missing was
# never the acts; it was ALL OF THEM, IN ORDER, KEYED. Two costs, both measured
# on that walk:
#
#   * THE ORDER IS KNOWLEDGE NOBODY WROTE DOWN. `ship.sh` deliberately does not
#     carry `deploy/.env`, so step 31 has to run on EVERY deploy and before
#     `up`; `DJB_IMAGE_REGISTRY` is in neither the vault's environment nor the
#     env file, so `up` and `release.sh` refuse until it is exported; and the
#     box's instance role holds the ECR pull grant, so `docker login` has to
#     precede `up` or the pull fails against a registry the box is entitled to.
#     Every one of those three was discovered by watching a refusal.
#   * AN IDEMPOTENT SEQUENCE IS A SKIPPABLE SEQUENCE — `release.sh`'s own
#     argument, one level up. Running all of it every time is safe and slow;
#     running some of it from memory is fast and silently wrong. So each act
#     here NAMES ITS INPUT and runs when that input moved, which is the only
#     form in which "we skipped it" is a fact rather than a hope.
#
# THE EXIT STATUS IS THE VERDICT, and it is this repository's three:
#
#   0   every act that needed to run ran, and the deployment answers. A tree
#       with nothing to deploy is also 0 — see the docs-only short circuit.
#   1   an act RAN AND FAILED. The act is named, nothing after it ran, and the
#       box is in whatever state that act left. The recovery is the from-the-top
#       tool: `deploy/release.sh` on the box, which is idempotent by design.
#   2   refused before anything was touched, or could not look — a piped
#       stdout, an unknown flag, a dirty tree, a box with no `TREE` marker, a
#       registry that does not have this tree's image, an input that could not
#       be read.
#
# THE ACTS AND THEIR KEYS. Read the box's `TREE` marker (line 1 is the tree tag,
# `digest <service> <sha256:…>` lines are what it last RELEASED) and this
# checkout's own tree, and key each act on the input it is about:
#
#   ship      the tree tag moved                    deploy/ship.sh
#   secrets   the ship ran (the tree it landed carries no deploy/.env)
#   login     the up will run (the pull grant is the box's own role's)
#   up        the tree tag moved, or the image digest moved
#   release   a migration leaf moved, deploy/observability/ moved, or the
#             image digest moved — i.e. any of release.sh's migrate+grants,
#             alerts and recreate inputs. `--without-alerts` is passed when
#             deploy/observability/ did NOT move, which is the one act of
#             release.sh's seven that this script can key from outside it.
#   readyz    always
#
# WHAT THIS DELIBERATELY DOES NOT DO, declared rather than discovered:
#
#   * IT DOES NOT KEY `release.sh`'s SEVEN ACTS INDIVIDUALLY, and it cannot.
#     `release.sh` takes `--dry-run` and `--without-alerts` and nothing else:
#     there is no `--only migrate`, and inventing one here would be a second
#     implementation of acts that already exist. So `release` is ONE act of
#     this script's six, its key is the UNION of the three inputs its sub-acts
#     are keyed on, and the line it prints NAMES which of them moved. Splitting
#     it further is a change to `release.sh`, not to this file.
#   * IT DOES NOT BUILD. The box does not build (ADR deploy-4): the image for a
#     tree is built ONCE, by the bank on its acceptance box from the tree its
#     own composed verdict just passed (ADR deploy-4a), and pushed under the
#     tree tag; CI's `images` job builds only a tag the registry lacks. A
#     registry that does not have it is a refusal here, before anything is
#     shipped.
#   * IT DOES NOT ROLL BACK. That is `deploy/ship.sh --ref <sha>` followed by a
#     release, and the runbook says so.
#   * IT DOES NOT DECIDE WHETHER THE TREE SHOULD BE STAGED. The PM's judgement.
#   * IT DOES NOT ROTATE SECRETS. The secrets act FETCHES what the vault holds.
#   * IT SEES A MIGRATION LEAF, NOT A MIGRATION'S BYTES. `django-linear-migrations`
#     refuses two leaves per app upstream, so a migration whose file changed
#     without the leaf moving is a state the tree cannot reach.
#
# THE DOCS-ONLY SHORT CIRCUIT, AND WHY IT IS NOT JUST "EVERY PATH IS INERT".
# The class list is `loop_scope__classify`'s (scripts/loop_tier.sh) — sourced
# and CALLED, never copied, so a territory added there is known here the day it
# is added. But `inert` is an answer to "can this path reach a Python test",
# and `deploy/observability/` is inert under that question while being the
# alerts act's whole input. So a delta is docs-only here when every path is
# inert AND no act's own input moved; the two halves together, or a deploy that
# moved the alert route would report nothing to deploy.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/.." && pwd)"
set +x  # never; see deploy/entrypoint.sh for the same line and the same reason

# --- it refuses to be piped ---------------------------------------------------
# release.sh's detection and release.sh's CI exemption, deliberately identical
# (deploy/release.sh:92-98, deploy/ship.sh:70-76). A pipe replaces this script's
# exit status with the filter's, and the exit status is the difference between
# "the box is serving this tree" and "some of the acts ran".
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! stage refuses pipes — a filter replaces the exit status of the stage with" >&2
    echo "   the filter's, and the exit status is the whole verdict. Run it" >&2
    echo "   bare or redirect to a file." >&2
    exit 2
fi

die() {
    # 2 is "could not get as far as staging", or "could not look". An act never
    # attempted must never share an exit code with an act that ran and failed.
    echo "!! stage: $*" >&2
    echo "   Nothing was staged; no act ran." >&2
    exit 2
}

say() { echo "stage: $*"; }

usage() {
    sed -n '2,6p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo ""
    echo "The header of ${BASH_SOURCE[0]} says what each act is and what keys it."
    exit 2
}

DESTINATION=""
KEY=""
# The landing directory and the vault prefix are configuration and neither is
# guessed — `deploy/ship.sh`'s grammar, for `deploy/ship.sh`'s reason: this
# script's acts `rm -rf` a staging area and write an environment file, and both
# are destructive in a directory this deployment may not own.
REMOTE_DIR="${DJB_DEPLOY_NAMESPACE:-}"
ENVIRONMENT="${DJB_DEPLOY_ENVIRONMENT:-}"
DRY_RUN=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    -h | --help)
        sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    --key)
        [ "$#" -ge 2 ] || die "--key needs a path"
        KEY="$2"
        shift 2
        ;;
    --dest)
        [ "$#" -ge 2 ] || die "--dest needs a path"
        REMOTE_DIR="$2"
        shift 2
        ;;
    --env)
        [ "$#" -ge 2 ] || die "--env needs an environment name"
        ENVIRONMENT="$2"
        shift 2
        ;;
    --dry-run)
        DRY_RUN=1
        shift
        ;;
    -*)
        echo "!! stage: unknown argument '$1'." >&2
        echo "" >&2
        usage
        ;;
    *)
        [ -z "$DESTINATION" ] || die "two destinations named ('$DESTINATION' and '$1'); this stages to one box"
        DESTINATION="$1"
        shift
        ;;
    esac
done

[ -n "$DESTINATION" ] || {
    echo "!! stage: no destination — name the box, e.g. ec2-user@1.2.3.4" >&2
    echo "" >&2
    usage
}

# --- the preconditions, all of them before anything is contacted --------------
command -v git >/dev/null 2>&1 || die "no 'git' on PATH"
command -v ssh >/dev/null 2>&1 || die "no 'ssh' on PATH"
[ -x "$HERE/provision.sh" ] || die "no $HERE/provision.sh — every coordinate below is one of its functions and this script owns no second copy"
[ -x "$HERE/ship.sh" ] || die "no $HERE/ship.sh — the ship act has nothing to call"
[ -n "$REMOTE_DIR" ] || die "DJB_DEPLOY_NAMESPACE is required — this deployment's namespace, the directory the tree lives in on the box. There is no default: a guessed namespace acts in somebody else's directory. Export it, or name the directory outright with --dest."
[ -n "$ENVIRONMENT" ] || die "no environment named — the vault prefix is \"<namespace>/<environment>/\" and there is no default, because a default is how one environment's secrets get written onto another environment's box. Pass --env <name>, or export DJB_DEPLOY_ENVIRONMENT."
[ -z "$KEY" ] || [ -f "$KEY" ] || die "no identity file at $KEY"
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout, so there is no tree to stage and nothing that could name one"

# THE CLASSIFIER IS SOURCED, NOT COPIED. `loop_scope__classify` is the one
# function in this repository that answers "what kind of territory is this
# path", and the docs-only short circuit below is a question about exactly
# that. A hand list here would be right the day it was written.
# NOT SILENCED. An earlier draft sourced it under `2>/dev/null` and a missing
# sibling library died with no message at all: the one thing a refusal must
# never do is refuse quietly.
# shellcheck source=scripts/loop_tier.sh
. "$ROOT/scripts/loop_tier.sh" ||
    die "could not source $ROOT/scripts/loop_tier.sh (its own error is above) — the docs-only short circuit is its classifier's answer and this script keeps no second list"
command -v loop_scope__classify >/dev/null 2>&1 ||
    die "$ROOT/scripts/loop_tier.sh defines no loop_scope__classify — the territory classes this script re-derives are gone from where they live"

# --- THIS TREE ----------------------------------------------------------------
TREE_TAG="$("$HERE/provision.sh" image-tag)" || exit 2
case "$TREE_TAG" in
untracked | "")
    die "the image tag reads '${TREE_TAG:-<empty>}' — this checkout cannot say which tree it is, so nothing here can say which image to stage"
    ;;
*-dirty)
    echo "!! stage: this checkout is dirty, so the tag would be '$TREE_TAG' while the" >&2
    echo "   ship carries the COMMITTED tree — the box would hold clean bytes under a" >&2
    echo "   name that says otherwise, and every key below is derived from that name." >&2
    echo "   Commit the change, then stage." >&2
    echo "   Nothing was staged; no act ran." >&2
    exit 2
    ;;
esac
HEAD_TREE="$(git -C "$ROOT" rev-parse --verify 'HEAD^{tree}')" || die "could not read this checkout's HEAD tree"

# --- THE REGISTRY COORDINATE, DERIVED AND THEN CARRIED ------------------------
# `DJB_IMAGE_REGISTRY` is in neither the vault's environment nor the env file
# `secrets-fetch` writes, so `provision.sh up` and `release.sh` both refuse on
# the box until it is in their environment — measured, twice, on the hand walk.
# It is derived HERE, on the deployer's side, from the one function that owns
# the composition: `image-repo <service>` prints `<registry>/djb-<service>`, so
# the registry is that answer minus the repository name. Deriving it rather
# than accepting a second slot keeps one source; carrying it to the box rather
# than writing it into a file keeps the coordinate out of the tree.
IMAGE_REPO_WEB="$("$HERE/provision.sh" image-repo web)" || exit 2
IMAGE_REGISTRY="${IMAGE_REPO_WEB%/djb-web}"
[ "$IMAGE_REGISTRY" != "$IMAGE_REPO_WEB" ] ||
    die "could not read a registry out of 'provision.sh image-repo web', which answered '$IMAGE_REPO_WEB' — the composition it performs is '<registry>/djb-<service>' and this derivation is its inverse. A guessed registry pulls somebody else's image and succeeds."

# The region is read off the registry host rather than named again: an ECR host
# is `<account>.dkr.ecr.<region>.amazonaws.com`. A registry that is not an ECR
# host needs no `get-login-password` and the login act says so instead of
# guessing a cloud.
REGISTRY_HOST="${IMAGE_REGISTRY%%/*}"
REGISTRY_REGION="$(printf '%s' "$REGISTRY_HOST" | sed -n 's/^[0-9][0-9]*\.dkr\.ecr\.\([a-z0-9-][a-z0-9-]*\)\.amazonaws\.com$/\1/p')"

# --- THE BOX'S TREE, READ BEFORE ANYTHING IS DECIDED --------------------------
SSH_ARGS=()
[ -z "$KEY" ] || SSH_ARGS+=(-i "$KEY")

remote() {
    ssh ${SSH_ARGS[@]+"${SSH_ARGS[@]}"} "$DESTINATION" "$1"
}

say "destination  ${DESTINATION}"
say "namespace    ${REMOTE_DIR}  (environment ${ENVIRONMENT}; vault prefix ${REMOTE_DIR}/${ENVIRONMENT}/)"
say "tree         HEAD → ${TREE_TAG}"
say "registry     ${IMAGE_REGISTRY}${REGISTRY_REGION:+  (ECR, region ${REGISTRY_REGION})}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-stage.XXXXXX")" || die "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT
MARKER="$WORK/TREE"

set +e
remote "cat '${REMOTE_DIR}/TREE'" >"$MARKER" 2>"$WORK/marker.err"
marker_rc=$?
set -e
if [ "$marker_rc" != "0" ] || [ ! -s "$MARKER" ]; then
    echo "!! stage: the box cannot say which tree it holds — ship first" >&2
    sed 's/^/   /' "$WORK/marker.err" >&2 || true
    echo "   ${REMOTE_DIR}/TREE is what every key below is measured against: the tag on" >&2
    echo "   line 1 is the tree the box is holding and the 'digest <service> <sha>'" >&2
    echo "   lines are what it last RELEASED. Without it, 'unchanged' and 'never" >&2
    echo "   deployed' are the same sentence, and this script will not guess which." >&2
    echo "       ./deploy/ship.sh ${DESTINATION}${KEY:+ --key ${KEY}}" >&2
    echo "   writes it. Nothing was staged; no act ran." >&2
    exit 2
fi

BOX_TAG="$(sed -n '1p' "$MARKER" | tr -d ' \t\r')"
case "$BOX_TAG" in
tree-*) ;;
*) die "the box's TREE marker opens with '${BOX_TAG:-<empty>}', which is not a 'tree-<sha>' tag. An act's input could not be read, so no act ran." ;;
esac
box_digest() { awk -v svc="$1" '$1 == "digest" && $2 == svc { print $3; exit }' "$MARKER"; }

BOX_TREE_SHA="${BOX_TAG#tree-}"
if ! git -C "$ROOT" rev-parse --verify --quiet "${BOX_TREE_SHA}^{tree}" >/dev/null; then
    die "the box holds ${BOX_TAG}, and this checkout has no such tree object — so the delta that keys every act below cannot be computed. Fetch the tree the box is holding, or re-ship. An act's input could not be read."
fi

# --- THE DELTA, AND THE KEYS IT DECIDES ---------------------------------------
DELTA="$WORK/delta"
git -C "$ROOT" diff --name-only "$BOX_TREE_SHA" "$HEAD_TREE" >"$DELTA" ||
    die "could not diff the box's tree against this one; an act's input could not be read"
DELTA_COUNT="$(grep -c . "$DELTA" || true)"

paths_under() { grep -E "$1" "$DELTA" >/dev/null 2>&1; }

TAG_MOVED=""
[ "$BOX_TAG" = "$TREE_TAG" ] || TAG_MOVED=1

MIGRATIONS_MOVED=""
paths_under '^apps/[^/]+/migrations/' && MIGRATIONS_MOVED=1 || true

OBSERVABILITY_MOVED=""
paths_under '^deploy/observability/' && OBSERVABILITY_MOVED=1 || true

# THE DIGEST, ASKED OF THE REGISTRY AND COMPARED WITH WHAT THE BOX PINNED.
# `image-digest` exits 2 when the registry does not have the tag, and that is
# the refusal `release.sh` performs before its own act 1 for the same reason:
# the box does not build, so there is nothing to fall back to and "no act ran"
# is still true here.
DIGEST_MOVED=""
DIGEST_REPORT=""
for stage_service in web worker; do
    set +e
    registry_digest="$("$HERE/provision.sh" image-digest "$stage_service" "$TREE_TAG" 2>&1)"
    digest_rc=$?
    set -e
    if [ "$digest_rc" != "0" ]; then
        echo "!! stage: REFUSED — the registry does not have this tree's ${stage_service} image" >&2
        printf '   %s\n' "$registry_digest" >&2
        echo "" >&2
        echo "   THE BOX DOES NOT BUILD (ADR deploy-4). The image for a tree is built" >&2
        echo "   ONCE, by the bank on its acceptance box from the tree its own composed" >&2
        echo "   verdict just passed (ADR deploy-4a), and pushed under the tree tag;" >&2
        echo "   there is nothing here to fall back to. Either THE BANK'S IMAGE STEP did" >&2
        echo "   not produce it — it never ran (no DJB_IMAGE_REGISTRY where the bank was" >&2
        echo "   typed) or its build or push was refused, and the bank's own log says" >&2
        echo "   'image: ...' either way — or this box is pointed at the wrong registry." >&2
        echo "   CI's images job is the fallback: it builds a tag the registry lacks, so" >&2
        echo "   a push of this tree to the forge produces one without anybody's hand." >&2
        echo "" >&2
        echo "   AND THERE IS A THIRD CAUSE THAT READS EXACTLY LIKE THE FIRST TWO: a" >&2
        echo "   registry that will not talk to THIS machine. A laptop with no ECR" >&2
        echo "   credential gets '403 Forbidden' on the manifest HEAD, and 'no such tag'" >&2
        echo "   and 'you are not logged in' are the same sentence to the reader above." >&2
        echo "   The box's own login (act 3) is the box's; this query is yours:" >&2
        echo "       aws ecr get-login-password --region ${REGISTRY_REGION:-<region>} \\" >&2
        echo "         | docker login --username AWS --password-stdin ${REGISTRY_HOST}" >&2
        echo "   Nothing was staged; no act ran." >&2
        exit 2
    fi
    pinned="$(box_digest "$stage_service")"
    if [ "$pinned" != "$registry_digest" ]; then
        DIGEST_MOVED=1
        DIGEST_REPORT="${DIGEST_REPORT}${DIGEST_REPORT:+, }${stage_service}"
    fi
done

# --- THE DOCS-ONLY SHORT CIRCUIT ----------------------------------------------
if [ "$DELTA_COUNT" -gt 0 ] && [ -z "$MIGRATIONS_MOVED" ] && [ -z "$OBSERVABILITY_MOVED" ] && [ -z "$DIGEST_MOVED" ]; then
    all_inert=1
    while IFS= read -r delta_path; do
        [ -n "$delta_path" ] || continue
        shape="$(loop_scope__classify "$delta_path")" || {
            echo "!! stage: '${delta_path}' is in the delta and scripts/loop_tier.sh's" >&2
            echo "   loop_scope__classify cannot say what territory it is. A path nothing" >&2
            echo "   can classify is an act's input that could not be read, and the" >&2
            echo "   answer is a new class THERE, not a guess here." >&2
            echo "   Nothing was staged; no act ran." >&2
            exit 2
        }
        [ "$shape" = "inert" ] || { all_inert=""; break; }
    done <"$DELTA"
    if [ -n "$all_inert" ]; then
        say "nothing to deploy — docs-only delta (${DELTA_COUNT} path(s))"
        say "the box holds ${BOX_TAG} and every path that moved since it is inert; no act"
        say "keys on any of them, so the box was not touched."
        exit 0
    fi
fi

# --- THE ACTS -----------------------------------------------------------------
# Named once and counted from the list, `release.sh`'s form and its reason: a
# seventh act added below without a name here would print `[7/6]`.
ACTS=(
    "ship — this tree onto the box, verified against the archive's own manifest"
    "secrets — deploy/.env from the vault, with the group the containers read it as"
    "login — the registry, as the box's own instance role"
    "up — the organs, the tag adoption and the pull"
    "release — integrations, migrate, grants, alerts, recreate, readyz"
    "readyz — the deployment answers"
)
TOTAL="${#ACTS[@]}"
ACT_INDEX=0
ACT_NAME=""
ACT_T0=0

act_begin() {
    ACT_INDEX=$((ACT_INDEX + 1))
    ACT_NAME="${ACTS[$((ACT_INDEX - 1))]%% —*}"
    ACT_T0="$(date +%s)"
}

act_ran() {
    echo "stage: [${ACT_INDEX}/${TOTAL}] ${ACT_NAME} — ran${1:+: $1} ($(($(date +%s) - ACT_T0))s)"
}

act_skipped() {
    echo "stage: [${ACT_INDEX}/${TOTAL}] ${ACT_NAME} — skipped: $1 unchanged ($(($(date +%s) - ACT_T0))s)"
}

act_would() {
    echo "stage: [${ACT_INDEX}/${TOTAL}] ${ACT_NAME} — WOULD RUN${1:+: $1}"
}

# The one failure path, `release.sh`'s shape and its sentence: whatever stopped,
# the reader gets the same paragraph and it always names the act.
stopped() {
    local status="$1"
    echo "" >&2
    echo "!! stage: STOPPED at act ${ACT_INDEX}/${TOTAL} — ${ACT_NAME} (exit ${status})." >&2
    echo "   No act after this one ran." >&2
    echo "   The from-the-top tool is the recovery: every act of deploy/release.sh is" >&2
    echo "   idempotent, so running it on the box repeats work rather than doubling it." >&2
    exit 1
}

# What each act is keyed on, decided once so the dry run and the real run can
# never answer differently.
DO_SHIP=""
[ -z "$TAG_MOVED" ] || DO_SHIP=1
DO_SECRETS="$DO_SHIP"
DO_UP=""
{ [ -z "$TAG_MOVED" ] && [ -z "$DIGEST_MOVED" ]; } || DO_UP=1
DO_LOGIN="$DO_UP"
DO_RELEASE=""
{ [ -z "$MIGRATIONS_MOVED" ] && [ -z "$OBSERVABILITY_MOVED" ] && [ -z "$DIGEST_MOVED" ]; } || DO_RELEASE=1

RELEASE_MOVED=""
[ -z "$MIGRATIONS_MOVED" ] || RELEASE_MOVED="${RELEASE_MOVED}${RELEASE_MOVED:+, }migrate+grants (a migration leaf moved)"
[ -z "$OBSERVABILITY_MOVED" ] || RELEASE_MOVED="${RELEASE_MOVED}${RELEASE_MOVED:+, }alerts (deploy/observability/ moved)"
[ -z "$DIGEST_MOVED" ] || RELEASE_MOVED="${RELEASE_MOVED}${RELEASE_MOVED:+, }recreate (the ${DIGEST_REPORT} image digest moved)"

# THE ONE ACT OF `release.sh`'s SEVEN THIS SCRIPT CAN KEY FROM OUTSIDE IT.
# `--without-alerts` is release.sh's own flag and its own sentence ("the alert
# route is NOT reconciled to this tree"), so passing it when
# `deploy/observability/` did not move is a skip release.sh itself announces
# rather than one this script performs behind its back.
RELEASE_FLAGS=""
[ -n "$OBSERVABILITY_MOVED" ] || RELEASE_FLAGS="--without-alerts"

say "box holds    ${BOX_TAG}  (${DELTA_COUNT} path(s) moved since)"
echo ""

# --- 1 · ship -----------------------------------------------------------------
act_begin
if [ -z "$DO_SHIP" ]; then
    act_skipped "the tree tag (${BOX_TAG})"
elif [ -n "$DRY_RUN" ]; then
    act_would "the tree tag moved ${BOX_TAG} → ${TREE_TAG}"
else
    set +e
    "$HERE/ship.sh" "$DESTINATION" ${KEY:+--key "$KEY"} --dest "$REMOTE_DIR"
    rc=$?
    set -e
    [ "$rc" = "0" ] || stopped "$rc"
    act_ran "${BOX_TAG} → ${TREE_TAG}"
fi

# --- 2 · secrets --------------------------------------------------------------
# ON EVERY SHIP, AND THAT IS NOT BELT AND BRACES. `ship.sh` extracts into a
# FRESH directory and swaps it into place, so the `deploy/.env` the previous
# tree had goes aside with it — by design, because hand-copying the file loses
# the group the containers read it as and every app container then restarts
# for ever with `Permission denied` and no explanation.
act_begin
if [ -z "$DO_SECRETS" ]; then
    act_skipped "the tree on the box (no ship, so its deploy/.env is still there)"
elif [ -n "$DRY_RUN" ]; then
    act_would "the ship would replace the tree, and no ship carries deploy/.env"
else
    set +e
    remote "cd '${REMOTE_DIR}' && ./deploy/provision.sh secrets-fetch '${REMOTE_DIR}/${ENVIRONMENT}/' deploy/.env"
    rc=$?
    set -e
    [ "$rc" = "0" ] || stopped "$rc"
    act_ran "${REMOTE_DIR}/${ENVIRONMENT}/env → deploy/.env"
fi

# --- 3 · login ----------------------------------------------------------------
# BEFORE `up`, AND AS THE BOX'S OWN ROLE. The pull grant belongs to the
# instance role, so the credential is fetched on the box and never travels:
# `get-login-password` reads the role from the instance metadata service and
# the password goes to `docker login` on stdin, so it is in no argv and no
# history file on either machine.
act_begin
if [ -z "$DO_LOGIN" ]; then
    act_skipped "the image (no pull, so no login)"
elif [ -z "$REGISTRY_REGION" ]; then
    act_skipped "the registry (${REGISTRY_HOST} is not an ECR host; its login is not this script's to guess)"
elif [ -n "$DRY_RUN" ]; then
    act_would "the box would log in to ${REGISTRY_HOST} as its own instance role"
else
    set +e
    remote "aws ecr get-login-password --region '${REGISTRY_REGION}' | docker login --username AWS --password-stdin '${REGISTRY_HOST}'"
    rc=$?
    set -e
    [ "$rc" = "0" ] || stopped "$rc"
    act_ran "${REGISTRY_HOST} as the box's instance role"
fi

# --- 4 · up -------------------------------------------------------------------
# THE ORGANS AND THE PULL, AND NOT THE APP PAIR. `provision.sh up` reconciles
# the services around the application and adopts this tree's image tag into the
# box's env file; the ONE recreate of `web` and `worker` in a deploy is
# `release.sh`'s act 6, after the migrate. That ordering is `release.sh`'s
# ruling and this script inherits it by calling the two in this order.
act_begin
if [ -z "$DO_UP" ]; then
    act_skipped "the tree tag and both image digests"
elif [ -n "$DRY_RUN" ]; then
    act_would "${TAG_MOVED:+the tree tag moved}${TAG_MOVED:+${DIGEST_MOVED:+ and }}${DIGEST_MOVED:+the ${DIGEST_REPORT} image digest moved}"
else
    set +e
    remote "cd '${REMOTE_DIR}' && DJB_IMAGE_REGISTRY='${IMAGE_REGISTRY}' ./deploy/provision.sh up"
    rc=$?
    set -e
    [ "$rc" = "0" ] || stopped "$rc"
    act_ran "pulled ${TREE_TAG} and reconciled the organs"
fi

# --- 5 · release --------------------------------------------------------------
act_begin
if [ -z "$DO_RELEASE" ]; then
    act_skipped "the migration leaves, deploy/observability/ and both image digests"
elif [ -n "$DRY_RUN" ]; then
    act_would "${RELEASE_MOVED}${RELEASE_FLAGS:+  (${RELEASE_FLAGS})}"
else
    # THE REMOTE REDIRECT IS NOT TIDINESS, IT IS release.sh's OWN REFUSAL.
    # `sshd` hands a command with no tty a PIPE for stdout, so `release.sh`
    # sees a piped stdout and refuses at exit 2 before act 1 — measured on the
    # hand walk, where the operator redirected on the box and read the file
    # back for exactly this reason. So the release writes to a file beside the
    # tree, its own status is carried out, and the transcript is printed here
    # in full: nothing is filtered and nothing replaces the exit status.
    set +e
    remote "cd '${REMOTE_DIR}' && DJB_IMAGE_REGISTRY='${IMAGE_REGISTRY}' ./deploy/release.sh ${RELEASE_FLAGS} >.stage-release.log 2>&1; release_rc=\$?; cat .stage-release.log; exit \$release_rc"
    rc=$?
    set -e
    [ "$rc" = "0" ] || stopped "$rc"
    act_ran "${RELEASE_MOVED}${RELEASE_FLAGS:+  (${RELEASE_FLAGS})}"
fi

# --- 6 · readyz ---------------------------------------------------------------
# ALWAYS, AND IT IS THE ACT THAT TURNS "the acts ran" INTO "the deployment
# answers". When the release act ran, its own act 7 already waited — bounded,
# 24 attempts — for the containers it had just recreated, so this is one probe
# after the fact rather than a second wait. When no act ran at all, this ONE
# probe is the whole of what a re-stage of an unchanged tree is for.
#
# PROBED FROM INSIDE `readyz-prober`, with that container's own target, its own
# `--connect-to` and its own certificate posture — `release.sh` act 7's
# argument verbatim: the prober's target is the one the alert route already
# watches, so this act and the 3am page agree by construction.
act_begin
if [ -n "$DRY_RUN" ]; then
    act_would "always — one probe from inside the readyz-prober container"
    echo ""
    say "DRY RUN — the box's TREE marker was read and nothing was touched."
    exit 0
fi
READYZ_PROBE="cd '${REMOTE_DIR}' && set -a && . deploy/.env && set +a && \
curl_args=\"-sS -o /dev/null -w %{http_code} --max-time 10\" && \
if [ \"\${PROBE_INSECURE:-0}\" = 1 ]; then curl_args=\"\$curl_args -k\"; fi && \
if [ -n \"\${PROBE_CONNECT_TO:-}\" ]; then curl_args=\"\$curl_args --connect-to \$PROBE_CONNECT_TO\"; fi && \
docker compose --env-file deploy/.env -f deploy/compose.yaml exec -T readyz-prober \
curl \$curl_args \"\${PROBE_TARGET:-https://\${SITE_ADDRESS}/readyz}\""
set +e
READYZ_CODE="$(remote "$READYZ_PROBE" 2>"$WORK/readyz.err")"
rc=$?
set -e
if [ "$rc" != "0" ]; then
    sed 's/^/   /' "$WORK/readyz.err" >&2 || true
    stopped "$rc"
fi
if [ "$READYZ_CODE" != "200" ]; then
    echo "" >&2
    echo "!! stage: STOPPED at act ${ACT_INDEX}/${TOTAL} — ${ACT_NAME}." >&2
    echo "   The readiness endpoint answered '${READYZ_CODE:-nothing}', not 200." >&2
    echo "   Every act before this one ran; the deployment is not serving." >&2
    echo "   Look at: docker compose -f ${REMOTE_DIR}/deploy/compose.yaml logs --tail 50 web worker" >&2
    echo "   Re-running deploy/release.sh on the box from the top is safe and is the" >&2
    echo "   usual next move." >&2
    exit 1
fi
act_ran "HTTP 200"

echo ""
say "STAGED. ${BOX_TAG} → ${TREE_TAG} on ${DESTINATION}, and it answers."
exit 0
