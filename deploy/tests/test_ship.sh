#!/usr/bin/env bash
# The drive for `deploy/ship.sh` — the fresh extract, the verification, the
# swap, the refusals and the exit codes.
#
#   ./deploy/tests/test_ship.sh          run every case
#   ./deploy/tests/test_ship.sh --list   name them and stop
#
# WHY IT EXISTS. The defect this script was written against is INVISIBLE when it
# happens: `tar -x` over an existing directory writes every file in the archive
# and deletes nothing, so a re-deploy across a commit that removed a file leaves
# that file on the box, under a `TREE` marker naming the new tree. Everything
# looks right. It is found only by counting files by hand on a live box.
#
# So the FIRST case here is the OLD ONE-LINER, kept for ever as a control: it
# performs the bare `tar -x` ship exactly as it was written and asserts that the
# survivor SURVIVES. It stays green-by-asserting-the-bug so the next reader can
# see the difference rather than take it on trust. Every case after it drives
# `ship.sh` over the same planted box and asserts the opposite.
#
# THE SHARP CASE has its own name below and it is the reason this is not
# cosmetic: `INSTALLED_APPS` is discovery-derived here, so a surviving
# `apps/<x>/apps.py` REINSTALLS an app the tree deleted.
#
# IT BUILDS ITS OWN BOX. There is no network and no ssh: a STUB `ssh` first on
# PATH runs the remote command string under `bash -c` with its working directory
# set to a scratch "box root", forwarding stdin so the tar pipe is real. What is
# proven is the CONTROL FLOW and the FILE SET — the same limit
# `deploy/tests/test_release.sh` declares about its stub `docker`.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * A REAL SSH. Authentication, `-i`, host keys, a dropped connection
#     mid-transfer: none of it is here. What is here is that a non-zero ssh is
#     exit 2 and that nothing is swapped when it happens.
#   * PERMISSIONS AND OWNERSHIP on the box. `deploy/.env`'s group (written by
#     the runbook's secrets step) is not something this drive can see; what it
#     asserts is that ship.sh does not carry that file at all and says so.
#   * WHETHER THE SHIPPED TREE RUNS. Building and starting are runbook Part 4's.
set -euo pipefail

cd "$(dirname "$0")/../.."

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_ship: $*" >&2
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
    echo "!! unknown argument '$1': test_ship.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v git >/dev/null 2>&1 || cannot_look "no git on PATH"
command -v tar >/dev/null 2>&1 || cannot_look "no tar on PATH"
[ -f deploy/ship.sh ] || cannot_look "deploy/ship.sh is not in this tree — there is nothing to drive"
git rev-parse --git-dir >/dev/null 2>&1 || cannot_look "not a git checkout — ship.sh ships a git tree and this drive has none"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-ship-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT

SHIP="$PWD/deploy/ship.sh"
TREE_ROOT="$PWD"

# --- the assertions (test_release.sh's helpers, same shapes) ------------------
DRIVE_OUT=""
DRIVE_EXIT=0
CURRENT=""
drive() {
    local label="$1" want="$2"
    shift 3
    CURRENT="$label"
    DRIVE_OUT="${WORK}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    set +e
    "$@" >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${DRIVE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    fi
}

says() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  ok       ${CURRENT} — says \"$1\""
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — does not say \"$1\""
        sed 's/^/             | /' "$DRIVE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    fi
}

holds() {
    local label="$1" want="$2" got="$3"
    if [ "$want" = "$got" ]; then
        echo "  ok       ${label} — ${got}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted '${want}', got '${got}'"
        FAILED=$((FAILED + 1))
    fi
}

