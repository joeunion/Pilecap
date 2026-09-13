"""The platform partition: its input closure, its skip key, and its canaries.

**The design is `docs/product/partition-closure.md` and it is the authority.**
This module is that design executed; every section reference below (§2, §3, §4,
§5, §6, §7, §8) is a section of that file, and a disagreement between the two is
a finding about this module.

WHAT IT BUYS. A cloned product pays the platform's whole pytest suite on every
full gate, forever, even when nothing it did could have changed a platform
verdict. The dividend: **the platform portion of the pytest suite is skipped
when a banked green verdict exists whose key still matches everything that
portion reads.** Product tests always run. The house-rules legs always run over
the whole tree — the partition is the pytest suite only.

THE KEY HAS TWO PARTS AND BOTH MUST MATCH (§4):

  1. **the closure hash** — SHA-256 over the sorted `(path, blob-hash)` pairs of
     every file the closure classes match (`quality/partition.yaml` §3). Any
     in-closure edit moves it.
  2. **the discovery digest** — a canonical serialization, hashed, of every
     discovered population, read through the same walks the platform reads them
     and serialized from the LOADED REGISTRY. proved the closure's
     files are not the partition's whole input: platform behaviour reaches
     through discovery — `INSTALLED_APPS` from the `apps/*` walk, the mounts
     walking every app's `api.py`/`mcp.py`, the search registry, lifecycle,
     integrations, SCHEDULES — so platform tests quantified over those
     populations change outcome while no closure file changes.

WHY THE DIGEST IS NOT A LIST OF CONVENTIONAL FILENAMES (§9's rejected
alternative, kept where it is implemented): a file-name list re-derives by hand
what discovery already derives, and goes stale the day a new seam lands. The
digest reads the population, not the files.

EXIT SEMANTICS, INHERITED WHOLE (§4): **0 skip-or-green · 1 violations · 2
enforcement broken.** Exit 2, specifically: an unmatchable closure class, an
unreadable closure member, a lockfile app the registry cannot find, a digest
section that cannot serialize, a canary that fails to fire, a ledger row whose
key cannot be parsed. 2 outranks a pass, and a mistyped invocation is never a
silent full run.

THE LEDGER IS `scripts/gate_ledger.sh`'S, one more consumer of the same pattern
(§4). It is not reimplemented here: this module shells into those functions, so
the verdict semantics have one home and the canaries forge rows through the same
seam a real run banks through.

WHAT THIS MODULE DOES NOT COVER is declared in `quality/partition.yaml` under
`does_not_cover`, read by `selftest` and printed, so the blind spots are said
out loud on the run that uses them rather than only in a design file.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
LOCKFILE_PATH = ROOT / "quality" / "partition.yaml"
GATE_LEDGER = ROOT / "scripts" / "gate_ledger.sh"

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_BROKEN = 2

# : The env var the digest subprocess reads to find a planted app's PARENT
# : directory, and the label to install. Only the canary sets it; a real run
# : never does. Two variables rather than one path so nothing has to parse a
# : path back into a package name.
PLANT_DIR_ENV = "DJB_PARTITION_PLANT_DIR"
PLANT_LABEL_ENV = "DJB_PARTITION_PLANT_LABEL"

# : Points the ledger at a scratch file. The canary's forge sets it; a real run
# : never does, so a forged row can never be mistaken for a banked verdict.
LEDGER_OVERRIDE_ENV = "DJB_PARTITION_LEDGER"


class Broken(Exception):
    """Enforcement is broken — exit 2. Never a finding about the tree."""


class Violation(Exception):
    """A finding about the tree — exit 1."""


# --- the lockfile -------------------------------------------------------------


def lockfile() -> dict[str, Any]:
    """The written-down record (§2). Absent is exit 2, naming it.

    A partition tool with no lockfile does not fall back to a live derivation:
    that is the alternative §2 rejects on principle, and doing it silently when
    the file is missing would be doing it in the one situation nobody is
    looking.
    """
    if not LOCKFILE_PATH.exists():
        raise Broken(
            f"the partition lockfile is missing: {LOCKFILE_PATH.relative_to(ROOT)}. "
            "The platform set is a written-down record, not a live derivation "
            "(partition-closure.md §2) — there is nothing to fall back to, and "
            "falling back would mean a clone calling its own apps platform."
        )
    try:
        loaded = yaml.safe_load(LOCKFILE_PATH.read_text())
    except yaml.YAMLError as error:  # pragma: no cover - a broken file is exit 2
        raise Broken(f"the partition lockfile does not parse: {error}") from error
    if not isinstance(loaded, dict):
        raise Broken("the partition lockfile is not a mapping")
    return loaded


def platform_apps() -> tuple[str, ...]:
    """The app labels inside the partition, sorted. The §2 boundary."""
    named = lockfile().get("platform_apps") or []
    if not named:
        raise Broken("the lockfile names no platform apps — the closure would be empty")
    return tuple(sorted(str(label) for label in named))


def exclusions() -> tuple[str, ...]:
    """The enumerated exclusions (§3). One today; a second is a design change."""
    return tuple(sorted(str(entry["path"]) for entry in (lockfile().get("exclusions") or [])))


def always_run() -> tuple[str, ...]:
    """The four frozen nets (§7), in declaration order — they run every time."""
    return tuple(str(entry["path"]) for entry in (lockfile().get("always_run") or []))


def tolerated_environment() -> frozenset[str]:
    """Env names whose value provably cannot change a verdict about code (§3)."""
    declared = (lockfile().get("environment") or {}).get("tolerated") or []
    return frozenset(str(entry["name"]) for entry in declared)


# --- the tree -----------------------------------------------------------------


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise Broken(f"`git {' '.join(args)}` failed: {result.stderr.strip()}")
    return result.stdout


def tree_paths() -> tuple[str, ...]:
    """Every path the gate can read: tracked, plus untracked-non-ignored.

    The same population `gate_measured_tree` keys on (`git add -A` honours
    `.gitignore`), so "the content the gate can read" rather than "the content
    plus every build artefact" — and a brand-new, not-yet-committed platform
    test file is IN the closure, which is the direction that has to be right.
    """
    tracked = _git("ls-files", "-z").split("\0")
    untracked = _git("ls-files", "--others", "--exclude-standard", "-z").split("\0")
    return tuple(sorted({path for path in (*tracked, *untracked) if path}))


def _expand(pattern: str, apps: Sequence[str]) -> list[str]:
    """`apps/{app}/**` over the lockfile's apps; everything else, as written."""
    if "{app}" in pattern:
        return [pattern.replace("{app}", app) for app in apps]
    return [pattern]


def _matches(path: str, pattern: str) -> bool:
    """Two shapes only: a directory subtree (`x/**`) and an exact path.

    Deliberately not `fnmatch`: a partial glob language is a language somebody
    writes a pattern in that means something slightly different from what they
    read, and the closure is not a place for that.
    """
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-2])
    return path == pattern


