#!/usr/bin/env bash
. "$(dirname -- "${BASH_SOURCE:-$0}")/../../scripts/bash_only.sh" || exit 2
# A PRODUCT'S ONCE-ONLY AWS HAND. The IAM and registry a product's first deploy
# needs and no developer credential may make: the environment box's role and
# instance profile (runbook step 19), the three image repositories, the GitHub
# OIDC provider and CI's push role (step 19a), and CI's deploy role (the
# runbook's "Deploying from CI"). `verifier_bootstrap.sh` is the shape.
#
# THE FOUR COORDINATES COME FROM YOUR SHELL, WITH NO DEFAULTS:
#
#   print the whole plan, call nothing, exit 2:
#
#     DJB_DEPLOY_NAMESPACE=<ns> AWS_REGION=<region> DJB_ENV=<env> DJB_GITHUB_REPO=<owner>/<repo> \
#       ./deploy/iam/product_bootstrap.sh
#
#   do it:
#
#     DJB_DEPLOY_NAMESPACE=<ns> AWS_REGION=<region> DJB_ENV=<env> DJB_GITHUB_REPO=<owner>/<repo> \
#       ./deploy/iam/product_bootstrap.sh --confirm
#
# BOTH OIDC SUBJECT SPELLINGS ARE TRUSTED: `repo:<owner>/<repo>:…` and its
# id-spelled twin `repo:<owner>@<owner id>/<repo>@<repo id>:…`, which a newer
# repository's token carries (`gh api repos/<owner>/<repo>/actions/oidc/customization/sub`
# says which). The ids are read once, at plan time, with `gh api repos/<owner>/<repo>`;
# `DJB_GITHUB_REPO_IDS=<owner id>/<repo id>` stands in for that read. No ids, no
# --confirm: a trust policy GitHub's first token would be refused by is never made.
#
# The account is the caller's own (`aws sts get-caller-identity`), read at
# --confirm; `AWS_PROFILE` picks the credential the way the CLI always does.
#
# WHAT IT MAKES, every name derived from the namespace, every one tagged
# djb:namespace=<ns>, each looked up first and left alone when found:
#
#   role + instance profile  <ns>-<env>-box   inline djb-box, djb-box-ecr
#   ECR repositories         <ns>/djb-web, <ns>/djb-worker, <ns>/djb-frontend   immutable, scanned
#   OIDC provider            token.actions.githubusercontent.com  one per account:
#                                             reused when found, never tagged
#   role                     <ns>-ci-images   inline djb-ci-images, ecr-public-login,
#                                             ecr-public-push
#   role                     <ns>-ci-deploy   inline djb-ci-deploy
#
# A FOUND ROLE'S DOCUMENTS ARE COMPARED, NOT REWRITTEN: a live trust or inline
# policy that differs from this tree's rendering prints the one command that
# publishes it — changing what a live credential may do is the owner's act. Two
# exceptions: a trust that differs only by lacking OIDC subjects this tree
# names gains them (`update-assume-role-policy`, the live list kept, each added
# subject printed) — the re-run that heals a role made before both spellings;
# and an inline policy whose statement Sids are exactly the set this tree
# renders is TEMPLATE-OWNED and rewritten (`put-role-policy`, the replaced
# values printed) — the re-run after a take that changed the document (N2179).
# Any other Sid set, or a statement with none, is hand-edited: printed, never put.
#
# WHAT IT DOES NOT DO. No delete. No key pair (step 18 — a private key is a
# secret this script never holds). No ECR Public repository (step 19a, 5c). No
# `gh` write — its one call reads the ids; the variable lines are PRINTED for the
# owner to paste.
#
# Exit: 0 everything exists (created or found) · non-zero an AWS call failed ·
# 2 refused — a coordinate unset or malformed, no --confirm, a piped stdout, an
# unknown flag, no `aws`, no interpreter in this checkout's venv, no OIDC ids.
# Nothing is created on any exit-2 path.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DEPLOY_NAME=product-bootstrap
DEPLOY_NOTHING="Nothing was created and no AWS call was made."
# shellcheck source=deploy/lib.sh
. "$HERE/../lib.sh" || exit 2

