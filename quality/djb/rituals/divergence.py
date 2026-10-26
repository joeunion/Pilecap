"""The divergence census: template files a product edited, and release names that collide."""

# does-not-cover: a rename — read as one deletion and one addition, never joined.
# does-not-cover: a divergence inside a product-owned file — invisible by construction.
# does-not-cover: whether a `divergence:` line's reason is a good one — paths, never reasons.
# does-not-cover: whether the base is the release this product merged — only that it resolves.
# does-not-cover: a name changed after creation, a computed `db_table`, an inherited kind override.
# does-not-cover: a mount, tag or title not spelled as a literal; a schema class in an unread file.
# does-not-cover: models outside `apps/`; a road marker built by code or under an unwalked root.

from __future__ import annotations

import fnmatch
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook

#: The checkout this census reads by default: the one it lives in.
ROOT = Path(__file__).resolve().parents[3]
#: The door a refusal names when it tells the operator what to type.
DOOR = "./scripts/divergence_census.sh"
#: The reserved globs — the drawers, the product's wherever they appear; counted as text.
DRAWER_GLOBS = ("**/local/**", "*.local.md", "apps/conftest_local.py")
#: The product's written base declaration, in the drawer.
TEMPLATE_BASE_DRAWER = "scripts/local/template-base"
#: The reader name for the working tree; every other reader is a git ref.
TREE = "tree"
TAG_COMMIT_WHERE = (
    "where the tag is fetched (a laptop with the 'template' remote), then commit the drawer"
)
RELEASE_REF = "v<the release you are folding>"
#: The shared set: adjudicated by hand at a merge, never a divergence.
SHARED_EXACT = frozenset(
    {
        "apps/core/roles.py",
        "pyproject.toml",
        "uv.lock",
        "compose.yaml",
        ".env.example",
        "quality/budgets.yaml",
        "scripts/test_impact.json",
        ".secrets.baseline",
    }
)
SHARED_SUFFIXES = ("pytest_durations.json", "gate_member_durations.json")
SHARED_GLOBS = ("compose.*.yaml",)
TEMPLATE_WORKFLOWS = frozenset({".github/workflows/ci.yml"})
CODEOWNERS = ".github/CODEOWNERS"
CODEOWNERS_TEMPLATE = ".github/CODEOWNERS.template"
TEMPLATE_DOCS = frozenset(
    {
        "docs/product/build-contract.md",
        "docs/product/instruments.md",
        "docs/product/partition-closure.md",
        "docs/product/publication-manifest.md",
        "docs/product/api-editorial-standard.md",
        "docs/product/scale-envelope.md",
    }
)
#: The publication bucket rules a path under them makes template-owned.
TEMPLATE_RULES = frozenset({"R2", "R3", "R4", "R5", "R9"})
#: The worked example: a product may delete it; an edit to what it keeps is a divergence.
WORKED_EXAMPLE_GLOBS = (
    "apps/example*/*",
    "frontend/src/screens/widget/*",
    "frontend/src/screens/customer/*",
    "frontend/src/copy/widget.ts",
    "frontend/src/copy/customer.ts",
)
_CY = "docs/product/cycles"
_BR = "docs/product/briefs"
#: The publication bucket rules as `archaeology_lib.sh::rules_for`'s blocks; first arm wins in one.
BUCKET_RULES: tuple[tuple[tuple[str, tuple[str, ...]], ...], ...] = (
    (("R1", ("apps/*", "config/*", "manage.py", "pilecap/*")),),
    (("R2", ("quality/*", "docs/product/instruments.md")),),
    (
        (
            "R12",
            (
                "scripts/test_impact.json",
                "scripts/pytest_durations.json",
                "scripts/gate_member_durations.json",
            ),
        ),
        (
            "R14",
            (
                ".github/workflows/proof-from-zero.yml",
                ".github/workflows/nightly-proof.yml",
                ".github/workflows/mirror-images.yml",
            ),
        ),
        (
            "R3",
            (
                "scripts/*",
                "deploy/*",
                "perf/*",
                "compose.yaml",
                "compose/*",
                "Dockerfile",
                ".dockerignore",
                ".devcontainer/*",
                ".github/*",
            ),
        ),
    ),
    (
        (
            "R4",
            (
                "pyproject.toml",
                "uv.lock",
                ".python-version",
                ".env.example",
                ".gitignore",
                ".editorconfig",
                ".gitattributes",
                ".secrets.baseline",
                "vendor/*",
                "templates/*",
            ),
        ),
    ),
    (
        (
            "R5",
            (
                ".claude/skills/*",
                ".claude/agents/*",
                "CLAUDE.md",
                "README.md",
                "docs/runbooks/*",
                "docs/standards.md",
            ),
        ),
    ),
    (("R6", ("TEMPLATE_VERSION", "CHANGELOG.md")),),
    (
        (
            "R7",
            tuple(
                f"docs/product/{name}.md"
                for name in (
                    "north-star",
                    "queue",
                    "queue-detail",
                    "readouts",
                    "misses",
                    "in-flight",
                    "goal-posts",
                    "design-agreements",
                    "pilot-readiness",
                    "rep-day",
                    "threat-model",
                )
            ),
        ),
    ),
    (
        ("R8S", (f"{_CY}/EXAMPLE-cycle-plan.md", f"{_CY}/README.md", f"{_BR}/README.md")),
        (
            "R8",
            (
                f"{_CY}/*",
                f"{_BR}/*",
                "docs/product/archive/*",
                "docs/product/retro/*",
                "docs/product/drafts/*",
                "docs/product/proposals/*",
                "docs/product/surveys/*",
                "docs/product/reports/*",
                "docs/product/pm-handoff-*.md",
            ),
        ),
    ),
    (
        (
            "R9",
            tuple(
                f"docs/product/{name}"
                for name in (
                    "adrs-ingredients.md",
                    "api-editorial-standard.md",
                    "architecture.md",
                    "build-contract.md",
                    "operating-protocol.md",
                    "partition-closure.md",
                    "scale-envelope.md",
                    "publication-manifest.md",
                    "design/*",
                    "adrs/*",
                )
            ),
        ),
    ),
    (("R10", ("docs/product/skeletons/*",)),),
    (("R11", ("frontend/*",)),),
    (("R13", ("docs/sdk/*",)),),
)
COLL_REMEDY = (
    "remedy: rename YOURS — CHANGELOG.md § [2.4.1] › What a product does at the merge › "
    "the rename road; the template's name is the release's"
)
COLL_KIND_REMEDY = (
    'remedy: give YOUR model a kind of its own — one line on its class, authz_kind = "<its own '
    "word>\"; the release's kind is the platform contract every product grants against, and it "
    "does not move"
)
COLL_MOUNT_REMEDY = (
    'remedy: mount YOURS elsewhere — PREFIX = "<its own word>" in your api.py (or the route '
    "path's first segment, when PREFIX is \"\"); the release's mount is the platform's"
)
COLL_TAG_REMEDY = (
    'remedy: tag YOURS with a word of its own — Router(tags=["<its own word>"]) and the matching '
    "TAGS key; a tag is a scope family, and one key across two apps is one token ceiling that "
    "reaches both"
)
COLL_TITLE_REMEDY = (
    'remedy: give YOUR tag a display of its own — Tag("<its own words>", …); a heading is what a '
    "reader of the document sees, and two apps under one heading are one section describing either"
)
COLL_SCHEMA_REMEDY = (
    "remedy: rename YOUR schema class — class <YourWord>Out(Schema); the document publishes one "
    "component per name and describes both apps' routes by whichever was discovered last"
)
#: Rule 84's valve word, assembled so this file declares no valve of its own.
COLL_ROAD_VALVE = "rule" + "-84"
COLL_ROAD_REMEDY = (
    "remedy: adopt the platform's — call <release path> (manage.py roads <job> after the merge) "
    "and delete yours; or keep yours and DECLARE it — a comment line directly above your marker, "
    f"`# {COLL_ROAD_VALVE}: <why your road stays>`, which house rule 84 counts and "
    "`manage.py roads` prints as kept"
)
#: The classes a release line keys the pairing by.
PAIR_CLASSES = frozenset(
    {"label", "table", "index", "constraint", "kind", "mount", "tag", "title", "schema", "road"}
)
#: The trailer's counters, in the order it prints them.
COUNTERS = (
    "label",
    "table",
    "index",
    "constraint",
    "kind",
    "reserved",
    "mount",
    "tag",
    "title",
    "schema",
    "road",
)
#: Where a road marker may live, and what the road census reads in each.
ROAD_ROOTS = ("apps", "config", "quality", "scripts", "deploy", "frontend/src")
ROAD_SUFFIXES = (".py", ".sh", ".ts", ".tsx")
RESERVED = "djb_"
USAGE_UNKNOWN = (
    "!! unknown argument '{arg}': divergence_census.sh takes nothing, --if-declared,",
    "   --against <release ref> [--sdk [--fix]], --roads, or --codeowners [<path>]",
)
DIED = (
    "!! divergence_census: DIED part-way ({cause}).",
    "   The run ended before any end this census authors. NOTHING THIS RUN",
    "   PRINTED IS A VERDICT — the diagnostic above this line names",
    "   the cause. Could-not-look, never a clean census.",
)


