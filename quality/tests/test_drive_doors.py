"""`./scripts/drive_doors.sh`: the bodies it sends, read off the published document; refusals."""

# does-not-cover: the doors — `apps/core/tests/test_drive_doors.py` drives them on the wire.

from __future__ import annotations

import asyncio
import json
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from quality.djb.rituals import drive_doors

pytestmark = pytest.mark.drives("quality/djb/rituals/drive_doors.py", "scripts/drive_doors.sh")

ROOT = Path(__file__).resolve().parents[2]


def test_a_published_document_drives_its_bodies_from_its_own_examples() -> None:
    document = drive_doors.Document(json.loads((ROOT / "frontend/openapi.json").read_text()))
    _, _, create = document.op("widget-create")
    sent = drive_doors.create_body(document.body_schema(create), "drive-0")
    assert list(sent) == ["name"] and sent["name"].endswith(" drive-0")
    _, _, update = document.op("widget-update")
    change = drive_doors.patch_body(document.body_schema(update), {"version": 7}, set(sent), "x")
    assert change == {"notes": "Moved to bay 3. patched x", "version": 7}
    _, _, listing = document.op("widget-list")
    assert drive_doors.list_filter(listing, sent) == sent
    with pytest.raises(drive_doors.CouldNotDrive, match="no `gizmo-create`"):
        document.op("gizmo-create")


@pytest.mark.parametrize("argv", [[], ["widget"], ["Widget", "--nope"], ["Widget", "Gear"]])
def test_a_wrong_ask_is_exit_2_before_any_request(argv: list[str]) -> None:
    assert drive_doors.main(argv, ROOT) == 2


def _described(status: str, **pending: bool) -> object:
    from temporalio.api.enums.v1 import WorkflowExecutionStatus
    from temporalio.api.workflow.v1 import (
        PendingActivityInfo,
        PendingChildExecutionInfo,
        PendingWorkflowTaskInfo,
    )
    from temporalio.api.workflowservice.v1 import DescribeWorkflowExecutionResponse

    raw = DescribeWorkflowExecutionResponse()
    raw.workflow_execution_info.status = WorkflowExecutionStatus.Value(
        f"WORKFLOW_EXECUTION_STATUS_{status}"
    )
    if pending.get("activity"):
        raw.pending_activities.append(PendingActivityInfo(activity_id="1"))
    if pending.get("child"):
        raw.pending_children.append(PendingChildExecutionInfo(workflow_id="c"))
    if pending.get("task"):
        raw.pending_workflow_task.CopyFrom(PendingWorkflowTaskInfo(attempt=1))
    return raw


@pytest.mark.parametrize(
    ("status", "pending", "state"),
    [
        ("COMPLETED", {}, drive_doors.CLOSED),
        ("TERMINATED", {"activity": True}, drive_doors.CLOSED),
        ("RUNNING", {}, drive_doors.PARKED),
        ("RUNNING", {"activity": True}, drive_doors.BUSY),
        ("RUNNING", {"child": True}, drive_doors.BUSY),
        ("RUNNING", {"task": True}, drive_doors.BUSY),
    ],
)
def test_a_run_is_settled_when_closed_or_parked_with_nothing_scheduled(
    status: str, pending: dict[str, bool], state: str
) -> None:
    assert drive_doors.run_state(_described(status, **pending)) == state


def _runs(states: list[str], bound: float) -> tuple[drive_doors.Runs, list[str]]:
    """One run whose probes answer `states` in turn, the last one for ever."""
    seen: list[str] = []

    async def started() -> list[drive_doors.RunRef]:
        return [("acme:example:widget:1", "r-1")]

    async def probe(ref: drive_doors.RunRef) -> str:
        seen.append(states[min(len(seen), len(states) - 1)])
        return seen[-1]

    return drive_doors.Runs(started=started, probe=probe, bound=bound), seen


def test_settle_waits_out_a_busy_run_until_it_parks() -> None:
    runs, seen = _runs([drive_doors.BUSY, drive_doors.BUSY, drive_doors.PARKED], bound=5)
    assert asyncio.run(drive_doors.settle(runs)) == [("acme:example:widget:1", "r-1")]
    assert seen == [drive_doors.BUSY, drive_doors.BUSY, drive_doors.PARKED]


def test_a_run_busy_past_the_bound_is_could_not_look_naming_the_run() -> None:
    runs, _ = _runs([drive_doors.BUSY], bound=0.3)
    with pytest.raises(drive_doors.CouldNotDrive) as stuck:
        asyncio.run(drive_doors.settle(runs))
    assert str(stuck.value).startswith(
        "run acme:example:widget:1 (run id r-1) did not settle within 0.3 s"
    )


