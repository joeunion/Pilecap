"""`deploy/load/realtime_lag.py`: the line, the door mode, fifty sockets, the missing frame."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import transaction
from django.test import Client
from django.utils.module_loading import import_string

from apps.accounts.services import issue_token
from apps.core.actor import system_actor
from apps.testing import fixtures
from pilecap.accounts import User
from pilecap.events import EMIT
from pilecap.tenancy import Tenant
from pilecap.testing import bridge_registry, get_listener, set_principal

# The fixtures apps/conftest.py gives every app test, named here: this module is outside apps/.
_clean_context = fixtures._clean_context
_no_dialling_temporal = fixtures._no_dialling_temporal
recorded_workflow_starts = fixtures.recorded_workflow_starts
tenant = fixtures.tenant
owner = fixtures.owner

PROBE = Path(__file__).resolve().parents[1] / "realtime_lag.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("load_realtime_lag", PROBE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["load_realtime_lag"] = module
    spec.loader.exec_module(module)
    return module


probe = _load()

pytestmark = [pytest.mark.django_db(transaction=True)]

EVENTS = 20
SOCKETS = 50
VALUE_KEYS = {"p95_commit_ms", "p95_ms", "p95_door_ms", "p50_ms", "max_ms"}


@pytest.fixture
def pushes_on_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dispatch's push hop run on commit in-process, where a worker would run it."""
    activities = importlib.import_module("apps.events.activities")
    types = importlib.import_module("apps.events.types")
    real_emit: Callable[..., Any] = get_listener(EMIT)

    def emit_then_push(**kwargs: Any) -> Any:
        event = real_emit(**kwargs)

        def push_on_commit() -> None:
            set_principal(tenant_id=str(event.tenant_id), user_id=None)
            activities.push_realtime(types.PushRealtime(event_id=str(event.pk)))

        transaction.on_commit(push_on_commit)
        return event

    monkeypatch.setitem(bridge_registry, EMIT, emit_then_push)


