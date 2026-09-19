"""One export, answered by both doors, compared ON THE WIRE.

House rule 46: every door pair an app has owes a parity test in that app.
`apps/exports` has a REST door and an MCP door, so it owes `(rest, mcp)`, and
this module is the answer.

**Why a registry diff is not this.** House rule 17 proves a capability exists on
both doors; it cannot see the two doors *disagree* about one. Both times they
did in this tree, both registries were complete: once, REST rendered a response
by field name while the MCP transport rendered `structuredContent` by
**alias**, so one `Field(alias=...)` made the machine door answer `owner.email`
where the human door answered `owner_email`; another time, one consumer, one
person, two credentials, two different sets of frames. Neither is visible to a
diff of two registries.

**The capability under test is `retrieve an export`.** It is the representative
one on purpose: it is a read of the app's central row, both doors answer the
*same* schema, and a shared schema is exactly the condition under which the alias mismatch hid
— a value-by-value comparison of two `model_dump()`s of one schema cannot fail,
because both sides of it are the same call. So nothing here calls a tool
function: both doors are driven through the one real ASGI application, over
`httpx`, and `response.json()` is compared with `result["structuredContent"]`.

**This model publishes three COMPUTED strings and that is why this file
matters more here than usual.** `organization_slug`, `expires_at`,
`download_path` and `download_url` are model properties rather than schema
aliases — deliberately, because an alias is a NAME and the two doors do not
agree about names. Four opportunities for that alias-mismatch shape in one schema; this is
the test that would have caught any of them.

`transaction=True` because the MCP transport runs a tool body on a worker thread
with its own database connection, which cannot see an uncommitted row.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.authz import refusal_sentence
from apps.core.ids import uuid7
from apps.core.models import Grant, Membership
from apps.core.services import root_organization

# The transport harness, from the module that owns it. Copying it here would be
# a second thing to keep in step with the MCP protocol version.
from apps.core.tests.test_mcp import MCP_HEADERS, PROTOCOL_VERSION, running
from apps.exports.models import Export
from apps.files import storage as files_storage
from apps.files.storage import DOWNLOAD_URL_TTL_SECONDS

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.models import Tenant

#: House rule 46. The door pair this module answers for `apps/exports`, read by
#: the gate off this module-level assignment. The population is DERIVED from the
#: doors the app has — a REST door beside an `mcp.py` owes `(rest, mcp)` — and
#: this is the claim that it is answered here.
DOOR_PAIR = ("rest", "mcp")

DETAIL_URL = "/api/v1/exports/{}/"
MCP_URL = "/mcp"
JSON = "application/json"

#: `ExportOut`'s wire contract, written out rather than derived from the schema.
#: A pin derived from the thing it pins cannot fail; this one fails the day
#: somebody adds a field, which is when a reviewer should be looking.
EXPORT_KEYS = frozenset(
    {
        "id",
        "status",
        "scope",
        "tenant_id",
        "organization_id",
        "organization_slug",
        "requested_by_id",
        "manifest",
        "artifact_bytes",
        "error",
        "created_at",
        "updated_at",
        "completed_at",
        "expires_at",
        "download_url",
        "download_path",
    }
)

#: **RETIRED.** This module used to name the fields whose PRECISION the
#: two doors disagreed about. `config/mcp.py` now puts every machine-door answer
#: out through the HTTP door's own encoder, so the two doors write the same
#: bytes and there is no exception left to name.


def _rpc(method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
    """One JSON-RPC request body, spelled the way a real MCP client spells it."""
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


@pytest.fixture
def bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="exports-door-parity",
        actor=actor_for(user=owner, tenant=tenant),
    )
    return plaintext


@pytest.fixture
def stranger_bearer(other_tenant: Tenant, stranger: User) -> str:
    """A real token for somebody in the OTHER tenant.

    A fixture rather than a line in the test, because minting one touches the
    database and these tests are `async`: a synchronous ORM call inside an async
    function is `SynchronousOnlyOperation`, and a fixture runs on the
    synchronous side where it belongs.
    """
    _, plaintext = issue_token(
        user=stranger,
        tenant=other_tenant,
        name="stranger-parity",
        actor=actor_for(user=stranger, tenant=other_tenant),
    )
    return plaintext


@pytest.fixture
def root_slug(tenant: Tenant) -> str:
    """The tenant's root organization slug, read on the synchronous side."""
    return str(root_organization(tenant=tenant).slug)


