"""The facade read whole: every re-export form, no test module behind it, a workflow-safe import."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from quality.checks._hub import facade_reexports
from quality.sdk import census

pytestmark = pytest.mark.drives("pilecap/*", "quality/checks/_hub.py", "quality/sdk/*")

ROOT = Path(__file__).resolve().parents[2]


def facade(tmp_path: Path, text: str, name: str = "__init__") -> Path:
    """A root whose `pilecap/<name>.py` is `text`."""
    (tmp_path / "pilecap").mkdir(exist_ok=True)
    (tmp_path / "pilecap" / f"{name}.py").write_text(text)
    return tmp_path


def test_a_top_level_reexport_is_read(tmp_path: Path) -> None:
    root = facade(tmp_path, "from apps.core.models import OrgScopedModel\n")
    assert facade_reexports(root) == {
        ("pilecap", "OrgScopedModel"): ("apps.core.models", "OrgScopedModel")
    }


def test_an_assignment_alias_is_read(tmp_path: Path) -> None:
    root = facade(
        tmp_path, "from apps.core.models import OrgScopedModel\n\nScopedBase = OrgScopedModel\n"
    )
    assert facade_reexports(root)[("pilecap", "ScopedBase")] == (
        "apps.core.models",
        "OrgScopedModel",
    )


def test_a_lazy_reexport_under_type_checking_is_read(tmp_path: Path) -> None:
    text = (
        "from typing import TYPE_CHECKING\n\n"
        "if TYPE_CHECKING:\n    from apps.core.models import OrgScopedModel as ScopedBase\n"
    )
    assert facade_reexports(facade(tmp_path, text))[("pilecap", "ScopedBase")] == (
        "apps.core.models",
        "OrgScopedModel",
    )


def test_a_shim_served_name_is_read(tmp_path: Path) -> None:
    text = (
        "from apps.core.models import OrgScopedModel\n"
        "from pilecap._deprecated import Deprecation, shim\n\n"
        'DEPRECATED = {"ScopedBase": Deprecation("2.5.0", "2.6.0", "OrgScopedModel", "renamed"),'
        ' "old_now": Deprecation("2.5.0", "2.6.0", "now", "removed", "apps.core.time.now")}\n'
        "__getattr__ = shim(__name__, DEPRECATED)\n"
    )
    found = facade_reexports(facade(tmp_path, text, "tenancy"))
    assert found[("pilecap.tenancy", "ScopedBase")] == ("apps.core.models", "OrgScopedModel")
    assert found[("pilecap.tenancy", "old_now")] == ("apps.core.time", "now")


def test_no_facade_module_imports_a_test_module() -> None:
    reached = sorted(
        f"{module}.{name} ← {source}"
        for (module, name), (source, _n) in facade_reexports(ROOT).items()
        if source.rpartition(".")[2].startswith("test_") or source.endswith(".conftest")
    )
    assert reached == []


def test_the_census_reads_the_lazy_root_as_the_hub_does() -> None:
    tree = census.parse(ROOT / "pilecap/__init__.py")
    bound = census.bindings(tree, "pilecap")
    hub = {n: s for (m, n), s in facade_reexports(ROOT).items() if m == "pilecap"}
    assert bound == hub and len(bound) >= 100


ORM_PROBE = """
import sys
import pilecap.determinism
heavy = sorted(m for m in sys.modules if m.startswith(("django.db", "apps.")) and
               m not in ("apps", "apps.core", "apps.core.determinism", "apps.core.roads"))
print(heavy)
"""


def test_the_workflow_facade_imports_no_orm() -> None:
    done = subprocess.run(
        [sys.executable, "-c", ORM_PROBE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"},
    )
    assert done.returncode == 0, done.stderr[-1500:]
    assert done.stdout.strip() == "[]"


def test_the_goldens_patch_no_platform_seam_by_string() -> None:
    patched = sorted(
        f"{path.relative_to(ROOT)}:{n}"
        for path in ROOT.glob("apps/example*/**/*.py")
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if 'setattr("apps.' in line
    )
    assert patched == []


def test_the_rule_9_valve_on_the_worked_workflow_is_gone() -> None:
    text = (ROOT / "apps/example/workflows.py").read_text()
    assert "rule-96:" not in text and "from pilecap.determinism import run_to_finish" in text


def test_a_base_spelled_through_a_facade_alias_keeps_its_model_in_the_censuses(
    tmp_path: Path,
) -> None:
    from quality.worlds import descendants

    root = facade(
        tmp_path,
        "from apps.core.models import OrgScopedModel\n\nScopedBase = OrgScopedModel\n",
        "tenancy",
    )
    (root / "apps/zzz_shop").mkdir(parents=True)
    (root / "apps/zzz_shop/models.py").write_text(
        "from pilecap.tenancy import ScopedBase\n\n\nclass Shelf(ScopedBase):\n    pass\n"
    )
    assert "Shelf" in descendants(root, "OrgScopedModel")
