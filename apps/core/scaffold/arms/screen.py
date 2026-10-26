"""The `screen` arm: the worked face, its words, its road, and the product pages it ends at."""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from django.apps import apps
from django.core.management.base import CommandError
from django.db import models

from apps.core.lexicon import looks_plural
from apps.core.scaffold.arms._common import NOUN_WORD, Arms, _refuse
from apps.core.scaffold.copier import (
    CLIENT,
    FACE,
    GENERATED,
    ROUTES,
    Copy,
    FenceError,
    Golden,
    face_copy,
    face_golden,
    face_lines,
    face_plan,
    face_taken,
    face_write,
    rename,
    snake,
)
from apps.core.scaffold.shapes import SHAPES, adopt_verbs

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("screen",)

#: The face's closed set of labels (house rule 72): a copied word the lexicon lacks joins it here.
LEXICON = "frontend/src/copy/lexicon.ts"
LEXICON_END = "] as const;"
LEXICON_ROW = re.compile(r'^\s*"([^"]+)",\s*$', re.MULTILINE)
#: The face verb each wire door adopts (rule 77's reader names the doors; `bulk` is its own read).
FACE_VERBS = {
    "update": "version",
    "archive": "archive",
    "restore": "archive",
    "move": "move",
    "duplicate": "duplicate",
    "merge": "merge",
    "history": "history",
    "import": "import",
    "attach": "attach",
}
#: Rule 77's own reader of the wire, run beside the engine: the noun's doors as JSON.
DOORS_PROGRAM = """
import json
import sys
from pathlib import Path

from quality.runners.js_verb_road import DOCUMENT, wire

root, noun = Path(sys.argv[1]), sys.argv[2]
doors, bulk, read = wire(root)
document = json.loads((root / DOCUMENT).read_text()) if read else {}
names = {
    str(operation.get("x-url-name") or "")
    for item in (document.get("paths") or {}).values()
    for operation in (item or {}).values()
    if isinstance(operation, dict)
}
print(json.dumps({
    "read": read,
    "listed": f"{noun.replace('-', '_')}-list" in names,
    "doors": sorted(doors.get(noun, ())),
    "bulk": sorted(bulk.get(noun, ())),
}))
"""


#: The copy module's columns block: its rows are the noun's own, filled by `place_columns`.
COLUMNS_BLOCK = re.compile(r"(\n    columns: \{\n)(?:        .*\n)*?(    \},\n)")

#: The product's list page: the live read, re-read whenever the socket says the noun changed.
LIST_PAGE = """\
"use client";

/**
 * The {nouns}, read live. The route fetches; the screen renders (fe-conventions
 * §4, Law 4). The kit's socket hook re-reads the list whenever a {noun} event
 * arrives or the socket re-opens after a drop (pushes only), and its state is
 * the list's `data-board`.
 */

import {{ useEffect, useState }} from "react";

import {{ list{Nouns}, type {Noun}Page }} from "@/api/client";
import {{ useEvents }} from "@/api/use-events";
import {{ {Noun}List }} from "@/screens/{noun}/{noun}-list";
import type {{ SurfaceState }} from "@pilecap/ui/state";

export default function {Nouns}ListPage() {{
    const feed = useEvents(null, ["{noun}"]);
    const [state, setState] = useState<SurfaceState<{Noun}Page>>({{ kind: "loading" }});

    // An effect that re-runs on every change keeps its live flag (fe-conventions §6.4).
    useEffect(() => {{
        let live = true;
        void list{Nouns}(null).then((answer) => {{
            if (!live) return;
            if (answer.kind === "refused") setState({{ kind: "error", refusal: answer.refusal }});
            else if (answer.data.items.length === 0) setState({{ kind: "empty" }});
            else setState({{ kind: "ready", data: answer.data }});
        }});
        return () => {{
            live = false;
        }};
    }}, [feed.changes]);

    const shown: SurfaceState<{Noun}Page> =
        feed.refusal === null ? state : {{ kind: "error", refusal: feed.refusal }};
    return <{Noun}List state={{shown}} board={{feed.board}} />;
}}
"""

