"""The runbooks' marked recipes, lifted out of the documents at run time and run as printed.

does-not-cover: the two vendor-signed recipes are executed for a signature and never posted.
does-not-cover: recipe 1's middle move — adding the endpoint in the provider's own console.
does-not-cover: TLS — `https://` becomes `http://`, the one substitution the recipes do not name.
does-not-cover: the prose — only the fenced blocks run.
does-not-cover: a recipe block the documents grew without a marker.
does-not-cover: which interpreter a recipe needs — house ones on the venv and bash, vendors on uv.
does-not-cover: the delivery workflow after the receiver's 202, and the handler's run as a run.
does-not-cover: the capacity chapter's review-tier sections and every number in it — shape only.
does-not-cover: whether a shape's move works — the census reads its steps' names, never runs them.
does-not-cover: a world killed with SIGKILL — its runs and database are left for the brooms.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from inspect import getsource
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from quality.could_not_look import CouldNotLook

pytestmark = pytest.mark.drives(
    ".env.example",
    "apps/*/apps.py",
    "apps/*/migrations/",
    "config/",
    "deploy/load/drive.py",
    "deploy/observability/alerts/census.py",
    "docs/runbooks/capacity.md",
    "docs/runbooks/deploy.md",
    "manage.py",
    "scripts/db.sh",
    "scripts/db_sweep.sh",
    "scripts/envelope.sh",
    "scripts/kill_mine.sh",
    "scripts/lifecycle.sh",
    "scripts/queue_cited.sh",
    "scripts/setup.sh",
    "scripts/sweep.sh",
    "quality/tests/fixtures/runbook/render_recipe.py",
    "quality/tests/fixtures/runbook/runbook_receiver.py",
)

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "runbooks" / "deploy.md"
CAPDOC = ROOT / "docs" / "runbooks" / "capacity.md"
RENDER = ROOT / "quality/tests/fixtures/runbook/render_recipe.py"
HARNESS = ROOT / "quality/tests/fixtures/runbook/runbook_receiver.py"
PY = ROOT / ".venv" / "bin" / "python"
MARKERS = ("connection-create", "house-v2", "house-legacy", "svix-sign", "twilio-sign")
CAP_MARKERS = ("pg-census", "pg-census-steady", "envelope-line-example", "envelope-line-check")
MARKER_LINE = re.compile(r"^<!-- recipe: ([A-Za-z0-9_-]+) -->$", re.M)
WHSEC = "whsec_cnVuYm9va2RyaXZlc2NyYXRjaHNlY3JldA"  # pragma: allowlist secret
SVIX_TABLE = '{"whsec_…": "whsec_c3VwZXJzZWNyZXRzaWduaW5na2V5MTIz"}'  # pragma: allowlist secret
TWILIO_TABLE = (
    '{"<the account auth_token>": "0123456789abcdef0123456789abcdef", '  # pragma: allowlist secret
    '"<host>": "example.invalid", "<connection-id>": "00000000-0000-0000-0000-000000000000"}'
)
SIGNATURE_CHECK = (
    '\nassert isinstance(signature, str) and signature, "no signature"\n'
    'print("{0} ok", len(signature))\n'
)


def shell(
    script: str, env: dict[str, str] | None = None, stdin: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """`script` in a bash that has sourced `scripts/db.sh` and `scripts/lifecycle.sh`."""
    prelude = (
        "source scripts/db.sh >/dev/null 2>&1 && source scripts/lifecycle.sh >/dev/null 2>&1 && "
    )
    with stdin.open() if stdin else open(os.devnull) as feed:
        return subprocess.run(
            ["bash", "-c", prelude + script],
            cwd=ROOT,
            stdin=feed,
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
        )


def render(doc: Path, marker: str, out: Path, table: str) -> subprocess.CompletedProcess[str]:
    """`render_recipe.py` lifting `marker` out of `doc` into `out` under `table`."""
    return subprocess.run(
        [str(PY), str(RENDER), str(doc), marker, str(out), table],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def lifted(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Every marked block of both documents, lifted with no substitution; a refusal is absent."""
    for path in (DOC, CAPDOC, RENDER, HARNESS, ROOT / "manage.py"):
        if not path.is_file():
            raise CouldNotLook(f"{path.relative_to(ROOT)} is not in this tree")
    if not os.access(PY, os.X_OK):
        raise CouldNotLook("this checkout has no .venv/bin/python — run ./scripts/setup.sh first")
    work = tmp_path_factory.mktemp("lifted")
    found: dict[str, Path] = {}
    for doc, markers in ((DOC, MARKERS), (CAPDOC, CAP_MARKERS)):
        for marker in markers:
            out = work / f"{marker}.txt"
            if (
                render(doc, marker, out, "{}").returncode == 0
                and out.is_file()
                and out.stat().st_size
            ):
                found[marker] = out
    return found


