"""One version: the `TEMPLATE_VERSION` file, and every reader of it agreeing.

The file is the source. Settings reads it once (`config.settings.base`'s
`version` road), and everything that reports a version — the index page, the
telemetry resource — reads the setting. `pyproject.toml` states a version too,
because a `[project]` table must; on the template that line is pinned equal to
the file here, so a release that bumps one and not the other is red at once.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from django.conf import settings

from config.settings.base import read_template_version

BASE_DIR = Path(settings.BASE_DIR)


def _the_file() -> str:
    """The version as the file states it, read here independently of the road."""
    return (BASE_DIR / "TEMPLATE_VERSION").read_text(encoding="utf-8").strip()


def test_the_setting_is_the_file() -> None:
    """`settings.TEMPLATE_VERSION` is the file's text, never a default."""
    assert settings.TEMPLATE_VERSION == _the_file()


def test_the_road_reads_the_file_it_is_handed(tmp_path: Path) -> None:
    """The road reads whatever tree it is pointed at — no cached or typed value."""
    (tmp_path / "TEMPLATE_VERSION").write_text("9.8.7\n", encoding="utf-8")
    assert read_template_version(tmp_path) == "9.8.7"


def test_the_road_refuses_a_tree_with_no_version_file(tmp_path: Path) -> None:
    """A missing file is loud at settings import, never a silent placeholder."""
    with pytest.raises(FileNotFoundError):
        read_template_version(tmp_path)


@pytest.mark.parametrize("text", ["2.5.0", "2.5.0a2", "2.5.0b1", "2.5.0rc3"])
def test_the_road_accepts_a_release_or_its_pre_release(tmp_path: Path, text: str) -> None:
    """A release and PEP 440's public pre-release (`a`, `b`, `rc`) are versions the file states."""
    (tmp_path / "TEMPLATE_VERSION").write_text(f"{text}\n", encoding="utf-8")
    assert read_template_version(tmp_path) == text


@pytest.mark.parametrize("text", ["2.5.0.1", "2.5", "abc", "v2.5.0", "2.5.0-alpha.1"])
def test_the_road_refuses_any_other_shape_with_a_sentence(tmp_path: Path, text: str) -> None:
    """Anything but `N.N.N` with an optional `a|b|rc` + digits is refused at settings import."""
    (tmp_path / "TEMPLATE_VERSION").write_text(f"{text}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="is not a version this file may state"):
        read_template_version(tmp_path)


@pytest.mark.template_only(
    reason="a product's pyproject states the PRODUCT's version; only the template's "
    "is the template's version"
)
def test_pyproject_states_the_same_version_as_the_file() -> None:
    """The `[project]` version line, the file and the setting are one value."""
    project = tomllib.loads((BASE_DIR / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == _the_file() == settings.TEMPLATE_VERSION
