# census: cross-app A7's link builders — one `invite_url`, one invite-path literal
"""The invitation makes a person, and the email can be acted on.

**Nothing here dials Zitadel** (ADR ident-5): the `instance` fixture replaces the
client's socket with a dictionary that answers the way the pinned build answered
the probe — including the two refusals, "User could not be found" and
"User is already initialized", which are the two answers this flow's behaviour
actually turns on.

What is pinned here, in order: the client's v2 half (idempotent creation, a code
that comes back and is never logged, the measured URL shape), the activity that
uses both, the workflow's merge, and the service that starts it on commit. The
run through a real Temporal server — the finish seam closing the run row (house
rule 28) — is at the bottom, in `test_workflows.py`'s style, because that is the
only place the ledger's two states can both be observed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import pytest
from django.core import mail as django_mail
from django.db import transaction
from django.urls import reverse

from apps.accounts import zitadel
from apps.accounts.activities import _invited_person_names, provision_invited_identity
from apps.accounts.models import User
from apps.accounts.tests.conftest import FakeZitadel
from apps.accounts.types import InvitationMessage, InvitedPerson
from apps.core import mail
from apps.core.actor import system_actor
from apps.core.models import Invitation, Membership, Tenant
from apps.core.observability import configure
from apps.core.services import PROVISION_INVITED_PERSON_WORKFLOW, invite_member
from apps.core.tests import test_surfaces as surface_world
from apps.workflows import context as workflow_context
from apps.workflows.models import WorkflowRun

# --- the client's v2 half ----------------------------------------------------


def test_an_invited_user_is_created_once_and_then_found(instance: FakeZitadel) -> None:
    """Search-then-create, which is what an at-least-once activity needs.

    The fake really does create a second object when asked twice, so this is
    idempotence being proved rather than a stub that de-duplicates.
    """
    first = zitadel.ensure_invited_user(
        email="ada@example.com", first_name="Ada", last_name="Lovelace"
    )
    second = zitadel.ensure_invited_user(
        email="ada@example.com", first_name="Ada", last_name="Lovelace"
    )

    assert first.created is True
    assert second.created is False
    assert first.id == second.id
    assert len(instance.users) == 1


def test_the_invited_user_is_created_with_no_password(instance: FakeZitadel) -> None:
    """The whole point of the shape: we never choose or transport their password.

    Asserted on the request the client actually built, because "no password" is
    an ABSENCE and an absence is exactly what a docstring cannot prove.
    """
    zitadel.ensure_invited_user(email="ada@example.com", first_name="Ada", last_name="Lovelace")

    sent = [body for method, path, body in instance.bodies if path == "/v2/users/human"]
    assert len(sent) == 1
    assert "password" not in json.dumps(sent[0]).lower()


def test_creating_an_invite_code_returns_it_and_a_second_call_supersedes(
    instance: FakeZitadel,
) -> None:
    """Not idempotent, and the test says so rather than hiding it.

    Measured on the pinned build: a second `CreateInviteCode` mints a second
    code. The idempotency this flow needs lives one level up, in the
    deterministic workflow id.
    """
    user = zitadel.ensure_invited_user(email="ada@example.com", first_name="A", last_name="L")

    first = zitadel.create_invite_code(user_id=user.id)
    second = zitadel.create_invite_code(user_id=user.id)

    assert first
    assert second
    assert first != second


def test_creating_an_invite_code_for_an_initialized_person_is_a_named_refusal(
    instance: FakeZitadel,
) -> None:
    """The ordinary case of somebody who already signs in here.

    It has to be distinguishable from a fault, because the two lead to different
    emails — and the flow must never retry six times over an answer that will
    never change.
    """
    user = zitadel.ensure_invited_user(email="ada@example.com", first_name="A", last_name="L")
    instance.initialized_users.add(user.id)

    with pytest.raises(zitadel.ZitadelError) as refusal:
        zitadel.create_invite_code(user_id=user.id)

    assert zitadel.is_already_initialized(refusal.value)


def test_a_transport_failure_is_not_read_as_already_initialized(instance: FakeZitadel) -> None:
    """The predicate must not be a synonym for "something went wrong"."""
    with pytest.raises(zitadel.ZitadelError) as refusal:
        zitadel.create_invite_code(user_id="no-such-user")

    assert not zitadel.is_already_initialized(refusal.value)


def test_the_invite_url_is_the_shape_measured_against_the_pinned_build(
    instance: FakeZitadel,
) -> None:
    """The probe fetched this path and got the "Activate User" form back.

    Pinned as a literal, deliberately: it is a fact about somebody else's front
    end, and the day Zitadel moves it this test is the thing that says so
    instead of an email full of dead links.
    """
    url = zitadel.invite_url(user_id="387593267740409862", code="ADHE4B")

    assert url == ("http://zitadel.test/ui/login/user/invite?userID=387593267740409862&code=ADHE4B")


def test_the_invite_code_lifetime_is_read_from_zitadel(instance: FakeZitadel) -> None:
    """One truth: the number in the email is the number Zitadel enforces."""
    assert zitadel.invite_code_lifetime() == timedelta(days=3)


def test_an_unreadable_lifetime_is_none_rather_than_a_guess(instance: FakeZitadel) -> None:
    """An email that states the wrong deadline is worse than one that states none."""
    instance.invite_code_expiry = "not-a-duration"

    assert zitadel.invite_code_lifetime() is None


# --- the activity ------------------------------------------------------------


@pytest.fixture
def invited(
    instance: FakeZitadel,
    homed: str,
    tenant: Tenant,
    owner: User,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., InvitedPerson]]:
    """What the run is started with, for a REAL invitation in a tenant whose realm exists.

    The activity reads the invitation's role off its row and provisions the
    person in the tenant's realm, so the payload names a real invitation and
    the tenant rides on the headers exactly as the interceptor restores it.
    """
    tokens = workflow_context.set_principal(tenant_id=str(tenant.pk), user_id=None, org_id=None)
    # A worker thread's connection hygiene, stood down on the test's own thread.
    monkeypatch.setattr("apps.accounts.activities.close_old_connections", lambda: None)

    def payload(email: str = "ada.lovelace@example.com", role: str = "") -> InvitedPerson:
        invitation = invite_member(
            tenant=tenant,
            email=email,
            role=role or None,
            invited_by=owner,
            actor=system_actor(tenant=tenant),
        )[0]
        return InvitedPerson(
            invitation_id=str(invitation.pk),
            email=email,
            message=InvitationMessage(
                to=[email],
                subject="You have been invited to Acme",
                template="invitation",
                context={},
            ),
        )

    yield payload
    workflow_context.reset_principal(tokens)


def test_the_activity_does_both_calls_and_comes_back_with_a_link(
    instance: FakeZitadel,
    invited: Callable[..., InvitedPerson],
) -> None:
    identity = provision_invited_identity(invited())

    assert identity.zitadel_user_id in instance.users
    assert identity.set_credentials_url.startswith(
        "http://zitadel.test/ui/login/user/invite?userID="
    )
    assert instance.invite_codes[identity.zitadel_user_id]
    # The code that was minted is the code in the link — one round trip, not two.
    assert instance.invite_codes[identity.zitadel_user_id][-1] in identity.set_credentials_url
    assert identity.link_expires_on
    assert identity.already_initialized is False


def test_the_activity_retried_settles_on_one_account(
    instance: FakeZitadel, invited: Callable[..., InvitedPerson]
) -> None:
    """Temporal's at-least-once, which is the normal case and not an edge one."""
    payload = invited()
    first = provision_invited_identity(payload)
    second = provision_invited_identity(payload)

    assert first.zitadel_user_id == second.zitadel_user_id
    assert len(instance.users) == 1
    # A fresh code each attempt, and it is the fresh one that goes out — which is
    # why the two calls are ONE activity.
    assert first.set_credentials_url != second.set_credentials_url


