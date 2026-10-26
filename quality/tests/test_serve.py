"""`scripts/serve.sh`'s port: derived per checkout, pinnable, refused when another holds it.

does-not-cover: it never runs uvicorn — every case asks for the port or stops at a refusal.
does-not-cover: the two-checkout cases run a copy of `serve.sh` and `db.sh` in scratch directories.
does-not-cover: the race between `serve.sh`'s probe and its exec — declared in `serve.sh`'s header.
does-not-cover: collision probability in the window; only compose's published ports are asserted.
does-not-cover: whether the holder `lsof` names is the right holder — only that the pid appears.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook

pytestmark = pytest.mark.drives(
    "compose.yaml",
    "scripts/db.sh",
    "scripts/kill_mine.sh",
    "scripts/queue_cited.sh",
    "scripts/serve.sh",
    "scripts/sweep.sh",
)

ROOT = Path(__file__).resolve().parents[2]
SERVE = ROOT / "scripts" / "serve.sh"
UNSET = ("PORT", "DATABASE_NAME", "DATABASE_NAME_SOURCE", "DJANGO_SETTINGS_MODULE")
COPIED = ("serve.sh", "bash_only.sh", "gate_refuse.sh", "db.sh")


@dataclass(frozen=True)
class Served:
    """One `serve.sh` run, its streams apart: the port is on stdout and nothing else."""

    rc: int
    out: str
    err: str

    @property
    def both(self) -> str:
        """Both streams, for a failing assertion's message."""
        return self.err + self.out


@pytest.fixture
def serve(scratch: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Served]:
    """`serve(script, *args, PORT=…)` runs a `serve.sh` with stdout and stderr to separate files."""
    if not os.access(SERVE, os.X_OK):
        raise CouldNotLook("scripts/serve.sh is not an executable file in this tree")
    if not (ROOT / "scripts" / "db.sh").is_file() or not (ROOT / "compose.yaml").is_file():
        raise CouldNotLook("scripts/db.sh or compose.yaml is not in this tree")
    for name in UNSET:
        monkeypatch.delenv(name, raising=False)
    count = 0

    def run(script: Path, *args: str, **env: str) -> Served:
        nonlocal count
        count += 1
        out, err = scratch / f"out{count}.log", scratch / f"err{count}.log"
        with out.open("wb") as o, err.open("wb") as e:
            done = subprocess.run(
                [str(script), *args],
                cwd=ROOT,
                stdout=o,
                stderr=e,
                stdin=subprocess.DEVNULL,
                env={**os.environ, **env},
            )
        return Served(done.returncode, out.read_text(), err.read_text())

    return run


@pytest.fixture
def checkout_copy(scratch: Path) -> Callable[[str], Path]:
    """`checkout_copy(name)`: a scratch directory with `serve.sh` and `db.sh` is a checkout."""

    def build(name: str) -> Path:
        root = scratch / name
        (root / "scripts").mkdir(parents=True)
        for file in COPIED:
            shutil.copy2(ROOT / "scripts" / file, root / "scripts" / file)
        return root

    return build


@pytest.fixture
def hold() -> Iterator[Callable[[int], None]]:
    """`hold(port)` listens on 127.0.0.1:port, as another checkout's server would."""
    held: list[socket.socket] = []

    def bind(port: int) -> None:
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            holder.bind(("127.0.0.1", port))
        except OSError as error:
            holder.close()
            raise CouldNotLook(
                f"the scratch holder never bound 127.0.0.1:{port}: {error}"
            ) from error
        holder.listen(5)
        held.append(holder)

    yield bind
    for holder in held:
        holder.close()


def port_is_free(port: int) -> bool:
    """Whether nothing listens on 127.0.0.1:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def free_port() -> int:
    """A port nothing listens on, taken from the derived window."""
    for port in range(20000, 30000):
        if port_is_free(port):
            return port
    raise CouldNotLook("no free port in 20000-29999")


def held_or_free(hold: Callable[[int], None], port: int) -> None:
    """Hold `port` unless something already does — a live server there is the case's condition."""
    if port_is_free(port):
        hold(port)


def test_the_port_is_derived_and_stable(serve: Callable[..., Served]) -> None:
    first = serve(SERVE, "--print-port")
    assert first.rc == 0, first.both
    second = serve(SERVE, "--print-port")
    assert first.out and first.out == second.out, (first.out, second.out)


def test_two_checkouts_derive_different_ports(
    serve: Callable[..., Served], checkout_copy: Callable[[str], Path]
) -> None:
    alpha = serve(checkout_copy("alpha") / "scripts" / "serve.sh", "--print-port")
    bravo = serve(checkout_copy("bravo") / "scripts" / "serve.sh", "--print-port")
    assert alpha.rc == 0, alpha.both
    assert bravo.rc == 0, bravo.both
    pa, pb = alpha.out.strip(), bravo.out.strip()
    assert pa and pb and pa != pb, (pa, pb)
    assert "8000" not in (pa, pb)


