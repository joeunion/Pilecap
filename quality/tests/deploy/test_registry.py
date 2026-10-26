"""Build once, promote by digest (ADR deploy-4), against a real `registry:2` and a buildx builder.

does-not-cover: whether this repository's Dockerfile builds for arm64 — CI's images job does.
does-not-cover: ECR itself — authentication, IAM, immutable-tag policy, lifecycle rules.
does-not-cover: the push credential, and whether the pushed image runs.
does-not-cover: registry availability as a deploy-time dependency (ADR deploy-4 accepts it).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "deploy/provision.sh", "Dockerfile", "compose.yaml", ".github/workflows/ci.yml"
)

ROOT = Path(__file__).resolve().parents[3]
PROVISION = ROOT / "deploy" / "provision.sh"
TAG = "tree-000000000001"
DOCKERFILE = 'FROM busybox:1.37.0\nARG MARK=one\nRUN echo "$MARK" >/mark\n'


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    """`docker <args>`, both streams captured."""
    return subprocess.run(["docker", *args], capture_output=True, text=True)


@dataclass(frozen=True)
class Registry:
    """A scratch registry on loopback and a docker-container builder that can push to it."""

    address: str
    builder: str
    work: Path

    def provision(self, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
        """`deploy/provision.sh <args>` with `DJB_IMAGE_REGISTRY` naming this registry."""
        return subprocess.run(
            [str(PROVISION), *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            env={**os.environ, "DJB_IMAGE_REGISTRY": self.address},
        )

    def answer(self, *args: str, cwd: Path = ROOT) -> str:
        """The stdout of a provision call that must succeed."""
        done = self.provision(*args, cwd=cwd)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()

    def push(self, service: str, mark: str, tag: str = TAG) -> None:
        """Build the two-line image for amd64 and arm64 and push it under `djb-<service>:<tag>`."""
        ref = self.answer("image-ref", service, tag)
        with (self.work / "build.log").open("a") as log:
            done = subprocess.run(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--builder",
                    self.builder,
                    "--platform",
                    "linux/amd64,linux/arm64",
                    "--build-arg",
                    f"MARK={mark}",
                    "--provenance=false",
                    "--tag",
                    ref,
                    "--push",
                    str(self.work),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        assert done.returncode == 0, f"the push of {ref} failed — see {self.work / 'build.log'}"

    def inspect(self, ref: str, template: str) -> str:
        """`docker buildx imagetools inspect --format <template> <ref>`."""
        done = docker("buildx", "imagetools", "inspect", "--format", template, ref)
        assert done.returncode == 0, done.stderr
        return done.stdout.strip()


@pytest.fixture(scope="module")
def registry(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Registry]:
    """One registry, one builder and one build context for the module, all removed at teardown."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no 'docker' on PATH")
    if docker("buildx", "version").returncode != 0:
        raise CouldNotLook("no 'docker buildx' — a manifest list cannot be built without it")
    if docker("info").returncode != 0:
        raise CouldNotLook("the container daemon is not answering")
    if not os.access(PROVISION, os.X_OK):
        raise CouldNotLook("deploy/provision.sh is not in this tree — there is nothing to drive")
    work = require_scratch(tmp_path_factory.mktemp("registry"), ROOT)
    ident = f"djbregport{uuid.uuid4().hex[:12]}"
    started = docker("run", "-d", "--name", ident, "-P", "registry:2")
    if started.returncode != 0:
        raise CouldNotLook(f"could not start a 'registry:2' container: {started.stderr.strip()}")
    try:
        port = docker("port", ident, "5000/tcp").stdout.splitlines()
        if not port:
            raise CouldNotLook("the scratch registry published no port")
        address = f"127.0.0.1:{port[0].rsplit(':', 1)[1]}"
        for _ in range(40):
            try:
                with urllib.request.urlopen(f"http://{address}/v2/", timeout=2):
                    break
            except OSError:
                time.sleep(0.25)
        else:
            raise CouldNotLook(f"the scratch registry at {address} never answered /v2/")
        (work / "buildkitd.toml").write_text(
            f'[registry."{address}"]\n  http = true\n  insecure = true\n'
        )
        made = docker(
            "buildx",
            "create",
            "--name",
            ident,
            "--driver",
            "docker-container",
            "--driver-opt",
            "network=host",
            "--config",
            str(work / "buildkitd.toml"),
        )
        if made.returncode != 0:
            raise CouldNotLook("could not create a docker-container buildx builder")
        if docker("buildx", "inspect", "--bootstrap", ident).returncode != 0:
            raise CouldNotLook("the scratch buildx builder would not start")
        (work / "Dockerfile").write_text(DOCKERFILE)
        yield Registry(address, ident, work)
    finally:
        docker("rm", "-f", ident)
        docker("buildx", "rm", ident)


@pytest.fixture(scope="module")
def web(registry: Registry) -> str:
    """The web image pushed once at `TAG`; its reference."""
    registry.push("web", "one")
    return registry.answer("image-ref", "web", TAG)


