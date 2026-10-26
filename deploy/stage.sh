#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../scripts/bash_only.sh" || exit 2
# From a green tree to a healthy stage box, with every act keyed on its input.
#
#   deploy/stage.sh ec2-user@1.2.3.4 --env staging               stage HEAD
#   deploy/stage.sh ec2-user@1.2.3.4 --env staging --key ~/k.pem with an identity file
#   deploy/stage.sh ec2-user@1.2.3.4 --env staging --dry-run     say what would run, touch nothing
#   deploy/stage.sh ec2-user@5.6.7.8 --env prod --sanction '<who>: <why>' --staging ec2-user@1.2.3.4 --nightly <dir>
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
# THE LIVE MARKER. `<namespace>/LIVE`, one line, `live <tree tag> <UTC stamp>`,
# written by act 6 after the readyz answered 200 and by nothing else; it is
# removed before the first act whenever any act that changes the box will run
# (a ship, an up or a release). A ship swaps the whole namespace directory, so
# a newly shipped tree arrives with no marker at all. What it does NOT see: a
# `release.sh` or `provision.sh up` run by hand on the box, which leaves the
# marker standing over a box it did not prove; the recovery path re-stages.
#
# THE CLOSING LINE IS THE MEASURE'S INSTRUMENT. A stage that reached a 200 ends
# on exactly one line, and it is the last one:
#
#   stage: <tree tag> live in <n>s (migrate <m>s)
#
# `<n>` is this script's own wall, from its first line to the readyz answer;
# `<m>` is the release's migrate act as `release.sh` printed it (`migrate:
# <m>s`), CARRIED rather than re-measured from out here, so the two halves of a
# slow deploy are told apart. When the release act did not run the half reads
# `(migrate skipped)`, and when it ran and printed no wall it reads `(migrate
# unmeasured)` — never a zero, which would be a measurement nobody took. A dry
# run and the docs-only short circuit print no closing line: nothing went live.
#
# PROMOTION TO PROD HAS FOUR TEETH, AND ALL FOUR ARE READ BEFORE THE PROD BOX IS
# CONTACTED. Every environment NOT on the declared non-prod list
# (`DJB_NONPROD_ENVIRONMENTS`; default `staging stage dev development test qa
# local`) is prod, whatever it is spelled. It runs the same six acts as staging —
# ADR deploy-4 (f): promotion is neither a re-tag nor a rebuild — but only when
#
#   1. `--sanction '<who>: <why>'` names who is promoting and why (the shape
#      the full gate's own sanction takes, and stricter: one printable line,
#      no control character, neither half whitespace only);
#   2. the staging box named by `--staging <destination>` has PROVED this tree
#      live — its `LIVE` marker reads `live <this checkout's tree tag> <at>`.
#      NOT line 1 of `TREE`: the ship act writes that at act 1, before the
#      pull, the migrate, the swap and the readyz, so mid-deploy (or after a
#      deploy that stopped past act 1) it names a tree the OLD containers are
#      still answering for. `LIVE` is withdrawn before any act that changes a
#      box and written only once act 6 has answered 200 (see "THE LIVE
#      MARKER" below);
#   3. that staging box's readyz answers 200, probed exactly as act 6 probes;
#   4. the nightly leak proof handed in as `--nightly <artifact dir>` is green
#      and no older than 24 h — read by `nightly-read` in
#      quality/djb/ledger.py, called, never re-parsed here. Its
#      `nightly:none`, `nightly:stale:<at>`, a non-zero `rc=` and an unreadable
#      record (its exit 2) are each a red tooth, named.
#
# Every red precondition is named in one refusal (exit 2), so an operator fixes
# them in one pass. The staging box is READ — its marker and its readyz — and
# never acted on; the prod box is not contacted at all. The three flags mean
# nothing for any other environment and are refused there, so a sanction typed
# at staging is never mistaken for one that was checked. What this does NOT
# check: that staging and prod share a namespace directory and an identity file
# (`--dest` and `--key` serve both boxes), and that the nightly measured THIS
# tree — the nightly is the suite's leak proof over main, and the tooth is its
# freshness and its colour, as the design rules it.
#
# THE DOCS-ONLY SHORT CIRCUIT, AND WHY IT IS NOT JUST "EVERY PATH IS INERT".
# The class list is `quality/djb/scope.py::classify`'s — CALLED through its
# `classify` verb, never copied, so a territory added there is known here the day it
# is added. But `inert` is an answer to "can this path reach a Python test",
# and `deploy/observability/` is inert under that question while being the
# alerts act's whole input. So a delta is docs-only here when every path is
# inert AND no act's own input moved; the two halves together, or a deploy that
# moved the alert route would report nothing to deploy.

