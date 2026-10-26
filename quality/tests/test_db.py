"""`scripts/db.sh` driven by a caller: the db-pin leg, the migration template, db.sh under zsh.

does-not-cover: whether the gate honours the leg's exit — the leg body's call line is asserted.
does-not-cover: which of two disagreeing names is right — the leg reports, never reads intent.
does-not-cover: a `DATABASE_NAME` from anywhere but the checkout's `.env` or the environment.
does-not-cover: a real `db_template_refresh` — the clone cases build their own one-table template.
does-not-cover: elapsed time — the `elapsed=` token is asserted present, never under a threshold.
does-not-cover: a real published template — the suite case publishes its own empty one.
does-not-cover: shells other than bash and zsh; the executables, which run under their own shebang.
does-not-cover: an unreachable SERVER under zsh — only a broken PATH inside `db_create` is planted.
"""

# deleted: test_the_leg_is_wired_into_the_fast_tier — dies with the shim
# pin: test_list_legs.py::test_the_full_fast_and_loop_leg_sequences_are_unchanged_by_the_refactor

from __future__ import annotations

import os
import secrets
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from quality.could_not_look import CouldNotLook
from quality.tests.fixtures.capture import Captured, run_to

pytestmark = pytest.mark.drives(
    ".github/workflows/ci.yml",
    "CLAUDE.md",
    "apps/*/apps.py",
    "apps/*/migrations/",
    "compose.yaml",
    "config/",
    "docs/product/build-contract.md",
    "manage.py",
    "quality/",
    "scripts/check.sh",
    "scripts/db.sh",
    "scripts/kill_mine.sh",
    "scripts/lifecycle.sh",
    "scripts/queue_cited.sh",
    "scripts/rung_start.sh",
    "scripts/setup.sh",
    "scripts/sweep.sh",
    "scripts/test.sh",
)

ROOT = Path(__file__).resolve().parents[2]
UNSET = (
    "DATABASE_NAME",
    "DATABASE_NAME_SOURCE",
    "DJB_DB_TEMPLATE",
    "DJB_TEST_DB_TEMPLATE",
    "DJANGO_SETTINGS_MODULE",
    "DB_TEMPLATE_CLONE_ATTEMPTS",
    "DB_TEMPLATE_CLONE_BACKOFF",
)
TAG = f"f6e{os.environ.get('PYTEST_XDIST_WORKER', 'gw')}{secrets.token_hex(3)}"
PRELUDE = (
    f"set -uo pipefail\nROOT={shlex.quote(str(ROOT))}\nTAG={TAG}\n"  # noqa: S608 — a shell script this test writes from quoted constants
    'DROP_IT() { db_query \'DROP DATABASE IF EXISTS :"name" WITH (FORCE)\' -v name="$1"; }\n'
    'CREATE_IT() { db_query \'CREATE DATABASE :"name" OWNER :"owner"\' '
    '-v name="$1" -v owner="$POSTGRES_USER"; }\n'
    "PROOF='CREATE TABLE the_proof (id int primary key); "
    "INSERT INTO the_proof VALUES (1),(2),(3);'\n"
)
SOURCED = 'cd "$ROOT" && . scripts/db.sh >/dev/null 2>&1\n'
WIDGET_MIGRATION = "class Migration:\n    dependencies = []\n"
TIED = (
    r"^[[:space:]]*(local|typeset|declare|export|readonly)[[:space:]]"
    r".*[[:space:]](path|status|options|fignore)="
)


@dataclass(frozen=True)
class Ran:
    """One run: its exit and both streams."""

    rc: int
    out: str


def ran_of(captured: Captured) -> Ran:
    """The capture as text, empty allowed — an empty transcript is a fact some cases assert."""
    return Ran(captured.rc, captured.path.read_text(errors="replace"))


@pytest.fixture(autouse=True)
def bare(monkeypatch: pytest.MonkeyPatch) -> None:
    """The names `.env` hands this process and db.sh reads, unset; compose pinned to this tree's."""
    for name in UNSET:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COMPOSE_FILE", str(ROOT / "compose.yaml"))


