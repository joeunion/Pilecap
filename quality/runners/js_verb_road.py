"""A noun face's road equals the verb doors its wire serves — the runner half. (patterns.md §20)

    python3 quality/runners/js_verb_road.py <root> [<root> …]

THE CLOSED QUESTION, BOTH WAYS: for every noun face — a directory under
`frontend/src/screens/` — do the verbs its `road.ts` declares equal the verb
doors `frontend/openapi.json` carries for that noun?

* **A road verb with no door** is a face drawing an act the server does not
  serve (`road-without-door`): the act would be pressed and 404.
* **A door the road does not declare** is a verb the wire offers and the face
  forgot (`door-without-road`): the reader cannot take an act the server
  would answer.
* **A face with doors and no road** declares nothing for the family's faces
  to be measured against (`road-missing`).
* **The bulk door's verbs** (the request body's `verb` discriminator) equal
  the road's `bulk:` list, both ways, the same two classes.

A WIRE NOUN WITH NO FACE is counted (`unfaced_nouns`) and is not red: a
capability on REST need not be on a screen (fe-conventions §11 — rule 17
weakens to coverage), and a face that exists must reach it through its road.

THE WIRE, READ FROM THE DOCUMENT OF RECORD: a verb door is an operation whose
`operationId` names the verb and the noun — `…_archive_<noun>_route`,
`…_restore_…`, `…_move_…`, `…_duplicate_…`, `…_merge_…` (POST),
`…_update_<noun>_route` (PATCH, the versioned Edit), `…_list_<noun>_history_route`
(GET), and `…_bulk_<nouns>_route` (POST, its verbs the body's discriminator).
The noun is the `operationId`'s, in kebab case (`widget_policy` →
`widget-policy`); a road names its noun in its `noun:` field, and a face
directory with no road is read under its own name.

IMPORT AND ATTACH RIDE OTHER APPS' DOORS, so their door for a noun is read
from what those doors declare about it: **a noun has an import door** when the
imports app's stage operation (`…_create_import_route`, POST) takes it as a
`kind` — its request body's `kind` enum names every declared importer; **a
noun has an attach door** when its own detail read (`…_retrieve_<noun>`, GET)
answers `tags` — the attach owners' declaration, a noun listing tags among its
attachments answering them on its detail (house rule 74). Both are judged both
ways, like every other door.

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

DOCUMENT = "frontend/openapi.json"
SCREENS = ("frontend", "src", "screens")
ROAD_FILE = "road.ts"

#: operationId shape -> (the verb, the method it must be).
DOORS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"_(archive|restore|move|duplicate|merge)_([a-z0-9_]+?)_route$"), "", "post"),
    (re.compile(r"_(update)_([a-z0-9_]+?)_route$"), "", "patch"),
    (re.compile(r"_list_([a-z0-9_]+?)_history_route$"), "history", "get"),
)
BULK = re.compile(r"_bulk_([a-z0-9_]+?)_route$")
#: The imports app's stage operation: its body's `kind` enum is every noun an importer takes.
IMPORT_STAGE = re.compile(r"_create_import_route$")
#: A noun's own detail read: its answer carrying `tags` is the noun's attach door.
DETAIL = re.compile(r"_retrieve_([a-z0-9_]+)$")
#: Verbs whose doors this runner does not read; a road may declare them unjudged. None today.
UNMEASURED: frozenset[str] = frozenset()


def _schema(document: dict, node: object) -> dict:
    """`node`, or the component its `$ref` names — one hop, the shape the document writes."""
    if not isinstance(node, dict):
        return {}
    ref = node.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        found = ((document.get("components") or {}).get("schemas") or {}).get(ref.rsplit("/", 1)[1])
        return found if isinstance(found, dict) else {}
    return node


_NOUN = re.compile(r"(?<![\w$])noun\s*:\s*[\"']([^\"'\n]+)[\"']")


def _kebab(name: str) -> str:
    return name.replace("_", "-")


def _singular(plural: str) -> str:
    if plural.endswith("ies"):
        return plural[:-3] + "y"
    return plural[:-1] if plural.endswith("s") else plural


def wire(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]], bool]:
    """(noun -> its single verb doors, noun -> its bulk door's verbs, the document was read)."""
    path = root / DOCUMENT
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}, False
    doors: dict[str, set[str]] = {}
    bulk: dict[str, set[str]] = {}
    for item in (document.get("paths") or {}).values():
        for method, operation in (item or {}).items():
            if not isinstance(operation, dict):
                continue
            op = str(operation.get("operationId") or "")
            for pattern, fixed, wanted in DOORS:
                m = pattern.search(op)
                if m and method.lower() == wanted:
                    verb = fixed or m.group(1)
                    noun = m.group(1) if fixed else m.group(2)
                    doors.setdefault(_kebab(noun), set()).add(verb)
                    break
            if IMPORT_STAGE.search(op) and method.lower() == "post":
                body = _schema(
                    document,
                    (
                        ((operation.get("requestBody") or {}).get("content") or {}).get(
                            "application/json"
                        )
                        or {}
                    ).get("schema"),
                )
                kinds = ((body.get("properties") or {}).get("kind") or {}).get("enum") or []
                for kind in kinds:
                    if isinstance(kind, str):
                        doors.setdefault(_kebab(kind), set()).add("import")
            m = DETAIL.search(op)
            if m and method.lower() == "get":
                answer = _schema(
                    document,
                    (
                        (
                            ((operation.get("responses") or {}).get("200") or {}).get("content")
                            or {}
                        ).get("application/json")
                        or {}
                    ).get("schema"),
                )
                if "tags" in (answer.get("properties") or {}):
                    doors.setdefault(_kebab(m.group(1)), set()).add("attach")
            m = BULK.search(op)
            if m and method.lower() == "post":
                schema = (
                    ((operation.get("requestBody") or {}).get("content") or {}).get(
                        "application/json"
                    )
                    or {}
                ).get("schema") or {}
                verbs = set(((schema.get("discriminator") or {}).get("mapping") or {}).keys())
                bulk.setdefault(_kebab(_singular(m.group(1))), set()).update(verbs)
    return doors, bulk, True


