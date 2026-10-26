"""`provision.sh preflight <env>`: every deploy precondition read at minute zero, nothing written.

does-not-cover: a real account — the stub answers in the shapes the CLI documents, unmeasured.
does-not-cover: an `aws` that answers a clean yes for a resource it cannot actually use.
does-not-cover: a real daemon's login — the `--on-box` stub `docker` is unmeasured against ECR.
does-not-cover: an IAM statement's `Condition` or `NotAction` — check 5 compares Action sets.
does-not-cover: whether a set mail key is valid — check 10 reads that it is set.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.scratch_repo import make_repo
from quality.tests.fixtures.stub_path import StubPath

COPIED = (
    "deploy/provision.sh",
    "deploy/iam/product-box-policy.json",
    "deploy/env.staging.example",
    "deploy/lib.sh",
    "deploy/envfile.py",
    "scripts/bash_only.sh",
    "scripts/gate_refuse.sh",
)
pytestmark = pytest.mark.drives(
    "deploy/provision.sh",
    "deploy/iam/product-box-policy.json",
    "deploy/env.staging.example",
    "deploy/lib.sh",
    "deploy/envfile.py",
    "scripts/bash_only.sh",
    "scripts/gate_refuse.sh",
)

ROOT = Path(__file__).resolve().parents[3]
PROVISION = ROOT / "deploy" / "provision.sh"
NS, ENV, ACCOUNT, REGION = "acmeport", "staging", "123456789012", "us-east-1"
MEDIA, BACKUPS = f"{NS}-{ENV}-{ACCOUNT}-media", f"{NS}-{ENV}-{ACCOUNT}-backups"
REGISTRY = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{NS}"
SECRET_ARN = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{NS}/{ENV}/env-??????"
OTHER = f"othername-{ENV}-{ACCOUNT}-media"
READ_ONLY = re.compile(r"^\S+ (describe-|get-|head-|list-)")


def _policy(*buckets: str, drop: str = "") -> str:
    """The box policy `product_bootstrap.sh` renders, naming `buckets`, without action `drop`."""
    text = (ROOT / "deploy" / "iam" / "product-box-policy.json").read_text()
    for slot, value in (
        ("ACCOUNT_ID", ACCOUNT),
        ("REGION", REGION),
        ("NAMESPACE", NS),
        ("ENV", ENV),
        ("MEDIA_BUCKET", buckets[0]),
        ("BACKUPS_BUCKET", buckets[1]),
    ):
        text = text.replace("${" + slot + "}", value)
    doc = json.loads(text)
    for statement in doc["Statement"]:
        statement["Action"] = [a for a in statement["Action"] if a != drop]
    return json.dumps(doc, separators=(",", ":"))


def _mail_slots() -> list[str]:
    """Every provider key slot `env-file` knows: the manifest's `ANYMAIL_*_KEY|_TOKEN` names."""
    manifest = (ROOT / "deploy" / "env.staging.example").read_text()
    return re.findall(r"^(ANYMAIL_[A-Z0-9_]+_(?:KEY|TOKEN))=", manifest, re.M)