#: The product's record page: one read of the row the path names.
RECORD_PAGE = """\
"use client";

/** One {noun}, read. The route fetches; the screen renders (fe-conventions §4, Law 4). */

import {{ useParams }} from "next/navigation";
import {{ useEffect, useState }} from "react";

import {{ get{Noun}, type {Noun}Detail }} from "@/api/client";
import {{ {Noun}Record }} from "@/screens/{noun}/{noun}-record";
import type {{ SurfaceState }} from "@pilecap/ui/state";

export default function {Noun}RecordPage() {{
    const {{ id }} = useParams<{{ id: string }}>();
    const [state, setState] = useState<SurfaceState<{Noun}Detail>>({{ kind: "loading" }});

    useEffect(() => {{
        let live = true;
        void get{Noun}(id, null).then((answer) => {{
            if (!live) return;
            setState(
                answer.kind === "refused"
                    ? {{ kind: "error", refusal: answer.refusal }}
                    : {{ kind: "ready", data: answer.data }},
            );
        }});
        return () => {{
            live = false;
        }};
    }}, [id]);

    return <{Noun}Record state={{state}} />;
}}
"""

#: The product pages' rows: the staff surface's own, which the walks yield to.
PRODUCT_ROWS = """
    {{
        path: "/{page}",
        job: "List the {nouns} the acting hat can read, live.",
        primarySeat: null,
        operation: "{noun}-list",
        devOnly: false,
        surfaces: ["staff"],
    }},
    {{
        path: "/{page}/[id]",
        job: "Read one {noun_one}.",
        primarySeat: null,
        operation: "{noun}-detail",
        devOnly: false,
        surfaces: ["staff"],
    }},"""

#: The client's two reads on the noun, each path the document's, verbatim.
CLIENT_READS = """
const {LIST} = "{listed}" as const satisfies keyof paths;
const {ONE} = "{detail}" as const satisfies keyof paths;

/** The generated response types, used verbatim (Law 3). */
export type {Noun}Page =
    paths[typeof {LIST}]["get"]["responses"][200]["content"]["application/json"];
export type {Noun}Detail =
    paths[typeof {ONE}]["get"]["responses"][200]["content"]["application/json"];

/** The {nouns} the acting hat can read — the product's list page. */
export async function list{Nouns}(hat: Hat): Promise<Answer<{Noun}Page>> {{
    return request<{Noun}Page>({LIST}, hat);
}}

/** One {noun_one} — the product's record page. */
export async function get{Noun}({camel}: string, hat: Hat): Promise<Answer<{Noun}Detail>> {{
    return request<{Noun}Detail>(filled({ONE}, {{ {param}: {camel} }}), hat);
}}"""


