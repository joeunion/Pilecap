"""`deploy/ship.sh` over a stub box: the fresh extract, the verification, the swap and the refusals.

does-not-cover: a real ssh — authentication, host keys, a connection dropped mid-transfer.
does-not-cover: permissions and ownership on the box; only that `deploy/.env` is not carried.
does-not-cover: whether the shipped tree runs — building and starting are the runbook's Part 4.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured

pytestmark = pytest.mark.drives(
    "deploy/ship.sh", "deploy/dns.sh", "scripts/db.sh", "scripts/tests/drive_preamble.sh"
)

ROOT = Path(__file__).resolve().parents[3]
SHIP = str(ROOT / "deploy" / "ship.sh")
FIXTURE_NS = "shipdrive"
GHOST = f"{FIXTURE_NS}/apps/ghost/apps.py"
DEST = "ec2-user@box.invalid"

SSH_STUB = """#!/usr/bin/env bash
while [ "$#" -gt 0 ]; do
    case "$1" in
    -i | -o | -p) shift 2 ;;
    -*) shift ;;
    *) break ;;
    esac
done
[ "$#" -gt 0 ] || { echo "stub ssh: no destination" >&2; exit 255; }
shift
printf '%s\\n' "$*" >>"$DJB_SHIP_SSH_LOG"
if [ "${DJB_SHIP_SSH_FAIL:-}" = "1" ]; then
    echo "stub ssh: the case asked ssh to fail" >&2
    exit 255
fi
cd "$DJB_SHIP_BOX_ROOT" || exit 255
bash -c "$*"
rc=$?
case "$*" in
*"tar -x"*)
    if [ -n "${DJB_SHIP_DELETE_AFTER:-}" ]; then rm -f "$DJB_SHIP_DELETE_AFTER"; fi
    if [ -n "${DJB_SHIP_ADD_AFTER:-}" ]; then
        mkdir -p "$(dirname "$DJB_SHIP_ADD_AFTER")"
        echo "a file the archive never carried" >"$DJB_SHIP_ADD_AFTER"
    fi
    ;;
esac
exit "$rc"
"""


def git(*args: str) -> str:
    """`git <args>` in this checkout; its stdout."""
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


@dataclass
class Box:
    """A scratch box root with a ghost app, a `deploy/.env`, a stale marker and a stub `ssh`."""

    base: Path
    capture: Callable[..., Captured]
    ref: str

    @property
    def root(self) -> Path:
        """The box's filesystem root, where the stub ssh runs every remote command."""
        return self.base / "root"

    @property
    def ssh_log(self) -> Path:
        """Every remote command the stub ssh received, one per line."""
        return self.base / "ssh.log"

    def env(self, **extra: str) -> dict[str, str]:
        """The environment a ship runs under: the stub first on PATH, the fixture namespace."""
        return {
            "PATH": f"{self.base / 'bin'}:{os.environ['PATH']}",
            "DJB_SHIP_SSH_LOG": str(self.ssh_log),
            "DJB_SHIP_BOX_ROOT": str(self.root),
            "DJB_DEPLOY_NAMESPACE": FIXTURE_NS,
            **extra,
        }

    def ship(self, *args: str, **extra: str) -> Captured:
        """`deploy/ship.sh <args>` against this box."""
        return self.capture([SHIP, *args], env=self.env(**extra))

    def ship_without_namespace(self, *args: str) -> Captured:
        """The same ship with `DJB_DEPLOY_NAMESPACE` removed, not emptied."""
        return self.capture(["env", "-u", "DJB_DEPLOY_NAMESPACE", SHIP, *args], env=self.env())

    def on(self, path: str) -> bool:
        """Whether `path` exists on the box."""
        return (self.root / path).exists()

    def files(self, path: str) -> int:
        """The count of non-directories under `path` on the box."""
        count = 0
        for top, dirs, names in os.walk(self.root / path):
            count += len(names) + sum(1 for d in dirs if os.path.islink(os.path.join(top, d)))
        return count

    def ssh_calls(self) -> int:
        """How many remote commands reached the stub."""
        return len(self.ssh_log.read_text().splitlines())