def closure_members() -> dict[str, tuple[str, ...]]:
    """Every closure class's members, derived by glob at hash time (§3).

    A class that matches NOTHING is exit 2 by name, and a member the exclusion
    list names is dropped — the closure never silently narrows and never
    silently widens.
    """
    lock = lockfile()
    apps = platform_apps()
    excluded = set(exclusions())
    paths = tree_paths()
    classes = lock.get("closure_classes") or []
    if not classes:
        raise Broken("the lockfile enumerates no closure classes")

    collected: dict[str, tuple[str, ...]] = {}
    for entry in classes:
        identifier = str(entry.get("id") or "?")
        patterns = [
            expanded
            for pattern in (entry.get("members") or [])
            for expanded in _expand(str(pattern), apps)
        ]
        members = sorted(
            {
                path
                for path in paths
                if path not in excluded and any(_matches(path, p) for p in patterns)
            }
        )
        if not members:
            raise Broken(
                f"closure class {identifier} ({entry.get('what')}) matches no file in "
                f"this tree. An enumerated class that matches nothing is exit 2: the "
                f"closure would have silently narrowed. Patterns: {patterns}"
            )
        collected[identifier] = tuple(members)
    return collected


def closure_hash(*, overrides: Mapping[str, bytes] | None = None) -> str:
    """Part 1 of the key: SHA-256 over sorted `(path, content-hash)` pairs (§4).

    `overrides` is how the born-with canary perturbs a member without touching
    the working tree (§8.1): an overlay in memory, never a write.

    A member that cannot be read is exit 2 — a closure that could not read one
    of its own inputs may not bank a verdict about it.
    """
    supplied = dict(overrides or {})
    digest = hashlib.sha256()
    for identifier, members in sorted(closure_members().items()):
        for path in members:
            if path in supplied:
                content = supplied[path]
            else:
                try:
                    content = (ROOT / path).read_bytes()
                except OSError as error:
                    raise Broken(
                        f"closure member {path} (class {identifier}) cannot be read: "
                        f"{error}. A closure that cannot read an input may not bank a "
                        "verdict about it."
                    ) from error
            digest.update(path.encode())
            digest.update(b"\0")
            digest.update(hashlib.sha256(content).hexdigest().encode())
            digest.update(b"\n")
    return digest.hexdigest()


# --- part 2: the discovery digest ---------------------------------------------
#
# THE SECTIONS ARE THE SEAM CENSUS (§4). Each is serialized on its own and
# hashed on its own, so a digest that moved can NAME the population that moved
# and the plant canary can say which section failed to see a plant — the build's
# own blind-spot note asks for exactly that.


def _canonical(value: Any) -> str:
    """One serialization, everywhere: sorted keys, no ambiguity, no repr luck.

    `default=str` is the honest fallback for a value that is not JSON — a
    function object in a `ScheduleDeclaration`, a model class in a `Searchable`
    — and every such value is one whose `str()` is its dotted identity rather
    than its address, EXCEPT bare functions, whose `repr` carries an address.
    Those are reduced to their qualified name before they get here.
    """
    return json.dumps(value, sort_keys=True, ensure_ascii=True, default=str)


