"""The fence grammar and the copier: `golden:` fences read, extracted, and copied renamed."""

# does-not-cover: a `golden:` fence spelled inside a string — only comment lines are fences.
# does-not-cover: a face fence outside the worked noun's screen folder and copy module.

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import textwrap
import tokenize
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from apps.core.scaffold import anchors
from apps.core.scaffold.shapes import ADOPT, FENCE_SHAPES, SHAPES, adopt_verbs

#: Where the template-owned extracts live, relative to a checkout's root.
GOLDENS = "apps/core/scaffold/goldens"
INDEX = "index.json"
SUFFIX = "-tpl"
#: A comment line `golden: … begin|end` (`#`, `//`, `/* */`, `{/* */}`) — every one is a fence.
FENCE_LINE = re.compile(
    r"^\s*(?:#|//|\{?/\*)\s*golden:(?P<body>.*?\s(?:begin|end))\s*(?:\*/\}?)?\s*$"
)
FENCE_BODY = re.compile(r"^\s*(?P<words>\S.*?)\s+(?P<edge>begin|end)$")
NAME = re.compile(r"^[a-z_][a-z0-9_-]*$")
#: Two blank lines between blocks: the formatter's own spacing at module level.
JOIN = "\n\n\n"
#: The source tree's noun, as the worked example spells it.
SOURCE_NOUN = "Widget"
SKIP_PARTS = frozenset({"__pycache__", "node_modules"})


class FenceError(ValueError):
    """A fence the grammar cannot read: an unknown word, a nest, an unmatched edge."""


class NoFormatter(RuntimeError):
    """No `ruff` beside this interpreter or on PATH: an extract cannot be made or read back."""


@dataclass(frozen=True)
class Fence:
    """One fence line: its edge and the extract keys it opens or closes."""

    edge: str
    keys: tuple[str, ...]


def parse_fence(line: str, verbs: Sequence[str], where: str = "") -> Fence | None:
    """The fence a line is, None when it is no `golden:` comment; a misspelt one is `FenceError`."""
    matched = FENCE_LINE.match(line)
    if matched is None:
        return None
    body = matched.group("body").strip()
    shaped = FENCE_BODY.match(body)
    if shaped is None:
        raise FenceError(f"{where}`golden: {body}` names no shape before its edge")
    words, edge = shaped.group("words").split(), shaped.group("edge")
    if all(_verbs_of(word, verbs) for word in words):
        return Fence(edge, tuple(f"{ADOPT}.{word}" for word in words))
    head, rest = words[0], words[1:]
    if head in FENCE_SHAPES and len(rest) <= 1 and all(NAME.match(word) for word in rest):
        return Fence(edge, (".".join(words),))
    unknown = [w for w in words if not _verbs_of(w, verbs) and w not in FENCE_SHAPES]
    raise FenceError(
        f"{where}`golden: {body}` names {', '.join(unknown) or ' '.join(words)}, which is no "
        f"verb this grammar knows ({' '.join(verbs)}) and no `<shape>[ <name>]` over the "
        f"registered shapes ({' '.join(sorted(FENCE_SHAPES))}) with a name matching "
        f"{NAME.pattern}"
    )


def _verbs_of(word: str, verbs: Sequence[str]) -> bool:
    """A verb, or a face's joint `a+b` of two or more distinct verbs."""
    parts = word.split("+")
    return all(p in verbs for p in parts) and len(set(parts)) == len(parts)


@dataclass
class Block:
    """One fenced block: its begin and end lines in the source, and the lines between."""

    begin: int
    end: int
    lines: list[str] = field(default_factory=list)


