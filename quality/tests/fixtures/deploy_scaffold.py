"""The `deploy_scaffold` fixture: what a deploy script sources beside itself, copied into scratch.

does-not-cover: a file a deploy script starts sourcing outside `SCAFFOLD_FILES` — it dies loudly.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.scratch import require_scratch

#: `deploy/tests/scaffold.sh`'s `DEPLOY_SCAFFOLD_FILES`, the same set at the same relative paths.
SCAFFOLD_FILES = (
    "scripts/bash_only.sh",
    "scripts/gate_refuse.sh",
    "scripts/ci_stack.sh",
    "scripts/db.sh",
    "deploy/lib.sh",
    "deploy/envfile.py",
)
_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=")


def dotenv_names(path: Path) -> tuple[str, ...]:
    """The names `path` assigns; none when it is absent."""
    if not path.is_file():
        return ()
    found = (_ASSIGNMENT.match(line) for line in path.read_text().splitlines())
    return tuple(match.group(1) for match in found if match)


def environ_without_dotenv(checkout: Path) -> dict[str, str]:
    """This process's environment less every name `checkout`'s `.env` assigns."""
    dropped = set(dotenv_names(checkout / ".env"))
    return {name: value for name, value in os.environ.items() if name not in dropped}


@dataclass(frozen=True)
class DeployScaffold:
    """This checkout's scaffold set, copied on request into a scratch deployment."""

    checkout: Path

    def into(self, root: Path | str, *extra: str) -> Path:
        """Copy the set and `extra` into `root`; `CouldNotLook` on an unsafe root or absent file."""
        target = require_scratch(root, self.checkout).resolve()
        for relative in (*SCAFFOLD_FILES, *extra):
            source = self.checkout / relative
            if not source.is_file():
                raise CouldNotLook(f"deploy_scaffold: {relative} is not in {self.checkout}")
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return target


@pytest.fixture
def deploy_scaffold(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> DeployScaffold:
    """The scaffold for this checkout, with every name its `.env` assigns unset for the test."""
    checkout = request.config.rootpath
    for name in dotenv_names(checkout / ".env"):
        monkeypatch.delenv(name, raising=False)
    return DeployScaffold(checkout)
