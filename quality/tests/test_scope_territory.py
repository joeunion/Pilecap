"""A product's `newapp` + `scaffold noun` writes only inside the territory scope.py declares."""

# does-not-cover: `scaffold screen` and the additive arms — the noun arm's writes are the census.

from __future__ import annotations

import secrets
import shutil
import subprocess

import pytest

from quality.djb import scope
from quality.tests.fixtures.scratch import require_scratch
from quality.tests.test_layer_boundary import ROOT, build_mirror, clean_env, git

pytestmark = pytest.mark.drives(
    "quality/djb/scope.py",
    "apps/core/scaffold/",
    "apps/core/management/commands/newapp.py",
)


def test_a_product_scaffold_writes_nothing_outside_the_declared_territory(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    home = require_scratch(tmp_path_factory.mktemp("territory"), ROOT)
    tree = build_mirror(home / "mirror")
    try:
        (tree / "quality/local").mkdir(parents=True, exist_ok=True)
        (tree / "quality/local/rules.yaml").write_text("rule_id_namespace: zzzt4y\n")
        git(tree, "add", "quality/local/rules.yaml")
        git(tree, "commit", "-q", "--no-verify", "-m", "zzzt4y: the product declares")
        env = clean_env(
            DJANGO_SETTINGS_MODULE="config.settings.test",
            DATABASE_NAME=f"djb_territory_{secrets.token_hex(3)}",
            DATABASE_URL="",
        )
        for argv in (("newapp", "gizmoes"), ("scaffold", "noun", "gizmoes", "Gear")):
            done = subprocess.run(  # noqa: S603 — argv from constants; the mirror's interpreter
                [".venv/bin/python", "manage.py", *argv],
                cwd=tree,
                env=env,
                capture_output=True,
                text=True,
            )
            assert done.returncode == 0, (argv, done.stdout + done.stderr)
        changed = git(tree, "diff", "--name-only", "HEAD").splitlines()
        added = git(tree, "ls-files", "--others", "--exclude-standard").splitlines()
        written = sorted({*changed, *added} - {""})
        assert any(p.startswith("apps/gizmoes/") for p in written), written
        platform = scope.platform_apps(tree)
        outside = [
            p
            for p in written
            if not scope.is_product_path(p, platform)
            and p not in scope.ROW_DERIVED
            and not p.startswith(scope.PRODUCT_DRAWER)
        ]
        assert outside == [], outside
    finally:
        shutil.rmtree(home, ignore_errors=True)