class Refused(CouldNotLook):
    """Exit 2 whose sentences are already on stderr: an end this census authored."""


class Unreadable(CouldNotLook):
    """A read under a reader failed; the caller names what could not be read."""


def out(text: str = "") -> None:
    """One line on stdout, flushed."""
    print(text, flush=True)


def err(text: str) -> None:
    """One line on stderr, flushed."""
    print(text, file=sys.stderr, flush=True)


def refuse(*lines: str) -> Refused:
    """The lines on stderr; the exit 2 they end in."""
    for line in lines:
        err(line)
    return Refused(lines[0] if lines else "")


def refuse_if_piped() -> None:
    """Exit 2 when stdout is a pipe outside CI: the exit status is the verdict."""
    if os.environ.get("CI"):
        return
    try:
        piped = stat.S_ISFIFO(os.fstat(1).st_mode)
    except OSError:
        piped = False
    if piped:
        raise refuse(
            "!! divergence_census.sh refuses pipes — run it bare or redirect to a file.",
            "   The exit status is the verdict, and a filter replaces it.",
        )


def git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """`git <argv>` in `root`, both streams captured."""
    return subprocess.run(["git", *argv], cwd=root, capture_output=True, text=True, check=False)


def resolves(root: Path, ref: str) -> bool:
    """`git rev-parse -q --verify <ref>^{commit}` answers."""
    return git(root, "rev-parse", "-q", "--verify", f"{ref}^{{commit}}").returncode == 0


# --- the classifier ------------------------------------------------------------------------------


def platform_apps(root: Path) -> list[str]:
    """`platform_apps:` out of `quality/partition.yaml`, through the partition's own reader."""
    from quality.partition import platform_apps_in

    try:
        return platform_apps_in((root / "quality/partition.yaml").read_text())
    except (OSError, CouldNotLook):
        return []


def is_platform_app_path(path: str, platform: Sequence[str]) -> bool:
    """`apps/<label>/…` whose label is a platform app, matched by whole name."""
    label = path.removeprefix("apps/").split("/", 1)[0]
    return label in platform


def shared_by_glob(path: str) -> bool:
    """A path the shared set names by pattern (`SHARED_GLOBS`)."""
    return any(fnmatch.fnmatchcase(path, glob) for glob in SHARED_GLOBS)


def is_shared(path: str) -> bool:
    """One of the files both sides legitimately write; adjudicated by hand at a merge."""
    if path in SHARED_EXACT or path.startswith("deploy/tests/") or shared_by_glob(path):
        return True
    return path.endswith(SHARED_SUFFIXES)


def rule_ids(path: str) -> list[str]:
    """Every publication rule id `path` matches, in the rules' order."""
    hits: list[str] = []
    for block in BUCKET_RULES:
        for rule, globs in block:
            if any(fnmatch.fnmatchcase(path, glob) for glob in globs):
                hits.append(rule)
                break
    return hits


def rules_for(paths: Iterable[str]) -> dict[str, list[str]]:
    """Every path's publication rule ids."""
    return {path: rule_ids(path) for path in paths}


def is_drawer(path: str) -> bool:
    """A reserved drawer path, the product's wherever it appears (`DRAWER_GLOBS`)."""
    local = path.startswith("local/") or "/local/" in path or path.endswith(".local.md")
    return local or path == "apps/conftest_local.py"


def is_worked_example(path: str) -> bool:
    """A path of the worked example: `apps/example*`, the widget and customer faces and copy."""
    return any(fnmatch.fnmatchcase(path, glob) for glob in WORKED_EXAMPLE_GLOBS)


def removed_worked_example(root: Path, path: str) -> bool:
    """Whether `path` is the worked example's and the app or file it lives in is not on `root`."""
    for glob in WORKED_EXAMPLE_GLOBS:
        if fnmatch.fnmatchcase(path, glob):
            home = root / "/".join(path.split("/")[: len(glob.removesuffix("/*").split("/"))])
            if home.is_file():
                return False
            return not any(
                held.is_file() and "__pycache__" not in held.parts for held in home.rglob("*")
            )
    return False


def ownership_of(path: str, rules: Sequence[str], platform: Sequence[str]) -> str:
    """`template`, `worked-example`, `product` or `shared`: drawers, shared, carve-outs, rules."""
    if is_drawer(path):
        return "product"
    if is_shared(path):
        return "shared"
    if is_worked_example(path):
        return "worked-example"
    if path in TEMPLATE_WORKFLOWS:
        return "template"
    if path.startswith(".github/workflows/") or path in ("README.md", CODEOWNERS):
        return "product"
    if path in TEMPLATE_DOCS or path.startswith("docs/product/design/"):
        return "template"
    if path.startswith("docs/product/"):
        return "product"
    if len(rules) != 1:
        return "product"
    rule = rules[0]
    if rule in TEMPLATE_RULES:
        return "template"
    if rule == "R1":
        if path.startswith(("config/", "pilecap/")) or path == "manage.py":
            return "template"
        if path.startswith("apps/"):
            return "template" if is_platform_app_path(path, platform) else "product"
    return "product"