class _Ready(BaseHTTPRequestHandler):
    """`/readyz` advertising the database the class names, and nothing else."""

    database = ""

    def do_GET(self) -> None:  # noqa: N802 — the stdlib's hook name
        said = {"db": True, **({"database": self.database} if self.database else {})}
        body = json.dumps(said).encode()
        self.send_response(200 if self.path == "/readyz" else 404)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def serving() -> Iterator[Callable[[str], str]]:
    """A stub server on a free port whose `/readyz` names the database asked; its base URL."""
    started: list[ThreadingHTTPServer] = []

    def serve(database: str) -> str:
        handler = type("Ready", (_Ready,), {"database": database})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield serve
    for server in started:
        server.shutdown()
        server.server_close()


def _dead_base() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}"


def _recorded(monkeypatch: pytest.MonkeyPatch, database: str, seeded: bool) -> list[str]:
    """The live drive's precondition and mint seams, each recording its call; the mint stops it."""
    calls: list[str] = []

    def derived() -> str:
        calls.append("database")
        return database

    def seed_rows(tenant: str, email: str) -> tuple[object, object]:
        calls.append("seed")
        if not seeded:
            raise drive_doors.CouldNotDrive(f"no seed rows (no tenant `{tenant}`) — next: seed")
        return object(), object()

    def open_token(tenant: object, owner: object) -> drive_doors.DriveToken:
        calls.append("mint")
        raise drive_doors.CouldNotDrive("minted")

    monkeypatch.setattr(drive_doors, "checkout_database", derived)
    monkeypatch.setattr(drive_doors, "seed_rows", seed_rows)
    monkeypatch.setattr(drive_doors, "open_token", open_token)
    return calls


