"""What the two doors PUBLISH about one response shape, compared.

**The finding.** A pydantic model has two JSON schemas, not one: a *validation*
schema saying what may be parsed into it, and a *serialization* schema saying
what comes out of it. For a `Decimal` they disagree — validation accepts a JSON
number or a numeric string, serialization is the string alone. django-ninja
renders `openapi.json` in serialization mode, because a response schema
describes a response; the MCP SDK renders `outputSchema` in validation mode,
because that is the call it also makes for arguments. So `MeasuredOut.value`
went out as `{"type": "string", "pattern": ...}` on one door and
`anyOf: [number, string]` on the other, while the docstring BOTH doors publish
(rule 41 pins them equal) promised that every number is a JSON string so no
client's float handling can change a figure — ADR core-7's rule. A JSON number
validated against one published document and not the other, and a generated
client written from the wrong one would round money through a float and be
believing its own contract while it did so.

Nothing on the wire was ever wrong, which is exactly why this needed a test:
both doors sent the string, so every wire-level parity test in the tree passed
while the two published documents said different things. `test_doors_over_the_wire`
modules (rule 46) watch the answers; this one watches the maps.

**The population is derived, never listed.** Every tool the machine door lists
publishes an `outputSchema`; each one names a root schema and carries a `$defs`
of everything it references. Every one of those names that `openapi.json` also
publishes as a component is a shape both doors describe, and the property is
asserted over all of them. A twin added next month is covered by having been
registered, not by anybody editing this file.

**What "the same thing" means here.** Full structural equality, after three
normalizations — each a difference between the two RENDERERS' conventions
rather than between the two doors' contracts, and each stated so a reader can
disagree with it:

1. **A `$ref` is compared by its target's name**, not by its pointer.
   `#/components/schemas/X` and `#/$defs/X` are the same schema kept in the two
   places the two documents keep schemas.
2. **The root `example` is dropped.** `apps.core.api.docs.add_examples` writes
   one onto every OpenAPI *component root* at document-render time and — its own
   docstring is the authority — never onto a property. The MCP document has no
   such pass. Every field-level `example` is still compared, which is where a
   real disagreement about an example would live.
3. **`default: null` is dropped.** ninja's `NinjaGenerateJsonSchema.default_schema`
   deliberately discards a null default; pydantic emits one. The field is in
   `required` on both sides either way, so the key is inert. A NON-null default
   is still compared — the clause is `default: null`, not `default`.

Everything else is compared exactly: every type, every format, every pattern,
every enum, every field, every `required` list. The blind spots the three
clauses buy are declared here rather than discovered later: a disagreement about
a *null default*, about a *component-root example*, or about which document a
`$ref` points INTO, is invisible to this test.

Driven over the wire, through the real ASGI application, for the reason
`test_mcp_arguments.py` is: what is under test is the *published* schema, and
only the wire sees what is published.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.accounts.models import User
from apps.core.models import Tenant
from apps.core.tests.test_mcp_arguments import _list_tools, _wide
from apps.core.tests.test_mcp_wall import _call_with
from config.api import api

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

#: The keys that carry a schema's own type vocabulary. A node "permits a JSON
#: number" when one of these branches says so, which is the only shape either of
#: these two generators emits for a union.
_BRANCH_KEYS = ("anyOf", "oneOf", "allOf")

#: What a JSON number is called in a `type` keyword.
_NUMERIC_TYPES = frozenset({"number", "integer"})

#: `get_widget_stats` on a tenant with no widgets, as the machine door renders
#: it — the whole `structuredContent`, spelled out. It is here to be identical
#: before and after the fix above it: the schema is the document, and the
#: document is not the wire. Both `Decimal`s arrive as strings, which is the
#: promise ADR core-7 makes and the one the published schemas now both keep.
EMPTY_WIDGET_STATS: dict[str, Any] = {
    "count": {
        "value": "0",
        "basis": {
            "formula": "live + archived",
            "inputs": {"live": "0", "archived": "0"},
        },
    }
}


def _rest_components() -> dict[str, Any]:
    """Every named schema `openapi.json` publishes, as a client reads them.

    Through `get_openapi_schema()` and a JSON round trip, which is how
    `test_contract_docs.py` and `test_response_headers.py` already name the
    published document in a test: the route serves exactly this object.
    """
    document: dict[str, Any] = json.loads(json.dumps(api.get_openapi_schema()))
    components: dict[str, Any] = document["components"]["schemas"]
    return components


def _published_by_name(listed: list[dict[str, Any]]) -> dict[str, list[tuple[str, Any]]]:
    """Every named schema the machine door publishes, and which tool published it.

    A tool's `outputSchema` is one schema with a `$defs` of everything it
    references. Both halves count: the root is a named shape too (its `title` is
    the model's name), and it is the one a `MeasuredOut`-carrying page hangs off.
    A name published by two tools is checked twice, deliberately — two tools
    disagreeing about one shape is the same finding one door over.
    """
    found: dict[str, list[tuple[str, Any]]] = {}
    for tool in listed:
        schema = tool.get("outputSchema") or {}
        title = schema.get("title")
        if isinstance(title, str):
            found.setdefault(title, []).append((tool["name"], schema))
        for name, sub in (schema.get("$defs") or {}).items():
            found.setdefault(name, []).append((tool["name"], sub))
    return found


def _normalised(node: Any, *, root: bool) -> Any:
    """One schema in the form the two renderers can honestly be compared in.

    The three clauses are the module docstring's, in order. `root` is true only
    for the top of a named schema, which is what keeps clause 2 from reaching a
    field's own example and clause 2's `$defs` from reaching a nested one.
    """
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                out[key] = value.rsplit("/", 1)[-1]
            elif key == "default" and value is None:
                continue
            elif root and key in ("example", "$defs"):
                continue
            else:
                out[key] = _normalised(value, root=False)
        return out
    if isinstance(node, list):
        return [_normalised(item, root=False) for item in node]
    return node


def _permits_a_json_number(node: Any) -> bool:
    """Whether this published node would accept a bare JSON number.

    It reads the `type` keyword and the union branches beside it and nothing
    else — which is all the property needs, because both of these generators say
    "a number is acceptable here" in exactly one way, and both were caught
    saying it. It is not a JSON Schema validator and does not pretend to be one:
    bringing one in would mean promoting `jsonschema` from a transitive
    dependency of the SDK to a declared one, which is a different rung's edit.
    """
    if not isinstance(node, dict):
        return False
    declared = node.get("type")
    if isinstance(declared, str) and declared in _NUMERIC_TYPES:
        return True
    if isinstance(declared, list) and _NUMERIC_TYPES & set(declared):
        return True
    return any(
        _permits_a_json_number(branch) for key in _BRANCH_KEYS for branch in (node.get(key) or [])
    )


def _string_typed(node: Any) -> bool:
    """A node that says a string and only a string — REST's half of the finding."""
    return isinstance(node, dict) and node.get("type") == "string" and "pattern" in node


# --- 1 · the tooth: every shape both doors publish agrees ----------------------


async def test_every_shape_both_doors_publish_says_the_same_thing(
    tenant: Tenant, owner: User
) -> None:
    """Closed — and the population is whatever is registered, not a list.

    On the tree that carried the finding this failed naming `MeasuredOut` and
    `MeasuredBasisOut`, across `get_usage` and `get_widget_stats`. Everything
    else the two doors publish already agreed exactly, which is what makes the
    equality property the honest one to assert rather than a weaker "no number
    where REST says string": the two renderings really are the same document,
    once the three renderer conventions are accounted for.
    """
    plaintext = await _wide(tenant, owner, name="schema-parity")

    listed = await _list_tools(plaintext)
    components = _rest_components()
    published = _published_by_name(listed)

    shared = sorted(name for name in published if name in components)
    assert shared, "no shape is published by both doors — the comparison has no subject"
    disagreements = [
        f"{name} (published by {tool})"
        for name in shared
        for tool, schema in published[name]
        if _normalised(schema, root=True) != _normalised(components[name], root=True)
    ]
    assert not disagreements, (
        f"these shapes are described differently by the two doors: {disagreements}"
    )


# --- 2 · the finding in its own words ------------------------------------------


async def test_a_number_the_http_door_publishes_as_a_string_is_a_string_here_too(
    tenant: Tenant, owner: User
) -> None:
    """A JSON number validates against neither published document.

    The same property the test above proves by equality, said in the vocabulary
    of the defect, over the same derived population: wherever `openapi.json`
    says a field is a patterned string — which is how it publishes every
    `Decimal`, because money that round-trips through a float stops adding up —
    the machine door's document says so too, and offers no `number` branch
    beside it for a client to take.
    """
    plaintext = await _wide(tenant, owner, name="schema-decimal")

    listed = await _list_tools(plaintext)
    components = _rest_components()
    published = _published_by_name(listed)

    watched: list[str] = []
    numeric: list[str] = []
    for name in sorted(published):
        rest = components.get(name)
        if not isinstance(rest, dict):
            continue
        for field, expected in (rest.get("properties") or {}).items():
            if not _string_typed(expected):
                continue
            for tool, schema in published[name]:
                watched.append(f"{name}.{field}")
                if _permits_a_json_number((schema.get("properties") or {}).get(field)):
                    numeric.append(f"{name}.{field} (published by {tool})")
    assert watched, "no patterned-string field is published by both doors to watch"
    assert not numeric, (
        "the machine door still accepts a JSON number where the HTTP door "
        f"publishes a string: {numeric}"
    )


# --- 3 · the document changed and the wire did not ------------------------------


async def test_the_result_on_the_wire_is_what_it_always_was(tenant: Tenant, owner: User) -> None:
    """The fix is to the map. This is the territory, unchanged.

    `outputSchema` is read at call time only to ask whether it is `None`; the
    body is built from the output model's own `model_dump(mode="json")`. So
    re-rendering the published schema cannot move a byte of it — and this test is
    the assertion of that, written to pass identically on the tree before the fix
    and the tree after it, which is how it was run.
    """
    plaintext = await _wide(tenant, owner, name="schema-wire")

    result = await _call_with(plaintext, "get_widget_stats")

    assert result.get("isError") is not True, result
    assert result["structuredContent"] == EMPTY_WIDGET_STATS, result


# --- 4 · a tool the library built no output schema for refuses the build ----------


class _NoSchema:
    """A return type pydantic cannot render — what a patched module global hands a tool."""


async def test_a_tool_returning_a_type_with_no_schema_refuses_the_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.example import mcp as example_mcp
    from config.mcp import build_server

    monkeypatch.setattr(example_mcp, "WidgetOut", _NoSchema)
    with pytest.raises(ImproperlyConfigured) as refused:
        build_server()
    said = str(refused.value)
    assert "MCP tool `archive_widget` returns `WidgetOut`" in said, said
    assert "_NoSchema" in said and "no structuredContent" in said, said


async def test_the_real_server_has_an_output_schema_on_every_tool() -> None:
    from apps.core.mcp import refuse_unstructured_results
    from config.mcp import server

    refuse_unstructured_results(server)


def _server_with_a_tool_returning(annotation: object) -> Any:
    from mcp.server import MCPServer

    def plant() -> None:
        """A planted tool; only its declared return type is under test."""

    plant.__annotations__ = {"return": annotation}
    server: MCPServer[Any] = MCPServer(name="test", version="1")
    server.add_tool(plant, name="plant")
    return server


def _content_and_stdlib_returns() -> list[object]:
    from datetime import datetime

    from mcp.server.mcpserver.utilities.types import Image
    from mcp_types import CallToolResult, TextContent

    return [
        dict,
        list,
        str,
        int,
        None,
        datetime,
        dict[str, Any],
        list[int],
        int | None,
        Image,
        TextContent,
        list[TextContent],
        CallToolResult,
    ]


@pytest.mark.parametrize("annotation", _content_and_stdlib_returns(), ids=repr)
def test_a_tool_returning_a_container_a_primitive_or_content_builds(annotation: object) -> None:
    from apps.core.mcp import refuse_unstructured_results

    refuse_unstructured_results(_server_with_a_tool_returning(annotation))


def test_a_tool_whose_return_no_longer_resolves_builds() -> None:
    from apps.core.mcp import refuse_unstructured_results

    server = _server_with_a_tool_returning(_NoSchema)
    (tool,) = server._tool_manager.list_tools()
    tool.fn.__annotations__ = {"return": "NowhereOut"}
    refuse_unstructured_results(server)


def test_a_tool_returning_a_class_of_ours_with_no_schema_refuses() -> None:
    from apps.core.mcp import refuse_unstructured_results

    with pytest.raises(ImproperlyConfigured) as refused:
        refuse_unstructured_results(_server_with_a_tool_returning(_NoSchema))
    assert "MCP tool `plant` returns" in str(refused.value), refused.value
