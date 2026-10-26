"""`divergence_census.sh --against <tag> --sdk [--fix]` over a product with three release tags."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from quality.sdk import surface
from quality.tests.fixtures.capture import run_to

pytestmark = pytest.mark.drives(
    "quality/sdk/*", "quality/djb/rituals/divergence.py", "scripts/divergence_census.sh"
)

ROOT = Path(__file__).resolve().parents[2]
ENTRY = (
    "import sys; from pathlib import Path; "
    "from quality.djb.rituals.divergence import main; "
    "sys.exit(main(sys.argv[1:], root=Path.cwd()))"
)
SHOP = "apps/zzz_shop/services.py"
FN = {"kind": "function", "source": "apps.core.x", "sig": "(*, a)"}
BASE = {"kind": "model", "fields": [["x", "aaaaaaaaaaaa"]], "meta": "m1", "migration": True}
RENAMED = {"since": "2.6.0", "until": "2.7.0", "instead": "g", "kind": "renamed"}
SIGNATURE = {
    "since": "2.6.0",
    "until": "2.7.0",
    "instead": "h",
    "kind": "signature",
    "change": "(*, a) → (*, a, b)",
}


def git(repo: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)


def release(repo: Path, version: str, names: dict[str, Any], deps: dict[str, Any]) -> None:
    """Commit a surface at `version` and tag it."""
    doc = {"names": {f"pilecap.{k}": v for k, v in names.items()}, "ts": {}}
    doc["deprecations"] = {f"pilecap.{k}": v for k, v in deps.items()}
    (repo / surface.SURFACE).write_text(surface.render(doc))
    (repo / "TEMPLATE_VERSION").write_text(f"{version}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"release {version}")
    git(repo, "tag", f"v{version}")


@pytest.fixture
def shop(tmp_path: Path) -> Path:
    """A product on 2.5.0 importing f, h and Base; 2.6.0 deprecates f and h; 2.7.0 drops f."""
    repo = tmp_path / "shop"
    (repo / "quality").mkdir(parents=True)
    (repo / "quality/partition.yaml").write_text("schema: v1\n\nplatform_apps:\n  - core\n")
    (repo / "apps/zzz_shop").mkdir(parents=True)
    (repo / "apps/zzz_shop/apps.py").write_text('"""The shop."""\n')
    (repo / SHOP).write_text(
        '"""The shop\'s services."""\n\nfrom pilecap import Base, f, h\n\n\n'
        "def use() -> object:\n    return f(a=1), h(a=1), Base, obj.f\n"
    )
    (repo / "frontend/src/app").mkdir(parents=True)
    (repo / "frontend/src/app/page.tsx").write_text('import { pathFor } from "@/screens/routes";\n')
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    release(repo, "2.5.0", {"f": FN, "g": FN, "h": FN, "Base": BASE}, {})
    moved = {**BASE, "fields": [["x", "bbbbbbbbbbbb"]]}
    later = {"g": FN, "h": {**FN, "sig": "(*, a, b)"}, "Base": moved}
    release(repo, "2.6.0", later, {"f": RENAMED, "h": SIGNATURE})
    release(repo, "2.7.0", later, {"h": SIGNATURE})
    return repo


def fold(repo: Path, *args: str) -> tuple[int, str]:
    """The census's `--sdk` mode from the product's declared base, captured to a file."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "DJB_TEMPLATE_BASE": "v2.5.0"}
    said = run_to(
        repo.parent / f"fold-{len(args)}.out", [sys.executable, "-c", ENTRY, *args], repo, env
    )
    return said.rc, said.text()


def test_a_name_removed_two_releases_ahead_is_exit_1_with_the_line(shop: Path) -> None:
    rc, text = fold(shop, "--against", "v2.7.0", "--sdk")
    assert rc == 1, text
    assert f"imports pilecap.f: removed in 2.7.0; use g — {SHOP}:3" in text
    assert "== 1 IMPORT(S) OF A REMOVED NAME" in text


def test_a_deprecated_name_is_a_note_and_exit_0(shop: Path) -> None:
    rc, text = fold(shop, "--against", "v2.6.0", "--sdk")
    assert rc == 0, text
    assert f"imports pilecap.f: deprecated since 2.6.0, removed in 2.7.0; use g — {SHOP}:3" in text


def test_a_signature_entry_prints_the_old_to_new_text(shop: Path) -> None:
    text = fold(shop, "--against", "v2.6.0", "--sdk")[1]
    assert (
        "imports pilecap.h: deprecated since 2.6.0, removed in 2.7.0; use h;"
        f" signature (*, a) → (*, a, b) — {SHOP}:3"
    ) in text


def test_a_model_base_digest_change_prints_the_makemigrations_line(shop: Path) -> None:
    text = fold(shop, "--against", "v2.6.0", "--sdk")[1]
    assert f"run makemigrations zzz_shop — Base.x changed — {SHOP}:3" in text


def test_a_moved_screen_path_prints_the_kit_path(shop: Path) -> None:
    text = fold(shop, "--against", "v2.6.0", "--sdk")[1]
    assert "imports @/screens/routes: deprecated since 2.5.0, removed in 3.0; use" in text
    assert "@pilecap/ui/routes — frontend/src/app/page.tsx:1" in text


def test_fix_rewrites_an_exact_rename_as_a_diff(shop: Path) -> None:
    rc, text = fold(shop, "--against", "v2.7.0", "--sdk", "--fix")
    assert rc == 0, text
    assert "-from pilecap import Base, f, h\n+from pilecap import Base, g, h\n" in text
    assert (
        "-    return f(a=1), h(a=1), Base, obj.f\n+    return g(a=1), h(a=1), Base, obj.f\n" in text
    )
    assert "== sdk --fix: 1 exact rename(s) rewritten — commit the diff above" in text
    assert "return g(a=1), h(a=1), Base, obj.f" in (shop / SHOP).read_text()


def test_fix_without_sdk_and_sdk_without_against_are_refused(shop: Path) -> None:
    assert fold(shop, "--fix")[0] == 2
    assert fold(shop, "--sdk")[0] == 2


def test_an_unparsable_product_file_is_a_could_not_look_line(shop: Path) -> None:
    (shop / "apps/zzz_shop/broken.py").write_text("def broken(:\n")
    rc, text = fold(shop, "--against", "v2.6.0", "--sdk")
    assert rc == 2, text
    assert "Traceback" not in text
    assert "!! sdk: apps/zzz_shop/broken.py does not parse" in text
    assert f"imports pilecap.f: deprecated since 2.6.0, removed in 2.7.0; use g — {SHOP}:3" in text


def test_the_moved_screen_line_waits_for_a_target_that_moved_them(shop: Path) -> None:
    (shop / "TEMPLATE_VERSION").write_text("2.4.9\n")
    git(shop, "commit", "-qam", "a target before the kit took the screens")
    git(shop, "tag", "v2.4.9")
    text = fold(shop, "--against", "v2.4.9", "--sdk")[1]
    assert "@/screens/routes" not in text, text
