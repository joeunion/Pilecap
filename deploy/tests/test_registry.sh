#!/usr/bin/env bash
# THIS FILE IS EXECUTED, AND IT IS BASH — not POSIX sh, and not zsh. The shebang
# above is honoured by `./this`; `sh this` and `zsh this` IGNORE it, and neither
# of them fails where the mistake was made (the argument, with measurements, is
# `scripts/tests/test_runbook_recipes.sh`'s header).
#
# TWO TESTS, because on macOS `/bin/sh` IS bash: BASH_VERSION is set under
# `sh x.sh` and only POSIX MODE tells the two apart.
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
# THE REGISTRY DRIVE — build once, promote by digest (ADR deploy-4), against a
# REAL registry.
#
#   ./deploy/tests/test_registry.sh          run every case
#   ./deploy/tests/test_registry.sh --list   name them and stop
#
# WHY IT EXISTS, AND WHY IT IS NOT `deploy/tests/test_release.sh`. That drive
# owns the release's CONTROL FLOW and proves it against a stub `docker` whose
# answers a case chooses — which is right for "does the refusal fire, in the
# right order, with the right sentence", and which cannot prove a single thing
# about registries. Every question below is about what a registry ACTUALLY DOES:
#
#   * does a `--platform linux/amd64,linux/arm64` build push ONE manifest that
#     carries both architectures, or two manifests, or one and a lie;
#   * does `deploy/provision.sh image-digest` read the INDEX digest back out of
#     it (the thing both architectures resolve through) rather than one
#     architecture's;
#   * does the same tag, resolved twice from two places, give the same digest —
#     which is the whole of what "promotion is not a rebuild" means;
#   * and does re-pushing DIFFERENT content under the SAME tag change that
#     digest — because `release.sh`'s mismatch refusal is built on the premise
#     that it does, and a premise nothing drives is a premise.
#
# A SINGLE-ARCH IMAGE IS THE DEFECT THIS EXISTS FOR. The deployment box is
# Graviton and every CI runner is amd64. A `--platform` typo, a builder that
# quietly fell back to the `docker` driver (which cannot push a manifest list at
# all), or a base image with no arm64 variant all produce a green build and an
# image the box cannot run — and the first machine to find out is the box, at
# 3am, with the previous tree already stopped.
#
# WHAT IT BUILDS. A two-line `FROM busybox` image, NOT this repository's
# Dockerfile. What is under test is the registry mechanism — the manifest, the
# digest, the immutability of the tag — and driving it with the real image would
# cost several minutes of emulated arm64 wheel building per run to prove exactly
# the same three facts. THE COST OF THAT CHOICE IS DECLARED: this drive says
# nothing about whether THIS repository's Dockerfile builds for arm64. The
# assertion that does is in `.github/workflows/ci.yml`'s images job, against the
# real image, and it is CI's to make.
#
# WHAT ELSE IT DOES NOT COVER:
#
#   * ECR itself. The registry here is `registry:2` on loopback: no
#     authentication, no IAM, no immutable-tag policy, no lifecycle rule. What
#     an ECR repository does with a re-push under an immutable tag is ECR's
#     behaviour and is not driven anywhere in this tree.
#   * The push CREDENTIAL. CI assumes a role by OIDC; nothing here does.
#   * Whether the pushed image RUNS. `deploy/tests/test_release.sh` proves the
#     release's wiring and `docs/runbooks/deploy.md`'s smoke steps prove the
#     deployment; neither is here.
#   * Registry availability as a deploy-time dependency. A box that cannot reach
#     the registry now cannot deploy at all — that is the trade ADR deploy-4
#     names and accepts, and it is a property of the world rather than of a
#     script.
#
# EXIT STATUS IS THE VERDICT, and it is this repository's three:
#   0  every property held.
#   1  a property did not hold.
#   2  could not look — no docker, no buildx, no registry image — and NOTHING
#      was asserted. A driver that could not run its cases has not cleared them.