@pytest.fixture
def sh(capture: Callable[..., Captured]) -> Callable[..., Ran]:
    """`sh(body, *args, cwd=…, env=…)` runs `body` under bash with `$ROOT` and `$TAG` set."""

    def run(body: str, *args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> Ran:
        return ran_of(capture(["bash", "-c", PRELUDE + body, "drive", *args], cwd=cwd, env=env))

    return run


def query(body: str, *args: str) -> subprocess.CompletedProcess[str]:
    """One db.sh call against this tree's compose Postgres, streams kept apart."""
    env = {k: v for k, v in os.environ.items() if k not in UNSET}
    env["COMPOSE_FILE"] = str(ROOT / "compose.yaml")
    return subprocess.run(
        ["bash", "-c", PRELUDE + SOURCED + body, "drive", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def exists(name: str) -> bool:
    """Whether the server holds `name`, asked by db.sh's own `db_exists`."""
    return query('db_exists "$1"', name).returncode == 0


@pytest.fixture(scope="module")
def stack() -> bool:
    """Whether the compose Postgres answers, probed without the leg's own `db_reachable`."""
    return query("db_query 'SELECT 1' -tA").returncode == 0


def live(stack: bool) -> None:
    """Refuse to look without docker and the compose Postgres."""
    if shutil.which("docker") is None:
        raise CouldNotLook("no docker on PATH — the live half cannot look")
    if not stack:
        raise CouldNotLook(
            "the compose Postgres is not reachable — the live half cannot look "
            "(docker compose up -d db)"
        )


@pytest.fixture
def made() -> Iterator[list[str]]:
    """Names this test creates; each dropped at teardown, and nothing else."""
    names: list[str] = []
    yield names
    for name in names:
        query("""db_query 'DROP DATABASE IF EXISTS :"name" WITH (FORCE)' -v name="$1" """, name)


@dataclass
class Checkout:
    """A scratch checkout and the name db.sh derives in it."""

    path: Path
    derived: str

    def env(self, *lines: str) -> None:
        """Write `.env` as the given lines."""
        (self.path / ".env").write_text("".join(f"{line}\n" for line in lines))

    def env_line(self) -> str:
        """The last `DATABASE_NAME=` line of `.env`."""
        found = [
            line
            for line in (self.path / ".env").read_text().splitlines()
            if line.startswith("DATABASE_NAME=")
        ]
        return found[-1] if found else ""


def derive(path: Path) -> str:
    """`db_name` in `path`, nothing exported."""
    done = query('cd "$1" && db_name', str(path))
    return done.stdout.strip()


@pytest.fixture
def fresh(scratch_repo: Callable[..., Path]) -> Callable[[], Checkout]:
    """`fresh()` builds a numbered scratch checkout with one commit."""
    count = 0

    def build() -> Checkout:
        nonlocal count
        count += 1
        repo = scratch_repo(f"checkout{count}", "db pin drive")
        (repo / "README").write_text("a checkout\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "base")
        name = derive(repo)
        if not name:
            raise CouldNotLook("db_name derived nothing in a scratch checkout")
        return Checkout(repo, name)

    return build


def git(repo: Path, *args: str) -> str:
    """One git command in `repo`; its stdout."""
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout


LEG = SOURCED + 'cd "$1"\nDATABASE_NAME="$(db_name)"\nDATABASE_NAME_SOURCE=derived\n'


@pytest.fixture
def leg(sh: Callable[..., Ran]) -> Callable[..., Ran]:
    """`leg(checkout, mode)` runs `db_pin_leg` standing in the checkout, its derivation agreed."""

    def run(at: Checkout, mode: str = "fast", shim: Path | None = None) -> Ran:
        if shim is None:
            return sh(LEG + 'db_pin_leg "$2"', str(at.path), mode)
        return sh(LEG + 'PATH="$3:$PATH"\ndb_pin_leg "$2"', str(at.path), mode, str(shim))

    return run


@pytest.fixture
def docker_shim(scratch: Path) -> tuple[Path, Path]:
    """A `docker` that logs every call and fails: the directory and its log."""
    shim = scratch / "shim"
    shim.mkdir()
    log = shim / "docker-calls.log"
    log.write_text("")
    script = shim / "docker"
    script.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >>{shlex.quote(str(log))}\nexit 1\n")
    script.chmod(0o755)
    return shim, log


EXPORTED = (
    'cd "$ROOT"\nexport DATABASE_NAME="$3"\nunset DATABASE_NAME_SOURCE\n. scripts/db.sh\n'
    'cd "$1"\ndb_pin_leg "$2"'
)
REEXPORTED = (
    'cd "$1"\nunset DATABASE_NAME DATABASE_NAME_SOURCE\n. "$ROOT/scripts/db.sh"\n'
    'export DATABASE_NAME="$3"\ndb_pin_leg "$2"'
)
UNEXPORTED = (
    'cd "$1"\nunset DATABASE_NAME DATABASE_NAME_SOURCE\n. "$ROOT/scripts/db.sh"\ndb_pin_leg "$2"'
)


def make_database(name: str, made: list[str]) -> None:
    """Create `name` through `db_create`, owned by this test; `CouldNotLook` when refused."""
    if query('db_create "$1"', name).returncode != 0:
        raise CouldNotLook(f"could not create the decoy database {name}")
    made.append(name)


def awk(program: str, path: Path) -> str:
    """`awk program path`'s output."""
    return subprocess.run(["awk", program, str(path)], capture_output=True, text=True).stdout


@pytest.fixture(scope="module")
def setup_block() -> dict[str, str]:
    """setup.sh's pin block, its `env_set` and its env-sync fence, each extracted from the file."""
    setup = ROOT / "scripts" / "setup.sh"
    block = awk("/^db_pin_decide$/ { on = 1 } on && /^db_create$/ { exit } on { print }", setup)
    env_set = awk("/^env_set\\(\\) \\{$/ { on = 1 } on { print } on && /^}$/ { exit }", setup)
    fence = subprocess.run(
        ["sed", "-n", "/^# >>> env-sync >>>$/,/^# <<< env-sync <<<$/p", str(setup)],
        capture_output=True,
        text=True,
    ).stdout
    if not block:
        raise CouldNotLook("setup.sh has no column-zero db_pin_decide … db_create block to run")
    if not env_set:
        raise CouldNotLook("setup.sh defines no env_set() at column zero")
    if "env_sync_from_example() {" not in fence:
        raise CouldNotLook("setup.sh's env-sync fence defines no env_sync_from_example")
    return {"SETUP_BLOCK": block, "SETUP_ENV_SET": env_set, "SETUP_ENV_FENCE": fence}


SETUP_PRE = (
    'cd "$1"\nunset DATABASE_NAME DATABASE_NAME_SOURCE\n'
    'if [ -n "$2" ]; then export DATABASE_NAME="$2"; fi\n'
    '. "$ROOT/scripts/db.sh" 2>/dev/null\n'
    'SCRATCH="$3"\n'
    'make_tmp() { eval "$1=\\"\\$(mktemp \\"${SCRATCH}/envset.XXXXXX\\")\\""; }\n'
)
SETUP_RUN = (
    'eval "$SETUP_ENV_SET"\neval "$SETUP_BLOCK"\necho "block-left-DATABASE_NAME=${DATABASE_NAME}"'
)


@pytest.fixture
def setup_run(
    sh: Callable[..., Ran], setup_block: dict[str, str], scratch: Path
) -> Callable[..., Ran]:
    """`setup_run(checkout, exported, sync=False)`: setup.sh's own blocks, run in the checkout."""

    def run(at: Checkout, exported: str, sync: bool = False) -> Ran:
        middle = 'eval "$SETUP_ENV_FENCE"\nenv_sync_from_example\n' if sync else ""
        return sh(
            SETUP_PRE + middle + SETUP_RUN, str(at.path), exported, str(scratch), env=setup_block
        )

    return run


THREE_READERS = r"""
envfile="$1"
printf 'shell [%s]\n' "$(set -a; . "$envfile"; set +a; printf '%s' "${DATABASE_NAME:-}")"
py="${ROOT}/.venv/bin/python"
if [ -x "$py" ] && "$py" -c 'import environ' >/dev/null 2>&1; then
    printf 'environ [%s]\n' "$("$py" -c '
import os, sys, environ
os.environ.pop("DATABASE_NAME", None)
environ.Env.read_env(sys.argv[1], overwrite=True)
sys.stdout.write(os.environ.get("DATABASE_NAME", "<unset>"))
' "$envfile")"
else
    printf 'environ SKIP no .venv python with django-environ in this tree\n'
fi
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 &&
    docker run --rm --env-file "$envfile" alpine:3 true >/dev/null 2>&1; then
    printf 'docker [%s]\n' "$(docker run --rm --env-file "$envfile" alpine:3 \
        printenv DATABASE_NAME 2>/dev/null || true)"
else
    printf 'docker SKIP no usable docker (or alpine:3 unavailable) on this machine\n'
fi
"""


def readers(sh: Callable[..., Ran], envfile: Path) -> list[tuple[str, str]]:
    """Each reader of `envfile` as (reader, `[value]` or `SKIP <why>`)."""
    lines = sh(THREE_READERS, str(envfile)).out.splitlines()
    return [(line.split(" ", 1)[0], line.split(" ", 1)[1]) for line in lines if " " in line]


def without_mode_line(out: str) -> str:
    """The leg's transcript less its `db-pin mode:` line."""
    return "".join(
        line for line in out.splitlines(keepends=True) if not line.startswith("  db-pin mode: ")
    )


def assert_silent(ran: Ran) -> None:
    """Silent but for the leg's own mode line, which is owed on every run."""
    assert without_mode_line(ran.out) == "", ran.out
    assert "  db-pin mode: " in ran.out, ran.out


# --- the pin comparison (quality/tests/test_db.py) ---------------------------------


def test_a_stale_pin_is_refused(fresh: Callable[[], Checkout], leg: Callable[..., Ran]) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_main", "DEBUG=1")
    ran = leg(at)
    assert ran.rc == 1, ran.out
    for needle in ("djb_main", at.derived, "# pinned", "./scripts/setup.sh"):
        assert needle in ran.out, ran.out


def test_the_refusal_says_what_the_disagreement_costs(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_stale_pin")
    ran = leg(at)
    for needle in ("DISAGREE", "manage.py", "TWO databases"):
        assert needle in ran.out, ran.out


def test_setup_keeps_a_pinned_line_through_the_environment_step(
    fresh: Callable[[], Checkout], setup_run: Callable[..., Ran]
) -> None:
    at = fresh()
    (at.path / ".env.example").write_text(
        "# the database\nDATABASE_URL=\nDATABASE_NAME=\nDEBUG=0\n"
    )
    at.env("# the database", "DATABASE_URL=", "# pinned", "DATABASE_NAME=djb_stale", "DEBUG=1")
    before = (at.path / ".env").read_bytes()
    ran = setup_run(at, "", sync=True)
    assert ran.rc == 0, ran.out
    assert "DATABASE_NAME left alone" in ran.out, ran.out
    assert "overridden" not in ran.out, ran.out
    assert (at.path / ".env").read_bytes() == before


def test_setup_adopts_the_derivation_over_an_unmarked_exported_stale_pin(
    fresh: Callable[[], Checkout],
    setup_run: Callable[..., Ran],
    leg: Callable[..., Ran],
    stack: bool,
    made: list[str],
) -> None:
    at = fresh()
    at.env("DEBUG=1", "DATABASE_NAME=djb_stale")
    ran = setup_run(at, "djb_stale")
    assert ran.rc == 0, ran.out
    assert (
        "DATABASE_NAME: the unmarked .env pin djb_stale (also exported in this shell) "
        "was overridden "
        f'by the derivation {at.derived}; add "# pinned" above it to keep it'
    ) in ran.out, ran.out
    assert "unset DATABASE_NAME" in ran.out, ran.out
    assert f"block-left-DATABASE_NAME={at.derived}" in ran.out, ran.out
    assert at.env_line() == f"DATABASE_NAME={at.derived}"
    live(stack)
    make_database(at.derived, made)
    after = leg(at, "fast")
    assert after.rc == 0, after.out
    assert "DISAGREE" not in after.out, after.out
    full = leg(at, "full")
    assert full.rc == 0, full.out
    assert "DISAGREE" not in full.out, full.out


def test_setup_names_only_the_pin_when_nothing_is_exported(
    fresh: Callable[[], Checkout], setup_run: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_stale")
    ran = setup_run(at, "")
    assert ran.rc == 0, ran.out
    assert (
        "DATABASE_NAME: the unmarked .env pin djb_stale was overridden "
        f"by the derivation {at.derived}; "
        'add "# pinned" above it to keep it'
    ) in ran.out, ran.out
    assert "also exported" not in ran.out, ran.out
    assert f"block-left-DATABASE_NAME={at.derived}" in ran.out, ran.out


def test_setup_leaves_a_pinned_line_alone(
    fresh: Callable[[], Checkout], setup_run: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("# pinned", "DATABASE_NAME=djb_stale")
    before = (at.path / ".env").read_bytes()
    ran = setup_run(at, "djb_stale")
    assert ran.rc == 0, ran.out
    assert "DATABASE_NAME left alone" in ran.out, ran.out
    assert "overridden" not in ran.out, ran.out
    assert "block-left-DATABASE_NAME=djb_stale" in ran.out, ran.out
    assert (at.path / ".env").read_bytes() == before


def ingredient_lines(text: str) -> list[str]:
    """Code lines of `text` that ask an ingredient of the pin decision table."""
    needles = (
        "db_pin_marked",
        "db_pin_line_has_inline_comment",
        "db_env_file_pin",
        "DB_PIN_MARKER_ERE",
        "#[[:space:]]*pinned",
    )
    passed = (
        'DB_PIN_MARKER_ERE="$DB_PIN_MARKER_ERE"',
        "DB_PIN_MARKER_ERE:-",
        'ENVIRON["DB_PIN_MARKER_ERE"]',
    )
    return [
        line
        for line in text.splitlines()
        if any(n in line for n in needles)
        and not line.lstrip().startswith("#")
        and not any(p in line for p in passed)
    ]


def test_setup_and_the_leg_read_one_decision_table() -> None:
    for reader in ("setup.sh", "rung_start.sh"):
        text = (ROOT / "scripts" / reader).read_text()
        assert "db_pin_decide" in text.splitlines(), f"{reader} never calls db_pin_decide"
        assert ingredient_lines(text) == [], f"{reader} asks an ingredient of the table itself"
    body = awk(
        "/^db_pin_leg\\(\\) \\{$/ { on = 1 } on { print } on && /^}$/ { exit }",
        ROOT / "scripts" / "db.sh",
    )
    assert "db_pin_decide" in body
    code = [line for line in body.splitlines() if not line.lstrip().startswith("#")]
    asks = ("db_pin_marked", "db_pin_line_has_inline_comment", "db_env_file_pin")
    assert not [line for line in code if any(a in line for a in asks)]


def test_setup_creates_after_the_name_is_settled() -> None:
    lines = (ROOT / "scripts" / "setup.sh").read_text().splitlines()
    decide = lines.index("db_pin_decide") if "db_pin_decide" in lines else -1
    create = lines.index("db_create") if "db_create" in lines else -1
    assert decide >= 0 and create > decide, (
        f"db_create at {create + 1}, db_pin_decide at {decide + 1}"
    )


def test_a_pinned_line_passes_silently(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("# pinned", "DATABASE_NAME=djb_main", "DEBUG=1")
    ran = leg(at)
    assert ran.rc == 0, ran.out
    assert_silent(ran)


def test_the_marker_carries_a_reason_and_still_passes(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("# pinned — the owner's live development database", "DATABASE_NAME=djb_main", "DEBUG=1")
    ran = leg(at)
    assert ran.rc == 0, ran.out
    assert_silent(ran)


def test_the_marker_must_be_directly_above_the_database_name_line(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env(
        "# pinned — a comment about something else entirely",
        "REDIS_URL=redis://localhost",
        "DATABASE_NAME=djb_main",
    )
    ran = leg(at)
    assert ran.rc == 1, ran.out
    assert at.derived in ran.out, ran.out
    second = fresh()
    second.env("# pinned", f"DATABASE_NAME={second.derived}", "DATABASE_NAME=djb_stale_second")
    ran = leg(second)
    assert ran.rc == 1, ran.out
    assert "djb_stale_second" in ran.out, ran.out


def test_the_inline_form_is_refused(fresh: Callable[[], Checkout], leg: Callable[..., Ran]) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_main  # pinned", "DEBUG=1")
    ran = leg(at)
    assert ran.rc == 1, ran.out
    for needle in ("INLINE COMMENT", "# pinned", "DATABASE_NAME=djb_main"):
        assert needle in ran.out, ran.out
    trailing = [
        line
        for line in ran.out.splitlines()
        if line.strip() == "DATABASE_NAME=djb_main" and line != line.rstrip()
    ]
    assert trailing == [], "the suggested rewrite has trailing whitespace"


def test_an_inline_comment_that_agrees_is_still_refused(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}  # pinned")
    ran = leg(at)
    assert ran.rc == 1, ran.out
    assert "INLINE COMMENT" in ran.out, ran.out
    assert "agree" not in ran.out, ran.out


def test_any_inline_comment_is_refused_not_only_the_marker(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_main # temporary, see the runbook")
    ran = leg(at)
    assert ran.rc == 1, ran.out
    assert "INLINE COMMENT" in ran.out, ran.out


def test_the_new_form_reads_identically_for_every_reader(
    sh: Callable[..., Ran], scratch: Path
) -> None:
    envfile = scratch / "three-readers-new.env"
    envfile.write_text("# pinned\nDATABASE_NAME=djb_three_readers\n")
    posed = [
        (reader, value) for reader, value in readers(sh, envfile) if not value.startswith("SKIP")
    ]
    for reader, value in posed:
        assert value == "[djb_three_readers]", f"{reader} reads {value}"
    assert len(posed) >= 2, f"only {len(posed)} reader could be posed — agreement needs two"


def test_the_old_form_still_splits_the_readers(sh: Callable[..., Ran], scratch: Path) -> None:
    envfile = scratch / "three-readers-old.env"
    envfile.write_text("DATABASE_NAME=djb_three_readers  # pinned\n")
    posed = [
        (reader, value) for reader, value in readers(sh, envfile) if not value.startswith("SKIP")
    ]
    dirty = [reader for reader, value in posed if value != "[djb_three_readers]"]
    assert dirty, f"every reader posed stripped the comment: {posed}"


def test_no_env_file_at_all_passes(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], docker_shim: tuple[Path, Path]
) -> None:
    at = fresh()
    (at.path / ".env").unlink(missing_ok=True)
    ran = leg(at, "fast", docker_shim[0])
    assert ran.rc == 0, ran.out
    assert "no .env" in ran.out, ran.out


def test_an_env_with_no_database_name_line_passes(
    fresh: Callable[[], Checkout],
    leg: Callable[..., Ran],
    docker_shim: tuple[Path, Path],
) -> None:
    at = fresh()
    at.env("DEBUG=1", "REDIS_URL=redis://localhost")
    ran = leg(at, "fast", docker_shim[0])
    assert ran.rc == 0, ran.out
    assert "pins no DATABASE_NAME" in ran.out, ran.out


def test_a_pin_that_agrees_passes(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], docker_shim: tuple[Path, Path]
) -> None:
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    ran = leg(at, "fast", docker_shim[0])
    assert ran.rc == 0, ran.out
    assert "agree" in ran.out, ran.out


def test_a_pin_that_agrees_and_is_marked_passes(
    fresh: Callable[[], Checkout],
    leg: Callable[..., Ran],
    docker_shim: tuple[Path, Path],
) -> None:
    at = fresh()
    at.env("# pinned", f"DATABASE_NAME={at.derived}")
    ran = leg(at, "fast", docker_shim[0])
    assert ran.rc == 0, ran.out


def test_a_quoted_pin_that_agrees_passes(
    fresh: Callable[[], Checkout],
    leg: Callable[..., Ran],
    docker_shim: tuple[Path, Path],
) -> None:
    for quote in ('"', "'"):
        at = fresh()
        at.env(f"DATABASE_NAME={quote}{at.derived}{quote}")
        ran = leg(at, "fast", docker_shim[0])
        assert ran.rc == 0, ran.out
        assert "agree" in ran.out, ran.out


def test_the_last_database_name_line_wins(
    fresh: Callable[[], Checkout],
    leg: Callable[..., Ran],
    docker_shim: tuple[Path, Path],
) -> None:
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DATABASE_NAME=djb_stale_second")
    ran = leg(at, "fast", docker_shim[0])
    assert ran.rc == 1, ran.out
    assert "djb_stale_second" in ran.out, ran.out
    good = fresh()
    good.env("DATABASE_NAME=djb_stale_first", f"DATABASE_NAME={good.derived}")
    ran = leg(good, "fast", docker_shim[0])
    assert ran.rc == 0, ran.out
    assert "agree" in ran.out, ran.out


def test_an_unreadable_env_cannot_look(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran]
) -> None:
    if os.geteuid() == 0:
        return  # why-not: root reads any mode, so chmod cannot pose the case
    at = fresh()
    at.env("DATABASE_NAME=djb_main")
    (at.path / ".env").chmod(0)
    ran = leg(at)
    (at.path / ".env").chmod(0o600)
    assert ran.rc == 2, ran.out
    assert "cannot be read" in ran.out, ran.out


SOURCE_ONLY = 'cd "$1"\nunset DATABASE_NAME\n. "$ROOT/scripts/db.sh"'


def test_the_source_time_note_points_at_the_leg(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_main")
    ran = sh(SOURCE_ONLY, str(at.path))
    assert ran.rc == 0, ran.out
    for needle in ("note: DATABASE_NAME pinned to djb_main", "db-pin leg", "check.sh"):
        assert needle in ran.out, ran.out


STEP_ENV = (
    SOURCE_ONLY + ' 2>&1\npython3 -c \'import os; print("step:", os.environ["DATABASE_NAME"],'
    ' os.environ["DATABASE_NAME_SOURCE"])\'\n'
    'db_pin_decide\ndb_pin_effective_name "$DB_PIN_VALUE" ".env pin"\n'
    'echo "leg: $DB_EFFECTIVE_NAME $DB_EFFECTIVE_SOURCE"\n'
)


def test_a_marked_pin_is_the_name_every_step_receives(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("# pinned", "DATABASE_NAME=djb_dbpin_kept", "DEBUG=1")
    ran = sh(STEP_ENV, str(at.path))
    assert ran.rc == 0, ran.out
    assert "step: djb_dbpin_kept .env pin" in ran.out, ran.out
    assert "leg: djb_dbpin_kept .env pin" in ran.out, ran.out
    assert f"derivation says {at.derived} — every step opens djb_dbpin_kept" in ran.out, ran.out


def test_a_marked_pin_wins_over_an_inherited_derivation_and_loses_to_an_export(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env("# pinned", "DATABASE_NAME=djb_dbpin_kept")
    inherited = f"DATABASE_NAME={at.derived}\nDATABASE_NAME_SOURCE=derived\nexport DATABASE_NAME\n"
    ran = sh(STEP_ENV.replace("unset DATABASE_NAME\n", inherited), str(at.path))
    assert "step: djb_dbpin_kept .env pin" in ran.out, ran.out
    ran = sh(
        STEP_ENV.replace("unset DATABASE_NAME\n", "export DATABASE_NAME=djb_other\n"), str(at.path)
    )
    assert "step: djb_other DATABASE_NAME exported" in ran.out, ran.out


def test_the_note_stays_off_stdout(fresh: Callable[[], Checkout]) -> None:
    at = fresh()
    at.env("DATABASE_NAME=djb_main")
    done = subprocess.run(
        ["bash", "-c", PRELUDE + SOURCE_ONLY, "drive", str(at.path)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert done.stdout == "", f"the note reached stdout — {done.stdout}"


# --- the existence half, and the mode that decides whether it is asked ------------------


def test_under_loop_an_absent_database_is_exit_2_naming_setup(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], stack: bool
) -> None:
    live(stack)
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    ran = leg(at, "loop")
    assert ran.rc == 2, ran.out
    for needle in ("does not exist", at.derived, "./scripts/setup.sh", "db-pin mode: loop"):
        assert needle in ran.out, ran.out
    assert "COULD NOT LOOK" not in ran.out, ran.out


def test_under_full_the_same_refusal(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], stack: bool
) -> None:
    live(stack)
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    ran = leg(at, "full")
    assert ran.rc == 2, ran.out
    for needle in ("does not exist", at.derived, "./scripts/setup.sh", "db-pin mode: full"):
        assert needle in ran.out, ran.out


def test_under_loop_a_present_database_says_so(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], stack: bool, made: list[str]
) -> None:
    live(stack)
    present = f"djb_dbpin_present_{TAG}"
    make_database(present, made)
    at = fresh()
    at.env(
        "# pinned — a database this test made, so the leg has something to find",
        f"DATABASE_NAME={present}",
    )
    ran = leg(at, "loop")
    assert ran.rc == 0, ran.out
    assert f"database {present} exists" in ran.out, ran.out
    assert "does not exist" not in ran.out, ran.out


def test_under_fast_existence_is_not_asked_of_a_pin_that_differs_and_says_so(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], docker_shim: tuple[Path, Path]
) -> None:
    shim, log = docker_shim
    at = fresh()
    at.env("# pinned", "DATABASE_NAME=djb_dbpin_elsewhere", "DEBUG=1")
    ran = leg(at, "fast", shim)
    assert ran.rc == 0, ran.out
    assert "existence asked of the derived name only" in ran.out, ran.out
    assert "does not exist" not in ran.out, ran.out
    assert "COULD NOT LOOK" not in ran.out, ran.out
    assert log.read_text() == "", f"the docker shim WAS called under fast: {log.read_text()}"


def test_an_unreachable_stack_under_loop_is_could_not_look(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], docker_shim: tuple[Path, Path]
) -> None:
    shim, log = docker_shim
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    ran = leg(at, "loop", shim)
    assert ran.rc == 2, ran.out
    for needle in ("COULD NOT LOOK", "docker", "db-pin mode: loop"):
        assert needle in ran.out, ran.out
    assert "does not exist" not in ran.out, ran.out
    assert log.read_text() != "", "the shim recorded nothing — the leg never tried to look"


def test_an_exported_database_name_is_the_one_asked_about(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran], stack: bool, made: list[str]
) -> None:
    live(stack)
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    make_database(at.derived, made)
    ran = sh(EXPORTED, str(at.path), "loop", "djb_vg1r_does_not_exist")
    assert ran.rc == 2, ran.out
    for needle in (
        "djb_vg1r_does_not_exist",
        "does not exist",
        "DATABASE_NAME exported",
        "unset DATABASE_NAME",
    ):
        assert needle in ran.out, ran.out
    assert f"{at.derived} exists" not in ran.out, ran.out
    present = f"djb_dbpin_exported_{TAG}"
    make_database(present, made)
    control = fresh()
    control.env(f"DATABASE_NAME={control.derived}", "DEBUG=1")
    ran = sh(EXPORTED, str(control.path), "loop", present)
    assert ran.rc == 0, ran.out
    assert f"database {present} exists (DATABASE_NAME exported)" in ran.out, ran.out


def test_a_pinned_absent_name_names_the_pin_and_its_remedy(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran], stack: bool
) -> None:
    live(stack)
    at = fresh()
    at.env(
        "# pinned — deliberate, and not this checkout's derivation",
        "DATABASE_NAME=djb_g4f2_pinned_absent",
    )
    ran = sh(UNEXPORTED, str(at.path), "loop")
    assert ran.rc == 2, ran.out
    for needle in (
        "djb_g4f2_pinned_absent",
        ".env pin",
        at.derived,
        "the pin DIFFERS from the derivation",
        "A bare `./scripts/setup.sh` creates and migrates djb_g4f2_pinned_absent",
        "pinned",
    ):
        assert needle in ran.out, ran.out
    assert "The pin and the derivation agree on the NAME" not in ran.out, ran.out
    assert "DATABASE_NAME=djb_g4f2_pinned_absent ./scripts/setup.sh" not in ran.out, ran.out


def test_a_re_exported_name_after_sourcing_is_asked_about(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran], stack: bool, made: list[str]
) -> None:
    live(stack)
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    make_database(at.derived, made)
    ran = sh(REEXPORTED, str(at.path), "loop", "djb_g4f2_reexported_absent")
    assert ran.rc == 2, ran.out
    for needle in (
        "djb_g4f2_reexported_absent",
        "DATABASE_NAME exported",
        "does not match this checkout's derivation",
        "inherited DATABASE_NAME_SOURCE label",
    ):
        assert needle in ran.out, ran.out
    assert f"{at.derived} exists" not in ran.out, ran.out
    ran = sh(UNEXPORTED, str(at.path), "loop")
    assert ran.rc == 0, ran.out
    assert f"database {at.derived} exists (derived)" in ran.out, ran.out
    assert "does not match this checkout's derivation" not in ran.out, ran.out


CHILD_PARENT = 'cd "$1"\nunset DATABASE_NAME DATABASE_NAME_SOURCE\n. "$ROOT/scripts/db.sh"\n'


def test_a_child_process_with_a_new_name_is_asked_about_that_name(
    fresh: Callable[[], Checkout],
    sh: Callable[..., Ran],
    stack: bool,
    made: list[str],
    scratch: Path,
) -> None:
    live(stack)
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}", "DEBUG=1")
    make_database(at.derived, made)
    child = scratch / "child-newname.sh"
    child.write_text('. "${1}/scripts/db.sh"\ndb_pin_leg loop\n')
    ran = sh(
        CHILD_PARENT + 'DATABASE_NAME=djb_g4f3_child_absent bash "$2" "$ROOT"',
        str(at.path),
        str(child),
    )
    assert ran.rc == 2, ran.out
    for needle in (
        "djb_g4f3_child_absent",
        "DATABASE_NAME exported",
        "does not match this checkout's derivation",
    ):
        assert needle in ran.out, ran.out
    assert f"{at.derived} exists" not in ran.out, ran.out
    ran = sh(CHILD_PARENT + 'bash "$2" "$ROOT"', str(at.path), str(child))
    assert ran.rc == 0, ran.out
    assert f"database {at.derived} exists (derived)" in ran.out, ran.out
    assert "does not match this checkout's derivation" not in ran.out, ran.out


def test_the_existence_line_names_its_source(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran], stack: bool, made: list[str]
) -> None:
    live(stack)
    at = fresh()
    (at.path / ".env").unlink(missing_ok=True)
    ran = sh(UNEXPORTED, str(at.path), "loop")
    assert ran.rc == 2, ran.out
    assert "(derived)" in ran.out, ran.out
    assert "DATABASE_NAME exported" not in ran.out, ran.out
    present = f"djb_dbpin_named_{TAG}"
    make_database(present, made)
    pinned = fresh()
    pinned.env("# pinned — a deliberate name", f"DATABASE_NAME={present}")
    ran = sh(UNEXPORTED, str(pinned.path), "loop")
    assert ran.rc == 0, ran.out
    assert f"database {present} exists (.env pin)" in ran.out, ran.out
    db_sh = (ROOT / "scripts" / "db.sh").read_text().splitlines()
    decisions = [
        line for line in db_sh if line.lstrip().startswith('DATABASE_NAME="${DATABASE_NAME:-')
    ]
    assert len(decisions) == 1, f"db.sh decides the precedence in {len(decisions)} places"
    assert "DATABASE_NAME_SOURCE" in "\n".join(db_sh)


def test_the_mode_is_printed_on_every_run(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], docker_shim: tuple[Path, Path]
) -> None:
    stale = fresh()
    stale.env("DATABASE_NAME=djb_definitely_stale", "DEBUG=1")
    ran = leg(stale, "fast")
    assert ran.rc == 1, ran.out
    assert "db-pin mode: fast" in ran.out, ran.out
    bare_one = fresh()
    (bare_one.path / ".env").unlink(missing_ok=True)
    ran = leg(bare_one, "fast", docker_shim[0])
    assert ran.rc == 0, ran.out
    assert "db-pin mode: fast" in ran.out, ran.out
    pinned = fresh()
    pinned.env("# pinned", "DATABASE_NAME=djb_main")
    ran = leg(pinned, "fast")
    assert ran.rc == 0, ran.out
    assert "db-pin mode: fast" in ran.out, ran.out
    agreed = fresh()
    agreed.env(f"DATABASE_NAME={agreed.derived}")
    ran = leg(agreed, "loop", docker_shim[0])
    assert "db-pin mode: loop" in ran.out, ran.out


def test_a_missing_or_unknown_mode_is_exit_2(
    fresh: Callable[[], Checkout], sh: Callable[..., Ran]
) -> None:
    at = fresh()
    at.env(f"DATABASE_NAME={at.derived}")
    ran = sh(SOURCED + 'cd "$1" && db_pin_leg', str(at.path))
    assert ran.rc == 2, ran.out
    assert "no mode" in ran.out, ran.out
    assert "fast, loop or full" in ran.out, ran.out
    ran = sh(SOURCED + 'cd "$1" && db_pin_leg "--loop"', str(at.path))
    assert ran.rc == 2, ran.out
    assert "unknown mode" in ran.out, ran.out
    assert "fast, loop or full" in ran.out, ran.out
    assert "agree" not in ran.out, ran.out


@pytest.mark.parametrize("mode", ["fast", "loop", "full"])
def test_the_db_pin_leg_passes_its_mode(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from quality.djb import registry as R
    from quality.djb.legs import db_pin

    asked: list[str] = []

    def library(ctx: R.Ctx, script: str) -> tuple[int, str]:
        asked.append(script)
        return 0, ""

    monkeypatch.setattr(db_pin, "library", library)
    assert db_pin.run(R.Ctx(ROOT, mode, {})) == 0
    assert asked == [f"db_pin_leg {mode}"]


# --- one checkout, one name: another checkout's name is refused (FF-PIN-1) ----------------

TWO_CLONES = (
    'for d in "$1" "$2"; do cd "$d" && . scripts/db.sh >/dev/null; '
    'echo "== ${d##*/}: DATABASE_NAME=${DATABASE_NAME:-unset}"; done'
)
FOREIGN_HASH = "0badf00d"
FOREIGN = f"djb_main_{FOREIGN_HASH}"
EXPORTED_FOREIGN = (
    'cd "$1"\nexport DATABASE_NAME="$3"\nexport DATABASE_NAME_SOURCE="DATABASE_NAME exported"\n'
    '. "$ROOT/scripts/db.sh"\ndb_pin_leg "$2"'
)


def foreign_line(name: str, digest: str, derived: str) -> str:
    """The sentence db.sh prints for a name another checkout derived, after its leader."""
    return (
        f"DATABASE_NAME {name} was derived for another checkout ({digest}); "
        f"this checkout derives {derived}"
    )


def test_two_verifier_clones_derive_two_names(
    scratch_repo: Callable[..., Path], scratch: Path, sh: Callable[..., Ran]
) -> None:
    source = scratch_repo("clonesource", "two verifier clones")
    (source / "scripts").mkdir()
    for name in ("db.sh", "gate_refuse.sh"):
        shutil.copyfile(ROOT / "scripts" / name, source / "scripts" / name)
    git(source, "add", "-A")
    git(source, "commit", "-q", "-m", "base")
    sha = git(source, "rev-parse", "HEAD").strip()
    clones = [scratch / "v-push1" / "clone", scratch / "v-push1" / "clone2"]
    for clone in clones:
        subprocess.run(["git", "clone", "-q", str(source), str(clone)], check=True)
        git(clone, "checkout", "-q", sha)
    ran = sh(TWO_CLONES, *map(str, clones))
    names = [line.split("DATABASE_NAME=", 1)[1] for line in ran.out.splitlines() if "== " in line]
    own = [derive(clone) for clone in clones]
    assert names == own, ran.out
    assert names[0] != names[1], ran.out
    digest = names[0].rsplit("_", 1)[1]
    assert foreign_line(names[0], digest, own[1]) in ran.out, ran.out


@pytest.mark.parametrize("mode", ["fast", "loop", "full"])
def test_a_pin_from_another_checkout_is_refused(
    mode: str, fresh: Callable[[], Checkout], sh: Callable[..., Ran]
) -> None:
    at = fresh()
    line = foreign_line(FOREIGN, FOREIGN_HASH, at.derived)
    ran = sh(EXPORTED_FOREIGN, str(at.path), mode, FOREIGN)
    assert ran.rc == 1, ran.out
    assert ran.out.count(f"!! {line}") == 1, ran.out
    assert ran.out.count(f"RED: {line}") == 1, ran.out
    for env in ([f"DATABASE_NAME={FOREIGN}"], ["# pinned", f"DATABASE_NAME={FOREIGN}"]):
        at.env(*env)
        ran = sh(UNEXPORTED, str(at.path), mode)
        assert ran.rc == 1, ran.out
        assert line in ran.out, ran.out
        assert "unset DATABASE_NAME" not in ran.out, ran.out
    own = fresh()
    own.env("# pinned", "DATABASE_NAME=djb_main_0badf00dd")
    assert sh(UNEXPORTED, str(own.path), "fast").rc == 0


def test_fast_says_an_absent_database_first_and_passes(
    fresh: Callable[[], Checkout], leg: Callable[..., Ran], stack: bool
) -> None:
    live(stack)
    at = fresh()
    git(at.path, "checkout", "-q", "-b", f"pm/fresh_{TAG}")
    name = derive(at.path)
    assert name != at.derived and name.startswith("djb_pm_fresh_"), name
    at.env(f"DATABASE_NAME={name}")
    started = time.monotonic()
    ran = leg(Checkout(at.path, name), "fast")
    took = time.monotonic() - started
    assert ran.rc == 0, ran.out
    assert [line for line in ran.out.splitlines() if line.startswith("!!")] == [], ran.out
    said = f"  database {name} does not exist (derived) — --fast needs none; ./scripts/setup.sh"
    assert said in ran.out, ran.out
    assert took < 5, f"{took:.1f}s\n{ran.out}"


def test_db_pin_is_the_first_fast_leg_to_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from quality.djb import cli
    from quality.djb import registry as R

    real = R.load(ROOT)
    answered: list[str] = []

    def stub(name: str) -> Callable[[R.Ctx], int]:
        def body(ctx: R.Ctx) -> int:
            answered.append(name)
            return 1 if name == "db-pin" else 0

        return body

    legs = tuple(replace(g, body=stub(g.name)) for g in real.legs)
    monkeypatch.setattr(cli, "table", lambda root: replace(real, legs=legs))
    monkeypatch.setattr(cli, "refuse_if_locked", lambda root: None)
    monkeypatch.delenv("DJB_GATE_LEGS_DRY", raising=False)
    assert cli.run_fast(ROOT, ()) == 1
    assert "migrations" not in answered, answered
    assert answered == ["db-pin"], answered


def test_fast_hands_its_legs_the_derived_name_when_nothing_names_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from quality.djb import cli
    from quality.djb import registry as R

    real = R.load(ROOT)
    seen: list[tuple[str | None, str | None]] = []

    def body(ctx: R.Ctx) -> int:
        seen.append((ctx.env.get("DATABASE_NAME"), ctx.env.get("DATABASE_NAME_SOURCE")))
        return 0

    legs = tuple(replace(g, body=body) for g in real.legs if g.name in ("db-pin", "sdk-reference"))
    monkeypatch.setattr(cli, "table", lambda root: replace(real, legs=legs, local=()))
    monkeypatch.setattr(cli, "refuse_if_locked", lambda root: None)
    monkeypatch.delenv("DJB_GATE_LEGS_DRY", raising=False)
    for name in ("DATABASE_NAME", "DATABASE_NAME_SOURCE", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    resolved = subprocess.run(
        ["bash", "-c", '. scripts/gate_refuse.sh && . scripts/db.sh && printf %s "$DATABASE_NAME"'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in UNSET},
    ).stdout
    assert resolved.startswith("djb_"), resolved
    assert cli.run_fast(ROOT, ()) == 0
    assert [name for name, _ in seen] == [resolved, resolved], seen
    assert {label for _, label in seen} <= {"derived", ".env pin"}, seen
    seen.clear()
    monkeypatch.setenv("DATABASE_URL", "postgres://u@h/named_by_the_url")
    assert cli.run_fast(ROOT, ()) == 0
    assert seen == [(None, None), (None, None)], seen


def test_fast_asks_existence_when_a_leg_will_open_it(
    fresh: Callable[[], Checkout],
    leg: Callable[..., Ran],
    docker_shim: tuple[Path, Path],
    stack: bool,
    made: list[str],
) -> None:
    shim, log = docker_shim
    marked = fresh()
    marked.env("# pinned", "DATABASE_NAME=djb_dbpin_elsewhere")
    ran = leg(marked, "fast", shim)
    assert ran.rc == 0, ran.out
    stale = fresh()
    stale.env("DATABASE_NAME=djb_dbpin_stale")
    ran = leg(stale, "fast", shim)
    assert ran.rc == 1 and "DISAGREE" in ran.out, ran.out
    assert log.read_text() == "", f"existence was asked of a pin that disagrees: {log.read_text()}"
    down = fresh()
    down.env(f"DATABASE_NAME={down.derived}")
    ran = leg(down, "fast", shim)
    assert ran.rc == 0, ran.out
    assert "the compose Postgres did not answer" in ran.out, ran.out
    assert log.read_text() != "", "an agreeing pin under fast never asked the server"
    live(stack)
    ran = leg(down, "fast")
    assert ran.rc == 0, ran.out
    assert f"database {down.derived} does not exist (derived)" in ran.out, ran.out
    make_database(down.derived, made)
    ran = leg(down, "fast")
    assert ran.rc == 0, ran.out
    assert f"database {down.derived} exists (derived)" in ran.out, ran.out
    block = (ROOT / "scripts" / "db.sh").read_text()
    assert "db_pin_leg fast    asked only when the pin and the derivation agree" in block


# --- the template database (quality/tests/test_db.py) ---------------------------


@pytest.fixture
def migrations(scratch_repo: Callable[..., Path]) -> Callable[[], Path]:
    """`migrations()` builds a numbered scratch checkout carrying one app's migration files."""
    count = 0

    def build() -> Path:
        nonlocal count
        count += 1
        repo = scratch_repo(f"migrations{count}", "db-template-drive")
        folder = repo / "apps" / "widgets" / "migrations"
        folder.mkdir(parents=True)
        (folder / "0001_initial.py").write_text(WIDGET_MIGRATION)
        (folder / "__init__.py").write_text("")
        (repo / "apps" / "widgets" / "models.py").write_text("WIDGET = 1\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "the migrations")
        return repo

    return build


def key_in(path: Path) -> str:
    """`db_migration_key` in `path`."""
    return query('cd "$1" && db_migration_key', str(path)).stdout.strip()


def test_a_new_migration_moves_the_key(migrations: Callable[[], Path]) -> None:
    repo = migrations()
    before = key_in(repo)
    assert before, "db_migration_key derived nothing over a checkout with a migration in it"
    (repo / "apps/widgets/migrations/0002_more.py").write_text(
        'class Migration:\n    dependencies = [("widgets", "0001_initial")]\n'
    )
    assert key_in(repo) != before


def test_editing_a_migration_moves_the_key(migrations: Callable[[], Path]) -> None:
    repo = migrations()
    before = key_in(repo)
    (repo / "apps/widgets/migrations/0001_initial.py").write_text(
        WIDGET_MIGRATION + "    atomic = False\n"
    )
    assert key_in(repo) != before


def test_removing_a_migration_moves_the_key(migrations: Callable[[], Path]) -> None:
    repo = migrations()
    extra = repo / "apps/widgets/migrations/0002_more.py"
    extra.write_text(WIDGET_MIGRATION)
    before = key_in(repo)
    extra.unlink()
    assert key_in(repo) != before


def test_a_non_migration_edit_does_not_move_the_key(migrations: Callable[[], Path]) -> None:
    repo = migrations()
    before = key_in(repo)
    (repo / "apps/widgets/models.py").write_text(
        'WIDGET = 2\nEXTRA = "a whole new model, no migration yet"\n'
    )
    (repo / "apps/widgets/services.py").write_text("a service\n")
    (repo / "README.md").write_text("a doc\n")
    assert key_in(repo) == before


def test_the_key_is_the_same_wherever_the_checkout_lives(migrations: Callable[[], Path]) -> None:
    one, two = migrations(), migrations()
    assert key_in(one) == key_in(two)
    assert derive(one) != derive(two)


def test_db_name_for_is_db_name_of_that_checkout(migrations: Callable[[], Path]) -> None:
    repo = migrations()
    top = git(repo, "rev-parse", "--show-toplevel").strip()
    name_for = 'db_name_for "$1" "$2" 2>&1'
    assert derive(repo) == query(name_for, "main", top).stdout
    git(repo, "checkout", "-q", "-b", "Feature/Odd.Name")
    assert derive(repo) == query(name_for, "Feature/Odd.Name", top).stdout
    homes = (ROOT / "scripts" / "db.sh").read_text().count("printf 'djb_%s_%s'")
    assert homes == 1, f"the derivation's printf has {homes} homes"


def test_a_checkout_with_no_migrations_derives_no_key(scratch_repo: Callable[..., Path]) -> None:
    repo = scratch_repo("bare", "db-template-drive")
    done = query('cd "$1" && db_migration_key >/dev/null 2>&1', str(repo))
    assert done.returncode != 0, "a checkout with no migrations derived a key"


def test_the_template_name_is_the_key_and_a_legal_database_name(
    migrations: Callable[[], Path],
) -> None:
    repo = migrations()
    name = query('cd "$1" && db_template_name', str(repo)).stdout.strip()
    assert name == f"djb_tmpl_{key_in(repo)}"
    assert query('db_valid_name "$1"', name).returncode == 0


LIFECYCLE = 'set +u\n. "$ROOT/scripts/lifecycle.sh" >/dev/null 2>&1 || true\n'


def test_the_template_is_its_own_lifecycle_class(sh: Callable[..., Ran]) -> None:
    for name in ("djb_tmpl_0123456789abcdef", "djb_tmpl_0123456789abcdef_mkab12cd"):
        claimed = sh(LIFECYCLE + 'lc_class_of database "$1" 2>/dev/null', name)
        assert claimed.out.strip() == "migration-template", claimed.out
    checkout = sh(LIFECYCLE + 'lc_claim_checkout_database "$1"', "djb_tmpl_0123456789abcdef")
    assert checkout.rc != 0, "the checkout-database class claims the template"


REFUSED_CREATE = (
    SOURCED + "set +e\n"
    "db_query() { return 1; }\n"
    'name="djb_drive_never_${TAG}"\n'
    '[ "$1" = plain ] || name="$(cd "$ROOT" && db_name)"\n'
    'if [ "$1" = escape ]; then DJB_DB_TEMPLATE=off; fi\n'
    'cd "$ROOT" && db_create "${name:0:63}"'
)


def test_db_create_returns_psqls_failure_on_every_path(sh: Callable[..., Ran]) -> None:
    for label in ("plain", "template", "escape"):
        ran = sh(REFUSED_CREATE, label)
        assert ran.rc != 0, f"{label}: a refused CREATE returned 0: {ran.out}"
        refused = [line for line in ran.out.splitlines() if line.startswith("created database")]
        assert refused == [], f"{label}: {ran.out}"


def psql_on(database: str, sql: str) -> str:
    """`sql` run on `database` as the compose superuser; its tuples-only output, or `unreadable`."""
    done = query(
        'printf "%s" "$2" | docker compose exec -T db '
        'psql -tA -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"',
        database,
        sql,
    )
    return "".join(done.stdout.split()) if done.returncode == 0 else "unreadable"


@pytest.fixture(scope="module")
def template_source(stack: bool) -> Iterator[str]:
    """A one-table template allowing no connections, built for this worker and dropped after."""
    live(stack)
    src = f"djb_tmpl_ffffffffffffffff_mk{TAG}"[:63]
    built = query(
        """DROP_IT "$1" >/dev/null 2>&1 || true
CREATE_IT "$1" >/dev/null || exit 1
printf '%s' "$PROOF" |
    docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" \\
    >/dev/null || exit 1
db_query 'ALTER DATABASE :"name" ALLOW_CONNECTIONS false' -v name="$1" >/dev/null""",
        src,
    )
    try:
        if built.returncode != 0:
            raise CouldNotLook(f"could not build the scratch template {src}: {built.stderr}")
        yield src
    finally:
        query("""db_query 'DROP DATABASE IF EXISTS :"name" WITH (FORCE)' -v name="$1" """, src)


def test_a_no_connections_template_clones(
    template_source: str, made: list[str], sh: Callable[..., Ran]
) -> None:
    target = f"djb_tmplclone_{TAG}"
    made.append(target)
    ran = sh(SOURCED + 'db_clone_database "$1" "$2"', target, template_source)
    assert ran.rc == 0, ran.out
    assert psql_on(target, "SELECT count(*) FROM the_proof;") == "3"


CONCURRENT = (
    SOURCED + 'for i in $(seq 1 "$1"); do\n'
    '    (db_clone_database "djb_tmplrace${i}_${TAG}" "$2" >/dev/null 2>&1\n'
    '     echo "clone${i} exit=$?") &\n'
    "done\nwait"
)


def test_concurrent_clones_of_one_template_all_succeed_uncorrupted(
    template_source: str, made: list[str], sh: Callable[..., Ran]
) -> None:
    n = 6
    made.extend(f"djb_tmplrace{i}_{TAG}" for i in range(1, n + 1))
    ran = sh(CONCURRENT, str(n), template_source)
    failed = [i for i in range(1, n + 1) if f"clone{i} exit=0" not in ran.out]
    assert failed == [], f"{len(failed)} of {n} concurrent clones failed: {ran.out}"
    wrong = [
        i
        for i in range(1, n + 1)
        if psql_on(f"djb_tmplrace{i}_{TAG}", "SELECT count(*) FROM the_proof;") != "3"
    ]
    assert wrong == [], f"{len(wrong)} of {n} concurrent clones came out with the wrong contents"


IN_USE = (
    SOURCED
    + """DROP_IT "$1" >/dev/null 2>&1 || true
CREATE_IT "$1" >/dev/null
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$1" -c "SELECT pg_sleep(20);" \\
    >/dev/null 2>&1 &
hold=$!
sleep 2
rc=0
DB_TEMPLATE_CLONE_ATTEMPTS=2 DB_TEMPLATE_CLONE_BACKOFF=1 db_clone_database "$2" "$1" || rc=$?
kill "$hold" 2>/dev/null || true
wait "$hold" 2>/dev/null || true
exit "$rc"
"""
)


def test_a_template_in_use_is_retried_and_then_refused_out_loud(
    stack: bool, made: list[str], sh: Callable[..., Ran]
) -> None:
    live(stack)
    held, target = f"djb_tmplopen_{TAG}", f"djb_tmplopenc_{TAG}"
    made.extend((held, target))
    ran = sh(IN_USE, held, target)
    assert ran.rc != 0, f"cloning from an in-use template returned 0: {ran.out}"
    assert "being accessed by other users" in ran.out, ran.out
    assert "retrying" in ran.out, ran.out


CREATE_IN = SOURCED + 'cd "$1" && DATABASE_NAME="$2" db_create'


def test_a_migration_set_with_no_template_falls_back_out_loud(
    stack: bool, migrations: Callable[[], Path], made: list[str], sh: Callable[..., Ran]
) -> None:
    live(stack)
    repo = migrations()
    target = derive(repo)
    assert target, "db_name derived nothing in the scratch checkout"
    made.append(target)
    ran = sh(CREATE_IN, str(repo), target)
    assert ran.rc == 0, ran.out
    assert f"created database {target}" in ran.out, ran.out
    lines = ran.out.splitlines()
    assert any(
        line.startswith(f"db.sh: db_create {target} path=fallback elapsed=")
        and line.split("elapsed=", 1)[1][:1].isdigit()
        for line in lines
    ), ran.out
    assert "TEMPLATE MISS" in ran.out and "db_template_refresh" in ran.out, ran.out
    tables = psql_on(target, "SELECT count(*) FROM pg_tables WHERE schemaname = 'public';")
    assert tables == "0"


def test_the_escape_restores_the_old_behaviour_exactly(
    stack: bool, migrations: Callable[[], Path], made: list[str], sh: Callable[..., Ran]
) -> None:
    live(stack)
    repo = migrations()
    target = derive(repo)
    made.append(target)
    ran = sh(CREATE_IN, str(repo), target, env={"DJB_DB_TEMPLATE": "off"})
    assert ran.rc == 0, ran.out
    assert "path=" not in ran.out, ran.out


def test_a_name_that_is_not_this_checkouts_own_is_never_templated(
    stack: bool, made: list[str], sh: Callable[..., Ran]
) -> None:
    live(stack)
    target = f"djb_tmplother_{TAG}"
    made.append(target)
    ran = sh(SOURCED + 'db_create "$1"', target)
    assert ran.rc == 0, ran.out
    assert "path=" not in ran.out, ran.out
    assert query('db_template_wanted "$1"', target).returncode != 0
    assert query('db_template_wanted "$(db_name)"').returncode == 0


SETTINGS_PROBE = """
import django, os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
django.setup()
from django.conf import settings
print(settings.DATABASES["default"].get("TEST", {}).get("TEMPLATE", "<none>"))
"""


def settings_template(value: str) -> str:
    """`TEST["TEMPLATE"]` with `DJB_TEST_DB_TEMPLATE` at `value`, the probe's own database named."""
    env = {k: v for k, v in os.environ.items() if k not in UNSET}
    done = subprocess.run(
        ["uv", "run", "python", "-c", SETTINGS_PROBE],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**env, "DATABASE_NAME": "djb_settings_probe", "DJB_TEST_DB_TEMPLATE": value},
    )
    lines = done.stdout.splitlines()
    return lines[-1] if lines else ""


def test_the_settings_take_the_template_from_the_environment() -> None:
    assert settings_template("djb_tmpl_drive_probe") == "djb_tmpl_drive_probe"


def test_the_settings_name_no_template_when_the_environment_is_silent() -> None:
    assert settings_template("") == "<none>"
    assert settings_template("   ") == "<none>"


@pytest.fixture
def tree(checkout: Path) -> Path:
    """A worktree of HEAD carrying this checkout's edits, its `.venv` linked and `.env` copied."""
    changed = subprocess.run(
        ["git", "-C", str(ROOT), "diff", "--name-only", "--diff-filter=d", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.split()
    for path in changed:
        shutil.copyfile(ROOT / path, checkout / path)
    (checkout / ".venv").symlink_to(ROOT / ".venv")
    if (ROOT / ".env").is_file():
        shutil.copyfile(ROOT / ".env", checkout / ".env")
    return checkout


def first_initial(at: Path) -> Path:
    """The first `apps/*/migrations/0001_initial.py` in `at`, in C order."""
    found = sorted(str(p.relative_to(at)) for p in at.glob("apps/*/migrations/0001_initial.py"))
    if not found:
        raise CouldNotLook("no migration file to perturb — the case cannot be arranged")
    return at / found[0]


def template_name(at: Path) -> str:
    """`db_template_name` in `at`."""
    return query('cd "$1" && db_template_name 2>/dev/null', str(at)).stdout.strip()


def collect(at: Path, scratch: Path) -> Captured:
    """`test.sh --collect-only` in `at`, uv kept off the linked environment."""
    return run_to(
        scratch / f"collect-{secrets.token_hex(3)}.out",
        ["./scripts/test.sh", "--collect-only", "-q", "-p", "no:randomly"],
        at,
        {**os.environ, "UV_NO_SYNC": "1"},
    )


def test_a_published_template_reaches_the_suite(
    stack: bool, tree: Path, made: list[str], scratch: Path
) -> None:
    live(stack)
    victim = first_initial(tree)
    victim.write_text(victim.read_text() + f"\n# djb test_db: published {TAG}\n")
    want = template_name(tree)
    assert want and not exists(want), f"the perturbed key {want!r} is already published"
    make_database(want, made)
    out = ran_of(collect(tree, scratch)).out
    assert f"CLONED from {want}" in out, out


def test_a_template_that_is_not_published_is_never_exported(
    stack: bool, tree: Path, scratch: Path
) -> None:
    live(stack)
    victim = first_initial(tree)
    original = victim.read_bytes()
    before = template_name(tree)
    victim.write_text(
        original.decode() + "\n# djb drive: temporary, removed by quality/tests/test_db.py\n"
    )
    after = template_name(tree)
    out = ran_of(collect(tree, scratch)).out
    victim.write_bytes(original)
    assert after != before, f"the perturbed set derives the same key {after}"
    if exists(after):
        raise CouldNotLook(f"the perturbed key {after} happens to be published on this machine")
    assert "no published template for this migration set" in out, out
    assert "CLONED from" not in out, out


def test_the_perturbed_migration_was_restored(tree: Path) -> None:
    victim = first_initial(tree)
    original = victim.read_bytes()
    victim.write_text(original.decode() + "\n# djb drive: temporary\n")
    victim.write_bytes(original)
    assert ROOT not in victim.parents, "the perturbation was aimed at this checkout"
    assert victim.read_bytes() == original


# --- db.sh under a real zsh (quality/tests/test_db.py) -------------------------------

CHILD_ZSH = """emulate -L zsh
print -r -- "child: shell=$ZSH_VERSION"
print -r -- "child: docker-before=$(command -v docker || print none)"
path_before=$PATH
. "$1"
print -r -- "child: derived=${DATABASE_NAME}"
db_create
print -r -- "child: rc=$?"
if [[ "$PATH" == "$path_before" ]]; then
    print -r -- "child: PATH-survived=yes"
else
    print -r -- "child: PATH-survived=no"
fi
print -r -- "child: docker-after=$(command -v docker || print none)"
"""

DERIVATIONS = """cd "$1"
. scripts/db.sh >/dev/null 2>&1
printf 'db_name=%s\\n' "$(db_name)"
printf 'db_path_hash=%s\\n' "$(db_path_hash /a/b 8)"
printf 'db_path_hash16=%s\\n' "$(db_path_hash /a/b 16)"
printf 'db_checkout_root=%s\\n' "$(db_checkout_root)"
printf 'db_migration_key=%s\\n' "$(db_migration_key)"
printf 'db_template_name=%s\\n' "$(db_template_name)"
printf 'db_env_file_pin=%s\\n' "$(db_env_file_pin)"
db_valid_name ok_1; printf 'valid_good=%s\\n' "$?"
db_valid_name 'bad-name'; printf 'valid_bad=%s\\n' "$?"
db_template_wanted "$(db_name)"; printf 'template_wanted=%s\\n' "$?"
"""


def zsh() -> str:
    """The zsh on PATH; `CouldNotLook` without one."""
    found = shutil.which("zsh")
    if found is None:
        raise CouldNotLook("no zsh on PATH — db.sh under zsh cannot be driven")
    return found


def test_db_sh_declares_no_zsh_tied_variable() -> None:
    code = "\n".join(
        line
        for line in (ROOT / "scripts" / "db.sh").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    pattern = TIED + r"|^[[:space:]]*(path|status|options|fignore)="
    hits = subprocess.run(["grep", "-nE", pattern], input=code, capture_output=True, text=True)
    assert hits.stdout == "", f"db.sh declares a zsh-tied variable:\n{hits.stdout}"
    planted = subprocess.run(
        ["grep", "-E", TIED],
        input='    local name="$1" t0 path=fallback\n',
        capture_output=True,
        text=True,
    )
    assert planted.returncode == 0, "the audit pattern does not match the original defect"


def test_the_derivations_agree_between_bash_and_zsh(scratch: Path) -> None:
    shell = zsh()
    probe = scratch / "derive.sh"
    probe.write_text(DERIVATIONS)
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_NAME"}
    a = subprocess.run(["bash", str(probe), str(ROOT)], capture_output=True, text=True, env=env)
    b = subprocess.run(
        [shell, "-f", str(probe), str(ROOT)], capture_output=True, text=True, env=env
    )
    bash_side = a.stdout + a.stderr
    assert bash_side, "the bash side produced nothing — the probe itself is broken"
    assert bash_side == b.stdout + b.stderr, "a derivation forks by shell"
    names = [line for line in bash_side.splitlines() if line.startswith("db_name=djb_")]
    assert names and names[0][len("db_name=") :].replace("_", "").isalnum(), bash_side


@pytest.fixture
def probe(scratch_repo: Callable[..., Path]) -> Callable[[], tuple[Path, str]]:
    """`probe()`: a scratch checkout on branch `zshprobe` and the name it derives."""
    count = 0

    def build() -> tuple[Path, str]:
        nonlocal count
        count += 1
        repo = scratch_repo(f"probe{count}", "db-zsh-drive")
        git(repo, "checkout", "-q", "-b", "zshprobe")
        (repo / "README").write_text("probe\n")
        git(repo, "add", "README")
        git(repo, "commit", "-q", "-m", "the probe")
        return repo, derive(repo)

    return build


def zsh_child(repo: Path, db_sh: Path, scratch: Path, capture: Callable[..., Captured]) -> Ran:
    """The child script under `zsh -f` in `repo`, sourcing `db_sh`."""
    child = scratch / "child.zsh"
    child.write_text(CHILD_ZSH)
    return ran_of(capture([zsh(), "-f", str(child), str(db_sh)], cwd=repo))


def test_db_create_under_zsh_really_creates_the_database(
    stack: bool,
    probe: Callable[[], tuple[Path, str]],
    made: list[str],
    scratch: Path,
    capture: Callable[..., Captured],
) -> None:
    live(stack)
    zsh()
    repo, target = probe()
    assert target.startswith("djb_zshprobe_"), (
        f"the probe derived {target!r} — refusing to create it"
    )
    made.append(target)
    ran = zsh_child(repo, ROOT / "scripts" / "db.sh", scratch, capture)
    assert ran.rc == 0, ran.out
    assert f"child: derived={target}" in ran.out, ran.out
    assert f"created database {target}" in ran.out, ran.out
    assert exists(target), (
        f"'created database {target}' was printed and the database does not exist"
    )
    assert "command not found" not in ran.out, ran.out
    assert "child: docker-after=/" in ran.out, ran.out
    assert any(
        line.startswith(f"db.sh: db_create {target} path=fallback elapsed=")
        and line.split("elapsed=", 1)[1][:1].isdigit()
        for line in ran.out.splitlines()
    ), ran.out


def test_reverting_the_rename_makes_db_create_fail_loud(
    stack: bool,
    probe: Callable[[], tuple[Path, str]],
    made: list[str],
    scratch: Path,
    capture: Callable[..., Captured],
) -> None:
    live(stack)
    zsh()
    planted = scratch / "db-reverted.sh"
    planted.write_text((ROOT / "scripts" / "db.sh").read_text().replace("creation_path", "path"))
    defect = subprocess.run(
        ["grep", "-qE", r"^[[:space:]]*local .*[[:space:]]path=fallback", str(planted)]
    )
    assert defect.returncode == 0, "the revert did not reproduce `local ... path=fallback`"
    repo, target = probe()
    assert target.startswith("djb_zshprobe_"), f"the probe derived {target!r}"
    made.append(target)
    ran = zsh_child(repo, planted, scratch, capture)
    assert f"created database {target}" not in ran.out and "child: rc=1" in ran.out, ran.out
    assert not exists(target), (
        "the reverted copy created the database — the defect no longer reproduces"
    )
    assert "command not found: docker" in ran.out, ran.out
    assert "child: docker-after=/" in ran.out, ran.out
