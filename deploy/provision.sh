#!/usr/bin/env bash
# Everything this deployment needs brought into existence, as plain annotated
# `aws` CLI and one generator (ADR deploy-1: an IaC framework is a toolchain tax
# at one box per environment; the runbook must be performable by a stranger with
# aws-cli and ssh).
#
#   deploy/provision.sh env-file <path> <env>          generate every value; NO AWS
#   deploy/provision.sh secrets-put <prefix> <file>    push them into Secrets Manager
#   deploy/provision.sh secrets-fetch <prefix> <file>  pull them back onto a box
#   deploy/provision.sh infra <env>                    EC2 + RDS + S3 + security groups
#   deploy/provision.sh project-name                   the name THIS stack carries
#   deploy/provision.sh derived-project-name           the name this CHECKOUT derives
#   deploy/provision.sh image-tag                      the tag its images carry
#   deploy/provision.sh image-repo <web|worker>        the registry repository it lives in
#   deploy/provision.sh image-ref <web|worker> [tag]   repository:tag, the one composed name
#   deploy/provision.sh image-digest <web|worker> [tag]  what the REGISTRY says that tag is
#   deploy/provision.sh tree-digest <web|worker>       what the box's TREE file PINS it to
#   deploy/provision.sh pin-digest <web|worker> <sha>  write that pin (release.sh's, act 7)
#   deploy/provision.sh up [args...]                   `compose up -d`, on THIS box's stack
#   deploy/provision.sh backup-policy <env> [--apply]  the backups bucket's WORM-ish posture
#
# `env-file` MAKES NO AWS CALLS AND COSTS NOTHING. That is what lets the whole
# deployment be proved on a laptop before a dollar is spent. `infra` is the only
# subcommand that creates a billable resource and it refuses to run without
# `--confirm`, because the difference between reading this file and running it
# should not be one arrow key.
#
# THE SECRETS DOCTRINE, IN CODE. Every secret this deployment holds is generated
# here, by `openssl`/`python`, straight into a file mode 600 or straight into
# Secrets Manager. No human types one. No value is echoed to a terminal, written
# to a log, or passed as a command-line argument that would land in `ps` or in a
# shell history file — the two paths that would (`secrets-put`, and Caddy's
# bcrypt hash) use stdin or a process substitution, and the one plaintext a
# person genuinely needs (the o11y wall's password) is printed once, deliberately,
# on the last line, and stored nowhere.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set +x  # never; see deploy/entrypoint.sh for the same line and the same reason

die() { echo "!! provision: $*" >&2; exit 2; }
say() { echo "provision: $*"; }

# --- THE DEPLOYMENT NAMESPACE ------------------------------------------------
# ONE SLUG, AND EVERY AWS COORDINATE THIS FILE COMPOSES IS COMPOSED FROM IT: the
# Secrets Manager prefix (`<ns>/<env>/env`), the two buckets
# (`<ns>-<env>-backups|media`), the two IAM roles (`<ns>-<env>-box`,
# `-backup-retention`), the EC2 Name/Project tags and the RDS identifier.
#
# IT IS CONFIGURATION AND IT HAS NO DEFAULT — `deploy/dns.sh:33-34`'s grammar,
# for its reason one level down: a wrong zone id is a write into somebody else's
# DNS, and a wrong namespace is a write into somebody else's resources. Both
# succeed. So unset is a REFUSAL, never a fallback, and there is deliberately no
# `:-` anywhere below.
#
# WHY NOT `DJB_PROJECT_NAME`: that name is taken and means something else — the
# compose project this CHECKOUT derives from its own path (see
# `derived_project_name` below), which is per-worktree and must never be
# confused with the account-level namespace an environment lives under.
#
# The refusal is a statement, never a `$(...)`: `die` inside a command
# substitution exits the subshell and leaves the caller running.
NAMESPACE=""
require_namespace() {
    NAMESPACE="${DJB_DEPLOY_NAMESPACE:-}"
    [ -n "$NAMESPACE" ] || die "DJB_DEPLOY_NAMESPACE is required — this deployment's namespace, the slug every secret prefix, bucket, role and tag is composed from. There is no default: a guessed namespace is a write into somebody else's resources. It is a slot in this environment's env file (deploy/env.staging.example); on a box 'set -a; . deploy/.env; set +a' after 'provision.sh secrets-fetch' exports it."
}

# --- the archive bucket's retention pairing ----------------------------------
# THREE NUMBERS, DECLARED TOGETHER, because the failure this closes is two of
# them drifting apart in two files nobody diffs against each other. The long
# argument is at the `put-bucket-lifecycle-configuration` call in `infra`; the
# short version is that the platform's purge deletes an object on a VERSIONED
# bucket, which keeps it as a noncurrent version forever unless something here
# says otherwise.
#
# The first number is `apps/exports`' own rule-31 declaration, RESTATED here and
# never re-decided: `apps/exports/models.py::EXPORT_RETENTION_DAYS` is the
# authority, and `apps/core/tests/test_archive_retention.py` fails if this copy
# stops matching it. The second is this deployment's grace window — how long
# after the platform has let go the bucket may still hold the bytes. The third
# is the only number a customer or an auditor should ever be quoted, and it is
# DERIVED so it cannot be quoted wrong.
DJB_EXPORT_RETENTION_DAYS=30
DJB_ARCHIVE_GRACE_DAYS=7
DJB_ARCHIVE_TOTAL_EXPOSURE_DAYS=$((DJB_EXPORT_RETENTION_DAYS + DJB_ARCHIVE_GRACE_DAYS))

usage() {
    # Up to the blank line that ends the header block, not a hard-coded line
    # number: this header grows a line every time a subcommand is added, and a
    # `2,30p` that once matched it printed `set -euo pipefail` as usage the
    # first time it did.
    sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed -n '/^#/p' | sed 's/^# \{0,1\}//'
    exit 2
}

PYTHON_BIN="${PYTHON_BIN:-}"
if [ -z "$PYTHON_BIN" ]; then
    command -v python3 >/dev/null 2>&1 && PYTHON_BIN=python3 || PYTHON_BIN=python
fi
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "no python on PATH"

# =============================================================================
# WHOSE STACK IS THIS — the project name, derived from the CHECKOUT
# =============================================================================
# `scripts/db.sh`'s doctrine, applied to compose. That file gives every checkout
# its own DATABASE because two checkouts of one branch used to share one and
# quietly write over each other; a compose stack is the same hazard with a
# louder blast radius. `deploy/compose.yaml` used to pin `name: djb-deploy`, so
# two checkouts on one laptop addressed ONE set of containers, ONE network and
# ONE set of volumes — and `teardown.sh local --purge` in checkout X destroyed
# checkout Y's data. Nobody had to be careless; the name was shared, so the
# collision was structural.
#
# The name follows the CHECKOUT, not the branch and not the directory compose
# happens to be invoked from:
#
#     djb_deploy_<first 8 hex of the SHA-256 of the checkout's top-level path>
#
# and `COMPOSE_PROJECT_NAME` wins over the derivation, which is the ONE escape —
# the same escape `DATABASE_NAME` is for `db.sh`, and for the same reason: an
# operator who means a specific stack (a deliberate second one, say) must be
# able to say
# so, out loud, on the command line.
#
# `provision.sh env-file` writes the derived name into `deploy/.env`, and compose
# reads `COMPOSE_PROJECT_NAME` out of that file by itself — so every bare
# `docker compose -f deploy/compose.yaml ...` in the runbook lands on this
# checkout's stack with nothing threaded through it. Verified against Compose
# v2.33: `-p` beats the env file, the env file beats a `name:` in the compose
# file, and with neither the project is the directory name (`deploy`) — which is
# exactly the shared name this removes, and why `compose.yaml` no longer carries
# a `name:` at all.

# First 8 hex of SHA-256, with the same fallback ladder db.sh uses, because this
# must not need a tool a fresh laptop might not have.
path_hash() {
    local input="$1" digest=""
    if command -v shasum >/dev/null 2>&1; then
        digest="$(printf '%s' "$input" | shasum -a 256 | awk '{print $1}')"
    elif command -v sha256sum >/dev/null 2>&1; then
        digest="$(printf '%s' "$input" | sha256sum | awk '{print $1}')"
    elif command -v openssl >/dev/null 2>&1; then
        digest="$(printf '%s' "$input" | openssl dgst -sha256 | awk '{print $NF}')"
    else
        digest="$(printf '%08x' "$(printf '%s' "$input" | cksum | awk '{print $1}')")"
    fi
    printf '%.8s' "$digest"
}

# The checkout's own top level. A linked worktree reports ITSELF, not the
# repository it is linked to, so a worktree and its parent derive different
# names even on the same branch — which is the whole point. Outside a repository
# the parent of deploy/ is the checkout.
checkout_root() {
    ( cd "$HERE" && git rev-parse --show-toplevel 2>/dev/null ) || dirname "$HERE"
}

# The derived name, and ONLY the derived name. Deliberately does not consult
# COMPOSE_PROJECT_NAME: `teardown.sh` compares the two, and a function that had
# already folded the override in would have nothing left to compare.
derived_project_name() {
    printf 'djb_deploy_%s' "$(path_hash "$(checkout_root)")"
}

# THE NAME THIS BOX'S STACK ACTUALLY CARRIES, which is not always the derived
# one. `cmd_up` ADOPTS the name of a stack that was already running from this
# checkout and writes it into `deploy/.env` — that is the whole point of the
# re-deploy migration — so on an adopted box the derivation names a
# project that does not exist. `provision.sh project-name` answered the
# derivation anyway, and the two runbook lines that ASK for a name believed it:
# step 9's `docker ps --filter label=…project=<name>` listed nothing, and step
# 12's `docker run --network <name>_default` joined a network with nothing on
# it (`djb_deploy_…` against a live `djb-deploy`). Neither failed loudly; the
# filter answered "no containers" and the psql container answered "could not
# connect", which are the sentences an operator reads as a broken deployment.
#
# THE PRECEDENCE IS `release.sh`'s, and it is the same everywhere in this
# deployment: an exported `COMPOSE_PROJECT_NAME` is the ONE escape and outranks
# everything · then the env file, which is where the adoption is written · then
# the derivation, which is the truth on every box that never adopted anything.
resolved_project_name() {
    if [ -n "${COMPOSE_PROJECT_NAME:-}" ]; then
        printf '%s' "$COMPOSE_PROJECT_NAME"
        return
    fi
    local from_file
    from_file="$(project_in_env_file)"
    if [ -n "$from_file" ]; then
        printf '%s' "$from_file"
        return
    fi
    derived_project_name
}

