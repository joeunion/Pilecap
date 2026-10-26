"""One export, answered by both doors, compared on the wire (rule 46).

Both doors are driven through the one ASGI application: a shared schema hides an alias mismatch from
any comparison of two `model_dump()`s. `transaction=True`: a tool body runs on its own connection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.core.actor import actor_for
from apps.core.ids import uuid7
from apps.core.services import root_organization
from apps.core.tests.doors import assert_four_doors
from apps.core.tests.wire import MCP_HEADERS, MCP_URL, bearer, initialize, rpc, wire
from apps.events.models import Event
from apps.exports.events import EXPORT_REQUESTED
from apps.exports.models import Export
from apps.exports.services import create_export
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


@pytest.fixture
def owner_bearer(tenant: Tenant, owner: User) -> str:
    """A real token for the owner — the one credential both doors accept."""
    return bearer(user=owner, tenant=tenant, name="exports-door-parity")


@pytest.fixture
def stranger_bearer(other_tenant: Tenant, stranger: User) -> str:
    """A real token for somebody in the other tenant, minted on the synchronous side."""
    return bearer(user=stranger, tenant=other_tenant, name="stranger-parity")


async def _both(token: str, url: str, tool: str, export_id: str) -> tuple[httpx.Response, Any]:
    """The REST answer at `url` and the JSON-RPC answer of `tool`, for one credential."""
    credential = {"authorization": f"Bearer {token}"}
    async with wire() as client:
        over_http = await client.get(url, headers={**credential, "accept": JSON})
        await initialize(client, credential, "exports-door-parity")
        called = await client.post(
            MCP_URL,
            headers={**MCP_HEADERS, **credential},
            json=rpc("tools/call", {"name": tool, "arguments": {"export_id": export_id}}, 2),
        )
    assert called.status_code == 200, called.text
    return over_http, called.json()


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
    owner_bearer: str, export: Export, named_bucket: str
) -> None:
    """The same row over HTTP and over JSON-RPC: one key set, one set of values.

    The keys are asserted first and by themselves, because keys were the
    disagreement and values were not — a test that compared only values
    passed while the two doors described one row in two vocabularies.
    """
    over_http, raw = await _both(
        owner_bearer, DETAIL_URL.format(export.pk), "get_export", str(export.pk)
    )

    assert over_http.status_code == 200, over_http.text
    assert "error" not in raw, raw
    over_mcp = raw["result"]["structuredContent"]
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
    owner_bearer: str, export: Export, root_slug: str, named_bucket: str
) -> None:
    """The four properties that are NOT schema aliases, and the reason they are not.

    `organization_slug`, `expires_at`, `download_path` and `download_url` are all
    computed above the columns. An alias would have been the shorter way to write
    each of them and would have put four different key names on the machine door.
    Asserted as VALUES here, so the pin is not only about key sets.
    """
    over_http, raw = await _both(
        owner_bearer, DETAIL_URL.format(export.pk), "download_export", str(export.pk)
    )

    rest_body = over_http.json()
    over_mcp = raw["result"]["structuredContent"]

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
    over_http, raw = await _both(
        stranger_bearer, DETAIL_URL.format(export.pk), "get_export", str(export.pk)
    )

    assert over_http.status_code == 404, over_http.text
    assert over_http.json()["code"] == "not_found"
    answered = raw["result"]
    assert answered.get("isError") is True
    assert "not_found" in str(answered["content"])


@pytest.fixture
def requested(tenant: Tenant, owner: User, recorded_workflow_starts: None) -> Export:
    """An export asked for through the service, so its `requested` event is on the spine."""
    actor = actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))
    return create_export(tenant=tenant, actor=actor, scope=Export.Scope.TENANT)


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_doors_and_the_event_tell_one_export(
    owner_bearer: str, requested: Export, named_bucket: str
) -> None:
    """REST, MCP and the recorded `exports.export.requested` payload are one row (rule 46)."""
    export = requested
    over_http, raw = await _both(
        owner_bearer, DETAIL_URL.format(export.pk), "get_export", str(export.pk)
    )
    assert over_http.status_code == 200, over_http.text
    recorded = await Event.objects.aget(name=EXPORT_REQUESTED, tenant=export.tenant)
    assert_four_doors(
        rest=over_http.json(),
        mcp=raw["result"]["structuredContent"],
        event_payload=recorded.payload,
    )
