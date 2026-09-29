"""The services, called directly: the vocabulary, the links, and the repointer.

Every row is written by the service that really writes it. The door tests
(`test_api.py`, `test_doors_over_the_wire.py`) prove the same properties on the
wire; these prove them where the rule lives.
"""

from __future__ import annotations

import pytest

from apps.accounts.models import User
from apps.core.actor import Actor, actor_for
from apps.core.exceptions import Archived, Conflict, Forbidden, Invalid, NotFound
from apps.core.models import Tenant
from apps.core.verbs import Repointer, hook
from apps.djb_tags.events import TAG_LINK_CREATED, TAG_LINK_DELETED, TAG_LINK_MOVED
from apps.djb_tags.merge_repointers import REPOINTERS
from apps.djb_tags.models import Tag, TagLink
from apps.djb_tags.selectors import list_tag_links, list_tags
from apps.djb_tags.services import (
    archive_tag,
    create_tag,
    create_tag_link,
    delete_tag_link,
    move_tag_links,
    rename_tag,
    restore_tag,
)
from apps.djb_tags.tests.conftest import World
from apps.events.models import Event

pytestmark = pytest.mark.django_db


def _subject(row: object) -> str:
    return f"widget:{row.pk}"  # type: ignore[attr-defined]


def _events(tenant: Tenant, name: str) -> int:
    return Event.objects.for_tenant(tenant).filter(name=name).count()


# --- the words ---------------------------------------------------------------


def test_a_tag_is_coined_once_per_tenant(tenant: Tenant, owner_actor: Actor) -> None:
    tag = create_tag(tenant=tenant, actor=owner_actor, name="  Very Urgent ")
    assert (tag.name, tag.slug) == ("Very Urgent", "very-urgent")
    with pytest.raises(Conflict):
        create_tag(tenant=tenant, actor=owner_actor, name="very urgent")


def test_an_archived_word_still_owns_its_slug(tenant: Tenant, owner_actor: Actor) -> None:
    tag = create_tag(tenant=tenant, actor=owner_actor, name="Urgent")
    archive_tag(tenant=tenant, actor=owner_actor, tag=tag)
    with pytest.raises(Conflict, match="restore it instead"):
        create_tag(tenant=tenant, actor=owner_actor, name="Urgent")


def test_a_word_with_no_letters_is_invalid_naming_name(tenant: Tenant, owner_actor: Actor) -> None:
    with pytest.raises(Invalid) as refused:
        create_tag(tenant=tenant, actor=owner_actor, name="!!!")
    assert set(refused.value.errors) == {"name"}


def test_a_member_may_not_coin_a_word(tenant: Tenant, member_actor: Actor) -> None:
    with pytest.raises(Forbidden):
        create_tag(tenant=tenant, actor=member_actor, name="Urgent")


def test_a_branch_actor_is_asked_at_the_root(world: World) -> None:
    """A tenant-wide kind is written at the root (house rule 55): the clerk's
    hat is branch A, and the root is where the question is asked."""
    with pytest.raises(Forbidden):
        create_tag(tenant=world.tenant, actor=world.clerk_actor, name="Urgent")


def test_rename_respells_and_moves_the_slug(tenant: Tenant, owner_actor: Actor) -> None:
    tag = create_tag(tenant=tenant, actor=owner_actor, name="Urgent")
    renamed = rename_tag(tenant=tenant, actor=owner_actor, tag=tag, name="Critical")
    assert (renamed.name, renamed.slug) == ("Critical", "critical")


def test_an_archived_word_cannot_be_renamed(tenant: Tenant, owner_actor: Actor) -> None:
    tag = create_tag(tenant=tenant, actor=owner_actor, name="Urgent")
    tag = archive_tag(tenant=tenant, actor=owner_actor, tag=tag)
    with pytest.raises(Archived):
        rename_tag(tenant=tenant, actor=owner_actor, tag=tag, name="Critical")


def test_archive_hides_the_word_and_a_second_press_changes_nothing(
    tenant: Tenant, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=tenant, actor=owner_actor, name="Urgent")
    first = archive_tag(tenant=tenant, actor=owner_actor, tag=tag)
    again = archive_tag(tenant=tenant, actor=owner_actor, tag=tag)
    assert again.archived_at == first.archived_at
    assert first.archived_by_id == owner_actor.user.pk  # type: ignore[union-attr]
    assert _events(tenant, "djb_tags.tag.archived") == 1
    assert list(list_tags(tenant=tenant, actor=owner_actor)) == []
    assert list(list_tags(tenant=tenant, actor=owner_actor, show="archived")) == [tag]
    restored = restore_tag(tenant=tenant, actor=owner_actor, tag=tag)
    assert restored.archived_at is None
    assert list(list_tags(tenant=tenant, actor=owner_actor)) == [tag]


