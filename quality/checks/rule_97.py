"""Rule 97: the SDK's surface is the tree's, and keeps every name the last release promised."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from quality.checks._hub import CheckResult

#: The census this check reads: `quality.sdk.surface`'s, run as a process (the import contract).
CENSUS = (sys.executable, "-m", "quality.sdk", "--ratchet")
#: The checkout whose `quality` package runs the census, whichever tree it reads.
HOME = str(Path(__file__).resolve().parents[2])


def sdk_surface_is_ratcheted(root: Path, rule: dict[str, object]) -> CheckResult:
    """Rule 97. The census's findings and counts, read from a file; its exit 2 is a finding."""
    out = CheckResult()
    with tempfile.NamedTemporaryFile("w+", prefix="djb-rule97-", suffix=".log") as sink:
        done = subprocess.run(
            [*CENSUS, "--root", str(root)],
            cwd=root,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONPATH": HOME},
        )
        sink.flush()
        sink.seek(0)
        report = sink.read()
    if done.returncode != 0:
        out.hit("quality/sdk/surface.py", 0, f"rule 97's census could not look:\n{report[-1500:]}")
        return out
    for line in report.splitlines():
        word, _, rest = line.partition(" ")
        if word == "count":
            key, _, n = rest.partition(" ")
            out.count(key, int(n))
        elif word == "finding":
            path, klass, why = rest.split("\t", 2)
            out.hit(path, 0, why, klass=klass)
    return out
