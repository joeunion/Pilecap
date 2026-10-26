"""The `--loop` scope: the changed files, their classes, the closure, the always-on set, the key."""

# does-not-cover: a path with a space in it — the shell word-splits the changed set; so does this.
# does-not-cover: the Mac shell's locale sort — this module sorts by bytes, as the box's shell does.

from __future__ import annotations

import fnmatch
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from quality.could_not_look import CouldNotLook, exit_could_not_look, tool_said

#: The checkout this module runs from: the closure's reader and the decider are its.
HOME = Path(__file__).resolve().parents[2]
#: The fork point the active rung is derived against when the caller names none.
BASE_REF = "refs/heads/main"
#: The test-impact map a `--loop` may narrow by (`scripts/test_impact.py` writes it).
MAP_PATH = "scripts/test_impact.json"
#: How many first-parent commits a map's tree is looked for among.
MAP_SCAN = 800
#: The harness population whose always-on block keys the scope; the files are git's answer.
HARNESS = ("apps/conftest.py", "apps/testing/*.py")
#: The census declaration's marker, depth and population clause (`apps/testing/tier.py`'s).
CENSUS_MARKER = "# census: cross-app"
CENSUS_LINES = 40
CENSUS_POPULATION = "population="
#: The line a census module names the files whose change seeds it.
SEEDED_BY = "CENSUS_SEEDED_BY"
#: The comment line a module declares a quoted path it never reads (the decider's).
NONREAD_NAME = "GATE_DOCS_ONLY_NONREAD"

_BEGIN = re.compile(r"^# >>> (\S(?:.*\S)?) >>>$")
_SEEDED = re.compile(rf"^{SEEDED_BY}[^=]*=\s*\((.*)\)\s*$")
_SHARED = (
    ("apps/conftest_local.py", True),
    ("apps/testing/*.py", True),
    ("apps/*/*conftest.py", False),
    ("conftest.py", True),
    ("*/conftest.py", True),
    ("apps/test_*.py", True),
    ("scripts/tests/*", True),
    ("scripts/check.sh", True),
    ("scripts/secrets_scan.sh", True),
    ("scripts/gate_ledger.sh", True),
)
_CLASSES = (
    (("apps/__init__.py", "manage.py"), "apps-boundary"),
    (("apps/*/tests/*",), "app-tests"),
    (("apps/*/*",), "app"),
    (("config/*",), "config"),
    (("pilecap/*",), "sdk"),
    (("templates/*",), "templates"),
    (("frontend/*",), "frontend"),
    (("quality/*",), "quality"),
    (("pyproject.toml", "uv.lock"), "declared-blind-spot"),
)
_INERT = (
    ".claude/*",
    ".github/*",
    ".devcontainer/*",
    "deploy/*",
    "compose/*",
    "perf/*",
    "vendor/*",
    "scripts/*",
    "templates",
    "frontend",
    "Dockerfile",
    ".dockerignore",
    "compose.yaml",
    ".editorconfig",
    ".gitignore",
    ".gitattributes",
    ".python-version",
    ".secrets.baseline",
    ".env.example",
    "TEMPLATE_VERSION",
    "*.md",
)
_SHARED_SHAPES = ("shared-test-infra", "apps-boundary", "config", "templates", "sdk")


class Unclassified(CouldNotLook):
    """A changed path the fan-out table has no row for: exit 2, never a guess."""


def _git(root: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *argv], capture_output=True, text=True, errors="surrogateescape"
    )


def _out(root: Path, *argv: str) -> str | None:
    done = _git(root, *argv)
    return done.stdout.strip() if done.returncode == 0 else None


def sha256(data: str) -> str:
    """The 64-hex digest of `data`'s UTF-8 bytes (`sha256_of`)."""
    return hashlib.sha256(data.encode("utf-8", "surrogateescape")).hexdigest()


def _sorted(words: Iterable[str]) -> list[str]:
    return sorted(set(words))


def _add(into: list[str], word: str) -> None:
    if word not in into:
        into.append(word)


