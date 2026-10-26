"""The stack's Docker Hub images: prefixed in `compose.yaml`, mirrored to ECR Public, pulled there.

does-not-cover: whether the mirror holds each digest now — the mirror workflow's run checks it.
does-not-cover: `deploy/compose.yaml` and `nightly-proof.yml` — they still pull Docker Hub directly.
"""

# does-not-cover: MinIO's pin, the canary's one exception — its home is the owner's decision, N2155.

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.drives(
    "compose.yaml",
    ".github/workflows/mirror-images.yml",
    ".github/workflows/ci.yml",
)

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "compose.yaml"
MIRROR_WORKFLOW = ROOT / ".github" / "workflows" / "mirror-images.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

PREFIX = "${DJB_STACK_REGISTRY:-docker.io}/"
STACK_STEP = "the stack the gate assumes (docker compose up)"
REGISTRY_STEP = "the stack's registry, the product's choice"
MINIO_LINE = re.compile(r"^\s*image:\s*(?P<alias>public\.ecr\.aws/[a-z0-9]+)/minio:", re.MULTILINE)
DERIVE_STEP = "derive the Docker Hub images compose.yaml names"
IMAGE_LINE = re.compile(r"^\s*image:\s*(?P<ref>[^\s#]+)", re.MULTILINE)
MAC_REF = re.compile(r"docker\.io/[a-z0-9._-]+/[a-z0-9._/-]+:[^@]+@sha256:[0-9a-f]{64}")
PINNED = re.compile(r"^(?P<repo>[^@]+):(?P<tag>[^:@/]+)@(?P<digest>sha256:[0-9a-f]{64})$")


def compose_refs() -> list[str]:
    """Every `image:` reference in `compose.yaml`, as written."""
    refs = [m.group("ref").strip("'\"") for m in IMAGE_LINE.finditer(COMPOSE.read_text())]
    assert refs, "compose.yaml names no image — this pin cannot look"
    return refs


def is_hub(ref: str) -> bool:
    """Docker's rule: the first segment is a registry only with a dot, a colon or `localhost`."""
    if ref.startswith(PREFIX):
        return True
    first, sep, _ = ref.split("@", 1)[0].partition("/")
    return not (sep and ("." in first or ":" in first or first == "localhost"))


def hub_refs() -> list[str]:
    return [ref for ref in compose_refs() if is_hub(ref)]


def workflow(path: Path) -> dict[Any, Any]:
    assert path.is_file(), f"{path.relative_to(ROOT)} does not exist"
    doc = yaml.safe_load(path.read_text())
    assert isinstance(doc, dict), f"{path.relative_to(ROOT)} is not a mapping"
    return doc


def find_step(doc: dict[Any, Any], name: str) -> tuple[dict[Any, Any], list[dict[Any, Any]], int]:
    """(the job, its steps, the index) of the step called `name` — exactly one in the file."""
    found = [
        (job, job.get("steps") or [], i)
        for job in (doc.get("jobs") or {}).values()
        for i, step in enumerate(job.get("steps") or [])
        if step.get("name") == name
    ]
    assert len(found) == 1, f"expected one step named {name!r}, found {len(found)}"
    return found[0]


def test_every_hub_image_carries_the_prefix_and_its_digest() -> None:
    hub = hub_refs()
    assert len(hub) >= 6, f"compose.yaml names {len(hub)} Docker Hub images; the stack has six"
    for ref in hub:
        assert ref.startswith(PREFIX), f"`{ref}` pulls Docker Hub with no `{PREFIX}` prefix"
        rest = ref[len(PREFIX) :]
        assert "/" in rest.split(":", 1)[0], f"`{ref}` names no namespace (`library/<name>`)"
        assert PINNED.match(rest), f"`{ref}` is not `<repo>:<tag>@sha256:<64 hex>`"


def test_the_default_resolves_to_the_reference_a_mac_already_pulls() -> None:
    for ref in hub_refs():
        assert ref.startswith(PREFIX), ref
        resolved = "docker.io/" + ref[len(PREFIX) :]
        assert MAC_REF.fullmatch(resolved), resolved


def test_non_hub_images_are_untouched() -> None:
    others = [ref for ref in compose_refs() if not is_hub(ref)]
    assert others, "compose.yaml names no non-Hub image — the partition this pin draws is gone"
    for ref in others:
        assert "${" not in ref, f"`{ref}` is not on Docker Hub and must not carry the stack prefix"


