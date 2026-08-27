"""The token door, driven through the mounted API.

The plaintext comes back exactly once, revoking it stops it working, and the
one narrowing that matters holds: a token cannot mint another token.

**And it holds at the door, in words the caller can act on.** The rule
was enforced in the route body, which runs after the token ceiling is checked —
so a narrow token was answered `insufficient_scope`, told to go and mint a wider
one, and sent to the one operation that refuses every token there is. The chain
is re-driven below, and it now stops at the first refusal.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import ApiToken, User
from apps.accounts.services import authenticate_token, issue_token
from apps.core.actor import actor_for
from apps.core.audit import AuditEntry
from apps.core.models import Tenant
from config.api import api as the_api

pytestmark = pytest.mark.django_db

TOKENS_URL = "/api/v1/tokens/"
# The nearest route that already goes through `_acting`, used to pin the
# refusal `create_token` now speaks against the one every other write speaks.
SSO_CONNECTIONS_URL = "/api/v1/auth/sso-connections/"
JSON = "application/json"


def _body(response: Any) -> dict[str, Any]:
    parsed: dict[str, Any] = json.loads(response.content)
    return parsed


def test_the_routes_are_where_the_router_put_them() -> None:
    assert reverse("api:token-create") == TOKENS_URL


def test_anonymous_cannot_mint(api: Client) -> None:
    response = api.post(TOKENS_URL, data=json.dumps({"name": "nope"}), content_type=JSON)
    assert response.status_code == 401
    assert ApiToken.objects.count() == 0


def test_a_signed_in_user_mints_a_working_token_once(
    api: Client, tenant: Tenant, owner: User
) -> None:
    api.force_login(owner)
    body_in = json.dumps({"name": "laptop", "scopes": ["*"]})
    response = api.post(TOKENS_URL, data=body_in, content_type=JSON)
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["name"] == "laptop"
    assert body["tenant_id"] == str(tenant.pk)

    plaintext = body["token"]
    assert plaintext.startswith("djb_")

    # It works, as the user who minted it, in the tenant they were acting in.
    resolved = authenticate_token(plaintext=plaintext)
    assert resolved is not None
    assert resolved[0] == owner
    assert resolved[1] == tenant

    # And it is not recoverable: only the hash was stored.
    token = ApiToken.objects.get(pk=body["id"])
    assert plaintext not in token.key_hash
    assert ApiToken.objects.filter(key_hash=plaintext).count() == 0


def test_a_token_cannot_mint_another_token(api: Client, tenant: Tenant, owner: User) -> None:
    """The rule that keeps revocation meaningful, and the code that names it."""
    _, plaintext = issue_token(
        user=owner, tenant=tenant, name="machine", actor=actor_for(user=owner, tenant=tenant)
    )
    response = api.post(
        TOKENS_URL,
        data=json.dumps({"name": "offspring"}),
        content_type=JSON,
        headers={"authorization": f"Bearer {plaintext}"},
    )
    assert response.status_code == 403, response.content
    assert _body(response)["code"] == "session_required"
    assert ApiToken.objects.count() == 1


# --- the remedy chain an agent could not follow --------------------------


def test_a_narrow_token_at_the_mint_is_not_sent_after_a_wider_one(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """**FT-1′ F2, re-driven end to end.** The dead-end chain, and where it stops.

    What happened: an agent holding `widgets:write` called the mint, and the
    token ceiling — checked between authentication and the view — answered
    first. It said `insufficient_scope`, named `tokens:write`, and offered "mint
    a token that carries the scope named here". The agent, following exactly
    that, arrived back at this operation, which refuses every token whatever it
    carries. Two refusals, each true, pointing at each other; and an agent
    runtime has no wire path to a wider token BY DESIGN, so the honest answer
    was never one of the offered ones.

    What it does now: the session-only refusal is the *first* one, because a
    door that shuts for every token has nothing to say about which scopes this
    one holds. Three assertions and they are the three halves of the finding —
    the code is not the scope one, the sentence does not name a scope to go and
    get, and at least one structured remedy points at the session.
    """
    _, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name="agent",
        scopes=["widgets:write"],
        actor=actor_for(user=owner, tenant=tenant),
    )
    minted_before = ApiToken.objects.count()

    response = api.post(
        TOKENS_URL,
        data=json.dumps({"name": "wider", "scopes": ["org-structure:read"]}),
        content_type=JSON,
        headers={"authorization": f"Bearer {plaintext}"},
    )
    body = _body(response)

    assert response.status_code == 403, response.content
    assert body["code"] == "session_required"
    assert "insufficient_scope" != body["code"]
    assert "tokens:write" not in body["detail"]
    assert "self:session" in [remedy["destination"] for remedy in body["remedies"]]
    assert ApiToken.objects.count() == minted_before


def test_the_session_path_the_remedy_names_actually_mints(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The other half: the way out the refusal points at is a way out.

    A remedy naming a path nobody has driven is the same failure one level up,
    so the session mint is driven here with a NARROW scope — the shape an
    operator setting an agent up actually asks for — rather than only with the
    `["*"]` the older tests use.
    """
    api.force_login(owner)
    response = api.post(
        TOKENS_URL,
        data=json.dumps({"name": "wider", "scopes": ["org-structure:read"]}),
        content_type=JSON,
    )
    assert response.status_code == 201, response.content
    body = _body(response)
    assert body["scopes"] == ["org-structure:read"]
    assert body["effective_scopes"] == ["org-structure:read"]
    assert authenticate_token(plaintext=body["token"]) is not None