def _match(path: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(path, pattern)


# --- the changed files -------------------------------------------------------


@dataclass
class Changed:
    """What the active rung changed: the paths, the sentence saying how, and the fork point."""

    paths: list[str]
    basis: str
    base: str = ""
    carried: str = ""


def changed_files(root: Path, base_ref: str | None = None, carried: str | None = None) -> Changed:
    """The rung's changed files since its fork point, plus the uncommitted (`secrets_scan`)."""
    if _git(root, "rev-parse", "--git-dir").returncode != 0:
        raise CouldNotLook(
            "the secret scan could not read a git directory here — the changed-file set is"
            " derived from git and from nothing else."
        )
    raw: list[str] = []
    head = _out(root, "rev-parse", "-q", "--verify", "HEAD") or ""
    if not head:
        raw += _z(_git(root, "ls-files", "-z").stdout)
        basis = (
            "an unborn HEAD — nothing is committed yet, so every staged file is new and all"
            " of them were scanned"
        )
        return Changed(_finish(root, raw), basis)
    ref = base_ref or BASE_REF
    ref_name = base_ref or "main"
    base = ""
    if _git(root, "rev-parse", "-q", "--verify", ref).returncode == 0:
        base = _out(root, "merge-base", "HEAD", ref) or ""
    branch = _out(root, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    taken = ""
    if carried and (not base or base == head):
        sha = _out(root, "rev-parse", "-q", "--verify", f"{carried}^{{commit}}") or ""
        if sha and sha != head:
            base, taken = sha, sha
    if not base:
        basis = (
            f"no local {ref} to fork from — ONLY this checkout's uncommitted changes were"
            " scanned, and nothing committed was"
        )
    elif base == head:
        if branch == "main":
            basis = (
                "on main itself (the merge-base IS this HEAD) — ONLY this checkout's"
                " uncommitted changes were scanned, and no committed history was"
            )
        else:
            basis = (
                f"branch '{branch}' has committed nothing yet (the merge-base with {ref_name}"
                " IS this HEAD) — ONLY this checkout's uncommitted changes were scanned"
            )
    else:
        done = _git(root, "diff", "--name-only", "-z", "--diff-filter=d", base, "HEAD")
        if done.returncode != 0:
            raise CouldNotLook(
                f"the secret scan could not diff HEAD against the merge-base {base}."
            )
        committed = _z(done.stdout)
        raw += committed
        short = _out(root, "rev-parse", "--short", base) or base
        if taken:
            basis = (
                f"{len(committed)} file(s) committed since the CARRIED fork point ({short}) —"
                " this checkout's own history reaches none (a depth-1 mirror collapses HEAD"
                f" and {ref_name} onto one commit), so the base came over in"
                " DJB_LOOP_SCOPE_BASE, plus this checkout's uncommitted changes"
            )
        else:
            basis = (
                f"{len(committed)} file(s) committed on '{branch}' since the merge-base with"
                f" {ref_name} ({short}), plus this checkout's uncommitted changes"
            )
    done = _git(root, "diff", "--name-only", "-z", "--diff-filter=d", "HEAD")
    if done.returncode != 0:
        raise CouldNotLook("the secret scan could not diff the working tree against HEAD.")
    raw += _z(done.stdout)
    fork = base if base and base != head else ""
    return Changed(_finish(root, raw), basis, fork, taken)


def deleted_files(root: Path, fork: str) -> list[str]:
    """The paths deleted since `fork` (committed) or in the working tree, sorted."""
    raw: list[str] = []
    if fork:
        raw += _z(_git(root, "diff", "--name-only", "-z", "--diff-filter=D", fork, "HEAD").stdout)
    raw += _z(_git(root, "diff", "--name-only", "-z", "--diff-filter=D", "HEAD").stdout)
    return [p for p in sorted(set(raw)) if not (root / p).exists()]


def _z(text: str) -> list[str]:
    return [one for one in text.split("\0") if one]


def _finish(root: Path, raw: list[str]) -> list[str]:
    return [p for p in sorted(set(raw)) if (root / p).is_file()]


# --- the fan-out table ---------------------------------------------------------


def is_shared_test_infra(path: str) -> bool:
    """Whether `path` is test infrastructure every app's tests stand on."""
    for pattern, shared in _SHARED:
        if _match(path, pattern):
            return shared
    return False


def is_app_tests_path(path: str) -> bool:
    """Whether `path` is under an app's own `tests/` tree."""
    if not path.startswith("apps/"):
        return False
    rest = path[len("apps/") :]
    return rest.partition("/")[2].startswith("tests/")


def classify(path: str, root: Path = HOME) -> str:
    """The fan-out row a changed path falls in; `Unclassified` when the table has none."""
    if is_shared_test_infra(path):
        return "shared-test-infra"
    for patterns, shape in _CLASSES:
        if any(_match(path, p) for p in patterns):
            if shape == "app-tests" and not is_app_tests_path(path):
                return "app"
            return shape
    from quality.djb import ledger

    if ledger.docs_only_admits(path, root=root, home=HOME):
        return "inert"
    if any(_match(path, p) for p in _INERT):
        return "inert"
    raise Unclassified(
        f"the --loop scope has NO ROW for this changed path: {path} — the fan-out decision"
        " table is quality/djb/scope.py's classify. A path it cannot classify is exit 2 rather"
        " than a guess: a silent full run wastes a builder's minutes and a silent narrow one"
        " grades a rung against a suite that never saw its change. The remedy is one row,"
        " written by whoever added the territory."
    )


# --- the closure -------------------------------------------------------------


def closure(apps_dir: Path, seeds: Iterable[str]) -> list[str]:
    """The reverse-transitive `depends_on` closure of `seeds`, sorted; a stranger is exit 2."""
    if str(HOME) not in sys.path:
        sys.path.insert(0, str(HOME))
    try:
        from config.settings.discovery import discover_apps
    except Exception as exc:
        raise CouldNotLook(
            f"the --loop scope could not import config.settings.discovery ({exc}). The closure"
            " is read from the app declarations through that module and from nothing else."
        ) from exc
    if not apps_dir.is_dir():
        raise CouldNotLook(f"the --loop scope found no apps directory at {apps_dir}.")
    try:
        discovered = discover_apps(apps_dir)
    except Exception as exc:
        raise CouldNotLook(
            f"the --loop scope could not read the app declarations under {apps_dir} ({exc})."
        ) from exc
    declared = {one.label: tuple(one.depends_on) for one in discovered}
    # forward edges are not widened: a dependency cannot import its dependent (the DAG).
    reverse: dict[str, set[str]] = {label: set() for label in declared}
    for label, deps in declared.items():
        for dep in deps:
            reverse.setdefault(dep, set()).add(label)
    seeds = list(seeds)
    missing = sorted(one for one in seeds if one not in declared)
    if missing:
        raise CouldNotLook(
            " ".join(
                f"the --loop scope derived the app label '{one}' from a changed path and the"
                f" declarations do not know it: {apps_dir / one / 'apps.py'} declares no"
                " AppConfig, or is not there."
                for one in missing
            )
        )
    seen: set[str] = set()
    queue = list(seeds)
    while queue:
        label = queue.pop()
        if label in seen:
            continue
        seen.add(label)
        queue.extend(sorted(reverse.get(label, ())))
    return sorted(seen)


# --- the always-on block and the declared censuses --------------------------


def harness_files(root: Path) -> list[Path]:
    """The harness population, as git tracks it (SCF.5): never a typed file list."""
    listed = _git(root, "ls-files", "--", *HARNESS).stdout.splitlines()
    return [root / one for one in listed if one]


def _lines(path: Path) -> list[str]:
    text = path.read_bytes().decode("utf-8", "surrogateescape")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def sentinels(files: Sequence[Path]) -> tuple[str, str] | None:
    """The always-on block's begin and end lines, read from the harness that carries them."""
    for path in files:
        lines = _lines(path)
        for line in lines:
            found = _BEGIN.match(line)
            if found and f"# <<< {found.group(1)} <<<" in lines:
                return line, f"# <<< {found.group(1)} <<<"
    return None


def always_digest(files: Sequence[Path]) -> str:
    """The digest of the always-on block across `files`, or `UNDECLARED`."""
    present = [p for p in files if p.is_file()]
    marks = sentinels(present)
    if not present or marks is None:
        return "UNDECLARED"
    begin, end = marks
    block: list[str] = []
    for path in present:
        on = False
        for line in _lines(path):
            if begin in line:
                on = True
            elif end in line:
                on = False
            elif on:
                block.append(line)
    text = "\n".join(block).rstrip("\n")
    return sha256(text) if text else "UNDECLARED"


def harness_digest(root: Path) -> str:
    """The always-on block's digest over the tracked harness (`loop_scope__harness_digest`)."""
    return always_digest(harness_files(root))


def declared_censuses(
    root: Path, directory: str = "apps", pattern: str = "test_*.py"
) -> list[tuple[str, str]]:
    """`(path, declaration)` for every module under `directory` carrying the census marker."""
    base = root / directory
    if not base.is_dir():
        raise CouldNotLook(
            f"loop_scope__declared_censuses: {directory} is not a directory. The declared"
            " cross-app censuses could not be read; nothing was listed."
        )
    found: list[str] = []
    for dirpath, _dirs, names in os.walk(base):
        for name in names:
            full = Path(dirpath) / name
            if fnmatch.fnmatchcase(name, pattern) and full.is_file() and not full.is_symlink():
                found.append(f"{directory}/{full.relative_to(base).as_posix()}")
    out: list[tuple[str, str]] = []
    for path in sorted(found):
        rest = _census_line(root / path)
        if rest is None:
            continue
        reason = rest
        if rest.startswith(CENSUS_POPULATION):
            spec = rest[len(CENSUS_POPULATION) :]
            globs = spec.split(" ", 1)[0]
            if not globs:
                raise CouldNotLook(
                    f"{path} declares an EMPTY POPULATION. The grammar is `{CENSUS_MARKER}"
                    f" {CENSUS_POPULATION}<glob>[,<glob>] <reason>`."
                )
            reason = spec[len(globs) :].lstrip()
        if not reason:
            raise CouldNotLook(f"{path} carries the census marker and gives NO REASON.")
        out.append((path, rest))
    return out


def _census_line(path: Path) -> str | None:
    try:
        lines = _lines(path)[:CENSUS_LINES]
    except OSError as exc:
        raise CouldNotLook(f"{path} could not be read ({exc})") from exc
    for line in lines:
        if not line.startswith(CENSUS_MARKER):
            continue
        rest = line[len(CENSUS_MARKER) :]
        if rest and rest[0] not in " \t":
            continue
        return rest.lstrip()
    return None


def walls_view_text(root: Path, machine: str) -> str | None:
    """The walls table as this machine reads it (`gate_member_walls_view`); `None` when empty."""
    from quality.djb import registry

    homes = [root / one for one in registry.WALLS_HOMES]
    members = registry.walls_view(homes, machine, only=False)
    if not members:
        return None
    order = {
        "box": ["box", "ubuntu-latest", "darwin"],
        "darwin": ["darwin", "ubuntu-latest"],
        "ubuntu-latest": ["ubuntu-latest", "darwin"],
    }.get(machine, [machine])
    at: dict[str, object] = {}
    for home in homes:
        try:
            doc = json.loads(home.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc.get("measured_at"), dict):
            at.update(doc["measured_at"])
        else:
            label = str(doc.get("machine") or "")
            at["darwin" if label.startswith("Darwin") else label] = doc.get("measured_at", "")
    basis = next((at[m] for m in order if m in at), "")
    names = sorted(members)
    lines = ["{", f'  "measured_at": "{basis}",', f'  "machine": "{machine}",', '  "members": {']
    for i, name in enumerate(names):
        lines.append(f'    "{name}": {int(members[name])}' + ("," if i < len(names) - 1 else ""))
    lines += ["  }", "}"]
    return "\n".join(lines)


def always_on_digest(
    root: Path, durations: str | None = None, drives: str = "scripts/tests"
) -> str:
    """The digest of the always-on leg's inputs: the walls it reads and the marked drives."""
    from quality.djb import registry

    if durations:
        path = root / durations
        body = path.read_text(encoding="utf-8").rstrip("\n") if path.is_file() else "no-durations"
    else:
        view = walls_view_text(root, registry._machine())
        body = view if view is not None else "no-durations"
    if (root / drives).is_dir():
        try:
            rows = declared_censuses(root, drives, "test_*.sh")
        except CouldNotLook:
            return "UNDECLARED"
        marked = "\n".join(f"{p}\t{r}" for p, r in rows)
    else:
        marked = "no-drives-dir"
    return sha256(f"{body}\n{marked}\n")


def census_modules(root: Path) -> list[tuple[str, str]]:
    """`(declared basename, module)` for every app test module naming what seeds it."""
    out: list[tuple[str, str]] = []
    for module in sorted(
        p.relative_to(root).as_posix() for p in root.glob("apps/*/tests/test_*.py")
    ):
        decls = None
        for line in _lines(root / module):
            found = _SEEDED.match(line)
            if found:
                decls = found.group(1)
                break
        if not decls:
            continue
        for decl in decls.replace(",", " ").replace('"', "").replace("'", "").split():
            out.append((decl, module))
    return out


def census_seeds(path: str, modules: Sequence[tuple[str, str]]) -> list[str]:
    """The census modules of OTHER apps that a change to `path` seeds."""
    if not _match(path, "apps/*/*.py"):
        return []
    base = path.rsplit("/", 1)[-1][: -len(".py")]
    changed_app = path[len("apps/") :].split("/", 1)[0]
    return [
        module
        for decl, module in modules
        if decl == base and module[len("apps/") :].split("/", 1)[0] != changed_app
    ]


def literal_reads(root: Path, paths: Sequence[str]) -> list[tuple[str, str, str]]:
    """`(file, needle, why)` for every unexcused quote of a changed path (the decider's judge)."""
    from quality import loop_key

    needles: set[str] = set()
    for p in paths:
        needles.add(p)
        if "/" in p:
            needles.add(p.rsplit("/", 1)[-1])
    mark = loop_key.decider_value(NONREAD_NAME, HOME)
    try:
        quotes = loop_key.quotes(root, frozenset(needles), mark)
    except CouldNotLook as exc:
        sys.stderr.write(f"!! COULD NOT LOOK: {exc}\n")
        return []
    out: list[tuple[str, str, str]] = []
    for quote in quotes:
        file = quote.site.split(":", 1)[0]
        declared = loop_key.declarations(_text(root / file), mark)
        if any(d == quote.needle or d.rsplit("/", 1)[-1] == quote.needle for _, d in declared):
            continue
        why = next((p for p in paths if quote.needle in (p, p.rsplit("/", 1)[-1])), quote.needle)
        out.append((file, quote.needle, why))
    return out


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError:
        return ""


# --- the test-impact map ------------------------------------------------------


@dataclass
class Impact:
    """What the map answered: its digest, its tree and age, and a selection or the fallback."""

    sha: str = "-"
    tree: str = "-"
    tree_full: str = ""
    age: str = "-"
    select: str = ""
    tests: str = ""
    seen: str = ""
    status: str = ""
    fallback: str = ""


def map_fresh(root: Path, tree: str, base_ref: str, scan: int = MAP_SCAN) -> int:
    """0 when `tree` is among the fork point's last `scan` trees, 1 when not, 2 unverifiable."""
    if not tree or tree == "-":
        return 2
    if _out(root, "rev-parse", "--is-shallow-repository") != "false":
        return 2
    base = _out(root, "merge-base", "HEAD", base_ref) or ""
    if not base:
        return 2
    done = _git(root, "rev-list", f"--max-count={scan}", "--format=%T", base)
    if done.returncode != 0:
        return 2
    return 0 if tree in done.stdout.splitlines() else 1


def map_age(root: Path, path: str, base_ref: str) -> str:
    """Commits on the fork point since `path` last changed, or `unverifiable`."""
    base = _out(root, "merge-base", "HEAD", base_ref) or ""
    if not base or _out(root, "rev-parse", "--is-shallow-repository") != "false":
        return "unverifiable"
    commit = _out(root, "log", "-1", "--format=%H", base, "--", path) or ""
    if not commit:
        return "unverifiable"
    return _out(root, "rev-list", "--count", f"{commit}..{base}") or "unverifiable"


def _read_map(
    path: Path, label: str, changed: Sequence[tuple[str, str]], modules: Sequence[str]
) -> dict[str, str]:
    report: dict[str, str] = {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        tests = doc["tests"]
        if not isinstance(tests, dict) or not tests:
            raise ValueError("the map records no test")
        generated = doc.get("generated") or {}
    except Exception as exc:
        return {
            "tree": "-",
            "status": "fallback",
            "reason": f"{label} could not be read as a map ({exc}) — closure scope",
        }
    try:
        report["tree"] = str(generated.get("tree", "-")).rsplit(":", 1)[-1] or "-"
    except AttributeError:
        return {"reason": ""}
    known: set[str] = set()
    for files in tests.values():
        known.update(files)
    unseen = [(shape, p) for shape, p in changed if p not in known]
    if unseen:
        shape, p = unseen[0]
        more = f", and {len(unseen) - 1} more it has not" if len(unseen) > 1 else ""
        report["status"] = "fallback"
        report["reason"] = f"{p} ({shape}) never recorded by the map{more} — closure scope"
        return report
    seen = {p for _shape, p in changed}
    selected = {nodeid for nodeid, files in tests.items() if not seen.isdisjoint(files)}
    for module in modules:
        held = {nodeid for nodeid in tests if nodeid.split("::", 1)[0] == module}
        if not held:
            report["status"] = "fallback"
            report["reason"] = (
                f"{module} is seeded into the selection and the map holds no test from it"
                " — closure scope"
            )
            return report
        selected |= held
    report["status"] = "select"
    report["selected"] = str(len(selected))
    report["seen"] = str(len(seen))
    report["_body"] = "".join(f"{one}\n" for one in sorted(selected))
    return report


def impact(
    root: Path,
    changed: Sequence[tuple[str, str]],
    modules: Sequence[str],
    *,
    asked: bool,
    full: bool,
    bypassed: bool = False,
    base_ref: str = BASE_REF,
    scan: int = MAP_SCAN,
    map_path: str = MAP_PATH,
) -> Impact:
    """What the map selects for `changed`, or the sentence saying why the closure runs instead."""
    out = Impact()
    if bypassed:
        out.sha = "bypassed"
        out.fallback = (
            "DJB_LOOP_NO_IMPACT is set — the map was NOT consulted and this run is today's"
            " closure scope. The valve only widens, and it keys itself map=bypassed so no"
            " verdict crosses between the two."
        )
        return out
    path = root / map_path
    if not path.is_file() or not os.access(path, os.R_OK):
        out.fallback = (
            f"{map_path} is absent or unreadable — closure scope. A tree whose acceptance box"
            " has never written a map is a tree, not a broken read."
        )
        return out
    out.sha = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    if not asked:
        out.fallback = (
            "the caller did not ask for the map (only the ordinary --loop consults it) —"
            " today's closure scope, unchanged."
        )
        return out
    if not changed:
        out.fallback = (
            "the active rung changed no file this derivation can see, so there is nothing to"
            " select for — the scope is what it was and the always-on set runs alone."
        )
        return out
    report = _read_map(path, map_path, changed, modules)
    if "tree" in report:
        out.tree_full = report["tree"]
        out.tree = report["tree"][:8]
    out.status = report.get("status", "")
    out.fallback = report.get("reason", "")
    out.tests = report.get("selected", "")
    out.seen = report.get("seen", "")
    out.age = map_age(root, map_path, base_ref)
    if out.status != "select":
        if not out.fallback:
            out.fallback = (
                "the map reader did not answer (Traceback (most recent call last):) — closure scope"
            )
        return out
    fresh = map_fresh(root, out.tree_full, base_ref, scan)
    if fresh == 1:
        out.fallback = (
            f"the map was measured on tree:{out.tree} and this checkout's history does not"
            " hold that tree — a map from a tree this base never had is STALE, and a stale"
            " map is a slower run, never a wrong one."
        )
        return out
    if fresh == 2:
        out.age = "unverifiable"
    if full:
        out.fallback = (
            "mode=full — the active rung changed a file every test in the tree stands on, and"
            " the FULL suite outranks any selection a map could make."
        )
        return out
    handle, name = tempfile.mkstemp(
        prefix="djb-loop-impact.",
        dir=os.environ.get("TMPDIR") or "/tmp",  # noqa: S108 — the TMPDIR fallback for a mkstemp file, unique per call
    )
    with os.fdopen(handle, "w", encoding="utf-8") as sink:
        sink.write(report["_body"])
    out.select = name
    return out


# --- the gate's own tests: touched, uncovered, the census ---------------------

#: Where the gate's test modules live: the platform's tree and the product's drawer.
GATE_TESTS = ("quality/tests", "quality/local/tests")
#: The product's drawer (`boundary.DRAWER`); its absence is the template, read on the stdlib floor.
DRAWER = "quality/local/rules.yaml"
#: The census's sentence for a module no source can select.
UNSELECTABLE = (
    "a test nobody can select is a test that runs never or always, and neither is a selection"
)


def gate_test_modules(root: Path) -> list[str]:
    """Every tracked `test_*.py` under the gate's test homes, git's answer, sorted by bytes."""
    done = _git(root, "ls-files", "-z", "--", *GATE_TESTS)
    if done.returncode != 0:
        raise CouldNotLook(f"git ls-files could not list the gate's tests: {done.stderr.strip()}")
    return _sorted(
        p
        for p in _z(done.stdout)
        if _match(p.rsplit("/", 1)[-1], "test_*.py") and p.endswith(".py") and "/fixtures/" not in p
    )


def _shared_gate_infra(path: str) -> bool:
    """A non-test `.py` in a gate test home: the fixtures and plugin every module stands on."""
    for home in GATE_TESTS:
        if path.startswith(home + "/") and path.endswith(".py"):
            return not _match(path.rsplit("/", 1)[-1], "test_*.py")
    return False


def declared_drives(path: Path) -> list[str]:
    """The globs a module's module-level `pytestmark` hands `pytest.mark.drives`, in order."""
    import ast

    try:
        tree = ast.parse(_lines_text(path))
    except SyntaxError as exc:
        raise CouldNotLook(
            f"{path} does not parse, so its drives marker cannot be read ({exc})"
        ) from exc
    out: list[str] = []
    for node in tree.body:
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets)
        ):
            continue
        for call in ast.walk(node.value):
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "drives"
            ):
                for arg in call.args:
                    if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                        raise CouldNotLook(
                            f"{path}'s drives marker holds a non-literal argument; a selection"
                            " is read from the source, never computed"
                        )
                    _add(out, arg.value)
    return out


