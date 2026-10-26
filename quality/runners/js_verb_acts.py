"""The family's acts are constructed, never spelled — the runner half. (patterns.md §4, §20, §26)

    python3 quality/runners/js_verb_acts.py <root> [<root> …]

FIVE CLOSED QUESTIONS about how a family act reaches a face, each a class:

(a) `hand-act` — is a `data-act="<verb>"` spelled by hand? An act's
    attributes come from `frontend/src/kit/verbs.ts` (`actsFor`,
    `bulkActsFor`, `footAct` spread `act.attrs`), so its order, its weight and
    its words are constructed from the one table; a string-literal
    `data-act` anywhere else under `frontend/src/` is an act somebody
    remembered, and it drifts the day the table moves.
(b) `objectless-ask` — is a permission asked without its object? A key shaped
    `"<noun>.<verb>"` (a family verb, `create` or `delete`) spelled under
    `frontend/src/` outside the generated client is a screen asking "may I
    archive widgets?" — answered no for every real administrator, because the
    server's answer is per row (`allowed_acts`), and a client that asks it has
    started resolving authority.
(c) `leaving-in-dialog` / `merge-outside-confirm` — is a one-press verb inside
    the dialog primitive, or merge outside it? A verb the same face undoes in
    one press (the table's `foot` is `null`: archive, restore, duplicate,
    import, attach) is never guarded by a dialog, so its word spelled — as JSX
    text or a string — or its foot asked for (`footAct(…, "<verb>")`) between
    `<Dialog` and its close is red (its foot act does not exist: the table
    gives it no foot word); merge alone is irreversible, so its foot act asked
    for in a module that draws no `<Dialog` is red. A sheet that collects an
    argument (Edit's, Move's) is not a confirm and is silent.
(d) `seat-reordered` — does a stylesheet reorder a seat? DOM order is the
    table's order (*Archive* last), and `order:` or a `*-reverse` direction in
    a rule whose selector names `[data-seat` would show another order than the
    census reads.
(e) `breakpoint` — does a width media query name an allowed breakpoint, in
    range syntax? Every `@media` width condition under `frontend/src/` (and
    every `matchMedia("…")` string) is `(width <op> <length>)`, `<op>` one of
    `<=`, `<`, `>=`, `>` — the book's pair is `(width <= 40rem)` and its
    complement `(width > 40rem)`, §26 "The phone": the book has two widths,
    and a third is a third set of captures on every mirror pass. The lengths
    read are a closed set, `rem`, `px` and `em` (`%`, `vw`, `ch` are not
    breakpoint lengths and stay refused). The allowed values are the book's
    40rem and the values a product's drawer records in a fenced `breakpoints`
    block, one per line, each `<length> — <reason>`; a line with no reason is
    its own finding. The refusal says which half failed: the FORM (a
    `min-`/`max-` query, or a length outside the three) or the VALUE (range
    syntax naming a width nobody declared).

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality import pattern_book  # noqa: E402
from quality.reason_floor import MIN_REASON  # noqa: E402
from quality.runners import _css, _source  # noqa: E402
from quality.runners import js_verb_table as _table  # noqa: E402

VERBS_MODULE = Path("frontend/src/kit/verbs.ts")
GENERATED = ("frontend", "src", "api", "generated")
BREAKPOINT = "40rem"

DATA_ACT_ATTR = re.compile(r"(?<![\w$-])data-act\s*=\s*$")
DATA_ACT_KEY = re.compile(r"[\"']data-act[\"']\s*:\s*$")
FOOT_CALL = re.compile(r"(?<![\w$.])footAct\s*\(")
DIALOG_OPEN = re.compile(r"<Dialog(?![\w$])")
DIALOG_CLOSE = re.compile(r"</Dialog\s*>")
JSX_TEXT = re.compile(r">([^<>{}]+)<")
SEAT_SELECTOR = re.compile(r"\[\s*data-seat\b")
MEDIA = re.compile(r"@media\b([^{]*)\{")
MATCH_MEDIA = re.compile(r"(?<![\w$])matchMedia\s*\(\s*$")
WIDTH_FEATURE = re.compile(r"\b(?:min-|max-)?(?:device-)?width\b")
#: The lengths a breakpoint is written in — the book's `rem`, and the `px` and
#: `em` a product's rulings use. Closed: a length outside it is a FORM finding.
LENGTHS = ("rem", "px", "em")
RANGE = re.compile(rf"^\(\s*width\s*(<=|<|>=|>)\s*([0-9.]+(?:{'|'.join(LENGTHS)}))\s*\)$")
#: Any width condition's value, to say in the refusal which value it named.
WIDTH_VALUE = re.compile(r"(?:[:<>=]\s*)([0-9.]+[a-z%]*)\s*\)$")
#: One line of a drawer's `breakpoints` block: `<length> — <reason>`.
DECLARED = re.compile(r"^(?P<length>[^\s—]+)\s+—\s+(?P<reason>\S.*?)\s*$")
DRAWER_GRAMMAR = f"(`{pattern_book.LOCAL_BOOK}`), one per line, each `<length> — <reason>`"


def _verbs(root: Path) -> tuple[set[str], set[str], dict[str, tuple[str, ...]]]:
    """(every family verb, the one-press verbs opening no sheet, verb -> its pressed words)."""
    rows, _found = _table.code_table(root)
    family = {row.verb for row in rows}
    no_foot = {row.verb for row in rows if row.press not in ("none", "confirm") and row.foot == ""}
    pressed = {row.verb: row.forms.get("pressed", ()) for row in rows}
    return family, no_foot, pressed


def _close_paren(code: str, open_at: int) -> int:
    """The offset just past the parenthesis that closes the `(` at `open_at`."""
    depth = 0
    for i in range(open_at, len(code)):
        if code[i] == "(":
            depth += 1
        elif code[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(code)


def _dialog_spans(src: _source.Source) -> list[tuple[int, int]]:
    """(start, end) of every `<Dialog …>…</Dialog>` (or self-closed) element, in the code text."""
    spans: list[tuple[int, int]] = []
    for m in DIALOG_OPEN.finditer(src.blank):
        close = DIALOG_CLOSE.search(src.blank, m.end())
        end = close.end() if close else len(src.blank)
        spans.append((m.start(), end))
    return spans


def _breakpoints(root: Path) -> tuple[set[str], list[tuple[str, int, str]]]:
    """(allowed widths, unreasoned lines): the book's 40rem, and every `breakpoints` line.

    A `breakpoints` line is `<length> — <reason>` (the house's dash grammar),
    as many lines as the block writes: the length joins the allowed set either
    way, and a line with no em dash, or a reason under `MIN_REASON`, is also a
    refusal naming its book and line — a value with no reason is a ruling
    nobody can revisit.
    """
    allowed = {BREAKPOINT}
    unreasoned: list[tuple[str, int, str]] = []
    for rel, line, text in pattern_book.fenced_lines(root, pattern_book.BREAKPOINTS_FENCE):
        m = DECLARED.match(text)
        allowed.add(m.group("length") if m else text.split()[0])
        if not m or len(m.group("reason")) < MIN_REASON:
            unreasoned.append((rel, line, text))
    return allowed, unreasoned


def _query_ok(query: str, allowed: set[str]) -> str | None:
    """None when every width condition is `(width <op> X)`, X an allowed length; else the refusal.

    The refusal is the FORM sentence when a condition is not range syntax over
    one of `LENGTHS` (a `min-`/`max-` query, a `%`/`vw`/`ch` length) and the
    VALUE sentence when the form holds and the width is neither the book's nor
    declared — the first failing condition's, completing a sentence whose
    subject (the query) the caller names.
    """
    for condition in re.findall(r"\([^()]*\)", query):
        if not WIDTH_FEATURE.search(condition):
            continue
        m = RANGE.match(condition.strip())
        if m is None:
            return _form_refusal(condition.strip(), allowed)
        if m.group(2) not in allowed:
            return (
                f"names a width that is not the one breakpoint ({BREAKPOINT}) and is not "
                "declared — a product's other values are a `breakpoints` block in its drawer "
                f"{DRAWER_GRAMMAR}"
            )
    return None


def _form_refusal(condition: str, allowed: set[str]) -> str:
    """The FORM sentence for one width condition, its last clause the verdict on its value."""
    sentence = (
        "is not in range syntax — every width query under frontend/src/ is "
        f"`(width <op> <length>)` in {', '.join(LENGTHS[:-1])} or {LENGTHS[-1]}, the book's pair "
        f"`(width <= {BREAKPOINT})` / `(width > {BREAKPOINT})` (§26 The phone); rewrite the "
        "FORM — `max-width: X` is `width <= X` and `min-width: X` is `width >= X`"
    )
    found = WIDTH_VALUE.search(condition)
    if found is None:
        return sentence
    value = found.group(1)
    if not value.endswith(LENGTHS):
        return f"{sentence}; the value {value} is not a length a breakpoint is written in"
    if value == BREAKPOINT:
        return f"{sentence}; the value {value} is the book's and stands"
    if value in allowed:
        return f"{sentence}; the value {value} is declared in your drawer and stands"
    return (
        f"{sentence}; the value {value} is not the book's {BREAKPOINT} and is not declared "
        "in your drawer"
    )


def main(argv: list[str]) -> int:
    root = Path.cwd()
    findings: list[dict] = []
    family, no_foot, pressed = _verbs(root)
    verb_alt = "|".join(sorted(family | {"create", "delete"}))
    ask = re.compile(rf"^[a-z][a-z0-9_-]*\.(?:{verb_alt})$") if family else None
    allowed, unreasoned = _breakpoints(root)
    scripts = [
        s for s in _source.scripts(argv) if Path(s.path).parts[: len(GENERATED)] != GENERATED
    ]
    sheets = _source.sheets(argv)
    dialogs = 0
    queries = 0

    def hit(path: str, line: int, msg: str, klass: str) -> None:
        findings.append({"path": path, "line": line, "msg": msg, "klass": klass})

    for src in scripts:
        own = Path(src.path) == VERBS_MODULE
        for lit in src.literals:
            head = src.code[max(0, lit.start - 40) : lit.start]
            # (a) a hand-spelled act.
            if (
                not own
                and lit.value in family
                and (DATA_ACT_ATTR.search(head) or DATA_ACT_KEY.search(head))
            ):
                hit(
                    src.path,
                    lit.line,
                    f'`data-act="{lit.value}"` is spelled by hand — a family act\'s attributes '
                    "come "
                    "from `frontend/src/kit/verbs.ts` (`actsFor`, `bulkActsFor`, `footAct` "
                    "spread `act.attrs`), so its order, weight and words are the table's",
                    "hand-act",
                )
            # (b) an object-less ask.
            if ask is not None and ask.match(lit.value) and not _source.is_specifier(src, lit):
                hit(
                    src.path,
                    lit.line,
                    f'`"{lit.value}"` asks a permission with no object — the server answers per '
                    "row (`allowed_acts`), and an abstract ask hides the act from every real "
                    "administrator; a face reads the row's answer and never asks its own",
                    "objectless-ask",
                )
            # (e) a matchMedia query.
            if MATCH_MEDIA.search(head) and WIDTH_FEATURE.search(lit.value):
                queries += 1
                why = _query_ok(lit.value, allowed)
                if why is not None:
                    hit(src.path, lit.line, f'`matchMedia("{lit.value}")` {why}', "breakpoint")
        # (c) the dialog primitive: one-press verbs never inside, merge's foot never outside.
        spans = _dialog_spans(src)
        dialogs += len(spans)

        def inside(offset: int, spans: list[tuple[int, int]] = spans) -> bool:
            return any(start <= offset < end for start, end in spans)

        leaving = {word: verb for verb in no_foot for word in pressed.get(verb, ())}
        for start, end in spans:
            for m in JSX_TEXT.finditer(src.blank, start, end):
                text = m.group(1).strip()
                if text in leaving:
                    hit(
                        src.path,
                        src.line_of(m.start(1)),
                        f"*{text}* sits inside the dialog primitive — `{leaving[text]}` is undone "
                        "in one press on the same face, so it is never guarded by a confirm (a "
                        "confirm "
                        "on a reversible act trains the click-through that then fires on merge)",
                        "leaving-in-dialog",
                    )
        for lit in src.literals:
            if lit.value in leaving and inside(lit.start) and not _source.is_key(src, lit):
                hit(
                    src.path,
                    lit.line,
                    f"*{lit.value}* sits inside the dialog primitive — `{leaving[lit.value]}` is "
                    "undone in one press on the same face, so it is never guarded by a confirm",
                    "leaving-in-dialog",
                )
        for m in FOOT_CALL.finditer(src.code):
            close = _close_paren(src.code, m.end() - 1)
            called = [lit.value for lit in src.literals if m.end() <= lit.start < close]
            verb = called[-1] if called else ""
            if verb == "merge" and not spans:
                hit(
                    src.path,
                    src.line_of(m.start()),
                    '`footAct(…, "merge")` in a module that draws no dialog — merge is the one '
                    "verb no press undoes, so its press is the confirm's foot and nowhere else",
                    "merge-outside-confirm",
                )

    for sheet in sheets:
        for rule in sheet.rules:
            if not any(SEAT_SELECTOR.search(selector) for selector in rule.selectors):
                continue
            for decl in rule.decls:
                value = decl.value.strip().lower()
                if decl.prop == "order" or (
                    decl.prop in ("flex-direction", "flex-flow") and "-reverse" in value
                ):
                    hit(
                        sheet.path,
                        decl.line,
                        f"`{decl.prop}: {decl.value.strip()}` on a `[data-seat]` rule reorders the "
                        "seat's acts — DOM order is the verb table's order (*Archive* last), and a "
                        "face that shows another order than the census reads has two orders",
                        "seat-reordered",
                    )
        text = _css.strip_comments(sheet.text, line_comments=False)
        for m in MEDIA.finditer(text):
            query = m.group(1).strip()
            if not WIDTH_FEATURE.search(query):
                continue
            queries += 1
            why = _query_ok(query, allowed)
            if why is not None:
                hit(
                    sheet.path,
                    text.count("\n", 0, m.start()) + 1,
                    f"`@media {query}` {why}",
                    "breakpoint",
                )

    # A drawer line with no reason: the block is outside this rule's roots, so
    # the finding is anchored on the tree it governs and names its own line.
    for rel, line, declared in unreasoned:
        hit(
            "/".join(_css.SRC_ROOT),
            1,
            f"`{declared}` ({rel}:{line}) declares a breakpoint with no reason — a declared "
            "breakpoint carries its reason after an em dash, at least "
            f"{MIN_REASON} characters: a product's design ruling is its own, and a value with "
            "no reason is a value nobody can revisit",
            "breakpoint",
        )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(scripts) + len(sheets),
                    "scripts": len(scripts),
                    "stylesheets": len(sheets),
                    "family_verbs": len(family),
                    "dialogs": dialogs,
                    "width_queries": queries,
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
