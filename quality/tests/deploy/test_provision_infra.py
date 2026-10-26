"""`provision.sh infra`: account-qualified bucket names; every resource looked up before it is made.

does-not-cover: a real account — the stub answers in the shapes the CLI documents, unmeasured.
does-not-cover: a security group found WITHOUT its ingress rules (a run killed between calls).
does-not-cover: regions other than us-east-1, where `create-bucket` needs a location constraint.
does-not-cover: `product_bootstrap.sh`'s live render — its bucket slots are read as text here.
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
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "deploy/provision.sh",
    "deploy/teardown.sh",
    "deploy/lib.sh",
    "deploy/env.staging.example",
    "deploy/iam/product-box-policy.json",
    "deploy/iam/product_bootstrap.sh",
    "deploy/pool_budget.py",
)

ROOT = Path(__file__).resolve().parents[3]
PROVISION = ROOT / "deploy" / "provision.sh"
LIB = ROOT / "deploy" / "lib.sh"
EXAMPLE = ROOT / "deploy" / "env.staging.example"
POLICY = ROOT / "deploy" / "iam" / "product-box-policy.json"
BOOTSTRAP = ROOT / "deploy" / "iam" / "product_bootstrap.sh"
NS, ENV, ACCOUNT = "acmeport", "staging", "123456789012"
MEDIA, BACKUPS = f"{NS}-{ENV}-{ACCOUNT}-media", f"{NS}-{ENV}-{ACCOUNT}-backups"
BARE = re.compile(rf"--bucket {NS}-{ENV}-(media|backups)(\s|$)")

# One world per test: STUB_HAVE names what already exists, STUB_LOG records every call.
AWS_STUB = """#!/usr/bin/env bash
argv="$*"
printf '%s\\n' "$argv" >>"$STUB_LOG"
have() { case " ${STUB_HAVE:-} " in *" $1 "*) return 0 ;; esac; return 1; }
case "$argv" in
*"sts get-caller-identity"*) echo "123456789012" ;;
*"ec2 describe-vpcs"*) echo "vpc-0drive" ;;
*"ec2 describe-security-groups"*)
    if have sg; then case "$argv" in *-web*) echo "sg-foundweb" ;; *) echo "sg-founddb" ;; esac
    else echo "None"; fi ;;
*"ec2 create-security-group"*)
    case "$argv" in *-web*) echo "sg-newweb" ;; *) echo "sg-newdb" ;; esac ;;
*"ec2 authorize-security-group-ingress"*) ;;
*"ec2 describe-key-pairs"*)
    have nokey && { echo "InvalidKeyPair.NotFound" >&2; exit 254; }
    echo "drive-key" ;;
*"rds describe-db-instances"*"Endpoint"*) echo "db.drive.invalid" ;;
*"rds describe-db-instances"*)
    have rds || { echo "An error occurred (DBInstanceNotFound)" >&2; exit 254; }
    echo "creating" ;;
*"rds create-db-instance"*) ;;
*"rds wait db-instance-available"*) ;;
*"s3api head-bucket"*)
    case "$argv" in *-123456789012-*) ;; *)
        echo "An error occurred (404) bare name" >&2; exit 254 ;; esac
    have buckets && exit 0
    echo "An error occurred (404) when calling the HeadBucket operation: Not Found" >&2; exit 254 ;;
*"s3api create-bucket"*)
    case "$argv" in *-123456789012-*) ;; *)
        echo "An error occurred (BucketAlreadyExists) when calling the CreateBucket operation" >&2
        exit 254 ;; esac
    if have collide; then
        echo "An error occurred (BucketAlreadyExists) when calling the CreateBucket operation" >&2
        exit 254
    fi ;;
*"s3api put-"*) ;;
*"ssm get-parameters"*) echo "ami-0drive" ;;
*"ec2 describe-instances"*) have instance && echo "i-0found" ;;
*"ec2 run-instances"*) ;;
*)
    echo "stub aws: REFUSING an unexpected call: $argv" >&2
    exit 99 ;;
