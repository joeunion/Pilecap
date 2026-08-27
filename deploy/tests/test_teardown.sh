#!/usr/bin/env bash
# The drive for `deploy/teardown.sh --all-mine` — the reaper's ORDERING, its
# loud per-volume failure, and the ownership guard it may never widen.
#
#   ./deploy/tests/test_teardown.sh          run every case
#   ./deploy/tests/test_teardown.sh --list   name them and stop
#
# WHY IT EXISTS. `--all-mine` is a DESTRUCTIVE instrument whose two interesting
# properties are both invisible on a happy path:
#
#   * THE ORDER OF ITS TWO SWEEPS. It ran the derived-name orphan sweep BEFORE
#     the per-project `down`. On an empty machine that is indistinguishable from
#     the right order. On a LIVE stack every `docker volume rm` fails, `set -e`
#     kills the script at the first one, and NOTHING is torn down — while the
#     output has already announced "volumes ... with no project left to own
#     them" about a project with eleven running containers. Reproduced live
#     before the fix; case_a and case_b are that reproduction, pinned.
#   * WHAT IT REFUSES TO TOUCH. The sweep is matched on `provision.sh
#     derived-project-name` and not on the resolved/adopted name, because the
#     resolved one folds in an exported `COMPOSE_PROJECT_NAME` and the adopted
#     line in `deploy/.env` — values somebody else can set. Fold those in and a
#     destructive sweep's blast radius is set by its environment.
#     case_g exports both and proves the sweep ignored them.
#
# IT USES A REAL DOCKER, DELIBERATELY, unlike `test_release.sh`'s stub. The
# defect is "a volume that is IN USE cannot be removed", and no stub can be
# wrong about that in the same way the daemon is. So the cases build throwaway
# `busybox` stacks — one container, one sleep, one volume — and reap those. No
# image is built, nothing of this repository's stack is started, and every
# object the drive creates is labelled with a project name derived from its own
# `mktemp -d` path, which no other checkout on the machine can produce.
#
# IT BUILDS ITS OWN CHECKOUTS. Each case gets a scratch directory holding a COPY
# of `teardown.sh`, a COPY of `provision.sh` (only `derived-project-name` is
# ever called) and a stub `compose.yaml` — `test_release.sh`'s shape and its
# declared limit: a copy, not the file itself, is what runs, and the copy is
# made with `cp` from this tree in every case.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * THE REAL STACK'S SERVICES. The stub compose file has two busybox services
#     and two volumes, not Postgres and ClickStack. What is proven is the
#     CONTROL FLOW and the OBJECT SET; what a real `down` does to a real
#     database is Docker's business.
#   * THE `local` LADDER. `teardown.sh local`'s REFUSED / ENFORCEMENT BROKEN
#     ownership ladder and the AWS branch are not driven here. This file is
#     `--all-mine`'s.
#   * ONE DOCKER VERSION. Everything here is what the daemon on the machine that
#     runs it does. `--filter volume=`, the "volume is in use" wording and the
#     label names are Docker's, and a version that changed them would change
#     these results.
#   * A HAND-NAMED STACK WHOSE CONTAINERS ARE GONE. `-p djb-drill` with nothing
#     running is unreachable by the sweep — teardown.sh declares that limit and
#     this drive does not close it.
set -euo pipefail

cd "$(dirname "$0")/../.."

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_teardown: $*" >&2
    echo "   Nothing was asserted. A driver that could not run its cases has not" >&2
    echo "   cleared them." >&2
    exit 2
}

case "${1:-}" in
"") ;;
--list)
    grep -n '^case_.*() {' "$0" | sed 's/() {.*//; s/^/  /'
    exit 0
    ;;
*)
    echo "!! unknown argument '$1': test_teardown.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

BUSYBOX="busybox:1.37.0"

