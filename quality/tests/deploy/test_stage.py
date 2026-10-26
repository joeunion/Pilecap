"""`deploy/stage.sh` over stub boxes: every act keyed on its own input, and prod's gate.

does-not-cover: the real box — pull, migrate and the prober are one timed run on the stage box.
does-not-cover: what the acts do; the stub ssh records a line and answers a code the case chose.
does-not-cover: the file itself — a copy runs; the script derives its siblings from its dir.
does-not-cover: the registry's own answer; `image-digest` is a knob, asserted as a branch only.
does-not-cover: a migration whose leaf did not move but whose bytes did.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.deploy_scaffold import DeployScaffold

pytestmark = pytest.mark.drives(
    "deploy/stage.sh",
    "deploy/lib.sh",
    "deploy/tests/scaffold.sh",
    "deploy/release.sh",
    "deploy/ship.sh",
    "deploy/provision.sh",
    "quality/djb/scope.py",
    "scripts/gate_refuse.sh",
    "quality/djb/ledger.py",
    "deploy/observability",
)

STAGING_DEST = "ec2-user@staging.invalid"
BOX = "ec2-user@box.invalid"
PROD = "ec2-user@prod.invalid"
DIGEST_A = "sha256:" + "1" * 64
DIGEST_B = "sha256:" + "2" * 64
DIGEST_C = "sha256:" + "3" * 64
DIGESTS = f"digest web {DIGEST_A}\ndigest worker {DIGEST_B}\ndigest frontend {DIGEST_C}\n"
REGISTRY = "000000000000.dkr.ecr.us-east-1.amazonaws.com/drivens"
SANCTION_OK = "release-captain: promote the migration staging has served since this morning"
COPIED = ("scripts/gate_refuse.sh",)
#: What `nightly-read` and the `classify` verb import: this checkout's, linked.
LEDGER_LINKS = ("quality", "apps/core/roads.py")

# `image-tag` is derived from git as the real one is; the two image arms answer from knobs.
PROVISION_STUB = """#!/usr/bin/env bash
here="$(cd -- "$(dirname -- "$0")" && pwd)"
service="${2:-}"
upper="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
case "${1:-}" in
image-services) echo "web worker frontend" ;;
image-tag)
    printf 'tree-%s\\n' "$(cd "$here/.." && git rev-parse --short=12 'HEAD^{tree}')"
    ;;
image-repo)
    printf '%s/djb-%s\\n' "${DJB_DRIVE_REGISTRY:?}" "$service"
    ;;
image-digest)
    eval "answer=\\${DJB_DRIVE_DIGEST_${upper}:-}"
    if [ -z "$answer" ]; then
        echo "stub provision: the registry has no djb-${service} at that tag" >&2
        exit 2
    fi
    printf '%s\\n' "$answer"
    ;;
*) echo "stub provision: unexpected $*" >&2; exit 2 ;;
esac
"""

SHIP_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >>"$DJB_DRIVE_SHIP_LOG"
echo "stub ship: shipped"
exit "${DJB_DRIVE_SHIP_RC:-0}"
"""