def _array(src: _source.Source, name: str) -> tuple[list[str], int] | None:
    """The string literals of `name: [ … ]` in the road, and the line it opens on."""
    m = re.search(rf"(?<![\w$]){name}\s*:\s*\[", src.code)
    if not m:
        return None
    end = src.code.find("]", m.end())
    end = len(src.code) if end == -1 else end
    values = [lit.value for lit in src.literals if m.end() <= lit.start < end]
    return values, src.line_of(m.start())


def faces(root: Path) -> list[tuple[Path, str]]:
    """(directory, noun) per face directory under screens/: the road's `noun:`, else its name."""
    base = root.joinpath(*SCREENS)
    out: list[tuple[Path, str]] = []
    if not base.is_dir():
        return out
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        modules = [
            p
            for p in _css.files_under(directory.relative_to(root))
            if p.suffix in _source.SCRIPT_SUFFIXES and not _source.exempt(p)
        ]
        if not modules:
            continue
        road = directory / ROAD_FILE
        noun = directory.name
        if road.is_file():
            src = _source.read(road)
            m = _NOUN.search(src.raw) if src is not None else None
            if m:
                noun = m.group(1)
        out.append((directory, noun))
    return out


def main(argv: list[str]) -> int:
    root = Path.cwd()
    findings: list[dict] = []
    doors, bulk, read = wire(root)
    unmeasured = 0
    roads = 0

    def hit(path: str, line: int, msg: str, klass: str) -> None:
        findings.append({"path": path, "line": line, "msg": msg, "klass": klass})

    if not read:
        hit(
            DOCUMENT,
            1,
            f"`{DOCUMENT}` did not read as the document of record — every road is judged "
            "against the verb doors it serves, and with no document nothing is",
            "wire-missing",
        )

    faced: set[str] = set()
    found = faces(root)
    for directory, noun in found:
        faced.add(noun)
        served = doors.get(noun, set())
        served_bulk = bulk.get(noun, set())
        road_path = directory / ROAD_FILE
        rel = str(road_path.relative_to(root))
        if not road_path.is_file():
            if served or served_bulk:
                hit(
                    str(directory.relative_to(root)),
                    1,
                    f"the face `{directory.relative_to(root)}` draws the noun `{noun}`, whose wire "
                    "serves "
                    + ", ".join(sorted(served | {f"bulk {v}" for v in served_bulk}))
                    + ", and "
                    f"declares no `{ROAD_FILE}` — a face with verb doors declares its road once, "
                    "and "
                    "every act it draws is constructed from it",
                    "road-missing",
                )
            continue
        roads += 1
        src = _source.read(road_path)
        if src is None:
            continue
        declared = _array(src, "verbs")
        verbs, verbs_line = declared if declared is not None else ([], 1)
        declared_bulk = _array(src, "bulk")
        bulk_verbs, bulk_line = declared_bulk if declared_bulk is not None else ([], verbs_line)
        judged = [verb for verb in verbs if verb not in UNMEASURED]
        unmeasured += len(verbs) - len(judged)
        for verb in judged:
            if verb not in served:
                hit(
                    rel,
                    verbs_line,
                    f"the road for `{noun}` declares `{verb}` and `{DOCUMENT}` serves no `{verb}` "
                    f"door for `{noun}` — the face would draw an act the server does not answer",
                    "road-without-door",
                )
        for verb in sorted(served - set(verbs)):
            hit(
                rel,
                verbs_line,
                f"`{DOCUMENT}` serves a `{verb}` door for `{noun}` and its road does not declare "
                f"`{verb}` — a verb the wire offers and the face forgot; add it with its face",
                "door-without-road",
            )
        for verb in bulk_verbs:
            if verb not in served_bulk:
                hit(
                    rel,
                    bulk_line,
                    f"the road for `{noun}` declares the bulk verb `{verb}` and `{noun}`'s bulk "
                    "door "
                    "does not take it — the selection bar would offer a verb the batch refuses",
                    "road-without-door",
                )
        for verb in sorted(served_bulk - set(bulk_verbs)):
            hit(
                rel,
                bulk_line,
                f"`{noun}`'s bulk door takes `{verb}` and its road's `bulk:` does not declare it "
                "— a verb the batch offers and the selection bar forgot",
                "door-without-road",
            )

    wire_nouns = set(doors) | set(bulk)
    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {
                    "files_scanned": roads + int(read),
                    "documents": int(read),
                    "wire_nouns": len(wire_nouns),
                    "faces": len(found),
                    "roads": roads,
                    "faced_nouns": len(wire_nouns & faced),
                    "unfaced_nouns": len(wire_nouns - faced),
                    "unmeasured_verbs": unmeasured,
                },
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
