# census: cross-app population=apps/core/scaffold/arms/*.py drives the field arm on a tree copy
"""`scaffold field`: named to the house rules, reverted when refused, removed by anchor, marked."""

# does-not-cover: every field kind's copy building — `quality/tests/test_golden_copy.py` builds it.

from __future__ import annotations

import io
import os
import re
import secrets
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from apps.core.scaffold.copier import ruff
from apps.core.tests.platform_tree import platform_tree
from apps.core.tests.tree_census import source_text

ROOT = Path(__file__).resolve().parents[3]
LABEL, NOUN = "gizmoes", "Gear"


@pytest.fixture(autouse=True)
def _the_platforms_frozen_families(monkeypatch: pytest.MonkeyPatch) -> None:
    """The cases scaffold onto the platform's tree: no product drawer's family is frozen."""
    from apps.core.api import frozen_families

    monkeypatch.setattr(frozen_families, "FROZEN_FAMILIES", frozen_families.CORE_FAMILIES)


def _scaffold(*argv: str) -> str:
    """`manage.py scaffold <argv>`'s standard output, in this process."""
    out = io.StringIO()
    call_command("scaffold", *argv, stdout=out)
    return out.getvalue()


def _noun_tree(tmp_path: Path) -> Path:
    """A namespaced scratch tree through links, its own `apps/` and budgets, the noun scaffolded."""
    root = platform_tree(tmp_path, "zzzf1d")
    for rel in ("quality/budgets.yaml", "apps/conftest_local.py"):
        if (root / rel).is_symlink():
            (root / rel).unlink()
            (root / rel).write_text((ROOT / rel).read_text())
    with override_settings(BASE_DIR=root):
        _scaffold("noun", LABEL, NOUN)
    return root


def _written(root: Path) -> dict[str, str]:
    """Every file a field's write or revert may touch, by path, with its text."""
    owned = [root / "apps" / LABEL, root / "quality/local", root / "apps/conftest_local.py"]
    found = {p for top in owned if top.exists() for p in [top, *top.rglob("*")] if p.is_file()}
    found.add(root / "quality/budgets.yaml")
    return {
        p.relative_to(root).as_posix(): source_text(p)
        for p in sorted(found)
        if "__pycache__" not in p.parts
    }


@pytest.fixture(scope="module")
def noun_root(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """One scaffolded noun the refusal cases share: each proves it wrote nothing."""
    yield _noun_tree(tmp_path_factory.mktemp("field_refusals"))


# --- 1 · the naming rules, before the first write -------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "said"),
    [
        ("on:date?", "a DateField's name ends `_on` (house rule 15)."),
        ("when:datetime?", "a DateTimeField's name ends `_at` (house rule 15)."),
        ("deleted:bool?", "no `is_deleted` booleans"),
        ("id:uuid?", "`id` is `Gear`'s already"),
        ("tenant:str?", "`tenant` is `Gear`'s already"),
        ("organization:str?", "`organization` is `Gear`'s already"),
        ("created_at:datetime?", "`created_at` is `Gear`'s already"),
        ("updated_at:datetime?", "`updated_at` is `Gear`'s already"),
        ("archived_at:datetime?", "`archived_at` is `Gear`'s already"),
        ("version:int?", "`version` is `Gear`'s already"),
    ],
)
def test_naming_rules_refuse_before_the_first_write(
    noun_root: Path, settings: Any, spec: str, said: str
) -> None:
    settings.BASE_DIR = noun_root
    before = _written(noun_root)
    with pytest.raises(CommandError) as refused:
        _scaffold("field", LABEL, NOUN, spec)
    assert refused.value.returncode == 2, str(refused.value)
    assert said in str(refused.value) and "Nothing was written." in str(refused.value)
    assert _written(noun_root) == before


def test_the_naming_sentences_are_the_system_checks_own() -> None:
    from django.db import models

    from apps.core.checks import field_name_policy
    from apps.core.scaffold.arms.field import naming_refusal

    for spec_type, field_class, name in (
        ("date", models.DateField, "on"),
        ("datetime", models.DateTimeField, "when"),
        ("bool", models.BooleanField, "deleted"),
    ):
        sentence = field_name_policy(field_class, name)
        assert sentence and sentence in (naming_refusal(name, spec_type) or "")
    assert naming_refusal("due_on", "date") is None
    assert naming_refusal("due_at", "datetime") is None


# --- the tracked tree: a field's write runs `makemigrations` there, as a product's does -----------

PLANTED = '''

class PlantedBare(models.Model):
    """Planted: a bare model, so the system checks `makemigrations` runs refuse (rule 2)."""
'''


