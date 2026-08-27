#!/usr/bin/env bash
# The drive for `DJB_DEPLOY_NAMESPACE` — the ONE slug every AWS deploy
# coordinate this repository composes is composed from.
#
#   ./deploy/tests/test_deploy_namespace.sh          run every case
#   ./deploy/tests/test_deploy_namespace.sh --list   name them and stop
#
# WHY IT EXISTS. Until this variable, `deploy/` spelled one account's real
# coordinates in fifteen files: a Secrets Manager prefix, two S3 buckets, two
# IAM roles, three EC2 tags, the box's deployment directory and an alert bundle
# name. Two things are wrong with a spelled coordinate and only the second one
# is obvious. The obvious one is that a template published to a stranger ships
# somebody else's account layout. The sharp one is that a coordinate nobody
# passes is a coordinate nobody can get WRONG LOUDLY: a clone that changed one
# of the fifteen and missed the other fourteen would provision half its
# resources under its own name and half under the template author's, and every
# one of those calls succeeds.
#
# So the coordinates are DERIVED, and the derivation REFUSES rather than
# defaults — `deploy/dns.sh:33-34`'s grammar verbatim, for its reason: a guessed
# namespace is not an error, it is a correct-looking write into somebody else's
# resources.
#
# WHAT IS ASSERTED, in two directions:
#
#   1. REFUSE-UNSET. Every script that composes a coordinate FOR EXECUTION
#      exits 2 with the variable named when it is unset, and does so BEFORE it
#      calls anything. No fallback, anywhere, to any value.
#   2. IDENTITY OF COMPOSITION. Each coordinate is the namespace verbatim plus
#      the suffix its own script owns — `<ns>/<env>/env`, `<ns>-<env>-backups`,
#      `<ns>-<env>-media`, `<ns>-<env>-box`, `<ns>-<env>-backup-retention`,
#      `<ns>-<env>` and `<ns>` — so an environment whose env file carries the
#      namespace it has always used addresses exactly the resources it has
#      always addressed. Every case drives TWO different namespaces, because one
#      value cannot tell a derivation from a coincidence.
#
# NOTHING HERE SPENDS MONEY OR TOUCHES AN ACCOUNT. The observations are the
# refusal messages and the two SUMMARY blocks `provision.sh infra` and
# `teardown.sh <env>` print BEFORE their `--confirm` refusal, plus
# `backup-policy --check`, which is read-only by name. `aws` is a stub that
# answers four read-only queries and REFUSES everything else with exit 99, so a
# case that reached a mutating call fails loudly rather than passing quietly.
#
# WHAT IT DOES NOT COVER, declared rather than discovered:
#
#   * A REAL ACCOUNT. Whether the composed strings name resources that exist is
#     the account's business and no drive's. What is proven is that the strings
#     are composed from the variable and from nothing else.
#   * `ship.sh`'s half. Its landing directory is the same variable and it is
#     driven where the rest of ship.sh is: `deploy/tests/test_ship.sh`, three
#     cases named for the namespace.
#   * THE RUNBOOK. `docs/runbooks/deploy.md` types these commands by hand and
#     no drive reads prose. The acceptance grep over `deploy/` and
#     `docs/runbooks/` is what holds the runbook to the variable form.
#   * A FUTURE COORDINATE. This pins the ones that exist today. A sixteenth
#     coordinate added later is invisible here until a case names it.
#   * THE LAPTOP BRANCHES. `teardown.sh local` and `provision.sh up` compose no
#     AWS coordinate and are deliberately NOT held to the variable — driving
#     that here would mean running `docker compose down` from a drive, which is
#     a mutation of the machine's stacks for the sake of an assertion. What
#     keeps it true is structural: the refusal sits inside the AWS branch, after
#     the laptop branch has already exited.
#   * THE ACCEPTANCE GREP. That the tree spells no coordinate ANYWHERE cannot be
#     a case in the tree: a case asserting the absence of a literal has to
#     contain the literal. It is the verifier's grep, re-run by hand.
set -euo pipefail

cd "$(dirname "$0")/../.."

PASSED=0
FAILED=0