def blocks_of(text: str, key: str, verbs: Sequence[str], where: str = "") -> list[Block]:
    """Every block of `text` fenced for `key`; a nest or an unmatched edge is `FenceError`."""
    blocks: list[Block] = []
    inside: Block | None = None
    for number, line in enumerate(text.splitlines(), 1):
        fence = parse_fence(line, verbs, f"{where}:{number}: ")
        if fence is not None and key in fence.keys:
            if fence.edge == "begin":
                if inside is not None:
                    raise FenceError(f"{where}:{number}: a `{key}` begin inside another")
                inside = Block(number, 0)
            else:
                if inside is None:
                    raise FenceError(f"{where}:{number}: a `{key}` end with no begin")
                inside.end = number
                blocks.append(inside)
                inside = None
        elif inside is not None:
            inside.lines.append(line)
    if inside is not None:
        raise FenceError(f"{where}:{inside.begin}: a `{key}` begin that never ends")
    return blocks


def keys_of(text: str, verbs: Sequence[str], where: str = "") -> set[str]:
    """Every extract key a text's fences name."""
    found: set[str] = set()
    for number, line in enumerate(text.splitlines(), 1):
        fence = parse_fence(line, verbs, f"{where}:{number}: ")
        if fence is not None:
            found.update(fence.keys)
    return found


def sources(app_dir: Path) -> list[Path]:
    """The Python modules under an app directory, in a stable order."""
    return [p for p in sorted(app_dir.rglob("*.py")) if not SKIP_PARTS & set(p.parts)]


def assemble(blocks: Sequence[Block]) -> str:
    """The copy's text: the blocks joined at module spacing."""
    return JOIN.join("\n".join(block.lines) for block in blocks) + "\n"


def collect(app_dir: Path, key: str, verbs: Sequence[str]) -> dict[str, list[Block]]:
    """`{relative path: blocks}` for every module under `app_dir` that fences `key`."""
    found: dict[str, list[Block]] = {}
    for path in sources(app_dir):
        rel = path.relative_to(app_dir).as_posix()
        if blocks := blocks_of(path.read_text(), key, verbs, rel):
            found[rel] = blocks
    return found


def snake(noun: str) -> str:
    """`WorkOrder` → `work_order`."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", noun).lower()


def relocations(
    source: str, target: str, noun: str, prefix: Iterable[tuple[str, str]] = ()
) -> tuple[tuple[str, str], ...]:
    """The renames a copy takes, in order: the app's paths, then each plural before its noun."""
    return (
        *prefix,
        (f"apps.{source}", f"apps.{target}"),
        (f"apps/{source}/", f"apps/{target}/"),
        (f"`apps/{source}`", f"`apps/{target}`"),
        (f'"{source}.', f'"{target}.'),
        (plurals(SOURCE_NOUN), plurals(noun)),
        (SOURCE_NOUN, noun),
        (plural_of(snake(SOURCE_NOUN)), plural_of(snake(noun))),
        (snake(SOURCE_NOUN), snake(noun)),
        (plural_of(snake(SOURCE_NOUN)).upper(), plural_of(snake(noun)).upper()),
        (snake(SOURCE_NOUN).upper(), snake(noun).upper()),
    )


def plural_of(word: str) -> str:
    """`word`'s plural as rule 17's tool names say it (`apps.core.verbs.plural`'s own body)."""
    from apps.core.lexicon import inflected

    return inflected(word)


def plurals(noun: str) -> str:
    """`Company` → `Companies`: the plural of a capitalised noun, its tail inflected."""
    said, many = snake(noun), plural_of(snake(noun))
    kept = len(said) - next(
        (i for i, (a, b) in enumerate(zip(said, many, strict=False)) if a != b),
        min(len(said), len(many)),
    )
    return noun[: len(noun) - kept] + many[len(said) - kept :]


def names_in(text: str) -> list[tokenize.TokenInfo]:
    """`text`'s identifier tokens, as far as a golden fragment tokenizes; prose is never one."""
    found: list[tokenize.TokenInfo] = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NAME:
                found.append(token)
    except (tokenize.TokenError, SyntaxError):
        pass
    return found


def rename(text: str, renames: Sequence[tuple[str, str]], moved: dict[str, int]) -> str:
    """`text` with each rename applied in order, counting each one's hits into `moved`."""
    for old, new in renames:
        moved[old] = moved.get(old, 0) + text.count(old)
        text = text.replace(old, new)
    return text