@dataclass
class World:
    """A scratch database migrated, a receiver serving it, and the Temporal runs it starts."""

    work: Path
    name: str
    key: str = field(default_factory=lambda: Fernet.generate_key().decode())
    queue: str = ""
    slug: str = ""
    receiver: subprocess.Popen[bytes] | None = None
    facts_env: dict[str, str] = field(default_factory=dict)

    @property
    def env(self) -> dict[str, str]:
        """The variables every process of this world runs under."""
        return {
            "DATABASE_NAME": self.name,
            "CONNECTIONS_ENCRYPTION_KEY": self.key,
            **self.facts_env,
        }

    def harness(self, *args: str) -> subprocess.CompletedProcess[str]:
        """`runbook_receiver.py <args>` against this world's database."""
        return subprocess.run(
            ["uv", "run", "python", str(HARNESS), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, **self.env},
        )

    def facts(self) -> str:
        """One read of the world's rows, one line each."""
        return self.harness("facts").stdout

    def runs_query(self) -> str:
        """This world's own running executions: its task queue AND the harness's tenant slug."""
        return (
            f'TaskQueue="{self.queue}" AND ExecutionStatus="Running" '
            f'AND WorkflowId STARTS_WITH "{self.slug}:"'
        )

    def running(self) -> list[str]:
        """The ids of this world's running executions; `CouldNotLook` when the server cannot say."""
        listed = shell(f"lc_temporal workflow list --query '{self.runs_query()}' -o json")
        try:
            return [doc["execution"]["workflowId"] for doc in json.loads(listed.stdout or "x")]
        except (ValueError, KeyError, TypeError) as error:
            raise CouldNotLook(
                f"Temporal would not list this world's runs: {listed.stderr}"
            ) from error

    def terminate(self) -> bool:
        """Terminate this world's running executions by id, three rounds; whether none remain."""
        for _ in range(3):
            ids = self.running()
            if not ids:
                return True
            for workflow_id in ids:
                shell(
                    f"lc_temporal workflow terminate --workflow-id '{workflow_id}' "
                    "--reason 'test_runbook: the module that started it has finished'"
                )
        return not self.running()

    def close(self) -> None:
        """Stop the receiver, terminate the runs, drop the database."""
        if self.receiver is not None and self.receiver.poll() is None:
            self.receiver.terminate()
            self.receiver.wait(timeout=30)
        if self.queue:
            try:
                self.terminate()
            except CouldNotLook:
                pass
        shell(f"db_exists '{self.name}' && db_drop '{self.name}' >/dev/null")


