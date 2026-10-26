"""Rows every comms test needs, built the way the product builds them.

C1-1a wrote these through the bare manager and said why: `Recipient`,
`MessageTemplate` and `ChannelPreference` had no write services yet. C1-1b built
them, so every helper here is now a call to one — which is worth more than
tidiness. A fixture that writes a preference row by hand can write a row the
services would refuse (a channel `Channel` has no member for, a half-open quiet
window, a consent row in a branch the sender cannot read), and every consent
test after it would be proving `send()` against a state the product cannot
reach. Going through the services means the set-up is as constrained as the
product is.

Each helper therefore takes an **actor** rather than a tenant and an
organization: that is what the services take, and where a row lands is decided
by the acting hat and never by an argument. `owner_actor` is the usual one; the
branch tests pass an actor per node, which is exactly the point they are making.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.comms.models import Category, Channel, ChannelPreference, MessageTemplate, Recipient
from apps.comms.services import (
    archive_recipient,
    create_recipient,
    create_template,
    grant_consent,
    retire_template,
    revise_template,
    revoke_consent,
    set_quiet_hours,
    suppress_recipient,
)
from apps.conftest import PASSWORD
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization, root_organization

#: What every fixture template asks its caller for. Kept small on purpose: the
#: point of the schema is that `send()` refuses a context missing a required
#: variable, and one variable proves that as well as ten.
CONTEXT_SCHEMA: dict[str, Any] = {
    "required": ["name"],
    "properties": {"name": {"type": "string"}, "invoices": {"type": "integer"}},
}


def _tenant_of(actor: Actor) -> Tenant:
    """The actor's tenant, insisted on rather than assumed.

    Every service here takes `tenant` explicitly — a write must never read the
    tenant from global state — and an actor fixture with no tenant would produce
    a set-up failure three assertions later instead of here.
    """
    assert actor.tenant is not None, "a comms fixture needs an actor with a tenant"
    return actor.tenant


def make_template(
    *,
    actor: Actor,
    name: str = "receipt",
    category: str = Category.TRANSACTIONAL,
    channel: str = Channel.EMAIL,
    subject: str = "Your receipt, {{ name }}",
    body: str = "Hello {{ name }}, here is your receipt.",
) -> MessageTemplate:
    """Version 1 of a template, through the service that claims the name."""
    return create_template(
        tenant=_tenant_of(actor),
        actor=actor,
        name=name,
        body=body,
        subject=subject,
        channel=channel,
        category=category,
        context_schema=CONTEXT_SCHEMA,
    )


def make_next_version(
    *,
    actor: Actor,
    name: str = "receipt",
    subject: str = "v2 for {{ name }}",
    body: str = "Hello {{ name }}, this is the second version.",
    retired: bool = False,
) -> MessageTemplate:
    """The next version of an existing template — a new row, never an edit.

    `retired=True` publishes it and immediately takes it out of service, which
    is the state a test needs to prove that a name resolves to the newest
    *active* version and not simply the newest one. Both halves are services:
    there is no path in this app, fixtures included, that writes `is_active` by
    hand.
    """
    revision = revise_template(
        tenant=_tenant_of(actor), actor=actor, name=name, body=body, subject=subject
    )
    if retired:
        revision = retire_template(tenant=_tenant_of(actor), actor=actor, template=revision)
    return revision


def make_recipient(
    *,
    actor: Actor,
    email: str = "reader@example.com",
    display_name: str = "A Reader",
) -> Recipient:
    """A contact, in whichever part of the tenant the actor is acting as."""
    return create_recipient(
        tenant=_tenant_of(actor), actor=actor, email=email, display_name=display_name
    )


def make_preference(
    *,
    actor: Actor,
    recipient: Recipient,
    channel: str = Channel.EMAIL,
    consented: bool = False,
    revoked: bool = False,
    suppressed: bool = False,
    quiet_hours: tuple[time, time] | None = None,
    quiet_hours_timezone: str = "UTC",
) -> ChannelPreference:
    """One preference row, expressed as the facts a test cares about.

    `consented` and `revoked` are booleans here and timestamps in the table:
    "they said yes, then later said no" is what a revocation is, so `revoked`
    grants first and revokes after, which is the only order that produces the
    row a real revocation leaves behind. The verbs are called in the order the
    person would have said them, and the row comes out as the product's.
    """
    tenant = _tenant_of(actor)
    preference: ChannelPreference | None = None
    if consented or revoked:
        preference = grant_consent(tenant=tenant, actor=actor, recipient=recipient, channel=channel)
    if revoked:
        preference = revoke_consent(
            tenant=tenant, actor=actor, recipient=recipient, channel=channel
        )
    if quiet_hours is not None:
        start, end = quiet_hours
        preference = set_quiet_hours(
            tenant=tenant,
            actor=actor,
            recipient=recipient,
            channel=channel,
            start=start,
            end=end,
            timezone_name=quiet_hours_timezone,
        )
    if suppressed:
        preference = suppress_recipient(
            tenant=tenant, actor=actor, recipient=recipient, channel=channel
        )
    assert preference is not None, (
        "make_preference with no fact to record would write no row — and the "
        "absence of a row is itself an answer, so say which fact you mean"
    )
    return preference


def make_archived_recipient(*, actor: Actor, email: str, display_name: str = "") -> Recipient:
    """A contact that has been closed. Still readable; out of the contact book."""
    recipient = make_recipient(actor=actor, email=email, display_name=display_name)
    return archive_recipient(tenant=_tenant_of(actor), actor=actor, recipient=recipient)


@pytest.fixture
def recipient(owner_actor: Actor) -> Recipient:
    return make_recipient(actor=owner_actor)


@pytest.fixture
def receipt(owner_actor: Actor) -> MessageTemplate:
    """A transactional template: goes out unless something suppresses it."""
    return make_template(actor=owner_actor)


@pytest.fixture
def newsletter(owner_actor: Actor) -> MessageTemplate:
    """A marketing template: goes out only with live consent, outside quiet hours."""
    return make_template(
        actor=owner_actor,
        name="newsletter",
        category=Category.MARKETING,
        subject="This month, {{ name }}",
        body="Hello {{ name }}, here is the newsletter.",
    )


# --- the hierarchy, shared by every file that proves a branch wall ---------------


@dataclass
class Branches:
    """root → A → A1, and root → B. Four nodes, three people, one tenant."""

    tenant: Tenant
    hq: Organization
    seller_a: Organization
    sub_a1: Organization
    seller_b: Organization
    owner: User
    manager: User
    clerk: User


@pytest.fixture
def branches(tenant: Tenant, owner: User) -> Branches:
    hq = root_organization(tenant=tenant)
    acting = actor_for(user=owner, tenant=tenant, org=hq)
    seller_a = create_organization(
        tenant=tenant, parent=hq, name="Seller A", slug="seller-a", actor=acting
    )
    seller_b = create_organization(
        tenant=tenant, parent=hq, name="Seller B", slug="seller-b", actor=acting
    )
    sub_a1 = create_organization(
        tenant=tenant, parent=seller_a, name="Sub A1", slug="sub-a1", actor=acting
    )
    manager = create_user(email="manager@example.com", password=PASSWORD)
    add_membership(
        user=manager,
        tenant=tenant,
        organization=seller_a,
        is_default=True,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    clerk = create_user(email="clerk@example.com", password=PASSWORD)
    add_membership(
        user=clerk,
        tenant=tenant,
        organization=sub_a1,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    return Branches(
        tenant=tenant,
        hq=hq,
        seller_a=seller_a,
        sub_a1=sub_a1,
        seller_b=seller_b,
        owner=owner,
        manager=manager,
        clerk=clerk,
    )


@pytest.fixture(autouse=True)
def _handler_runs_at_the_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    """The receiver's handler run, done at the receipt: these tests read its effect at the 202."""
    from apps.connections.tests.handler_runs import run_handlers_at_the_receipt

    run_handlers_at_the_receipt(monkeypatch)