# --- the scratch box ----------------------------------------------------------
#
# THE PLANT IS AN APP THAT NO LONGER EXISTS IN THE TREE. `apps/ghost/apps.py` is
# not tracked anywhere in this repository, so it is in NO archive this drive
# makes — which is exactly the state a file deleted upstream is in on a box that
# was overlaid. `deploy/.env` is planted too, because it is the one file the box
# legitimately holds and the archive legitimately does not.
# THE FIXTURE NAMESPACE, AND WHY IT IS NOT THE REAL ONE. `ship.sh`'s landing
# directory is composed from `DJB_DEPLOY_NAMESPACE` (deploy/dns.sh's refuse-unset
# grammar), and a drive whose fixture carried the deployment's REAL namespace
# could not tell a derivation from a hardcode: every assertion below would pass
# just as well against a script that ignored the variable and spelled the value.
# So the fixture is deliberately a name no deployment uses. Do not "simplify" it
# back to the real one — that removes the only thing these cases prove.
FIXTURE_NS="shipdrive"
BOX=""
SSH_LOG=""
GHOST="${FIXTURE_NS}/apps/ghost/apps.py"
N=0
fresh_box() {
    N=$((N + 1))
    BOX="${WORK}/box${N}"
    SSH_LOG="${WORK}/box${N}.ssh.log"
    mkdir -p "$BOX/bin" "$BOX/root/${FIXTURE_NS}/apps/ghost" "$BOX/root/${FIXTURE_NS}/deploy"
    : >"$SSH_LOG"

    cat >"$BOX/root/$GHOST" <<'GHOSTPY'
class GhostConfig(AppConfig):
    name = "apps.ghost"
GHOSTPY
    echo "SECRET_KEY='the box already had this'  # pragma: allowlist secret" \
        >"$BOX/root/${FIXTURE_NS}/deploy/.env"
    echo "stale" >"$BOX/root/${FIXTURE_NS}/STALE-MARKER"

    # THE STUB SSH. Strips the flags and the destination, records the remote
    # command, and runs it under bash in the box root with stdin forwarded — so
    # the tar that arrives is the tar that was sent.
    cat >"$BOX/bin/ssh" <<'SSHSTUB'
#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
    case "$1" in
    -i | -o | -p) shift 2 ;;
    -*) shift ;;
    *) break ;;
    esac
done
[ "$#" -gt 0 ] || { echo "stub ssh: no destination" >&2; exit 255; }
shift # the user@host
printf '%s\n' "$*" >>"$DJB_SHIP_SSH_LOG"

if [ "${DJB_SHIP_SSH_FAIL:-}" = "1" ]; then
    echo "stub ssh: the case asked ssh to fail" >&2
    exit 255
fi

cd "$DJB_SHIP_BOX_ROOT" || exit 255
bash -c "$*"
rc=$?

# The sabotage knobs fire AFTER the command they follow, so a case can make the
# landed tree disagree with the archive without touching ship.sh.
case "$*" in
*"tar -x"*)
    if [ -n "${DJB_SHIP_DELETE_AFTER:-}" ]; then rm -f "$DJB_SHIP_DELETE_AFTER"; fi
    if [ -n "${DJB_SHIP_ADD_AFTER:-}" ]; then
        mkdir -p "$(dirname "$DJB_SHIP_ADD_AFTER")"
        echo "a file the archive never carried" >"$DJB_SHIP_ADD_AFTER"
    fi
    ;;
esac
exit "$rc"
SSHSTUB
    chmod +x "$BOX/bin/ssh"
}

ship() {
    local envs=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
        *=*)
            envs+=("$1")
            shift
            ;;
        *) break ;;
        esac
    done
    env PATH="${BOX}/bin:$PATH" \
        DJB_SHIP_SSH_LOG="$SSH_LOG" \
        DJB_SHIP_BOX_ROOT="${BOX}/root" \
        DJB_DEPLOY_NAMESPACE="$FIXTURE_NS" \
        ${envs[@]+"${envs[@]}"} "$@"
}

# The same runner with the namespace REMOVED rather than overridden, for the
# refusal cases. `env -u` rather than an empty value, because unset and empty
# must both refuse and only one of them is what an operator who never set it
# has.
ship_without_namespace() {
    ship env -u DJB_DEPLOY_NAMESPACE "$@"
}