def test_an_expired_or_wrong_token_is_at_the_same_shut_door(api: Client) -> None:
    """A token nobody can resolve gets the session refusal too, and should.

    Telling this caller their token is stale would send them to renew it and
    come straight back to a door no token opens. The refusal is about the
    operation, not about the credential.
    """
    response = api.post(
        TOKENS_URL,
        data=json.dumps({"name": "nope", "scopes": ["*"]}),
        content_type=JSON,
        headers={"authorization": "Bearer djb_not-a-real-token"},
    )
    assert response.status_code == 403, response.content
    assert _body(response)["code"] == "session_required"


def test_the_published_mint_does_not_offer_a_scope_that_cannot_reach_it() -> None:
    """**FT-1′ F3, the half that lives in this app.** The document stops teaching it.

    Every route's refusal block is derived from the door's SHAPE, and the shape
    of an authenticated write includes `insufficient_scope` — correctly, for
    eighty-odd operations. Not for this one: no ceilinged token reaches the view
    at all, so publishing the code taught a caller to handle a refusal this
    operation cannot make, and to handle it by going and minting a wider token
    here. `@refuses(...)` is the declared valve for exactly that, and this is
    what it is being used for.
    """
    mint = the_api.get_openapi_schema()["paths"][TOKENS_URL]["post"]
    published = {
        code
        for body in (mint.get("responses") or {}).values()
        for code in (body.get("x-refusal-codes") or ())
        if isinstance(body, dict)
    }
    assert "insufficient_scope" not in published, published
    assert "forbidden" in published


def test_revoking_stops_the_token_and_keeps_the_row(
    api: Client, tenant: Tenant, owner: User
) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="doomed", actor=actor_for(user=owner, tenant=tenant)
    )
    api.force_login(owner)
    assert api.delete(f"{TOKENS_URL}{token.pk}/").status_code == 204
    assert authenticate_token(plaintext=plaintext) is None
    assert ApiToken.objects.filter(pk=token.pk).exists()


def test_a_token_can_revoke_itself(api: Client, tenant: Tenant, owner: User) -> None:
    token, plaintext = issue_token(
        user=owner, tenant=tenant, name="self-destruct", actor=actor_for(user=owner, tenant=tenant)
    )
    response = api.delete(
        f"{TOKENS_URL}{token.pk}/",
        headers={"authorization": f"Bearer {plaintext}"},
    )
    assert response.status_code == 204
    assert authenticate_token(plaintext=plaintext) is None