@pytest.fixture(scope="module")
def world(tmp_path_factory: pytest.TempPathFactory, lifted: dict[str, Path]) -> Iterator[World]:
    """This module's world, named per xdist worker so two never share a database or a queue."""
    for tool in ("python3", "curl", "openssl", "uv"):
        if shutil.which(tool) is None:
            raise CouldNotLook(f"no {tool} on PATH")
    suffix = os.environ.get("PYTEST_XDIST_WORKER", "gw")
    digest = shell(f"db_path_hash '{ROOT}' 12").stdout.strip()
    name = f"test_djb_rbk_{digest}_f6{suffix}"
    if not digest or shell(f"db_valid_name '{name}'").returncode != 0:
        raise CouldNotLook(f"the derived scratch database name is not a name: {name}")
    made = World(tmp_path_factory.mktemp("world"), name)
    asked = made.harness("world")
    values = dict(line.split("=", 1) for line in asked.stdout.splitlines() if "=" in line)
    made.queue, made.slug = values.get("DRIVE_QUEUE", ""), values.get("DRIVE_SLUG", "")
    if not made.queue:
        raise CouldNotLook(f"the harness would not name this world's task queue: {asked.stderr}")
    try:
        if shell(f"db_create '{name}'").returncode != 0:
            raise CouldNotLook(f"could not create {name} — is the compose stack up?")
        migrated = subprocess.run(
            ["uv", "run", "python", "manage.py", "migrate", "--noinput"],
            cwd=ROOT,
            capture_output=True,
            env={**os.environ, **made.env},
        )
        if migrated.returncode != 0:
            raise CouldNotLook(f"could not migrate {name}")
        env_file, log = made.work / "receiver.env", made.work / "receiver.log"
        with log.open("wb") as sink:
            made.receiver = subprocess.Popen(
                ["uv", "run", "python", str(HARNESS), "serve", str(env_file)],
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env={**os.environ, **made.env},
            )
        for _ in range(120):
            if env_file.is_file() and "RECEIVER_READY=1" in env_file.read_text():
                break
            if made.receiver.poll() is not None:
                raise CouldNotLook(
                    f"the receiver died before it was listening: {log.read_text()[-2000:]}"
                )
            time.sleep(0.5)
        else:
            raise CouldNotLook("the receiver did not come up within 60s")
        made.facts_env = dict(
            line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line
        )
        yield made
    finally:
        made.close()


def table_for(world: World, event: str, handle: str, connection_id: str) -> str:
    """The declared substitution table: scheme, host, connection, secret, handle, and one event."""
    table = {
        "https://": "http://",
        "<host>": world.facts_env.get("HOST", ""),
        "<connection-id>": connection_id,
        "…the connection's webhook_secret…": WHSEC,
        '"message_id": "…"': f'"message_id": "{handle}"',
        '"message_id":"…"': f'"message_id":"{handle}"',
    }
    if event != "bounced":
        table["bounced"] = event
    return json.dumps(table)


@dataclass(frozen=True)
class Connection:
    """Recipe 1's run: the id it answered and the world's rows after it."""

    id: str
    output: str
    facts: str


@pytest.fixture(scope="module")
def connection(world: World) -> Connection:
    """Recipe 1 rendered and run as printed with `$HOST`, `$TOKEN` and `$WHSEC` filled."""
    recipe = world.work / "recipe1.sh"
    if (
        render(DOC, "connection-create", recipe, table_for(world, "bounced", "x", "")).returncode
        != 0
    ):
        raise CouldNotLook(f"could not lift recipe 1 out of {DOC}")
    ran = subprocess.run(
        ["bash", str(recipe)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **world.env, "WHSEC": WHSEC},
    )
    try:
        answered = str(json.loads(ran.stdout).get("id", ""))
    except ValueError:
        answered = ""
    return Connection(answered, ran.stdout + ran.stderr, world.facts())


def house(
    world: World, connection: Connection, marker: str, runner: str, event: str, handle: str
) -> str:
    """One house recipe rendered for `event` and `handle`, run by `runner`; its output."""
    recipe = world.work / f"{marker}-{event}.run"
    table = table_for(world, event, handle, connection.id)
    assert render(DOC, marker, recipe, table).returncode == 0, (
        f"could not lift {marker} out of {DOC}"
    )
    ran = subprocess.run(
        [runner, str(recipe)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, **world.env, "SECRET": WHSEC, "CONNECTION_ID": connection.id},
    )
    return ran.stdout + ran.stderr


def needle(*parts: str) -> str:
    """A censused string joined at run time, so this file never spells it."""
    return "".join(parts)


def test_every_marker_in_the_document_is_driven(lifted: dict[str, Path]) -> None:
    assert sorted(MARKER_LINE.findall(DOC.read_text())) == sorted(MARKERS)
    assert [m for m in MARKERS if m not in lifted] == []


def test_every_marker_in_the_capacity_chapter_is_driven(lifted: dict[str, Path]) -> None:
    assert sorted(MARKER_LINE.findall(CAPDOC.read_text())) == sorted(CAP_MARKERS)
    assert [m for m in CAP_MARKERS if m not in lifted] == []


