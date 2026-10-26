"""`quality/docs_derived.py`: a stale block is exit 1 with its line; unknown or unreadable is 2."""

# does-not-cover: whether the prose beside a block is true — the tool owns the fenced body only.

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from quality import docs_derived as dd
from quality.could_not_look import CouldNotLook

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "docs" / "product" / "architecture.md"


def _app(root: Path, label: str, deps: tuple[str, ...], *doors: str) -> None:
    (root / "apps" / label).mkdir(parents=True)
    (root / "apps" / label / "apps.py").write_text(
        f"class C:\n    depends_on: tuple[str, ...] = {deps!r}\n"
    )
    for door in doors:
        (root / "apps" / label / door).write_text("")


@pytest.fixture
def world(tmp_path: Path) -> Path:
    """Two platform apps, one worked, one product; a page carrying both blocks, regenerated."""
    _app(tmp_path, "core", ())
    _app(tmp_path, "events", ("core",), "api.py", "receivers.py")
    _app(tmp_path, "example", ("core", "events"), "api.py", "mcp.py")
    _app(tmp_path, "shop", ("core",), "workflows.py")
    (tmp_path / "quality" / "sdk").mkdir(parents=True)
    (tmp_path / "quality" / "partition.yaml").write_text(
        "platform_apps:\n  - core\n  - events\n  - example\n"
    )
    (tmp_path / "quality" / "sdk" / "census.py").write_text('WORKED_EXAMPLE = "example*"\n')
    (tmp_path / "quality" / "rules.yaml").write_text("rules:\n  - id: 1\n  - id: 3\n")
    (tmp_path / "page.md").write_text(
        "# Page\n\n<!-- derived: app-map -->\n<!-- /derived -->\n\n"
        "1. A list item:\n   <!-- derived: rule-count -->\n   <!-- /derived -->\n"
    )
    assert dd.main(["--root", str(tmp_path), "--write"]) == 0
    return tmp_path


