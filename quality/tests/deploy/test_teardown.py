"""`deploy/teardown.sh --all-mine` on a real docker: its sweeps' order, its loud failure, its guard.

does-not-cover: the real stack's services — two busybox services prove the control flow.
does-not-cover: `teardown.sh local`'s ownership ladder.
does-not-cover: the AWS branch beyond its two security-group deletes, driven against a stub `aws`.
does-not-cover: more than one docker version — the filters, wording and labels are the daemon's.
does-not-cover: a hand-named stack whose containers are gone; teardown.sh declares that limit.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.deploy_scaffold import DeployScaffold

pytestmark = pytest.mark.drives(
    "deploy/teardown.sh",
    "deploy/provision.sh",
    "deploy/compose.yaml",
    "compose.yaml",
    "deploy/tests/scaffold.sh",
    "scripts/tests/drive_preamble.sh",
)

BUSYBOX = "busybox:1.37.0"
COMPOSE = """services:
  keeper:
    image: busybox:1.37.0
    command: ["sh", "-c", "while true; do sleep 30; done"]
    volumes:
      - keeper_data:/data
  laptop_only:
    profiles: ["laptop"]
    image: busybox:1.37.0
    command: ["sh", "-c", "while true; do sleep 30; done"]
    volumes:
      - laptop_data:/data
volumes:
  keeper_data:
  laptop_data:
"""
STUB_AWS = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$STUB_AWS_LOG"
case "$*" in
"sts get-caller-identity "*)
    echo 123456789012
    exit 0
    ;;
"ec2 describe-instances "*)
    exit 0
    ;;
"rds describe-db-instances "*)
    if [ -n "${STUB_AWS_EXPIRED:-}" ]; then
        echo "An error occurred (ExpiredTokenException) when calling the DescribeDBInstances" \\
            "operation: The security token included in the request is expired" >&2
        exit 254
    fi
    echo "An error occurred (DBInstanceNotFound): DBInstance not found." >&2
    exit 254
    ;;
"s3api head-bucket "*)
    echo "An error occurred (404) when calling the HeadBucket operation: Not Found" >&2
    exit 254
    ;;
"secretsmanager describe-secret "*)
    echo "An error occurred (ResourceNotFoundException): can't find the specified secret." >&2
    exit 254
    ;;
"ec2 describe-security-groups "*)
    if [ -n "${STUB_AWS_SG_EXPIRED:-}" ]; then
        echo "An error occurred (RequestExpired): Request has expired." >&2
        exit 254
    fi
    args="$*"
    group="${args##*Values=}"
    echo "sg-${group%% *}"
    exit 0
    ;;
"ec2 delete-security-group "*)
    refused="$(cat "$STUB_AWS_LOG.refused" 2>/dev/null || echo 0)"
    if [ "$refused" -lt "$STUB_AWS_REFUSALS" ]; then
        echo $((refused + 1)) >"$STUB_AWS_LOG.refused"
        echo "An error occurred (DependencyViolation): resource has a dependent object" >&2
        exit 254
    fi
    exit 0
    ;;
esac
exit 255
"""
STUB_SLEEP = """#!/usr/bin/env bash
printf 'sleep %s\\n' "$*" >>"$STUB_AWS_LOG"
"""
BROKEN_DOCKER = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$DJB_TEARDOWN_DOCKER_LOG"
case "$*" in
"compose ls -a --format json")
    echo "this is not json"
    exit 0
    ;;
esac
exit 0
"""


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    """`docker <args>`, both streams kept, never raising on its exit."""
    return subprocess.run(["docker", *args], capture_output=True, text=True)


def lines(*args: str) -> list[str]:
    """The non-empty lines of `docker <args>`'s stdout."""
    return [line for line in docker(*args).stdout.splitlines() if line]


@pytest.fixture(scope="module")
def daemon() -> None:
    """A docker that answers, with the busybox image present."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no docker on PATH — this module reaps real containers")
    if docker("info").returncode != 0:
        raise CouldNotLook("docker is on PATH but not answering; nothing was driven")
    if docker("image", "inspect", BUSYBOX).returncode != 0 and docker("pull", BUSYBOX).returncode:
        raise CouldNotLook(f"could not obtain {BUSYBOX}; the cases have nothing to run")


@dataclass
class Leash:
    """Every docker object a case creates, by name, removed at teardown whatever happened."""

    projects: list[str] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)
    containers: list[str] = field(default_factory=list)

    def release(self) -> None:
        """Remove what this case made and nothing else; never docker's "all" of anything."""
        for name in self.containers:
            docker("rm", "-f", name)
        for name in self.projects:
            label = f"label=com.docker.compose.project={name}"
            ids = lines("ps", "-aq", "--filter", label)
            if ids:
                docker("rm", "-f", *ids)
            ids = lines("volume", "ls", "-q", "--filter", label)
            if ids:
                docker("volume", "rm", *ids)
            docker("network", "rm", f"{name}_default")
        for name in self.volumes:
            docker("volume", "rm", name)