on_box() { [ -e "${BOX}/root/$1" ] && echo yes || echo no; }
box_file_count() { find "${BOX}/root/$1" ! -type d 2>/dev/null | wc -l | tr -d ' '; }

# The ref every case ships. HEAD is dirty while a rung is being built — ship.sh
# refuses that on purpose — so the drive names the committed tree explicitly,
# which is also the `--ref` path the rollback uses.
REF="$(git rev-parse HEAD)"
ARCHIVE_COUNT="$(git archive --add-virtual-file=TREE:probe "$REF" | tar -t | grep -cv '/$')"

# =============================================================================
# The control: the OLD one-liner, and the survivor it leaves
# =============================================================================

case_the_overlay_one_liner_leaves_the_survivor_behind() {
    # RUNBOOK STEP 30 AS IT WAS WRITTEN, performed against the stub box. Kept as
    # a permanent control rather than a one-off red: it is the only thing in the
    # tree that demonstrates WHY the fresh extract exists, and if `tar -x` ever
    # started deleting, this case would be the one that noticed.
    local rc
    fresh_box
    holds "the ghost app is planted on the box" "yes" "$(on_box "$GHOST")"
    set +e
    git archive --add-virtual-file=TREE:"stub-tag" "$REF" |
        ship bash -c "cd \"\$DJB_SHIP_BOX_ROOT\" && mkdir -p ${FIXTURE_NS} && tar -x -C ${FIXTURE_NS}"
    rc=$?
    set -e
    holds "the overlay extract itself succeeded" "0" "$rc"
    # THE DEFECT, ASSERTED. Both of these are "yes" and both of them are wrong.
    holds "OVERLAY: a removed app's apps.py SURVIVES the re-ship" "yes" "$(on_box "$GHOST")"
    holds "OVERLAY: an unrelated stale file SURVIVES too" "yes" \
        "$(on_box "${FIXTURE_NS}/STALE-MARKER")"
    holds "OVERLAY: the TREE marker names the NEW tree over the OLD files" "yes" \
        "$(on_box "${FIXTURE_NS}/TREE")"
}

# =============================================================================
# The fresh extract — the same box, the other answer
# =============================================================================

case_the_sharp_case_a_removed_apps_py_does_not_survive_a_ship() {
    # THE ONE THAT MATTERS. `INSTALLED_APPS` is derived by walking `apps/*` for an
    # `AppConfig`, so a surviving `apps/ghost/apps.py` is not a stale file — it is
    # an app this tree deleted, installed again, with its routes and its models,
    # and nothing in the release, the gate or /readyz able to see it.
    fresh_box
    holds "the ghost app is planted on the box" "yes" "$(on_box "$GHOST")"
    drive "ship over a ghost app" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "SHIP: the removed app's apps.py is GONE" "no" "$(on_box "$GHOST")"
    holds "SHIP: its directory is gone with it" "no" "$(on_box "${FIXTURE_NS}/apps/ghost")"
    holds "SHIP: the unrelated stale file is gone too" "no" "$(on_box "${FIXTURE_NS}/STALE-MARKER")"
    says "SHIPPED"
}

case_the_landed_file_set_is_exactly_the_archives() {
    fresh_box
    drive "ship a clean tree" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the box holds exactly the archive's file count" "$ARCHIVE_COUNT" \
        "$(box_file_count "${FIXTURE_NS}")"
    says "no survivor, nothing missing"
}