def _named(value: Any) -> Any:
    """A value's stable identity: a callable becomes its dotted name.

    Without this a `ScheduleDeclaration`'s function fields serialize as
    `<function probe_schedule at 0x1155ef560>` and the digest changes on every
    interpreter start — the exact "repr details that vary within one tree state"
    the design's blind-spot list warns the build about.
    """
    if callable(value) and hasattr(value, "__qualname__"):
        return f"{getattr(value, '__module__', '?')}.{value.__qualname__}"
    if isinstance(value, (list, tuple)):
        return [_named(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _named(item) for key, item in sorted(value.items())}
    return value


def _digest_sections_in_process() -> dict[str, Any]:
    """Serialize every discovered population, from the LOADED registry.

    Runs inside the digest subprocess, after `django.setup()`. Every section
    that raises is exit 2 naming the section: a digest that cannot serialize a
    population it claims to cover has not covered it.
    """
    from django.apps import apps as django_apps

    sections: dict[str, Any] = {}

    def take(name: str, produce: Any) -> None:
        try:
            sections[name] = _named(produce())
        except Exception as error:  # noqa: BLE001 - any failure here is exit 2
            raise Broken(
                f"digest section {name!r} could not serialize: {type(error).__name__}: {error}"
            ) from error

    def _apps() -> Any:
        return sorted(
            [
                str(config.label),
                str(config.name),
                sorted(str(item) for item in (getattr(config, "depends_on", ()) or ())),
                bool(getattr(config, "optional", False)),
            ]
            for config in django_apps.get_app_configs()
        )

    def _rest() -> Any:
        from config.api import api

        return api.get_openapi_schema()

    def _mcp() -> Any:
        from config.mcp import build_server

        return sorted(
            [tool.name, tool.description, tool.parameters, tool.output_schema]
            for tool in build_server()._tool_manager.list_tools()
        )

    def _models() -> Any:
        from apps.core.models import InheritedDownward, OrgScopedModel, TenantScopedModel

        found = []
        for model in django_apps.get_models(include_auto_created=True):
            meta = model._meta
            found.append(
                [
                    str(meta.label),
                    sorted(
                        [
                            field.name,
                            field.get_internal_type(),
                            bool(field.null),
                            bool(field.unique),
                        ]
                        for field in meta.concrete_fields
                    ),
                    "org"
                    if issubclass(model, OrgScopedModel)
                    else "tenant"
                    if issubclass(model, TenantScopedModel)
                    else "base",
                    bool(getattr(model, "append_only", False)),
                    getattr(model, "derive_org_from", None),
                    issubclass(model, InheritedDownward),
                ]
            )
        return sorted(found)

    def _events() -> Any:
        import importlib
        import importlib.util

        found = []
        for config in django_apps.get_app_configs():
            if not config.name.startswith("apps."):
                continue
            module_name = f"{config.name}.events"
            if importlib.util.find_spec(module_name) is None:
                continue
            module = importlib.import_module(module_name)
            for attribute in sorted(dir(module)):
                if attribute.startswith("_") or not attribute.isupper():
                    continue
                value = getattr(module, attribute)
                if isinstance(value, str):
                    found.append([str(config.label), attribute, value])
        return sorted(found)

    def _search() -> Any:
        from apps.search.registry import declarations

        return sorted(
            [
                str(declaration.model._meta.label),
                declaration.label,
                [list(pair) for pair in declaration.fields],
                sorted(declaration.refresh_on),
                declaration.display,
            ]
            for declaration in declarations()
        )

    def _lifecycle() -> Any:
        from apps.core.lifecycle import declared_lifecycles, population_sources

        return {
            "declared": {
                label: [
                    str(lifecycle.kind),
                    str(lifecycle.reason),
                    str(lifecycle.trigger),
                    str(lifecycle.purged_by),
                ]
                for label, lifecycle in sorted(declared_lifecycles().items())
            },
            "sources": dict(sorted(population_sources().items())),
        }

    def _integrations() -> Any:
        from apps.core.integrations import census

        # The declared POPULATION, not its live status. `status`, `detail` and
        # `remedy` are what the probes found on THIS machine a moment ago —
        # putting them in the key would make an unconfigured Meilisearch move
        # the digest and re-run the platform suite for a reason no tree change
        # caused. What the partition needs to see is that an integration
        # ARRIVED or LEFT, which is `key`, `title`, who declared it, and whether
        # it claims a live probe.
        taken = census()
        return {
            "integrations": sorted(
                [
                    str(integration.key),
                    str(integration.title),
                    str(integration.declared_by),
                    str(integration.probe),
                ]
                for integration in taken.integrations
            ),
            "seams": sorted(str(seam.module) for seam in taken.unreadable),
        }

    def _schedules() -> Any:
        from apps.workflows.client import discovered_schedules

        return sorted(
            [
                declaration.name,
                declaration.log_prefix,
                sorted(declaration.legacy_ids),
            ]
            for declaration in discovered_schedules()
        )

    def _scope_families() -> Any:
        from apps.core.api.scopes import FROZEN_FAMILIES, SANCTIONED_RENAMES, families

        return {
            "live": sorted(families()),
            "frozen": sorted(FROZEN_FAMILIES),
            "renames": {key: sorted(value) for key, value in sorted(SANCTIONED_RENAMES.items())},
        }

    def _policies() -> Any:
        from apps.core.authz import action_prose, policies

        return {
            "policies": {action: predicate for action, predicate in sorted(policies().items())},
            "prose": sorted(action_prose()),
        }

    def _meters() -> Any:
        from apps.usage.meters import declared_meters

        return {label: sorted(names) for label, names in sorted(declared_meters().items())}

    def _sockets() -> Any:
        from config.asgi import discovered_websocket_urlpatterns

        return sorted(
            [str(pattern.pattern), str(pattern.name or "")]
            for pattern in discovered_websocket_urlpatterns()
        )

    take("apps", _apps)
    take("rest", _rest)
    take("mcp", _mcp)
    take("models", _models)
    take("events", _events)
    take("search", _search)
    take("lifecycle", _lifecycle)
    take("integrations", _integrations)
    take("schedules", _schedules)
    take("scope_families", _scope_families)
    # The three sections the AST seam census produced on its FIRST RUN, which is
    # the mechanism §4 built it for: "a future discovery seam joins the digest in
    # the commit that lands it or the gate says so". The design's §4 table names
    # ten; the census found thirteen walking modules and three walked populations
    # no section covered — `policies.py` (apps.core.authz), `meters.py`
    # (apps.usage.meters) and `consumers.py` (config.asgi). Each is a population
    # a product app joins by dropping a conventionally named file, which is
    # exactly the channel the digest exists to close.
    take("policies", _policies)
    take("meters", _meters)
    take("sockets", _sockets)

    declared = {str(entry["id"]) for entry in (lockfile().get("digest_sections") or [])}
    if declared != set(sections):
        raise Broken(
            "the lockfile's digest sections and the ones this tool serializes disagree: "
            f"declared-not-served {sorted(declared - set(sections))}, "
            f"served-not-declared {sorted(set(sections) - declared)}"
        )
    return sections


def _install_plant() -> None:
    """Put a planted app on the `apps` package's search path, before setup.

    The `scratch_tagged_app` shape (`apps/accounts/tests/test_scopes.py`),
    lifted to a subprocess: the plant is a real package in a real registry, and
    the working tree is never written to. Reading `settings.INSTALLED_APPS`
    configures settings — including `config/settings/discovery.py`'s walk — and
    the append lands before `django.setup()` reads the value.
    """
    directory = os.environ.get(PLANT_DIR_ENV)
    label = os.environ.get(PLANT_LABEL_ENV)
    if not directory or not label:
        return
    from django.conf import settings

    import apps as apps_package

    apps_package.__path__.append(directory)
    settings.INSTALLED_APPS = [*settings.INSTALLED_APPS, f"apps.{label}"]


def section_hashes(*, plant: tuple[Path, str] | None = None) -> dict[str, str]:
    """Part 2 of the key, section by section — computed in a SUBPROCESS.

    A subprocess because the digest loads the whole app registry and builds both
    doors, and because the plant canary needs a registry that is not this
    process's. `sys.executable` rather than `uv run`: this already runs inside
    the environment the gate resolved, and re-resolving it would put the digest
    and the suite on two different resolutions of the same lock.
    """
    environment = dict(os.environ)
    environment.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    environment.pop(PLANT_DIR_ENV, None)
    environment.pop(PLANT_LABEL_ENV, None)
    if plant is not None:
        environment[PLANT_DIR_ENV] = str(plant[0])
        environment[PLANT_LABEL_ENV] = plant[1]
    result = subprocess.run(
        [sys.executable, "-m", "quality.partition", "digest"],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise Broken(
            "the discovery digest could not be computed (exit "
            f"{result.returncode}). A digest section that cannot serialize is exit 2 "
            f"(§4). What the subprocess said:\n{result.stdout.strip()}\n{result.stderr.strip()}"
        )
    try:
        sections = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise Broken(
            f"the digest subprocess did not answer JSON: {error}. Its output was:\n"
            f"{result.stdout[:2000]}"
        ) from error
    return {str(name): str(value) for name, value in sections.items()}


def digest_of(sections: Mapping[str, str]) -> str:
    """The one hash over the section hashes, sorted. Order can never surprise."""
    digest = hashlib.sha256()
    for name in sorted(sections):
        digest.update(f"{name}\0{sections[name]}\n".encode())
    return digest.hexdigest()


# --- the key ------------------------------------------------------------------


def skip_key(*, plant: tuple[Path, str] | None = None) -> tuple[str, str, dict[str, str]]:
    """`(closure hash, digest, per-section hashes)` — both parts, and the detail."""
    sections = section_hashes(plant=plant)
    return closure_hash(), digest_of(sections), sections


def key_string(closure: str, digest: str) -> str:
    return f"{closure}:{digest}"


# --- the ledger (`scripts/gate_ledger.sh`, one more consumer) -----------------


def _ledger(function: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Call one of `gate_ledger.sh`'s partition functions. BASH ONLY.

    The ledger's semantics have one home and it is that file (its own header
    says so, and says why it must not be sourced into zsh). This module owns
    the DECISION; it does not own a second copy of the verdict rules.
    """
    if not GATE_LEDGER.exists():
        raise Broken(f"the gate ledger is missing: {GATE_LEDGER.relative_to(ROOT)}")
    return subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; "$2" "${@:3}"',
            "_",
            str(GATE_LEDGER),
            function,
            *arguments,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def banked(key: str) -> str | None:
    """The banked row for this key, or `None`. An unparseable key is exit 2."""
    result = _ledger("partition_ledger_lookup", key)
    if result.returncode == 2:
        raise Broken(
            "the partition ledger holds a row whose key cannot be parsed — a ledger "
            "this tool cannot read is enforcement broken, not a miss:\n"
            f"{result.stderr.strip()}"
        )
    if result.returncode != 0:
        return None
    line = result.stdout.strip()
    return line or None


def bank(key: str) -> None:
    result = _ledger("partition_ledger_record", key)
    if result.returncode != 0:
        raise Broken(f"the partition verdict could not be banked: {result.stderr.strip()}")


# --- §3 · the environment read-set --------------------------------------------


def _settings_modules() -> list[Path]:
    return sorted((ROOT / "config" / "settings").glob("*.py"))


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return _UNKNOWN


class _Unknown:
    def __repr__(self) -> str:  # pragma: no cover - printed only in diagnostics
        return "<not a literal>"


_UNKNOWN = _Unknown()


def environment_reads() -> dict[str, Any]:
    """Every env var `config/settings/**` reads, with the default it names.

    An AST census, never a hand list: `env.<type>("NAME", default=...)`,
    `os.environ.get("NAME", default)`, `os.getenv("NAME", default)` and
    `os.environ["NAME"]`. `config/settings/test.py` is excluded from the READ
    side because it is the neutralization seam, not a reader of the ambient
    environment — what it PINS is subtracted below.

    Declared blind spot, and it is in the lockfile too: the `ANYMAIL_*` prefix
    scan in `base.py` is a comprehension over `os.environ` and names no variable
    this census can collect.
    """
    found: dict[str, Any] = {}
    for path in _settings_modules():
        if path.name == "test.py":
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name, default = _read_call(node)
            if name is not None:
                found.setdefault(name, default)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "environ"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)
            ):
                found.setdefault(node.slice.value, _UNKNOWN)
    return found


def _read_call(node: ast.Call) -> tuple[str | None, Any]:
    """`(env name, default)` for a call that reads the environment, else `(None, ...)`."""
    target = node.func
    reader = ""
    if isinstance(target, ast.Attribute):
        base = target.value
        if isinstance(base, ast.Name) and base.id == "env":
            reader = "env"
        elif isinstance(base, ast.Name) and base.id == "os" and target.attr == "getenv":
            reader = "getenv"
        elif isinstance(base, ast.Attribute) and base.attr == "environ" and target.attr == "get":
            reader = "environ.get"
    if not reader:
        return None, _UNKNOWN
    if not node.args or not isinstance(node.args[0], ast.Constant):
        return None, _UNKNOWN
    name = node.args[0].value
    if not isinstance(name, str):
        return None, _UNKNOWN
    for keyword in node.keywords:
        if keyword.arg == "default":
            return name, _literal(keyword.value)
    if len(node.args) > 1:
        return name, _literal(node.args[1])
    return name, _UNKNOWN


def settings_pinned_names() -> frozenset[str]:
    """Every setting `config/settings/test.py` assigns at module level.

    That file is the neutralization seam (§3): what it pins, the ambient
    environment can no longer reach the suite through.
    """
    path = ROOT / "config" / "settings" / "test.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return frozenset(names)


def _default_spellings(default: Any) -> set[str]:
    """What an environment value may say and still be the default."""
    if default is _UNKNOWN:
        return set()
    if isinstance(default, bool):
        return (
            {"1", "true", "True", "yes", "on"}
            if default
            else {"0", "false", "False", "no", "off", ""}
        )
    if default is None:
        return {""}
    if isinstance(default, (list, tuple)):
        return {"", ",".join(str(item) for item in default)}
    return {str(default)}


def _dotenv(path: Path) -> dict[str, str]:
    """A `.env`-shaped file as a mapping. `django-environ`'s own read, narrowed."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def live_environment() -> dict[str, str]:
    """The environment as the SUITE sees it: `os.environ` over `.env`.

    `config/settings/base.py` calls `env.read_env(.env)`, which fills gaps in
    `os.environ` and never overrides it — so this is the same precedence, and a
    check that read only `os.environ` would be blind to exactly the file every
    laptop configures the suite with.
    """
    return {**_dotenv(ROOT / ".env"), **os.environ}


def reference_environment() -> dict[str, str]:
    """What a value has to be to count as UNBENT — `.env.example`, then the code.

    **The reference is `.env.example` and not the code's fallback, and this is
    the one place the build had to choose a reading.** The design's §3 criterion
    says "set to a non-default". Read as "the `env.str(...)` default", every
    honest checkout of this template is permanently bent: `.env.example` ships
    twelve working development values (`AWS_ACCESS_KEY_ID=minioadmin`,
    `EMAIL_PORT=1025`, …) precisely so that `cp .env.example .env` runs, which
    `config/settings/guards.py` states as doctrine. Nothing would ever bank, and
    a dividend deleted is not a dividend protected.

    So the reference is the tree's own declared environment — `.env.example`,
    which `base.py`'s own docstring calls "the complete list" of what settings
    read — falling back to the code's default for a name the example does not
    carry. **`.env.example` is therefore IN THE CLOSURE** (class C4): change the
    reference and the whole partition re-runs, which is what keeps this honest
    rather than convenient.
    """
    return _dotenv(ROOT / ".env.example")


def bent_environment() -> list[str]:
    """Read env vars whose value differs from the declared reference, as sentences.

    Non-empty means the verdict RUNS and is NOT BANKED (§4's decision table):
    banked green under a bent environment is the stale-green class with no diff
    at all. `config/settings/test.py`'s pins are subtracted first — that file is
    the neutralization seam, and what it pins the ambient environment can no
    longer reach the suite through.
    """
    pinned = settings_pinned_names()
    tolerated = tolerated_environment()
    reference = reference_environment()
    live = live_environment()
    bent: list[str] = []
    for name, default in sorted(environment_reads().items()):
        if name in tolerated or name in pinned:
            continue
        value = live.get(name)
        if value is None:
            continue
        expected = {reference[name]} if name in reference else _default_spellings(default)
        if value.strip() in expected:
            continue
        bent.append(
            f"{name}={value.strip()!r} — `config/settings/` reads it, "
            f"`config/settings/test.py` does not pin it, and the declared "
            f"environment says {sorted(expected)!r}"
        )
    return bent


# --- §4 · the AST seam census -------------------------------------------------


def _walking_modules() -> list[str]:
    """Every platform module that performs the discovery walk shape.

    The shape, stated so a reader can disagree with it: a module that asks the
    app registry for its configs AND reaches for a submodule of an app by its
    dotted name (`importlib.util.find_spec` / `import_module`). That is what a
    discovery seam looks like in this tree, in every one of the ten it already
    has.

    Tests are excluded: the census is about seams the platform READS THROUGH,
    and a test that walks the registry is a quantified assertion — which is §5's
    census, a different instrument with a different disposition.
    """
    found: list[str] = []
    for path in sorted((ROOT / "apps").rglob("*.py")) + sorted((ROOT / "config").rglob("*.py")):
        relative = path.relative_to(ROOT)
        parts = relative.with_suffix("").parts
        if any(part == "tests" for part in parts) or parts[-1].startswith("test_"):
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as error:  # pragma: no cover - a broken file is exit 2
            raise Broken(f"the seam census cannot parse {relative}: {error}") from error
        source = ast.dump(tree)
        asks_registry = "get_app_configs" in source
        reaches = "find_spec" in source or "import_module" in source
        if asks_registry and reaches:
            found.append(".".join(parts))
    return found


def _platform_test_modules(
    *, root: Path = ROOT, platform: Sequence[str] | None = None
) -> list[Path]:
    """Every test module inside the partition — the ones a skip stops running.

    `root` and `platform` are the canaries' seam, not configuration: §8.4 drives
    this exact function over a scratch tree, because a canary that re-implemented
    the population walk would be proving a copy of the check rather than the
    check. Both default to the live tree and the live lockfile.
    """
    apps = set(platform_apps() if platform is None else platform)
    found: list[Path] = []
    for path in sorted((root / "apps").rglob("*.py")):
        relative = path.relative_to(root)
        parts = relative.parts
        if len(parts) > 1 and parts[1] not in apps and len(parts) > 2:
            continue  # a product app's tests are outside the partition
        if "tests" in parts or parts[-1].startswith("test_") or parts[-1] == "conftest.py":
            found.append(path)
    return found


def read_census() -> list[str]:
    """Repository files a PLATFORM TEST reads that no closure class covers.

    **This is the tooth the design's §3 does not have, and the reason it needs
    one is the design's own standard.** Its header cites the architect
    checklist's closed-question line — *every enumeration below is derived or
    pinned, never a hand list of an open set* — and §3's class list IS a hand
    list until something checks that it covers what the partition's tests
    actually read. §8's canaries prove the LISTED classes move the hash; not one
    of them can notice a class that was never listed, and a file a platform test
    reads which is outside the closure is a silent stale green: edit it, and a
    banked verdict goes on vouching for a suite whose answer just changed.

    The method, stated so a reader can disagree with it: a path this tree BUILDS
    — a `/`-chain rooted at `BASE_DIR`, `ROOT` or a `Path(...)` call, which is
    how every filesystem read in these modules is written — is resolved to a
    repository-relative path and required to be a closure member or to live
    under one. Detecting the CONSTRUCTION rather than the literal is what makes
    this usable: a first cut over bare string constants reported
    `docs/runbooks/deploy.md` (an assertion about prose), `docs` (a URL segment)
    and `APPS` (a case-insensitive filesystem matching `apps/`), and a census
    that cries wolf is a census somebody widens until it is silent.

    `does_not_cover`, declared: a path assembled from a fixture, a setting, an
    environment variable or a loop variable is not seen; nor is a read performed
    by a helper the test imports from outside its own module.
    """
    members = {path for paths in closure_members().values() for path in paths}
    covered = {str(Path(path).parent) for path in members}
    strays: list[str] = []
    for module in _platform_test_modules():
        relative = str(module.relative_to(ROOT))
        try:
            tree = ast.parse(module.read_text())
        except SyntaxError as error:  # pragma: no cover - a broken file is exit 2
            raise Broken(f"the read census cannot parse {relative}: {error}") from error
        named: set[str] = set()
        for node in ast.walk(tree):
            built = _built_path(node)
            if built is None:
                continue
            if built in members or built in covered:
                continue
            if any(built == d or d.startswith(f"{built}/") for d in covered):
                continue
            if not (ROOT / built).exists():
                continue
            named.add(built)
        for value in sorted(named):
            strays.append(f"{relative} reads {value}, which no closure class covers")
    return strays


def _built_path(node: ast.AST) -> str | None:
    """`BASE_DIR / "scripts" / "db.sh"` → `scripts/db.sh`. Anything else, `None`.

    Only the outermost chain answers: a nested `BinOp` is skipped so one
    expression reports one path rather than one per segment.
    """
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
        return None
    segments: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.BinOp) and isinstance(current.op, ast.Div):
        right = current.right
        if not isinstance(right, ast.Constant) or not isinstance(right.value, str):
            return None
        segments.append(right.value)
        current = current.left
    if not _is_repository_root(current):
        return None
    return "/".join(reversed(segments)).strip("/") or None


def _is_repository_root(node: ast.AST) -> bool:
    """Whether an expression is this repository's root — `BASE_DIR`, `Path(...)`."""
    if isinstance(node, ast.Name):
        return node.id in {"BASE_DIR", "ROOT", "REPO", "REPO_ROOT"}
    if isinstance(node, ast.Attribute):
        return node.attr in {"BASE_DIR", "ROOT"}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Path":
        return bool(node.args) and _is_repository_root(node.args[0])
    return False


def product_app_labels(
    *, root: Path = ROOT, platform: Sequence[str] | None = None
) -> frozenset[str]:
    """Every real app in this tree the lockfile does not claim — DERIVED (§2).

    "Real" is the same test `product_paths` applies when it decides what pytest
    runs under a skip: a directory under `apps/` carrying an `apps.py`. The two
    populations are deliberately the same one — what always runs under a skip,
    and what a platform test may therefore not import — so they cannot drift
    apart into a window where a thing runs but nothing may name it.

    NEVER A HAND LIST. The lockfile names the PLATFORM half and this subtracts
    it; an unreadable lockfile is `Broken` out of `platform_apps()`, which is
    exit 2 and never a judgment about the readable part.
    """
    claimed = set(platform_apps() if platform is None else platform)
    directory = root / "apps"
    if not directory.is_dir():
        raise Broken(f"the import census cannot read {directory}: there is no apps/ tree")
    return frozenset(
        entry.name
        for entry in sorted(directory.iterdir())
        if entry.is_dir() and (entry / "apps.py").exists() and entry.name not in claimed
    )


def _imported_modules(tree: ast.AST) -> set[str]:
    """Every absolute dotted module name an AST imports. Relative imports skipped.

    A relative import (`from ..services import x`) cannot cross an app boundary
    upward into a sibling app without going through `apps.`, so the absolute
    spelling is the whole population — and it is the only spelling this tree
    permits (`django-conventions` §1: the import path is `apps.<name>`).
    """
    named: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            named.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            named.add(node.module)
            named.update(f"{node.module}.{alias.name}" for alias in node.names)
    return named


def import_census(*, root: Path = ROOT, platform: Sequence[str] | None = None) -> list[str]:
    """Platform test modules that IMPORT a product app — the other half of §4's
    sentence, and the half `read_census` cannot see.

    **Why this exists.** The decision table's first row says a product's own
    `services.py`, selectors, tests and migrations are `skip — the dividend, and
    it is sound: no platform test reads any of it`
    (`docs/product/partition-closure.md:218`). `read_census` above checks the
    FILE-READ half of that sentence and nothing checked the IMPORT half: a
    platform test that does `from apps.<product>.checks import ...` reads the
    product app through the import system, where no built path appears and no
    closure class is consulted. A product-only edit moves neither key part, so a
    banked skip goes on vouching for a platform test whose answer just changed —
    the same stale green C8 was added to close, arriving through the other door.
    The sibling platform's import-census ruling is the source (road (a): the
    sentence becomes a checked rule over a derived population), measured live on
    their tree, where `test_slug_clash_sentence.py` imported
    `apps.playbook.checks`.

    **The population is derived on both sides** — the platform test modules from
    the lockfile's app list, the product apps as everything under `apps/` the
    lockfile does not claim — so this is a closed question, never a hand list.

    **THE FAIL-SAFE DIRECTION.** An app the lockfile forgets is a PRODUCT app
    here, so a forgotten platform app makes this census louder, never quieter:
    the same direction §2 chose for the boundary itself.

    `does_not_cover`, declared and shared honestly with their blind spot 1: the
    BEHAVIORAL coupling residue. A platform test that reaches a product app
    without naming it — through a database row the product's migrations created,
    a fixture the product registered, a discovered registry entry, or an event
    payload it consumes — is invisible to any import census, because nothing in
    the module's text mentions the app. Also invisible: an import assembled at
    run time (`importlib.import_module(name)` over a computed string).
    """
    products = product_app_labels(root=root, platform=platform)
    if not products:
        # NOT a pass, and not silence either: on this template's tree every app
        # is a platform app, so the live population is empty and a green here
        # asserts over nothing. §8.4's plant is what makes the check falsifiable,
        # and it runs whether or not this early return is taken.
        return []
    findings: list[str] = []
    for module in _platform_test_modules(root=root, platform=platform):
        relative = str(module.relative_to(root))
        try:
            tree = ast.parse(module.read_text(), filename=str(module))
        except SyntaxError as error:  # pragma: no cover - a broken file is exit 2
            raise Broken(f"the import census cannot parse {relative}: {error}") from error
        reached: dict[str, set[str]] = {}
        for name in _imported_modules(tree):
            parts = name.split(".")
            if len(parts) >= 2 and parts[0] == "apps" and parts[1] in products:
                reached.setdefault(parts[1], set()).add(name)
        for app in sorted(reached):
            # One line per (module, product app), and the DEEPER spellings of one
            # import collapse into the shallowest — `from apps.x.services import M`
            # yields both `apps.x.services` and `apps.x.services.M`, and reporting
            # both would say one violation twice. A census that inflates its own
            # count is a census whose numbers nobody can use.
            names = reached[app]
            minimal = sorted(
                n for n in names if not any(n != o and n.startswith(f"{o}.") for o in names)
            )
            findings.append(
                f"{relative} imports {', '.join(minimal)} — apps/{app} is a product app"
            )
    return findings


def seam_census() -> list[str]:
    """Discovery walks the lockfile's digest sections do not claim (§4).

    Exit 1 naming the stray, so a future discovery seam joins the digest in the
    commit that lands it or the gate says so. `does_not_cover`, declared: a
    discovery seam written in a shape this census does not recognize.
    """
    claimed = {
        str(module)
        for section in (lockfile().get("digest_sections") or [])
        for module in (section.get("walks") or [])
    }
    return [module for module in _walking_modules() if module not in claimed]


# --- §7 · the always-run nets' liveness ---------------------------------------


def net_liveness() -> None:
    """Every listed net collects at least one test, or exit 2.

    A listed net that collects zero tests is a name in a tuple pretending to be
    a belt. The enumeration lived only in a trim-listed cycle plan until;
    it is executable now, and this is what keeps it honest.
    """
    nets = always_run()
    if not nets:
        raise Broken("the lockfile lists no always-run nets — §7's belt is missing")
    missing = [path for path in nets if not (ROOT / path).exists()]
    if missing:
        raise Broken(f"always-run nets that do not exist: {missing}")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:randomly", *nets],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise Broken(
            "the always-run nets could not be collected — a net this gate cannot "
            f"collect is not a belt:\n{result.stdout[-3000:]}\n{result.stderr[-2000:]}"
        )
    for path in nets:
        if path not in result.stdout:
            raise Broken(
                f"the always-run net {path} collected ZERO tests (§7's liveness "
                "clause). A listed net that collects nothing is exit 2, not a pass."
            )


