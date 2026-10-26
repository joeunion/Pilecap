"""Judge a trivy JSON report: a fixable CRITICAL blocks unless a live exception accepts it."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

#: The longest an exception may stand before it is declared again (principle 20).
MAX_EXCEPTION_DAYS = 60

#: The one severity that blocks, when the report names a fixed version.
BLOCKS = "CRITICAL"

#: The severities whose findings are printed line by line; the rest are counted.
LISTED = ("CRITICAL", "HIGH")

VULN_ID_RE = re.compile(r"^(CVE-\d{4}-\d{4,}|GHSA(-[23456789cfghjmpqrvwx]{4}){3})$")


@dataclass(frozen=True)
class ImageException:
    """One vulnerability accepted in the named images until `until`, at most MAX_EXCEPTION_DAYS."""

    cve: str
    why: str
    images: tuple[str, ...]
    declared: date
    until: date


#: The declared exceptions; an image is named as the scan names it (a service, or a repository).
IMAGE_EXCEPTIONS: tuple[ImageException, ...] = (
    *(
        ImageException(
            cve=cve,
            why=(
                "perl-base in node:26.4.0-slim's Debian layer; the frontend runs"
                " `node server.js` as uid 1000 and never invokes perl"
            ),
            images=("frontend",),
            declared=date(2026, 10, 21),
            until=date(2026, 11, 20),
        )
        for cve in ("CVE-2026-13221", "CVE-2026-42496", "CVE-2026-8376")
    ),
    ImageException(
        cve="CVE-2026-59873",
        why="node-tar inside the base image's global npm; the frontend's runtime never runs npm",
        images=("frontend",),
        declared=date(2026, 10, 21),
        until=date(2026, 11, 20),
    ),
)


@dataclass
class Verdict:
    """One report's blocking lines, accepted ids, listed lines and counts by severity."""

    blocking: list[str] = field(default_factory=list)
    accepted: list[str] = field(default_factory=list)
    listed: list[str] = field(default_factory=list)
    counts: Counter[str] = field(default_factory=Counter)


def exception_failures(exceptions: Sequence[ImageException], today: date) -> list[str]:
    """Every declared exception that is malformed or expired, one sentence each naming it."""
    wrong: list[str] = []
    seen: set[str] = set()
    for e in exceptions:
        if not VULN_ID_RE.match(e.cve):
            wrong.append(f"{e.cve!r} is not a CVE or GHSA id")
        if e.cve in seen:
            wrong.append(f"{e.cve} is declared twice")
        seen.add(e.cve)
        if not e.why.strip() or "\n" in e.why:
            wrong.append(f"{e.cve} carries no one-line why")
        if not e.images or not all(i.strip() for i in e.images):
            wrong.append(f"{e.cve} names no image it was judged in")
        if e.declared > today:
            wrong.append(f"{e.cve} is declared in the future ({e.declared.isoformat()})")
        span = (e.until - e.declared).days
        if not 0 < span <= MAX_EXCEPTION_DAYS:
            wrong.append(f"{e.cve} stands {span} days, outside 1..{MAX_EXCEPTION_DAYS}")
        if e.until < today:
            wrong.append(
                f"{e.cve} expired on {e.until.isoformat()} — bump the image or declare it again"
            )
    return wrong


def _vulnerabilities(report: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every vulnerability in the report; `ValueError` when the report is not trivy's JSON shape."""
    results = report.get("Results")
    if "SchemaVersion" not in report or not isinstance(results, list):
        raise ValueError("the report has no SchemaVersion or no Results list")
    found: list[Mapping[str, Any]] = []
    for result in results:
        if not isinstance(result, Mapping):
            raise ValueError("a Results entry is not an object")
        found.extend(v for v in result.get("Vulnerabilities") or [] if isinstance(v, Mapping))
    return found


def judge(
    report: Mapping[str, Any],
    image: str,
    today: date,
    exceptions: Sequence[ImageException] | None = None,
) -> Verdict:
    """Block a fixable CRITICAL not accepted for this image; a bad or expired exception blocks."""
    declared = IMAGE_EXCEPTIONS if exceptions is None else exceptions
    verdict = Verdict(blocking=exception_failures(declared, today))
    live = {e.cve for e in declared if image in e.images and e.declared <= today <= e.until}
    for v in _vulnerabilities(report):
        severity = str(v.get("Severity") or "UNKNOWN")
        verdict.counts[severity] += 1
        cve = str(v.get("VulnerabilityID") or "?")
        fixed = str(v.get("FixedVersion") or "")
        package = f"{v.get('PkgName', '?')} {v.get('InstalledVersion', '?')}"
        line = f"{cve} {severity} {package} → {fixed or 'no fix'}"
        if severity == BLOCKS and fixed and cve in live:
            verdict.accepted.append(cve)
        elif severity == BLOCKS and fixed:
            verdict.blocking.append(line)
        elif severity in LISTED:
            verdict.listed.append(line)
    return verdict


def main(argv: Sequence[str], today: date | None = None) -> int:
    """Print the verdict for one report and answer its exit status."""
    args = [a for a in argv if a != "--report-only"]
    report_only = len(args) != len(argv)
    if len(args) != 2:
        print("usage: image_scan_policy.py <report.json> <image> [--report-only]", file=sys.stderr)
        return 2
    path, image = Path(args[0]), args[1]
    try:
        verdict = judge(json.loads(path.read_text()), image, today or date.today())
    except (OSError, ValueError) as error:
        print(
            f"image_scan: {image}: the report {path} could not be read ({error})", file=sys.stderr
        )
        return 2
    counts = " · ".join(f"{s} {verdict.counts[s]}" for s in sorted(verdict.counts)) or "none"
    print(f"image_scan: {image}: {len(verdict.blocking)} blocking · findings: {counts}")
    for cve in verdict.accepted:
        print(f"  accepted: {cve} (a declared exception in deploy/image_scan_policy.py)")
    for line in verdict.listed:
        print(f"  reported: {line}")
    for line in verdict.blocking:
        print(f"  BLOCKING: {line}")
    if verdict.blocking and report_only:
        print(f"image_scan: {image}: REPORT-ONLY — {len(verdict.blocking)} would block")
        return 0
    return 1 if verdict.blocking else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
