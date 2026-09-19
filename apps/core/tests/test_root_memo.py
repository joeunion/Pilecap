"""The tenant root is resolved ONCE, and this is the drive for it.

`core.services.root_organization` was read on a hot path that nothing bounded:
the tenant-wide READS in `events` and `connections` asked it on every call, and
`emit()` -> `enqueue_dispatch` -> `get_event` therefore asked it inside the
caller's transaction on every emitting write, in every app that emits from
`services.py`. The cost was N reads per request where N is the number of events
emitted, and nothing bounded N: a write that emitted three times paid three.

**Two things happened to that path and the cases below hold both.** The memo
took it to ONE per request. Then PR5.5 answered the register question — sight is
the acting hat's, configuration is the root's — and the READ sites stopped
resolving a node at all, so the emit path's number is now ZERO and the three
equalities that measure it say so. What still asks for a root is every WRITE,
in six apps, and that is what the contract clauses below are driven through.

**What this module measures, and what it deliberately does not.** It measures
the NUMBER of root reads, by capturing the statements and matching the one
statement the root read is (`ROOT_READ` below). It has no opinion about which
node a tenant-wide read should ask at: the memo was right under either answer,
and it is still right under the one that landed, because it changes how often a
node is resolved and never which node a question is about.

The contract the memo makes — source of truth, key, lifetime, invalidation,
failure — is declared on the carrier, `core.models.Tenant`, beside the slot,
the way the permission memo's is declared on `core.actor.Actor`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from django.db import connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext

from apps.core.exceptions import Conflict
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import create_organization, root_organization

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.accounts.models import User
    from apps.core.actor import Actor

pytestmark = pytest.mark.django_db

#: The one statement the memo exists to stop repeating, matched on its shape
#: rather than counted by subtraction: a total that moves for another reason
#: would otherwise read as a root read appearing or disappearing.
#:
#:     SELECT ... FROM "core_organization"
#:     WHERE ("core_organization"."tenant_id" = %s
#:            AND "core_organization"."parent_id" IS NULL)
#:     ORDER BY "core_organization"."path" ASC LIMIT 1
ROOT_READ = re.compile(r'FROM "core_organization".+"parent_id" IS NULL', re.DOTALL)


def _root_reads(captured: CaptureQueriesContext) -> list[str]:
    """Every captured statement that is the root read, in order."""
    return [entry["sql"] for entry in captured.captured_queries if ROOT_READ.search(entry["sql"])]


# --- 1 · the cost that had no ceiling ----------------------------------------


def test_three_emits_in_one_transaction_read_the_root_once(
    tenant: Tenant, root_org: Organization, owner_actor: Actor, recorded_workflow_starts: None
) -> None:
    """**RT.2, and the number is ZERO since PR5.5.** N emits, no root read.

    Three `emit()` calls in one transaction is the shape a service with more
    than one thing to say already has, and it is the smallest world in which
    "per call" and "per request" gave different numbers. The history is the
    point of keeping it: three root reads on the tree this was written against
    (one per `emit`, each issued by `events.selectors.get_event` under
    `enqueue_dispatch`, inside the caller's transaction), ONE after the memo
    landed, and NONE now that a read of a tenant-wide kind asks at the acting
    hat and resolves no node at all (the universal-homing proposal,
    2026-09-17 — every record homed at a node — is where that decision and its
    v2.2 successor live).

    **The equality is still an equality, and it still binds.** Zero is the
    strongest form this assertion has ever had: a regression that put ONE back
    fails here, which is exactly what it should do — the emit path has no
    business resolving a root any more, and the memo's own property is asserted
    beside this by the clause tests, over the WRITE sites that still ask for
    one.
    """
    from apps.events.services import emit

    payload = {"organization_id": str(root_org.pk)}
    # The `root_org` fixture above already asked, on this same instance. A
    # measurement of what a request pays must start where a request starts —
    # with nothing remembered — so the memo is emptied through its one
    # invalidation rather than by reaching into the slot.
    tenant.forget_root()

    with CaptureQueriesContext(connection) as captured, transaction.atomic():
        for _ in range(3):
            emit(
                name="example.widget.created",
                tenant=tenant,
                payload=dict(payload),
                actor=owner_actor,
            )

    assert _root_reads(captured) == [], _root_reads(captured)


def test_a_door_that_lists_endpoints_then_reads_an_event_pays_one_root_read(
    api: Client,
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> None:
    """**RT.2's sibling, and it is ZERO since PR5.5.** Two tenant-wide reads, no
    root read.

    Driven through the two `events` selectors rather than over the wire, because
    the claim is about what those two reads cost and a door request would add
    its own middleware resolution to the count — which is the subject of the
    test below, not of this one.

    The history, kept because the number is the whole point: two root reads on
    the tree this was written against (one per selector, since `_tenant_root`
    held no memo), ONE once the memo landed, and NONE now that sight is the
    acting hat's — the selectors ask `endpoint.read` and `event.read` with no
    node and with the row, and neither resolves an organization.

    *Absent:* one root read, which is what a read path that started resolving
    the root again would cost, and this equality is what refuses it.
    """
    from apps.events.selectors import get_event, list_endpoints
    from apps.events.services import emit

    with transaction.atomic():
        event = emit(
            name="example.widget.created",
            tenant=tenant,
            payload={"organization_id": str(root_org.pk)},
            actor=owner_actor,
        )
    tenant.forget_root()

    with CaptureQueriesContext(connection) as captured:
        list(list_endpoints(tenant=tenant, actor=owner_actor))
        get_event(tenant=tenant, event_id=event.pk, actor=owner_actor)

    assert _root_reads(captured) == [], _root_reads(captured)


# --- 2 · the contract, clause by clause --------------------------------------


def test_two_tenants_never_share_a_memo(
    tenant: Tenant, other_tenant: Tenant, root_org: Organization, other_root_org: Organization
) -> None:
    """**The key clause.** The tenant is the key AND the carrier.

    A memo held on the tenant instance cannot be reached from another tenant's,
    so the cross-tenant confusion an actor memo needs an identity gate to refuse
    (`core.authz._memo_box`) cannot be expressed here at all. Asserted rather
    than assumed, because "it cannot happen" is the claim that goes stale.

    *Absent:* a process-wide dict keyed by nothing would answer the second
    tenant with the first tenant's root.
    """
    tenant.forget_root()
    other_tenant.forget_root()

    assert root_organization(tenant=tenant) == root_org
    assert root_organization(tenant=other_tenant) == other_root_org
    assert root_org != other_root_org


def test_a_second_instance_of_one_tenant_starts_cold(tenant: Tenant) -> None:
    """**The lifetime clause.** The memo is the instance's, never the row's.

    Two `Tenant` objects for one row are two requests as far as this memo is
    concerned — which is what "one request, one activity, one command" means
    when the carrier is a model instance. A memo that survived a re-fetch would
    be a process cache wearing a request's name.

    *Absent:* a class attribute assigned rather than an instance one would make
    the second instance answer from the first's memo, and both from a box every
    tenant in the process shares.
    """
    warm = root_organization(tenant=tenant)
    cold = Tenant.objects.get(pk=tenant.pk)

    with CaptureQueriesContext(connection) as captured:
        assert root_organization(tenant=cold) == warm
    assert len(_root_reads(captured)) == 1, _root_reads(captured)


def test_forget_root_is_the_one_invalidation(tenant: Tenant) -> None:
    """**The invalidation clause.** One way to empty it, and it is a method.

    *Absent:* nothing empties the memo, so a test measuring a cold read has to
    build a second instance to get one.
    """
    root_organization(tenant=tenant)
    with CaptureQueriesContext(connection) as warm:
        root_organization(tenant=tenant)
    assert _root_reads(warm) == []

    tenant.forget_root()
    with CaptureQueriesContext(connection) as cold:
        root_organization(tenant=tenant)
    assert len(_root_reads(cold)) == 1, _root_reads(cold)


def test_a_tenant_with_no_root_remembers_nothing(db: None) -> None:
    """**The failure clause.** A broken database is never memoised.

    `root_organization` raises rather than answering `None`, and the raise must
    leave the memo empty: remembering a failure would turn one broken row into
    an answer every later call in the request agreed with.

    The victim is built here rather than found — a tenant written around the
    service, which is the only way to have one without a root.

    *Absent:* a memo filled before the `None` check would hold `None` and the
    second call would return it instead of raising.
    """
    orphan = Tenant.objects.create(name="Rootless", slug="rootless")

    for _ in range(2):
        with pytest.raises(Conflict):
            root_organization(tenant=orphan)

    with CaptureQueriesContext(connection) as captured:
        with pytest.raises(Conflict):
            root_organization(tenant=orphan)
    assert len(_root_reads(captured)) == 1, "a failure is re-asked, never remembered"


# --- 3 · the fill from the site that already holds it -------------------------


def test_the_hat_the_door_resolved_fills_the_memo(
    tenant: Tenant, root_org: Organization, owner: User
) -> None:
    """**RT.1.** The root passed down from the one site that already holds it.

    `core.middleware.resolve_org` reads the acting hat on every request at every
    door. When that hat IS the root — which is every request in a flat product
    and every request an administrator makes in a networked one — the row is
    already in hand and the memo is filled from it, so the request's first
    tenant-wide read costs nothing at all.

    *Absent:* the hat is resolved and thrown away, and the first root-asking
    of the request reads the same row a second time.
    """
    from apps.core.middleware import resolve_org

    tenant.forget_root()
    hat = resolve_org(user=owner, tenant=tenant, requested_slug=root_org.slug)
    assert hat == root_org

    with CaptureQueriesContext(connection) as captured:
        assert root_organization(tenant=tenant) == root_org
    assert _root_reads(captured) == []


def test_a_branch_hat_fills_nothing(
    tenant: Tenant, root_org: Organization, owner: User, owner_actor: Actor
) -> None:
    """**The negative.** Only a root fills the root memo.

    A hat one level down is not the tenant's root, and a fill that took the
    caller's word for it would answer every tenant-wide read of that request
    with a branch — which is the failure the whole register question is about.
    The test is `parent is None` and the reason it is sufficient is the database
    constraint `organization_one_root_per_tenant`: at most one row per tenant
    can satisfy it.

    *Absent:* a fill that trusted its argument would memoise the branch.
    """
    from apps.core.middleware import resolve_org

    branch = create_organization(
        tenant=tenant, parent=root_org, name="Branch", slug="branch", actor=owner_actor
    )
    Membership.objects.filter(tenant=tenant, user=owner).update(organization=branch)
    tenant.forget_root()

    hat = resolve_org(user=owner, tenant=tenant, requested_slug=branch.slug)
    assert hat == branch

    with CaptureQueriesContext(connection) as captured:
        assert root_organization(tenant=tenant) == root_org
    assert len(_root_reads(captured)) == 1, "a branch must not answer for the root"


def test_the_memo_answers_every_site_because_it_is_inside_the_one_function(
    tenant: Tenant, root_org: Organization, owner_actor: Actor
) -> None:
    """**RT.1.** One resolution, and no registry of call sites to keep.

    The memo is inside `core.services.root_organization` itself, so every
    caller — every `require(..., root_organization(tenant=...))` site in the
    write paths of six apps — reads it without being edited, and a site added
    tomorrow is memoised the day it is written. This asserts the property those
    call sites rely on rather than listing them: one read for the first ask,
    none for any ask after it.

    **The two `_tenant_root` helpers this used to be driven through are gone**
    (PR5.5): the reads of tenant-wide kinds in `events` and `connections` ask at
    the acting hat now and resolve no root at all, so the helper that used to
    stand in for "a second caller" is no longer one. The write sites are, and
    the property is `root_organization`'s own — asked three times here, through
    the function every one of those sites calls unchanged. The registry of sites
    is derived by grep, not kept here: a list in a test is the thing that goes
    stale, and this one just did.
    """
    tenant.forget_root()
    with CaptureQueriesContext(connection) as captured:
        assert root_organization(tenant=tenant) == root_org
        assert root_organization(tenant=tenant) == root_org
        assert root_organization(tenant=tenant) == root_org
    assert len(_root_reads(captured)) == 1, _root_reads(captured)


def test_the_slot_is_never_shared_by_the_class(tenant: Tenant, other_tenant: Tenant) -> None:
    """**The lifetime clause, at the mechanism.** An instance attribute, always.

    The hazard a scalar default exists to refuse: a mutable class attribute
    (`_root: dict = {}`) would be ONE box for every tenant in the process, and
    `forget_root()` on one tenant would empty everybody's. The class default is
    `None` and every fill is an assignment onto the instance, so the class
    itself never learns anything.

    *Absent:* a class-level mutable default makes this fail on the second
    assertion.
    """
    root_organization(tenant=tenant)
    root_organization(tenant=other_tenant)

    assert Tenant._root_organization is None, "the class itself remembers nothing"
    assert tenant._root_organization is not None
    assert other_tenant._root_organization is not None
    assert tenant._root_organization != other_tenant._root_organization


def test_the_contract_is_declared_on_the_carrier() -> None:
    """**Principle 10.** A cache says what it is, where the slot is.

    The permission memo's contract is written on `Actor._permission_rows`; this
    one is written on `Tenant`, in the same five clauses, so a reader who found
    one finds the other in the same place. Asserted so that a slot can never
    arrive without them.
    """
    import inspect

    source = inspect.getsource(Tenant)
    for clause in ("Source of truth", "Key", "TTL", "Invalidation", "Failure"):
        assert clause in source, f"the root memo's contract does not state: {clause}"
