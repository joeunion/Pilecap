"""The wire shapes for search. Four, and each one earns its place.

One schema language across REST and MCP is why there is no second serializer
here. `SearchHitOut` is what a result is; `SearchPage` is the envelope every
list in this product answers with, plus the one thing search has to say that a
list does not — **which engine answered**. `SearchKindOut` and `SearchKindPage`
are the vocabulary: what `?kinds=` may name, published rather than guessed at.

**Nothing here carries a `Field(alias=...)`** (ADR example-3): REST renders by
field name and the MCP transport renders `structuredContent` by alias, so an
alias would make the two doors describe one hit with two key sets and every
value equal — the class of drift a value-by-value comparison is blind to.
`tests/test_doors_over_the_wire.py` compares the two key sets and is what keeps
that true.

**The document behind a hit is lean on purpose** (ADR search-2): the row's id,
the display label, and nothing else. No snapshot of the row, no relations, no
counts. A search result is a *pointer* — the client fetches the row through the
resource's own door, which is where the scoping, the field-level rules and the
freshness all already live. A fatter hit would be a second, stale copy of the
row with a different set of rules on it.
"""

from __future__ import annotations

from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.core.schemas import ListPage, example


class SearchHitOut(Schema):
    """One thing that was found: what it is, which one, and what to call it."""

    kind: str = Field(
        ...,
        json_schema_extra=example("widgets"),
        description=(
            "Which kind of thing this is. The same value you can send in `kinds` to "
            "narrow a search to it."
        ),
    )
    id: UUID = Field(
        ...,
        json_schema_extra=example("0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"),
        description=(
            "The identifier of the row itself. Fetch it from that kind's own endpoint "
            "to see the whole thing."
        ),
    )
    label: str = Field(
        ...,
        json_schema_extra=example("Left-handed sprocket"),
        description="What to show a person: the row's own display name.",
    )
    rank: float = Field(
        ...,
        json_schema_extra=example(1998.0),
        description=(
            "How good a match this is, higher first. It is comparable **within one "
            "response** and means nothing between two of them — never store it, and "
            "never show it as a score."
        ),
    )


class SearchPage(ListPage):
    """One page of results, in the envelope every list here uses (ADR core-18).

    `items`, `has_more`, `next_cursor` and `count` are the standard envelope:
    walk with `?cursor=`, stop when `has_more` is false, and `count` is `null`
    unless you sent `?include_count=true`. The cursor is opaque — it names a
    position in *this* ranked result set, so it is not interchangeable with a
    list endpoint's cursor and the API says so rather than misreading one.

    `engine` is search's own field and it is on the wire on purpose. Search
    degrades rather than failing: when the index is unreachable the product
    answers from Postgres instead — slower, plainer, and still correctly scoped
    — and a caller that wants to say "results may be incomplete" can. A caller
    that does not care ignores it. What neither has to do is guess.
    """

    items: list[SearchHitOut] = Field(
        ...,
        json_schema_extra=example(
            [
                {
                    "kind": "widgets",
                    "id": "0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b",
                    "label": "Left-handed sprocket",
                    "rank": 1998.0,
                }
            ]
        ),
        description="The matches, best first.",
    )
    engine: str = Field(
        ...,
        json_schema_extra=example("meili"),
        description=(
            "Which engine answered: `meili` normally, `postgres` while the index is "
            "unreachable. The results are scoped identically either way. A page that "
            "was answered without asking any engine — because you can see nothing "
            "here — still names the engine this deployment searches with, so that a "
            "page you are not entitled to and a page that matched nothing cannot be "
            "told apart."
        ),
    )


class SearchKindOut(Schema):
    """One kind of thing this product can search, and the part of it that owns them.

    Derived from the registry at request time, so it is complete and current for
    the build answering — never a hand-kept list. The same for every customer:
    it says what the PRODUCT can find, not what you happen to have.
    """

    kind: str = Field(
        ...,
        json_schema_extra=example("widgets"),
        description=(
            "The value to send in `kinds` to narrow a search to this, and the value "
            "`kind` carries on every hit of it."
        ),
    )
    app: str = Field(
        ...,
        json_schema_extra=example("example"),
        description="Which part of the product owns these — where you fetch one in full.",
    )


class SearchKindPage(ListPage):
    """A page of the vocabulary, in the list envelope both doors use."""

    items: list[SearchKindOut] = Field(
        ...,
        json_schema_extra=example([{"kind": "widgets", "app": "example"}]),
        description="The kinds, in alphabetical order.",
    )