# --- §8 · the canary set ------------------------------------------------------


def _scratch_plant(directory: Path, label: str) -> Path:
    """'s plant, materialized: `apps.py` + an `api.py` with a `TAGS` dict.

    Exactly the shape drove, and it is deliberately a REAL app package in
    a REAL registry rather than a stand-in — the claim under test is that the
    digest sees a product app arrive, and a fixture that faked the arrival would
    be proving something else.
    """
    package = directory / label
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    (package / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\n"
        "class PlantConfig(AppConfig):\n"
        f'    name = "apps.{label}"\n'
        f'    label = "{label}"\n'
        '    depends_on = ("core",)\n'
    )
    (package / "api.py").write_text(
        "from ninja import Router\n\n"
        "from apps.accounts.auth import API_AUTH\n"
        "from apps.core.api.docs import Tag\n\n"
        f'PREFIX = "{label}"\n'
        f'TAGS = {{"{label}": Tag("Plant", "The partition canary\'s planted product app.", '
        'plane="everyday", plane_note="the canary\'s own section.")}\n'
        f'router = Router(tags=["{label}"], auth=API_AUTH)\n'
    )
    (package / "services.py").write_text(
        '"""A body no discovery walk reads — the §8.3 negative\'s subject."""\n\nMARKER = \'one\'\n'
    )
    return directory