def the_one_alias() -> str:
    """`public.ecr.aws/<alias>` as the MinIO pin spells it — the one place it is written."""
    found = MINIO_LINE.findall(COMPOSE.read_text())
    assert len(found) == 1, f"compose.yaml's MinIO pin names {found or 'no'} ECR Public alias"
    return str(found[0])


def derivation() -> dict[str, Any]:
    _job, steps, index = find_step(workflow(MIRROR_WORKFLOW), DERIVE_STEP)
    step = steps[index]
    assert step.get("shell") == "python3 {0}", "the derivation step is not a python3 script"
    namespace: dict[str, Any] = {"__name__": "mirror_images_derivation"}
    exec(compile(step["run"], str(MIRROR_WORKFLOW), "exec"), namespace)  # noqa: S102 — runs the workflow step this repository commits, as CI would
    return namespace


@pytest.mark.template_only(
    reason="the image mirror is the template's own workflow; a product never receives it"
)
def test_the_alias_is_spelled_once() -> None:
    alias = the_one_alias().split("/", 1)[1]
    for path in (MIRROR_WORKFLOW, CI_WORKFLOW):
        assert alias not in path.read_text(), (
            f"{path.relative_to(ROOT)} spells the alias a second time"
        )


@pytest.mark.template_only(
    reason="the image mirror is the template's own workflow; a product never receives it"
)
def test_the_mirror_derivation_lists_exactly_the_hub_images() -> None:
    namespace = derivation()
    text = COMPOSE.read_text()
    mirror = namespace["mirror_registry"](text)
    assert mirror == the_one_alias()
    rows = namespace["hub_images"](text, mirror)
    expected = []
    for ref in hub_refs():
        m = PINNED.match(ref[len(PREFIX) :])
        assert m is not None, ref
        expected.append(
            {
                "source": f"docker.io/{m['repo']}@{m['digest']}",
                "mirror": f"{mirror}/{m['repo']}:{m['tag']}",
                "digest": m["digest"],
            }
        )
    got = [{k: row[k] for k in ("source", "mirror", "digest")} for row in rows]
    assert got == expected


@pytest.mark.template_only(
    reason="the image mirror is the template's own workflow; a product never receives it"
)
def test_the_mirror_workflow_pushes_to_ecr_public_on_the_compose_file() -> None:
    doc = workflow(MIRROR_WORKFLOW)
    assert doc.get("permissions", {}).get("id-token") == "write"
    assert "packages" not in doc.get("permissions", {})
    triggers = doc.get(True) or doc.get("on")  # PyYAML reads the bare key `on` as True
    assert isinstance(triggers, dict), "the mirror workflow declares no triggers"
    assert "workflow_dispatch" in triggers
    assert "compose.yaml" in triggers["push"]["paths"]
    assert triggers["push"]["branches"] == ["main"]
    copy = doc["jobs"]["copy"]["steps"]
    uses = [str(step.get("uses", "")).split("@", 1)[0] for step in copy]
    assert "aws-actions/configure-aws-credentials" in uses
    login = [
        step
        for step in copy
        if str(step.get("uses", "")).startswith("aws-actions/amazon-ecr-login@")
    ]
    assert len(login) == 1 and login[0]["with"].get("registry-type") == "public"


DOCKER_SHIM = """#!/bin/bash
printf '%s\\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"
cat >/dev/null
"""


