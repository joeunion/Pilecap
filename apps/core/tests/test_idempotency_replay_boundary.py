"""Which refusals a key may replay, and which ones were never the key's answer.

**ADR core-23** (numbered core-19 in the lead's validation pass, where the id
collided with the live ADR core-19 for the rate-limit headers). `_remember` used
to hold exactly one line: **below 500 is a decision, so it replays**. That line
is right about everything a *service* decided and wrong about everything decided
in **front** of one.

The reproduced class: a client sends `POST` with `Idempotency-Key: K` and
a broken credential — no CSRF token on a signed-in browser write. The door
refuses `403 page_token_missing`; nothing ran, nothing was written, and that 403
is recorded as K's answer. The client fixes its credential and retries with the
identical key and body, which is exactly the protocol's promise — and gets the
stale 403 back with `Idempotent-Replayed: true`. **The key is poisoned for its
whole TTL and the write is permanently unreachable**, with no way for the client
to tell a cached refusal from a live one.

Found in validation, the same class again: `rate_limited` (429, `boundary=door`)
is below 500, so a key that once hit a rate limit is answered from the limit
forever — the one refusal whose whole contract is *come back later*.

**The boundary, and why the registry already knew it.** The fingerprint is
`method + path + RAW BODY` (`fingerprint_for`). A credential, `X-Tenant`,
`X-Org`, `X-CSRFToken`, the rate-limit counters and the query string are all
outside it — so a refusal decided on any of them is a refusal about material the
key does not name, and replaying it answers a question the client did not ask
again. The registry has carried the answer since it was written:
`boundary="door"` means *the edge refused before a service was reached*. Nothing
ran, so the key was never spent. `envelope_codes()` is that population, derived
— never a hand list, because the set is open and the checklist forbids one.

**What still replays, deliberately.** Every refusal a service, a selector or a
policy decided: `400 invalid`, `409 conflict`, `404 not_found`. Those are
decisions about the fingerprinted request itself, and a client that retries one
must get the same answer rather than a second attempt at the same rejected
write. The residual is stated at `REPLAYABLE_BELOW`: a domain `403 forbidden`
for an actor who was promoted between the two calls still replays, because a
policy decision IS a decision about this request.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from django.core.cache import cache
from django.http import HttpResponse
from django.test import Client, RequestFactory

from apps.accounts.models import User
from apps.core.exceptions import REFUSALS, envelope_codes
from apps.core.idempotency import (
    HEADER,
    REPLAYED_HEADER,
    IdempotencyMiddleware,
    IdempotencyRecord,
)
from apps.core.models import Tenant
from apps.core.throttling import AuthRateThrottle, TenantRateThrottle
from apps.example.models import Widget
from config.api import CODE_STATUS, api

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
JSON = "application/json"


# --- The unit: one stubbed answer, through the real middleware ----------------
#
# The middleware's decision is a pure function of the answer it was handed — a
# status and a body — so it is driven with the answer named rather than with an
# app contorted into producing one. Every code in the registry is driven this
# way below, off the registry itself, so a code registered next month is in the
# table by being registered.


def _drive(
    rf: RequestFactory,
    *,
    tenant: Tenant,
    key: str,
    answer: HttpResponse,
    body: str = '{"name": "Same"}',
) -> HttpResponse:
    """One claimed request through the real middleware, answered as told."""

    def get_response(request: Any) -> HttpResponse:
        return answer

    request = rf.post(LIST_URL, data=body, content_type=JSON, headers={HEADER: key})
    request.tenant = tenant  # type: ignore[attr-defined]
    return IdempotencyMiddleware(get_response)(request)


def _refusal_answer(code: str) -> HttpResponse:
    """What the doors send for a code, near enough for `_remember` to read."""
    response = HttpResponse(
        json.dumps({"detail": "Refused.", "code": code}),
        status=CODE_STATUS[code],
        content_type="application/json; charset=utf-8",
    )
    return response


def _codes_with_a_status() -> list[str]:
    return sorted(code for code, row in REFUSALS.items() if row.status is not None)


@pytest.mark.parametrize("code", _codes_with_a_status())
def test_every_registered_code_lands_on_the_arm_its_boundary_names(
    rf: RequestFactory, tenant: Tenant, code: str
) -> None:
    """The whole table, derived — the claim is kept or dropped by boundary.

    A door refusal leaves no record, so the retry is the fresh request it always
    was. Everything else is stored and replayable, which is the below-500
    doctrine unchanged for the layer it was always right about.
    """
    key = f"boundary-{code}"
    _drive(rf, tenant=tenant, key=key, answer=_refusal_answer(code))

    record = IdempotencyRecord.objects.filter(key=key).first()
    if code in envelope_codes() or CODE_STATUS[code] >= 500:
        assert record is None, f"{code} left a claim behind"
    else:
        assert record is not None, f"{code} dropped a claim it should have kept"
        assert record.status_code == CODE_STATUS[code]


def test_a_door_refusal_recorded_under_a_key_does_not_answer_the_retry(
    rf: RequestFactory, tenant: Tenant
) -> None:
    """The poisoned key's shape, said once at the unit: refuse, then succeed on the retry.

    The red on the baseline is the second assertion: `second` came back 403 with
    `Idempotent-Replayed: true`, and the 201 was unreachable under that key for
    the record's whole 24-hour TTL.
    """
    door = _refusal_answer("page_token_missing")
    first = _drive(rf, tenant=tenant, key="fixed-fault", answer=door)
    assert first.status_code == 403
    assert first.headers.get(REPLAYED_HEADER) is None

    created = HttpResponse('{"id": "fresh"}', status=201, content_type=JSON)
    second = _drive(rf, tenant=tenant, key="fixed-fault", answer=created)

    assert second.status_code == 201
    assert second.headers.get(REPLAYED_HEADER) is None

    # And the key is now the 201's, so a third identical send replays it.
    third = _drive(
        rf,
        tenant=tenant,
        key="fixed-fault",
        answer=HttpResponse('{"id": "never"}', status=201, content_type=JSON),
    )
    assert third.headers[REPLAYED_HEADER] == "true"
    assert json.loads(third.content)["id"] == "fresh"


def test_a_service_decision_recorded_under_a_key_still_answers_the_retry(
    rf: RequestFactory, tenant: Tenant
) -> None:
    """Criterion 7's negative: nothing below the doors changed.

    Driven for all three of the plan's named codes, because "a decision replays"
    is the half of the doctrine the boundary split had to leave intact.
    """
    for code in ("invalid", "conflict", "not_found"):
        key = f"decision-{code}"
        first = _drive(rf, tenant=tenant, key=key, answer=_refusal_answer(code))
        assert first.status_code == CODE_STATUS[code]

        second = _drive(
            rf,
            tenant=tenant,
            key=key,
            answer=HttpResponse('{"id": "never"}', status=201, content_type=JSON),
        )
        assert second.status_code == CODE_STATUS[code], code
        assert second.headers[REPLAYED_HEADER] == "true"
        assert json.loads(second.content)["code"] == code


def test_a_body_that_is_not_a_refusal_envelope_is_remembered_as_it_always_was(
    rf: RequestFactory, tenant: Tenant
) -> None:
    """The reader is narrow on purpose: no JSON, no code key, no decision.

    A sub-500 answer whose body this middleware cannot read is stored, exactly
    as it was before the rung. Guessing at an unparseable body would be a
    middleware inventing a refusal nobody made.
    """
    for label, answer in (
        ("html", HttpResponse("<p>fine</p>", status=200, content_type="text/html")),
        ("no-code", HttpResponse('{"detail": "fine"}', status=200, content_type=JSON)),
        ("not-json", HttpResponse("not json at all", status=200, content_type=JSON)),
    ):
        key = f"opaque-{label}"
        _drive(rf, tenant=tenant, key=key, answer=answer)
        assert IdempotencyRecord.objects.filter(key=key).exists(), label


# --- Criterion 6: the middleware's own two codes are never a stored answer -----


def test_no_record_ever_stores_the_middlewares_own_refusals(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """`idempotency_key_reuse` and `in_progress` are raised live, never cached.

    They are answers ABOUT a record rather than answers stored in one, and a
    record holding either as its body would be a claim that replayed a refusal
    to talk about itself. Both are `boundary="door"`, so the new arm agrees with
    the shape that already held; this pins the shape rather than trusting it.
    """
    api.force_login(owner)
    first = api.post(
        LIST_URL,
        data=json.dumps({"name": "Held"}),
        content_type=JSON,
        headers={HEADER: "own-codes"},
    )
    assert first.status_code == 201, first.content

    reuse = api.post(
        LIST_URL,
        data=json.dumps({"name": "Different"}),
        content_type=JSON,
        headers={HEADER: "own-codes"},
    )
    assert reuse.status_code == 409
    assert json.loads(reuse.content)["code"] == "idempotency_key_reuse"

    # And the second of the two, driven the way `test_idempotency.py` drives it:
    # a claimed-but-incomplete record is exactly the state a request still in
    # flight leaves behind.
    IdempotencyRecord.objects.filter(key="own-codes").update(status_code=None, body="")
    in_flight = api.post(
        LIST_URL,
        data=json.dumps({"name": "Held"}),
        content_type=JSON,
        headers={HEADER: "own-codes"},
    )
    assert in_flight.status_code == 409
    assert json.loads(in_flight.content)["code"] == "in_progress"

    stored = [
        json.loads(row.body).get("code") if row.body.startswith("{") else None
        for row in IdempotencyRecord.objects.all()
    ]
    assert "idempotency_key_reuse" not in stored
    assert "in_progress" not in stored


# --- Criterion 5: the 429 sibling, driven live --------------------------------


@pytest.fixture
def _empty_bucket() -> Iterator[None]:
    """Counters live in the cache, so a test that inherits one is a flake."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def one_a_minute(_empty_bucket: None) -> Iterator[None]:
    """Every operation throttled to one request a minute, both buckets.

    Constructor rates rather than settings, for `test_rate_limit_headers.py`'s
    reason: ninja resolves the settings table once, at import.
    """
    replaced: list[Any] = [AuthRateThrottle("1/min"), TenantRateThrottle("1/min")]
    originals: list[tuple[Any, list[Any]]] = []
    for bound in api._get_bound_routers():
        for _path, view in bound.path_operations.items():
            for operation in view.operations:
                originals.append((operation, operation.throttle_objects))
                operation.throttle_objects = replaced
    yield
    for operation, throttles in originals:
        operation.throttle_objects = throttles


