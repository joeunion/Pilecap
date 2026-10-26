"""Each verb of the worked face, copied from its extract, holds rules 77-80, tsc and the census."""

# does-not-cover: whether the worked face is GOOD — only that its fenced text meets its wire.
# does-not-cover: the RENDERED face — the browser drive and the mirror pass.
# does-not-cover: the routes a product adds; the worked face's walk pages are not copied.
# does-not-cover: the owners' doors attach and import ride — rule 77 judges neither verb.
# does-not-cover: the whole fe suite — only the rules' runners, the type-check and the census.
# does-not-cover: the real face's own findings — seen, never judged here; they are the gate's.

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from apps.core.scaffold import copier
from apps.core.scaffold.shapes import ADOPT, adopt_verbs
from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.scratch import require_scratch

pytestmark = pytest.mark.drives(
    "frontend/",
    "frontend/openapi.json",
    "frontend/src/api/generated/schema.d.ts",
    "docs/product/design/",
    "scripts/archaeology_lib.sh",
    "scripts/gate_refuse.sh",
)

ROOT = Path(__file__).resolve().parents[2]
PY = ROOT / ".venv/bin/python"
FE = ROOT / "frontend"
SOURCES = copier.face_sources()
COPIES = (
    "frontend/src/screens/gadget",
    "frontend/src/copy/gadget.ts",
    "frontend/src/app/example/gadgets",
)
VERBS = adopt_verbs(ROOT)
#: The worked noun's doors each verb adopts, as (method, path suffix) under the collection.
DOORS: dict[str, list[tuple[str, str]]] = {
    "archive": [("post", "/{widget_id}/archive/"), ("post", "/{widget_id}/restore/")],
    "version": [("patch", "/{widget_id}/")],
    "move": [("post", "/{widget_id}/move/")],
    "bulk": [("post", "/bulk/")],
    "history": [("get", "/{widget_id}/history/")],
    "duplicate": [("post", "/{widget_id}/duplicate/")],
    "merge": [("post", "/{widget_id}/merge/"), ("get", "/{widget_id}/merge/")],
    # Attach and import ride their owners' doors, which the world's document already carries.
    "attach": [],
    "import": [],
}
COLLECTION = "/api/v1/widgets"
READS = [("get", "/"), ("get", "/{widget_id}/")]
TSC_ERROR = re.compile(r"^(\S[^(]*)\(\d+,\d+\): error TS\d+:")


def rename(text: str) -> str:
    """The one rename: `Widget`→`Gadget`, `widget`→`gadget`, `WIDGET`→`GADGET`."""
    return text.replace("Widget", "Gadget").replace("widget", "gadget").replace("WIDGET", "GADGET")


def _texts(root: Path) -> dict[str, str]:
    """`{source path: fenced text}`: the template's extract, or a fixture face's own files."""
    golden = copier.index(root).get(copier.FACE)
    if golden is not None:
        return copier.face_golden(root, golden)
    return {rel: (root / rel).read_text(encoding="utf-8") for rel in copier.face_files(root)}


def extract(root: Path, world: Path, verb: str) -> list[str]:
    """The base and `verb`'s lines (every verb's for `all`, none for `base`), into `world`."""
    wanted = set(DOORS) if verb == "all" else set() if verb == "base" else {verb}
    copy = copier.face_copy(_texts(root), "Gadget", wanted, VERBS)
    copier.face_write(world, copy)
    return [f"copied {rel} from {span}" for rel, span in copy.spans.items()]


def verb_blocks(root: Path, verb: str) -> int:
    """How many fences open for `verb` in the worked face."""
    opened = [
        fence
        for text in _texts(root).values()
        for line in text.splitlines()
        if (fence := copier.parse_fence(line, VERBS)) is not None and fence.edge == "begin"
    ]
    return sum(1 for fence in opened if f"{ADOPT}.{verb}" in fence.keys)


def wire(root: Path, world: Path, verb: str) -> list[str]:
    """The worked noun's schemas and this verb's doors, renamed, planted in the world's document."""
    document = json.loads((root / "frontend/openapi.json").read_text(encoding="utf-8"))
    paths, schemas = document["paths"], document["components"]["schemas"]
    for name in [n for n in schemas if "Widget" in n]:
        schemas[rename(name)] = json.loads(rename(json.dumps(schemas[name])))
    wanted = list(READS)
    for case in DOORS if verb == "all" else () if verb == "base" else (verb,):
        wanted.extend(DOORS[case])
    detail = schemas.get(rename("WidgetDetailOut")) or {}
    if verb not in ("attach", "all"):
        (detail.get("properties") or {}).pop("tags", None)
    if verb in ("import", "all"):
        kind = ((schemas.get("DjbImportIn") or {}).get("properties") or {}).get("kind") or {}
        if "enum" in kind and rename("widget") not in kind["enum"]:
            kind["enum"] = [*kind["enum"], rename("widget")]
    for method, suffix in wanted:
        operation = (paths.get(COLLECTION + suffix) or {}).get(method)
        if operation is None:
            raise CouldNotLook(f"the worked noun's wire has no `{method.upper()} {suffix}`")
        paths.setdefault(rename(COLLECTION + suffix), {})[method] = json.loads(
            rename(json.dumps(operation))
        )
    out = world / "frontend/openapi.json"
    out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return [f"{m.upper()} {rename(COLLECTION + s)}" for m, s in wanted]