case_the_tree_marker_carries_the_laptops_own_image_tag() {
    # N121b. The box has no `.git`, so `TREE` is the only thing that can answer
    # "which tree is this" — and it must answer with the same bytes the laptop's
    # own `image-tag` prints, or the image built on the box is tagged with a lie.
    fresh_box
    drive "ship for the TREE marker" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    local landed expected
    landed="$(cat "${BOX}/root/${FIXTURE_NS}/TREE" 2>/dev/null || echo "<absent>")"
    expected="tree-$(git rev-parse --short=12 "${REF}^{tree}")"
    holds "TREE names this tree" "$expected" "$landed"
    # And the same tag is what `provision.sh image-tag` derives on this laptop for
    # this tree — read from the function rather than repeated here.
    holds "TREE equals the laptop's own image-tag derivation" \
        "$(cd "$TREE_ROOT" && git rev-parse --short=12 "${REF}^{tree}" | sed 's/^/tree-/')" \
        "$landed"
}

case_the_deploy_env_is_not_carried_and_the_ship_says_why() {
    # It is the one file the box legitimately holds and the archive legitimately
    # does not. Hand-copying it loses the GROUP and every app container then
    # restarts for ever with `Permission denied`. So the
    # ship does not carry it, does not preserve it into the new tree, and points
    # at the step that writes it properly.
    fresh_box
    drive "ship past deploy/.env" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the new tree carries no deploy/.env" "no" "$(on_box "${FIXTURE_NS}/deploy/.env")"
    holds "the tree it replaced still has the old one, beside it" "yes" \
        "$(on_box "${FIXTURE_NS}.previous/deploy/.env")"
    says "step 31"
}

case_the_tree_it_replaced_is_kept_for_the_rollback() {
    # The runbook's rollback is "re-ship the previous tree". Keeping it on the box
    # makes the first move at 3am a look rather than a laptop.
    fresh_box
    drive "ship keeping the previous tree" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the previous tree is beside the live one, ghost and all" "yes" \
        "$(on_box "${FIXTURE_NS}.previous/apps/ghost/apps.py")"
    holds "the staging directory is gone once the swap is done" "no" \
        "$(on_box "${FIXTURE_NS}.incoming")"
}

case_a_leftover_landing_from_a_failed_ship_is_cleared_not_overlaid() {
    # THE CASE THAT COVERS THE `rm -rf` ITSELF, and it exists because plant-verify
    # found it missing: severing the fresh-extract guard left every other case in
    # this file green, because a fresh scratch box never has a landing directory
    # to overlay ONTO.
    #
    # The state is not hypothetical — it is the one an exit-1 ship LEAVES: the
    # verification refuses and the bad tree stays in `.incoming` for somebody to
    # look at. If the next ship overlaid onto that, the survivor the first ship
    # refused would be carried into the tree the second one swaps into place, and
    # the refusal would have made things worse rather than better.
    fresh_box
    mkdir -p "${BOX}/root/${FIXTURE_NS}.incoming/apps/ghost"
    cp "${BOX}/root/$GHOST" "${BOX}/root/${FIXTURE_NS}.incoming/apps/ghost/apps.py"
    echo "left over" >"${BOX}/root/${FIXTURE_NS}.incoming/LEFTOVER"
    drive "ship over a leftover landing" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the leftover ghost did not ride into the live tree" "no" "$(on_box "$GHOST")"
    holds "the leftover marker did not either" "no" "$(on_box "${FIXTURE_NS}/LEFTOVER")"
    holds "the box holds exactly the archive's file count" "$ARCHIVE_COUNT" \
        "$(box_file_count "${FIXTURE_NS}")"
}

case_a_first_ship_onto_an_empty_box_works() {
    # Nothing to move aside. The swap must not require a previous tree to exist.
    fresh_box
    rm -rf "${BOX}/root/${FIXTURE_NS}"
    drive "first ship" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the tree landed" "yes" "$(on_box "${FIXTURE_NS}/TREE")"
    holds "no previous tree was invented" "no" "$(on_box "${FIXTURE_NS}.previous")"
}

# =============================================================================
# The verification — exit 1, and NOTHING swapped
# =============================================================================