def test_a_member_may_not_archive_a_word(
    tenant: Tenant, owner_actor: Actor, member_actor: Actor
) -> None:
    tag = create_tag(tenant=tenant, actor=owner_actor, name="Urgent")
    with pytest.raises(Forbidden):
        archive_tag(tenant=tenant, actor=member_actor, tag=tag)


# --- the links (TG.1) ----------------------------------------------------------


@pytest.mark.usefixtures("widget_takes_tags")
def test_a_link_lands_in_the_subjects_branch_and_is_idempotent(
    world: World, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    first = create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=tag, subject=_subject(world.widget_a)
    )
    second = create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=tag, subject=_subject(world.widget_a)
    )
    assert first.created is True
    assert second.created is False
    assert second.link.pk == first.link.pk
    assert first.link.organization_id == world.branch_a.pk
    assert TagLink.objects.for_tenant(world.tenant).count() == 1
    assert _events(world.tenant, TAG_LINK_CREATED) == 1


@pytest.mark.usefixtures("tag_takes_tags")
def test_a_link_on_a_tenant_wide_subject_lands_at_the_acting_hat(
    world: World, owner: User, owner_actor: Actor
) -> None:
    """The landing law's second case: a subject with no branch of its own lands
    the link at the ACTING HAT (ADR core-20), never at the root — visibility is
    down-only, so a root-landed link is one its own branch author cannot read
    back. The word itself stays root-written (house rule 55)."""
    subject = create_tag(tenant=world.tenant, actor=owner_actor, name="Region")
    word = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    linking = create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=word, subject=f"djb_tag:{subject.pk}"
    )
    assert linking.link.organization_id == world.branch_a.pk
    assert linking.link.organization_id != world.root.pk
    read_back = list_tag_links(
        tenant=world.tenant, actor=world.clerk_actor, subject=f"djb_tag:{subject.pk}"
    )
    assert [link.pk for link in read_back] == [linking.link.pk]
    at_b = actor_for(user=owner, tenant=world.tenant, org=world.branch_b)
    assert not list_tag_links(tenant=world.tenant, actor=at_b, subject=f"djb_tag:{subject.pk}")


@pytest.mark.usefixtures("tag_takes_tags")
def test_a_word_already_on_a_tenant_wide_subject_from_another_branch_is_a_conflict(
    world: World, owner: User, owner_actor: Actor
) -> None:
    """One link per `(tag, subject)` holds tenant-wide, and a link another branch
    landed is not this hat's to read — so the second branch's press is a
    `conflict` with no row change and no event, never a 500 off the lost race."""
    subject = create_tag(tenant=world.tenant, actor=owner_actor, name="Region")
    word = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=word, subject=f"djb_tag:{subject.pk}"
    )
    at_b = actor_for(user=owner, tenant=world.tenant, org=world.branch_b)
    with pytest.raises(Conflict):
        create_tag_link(tenant=world.tenant, actor=at_b, tag=word, subject=f"djb_tag:{subject.pk}")
    assert TagLink.objects.for_tenant(world.tenant).count() == 1
    assert _events(world.tenant, TAG_LINK_CREATED) == 1


@pytest.mark.usefixtures("widget_takes_tags")
def test_a_sibling_branchs_subject_is_not_found(world: World, owner_actor: Actor) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    with pytest.raises(NotFound):
        create_tag_link(
            tenant=world.tenant,
            actor=world.clerk_actor,
            tag=tag,
            subject=_subject(world.widget_b),
        )
    with pytest.raises(NotFound):
        list_tag_links(
            tenant=world.tenant, actor=world.clerk_actor, subject=_subject(world.widget_b)
        )


@pytest.mark.usefixtures("widget_takes_no_tags")
def test_a_kind_that_does_not_take_tags_is_invalid_naming_subject(
    world: World, owner_actor: Actor
) -> None:
    """`Widget` with `tags` taken out of its declaration: `invalid` naming `subject`."""
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    with pytest.raises(Invalid) as refused:
        create_tag_link(
            tenant=world.tenant,
            actor=world.clerk_actor,
            tag=tag,
            subject=_subject(world.widget_a),
        )
    assert set(refused.value.errors) == {"subject"}


@pytest.mark.usefixtures("widget_takes_tags")
def test_an_archived_word_cannot_be_put_on_a_row(world: World, owner_actor: Actor) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    archive_tag(tenant=world.tenant, actor=owner_actor, tag=tag)
    tag.refresh_from_db()
    with pytest.raises(Archived):
        create_tag_link(
            tenant=world.tenant,
            actor=world.clerk_actor,
            tag=tag,
            subject=_subject(world.widget_a),
        )