def _lines_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="surrogateescape")
    except OSError as exc:
        raise CouldNotLook(f"{path} could not be read ({exc})") from exc


def _covers(pattern: str, paths: Iterable[str]) -> list[str]:
    from quality.djb import ledger

    entries = [ledger.Entry("-", p) for p in paths]
    return [line.split(" ", 1)[1] for line in ledger.expand(entries, pattern)]


def map_rows(root: Path, map_path: str = MAP_PATH) -> dict[str, set[str]]:
    """Module -> the files the map says it executed, for the gate's test homes only."""
    path = root / map_path
    if not path.is_file():
        return {}
    try:
        tests = json.loads(path.read_text(encoding="utf-8"))["tests"]
    except (ValueError, KeyError, TypeError) as exc:
        raise CouldNotLook(f"{map_path} could not be read as a map ({exc})") from exc
    out: dict[str, set[str]] = {}
    for nodeid, files in tests.items():
        module = nodeid.split("::", 1)[0]
        if any(module.startswith(home + "/") for home in GATE_TESTS):
            out.setdefault(module, set()).update(files)
    return out


#: The probe app a would-be product's paths are judged under; no partition names it.
PROBE_APP = "zzz_canary"
HARNESS_DIR = "testing"
_UNOWNED_LEAF = "zzz_unowned_probe"
UNOWNED_WHY = ("shared", "census-every", "catch-all")


@dataclass(frozen=True)
class Declaration:
    """One gate test module's own selection sources: drives, census population, map rows."""

    module: str
    drives: tuple[str, ...]
    census: str
    population: tuple[str, ...]
    rows: frozenset[str]


def declarations(root: Path, modules: Sequence[str] | None = None) -> list[Declaration]:
    """Each gate test module's declaration, read once; `modules` defaults to git's listing."""
    rows = map_rows(root)
    out: list[Declaration] = []
    for module in gate_test_modules(root) if modules is None else modules:
        line = _census_line(root / module)
        population: tuple[str, ...] = ()
        if line is not None and line.startswith(CENSUS_POPULATION):
            spec = line[len(CENSUS_POPULATION) :].split(" ", 1)[0]
            population = tuple(g for g in spec.split(",") if g)
        out.append(
            Declaration(
                module,
                tuple(declared_drives(root / module)),
                "" if line is None else ("population" if population else "every"),
                population,
                frozenset(rows.get(module, ())),
            )
        )
    return out


def platform_apps(root: Path) -> tuple[str, ...]:
    """`platform_apps:` from `root`'s partition lockfile, else this checkout's; stdlib only."""
    for base in (root, HOME):
        path = base / "quality/partition.yaml"
        if not path.is_file():
            continue
        out: list[str] = []
        listing = False
        for line in _lines(path):
            if line.startswith("platform_apps:"):
                listing = True
            elif listing and line.startswith("  - "):
                out.append(line[4:].split(" #", 1)[0].strip())
            elif listing and line.strip() and not line.lstrip().startswith("#"):
                break
        if out:
            return tuple(sorted(out))
    raise CouldNotLook("no quality/partition.yaml names platform_apps — no path is a product's")


def product_root(path: str, platform: Sequence[str]) -> str:
    """`apps/<label>/` for a path under a non-platform app, `frontend/` under it, else `""`."""
    if path.startswith("frontend/"):
        return "frontend/"
    parts = path.split("/")
    if len(parts) > 2 and parts[0] == "apps" and parts[1] not in (*platform, HARNESS_DIR):
        return f"apps/{parts[1]}/"
    return ""


def is_product_path(path: str, platform: Sequence[str]) -> bool:
    """Whether a product diff writes `path`: its own app, `frontend/`, or a derived file."""
    return bool(product_root(path, platform)) or any(_match(path, g) for g in PRODUCT_DERIVED)


@functools.lru_cache(maxsize=4096)
def _glob_rx(glob: str) -> re.Pattern[str]:
    from quality.djb import ledger

    return ledger._to_re(glob)


def _hits(glob: str, path: str) -> bool:
    return _glob_rx(glob).match(path) is not None


def _owns(glob: str, path: str, root_of: str) -> bool:
    return _hits(glob, path) and not (root_of and _hits(glob, root_of + _UNOWNED_LEAF))


def why_selected(decl: Declaration, path: str, platform: Sequence[str]) -> str:
    """Why `path` selects `decl.module` — an owning source or an `UNOWNED_WHY` word — or `""`."""
    if _shared_gate_infra(path):
        return "shared"
    if path == decl.module:
        return "self"
    if path in decl.rows:
        return "map"
    root_of = product_root(path, platform)
    caught = ""
    for kind, globs in (("drives", decl.drives), ("census", decl.population)):
        for glob in globs:
            if _owns(glob, path, root_of):
                return f"{kind} {glob}"
            if _hits(glob, path):
                caught = "catch-all"
    return caught or ("census-every" if decl.census == "every" else "")


@dataclass
class Selection:
    """The gate test modules a change selects, each with the owning reason or `UNOWNED_WHY`."""

    why: dict[str, list[str]] = field(default_factory=dict)

    @property
    def modules(self) -> list[str]:
        return list(self.why)

    @property
    def unowned(self) -> list[str]:
        """The modules no changed path selects by the module's own narrowed declaration."""
        return [m for m, ws in self.why.items() if all(w in UNOWNED_WHY for w in ws)]


def selection(
    root: Path, changed: Sequence[str], decls: Sequence[Declaration] | None = None
) -> Selection:
    """The modules `changed` selects and why, one reason per changed path that selects it."""
    platform = platform_apps(root)
    out = Selection()
    for decl in declarations(root) if decls is None else decls:
        for path in changed:
            why = why_selected(decl, path, platform)
            if why:
                out.why.setdefault(decl.module, []).append(why)
    return out


def touched(root: Path, changed: Sequence[str]) -> list[str]:
    """The gate's test modules a change selects: the map's rows, the drives marker, the census."""
    found = selection(root, changed).modules
    if not found or product_namespace(root) is None:
        return found
    from quality.djb.legs import always_on

    left = always_on.platform_tests(found)
    return [m for m in found if m not in left]


#: The names a gate test module joins a checkout-relative path to when it reads the checkout.
CHECKOUT_ROOTS = ("ROOT", "HOME", "REPO_ROOT")


def _spelled(path: Path) -> list[str]:
    """Every literal the module joins to a checkout root with `/` — what its body reads."""
    import ast

    out: list[str] = []
    for node in ast.walk(ast.parse(_lines_text(path))):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
            continue
        left = node.left
        name = left.id if isinstance(left, ast.Name) else getattr(left, "attr", "")
        right = node.right
        if name in CHECKOUT_ROOTS and isinstance(right, ast.Constant):
            if isinstance(right.value, str):
                _add(out, right.value)
    return out


def uncovered(root: Path, module: str, tracked: Sequence[str]) -> tuple[list[str], list[str]]:
    """`(globs matching no tracked file, tracked paths the body spells that nothing declares)`."""
    globs = declared_drives(root / module)
    empty = [glob for glob in globs if not _covers(glob, tracked)]
    covered = set(map_rows(root).get(module, ())) | {module}
    for glob in globs:
        covered.update(_covers(glob, tracked))
    files = set(tracked)
    unread = [word for word in _spelled(root / module) if word in files and word not in covered]
    return empty, unread


def census(root: Path) -> list[str]:
    """One finding per gate test module no source selects or whose declaration is about nothing."""
    done = _git(root, "ls-files", "-z")
    if done.returncode != 0:
        raise CouldNotLook(f"git ls-files could not list the tree: {done.stderr.strip()}")
    tracked = _z(done.stdout)
    rows = map_rows(root)
    out: list[str] = []
    for module in gate_test_modules(root):
        census_line = _census_line(root / module) is not None
        globs = declared_drives(root / module)
        if not (census_line or globs or module in rows):
            out.append(
                f"{module}: no impact-map entry, no drives marker and no census line"
                f" — {UNSELECTABLE}"
            )
            continue
        empty, unread = uncovered(root, module, tracked)
        for glob in empty:
            out.append(
                f"{module}: its drives glob {glob} matches no tracked file — a declaration"
                " about nothing"
            )
        if unread:
            out.append(
                f"{module}: its body spells {_phrase(unread)} and its drives marker covers"
                " none of them — declare each, or the module is never selected when it changes"
            )
    return out


def _phrase(words: Sequence[str]) -> str:
    if len(words) == 1:
        return words[0]
    return f"{', '.join(words[:-1])} and {words[-1]}"


# --- the scope -----------------------------------------------------------------


@dataclass
class Scope:
    """One `--loop` scope derivation: every decision `loop_tier_own_apps` makes, by name."""

    mode: str = "fast"
    basis: str = ""
    reason: str = ""
    own: list[str] = field(default_factory=list)
    shared_hits: list[str] = field(default_factory=list)
    narrow: bool = False
    apps: list[str] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    widened: list[str] = field(default_factory=list)
    shapes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tests_only: list[str] = field(default_factory=list)
    changed_tests: list[str] = field(default_factory=list)
    seeded_tests: list[str] = field(default_factory=list)
    seeded_by: list[str] = field(default_factory=list)
    literal_tests: list[str] = field(default_factory=list)
    literal_by: list[str] = field(default_factory=list)
    literal_unselected: list[str] = field(default_factory=list)
    always: str = ""
    always_on: str = ""
    tax: str = ""
    changed: list[str] = field(default_factory=list)
    changed_tsv: list[tuple[str, str]] = field(default_factory=list)
    impact: Impact = field(default_factory=Impact)
    asked_impact: bool = False
    mine: bool = False
    key_mode: str = "fast"
    product: list[str] | None = None

    def note(self, line: str) -> None:
        """Add a note once: a line already opening a note is not said twice."""
        if ("\n" + line) not in ("\n" + "\n".join(self.notes)):
            self.notes.append(line)

    @property
    def canonical(self) -> str:
        """The scope string the loop key hashes (`LOOP_SCOPE_CANONICAL`)."""
        if self.product is not None:
            return (
                f"mode=product own={_w(self.touched)} scope={_w(self.product)}"
                f" always={self.always} tests=- seeded=- alwayson={self.always_on} map=-"
            )
        if self.mode == "full":
            return (
                f"mode=full own=- scope=- always={self.always} tests=- seeded=-"
                f" alwayson={self.always_on} map={self.impact.sha or '-'}"
            )
        return (
            f"mode={self.key_mode} own={_w(self.touched)} scope={_w(self.apps)}"
            f" always={self.always} tests={_w(self.tests_only)} seeded={_w(self.seeded_tests)}"
            f" alwayson={self.always_on} map={self.impact.sha or '-'}"
        )


