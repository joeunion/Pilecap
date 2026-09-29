"""A refusal's remedy is ONE declaration: the API document publishes what the wire sends.

A family refusal points at the refused row's own door (`route:widget-archive`),
which the registry cannot spell for every noun — so it registers the remedy with
a `<noun>` slot, the raise site fills it from its `noun`, and the document fills
it from the operation's kind. Before, the registry said `self:reread` while the
class sent the route, and the published 409 described a remedy nobody received.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from apps.core.exceptions import NOUN_SLOT, Archived, Merged, MergeSurvivor, wire_refusal
from config.api import api

DELETE = ("/api/v1/widgets/{widget_id}/", "delete")
REMEDY_LINE = re.compile(r"^- (?P<label>.*) \(`(?P<destination>.*)`\)$", re.M)


@pytest.fixture(scope="module")
def document() -> dict[str, Any]:
    schema: dict[str, Any] = api.get_openapi_schema()
    return schema


def _published(
    document: dict[str, Any], path: str, method: str, code: str
) -> list[tuple[str, str]]:
    responses = document["paths"][path][method]["responses"]
    conflict = responses.get(409) or responses["409"]
    assert code in conflict["x-refusal-codes"], (code, conflict["x-refusal-codes"])
    (block,) = [b for b in conflict["description"].split("\n\n") if b.startswith(f"**`{code}`**")]
    return [(m["label"], m["destination"]) for m in REMEDY_LINE.finditer(block)]


@pytest.mark.parametrize(
    ("code", "raised"),
    [
        ("merge_survivor", MergeSurvivor(noun="widget")),
        ("merged", Merged(noun="widget", merged_into="00000000-0000-0000-0000-000000000000")),
        ("archived", Archived(noun="widget")),
    ],
    ids=["merge_survivor", "merged", "archived"],
)
def test_the_published_remedy_is_the_one_the_wire_sends(
    document: dict[str, Any], code: str, raised: Any
) -> None:
    sent = [(r["label"], r["destination"]) for r in wire_refusal(raised)["remedies"]]
    assert _published(document, *DELETE, code) == sent


def test_no_operation_publishes_an_unfilled_noun_slot(document: dict[str, Any]) -> None:
    assert NOUN_SLOT not in json.dumps(document["paths"])


def test_a_route_named_for_something_else_fills_the_slot_from_its_path(
    document: dict[str, Any],
) -> None:
    """`version-add` names no kind; its `{file_id}` does, and a file's archive is the refusal."""
    sent = [(r["label"], r["destination"]) for r in wire_refusal(Archived(noun="file"))["remedies"]]
    assert _published(document, "/api/v1/files/{file_id}/versions/", "post", "archived") == sent