# One world per test: STUB_HAVE names what is wrong with it, STUB_LOG records every call.
AWS_STUB = f"""#!/usr/bin/env bash
argv="$*"
printf '%s\\n' "$argv" >>"$STUB_LOG"
have() {{ case " ${{STUB_HAVE:-}} " in *" $1 "*) return 0 ;; esac; return 1; }}
nope() {{ echo "An error occurred ($1) when calling the $2 operation: $3" >&2; exit 254; }}
case "$argv" in
*"sts get-caller-identity"*) echo "{ACCOUNT}" ;;
*"ec2 describe-key-pairs"*)
    have nokey && nope InvalidKeyPair.NotFound DescribeKeyPairs "The key pair does not exist"
    echo "drive-key" ;;
*"s3api head-bucket"*)
    have s3odd && {{ echo "Could not connect to the endpoint URL: https://s3" >&2; exit 255; }}
    have foreign && nope 403 HeadBucket Forbidden
    have buckets && exit 0
    nope 404 HeadBucket "Not Found" ;;
*"iam get-role-policy"*)
    have nopolicy && nope NoSuchEntity GetRolePolicy "The role policy cannot be found"
    have widepolicy && {{ echo '{_policy(MEDIA, OTHER)}'; exit 0; }}
    have noput && {{ echo '{_policy(MEDIA, BACKUPS, drop="s3:PutObject")}'; exit 0; }}
    echo '{_policy(MEDIA, BACKUPS)}' ;;
*"iam get-role "*)
    have norole && nope NoSuchEntity GetRole "The role cannot be found"
    echo "{NS}-{ENV}-box" ;;
*"iam get-instance-profile"*)
    have noprofile && nope NoSuchEntity GetInstanceProfile "Instance Profile cannot be found"
    echo "{NS}-{ENV}-box" ;;
*"ecr describe-repositories"*)
    have norepo && nope RepositoryNotFoundException DescribeRepositories "does not exist"
    echo "{NS}/djb-web {NS}/djb-worker {NS}/djb-frontend" ;;
*"ecr describe-images"*)
    have noimage && nope ImageNotFoundException DescribeImages "The image requested does not exist"
    echo "sha256:0drive" ;;
*"secretsmanager get-secret-value"*)
    have secretdenied && nope AccessDeniedException GetSecretValue "is not authorized"
    have nosecret && nope ResourceNotFoundException GetSecretValue "can't find the specified secret"
    echo "{SECRET_ARN}" ;;
*"route53 get-hosted-zone"*)
    have nozone && nope NoSuchHostedZone GetHostedZone "No hosted zone found"
    echo "example.test." ;;
*"route53 list-resource-record-sets"*) have site && echo "{ENV}.example.test." ;;
*)
    echo "stub aws: REFUSING an unexpected call: $argv" >&2
    exit 99 ;;
esac
exit 0
"""

# The box's daemon: logged in unless STUB_HAVE says otherwise.
DOCKER_STUB = f"""#!/usr/bin/env bash
argv="$*"
printf 'docker %s\\n' "$argv" >>"$STUB_LOG"
have() {{ case " ${{STUB_HAVE:-}} " in *" $1 "*) return 0 ;; esac; return 1; }}
case "$argv" in
"buildx imagetools inspect "*)
    have loggedout && {{
        echo "ERROR: failed to authorize: failed to fetch anonymous token: 401 Unauthorized" >&2
        exit 1
    }}
    have notag && {{ echo "ERROR: {REGISTRY}/djb-web:x: not found" >&2; exit 1; }}
    have dockerodd && {{ echo "ERROR: dial tcp: lookup registry: no such host" >&2; exit 1; }}
    echo '"sha256:0box"' ;;
*)
    echo "stub docker: REFUSING an unexpected call: $argv" >&2
    exit 99 ;;
esac
"""

ENV_FILE = f"""DJB_DEPLOY_NAMESPACE='{NS}'
DJB_IMAGE_REGISTRY='{REGISTRY}'
CLICKSTACK_ADMIN_EMAIL=
CLICKSTACK_ADMIN_PASSWORD=
"""

EXPORTED = {
    "AWS_REGION": REGION,
    "DJB_DEPLOY_NAMESPACE": "",
    "DJB_IMAGE_REGISTRY": "",
    "DJB_DOMAIN": "example.test",
    "DJB_ZONE_ID": "Z0DRIVE",
    "DJB_OWNER_IP": "203.0.113.7",
    "DJB_KEY_NAME": "drive-key",
}

Run = Callable[..., tuple[Captured, list[str]]]


@pytest.fixture
def tree(scratch: Path) -> Path:
    """`provision.sh` in a committed copy of the files it runs, so its image tag is clean."""
    if not PROVISION.is_file():
        raise CouldNotLook(f"{PROVISION} is not in this tree")
    repo = make_repo(scratch / "tree")
    for name in COPIED:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, repo / name)
    for step in (["add", *COPIED], ["commit", "-q", "-m", "copy"]):
        done = subprocess.run(["git", "-C", str(repo), *step], capture_output=True, text=True)
        if done.returncode != 0:
            raise CouldNotLook(f"git {step[0]} failed in {repo}: {done.stderr.strip()}")
    return repo / "deploy" / "provision.sh"


@pytest.fixture
def tag(tree: Path, capture: Callable[..., Captured]) -> str:
    """The copy's image tag, as `provision.sh image-tag` answers it."""
    got = capture([str(tree), "image-tag"])
    return got.text().strip()


