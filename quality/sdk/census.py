"""The SDK census: every platform name a product could reach, and the bucket `pilecap` puts it."""

# does-not-cover: a capability that lives only inside a door (a route with no service or selector).
# does-not-cover: a name bound by code (`globals()`, a loop, a star import) — literals only.
# does-not-cover: whether a PUBLIC name is a good one, or a reason true — membership and length.
# does-not-cover: an export reaching past the population — counted and printed, never judged.

from __future__ import annotations

import argparse
import ast
import fnmatch
import os
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook, exit_could_not_look
from quality.djb.rituals.divergence import platform_apps
from quality.reason_floor import MIN_REASON
from quality.sdk.reexports import reexports

#: The checkout this census reads by default: the one it lives in.
ROOT = Path(__file__).resolve().parents[2]
#: The worked example's labels: platform in `partition.yaml`, product-shaped, never the population.
WORKED_EXAMPLE = "example*"
#: Each platform app's population files: (glob under the app, what is counted, the column).
APP_FILES: tuple[tuple[str, str, str], ...] = (
    ("services.py", "def", "services"),
    ("services/*.py", "def", "services"),
    ("selectors.py", "def", "selectors"),
    ("types.py", "class", "types"),
    ("events.py", "event", "events"),
)
#: `apps/core`'s public modules: every public name each one defines joins the population.
CORE_MODULES = tuple(
    f"apps.core.{m}"
    for m in (
        "models actor service authz exceptions schemas verbs roads lifecycle log concurrency"
        " context determinism bulk idempotency policies money time headers flags schedules"
        " surfaces roles mcp admin requests audit asyncdb middleware bridge blockers fields"
        " api.acting api.docs api.frozen_families api.mount api.pagination"
        " api.query api.routes api.scopes"
    ).split()
)
#: The discovered-file protocols that live outside the files above, read whole.
PROTOCOL_MODULES = ("apps.connections.providers", "apps.usage.meters")
#: The facade package, its keep-back table, and its testing half.
FACADE = "pilecap"
INTERNAL_FILE = "pilecap/_internal.py"
TESTING = "testing"
#: Where a testing-only helper (a `pilecap.testing` re-export outside the population) is read.
TESTING_PAGE = "docs/sdk/pilecap.testing.md"
COLUMNS = ("services", "selectors", "types", "events", "modules")


@dataclass(frozen=True)
class Name:
    """One population member: its dotted key, its app and the column it is counted in."""

    key: str
    app: str
    column: str


@dataclass
class Partition:
    """The three buckets as the facade declares them, keyed by each name's defining module."""

    public: dict[str, str] = field(default_factory=dict)
    testing: dict[str, str] = field(default_factory=dict)
    internal: dict[str, str] = field(default_factory=dict)
    internal_modules: dict[str, str] = field(default_factory=dict)
    classes: dict[str, str] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)


# --- reading modules ---------------------------------------------------------------------------


def module_file(root: Path, module: str) -> Path | None:
    """The file a dotted module lives in under `root`, or None."""
    base = root.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


def parse(path: Path) -> ast.Module:
    """The module's tree; an unreadable or unparsable file is could-not-look."""
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        raise CouldNotLook(f"sdk census: cannot read {path}: {exc}") from exc


def _targets(node: ast.stmt) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    if isinstance(node, ast.TypeAlias):
        return [node.name.id]
    return []


def declared_all(tree: ast.Module) -> list[str] | None:
    """The module's literal `__all__`, or None when it declares none."""
    for node in tree.body:
        if "__all__" in _targets(node):
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            if isinstance(value, (ast.List, ast.Tuple)):
                return [str(e.value) for e in value.elts if isinstance(e, ast.Constant)]
    return None


