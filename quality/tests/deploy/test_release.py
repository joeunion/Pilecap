"""`deploy/release.sh` over a stub docker: refusals, the stop at the named act, exits, re-runs.

does-not-cover: whether the acts do what they say — the stub docker proves the wiring and the order.
does-not-cover: a real sink; `apply.py` is stubbed to an exit code, reported verbatim.
does-not-cover: the file itself — a copy runs, since the script derives everything from its dir.
does-not-cover: idempotence of the underlying acts; only re-running the script is proven here.
does-not-cover: `compose exec web`, a command typed on a box, a service later made off-limits.
does-not-cover: the two Temporal organs' server versions — pinned as the one declared pair.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured
from quality.tests.fixtures.deploy_scaffold import DeployScaffold

pytestmark = pytest.mark.drives(
    "deploy/",
    "compose.yaml",
    "docs/runbooks/",
    "manage.py",
    "scripts/bash_only.sh",
    "scripts/tests/drive_preamble.sh",
)

ROOT = Path(__file__).resolve().parents[3]
TAG = "tree-stub00000000"
DIGEST_WEB = "sha256:" + "1" * 64
DIGEST_WORKER = "sha256:" + "2" * 64
DIGEST_FRONTEND = "sha256:" + "3" * 64
EDGE = "{$SITE_ADDRESS} {\n\treverse_proxy web:8000\n}\n"
PIN_9 = "sha256:" + "9" * 64
ALL_ACTS = (
    "integrations migrate grants-generate grants-apply alerts-apply recreate edge-read readyz"
)

COMPOSE = """services:
  db:
    image: postgres:18.6
  web:
    image: djb-web:tree-stub
"""

ENV_FILE = """COMPOSE_PROJECT_NAME='djb_deploy_stubbed'
SITE_ADDRESS='drive.invalid'
O11Y_ADDRESS='o11y.drive.invalid'
POSTGRES_USER='drive_master'
POSTGRES_PASSWORD='not-a-real-password'  # pragma: allowlist secret
DATABASE_USER='drive_app'
DATABASE_PASSWORD='not-a-real-password-either'  # pragma: allowlist secret
DATABASE_NAME='drive_db'
DATABASE_HOST='db.drive.invalid'
DATABASE_PORT='5432'
PGSSLMODE='require'
CLICKSTACK_ADMIN_EMAIL='operator@drive.invalid'
CLICKSTACK_ADMIN_PASSWORD='not-a-real-password-3'  # pragma: allowlist secret
SLACK_WEBHOOK_URL='https://hooks.drive.invalid/services/stub'
DJB_DEPLOY_NAMESPACE='drivenamespace'
PROBE_INSECURE='0'
PROBE_CONNECT_TO=''
"""

# Each arm answers from a knob: an empty digest knob IS "the registry has no such tag" (exit 2).
PROVISION_STUB = """#!/usr/bin/env bash
service="${2:-}"
upper="$(printf '%s' "$service" | tr '[:lower:]' '[:upper:]')"
case "${1:-}" in
project-name) echo "djb_deploy_derived" ;;
image-tag)    echo "${DJB_DRIVE_IMAGE_TAG:-tree-stub00000000}" ;;
image-services) echo "web worker frontend" ;;
image-ref)
    tag="${3:-${DJB_DRIVE_IMAGE_TAG:-tree-stub00000000}}"
    echo "${DJB_DRIVE_REGISTRY:-drive.invalid/ns}/djb-${service}:${tag}"
    ;;
image-digest)
    eval "answer=\\${DJB_DRIVE_REGISTRY_DIGEST_${upper}:-}"
    if [ -z "$answer" ]; then
        echo "stub provision: the registry has no djb-${service} at that tag" >&2
        exit 2
    fi
    echo "$answer"
    ;;
tree-digest)
    eval "answer=\\${DJB_DRIVE_TREE_PIN_${upper}:-}"
    [ -z "$answer" ] || echo "$answer"
    ;;
pin-digest)
    [ -z "${DJB_DRIVE_PIN_LOG:-}" ] || echo "$service ${3:-}" >>"$DJB_DRIVE_PIN_LOG"
    ;;
*) echo "stub provision: unexpected $*" >&2; exit 2 ;;
esac
"""

APPLY_STUB = """#!/usr/bin/env python3
import os
import sys

log = os.environ.get("DJB_DRIVE_ALERTS_LOG")
if log:
    with open(log, "a", encoding="utf-8") as handle:
        handle.write(f"CLICKSTACK_URL={os.environ.get('CLICKSTACK_URL', '')}\\n")
        handle.write(f"SLACK_WEBHOOK_URL={os.environ.get('SLACK_WEBHOOK_URL', '')}\\n")
        handle.write(f"CLICKSTACK_ADMIN_EMAIL={os.environ.get('CLICKSTACK_ADMIN_EMAIL', '')}\\n")