@pytest.fixture
def preflight(
    tree: Path, scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> Run:
    """`preflight(have, env_text=…, **env)` runs `preflight staging <file>` in the world `have`."""
    stub_path.plant("aws", AWS_STUB)
    stub_path.plant("docker", DOCKER_STUB)
    log = scratch / "aws.calls"
    env_file = scratch / "staging.env"

    def run(
        have: str = "buckets site",
        env_text: str | None = ENV_FILE,
        extra: tuple[str, ...] = (),
        **over: str,
    ) -> tuple[Captured, list[str]]:
        log.write_text("")
        if env_file.exists():
            env_file.unlink()
        if env_text is not None:
            env_file.write_text(env_text)
        env = {
            **EXPORTED,
            **over,
            "PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(log),
            "STUB_HAVE": have,
        }
        got = capture([str(tree), "preflight", ENV, str(env_file), *extra], env=env)
        return got, log.read_text().splitlines()

    return run


def _line(text: str, step: str) -> str:
    """The one check line for runbook step `step`; asserting there is exactly one."""
    found = [x for x in text.splitlines() if re.match(rf"^(ok|REFUSED|ERROR) {step} ", x)]
    assert len(found) == 1, (step, text)
    return found[0]


def test_an_all_ok_world_prints_ten_ok_lines_and_writes_nothing(preflight: Run, tag: str) -> None:
    assert re.fullmatch(r"tree-[0-9a-f]{12}", tag), tag
    run, calls = preflight()
    text = run.text()
    assert run.rc == 0, text
    checks = [x for x in text.splitlines() if re.match(r"^(ok|REFUSED|ERROR) ", x)]
    assert len(checks) == 10 and all(x.startswith("ok ") for x in checks), text
    assert calls and [c for c in calls if not READ_ONLY.match(c)] == [], calls


def test_check_1_an_empty_slot_names_the_env_file_line(preflight: Run) -> None:
    run, _ = preflight(env_text=f"DJB_DEPLOY_NAMESPACE='{NS}'\nDJB_IMAGE_REGISTRY=\n")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "16")
    assert line.startswith("REFUSED 16 provision.sh env-file") and "DJB_IMAGE_REGISTRY" in line
    assert f"./deploy/provision.sh env-file deploy/.env {ENV}" in line, line


def test_check_1_a_missing_env_file_is_refused(preflight: Run) -> None:
    run, _ = preflight(env_text=None)
    text = run.text()
    assert run.rc == 1, text
    assert "does not exist" in _line(text, "16"), text


def test_check_1_no_file_yet_with_every_slot_exported_is_ok(preflight: Run) -> None:
    run, _ = preflight(env_text=None, DJB_DEPLOY_NAMESPACE=NS, DJB_IMAGE_REGISTRY=REGISTRY)
    text = run.text()
    assert run.rc == 0, text
    line = _line(text, "16")
    assert line.startswith("ok 16 provision.sh env-file") and "not generated yet" in line, line


def test_check_1_the_laptop_file_stops_before_any_aws_call(preflight: Run) -> None:
    laptop = "DJB_DEPLOY_NAMESPACE='laptop'\nDJB_IMAGE_REGISTRY='local'\n"
    run, calls = preflight(env_text=laptop)
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "16")
    assert line.startswith("REFUSED 16") and "laptop file" in line, line
    assert "DJB_DEPLOY_NAMESPACE=laptop" not in text, text
    assert calls == [], calls


def test_check_2_an_unset_owner_ip_prints_infras_own_line(preflight: Run) -> None:
    run, _ = preflight(DJB_OWNER_IP="")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "20")
    assert line.startswith("REFUSED 20"), line
    assert line.endswith(
        """export DJB_OWNER_IP="$(curl -s https://checkip.amazonaws.com | tr -d '\\n')\""""
    ), line


def test_check_2_two_addresses_are_refused(preflight: Run) -> None:
    run, _ = preflight(DJB_OWNER_IP="203.0.113.7 198.51.100.2")
    assert run.rc == 1 and _line(run.text(), "20").startswith("REFUSED 20"), run.text()


def test_check_3_a_missing_key_pair_names_step_18(preflight: Run) -> None:
    run, _ = preflight("buckets site nokey")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "18")
    assert line.startswith("REFUSED 18") and "aws ec2 create-key-pair" in line, line


def test_check_4_a_bucket_another_account_holds_is_refused(preflight: Run) -> None:
    run, _ = preflight("foreign site")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "22")
    assert line.startswith("REFUSED 22") and "another AWS account" in line, line
    assert "DJB_DEPLOY_NAMESPACE" in line, line