@pytest.fixture
def export(tenant: Tenant, owner: User) -> Export:
    """One committed export for both doors to answer with.

    Written through the manager rather than through `create_export`: the service
    starts a durable run on commit, and this test is about how a row is
    RENDERED, not about how it is made. Marked `completed` with a key on it so
    that the two download fields — the pair most likely to disagree between the
    doors, because both are computed — actually have something to render.
    """
    row = Export.objects.create(
        tenant=tenant,
        organization=root_organization(tenant=tenant),
        requested_by=owner,
        scope=Export.Scope.TENANT,
        status=Export.Status.COMPLETED,
        # THE FILES GRAMMAR (XPr), and it is load-bearing here rather than
        # cosmetic: `download_url` presigns this key, and `files.storage`'s
        # `refuse_foreign_key` belt REFUSES a key outside the acting tenant's
        # prefix — so the old `"tenants/acme/parity-export.zip"` would not merely
        # look wrong, it would raise. Built through `version_key` rather than
        # typed, so the day the grammar moves this fixture moves with it.
        artifact_key=files_storage.version_key(tenant=tenant, file_pk=uuid7(), version=1),
        artifact_bytes=4096,
        manifest={"version": 1, "rows": 12, "models": []},
    )
    return row


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_two_doors_put_the_same_export_on_the_wire(
    bearer: str, export: Export, named_bucket: str
) -> None:
    """The same row over HTTP and over JSON-RPC: one key set, one set of values.

    The keys are asserted first and by themselves, because keys were the
    disagreement and values were not — a test that compared only values
    passed while the two doors described one row in two vocabularies.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(export.pk), headers={**bearer_header, "accept": JSON}
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
                        "clientInfo": {"name": "exports-door-parity", "version": "1"},
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
                    {"name": "get_export", "arguments": {"export_id": str(export.pk)}},
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
    assert set(rest_body) == EXPORT_KEYS

    assert set(over_mcp) == set(rest_body), (
        "The two doors describe the same export with different keys. "
        f"Only on MCP: {sorted(set(over_mcp) - set(rest_body))}; "
        f"only on REST: {sorted(set(rest_body) - set(over_mcp))}. "
        "A `Field(alias=...)` on a read schema does this: the MCP transport "
        "serialises `structuredContent` by alias and REST renders by field "
        "name. Resolve a relation or a computed string with a model property, "
        "not an alias (ADR example-3)."
    )

    # Every value, exactly, except the timestamps whose precision differs above
    # and `download_url`, which is not a value at all.
    #
    # **`download_url` is a FRESHLY SIGNED string** since XPr moved the archive
    # onto the files seam: it carries `X-Amz-Date` and a signature computed over
    # it, so two calls a second apart legitimately differ and comparing them
    # whole is a test that fails on the clock rather than on the doors. It was
    # caught exactly that way — green on a fast run, red across a second
    # boundary (`...215640Z` vs `...215641Z`) in the wide sweep — which is the
    # reason it is excluded here with a sentence rather than retried into
    # silence. What actually has to agree about it is compared properly in
    # `test_the_computed_download_pair_reads_the_same_on_both_doors`: the object
    # it points at, the host, the signed parameter set, and the TTL.
    for key in set(rest_body) - {"download_url"}:
        assert over_mcp[key] == rest_body[key], f"the two doors disagree about {key}"

    # ...and that it is PRESENT on both doors, which is the half this test still
    # owns: a door that dropped it would otherwise pass here unnoticed.
    assert (over_mcp["download_url"] is None) == (rest_body["download_url"] is None)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_computed_download_pair_reads_the_same_on_both_doors(
    bearer: str, export: Export, root_slug: str, named_bucket: str
) -> None:
    """The four properties that are NOT schema aliases, and the reason they are not.

    `organization_slug`, `expires_at`, `download_path` and `download_url` are all
    computed above the columns. An alias would have been the shorter way to write
    each of them and would have put four different key names on the machine door.
    Asserted as VALUES here, so the pin is not only about key sets.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(export.pk), headers={**bearer_header, "accept": JSON}
            )
            headers = {**MCP_HEADERS, **bearer_header}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "exports-download-parity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "download_export", "arguments": {"export_id": str(export.pk)}},
                    2,
                ),
            )

    rest_body = over_http.json()
    over_mcp = called.json()["result"]["structuredContent"]

    # The download tool is the ONE place the two doors answer different SHAPES —
    # a redirect over HTTP, a location over JSON-RPC — so what is compared is the
    # fields they share, which must agree exactly.
    assert set(over_mcp) == {"id", "download_url", "download_path", "artifact_bytes", "expires_at"}
    assert over_mcp["download_path"] == rest_body["download_path"]
    assert over_mcp["artifact_bytes"] == rest_body["artifact_bytes"]

    # `download_url` USED TO BE `None` on both doors, and the assertion was
    # `== ... is None`. XPr moved the archive onto the files seam, which always
    # signs (`files.storage.bucket_name()` refuses a deployment that has named no
    # bucket, so there is no un-signing world left), and XP-1's own ratified
    # either/or resolves to its first branch. So the pin becomes what it was
    # always FOR: the two doors compute this string the same way. Compared
    # field-by-field rather than whole, because a presigned URL carries
    # `X-Amz-Date` and a signature over it — two calls a few milliseconds apart
    # legitimately differ, and asserting equality of the raw strings would be a
    # test that fails on a slow machine.
    over_http_url = urlsplit(rest_body["download_url"])
    over_mcp_url = urlsplit(over_mcp["download_url"])
    assert over_http_url.path == over_mcp_url.path, "the two doors point at different objects"
    assert over_http_url.netloc == over_mcp_url.netloc
    signed_over_http = parse_qs(over_http_url.query)
    signed_over_mcp = parse_qs(over_mcp_url.query)
    assert set(signed_over_http) == set(signed_over_mcp), "differently signed URLs"
    # The TTL is the one signed parameter that must not vary: it is the files
    # seam's `DOWNLOAD_URL_TTL_SECONDS`, INHERITED rather than restated here
    # (the first of XPr's four re-point items), so a door that had grown its own
    # posture would show up as a different number on one side.
    assert signed_over_http["X-Amz-Expires"] == signed_over_mcp["X-Amz-Expires"]
    assert signed_over_http["X-Amz-Expires"] == [str(DOWNLOAD_URL_TTL_SECONDS)]
    # And the fourth computed string, on the door that publishes it: a property
    # rather than an alias, so both doors call it `organization_slug`.
    assert rest_body["organization_slug"] == root_slug


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_export_to_a_stranger(
    stranger_bearer: str, export: Export
) -> None:
    """Not-there and not-yours are one answer, and it is one answer at both doors."""
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {stranger_bearer}"}

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(export.pk), headers={**bearer_header, "accept": JSON}
            )
            headers = {**MCP_HEADERS, **bearer_header}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "exports-refusal-parity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_export", "arguments": {"export_id": str(export.pk)}},
                    2,
                ),
            )

    assert over_http.status_code == 404, over_http.text
    assert over_http.json()["code"] == "not_found"
    answered = called.json()["result"]
    assert answered.get("isError") is True
    assert "not_found" in str(answered["content"])


