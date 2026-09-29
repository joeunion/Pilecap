"""The world every tags test is measured against.

One tenant, a root and two sibling branches, and a clerk who belongs to branch
A only — the pair every attachment test needs: a subject the clerk can reach
(a widget in A) and one they cannot (a widget in B).

**The subject is the worked example's `Widget`**, which declares
`attachments = ("notes", "tags", "files")`. `widget_takes_tags` still ADDS
`"tags"` through `monkeypatch` (a no-op on this tree, and what keeps these
tests honest on a tree whose example declares nothing), and the refusal half
("a kind that does not take tags") takes the one word OUT with
`widget_takes_no_tags` — both undone by `monkeypatch` when the test ends.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.djb_tags.models import ATTACHMENT, Tag
from apps.example.models import Widget
from apps.example.services import create_widget

PASSWORD = "a-long-enough-password-for-validators"  # pragma: allowlist secret


@dataclass
class World:
    tenant: Tenant
    root: Organization
    branch_a: Organization
    branch_b: Organization
    clerk: User
    clerk_actor: Actor
    widget_a: Widget
    other_widget_a: Widget
    widget_b: Widget


@pytest.fixture
def widget_takes_tags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`Widget` takes tags for this test only — ADDED to whatever it declares.

    Additive, never a replacement: a real `attachments` declaration on the class
    stays in force inside the test, so a test can never hide one.
    """
    _takes_tags(monkeypatch, Widget)
    yield


@pytest.fixture
def widget_takes_no_tags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`Widget` WITHOUT tags for this test only — every other attachment it declares kept.

    The worked example declares `attachments = ("notes", "tags", "files")`, so a
    test asking what a kind that does not take tags is told takes that one word
    OUT, and only it — subtractive, undone by `monkeypatch`, never a hand `del`.
    """
    kept = tuple(kind for kind in getattr(Widget, "attachments", ()) if kind != ATTACHMENT)
    monkeypatch.setattr(Widget, "attachments", kept, raising=False)
    yield


@pytest.fixture
def tag_takes_tags(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A TENANT-WIDE subject that takes tags, for this test only: `Tag` itself.

    The tree has no tenant-wide noun that declares attachments, and `Tag` is the
    nearest tenant-wide kind the resolver already knows — a row with no branch
    of its own, which is the whole of what the landing law's second case needs.
    """
    _takes_tags(monkeypatch, Tag)
    yield


def _takes_tags(monkeypatch: pytest.MonkeyPatch, model: type) -> None:
    declared = tuple(getattr(model, "attachments", ()) or ())
    if ATTACHMENT not in declared:
        monkeypatch.setattr(model, "attachments", (*declared, ATTACHMENT), raising=False)


@pytest.fixture
def world(
    tenant: Tenant,
    root_org: Organization,
    owner: User,
    owner_actor: Actor,
    recorded_workflow_starts: None,
) -> World:
    branch_a = create_organization(
        tenant=tenant, parent=root_org, name="Branch A", slug="branch-a", actor=owner_actor
    )
    branch_b = create_organization(
        tenant=tenant, parent=root_org, name="Branch B", slug="branch-b", actor=owner_actor
    )
    clerk = create_user(email="clerk@example.com", password=PASSWORD)
    add_membership(
        user=clerk,
        tenant=tenant,
        organization=branch_a,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant, org=root_org),
    )
    clerk_actor = actor_for(user=clerk, tenant=tenant, org=branch_a)
    at_b = actor_for(user=owner, tenant=tenant, org=branch_b)
    return World(
        tenant=tenant,
        root=root_org,
        branch_a=branch_a,
        branch_b=branch_b,
        clerk=clerk,
        clerk_actor=clerk_actor,
        widget_a=create_widget(tenant=tenant, actor=clerk_actor, name="Bench A"),
        other_widget_a=create_widget(tenant=tenant, actor=clerk_actor, name="Duplicate A"),
        widget_b=create_widget(tenant=tenant, actor=at_b, name="Bench B"),
    )
