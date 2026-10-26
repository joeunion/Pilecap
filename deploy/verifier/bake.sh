#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../../scripts/bash_only.sh" || exit 2
# THE VERIFIER IMAGE RECIPE — everything that must already be on a box before a
# verification is worth starting on it, done once, so that every launch after it
# is a boot and a push rather than twenty minutes of provisioning.
#
#   deploy/verifier/bake.sh --plan   print the ordered steps and run NOTHING
#   deploy/verifier/bake.sh          run them, on a bake box and nowhere else
#
# WHERE IT RUNS. On a bake box, over the same SSH-through-Session-Manager
# transport every other remote command uses. It refuses (exit 2, having done
# nothing) unless /etc/verifier/bake exists — the marker the bake box's own
# user-data writes. That refusal is the whole reason the marker exists: this
# script installs packages, creates an account, writes /etc/environment and
# clears the cloud-init state, and it must never do any of that on an operator's
# laptop or on a live verifier box somebody is mid-verification on.
#
# WHY AN AMI AND NOT THE CONTAINER IMAGE CI ALREADY BUILDS. CI builds the
# application image — one Python runtime with the project's dependencies in it.
# A verification needs a MACHINE: a docker daemon, the seven compose images
# pre-pulled, git, the pinned `uv`, a warm dependency cache and a source
# checkout. None of that is in an application image, and the gate runs against a
# TREE rather than against a container. So: bake a machine image; leave the
# registry and its deploy role entirely alone.
#
# WHY NOT A MANAGED IMAGE PIPELINE. It is a pipeline, a component set, an
# infrastructure configuration, a distribution configuration and the IAM for all
# four — for one image that a script bakes in twenty minutes. Recorded as the
# escalation the day there is a second image or a schedule to keep.
#
# WHY --plan EXISTS. The plan IS the image's runbook. An image whose recipe can
# only be read by running it is the class of step that fails as written, and the
# operator reading this file before spending money must be able to see the whole
# ordered list without spending any.
#
# THE ORDER IS LOAD-BEARING, and the drive asserts it:
#
#   the checkout ARRIVES on `main` — that is where the wrapper's first push
#   lands — and is PARKED on a branch nobody pushes BEFORE anything is built
#   inside it, for two reasons. The first is the old one: `main` is then never
#   the checked-out branch, which is what lets the operator's later
#   `git push … main:main` update `main` on the box. The second cost a whole
#   bank on boxes to learn: every name this recipe DERIVES from the checkout is
#   derived from the branch it is standing on, and `./scripts/setup.sh` derives
#   this checkout's database name that way (`scripts/db.sh`:
#   `djb_<branch>_<hash of the path>`). Run before the park it makes a database
#   named from `main`, the park then moves the checkout, and every box launched
#   from the image derives a name nothing on it ever created. Park first and the
#   derivation IS the baked name, on the bake box and on every box after it.
#
#   PARKING IS NOT A DETACHED HEAD, which is what the old order was afraid of:
#   `git checkout -B` puts a branch at the commit that is already checked out,
#   so the tree the steps below stand in is byte-for-byte the tree the push
#   landed. Then: the frontend toolchain (its pnpm half reads a version out of
#   the tree, so it cannot precede the checkout guard, and the stack step runs
#   `pnpm install`, so it cannot follow it), the dependencies, the stack, the
#   images, the account's shell environment while the stack is up and provable,
#   and the two removals last.
#
# Exit: 0 the recipe ran and the box is ready to capture · 1 a step failed ·
# 2 refused — not a bake box, an unknown flag, a tool that is not here, an
# account that cannot sudo without a password (asserted before step 1, because
# every step of this recipe is root — FIELD TEST 5 discovered it at step 1
# instead, eleven minutes of push later), or a sudo rule that is still in force
# after step 15 removed it, which would be root baked into the image.
#
# NO PIPE REFUSAL HERE, and that is deliberate rather than an omission. Every
# other executable in this family refuses a piped stdout because a filter
# replaces the exit status that is the verdict. This one is invoked over SSH,
# whose remote stdout IS a pipe by construction, so the family's own guard would
# refuse every real invocation. The exit status is preserved end to end by the
# transport instead, and the wrapper that calls it asserts that.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set +x # never; a recipe that traces itself traces whatever it was handed

