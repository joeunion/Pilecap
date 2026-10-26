"""Every ADR id the shipped tree cites has its file `docs/product/adrs/<id>.md`, headed by it."""

# does-not-cover: an id cited only in trimmed history (cycles, reports, archive) — never exported.
# does-not-cover: whether a file's text decides what its citations claim — resolution, not meaning.

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

from quality.djb.rituals import publish

ROOT = Path(__file__).resolve().parents[2]
ADRS = ROOT / "docs" / "product" / "adrs"
CITED = re.compile(r"ADR ([a-z][a-z0-9_]*(?:-[a-z][a-z0-9_]*)*-[0-9]+[a-z]?)(?![a-z0-9_-])")


@pytest.fixture(scope="module")
def citations() -> dict[str, set[str]]:
    """Every ADR id a SHIP-bucket file cites, with the files citing it."""
    found: dict[str, set[str]] = defaultdict(set)
    for rel in publish.census(ROOT).ship:
        path = ROOT / rel
        try:
            text = path.read_text()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for adr in CITED.findall(text):
            found[adr].add(rel)
    return found


def _files() -> dict[str, Path]:
    return {p.stem: p for p in sorted(ADRS.glob("*.md")) if p.name != "README.md"}


def test_every_cited_adr_id_has_its_file(citations: dict[str, set[str]]) -> None:
    assert ADRS.is_dir(), f"{ADRS.relative_to(ROOT)} does not exist: no cited id can resolve"
    files = _files()
    missing = {adr: sorted(where)[:3] for adr, where in citations.items() if adr not in files}
    print(f"{len(citations)} ids cited by the shipped tree · {len(files)} ADR files")
    assert not missing, f"ADR ids cited with no file: {missing}"


def test_files_no_citation_names_are_reported(citations: dict[str, set[str]]) -> None:
    """Reported, never red: a decision nobody cites yet is still a decision."""
    files = _files()
    uncited = [
        adr
        for adr, path in files.items()
        if not citations.get(adr, set()) - {str(path.relative_to(ROOT))}
    ]
    print(f"ADR files no other shipped file cites: {uncited}")


def test_every_adr_file_is_headed_by_its_own_id() -> None:
    wrong = {
        adr: path.read_text().split("\n", 1)[0]
        for adr, path in _files().items()
        if path.read_text().split("\n", 1)[0] != f"# ADR {adr}"
    }
    assert _files() and not wrong, f"filename is not the heading's id: {wrong}"


def test_every_rule_doc_anchor_into_the_log_resolves_where_it_points() -> None:
    """A rule whose `doc:` anchor moved with an ADR block names the file it moved to."""
    import yaml

    rules = yaml.safe_load((ROOT / "quality" / "rules.yaml").read_text())["rules"]
    log = {str(p.relative_to(ROOT)): p.read_text().lower() for p in _files().values()}
    arch = "docs/product/architecture.md"
    wrong = []
    into_log = 0
    for rule in rules:
        doc = rule.get("doc") or {}
        where, anchor = str(doc.get("file", "")), str(doc.get("contains", "")).lower()
        if where in log:
            into_log += 1
            if anchor not in log[where]:
                wrong.append((rule["id"], where, "anchor missing"))
        elif where == arch and anchor not in (ROOT / arch).read_text().lower():
            homes = [f for f, text in log.items() if anchor in text]
            wrong.append((rule["id"], where, f"anchor moved to {homes}"))
    print(f"{into_log} rule doc anchors point into the ADR log")
    assert not wrong, wrong
