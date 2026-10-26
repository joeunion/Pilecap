"""`deploy/provision.sh` over a stub docker: the name it answers with, and what `up` recreates.

does-not-cover: every other subcommand (`env-file`, `secrets-*`, `infra`, `image-tag`, …).
does-not-cover: `up`'s adoption and refusal ladder beyond the one case each property needs.
does-not-cover: what compose does — the stub records arguments and starts nothing.
does-not-cover: the box — a re-deploy's zero window is measured there with a clock, not here.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.deploy_scaffold import DeployScaffold

pytestmark = pytest.mark.drives(
    "deploy/provision.sh",
    "deploy/tests/scaffold.sh",
    "compose.yaml",
    "scripts/tests/drive_preamble.sh",
)

DERIVED = re.compile(r"^djb_deploy_[0-9a-f]{8}$", re.MULTILINE)

COMPOSE = """services:
  db:
    image: postgres:18.6
  caddy:
    image: caddy:2.10.2
  web:
    image: djb-web:tree-stubbed0000
  worker:
    image: djb-worker:tree-stubbed0000
"""

ENV_FILE = """COMPOSE_PROJECT_NAME='djb-deploy'
DJB_IMAGE_TAG='tree-stubbed0000'
SITE_ADDRESS='drive.invalid'
"""

# Compose's own order for `config --services`: the app pair sits in the middle, not at the end.
DOCKER_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"
case "$*" in
*"compose ls --format json"*)
    printf '%s' "${DJB_DRIVE_COMPOSE_LS:-[]}"
    ;;
*"image inspect"*) exit 0 ;;
*"config --services"*)
    printf '%s\\n' db web caddy worker oneoff
    ;;
*" config")
    printf '%s\\n' 'name: djb-deploy' 'services:' '  caddy:' '    restart: unless-stopped' \\
        '  db:' '    restart: unless-stopped' '  oneoff:' '    restart: "no"' \\
        '  web:' '    restart: unless-stopped' '  worker:' '    restart: unless-stopped'
    ;;
esac
exit 0
"""


@dataclass
class Deployment:
    """A scratch deployment: `provision.sh` copied, its scaffold, a TREE marker, a stub docker."""

    case: Path
    capture: Callable[..., Captured]

    @property
    def deploy(self) -> Path:
        """The deployment's `deploy/` directory."""
        return self.case / "deploy"

    @property
    def docker_log(self) -> Path:
        """Every docker invocation the stub received, in order."""
        return self.case / "docker.log"

    def argv(self, *args: str, **extra: str) -> list[str]:
        """`provision.sh <args>` with an operator's `COMPOSE_PROJECT_NAME` removed, `extra` set."""
        return [
            "env",
            "-u",
            "COMPOSE_PROJECT_NAME",
            f"PATH={self.case / 'bin'}:{os.environ['PATH']}",
            f"DJB_DRIVE_DOCKER_LOG={self.docker_log}",
            *(f"{name}={value}" for name, value in extra.items()),
            str(self.deploy / "provision.sh"),
            *args,
        ]

    def provision(self, *args: str, **extra: str) -> Captured:
        """One run, both streams captured."""
        return self.capture(self.argv(*args, **extra))

    def stdout_of(self, *args: str) -> str:
        """One run's stdout alone, newlines dropped, whatever its exit."""
        done = subprocess.run(self.argv(*args), capture_output=True, text=True, cwd=self.case)
        return done.stdout.replace("\n", "")

    def docker_saw(self, needle: str) -> int:
        """How many stub docker invocations carry `needle`."""
        return sum(needle in line for line in self.docker_log.read_text().splitlines())

    def running_here(self) -> str:
        """A compose listing saying a `djb-deploy` stack from THIS compose file is running."""
        return json.dumps(
            [
                {
                    "Name": "djb-deploy",
                    "Status": "running(4)",
                    "ConfigFiles": str(self.deploy / "compose.yaml"),
                }
            ],
            separators=(",", ":"),
        )


@pytest.fixture
def deployment(
    scratch: Path, capture: Callable[..., Captured], deploy_scaffold: DeployScaffold
) -> Deployment:
    """A fresh deployment per case; the TREE marker is the shape a real box is in (no `.git`)."""
    if not (deploy_scaffold.checkout / "deploy" / "provision.sh").is_file():
        raise CouldNotLook("deploy/provision.sh is not in this tree — there is nothing to drive")
    case = deploy_scaffold.into(scratch / "case", "deploy/provision.sh")
    made = Deployment(case, capture)
    (made.deploy / "provision.sh").chmod(0o755)
    (case / "bin").mkdir()
    made.docker_log.write_text("")
    (case / "TREE").write_text("tree-stubbed0000\n")
    (made.deploy / "compose.yaml").write_text(COMPOSE)
    (made.deploy / ".env").write_text(ENV_FILE)
    stub = case / "bin" / "docker"
    stub.write_text(DOCKER_STUB)
    stub.chmod(0o755)
    return made