case_a_survivor_the_verification_can_see_is_exit_one() {
    # The belt for the fresh extract. If anything ever put a file into the landing
    # directory that the archive did not carry, the ship refuses rather than
    # swapping it into place.
    fresh_box
    drive "a survivor in the landing" 1 -- ship \
        DJB_SHIP_ADD_AFTER="${BOX}/root/${FIXTURE_NS}.incoming/apps/ghost/apps.py" \
        "$SHIP" ec2-user@box.invalid --ref "$REF"
    says "NOT the tree in the archive"
    says "apps/ghost/apps.py"
    says "discovery-derived"
    # THE PROPERTY WORTH MORE THAN THE REFUSAL: the box goes on serving what it
    # was serving. A verification that failed and swapped anyway would be a
    # verification that made things worse.
    says "NOTHING WAS SWAPPED"
    holds "the live tree was not replaced" "yes" "$(on_box "$GHOST")"
    holds "no previous tree was made" "no" "$(on_box "${FIXTURE_NS}.previous")"
}

case_a_missing_file_is_exit_one() {
    fresh_box
    drive "a truncated landing" 1 -- ship \
        DJB_SHIP_DELETE_AFTER="${BOX}/root/${FIXTURE_NS}.incoming/TREE" \
        "$SHIP" ec2-user@box.invalid --ref "$REF"
    says "NOT the tree in the archive"
    says "TREE"
    says "NOTHING WAS SWAPPED"
    holds "the live tree was not replaced" "yes" "$(on_box "$GHOST")"
}

case_a_box_that_cannot_be_read_is_exit_two() {
    # "I could not look" is never "I looked and it is fine", and it is never
    # "I looked and it is wrong" either — an unreachable box and an empty listing
    # are indistinguishable to a comparison, and only one of them is a bad ship.
    fresh_box
    drive "ssh that will not answer" 2 -- ship DJB_SHIP_SSH_FAIL=1 \
        "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the live tree was not replaced" "yes" "$(on_box "$GHOST")"
}

# =============================================================================
# The refusals — exit 2, and nothing sent
# =============================================================================

case_an_unknown_flag_is_refused() {
    fresh_box
    drive "unknown flag" 2 -- ship "$SHIP" ec2-user@box.invalid --overlay
    says "unknown argument"
    holds "unknown flag: ssh was never invoked" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
}

case_a_piped_stdout_is_refused() {
    # The pipe refusal in the ship's vocabulary: the exit status is the
    # difference between
    # "the box is running this tree" and "this tree plus whatever was there".
    fresh_box
    drive "piped stdout" 2 -- ship bash -c "set -o pipefail; '$SHIP' ec2-user@box.invalid --ref '$REF' | cat"
    says "refuses pipes"
    holds "piped stdout: ssh was never invoked" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
}

case_no_destination_is_refused() {
    fresh_box
    drive "no destination" 2 -- ship "$SHIP"
    says "name the box"
    holds "no destination: ssh was never invoked" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
}

case_a_ref_that_names_no_tree_is_refused() {
    fresh_box
    drive "unknown ref" 2 -- ship "$SHIP" ec2-user@box.invalid --ref no-such-ref-anywhere
    says "does not name a tree"
    holds "unknown ref: ssh was never invoked" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
}

case_an_unset_namespace_is_refused() {
    # THE LANDING DIRECTORY IS CONFIGURATION AND HAS NO DEFAULT, for `dns.sh`'s
    # reason one directory down: a guessed namespace is a `rm -rf` and a swap
    # under a name this deployment may not own. Refused before the archive is
    # built, so nothing is even read, let alone sent.
    fresh_box
    drive "no namespace" 2 -- ship_without_namespace \
        "$SHIP" ec2-user@box.invalid --ref "$REF"
    says "DJB_DEPLOY_NAMESPACE"
    holds "no namespace: ssh was never invoked" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
    holds "no namespace: the box is exactly as it was" "yes" "$(on_box "$GHOST")"
}

