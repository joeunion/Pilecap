"""Which part of the tenant an event belongs to, and how it got there.

`Event.organization` exists so the realtime fan-out can reach the branch a write
landed in instead of the whole tenant (ADR realtime-2a). Everything that can go
wrong with it is a *wrong* stamp rather than a missing one, because a wrong
stamp survives the fix wearing the fix's clothes: the fan-out narrows, the
narrowing looks like it works, and the rows go to the wrong branch. So the
properties proved here are, in order:

* the stamp is the **row's** organization and never the **actor's hat** — the
  two differ exactly when somebody writes downward into a branch they can see,
  which is the ordinary case in a network and the one a hat-stamped event gets
  wrong;
* an **org-less subject leaves NULL**, and NULL means tenant-wide, which is
  byte-for-byte what every event in this table did before the column existed;
* an id that resolves in **somebody else's tree**, or resolves to nothing at
  all, is **refused** rather than stamped NULL — the narrowing decision fails
  CLOSED, because NULL means tenant-wide and an unresolved
  narrowing that broadcasts is the leak this guards against;
* an **inbound** event is never stamped from a body we did not compose;
* and the **seam** this builds on is in the tree: the envelope the bridge carries
  has the organization on it, so the socket door can narrow on a field it can
  actually see.
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.core.actor import Actor, system_actor
from apps.core.exceptions import Invalid
from apps.core.models import Organization, Tenant
from apps.core.services import create_organization, root_organization
from apps.events import schemas, services
from apps.events.models import Event
from apps.example.events import WIDGET_CREATED
from apps.example.models import Widget
from apps.example.schemas import WidgetOut
from apps.search.events import SEARCH_ENGINE_DEGRADED as ENGINE_DEGRADED

pytestmark = pytest.mark.django_db


@pytest.fixture
def branch(tenant: Tenant, owner_actor: Actor) -> Organization:
    """One node under the root, so "the hat" and "the row" can disagree."""
    return create_organization(
        tenant=tenant,
        parent=root_organization(tenant=tenant),
        name="Branch",
        slug="branch",
        actor=owner_actor,
    )


def _subject(*, tenant: Tenant, owner: Any, organization: Organization) -> dict[str, Any]:
    """An org-scoped row's payload, exactly as its own service would emit it.

    Built from the model and its `Out` schema rather than by calling
    `apps.example.services`: `import-linter` holds the platform apps below the
    domain ones, so this app's tests may not reach up into an app that starts a
    workflow. What the derivation actually reads is the payload — and this is
    that payload, from a real `OrgScopedModel`, byte for byte what `_publish`
    hands to `emit`.
    """
    widget = Widget.objects.create(
        tenant=tenant, organization=organization, owner=owner, name="A widget"
    )
    return dict(WidgetOut.from_orm(widget).model_dump(mode="json"))


# --- The stamp ---------------------------------------------------------------


def test_the_stamp_is_the_rows_organization_and_not_the_actors_hat(
    tenant: Tenant, owner: Any, owner_actor: Actor, branch: Organization
) -> None:
    """The one that catches the plausible wrong fix.

    Stamping `actor.org` would pass every test where the writer sits where the
    row does — which is every flat product and most of the fixtures. It is wrong
    the moment somebody writes *downward*: a manager at the root editing a
    branch's widget would fan the branch's row to the root's subtree group and
    not to the branch's own sockets, and nothing downstream could tell.
    """
    payload = _subject(tenant=tenant, owner=owner, organization=branch)

    # The emit that disagrees: the hat is the root, the row is the branch.
    event = services.emit(name=WIDGET_CREATED, tenant=tenant, payload=payload, actor=owner_actor)

    assert owner_actor.org == root_organization(tenant=tenant)
    assert event.organization == branch


def test_an_org_less_subject_leaves_the_event_tenant_wide(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """NULL is not a gap. It is the answer, and it means what it used to mean.

    A payload with no `organization_id` is an event about something no part of
    the tenant owns in particular. Before this column it went to the whole
    tenant's sockets; NULL is how it keeps doing exactly that.

    **The subject is `search.engine.degraded` and no longer a widget** (R4-F2,
    house rule 59). A widget is an `OrgScopedModel`: it always belongs to a
    branch, so a widget event with no branch on it was never an org-less
    subject — it was a body that had lost its narrowing key, and `emit` now
    refuses one. The engine being down is the real thing nobody's branch owns,
    which is what this test was always about.
    """
    event = services.emit(
        name=ENGINE_DEGRADED,
        tenant=tenant,
        payload={"engine": "meilisearch"},
        actor=owner_actor,
    )

    assert event.organization_id is None


def test_an_organization_from_another_tenant_is_refused_rather_than_broadcast(
    tenant: Tenant, other_tenant: Tenant, owner_actor: Actor
) -> None:
    """The scoped read still refuses the foreign branch — and now says so.

    The read is `for_tenant`, so a foreign id can never stamp another tenant's
    tree. What changed is what happens next: the old answer was
    NULL, and NULL means *tenant-wide*, so a payload naming a branch nobody here
    owns was delivered to every socket in this tenant. Refusing is the closed
    direction, and it matches every other unresolved case in the hierarchy —
    `for_tenant(None)`, `visible_to(None)`, `list_subtree_org_ids(org=None)`.
    """
    theirs = root_organization(tenant=other_tenant)

    with pytest.raises(Invalid) as refusal:
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload={"id": "x", "organization_id": str(theirs.pk)},
            actor=owner_actor,
        )

    assert "organization_id" in refusal.value.errors
    assert not Event.objects.filter(tenant=tenant).exists()


def test_a_malformed_organization_id_is_refused_rather_than_stamped_null(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The inversion, stated: an emit **does** get to raise here, and must.

    This test used to assert the opposite, on the reasoning that an emit sits
    inside somebody's transaction and so may not raise. That reasoning is what
    produced the fail-open: the alternative to raising is not "nothing happens",
    it is "the subject's own row is broadcast to every socket in the tenant".
    Rolling the caller's write back is the cheap outcome; the broadcast is not.
    """
    with pytest.raises(Invalid):
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload={"id": "x", "organization_id": "not-a-uuid"},
            actor=owner_actor,
        )


