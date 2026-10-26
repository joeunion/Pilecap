"""The run ledger's wire shape — one schema, both doors (ADR workflows-6).

`WorkflowRunOut` is what the REST list, the REST detail, the MCP tools and the
replay answer all return, so a client that has learned to read one run has
learned to read all of them.

**What is deliberately not here is the run's input.** Temporal's history already
witnesses it and a second copy in this row would be two truths about one fact;
`input_digest` is the shape that answers the question the product actually has
— *is this the same work as last time* — without becoming a copy of somebody's
payload on a list endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from ninja import FilterLookup, FilterSchema, Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import ListPage, example, personal


class WorkflowRunFilter(FilterSchema):
    """The narrowings a client may ask for, declared rather than improvised."""

    status: Annotated[str | None, FilterLookup(q="status")] = None
    type: Annotated[str | None, FilterLookup(q="type")] = None


class WorkflowRunOut(Schema):
    """One run, as every door reports it."""

    # No field aliases, for the reason `comms.MessageOut` states in full: the
    # MCP transport serialises a tool result by alias, so an aliased field
    # answers under a different key at the machine door than at the human one.
    # `started_by_email` is a property on `WorkflowRun` instead.
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    #: The deterministic, house-shaped id (rule 18) — `<tenant>:<app>:<noun>:<key>`
    #: — which is what a person searches the Temporal UI on.
    workflow_id: str = Field(
        json_schema_extra=example("acme:example:onboard:0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21")
    )
    #: Temporal's own execution id. Empty while a start or a replay is still in
    #: flight: the row is written in the caller's transaction and this arrives
    #: from the server afterwards.
    run_id: str = Field(json_schema_extra=example("0195f1d4-9d2c-7c31-9d0b-0b6f6b3a6f21"))
    type: str = Field(json_schema_extra=example("WidgetOnboardingWorkflow"))
    status: str = Field(json_schema_extra=example("completed"))
    started_at: datetime
    finished_at: datetime | None
    #: The failing activity's own complaint, not the wrapper's — see
    #: `workflows.py::_reason`. Empty unless `status` is `failed`.
    error: str = Field(json_schema_extra=example(""))
    #: sha256 over the run's input, computed by the starters. Empty means
    #: unknown (a row written before the column existed), never "no input".
    #:
    #: **The example is `deadbeef` eight times, and the reason is arithmetic
    #: rather than taste.** A realistic 64-character digest is indistinguishable
    #: from a leaked key to a secret scanner — `detect-secrets` failed the full
    #: gate on the first version of this line — and every product cloned from
    #: this template inherits that scanner along with the example, so
    #: allow-listing it would have taught the clone to allow-list its own.
    #:
    #: The scanner's test is **Shannon entropy over the character
    #: distribution**, which repetition of a 16-symbol block does not lower at
    #: all: `9f2b1c7d4e6a8035` four times scores 4.0, exactly what a random
    #: digest scores. That was this comment's first answer and it was wrong; the
    #: second full-gate run said so. Eight distinct symbols score 2.156, under
    #: the 3.0 limit — and `deadbeef` reads as a sample to a person as well.
    input_digest: str = Field(
        json_schema_extra=example(
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        )
    )
    #: Who asked for it. `null`/`""` is **unknown**, not "nobody": rows written
    #: before ADR workflows-6, and platform runs the deployment owns rather
    #: than a person. A run with no recorded starter is nobody's own run and is
    #: never replayable.
    started_by_id: UUID | None
    started_by_email: str = Field(json_schema_extra=personal(example("dana@example.com")))
    created_at: datetime


class WorkflowRunPage(ListPage):
    """A page of runs — the list envelope, for a door with no query string.

    REST gets this shape from ninja's `@paginate` and never names it; the MCP
    tool returns a value rather than a response, so the same envelope has to be
    a schema it can declare. Deliberately the *same* envelope, so a machine
    client that has learned to unwrap the REST list does not learn a second one.
    """

    items: list[WorkflowRunOut]
