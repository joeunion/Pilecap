"""The run ledger's two doors, compared on the wire. **House rule 46's answer.**

`apps/workflows` has a REST door (`api.py`) and a machine door (`mcp.py`), so it
owes a `(rest, mcp)` parity test, and until this module it had none — it was one
of the five apps in rule 46's measured backlog.

## Why a registry diff is not this

House rule 17 already proves the two doors expose the same *capabilities*: it
diffs the two registries and would notice a tool that went missing. It is blind
to the failure this file is for — **the two doors answering the same question
differently** — and both times that happened in this tree, a test of exactly
this shape is what found it:

* REST renders a response by field name; the MCP transport renders a
  tool result's `structuredContent` **by alias**. A `Field(alias="owner.email")`
  made the machine door answer `owner.email` where the human door answered
  `owner_email`. One row, two key sets, every value equal — invisible to any
  test that compares values, and invisible to a registry diff, because both
  registries were complete.
* One consumer, one person, one `X-Org`, two credentials, two
  different sets of frames.

`WorkflowRunOut` carries a comment saying it has no aliases *for that reason*.
This module is what makes that comment a fact rather than an intention: the day
somebody adds one, this test goes red in the diff that added it.

## What is driven

Both doors, through the one real ASGI application — `config.asgi.
build_application()`, the object `scripts/serve.sh` hands uvicorn — over
`httpx`, with the **same bearer token** on both. Nothing here calls a tool
function directly: a tool function returns a `WorkflowRunOut`, and the earlier bug lived in
the serializer *between* that object and the client, which is the half a
direct call skips.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.models import Tenant

# The transport harness, from the module that owns it. Copying it here would be
# a second thing to keep in step with the MCP protocol version.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.workflows.models import WorkflowRun
from apps.workflows.services import record_run, workflow_id

#: House rule 46. The door pair this module answers for `apps/workflows`, read
#: by the gate off this module-level assignment.
DOOR_PAIR = ("rest", "mcp")

pytestmark = pytest.mark.django_db

DETAIL_URL = "/api/v1/runs/{}/"
MCP_URL = "/mcp"
JSON = "application/json"

# The run read shape, as a key set, written out rather than derived from
# `WorkflowRunOut` — a pin derived from the thing it pins cannot fail. This is
# the REST contract: both doors are held to it, and a rename that reaches the
# wire has to change this line, in the diff, where a reviewer sees it.
RUN_KEYS = frozenset(
    {
        "id",
        "workflow_id",
        "run_id",
        "type",
        "status",
        "started_at",
        "finished_at",
        "error",
        "input_digest",
        "started_by_id",
        "started_by_email",
        "created_at",
    }
)


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="door-parity", actor=actor_for(user=owner, tenant=tenant)
    )
    return plaintext


@pytest.fixture
def run(tenant: Tenant, owner: User) -> WorkflowRun:
    """One committed, finished run for both doors to answer with.

    Written through `record_run` — the service every starter goes through — so
    the row has the `input_digest` and the `started_by` that the read shape
    reports. It is closed rather than left running so that `finished_at` is a
    real timestamp on the wire: a `None` on both doors would agree trivially,
    and the two doors have disagreed about *rendering* before.
    """
    row = record_run(
        tenant=tenant,
        workflow_id=workflow_id(tenant=tenant, app="example", noun="widget", key="parity"),
        workflow_type="WidgetOnboardingWorkflow",
        input_digest="d" * 64,
        user=owner,
    )
    row.status = WorkflowRun.Status.COMPLETED
    row.run_id = "execution-parity"
    row.finished_at = row.started_at
    row.save()
    return row


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_key_set_on_the_wire(
    bearer: str, run: WorkflowRun
) -> None:
    """The same run, over HTTP and over JSON-RPC: one key set, not two.

    The assertion is on the **keys**, deliberately and by itself. Values were
    never the disagreement — `owner.email` and `owner_email` carried the
    same string — so a test that compared values passed while the two doors
    described one row in two vocabularies. Comparing the key sets is the
    assertion that could have failed on the day an alias landed.

    The values are compared too, on the second pass below, because a ledger that
    agreed on keys and disagreed on `status` would be worse than either.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(run.pk), headers={**bearer_header, "accept": JSON}
            )
            assert over_http.status_code == 200, over_http.text

            headers = {**MCP_HEADERS, **bearer_header}
            initialize = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "run-door-parity", "version": "1"},
                    },
                    1,
                ),
            )
            assert initialize.status_code == 200, initialize.text

            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_run", "arguments": {"run_id": str(run.pk)}},
                    2,
                ),
            )
            assert called.status_code == 200, called.text

    answered = called.json()
    assert "error" not in answered, answered
    over_mcp = answered["result"]["structuredContent"]
    rest_body = over_http.json()

    # The REST body first, against the written-out contract: whatever the two
    # doors are made to agree on, they agree on *this*. Without this half, a
    # future fix could reconcile the doors by moving REST, which is the one
    # direction that breaks a client.
    assert set(rest_body) == RUN_KEYS

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same run with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field "
        "name. Resolve a relation with a model property, not an alias — "
        "`WorkflowRunOut.started_by_email` is this schema's own precedent."
    )

    # The identifying half of the row, value for value. Not every key: the two
    # doors legitimately render a datetime through the same serializer and
    # pinning all twelve here would re-assert what the key-set comparison and
    # `test_api.py` already own. These four are what a caller acts on.
    for key in ("id", "workflow_id", "status", "started_by_email"):
        assert str(over_mcp[key]) == str(rest_body[key]), (
            f"The two doors disagree about {key!r}: "
            f"REST says {rest_body[key]!r}, MCP says {over_mcp[key]!r}."
        )
