"""`scripts/ci_stack.sh` end to end under a stub `docker`: derive the database, bring organs up.

does-not-cover: a real compose stack going healthy — the workflows' runs are that measurement.
does-not-cover: the registry login steps before each workflow's up — actions, not this script's.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives(
    "scripts/ci_stack.sh",
    "scripts/db.sh",
    "scripts/lifecycle.sh",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly-proof.yml",
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ci_stack.sh"
UNSET = (
    "DATABASE_NAME",
    "DATABASE_NAME_SOURCE",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
)

DOCKER_STUB = """#!/usr/bin/env bash
L="$CI_STACK_DRIVE_LOG"
printf '%s | POSTGRES_DB=%s POSTGRES_USER=%s\\n' "$*" "${POSTGRES_DB:-}" "${POSTGRES_USER:-}" >>"$L"
case "$*" in
"compose exec -T db psql"*)
    cat >/dev/null
    case "$*" in *"-tA"*) exit 0 ;; esac
    exit "${CI_STACK_DRIVE_PSQL_RC:-0}"
    ;;
"compose config --services") printf '%s\\n' ${CI_STACK_DRIVE_SERVICES:-db redis} ;;
"compose config --images"*) printf '%s\\n' "${CI_STACK_DRIVE_IMAGE:-public.ecr.aws/x/mailpit:v1}" ;;
"compose pull"*)
    [ "$(grep -c '^compose pull' "$L")" -gt "${CI_STACK_DRIVE_PULL_FAILS:-0}" ] || exit 18
    ;;
"compose up -d --wait"*)
    [ "$(grep -c '^compose up -d --wait' "$L")" -gt "${CI_STACK_DRIVE_UP_FAILS:-0}" ] || exit 1
    exit "${CI_STACK_DRIVE_UP_RC:-0}"
    ;;
esac
exit 0
"""


@dataclass(frozen=True)
class Run:
    """One `ci_stack.sh` run: its capture, the stub's log and the GITHUB_ENV it wrote."""

    out: Captured
    docker_log: str
    github_env: str


@pytest.fixture
def stack(
    scratch: Path, capture: Callable[..., Captured], monkeypatch: pytest.MonkeyPatch
) -> Iterator[Callable[..., Run]]:
    """`stack(*args, **env)` runs the script with the stub `docker` first on PATH."""
    if not SCRIPT.is_file():
        raise CouldNotLook("scripts/ci_stack.sh is not in this tree — there is nothing to drive")
    bin_dir = scratch / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(DOCKER_STUB)
    docker.chmod(0o755)
    for name in UNSET:
        monkeypatch.delenv(name, raising=False)
    log, github_env = scratch / "docker.log", scratch / "github.env"

    def run(*args: str, **env: str) -> Run:
        log.write_text("")
        github_env.write_text("")
        out = capture(
            ["./scripts/ci_stack.sh", *args],
            env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "CI_STACK_DRIVE_LOG": str(log),
                "GITHUB_ENV": str(github_env),
                "DATABASE_USER": "drive_user",
                "DATABASE_PASSWORD": "drive_pw",  # pragma: allowlist secret
                "CI_STACK_RETRY_PAUSE": "0",
                **env,
            },
        )
        return Run(out, log.read_text(), github_env.read_text())

    yield run


