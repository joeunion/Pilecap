"""The doors drive on the wire: the worked noun through REST, MCP and its event; a planted part."""

# does-not-cover: the served stack — the drive runs over the in-process application `wire()` serves.
# does-not-cover: a worker — the runs are the wire's own rows; how far along each is, the test says.

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.core.management import call_command

from quality.djb.rituals import drive_doors


def _seeded() -> tuple[Any, Any]:
    """`manage.py seed`'s tenant and owner."""
    from apps.accounts.models import User
    from apps.core.models import Tenant

    call_command("seed", "--force", stdout=io.StringIO())
    return Tenant.objects.get(slug="acme"), User.objects.get(email="owner@example.com")


def _wire_runs(
    tenant: Any, owner: Any, state: str, bound: float = 1.0
) -> tuple[drive_doors.Runs, list[drive_doors.RunRef]]:
    """The owner's run rows since now, every one answering `state` — the wire has no worker."""
    runs = drive_doors.live_runs(tenant, owner, datetime.now(UTC))
    asked: list[drive_doors.RunRef] = []

    async def probe(ref: drive_doors.RunRef) -> str:
        asked.append(ref)
        return state

    runs.probe, runs.bound = probe, bound
    return runs, asked


async def _drive(
    seeded: tuple[Any, Any] | None = None, state: str = drive_doors.PARKED
) -> tuple[drive_doors.Drive, list[drive_doors.RunRef]]:
    """One live drive's shape on the wire: a token opened, the drive, the token closed."""
    from apps.core.tests.wire import wire

    tenant, owner = seeded or await sync_to_async(_seeded)()
    reader = sync_to_async(drive_doors.live_event_reader(tenant, owner))
    token = await sync_to_async(drive_doors.open_token)(tenant, owner)
    runs, asked = _wire_runs(tenant, owner, state)
    try:
        async with wire() as client:
            return await drive_doors.drive(client, token.plaintext, "Widget", reader, runs), asked
    finally:
        await sync_to_async(drive_doors.close_token)(tenant, owner, token.name)


def _live_drive_tokens(owner: Any) -> list[str]:
    return [t.name for t in drive_doors.leftover_tokens(owner)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_worked_noun_prints_four_bodies_and_its_doors_agree(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result, asked = await _drive()
    assert asked, "the create's onboarding run was never asked whether it settled"
    assert result.event == "example.widget.updated"
    assert len(result.bodies) == 4
    rest, over_mcp, patched, payload = result.bodies.values()
    assert rest["id"] == over_mcp["id"] == patched["id"] == payload["id"]
    assert "patched drive-" in rest["notes"]
    assert result.personal == {"owner_email", "owner_name"}
    assert drive_doors.report(result) == 0
    said = capsys.readouterr().out
    assert said.count("\n== ") + said.startswith("== ") == 4 + 3
    assert said.splitlines()[-1] == "doors agree: Widget · widget_entry"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_child_the_noun_records_is_driven_under_the_row_on_both_doors() -> None:
    result, _ = await _drive()
    assert list(result.children) == ["widget_entry"]
    listed, over_mcp, recorded = result.children["widget_entry"].values()
    rest_row = next(iter(result.bodies.values()))
    assert listed["id"] == over_mcp["id"] == recorded["id"]
    assert listed["widget_id"] == rest_row["id"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_planted_child_divergence_names_the_child_and_its_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from apps.example import mcp
    from apps.example.schemas import WidgetEntryOut

    class Planted:
        """The MCP door's child `Out`, edited: its rows say another note than the REST door's."""

        @staticmethod
        def from_orm(entry: Any) -> WidgetEntryOut:
            return WidgetEntryOut.from_orm(entry).model_copy(update={"note": "planted"})

    monkeypatch.setattr(mcp, "WidgetEntryOut", Planted)
    result, _ = await _drive()
    assert drive_doors.report(result) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert last.startswith("doors disagree: widget_entry — REST and MCP disagree"), last
    assert "'note'" in last, last


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_planted_mcp_divergence_names_the_first_differing_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import config.mcp  # noqa: F401 — the server is built before the plant, or its tools lose their schema
    from apps.example import mcp
    from apps.example.schemas import WidgetOut

    class Planted:
        """The MCP door's `Out`, edited: its rows say other notes than the REST door's."""

        @staticmethod
        def from_orm(widget: Any) -> WidgetOut:
            return WidgetOut.from_orm(widget).model_copy(update={"notes": "planted"})

    monkeypatch.setattr(mcp, "WidgetOut", Planted)
    result, _ = await _drive()
    assert drive_doors.report(result) == 1
    last = capsys.readouterr().out.splitlines()[-1]
    assert last.startswith("doors disagree: REST and MCP disagree for one viewer — 'notes':"), last


@pytest.mark.django_db
def test_a_dead_server_is_named_before_the_seed(capsys: pytest.CaptureFixture[str]) -> None:
    assert drive_doors.main(["Widget", "--base", "http://127.0.0.1:9", "--tenant", "zz"]) == 2
    assert (
        capsys.readouterr()
        .out.splitlines()[-1]
        .startswith("could not drive: nothing serves at http://127.0.0.1:9")
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_two_drives_in_a_row_on_one_seed_agree_and_leave_no_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    seeded = await sync_to_async(_seeded)()
    first, _ = await _drive(seeded)
    second, _ = await _drive(seeded)
    assert drive_doors.report(first) == 0
    assert drive_doors.report(second) == 0
    assert capsys.readouterr().out.count("doors agree") == 2
    assert await sync_to_async(_live_drive_tokens)(seeded[1]) == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_run_that_never_settles_is_could_not_look_naming_it() -> None:
    with pytest.raises(
        drive_doors.CouldNotDrive, match=r"run acme:example:widget:\S+ .* did not settle"
    ):
        await _drive(state=drive_doors.BUSY)


@pytest.mark.django_db
def test_a_drive_token_is_per_run_and_a_leftover_is_revoked_first() -> None:
    from apps.core.tests.wire import bearer

    tenant, owner = _seeded()
    bearer(user=owner, tenant=tenant, name="drive-doors")
    token = drive_doors.open_token(tenant, owner)
    assert token.revoked_stale == ["drive-doors"]
    assert re.fullmatch(r"drive-doors-\d{8}T\d{12}Z", token.name), token.name
    assert _live_drive_tokens(owner) == [token.name]
    assert drive_doors.close_token(tenant, owner, token.name) == token.name
    assert _live_drive_tokens(owner) == []