@pytest.fixture
def provision(registry: Registry, capture: Callable[..., Captured]) -> Callable[..., Captured]:
    """`provision(*args)` captures one provision call with this registry configured."""

    def run(*args: str) -> Captured:
        return capture([str(PROVISION), *args], env={"DJB_IMAGE_REGISTRY": registry.address})

    return run


def test_the_reference_is_composed_and_never_typed(registry: Registry) -> None:
    assert registry.answer("image-repo", "web") == f"{registry.address}/djb-web"
    assert registry.answer("image-ref", "web", TAG) == f"{registry.address}/djb-web:{TAG}"
    assert registry.answer("image-ref", "worker", TAG) == f"{registry.address}/djb-worker:{TAG}"


def test_an_unknown_service_is_refused_rather_than_composed(
    provision: Callable[..., Captured],
) -> None:
    run = provision("image-ref", "caddy", TAG)
    text = run.text()
    assert run.rc == 2, text
    assert "web worker" in text
    assert f":{TAG}" not in text, "image-ref printed a half-composed name after refusing"


def test_an_empty_registry_slot_is_a_refusal_and_not_a_guess(
    capture: Callable[..., Captured],
) -> None:
    run = capture(["env", "-u", "DJB_IMAGE_REGISTRY", str(PROVISION), "image-ref", "web", TAG])
    text = run.text()
    assert run.rc == 2, text
    assert "DJB_IMAGE_REGISTRY is empty" in text


def test_a_tag_the_registry_lacks_is_exit_two_and_not_an_empty_digest(
    registry: Registry, provision: Callable[..., Captured]
) -> None:
    run = provision("image-digest", "web", "tree-ffffffffffff")
    text = run.text()
    assert run.rc == 2, text
    assert f"{registry.address}/djb-web:tree-ffffffffffff" in text


def test_one_build_pushes_a_manifest_carrying_both_architectures(
    registry: Registry, web: str
) -> None:
    platforms = registry.inspect(
        web, "{{range .Manifest.Manifests}}{{.Platform.OS}}/{{.Platform.Architecture}} {{end}}"
    )
    assert "linux/amd64" in platforms
    assert "linux/arm64" in platforms


def test_the_digest_read_back_is_the_index_and_not_one_architectures(
    registry: Registry, web: str
) -> None:
    digest = registry.answer("image-digest", "web", TAG)
    assert digest.startswith("sha256:"), digest
    assert digest == registry.inspect(web, "{{json .Manifest.Digest}}").strip('"')


def test_the_same_tag_resolves_to_the_same_digest_from_anywhere(
    registry: Registry, web: str, scratch: Path
) -> None:
    first = registry.answer("image-digest", "web", TAG)
    assert registry.answer("image-digest", "web", TAG, cwd=scratch) == first


def test_re_pushing_different_content_under_one_tag_changes_the_digest(
    registry: Registry,
) -> None:
    tag = "tree-000000000002"
    registry.push("web", "one", tag)
    before = registry.answer("image-digest", "web", tag)
    registry.push("web", "two", tag)
    after = registry.answer("image-digest", "web", tag)
    assert before != after, "a re-push with different content kept its digest"


def test_the_worker_is_its_own_repository(registry: Registry, web: str) -> None:
    registry.push("worker", "worker")
    assert registry.answer("image-digest", "web", TAG) != registry.answer(
        "image-digest", "worker", TAG
    )


#: A `docker` whose `imagetools inspect` answers the way buildx does for each status.
DOCKER_STUB = """#!/usr/bin/env bash
case "$STUB_ANSWER" in
401) echo "ERROR: unexpected status from HEAD request to ${*: -1}: 401 Unauthorized" >&2 ;;
404) echo "ERROR: ${*: -1}: not found" >&2 ;;
esac
exit 1
"""
#: (the stub's status, the account, the tag): a `401` inside an id is never the status.
DIGEST_CASES = [
    ("401", "123456789012", TAG),
    ("404", "123456789012", TAG),
    ("404", "123401789012", TAG),
    ("404", "123456789012", "tree-401000000000"),
]


@pytest.mark.parametrize(("answer", "account", "tag"), DIGEST_CASES)
def test_a_daemon_not_logged_in_is_told_apart_from_a_missing_tag(
    stub_path: StubPath, capture: Callable[..., Captured], answer: str, account: str, tag: str
) -> None:
    ecr = f"{account}.dkr.ecr.us-west-2.amazonaws.com"
    stub_path.plant("docker", DOCKER_STUB)
    env = {
        "PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}",
        "DJB_IMAGE_REGISTRY": f"{ecr}/acmeport",
        "STUB_ANSWER": answer,
    }
    run = capture([str(PROVISION), "image-digest", "web", tag], env=env)
    text = run.text()
    assert run.rc == 2, text
    login = (
        f"the daemon is not logged in to {ecr}: aws ecr get-login-password --region us-west-2"
        f" | docker login --username AWS --password-stdin {ecr}"
    )
    missing = f"the registry has no {ecr}/acmeport/djb-web:{tag}"
    assert (login in text, missing in text) == (answer == "401", answer == "404"), text
