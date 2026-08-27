#!/usr/bin/env bash
# The drive for two `deploy/provision.sh` properties — the project name it
# ANSWERS WITH, and what `up` does to the app pair on a re-deploy.
#
#   ./deploy/tests/test_provision_up.sh          run every case
#   ./deploy/tests/test_provision_up.sh --list   name them and stop
#
# WHY IT IS A SEPARATE FILE AND WHY IT IS SMALL. `test_release.sh` drives
# `release.sh`; this drives `provision.sh`, and a drive that claims to cover a
# 1500-line script it only touches two functions of is a coverage claim nobody
# should believe. So the scope is stated here rather than implied: these are
# two behaviours, and nothing else in `provision.sh` is driven by anything yet.
# That gap is real and is declared, not hidden.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * EVERY OTHER SUBCOMMAND. `env-file`, `secrets-put`, `secrets-fetch`,
#     `infra`, `backup-policy` and `image-tag` have no drive here or anywhere.
#     `infra` in particular spends money and is guarded by `--confirm` and by
#     nothing else.
#   * `up`'s ADOPTION AND REFUSAL LADDER. The `count > 1` refusal, the
#     deliberate-second-stack refusal and the name migration are exercised only
#     as far as one case needs them; their own cases are owed.
#   * WHAT COMPOSE DOES. The stub `docker` records invocations and answers; it
#     starts nothing. What is proven here is the ARGUMENTS — which services the
#     up names and which flag it names them with — because that is where both
#     defects lived.
#   * THE BOX. That a re-deploy's window is actually zero is measured on the box
#     with a clock, not here; this proves only that no command in the runbook's
#     step 34 asks for the recreate.
#
# INVISIBLE TO `check.sh` — the same gap `test_release.sh` and `test_ship.sh`
# sit in. Nobody's moment invokes this file; it is run by hand and its counts
# are read off the run, until the three of them are wired into the selftest
# leg.
set -euo pipefail

cd "$(dirname "$0")/../.."

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_provision_up: $*" >&2
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
    echo "!! unknown argument '$1': test_provision_up.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

command -v bash >/dev/null 2>&1 || cannot_look "no bash on PATH"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — provision.sh's env-file rewrites are python"
[ -f deploy/provision.sh ] || cannot_look "deploy/provision.sh is not in this tree — there is nothing to drive"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-provision-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
# NORMALISED, and it is not cosmetic. A `TMPDIR` with a trailing slash makes
# `mktemp -d` hand back `…/T//djb-…`, while `provision.sh` derives its own
# `HERE` through `cd … && pwd` and gets `…/T/djb-…`. `running_projects_here()`
# compares those two spellings STRING-WISE — it is asking Docker's own record
# which config file brought a project up — so an un-normalised path makes every
# case here silently take the "no stack is running" branch, and the drive would
# report green about a code path it never entered.
WORK="$(cd "$WORK" && pwd)" || cannot_look "could not resolve the scratch directory"
trap 'rm -rf "$WORK"' EXIT

SOURCE="$PWD/deploy/provision.sh"

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

# --- the scratch deployment ---------------------------------------------------
CASE_DIR=""
DEPLOY=""
DOCKER_LOG=""
N=0
fresh_deploy() {
    N=$((N + 1))
    CASE_DIR="${WORK}/case${N}"
    DEPLOY="${CASE_DIR}/deploy"
    DOCKER_LOG="${CASE_DIR}/docker.log"
    mkdir -p "$DEPLOY" "$CASE_DIR/bin"
    : >"$DOCKER_LOG"

    cp "$SOURCE" "$DEPLOY/provision.sh"
    chmod +x "$DEPLOY/provision.sh"
    # `image_tag()` reads git where git exists and the archive's TREE marker
    # where it does not. The scratch deployment has no repository, so it gets
    # the marker — which is also the shape a real BOX is in (`git archive`
    # ships no `.git`), so this is the honest fixture rather than a convenient
    # one.
    printf 'tree-stubbed0000\n' >"${CASE_DIR}/TREE"

    cat >"$DEPLOY/compose.yaml" <<'YAML'
services:
  db:
    image: postgres:18.6
  caddy:
    image: caddy:2.10.2
  web:
    image: djb-web:tree-stubbed0000
  worker:
    image: djb-worker:tree-stubbed0000
YAML

    cat >"$DEPLOY/.env" <<'ENV'
COMPOSE_PROJECT_NAME='djb-deploy'
DJB_IMAGE_TAG='tree-stubbed0000'
SITE_ADDRESS='drive.invalid'
ENV

    # THE STUB DOCKER. It records every invocation in order and answers the
    # three questions `cmd_up` asks: which projects are running, whether the
    # tree's image exists, and what the services of this compose file are.
    cat >"$CASE_DIR/bin/docker" <<'DOCKER'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"
case "$*" in
*"compose ls --format json"*)
    printf '%s' "${DJB_DRIVE_COMPOSE_LS:-[]}"
    ;;
