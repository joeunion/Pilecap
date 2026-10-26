"""Rule 94: a product diff pays no platform member."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from quality.checks._hub import CheckResult

#: The census this check reads: `quality.djb.scope`'s, run as a process (the import contract).
CENSUS = (sys.executable, "-m", "quality.djb.scope", "product-census")


def product_diff_pays_no_platform_member(root: Path, rule: dict) -> CheckResult:
    """Rule 94. The census's findings and counts, read from a file; its exit 2 is a finding."""
    out = CheckResult()
    with tempfile.NamedTemporaryFile("w+", prefix="djb-rule94-", suffix=".log") as sink:
        done = subprocess.run(
            [*CENSUS, "--root", str(root)], cwd=root, stdout=sink, stderr=subprocess.STDOUT
        )
        sink.flush()
        sink.seek(0)
        report = sink.read()
    if done.returncode != 0:
        out.hit("quality/djb/scope.py", 0, f"rule 94's census could not look:\n{report[-1500:]}")
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