# `die` and `say` are deploy/lib.sh's.
DEPLOY_NAME=bake
# shellcheck source=deploy/lib.sh
. "$HERE/../lib.sh" || exit 2

#: The marker the bake box's own user-data writes. Its absence is the refusal
#: that keeps this recipe off a laptop and off a live verifier box.
BAKE_MARKER="${VERIFIER_ROOT:-}/etc/verifier/bake"

#: Where the recipe puts the reaper and its units on the image. The service unit
#: names this path; the two must move together.
VERIFIER_OPT="${VERIFIER_ROOT:-}/opt/verifier"

#: The account every verification runs as. On the IMAGE it is in the docker
#: group and has no sudo rule — nothing a verification does needs root. On the
#: BAKE BOX it has passwordless sudo, because installing the machine is nothing
#: but root: the bake seam grants it (`bake-user-data.yaml`, argued there in
#: full), this file asserts it before step 1 and removes it at step 15, so the
#: two sentences are true of two different machines and neither leaks into the
#: other.
BAKE_USER="${DJB_VERIFIER_BAKE_USER:-verifier}"

#: Where cloud-init writes the sudo rules it is asked for — one drop-in for
#: every user in the seam's `users:` block. Step 14 removes it, so the bake
#: account's root does not outlive the bake; a knob rather than a literal
#: because it is cloud-init's convention and not this tree's, and the day an
#: AMI's cloud-init files it somewhere else, step 15's own assertion is what
#: refuses the bake rather than shipping an image with root in it.
BAKE_SUDOERS="${VERIFIER_ROOT:-}/etc/sudoers.d/90-cloud-init-users"

#: The source checkout on the image, and the branch it is parked on. THIS IS
#: THE ONE PLACE THE PATH IS WRITTEN DOWN — the recipe neither clones nor
#: creates it. THREE things read this knob and none of them re-types it: the
#: bake box's user-data renders it into the `git init` that CREATES the
#: repository (`bake-user-data.yaml`'s ${VERIFIER_CHECKOUT} slot), the wrapper
#: renders it into its push TARGET, and step 6 below CHECKS what arrived. It
#: carries NO product name: the machinery is system layer and ships in the
#: template, and more than one deployment uses it.
#: The park branch exists so that `main` is never the checked-out branch: a push
#: into a non-bare repository's CHECKED-OUT branch is refused by git, and every
#: launch pushes `main`. The FIRST push — the bake box's own — is the exception
#: that proves it: there the checkout is still on `main`, and it is receivable
#: only because the user-data set `receive.denyCurrentBranch=updateInstead` on
#: it, which is what puts the pushed tree in the working directory the steps
#: below stand in.
BAKE_CHECKOUT="${DJB_VERIFIER_CHECKOUT:-/home/${BAKE_USER}/src}"
BAKE_PARK_BRANCH="verifier-parking"

#: The pinned `uv`, the same version the application image pins, so a lockfile
#: that resolves on the image resolves in CI.
BAKE_UV_VERSION="${DJB_VERIFIER_UV_VERSION:-0.12.5}"

#: COMPOSE V2 IS A CLI-PLUGIN BINARY, NOT A PACKAGE, and that sentence cost a
#: bake box to learn. Amazon Linux 2023's repositories carry `docker` and no
#: compose package of any name: `dnf install -y docker-compose-plugin` answers
#: `Error: Unable to find a match` and step 1 dies with the whole recipe behind
#: it. The plugin is published as one static binary per architecture, and
#: `docker compose` finds it by looking in the cli-plugins directories.
#:
#: PINNED, for `BAKE_UV_VERSION`'s reason one knob up: a download that resolves
#: "latest" is a different compose on every bake, and an image nobody can say
#: the version of is an image nobody can reproduce a failure on.
#:
#: AND CHECKSUMMED, which is the half the uv pin does NOT need. uv arrives
#: through its publisher's own installer; this arrives as a bare binary that
#: the next line marks executable and docker then runs as part of every
#: verification. The sha256 is the release's published one for this exact
#: version and architecture, and it is verified BEFORE the binary is installed
#: — a verification after the install is a verification of something already in
#: place.
#:
#: AARCH64, because every box in this family is arm64 (`c7g.*`, the instance
#: type knobs in `scripts/verifier_box.sh`). A bake on some future x86 type
#: needs the other asset and the other sha, which is why both are knobs and
#: neither is spelled twice.
BAKE_COMPOSE_VERSION="${DJB_VERIFIER_COMPOSE_VERSION:-2.29.7}"
BAKE_COMPOSE_SHA256="${DJB_VERIFIER_COMPOSE_SHA256:-6e9fbd5daa20dca5d7d89145081ae8155d68ef2928b497d9f85b54fe0f9dbb2c}"
BAKE_COMPOSE_PLUGIN="${VERIFIER_ROOT:-}/usr/local/lib/docker/cli-plugins/docker-compose"