command -v docker >/dev/null 2>&1 || cannot_look "no docker on PATH — this drive reaps real containers"
docker info >/dev/null 2>&1 || cannot_look "docker is on PATH but not answering; nothing was driven"
[ -f deploy/teardown.sh ] || cannot_look "deploy/teardown.sh is not in this tree — there is nothing to drive"
[ -f deploy/provision.sh ] || cannot_look "deploy/provision.sh is not in this tree — the derivation comes from it"
docker image inspect "$BUSYBOX" >/dev/null 2>&1 \
    || docker pull "$BUSYBOX" >/dev/null 2>&1 \
    || cannot_look "could not obtain $BUSYBOX; the cases have nothing to run"

TREE="$PWD"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-teardown-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
# NORMALISED, because `$TMPDIR` ends in a slash on macOS and `mktemp` keeps it:
# the paths this drive builds would then carry a `//` that `teardown.sh`'s own
# `cd … && pwd` has already collapsed, and every assertion about a path it
# printed would fail on a difference that is not a difference.
WORK="$(cd "$WORK" && pwd)" || cannot_look "could not resolve the scratch directory"

# --- the leash ---------------------------------------------------------------
# Everything the drive creates is remembered by name here and removed at EXIT,
# whatever happened. The drive's own victims are the only things it may destroy:
# it never asks docker for "all" of anything.
CLEAN_PROJECTS=""
CLEAN_VOLUMES=""
CLEAN_CONTAINERS=""

own_project() { CLEAN_PROJECTS="$CLEAN_PROJECTS $1"; }
own_volume() { CLEAN_VOLUMES="$CLEAN_VOLUMES $1"; }
own_container() { CLEAN_CONTAINERS="$CLEAN_CONTAINERS $1"; }

# shellcheck disable=SC2329  # invoked by the EXIT trap below, not by name
cleanup() {
    set +e
    local name ids
    for name in $CLEAN_CONTAINERS; do
        docker rm -f "$name" >/dev/null 2>&1
    done
    for name in $CLEAN_PROJECTS; do
        ids="$(docker ps -aq --filter "label=com.docker.compose.project=$name" 2>/dev/null)"
        if [ -n "$ids" ]; then
            # shellcheck disable=SC2086
            docker rm -f $ids >/dev/null 2>&1
        fi
        ids="$(docker volume ls -q --filter "label=com.docker.compose.project=$name" 2>/dev/null)"
        if [ -n "$ids" ]; then
            # shellcheck disable=SC2086
            docker volume rm $ids >/dev/null 2>&1
        fi
        docker network rm "${name}_default" >/dev/null 2>&1
    done
    for name in $CLEAN_VOLUMES; do
        docker volume rm "$name" >/dev/null 2>&1
    done
    rm -rf "$WORK"
}
trap cleanup EXIT

# --- the assertions (test_ship.sh / test_release.sh helpers, same shapes) -----
DRIVE_OUT=""
DRIVE_EXIT=0
CURRENT=""

reap() {
    # reap <label> <wanted exit> <checkout root> [VAR=value ...]
    local label="$1" want="$2" root="$3"
    shift 3
    CURRENT="$label"
    DRIVE_OUT="${WORK}/$(printf '%s' "$label" | tr -c 'a-zA-Z0-9' '_').log"
    set +e
    ( cd "$root" && env "$@" "$root/deploy/teardown.sh" --all-mine ) >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
    if [ "$DRIVE_EXIT" -eq "$want" ]; then
        echo "  ok       ${label} — exit ${DRIVE_EXIT}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${label} — wanted exit ${want}, got ${DRIVE_EXIT}"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -40
        FAILED=$((FAILED + 1))
    fi
}

says() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  ok       ${CURRENT} — says \"$1\""
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — does not say \"$1\""
        sed 's/^/             | /' "$DRIVE_OUT" | tail -40
        FAILED=$((FAILED + 1))
    fi
}

says_not() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  FAILED   ${CURRENT} — says \"$1\" and must not"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -40
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — never says \"$1\""
        PASSED=$((PASSED + 1))
    fi
}

