"""The REST door, through the mounted API so the tenant and hat middleware run.

TG.1 on the wire: coin a word, put it on a row (201, then 200 the same row and
no second event), take it off, archive the word — gone from `/tags/`, still on
the row. Around it, the attachment law: a sibling branch's row is 404, a kind
that does not take tags is 400 naming `subject`. And one query pin per list.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.core.actor import Actor
from apps.core.models import Tenant
from apps.events.models import Event
from apps.tags.events import TAG_LINK_CREATED
from apps.tags.models import Tag, TagLink
from apps.tags.services import create_tag, create_tag_link
from apps.tags.tests.conftest import World

pytestmark = pytest.mark.django_db

TAGS_URL = "/api/v1/tags/"
TAG_URL = "/api/v1/tags/{}/"
LINKS_URL = "/api/v1/tag-links/"
LINK_URL = "/api/v1/tag-links/{}/"
JSON = "application/json"

# Measured at ten rows, and the same at one: session + user, the SAVEPOINT
# pair (ATOMIC_REQUESTS), the two membership reads the tenant and hat
# middleware make, the three tables resolution reads for `tag.read`, and the
# page — one statement, `archived_by` joined (`select_related`).
TAGS_QUERY_BUDGET = 10

# The same shape for a subject's links, plus the subject's own resolution —
# the row read through `visible_to` the hat, and its organization for the
# `may_be_named` question and the link's landing node — and the page, `tag`
# joined, so `tag_name` / `tag_slug` cost nothing per row. Measured at one link
# and at ten: the same.
LINKS_QUERY_BUDGET = 12


def _body(response: Any) -> Any:
    return json.loads(response.content)


def _post(api: Client, url: str, payload: dict[str, Any]) -> Any:
    return api.post(url, data=json.dumps(payload), content_type=JSON)


def test_the_route_map_is_the_published_one() -> None:
    """Every door this app mounts, by name, at the path the design names — the
    paths are the contract (`/tags/`, `/tag-links/`), so a move shows up here."""
    some = "0196a1f2-7c3d-7e41-9b2a-5d6e7f8a9b0c"
    routes = {
        ("tag-list", ()): TAGS_URL,
        ("tag-create", ()): TAGS_URL,
        ("tag-detail", (some,)): TAG_URL.format(some),
        ("tag-rename", (some,)): TAG_URL.format(some),
        ("tag-archive", (some,)): f"{TAG_URL.format(some)}archive/",
        ("tag-restore", (some,)): f"{TAG_URL.format(some)}restore/",
        ("tag_links-list", ()): LINKS_URL,
        ("tag_link-create", ()): LINKS_URL,
        ("tag_link-delete", (some,)): LINK_URL.format(some),
    }
    for (name, args), path in routes.items():
        assert reverse(f"api:{name}", args=args) == path, name


def test_anonymous_is_refused(api: Client) -> None:
    assert api.get(TAGS_URL).status_code == 401
    assert api.get(LINKS_URL, {"subject": "widget:x"}).status_code == 401


def test_coin_a_word_over_the_wire(api: Client, tenant: Tenant, owner: User) -> None:
    api.force_login(owner)
    response = _post(api, TAGS_URL, {"name": "Urgent"})
    assert response.status_code == 201, response.content
    body = _body(response)
    assert (body["name"], body["slug"], body["archived_at"]) == ("Urgent", "urgent", None)
    again = _post(api, TAGS_URL, {"name": "urgent"})
    assert again.status_code == 409
    assert _body(again)["code"] == "conflict"


def test_a_member_may_not_coin_a_word(api: Client, member: User) -> None:
    api.force_login(member)
    response = _post(api, TAGS_URL, {"name": "Urgent"})
    assert response.status_code == 403
    assert _body(response)["code"] == "forbidden"


def test_an_unknown_field_is_refused(api: Client, owner: User) -> None:
    api.force_login(owner)
    response = _post(api, TAGS_URL, {"name": "Urgent", "colour": "red"})
    assert response.status_code == 422
    assert _body(response)["code"] == "invalid_body"


@pytest.mark.usefixtures("widget_takes_tags")
def test_tg1_link_twice_remove_and_archive_over_the_wire(
    api: Client, world: World, owner: User, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    subject = f"widget:{world.widget_a.pk}"
    api.force_login(world.clerk)

    first = _post(api, LINKS_URL, {"tag_id": str(tag.pk), "subject": subject})
    assert first.status_code == 201, first.content
    second = _post(api, LINKS_URL, {"tag_id": str(tag.pk), "subject": subject})
    assert second.status_code == 200, second.content
    assert _body(second) == _body(first)
    assert _body(first)["organization_id"] == str(world.branch_a.pk)
    assert Event.objects.for_tenant(world.tenant).filter(name=TAG_LINK_CREATED).count() == 1

    listed = api.get(LINKS_URL, {"subject": subject})
    assert listed.status_code == 200
    assert [item["id"] for item in _body(listed)["items"]] == [_body(first)["id"]]

    # Archive the word, as an administrator of the whole tenant.
    admin = Client()
    admin.force_login(owner)
    archived = admin.post(f"{TAG_URL.format(tag.pk)}archive/")
    assert archived.status_code == 200, archived.content
    assert _body(archived)["archived_at"] is not None
    assert _body(archived)["archived_by"]["id"] == str(owner.pk)
    assert _body(admin.get(TAGS_URL))["items"] == []
    assert [item["id"] for item in _body(admin.get(TAGS_URL, {"show": "archived"}))["items"]] == [
        str(tag.pk)
    ]
    # ...and the row still carries it.
    still = api.get(LINKS_URL, {"subject": subject})
    assert [item["tag_id"] for item in _body(still)["items"]] == [str(tag.pk)]

    removed = api.delete(LINK_URL.format(_body(first)["id"]))
    assert removed.status_code == 204
    assert _body(api.get(LINKS_URL, {"subject": subject}))["items"] == []


@pytest.mark.usefixtures("widget_takes_tags")
def test_a_sibling_branchs_subject_is_404_both_ways(
    api: Client, world: World, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    subject = f"widget:{world.widget_b.pk}"
    api.force_login(world.clerk)
    tagged = _post(api, LINKS_URL, {"tag_id": str(tag.pk), "subject": subject})
    assert tagged.status_code == 404, tagged.content
    assert api.get(LINKS_URL, {"subject": subject}).status_code == 404
    assert not TagLink.objects.for_tenant(world.tenant).exists()


@pytest.mark.usefixtures("widget_takes_no_tags")
def test_a_kind_that_does_not_take_tags_is_400_naming_subject(
    api: Client, world: World, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    api.force_login(world.clerk)
    subject = f"widget:{world.widget_a.pk}"
    for response in (
        _post(api, LINKS_URL, {"tag_id": str(tag.pk), "subject": subject}),
        api.get(LINKS_URL, {"subject": subject}),
        api.get(LINKS_URL, {"subject": "no-colon"}),
    ):
        assert response.status_code == 400, response.content
        body = _body(response)
        assert body["code"] == "invalid"
        assert set(body["errors"]) == {"subject"}


@pytest.mark.usefixtures("widget_takes_tags")
def test_a_link_in_another_branch_cannot_be_removed(
    api: Client, world: World, owner: User, owner_actor: Actor
) -> None:
    tag = create_tag(tenant=world.tenant, actor=owner_actor, name="Urgent")
    link = create_tag_link(
        tenant=world.tenant, actor=owner_actor, tag=tag, subject=f"widget:{world.widget_b.pk}"
    ).link
    api.force_login(world.clerk)
    assert api.delete(LINK_URL.format(link.pk)).status_code == 404
    assert TagLink.objects.for_tenant(world.tenant).filter(pk=link.pk).exists()


def test_another_tenants_words_are_absent(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    other_tenant: Tenant,
    stranger_actor: Actor,
) -> None:
    create_tag(tenant=tenant, actor=owner_actor, name="Ours")
    theirs = create_tag(tenant=other_tenant, actor=stranger_actor, name="Theirs")
    api.force_login(owner)
    assert [item["name"] for item in _body(api.get(TAGS_URL))["items"]] == ["Ours"]
    assert api.get(TAG_URL.format(theirs.pk)).status_code == 404


@pytest.mark.parametrize("rows", [1, 10])
def test_tags_list_query_count_does_not_grow_with_rows(
    api: Client,
    tenant: Tenant,
    owner: User,
    owner_actor: Actor,
    django_assert_num_queries: Any,
    rows: int,
) -> None:
    for index in range(rows):
        create_tag(tenant=tenant, actor=owner_actor, name=f"Word {index}")
    api.force_login(owner)
    with django_assert_num_queries(TAGS_QUERY_BUDGET):
        response = api.get(TAGS_URL)
    assert response.status_code == 200
    assert len(_body(response)["items"]) == rows


@pytest.mark.parametrize("rows", [1, 10])
@pytest.mark.usefixtures("widget_takes_tags")
def test_tag_links_list_query_count_does_not_grow_with_rows(
    api: Client, world: World, owner_actor: Actor, django_assert_num_queries: Any, rows: int
) -> None:
    subject = f"widget:{world.widget_a.pk}"
    for index in range(rows):
        tag = create_tag(tenant=world.tenant, actor=owner_actor, name=f"Word {index}")
        create_tag_link(tenant=world.tenant, actor=world.clerk_actor, tag=tag, subject=subject)
    api.force_login(world.clerk)
    with django_assert_num_queries(LINKS_QUERY_BUDGET):
        response = api.get(LINKS_URL, {"subject": subject})
    assert response.status_code == 200
    assert len(_body(response)["items"]) == rows
    assert Tag.objects.for_tenant(world.tenant).count() == rows