def test_project_name_answers_the_adopted_name(deployment: Deployment) -> None:
    run = deployment.provision("project-name")
    assert run.rc == 0, run.text()
    assert run.text().replace("\n", "") == "djb-deploy"


def test_project_name_falls_back_to_the_derivation(deployment: Deployment) -> None:
    env_file = deployment.deploy / ".env"
    lines = env_file.read_text().splitlines(keepends=True)
    env_file.write_text("".join(x for x in lines if not x.startswith("COMPOSE_PROJECT_NAME=")))
    run = deployment.provision("project-name")
    assert run.rc == 0, run.text()
    assert len(DERIVED.findall(run.text())) == 1


def test_an_exported_name_outranks_the_env_file(deployment: Deployment) -> None:
    run = deployment.provision("project-name", COMPOSE_PROJECT_NAME="djb-drill")
    assert run.rc == 0, run.text()
    assert run.text().replace("\n", "") == "djb-drill"


def test_the_derivation_is_still_reachable_under_its_own_name(deployment: Deployment) -> None:
    run = deployment.provision("derived-project-name")
    assert run.rc == 0, run.text()
    assert len(DERIVED.findall(run.text())) == 1
    assert "djb-deploy" not in run.text()


def test_the_two_names_disagree_where_a_name_was_adopted(deployment: Deployment) -> None:
    resolved = deployment.stdout_of("project-name")
    derived = deployment.stdout_of("derived-project-name")
    assert DERIVED.fullmatch(derived), f"the derived answer is not derivation-shaped: {derived!r}"
    assert resolved != derived, (
        f"the resolved and derived names are the same string ({resolved}) — teardown.sh's "
        "ownership comparison would compare a value with itself and always agree"
    )


def test_up_does_not_recreate_the_app_pair(deployment: Deployment) -> None:
    run = deployment.provision("up", DJB_DRIVE_COMPOSE_LS=deployment.running_here())
    assert run.rc == 0, run.text()
    assert deployment.docker_saw("up -d --no-recreate web worker") == 1
    bulk = [
        line
        for line in deployment.docker_log.read_text().splitlines()
        if "up -d" in line and "--no-recreate" not in line
    ]
    assert not [line for line in bulk if re.search(r"(^| )(web|worker)( |$)", line)]
    assert len([line for line in bulk if re.search(r"(^| )db( |$)", line)]) == 1


def test_up_still_creates_the_app_pair_on_a_box_that_never_deployed(
    deployment: Deployment,
) -> None:
    run = deployment.provision("up")
    assert run.rc == 0, run.text()
    assert "no stack from this checkout is running" in run.text()
    assert deployment.docker_saw("up -d --no-recreate web worker") == 1


def test_up_says_which_of_the_three_things_happened(deployment: Deployment) -> None:
    run = deployment.provision("up", DJB_DRIVE_COMPOSE_LS=deployment.running_here())
    assert run.rc == 0, run.text()
    assert "already running, and the env file agrees" in run.text()


def test_up_never_ups_the_compose_run_door(deployment: Deployment) -> None:
    run = deployment.provision("up", DJB_DRIVE_COMPOSE_LS=deployment.running_here())
    assert run.rc == 0, run.text()
    ups = [line for line in deployment.docker_log.read_text().splitlines() if " up -d" in line]
    assert ups and not [line for line in ups if re.search(r"(^| )oneoff( |$)", line)], ups
    assert len([line for line in ups if re.search(r"(^| )caddy( |$)", line)]) == 1, ups
    assert "not upped — compose run doors: oneoff" in run.text()


RENDERED = (
    "name: p\nservices:\n"
    '  init:\n    restart: "no"\n'
    '  oneoff:\n    restart: "no"\n'
    "  zitadel:\n    depends_on:\n      init:\n        condition: service_completed_successfully\n"
    "    restart: unless-stopped\n"
    "volumes:\n  oneoff_data: {}\n"
)


def test_the_one_reader_names_the_one_shot_and_the_door(tmp_path: Path) -> None:
    lib = Path(__file__).resolve().parents[3] / "scripts/ci_stack.sh"
    done = subprocess.run(
        ["bash", "-c", f'. "{lib}" && compose_once_members'],
        input=RENDERED,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done
    assert done.stdout == "once\tinit\tzitadel\ndoor\toneoff\n", done.stdout
