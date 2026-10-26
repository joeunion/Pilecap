"""`scaffold screen <Noun>` ends at a product page: the page pair, its rows, the client's reads."""

# does-not-cover: the RENDERED product page — the browser drive; here only its types and the suite.
# does-not-cover: a live socket — the board's dial is the hook's tests' (fake timers, no proxy).

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command

from apps.core.management.commands.scaffold import Command
from apps.core.scaffold.arms.screen import LEXICON, ScreenArm
from apps.core.tests.tree_census import source_text
from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.scratch import require_scratch

ROOT = Path(__file__).resolve().parents[3]
FE = ROOT / "frontend"
#: What the copy world carries: everything the face's suite reads, as tracked.
TRACKED = "frontend quality apps config docs/product/design scripts pyproject.toml"


def renamed(text: str, noun: str) -> str:
    """The worked noun's three spellings as `noun`'s."""
    word = noun.lower()
    return text.replace("Widget", noun).replace("widget", word).replace("WIDGET", word.upper())


def planted(document: dict[str, Any], noun: str) -> dict[str, Any]:
    """`document` with the worked wire planted as `noun`'s; merge left off (`verb-focus`)."""
    schemas, paths = document["components"]["schemas"], document["paths"]
    for name in [n for n in schemas if "Widget" in n]:
        schemas[renamed(name, noun)] = json.loads(renamed(json.dumps(schemas[name]), noun))
    for path in [p for p in paths if p.startswith("/api/v1/widgets/") and "/merge/" not in p]:
        paths[renamed(path, noun)] = json.loads(renamed(json.dumps(paths[path]), noun))
    return document


def _scaffold(*argv: str) -> list[str]:
    out = io.StringIO()
    call_command("scaffold", *argv, stdout=out)
    return out.getvalue().splitlines()


def test_the_product_page_and_client_calls_are_written(monkeypatch: pytest.MonkeyPatch) -> None:
    document = planted(json.loads((FE / "openapi.json").read_text()), "Gizmo")
    monkeypatch.setattr(Command, "served", lambda self, root, noun: ())
    monkeypatch.setattr(Command, "document", lambda self, root: document)
    lexicon = (ROOT / LEXICON).read_text()
    planned = _scaffold("screen", "Gizmo", "--dry-run")
    written = [
        line.split()[2].partition(":")[0] for line in planned if line.startswith("would write")
    ]
    inserted = [
        line.split()[2].partition(":")[0] for line in planned if line.startswith("would insert")
    ]
    assert "frontend/src/app/gizmos/page.tsx" in written, planned
    assert "frontend/src/app/gizmos/[id]/page.tsx" in written, planned
    assert "frontend/src/app/example/gizmos/page.tsx" in written, planned
    assert {"frontend/src/api/client.ts", "frontend/src/kit/routes.ts"} <= set(inserted), planned
    assert not (ROOT / "frontend/src/app/gizmos").exists()
    assert (ROOT / LEXICON).read_text() == lexicon


def test_the_columns_are_the_nouns_own_fields_read_off_the_model_and_the_wire() -> None:
    arm = Command()
    assert arm.columns(ROOT, "Widget") == [
        ("due_at", "Due at", "day"),
        ("status", "Status", "word"),
    ]
    assert arm.columns(ROOT, "NoSuchNoun") == []


def test_the_next_line_names_the_tests_and_the_rows_the_walks_yield_to() -> None:
    source = (ROOT / "apps/core/scaffold/arms/screen.py").read_text()
    said = source.partition('f"Next: ')[2].partition("\n        )")[0]
    assert "`pnpm test`" in said and "`pnpm run typecheck`" in said, said
    assert "yield to" in said and "prefers their rows" in said, said