def test_the_activity_reports_an_initialized_person_instead_of_failing(
    instance: FakeZitadel, invited: Callable[..., InvitedPerson], homed: str
) -> None:
    """Somebody who already signs in here, invited into a second tenant."""
    existing = zitadel.ensure_invited_user(
        email="ada.lovelace@example.com", first_name="Ada", last_name="Lovelace", org_id=homed
    )
    instance.initialized_users.add(existing.id)

    identity = provision_invited_identity(invited())

    assert identity.already_initialized is True
    assert identity.set_credentials_url == ""
    assert identity.zitadel_user_id == existing.id


def test_no_log_record_carries_the_invite_code(
    instance: FakeZitadel, caplog: pytest.LogCaptureFixture, invited: Callable[..., InvitedPerson]
) -> None:
    """**The criterion this test would be worth least without.**

    A credential in a log line is a credential in every sink the deployment
    forwards to, for as long as that sink keeps things — which is longer than
    the code's three days and outside anybody's control. Read off the records
    stdlib logging actually received, rendered, so what is searched is the text
    that would have left the process.
    """
    configure()
    with caplog.at_level(logging.INFO):
        identity = provision_invited_identity(invited())

    code = instance.invite_codes[identity.zitadel_user_id][-1]
    emitted = "\n".join(record.getMessage() for record in caplog.records)

    # The test is only meaningful if the flow logged at all and the code exists.
    assert code
    assert "accounts.invitation.identity_provisioned" in emitted
    assert code not in emitted
    # And the link is not logged either — it is the code with a prefix on it.
    assert identity.set_credentials_url not in emitted
    assert "/ui/login/user/invite" not in emitted


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("ada.lovelace@example.com", ("Ada", "Lovelace")),
        ("ada_lovelace@example.com", ("Ada", "Lovelace")),
        ("ada@example.com", ("Ada", "Ada")),
        ("ada.byron.lovelace@example.com", ("Ada", "Byron Lovelace")),
    ],
)
def test_names_are_derived_from_the_address(email: str, expected: tuple[str, str]) -> None:
    """Zitadel wants two names and an invitation carries an address.

    Obviously-derived beats plausible-looking: the person corrects both on the
    screen this is shown on.
    """
    assert _invited_person_names(email) == expected


