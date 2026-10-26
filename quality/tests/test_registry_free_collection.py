"""Every gate test module collects with no app registry, because CI's selftest shards have none."""

# census: cross-app population=quality/tests/ every module under quality/tests is its subject

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.harness import is_could_not_look, pytest_report_teststatus

pytestmark = pytest.mark.drives("quality/tests/harness.py")

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / "quality" / "tests"
#: The errors an import raises when it reached the app registry with no settings module.
REGISTRY_ERRORS = ("ImproperlyConfigured", "AppRegistryNotReady")

#: CI's shards read no `.env` file and export a derived name: the worker models that.
CENSUS_ENV = {"DATABASE_NAME": "djb_collection_census"}
#: Imports each named module in order, one JSON line each; stops after one that configured Django.
WORKER = r"""
import importlib, json, os, sys, traceback
roots, names = sys.argv[1].split(os.pathsep), sys.argv[2:]
sys.path[:0] = roots
try:
    import environ
    environ.Env.read_env = classmethod(lambda cls, *args, **kwargs: None)
except ImportError:
    pass
for name in names:
    out = {"module": name}
    try:
        importlib.import_module(name)
    except BaseException as exc:
        out["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"
        out["kind"] = type(exc).__name__
        out["chain"] = [
            f"{os.path.relpath(f.filename, roots[0])}:{f.lineno} {f.line}"
            for f in traceback.extract_tb(exc.__traceback__)
            if any(f.filename.startswith(r + os.sep) for r in roots)
            and os.sep + ".venv" + os.sep not in f.filename
        ]
    print(json.dumps(out), flush=True)
    conf = sys.modules.get("django.conf")
    if os.environ.get("DJANGO_SETTINGS_MODULE") or (conf and conf.settings.configured):
        print(json.dumps({"configured": name}), flush=True)
        break
"""


def withheld_env(root: Path) -> dict[str, str]:
    """This environment less the settings module and every key `.env` names, plus `CENSUS_ENV`."""
    dotenv = root / ".env"
    keys = {"DJANGO_SETTINGS_MODULE"}
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            name = line.split("=", 1)[0].removeprefix("export ").strip()
            if "=" in line and name and not name.startswith("#"):
                keys.add(name)
    kept = {k: v for k, v in os.environ.items() if k not in keys and not k.startswith("PYTEST_")}
    return {**kept, **CENSUS_ENV}


def module_names(home: Path = HOME, root: Path = ROOT) -> list[str]:
    """Every module under `home` but the fixture worlds, dotted from `root`."""
    return sorted(
        ".".join(p.relative_to(root).with_suffix("").parts).removesuffix(".__init__")
        for p in home.rglob("*.py")
        if "fixtures" not in p.relative_to(home).parts and "__pycache__" not in p.parts
    )