@dataclass
class Tracked:
    """The tracked tree copied whole, the noun scaffolded into it, and its commands' env."""

    root: Path
    env: dict[str, str]

    def run(self, *argv: str) -> subprocess.CompletedProcess[str]:
        """`manage.py <argv>` in the copy."""
        return subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `python`, no shell
            [sys.executable, "manage.py", *argv],
            cwd=self.root,
            env=self.env,
            capture_output=True,
            text=True,
        )

    def files(self) -> dict[str, str]:
        """The app's files and the shared ones a write records into, by path, with their text."""
        app_dir = self.root / "apps" / LABEL
        found = [p for p in sorted(app_dir.rglob("*")) if "__pycache__" not in p.parts]
        found += [self.root / "quality/budgets.yaml", self.root / "apps/conftest_local.py"]
        return {p.relative_to(self.root).as_posix(): source_text(p) for p in found if p.is_file()}

    @contextmanager
    def planted(self) -> Iterator[None]:
        """The app's models carrying a bare model the system checks refuse, taken out after."""
        models = self.root / "apps" / LABEL / "models.py"
        models.write_text(models.read_text() + PLANTED)
        try:
            yield
        finally:
            models.write_text(models.read_text().removesuffix(PLANTED))


@pytest.fixture(scope="module")
def tracked(tmp_path_factory: pytest.TempPathFactory) -> Tracked:
    """One tracked copy with the noun in it; each case adds its own field name."""
    if shutil.which("tar") is None:
        pytest.skip("no tar on PATH — the tracked tree is copied with it")
    root = tmp_path_factory.mktemp("field_tracked") / "tree"
    root.mkdir()
    copied = subprocess.run(  # noqa: S603 — `bash -c` over a pipeline this test writes; no caller input
        ["bash", "-c", f"git ls-files -z | tar --null -T - -cf - | tar -xf - -C {str(root)!r}"],  # noqa: S607 — `bash` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert copied.returncode == 0, copied.stderr
    if (ROOT / ".env").is_file():
        shutil.copy(ROOT / ".env", root / ".env")
    (root / "quality/local").mkdir(parents=True, exist_ok=True)
    (root / "quality/local/rules.yaml").write_text("rule_id_namespace: zzzf1r\n")
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_NAME": f"djb_scaffold_{secrets.token_hex(3)}",
        "DATABASE_URL": "",
    }
    tree = Tracked(root, env)
    for argv in (("newapp", LABEL), ("scaffold", "noun", LABEL, NOUN)):
        done = tree.run(*argv)
        assert done.returncode == 0, (argv, done.stdout + done.stderr)
    return tree


# --- 2 · a refused migration leaves nothing -------------------------------------------------------


def test_a_refused_migration_leaves_no_anchor(tracked: Tracked) -> None:
    with tracked.planted():
        before = tracked.files()
        done = tracked.run("scaffold", "field", LABEL, NOUN, "shade:str?", "--skip-checks")
        after = tracked.files()
    assert done.returncode == 1, done.stdout + done.stderr
    assert "makemigrations gizmoes refused" in done.stderr and "PlantedBare" in done.stderr
    reverted = [line for line in done.stdout.splitlines() if line.startswith("reverted: ")]
    assert len(reverted) == 1, done.stdout
    assert re.fullmatch(
        r"reverted: [1-9]\d* lines in [1-9]\d* files — nothing of this field remains", reverted[0]
    ), reverted
    assert "undo: " not in done.stdout
    assert after == before


# --- 3 · `--remove` reverts by anchor on a tree whose check fails ---------------------------------


def test_remove_runs_on_a_tree_that_fails_check(tracked: Tracked) -> None:
    before = tracked.files()
    added = tracked.run("scaffold", "field", LABEL, NOUN, "color:str?")
    assert added.returncode == 0, added.stdout + added.stderr
    assert f"undo: scaffold field {LABEL} {NOUN} color:str? --remove" in added.stdout
    with tracked.planted():
        checked = tracked.run("check")
        assert checked.returncode == 1 and "PlantedBare" in checked.stdout + checked.stderr
        removed = tracked.run("scaffold", "field", LABEL, NOUN, "color:str?", "--remove")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert re.search(
        r"^removed apps/gizmoes/migrations/\d{4}_gear_color\.py$", removed.stdout, re.M
    )
    after = tracked.files()
    budgets = "quality/budgets.yaml"
    assert {k: v for k, v in after.items() if k != budgets} == {
        k: v for k, v in before.items() if k != budgets
    }