@dataclass
class Copy:
    """A rendered copy: `{relative path: text}`, each file's spans, and the renames' counts."""

    files: dict[str, str] = field(default_factory=dict)
    spans: dict[str, str] = field(default_factory=dict)
    moved: dict[str, int] = field(default_factory=dict)
    renames: tuple[tuple[str, str], ...] = ()

    def report(self) -> list[str]:
        """The `relocated:` line and one `copied` line per file, as the drive reads them."""
        head = " · ".join(f"{o} → {n} ×{self.moved.get(o, 0)}" for o, n in self.renames)
        lines = [f"relocated: {head}"]
        for rel, text in self.files.items():
            lines.append(f"copied {rel} ({text.count(chr(10))} lines) from {self.spans[rel]}")
        return lines


def render(
    found: dict[str, list[Block]], renames: Sequence[tuple[str, str]], label: str = ""
) -> Copy:
    """The copy of `found`'s blocks under `renames`; spans read `<label><rel>:<begin>-<end>`."""
    copy = Copy(renames=tuple(renames))
    for rel, blocks in found.items():
        copy.files[rel] = rename(assemble(blocks), renames, copy.moved)
        copy.spans[rel] = ", ".join(f"{label}{rel}:{b.begin}-{b.end}" for b in blocks)
    return copy


def app_config(label: str) -> str:
    """The `apps.py` a copied app is born with when its directory is new."""
    config = "".join(part.title() for part in label.split("_"))
    return (
        "from django.apps import AppConfig\n\n\n"
        f"class {config}Config(AppConfig):\n"
        f'    name = "apps.{label}"\n'
        '    depends_on: tuple[str, ...] = ("core", "accounts", "events")\n'
    )


def write_app(destination: Path, label: str, copy: Copy) -> None:
    """The copy written under `destination`, the package born first when it is new."""
    if not destination.exists():
        (destination / "migrations").mkdir(parents=True)
        (destination / "__init__.py").write_text("")
        (destination / "migrations/__init__.py").write_text("")
        (destination / "apps.py").write_text(app_config(label))
    for rel, text in copy.files.items():
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.parent / "__init__.py").exists():
            (target.parent / "__init__.py").write_text("")
        target.write_text(text)


# --- the extracts: the template's fences, formatted, where a product without them reads them --


def ruff() -> str:
    """The `ruff` this checkout formats with: beside the interpreter, else on PATH."""
    beside = Path(sys.executable).parent / "ruff"
    found = str(beside) if beside.is_file() else shutil.which("ruff")
    if not found:
        raise NoFormatter("no `ruff` beside this interpreter or on PATH — nothing can be formatted")
    return found


