#!/usr/bin/env bash
# Put THIS tree on the box — the whole tree, and nothing that was there before.
#
#   deploy/ship.sh ec2-user@1.2.3.4                       ship HEAD to ~/$DJB_DEPLOY_NAMESPACE
#   deploy/ship.sh ec2-user@1.2.3.4 --key ~/.ssh/box.pem  with an identity file
#   deploy/ship.sh ec2-user@1.2.3.4 --ref <sha>           ship an older tree (the rollback)
#   deploy/ship.sh ec2-user@1.2.3.4 --dry-run             say what would land and touch nothing
#
# WHY THIS EXISTS. The runbook's ship step used to be one line:
#
#     git archive --add-virtual-file=TREE:"$(./deploy/provision.sh image-tag)" HEAD \
#       | ssh … 'mkdir -p "$NS" && tar -x -C "$NS"'
#
# `tar -x` OVERLAYS. It writes every file in the archive and DELETES NOTHING, so
# a file removed upstream survives on the box while the `TREE` marker beside it
# names the new tree. LOAD-1a measured it: the box held 1119 files carrying the
# tag of a 1117-file tree, with `apps/core/storage.py` and its test — deleted two
# commits earlier — still sitting there. The deployment's own "every image is
# pinned to a tree" claim was false on the only machine it mattered on.
#
# THE SHARP EDGE, AND IT IS WHY THIS IS NOT COSMETIC. `INSTALLED_APPS` is
# DISCOVERY-DERIVED in this template: every package under `apps/` with an
# `AppConfig` is installed, because that is what lets one agent per app work in
# parallel without editing a shared file (CLAUDE.md, django-conventions §1). So a
# re-deploy across a commit that REMOVED AN APP leaves that app's `apps.py` on
# the box and Django installs it again — the app comes back from the dead,
# with its routes, its models and its migrations, and nothing in the release, the
# gate or `/readyz` can see it. An overlay is not a slow leak here; it is a
# resurrection.
#
# WHAT IT DOES INSTEAD, in one sentence: extract into a FRESH location, VERIFY
# the landed file set against the archive's own manifest, and only then swap it
# into place — keeping the tree it replaced beside it, which is what makes the
# runbook's rollback a re-ship rather than an improvisation.
#
# THE EXIT STATUS IS THE VERDICT, and it is this repository's three:
#
#   0   the tree landed and every file in the archive is on the box, with
#       nothing else in the deployment directory.
#   1   it landed and the verification FAILED — a survivor, or a missing file.
#       The new tree is left in the `.incoming` directory, NOTHING was swapped,
#       and the box goes on serving whatever it was serving.
#   2   refused before anything was shipped, or the box could not be READ.
#       "I could not look" is never quietly turned into "it is fine".
#
# WHAT IT DELIBERATELY DOES NOT DO:
#
#   * IT DOES NOT CARRY `deploy/.env`. `git archive` ships the tracked tree and
#     that file is not in it, by design — it is written on the box from the vault
#     by runbook step 31, `chgrp 10001, mode 640`. Hand-copying it across loses
#     the GROUP and every app container then restarts for ever with `Permission
#     denied` and no explanation. So this
#     script does not copy it, does not preserve it, and says so on the way out:
#     the preservation route is step 31 and it is one command.
#   * IT DOES NOT BUILD OR START ANYTHING. Steps 33 and 34 are Part 4's.
#   * IT DOES NOT DECIDE WHICH TREE SHOULD SHIP. That is the PM's judgement.

set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/.." && pwd)"
set +x  # never; see deploy/entrypoint.sh for the same line and the same reason

# --- it refuses to be piped ---------------------------------------------------
# release.sh's detection and release.sh's CI exemption, deliberately identical
# (deploy/release.sh:85-90, scripts/check.sh:38-64). A pipe replaces this
# script's exit status with the filter's, and the exit status is the difference
# between "the box is running this tree" and "the box is running this tree plus
# whatever was there before".
if [ -z "${CI:-}" ] && { [ -p /dev/fd/1 ] || [ -p /dev/stdout ]; }; then
    echo "!! ship refuses pipes — a filter replaces the exit status of the ship with" >&2
    echo "   the filter's, and the exit status is the whole verdict. Run it" >&2
    echo "   bare or redirect to a file." >&2
    exit 2
fi

die() {
    # 2 is "could not get as far as shipping", or "could not look". An archive
    # that was never sent must never share an exit code with a tree that landed
    # wrong.
    echo "!! ship: $*" >&2
    echo "   Nothing was shipped; the box is untouched." >&2
    exit 2
}

