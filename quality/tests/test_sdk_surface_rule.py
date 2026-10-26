"""Rule 97's history half and the derived `### SDK` section, over a scratch repo with a tag."""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from quality.checks.rule_97 import sdk_surface_is_ratcheted
from quality.sdk import changelog as sdk_changelog
from quality.sdk import reference, surface

pytestmark = pytest.mark.drives(
    "quality/sdk/*",
    "quality/checks/rule_97.py",
    "quality/djb/boundary.py",
    "pilecap/*",
    "CHANGELOG.md",
    "quality/sdk_surface.json",
    "docs/sdk/*",
)

DEPRECATION = 'Deprecation(since="{since}", until="{until}", instead="{instead}", kind="{kind}"{x})'


def git(root: Path, *argv: str) -> None:
    subprocess.run(["git", *argv], cwd=root, check=True, capture_output=True)


def facade(root: Path, names: dict[str, str], deprecated: dict[str, dict[str, str]]) -> None:
    """Write `pilecap/__init__.py` exporting `names` and the surface file that says so."""
    rows = {
        k: DEPRECATION.format(x=f', change="{v["change"]}"' if v.get("change") else "", **v)
        for k, v in deprecated.items()
    }
    table = ", ".join(f'"{k}": {v}' for k, v in rows.items())
    (root / "pilecap").mkdir(exist_ok=True)
    (root / "pilecap/__init__.py").write_text(
        f'"""World."""\n\n__all__ = {sorted(names)!r}\n\nDEPRECATED = {{{table}}}\n'
    )
    doc: dict[str, Any] = {
        "names": {f"pilecap.{n}": {"kind": "function", "sig": s} for n, s in names.items()},
        "deprecations": {f"pilecap.{k}": v for k, v in deprecated.items()},
        "ts": {},
    }
    (root / surface.SURFACE).write_text(surface.render(doc))
    (root / reference.HOME).mkdir(parents=True, exist_ok=True)
    heads = "".join(f"### `pilecap.{n}`\n\n" for n in sorted(names))
    (root / reference.INDEX).write_text(f"# World\n\n{heads}")


def release(root: Path, version: str, intent: str = "") -> None:
    """Commit the world, name `version` the newest release, and tag it."""
    (root / "TEMPLATE_VERSION").write_text(f"{version}\n")
    unreleased = f"## [Unreleased]{f' — {intent}' if intent else ''}"
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n{unreleased}\n\n## [{version}] — w\n")
    git(root, "add", "-A")
    git(root, "commit", "-qm", f"release {version}")
    git(root, "tag", f"v{version}")


@pytest.fixture
def world(tmp_path: Path) -> Path:
    """A repository at release 2.4.0 exporting `f(*, a)` and `g()`."""
    (tmp_path / "quality").mkdir()
    (tmp_path / "frontend/src/kit").mkdir(parents=True)
    (tmp_path / surface.KIT_SURFACE).write_text('{"modules": {}}\n')
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "w@example.invalid")
    git(tmp_path, "config", "user.name", "w")
    facade(tmp_path, {"f": "(*, a)", "g": "()"}, {})
    release(tmp_path, "2.4.0")
    return tmp_path


def census(root: Path) -> tuple[list[str], str]:
    """The census's finding lines and its whole output."""
    out = io.StringIO()
    with redirect_stdout(out):
        assert surface.main(["--ratchet", "--root", str(root)]) == 0
    text = out.getvalue()
    return [line for line in text.splitlines() if line.startswith("finding ")], text


def test_a_narrowed_signature_on_a_tagged_world_fires(world: Path) -> None:
    facade(world, {"f": "(*, a, b)", "g": "()"}, {})
    findings, text = census(world)
    assert "previous: v2.4.0" in text
    assert findings == [
        "finding pilecap/__init__.py\tsignature\tpilecap.f narrowed (*, a) → (*, a, b): required b"
        " added. A narrowed public signature is a major release; keep the old call binding (an"
        " optional parameter is minor), or declare a `signature` Deprecation with its old→new text"
    ]


def test_the_rule_reads_the_census_through_the_engine_seam(world: Path) -> None:
    facade(world, {"f": "(*, a, b)", "g": "()"}, {})
    result = sdk_surface_is_ratcheted(world, {})
    assert [(f.klass, f.path) for f in result.findings] == [("signature", "pilecap/__init__.py")]
    assert result.targets_matched == {
        "surface_names": 2,
        "facade_names": 2,
        "previous_names": 2,
        "unratchetable_signatures": 0,
    }


def test_an_optional_parameter_added_is_silent(world: Path) -> None:
    facade(world, {"f": "(*, a, b=)", "g": "()"}, {})
    assert census(world)[0] == []


def test_a_removal_without_a_deprecation_fires(world: Path) -> None:
    facade(world, {"g": "()"}, {})
    (finding,) = census(world)[0]
    assert finding.startswith("finding pilecap/__init__.py\tremoved\tpilecap.f left the SDK")