set -euo pipefail
cd "$(dirname "$0")/../.."

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_registry: $*" >&2
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
    echo "!! unknown argument '$1': test_registry.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v docker >/dev/null 2>&1 || cannot_look "no 'docker' on PATH"
docker buildx version >/dev/null 2>&1 || cannot_look "no 'docker buildx' — a manifest list cannot be built without it"
docker info >/dev/null 2>&1 || cannot_look "the container daemon is not answering"
[ -x deploy/provision.sh ] || cannot_look "deploy/provision.sh is not in this tree — there is nothing to drive"

# --- the assertions -----------------------------------------------------------
ok() {
    echo "  ok       $*"
    PASSED=$((PASSED + 1))
}
bad() {
    echo "  FAILED   $*"
    FAILED=$((FAILED + 1))
}
holds() {
    local label="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then ok "${label} — ${got}"; else
        bad "${label} — wanted '${want}', got '${got}'"
    fi
}
contains() {
    local label="$1" needle="$2" hay="$3"
    case "$hay" in
    *"$needle"*) ok "${label} — carries ${needle}" ;;
    *) bad "${label} — does not carry '${needle}' (got: ${hay})" ;;
    esac
}

# --- THE SCRATCH WORLD, AND IT IS ENTIRELY THIS DRIVE'S -----------------------
# A registry container, a buildx builder and a scratch directory, every one of
# them named with a per-run identity nothing else on this machine derives, and
# every one of them removed in the trap. Nothing that anybody owns is inside
# this drive's reach — which is `scripts/tests/test_sweep.sh`'s rule and it
# applies to anything that creates world.
#
# The port is asked of the kernel rather than chosen: a fixed 5000 collides with
# whatever else on a shared machine is doing exactly this, and the collision
# reads as a registry that refused rather than as a port that was taken.
IDENT="djbregdrive$$"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-registry-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
REGISTRY_CID=""
BUILDER=""