def test_the_drive_holds_no_copy_of_the_recipes(lifted: dict[str, Path]) -> None:
    digest, legacy = needle("hmac", ".new("), needle("openssl", " dgst")
    assert digest in lifted["house-v2"].read_text(), "extraction is broken"
    assert legacy in lifted["house-legacy"].read_text(), "extraction is broken"
    for path in (Path(__file__), HARNESS):
        text = path.read_text()
        assert digest not in text and legacy not in text, f"{path} computes a signature of its own"


def test_the_drive_holds_no_copy_of_the_capacity_recipes(lifted: dict[str, Path]) -> None:
    catalog, bound = needle("pg_stat", "_activity"), needle("ERR_BOUND", "_PCT")
    assert catalog in lifted["pg-census"].read_text()
    assert catalog in lifted["pg-census-steady"].read_text()
    assert bound in lifted["envelope-line-check"].read_text()
    for path in (Path(__file__), HARNESS):
        text = path.read_text()
        assert catalog not in text and bound not in text, f"{path} carries the capacity arithmetic"


def test_the_envelope_line_checker_accepts_the_chapters_own_example(
    lifted: dict[str, Path],
) -> None:
    with lifted["envelope-line-example"].open() as example:
        ran = subprocess.run(
            [str(PY), str(lifted["envelope-line-check"]), "--knee"],
            stdin=example,
            capture_output=True,
            text=True,
        )
    assert ran.returncode == 0, ran.stdout + ran.stderr


def test_the_envelope_line_checker_refuses_an_incomplete_line(
    lifted: dict[str, Path], scratch: Path
) -> None:
    fields = lifted["envelope-line-example"].read_text().strip().split(" | ")
    short = scratch / "envelope-short.txt"
    short.write_text(" | ".join(fields[:-1]) + "\n")
    with short.open() as line:
        ran = subprocess.run(
            [str(PY), str(lifted["envelope-line-check"]), "--knee"],
            stdin=line,
            capture_output=True,
            text=True,
        )
    assert ran.returncode != 0, "a line one part short passed — the checker cannot fail"


SHAPES_HEAD = "## 10 · Shapes"
RECORDED_SHA = re.compile(r"^- \d{4}-\d{2}-\d{2} · sha `([0-9a-f]{12})`", re.M)
CITED_SHA = re.compile(r"`([0-9a-f]{12})`")
UNBUILT = re.compile(r"not in the tree \([^)]*\bdue in \d+\.\d+(?:\.\d+)?\b")
#: What § 10 may spell with a digit: a sha, a path, a class, a section, a shape, an id, an ADR.
NOT_A_NUMBER = re.compile(
    r"`[0-9a-f]{12}`|`[\w./-]+\.\w+`|\b(?:db\.)?[a-z]\d+[a-z]*\.[a-z0-9]+\b|§ \d+[a-z]?"
    r"|\bS\d\b|\bN\d+\b|\b[A-Z]+(?:-[A-Z]+)*-\d+\b|\bdue in \d+\.\d+(?:\.\d+)?\b|\bADR [a-z]+-\d+"
)


def shapes_section() -> str:
    """§ 10 of the capacity chapter, heading to the next `## `."""
    text = CAPDOC.read_text()
    assert SHAPES_HEAD in text, f"{CAPDOC.name} has no {SHAPES_HEAD!r} section"
    return text.split(SHAPES_HEAD, 1)[1].split("\n## ", 1)[0]


def shape_rows() -> dict[str, list[str]]:
    """The shapes table's rows by shape id, each a list of its cells."""
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in shapes_section().splitlines()
        if re.match(r"^\| S\d ", line)
    ]
    return {row[0]: row for row in rows}


def declared_keys(path: str, block: str, pattern: str) -> set[str]:
    """The keys a source declares in one named block, read off its text."""
    text = (ROOT / path).read_text()
    body = text.split(block, 1)[1].split("\n)\n", 1)[0] if block in text else ""
    return set(re.findall(pattern, body))