def _w(words: Sequence[str]) -> str:
    return " ".join(words) or "-"


def census_moved(declaration: str, changed: Sequence[str]) -> bool:
    """Whether a census joins: it declares `every`, or a changed path is in its population."""
    if not declaration.startswith(CENSUS_POPULATION):
        return True
    globs = declaration[len(CENSUS_POPULATION) :].split(" ", 1)[0].split(",")
    return any(_hits(glob, path) for glob in globs if glob for path in changed)


def census_join(root: Path, scope: Scope) -> None:
    """Seed each marked census whose population moved; exit 2 when a marked one is unread."""
    from quality.djb.legs import always_on

    joined = always_on.census_population(root)
    marked = [path for path, _ in declared_censuses(root, *always_on.CENSUS_HOME)]
    missing = sorted(set(marked) - set(joined))
    if missing:
        raise CouldNotLook(
            f"{len(missing)} module(s) carry the census marker and are NOT in the always-on"
            f" census set: {' '.join(missing)}. A marked census left out of a scope is a hole"
            " every narrowed loop falls through; nothing was selected."
        )
    declared = dict(declared_censuses(root, *always_on.CENSUS_HOME))
    moved = [m for m in joined if census_moved(declared.get(m, ""), scope.changed)]
    for module in moved:
        _add(scope.seeded_tests, module)
    scope.seeded_tests = sorted(scope.seeded_tests)
    if joined:
        scope.note(f"{always_on.joined_line(moved, joined)}: {' '.join(moved) or '-'}")


def derive(
    root: Path,
    *,
    base_ref: str | None = None,
    carried: str | None = None,
    mine: bool = False,
    asked_impact: bool = False,
    also: str = "",
    no_impact: bool = False,
    scan: int = MAP_SCAN,
) -> Scope:
    """The active rung's `--loop` scope over `root` (`loop_tier_own_apps`); exit 2 on doubt."""
    scope = Scope(mine=mine, asked_impact=asked_impact)
    changed = changed_files(root, base_ref, carried)
    scope.basis = changed.basis
    ref = base_ref or BASE_REF
    if _git(root, "rev-parse", "-q", "--verify", ref).returncode != 0:
        raise CouldNotLook(
            f"this checkout has NO local {ref}, so the --loop scope has no fork point to derive"
            " the active rung from. A thin basis is not a small answer; it is the wrong one."
            " The two legal moves: create the ref at this clone's fork point (`git branch main"
            " <the sha this branch was cut from>`), or run the gate in a checkout of the family"
            " that has one — the primary, or any linked worktree of it."
        )
    modules = census_modules(root)
    touched: list[str] = []
    tests_touched: list[str] = []
    literal_paths: list[str] = []
    for path in changed.paths:
        shape = classify(path, root)
        _add(scope.shapes, shape)
        scope.changed.append(path)
        scope.changed_tsv.append((shape, path))
        for module in census_seeds(path, modules):
            _add(scope.seeded_tests, module)
            _add(scope.seeded_by, path)
        label = path[len("apps/") :].split("/", 1)[0] if path.startswith("apps/") else ""
        if shape in _SHARED_SHAPES:
            _add(scope.shared_hits, path)
        elif shape == "app" and label:
            _add(touched, label)
        elif shape == "inert" and (path == "TEMPLATE_VERSION" or path.endswith(".md")):
            literal_paths.append(path)
        elif shape == "app-tests" and label:
            _add(tests_touched, label)
            name = path.rsplit("/", 1)[-1]
            if name.startswith("test_") and name.endswith(".py"):
                _add(scope.changed_tests, path)
    platform = platform_apps(root)
    for path in deleted_files(root, changed.base):
        label = product_root(path, platform)[len("apps/") : -1]
        if label and (root / "apps" / label).is_dir():
            _add(touched, label)
            scope.note(
                f"{path} was deleted: a deletion under a product app runs that app's own scope,"
                " which the changed-file reader alone never sees"
            )
    scope.shapes = sorted(scope.shapes)
    if "quality" in scope.shapes:
        scope.note(
            "quality/** was touched and widens NO pytest scope: a quality/** rung runs the FULL"
            " GATE under a typed DJB_GATE_SANCTION (rung-execution §3), and that rule outranks"
            " any widening this table could do."
        )
    if "declared-blind-spot" in scope.shapes:
        scope.note(
            "pyproject.toml / uv.lock was touched and widens NO scope — the declared blind spot,"
            " re-declared: a rung touching either is a DEPENDENCY rung and runs the FULL gate"
            " (rung-execution §3), which is the wall that covers it."
        )
    if "frontend" in scope.shapes:
        scope.note(
            "frontend/** was touched and derives NO backend scope: there is no import path from"
            " frontend/ into a Python test. The fe leg's own change-awareness is what grades"
            " that change."
        )
    if scope.shared_hits:
        if mine:
            scope.note(
                "--mine narrowed NOTHING: the active rung changed shared test infrastructure,"
                " which outranks the flag — there is no own-app scope to subtract a closure"
                " from, so this run is the FULL suite."
            )
        scope.mode = "full"
        scope.reason = (
            "the active rung changed shared test infrastructure or a file no app owns that"
            " every test stands on — so --loop runs the FULL suite, not a scope"
        )
        scope.always = harness_digest(root)
        scope.always_on = always_on_digest(root)
        scope.impact = impact(
            root,
            scope.changed_tsv,
            scope.seeded_tests,
            asked=asked_impact,
            full=True,
            bypassed=no_impact,
            base_ref=ref,
            scan=scan,
        )
        scope.tax = tax_line(root, charged(root, scope.changed, changed.base))
        return on_a_product(root, scope)
    scope.touched = sorted(touched)
    if also:
        for label in also.split():
            _add(touched, label)
        scope.touched = sorted(touched)
        scope.note(
            f"DJB_LOOP_SCOPE_ALSO widened the seeds with: {also}. The override can only ADD —"
            " nothing it names can leave the scope."
        )
    scope.tests_only = sorted(one for one in tests_touched if one not in scope.touched)
    if scope.tests_only:
        closure(root / "apps", scope.tests_only)
        scope.changed_tests = [
            p for p in scope.changed_tests if p[len("apps/") :].split("/", 1)[0] in scope.tests_only
        ]
        scope.note(
            "a cross-app coupling that is not an import and not a test import is not in this"
            " selection; the push runs everything"
        )
    else:
        scope.changed_tests = []
    if scope.seeded_tests:
        scope.seeded_tests = sorted(scope.seeded_tests)
        scope.seeded_by = sorted(scope.seeded_by)
        scope.note(
            f"census-seeded by {' '.join(scope.seeded_by)}: {' '.join(scope.seeded_tests)} — a"
            " core census that reads OTHER apps' declarations, which the reverse depends_on"
            " closure can never reach (core is everyone's dependency and nobody's dependant)."
            " The module is added, never the core app or its organ tests."
        )
    if literal_paths:
        for file, needle, why in literal_reads(root, literal_paths):
            if _match(file, "apps/*/tests/test_*.py"):
                _add(scope.literal_tests, file)
                _add(scope.literal_by, why)
            else:
                _add(scope.literal_unselected, f"{file}({needle})")
    if scope.literal_tests:
        scope.literal_tests = sorted(scope.literal_tests)
        scope.literal_by = sorted(scope.literal_by)
        for one in scope.literal_tests:
            _add(scope.seeded_tests, one)
        scope.seeded_tests = sorted(scope.seeded_tests)
        scope.note(
            f"literal-read seeded by {' '.join(scope.literal_by)}: {' '.join(scope.literal_tests)}"
            " — each module QUOTES a changed path the inert row would otherwise have dropped,"
            " found by gate_docs_only_literal_reads (scripts/gate_ledger.sh), the docs-only push"
            " road's own judge. The module is added, never its app."
        )
    if scope.literal_unselected:
        scope.note(
            f"literal-read NOT selected: {' '.join(scope.literal_unselected)} — a module that is"
            " not a test quotes a changed inert path; its behaviour is reached only through the"
            " tests that import it, and the push runs everything."
        )
    census_join(root, scope)
    if scope.touched:
        scope.apps = closure(root / "apps", scope.touched)
        scope.widened = sorted(one for one in scope.apps if one not in scope.touched)
    if mine and scope.apps:
        own = " ".join(scope.touched)
        scope.apps = list(scope.touched)
        scope.widened = []
        scope.note(
            f"--mine: the depends_on closure was NOT walked into the scope — [{own}]"
            " run IN FULL and nothing else does; a regression in a DEPENDANT of those apps"
            " surfaces at the ordinary --loop, which is the run to make at your last boundary."
        )
    scope.own = list(scope.touched)
    scope.narrow = True
    scope.always = harness_digest(root)
    scope.always_on = always_on_digest(root)
    scope.key_mode = "mine" if mine else "fast"
    scope.impact = impact(
        root,
        scope.changed_tsv,
        scope.seeded_tests,
        asked=asked_impact,
        full=False,
        bypassed=no_impact,
        base_ref=ref,
        scan=scan,
    )
    if scope.impact.select:
        scope.note(
            f"the TEST-IMPACT MAP answered: {scope.impact.tests} test(s) selected for"
            f" {scope.impact.seen} changed file(s) it has seen, so the closure above is NOT what"
            " runs — the scope flags are dropped and the selection is handed to pytest whole. A"
            " test the map attributes elsewhere is the declared hole, bounded by the wave's bank."
        )
    else:
        scope.note(f"the TEST-IMPACT MAP did NOT narrow this run: {scope.impact.fallback}")
    widened, own, tests = _w(scope.widened), " ".join(scope.touched), " ".join(scope.tests_only)
    if scope.apps:
        if mine:
            scope.reason = (
                f"--mine: the fast tier narrowed to the active rung's OWN app(s) [{own}],"
                " which run IN FULL, with the reverse-transitive depends_on closure NOT walked"
                " into the scope — plus the always-on cross-app set"
            )
        else:
            scope.reason = (
                f"the fast tier NARROWED to the active rung's scope — its own app(s) [{own}],"
                f" which run IN FULL, plus the reverse-transitive depends_on closure [{widened}],"
                " which runs its fast tier — plus the always-on cross-app set"
            )
        if scope.tests_only:
            scope.reason += (
                f" — and [{tests}] changed ONLY tests under apps/<x>/tests/,"
                " so they seeded NO closure: their test trees run at the fast tier, the edited"
                " modules run whatever tier they are in, and so does every collected module that"
                " names one of those test packages"
            )
    elif scope.tests_only:
        scope.reason = (
            f"the active rung changed only tests under apps/<x>/tests/ [{tests}],"
            " so NO closure was walked — those apps' test trees run at the fast tier, the edited"
            " modules run whatever tier they are in, every collected module that names one of"
            " those test packages runs its fast tier, plus the always-on cross-app set"
        )
    else:
        scope.reason = (
            "the active rung changed no file under apps/<x>/ and no shared test infrastructure,"
            " so the scope is EMPTY and the always-on cross-app set runs alone"
        )
    scope.tax = tax_line(root, charged(root, scope.changed, changed.base))
    return on_a_product(root, scope)


def product_namespace(root: Path) -> str | None:
    """The drawer's namespace (`gate_tests.product_of`); None on the template, stdlib alone."""
    if not (root / DRAWER).is_file():
        return None
    from quality.djb.legs import gate_tests

    try:
        return gate_tests.product_of(root)
    except ImportError as exc:
        raise CouldNotLook(
            f"{DRAWER} is present and this interpreter cannot import its reader ({exc}):"
            " a product tree's scope is not derived on the stdlib floor"
        ) from exc
    except OSError as exc:
        raise CouldNotLook(f"{DRAWER} could not be read: {exc}") from exc