NAMESPACE="${DJB_DEPLOY_NAMESPACE:-}"
[ -n "$NAMESPACE" ] || die "DJB_DEPLOY_NAMESPACE is required — the slug every name here is composed from.
   There is no default: more than one product shares an AWS account, and a
   guessed namespace is a write into somebody else's resources."
REGION="${AWS_REGION:-}"
[ -n "$REGION" ] || die "AWS_REGION is required — the region every call carries explicitly. There is
   no default: your configured one is very often not the one the boxes live in."
ENVIRONMENT="${DJB_ENV:-}"
[ -n "$ENVIRONMENT" ] || die "DJB_ENV is required — the environment the box role serves (staging, prod).
   The box role reads that environment's one secret and two buckets and no other's."
REPO="${DJB_GITHUB_REPO:-}"
[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || die "DJB_GITHUB_REPO is required as one <owner>/<repo> (got '${REPO}').
   The two CI roles trust that repository's tokens and no other's; a wildcard is
   how somebody else's fork pushes into your registry."
REPO_IDS="${DJB_GITHUB_REPO_IDS:-}"
[ -z "$REPO_IDS" ] || [[ "$REPO_IDS" =~ ^[0-9]+/[0-9]+$ ]] || die "DJB_GITHUB_REPO_IDS is <owner id>/<repo id>, both numeric (got '${REPO_IDS}')."

refuse_if_piped "$DEPLOY_NAME"

CONFIRM=""
while [ "$#" -gt 0 ]; do
    case "$1" in
    --confirm) CONFIRM=1 ;;
    *) die "unknown argument '$1': takes --confirm, or nothing" ;;
    esac
    shift
done

BOX_ROLE="${NAMESPACE}-${ENVIRONMENT}-box"
IMAGES_ROLE="${NAMESPACE}-ci-images"
DEPLOY_ROLE="${NAMESPACE}-ci-deploy"
OIDC_HOST="token.actions.githubusercontent.com"
REPOSITORIES=("${NAMESPACE}/djb-web" "${NAMESPACE}/djb-worker" "${NAMESPACE}/djb-frontend")
TAGS=("Key=djb:namespace,Value=${NAMESPACE}")
# <role> <inline policy name> <document> — the runbook's own names.
INLINE=(
    "$BOX_ROLE djb-box product-box-policy.json"
    "$BOX_ROLE djb-box-ecr product-box-ecr-policy.json"
    "$IMAGES_ROLE djb-ci-images product-ci-images-policy.json"
    "$IMAGES_ROLE ecr-public-login product-ci-ecr-public-login.json"
    "$IMAGES_ROLE ecr-public-push product-ci-ecr-public-push.json"
    "$DEPLOY_ROLE djb-ci-deploy product-ci-deploy-policy.json"
)
for doc in product-box-trust.json product-ci-images-trust.json product-ci-deploy-trust.json \
    $(printf '%s\n' "${INLINE[@]}" | awk '{print $3}'); do
    [ -r "$HERE/$doc" ] || die "the document ${doc} is not beside this script (${HERE})"
done
CHECKOUT_PYTHON="${HERE}/../../.venv/bin/python"
[ -x "$CHECKOUT_PYTHON" ] || die "this checkout has no .venv/bin/python (looked at ${CHECKOUT_PYTHON}).
   The plan summarises each policy with deploy/policy_summary.py; run ./scripts/setup.sh first."
command -v python3 >/dev/null 2>&1 || die "no 'python3' on PATH — the inline readers here parse JSON with it"

# Each OIDC subject followed by its id-spelled twin; the tracked document on stdin.
TWINS_PY='
import json, sys

doc, repo, ids = json.load(sys.stdin), sys.argv[1], sys.argv[2]
if ids:
    (owner, name), (oid, rid) = repo.split("/"), ids.split("/")
    key = "token.actions.githubusercontent.com:sub"
    for statement in doc["Statement"]:
        like = statement.get("Condition", {}).get("StringLike", {})
        if key in like:
            twin = f"repo:{owner}@{oid}/{name}@{rid}:"
            like[key] = [s for sub in like[key] for s in (sub, sub.replace(f"repo:{repo}:", twin))]