@pytest.fixture
def box(scratch: Path, capture: Callable[..., Captured]) -> Box:
    """A fresh planted box per case; the ref shipped is HEAD's committed tree."""
    if shutil.which("git") is None or shutil.which("tar") is None:
        raise CouldNotLook("no git or tar on PATH")
    if not Path(SHIP).is_file():
        raise CouldNotLook("deploy/ship.sh is not in this tree — there is nothing to drive")
    made = Box(scratch / "box", capture, git("rev-parse", "HEAD"))
    (made.base / "bin").mkdir(parents=True)
    (made.root / FIXTURE_NS / "apps" / "ghost").mkdir(parents=True)
    (made.root / FIXTURE_NS / "deploy").mkdir(parents=True)
    made.ssh_log.write_text("")
    (made.root / GHOST).write_text('class GhostConfig(AppConfig):\n    name = "apps.ghost"\n')
    (made.root / FIXTURE_NS / "deploy" / ".env").write_text(
        "SECRET_KEY='the box already had this'  # pragma: allowlist secret\n"
    )
    (made.root / FIXTURE_NS / "STALE-MARKER").write_text("stale\n")
    stub = made.base / "bin" / "ssh"
    stub.write_text(SSH_STUB)
    stub.chmod(0o755)
    return made


@pytest.fixture(scope="module")
def archive_count() -> int:
    """The file count of HEAD's archive with the TREE marker, as the ship lands it."""
    archive = subprocess.run(
        ["git", "archive", "--add-virtual-file=TREE:probe", git("rev-parse", "HEAD")],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as listing:
        return sum(1 for member in listing.getmembers() if not member.isdir())


def test_the_overlay_one_liner_leaves_the_survivor_behind(box: Box) -> None:
    assert box.on(GHOST)
    overlay = subprocess.run(  # noqa: S602 — the subject is deploy's shell one-liner; every value is this test's
        f"git archive --add-virtual-file=TREE:stub-tag {box.ref} | "
        f'(cd "$DJB_SHIP_BOX_ROOT" && mkdir -p {FIXTURE_NS} && tar -x -C {FIXTURE_NS})',
        shell=True,
        cwd=ROOT,
        env={**os.environ, **box.env()},
        executable="/bin/bash",
    )
    assert overlay.returncode == 0
    assert box.on(GHOST), "OVERLAY: a removed app's apps.py SURVIVES the re-ship"
    assert box.on(f"{FIXTURE_NS}/STALE-MARKER")
    assert box.on(f"{FIXTURE_NS}/TREE")


def test_the_sharp_case_a_removed_apps_py_does_not_survive_a_ship(box: Box) -> None:
    assert box.on(GHOST)
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    assert not box.on(GHOST)
    assert not box.on(f"{FIXTURE_NS}/apps/ghost")
    assert not box.on(f"{FIXTURE_NS}/STALE-MARKER")
    assert "SHIPPED" in ran.text()


def test_the_landed_file_set_is_exactly_the_archives(box: Box, archive_count: int) -> None:
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    assert box.files(FIXTURE_NS) == archive_count
    assert "no survivor, nothing missing" in ran.text()


def test_the_tree_marker_carries_the_laptops_own_image_tag(box: Box) -> None:
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    landed = (box.root / FIXTURE_NS / "TREE").read_text().strip()
    assert landed == "tree-" + git("rev-parse", "--short=12", f"{box.ref}^{{tree}}")


def test_the_deploy_env_is_not_carried_and_the_ship_says_why(box: Box) -> None:
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    assert not box.on(f"{FIXTURE_NS}/deploy/.env")
    assert box.on(f"{FIXTURE_NS}.previous/deploy/.env")
    assert "step 31" in ran.text()


def test_the_tree_it_replaced_is_kept_for_the_rollback(box: Box) -> None:
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    assert box.on(f"{FIXTURE_NS}.previous/apps/ghost/apps.py")
    assert not box.on(f"{FIXTURE_NS}.incoming")


def test_a_leftover_landing_from_a_failed_ship_is_cleared_not_overlaid(
    box: Box, archive_count: int
) -> None:
    incoming = box.root / f"{FIXTURE_NS}.incoming"
    (incoming / "apps" / "ghost").mkdir(parents=True)
    shutil.copy2(box.root / GHOST, incoming / "apps" / "ghost" / "apps.py")
    (incoming / "LEFTOVER").write_text("left over\n")
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    assert not box.on(GHOST)
    assert not box.on(f"{FIXTURE_NS}/LEFTOVER")
    assert box.files(FIXTURE_NS) == archive_count


def test_a_first_ship_onto_an_empty_box_works(box: Box) -> None:
    shutil.rmtree(box.root / FIXTURE_NS)
    ran = box.ship(DEST, "--ref", box.ref)
    assert ran.rc == 0, ran.text()
    assert box.on(f"{FIXTURE_NS}/TREE")
    assert not box.on(f"{FIXTURE_NS}.previous")


def test_a_survivor_the_verification_can_see_is_exit_one(box: Box) -> None:
    survivor = box.root / f"{FIXTURE_NS}.incoming" / "apps" / "ghost" / "apps.py"
    ran = box.ship(DEST, "--ref", box.ref, DJB_SHIP_ADD_AFTER=str(survivor))
    text = ran.text()
    assert ran.rc == 1, text
    for words in ("NOT the tree in the archive", "apps/ghost/apps.py", "discovery-derived"):
        assert words in text
    assert "NOTHING WAS SWAPPED" in text
    assert box.on(GHOST)
    assert not box.on(f"{FIXTURE_NS}.previous")


def test_a_missing_file_is_exit_one(box: Box) -> None:
    gone = box.root / f"{FIXTURE_NS}.incoming" / "TREE"
    ran = box.ship(DEST, "--ref", box.ref, DJB_SHIP_DELETE_AFTER=str(gone))
    text = ran.text()
    assert ran.rc == 1, text
    assert "NOT the tree in the archive" in text and "TREE" in text
    assert "NOTHING WAS SWAPPED" in text
    assert box.on(GHOST)


def test_a_box_that_cannot_be_read_is_exit_two(box: Box) -> None:
    ran = box.ship(DEST, "--ref", box.ref, DJB_SHIP_SSH_FAIL="1")
    assert ran.rc == 2, ran.text()
    assert box.on(GHOST)


def test_an_unknown_flag_is_refused(box: Box) -> None:
    ran = box.ship(DEST, "--overlay")
    assert ran.rc == 2, ran.text()
    assert "unknown argument" in ran.text()
    assert box.ssh_calls() == 0


def test_a_piped_stdout_is_refused(box: Box) -> None:
    ran = box.capture(
        ["bash", "-c", f"set -o pipefail; '{SHIP}' {DEST} --ref '{box.ref}' | cat"], env=box.env()
    )
    assert ran.rc == 2, ran.text()
    assert "refuses pipes" in ran.text()
    assert box.ssh_calls() == 0


def test_no_destination_is_refused(box: Box) -> None:
    ran = box.ship()
    assert ran.rc == 2, ran.text()
    assert "name the box" in ran.text()
    assert box.ssh_calls() == 0


def test_a_ref_that_names_no_tree_is_refused(box: Box) -> None:
    ran = box.ship(DEST, "--ref", "no-such-ref-anywhere")
    assert ran.rc == 2, ran.text()
    assert "does not name a tree" in ran.text()
    assert box.ssh_calls() == 0


def test_an_unset_namespace_is_refused(box: Box) -> None:
    ran = box.ship_without_namespace(DEST, "--ref", box.ref)
    assert ran.rc == 2, ran.text()
    assert "DJB_DEPLOY_NAMESPACE" in ran.text()
    assert box.ssh_calls() == 0
    assert box.on(GHOST)


def test_the_landing_is_composed_from_the_namespace(box: Box) -> None:
    first = box.ship(DEST, "--ref", box.ref, "--dry-run")
    assert first.rc == 0, first.text()
    assert f"landing      {FIXTURE_NS}  (staged in {FIXTURE_NS}.incoming" in first.text()
    assert f"{FIXTURE_NS}.previous" in first.text()
    second = box.ship(DEST, "--ref", box.ref, "--dry-run", DJB_DEPLOY_NAMESPACE="otherdrive")
    assert second.rc == 0, second.text()
    assert "landing      otherdrive  (staged in otherdrive.incoming" in second.text()
    assert "otherdrive.previous" in second.text()
    assert box.ssh_calls() == 0


def test_an_explicit_dest_outranks_the_namespace(box: Box) -> None:
    ran = box.ship_without_namespace(DEST, "--ref", box.ref, "--dest", "namedbyhand", "--dry-run")
    assert ran.rc == 0, ran.text()
    assert "landing      namedbyhand" in ran.text()


def test_dry_run_touches_nothing(box: Box) -> None:
    ran = box.ship(DEST, "--ref", box.ref, "--dry-run")
    assert ran.rc == 0, ran.text()
    assert "DRY RUN" in ran.text() and "nothing was touched." in ran.text()
    assert box.ssh_calls() == 0
    assert box.on(GHOST)


def test_the_ship_is_re_runnable(box: Box, archive_count: int) -> None:
    for _ in range(2):
        ran = box.ship(DEST, "--ref", box.ref)
        assert ran.rc == 0, ran.text()
    assert box.files(FIXTURE_NS) == archive_count
    assert box.files(f"{FIXTURE_NS}.previous") == archive_count