say() { echo "ship: $*"; }

usage() {
    sed -n '2,8p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo ""
    echo "The header of ${BASH_SOURCE[0]} says what it does and why."
    exit 2
}

DESTINATION=""
KEY=""
# THE LANDING DIRECTORY IS CONFIGURATION AND HAS NO DEFAULT — `deploy/dns.sh`'s
# grammar, one directory down. This script `rm -rf`s the staging area it names
# and moves the live tree aside; a guessed name is a destructive operation
# against a directory this deployment may not own. So the default is EMPTY and
# unset is a refusal below, never a fallback. `--dest` outranks it: an operator
# who names the directory outright has left nothing to guess.
REMOTE_DIR="${DJB_DEPLOY_NAMESPACE:-}"
REF="HEAD"
DRY_RUN=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    -h | --help)
        sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
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
    --ref)
        [ "$#" -ge 2 ] || die "--ref needs a git ref"
        REF="$2"
        shift 2
        ;;
    --dry-run)
        DRY_RUN=1
        shift
        ;;
    -*)
        echo "!! ship: unknown argument '$1'." >&2
        echo "" >&2
        usage
        ;;
    *)
        [ -z "$DESTINATION" ] || die "two destinations named ('$DESTINATION' and '$1'); this ships to one box"
        DESTINATION="$1"
        shift
        ;;
    esac
done

[ -n "$DESTINATION" ] || {
    echo "!! ship: no destination — name the box, e.g. ec2-user@1.2.3.4" >&2
    echo "" >&2
    usage
}

# --- the preconditions, all of them before anything is sent -------------------
[ -n "$REMOTE_DIR" ] || die "DJB_DEPLOY_NAMESPACE is required — this deployment's namespace, the directory this tree lands in on the box. There is no default: a guessed namespace is an 'rm -rf' and a swap in somebody else's directory. It is a slot in this environment's env file (deploy/env.staging.example), or name the directory outright with --dest."
command -v git >/dev/null 2>&1 || die "no 'git' on PATH"
command -v ssh >/dev/null 2>&1 || die "no 'ssh' on PATH"
command -v tar >/dev/null 2>&1 || die "no 'tar' on PATH"
git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1 || die "$ROOT is not a git checkout, so there is no tree to ship and nothing that could name one"
git -C "$ROOT" rev-parse --verify --quiet "${REF}^{tree}" >/dev/null || die "'$REF' does not name a tree in this checkout"

# `--add-virtual-file` is what puts the tree's name INSIDE the archive, which is
# the whole of N121b: the box gets no `.git`, so without it `provision.sh
# image-tag` on the box prints `untracked` and the image built there is tagged
# with a lie.
# Read off `git --version` rather than off `git archive --help`, which on a mac
# opens a man page and answers about a formatter rather than about a flag.
GIT_VERSION="$(git --version | sed -n 's/^git version \([0-9][0-9.]*\).*/\1/p')"
GIT_MAJOR="${GIT_VERSION%%.*}"
GIT_MINOR="${GIT_VERSION#*.}"
GIT_MINOR="${GIT_MINOR%%.*}"
[ -n "$GIT_MAJOR" ] && [ -n "$GIT_MINOR" ] ||
    die "could not read a version out of 'git --version'; --add-virtual-file needs git >= 2.38 and this cannot tell whether it is there"
if [ "$GIT_MAJOR" -lt 2 ] || { [ "$GIT_MAJOR" -eq 2 ] && [ "$GIT_MINOR" -lt 38 ]; }; then
    die "git ${GIT_VERSION} has no --add-virtual-file (needs >= 2.38); without it the box cannot know which tree it is holding"
fi

# THE TAG IS DERIVED WHERE GIT IS, BY THE FUNCTION THAT ALREADY OWNS IT. For the
# ordinary case — shipping HEAD — this is `provision.sh image-tag` verbatim, so
# the bytes in the archive's `TREE` file and the bytes the laptop prints are the
# same bytes by construction rather than by anybody remembering. For an explicit
# `--ref` (the rollback) the tag is derived from that ref's tree and the run says
# so, because `image-tag` answers about HEAD and only about HEAD.
if [ "$REF" = "HEAD" ]; then
    [ -x "$HERE/provision.sh" ] || die "no $HERE/provision.sh — the image tag is its function and this script does not own a second copy"
    TREE_TAG="$("$HERE/provision.sh" image-tag)" || exit 2
