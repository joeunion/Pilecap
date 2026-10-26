"""The `scratch` fixture: the test's own directory, proven absolute and outside every checkout."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook


def require_scratch(value: str | os.PathLike[str], checkout: Path) -> Path:
    """`value` as scratch; `CouldNotLook` if empty, relative, `/`, `$HOME`, a file, or inside."""
    text = os.fspath(value)
    if not text:
        raise CouldNotLook(
            "the scratch path is empty — `git -C ''` would run wherever this process stands"
        )
    path = Path(text)
    if not path.is_absolute():
        raise CouldNotLook(f"the scratch path {text!r} is relative")
    if path == Path("/") or path == Path.home():
        raise CouldNotLook(f"the scratch path {text!r} is `/` or $HOME")
    if path.exists() and not path.is_dir():
        raise CouldNotLook(f"the scratch path {text!r} exists and is not a directory")
    real, root = path.resolve(), checkout.resolve()
    if real == root or root in real.parents:
        raise CouldNotLook(f"the scratch path {text!r} is inside the checkout {root}")
    return path


@pytest.fixture
def scratch(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    """A per-test directory under pytest's temp root, through `require_scratch`."""
    return require_scratch(tmp_path, request.config.rootpath)
