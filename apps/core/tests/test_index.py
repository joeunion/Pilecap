"""`/` names the doors — and names only doors that are really mounted.

Before this, `/` on a live box was Django's bare "Not Found": the first thing
an owner or a third party sees, saying nothing about a running product.

The property under test is not "a page renders". It is that **every href on the
page is derived** — reversed out of the live URL configuration, or read from the
constant the mount itself routes on — so that the page cannot claim a door this
process did not mount. A hand-written list of paths would render identically and
would be wrong the first time somebody moved the API's version segment; these
tests re-derive the expected set from the registries and demand equality, which
is what a typed list could not survive.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from django.conf import settings
from django.test import Client
from django.urls import NoReverseMatch, URLPattern, URLResolver, get_resolver, reverse

from apps.core.mcp import MCP_PATH
from apps.core.views import doors, rest_resources, template_version

HREF = re.compile(r'href="([^"]+)"')

#: Where `config/urls.py` hangs the API today. Typed HERE on purpose: the point
#: of these tests is to state the truth independently of the code that derives
#: it, so that the two can disagree. The view reads it off the mount.
API_ROOT = "/api/v1/"

pytestmark = pytest.mark.django_db


@pytest.fixture
def page(client: Client) -> Any:
    return client.get("/")


# --- it answers ---------------------------------------------------------------


def test_the_root_answers_html(page: Any) -> None:
    """200 and HTML, to an anonymous client: the page needs no credential."""
    assert page.status_code == 200
    assert page["Content-Type"].startswith("text/html")


def test_head_answers_too(client: Client) -> None:
    """A probe or a link checker asks HEAD; a 404 there is the same finding."""
    assert client.head("/").status_code == 200


def test_it_prints_the_template_version(page: Any) -> None:
    """The version this tree was cloned from, from the one file that states it."""
    version = (Path(settings.BASE_DIR) / "TEMPLATE_VERSION").read_text().strip()

    assert version
    assert template_version() == version
    assert version in page.content.decode()


# --- every href is derived, not typed -----------------------------------------


def _mounted_names() -> set[str]:
    """Every named URL in this process, namespaces included."""
    found: set[str] = set()

    def walk(resolver: URLResolver, namespace: str) -> None:
        for entry in resolver.url_patterns:
            if isinstance(entry, URLResolver):
                walk(entry, namespace + (f"{entry.namespace}:" if entry.namespace else ""))
            elif isinstance(entry, URLPattern) and entry.name:
                found.add(f"{namespace}{entry.name}")

    walk(get_resolver(), "")
    return found


def _reversible() -> dict[str, str]:
    """The mounted names that take no arguments, and what each reverses to."""
    out: dict[str, str] = {}
    for name in _mounted_names():
        try:
            out[name] = reverse(name)
        except NoReverseMatch:
            continue
    return out


def test_every_door_href_is_a_reversed_name_or_the_mount_constant() -> None:
    """The falsifier for "somebody typed a path".

    Each door's href must equal `reverse()` of some name this process mounted,
    or `MCP_PATH` — the constant `config/asgi.py` routes the machine door on.
    A path spelled out in the view or the template belongs to neither set.
    """
    derived = set(_reversible().values()) | {MCP_PATH}

    listed = [door.href for door in doors()]
    assert listed, "the page listed no doors at all"
    assert set(listed) <= derived, [href for href in listed if href not in derived]


def test_the_doors_are_exactly_the_ones_this_deployment_mounts() -> None:
    """The set, not merely a subset: a sixth row would have to be justified."""
    by_label = {door.label: door.href for door in doors()}

    assert set(by_label) == {"REST", "MCP", "Sign in", "Liveness", "Readiness"}
    assert by_label["REST"] == reverse("api:openapi-view")
    assert by_label["MCP"] == MCP_PATH
    assert by_label["Sign in"] == reverse("account_login")
    assert by_label["Liveness"] == reverse("healthz")
    assert by_label["Readiness"] == reverse("readyz")


def test_the_rest_resources_are_exactly_what_the_api_mounted() -> None:
    """Re-derived here from the URL registry, and compared as a set.

    This is the half `DJB_DISABLED_APPS` moves: an app that is not installed
    contributes no routes, so its segment is absent from both sides at once.
    """
    expected = {
        segment
        for name, url in _reversible().items()
        if name.startswith("api:") and url.startswith(API_ROOT)
        for segment in [url.removeprefix(API_ROOT).split("/")[0]]
        if segment and "." not in segment and segment != "docs"
    }

    assert {resource.label for resource in rest_resources()} == expected
    assert "widgets" in expected, "the worked example's door is mounted by default"
    assert {resource.path for resource in rest_resources()} == {
        f"{API_ROOT}{segment}/" for segment in expected
    }


def test_a_prefix_is_only_linked_when_something_answers_at_it() -> None:
    """A directory listing whose rows 404 is worse than one that says "namespace".

    `/api/v1/widgets/` is a real route. `/api/v1/auth/` is not — realm discovery
    and the SSO connections live one level down — and linking it would offer a
    404, which is exactly the bare "Not Found" this page exists to stop showing
    people.

    `auth` is the example since ADR api-2 flattened the four platform groups:
    the namespaces that survive are the ones where the segment is a genuine
    grouping rather than an app label, which is the distinction the ruling
    drew. Asserted as membership rather than as the whole set, so the day
    somebody puts a route at `/api/v1/auth/` this test says so and does not
    quietly stop meaning anything.
    """
    mounted = set(_reversible().values())
    linked = {resource.path for resource in rest_resources() if resource.href}
    named = {resource.path for resource in rest_resources() if resource.href is None}

    assert linked <= mounted
    assert named.isdisjoint(mounted)
    assert linked and named, "both halves should exist in the template's own tree"
    assert f"{API_ROOT}widgets/" in linked
    assert f"{API_ROOT}auth/" in named
    for resource in rest_resources():
        assert resource.href in (None, resource.path)


def test_every_href_the_page_renders_is_one_the_view_derived(page: Any) -> None:
    """The template cannot smuggle a path in either."""
    derived = {door.href for door in doors()} | {
        resource.href for resource in rest_resources() if resource.href
    }

    assert set(HREF.findall(page.content.decode())) == derived


# --- the judgement is recorded ------------------------------------------------


def test_the_root_index_is_recorded_with_its_reason() -> None:
    """A view that answers with no credential is a decision somebody wrote down.

    It is `allow_unauthenticated_views` and not `allow_unauthenticated` because
    the latter is the ninja registry's, asserted as an equality by two tests
    that read the live routes — a Django view put in it fails both. The reason
    is what is being held down here; the key is where rule 3 keeps it.
    """
    rules = yaml.safe_load((Path(settings.BASE_DIR) / "quality" / "rules.yaml").read_text())
    rule = next(entry for entry in rules["rules"] if str(entry["id"]) == "3")
    recorded = rule["scope"]["allow_unauthenticated_views"]

    entry = next(one for one in recorded if one["url_name"] == "index")
    assert entry["view"] == "apps.core.views.index"
    assert "opens none" in entry["reason"]
    assert reverse("index") == "/"


def test_the_page_says_the_same_thing_to_everybody(client: Client, owner: Any) -> None:
    """The recorded reason, as a property: it reads no request state.

    If the page ever grew a "signed in as…" line this fails, and whoever added
    it has to revisit the reason in `rules.yaml` rather than quietly widening
    it.
    """
    before = client.get("/").content
    client.force_login(owner)

    assert client.get("/").content == before