esac
exit 0
"""

CONFIRMED = {
    "DJB_DEPLOY_NAMESPACE": NS,
    "AWS_REGION": "us-east-1",
    "DJB_OWNER_IP": "203.0.113.7",
    "DJB_KEY_NAME": "drive-key",
    "POSTGRES_USER": "drive",
    "POSTGRES_PASSWORD": "drive-not-a-secret",  # pragma: allowlist secret
    "DATABASE_NAME": "djb_staging",
    "DJB_INSTANCE_PROFILE": f"{NS}-{ENV}-box",
}


@pytest.fixture
def infra(
    scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> Callable[..., tuple[Captured, list[str]]]:
    """`infra(have, *argv, **env)` runs `provision.sh infra staging <argv>` in the world `have`."""
    if not PROVISION.is_file():
        raise CouldNotLook(f"{PROVISION} is not in this tree")
    stub_path.plant("aws", AWS_STUB)
    log = scratch / "aws.calls"

    def run(have: str, *argv: str, **over: str) -> tuple[Captured, list[str]]:
        log.write_text("")
        env = {
            **CONFIRMED,
            **over,
            "PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(log),
            "STUB_HAVE": have,
        }
        got = capture([str(PROVISION), "infra", ENV, *argv], env=env)
        return got, log.read_text().splitlines()

    return run


def test_the_summary_names_the_account_qualified_buckets(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("")
    text = run.text()
    assert run.rc == 2, text
    assert f"s3://{MEDIA}" in text and f"s3://{BACKUPS}" in text, text
    assert "refusing without --confirm" in text
    assert [c for c in calls if "create-" in c or "run-instances" in c] == [], calls


def test_a_fresh_world_is_created_and_the_bare_name_is_never_asked_for(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("", "--confirm")
    text = run.text()
    assert run.rc == 0, text
    assert [c for c in calls if BARE.search(c)] == [], calls
    for needle in (
        f"created security group {NS}-{ENV}-web",
        f"created security group {NS}-{ENV}-db",
        f"created RDS {NS}-{ENV}-db",
        f"created bucket s3://{MEDIA}",
        f"created bucket s3://{BACKUPS}",
        f"created instance {NS}-{ENV}",
        "AWS_STORAGE_BUCKET_NAME=" + MEDIA,
    ):
        assert needle in text, (needle, text)
    assert sum("create-bucket" in c for c in calls) == 2, calls


def test_an_existing_world_is_found_and_nothing_is_created(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("sg rds buckets instance", "--confirm")
    text = run.text()
    assert run.rc == 0, text
    made = [c for c in calls if re.search(r" create-|run-instances|authorize-security", c)]
    assert made == [], made
    for needle in (
        f"found   security group {NS}-{ENV}-web (sg-foundweb)",
        f"found   security group {NS}-{ENV}-db (sg-founddb)",
        f"found   RDS {NS}-{ENV}-db (creating)",
        f"found   bucket s3://{MEDIA}",
        f"found   bucket s3://{BACKUPS}",
        f"found   instance {NS}-{ENV} (i-0found)",
    ):
        assert needle in text, (needle, text)
    assert any("rds wait db-instance-available" in c for c in calls), calls


def test_a_name_another_account_holds_is_refused_naming_the_global_namespace(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("collide", "--confirm")
    text = run.text()
    assert run.rc == 2, text
    assert "global" in text and "<namespace>-<env>-<account>-media" in text, text
    assert sum("create-bucket" in c for c in calls) == 1, calls
    assert [c for c in calls if BARE.search(c)] == [], calls


def test_a_missing_key_pair_is_refused_before_anything_is_made(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("nokey", "--confirm")
    text = run.text()
    assert run.rc == 2, text
    assert "drive-key" in text
    assert [c for c in calls if " create-" in c] == [], calls


def test_a_class_the_pool_table_does_not_know_is_refused_before_the_summary(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("", "--confirm", DJB_RDS_CLASS="db.r6g.large")
    text = run.text()
    assert run.rc == 2, text
    assert "deploy/pool_budget.py CLASSES" in text, text
    assert "about to CREATE" not in text, text
    assert [c for c in calls if " create-" in c or "run-instances" in c] == [], calls


def test_an_unset_owner_ip_prints_the_one_line_that_sets_it(
    infra: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = infra("", "--confirm", DJB_OWNER_IP="")
    text = run.text()
    assert run.rc == 2, text
    assert "DJB_OWNER_IP is unset" in text, text
    assert "checkip.amazonaws.com" in text, text
    assert [c for c in calls if " create-" in c] == [], calls


def test_an_empty_namespace_names_the_env_file_that_blanked_it(
    capture: Callable[..., Captured],
) -> None:
    run = capture([str(PROVISION), "infra", ENV], env={"DJB_DEPLOY_NAMESPACE": ""})
    text = run.text()
    assert run.rc == 2, text
    assert "set but EMPTY" in text and "set -a" in text, text


def test_sourcing_the_env_example_leaves_the_exported_values_intact() -> None:
    if shutil.which("bash") is None:
        raise CouldNotLook("no bash on PATH")
    script = (
        "export DJB_DEPLOY_NAMESPACE=acmeport DJB_IMAGE_REGISTRY=registry.invalid/acme; "
        'set -a; . "$1" >/dev/null 2>&1; set +a; '
        'printf "%s|%s" "$DJB_DEPLOY_NAMESPACE" "$DJB_IMAGE_REGISTRY"'
    )
    got = subprocess.run(
        ["bash", "-c", script, "drive", str(EXAMPLE)], capture_output=True, text=True, check=False
    )
    assert got.stdout == "acmeport|registry.invalid/acme", got.stdout + got.stderr
    assigned = [
        line
        for line in EXAMPLE.read_text().splitlines()
        if re.match(r"^(export\s+)?(DJB_DEPLOY_NAMESPACE|DJB_IMAGE_REGISTRY)=", line)
    ]
    assert assigned == [], assigned


def test_one_function_names_both_buckets_and_the_box_policy_reads_it() -> None:
    script = (
        'DEPLOY_NAME=drive; . "$1"; NAMESPACE=acmeport; '
        "bucket_name media staging 123456789012; echo; bucket_name backups staging 123456789012"
    )
    got = subprocess.run(
        ["bash", "-c", script, "drive", str(LIB)], capture_output=True, text=True, check=False
    )
    assert got.stdout.split() == [MEDIA, BACKUPS], got.stdout + got.stderr
    statements = json.loads(POLICY.read_text())["Statement"]
    s3 = sorted(r for s in statements for r in s["Resource"] if r.startswith("arn:aws:s3"))
    assert s3 == sorted(
        f"arn:aws:s3:::${{{k}_BUCKET}}{tail}" for k in ("MEDIA", "BACKUPS") for tail in ("", "/*")
    ), s3
    source = BOOTSTRAP.read_text()
    for kind in ("media", "backups"):
        assert f'bucket_name {kind} "$ENVIRONMENT" "$ACCOUNT"' in source, kind


HASH = "$2a$14$" + "stub" * 5 + "stuO" + "stub" * 7 + "stu"
DOCKER_STUB = f"""#!/usr/bin/env bash
case "$*" in *hash-password*) echo '{HASH}' ;; esac
exit 0
"""


@pytest.mark.parametrize("exported", ["", NS])
def test_env_file_writes_the_namespace_it_knows_and_never_an_empty_one(
    exported: str, scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> None:
    stub_path.plant("docker", DOCKER_STUB)
    out = scratch / "staging.env"
    env = {
        "PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
        "DJB_DOMAIN": "example.test",
        "DJB_DEPLOY_NAMESPACE": exported,
        "DJB_IMAGE_REGISTRY": "",
    }
    run = capture(["./deploy/provision.sh", "env-file", str(out), "staging"], cwd=ROOT, env=env)
    assert run.rc == 0, run.text()
    lines = out.read_text().splitlines()
    empty = [x for x in lines if re.match(r"^(DJB_DEPLOY_NAMESPACE|DJB_IMAGE_REGISTRY)=(''|)$", x)]
    assert empty == [], empty
    written = [x for x in lines if x.startswith("DJB_DEPLOY_NAMESPACE=")]
    assert written == ([f"DJB_DEPLOY_NAMESPACE='{NS}'"] if exported else []), written