# The ordering assertion, and it is the point of this drive: line number of
# the first <first> against line number of the first <second>.
says_before() {
    local first="$1" second="$2" a b
    a="$(grep -nF -- "$first" "$DRIVE_OUT" | head -n1 | cut -d: -f1)"
    b="$(grep -nF -- "$second" "$DRIVE_OUT" | head -n1 | cut -d: -f1)"
    if [ -z "$a" ] || [ -z "$b" ]; then
        echo "  FAILED   ${CURRENT} — cannot order \"$first\" against \"$second\": one of them never appeared"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -40
        FAILED=$((FAILED + 1))
        return
    fi
    if [ "$a" -lt "$b" ]; then
        echo "  ok       ${CURRENT} — \"$first\" (line $a) before \"$second\" (line $b)"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   ${CURRENT} — \"$first\" (line $a) is NOT before \"$second\" (line $b)"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -40
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

volume_present() {
    if docker volume inspect "$1" >/dev/null 2>&1; then echo yes; else echo no; fi
}

container_state() {
    docker ps -a --filter "name=^${1}$" --format '{{.State}}' 2>/dev/null | head -n1
}

project_containers() {
    docker ps -aq --filter "label=com.docker.compose.project=$1" 2>/dev/null | grep -c . || true
}

project_volumes() {
    docker volume ls -q --filter "label=com.docker.compose.project=$1" 2>/dev/null | grep -c . || true
}

# --- the scratch checkout ----------------------------------------------------
# A directory that is not a git checkout, so `provision.sh`'s `checkout_root`
# falls back to its parent — which makes the derived project name a function of
# this drive's own mktemp path and of nothing else on the machine.
# It sets CHECKOUT rather than echoing the path, and that is not a style choice:
# assigning from a command substitution runs the function in a SUBSHELL, so the counter it
# increments is thrown away and every case gets checkout1 — which makes two
# "different" checkouts derive the same project name and quietly turns case_d's
# cannot-widen proof into a comparison of a value with itself.
N=0
CHECKOUT=""
make_checkout() {
    N=$((N + 1))
    local root="${WORK}/checkout${N}"
    CHECKOUT="$root"
    mkdir -p "$root/deploy"
    cp "$TREE/deploy/teardown.sh" "$root/deploy/teardown.sh"
    cp "$TREE/deploy/provision.sh" "$root/deploy/provision.sh"
    chmod +x "$root/deploy/teardown.sh" "$root/deploy/provision.sh"
    cat >"$root/deploy/compose.yaml" <<'COMPOSE'
services:
  keeper:
    image: busybox:1.37.0
    command: ["sh", "-c", "while true; do sleep 30; done"]
    volumes:
      - keeper_data:/data
  laptop_only:
    profiles: ["laptop"]
    image: busybox:1.37.0
    command: ["sh", "-c", "while true; do sleep 30; done"]
    volumes:
      - laptop_data:/data
volumes:
  keeper_data:
  laptop_data:
COMPOSE
}

derived_of() {
    "$1/deploy/provision.sh" derived-project-name
}

stack_up() {
    # stack_up <checkout root> <project name>
    own_project "$2"
    docker compose -p "$2" -f "$1/deploy/compose.yaml" --profile laptop up -d >/dev/null 2>&1 \
        || cannot_look "could not bring up the scratch stack $2"
}

plant_labelled_volume() {
    # plant_labelled_volume <volume name> <project label>
    own_volume "$1"
    docker volume create --label "com.docker.compose.project=$2" "$1" >/dev/null 2>&1 \
        || cannot_look "could not plant the volume $1"
}

# =============================================================================
# THE CASES
# =============================================================================

# The ordering property itself. A LIVE stack, whose volumes are in use, reaped
# in one command.
# On the unfixed script this exits 1 having removed nothing at all, because the
# orphan sweep ran first and `docker volume rm` refused every in-use volume.
case_a_a_live_stack_is_fully_reaped() {
    local root derived
    make_checkout; root="$CHECKOUT"
    derived="$(derived_of "$root")"
    stack_up "$root" "$derived"
    echo "COMPOSE_PROJECT_NAME='$derived'" >"$root/deploy/.env"

    holds "case_a — containers up before the reap" 2 "$(project_containers "$derived")"
    holds "case_a — volumes present before the reap" 2 "$(project_volumes "$derived")"

    reap "case_a live stack" 0 "$root"
    says "down --volumes: $derived"
    says "census AFTER:"
    holds "case_a — containers after" 0 "$(project_containers "$derived")"
    holds "case_a — volumes after" 0 "$(project_volumes "$derived")"
    holds "case_a — deploy/.env after" "gone" "$([ -f "$root/deploy/.env" ] && echo present || echo gone)"
}

# THE ORDERING, read off the transcript. The stack is up under an ADOPTED name
# (which is legal and is what a re-deployed box carries), and a volume labelled
# with the DERIVED name is left with no project to own it. Both sweeps therefore
# fire, and the orphan sentence must come after the `down` — because that is the
# only moment at which the sentence is true.
case_b_the_orphan_sweep_runs_after_the_down() {
    local root derived adopted ghost
    make_checkout; root="$CHECKOUT"
    derived="$(derived_of "$root")"
    adopted="djb-adopted-${derived#djb_deploy_}"
    ghost="${derived}_ghost"

    stack_up "$root" "$adopted"
    plant_labelled_volume "$ghost" "$derived"

    reap "case_b ordering" 0 "$root"
    says "down --volumes: $adopted"
    says "no project left to own them"
    says_before "down --volumes: $adopted" "no project left to own them"
    says "removed 1 orphaned volume(s)"
    holds "case_b — the ghost volume after" "no" "$(volume_present "$ghost")"
    holds "case_b — the adopted project after" 0 "$(project_containers "$adopted")"
}

# A VOLUME STILL HELD AFTER THE DOWN. Not `|| true`: named, its holder named,
# the rest of the reap completed anyway, and the script exits non-zero. The
# holder is a container OUTSIDE the project, which is the only way a volume
# survives its own `down --volumes`.
case_c_a_held_volume_is_loud_named_and_non_zero() {
    local root derived held holder
    make_checkout; root="$CHECKOUT"
    derived="$(derived_of "$root")"
    held="${derived}_held"
    holder="djb-drive-holder-${derived#djb_deploy_}"

    stack_up "$root" "$derived"
    echo "COMPOSE_PROJECT_NAME='$derived'" >"$root/deploy/.env"
    plant_labelled_volume "$held" "$derived"
    own_container "$holder"
    docker run -d --name "$holder" -v "${held}:/data" "$BUSYBOX" \
        sh -c 'while true; do sleep 30; done' >/dev/null 2>&1 \
        || cannot_look "could not start the holding container $holder"

    reap "case_c held volume" 1 "$root"
    says "volume NOT removed: $held"
    says "held by"
    says "$holder"
    says "1 volume(s) survived this reap"
    # The rest of the reap happened anyway — the half a bare abort loses.
    says "census AFTER:"
    holds "case_c — the project's own containers after" 0 "$(project_containers "$derived")"
    holds "case_c — deploy/.env after" "gone" "$([ -f "$root/deploy/.env" ] && echo present || echo gone)"
    holds "case_c — the held volume survived" "yes" "$(volume_present "$held")"
    holds "case_c — its holder is still running" "running" "$(container_state "$holder")"
}

# CANNOT WIDEN. Another checkout's stack, and a volume labelled for a project
# neither checkout owns, are both untouched by this checkout's reap.
case_d_a_foreign_checkouts_stack_survives() {
    local mine theirs mine_name theirs_name stray
    make_checkout; mine="$CHECKOUT"
    make_checkout; theirs="$CHECKOUT"
    mine_name="$(derived_of "$mine")"
    theirs_name="$(derived_of "$theirs")"
    stray="djb-drive-stray-${mine_name#djb_deploy_}"

    holds "case_d — the two checkouts derive different names" "different" \
        "$([ "$mine_name" = "$theirs_name" ] && echo same || echo different)"

    stack_up "$mine" "$mine_name"
    stack_up "$theirs" "$theirs_name"
    plant_labelled_volume "$stray" "djb-nobody-owns-this"

    reap "case_d foreign survives" 0 "$mine"
    holds "case_d — my containers after" 0 "$(project_containers "$mine_name")"
    holds "case_d — my volumes after" 0 "$(project_volumes "$mine_name")"
    holds "case_d — their containers after" 2 "$(project_containers "$theirs_name")"
    holds "case_d — their volumes after" 2 "$(project_volumes "$theirs_name")"
    holds "case_d — the unowned stray volume after" "yes" "$(volume_present "$stray")"
}

# NOTHING OF MINE IS REPORTED AS NOTHING, not as a clean sweep, and the census
# AFTER is still printed — a reap that found nothing still says what it looked at.
case_e_nothing_of_mine_is_reported_as_nothing() {
    local root
    make_checkout; root="$CHECKOUT"

    reap "case_e empty machine" 0 "$root"
    says "no compose project on this machine names $root/deploy/compose.yaml"
    says "nothing else to reap."
    says "no $root/deploy/.env to remove"
    says "census AFTER:"
    says_not "no project left to own them"
}

# A CENSUS THAT CANNOT BE READ REFUSES TO JUDGE. Exit 2, and — the half that
# matters — no destructive call was made at all.
case_f_a_docker_that_cannot_answer_exits_2() {
    local root log bin
    make_checkout; root="$CHECKOUT"
    log="$WORK/broken-docker.log"
    bin="$WORK/broken-docker-bin"
    mkdir -p "$bin"
    : >"$log"
    cat >"$bin/docker" <<'STUB'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_TEARDOWN_DOCKER_LOG"
case "$*" in
"compose ls -a --format json")
    echo "this is not json"
    exit 0
    ;;
esac
exit 0
STUB
    chmod +x "$bin/docker"

    CURRENT="case_f broken docker"
    DRIVE_OUT="$WORK/case_f.log"
    set +e
    ( cd "$root" \
        && PATH="$bin:$PATH" DJB_TEARDOWN_DOCKER_LOG="$log" \
            "$root/deploy/teardown.sh" --all-mine ) >"$DRIVE_OUT" 2>&1
    DRIVE_EXIT=$?
    set -e
    holds "case_f — exit status" 2 "$DRIVE_EXIT"
    says "could not read 'docker compose ls'"
    holds "case_f — destructive calls made" 0 "$(grep -c -e 'volume rm' -e ' down ' "$log" || true)"
}