# What the images are tagged. Not `latest`: compose tags a `build:` service
# `<project>-web:latest` when no `image:` is given, which made `compose.yaml`'s
# own "EVERY IMAGE IS PINNED / `latest` nowhere" paragraph false about the two
# images this repository actually builds. The TREE hash rather
# than the commit, because the tree is what went into the image: two commits
# with identical content build the same image and should say so. A dirty tree is
# marked, because an image built from uncommitted work is not the tree it names.
#
# THE BOX HAS NO `.git`, AND THAT USED TO MAKE THIS FUNCTION LIE. Runbook step 30
# ships the tree with `git archive HEAD`, which is exactly right — no history, no
# credential, no `.venv` — and leaves the box with no repository to ask. This
# function then printed `untracked`, the box built `djb-web:untracked`, and the
# deployment's own "every image is pinned to a tree" claim was false on the only
# machine it mattered on.
#
# So the tag is DERIVED WHERE GIT IS — on the laptop — and CARRIED IN THE ARCHIVE
# as a `TREE` file beside `deploy/`, whose FIRST LINE is the tag:
#
#     git archive --add-virtual-file=TREE:"$(./deploy/provision.sh image-tag)" HEAD \
#       | ssh … 'mkdir -p "$NS" && tar -x -C "$NS"'
#
# Git wins where git exists, so a laptop is unchanged and a checkout can never be
# fooled by a stale `TREE` somebody left behind. `TREE` answers only where the
# repository does not, which is the one place it is the better witness. `untracked`
# survives as the last resort and now means what it says: no git AND no archive
# marker, i.e. somebody assembled this tree by hand.
#
# --- THE TREE FILE'S GRAMMAR, AND WHY IT IS LINE-ORIENTED ---------------------
# It used to be read as `tr -d ' \t\r\n' < TREE` — the WHOLE FILE with every
# whitespace byte removed — which is a reader that cannot survive the file
# growing a second line. `release.sh` now pins the released image DIGEST beside
# the tag, so the file does grow one, and the old reader would have
# concatenated `tree-abc123def456` and `sha256:…` into a single tag naming
# nothing. That is the C1 disease exactly: two readers of one file that disagree
# about where a value ends.
#
# The grammar, and it is one sentence: LINE 1 IS THE TAG, BARE. Every later line
# is `<key> <value…>`, read by key and never by position. A legacy one-line
# `TREE` is therefore still read correctly by the same code — which is what lets
# a box shipped before this change be released after it.
#
#     tree-a1b2c3d4e5f6
#     digest web sha256:…
#     digest worker sha256:…
image_tag() {
    local tree dirty=""
    tree="$( cd "$HERE" && git rev-parse --short=12 'HEAD^{tree}' 2>/dev/null )" || tree=""
    if [ -z "$tree" ]; then
        if [ -f "$HERE/../TREE" ]; then
            # LINE 1, whitespace trimmed. Written by the ship step above out of
            # this same function, so the box's tag and the laptop's are the same
            # bytes by construction rather than by anybody remembering.
            head -n1 "$HERE/../TREE" | tr -d ' \t\r\n'
            return
        fi
        printf 'untracked'
        return
    fi
    if ! ( cd "$HERE" && git diff --quiet HEAD 2>/dev/null ); then
        dirty="-dirty"
    fi
    printf 'tree-%s%s' "$tree" "$dirty"
}

# =============================================================================
# THE REGISTRY — build once, promote by digest (ADR deploy-4)
# =============================================================================
# WHAT WENT WRONG WITHOUT IT. This deployment built its images THREE TIMES for
# one tree: twice in CI (`docker build --target web|worker`, whose output died
# with the runner and was therefore never CI-tested in any sense that reached a
# box), and once more on the box itself, arm64, at runbook step 33. Three builds
# of "the same" tree is three chances to differ — a base image that moved
# between them, a transient apt mirror, a wheel rebuilt — and NOTHING anywhere
# could tell you whether the amd64 thing CI proved and the arm64 thing the box
# ran were the same software. The box build is also the slowest step in a
# deploy and the one most likely to fail at 3am, on the machine least able to
# be debugged.
#
# THE RULE NOW. One image per tree, built ONCE, in CI, multi-arch, pushed to a
# registry under the tree tag. The box PULLS it. A release RESOLVES the tag to
# an immutable digest, refuses a tag the registry does not have, and pins the
# digest it released into `TREE` — so the question "what is actually running"
# has a byte answer on the box rather than an inference from a tag.
#
# WHY A TAG AT ALL, IF THE DIGEST IS THE TRUTH. Because the tag is DERIVED
# (`tree-<12hex>`), not chosen: it is a name for the digest that a human can
# read, and it is the same name on every environment. There is deliberately no
# `:staging` and no `:prod` — a moving tag makes "which image is prod running"
# unanswerable from the box, which is the disease this whole file exists to
# refuse. PROMOTION IS THEREFORE NOT A RE-TAG AND NOT A REBUILD: staging and
# prod point their `DJB_IMAGE_TAG` at the same tree, resolve the same digest,
# and run the same bytes.

# The repository PREFIX every image name here is composed from. Configuration,
# no default — `deploy/dns.sh`'s grammar and `DJB_DEPLOY_NAMESPACE`'s, for the
# same reason one level down: a guessed registry is a pull from, or a push to,
# somebody else's namespace, and both succeed. For ECR it is
# `<account>.dkr.ecr.<region>.amazonaws.com/<namespace>`; on a laptop the
# generator writes the bare local prefix `local`, which no registry is ever
# consulted for.
#
# The refusal is a statement rather than a `$(...)`: `die` inside a command
# substitution exits only the subshell.
IMAGE_REGISTRY=""
require_image_registry() {
    IMAGE_REGISTRY="${DJB_IMAGE_REGISTRY:-}"
    if [ -z "$IMAGE_REGISTRY" ] && [ -f "$HERE/.env" ]; then
        IMAGE_REGISTRY="$(sed -n "s/^DJB_IMAGE_REGISTRY='\{0,1\}\([^']*\)'\{0,1\}$/\1/p" "$HERE/.env" | head -n1)"
    fi
    [ -n "$IMAGE_REGISTRY" ] || die "DJB_IMAGE_REGISTRY is empty.
   It is the repository prefix every image name is composed from — for ECR
   '<account>.dkr.ecr.<region>.amazonaws.com/<namespace>', on a laptop 'local'.
   It has no default on purpose: a guessed registry pulls somebody else's image
   and succeeds. Export it, or fill the slot deploy/.env carries."
}

# The two services that have an image, named once. A third one added below
# without a name here would compose a repository nothing pushes to.
IMAGE_SERVICES="web worker"

require_image_service() {
    local want="${1:-}"
    case " $IMAGE_SERVICES " in
    *" $want "*) return 0 ;;
    esac
    die "unknown image service '${want:-<none>}'. This deployment has: $IMAGE_SERVICES"
}

# `<prefix>/djb-<service>`. The `djb-` half is the image NAME this repository has
# always used and it is deliberately kept: `apps/core/tests/test_connection_pool.py`
# reads `deploy/compose.yaml` and asserts the one-off door runs the same image
# name `web` does, and the runbooks, the release drive and the provision drive
# all speak it. A registry migration is not the moment to rename the thing being
# migrated.
image_repo() {
    require_image_service "${1:-}"
    require_image_registry
    printf '%s/djb-%s' "$IMAGE_REGISTRY" "$1"
}

# repository:tag — THE ONE COMPOSED NAME. `deploy/compose.yaml` interpolates the
# identical string out of `deploy/.env`; CI builds and pushes it; `release.sh`
# resolves it. Four sites, one composition, so they cannot drift.
#
# `repo` is resolved into a variable and its status CHECKED, rather than
# interpolated inline: `die` inside a command substitution exits the SUBSHELL,
# so an inline `$(image_repo …)` printed the refusal on stderr and then went on
# to print `:tree-…` on stdout and exit 0 — a caller reading that string would
# have composed an image name with no repository in it. The file's own
# `require_namespace` paragraph says the same thing about the same trap.
image_ref() {
    local service="${1:-}" tag="${2:-}" repo
    [ -n "$tag" ] || tag="$(image_tag)"
    repo="$(image_repo "$service")" || exit 2
    printf '%s:%s' "$repo" "$tag"
}

# WHAT THE REGISTRY SAYS THAT TAG IS. The manifest digest — for a multi-arch
# image, the digest of the INDEX, which is the thing both architectures resolve
# through and therefore the only digest that names "this image" rather than
# "this image on amd64".
#
# `docker buildx imagetools inspect` rather than `docker manifest inspect`: the
# latter needs experimental mode on some daemons and prints the manifest without
# reliably printing its own digest. This prints exactly one line or fails.
#
# EXIT 2 ON ANYTHING IT COULD NOT RESOLVE, and the caller must not turn that
# into "no digest". "The registry does not have this tag" and "I could not reach
# the registry" are different sentences and only one of them is the deployer's
# fault; both are refusals, neither is a pass.
image_digest() {
    local service="${1:-}" tag="${2:-}" ref out
    ref="$(image_ref "$service" "$tag")" || exit 2
    command -v docker >/dev/null 2>&1 || die "no 'docker' on PATH; the registry cannot be asked what $ref is"
    out="$(docker buildx imagetools inspect --format '{{json .Manifest.Digest}}' "$ref" 2>&1)" || {
        echo "!! provision: the registry has no $ref (or could not be reached)." >&2
        printf '   %s\n' "$out" >&2
        exit 2
    }
    out="${out//\"/}"
    case "$out" in
    sha256:*) printf '%s' "$out" ;;
    *) die "the registry answered about $ref with something that is not a digest: $out" ;;
    esac
}

# WHAT THE BOX PINS. Read off `TREE`'s `digest <service> <sha256:…>` line — by
# KEY, never by position, per the grammar above. Empty output and exit 0 mean
# "this tree has never been released here", which is a legitimate state (the
# first release of a freshly shipped tree) and is NOT a mismatch.
tree_digest() {
    require_image_service "${1:-}"
    [ -f "$HERE/../TREE" ] || return 0
    awk -v svc="$1" '$1 == "digest" && $2 == svc { print $3; exit }' "$HERE/../TREE"
}

# WRITE that pin. `release.sh` act 7's, and nobody else's — the pin is a record
# of what was RELEASED, so anything that wrote it earlier would be recording an
# intention as a fact.
#
# Rewritten whole rather than appended to, so a re-release of the same tree
# replaces its own line instead of growing a file with two answers in it. Line 1
# is never touched.
pin_digest() {
    local service="${1:-}" digest="${2:-}" file="$HERE/../TREE" tmp
    require_image_service "$service"
    case "$digest" in
    sha256:*) : ;;
    *) die "pin-digest: '$digest' is not a sha256:… digest" ;;
    esac
    [ -f "$file" ] || die "no $file — this box has no TREE marker to pin a digest into. Re-ship (deploy/ship.sh)."
    tmp="$(mktemp "${file}.XXXXXX")" || die "could not write beside $file"
    awk -v svc="$service" -v dg="$digest" '
        NR == 1 { print; next }
        $1 == "digest" && $2 == svc { next }
        { print }
        END { print "digest " svc " " dg }
    ' "$file" >"$tmp" || { rm -f "$tmp"; die "could not rewrite $file"; }
    mv "$tmp" "$file" || die "could not replace $file"
}

# The Caddy image, for `caddy hash-password`. Pinned to the same tag
# deploy/compose.yaml runs, and read from that file rather than repeated here —
# two pins that can disagree is one pin.
caddy_image() {
    grep -E '^\s+image: caddy:' "$HERE/compose.yaml" | head -n1 | awk '{print $2}'
}

# The one slot this deployment ships UNFILLED, and the sentinel that says so.
# Read out of `deploy/entrypoint.sh`, which is the file that REFUSES the sentinel
# on any other name — the same "two pins that can disagree is one pin" rule
# `caddy_image()` follows. A sentinel that the generator wrote and the entrypoint
# had never heard of would be a refusal on every boot.
deferred_sentinel() {
    local value
    value="$(sed -n "s/^DJB_DEFERRED_SENTINEL='\([^']*\)'$/\1/p" "$HERE/entrypoint.sh" | head -n1)"
    [ -n "$value" ] || die "could not read DJB_DEFERRED_SENTINEL out of deploy/entrypoint.sh. That file declares it and this generator writes it; with the two out of step every container would refuse to start."
    printf '%s' "$value"
}

# =============================================================================
# env-file — the generator
# =============================================================================
# Takes `env.<env>.example` as the manifest of NAMES (plus, for prod, its delta
# file) and fills every slot the table below calls generated. One template, so
# a variable added to the staging manifest reaches every environment without a
# second edit — the claim `env.prod.example` makes, made true here.