def _check(root: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    rc = dd.main(["--root", str(root), "--check"])
    return rc, capsys.readouterr().out


def test_a_regenerated_block_is_current(world: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc, out = _check(world, capsys)
    assert rc == 0, out
    page = (world / "page.md").read_text()
    assert (
        "| `example` | `core`, `events` | `api.py` · `mcp.py` | platform · worked example |" in page
    )
    assert "| `shop` | `core` | `workflows.py` | product |" in page
    assert "| `core` | — | — | platform |" in page
    assert "   2 house rules — `python -m quality.gate --rules` lists them." in page


def test_a_hand_edited_cell_is_exit_1_naming_its_line(
    world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    page = world / "page.md"
    page.write_text(page.read_text().replace("| `core` | — | — |", "| `core` | `accounts` | — |"))
    rc, out = _check(world, capsys)
    assert rc == 1, out
    line = page.read_text().splitlines().index("| `core` | `accounts` | — | platform |") + 1
    assert f"page.md:{line}: derived block 'app-map' is stale" in out
    assert "found '| `core` | `accounts` | — | platform |'" in out


def test_an_app_added_without_regenerating_is_exit_1(
    world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _app(world, "billing", ("core",), "api.py")
    rc, out = _check(world, capsys)
    assert rc == 1, out
    assert "billing" in out


def test_a_typed_count_is_exit_1(world: Path, capsys: pytest.CaptureFixture[str]) -> None:
    page = world / "page.md"
    page.write_text(page.read_text().replace("   2 house rules", "   26 house rules"))
    rc, out = _check(world, capsys)
    assert rc == 1, out
    assert "derived block 'rule-count' is stale" in out


def test_a_block_naming_no_generator_is_exit_2(
    world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (world / "other.md").write_text("<!-- derived: app-mapp -->\n<!-- /derived -->\n")
    rc, out = _check(world, capsys)
    assert rc == 2, out
    assert "other.md:1: block 'app-mapp' names no generator" in out


@pytest.mark.parametrize(
    "text, said",
    [
        ("<!-- derived: app-map -->\nbody\n", "is never closed"),
        ("body\n<!-- /derived -->\n", "a closing fence with no block open"),
    ],
)
def test_a_broken_fence_is_exit_2(
    world: Path, capsys: pytest.CaptureFixture[str], text: str, said: str
) -> None:
    (world / "other.md").write_text(text)
    rc, out = _check(world, capsys)
    assert rc == 2 and said in out, out


def test_an_unreadable_input_is_exit_2(world: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (world / "apps" / "events" / "apps.py").write_text("class C:\n    pass\n")
    rc, out = _check(world, capsys)
    assert rc == 2, out
    assert "apps/events/apps.py: declares no depends_on" in out


def test_a_fence_quoted_in_a_code_block_is_text(
    world: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (world / "other.md").write_text("```\n<!-- derived: nope -->\n```\n")
    rc, out = _check(world, capsys)
    assert rc == 0, out


def test_it_runs_with_django_refused() -> None:
    """The tool imports no Django: a finder that refuses the package changes nothing."""
    probe = (
        "import sys\n"
        "class Refuse:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] == 'django': raise ImportError('django refused')\n"
        "sys.meta_path.insert(0, Refuse())\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from quality import docs_derived\n"
        f"sys.exit(docs_derived.main(['--root', {str(ROOT)!r}, '--check']))\n"
    )
    run = subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr


def test_the_app_map_lists_exactly_the_discovered_apps() -> None:
    """list == population: one row per `apps/*/apps.py`, every platform app among them."""
    rows = [line.split("`")[1] for line in dd.app_map(ROOT)[2:]]
    population = dd.discovered_apps(ROOT)
    platform = dd._yaml(ROOT, "quality/partition.yaml")["platform_apps"]
    assert isinstance(platform, list), platform
    print(f"{len(rows)} rows · {len(population)} discovered apps · {len(platform)} platform apps")
    assert rows == population
    assert set(platform) <= set(population)


def test_the_rule_count_is_the_engines() -> None:
    run = subprocess.run(
        [sys.executable, "-m", "quality.gate", "--rules"], cwd=ROOT, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
    engine = len(run.stdout.splitlines())
    assert dd.rule_count(ROOT) == [
        f"{engine} house rules — `python -m quality.gate --rules` lists them."
    ]


def test_the_architecture_carries_the_app_map_and_the_rule_count_current(
    capsys: pytest.CaptureFixture[str],
) -> None:
    names = [b.name for b in dd.blocks(ARCH)]
    assert names.count("app-map") == 1, names
    assert names.count("rule-count") == 1, names
    rc = dd.main(["--root", str(ROOT), "--check", str(ARCH.relative_to(ROOT))])
    assert rc == 0, capsys.readouterr().out


@pytest.mark.drives("scripts/docs_legs.sh", "quality/djb/legs/dangling_docs.py")
def test_the_dangling_docs_body_runs_the_check(world: Path) -> None:
    """`docs_derived_check`, as `docs_dangling_docs_loop` calls it: 0 current, 1 stale, its line."""
    libraries = "".join(
        f". {lib} || exit 2\n"
        for lib in ("scripts/secrets_scan.sh", "scripts/archaeology_lib.sh", "scripts/docs_legs.sh")
    )

    def drive() -> subprocess.CompletedProcess[str]:
        script = f"set -uo pipefail\n{libraries}docs_derived_check {str(world)!r}\n"
        return subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True)

    current = drive()
    assert current.returncode == 0, current.stdout + current.stderr
    page = world / "page.md"
    page.write_text(page.read_text().replace("   2 house rules", "   26 house rules"))
    stale = drive()
    assert stale.returncode == 1, stale.stdout + stale.stderr
    assert "page.md:" in stale.stdout and "derived block 'rule-count' is stale" in stale.stdout


def test_the_alert_census_block_is_the_census_total_line(tmp_path: Path) -> None:
    """`alert-census` carries the one `ALERTS = ` line the census prints; none is 2."""
    home = tmp_path / "deploy/observability/alerts"
    home.mkdir(parents=True)
    census = (
        "def census(root):\n    return {}\n"
        "def render(result):\n    return 'x\\nALERTS = 1 = 1\\n'\n"
    )
    (home / "census.py").write_text(census)
    assert dd.alert_census(tmp_path) == ["`ALERTS = 1 = 1`"]
    (home / "census.py").write_text(census.replace("ALERTS", "TOTAL"))
    with pytest.raises(CouldNotLook):
        dd.alert_census(tmp_path)
    assert dd.alert_census(ROOT)[0].startswith("`ALERTS = ")


def test_the_deploy_steps_block_counts_the_openers_and_the_parts(tmp_path: Path) -> None:
    """`deploy-steps` counts `**<n>. ` openers and `## Part <n> · ` headings, never a total."""
    (tmp_path / "docs/runbooks").mkdir(parents=True)
    (tmp_path / "docs/runbooks/deploy.md").write_text(
        "## Part 0 · A\n\n**1. One.**\n\n**19a. Two.**\n\n"
        "## Part 1 · B\n\n**2. Three.** **4. no**\n"
    )
    assert dd.deploy_steps(tmp_path) == ["There are **3** numbered steps, in **2** parts."]