# THE GUARD, PROVEN BEHAVIOURALLY. An exported COMPOSE_PROJECT_NAME and
# an adopted name in deploy/.env are both set to names that own real volumes.
# The sweep must ignore both and act only on the derivation.
case_g_the_sweep_matches_the_derivation_not_the_adopted_name() {
    local root derived exported adopted mine_orphan
    make_checkout; root="$CHECKOUT"
    derived="$(derived_of "$root")"
    exported="djb-exported-${derived#djb_deploy_}"
    adopted="djb-adopted-${derived#djb_deploy_}"
    mine_orphan="${derived}_orphan"

    printf "COMPOSE_PROJECT_NAME='%s'\n" "$adopted" >"$root/deploy/.env"
    plant_labelled_volume "$exported" "$exported"
    plant_labelled_volume "$adopted" "$adopted"
    plant_labelled_volume "$mine_orphan" "$derived"

    reap "case_g derivation only" 0 "$root" "COMPOSE_PROJECT_NAME=$exported"
    says "removed 1 orphaned volume(s)"
    holds "case_g — the derived-name orphan was reaped" "no" "$(volume_present "$mine_orphan")"
    holds "case_g — the EXPORTED name's volume survived" "yes" "$(volume_present "$exported")"
    holds "case_g — the ADOPTED name's volume survived" "yes" "$(volume_present "$adopted")"
}

case_a_a_live_stack_is_fully_reaped
case_b_the_orphan_sweep_runs_after_the_down
case_c_a_held_volume_is_loud_named_and_non_zero
case_d_a_foreign_checkouts_stack_survives
case_e_nothing_of_mine_is_reported_as_nothing
case_f_a_docker_that_cannot_answer_exits_2
case_g_the_sweep_matches_the_derivation_not_the_adopted_name

echo ""
echo "test_teardown: $PASSED passed, $FAILED failed"
[ "$FAILED" -eq 0 ] || exit 1
exit 0