cmd_env_file() {
    local out="${1:-}" environment="${2:-}"
    [ -n "$out" ] && [ -n "$environment" ] || usage
    shift 2 || true

    # --- --adopt: the environment that ALREADY EXISTS ------------------------
    # `env-file` regenerates every secret, which is right for a FIRST provision
    # and wrong for an environment that is already up: `POSTGRES_PASSWORD` is
    # RDS's master, nothing in the deploy path re-applies it, and a fresh value
    # locks the box out of its own database. The overwrite guard below catches
    # the in-place case; it does NOT catch the one that actually bites — the
    # file is absent (teardown removed it, or this is a fresh checkout), so the
    # operator generates to a clean path and the refusal never fires.
    #
    # `--adopt <file>` is that path: point it at the environment's CURRENT env
    # (the one `secrets-fetch` just wrote from the vault) and the four ADOPTED
    # names are carried across instead of re-minted. Everything else is
    # regenerated exactly as before, and the run prints what it kept.
    local force="" adopt=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --force) force="--force" ;;
            --adopt) shift; adopt="${1:-}"
                     [ -n "$adopt" ] || die "--adopt needs the path of the environment's current env file" ;;
            --adopt=*) adopt="${1#--adopt=}" ;;
            *) die "unknown flag $1 (env-file takes --force and --adopt <file>)" ;;
        esac
        shift
    done
    [ -z "$adopt" ] || [ -f "$adopt" ] || die "--adopt $adopt: no such file. It is the environment's CURRENT env — 'provision.sh secrets-fetch \"\$DJB_DEPLOY_NAMESPACE/<env>/\" <file>' writes one."

    if [ -e "$out" ] && [ "$force" != "--force" ]; then
        die "$out already exists. Overwriting an environment's secrets is how a running deployment loses its Fernet key and every credential it protected.
   For an environment that is ALREADY UP, do not regenerate: 'provision.sh secrets-fetch \"\$DJB_DEPLOY_NAMESPACE/<env>/\" $out' fetches what it is running on.
   If you must regenerate for an adopted environment, pass --adopt <its current env file> so the RDS master password and the three other
   already-known values are carried rather than re-minted, and --force if you also mean to overwrite this path."
    fi

    # umask first, so the file is never briefly world-readable between creat()
    # and chmod. A race nobody would ever see and everybody would inherit.
    ( umask 077
      CADDY_IMAGE="$(caddy_image)" \
      DJB_PROJECT_NAME="$(derived_project_name)" \
      DJB_IMAGE_TAG="$(image_tag)" \
      DJB_IMAGE_REGISTRY_SLOT="$( [ "$environment" = "laptop" ] && printf 'local' || printf '%s' "${DJB_IMAGE_REGISTRY:-}" )" \
      DJB_DEFERRED_SENTINEL="$(deferred_sentinel)" \
      DJB_ADOPT_FROM="$adopt" \
      "$PYTHON_BIN" - "$HERE" "$out" "$environment" <<'PYTHON'
from __future__ import annotations

import base64
import os
import secrets
import subprocess
import sys
from pathlib import Path

here, out, environment = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

# Derived by the shell above, where git lives. Required, not defaulted: a
# generated env file with no project name is one that silently shares a stack.
project_name = os.environ["DJB_PROJECT_NAME"]
image_tag = os.environ["DJB_IMAGE_TAG"]
# The repository prefix every image name is composed from (ADR deploy-4). The
# shell resolved it: `local` for the laptop (a purely local name no registry is
# consulted for), otherwise whatever the operator exported — EMPTY when they
# exported nothing, which is a deliberate refusal at `up` rather than a guess
# here. `deploy/compose.yaml`'s `${DJB_IMAGE_REGISTRY:?…}` is where it lands.
image_registry = os.environ["DJB_IMAGE_REGISTRY_SLOT"]
# Read out of deploy/entrypoint.sh by the shell above. See DEFERRED_SENTINEL.
deferred_sentinel = os.environ["DJB_DEFERRED_SENTINEL"]

# --- what each environment overrides ----------------------------------------
# `staging` is the manifest itself. `prod` layers its own delta file over it.
# `laptop` is declared HERE rather than as a third `.example`, because it is not
# an environment anybody deploys — it is the proof harness for this compose, and
# a third manifest file would be a third thing to keep in step for a target that
# exists only while somebody is looking at it.
LAPTOP = {
    "SITE_ADDRESS": "localhost",
    "AUTH_ADDRESS": "auth.localhost",
    "O11Y_ADDRESS": "o11y.localhost",
    # Caddy's own CA. No ACME, no port 80, no DNS, no rate limit — the whole
    # reason the laptop proof needs nothing outside the laptop.
    "CADDY_TLS": "internal",
    "ALLOWED_HOSTS": "localhost,127.0.0.1",
    "CSRF_TRUSTED_ORIGINS": "https://localhost",
    "PUBLIC_BASE_URL": "https://localhost",
    "ZITADEL_EXTERNALDOMAIN": "auth.localhost",
    "ZITADEL_ISSUER": "https://auth.localhost",
    "ZITADEL_ADMIN_USERNAME": "zitadel-admin@localhost",
    # The `db` service (profiles: ["laptop"]) rather than an RDS endpoint, and
    # no TLS to it: it is a container on a bridge network that does not leave
    # this machine. A real environment sets DATABASE_SSLMODE=require and means it.
    "DATABASE_HOST": "db",
    "DATABASE_SSLMODE": "disable",
    "PGSSLMODE": "disable",
    "DATABASE_NAME": "djb_laptop",
    "DATABASE_URL": "",
    # The `db` container accepts plaintext; RDS does not. Same override as the
    # three SSL-mode lines above, for the one consumer whose switch is its own.
    "TEMPORAL_SQL_TLS": "false",
    "TEMPORAL_TASK_QUEUE": "djb-laptop",
    "DJB_ENVIRONMENT": "laptop",
    "DEFAULT_FROM_EMAIL": "no-reply@localhost",
    "SERVER_EMAIL": "no-reply@localhost",
    # The staging manifest names a real ESP (ADR comms-12) and the laptop must
    # not inherit it: a laptop proof that reached a provider would be a laptop
    # that can email a real person, and one with the slot empty would fail every
    # send with a credential error nobody asked for. The console backend is the
    # honest laptop answer — it accepts, prints, and reaches nobody.
    "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
    "DJB_SECRETS_SOURCE": "file:/deploy/.env",  # pragma: allowlist secret
    # --- the prober's two laptop-only answers -------------------------------
    # `deploy/env.staging.example` promises both of these in prose beside the
    # slots ("the laptop generator sets 1", "the laptop generator fills it"), so
    # they belong HERE rather than in a runbook step somebody has to remember.
    #
    # PROBE_INSECURE: Caddy signs with its own internal CA on a laptop
    # (CADDY_TLS=internal, three lines up), and curl will not verify that. On a
    # box it stays 0 and means it: a prober that skipped verification would not
    # be probing the path a browser takes.
    #
    # PROBE_CONNECT_TO: inside a container `localhost` IS the container, so a
    # laptop probe of `https://localhost/readyz` would probe the prober. curl's
    # `--connect-to <host:port:connect-to-host:port>` opens the socket to the
    # `caddy` container while the Host header and the TLS SNI stay `localhost`,
    # so TLS, Caddy's site block and the reverse proxy are all still in the
    # tested path — only public DNS is not, and on a box it is, because there
    # this slot is empty. See deploy/observability/alerts/prober.sh's header.
    "PROBE_INSECURE": "1",
    "PROBE_CONNECT_TO": "localhost:443:caddy:443",
    # --- the laptop's namespace ---------------------------------------------
    # THE ONE ENVIRONMENT WHERE A VALUE IS HONEST RATHER THAN A GUESS. A laptop
    # has no AWS account, no bucket, no role and no secret prefix; the only
    # consumer that reaches it here is `apply.py`, which names the alert bundle
    # in the laptop's own ClickStack. Filling it is therefore not a fallback to
    # anybody's real namespace — it is the laptop's own, and it is `laptop` so
    # that a bundle created under it says out loud which environment made it.
    # `staging` and `prod` inherit the EMPTY staging slot and refuse, which is
    # the whole point.
    "DJB_DEPLOY_NAMESPACE": "laptop",
}

# --- the generated population ------------------------------------------------
# A slot in this table is filled by the generator and by nothing else. A slot
# NOT in it and still empty after the merge is a refusal, not a default: an
# empty ALLOWED_HOSTS is a deployment that will not start, and finding that out
# at container boot rather than here wastes the boot.
def hex32() -> str:
    return secrets.token_hex(32)


def fernet() -> str:
    # The same thing `cryptography.fernet.Fernet.generate_key()` produces —
    # 32 random bytes, urlsafe-base64 — without importing cryptography, so this
    # generator runs on a box that has python and nothing installed.
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


def password(length: int = 40) -> str:
    # urlsafe alphabet: no quoting hazard in an env file, a URL, a psql
    # connection string or a compose substitution. Length over character-class
    # theatre.
    return secrets.token_urlsafe(length)[:length]


def zitadel_masterkey() -> str:
    # EXACTLY 32 characters or Zitadel refuses to start.
    return secrets.token_urlsafe(64)[:32]


def zitadel_admin_password() -> str:
    # Zitadel's default complexity policy wants upper, lower, digit and symbol.
    # Generated, not chosen, and the four classes are appended rather than
    # hoped for.
    return password(32) + "aA1!"


GENERATED = {
    "SECRET_KEY": hex32,
    "CONNECTIONS_ENCRYPTION_KEY": fernet,
    "POSTGRES_PASSWORD": password,
    "DATABASE_PASSWORD": password,
    "ZITADEL_DATABASE_PASSWORD": password,
    "ZITADEL_MASTERKEY": zitadel_masterkey,
    "ZITADEL_ADMIN_PASSWORD": zitadel_admin_password,
    # The search engine's master key. GENERATED rather than DEFERRED because
    # both sides read it out of this one file — `deploy/compose.yaml` hands it to
    # the container and the app dials with it — so a generated value is correct
    # end to end with no human step, exactly like POSTGRES_PASSWORD. NOT
    # `ADOPTED`: Meilisearch takes the key at start-up rather than baking it into
    # the index, so a regenerate that both sides read stays consistent.
    "MEILI_MASTER_KEY": password,
}

# --- ADOPTED: facts about a world that ALREADY EXISTS ------------------------
# WHAT THIS CLOSES. `env-file` regenerates every GENERATED slot on every run.
# For a FRESH environment that is exactly right. For an environment that is
# already up it is a quiet catastrophe: `POSTGRES_PASSWORD` is the RDS MASTER
# password, nothing in the deploy path ever re-applies it to RDS, so a second
# `env-file` produces a file that cannot authenticate to the instance that
# exists — `migrate` fails and the box is locked out of its own database. A
# re-ship that forgets to carry the value over is a bricked environment.
#
# THE SHAPE, ONE LEVEL DOWN: read what is already true and keep it.
# If the OUTPUT FILE already exists and holds a non-empty value for one of the
# names below, that value is carried forward and the run says so. A fresh
# environment has no such file, so nothing changes for a first provision — the
# preservation cannot fire where there is nothing to preserve.
#
# WHY THESE FOUR AND NOT ALL SEVEN. The test is not "is it a secret", it is
# "does something OUTSIDE this file already know it":
#
#   POSTGRES_PASSWORD           RDS holds it. Nothing re-applies it.
#   CONNECTIONS_ENCRYPTION_KEY  every stored credential is Fernet-encrypted
#                               with it; a new key cannot read the old rows.
#   ZITADEL_MASTERKEY           Zitadel encrypted its own data with it.
#   ZITADEL_ADMIN_PASSWORD      the account exists at the identity platform
#                               with the old one; a new value is just wrong.
#
# `SECRET_KEY` and `DATABASE_PASSWORD` deliberately still rotate: sessions are
# disposable, and the app role's password is re-applied by the release step's
# `grants.sql.py` in the same performance. `ZITADEL_DATABASE_PASSWORD` rotates
# too — Zitadel's own database role is created by its init from this value.
#
# `env-file` MAKES NO AWS CALLS and this does not change that: the truth is
# read from the file on disk, never from the vault.
ADOPTED = (
    "POSTGRES_PASSWORD",
    "CONNECTIONS_ENCRYPTION_KEY",
    "ZITADEL_MASTERKEY",
    "ZITADEL_ADMIN_PASSWORD",
)

# Where the already-true values are read from: `--adopt <file>` when the
# operator named one, otherwise the output path itself when it already exists
# (the in-place regenerate). A fresh environment has neither, so nothing is
# adopted and a first provision is untouched.
adopt_from = os.environ.get("DJB_ADOPT_FROM", "")
source = Path(adopt_from) if adopt_from else out
existing: dict[str, str] = {}
if source.exists():
    for line in source.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, raw = line.partition("=")
            existing[key.strip()] = raw.strip().strip("'")

# --- the one slot that ships UNFILLED, on purpose ----------------------------
# A GENERATED value here is not a secret, it is a WRONG ANSWER. ClickStack's
# all-in-one image mints its OWN ingestion key during the first-run setup a
# human performs in the UI (runbook Part 9, step 53) and enforces it, so the key
# travels UI → env file and never the other way. While the generated value sat
# in this slot the sink refused every batch, the collector dropped them after
# its retry budget, and the stack looked perfectly healthy the whole time —
# O1′'s finding, and the exact failure this table now refuses to produce.
#
# It cannot simply be EMPTY: `deploy/compose.yaml` reads it as
# `${CLICKSTACK_API_KEY:?…}` on two services, and the stack has to be up before
# the UI that mints the key exists. So the slot ships carrying a sentinel that
# says out loud that it is not filled in yet. `deploy/entrypoint.sh` declares
# that sentinel, accepts it on THIS NAME ONLY, and refuses to start any
# container where a second slot carries it.
DEFERRED_SENTINEL = {
    "CLICKSTACK_API_KEY": "runbook Part 9 step 54 — the key ClickStack's UI mints at first-run setup",
}

# Slots that are legitimately empty until a later step or a later rung fills
# them, each with the thing that fills it. Anything empty and not named here
# stops the generator.
DEFERRED = {
    # THE ACCOUNT-LEVEL NAMESPACE. Not generated and not defaultable: it is a
    # fact about an AWS account, and the ONE value this generator could produce
    # (a guess) is the one value that must never reach a script — every
    # coordinate composed from it addresses real resources, and a wrong one
    # succeeds. So the slot ships EMPTY, this environment's vault blob carries
    # it, and every consumer refuses rather than falls back
    # (`require_namespace` above, `deploy/ship.sh`, `deploy/teardown.sh`,
    # `deploy/observability/alerts/apply.py`). The laptop overrides it below,
    # where there is no account to be wrong about.
    "DJB_DEPLOY_NAMESPACE": "the operator, out of this environment's vault blob — there is no default (deploy/env.staging.example says why)",
    "ZITADEL_PAT": "the runbook's identity step, out of the zitadel_bootstrap volume",
    "ZITADEL_CLIENT_ID": "manage.py zitadel_seed, printed once",
    # detect-secrets reads `<secret-shaped name>: <string>` as an assignment. On the six
    # pragma'd lines below — and on one in LAPTOP above — what it is actually reading is a
    # NAME and a sentence about which step fills that slot. There is no value on any of
    # them, and there structurally cannot be: `DEFERRED` maps an EMPTY slot to its owner,
    # and every real value is produced by `secrets.token_*` at run time and written
    # straight into a mode-600 file this repository ignores.
    #
    # Line-scoped by convention, and deliberately not a baseline entry: a pragma
    # on a line that could ever hold a real value is a smuggling lane, so these sit only
    # on lines whose value is prose.
    "ZITADEL_CLIENT_SECRET": "manage.py zitadel_seed, printed once",  # pragma: allowlist secret
    "ZITADEL_MCP_AUDIENCE": "manage.py zitadel_seed (the project id)",
    "ZITADEL_DEV_USER_EMAIL": "nothing: DEBUG is off, so zitadel_seed refuses the dev user by design",
    "ZITADEL_DEV_USER_PASSWORD": "nothing: same refusal",  # pragma: allowlist secret
    "GOOGLE_OAUTH_CLIENT_ID": "the Google Cloud OAuth client",
    "GOOGLE_OAUTH_CLIENT_SECRET": "the Google Cloud OAuth client",  # pragma: allowlist secret
    "GOOGLE_WORKSPACE_DOMAINS": "the owner's domain list; empty DISABLES the provider",
    "ANYMAIL_RESEND_API_KEY": "the Resend dashboard, an API key with sending access",  # pragma: allowlist secret
    "EMAIL_HOST": "nothing: the SMTP settings are dead under an anymail backend (ADR comms-12)",
    "EMAIL_HOST_USER": "nothing: same",
    "EMAIL_HOST_PASSWORD": "nothing: same",  # pragma: allowlist secret
    "AWS_STORAGE_BUCKET_NAME": "provision.sh infra, which creates the bucket",
    "AWS_S3_ENDPOINT_URL": "nothing: empty means real S3",
    "AWS_S3_CUSTOM_DOMAIN": "nothing: empty means the bucket's own hostname",
    "AWS_ACCESS_KEY_ID": "nothing, ever: the box has an instance role",
    "AWS_SECRET_ACCESS_KEY": "nothing, ever",  # pragma: allowlist secret
    "CADDY_TLS": "the runbook's TLS step (an ACME account email)",
    "DATABASE_HOST": "provision.sh infra, which creates the RDS instance",
    "DATABASE_URL": "nothing: the parts govern, and PGSSLMODE carries the TLS answer",
    "CORS_ALLOWED_ORIGINS": "a product with a browser front end on another origin",
    "O11Y_PASSWORD_HASH": "this generator, below",  # pragma: allowlist secret
    # --- the alert route's destination, and the prober's box-side default ----
    # SLACK_WEBHOOK_URL is a real Slack incoming webhook, whose URL a
    # deployment supplies; on a laptop it is the dummy receiver
    # (`http://alerts-dummy:9099/hook`,
    # deploy/observability/alerts/compose.sink.yaml). It is DEFERRED rather than
    # GENERATED for the obvious reason — nobody can generate somebody else's
    # webhook — and EMPTY IS A DISARMED HALF, not a silent default: the prober
    # says so out loud once per start, and `apply.py` refuses rather than
    # defaults. docs/runbooks/alerts.md § Installing the route owns the step.
    # The observability sink's operator account. Not generated: a human
    # chooses it at ClickStack's first-run setup (runbook Part 9 step 53) and
    # the sink is the authority on it, exactly like CLICKSTACK_API_KEY one slot
    # down. Its HOME is this environment's vault blob, never a dotfile on a box.
    "CLICKSTACK_ADMIN_EMAIL": "runbook Part 9 step 53 — the operator account registered at first-run setup",
    "CLICKSTACK_ADMIN_PASSWORD": "runbook Part 9 step 53 — chosen with the account; apply.py/export.py refuse without it",  # pragma: allowlist secret
    "SLACK_WEBHOOK_URL": "the Slack incoming webhook (a laptop: the dummy receiver); empty DISARMS the prober's deaf-sink half",  # pragma: allowlist secret
    # EMPTY ON A BOX IS THE ANSWER, not a slot waiting for one: with it unset
    # the prober resolves the site's public name itself, so DNS is in the tested
    # path. Only the laptop fills it, from LAPTOP above.
    "PROBE_CONNECT_TO": "nothing on a box: empty is what puts public DNS in the probe's path (the laptop generator fills it)",
    # `env.staging.example` ships the template's own two shipped
    # comms fakes here; `env.prod.example` overrides the slot to EMPTY, which is
    # the full release wall and the right default for a product. Empty is the
    # ANSWER rather than a slot waiting for one, so it is DEFERRED with "nothing"
    # as its owner — AWS_S3_ENDPOINT_URL's shape exactly.
    "DJB_ACCEPTED_FAKES": "nothing: empty is the whole wall — a key here is a fake this deployment knowingly stands on, printed on every release",
}


def parse(path: Path) -> list[tuple[str, str] | str]:
    """Lines, keeping comments and blanks so the generated file reads like the
    manifest it came from. A file of bare KEY=VALUE with every reason stripped
    out is the file nobody can safely edit at 3am."""
    parsed: list[tuple[str, str] | str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            parsed.append(line)
            continue
        name, sep, value = line.partition("=")
        if sep:
            parsed.append((name.strip(), value.strip()))
        else:
            parsed.append(line)
    return parsed


manifest = parse(here / "env.staging.example")

overrides: dict[str, str] = {}
if environment == "prod":
    for item in parse(here / "env.prod.example"):
        if isinstance(item, tuple):
            overrides[item[0]] = item[1]
elif environment == "laptop":
    overrides = dict(LAPTOP)
elif environment != "staging":
    raise SystemExit(f"!! provision: unknown environment {environment!r}: laptop, staging or prod")

# --- the o11y wall's bcrypt hash --------------------------------------------
# Generated here so the plaintext exists in exactly one place for exactly as
# long as this process runs, and is printed once at the end. The hash goes in
# the file; the password does not.
o11y_plaintext = password(24)
caddy_image = os.environ.get("CADDY_IMAGE", "")
try:
    hashed = subprocess.run(
        ["docker", "run", "--rm", "-i", caddy_image,
         "caddy", "hash-password", "--plaintext", o11y_plaintext],
        capture_output=True, text=True, check=True, timeout=120,
    ).stdout.strip()
except Exception as error:
    raise SystemExit(
        f"!! provision: could not hash the observability password with {caddy_image!r} "
        f"({type(error).__name__}: {error}).\n"
        "   `caddy hash-password` is bcrypt and this generator will not ship a "
        "weaker stand-in. Pull the image and re-run."
    ) from error
overrides["O11Y_PASSWORD_HASH"] = hashed

def emit(name: str, value: str) -> str:
    """`NAME='value'` — SINGLE-quoted, and that is load-bearing twice over.

    `docker compose` runs its own `${...}` interpolation over an env file's
    values, and a bcrypt hash is `$2a$14$...`: unquoted, compose reads `$14` as
    a variable, warns about it, and hands Caddy a truncated hash that rejects
    every password forever. Single quotes make compose take the value
    literally, and they make `set -a; . file` in deploy/entrypoint.sh take it
    literally too — one encoding both readers agree on. Verified against
    Compose v2.33 rather than assumed.

    A value containing a single quote is refused rather than escaped: no dotenv
    parser agrees on how `'\\''` should behave, and a credential that survives
    one reader and not the other is worse than one that stops the generator.
    """
    if "'" in value:
        raise SystemExit(
            f"!! provision: {name} contains a single quote. deploy/.env is read by "
            "docker compose's dotenv parser and by a shell, and they do not agree "
            "on how to escape one. Generate or choose a value without it."
        )
    if "\n" in value:
        raise SystemExit(f"!! provision: {name} contains a newline; an env file cannot carry one")
    return f"{name}='{value}'"


lines: list[str] = [
    "# GENERATED by deploy/provision.sh env-file. Do not edit by hand.",
    f"# Environment: {environment}. Every secret here was generated by a machine;",
    "# no human typed one, and no value in it has ever been in a report.",
    "#",
    "# Every value is single-quoted so that docker compose's interpolation and a",
    "# shell's `.` read the same bytes — see `emit` in deploy/provision.sh.",
    "#",
    "# Mode 600, and it belongs on exactly one box. deploy/teardown.sh removes it.",
    "",
    "# --- WHOSE STACK THIS IS -----------------------------------------------",
    "# Read by `docker compose` itself, out of this file, with nothing threaded",
    "# through the command line: every `docker compose -f deploy/compose.yaml`",
    "# run from this checkout lands on THIS project and no other checkout's.",
    "# Derived from the checkout's path (deploy/provision.sh derived-project-name); the",
    "# ONE escape is exporting COMPOSE_PROJECT_NAME, which outranks this line.",
    emit("COMPOSE_PROJECT_NAME", project_name),
    "",
    "# What the two images are tagged. Never `latest` — the tree hash says which",
    "# tree the image came from, and it is the SAME tag in every environment,",
    "# because promotion is not a re-tag (ADR deploy-4).",
    "#     ./deploy/provision.sh image-tag",
    emit("DJB_IMAGE_TAG", image_tag),
    "",
    "# --- WHERE THE IMAGES COME FROM ----------------------------------------",
    "# The repository prefix `deploy/compose.yaml` composes every image name",
    "# from: '<registry>/web:<tag>' and '<registry>/worker:<tag>'. For ECR that",
    "# is '<account>.dkr.ecr.<region>.amazonaws.com/<namespace>'; on a laptop it",
    "# is the bare local prefix 'local', which no registry is consulted for.",
    "#",
    "# EMPTY IS A REFUSAL, NEVER A FALLBACK. A guessed registry pulls somebody",
    "# else's image and succeeds. `provision.sh up` refuses on an empty slot and",
    "# so does compose's own `${DJB_IMAGE_REGISTRY:?…}`.",
    "#     ./deploy/provision.sh image-ref web",
    emit("DJB_IMAGE_REGISTRY", image_registry),
    "",
]

missing: list[str] = []
adopted_kept: list[str] = []
for item in manifest:
    if isinstance(item, str):
        lines.append(item)
        continue
    name, value = item
    if name in overrides:
        value = overrides[name]
    elif name in ADOPTED and existing.get(name):
        # Already true out there. Kept, and said out loud below.
        value = existing[name]
        adopted_kept.append(name)
    elif name in GENERATED:
        value = GENERATED[name]()
    elif name in DEFERRED_SENTINEL:
        value = deferred_sentinel
    if (
        value == ""
        and name not in DEFERRED
        and name not in GENERATED
        and name not in DEFERRED_SENTINEL
    ):
        missing.append(name)
    lines.append(emit(name, value))

if missing:
    raise SystemExit(
        "!! provision: these variables are empty and nothing claims to fill them: "
        + ", ".join(missing)
        + "\n   Add them to env.staging.example with a value, to GENERATED if they "
        "are secrets, to DEFERRED with the step that fills them, or to "
        "DEFERRED_SENTINEL if the deployment must boot before that step can run. "
        "An empty slot with no owner is a boot failure with no explanation."
    )

out.write_text("\n".join(lines) + "\n", encoding="utf-8")
out.chmod(0o600)

print(f"provision: wrote {out} ({len(GENERATED) - len(adopted_kept)} secrets generated, mode 600)")
if adopted_kept:
    print(
        f"provision: ADOPTED {len(adopted_kept)} value(s) from {source.name} "
        "rather than regenerating them — something outside this file already knows them:"
    )
    for name in adopted_kept:
        print(f"provision:   {name}")
    print(
        "provision: (POSTGRES_PASSWORD is RDS's master and nothing re-applies it, "
        "so regenerating it locks the box out of its own database.)"
    )
for name, owner in sorted(DEFERRED_SENTINEL.items()):
    print(f"provision: {name} ships DEFERRED — filled by {owner}")
print("")
print("provision: the observability wall's password, printed ONCE and stored nowhere:")
print(f"    user     {overrides.get('O11Y_USER', 'observer')}")
print(f"    password {o11y_plaintext}")
print("")
PYTHON
    )

    # The belt, over what was just generated. Two things at once: it proves the
    # generator produced nothing published, and it proves
    # the belt is wired before anybody depends on it at boot.
    "$HERE/assert_not_published.sh" "$out"
    say "assert_not_published: clean over $out"
}

