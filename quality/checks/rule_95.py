"""Rule 95: on a product's tree, a commit touching the platform or stack carries its sanction."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from quality.checks._hub import CheckResult

#: The census this rule runs, never re-implements (`quality/djb/boundary.py::census`).
_BOUNDARY = "quality/djb/boundary.py"


def system_layer_commits_carry_their_sanction(root: Path, rule: dict) -> CheckResult:
    """Rule 95. Turn the boundary census's rows into findings; its exit 2 is a could-not-look."""
    out = CheckResult()
    if not (root / _BOUNDARY).is_file():
        out.hit(
            _BOUNDARY, 0, "rule 95's census is not in this tree; nothing was judged", klass="census"
        )
        return out
    with tempfile.NamedTemporaryFile("w+", prefix="djb-rule95-", suffix=".log") as sink:
        proc = subprocess.run(
            [sys.executable, "-m", "quality.djb.boundary", "--census"],
            cwd=root,
            stdout=sink,
            stderr=subprocess.STDOUT,
            check=False,
        )
        sink.seek(0)
        report = sink.read()
    if proc.returncode not in (0, 1):
        out.hit(
            _BOUNDARY,
            0,
            "rule 95's census could not look (exit "
            f"{proc.returncode}); an unjudged history is not a sanctioned one. Output:\n"
            + report.strip()[-1500:],
            klass="census",
        )
        return out
    for line in report.splitlines():
        if line.startswith("census: platform_paths="):
            for item in line.removeprefix("census: ").split():
                key, _, value = item.partition("=")
                if value.isdigit():
                    out.count(key, int(value))
        elif line.startswith("unsanctioned: "):
            sha, path, _count, subject = (
                part.strip() for part in line.removeprefix("unsanctioned: ").split(" · ", 3)
            )
            out.hit(
                path,
                1,
                f"commit {sha} ('{subject}') touches `{path}` — the platform's or the stack's — "
                "with no `Layer-Sanction:` trailer and is no fold commit: it stepped around the "
                'hook. Revert it, or re-commit it under DJB_LAYER_SANCTION="<who>: <why>".',
                klass="unsanctioned",
            )
        elif line.startswith("pending: "):
            path, sentence = line.removeprefix("pending: ").split(" · ", 1)
            out.hit(path, 1, f"uncommitted: {sentence}", klass="pending")
    return out