*"image inspect"*) exit 0 ;;
*"config --services"*)
    # Compose's own answer, and the ORDER is compose's: the app pair sits in the
    # middle rather than at the end, so a filter that works by dropping the last
    # two lines would fail here.
    printf '%s\n' db web caddy worker
    ;;
esac
exit 0
DOCKER
    chmod +x "$CASE_DIR/bin/docker"
}

# `env -u COMPOSE_PROJECT_NAME` for `test_release.sh`'s reason: one case exports
# that name on purpose and an operator's own shell must never answer for it.
provision() {
    local envs=()
    while [ "$#" -gt 0 ]; do
        case "$1" in
        *=*) envs+=("$1"); shift ;;
        *) break ;;
        esac
    done
    env -u COMPOSE_PROJECT_NAME \
        PATH="${CASE_DIR}/bin:$PATH" \
        DJB_DRIVE_DOCKER_LOG="$DOCKER_LOG" \
        ${envs[@]+"${envs[@]}"} "$@"
}

docker_saw() { grep -cF -- "$1" "$DOCKER_LOG" || true; }

# One JSON array saying "a stack named djb-deploy, brought up from THIS scratch
# checkout's compose file, is running" — the adopted-name shape.
running_here() {
    printf '[{"Name":"djb-deploy","Status":"running(4)","ConfigFiles":"%s"}]' \
        "$DEPLOY/compose.yaml"
}

# =============================================================================
# `project-name` answers the name the stack ACTUALLY carries
# =============================================================================
# The defect: `provision.sh project-name` answered the DERIVATION and nothing
# else, while `provision.sh up` had already ADOPTED the running stack's name
# into `deploy/.env` on every box whose stack predates the derivation. So the
# runbook's two lines that ask for a name — step 9's `--filter` and step 12's
# `--network` — named a project that does not exist on an adopted box:
# `djb_deploy_<8 hex>` against a live `djb-deploy`, and step 12's psql container
# joined a network with nothing on it.

case_project_name_answers_the_adopted_name() {
    fresh_deploy
    drive "project-name, adopted" 0 -- provision "$DEPLOY/provision.sh" project-name
    holds "the adopted name in deploy/.env is the answer" "djb-deploy" \
        "$(tr -d '\n' <"$DRIVE_OUT")"
}

case_project_name_falls_back_to_the_derivation() {
    fresh_deploy
    sed -i.bak "/^COMPOSE_PROJECT_NAME=/d" "$DEPLOY/.env"
    drive "project-name, derived" 0 -- provision "$DEPLOY/provision.sh" project-name
    holds "with no name in the env file the derivation answers" "1" \
        "$(grep -c '^djb_deploy_[0-9a-f]\{8\}$' "$DRIVE_OUT" || true)"
}

case_an_exported_name_outranks_the_env_file() {
    fresh_deploy
    drive "project-name, exported" 0 -- provision COMPOSE_PROJECT_NAME=djb-drill \
        "$DEPLOY/provision.sh" project-name
    holds "the one escape still outranks everything" "djb-drill" \
        "$(tr -d '\n' <"$DRIVE_OUT")"
}

# THE OTHER HALF, and it is load-bearing rather than tidy: `teardown.sh` decides
# whether a project is THIS CHECKOUT'S by comparing the resolved name against
# the derived one. Fold the adoption into the only function that produces the
# derivation and that comparison compares a value with itself and always agrees
# — a destructive command whose ownership check has quietly stopped asking
# anything. So the derivation keeps a name of its own.
case_the_derivation_is_still_reachable_under_its_own_name() {
    fresh_deploy
    drive "derived-project-name, adopted stack" 0 -- provision \
        "$DEPLOY/provision.sh" derived-project-name
    holds "the derivation answers even where a name was adopted" "1" \
        "$(grep -c '^djb_deploy_[0-9a-f]\{8\}$' "$DRIVE_OUT" || true)"
    holds "and it is NOT the adopted name" "0" \
        "$(grep -cF 'djb-deploy' "$DRIVE_OUT" || true)"
}