print("[stub apply.py] reconciled")
sys.exit(int(os.environ.get("DJB_DRIVE_ALERTS_RC", "0")))
"""

# The log IS the sequence; `restart` is kept after `up -d` so a regression shows under its name.
DOCKER_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >>"$DJB_DRIVE_DOCKER_LOG"

what="unknown"
case "$*" in
*grants.sql.py*) what="grants-generate" ;;
*alerts/apply.py*) what="alerts-apply" ;;
*"manage.py integrations"*) what="integrations" ;;
*"manage.py migrate"*) what="migrate" ;;
*" psql "*) what="grants-apply" ;;
*readyz-prober*) what="readyz" ;;
*"exec -T caddy"*) what="edge-read" ;;
*"up -d"*) what="recreate" ;;
*restart*) what="restart" ;;
esac

if [ "$what" = "${DJB_DRIVE_FAIL_ACT:-}" ]; then
    echo "stub docker: the case asked ${what} to fail" >&2
    exit "${DJB_DRIVE_FAIL_RC:-1}"
fi

case "$what" in
integrations)
    echo "configured      object-storage - bucket drive-bucket answered a HEAD from this process."
    echo "configured      outbound-email - smtp - mail leaves this process."
    prev=""
    for word in "$@"; do
        if [ "$prev" = "--accept-fake" ]; then
            echo "ACCEPTED FAKE  ${word} - a stand-in this operator named in the vault."
            echo "               remedy: point it at a real gateway."
        fi
        prev="$word"
    done
    if [ "${DJB_DRIVE_STALE_ACCEPTANCE:-}" = "1" ]; then
        echo "REFUSED: 1 acceptance(s) do not name a fake." >&2
        exit 1
    fi
    if [ "${DJB_DRIVE_FAKE_INTEGRATION:-}" = "1" ]; then
        echo "FAKE            outbound-email - console - mail is printed to stdout" \
            "and never reaches anybody."
        echo "REFUSED: 1 integration(s) are not configured - outbound-email." >&2
        exit 1
    fi
    echo "All 2 integrations are configured."
    ;;
migrate)
    echo "Operations to perform: Apply all migrations." \
        "Running migrations: No migrations to apply."
    ;;
alerts-apply)
    if [ -n "${DJB_DRIVE_ALERTS_LOG:-}" ]; then
        {
            echo "CLICKSTACK_URL=${CLICKSTACK_URL:-}"
            echo "SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL:-}"
            echo "CLICKSTACK_ADMIN_EMAIL=${CLICKSTACK_ADMIN_EMAIL:-}"
            echo "DJB_DEPLOY_NAMESPACE=${DJB_DEPLOY_NAMESPACE:-}"
        } >>"$DJB_DRIVE_ALERTS_LOG"
    fi
    echo "[stub apply.py, in-container] reconciled"
    exit "${DJB_DRIVE_ALERTS_RC:-0}"
    ;;
grants-generate)
    if [ "${DJB_DRIVE_EMPTY_GRANTS:-}" = "1" ]; then exit 0; fi
    echo "-- Generated by deploy/grants.sql.py. Do not edit; re-generate."
    echo 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "public" TO "drive_app";'
    echo 'REVOKE UPDATE, DELETE ON "core_auditentry" FROM "drive_app";'
    ;;
grants-apply)
    cat >/dev/null
    echo "GRANT"
    echo "REVOKE"
    ;;
readyz) printf '%s' "${DJB_DRIVE_READYZ_CODE:-200}" ;;
edge-read) [ -z "${DJB_DRIVE_EDGE_RUNNING:-}" ] || cat "$DJB_DRIVE_EDGE_RUNNING" ;;
recreate) echo "Container djb-web-1  Recreated" ; echo "Container djb-worker-1  Recreated" ;;
restart) echo "Restarting web ... done" ;;
*) echo "stub docker: unclassified invocation: $*" >&2 ;;
esac
exit 0
"""

ACTS = (
    ("grants.sql.py", "grants-generate"),
    ("alerts/apply.py", "alerts-apply"),
    ("manage.py integrations", "integrations"),
    ("manage.py migrate", "migrate"),
    (" psql ", "grants-apply"),
    ("readyz-prober", "readyz"),
    ("exec -T caddy", "edge-read"),
    ("up -d", "recreate"),
    ("restart", "restart"),
)

# The Temporal pair, measured unequal (dev server 1.31.2, auto-setup 1.29.0), pinned as declared.
TEMPORAL_DECLARED_PAIR = [
    "temporalio/temporal:1.8.2@sha256:cf86707827fac99e4d1c4a47dc11b105382d796199c7bd41fb3213fb0471628e",
    "temporalio/auto-setup:1.29.0@sha256:8940bfb5aed467458d50c365e420038bc334a44af77e8f4b5e2bfcd608ac7951",
]


@dataclass
class Deployment:
    """A scratch deployment: `release.sh` copied, stub siblings, a TREE marker, a stub docker."""

    case: Path
    capture: Callable[..., Captured]

    @property
    def deploy(self) -> Path:
        """The deployment's `deploy/` directory."""
        return self.case / "deploy"

    @property
    def script(self) -> str:
        """The copy of `release.sh` this deployment runs."""
        return str(self.deploy / "release.sh")

    @property
    def docker_log(self) -> Path:
        """Every docker invocation, in order."""
        return self.case / "docker.log"

    @property
    def alerts_log(self) -> Path:
        """The environment the alerts act was handed; absent when it never ran."""
        return self.case / "alerts.log"

    @property
    def pin_log(self) -> Path:
        """Every `pin-digest` the stub provision recorded."""
        return self.case / "pin.log"

    @property
    def env_file(self) -> Path:
        """The deployment's `deploy/.env`."""
        return self.deploy / ".env"

    def release(self, *argv: str, **knobs: str) -> Captured:
        """`argv` under the stub docker and the case's knobs, applied last."""
        assignments = {
            "PATH": f"{self.case / 'bin'}:{os.environ['PATH']}",
            "DJB_DRIVE_DOCKER_LOG": str(self.docker_log),
            "DJB_DRIVE_ALERTS_LOG": str(self.alerts_log),
            "DJB_DRIVE_PIN_LOG": str(self.pin_log),
            "DJB_READYZ_ATTEMPTS": "2",
            "DJB_READYZ_INTERVAL": "0",
            "DJB_DRIVE_IMAGE_TAG": TAG,
            "DJB_DRIVE_REGISTRY_DIGEST_WEB": DIGEST_WEB,
            "DJB_DRIVE_REGISTRY_DIGEST_WORKER": DIGEST_WORKER,
            "DJB_DRIVE_REGISTRY_DIGEST_FRONTEND": DIGEST_FRONTEND,
            "DJB_DRIVE_EDGE_RUNNING": str(self.deploy / "Caddyfile"),
            **knobs,
        }
        pairs = [f"{name}={value}" for name, value in assignments.items()]
        return self.capture(
            ["env", "-u", "COMPOSE_PROJECT_NAME", "-u", "DJB_IMAGE_TAG", *pairs, *argv]
        )

    def calls(self) -> list[str]:
        """Every docker invocation's argv line."""
        return self.docker_log.read_text().splitlines()

    def saw(self, needle: str) -> int:
        """How many docker invocations carry `needle`."""
        return sum(needle in line for line in self.calls())

    def acts(self) -> str:
        """The stub's classification of each invocation, in order, one word each."""
        words = [next((w for n, w in ACTS if n in line), "?") for line in self.calls()]
        return " ".join(words)

    def pins(self) -> list[str]:
        """The pins recorded, in order."""
        return self.pin_log.read_text().splitlines()

    def edit_env(self, pattern: str, replacement: str | None) -> None:
        """Replace (or, given `None`, delete) every `.env` line matching `pattern`."""
        lines = self.env_file.read_text().splitlines(keepends=True)
        out = [
            line if not re.match(pattern, line) else ("" if replacement is None else replacement)
            for line in lines
        ]
        self.env_file.write_text("".join(out))

    def append_env(self, line: str) -> None:
        """Append one line to `.env`."""
        with self.env_file.open("a") as handle:
            handle.write(f"{line}\n")


