"""LF1-3: `redact_invitations` — erasure's fourth residue table gets a seam.

Criterion LF1-3 of rung LF-1, carrying ADR ident-5's residue census. The
absent-answer names the failure precisely: without this service, `accounts`
would have to reach into `core`'s `Invitation` rows to finish an erasure — a
door writing another app's model, which is C3 and house rule 10 in one move —
or leave the address behind, which is the residue the whole wave exists to
close.

The three properties the criterion asks for:

* every invitation holding the address is redacted, **across tenants**;
* another address's invitations are untouched;
* the write is `@service` and audited (action + door — G3).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from apps.core.actor import Actor, system_actor
from apps.core.audit import AuditEntry
from apps.core.log import REDACTED
from apps.core.models import Invitation, Tenant, is_org_scoped
from apps.core.services import (
    REDACTED_EMAIL_DOMAIN,
    invite_member,
    redact_invitations,
)

pytestmark = pytest.mark.django_db

TARGET = "leaver@example.com"
BYSTANDER = "stays@example.com"


def _invite(tenant: Tenant, email: str) -> Invitation:
    invitation, _token = invite_member(
        tenant=tenant, email=email, actor=system_actor(tenant=tenant)
    )
    return invitation


# --- the sweep ---------------------------------------------------------------


def test_a_pending_invitation_is_voided_and_redacted(tenant: Tenant, owner_actor: Actor) -> None:
    invitation = _invite(tenant, TARGET)

    redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.REVOKED
    assert invitation.email.endswith(f"@{REDACTED_EMAIL_DOMAIN}")
    assert TARGET not in invitation.email


def test_the_sweep_crosses_tenants(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """**The whole point.** Nobody knows which tenants hold an offer to an address.

    An invitation to somebody with no account is precisely a row in a tenant
    the person has no membership in — so a tenant-scoped sweep would miss every
    row that matters. `for_tenant` has nothing to be given here, and the rule-8
    override at the call site says exactly that (spelled without the marker,
    which the gate greps for and would otherwise count twice).
    """
    here = _invite(tenant, TARGET)
    there = _invite(other_tenant, TARGET)

    swept = redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    assert swept.count == 2
    assert swept.label == Invitation._meta.label, "the population, not an object"
    # Read back from the database rather than from the return value: since ADR
    # core-22's L6 ruling this sweep hands back a population and not its
    # victims, and what landed is the stronger claim anyway.
    assert {row.pk for row in Invitation.objects.filter(status=Invitation.Status.REVOKED)} == {
        here.pk,
        there.pk,
    }
    for row in (here, there):
        row.refresh_from_db()
        assert row.status == Invitation.Status.REVOKED
        assert TARGET not in row.email


def test_another_address_is_untouched(tenant: Tenant, owner_actor: Actor) -> None:
    bystander = _invite(tenant, BYSTANDER)

    redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    bystander.refresh_from_db()
    assert bystander.email == BYSTANDER
    assert bystander.status == Invitation.Status.PENDING


def test_the_address_is_normalised_before_it_is_matched(tenant: Tenant, owner_actor: Actor) -> None:
    """`invite_member` lowercases; an erasure asked in mixed case still lands."""
    invitation = _invite(tenant, TARGET)

    redact_invitations(email=f"  {TARGET.upper()}  ", actor=owner_actor, tenant=tenant)

    invitation.refresh_from_db()
    assert TARGET not in invitation.email


def test_each_redacted_address_is_unique(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """A shared sentinel silently GROUPS rows that have nothing to do with each
    other — `erase_user`'s reason for `erased+<uuid7>@…`, one table over."""
    _invite(tenant, TARGET)
    _invite(other_tenant, TARGET)

    swept = redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    assert swept.count == 2
    addresses = set(
        Invitation.objects.filter(email__endswith=REDACTED_EMAIL_DOMAIN).values_list(
            "email", flat=True
        )
    )
    assert len(addresses) == 2, "a distinct redacted address per row"