set -euo pipefail

# The closing line's wall starts here, before anything else is paid for.
STAGE_T0="$(date +%s)"

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/.." && pwd)"
set +x  # never; see deploy/entrypoint.sh for the same line and the same reason

# THE SCAFFOLD is deploy/lib.sh's and the pipe guard is the seam's
# `refuse_if_piped`: a pipe replaces this script's exit status with the
# filter's, and the exit status is the difference between "the box is serving
# this tree" and "some of the acts ran". `die` is exit 2, "could not get as far
# as staging" or "could not look": an act never attempted must never share an
# exit code with an act that ran and failed (`stopped`, exit 1).
DEPLOY_NAME=stage
DEPLOY_NOTHING="Nothing was staged; no act ran."
DEPLOY_USAGE_LINES=6
DEPLOY_USAGE_TAIL="The header of ${BASH_SOURCE[0]} says what each act is and what keys it."
DEPLOY_RECOVERY="The from-the-top tool is the recovery: every act of deploy/release.sh is
idempotent, so running it on the box repeats work rather than doubling it."
# shellcheck source=deploy/lib.sh
. "$HERE/lib.sh" || exit 2
refuse_if_piped "$DEPLOY_NAME"

DESTINATION=""
KEY=""
# The landing directory and the vault prefix are configuration and neither is
# guessed — `deploy/ship.sh`'s grammar, for `deploy/ship.sh`'s reason: this
# script's acts `rm -rf` a staging area and write an environment file, and both
# are destructive in a directory this deployment may not own.
REMOTE_DIR="${DJB_DEPLOY_NAMESPACE:-}"
ENVIRONMENT="${DJB_DEPLOY_ENVIRONMENT:-}"
DRY_RUN=""
# The prod gate's three inputs. Set means typed; they are refused outside prod.
SANCTION=""
SANCTION_TYPED=""
STAGING_DEST=""
NIGHTLY_DIR=""
PROD_FLAGS_TYPED=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    -h | --help) usage 0 ;;
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
    --sanction)
        [ "$#" -ge 2 ] || die "--sanction needs '<who>: <why>'"
        SANCTION="$2"
        SANCTION_TYPED=1
        PROD_FLAGS_TYPED=1
        shift 2
        ;;
    --staging)
        [ "$#" -ge 2 ] || die "--staging needs the staging box's destination"
        STAGING_DEST="$2"
        PROD_FLAGS_TYPED=1
        shift 2
        ;;
    --nightly)
        [ "$#" -ge 2 ] || die "--nightly needs the downloaded nightly-leak-proof artifact's directory"
        NIGHTLY_DIR="$2"
        PROD_FLAGS_TYPED=1
        shift 2
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
# PROD IS EVERYTHING NOT DECLARED OTHERWISE. The teeth are not keyed on a
# spelling of "prod" — `PROD`, `Production` and `prod-eu` would each walk past
# a list of prod names. They are keyed on the one declared list of NON-prod
# names, matched exactly and case-sensitively, and every other environment is
# gated. The list is `DJB_NONPROD_ENVIRONMENTS` (space-separated), defaulting to
# the names below; a product with another pre-prod environment names it there.
# Set empty, it gates every environment — the failure mode is a refusal, never
# a bare deploy.
NONPROD_ENVIRONMENTS="${DJB_NONPROD_ENVIRONMENTS-staging stage dev development test qa local}"
IS_PROD=1
for nonprod in $NONPROD_ENVIRONMENTS; do
    [ "$ENVIRONMENT" != "$nonprod" ] || IS_PROD=""
done
[ -n "$IS_PROD" ] || [ -z "$PROD_FLAGS_TYPED" ] ||
    die "--sanction, --staging and --nightly are the prod gate's and mean nothing for --env ${ENVIRONMENT}. A sanction typed here would read as one that was checked."
[ -z "$KEY" ] || [ -f "$KEY" ] || die "no identity file at $KEY"
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout, so there is no tree to stage and nothing that could name one"

# THE CLASSIFIER IS CALLED, NOT COPIED: `quality/djb/scope.py::classify` answers "what territory is this path".
# Invariant: asked once here, unsilenced, so a classifier that will not run refuses before anything is staged.
stage_classify() { (cd "$ROOT" && python3 -E -S -m quality.djb.scope classify --root "$ROOT" "$@"); }
stage_classify README.md >/dev/null ||
    die "quality.djb.scope's classify verb would not answer from $ROOT (its own error is above) — the docs-only short circuit is its answer and this script keeps no second list"

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

