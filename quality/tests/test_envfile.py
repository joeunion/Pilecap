"""`deploy/envfile.py` is the one reader and writer of a deploy env file, agreeing with `set -a`."""

# does-not-cover: docker compose's own dotenv parser — the shell is the reader asserted against.
# does-not-cover: a value outside the contract (`$` in double quotes, a backslash, a comment).
# does-not-cover: a live file an OLD writer corrupted — `--check` names it; restoring is ops'.
# does-not-cover: `secrets-put`/`secrets-fetch` against a real vault.

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "deploy/envfile.py",
    "deploy/provision.sh",
    "deploy/assert_not_published.sh",
    "deploy/teardown.sh",
)

ROOT = Path(__file__).resolve().parents[2]
ENVFILE = ROOT / "deploy/envfile.py"
SHAPES = """\
# a comment the reader skips

BARE=plain
SINGLE='single quoted'
DOUBLE="double quoted"
EXPORTED_BARE=exported
export EXPORTED_SINGLE='exported single'
export EXPORTED_DOUBLE="exported double"
HASH='$2a$14$abc.def/ghi'
EMPTY=
"""
HASH = "$2a$14$" + "stub" * 5 + "stuO" + "stub" * 7 + "stu"
HASH_STUB = f"""#!/usr/bin/env bash
case "$*" in *hash-password*) echo '{HASH}' ;; esac
exit 0
"""


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("djb_deploy_envfile", ENVFILE)
    if spec is None or spec.loader is None:
        raise CouldNotLook(f"{ENVFILE} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shell_reads(path: Path, names: list[str]) -> dict[str, str]:
    """Each name as `set -a; . file` reads it in an empty environment."""
    script = 'set -a; . "$1"; shift; for n in "$@"; do printf "%s=%s\\n" "$n" "${!n-}"; done'
    done = subprocess.run(
        ["env", "-i", "bash", "-c", script, "_", str(path), *names],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise CouldNotLook(f"the shell could not read {path}: {done.stderr}")
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


def _cli(capture: Callable[..., Captured], *args: str) -> Captured:
    return capture([sys.executable, str(ENVFILE), *args], cwd=ROOT)


def test_the_reader_and_the_shell_agree_on_every_line_shape(scratch: Path) -> None:
    path = scratch / "shapes.env"
    path.write_text(SHAPES)
    read = _module().read_env_file(str(path))
    assert len(read) == 8, read
    assert _shell_reads(path, sorted(read)) == dict(read)


def test_the_adopt_path_round_trips_a_double_quoted_password(
    scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> None:
    stub_path.plant("docker", HASH_STUB)
    old, out = scratch / "old.env", scratch / "generated.env"
    old.write_text('POSTGRES_PASSWORD="abc"\n')
    env = {"PATH": f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}"}
    run = capture(
        ["./deploy/provision.sh", "env-file", str(out), "laptop", "--adopt", str(old)],
        cwd=ROOT,
        env=env,
    )
    assert run.rc == 0, run.text()
    assert _shell_reads(out, ["POSTGRES_PASSWORD"]) == {"POSTGRES_PASSWORD": "abc"}


DOMAIN = "workbench.example.com"
NAMED = {
    "SITE_ADDRESS": "{host}",
    "AUTH_ADDRESS": "auth.{host}",
    "O11Y_ADDRESS": "o11y.{host}",
    "ALLOWED_HOSTS": "{host}",
    "CSRF_TRUSTED_ORIGINS": "https://{host}",
    "DEFAULT_FROM_EMAIL": "no-reply@{host}",
}


def _generate(
    scratch: Path, stub_path: StubPath, capture: Callable[..., Captured], env: str, domain: str
) -> tuple[Captured, Path]:
    stub_path.plant("docker", HASH_STUB)
    out = scratch / f"{env}-{domain or 'unset'}.env"
    path = f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}"
    run = capture(
        ["./deploy/provision.sh", "env-file", str(out), env],
        cwd=ROOT,
        env={"PATH": path, "DJB_DOMAIN": domain},
    )
    return run, out


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_djb_domain_names_every_host_the_way_dns_sh_does(
    env: str, scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> None:
    run, out = _generate(scratch, stub_path, capture, env, DOMAIN)
    assert run.rc == 0, run.text()
    host = f"{env}.{DOMAIN}"
    read = _module().read_env_file(str(out))
    assert {k: read[k] for k in NAMED} == {k: v.format(host=host) for k, v in NAMED.items()}
    assert [x for x in out.read_text().splitlines() if "example.invalid" in x] == []


@pytest.mark.parametrize("domain", ["", "Not A Host", "staging.example.invalid"])
def test_a_missing_or_placeholder_domain_is_refused_and_writes_nothing(
    domain: str, scratch: Path, stub_path: StubPath, capture: Callable[..., Captured]
) -> None:
    run, out = _generate(scratch, stub_path, capture, "staging", domain)
    assert run.rc != 0 and "DJB_DOMAIN" in run.text(), run.text()
    assert not out.exists()


def test_set_key_replaces_in_place_and_appends_without_reordering(
    scratch: Path, capture: Callable[..., Captured]
) -> None:
    path = scratch / "set.env"
    path.write_text('# head\nA=1\nexport B="2"\nC=3\n')
    path.chmod(0o640)
    for name, value in (("B", "two"), ("D", "four")):
        run = _cli(capture, "set", str(path), name, value)
        assert run.rc == 0, run.path.read_text()
    assert path.read_text().rstrip("\n") == "# head\nA=1\nB='two'\nC=3\nD='four'"
    assert path.stat().st_mode & 0o777 == 0o640


def test_set_key_refuses_a_single_quote_and_leaves_the_file_alone(
    scratch: Path, capture: Callable[..., Captured]
) -> None:
    path = scratch / "refuse.env"
    path.write_text("A='1'\n")
    run = _cli(capture, "set", str(path), "A", "it's")
    assert run.rc == 2 and "A contains a single quote" in run.text()
    assert path.read_text() == "A='1'\n"


def test_the_check_names_a_value_an_old_writer_rewrapped(
    scratch: Path, capture: Callable[..., Captured]
) -> None:
    path = scratch / "check.env"
    path.write_text("POSTGRES_PASSWORD='\"abc\"'\nGOOD='x'\n")
    run = _cli(capture, "--check", str(path))
    out = run.text()
    assert run.rc == 1 and "POSTGRES_PASSWORD" in out and "GOOD" not in out, out


def test_no_second_reader_of_the_file_is_left_in_deploy() -> None:
    found = []
    for pattern, paths in (
        (
            r"strip\(\"'\"\)|def parse\(|def emit\(|def read_env_file\(",
            ["deploy", ":!deploy/envfile.py"],
        ),
        (r"sed -n \"s/\^[A-Z_]+='.*\.env\"", ["deploy"]),
    ):
        done = subprocess.run(
            ["git", "-C", str(ROOT), "grep", "-nE", pattern, "--", *paths],
            capture_output=True,
            text=True,
        )
        if done.returncode > 1:
            raise CouldNotLook(f"git grep could not read deploy/: {done.stderr}")
        found.extend(done.stdout.splitlines())
    assert found == [], found