def run_registry_step(
    tmp_path: Path, **env: str
) -> tuple[subprocess.CompletedProcess[str], str, str]:
    """(the run, what it wrote to `$GITHUB_ENV`, every docker call) for the registry step."""
    _job, steps, at = find_step(workflow(CI_WORKFLOW), REGISTRY_STEP)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_text(DOCKER_SHIM)
    (bin_dir / "docker").chmod(0o755)
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    docker_log = tmp_path / "docker.log"
    docker_log.write_text("")
    done = subprocess.run(  # noqa: S603 — the committed workflow step under test, run as CI runs it
        ["bash", "-c", steps[at]["run"]],  # noqa: S607 — `bash` from PATH, as the CI runner has it
        cwd=ROOT,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GITHUB_ENV": str(env_file),
            "DJB_DRIVE_DOCKER_LOG": str(docker_log),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return done, env_file.read_text(), docker_log.read_text()


def test_ci_chooses_the_registry_before_the_stack_and_never_from_the_minio_pin() -> None:
    ci = workflow(CI_WORKFLOW)
    job, steps, index = find_step(ci, STACK_STEP)
    assert "packages" not in (job.get("permissions") or {}), "a ghcr permission outlived the mirror"
    assert not any("docker/login-action" in str(step.get("uses", "")) for step in steps)
    _job, _steps, at = find_step(ci, REGISTRY_STEP)
    assert _job is job and at < index, "the registry is chosen after the stack comes up"
    step_env = steps[at].get("env") or {}
    assert step_env.get("STACK_REGISTRY") == "${{ vars.DJB_STACK_REGISTRY }}"
    assert step_env.get("DOCKERHUB_USERNAME") == "${{ secrets.DOCKERHUB_USERNAME }}"
    assert step_env.get("DOCKERHUB_TOKEN") == "${{ secrets.DOCKERHUB_TOKEN }}"
    assert "compose.yaml" not in steps[at]["run"], "the registry is derived from compose.yaml"
    for step in steps:
        assert "DJB_STACK_REGISTRY" not in (step.get("env") or {}), step.get("name")


def test_a_repository_variable_is_the_registry_and_nothing_logs_in(tmp_path: Path) -> None:
    done, env, docker = run_registry_step(
        tmp_path,
        STACK_REGISTRY="registry.example.com/stack",
        DOCKERHUB_USERNAME="someone",
        DOCKERHUB_TOKEN="not-a-token",  # noqa: S106 — a fake Docker Hub token the stub docker accepts  # pragma: allowlist secret
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert env == "DJB_STACK_REGISTRY=registry.example.com/stack\n"
    assert docker == ""
    assert "the repository variable DJB_STACK_REGISTRY" in done.stdout


def test_docker_hub_credentials_log_in_to_docker_hub(tmp_path: Path) -> None:
    done, env, docker = run_registry_step(
        tmp_path,
        STACK_REGISTRY="",
        DOCKERHUB_USERNAME="someone",
        DOCKERHUB_TOKEN="not-a-token",  # noqa: S106 — a fake Docker Hub token the stub docker accepts  # pragma: allowlist secret
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert env == "DJB_STACK_REGISTRY=docker.io\n"
    assert docker == "login docker.io --username someone --password-stdin\n"
    assert "not-a-token" not in done.stdout + done.stderr
    assert "logged in as someone" in done.stdout


def test_neither_is_anonymous_docker_hub_with_the_rationing_named(tmp_path: Path) -> None:
    done, env, docker = run_registry_step(
        tmp_path, STACK_REGISTRY="", DOCKERHUB_USERNAME="", DOCKERHUB_TOKEN=""
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert env == "DJB_STACK_REGISTRY=docker.io\n"
    assert docker == ""
    warnings = [line for line in done.stdout.splitlines() if line.startswith("::warning::")]
    assert len(warnings) == 1 and "anonymous" in warnings[0] and "rate" in warnings[0], done.stdout


#: The platform owner's AWS account and ECR Public alias; a product path naming either needs it.
PLATFORM_MARKS = ("050254549871", "w9i8o4b2")
PRODUCT_PATHS = ("compose.yaml", "deploy", "scripts", ".github/workflows/ci.yml")
#: The one open exception: MinIO's pin (the module's does-not-cover comment names its owner).
MINIO_EXCEPTION = re.compile(r"^\s*image:\s*public\.ecr\.aws/w9i8o4b2/minio:")


def test_no_product_path_names_the_platform_owners_registry() -> None:
    listed = subprocess.run(  # noqa: S603 — argv list to `git` over constant paths; no shell
        ["git", "ls-files", "-z", "--", *PRODUCT_PATHS],  # noqa: S607 — `git` from PATH, as the gate runs it
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\0")
    files = [ROOT / name for name in listed if name]
    assert any(path.name == "ci.yml" for path in files), (
        "the census lists no ci.yml — it cannot look"
    )
    found: list[str] = []
    excepted: list[str] = []
    for path in files:
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if not any(mark in line for mark in PLATFORM_MARKS):
                continue
            where = f"{path.relative_to(ROOT)}:{number}"
            (
                excepted if path.name == "compose.yaml" and MINIO_EXCEPTION.match(line) else found
            ).append(where)
    assert not found, f"product paths name the platform owner's registry: {found}"
    assert len(excepted) <= 1, f"the MinIO exception is one line, found {excepted}"
