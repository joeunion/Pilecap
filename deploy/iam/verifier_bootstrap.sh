#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../../scripts/bash_only.sh" || exit 2
# THE OWNER'S ONCE-ONLY HAND. Everything the verifier boxes need that nobody but
# a human with the account's own credential can make: one IAM identity, its
# policy, the boxes' instance role, and the egress-only security group they
# launch into.
#
# THE THREE COORDINATES COME FROM YOUR SHELL AND ARE NOT IN THIS TREE. They have
# no defaults (the refusals below say why), which is what makes the lines here
# the command rather than a sketch of it: typing the script's name with nothing
# in front of it exits 2 before it does anything. Substitute your own; the
# placeholders are placeholders on purpose, and a real account number or region
# committed into this file is the per-deployment fact this whole script is shaped
# to keep out of the tree.
#
#   print the whole plan, create NOTHING, exit 2:
#
#     DJB_DEPLOY_NAMESPACE=<ns> DJB_VERIFIER_ACCOUNT=<12-digit account> DJB_VERIFIER_REGION=<region> \
#       ./deploy/iam/verifier_bootstrap.sh
#
#   do it:
#
#     DJB_DEPLOY_NAMESPACE=<ns> DJB_VERIFIER_ACCOUNT=<12-digit account> DJB_VERIFIER_REGION=<region> \
#       ./deploy/iam/verifier_bootstrap.sh --confirm
#
#   do it, and mint a new access key even though one already exists:
#
#     DJB_DEPLOY_NAMESPACE=<ns> DJB_VERIFIER_ACCOUNT=<12-digit account> DJB_VERIFIER_REGION=<region> \
#       ./deploy/iam/verifier_bootstrap.sh --confirm --rotate-key
#
# Then, once, by hand:
#
#   aws configure --profile <ns>-verifier   paste the key id and the secret
#                                           printed on the LAST line above;
#                                           the same region; output json
#
# and nothing else about these boxes ever needs the owner again: bringing one
# up, taking one down, baking an image and the census are all the wrapper's, and
# the teardown is the image's own timer.
#
# EVERY NAME IT MINTS IS DERIVED FROM THE DEPLOYMENT NAMESPACE, AND THAT IS THE
# WHOLE REASON THIS FILE HAS NO PRODUCT NAME IN IT. The machinery is system
# layer and ships in the template; the identities, the group and the image are
# per deployment. More than one product already shares one AWS account, so a
# fixed `thing-verifier-ops` would mean the second product to run this script
# finds the first one's identity and either fails or, worse, quietly adopts it —
# and a census in one product would list the other's boxes and offer to
# terminate them. So: `DJB_DEPLOY_NAMESPACE` is required, there is no default
# (a guessed namespace is a write into somebody else's resources — the
# provisioning script's own sentence, one door over), every resource carries
# `djb:namespace=<namespace>`, and every Allow in the policy is conditioned on
# that tag. This script is idempotent PER NAMESPACE: a second product in the
# same account creates its own six things and never touches the first's.
#
# WHY IT REFUSES BY DEFAULT. Reading this file must never be one arrow key away
# from creating an IAM identity — the same sentence the provisioning script
# carries one door over, for a heavier reason: a credential created by accident
# is a credential nobody is watching. So the bare run PRINTS THE WHOLE PLAN,
# including every statement of the policy it would attach, and exits 2 having
# called nothing at all. The plan is the thing to read; `--confirm` is the thing
# to type afterwards.
#
# WHY IT IS IDEMPOTENT. The five resources are looked up by name before
# anything is created; a second run finds each one, says `exists`, and creates
# nothing. That matters more than it sounds: the failure mode of a
# non-idempotent credential bootstrap is a drawer full of access keys nobody can
# attribute, and the second-run path is the one a person actually takes (a
# half-finished first run, a re-read of the plan, a new laptop).
#
# THE ACCESS KEY IS PRINTED ONCE, ON THE LAST LINE, AND STORED NOWHERE. It is
# never passed as an argument to anything — a secret in an argv lands in `ps`
# and in a shell history — and it is never written to a file. Lose it and
# re-run with `--rotate-key`.
#
# WHAT IT CREATES, and nothing else (<ns> is the deployment namespace):
#
#   policy            <ns>-verifier-ops   the document beside this file
#   user              <ns>-verifier-ops   with that policy attached
#   role              <ns>-verifier-box   trust: the EC2 service alone;
#                                         policy: AmazonSSMManagedInstanceCore
#                                         and NOTHING ELSE. Its registry grant
#                                         is PRINTED for a human, never
#                                         attached here — step 3b says why
#   instance profile  <ns>-verifier-box   carrying that role
#   security group    <ns>-verifier       in the default VPC, egress-only — a
#                                         new EC2 group has no ingress rule and
#                                         this script never adds one
#   access key        one, for the user, printed once
#
# WHAT IT DELIBERATELY DOES NOT DO. There is no `--delete`. Tearing down a
# credential is a decision, not a convenience, and the five names above are the
# whole list a person needs to remove them by hand in the console or with five
# `aws iam delete-*` calls. A reversal that is one flag away from a script that
# also creates things is a reversal somebody runs at the wrong moment.
#
# WHY THE BOX ROLE IS NEW AND NOT THE ENVIRONMENTS' ONE. The environment boxes'
# instance profile reads that environment's secrets prefix and writes its backup
# bucket. A verifier box is a throwaway machine that runs whatever tree it was
# handed; handing it that role would put a real environment's credentials one
# `curl` away from an unreviewed branch. Its role can register with Session
# Manager and do nothing else at all.
#
# THE INTERPRETER IT ASSUMES, said here because it is an assumption and not an
# accident: `<this checkout>/.venv/bin/python`, resolved from this file's own
# location, for every PYTHON FILE THIS REPOSITORY SHIPS that it runs — which is
# `deploy/policy_summary.py`, the reader that turns the policy document into the
# plan's statement-by-statement summary. NEVER `python3` off PATH: that is some
# other environment's Python, and on a machine whose system one is a 3.9 a file
# this repository writes at 3.12 fails in a way that reads as a finding about
# the file. The gate paid for exactly that on a verifier box. The `python3 -c`
# programs further down are INLINE and stay: a `json.load` and a dict
# comparison are stdlib on any Python 3, and their absence is refused by the
# same guard.
#
# SO THIS SCRIPT IS RUN FROM A PROVISIONED CHECKOUT, and says so rather than
# discovering it: `./scripts/setup.sh` (or `uv sync`) before the one hand below.
# An unprovisioned checkout is exit 2 with that sentence, not a run under
# whatever interpreter happened to be first on PATH.
#
# Exit: 0 everything exists (created or found) · 1 an AWS call failed ·
# 2 refused — any of the three coordinates unset, no --confirm, a credential
# that resolves to another account, a piped stdout, an unknown flag, no `aws` on
# PATH, no interpreter in this checkout's venv. Nothing is created on any
# exit-2 path.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
set +x # never; this script handles a secret access key