def test_the_port_says_where_it_came_from(serve: Callable[..., Served]) -> None:
    ran = serve(SERVE, "--print-port")
    assert ran.rc == 0, ran.both
    assert "derived from this checkout" in ran.both
    assert str(ROOT) in ran.both
    assert len(ran.out.splitlines()) == 1, ran.out


def test_a_pin_wins_outright(serve: Callable[..., Served]) -> None:
    port = free_port()
    ran = serve(SERVE, "--print-port", PORT=str(port))
    assert ran.rc == 0, ran.both
    assert ran.out.strip() == str(port)
    assert "pinned by PORT=" in ran.both


def test_the_window_is_clear_of_every_published_port() -> None:
    serve_text = SERVE.read_text()
    base = re.search(r"^SERVE_PORT_BASE=(\d+)", serve_text, re.M)
    span = re.search(r"^SERVE_PORT_SPAN=(\d+)", serve_text, re.M)
    if base is None or span is None:
        raise CouldNotLook("serve.sh no longer declares SERVE_PORT_BASE/SERVE_PORT_SPAN")
    low, width = int(base.group(1)), int(span.group(1))
    published: set[int] = set()
    for line in (ROOT / "compose.yaml").read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        parts = stripped[2:].strip().strip('"').strip("'").split(":")
        if len(parts) < 2:
            continue
        host = parts[-2]
        default = re.fullmatch(r"\$\{[A-Za-z0-9_]+:-(\d+)\}", host)
        if default:
            host = default.group(1)
        if host.isdigit():
            published.add(int(host))
    if not published:
        raise CouldNotLook("no published ports parsed out of compose.yaml — the reader is broken")
    assert (low, low + width - 1) == (20000, 29999)
    assert sorted(p for p in published if low <= p < low + width) == []


def test_a_taken_port_is_refused_loudly(
    serve: Callable[..., Served], hold: Callable[[int], None]
) -> None:
    port = free_port()
    hold(port)
    ran = serve(SERVE, PORT=str(port))
    assert ran.rc == 2, ran.both
    assert "REFUSES" in ran.both
    assert f"127.0.0.1:{port} is already listening" in ran.both
    assert str(os.getpid()) in ran.err or "no `lsof` on PATH" in ran.err, ran.err
    assert "Uvicorn running" not in ran.both


def test_the_belt_covers_the_derived_port_too(
    serve: Callable[..., Served], hold: Callable[[int], None]
) -> None:
    mine = serve(SERVE, "--print-port").out.strip()
    if not mine:
        raise CouldNotLook("this checkout's serve.sh printed no port")
    held_or_free(hold, int(mine))
    ran = serve(SERVE)
    assert ran.rc == 2, ran.both
    assert f"127.0.0.1:{mine} is already listening" in ran.both
    assert "derived from this checkout" in ran.both


def test_a_public_base_url_that_names_another_port_is_announced(
    serve: Callable[..., Served],
    checkout_copy: Callable[[str], Path],
    hold: Callable[[int], None],
) -> None:
    root = checkout_copy("delta")
    script = root / "scripts" / "serve.sh"
    (root / ".env").write_text("PUBLIC_BASE_URL=http://127.0.0.1:8000\n")
    port = serve(script, "--print-port").out.strip()
    if not port:
        raise CouldNotLook("the scratch checkout printed no port")
    held_or_free(hold, int(port))
    ran = serve(script)
    assert "PUBLIC_BASE_URL in .env says port 8000" in ran.both
    assert f"http://127.0.0.1:{port}" in ran.both
    (root / ".env").write_text(f"PUBLIC_BASE_URL=http://127.0.0.1:{port}\n")
    agreed = serve(script)
    assert "PUBLIC_BASE_URL in .env says port" not in agreed.err


def test_an_unknown_argument_is_exit_2(serve: Callable[..., Served]) -> None:
    ran = serve(SERVE, "--pirnt-port")
    assert ran.rc == 2, ran.both
    assert "unknown argument" in ran.both
    assert "Uvicorn running" not in ran.both


def test_a_missing_derivation_seam_is_exit_2(
    serve: Callable[..., Served], checkout_copy: Callable[[str], Path]
) -> None:
    root = checkout_copy("charlie")
    (root / "scripts" / "db.sh").unlink()
    ran = serve(root / "scripts" / "serve.sh", "--print-port")
    assert ran.rc == 2, ran.both
    assert "scripts/db.sh is missing or unreadable" in ran.both


def test_the_port_derivation_rides_db_sh_rather_than_copying_it() -> None:
    text = SERVE.read_text()
    assert "db_path_hash" in text and "db_checkout_root" in text
    assert not re.search(r"shasum|sha256sum|sha256_of|openssl dgst|cksum", text)
