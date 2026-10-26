"""Every excuse in `.secrets.baseline` still excuses a path or a line the scan reads."""

# does-not-cover: a publish export — an excuse alive only in a file the export trims reads dead.
# does-not-cover: whether an excuse is narrow — a live regex may still admit more than it needs.

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.drives(".secrets.baseline")

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ".secrets.baseline"
FILES = "detect_secrets.filters.regex.should_exclude_file"
LINES = "detect_secrets.filters.regex.should_exclude_line"
VALUES = "detect_secrets.filters.regex.should_exclude_secret"


def scanned(root: Path, excluded: list[re.Pattern[str]]) -> list[Path]:
    """The tracked files the scan reads: git's list less the baseline's file excuses."""
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    return [root / p for p in listed if p and not any(x.search(p) for x in excluded)]


def as_token(pattern: str) -> re.Pattern[str]:
    """A secret excuse anchored to the whole value, as a token found inside a line."""
    return re.compile(rf"(?<!\w){pattern.removeprefix('^').removesuffix('$')}(?!\w)")


def dead_filters(baseline: Path, root: Path) -> list[str]:
    """Each line or secret excuse that matches no line of any file the scan reads."""
    used = json.loads(baseline.read_text())["filters_used"]
    patterns = {f["path"]: f.get("pattern", []) for f in used}
    excluded = [re.compile(p) for p in patterns.get(FILES, [])]
    wanted = [(LINES, p, re.compile(p)) for p in patterns.get(LINES, [])]
    wanted += [(VALUES, p, as_token(p)) for p in patterns.get(VALUES, [])]
    alive: set[str] = set()
    for path in scanned(root, excluded):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        for _kind, pattern, found in wanted:
            if pattern not in alive and found.search(text):
                alive.add(pattern)
    return [
        f"{kind.rsplit('.', 1)[1]} {pattern}" for kind, pattern, _ in wanted if pattern not in alive
    ]


def tracked(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    return [p for p in listed if p]


def dead_paths(baseline: Path, root: Path) -> list[str]:
    """Each file excuse that matches no tracked path: the scan reads tracked files only."""
    used = json.loads(baseline.read_text())["filters_used"]
    patterns: list[str] = next((f.get("pattern", []) for f in used if f["path"] == FILES), [])
    paths = tracked(root)
    return [p for p in patterns if not any(re.search(p, path) for path in paths)]


def test_every_path_excuse_matches_a_tracked_path() -> None:
    assert dead_paths(ROOT / BASELINE, ROOT) == []


def test_a_planted_path_excuse_with_no_tracked_path_is_named(tmp_path: Path) -> None:
    data = json.loads((ROOT / BASELINE).read_text())
    dead = "^" + "zzdead" + "_excuse_dir/"
    for entry in data["filters_used"]:
        if entry["path"] == FILES:
            entry["pattern"] = [*entry["pattern"], dead]
    planted = tmp_path / BASELINE
    planted.write_text(json.dumps(data))
    assert dead_paths(planted, ROOT) == [dead]


def test_every_content_excuse_matches_a_line_the_scan_reads() -> None:
    assert dead_filters(ROOT / BASELINE, ROOT) == []


def test_a_planted_excuse_with_nothing_to_excuse_is_named(tmp_path: Path) -> None:
    data = json.loads((ROOT / BASELINE).read_text())
    dead = "^" + "ZZDEAD" + "_EXCUSE_[0-9]{9}$"
    for entry in data["filters_used"]:
        if entry["path"] == VALUES:
            entry["pattern"] = [*entry["pattern"], dead]
    planted = tmp_path / BASELINE
    planted.write_text(json.dumps(data))
    assert dead_filters(planted, ROOT) == [f"should_exclude_secret {dead}"]
