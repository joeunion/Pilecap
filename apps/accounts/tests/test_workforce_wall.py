"""The workforce wall: who the platform door may turn into a NEW person.

There is one interactive sign-in road — Zitadel — and the deployment's own
Google Workspace door is an identity provider *inside* it
(`sync_workforce_identity_config` → one activity →
`zitadel.ensure_google_identity_provider`). Its assertions therefore arrive on
the platform branch of the adapter like everybody else's, and the domain
restriction `architecture.md` promises for the workforce ("Google federated
through Zitadel, domain-restricted") has to be enforced there — on the one
branch where a person nobody has vouched for becomes a `User`.

The four cases the wall is judged by, each driven through the adapter with the
object allauth actually hands it:

* a new subject at a workspace domain becomes a `User` carrying `zitadel_sub`
  — the join every downstream mechanism keys on (erasure's platform revocation,
  the MCP resource server's subject lookup);
* a new subject at a domain nobody configured is refused, writes no row, and
  leaves `accounts.platform.refused reason=domain_not_allowed`;
* an EXISTING person at any domain — somebody invited, seeded, or made by
  `createsuperuser`, who signs in with a Zitadel-hosted password — is not a
  signup and walks straight through;
* an EMPTY `GOOGLE_WORKSPACE_DOMAINS` fails CLOSED: no workforce door is
  configured, so no new person from nobody's domain becomes a `User` at all.

And the one door that is not the workforce's: an address holding a live
invitation is a person a tenant already vouched for, so its first sign-in is a
signup the invitation authorised, whatever the domain.
"""

from __future__ import annotations

import io
import logging
from datetime import timedelta
from typing import Any

import pytest
from allauth.core.exceptions import ImmediateHttpResponse
from django.core.management import call_command
from django.http import HttpRequest

from apps.accounts.adapter import SocialAccountAdapter
from apps.accounts.models import FirstAdminVouch, User
from apps.accounts.selectors import get_platform_provider_id
from apps.accounts.services import create_user
from apps.accounts.tests.conftest import FakeZitadel, assertion, subject_of
from apps.core.actor import system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Membership, Tenant
from apps.core.services import invite_member
from apps.core.time import now

pytestmark = pytest.mark.django_db

WORKFORCE_DOMAIN = "union.studio"
NOBODYS_ADDRESS = "stranger@gmail.com"


@pytest.fixture
def workforce(settings: Any) -> None:
    """A deployment whose workforce door names its domain."""
    settings.GOOGLE_WORKSPACE_DOMAINS = [WORKFORCE_DOMAIN]


def _sign_in(request: HttpRequest, *, subject: str, email: str) -> Any:
    """One platform assertion through the gate and, if it passes, the signup lock."""
    login = assertion(provider=get_platform_provider_id(), subject=subject, email=email)
    door = SocialAccountAdapter(request)
    door.pre_social_login(request, login)
    return login


def _sign_up(request: HttpRequest, login: Any) -> User:
    """What allauth does next for a login nobody was linked to: ask, then write."""
    door = SocialAccountAdapter(request)
    assert door.is_open_for_signup(request, login) is True
    login.user = User(email=login.email_addresses[0].email)
    return door.save_user(request, login)


def test_a_new_person_at_a_workspace_domain_becomes_a_user_with_the_join(
    workforce: None, platform_provider: None, login_request: HttpRequest
) -> None:
    """(a) The workforce door open: the row, and the subject on it."""
    login = _sign_in(login_request, subject="zitadel|new", email=f"new@{WORKFORCE_DOMAIN}")
    assert login.user is None or login.user.pk is None

    user = _sign_up(login_request, login)

    user.refresh_from_db()
    assert user.email == f"new@{WORKFORCE_DOMAIN}"
    assert subject_of(user) == "zitadel|new"


