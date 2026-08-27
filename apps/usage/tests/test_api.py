"""The read door as a client meets it: the credential, the ceiling, the number.

**This app has two routes and no write door, and both halves are asserted
here.** The report and the vocabulary it is read against are the whole of the
HTTP surface (ADR usage-1, § Doors), and
`test_there_is_no_write_door` is what keeps the absence a decision rather than a
gap somebody fills in later: a client that could send a usage body could mint or
dispute its own bill.

Six properties, each of which can be wrong in a way that looks right:

* **the credential** — no credential is `401 unauthenticated`, not an empty
  report. A report that answered zero to a stranger would look exactly like a
  report answered to somebody with nothing;
* **the ceiling** — a token minted for another section is refused by name, and
  the name it is refused with is the one to go and ask for (`usage:read`);
* **the number** — the value equals the sum of the day subtotals the server
  itself sent, recomputed here from the wire body rather than from the selector
  (ADR core-7);
* **the hat** — a branch's report never tallies a sibling's consumption, over
  the wire and not only in the selector (house rule 24; the anti-oracle) — and
  a hat that was SENT and did not resolve is refused rather than answered with
  a bill of zero;
* **the vocabulary** — a meter this deployment does not declare is refused
  naming what IS declared, and the catalogue that says so is one request away.
  Zero-filling can only mean "none" once "I asked the wrong question"
  has somewhere else to go.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.services import issue_token
from apps.core.actor import actor_for
from apps.core.middleware import ORG_HEADER
from apps.core.models import Organization, Tenant
from apps.usage import meters as meters_module
from apps.usage.services import record_usage
from apps.usage.tests.conftest import METER, OTHER_METER, World
from apps.usage.types import METERS_DESTINATION

pytestmark = pytest.mark.django_db

URL = "/api/v1/usage/"
METERS_URL = "/api/v1/meters/"
JSON = "application/json"

#: A fixed instant, so a run at 23:59:59 UTC does not bucket its rows into two
#: days — and so the window under test is named rather than "whenever this ran".
NOON = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
ON = NOON.date().isoformat()

#: The report's wire shape, written out rather than derived from the schema — a
#: pin taken from the thing it pins cannot fail. A field added or renamed on the
#: published contract has to change this line, in the diff, where it is read.
REPORT_KEYS = frozenset({"period", "starts_on", "ends_on", "meters"})


def _bearer(plaintext: str) -> dict[str, str]:
    return {"authorization": f"Bearer {plaintext}"}


def _body(response: Any) -> dict[str, Any]:
    return dict(json.loads(response.content))


def _record(world: World, **overrides: Any) -> Any:
    call: dict[str, Any] = {
        "tenant": world.tenant,
        "actor": world.north_actor,
        "meter": METER,
        "quantity": Decimal("30"),
        "ref": world.widget,
        "idempotency_key": "wire-1",
        "occurred_at": NOON,
    }
    call.update(overrides)
    return record_usage(**call)


# --- 0 · the mount ------------------------------------------------------------


def test_the_route_is_mounted_where_the_document_says() -> None:
    """`usage-detail` resolves to `/api/v1/usage/`, and nothing else does.

    The url_name is what `config/api.py` binds, what house rule 17 derives the
    MCP twin from and what a reverse in any other app would name — so it is
    asserted rather than assumed, beside the literal every other test in this
    module sends. A `PREFIX` edited without meaning to fails here first.
    """
    assert reverse("api:usage-detail") == URL


# --- 1 · the credential -------------------------------------------------------


def test_the_report_is_refused_without_a_credential(api: Client) -> None:
    """No credential is a refusal, never an empty report.

    The distinction is the whole of it: a stranger who got `{"meters": {}}` back
    would be told that this account consumed nothing, which is a statement about
    somebody else's data made to a person with no right to hear it.
    """
    response = api.get(URL)

    assert response.status_code == 401, response.content
    assert _body(response)["code"] == "unauthenticated"


# --- 2 · the ceiling ----------------------------------------------------------


def test_a_token_scoped_elsewhere_is_refused_and_told_which_scope(
    api: Client, world: World
) -> None:
    """The ceiling probe. A token minted for another section never reads usage.

    And the refusal names `usage:read`, because "no" without the name of what to
    ask for leaves the agent's human with nothing to act on.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="elsewhere",
        scopes=["widgets:read"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(URL, headers=_bearer(plaintext))

    assert response.status_code == 403, response.content
    body = _body(response)
    assert body["code"] == "insufficient_scope"
    assert "usage:read" in body["detail"], body
    assert body["remedies"], "a refusal with no way out is a dead end with a status code"


def test_a_token_scoped_for_usage_reads(api: Client, world: World, a_declared_meter: str) -> None:
    """The other half of the same property: the narrow token that is enough.

    Without it the test above would pass on a door that refused everybody.
    """
    _record(world)
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="narrow",
        scopes=["usage:read"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(f"{URL}?period=month&on={ON}", headers=_bearer(plaintext))

    assert response.status_code == 200, response.content
    assert set(_body(response)) == REPORT_KEYS


# --- 3 · the number -----------------------------------------------------------


def test_the_report_is_the_seeded_ledger_and_re_adds(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """**Two days, one total, and a basis that adds up.**

    The recomputation is done here from the body the server sent, using the
    formula the server sent — so a server that shipped `value=42.5` beside days
    summing to 30 fails, which is what makes the basis a contract rather than
    decoration.
    """
    _record(world, quantity=Decimal("30"), idempotency_key="d1")
    _record(
        world,
        quantity=Decimal("12.5"),
        occurred_at=NOON + timedelta(days=1),
        idempotency_key="d2",
    )
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(f"{URL}?period=month&on={ON}", headers=_bearer(plaintext))

    assert response.status_code == 200, response.content
    body = _body(response)
    assert body["period"] == "month"
    assert body["starts_on"] == "2026-08-01"
    assert body["ends_on"] == "2026-08-31"

    measured = body["meters"][METER]
    # The scale is the column's — `quantity` is `Decimal(19, 4)` — and it
    # survives the sum and the wire. Pinned at four places rather than compared
    # as a number, because "42.5000" and 42.5 are the same quantity and only one
    # of them is what a client receives.
    assert measured["value"] == "42.5000", "a Decimal on the wire is a string, not a float"
    assert measured["basis"]["formula"] == "sum(day_totals)"
    inputs = measured["basis"]["inputs"]
    assert len(inputs) == 31, "every day of the window is in the basis, the empty ones too"
    assert inputs["2026-08-12"] == "30.0000"
    assert inputs["2026-08-13"] == "12.5000"
    recomputed = sum(Decimal(str(value)) for value in inputs.values())
    assert recomputed == Decimal(measured["value"])


def test_a_meter_that_was_asked_for_and_never_fired_answers_zero(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """A meter that never fired answers zero rather than going missing.

    A key missing from a mapping cannot say which, so a named meter comes back
    at zero rather than being left out.
    """
    _record(world)
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(
        f"{URL}?period=month&on={ON}&meters={METER}&meters={OTHER_METER}",
        headers=_bearer(plaintext),
    )

    assert response.status_code == 200, response.content
    meters = _body(response)["meters"]
    assert set(meters) == {METER, OTHER_METER}
    assert Decimal(meters[OTHER_METER]["value"]) == Decimal(0)


def test_a_window_this_door_does_not_bucket_is_refused(api: Client, world: World) -> None:
    """`?period=year` is refused rather than quietly rounded to something else.

    The two windows are a bucketing decision somebody made (`types.PeriodKind`);
    a door that guessed at a third would be answering a question nobody asked.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(f"{URL}?period=year", headers=_bearer(plaintext))

    assert response.status_code == 400, response.content
    assert _body(response)["code"] == "invalid"


# --- 4 · the hat --------------------------------------------------------------


def test_a_branch_never_tallies_a_sibling_over_the_wire(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """The anti-oracle, one level down (house rule 24), at the door.

    North consumed; south did not. The root's report tallies both branches and
    north's report tallies only north — so south's zero is a measurement rather
    than an empty database.
    """
    _record(world, actor=world.north_actor, quantity=Decimal("30"), idempotency_key="north")
    _record(world, actor=world.south_actor, quantity=Decimal("70"), idempotency_key="south")

    _, root_token = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )
    _, north_token = issue_token(
        user=world.north_admin,
        tenant=world.tenant,
        name="north",
        scopes=["usage:read"],
        actor=actor_for(user=world.north_admin, tenant=world.tenant),
    )

    whole = api.get(f"{URL}?period=month&on={ON}", headers=_bearer(root_token))
    branch = api.get(f"{URL}?period=month&on={ON}", headers=_bearer(north_token))

    assert whole.status_code == 200, whole.content
    assert branch.status_code == 200, branch.content
    assert Decimal(_body(whole)["meters"][METER]["value"]) == Decimal("100")
    assert Decimal(_body(branch)["meters"][METER]["value"]) == Decimal("30")


# --- 5 · the absence that is the contract -------------------------------------


def test_there_is_no_write_door(api: Client, tenant: Tenant, world: World) -> None:
    """**Door-less by design, asserted rather than assumed** (ADR usage-1).

    A client that could send a usage body could mint or dispute its own bill, so
    `record_usage` is reached from activities and services and from no route and
    no tool. A `POST` here is answered by the mount as a method this resource
    does not have — and the day somebody adds one, this test is what says so.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.post(
        URL,
        data=json.dumps({"meter": METER, "quantity": "1"}),
        content_type=JSON,
        headers=_bearer(plaintext),
    )

    assert response.status_code == 405, response.content


# --- 6 · the vocabulary ---------------------------------------------------------


def test_the_meters_route_is_mounted_where_the_document_says() -> None:
    """`meter-list` resolves to `/api/v1/meters/` — a resource, not this app's label.

    The first path segment names what is being listed (ADR api-2). The report's
    own mount is asserted above and both are pinned here rather than assumed,
    because this app now serves two resources out of one router and an edited
    `PREFIX` would move both at once.
    """
    assert reverse("api:meter-list") == METERS_URL


def test_the_vocabulary_is_refused_without_a_credential(api: Client) -> None:
    """Which meters a product bills on is not something a stranger reads.

    The catalogue is the same for every customer, which makes it tempting to
    leave open; it is still a fact about the product we have not decided to
    publish, so the router's `auth=` applies here exactly as to the report.
    """
    response = api.get(METERS_URL)

    assert response.status_code == 401, response.content
    assert _body(response)["code"] == "unauthenticated"


def test_the_vocabulary_is_the_live_registry(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """Derived from the installed apps' own `meters.py`, in the list envelope.

    Asserted against the registry the fixture planted rather than against a
    written-out list: a catalogue test that pinned the names would be a second
    hand-listed vocabulary, which is the thing this route exists not to be.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(METERS_URL, headers=_bearer(plaintext))

    assert response.status_code == 200, response.content
    body = _body(response)
    assert set(body) == {"items", "has_more", "next_cursor", "count"}
    assert body["count"] is None, "a total costs a statement; it arrives only when asked for"
    assert body["items"] == [
        {"name": METER, "app": "example"},
        {"name": OTHER_METER, "app": "example"},
    ]


def test_a_meter_this_deployment_does_not_declare_is_refused_not_zero_filled(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """A typo and a real meter at zero stop being the same answer.

    `?meters=not.a.meter` used to come back `200` zero-filled while this
    operation's contract promised the zero-filling was there "so you can tell
    none from I asked the wrong question". Now it is a refusal that names the
    vocabulary and carries the way out — the catalogue route — as a remedy,
    which is what an agent needs to ask its human for the right spelling.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(
        f"{URL}?period=month&on={ON}&meters=not.a.meter&meters={METER}",
        headers=_bearer(plaintext),
    )

    assert response.status_code == 400, response.content
    body = _body(response)
    assert body["code"] == "invalid"
    said = " ".join(body["errors"]["meters"])
    assert "not.a.meter" in said, body
    assert METER in said, "the refusal says what the vocabulary IS, not only that this is not it"
    assert METERS_DESTINATION in [remedy["destination"] for remedy in body["remedies"]], body


def test_a_meter_that_is_declared_is_not_refused(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """The other half: the check refuses a name, never the act of naming one.

    Without this the test above would pass on a door that refused every
    `?meters=` it was given.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(f"{URL}?period=month&on={ON}&meters={METER}", headers=_bearer(plaintext))

    assert response.status_code == 200, response.content
    assert set(_body(response)["meters"]) == {METER}


# --- 7 · the hat that was sent and did not resolve -------------------------------


def test_a_sent_but_unresolved_hat_is_refused_rather_than_billed_at_zero(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """A fat-fingered `X-Org` is a refusal, never a bill of zero.

    `resolve_org` fails closed to `None`, which is right for a read of rows and
    wrong for a total: `200 {"meters": {}}` is the sentence "you consumed
    nothing", said convincingly, to somebody who mistyped. The refusal is the
    `403` this operation's contract has always promised, and it names the header
    so the caller knows which of the two they got wrong.

    **It is now the PLATFORM's refusal and not this app's** (ADR core-21).
    This route's own guard was the first place the hazard was closed, and one
    app's copy of a platform law is how the empty-`X-Org` hole came to be
    open here while its neighbours were untouched. The law moved to
    `core.middleware.addressing_refusal`, which every door asks before any route
    runs — so the code is `addressing_header_not_honoured`, the detail names the
    header rather than the slug (the anti-oracle pin: foreign and nonexistent are
    byte-identical), and the guard below is now unreachable belt.
    """
    _record(world)
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(
        f"{URL}?period=month&on={ON}",
        headers={**_bearer(plaintext), ORG_HEADER: "nosuchorg"},
    )

    assert response.status_code == 403, response.content
    body = _body(response)
    assert body["code"] == "addressing_header_not_honoured"
    assert ORG_HEADER in body["detail"], body
    assert f"header:{ORG_HEADER}" in [remedy["destination"] for remedy in body["remedies"]], body


def test_a_hat_in_another_tenant_is_refused_the_same_way(
    api: Client, world: World, other_root_org: Organization, a_declared_meter: str
) -> None:
    """A slug that exists — elsewhere — is the same refusal, and deliberately so.

    Telling "no such organization" apart from "not yours" would make this route
    an existence oracle over another customer's org names. Both are "not one you
    can act as", which is also the truth — and since ADR core-21 they are not
    merely the same code but the same BYTES, because the platform's refusal
    names the header and never the slug.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(
        f"{URL}?period=month&on={ON}",
        headers={**_bearer(plaintext), ORG_HEADER: other_root_org.slug},
    )
    absent = api.get(
        f"{URL}?period=month&on={ON}",
        headers={**_bearer(plaintext), ORG_HEADER: "nosuchorg"},
    )

    assert response.status_code == 403, response.content
    assert _body(response)["code"] == "addressing_header_not_honoured"
    assert response.content == absent.content


def test_sending_no_hat_at_all_is_untouched(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """The other half: only a hat that was SENT and failed is refused.

    A caller who sends no `X-Org` still gets their default node's report, which
    is the behaviour every existing client depends on — and the reason the check
    reads the header rather than the resolved value, which cannot tell the two
    apart.
    """
    _record(world)
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(f"{URL}?period=month&on={ON}", headers=_bearer(plaintext))

    assert response.status_code == 200, response.content
    assert Decimal(_body(response)["meters"][METER]["value"]) == Decimal("30")


def test_a_hat_the_caller_really_holds_still_reads(
    api: Client, world: World, a_declared_meter: str
) -> None:
    """And a good `X-Org` is honoured, so the refusal above is not a blanket one."""
    _record(world, actor=world.north_actor, idempotency_key="north-hat")
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    response = api.get(
        f"{URL}?period=month&on={ON}",
        headers={**_bearer(plaintext), ORG_HEADER: world.north.slug},
    )

    assert response.status_code == 200, response.content
    assert Decimal(_body(response)["meters"][METER]["value"]) == Decimal("30")


# --- 8 · the published example is a promise --------------------------------------
#
# **No `a_declared_meter` anywhere in this section, and that is the point.** The
# document is rendered off the LIVE registry, so a test that patched the
# registry would be comparing a published example against a vocabulary no
# deployment has. These drive the example a stranger actually reads.


def _published_meters_example() -> dict[str, Any]:
    """`UsageReportOut.meters`'s example, read off the document a client fetches.

    Off the rendered document rather than off the schema class, deliberately:
    the defect this closes is a thing a stranger reads in the reference page and
    in `get_usage.outputSchema`, and both of those are this node.
    """
    from config.api import api as contract

    document = contract.get_openapi_schema()
    node = document["components"]["schemas"]["UsageReportOut"]["properties"]["meters"]
    return dict(node["example"])


def test_the_published_example_names_meters_this_deployment_declares(
    api: Client, world: World
) -> None:
    """**The repro.** The example key, against `GET /meters/`.

    The example was aspirational before this refusal existed —
    `completions.tokens.input` named an app that does not exist yet — and the
    undeclared-meter refusal turned aspiration into a `400` a stranger hits on
    first copy-paste. The
    published vocabulary and the published example are two views of one registry
    and this is the assertion that they are.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )

    catalogue = api.get(METERS_URL, headers=_bearer(plaintext))
    assert catalogue.status_code == 200, catalogue.content
    published = {item["name"] for item in _body(catalogue)["items"]}
    assert published, "the deployment declares no meters — this test would pass vacuously"

    assert set(_published_meters_example()) <= published, (
        "the published example names a meter GET /api/v1/meters/ does not list; "
        f"example keys {sorted(_published_meters_example())}, vocabulary {sorted(published)}"
    )


def test_the_published_example_is_answered_rather_than_refused(api: Client, world: World) -> None:
    """The same claim as a DRIVE: paste the example's key back and get a report.

    The test above compares two documents; this one is the story the finding is
    about — somebody copies what the reference page shows them and sends it. A
    `400` here is the product refusing its own documentation.
    """
    _, plaintext = issue_token(
        user=world.owner,
        tenant=world.tenant,
        name="root",
        scopes=["*"],
        actor=actor_for(user=world.owner, tenant=world.tenant),
    )
    keys = sorted(_published_meters_example())
    assert keys, "an example with no meters in it cannot show a caller the shape"

    query = "&".join(f"meters={key}" for key in keys)
    response = api.get(f"{URL}?period=month&on={ON}&{query}", headers=_bearer(plaintext))

    assert response.status_code == 200, response.content
    assert set(_body(response)["meters"]) == set(keys)


def test_the_example_is_derived_and_follows_the_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It is DERIVED, not a constant that happens to be right today.

    A hand-keyed example is correct until the day the vocabulary moves, and
    nothing says so — which is exactly how `completions.tokens.input` survived
    into a published document. Plant a registry, re-render, and the example
    follows it: that is what makes the two tests above properties of the
    mechanism rather than of one string.

    The registry is patched on `apps.usage.meters` and read back through the
    rendered document, so the whole path — the schema's `json_schema_extra`
    hook, the derivation, the OpenAPI build — is what is being exercised.
    """
    monkeypatch.setattr(
        meters_module,
        "declared_meters",
        lambda: {"zzz": frozenset({"zzz.planted.things"})},
    )

    assert set(_published_meters_example()) == {"zzz.planted.things"}


def test_a_deployment_with_no_meters_publishes_an_empty_example(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other branch: nothing declared, nothing shown — and nothing invented.

    A product that deletes `apps/files` before declaring a meter of its own has
    a read door that can only ever answer `{"meters": {}}`. There is no name the
    example could carry that the door would not refuse, so it carries none. The
    branch is driven rather than argued because "it degrades sensibly" is the
    kind of claim that is true until somebody adds a placeholder.
    """
    monkeypatch.setattr(meters_module, "declared_meters", dict)

    assert _published_meters_example() == {}