#: NODE, AND IT IS NOT OPTIONAL FURNITURE. The gate's fe leg has a drive, and
#: that drive needs a real pnpm: on an image without one it answers "no pnpm on
#: PATH · Nothing was asserted", which is COULD NOT LOOK, and 2 outranks every
#: green beside it — so a box with no frontend toolchain reaches NO verdict, on
#: any tree. The frozen install itself is the fe leg's own function
#: (`scripts/fe_gate.sh::fe_leg_frozen_lockfile`), run by whatever installs a
#: checkout's frontend; this step only puts the runtime and the pinned pnpm on
#: the image. Measured on a box, 2026-09-18.
#:
#: PINNED AND CHECKSUMMED, exactly as the compose plugin above and for the same
#: two reasons: a download that resolves "latest" is a different runtime on every
#: bake, and a bare tarball from a publisher is verified BEFORE it is unpacked or
#: it is verified after it is already installed. AARCH64, like everything else in
#: this family; an x86 bake needs the other asset and the other sha, which is why
#: both are knobs.
#:
#: THE LINE: the version satisfies `frontend/package.json`'s `engines.node`, and
#: the sha256 is the publisher's own for this exact version and architecture
#: (nodejs.org/dist/v<version>/SHASUMS256.txt).
BAKE_NODE_VERSION="${DJB_VERIFIER_NODE_VERSION:-24.21.0}"
BAKE_NODE_SHA256="${DJB_VERIFIER_NODE_SHA256:-724282c3b43aec998aa9527380465b45d229e021b58035f5f4f63095eabfe5d5}"

#: Where node's bin/ lands. /usr/local is already on every login PATH, which is
#: what puts `node`, `npm`, `corepack` and corepack's `pnpm` shim in front of the
#: account a verification runs as without a profile edit anybody can forget.
BAKE_NODE_PREFIX="${VERIFIER_ROOT:-}/usr/local"

#: Two pytest slots, so each slot runs half the box's cores. Written to
#: /etc/environment, which PAM reads for every session the transport opens.
BAKE_GATE_SLOTS="${DJB_VERIFIER_GATE_SLOTS:-2}"