'

# The ids, read once: `gh` answers `<owner id>/<repo id>` or IDS_REFUSED says why not.
IDS_REFUSED=""
if [ -z "$REPO_IDS" ]; then
    if ! command -v gh >/dev/null 2>&1; then
        IDS_REFUSED="no 'gh' on PATH to read ${REPO}'s ids"
    elif ! answer="$(gh api "repos/${REPO}" --jq '"\(.owner.id)/\(.id)"' 2>&1)"; then
        IDS_REFUSED="gh api repos/${REPO} failed: ${answer%%$'\n'*}"
    elif [[ ! "$answer" =~ ^[0-9]+/[0-9]+$ ]]; then
        IDS_REFUSED="gh api repos/${REPO} answered '${answer%%$'\n'*}', not <owner id>/<repo id>"
    else
        REPO_IDS="$answer"
    fi
fi

# <trust document> — its OIDC subjects, one per line, indented for the plan.
plan_subjects() {
    sed -e "s|\${REPO}|${REPO}|g" "$HERE/$1" | python3 -c "${TWINS_PY}
for statement in doc['Statement']:
    for sub in statement.get('Condition', {}).get('StringLike', {}).get(key, []):
        print('         ' + sub)
" "$REPO" "$REPO_IDS"
}

# --- the plan: NO AWS CALL HAPPENS ABOVE THIS POINT OR INSIDE IT -------------
if [ -n "$IDS_REFUSED" ]; then
    IDS_LINE="REFUSED — ${IDS_REFUSED}. --confirm makes nothing until the ids are read:
  authenticate gh, or set DJB_GITHUB_REPO_IDS=<owner id>/<repo id>"
else
    IDS_LINE="both subject spellings, ids ${REPO_IDS}"
fi
cat <<PLAN
product-bootstrap: namespace ${NAMESPACE}, region ${REGION}, environment ${ENVIRONMENT}, repository ${REPO}.
The account is your credential's own, read at --confirm. This would make — each
looked up first and left alone when found, each namespaced one tagged
djb:namespace=${NAMESPACE}:

  1. role ${BOX_ROLE}                                         (step 19)
       trust: the EC2 service alone (product-box-trust.json)
       inline djb-box: this environment's one secret and two buckets
       inline djb-box-ecr: pull ${REPOSITORIES[*]}     (19a, 7)
  2. instance profile ${BOX_ROLE}, carrying that role             (step 19)
  3. ECR repositories ${REPOSITORIES[*]}             (19a, 1)
       IMMUTABLE tags, scanOnPush
  4. OIDC provider ${OIDC_HOST}                  (19a, 3)
       ONE PER ACCOUNT: reused when found, never tagged
  5. role ${IMAGES_ROLE}                                            (19a, 4-5c)
       trust: ${REPO}'s main and its pull requests
