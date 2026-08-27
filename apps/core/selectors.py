"""Reads over the tenancy and hierarchy rows — composition both doors share.

House rule 12: nothing here writes, and nothing here returns a wire shape. A
selector hands back a queryset or a row, and `api/routes.py` and `mcp.py` turn
it into schemas — which is what lets the two doors answer with the same rows by
construction rather than by two functions agreeing.

**Why the narrowing is written out here rather than through `visible_to`.**
`ScopedQuerySet.visible_to` filters on an `organization` foreign key, and the
three models below do not have one in the shape it expects:

* `Organization` **is** the node — it has no `organization` column, and
  `visible_to` raises `TypeError` on it by design. Its subtree read is the same
  indexed prefix scan `visible_to` performs, expressed on the row's own `path`.
* `Membership` is person × tenant × org × role and inherits `BaseModel`, not
  `TenantScopedModel`, so it carries no scoped manager at all. Its reads name
  the tenant explicitly and narrow by the hat's subtree through the related
  organization's path.
`Invitation` is the exception that proves the paragraph: it **is** org-scoped
since ADR core-20 — it records the node it was sent from — so its two reads go
through `visible_to` like any other org-scoped read, with no prefix scan written
out here at all.

Every one of them **fails closed on an unresolved hat**, the same way
`for_tenant(None)` and `visible_to(None)` do: no hat reads an empty table, never
the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q, QuerySet

from apps.core.exceptions import NotFound
from apps.core.models import PATH_SEPARATOR, Invitation, Membership, Organization, Tenant

if TYPE_CHECKING:  # pragma: no cover - typing only
    from apps.core.models import ScopedQuerySet


def _subtree(org: Organization | None) -> Q:
    """Everything at or below `org`, as a `Q` over an organization `path`.

    One indexed `LIKE 'prefix.%'` plus an equality, which is exactly what
    `ScopedQuerySet.visible_to` does — restated here because the models below
    reach the path by three different routes and the alternative is three
    slightly different prefix scans.
    """
    if org is None:
        # An impossible predicate rather than `Q()`: an empty `Q` would widen
        # the read to the whole tenant, which is the failure this exists to
        # prevent. Callers already refuse a `None` hat; this is the belt.
        return Q(pk__in=[])
    return Q(path=org.path) | Q(path__startswith=org.path + PATH_SEPARATOR)


def list_organizations(
    *, tenant: Tenant | None, org: Organization | None
) -> QuerySet[Organization]:
    """The nodes this hat covers: its own and its descendants'.

    Never a parent's and never a sibling's — visibility flows downward only, and
    the org tree is the one place where "I can see it" and "I can act on it" are
    most tempting to widen.
    """
    # `for_tenant(None)` already returns nothing and `_subtree(None)` is an
    # impossible predicate, so both halves fail closed without an early return
    # — and the read goes through the scoped manager, which is what house rule 8
    # is watching for.
    return Organization.objects.for_tenant(tenant).filter(_subtree(org)).order_by("path")


def get_organization(
    *, tenant: Tenant | None, org: Organization | None, organization_id: UUID
) -> Organization:
    """One node by id, from within this hat's subtree.

    A node in a sibling branch — or in another tenant — answers `not_found` and
    never `forbidden`: a refusal that told those two apart would confirm the row
    exists, which is the fact the scoping was hiding.
    """
    found = list_organizations(tenant=tenant, org=org).filter(pk=organization_id).first()
    if found is None:
        raise NotFound()
    return found


def list_memberships(*, tenant: Tenant | None, org: Organization | None) -> QuerySet[Membership]:
    """Who belongs to the part of the tenant this hat covers.

    `select_related` on both the user and the organization because the wire
    shape carries the person's address and the branch's id — without it this is
    two extra queries per row, and the query pin in the tests is what makes that
    a failure rather than a slow page.
    """
    if tenant is None or org is None:
        return Membership.objects.none()
    subtree = Q(organization__path=org.path) | Q(
        organization__path__startswith=org.path + PATH_SEPARATOR
    )
    return (
        Membership.objects.filter(tenant=tenant)
        .filter(subtree)
        .select_related("user", "organization")
        .order_by("organization__path", "user__email")
    )


def get_membership(
    *, tenant: Tenant | None, org: Organization | None, membership_id: UUID
) -> Membership:
    """One membership by id, from within this hat's subtree. `not_found` otherwise."""
    found = list_memberships(tenant=tenant, org=org).filter(pk=membership_id).first()
    if found is None:
        raise NotFound()
    return found


def list_invitations(
    *, tenant: Tenant | None, org: Organization | None
) -> ScopedQuerySet[Invitation]:
    """Every invitation issued inside this hat's subtree, newest first.

    **Narrowed by the hat since ADR core-20.** An invitation records the node it
    was sent from, so it IS held on a branch, and a list that showed every
    branch's offers would tell a branch manager who the branch beside them is
    hiring. This read was tenant-wide while the row carried no organization; the
    change can only ever surprise a caller *narrower*, which is the placement
    law's own safety property.

    `visible_to` is the seam, exactly as house rule 24 requires — the one
    predicate every org-scoped read in the product goes through, rather than a
    prefix scan written out here. It fails closed on an unresolved hat: no hat
    reads an empty table, never the table.
    """
    return Invitation.objects.for_tenant(tenant).visible_to(org).order_by("-created_at")


def get_invitation(
    *, tenant: Tenant | None, org: Organization | None, invitation_id: UUID
) -> Invitation:
    """One invitation by id, from within this hat's subtree. `not_found` otherwise.

    Another branch's invitation is `not_found` and never `forbidden`: the tree's
    answer to "outside what you can see" is that it is not there, so a caller
    cannot map the shape of a subtree they hold nothing on by reading which ids
    refuse differently.
    """
    found = list_invitations(tenant=tenant, org=org).filter(pk=invitation_id).first()
    if found is None:
        raise NotFound()
    return found
