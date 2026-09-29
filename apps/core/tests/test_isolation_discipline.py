# census: cross-app population=apps/**/tests/** for the bare isolate_apps sites
"""Every test that builds a throwaway registry builds it with `isolated_apps`.

Django's `isolate_apps` leaves a planted model's relation graph written onto the
real classes it registered (`apps/core/tests/isolation.py` has the mechanism
and the fix). `isolated_apps` is the drop-in that rebuilds the real caches on
the way out; this census reads every file under `apps/**/tests/**` and names
each import or use of `isolate_apps` that does not come from
`apps.core.tests.isolation`.

**The walk is the partition's own** (`quality.partition.tree_paths`: tracked,
plus untracked-non-ignored), so a test file written a minute ago and not yet
committed is read — the direction that has to be right for a census run at
`--loop`.

**Parsed, not grepped**, so a docstring that explains `isolate_apps` (several
do, this one included) is prose and never a site; only an `import`, a
`from … import`, a name or an attribute load spelled `isolate_apps` counts.

DOES NOT COVER: a spelling that never writes the name — `getattr(utils,
"isolate_" + "apps")`, `importlib`, a hand-built `Apps` registry. Those are
the registry-integrity guard's (`apps/conftest.py`,
`_no_module_rewrites_the_real_registry`): it reads the RESULT at every module's
teardown and names the module whatever road it took, which is why it exists
beside this and was built first.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings

from apps.core.tests.tree_census import source_tree
from quality.partition import tree_paths

BASE_DIR = Path(str(settings.BASE_DIR))

#: The one module a test may take the throwaway registry from.
BLESSED = "apps.core.tests.isolation"

#: Django's name for the thing, which is the spelling this census refuses.
BARE = "isolate_apps"


def _in_a_tests_tree(path: str) -> bool:
    parts = Path(path).parts
    return path.endswith(".py") and parts[:1] == ("apps",) and "tests" in parts[2:-1]


def bare_sites(tree: ast.AST) -> list[tuple[int, str]]:
    """(line, what) for every import or use of `isolate_apps` not taken from `BLESSED`."""
    sites: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            for alias in node.names:
                if alias.name == BARE and source != BLESSED:
                    sites.append((node.lineno, f"from {source} import {BARE}"))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[-1] == BARE:
                    sites.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.Name) and node.id == BARE:
            sites.append((node.lineno, BARE))
        elif isinstance(node, ast.Attribute) and node.attr == BARE:
            sites.append((node.lineno, f"….{BARE}"))
    return sorted(set(sites))


def census(paths: list[str]) -> list[str]:
    """`path:line  what` for every bare site in `paths` (repository-relative)."""
    found: list[str] = []
    for path in paths:
        tree = source_tree(BASE_DIR / path)
        found.extend(f"{path}:{line}  {what}" for line, what in bare_sites(tree))
    return found


#: The blessed module is the one place Django's class is imported: it subclasses it.
HOME = "apps/core/tests/isolation.py"


def _population() -> list[str]:
    return [path for path in tree_paths() if _in_a_tests_tree(path) and path != HOME]


def test_the_census_reads_a_real_population() -> None:
    """An empty walk is a census that stopped looking, not a clean tree."""
    population = _population()
    assert len(population) > 100, population
    assert "apps/core/tests/test_isolation_discipline.py" in population
    assert "apps/core/tests/test_archivable.py" in population


def test_every_throwaway_registry_is_built_with_isolated_apps() -> None:
    bare = census(_population())
    assert bare == [], (
        "`isolate_apps` used without the teardown that rebuilds the real models' relation "
        "caches:\n    "
        + "\n    ".join(bare)
        + f"\n  Import `isolated_apps` from `{BLESSED}` instead — the same arguments, the "
        "same decorator and context-manager forms."
    )


def test_the_census_fires_on_each_spelling_and_not_on_prose_or_the_blessed_import() -> None:
    """The canary, in process: each bare spelling named, each blessed one silent."""
    planted = ast.parse(
        "from django.test.utils import isolate_apps\n"
        "import django.test.utils\n"
        "@isolate_apps('apps.core')\n"
        "def test_a(): ...\n"
        "def test_b():\n"
        "    with django.test.utils.isolate_apps('apps.core'): ...\n"
    )
    assert [line for line, _ in bare_sites(planted)] == [1, 3, 6]

    silent = ast.parse(
        '"""Built under `isolate_apps`, which this docstring only mentions."""\n'
        "from apps.core.tests.isolation import isolated_apps\n"
        "@isolated_apps('apps.core')\n"
        "def test_a(): ...\n"
    )
    assert bare_sites(silent) == []


def test_the_registry_guard_names_a_model_class_left_registered_and_not_an_isolated_one() -> None:
    """The teardown guard's canary, in process: a bare class named, an isolated one silent.

    The census above reads a spelling; the guard in `apps/conftest.py` reads the
    registry. A model class defined bare in a test body spells nothing this
    census knows — it joins the real registry and stays, and every registry
    reader after it on that worker counts it. The guard's difference names it;
    the same class under `isolated_apps` leaves nothing to name. The plant is
    taken back out in a `finally`, so the canary is not itself the leak.
    """
    from django.apps import apps as global_apps

    from apps.core import authz
    from apps.core.audit import AuditEntry
    from apps.core.tests.isolation import (
        isolated_apps,
        registry_difference,
        registry_field_names,
    )

    before = registry_field_names()
    with isolated_apps("apps.core"):

        class IsolatedRegistryPlant(AuditEntry):
            class Meta:
                proxy = True

    assert registry_difference(before, registry_field_names()) == []

    class BareRegistryPlant(AuditEntry):
        class Meta:
            proxy = True

    try:
        assert registry_difference(before, registry_field_names()) == [
            "core.BareRegistryPlant · joined the registry"
        ]
    finally:
        global_apps.all_models["core"].pop("bareregistryplant", None)
        global_apps.clear_cache()
        authz.reset_policies()
    assert registry_difference(before, registry_field_names()) == []