def on_the_real_face(path: str | None) -> bool:
    """Whether `path` lies in the worked face the copy was taken FROM — the gate's to judge."""
    text = str(path or "")
    return any(text == s or text.startswith(s + "/") for s in SOURCES if s not in copier.SHARED)


def judged_findings(reply: str) -> tuple[list[str], list[str]]:
    """A runner's findings split into the judged and the real face's (seen, not judged)."""
    judged: list[str] = []
    seen: list[str] = []
    for finding in json.loads(reply).get("findings", []):
        text = (
            f"{finding.get('path')}:{finding.get('line')}: [{finding.get('klass')}] "
            f"{finding.get('msg')}"
        )
        (seen if on_the_real_face(finding.get("path")) else judged).append(text)
    return judged, seen


def tsc_errors(log: str) -> tuple[list[str], list[str]]:
    """`tsc --noEmit`'s report split per error by path; an error with no path is judged."""
    blocks: list[tuple[str | None, list[str]]] = []
    for line in log.splitlines():
        match = TSC_ERROR.match(line)
        if match or not blocks or not line[:1].isspace():
            blocks.append((match.group(1) if match else None, [line]))
        else:
            blocks[-1][1].append(line)
    judged: list[str] = []
    seen: list[str] = []
    for where, lines in blocks:
        if any(part.strip() for part in lines):
            real = where is not None and on_the_real_face("frontend/" + where)
            (seen if real else judged).append("\n".join(lines))
    return judged, seen


def add_merge(world: Path) -> None:
    """The negative's edit: `merge` added to the copied road."""
    road = world / "frontend/src/screens/gadget/road.ts"
    grown, n = re.subn(r"(verbs:\s*\[)", r'\1\n        "merge",', road.read_text(), count=1)
    if n != 1:
        raise CouldNotLook("the copied road has no `verbs: [` to grow")
    road.write_text(grown)


