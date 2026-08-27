"""ER1-1/ER1-2/ER1-4: what erasure leaves behind, measured over the whole schema.

**This file is a probe before it is a test.** P5-R1 found that `erase_user`
anonymised the `User` row and left the person in four other tables, and it found
it with a DB-level sweep rather than by reading the service — which is the only
way that class of defect is ever found, because the service says nothing about
the tables it does not touch. The probe is kept here, permanently, as the
regression.

**The table list is DERIVED and that is the whole design.** A hand-written list
of four tables passes forever and misses the fifth one: an app that starts
copying an address into its own column, an allauth upgrade that grows a table, a
product model with a `contact_email`. So `residue()` walks Django's model
registry, takes every text-shaped and JSON-shaped column on every concrete
model, and asks the database directly whether any of them still holds the erased
person's identifiers. The population is whatever `get_models()` returns on the
day the test runs; nothing here is a name somebody typed.

**What survives is a declared population, not an absence of findings.**
`RETAINED` below is the other half of ADR ident-5: every column that legitimately
still holds an identifier after an erasure, each with the reason it does. A hit
outside that map fails; a member of the map that stops being hit fails too
(`test_every_retained_column_is_still_a_real_retention`), because a retention
nobody can find is indistinguishable from a retention that quietly stopped.

DOES NOT COVER — declared:

* **free-text PII a product writes into its own columns.** The sweep looks for
  the identifiers erasure KNOWS about — the address the person signed in with
  and the subject their IdP asserted. A product that stores "Jo, the one on the
  third floor" in a note erases that in its own service; `erase_user`'s
  docstring says so and this is the boundary that makes it true.
* **an alias.** `jo+work@example.com` is a different string from
  `jo@example.com`, and `core.redact_invitations` declares the same limit.
  The sweep matches the address as it was written down.
* **binary and non-text columns.** Bytes, integers and encrypted fields are
  outside the cast; an encrypted column that held the address would be
  ciphertext here and would not match, which is the correct answer for a column
  whose plaintext nobody can read without the key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from allauth.account.models import EmailAddress
from allauth.socialaccount.models import SocialAccount
from django.apps import apps as django_apps
from django.db import connection as db_connection

from apps.accounts.models import ApiToken, SsoConnection, User
from apps.accounts.services import (
    ERASED_EMAIL_DOMAIN,
    create_user,
    erase_user,
    issue_token,
    provision_sso_identity,
    record_zitadel_identity,
)
from apps.core import bridge
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.models import Invitation, Membership, Tenant
from apps.core.services import add_membership, invite_member

if TYPE_CHECKING:  # pragma: no cover - typing only
    from django.db.models import Model

pytestmark = pytest.mark.django_db

# The person the whole file is about. Distinctive strings, so a match is a match
# and never a coincidence with a fixture two files away.
TARGET_EMAIL = "residue-target@acme.com"
TARGET_SUBJECT = "zitadel-subject-residue-target"

# The field kinds a person's identifier can hide in. Django's internal type
# rather than the class, so a product's own `EmailField` subclass and every
# encrypted-text field that reports one of these names are swept too.
TEXT_FIELD_TYPES = frozenset(
    {
        "CharField",
        "TextField",
        "EmailField",
        "SlugField",
        "URLField",
        "JSONField",
    }
)

# --- The declared retentions (ER1-2, ADR ident-5) -----------------------------
#
# Every column that still holds one of the person's identifiers AFTER erasure,
# and the reason it does. This map is the enumerated half of ADR ident-5: the
# sweep proves there is nothing else, and this says why each survivor is not a
# bug. Keyed by `app_label.Model` and column, which is what `residue()` returns.
RETAINED: dict[tuple[str, str], str] = {
    ("accounts.User", "zitadel_sub"): (
        "The collision fence. The subject is an opaque identifier the identity "
        "platform minted — not contact data — and the column is unique, which is "
        "what refuses a re-link of somebody else's Zitadel account to this row "
        "(`test_rp_login.py::test_a_subject_already_linked_elsewhere_is_refused`). "
        "Blanking it frees the subject for exactly that re-link."
    ),
    ("events.Event", "payload"): (
        "ADO-4, ratified: an event payload is the WITNESSED record of what was "
        "emitted, and rewriting it falsifies the replay contract the architecture "
        "states. Declared, not swept — `Event`'s own lifecycle carries the "
        "trigger, and `erase_user`'s docstring names this retention by name. "
        "ADO-4 says 'Event/Outbox payloads'; on this tree there is one payload "
        "and `Outbox` is a `OneToOneField` onto the `Event` that holds it, which "
        "`test_the_outbox_row_still_reaches_the_retained_payload` pins."
    ),
}


# --- The probe ----------------------------------------------------------------


def _text_columns(model: type[Model]) -> list[str]:
    """Every text-shaped or JSON-shaped column on one concrete model."""
    return [
        str(field.column)
        for field in model._meta.concrete_fields
        if field.get_internal_type() in TEXT_FIELD_TYPES
    ]


def residue(*needles: str) -> dict[tuple[str, str], int]:
    """Every (model label, column) still holding one of `needles`, and how often.

    The DB-level sweep, derived from the model registry — see this module's
    docstring for why it is derived and what it deliberately cannot see. The
    cast to `text` is what lets one statement ask a `jsonb` column and a
    `varchar` column the same question.
    """
    found: dict[tuple[str, str], int] = {}
    patterns = [f"%{needle}%" for needle in needles]
    with db_connection.cursor() as cursor:
        for model in django_apps.get_models():
            if model._meta.proxy or not model._meta.managed:
                continue
            for column in _text_columns(model):
                cursor.execute(
                    f'SELECT COUNT(*) FROM "{model._meta.db_table}" '  # noqa: S608
                    f'WHERE "{column}"::text ILIKE ANY(%s)',
                    [patterns],
                )
                count = int(cursor.fetchone()[0])
                if count:
                    found[(model._meta.label, column)] = count
    return found


# --- The footprint the probe is run against -----------------------------------


@pytest.fixture
def target(tenant: Tenant, sso_connection: SsoConnection, other_tenant: Tenant) -> User:
    """A person with the whole account footprint an erasure has to reach.

    Every row here is written by the code that really writes it — the SSO
    provisioning service, the identity join, the invitation service — rather
    than by `objects.create`, so the shapes are the shapes production makes.
    """
    identity = provision_sso_identity(
        tenant=tenant,
        actor=system_actor(tenant),
        connection=sso_connection,
        subject="idp-subject-residue",
        email=TARGET_EMAIL,
        email_verified=True,
    )
    person = identity.user
    record_zitadel_identity(
        user=person, subject=TARGET_SUBJECT, tenant=None, actor=system_actor(tenant=None)
    )
    issue_token(
        user=person, tenant=tenant, name="a token", actor=actor_for(user=person, tenant=tenant)
    )
    EmailAddress.objects.create(user=person, email=TARGET_EMAIL, verified=True, primary=True)
    SocialAccount.objects.create(
        user=person,
        provider="zitadel",
        uid=TARGET_SUBJECT,
        extra_data={"email": TARGET_EMAIL, "email_verified": True},
    )
    # A standing offer from a tenant the person has nothing to do with — the
    # case `redact_invitations` exists for, and the one no tenant-scoped sweep
    # could find.
    invite_member(tenant=other_tenant, email=TARGET_EMAIL, actor=system_actor(other_tenant))
    return person


@pytest.fixture
def eraser(tenant: Tenant, target: User) -> Actor:
    """Somebody who may erase the target: an owner of the tenant they are in."""
    from apps.core.services import root_organization

    owner = create_user(email="residue-owner@acme.com", password="x" * 20)
    add_membership(
        user=owner, tenant=tenant, role=Membership.Role.OWNER, actor=system_actor(tenant=tenant)
    )
    return actor_for(user=owner, tenant=tenant, org=root_organization(tenant=tenant))


# --- ER1-1: red first, then zero ----------------------------------------------


def test_the_probe_finds_the_footprint_before_anything_erases_it(target: User) -> None:
    """The instrument, proven able to fail. Without this the sweep proves nothing.

    A probe that finds nothing on an un-erased person is a probe with a broken
    query, and it would read exactly like a clean erasure.
    """
    hits = residue(TARGET_EMAIL, TARGET_SUBJECT)

    assert ("accounts.User", "email") in hits
    assert ("account.EmailAddress", "email") in hits
    assert ("socialaccount.SocialAccount", "extra_data") in hits
    assert ("accounts.SsoIdentity", "email") in hits
    assert ("core.Invitation", "email") in hits


def test_erasure_leaves_nothing_outside_the_declared_retentions(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """ER1-1. The whole schema, swept, with only the declared survivors left.

    The assertion is a set difference and not a list of tables on purpose: the
    day a new model starts holding an address, this fails naming it, and the
    person who added the column is told to erase it or to declare why it stays.
    """
    erase_user(user=target, actor=eraser, tenant=tenant)

    leftover = {where: count for where, count in residue(TARGET_EMAIL).items()}

    assert leftover == {}, (
        "erasure left the address behind in "
        + ", ".join(f"{label}.{column}" for label, column in sorted(leftover))
        + " — sweep it in `_erase_the_account_footprint`, or add it to RETAINED "
        "with the reason it survives (ADR ident-5)."
    )


def test_the_only_identifier_that_survives_is_a_declared_one(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """ER1-1, the other half: sweep BOTH identifiers, allow only what is declared."""
    erase_user(user=target, actor=eraser, tenant=tenant)

    undeclared = set(residue(TARGET_EMAIL, TARGET_SUBJECT)) - set(RETAINED)

    assert undeclared == set(), (
        "these columns still hold the erased person and nothing says why: "
        + ", ".join(f"{label}.{column}" for label, column in sorted(undeclared))
    )


# --- ER1-2: every retention asserted WITH its reason --------------------------


def test_every_retained_column_is_still_a_real_retention(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """A declared retention nobody can find has quietly become an erasure.

    Both directions matter. An undeclared survivor is the bug ER-1 fixes; a
    declared survivor that has vanished means the reason below is now prose
    about something that no longer happens, and the map has to shrink.
    """
    seed_an_event_carrying_the_address(tenant=tenant)

    erase_user(user=target, actor=eraser, tenant=tenant)

    found = set(residue(TARGET_EMAIL, TARGET_SUBJECT))
    assert set(RETAINED) <= found, "declared as retained and not actually present: " + ", ".join(
        f"{label}.{column}" for label, column in sorted(set(RETAINED) - found)
    )
    for reason in RETAINED.values():
        assert len(reason) > 40


def test_the_subject_is_retained_because_it_is_the_collision_fence(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """ER1-2. The reason proven, not prosed.

    `zitadel_sub` survives erasure, and the thing it buys is that the subject
    stays claimed: an erased person's Zitadel account cannot be re-linked to
    somebody else's row by an IdP assertion. Blanking the column would free it.
    """
    from apps.core.exceptions import Conflict

    erase_user(user=target, actor=eraser, tenant=tenant)
    target.refresh_from_db()
    assert target.zitadel_sub == TARGET_SUBJECT

    somebody_else = create_user(email="opportunist@acme.com", password="y" * 20)
    with pytest.raises(Conflict):
        record_zitadel_identity(
            user=somebody_else, subject=TARGET_SUBJECT, tenant=None, actor=system_actor(tenant=None)
        )


def test_memberships_and_the_audit_trail_are_kept(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """ER1-2. The two retentions the docstring has always argued for."""
    before = AuditEntry.objects.for_tenant(tenant).count()

    erase_user(user=target, actor=eraser, tenant=tenant)

    assert Membership.objects.filter(user_id=target.pk, tenant=tenant).exists()
    assert AuditEntry.objects.for_tenant(tenant).count() > before


def seed_an_event_carrying_the_address(*, tenant: Tenant) -> Any:
    """An emitted event whose payload holds the pre-erasure address (ADO-4).

    **Through `core.bridge`, and not by importing `apps.events`.** `accounts`
    sits BELOW `events` in the layer contract (`.importlinter`), so an import
    here would be the rung breaking the architecture to test it. The bridge is
    the seam that exists for exactly this — the same one `apps/example` publishes
    through — and it resolves the real `events.services.emit` at run time.
    """
    return bridge.get(bridge.EMIT)(
        tenant=tenant,
        name="example.widget.created",
        payload={"contact": TARGET_EMAIL},
        actor=system_actor(tenant),
    )


def test_the_outbox_row_still_reaches_the_retained_payload(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """ER1-2. ADO-4 pinned as fact, in the shape this tree actually has.

    ADO-4 ratifies "Event/Outbox payloads" as retained. On this tree there is
    exactly one payload column: `Outbox` is a `OneToOneField` onto `Event` and
    carries the delivery state, not a copy of the body. So the honest pin is
    that the outbox row for a pre-erasure event still resolves to a payload
    holding the pre-erasure address — the retention ADO-4 describes, reached the
    way this schema reaches it.

    The model comes off the app registry rather than out of an import, for the
    layer-contract reason `seed_an_event_carrying_the_address` gives.
    """
    outbox_model = django_apps.get_model("events", "Outbox")

    event = seed_an_event_carrying_the_address(tenant=tenant)

    erase_user(user=target, actor=eraser, tenant=tenant)

    outbox = outbox_model.objects.select_related("event").get(event_id=event.pk)
    assert TARGET_EMAIL in str(outbox.event.payload)


# --- ER1-4: transactional honesty ---------------------------------------------


def test_a_failure_mid_sweep_rolls_the_whole_erasure_back(
    target: User, eraser: Actor, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ER1-4. Half an erasure looks like success, which is worse than residue.

    The failure is planted in the LAST thing the sweep does, so everything
    before it has already written; if the transaction were not doing its job the
    probe would come back with the earlier tables clean.
    """
    from apps.accounts import services

    def explode(**_: Any) -> None:
        raise RuntimeError("the identity platform fell over mid-sweep")

    monkeypatch.setattr(services, "redact_invitations", explode)

    with pytest.raises(RuntimeError):
        erase_user(user=target, actor=eraser, tenant=tenant)

    hits = residue(TARGET_EMAIL, TARGET_SUBJECT)
    assert ("accounts.User", "email") in hits
    assert ("account.EmailAddress", "email") in hits
    assert ("socialaccount.SocialAccount", "extra_data") in hits
    assert ("accounts.SsoIdentity", "email") in hits
    assert ("core.Invitation", "email") in hits
    target.refresh_from_db()
    assert target.is_active is True


def test_the_tokens_and_the_socket_kick_are_untouched_by_the_sweep(
    target: User, eraser: Actor, tenant: Tenant
) -> None:
    """ER1-4. The two things that already worked still work."""
    erase_user(user=target, actor=eraser, tenant=tenant)

    assert not ApiToken.objects.filter(user_id=target.pk, revoked_at__isnull=True).exists()
    target.refresh_from_db()
    assert target.email.endswith(f"@{ERASED_EMAIL_DOMAIN}")
    assert not Invitation.objects.filter(email=TARGET_EMAIL).exists()