@pytest.fixture
def read_withheld(tenant: Tenant, owner: User) -> Grant:
    """One `withhold` row on the owner's own membership. **`export.read`, gone.**

    A withhold beats everything — "forbid overrides permit" — and it beats it
    for an owner too, which is what makes this the smallest world in which a
    perfectly ordinary credential is refused a read at both doors. Nothing about
    the role, the hat or the row changes: the only difference between this test
    and the one above it is this row.
    """
    membership = Membership.objects.filter(tenant=tenant).get(user=owner)
    return Grant.objects.create(
        tenant=tenant,
        membership=membership,
        permission="export.read",
        effect=Grant.Effect.WITHHOLD,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_both_doors_refuse_the_same_withheld_read_with_the_same_words(
    bearer: str, export: Export, read_withheld: Grant
) -> None:
    """**PR4.e.2 — rule 46's named case for Phase R.**

    A read is a permission now (ADR core-27), so there is a new refusal on both
    doors, and a new refusal is exactly where two doors come apart: one composes
    a body and the other stringifies an exception. Both go through
    `core.exceptions.wire_refusal`, and this is the test that says so — the code
    AND the sentence, not just the status.

    The sentence is read from `refusal_sentence` rather than typed, so the two
    doors are compared against the key's own prose and not against a third copy
    of it that could drift from both.

    *Absent (baseline `11b1a765`):* 200 on both doors, with the export in the
    body — the row a withheld reader could still read.
    """
    from config.asgi import build_application

    application = build_application()
    bearer_header = {"authorization": f"Bearer {bearer}"}
    sentence = refusal_sentence("export.read")

    async with running(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            over_http = await client.get(
                DETAIL_URL.format(export.pk), headers={**bearer_header, "accept": JSON}
            )
            headers = {**MCP_HEADERS, **bearer_header}
            await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "initialize",
                    {
                        "protocolVersion": PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "exports-read-parity", "version": "1"},
                    },
                    1,
                ),
            )
            called = await client.post(
                MCP_URL,
                headers=headers,
                json=_rpc(
                    "tools/call",
                    {"name": "get_export", "arguments": {"export_id": str(export.pk)}},
                    2,
                ),
            )

    assert over_http.status_code == 403, over_http.text
    assert over_http.json()["code"] == "forbidden"
    assert over_http.json()["detail"] == sentence

    answered = called.json()["result"]
    assert answered.get("isError") is True
    assert "forbidden" in str(answered["content"])
    assert sentence in str(answered["content"]), answered["content"]