def test_an_empty_organization_id_is_refused_too(tenant: Tenant, owner_actor: Actor) -> None:
    """Present-and-empty is an unresolved narrowing, not an org-less subject.

    `OrgScopedModel.organization` is a non-nullable FK, so a payload that
    carries the key at all is a payload about an org-scoped row. An empty value
    there means the shape lost its answer somewhere, which is exactly the case
    that must not fall through to tenant-wide. Omitting the key is how an
    org-less subject says so, and the test above proves that still works.
    """
    with pytest.raises(Invalid):
        services.emit(
            name=WIDGET_CREATED,
            tenant=tenant,
            payload={"id": "x", "organization_id": None},
            actor=owner_actor,
        )


def test_an_inbound_event_is_never_stamped_from_a_body_we_did_not_compose(
    tenant: Tenant, branch: Organization
) -> None:
    """`record_event` takes the organization; only `emit` derives one.

    An inbound webhook's body belongs to whoever sent it, and an
    `organization_id` in it names their idea of a row, not our tree. The split
    between the two writers is what makes that structural rather than remembered.
    """
    event = services.record_event(
        tenant=tenant,
        name="stripe.invoice.paid",
        payload={"v": 1, "organization_id": str(branch.pk)},
        actor=system_actor(tenant=tenant),
    )

    assert event.organization_id is None


# --- The seam this narrowing builds on ----------------------------------------


def test_the_envelope_carries_the_organization_the_fan_out_narrows_on(
    tenant: Tenant, owner: Any, owner_actor: Actor, branch: Organization
) -> None:
    """The org is on the wire, in the one serialisation both doors are handed.

    This is the seam, in code rather than in prose: `schemas.envelope` is what
    the push activity hands across `core.bridge`, so the socket side can read
    the branch off the same body a webhook subscriber is signed and sent. A
    consumer cannot narrow on a field that never left this app.
    """
    payload = _subject(tenant=tenant, owner=owner, organization=branch)
    event = services.emit(name=WIDGET_CREATED, tenant=tenant, payload=payload, actor=owner_actor)

    body = schemas.envelope(event)

    assert body["organization_id"] == str(branch.pk)


def test_the_envelope_says_null_for_a_tenant_wide_event(tenant: Tenant, owner_actor: Actor) -> None:
    """None-tolerant, on the wire as well as in the column.

    The key is present and null rather than absent, so the reader on the other
    side branches on a value instead of on whether a key exists.

    The subject is the declared org-less name for the sibling test's reason
    (R4-F2): a widget always belongs to a branch, so it can no longer stand in
    for a thing no branch owns.
    """
    event = services.emit(
        name=ENGINE_DEGRADED,
        tenant=tenant,
        payload={"engine": "meilisearch"},
        actor=owner_actor,
    )

    body = schemas.envelope(event)

    assert "organization_id" in body
    assert body["organization_id"] is None
