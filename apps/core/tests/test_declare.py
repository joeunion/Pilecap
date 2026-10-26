"""`manage.py declare <ns>` writes the product's day-zero declaration once, from the tree."""

# does-not-cover: the hook's verdict on the declared tree — the proof from zero commits it.

from __future__ import annotations

import io
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.core.management.commands import declare
from quality.engine.world import RULES, is_template_id

SHAPE = "DJB_IDENTITY_SHAPE=platform_apps=own"  # pragma: allowlist secret
TRACKED = "identity_shape: platform_apps=own"
ROOT = Path(__file__).resolve().parents[3]


def _git(root: Path, *argv: str) -> str:
    done = subprocess.run(  # noqa: S603 — argv list built here from constants and paths; `git`, no shell
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *argv],  # noqa: S607 — `git` resolved on PATH, as the gate's own legs run it
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def _tree(tmp_path: Path, *, product_app: bool = False) -> Path:
    root = tmp_path / "clone"
    (root / "quality").mkdir(parents=True)
    (root / "quality/partition.yaml").write_text("platform_apps:\n  - core\n  - accounts\n")
    (root / "TEMPLATE_VERSION").write_text("9.9.9\n")
    for app in ("core", "accounts", *(("zebras",) if product_app else ())):
        (root / "apps" / app).mkdir(parents=True)
        (root / "apps" / app / "apps.py").write_text('"""An app."""\n')
    (root / ".env").write_text("DEBUG=1\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "--", "quality", "TEMPLATE_VERSION", "apps")
    _git(root, "commit", "-q", "-m", "the template")
    return root


def _declare(root: Path, namespace: str = "acme") -> str:
    out = io.StringIO()
    call_command("declare", namespace, root=str(root), stdout=out)
    return out.getvalue()


def _written(root: Path) -> dict[str, str]:
    paths = ("quality/local/rules.yaml", "scripts/local/template-base", ".env")
    return {p: (root / p).read_text() for p in paths if (root / p).is_file()}


def _through() -> int:
    return max(int(r["id"]) for r in RULES if is_template_id(str(r["id"])))


def test_a_fresh_clone_gets_the_drawer_and_the_base(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    said = _declare(root)
    assert _written(root)["quality/local/rules.yaml"] == (
        f"rule_id_namespace: acme\ntemplate_rule_ids_through: {_through()}\n"
    )
    assert _written(root)["scripts/local/template-base"] == _git(root, "rev-parse", "HEAD") + "\n"
    assert _written(root)[".env"] == "DEBUG=1\n"
    assert SHAPE in said
    assert said.rstrip().splitlines()[-1] == (
        "next: git add quality/local/rules.yaml scripts/local/template-base && git commit"
    )


def test_a_product_app_adds_the_identity_line_to_env(tmp_path: Path) -> None:
    root = _tree(tmp_path, product_app=True)
    _declare(root)
    assert _written(root)[".env"] == f"DEBUG=1\n{SHAPE}\n"


def test_a_product_app_declares_the_shape_in_the_tracked_drawer(tmp_path: Path) -> None:
    root = _tree(tmp_path, product_app=True)
    said = _declare(root)
    assert _written(root)["quality/local/rules.yaml"] == (
        f"rule_id_namespace: acme\ntemplate_rule_ids_through: {_through()}\n{TRACKED}\n"
    )
    assert f"quality/local/rules.yaml: += {TRACKED}" in said


def test_a_drawer_declared_before_the_shape_gains_it_on_the_next_run(tmp_path: Path) -> None:
    root = _tree(tmp_path, product_app=True)
    held = f"rule_id_namespace: acme\ntemplate_rule_ids_through: {_through()}\n"
    (root / "quality/local").mkdir()
    (root / "quality/local/rules.yaml").write_text(held)
    (root / ".env").write_text(f"DEBUG=1\n{SHAPE}\n")
    said = _declare(root)
    assert _written(root)["quality/local/rules.yaml"] == f"{held}{TRACKED}\n"
    assert _written(root)[".env"] == f"DEBUG=1\n{SHAPE}\n"
    assert "nothing changed" not in said
    assert said.rstrip().splitlines()[-1].startswith("next: git add quality/local/rules.yaml")


def test_the_shape_a_human_typed_in_env_is_the_one_the_drawer_carries(tmp_path: Path) -> None:
    root = _tree(tmp_path, product_app=True)
    (root / ".env").write_text("DJB_IDENTITY_SHAPE=login_page=own;platform_apps=own\n")
    _declare(root)
    drawer = _written(root)["quality/local/rules.yaml"]
    assert drawer.endswith("identity_shape: login_page=own;platform_apps=own\n")


def test_a_typed_shape_without_platform_apps_is_not_carried(tmp_path: Path) -> None:
    root = _tree(tmp_path, product_app=True)
    (root / ".env").write_text("DJB_IDENTITY_SHAPE=login_page=own\n")
    said = _declare(root)
    assert "identity_shape" not in _written(root)["quality/local/rules.yaml"]
    assert "add `platform_apps=own` to it" in said


def test_a_second_run_reports_and_changes_nothing(tmp_path: Path) -> None:
    root = _tree(tmp_path, product_app=True)
    _declare(root)
    assert _written(root)["quality/local/rules.yaml"].count("identity_shape:") == 1
    _git(root, "add", "--", "quality/local/rules.yaml", "scripts/local/template-base")
    _git(root, "commit", "-q", "-m", "declared")
    before = _written(root)
    said = _declare(root)
    assert _written(root) == before
    assert "nothing changed" in said
    assert "next:" not in said


@pytest.mark.parametrize("namespace", ["Acme", "1acme", "ac-me", "djb", ""])
def test_a_namespace_of_the_wrong_shape_is_refused_before_a_write(
    tmp_path: Path, namespace: str
) -> None:
    root = _tree(tmp_path)
    with pytest.raises(CommandError) as refused:
        _declare(root, namespace)
    assert refused.value.returncode == 2
    assert _written(root) == {".env": "DEBUG=1\n"}


def test_a_second_namespace_is_refused(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    _declare(root)
    before = _written(root)
    with pytest.raises(CommandError) as refused:
        _declare(root, "other")
    assert refused.value.returncode == 2
    assert "acme" in str(refused.value)
    assert _written(root) == before


def test_a_drawer_with_rules_keeps_them_and_gains_the_keys(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    (root / "quality/local").mkdir()
    (root / "quality/local/rules.yaml").write_text("ratchets: {}\n")
    _declare(root)
    assert _written(root)["quality/local/rules.yaml"] == (
        f"rule_id_namespace: acme\ntemplate_rule_ids_through: {_through()}\nratchets: {{}}\n"
    )


def test_a_template_remote_sets_the_base_to_the_release_the_clone_stands_on(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    release = _git(root, "rev-parse", "HEAD")
    _git(root, "tag", "v9.9.9")
    (root / "product.txt").write_text("a product\n")
    _git(root, "add", "--", "product.txt")
    _git(root, "commit", "-q", "-m", "the product's first change")
    _git(root, "remote", "add", "template", str(root))
    _declare(root)
    assert _written(root)["scripts/local/template-base"] == release + "\n"


def test_after_a_release_a_second_run_moves_both_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _tree(tmp_path)
    _git(root, "tag", "v9.9.9")
    _git(root, "remote", "add", "template", str(root))
    first = _git(root, "rev-parse", "HEAD")
    _declare(root)
    (root / "TEMPLATE_VERSION").write_text("9.9.10\n")
    _git(root, "add", "--", "TEMPLATE_VERSION")
    _git(root, "commit", "-q", "-m", "the next release")
    _git(root, "tag", "v9.9.10")
    release = _git(root, "rev-parse", "HEAD")
    monkeypatch.setattr(declare, "template_ids_through", lambda: _through() + 1)
    said = _declare(root)
    assert _written(root)["quality/local/rules.yaml"] == (
        f"rule_id_namespace: acme\ntemplate_rule_ids_through: {_through() + 1}\n"
    )
    assert _written(root)["scripts/local/template-base"] == release + "\n"
    assert f"template_rule_ids_through: {_through()} → {_through() + 1}" in said
    assert f"{first} → {release}" in said
    assert "nothing changed" not in said


def _product_copy(tmp_path: Path, drawer: str) -> Path:
    """The tracked tree copied whole, one product app added, the drawer given."""
    if shutil.which("tar") is None:
        pytest.skip("no tar on PATH — the tracked tree is copied with it")
    root = tmp_path / "tree"
    root.mkdir()
    copied = subprocess.run(  # noqa: S603 — `bash -c` over a pipeline this test writes; no caller input
        ["bash", "-c", f"git ls-files -z | tar --null -T - -cf - | tar -xf - -C {str(root)!r}"],  # noqa: S607 — `bash` resolved on PATH, as the gate's own legs run it
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert copied.returncode == 0, copied.stderr
    if (ROOT / ".env").is_file():
        env = (ROOT / ".env").read_text().splitlines()
        kept = [ln for ln in env if not ln.startswith("DJB_IDENTITY_SHAPE=")]
        (root / ".env").write_text("\n".join(kept) + "\n")
    app = root / "apps" / "zzzk6as"
    app.mkdir()
    (app / "__init__.py").write_text("")
    (app / "apps.py").write_text(
        "from django.apps import AppConfig\n\n\n"
        "class ZzzConfig(AppConfig):\n"
        '    """A product app."""\n\n'
        '    name = "apps.zzzk6as"\n'
        '    depends_on: tuple[str, ...] = ("core",)\n'
    )
    (root / "quality/local").mkdir(parents=True, exist_ok=True)
    (root / "quality/local/rules.yaml").write_text(drawer)
    return root


def _census(root: Path, shape: str | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "DJB_IDENTITY_SHAPE"}
    env |= {
        "DJANGO_SETTINGS_MODULE": "config.settings.test",
        "DATABASE_NAME": f"djb_declare_{secrets.token_hex(3)}",
        "DATABASE_URL": "",
    }
    if shape is not None:
        env["DJB_IDENTITY_SHAPE"] = shape
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "apps/core/tests/test_template_shape.py",
            "-q",
            "-p",
            "no:cacheprovider",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


PRODUCT_DRAWER = "rule_id_namespace: zzzk6a\ntemplate_rule_ids_through: 98\n"


def test_a_product_copy_runs_the_census_from_the_tracked_drawer_alone(tmp_path: Path) -> None:
    root = _product_copy(tmp_path, f"{PRODUCT_DRAWER}{TRACKED}\n")
    done = _census(root, None)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-2000:]


def test_an_environment_disagreeing_with_the_drawer_is_refused_naming_both(
    tmp_path: Path,
) -> None:
    root = _product_copy(tmp_path, f"{PRODUCT_DRAWER}{TRACKED}\n")
    done = _census(root, "platform_apps=template")
    said = done.stdout + done.stderr
    assert done.returncode != 0, said[-3000:]
    assert "platform_apps=template" in said and "platform_apps=own" in said, said[-3000:]
    assert "disagree" in said, said[-3000:]


def test_a_head_git_cannot_read_is_refused_quoting_git(tmp_path: Path) -> None:
    from apps.core.management.commands import declare as command

    with pytest.raises(CommandError) as refused:
        command.head_commit(tmp_path)
    assert "no commit at HEAD" in str(refused.value)
    assert "\n   the tool said: fatal: not a git repository" in str(refused.value)