class ScreenArm(Arms):
    """`scaffold screen`."""

    def screen(
        self, root: Path, goldens: dict[str, Golden], words: list[str], check: bool, dry: bool
    ) -> None:
        """`screen <Noun>`: the worked face, words and road, for the verbs the wire serves."""
        golden = goldens.get(FACE)
        if golden is None:
            self.pending(next(s for s in SHAPES if s.golden == FACE), goldens)
            return
        if len(words) != 1:
            raise _refuse("screen takes <Noun> — e.g. `scaffold screen Order`.")
        noun = words[0]
        if not NOUN_WORD.match(noun) or looks_plural(snake(noun)):
            raise _refuse(
                f"{noun!r} is not a singular PascalCase noun — house rule 16: the face draws "
                "one noun, named as its model is."
            )
        verbs = adopt_verbs(root)
        served = self.served(root, noun)
        try:
            copy = face_copy(face_golden(root, golden), noun, served, verbs)
        except FenceError as error:
            raise _refuse(f"the golden could not be read: {error}") from error
        cols = self.columns(root, noun)
        self.place_columns(copy, noun, cols)
        if check:
            self.compare_face(root, golden, noun, served, copy)
            return
        pages = self.product_pages(root, noun, copy)
        taken = sorted(face_taken(root, copy))
        if taken:
            raise _refuse(
                f"{taken[0]} already exists — the scaffold writes new files and never "
                "overwrites one; a face grows a verb by hand from the worked one."
            )
        verb_list = " ".join(served) or "none — the base face"
        words = self.new_words(root, copy, [label for _, label, _ in cols])
        if dry:
            written, inserted = face_plan(root, golden, copy)
            at = (root / LEXICON).read_text(encoding="utf-8").rpartition(LEXICON_END)[0]
            row = at.count("\n") + 2
            inserted.extend((LEXICON, row + i, json.dumps(w)) for i, w in enumerate(words))
            self.plan(root, None, "", written=written, inserted=inserted, records=False)
            return
        face_write(root, copy)
        for line in copy.report():
            self.stdout.write(line)
        self.record_words(root, noun, words)
        self.stdout.write(f"verbs drawn: {verb_list}")
        self.stdout.write(
            f"Next: the walk pages are dev-only, and on the staff surface they yield to the "
            f"product's own pages {pages} — the route table prefers their rows (house rule 71); "
            "then `pnpm run typecheck` and `pnpm test`."
        )

    def new_words(self, root: Path, copy: Copy, labels: Sequence[str] = ()) -> list[str]:
        """The copy's labels the lexicon lacks: the worked noun's rows renamed, its columns'."""
        lexicon = root / LEXICON
        if not lexicon.is_file():
            return []
        rows = LEXICON_ROW.findall(lexicon.read_text(encoding="utf-8"))
        spelled = "".join(copy.files.values())
        found: list[str] = []
        for row in rows:
            word = rename(row, copy.renames, {})
            if word != row and word not in rows and word not in found and f'"{word}"' in spelled:
                found.append(word)
        found += [label for label in dict.fromkeys(labels) if label not in [*rows, *found]]
        return found

    def columns(self, root: Path, noun: str) -> list[tuple[str, str, str]]:
        """The noun's first three enums, edited dates and edited short words, in model order."""
        schemas = self.document(root).get("components", {}).get("schemas", {})
        carried = set((schemas.get(f"{noun}Out") or {}).get("properties") or {})
        edited = set((schemas.get(f"{noun}Patch") or {}).get("properties") or {})
        model = next((m for m in apps.get_models() if m.__name__ == noun), None)
        found: list[tuple[str, str, str]] = []
        for field in model._meta.concrete_fields if model is not None else ():
            if field.name == "name" or field.name not in carried:
                continue
            if isinstance(field, models.CharField) and (field.choices or field.name in edited):
                reads = "word"
            elif isinstance(field, models.DateField) and field.name in edited:
                reads = "day"
            else:
                continue
            label = str(field.verbose_name)
            found.append((field.name, label[:1].upper() + label[1:], reads))
        return found[:3]

    def place_columns(self, copy: Copy, noun: str, cols: list[tuple[str, str, str]]) -> None:
        """The copy's words and grid given the noun's own columns in place of the worked noun's."""
        word = snake(noun)
        words = f"frontend/src/copy/{word}.ts"
        sheet = f"frontend/src/screens/{word}/{word}-face.css"
        if words in copy.files:
            rows = "".join(
                f"        {field}: {{ label: {json.dumps(label)}, reads: {json.dumps(reads)} }},\n"
                for field, label, reads in cols
            )
            copy.files[words], n = COLUMNS_BLOCK.subn(rf"\g<1>{rows}\g<2>", copy.files[words])
            if n != 1:
                raise _refuse(f"{words} carries no `columns: {{ … }}` block to fill.")
        if sheet in copy.files:
            grid = re.compile(
                rf"(\.{word.replace('_', '-')}-rows \{{[^}}]*grid-template-columns: "
                r"minmax\(0, 1fr\) repeat\()\d+(, auto\);)"
            )
            copy.files[sheet], n = grid.subn(rf"\g<1>{len(cols) + 2}\g<2>", copy.files[sheet])
            if n != 1:
                raise _refuse(f"{sheet} carries no row grid to size.")

    def document(self, root: Path) -> dict[str, Any]:
        """`frontend/openapi.json`, read; empty when the tree has none."""
        path = root / "frontend/openapi.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

    def product_pages(self, root: Path, noun: str, copy: Copy) -> str:
        """The noun's list and record pages, their route rows and the client's two reads."""
        word = snake(noun)
        found: dict[str, str] = {}
        for path, item in (self.document(root).get("paths") or {}).items():
            for operation in (item or {}).values():
                if isinstance(operation, dict) and operation.get("x-url-name"):
                    found.setdefault(str(operation["x-url-name"]), path)
        listed, detail = found.get(f"{word}-list"), found.get(f"{word}-detail")
        segment = re.fullmatch(r"\{([a-z_]+)\}", (detail or "").rstrip("/").rpartition("/")[2])
        if listed is None or detail is None or segment is None:
            raise _refuse(
                f"frontend/openapi.json serves no `{word}-list` and `{word}-detail` pair — the "
                "product pages read both; mount the noun's list and detail, then regenerate."
            )
        page = listed.rstrip("/").rpartition("/")[2]
        param = segment.group(1)
        plural = f"{noun}s"
        upper = word.upper()
        fill = {
            "Noun": noun,
            "Nouns": plural,
            "noun": word,
            "nouns": f"{word.replace('_', ' ')}s",
            "noun_one": word.replace("_", " "),
            "page": page,
            "LIST": f"{upper}S",
            "ONE": upper,
            "listed": listed,
            "detail": detail,
            "param": param,
            "camel": re.sub(r"_([a-z])", lambda m: m.group(1).upper(), param),
        }
        for rel, text in (
            (f"frontend/src/app/{page}/page.tsx", LIST_PAGE),
            (f"frontend/src/app/{page}/[id]/page.tsx", RECORD_PAGE),
        ):
            copy.files[rel] = text.format(**fill)
            copy.spans[rel] = GENERATED
        copy.files[ROUTES] = copy.files.get(ROUTES, "") + PRODUCT_ROWS.format(**fill)
        copy.files[CLIENT] = CLIENT_READS.format(**fill)
        copy.spans[CLIENT] = GENERATED
        return (
            f"`/{page}` and `/{page}/[id]` (frontend/src/app/{page}/page.tsx, "
            f"frontend/src/app/{page}/[id]/page.tsx)"
        )

    def record_words(self, root: Path, noun: str, words: list[str]) -> None:
        """The copy's new words appended to the lexicon, each printed as the row it wrote."""
        if not words:
            return
        lexicon = root / LEXICON
        text = lexicon.read_text(encoding="utf-8")
        head, closing, tail = text.rpartition(LEXICON_END)
        if not closing:
            raise _refuse(f"{LEXICON} has no `LEXICON` array ending in {LEXICON_END!r}.")
        rows = "".join(f"    {json.dumps(word)},\n" for word in words)
        lexicon.write_text(f"{head}    // The {noun} face's words.\n{rows}{closing}{tail}")
        for word in words:
            self.stdout.write(f"lexicon: {LEXICON} += {json.dumps(word)}")

    def served(self, root: Path, noun: str) -> tuple[str, ...]:
        """The face verbs `frontend/openapi.json` serves for `noun`, in adoption order."""
        word = snake(noun).replace("_", "-")
        done = subprocess.run(  # noqa: S603 — argv list to this interpreter running a module constant program
            [sys.executable, "-P", "-c", DOORS_PROGRAM, str(root), word],
            cwd=root,
            env={**os.environ, "PYTHONPATH": str(root)},
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            raise _refuse(f"rule 77's wire reader did not run: {done.stderr.strip()}")
        answer = json.loads(done.stdout)
        if not answer["read"] or not answer["listed"]:
            raise _refuse(
                f"frontend/openapi.json serves no `{snake(noun)}-list` — a screen draws a noun "
                "the wire serves (house rule 77); mount the noun, then regenerate the document."
            )
        wanted = {FACE_VERBS[door] for door in answer["doors"] if door in FACE_VERBS}
        if answer["bulk"]:
            wanted.add("bulk")
        return tuple(verb for verb in adopt_verbs(root) if verb in wanted)

    def compare_face(
        self, root: Path, golden: Golden, noun: str, served: tuple[str, ...], copy: Copy
    ) -> None:
        """Exit 0 when the noun's face holds exactly the copy; the diff and 1 otherwise."""
        verbs = adopt_verbs(root)
        renames = tuple((old, new) for old, new in copy.renames)
        drift: list[str] = []
        for rel in golden.files:
            target = rename(rel, renames, {})
            path = root / target
            theirs = (
                "\n".join(face_lines(path.read_text(encoding="utf-8"), served, verbs, target))
                + "\n"
                if path.is_file()
                else ""
            )
            mine = copy.files.get(target, "")
            if theirs.strip() or mine:
                drift.extend(
                    difflib.unified_diff(
                        theirs.splitlines(keepends=True),
                        mine.splitlines(keepends=True),
                        f"{target} (fenced)",
                        f"{golden.path(rel)} (generated)",
                    )
                )
        if drift:
            self.stdout.write("".join(drift))
            raise CommandError(f"the {noun} face differs from its golden", returncode=1)
        self.stdout.write(f"the {noun} face: `{golden.key}` regenerates byte-for-byte.")