else
    TREE_TAG="tree-$(git -C "$ROOT" rev-parse --short=12 "${REF}^{tree}")"
fi

case "$TREE_TAG" in
untracked)
    die "the image tag reads 'untracked' — this checkout cannot say which tree it is, and a box tagged 'untracked' is a box whose images name nothing"
    ;;
*-dirty)
    # `git archive` ships the COMMITTED tree; the tag would say `-dirty`. The box
    # would then hold clean bytes under a name that says they are not, which is
    # the exact class of lie this whole `TREE` mechanism exists to remove.
    echo "!! ship: this checkout is dirty, so the tag would be '$TREE_TAG' while the" >&2
    echo "   archive carries the COMMITTED tree — the box would hold clean bytes under" >&2
    echo "   a name that says otherwise. Commit the change, or name the tree you mean:" >&2
    echo "       ./deploy/ship.sh $DESTINATION --ref <sha>" >&2
    echo "   Nothing was shipped; the box is untouched." >&2
    exit 2
    ;;
esac

SSH_ARGS=()
if [ -n "$KEY" ]; then
    [ -f "$KEY" ] || die "no identity file at $KEY"
    SSH_ARGS+=(-i "$KEY")
fi

INCOMING="${REMOTE_DIR}.incoming"
PREVIOUS="${REMOTE_DIR}.previous"

say "destination  ${DESTINATION}"
say "tree         ${REF} → ${TREE_TAG}"
say "landing      ${REMOTE_DIR}  (staged in ${INCOMING}; the tree it replaces is kept as ${PREVIOUS})"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-ship.XXXXXX")" || die "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT
ARCHIVE="$WORK/tree.tar"
EXPECTED="$WORK/expected"
LANDED="$WORK/landed"

# =============================================================================
# 1 · the archive, and the manifest READ OFF IT
# =============================================================================
# Written to a file rather than streamed straight into ssh, for one reason: the
# manifest this verifies against is then `tar -t` over THE SAME BYTES that get
# sent. Deriving it from `git ls-tree` instead would be a second opinion about
# what is in the archive, and a `.gitattributes export-ignore` a product added
# would make the two disagree silently — the verification passing while the
# thing it verified was never checked.
git -C "$ROOT" archive --add-virtual-file=TREE:"$TREE_TAG" "$REF" >"$ARCHIVE" ||
    die "git archive failed; nothing was sent"
[ -s "$ARCHIVE" ] || die "git archive produced an empty file; nothing was sent"

# Directories are entries in a tar and are not files on the box; the comparison
# is over the file set, so they come out of both sides rather than one.
tar -tf "$ARCHIVE" | grep -v '/$' | LC_ALL=C sort >"$EXPECTED"
EXPECTED_COUNT="$(wc -l <"$EXPECTED" | tr -d ' ')"
[ "$EXPECTED_COUNT" -gt 0 ] || die "the archive lists no files; nothing was sent"
say "archive      ${EXPECTED_COUNT} files, including the TREE marker"

if [ -n "$DRY_RUN" ]; then
    say "DRY RUN — the box was not contacted."
    say "would extract into ${INCOMING} (fresh: removed first, never overlaid)"
    say "would verify the landed file set equals the ${EXPECTED_COUNT} above"
    say "would swap ${REMOTE_DIR} aside to ${PREVIOUS} and move ${INCOMING} into place"
    say "would NOT carry deploy/.env — runbook step 31 writes it on the box, with the group"
    say "nothing was touched."
    exit 0
fi

remote() {
    ssh ${SSH_ARGS[@]+"${SSH_ARGS[@]}"} "$DESTINATION" "$1"
}

# =============================================================================
# 2 · extract into a FRESH location
# =============================================================================
# `rm -rf` first, and that is the whole fix: the incoming directory is emptied
# before the archive is unpacked into it, so what lands is the archive and
# NOTHING ELSE. Not the live directory — a half-extracted deployment directory
# is a box serving a tree that exists in no repository — so the removal is only
# ever of the staging area this script owns the name of.
say ""
say "[1/3] extract — into ${INCOMING}, emptied first, never overlaid"
set +e
remote "set -e; rm -rf '${INCOMING}'; mkdir -p '${INCOMING}'; tar -x -C '${INCOMING}'" <"$ARCHIVE"
rc=$?
set -e
if [ "$rc" != "0" ]; then
    echo "!! ship: the extract failed (exit ${rc})." >&2
    echo "   Nothing was swapped; the box is still serving whatever it was serving." >&2
    exit 2