cleanup() {
    [ -z "$REGISTRY_CID" ] || docker rm -f "$REGISTRY_CID" >/dev/null 2>&1 || true
    [ -z "$BUILDER" ] || docker buildx rm "$BUILDER" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

echo "test_registry: bringing up a scratch registry and a scratch builder (identity ${IDENT})"

REGISTRY_CID="$(docker run -d --name "$IDENT" -P registry:2 2>/dev/null)" ||
    cannot_look "could not start a 'registry:2' container — no image, no daemon, or no network to fetch it"
PORT="$(docker port "$IDENT" 5000/tcp 2>/dev/null | head -n1 | sed 's/.*://')"
[ -n "$PORT" ] || cannot_look "the scratch registry published no port"
REGISTRY="127.0.0.1:${PORT}"

# Wait for it to answer rather than assuming it did. A registry that is still
# starting refuses exactly like a registry that is broken.
ready=""
for _ in $(seq 1 40); do
    if docker run --rm --network host curlimages/curl:8.11.1 -fsS "http://${REGISTRY}/v2/" >/dev/null 2>&1 ||
        curl -fsS "http://${REGISTRY}/v2/" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.25
done
[ -n "$ready" ] || cannot_look "the scratch registry at ${REGISTRY} never answered /v2/"

# `docker-container` driver, because the default `docker` driver holds ONE
# architecture in the local image store and cannot push a manifest list at all —
# it is the single most likely way for a multi-arch build to silently become
# single-arch, and a drive that used it would prove the defect rather than the
# fix. `--driver-opt network=host` so the builder container can reach a registry
# published on the host's loopback, and the insecure entry because the scratch
# registry speaks HTTP.
BUILDER="$IDENT"
cat >"$WORK/buildkitd.toml" <<TOML
[registry."${REGISTRY}"]
  http = true
  insecure = true
TOML
docker buildx create --name "$BUILDER" --driver docker-container \
    --driver-opt network=host --config "$WORK/buildkitd.toml" >/dev/null 2>&1 ||
    cannot_look "could not create a docker-container buildx builder"
docker buildx inspect --bootstrap "$BUILDER" >/dev/null 2>&1 ||
    cannot_look "the scratch buildx builder would not start"

# The image under test. Two lines, and the ARG is what lets a case push
# DIFFERENT CONTENT under the same tag without a second Dockerfile.
cat >"$WORK/Dockerfile" <<'DOCKERFILE'
FROM busybox:1.37.0
ARG MARK=one
RUN echo "$MARK" >/mark
DOCKERFILE

TAG="tree-000000000001"
provision() { DJB_IMAGE_REGISTRY="$REGISTRY" ./deploy/provision.sh "$@"; }

push_image() {
    local service="$1" mark="${2:-one}" ref
    ref="$(provision image-ref "$service" "$TAG")"
    docker buildx build --builder "$BUILDER" \
        --platform linux/amd64,linux/arm64 \
        --build-arg "MARK=$mark" \
        --provenance=false \
        --tag "$ref" --push "$WORK" >>"$WORK/build.log" 2>&1
}

# =============================================================================
# the cases
# =============================================================================

case_the_reference_is_composed_and_never_typed() {
    # ONE COMPOSITION, four consumers — compose.yaml, CI, release.sh and this.
    # A second copy of the rule anywhere is a second answer to "which image".
    holds "image-repo composes prefix + djb-<service>" \
        "${REGISTRY}/djb-web" "$(provision image-repo web)"
    holds "image-ref appends the tag" \
        "${REGISTRY}/djb-web:${TAG}" "$(provision image-ref web "$TAG")"
    holds "the worker is the same composition" \
        "${REGISTRY}/djb-worker:${TAG}" "$(provision image-ref worker "$TAG")"
}

case_an_unknown_service_is_refused_rather_than_composed() {
    local out rc
    set +e
    out="$(provision image-ref caddy "$TAG" 2>&1)"
    rc=$?
    set -e
    holds "an image name for a service that has none is exit 2" "2" "$rc"
    contains "and it says which services there are" "web worker" "$out"
    # THE HALF THAT WAS ACTUALLY BROKEN. `die` inside a command substitution
    # exits the SUBSHELL, so the first version of `image_ref` printed the
    # refusal on stderr and then printed `:tree-…` on stdout and exited 0 — a
    # caller would have composed an image name with no repository in it.
    case "$out" in
    *":${TAG}"*) bad "image-ref printed a half-composed name after refusing" ;;
    *) ok "and it prints NO half-composed name after refusing" ;;
    esac
}

case_an_empty_registry_slot_is_a_refusal_and_not_a_guess() {
    local out rc
    set +e
    out="$(env -u DJB_IMAGE_REGISTRY ./deploy/provision.sh image-ref web "$TAG" 2>&1)"
    rc=$?
    set -e
    holds "no registry configured is exit 2" "2" "$rc"
    contains "and it says what the slot is for" "DJB_IMAGE_REGISTRY is empty" "$out"
}

case_a_tag_the_registry_lacks_is_exit_two_and_not_an_empty_digest() {
    # THE PREMISE OF release.sh's FIRST REFUSAL. "The registry does not have it"
    # must never degrade to "the digest is the empty string", because an empty
    # string compares equal to an absent pin and the release would sail on.
    local out rc
    set +e
    out="$(provision image-digest web tree-ffffffffffff 2>&1)"
    rc=$?
    set -e
    holds "a tag nothing pushed is exit 2" "2" "$rc"
    contains "and it names the reference it looked for" \
        "${REGISTRY}/djb-web:tree-ffffffffffff" "$out"
}

case_one_build_pushes_a_manifest_carrying_both_architectures() {
    # THE CRITERION. Read back OUT OF THE REGISTRY rather than out of the build
    # log, because the registry is what a box pulls.
    push_image web one || {
        bad "the multi-arch push failed — see ${WORK}/build.log"
        return
    }
    local ref platforms
    ref="$(provision image-ref web "$TAG")"
    platforms="$(docker buildx imagetools inspect --format '{{range .Manifest.Manifests}}{{.Platform.OS}}/{{.Platform.Architecture}} {{end}}' "$ref")"
    contains "the pushed manifest carries linux/amd64" "linux/amd64" "$platforms"
    contains "the pushed manifest carries linux/arm64" "linux/arm64" "$platforms"
}

