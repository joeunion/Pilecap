"""The transport's helpers for its partitions: a fed and sunk bounded ssh, the scp argv, capture."""

from __future__ import annotations

import time

import pytest

from quality.djb.box.core import load_config
from quality.djb.box.transport import DEVNULL, PIPE, STDOUT, Transport, capture
from quality.tests.conftest import REAL_TIME_CEILING_S
from quality.tests.fixtures.box_world import NS, RG, World

pytestmark = pytest.mark.drives("quality/djb/box/transport.py")

SH = {"PATH": "/usr/bin:/bin"}
NOISY = ["sh", "-c", "echo out; echo err >&2; exit 3"]


def _transport(world: World) -> Transport:
    world.keyed_box()
    return Transport(load_config(world.env()))


def test_ssh_within_feeds_stdin_and_sinks_stderr_on_the_one_argv(world: World) -> None:
    transport = _transport(world)
    feed = world.root / "feed"
    feed.write_bytes(b"payload\n")
    errors = world.root / "errors"
    world.ssh(1, "hang", 'cat >"$REC/ssh/1.fed"; echo answered; echo complained >&2; exit 0\n')
    with feed.open("rb") as source, errors.open("wb") as sink:
        rc, out = transport.ssh_within(5, "i-up1", "cat >/dev/null", stdin=source, stderr=sink)
    assert (rc, out) == (0, "answered\n")
    assert (world.rec / "ssh" / "1.fed").read_bytes() == b"payload\n"
    assert errors.read_text() == "complained\n"
    argv = transport.ssh_argv("i-up1", "cat >/dev/null")
    assert world.ssh_flat(1) == " ".join(argv[1:]) + " "


def test_ssh_within_by_default_discards_stderr_and_keeps_the_recorded_line(world: World) -> None:
    transport = _transport(world)
    world.ssh(1, "out", "abc\n")
    world.ssh(1, "err", "a warning\n")
    assert transport.ssh_within(5, "i-up1", "true") == (0, "abc\n")
    flat = world.ssh_flat(1)
    for want in (
        "ProxyCommand=aws ssm start-session --target %h --document-name AWS-StartSSHSession",
        f"--profile {NS}-verifier",
        f"--region {RG}",
        "-o ServerAliveInterval=30",
        "verifier@i-up1",
        "touch /run/verifier/last-activity 2>/dev/null || true; true ",
    ):
        assert want in flat


def test_a_fed_session_is_still_bounded_by_real_time(world: World) -> None:
    transport = _transport(world)
    world.ssh(1, "hang", ":\n")
    feed = world.root / "feed"
    feed.write_bytes(b"x")
    started = time.monotonic()
    with feed.open("rb") as source:
        assert transport.ssh_within(1, "i-up1", "true", stdin=source) == (124, "")
    assert time.monotonic() - started < REAL_TIME_CEILING_S


def test_scp_argv_carries_the_key_the_tunnel_and_no_host_key_pinning(world: World) -> None:
    transport = _transport(world)
    key = str(world.vhome / "i-up1" / "id_ed25519")
    assert transport.scp_argv("i-up1", "a", "verifier@i-up1:b") == [
        "scp",
        "-i",
        key,
        "-o",
        "ProxyCommand=aws ssm start-session --target %h --document-name AWS-StartSSHSession"
        f" --parameters portNumber=%p --profile {NS}-verifier --region {RG}",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
        "a",
        "verifier@i-up1:b",
    ]


def test_scp_argv_is_the_push_programs_byte_for_byte(world: World) -> None:
    from quality.djb.box.core import Box
    from quality.djb.box.push import scp_argv

    box = Box(load_config(world.env()))
    world.keyed_box()
    assert box.scp_argv("i-up1", "x", "y") == scp_argv(box, "i-up1", "x", "y")


def test_capture_answers_the_status_and_stdout_and_drops_stderr() -> None:
    assert capture(NOISY, env=SH) == (3, "out")


def test_capture_folds_stderr_in_when_asked() -> None:
    assert capture(NOISY, env=SH, stderr=STDOUT) == (3, "out\nerr")


def test_the_redirections_are_the_standard_librarys() -> None:
    import subprocess

    assert (PIPE, DEVNULL, STDOUT) == (subprocess.PIPE, subprocess.DEVNULL, subprocess.STDOUT)