case_the_landing_is_composed_from_the_namespace() {
    # THE DERIVATION, ASSERTED AT THE ONE PLACE IT IS OBSERVABLE FOR FREE.
    # `--dry-run` prints the landing, the staging directory and the kept
    # previous tree without contacting the box, and all three are the namespace
    # verbatim plus this script's own two suffixes. Driven twice under two
    # DIFFERENT namespaces, because one value cannot distinguish a derivation
    # from a coincidence.
    fresh_box
    drive "landing under the fixture namespace" 0 -- ship \
        "$SHIP" ec2-user@box.invalid --ref "$REF" --dry-run
    says "landing      ${FIXTURE_NS}  (staged in ${FIXTURE_NS}.incoming"
    says "${FIXTURE_NS}.previous"
    drive "landing under a second namespace" 0 -- ship \
        DJB_DEPLOY_NAMESPACE=otherdrive \
        "$SHIP" ec2-user@box.invalid --ref "$REF" --dry-run
    says "landing      otherdrive  (staged in otherdrive.incoming"
    says "otherdrive.previous"
    holds "neither dry run contacted the box" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
}

case_an_explicit_dest_outranks_the_namespace() {
    # `--dest` is the operator naming the directory outright, and it is the ONE
    # escape — the same shape `DATABASE_NAME` has over `scripts/db.sh`'s
    # derivation. With it there is nothing to guess, so the refusal must not
    # fire.
    fresh_box
    drive "--dest with no namespace" 0 -- ship_without_namespace \
        "$SHIP" ec2-user@box.invalid --ref "$REF" --dest namedbyhand --dry-run
    says "landing      namedbyhand"
}

case_dry_run_touches_nothing() {
    fresh_box
    drive "--dry-run" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF" --dry-run
    says "DRY RUN"
    says "nothing was touched."
    holds "--dry-run: ssh was never invoked" "0" "$(wc -l <"$SSH_LOG" | tr -d ' ')"
    holds "--dry-run: the box is exactly as it was" "yes" "$(on_box "$GHOST")"
}

case_the_ship_is_re_runnable() {
    # Twice in a row lands the same tree; the second run's previous is the first
    # run's live tree, and nothing accumulates.
    fresh_box
    drive "first ship" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    drive "second ship" 0 -- ship "$SHIP" ec2-user@box.invalid --ref "$REF"
    holds "the box still holds exactly the archive's file count" "$ARCHIVE_COUNT" \
        "$(box_file_count "${FIXTURE_NS}")"
    holds "the previous tree is the tree, not a pile of them" "$ARCHIVE_COUNT" \
        "$(box_file_count "${FIXTURE_NS}.previous")"
}

case_the_overlay_one_liner_leaves_the_survivor_behind
case_the_sharp_case_a_removed_apps_py_does_not_survive_a_ship
case_the_landed_file_set_is_exactly_the_archives
case_the_tree_marker_carries_the_laptops_own_image_tag
case_the_deploy_env_is_not_carried_and_the_ship_says_why
case_the_tree_it_replaced_is_kept_for_the_rollback
case_a_leftover_landing_from_a_failed_ship_is_cleared_not_overlaid
case_a_first_ship_onto_an_empty_box_works
case_a_survivor_the_verification_can_see_is_exit_one
case_a_missing_file_is_exit_one
case_a_box_that_cannot_be_read_is_exit_two
case_an_unknown_flag_is_refused
case_a_piped_stdout_is_refused
case_no_destination_is_refused
case_a_ref_that_names_no_tree_is_refused
case_an_unset_namespace_is_refused
case_the_landing_is_composed_from_the_namespace
case_an_explicit_dest_outranks_the_namespace
case_dry_run_touches_nothing
case_the_ship_is_re_runnable

echo "test_ship: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. The one that matters most is the FILE SET: an" >&2
    echo "   overlay leaves a deleted app's apps.py on the box, discovery reinstalls" >&2
    echo "   it, and nothing anywhere says so." >&2
    exit 1
fi
exit 0