@dataclass(frozen=True)
class Face:
    """The one world every copy case is built in: tracked frontend, quality and the pattern book."""

    root: Path

    def run(self, argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(argv, cwd=cwd, capture_output=True, text=True)


@pytest.fixture(scope="module")
def face(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Face]:
    """The world, made once per module: tracked files copied, node_modules linked, client built."""
    if not os.access(PY, os.X_OK):
        raise CouldNotLook("no virtualenv at .venv — the runners run with this checkout's python")
    bins = FE / "node_modules/.bin"
    if not all(os.access(bins / t, os.X_OK) for t in ("tsc", "vitest", "openapi-typescript")):
        raise CouldNotLook("frontend/node_modules has no tsc, vitest or openapi-typescript")
    root = require_scratch(tmp_path_factory.mktemp("golden-face"), ROOT) / "world"
    root.mkdir()
    tracked = (
        "frontend quality docs/product/design scripts/archaeology_lib.sh scripts/gate_refuse.sh"
    )
    copied = subprocess.run(
        [
            "bash",
            "-c",
            f"git ls-files -z -- {tracked} | tar --null -T - -cf - | tar -xf - -C {str(root)!r}",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if copied.returncode != 0:
        raise CouldNotLook(f"the world could not be copied: {copied.stderr}")
    modules = root / "frontend/node_modules"
    modules.mkdir()
    for entry in [*(FE / "node_modules").iterdir()]:
        (modules / entry.name).symlink_to(entry)
    wire(ROOT, root, "all")
    generated = subprocess.run(
        [
            "node_modules/.bin/openapi-typescript",
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
    if not (root / "frontend/src/screens/verb-face-census.test.tsx").is_file():
        raise CouldNotLook("the verb face census is not in this tree")
    yield Face(root)
    shutil.rmtree(root, ignore_errors=True)


def _fresh(face: Face) -> None:
    shutil.rmtree(face.root / COPIES[0], ignore_errors=True)
    (face.root / COPIES[1]).unlink(missing_ok=True)
    shutil.rmtree(face.root / COPIES[2], ignore_errors=True)
    for table in copier.SHARED:
        (face.root / table).write_text((ROOT / table).read_text(encoding="utf-8"))


def _archaeology(face: Face) -> tuple[int, str]:
    script = (
        ". scripts/archaeology_lib.sh || exit 2\n"
        f"cd {str(face.root)!r} || exit 2\n"
        f"archaeology_scan_files $(find {' '.join(COPIES)} -type f)\n"
    )
    done = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def _runner(face: Face, rule: str) -> str:
    done = face.run([str(PY), f"quality/runners/js_verb_{rule}.py", "frontend"], face.root)
    if done.returncode != 0:
        raise CouldNotLook(f"quality/runners/js_verb_{rule}.py did not run: {done.stderr}")
    return done.stdout


def golden_case(face: Face, verb: str) -> None:
    """Copy, wire, copyable, rules 77-80, `tsc` and the verb face census, for one verb."""
    if verb not in ("all", "base") and verb_blocks(ROOT, verb) == 0:
        raise CouldNotLook(f"the worked face fences no '{verb}' block — nothing to copy")
    _fresh(face)
    if not extract(ROOT, face.root, verb):
        raise CouldNotLook(f"the '{verb}' copy wrote no file")
    wire(ROOT, face.root, verb)
    rc, out = _archaeology(face)
    assert rc == 0 and "archaeology-census:" not in out, out
    for rule in ("road", "acts", "words", "table"):
        judged, _ = judged_findings(_runner(face, rule))
        assert judged == [], (rule, judged)
    tsc = face.run(["node_modules/.bin/tsc", "--noEmit", "-p", "."], face.root / "frontend")
    if tsc.returncode != 0:
        judged, seen = tsc_errors(tsc.stdout + tsc.stderr)
        assert judged == [] and seen, f"the copy does not compile on its own: {judged[:20]}"
    census = face.run(
        [
            "node_modules/.bin/vitest",
            "run",
            "--reporter=verbose",
            "src/screens/verb-face-census.test.tsx",
        ],
        face.root / "frontend",
    )
    out = census.stdout + census.stderr
    assert census.returncode == 0, out[-4000:]
    assert "the 'gadget' face's road" in out, "the census never named the gadget face"


# --- the fence grammar, over a fixture face of its own --------------------------------------------


def _fixture(scratch: Path, text: str) -> tuple[Path, Path]:
    source, out = scratch / "fence-fixture", scratch / "fence-world"
    (source / "frontend/src/screens/widget").mkdir(parents=True, exist_ok=True)
    out.mkdir(exist_ok=True)
    (source / "frontend/src/screens/widget/fence.ts").write_text(text)
    return source, out


def test_the_joint_fence_copies_only_with_every_verb(scratch: Path) -> None:
    source, out = _fixture(
        scratch,
        "// golden: face begin\nexport const base = 1;\n// golden: face end\n"
        "// golden: bulk begin\nexport const bulkOnly = 2;\n"
        "// golden: bulk+merge begin\nexport const bothBulkAndMerge = 3;\n"
        "// golden: bulk+merge end\n// golden: bulk end\n",
    )
    extract(source, out, "bulk")
    copy = (out / "frontend/src/screens/gadget/fence.ts").read_text()
    assert "bulkOnly" in copy and "bothBulkAndMerge" not in copy
    shutil.rmtree(out)
    out.mkdir()
    extract(source, out, "all")
    assert "bothBulkAndMerge" in (out / "frontend/src/screens/gadget/fence.ts").read_text()


@pytest.mark.parametrize("malformed", ["bulk+", "bulk+nothing", "merge+merge"])
def test_a_malformed_joint_fence_is_exit_2(scratch: Path, malformed: str) -> None:
    source, out = _fixture(
        scratch,
        f"// golden: {malformed} begin\nexport const x = 1;\n// golden: {malformed} end\n",
    )
    with pytest.raises(copier.FenceError, match="no verb this grammar knows"):
        extract(source, out, "bulk")


def test_the_face_extract_is_what_the_face_fences_say() -> None:
    assert copier.drift(ROOT) == [], "run `./scripts/pm_fold.sh --only goldens`"


def test_the_screen_regenerates_the_worked_face_byte_for_byte() -> None:
    done = subprocess.run(
        [str(PY), "manage.py", "scaffold", "screen", "Widget", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "`face` regenerates byte-for-byte" in done.stdout


# --- the copy cases, one per verb and one for every verb at once ----------------------------------


def test_the_archive_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "archive")


def test_the_version_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "version")


def test_the_move_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "move")


def test_the_bulk_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "bulk")


def test_the_history_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "history")


def test_the_duplicate_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "duplicate")


def test_the_merge_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "merge")


def test_the_attach_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "attach")


def test_the_import_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "import")


def test_the_all_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "all")


def test_the_base_copy_holds_the_rules_the_types_and_the_census(face: Face) -> None:
    golden_case(face, "base")


def test_every_door_verb_has_its_copy_case() -> None:
    names = set(globals())
    missing = [
        v
        for v in DOORS
        if f"test_the_{v}_copy_holds_the_rules_the_types_and_the_census" not in names
    ]
    assert missing == []


def test_the_copy_road_naming_merge_against_a_wire_without_it_reds_rule_77(face: Face) -> None:
    _fresh(face)
    extract(ROOT, face.root, "archive")
    wire(ROOT, face.root, "archive")
    add_merge(face.root)
    judged, _ = judged_findings(_runner(face, "road"))
    assert len(judged) == 1, judged
    assert (
        "declares `merge` and `frontend/openapi.json` serves no `merge` door for `gadget`"
        in judged[0]
    )


def test_the_cleanup_census_leaves_nothing() -> None:
    for path in COPIES:
        assert not (ROOT / path).exists(), f"the checkout carries {path}"