@pytest.mark.usefixtures("widget_takes_tags")
def test_archiving_a_word_keeps_its_links_readable(world: World, owner_actor: Actor) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=tag, subject=_subject(world.widget_a)
    )
    archive_tag(tenant=world.tenant, actor=owner_actor, tag=tag)
    links = list(
        list_tag_links(
            tenant=world.tenant, actor=world.clerk_actor, subject=_subject(world.widget_a)
        )
    )
    assert [link.tag_id for link in links] == [tag.pk]
    assert links[0].tag.is_archived


@pytest.mark.usefixtures("widget_takes_tags")
def test_delete_tag_link_removes_it_and_says_so(world: World, owner_actor: Actor) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    link = create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=tag, subject=_subject(world.widget_a)
    ).link
    removed = delete_tag_link(tenant=world.tenant, actor=world.clerk_actor, link=link)
    assert removed.pk == link.pk
    assert not TagLink.objects.for_tenant(world.tenant).exists()
    assert _events(world.tenant, TAG_LINK_DELETED) == 1


# --- the repointer (the merge case) --------------------------------------------


def test_tags_declares_one_repointer_for_every_noun() -> None:
    declared = {config.label: repointers for config, repointers in hook("merge_repointers")}
    assert set(declared["djb_tags"]) == {"*"}
    assert isinstance(declared["djb_tags"]["*"], Repointer)


@pytest.mark.usefixtures("widget_takes_tags")
def test_the_repointer_moves_every_link_and_counts_what_it_moves(
    world: World, owner_actor: Actor
) -> None:
    """A planted merge: the loser carries three words, the survivor already
    carries one of them. After `repoint` the loser carries nothing, the survivor
    carries all three once each, and the answer equals `count`'s dry run."""
    tenant = world.tenant
    loser, survivor = world.other_widget_a, world.widget_a
    urgent, blue, big = (
        create_tag(tenant=tenant, actor=owner_actor, name=name)
        for name in ("Urgent", "Blue", "Big")
    )
    for tag in (urgent, blue, big):
        create_tag_link(tenant=tenant, actor=world.clerk_actor, tag=tag, subject=_subject(loser))
    create_tag_link(tenant=tenant, actor=world.clerk_actor, tag=urgent, subject=_subject(survivor))
    repointer = REPOINTERS["*"]

    stamped_before = dict(
        TagLink.objects.for_tenant(tenant)
        .filter(subject_id=loser.pk)
        .values_list("tag__slug", "updated_at")
    )

    counted = repointer.count(tenant=tenant, loser=loser)
    moved = repointer.repoint(tenant=tenant, actor=owner_actor, loser=loser, survivor=survivor)

    assert counted == 3
    assert moved == counted
    assert repointer.count(tenant=tenant, loser=loser) == 0
    on_survivor = TagLink.objects.for_tenant(tenant).filter(subject_id=survivor.pk)
    assert sorted(on_survivor.values_list("tag__slug", flat=True)) == ["big", "blue", "urgent"]
    assert set(on_survivor.values_list("organization_id", flat=True)) == {survivor.organization_id}
    # Three counted as LEFT: two moved, one collapsed onto the survivor's own
    # link — two `.moved` and one `.deleted` (the collapsed link's own leaving
    # event), never a third `.moved`.
    assert _events(tenant, TAG_LINK_MOVED) == 2
    assert _events(tenant, TAG_LINK_DELETED) == 1
    # Every moving write stamps `updated_at` (house rule 76's form).
    for slug in ("blue", "big"):
        moved_link = on_survivor.get(tag__slug=slug)
        assert moved_link.updated_at > stamped_before[slug]


@pytest.mark.usefixtures("widget_takes_tags")
def test_the_repointer_refuses_a_subject_the_actor_cannot_reach(
    world: World, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    create_tag_link(
        tenant=world.tenant, actor=world.clerk_actor, tag=tag, subject=_subject(world.widget_a)
    )
    with pytest.raises(NotFound):
        move_tag_links(
            tenant=world.tenant,
            actor=world.clerk_actor,
            loser=world.widget_a,
            survivor=world.widget_b,
        )
    assert TagLink.objects.for_tenant(world.tenant).get().subject_id == world.widget_a.pk


def test_the_tags_list_is_the_tenants_own(
    tenant: Tenant, owner_actor: Actor, other_tenant: Tenant, stranger_actor: Actor
) -> None:
    create_tag(tenant=tenant, actor=owner_actor, name="Ours")
    create_tag(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    assert [tag.name for tag in list_tags(tenant=tenant, actor=owner_actor)] == ["Ours"]
    assert Tag.objects.for_tenant(other_tenant).count() == 1