# `die`, `say` and the pipe guard are deploy/lib.sh's and the seam's.
DEPLOY_NAME=verifier-bootstrap
# shellcheck source=deploy/lib.sh
. "$HERE/../lib.sh" || exit 2

#: The deployment namespace — the slug every identity, group, image and tag
#: below is composed from. REQUIRED, with no default, exactly as
#: `deploy/provision.sh`'s `require_namespace` requires it and for the same
#: reason: a guessed namespace is a write into somebody else's resources, and
#: more than one product shares this account.
NAMESPACE="${DJB_DEPLOY_NAMESPACE:-}"
[ -n "$NAMESPACE" ] || die "DJB_DEPLOY_NAMESPACE is required — this deployment's namespace,
   the slug every identity, security group, image and tag here is composed from.
   There is no default: more than one product shares this AWS account, and a
   guessed namespace is a write into somebody else's resources. It is a slot in
   this environment's env file (deploy/env.staging.example)."

#: The account these resources belong in — the same account the environment
#: boxes live in, so a verifier box shares their bill and their quota. REQUIRED,
#: with no default. An account number is a per-deployment FACT, and a default
#: one shipped inside system machinery is a fact every clone of this template
#: inherits without being asked. It is also the guard: the caller's credential
#: is compared against this before anything is created, and a wrong account is
#: somebody else's IAM.
DJB_VERIFIER_ACCOUNT="${DJB_VERIFIER_ACCOUNT:-}"
[ -n "$DJB_VERIFIER_ACCOUNT" ] || die "DJB_VERIFIER_ACCOUNT is required — the 12-digit account
   these resources belong in, and the account this script refuses to run against
   any other. There is no default: an account number is a per-deployment fact,
   and one shipped in the tree is a fact every clone inherits silently. It lives
   in the shell you run this from, beside DJB_DEPLOY_NAMESPACE."