# The same transport to a NAMED box — the prod gate's reads of staging.
remote_at() {
    ssh ${SSH_ARGS[@]+"${SSH_ARGS[@]}"} "$1" "$2"
}

# ONE readyz probe: the box's own `readyz-prober` container asked for one
# (`prober.sh --once`) — its target, its socket override and its certificate
# posture, the same probe `release.sh`'s readyz act makes — for act 6 and for
# the prod gate's probe of staging, so the three can never disagree about what
# "answers" means.
READYZ_PROBE="cd '${REMOTE_DIR}' && docker compose --env-file deploy/.env -f deploy/compose.yaml \
exec -T readyz-prober sh /alerts/prober.sh --once"

say "destination  ${DESTINATION}"
say "namespace    ${REMOTE_DIR}  (environment ${ENVIRONMENT}; vault prefix ${REMOTE_DIR}/${ENVIRONMENT}/)"
say "tree         HEAD → ${TREE_TAG}"
say "registry     ${IMAGE_REGISTRY}${REGISTRY_REGION:+  (ECR, region ${REGISTRY_REGION})}"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-stage.XXXXXX")" || die "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT
MARKER="$WORK/TREE"

# --- THE PROD GATE: four preconditions, read before the prod box is contacted --
# sanction_shaped <sanction> — `<who>: <why>`, neither half whitespace only.
# The halves are copied OUT of BASH_REMATCH before they are tested, because
# each later `=~` overwrites it.
sanction_shaped() {
    local who why
    [[ $1 =~ ^([^:]+):\ (.+)$ ]] || return 1
    who=${BASH_REMATCH[1]}
    why=${BASH_REMATCH[2]}
    [[ $who =~ [^[:space:]] ]] && [[ $why =~ [^[:space:]] ]]
}