def test_remove_refuses_a_module_holding_lines_the_scaffold_never_wrote(tracked: Tracked) -> None:
    added = tracked.run("scaffold", "field", LABEL, NOUN, "tint:str?")
    assert added.returncode == 0, added.stdout + added.stderr
    services = tracked.root / "apps" / LABEL / "services.py"
    services.write_text(services.read_text().replace("tint=tint", "tint=tint or None", 1))
    before = tracked.files()
    removed = tracked.run("scaffold", "field", LABEL, NOUN, "tint:str?", "--remove")
    assert removed.returncode == 2, removed.stdout + removed.stderr
    assert "apps/gizmoes/services.py is not the module the scaffold wrote `tint` into" in (
        removed.stderr
    )
    assert tracked.files() == before


# --- 4 · one import per name ----------------------------------------------------------------------


def test_uuid_on_a_module_that_imports_uuid_adds_no_second_import(tracked: Tracked) -> None:
    app_dir = tracked.root / "apps" / LABEL
    held = {rel: (app_dir / rel).read_text() for rel in ("api.py", "mcp.py", "schemas.py")}
    assert all("from uuid import UUID\n" in text for text in held.values())
    done = tracked.run("scaffold", "field", LABEL, NOUN, "part_ref:uuid?")
    assert done.returncode == 0, done.stdout + done.stderr
    for rel in held:
        text = (app_dir / rel).read_text()
        assert "part_ref" in text, rel
        assert text.count("from uuid import UUID\n") == 1, rel
    linted = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `ruff`, no shell
        [ruff(), "check", *(str(app_dir / rel) for rel in held)],
        cwd=tracked.root,
        capture_output=True,
        text=True,
    )
    assert linted.returncode == 0, linted.stdout + linted.stderr


def test_the_import_helper_reads_what_a_module_already_binds() -> None:
    from apps.core.scaffold.arms._common import lacks_import

    module = "from uuid import UUID\nimport decimal\n# isort: split\nfrom pilecap import example\n"
    assert not lacks_import(module, "from uuid import UUID")
    assert not lacks_import(module, "from pilecap import example")
    assert lacks_import(module, "from decimal import Decimal")
    assert lacks_import(module, "from datetime import date")


# --- 5 · a person's field is marked ---------------------------------------------------------------


def test_a_personal_name_writes_the_mark_and_a_shaped_example(tracked: Tracked) -> None:
    from quality.checks.rule_93 import personal_fields_declared

    done = tracked.run("scaffold", "field", LABEL, NOUN, "contact_email:str?")
    assert done.returncode == 0, done.stdout + done.stderr
    app_dir = tracked.root / "apps" / LABEL
    schemas = (app_dir / "schemas.py").read_text()
    out = schemas[schemas.index(f"class {NOUN}Out(") :]
    out = out[: out.index("\nclass ")]
    assert re.search(
        r"contact_email: str \| None = Field\(\s*default=None,\s*"
        r'json_schema_extra=personal\(example\("sam@example\.com"\)\)',
        out,
    ), out
    assert "sam@example.com" in schemas
    for rel in ("tests/test_api.py", "tests/test_mcp.py", "tests/test_services.py"):
        text = (app_dir / rel).read_text()
        assert "@example.com" in text, rel
    rules = yaml.safe_load((ROOT / "quality/rules.yaml").read_text())["rules"]
    rule = next(r for r in rules if str(r.get("id")) == "93")
    found = personal_fields_declared(tracked.root, rule).findings
    assert not [f for f in found if f"apps/{LABEL}/" in f.path], found


def test_a_word_outside_the_lexicon_keeps_the_plain_samples() -> None:
    from apps.core.scaffold.arms._common import FIELD_TYPES
    from apps.core.scaffold.arms.field import personal_kind

    assert personal_kind(NOUN, "nickname", FIELD_TYPES["str"]) is None
    marked = personal_kind(NOUN, "phone", FIELD_TYPES["str"])
    assert marked is not None and marked.personal and "First" not in str(marked.python)
    assert personal_kind(NOUN, "phone", FIELD_TYPES["int"]) is None


# --- 6 · the arm says what it does not cover ------------------------------------------------------


def test_the_field_arm_declares_what_it_does_not_cover() -> None:
    text = (ROOT / "apps/core/scaffold/arms/field.py").read_text()
    declared = [line for line in text.splitlines() if line.startswith("# does-not-cover: ")]
    for hole in ("a default", "a non-nullable column", "a child row"):
        assert any(hole in line for line in declared), (hole, declared)