def on_a_product(root: Path, scope: Scope) -> Scope:
    """A product tree's own apps the change is inside, else all of them; never a platform's."""
    if product_namespace(root) is None:
        return scope
    from quality.djb.legs import gate_tests

    apps = gate_tests.product_apps(root)
    hit = [one for one in apps if any(p.startswith(f"{one}/") for p in scope.changed)]
    scope.product = hit or list(apps)
    scope.note(
        f"a product tree: pytest runs the product's own apps [{_w(scope.product)}] by path,"
        " with or without a map — the platform's tests are not a product's to pay for"
    )
    return scope


# --- the loop key, its environment fingerprint, and reuse across a docs-only delta --------------

#: The fence a shell file declares the `.env` names a checkout derives for itself between.
ENV_DECL = ("# >>> derived-env-keys >>>", "# <<< derived-env-keys <<<")
#: The module that answers the suite's environment read-set (`python -m <it> env-reads`).
ENV_READS_OWNER = "quality/partition.py"
_DECL_NAME = re.compile(r"^[A-Z][A-Z0-9_]*[ \t]")


def derived_env_keys(root: Path) -> list[str]:
    """The `.env` names each `scripts/*.sh` declares inside its fence, sorted by bytes."""
    begin, end = ENV_DECL
    out: set[str] = set()
    for path in sorted((root / "scripts").glob("*.sh")):
        if not path.is_file():
            continue
        on = False
        for line in _lines(path):
            if begin in line:
                on = True
                continue
            if end in line:
                on = False
                continue
            if not on:
                continue
            line = re.sub(r"^[ \t]*#[ \t]*", "", line, count=1)
            if not _DECL_NAME.match(line):
                continue
            name = re.split(r"[ \t]", line, maxsplit=1)[0]
            if line[len(name) :].lstrip(" \t").startswith("—"):
                out.add(name)
    return sorted(out)


def _dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in _lines(path):
        line = raw.lstrip(" \t")
        if line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip(" \t")
        if len(value) > 1 and value[0] in "\"'" and value[-1] == value[0]:
            value = value[1:-1]
        out[re.sub(r"[ \t]", "", name)] = value
    return out


def env_reads(root: Path, reads_file: str | None = None) -> str:
    """The digest of each name the suite reads, as the process or `.env` sets it; or `no-census`."""
    from quality.djb import env as environment

    if reads_file:
        if not Path(reads_file).is_file():
            raise CouldNotLook(f"the environment read-set file {reads_file} does not exist")
        names = Path(reads_file).read_text(encoding="utf-8").rstrip("\n")
    elif (root / ENV_READS_OWNER).is_file():
        python = root / ".venv/bin/python"
        if not os.access(python, os.X_OK):
            raise CouldNotLook(f"{python} is not executable, so the read-set has no reader")
        module = ENV_READS_OWNER[: -len(".py")].replace("/", ".")
        done = subprocess.run(
            [str(python), "-m", module, "env-reads"], cwd=root, capture_output=True, text=True
        )
        if done.returncode != 0:
            raise CouldNotLook(
                f"{module} env-reads exited {done.returncode}{tool_said(done.stderr)}"
            )
        names = done.stdout.rstrip("\n")
    else:
        return "no-census"
    if not names:
        raise CouldNotLook("the environment read-set is empty — a read that did not answer")
    dotenv = root / ".env"
    file = _dotenv(dotenv) if dotenv.is_file() else {}
    live = environment.environ()
    body = ""
    for name in names.split("\n"):
        if not name:
            continue
        if name in live:
            body += f"{name}={live[name]}\n"
        elif name in file:
            body += f"{name}={file[name]}\n"
        else:
            body += f"{name}=<unset>\n"
    return sha256(body)


def _dists(root: Path) -> list[str]:
    venv = root / ".venv"
    if venv.is_symlink():
        return []
    found: list[str] = []
    for dirpath, dirs, _names in os.walk(venv):
        depth = len(Path(dirpath).relative_to(venv).parts)
        for name in dirs:
            if fnmatch.fnmatchcase(name, "*.dist-info") and depth + 1 <= 4:
                found.append(name)
        if depth + 1 >= 4:
            dirs[:] = []
    return sorted(found)


@dataclass
class Fingerprint:
    """The environment half of the loop key, and the components it hashes."""

    digest: str
    components: str


def env_fingerprint(root: Path, reads_file: str | None = None) -> Fingerprint:
    """The `.env` less its derived keys, the installed dists, the read-set and the merge-base."""
    keys = derived_env_keys(root)
    dotenv = root / ".env"
    if dotenv.is_file():
        if not keys:
            excluded = "UNDECLARED(whole-file)"
            env_digest = hashlib.sha256(dotenv.read_bytes()).hexdigest()
        else:
            excluded = ",".join(keys)
            drop = set(keys)
            kept = [
                line
                for line in _lines(dotenv)
                if re.sub(r"[ \t]", "", line.split("=", 1)[0]) not in drop
            ]
            env_digest = sha256("".join(f"{line}\n" for line in kept))
    else:
        excluded = env_digest = "no-env-file"
    site = _dists(root)
    if not site:
        raise CouldNotLook(
            f"the --loop ledger could not census the installed distributions under"
            f" {root / '.venv'}. Zero distributions is a read that did not answer, not an empty"
            " environment — no key is derived and nothing is reused."
        )
    dists = sha256("\n".join(site))
    reads = env_reads(root, reads_file)
    head = _out(root, "rev-parse", "-q", "--verify", "HEAD") or "unborn"
    base = "no-local-main"
    if _git(root, "rev-parse", "-q", "--verify", BASE_REF).returncode == 0:
        base = _out(root, "merge-base", "HEAD", BASE_REF) or "no-merge-base"
    return Fingerprint(
        sha256(
            f"env={env_digest} excluded={excluded} dists={dists} reads={reads} merge-base={base}\n"
        ),
        f"env-file={env_digest} excluded={excluded} dists={dists} env-reads={reads}"
        f" head={head} merge-base={base}",
    )


def loop_key(root: Path, tree: str, scope: Scope, reads_file: str | None = None) -> str:
    """`loop-v1:<hex>` for the measured `tree` under `scope` in this environment."""
    from quality.djb import ledger

    try:
        key_tree = ledger.loop_key_tree(root, tree)
    except ledger.KeyCannot as exc:
        raise CouldNotLook(str(exc)) from exc
    return ledger.loop_key(key_tree, env_fingerprint(root, reads_file).digest, scope.canonical)


@dataclass
class Reuse:
    """A docs-only reuse: the banked tree and the delta's size, or why it was refused."""

    tree: str = ""
    count: int = 0
    why: str = ""


def _component(line: str, name: str) -> str:
    padded = f" {line} "
    if f" {name}=" not in padded:
        return ""
    return padded.split(f" {name}=", 1)[1].split(" ", 1)[0]


def loop_reuse(root: Path, basis: str) -> Reuse:
    """A verdict banked on an ancestor HEAD, reused across a docs-only delta since it."""
    from quality.djb import ledger

    out = Reuse()
    head = _component(basis, "head")
    if not head:
        return out
    if _git(root, "merge-base", "--is-ancestor", head, "HEAD").returncode != 0:
        return out
    files = ledger.changed_between(root, head, "HEAD")
    if not files:
        return out
    if not all(ledger.docs_only_admits(p, head, "HEAD", root=root) for p in files):
        return out
    if _out(root, "status", "--porcelain"):
        out.why = (
            "docs-only delta, but the WORKING TREE is not clean: an uncommitted edit is not a delta"
            " anyone can name — measuring"
        )
        return out
    banked = _component(basis, "tree")
    committed = ledger.measured_tree_of(root, head)
    if not banked or banked != committed:
        out.why = (
            "the banked verdict was measured on a tree that is not its head's measured tree"
            " — measuring"
        )
        return out
    readers = sorted(p for p in (root / "apps").rglob("*.py") if p.is_file())
    for path in files:
        hit = next((r for r in readers if path in _text(r)), None)
        if hit is not None:
            out.why = (
                f"docs-only delta touches a path spelled in a module under apps/: {path}"
                f" (named in {hit.relative_to(root).as_posix()}) — measuring"
            )
            return out
    out.tree, out.count = banked, len(files)
    return out


def pytest_args(scope: Scope, counts: str = "") -> list[str]:
    """The flags the pytest door is handed for `scope` (`loop_scope__pytest_args`)."""
    if scope.product is not None:
        return list(scope.product)
    if scope.mode == "full" or not scope.narrow:
        return []
    out: list[str] = []
    if scope.asked_impact:
        out += [f"--djb-changed={p}" for p in scope.changed]
    tests = [*scope.changed_tests, *scope.seeded_tests]
    if scope.impact.select:
        out.append(f"--djb-impact-select={scope.impact.select}")
        out += [f"--djb-changed-test={p}" for p in tests]
        if counts:
            out.append(f"--djb-scope-counts={counts}")
        return out
    out.append("--djb-scope-narrow")
    out += [f"--djb-scope={label}" for label in scope.apps]
    out += [f"--djb-tests-only={label}" for label in scope.tests_only]
    out += [f"--djb-changed-test={p}" for p in tests]
    if counts:
        out.append(f"--djb-scope-counts={counts}")
    return out


def banner(scope: Scope) -> list[str]:
    """The `--loop` scope block, one line per decision, as the gate prints it before any leg."""
    out = [
        f"- loop scope: {scope.reason}",
        f"  basis:      {scope.basis}",
        f"  scope   touched: {_w(scope.touched)}",
        f"  scope   tests-only: {_w(scope.tests_only)}",
        f"  scope   closure: {_w(scope.widened)}",
        f"  scope   own (organ tests in full): {_w(scope.own)}",
        f"  scope   rule: {scope.reason}",
        f"  scope   map: sha={scope.impact.sha or '-'} generated=tree:{scope.impact.tree or '-'}"
        f" age={scope.impact.age or '-'} commit(s) since",
    ]
    if scope.impact.select:
        out += [
            f"  scope   impact: {scope.impact.seen or 0} changed file(s) the map has SEEN ->"
            f" {scope.impact.tests or 0} test(s) selected; fallback: none",
            "          the always-on cross-app set is added at the pytest door, which",
            "          prints its own count as `impact-select: <named>, <always-on>`;",
            "          the closure scope above was NOT what ran.",
        ]
    else:
        out.append(
            "  scope   impact: no selection; fallback:"
            f" {scope.impact.fallback or 'the map was not consulted'}"
        )
    if scope.tax:
        out.append(f"  {scope.tax}")
    out += [f"  note:       {line}" for line in scope.notes]
    return out


#: The history files a consumer census never counts (GP 4.0's exclusions).
HISTORY = (
    "docs/product/cycles/*",
    "docs/product/archive/*",
    "docs/product/surveys/*",
    "docs/product/reports/*",
    "docs/product/briefs/*",
    "CHANGELOG.md",
)
_FUNC = re.compile(r"^([a-z_][a-z0-9_]*)\(\)\s*\{", re.MULTILINE)
_COMMENT = re.compile(r"^\s*#")
_CALL_AT = r"(?:^|[;&|({\n'\"]|\$\(|\bthen\s|\bdo\s|\bif\s|!\s|&&\s|\|\|\s)\s*"


def _sourced(lib: str) -> re.Pattern[str]:
    return re.compile(
        rf"(?:^|[\s;&|({{'\"])(?:\.|source)\s+(?:[\"'$./]|scripts/).*?\b{lib}\.sh\b"
        rf"|[\"']source[\"'],\s*[\"']scripts/{lib}\.sh[\"']"
    )


def lib_functions(root: Path, lib: str) -> list[str]:
    """The function names `scripts/<lib>.sh` defines, sorted."""
    return sorted(set(_FUNC.findall(_text(root / "scripts" / f"{lib}.sh"))))