def test_check_4_free_bucket_names_are_ok(preflight: Run) -> None:
    run, _ = preflight("site")
    assert _line(run.text(), "22").startswith("ok 22"), run.text()


def test_check_5_a_box_policy_naming_other_buckets_is_refused(preflight: Run) -> None:
    run, _ = preflight("buckets site widepolicy")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "19")
    assert line.startswith("REFUSED 19") and OTHER in line, line
    assert "./deploy/iam/product_bootstrap.sh --confirm" in line, line


@pytest.mark.parametrize("missing", ["norole", "noprofile", "nopolicy"])
def test_check_5_a_missing_role_profile_or_policy_is_refused(preflight: Run, missing: str) -> None:
    run, _ = preflight(f"buckets site {missing}")
    assert run.rc == 1, run.text()
    assert _line(run.text(), "19").startswith("REFUSED 19"), run.text()


def test_check_5_a_missing_action_is_named(preflight: Run) -> None:
    run, _ = preflight("buckets site noput")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "19")
    assert line.startswith("REFUSED 19") and "actions differ: -s3:PutObject" in line, line
    assert "./deploy/iam/product_bootstrap.sh --confirm" in line, line


def test_the_laptop_names_the_box_login_it_cannot_check(preflight: Run) -> None:
    run, calls = preflight()
    text = run.text()
    host = REGISTRY.split("/", 1)[0]
    found = [x for x in text.splitlines() if x.startswith("not checked here: ")]
    assert found == [
        f"not checked here: the box's docker login to {host} — run "
        f"ssh <user>@<box> 'cd {NS} && ./deploy/provision.sh preflight {ENV} --on-box' on the box"
    ], text
    assert not [c for c in calls if c.startswith("docker ")], calls


def test_the_box_arm_checks_the_daemons_login_and_asks_aws_nothing(
    preflight: Run, tag: str
) -> None:
    run, calls = preflight(extra=("--on-box",))
    text = run.text()
    assert run.rc == 0, text
    line = _line(text, "33")
    assert line.startswith("ok 33") and "logged in to" in line and "sha256:0box" in line, line
    assert [c for c in calls if not c.startswith("docker ")] == [], calls
    assert [x for x in text.splitlines() if re.match(r"^(ok|REFUSED|ERROR) ", x)] == [line]


def test_the_box_arm_refuses_a_logged_out_daemon_with_the_login_line(preflight: Run) -> None:
    run, _ = preflight("loggedout", ENV_FILE, ("--on-box",))
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "33")
    host = REGISTRY.split("/", 1)[0]
    assert line.startswith("REFUSED 33") and "not logged in" in line, line
    assert line.endswith(
        f"aws ecr get-login-password --region {REGION} "
        f"| docker login --username AWS --password-stdin {host}"
    ), line


def test_the_box_arm_counts_a_missing_tag_as_logged_in(preflight: Run) -> None:
    run, _ = preflight("notag", ENV_FILE, ("--on-box",))
    line = _line(run.text(), "33")
    assert run.rc == 0 and line.startswith("ok 33") and "logged in to" in line, run.text()


def test_the_box_arm_an_odd_docker_failure_is_exit_2(preflight: Run) -> None:
    run, _ = preflight("dockerodd", ENV_FILE, ("--on-box",))
    line = _line(run.text(), "33")
    assert run.rc == 2 and line.startswith("ERROR 33"), run.text()
    assert "docker could not answer: " in line and "aws could not answer" not in line, line


def test_the_laptop_names_a_non_ecr_registry_as_written(preflight: Run) -> None:
    run, _ = preflight(env_text=f"DJB_DEPLOY_NAMESPACE='{NS}'\nDJB_IMAGE_REGISTRY='ghcr.io/acme'\n")
    found = [x for x in run.text().splitlines() if x.startswith("not checked here: the box's")]
    assert found and "docker login to ghcr.io/acme — " in found[0], run.text()


def test_check_6_an_unpushed_tag_names_ci(preflight: Run, tag: str) -> None:
    run, _ = preflight("buckets site noimage")
    text = run.text()
    assert run.rc == 1, text
    line = _line(text, "33")
    assert line.startswith("REFUSED 33 provision.sh image-digest") and tag in line, line
    assert "gh run list" in line, line


def test_check_6_a_missing_repository_names_the_bootstrap(preflight: Run) -> None:
    run, _ = preflight("buckets site norepo")
    assert run.rc == 1, run.text()
    assert "product_bootstrap.sh --confirm" in _line(run.text(), "19a"), run.text()


