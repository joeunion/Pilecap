"""`scripts/envelope.sh` refuses before any box exists when the sha is not the tree it pushes."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "envelope.sh"


def _run(tmp_path: Path, *args: str) -> tuple[int, str]:
    out = tmp_path / "out.txt"
    with out.open("w") as sink:
        done = subprocess.run(
            ["bash", str(SCRIPT), *args],
            stdout=sink,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            timeout=60,
        )
    return done.returncode, out.read_text()


def test_a_sha_that_is_not_head_is_refused_before_a_box(tmp_path: Path) -> None:
    parent = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD~1"], capture_output=True, text=True
    ).stdout.strip()
    status, said = _run(tmp_path, parent)
    assert status == 2, said
    assert "is not HEAD" in said
    assert "verifier_box" not in said


def test_help_prints_the_synopsis(tmp_path: Path) -> None:
    status, said = _run(tmp_path, "--help")
    assert status == 0, said
    assert "scripts/envelope.sh <sha>" in said
    assert "does-not-cover: client-side saturation" in said


def test_an_unknown_shape_is_refused_before_a_box(tmp_path: Path) -> None:
    head = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    status, said = _run(tmp_path, head, "--shape", "two-box")
    assert status == 2, said
    assert "--shape takes prod or one-box" in said
    assert "verifier_box" not in said


def test_the_probe_tells_a_listener_from_a_closed_port(tmp_path: Path) -> None:
    listener = socket.create_server(("127.0.0.1", 0))
    closed = socket.create_server(("127.0.0.1", 0))
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        status, said = _run(
            tmp_path,
            "--on-box",
            "probe",
            "127.0.0.1",
            str(listener.getsockname()[1]),
            str(closed_port),
        )
    finally:
        listener.close()
    assert status == 0, said
    lines = [line for line in said.splitlines() if line.startswith("probe ")]
    assert lines[0].endswith(" open") and lines[1] == f"probe 127.0.0.1:{closed_port} reachable"


UTILIZATION = ROOT / "deploy" / "load" / "utilization.sh"
IMAGE_PROJECT = "djangobootstrap"
FAKE_DOCKER = """#!/usr/bin/env bash
state="$(dirname "$0")/stopped"
case "$1" in
ps)
    if [ "$2" = "-q" ]; then
        [ -e "$state" ] || printf 'aaa\\nbbb\\n'
    else
        printf 'djb_deploy_1\\tdjb_deploy_1-web-1\\tweb:t\\n'
        [ -e "$state" ] || printf 'djangobootstrap\\tdjangobootstrap-zitadel-1\\tzitadel:v\\n'
    fi ;;