# Two boxes, two logs: the staging box answering anything but its two reads is exit 97.
SSH_STUB = r"""#!/usr/bin/env bash
cmd="${!#}"
dest="${@: -2:1}"
if [ -n "${DJB_DRIVE_STAGING_DEST:-}" ] && [ "$dest" = "$DJB_DRIVE_STAGING_DEST" ]; then
    printf '%s\n' "$cmd" >>"$DJB_DRIVE_STAGING_SSH_LOG"
    case "$cmd" in
    cat*TREE*)
        if [ -s "$DJB_DRIVE_STAGING_TREE" ]; then
            cat "$DJB_DRIVE_STAGING_TREE"
        else
            echo "cat: no such file or directory" >&2
            exit 1
        fi
        ;;
    cat*LIVE*)
        if [ -s "$DJB_DRIVE_STAGING_LIVE" ]; then
            cat "$DJB_DRIVE_STAGING_LIVE"
        else
            echo "cat: no such file or directory" >&2
            exit 1
        fi
        ;;
    *readyz-prober*)
        printf '%s' "${DJB_DRIVE_STAGING_READYZ_CODE:-200}"
        exit "${DJB_DRIVE_STAGING_READYZ_RC:-0}"
        ;;
    *) echo "stub ssh: the STAGING box was asked to act: $cmd" >&2; exit 97 ;;
    esac
    exit 0
fi
printf '%s\n' "$cmd" >>"$DJB_DRIVE_SSH_LOG"
case "$cmd" in
cat*TREE*)
    if [ -s "$DJB_DRIVE_BOX_TREE" ]; then
        cat "$DJB_DRIVE_BOX_TREE"
    else
        echo "cat: no such file or directory" >&2
        exit 1
    fi
    ;;
rm\ -f*LIVE*) rm -f "$DJB_DRIVE_BOX_LIVE"; exit "${DJB_DRIVE_LIVE_RM_RC:-0}" ;;
echo\ \'live\ *LIVE*)
    line="${cmd#echo \'}"
    printf '%s\n' "${line%%\'*}" >"$DJB_DRIVE_BOX_LIVE"
    exit "${DJB_DRIVE_LIVE_RC:-0}"
    ;;
*secrets-fetch*) exit "${DJB_DRIVE_SECRETS_RC:-0}" ;;
*"docker login"*) exit "${DJB_DRIVE_LOGIN_RC:-0}" ;;
*provision.sh\ up*) exit "${DJB_DRIVE_UP_RC:-0}" ;;
*release.sh*)
    printf '%s\n' "${DJB_DRIVE_RELEASE_OUT-release: migrate: 7s}"
    exit "${DJB_DRIVE_RELEASE_RC:-0}"
    ;;
*readyz-prober*) printf '%s' "${DJB_DRIVE_READYZ_CODE:-200}"; exit "${DJB_DRIVE_READYZ_RC:-0}" ;;
*) echo "stub ssh: unexpected remote command: $cmd" >&2; exit 97 ;;
esac
"""

STAGING_ONLY_READ = re.compile(r"^cat .*/(TREE|LIVE)'$|readyz-prober")


def git(repo: Path, *args: str) -> str:
    """`git <args>` in the case repo; its stdout, stripped."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise CouldNotLook(f"git {' '.join(args)} failed in {repo}: {done.stderr}")
    return done.stdout.strip()


def filled(path: Path) -> list[str]:
    """The non-empty lines of `path`."""
    return [line for line in path.read_text().splitlines() if line]


@dataclass
class World:
    """One case's throwaway checkout, its stub box, staging box and registry, and their logs."""

    case: Path
    capture: Callable[..., Captured]
    box_tag: str = ""

    @property
    def repo(self) -> Path:
        """The scratch checkout the copy of `stage.sh` stages."""
        return self.case / "repo"

    @property
    def ssh_log(self) -> Path:
        """Every remote command the box under deploy received."""
        return self.case / "ssh.log"

    @property
    def ship_log(self) -> Path:
        """Every `ship.sh` invocation."""
        return self.case / "ship.log"

    @property
    def staging_log(self) -> Path:
        """Every remote command the staging box received."""
        return self.case / "staging-ssh.log"

    @property
    def nightly(self) -> Path:
        """Where a downloaded leak-proof artifact lands."""
        return self.case / "nightly"

    def tag(self) -> str:
        """The tree tag of the case repo's HEAD."""
        return "tree-" + git(self.repo, "rev-parse", "--short=12", "HEAD^{tree}")

    def plant(self, relative: str, text: str, message: str) -> None:
        """Write `relative` and commit it."""
        (self.repo / relative).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", message)

    def base_env(self) -> dict[str, str | None]:
        """The knobs every ordinary stage runs under."""
        return {
            "PATH": f"{self.case / 'bin'}:{os.environ['PATH']}",
            "DJB_DRIVE_SSH_LOG": str(self.ssh_log),
            "DJB_DRIVE_SHIP_LOG": str(self.ship_log),
            "DJB_DRIVE_BOX_TREE": str(self.case / "box" / "TREE"),
            "DJB_DRIVE_REGISTRY": REGISTRY,
            "DJB_DRIVE_DIGEST_WEB": DIGEST_A,
            "DJB_DRIVE_DIGEST_WORKER": DIGEST_B,
            "DJB_DRIVE_DIGEST_FRONTEND": DIGEST_C,
            "DJB_DRIVE_STAGING_DEST": STAGING_DEST,
            "DJB_DRIVE_STAGING_SSH_LOG": str(self.staging_log),
            "DJB_DRIVE_STAGING_TREE": str(self.case / "staging" / "TREE"),
            "DJB_DRIVE_STAGING_LIVE": str(self.case / "staging" / "LIVE"),
            "DJB_DRIVE_BOX_LIVE": str(self.case / "box" / "LIVE"),
            "DJB_DRIVE_UP_RC": "0",
            "DJB_DRIVE_STAGING_READYZ_CODE": "200",
            "DJB_DRIVE_RELEASE_OUT": "release: migrate: 7s",
            "DJB_DEPLOY_NAMESPACE": "drivens",
        }

    def stage(self, *args: str, **knobs: str | None) -> Captured:
        """The copy of `stage.sh <args>` from the repo; a knob of `None` is left unset."""
        merged = {**self.base_env(), **knobs}
        env = {k: v for k, v in merged.items() if v is not None}
        drop = [arg for k, v in merged.items() if v is None for arg in ("-u", k)]
        return self.capture(["env", *drop, "./deploy/stage.sh", *args], cwd=self.repo, env=env)

    def asked(self) -> list[str]:
        """The box's remote commands, in order."""
        return filled(self.ssh_log)

    def asked_line(self, needle: str, last: bool = False) -> int | None:
        """The 1-based line of the first (or last) remote command carrying `needle`."""
        found = [n for n, line in enumerate(self.asked(), start=1) if needle in line]
        return (found[-1] if last else found[0]) if found else None

    def ships(self) -> int:
        """How many times `ship.sh` was called."""
        return len(filled(self.ship_log))

    def reset_logs(self) -> None:
        """Empty the box's and the ship's logs between two stages of one world."""
        self.ssh_log.write_text("")
        self.ship_log.write_text("")

    def staging_holds_this_tree(self) -> None:
        """Staging holds HEAD's tree, released, and proved it live."""
        tag = self.tag()
        (self.case / "staging" / "TREE").write_text(f"{tag}\n{DIGESTS}")
        (self.case / "staging" / "LIVE").write_text(f"live {tag} 20260927T120000Z\n")

    def declare_product(self, checkout: Path) -> None:
        """The linked `quality/` becomes the checkout's entries plus a drawer naming a namespace."""
        quality = self.repo / "quality"
        quality.unlink()
        quality.mkdir()
        for entry in (checkout / "quality").iterdir():
            if entry.name != "local":
                (quality / entry.name).symlink_to(entry)
        (quality / "local").mkdir()
        (quality / "local" / "rules.yaml").write_text("rule_id_namespace: zzzstage\n")

    def nightly_artifact(self, ago: int, rc: int) -> None:
        """A downloaded `nightly-leak-proof` record, `ago` seconds old, exiting `rc`."""
        at = (datetime.now(UTC) - timedelta(seconds=ago)).strftime("%Y%m%dT%H%M%SZ")
        self.nightly.mkdir(exist_ok=True)
        (self.nightly / "leak_proof.txt").write_text(
            f"schema=leak-proof/1 at={at} commit={'c' * 40} tree={'e' * 40} seed=4242 "
            f"pass1=ok pass2=ok map=written rc={rc} run=7 attempt=1 where=nightly\n"
        )


