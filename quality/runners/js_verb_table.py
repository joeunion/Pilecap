"""The verb table equals the book's — the runner half. (patterns.md §4, the verb table)

    python3 quality/runners/js_verb_table.py <root> [<root> …]

THE CLOSED QUESTION: does `frontend/src/kit/verbs.ts`'s `VERB_TABLE` — the
one declaration every noun face draws its family acts from — equal the book's
verb table row for row? The book's table is the fenced `verb-table` block in
the pattern book (`docs/product/design/patterns.md`, §4), read through
`quality/pattern_book.py`, the one reader of the book and its drawer; a
product that renames or re-rules its verbs writes its WHOLE table in its
drawer's block, which then stands for the book's. Compared, per row and in
order:

* the verbs, in the same sequence (the order a face draws them in is the
  table's order, so a reordered table is a reordered face — `table-order`);
* a verb on one side and not the other (`table-row`);
* per verb: its place in `record-acts` (`order`), how it is pressed
  (`press`), its weight, and whether each of its five forms is present —
  pressed · busy · state · refused · way back (`table-cell`).

The WORDS in the two tables are not compared: a product's word is one
lexicon line (house rule 72) and the synonyms of a verb are rule 79's. A
ruling stays a token: the book's cells are read as tokens, never as prose.

Also the reader the other verb runners import (`code_table`, `family_words`),
so three runners cannot disagree about what the table says.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality import pattern_book  # noqa: E402
from quality.runners import _source  # noqa: E402

TABLE = "frontend/src/kit/verbs.ts"
NONE = "—"
FORMS = ("pressed", "busy", "state", "refused", "way back")
COLUMNS = ("verb", "pressed", "busy", "state", "refused", "way back", "press", "order", "weight")

_START = re.compile(r"\bexport\s+const\s+VERB_TABLE\b[^=]*=\s*\[")
_STRING = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


@dataclass(frozen=True)
class Row:
    """One verb's row, as either table states it: tokens for rulings, the forms' words."""

    verb: str
    line: int
    order: str
    press: str
    weight: str
    forms: dict[str, tuple[str, ...]]
    #: The word on the foot of the sheet or confirm the act opens; "" when it opens
    #: none (the code's table only — the book's has no foot column).
    foot: str = ""

    def present(self, form: str) -> bool:
        return bool(self.forms.get(form))


def _strings(text: str) -> tuple[str, ...]:
    return tuple(m.group(1) for m in _STRING.finditer(text))


def _field(body: str, name: str) -> str | None:
    """The raw value of `name:` in one object literal, up to the next top-level comma."""
    m = re.search(rf"(?<![\w$]){re.escape(name)}\s*:", body)
    if not m:
        return None
    i, depth = m.end(), 0
    for j in range(i, len(body)):
        c = body[j]
        if c in "[{(":
            depth += 1
        elif c in "]})":
            if depth == 0:
                return body[i:j].strip()
            depth -= 1
        elif c == "," and depth == 0:
            return body[i:j].strip()
    return body[i:].strip()


def code_table(root: Path) -> tuple[list[Row], bool]:
    """(`VERB_TABLE`'s rows in order, whether the declaration was found) from verbs.ts."""
    path = root / TABLE
    src = _source.read(path) if path.is_file() else None
    if src is None:
        return [], False
    start = _START.search(src.code)
    if start is None:
        return [], False
    rows: list[Row] = []
    i = start.end()
    depth = 0
    open_at = -1
    while i < len(src.code):
        c = src.code[i]
        if c == "{":
            if depth == 0:
                open_at = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and open_at >= 0:
                body = src.raw[open_at : i + 1]
                rows.append(_code_row(body, src.line_of(open_at)))
        elif c == "]" and depth == 0:
            break
        i += 1
    return rows, True


def _code_row(body: str, line: int) -> Row:
    def words(name: str) -> tuple[str, ...]:
        value = _field(body, name)
        return () if value is None or value == "null" else _strings(value)

    way_back = words("wayBack") + words("wayBackByKind")
    return Row(
        verb=(words("verb") or ("",))[0],
        line=line,
        order=(_field(body, "order") or "null").replace("null", NONE),
        press=(words("press") or ("",))[0],
        weight=(words("weight") or ("",))[0],
        foot=(words("foot") or ("",))[0],
        forms={
            "pressed": words("pressed"),
            "busy": words("busy"),
            "state": words("state"),
            "refused": words("refused"),
            # A way back is a verb and its word; the words are what a reader sees.
            "way back": tuple(w for w in way_back if w[:1].isupper()),
        },
    )


def book_table(root: Path) -> tuple[list[Row], str]:
    """(the book's rows in order, their book); a drawer's block stands for the book's."""
    lines = pattern_book.fenced_lines(root, pattern_book.VERB_TABLE_FENCE)
    drawer = [entry for entry in lines if entry[0] == pattern_book.LOCAL_BOOK]
    chosen = drawer or [entry for entry in lines if entry[0] == pattern_book.BOOK]
    rows: list[Row] = []
    for _rel, line, text in chosen:
        cells = [cell.strip() for cell in text.split("|")]
        if len(cells) != len(COLUMNS):
            continue
        # Indexed, not zipped: a runner runs under the box's system python3,
        # which predates `zip(..., strict=)`; the length is checked above.
        cell = {name: cells[i] for i, name in enumerate(COLUMNS)}

        def split(value: str) -> tuple[str, ...]:
            return () if value in (NONE, "") else tuple(part.strip() for part in value.split("·"))

        rows.append(
            Row(
                verb=cell["verb"],
                line=line,
                order=cell["order"],
                press=cell["press"],
                weight=cell["weight"],
                forms={form: split(cell[form]) for form in FORMS},
            )
        )
    return rows, (pattern_book.LOCAL_BOOK if drawer else pattern_book.BOOK)


def family_words(root: Path) -> set[str]:
    """Every word the code's verb table spends — the product's word for each verb, as renamed."""
    rows, _found = code_table(root)
    return {word for row in rows for words in row.forms.values() for word in words}


def main(argv: list[str]) -> int:
    root = Path.cwd()
    findings: list[dict] = []
    code, found = code_table(root)
    book, source = book_table(root)

    def hit(line: int, msg: str, klass: str) -> None:
        findings.append({"path": TABLE, "line": line, "msg": msg, "klass": klass})

    if not found:
        hit(
            1,
            f"`{TABLE}` declares no `VERB_TABLE` — the noun-verb family's faces draw their acts "
            "from that one table, and the book's verb table has nothing to be compared with",
            "table-missing",
        )
    if not book:
        hit(
            1,
            f"the pattern book carries no `verb-table` block ({pattern_book.BOOK} §4, or a "
            "product's whole table in its drawer) — the code's table has no ruling to equal",
            "table-missing",
        )
    if found and book:
        mine = [row.verb for row in code]
        ruled = [row.verb for row in book]
        by_verb = {row.verb: row for row in code}
        for row in book:
            if row.verb not in by_verb:
                hit(
                    code[0].line if code else 1,
                    f"the book's verb table ({source}:{row.line}) rules `{row.verb}` and "
                    "`VERB_TABLE` has no row for it — a verb the book rules is a verb every "
                    "face may draw",
                    "table-row",
                )
        ruled_set = set(ruled)
        for row in code:
            if row.verb not in ruled_set:
                hit(
                    row.line,
                    f"`VERB_TABLE` has a row for `{row.verb}` and the book's verb table "
                    f"({source}) rules none — a verb no ruling names is a seat nobody decided",
                    "table-row",
                )
        shared_mine = [verb for verb in mine if verb in ruled_set]
        shared_ruled = [verb for verb in ruled if verb in by_verb]
        if shared_mine != shared_ruled:
            first = next(
                (
                    verb
                    for i, verb in enumerate(shared_mine)
                    if i >= len(shared_ruled) or shared_ruled[i] != verb
                ),
                shared_mine[0],
            )
            hit(
                by_verb[first].line,
                "`VERB_TABLE` orders the verbs " + " · ".join(shared_mine) + " and the book's "
                f"verb table ({source}) orders them " + " · ".join(shared_ruled) + " — a face "
                "draws its acts in the table's order, so a reordered table is a reordered face",
                "table-order",
            )
        for ruling in book:
            row = by_verb.get(ruling.verb)
            if row is None:
                continue
            for name, have, want in (
                ("order", row.order, ruling.order),
                ("press", row.press, ruling.press),
                ("weight", row.weight, ruling.weight),
            ):
                if have != want:
                    hit(
                        row.line,
                        f"`{row.verb}`'s {name} is `{have}` in `VERB_TABLE` and `{want}` in the "
                        f"book's verb table ({source}:{ruling.line}) — a ruling stays a token",
                        "table-cell",
                    )
            for form in FORMS:
                if row.present(form) != ruling.present(form):
                    said = "has" if row.present(form) else "has no"
                    ruled_word = "rules one" if ruling.present(form) else "rules none"
                    hit(
                        row.line,
                        f"`{row.verb}` {said} {form} form in `VERB_TABLE` and the book's verb "
                        f"table ({source}:{ruling.line}) {ruled_word} — the five forms are the "
                        "verb's words on every face",
                        "table-cell",
                    )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": int(found),
                    "code_tables": int(found),
                    "code_rows": len(code),
                    "book_tables": int(bool(book)),
                    "book_rows": len(book),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