def registry_needers(names: Sequence[str], roots: Sequence[Path] = (ROOT,)) -> list[dict[str, str]]:
    """Each module of `names` whose import, with no settings module, raised a registry error."""
    left, found = list(names), []
    while left:
        done = subprocess.run(
            [sys.executable, "-I", "-c", WORKER, os.pathsep.join(map(str, roots)), *left],
            cwd=roots[0],
            env=withheld_env(ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        seen: list[str] = []
        for line in done.stdout.splitlines():
            row = json.loads(line)
            if "module" in row:
                seen.append(row["module"])
                if row.get("kind") in REGISTRY_ERRORS:
                    found.append(row)
        if not seen:
            raise CouldNotLook(
                f"the collection census imported nothing (exit {done.returncode}): {done.stderr}"
            )
        left = left[len(seen) :]
    return found


def named(rows: Sequence[dict[str, str]]) -> str:
    """One line per refused module: the module, the import chain that needed the registry, why."""
    return "\n".join(
        f"{row['module']}: {' -> '.join(row['chain']) or '(no frame in the checkout)'}"
        f" — {row['error']}"
        for row in rows
    )


def test_every_shipped_module_collects_without_a_registry() -> None:
    names = module_names()
    assert len(names) > 100, names
    found = registry_needers(names)
    assert not found, (
        "these modules import the app registry at collection, which CI's selftest shards do not"
        " have (DJANGO_SETTINGS_MODULE unset; the checkout's .env withheld):\n" + named(found)
    )


def test_a_planted_module_that_imports_the_registry_is_named(tmp_path: Path) -> None:
    package = tmp_path / "planted_census"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "test_needs.py").write_text("from apps.core.models import Tenant  # noqa: F401\n")
    (package / "test_clean.py").write_text("import json  # noqa: F401\n")
    rows = registry_needers(
        ["planted_census.test_clean", "planted_census.test_needs"], roots=(tmp_path, ROOT)
    )
    assert [row["module"] for row in rows] == ["planted_census.test_needs"], rows
    assert "test_needs.py:1 from apps.core.models import Tenant" in named(rows), named(rows)
    assert "ImproperlyConfigured" in rows[0]["error"], rows


def test_a_dotenv_with_an_empty_database_name_does_not_red_the_census(tmp_path: Path) -> None:
    package = tmp_path / "planted_dotenv"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / ".env").write_text("DATABASE_NAME=\n")
    (package / "test_reads_env.py").write_text(
        "import os\nfrom pathlib import Path\n\nimport environ\n"
        "from django.core.exceptions import ImproperlyConfigured\n\n"
        "environ.Env().read_env(str(Path(__file__).with_name('.env')))\n"
        "if not os.environ.get('DATABASE_NAME'):\n"
        "    raise ImproperlyConfigured('DATABASE_NAME is not set')\n"
    )
    rows = registry_needers(["planted_dotenv.test_reads_env"], roots=(tmp_path, ROOT))
    assert rows == [], named(rows)


def test_a_module_that_configures_django_does_not_hide_the_next(tmp_path: Path) -> None:
    package = tmp_path / "planted_order"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "test_a_sets.py").write_text(
        "import os\nos.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.test'\n"
    )
    (package / "test_b_needs.py").write_text("from apps.core.models import Tenant  # noqa: F401\n")
    rows = registry_needers(
        ["planted_order.test_a_sets", "planted_order.test_b_needs"], roots=(tmp_path, ROOT)
    )
    assert [row["module"] for row in rows] == ["planted_order.test_b_needs"], rows


def test_a_product_path_no_gate_module_quotes_exists() -> None:
    """A withheld-selftest live proof touches one, e.g. `apps/example/admin.py` at 7f7d13158."""
    from quality import loop_key
    from quality.djb import scope

    listed = subprocess.run(
        ["git", "ls-files", "-z", "apps/"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    paths = frozenset(p for p in listed.stdout.split("\0") if p)
    quoted: set[str] = set()
    for file in loop_key.reader_files(ROOT, scope.SELFTEST_CLOSURE.quoters):
        text = file.read_text(encoding="utf-8", errors="surrogateescape")
        quoted |= {needle for _, needle in loop_key.quoted_needles(text, paths)}
    unquoted = sorted(paths - quoted)
    assert unquoted, f"every one of {len(paths)} paths under apps/ is quoted by a gate module"
    assert scope.selftest_reach(ROOT, unquoted[:1]) is None, unquoted[0]


def test_a_collect_report_is_read_as_its_own_collection_error(pytestconfig: pytest.Config) -> None:
    report = pytest.CollectReport(
        "quality/tests/test_planted.py", "failed", "planted collection error", []
    )
    assert is_could_not_look(report) is False
    assert pytest_report_teststatus(report, pytestconfig) is None


def test_a_module_that_cannot_collect_prints_its_error_never_the_harness_traceback(
    nested_pytest: Callable[..., tuple[int, str]],
) -> None:
    rc, out = nested_pytest({"test_c.py": "raise ImportError('planted collection error')\n"})
    assert rc in (1, 2), out
    assert "planted collection error" in out, out
    assert "user_properties" not in out, out