class InProcessDoors:
    """A fake transport: REST via the test client, sockets via the ASGI app, each recorded."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.sockets: list[str] = []
        self.client = Client()

    def _call(self, method: str, path: str, token: str, tenant: str, body: object) -> Any:
        self.calls.append((method, path, token))
        return self.client.generic(
            method,
            path,
            data=json.dumps(body) if body is not None else "",
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_TENANT=tenant,
        )

    async def call(
        self, method: str, path: str, *, token: str, tenant: str, body: object = None
    ) -> tuple[int, dict[str, Any]]:
        response = await sync_to_async(self._call)(method, path, token, tenant, body)
        return response.status_code, (response.json() if response.content else {})

    async def socket(self, *, token: str, tenant: str, within: float) -> Any:
        self.sockets.append(token)
        socket = probe.InProcessSocket(
            import_string(settings.ASGI_APPLICATION),
            [(b"authorization", f"Bearer {token}".encode()), (b"x-tenant", tenant.encode())],
        )
        await socket.open(within)
        return socket


def _credentials(path: Path, tenant: Tenant, owner: User, count: int) -> Path:
    rows = []
    for n in range(count):
        _token, plaintext = issue_token(
            user=owner,
            tenant=tenant,
            name=f"probe-{n}",
            actor=system_actor(tenant=tenant),
            scopes=["*"],
        )
        rows.append({"tenant": tenant.slug, "token": plaintext})
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _json_line(out: StringIO) -> dict[str, Any]:
    lines = [line for line in out.getvalue().splitlines() if line.startswith("{")]
    assert len(lines) == 1, out.getvalue()
    return dict(json.loads(lines[0]))


def _run(*args: str) -> dict[str, Any]:
    out = StringIO()
    assert probe.main(list(args), out) == 0
    return _json_line(out)


@pytest.mark.usefixtures("recorded_workflow_starts", "pushes_on_commit")
def test_twenty_frames_measured(tenant: Tenant, owner: User) -> None:
    measured = _run("--events", str(EVENTS), "--tenant", tenant.slug, "--json")

    assert set(measured) == {"value", "basis", "instrument"}
    assert set(measured["value"]) == VALUE_KEYS
    assert all(isinstance(measured["value"][key], str) for key in measured["value"])
    assert measured["basis"]["events"] == EVENTS
    assert measured["basis"]["frames"] == EVENTS
    assert measured["basis"]["formula"]
    assert "relay_poll_seconds" in measured["basis"]
    assert "channel_layer" in measured["basis"]
    assert measured["instrument"].startswith("deploy/load/realtime_lag.py")


@pytest.mark.usefixtures("recorded_workflow_starts", "pushes_on_commit")
def test_the_plain_line_names_each_number(tenant: Tenant, owner: User) -> None:
    out = StringIO()
    assert probe.main(["--events", "3", "--tenant", tenant.slug], out) == 0
    text = out.getvalue()

    for word in (
        "realtime=p95_commit_ms=",
        " p95_ms=",
        "p95_door_ms=",
        "p50_ms=",
        "max_ms=",
        "events=3",
        "relay_poll_seconds=",
    ):
        assert word in text, text


@pytest.mark.usefixtures("recorded_workflow_starts")
def test_a_missing_frame_is_exit_2(
    tenant: Tenant, owner: User, capsys: pytest.CaptureFixture[str]
) -> None:
    status = probe.main(["--events", "2", "--tenant", tenant.slug, "--within", "1"], StringIO())

    assert status == 2
    assert "0 of 2 frames" in capsys.readouterr().err


@pytest.mark.usefixtures("recorded_workflow_starts", "pushes_on_commit")
def test_the_door_mode_presses_through_rest(tenant: Tenant, owner: User, tmp_path: Path) -> None:
    creds = _credentials(tmp_path / "probe.json", tenant, owner, 1)
    doors = InProcessDoors()
    out = StringIO()

    status = probe.main(
        ["--credentials", str(creds), "--events", "3", "--client", "drive-box", "--json"],
        out,
        transport=doors,
    )

    assert status == 0, out.getvalue()
    measured = _json_line(out)
    paths = [(method, path) for method, path, _ in doors.calls]
    assert paths[0] == ("POST", "/api/v1/widgets/")
    touches = [p for p in paths[1:] if p[1].endswith("/touch/")]
    assert len(touches) == 3 == len(paths) - 1
    assert len(doors.sockets) == 1
    assert measured["basis"]["path"] == "dispatch"
    assert measured["basis"]["fallback"].startswith("relay every ")
    assert isinstance(measured["basis"]["relay_poll_seconds"], int)
    assert measured["basis"]["client"] == "drive-box"
    assert measured["basis"]["frames"] == 3
    assert set(measured) == {"value", "basis", "instrument"}


@pytest.mark.usefixtures("recorded_workflow_starts", "pushes_on_commit")
def test_fifty_sockets_each_receive_every_frame(
    tenant: Tenant, owner: User, tmp_path: Path
) -> None:
    cap = probe.declared_socket_caps(probe.BASE_PY)[0]
    needed = -(-SOCKETS // cap)
    creds = _credentials(tmp_path / "probe.json", tenant, owner, needed)
    doors = InProcessDoors()
    out = StringIO()

    status = probe.main(
        [
            "--credentials", str(creds), "--sockets", str(SOCKETS), "--events", str(EVENTS),
            "--load", "conc-8", "--json",
        ],
        out,
        transport=doors,
    )  # fmt: skip

    assert status == 0, out.getvalue()
    measured = _json_line(out)
    assert len(doors.sockets) == SOCKETS
    assert max(doors.sockets.count(token) for token in set(doors.sockets)) <= cap
    assert measured["basis"]["sockets"] == SOCKETS
    assert measured["basis"]["events"] == EVENTS
    assert measured["basis"]["frames"] == SOCKETS * EVENTS
    assert measured["basis"]["load"] == "conc-8"
    assert measured["basis"]["formula"]
    assert set(measured["value"]) == VALUE_KEYS


@pytest.mark.usefixtures("recorded_workflow_starts")
def test_a_missing_socket_frame_is_exit_2(
    tenant: Tenant, owner: User, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    creds = _credentials(tmp_path / "probe.json", tenant, owner, 1)

    status = probe.main(
        ["--credentials", str(creds), "--sockets", "2", "--events", "1", "--within", "1"],
        StringIO(),
        transport=InProcessDoors(),
    )

    assert status == 2
    assert "2 of 2 sockets missed press 1" in capsys.readouterr().err


@pytest.mark.usefixtures("recorded_workflow_starts")
def test_more_sockets_than_the_join_bound_allows_is_exit_2(
    tenant: Tenant, owner: User, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cap = probe.declared_socket_caps(probe.BASE_PY)[0]
    creds = _credentials(tmp_path / "probe.json", tenant, owner, 1)
    doors = InProcessDoors()

    status = probe.main(
        ["--credentials", str(creds), "--sockets", str(cap + 1)], StringIO(), transport=doors
    )

    assert status == 2
    assert "REALTIME_MAX_SOCKETS_PER_CREDENTIAL" in capsys.readouterr().err
    assert doors.calls == []


class CannedSocket:
    """A socket that hears every press at once, its frame stamped `occurred_at` `before` earlier."""

    def __init__(self, widget_id: str, before: float, *, stamped: bool = True) -> None:
        self.widget_id = widget_id
        self.before = before
        self.stamped = stamped

    async def frame(self, deadline: float) -> tuple[float, float, dict[str, Any]]:
        wall = time.time()
        frame: dict[str, Any] = {"name": probe.WIDGET_TOUCHED, "payload": {"id": self.widget_id}}
        if self.stamped:
            occurred = datetime.fromtimestamp(wall - self.before, tz=UTC)
            frame["occurred_at"] = occurred.isoformat().replace("+00:00", "Z")
        return time.perf_counter(), wall, frame

    async def close(self) -> None:
        return None


class CannedDoors:
    """REST answers and sockets from memory: no database, no network."""

    def __init__(self, before: float, *, stamped: bool = True) -> None:
        self.before = before
        self.stamped = stamped

    async def call(
        self, method: str, path: str, *, token: str, tenant: str, body: object = None
    ) -> tuple[int, dict[str, Any]]:
        return (201, {"id": "w-canned"}) if path.endswith("/widgets/") else (200, {})

    async def socket(self, *, token: str, tenant: str, within: float) -> CannedSocket:
        return CannedSocket("w-canned", self.before, stamped=self.stamped)


def _canned_credentials(path: Path) -> Path:
    path.write_text(json.dumps([{"tenant": "acme", "token": "t0"}]), encoding="utf-8")
    return path


@pytest.mark.django_db(transaction=False)
def test_the_line_carries_the_commit_based_lag_and_the_door_round_trip(tmp_path: Path) -> None:
    creds = str(_canned_credentials(tmp_path / "probe.json"))
    an_hour = 3600.0
    out = StringIO()
    argv = ["--credentials", creds, "--sockets", "2", "--events", "3"]
    assert probe.main([*argv, "--json"], out, transport=CannedDoors(an_hour)) == 0
    measured = _json_line(out)
    assert set(measured["value"]) == VALUE_KEYS
    assert Decimal(measured["value"]["p95_commit_ms"]) > Decimal(measured["value"]["p95_ms"])
    assert measured["basis"]["formula"] == probe.FORMULA_DOOR
    assert "occurred_at" in measured["basis"]["formula_commit"]
    assert "round trip" in measured["basis"]["formula_door"]
    assert measured["basis"]["clock"].startswith("undeclared")

    plain = StringIO()
    clock = "web=+0.000012s,drive=-0.000034s"
    assert probe.main([*argv, "--clock", clock], plain, transport=CannedDoors(an_hour)) == 0
    line = plain.getvalue().strip()
    assert line.startswith("realtime=p95_commit_ms="), line
    assert " p95_ms=" in line and " p95_door_ms=" in line and f" clock={clock}" in line


@pytest.mark.django_db(transaction=False)
def test_a_frame_without_occurred_at_is_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    creds = str(_canned_credentials(tmp_path / "probe.json"))
    status = probe.main(
        ["--credentials", creds, "--events", "1"],
        StringIO(),
        transport=CannedDoors(1.0, stamped=False),
    )
    assert status == 2
    assert "occurred_at" in capsys.readouterr().err


@pytest.mark.django_db(transaction=False)
def test_the_join_bound_is_read_from_the_named_settings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings_py = tmp_path / "base.py"
    settings_py.write_text(
        'X = env.int("REALTIME_MAX_SOCKETS_PER_CREDENTIAL", default=3)\n'
        'Y = env.int("REALTIME_MAX_SOCKETS_PER_TENANT", default=500)\n',
        encoding="utf-8",
    )
    creds = str(_canned_credentials(tmp_path / "probe.json"))
    argv = ["--credentials", creds, "--sockets", "4", "--settings-py", str(settings_py)]
    assert probe.main(argv, StringIO(), transport=CannedDoors(1.0)) == 2
    assert "REALTIME_MAX_SOCKETS_PER_CREDENTIAL=3" in capsys.readouterr().err
    argv[3] = "3"
    assert probe.main(argv, StringIO(), transport=CannedDoors(1.0)) == 0