def test_the_product_pages_are_named_by_the_files_written() -> None:
    """The `Next:` line names the product pages' files under the product's route."""
    source = (ROOT / "apps/core/scaffold/arms/screen.py").read_text()
    said = source.partition("def product_pages")[2].partition("def record_words")[0]
    assert '(frontend/src/app/{page}/page.tsx, "' in said, said
    assert 'f"frontend/src/app/{page}/[id]/page.tsx)"' in said, said


# --- the copy, written into a world of its own, typechecks and passes the face's suite ----------


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """A copy of the tracked tree with the worked noun's wire planted again as `Gadget`."""
    bins = FE / "node_modules/.bin"
    if not all(os.access(bins / t, os.X_OK) for t in ("tsc", "vitest", "openapi-typescript")):
        raise CouldNotLook("frontend/node_modules has no tsc, vitest or openapi-typescript")
    root = require_scratch(tmp_path_factory.mktemp("screen-copy"), ROOT) / "world"
    root.mkdir()
    copied = subprocess.run(  # noqa: S603 — `bash -c` over a pipeline this test writes; no caller input
        [  # noqa: S607 — `bash` from PATH, as the gate runs it
            "bash",
            "-c",
            f"git ls-files -z -- {TRACKED} | tar --null -T - -cf - | tar -xf - -C {str(root)!r}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if copied.returncode != 0:
        raise CouldNotLook(f"the world could not be copied: {copied.stderr}")
    modules = root / "frontend/node_modules"
    modules.mkdir()
    for entry in (FE / "node_modules").iterdir():
        (modules / entry.name).symlink_to(entry)
    document = planted(json.loads((FE / "openapi.json").read_text()), "Gadget")
    (root / "frontend/openapi.json").write_text(json.dumps(document, indent=2) + "\n")
    generated = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; no shell
        [
            str(bins / "openapi-typescript"),
            "openapi.json",
            "--output",
            "src/api/generated/schema.d.ts",
        ],
        cwd=root / "frontend",
        capture_output=True,
        text=True,
    )
    if generated.returncode != 0:
        raise CouldNotLook(f"openapi-typescript could not generate the client: {generated.stderr}")
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_the_copy_typechecks_and_passes_the_suite(
    world: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.BASE_DIR = world
    widget = ScreenArm.columns
    monkeypatch.setattr(Command, "columns", lambda self, root, noun: widget(self, root, "Widget"))
    said = _scaffold("screen", "Gadget")
    assert any(
        line.startswith("Next: ") and "`/gadgets` and `/gadgets/[id]`" in line for line in said
    ), said
    page = source_text(world / "frontend/src/app/gadgets/page.tsx")
    assert 'useEvents(null, ["gadget"])' in page and "listGadgets(null)" in page
    client = source_text(world / "frontend/src/api/client.ts")
    assert (
        "export async function listGadgets(" in client
        and "export async function getGadget(" in client
    )
    words = source_text(world / "frontend/src/copy/gadget.ts")
    assert 'due_at: { label: "Due at", reads: "day" }' in words, words
    for runner in sorted((world / "quality/runners").glob("js_*.py")):
        done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, str(runner), "frontend"], cwd=world, capture_output=True, text=True
        )
        assert done.returncode == 0, f"{runner.name} did not run: {done.stderr}"
        assert json.loads(done.stdout)["findings"] == [], (runner.name, done.stdout[:4000])
    lint = ["eslint", "src/app", "src/api", "src/screens/gadget", "--max-warnings=0"]
    for argv in (["tsc", "--noEmit"], lint, ["vitest", "run"]):
        done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; no shell
            [str(world / "frontend/node_modules/.bin" / argv[0]), *argv[1:]],
            cwd=world / "frontend",
            capture_output=True,
            text=True,
        )
        output = done.stdout + done.stderr
        failed = [line for line in output.splitlines() if " FAIL " in line or " × " in line]
        assert done.returncode == 0, f"{' '.join(argv)} on the copy:\n" + "\n".join(
            failed or output.splitlines()[-80:]
        )
