"""The `nested_pytest` fixture: a planted test tree run under this harness in a separate process."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent.parent


def run_tree(
    tree: Path,
    root: Path,
    files: Mapping[str, str],
    env: Mapping[str, str] | None = None,
    workers: int = 0,
) -> tuple[int, str]:
    """Plant `files` beside copies of the conftest and fixtures; pytest them under `root`."""
    tree.mkdir(parents=True)
    shutil.copy(HARNESS / "conftest.py", tree / "conftest.py")
    shutil.copytree(
        HARNESS / "fixtures",
        tree / "fixtures",
        ignore=shutil.ignore_patterns("__pycache__", "__init__.py"),
    )
    for name, text in files.items():
        (tree / name).parent.mkdir(parents=True, exist_ok=True)
        (tree / name).write_text(text)
    config = root / "pyproject.toml"
    if not config.exists():
        shutil.copy(HARNESS.parent.parent / "pyproject.toml", config)
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "DJB_GATE_"))}
    sink = tree.parent / f"{tree.name}.out"
    with sink.open("wb") as out:
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-c",
                str(config),
                "-p",
                "no:django",
                "-p",
                "no:randomly",
                "-p",
                "no:cacheprovider",
                "-n",
                str(workers),
                "-W",
                "ignore::pytest.PytestConfigWarning",
                "-q",
                str(tree),
            ],
            cwd=tree,
            stdout=out,
            stderr=subprocess.STDOUT,
            env={**clean, "PYTHONPATH": str(HARNESS.parent.parent), **(env or {})},
        )
    return done.returncode, sink.read_text(errors="replace")


@pytest.fixture
def nested_pytest(scratch: Path) -> Callable[..., tuple[int, str]]:
    """`nested_pytest(files, root=…, env=…, workers=…)` answers the run's exit and output."""
    count = 0

    def run(
        files: Mapping[str, str],
        root: Path | None = None,
        env: Mapping[str, str] | None = None,
        workers: int = 0,
    ) -> tuple[int, str]:
        nonlocal count
        count += 1
        home = root if root is not None else scratch / f"root-{count}"
        home.mkdir(parents=True, exist_ok=True)
        return run_tree(scratch / f"tree-{count}", home, files, env, workers)

    return run
