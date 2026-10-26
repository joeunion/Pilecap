"""`provision.sh secrets-put` under the box role: put first, create only on a missing secret."""

# does-not-cover: a real account; throttling and 5xx answers are not modelled.

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives("deploy/provision.sh", "deploy/envfile.py")

ROOT = Path(__file__).resolve().parents[3]
PROVISION = ROOT / "deploy" / "provision.sh"
PREFIX = "acmeport/staging/"
SECRET = f"{PREFIX}env"
VALUE = "drive-not-a-secret"  # pragma: allowlist secret

# The box role: describe and create denied; STUB_PUT and STUB_CREATE pick the rest.
AWS_STUB = """#!/usr/bin/env bash
argv="$*"
printf '%s\\n' "$argv" >>"$STUB_LOG"
denied() {
    who="arn:aws:sts::123456789012:assumed-role/acmeport-staging-box/i-0drive"
    printf '%s %s %s %s\\n' \\
        "An error occurred (AccessDeniedException) when calling the $1 operation:" \\
        "User: $who is not authorized to perform: secretsmanager:$1" \\
        "on resource: acmeport/staging/env because no identity-based policy allows" \\
        "the secretsmanager:$1 action" >&2
    exit 254
}
case "$argv" in
*"secretsmanager describe-secret"*) denied DescribeSecret ;;
*"secretsmanager put-secret-value"*)
    case "${STUB_PUT:-ok}" in
    missing)
        printf '%s %s\\n' \\
            "An error occurred (ResourceNotFoundException) when calling the PutSecretValue" \\
            "operation: Secrets Manager can't find the specified secret." >&2
        exit 254 ;;
    denied) denied PutSecretValue ;;
    esac
    cat >"$STUB_LOG.put" ;;
*"secretsmanager create-secret"*)
    [ "${STUB_CREATE:-denied}" = ok ] || denied CreateSecret
    cat >"$STUB_LOG.create" ;;
*)
    echo "stub aws: REFUSING an unexpected call: $argv" >&2
    exit 99 ;;
esac
exit 0
"""


@pytest.fixture
def secrets_put(
    scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> Callable[..., tuple[Captured, list[str]]]:
    """`secrets_put(**env)` runs `provision.sh secrets-put` over a one-key env file."""
    if not PROVISION.is_file():
        raise CouldNotLook(f"{PROVISION} is not in this tree")
    stub_path.plant("aws", AWS_STUB)
    log = scratch / "aws.calls"
    env_file = scratch / "box.env"
    env_file.write_text(f"ZITADEL_PAT='{VALUE}'\n")

    def run(**over: str) -> tuple[Captured, list[str]]:
        log.write_text("")
        env = {
            **over,
            "PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(log),
        }
        got = capture([str(PROVISION), "secrets-put", PREFIX, str(env_file)], env=env)
        return got, log.read_text().splitlines()

    return run


def _ops(calls: list[str]) -> list[str]:
    return [call.split()[1] for call in calls]


def test_the_box_role_updates_an_existing_secret_without_describe_or_create(
    secrets_put: Callable[..., tuple[Captured, list[str]]], scratch: Path
) -> None:
    run, calls = secrets_put(STUB_PUT="ok")
    out = run.text()
    assert run.rc == 0, out
    assert f"updating {SECRET}" in out and f"stored: {SECRET}" in out, out
    assert "creating" not in out, out
    assert _ops(calls) == ["put-secret-value"], calls
    assert json.loads((scratch / "aws.calls.put").read_text()) == {"ZITADEL_PAT": VALUE}
    assert not any(VALUE in call for call in calls), calls


def test_a_missing_secret_is_created_once(
    secrets_put: Callable[..., tuple[Captured, list[str]]], scratch: Path
) -> None:
    run, calls = secrets_put(STUB_PUT="missing", STUB_CREATE="ok")
    out = run.text()
    assert run.rc == 0, out
    assert f"creating {SECRET}" in out and f"stored: {SECRET}" in out, out
    assert _ops(calls) == ["put-secret-value", "create-secret"], calls
    assert json.loads((scratch / "aws.calls.create").read_text()) == {"ZITADEL_PAT": VALUE}


def test_any_other_put_failure_dies_with_its_text_and_never_creates(
    secrets_put: Callable[..., tuple[Captured, list[str]]],
) -> None:
    run, calls = secrets_put(STUB_PUT="denied", STUB_CREATE="ok")
    out = run.text()
    assert run.rc != 0, out
    assert "not authorized to perform: secretsmanager:PutSecretValue" in out, out
    assert "creating" not in out and "stored:" not in out, out
    assert "create-secret" not in _ops(calls), calls