def build(case: Path, scaffold: DeployScaffold, capture: Callable[..., Captured]) -> World:
    """A world whose box holds the base tree pinned at digests A and B."""
    world = World(case, capture)
    repo = scaffold.into(case / "repo", "deploy/stage.sh", *COPIED)
    for directory in ("deploy/observability/alerts", "apps/core/migrations"):
        (repo / directory).mkdir(parents=True, exist_ok=True)
    for directory in ("bin", "box", "staging"):
        (case / directory).mkdir()
    for empty in (world.ssh_log, world.ship_log, world.staging_log):
        empty.write_text("")
    for marker in ("staging/TREE", "staging/LIVE", "box/TREE"):
        (case / marker).write_text("")
    for path, body in (
        (repo / "deploy" / "provision.sh", PROVISION_STUB),
        (repo / "deploy" / "ship.sh", SHIP_STUB),
        (case / "bin" / "ssh", SSH_STUB),
    ):
        path.write_text(body)
        path.chmod(0o755)
    (repo / "deploy" / "stage.sh").chmod(0o755)
    for relative, text in (
        ("apps/core/migrations/0001_initial.py", "first\n"),
        ("deploy/observability/alerts/apply.py", "route\n"),
        ("README.md", "readme\n"),
        ("notes.md", "note\n"),
        ("apps/core/services.py", "code\n"),
    ):
        (repo / relative).write_text(text)
    git(repo, "init", "-q")
    for link in LEDGER_LINKS:
        (repo / link).symlink_to(scaffold.checkout / link)
    # Invariant: the links are excluded, so the tree tag is the world's own bytes.
    (repo / ".git" / "info" / "exclude").write_text(
        "".join(f"/{link}\n" for link in LEDGER_LINKS) + "__pycache__/\n"
    )
    git(repo, "config", "user.email", "drive@drive.invalid")
    git(repo, "config", "user.name", "stage drive")
    git(repo, "add", "-A")
    git(repo, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "base")
    world.box_tag = world.tag()
    (case / "box" / "TREE").write_text(f"{world.box_tag}\n{DIGESTS}")
    return world