# =============================================================================
# secrets-put / secrets-fetch — Secrets Manager, per-environment prefix
# =============================================================================

cmd_secrets_put() {
    local prefix="${1:-}" file="${2:-}"
    [ -n "$prefix" ] && [ -n "$file" ] || usage
    [ -f "$file" ] || die "no such env file: $file"
    command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"
    case "$prefix" in */) ;; *) die "prefix must end in / — e.g. \"\$DJB_DEPLOY_NAMESPACE/staging/\"" ;; esac

    # ONE SECRET, ONE JSON OBJECT, under `<prefix>env`. Not one secret per
    # variable: Secrets Manager bills per secret per month (the cost table's
    # ~8 × $0.40 line was written before this shape), and more importantly a
    # deployment's environment is one atomic thing — half-updated is a state
    # nobody wants to reason about at 3am.
    #
    # THE VALUE GOES OVER STDIN, never as an argument: `aws ... --secret-string
    # "$(cat file)"` puts every credential in this deployment into the process
    # table and into this shell's history file.
    local id="${prefix}env"
    local payload
    payload="$("$PYTHON_BIN" - "$file" <<'PYTHON'
import json, sys
from pathlib import Path

values = {}
for raw in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[len("export "):].strip()
    name, sep, value = line.partition("=")
    if not sep:
        continue
    value = value.strip()
    # THE VAULT HOLDS THE VALUE, NOT THE FILE'S ENCODING. Every file this
    # reads was written by `env-file`'s `emit` or by `secrets-fetch`, and both
    # SINGLE-QUOTE every value so that docker compose's interpolation and a
    # shell's `.` read the same bytes. Stored with those quotes still on, the
    # round trip breaks in a way neither end can see alone: `secrets-fetch`
    # reads back a value containing a literal quote and refuses to write "an
    # env file whose two readers would disagree about it" — which is exactly
    # right, and which stops the runbook at its secrets step on a box —
    # `secrets-put` and `secrets-fetch` have to have met for the pair to work.
    #
    # Exactly ONE matching pair, and only a pair `emit` could have added:
    # stripping greedily would quietly change a value that genuinely begins
    # and ends with a quote character.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    values[name.strip()] = value