stats) printf 'djangobootstrap-zitadel-1 12.50%%\\ndjangobootstrap-db-1 1.25%%\\n' ;;
stop) shift; echo "$@" >"$state" ;;
esac
"""


def _fake_docker(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o755)
    return bin_dir


def _census(tmp_path: Path, docker: Path) -> tuple[int, str]:
    out = tmp_path / "census.txt"
    stat = tmp_path / "stat"
    stat.write_text("cpu  100 0 100 800 0 0 0 0 0 0\n")
    later = tmp_path / "stat-later"
    later.write_text("cpu  200 0 200 1000 0 0 0 0 0 0\n")
    done = subprocess.run(
        [
            "bash",
            str(UTILIZATION),
            "--cpu-only",
            "--samples",
            "1",
            "--interval",
            "0",
            "--census",
            str(out),
            "--own-project",
            "djb_deploy_1",
            "--docker",
            str(docker),
            "--proc-stat",
            str(stat),
            "--proc-stat",
            str(later),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return done.returncode, out.read_text() if out.exists() else done.stderr


def test_the_compose_file_names_the_image_project() -> None:
    names = [
        line.split()[1]
        for line in (ROOT / "compose.yaml").read_text().splitlines()
        if line.startswith("name:")
    ]
    assert names == [IMAGE_PROJECT]


def test_the_census_says_shared_while_the_image_stack_runs_and_bare_after(
    tmp_path: Path,
) -> None:
    bin_dir = _fake_docker(tmp_path)
    status, census = _census(tmp_path, bin_dir / "docker")
    assert status == 0, census
    assert census.splitlines()[-1] == "host=shared others=djangobootstrap-zitadel-1"
    (bin_dir / "stopped").write_text("")
    status, census = _census(tmp_path, bin_dir / "docker")
    assert status == 0, census
    assert census.splitlines() == ["djb_deploy_1\tdjb_deploy_1-web-1\tweb:t", "host=bare"]


def test_the_image_stack_is_stopped_and_its_cpu_named(tmp_path: Path) -> None:
    bin_dir = _fake_docker(tmp_path)
    out = tmp_path / "out.txt"
    with out.open("w") as sink:
        done = subprocess.run(
            ["bash", str(SCRIPT), "--on-box", "image-stack"],
            stdout=sink,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
            timeout=60,
            env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path)},
        )
    said = out.read_text()
    assert done.returncode == 0, said
    assert (bin_dir / "stopped").read_text().split() == ["aaa", "bbb"]
    assert f"({IMAGE_PROJECT}) stopped: 2 containers, 13.8% of one core" in said


def test_every_stack_box_stops_the_image_stack_before_its_own_comes_up() -> None:
    text = SCRIPT.read_text()
    for role in ("on_box_one", "on_box_organs", "on_box_web"):
        body = text.split(f"\n{role}() {{\n", 1)[1].split("\n}\n", 1)[0]
        stop = body.index("image_stack_stopped")
        up = min(i for i in (body.find(" up -d"), body.find("provision.sh up")) if i >= 0)
        assert stop < up, role
        assert "--census " in body and "--own-project " in body, role


def test_the_organs_box_defaults_to_m7g_xlarge() -> None:
    """The organs box defaults to `m7g.xlarge`, set in one place and named in the header."""
    laptop = SCRIPT.read_text().split("# --- the laptop half ---", 1)[1]
    defaults = [line for line in laptop.splitlines() if line.startswith("organs_type=")]
    assert defaults == ["organs_type=m7g.xlarge"]
    assert "The ORGANS box (default m7g.xlarge)" in SCRIPT.read_text()


def test_both_halves_of_the_prod_shape_declare_their_clock_offset() -> None:
    text = SCRIPT.read_text()
    for role in ("on_box_web", "on_box_drive"):
        body = text.split(f"\n{role}() {{\n", 1)[1].split("\n}\n", 1)[0]
        assert "chronyc tracking" in body and "System time" in body, role


def _functions(*names: str) -> str:
    text = SCRIPT.read_text()
    return "\n".join(
        f"{name}() {{\n" + text.split(f"\n{name}() {{\n", 1)[1].split("\n}\n", 1)[0] + "\n}"
        for name in names
    )


def _bash(tmp_path: Path, body: str, *names: str) -> tuple[int, str]:
    script = tmp_path / "harness.sh"
    script.write_text(
        "set -euo pipefail\n"
        f". {ROOT / 'scripts' / 'gate_refuse.sh'}\n"
        f"{_functions(*names)}\n"
        f"{body}\n"
    )
    done = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
        env={**os.environ, "W": str(tmp_path)},
    )
    return done.returncode, done.stdout + done.stderr


def test_the_realtime_probe_prints_its_line_or_could_not_look(tmp_path: Path) -> None:
    body = """PROBE_SOCKETS=50 PROBE_EVENTS=20
