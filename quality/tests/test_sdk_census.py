"""`python -m quality.sdk`: the census pinned both ways, re-exports imported, the goldens read."""

# does-not-cover: whether a PUBLIC name should be public — the census reads membership, not taste.
# does-not-cover: a golden reaching a platform name through a string (`setattr(m, "x")`).

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import sys
import tomllib
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from quality.djb import scope
from quality.reason_floor import MIN_REASON
from quality.sdk import census

pytestmark = pytest.mark.drives(
    "pilecap/*",
    "quality/sdk/*",
    "quality/partition.yaml",
    "TEMPLATE_VERSION",
    "apps/*/services*",
    "apps/*/selectors.py",
    "apps/*/types.py",
    "apps/*/events.py",
    "apps/core/*",
    "apps/connections/providers.py",
    "apps/usage/meters.py",
    "apps/example*",
    "pyproject.toml",
    "quality/djb/scope.py",
    "docs/sdk/pilecap.testing.md",
)

ROOT = Path(__file__).resolve().parents[2]
#: The SDK's one keep-back table, as the census reads it.
INTERNAL = "pilecap/_internal.py"


def run(root: Path, *argv: str) -> tuple[int, str]:
    """The census's exit and its printed lines, in-process."""
    out = io.StringIO()
    with redirect_stdout(out):
        rc = census.main(list(argv), root=root)
    return rc, out.getvalue()


def _ignore(directory: str, names: list[str]) -> list[str]:
    return [n for n in names if n in ("__pycache__", "migrations", "node_modules")]


@pytest.fixture
def world(tmp_path: Path) -> Path:
    """A checkout holding only what the census reads: the apps, the facade and the partition."""
    shutil.copytree(ROOT / "apps", tmp_path / "apps", ignore=_ignore)
    shutil.copytree(ROOT / "pilecap", tmp_path / "pilecap", ignore=_ignore)
    (tmp_path / "quality").mkdir()
    shutil.copy(ROOT / "quality/partition.yaml", tmp_path / "quality/partition.yaml")
    (tmp_path / census.TESTING_PAGE).parent.mkdir(parents=True)
    shutil.copy(ROOT / census.TESTING_PAGE, tmp_path / census.TESTING_PAGE)
    return tmp_path


def test_the_census_is_exact_on_this_tree() -> None:
    rc, said = run(ROOT, "--census")
    assert rc == 0, said
    assert re.search(
        r"^census: exact — \d+ names, PUBLIC \d+ · TESTING \d+ · INTERNAL \d+$", said, re.M
    )
    apps = census.census_apps(ROOT)
    assert len(apps) >= 2 and not any(a.startswith("example") for a in apps)
    for app in apps:
        assert re.search(rf"^  {app}\s+\d", said, re.M), f"{app} has no row"


def test_no_testing_re_export_is_an_unread_population() -> None:
    rc, said = run(ROOT, "--census")
    assert rc == 0, said
    assert re.search(r"^  beyond the population: \d+ PUBLIC and 0 TESTING re-exports", said, re.M)
    declared = re.search(
        r"^  testing-only: (\d+) TESTING re-exports .* declared by name", said, re.M
    )
    assert declared and int(declared.group(1)) > 0, said


def test_a_testing_only_name_off_its_page_is_red_naming_it(world: Path) -> None:
    page = world / census.TESTING_PAGE
    page.write_text(page.read_text().replace("### `pilecap.testing.bridge_registry`", "### gone"))
    rc, said = run(world, "--census")
    assert rc == 1, said
    assert "!! testing-only off its page: pilecap.testing.bridge_registry" in said


def test_the_world_is_exact_before_it_is_planted(world: Path) -> None:
    rc, said = run(world, "--census")
    assert rc == 0, said


def test_one_extra_public_def_in_a_platform_service_is_red_naming_it(world: Path) -> None:
    services = world / "apps/comms/services.py"
    services.write_text(
        services.read_text() + "\n\ndef zz_census_probe(*, tenant: object) -> None:\n    pass\n"
    )
    rc, said = run(world, "--census")
    assert rc == 1, said
    assert "!! unpartitioned: apps.comms.services.zz_census_probe (services)" in said
    assert said.rstrip().endswith("the partition is not exact")


