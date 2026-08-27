"""The audited population records WHO — as a class, not one service at a time.

ADR core-22 read AU-3's "identity of associated individuals" onto
`actor_user` / `actor_token` / `actor_kind`, and `write_audit` takes all three
from the `actor` a service was given and **from nowhere else**. AUDIT-2 closed
that for the two token doors. AUDIT-2c's L1 and L10 rulings closed it for the
population: **every audited service takes a required, never-defaulted `actor`
and a required, never-defaulted `tenant`.**

The census below is DERIVED from the decorator's own rule for who writes a row
(`core.service._declares_tenant` — the signature, never a list somebody keeps),
so a service added next week is in it the day it is written. That is the whole
difference between this and the prose roll-call in `_declares_tenant`'s
docstring, which said of itself: *"the list is prose and nothing checks it,
which is exactly how it went stale."*

**Why a default is worse than an absence.** The decorator reads the audited
population off the DECLARATION and writes the row from the CALL. A defaulted
parameter is therefore a service that looks attributed and files every row
under nobody the moment one caller leaves it out — which is exactly how
`accounts.sync_workforce_identity_config` went unaudited under ADR core-8, and
the reason that lesson is now a checked standard rather than a paragraph.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Any

import pytest
from django.apps import apps as django_apps

import apps as apps_package
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.audit import AuditEntry
from apps.core.exceptions import Forbidden
from apps.core.models import Membership, Organization, Tenant
from apps.core.service import _declares_tenant
from apps.core.services import add_membership, revoke_membership, set_role

pytestmark = pytest.mark.django_db


def _emitters() -> list[tuple[str, Any]]:
    """Every audit emitter in the tree, derived off the decorator's own rule.

    An emitter is a `@service` whose signature DECLARES a keyword-only
    `tenant` — `core.service._declares_tenant`, which is what actually decides
    whether a row is written. Reading the same predicate the decorator reads is
    what keeps this census from becoming a second opinion about the population.
    """
    found: list[tuple[str, Any]] = []
    for module in pkgutil.iter_modules(apps_package.__path__):
        name = f"apps.{module.name}.services"
        try:
            services = importlib.import_module(name)
        except ModuleNotFoundError:
            continue
        for attribute, value in vars(services).items():
            wrapped = getattr(value, "__wrapped__", None)
            if wrapped is None or getattr(wrapped, "__module__", None) != name:
                continue
            if _declares_tenant(wrapped):
                found.append((f"{module.name}.{attribute}", wrapped))
    return sorted(found)


def _offenders(parameter: str) -> list[str]:
    out = []
    for action, fn in _emitters():
        params = inspect.signature(fn).parameters
        if parameter not in params:
            out.append(f"{action}: no {parameter} at all")
        elif params[parameter].default is not inspect.Parameter.empty:
            out.append(f"{action}: {parameter} is DEFAULTED")
    return out


def test_the_census_is_not_empty() -> None:
    """The anti-vacuous guard: a census that found nothing proves nothing."""
    assert len(_emitters()) > 50, "the emitter census is reading the wrong thing"


#: The emitters that take NO actor, and the reason they are legal: ADR
#: core-22's absence (ii) — a service called from an activity, a schedule or a
#: circuit breaker records `kind=system` with no person, because the human
#: cause is upstream at the door that started the run and is REACHABLE through
#: the causation chain rather than restated on every row. Every member carries
#: a `# authz:` valve at its own site saying the same thing in its own words.
#:
#: **It is a closed list on purpose.** An emitter that arrives without an actor
#: and without a line here fails the census below — which is the difference
#: between an enumerated absence and a habit.
MACHINE_WORK: frozenset[str] = frozenset(
    {
        # the dispatch workflow's own activities
        "events.enqueue_dispatch",
        "events.close_outbox",
        "events.record_delivery_attempt",
        "events.dead_letter_delivery",
        # deployment housekeeping, run by a schedule
        "events.purge_deliveries",
        "exports.purge_exports",
        "files.purge_pending_versions",
        "connections.purge_inbound_webhooks",
        # platform bookkeeping written by the workflow client
        "workflows.record_run",
        "workflows.finish_run",
        # the login flow: an identity provider asserted an identity, and
        # `ensure_membership`'s own docstring argues the case at length
        "accounts.ensure_membership",
        # the search circuit breaker reporting on itself (absence vii)
        "search.announce_degraded",
        "search.announce_recovered",
    }
)


def test_no_audit_emitter_DEFAULTS_its_actor() -> None:
    """The class standard, and the one a default is measured against.

    Absence and default are not the same failure. An emitter with no `actor` at
    all is making a claim — nobody asked for this — which `MACHINE_WORK` below
    holds it to. An emitter with a DEFAULTED actor is making no claim at all:
    it looks attributed and files under nobody the moment one caller leaves the
    argument out, and nothing anywhere says which callers did. That is how
    `sync_workforce_identity_config` went unaudited under ADR core-8, and L1
    is that lesson applied to the row's other half.
    """
    defaulted = [line for line in _offenders("actor") if "DEFAULTED" in line]
    assert defaulted == []


def test_the_actor_less_population_is_exactly_the_declared_machine_work() -> None:
    """L1's other half: the absence is ENUMERATED, so it cannot spread quietly.

    Both directions. A new emitter that takes no actor fails until somebody
    writes down why; a name that stops being actor-less has to leave the list,
    so the list cannot outlive its own reasons.
    """
    actual = {line.split(":")[0] for line in _offenders("actor") if "no actor" in line}

    assert actual - MACHINE_WORK == set(), (
        "an audit emitter takes no actor and no line says why (ADR core-22, absence ii)"
    )
    assert MACHINE_WORK - actual == set(), (
        "MACHINE_WORK names an emitter that now takes an actor — take it off the list"
    )


def test_every_audit_emitter_takes_a_required_tenant() -> None:
    """L10. `Tenant | None` is legal; a DEFAULT is not.

    A nullable tenant is a real and declared population — the deployment's own
    actions (ADR core-8 (b)) — and several services legitimately have one. What
    is refused here is the *default*, because that is the shape where a caller
    can silently opt a row out of the workspace it belongs to.
    """
    assert _offenders("tenant") == []


# --- the wall, re-keyed: red BOTH ways --------------------------------------


@pytest.fixture
def branch(tenant: Tenant, root_org: Organization) -> Organization:
    from apps.core.services import create_organization

    return create_organization(
        tenant=tenant,
        name="Branch",
        slug="branch",
        parent=root_org,
        actor=system_actor(tenant=tenant),
    )


def _admin(tenant: Tenant, org: Organization, email: str) -> Actor:
    from apps.accounts.services import create_user

    person = create_user(email=email, password="x" * 14)
    add_membership(
        user=person,
        tenant=tenant,
        organization=org,
        role=Membership.Role.ADMIN,
        actor=system_actor(tenant=tenant),
    )
    return actor_for(user=person, tenant=tenant, org=org)


def test_a_human_above_their_ceiling_is_still_refused(
    tenant: Tenant, root_org: Organization
) -> None:
    """Half one of the re-keying: the wall did not get weaker.

    An `admin` granting `owner` is the case the escalation wall exists for, and
    it must answer exactly as it did before `kind` became the key. If this ever
    goes green because a system actor slipped past, the wall has been replaced
    by a hole in the shape of a missing argument — which is the shape ADR
    core-22's L1 ruling took away.
    """
    from apps.accounts.services import create_user

    acting = _admin(tenant, root_org, "wall-admin@example.com")
    newcomer = create_user(email="wall-newcomer@example.com", password="x" * 14)

    with pytest.raises(Forbidden, match="nobody grants above themselves"):
        add_membership(
            user=newcomer,
            tenant=tenant,
            organization=root_org,
            role=Membership.Role.OWNER,
            actor=acting,
        )


def test_a_system_actor_passes_the_wall_and_the_row_says_system(
    tenant: Tenant, root_org: Organization
) -> None:
    """Half two: the altitude is DECLARED, and the trail records the altitude.

    This is the whole substance of the re-keying. The product configuring
    itself — a seed, an invitation accepted at signup, a management command —
    has no ceiling to measure, and the old wall let it through because
    `actor.user` happened to be `None`. That is an exemption: it leaves no
    trace, and a caller who simply forgot the argument got the same silence.

    Keyed on `kind` it is an **altitude**: the grant goes through, and the audit
    row says `actor_kind=system` with no person — a reviewer can tell it from a
    human grant at a glance, which is the difference between a trail and a
    trail with a hole in it.
    """
    from apps.accounts.services import create_user

    newcomer = create_user(email="altitude@example.com", password="x" * 14)

    membership = add_membership(
        user=newcomer,
        tenant=tenant,
        organization=root_org,
        role=Membership.Role.OWNER,
        actor=system_actor(tenant=tenant),
    )

    assert membership.role == Membership.Role.OWNER, "the altitude passes the wall"
    row = (
        AuditEntry.objects.for_tenant(tenant)
        .filter(action="core.add_membership")
        .latest("created_at")
    )
    assert row.actor_kind == AuditEntry.Kind.SYSTEM, "and the row NAMES the altitude"
    assert row.actor_user_id is None
    assert row.object_id == membership.pk


def test_an_unauthenticated_human_actor_is_refused_rather_than_waved_through(
    tenant: Tenant, root_org: Organization
) -> None:
    """The third case the old `granter is None` swallowed.

    `human` with no user is nobody authenticated. Under the old key it reached
    the wall as `None` and passed; under the new one it is refused, because
    there is no ceiling to measure and no reason to believe the grant is
    legitimate. This is the tightening the re-keying pays for, said out loud.
    """
    from apps.accounts.services import create_user

    newcomer = create_user(email="anonymous-grant@example.com", password="x" * 14)

    with pytest.raises(Forbidden, match="resolved nobody"):
        add_membership(
            user=newcomer,
            tenant=tenant,
            organization=root_org,
            role=Membership.Role.MEMBER,
            actor=actor_for(user=None, tenant=tenant, org=root_org),
        )


# --- L5: the death names what died ------------------------------------------


def test_a_revoked_membership_is_named_by_the_row_that_records_it(
    tenant: Tenant, root_org: Organization
) -> None:
    """L5. A death is exactly what an audit trail exists for.

    `revoke_membership` returned `None` until AUDIT-2c, so the row recording
    the most consequential act in the hierarchy named no object at all: "whose
    hat did you take, and which one was it" was answerable only from a redacted
    `input`. The typed result names the dead row's own pk — still the honest
    answer to "what did this act on", because nothing points at it any more and
    that IS the fact.
    """
    from apps.accounts.services import create_user

    person = create_user(email="doomed@example.com", password="x" * 14)
    membership = add_membership(
        user=person,
        tenant=tenant,
        organization=root_org,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    dead_pk = membership.pk
    acting = _admin(tenant, root_org, "revoker@example.com")

    died = revoke_membership(tenant=tenant, membership=membership, actor=acting)

    assert died.membership_id == dead_pk
    assert died.user_id == person.pk
    assert died.role == Membership.Role.MEMBER
    assert not Membership.objects.filter(pk=dead_pk).exists()

    row = AuditEntry.objects.for_tenant(tenant).filter(action="core.revoke_membership").get()
    assert row.object_type == Membership._meta.label
    assert row.object_id == dead_pk, "the trail names the hat it took"
    assert row.actor_user_id == acting.user_id if acting.user else None


def test_setting_a_role_still_records_the_person_who_set_it(
    tenant: Tenant, root_org: Organization
) -> None:
    """The sibling road, so the pair cannot drift, one level up."""
    from apps.accounts.services import create_user

    person = create_user(email="promotable@example.com", password="x" * 14)
    membership = add_membership(
        user=person,
        tenant=tenant,
        organization=root_org,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    acting = _admin(tenant, root_org, "promoter@example.com")

    set_role(tenant=tenant, membership=membership, role=Membership.Role.ADMIN, actor=acting)

    row = AuditEntry.objects.for_tenant(tenant).filter(action="core.set_role").get()
    assert row.actor_kind == AuditEntry.Kind.HUMAN
    assert row.actor_user_id == acting.user_id
    assert row.object_id == membership.pk


# --- L6: a sweep files under a population, never under a victim --------------


def test_a_sweep_files_under_the_population_it_walked(tenant: Tenant, owner: Any) -> None:
    """L6. The swept model's label, a NULL id, and a count that is not a guess.

    A row naming one arbitrary victim out of nine hundred would be worse than a
    row naming none: it reads as a single deletion somebody could go and look
    up. The population shape says what actually happened.
    """
    from apps.core.services import invite_member, redact_invitations

    invite_member(
        tenant=tenant,
        email="sweep-me@example.com",
        actor=system_actor(tenant=tenant),
    )

    swept = redact_invitations(
        email="sweep-me@example.com", actor=system_actor(tenant=tenant), tenant=None
    )

    assert swept.count == 1
    assert swept.label == "core.Invitation"
    assert django_apps.get_model(swept.label) is not None, "a resolvable lazy reference"

    row = AuditEntry.objects.for_platform().filter(action="core.redact_invitations").get()
    assert row.object_type == "core.Invitation"
    assert row.object_id is None, "a population has no single id, and says so"