cannot_look() {
    echo "!! test_deploy_namespace: $*" >&2
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
    echo "!! unknown argument '$1': test_deploy_namespace.sh takes nothing or --list" >&2
    exit 2
    ;;
esac

[ -f deploy/provision.sh ] || cannot_look "deploy/provision.sh is not in this tree"
[ -f deploy/teardown.sh ] || cannot_look "deploy/teardown.sh is not in this tree"
[ -f deploy/observability/alerts/apply.py ] || cannot_look "deploy/observability/alerts/apply.py is not in this tree"
command -v python3 >/dev/null 2>&1 || cannot_look "no python3 on PATH — apply.py is a python file"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/djb-namespace-drive.XXXXXX")" || cannot_look "could not make a scratch directory"
trap 'rm -rf "$WORK"' EXIT

PROVISION="$PWD/deploy/provision.sh"
TEARDOWN="$PWD/deploy/teardown.sh"
APPLY="$PWD/deploy/observability/alerts/apply.py"

# THE TWO FIXTURE NAMESPACES, AND WHY NEITHER IS A REAL ONE. A fixture carrying
# the deployment's actual namespace could not tell a derivation from a hardcode:
# every assertion below would pass just as well against a script that ignored
# the variable and spelled the value. Do not "simplify" either of these to a
# real namespace — that removes the only thing these cases prove.
NS_A="acmedrive"
NS_B="zebradrive"
ENV_A="staging"
ENV_B="prod"

# --- the stub AWS CLI ---------------------------------------------------------
# Answers the read-only queries the composition cases reach and refuses
# everything else. Exit 99 rather than 1, so a mutating call is distinguishable
# in the log from a query that legitimately found nothing.
BIN="${WORK}/bin"
mkdir -p "$BIN"
cat >"$BIN/aws" <<'AWSSTUB'
#!/usr/bin/env bash
argv="$*"
case "$argv" in
*"sts get-caller-identity"*) echo "000000000000" ;;
*"iam list-role-policies"*"length(PolicyNames)"*) echo "1" ;;
*"iam list-role-policies"*"PolicyNames[0]"*) echo "the-one-inline-policy" ;;
*"s3api get-bucket-versioning"*) echo '{"Status":"Enabled"}' ;;
*"s3api get-bucket-policy"*)
    echo "An error occurred (NoSuchBucketPolicy) when calling GetBucketPolicy" >&2
    exit 1
    ;;
*"iam get-role-policy"*) echo '{"Statement":[]}' ;;
*)
    echo "stub aws: REFUSING an unexpected call: $argv" >&2
    exit 99
    ;;
esac
exit 0
AWSSTUB
chmod +x "$BIN/aws"

# --- the assertions (test_ship.sh's helpers, same shapes) ---------------------
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

says_not() {
    if grep -qF -- "$1" "$DRIVE_OUT"; then
        echo "  FAILED   ${CURRENT} — says \"$1\" and must not"
        sed 's/^/             | /' "$DRIVE_OUT" | tail -30
        FAILED=$((FAILED + 1))
    else
        echo "  ok       ${CURRENT} — does not say \"$1\""
        PASSED=$((PASSED + 1))
    fi
}

# Run a deploy script with the stub aws first on PATH and the namespace set.
with_ns() {
    local ns="$1"
    shift
    env PATH="${BIN}:$PATH" DJB_DEPLOY_NAMESPACE="$ns" "$@"
}

# The same, with the variable REMOVED rather than emptied: unset is what an
# operator who never set it actually has. `-u` comes BEFORE the PATH assignment
# because `env` stops reading options at the first non-option argument, and an
# assignment is one — with the order reversed `-u` becomes the command name.
without_ns() {
    env -u DJB_DEPLOY_NAMESPACE PATH="${BIN}:$PATH" "$@"
}

# =============================================================================
# provision.sh infra — the summary that names every coordinate it would create
# =============================================================================

case_provision_infra_refuses_an_unset_namespace() {
    drive "infra, no namespace" 2 -- without_ns "$PROVISION" infra "$ENV_A"
    says "DJB_DEPLOY_NAMESPACE"
    # The refusal is BEFORE the summary, so not one coordinate is printed and
    # not one aws call is made.
    says_not "about to CREATE billable resources"
}

case_provision_infra_composes_every_coordinate_from_the_namespace() {
    # `infra` without `--confirm` prints its whole cost summary and then
    # refuses. That summary is the free, non-mutating window onto every
    # coordinate the subcommand would create.
    drive "infra summary under namespace A" 2 -- with_ns "$NS_A" "$PROVISION" infra "$ENV_A"
    says "s3://${NS_A}-${ENV_A}-media"
    says "s3://${NS_A}-${ENV_A}-backups"
    says "${NS_A}/${ENV_A}/env"
    says "refusing without --confirm"

    drive "infra summary under namespace B" 2 -- with_ns "$NS_B" "$PROVISION" infra "$ENV_B"
    says "s3://${NS_B}-${ENV_B}-media"
    says "s3://${NS_B}-${ENV_B}-backups"
    says "${NS_B}/${ENV_B}/env"
    # THE NEGATIVE THAT MAKES THE POSITIVE MEAN SOMETHING: nothing of the other
    # namespace leaks into this run.
    says_not "$NS_A"
}

