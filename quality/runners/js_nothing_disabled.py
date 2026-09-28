"""Nothing is disabled — the runner half. (patterns.md §4)

    python3 quality/runners/js_nothing_disabled.py <root> [<root> …]

THE CLOSED QUESTION: does anything under `frontend/src/` disable a control? A
disabled control says *no* without saying *why*: the reader sees an act, presses
it, and nothing happens — no sentence, no remedy, no way forward. The book's act
vocabulary has three answers and none of them is disabled: an act the role may
not take is ABSENT; an act that is working says its verb's progressive
(*Saving…*) and stays pressable; an act that cannot run yet is pressed and the
server's refusal answers it, in the refusal seat, with its remedies.

WHAT COUNTS, in a script: a `disabled` or `aria-disabled` attribute on a JSX
element (bare, `={…}` or `="…"`); a `disabled` key in an object literal or a
type (`{ disabled: busy }`, `disabled?: boolean` — a props type that offers the
switch is the switch); a `.disabled =` assignment; a `setAttribute("disabled")`
or `toggleAttribute("disabled")`. In a stylesheet: a selector naming
`:disabled`, `[disabled]` or `[aria-disabled]` — a face styled for a state the
book says never exists — and a `pointer-events: none` or `cursor: not-allowed`
declaration in a rule whose subject is a PRESSABLE: the same dead control,
spelled in CSS instead of an attribute (`.act[data-busy] { pointer-events: none }`).

THE PRESSABLES are rule 67's population (`js_focus_ring.py`), not a second
list: a subject compound naming `a`, `button`, `summary` or a pressed
`[role=…]`, or a class some stylesheet writes on one of those, gives
`cursor: pointer`, or a screen puts on one as a host element. The element and
role sets and the selector reader are imported from that runner; the class
walk is mirrored in `pressable_classes` below because that runner holds it
inline in its `main`, and it keeps the same three clauses. A subject that is a
pseudo-element (`button::before`) or sits inside a pressable (`button svg`) is
decoration, not the control, and is not read. The WORD in prose (a copy string, a comment, a longer
identifier such as `wasDisabledBy`) is not a switch and is not read.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _css, _source  # noqa: E402
from quality.runners import js_focus_ring as _ring  # noqa: E402

ATTR = re.compile(r"(?<![\w$.-])(aria-disabled|disabled)(?![\w$-])")
KEY = re.compile(r"(?<![\w$.-])disabled\s*\??\s*:(?!:)")
ASSIGN = re.compile(r"\.disabled\s*=(?!=)")
SELECTOR = re.compile(r":disabled\b|\[\s*(?:aria-)?disabled\b")
#: property -> the value that makes a pressable dead to the pointer.
DEAD_TO_THE_POINTER = {"pointer-events": "none", "cursor": "not-allowed"}

WHY = (
    "nothing is disabled (patterns.md §4): an act the role may not take is absent, an act at "
    "work says its verb's progressive and stays pressable, and an act that cannot run yet is "
    "answered by the server's refusal — a disabled control says no without saying why"
)


def pressable_classes(population: list[_css.Sheet]) -> set[str]:
    """Every class rule 67's derivation knows as pressable (see the module docstring)."""
    classes: set[str] = set()
    for sheet in population:
        for rule in sheet.rules:
            is_pointer = any(
                d.prop == "cursor" and d.value.strip().lower() == "pointer" for d in rule.decls
            )
            for selector in rule.selectors:
                element, names, role, _ = _ring._compound(selector)
                if element in _ring.ELEMENTS or role in _ring.ROLES or is_pointer:
                    classes.update(names)
        if not sheet.is_css:
            for m in _ring._HOST.finditer(sheet.text):
                named = _ring._CLASSNAME.search(m.group(2))
                if named:
                    classes.update(named.group(1).split())
            for m in _ring._HOST_ROLE.finditer(sheet.text):
                named = _ring._CLASSNAME.search(m.group(0))
                if m.group(1) in _ring.ROLES and named:
                    classes.update(named.group(1).split())
    return classes


def presses(selector: str, classes: set[str]) -> bool:
    """Is this selector's subject a pressable itself (never a pseudo-element of one)?"""
    if "::" in _ring._last_compound(selector):
        return False
    element, names, role, pseudos = _ring._compound(selector)
    if pseudos & {"before", "after", "first-letter", "first-line"}:
        return False
    return element in _ring.ELEMENTS or role in _ring.ROLES or bool(names & classes)


def main(argv: list[str]) -> int:
    findings: list[dict] = []
    scripts = _source.scripts(argv)
    population = _css.population(argv, frozenset())
    sheets = [s for s in population if s.is_css]
    classes = pressable_classes(population)

    for src in scripts:
        seen: set[int] = set()
        for tag in _source.tags(src):
            for m in ATTR.finditer(tag.attrs):
                at = tag.start + 1 + len(tag.name) + m.start()
                line = src.line_of(at)
                seen.add(line)
                findings.append(
                    {
                        "path": src.path,
                        "line": line,
                        "msg": f"`<{tag.name} {m.group(1)}>` disables a control — {WHY}",
                        "klass": "disabled",
                    }
                )
        for pattern, shape in ((KEY, "a `disabled` key"), (ASSIGN, "a `.disabled =` assignment")):
            for m in pattern.finditer(src.blank):
                line = src.line_of(m.start())
                if line in seen:
                    continue
                seen.add(line)
                findings.append(
                    {
                        "path": src.path,
                        "line": line,
                        "msg": f"{shape} offers the switch that disables a control — {WHY}",
                        "klass": "disabled",
                    }
                )
        for lit in src.literals:
            if lit.value not in ("disabled", "aria-disabled"):
                continue
            head = src.code[max(0, lit.start - 30) : lit.start]
            if not (_source.is_key(src, lit) or re.search(r"(?:set|toggle)Attribute\(\s*$", head)):
                continue
            if lit.line in seen:
                continue
            seen.add(lit.line)
            findings.append(
                {
                    "path": src.path,
                    "line": lit.line,
                    "msg": f"`{lit.value}` set by name disables a control — {WHY}",
                    "klass": "disabled",
                }
            )

    for sheet in sheets:
        for rule in sheet.rules:
            for selector in rule.selectors:
                if SELECTOR.search(selector):
                    findings.append(
                        {
                            "path": sheet.path,
                            "line": rule.line,
                            "msg": f"the selector `{selector}` styles a disabled state — {WHY}",
                            "klass": "disabled",
                        }
                    )
            dead = [
                d
                for d in rule.decls
                if d.prop in DEAD_TO_THE_POINTER
                and (_css.value_tokens(d.value.lower()) or [""])[0] == DEAD_TO_THE_POINTER[d.prop]
            ]
            if not dead:
                continue
            subject = next((sel for sel in rule.selectors if presses(sel, classes)), None)
            if subject is None:
                continue
            for d in dead:
                findings.append(
                    {
                        "path": sheet.path,
                        "line": d.line,
                        "msg": (
                            f"`{d.prop}: {DEAD_TO_THE_POINTER[d.prop]}` on the pressable "
                            f"`{subject}` disables a control — {WHY}"
                        ),
                        "klass": "disabled",
                    }
                )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(scripts) + len(sheets),
                    "scripts": len(scripts),
                    "stylesheets": len(sheets),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