def test_check_7_no_secret_yet_is_fine_before_step_17(preflight: Run) -> None:
    run, _ = preflight("buckets site nosecret")
    line = _line(run.text(), "17")
    assert line.startswith("ok 17") and "not stored yet" in line, line


def test_check_7_a_denied_secret_is_could_not_look(preflight: Run) -> None:
    run, _ = preflight("buckets site secretdenied nokey")
    text = run.text()
    assert run.rc == 2, text
    line = _line(text, "17")
    assert line.startswith("ERROR 17") and "AccessDeniedException" in line, line


def test_check_8_empty_clickstack_slots_are_informational(preflight: Run) -> None:
    run, _ = preflight()
    line = _line(run.text(), "37")
    assert line.startswith("ok 37") and "./deploy/release.sh --without-alerts" in line, line


def test_check_10_no_mail_key_says_staging_sends_no_mail(preflight: Run) -> None:
    run, _ = preflight(**dict.fromkeys(_mail_slots(), ""))
    assert run.rc == 0, run.text()
    line = _line(run.text(), "24")
    assert line.startswith("ok 24 comms: no mail provider key set"), line
    assert "staging sends no mail — deploy.md § Email mechanism" in line, line
    assert "comms.message.failed is the expected outcome" in line, line


def test_env_file_knows_at_least_one_mail_slot() -> None:
    assert _mail_slots(), "env.staging.example names no ANYMAIL_*_KEY|_TOKEN slot"


@pytest.mark.parametrize("slot", _mail_slots())
def test_check_10_a_set_mail_key_names_its_provider_and_the_page(preflight: Run, slot: str) -> None:
    provider = slot.split("_")[1].lower()
    run, _ = preflight(**{slot: "drive-value"})
    line = _line(run.text(), "24")
    assert line.startswith(f"ok 24 comms: {slot} is set; comms sends through anymail:{provider}"), (
        line
    )
    assert "deploy.md § Email mechanism" in line, line


def test_check_10_reads_a_provider_slot_by_prefix_with_no_edit(preflight: Run) -> None:
    mailgun = ENV_FILE + "ANYMAIL_MAILGUN_API_KEY='drive-value'\n"  # pragma: allowlist secret
    run, _ = preflight(env_text=mailgun)
    line = _line(run.text(), "24")
    assert line.startswith("ok 24 comms: ANYMAIL_MAILGUN_API_KEY is set"), line
    assert "anymail:mailgun" in line, line


def test_check_10_ses_sends_on_the_box_role_with_no_key(preflight: Run) -> None:
    run, _ = preflight(EMAIL_BACKEND="anymail.backends.amazon_ses.EmailBackend")
    line = _line(run.text(), "24")
    assert line.startswith("ok 24 comms: EMAIL_BACKEND is Amazon SES"), line
    assert "instance role" not in line and "deploy.md § Email mechanism" in line, line
    role = f"arn:aws:iam::{ACCOUNT}:role/{NS}-{ENV}-box"
    assert (
        "not checked here: SES's credential is the box's instance role — aws iam "
        f"simulate-principal-policy --policy-source-arn {role} --action-names ses:SendRawEmail"
    ) in run.text().splitlines(), run.text()


def test_check_9_an_unreadable_zone_is_refused_and_the_site_record_is_stated(
    preflight: Run,
) -> None:
    run, _ = preflight("buckets nozone")
    assert _line(run.text(), "26").startswith("REFUSED 26"), run.text()
    run, _ = preflight("buckets")
    assert f"{ENV}.example.test absent" in _line(run.text(), "26"), run.text()
    run, _ = preflight("buckets site")
    assert f"{ENV}.example.test present" in _line(run.text(), "26"), run.text()


def test_an_odd_aws_failure_is_exit_2_with_its_stderr(preflight: Run) -> None:
    run, _ = preflight("s3odd site nokey")
    text = run.text()
    assert run.rc == 2, text
    line = _line(text, "22")
    assert line.startswith("ERROR 22") and "Could not connect to the endpoint URL" in line, line


def test_an_error_after_a_refusal_still_exits_2(preflight: Run) -> None:
    run, _ = preflight("site nokey s3odd")
    text = run.text()
    assert run.rc == 2, text
    refused, error = _line(text, "18"), _line(text, "22")
    assert refused.startswith("REFUSED 18") and error.startswith("ERROR 22"), text
    assert text.index(refused) < text.index(error), text
