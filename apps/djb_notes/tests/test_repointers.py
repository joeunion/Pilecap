"""The `"*"` repointer, in a planted merge: every note of the loser moves, and
`count` says exactly how many before the move does it."""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.exceptions import NotFound
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_organization
from apps.core.verbs import Repointer, hook
from apps.djb_notes.models import Note
from apps.djb_notes.services import archive_note, create_note, move_notes
from apps.events.models import Event
from apps.example.models import Widget
from apps.example.services import create_widget

pytestmark = pytest.mark.django_db

PASSWORD = "a-long-enough-password"  # pragma: allowlist secret


@pytest.fixture(autouse=True)
def declares_notes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The widget declares notes for this module, ADDED to whatever it declares.

    Additive and undone by `monkeypatch`, never a replacement and never a hand
    `del`: the day the worked example declares its own attachments, this plant
    keeps them and leaves them exactly as it found them.
    """
    monkeypatch.setattr(
        Widget, "attachments", (*getattr(Widget, "attachments", ()), "notes"), raising=False
    )


def _the_notes_repointer() -> Repointer:
    """Found the way the merge will find it: the hook walk, key `"*"`."""
    found = [
        declared["*"]
        for config, declared in hook("merge_repointers")
        if config.label == "djb_notes" and "*" in declared
    ]
    assert len(found) == 1, found
    repointer = found[0]
    assert isinstance(repointer, Repointer)
    return repointer


def test_the_repointer_moves_every_note_of_the_loser_and_counts_it_first(
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    admin_actor: Actor,
    root_org: Organization,
) -> None:
    branch = create_organization(
        tenant=tenant, parent=root_org, name="Branch", slug="branch", actor=owner_actor
    )
    loser = create_widget(tenant=tenant, actor=owner_actor, name="Loser")
    survivor = create_widget(
        tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=branch), name="Survivor"
    )
    bystander = create_widget(tenant=tenant, actor=owner_actor, name="Bystander")

    def write(widget: Widget, body: str) -> Note:
        return create_note(
            tenant=tenant, actor=owner_actor, subject=f"widget:{widget.pk}", body=body
        )

    on_loser = [write(loser, "one"), write(loser, "two")]
    on_loser.append(archive_note(tenant=tenant, actor=admin_actor, note=write(loser, "three")))
    already = write(survivor, "the survivor's own")
    elsewhere = write(bystander, "not part of it")

    repointer = _the_notes_repointer()
    assert repointer.title == "Notes"

    counted = repointer.count(tenant=tenant, loser=loser)
    moved = repointer.repoint(tenant=tenant, actor=admin_actor, loser=loser, survivor=survivor)

    assert counted == 3
    assert moved == counted

    every = Note.objects.for_tenant(tenant).including_archived()
    assert not every.filter(subject_id=loser.pk).exists()
    on_survivor = every.filter(subject_kind="widget", subject_id=survivor.pk)
    assert set(on_survivor.values_list("pk", flat=True)) == {n.pk for n in [*on_loser, already]}
    # A note lives where its subject lives — the moved notes follow the survivor's branch.
    assert set(on_survivor.values_list("organization_id", flat=True)) == {branch.pk}
    # The archived one moved and stayed archived.
    assert every.get(pk=on_loser[2].pk).archived_at is not None
    # Nothing else moved.
    assert every.get(pk=elsewhere.pk).subject_id == bystander.pk

    # A repeat finds nothing left on the loser.
    assert repointer.count(tenant=tenant, loser=loser) == 0
    assert repointer.repoint(tenant=tenant, actor=admin_actor, loser=loser, survivor=survivor) == 0


def test_an_actor_who_cannot_reach_the_survivor_moves_nothing(
    tenant: Tenant, owner: User, owner_actor: Actor, root_org: Organization
) -> None:
    """A branch-A member naming a branch-B survivor: `not_found`, and not one row moves.

    The repointer does not trust its caller to have authorized the merge: both
    subjects are re-resolved for the acting person, so a survivor they could
    never have reached is the same answer as one that does not exist.
    """
    branch_a = create_organization(
        tenant=tenant, parent=root_org, name="A", slug="a", actor=owner_actor
    )
    branch_b = create_organization(
        tenant=tenant, parent=root_org, name="B", slug="b", actor=owner_actor
    )
    member_a = create_user(email="member-a@example.com", password=PASSWORD)
    add_membership(
        user=member_a,
        tenant=tenant,
        organization=branch_a,
        is_default=True,
        role=Membership.Role.MEMBER,
        actor=system_actor(tenant=tenant),
    )
    acting_a = actor_for(user=member_a, tenant=tenant, org=branch_a)
    loser = create_widget(tenant=tenant, actor=acting_a, name="Loser at A")
    survivor = create_widget(
        tenant=tenant, actor=actor_for(user=owner, tenant=tenant, org=branch_b), name="At B"
    )
    note = create_note(tenant=tenant, actor=acting_a, subject=f"widget:{loser.pk}", body="mine")

    with pytest.raises(NotFound):
        move_notes(tenant=tenant, actor=acting_a, loser=loser, survivor=survivor)

    after = Note.objects.for_tenant(tenant).including_archived().get(pk=note.pk)
    assert after.subject_id == loser.pk
    assert after.organization_id == branch_a.pk
    assert not Event.objects.for_tenant(tenant).filter(name="djb_notes.note.moved").exists()


def test_every_moved_note_says_so_once_and_a_repeat_says_nothing(
    tenant: Tenant, owner_actor: Actor, admin_actor: Actor
) -> None:
    loser = create_widget(tenant=tenant, actor=owner_actor, name="Loser")
    survivor = create_widget(tenant=tenant, actor=owner_actor, name="Survivor")
    notes = [
        create_note(tenant=tenant, actor=owner_actor, subject=f"widget:{loser.pk}", body=b)
        for b in ("one", "two")
    ]

    assert move_notes(tenant=tenant, actor=admin_actor, loser=loser, survivor=survivor) == 2
    moved = Event.objects.for_tenant(tenant).filter(name="djb_notes.note.moved")
    assert sorted(e.payload["id"] for e in moved) == sorted(str(n.pk) for n in notes)
    assert {e.payload["subject"] for e in moved} == {f"widget:{survivor.pk}"}

    assert move_notes(tenant=tenant, actor=admin_actor, loser=loser, survivor=survivor) == 0
    assert moved.count() == 2