def consumers(root: Path, lib: str) -> dict[str, list[str]]:
    """Each file naming `scripts/<lib>.sh` or calling its functions: code, prelude, pin or cite."""
    names = [n for n in lib_functions(root, lib) if not n.startswith("_")]
    sourced = _sourced(lib)
    listed = re.compile(rf"^\s*[\"']\.?/?scripts/{lib}\.sh[\"'],?\s*$")
    called = re.compile(_CALL_AT + "(?:" + "|".join(map(re.escape, names)) + r")\b(?![\"':]|\s*\()")
    words = [w for n in [f"{lib}.sh", *names] for w in ("-e", n)]
    found = (_out(root, "grep", "-l", "-z", "-F", *words) or "").split("\0")
    kinds: dict[str, list[str]] = {"code": [], "prelude": [], "pin": [], "cite": []}
    for path in found:
        if not path or path == f"scripts/{lib}.sh" or any(_match(path, h) for h in HISTORY):
            continue
        text = _text(root / path)
        if f"{lib}.sh" not in text and not (names and called.search(text)):
            continue
        lines = [] if path.endswith((".md", ".txt", ".json", ".claims")) else text.splitlines()
        lines = [line for line in lines if not _COMMENT.match(line)]
        code = any(sourced.search(line) or (names and called.search(line)) for line in lines)
        test = "/tests/" in f"/{path}"
        if code or (test and any(listed.search(line) for line in lines)):
            kinds["pin" if test else "code"].append(path)
        elif any(listed.search(line) for line in lines):
            kinds["prelude"].append(path)
        else:
            kinds["cite"].append(path)
    return kinds