def defined(tree: ast.Module, kind: str) -> list[str]:
    """The public names a module defines at top level, of one kind (def, class, event, any)."""
    found: list[str] = []
    for node in tree.body:
        names: list[str] = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and kind in ("def", "any"):
            names = [node.name]
        elif isinstance(node, ast.ClassDef) and kind in ("class", "any"):
            names = [node.name]
        elif kind == "any":
            names = _targets(node)
        elif kind == "event" and isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                names = _targets(node)
        for name in names:
            if not name.startswith("_") and name not in found:
                found.append(name)
    if kind == "any":
        listed = declared_all(tree)
        if listed is not None:
            found = [n for n in found if n in listed]
    return found


def bindings(tree: ast.Module, module: str) -> dict[str, tuple[str, str]]:
    """Each name the module re-exports: `b` → (M, a), relative imports made absolute."""
    return reexports(tree, module)


def resolve(root: Path, module: str, name: str, seen: frozenset[str] = frozenset()) -> str | None:
    """The key `module.name` reaches through re-exports: the module that defines it, or None."""
    here = f"{module}.{name}"
    path = module_file(root, module)
    if path is None or here in seen:
        return None
    tree = parse(path)
    if name in _defined_any(tree):
        return here
    if module_file(root, here) is not None:
        return here
    bound = bindings(tree, module).get(name)
    if bound is None:
        return None
    source, original = bound
    if not source.startswith(("apps.", "pilecap")):
        return f"{source}.{original}"
    return resolve(root, source, original, seen | {here})