# --- the base ------------------------------------------------------------------------------------


@dataclass
class Base:
    """The declared base and the reader that declared it."""

    ref: str
    source: str


#: The variable this module's base reader is named after: the `template base` drawer's reader.
BASE_FROM = TEMPLATE_BASE_DRAWER


def declare_base(root: Path, environ: dict[str, str] | os._Environ[str]) -> Base | None:
    """The typed override, then the drawer, then the `template` remote's tag; None when none."""
    typed = environ.get("DJB_TEMPLATE_BASE", "")
    if typed:
        return Base(typed, "DJB_TEMPLATE_BASE")
    drawer = root / BASE_FROM
    if drawer.is_file():
        ref = "".join(drawer.read_text().split())
        if not ref:
            raise refuse(
                f"!! {TEMPLATE_BASE_DRAWER} is empty — a declaration that names no",
                "   ref is not a declaration. Write the commit of the release you merged",
                "   (git rev-parse '<tag>^{commit}'), or delete",
                "   the file and let the remote derive it.",
            )
        return Base(ref, BASE_FROM)
    remotes = git(root, "remote").stdout.splitlines()
    if "template" not in remotes:
        return None
    try:
        version = "".join((root / "TEMPLATE_VERSION").read_text().split())
    except OSError:
        version = ""
    if not re.match(r"^[0-9].*\.[0-9].*\.[0-9]", version):
        raise refuse(
            "!! a 'template' remote is configured and TEMPLATE_VERSION does not read",
            f'   as <major>.<minor>.<patch>: "{version}". The base tag is derived from',
            "   it, and a derivation that cannot be read is a could-not-look.",
        )
    return Base(f"v{version}", "the 'template' remote, derived from TEMPLATE_VERSION")


# --- the readers: the working tree or a ref, one parser each -------------------------------------


def read(root: Path, reader: str, path: str) -> str:
    """The file's text from the working tree or a ref; `Unreadable` when it cannot be read."""
    if reader == TREE:
        try:
            return (root / path).read_text(errors="replace")
        except OSError as error:
            raise Unreadable(path) from error
    done = git(root, "show", f"{reader}:{path}")
    if done.returncode != 0:
        raise Unreadable(path)
    return done.stdout


def ls_tree(root: Path, reader: str, *specs: str, recursive: bool = True) -> list[str]:
    """`git ls-tree [-r] --name-only <reader> -- <specs>`; `Unreadable` when git fails."""
    argv = ["ls-tree", *(["-r"] if recursive else []), "--name-only", reader, "--", *specs]
    done = git(root, *argv)
    if done.returncode != 0:
        raise Unreadable(" ".join(specs))
    return [line for line in done.stdout.splitlines() if line]


def files_of(
    root: Path, reader: str, appdir: str, singles: Sequence[str], package: str
) -> list[str]:
    """`<appdir>/<single>` files and `<appdir>/<package>/*.py`, from the tree or a ref."""
    if reader == TREE:
        found = [f"{appdir}/{s}" for s in singles if (root / appdir / s).is_file()]
        pkg = root / appdir / package
        found += sorted(f"{appdir}/{package}/{p.name}" for p in pkg.glob("*.py") if p.is_file())
        return found
    return ls_tree(root, reader, *(f"{appdir}/{s}" for s in singles), f"{appdir}/{package}/")


def _first(path: str) -> str:
    """The first path segment a route answers at; '' for the root or a `{parameter}`."""
    segs = path.lstrip("/").split("/")
    if not segs or segs[0] == "" or segs[0].startswith("{"):
        return ""
    return segs[0]


def _owner_of(line: str) -> str:
    """The router a decorator or an `add_router` line belongs to."""
    owner = re.sub(r"^[ \t]*@?", "", line, count=1)
    return owner.split(".", 1)[0]