print(json.dumps(values, separators=(",", ":"), sort_keys=True))
PYTHON
)"

    if aws secretsmanager describe-secret --secret-id "$id" >/dev/null 2>&1; then
        say "updating $id"
        aws secretsmanager put-secret-value \
            --secret-id "$id" \
            --secret-string file:///dev/stdin <<<"$payload" >/dev/null
    else
        say "creating $id"
        aws secretsmanager create-secret \
            --name "$id" \
            --description "Pilecap deployment environment (deploy/provision.sh)" \
            --secret-string file:///dev/stdin <<<"$payload" >/dev/null
    fi
    say "stored: $id"
}

cmd_secrets_fetch() {
    local prefix="${1:-}" out="${2:-}"
    [ -n "$prefix" ] && [ -n "$out" ] || usage
    command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"
    case "$prefix" in */) ;; *) die "prefix must end in / — e.g. \"\$DJB_DEPLOY_NAMESPACE/staging/\"" ;; esac

    # This is what a box runs, as its instance role, to materialize the compose
    # env file. `entrypoint.sh` fetches the APP's own variables itself when the
    # runtime image can; the ORGANS need theirs in a file compose can substitute
    # from, and this is where that file comes from.
    #
    # The formatter is a process substitution rather than `python -c '...'`
    # because the program itself has to contain single quotes (it writes them
    # around every value) and a `-c` argument is already inside a pair. Stdin
    # stays the pipe, which is where the secret is: it never becomes an
    # argument and never becomes a file.
    # Unlink rather than truncate, so a re-fetch starts from nothing: a run
    # that dies mid-write leaves no file at all rather than half an
    # environment, and the group/mode this function sets at the end are
    # re-applied from a known state every time.
    rm -f "$out"
    ( umask 077
      aws secretsmanager get-secret-value --secret-id "${prefix}env" \
          --query SecretString --output text \
      | "$PYTHON_BIN" <(cat <<'PYTHON'
import json
import sys

values = json.load(sys.stdin)
print("# FETCHED by deploy/provision.sh secrets-fetch. Do not edit by hand.")
print("# Single-quoted for the same reason the generator quotes: compose")
print("# interpolates an env file, and a bcrypt hash is full of dollar signs.")
for key in sorted(values):
    value = str(values[key])
    if "'" in value or "\n" in value:
        raise SystemExit(
            f"!! provision: {key} carries a quote or a newline; refusing to write "
            "an env file whose two readers would disagree about it"
        )
    print(f"{key}='{value}'")
PYTHON
) > "$out" )
    chmod 600 "$out"
    say "wrote $out (mode 600)"

    "$HERE/assert_not_published.sh" "$out"
    say "assert_not_published: clean over $out"

    # --- and now let the OTHER reader in -------------------------------------
    # THIS FILE HAS TWO READERS ON A BOX, and 600 serves only one of them.
    #
    #   the account running the runbook   `docker compose` interpolates
    #                                     ${DATABASE_HOST} and friends out of
    #                                     deploy/.env, and it does that as
    #                                     whoever typed the command.
    #   uid 10001                         `deploy/` is bind-mounted read-only
    #                                     into `web` and `worker`, which run as
    #                                     the unprivileged `djb` user the
    #                                     Dockerfile creates (uid/gid 10001),
    #                                     and entrypoint.sh sources the file
    #                                     from in there.
    #
    # Owned by the runbook's account at 600, the containers restart forever on
    #
    #   /deploy/entrypoint.sh: line 106: /deploy/.env: Permission denied
    #
    # with no other symptom; chown it to 10001 instead and `docker compose` is
    # the one locked out ("open .../deploy/.env: permission denied"). Neither
    # happens on a Mac, because Docker Desktop's file sharing presents a
    # bind-mounted file as owned by the container's user whatever the host
    # says. On Linux the uid is the uid — which is why the laptop proof was
    # green and the first real box was not.
    #
    # So: keep the owner, add the GROUP, and open exactly the group bit.
    # 640 root:10001-style — readable by the two readers it has and by no
    # third account on the box. Still never world-readable; `teardown.sh`
    # still removes it.
    local runtime_gid="${DJB_RUNTIME_GID:-10001}"
    local chgrp_cmd=""
    if [ "$(id -u)" = "0" ]; then
        chgrp_cmd="chgrp"
    elif command -v sudo >/dev/null 2>&1 && sudo -n true 2>/dev/null; then
        chgrp_cmd="sudo chgrp"
    else
        # Loud, and it names the exact commands — a silent skip here is the
        # restart loop above, found ten minutes later in a container log.
        die "wrote $out but cannot give group $runtime_gid read access, and that group is the uid web/worker run as. Without it both containers restart forever on 'Permission denied' and nothing else says why. Run: sudo chgrp $runtime_gid $out && chmod 640 $out"
    fi
    $chgrp_cmd "$runtime_gid" "$out"
    chmod 640 "$out"
    say "group $runtime_gid, mode 640 over $out (web/worker read it as that gid; compose reads it as you)"
}

# =============================================================================
# up — bring THIS box's stack up, and refuse to bring a second one up beside it
# =============================================================================
# WHY THIS IS A SUBCOMMAND AND NOT `docker compose up -d` IN THE RUNBOOK. The
# derived project name (`djb_deploy_<8 hex of the checkout's path>`) is right,
# and it ORPHANS EVERY BOX THAT WAS DEPLOYED BEFORE IT EXISTED. Staging's stack
# was brought up as `djb-deploy`, from a `.env` written before the line existed;
# the re-deploy shipped a fresh tree, generated a fresh env file, derived a
# different name, and `docker compose up -d` cheerfully started A SECOND FULL
# STACK beside the running one — same box, same ports, same database.
#
# Two rules, and they are the `scripts/kill_mine.sh` refusal in compose's
# vocabulary:
#
#   1. THE RUNNING PROJECT WINS OVER THE DERIVATION. If exactly one project
#      brought up from THIS checkout's `deploy/` is running, that is this box's
#      stack whatever a freshly generated `.env` says, and its name is written
#      into `.env` so every later bare `docker compose` lands on it too. A
#      re-deploy migrates the name instead of forking the box.
#   2. A DELIBERATE SECOND NAME BESIDE A RUNNING ONE IS REFUSED, exit 2, naming
#      both. An exported `COMPOSE_PROJECT_NAME` is the one escape everywhere
#      else in this deployment; here it is the exact shape of the accident, so
#      it has to be argued with rather than obeyed. `--second` says "I mean it"
#      out loud — that is what a restore drill does, and it is a different sentence
#      from the one somebody types by accident during a re-deploy.
#
# WHAT IT CANNOT SEE, declared: it reads `docker compose ls`, so a stack somebody
# started with `docker run` by hand, or with a compose file from another path, is
# not seen. Ownership is proved from the CONFIG FILES compose itself records —
# a project whose first config file is this checkout's `deploy/compose.yaml`.