def test_a_server_on_another_database_is_named(
    monkeypatch: pytest.MonkeyPatch,
    serving: Callable[[str], str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = serving("djb_pm_old_1a2b3c4d")
    calls = _recorded(monkeypatch, "djb_pm_new_5e6f7a8b", seeded=True)
    assert drive_doors.main(["Widget", "--base", base], ROOT) == 2
    port = base.rsplit(":", 1)[1]
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"could not drive: the server on :{port} serves djb_pm_old_1a2b3c4d; this checkout "
        "derives djb_pm_new_5e6f7a8b — next: ./scripts/kill_mine.sh --kill, then ./scripts/serve.sh"
    )
    assert "mint" not in calls, "a token was minted for a server on another database"


def test_a_server_naming_no_database_is_refused_before_the_mint(
    monkeypatch: pytest.MonkeyPatch,
    serving: Callable[[str], str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    base = serving("")
    calls = _recorded(monkeypatch, "djb_x", seeded=True)
    assert drive_doors.main(["Widget", "--base", base], ROOT) == 2
    port = base.rsplit(":", 1)[1]
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"could not drive: the server on :{port} names no database on /readyz (it answered "
        "200; only a DEBUG server names one) — next: ./scripts/kill_mine.sh --kill, then "
        "./scripts/serve.sh"
    )
    assert calls == []


def test_preconditions_precede_the_mint(
    monkeypatch: pytest.MonkeyPatch, serving: Callable[[str], str]
) -> None:
    calls = _recorded(monkeypatch, "djb_x", seeded=True)
    with pytest.raises(drive_doors.CouldNotDrive, match="^nothing serves at "):
        drive_doors.live("Widget", _dead_base(), "acme", "owner@example.com")
    assert calls == [], "a dead server is named before the database, the seed or the mint"
    calls = _recorded(monkeypatch, "djb_x", seeded=False)
    with pytest.raises(drive_doors.CouldNotDrive, match="^no seed rows"):
        drive_doors.live("Widget", serving("djb_x"), "acme", "owner@example.com")
    assert calls == ["database", "seed"]
    calls = _recorded(monkeypatch, "djb_x", seeded=True)
    with pytest.raises(drive_doors.CouldNotDrive, match="^minted$"):
        drive_doors.live("Widget", serving("djb_x"), "acme", "owner@example.com")
    assert calls == ["database", "seed", "mint"]


def test_a_dead_stack_preflight_is_exit_2_in_a_second(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _recorded(monkeypatch, "djb_x", seeded=True)
    t0 = time.monotonic()
    assert drive_doors.main(["Widget", "--preflight", "--base", _dead_base()], ROOT) == 2
    assert time.monotonic() - t0 < 5
    assert capsys.readouterr().out.splitlines()[-1].startswith("could not drive: nothing serves")
    assert calls == []


def test_a_live_preflight_mints_nothing(
    monkeypatch: pytest.MonkeyPatch,
    serving: Callable[[str], str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = _recorded(monkeypatch, "djb_x", seeded=True)
    base = serving("djb_x")
    assert drive_doors.main(["Widget", "--preflight", "--base", base], ROOT) == 0
    assert calls == ["database", "seed"]
    port = base.rsplit(":", 1)[1]
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"preflight: the server on :{port} serves djb_x, this checkout's database; "
        "tenant acme and owner@example.com are seeded"
    )


FAMILY = frozenset({"archive", "restore", "move", "merge", "duplicate", "bulk", "history"})


def test_the_declared_verbs_are_read_off_the_published_document() -> None:
    document = drive_doors.Document(json.loads((ROOT / "frontend/openapi.json").read_text()))
    assert [verb for verb, _ in drive_doors.declared_verbs(document, "widget", FAMILY)] == [
        "approve",
        "touch",
        "transition",
    ]


def _widget_world(document: drive_doors.Document) -> httpx.MockTransport:
    """A widget row whose `touch` moves its stamp and whose `transition` moves its status."""
    row: dict[str, Any] = {
        "id": "w-1",
        "name": "Bay 3",
        "status": "draft",
        "version": 1,
        "updated_at": "t1",
    }
    tools = [
        {"name": f"{verb}_widget", "description": document.op(f"widget-{verb}")[2]["summary"]}
        for verb in ("approve", "touch", "transition")
    ]

    def answer(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == drive_doors.MCP_URL:
            return httpx.Response(200, json={"result": {"tools": tools}})
        if request.method == "GET" and path == "/api/v1/widgets/w-1/":
            return httpx.Response(200, json=row)
        if path.endswith("/touch/"):
            row.update(version=row["version"] + 1, updated_at="t2")
        elif path.endswith("/transition/"):
            row.update(status=json.loads(request.content)["status"], version=row["version"] + 1)
        elif path.endswith("/approve/"):
            return httpx.Response(409, json={"code": "conflict", "detail": "already approved"})
        else:
            return httpx.Response(404, json={"code": "not_found"})
        return httpx.Response(200, json=row)

    return httpx.MockTransport(answer)


def test_verbs_are_pressed_and_named(capsys: pytest.CaptureFixture[str]) -> None:
    document = drive_doors.Document(json.loads((ROOT / "frontend/openapi.json").read_text()))

    async def started() -> list[drive_doors.RunRef]:
        return []

    async def probe(ref: drive_doors.RunRef) -> str:
        return drive_doors.CLOSED

    async def press() -> drive_doors.Drive:
        result = drive_doors.Drive(noun="Widget", document=document, row_id="w-1")
        transport = _widget_world(document)
        async with httpx.AsyncClient(base_url="http://drive", transport=transport) as client:
            runs = drive_doors.Runs(started=started, probe=probe)
            await drive_doors.press_verbs(client, "t", result, runs, FAMILY)
        return result

    result = asyncio.run(press())
    assert {verb: p.moved for verb, p in result.pressed.items()} == {
        "touch": ["updated_at", "version"],
        "transition": ["status", "version"],
    }
    assert result.not_pressed == ["approve (answered 409 conflict)"]
    result.bodies = {}
    assert drive_doors.verdict(result) == "doors agree: Widget · verbs: touch, transition"
    drive_doors.say_verbs(result)
    said = capsys.readouterr().out.splitlines()
    assert "-- pressed touch (mcp touch_widget): moved updated_at, version" in said
    assert "-- not pressed: approve (answered 409 conflict)" in said


def test_a_verb_whose_body_has_no_example_is_not_pressed_and_says_why() -> None:
    reason: dict[str, Any] = {"type": "string"}
    schema: dict[str, Any] = {"properties": {"reason": reason}, "required": ["reason"]}
    assert drive_doors.verb_body(schema, {"version": 3}) == (None, ["reason"])
    reason["example"] = "late"
    schema["properties"]["version"] = {"type": "integer"}
    assert drive_doors.verb_body(schema, {"version": 3}) == ({"reason": "late", "version": 3}, [])


def test_a_serve_script_that_names_no_port_is_quoted(tmp_path: Path) -> None:
    said = "!! serve.sh: no .env in this checkout — run ./scripts/setup.sh"
    serve = tmp_path / "scripts/serve.sh"
    serve.parent.mkdir()
    serve.write_text(f"#!/bin/sh\necho {said!r} >&2\nexit 2\n")
    serve.chmod(0o755)
    with pytest.raises(drive_doors.CouldNotDrive) as refused:
        drive_doors.base_url(tmp_path)
    assert f"named no port\n   the tool said: {said}" in str(refused.value)


def test_a_database_that_answers_no_query_is_quoted(monkeypatch: pytest.MonkeyPatch) -> None:
    from django.db import OperationalError

    said = 'FATAL:  password authentication failed for user "djb"'

    def refuse(**_: object) -> object:
        raise OperationalError(said)

    rows = SimpleNamespace(objects=SimpleNamespace(filter=refuse))
    monkeypatch.setitem(sys.modules, "apps.accounts.models", SimpleNamespace(User=rows))
    monkeypatch.setitem(sys.modules, "apps.core.models", SimpleNamespace(Tenant=rows))
    with pytest.raises(drive_doors.CouldNotDrive) as refused:
        drive_doors.seed_rows("acme", "owner@example.com")
    assert f"next: ./scripts/setup.sh\n   the tool said: {said}" in str(refused.value)