def test_one_internal_reason_under_the_floor_is_red_naming_it(world: Path) -> None:
    table = world / INTERNAL
    text = table.read_text()
    key = "apps.core.services.tenants.close_tenant"
    found = re.search(rf'"{re.escape(key)}": \(\n\s+"([^"]+)"\n\s+\),', text)
    assert found, f"{key} is not in {INTERNAL} in the form this test plants into"
    short = "tenant-lifecycle: " + "x" * (MIN_REASON - 1)
    table.write_text(text[: found.start(1)] + short + text[found.end(1) :])
    rc, said = run(world, "--census")
    assert rc == 1, said
    assert f"!! reason under the floor: {key}: {short!r}" in said


def test_a_reason_with_no_class_and_a_stale_line_are_red(world: Path) -> None:
    table = world / INTERNAL
    text = table.read_text()
    planted = '    "apps.comms.services.zz_gone": "a reason long enough but with no class",\n'
    table.write_text(
        text.replace(
            "INTERNAL: dict[str, str] = {\n", "INTERNAL: dict[str, str] = {\n" + planted, 1
        )
    )
    rc, said = run(world, "--census")
    assert rc == 1, said
    assert "!! stale INTERNAL: apps.comms.services.zz_gone" in said
    assert "!! reason without a class: apps.comms.services.zz_gone" in said


def test_a_name_in_two_buckets_is_red(world: Path) -> None:
    facade = world / "pilecap/comms.py"
    text = facade.read_text().replace(
        "__all__ = [\n", '__all__ = [\n    "close_suppression_surge",\n', 1
    )
    facade.write_text("from apps.comms.services import close_suppression_surge\n" + text)
    rc, said = run(world, "--census")
    assert rc == 1, said
    assert (
        "!! two buckets: apps.comms.services.close_suppression_surge is public and internal" in said
    )


def test_a_core_module_nobody_declared_is_red(world: Path) -> None:
    (world / "apps/core/zz_census_probe.py").write_text("def probe() -> None:\n    pass\n")
    rc, said = run(world, "--census")
    assert rc == 1, said
    assert "!! undeclared module: apps.core.zz_census_probe" in said


def test_no_facade_is_could_not_look(world: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shutil.rmtree(world / "pilecap")
    with pytest.raises(SystemExit) as exited:
        run(world, "--census")
    assert exited.value.code == 2
    assert "!! COULD NOT LOOK: sdk census: no pilecap/ package" in capsys.readouterr().err


@pytest.fixture(scope="module")
def resolved() -> subprocess.CompletedProcess[str]:
    """`python -m quality.sdk --resolve` once: every facade module imported under Django."""
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "config.settings.test"}
    return subprocess.run(
        [sys.executable, "-m", "quality.sdk", "--resolve"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_every_reexport_resolves(resolved: subprocess.CompletedProcess[str]) -> None:
    assert resolved.returncode == 0, resolved.stdout + resolved.stderr
    modules = sum(1 for _ in census.facade_modules(ROOT))
    assert modules >= 2
    assert f"resolve: {modules} facade modules, 0 failure(s)" in resolved.stdout


def test_the_version_is_the_templates(resolved: subprocess.CompletedProcess[str]) -> None:
    version = (ROOT / "TEMPLATE_VERSION").read_text().strip()
    assert resolved.returncode == 0, resolved.stdout + resolved.stderr
    assert f"version: pilecap.__version__ = {version} = TEMPLATE_VERSION" in resolved.stdout


def test_the_goldens_imports_are_exported() -> None:
    imports = census.golden_imports(ROOT)
    assert any(not is_test for *_, is_test in imports) and any(is_test for *_, is_test in imports)
    assert census.golden_gaps(ROOT, census.partition(ROOT)) == []


def test_a_golden_production_import_of_a_testing_name_is_a_gap(world: Path) -> None:
    services = world / "apps/example/services.py"
    services.write_text("from apps.core.authz import vocabulary\n" + services.read_text())
    gaps = census.golden_gaps(world, census.partition(world))
    assert gaps == ["apps/example/services.py:1 imports apps.core.authz.vocabulary — not in PUBLIC"]


def test_the_import_contract_names_the_platform_apps_the_partition_names() -> None:
    contracts = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["importlinter"]
    held = [c for c in contracts["contracts"] if c.get("forbidden_modules") == ["pilecap"]]
    assert len(held) == 1, "one contract keeps the platform from importing pilecap"
    assert held[0]["source_modules"] == [f"apps.{a}" for a in census.census_apps(ROOT)]
    assert "pilecap" in contracts["root_packages"]


def test_a_changed_facade_file_has_a_loop_scope_row() -> None:
    assert scope.classify("pilecap/__init__.py", ROOT) == "sdk"
    assert "sdk" in scope._SHARED_SHAPES
