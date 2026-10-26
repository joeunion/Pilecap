"""The `stub_path` fixture: a scratch `bin/` first on PATH, where a test plants its fakes."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook

#: What follows the stub directory on PATH: the system's own tools, never the caller's PATH.
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")


@dataclass
class StubPath:
    """One stub directory; `plant` writes an executable, `path` is the PATH that finds it first."""

    bin: Path
    planted: set[str] = field(default_factory=set)
    hidden: set[str] = field(default_factory=set)

    def plant(self, name: str, body: str) -> Path:
        """Write `name` as an executable; `CouldNotLook` on a path, a second plant, or no `#!`."""
        if not name or "/" in name or name in {".", ".."}:
            raise CouldNotLook(f"stub_path: {name!r} is not a bare command name")
        if name in self.planted:
            raise CouldNotLook(f"stub_path: {name!r} is planted twice — one world, one answer")
        if not body.startswith("#!"):
            raise CouldNotLook(
                f"stub_path: the stub {name!r} has no `#!` line, so exec cannot run it"
            )
        target = self.bin / name
        target.write_text(body)
        target.chmod(0o755)
        self.planted.add(name)
        return target

    def remove(self, name: str) -> None:
        """Take a planted stub away, so the world answers `command not found` for it."""
        if name not in self.planted:
            raise CouldNotLook(f"stub_path: {name!r} was never planted, so it cannot be removed")
        (self.bin / name).unlink()
        self.planted.discard(name)
        self.hide(name)

    def hide(self, name: str) -> None:
        """Make `name` absent from `path` on any host; `CouldNotLook` if `path` still finds it."""
        if name in self.planted:
            raise CouldNotLook(f"stub_path: {name!r} is planted — remove it, do not hide it")
        self.hidden.add(name)
        mirror = self._mirror()
        if not mirror.exists():
            mirror.mkdir()
            for directory in SYSTEM_PATH:
                tools = sorted(Path(directory).iterdir()) if Path(directory).is_dir() else []
                for tool in tools:
                    link = mirror / tool.name
                    if not link.is_symlink() and not link.exists():
                        link.symlink_to(tool)
        for gone in self.hidden:
            (mirror / gone).unlink(missing_ok=True)
        found = shutil.which(name, path=self.path)
        if found is not None:
            raise CouldNotLook(f"stub_path: {name!r} is hidden and {self.path} still finds {found}")

    def _mirror(self) -> Path:
        return self.bin.with_name(f"{self.bin.name}.system")

    @property
    def path(self) -> str:
        """The PATH a subject runs under: the stubs, then the system tools less the hidden ones."""
        if self.hidden:
            return os.pathsep.join((str(self.bin), str(self._mirror())))
        return os.pathsep.join((str(self.bin), *SYSTEM_PATH))

    def require_real(self, name: str) -> str:
        """The real `name` on the system PATH; `CouldNotLook` when absent or when it is a stub."""
        found = shutil.which(name, path=os.pathsep.join(SYSTEM_PATH))
        if found is None:
            raise CouldNotLook(f"stub_path: no real {name!r} on {os.pathsep.join(SYSTEM_PATH)}")
        return found


@pytest.fixture
def stub_path(scratch: Path) -> StubPath:
    """An empty stub directory under `scratch`."""
    directory = scratch / "bin"
    directory.mkdir()
    return StubPath(directory)