# Every RUNNING compose project on this machine whose config files include this
# checkout's compose.yaml. One name per line; empty means none.
#
# The payload travels as an ARGUMENT, not on stdin: `python -` reads its program
# from stdin, so a pipe and a heredoc into one command make a program that reads
# its own source as data. Project names and file paths are not secrets, so `ps`
# is not an argument here (it very much is in `secrets-put`, which is why that
# one uses stdin).
running_projects_here() {
    "$PYTHON_BIN" - "$HERE/compose.yaml" \
        "$(docker compose ls --format json 2>/dev/null)" <<'PYTHON'
import json, sys

wanted, payload = sys.argv[1], sys.argv[2]
try:
    projects = json.loads(payload)
except Exception:
    # A docker that could not answer is NOT "no projects". Exit 2 so the caller
    # refuses rather than proceeding on a silence it mistook for an absence.
    raise SystemExit(2)
for project in projects:
    files = str(project.get("ConfigFiles", "")).split(",")
    if any(entry.strip() == wanted for entry in files):
        print(project.get("Name", ""))
PYTHON
}

# The name written into deploy/.env, if there is one. teardown.sh reads the same
# line the same way.
project_in_env_file() {
    [ -f "$HERE/.env" ] || return 0
    sed -n "s/^COMPOSE_PROJECT_NAME='\{0,1\}\([^']*\)'\{0,1\}$/\1/p" "$HERE/.env" | head -n1
}

# The image tag the env file pins, read the same way. `deploy/compose.yaml`
# interpolates `djb-web:${DJB_IMAGE_TAG}` out of THIS FILE, so this line — not
# the tag you exported to build with — decides which image actually runs.
image_tag_in_env_file() {
    [ -f "$HERE/.env" ] || return 0
    sed -n "s/^DJB_IMAGE_TAG='\{0,1\}\([^']*\)'\{0,1\}$/\1/p" "$HERE/.env" | head -n1
}

# --- THE TAG THE TREE SAYS, AND THE TAG THE FILE PINS -------------------------
# A RE-DEPLOY BUILT A NEW IMAGE AND RAN THE OLD ONE. Found on staging: the tree
# was re-shipped (step 30), the images were rebuilt (step 33) against an exported
# `DJB_IMAGE_TAG`, and `up` then started `djb-web:<the previous tag>` — because
# `deploy/.env` is what compose interpolates from, and step 31's `secrets-fetch`
# had just restored that file from the vault carrying the tag stored at the LAST
# deploy. Nothing failed. `/` served the old code, the runbook's proof read
# false, and the only witness was `docker inspect`.
#
# THE TREE IS THE TRUTH. `image_tag()` is derived from the tree that is on this
# box right now (git where git exists, the archive's TREE file where it does
# not), so a disagreement means the file is stale, never the tree. This adopts
# the tree's tag and says so — the same shape the project-name migration above
# uses, and for the same reason: a re-deploy should MIGRATE the pin rather than
# fork off it.
#
# It refuses, rather than adopting, when no image for this tree can be got: the
# alternative is `up` dying on a missing image with compose's own message, which
# does not say which step was skipped.
#
# WHAT THE REGISTRY MOVE CHANGED HERE. The check used to be `docker image inspect` on a
# LOCALLY BUILT tag, because the box built its own images at runbook step 33.
# The box builds nothing now — CI does, once, multi-arch — so the honest
# question is "can this box GET the image for this tree", and the honest way to
# ask it is to try the pull. A local hit short-circuits it (the laptop proof
# builds its own and never reaches a registry), a pull satisfies it, and only a
# tree no registry has is a refusal.
reconcile_image_tag() {
    local tree_tag file_tag service ref missing=""
    tree_tag="$(image_tag)"
    file_tag="$(image_tag_in_env_file)"
    [ -n "$tree_tag" ] || return 0
    [ "$tree_tag" != "$file_tag" ] || return 0

    for service in $IMAGE_SERVICES; do
        ref="$(image_ref "$service" "$tree_tag")" || exit 2
        docker image inspect "$ref" >/dev/null 2>&1 && continue
        say "pulling $ref"
        docker pull "$ref" >/dev/null 2>&1 && continue
        missing="$missing $ref"
    done

    if [ -n "$missing" ]; then
        echo "!! provision: REFUSED." >&2
        echo "   this tree is    $tree_tag" >&2
        echo "   the env file    ${file_tag:-<none>}" >&2
        echo "" >&2
        echo "   Neither this machine nor the registry has:" >&2
        printf '     %s\n' $missing >&2
        echo "" >&2
        echo "   Bringing the stack up would either run the OLD image the env file" >&2
        echo "   pins or die on a missing one. THE BOX DOES NOT BUILD (ADR deploy-4):" >&2
        echo "   the image for a tree is built once, in CI, and pushed. So either" >&2
        echo "   this tree never reached a green CI run, or you are pointed at the" >&2
        echo "   wrong registry:" >&2
        echo "" >&2
        echo "     ./deploy/provision.sh image-ref web       # what is being looked for" >&2
        echo "     grep DJB_IMAGE_REGISTRY deploy/.env       # where it is being looked for" >&2
        echo "" >&2
        echo "   Nothing was started." >&2
        exit 2
    fi

    say "adopting this tree's image tag $tree_tag (env file pinned ${file_tag:-<none>})"
    if [ -n "$file_tag" ]; then
        "$PYTHON_BIN" - "$HERE/.env" "$tree_tag" <<'PYTHON'
import sys
from pathlib import Path

path, tag = Path(sys.argv[1]), sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
out = [
    f"DJB_IMAGE_TAG='{tag}'" if line.startswith("DJB_IMAGE_TAG=") else line
    for line in lines
]
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PYTHON
    else
        printf "DJB_IMAGE_TAG='%s'\n" "$tree_tag" >> "$HERE/.env"
    fi
    say "wrote DJB_IMAGE_TAG=$tree_tag into $HERE/.env"
}

cmd_up() {
    local second=""
    if [ "${1:-}" = "--second" ]; then second="--second"; shift; fi
    command -v docker >/dev/null 2>&1 || die "no 'docker' on PATH"
    [ -f "$HERE/.env" ] || die "no $HERE/.env. Generate one (provision.sh env-file) or fetch one (provision.sh secrets-fetch) before bringing a deployment up."

    # Before anything is started: make the env file pin the image this tree
    # actually is. Refuses if that image was never built.
    reconcile_image_tag

    local running exported in_file derived
    running="$(running_projects_here)" || die "could not read 'docker compose ls'. A monitor that cannot see the machine may not act on it; nothing was started."
    exported="${COMPOSE_PROJECT_NAME:-}"
    in_file="$(project_in_env_file)"
    derived="$(derived_project_name)"
    local count
    count="$(printf '%s' "$running" | grep -c . || true)"

    if [ "$count" -gt 1 ]; then
        echo "!! provision: REFUSED." >&2
        echo "   running from this checkout:" >&2
        printf '     %s\n' $running >&2
        echo "" >&2
        echo "   More than one stack from this checkout is already running. Which one a" >&2
        echo "   re-deploy means is not this script's guess to make. Tear the extra one" >&2
        echo "   down (deploy/teardown.sh --all-mine) or name the one you mean with" >&2
        echo "   COMPOSE_PROJECT_NAME=<name> and --second. Nothing was started." >&2
        exit 2
    fi

    if [ "$count" -eq 1 ]; then
        local live
        live="$(printf '%s' "$running" | head -n1)"
        if [ -n "$exported" ] && [ "$exported" != "$live" ] && [ "$second" != "--second" ]; then
            echo "!! provision: REFUSED." >&2
            echo "   already running   $live" >&2
            echo "   you asked for     $exported" >&2
            echo "   derived name      $derived" >&2
            echo "   env file says     ${in_file:-<none>}" >&2
            echo "" >&2
            echo "   Bringing that up would put a SECOND full stack on this box beside the" >&2
            echo "   running one — the same ports, the same database, the same Zitadel" >&2
            echo "   instance — which is the accident this refusal exists to stop. If" >&2
            echo "   you mean a deliberate second stack (a restore drill), say so: re-run" >&2
            echo "   with --second and a ports override. Nothing was started." >&2
            exit 2
        fi
        if [ "$second" = "--second" ] && [ -n "$exported" ] && [ "$exported" != "$live" ]; then
            say "second stack requested deliberately: $exported (beside the running $live)"
        elif [ "$live" != "$in_file" ]; then
            # THE MIGRATION. The running project is this box's stack; the env
            # file is what every later bare `docker compose` reads, so the name
            # goes in there rather than into one operator's shell.
            say "adopting the running project $live (env file said ${in_file:-<none>}, derivation says $derived)"
            if [ -n "$in_file" ]; then
                "$PYTHON_BIN" - "$HERE/.env" "$live" <<'PYTHON'
import sys
from pathlib import Path

path, name = Path(sys.argv[1]), sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
out = [
    f"COMPOSE_PROJECT_NAME='{name}'" if line.startswith("COMPOSE_PROJECT_NAME=") else line
    for line in lines
]
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PYTHON
            else
                printf "COMPOSE_PROJECT_NAME='%s'\n" "$live" >> "$HERE/.env"
            fi
            say "wrote COMPOSE_PROJECT_NAME=$live into $HERE/.env"
        else
            say "project $live (already running, and the env file agrees)"
        fi
    else
        say "no stack from this checkout is running; bringing up ${in_file:-$derived}"
    fi

    # --- THE APP PAIR IS NOT RECREATED HERE ----------------------------------
    #
    # This step used to be one `up -d` over the whole stack, and on a re-deploy
    # that recreated `web` and `worker` ON THE NEW IMAGE — one runbook step
    # BEFORE Part 5 could migrate. So every re-deploy served new code against
    # the old schema for the length of the gap. It is not theoretical and it was
    # not silent: staging measured three `reconcile_search_index` failures
    # against a missing column in a four-minute window, self-healed by Temporal's
    # retry, which is the belt and not the fix. `release.sh`'s header said
    # "within a release there is no way to open it", and that sentence was true
    # of the release and false of the runbook — the half nobody owned.
    #
    # THE RULING: the ONE recreate in a deploy is release act 6, which sits
    # after act 2's migrate. So this step reconciles everything AROUND the app
    # and leaves the app alone.
    #
    # `--no-recreate` RATHER THAN "skip the pair", and the difference is the
    # first deploy: a box that has never deployed has no `web` to leave alone,
    # and `--no-recreate` CREATES what is absent while leaving what is running
    # exactly where it is. One flag covers both paths, so there is no branch
    # here that a first deploy takes and a re-deploy does not.
    #
    # THE SERVICE LIST IS COMPOSE'S OWN, read back with the caller's own flags
    # so a `--profile laptop` up reconciles the laptop's services and a box's up
    # reconciles the box's — neither list is typed here, and a service added to
    # `compose.yaml` needs no edit in this file. `$@` is whatever the runbook
    # step needs (`--profile laptop`); the project comes from deploy/.env, which
    # this function has just made true.
    local -a compose_cmd
    compose_cmd=(docker compose --env-file "$HERE/.env" -f "$HERE/compose.yaml" "$@")

    local services others
    services="$("${compose_cmd[@]}" config --services)" \
        || die "could not read the service list out of $HERE/compose.yaml. Nothing was started."
    [ -n "$services" ] || die "$HERE/compose.yaml declares no services for these flags. Nothing was started."
    others="$(printf '%s\n' "$services" | grep -vx -e web -e worker || true)"

    if [ -n "$others" ]; then
        # shellcheck disable=SC2086  # the service list is newline-separated and must split
        "${compose_cmd[@]}" up -d $others
    fi
    "${compose_cmd[@]}" up -d --no-recreate web worker
    say "web and worker were NOT recreated here — release.sh act 6 does that, after the migrate"
}

# =============================================================================
# infra — the only subcommand that spends money
# =============================================================================

