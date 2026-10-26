"""Rule 98: harness files against their targets, the always-loaded set, the duplication census."""

# does-not-cover: whether a cut kept the meaning — the owner reads the map in the rung's report.

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from quality.checks.rule_98 import (
    always_loaded,
    harness_budget,
    harness_census,
    harness_files,
)
from quality.could_not_look import CouldNotLook

pytestmark = pytest.mark.drives("quality/checks/rule_98.py", "quality/rules.yaml")

RULE: dict[str, Any] = {
    "id": "98",
    "budgets": {"claude_md": 150, "skill": 300, "agent": 120},
    "token_bytes": 4,
    "duplicates": [
        {"say": "never pipe the gate", "pattern": r"never pipe", "owner": "scripts/gate.sh"},
    ],
}
GUIDE_HEAD = "# Guide\n\n> Load `primer` before anything else.\n\n"


def lines(n: int) -> str:
    """`n` numbered lines."""
    return "".join(f"line {i}\n" for i in range(n))


def world(root: Path, *, guide: int = 10, skill: int = 10, agent: int = 5) -> Path:
    """A guide, two skills (one the guide's header names) and one agent, each `n` lines long."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "CLAUDE.md").write_text(GUIDE_HEAD + lines(guide - 4))
    for name in ("primer", "other"):
        home = root / ".claude" / "skills" / name
        home.mkdir(parents=True)
        (home / "SKILL.md").write_text(f"---\nname: {name}\n---\n" + lines(skill - 3))
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "builder.md").write_text("---\nname: builder\n---\n" + lines(agent - 3))
    return root


def classes(root: Path, rule: dict[str, Any] = RULE) -> dict[str, int]:
    """Each finding class and its weight."""
    return {f.klass: f.weight for f in harness_budget(root, rule).findings}


def test_the_population_is_the_guide_every_skill_and_every_agent(tmp_path: Path) -> None:
    members = [m for m, _pop, _path in harness_files(world(tmp_path))]
    assert members == ["claude_md", "skills/other", "skills/primer", "agents/builder"]


def test_a_skill_over_its_target_is_counted_by_the_lines_over(tmp_path: Path) -> None:
    assert classes(world(tmp_path, skill=301))["skills/other.lines"] == 1


def test_a_skill_at_its_target_is_silent(tmp_path: Path) -> None:
    assert not [k for k in classes(world(tmp_path, skill=300)) if k.endswith(".lines")]


def test_the_guide_at_151_fires_and_at_150_is_silent(tmp_path: Path) -> None:
    assert classes(world(tmp_path / "a", guide=151))["claude_md.lines"] == 1
    assert "claude_md.lines" not in classes(world(tmp_path / "b", guide=150))


def test_a_nested_agent_over_its_target_is_its_own_member(tmp_path: Path) -> None:
    root = world(tmp_path)
    nested = root / ".claude" / "agents" / "team" / "lead.md"
    nested.parent.mkdir()
    nested.write_text(lines(121))
    assert classes(root)["agents/team/lead.lines"] == 1


def test_the_always_loaded_set_is_the_guide_the_named_skill_whole_and_every_frontmatter(
    tmp_path: Path,
) -> None:
    root = world(tmp_path)
    loaded = dict(always_loaded(root))
    assert loaded["CLAUDE.md"] == len((root / "CLAUDE.md").read_bytes())
    assert loaded[".claude/skills/primer/SKILL.md"] == len(
        (root / ".claude/skills/primer/SKILL.md").read_bytes()
    )
    assert loaded[".claude/skills/other/SKILL.md"] == len(b"---\nname: other\n---")
    assert loaded[".claude/agents/builder.md"] == len(b"---\nname: builder\n---")


def test_the_token_estimate_is_bytes_over_the_factor_rounded_up(tmp_path: Path) -> None:
    root = world(tmp_path)
    total = sum(n for _path, n in always_loaded(root))
    assert classes(root)["always_loaded.tokens"] == -(-total // 4)


def test_a_rule_with_no_budgets_could_not_look(tmp_path: Path) -> None:
    with pytest.raises(CouldNotLook):
        harness_budget(world(tmp_path), {"id": "98", "token_bytes": 4})


def test_the_census_prints_each_file_beside_its_target_and_ceiling(tmp_path: Path) -> None:
    root = world(tmp_path, skill=320)
    rule = {**RULE, "ratchets": {"skills/other.lines": 20}}
    printed = "\n".join(harness_census(root, rule))
    assert ".claude/skills/other/SKILL.md: 320 lines · target 300 · ceiling 320" in printed
    assert ".claude/skills/primer/SKILL.md: 320 lines · target 300 · ceiling 300" in printed


def test_a_planted_duplicate_is_counted_per_file_beside_its_owner(tmp_path: Path) -> None:
    root = world(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "gate.sh").write_text("# never pipe it\n")
    (root / "scripts" / "copy.sh").write_text("# Never pipe the gate.\n")
    (root / ".claude/skills/other/SKILL.md").write_text("never pipe it, twice: never pipe\n")
    printed = harness_census(root, RULE)
    head = next(line for line in printed if "'never pipe the gate'" in line)
    assert "owner scripts/gate.sh (states it)" in head
    assert "restated in 2 files — delete once the owner says which owns it" in head
    assert "    scripts/copy.sh" in printed
    assert "    .claude/skills/other/SKILL.md" in printed


def test_the_owner_s_numbers_are_the_declared_targets() -> None:
    rules = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / "quality/rules.yaml").read_text()
    )["rules"]
    rule = next(r for r in rules if str(r["id"]) == "98")
    assert rule["budgets"] == {"claude_md": 150, "skill": 300, "agent": 120}