@pytest.fixture
def fresh(
    scratch: Path, capture: Callable[..., Captured], deploy_scaffold: DeployScaffold
) -> Callable[[], Deployment]:
    """`fresh()` builds the next deployment, so no case reads another's logs."""
    if not (ROOT / "deploy" / "release.sh").is_file():
        raise CouldNotLook("deploy/release.sh is not in this tree — there is nothing to drive")
    made = 0

    def build() -> Deployment:
        nonlocal made
        made += 1
        case = deploy_scaffold.into(scratch.resolve() / f"case{made}", "deploy/release.sh")
        world = Deployment(case, capture)
        (world.deploy / "observability" / "alerts").mkdir(parents=True)
        (case / "bin").mkdir()
        world.pin_log.write_text("")
        world.docker_log.write_text("")
        (case / "TREE").write_text(f"{TAG}\n")
        (world.deploy / "compose.yaml").write_text(COMPOSE)
        (world.deploy / "Caddyfile").write_text(EDGE)
        world.env_file.write_text(ENV_FILE)
        for path, body in (
            (world.deploy / "provision.sh", PROVISION_STUB),
            (world.deploy / "observability" / "alerts" / "apply.py", APPLY_STUB),
            (case / "bin" / "docker", DOCKER_STUB),
        ):
            path.write_text(body)
            path.chmod(0o755)
        (world.deploy / "release.sh").chmod(0o755)
        return world

    return build


def says(run: Captured, *needles: str) -> None:
    """Every needle is in the run's transcript."""
    text = run.text()
    for needle in needles:
        assert needle in text, f"does not say {needle!r}"


def says_not(run: Captured, *needles: str) -> None:
    """No needle is in the run's transcript."""
    text = run.text()
    for needle in needles:
        assert needle not in text, f"says {needle!r} and must not"


def exits(run: Captured, rc: int) -> None:
    """The run exited `rc`."""
    assert run.rc == rc, f"wanted exit {rc}, got {run.rc}\n{run.text()[-3000:]}"


def sever(world: Deployment, pattern: str) -> str:
    """A copy of `release.sh` beside the real one with the guard matching `pattern` made false."""
    source = (ROOT / "deploy" / "release.sh").read_text()
    severed = re.sub(pattern, "if false; then", source, flags=re.MULTILINE)
    assert severed != source, "the canary planted NOTHING — the sever pattern no longer matches"
    path = world.deploy / "severed.sh"
    path.write_text(severed)
    path.chmod(0o755)
    return str(path)


STALE_TAG_GUARD = (
    r'^if \[ -n "\$\{DJB_IMAGE_TAG:-\}" \] && \[ "\$DJB_IMAGE_TAG" != "\$IMAGE_TAG" \]; then'
)
NO_SUCH_TAG_GUARD = r'(?<=    )if \[ "\$release_rc" != "0" \]; then'
MISMATCH_GUARD = (
    r'(?<=    )if \[ -n "\$release_pin" \] && \[ "\$release_pin" != "\$release_digest" \]; then'
)
NO_REGISTRY = {
    "DJB_DRIVE_REGISTRY_DIGEST_WEB": "",
    "DJB_DRIVE_REGISTRY_DIGEST_WORKER": "",
    "DJB_DRIVE_REGISTRY_DIGEST_FRONTEND": "",
}


# --- the refusals: exit 2, and nothing ran --------------------------------------------


def test_an_unknown_flag_is_refused(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, "--skip-grants")
    exits(run, 2)
    says(run, "unknown argument")
    assert world.calls() == []


