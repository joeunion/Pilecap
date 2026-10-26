"""The ways a token is refused, exercised against a real verifier.

W2R3-5. Every one of these drives `allauth.socialaccount.internal.jwtkit` — the
same function the browser callback runs — against the same in-process JWKS the
stub publishes. Nothing here asserts about a mock.

**Where each one is proved, and why they are not all in the same place.**
allauth deliberately skips id_token *signature* verification on the
authorization-code flow: the token arrived over a direct connection to the
issuer, which OpenID Connect Core §3.1.3.7 says is sufficient, and
`openid_connect/views.py` spells it `verify_signature = not
self.did_fetch_access_token`. Issuer, audience and expiry are enforced there
regardless. So:

* **audience** and **expiry** are proved through the real browser callback, end
  to end, because that is where they actually run;
* **signature** is proved by calling the verifier the way a **resource server**
  must — `verify_signature=True`, with no TLS provenance to lean on — which is
  precisely the call the MCP door's bearer validation makes, against this JWKS.

Writing it the other way round would have been easier and dishonest: a signature
test through the callback passes with a token signed by nobody, because nothing
there is checking.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from allauth.socialaccount.internal import jwtkit
from allauth.socialaccount.providers.oauth2.client import OAuth2Error
from django.test import Client

from apps.accounts.models import User
from apps.accounts.tests.stub_issuer import StubIssuer, sign_jwt, wrongly_signed
from apps.accounts.tests.test_rp_login import sign_in

pytestmark = pytest.mark.django_db


def verify(issuer: StubIssuer, token: str) -> dict[str, Any]:
    """The resource-server call: signature checked, nothing taken on trust."""
    decoded: dict[str, Any] = jwtkit.verify_and_decode(
        credential=token,
        keys_url=f"{issuer.base_url}/jwks",
        issuer=issuer.base_url,
        audience=issuer.client_id,
        lookup_kid=jwtkit.lookup_kid_jwk,
        verify_signature=True,
    )
    return decoded


def test_a_correctly_signed_token_verifies(stub_issuer: StubIssuer) -> None:
    """The control. Four refusals and no acceptance is a broken verifier."""
    decoded = verify(stub_issuer, sign_jwt(stub_issuer.claims()))

    assert decoded["sub"] == stub_issuer.subject
    assert decoded["email"] == stub_issuer.email


def test_a_token_signed_with_an_unpublished_key_is_refused(
    stub_issuer: StubIssuer,
) -> None:
    """**Signature.** Well-formed, right `kid`, right claims — wrong key."""
    with pytest.raises(OAuth2Error):
        verify(stub_issuer, wrongly_signed(stub_issuer.claims()))


def test_a_token_for_another_audience_is_refused(stub_issuer: StubIssuer) -> None:
    """**Audience**, at the verifier."""
    claims = {**stub_issuer.claims(), "aud": "some-other-client"}

    with pytest.raises(OAuth2Error):
        verify(stub_issuer, sign_jwt(claims))


def test_an_expired_token_is_refused(stub_issuer: StubIssuer) -> None:
    """**Expiry**, at the verifier."""
    now = int(time.time())
    claims = {**stub_issuer.claims(), "iat": now - 3600, "exp": now - 60}

    with pytest.raises(OAuth2Error):
        verify(stub_issuer, sign_jwt(claims))


def test_a_token_from_another_issuer_is_refused(stub_issuer: StubIssuer) -> None:
    """Issuer — not one of the three the criterion names, and free to have."""
    claims = {**stub_issuer.claims(), "iss": "https://somebody-else.example"}

    with pytest.raises(OAuth2Error):
        verify(stub_issuer, sign_jwt(claims))


# --- the same refusals, where a browser meets them ----------------------------


def test_an_id_token_for_another_audience_refuses_the_login(
    api: Client, stub_issuer: StubIssuer
) -> None:
    """Audience, over the wire: the callback refuses and writes no account."""
    stub_issuer.audience_override = "a-client-that-is-not-us"

    response = sign_in(api)

    assert response.status_code >= 400
    assert not User.objects.filter(email=stub_issuer.email).exists()
    assert "_auth_user_id" not in api.session


def test_an_expired_id_token_refuses_the_login(api: Client, stub_issuer: StubIssuer) -> None:
    """Expiry, over the wire. The stub mints it already dead."""
    stub_issuer.expires_in = -60

    response = sign_in(api)

    assert response.status_code >= 400
    assert not User.objects.filter(email=stub_issuer.email).exists()
    assert "_auth_user_id" not in api.session