def consumers_main(argv: Sequence[str]) -> int:
    """`consumers [--root R] <lib>…`: one row per library and kind, then each file."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m quality.djb.scope consumers")
    parser.add_argument("--root", default=".")
    parser.add_argument("--files", action="store_true", help="each file under its row")
    parser.add_argument("libs", nargs="+")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    for lib in args.libs:
        path = root / "scripts" / f"{lib}.sh"
        if not path.is_file():
            print(f"{lib}\tgone")
            continue
        lines = _lines(path)
        code_lines = sum(1 for line in lines if line.strip() and not _COMMENT.match(line))
        kinds = consumers(root, lib)
        print(
            f"{lib}\tcode-lines={code_lines}\tcode={len(kinds['code'])}"
            f"\tprelude={len(kinds['prelude'])}\tpin={len(kinds['pin'])}\tcite={len(kinds['cite'])}"
        )
        if args.files:
            for kind in ("code", "prelude", "pin"):
                for file in kinds[kind]:
                    print(f"  {kind}\t{file}")
    return 0


# --- the CI lane: the one word a pull request's run is chosen by --------------------------------

#: The lanes CI runs, cheapest first; `fast` is the pre-commit hook's and never a CI lane.

# --- the selftest unit's plan on a `full` lane (CI-THIRD-2) ------------------------------------

PLAN_SCHEMA = "selftest-plan/1"
PLAN_ENV = "DJB_SELFTEST_PLAN"
WHOLE = "whole"


@dataclass(frozen=True)
class SelftestPlan:
    """Which gate test modules and which rules' forms a `full` lane's selftest unit runs."""

    modules: tuple[str, ...] | None
    modules_of: int
    modules_why: str
    rules: tuple[str, ...] | None
    rules_of: int
    rules_why: str

    @property
    def narrowed(self) -> bool:
        return self.modules is not None or self.rules is not None

    def line(self) -> str:
        def field_(name: str, got: tuple[str, ...] | None) -> str:
            return f"{name}={WHOLE if got is None else ','.join(got)}"

        return f"{PLAN_SCHEMA} {field_('gate-tests', self.modules)} {field_('engine', self.rules)}"

    def lines(self) -> list[str]:
        if self.modules is None:
            tests = f"gate-tests whole — {self.modules_why}"
        else:
            first = " ".join(m.rsplit("/", 1)[-1] for m in self.modules[:3])
            more = " …" if len(self.modules) > 3 else ""
            tests = (
                f"gate-tests narrowed — {len(self.modules)} of {self.modules_of} modules selected"
                f" ({first}{more})"
            )
        if self.rules is None:
            engine = f"engine whole — {self.rules_why}"
        else:
            ids = " ".join(self.rules) or "none"
            engine = (
                f"engine narrowed — {len(self.rules)} of {self.rules_of} rules re-keyed ({ids})"
            )
        return [tests, engine, "drives whole — the one drive is never narrowed"]


def parse_plan(text: str) -> SelftestPlan:
    """The plan a `selftest-plan/1` line names; `CouldNotLook` when it is not one."""
    toks = text.strip().split(" ")
    got = dict(t.split("=", 1) for t in toks[1:] if "=" in t)
    if not toks or toks[0] != PLAN_SCHEMA or set(got) != {"gate-tests", "engine"}:
        raise CouldNotLook(f"'{text.strip()[:120]}' is not a {PLAN_SCHEMA} line")

    def members(word: str) -> tuple[str, ...] | None:
        return None if word == WHOLE else tuple(w for w in word.split(",") if w)

    modules, rules = members(got["gate-tests"]), members(got["engine"])
    return SelftestPlan(modules, len(modules or ()), "", rules, len(rules or ()), "")


def read_plan(env: Mapping[str, str] | None = None) -> SelftestPlan | None:
    """The plan `DJB_SELFTEST_PLAN` names (in `env`, else this process's), or None when unset."""
    from quality.djb import env as djb_env

    path = (djb_env.read(PLAN_ENV) if env is None else env.get(PLAN_ENV, "")) or ""
    if not path:
        return None
    try:
        return parse_plan(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise CouldNotLook(f"{PLAN_ENV}={path} could not be read ({exc})") from exc


def _map_predates(root: Path, fork: str, paths: Sequence[str]) -> str:
    """A changed non-test `quality/` module a map not stamped at the fork never saw run."""
    path = root / MAP_PATH
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        known = {f for files in doc["tests"].values() for f in files}
        stamp = str((doc.get("generated") or {}).get("tree", "")).rsplit(":", 1)[-1]
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return MAP_PATH
    if stamp and stamp == _out(root, "rev-parse", f"{fork}^{{tree}}"):
        return ""
    for p in paths:
        name = p.rsplit("/", 1)[-1]
        if p.startswith("quality/") and p.endswith(".py") and not _match(name, "test_*.py"):
            if p not in known:
                return p
    return ""


def gate_tests_plan(
    root: Path, fork: str, paths: Sequence[str]
) -> tuple[tuple[str, ...] | None, int, str]:
    """`(modules or None for whole, of how many, why)` — the diff's selection, else whole."""
    from quality.djb.legs import gate_tests

    every = gate_tests.modules(root, narrowed=False)
    shared = next((p for p in paths if _shared_gate_infra(p)), "")
    if shared:
        return None, len(every), f"{shared} is shared gate infrastructure"
    held = set(every)
    other = next((p for p in paths if p not in held), "")
    if other and not map_rows(root):
        homes = " or ".join(GATE_TESTS)
        return (
            None,
            len(every),
            f"the map has no rows for {homes} ({MAP_PATH} is the app suites' coverage;"
            f" {other} is not a gate test module, so only the whole run vouches for it)",
        )
    stale = _map_predates(root, fork, paths)
    if stale:
        return None, len(every), f"the map predates {stale} (the fold's map step re-derives it)"
    picked = tuple(m for m in touched(root, charged(root, paths, fork)) if m in held)
    if not picked:
        return None, len(every), "the diff selects no module, and an empty run vouches for none"
    return picked, len(every), ""


def _fork_blobs(root: Path, fork: str) -> dict[str, str]:
    done = _git(root, "ls-tree", "-r", "-z", "--full-tree", fork)
    if done.returncode != 0:
        raise CouldNotLook(f"git ls-tree {fork[:12]} would not answer: {done.stderr.strip()}")
    out: dict[str, str] = {}
    for entry in _z(done.stdout):
        meta, _, path = entry.partition("\t")
        if path and meta.split(" ")[1:2] == ["blob"]:
            out[path] = meta.split(" ")[2]
    return out


RuleDoc = dict[str, object]


def _rules_docs(root: Path, rev: str | None) -> tuple[RuleDoc, list[RuleDoc]]:
    """`(non-rule keys, rules)` of `rules.yaml` and the drawer at `rev` (None: the checkout)."""
    import yaml

    rest: RuleDoc = {}
    rules: list[RuleDoc] = []
    for home in ("quality/rules.yaml", "quality/local/rules.yaml"):
        if rev is None:
            text = (root / home).read_text(encoding="utf-8") if (root / home).is_file() else ""
        else:
            text = _out(root, "show", f"{rev}:{home}") or ""
        doc = yaml.safe_load(text) if text else {}
        doc = doc if isinstance(doc, dict) else {}
        rest[home] = {k: v for k, v in doc.items() if k != "rules"}
        rules += [r for r in doc.get("rules") or [] if isinstance(r, dict)]
    return rest, rules


RULE_COMPONENTS = ("scope", "walk", "reads", "doc")


def engine_plan(
    root: Path, fork: str, paths: Sequence[str]
) -> tuple[tuple[str, ...] | None, int, str]:
    """`(re-keyed rule ids or None for whole, of how many, why)` for `fork...HEAD`."""
    from quality import tree as T

    read = T.read_tree(root)
    if read.why:
        raise CouldNotLook(f"the measured tree would not read ({read.why})")
    return rekeyed_rules(
        (read.blobs, *_rules_docs(root, None)),
        (_fork_blobs(root, fork), *_rules_docs(root, fork)),
        paths,
    )


def rekeyed_rules(
    head: tuple[dict[str, str], RuleDoc, list[RuleDoc]],
    fork: tuple[dict[str, str], RuleDoc, list[RuleDoc]],
    paths: Sequence[str],
) -> tuple[tuple[str, ...] | None, int, str]:
    """Over `(blobs, non-rule keys, rules)` at each end: the rules whose memo inputs moved."""
    from quality.engine import memo

    blobs, rest, every = head
    rules = [r for r in every if r.get("enabled", True)]
    closure = set(memo.engine_closure(frozenset(blobs) | frozenset(paths)))
    hit = next((p for p in paths if p in closure), "")
    if hit:
        where = next((r for r in memo.ENGINE_CLOSURE if hit.startswith(r)), "")
        return (
            None,
            len(rules),
            f"{hit} is in the engine's closure ({where or 'reached by its code'})",
        )
    if fork[1] != rest:
        return None, len(rules), "a rules.yaml key outside `rules:` moved, and every rule reads it"
    before = {str(r.get("id")): r for r in fork[2]}
    rekeyed: list[str] = []
    for rule in rules:
        rid = str(rule.get("id"))
        old = before.get(rid)
        if old != rule:
            rekeyed.append(rid)
            continue
        now, why_now = memo.memo_components(rule, (blobs, ""))
        then, why_then = memo.memo_components(old, (fork[0], ""))
        if why_now or why_then or any(now[c] != then[c] for c in RULE_COMPONENTS):
            rekeyed.append(rid)
    return tuple(rekeyed), len(rules), ""


def selftest_plan(root: Path, fork: str, paths: Sequence[str]) -> SelftestPlan:
    """The selftest unit's plan for `fork...HEAD` (CI-THIRD-2): each member narrowed or whole."""
    modules, of, why = gate_tests_plan(root, fork, paths)
    rules, rules_of, rules_why = engine_plan(root, fork, paths)
    return SelftestPlan(modules, of, why, rules, rules_of, rules_why)


def narrowed_walls(root: Path, plan: SelftestPlan, walls: Mapping[str, float]) -> dict[str, float]:
    """The walls table with a narrowed member priced at its selection's own walls."""
    from quality.djb import ledger
    from quality.djb import registry as R
    from quality.djb.legs import gate_tests

    homes = [root / h for h in R.WALLS_HOMES]
    out = dict(walls)
    if plan.modules is not None and gate_tests.NAME in out:
        column = ledger.module_durations(homes, R._machine())
        median = sorted(column.values())[len(column) // 2] if column else 0.0
        out[gate_tests.NAME] = sum(column.get(m, median) for m in plan.modules)
    if plan.rules is not None and R.ENGINE_MEMBER in out:
        secs = ledger.rule_durations(homes, R._machine())
        median = sorted(secs.values())[len(secs) // 2] if secs else 0.0
        out[R.ENGINE_MEMBER] = secs.get(R.RULE_WHOLE, 0.0) + sum(
            secs.get(r, median) for r in plan.rules
        )
    return out


def narrowed_shards(root: Path, plan: SelftestPlan) -> int:
    """The selftest unit's CI shard count over the plan's walls (`--list-legs --ci`'s formula)."""
    from quality.djb import ledger
    from quality.djb import registry as R
    from quality.djb.legs import gate_tests

    table = R.load(root)
    members = list(table.unit("selftest")[1])
    population = [R.ENGINE_MEMBER, *(m for m in members if m != "selftest")]
    walls = narrowed_walls(root, plan, ledger.durations(root, R.CI_MACHINE, only=True))
    units = dict(table.units(root))
    if plan.modules is not None:
        units[gate_tests.NAME] = list(plan.modules)
    parts = R.member_parts([root / h for h in R.WALLS_HOMES], R.CI_MACHINE, units)
    return R.shard_count(walls, population, table.pieces(), parts)


def pytest_reach(root: Path, paths: Sequence[str]) -> tuple[str, str] | None:
    """`(path, class)` for a changed path in the app suite's closure, else None."""
    from quality import partition as P

    apps = P.platform_apps()
    classes = [
        (str(c.get("id")), pattern)
        for c in P.lockfile().get("closure_classes") or []
        for raw in c.get("members") or []
        for pattern in P._expand(str(raw), apps)
    ]
    if not classes:
        raise CouldNotLook("quality/partition.yaml declares no closure class")
    for path in paths:
        hit = next((cid for cid, pattern in classes if P._matches(path, pattern)), "")
        hit = hit or next((r for r in PYTEST_CLOSURE.roots if path.startswith(r)), "")
        if hit:
            return path, hit
    from quality import loop_key

    asked = frozenset(paths)
    for file in loop_key.reader_files(root, PYTEST_CLOSURE.quoters):
        for _, needle in loop_key.quoted_needles(_text(file), asked):
            return needle, f"quoted at {file.relative_to(root).as_posix()}"
    return None


CI_LANES = ("docs", "loop", "full")
# names, never reads: quality/ scripts/ .github/ deploy/ compose. compose/ pyproject.toml uv.lock — the forced-full list, matched against a diff; FORCED_EXEMPT's walls tables excepted; no migration: its checks are static legs (migrations, rules 6 and 22), never narrowed  # noqa: E501
FORCED_FULL = (
    "quality/",
    "scripts/",
    ".github/",
    "deploy/",
    "compose.",
    "compose/",
    "pyproject.toml",
    "uv.lock",
)
#: The fold's CI walls tables, never forced: always-on and the shard count read them as prices.
FORCED_EXEMPT = (
    "scripts/gate_member_durations.json",
    "scripts/local/gate_member_durations.ci.json",
)
#: The files a product diff writes by derivation: never forced, never charged (rule 94).
PRODUCT_DERIVED = (
    "frontend/openapi.json",
    "frontend/src/api/generated/schema.d.ts",
    "apps/*/migrations/*.py",
    "apps/*/migrations/max_migration.txt",
    "apps/*/tests/*authz_baseline.json",
)
ROW_DERIVED = ("quality/budgets.yaml",)
#: A product's own drawer, scripts and decision page: never forced; the template's examples are.
PRODUCT_DRAWER = (
    "quality/local/",
    "scripts/local/",
    "apps/conftest_local.py",
    "docs/product/architecture.md",
)
_ROW_KEY = re.compile(r"^  (\S+?):(?:\s|$)")
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
SUPPLY_CHAIN_READS = ("frontend/package.json", "frontend/pnpm-lock.yaml")
LOOP_UNITS = ("static", "full-house-rules", "pytest-x2")
PYTEST_UNIT = LOOP_UNITS[2]
#: What each lane's CI rows run, as the run header prints it.
LANE_RUNS = {
    "docs": "nothing — derive, verdict and gate-verdict only: no row, no image",
    "loop": (
        "static and full-house-rules whole, pytest-x2 narrowed by `--pr --base` to the scope"
        " below, the selftest unit as ONE row running the harness selection alone (no engine"
        " selftest, no drive), supply-chain only when the diff touches a manifest it reads —"
        " the `units:` line names the rows"
    ),
    "full": "every unit `--list-legs --ci` lists, whole — no row is narrowed",
    "full-narrowed": (
        "every unit `--list-legs --ci` lists, whole but the selftest unit, which runs its plan"
        " below over its own shard count — the `units:` line names them"
    ),
    "full-withheld": (
        "every unit `--list-legs --ci` lists but the selftest unit, which is withheld; each row"
        " that runs is whole — the `units:` line names them"
    ),
}


@dataclass(frozen=True)
class Closure:
    """The selftest unit's input closure: the roots it reads, and the homes whose quotes add."""

    roots: tuple[str, ...]
    quoters: tuple[str, ...]


#: The selftest closure (ADR gate-1), roots + quoted paths. DOES NOT COVER glob or built reads.
SELFTEST_CLOSURE = Closure(
    roots=(*FORCED_FULL, "config/", "templates/", "pilecap/"),
    quoters=("quality/tests", "quality/canary", "quality/negative", "quality/djb"),
)


#: The app suite's closure past the lockfile's classes (CI-THIRD-3): the facade, and quotes.
PYTEST_CLOSURE = Closure(roots=("pilecap/",), quoters=("apps", "config"))


def selftest_reach(root: Path, paths: Sequence[str]) -> tuple[str, str] | None:
    """`(path, root or quoting file)` for a changed path in the selftest closure, else None."""
    for path in paths:
        hit = next((r for r in SELFTEST_CLOSURE.roots if path.startswith(r)), "")
        if hit and path not in FORCED_EXEMPT:
            return path, hit
    asked = frozenset(p for p in paths if p not in FORCED_EXEMPT)
    if not asked:
        return None
    from quality import loop_key

    mark = loop_key.decider_value(NONREAD_NAME, HOME)
    for file in loop_key.reader_files(root, SELFTEST_CLOSURE.quoters):
        text = _text(file)
        declared: list[tuple[int, str]] | None = None
        for _, needle in loop_key.quoted_needles(text, asked):
            declared = loop_key.declarations(text, mark) if declared is None else declared
            if not any(word == needle for _, word in declared):
                return needle, file.relative_to(root).as_posix()
    return None


def ci_units(root: Path) -> list[str]:
    """The unit names `--list-legs --ci` lists for this checkout, in order."""
    from quality.djb import registry as R

    try:
        return [unit.name for unit, _ in R.load(root).rows]
    except R.RegistryError as exc:
        raise CouldNotLook(f"the gate's units could not be listed ({exc})") from exc


def forced_by(path: str) -> str:
    """The forced-full root prefix `path` falls under, or `""`."""
    if path in FORCED_EXEMPT:
        return ""
    return next((name for name in FORCED_FULL if path.startswith(name)), "")


def _row_keys(text: str) -> list[str]:
    out: list[str] = []
    key = ""
    for line in text.splitlines():
        found = _ROW_KEY.match(line)
        if found and not line.lstrip().startswith("#"):
            key = found.group(1)
        elif not line.strip() or not line.startswith(" "):
            key = ""
        out.append(key)
    return out


def _row_is_product(key: str, platform: Sequence[str]) -> bool:
    from quality.engine.run import EXAMPLE_BUDGET_APPS

    return bool(product_root(key, platform)) or key.startswith(EXAMPLE_BUDGET_APPS)


def row_derived(root: Path, path: str, fork: str) -> bool:
    """Whether every line `path` changed since `fork` sits in a product app's or example's row."""
    if path not in ROW_DERIVED or not fork:
        return False
    done = _git(root, "diff", "-U0", "--no-color", fork, "--", path)
    shown = _git(root, "show", f"{fork}:{path}")
    if done.returncode != 0 or shown.returncode != 0 or not (root / path).is_file():
        return False
    before, after = _row_keys(shown.stdout), _row_keys(_lines_text(root / path))
    platform = platform_apps(root)
    keys: list[str] = []
    for line in done.stdout.splitlines():
        hunk = _HUNK.match(line)
        if not hunk:
            continue
        old, olds, new, news = (int(g) if g is not None else 1 for g in hunk.groups())
        keys += before[old - 1 : old - 1 + olds] + after[new - 1 : new - 1 + news]
    return bool(keys) and all(k and _row_is_product(k, platform) for k in keys)


def charged(root: Path, paths: Sequence[str], fork: str) -> list[str]:
    """`paths` less each per-app table whose diff since `fork` touches product rows alone."""
    return [p for p in paths if not row_derived(root, p, fork)]


def _minutes(seconds: Sequence[float | None]) -> str:
    known = [s for s in seconds if s is not None]
    if seconds and not known:
        return "?"
    return f"{round(sum(known) / 60, 1):g}{'+?' if len(known) < len(seconds) else ''}"


@dataclass
class Tax:
    """The members a diff selected and did not own, with each one's recorded seconds or None."""

    members: dict[str, float | None] = field(default_factory=dict)
    whole: dict[str, list[float | None]] = field(default_factory=dict)

    @property
    def line(self) -> str:
        """`tax: <N> min in <M> member(s) the diff did not own — <names>; whole: …` (D1)."""
        names = " ".join(f"{m}({_minutes([s])})" for m, s in self.members.items())
        whole = " ".join(f"{u} {_minutes(s)} min" for u, s in self.whole.items())
        return (
            f"tax: {_minutes(list(self.members.values()))} min in {len(self.members)} member(s)"
            f" the diff did not own — {names or 'none'}; whole: {whole or '?'}"
            " (reported, never asserted)"
        )


def _whole_walls(root: Path, machine: str, homes: Sequence[Path]) -> dict[str, list[float | None]]:
    from quality.djb import ledger
    from quality.djb import registry as R

    walls = ledger.durations(root, machine, homes=list(homes), say=lambda line: None)
    try:
        static = [m for u, ms in R.load(root).rows if u.name == "static" for m in ms]
    except (R.RegistryError, CouldNotLook, ImportError, OSError):
        return {"static": [None], "fe": [None]}
    seconds = {m: None if walls.get(m) is None else float(walls[m]) for m in static}
    return {"static": [s for m, s in seconds.items() if m != "fe"], "fe": [seconds.get("fe")]}


def tax_line(root: Path, paths: Sequence[str]) -> str:
    """`tax(...).line`, or the reason it could not be priced — a price never refuses a scope."""
    try:
        return tax(root, paths).line
    except CouldNotLook as exc:
        return f"tax: ? — could not price this diff ({exc})"


def tax(root: Path, paths: Sequence[str]) -> Tax:
    """The tax a diff pays: its unowned harness modules, priced from the walls table."""
    from quality.djb import ledger
    from quality.djb import registry as R

    machine = R._machine()
    homes = [root / h for h in R.WALLS_HOMES]
    seconds = ledger.module_durations(homes, machine)
    out = Tax()
    for module in selection(root, paths).unowned:
        out.members[module] = seconds.get(module)
    out.whole = _whole_walls(root, machine, homes)
    return out


@dataclass
class Lane:
    """One CI lane decision: the word, why, the diff it read and the loop scope it agrees with."""

    word: str
    reason: str
    base: str
    head: str
    paths: list[str] = field(default_factory=list)
    forced: list[tuple[str, str]] = field(default_factory=list)
    readers: list[str] = field(default_factory=list)
    scope: Scope | None = None
    units: list[str] = field(default_factory=list)
    harness: list[str] = field(default_factory=list)
    selftest: str = ""
    selftest_why: str = ""
    plan: SelftestPlan | None = None
    planned: bool = False
    pytest: str = ""
    pytest_why: str = ""

    def judge_selftest(self, root: Path) -> None:
        """Set `selftest` ran or withheld; a withheld `full` lane lists every other unit."""
        reach = selftest_reach(root, self.paths)
        if reach is not None:
            self.selftest, self.selftest_why = "ran", f"{reach[0]} is in the closure ({reach[1]})"
            self.plan_selftest(root)
            return
        self.selftest = "withheld"
        self.selftest_why = (
            f"none of the {len(self.paths)} changed path(s) is in the selftest closure"
        )
        self.units = [u for u in ci_units(root) if u != "selftest"]

    def plan_selftest(self, root: Path) -> None:
        """A `ran` unit's plan: `narrowed`, with its own shard count, when it narrows."""
        if not self.planned:
            return
        self.plan = selftest_plan(root, self.base, self.paths)
        if not self.plan.narrowed:
            return
        n = narrowed_shards(root, self.plan)
        self.selftest = "narrowed"
        self.selftest_why += f"; it runs what the diff reaches, {n} shard(s)"
        self.units = [f"selftest:{n}" if u == "selftest" else u for u in ci_units(root)]

    def plan_pytest(self, root: Path) -> None:
        """pytest-x2 on a `full` lane: `narrowed` to the row's `--pr` scope off the closure."""
        if not self.planned:
            return
        reach = pytest_reach(root, self.paths)
        if reach is not None:
            self.pytest = "whole"
            self.pytest_why = f"{reach[0]} is in the app suite's closure ({reach[1]})"
            return
        self.pytest = "narrowed"
        self.pytest_why = (
            f"none of the {len(self.paths)} changed path(s) is in the app suite's closure; the"
            " row runs the loop's own `--pr` scope"
        )
        units = self.units or ci_units(root)
        self.units = [f"{u}:pr" if u == PYTEST_UNIT else u for u in units]


def lane(root: Path, base: str, head: str, *, plan: bool = False) -> Lane:
    """The CI lane for `base...head` over this checkout: forced `full`, `docs`, else the loop's."""
    here = _out(root, "rev-parse", "-q", "--verify", "HEAD") or ""
    sha = _out(root, "rev-parse", "-q", "--verify", f"{head}^{{commit}}") or ""
    if not sha or sha != here:
        raise CouldNotLook(
            f"--head {head} is not this checkout's HEAD ({here[:12] or 'unborn'}) — the lane"
            " reads the checkout's own tree, the one --loop would measure; check the head out"
        )
    known = _out(root, "rev-parse", "-q", "--verify", f"{base}^{{commit}}")
    fork = _out(root, "merge-base", "HEAD", base) if known else ""
    if not fork:
        raise CouldNotLook(f"--base {base} names no commit this checkout shares a history with")
    from quality.djb import ledger

    paths = ledger.changed_between(root, fork, "HEAD")
    paths += [p for p in _z(_git(root, "diff", "--name-only", "-z", "HEAD").stdout) if p]
    paths = sorted(set(paths))
    out = Lane("full", "", fork, sha, paths, planned=plan)
    drawer = PRODUCT_DRAWER if product_namespace(root) is not None else None
    out.forced = [
        (p, forced_by(p))
        for p in charged(root, paths, fork)
        if forced_by(p) and not (drawer and p.startswith(drawer))
    ]
    if out.forced:
        out.reason = (
            f"the diff touches {len(out.forced)} path(s) the forced-full list names — the gate,"
            " the engine, the workflow, deploy, the stack or the dependencies"
        )
        path, pattern = out.forced[0]
        out.selftest, out.selftest_why = "ran", f"{path} is in the closure ({pattern})"
        out.plan_selftest(root)
        out.plan_pytest(root)
        return out
    platform = platform_apps(root)
    gone = [p for p in paths if not (root / p).is_file() and not product_root(p, platform)]
    admitted = all(ledger.docs_only_admits(p, fork, "HEAD", root=root, home=HOME) for p in paths)
    if gone and not admitted:
        out.reason = (
            f"the diff deletes {len(gone)} path(s) outside the docs-only list, and the loop's"
            f" changed-file reader never sees a deletion: {' '.join(gone[:3])}"
        )
        out.judge_selftest(root)
        return out
    derived = derive(root, base_ref=base, asked_impact=True)
    out.scope = derived
    declaring = tuple(f"{one}/" for one in ledger.DOCS_ONLY_DECLARING_ROOTS)
    out.readers = [u for u in derived.literal_unselected if not u.startswith(declaring)]
    quoted = [u for u in derived.literal_unselected if u.startswith(declaring)]
    if admitted and not derived.literal_tests and not quoted:
        out.word = "docs"
        out.reason = (
            f"the docs-only list admits every one of the {len(paths)} changed path(s) and no"
            " module under apps/ or config/ quotes one (the docs-only road's own refusal)"
        )
    elif derived.mode == "full":
        out.reason = f"the loop's own scope is the whole suite: {derived.reason}"
        out.judge_selftest(root)
        out.plan_pytest(root)
    else:
        out.word = "loop"
        out.reason = (
            "no forced path, and not wholly documentation — the loop's own scope, below"
            if not admitted
            else "every path is admitted, and a module under apps/ or config/ quotes one — the"
            " loop runs its reader"
        )
        from quality.djb.legs import always_on

        harness = touched(root, charged(root, paths, fork))
        out.harness = [m for m in harness if m != always_on.RUNNER]
        out.units = list(LOOP_UNITS)
        if out.harness:
            out.units.append("selftest:1")
        if any(p in SUPPLY_CHAIN_READS for p in paths):
            out.units.append("supply-chain")
    return out


def lane_main(argv: Sequence[str]) -> int:
    """`lane --base B --head H [--root R]`: the word on line one, then why and what it runs."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m quality.djb.scope lane")
    parser.add_argument("--root", default=".")
    parser.add_argument("--base", required=True, help="the proposed change's base commit")
    parser.add_argument("--head", required=True, help="the commit this checkout holds")
    parser.add_argument("--plan", action="store_true", help="plan the selftest unit (the venv's)")
    args = parser.parse_args(argv)
    try:
        picked = lane(Path(args.root).resolve(), args.base, args.head, plan=args.plan)
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))
    print(picked.word)
    print(f"  lane:       {picked.word} — {picked.reason}")
    print(f"  diff:       {picked.base[:12]}...{picked.head[:12]}, {len(picked.paths)} path(s)")
    if picked.selftest:
        print(f"  selftest:  {picked.selftest} — {picked.selftest_why}")
    for line in picked.plan.lines() if picked.plan is not None else ():
        print(f"  selftest:  {line}")
    if picked.plan is not None and picked.plan.narrowed:
        print(f"  plan:       {picked.plan.line()}")
    if picked.pytest:
        print(f"  {PYTEST_UNIT}: {picked.pytest} — {picked.pytest_why}")
    for path, pattern in picked.forced:
        print(f"  forced:     {path} ({pattern})")
    runs = picked.word
    if picked.word == "full" and picked.selftest in ("withheld", "narrowed"):
        runs = f"full-{picked.selftest}"
    print(f"  runs:       {LANE_RUNS[runs]}")
    if picked.word == "full" and picked.units:
        print(f"  units:      {' '.join(picked.units)}")
    if picked.word == "loop":
        print(f"  units:      {' '.join(picked.units)}")
        print(f"  harness:    {' '.join(picked.harness) or '-'}")
    if picked.word == "docs" and picked.readers:
        print(
            f"  readers:    {len(picked.readers)} quote(s) outside apps/ and config/ this lane"
            f" runs none of: {' '.join(picked.readers)}"
        )
    if picked.scope is not None:
        for line in banner(picked.scope):
            print(line)
        print(f"  scope=      {picked.scope.canonical}")
    return 0


PLATFORM_UNITS = ("selftest", "supply-chain")


def _probe(glob: str) -> str:
    return glob.replace("*", PROBE_APP, 1).replace("*", "zzz_probe")


def _gate_module(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return (
        any(path.startswith(f"{home}/") for home in GATE_TESTS)
        and _match(name, "test_*.py")
        and "/fixtures/" not in path
    )


@dataclass
class ProductCensus:
    """Rule 94's census: the counts it read and one `(path, class, sentence)` per finding."""

    counts: dict[str, int] = field(default_factory=dict)
    findings: list[tuple[str, str, str]] = field(default_factory=list)


def product_census(root: Path) -> ProductCensus:
    """Every product path forces nothing and selects only the members that own it (rule 94)."""
    out = ProductCensus()
    listed = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listed.returncode != 0:
        raise CouldNotLook(f"rule 94 could not list the tree: {listed.stderr.strip()}")
    tree = sorted(set(_z(listed.stdout)))
    platform = platform_apps(root)
    decls = declarations(root, [p for p in tree if _gate_module(p)])
    probes = [f"apps/{PROBE_APP}/services.py"]
    probes += [_probe(g) for g in PRODUCT_DERIVED if g.startswith("apps/")]
    paths = sorted({*(p for p in tree if is_product_path(p, platform)), *probes})
    out.counts = {"gate_modules_read": len(decls), "probe_paths": len(probes)}
    out.counts["product_paths_read"] = len(paths)
    out.counts["frontend_paths_priced"] = 0
    for path in paths:
        forced = forced_by(path)
        if forced:
            out.findings.append(
                (path, "forced", f"{path} is a product path and forces the full lane ({forced})")
            )
        if product_root(path, platform) == "frontend/":
            out.counts["frontend_paths_priced"] += 1
            continue
        chosen = selection(root, [path], decls)
        for module in chosen.unowned:
            out.findings.append(
                (
                    module,
                    "unowned",
                    f"{path} is a product path and selects {module} by"
                    f" {' '.join(chosen.why[module])} — a platform member it does not own;"
                    " narrow the module's declaration to the paths it reads",
                )
            )
    for unit in PLATFORM_UNITS:
        if any(word.split(":", 1)[0] == unit for word in LOOP_UNITS):
            out.findings.append(
                ("quality/djb/scope.py", "lane", f"the loop lane runs the {unit} unit whole")
            )
    return out


def product_census_main(argv: Sequence[str]) -> int:
    """`product-census [--root R]`: `count <key> <n>` and `finding <path>\t<class>\t<why>`."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m quality.djb.scope product-census")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    try:
        census_ = product_census(Path(args.root).resolve())
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))
    for key, n in census_.counts.items():
        print(f"count {key} {n}")
    for path, klass, why in census_.findings:
        print(f"finding {path}\t{klass}\t{why}")
    return 0


def classify_main(argv: Sequence[str]) -> int:
    """`classify [--root R] <path>…`: each fan-out row on stdout; exit 2 on an unclassified path."""
    import argparse

    parser = argparse.ArgumentParser(prog="python -m quality.djb.scope classify")
    parser.add_argument("--root", default=".")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    for path in args.paths:
        try:
            print(classify(path, root))
        except Unclassified as exc:
            print(exc, file=sys.stderr)
            return 2
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Print the scope block, the canonical scope and the pytest flags for this checkout."""
    import argparse

    words = list(sys.argv[1:] if argv is None else argv)
    if words[:1] == ["classify"]:
        return classify_main(words[1:])
    if words[:1] == ["consumers"]:
        return consumers_main(words[1:])
    if words[:1] == ["lane"]:
        return lane_main(words[1:])
    if words[:1] == ["product-census"]:
        return product_census_main(words[1:])
    parser = argparse.ArgumentParser(prog="python -m quality.djb.scope")
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--base", default=None, help="the fork point's ref (default refs/heads/main)"
    )
    parser.add_argument("--carried", default=None, help="a fork point carried to a collapsed clone")
    parser.add_argument("--also", default="", help="app labels the caller adds to the seeds")
    parser.add_argument("--mine", action="store_true")
    parser.add_argument("--impact", action="store_true", help="consult the test-impact map")
    parser.add_argument("--no-impact", action="store_true", help="the map is bypassed and keyed so")
    parser.add_argument("--scan", type=int, default=MAP_SCAN)
    parser.add_argument("--touched", action="store_true", help="the gate tests the change selects")
    parser.add_argument("--census", action="store_true", help="the gate tests' selection census")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.census or args.touched:
        try:
            if args.census:
                findings = census(root)
                for line in findings:
                    print(f"  touched census: {line}")
                if findings:
                    exit_could_not_look(f"{len(findings)} gate test module finding(s) above")
                print(
                    f"  touched census: {len(gate_test_modules(root))} module(s), each selectable"
                )
                return 0
            for module in touched(root, changed_files(root, args.base, args.carried).paths):
                print(f"  touched     {module}")
        except CouldNotLook as exc:
            exit_could_not_look(str(exc))
        return 0
    try:
        scope = derive(
            root,
            base_ref=args.base,
            carried=args.carried,
            mine=args.mine,
            asked_impact=args.impact,
            also=args.also,
            no_impact=args.no_impact,
            scan=args.scan,
        )
    except CouldNotLook as exc:
        exit_could_not_look(str(exc))
    for line in banner(scope):
        print(line)
    print(f"  scope=      {scope.canonical}")
    for arg in pytest_args(scope):
        print(f"  arg         {arg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