def canary_born_with(say: Any) -> None:
    """§8.1 — the owner's born-with clause, TOTAL over the closure classes.

    For each class, perturb one member in an overlay (never the working tree)
    and recompute: the closure hash MUST differ. Any class whose perturbation
    fails to move the hash is exit 2 by name. "An in-closure edit that fails to
    invalidate = exit 2", made total over the classes rather than sampled.
    """
    baseline = closure_hash()
    for identifier, members in sorted(closure_members().items()):
        # HEAD AND TAIL, not one sample. A class whose glob accidentally covered
        # only its first member would pass a single-sample canary and be a
        # blind spot for everything after it; two ends is the cheapest
        # perturbation that cannot be satisfied by a one-file class.
        for member in {members[0], members[-1]}:
            original = (ROOT / member).read_bytes()
            perturbed = closure_hash(overrides={member: original + b"\n# born-with canary\n"})
            if perturbed == baseline:
                raise Broken(
                    f"BORN-WITH CANARY DID NOT FIRE for closure class {identifier}: "
                    f"perturbing {member} left the closure hash unchanged. An in-closure "
                    "edit that fails to invalidate is exit 2, not a pass — this class is "
                    "in the lockfile and out of the key."
                )
        say(
            f"    {identifier}: perturbing {members[0]} and {members[-1]} "
            f"moves the closure hash ({len(members)} members)"
        )