# =============================================================================
# provision.sh backup-policy — the bucket and the two roles
# =============================================================================

case_backup_policy_refuses_an_unset_namespace() {
    drive "backup-policy, no namespace" 2 -- without_ns "$PROVISION" backup-policy "$ENV_A"
    says "DJB_DEPLOY_NAMESPACE"
    says_not "READ-ONLY"
}

case_backup_policy_composes_the_bucket_and_the_role() {
    drive "backup-policy --check under namespace A" 0 \
        -- with_ns "$NS_A" "$PROVISION" backup-policy "$ENV_A" --check
    says "bucket ${NS_A}-${ENV_A}-backups"
    says "role ${NS_A}-${ENV_A}-box"
    says "nothing was changed"

    drive "backup-policy --check under namespace B" 0 \
        -- with_ns "$NS_B" "$PROVISION" backup-policy "$ENV_B" --check
    says "bucket ${NS_B}-${ENV_B}-backups"
    says "role ${NS_B}-${ENV_B}-box"
    says_not "$NS_A"
}

# =============================================================================
# teardown.sh — the reverse list, which must name the same strings
# =============================================================================

case_teardown_refuses_an_unset_namespace() {
    drive "teardown, no namespace" 2 -- without_ns "$TEARDOWN" "$ENV_A"
    says "DJB_DEPLOY_NAMESPACE"
    says_not "about to DESTROY"
}

case_teardown_composes_every_coordinate_from_the_namespace() {
    # Without `--confirm` it prints what it would destroy and refuses. The list
    # of what to delete has to be the list of what was created — that is
    # teardown.sh's own header — so these strings are provision's, asserted from
    # the other end.
    drive "teardown summary under namespace A" 2 -- with_ns "$NS_A" "$TEARDOWN" "$ENV_A"
    says "about to DESTROY ${NS_A}-${ENV_A}"
    says "s3://${NS_A}-${ENV_A}-media"
    says "s3://${NS_A}-${ENV_A}-backups"
    says "${NS_A}/${ENV_A}/env"
    says "refusing without --confirm"

    drive "teardown summary under namespace B" 2 -- with_ns "$NS_B" "$TEARDOWN" "$ENV_B"
    says "about to DESTROY ${NS_B}-${ENV_B}"
    says_not "$NS_A"
}

# =============================================================================
# the alert bundle's name
# =============================================================================

case_alerts_apply_refuses_an_unset_namespace() {
    drive "apply.py, no namespace" 2 -- without_ns python3 "$APPLY" --dry-run
    says "DJB_DEPLOY_NAMESPACE"
}

case_alerts_apply_composes_the_bundle_name_and_the_slot() {
    # `--dry-run` prints the census and stops before it dials anything, which is
    # where the resolved bundle name and slot are read from.
    drive "apply.py --dry-run under namespace A" 0 -- with_ns "$NS_A" python3 "$APPLY" --dry-run
    says "${NS_A}-alerts"
    says "${NS_A}/<env>/env"

    drive "apply.py --dry-run under namespace B" 0 -- with_ns "$NS_B" python3 "$APPLY" --dry-run
    says "${NS_B}-alerts"
    says_not "$NS_A"
}

case_provision_infra_refuses_an_unset_namespace
case_provision_infra_composes_every_coordinate_from_the_namespace
case_backup_policy_refuses_an_unset_namespace
case_backup_policy_composes_the_bucket_and_the_role
case_teardown_refuses_an_unset_namespace
case_teardown_composes_every_coordinate_from_the_namespace
case_alerts_apply_refuses_an_unset_namespace
case_alerts_apply_composes_the_bundle_name_and_the_slot

echo "test_deploy_namespace: ${PASSED} passed · ${FAILED} failed"
if [ "$FAILED" -gt 0 ]; then
    echo "!! a property did not hold. The one that matters most is REFUSE-UNSET: a" >&2
    echo "   deploy script that falls back to a guessed namespace writes into" >&2
    echo "   somebody else's account and every call succeeds." >&2
    exit 1
fi
exit 0