# --- the service starts it ---------------------------------------------------


@pytest.fixture
def clean_bridge() -> Iterator[None]:
    """Put back what the apps registered at startup."""
    from apps.core import bridge

    saved = bridge.registered()
    yield
    bridge.clear()
    for name, fn in saved.items():
        bridge.register(name, fn)


@pytest.mark.django_db
def test_inviting_somebody_starts_the_provisioning_run(tenant: Tenant, owner: User) -> None:
    """One run, under an id keyed on the row (house rule 18).

    And still no SMTP inside the request: the outbox being empty is what says
    the message waits for the link rather than racing it.
    """
    invitation, _token = invite_member(
        tenant=tenant,
        email="Newcomer@Example.com",
        role=Membership.Role.ADMIN,
        invited_by=owner,
        actor=system_actor(tenant=tenant),
    )

    assert django_mail.outbox == []
    run = WorkflowRun.objects.for_tenant(tenant).get(type=PROVISION_INVITED_PERSON_WORKFLOW)
    assert run.workflow_id == f"{tenant.slug}:accounts:invite:{invitation.pk}"


@pytest.mark.django_db
def test_a_rolled_back_invitation_provisions_nobody(tenant: Tenant, owner: User) -> None:
    """No row, no run, no account in the identity platform.

    The start is registered on `transaction.on_commit`, so the rollback takes it
    with the invitation — which is the whole reason it is not a call.
    """

    class Deliberate(Exception):
        pass

    with pytest.raises(Deliberate), transaction.atomic():
        invite_member(
            tenant=tenant,
            email="ghost@example.com",
            invited_by=owner,
            actor=system_actor(tenant=tenant),
        )
        raise Deliberate

    assert not Invitation.objects.for_tenant(tenant).exists()
    assert not WorkflowRun.objects.for_tenant(tenant).exists()
    assert django_mail.outbox == []


@pytest.mark.django_db
def test_the_payload_the_service_hands_over_carries_the_message_and_no_link(
    tenant: Tenant, owner: User, clean_bridge: None
) -> None:
    """The contract between two apps that never import each other.

    The link is absent here **because it does not exist yet** — Zitadel has not
    been asked for a code. The workflow merges it in. Asserting that absence is
    what stops somebody helpfully building a URL in the service, which would put
    the management call inside the transaction (ADR ident-2, C2).
    """
    from apps.core import bridge

    calls: list[dict[str, Any]] = []
    bridge.register(bridge.START_WORKFLOW_ON_COMMIT, lambda **kwargs: calls.append(kwargs))

    invitation, token = invite_member(
        tenant=tenant, email="ada@example.com", invited_by=owner, actor=system_actor(tenant=tenant)
    )

    assert len(calls) == 1
    assert calls[0]["workflow"] == PROVISION_INVITED_PERSON_WORKFLOW
    assert calls[0]["id"] == f"{tenant.slug}:accounts:invite:{invitation.pk}"
    argument = calls[0]["arg"]
    assert argument["invitation_id"] == str(invitation.pk)
    assert argument["email"] == "ada@example.com"
    assert argument["message"]["template"] == "invitation"
    assert argument["message"]["to"] == ["ada@example.com"]
    assert "set_credentials_url" not in argument["message"]["context"]
    # And OUR bearer credential is still nowhere in it (ADR accounts-1).
    assert token not in json.dumps(argument)