def canary_planted_app(say: Any) -> None:
    """§8.2 — the criteria's specified canary, 's shape.

    Materialize a scratch product app into an overlay, compute the digest with
    and without it in a subprocess registry, and require: the digest DIFFERS,
    and the skip decision with the plant present is REFUSED against a verdict
    banked without it. A digest that fails to see the plant is exit 2 — the
    partition may not claim a planted product app is provably unread when its
    own instrument cannot tell the difference.
    """
    label = "partitioncanary"
    with tempfile.TemporaryDirectory(prefix="djb-partition-plant-") as scratch:
        directory = _scratch_plant(Path(scratch), label)
        without = section_hashes()
        with_plant = section_hashes(plant=(directory, label))
        moved = sorted(name for name in without if without[name] != with_plant.get(name))
        if digest_of(without) == digest_of(with_plant):
            raise Broken(
                "THE PLANT CANARY DID NOT FIRE: a planted product app "
                f"(apps/{label} with a router and a TAGS dict) "
                "left the discovery digest unchanged. No digest section moved. The "
                "partition may not claim a product app is provably unread when its "
                "own instrument cannot tell the difference."
            )
        say(f"    a planted product app moves the digest; sections that moved: {moved}")

        # And the decision itself refuses. A forged ledger row banked under the
        # plant-free key must not license a skip while the plant is present.
        with _scratch_ledger():
            bank(key_string(closure_hash(), digest_of(without)))
            if banked(key_string(closure_hash(), digest_of(with_plant))) is not None:
                raise Broken(
                    "THE PLANT CANARY DID NOT FIRE at the decision: a verdict banked "
                    "without the plant was honoured WITH it. The digest moved and the "
                    "skip did not refuse, which is the skip machinery ignoring its own key."
                )
        say("    a verdict banked without the plant does NOT license a skip with it")

        # §8.3 — the negative. A body no walk discovers moves neither key part.
        (directory / label / "services.py").write_text("MARKER = 'two'\n")
        after = section_hashes(plant=(directory, label))
        if digest_of(after) != digest_of(with_plant):
            fired = sorted(name for name in after if after[name] != with_plant.get(name))
            raise Violation(
                "THE NEGATIVE FIRED — and a negative that fires is a finding, not a "
                f"pass. Editing a body no discovery walk reads moved these digest "
                f"sections: {fired}. The closure has silently over-reached and the "
                "dividend is gone: every product commit would invalidate."
            )
    say("    the negative stays silent: an undiscovered body moves neither key part")

    # The other half of the negative, on part 1: a product-shaped path is
    # matched by no closure class, so a product's own files are never members.
    members = {path for paths in closure_members().values() for path in paths}
    for product_path in (f"apps/{label}/services.py", f"apps/{label}/api.py"):
        if product_path in members:
            raise Violation(
                f"THE NEGATIVE FIRED on part 1: {product_path} is a closure member. "
                "A product app's own files are outside the closure by construction "
                "(§2's fail-safe direction) — if they are inside it, the dividend is gone."
            )
    say("    the negative stays silent on part 1: product-shaped paths are not members")