def test_a_rate_limited_write_does_not_poison_its_key(
    api: Client, owner: User, tenant: Tenant, one_a_minute: None
) -> None:
    """The sibling found in validation, end to end through the real stack.

    On the baseline the second POST came back `429 Idempotent-Replayed: true`
    even with the bucket refilled — the allowance the refusal told the client to
    wait for had arrived and the key could never spend it. The write was
    unreachable under that key until the record expired.
    """
    api.force_login(owner)
    assert api.get(LIST_URL).status_code == 200  # spends the minute's allowance

    refused = api.post(
        LIST_URL,
        data=json.dumps({"name": "Too fast"}),
        content_type=JSON,
        headers={HEADER: "burst"},
    )
    assert refused.status_code == 429, refused.content
    assert json.loads(refused.content)["code"] == "rate_limited"
    assert refused.headers.get(REPLAYED_HEADER) is None

    cache.clear()  # the allowance the refusal promised, arrived

    retried = api.post(
        LIST_URL,
        data=json.dumps({"name": "Too fast"}),
        content_type=JSON,
        headers={HEADER: "burst"},
    )
    assert retried.status_code == 201, retried.content
    assert retried.headers.get(REPLAYED_HEADER) is None
    assert Widget.objects.for_tenant(tenant).filter(name="Too fast").count() == 1


# --- Criterion 7, live: a 404 the selector decided is still the key's answer ---


def test_a_not_found_a_selector_decided_is_still_replayed(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """Through the real stack, so the negative is not only a stubbed one.

    The body is valid for a `Versioned` noun so the refusal is the selector's,
    not the schema's.
    """
    api.force_login(owner)
    url = f"{LIST_URL}{uuid4()}/"
    body = json.dumps({"name": "Ghost", "version": 1})

    first = api.patch(url, data=body, content_type=JSON, headers={HEADER: "ghost"})
    assert first.status_code == 404, first.content

    second = api.patch(url, data=body, content_type=JSON, headers={HEADER: "ghost"})
    assert second.status_code == 404
    assert second.headers[REPLAYED_HEADER] == "true"