def test_every_shape_row_cites_a_recorded_knee_or_says_unmeasured() -> None:
    rows = shape_rows()
    assert {"S1", "S2", "S3"} <= set(rows), f"the shapes table holds {sorted(rows)}"
    recorded = set(RECORDED_SHA.findall(CAPDOC.read_text().split(SHAPES_HEAD, 1)[0]))
    assert recorded, "§ 9 holds no recorded bullet — the lift is broken"
    alerts = declared_keys("deploy/observability/alerts/census.py", "TRACES:", r'"key": "(\w+)"')
    samplers = declared_keys("deploy/load/drive.py", "CPU_KEYS:", r'"(\w+)"')
    shapes = set(re.findall(r"^(\S+)\) type=", (ROOT / "scripts/envelope.sh").read_text(), re.M))
    assert alerts and samplers and shapes, "a declaration moved — the census reads nothing"
    for shape, (_, _, _, line, trigger, move) in ((k, v[:6]) for k, v in rows.items()):
        shas = set(CITED_SHA.findall(line))
        assert shas or "`unmeasured`" in line, f"{shape}: no line and no `unmeasured`"
        assert shas <= recorded, f"{shape}: cites {sorted(shas - recorded)}, not in § 9"
        named = set(re.findall(r"`(\w+)`", trigger))
        assert named & alerts, f"{shape}: the trigger names no alert key of {sorted(alerts)}"
        stray = sorted(named - alerts - samplers)
        assert not stray, f"{shape}: the trigger names {stray}, which nothing declares"
        steps = set(re.findall(r"--shape (\S+?)`", move))
        assert steps or UNBUILT.search(move), f"{shape}: the move is neither a step nor dated"
        assert steps <= shapes, f"{shape}: `envelope.sh` takes no --shape {sorted(steps - shapes)}"


def test_the_shapes_section_retypes_no_number() -> None:
    fresh = re.findall(r"\S*\d\S*", NOT_A_NUMBER.sub("", shapes_section()))
    assert fresh == [], f"§ 10 types numbers § 9 or the memo own: {fresh}"


def test_a_killed_drive_still_runs_its_cleanups(scratch: Path) -> None:
    sentinel, started, out = (
        scratch / "killable.cleaned",
        scratch / "killable.started",
        scratch / "killed.log",
    )
    script = scratch / "killable.sh"
    script.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'cd "{ROOT}"\n. scripts/tests/drive_preamble.sh\n'
        f"drive_at_exit \"touch '{sentinel}'\"\n"
        f'touch "{started}"\nwhile :; do sleep 0.2; done\n'
    )
    with out.open("wb") as sink:
        killable = subprocess.Popen(["bash", str(script)], stdout=sink, stderr=subprocess.STDOUT)
        for _ in range(100):
            if started.exists() or killable.poll() is not None:
                break
            time.sleep(0.1)
        if not started.exists():
            killable.kill()
            killable.wait()
            pytest.fail(f"the killable script never became ready: {out.read_text()}")
        assert not sentinel.exists(), "the cleanup ran before anything was killed"
        killable.send_signal(signal.SIGTERM)
        rc = killable.wait()
    assert sentinel.exists(), "a TERM'd drive skipped its registered cleanup"
    assert rc == 143, rc
    assert "killed by SIGTERM" in out.read_text()


def test_the_census_recipes_are_legal_and_attribute_in_one_read(lifted: dict[str, Path]) -> None:
    if shell('db_query "SELECT 1" -tA').returncode != 0:
        raise CouldNotLook("no Postgres to drive the census recipes at — is the compose stack up?")
    user = shell('printf %s "$POSTGRES_USER"').stdout
    census = shell("db_psql -tA -F'|'", stdin=lifted["pg-census"])
    assert census.returncode == 0, census.stdout + census.stderr
    assert re.search(rf"^postgres\|{re.escape(user)}\|", census.stdout, re.M), census.stdout
    steady = shell("db_psql -tA -F'|'", stdin=lifted["pg-census-steady"])
    assert steady.returncode == 0, steady.stdout + steady.stderr
    rows = [line.split("|") for line in steady.stdout.splitlines()]
    assert any(r[0] == "postgres" and r[1] == user and len(r) >= 5 for r in rows), steady.stdout