cmd_infra() {
    local environment="${1:-}" confirm="${2:-}"
    [ -n "$environment" ] || usage
    command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"
    # BEFORE the summary, not after: the summary spells every coordinate this
    # subcommand would create, and a summary printed under a guessed namespace
    # is a cost table for the wrong account.
    require_namespace

    # The approved cost table. Every line here is re-priced before purchase
    # and the actuals reported; a delta over 10% is pinged BEFORE creation, not
    # explained afterwards.
    local region="${AWS_REGION:-us-east-1}"
    local instance_type="${DJB_INSTANCE_TYPE:-t4g.large}"
    local volume_gb="${DJB_VOLUME_GB:-50}"
    local rds_class="${DJB_RDS_CLASS:-db.t4g.micro}"
    local rds_gb="${DJB_RDS_GB:-20}"
    local name="${NAMESPACE}-$environment"

    cat <<SUMMARY
provision: about to CREATE billable resources in $region

    EC2       1 x $instance_type, gp3 ${volume_gb}GB, Amazon Linux 2023 (arm64)
    RDS       $rds_class, single-AZ, ${rds_gb}GB, automated snapshots ON
    S3        s3://$name-media  and  s3://$name-backups
    SG        80/443 world, 22 owner IP only, everything else closed
    Secrets   ${NAMESPACE}/$environment/env

Re-price every line against today's list price before continuing (the
shop-the-price duty). A delta over 10% is a ping, not a decision.
SUMMARY

    [ "$confirm" = "--confirm" ] || die "refusing without --confirm. Reading this file must never be one arrow key away from spending money."

    [ -n "${DJB_OWNER_IP:-}" ] || die "DJB_OWNER_IP is unset. The ssh rule needs one address; 0.0.0.0/0 on port 22 is not a fallback."
    [ -n "${DJB_KEY_NAME:-}" ] || die "DJB_KEY_NAME is unset — the EC2 key pair to attach. A box nobody can ssh to is a box nobody can deploy."

    # --- security groups -----------------------------------------------------
    # Two, not one: the box's and the database's, so the RDS rule can name the
    # box's group rather than a CIDR. A CIDR is a promise about a subnet; a
    # group reference is a promise about a machine.
    local vpc
    vpc="$(aws ec2 describe-vpcs --region "$region" --filters Name=is-default,Values=true \
            --query 'Vpcs[0].VpcId' --output text)"
    [ "$vpc" != "None" ] || die "no default VPC in $region; name one with DJB_VPC_ID and re-run (this script does not create a VPC — that is a network design, not a provisioning step)"

    local web_sg db_sg
    web_sg="$(aws ec2 create-security-group --region "$region" --vpc-id "$vpc" \
        --group-name "$name-web" --description "$name web box" \
        --query 'GroupId' --output text)"
    db_sg="$(aws ec2 create-security-group --region "$region" --vpc-id "$vpc" \
        --group-name "$name-db" --description "$name database" \
        --query 'GroupId' --output text)"

    # 443 to the world, and 80 as well — but not for the reason this comment
    # used to give. It said the HTTP-01 challenge arrives on 80; a real box
    # then validated every certificate over TLS-ALPN-01 on 443 and never bound
    # 80 at all (deploy/Caddyfile). The rule stays because the ACME client
    # picks the challenge, not this file: an issuance method that changes under
    # a renewal should not also need a firewall change nobody remembers. An
    # open port with nothing listening accepts nothing.
    aws ec2 authorize-security-group-ingress --region "$region" --group-id "$web_sg" \
        --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null
    aws ec2 authorize-security-group-ingress --region "$region" --group-id "$web_sg" \
        --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
    aws ec2 authorize-security-group-ingress --region "$region" --group-id "$web_sg" \
        --protocol tcp --port 22 --cidr "${DJB_OWNER_IP}/32" >/dev/null

    # Postgres, from the box's group and from nowhere else. Not from the
    # owner's IP: a psql session from a laptop is an ssh tunnel through the box,
    # which is one credential to hold instead of two and one path to audit.
    aws ec2 authorize-security-group-ingress --region "$region" --group-id "$db_sg" \
        --protocol tcp --port 5432 --source-group "$web_sg" >/dev/null

    say "security groups: web=$web_sg db=$db_sg"

    # --- RDS -----------------------------------------------------------------
    # Automated backups ON with a 7-day window, because that half IS the backup
    # posture the restore drill exercises (ADR deploy-1's rejection of
    # Postgres-in-compose). The
    # master password comes from the env file, over stdin; it is never an
    # argument.
    # `--db-name` IS THE APPLICATION'S OWN DATABASE, and it has to be, because
    # nothing else on the box creates it. Temporal's auto-setup creates its two
    # (`temporal`, `temporal_visibility`); Zitadel's `start-from-init` creates
    # its one; every other organ brings its own. The APP's — DATABASE_NAME,
    # `djb_staging` — had no maker at all while this line said `postgres`, and
    # runbook step 35 died on the first performance against RDS with
    # `FATAL: database "djb_staging" does not exist`. A laptop never
    # sees it: the `db` container is born with POSTGRES_DB already set.
    #
    # `postgres` still exists whatever is passed here — every PostgreSQL
    # cluster has it — so Zitadel's ZITADEL_ADMIN_EXISTING_DATABASE, which
    # names it, keeps working.
    # --- THE MAJOR IS PINNED, NOT AWS'S DEFAULT (ADR deploy-1) ---------------
    # This line used to be absent, so the engine version was whatever RDS
    # defaulted to on the day — which can land a major ahead of every client
    # pinned in this tree, and `pg_dump` refuses cross-major outright. A
    # deployment whose database major is decided by a vendor default is a
    # deployment whose backups stop working on a Tuesday for a reason nobody
    # changed. `DJB_RDS_ENGINE_VERSION` is the escape for a product that has
    # decided otherwise, and it has to say so out loud to use it.
    #
    # THE MAJOR, NOT A MINOR. The ratified decision is "Postgres 18"; which
    # 18.x is a fact about the day you
    # provisioned. RDS accepts a major-only version and resolves it to the
    # current default minor at create time, and `--auto-minor-version-upgrade`
    # (RDS's default, declared here rather than assumed) keeps it tracking them.
    # Hard-coding `18.6` here would be stale the day AWS ships 18.7 — the same
    # staleness class the missing pin was, one level up.
    say "creating RDS $name-db ($rds_class, ${rds_gb}GB) — this takes several minutes"
    aws rds create-db-instance --region "$region" \
        --db-instance-identifier "$name-db" \
        --db-instance-class "$rds_class" \
        --engine postgres \
        --engine-version "${DJB_RDS_ENGINE_VERSION:-18}" \
        --auto-minor-version-upgrade \
        --allocated-storage "$rds_gb" \
        --storage-type gp3 \
        --no-multi-az \
        --backup-retention-period 7 \
        --no-publicly-accessible \
        --vpc-security-group-ids "$db_sg" \
        --master-username "${POSTGRES_USER:?POSTGRES_USER must be exported from the env file}" \
        --master-user-password "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be exported from the env file}" \
        --db-name "${DATABASE_NAME:?DATABASE_NAME must be exported from the env file: it is the database the application itself uses, and RDS is the only thing that creates it}" \
        --tags "Key=Environment,Value=$environment" "Key=Project,Value=$NAMESPACE" \
        >/dev/null

    # --- S3 ------------------------------------------------------------------
    # Two buckets, both private, both versioned. Public-read on a media bucket
    # makes every key a URL anyone who guesses it can fetch, which is the same
    # as having no tenancy on files at all (.env.example says so; here it is
    # enforced).
    local bucket
    for bucket in "$name-media" "$name-backups"; do
        aws s3api create-bucket --region "$region" --bucket "$bucket" >/dev/null
        aws s3api put-public-access-block --bucket "$bucket" \
            --public-access-block-configuration \
            BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true \
            >/dev/null
        aws s3api put-bucket-versioning --bucket "$bucket" \
            --versioning-configuration Status=Enabled >/dev/null
        aws s3api put-bucket-encryption --bucket "$bucket" \
            --server-side-encryption-configuration \
            '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null
        say "bucket: s3://$bucket (private, versioned, encrypted)"
    done

    # --- the archive bucket's retention posture -------------------------------
    #
    # THE DISAGREEMENT THIS CLOSES, and it is not a tidiness one. `apps/exports`
    # declares under house rule 31 that an archive — a copy of one tenant's whole
    # database — is `purged` after DJB_EXPORT_RETENTION_DAYS, and
    # `purge_exports` honours that: it calls `delete_object` on the artifact and
    # deletes the row. **On a VERSIONED bucket that deletes nothing.** S3 writes
    # a delete marker and keeps the object as a noncurrent version, forever, with
    # no expiry configured — so the platform's own instrument reports the archive
    # purged, `Export` is gone, `/readyz` is green, and the bytes are still
    # there. That is the exact shape rule 31 exists to refuse (the poller that
    # was never built) arriving one layer below the ORM, where no rule in
    # `quality/` can see it: the declaration is in the tree and the disposal is
    # in somebody's AWS account.
    #
    # WHY IT IS HERE AND NOT IN `apps/exports/**`. It cannot be anywhere else.
    # A bucket lifecycle configuration is deployment state, set where buckets are
    # made; no code under `apps/` can carry it.
    #
    # THE PAIRING, AND WHY IT IS TWO NUMBERS AND A SUM. The grace window is
    # deliberately not "the same number as the platform's": the bucket is the
    # BELT and must let go AFTER the platform has, never before — a bucket that
    # expired first would 404 a download while the row still said the archive was
    # live, which is the disagreement inverted rather than closed. So the two
    # numbers are stated separately and the honest claim is their SUM: this
    # deployment holds an archive's bytes for at most
    # DJB_ARCHIVE_TOTAL_EXPOSURE_DAYS. `apps/core/tests/test_archive_retention.py`
    # recomputes that sum against `apps/exports`' own declaration and fails if
    # anybody moves one number without the other.
    #
    # NOT PREFIX-SCOPED, and that is a declared limit rather than an oversight:
    # an export artifact is stored through `apps/files` at
    # `t/<tenant>/f/<file>/v/<n>`, the same keyspace as every other stored file,
    # so there is no archive prefix for a rule to name. This posture therefore
    # bounds the noncurrent versions of EVERYTHING in the media bucket, which is
    # the right answer for every one of them and is a wider claim than the
    # pairing asks for. An archive-specific window needs an archive-specific prefix,
    # which is `apps/files`' keyspace decision (ADR files-2) and not this
    # script's to invent.
    #
    # AbortIncompleteMultipartUpload rides along: a failed export upload leaves
    # parts that are billed and are invisible in every listing.
    local media="$name-media"
    say "archive retention: noncurrent versions expire ${DJB_ARCHIVE_GRACE_DAYS} day(s) after the platform's purge"
    say "  the platform purges an archive at ${DJB_EXPORT_RETENTION_DAYS} days (apps/exports, house rule 31)"
    say "  total exposure: ${DJB_ARCHIVE_TOTAL_EXPOSURE_DAYS} days"
    aws s3api put-bucket-lifecycle-configuration --bucket "$media" \
        --lifecycle-configuration "$(
            cat <<LIFECYCLE
{"Rules": [
  {"ID": "expire-noncurrent-versions",
   "Status": "Enabled",
   "Filter": {"Prefix": ""},
   "NoncurrentVersionExpiration": {"NoncurrentDays": ${DJB_ARCHIVE_GRACE_DAYS}}},
  {"ID": "abort-incomplete-uploads",
   "Status": "Enabled",
   "Filter": {"Prefix": ""},
   "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}}
]}
LIFECYCLE
        )" >/dev/null
    say "bucket lifecycle applied to s3://$media (2 rules)"

    # --- EC2 -----------------------------------------------------------------
    # Graviton, because the price table says so and every image this compose
    # runs publishes an arm64 manifest. The AMI is resolved from SSM rather
    # than pinned in this file: an AMI id is per-region and goes stale, and a
    # runbook step that says "look up the current AMI id" is a step that fails
    # as written.
    local ami
    ami="$(aws ssm get-parameters --region "$region" \
        --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
        --query 'Parameters[0].Value' --output text)"

    say "launching $instance_type from $ami"
    aws ec2 run-instances --region "$region" \
        --image-id "$ami" \
        --instance-type "$instance_type" \
        --key-name "$DJB_KEY_NAME" \
        --security-group-ids "$web_sg" \
        --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=$volume_gb,VolumeType=gp3,Encrypted=true}" \
        --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
        --iam-instance-profile "Name=${DJB_INSTANCE_PROFILE:?DJB_INSTANCE_PROFILE is unset — the role that reads Secrets Manager and writes the backup bucket. A box with long-lived keys in a file instead is the posture this design exists to avoid.}" \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$name},{Key=Environment,Value=$environment},{Key=Project,Value=$NAMESPACE}]" \
        >/dev/null

    say "created. Record the actuals against the approved cost table before the next step."
}

