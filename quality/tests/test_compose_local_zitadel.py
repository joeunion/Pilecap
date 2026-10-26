"""The laptop's Zitadel in the box's three-service shape, asserted over the root file's render.

does-not-cover: whether the split boots — a render proves shape; the rung's live drive booted it.
does-not-cover: a running stack keeps its old single service until the next `docker compose up`.
does-not-cover: the UID the image picks with no `user:`; the box census reads the same blind spot.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.deploy.test_compose_floor import (
    ADMIN_PREFIX,
    BOOTSTRAP_TARGET,
    BOX_FILE,
    COLD_START_WORDS,
    FIRST_PREFIX,
    LAPTOP_FILE,
    PAT_KEY,
    ROOT,
    ZITADEL_RUNNING,
    chain_to,
    derive_env,
    env_keys,
    load,
    render,
    services,
)
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives("compose.yaml", "deploy/compose.yaml")

ONE_SHOTS = ("zitadel-init", "zitadel-setup")
TLS_FLAG = re.compile(r"--tlsMode \S+")
TLS_MODES = {"laptop": "--tlsMode disabled", "box": "--tlsMode external"}


def command(block: dict[str, Any]) -> str:
    """A service's command as one string, `-` when it has none."""
    said = block.get("command")
    return " ".join(str(p) for p in said) if isinstance(said, list) else str(said or "-")


def running_findings(rendered: dict[str, Any]) -> list[str]:
    """What makes the running Zitadel more than a server: root, a cold start, a bootstrap secret."""
    block = services(rendered).get(ZITADEL_RUNNING)
    if block is None:
        return [f"no {ZITADEL_RUNNING!r} service"]
    found = []
    said = command(block)
    if not (said == "start" or said.startswith("start ")):
        found.append(f"command is {said!r}, not `start`")
    found += [f"command runs {w}" for w in COLD_START_WORDS if f" {w} " in f" {said} "]
    if "user" in block:
        found.append(f"user: {block['user']!r}")
    found += [f"holds {k}" for k in env_keys(rendered, ZITADEL_RUNNING, ADMIN_PREFIX)]
    found += [f"holds {k}" for k in env_keys(rendered, ZITADEL_RUNNING, FIRST_PREFIX)]
    if "ZITADEL_MASTERKEY" not in (block.get("environment") or {}):
        found.append("no ZITADEL_MASTERKEY to decrypt with")
    return found


def shape(rendered: dict[str, Any]) -> dict[str, tuple[str, str, str, bool]]:
    """Per Zitadel service: (command without its TLS mode, user, restart, bootstrap mounted)."""
    every = services(rendered)
    out = {}
    for name in (ZITADEL_RUNNING, *ONE_SHOTS):
        block = every.get(name) or {}
        targets = {m.get("target") for m in block.get("volumes") or []}
        out[name] = (
            TLS_FLAG.sub("--tlsMode", command(block)),
            str(block.get("user", "-")),
            str(block.get("restart", "-")),
            BOOTSTRAP_TARGET in targets,
        )
    return out


@pytest.fixture(scope="module")
def work(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The module's scratch directory; could-not-look when docker compose cannot answer."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no docker on PATH — the render is docker compose's own")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        raise CouldNotLook("docker is on PATH but 'docker compose' does not answer")
    return require_scratch(tmp_path_factory.mktemp("compose-local-zitadel"), ROOT).resolve()


def take(work: Path, source: Path, name: str) -> dict[str, Any]:
    """`source` rendered bare, every `:?` slot answered; could-not-look when it does not render."""
    env = derive_env(source, work / f"{name}.env")
    out = work / f"{name}.json"
    rc = render([source], env, out, "--project-directory", str(source.parent))
    if rc != 0:
        raise CouldNotLook(
            f"{source.name} does not render (exit {rc}): {Path(f'{out}.err').read_text()}"
        )
    return load(out)


@pytest.fixture(scope="module")
def laptop(work: Path) -> dict[str, Any]:
    """The root `compose.yaml`, rendered."""
    return take(work, LAPTOP_FILE, "laptop")


def test_the_running_zitadel_is_a_server_and_nothing_else(laptop: dict[str, Any]) -> None:
    assert running_findings(laptop) == []


def test_the_one_shots_run_as_root_hold_the_bootstrap_and_exit(laptop: dict[str, Any]) -> None:
    every = services(laptop)
    wanted = sorted({k for b in every.values() for k in (b.get("environment") or {})
                     if k.startswith(FIRST_PREFIX)})  # fmt: skip
    for name in ONE_SHOTS:
        assert name in every, f"no {name!r} service"
        block = every[name]
        assert str(block.get("restart", "-")) == "no", name
        assert str(block.get("user", "-")) == "0", name
        assert env_keys(laptop, name, ADMIN_PREFIX), name
        assert env_keys(laptop, name, FIRST_PREFIX) == wanted, name
        assert PAT_KEY in (block.get("environment") or {}), name
    assert chain_to(laptop, ZITADEL_RUNNING) == ["zitadel-setup", "zitadel-init"]
    assert command(every["zitadel-init"]) == "init"


def test_the_laptop_and_the_box_differ_only_in_the_tls_mode(
    laptop: dict[str, Any], work: Path
) -> None:
    box = take(work, BOX_FILE, "box")
    assert shape(laptop) == shape(box)
    for rendered, mode in ((laptop, TLS_MODES["laptop"]), (box, TLS_MODES["box"])):
        for name in (ZITADEL_RUNNING, "zitadel-setup"):
            assert mode in command(services(rendered)[name]), (name, mode)


def test_a_root_user_planted_on_the_running_zitadel_reds_the_census(work: Path) -> None:
    lines = LAPTOP_FILE.read_text().splitlines(keepends=True)
    at = lines.index(f"  {ZITADEL_RUNNING}:\n")
    copy = work / "planted" / "compose.yaml"
    copy.parent.mkdir(exist_ok=True)
    copy.write_text("".join([*lines[: at + 1], '    user: "0"\n', *lines[at + 1 :]]))
    assert running_findings(take(work, copy, "planted")) == ["user: '0'"]
