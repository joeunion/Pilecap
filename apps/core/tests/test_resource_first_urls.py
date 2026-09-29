"""ADR api-2: the first path segment names a resource, never an app.

The owner's ruling (design-agreements.md, 2026-08-24) is a URL contract, so it
is asserted the way a contract is: over the WHOLE exported document rather than
over a list of routes somebody maintains. A route added in any app is in scope
from the moment discovery finds it, which is the difference between a standard
and a checklist.

Four properties, and the fourth is the one that makes the other three worth
having:

* **no path's first segment is an app label** — house rule 32's own census,
  re-asserted here from the document rather than from the registry, so the rule
  and the document have to agree with each other and not merely with themselves;
* **every path ends with a slash** — one convention, no exceptions, which is
  what the five slashless routes were breaking;
* **the old spellings are gone**, and answer the API's own JSON 404
  rather than a page of HTML — a move nobody can observe is a move that will be
  half-made;
* **the bodies did not move when the paths did.** Each moved group's
  representative route is pinned against the body it returned at the OLD path at
  the rung's baseline (tree 492d49e), pasted below. A URL change that also
  changed a payload would be a contract change wearing a rename.

`url_name`s are deliberately absent from all of this: they are internal joins —
rule 17 derives the expected MCP tool names from them and rule 3's route-test
clause greps them — so the tool registry is pinned here too, to prove that moving
paths moved no tool name.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.core.checks import _local_app_configs, allowed_label_paths
from apps.core.models import Tenant
from config.api import api as ninja_api

pytestmark = pytest.mark.django_db

JSON = "application/json"

#: The bodies the four moved groups return at their NEW paths. Originally pinned
#: against the OLD paths at the original baseline (main @ 492d49e); re-baselined
#: once, deliberately, when ADR core-18's cursor cut replaced the list
#: envelope tree-wide — the rename itself still moved no payload, and the
#: envelope change is the ratified one, not a drift. `count` is null because
#: nothing here sends `include_count=true`.
BASELINE_BODIES: dict[str, tuple[str, str]] = {
    "core": (
        "/api/v1/organizations/",
        '{"items": [{"name": "Acme", "slug": "acme", "parent_id": null, '
        '"path": "0000", "depth": 0}], "has_more": false, "next_cursor": null, '
        '"count": null}',
    ),
    "comms": (
        "/api/v1/delivery-policies/",
        '{"items": [], "has_more": false, "next_cursor": null, "count": null}',
    ),
    "workflows": (
        "/api/v1/runs/",
        '{"items": [], "has_more": false, "next_cursor": null, "count": null}',
    ),
}

#: The old spellings that were deleted. Every one of them must now answer the
#: API's own refusal, not Django's HTML page and not a redirect.
RETIRED = (
    "/api/v1/core/organizations/",
    "/api/v1/comms/messages/",
    "/api/v1/comms/policies/",
    "/api/v1/events/endpoints/",
    "/api/v1/events/catalogue/",
    "/api/v1/workflows/runs/",
    "/api/v1/auth/realm",
    "/api/v1/users/me/deactivate",
    "/api/v1/users/me/erase",
)


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    """The document as `/api/v1/docs` and `scripts/gen_client.sh` both read it."""
    rendered: dict[str, Any] = json.loads(json.dumps(ninja_api.get_openapi_schema()))
    return rendered


def api_paths(document: dict[str, Any]) -> list[str]:
    return sorted(document.get("paths") or {})


def first_segment(path: str) -> str:
    """The resource segment: the first part after the version prefix."""
    parts = [part for part in path.split("/") if part]
    # `api`, `v1`, then the resource. The version segment is `config/urls.py`'s
    # and an app never writes it, so it is skipped rather than allow-listed.
    return parts[2] if len(parts) > 2 else ""


def test_no_path_starts_with_an_app_label(document: dict[str, Any]) -> None:
    """The ruling itself, as a census over the whole document.

    The population is closed at both ends — every mounted path on one side,
    every installed app label on the other — so this cannot pass by listing the
    right exceptions.
    """
    labels = {config.label for config in _local_app_configs()}
    assert labels, "no local apps found — the census would pass vacuously"
    valved = allowed_label_paths()
    leaking = {
        path: first_segment(path)
        for path in api_paths(document)
        if first_segment(path) in labels and first_segment(path) not in valved
    }
    assert not leaking, (
        "these paths put an app label where a resource name belongs "
        f"(ADR api-2, house rule 32): {leaking}"
    )


def test_the_valve_is_declared_and_not_empty(document: dict[str, Any]) -> None:
    """`connections` is a coincidence, and a coincidence has to be declared.

    A1 names an app as the plural of its aggregate, so a domain app's label can
    legitimately BE its best resource name. The valve says which, and why —
    and a valve entry that no path uses is dead weight the next reader trusts.
    """
    valved = allowed_label_paths()
    assert "connections" in valved
    served = {first_segment(path) for path in api_paths(document)}
    # Dead weight is judged over the labels INSTALLED here. An entry whose app
    # is installed and serves no such path is dead weight; an entry for an app
    # this deployment does not install — an optional app left out, or an app
    # whose entry landed in a shared commit ahead of its own merge — has no path
    # to use it in THIS registry, and rule 32 never reads it (a label that is not
    # installed cannot leak). Still closed at both ends: the installed labels
    # come off the registry, the paths off the live document.
    installed = {config.label for config in _local_app_configs()}
    unused = (valved & installed) - served
    assert not unused, f"valve entries no path uses: {sorted(unused)}"
    homeless = homeless_valve_entries(valved, installed, _template_apps(), served=served)
    assert not homeless, (
        f"valve entries naming no app — not installed here, not one of the "
        f"template's apps (quality/partition.yaml) and no resource the template "
        f"serves: {homeless}"
    )


def _template_apps() -> set[str]:
    """The template's own apps, read off the partition's boundary — never typed here."""
    from quality.partition import platform_apps

    return set(platform_apps())


def homeless_valve_entries(
    valved: set[str],
    installed: set[str],
    template: set[str],
    *,
    served: set[str] | frozenset[str] = frozenset(),
) -> list[str]:
    """Entries whose label names no app this tree could ever install.

    The dead-weight judgement above reads installed apps only, so an entry for an
    app that left the tree stays silent forever: it is never installed, so never
    judged. The other half of the population is the partition's — an optional
    app a deployment disabled (`DJB_DISABLED_APPS`) is still one of the
    template's, and its entry waits for the deployment that installs it.

    **A resource the template serves is at home too.** The template mounts its
    notes, tags and imports under the `djb_` words (`/djb_notes/`,
    `/djb_tags/`, `/djb_tag_links/`, `/djb_imports/`), so a product's own
    `notes` label coincides with nothing of the template's. The clause stays
    for the words the template still serves as resources — `files`, `search` —
    where a PRODUCT that owns an app of that label coincides with the
    template's first segment: the entry is that product's valve, and it names a
    path this tree serves (`served`), not an app.
    """
    return sorted(valved - installed - template - served)


def test_a_valve_entry_for_an_app_that_is_gone_is_named() -> None:
    """The canary: a planted `zzz_gone` entry names itself; a disabled template app does not."""
    installed = {"connections", "exports"}
    template = {"connections", "exports", "search"}
    assert homeless_valve_entries({"connections", "search", "zzz_gone"}, installed, template) == [
        "zzz_gone"
    ]
    assert homeless_valve_entries({"connections", "search"}, installed, template) == []
    # A served first segment no app here is labelled — a product's coinciding
    # label — is at home; the same word the template does not serve is not.
    assert homeless_valve_entries({"notes"}, installed, template, served={"notes"}) == []
    assert homeless_valve_entries({"notes"}, installed, template, served={"tags"}) == ["notes"]


def test_every_path_ends_with_a_slash(document: dict[str, Any]) -> None:
    """One convention, no exceptions — the half the five action routes broke."""
    slashless = [path for path in api_paths(document) if not path.endswith("/")]
    assert not slashless, f"paths with no trailing slash (ADR api-2): {slashless}"


@pytest.mark.parametrize("path", RETIRED)
def test_a_retired_spelling_answers_the_apis_own_refusal(
    api: Client, owner: User, path: str
) -> None:
    """The move is observable: the old path is gone, and says so in JSON.

    404 and not 301: dual-serving the old spelling was rejected in ADR api-2,
    and a redirect is dual-serving with extra steps.
    """
    api.force_login(owner)
    response = api.get(path)
    assert response.status_code == 404, path
    assert response["Content-Type"].startswith(JSON), response["Content-Type"]
    assert response.json()["code"] == "not_found"


def test_the_moved_groups_return_the_bodies_they_returned_before(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """The paths moved and the payloads did not — pinned against the baseline.

    Read the ids and timestamps out first: they are per-run, and pinning them
    would make this a test about uuid7 rather than about the rename.
    """
    api.force_login(owner)
    volatile = {"id", "created_at", "updated_at"}
    for group, (path, expected) in BASELINE_BODIES.items():
        response = api.get(path)
        assert response.status_code == 200, (group, path, response.content)
        body = response.json()
        body["items"] = [
            {key: value for key, value in item.items() if key not in volatile}
            for item in body["items"]
        ]
        assert json.dumps(body) == expected, group


def test_the_event_types_collection_kept_its_derived_rows(
    api: Client, tenant: Tenant, owner: User
) -> None:
    """`events/catalogue` → `event-types`, same rows, new noun.

    Pinned as a property rather than as a paste: the catalogue is DERIVED from
    the installed apps' `events.py` declarations, so a literal list here would
    be a second declaration going stale the day an app adds an event.
    """
    from apps.events.events import declared_names

    declared = sorted(name for names in declared_names().values() for name in names)
    assert declared, "no app declares an event — this would pass vacuously"

    api.force_login(owner)
    # The WHOLE collection, walked page by page: one page is 50 rows by default
    # and the declarations outgrow it, so a pin over the first page alone
    # compares a prefix and fails the day an app adds an event past the page.
    response = api.get("/api/v1/event-types/")
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["count"] is None  # not asked for (ADR core-18)
    names = [row["name"] for row in body["items"]]
    while body["has_more"]:
        response = api.get("/api/v1/event-types/", {"cursor": body["next_cursor"]})
        assert response.status_code == 200, response.content
        body = response.json()
        names.extend(row["name"] for row in body["items"])
    assert names == declared
    counted = api.get("/api/v1/event-types/?include_count=true").json()
    assert counted["count"] == len(declared)


def test_no_tool_name_moved_when_the_paths_did() -> None:
    """Door parity survives by construction, and this is what proves it.

    Tool names derive from `url_name` (rule 17's check does the noun-verb →
    verb_noun turn), and no `url_name` changed here — so the registry is
    the same set it was before. A tool name that DID move would mean the paths
    and the machine door were coupled, which is the coupling ADR api-2 records
    as absent.
    """
    from config.mcp import server

    names = sorted(tool.name for tool in server._tool_manager.list_tools())
    assert names, "no MCP tools discovered — this would pass vacuously"
    assert "list_delivery_policies" not in names, (
        "a tool was renamed to follow a URL — tool names derive from url_name, "
        "not from paths (ADR api-2)"
    )
    assert "list_policies" in names