# =============================================================================
# backup-policy — a compromised box cannot delete its own backups
# =============================================================================
# WHAT THIS CLOSES. The default posture around a backups bucket is thin: no
# bucket policy at all (`NoSuchBucketPolicy`), the box role's S3
# grant spanning the whole bucket, no Object Lock, no MFA-delete. Versioning was
# the ONLY thing between a compromised box and its own backup history — and
# versioning alone does not stop a delete, it only keeps a version behind one.
#
# WHAT WAS CHOSEN, AND WHY (the ADR shape the plan asked for):
#
#   context   The threat is a COMPROMISED BOX: the instance role is
#             the credential most likely to leak, because it lives on the
#             machine with the public IP. Backups that the attacker can delete
#             are not backups.
#   decision  Versioning (already on) + a BUCKET POLICY that denies every
#             delete-shaped and policy-shaped action to every principal except
#             one named retention role, and denies non-TLS transport. Applied
#             here, in code, and read back by `--check` rather than believed.
#   rejected  OBJECT LOCK (true WORM, compliance mode is undeletable even by
#             root) — stronger, and the right answer for a product under a
#             retention obligation; not taken here because it wants a
#             versioned bucket configured for it and a retention period chosen
#             per product, and an unchosen retention is either useless (a day)
#             or a bill nobody agreed to (years). TRIGGER TO REVISIT, named:
#             the first product with a stated retention obligation, or the CRM
#             before it holds pilot data.
#   rejected  MFA-DELETE — can only be enabled by the ROOT account user with an
#             MFA device, cannot be set by an IAM principal, and cannot be
#             scripted; it would make this subcommand a paragraph asking
#             somebody to log in as root. It also blocks legitimate lifecycle
#             expiry, so a template that turned it on would be handing every
#             clone a manual chore.
#
# WHAT THIS IS NOT: a cadence. A product decides its backup CADENCE and
# nothing here schedules anything. POLICY is not cadence, and the deferral of
# one is not a deferral of the other.
#
# THE HONEST LIMIT, declared: a bucket policy is removable by a principal with
# `s3:PutBucketPolicy` on the bucket — an account administrator. This stops the
# BOX, which is the threat named; it does not stop the account. Object Lock is
# the answer that stops the account, and its trigger is above.
cmd_backup_policy() {
    local environment="${1:-}" mode="${2:---check}"
    [ -n "$environment" ] || usage
    command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"
    require_namespace

    local bucket="${NAMESPACE}-${environment}-backups"
    local media="${NAMESPACE}-${environment}-media"
    local role="${NAMESPACE}-${environment}-box"
    local retention_role="${NAMESPACE}-${environment}-backup-retention"
    local account
    account="$(aws sts get-caller-identity --query Account --output text 2>/dev/null)" \
        || die "cannot read the AWS account id — is the session live? ('aws login'). Nothing was changed."
    [ -n "$account" ] && [ "$account" != "None" ] \
        || die "cannot read the AWS account id. Nothing was changed."

    # --- WHICH INLINE POLICY IS THE BOX ROLE'S: ASKED, NOT ASSUMED ----------
    # The first cut hard-coded `djb-box`, the name runbook step 19 types. The
    # LIVE role carries `<namespace>-<env>-box`: the box was provisioned by a
    # hand that differed from the runbook. IAM policies are ADDITIVE, so putting
    # a narrow `djb-box` beside the existing one would have left s3:DeleteObject
    # granted and still reported success — the narrowing would have done
    # NOTHING. Only reading the live role showed it.
    local policy_name count
    count="$(aws iam list-role-policies --role-name "$role" \
               --query 'length(PolicyNames)' --output text 2>/dev/null)" || count=0
    [ "$count" = "1" ] \
        || die "role $role carries $count inline policies; this narrows exactly one and will not guess which. Nothing was changed."
    policy_name="$(aws iam list-role-policies --role-name "$role" \
                     --query 'PolicyNames[0]' --output text 2>/dev/null)"
    [ -n "$policy_name" ] && [ "$policy_name" != "None" ] \
        || die "role $role has no inline policy to narrow. Nothing was changed."

    if [ "$mode" = "--check" ]; then
        say "READ-ONLY. bucket $bucket, role $role, inline policy $policy_name, account $account"
        echo "--- versioning ---"
        aws s3api get-bucket-versioning --bucket "$bucket" --output json 2>&1 | head -5
        echo "--- bucket policy statements (Sid / Effect) ---"
        # `|| true` on both: a bucket with NO policy is the answer this check
        # exists to give (it is the very posture named above), not a reason to abort under
        # `set -o pipefail`. The summary prints the AWS message verbatim.
        { aws s3api get-bucket-policy --bucket "$bucket" --query Policy --output text 2>&1 \
            | "$PYTHON_BIN" "$HERE/policy_summary.py" bucket; } || true
        echo "--- the box role's inline grant ---"
        { aws iam get-role-policy --role-name "$role" --policy-name "$policy_name" \
            --query PolicyDocument --output json 2>&1 \
            | "$PYTHON_BIN" "$HERE/policy_summary.py" role; } || true
        echo ""
        say "nothing was changed. Re-run with --apply to write the policy."
        return 0
    fi
    [ "$mode" = "--apply" ] || die "unknown mode $mode (backup-policy takes --check, the default, or --apply)"

    # --- the bucket policy --------------------------------------------------
    # `Principal: "*"` + an `aws:PrincipalArn` CONDITION, not `NotPrincipal`,
    # and that is the fix for the MalformedPolicy this first returned. Two
    # reasons, both load-bearing:
    #
    #   1. AWS RESOLVES A PRINCIPAL ARN AT PutBucketPolicy TIME. `NotPrincipal`
    #      naming a retention role nobody has created yet is "Invalid principal
    #      in policy" — so the guard could not be installed until its own
    #      exemption existed, which is backwards: the guard is what you want
    #      FIRST. A condition VALUE is a string and is never resolved, so the
    #      policy lands today and begins exempting the retention role the moment
    #      a product creates one.
    #   2. `NotPrincipal` matches the request's principal EXACTLY, and a request
    #      from a role arrives as `arn:aws:sts::…:assumed-role/Name/Session`, so
    #      exempting a role by its `iam::…:role/Name` ARN silently fails to
    #      match — and wildcards are illegal in NotPrincipal. `aws:PrincipalArn`
    #      resolves a role session to the ROLE's ARN, which is what we mean.
    #
    # BREAK-GLASS, STATED: the account ROOT user, and the retention role if a
    # product creates one. Everything else — including the administrator running
    # this script — is denied the data-destroying actions. Deliberate: an admin
    # who must remove a backup assumes the retention role or acts as root, and
    # both are acts somebody chose and CloudTrail records.
    local policy_file; policy_file="$(mktemp)"
    cat > "$policy_file" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "NoBackupDeletionExceptBreakGlass",
      "Effect": "Deny",
      "Principal": "*",
      "Action": ["s3:DeleteObject", "s3:DeleteObjectVersion",
                 "s3:PutBucketVersioning", "s3:PutLifecycleConfiguration"],
      "Resource": ["arn:aws:s3:::${bucket}", "arn:aws:s3:::${bucket}/*"],
      "Condition": {"StringNotLike": {"aws:PrincipalArn": [
        "arn:aws:iam::${account}:root",
        "arn:aws:iam::${account}:role/${retention_role}"]}}
    },
    {
      "Sid": "TheBoxMayNotRemoveThisGuard",
      "Effect": "Deny",
      "Principal": "*",
      "Action": ["s3:PutBucketPolicy", "s3:DeleteBucketPolicy", "s3:DeleteBucket"],
      "Resource": "arn:aws:s3:::${bucket}",
      "Condition": {"StringLike": {"aws:PrincipalArn":
        "arn:aws:iam::${account}:role/${role}"}}
    },
    {
      "Sid": "TlsOnly",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::${bucket}", "arn:aws:s3:::${bucket}/*"],
      "Condition": {"Bool": {"aws:SecureTransport": "false"}}
    }
  ]
}
JSON
    aws s3api put-bucket-policy --bucket "$bucket" --policy "file://$policy_file" \
        || { rm -f "$policy_file"; die "the bucket policy was refused; nothing else was changed."; }
    rm -f "$policy_file"
    say "bucket policy applied to $bucket (3 statements)"

    # --- the box role's grant, narrowed SURGICALLY --------------------------
    # The live document is READ, TRANSFORMED and written back under its own
    # name. It is NOT replaced by one this script composed: the live policy
    # carries `secretsmanager:DescribeSecret` and `ListSecrets`, which
    # `secrets-fetch` needs and the first cut would have dropped on the floor
    # while calling it a narrowing. The transform is exactly one thing — a
    # statement granting delete over the BACKUPS bucket loses that action, and
    # keeps it for media, because deleting a media file is something a product
    # legitimately does and deleting its own backup is not.
    local live_file narrowed_file
    live_file="$(mktemp)"; narrowed_file="$(mktemp)"
    aws iam get-role-policy --role-name "$role" --policy-name "$policy_name" \
        --query PolicyDocument --output json > "$live_file" \
        || { rm -f "$live_file" "$narrowed_file"; die "cannot read the box role's policy; the bucket policy IS applied, the role is unchanged."; }

    DJB_BACKUPS_BUCKET="$bucket" DJB_MEDIA_BUCKET="$media" \
        "$PYTHON_BIN" "$HERE/narrow_backup_grant.py" "$live_file" "$narrowed_file" \
        || { rm -f "$live_file" "$narrowed_file"; die "could not narrow the policy document; the bucket policy IS applied, the role is unchanged."; }

    aws iam put-role-policy --role-name "$role" --policy-name "$policy_name" \
        --policy-document "file://$narrowed_file" \
        || { rm -f "$live_file" "$narrowed_file"; die "the role update was refused; the bucket policy IS applied."; }
    rm -f "$live_file" "$narrowed_file"
    say "box role $role inline policy $policy_name narrowed: no delete over $bucket"
    say "read it back with: deploy/provision.sh backup-policy $environment --check"
}

# =============================================================================

case "${1:-}" in
    project-name)  resolved_project_name; echo ;;
    derived-project-name) derived_project_name; echo ;;
    image-tag)     image_tag; echo ;;
    image-repo)    shift; image_repo "${1:-}"; echo ;;
    image-ref)     shift; image_ref "${1:-}" "${2:-}"; echo ;;
    image-digest)  shift; image_digest "${1:-}" "${2:-}"; echo ;;
    tree-digest)   shift; tree_digest "${1:-}" ;;
    pin-digest)    shift; pin_digest "${1:-}" "${2:-}" ;;
    up)            shift; cmd_up "$@" ;;
    env-file)      shift; cmd_env_file "$@" ;;
    secrets-put)   shift; cmd_secrets_put "$@" ;;
    secrets-fetch) shift; cmd_secrets_fetch "$@" ;;
    infra)         shift; cmd_infra "$@" ;;
    backup-policy) shift; cmd_backup_policy "$@" ;;
    *)             usage ;;
esac