ROUTE_OPEN = re.compile(r"^[ \t]*@[A-Za-z_][A-Za-z0-9_]*\.(get|post|patch|put|delete)\([ \t]*$")
ROUTE_LINE = re.compile(
    r"^[ \t]*@[A-Za-z_][A-Za-z0-9_]*\.(get|post|patch|put|delete)\([ \t]*[\"'](/[^\"']*)"
)
ROUTE_NEXT = re.compile(r"^[ \t]*[\"'](/[^\"']*)")
ADD_ROUTER = re.compile(
    r"^[ \t]*[A-Za-z_][A-Za-z0-9_]*\.add_router\([ \t]*[\"']([^\"']*)[\"'][ \t]*,[ \t]*"
    r"([A-Za-z_][A-Za-z0-9_]*)"
)
TAGS_KW = re.compile(r"(^|[(, \t])tags=\[[^]]*\]")
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
TAGS_OPEN = re.compile(r"^TAGS[ \t]*(:[^=]*)?=[ \t]*\{")
TAGS_ONE_LINE = re.compile(r"^TAGS[ \t]*(:[^=]*)?=[ \t]*\{.*\}[ \t]*$")
TAG_ENTRY = re.compile(r"[\"'][ \t]*:[ \t]*[A-Za-z_][A-Za-z0-9_.]*\(")
TAG_ASSIGN = re.compile(r"^TAGS\[[^]]*\][ \t]*=[ \t]*[A-Za-z_][A-Za-z0-9_.]*\(")
TITLE_LITERAL = re.compile(r"^[ \t]*(display[ \t]*=[ \t]*)?(\"[^\"]*\"|'[^']*')")
PREFIX_LINE = re.compile(r"^PREFIX[ \t]*(:[^=]*)?=[ \t]*[\"']")
ROUTER_LINE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*[ \t]*(:[^=]*)?=[ \t]*Router\(")
SCHEMA_CLASS = re.compile(r"^class ([A-Za-z_][A-Za-z0-9_]*)\(")


@dataclass
class _Mounts:
    """The mount reader's running state over one app's api files."""

    label: str
    rows: list[tuple[str, ...]] = field(default_factory=list)
    seen: set[tuple[str, str, str]] = field(default_factory=set)
    routes: list[tuple[str, str, str]] = field(default_factory=list)
    nested: set[str] = field(default_factory=set)
    untitled: list[str] = field(default_factory=list)
    spelled: bool = False
    empty: bool = False
    routerfile: str = ""

    def emit(self, klass: str, value: str, file: str) -> None:
        """One row, once per (class, value, file)."""
        if value == "" or (klass, value, file) in self.seen:
            return
        self.seen.add((klass, value, file))
        self.rows.append((klass, value, file))

    def route(self, owner: str, path: str, file: str) -> None:
        """A route's first segment, held until the end decides whether it mounts."""
        seg = _first(path)
        if seg:
            self.routes.append((owner, seg, file))

    def untitle(self, file: str) -> None:
        """A `Tag(` whose display literal was not read."""
        if file not in self.untitled:
            self.untitled.append(file)

    def title_literal(self, text: str, file: str) -> bool:
        """The display literal at the head of `text`, emitted; False when there is none."""
        match = TITLE_LITERAL.match(text)
        if not match:
            return False
        self.emit("title", match.group(2)[1:-1], file)
        return True

    def read(self, file: str, text: str) -> None:
        """One api file, line by line, in the census's rule order."""
        pending = ""
        intags = False
        tpend = False
        for line in text.split("\n"):
            if pending:
                nxt = ROUTE_NEXT.match(line)
                if nxt:
                    self.route(pending, nxt.group(1), file)
                pending = ""
            if re.match(r"^[ \t]*#", line):
                continue
            if tpend:
                tpend = False
                if not self.title_literal(line, file):
                    self.untitle(file)
            if TAGS_OPEN.match(line):
                intags = True
            if intags or line.startswith("TAGS["):
                hit = TAG_ENTRY.search(line) or TAG_ASSIGN.search(line)
                if hit:
                    rest = line[hit.end() :]
                    if rest.strip(" \t") == "":
                        tpend = True
                    elif not self.title_literal(rest, file):
                        self.untitle(file)
                if line.startswith("}") or TAGS_ONE_LINE.match(line):
                    intags = False
            if PREFIX_LINE.match(line):
                value = re.sub(r"^[^\"']*[\"']", "", line, count=1)
                value = re.sub(r"[\"'].*$", "", value)
                self.spelled = True
                value = value.strip("/")
                if value == "":
                    self.empty = True
                else:
                    self.emit("mount", _first(value), file)
            if ROUTER_LINE.match(line) and not self.routerfile:
                self.routerfile = file
            if ROUTE_OPEN.match(line):
                pending = _owner_of(line)
            else:
                hit = ROUTE_LINE.match(line)
                if hit:
                    self.route(_owner_of(line), hit.group(2), file)
            added = ADD_ROUTER.match(line)
            if added and _first(added.group(1)):
                self.nested.add(added.group(2))
                self.route(_owner_of(line), added.group(1), file)
            rest = line
            while True:
                hit = TAGS_KW.search(rest)
                if not hit:
                    break
                for quoted in QUOTED.findall(hit.group(0)):
                    self.emit("tag", quoted[1:-1], file)
                rest = rest[hit.end() :]
        if tpend:
            self.untitle(file)

    def finish(self) -> list[tuple[str, ...]]:
        """The label mount, the empty-prefix routes, the untitled files; every row."""
        if not self.spelled and self.routerfile:
            self.emit("mount", self.label, self.routerfile)
        if self.empty:
            for owner, seg, file in self.routes:
                if owner not in self.nested:
                    self.emit("mount", seg, file)
        return [*self.rows, *(("unparsed", f, "-", "title") for f in self.untitled)]


def _nested_api(path: str, appdir: str) -> bool:
    """A file in a subdirectory of the api package: not the module's."""
    rel = path.removeprefix(f"{appdir}/")
    return rel.startswith("api/") and rel.count("/") >= 2


def census_mounts(root: Path, reader: str, appdir: str, label: str) -> list[tuple[str, ...]]:
    """The app's REST mounts, router tags and tag titles, read as text from its api files."""
    state = _Mounts(label)
    for f in files_of(root, reader, appdir, ("api.py",), "api"):
        if not f.endswith(".py") or _nested_api(f, appdir):
            continue
        state.read(f, read(root, reader, f))
    return state.finish()


def census_schemas(root: Path, reader: str, appdir: str) -> list[tuple[str, ...]]:
    """Every `class <Name>(` at column zero in the app's schema and api files."""
    rows: list[tuple[str, ...]] = []
    for f in files_of(root, reader, appdir, ("schemas.py", "api.py"), "api"):
        if not f.endswith(".py") or _nested_api(f, appdir):
            continue
        for line in read(root, reader, f).split("\n"):
            hit = SCHEMA_CLASS.match(line)
            if hit:
                rows.append(("schema", hit.group(1), f))
    return rows


MIGRATION_TOKEN = re.compile(
    r"migrations\.[A-Za-z]+\(|UniqueConstraint\(|CheckConstraint\(|[A-Za-z0-9_]*Index\("
    r"|[^A-Za-z0-9_]name *= *\"[^\"]*\"|^name *= *\"[^\"]*\"|\"db_table\" *: *\"[^\"]*\""
)


def migration_names(text: str, label: str, file: str) -> list[tuple[str, ...]]:
    """The tables, models, indexes and unique constraints one migration file creates."""
    rows: list[tuple[str, ...]] = []
    model = dbt = want = ""
    inmodel = False

    def flush() -> None:
        nonlocal model, dbt, inmodel
        if model:
            rows.append(("table", dbt or f"{label}_{model.lower()}", file))
            rows.append(("model", model, file))
        model = dbt = ""
        inmodel = False

    for line in text.split("\n"):
        if re.match(r"^[ \t]*#", line):
            continue
        rest = line
        while True:
            hit = MIGRATION_TOKEN.search(rest)
            if not hit:
                break
            tok = hit.group(0)
            rest = rest[hit.end() :]
            if tok.startswith("migrations."):
                flush()
                inmodel = tok.endswith("CreateModel(")
                want = "model" if inmodel else ""
            elif tok.endswith("UniqueConstraint("):
                want = "constraint"
            elif tok.endswith("CheckConstraint("):
                want = "check"
            elif tok.endswith("Index("):
                want = "index"
            elif tok.startswith('"db_table"'):
                if inmodel:
                    dbt = re.sub(r'^"db_table" *: *"', "", tok)[:-1]
            else:
                value = re.sub(r'^.*name *= *"', "", tok)[:-1]
                if want == "model":
                    model = value
                elif want in ("index", "constraint"):
                    rows.append((want, value, file))
                want = ""
    flush()
    return rows


CLASS_HEAD = re.compile(r"^class ([A-Za-z_][A-Za-z0-9_]*)[(:]")
KIND_LINE = re.compile(r"^    authz_kind[ \t]*(:[^=]*)?=")
KIND_OF_LINE = re.compile(r"^    authz_kind_of[ \t]*(:[^=]*)?=")


def kind_overrides(text: str) -> list[tuple[str, str]]:
    """(class, word | @none | @child) for every kind override typed in a class body."""
    rows: list[tuple[str, str]] = []
    cls = ""
    for line in text.split("\n"):
        head = CLASS_HEAD.match(line)
        if head:
            cls = head.group(1)
            continue
        if re.match(r"^[^ \t#]", line):
            cls = ""
        if not cls:
            continue
        for pattern, child in ((KIND_LINE, False), (KIND_OF_LINE, True)):
            if not pattern.match(line):
                continue
            value = re.sub(r"^[^=]*=[ \t]*", "", line, count=1)
            value = re.sub(r"[ \t]*(#.*)?$", "", value, count=1)
            if child:
                if value != "None":
                    rows.append((cls, "@child"))
            elif value == "None":
                rows.append((cls, "@none"))
            elif re.match(r"^\"[^\"]*\"$|^'[^']*'$", value):
                rows.append((cls, value[1:-1]))
    return rows


def snake(name: str) -> str:
    """`WidgetEntry` → `widget_entry`, as `apps/core/authz.py` derives a kind."""
    return "".join(("_" if i and c.isupper() else "") + c.lower() for i, c in enumerate(name))


def census_names(root: Path, reader: str, appspy: str) -> list[tuple[str, ...]]:
    """One row per name an app holds: label, mounts, tags, titles, schemas, tables, kinds."""
    appdir = appspy.removesuffix("/apps.py")
    migdir = f"{appdir}/migrations"
    body = read(root, reader, appspy)
    label = name = ""
    for line in body.split("\n"):
        if re.match(r"^[ \t]+label[ \t]*=[ \t]*[\"']", line):
            label = re.sub(r"[\"'].*$", "", re.sub(r"^[^\"']*[\"']", "", line, count=1))
        if re.match(r"^[ \t]+name[ \t]*=[ \t]*[\"']", line) and not name:
            name = re.sub(r"[\"'].*$", "", re.sub(r"^[^\"']*[\"']", "", line, count=1))
    label = label or (name.split(".")[-1] if name else "") or appdir.rsplit("/", 1)[-1]
    rows: list[tuple[str, ...]] = [("label", label, appdir)]
    rows += census_mounts(root, reader, appdir, label)
    rows += census_schemas(root, reader, appdir)
    if reader == TREE:
        if not (root / migdir).is_dir():
            return [*rows, ("unparsed", appdir, "-")]
        files = sorted(f"{migdir}/{p.name}" for p in (root / migdir).glob("*.py") if p.is_file())
    else:
        files = ls_tree(root, reader, f"{migdir}/", recursive=False)
        if not files:
            return [*rows, ("unparsed", appdir, "-")]
    rows.append(("parsed", appdir, "-"))
    mig: list[tuple[str, ...]] = []
    for f in files:
        if f.endswith(".py"):
            mig += migration_names(read(root, reader, f), label, f)
    rows += mig
    overrides: dict[str, str] = {}
    for f in files_of(root, reader, appdir, ("models.py",), "models"):
        if not f.endswith(".py"):
            continue
        for cls, word in kind_overrides(read(root, reader, f)):
            if cls not in overrides or word == "@child":
                overrides[cls] = word
    seen: set[str] = set()
    for row in mig:
        if row[0] != "model" or row[1] in seen:
            continue
        seen.add(row[1])
        kind = overrides.get(row[1], snake(row[1]))
        if kind not in ("@none", "@child"):
            rows.append(("kind", kind, f"{appdir} · {row[1]}"))
    return rows


# --- the roads: `quality.roads.census` over each side's files ------------------------------------


def road_files(root: Path, reader: str, which: str, platform: Sequence[str]) -> list[str]:
    """The files the road census reads: every one that spells `road`, or only yours."""
    if reader == TREE:
        listing = []
        for top in ROAD_ROOTS:
            base = root / top
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if path.suffix not in ROAD_SUFFIXES or not path.is_file():
                    continue
                try:
                    if "road" in path.read_text(errors="replace"):
                        listing.append(str(path.relative_to(root)))
                except OSError as error:
                    raise Unreadable(str(path)) from error
    else:
        done = git(root, "grep", "-l", "-F", "road", reader, "--", *ROAD_ROOTS)
        if done.returncode > 1:
            raise Unreadable(f"{reader}: git grep")
        prefix = f"{reader}:"
        listing = [
            line[len(prefix) :] for line in done.stdout.splitlines() if line.startswith(prefix)
        ]
    chosen: list[str] = []
    for rel in sorted(set(listing)):
        if not rel.endswith(ROAD_SUFFIXES):
            continue
        if which == "yours":
            if "/local/" not in f"/{rel}":
                if not rel.startswith("apps/") or rel.count("/") < 2:
                    continue
                if is_platform_app_path(rel, platform):
                    continue
        chosen.append(rel)
    return chosen


def census_roads_over(
    root: Path, reader: str, which: str, platform: Sequence[str]
) -> list[tuple[str, ...]]:
    """Every marker the population holds — `quality.roads.census` over the files, either side."""
    from quality.roads import CensusError, census

    files = road_files(root, reader, which, platform)
    rows: list[tuple[str, ...]] = []
    if not files:
        return rows
    with tempfile.TemporaryDirectory(prefix="djb-divergence-roads.") as work:
        world = Path(work)
        for rel in files:
            target = world / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(read(root, reader, rel))
        while True:
            try:
                markers = census(world)
                break
            except CensusError as refusal:
                where = str(refusal).split(":", 1)[0]
                if not (world / where).is_file():
                    raise Unreadable(f"the road census: {refusal}") from refusal
                rows.append(("unparsed", where))
                (world / where).unlink()
    for marker in markers:
        if marker.valve is not None:
            rows.append(("road", marker.job, marker.path, "kept"))
        else:
            rows.append(("road", marker.job, marker.path))
    return rows


# --- the collision census ------------------------------------------------------------------------


def pair(
    release: Sequence[tuple[str, ...]], yours: Sequence[tuple[str, ...]], ref: str
) -> dict[str, int]:
    """The pairs, one line each and a remedy under each; the counts per class."""
    rel: dict[tuple[str, str], str] = {}
    for row in release:
        if row[0] in PAIR_CLASSES and (row[0], row[1]) not in rel:
            rel[(row[0], row[1])] = row[2]
    n = dict.fromkeys(COUNTERS, 0)
    for row in yours:
        klass, value = row[0], row[1]
        where = row[2] if len(row) > 2 else ""
        tail = row[3] if len(row) > 3 else ""
        known = (klass, value) in rel
        theirs = rel.get((klass, value), "")
        if klass == "unparsed" and tail == "title":
            out(
                f"   unparsed: {value} (yours) — a Tag( whose display literal is not on its line"
                " or the next; its title was not read"
            )
            continue
        if klass in ("title", "schema") and known:
            out(f"collision: {klass} {value} — yours ({where}) vs {ref} ({theirs})")
            out(f"   {COLL_TITLE_REMEDY if klass == 'title' else COLL_SCHEMA_REMEDY}")
            n[klass] += 1
            continue
        if klass == "road" and known and tail == "kept":
            out(
                f"   kept: road {value} — yours ({where}) beside {ref} ({theirs}), declared by the"
                " valve above your marker"
            )
            continue
        if klass == "road" and known:
            out(f"collision: road {value} — yours ({where}) vs {ref} ({theirs})")
            out(f"   {COLL_ROAD_REMEDY}")
            n["road"] += 1
            continue
        if klass == "unparsed" and len(row) == 2:
            out(
                f"   unparsed: {value} (yours) — a road marker that does not split into a job and"
                " its contract; its job was not read"
            )
            continue
        if klass in ("mount", "tag") and value.startswith(RESERVED):
            out(
                f"collision: reserved prefix djb_ — {klass} {value} in {where} (yours); djb_ is"
                " the template's namespace for its platform apps"
            )
            out(f"   {COLL_MOUNT_REMEDY if klass == 'mount' else COLL_TAG_REMEDY}")
            n["reserved"] += 1
            continue
        if klass in ("mount", "tag") and known:
            out(f"collision: {klass} {value} — yours ({where}) vs {ref} ({theirs})")
            out(f"   {COLL_MOUNT_REMEDY if klass == 'mount' else COLL_TAG_REMEDY}")
            n[klass] += 1
            continue
        if klass == "kind" and known:
            out(f"collision: kind {value} — yours ({where}) vs {ref} ({theirs})")
            out(f"   {COLL_KIND_REMEDY}")
            n["kind"] += 1
            continue
        if klass == "label" and value.startswith(RESERVED):
            out(
                f"collision: reserved prefix djb_ — {where} (yours); djb_ is the template's"
                " namespace for its platform apps"
            )
            out(f"   {COLL_REMEDY}")
            n["reserved"] += 1
        if klass in ("label", "table", "index", "constraint") and known:
            if klass == "label":
                out(f"collision: label {value} — {where} (yours) vs {theirs} ({ref})")
            else:
                out(f"collision: {klass} {value} — yours ({where}) vs {ref} ({theirs})")
            out(f"   {COLL_REMEDY}")
            n[klass] += 1
        if klass == "unparsed":
            out(
                f"   unparsed: {value} (yours) — no migrations/ directory: its label was read, its"
                " tables, indexes and constraints were not"
            )
    return n


def collisions(root: Path, ref: str, platform: Sequence[str]) -> dict[str, int]:
    """The collision half against `ref`: the pairs per class, every one printed."""
    if not resolves(root, ref):
        raise refuse(
            f"!! --against {ref} does not resolve to a commit in this checkout.",
            "   A release you have not fetched cannot be compared with. Fetch it and re-run:",
            "     git fetch template --tags",
            "   This census writes nothing, so it will not fetch for you. Could-not-look,",
            "   never a clean collision census.",
        )
    out("")
    out(f"-- collisions: the release's app names against yours ({ref})")
    try:
        listing = ls_tree(root, ref, "apps/")
    except Unreadable:
        raise refuse(f"!! git could not list apps/ at {ref} — could-not-look") from None
    release: list[tuple[str, ...]] = []
    for path in listing:
        parts = path.split("/")
        if len(parts) == 3 and parts[0] == "apps" and parts[2] == "apps.py":
            try:
                release += census_names(root, ref, path)
            except Unreadable:
                raise refuse(
                    f"!! a git read of {path} (or its migrations) at {ref} failed — could-not-look"
                ) from None
    yours: list[tuple[str, ...]] = []
    for appspy in sorted((root / "apps").glob("*/apps.py")):
        if not appspy.is_file():
            continue
        path = str(appspy.relative_to(root))
        if is_platform_app_path(path, platform):
            continue
        try:
            yours += census_names(root, TREE, path)
        except Unreadable:
            raise refuse(
                f"!! {path} (or its migrations) could not be read — could-not-look"
            ) from None
    try:
        release += census_roads_over(root, ref, "all", platform)
    except Unreadable:
        raise refuse(
            f"!! a git read of the release's road markers at {ref} failed — could-not-look"
        ) from None
    try:
        yours += census_roads_over(root, TREE, "yours", platform)
    except Unreadable:
        raise refuse(
            "!! the road markers of your files could not be read — could-not-look"
        ) from None
    n = pair(release, yours, ref)
    for row in release:
        if row[0] == "unparsed" and len(row) == 3:
            out(f"   unparsed: {row[1]} (release) — no migrations/ directory")
    for row in release:
        if row[0] == "unparsed" and len(row) == 2:
            out(
                f"   unparsed: {row[1]} (release) — a road marker that does not split into a job"
                " and its contract; its job was not read"
            )
    for row in release:
        if row[0] == "unparsed" and len(row) > 3 and row[3] == "title":
            out(
                f"   unparsed: {row[1]} (release) — a Tag( whose display literal is not on its"
                " line or the next; its title was not read"
            )

    def count(rows: Sequence[tuple[str, ...]], klass: str, width: int | None = None) -> int:
        return sum(1 for r in rows if r[0] == klass and (width is None or len(r) == width))

    pairs = sum(n.values())
    out(
        "collisions: "
        f"labels={n['label']} tables={n['table']} indexes={n['index']} "
        f"constraints={n['constraint']} kinds={n['kind']} reserved={n['reserved']} "
        f"mounts={n['mount']} tags={n['tag']} titles={n['title']} schemas={n['schema']} "
        f"roads={n['road']} · release {ref} parsed={count(release, 'parsed')} "
        f"unparsed={count(release, 'unparsed', 3)} · yours parsed={count(yours, 'parsed')} "
        f"unparsed={count(yours, 'unparsed', 3)}"
    )
    if count(release, "parsed") == 0:
        raise refuse(
            f"!! the release at {ref} carries not one app with migrations — this reader is",
            "   looking at something that is not a release of this template. Could-not-look.",
        )
    if pairs == 0:
        out(f"collisions: none against {ref}")
    return n


def collision_verdict(pairs: int, roads: int, ref: str, rc: int) -> int:
    """The collision census outranks the divergence verdict: any pair is exit 2."""
    if pairs <= 0:
        return rc
    out(f"== REFUSED · {pairs} name collision(s) against {ref} — exit 2 whatever the")
    out("   divergence verdict above says: the release's migrations would die on")
    out("   them one step after the merge. Rename YOURS, then run this again.")
    if roads > 0:
        out("   A road pair is no rename: the merged tree fails house rule 84 at your")
        out("   first gate, and the remedy under each pair names the two ways out.")
    return 2


# --- the divergence half -------------------------------------------------------------------------


def seen_paths(root: Path) -> list[str]:
    """Tracked plus untracked-and-not-ignored: the set the gate measures."""
    tracked = git(root, "ls-files")
    others = git(root, "ls-files", "--others", "--exclude-standard")
    if tracked.returncode != 0 or others.returncode != 0:
        raise refuse("!! git could not list this tree — could-not-look, never an empty census")
    return sorted({p for p in (tracked.stdout + others.stdout).splitlines() if p})


def named_divergences(root: Path) -> set[str]:
    """Every path a `divergence:` line in the product's architecture.md names."""
    arch = root / "docs/product/architecture.md"
    if not arch.is_file():
        return set()
    named: set[str] = set()
    for line in arch.read_text(errors="replace").splitlines():
        hit = re.match(r".*divergence:\s*`?([^`\s]*)`?.*", line)
        if hit:
            named.add(hit.group(1))
    return named


def census_line(owned: int, base: str, diverged: int = 0, unnamed: int = 0) -> str:
    """The census's one machine line."""
    return (
        f"census: owned={owned} drawers={len(DRAWER_GLOBS)} base={base} "
        f"diverged={diverged} unnamed={unnamed}"
    )


@dataclass
class Args:
    """The census's flags."""

    if_declared: bool = False
    against: str = ""
    roads_only: bool = False
    sdk: bool = False
    fix: bool = False


def parse(argv: Sequence[str]) -> Args:
    """The shell's flag loop; an unknown argument or a bare `--against` is exit 2."""
    args = Args()
    rest = list(argv)
    while rest:
        arg = rest.pop(0)
        if arg == "--roads":
            args.roads_only = True
        elif arg == "--if-declared":
            args.if_declared = True
        elif arg in ("--sdk", "--fix"):
            setattr(args, arg[2:], True)
        elif arg == "--against":
            if not rest or not rest[0]:
                raise refuse(
                    "!! --against needs the release ref you are about to fold (a tag, after",
                    "   `git fetch template --tags`) — a collision census against nothing is"
                    " not one",
                )
            args.against = rest.pop(0)
        else:
            raise refuse(*(line.format(arg=arg) for line in USAGE_UNKNOWN))
    if (args.sdk or args.fix) and not (args.sdk and args.against) or args.sdk and args.roads_only:
        raise refuse(
            "!! --sdk reads the surfaces from your base to --against <release ref> and prints",
            "   each import the fold breaks; --fix (exact renames) rides --sdk; --roads is apart",
        )
    if args.roads_only and (args.against or args.if_declared):
        raise refuse(
            "!! --roads prints this checkout's road markers and nothing else; it takes",
            "   no --against and no --if-declared — run those as their own census",
        )
    return args


def print_rows(rows: Iterable[tuple[str, ...]]) -> None:
    """Rows tab-joined, one per line."""
    for row in rows:
        out("\t".join(row))


def divergences(root: Path, base: Base, owned_count: int, classify: Callable[[str], str]) -> int:
    """Diff the tree against the base; each template-owned path that differs, named or not."""
    out(f"   base       {base.ref}  (from {base.source})")
    if not resolves(root, base.ref):
        err(f"!! the declared base does not resolve to a commit in this checkout: {base.ref}")
        err(f"   (declared by {base.source})")
        err("   A tag you have not fetched is not a base. Fetch it and re-run:")
        err("     git fetch template --tags")
        err(f"   or write the tag's commit in the drawer, {TAG_COMMIT_WHERE}:")
        err(f"     git rev-parse '{base.ref}^{{commit}}' > {TEMPLATE_BASE_DRAWER}")
        err("   This census writes nothing, so it will not fetch for you.")
        out(census_line(owned_count, "unresolved"))
        return 2
    named = named_divergences(root)
    out("")
    out("-- divergences: a template-owned path whose content is not the base's")
    diff = git(root, "diff", "--numstat", "--no-renames", base.ref)
    if diff.returncode != 0:
        err(
            f"!! git diff against {base.ref} failed (exit {diff.returncode})"
            " — could-not-look, never a"
        )
        err("   clean census.")
        out(census_line(owned_count, base.ref))
        return 2
    found: list[tuple[str, str, str]] = []
    deleted = 0
    for line in diff.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3 or not parts[2]:
            continue
        kind = classify(parts[2])
        if kind == "worked-example" and not (root / parts[2]).exists():
            deleted += 1
        elif kind in ("template", "worked-example"):
            found.append((parts[0], parts[1], parts[2]))
    others = git(root, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    found += [
        ("new", "-", p) for p in others if p and classify(p) in ("template", "worked-example")
    ]
    if deleted:
        out(
            f"   deleted worked example: {deleted} path(s) — not a divergence; a product"
            " may delete the worked example, and an edit to what it keeps diverges"
        )
    unnamed = 0
    for added, removed, path in found:
        last = git(root, "log", "-1", "--format=%h %s", "--", path).stdout.strip()
        last = last or "(no commit yet — untracked in this checkout)"
        delta = "a file the base does not have" if added == "new" else f"+{added}-{removed}"
        if path in named:
            out(f"   named-divergence: {path} · {delta} · {last}")
        else:
            unnamed += 1
            out(f"   divergence: {path} · {delta} · {last}")
    if not found:
        out("   none")
    out(census_line(owned_count, base.ref, len(found), unnamed))
    if unnamed:
        out("")
        out(
            f"== {unnamed} UNNAMED DIVERGENCE(S) · {len(found)} diverged of {owned_count}"
            " template-owned paths"
        )
        out("   A template-owned file carries no product edits. Either move the change")
        out("   into the drawer beside it — a local/ sibling the template's own reader")
        out("   discovers and never ships — or record it in docs/product/architecture.md")
        out("   as the deliberate divergence it is, one line each:")
        for _added, _removed, path in found:
            if path not in named:
                out(f"     divergence: {path} — <why this product needs it>")
        return 1
    out("")
    if found:
        out(f"== CLEAN · {len(found)} divergence(s), every one of them named in architecture.md")
    else:
        out(f"== CLEAN · no template-owned file in this tree differs from {base.ref}")
    return 0


def census(root: Path, args: Args, environ: dict[str, str] | os._Environ[str]) -> int:
    """The whole census over `root`: header, collisions, base, owned set, divergences."""
    if git(root, "rev-parse", "--git-dir").returncode != 0:
        raise refuse("!! not a git checkout — this census reads git and nothing else")
    platform = platform_apps(root)
    if args.sdk:
        base = declare_base(root, environ)
        if base is None:
            raise refuse("!! --sdk needs the declared base — the release this product stands on")
        from quality.sdk.upgrade import sdk_step

        return sdk_step(root, base.ref, args.against, fix=args.fix)
    out(f"== divergence census · {root}")
    if args.roads_only:
        try:
            print_rows(census_roads_over(root, TREE, "all", platform))
        except Unreadable:
            raise refuse(
                "!! the road census could not read this checkout — could-not-look"
            ) from None
        return 0
    counts = dict.fromkeys(COUNTERS, 0)
    if not args.against:
        out("collisions: not measured (no --against <release ref>)")
    else:
        counts = collisions(root, args.against, platform)
    try:
        rc = _divergence_half(root, args, environ, platform)
    except Refused:
        collision_verdict(sum(counts.values()), counts["road"], args.against, 2)
        raise
    return collision_verdict(sum(counts.values()), counts["road"], args.against, rc)


def _divergence_half(
    root: Path, args: Args, environ: dict[str, str] | os._Environ[str], platform: Sequence[str]
) -> int:
    """The base, the owned set and the comparison; the divergence verdict."""
    base = declare_base(root, environ)
    if base is None:
        if args.if_declared:
            out("   base       none declared — SKIPPED")
            out("   A tree with no declared base is not a tree with no divergences. This")
            out("   is the template's own shape: it has no template. A product declares")
            out(f"   its base in {TEMPLATE_BASE_DRAWER}, or by adding a git remote")
            out("   named 'template', or by typing DJB_TEMPLATE_BASE.")
        else:
            err("!! NO BASE IS DECLARED, so there is nothing to compare this tree against.")
            err("   Declare one of the three, in this order of precedence:")
            err(f"     DJB_TEMPLATE_BASE=<ref> {DOOR}")
            err(f"     echo <commit-or-tag> > {TEMPLATE_BASE_DRAWER}")
            err("       (a product's CI resolves a commit and not the template's tag, so write")
            err(f"       the tag's commit, {TAG_COMMIT_WHERE}:")
            err(f"       git rev-parse '<tag>^{{commit}}' > {TEMPLATE_BASE_DRAWER})")
            err("     git remote add template <url> && git fetch template --tags")
            err("       (then the tag v<TEMPLATE_VERSION> is the base)")
            err("   Could-not-look, not a clean tree.")
    seen = seen_paths(root)
    if not seen:
        raise refuse(
            "!! the census saw no paths at all — this reader is looking at the wrong",
            "   tree, and that is a could-not-look, never an empty owned set.",
        )
    rules = rules_for(seen)

    def classify(path: str) -> str:
        if path not in rules:
            rules.update(rules_for([path]))
        return ownership_of(path, rules.get(path, []), platform)

    owned = [p for p in seen if classify(p) == "template"]
    out(f"   owned      {len(owned)} template-owned paths (derived: the publication bucket")
    out("              rules in quality/djb/rituals/divergence.py, less the drawers and the")
    out("              shared set; docs/product/build-contract.md § Ownership is the table)")
    out(
        f"   drawers    {len(DRAWER_GLOBS)} reserved paths are the product's wherever they appear"
        f" ({' '.join(DRAWER_GLOBS)})"
    )
    worked = sum(1 for p in seen if classify(p) == "worked-example")
    out(
        f"   worked     {worked} worked-example paths: deleting one is not a divergence, editing is"
    )
    if not owned:
        err("!! not one template-owned path in this tree. The classifier is reading")
        err("   something that is not a checkout of this template — could-not-look,")
        err("   never a clean census.")
        out(census_line(0, "none"))
        return 2
    if base is None:
        out(census_line(len(owned), "none"))
        if args.if_declared:
            out(
                f"== SKIPPED · no base declared · {len(owned)} template-owned paths were classified"
            )
            return 0
        return 2
    return divergences(root, base, len(owned), classify)


def codeowners_roots(paths: Iterable[str], platform: Sequence[str]) -> tuple[list[str], list[str]]:
    """(owned roots, the product's paths inside them): shallowest all-template-or-reserved dirs."""
    rules = rules_for({*paths, CODEOWNERS_TEMPLATE})
    kinds = {p: ownership_of(p, ids, platform) for p, ids in rules.items()}
    drawer = {p for p in kinds if is_drawer(p)}
    mixed: set[str] = set()
    for path, kind in kinds.items():
        if kind == "product" and path not in drawer:
            parts = path.split("/")
            mixed.update("/".join(parts[:i]) for i in range(1, len(parts)))
    owned: set[str] = set()
    for path, kind in kinds.items():
        if kind not in ("template", "worked-example"):
            continue
        parts = path.split("/")
        dirs = ("/".join(parts[:i]) for i in range(1, len(parts)))
        owned.add(next((d + "/" for d in dirs if d not in mixed), path))
    unowned = sorted(
        p
        for p, kind in kinds.items()
        if kind not in ("template", "worked-example")
        and any(p.startswith(r) for r in owned if r.endswith("/"))
        and p not in drawer
    )
    return sorted(owned), unowned


def codeowners_text(root: Path) -> str:
    """The CODEOWNERS a product adopts: `@OWNER` on every template-owned root, the rest unowned."""
    tracked = git(root, "ls-files")
    if tracked.returncode != 0:
        raise refuse("!! git could not list this tree — could-not-look, never an empty file")
    owned, unowned = codeowners_roots(tracked.stdout.splitlines(), platform_apps(root))
    lines = [
        "# Generated by `python -m quality.djb.rituals.divergence --codeowners` (rule 60's",
        "# classifier). A product copies it to .github/CODEOWNERS and names its owner for @OWNER.",
        *(f"/{r} @OWNER" for r in owned),
        "# The product's inside those roots: the shared set and the drawers.",
        *(f"/{p}" for p in unowned),
        *(g if g.startswith("*") else f"/{g}" for g in DRAWER_GLOBS),
    ]
    return "\n".join(lines) + "\n"


def write_codeowners(argv: Sequence[str], root: Path) -> int:
    """`--codeowners [<path>]`: write the file (the template's own by default) and say where."""
    if len(argv) > 1:
        err("!! --codeowners takes at most one path to write")
        return 2
    target = (root / (argv[0] if argv else CODEOWNERS_TEMPLATE)).resolve()
    text = codeowners_text(root)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    except OSError as exc:
        err(f"!! --codeowners could not write {target} ({exc.strerror}) — could-not-look")
        return 2
    shown = target.relative_to(root.resolve()) if target.is_relative_to(root.resolve()) else target
    out(f"codeowners: wrote {shown}")
    return 0


def died_part_way(cause: str) -> int:
    """The exit guard's sentence for a run that ended outside every end this census authors."""
    err("")
    for line in DIED:
        err(line.format(cause=cause))
    return 2


def roads_over(argv: Sequence[str]) -> int:
    """`--roads-over <reader> <all|yours> <root>`: the shell census's roads class until its shim."""
    if len(argv) != 3 or argv[1] not in ("all", "yours"):
        err("!! --roads-over takes <reader> <all|yours> <root>")
        return 2
    reader, which, where = argv
    root = Path(where).resolve()
    try:
        print_rows(census_roads_over(root, reader, which, platform_apps(root)))
    except Unreadable as cannot:
        err(f"!! the road census could not read {cannot} — could-not-look")
        return 2
    return 0


def main(argv: Sequence[str] | None = None, root: Path = ROOT) -> int:
    """The census: exit 0 clean or every divergence named, 1 one unnamed, 2 could not look."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--roads-over"]:
        return roads_over(argv[1:])
    if argv[:1] == ["--codeowners"]:
        return write_codeowners(argv[1:], root.resolve())
    try:
        refuse_if_piped()
        root = root.resolve()
        args = parse(argv)
        return census(root, args, os.environ)
    except Refused:
        return 2
    except CouldNotLook as cannot:
        err(f"!! divergence_census: COULD NOT LOOK: {cannot}")
        return 2
    except Exception as exc:  # noqa: BLE001 — the exit guard: a death outside a refusal is exit 2
        return died_part_way(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