def test_a_new_person_from_nobodys_domain_is_refused_and_writes_nothing(
    workforce: None,
    platform_provider: None,
    login_request: HttpRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(b) The wall: a refusal page, no row, and the structured line naming why.

    The page is reachable by anybody who can get the identity platform to
    assert an address, so it names no domain — the sentence the retired direct
    road used, without the vendor in it.
    """
    before = User.objects.count()
    caplog.clear()

    with caplog.at_level(logging.WARNING), pytest.raises(ImmediateHttpResponse) as raised:
        _sign_in(login_request, subject="zitadel|stranger", email=NOBODYS_ADDRESS)

    assert raised.value.response.status_code == 403
    page = raised.value.response.content.decode()
    assert "not part of this organisation" in page
    assert WORKFORCE_DOMAIN not in page
    assert User.objects.count() == before
    refused = [r for r in caplog.records if "accounts.platform.refused" in r.getMessage()]
    assert refused, [r.getMessage() for r in caplog.records]
    assert "domain_not_allowed" in refused[-1].getMessage()
    assert "gmail.com" in refused[-1].getMessage()

    # The second lock says the same thing, so a branch added above it later
    # cannot turn the wall into a row.
    login = assertion(
        provider=get_platform_provider_id(), subject="zitadel|stranger", email=NOBODYS_ADDRESS
    )
    assert SocialAccountAdapter(login_request).is_open_for_signup(login_request, login) is False


def test_an_existing_person_at_any_domain_is_not_a_signup(
    workforce: None, platform_provider: None, login_request: HttpRequest
) -> None:
    """(c) The pilot's negative: an account that already exists is linked, never walled."""
    existing = create_user(email="pilot@customer-of-ours.example")

    login = _sign_in(login_request, subject="zitadel|pilot", email=existing.email)

    assert login.user is not None
    assert login.user.pk == existing.pk
    existing.refresh_from_db()
    assert subject_of(existing) == "zitadel|pilot"


def test_no_workforce_domains_fails_closed(
    settings: Any, platform_provider: None, login_request: HttpRequest
) -> None:
    """(d) Empty is OFF, never "any domain": no new person from nobody's domain.

    The ruled default. A deployment that configured no workforce door has no
    door through which a stranger becomes an account, and the failure the open
    reading would produce — everyone the identity platform will vouch for
    quietly becoming a user — looks exactly like success.
    """
    settings.GOOGLE_WORKSPACE_DOMAINS = []

    with pytest.raises(ImmediateHttpResponse):
        _sign_in(login_request, subject="zitadel|stranger", email=NOBODYS_ADDRESS)
    with pytest.raises(ImmediateHttpResponse):
        _sign_in(login_request, subject="zitadel|anyone", email=f"anyone@{WORKFORCE_DOMAIN}")
    assert User.objects.count() == 0


def test_an_invited_address_signs_up_whatever_its_domain(
    settings: Any,
    platform_provider: None,
    login_request: HttpRequest,
    tenant: Tenant,
) -> None:
    """A tenant vouched for this address, so its first sign-in is not the workforce's.

    With the workforce door off entirely — the strictest deployment — an
    invitation is still how somebody new arrives, and the membership it names
    is waiting when they do.
    """
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    invite_member(
        tenant=tenant, email="invited@elsewhere.example", actor=system_actor(tenant=tenant)
    )

    login = _sign_in(login_request, subject="zitadel|invited", email="invited@elsewhere.example")
    user = _sign_up(login_request, login)

    user.refresh_from_db()
    assert subject_of(user) == "zitadel|invited"
    assert Membership.objects.filter(user_id=user.pk, tenant=tenant).exists()


# --- The day-zero door: the person the operator invited on the box -----------

FIRST_ADMIN = "a@example.test"


def _invite_the_first_human(settings: Any, *, email: str = FIRST_ADMIN) -> None:
    """`zitadel_first_admin` as the operator runs it, Zitadel being the fake."""
    settings.PUBLIC_BASE_URL = "https://app.yourcompany.test"
    call_command("zitadel_first_admin", f"--email={email}", stdout=io.StringIO())


def test_the_first_human_the_operator_invited_signs_up_with_no_door_and_no_tenant(
    settings: Any,
    instance: FakeZitadel,
    platform_provider: None,
    login_request: HttpRequest,
) -> None:
    """No workforce door, no tenant: the operator's invitee signs up, and spends the vouch."""
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    _invite_the_first_human(settings)

    login = _sign_in(login_request, subject="zitadel|first", email=FIRST_ADMIN)
    user = _sign_up(login_request, login)

    user.refresh_from_db()
    assert subject_of(user) == "zitadel|first"
    vouch = FirstAdminVouch.objects.get(email=FIRST_ADMIN)
    assert vouch.consumed_at is not None and vouch.consumed_by_id == user.pk
    assert AuditEntry.objects.filter(action="accounts.mark_first_admin_vouch_spent").count() == 1


def test_the_first_admin_vouch_admits_one_address_once(
    settings: Any,
    instance: FakeZitadel,
    platform_provider: None,
    login_request: HttpRequest,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A stranger at the same domain is still refused, and a spent vouch admits nobody."""
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    _invite_the_first_human(settings)
    caplog.clear()

    with caplog.at_level(logging.WARNING), pytest.raises(ImmediateHttpResponse):
        _sign_in(login_request, subject="zitadel|other", email="b@example.test")
    refused = [r for r in caplog.records if "accounts.platform.refused" in r.getMessage()]
    assert refused and "domain_not_allowed" in refused[-1].getMessage()

    _sign_up(login_request, _sign_in(login_request, subject="zitadel|first", email=FIRST_ADMIN))

    assert SocialAccountAdapter._may_sign_up(FIRST_ADMIN) is False
    assert User.objects.filter(email="b@example.test").exists() is False


def test_an_expired_vouch_admits_nobody(settings: Any) -> None:
    """Fails closed on the clock: day zero has a deadline the command printed."""
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    FirstAdminVouch.objects.create(email=FIRST_ADMIN, expires_at=now() - timedelta(seconds=1))

    assert SocialAccountAdapter._may_sign_up(FIRST_ADMIN) is False


def test_a_vouch_admits_nobody_once_a_tenant_exists(settings: Any, tenant: Tenant) -> None:
    """Fails closed at the first tenant: from then on `invite_member` is the only way in."""
    settings.GOOGLE_WORKSPACE_DOMAINS = []
    FirstAdminVouch.objects.create(email=FIRST_ADMIN, expires_at=now() + timedelta(days=1))

    assert SocialAccountAdapter._may_sign_up(FIRST_ADMIN) is False