fi

# =============================================================================
# 3 · verify the landed file set against the archive's manifest
# =============================================================================
# THE HALF LOAD-1A PERFORMED BY HAND AND THE RUNBOOK LACKED. Extracting into a
# fresh directory makes a survivor impossible in theory; this is what makes it
# checkable in fact, and it is also the only thing standing between a truncated
# transfer and a box that looks deployed.
#
# `find` failing, or answering nothing, is exit 2 — "I could not look" — because
# an empty listing and an unreachable box are indistinguishable to a comparison
# and only one of them means the ship failed.
say ""
say "[2/3] verify — the landed file set against the archive's own manifest"
set +e
remote "cd '${INCOMING}' && find . ! -type d -print | sed 's|^\\./||' | LC_ALL=C sort" >"$LANDED" 2>"$WORK/find.err"
rc=$?
set -e
if [ "$rc" != "0" ] || [ ! -s "$LANDED" ]; then
    echo "!! ship: could not read the landed file set back off the box." >&2
    sed 's/^/   /' "$WORK/find.err" >&2 || true
    echo "   The archive is in ${INCOMING} and NOTHING was swapped — this is 'I could" >&2
    echo "   not look', not 'I looked and it is wrong'." >&2
    exit 2
fi

MISSING="$(LC_ALL=C comm -23 "$EXPECTED" "$LANDED" || true)"
SURVIVORS="$(LC_ALL=C comm -13 "$EXPECTED" "$LANDED" || true)"
if [ -n "$MISSING" ] || [ -n "$SURVIVORS" ]; then
    echo "" >&2
    echo "!! ship: the tree on the box is NOT the tree in the archive." >&2
    if [ -n "$SURVIVORS" ]; then
        echo "   $(printf '%s\n' "$SURVIVORS" | wc -l | tr -d ' ') file(s) are on the box and not in the archive:" >&2
        printf '%s\n' "$SURVIVORS" | sed 's/^/     + /' >&2
        echo "   A SURVIVOR IS NOT COSMETIC: INSTALLED_APPS is discovery-derived, so a" >&2
        echo "   surviving apps/<x>/apps.py reinstalls an app this tree deleted." >&2
    fi
    if [ -n "$MISSING" ]; then
        echo "   $(printf '%s\n' "$MISSING" | wc -l | tr -d ' ') file(s) are in the archive and not on the box:" >&2
        printf '%s\n' "$MISSING" | sed 's/^/     - /' >&2
    fi
    echo "   NOTHING WAS SWAPPED. ${REMOTE_DIR} is untouched and the box is still" >&2
    echo "   serving whatever it was serving; the bad extract is in ${INCOMING}." >&2
    exit 1
fi
say "  ${EXPECTED_COUNT} files, exactly the archive's set — no survivor, nothing missing"

# =============================================================================
# 4 · swap it into place, keeping the tree it replaced
# =============================================================================
# The swap is two `mv`s inside one remote shell, so the window in which the
# deployment directory does not exist is as short as a rename. The tree it
# replaces is KEPT as `<dest>.previous` rather than deleted — not as a backup of
# the code (git is that) but because the runbook's rollback is "re-ship the
# previous tree", and having it already on the box makes the first thing an
# operator does at 3am a `mv` instead of a laptop.
say ""
say "[3/3] swap — ${INCOMING} into place, ${REMOTE_DIR} aside to ${PREVIOUS}"
set +e
remote "set -e; rm -rf '${PREVIOUS}'; if [ -e '${REMOTE_DIR}' ]; then mv '${REMOTE_DIR}' '${PREVIOUS}'; fi; mv '${INCOMING}' '${REMOTE_DIR}'"
rc=$?
set -e
if [ "$rc" != "0" ]; then
    echo "!! ship: the swap failed (exit ${rc}) AFTER the tree verified." >&2
    echo "   Look on the box: one of ${REMOTE_DIR}, ${PREVIOUS} or ${INCOMING} holds it." >&2
    exit 1
fi

echo ""
say "SHIPPED. ${EXPECTED_COUNT} files at ${REMOTE_DIR}, tagged ${TREE_TAG}."
say "The tree it replaced is at ${PREVIOUS} — the rollback re-ships that, it does not"
say "edit this one."
say ""
say "deploy/.env was NOT carried and must not be hand-copied: it is written on the"
say "box from the vault by runbook step 31, which is also what gives it the group"
say "the containers read it as. Run step 31 next."
exit 0