fine() { echo noise; echo "realtime=p95_ms=12.0 sockets=$2 load=$6"; }
blind() { echo 'COULD NOT LOOK: no frame | in 30 s'; return 2; }
realtime_probe conc-16 drive-box fine
realtime_probe idle drive-box blind"""
    status, said = _bash(tmp_path, body, "realtime_probe")
    assert status == 0, said
    lines = [line for line in said.splitlines() if line.startswith("== REALTIME")]
    assert lines == [
        "== REALTIME · realtime=p95_ms=12.0 sockets=50 load=conc-16",
        "== REALTIME · realtime=could-not-look sockets=50 events=20 load=idle "
        "client=drive-box exit=2 why=no-frame-_-in-30-s",
    ]


def test_the_socket_probe_runs_inside_the_soak_then_idle_after(tmp_path: Path) -> None:
    body = """PROBE_SOCKETS=50 PROBE_EVENTS=20
realtime_probe() { echo "probe $1 $2 $3"; }
SOAK=(sh -c 'sleep 1; echo soak-done')
PROBE=(probe-cmd)
soak_and_probe 0 16 drive-box
SOAK=(sh -c 'sleep 1; echo soak-failed; exit 3')
rc=0; soak_and_probe 0 16 drive-box || rc=$?
echo "rc=$rc\""""
    status, said = _bash(tmp_path, body, "soak_and_probe")
    assert status == 0, said
    lines = [ln for ln in said.splitlines() if ln.startswith(("probe ", "soak-", "rc="))]
    assert lines == [
        "probe conc-16 drive-box probe-cmd",
        "soak-done",
        "probe idle drive-box probe-cmd",
        "probe conc-16 drive-box probe-cmd",
        "soak-failed",
        "rc=3",
    ]


def test_record_writes_every_realtime_line_under_the_one_entry(tmp_path: Path) -> None:
    capacity = tmp_path / "capacity.md"
    capacity.write_text("## 9\n- older\n<!-- recorded-knees end -->\ntail\n")
    (tmp_path / "work").mkdir()
    body = f"""CAPACITY={capacity} MARK_END='<!-- recorded-knees end -->' work={tmp_path / "work"}
full=0123456789abcdef t0=$(date +%s)
rt="$(printf 'realtime=a load=conc-16\\nrealtime=b load=idle')"
record 'metric=e' 'soak=steady' 'c7g.xlarge' "$rt" bare"""
    status, said = _bash(tmp_path, body, "record")
    assert status == 0, said
    lines = capacity.read_text().splitlines()
    at = lines.index("<!-- recorded-knees end -->")
    assert (
        lines[at - 5].startswith("- ")
        and "sha `0123456789ab` · `c7g.xlarge` · host=bare" in (lines[at - 5])
    )
    assert lines[at - 4 : at] == [
        "  - `metric=e`",
        "  - `soak=steady`",
        "  - `realtime=a load=conc-16`",
        "  - `realtime=b load=idle`",
    ]
    silent = body.rsplit("\n", 1)[0] + "\nrecord 'metric=e' 'soak=steady' 'c7g.xlarge' '' bare"
    status, said = _bash(tmp_path, silent, "record")
    assert status == 2 and "no REALTIME line" in said


def test_the_identity_home_count_names_the_staff_realm() -> None:
    body = SCRIPT.read_text().split("\nidentity_homes() {\n", 1)[1].split("\n}\n", 1)[0]
    assert "(of $want seeded tenants + the staff realm)" in body


def test_a_chrony_line_reads_as_a_signed_offset(tmp_path: Path) -> None:
    body = """echo 'System time     : 0.000012345 seconds fast of NTP time' | chrony_offset; echo
echo 'System time     : 0.000400000 seconds slow of NTP time' | chrony_offset; echo
echo 'System time : unread, chronyc did not answer' | chrony_offset; echo"""
    status, said = _bash(tmp_path, body, "chrony_offset")
    assert status == 0, said
    assert said.splitlines() == ["+0.000012345s", "-0.000400000s", ""]


def test_the_drive_half_hands_the_probe_both_clocks() -> None:
    text = SCRIPT.read_text()
    body = text.split("\non_box_drive() {\n", 1)[1].split("\n}\n", 1)[0]
    assert "--clock" in body and "clock-web.txt" in body and "chrony_offset" in body
    laptop = text.split("# --- the laptop half ---", 1)[1]
    assert "clock-web.txt" in laptop
