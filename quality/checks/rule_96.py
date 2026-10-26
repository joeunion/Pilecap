"""Rule 96: a product app imports `pilecap`, never a platform app's module."""

from __future__ import annotations

import ast
import fnmatch
from pathlib import Path

import yaml

from quality.checks._hub import FACADE, CheckResult, _parse, facade_reexports

#: The worked example's labels: judged on the template, where no product app exists yet.
WORKED_EXAMPLE = "example*"
#: The shared test harness under `apps/`, no app of anyone's (`quality.djb.scope.HARNESS_DIR`).
HARNESS = "testing"
#: The drawer that declares a product's namespace (ADR gate-5).
DRAWER = "quality/local/rules.yaml"
#: How deep a re-export chain is followed to the name a facade module binds.
DEPTH = 4


def _platform_apps(root: Path) -> set[str]:
    """`platform_apps:` of the partition lockfile; unreadable is empty, which the floor refuses."""
    try:
        doc = yaml.safe_load((root / "quality/partition.yaml").read_text())
    except (OSError, yaml.YAMLError):
        return set()
    return {str(a) for a in (doc or {}).get("platform_apps") or []}


def _namespaced(root: Path) -> bool:
    from quality.engine.rules import declared_namespace  # the engine imports this module

    try:
        doc = yaml.safe_load((root / DRAWER).read_text())
    except (OSError, yaml.YAMLError):
        return False
    return declared_namespace(doc if isinstance(doc, dict) else {}) is not None


def _judged(root: Path, platform: set[str], out: CheckResult) -> list[Path]:
    """The app directories this tree's rule reads: product apps, and the example on the template."""
    namespaced = _namespaced(root)
    judged: list[Path] = []
    for app in sorted(p for p in (root / "apps").iterdir() if p.is_dir()):
        if app.name.startswith("__") or app.name == HARNESS:
            continue
        out.count("apps_classified")
        worked = fnmatch.fnmatchcase(app.name, WORKED_EXAMPLE)
        if app.name not in platform or (worked and not namespaced):
            judged.append(app)
    return judged


def _bindings(tree: ast.Module) -> dict[str, tuple[str, str]]:
    """Each top-level `from M import a as b` (absolute): `b` → (M, a)."""
    out: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                out[alias.asname or alias.name] = (node.module, alias.name)
    return out


def _module_path(root: Path, module: str) -> Path | None:
    base = root.joinpath(*module.split("."))
    for path in (base.with_suffix(".py"), base / "__init__.py"):
        if path.is_file():
            return path
    return None


class _Facade:
    """Which `pilecap` module carries a platform name, read off the facade's files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.carriers: dict[tuple[str, str], list[str]] = {}
        self.modules: dict[str, set[str]] = {}
        for (facade, local), (source, name) in facade_reexports(root).items():
            if source.startswith("apps."):
                self.carriers.setdefault((source, name), []).append(f"{facade}.{local}")
                self.modules.setdefault(source, set()).add(facade)

    def names(self) -> int:
        return sum(len(v) for v in self.carriers.values())

    def carrier(self, module: str, name: str) -> list[str]:
        """The facade spellings of `module.name`, following re-exports to their source."""
        for _ in range(DEPTH):
            found = self.carriers.get((module, name))
            if found:
                return sorted(found)
            path = _module_path(self.root, module)
            tree = _parse(path) if path is not None else None
            bound = _bindings(tree).get(name) if tree is not None else None
            if bound is None:
                return []
            module, name = bound
        return []

    def module_carriers(self, module: str) -> list[str]:
        inside = [fs for src, fs in self.modules.items() if f"{src}.".startswith(f"{module}.")]
        return sorted(set().union(*inside)) if inside else []


def _platform_target(module: str, platform: set[str]) -> bool:
    parts = module.split(".")
    return len(parts) >= 2 and parts[0] == "apps" and parts[1] in platform


def _road(carriers: list[str], production: bool) -> str:
    usable = [c for c in carriers if not (production and c.startswith(f"{FACADE}.testing."))]
    if usable:
        module, _, name = usable[0].rpartition(".")
        return f"use `from {module} import {name}`"
    if carriers:
        return f"{carriers[0]} is the testing half's — production code has no public name for it"
    return "pilecap has no public name for it"


def _lacks(spelled: str, road: str) -> str:
    if road.startswith("use "):
        return road
    return (
        f"{road}. On the template that is a finding against the facade, not a valve; on a "
        f'product, same day: keep the line and add the valve "# rule-96: pilecap lacks {spelled}'
        ' — <job>"; it is counted and printed, and the printed line IS your platform-feedback '
        "row (docs/product/queue.md § platform feedback)"
    )


def product_apps_import_the_sdk_only(root: Path, rule: dict) -> CheckResult:
    """Rule 96. Every `apps.<platform>` import in a judged app, named with the `pilecap` road."""
    out = CheckResult()
    platform = _platform_apps(root)
    out.count("platform_apps", len(platform))
    facade = _Facade(root)
    out.count("facade_names", facade.names())
    judged = _judged(root, platform, out)
    platform -= {app.name for app in judged}
    for app in judged:
        for path in sorted(app.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if "/migrations/" in rel or "__pycache__" in rel:
                continue
            tree = _parse(path)
            if tree is None:
                continue
            out.count("files_scanned")
            production = "/tests/" not in rel and path.name != "conftest.py"
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if _platform_target(alias.name, platform):
                            carried = ", ".join(facade.module_carriers(alias.name)) or "none"
                            out.hit(
                                rel,
                                node.lineno,
                                f"imports the platform module {alias.name} — a product reaches "
                                f"the platform through `pilecap` only; the facade modules "
                                f"carrying its names: {carried}",
                            )
                elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                    if not _platform_target(node.module, platform):
                        continue
                    for alias in node.names:
                        spelled = f"{node.module}.{alias.name}"
                        if _module_path(root, spelled) is not None:
                            carried = ", ".join(facade.module_carriers(spelled)) or "none"
                            road = f"the facade modules carrying its names: {carried}"
                        else:
                            road = _lacks(
                                spelled,
                                _road(facade.carrier(node.module, alias.name), production),
                            )
                        out.hit(rel, node.lineno, f"imports {spelled} — {road}")
    return out
