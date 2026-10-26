"""A ratchet over recorded debt (a rule's `debt:`): its member floors, summed from the floors."""

# does-not-cover: whether a floor is the measured count — the engine's ratchet judges that.

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

#: The machine line a release section carries: `ratchet-debt: 91=<n> 98=<m>`.
DEBT_LINE = re.compile(r"^ratchet-debt:((?:\s+[0-9A-Za-z-]+=[0-9]+)+)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class Debt:
    """One rule's recorded debt: the lines its floors hold, over how many members, since when."""

    rule: str
    lines: int
    members: int
    since: str

    def sentence(self) -> str:
        """The `--explain` line: what the rule is, in its own figures."""
        return (
            f"a ratchet over recorded debt: {self.lines} lines across {self.members} members, "
            f"down-only since {self.since}; a standard for NEW files"
        )


def debt_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The enabled rules that declare `debt:`, in rule order."""
    return [r for r in rules if r.get("debt") and r.get("enabled", True)]


def debt_of(rule: dict[str, Any], floors: Mapping[str, int]) -> Debt:
    """`rule`'s debt over `floors` (`<member>.<class>` → count), its `debt.counts` summed."""
    declared = rule.get("debt") or {}
    counted = set(declared.get("counts") or rule.get("member_classes") or ())
    held: dict[str, int] = {}
    for klass, count in floors.items():
        member, _, suffix = str(klass).partition(".")
        if suffix in counted and int(count) > 0:
            held[member] = held.get(member, 0) + int(count)
    return Debt(str(rule["id"]), sum(held.values()), len(held), str(declared.get("since", "?")))


def debts_at(root: Path) -> dict[str, Debt]:
    """Every `debt:` rule's debt as `root`'s own rules and floors record it."""
    from quality.checks._hub import read_member_floors

    rules = (yaml.safe_load((root / "quality/rules.yaml").read_text()) or {}).get("rules") or []
    declared = debt_rules(rules)
    if not declared:
        return {}
    by_rule = {
        str(r["id"]): [str(c) for c in r["member_classes"]]
        for r in rules
        if r.get("member_classes")
    }
    floors, problems = read_member_floors(root, by_rule, ())
    if problems:
        raise ValueError("; ".join(problems))
    out: dict[str, Debt] = {}
    for rule in declared:
        rid = str(rule["id"])
        out[rid] = debt_of(rule, {f.klass: f.count for f in floors if f.rule == rid})
    return out


def machine_line(debts: Mapping[str, Debt]) -> str:
    """`ratchet-debt: 91=<n> 98=<m>` — the line a release section carries, rule order kept."""
    return "ratchet-debt: " + " ".join(f"{rid}={d.lines}" for rid, d in debts.items())


def read_machine_line(text: str) -> dict[str, int] | None:
    """The `ratchet-debt:` figures one CHANGELOG section carries; None when it carries none."""
    found = DEBT_LINE.search(text)
    if found is None:
        return None
    pairs = (pair.split("=", 1) for pair in found.group(1).split())
    return {rid: int(n) for rid, n in pairs}
