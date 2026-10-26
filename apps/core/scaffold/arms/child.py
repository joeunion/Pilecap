"""The `child` arm: an append-only row under a noun of the same app."""

from __future__ import annotations

import builtins
import io
import keyword
import re
import tokenize
from pathlib import Path
from typing import Any

from apps.core.lexicon import looks_plural
from apps.core.scaffold.arms._common import NOUN_WORD, Arms, _refuse, class_names, lexicon
from apps.core.scaffold.copier import SOURCE_NOUN, Golden, names_in, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("child",)

#: The child golden's own row word, singular, as its class names it under the parent noun.
GOLDEN_CHILD = "Entry"
#: The verb of the child's one write service, `record_<parent>_<child>`: house rule 16 reads it.
CHILD_SERVICE_VERB = "record"


def plural_of(word: str) -> str:
    """`entry` → `entries`, `box` → `boxes`, `line_item` → `line_items`: the last word's plural."""
    if re.search(r"[^aeiou]y$", word):
        return f"{word[:-1]}ies"
    if re.search(r"(s|x|z|ch|sh)$", word):
        return f"{word}es"
    return f"{word}s"


#: A golden line's bare locals re-spelled, by column: `{line: ((column, golden, new), ...)}`.
Held = dict[str, tuple[tuple[int, str, str], ...]]


class ChildClash(ValueError):
    """A child whose word, and its full name too, the golden already spells as another name."""


def child_forms(child: str) -> tuple[tuple[str, str], ...]:
    """The golden child's tokens and the child's, in every case the golden spells them."""
    one, many = snake(child), plural_of(snake(child))
    pascal = "".join(part.title() for part in many.split("_"))
    golden = snake(GOLDEN_CHILD)
    golden_many = plural_of(golden)
    return (
        (golden_many.title(), pascal),
        (golden_many.upper(), many.upper()),
        (golden_many, many),
        (GOLDEN_CHILD, child),
        (golden.upper(), one.upper()),
        (golden, one),
    )


def human(child: str) -> tuple[str, str]:
    """`GerminationTest` → (`germination test`, `germination tests`): the words prose says."""
    one = snake(child)
    return one.replace("_", " "), plural_of(one).replace("_", " ")


def _prose_pattern(token: str) -> re.Pattern[str]:
    """`token` as a word of a sentence: space before it, a space, mark or quote after it."""
    return re.compile(rf"(?<=[\s(]){token}(?=[\s,.;:!?'\")]|$)")


def prose_held(texts: dict[str, str], child: str) -> Held:
    """The golden child's words in strings and comments, re-said in words (rule 41 titles)."""
    one, many = human(child)
    golden = snake(GOLDEN_CHILD)
    words = ((plural_of(golden), many), (golden, one))
    held: dict[str, set[tuple[int, str, str]]] = {}
    for text in texts.values():
        rows = text.splitlines()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        except (tokenize.TokenError, SyntaxError):
            tokens = []
        for token in tokens:
            if token.type not in (tokenize.STRING, tokenize.COMMENT):
                continue
            for index, piece in enumerate(token.string.split("\n")):
                row = token.start[0] + index
                offset = token.start[1] if index == 0 else 0
                for old, new in words:
                    for match in _prose_pattern(old).finditer(piece):
                        line = rows[row - 1]
                        held.setdefault(line, set()).add((offset + match.start(), old, new))
    return {line: tuple(sorted(at)) for line, at in held.items()}


def _bounded(token: str) -> re.Pattern[str]:
    """`token` as a whole segment of a word; capitalised, only after the golden noun."""
    if token.isupper():
        return re.compile(rf"(?<![A-Z0-9]){token}(?![A-Z0-9])")
    if token[0].isupper():
        return re.compile(rf"(?:(?<={SOURCE_NOUN})|(?<![A-Za-z0-9])){token}(?![a-z0-9])")
    return re.compile(rf"(?<![A-Za-z0-9]){token}(?![a-z0-9])")


