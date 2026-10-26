"""The `collection_world` fixture: a worktree of HEAD with the collection world; its reader."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.checkout import add_checkout, remove_checkout
from quality.tests.fixtures.scratch import require_scratch

WORLD_DIR = "quality/tests/fixtures/collection_world"
#: The world collects 57 items and its smallest app 10, so 50 fails when any one app goes missing.
WORLD_FLOOR = 50
#: A narrowed selection's floor: refuses the narrowing that deselected nearly everything.
WORLD_NARROWED_FLOOR = 10
#: Concurrent collections at most; a share of the box, never a claim on it.
COLLECT_MAX = 4


@dataclass(frozen=True)
class Collection:
    """One `--collect-only`: its exit, and the file both streams went to."""

    rc: int
    path: Path

    def text(self) -> str:
        return self.path.read_text(errors="replace") if self.path.is_file() else ""

    def ids(self, floor: int | None = None) -> list[str]:
        """The sorted node ids; `CouldNotLook` on a failed, empty or under-floor collection."""
        text = self.text()
        if self.rc != 0:
            errors = [
                x for x in text.splitlines() if x.startswith(("ERROR", "E  ", "INTERNALERROR"))
            ]
            tail = [x for x in text.splitlines() if x.strip()][-5:]
            raise CouldNotLook(
                f"a --collect-only exited {self.rc} ({self.path}) — pytest's own error line(s):\n"
                + "\n".join(errors[:5] + ["its last lines:", *tail])
            )
        if not text:
            raise CouldNotLook(f"a --collect-only exited 0 and printed nothing ({self.path})")
        ids = sorted(x for x in text.splitlines() if "::" in x)
        if floor is not None and len(ids) < floor:
            raise CouldNotLook(
                f"the collection in {self.path} held {len(ids)} item(s), under the floor of {floor}"
                " this caller is a claim about — the fixture world did not install, or an app of it"
                " is gone, and every union would be vacuously equal"
            )
        return ids


@dataclass(frozen=True)
class World:
    """The installed world: its checkout, its derived pytest targets, and a sink directory."""

    root: Path
    targets: tuple[str, ...]
    sinks: Path

    def env(self) -> dict[str, str]:
        return {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "DJB_GATE_"))}

    def pytest(self, name: str, args: Sequence[str]) -> Collection:
        """`python -m pytest <args>` in the world, both streams to `<sinks>/<name>.out`."""
        sink = self.sinks / f"{name}.out"
        with sink.open("wb") as out:
            done = subprocess.run(
                [str(self.root / ".venv/bin/python"), "-m", "pytest", *args],
                cwd=self.root,
                stdout=out,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=self.env(),
            )
        return Collection(done.returncode, sink)

    def collect(
        self, runs: Mapping[str, Sequence[str]], targets: Sequence[str] | None = None
    ) -> dict[str, Collection]:
        """Each named flag set collected over `targets` (the whole world), at most four at once."""
        over = list(self.targets if targets is None else targets)

        def one(item: tuple[str, Sequence[str]]) -> tuple[str, Collection]:
            name, flags = item
            args = ["--collect-only", "-q", "-p", "no:cacheprovider", *flags, *over]
            return name, self.pytest(name, args)

        with ThreadPoolExecutor(max_workers=COLLECT_MAX) as pool:
            return dict(pool.map(one, runs.items()))


def world_labels(root: Path) -> list[str]:
    """The world's app labels, derived from its directory."""
    return sorted(p.name for p in (root / WORLD_DIR / "apps").iterdir() if p.is_dir())


@pytest.fixture(scope="module")
def collection_world(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> Iterator[World]:
    """A detached worktree of HEAD, `.venv` lent, the world installed by its own `install.sh`."""
    root = request.config.rootpath
    venv = root / ".venv"
    if not (venv / "bin" / "python").exists():
        raise CouldNotLook(f"collection_world: {venv} has no interpreter to lend")
    base = require_scratch(tmp_path_factory.mktemp("world"), root).resolve()
    dest = add_checkout(root, base / "mirror")
    (dest / ".venv").symlink_to(venv)
    installed = subprocess.run(
        [
            "bash",
            "-c",
            '. "$COLLECTION_WORLD_DIR/install.sh" && world_install "$1"',
            "-",
            str(dest),
        ],
        env={**os.environ, "COLLECTION_WORLD_DIR": str(root / WORLD_DIR)},
        capture_output=True,
        text=True,
    )
    if installed.returncode != 0:
        remove_checkout(root, dest)
        raise CouldNotLook(f"collection_world: world_install exited {installed.returncode}")
    targets = [f"apps/{label}" for label in world_labels(root)]
    targets += sorted(f"apps/{p.name}" for p in (root / WORLD_DIR / "apps_root").glob("test_*.py"))
    sinks = base / "sinks"
    sinks.mkdir()
    yield World(dest, tuple(targets), sinks)
    remove_checkout(root, dest)