def canary_import_census(say: Any) -> None:
    """§8.4 — the import census, born provably non-vacuous.

    **The empty-population problem, stated plainly.** On this template's tree
    every app is a platform app (`quality/partition.yaml` names all of them), so
    `import_census`'s derived product set is EMPTY and the census asserts over
    nothing. A green from an empty quantifier is not evidence, and shipping one
    is how a check arrives already unable to fail. The plant IS the falsifying
    world: a scratch tree carrying a real product app (a directory with an
    `apps.py`, absent from the lockfile) and a platform test that imports it.

    The plant is built in a temporary directory, never in the working tree — a
    destructive demonstration creates its own victim — and it drives the REAL
    `import_census` and the REAL `_platform_test_modules`, not a re-implementation.

    A canary that does not fire is exit 2, not a pass (house canary discipline).
    """
    label = "partitionimportcanary"
    host = platform_apps()[0]  # a real platform app, so the plant lands in the real population
    with tempfile.TemporaryDirectory(prefix="djb-partition-import-") as scratch:
        root = Path(scratch)
        tests = root / "apps" / host / "tests"
        tests.mkdir(parents=True)
        violator = tests / "test_import_census_canary.py"
        violator.write_text(f"from apps.{label}.services import MARKER\n")
        _scratch_plant(root / "apps", label)

        products = product_app_labels(root=root)
        if label not in products:
            raise Broken(
                "THE IMPORT CANARY COULD NOT BE PLANTED: the derived product set "
                f"{sorted(products)} does not contain the planted app {label!r}, so the "
                "canary would have proved nothing. The derivation is what is broken here, "
                "not the plant."
            )
        fired = import_census(root=root)
        if not fired:
            raise Broken(
                "THE IMPORT CANARY DID NOT FIRE: a platform test importing a planted "
                f"product app (apps/{host}/tests/{violator.name} importing apps.{label}) "
                "left the import census silent. On this tree the live product population "
                "is empty, so this plant is the ONLY thing that can tell a working census "
                "from one that cannot fail — a canary that does not fire is exit 2."
            )
        say(f"    a platform test importing a planted product app fires: {fired[0]}")

        # THE NEGATIVE — the other direction, which is always legal. A PRODUCT
        # test importing a platform module is exactly what a product is supposed
        # to do, and it must stay silent. It does so for a reason worth naming:
        # a product app's tests are not in `_platform_test_modules` at all, which
        # is the boundary doing the work rather than a special case in the census.
        violator.unlink()
        product_tests = root / "apps" / label / "tests"
        product_tests.mkdir(parents=True)
        (product_tests / "test_negative.py").write_text(
            f"from apps.{host}.services import anything\n"
        )
        noise = import_census(root=root)
        if noise:
            raise Violation(
                "THE NEGATIVE FIRED — and a negative that fires is a finding, not a pass. "
                f"A product test importing a platform module was reported: {noise}. That "
                "direction is always legal; a census that refuses it would refuse every "
                "product this template exists to start."
            )
        say("    the negative stays silent: a product test importing platform is legal")


class _scratch_ledger:
    """Point the ledger at a throwaway file for the length of a canary.

    A forged row must never be able to become a banked verdict, so the forge
    never writes to the real ledger — the same discipline as a destructive
    demonstration creating its own victim.
    """

    def __enter__(self) -> None:
        self._previous = os.environ.get(LEDGER_OVERRIDE_ENV)
        self._file = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed in __exit__
            prefix="djb-partition-ledger-", delete=False
        )
        self._file.close()
        os.environ[LEDGER_OVERRIDE_ENV] = self._file.name

    def __exit__(self, *_: object) -> None:
        os.unlink(self._file.name)
        if self._previous is None:
            os.environ.pop(LEDGER_OVERRIDE_ENV, None)
        else:
            os.environ[LEDGER_OVERRIDE_ENV] = self._previous


def canary_stale_ledger(say: Any, closure: str, digest: str) -> None:
    """§8.4 — the forge, per key part, plus the unparseable row.

    A row whose key mismatches the tree IN EACH PART SEPARATELY must not license
    a skip; a forged row with an unparseable key is exit 2. Both parts are
    forged apart so that a decision matching on only one of them is caught.
    """
    forged = "f" * 64
    with _scratch_ledger():
        bank(key_string(forged, digest))
        if banked(key_string(closure, digest)) is not None:
            raise Broken(
                "THE STALE-LEDGER FORGE DID NOT FIRE (closure part): a row banked "
                "under a different closure hash was honoured for this tree."
            )
        say("    a row whose CLOSURE half is stale refuses the skip")

    with _scratch_ledger():
        bank(key_string(closure, forged))
        if banked(key_string(closure, digest)) is not None:
            raise Broken(
                "THE STALE-LEDGER FORGE DID NOT FIRE (digest part): a row banked "
                "under a different discovery digest was honoured for this tree."
            )
        say("    a row whose DIGEST half is stale refuses the skip")

    with _scratch_ledger():
        path = Path(os.environ[LEDGER_OVERRIDE_ENV])
        path.write_text("v1 not-a-key partition 2026-08-26T00:00:00Z caller=unstated\n")
        try:
            banked(key_string(closure, digest))
        except Broken:
            say("    a row whose key cannot be parsed is exit 2, not a miss")
        else:
            raise Broken(
                "THE UNPARSEABLE-ROW CLAUSE DID NOT FIRE: a ledger row whose key is "
                "not a key was read as an ordinary miss. A ledger this tool cannot "
                "read is enforcement broken (§4), never a silent full run."
            )