# --- the message ------------------------------------------------------------


def _rendered(context: dict[str, Any]) -> tuple[str, str]:
    base = {
        "tenant_name": "Acme",
        "email": "ada@example.com",
        "role": "Member",
        "invited_by": "owner@example.com",
        "sign_in_url": "http://127.0.0.1:8000/accounts/login/",
        "expires_on": "2026-09-06",
    }
    text, html = mail.render(template="invitation", context={**base, **context})
    assert html is not None
    return text, html


def test_the_email_leads_with_the_credential_setting_link() -> None:
    """Byte for byte in the text part, and that is not pedantry.

    Django autoescapes by default, and the credential-setting URL is the first
    thing this email has ever carried with a query string in it: `&` became
    `&amp;`, a text client showed that literally, and the invited person copied
    a URL that does not work. Caught here. The text template is
    `{% autoescape off %}` — it is plain text, there is nothing for escaping to
    protect — and this assertion is what keeps it that way.
    """
    link = "http://zitadel.test/ui/login/user/invite?userID=1&code=ABC123"
    text, html = _rendered({"set_credentials_url": link, "link_expires_on": "2026-08-26"})

    assert link in text
    assert "&amp;" not in text
    # In HTML the escaped form inside the href is the CORRECT one — a browser
    # parses it back to `&` — so the assertion there is that the link is real
    # and reachable, not that it is unescaped.
    assert 'href="http://zitadel.test/ui/login/user/invite?userID=1&amp;code=ABC123"' in html
    for rendered in (text, html):
        # The link's own deadline, which is the one the reader can miss.
        assert "2026-08-26" in rendered


def test_the_email_never_offers_a_signup_that_does_not_exist() -> None:
    """The exact wrongness: there is no signup door and there never was.

    Checked on BOTH branches, because a fallback nobody looks at is where the
    old wording would survive.
    """
    with_link, with_link_html = _rendered(
        {"set_credentials_url": "http://z/x?code=1", "link_expires_on": "2026-08-26"}
    )
    without, without_html = _rendered({"set_credentials_url": "", "link_expires_on": ""})

    for rendered in (with_link, with_link_html, without, without_html):
        lowered = rendered.lower()
        assert "sign up" not in lowered
        assert "signup" not in lowered


def test_the_email_tells_an_existing_person_to_sign_in() -> None:
    """The branch for somebody who already has credentials here."""
    text, html = _rendered({"set_credentials_url": "", "link_expires_on": ""})

    for rendered in (text, html):
        assert "http://127.0.0.1:8000/accounts/login/" in rendered
        assert "sign in" in rendered.lower()
        assert "no password yet" not in rendered.lower()


def test_the_two_expiries_are_each_attached_to_what_they_govern() -> None:
    """One truth per claim (criterion 4).

    The invite code stands for three days and our row for fourteen, and the old
    email stated only the fourteen — beside a link that died in three. Both
    numbers are true; what was wrong was printing one of them next to the other
    one's link.
    """
    text, _html = _rendered(
        {"set_credentials_url": "http://z/x?code=1", "link_expires_on": "2026-08-26"}
    )

    assert "That link stops working on 2026-08-26." in text
    assert "The invitation itself stands\nuntil 2026-09-06" in text


def test_no_template_markup_survives_either_branch() -> None:
    """The Mailpit lesson, re-run over the branch that did not exist before."""
    for context in (
        {"set_credentials_url": "http://z/x?code=1", "link_expires_on": "2026-08-26"},
        {"set_credentials_url": "", "link_expires_on": ""},
    ):
        for rendered in _rendered(context):
            for marker in ("{#", "#}", "{%", "%}", "{{", "}}"):
                assert marker not in rendered


# --- A7.3 · both links follow `invite_url`, and there is no second builder ----


def test_ours_the_activitys_link_is_our_page(
    instance: FakeZitadel, settings: Any, invited: Callable[..., InvitedPerson]
) -> None:
    """The invitation email's link follows the door, exactly as day zero's does.

    Two producers of a credential-setting link exist in this tree — this
    activity and `zitadel_first_admin` — and under `ours` a deployment where
    one of them still pointed at the identity platform would be a product
    whose first human lands on our page and whose second lands on somebody
    else's, with one of the two screens never having been designed for them.
    """
    settings.SIGN_IN_DOOR = "ours"

    identity = provision_invited_identity(invited())

    code = instance.invite_codes[identity.zitadel_user_id][-1]
    assert identity.set_credentials_url == zitadel.invite_url(
        user_id=identity.zitadel_user_id, code=code
    )
    assert identity.set_credentials_url.startswith(
        f"{settings.PUBLIC_BASE_URL}{reverse('account_login')}?"
    )
    assert zitadel.INVITE_PATH not in identity.set_credentials_url
    assert f"userID={identity.zitadel_user_id}" in identity.set_credentials_url
    assert f"code={code}" in identity.set_credentials_url