def test_a_removal_deprecated_one_minor_ahead_is_silent(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()"}, {"f": entry})
    assert census(world)[0] == []


def test_a_removal_past_its_until_is_silent(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()"}, {"f": entry})
    release(world, "2.5.0")
    facade(world, {"g": "()"}, {})
    (world / "TEMPLATE_VERSION").write_text("2.6.0\n")
    assert census(world)[0] == []


def test_a_removal_before_its_until_fires(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.7.0", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()"}, {"f": entry})
    release(world, "2.5.0")
    facade(world, {"g": "()"}, {})
    assert census(world)[0] == [
        "finding pilecap/__init__.py\tremoved\tpilecap.f was deprecated until 2.7.0 and left"
        " before it"
    ]


def test_a_removed_entry_with_nothing_to_serve_fires(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "removed"}
    facade(world, {"g": "()"}, {"f": entry})
    (finding,) = census(world)[0]
    assert "pilecap.f: a `removed` entry names the object it serves until 2.6.0 in `change`" in (
        finding
    )


def test_a_hand_edited_deprecation_value_is_drift(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()"}, {"f": entry})
    path = world / surface.SURFACE
    path.write_text(path.read_text().replace('"until": "2.6.0"', '"until": "2.9.0"'))
    (finding,) = census(world)[0]
    assert "the deprecations block is not the facade's DEPRECATED tables" in finding


@pytest.mark.parametrize(("intent", "fires"), [("2.5.1", True), ("2.6.0", False), ("", True)])
def test_the_release_being_built_is_the_unreleased_intent(
    world: Path, intent: str, fires: bool
) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()"}, {"f": entry})
    release(world, "2.5.0", intent)
    facade(world, {"g": "()"}, {})
    findings, text = census(world)
    assert bool(findings) is fires, text
    if not intent:
        assert "building: ## [Unreleased] names no version — judged as 2.5.1" in text


def test_the_census_counts_the_signatures_it_cannot_ratchet(world: Path) -> None:
    facade(world, {"f": "(*, a)", "g": "(?)", "h": "(*args, **kwargs)"}, {})
    assert "count unratchetable_signatures 2" in census(world)[1]


def test_a_signature_entry_without_its_old_to_new_text_fires(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "f", "kind": "signature"}
    facade(world, {"f": "(*, a, b)", "g": "()"}, {"f": entry})
    findings = census(world)[0]
    assert any("a `signature` entry carries its old→new text" in f for f in findings)
    entry["change"] = "(*, a) → (*, a, b)"
    facade(world, {"f": "(*, a, b)", "g": "()"}, {"f": entry})
    assert census(world)[0] == []


def test_a_deprecation_served_under_one_minor_fires(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.5.1", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()"}, {"f": entry})
    (finding,) = census(world)[0]
    assert "until 2.5.1 is not one minor past since 2.5.0" in finding


def test_a_name_exported_and_not_filed_is_drift(world: Path) -> None:
    text = (world / "pilecap/__init__.py").read_text().replace("'g'", "'g', 'h'")
    (world / "pilecap/__init__.py").write_text(text)
    drift, ref = census(world)[0]
    assert "pilecap.h is exported and absent from quality/sdk_surface.json" in drift
    assert "pilecap.h is exported and absent from docs/sdk/" in ref


def test_a_product_tree_prints_the_skip_line_and_judges_nothing(world: Path) -> None:
    (world / "quality/local").mkdir()
    (world / surface.LOCAL_RULES).write_text("rule_id_namespace: zzshop\n")
    facade(world, {"g": "()"}, {})
    findings, text = census(world)
    assert findings == [] and surface.SKIP_LINE in text
    assert surface.SKIP_LINE.startswith(
        "sdk-surface: a product tree — the promise is the template's"
    )


def test_no_previous_tag_compares_against_the_empty_surface(world: Path) -> None:
    git(world, "tag", "-d", "v2.4.0")
    facade(world, {"g": "()"}, {})
    findings, text = census(world)
    assert findings == []
    assert "previous: v2.4.0 does not resolve here — compared against the empty surface" in text


def changelog(root: Path, *argv: str) -> tuple[int, str]:
    """`python -m quality.sdk --changelog …` in-process: its exit and its lines."""
    out = io.StringIO()
    with redirect_stdout(out):
        rc = sdk_changelog.main(["--changelog", *argv, "--root", str(root)])
    return rc, out.getvalue()


def test_the_derived_sdk_section_names_what_moved_since_the_last_release(world: Path) -> None:
    entry = {"since": "2.5.0", "until": "2.6.0", "instead": "g", "kind": "renamed"}
    facade(world, {"g": "()", "k": "()"}, {"f": entry})
    assert changelog(world, "--write")[0] == 0
    text = (world / "CHANGELOG.md").read_text()
    assert "## [Unreleased]\n\n### SDK\n\n- added: pilecap.k\n" in text
    assert "- deprecated: pilecap.f (renamed, until v2.6.0) → pilecap.g\n" in text
    assert changelog(world, "--check") == (
        0,
        "changelog: ## [Unreleased] · previous: v2.4.0\n"
        "changelog: `### SDK` of ## [Unreleased] is the derived one\n",
    )


def test_a_hand_edit_of_the_sdk_section_is_refused(world: Path) -> None:
    facade(world, {"f": "(*, a)", "g": "()", "k": "()"}, {})
    changelog(world, "--write")
    path = world / "CHANGELOG.md"
    path.write_text(path.read_text().replace("- added: pilecap.k", "- added: pilecap.k, by hand"))
    rc, text = changelog(world, "--check")
    assert rc == 1 and "never by hand" in text


def test_the_first_release_adds_every_name_in_one_summary_line(world: Path) -> None:
    git(world, "tag", "-d", "v2.4.0")
    facade(world, {"f": "(*, a)", "g": "()", "k": "()"}, {})
    changelog(world, "--write")
    text = (world / "CHANGELOG.md").read_text()
    assert "### SDK\n\n- added: 3 names — quality/sdk_surface.json is the record\n" in text
    assert changelog(world, "--check")[0] == 0


def test_this_trees_sdk_section_is_derived_and_adds_every_name() -> None:
    root = Path(__file__).resolve().parents[2]
    assert changelog(root, "--check")[0] == 0
    names = json.loads((root / surface.SURFACE).read_text())["names"]
    head = (root / "CHANGELOG.md").read_text().split("\n## [", 2)[1]
    assert f"- added: {len(names)} names — quality/sdk_surface.json is the record\n" in head


def test_a_name_exported_twice_fires(world: Path) -> None:
    init = world / "pilecap/__init__.py"
    init.write_text(init.read_text().replace("['f', 'g']", "['f', 'g', 'g']"))
    assert census(world)[0] == [
        "finding pilecap/__init__.py\treference\tpilecap.g is exported twice — every export once"
    ]


def test_a_name_absent_from_the_reference_fires(world: Path) -> None:
    (world / reference.INDEX).write_text("# World\n\n### `pilecap.f`\n\n### `pilecap.f`\n")
    assert census(world)[0] == [
        "finding docs/sdk\treference\tpilecap.f is listed 2 times in docs/sdk/ — run "
        "python -m quality.sdk --reference",
        "finding pilecap/__init__.py\treference\tpilecap.g is exported and absent from docs/sdk/"
        " — run python -m quality.sdk --reference",
    ]


def cut(root: Path, version: str, *history: str) -> None:
    """Head CHANGELOG.md with `version` being cut over `history`, no `## [Unreleased]`."""
    (root / "TEMPLATE_VERSION").write_text(f"{version}\n")
    heads = "".join(f"## [{v}] — w\n\n" for v in (version, *history))
    (root / "CHANGELOG.md").write_text(f"# Changelog\n\n{heads}")


def test_a_pre_release_is_ratcheted_against_the_last_release(world: Path) -> None:
    cut(world, "2.5.0a1", "2.4.0")
    facade(world, {"f": "(*, a, b)", "g": "()"}, {})
    findings, text = census(world)
    assert "previous: v2.4.0" in text
    assert [f.split("\t")[1] for f in findings] == ["signature"]


def test_a_final_release_is_ratcheted_past_its_own_pre_release(world: Path) -> None:
    facade(world, {"f": "(*, a)", "g": "()", "h": "()"}, {})
    cut(world, "2.5.0a1", "2.4.0")
    git(world, "add", "-A")
    git(world, "commit", "-qm", "release 2.5.0a1")
    git(world, "tag", "v2.5.0a1")
    facade(world, {"f": "(*, a)", "g": "()"}, {})
    for version, history in (("2.5.0a2", ("2.5.0a1", "2.4.0")), ("2.5.0", ("2.5.0a1", "2.4.0"))):
        cut(world, version, *history)
        findings, text = census(world)
        assert "previous: v2.4.0" in text and findings == [], text


def test_the_sdk_section_of_a_pre_release_being_cut_is_its_own(world: Path) -> None:
    cut(world, "2.5.0a1", "2.4.0")
    facade(world, {"f": "(*, a)", "g": "()", "k": "()"}, {})
    assert changelog(world, "--write")[0] == 0
    assert (
        "## [2.5.0a1] — w\n\n### SDK\n\n- added: pilecap.k\n"
        in (world / "CHANGELOG.md").read_text()
    )
    assert changelog(world, "--check") == (
        0,
        "changelog: ## [2.5.0a1] · previous: v2.4.0\n"
        "changelog: `### SDK` of ## [2.5.0a1] is the derived one\n",
    )