def derived_name() -> str:
    """This checkout's database name, as `scripts/db.sh` derives it with no name set."""
    done = subprocess.run(
        [
            "env",
            "-u",
            "DATABASE_NAME",
            "bash",
            "-c",
            '. scripts/db.sh >/dev/null 2>&1; printf %s "$DATABASE_NAME"',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if not done.stdout:
        raise CouldNotLook("scripts/db.sh derived no database name for this checkout")
    return done.stdout


def test_up_derives_the_database_and_waits_on_the_named_organs(stack: Callable[..., Run]) -> None:
    want = derived_name()
    run = stack("up", "db", "redis")
    assert run.out.rc == 0, run.out.text()
    assert "compose up -d --wait db redis | POSTGRES_DB= POSTGRES_USER=drive_user" in run.docker_log
    assert re.search(
        rf"^compose exec -T db psql .*-v name={re.escape(want)} ", run.docker_log, re.M
    )
    assert f"DATABASE_NAME={want}" in run.github_env.splitlines()


def test_up_hands_compose_no_per_checkout_database(stack: Callable[..., Run]) -> None:
    run = stack("up", "db")
    assert run.out.rc == 0, run.out.text()
    assert "compose up -d --wait db | POSTGRES_DB= " in run.docker_log


def test_up_without_db_creates_nothing(stack: Callable[..., Run]) -> None:
    run = stack("up", "mailpit")
    assert run.out.rc == 0, run.out.text()
    assert "compose up -d --wait mailpit" in run.docker_log
    assert "compose exec" not in run.docker_log


def test_a_database_the_server_will_not_create_is_exit_1(stack: Callable[..., Run]) -> None:
    run = stack("up", "db", CI_STACK_DRIVE_PSQL_RC="1")
    text = run.out.text()
    assert run.out.rc == 1, text
    assert re.search(
        r"^RED: ci_stack: the db organ is healthy and .* could not be created", text, re.M
    )
    assert not re.search(r"^created database", text, re.M)


def test_with_no_service_named_the_population_is_compose_s_own(stack: Callable[..., Run]) -> None:
    run = stack("up", CI_STACK_DRIVE_SERVICES="db redis temporal")
    assert run.out.rc == 0, run.out.text()
    assert "compose config --services" in run.docker_log
    assert "compose up -d --wait db redis temporal |" in run.docker_log


def test_a_name_of_another_shape_refuses_before_anything_starts(stack: Callable[..., Run]) -> None:
    run = stack("up", "db", DATABASE_NAME="typed_by_hand")
    text = run.out.text()
    assert run.out.rc == 2, text
    assert "no derived database name" in text
    assert "compose up" not in run.docker_log


def test_an_organ_that_never_goes_healthy_is_exit_1_with_the_tail(
    stack: Callable[..., Run],
) -> None:
    run = stack("up", "db", "redis", CI_STACK_DRIVE_UP_RC="1")
    text = run.out.text()
    assert run.out.rc == 1, text
    assert re.search(r"^RED: ci_stack", text, re.M)
    assert "compose ps" in run.docker_log
    assert "compose logs --no-color --tail=200 db redis" in run.docker_log


def test_a_pull_that_fails_once_is_retried_once_and_goes_green(
    stack: Callable[..., Run],
) -> None:
    run = stack("up", "mailpit", CI_STACK_DRIVE_UP_FAILS="1")
    text = run.out.text()
    assert run.out.rc == 0, text
    assert re.search(r"^ci_stack: .* exited 1 — retrying once in 0s", text, re.M), text
    calls = [line.split(" | ")[0] for line in run.docker_log.splitlines()]
    first, second = [i for i, c in enumerate(calls) if c.startswith("compose up -d --wait")]
    assert "compose ps" in calls[first:second], f"no tail before the retry: {calls}"
    assert not re.search(r"^RED: ci_stack", text, re.M)


def test_a_pull_that_fails_twice_is_red_after_one_retry(stack: Callable[..., Run]) -> None:
    run = stack("up", "mailpit", CI_STACK_DRIVE_UP_FAILS="2")
    text = run.out.text()
    assert run.out.rc == 1, text
    assert "retrying once" in text
    assert run.docker_log.count("compose up -d --wait mailpit") == 2
    assert re.search(r"^RED: ci_stack: docker compose up --wait exited 1", text, re.M)


def test_an_image_that_will_not_pull_twice_is_could_not_look(stack: Callable[..., Run]) -> None:
    run = stack("up", "mailpit", CI_STACK_DRIVE_PULL_FAILS="2")
    text = run.out.text()
    assert run.out.rc == 2, text
    assert "could not look: public.ecr.aws/x/mailpit:v1 pull failed (public.ecr.aws)" in text
    assert run.docker_log.count("compose pull --quiet mailpit") == 2
    assert "compose up -d --wait" not in run.docker_log
    assert not re.search(r"^RED: ci_stack", text, re.M)


def test_an_image_that_pulls_on_the_retry_goes_on_up(stack: Callable[..., Run]) -> None:
    run = stack("up", "mailpit", CI_STACK_DRIVE_PULL_FAILS="1", CI_STACK_DRIVE_IMAGE="axllent/x:1")
    assert run.out.rc == 0, run.out.text()
    assert "retrying once in 0s" in run.out.text()
    assert run.docker_log.count("compose up -d --wait mailpit") == 1


@pytest.mark.parametrize(
    ("image", "registry"),
    [
        ("public.ecr.aws/x/mailpit:v1", "public.ecr.aws"),
        ("axllent/mailpit:v1", "docker.io"),
        ("redis:7", "docker.io"),
        ("localhost:5000/a:1", "localhost:5000"),
    ],
)
def test_the_registry_is_read_off_the_image(image: str, registry: str) -> None:
    done = subprocess.run(
        ["bash", "-c", f'. scripts/ci_stack.sh && ci_stack_registry "{image}"'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.stdout.strip() == registry, done.stderr


def test_an_unknown_subcommand_is_could_not_look(stack: Callable[..., Run]) -> None:
    run = stack("start")
    text = run.out.text()
    assert run.out.rc == 2, text
    assert "unknown subcommand 'start'" in text


def test_both_workflows_stand_the_stack_up_through_it() -> None:
    copies: list[str] = []
    for workflow in (".github/workflows/ci.yml", ".github/workflows/nightly-proof.yml"):
        text = (ROOT / workflow).read_text()
        calls = re.findall(
            r"\./scripts/ci_stack\.sh up db redis temporal minio meilisearch$", text, re.M
        )
        if len(calls) != 1:
            copies.append(f"{workflow}: {len(calls)} call(s) through ci_stack.sh")
        if re.search(r"docker compose up -d|^[ \t]+\. \./scripts/db\.sh", text, re.M):
            copies.append(f"{workflow}: a copy of the recipe stands")
    assert not copies, copies