def test_every_credential_setting_link_in_the_tree_comes_from_invite_url() -> None:
    """The census behind the two cases above: one builder, and it branches.

    A second place that spelled the hosted path would keep passing every test
    about the door it was written for. Two halves:

    (1) The path is a STRING LITERAL in exactly one module. Read by AST and
        compared for equality rather than grepped, so that prose which quotes
        the path — `zitadel_measure`'s own description of what C7 measures —
        is not counted as a second spelling of it. A comment cannot build a
        URL; a constant can.
    (2) Every producer of a credential-setting link calls `invite_url`. The
        population is named here because it is small and because naming it is
        what makes a THIRD producer a failure rather than an omission.
    """
    import ast
    from pathlib import Path

    from django.conf import settings as django_settings

    from apps.core.tests.tree_census import source_text, source_tree

    root = Path(django_settings.BASE_DIR) / "apps"
    walked = [path for path in sorted(root.rglob("*.py")) if "tests" not in path.parts]
    spellers = sorted(
        str(path.relative_to(django_settings.BASE_DIR))
        for path in walked
        if any(
            isinstance(node, ast.Constant) and node.value == zitadel.INVITE_PATH
            for node in ast.walk(source_tree(path))
        )
    )
    assert spellers == ["apps/accounts/zitadel.py"], spellers

    # The invitation activity reaches its link through the realm port now, so the
    # port's Zitadel adapter is the producer that calls the builder for it.
    producers = (
        "apps/accounts/management/commands/zitadel_first_admin.py",
        "apps/accounts/realms/zitadel.py",
    )
    for name in producers:
        assert "zitadel.invite_url(" in source_text(Path(django_settings.BASE_DIR) / name), name
    callers = sorted(
        str(path.relative_to(django_settings.BASE_DIR))
        for path in walked
        if "invite_url(" in source_text(path)
    )
    assert callers == sorted([*producers, "apps/accounts/zitadel.py"]), callers


def test_the_email_leads_with_the_credential_setting_link_under_either_door() -> None:
    """A7.3 · the template is door-agnostic, and that is a property, not luck.

    The mail renders whatever link the activity hands it, so the door lives
    one layer up — which is why the case above asserts on the ACTIVITY and
    this one asserts the template survives our own URL shape. Our page's link
    carries the same `?userID=…&code=…` tail (A5.5 kept Zitadel's spelling),
    so the ampersand trap the original case was written for is live on both
    doors and is re-driven here against ours.
    """
    link = "https://app.yourcompany.test/accounts/login/?userID=1&code=ABC123"
    text, html = _rendered({"set_credentials_url": link, "link_expires_on": "2026-08-26"})

    assert link in text
    assert "&amp;" not in text
    assert f'href="{link.replace("&", "&amp;")}"' in html


# --- the link a REAL invitation mails lands on the role's surface --------------

customer_role = surface_world.customer_role
two_faces = surface_world.two_faces


@pytest.mark.parametrize(
    ("role", "host"),
    [("customer", surface_world.CUSTOMER_HOST), ("member", surface_world.STAFF_HOST)],
)
def test_the_set_credentials_link_lands_on_the_host_of_the_invited_role(
    instance: FakeZitadel,
    settings: Any,
    two_faces: Any,
    invited: Callable[..., InvitedPerson],
    homed: str,
    role: str,
    host: str,
) -> None:
    """A customer's link on the customer host, a staff member's on the staff host.

    The role is read off the invitation row the run was started for, and the
    link is built by the one URL seam through the realm port — so the mail a
    real invitation sends carries the host of the surface the role belongs to,
    and the person is made in the tenant's realm, never the staff org.
    """
    settings.SIGN_IN_DOOR = "ours"

    identity = provision_invited_identity(invited(email=f"{role}@example.com", role=role))

    assert urlsplit(identity.set_credentials_url).hostname == host
    assert instance.users[identity.zitadel_user_id]["details"]["resourceOwner"] == homed