$( [ -n "$IDS_REFUSED" ] || plan_subjects product-ci-images-trust.json)
       inline djb-ci-images: push and read the ${#REPOSITORIES[@]} repositories
       inline ecr-public-login: log in to ECR Public for the stack pulls
       inline ecr-public-push: mirror the stack images to ECR Public
  6. role ${DEPLOY_ROLE}                                            ("Deploying from CI")
       trust: ${REPO}'s main only — ci.yml's deploy jobs declare no environment
$( [ -n "$IDS_REFUSED" ] || plan_subjects product-ci-deploy-trust.json)
       inline djb-ci-deploy: read the two repositories; reach Project=${NAMESPACE} boxes

  OIDC trust: ${IDS_LINE}.

A found role's trust and inline documents are COMPARED with this tree's; one that
differs prints the command that publishes it, and is never rewritten here — except
a trust that only lacks subjects above: it gains them, the live list kept, each
added subject printed; and an inline policy whose statement Sids are exactly the
ones listed below: it is the template's own, and --confirm rewrites it.

The statements of each inline policy:
PLAN
for row in "${INLINE[@]}"; do
    read -r role name doc <<<"$row"
    echo "  ${role} / ${name} (${doc}):"
    "$CHECKOUT_PYTHON" "$HERE/../policy_summary.py" role <"$HERE/$doc"
    echo "    found differing with exactly these Sids: would rewrite; any other Sid set: printed"
done
echo ""

[ -z "$CONFIRM" ] || [ -z "$IDS_REFUSED" ] || die "OIDC trust: REFUSED — ${IDS_REFUSED}.
   Authenticate gh, or set DJB_GITHUB_REPO_IDS=<owner id>/<repo id>."
if [ -z "$CONFIRM" ]; then
    echo "product-bootstrap: nothing was created and no AWS call was made." >&2
    echo "   Re-run with --confirm to make the six things above." >&2
    exit 2
fi

# shellcheck disable=SC2034 # read by deploy/lib.sh's die
DEPLOY_NOTHING="Nothing was created."
command -v aws >/dev/null 2>&1 || die "no 'aws' on PATH"
AWSQ() { aws --region "$REGION" "$@"; }

ACCOUNT="$(AWSQ sts get-caller-identity --query Account --output text)"
[[ "$ACCOUNT" =~ ^[0-9]{12}$ ]] || die "sts get-caller-identity answered '${ACCOUNT}', not a 12-digit account"
say "account ${ACCOUNT} (the caller's own)"

# The tracked document with its slots filled and each OIDC subject's twin beside it.
MEDIA_BUCKET="$(bucket_name media "$ENVIRONMENT" "$ACCOUNT")"
BACKUPS_BUCKET="$(bucket_name backups "$ENVIRONMENT" "$ACCOUNT")"

render() {
    sed -e "s|\${ACCOUNT_ID}|${ACCOUNT}|g" -e "s|\${REGION}|${REGION}|g" \
        -e "s|\${MEDIA_BUCKET}|${MEDIA_BUCKET}|g" -e "s|\${BACKUPS_BUCKET}|${BACKUPS_BUCKET}|g" \
        -e "s|\${NAMESPACE}|${NAMESPACE}|g" -e "s|\${ENV}|${ENVIRONMENT}|g" \
        -e "s|\${REPO}|${REPO}|g" "$HERE/$1" | python3 -c "${TWINS_PY}
print(json.dumps(doc, separators=(',', ':')))
" "$REPO" "$REPO_IDS"
}

# A trust, wanted then live: `same`, `different`, `unknown`, or `heal` followed by
# the live document with the missing OIDC subjects appended and then each of them.
trust_verdict() {
    printf '%s\n\037\n%s\n' "$1" "$2" | python3 -c '
import copy, json, sys

KEY = "token.actions.githubusercontent.com:sub"
raw = sys.stdin.read().split("\x1f")
try:
    want, live = (json.loads(part) for part in raw[:2])
    if len(want["Statement"]) != len(live["Statement"]):
        raise ValueError("a different number of statements")
    pairs = list(zip(want["Statement"], live["Statement"]))
except (ValueError, IndexError, KeyError, TypeError):
    print("unknown")
    sys.exit(0)


def subjects(statement):
    value = statement.get("Condition", {}).get("StringLike", {}).get(KEY)
    return [value] if isinstance(value, str) else value


def bare(doc):
    doc = copy.deepcopy(doc)
    for statement in doc["Statement"]:
        statement.get("Condition", {}).get("StringLike", {}).pop(KEY, None)
    return doc


if bare(want) != bare(live) or any((subjects(w) is None) != (subjects(l) is None) for w, l in pairs):
    print("different")
    sys.exit(0)
missing = [[s for s in subjects(w) or [] if s not in (subjects(l) or [])] for w, l in pairs]
if not any(missing):
    same = all(set(subjects(w) or []) == set(subjects(l) or []) for w, l in pairs)
    print("same" if same else "different")
    sys.exit(0)
healed = copy.deepcopy(live)
for statement, (_, l), gained in zip(healed["Statement"], pairs, missing):
    if gained:
        statement["Condition"]["StringLike"][KEY] = (subjects(l) or []) + gained
print("heal")
print(json.dumps(healed, separators=(",", ":")))
print("\n".join(s for gained in missing for s in gained))
'
}

# An inline policy, wanted then live: `same`, `different`, `unknown`, or `owned`
# followed by the template's Sids and the live values the rewrite replaces.
inline_verdict() {
    printf '%s\n\037\n%s\n' "$1" "$2" | python3 -c '
import json, sys

raw = sys.stdin.read().split("\x1f")
try:
    want, live = (json.loads(part) for part in raw[:2])
    sids = [[s.get("Sid") for s in d["Statement"]] for d in (want, live)]
except (ValueError, IndexError, KeyError, TypeError, AttributeError):
    print("unknown")
    sys.exit(0)
if want == live:
    print("same")
    sys.exit(0)
mine, theirs = sids
if None in mine or not mine or sorted(map(str, theirs)) != sorted(mine) or len(set(mine)) != len(mine):
    print("different")
    sys.exit(0)


def values(statement):
    for key in ("Effect", "Action", "Resource", "NotAction", "NotResource", "Condition"):
        value = statement.get(key)
        if isinstance(value, dict):
            yield from (json.dumps({k: v}, separators=(",", ":")) for k, v in value.items())
        elif value is not None:
            yield from ([value] if isinstance(value, str) else value)


by_sid = {s["Sid"]: s for s in want["Statement"]}
was = [v for s in live["Statement"] for v in values(s) if v not in set(values(by_sid[s["Sid"]]))]
print("owned")
print(",".join(sorted(mine)))
print(" ".join(was) or "(order or form only)")
'
}

# Print the publishing command for a document that differs; never run it.
stale() {
    local what="$1" path="$2" command="$3"
    say "  ${what} is NOT what this tree renders; the account enforces the live one."
    say "  The rendered document is at ${path}; publish it with:"
    say "    aws --region ${REGION} ${command} --policy-document file://${path}"
}

# <role> <trust document> — echoes the role's ARN as IAM answers it.
ensure_role() {
    local role="$1" trust arn live verdict healed gained
    trust="$(render "$2")"
    if arn="$(AWSQ iam get-role --role-name "$role" --query Role.Arn --output text 2>/dev/null)"; then
        say "role ${role} exists" >&2
        live="$(AWSQ iam get-role --role-name "$role" --query Role.AssumeRolePolicyDocument --output json)"
        verdict="$(trust_verdict "$trust" "$live")"
        if [ "$verdict" = same ]; then
            say "  trust of ${role} up to date" >&2
        elif [ "${verdict%%$'\n'*}" = heal ]; then
            healed="$(sed -n 2p <<<"$verdict")"
            AWSQ iam update-assume-role-policy --role-name "$role" --policy-document "$healed" >/dev/null
            while IFS= read -r gained; do
                say "  trust of ${role} gains ${gained}" >&2
            done < <(sed -n '3,$p' <<<"$verdict")
        else
            printf '%s\n' "$trust" >"${TMPDIR:-/tmp}/${role}-trust.json"
            stale "the trust of ${role}" "${TMPDIR:-/tmp}/${role}-trust.json" \
                "iam update-assume-role-policy --role-name ${role}" >&2
        fi
    else
        arn="$(AWSQ iam create-role --role-name "$role" --assume-role-policy-document "$trust" \
            --tags "${TAGS[@]}" "Key=djb:role,Value=${role#"${NAMESPACE}"-}" \
            --query Role.Arn --output text)"
        say "role ${role} created" >&2
    fi
    echo "$arn"
}

# <role> <policy name> <document>
ensure_inline() {
    local role="$1" name="$2" doc live path verdict
    doc="$(render "$3")"
    if live="$(AWSQ iam get-role-policy --role-name "$role" --policy-name "$name" \
        --query PolicyDocument --output json 2>/dev/null)"; then
        verdict="$(inline_verdict "$doc" "$live")"
        if [ "$verdict" = same ]; then
            say "inline ${name} on ${role} up to date"
        elif [ "${verdict%%$'\n'*}" = owned ]; then
            AWSQ iam put-role-policy --role-name "$role" --policy-name "$name" \
                --policy-document "$doc" >/dev/null
            say "rewrote ${role} ${name} (template-owned: Sids $(sed -n 2p <<<"$verdict"); was: $(sed -n 3p <<<"$verdict"))"
        else
            path="${TMPDIR:-/tmp}/${role}-${name}.json"
            printf '%s\n' "$doc" >"$path"
            stale "inline ${name} on ${role}" "$path" \
                "iam put-role-policy --role-name ${role} --policy-name ${name}"
        fi
    else
        AWSQ iam put-role-policy --role-name "$role" --policy-name "$name" \
            --policy-document "$doc" >/dev/null
        say "inline ${name} on ${role} created"
    fi
}

# --- 1 · 2 · the box role and its instance profile (step 19) -----------------
BOX_ARN="$(ensure_role "$BOX_ROLE" product-box-trust.json)"
if AWSQ iam get-instance-profile --instance-profile-name "$BOX_ROLE" >/dev/null 2>&1; then
    say "instance profile ${BOX_ROLE} exists"
else
    AWSQ iam create-instance-profile --instance-profile-name "$BOX_ROLE" --tags "${TAGS[@]}" >/dev/null
    AWSQ iam add-role-to-instance-profile --instance-profile-name "$BOX_ROLE" \
        --role-name "$BOX_ROLE" >/dev/null
    say "instance profile ${BOX_ROLE} created, carrying ${BOX_ROLE}"
fi

# --- 3 · the two repositories (step 19a, 1) -----------------------------------
for repository in "${REPOSITORIES[@]}"; do
    if AWSQ ecr describe-repositories --repository-names "$repository" >/dev/null 2>&1; then
        say "repository ${repository} exists"
    else
        AWSQ ecr create-repository --repository-name "$repository" \
            --image-tag-mutability IMMUTABLE --image-scanning-configuration scanOnPush=true \
            --tags "Key=djb:namespace,Value=${NAMESPACE}" >/dev/null
        say "repository ${repository} created"
    fi
done

# --- 4 · the OIDC provider, one per account (step 19a, 3) ---------------------
OIDC_ARN="arn:aws:iam::${ACCOUNT}:oidc-provider/${OIDC_HOST}"
PROVIDERS="$(AWSQ iam list-open-id-connect-providers \
    --query 'OpenIDConnectProviderList[].Arn' --output text)"
if [[ " ${PROVIDERS} " == *"${OIDC_ARN}"* ]]; then
    say "${OIDC_ARN} exists — reused; it is the account's, not this namespace's"
else
    AWSQ iam create-open-id-connect-provider --url "https://${OIDC_HOST}" \
        --client-id-list sts.amazonaws.com >/dev/null
    say "${OIDC_ARN} created"
fi

# --- 5 · 6 · the two CI roles --------------------------------------------------
IMAGES_ARN="$(ensure_role "$IMAGES_ROLE" product-ci-images-trust.json)"
DEPLOY_ARN="$(ensure_role "$DEPLOY_ROLE" product-ci-deploy-trust.json)"
for row in "${INLINE[@]}"; do
    # shellcheck disable=SC2086
    ensure_inline $row
done

REGISTRY="${ACCOUNT}.dkr.ecr.${REGION}.amazonaws.com/${NAMESPACE}"
echo ""
say "done. The box's instance profile, for step 20 onward:"
echo "    export DJB_INSTANCE_PROFILE=${BOX_ROLE}    # role ${BOX_ARN}"
echo ""
say "Paste these on ${REPO} (variables, not secrets — they are coordinates):"
echo "    gh variable set AWS_ECR_ROLE_ARN --repo ${REPO} --body ${IMAGES_ARN}"
echo "    gh variable set DJB_IMAGE_REGISTRY --repo ${REPO} --body ${REGISTRY}"
echo "    gh variable set AWS_REGION --repo ${REPO} --body ${REGION}"
echo "    gh variable set DJB_DEPLOY_NAMESPACE --repo ${REPO} --body ${NAMESPACE}"
say "The deploy role is ${DEPLOY_ARN}. Its variable AWS_DEPLOY_ROLE_ARN stays UNSET until"
say "  the runner-to-box transport exists (the runbook's \"Deploying from CI\" says why)."
say "This replaced, by hand: deploy.md steps 19 and 19a (items 1-7) and the deploy role of"
say "  \"Deploying from CI\". Still yours: step 18's key pair, and ECR Public's repositories (19a, 5c)."