def test_a_non_pending_invitation_keeps_its_status_and_loses_its_address(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Voiding and redacting are two acts, and only one applies to history.

    An accepted or revoked invitation is the record that an offer was made and
    what became of it. That fact stays; the person does not.
    """
    invitation = _invite(tenant, TARGET)
    Invitation.objects.filter(pk=invitation.pk).update(status=Invitation.Status.ACCEPTED)

    redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    invitation.refresh_from_db()
    assert invitation.status == Invitation.Status.ACCEPTED
    assert TARGET not in invitation.email


def test_an_address_nobody_was_invited_at_is_a_quiet_no_op(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Erasure runs for everybody, and most people were never invited anywhere."""
    swept = redact_invitations(email="nobody@example.com", actor=owner_actor, tenant=tenant)
    assert swept.count == 0


def test_an_empty_address_sweeps_nothing(tenant: Tenant, owner_actor: Actor) -> None:
    """The one input that would otherwise match every row with a blank email."""
    _invite(tenant, TARGET)
    assert redact_invitations(email="   ", actor=owner_actor, tenant=tenant).count == 0
    assert Invitation.objects.for_tenant(tenant).filter(email=TARGET).exists()


# --- the audit row (G3) ------------------------------------------------------


def test_the_sweep_is_audited_with_its_action_and_its_door(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """G3: action + door, in the tenant the erasure was performed in."""
    _invite(tenant, TARGET)

    redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    row = AuditEntry.objects.for_tenant(tenant).filter(action="core.redact_invitations").first()
    assert row is not None
    assert row.outcome == AuditEntry.Outcome.OK
    assert row.actor_user_id == owner_actor.user_id


def test_a_sweep_with_no_tenant_lands_in_the_platform_trail(owner_actor: Actor) -> None:
    """ADR core-8's declared null population — `erase_user`'s own shape.

    `tenant` is an audit-population selector here and not a filter: the sweep
    is platform-wide either way. Passing nothing says "the deployment did
    this", and the row is readable through `for_platform()` and through no
    tenant's ledger.
    """
    redact_invitations(email=TARGET, actor=owner_actor, tenant=None)

    assert AuditEntry.objects.for_platform().filter(action="core.redact_invitations").exists()


def test_the_address_never_reaches_the_audit_input(tenant: Tenant, owner_actor: Actor) -> None:
    """An email address is a person, so it is not in core's `LOG_KEYS`.

    A redaction service that wrote the address it was erasing into the trail it
    writes would have moved the residue rather than removed it.
    """
    _invite(tenant, TARGET)
    redact_invitations(email=TARGET, actor=owner_actor, tenant=tenant)

    row = AuditEntry.objects.for_tenant(tenant).filter(action="core.redact_invitations").first()
    assert row is not None
    assert row.input["email"] == REDACTED


# --- the shape the rules read ------------------------------------------------


def test_no_uncounted_reach_valve_stands_on_the_email() -> None:
    """No `# reach:` on the `str` reference: rule 26 counts none there, so it is a comment."""
    source = inspect.getsource(redact_invitations)
    assert "# reach:" not in source

    # The two properties rule 26's population test reduces to, read off the
    # model registry and the signature rather than out of the engine (importing
    # `quality` from a test would drag the whole engine into mypy's strict
    # graph). The first holds since ADR core-20; the second is why the counter
    # still never sees this service.
    assert is_org_scoped(Invitation)
    parameters = inspect.signature(redact_invitations).parameters
    assert "organization" not in parameters
    # Compared as a STRING: this module has `from __future__ import
    # annotations`, so every annotation reaches `inspect` unevaluated.
    assert parameters["email"].annotation == "str"


def test_the_service_authorizes_or_says_why_not() -> None:
    """Rule 13's other half: it takes an actor, so it owes an answer."""
    source = inspect.getsource(redact_invitations)
    assert "# authz:" in source


def test_the_redacted_domain_matches_the_one_accounts_uses() -> None:
    """The repeat is deliberate (`core` may not import `accounts`); pin the pair.

    `apps.core.services.RESERVED_TENANT_SLUGS` is pinned to
    `apps.workflows.services.PLATFORM_SEGMENT` the same way and for the same
    reason: a constant repeated across a layer boundary drifts unless something
    holds the two together.
    """
    from apps.accounts.services import ERASED_EMAIL_DOMAIN

    assert REDACTED_EMAIL_DOMAIN == ERASED_EMAIL_DOMAIN


def test_the_signature_is_keyword_only_and_carries_the_audit_selector() -> None:
    """The lexicon delta, pinned: `tenant` was added to the ratified signature."""
    parameters = inspect.signature(redact_invitations).parameters
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters.values()
    )
    assert set(parameters) == {"email", "actor", "tenant"}


def test_the_docstring_declares_the_alias_blind_spot() -> None:
    """A declared blind spot goes in the docstring, not in silence."""
    doc: Any = redact_invitations.__doc__
    assert "alias" in doc