# -----------------------------------------------------------------------------
# THE PLAN. One function, printed by `--plan` and walked by the run, so the
# printed runbook cannot drift from the steps: the names below are the step
# names, and each `step` call in the body quotes one of them.
# -----------------------------------------------------------------------------
plan() {
    cat <<PLAN
bake: the verifier image recipe, in order. --plan runs NONE of it.

   1. packages        dnf install docker, git, tar, chrony, zsh — and then compose
                      v2 ${BAKE_COMPOSE_VERSION} as a PINNED BINARY, downloaded, its
                      sha256 verified, and only then installed into
                      ${BAKE_COMPOSE_PLUGIN}
                      (AL2023 ships NO compose package under any name: compose
                      v2 is a cli-plugins binary. docker and git are already on
                      the box — the bake box's user-data installs both before
                      the push that carries this file; dnf is idempotent and
                      the list stays whole, so the recipe still describes the
                      machine it needs rather than the difference between two
                      files)
   2. docker          enable it, and put ${BAKE_USER} in the docker group
   3. account         create ${BAKE_USER} if the bootstrap user-data did not
   4. uv              install uv ${BAKE_UV_VERSION}, the version the app image pins
   5. reaper          install idle_reaper.sh into ${VERIFIER_OPT} and its
                      systemd unit + timer into /etc/systemd/system, LEFT
                      DISABLED (the launch user-data enables the timer; a bake
                      box that reaps itself mid-recipe is a half-written image)
   6. checkout        CHECK ${BAKE_CHECKOUT}, still on main — the bake box's
                      user-data initialised the repository there and the
                      wrapper pushed this tree into it before this ran;
                      nothing here clones
   7. park            git checkout -B ${BAKE_PARK_BRANCH} in the checkout —
                      FIRST, before anything is built in it, and the order is
                      the whole remedy. main is then never the checked-out
                      branch, so the operator's later push can update it; and
                      every step below stands on the branch the image ships
                      parked on, so the DATABASE_NAME step 9 derives
                      (scripts/db.sh derives one per branch per checkout) is
                      the name every later run on every box derives too.
                      Parking LAST is what the first bank on boxes measured:
                      the stack was made under main, and every box from that
                      image then looked for a database no step had created
   8. frontend        node v${BAKE_NODE_VERSION} (arm64) as a PINNED tarball whose
                      sha256 is verified BEFORE it is unpacked into
                      ${BAKE_NODE_PREFIX}, and then pnpm AT THE VERSION THE
                      CHECKOUT PINS — read out of frontend/package.json's
                      packageManager field rather than typed here, and
                      activated through corepack for ${BAKE_USER}. Not
                      furniture: the gate's fe drive answers 'no pnpm on PATH ·
                      Nothing was asserted' without it, which is COULD NOT LOOK
                      on every box loop and every bank's selftest shard; the
                      frozen install is the fe leg's own (scripts/fe_gate.sh)
   9. dependencies    uv sync --frozen  (the warm cache is most of what the
                      image is for)
  10. stack           ./scripts/setup.sh  (the compose stack up, this
                      checkout's database — named from the branch step 7
                      parked on — and the identity seed), then
                      db_template_refresh (scripts/db.sh): the migration
                      template for this tree's digest, published into the
                      image so a cold box clones it instead of migrating
  11. images          docker compose pull  (db redis temporal zitadel mailpit
                      minio meilisearch — pre-pulled so a launch is a boot)
  12. environment     DJB_GATE_SLOTS=${BAKE_GATE_SLOTS} into /etc/environment, read by PAM
                      for every session the transport opens
  13. marker         rm -f ${BAKE_MARKER} — LAST, and it is the step that makes
                      the refusal at the top of this file worth anything.
                      create-image captures the root volume AS IT STANDS, so a
                      marker left in place is BAKED INTO THE IMAGE — and every
                      verifier box launched from that image then satisfies this
                      recipe's own precondition, which puts the destructive run
                      (packages, /etc/environment, the wipe below) one command
                      away from a live box somebody is mid-verification on.
                      Removing it also makes a second bake.sh on THIS box refuse
                      as 'not a bake box', which is the same property one layer up.
  14. clean          truncate the reaper log, then cloud-init clean --logs, so
                      the captured image has no instance identity in it
  15. sudo           remove ${BAKE_SUDOERS} — the drop-in cloud-init wrote for
                      the bake account — and PROVE the rule is gone. LAST,
                      because every step above it needs the rule: the bake box
                      is granted passwordless root by its own user-data and
                      create-image captures the root volume as it stands, so a
                      rule left in place is baked into the image and every
                      verifier box launched from it gets root the launch seam
                      says out loud that it does not want. The proof is the
                      half that matters: the path above is cloud-init's
                      convention, so a bake that cannot make 'sudo -n true'
                      fail afterwards REFUSES rather than reporting success
                      over a root-capable image.

bake: --plan printed the recipe above and ran none of it.
PLAN
}

# -----------------------------------------------------------------------------
case "${1:-}" in
--plan)
    plan
    exit 0
    ;;
"") ;;
*)
    die "unknown argument '$1': bake.sh takes nothing or --plan"
    ;;
esac

[ -r "$BAKE_MARKER" ] || die "this is not a bake box (${BAKE_MARKER} is not here).
   The recipe installs packages, creates an account, writes /etc/environment and
   clears the cloud-init state. It must never run on a laptop or on a verifier
   box somebody is mid-verification on. The marker is written by
   deploy/verifier/bake-user-data.yaml, which only a bake box boots with."

