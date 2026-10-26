"""The image's file set imports with no gate in it, and its dev-only commands refuse by name."""

# does-not-cover: a gate read inside a function the import never calls — the census reads source.
# does-not-cover: Docker's own matcher — `image_files` re-implements the patterns this tree uses.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

pytestmark = pytest.mark.drives(
    ".dockerignore",
    "pyproject.toml",
    "manage.py",
    "apps/core/apps.py",
    "apps/core/management/commands/declare.py",
    "apps/core/management/commands/newapp.py",
    "apps/core/management/commands/roads.py",
    "apps/core/management/commands/scaffold.py",
)

ROOT = Path(__file__).resolve().parents[2]
DEV_ONLY_COMMANDS = {
    "declare": ["acme"],
    "newapp": ["gadgets"],
    "roads": [],
    "scaffold": ["--list"],
}


def _pattern(line: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(line):
        if line.startswith("**", i):
            out, i = out + ".*", i + 2
        elif line[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif line[i] == "?":
            out, i = out + "[^/]", i + 1
        elif line[i] == "[":
            end = line.index("]", i)
            out, i = out + line[i : end + 1], end + 1
        else:
            out, i = out + re.escape(line[i]), i + 1
    return re.compile(out + "(/.*)?")


def ignore_lines(root: Path = ROOT) -> list[str]:
    text = (root / ".dockerignore").read_text()
    return [s.strip() for s in text.splitlines() if s.strip() and not s.lstrip().startswith("#")]


def image_files(root: Path = ROOT) -> list[str]:
    rules = [(s.startswith("!"), _pattern(s.lstrip("!").strip("/"))) for s in ignore_lines(root)]
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout
    kept = []
    for path in filter(None, listed.split("\0")):
        excluded = False
        for negated, rule in rules:
            if rule.fullmatch(path):
                excluded = not negated
        if not excluded and (root / path).is_file():
            kept.append(path)
    return kept


def _is_runtime(rel: str) -> bool:
    parts = Path(rel).parts
    name = parts[-1]
    return (
        "tests" not in parts
        and not name.startswith("test_")
        and name != "conftest.py"
        and parts[:2] != ("apps", "testing")
    )


@pytest.fixture(scope="module")
def image(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    home = tmp_path_factory.mktemp("image")
    for rel in image_files():
        (home / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, home / rel)
    yield home


PROBE = r"""
import importlib, json, os, sys
home = sys.argv[1]
real = os.path.realpath(sys.argv[2])
sys.path[:] = [home] + [p for p in sys.path if p and os.path.realpath(p) != real]
import django
django.setup()
failed = {}
for name in json.loads(sys.argv[3]):
    try:
        importlib.import_module(name)
    except Exception as exc:
        failed[name] = f"{type(exc).__name__}: {exc}"
print(json.dumps(failed))
"""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    env.pop("PYTHONPATH", None)
    return env


def test_the_image_carries_no_gate(image: Path) -> None:
    """The copy holds `quality/`'s data files and no engine: what `.dockerignore` leaves of it."""
    shipped = sorted(
        str(p.relative_to(image)) for p in (image / "quality").rglob("*") if p.is_file()
    )
    assert shipped and all(not p.endswith(".py") for p in shipped), shipped


def test_every_runtime_module_imports_without_the_gate(image: Path) -> None:
    """Every runtime `apps/**` module the image keeps imports there, the checkout off the path."""
    modules = sorted(
        ".".join(Path(rel).with_suffix("").parts).removesuffix(".__init__")
        for rel in (str(p.relative_to(image)) for p in (image / "apps").rglob("*.py"))
        if _is_runtime(rel) and "migrations" not in Path(rel).parts
    )
    assert len(modules) > 100, modules
    done = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, str(image), str(ROOT), json.dumps(modules)],
        capture_output=True,
        text=True,
        check=False,
        cwd=image,
        env=_env(),
    )
    assert done.returncode == 0, done.stderr[-4000:]
    assert json.loads(done.stdout) == {}


@pytest.mark.parametrize("command", sorted(DEV_ONLY_COMMANDS))
def test_a_dev_only_command_refuses_in_the_image(image: Path, command: str) -> None:
    """`manage.py <dev-only command>` in the copy exits 2 with the declared sentence, untraced."""
    done = subprocess.run(
        [sys.executable, "manage.py", command, *DEV_ONLY_COMMANDS[command]],
        capture_output=True,
        text=True,
        check=False,
        cwd=image,
        env=_env(),
    )
    assert "Traceback" not in done.stderr, done.stderr[-4000:]
    assert done.returncode == 2, (done.returncode, done.stdout[-2000:], done.stderr[-2000:])
    assert "runs in a checkout, never in the image" in done.stderr, done.stderr
    assert "docs/sdk/the-one-path.md" in done.stderr, done.stderr


CONTRACT = "the product never imports the gate outside CoreConfig.DEV_ONLY"


def _planted(tmp_path: Path, module: str) -> subprocess.CompletedProcess[str]:
    doc = tomllib.loads((ROOT / "pyproject.toml").read_text())
    found = [c for c in doc["tool"]["importlinter"]["contracts"] if c["name"] == CONTRACT]
    assert len(found) == 1, f"pyproject.toml declares {len(found)} contracts named {CONTRACT!r}"
    for package in (
        "apps",
        "apps/core",
        "apps/core/management",
        "apps/core/management/commands",
        "config",
        "pilecap",
        "quality",
        "quality/engine",
    ):
        (tmp_path / package).mkdir(parents=True, exist_ok=True)
        (tmp_path / package / "__init__.py").write_text("")
    planted = tmp_path / (module.replace(".", "/") + ".py")
    planted.write_text("import quality.engine\n")
    contract = {**found[0], "unmatched_ignore_imports_alerting": "none"}
    toml = '[tool.importlinter]\nroot_packages = ["apps", "config", "quality", "pilecap"]\n\n'
    toml += "[[tool.importlinter.contracts]]\n" + "".join(
        f"{key} = {json.dumps(value)}\n" for key, value in contract.items()
    )
    (tmp_path / "pyproject.toml").write_text(toml)
    return subprocess.run(
        [str(Path(sys.executable).with_name("lint-imports")), "--no-cache"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        check=False,
    )


def test_a_planted_gate_import_in_the_product_is_refused(tmp_path: Path) -> None:
    """`apps.core.planted -> quality.engine` breaks the contract, and the refusal names the edge."""
    done = _planted(tmp_path, "apps.core.planted")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "apps.core.planted -> quality.engine" in done.stdout, done.stdout


def test_the_named_dev_only_edge_is_kept(tmp_path: Path) -> None:
    """`declare`'s gate import is the one named runtime-tree edge, so the same contract keeps it."""
    done = _planted(tmp_path, "apps.core.management.commands.declare")
    assert done.returncode == 0, done.stdout + done.stderr
    assert f"{CONTRACT} KEPT" in done.stdout, done.stdout