def _defined_any(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        names.update(_targets(node))
    return names


# --- the population ----------------------------------------------------------------------------


def census_apps(root: Path) -> list[str]:
    """`partition.yaml`'s platform apps, the worked example out; none is could-not-look."""
    named = platform_apps(root)
    if not named:
        raise CouldNotLook(f"sdk census: no platform_apps in {root / 'quality/partition.yaml'}")
    return [a for a in named if not fnmatch.fnmatchcase(a, WORKED_EXAMPLE)]


def _module_of(root: Path, path: Path) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def population(root: Path) -> list[Name]:
    """Every population member, in app order then file order."""
    out: list[Name] = []
    seen: set[str] = set()

    def add(module: str, names: Iterable[str], app: str, column: str) -> None:
        for name in names:
            key = f"{module}.{name}"
            if key not in seen:
                seen.add(key)
                out.append(Name(key, app, column))

    for app in census_apps(root):
        home = root / "apps" / app
        if not home.is_dir():
            raise CouldNotLook(f"sdk census: platform app {app!r} has no directory under apps/")
        for pattern, kind, column in APP_FILES:
            for path in sorted(home.glob(pattern)):
                add(_module_of(root, path), defined(parse(path), kind), app, column)
        for module in (*CORE_MODULES, *PROTOCOL_MODULES):
            if module.split(".")[1] != app:
                continue
            source = module_file(root, module)
            if source is None:
                raise CouldNotLook(f"sdk census: {module} is declared and has no file")
            add(module, defined(parse(source), "any"), app, "modules")
    return out


def core_modules(root: Path) -> list[str]:
    """Every `apps/core` module outside the per-app files: each is declared surface or internal."""
    home = root / "apps" / "core"
    found: list[str] = []
    for path in sorted([*home.glob("*.py"), *home.glob("api/*.py")]):
        module = _module_of(root, path)
        if module.endswith((".services", ".selectors", ".types", ".events")):
            continue
        if defined(parse(path), "any"):
            found.append(module)
    return found


# --- the partition -----------------------------------------------------------------------------


def _literal_dict(tree: ast.Module, name: str, path: Path) -> dict[str, str]:
    for node in tree.body:
        if name in _targets(node):
            value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
            try:
                data = ast.literal_eval(value) if value is not None else None
            except ValueError as exc:
                raise CouldNotLook(f"sdk census: {path}::{name} is not a literal: {exc}") from exc
            if not isinstance(data, dict):
                raise CouldNotLook(f"sdk census: {path}::{name} is not a dict")
            return {str(k): str(v) for k, v in data.items()}
    raise CouldNotLook(f"sdk census: {path} declares no {name}")


def facade_modules(root: Path) -> Iterator[tuple[str, Path, bool]]:
    """Each facade module: (dotted name, file, is the testing half); the keep-back table out."""
    home = root / FACADE
    for path in sorted(home.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if rel == INTERNAL_FILE or "__pycache__" in rel:
            continue
        module = _module_of(root, path)
        yield module, path, module.split(".")[1:2] == [TESTING]


def exports(root: Path, module: str, path: Path) -> list[tuple[str, str | None]]:
    """Each `__all__` name of a facade module and the key it resolves to (None: unresolved)."""
    tree = parse(path)
    listed = declared_all(tree)
    if listed is None:
        raise CouldNotLook(f"sdk census: {module} declares no __all__")
    bound = bindings(tree, module)
    own = _defined_any(tree)
    out: list[tuple[str, str | None]] = []
    for name in listed:
        if name in bound:
            source, original = bound[name]
            out.append((name, resolve(root, source, original)))
        elif name not in own:
            out.append((name, None))
    return out


def partition(root: Path) -> Partition:
    """The facade's three buckets, read off its files without importing anything."""
    if not (root / FACADE).is_dir():
        raise CouldNotLook(f"sdk census: no {FACADE}/ package under {root}")
    part = Partition()
    for module, path, testing in facade_modules(root):
        bucket = part.testing if testing else part.public
        for name, key in exports(root, module, path):
            if key is None:
                part.unresolved.append(f"{module}.{name}")
            else:
                bucket.setdefault(key, f"{module}.{name}")
    internal_path = root / INTERNAL_FILE
    tree = parse(internal_path)
    part.internal = _literal_dict(tree, "INTERNAL", internal_path)
    part.internal_modules = _literal_dict(tree, "INTERNAL_MODULES", internal_path)
    part.classes = _literal_dict(tree, "REASON_CLASSES", internal_path)
    return part


def reason_class(reason: str, classes: Mapping[str, str]) -> tuple[str | None, str]:
    """(class, the reason's own words) when `reason` opens `<class>: `, else (None, reason)."""
    head, sep, rest = reason.partition(": ")
    if sep and head in classes:
        return head, rest.strip()
    return None, reason.strip()


# --- the verdict -------------------------------------------------------------------------------


@dataclass
class Verdict:
    """What the census found: the population, the buckets, and every way the two disagree."""

    names: list[Name]
    part: Partition
    findings: list[str]

    def bucket_of(self, key: str) -> str:
        """`public`, `testing`, `internal` or `none`."""
        for bucket in ("public", "testing", "internal"):
            if key in getattr(self.part, bucket):
                return bucket
        return "none"


def judge(root: Path) -> Verdict:
    """Read the population and the partition; every disagreement is one finding line."""
    names = population(root)
    part = partition(root)
    keys = {n.key for n in names}
    findings: list[str] = []
    for n in names:
        held = [b for b in ("public", "testing", "internal") if n.key in getattr(part, b)]
        if not held:
            findings.append(
                f"unpartitioned: {n.key} ({n.column}) — export it from pilecap, from"
                " pilecap.testing, or keep it back in pilecap/_internal.py::INTERNAL with a reason"
            )
        elif len(held) > 1:
            findings.append(f"two buckets: {n.key} is {' and '.join(held)} — one bucket per name")
    for key in sorted(set(part.internal) - keys):
        findings.append(f"stale INTERNAL: {key} is not in the population — remove its line")
    for key, reason in sorted({**part.internal, **part.internal_modules}.items()):
        klass, words = reason_class(reason, part.classes)
        if klass is None:
            findings.append(
                f"reason without a class: {key}: {reason!r} — open it with one of"
                f" {', '.join(sorted(part.classes))} and a colon"
            )
        elif len(words) < MIN_REASON:
            findings.append(
                f"reason under the floor: {key}: {reason!r} — {len(words)} characters"
                f" after the class, the floor is {MIN_REASON}"
            )
    declared = set(CORE_MODULES) | set(part.internal_modules)
    for module in core_modules(root):
        if module not in declared:
            findings.append(
                f"undeclared module: {module} — name it in the census's CORE_MODULES or"
                " keep it back in pilecap/_internal.py::INTERNAL_MODULES with a reason"
            )
    for module in sorted(set(part.internal_modules)):
        if module in CORE_MODULES or module_file(root, module) is None:
            findings.append(f"stale INTERNAL_MODULES: {module} — surface or absent; remove it")
    findings += [f"unresolved export: {e} — its import names nothing" for e in part.unresolved]
    page = root / TESTING_PAGE
    if not page.is_file():
        raise CouldNotLook(f"sdk census: no {TESTING_PAGE} to read the testing-only names on")
    headings = set(page.read_text(encoding="utf-8").splitlines())
    for key, facade in sorted(testing_only(part, keys).items()):
        if f"### `{facade}`" not in headings:
            findings.append(
                f"testing-only off its page: {facade} ({key}) — regenerate with --reference"
            )
    return Verdict(names, part, findings)


def testing_only(part: Partition, keys: set[str]) -> dict[str, str]:
    """Each `pilecap.testing` re-export outside the population — declared by its `__all__` name."""
    return {key: facade for key, facade in part.testing.items() if key not in keys}


def render(v: Verdict, *, show_names: bool = False) -> list[str]:
    """The printed census: by app with counts per column and per bucket, then the verdict."""
    apps = list(dict.fromkeys(n.app for n in v.names))
    rows: dict[str, Counter[str]] = {a: Counter() for a in apps}
    for n in v.names:
        rows[n.app][n.column] += 1
        rows[n.app][v.bucket_of(n.key)] += 1
    head = ("services", "selectors", "types", "events", "modules", "public", "testing", "internal")
    out = [
        f"sdk census: {len(apps)} platform apps from quality/partition.yaml"
        f" (the worked example, {WORKED_EXAMPLE}, is not the population)",
        "  " + f"{'app':<14}" + "".join(f"{h:>10}" for h in head),
    ]
    total: Counter[str] = Counter()
    for app in apps:
        total.update(rows[app])
        out.append("  " + f"{app:<14}" + "".join(f"{rows[app][h]:>10}" for h in head))
    out.append("  " + f"{'total':<14}" + "".join(f"{total[h]:>10}" for h in head))
    keys = {n.key for n in v.names}
    beyond_p = sorted(set(v.part.public) - keys)
    declared = testing_only(v.part, keys)
    beyond_t = sorted(set(v.part.testing) - keys - set(declared))
    out.append(
        f"  beyond the population: {len(beyond_p)} PUBLIC and {len(beyond_t)} TESTING"
        " re-exports reach modules the census does not read"
    )
    out.append(
        f"  testing-only: {len(declared)} TESTING re-exports reach helpers outside the"
        f" population, each declared by name in pilecap.testing and read on {TESTING_PAGE}"
    )
    by_class = Counter(
        reason_class(r, v.part.classes)[0] or "none" for r in v.part.internal.values()
    )
    out.append(
        "  INTERNAL reasons by class: "
        + " · ".join(f"{k}={by_class[k]}" for k in sorted(by_class))
        + f" · INTERNAL_MODULES={len(v.part.internal_modules)}"
    )
    if show_names:
        out += [f"  {v.bucket_of(n.key):<9}{n.column:<10}{n.key}" for n in v.names]
    out += [f"  !! {f}" for f in v.findings]
    if v.findings:
        out.append(f"census: {len(v.findings)} finding(s) — the partition is not exact")
    else:
        out.append(
            f"census: exact — {len(v.names)} names, PUBLIC {total['public']}"
            f" · TESTING {total['testing']} · INTERNAL {total['internal']}"
        )
    return out


# --- the goldens, read as a negative ------------------------------------------------------------


def golden_imports(root: Path) -> list[tuple[str, int, str, bool]]:
    """Each platform name the example imports, direct or via `pilecap`: (file, line, key, test)."""
    out: list[tuple[str, int, str, bool]] = []
    for path in sorted(root.glob("apps/example*/**/*.py")):
        rel = path.relative_to(root).as_posix()
        if "/migrations/" in rel:
            continue
        is_test = "/tests/" in rel or path.name.startswith("test_") or path.name == "conftest.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                source = node.module
                platform = source.startswith("apps.") and not fnmatch.fnmatchcase(
                    source.split(".")[1], WORKED_EXAMPLE
                )
                if not platform and source.split(".")[0] != FACADE:
                    continue
                for alias in node.names:
                    if module_file(root, f"{source}.{alias.name}") is not None:
                        modules[alias.asname or alias.name] = f"{source}.{alias.name}"
                        continue
                    key = resolve(root, source, alias.name) or f"{source}.{alias.name}"
                    out.append((rel, node.lineno, key, is_test))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in modules
            ):
                module = modules[node.value.id]
                key = resolve(root, module, node.attr) or f"{module}.{node.attr}"
                out.append((rel, node.lineno, key, is_test))
    return out


def golden_gaps(root: Path, part: Partition) -> list[str]:
    """Each golden import the facade lacks: production ⊆ PUBLIC, tests ⊆ PUBLIC ∪ TESTING."""
    gaps: list[str] = []
    for rel, line, key, is_test in golden_imports(root):
        if key in part.public or (is_test and key in part.testing):
            continue
        where = "PUBLIC or TESTING" if is_test else "PUBLIC"
        gaps.append(f"{rel}:{line} imports {key} — not in {where}")
    return gaps


# --- every re-export, imported -----------------------------------------------------------------


def resolve_imports(root: Path) -> tuple[list[str], str]:
    """Import each facade module under Django, getattr each `__all__` name: (failures, version)."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    sys.path.insert(0, str(root))
    import importlib

    import django

    django.setup()
    failures: list[str] = []
    for module, _path, _testing in facade_modules(root):
        try:
            loaded = importlib.import_module(module)
        except Exception as exc:  # noqa: BLE001 — every import failure is the finding, named
            failures.append(f"{module}: import failed: {type(exc).__name__}: {exc}")
            continue
        for name in getattr(loaded, "__all__", ()):
            if not hasattr(loaded, name):
                failures.append(f"{module}.{name}: does not resolve")
    from django.conf import settings

    import pilecap

    version = str(pilecap.__version__)
    if version != settings.TEMPLATE_VERSION:
        failures.append(f"pilecap.__version__ {version!r} != {settings.TEMPLATE_VERSION!r}")
    return failures, version


# --- the door ----------------------------------------------------------------------------------


def main(argv: Sequence[str], root: Path | None = None) -> int:
    """`--census [--names]` exits 0 only on the exact partition; `--resolve` imports each export."""
    parser = argparse.ArgumentParser(prog="python -m quality.sdk")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--census", action="store_true", help="the partition, by app; exit 0 exact")
    mode.add_argument("--resolve", action="store_true", help="import every re-export (Django)")
    parser.add_argument("--names", action="store_true", help="every name under its bucket")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(list(argv))
    home = (args.root or root or ROOT).resolve()
    try:
        if args.resolve:
            failures, version = resolve_imports(home)
            for line in failures:
                print(f"  !! {line}")
            if not failures:
                print(f"version: pilecap.__version__ = {version} = TEMPLATE_VERSION")
            modules = sum(1 for _ in facade_modules(home))
            print(f"resolve: {modules} facade modules, {len(failures)} failure(s)")
            return 1 if failures else 0
        verdict = judge(home)
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))
    for line in render(verdict, show_names=args.names):
        print(line)
    return 1 if verdict.findings else 0