@pytest.fixture
def fresh(
    scratch: Path, capture: Callable[..., Captured], deploy_scaffold: DeployScaffold
) -> Callable[[], World]:
    """`fresh()` builds the next world, so no case reads a log another world wrote."""
    root = deploy_scaffold.checkout
    for needed in ("deploy/stage.sh", *COPIED):
        if not (root / needed).is_file():
            raise CouldNotLook(
                f"{needed} is not in this tree — the drive copies it, never models it"
            )
    made = 0

    def next_world() -> World:
        nonlocal made
        made += 1
        return build(scratch.resolve() / f"case{made}", deploy_scaffold, capture)

    return next_world


def act(run: Captured, step: str, name: str, rest: str) -> None:
    """The act line is one sentence: its state and the input it names."""
    line = f"stage: [{step}] {name} — {rest}"
    assert line in run.text(), f"does not print {line!r}"


def closes(run: Captured, tag: str, migrate: str) -> None:
    """The last line is `stage: <tag> live in <n>s (migrate <m>)`."""
    last = run.text().splitlines()[-1]
    pattern = rf"stage: {re.escape(tag)} live in [0-9]+s \(migrate {re.escape(migrate)}\)"
    assert re.fullmatch(pattern, last), last


def prod_untouched(world: World) -> None:
    """The prod box saw nothing, the ship never ran, staging was only read."""
    assert world.asked() == []
    assert world.ships() == 0
    acted = [line for line in world.staging_log.read_text().splitlines()]
    assert all(STAGING_ONLY_READ.search(line) for line in acted), acted


def prod_world(fresh: Callable[[], World]) -> World:
    """A migration to promote, staging holding this tree at 200, a green nightly an hour old."""
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    world.staging_holds_this_tree()
    world.nightly_artifact(3600, 0)
    return world


def prod_args(world: World, *more: str) -> tuple[str, ...]:
    """`--env prod` with the sanction, the staging box and the nightly, then `more`."""
    return (
        PROD, "--env", "prod", "--sanction", SANCTION_OK,
        "--staging", STAGING_DEST, "--nightly", str(world.nightly), *more,
    )  # fmt: skip