def test_the_drive_supplies_the_cipher_key_its_world_needs(world: World) -> None:
    assert world.key, "the world minted no CONNECTIONS_ENCRYPTION_KEY"
    dotenv = ROOT / ".env"
    found = (
        re.search(r"^\s*CONNECTIONS_ENCRYPTION_KEY=(.*)$", dotenv.read_text(), re.M)
        if dotenv.is_file()
        else None
    )
    theirs = found.group(1).strip().strip("\"' \r") if found else ""
    assert not theirs or theirs != world.key, "the world uses the checkout's own .env key"
    Fernet(world.key.encode())


def test_the_connection_recipe_creates_the_connection(world: World, connection: Connection) -> None:
    assert connection.id, f"the recipe did not answer a connection id: {connection.output}"
    want = world.harness("digest", WHSEC).stdout.strip()
    rows = [line.split() for line in connection.facts.splitlines()]
    got = [r[4] for r in rows if len(r) >= 5 and r[0] == "connection" and r[1] == connection.id]
    assert want and got == [want], (want, got)
    assert re.search(
        rf"^connection {re.escape(connection.id)} comms-email Resend ", connection.facts, re.M
    )


def test_the_v2_recipe_lands_an_engagement(world: World, connection: Connection) -> None:
    handle = world.facts_env["HANDLE_V2"]
    out = house(world, connection, "house-v2", str(PY), "opened", handle)
    assert re.search(r"^202$", out, re.M), out
    assert re.search(rf"^engagement {re.escape(handle)} opened ", world.facts(), re.M)


def test_the_v2_recipe_as_printed_bounces_the_message(world: World, connection: Connection) -> None:
    handle = world.facts_env["HANDLE_V2"]
    out = house(world, connection, "house-v2", str(PY), "bounced", handle)
    assert re.search(r"^202$", out, re.M), out
    assert re.search(rf"^message {re.escape(handle)} bounced$", world.facts(), re.M)


def test_the_legacy_recipe_lands_an_engagement(world: World, connection: Connection) -> None:
    handle = world.facts_env["HANDLE_LEGACY"]
    out = house(world, connection, "house-legacy", "bash", "opened", handle)
    assert re.search(r"^202$", out, re.M), out
    assert re.search(rf"^engagement {re.escape(handle)} opened ", world.facts(), re.M)


def test_the_legacy_recipe_as_printed_bounces_the_message(
    world: World, connection: Connection
) -> None:
    handle = world.facts_env["HANDLE_LEGACY"]
    out = house(world, connection, "house-legacy", "bash", "bounced", handle)
    assert re.search(r"^202$", out, re.M), out
    assert re.search(rf"^message {re.escape(handle)} bounced$", world.facts(), re.M)


def test_the_vendor_signed_recipes_bind_their_symbols(scratch: Path) -> None:
    for marker, vendor, table in (
        ("svix-sign", "svix", SVIX_TABLE),
        ("twilio-sign", "twilio", TWILIO_TABLE),
    ):
        recipe = scratch / f"recipe_{vendor}.py"
        if render(DOC, marker, recipe, table).returncode != 0:
            raise CouldNotLook(f"could not lift the {vendor} recipe out of {DOC}")
        recipe.write_text(recipe.read_text() + SIGNATURE_CHECK.format(vendor))
        ran = subprocess.run(
            ["uv", "run", "python", str(recipe)], cwd=ROOT, capture_output=True, text=True
        )
        assert ran.returncode == 0 and f"{vendor} ok" in ran.stdout, ran.stdout + ran.stderr


def test_the_drive_terminates_the_runs_it_started(world: World) -> None:
    probe = f"{world.slug}:rbkprobe:terminator:own"
    shell(
        f"lc_temporal workflow start --workflow-id '{probe}' --task-queue '{world.queue}' "
        "--type RunbookDriveProbeNeverRuns"
    )
    assert world.running(), "not even this case's own probe is running"
    assert world.terminate(), f"runs remained after the terminator: {world.running()}"
    assert world.running() == []
    assert "self.terminate()" in getsource(World.close), "the world's close does not terminate"
