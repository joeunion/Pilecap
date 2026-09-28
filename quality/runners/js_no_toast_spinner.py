"""No toast, no spinner, no shimmer — the runner half. (patterns.md §13, §17)

    python3 quality/runners/js_no_toast_spinner.py <root> [<root> …]

THE CLOSED QUESTION: does anything under `frontend/src/` draw one of the three
faces the book rules out by name? A TOAST is an outcome that leaves before it
is read, over content it was not about (§17: an outcome is a band under the
head, and it stays). A SPINNER and a SHIMMER are motion that says *wait* and
nothing else (§13: loading is still shapes at the content's heights — the
reader sees what is coming, not that something is).

THE FAMILIES, closed and named — the rule keys on words, so its reach is
exactly this list:

* in a script: an identifier (an import, a component, a hook, a call) whose
  words include `toast`, `toaster`, `snackbar`, `spinner`, `shimmer` or
  `loader` — `LoadingSpinner`, `useToast`, `toast.success(…)`, `<Shimmer />`,
  `<Loader2 />` (never `downloader` or `preload`: a word, not a substring) — or is
  `CircularProgress` / `ActivityIndicator`; an import from a package whose
  name carries one of those words or is one of the named toast and loader
  libraries; a `className` literal holding a class from the class family
  below;
* in a stylesheet: a class selector or an `@keyframes` name whose words
  include `toast`, `toaster`, `snackbar`, `spinner`, `spin`, `shimmer` or
  `loader`.

A still skeleton (`WelcomeSkeleton`, `aria-busy`) is the book's loading face
and is not in any family. The words in prose — a copy string, a comment — are
not read.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _source  # noqa: E402

#: word -> family. The identifier family; a class name also counts `spin`.
IDENT_WORDS = {
    "toast": "toast",
    "toaster": "toast",
    "snackbar": "toast",
    "spinner": "spinner",
    "shimmer": "shimmer",
    "loader": "spinner",
}
CLASS_WORDS = {**IDENT_WORDS, "spin": "spinner"}
IDENT_NAMES = {"CircularProgress": "spinner", "ActivityIndicator": "spinner"}
PACKAGES = {
    "sonner": "toast",
    "notistack": "toast",
    "react-toastify": "toast",
    "react-hot-toast": "toast",
    "react-spinners": "spinner",
    "react-loader-spinner": "spinner",
    "react-loading-skeleton": "shimmer",
}

WHY = {
    "toast": "there are no toasts (patterns.md §17): an outcome is a band under the head that "
    "stays until it is read, never a notice that leaves on a timer over content it was not about",
    "spinner": "there are no spinners (patterns.md §13): loading is still shapes at the "
    "content's heights, so the reader sees what is coming rather than that something is",
    "shimmer": "there is no shimmer (patterns.md §13): loading is STILL shapes at the content's "
    "heights — motion that only says wait is the spinner again",
}

IDENT = re.compile(r"(?<![\w$])[A-Za-z_$][\w$]*")
CLASSNAME = re.compile(r"\bclass(?:Name)?\s*=\s*\{?\s*$")
KEYFRAMES = re.compile(r"@keyframes\s+([A-Za-z_-][\w-]*)")
CLASS_SELECTOR = re.compile(r"\.(-?[A-Za-z_][\w-]*)")


def family_of(name: str, table: dict[str, str]) -> str | None:
    for word in _source.words(name):
        if word in table:
            return table[word]
    return None


def main(argv: list[str]) -> int:
    findings: list[dict] = []
    scripts = _source.scripts(argv)
    sheets = _source.sheets(argv)

    def add(path: str, line: int, what: str, family: str) -> None:
        findings.append(
            {"path": path, "line": line, "msg": f"{what} — {WHY[family]}", "klass": family}
        )

    for src in scripts:
        seen: set[tuple[int, str]] = set()
        for m in IDENT.finditer(src.blank):
            name = m.group(0)
            family = IDENT_NAMES.get(name) or family_of(name, IDENT_WORDS)
            if family is None:
                continue
            line = src.line_of(m.start())
            if (line, name) in seen:
                continue
            seen.add((line, name))
            add(src.path, line, f"`{name}` is a {family}", family)
        for lit in src.literals:
            if _source.is_specifier(src, lit):
                package = lit.value
                family = PACKAGES.get(package) or PACKAGES.get(package.split("/", 1)[0])
                if family is None and not package.startswith((".", "@/")):
                    family = family_of(package, IDENT_WORDS)
                if family is not None:
                    add(src.path, lit.line, f"the import of `{package}` brings a {family}", family)
                continue
            head = src.code[max(0, lit.start - 30) : lit.start]
            if not CLASSNAME.search(head):
                continue
            for klass in lit.value.split():
                family = family_of(klass, CLASS_WORDS)
                if family is not None:
                    add(src.path, lit.line, f"the class `{klass}` is a {family}", family)

    for sheet in sheets:
        for rule in sheet.rules:
            for selector in rule.selectors:
                for klass in CLASS_SELECTOR.findall(selector):
                    family = family_of(klass, CLASS_WORDS)
                    if family is not None:
                        add(sheet.path, rule.line, f"the class `.{klass}` is a {family}", family)
        for m in KEYFRAMES.finditer(sheet.text):
            family = family_of(m.group(1), CLASS_WORDS)
            if family is not None:
                line = sheet.text.count("\n", 0, m.start()) + 1
                add(
                    sheet.path,
                    line,
                    f"the animation `@keyframes {m.group(1)}` is a {family}",
                    family,
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
