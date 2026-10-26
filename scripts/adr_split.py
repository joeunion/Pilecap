"""Move every ADR block out of the two old homes into `docs/product/adrs/<id>.md`, one per id.

does-not-cover: an ADR stated in a sentence that opens no bold lead (it stays where it stands).
does-not-cover: a cross-reference inside a moved block ("see … above") — it moves as written.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quality.could_not_look import CouldNotLook as Refused  # noqa: E402

DOCS = "docs/product"
HOMES = (f"{DOCS}/adrs-ingredients.md", f"{DOCS}/architecture.md")
ADRS = f"{DOCS}/adrs"
ID = r"[a-z][a-z0-9_]*(?:-[a-z][a-z0-9_]*)*-[0-9]+[a-z]?"
CITED = re.compile(rf"ADR ({ID})(?![a-z0-9_-])")
OPENS = re.compile(r"^(?:- )?\*\*ADR ")
LIST = re.compile(rf"^- \*\*ADR ({ID})(?![a-z0-9_-])")
PARA = re.compile(rf"^\*\*(?:ADR ({ID})(?![a-z0-9_-])|[^*]*? — ADR ({ID}) · )")
CELL = re.compile(rf"\*\*(?:ADR ({ID}) · |(?!Amended)[^*|]*?\(ADR ({ID})[^*|]*?\):\*\*)")
STOP_BEFORE = ("Concurrency: read-modify-write",)


@dataclass
class Block:
    """One moved piece of text: its id, its source file, and the text itself."""

    id: str
    source: str
    text: str


def _starts(line: str) -> str | None:
    """The id a paragraph or list block opening on `line` carries; `Refused` if unparsable."""
    m = LIST.match(line) or PARA.match(line)
    if m:
        return next(g for g in m.groups() if g)
    if OPENS.match(line):
        raise Refused(f"a block opens with an id this grammar cannot parse: {line[:80]!r}")
    return None


def _cells(line: str) -> tuple[str, list[Block]]:
    """A table row with its ADR tails cut out, and the tails as blocks."""
    leads = list(CELL.finditer(line))
    if not line.startswith("|") or not leads:
        return line, []
    end = line.rstrip().rfind(" |")
    if end <= leads[-1].start():
        raise Refused(f"a table cell's ADR tail has no cell end: {line[:80]!r}")
    blocks, cuts = [], [m.start() for m in leads] + [end]
    for m, stop in zip(leads, cuts[1:], strict=True):
        blocks.append(Block(next(g for g in m.groups() if g), "", line[m.start() : stop].rstrip()))
    prefix = line[: leads[0].start()].rstrip()
    ids = "; ".join(f"ADR {b.id}" for b in blocks)
    keep = f"{prefix} {ids}" if prefix.endswith("|") else f"{prefix} ({ids})"
    return keep + line[end:], blocks


def split(text: str, source: str) -> tuple[str, list[Block], list[tuple[str, str]]]:
    """The text with its blocks removed, the blocks, and `(id, where)` for every citation left."""
    lines = text.split("\n")
    kept: list[str] = []
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        bid = _starts(line)
        if bid is None:
            row, cut = _cells(line)
            for b in cut:
                b.source = source
            blocks.extend(cut)
            kept.append(row)
            i += 1
            continue
        j = i + 1
        if line.startswith("- "):
            while j < len(lines) and (
                lines[j].startswith(" ")
                or (lines[j] == "" and j + 1 < len(lines) and lines[j + 1].startswith(" "))
            ):
                j += 1
        else:
            while j < len(lines):
                nxt = lines[j]
                if nxt.startswith("#") or nxt.startswith(STOP_BEFORE) or _starts(nxt):
                    break
                j += 1
        body = lines[i:j]
        while body and body[-1] == "":
            body.pop()
        blocks.append(Block(bid, source, "\n".join(body)))
        gap = j
        while j < len(lines) and lines[j] == "":
            j += 1
        if j > gap and j < len(lines) and kept and kept[-1] != "":
            kept.append("")
        i = j
    if text.endswith("\n") and kept and kept[-1] != "":
        kept.append("")
    heading = "(the top)"
    where: list[tuple[str, str]] = []
    for line in kept:
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        for m in CITED.finditer(line):
            where.append((m.group(1), f'`{source}` § "{heading}"'))
    for b in blocks:
        for m in CITED.finditer(b.text):
            if m.group(1) != b.id:
                where.append((m.group(1), f"within ADR {b.id}"))
    return "\n".join(kept), blocks, where


def shipped_citations(root: Path) -> set[str]:
    """Every ADR id a SHIP-bucket file of `root` cites, by the publication census."""
    sys.path.insert(0, str(root))
    from quality.djb.rituals.publish import census

    ids: set[str] = set()
    for path in census(root).ship:
        try:
            ids.update(CITED.findall((root / path).read_text()))
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
    return ids


def pointer(adr: str, where: list[str]) -> str:
    """The file for an id the shipped tree cites and no block carries."""
    lines = [
        f"# ADR {adr}",
        "",
        "No block of its own carried this id when the decision log was split (CQ-DOCS-M0,",
        "2026-10-23). The shipped tree names it at:",
        "",
    ]
    lines += [f"- {w}" for w in where] or [
        "- no shipped document: its decision text lives only in trimmed history"
    ]
    return "\n".join(lines) + "\n"


def run(root: Path, dry: bool) -> int:
    """Split both homes under `root`; print what moved; 0 done, 2 refused."""
    texts: dict[str, str] = {}
    blocks: list[Block] = []
    where: dict[str, list[str]] = {}
    for home in HOMES:
        kept, moved, cites = split((root / home).read_text(), home)
        texts[home] = kept
        blocks += moved
        for adr, w in cites:
            if w not in where.setdefault(adr, []):
                where[adr].append(w)
    adrs = root / ADRS
    files: dict[str, str] = {}
    for b in blocks:
        files[b.id] = (files[b.id] + "\n\n" if b.id in files else f"# ADR {b.id}\n\n") + b.text
    clash = sorted(a for a in files if (adrs / f"{a}.md").exists())
    if clash:
        raise Refused(f"a block's file already exists: {', '.join(clash)}")
    for adr in sorted(shipped_citations(root) - set(files)):
        if not (adrs / f"{adr}.md").exists():
            files[adr] = pointer(adr, where.get(adr, [])).rstrip("\n")
    print(f"blocks moved: {len(blocks)} · files written: {len(files)}")
    for adr in sorted(files):
        kind = "pointer" if files[adr].startswith(f"# ADR {adr}\n\nNo block") else "block"
        print(f"  {kind:8} {adr}")
    if dry or not files:
        return 0
    adrs.mkdir(parents=True, exist_ok=True)
    for adr, body in files.items():
        (adrs / f"{adr}.md").write_text(body + "\n")
    for home, kept in texts.items():
        (root / home).write_text(kept)
    return 0


def main(argv: list[str]) -> int:
    """The command line: `--root`, `--dry-run`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(args.root.resolve(), args.dry_run)
    except Refused as refused:
        print(f"adr_split: REFUSED — {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
