"""Rule 91 over an app the scaffold or `newapp` wrote: a new tail is a line to delete."""

# does-not-cover: a floor the write left headroom under — the engine prints its lower line.

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

#: Rule 91's census of one app, run beside the engine as the tidy is: `<class> <lines>` per class.
PROGRAM = """
import sys
from pathlib import Path

import yaml

from quality.checks.rule_91 import comment_doctrine

root, label = Path(sys.argv[1]), sys.argv[2]
rules = yaml.safe_load((root / "quality/rules.yaml").read_text())["rules"]
rule = next(r for r in rules if str(r["id"]) == "91")
seen: dict[str, int] = {}
for finding in comment_doctrine(root, rule).findings:
    member, _, klass = finding.klass.partition(".")
    if member == label:
        seen[klass] = seen.get(klass, 0) + finding.weight
for klass, lines in sorted(seen.items()):
    print(klass, lines)
"""


def measure(root: Path, label: str) -> dict[str, int] | None:
    """Rule 91's line count per class of `apps/<label>`, or None when the census could not run."""
    with tempfile.TemporaryFile("w+") as said:
        done = subprocess.run(  # noqa: S603 — argv list to this interpreter running a module constant program
            [sys.executable, "-P", "-c", PROGRAM, str(root), label],
            cwd=root,
            env={**os.environ, "PYTHONPATH": str(root)},
            stdout=said,
            stderr=subprocess.STDOUT,
            text=True,
        )
        said.seek(0)
        lines = said.read().splitlines()
    if done.returncode != 0:
        return None
    return {klass: int(count) for klass, count in (line.split() for line in lines)}


def said(label: str, before: dict[str, int], after: dict[str, int]) -> list[str]:
    """One line per class this write grew: rule 91 records no floor for it (`inflow: refused`)."""
    out: list[str] = []
    for klass in sorted(after):
        grown = after[klass] - before.get(klass, 0)
        if grown > 0:
            out.append(
                f"rule 91: apps/{label} gained {grown} {klass} line(s) — a new tail is judged at "
                "zero and no floor is recorded for it (`inflow: refused`): delete them"
            )
    return out


def record(root: Path, label: str, before: dict[str, int] | None) -> list[str]:
    """Measure `apps/<label>` and say each class this write grew past `before`; writes nothing."""
    after = measure(root, label)
    if after is None:
        return [
            f"rule 91: NOT measured (the census could not run) — the house rules print each "
            f"tail in apps/{label} as a finding."
        ]
    return said(label, before or {}, after)