def formatted(text: str, root: Path, rel: str = "golden.py") -> str:
    """`text` as `ruff format` writes it under `root`'s own configuration."""
    done = subprocess.run(  # noqa: S603 — argv list to the venv's ruff, the text on stdin; no shell
        [ruff(), "format", "--stdin-filename", str(root / GOLDENS / rel), "-"],
        cwd=root,
        input=text,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise FenceError(f"{rel}: the assembled copy does not format: {done.stderr.strip()}")
    return done.stdout


def fenced_apps(root: Path, verbs: Sequence[str]) -> dict[str, dict[str, set[str]]]:
    """`{app: {key: {relative paths}}}` for every app under `root/apps` that carries a fence."""
    found: dict[str, dict[str, set[str]]] = {}
    base = root / "apps"
    for app_dir in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        for path in sources(app_dir):
            rel = path.relative_to(app_dir).as_posix()
            for key in keys_of(path.read_text(), verbs, f"apps/{app_dir.name}/{rel}"):
                found.setdefault(app_dir.name, {}).setdefault(key, set()).add(rel)
    return found


def extracts(root: Path) -> dict[str, str]:
    """`{path under GOLDENS: text}` — every fence of the tree, formatted, and the index."""
    verbs = adopt_verbs(root)
    homes: dict[str, str] = {}
    for app, keys in fenced_apps(root, verbs).items():
        for key in keys:
            if key in homes:
                raise FenceError(f"`{key}` is fenced in apps/{homes[key]} and apps/{app}")
            homes[key] = app
    written: dict[str, str] = {}
    table: dict[str, dict[str, object]] = {}
    for key in sorted(homes):
        found = collect(root / "apps" / homes[key], key, verbs)
        table[key] = {"app": homes[key], "files": sorted(found)}
        for rel, blocks in found.items():
            if anchors.additive(key) and rel == anchors.APP_CONFIG:
                text = textwrap.dedent(assemble(blocks))
                written[f"{key}/{rel}{SUFFIX}"] = formatted(text, root, f"{key}/{rel}")
                continue
            if anchors.additive(key):
                source = (root / "apps" / homes[key] / rel).read_text()
                where = f"apps/{homes[key]}/{rel}"
                written[f"{key}/{rel}{SUFFIX}"] = anchors.serialize(
                    anchors.pieces(source, key, verbs, where)
                )
                continue
            written[f"{key}/{rel}{SUFFIX}"] = formatted(assemble(blocks), root, f"{key}/{rel}")
    if written:
        written[INDEX] = json.dumps(table, indent=2, sort_keys=True) + "\n"
    return written


def drift(root: Path, *, face: bool = True) -> list[str]:
    """Every extract path under `root` that differs from its fences, or is stale; `face` or not."""
    goldens = root / GOLDENS
    wanted = {**extracts(root), **(face_extracts(root) if face else {})}
    present = (
        {p.relative_to(goldens).as_posix() for p in goldens.rglob("*") if p.is_file()}
        if goldens.is_dir()
        else set()
    )
    if not face:
        present = {rel for rel in present if not rel.startswith(f"{FACE}/")}
    moved = [
        rel
        for rel, text in wanted.items()
        if rel not in present or (goldens / rel).read_text() != text
    ]
    return sorted({*moved, *(present - set(wanted))})


def regenerate(root: Path) -> list[str]:
    """The extracts rewritten under `root`; the paths that changed, stale ones deleted."""
    goldens = root / GOLDENS
    wanted = {**extracts(root), **face_extracts(root)}
    changed: list[str] = []
    present = (
        {p.relative_to(goldens).as_posix() for p in goldens.rglob("*") if p.is_file()}
        if goldens.is_dir()
        else set()
    )
    for rel in sorted(present - set(wanted)):
        (goldens / rel).unlink()
        changed.append(f"{GOLDENS}/{rel}")
    for rel, text in wanted.items():
        target = goldens / rel
        if not target.is_file() or target.read_text() != text:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            changed.append(f"{GOLDENS}/{rel}")
    if goldens.is_dir():
        for directory in sorted(goldens.rglob("*"), reverse=True):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
    return changed


@dataclass(frozen=True)
class Golden:
    """One extract read back: its key, the app its fences live in, and its files."""

    key: str
    app: str
    files: tuple[str, ...]

    def path(self, rel: str) -> str:
        """The extract file holding `rel`'s blocks, relative to the checkout."""
        return f"{GOLDENS}/{self.key}/{rel}{SUFFIX}"


def index(root: Path) -> dict[str, Golden]:
    """The extracts' index under `root`, the face's beside it; empty when it carries none."""
    found: dict[str, Golden] = {}
    for path in (root / GOLDENS / INDEX, root / GOLDENS / FACE / INDEX):
        if path.is_file():
            for key, entry in json.loads(path.read_text()).items():
                found[key] = Golden(key, str(entry["app"]), tuple(str(f) for f in entry["files"]))
    return found


#: The sorter reads a package it cannot find on disk as third-party; a copy's app is not there yet.
FIRST_PARTY = 'lint.isort.known-first-party = ["apps", "pilecap"]'


def tidied(text: str, root: Path, rel: str, app: str) -> str:
    """`text` with unused imports dropped and the rest sorted as `apps/<app>/<rel>`, formatted."""
    done = subprocess.run(  # noqa: S603 — argv list to the venv's ruff, the text on stdin; no shell
        [ruff(), "check", "--fix", "--exit-zero", "--quiet", "--select", "F401,I"]
        + ["--config", FIRST_PARTY, "--stdin-filename", str(root / "apps" / app / rel), "-"],
        cwd=root,
        input=text,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise FenceError(f"{rel}: the copy's imports could not be tidied: {done.stderr.strip()}")
    return formatted(done.stdout, root, rel)


def unfenced(text: str) -> str:
    """`text` without its fence lines: a copy carries the blocks, never another golden's edges."""
    return "".join(line for line in text.splitlines(keepends=True) if not FENCE_LINE.match(line))


#: A road marker's worked example, `example="<path>::<symbol>"`, as the goldens spell it.
EXAMPLE = re.compile(r'example="(?P<path>[^":]+)::(?P<symbol>[A-Za-z_][A-Za-z0-9_]*)"')

#: A decorator road marker, `@road("<job>", example=...)`, from its first line to its last.
MARKER = re.compile(
    r'^[ \t]*@road\(\s*"[a-z][a-z0-9_]*",\s*(?P<example>example="[^"]*"),?\s*\)[ \t]*\n', re.M
)


def from_golden(root: Path, golden: Golden, target: str, noun: str) -> Copy:
    """The copy of one extract for `target` and `noun`, formatted; one span per extract file."""
    renames = relocations(golden.app, target, noun)
    copy = Copy(renames=renames)
    originals: dict[str, str] = {}
    for rel in golden.files:
        source = golden.path(rel)
        originals[rel] = (root / source).read_text()
        copy.files[rel] = rename(originals[rel], renames, copy.moved)
    for rel in golden.files:
        renamed = carried_examples(originals[rel], copy.files[rel], copy.files, target)
        text = tidied(unfenced(renamed), root, rel, target)
        copy.files[rel] = text
        copy.spans[rel] = f"{golden.path(rel)}:0-{text.count(chr(10)) + 1}"
    return copy


def carried_examples(original: str, renamed: str, files: dict[str, str], target: str) -> str:
    """`renamed` without the road marker of each example the copy does not carry."""
    sources = list(EXAMPLE.finditer(original))
    copies = list(EXAMPLE.finditer(renamed))
    if len(sources) != len(copies):
        raise FenceError(f"a rename moved a road example's quotes: {len(sources)} → {len(copies)}")
    markers = {found.start("example"): found for found in MARKER.finditer(renamed)}
    prefix = f"apps/{target}/"
    for was, now in reversed(list(zip(sources, copies, strict=True))):
        path = now["path"]
        held = files.get(path.removeprefix(prefix), "") if path.startswith(prefix) else None
        if held is None or was.group(0) == now.group(0):
            continue
        if re.search(rf"^(?:async )?def {now['symbol']}\(", held, re.M):
            continue
        marker = markers.get(now.start())
        if marker is None:
            raise FenceError(f"a road example the copy does not carry is not a decorator's: {path}")
        renamed = renamed[: marker.start()] + renamed[marker.end() :]
    return renamed


def overlong(root: Path, copy: Copy, app: str) -> list[str]:
    """`<path>:<line>` for every line of `copy` ruff's E501 reads past the tree's line length."""
    found: list[str] = []
    for rel, text in copy.files.items():
        done = subprocess.run(  # noqa: S603 — argv list to the venv's ruff, the text on stdin; no shell
            [ruff(), "check", "--select", "E501", "--output-format", "concise", "--exit-zero"]
            + ["--stdin-filename", str(root / "apps" / app / rel), "-"],
            cwd=root,
            input=text,
            capture_output=True,
            text=True,
        )
        found += [
            f"apps/{app}/{rel}:{line.split(':')[1]}"
            for line in done.stdout.splitlines()
            if "E501" in line
        ]
    return found


def fenced_copy(root: Path, golden: Golden, app_dir: Path) -> dict[str, str]:
    """What `app_dir`'s own fences for `golden.key` hold, formatted — the `--check` comparand."""
    verbs = adopt_verbs(root)
    found = collect(app_dir, golden.key, verbs)
    return {
        rel: tidied(unfenced(assemble(blocks)), root, rel, app_dir.name)
        for rel, blocks in found.items()
    }


# --- the face: the worked noun's screens and words, read with their verb fences ------------------

#: The screen shape's golden: the worked face's extract key, and the fence word its base opens with.
FACE = next(s.golden for s in SHAPES if s.key == "screen")
FACE_SUFFIXES = (".ts", ".tsx", ".css")


#: The walk pages' rows (house rule 71): a shared table a face adds its rows to.
ROUTES = "frontend/src/kit/routes.ts"
#: The face's refusal census: its panel-only backlog, a shared table keyed by operation.
UNIONS = "frontend/src/api/refusal-union.test.ts"
#: The one door to the backend: a product page's two reads join its operations.
CLIENT = "frontend/src/api/client.ts"
#: Each shared table: where it opens, and the close its copied rows go before.
SHARED: dict[str, tuple[str, str]] = {
    ROUTES: ("export const ROUTE_TABLE", "\n];\n"),
    UNIONS: ("const PANEL_ONLY", "\n};\n"),
    CLIENT: ("export async function listOrganizations(", "\n\n/** A document path with its"),
}
#: The span a file the screen shape writes from no golden is reported under.
GENERATED = "the screen shape (generated)"


def face_sources() -> tuple[str, ...]:
    """The worked face: its screens, its words, its walk pages and its rows in the route table."""
    word = snake(SOURCE_NOUN)
    return (
        f"frontend/src/screens/{word}",
        f"frontend/src/copy/{word}.ts",
        f"frontend/src/app/example/{word}s",
        *SHARED,
    )


def face_files(root: Path) -> list[str]:
    """Every face source file under `root` that carries a fence, relative to the checkout."""
    found: list[Path] = []
    for source in face_sources():
        path = root / source
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(
                p
                for p in sorted(path.rglob("*"))
                if p.is_file() and p.suffix in FACE_SUFFIXES and not SKIP_PARTS & set(p.parts)
            )
    return [
        p.relative_to(root).as_posix()
        for p in found
        if any(FENCE_LINE.match(line) for line in p.read_text(encoding="utf-8").splitlines())
    ]


def face_word(key: str) -> str:
    """A face fence's word: the base, a verb, or a joint `a+b`."""
    return key.removeprefix(f"{ADOPT}.")


def fenced_lines(text: str, verbs: Sequence[str], where: str = "") -> str:
    """`text`'s fence lines and every line inside one — what a face extract holds."""
    kept: list[str] = []
    depth = 0
    for number, line in enumerate(text.splitlines(), 1):
        fence = parse_fence(line, verbs, f"{where}:{number}: ")
        if fence is not None:
            depth += len(fence.keys) if fence.edge == "begin" else -len(fence.keys)
            kept.append(line)
        elif depth > 0:
            kept.append(line)
    return "\n".join(kept) + "\n"


def face_lines(
    text: str, wanted: Iterable[str], verbs: Sequence[str], where: str = ""
) -> list[str]:
    """The base and `wanted` verbs' lines of one face file; a joint needs every verb it names."""
    chosen = set(wanted)
    opened: list[tuple[str, int]] = []
    kept: list[str] = []
    for number, line in enumerate(text.splitlines(), 1):
        fence = parse_fence(line, verbs, f"{where}:{number}: ")
        if fence is not None:
            for word in map(face_word, fence.keys):
                if fence.edge == "begin":
                    opened.append((word, number))
                elif not any(name == word for name, _ in opened):
                    raise FenceError(f"{where}:{number}: `golden: {word} end` closes nothing")
                else:
                    del opened[max(i for i, (name, _) in enumerate(opened) if name == word)]
            continue
        names = {name for name, _ in opened}
        joints = [set(name.split("+")) for name in names if "+" in name]
        single = {name for name in names if "+" not in name} - {FACE}
        if joints:
            keep = all(j <= chosen for j in joints) and (not single or bool(single & chosen))
        else:
            keep = bool(single & chosen) or (FACE in names and not single)
        if keep:
            kept.append(line)
    if opened:
        word, number = opened[-1]
        raise FenceError(f"{where}:{number}: `golden: {word} begin` is never closed")
    return kept


def face_extracts(root: Path) -> dict[str, str]:
    """`{path under GOLDENS: text}` for the worked face — its fenced lines and its index."""
    verbs = adopt_verbs(root)
    files = face_files(root)
    if not files:
        return {}
    written = {
        f"{FACE}/{rel}{SUFFIX}": fenced_lines((root / rel).read_text(encoding="utf-8"), verbs, rel)
        for rel in files
    }
    written[f"{FACE}/{INDEX}"] = (
        json.dumps({FACE: {"app": "", "files": files}}, indent=2, sort_keys=True) + "\n"
    )
    return written


def face_renames(noun: str) -> tuple[tuple[str, str], ...]:
    """The face's renames: the worked noun's three spellings, then its paths follow them."""
    word = snake(noun)
    return (
        (SOURCE_NOUN, noun),
        (snake(SOURCE_NOUN), word),
        (snake(SOURCE_NOUN).upper(), word.upper()),
    )


def face_copy(
    texts: dict[str, str], noun: str, wanted: Iterable[str], verbs: Sequence[str]
) -> Copy:
    """The face for `noun` from `{source: fenced text}`: the base and `wanted` verbs, renamed."""
    renames = face_renames(noun)
    copy = Copy(renames=renames)
    chosen = tuple(wanted)
    for rel, text in texts.items():
        lines = face_lines(text, chosen, verbs, rel)
        if not lines:
            continue
        target = rename(rel, renames, {})
        copy.files[target] = rename("\n".join(lines) + "\n", renames, copy.moved)
        copy.spans[target] = f"{rel} ({len(lines)} of its fenced lines)"
    return copy


def face_golden(root: Path, golden: Golden) -> dict[str, str]:
    """`{source path: fenced text}` of the face extract `golden` names under `root`."""
    return {rel: (root / golden.path(rel)).read_text(encoding="utf-8") for rel in golden.files}


def face_taken(root: Path, copy: Copy) -> list[str]:
    """The copy's files already under `root`, and a shared table already holding a copied row."""
    taken = [rel for rel in copy.files if rel not in SHARED and (root / rel).exists()]
    for rel, (opens, _) in SHARED.items():
        table = root / rel
        if rel not in copy.files or not table.is_file():
            continue
        held = table.read_text(encoding="utf-8").partition(opens)[2]
        names = [new for _, new in copy.renames]
        rows = [
            line
            for line in copy.files[rel].splitlines()
            if any(name in line for name in names) and line in held
        ]
        taken += [f"{rel}: {line.strip()}" for line in rows[:1]]
    return taken


def face_plan(
    root: Path, golden: Golden, copy: Copy
) -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """`--dry-run`'s files: each new file whole, then each shared table's rows before it closes."""
    written: list[tuple[str, int, str]] = []
    inserted: list[tuple[str, int, str]] = []
    for rel, text in copy.files.items():
        if rel in SHARED:
            opens, close = SHARED[rel]
            before, anchor, after = (root / rel).read_text(encoding="utf-8").partition(opens)
            line = (before + anchor + after.partition(close)[0]).count("\n") + 2
            inserted.append((rel, line, f"before `{close.strip()}` of {opens}"))
            continue
        span = copy.spans[rel]
        source = span if span == GENERATED else golden.path(span.partition(" (")[0])
        written.append((rel, text.count("\n"), source))
    return written, inserted


def face_write(root: Path, copy: Copy) -> None:
    """The copy written under `root`: new files whole, a shared table's rows before it closes."""
    for rel, text in copy.files.items():
        target = root / rel
        if rel in SHARED:
            opens, close = SHARED[rel]
            held = target.read_text(encoding="utf-8")
            before, anchor, after = held.partition(opens)
            body, closing, tail = after.partition(close)
            if not anchor or not closing:
                raise FenceError(f"{rel} has no table opening {opens!r} and closing {close!r}")
            rows = "\n" + text.rstrip("\n")
            target.write_text(before + anchor + body + rows + closing + tail, encoding="utf-8")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
