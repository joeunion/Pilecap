"""The same write, sent twice, happens once.

Driven through the real API with the real middleware, because the claim is
about what a retrying HTTP client sees. The load-bearing assertion in the first
test is the row count: a replay that returned the right body while creating a
second widget would look correct and be the exact bug this prevents.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.test import Client, RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.services import issue_token
from apps.core import idempotency
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import REFUSAL_CONTENT_TYPE, REFUSALS
from apps.core.idempotency import (
    HEADER,
    REPLAYED_HEADER,
    IdempotencyRecord,
    purge_expired,
    scope_for,
)
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership, root_organization
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

LIST_URL = "/api/v1/widgets/"
JSON = "application/json"


def _post(api: Client, name: str, key: str | None = None, **extra: Any) -> Any:
    headers: dict[str, str] = dict(extra.pop("headers", {}))
    if key is not None:
        headers[HEADER] = key
    return api.post(
        LIST_URL,
        data=json.dumps({"name": name}),
        content_type=JSON,
        headers=headers,
        **extra,
    )


def test_a_repeated_key_replays_the_first_response_and_writes_nothing(
    api: Client, owner: User, tenant: Tenant
) -> None:
    api.force_login(owner)

    first = _post(api, "Charged once", key="k-1")
    assert first.status_code == 201, first.content
    assert REPLAYED_HEADER not in first.headers

    second = _post(api, "Charged once", key="k-1")
    assert second.status_code == 201
    assert second.headers[REPLAYED_HEADER] == "true"
    assert json.loads(second.content) == json.loads(first.content)

    # The whole point: one row, not two.
    assert Widget.objects.for_tenant(tenant).count() == 1


def test_without_a_key_nothing_is_replayed(api: Client, owner: User, tenant: Tenant) -> None:
    """Opt-in. A client that does not ask for the guarantee does not get it —
    and does not get a surprising one either."""
    api.force_login(owner)
    assert _post(api, "One").status_code == 201
    assert _post(api, "Two").status_code == 201
    assert Widget.objects.for_tenant(tenant).count() == 2


def test_the_same_key_with_a_different_body_is_refused(api: Client, owner: User) -> None:
    """Answering it with the other request's response would be a silent,
    expensive wrong answer.

    The body is the envelope every other refusal uses, and the code is a
    **registered** one, so a client that branches on it is branching on
    something `manage.py introspect` publishes.

    That envelope used to be `{detail, code}` and nothing
    else, because this middleware built its body by hand from in front of the
    API — so the two remedies the registry has always held for this code
    reached no client, while every sibling refusal on the same eight routes
    carried three. It goes through `wire_refusal` now, the one composer, and
    the internal `remedy` prose still stays off the wire: that is advice for
    whoever is HOLDING the refusal, and it is not the same thing as `remedies`,
    which is what the caller can DO.
    """
    api.force_login(owner)
    assert _post(api, "First", key="k-2").status_code == 201

    response = _post(api, "Something else entirely", key="k-2")
    assert response.status_code == 409

    body = json.loads(response.content)
    assert set(body) == {"detail", "code", "remedies"}
    assert body["code"] == "idempotency_key_reuse"
    assert body["detail"]

    registered = REFUSALS[body["code"]]
    assert registered.boundary == "door"
    assert registered.remedy not in response.content.decode()

    # The remedies are the REGISTRY's, not a second set written here — which is
    # the whole point of routing through the one composer.
    assert body["remedies"] == [
        {"label": remedy.label, "destination": remedy.destination} for remedy in registered.remedies
    ]
    # The second tell: the charset. This body used to answer
    # `application/json` where every sibling answered
    # `application/json; charset=utf-8` — legible from outside as "built
    # somewhere else", and it was.
    assert response.headers["Content-Type"] == REFUSAL_CONTENT_TYPE


def test_a_concurrent_retry_is_told_to_wait_rather_than_allowed_to_double_write(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """The claim is written before the view runs, so the second one finds it.

    Simulated by leaving a claimed-but-incomplete record behind, which is
    exactly the state a request that is still in flight leaves.
    """
    api.force_login(owner)
    first = _post(api, "In flight", key="k-3")
    assert first.status_code == 201

    IdempotencyRecord.objects.filter(key="k-3").update(status_code=None, body="")

    response = _post(api, "In flight", key="k-3")
    assert response.status_code == 409

    body = json.loads(response.content)
    assert set(body) == {"detail", "code", "remedies"}
    assert body["code"] == "in_progress"
    assert REFUSALS[body["code"]].boundary == "door"
    assert body["remedies"] == [
        {"label": remedy.label, "destination": remedy.destination}
        for remedy in REFUSALS[body["code"]].remedies
    ]
    assert response.headers["Content-Type"] == REFUSAL_CONTENT_TYPE
    assert Widget.objects.for_tenant(tenant).count() == 1


def test_a_refusal_is_replayed_because_it_is_a_decision(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """A 400 is a decision the server will make again, so it replays.

    Only a 5xx drops the claim, because that is a failure rather than an answer
    and a retry should genuinely retry it.
    """
    api.force_login(owner)
    create_widget(
        tenant=tenant,
        actor=Actor(
            user=owner,
            token=None,
            kind="human",
            tenant=tenant,
            org=root_organization(tenant=tenant),
        ),
        name="Taken",
    )

    response = _post(api, "Taken", key="k-4")
    assert response.status_code == 400
    replayed = _post(api, "Taken", key="k-4")
    assert replayed.status_code == 400
    assert replayed.headers[REPLAYED_HEADER] == "true"


def test_a_key_does_not_cross_a_credential(
    api: Client, owner: User, tenant: Tenant, member: User
) -> None:
    """Keys are chosen by clients and two of them will collide eventually.

    A collision that crossed a credential — or a tenant — would hand one caller
    another caller's response body.
    """
    api.force_login(owner)
    assert _post(api, "Mine", key="shared-key").status_code == 201

    other = Client()
    other.force_login(member)
    second = _post(other, "Theirs", key="shared-key")
    assert second.status_code == 201
    assert REPLAYED_HEADER not in second.headers
    assert Widget.objects.for_tenant(tenant).count() == 2


def test_the_machine_door_gets_the_same_guarantee(api: Client, owner: User, tenant: Tenant) -> None:
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="ci", actor=actor_for(user=owner, tenant=tenant)
    )
    headers = {"authorization": f"Bearer {plaintext}"}

    first = _post(api, "By the robot", key="k-5", headers=headers)
    assert first.status_code == 201, first.content
    second = _post(api, "By the robot", key="k-5", headers=headers)
    assert second.headers[REPLAYED_HEADER] == "true"
    assert Widget.objects.for_tenant(tenant).count() == 1


def test_a_get_is_never_intercepted(api: Client, owner: User) -> None:
    """Reads are idempotent already; recording them would be a cache nobody asked for."""
    api.force_login(owner)
    api.get(LIST_URL, headers={HEADER: "k-6"})
    assert not IdempotencyRecord.objects.filter(key="k-6").exists()


def test_an_expired_record_lets_the_request_through(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """Twenty-four hours is a window, not forever: a client retrying a day later
    is making a new request by any reasonable reading."""
    api.force_login(owner)
    assert _post(api, "First time", key="k-7").status_code == 201

    IdempotencyRecord.objects.filter(key="k-7").update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )

    again = _post(api, "First time", key="k-7")
    # The name is unique per owner per tenant, so the *service* refuses it —
    # which proves the request genuinely ran rather than being replayed.
    assert again.status_code == 400
    assert REPLAYED_HEADER not in again.headers


def test_purge_expired_removes_only_what_has_expired(api: Client, owner: User) -> None:
    api.force_login(owner)
    _post(api, "Live", key="live")
    _post(api, "Dead", key="dead")
    IdempotencyRecord.objects.filter(key="dead").update(
        expires_at=timezone.now() - timedelta(hours=1)
    )

    assert purge_expired() == 1
    assert list(IdempotencyRecord.objects.values_list("key", flat=True)) == ["live"]


# --- N100a: the scope names the actor, never the header -----------------------
#
# The defect these hold shut: `scope_for` used to digest the *requested*
# `X-Tenant` string, defaulting to `""` when it was absent, so the scope
# followed the request's spelling and not the tenant the door resolved. One
# credential with memberships in two tenants, `X-Tenant` omitted both times and
# a default membership flipped in between, is one spelling and two hats — and
# the second call was answered from the first hat's cache. The same walk is
# driven over real HTTP in `test_idempotency_over_the_wire.py`; these are the
# same properties where they can be asserted against rows.


@pytest.fixture
def two_hats(owner: User, tenant: Tenant, other_tenant: Tenant) -> User:
    """One person, memberships in two tenants, the first one their default."""
    add_membership(
        user=owner, tenant=other_tenant, is_default=False, actor=system_actor(tenant=other_tenant)
    )
    return owner


def _default_membership_becomes(*, user: User, tenant: Tenant) -> None:
    """Flip which tenant this person lands in when they name none.

    `add_membership`'s own rule, applied to a membership that already exists:
    at most one membership per user is the default, and asking for a second
    moves the flag rather than tripping the constraint. Written through the
    manager rather than through the service because the service *creates* and
    the row is already there; the escalation wall is untouched either way —
    nothing here grants a role.
    """
    Membership.objects.filter(user_id=user.pk, is_default=True).update(is_default=False)
    Membership.objects.filter(user_id=user.pk, tenant=tenant).update(is_default=True)


def test_a_flipped_default_membership_is_a_different_scope_not_a_replay(
    api: Client, two_hats: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """N100a-1. The red: one credential, one key, one body, two hats.

    Nothing about the request changes between the two calls — same session,
    same body, same key, `X-Tenant` absent both times. What changes is the
    tenant the door *resolves*, and that is now what the scope is built from.
    Before the fix the second call came back `Idempotent-Replayed: true`
    carrying the first tenant's widget; both assertions below failed.
    """
    api.force_login(two_hats)

    first = _post(api, "Same body", key="hat-flip")
    assert first.status_code == 201, first.content
    assert json.loads(first.content)["tenant_id"] == str(tenant.pk)

    _default_membership_becomes(user=two_hats, tenant=other_tenant)

    second = _post(api, "Same body", key="hat-flip")
    assert second.status_code == 201, second.content
    # The two assertions the criteria name, and both fail on the baseline.
    assert second.headers.get(REPLAYED_HEADER) is None
    assert json.loads(second.content)["tenant_id"] == str(other_tenant.pk)

    # One row in each tenant, and the first tenant's record left as it was.
    assert Widget.objects.for_tenant(tenant).count() == 1
    assert Widget.objects.for_tenant(other_tenant).count() == 1
    records = IdempotencyRecord.objects.filter(key="hat-flip")
    assert sorted(str(pk) for pk in records.values_list("tenant_id", flat=True)) == sorted(
        [str(tenant.pk), str(other_tenant.pk)]
    )


def test_two_hats_named_by_header_never_share_a_scope_on_a_session(
    api: Client, two_hats: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """N100a-2, the human door. `X-Tenant: a`, then `b`, then `a` again."""
    api.force_login(two_hats)
    key = "hats-session"

    first = _post(api, "By hat", key=key, headers={"X-Tenant": tenant.slug})
    assert first.status_code == 201, first.content
    assert first.headers.get(REPLAYED_HEADER) is None

    second = _post(api, "By hat", key=key, headers={"X-Tenant": other_tenant.slug})
    assert second.status_code == 201, second.content
    assert second.headers.get(REPLAYED_HEADER) is None
    assert json.loads(second.content)["tenant_id"] == str(other_tenant.pk)

    # Two writes, two tenants — and the first hat still gets its own answer,
    # byte for byte.
    again = _post(api, "By hat", key=key, headers={"X-Tenant": tenant.slug})
    assert again.headers[REPLAYED_HEADER] == "true"
    assert again.content == first.content

    assert Widget.objects.for_tenant(tenant).count() == 1
    assert Widget.objects.for_tenant(other_tenant).count() == 1


def test_two_hats_named_by_header_never_share_a_scope_on_a_token(
    api: Client, two_hats: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """N100a-2, the machine door, with a token that carries no pin.

    An unpinned token resolves its tenant the way a signed-in request does, and
    it resolves it *inside the view* — after this middleware has had to decide
    whether to claim or to replay. The scope on that path carries the tenant the
    request named **as a row**, and the stored `tenant` FK is what stops a
    record crossing.
    """
    _, plaintext = issue_token(
        user=two_hats, tenant=None, name="unpinned", actor=actor_for(user=two_hats, tenant=None)
    )
    auth = {"authorization": f"Bearer {plaintext}"}
    key = "hats-token"

    first = _post(api, "By robot hat", key=key, headers={**auth, "X-Tenant": tenant.slug})
    assert first.status_code == 201, first.content
    assert first.headers.get(REPLAYED_HEADER) is None

    second = _post(api, "By robot hat", key=key, headers={**auth, "X-Tenant": other_tenant.slug})
    assert second.status_code == 201, second.content
    assert second.headers.get(REPLAYED_HEADER) is None
    assert json.loads(second.content)["tenant_id"] == str(other_tenant.pk)

    again = _post(api, "By robot hat", key=key, headers={**auth, "X-Tenant": tenant.slug})
    assert again.headers[REPLAYED_HEADER] == "true"
    assert again.content == first.content

    assert Widget.objects.for_tenant(tenant).count() == 1
    assert Widget.objects.for_tenant(other_tenant).count() == 1


def test_the_single_tenant_client_that_omits_the_header_still_replays(
    api: Client, owner: User, tenant: Tenant
) -> None:
    """N100a-3. The common case, and the branch the steer refused to take.

    Making `X-Tenant` mandatory would have closed the hole by breaking every
    client that never needed the header. One membership, no header, same key
    twice: still one row and still a replay.
    """
    api.force_login(owner)
    first = _post(api, "Only tenant", key="single-tenant")
    assert first.status_code == 201, first.content

    second = _post(api, "Only tenant", key="single-tenant")
    assert second.headers[REPLAYED_HEADER] == "true"
    assert second.content == first.content
    assert Widget.objects.for_tenant(tenant).count() == 1
    assert IdempotencyRecord.objects.filter(key="single-tenant").count() == 1


def test_a_request_that_resolves_no_tenant_is_never_replayed_and_leaves_no_trap(
    api: Client, owner: User, nomad: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """N100a-3, the fail-closed half (house rule 8, at the door).

    A signed-in person who belongs to no tenant at all resolves nothing — the
    route refuses, and the record left behind has a NULL tenant. `_may_replay`
    refuses to hand a NULL-tenant record to anybody: not to a repeat of itself,
    and above all not to a request that *did* resolve a tenant.

    **The driver changed with ADR core-21 and the property did not.** It used to
    be a token pinned to one tenant while the header named another, because that
    request used to fail to authenticate at all. Under the addressing-header law
    the credential authenticates and the DOOR refuses, so that request resolves
    the pin — which is a different fact and no longer this test's subject. The
    nomad is the honest driver for "resolved nothing", and the pinned-token
    refusal is driven at `apps/core/tests/test_addressing_headers.py`.
    """
    api.force_login(nomad)

    refused = _post(api, "Nowhere", key="no-tenant")
    assert refused.status_code == 403, refused.content
    assert refused.headers.get(REPLAYED_HEADER) is None

    record = IdempotencyRecord.objects.filter(key="no-tenant").first()
    assert record is not None
    assert record.tenant_id is None

    # A second identical attempt is refused on its own merits, never replayed.
    again = _post(api, "Nowhere", key="no-tenant")
    assert again.status_code == 403
    assert again.headers.get(REPLAYED_HEADER) is None
    api.logout()

    # And the record it left cannot be reached by a request that resolves one:
    # a resolved scope and an unresolved one are separated by a domain marker,
    # so they can never hash to the same 64 characters.
    api.force_login(owner)
    resolved = _post(api, "Somewhere", key="no-tenant")
    assert resolved.status_code == 201, resolved.content
    assert resolved.headers.get(REPLAYED_HEADER) is None
    assert Widget.objects.for_tenant(tenant).count() == 1


def test_a_replayed_record_names_the_tenant_it_was_replayed_to(
    api: Client, two_hats: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """N100a-4. The stored row tells the truth, so the next reader may trust it.

    The FK is not decoration: `_may_replay` reads it, so a record whose tenant
    disagreed with the hat being answered would be a replay that never happens.
    """
    api.force_login(two_hats)
    _post(api, "Truthful", key="truthful", headers={"X-Tenant": other_tenant.slug})
    replayed = _post(api, "Truthful", key="truthful", headers={"X-Tenant": other_tenant.slug})
    assert replayed.headers[REPLAYED_HEADER] == "true"

    records = list(IdempotencyRecord.objects.filter(key="truthful"))
    assert len(records) == 1
    assert records[0].tenant_id == other_tenant.pk


def test_a_bearer_that_names_no_tenant_no_longer_crosses_hats(
    api: Client, two_hats: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """The last population, closed by the seam.

    A bearer credential that sends **no** `X-Tenant` resolves its tenant from
    the user's default membership, inside the view, off an `ApiToken` row in
    `apps.accounts` — an app `core` may not import (house rule 7). Part 1 left
    that one path scoped on the credential alone and pinned this test to the
    hole; it now asserts the closure its siblings already assert.

    What made it possible: `core.idempotency.register_tenant_resolver`, which
    `AccountsConfig.ready()` registers `tenant_for_bearer_credential` into. The
    scope digests the tenant that resolver returns exactly as it digests the one
    `TenantMiddleware` resolved, because it is the same answer to the same
    question arriving a little later. Nothing imports upward.

    Red on efde532 (part 1, on main), green here. Driven over real HTTP too, in
    `test_idempotency_over_the_wire.py`.
    """
    _, plaintext = issue_token(
        user=two_hats,
        tenant=None,
        name="unpinned-no-header",
        actor=actor_for(user=two_hats, tenant=None),
    )
    auth = {"authorization": f"Bearer {plaintext}"}

    first = _post(api, "No longer blind", key="blind-spot", headers=auth)
    assert first.status_code == 201, first.content
    assert first.headers.get(REPLAYED_HEADER) is None
    assert json.loads(first.content)["tenant_id"] == str(tenant.pk)

    _default_membership_becomes(user=two_hats, tenant=other_tenant)

    second = _post(api, "No longer blind", key="blind-spot", headers=auth)
    # The second hat gets its own answer, which is the whole of ADR core-16.
    assert second.status_code == 201, second.content
    assert second.headers.get(REPLAYED_HEADER) is None
    assert json.loads(second.content)["tenant_id"] == str(other_tenant.pk)

    # One row in each tenant, and two records with the tenants to match.
    assert Widget.objects.for_tenant(tenant).count() == 1
    assert Widget.objects.for_tenant(other_tenant).count() == 1
    records = IdempotencyRecord.objects.filter(key="blind-spot")
    assert sorted(str(pk) for pk in records.values_list("tenant_id", flat=True)) == sorted(
        [str(tenant.pk), str(other_tenant.pk)]
    )


def test_a_bearer_credential_that_stays_put_still_replays(
    api: Client, two_hats: User, tenant: Tenant
) -> None:
    """The seam must not have bought the fix by breaking the ordinary retry.

    Same token, no header, nothing flipped: the second call is the replay a
    machine client sends `Idempotency-Key` to get, and there is one row.
    """
    _, plaintext = issue_token(
        user=two_hats,
        tenant=None,
        name="unpinned-steady",
        actor=actor_for(user=two_hats, tenant=None),
    )
    auth = {"authorization": f"Bearer {plaintext}"}

    first = _post(api, "Steady", key="steady", headers=auth)
    assert first.status_code == 201, first.content

    second = _post(api, "Steady", key="steady", headers=auth)
    assert second.headers[REPLAYED_HEADER] == "true"
    assert second.content == first.content
    assert Widget.objects.for_tenant(tenant).count() == 1


def test_a_cookie_and_a_bearer_that_disagree_never_cross(
    api: Client, two_hats: User, tenant: Tenant, other_tenant: Tenant
) -> None:
    """The disagreement case, declared rather than left silent.

    A request may carry both a session cookie and an `Authorization` header.
    `TenantMiddleware` resolves the session's tenant before this middleware
    runs, so `getattr(request, "tenant")` is already set and the scope is built
    on it — and then `ApiTokenAuth` re-tenants the request inside the view from
    the token, which may be pinned somewhere else entirely. The two halves
    genuinely disagree, and `_may_replay` compares the stored FK against what
    the door resolved, so nothing crosses.

    No fix is claimed here: this pins today's fail-closed behaviour so a change
    to it is a decision somebody makes rather than a drift nobody sees. The
    token wins the request — ninja tries `ApiTokenAuth` first, deliberately
    (`apps/accounts/auth.py`, queue V1) — and the record filed under the
    session's scope is never handed to a hat that did not earn it.
    """
    api.force_login(two_hats)
    # A token pinned to the OTHER tenant, sent alongside the session cookie
    # whose default membership is `tenant`.
    _, plaintext = issue_token(
        user=two_hats,
        tenant=other_tenant,
        name="pinned-elsewhere",
        actor=actor_for(user=two_hats, tenant=other_tenant),
    )
    both = {"authorization": f"Bearer {plaintext}"}

    first = _post(api, "Two credentials", key="disagree", headers=both)
    assert first.status_code == 201, first.content
    # The token decided the request, not the cookie.
    assert json.loads(first.content)["tenant_id"] == str(other_tenant.pk)

    record = IdempotencyRecord.objects.get(key="disagree")
    # Filed while the session's tenant was the only one known, and the row
    # still remembers where the request actually landed.
    assert record.tenant_id == other_tenant.pk

    # The same two credentials again is the ordinary replay: both halves agree
    # with themselves, so the retry gets its own first answer back.
    again = _post(api, "Two credentials", key="disagree", headers=both)
    assert again.headers[REPLAYED_HEADER] == "true"
    assert again.content == first.content
    assert Widget.objects.for_tenant(other_tenant).count() == 1
    # And nothing was written into the tenant the cookie would have chosen.
    assert Widget.objects.for_tenant(tenant).count() == 0


def test_the_seam_costs_one_token_read_and_no_second_last_used_write(
    api: Client, two_hats: User
) -> None:
    """Part 2 criterion (3): the cost, counted rather than asserted.

    The path is a write to `/api/` carrying both a bearer token and an
    `Idempotency-Key`. Measured on this tree, `accounts_apitoken` statements:

    ======================================  ========  =======
    statement                               efde532   with the seam
    ======================================  ========  =======
    resolve the token (`authenticate_token`)       1        2
    `touch_token` writing `last_used_at`           1        1
    the FK existence check on the audit row        1        1
    **total**                                      3        4
    ======================================  ========  =======

    So: **one extra SELECT, and no extra write.** The resolution doubles because
    the seam resolves in the middleware and `ApiTokenAuth` resolves again in the
    view — the deliberate cost of knowing the tenant before the claim is filed.
    The write does *not* double, because `touch_token` refuses to write twice
    inside `ACCOUNTS_TOKEN_TOUCH_SECONDS` and the second resolution in one
    request sees the first one's timestamp.

    Counted here rather than reasoned about, because "it dedupes" is a claim
    about a window and a clock, and both are settings somebody can change. A
    deployment that set `ACCOUNTS_TOKEN_TOUCH_SECONDS=0` would double the write
    and this is the test that would say so.
    """
    _, plaintext = issue_token(
        user=two_hats, tenant=None, name="cost", actor=actor_for(user=two_hats, tenant=None)
    )
    auth = {"authorization": f"Bearer {plaintext}"}

    with CaptureQueriesContext(connection) as captured:
        response = _post(api, "Counted", key="cost", headers=auth)
    assert response.status_code == 201, response.content

    statements = [entry["sql"] for entry in captured.captured_queries]
    token_sql = [sql for sql in statements if "accounts_apitoken" in sql]
    # `authenticate_token` is the only thing that looks a token up by its hash.
    resolutions = [sql for sql in token_sql if "key_hash" in sql]
    writes = [sql for sql in token_sql if sql.lstrip().startswith("UPDATE")]

    assert len(resolutions) == 2, token_sql
    assert len(writes) == 1, token_sql
    assert len(token_sql) == 4, token_sql


def test_the_resolver_is_asked_once_per_request(
    api: Client, two_hats: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`acting_tenant` remembers, so two call sites are not two queries.

    `scope_for` and `_may_replay` both want the answer. Without the per-request
    memo the seam would cost two token reads instead of one, and the cost test
    above would be measuring something other than what it claims.
    """
    # Imported in the body rather than at module scope so that this module
    # still *collects* against a tree where the seam does not exist yet — which
    # is what lets the red be the assertions failing rather than an ImportError
    # standing in for them.
    from apps.accounts.apps import tenant_for_bearer_credential

    _, plaintext = issue_token(
        user=two_hats,
        tenant=None,
        name="counted-resolver",
        actor=actor_for(user=two_hats, tenant=None),
    )
    auth = {"authorization": f"Bearer {plaintext}"}
    calls: list[str] = []

    def counting(request: Any) -> Any:
        calls.append(request.path)
        return tenant_for_bearer_credential(request)

    monkeypatch.setattr(idempotency, "_tenant_resolvers", [counting])

    _post(api, "Once", key="once", headers=auth)
    assert len(calls) == 1, calls

    # And on the replay, which reaches `_may_replay` as well as `scope_for`.
    calls.clear()
    _post(api, "Once", key="once", headers=auth)
    assert len(calls) == 1, calls


def test_the_scope_is_built_from_the_resolved_tenant_not_the_spelling(
    rf: RequestFactory, tenant: Tenant, other_tenant: Tenant
) -> None:
    """The unit under all of the above, said once directly.

    Two requests that *spell* the same thing (nothing) and resolve differently
    get different scopes; a request that spells one tenant while the door
    resolved another is scoped on what the door resolved. That is the whole of
    the fix, and it is the assertion the header census (rule 40)
    will later hold from the other side.
    """
    resolved_a = rf.post(LIST_URL)
    resolved_a.tenant = tenant  # type: ignore[attr-defined]
    resolved_b = rf.post(LIST_URL)
    resolved_b.tenant = other_tenant  # type: ignore[attr-defined]

    assert scope_for(resolved_a) != scope_for(resolved_b)

    spelled = rf.post(LIST_URL, headers={"X-Tenant": other_tenant.slug})
    spelled.tenant = tenant  # type: ignore[attr-defined]
    assert scope_for(spelled) == scope_for(resolved_a)
