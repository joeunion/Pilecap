"""The pattern book, read — the ONE reader of the book and its drawer.

    from quality import pattern_book
    found, counts = pattern_book.findings(root)

THE BOOK IS A LIST OF ELEMENT CLASSES, AND EVERY ENTRY NAMES THE FILE THAT
MEASURES IT. A pattern whose instrument does not exist is a wish: two verifiers
once passed a face that broke a written rule, because the rule had no test to
fail. So the book's grammar is small and closed, and this module is the only
thing that reads it:

* **an entry** is a heading section carrying the six labelled paragraphs —
  `**Shape.**` · `**Words.**` · `**Placement.**` · `**States.**` ·
  `**Ruling.**` · `**Instrument.**` — at the start of a line. A section that
  carries ANY of the six is an entry and owes all six; the instrument paragraph
  names at least one repository path in backticks, and every path it names is
  a file in this tree.
* **the instrument index** is the table under the heading
  `## The instruments, by file`; its second column names the file, and the
  same rule holds for every row.
* **the motion ledger** is every fenced block opened with three backticks and
  `motion-ledger`: one row per moment that moves, four ` | `-separated fields
  (moment · token · what moves · under reduced motion), the token spelled
  `--motion-<name>`. Rule 66 compares the token set a product declares against
  exactly these rows; this module only reads them.

TWO BOOKS, ONE GRAMMAR. The template ships the book (`BOOK`); a product's own
entries, index rows and ledger rows go in its DRAWER beside it (`LOCAL_BOOK`,
ADR platform-extension-1), which the template never ships and so a fold can
never conflict with. Absent, the drawer is byte-identical behaviour. Every
block is read in both files — EVERY fenced block, not the first, for the
reason `quality/checks.py::drawer_rows` gives: an append is how a product
extends a list and how a canary is planted.

Pure Python, no Django: `quality/checks.py` (rule 63) and the motion-ledger
runner under `quality/runners/` (rule 66, a subprocess) both read the book
through this module, so there is one grammar and not two.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

#: The template's book. Template-owned; a product never edits it.
BOOK = "docs/product/design/patterns.md"
#: The product's drawer beside it — the one place a product's entries land.
LOCAL_BOOK = "docs/product/design/patterns.local.md"

#: The six parts of an entry, in the order the book writes them.
FIELDS: tuple[str, ...] = ("Shape", "Words", "Placement", "States", "Ruling", "Instrument")

INDEX_HEADING = "## The instruments, by file"
LEDGER_FENCE = "```motion-ledger"

_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FIELD = re.compile(r"^\*\*(" + "|".join(FIELDS) + r")\.\*\*")
_TICKED = re.compile(r"`([^`]+)`")
#: A repository path: two or more segments, the last one carrying a suffix.
#: Brackets are legal because an app-router segment is spelled `[id]`.
_PATH = re.compile(r"^[A-Za-z0-9_.@-]+(?:/[A-Za-z0-9_.@()\[\]-]+)+$")
MOTION_TOKEN = re.compile(r"^--motion-[a-z0-9]+(?:-[a-z0-9]+)*$")

#: THE FACE LAYERS — every module under these draws (or declares it draws
#: nothing), so every one names the book's sections it draws in a header line.
FACE_LAYERS: tuple[str, ...] = ("frontend/src/screens", "frontend/src/components")
FACE_SUFFIXES: tuple[str, ...] = (".ts", ".tsx", ".js", ".jsx")
#: Test and story modules exercise a face; they do not draw one.
FACE_EXEMPT_INFIXES: tuple[str, ...] = (".test.", ".stories.", ".spec.")
FACE_SKIP_DIRS = frozenset({"node_modules", ".next", "dist", "build", "coverage"})
#: `// patterns: §15, §26` (or ` * patterns: …` inside the header block),
#: within the file's first `FACE_HEADER_LINES` lines.
FACE_HEADER = re.compile(r"^\s*(?://|/?\*+)\s*patterns:\s*(.+?)\s*(?:\*/)?\s*$")
FACE_HEADER_LINES = 12
_SECTION = re.compile(r"§\s*(\d+)")
#: The two declarations the reader accepts BY NAME instead of a section. Each is
#: a sentence a reviewer can disagree with, counted on the rule's line, never
#: a silent pass: a surface whose words the template owns (the placeholder
#: landing), and a module in a face layer that draws nothing (a seam).
NAMED_DECLARATIONS: dict[str, str] = {
    "template placeholder — words owned": "placeholder_declarations",
    "none — draws no face": "no_face_declarations",
}

#: EVERY FINDING CLASS THIS READER EMITS, and nothing else — the one list rule
#: 63's `ratchets:` keys are compared against (ADR gate-6: a recorded 0 is a
#: measurement, an absent key is silence). A product folding the template meets
#: its backlog in exactly these classes, and records it in its drawer under the
#: same names; a class added here without its key, or a key with no class, is
#: the rule's `ratchet_classes_keyed` floor unbound (exit 2), never a quiet gap.
CLASSES: tuple[str, ...] = (
    "book",
    "entry-form",
    "instrument-unnamed",
    "instrument-missing",
    "ledger-row",
    "face-undeclared",
    "face-section-missing",
)


@dataclass
class Entry:
    """One entry: where its heading is, and the line each of its parts starts on."""

    line: int
    heading: str
    fields: dict[str, tuple[int, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    msg: str
    klass: str


def _paths_in(text: str) -> list[str]:
    """Every backticked token in `text` shaped like a repository file path."""
    out: list[str] = []
    for raw in _TICKED.findall(text):
        candidate = raw.strip().split("::", 1)[0].split("#", 1)[0]
        if _PATH.match(candidate) and "." in candidate.rsplit("/", 1)[-1]:
            out.append(candidate)
    return out


def _outside_fences(lines: list[str]) -> list[bool]:
    """True for each line that sits OUTSIDE a fenced block — prose, not an example."""
    out: list[bool] = []
    inside = False
    for text in lines:
        if text.strip().startswith("```"):
            out.append(False)
            inside = not inside
            continue
        out.append(not inside)
    return out


def entries(text: str) -> list[Entry]:
    """Every heading section that carries at least one of the six labelled parts."""
    lines = text.splitlines()
    prose = _outside_fences(lines)
    found: list[Entry] = []
    current: Entry | None = None
    active: str | None = None
    for number, line in enumerate(lines, start=1):
        if not prose[number - 1]:
            continue
        heading = _HEADING.match(line)
        if heading:
            if current is not None and current.fields:
                found.append(current)
            current = Entry(number, heading.group(2))
            active = None
            continue
        if current is None:
            continue
        label = _FIELD.match(line)
        if label:
            active = label.group(1)
            current.fields[active] = (number, line)
            continue
        if not line.strip():
            active = None
            continue
        if active is not None:
            at, body = current.fields[active]
            current.fields[active] = (at, body + "\n" + line)
    if current is not None and current.fields:
        found.append(current)
    return found


def index_rows(text: str) -> list[tuple[int, list[str]]]:
    """(line, the paths its file column names) for every row of every index table."""
    rows: list[tuple[int, list[str]]] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            inside = line.strip() == INDEX_HEADING
            continue
        if not inside or not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= set("-: "):
            continue
        if cells[1].lower().startswith("instrument file"):
            continue  # the header row
        rows.append((number, _paths_in(cells[1])))
    return rows


def ledger_rows(text: str) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
    """(line, token) for every well-formed motion-ledger row, and (line, why) for the rest.

    Blank lines and whole-line `#` comments inside the block are skipped, so a
    book can carry the row's form as a comment with no row under it.
    """
    rows: list[tuple[int, str]] = []
    bad: list[tuple[int, str]] = []
    inside = False
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not inside:
            inside = stripped == LEDGER_FENCE
            continue
        if stripped.startswith("```"):
            inside = False
            continue
        if not stripped or stripped.startswith("#"):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        if len(cells) != 4:
            bad.append((number, f"{len(cells)} ` | `-separated field(s), not 4"))
            continue
        if not MOTION_TOKEN.match(cells[1]):
            bad.append((number, f"the token field is {cells[1]!r}, not `--motion-<name>`"))
            continue
        rows.append((number, cells[1]))
    return rows, bad


def books(root: Path) -> list[tuple[str, str]]:
    """(relative path, text) for the template's book and, when a product wrote one, its drawer."""
    out: list[tuple[str, str]] = []
    for rel in (BOOK, LOCAL_BOOK):
        path = root / rel
        if path.is_file():
            try:
                out.append((rel, path.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                out.append((rel, ""))
    return out


#: The book's other machine-read blocks, each a fenced block the reader
#: returns line by line (book first, then the drawer): the verb table the
#: family's faces transcribe (house rule 80), the words a product declares are
#: not another verb's synonym (rule 79), and the one other breakpoint a
#: product's drawer may record (rule 78's breakpoint clause).
VERB_TABLE_FENCE = "```verb-table"
VERB_WORDS_FENCE = "```verb-words"
BREAKPOINTS_FENCE = "```breakpoints"


def fenced_lines(root: Path, fence: str) -> list[tuple[str, int, str]]:
    """(book, line, text) for every line of every `fence` block in the book and the drawer.

    Blank lines and whole-line `#` comments are skipped, so a book can carry a
    block's form as a comment with no row under it — the motion ledger's rule.
    """
    out: list[tuple[str, int, str]] = []
    for rel, text in books(root):
        inside = False
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not inside:
                inside = stripped == fence
                continue
            if stripped.startswith("```"):
                inside = False
                continue
            if stripped and not stripped.startswith("#"):
                out.append((rel, number, stripped))
    return out


def ledger_tokens(root: Path) -> tuple[bool, dict[str, tuple[str, int]]]:
    """(the template's book was readable, token -> (book, line) of its FIRST ledger row)."""
    found: dict[str, tuple[str, int]] = {}
    read = books(root)
    for rel, text in read:
        rows, _bad = ledger_rows(text)
        for line, token in rows:
            found.setdefault(token, (rel, line))
    return any(rel == BOOK for rel, _ in read), found


def entry_sections(root: Path) -> set[str]:
    """Every `§N` an entry's heading carries, in the book and the drawer."""
    found: set[str] = set()
    for _rel, text in books(root):
        for entry in entries(text):
            found.update(_SECTION.findall(entry.heading))
    return found


def face_files(root: Path) -> list[Path]:
    """Every module in a face layer, test and story modules aside."""
    out: list[Path] = []
    for layer in FACE_LAYERS:
        base = root / layer
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            rel_parts = path.relative_to(root).parts
            if FACE_SKIP_DIRS & set(rel_parts) or not path.is_file():
                continue
            if path.suffix not in FACE_SUFFIXES:
                continue
            if any(infix in path.name for infix in FACE_EXEMPT_INFIXES):
                continue
            out.append(path)
    return out


def face_declaration(text: str) -> str | None:
    """The file's `patterns:` declaration, or None when its header carries none."""
    for line in text.splitlines()[:FACE_HEADER_LINES]:
        m = FACE_HEADER.match(line)
        if m:
            return m.group(1).strip()
    return None


def face_findings(root: Path, out: list[Finding], counts: dict[str, int]) -> None:
    """The second clause: every face module declares the sections it draws."""
    sections = entry_sections(root)
    counts.setdefault("face_files", 0)
    for key in NAMED_DECLARATIONS.values():
        counts.setdefault(key, 0)
    for path in face_files(root):
        rel = str(path.relative_to(root))
        counts["face_files"] += 1
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        declared = face_declaration(text)
        if declared is None:
            out.append(
                Finding(
                    rel,
                    1,
                    f"`{rel}` is in a face layer and declares no pattern-book section — "
                    "its header carries `// patterns: §<n>` for every section it draws "
                    "(several allowed), or one of the named declarations ("
                    + " · ".join(f"`{name}`" for name in NAMED_DECLARATIONS)
                    + "). A face drawn with no entry is a face drawn on a guess.",
                    "face-undeclared",
                )
            )
            continue
        if declared in NAMED_DECLARATIONS:
            counts[NAMED_DECLARATIONS[declared]] += 1
            continue
        named = _SECTION.findall(declared)
        if not named:
            out.append(
                Finding(
                    rel,
                    1,
                    f"`{rel}` declares `patterns: {declared}`, which names no `§<n>` and "
                    "is none of the named declarations — the reader cannot resolve it.",
                    "face-undeclared",
                )
            )
            continue
        for number in named:
            if number not in sections:
                out.append(
                    Finding(
                        rel,
                        1,
                        f"`{rel}` declares it draws §{number}, and no entry in the pattern "
                        "book or its drawer carries §" + number + " — write the entry "
                        "(and land its instrument) before the face that draws it.",
                        "face-section-missing",
                    )
                )


def findings(root: Path) -> tuple[list[Finding], dict[str, int]]:
    """Rule 63 over both books: (findings, counts). Counts feed the rule's floors."""
    out: list[Finding] = []
    counts = {"books": 0, "entries": 0, "index_rows": 0, "ledger_blocks": 0}
    read = books(root)
    if not any(rel == BOOK for rel, _ in read):
        out.append(
            Finding(
                BOOK,
                0,
                "the pattern book is not in this tree, so no element class has an entry and "
                "no entry names its instrument. That is enforcement broken, not a product "
                "with no front end: the book ships with the template.",
                "book",
            )
        )
    for rel, text in read:
        counts["books"] += 1
        counts["ledger_blocks"] += sum(
            1 for line in text.splitlines() if line.strip() == LEDGER_FENCE
        )
        for entry in entries(text):
            counts["entries"] += 1
            missing = [name for name in FIELDS if name not in entry.fields]
            if missing:
                out.append(
                    Finding(
                        rel,
                        entry.line,
                        f"the entry `{entry.heading}` is missing "
                        + ", ".join(f"**{name}.**" for name in missing)
                        + " — an entry is six parts (shape · words · placement · states · "
                        "ruling · instrument), each a paragraph opening with its bold label, "
                        "and a part left out is a question the builder answers alone.",
                        "entry-form",
                    )
                )
            if "Instrument" not in entry.fields:
                continue
            at, body = entry.fields["Instrument"]
            named = _paths_in(body)
            if not named:
                out.append(
                    Finding(
                        rel,
                        at,
                        f"the entry `{entry.heading}` names no instrument file — its "
                        "**Instrument.** paragraph must name, in backticks, the file that "
                        "measures the pattern. A ruling with no instrument is a wish, and "
                        "it will be broken by a face nobody's test can fail on.",
                        "instrument-unnamed",
                    )
                )
            for path in named:
                if not (root / path).is_file():
                    out.append(
                        Finding(
                            rel,
                            at,
                            f"the entry `{entry.heading}` names the instrument `{path}`, "
                            "which is not a file in this tree — an instrument that does not "
                            "exist cannot fail, so the pattern has no teeth. Land the "
                            "instrument first (red, with its owed list), then the entry.",
                            "instrument-missing",
                        )
                    )
        for line, named in index_rows(text):
            counts["index_rows"] += 1
            if not named:
                out.append(
                    Finding(
                        rel,
                        line,
                        "this row of the instrument index names no file in its second "
                        "column — the index is copied into briefs as a territory line, so "
                        "a row with no file is a territory nobody can find.",
                        "instrument-unnamed",
                    )
                )
            for path in named:
                if not (root / path).is_file():
                    out.append(
                        Finding(
                            rel,
                            line,
                            f"the instrument index names `{path}`, which is not a file in "
                            "this tree — the index and the entries name the same files, or "
                            "the difference is a finding.",
                            "instrument-missing",
                        )
                    )
        _rows, bad = ledger_rows(text)
        for line, why in bad:
            out.append(
                Finding(
                    rel,
                    line,
                    f"this motion-ledger row is unreadable — {why}. A row is `<moment> | "
                    "--motion-<name> | <what moves> | <under reduced motion>`, and rule 66 "
                    "compares the declared motion tokens against exactly these rows.",
                    "ledger-row",
                )
            )
    face_findings(root, out, counts)
    return out, counts