step() { echo ""; echo "== bake step $*"; }

# >>> the frontend toolchain >>>
# EXTRACTED AND READ BY `quality/tests/test_verifier_image.py` — the two sentinel
# lines around this block are how that module reaches the SHIPPED bytes rather
# than a copy of them. Keep them.
#
# IT IS READ AND NOT RUN, deliberately: running it downloads a tarball from
# nodejs.org, and a drive that did that on every gate would be buying a network
# round trip to learn what its text already says. What the image really answers
# — that the tarball unpacks, that corepack activates, that `pnpm --version` is
# the pinned one — this function asserts on the box itself, below, where the
# answer is real.
#
# WHY A FUNCTION at all: so the drive has one bracketed thing to read, and so
# the two halves — a PINNED runtime and a DERIVED package manager — sit together
# with the argument for the asymmetry between them.
install_frontend_toolchain() {
    local tmp pinned
    say "node v${BAKE_NODE_VERSION} (pinned; sha256 verified before it is unpacked)"
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/djb-bake-node.XXXXXX")" ||
        die "could not make a scratch directory to download node through"
    curl -fsSL -o "${tmp}/node.tar.gz" \
        "https://nodejs.org/dist/v${BAKE_NODE_VERSION}/node-v${BAKE_NODE_VERSION}-linux-arm64.tar.gz"
    printf '%s  %s\n' "$BAKE_NODE_SHA256" "${tmp}/node.tar.gz" >"${tmp}/node.sha256"
    sha256sum -c "${tmp}/node.sha256" >/dev/null || die "the node v${BAKE_NODE_VERSION} tarball this bake downloaded does NOT match the
   sha256 the recipe pins (${BAKE_NODE_SHA256}).
   Nothing was unpacked. Either the pin is stale — a knob pointed at a version
   whose sha nobody updated — or the download is not what the publisher signed.
   Both are a human's to decide, and the runtime would otherwise run the
   frontend half of every verification on every box from this image."
    # `.tar.gz` AND NOT `.tar.xz`: `tar -J` shells out to an `xz` binary that
    # AL2023 does not install by default, so the xz asset would add a package to
    # step 1 to save 8 MB of a one-time download.
    sudo tar -xzf "${tmp}/node.tar.gz" -C "$BAKE_NODE_PREFIX" --strip-components=1 \
        --exclude=CHANGELOG.md --exclude=LICENSE --exclude=README.md
    rm -rf "$tmp"
    node --version >/dev/null 2>&1 || die "node v${BAKE_NODE_VERSION} was unpacked into ${BAKE_NODE_PREFIX} and \`node --version\`
   still does not answer, so its bin/ is not on this PATH. Every verification on
   this image needs it; point BAKE_NODE_PREFIX at a prefix that is."

    # AND PNPM AT THE VERSION THE CHECKOUT PINS, READ OUT OF THE TREE. The
    # `packageManager` field is what every developer and CI already obey; a
    # second spelling in this file is a version the image and the tree can
    # disagree about until a lockfile refuses on a box nobody is watching.
    pinned="$(sed -n 's/.*"packageManager"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        "${BAKE_CHECKOUT}/frontend/package.json" | sed -n 1p)"
    case "$pinned" in
    pnpm@[0-9]*) ;;
    *) die "${BAKE_CHECKOUT}/frontend/package.json's \`packageManager\` reads
   '\''${pinned:-<absent>}'\'' — this recipe derives the package manager from that field
   and will not guess one. A tree whose field is missing or is not a pnpm pin is
   a tree this image cannot carry a matching pnpm for." ;;
    esac
    say "pnpm ${pinned#*@} (derived from the checkout's packageManager field, never typed here)"
    # `corepack enable` writes the shims into node's own bin/ and is root's;
    # `corepack prepare` fills a per-user cache, so it runs AS the account every
    # verification runs as — a cache in root's home is a download at first use
    # on a box that should need no network to run a gate.
    sudo env COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack enable pnpm
    sudo -u "$BAKE_USER" env COREPACK_ENABLE_DOWNLOAD_PROMPT=0 corepack prepare "$pinned" --activate
    sudo -u "$BAKE_USER" env COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm --version >/dev/null 2>&1 || die "pnpm was activated from '${pinned}' and \`pnpm --version\` does not answer for
   ${BAKE_USER}. The gate's fe drive reads COULD NOT LOOK without it, which is
   exit 2 on every box launched from this image."
}
# <<< the frontend toolchain <<<

