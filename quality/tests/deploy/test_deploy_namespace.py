"""`DJB_DEPLOY_NAMESPACE`: every AWS coordinate is composed from it, and its absence refuses.

does-not-cover: a real account — whether the composed strings name resources that exist.
does-not-cover: `ship.sh`'s landing directory, which `quality/tests/deploy/test_ship.py` drives.
does-not-cover: the runbook's typed commands, and a coordinate added after these cases.
does-not-cover: the laptop branches (`teardown.sh local`, `provision.sh up`), which compose none.
does-not-cover: the acceptance grep that the tree spells no coordinate anywhere.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives(
    "deploy/teardown.sh",
    "deploy/provision.sh",
    "deploy/observability/alerts/apply.py",
    "deploy/dns.sh",
)

ROOT = Path(__file__).resolve().parents[3]
PROVISION = str(ROOT / "deploy" / "provision.sh")
TEARDOWN = str(ROOT / "deploy" / "teardown.sh")
APPLY = str(ROOT / "deploy" / "observability" / "alerts" / "apply.py")
# Neither is a real namespace: a real one could not tell a derivation from a hardcode.
NS_A, NS_B = "acmeport", "zebraport"
ENV_A, ENV_B = "staging", "prod"
ACCOUNT = "000000000000"

AWS_STUB = """#!/usr/bin/env bash
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
"""


@pytest.fixture
def deploy(scratch: Path, capture: Callable[..., Captured]) -> Callable[..., Captured]:
    """`deploy(ns, *argv)` runs argv with the stub `aws` first; `ns=None` removes the variable."""
    for subject in (PROVISION, TEARDOWN, APPLY):
        if not Path(subject).is_file():
            raise CouldNotLook(f"{subject} is not in this tree")
    if shutil.which("python3") is None:
        raise CouldNotLook("no python3 on PATH — apply.py is a python file")
    bin_dir = scratch / "bin"
    bin_dir.mkdir()
    (bin_dir / "aws").write_text(AWS_STUB)
    (bin_dir / "aws").chmod(0o755)
    path = f"{bin_dir}:{os.environ['PATH']}"

    def run(ns: str | None, *argv: str) -> Captured:
        if ns is None:
            return capture(["env", "-u", "DJB_DEPLOY_NAMESPACE", *argv], env={"PATH": path})
        return capture(list(argv), env={"PATH": path, "DJB_DEPLOY_NAMESPACE": ns})

    return run


def test_provision_infra_refuses_an_unset_namespace(deploy: Callable[..., Captured]) -> None:
    run = deploy(None, PROVISION, "infra", ENV_A)
    text = run.text()
    assert run.rc == 2, text
    assert "DJB_DEPLOY_NAMESPACE" in text
    assert "about to CREATE billable resources" not in text


def test_provision_infra_composes_every_coordinate_from_the_namespace(
    deploy: Callable[..., Captured],
) -> None:
    run = deploy(NS_A, PROVISION, "infra", ENV_A)
    text = run.text()
    assert run.rc == 2, text
    for needle in (
        f"s3://{NS_A}-{ENV_A}-{ACCOUNT}-media",
        f"s3://{NS_A}-{ENV_A}-{ACCOUNT}-backups",
        f"{NS_A}/{ENV_A}/env",
        "refusing without --confirm",
    ):
        assert needle in text
    run = deploy(NS_B, PROVISION, "infra", ENV_B)
    text = run.text()
    assert run.rc == 2, text
    for needle in (
        f"s3://{NS_B}-{ENV_B}-{ACCOUNT}-media",
        f"s3://{NS_B}-{ENV_B}-{ACCOUNT}-backups",
        f"{NS_B}/{ENV_B}/env",
    ):
        assert needle in text
    assert NS_A not in text


def test_backup_policy_refuses_an_unset_namespace(deploy: Callable[..., Captured]) -> None:
    run = deploy(None, PROVISION, "backup-policy", ENV_A)
    text = run.text()
    assert run.rc == 2, text
    assert "DJB_DEPLOY_NAMESPACE" in text
    assert "READ-ONLY" not in text


def test_backup_policy_composes_the_bucket_and_the_role(deploy: Callable[..., Captured]) -> None:
    run = deploy(NS_A, PROVISION, "backup-policy", ENV_A, "--check")
    text = run.text()
    assert run.rc == 0, text
    for needle in (
        f"bucket {NS_A}-{ENV_A}-{ACCOUNT}-backups",
        f"role {NS_A}-{ENV_A}-box",
        "nothing was changed",
    ):
        assert needle in text
    run = deploy(NS_B, PROVISION, "backup-policy", ENV_B, "--check")
    text = run.text()
    assert run.rc == 0, text
    assert f"bucket {NS_B}-{ENV_B}-{ACCOUNT}-backups" in text
    assert f"role {NS_B}-{ENV_B}-box" in text
    assert NS_A not in text


def test_teardown_refuses_an_unset_namespace(deploy: Callable[..., Captured]) -> None:
    run = deploy(None, TEARDOWN, ENV_A)
    text = run.text()
    assert run.rc == 2, text
    assert "DJB_DEPLOY_NAMESPACE" in text
    assert "about to DESTROY" not in text


def test_teardown_composes_every_coordinate_from_the_namespace(
    deploy: Callable[..., Captured],
) -> None:
    run = deploy(NS_A, TEARDOWN, ENV_A)
    text = run.text()
    assert run.rc == 2, text
    for needle in (
        f"about to DESTROY {NS_A}-{ENV_A}",
        f"s3://{NS_A}-{ENV_A}-{ACCOUNT}-media",
        f"s3://{NS_A}-{ENV_A}-{ACCOUNT}-backups",
        f"{NS_A}/{ENV_A}/env",
        "refusing without --confirm",
    ):
        assert needle in text
    run = deploy(NS_B, TEARDOWN, ENV_B)
    text = run.text()
    assert run.rc == 2, text
    assert f"about to DESTROY {NS_B}-{ENV_B}" in text
    assert NS_A not in text


def test_alerts_apply_refuses_an_unset_namespace(deploy: Callable[..., Captured]) -> None:
    run = deploy(None, "python3", APPLY, "--dry-run")
    text = run.text()
    assert run.rc == 2, text
    assert "DJB_DEPLOY_NAMESPACE" in text


def test_alerts_apply_composes_the_bundle_name_and_the_slot(
    deploy: Callable[..., Captured],
) -> None:
    run = deploy(NS_A, "python3", APPLY, "--dry-run")
    text = run.text()
    assert run.rc == 0, text
    assert f"{NS_A}-alerts" in text
    assert f"{NS_A}/<env>/env" in text
    run = deploy(NS_B, "python3", APPLY, "--dry-run")
    text = run.text()
    assert run.rc == 0, text
    assert f"{NS_B}-alerts" in text
    assert NS_A not in text