#: The region every call carries explicitly. REQUIRED, with no default, for the
#: same reason and one more: the operator's own configured default region is
#: very often NOT the one the environment boxes live in, and a script that
#: inherits it creates a security group in a region the launch cannot find.
DJB_VERIFIER_REGION="${DJB_VERIFIER_REGION:-}"
[ -n "$DJB_VERIFIER_REGION" ] || die "DJB_VERIFIER_REGION is required — the region the
   environment boxes live in. There is no default: a region guessed here is a
   security group and an identity created somewhere the launch will never look,
   and your own configured default is very often a different one. It lives in
   the shell you run this from, beside DJB_DEPLOY_NAMESPACE."

#: The AWS CLI profile this script runs as — the OWNER's, not the verifier's.
#: The verifier profile is what this script's last line lets the owner create.
DJB_VERIFIER_ADMIN_PROFILE="${DJB_VERIFIER_ADMIN_PROFILE:-default}"

POLICY_NAME="${NAMESPACE}-verifier-ops"
USER_NAME="${NAMESPACE}-verifier-ops"
ROLE_NAME="${NAMESPACE}-verifier-box"
PROFILE_NAME="${NAMESPACE}-verifier-box"
GROUP_NAME="${NAMESPACE}-verifier"
CLI_PROFILE="${NAMESPACE}-verifier"
SSM_MANAGED_POLICY="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
#: EC2's own service-linked role for Spot. NOT namespaced and not ours: there is
#: exactly one per account, AWS owns its name, and every Spot request in the
#: account needs it. This script CHECKS it and never creates it — see step 0.
SPOT_SLR_NAME="AWSServiceRoleForEC2Spot"
SPOT_SLR_SERVICE="spot.amazonaws.com"

POLICY_DOC="${HERE}/verifier-ops-policy.json"
TRUST_DOC="${HERE}/verifier-box-trust.json"
SUMMARY="${HERE}/../policy_summary.py"

# --- the pipe refusal --------------------------------------------------------
# The exit status is the verdict and a filter replaces it — the seam's
# `refuse_if_piped`. This script also prints an access key on its last line.
refuse_if_piped "$DEPLOY_NAME" "This script prints an access key on its last line; a filter takes it too."

CONFIRM=""
ROTATE=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --confirm) CONFIRM=1 ;;
    --rotate-key) ROTATE=1 ;;
    *) die "unknown argument '$1': takes --confirm and --rotate-key, or nothing" ;;
    esac
    shift
done