def selftest(say: Any) -> tuple[str, str, dict[str, str]]:
    """Every canary, planted through the real scope, before the first decision.

    House canary discipline, inherited: a canary that does not fire is exit 2,
    not a pass; negatives stay silent; `does_not_cover` is stated where the
    canary is declared — and printed here, on the run that uses it.
    """
    say("  partition self-test (§8) — canaries fire before any decision is made")

    registry_labels = _installed_labels()
    unknown = [label for label in platform_apps() if label not in registry_labels]
    if unknown:
        raise Broken(
            f"the lockfile names {unknown}, which the live app registry cannot find. "
            "A closure that claims territory it cannot see may not bank a verdict "
            "about it (§2). The fail-safe direction is the OTHER way: an app the "
            "lockfile does not name simply always runs."
        )
    say(f"    every lockfile app is live ({len(platform_apps())} apps)")

    canary_born_with(say)
    closure = closure_hash()
    sections = section_hashes()
    digest = digest_of(sections)
    canary_planted_app(say)
    canary_stale_ledger(say, closure, digest)
    net_liveness()
    say(f"    every always-run net collects tests ({len(always_run())} nets)")

    reads = read_census()
    if reads:
        raise Violation(
            "PLATFORM TESTS READ FILES NO CLOSURE CLASS COVERS:\n    "
            + "\n    ".join(reads)
            + "\n  Each of these is an out-of-closure file whose edit changes a platform "
            "test's answer, which makes a banked skip a stale green. Add the path (or "
            "its directory) to a closure class in quality/partition.yaml with the "
            "reason — or say why the test does not really read it, in the same diff."
        )
    say("    every file a platform test builds a path to is in the closure")

    # §8.4 FIRST, then the census it makes falsifiable — the plant proves the
    # instrument can fire before the instrument's silence is read as evidence.
    canary_import_census(say)
    imports = import_census()
    if imports:
        raise Violation(
            "PLATFORM TESTS IMPORT PRODUCT APPS:\n    "
            + "\n    ".join(imports)
            + "\n  The decision table's first row (partition-closure.md:218) says a "
            "product-only edit is a sound skip because no platform test reads any of it. "
            "Each line above is a platform test that does — through the import system, "
            "where no closure class is consulted — so a product-only edit moves neither "
            "key part while changing that test's answer, and the banked skip is a stale "
            "green. Move the test to the app it is really about, re-derive it as genuinely "
            "cross-app (read the registry, not a product module), or invert the dependency "
            "so the shape lives where both sides may legally read it."
        )
    say("    no platform test imports a product app")

    strays = seam_census()
    if strays:
        raise Violation(
            "DISCOVERY WALKS NO DIGEST SECTION CLAIMS: "
            + ", ".join(strays)
            + ". A platform module that walks the app registry for a submodule is a "
            "discovery seam, and a seam outside the digest is a channel the skip key "
            "cannot see. Name it under a section's `walks:` in quality/partition.yaml "
            "— or say why it is not a seam, in the same diff."
        )
    say("    every discovery walk belongs to a digest section")

    for blind_spot in lockfile().get("does_not_cover") or []:
        say(f"    does not cover: {str(blind_spot).strip()}")
    return closure, digest, sections


def _installed_labels() -> frozenset[str]:
    """The live app registry's labels, read in the digest subprocess's shape."""
    result = subprocess.run(
        [sys.executable, "-m", "quality.partition", "labels"],
        cwd=ROOT,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise Broken(
            "the live app registry could not be read, so the lockfile's names cannot "
            f"be checked against it:\n{result.stdout[-2000:]}\n{result.stderr[-2000:]}"
        )
    return frozenset(json.loads(result.stdout))


# --- the decision -------------------------------------------------------------


def product_paths() -> list[str]:
    """What pytest is given when the platform partition is SKIPPED.

    Every `apps/` subdirectory the lockfile does not claim, plus the four
    always-run nets. Positional arguments rather than `--ignore`, because
    `testpaths` and `--ignore` interact in ways a reader has to know pytest to
    predict, and a skip decision has to be legible in the command line the log
    prints.
    """
    apps = set(platform_apps())
    product = sorted(
        str(entry.relative_to(ROOT))
        for entry in (ROOT / "apps").iterdir()
        if entry.is_dir() and entry.name not in apps and (entry / "apps.py").exists()
    )
    return [*product, *always_run()]


def decide(*, out: Path | None, say: Any) -> int:
    """The whole decision, printed. Exit 0 decided · 1 finding · 2 broken."""
    closure, digest, sections = selftest(say)
    key = key_string(closure, digest)
    bent = bent_environment()

    row = banked(key)
    mode = "skip" if row is not None else "full"
    if mode == "skip":
        paths = product_paths()
        say("  PLATFORM PARTITION: SKIPPED — a green verdict is banked for this key")
        say(f"    key    {key}")
        say(f"    banked {row}")
        say(f"    running instead: {' '.join(paths) if paths else '(nothing but the nets)'}")
    else:
        paths = []
        say("  PLATFORM PARTITION: RUNNING — no banked verdict for this key")
        say(f"    key    {key}")
        say("    closure " + closure)
        say("    digest  " + digest)
    if bent:
        say("  THE ENVIRONMENT IS BENT — this run will NOT bank a verdict:")
        for sentence in bent:
            say(f"    {sentence}")

    if out is not None:
        out.write_text(
            json.dumps(
                {
                    "mode": mode,
                    "key": key,
                    "closure": closure,
                    "digest": digest,
                    "sections": sections,
                    "paths": paths,
                    "bent_environment": bent,
                    "bankable": not bent,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    return EXIT_OK


# --- the entry point ----------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m quality.partition", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest", help="§8's canaries, and nothing else")
    decide_parser = sub.add_parser("decide", help="self-test, then the skip decision")
    decide_parser.add_argument("--out", type=Path, default=None)
    bank_parser = sub.add_parser("bank", help="record a green verdict for a key")
    bank_parser.add_argument("--key", required=True)
    sub.add_parser("key", help="print the two key parts")
    sub.add_parser("digest", help="internal: the digest sections, as JSON, in a loaded registry")
    sub.add_parser("labels", help="internal: the live app registry's labels, as JSON")
    sub.add_parser("paths", help="what pytest runs when the partition is skipped")
    arguments = parser.parse_args(argv)

    def say(line: str) -> None:
        print(line, flush=True)

    try:
        if arguments.command == "digest":
            _install_plant()
            import django

            django.setup()
            print(
                json.dumps(
                    {
                        name: hashlib.sha256(_canonical(value).encode()).hexdigest()
                        for name, value in _digest_sections_in_process().items()
                    }
                )
            )
            return EXIT_OK
        if arguments.command == "labels":
            import django

            django.setup()
            from django.apps import apps as django_apps

            print(json.dumps(sorted(str(c.label) for c in django_apps.get_app_configs())))
            return EXIT_OK
        if arguments.command == "selftest":
            selftest(say)
            return EXIT_OK
        if arguments.command == "decide":
            return decide(out=arguments.out, say=say)
        if arguments.command == "bank":
            bank(arguments.key)
            say(f"  partition verdict banked for {arguments.key}")
            return EXIT_OK
        if arguments.command == "key":
            closure, digest, sections = skip_key()
            say(f"closure {closure}")
            say(f"digest  {digest}")
            for name in sorted(sections):
                say(f"  {name:<16} {sections[name]}")
            return EXIT_OK
        if arguments.command == "paths":
            for path in product_paths():
                say(path)
            return EXIT_OK
    except Broken as error:
        print(f"!! {error}", file=sys.stderr)
        return EXIT_BROKEN
    except Violation as error:
        print(f"!! {error}", file=sys.stderr)
        return EXIT_VIOLATION
    return EXIT_BROKEN  # pragma: no cover - argparse refuses an unknown command first


if __name__ == "__main__":
    sys.exit(main())