def test_a_piped_stdout_is_refused(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release("bash", "-c", f"set -o pipefail; '{world.script}' | cat")
    exits(run, 2)
    says(run, "refuses pipes")
    assert world.calls() == []


def test_a_missing_env_file_is_refused(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.env_file.unlink()
    run = world.release(world.script)
    exits(run, 2)
    says(run, "/.env", "secrets-fetch", "Nothing was released")
    assert world.calls() == []


def test_an_empty_required_slot_is_refused_before_the_first_act(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.edit_env(r"^DATABASE_HOST=", "DATABASE_HOST=''\n")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "DATABASE_HOST", "Nothing was released")
    assert world.calls() == []


def test_missing_alert_credentials_are_a_refusal_not_a_skip(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.edit_env(r"^CLICKSTACK_ADMIN_PASSWORD=", "CLICKSTACK_ADMIN_PASSWORD=''\n")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "REFUSED", "CLICKSTACK_ADMIN_PASSWORD", "--without-alerts", "Nothing was released")
    assert world.calls() == []


def test_an_unreadable_postgres_pin_is_refused(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    (world.deploy / "compose.yaml").write_text("services:\n  web:\n    image: djb-web:tree-stub\n")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "postgres image pin")
    assert world.calls() == []


def test_a_missing_apply_py_is_refused_before_the_first_act(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    (world.deploy / "observability" / "alerts" / "apply.py").unlink()
    run = world.release(world.script)
    exits(run, 2)
    says(run, "apply.py", "Nothing was released")
    assert world.calls() == []


# --- the clean run ----------------------------------------------------------------------


def test_a_clean_release_performs_seven_acts_in_order(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    says(run, *(f"[{n}/7]" for n in range(1, 8)))
    says(run, "RELEASED. 7/7 acts complete.", 'REVOKE UPDATE, DELETE ON "core_auditentry"')
    assert world.acts() == ALL_ACTS


def test_the_psql_client_is_the_compose_pin(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    exits(world.release(world.script), 0)
    assert world.saw("postgres:18.6") == 1
    assert world.saw("postgres:16.10") == 0


def test_the_migrate_act_prints_its_wall(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    lines = run.text().splitlines()
    wall = re.compile(r"release: migrate: [0-9]+s")

    def first(test: Callable[[str], bool]) -> int | None:
        return next((n for n, line in enumerate(lines, start=1) if test(line)), None)

    at2 = first(lambda x: x.startswith("release: [2/7]"))
    at_wall = first(lambda x: bool(wall.fullmatch(x)))
    at3 = first(lambda x: x.startswith("release: [3/7]"))
    assert sum(bool(wall.fullmatch(x)) for x in lines) == 1
    assert at2 is not None and at_wall is not None and at3 is not None
    assert at2 < at_wall < at3, (at2, at_wall, at3)

    world = fresh()
    run = world.release(world.script, "--dry-run")
    exits(run, 0)
    says_not(run, "release: migrate: ")


def test_the_psql_client_carries_the_compose_digest(fresh: Callable[[], Deployment]) -> None:
    digest = "sha256:" + "5a" * 32
    world = fresh()
    (world.deploy / "compose.yaml").write_text(
        f"services:\n  db:\n    image: postgres:18.6@{digest}\n"
        "  web:\n    image: djb-web:tree-stub\n"
    )
    exits(world.release(world.script), 0)
    assert world.saw(f"postgres:18.6@{digest}") == 1

    world = fresh()
    (world.deploy / "compose.yaml").write_text(
        f"services:\n  db:\n    image: postgres:18.6@{digest}\n"
    )
    run = world.release(world.script, "--dry-run")
    exits(run, 0)
    says(run, f"psql client  postgres:18.6@{digest}")


def test_the_network_is_the_env_files_project(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    exits(world.release(world.script), 0)
    assert world.saw("--network djb_deploy_stubbed_default") == 1


def test_the_project_falls_back_to_the_derivation(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.edit_env(r"^COMPOSE_PROJECT_NAME=", None)
    exits(world.release(world.script), 0)
    assert world.saw("--network djb_deploy_derived_default") == 1


def alerts_has(world: Deployment, needle: str) -> int:
    """How many lines of the alerts act's recorded environment carry `needle`."""
    if not world.alerts_log.is_file():
        return 0
    return sum(needle in line for line in world.alerts_log.read_text().splitlines())


def test_the_alerts_act_is_handed_the_sink_and_the_slot(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    exits(world.release(world.script), 0)
    assert alerts_has(world, "CLICKSTACK_URL=http://clickstack:8080") == 1
    assert alerts_has(world, "SLACK_WEBHOOK_URL=https://hooks.drive.invalid") == 1
    assert world.saw("-e DJB_DEPLOY_NAMESPACE") == 1


def test_the_alerts_act_runs_in_container_on_the_stack_network(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    calls = world.calls()
    assert sum(bool(re.search(r"run --rm.*alerts/apply\.py", c)) for c in calls) == 1
    assert world.saw("oneoff python") == 4
    assert sum(bool(re.search(r"run .*\sweb\s", c)) for c in calls) == 0
    assert world.saw("/app/deploy/observability/alerts/apply.py") == 1
    assert alerts_has(world, "CLICKSTACK_URL=http://clickstack:8080") == 1
    assert alerts_has(world, "CLICKSTACK_ADMIN_EMAIL=operator@drive.invalid") == 1
    says_not(run, "https://o11y.drive.invalid")
    assert alerts_has(world, "o11y.drive.invalid") == 0


def test_the_release_runs_no_host_python_against_the_tree(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    pylog = world.case / "python.log"
    pylog.write_text("")
    for name in ("python", "python3"):
        stub = world.case / "bin" / name
        stub.write_text(
            '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >>"$DJB_DRIVE_PYTHON_LOG"\nexit 0\n'
        )
        stub.chmod(0o755)
    exits(world.release(world.script, DJB_DRIVE_PYTHON_LOG=str(pylog)), 0)
    assert pylog.read_text().splitlines() == []


def test_act_six_recreates_the_app_rather_than_restarting_it(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    says(run, "[6/7] recreate")
    assert world.saw("up -d --no-deps web worker frontend") == 1
    assert world.saw("restart web worker") == 0
    assert world.saw("restart caddy") == 0, "an edge whose file did not move is left alone"


def test_act_six_restarts_an_edge_whose_file_moved(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    running = world.case / "Caddyfile.running"
    running.write_text("{$SITE_ADDRESS} {\n\treverse_proxy web:8000 frontend:3000\n}\n")
    run = world.release(world.script, DJB_DRIVE_EDGE_RUNNING=str(running))
    exits(run, 0)
    says(run, "caddy restarted onto")
    assert world.acts().split()[-3:] == ["edge-read", "restart", "readyz"], world.acts()


def test_the_readyz_probe_is_the_probers_own(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.edit_env(r"^PROBE_INSECURE=", "PROBE_INSECURE='1'\n")
    world.edit_env(r"^PROBE_CONNECT_TO=", "PROBE_CONNECT_TO='localhost:443:caddy:443'\n")
    exits(world.release(world.script), 0)
    assert world.saw("exec -T readyz-prober sh /alerts/prober.sh --once") == 1
    assert world.saw(" -k ") == 0
    assert world.saw("localhost:443:caddy:443") == 0
    assert world.saw("/readyz") == 0

    bin_dir, args = world.case / "curlbin", world.case / "curl.args"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >"{args}"\nprintf 200\n')
    curl.chmod(0o755)
    once = subprocess.run(
        ["sh", "deploy/observability/alerts/prober.sh", "--once"],
        cwd=ROOT, capture_output=True, text=True,
        env={**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin",
             "PROBE_TARGET": "https://drive.invalid/readyz",
             "PROBE_CONNECT_TO": "localhost:443:caddy:443", "PROBE_INSECURE": "1"},
    )  # fmt: skip
    assert f"{once.stdout} {once.returncode}" == "200 0"
    called = args.read_text().splitlines()
    assert sum("-k " in line for line in called) == 1
    assert sum("--connect-to localhost:443:caddy:443" in line for line in called) == 1
    assert sum("https://drive.invalid/readyz" in line for line in called) == 1


SCAFFOLD_EXCEPTIONS = {
    "deploy/entrypoint.sh",
    "deploy/assert_not_published.sh",
    "deploy/observability/alerts/prober.sh",
    "deploy/verifier/idle_reaper.sh",
}


def git_lines(*args: str) -> list[str]:
    """`git <args>` in this checkout; its non-empty stdout lines, whatever its exit."""
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return [line for line in done.stdout.splitlines() if line]


def test_every_deploy_executable_sources_the_one_scaffold() -> None:
    sources = re.compile(r'^\s*\. "\$HERE/(\.\./)?lib\.sh" \|\| exit 2$', re.MULTILINE)
    own_copy = re.compile(r"^(die|say|usage|stopped|act)\(\) *\{", re.MULTILINE)
    population = [
        f
        for f in git_lines("ls-files", "deploy/*.sh")
        if not f.startswith("deploy/tests/") and f not in SCAFFOLD_EXCEPTIONS
        and os.access(ROOT / f, os.X_OK)
    ]  # fmt: skip
    missing = []
    for relative in population:
        text = (ROOT / relative).read_text()
        lines = text.splitlines()
        line2 = lines[1] if len(lines) > 1 else ""
        if (
            not line2.endswith('scripts/bash_only.sh" || exit 2')
            or not sources.search(text)
            or own_copy.search(text)
        ):
            missing.append(relative)
    assert len(population) >= 5, f"the census read {len(population)} deploy executable(s)"
    assert missing == [], missing
    guard = "-p /dev/fd/" + "1"
    assert git_lines("grep", "-l", "--", guard, "--", "deploy") == []
    cited = r"scripts/check\.sh:[0-9]+|release\.sh:[0-9]+"
    assert git_lines("grep", "-nE", cited, "--", "deploy", ":!deploy/tests") == []


def test_without_alerts_skips_exactly_one_act_and_says_so(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, "--without-alerts")
    exits(run, 0)
    says(run, "[5/7]", "SKIPPED", "typed on purpose", "RELEASED")
    assert not world.alerts_log.exists()
    assert world.acts() == ALL_ACTS.replace("alerts-apply ", "")


def test_dry_run_touches_nothing(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, "--dry-run")
    exits(run, 0)
    says(run, "DRY RUN", "nothing was touched.")
    says_not(run, "RELEASED")
    assert world.calls() == []
    assert not world.alerts_log.exists()


# --- the failures: exit 1, the act named, nothing after it -----------------------------


def test_a_fake_integration_stops_the_release_before_anything_changed(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_FAKE_INTEGRATION="1")
    exits(run, 1)
    says(run, "STOPPED at act 1/7 — integrations", "No act after this one ran.")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations"


def test_an_unreadable_seam_stops_the_release_with_its_own_code(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_FAIL_ACT="integrations", DJB_DRIVE_FAIL_RC="2")
    exits(run, 1)
    says(run, "STOPPED at act 1/7 — integrations (exit 2)")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations"


def test_a_failed_migrate_stops_at_act_one(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_FAIL_ACT="migrate", DJB_DRIVE_FAIL_RC="1")
    exits(run, 1)
    says(run, "STOPPED at act 2/7 — migrate", "No act after this one ran.")
    says(run, "RE-RUN THIS SCRIPT FROM THE TOP")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations migrate"


def test_an_empty_generated_sql_stops_at_act_two(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_EMPTY_GRANTS="1")
    exits(run, 1)
    says(run, "STOPPED at act 3/7 — grants generate")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations migrate grants-generate"


def test_a_failed_grants_apply_stops_at_act_three(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_FAIL_ACT="grants-apply", DJB_DRIVE_FAIL_RC="3")
    exits(run, 1)
    says(run, "STOPPED at act 4/7 — grants apply (exit 3)")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations migrate grants-generate grants-apply"


def test_a_failed_alerts_apply_stops_at_act_four_with_its_own_code(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_ALERTS_RC="3")
    exits(run, 1)
    says(run, "STOPPED at act 5/7 — alerts apply (exit 3)")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations migrate grants-generate grants-apply alerts-apply"


def test_a_failed_recreate_stops_at_act_five(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_FAIL_ACT="recreate", DJB_DRIVE_FAIL_RC="1")
    exits(run, 1)
    says(run, "STOPPED at act 6/7 — recreate")
    says_not(run, "RELEASED")
    assert world.acts() == (
        "integrations migrate grants-generate grants-apply alerts-apply recreate"
    )


def test_a_deployment_that_never_becomes_ready_is_a_failed_release(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_READYZ_CODE="503")
    exits(run, 1)
    says(run, "did not answer 200", "the deployment is not serving", "last answer: 503")
    says_not(run, "RELEASED")
    assert world.saw("readyz-prober") == 2


# --- the acceptance slot ----------------------------------------------------------------


def test_an_empty_acceptance_slot_is_the_whole_wall(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    assert world.saw("--accept-fake") == 0
    says_not(run, "ACCEPTED FAKE")


def test_an_accepted_fake_proceeds_past_act_one_and_says_so(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.append_env("DJB_ACCEPTED_FAKES='stub-standin-a'")
    run = world.release(world.script)
    exits(run, 0)
    assert world.saw("--accept-fake stub-standin-a") == 1
    says(run, "ACCEPTED FAKE", "stub-standin-a", "RELEASED", "stood on 1 accepted fake(s)")


def test_two_accepted_fakes_are_two_flags_in_order(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.append_env("DJB_ACCEPTED_FAKES='stub-standin-a stub-standin-b'")
    run = world.release(world.script)
    exits(run, 0)
    assert world.saw("--accept-fake stub-standin-a") == 1
    assert world.saw("--accept-fake stub-standin-b") == 1
    says(run, "stood on 2 accepted fake(s)")


def test_an_accepted_fake_beside_an_unaccepted_one_still_stops_at_act_one(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.append_env("DJB_ACCEPTED_FAKES='stub-standin-a'")
    run = world.release(world.script, DJB_DRIVE_FAKE_INTEGRATION="1")
    exits(run, 1)
    says(run, "ACCEPTED FAKE", "STOPPED at act 1/7 — integrations", "No act after this one ran.")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations"


def test_a_stale_acceptance_stops_at_act_one(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.append_env("DJB_ACCEPTED_FAKES='stub-standin-a'")
    run = world.release(world.script, DJB_DRIVE_STALE_ACCEPTANCE="1")
    exits(run, 1)
    assert world.saw("--accept-fake stub-standin-a") == 1
    says(run, "STOPPED at act 1/7 — integrations")
    says_not(run, "RELEASED")
    assert world.acts() == "integrations"


def test_the_dry_run_names_the_acceptance_without_touching_anything(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.append_env("DJB_ACCEPTED_FAKES='stub-standin-a'")
    run = world.release(world.script, "--dry-run")
    exits(run, 0)
    says(run, "stub-standin-a", "nothing was touched.")
    assert world.calls() == []


# --- the alert route's two questions ----------------------------------------------------


def test_an_empty_webhook_slot_refuses_in_its_own_words(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.edit_env(r"^SLACK_WEBHOOK_URL=", "SLACK_WEBHOOK_URL=''\n")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "REFUSED", "SLACK_WEBHOOK_URL", "nowhere to deliver", "route unreconciled")
    says(run, "Nothing was released")
    says_not(run, "step 53", "no sink yet")
    assert world.calls() == []


def test_the_deferred_clickstack_pair_keeps_its_own_message(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.edit_env(r"^CLICKSTACK_ADMIN_EMAIL=", "CLICKSTACK_ADMIN_EMAIL=''\n")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "REFUSED", "CLICKSTACK_ADMIN_EMAIL", "step 53", "no sink yet")
    says_not(run, "nowhere to deliver")
    assert world.calls() == []


def test_without_alerts_still_releases_with_an_empty_webhook_slot(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.edit_env(r"^SLACK_WEBHOOK_URL=", "SLACK_WEBHOOK_URL=''\n")
    run = world.release(world.script, "--without-alerts")
    exits(run, 0)
    says(run, "[5/7]", "SKIPPED", "RELEASED")


# --- the pins and the transcript, read off the real tree -------------------------------


STACK_PREFIX = re.compile(r"^\$\{DJB_STACK_REGISTRY:-docker\.io\}/(library/)?")


def compose_images(path: Path) -> dict[str, str]:
    """Each service's literal `image:` under `services:`, interpolated ones left out."""
    out: dict[str, str] = {}
    inside, service = False, None
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        if re.match(r"^\S", line):
            inside = line.startswith("services:")
            continue
        if not inside:
            continue
        named = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if named:
            service = named.group(1)
            continue
        image = re.match(r"^    image:\s*(\S+)\s*(#.*)?$", line)
        ref = STACK_PREFIX.sub("", image.group(1)) if image else ""
        if image and service and "${" not in ref:
            out[service] = ref
    return out


def split_ref(ref: str) -> tuple[str, str]:
    """(repository, digest) of an image reference."""
    name, _, digest = ref.partition("@")
    repo = name.rsplit(":", 1)[0] if ":" in name.rsplit("/", 1)[-1] else name
    return repo, digest


def image_census(laptop_file: Path, box_file: Path) -> tuple[int, list[str]]:
    """(shared services compared, one line per service whose images disagree)."""
    laptop, box = compose_images(laptop_file), compose_images(box_file)
    shared = sorted(set(laptop) & set(box))
    found = []
    for service in shared:
        a, b = laptop[service], box[service]
        if service == "temporal":
            if [a, b] != TEMPORAL_DECLARED_PAIR:
                found.append(f"temporal: the declared pair moved ({a} / {b})")
            continue
        if split_ref(a) != split_ref(b) or not split_ref(a)[1]:
            found.append(f"{service}: {a} / {b}")
    return len(shared), found


def test_every_image_both_compose_files_declare_is_the_same_image(scratch: Path) -> None:
    count, found = image_census(ROOT / "compose.yaml", ROOT / "deploy" / "compose.yaml")
    assert count >= 2, f"the image census compared {count} shared service(s)"
    assert found == [], found
    plant = scratch / "compose-drift.yaml"
    plant.write_text(
        re.sub(
            r"getmeili/meilisearch:(v[0-9.]*)@sha256:[0-9a-f]*",
            r"getmeili/meilisearch:\1@sha256:" + "0" * 64,
            (ROOT / "deploy" / "compose.yaml").read_text(),
        )
    )
    _count, drifted = image_census(ROOT / "compose.yaml", plant)
    assert any(line.startswith("meilisearch: getmeili/meilisearch") for line in drifted), drifted


GLOBAL_FLAGS = set(
    "-p --project-name -f --file --env-file --profile --project-directory --parallel "
    "--progress --ansi".split()
)
RUN_FLAGS = set(
    "-e --env -v --volume -w --workdir -u --user -l --label -p --publish --name "
    "--entrypoint".split()
)


def compose_run_census(*paths: Path) -> list[str]:
    """`file:line: compose run names <svc>` for every one-off that runs as web or worker."""
    found: list[str] = []
    buf, start = "", 0
    for path in paths:
        for number, raw in enumerate(path.read_text().splitlines(), start=1):
            if buf == "":
                start, buf = number, raw
            else:
                buf = f"{buf} {raw}"
            if re.search(r"\\\s*$", buf):
                buf = re.sub(r"\\\s*$", " ", buf)
                continue
            line, buf = buf, ""
            tokens = re.split(r"\s+", line)
            at = 0
            for i, tok in enumerate(tokens):
                after = tokens[i + 1] if i + 1 < len(tokens) else ""
                if tok == "docker" and after == "compose":
                    at = i + 2
                    break
                if tok == "compose":
                    at = i + 1
                    break
            if at == 0:
                continue
            sub, at = word_after(tokens, at, GLOBAL_FLAGS, skip=("...", "…"))
            if sub != "run":
                continue
            service, _ = word_after(tokens, at, RUN_FLAGS)
            if service in ("web", "worker"):
                found.append(f"{path}:{start}: `compose run` names `{service}`")
    return found


def word_after(
    tokens: list[str], at: int, flags: set[str], skip: tuple[str, ...] = ()
) -> tuple[str, int]:
    """The first bare token from `at`, value-taking `flags` skipped; and the index after it."""
    i = at
    while i < len(tokens):
        tok = tokens[i]
        if tok == "" or tok in skip:
            i += 1
            continue
        if tok.startswith("-"):
            i += 2 if "=" not in tok and tok in flags else 1
            continue
        return tok, i + 1
    return "", i


def test_no_one_off_runs_as_web_or_worker() -> None:
    population = [
        ROOT / "deploy" / "release.sh",
        *sorted((ROOT / "docs" / "runbooks").glob("*.md")),
    ]
    assert len(population) >= 2, "the compose-run census found no runbooks to read"
    found = compose_run_census(*population)
    assert found == [], "\n".join(found)


VICTIM = """Prose that says the word web, and mentions docker compose run in a sentence.
```bash
docker compose -f deploy/compose.yaml run --rm -T web python manage.py migrate
docker compose -f deploy/compose.yaml run --rm -T -e A -e B worker python -c pass
docker compose -f deploy/compose.yaml exec web uv run python manage.py shell
docker compose -f deploy/compose.yaml run --rm -T oneoff python manage.py migrate
docker compose -f deploy/compose.yaml \\
  run --rm -T \\
  web python manage.py check --deploy
docker compose -p djb-b1a ... run --rm -T web python manage.py introspect
"""


def test_the_compose_run_census_can_actually_fire(scratch: Path) -> None:
    victim = scratch / "planted-runbook.md"
    victim.write_text(VICTIM)
    found = compose_run_census(victim)
    assert len(found) == 4, found
    assert [f for f in found if re.search(r":1:|:5:|:6:", f)] == []
    assert sum(":7:" in f for f in found) == 1
    assert sum(":10:" in f for f in found) == 1


# --- re-runnability -----------------------------------------------------------------------


def test_a_release_that_stopped_can_be_re_run_from_the_top(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_FAIL_ACT="grants-apply", DJB_DRIVE_FAIL_RC="1")
    exits(run, 1)
    says(run, "STOPPED at act 4/7")
    world.docker_log.write_text("")
    run = world.release(world.script)
    exits(run, 0)
    says(run, "RELEASED")
    assert world.acts() == ALL_ACTS


# --- build once, promote by digest (ADR deploy-4) ---------------------------------------


def test_a_tag_the_registry_lacks_stops_before_act_one(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script, **NO_REGISTRY)
    exits(run, 2)
    says(run, "REFUSED — the registry does not have", "djb-web:tree-stub00000000")
    says(run, "THE BOX DOES NOT BUILD", "Nothing was released; no act ran.")
    assert world.calls() == []
    assert world.pins() == []


def test_a_registry_digest_that_contradicts_the_pin_stops_before_act_one(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, DJB_DRIVE_TREE_PIN_WEB=PIN_9)
    exits(run, 1)
    says(run, "THE REGISTRY AND THIS BOX DISAGREE", "the registry says   sha256:1111")
    says(run, "this box pinned     sha256:9999", "Nothing was released; no act ran.")
    assert world.calls() == []


def test_a_pin_that_agrees_with_the_registry_is_not_a_mismatch(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(
        world.script,
        DJB_DRIVE_TREE_PIN_WEB=DIGEST_WEB,
        DJB_DRIVE_TREE_PIN_WORKER=DIGEST_WORKER,
        DJB_DRIVE_TREE_PIN_FRONTEND=DIGEST_FRONTEND,
    )
    exits(run, 0)
    says(run, "RELEASED. 7/7 acts complete.")
    says_not(run, "DISAGREE")


def test_an_unpinned_box_is_not_a_mismatch(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    says(run, "RELEASED. 7/7 acts complete.")
    says_not(run, "DISAGREE")


def test_the_release_pins_the_registrys_digest_after_the_recreate(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script)
    exits(run, 0)
    says(run, "pinned 3 digests into")
    assert world.pins()[:3] == [
        f"web {DIGEST_WEB}",
        f"worker {DIGEST_WORKER}",
        f"frontend {DIGEST_FRONTEND}",
    ]
    lines = run.text().splitlines()
    recreate = next((n for n, x in enumerate(lines) if "recreate — every image service" in x), None)
    pinned = next((n for n, x in enumerate(lines) if "pinned 3 digests into" in x), None)
    assert recreate is not None and pinned is not None and recreate < pinned, (recreate, pinned)


def test_a_checkout_with_no_tree_marker_pins_nothing_and_says_so(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    (world.case / "TREE").unlink()
    run = world.release(world.script)
    exits(run, 0)
    says(run, "this is a checkout, not a shipped box; nothing pinned")
    assert world.pins() == []


def test_a_stale_env_image_tag_is_refused_before_act_one(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    world.append_env("DJB_IMAGE_TAG='tree-thelastdeploy'")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "REFUSED — the env file pins a different tree than this box holds")
    says(run, "this tree is    tree-stub00000000", "the env file    tree-thelastdeploy")
    says(run, "./deploy/provision.sh up", "Nothing was released; no act ran.")
    assert world.calls() == []
    assert world.pins() == []

    severed = world.release(sever(world, STALE_TAG_GUARD))
    exits(severed, 0)
    says_not(severed, "REFUSED — the env file pins a different tree than this box holds")

    world = fresh()
    world.append_env("DJB_IMAGE_TAG='tree-thelastdeploy'")
    run = world.release(world.script)
    exits(run, 2)
    says(run, "REFUSED — the env file pins a different tree than this box holds")


def test_an_env_tag_that_agrees_and_a_checkout_that_pins_none_both_release(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    world.append_env(f"DJB_IMAGE_TAG='{TAG}'")
    run = world.release(world.script)
    exits(run, 0)
    says(run, "RELEASED. 7/7 acts complete.")
    says_not(run, "the env file pins a different tree")

    world = fresh()
    (world.case / "TREE").unlink()
    run = world.release(world.script)
    exits(run, 0)
    says(run, "RELEASED. 7/7 acts complete.")
    says_not(run, "the env file pins a different tree")


def test_the_dry_run_names_the_image_and_the_digest_it_would_release(
    fresh: Callable[[], Deployment],
) -> None:
    world = fresh()
    run = world.release(world.script, "--dry-run")
    exits(run, 0)
    says(run, "tree tag     tree-stub00000000", "djb-web:tree-stub00000000", DIGEST_WEB)
    says(run, "nothing was touched.")
    assert world.pins() == []


def test_the_registry_guards_can_actually_fire(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    run = world.release(sever(world, NO_SUCH_TAG_GUARD), **NO_REGISTRY)
    exits(run, 0)
    says_not(run, "REFUSED — the registry does not have")

    run = world.release(sever(world, MISMATCH_GUARD), DJB_DRIVE_TREE_PIN_WEB=PIN_9)
    exits(run, 0)
    says_not(run, "THE REGISTRY AND THIS BOX DISAGREE")

    world = fresh()
    run = world.release(world.script, **NO_REGISTRY)
    exits(run, 2)
    says(run, "REFUSED — the registry does not have")


def test_promotion_is_a_re_pin_of_the_same_digest_and_never_a_build(
    fresh: Callable[[], Deployment],
) -> None:
    staging = fresh()
    exits(staging.release(staging.script), 0)
    prod = fresh()
    exits(prod.release(prod.script), 0)
    assert prod.pin_log.read_text() == staging.pin_log.read_text()
    built = [c for c in prod.calls() if re.search(r"(^| )(build|buildx)( |$)", c)]
    assert built == [], built


def test_the_deployment_compose_declares_no_build() -> None:
    box = (ROOT / "deploy" / "compose.yaml").read_text().splitlines()
    second = ROOT / "deploy" / "compose.second.yaml"
    both = box + (second.read_text().splitlines() if second.is_file() else [])
    assert sum(bool(re.match(r"^\s*build:", x)) for x in both) == 0
    anchored = r"^x-image-(web|worker): &image-(web|worker) \$\{DJB_IMAGE_REGISTRY"
    assert sum(bool(re.match(anchored, x)) for x in box) == 2
    assert sum(bool(re.fullmatch(r"    image: \*image-(web|worker)", x)) for x in box) == 2
    oneoff = "    image: ${DJB_IMAGE_REGISTRY}/djb-web:${DJB_IMAGE_TAG}"
    assert sum(x == oneoff for x in box) == 1


def test_two_clean_runs_perform_the_identical_sequence(fresh: Callable[[], Deployment]) -> None:
    world = fresh()
    exits(world.release(world.script), 0)
    first = world.docker_log.read_bytes()
    world.docker_log.write_text("")
    exits(world.release(world.script), 0)
    assert world.docker_log.read_bytes() == first