# THE OTHER PRECONDITION, AND FIELD TEST 5 IS WHY IT IS ASSERTED HERE RATHER
# THAN DISCOVERED AT THE NEXT LINE. Every step below is root: `dnf`,
# `systemctl`, `useradd`, `install`, the `uv` installer, `/etc/environment`,
# `cloud-init clean`. On 2026-09-17 a bake box booted, the marker arrived, and
# 655 s of push landed 213 MB of history through the tunnel — and then step 1
# answered `sudo: a terminal is required to read the password` and `sudo: a
# password is required`, because the bake seam's `users:` entry granted the
# account no rule and a tunnelled session has no tty to answer a prompt with.
# Eleven minutes and an on-demand box, spent on a precondition one line can
# state.
#
# `-n`, WHICH IS THE WHOLE MECHANISM. `sudo -n true` never prompts: it either
# answers 0 or refuses, so this is a REFUSAL on a box with no rule rather than
# a recipe hanging on a password nobody can type. And it names the file that
# grants the rule, because the fix is in the seam and not on the box.
sudo -n true 2>/dev/null || die "the account this session opened as — the seam calls it ${BAKE_USER} —
   cannot sudo without a password, and
   every step of this recipe is root: dnf, systemctl, useradd, install, the uv
   installer, /etc/environment, cloud-init clean. Nothing was installed.
   THE FIX IS IN THE SEAM, not on this box. deploy/verifier/bake-user-data.yaml's
   \`users:\` entry for the bake account needs the line:
     sudo: ALL=(ALL) NOPASSWD:ALL
   The bootstrap's own \`sudo -u\` calls prove nothing about this: cloud-init's
   runcmd runs as root, so those are root dropping privilege rather than this
   account climbing. (That rule does not reach the image — step 15 removes it.)"

step "1/15 packages"
# KEPT WHOLE, AND IDEMPOTENT. docker and git are already here — the bake box's
# user-data installs both before the push that carries this file, because the
# push needs `git-receive-pack` on the box and the recipe arrives IN that push.
# `dnf install` on a package that is present is `Nothing to do` and exit 0, so
# listing them twice costs a second and buys the recipe its independence: this
# line is the statement of what the image needs, not the difference between two
# files that must then be read together.
sudo dnf install -y docker git tar chrony zsh

# AND THE COMPOSE PLUGIN, WHICH IS NOT A PACKAGE HERE. The argument is beside
# the knobs above; this is the mechanism. Download to a temporary file, verify
# the published sha256 AGAINST THAT FILE, and only then install it — 0755, root
# owned — where `docker compose` looks. A checksum after the install is a
# checksum of a binary that is already in place.
say "compose v${BAKE_COMPOSE_VERSION} (pinned; sha256 verified before it is installed)"
compose_tmp="$(mktemp)"
curl -fsSL -o "$compose_tmp" \
    "https://github.com/docker/compose/releases/download/v${BAKE_COMPOSE_VERSION}/docker-compose-linux-aarch64"
printf '%s  %s\n' "$BAKE_COMPOSE_SHA256" "$compose_tmp" >"${compose_tmp}.sha256"
sha256sum -c "${compose_tmp}.sha256" >/dev/null || die "the compose v${BAKE_COMPOSE_VERSION} binary this bake downloaded does NOT match the
   sha256 the recipe pins (${BAKE_COMPOSE_SHA256}).
   Nothing was installed. Either the pin is stale — a re-tagged release, a knob
   pointed at a version whose sha nobody updated — or the download is not what
   the publisher signed. Both are a human's to decide, and neither is something
   a recipe may shrug at: the binary would run as part of every verification on
   every box launched from this image."
sudo install -d -m 0755 "$(dirname "$BAKE_COMPOSE_PLUGIN")"
sudo install -m 0755 "$compose_tmp" "$BAKE_COMPOSE_PLUGIN"
rm -f "$compose_tmp" "${compose_tmp}.sha256"
# The plugin answers before the daemon is up — `docker compose version` is the
# plugin alone — so a plugin that landed somewhere docker does not look is a
# refusal here rather than a `docker compose pull` that dies at step 9.
docker compose version >/dev/null 2>&1 || die "compose v${BAKE_COMPOSE_VERSION} was installed at ${BAKE_COMPOSE_PLUGIN} and
   \`docker compose version\` still does not answer, so docker is not finding the
   plugin there. Step 9 (\`docker compose pull\`) and every verification on this
   image need it. Read \`docker --help\` for the cli-plugins directories this
   docker searches and point BAKE_COMPOSE_PLUGIN at one of them."

step "2/15 docker"
sudo systemctl enable --now docker

step "3/15 account"
id "$BAKE_USER" >/dev/null 2>&1 || sudo useradd -m -s /bin/bash "$BAKE_USER"
sudo usermod -aG docker "$BAKE_USER"

step "4/15 uv ${BAKE_UV_VERSION}"
# From the published installer with the version pinned, for the application
# image's own reason: a `curl | sh` that resolves "latest" is a different
# toolchain on every bake.
curl -LsSf "https://astral.sh/uv/${BAKE_UV_VERSION}/install.sh" | sudo env UV_INSTALL_DIR=/usr/local/bin sh

step "5/15 reaper"
sudo install -d -m 0755 "$VERIFIER_OPT"
sudo install -m 0755 "${HERE}/idle_reaper.sh" "${VERIFIER_OPT}/idle_reaper.sh"
sudo install -m 0644 "${HERE}/verifier-reaper.service" /etc/systemd/system/verifier-reaper.service
sudo install -m 0644 "${HERE}/verifier-reaper.timer" /etc/systemd/system/verifier-reaper.timer
# NOT enabled. The launch user-data enables the timer.
sudo systemctl daemon-reload

step "6/15 checkout"
[ -d "$BAKE_CHECKOUT/.git" ] || die "no checkout at ${BAKE_CHECKOUT}.
   The bake box's own user-data (deploy/verifier/bake-user-data.yaml) creates
   the repository here, and the wrapper pushes this tree into it before it runs
   the recipe; a recipe that cloned from a forge would need a credential on a
   box that is designed to hold none. All three read one knob — BAKE_CHECKOUT,
   above — so this refusal means the user-data did not run, not that they
   disagree."

step "7/15 park on ${BAKE_PARK_BRANCH}"
# FIRST, AND THE FIRST BANK ON BOXES IS WHY. This used to be step 11, after the
# stack was already made. `./scripts/setup.sh` derives this checkout's database
# name from the branch it is standing on (`scripts/db.sh`), so a stack made on
# `main` and then parked left the image carrying a database named
# `djb_main_<hash>` while every later run on every box derived
# `djb_verifier_parking_<hash>` — a name nothing had created. Measured
# 2026-09-18: the gate's db-pin leg red on the first box consult, then three
# selftest shards exit 2 in the first bank on boxes, one of them a drive that
# derives the name and could not look. Parking here makes the derivation and
# the baked name the same string, and leaves the db-pin leg free to judge a
# stale pin instead of being silenced by one.
#
# `-B` rather than `-b`: the recipe is re-runnable in principle, and a second
# bake on a box that already carries the branch must move it rather than refuse.
# It is a branch at the commit already checked out — the tree does not move, so
# every step below reads exactly what a step 6 checkout read.
(cd "$BAKE_CHECKOUT" && sudo -u "$BAKE_USER" git checkout -B "$BAKE_PARK_BRANCH")

step "8/15 frontend — node v${BAKE_NODE_VERSION} + the checkout's pnpm"
# AFTER THE CHECKOUT GUARD, because the pnpm half reads a file out of the tree,
# and BEFORE THE STACK, so `./scripts/setup.sh` and anything it starts find node
# and the pinned pnpm on the PATH. The argument for the whole step is beside
# the knobs; the argument for the asymmetry between a pinned runtime and a
# derived package manager is inside the block.
install_frontend_toolchain

step "9/15 dependencies — uv sync --frozen"
(cd "$BAKE_CHECKOUT" && sudo -u "$BAKE_USER" uv sync --frozen)

step "10/15 stack — ./scripts/setup.sh, then the migration template"
# >>> the stack >>>
# On the parked branch (step 7), so the DATABASE_NAME setup derives is every later box's.
(cd "$BAKE_CHECKOUT" && sudo -u "$BAKE_USER" ./scripts/setup.sh)
# A failed publish fails the bake: the image without its template is the cold-box regression.
(cd "$BAKE_CHECKOUT" && sudo -u "$BAKE_USER" bash -c '. scripts/db.sh && db_template_refresh')
# <<< the stack <<<

step "11/15 images — docker compose pull"
(cd "$BAKE_CHECKOUT" && sudo -u "$BAKE_USER" docker compose pull)

step "12/15 environment — DJB_GATE_SLOTS=${BAKE_GATE_SLOTS}"
# PAM's pam_env reads /etc/environment for every session, which is what makes
# this reach a gate started over the transport. It is `KEY=value` lines only —
# no expansion, no export.
grep -E '^DJB_GATE_SLOTS=' /etc/environment >/dev/null 2>&1 &&
    sudo sed -i "s/^DJB_GATE_SLOTS=.*/DJB_GATE_SLOTS=${BAKE_GATE_SLOTS}/" /etc/environment ||
    echo "DJB_GATE_SLOTS=${BAKE_GATE_SLOTS}" | sudo tee -a /etc/environment >/dev/null

step "13/15 marker"
# LAST, AND IT IS WHAT MAKES THE REFUSAL AT THE TOP OF THIS FILE WORTH
# ANYTHING. `create-image` captures the root volume as it stands. A marker left
# in place is baked into the image, so every verifier box launched from it
# satisfies this recipe's own precondition — and the destructive run is then one
# command away from a live box somebody is mid-verification on. It also makes a
# second `bake.sh` on THIS box refuse, which is the property the drive can only
# reach under a scratch root.
sudo rm -f "$BAKE_MARKER"

step "14/15 clean"
sudo truncate -s 0 /var/log/verifier-reaper.log 2>/dev/null || true
sudo cloud-init clean --logs

step "15/15 sudo — the bake account's root leaves with the bake"
# LAST, AND FOR THE MIRROR IMAGE OF STEP 12'S REASON. `create-image` captures
# the root volume as it stands, and cloud-init's sudo rules are FILES on that
# volume — so the rule the bake seam granted (argued in full in
# `bake-user-data.yaml`) would be baked into the image, and every verifier box
# launched from it would hand its account passwordless root. The launch seam
# says the opposite out loud — "with NO sudo rule: nothing a verification does
# needs root" — and a rule arriving through the AMI instead of through the seam
# is that sentence broken where nobody is reading.
#
# IT CANNOT BE EARLIER. Every step above this one is a `sudo`, the clean
# included; removing the rule before them is a recipe that refuses itself
# halfway through.
#
# AND IT IS PROVED, WHICH IS THE HALF THAT MATTERS. The drop-in's path is
# cloud-init's convention rather than this tree's, and nothing on the
# operator's machine can see whether this AMI's cloud-init honours it. So the
# removal is followed by its own check: if `sudo -n true` still answers 0, the
# rule is somewhere this step did not look and the bake REFUSES — a refused
# bake costs one machine, and an image with root in it is every box after it.
sudo rm -f "$BAKE_SUDOERS"
if sudo -n true 2>/dev/null; then
    die "${BAKE_SUDOERS} was removed and the bake account can STILL sudo without a
   password, so cloud-init on this image filed its rule somewhere else and the
   capture would bake passwordless root into every verifier box launched from
   it. NOTHING IS WRONG WITH THE BOX — this recipe is looking in the wrong
   place. Read \`sudo -l\` and \`ls /etc/sudoers.d\` on the box, point
   BAKE_SUDOERS at what you find, and bake again. Nothing was captured."
fi
say "the bake account's sudo rule is gone (${BAKE_SUDOERS}); the image's account is not root"

echo ""
say "ready for create-image"
