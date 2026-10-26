"""`deploy/image_scan.sh` folds trivy into 0/1/2; two workflows scan what they build and pin."""

# does-not-cover: trivy's own answers — a fake stands in; the PR's run proves the real one.
# does-not-cover: the nightly's schedule firing — its derive step is run here, its scan in CI.
# does-not-cover: the attestation's verification — `gh attestation verify` is the report's.

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.stub_path import StubPath

pytestmark = pytest.mark.drives(
    "deploy/image_scan.sh",
    "deploy/image_scan_policy.py",
    ".github/workflows/ci.yml",
    ".github/workflows/nightly-security.yml",
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "deploy/image_scan.sh"
POLICY = ROOT / "deploy/image_scan_policy.py"
CI = ROOT / ".github/workflows/ci.yml"
NIGHTLY = ROOT / ".github/workflows/nightly-security.yml"
COMPOSE = ROOT / "deploy/compose.yaml"
PINNED = re.compile(r"image: (\S+@sha256:[0-9a-f]{64})")

#: The fake: `image` copies $FAKE_REPORT to `--output`, `convert` a stub SBOM; FAKE_FAIL fails it.
FAKE_TRIVY = """#!/usr/bin/env bash
out=""
prev=""
for a in "$@"; do
  [ "$prev" = "--output" ] && out="$a"
  prev="$a"
done
echo "$*" >>"$FAKE_ARGS"
if [ -n "${FAKE_FAIL:-}" ]; then echo "$FAKE_FAIL" >&2; exit 1; fi
case "$1" in
  image) cp "$FAKE_REPORT" "$out" ;;
  convert) echo '{"bomFormat":"CycloneDX"}' >"$out" ;;
esac
exit 0
"""


def _vuln(cve: str, severity: str, fixed: str = "") -> dict[str, Any]:
    return {
        "VulnerabilityID": cve,
        "PkgName": "openssl",
        "InstalledVersion": "1.0",
        "FixedVersion": fixed,
        "Severity": severity,
    }


def _report(*vulns: dict[str, Any]) -> dict[str, Any]:
    return {
        "SchemaVersion": 2,
        "ArtifactName": "web",
        "Results": [{"Target": "web (debian 13)", "Vulnerabilities": list(vulns)}],
    }


CLEAN = _report()
CRITICAL_FIXABLE = _report(_vuln("CVE-2026-0001", "CRITICAL", "1.1"), _vuln("CVE-2026-0002", "LOW"))
HIGH_ONLY = _report(_vuln("CVE-2026-0003", "HIGH", "1.2"), _vuln("CVE-2026-0004", "CRITICAL"))


def _policy() -> ModuleType:
    spec = importlib.util.spec_from_file_location("djb_deploy_image_scan_policy", POLICY)
    if spec is None or spec.loader is None:
        raise CouldNotLook(f"{POLICY} could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _archive(scratch: Path) -> Path:
    """A minimal OCI archive: the script needs `index.json` inside and nothing else."""
    layout = scratch / "layout"
    layout.mkdir()
    (layout / "index.json").write_text('{"schemaVersion":2,"manifests":[]}')
    (layout / "oci-layout").write_text('{"imageLayoutVersion":"1.0.0"}')
    archive = scratch / "web.tar"
    with tarfile.open(archive, "w") as tar:
        for f in layout.iterdir():
            tar.add(f, arcname=f.name)
    return archive


def _scan(
    capture: Callable[..., Captured],
    stub_path: StubPath,
    scratch: Path,
    report: dict[str, Any] | None,
    *args: str,
    fail: str = "",
    plant: bool = True,
) -> Captured:
    if plant:
        stub_path.plant("trivy", FAKE_TRIVY)
    path = f"{stub_path.bin}{os.pathsep}{os.environ['PATH']}"
    if not plant and shutil.which("trivy", path=path) is not None:
        raise CouldNotLook(f"a real trivy is on PATH ({shutil.which('trivy', path=path)})")
    fake_report = scratch / "fake-report.json"
    fake_report.write_text(json.dumps(report or {}))
    env = {
        "PATH": path,
        "HOME": str(scratch),
        "FAKE_REPORT": str(fake_report),
        "FAKE_ARGS": str(scratch / "fake-args.txt"),
        "FAKE_FAIL": fail,
    }
    return capture(["bash", str(SCRIPT), *args], cwd=ROOT, env=env)


@pytest.mark.parametrize(
    ("report", "rc", "says"),
    [
        (CLEAN, 0, "0 blocking"),
        (CRITICAL_FIXABLE, 1, "CVE-2026-0001"),
        (HIGH_ONLY, 0, "CVE-2026-0003"),
    ],
    ids=["clean", "critical-with-a-fix", "high-and-below"],
)
def test_the_scan_folds_into_zero_one_two(
    capture: Callable[..., Captured],
    stub_path: StubPath,
    scratch: Path,
    report: dict[str, Any],
    rc: int,
    says: str,
) -> None:
    run = _scan(capture, stub_path, scratch, report, str(_archive(scratch)))
    assert run.rc == rc, run.text()
    assert says in run.text()


def test_a_scanner_that_cannot_look_is_two_with_its_cause(
    capture: Callable[..., Captured], stub_path: StubPath, scratch: Path
) -> None:
    cause = "FATAL failed to download vulnerability DB: connection refused"
    run = _scan(capture, stub_path, scratch, None, str(_archive(scratch)), fail=cause)
    assert run.rc == 2, run.text()
    assert "connection refused" in run.text()


def test_no_scanner_on_path_is_two(
    capture: Callable[..., Captured], stub_path: StubPath, scratch: Path
) -> None:
    run = _scan(capture, stub_path, scratch, CLEAN, str(_archive(scratch)), plant=False)
    assert run.rc == 2, run.text()
    assert "no trivy" in run.text()


def test_report_only_prints_the_finding_and_exits_zero(
    capture: Callable[..., Captured], stub_path: StubPath, scratch: Path
) -> None:
    run = _scan(
        capture, stub_path, scratch, CRITICAL_FIXABLE, str(_archive(scratch)), "--report-only"
    )
    assert run.rc == 0, run.text()
    assert "CVE-2026-0001" in run.text() and "REPORT-ONLY" in run.text()


def test_a_remote_ref_is_scanned_from_the_registry_and_writes_its_sbom(
    capture: Callable[..., Captured], stub_path: StubPath, scratch: Path
) -> None:
    sbom = scratch / "sbom-web-tree-abc.cdx.json"
    ref = "caddy:2.10.2@sha256:" + "a" * 64
    run = _scan(capture, stub_path, scratch, CLEAN, ref, "--sbom", str(sbom))
    assert run.rc == 0, run.text()
    args = (scratch / "fake-args.txt").read_text()
    assert f"--image-src remote {ref}" in args
    assert re.search(r"^convert .*--format cyclonedx", args, re.MULTILINE), args
    assert json.loads(sbom.read_text())["bomFormat"] == "CycloneDX"


def test_an_expired_exception_is_a_finding() -> None:
    policy = _policy()
    accepted = policy.ImageException(
        cve="CVE-2026-0001",
        why="reached only through a tool the image never runs",
        images=("web",),
        declared=date(2026, 10, 1),
        until=date(2026, 11, 1),
    )
    before = policy.judge(CRITICAL_FIXABLE, "web", date(2026, 10, 21), (accepted,))
    assert before.blocking == [] and before.accepted == ["CVE-2026-0001"]
    after = policy.judge(CRITICAL_FIXABLE, "web", date(2026, 11, 2), (accepted,))
    assert any("CVE-2026-0001" in line and "expired" in line for line in after.blocking)
    elsewhere = policy.judge(CRITICAL_FIXABLE, "worker", date(2026, 10, 21), (accepted,))
    assert any("CVE-2026-0001" in line for line in elsewhere.blocking)


def test_the_declared_exceptions_are_well_formed_today() -> None:
    policy = _policy()
    assert policy.exception_failures(policy.IMAGE_EXCEPTIONS, date.today()) == []


def _steps(workflow: Path, job: str) -> list[dict[str, Any]]:
    data = yaml.safe_load(workflow.read_text())
    steps: list[dict[str, Any]] = data["jobs"][job]["steps"]
    return steps


def _index(steps: list[dict[str, Any]], needle: str) -> int:
    found = [
        i for i, s in enumerate(steps) if needle in str(s.get("run", "")) + str(s.get("uses", ""))
    ]
    if len(found) != 1:
        raise CouldNotLook(f"{needle!r} is in {len(found)} steps, not one")
    return found[0]


def test_the_images_job_scans_after_the_build_and_before_the_hand_off() -> None:
    steps = _steps(CI, "images")
    build = _index(steps, "docker buildx build")
    scan = _index(steps, 'deploy/image_scan.sh "$archive"')
    hand_off = next(i for i, s in enumerate(steps) if s.get("with", {}).get("name") == "images")
    assert build < scan < hand_off
    assert "--sbom" in steps[scan]["run"]


def test_the_push_attests_what_it_pushed() -> None:
    data = yaml.safe_load(CI.read_text())
    job = data["jobs"]["images-push"]
    assert job["permissions"]["attestations"] == "write"
    assert job["permissions"]["id-token"] == "write"
    uses = [str(s.get("uses", "")) for s in job["steps"]]
    assert any(u.startswith("actions/attest-build-provenance@") for u in uses)
    pinned = [u for u in uses if u.startswith("actions/attest-build-provenance@")][0]
    assert re.fullmatch(r"actions/attest-build-provenance@[0-9a-f]{40}", pinned), pinned


def test_the_nightly_derives_its_images_from_compose_and_never_types_them(scratch: Path) -> None:
    data = yaml.safe_load(NIGHTLY.read_text())
    triggers = data[True] if True in data else data["on"]
    assert "schedule" in triggers and "workflow_dispatch" in triggers
    steps = _steps(NIGHTLY, "images")
    derive = steps[_index(steps, "grep -oE")]
    out = scratch / "github_output"
    done = subprocess.run(
        ["bash", "-c", derive["run"]],
        cwd=ROOT,
        env={**os.environ, "GITHUB_OUTPUT": str(out)},
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    derived = out.read_text().split("images=", 1)[1].split()
    expected = sorted(set(PINNED.findall(COMPOSE.read_text())))
    assert len(expected) >= 5, f"compose.yaml pins {len(expected)} images"
    assert derived == expected
    assert not re.search(r"postgres:\d|redis:\d|caddy:\d", NIGHTLY.read_text())
    upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact@")]
    assert upload and upload[0].get("if") == "always()"
