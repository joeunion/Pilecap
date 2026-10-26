"""A guide sentence promising a mechanism cites the line that is it; its count is the tree's."""

# does-not-cover: whether a cited line IS the mechanism — the generator's anchor chose it.
# does-not-cover: the module pages (one per facade) — only the guides `reference.EXTRA` writes.

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from quality.djb import registry
from quality.sdk import reference

pytestmark = pytest.mark.drives("quality/sdk/reference.py", "deploy/provision.sh")

ROOT = Path(__file__).resolve().parents[2]
#: The words a sentence uses when it says something happens without the reader's hand.
PROMISES = re.compile(r"runs once|carries|the owner|supplies|automatically|\bCI\b")
CITATION = re.compile(r"`([\w./-]+\.\w+):(\d+)`")
NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven")
#: The registry's units that are the platform's own tests, which day zero's full gate names.
PLATFORM_UNITS = ("pytest-x2", "selftest")

#: The day the dated rows below were written; the rung that rewrites step 5 deletes them.
KNOWN_SINCE = "2026-10-19"
#: Members step 5 does not name yet; a member it names now reds until deleted.
KNOWN_UNNAMED: frozenset[str] = frozenset()


def guides() -> dict[str, str]:
    """Each guide page the generator writes, by file name."""
    pages, missing = reference.build(ROOT)
    assert not missing, missing
    return {name: pages[name] for name, _title, _render in reference.EXTRA}


def blocks(page: str) -> list[str]:
    """A page's paragraphs and list items, code fences and headings out."""
    out, fenced = [], False
    for block in re.split(r"\n(?=- |\d+\. )|\n\n", page):
        if block.lstrip().startswith("```"):
            fenced = not fenced if block.count("```") % 2 else fenced
            continue
        if not fenced and block.strip() and not block.lstrip().startswith("#"):
            out.append(block)
    return out


def test_every_promise_carries_a_citation() -> None:
    bare = []
    for name, page in guides().items():
        parts = blocks(page)
        for i, block in enumerate(parts):
            if not PROMISES.search(block) or CITATION.search(block):
                continue
            led = block.rstrip().endswith(":") and i + 1 < len(parts)
            if led and CITATION.search(parts[i + 1]):
                continue
            bare.append(f"{name}: {' '.join(block.split())[:160]}")
    assert not bare, f"a sentence promises a mechanism and cites no `file:line`: {bare}"


def test_every_citation_names_a_line_that_is_there() -> None:
    broken = []
    for name, page in guides().items():
        for path, line in CITATION.findall(page):
            file = ROOT / path
            lines = file.read_text().splitlines() if file.is_file() else []
            if not 0 < int(line) <= len(lines) or not lines[int(line) - 1].strip():
                broken.append(f"{name}: {path}:{line}")
    assert not broken, f"a citation names a line that is not there or is blank: {broken}"


def test_a_count_of_images_is_the_count_image_services_names() -> None:
    done = subprocess.run(
        ["bash", "deploy/provision.sh", "image-services"], cwd=ROOT, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    word = NUMBERS[len(done.stdout.split())]
    said = sorted(
        {
            f"{name}: {n}"
            for name, page in guides().items()
            for n in re.findall(r"\bthe (\w+) image(?:s| repositories)\b", page)
            if n != word
        }
    )
    assert not said, f"a guide counts the images otherwise than image-services ({word}): {said}"


def test_day_zero_s_full_gate_names_every_platform_test_member() -> None:
    table = registry.load(ROOT)
    members = sorted({m for unit, ms in table.rows if unit.name in PLATFORM_UNITS for m in ms})
    step = next(
        line for line in reference.day_zero_page(ROOT).splitlines() if line.startswith("5. ")
    )
    unnamed = {m for m in members if f"`{m}`" not in step}
    assert unnamed - KNOWN_UNNAMED == set(), (
        f"day zero's full gate (step 5) does not say what these platform members do on a"
        f" product: {sorted(unnamed - KNOWN_UNNAMED)}"
    )
    assert not KNOWN_UNNAMED - unnamed, (
        f"step 5 names {sorted(KNOWN_UNNAMED - unnamed)} now — delete their {KNOWN_SINCE} rows"
    )