if [ -n "$IS_PROD" ]; then
    PROD_RED=()
    PROD_SEEN_SANCTION=""
    PROD_SEEN_STAGING=""
    PROD_SEEN_NIGHTLY=""

    # 1 · the sanction — the full gate's shape (scripts/check.sh), and stricter:
    # it is ONE printable line a human typed. Bash's `.` matches a newline, so
    # the shape alone admits a second line smuggled into either half; and a
    # reason (or a who) of whitespace only is a sanction that names nobody.
    if [ -z "$SANCTION_TYPED" ] || [ -z "$SANCTION" ]; then
        PROD_RED+=("sanction: no sanction — --sanction '<who>: <why>' names who is promoting this tree to prod and why")
    elif [[ $SANCTION =~ [[:cntrl:]] ]]; then
        PROD_RED+=("sanction: the sanction carries a control character (a newline, a tab, an escape) — it is one printable line, '<who>: <why>'")
    elif ! sanction_shaped "$SANCTION"; then
        PROD_RED+=("sanction: the sanction '${SANCTION}' is not '<who>: <why>' — something before the first colon, a colon, a space, then the reason")
    else
        PROD_SEEN_SANCTION="$SANCTION"
    fi

    # 2 and 3 · staging holds THIS tree, and answers.
    if [ -z "$STAGING_DEST" ]; then
        PROD_RED+=("staging tree: no staging box named — --staging <destination> is the box whose TREE marker must already say ${TREE_TAG}")
        PROD_RED+=("staging readyz: not probed — no staging box named")
    else
        # THE LIVE MARKER, NOT THE TREE MARKER (the header's tooth 2): what
        # staging PROVED, never merely what it was shipped.
        set +e
        remote_at "$STAGING_DEST" "cat '${REMOTE_DIR}/LIVE'" >"$WORK/staging-LIVE" 2>"$WORK/staging-LIVE.err"
        staging_rc=$?
        set -e
        staging_tag=""
        if [ "$staging_rc" = "0" ]; then
            staging_tag="$(awk 'NR == 1 && $1 == "live" && $2 ~ /^tree-[0-9a-f]+$/ { print $2 }' "$WORK/staging-LIVE")"
        fi
        if [ -z "$staging_tag" ]; then
            PROD_RED+=("staging tree: staging cannot say which tree it holds live — ${STAGING_DEST}:${REMOTE_DIR}/LIVE is absent or not 'live <tag> <at>' (read exit ${staging_rc}): a staging deploy is in flight, or the last one stopped before its readyz answered 200. Re-stage staging, then promote")
        elif [ "$staging_tag" != "$TREE_TAG" ]; then
            PROD_RED+=("staging tree: staging holds ${staging_tag}, and this tree is ${TREE_TAG} — prod is promoted only to the tree staging has proven live (its LIVE marker, written after its readyz answered)")
        fi
        set +e
        staging_code="$(remote_at "$STAGING_DEST" "$READYZ_PROBE" 2>"$WORK/staging-readyz.err")"
        staging_probe_rc=$?
        set -e
        if [ "$staging_probe_rc" != "0" ] || [ "$staging_code" != "200" ]; then
            PROD_RED+=("staging readyz: staging's readyz answered '${staging_code:-nothing}', not 200 (probe exit ${staging_probe_rc}) — a staging box that does not answer has proven nothing about this tree")
        fi
        [ -n "$staging_tag" ] && [ "$staging_tag" = "$TREE_TAG" ] && [ "$staging_probe_rc" = "0" ] && [ "$staging_code" = "200" ] &&
            PROD_SEEN_STAGING="${staging_tag} on ${STAGING_DEST}, readyz 200"
    fi

    # 4 · the nightly leak proof, read by the ledger's own reader under the stdlib floor.
    # A product tree (its drawer's `rule_id_namespace:`, declared_namespace's field) is spared it unless --nightly is given.
    case "$NIGHTLY_DIR" in "" | /*) nightly_at="$NIGHTLY_DIR" ;; *) nightly_at="$PWD/$NIGHTLY_DIR" ;; esac
    if [ -z "$NIGHTLY_DIR" ] && grep -Eq "^[[:space:]{]*rule_id_namespace:[[:space:]]*([\"']?[^[:space:]\"'#]|$)" "$ROOT/quality/local/rules.yaml" 2>/dev/null; then
        nightly_rc=0
        nightly_form="nightly:product"
        : >"$WORK/nightly.err"
    else
        set +e
        nightly_form="$(cd "$ROOT" && python3 -E -S -m quality.djb.ledger nightly-read "$nightly_at" 2>"$WORK/nightly.err")"
        nightly_rc=$?
        set -e
    fi
    nightly_why="$(sed -n '1p' "$WORK/nightly.err")"
    case "$nightly_rc:$nightly_form" in
    0:nightly:product)
        PROD_SEEN_NIGHTLY="a product tree — the platform's nightly leak proof is the template's; the product's own gate is its proof (staging proved ${PROD_SEEN_STAGING:-nothing})"
        ;;
    0:nightly:none)
        PROD_RED+=("nightly: there is no nightly leak proof (nightly:none) — hand the downloaded nightly-leak-proof artifact's directory to --nightly")
        ;;
    0:nightly:stale:*)
        PROD_RED+=("nightly: the nightly leak proof is older than 24 h (${nightly_form}) — run the nightly on main, then promote")
        ;;
    0:nightly:*" rc=0")
        PROD_SEEN_NIGHTLY="$nightly_form"
        ;;
    0:nightly:*" rc="*)
        PROD_RED+=("nightly: the nightly leak proof is RED (rc=${nightly_form##* rc=}) — ${nightly_form}; a leak the suite found last night is not promoted today")
        ;;
    *)
        PROD_RED+=("nightly: the nightly leak proof is unreadable (reader exit ${nightly_rc}) — ${nightly_why:-${nightly_form:-no reason given}}")
        ;;
    esac

    if [ "${#PROD_RED[@]}" -gt 0 ]; then
        echo "!! stage: REFUSED — a promotion to prod needs four preconditions green, and ${#PROD_RED[@]} of 4 preconditions are red:" >&2
        for red in "${PROD_RED[@]}"; do
            echo "   - ${red}" >&2
        done
        echo "   Nothing was staged; no act ran; the prod box was not contacted." >&2
        exit 2
    fi
    say "prod gate  sanction  ${PROD_SEEN_SANCTION}"
    say "prod gate  staging   ${PROD_SEEN_STAGING}"
    say "prod gate  nightly   ${PROD_SEEN_NIGHTLY}"
fi

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
# The image services are provision.sh's one list, never typed here.
STAGE_SERVICES="$("$HERE/provision.sh" image-services)" || exit 2
for stage_service in $STAGE_SERVICES; do
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
        shape="$(stage_classify "$delta_path")" || {
            echo "!! stage: '${delta_path}' is in the delta and quality/djb/scope.py's" >&2
            echo "   classify cannot say what territory it is. A path nothing" >&2
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

# The closing line's migrate half: `skipped` unless the release act runs and
# says otherwise.
MIGRATE_REPORT="skipped"

say "box holds    ${BOX_TAG}  (${DELTA_COUNT} path(s) moved since)"
echo ""

# --- the LIVE marker, withdrawn before anything changes the box ----------------
# WHENEVER AN ACT THAT CHANGES THE BOX WILL RUN, the box stops claiming a proven
# tree until act 6 proves one again — so a deploy in flight, or one that stops
# at any act, leaves no marker a promotion could read as a proof. A readyz-only
# re-stage changes nothing and withdraws nothing. Nothing has been touched yet,
# so a box that will not let go of its marker is a refusal, exit 2.
if [ -z "$DRY_RUN" ] && { [ -n "$DO_SHIP" ] || [ -n "$DO_UP" ] || [ -n "$DO_RELEASE" ]; }; then
    set +e
    remote "rm -f '${REMOTE_DIR}/LIVE'"
    rc=$?
    set -e
    [ "$rc" = "0" ] || die "could not withdraw ${REMOTE_DIR}/LIVE on the box (exit ${rc}) — a marker left standing over a deploy in flight would read as a proof"
fi

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
    #
    # The transcript lands in a file HERE too, and is printed whole before the
    # status is read, so this script can read the release's own `migrate: <n>s`
    # line out of it for the closing line. Nothing is filtered on the way.
    set +e
    remote "cd '${REMOTE_DIR}' && DJB_IMAGE_REGISTRY='${IMAGE_REGISTRY}' ./deploy/release.sh ${RELEASE_FLAGS} >.stage-release.log 2>&1; release_rc=\$?; cat .stage-release.log; exit \$release_rc" >"$WORK/release.out"
    rc=$?
    set -e
    cat "$WORK/release.out"
    MIGRATE_WALL="$(sed -n 's/^release: migrate: \([0-9][0-9]*\)s$/\1/p' "$WORK/release.out")"
    MIGRATE_WALL="${MIGRATE_WALL%%$'\n'*}"
    MIGRATE_REPORT="${MIGRATE_WALL:+${MIGRATE_WALL}s}"
    MIGRATE_REPORT="${MIGRATE_REPORT:-unmeasured}"
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
# PROBED BY `readyz-prober` ITSELF (`READYZ_PROBE` above) — `release.sh` act
# 7's argument verbatim: the prober's target is the one the alert route already
# watches, so this act and the 3am page agree by construction.
act_begin
if [ -n "$DRY_RUN" ]; then
    act_would "always — one probe from inside the readyz-prober container"
    echo ""
    say "DRY RUN — the box's TREE marker was read and nothing was touched."
    exit 0
fi
set +e
READYZ_CODE="$(remote "$READYZ_PROBE" 2>"$WORK/readyz.err")"
rc=$?
set -e
if [ "$rc" != "0" ]; then
    sed 's/^/   /' "$WORK/readyz.err" >&2 || true
    stopped "$rc"
fi
if [ "$READYZ_CODE" != "200" ]; then
    DEPLOY_RECOVERY="The readiness endpoint answered '${READYZ_CODE:-nothing}', not 200.
Every act before this one ran; the deployment is not serving.
Look at: docker compose -f ${REMOTE_DIR}/deploy/compose.yaml logs --tail 50 web worker
Re-running deploy/release.sh on the box from the top is safe and is the
usual next move."
    stopped 1
fi
act_ran "HTTP 200"

# THE PROOF, WRITTEN ONLY NOW: the one place `LIVE` is written. A box that
# answers but will not take the marker is a stage a promotion cannot read, so
# it is exit 1, named — the deployment IS serving, and a re-stage writes it.
set +e
remote "echo 'live ${TREE_TAG} $(date -u +%Y%m%dT%H%M%SZ)' >'${REMOTE_DIR}/LIVE'"
rc=$?
set -e
if [ "$rc" != "0" ]; then
    echo "!! stage: the deployment answers 200, but ${REMOTE_DIR}/LIVE could not be written (exit ${rc})." >&2
    echo "   A promotion to prod reads that marker and will refuse this tree until a" >&2
    echo "   re-stage (readyz only, when nothing moved) writes it." >&2
    exit 1
fi

echo ""
say "STAGED. ${BOX_TAG} → ${TREE_TAG} on ${DESTINATION}, and it answers."
say "${TREE_TAG} live in $(($(date +%s) - STAGE_T0))s (migrate ${MIGRATE_REPORT})"
exit 0
