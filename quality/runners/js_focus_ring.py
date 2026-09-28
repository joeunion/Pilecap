"""One focus ring, and the act floor's static half. (patterns.md §26)

    python3 quality/runners/js_focus_ring.py <root> [<root> …]

THE POPULATION IS THE PRESSABLES, derived from the text and never listed:

* a PRESSABLE ELEMENT is `a`, `button`, `summary` or a `[role=…]` a person
  presses (button, link, tab, menuitem, switch, checkbox, radio, option) —
  wherever a stylesheet under `frontend/src/` styles one, or a screen renders
  one as a host element (`<a …>`, `<button …>`, `<summary …>`);
* a PRESSABLE CLASS is a class a stylesheet writes on a pressable element
  (`button.act`), gives `cursor: pointer`, or a screen puts on a pressable host
  element (`<button className="act">`).

TWO CLOSED QUESTIONS OVER IT:

1. **One ring.** Every pressable element and every pressable class has a
   `:focus-visible` rule whose declarations name the ONE ring token,
   `var(--focus-ring)`. A pressable with no ring is a control a keyboard can
   reach and nobody can see; a ring of its own is a second ring.
2. **The act floor, static half.** Every pressable CLASS consumes
   `var(--act-min)` in a rule of its own (not a `:hover` or `:focus` one) — its
   target is at least the floor tall and wide. Bare elements answer this
   question through the tokens layer's own floor rule, and an `a` inside a
   sentence is the named exception, so elements are asked the first question
   only. The measured box at the phone width is the other half and needs a
   rendered browser; it is not a house rule here.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _css  # noqa: E402

ELEMENTS = frozenset({"a", "button", "summary"})
ROLES = frozenset({"button", "link", "tab", "menuitem", "switch", "checkbox", "radio", "option"})
RING = re.compile(r"var\(\s*--focus-ring\s*[,)]")
ACT_MIN = re.compile(r"var\(\s*--act-min\s*[,)]")
_COMBINATOR = re.compile(r"\s*[>+~]\s*|\s+")
_CLASS = re.compile(r"\.([A-Za-z_][\w-]*)")
_ROLE = re.compile(r"\[\s*role\s*=\s*[\"']?([a-z]+)[\"']?\s*\]")
_PSEUDO = re.compile(r"::?[A-Za-z-]+(?:\([^)]*\))?")
_ELEMENT = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)")
_HOST = re.compile(r"<(a|button|summary)\b([^>]*)>", re.S)
_HOST_ROLE = re.compile(r"<[A-Za-z][\w.]*\b[^>]*\brole=[\"']([a-z]+)[\"'][^>]*>", re.S)
_CLASSNAME = re.compile(r"\bclassName=[\"']([^\"']+)[\"']")


def _last_compound(selector: str) -> str:
    depth = 0
    cut = 0
    for i, ch in enumerate(selector):
        if ch in "([":
            depth += 1
        elif ch in ")]" and depth:
            depth -= 1
        elif depth == 0 and (ch.isspace() or ch in ">+~"):
            cut = i + 1
    return selector[cut:].strip()


def _compound(selector: str) -> tuple[str, frozenset[str], str, frozenset[str]]:
    """(element, classes, role, pseudo-classes) of a selector's subject compound."""
    last = _last_compound(selector)
    pseudos = frozenset(p.split("(")[0].lstrip(":") for p in _PSEUDO.findall(last))
    bare = _PSEUDO.sub("", last)
    element = _ELEMENT.match(bare).group(1).lower() if _ELEMENT.match(bare) else ""
    role = _ROLE.search(bare).group(1) if _ROLE.search(bare) else ""
    return element, frozenset(_CLASS.findall(bare)), role, pseudos


def main(argv: list[str]) -> int:
    sheets = _css.population(argv, frozenset())
    #: subject -> (path, line) where it was first seen. Subjects are
    #: ("element", name) / ("role", name) / ("class", name).
    subjects: dict[tuple[str, str], tuple[str, int]] = {}
    ringed: set[tuple[str, str]] = set()
    floored: set[str] = set()
    pointer: dict[str, tuple[str, int]] = {}

    def see(subject: tuple[str, str], path: str, line: int) -> None:
        subjects.setdefault(subject, (path, line))

    for sheet in sheets:
        for rule in sheet.rules:
            text = " ".join(f"{d.prop}: {d.value}" for d in rule.decls)
            has_ring = RING.search(text) is not None
            has_floor = ACT_MIN.search(text) is not None
            is_pointer = any(
                d.prop == "cursor" and d.value.strip().lower() == "pointer" for d in rule.decls
            )
            for selector in rule.selectors:
                element, classes, role, pseudos = _compound(selector)
                pressable_el = element in ELEMENTS or role in ROLES
                subject_el = (
                    ("element", element)
                    if element in ELEMENTS
                    else ("role", role)
                    if role in ROLES
                    else None
                )
                if subject_el and not classes:
                    see(subject_el, sheet.path, rule.line)
                    if "focus-visible" in pseudos and has_ring:
                        ringed.add(subject_el)
                for name in classes:
                    if pressable_el or is_pointer:
                        see(("class", name), sheet.path, rule.line)
                    if is_pointer:
                        pointer.setdefault(name, (sheet.path, rule.line))
                    if "focus-visible" in pseudos and has_ring:
                        ringed.add(("class", name))
                    if not pseudos and has_floor:
                        floored.add(name)
        if not sheet.is_css:
            for m in _HOST.finditer(sheet.text):
                line = sheet.text.count("\n", 0, m.start()) + 1
                see(("element", m.group(1)), sheet.path, line)
                named = _CLASSNAME.search(m.group(2))
                if named:
                    for name in named.group(1).split():
                        see(("class", name), sheet.path, line)
            for m in _HOST_ROLE.finditer(sheet.text):
                if m.group(1) in ROLES:
                    line = sheet.text.count("\n", 0, m.start()) + 1
                    see(("role", m.group(1)), sheet.path, line)
                    named = _CLASSNAME.search(m.group(0))
                    if named:
                        for name in named.group(1).split():
                            see(("class", name), sheet.path, line)

    findings: list[dict] = []
    for subject, (path, line) in sorted(subjects.items()):
        kind, name = subject
        label = {"element": f"`{name}`", "role": f'`[role="{name}"]`', "class": f"`.{name}`"}[kind]
        if subject not in ringed:
            findings.append(
                {
                    "path": path,
                    "line": line,
                    "msg": (
                        f"the pressable {label} has no `:focus-visible` rule naming "
                        "`var(--focus-ring)` — every pressable wears the ONE ring when the "
                        "keyboard reaches it (patterns.md §26); a control a keyboard can "
                        "reach and nobody can see is the defect"
                    ),
                    "klass": "no-ring",
                }
            )
        if kind == "class" and name not in floored:
            findings.append(
                {
                    "path": path,
                    "line": line,
                    "msg": (
                        f"the pressable class {label} consumes no `var(--act-min)` in a rule "
                        "of its own — every pressable class is at least the act floor tall "
                        "and wide (patterns.md §26, the static half)"
                    ),
                    "klass": "no-act-min",
                }
            )

    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": len(sheets),
                    "stylesheets": sum(1 for s in sheets if s.is_css),
                    "pressables": len(subjects),
                    "pressable_classes": sum(1 for k, _ in subjects if k == "class"),
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
