"""The `deploy_scaffold` fixture: found by discovery, copying the shell scaffold's set, refusing.

does-not-cover: a deploy script sourcing a file the set lacks — its own module says so.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.deploy_scaffold import (
    SCAFFOLD_FILES,
    DeployScaffold,
    dotenv_names,
    environ_without_dotenv,
)
from quality.tests.harness import fixtures_in

pytestmark = pytest.mark.drives("deploy/tests/scaffold.sh")

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_the_fixture_is_found_by_discovery() -> None:
    assert "deploy_scaffold" in fixtures_in(FIXTURES)


def test_the_set_is_the_shell_scaffolds_set(deploy_scaffold: DeployScaffold) -> None:
    text = (deploy_scaffold.checkout / "deploy" / "tests" / "scaffold.sh").read_text()
    match = re.search(r'^DEPLOY_SCAFFOLD_FILES="([^"]*)"', text, re.MULTILINE)
    assert match is not None
    assert tuple(match.group(1).split()) == SCAFFOLD_FILES


def test_it_copies_the_set_and_the_extras_keeping_the_mode(
    deploy_scaffold: DeployScaffold, scratch: Path
) -> None:
    root = deploy_scaffold.into(scratch / "deployment", "deploy/release.sh")
    for relative in (*SCAFFOLD_FILES, "deploy/release.sh"):
        assert (root / relative).read_bytes() == (deploy_scaffold.checkout / relative).read_bytes()
    assert (root / "deploy" / "release.sh").stat().st_mode & 0o111


def test_it_refuses_a_root_inside_the_checkout(deploy_scaffold: DeployScaffold) -> None:
    with pytest.raises(CouldNotLook, match="inside the checkout"):
        deploy_scaffold.into(deploy_scaffold.checkout / "deploy-scratch")
    assert not (deploy_scaffold.checkout / "deploy-scratch").exists()


@pytest.mark.parametrize("root", ["", "relative/deployment"])
def test_it_refuses_an_empty_or_relative_root(deploy_scaffold: DeployScaffold, root: str) -> None:
    with pytest.raises(CouldNotLook):
        deploy_scaffold.into(root)


def test_it_refuses_a_file_the_checkout_does_not_have(
    deploy_scaffold: DeployScaffold, scratch: Path
) -> None:
    with pytest.raises(CouldNotLook, match="deploy/no-such-script.sh"):
        deploy_scaffold.into(scratch / "deployment", "deploy/no-such-script.sh")


def test_the_dotenv_names_are_unset(deploy_scaffold: DeployScaffold) -> None:
    names = dotenv_names(deploy_scaffold.checkout / ".env")
    assert not [name for name in names if name in os.environ]


def test_the_environment_without_the_dotenv_names(deploy_scaffold: DeployScaffold) -> None:
    names = set(dotenv_names(deploy_scaffold.checkout / ".env"))
    kept = environ_without_dotenv(deploy_scaffold.checkout)
    assert not names & set(kept)
    assert kept["PATH"] == os.environ["PATH"]