def test_somebody_elses_token_is_a_404(
    api: Client, tenant: Tenant, other_tenant: Tenant, owner: User, stranger: User
) -> None:
    theirs, plaintext = issue_token(
        user=stranger,
        tenant=other_tenant,
        name="not yours",
        actor=actor_for(user=stranger, tenant=other_tenant),
    )
    api.force_login(owner)
    assert api.delete(f"{TOKENS_URL}{theirs.pk}/").status_code == 404
    assert authenticate_token(plaintext=plaintext) is not None


def test_a_user_with_no_resolvable_tenant_cannot_mint_over_the_wire(
    api: Client, nomad: User
) -> None:
    """No tenant to act in is a refusal, not an unpinned token.

    This test used to assert the opposite, and the behaviour change is the
    point (the PM ratified it over a recorded exemption). `create_token` was the
    one write in this module that did not go through `_acting`, so a signed-in
    person with no resolvable tenant minted a token pinned to nothing — and
    `issue_token` declares a `tenant`, so the `@service` decorator wrote its
    audit row into the **platform** population. "Platform means the deployment's
    own actions" was documentation enforced by nothing: anybody with a session
    and no membership could deposit a row there from the wire.

    A token pinned to no tenant is still a real product state — `manage.py
    issue_token` mints one, and `authenticate_token` resolves a tenant per
    request for it. What is gone is the *wire* as a way to ask for one.
    """
    api.force_login(nomad)
    body_in = json.dumps({"name": "homeless", "scopes": ["*"]})
    response = api.post(TOKENS_URL, data=body_in, content_type=JSON)
    assert response.status_code == 403, response.content
    assert ApiToken.objects.count() == 0


def test_the_refusal_is_the_one_every_other_write_in_this_module_speaks(
    api: Client, nomad: User
) -> None:
    """Byte-equal with an existing `_acting` route's refusal, so it cannot drift.

    `create_token` does not restate the refusal; it calls the same helper the
    SSO-connection routes call. Pinning the *bodies* against each other — rather
    than pinning a literal string here — means a change to `_acting`'s wording
    moves both at once and this test keeps passing for the right reason.
    """
    api.force_login(nomad)
    body_in = json.dumps({"name": "homeless", "scopes": ["*"]})
    minting = api.post(TOKENS_URL, data=body_in, content_type=JSON)
    configuring = api.post(
        SSO_CONNECTIONS_URL,
        data=json.dumps(
            {
                "name": "acme",
                "issuer": "https://idp.example.com",
                "client_id": "abc",
                "client_secret": "shh",  # pragma: allowlist secret
                "email_domains": ["example.com"],
            }
        ),
        content_type=JSON,
    )
    assert minting.status_code == configuring.status_code == 403
    assert minting.content == configuring.content


def test_minting_over_the_wire_leaves_nothing_in_the_platform_audit_population(
    api: Client, tenant: Tenant, owner: User, nomad: User
) -> None:
    """The property this guards against, asserted as a population diff.

    Not "the mechanism ran" — the population. Across a successful mint and a
    refused one, `AuditEntry.objects.for_platform()` gains nothing: every audit
    row a wire-minted token leaves now sits in the tenant's own ledger, where
    the people who can read that ledger can see it.
    """
    before = AuditEntry.objects.for_platform().count()

    api.force_login(owner)
    minted = api.post(
        TOKENS_URL, data=json.dumps({"name": "laptop", "scopes": ["*"]}), content_type=JSON
    )
    assert minted.status_code == 201, minted.content
    assert _body(minted)["tenant_id"] == str(tenant.pk)

    api.force_login(nomad)
    refused = api.post(
        TOKENS_URL, data=json.dumps({"name": "homeless", "scopes": ["*"]}), content_type=JSON
    )
    assert refused.status_code == 403, refused.content

    assert AuditEntry.objects.for_platform().count() == before
    assert AuditEntry.objects.for_tenant(tenant).filter(action="accounts.issue_token").count() == 1