@dataclass
class World:
    """Scratch checkouts: copies of `teardown.sh` and `provision.sh`, and a stub compose file."""

    base: Path
    scaffold: DeployScaffold
    capture: Callable[..., Captured]
    leash: Leash
    made: int = 0

    def checkout(self) -> Path:
        """A fresh scratch checkout, not a git one, so its derived name is its own path's."""
        self.made += 1
        root = self.scaffold.into(
            self.base / f"checkout{self.made}", "deploy/teardown.sh", "deploy/provision.sh"
        )
        for script in ("teardown.sh", "provision.sh"):
            (root / "deploy" / script).chmod(0o755)
        (root / "deploy" / "compose.yaml").write_text(COMPOSE)
        return root

    def derived(self, root: Path) -> str:
        """`provision.sh derived-project-name` for `root`."""
        done = subprocess.run(
            [str(root / "deploy" / "provision.sh"), "derived-project-name"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        if done.returncode != 0 or not done.stdout.strip():
            raise CouldNotLook(f"no derived project name for {root}: {done.stderr}")
        return done.stdout.strip()

    def stack_up(self, root: Path, project: str) -> None:
        """Bring the stub stack up under `project`."""
        self.leash.projects.append(project)
        compose = str(root / "deploy" / "compose.yaml")
        up = docker("compose", "-p", project, "-f", compose, "--profile", "laptop", "up", "-d")
        if up.returncode != 0:
            raise CouldNotLook(f"could not bring up the scratch stack {project}: {up.stderr}")

    def plant_volume(self, name: str, project: str) -> None:
        """A volume labelled as `project`'s."""
        self.leash.volumes.append(name)
        label = f"com.docker.compose.project={project}"
        if docker("volume", "create", "--label", label, name).returncode != 0:
            raise CouldNotLook(f"could not plant the volume {name}")

    def reap(self, root: Path, **extra: str) -> Captured:
        """`teardown.sh --all-mine` from `root`."""
        return self.capture(
            [str(root / "deploy" / "teardown.sh"), "--all-mine"], cwd=root, env=extra
        )


@pytest.fixture
def world(
    daemon: None, scratch: Path, capture: Callable[..., Captured], deploy_scaffold: DeployScaffold
) -> Iterator[World]:
    """The case's checkouts and its leash; the leash is released at teardown."""
    for subject in ("teardown.sh", "provision.sh"):
        if not (deploy_scaffold.checkout / "deploy" / subject).is_file():
            raise CouldNotLook(f"deploy/{subject} is not in this tree — there is nothing to drive")
    made = World(scratch.resolve(), deploy_scaffold, capture, Leash())
    try:
        yield made
    finally:
        made.leash.release()


def present(volume: str) -> bool:
    """Whether docker still has `volume`."""
    return docker("volume", "inspect", volume).returncode == 0


def state(container: str) -> str:
    """The container's state word, or empty."""
    found = lines("ps", "-a", "--filter", f"name=^{container}$", "--format", "{{.State}}")
    return found[0] if found else ""


def containers_of(project: str) -> int:
    """How many containers carry the project's label."""
    return len(lines("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"))


def volumes_of(project: str) -> int:
    """How many volumes carry the project's label."""
    return len(
        lines("volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}")
    )


def before(text: str, first: str, then: str) -> bool:
    """Whether `first` is on an earlier line of `text` than `then`."""
    numbered = text.splitlines()
    a = next((i for i, line in enumerate(numbered) if first in line), None)
    b = next((i for i, line in enumerate(numbered) if then in line), None)
    return a is not None and b is not None and a < b


def test_a_a_live_stack_is_fully_reaped(world: World) -> None:
    root = world.checkout()
    derived = world.derived(root)
    world.stack_up(root, derived)
    (root / "deploy" / ".env").write_text(f"COMPOSE_PROJECT_NAME='{derived}'\n")
    assert (containers_of(derived), volumes_of(derived)) == (2, 2)

    run = world.reap(root)
    assert run.rc == 0, run.text()
    assert f"down --volumes: {derived}" in run.text()
    assert "census AFTER:" in run.text()
    assert (containers_of(derived), volumes_of(derived)) == (0, 0)
    assert not (root / "deploy" / ".env").exists()


def test_b_the_orphan_sweep_runs_after_the_down(world: World) -> None:
    root = world.checkout()
    derived = world.derived(root)
    adopted = f"djb-adopted-{derived.removeprefix('djb_deploy_')}"
    ghost = f"{derived}_ghost"
    world.stack_up(root, adopted)
    world.plant_volume(ghost, derived)

    run = world.reap(root)
    assert run.rc == 0, run.text()
    text = run.text()
    assert f"down --volumes: {adopted}" in text
    assert "no project left to own them" in text
    assert before(text, f"down --volumes: {adopted}", "no project left to own them")
    assert "removed 1 orphaned volume(s)" in text
    assert not present(ghost)
    assert containers_of(adopted) == 0


def test_c_a_held_volume_is_loud_named_and_non_zero(world: World) -> None:
    root = world.checkout()
    derived = world.derived(root)
    held = f"{derived}_held"
    holder = f"djb-drive-holder-{derived.removeprefix('djb_deploy_')}"
    world.stack_up(root, derived)
    (root / "deploy" / ".env").write_text(f"COMPOSE_PROJECT_NAME='{derived}'\n")
    world.plant_volume(held, derived)
    world.leash.containers.append(holder)
    started = docker(
        "run", "-d", "--name", holder, "-v", f"{held}:/data", BUSYBOX,
        "sh", "-c", "while true; do sleep 30; done",
    )  # fmt: skip
    if started.returncode != 0:
        raise CouldNotLook(f"could not start the holding container {holder}")

    run = world.reap(root)
    assert run.rc == 1, run.text()
    text = run.text()
    for needle in (f"volume NOT removed: {held}", "held by", holder, "1 volume(s) survived"):
        assert needle in text, needle
    assert "census AFTER:" in text
    assert containers_of(derived) == 0
    assert not (root / "deploy" / ".env").exists()
    assert present(held)
    assert state(holder) == "running"


def test_d_a_foreign_checkouts_stack_survives(world: World) -> None:
    mine, theirs = world.checkout(), world.checkout()
    mine_name, theirs_name = world.derived(mine), world.derived(theirs)
    stray = f"djb-drive-stray-{mine_name.removeprefix('djb_deploy_')}"
    assert mine_name != theirs_name
    world.stack_up(mine, mine_name)
    world.stack_up(theirs, theirs_name)
    world.plant_volume(stray, "djb-nobody-owns-this")

    run = world.reap(mine)
    assert run.rc == 0, run.text()
    assert (containers_of(mine_name), volumes_of(mine_name)) == (0, 0)
    assert (containers_of(theirs_name), volumes_of(theirs_name)) == (2, 2)
    assert present(stray)


def test_e_nothing_of_mine_is_reported_as_nothing(world: World) -> None:
    root = world.checkout()
    run = world.reap(root)
    assert run.rc == 0, run.text()
    text = run.text()
    assert f"no compose project on this machine names {root}/deploy/compose.yaml" in text
    assert "nothing else to reap." in text
    assert f"no {root}/deploy/.env to remove" in text
    assert "census AFTER:" in text
    assert "no project left to own them" not in text


def test_f_a_docker_that_cannot_answer_exits_2(world: World, scratch: Path) -> None:
    root = world.checkout()
    log = scratch / "broken-docker.log"
    log.write_text("")
    stub = scratch / "broken-docker-bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(BROKEN_DOCKER)
    stub.chmod(0o755)

    run = world.reap(
        root, PATH=f"{stub.parent}:{os.environ['PATH']}", DJB_TEARDOWN_DOCKER_LOG=str(log)
    )
    assert run.rc == 2, run.text()
    assert "could not read 'docker compose ls'" in run.text()
    calls = log.read_text().splitlines()
    assert not [c for c in calls if "volume rm" in c or " down " in c]


def test_g_the_sweep_matches_the_derivation_not_the_adopted_name(world: World) -> None:
    root = world.checkout()
    derived = world.derived(root)
    suffix = derived.removeprefix("djb_deploy_")
    exported, adopted = f"djb-exported-{suffix}", f"djb-adopted-{suffix}"
    orphan = f"{derived}_orphan"
    (root / "deploy" / ".env").write_text(f"COMPOSE_PROJECT_NAME='{adopted}'\n")
    world.plant_volume(exported, exported)
    world.plant_volume(adopted, adopted)
    world.plant_volume(orphan, derived)

    run = world.reap(root, COMPOSE_PROJECT_NAME=exported)
    assert run.rc == 0, run.text()
    assert "removed 1 orphaned volume(s)" in run.text()
    assert not present(orphan)
    assert present(exported)
    assert present(adopted)


@dataclass
class Account:
    """A scratch deployment whose `aws` and `sleep` are stubs writing one call log."""

    root: Path
    bin: Path
    log: Path
    capture: Callable[..., Captured]

    def teardown(self, refusals: int = 0, **extra: str) -> Captured:
        """`teardown.sh staging --confirm` on the stub, refusing the first `refusals` deletes."""
        return self.capture(
            [str(self.root / "deploy" / "teardown.sh"), "staging", "--confirm"],
            cwd=self.root,
            env={
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "DJB_DEPLOY_NAMESPACE": "drive",
                "AWS_REGION": "us-east-1",
                "STUB_AWS_LOG": str(self.log),
                "STUB_AWS_REFUSALS": str(refusals),
                **extra,
            },
        )

    def calls(self, verb: str) -> list[str]:
        """The logged calls whose text contains `verb`, in order."""
        return [line for line in self.log.read_text().splitlines() if verb in line]

    def deleted(self) -> list[str]:
        """The group ids `delete-security-group` was called with, in order."""
        return [c.split("--group-id ")[1].split()[0] for c in self.calls("delete-security-group")]


@pytest.fixture
def account(
    scratch: Path, capture: Callable[..., Captured], deploy_scaffold: DeployScaffold
) -> Account:
    """A scratch copy of `teardown.sh` with the stubs first on its PATH."""
    root = deploy_scaffold.into(scratch.resolve() / "aws-checkout", "deploy/teardown.sh")
    (root / "deploy" / "teardown.sh").chmod(0o755)
    bin_dir = scratch.resolve() / "aws-bin"
    bin_dir.mkdir()
    for name, body in (("aws", STUB_AWS), ("sleep", STUB_SLEEP)):
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    log = scratch.resolve() / "aws-calls.log"
    log.write_text("")
    return Account(root, bin_dir, log, capture)


def test_h_the_db_group_goes_before_the_web_group_its_rule_names(account: Account) -> None:
    run = account.teardown()
    assert run.rc == 0, run.text()
    assert account.deleted() == ["sg-drive-staging-db", "sg-drive-staging-web"]
    buckets = "s3://drive-staging-123456789012-media, s3://drive-staging-123456789012-backups"
    assert buckets in run.text(), run.text()


def test_i_a_dependency_violation_is_retried_with_a_line(account: Account) -> None:
    run = account.teardown(refusals=1)
    assert run.rc == 0, run.text()
    text = run.text()
    retries = [line for line in text.splitlines() if "still has a dependent object" in line]
    assert len(retries) == 1, text
    assert "sg-drive-staging-db" in retries[0]
    assert account.deleted() == [
        "sg-drive-staging-db",
        "sg-drive-staging-db",
        "sg-drive-staging-web",
    ]
    assert len(account.calls("sleep ")) == 1


def test_j_a_dependency_violation_that_persists_fails_loud(account: Account) -> None:
    run = account.teardown(refusals=99)
    assert run.rc != 0, run.text()
    text = run.text()
    assert "still refuses" in text and "DependencyViolation" in text, text
    assert set(account.deleted()) == {"sg-drive-staging-db"}
    assert "done. DNS records" not in text


def test_k_a_probe_that_cannot_look_stops_the_teardown_with_awss_line(account: Account) -> None:
    run = account.teardown(STUB_AWS_EXPIRED="1")
    assert run.rc == 2, run.text()
    text = run.text()
    assert "COULD NOT LOOK — the probe for RDS drive-staging-db failed" in text, text
    assert "The security token included in the request is expired" in text, text
    assert account.calls("delete-security-group") == [], "a probe that could not look deleted on"
    assert "done. DNS records" not in text


def test_l_a_group_probe_that_cannot_look_is_never_read_as_none(account: Account) -> None:
    run = account.teardown(STUB_AWS_SG_EXPIRED="1")
    assert run.rc == 2, run.text()
    assert "Request has expired." in run.text() and "security group drive-staging-db" in run.text()
    assert account.calls("delete-security-group") == []