[ -r "$POLICY_DOC" ] || die "the policy document is not beside this script (${POLICY_DOC})"
[ -r "$TRUST_DOC" ] || die "the trust document is not beside this script (${TRUST_DOC})"
# THE CHECKOUT'S OWN INTERPRETER, resolved from this file's location rather
# than from PATH — the header says why. `deploy/` sits outside the gate's
# sourced seam on purpose (`scripts/gate_refuse.sh` is the gate's, and a
# deployment host has no gate beside it), so this is the same two lines
# `checkout_python` is, spelled where they are used.
CHECKOUT_PYTHON="${HERE}/../../.venv/bin/python"
[ -x "$CHECKOUT_PYTHON" ] || die "this checkout has no .venv/bin/python (looked at ${CHECKOUT_PYTHON}).
   The plan below summarises the policy with deploy/policy_summary.py, a file
   this repository writes at the version that venv holds; a system python3 is
   some other environment's and on a 3.9 it fails as if the file were wrong.
   Run ./scripts/setup.sh (or \`uv sync\`) first. Nothing was created."
# The inline programs below are stdlib on any Python 3 and are guarded here
# rather than by the venv, so a checkout that has one but not the other says
# which is missing.
command -v python3 >/dev/null 2>&1 || die "no 'python3' on PATH — the inline readers here parse JSON with it"

# --- the plan, printed before anything is asked of AWS -----------------------
#
# NO AWS CALL HAPPENS ABOVE THIS POINT OR INSIDE IT. That is the property that
# makes a bare run safe to type: a reader who wants to know what this would do
# gets the whole answer without a credential, without a network and without a
# billable anything.
cat <<PLAN
verifier-bootstrap: namespace ${NAMESPACE}, account ${DJB_VERIFIER_ACCOUNT}, region ${DJB_VERIFIER_REGION}.
This would create — and every one of these names is DERIVED from the namespace,
so a second product in this same account creates its own and touches none of these:

  1. IAM policy            ${POLICY_NAME}
                           from $(basename "$POLICY_DOC"), summarised statement by
                           statement below
  2. IAM user              ${USER_NAME}, with that policy attached and nothing else
  3. IAM role              ${ROLE_NAME}
                           trust: the EC2 service alone ($(basename "$TRUST_DOC"))
                           policy: ${SSM_MANAGED_POLICY}
                           and NOTHING else — never an environment box's role,
                           which reads a secrets prefix and writes a backup bucket
  4. instance profile      ${PROFILE_NAME}, carrying role ${ROLE_NAME}
  5. security group        ${GROUP_NAME} in the default VPC of ${DJB_VERIFIER_REGION},
                           tagged djb:role=verifier djb:namespace=${NAMESPACE},
                           EGRESS ONLY — a new EC2 security group has no ingress
                           rule and this script never adds one
  6. access key            one, for ${USER_NAME}, printed ONCE on the last line
                           and stored nowhere. A second run mints no second key
                           unless --rotate-key is typed.

And it would CHECK, and never create, two things that belong to the account
rather than to this deployment — printing the one admin command for each when
it is needed, because both change what a live credential may do and that is the
owner's act:

  0. EC2's Spot service-linked role ${SPOT_SLR_NAME}. One per account,
                           AWS's name, needed by every Spot request in it. The
                           ops user may not create it, by design: this policy
                           grants no iam write at all, so the FIRST Spot launch
                           in a fresh account fails
                           AuthFailure.ServiceLinkedRoleCreationNotPermitted.
  1b. the policy's live DEFAULT VERSION. A policy is a thing AND a document,
                           and finding the thing answers nothing about the
                           document. The rendered one is COMPARED against the
                           live default version, and the one command that
                           publishes a new default is printed only when the two
                           actually differ.
  3b. ${ROLE_NAME}'s REGISTRY GRANT (${NAMESPACE}-verifier-box-ecr). The bank
                           builds the deployed image on a box and pushes it
                           under the tree's tag (ADR deploy-4a), which needs a
                           token minted by the box's OWN role — never one piped
                           from a laptop. This is the widest grant any identity
                           here carries (a box that can WRITE to the registry
                           production pulls from), so it is rendered, compared
                           against what the role actually has, and the one
                           put-role-policy is printed for a human. A missing
                           grant costs the image and never a verdict: the bank
                           prints 'image: NOT built' and banks its row.

Every resource above is tagged djb:namespace=${NAMESPACE}, and every Allow in the
policy is conditioned on that tag: this credential cannot see, start, stop or
terminate another product's verifier boxes in this account, and no census of
this deployment lists them.

verifier-bootstrap: the eight clauses of ${POLICY_NAME}, and the statements that carry them:

  1) launch a box, and only one tagged djb:role + djb:owner + djb:expires + djb:namespace=${NAMESPACE}
  2) tag it, and only as part of the launch or the image capture
  3) terminate it, and only while it carries djb:role=verifier|verifier-bake AND this namespace
  4) capture an image from a bake box of this namespace, and deregister only its own verifier images
  5) read the account: instances, images, prices, the Amazon Linux parameter, the two quotas
  6) open a Session Manager session to a tagged box of this namespace, and end only its own sessions
  7) pass exactly one role, ${ROLE_NAME}, and only to EC2
  8) DENY every write to any instance that carries a Project tag and NO djb:role tag —
     the environment boxes' tag shape, denied explicitly over the top of every Allow above

PLAN

"$CHECKOUT_PYTHON" "$SUMMARY" role <"$POLICY_DOC"
echo ""

if [ -z "$CONFIRM" ]; then
    echo "verifier-bootstrap: nothing was created and no AWS call was made." >&2
    echo "   Re-run with --confirm to create the six things above. Reading this file" >&2
    echo "   must never be one arrow key away from creating an IAM identity." >&2
    exit 2
fi

command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"

AWSQ() { aws --region "$DJB_VERIFIER_REGION" --profile "$DJB_VERIFIER_ADMIN_PROFILE" "$@"; }

# --- the account pin ---------------------------------------------------------
ACCOUNT="$(AWSQ sts get-caller-identity --query Account --output text)"
if [ "$ACCOUNT" != "$DJB_VERIFIER_ACCOUNT" ]; then
    die "this credential resolves to account ${ACCOUNT}, not ${DJB_VERIFIER_ACCOUNT}.
   Nothing was created. The verifier boxes belong in the same account and region
   as the environment boxes so they share a bill and a quota; creating them
   anywhere else makes a credential nobody is watching. Set
   DJB_VERIFIER_ACCOUNT if this account is deliberately a different one."
fi

# --- 0 · EC2's Spot service-linked role, checked and never created -----------
#
# THE FAILURE THIS ANSWERS, PAID FOR AT A REAL LAUNCH. The first Spot
# `run-instances` in a fresh account creates EC2's Spot service-linked role as a
# side effect — if the caller may. The verifier ops user may not, deliberately:
# its policy grants no `iam:` write of any kind, and `iam:CreateServiceLinkedRole`
# is one. So the first launch comes back
# `AuthFailure.ServiceLinkedRoleCreationNotPermitted`, having created nothing,
# and the operator is left holding an error code about a role nobody mentioned.
# Two launches were aborted on it before it was written down.
#
# CHECKED HERE AND NOT CREATED, for the same reason the policy version below is
# printed rather than published: this role is ACCOUNT-WIDE. It is not
# namespaced, it is not tagged, a second deployment in this account shares it,
# and nothing in this repository would ever delete it. That makes creating it an
# act with a blast radius past this deployment, which is the owner's to take.
if AWSQ iam get-role --role-name "$SPOT_SLR_NAME" >/dev/null 2>&1; then
    say "spot service-linked role ${SPOT_SLR_NAME} exists"
else
    say "spot service-linked role ${SPOT_SLR_NAME} is ABSENT — the FIRST Spot launch in this"
    say "  account will fail with AuthFailure.ServiceLinkedRoleCreationNotPermitted, having"
    say "  created nothing. The ops user may not create it (this policy grants no iam write,"
    say "  by design), so create it ONCE under the admin profile:"
    say "    aws --region ${DJB_VERIFIER_REGION} --profile ${DJB_VERIFIER_ADMIN_PROFILE} \\"
    say "      iam create-service-linked-role --aws-service-name ${SPOT_SLR_SERVICE}"
    say "  A second run of that command answers InvalidInput (the name has been taken), so"
    say "  it is safe to repeat; this script's own check is what tells you whether to."
fi

# The three coordinates the shipped document leaves as slots, so the tracked
# file carries no account id and no product name and a clone of this template
# needs no edit to it.
RENDERED="$(sed -e "s|\${ACCOUNT_ID}|${ACCOUNT}|g" \
    -e "s|\${REGION}|${DJB_VERIFIER_REGION}|g" \
    -e "s|\${NAMESPACE}|${NAMESPACE}|g" "$POLICY_DOC")"
POLICY_ARN="arn:aws:iam::${ACCOUNT}:policy/${POLICY_NAME}"

# Every created resource carries these. The namespace tag is what a census
# filters on, and what every Allow in the policy is conditioned on.
NS_TAGS="Key=djb:role,Value=verifier-ops Key=djb:namespace,Value=${NAMESPACE}"

# --- 1 · the policy ----------------------------------------------------------
# IDEMPOTENT IS NOT UP TO DATE, and this branch is where the two part company.
# Everything else this script makes is a THING: a user either exists or it does
# not, and finding it is the whole answer. A policy is a thing AND A DOCUMENT,
# and the document in this tree changes — so `exists` answers the first
# question while saying nothing about the second, and the account goes on
# enforcing whatever version it was created with. A live account met the cost:
# the file granted `ec2:CreateTags` on an image and a snapshot, the attached
# version did not, and a capture was refused on a grant the tracked file
# plainly contained.
#
# WHY IT PRINTS RATHER THAN PUBLISHES. A new default policy version changes
# what a live credential may do, in an account this script is otherwise only
# ever asked to populate once; that is the owner's act, and refuse-first is
# this file's whole shape. So it renders the document to a file, names it, and
# hands over the one command — including `--set-as-default`, because a version
# nothing defaults to enforces nothing.
if AWSQ iam get-policy --policy-arn "$POLICY_ARN" >/dev/null 2>&1; then
    say "policy ${POLICY_NAME} exists"
    # AND IT IS COMPARED, NOT ASSUMED STALE. The first form of this branch
    # printed the `create-policy-version` command on EVERY re-run, because
    # "exists" was all it knew. An instruction that is printed whether or not it
    # is needed is an instruction nobody reads by the third run — and this one
    # changes what a live credential may do, which is the last thing that should
    # arrive as noise. So the live DEFAULT VERSION's document is fetched and
    # compared with the rendered one, and the command is printed only when they
    # actually differ.
    #
    # CANONICAL JSON, NOT BYTES. The CLI returns the document decoded and
    # re-serialised in its own key order and spacing; the tracked file is
    # hand-formatted with three slots substituted into it. A byte comparison
    # would report every policy as stale for ever, which is the same as not
    # comparing.
    POLICY_LIVE_VERSION="$(AWSQ iam get-policy --policy-arn "$POLICY_ARN" \
        --query 'Policy.DefaultVersionId' --output text 2>/dev/null || true)"
    POLICY_LIVE_DOC=""
    if [ -n "$POLICY_LIVE_VERSION" ] && [ "$POLICY_LIVE_VERSION" != "None" ]; then
        POLICY_LIVE_DOC="$(AWSQ iam get-policy-version --policy-arn "$POLICY_ARN" \
            --version-id "$POLICY_LIVE_VERSION" \
            --query 'PolicyVersion.Document' --output json 2>/dev/null || true)"
    fi
    POLICY_VERDICT=unknown
    if [ -n "$POLICY_LIVE_DOC" ]; then
        # BOTH DOCUMENTS ON STDIN, NEVER IN AN ARGV: a policy document is long
        # and an argv is a public place. Exit 0 same · 1 different · 2 could not
        # read either as JSON, which is could-not-look and is NOT "the same".
        POLICY_VERDICT="$(printf '%s\n\037\n%s\n' "$RENDERED" "$POLICY_LIVE_DOC" | python3 -c '
import json, sys

raw = sys.stdin.read().split("\x1f")
try:
    a, b = (json.loads(part) for part in raw[:2])
except (ValueError, IndexError):
    print("unknown")
else:
    print("same" if a == b else "different")
')"
    fi
    case "$POLICY_VERDICT" in
    same)
        say "  up to date: the live default version ${POLICY_LIVE_VERSION} IS $(basename "$POLICY_DOC") as this"
        say "  tree renders it. Nothing to publish."
        ;;
    *)
        RENDERED_PATH="${TMPDIR:-/tmp}/${POLICY_NAME}-rendered.json"
        (
            umask 077
            printf '%s\n' "$RENDERED" >"$RENDERED_PATH"
        )
        if [ "$POLICY_VERDICT" = "different" ]; then
            say "  OUT OF DATE. The live default version ${POLICY_LIVE_VERSION} is not what"
            say "  $(basename "$POLICY_DOC") renders in this tree, and the account enforces the"
            say "  live one: a grant the tracked file plainly contains can be refused."
        else
            say "  NOT COMPARED — the live default version could not be read, so whether it"
            say "  matches $(basename "$POLICY_DOC") is unknown. Treated as out of date, because"
            say "  a document nobody could read is not a document that agrees."
        fi
        say "  The rendered document is at ${RENDERED_PATH}; publish it as the live version with:"
        say "    aws --region ${DJB_VERIFIER_REGION} --profile ${DJB_VERIFIER_ADMIN_PROFILE} iam create-policy-version \\"
        say "      --policy-arn ${POLICY_ARN} \\"
        say "      --policy-document file://${RENDERED_PATH} --set-as-default"
        say "  (IAM keeps five versions; delete an old one with iam delete-policy-version if that limit bites.)"
        ;;
    esac
else
    # shellcheck disable=SC2086
    AWSQ iam create-policy --policy-name "$POLICY_NAME" \
        --description "Bring ${NAMESPACE} verifier boxes up and down; nothing else in this account." \
        --policy-document "$RENDERED" \
        --tags $NS_TAGS >/dev/null
    say "policy ${POLICY_NAME} created"
fi

# --- 2 · the user ------------------------------------------------------------
if AWSQ iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
    say "user ${USER_NAME} exists"
else
    # shellcheck disable=SC2086
    AWSQ iam create-user --user-name "$USER_NAME" --tags $NS_TAGS >/dev/null
    say "user ${USER_NAME} created"
    AWSQ iam attach-user-policy --user-name "$USER_NAME" --policy-arn "$POLICY_ARN" >/dev/null
    say "policy ${POLICY_NAME} attached to ${USER_NAME}"
fi

# --- 3 · the box role --------------------------------------------------------
if AWSQ iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    say "role ${ROLE_NAME} exists"
else
    # shellcheck disable=SC2086
    AWSQ iam create-role --role-name "$ROLE_NAME" \
        --description "A ${NAMESPACE} verifier box's own identity: register with Session Manager, and nothing else." \
        --assume-role-policy-document "file://${TRUST_DOC}" \
        --tags $NS_TAGS >/dev/null
    say "role ${ROLE_NAME} created"
    # ONE managed policy, and the drive asserts it is this one and no other.
    AWSQ iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$SSM_MANAGED_POLICY" >/dev/null
    say "policy AmazonSSMManagedInstanceCore attached to ${ROLE_NAME} (the only one)"
fi

# --- 3b · the box role's registry grant, PRINTED and never attached ----------
#
# WHY THE BOX NEEDS ONE AT ALL. The bank builds the deployed image on a
# verifier box, from the tree its own composed verdict has just passed (ADR
# deploy-4a), and pushes it under that tree's tag. A push needs a registry
# token, and the ONLY honest place to mint one is the box's own instance role:
# a token piped over from the operator's laptop makes every bank depend on one
# person's credentials and puts a registry password in a local argv. That is
# not hypothetical — it is exactly how the first hand-built image was pushed,
# and this step is what replaces it.
#
# WHY IT IS PRINTED RATHER THAN ATTACHED. This grant lets a box WRITE to the
# registry that production pulls from, which is the widest thing any identity
# in this file can do. Step 1's paragraph makes the same argument about a
# policy version: an act that changes what a live credential may do is the
# owner's, and this script's whole shape is refuse-first. So it renders the
# document, compares it with what the role actually carries, and prints the one
# command — and prints NOTHING when the live grant already IS this document,
# because an instruction printed on every run is one nobody reads by the third.
#
# EVERY COORDINATE IS DERIVED. The two repository ARNs are composed from the
# caller's own account (already checked against DJB_VERIFIER_ACCOUNT), the
# region this script was given, and the namespace — the same three slots the
# ops policy's tracked document carries. Nothing account-specific is typed
# here or anywhere in the tree.
#
# LEAST PRIVILEGE, AND THE ONE STATEMENT THAT CANNOT BE SCOPED.
# `ecr:GetAuthorizationToken` takes no resource — AWS mints an account-level
# token and there is no repository to name — so it is `*` by the API's shape,
# not by ours; every other action is on the two repositories this deployment
# has and on nothing else. `ecr:DeleteRepository`, `ecr:BatchDeleteImage` and
# every registry-wide write are absent: a bank may add an image and may never
# remove one.
ECR_POLICY_NAME="${NAMESPACE}-verifier-box-ecr"
ECR_REPO_ARN_WEB="arn:aws:ecr:${DJB_VERIFIER_REGION}:${ACCOUNT}:repository/${NAMESPACE}/djb-web"
ECR_REPO_ARN_WORKER="arn:aws:ecr:${DJB_VERIFIER_REGION}:${ACCOUNT}:repository/${NAMESPACE}/djb-worker"
ECR_DOC="$(
    cat <<JSON
{"Version": "2012-10-17", "Statement": [
  {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
  {"Effect": "Allow",
   "Action": ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage",
              "ecr:GetDownloadUrlForLayer", "ecr:InitiateLayerUpload",
              "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
              "ecr:PutImage", "ecr:DescribeImages", "ecr:ListImages"],
   "Resource": ["${ECR_REPO_ARN_WEB}",
                "${ECR_REPO_ARN_WORKER}"]}]}
JSON
)"
ECR_LIVE_DOC="$(AWSQ iam get-role-policy --role-name "$ROLE_NAME" \
    --policy-name "$ECR_POLICY_NAME" --query 'PolicyDocument' --output json 2>/dev/null || true)"
ECR_VERDICT=absent
if [ -n "$ECR_LIVE_DOC" ] && [ "$ECR_LIVE_DOC" != "None" ]; then
    # BOTH DOCUMENTS ON STDIN AND COMPARED AS JSON, step 1's reader exactly:
    # the CLI returns the document decoded and re-serialised in its own key
    # order, so a byte comparison would report every grant as stale for ever.
    ECR_VERDICT="$(printf '%s\n\037\n%s\n' "$ECR_DOC" "$ECR_LIVE_DOC" | python3 -c '
import json, sys

raw = sys.stdin.read().split("\x1f")
try:
    a, b = (json.loads(part) for part in raw[:2])
except (ValueError, IndexError):
    print("unknown")
else:
    print("same" if a == b else "different")
')"
fi
case "$ECR_VERDICT" in
same)
    say "registry grant ${ECR_POLICY_NAME} on ${ROLE_NAME} is up to date — a box can push"
    say "  the two repositories of this namespace and nothing else. Nothing to publish."
    ;;
*)
    ECR_DOC_PATH="${TMPDIR:-/tmp}/${ECR_POLICY_NAME}.json"
    printf '%s\n' "$ECR_DOC" >"$ECR_DOC_PATH"
    if [ "$ECR_VERDICT" = "different" ]; then
        say "registry grant ${ECR_POLICY_NAME} on ${ROLE_NAME} is OUT OF DATE — what the role"
        say "  carries is not what this tree renders, and the account enforces the live one."
    else
        say "registry grant ${ECR_POLICY_NAME} on ${ROLE_NAME} is ABSENT. Until it is attached a"
        say "  verifier box cannot push the image the bank builds (ADR deploy-4a): the bank"
        say "  prints 'image: NOT built' and every verdict it banks is unaffected."
    fi
    say "  The rendered document is at ${ECR_DOC_PATH}; attach it with:"
    say "    aws --region ${DJB_VERIFIER_REGION} --profile ${DJB_VERIFIER_ADMIN_PROFILE} iam put-role-policy \\"
    say "      --role-name ${ROLE_NAME} --policy-name ${ECR_POLICY_NAME} \\"
    say "      --policy-document file://${ECR_DOC_PATH}"
    say "  It grants: a registry token (account-wide, the API's own shape), and layer"
    say "  upload, PutImage, DescribeImages and pull on ${NAMESPACE}/djb-web and"
    say "  ${NAMESPACE}/djb-worker. No delete of any kind, and no other repository."
    ;;
esac

# --- 4 · the instance profile ------------------------------------------------
if AWSQ iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
    say "instance profile ${PROFILE_NAME} exists"
else
    # shellcheck disable=SC2086
    AWSQ iam create-instance-profile --instance-profile-name "$PROFILE_NAME" --tags $NS_TAGS >/dev/null
    AWSQ iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME" >/dev/null
    say "instance profile ${PROFILE_NAME} created, carrying ${ROLE_NAME}"
fi

# --- 5 · the security group --------------------------------------------------
#
# NO INGRESS RULE IS EVER ADDED, here or anywhere. A new EC2 security group is
# created with an allow-all EGRESS rule and no ingress rule at all, which is
# exactly the posture a verifier box wants: it reaches out to a package index
# and a registry, and nothing on the internet can reach it. Every connection to
# it is an SSH session tunnelled through Session Manager, which needs no open
# port.
EXISTING_GROUP="$(AWSQ ec2 describe-security-groups \
    --filters "Name=group-name,Values=${GROUP_NAME}" \
    --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)"
if [ -n "$EXISTING_GROUP" ] && [ "$EXISTING_GROUP" != "None" ]; then
    say "security group ${GROUP_NAME} exists (${EXISTING_GROUP})"
else
    VPC="$(AWSQ ec2 describe-vpcs --filters Name=is-default,Values=true \
        --query 'Vpcs[0].VpcId' --output text)"
    { [ -n "$VPC" ] && [ "$VPC" != "None" ]; } ||
        die "no default VPC in ${DJB_VERIFIER_REGION}. This script does not create one —
   a network is a design decision, not a bootstrap step."
    GROUP_ID="$(AWSQ ec2 create-security-group --group-name "$GROUP_NAME" \
        --description "${NAMESPACE} verifier boxes: egress only, no ingress, reached over Session Manager." \
        --vpc-id "$VPC" --query GroupId --output text)"
    AWSQ ec2 create-tags --resources "$GROUP_ID" \
        --tags Key=djb:role,Value=verifier "Key=djb:namespace,Value=${NAMESPACE}" \
        "Key=Name,Value=${GROUP_NAME}" >/dev/null
    say "security group ${GROUP_NAME} created (${GROUP_ID}) in ${VPC} — egress only"
fi

# --- 6 · the access key ------------------------------------------------------
EXISTING_KEYS="$(AWSQ iam list-access-keys --user-name "$USER_NAME" \
    --query 'AccessKeyMetadata[].AccessKeyId' --output text 2>/dev/null || true)"
if [ -n "$EXISTING_KEYS" ] && [ -z "$ROTATE" ]; then
    say "access key exists for ${USER_NAME} (${EXISTING_KEYS}) — no second key minted."
    echo ""
    say "everything above already existed. Nothing was created."
    say "If the secret half was lost, re-run with --confirm --rotate-key."
    exit 0
fi

KEY_JSON="$(AWSQ iam create-access-key --user-name "$USER_NAME")"
# Parsed on stdin, never as an argument: a secret in an argv lands in `ps` and
# in a shell history file.
KEY_LINE="$(printf '%s' "$KEY_JSON" | python3 -c 'import json,sys
k = json.load(sys.stdin)["AccessKey"]
print("%s %s" % (k["AccessKeyId"], k["SecretAccessKey"]))')"

echo ""
say "done. Now, once, on this machine:"
say "    aws configure --profile ${CLI_PROFILE}"
say "  region ${DJB_VERIFIER_REGION}, output json, and the two values on the LAST line below."
say "  They are printed here once and stored nowhere."
echo ""
printf 'ACCESS KEY (id then secret, copy them now): %s\n' "$KEY_LINE"
