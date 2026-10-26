"""One name per capability: the MCP tool's name IS its url_name's derivation.

ADR api-2 says url_names do not move and that house rule 17 derives the
expected MCP tool names from them; `apps.core.verbs.derive_tool_name` is that
derivation, and this census holds every bound pair to it. The pairs are found by
the PROSE identity (`apps.core.mcp.twin_of` — a tool publishing its route's
contract word for word, rule 41's pin), so the census sees a twin whose name
drifted rather than missing it.

**The recorded irregulars.** The bound pairs are twins by contract and not by
name. They are recorded below, each with where its rename lands — and the
equality is EXACT, so the list can only shrink: a fifth irregular fails by name,
and a recorded one that is renamed fails until its line is deleted.
"""

from __future__ import annotations

from typing import get_args

import pytest

from apps.accounts.models import User
from apps.core.models import Organization, Tenant
from apps.core.schemas import SHOW_WORDS, Show
from apps.core.verbs import (
    UnderivableName,
    _list_forms,
    derive_tool_name,
    plural,
    shown,
    split_url_name,
)

#: Bound pairs whose tool is the route's twin by contract and named otherwise.
#: Each is a wire change to rename (ADR api-2, Q3), so it lands with the owner of
#: the tool's module, named here; until then rule 17 accepts the contract twin.
IRREGULAR: dict[str, tuple[str, str]] = {
    "search-query": ("search_query", "the search app's tool (apps/search/mcp.py)"),
}


def _bound_pairs() -> list[tuple[str, str]]:
    """`(url_name, tool name)` for every bound operation that has an MCP twin."""
    from apps.core.api.mount import bound_operations
    from apps.core.mcp import twin_of
    from config.mcp import server

    tools = server._tool_manager.list_tools()
    pairs: list[tuple[str, str]] = []
    for _path, name, operation in bound_operations():
        twin = twin_of(operation, tools)
        if twin is not None and name:
            pairs.append((name, twin.name))
    return pairs


def test_every_tool_name_is_the_derivation() -> None:
    pairs = _bound_pairs()
    print(f"bound pairs with a twin: {len(pairs)}")
    # A floor from the printed line ("bound pairs with a twin: 136", 2026-10-01),
    # so a census that found no pairs cannot pass.
    assert len(pairs) >= 136
    drifted = {url_name: tool for url_name, tool in pairs if tool != derive_tool_name(url_name)}
    assert drifted == {url_name: tool for url_name, (tool, _) in IRREGULAR.items()}, drifted


@pytest.mark.parametrize(
    ("url_name", "noun", "verb"),
    [
        ("sso-connection-list", "sso-connection", "list"),
        ("sso-connection-create", "sso-connection", "create"),
        ("sso-connection-disable", "sso-connection", "disable"),
        ("sso-connection-update", "sso-connection", "update"),
        ("connection-oauth-callback", "connection-oauth", "callback"),
        ("connection-oauth-start", "connection-oauth", "start"),
        ("api:widget_history-list", "widget_history", "list"),
    ],
)
def test_one_splitter_the_last_hyphen(url_name: str, noun: str, verb: str) -> None:
    """The six names the two old splitters disagreed on resolve one way everywhere."""
    assert split_url_name(url_name) == (noun, verb)


@pytest.mark.parametrize("url_name", ["widgets", "-list", "widget-", "widget-Bad"])
def test_a_name_with_no_verb_is_underivable(url_name: str) -> None:
    with pytest.raises(UnderivableName):
        derive_tool_name(url_name)


@pytest.mark.parametrize(
    ("noun", "expected"),
    [
        ("widget", "widgets"),
        ("widget_entry", "widget_entries"),
        ("widget_policy", "widget_policies"),
        ("delivery", "deliveries"),
        ("day", "days"),
        ("address", "addresses"),
        ("box", "boxes"),
        ("widget_history", "widget_history"),
        # A plural stays a plural, and a singular ending in `s` is inflected —
        # the one judgement, `apps.core.lexicon.looks_plural`.
        ("dead_letters", "dead_letters"),
        ("widget_entries", "widget_entries"),
        ("status", "statuses"),
        ("order_status", "order_statuses"),
        ("analysis", "analysises"),
    ],
)
def test_one_pluralizer(noun: str, expected: str) -> None:
    assert plural(noun) == expected


@pytest.mark.parametrize(
    ("url_name", "tool"),
    [
        ("widget-list", "list_widgets"),
        ("dead_letters-list", "list_dead_letters"),
        ("widget_history-list", "list_widget_history"),
        ("widget-detail", "get_widget"),
        ("widget_merge-detail", "get_widget_merge"),
        ("widget-bulk", "bulk_widgets"),
        ("widget-archive", "archive_widget"),
        ("sso-connection-list", "list_sso_connections"),
        # The finding the one plural closed: the tool name's own shortcut said
        # `list_status` where `plural()` said `statuses` — two answers to one word.
        ("status-list", "list_statuses"),
        ("address-bulk", "bulk_addresses"),
    ],
)
def test_the_table(url_name: str, tool: str) -> None:
    assert derive_tool_name(url_name) == tool


def test_a_kinds_list_doors_are_its_name_and_its_plural() -> None:
    """The blocker's list door and rule 74's list check read the one pluralizer."""
    assert _list_forms("widget_entry") == ["widget_entry-list", "widget_entries-list"]


@pytest.mark.django_db
def test_shown_cuts_the_book(tenant: Tenant, owner: User, root_org: Organization) -> None:
    """`?show=`'s one reader: the three cuts, and an unknown word refused naming `show`.

    RED on the baseline (`apps/djb_tags/selectors.py`): an unknown word read as `live`.
    """
    from apps.core.actor import actor_for
    from apps.core.exceptions import Invalid
    from apps.example.models import Widget
    from apps.example.services import archive_widget, create_widget

    actor = actor_for(user=owner, tenant=tenant, org=root_org)
    kept = create_widget(tenant=tenant, actor=actor, name="kept")
    gone = create_widget(tenant=tenant, actor=actor, name="gone")
    archive_widget(tenant=tenant, actor=actor, widget=gone)
    book = Widget.objects.for_tenant(tenant)
    assert set(shown(book, "live")) == {kept}
    assert set(shown(book, "archived")) == {gone}
    assert set(shown(book, "all")) == {kept, gone}
    with pytest.raises(Invalid) as refused:
        shown(book, "archvied")
    assert set(refused.value.errors) == {"show"}
    assert get_args(Show) == SHOW_WORDS