case_the_digest_read_back_is_the_index_and_not_one_architectures() {
    local ref digest index_digest
    ref="$(provision image-ref web "$TAG")"
    digest="$(provision image-digest web "$TAG")"
    case "$digest" in
    sha256:*) ok "image-digest answers a sha256 digest" ;;
    *) bad "image-digest answered '${digest}', which is not a digest" ;;
    esac
    # The INDEX's own digest — the one both architectures resolve through, and
    # therefore the only digest that names "this image" rather than "this image
    # on amd64". Asserted against `imagetools`' own answer for the same ref.
    index_digest="$(docker buildx imagetools inspect --format '{{json .Manifest.Digest}}' "$ref" | tr -d '"')"
    holds "and it is the index digest the registry reports" "$index_digest" "$digest"
}

case_the_same_tag_resolves_to_the_same_digest_from_anywhere() {
    # PROMOTION, staging → prod, in one sentence: two environments ask the
    # registry the same question and get the same answer, so they run the same
    # bytes. There is no re-tag and there is nothing to rebuild.
    local first second
    first="$(provision image-digest web "$TAG")"
    second="$(cd "$WORK" && DJB_IMAGE_REGISTRY="$REGISTRY" "$OLDPWD/deploy/provision.sh" image-digest web "$TAG")"
    holds "the digest is the same asked from a different directory" "$first" "$second"
}

case_re_pushing_different_content_under_one_tag_changes_the_digest() {
    # THE PREMISE OF release.sh's SECOND REFUSAL. If a tag could be re-pointed
    # without the digest moving, the mismatch guard would be guarding nothing.
    local before after
    before="$(provision image-digest web "$TAG")"
    push_image web two || {
        bad "the second push failed — see ${WORK}/build.log"
        return
    }
    after="$(provision image-digest web "$TAG")"
    if [ "$before" = "$after" ]; then
        bad "a tag re-pushed with different content kept its digest — the mismatch refusal guards nothing"
    else
        ok "a re-push under the same tag moved the digest ${before} -> ${after}"
    fi
    # And that is EXACTLY the state release.sh refuses: a box pinned `before`
    # and the registry now says `after`.
    holds "which is a box-pin/registry disagreement by construction" "0" \
        "$([ "$before" != "$after" ] && echo 0 || echo 1)"
}

case_the_worker_is_its_own_repository() {
    # Two images, two repositories, one tag. A composition that collapsed them
    # would make the worker run the web image, which no test above would see.
    push_image worker one || {
        bad "the worker push failed — see ${WORK}/build.log"
        return
    }
    local web_digest worker_digest
    web_digest="$(provision image-digest web "$TAG")"
    worker_digest="$(provision image-digest worker "$TAG")"
    if [ "$web_digest" = "$worker_digest" ]; then
        bad "web and worker resolved to ONE digest — the two repositories are the same repository"
    else
        ok "web and worker are separate repositories at the same tag"
    fi
}

case_the_reference_is_composed_and_never_typed
case_an_unknown_service_is_refused_rather_than_composed
case_an_empty_registry_slot_is_a_refusal_and_not_a_guess
case_a_tag_the_registry_lacks_is_exit_two_and_not_an_empty_digest
case_one_build_pushes_a_manifest_carrying_both_architectures
case_the_digest_read_back_is_the_index_and_not_one_architectures
case_the_same_tag_resolves_to_the_same_digest_from_anywhere
case_re_pushing_different_content_under_one_tag_changes_the_digest
case_the_worker_is_its_own_repository

echo "test_registry: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. A single-architecture image, a digest that is" >&2
    echo "   one architecture's rather than the index's, or a tag that can be" >&2
    echo "   re-pointed invisibly each turn 'build once, promote by digest' back" >&2
    echo "   into 'hope the box built the same thing'." >&2
    exit 1
fi
exit 0