case_the_two_names_disagree_where_a_name_was_adopted() {
    fresh_deploy
    local resolved derived
    # `|| true` on both: a subcommand this tree does not have exits 2 through
    # `usage`, and under `set -e` that would end the DRIVE rather than fail the
    # case — a driver that stops early has not cleared the cases it never ran.
    resolved="$(provision "$DEPLOY/provision.sh" project-name 2>/dev/null | tr -d '\n' || true)"
    derived="$(provision "$DEPLOY/provision.sh" derived-project-name 2>/dev/null | tr -d '\n' || true)"
    # BOTH halves, because "they differ" alone passes when one of them is a page
    # of usage text: the derived answer has to still BE the derivation.
    holds "the derived answer is derivation-shaped" "1" \
        "$(printf '%s' "$derived" | grep -c '^djb_deploy_[0-9a-f]\{8\}$' || true)"
    if [ -n "$derived" ] && [ "$resolved" != "$derived" ]; then
        echo "  ok       the resolved and derived names differ — ${resolved} vs ${derived}"
        PASSED=$((PASSED + 1))
    else
        echo "  FAILED   the resolved and derived names are the same string (${resolved})"
        echo "             — teardown.sh's ownership comparison would compare a value"
        echo "               with itself and always agree."
        FAILED=$((FAILED + 1))
    fi
}

# =============================================================================
# `up` leaves the app pair alone, so only release act 6 recreates it
# =============================================================================
# The defect, MEASURED: runbook step 34 recreated `web` and `worker` on the new
# image one step before Part 5 could migrate, so every re-deploy served new code
# against the old schema for the length of the gap — three `reconcile_search_
# index` failures on a missing column in a four-minute window on staging,
# self-healed by Temporal's retry, which is the belt and not the fix.
# `release.sh`'s header claimed "within a release there is no way to open it",
# which was true of the release and false of the runbook.

case_up_does_not_recreate_the_app_pair() {
    fresh_deploy
    drive "up on a running stack" 0 -- provision \
        DJB_DRIVE_COMPOSE_LS="$(running_here)" "$DEPLOY/provision.sh" up
    holds "the app pair is brought up with --no-recreate and nothing else" "1" \
        "$(docker_saw 'up -d --no-recreate web worker')"
    # THE ABSENT CASE. The bulk up must not name the pair at all — a
    # `--no-recreate` on the pair beside a plain `up -d` that includes them is
    # the defect with a decoration on it.
    local bulk
    bulk="$(grep -F 'up -d' "$DOCKER_LOG" | grep -vF -- '--no-recreate' || true)"
    holds "the stack-wide up names neither web nor worker" "0" \
        "$(printf '%s\n' "$bulk" | grep -cE '(^| )(web|worker)( |$)' || true)"
    holds "the stack-wide up still reconciles everything else" "1" \
        "$(printf '%s\n' "$bulk" | grep -cE '(^| )db( |$)' || true)"
}

case_up_still_creates_the_app_pair_on_a_box_that_never_deployed() {
    fresh_deploy
    # No stack running: the first deploy. `--no-recreate` CREATES what is absent
    # — that is the whole reason it is the flag rather than "skip the pair" —
    # so a first deploy still ends with a web and a worker.
    drive "up on an empty box" 0 -- provision "$DEPLOY/provision.sh" up
    says "no stack from this checkout is running"
    holds "the app pair is created" "1" \
        "$(docker_saw 'up -d --no-recreate web worker')"
}

case_up_says_which_of_the_three_things_happened() {
    fresh_deploy
    drive "up announces the adoption" 0 -- provision \
        DJB_DRIVE_COMPOSE_LS="$(running_here)" "$DEPLOY/provision.sh" up
    says "already running, and the env file agrees"
}

case_project_name_answers_the_adopted_name
case_project_name_falls_back_to_the_derivation
case_an_exported_name_outranks_the_env_file
case_the_derivation_is_still_reachable_under_its_own_name
case_the_two_names_disagree_where_a_name_was_adopted
case_up_does_not_recreate_the_app_pair
case_up_still_creates_the_app_pair_on_a_box_that_never_deployed
case_up_says_which_of_the_three_things_happened

echo "test_provision_up: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. The two here are the ones a wrong answer" >&2
    echo "   makes SILENT: a runbook command joining a network that does not" >&2
    echo "   exist, and a re-deploy serving new code on the old schema for as" >&2
    echo "   long as the migrate takes." >&2
    exit 1
fi
exit 0
