"""`CoreConfig.DEV_ONLY` is the one list: every gate reader under `apps/` is on it."""

# does-not-cover: a gate read spelled outside `tier.py`'s `quality_reader` tokens (an f-string).

from __future__ import annotations

import ast
import re

import pytest

from apps.core.apps import CoreConfig
from quality.tests.test_image_imports import ROOT, ignore_lines, image_files

pytestmark = pytest.mark.drives(".dockerignore", "apps/core/apps.py", "apps/testing/tier.py")

TIER = ROOT / "apps/testing/tier.py"

EXEMPT = {
    "apps/testing/tier.py": "the census's own reader: the spellings are its data, never a read",
    "apps/testing/template_only.py": "pytest's harness: it runs under the dev group, in a checkout",
}
DATA_READ = re.compile(r'"quality"((?:\s*/\s*"[^"]+")+)')


def _runtime_sources() -> dict[str, str]:
    found = {}
    for path in sorted((ROOT / "apps").rglob("*.py")):
        rel = str(path.relative_to(ROOT))
        parts = path.relative_to(ROOT).parts
        if "tests" in parts or parts[-1].startswith("test_") or parts[-1] == "conftest.py":
            continue
        found[rel] = path.read_text()
    return found


def _on_dev_only(rel: str) -> bool:
    return any(rel == entry or rel.startswith(entry + "/") for entry in CoreConfig.DEV_ONLY)


def _quality_reader() -> tuple[str, ...]:
    """`tier.py`'s `DJB_DECLARED_READS["quality_reader"]`, read off its source (no app registry)."""
    for node in ast.walk(ast.parse(TIER.read_text())):
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", "") == "DJB_DECLARED_READS"
        ):
            reads = ast.literal_eval(node.value or ast.Constant(None))
            names: tuple[str, ...] = reads["quality_reader"]
            return names
    raise AssertionError(f"{TIER} declares no DJB_DECLARED_READS")


def _gate_reads(source: str, reincluded: set[str]) -> list[str]:
    tokens = _quality_reader()

    def data(match: re.Match[str]) -> str:
        path = "quality/" + "/".join(re.findall(r'"([^"]+)"', match.group(1)))
        return "" if path in reincluded else match.group(0)

    return [
        line.strip()
        for line in source.splitlines()
        if any(token in DATA_READ.sub(data, line) for token in tokens)
    ]


def _reincluded() -> set[str]:
    return {line[1:] for line in ignore_lines() if line.startswith("!quality/")}


def test_every_gate_reader_is_dev_only() -> None:
    """A module spelling a gate read is on `DEV_ONLY` or exempt by name; data is re-included."""
    reincluded = _reincluded()
    stray = {
        rel: reads
        for rel, source in _runtime_sources().items()
        if (reads := _gate_reads(source, reincluded))
        and not _on_dev_only(rel)
        and rel not in EXEMPT
    }
    assert stray == {}, f"gate readers missing from CoreConfig.DEV_ONLY: {stray}"


def test_every_exemption_still_reads_the_gate() -> None:
    """An exemption whose module no longer spells a gate read is stale and goes."""
    sources, reincluded = _runtime_sources(), _reincluded()
    stale = [rel for rel in EXEMPT if not _gate_reads(sources.get(rel, ""), reincluded)]
    assert stale == []


def test_the_image_drops_exactly_dev_only() -> None:
    """`.dockerignore`'s `apps/` lines are `DEV_ONLY`, each exists, and none survives the walk."""
    apps_lines = {line.strip("/") for line in ignore_lines() if line.startswith("apps/")}
    assert apps_lines == set(CoreConfig.DEV_ONLY)
    assert all((ROOT / entry).exists() for entry in CoreConfig.DEV_ONLY), CoreConfig.DEV_ONLY
    leaked = [rel for rel in image_files() if _on_dev_only(rel)]
    assert leaked == []