def child_held(texts: dict[str, str], child: str) -> tuple[Held, list[str]]:
    """The golden's bare locals whose new spelling it already uses, re-spelled in full."""
    forms = dict(child_forms(child))
    tokens = {rel: names_in(text) for rel, text in texts.items()}
    used: dict[str, str] = {}
    for rel, found in tokens.items():
        for token in found:
            if token.string not in forms:
                used.setdefault(token.string, f"{rel}:{token.start[0]}")
    builtin = set(dir(builtins))

    def taken(word: str) -> str:
        if keyword.iskeyword(word):
            return "a Python keyword"
        return used.get(word) or ("a Python builtin" if word in builtin else "")

    respelled: dict[str, str] = {}
    said: list[str] = []
    for old, new in forms.items():
        site = taken(new) if old != new else ""
        if not site or not any(t.string == old for found in tokens.values() for t in found):
            continue
        full = f"{SOURCE_NOUN}{new}" if new[0].isupper() else f"{snake(SOURCE_NOUN)}_{new}"
        if again := taken(full):
            raise ChildClash(
                f"{child}'s form `{new}` is an identifier the golden already uses ({site}), and "
                f"so is its full name `{full}` ({again}) — name the child something else."
            )
        respelled[old] = full
        said.append(
            f"`{old}` → `{full}`: `{new}` is an identifier the golden already uses ({site})"
        )
    held: dict[str, set[tuple[int, str, str]]] = {}
    for found in tokens.values():
        for token in found:
            if token.string in respelled:
                key = token.line.rstrip("\n")
                at = (token.start[1], token.string, respelled[token.string])
                held.setdefault(key, set()).add(at)
    for line, ats in prose_held(texts, child).items():
        held.setdefault(line, set()).update(ats)
    return {line: tuple(sorted(at)) for line, at in held.items()}, said


def child_lines(line: str, child: str, held: Held | None = None) -> str:
    """A golden `Entry` line as the child `child` says it: class, snake, plural, constants."""
    for column, old, new in reversed((held or {}).get(line, ())):
        line = line[:column] + new + line[column + len(old) :]
    for old, new in child_forms(child):
        line = _bounded(old).sub(new, line)
    for one in {snake(child), human(child)[0]}:
        if not one.startswith(("a", "e", "i", "o", "u")):
            line = re.sub(rf"\b([Aa])n (?={one}\b)", r"\1 ", line)
    return line


class ChildArm(Arms):
    """`scaffold child`."""

    def child(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`child <app> <Parent> <Child>`: an append-only row under a noun, its doors, its tests."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse("child takes <app> <Parent> <Child> — e.g. `child orders Order Line`.")
        label, parent, child = words
        if not NOUN_WORD.match(child) or looks_plural(snake(child)):
            raise _refuse(
                f"{child!r} is not a singular PascalCase noun — house rule 16: models are "
                "singular, and the child names the model the copy declares."
            )
        if CHILD_SERVICE_VERB not in lexicon(root):
            raise _refuse(
                f"`{CHILD_SERVICE_VERB}` is not a declared service verb — house rule 16 would "
                f"refuse `{CHILD_SERVICE_VERB}_{snake(parent)}_{snake(child)}`."
            )
        if not options["check"]:
            models = root / "apps" / label / "models.py"
            text = models.read_text() if models.is_file() else ""
            if not re.search(rf"^class {parent}\(", text, re.M):
                raise _refuse(
                    f"apps/{label}/models.py declares no `{parent}` — a child hangs off a noun "
                    f"`scaffold noun {label} {parent}` wrote; scaffold the noun first."
                )
            if re.search(rf"^class {parent}{child}\(", text, re.M):
                raise _refuse(f"apps/{label}/models.py already declares `{parent}{child}`.")
            many = plural_of(snake(child))
            if many in class_names(text, parent):
                raise _refuse(
                    f"`{parent}` already has a `{many}` — the child's rows are read as "
                    f"`{snake(parent)}.{many}`; name the child something else."
                )
        texts = {rel: (root / golden.path(rel)).read_text() for rel in golden.files}
        try:
            held, said = child_held(texts, child)
        except ChildClash as clash:
            raise _refuse(f"{clash} Nothing was written.") from clash
        self.additive(
            root,
            golden,
            label,
            parent,
            lambda line: child_lines(line, child, held),
            options,
            migration=f"{snake(parent)}_{snake(child)}",
        )
        for line in said:
            moved = line.replace(snake(SOURCE_NOUN), snake(parent)).replace(SOURCE_NOUN, parent)
            self.stdout.write(f"renamed: {moved}")