def test_each_act_is_keyed_on_its_own_input(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    act(run, "5/6", "release", "ran: migrate+grants (a migration leaf moved)")
    assert "--without-alerts" in run.text()
    assert world.ships() == 1
    assert world.asked_line("release.sh --without-alerts")
    assert world.asked_line("readyz-prober")

    world = fresh()
    world.plant("deploy/observability/alerts/apply.py", "route v2\n", "an alert route")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    act(run, "5/6", "release", "ran: alerts (deploy/observability/ moved)")
    assert "--without-alerts" not in run.text()
    assert world.asked_line("readyz-prober")

    world = fresh()
    run = world.stage(BOX, "--env", "staging", DJB_DRIVE_DIGEST_WEB="sha256:" + "3" * 64)
    assert run.rc == 0, run.text()
    act(run, "1/6", "ship", f"skipped: the tree tag ({world.box_tag}) unchanged")
    act(
        run, "2/6", "secrets",
        "skipped: the tree on the box (no ship, so its deploy/.env is still there) unchanged",
    )  # fmt: skip
    act(run, "5/6", "release", "ran: recreate (the web image digest moved)")
    assert world.ships() == 0
    assert world.asked_line("provision.sh up")
    assert not world.asked_line("secrets-fetch")

    world = fresh()
    world.plant("apps/core/services.py", "code v2\n", "ordinary code")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    act(run, "1/6", "ship", f"ran: {world.box_tag} → {world.tag()}")
    act(
        run, "5/6", "release",
        "skipped: the migration leaves, deploy/observability/ and both image digests unchanged",
    )  # fmt: skip
    assert world.ships() == 1
    assert world.asked_line("secrets-fetch")
    assert world.asked_line("provision.sh up")
    assert not world.asked_line("release.sh")
    assert world.asked_line("readyz-prober")


def test_a_docs_only_tree_deploys_nothing(fresh: Callable[[], World]) -> None:
    world = fresh()
    (world.repo / "notes.md").write_text("note v2\n")
    world.plant("README.md", "readme v2\n", "docs only")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    assert "nothing to deploy — docs-only delta (2 path(s))" in run.text()
    assert "[1/6]" not in run.text()
    asked = world.asked()
    assert len(asked) == 1 and "TREE" in asked[0], asked
    assert world.ships() == 0


def test_an_unknown_box_state_acts_nothing(fresh: Callable[[], World]) -> None:
    world = fresh()
    (world.case / "box" / "TREE").write_text("")
    world.plant("apps/core/services.py", "code v2\n", "ordinary code")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 2, run.text()
    assert "!! stage: the box cannot say which tree it holds — ship first" in run.text()
    assert "Nothing was staged; no act ran." in run.text()
    assert world.ships() == 0
    assert len(world.asked()) == 1

    world = fresh()
    world.plant("apps/core/services.py", "code v2\n", "ordinary code")
    run = world.stage(BOX, "--env", "staging", DJB_DRIVE_DIGEST_WEB="")
    assert run.rc == 2, run.text()
    for needle in (
        "the registry does not have this tree's web image",
        "THE BOX DOES NOT BUILD (ADR deploy-4).",
        "THE BANK'S IMAGE STEP did",
        "this box is pointed at the wrong registry.",
        "CI's images job is the fallback",
        "Nothing was staged; no act ran.",
    ):
        assert needle in run.text(), needle
    assert world.ships() == 0


def test_a_second_stage_of_one_tree_is_readyz_only(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    first = world.stage(BOX, "--env", "staging")
    assert first.rc == 0, first.text()
    (world.case / "box" / "TREE").write_text(f"{world.tag()}\n{DIGESTS}")
    world.reset_logs()
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    act(run, "1/6", "ship", f"skipped: the tree tag ({world.tag()}) unchanged")
    act(
        run, "5/6", "release",
        "skipped: the migration leaves, deploy/observability/ and both image digests unchanged",
    )  # fmt: skip
    act(run, "6/6", "readyz", "ran: HTTP 200")
    assert world.ships() == 0
    assert not world.asked_line("release.sh")
    assert not world.asked_line("provision.sh up")
    assert world.asked_line("readyz-prober")


def test_the_registry_coordinate_is_derived_and_carried(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    assert f"registry     {REGISTRY}" in run.text()
    assert world.asked_line(f"DJB_IMAGE_REGISTRY='{REGISTRY}' ./deploy/provision.sh up")
    assert world.asked_line(f"DJB_IMAGE_REGISTRY='{REGISTRY}' ./deploy/release.sh")
    login, up = world.asked_line("docker login"), world.asked_line("provision.sh up")
    assert login is not None and up is not None and login < up, (login, up)
    assert "(ECR, region us-east-1)" in run.text()
    assert world.asked_line("aws ecr get-login-password --region 'us-east-1'")


def test_a_failed_act_stops_the_sequence_naming_itself(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(
        BOX, "--env", "staging",
        DJB_DRIVE_UP_RC="3", DJB_DRIVE_STAGING_DEST=None, DJB_DRIVE_STAGING_SSH_LOG=None,
        DJB_DRIVE_STAGING_TREE=None, DJB_DRIVE_STAGING_LIVE=None,
        DJB_DRIVE_STAGING_READYZ_CODE=None, DJB_DRIVE_RELEASE_OUT=None,
    )  # fmt: skip
    assert run.rc == 1, run.text()
    assert "RED: stage: STOPPED at act 4/6 — up (exit 3)." in run.text()
    assert "No act after this one ran." in run.text()
    assert not world.asked_line("release.sh")
    assert not world.asked_line("readyz-prober")


def test_it_refuses_a_piped_stdout_and_an_unknown_flag(
    fresh: Callable[[], World], capture: Callable[..., Captured]
) -> None:
    world = fresh()
    piped = capture(
        ["bash", "-c", f"./deploy/stage.sh {BOX} --env staging | cat"],
        cwd=world.repo,
        env={
            "PATH": f"{world.case / 'bin'}:{os.environ['PATH']}",
            "DJB_DEPLOY_NAMESPACE": "drivens",
            "CI": "",
        },
    )
    assert "!! stage refuses pipes" in piped.text()
    assert "stage: [1/6]" not in piped.text()

    for args, rc, needle in (
        ((BOX, "--env", "staging", "--force"), 2, "!! stage: unknown argument '--force'."),
        (("--env", "staging"), 2, "!! stage: no destination"),
        ((BOX,), 2, "no environment named"),
    ):
        run = world.stage(*args)
        assert run.rc == rc, run.text()
        assert needle in run.text()


def test_a_dry_run_reads_the_box_and_touches_nothing(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(BOX, "--env", "staging", "--dry-run")
    assert run.rc == 0, run.text()
    assert "WOULD RUN" in run.text()
    assert "DRY RUN — the box's TREE marker was read and nothing was touched." in run.text()
    assert " — ran" not in run.text()
    assert world.ships() == 0
    asked = world.asked()
    assert len(asked) == 1 and "TREE" in asked[0], asked


def test_the_docs_only_classes_are_the_classifiers_and_not_a_list(
    fresh: Callable[[], World],
) -> None:
    world = fresh()
    world.plant(
        "deploy/observability/alerts/apply.py",
        "route v2\n",
        "an alert route, which is inert to the classifier",
    )
    shape = subprocess.run(
        [
            "python3", "-E", "-S", "-m", "quality.djb.scope", "classify",
            "deploy/observability/alerts/apply.py",
        ],
        cwd=world.repo, capture_output=True, text=True,
    ).stdout.strip()  # fmt: skip
    assert shape == "inert", f"the classifier calls deploy/observability/ {shape!r}"
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    assert "nothing to deploy" not in run.text()
    act(run, "5/6", "release", "ran: alerts (deploy/observability/ moved)")


def test_the_closing_line_carries_both_walls(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(BOX, "--env", "staging", DJB_DRIVE_RELEASE_OUT="release: migrate: 42s")
    assert run.rc == 0, run.text()
    closes(run, world.tag(), "42s")

    world = fresh()
    world.plant("apps/core/services.py", "code v2\n", "ordinary code")
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    closes(run, world.tag(), "skipped")

    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(BOX, "--env", "staging", DJB_DRIVE_RELEASE_OUT="")
    assert run.rc == 0, run.text()
    closes(run, world.tag(), "unmeasured")


BAD_SANCTIONS = {
    "newline_in_reason": ("release-captain: promote\nand something else", "control character"),
    "newline_in_who": ("release\ncaptain: promote the staged tree", "control character"),
    "tab_in_reason": ("release-captain: promote\tthe staged tree", "control character"),
    "blank_reason": ("release-captain:    ", "is not '<who>: <why>'"),
    "blank_who": ("   : promote the staged tree", "is not '<who>: <why>'"),
}


def test_prod_refuses_without_a_sanction(fresh: Callable[[], World]) -> None:
    for spelling in ("prod", "PROD", "Production", "prod-eu"):
        world = prod_world(fresh)
        run = world.stage(PROD, "--env", spelling)
        assert run.rc == 2, run.text()
        assert "!! stage: REFUSED — a promotion to prod" in run.text()
        assert "no sanction" in run.text()
        prod_untouched(world)

    world = prod_world(fresh)
    run = world.stage(
        PROD, "--env", "prod", "--staging", STAGING_DEST, "--nightly", str(world.nightly)
    )
    assert run.rc == 2, run.text()
    assert "no sanction" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    run = world.stage(
        PROD, "--env", "prod", "--sanction", "ship it",
        "--staging", STAGING_DEST, "--nightly", str(world.nightly),
    )  # fmt: skip
    assert run.rc == 2, run.text()
    assert "the sanction 'ship it' is not '<who>: <why>'" in run.text()
    prod_untouched(world)

    for label, (sanction, needle) in BAD_SANCTIONS.items():
        world = prod_world(fresh)
        run = world.stage(
            PROD, "--env", "prod", "--sanction", sanction,
            "--staging", STAGING_DEST, "--nightly", str(world.nightly),
        )  # fmt: skip
        assert run.rc == 2, (label, run.text())
        expected = "the sanction carries a control character" if "control" in needle else needle
        assert expected in run.text(), label
        prod_untouched(world)


def test_prod_refuses_when_staging_is_not_this_tree(fresh: Callable[[], World]) -> None:
    world = prod_world(fresh)
    staged = (world.case / "staging" / "TREE").read_text().splitlines()[0]
    world.plant("apps/core/services.py", "code v2\n", "a tree staging never saw")
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert f"staging holds {staged}, and this tree is {world.tag()}" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    (world.case / "staging" / "TREE").write_text("")
    (world.case / "staging" / "LIVE").write_text("")
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "staging cannot say which tree it holds" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    run = world.stage(
        PROD, "--env", "prod", "--sanction", SANCTION_OK, "--nightly", str(world.nightly)
    )
    assert run.rc == 2, run.text()
    assert "no staging box named" in run.text()
    prod_untouched(world)


def test_prod_refuses_when_staging_does_not_answer(fresh: Callable[[], World]) -> None:
    world = prod_world(fresh)
    run = world.stage(*prod_args(world), DJB_DRIVE_STAGING_READYZ_CODE="503")
    assert run.rc == 2, run.text()
    assert "staging's readyz answered '503', not 200" in run.text()
    prod_untouched(world)


def test_prod_refuses_every_nightly_that_is_not_green_and_fresh(
    fresh: Callable[[], World],
) -> None:
    world = prod_world(fresh)
    world.nightly_artifact(3600, 1)
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "the nightly leak proof is RED (rc=1)" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    world.nightly_artifact(2 * 86400, 0)
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "the nightly leak proof is older than 24 h" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    run = world.stage(PROD, "--env", "prod", "--sanction", SANCTION_OK, "--staging", STAGING_DEST)
    assert run.rc == 2, run.text()
    assert "there is no nightly leak proof (nightly:none)" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    (world.nightly / "leak_proof.txt").unlink()
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "the nightly leak proof is unreadable" in run.text()
    assert "holds no leak_proof.txt" in run.text()
    prod_untouched(world)


def test_prod_names_every_red_precondition_at_once(fresh: Callable[[], World]) -> None:
    world = prod_world(fresh)
    (world.case / "staging" / "TREE").write_text("")
    (world.case / "staging" / "LIVE").write_text("")
    run = world.stage(
        PROD, "--env", "prod", "--staging", STAGING_DEST, DJB_DRIVE_STAGING_READYZ_CODE="502"
    )
    assert run.rc == 2, run.text()
    for needle in (
        "no sanction",
        "staging cannot say which tree it holds",
        "staging's readyz answered '502', not 200",
        "there is no nightly leak proof (nightly:none)",
        "4 of 4 preconditions are red",
    ):
        assert needle in run.text(), needle
    prod_untouched(world)


def test_prod_proceeds_when_all_four_are_green(fresh: Callable[[], World]) -> None:
    world = prod_world(fresh)
    tag = world.tag()
    run = world.stage(*prod_args(world))
    assert run.rc == 0, run.text()
    assert f"stage: prod gate  sanction  {SANCTION_OK}" in run.text()
    assert f"stage: prod gate  staging   {tag} on {STAGING_DEST}, readyz 200" in run.text()
    assert "stage: prod gate  nightly   nightly:" in run.text()
    act(run, "5/6", "release", "ran: migrate+grants (a migration leaf moved)")
    assert world.asked_line("release.sh")
    assert world.ships() == 1
    closes(run, tag, "7s")


def test_a_product_tree_promotes_without_the_platforms_nightly(
    fresh: Callable[[], World], deploy_scaffold: DeployScaffold
) -> None:
    world = prod_world(fresh)
    world.declare_product(deploy_scaffold.checkout)
    tag = world.tag()
    run = world.stage(PROD, "--env", "prod", "--sanction", SANCTION_OK, "--staging", STAGING_DEST)
    assert run.rc == 0, run.text()
    assert "nightly:none" not in run.text()
    assert (
        "stage: prod gate  nightly   a product tree — the platform's nightly leak proof is the"
        " template's; the product's own gate is its proof (staging proved"
        f" {tag} on {STAGING_DEST}, readyz 200)"
    ) in run.text()
    assert world.ships() == 1

    world = prod_world(fresh)
    world.declare_product(deploy_scaffold.checkout)
    world.nightly_artifact(3600, 1)
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "the nightly leak proof is RED (rc=1)" in run.text()
    prod_untouched(world)


def test_prod_reads_what_staging_proved_not_what_it_shipped(fresh: Callable[[], World]) -> None:
    world = prod_world(fresh)
    (world.case / "staging" / "LIVE").write_text("")
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "staging cannot say which tree it holds live" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    older = world.box_tag
    (world.case / "staging" / "LIVE").write_text(f"live {older} 20260927T100000Z\n")
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert f"staging holds {older}, and this tree is {world.tag()}" in run.text()
    prod_untouched(world)

    world = prod_world(fresh)
    (world.case / "staging" / "LIVE").write_text("garbage\n")
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "staging cannot say which tree it holds live" in run.text()
    prod_untouched(world)


def test_a_stage_withdraws_live_before_acting_and_writes_it_after_readyz(
    fresh: Callable[[], World],
) -> None:
    world = fresh()
    live = world.case / "box" / "LIVE"
    live.write_text(f"live {world.box_tag} 20260927T090000Z\n")
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    mine = world.tag()
    run = world.stage(BOX, "--env", "staging", DJB_DRIVE_UP_RC="3")
    assert run.rc == 1, run.text()
    assert "RED: stage: STOPPED at act 4/6 — up (exit 3)." in run.text()
    assert world.asked_line("rm -f 'drivens/LIVE'")
    assert not live.exists(), live.read_text()
    withdrawn, first_act = (
        world.asked_line("rm -f 'drivens/LIVE'"),
        world.asked_line("secrets-fetch"),
    )
    assert withdrawn is not None and first_act is not None and withdrawn < first_act
    assert world.ships() == 1
    (world.case / "staging" / "TREE").write_text(f"{mine}\n")
    (world.case / "staging" / "LIVE").write_text("")
    world.nightly_artifact(3600, 0)
    world.reset_logs()
    run = world.stage(*prod_args(world))
    assert run.rc == 2, run.text()
    assert "staging cannot say which tree it holds live" in run.text()
    prod_untouched(world)

    world = fresh()
    live = world.case / "box" / "LIVE"
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    mine = world.tag()
    run = world.stage(BOX, "--env", "staging")
    assert run.rc == 0, run.text()
    assert live.is_file() and re.fullmatch(
        rf"live {mine} [0-9]{{8}}T[0-9]{{6}}Z\n", live.read_text()
    )
    written = next(
        (n for n, line in enumerate(world.asked(), start=1) if line.startswith("echo 'live ")), None
    )
    readyz = world.asked_line("readyz-prober", last=True)
    assert written is not None and readyz is not None and written > readyz, (written, readyz)
    world.staging_holds_this_tree()
    (world.case / "staging" / "LIVE").write_text(live.read_text())
    world.nightly_artifact(3600, 0)
    world.reset_logs()
    run = world.stage(*prod_args(world))
    assert run.rc == 0, run.text()
    assert f"stage: prod gate  staging   {mine} on {STAGING_DEST}, readyz 200" in run.text()

    world = fresh()
    world.plant("apps/core/migrations/0002_more.py", "second\n", "a migration")
    run = world.stage(
        BOX, "--env", "staging",
        DJB_DRIVE_READYZ_CODE="503", DJB_DRIVE_STAGING_DEST=None, DJB_DRIVE_STAGING_SSH_LOG=None,
        DJB_DRIVE_STAGING_TREE=None, DJB_DRIVE_STAGING_LIVE=None, DJB_DRIVE_UP_RC=None,
        DJB_DRIVE_STAGING_READYZ_CODE=None, DJB_DRIVE_RELEASE_OUT=None,
    )  # fmt: skip
    assert run.rc == 1, run.text()
    assert not (world.case / "box" / "LIVE").exists()


def test_prod_refuses_a_tree_the_registry_does_not_hold(fresh: Callable[[], World]) -> None:
    world = prod_world(fresh)
    run = world.stage(*prod_args(world), DJB_DRIVE_DIGEST_WEB="")
    assert run.rc == 2, run.text()
    assert f"stage: prod gate  sanction  {SANCTION_OK}" in run.text()
    assert "!! stage: REFUSED — the registry does not have this tree's web image" in run.text()
    assert world.ships() == 0
    asked = world.asked()
    assert len(asked) == 1 and re.search(r"^cat .*/TREE'$", asked[0]), asked


def test_the_prod_flags_mean_nothing_outside_prod(fresh: Callable[[], World]) -> None:
    world = fresh()
    world.plant("apps/core/services.py", "code v2\n", "ordinary code")
    run = world.stage(BOX, "--env", "dev")
    assert run.rc == 0, run.text()
    assert "prod gate" not in run.text()
    assert "REFUSED" not in run.text()

    world = fresh()
    run = world.stage(BOX, "--env", "staging", "--sanction", SANCTION_OK)
    assert run.rc == 2, run.text()
    assert (
        "--sanction, --staging and --nightly are the prod gate's and mean nothing for --env staging"
        in run.text()
    )
    assert world.ships() == 0


def test_the_could_not_look_class_has_one_printed_spelling(deploy_scaffold: DeployScaffold) -> None:
    text = (deploy_scaffold.checkout / "deploy" / "stage.sh").read_text().splitlines()
    printed = re.compile(r"^\s*[^#\s][^#]*cannot look")
    hits = [n for n, line in enumerate(text, start=1) if printed.search(line)]
    assert hits == [], f"deploy/stage.sh prints the second spelling at {hits}"
