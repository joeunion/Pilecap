"""The fenced module's own claims: the namespace, the filter, and the sentinel.

Everything here is about what `engine.py` says to somebody else's server. The
tests that matter most are the boring ones — a derived prefix and a rendered
filter string — because those two values are the whole of "two checkouts never
collide" and "a client can never widen a scope", and both are the kind of thing
that is right until somebody makes a small edit.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from apps.search import engine as engine_module
from apps.search.engine import (
    DECLARATION_DOCUMENT_ID,
    index_name,
    index_prefix,
    scope_expression,
    staging_index_name,
)
from apps.search.types import ScopeFilter


def test_two_checkouts_get_disjoint_index_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Criterion 7's derivation half. The invariant in one line.

    Two checkouts that cannot share a Postgres database cannot share a
    Meilisearch namespace, because both are derived from the same name. This is
    what makes a parallel gate safe in Meili exactly as it already is in
    Postgres — and it is why there is deliberately no `MEILI_INDEX_PREFIX` to
    pin.
    """
    monkeypatch.setenv("DATABASE_NAME", "djb_worktree_alpha_11112222")
    alpha = index_prefix()
    monkeypatch.setenv("DATABASE_NAME", "djb_worktree_beta_33334444")
    beta = index_prefix()

    assert alpha != beta
    assert index_name("widgets").startswith(beta)
    assert staging_index_name("widgets").startswith(index_name("widgets"))


def test_an_exotic_database_name_still_makes_a_legal_uid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A product may pin any `DATABASE_NAME`; Meili accepts a narrower alphabet.

    Sanitising silently would be the trap: two different names could sanitise to
    one prefix and two deployments would share a namespace without anybody
    seeing it. So the hash of the ORIGINAL is appended whenever sanitising
    changed anything, and the two stay disjoint.
    """
    monkeypatch.setenv("DATABASE_NAME", "prod.eu-west-1")
    first = index_prefix()
    monkeypatch.setenv("DATABASE_NAME", "prod_eu-west-1")
    second = index_prefix()

    assert first != second
    assert all(character.isalnum() or character in "_-" for character in first)


def test_an_org_scoped_filter_names_the_tenant_and_the_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The filter's exact shape, rendered — the string the server actually gets."""
    tenant = uuid4()
    first, second = uuid4(), uuid4()
    rendered = scope_expression(ScopeFilter(tenant_id=tenant, org_ids=(first, second)))

    assert rendered == f'tenant_id = "{tenant}" AND org_id IN ["{first}", "{second}"]'


def test_a_tenant_scoped_filter_names_only_the_tenant() -> None:
    """`None` org ids means the kind has no organization, not that the hat failed."""
    tenant = uuid4()
    assert scope_expression(ScopeFilter(tenant_id=tenant)) == f'tenant_id = "{tenant}"'


def test_a_hostile_value_cannot_reach_the_filter_expression() -> None:
    """The smuggling defence, stated as a type rather than as an escaping routine.

    `scope_expression` renders through `UUID(...)`, so a value that is not a UUID
    does not get escaped — it does not get *rendered*. There is no quoting bug to
    find because there is no string interpolation of caller-supplied text at all.
    """
    with pytest.raises(ValueError):
        scope_expression(ScopeFilter(tenant_id='" OR tenant_id != "x'))  # type: ignore[arg-type]


def test_the_declaration_sentinel_cannot_be_a_row_id() -> None:
    """The digest lives on a document id no primary key can collide with.

    It is also unreachable through the chokepoint by construction: it carries no
    `tenant_id`, and every query this product makes filters on one. That is an
    argument about shape rather than about anybody remembering to exclude it.
    """
    with pytest.raises(ValueError):
        _ = uuid4().__class__(DECLARATION_DOCUMENT_ID)


@pytest.mark.django_db(transaction=True)
def test_the_real_engine_round_trips_settings_a_document_and_a_swap(live_label: str) -> None:
    """Against the container on `MEILI_URL`: create, stamp, search, swap, drop.

    The recorded tests elsewhere all rest on this one being true. Each step is
    asserted rather than merely executed, because "no exception" is what a
    round-trip test says when the client has quietly started swallowing something.
    """
    if not os.environ.get("MEILI_URL"):
        pytest.skip("no MEILI_URL — the search organ is not configured for this checkout")

    from apps.search.types import Searchable

    from .conftest import WIDGETS

    declaration = Searchable(
        model=WIDGETS.model, label=live_label, fields=[("name", "A")], display="name"
    )
    live = engine_module.engine()
    tenant = uuid4()
    org = uuid4()

    try:
        assert live.state(label=live_label).exists is False

        live.apply_settings(declaration=declaration, digest="a-digest-we-chose")
        state = live.state(label=live_label)
        assert state.exists is True
        assert state.digest == "a-digest-we-chose"

        row = uuid4()
        live.upsert(
            label=live_label,
            documents=[
                {
                    "id": str(row),
                    "tenant_id": str(tenant),
                    "org_id": str(org),
                    "label": "Left-handed sprocket",
                    "name": "Left-handed sprocket",
                }
            ],
        )

        mine = live.query(
            kinds=[live_label],
            q="sprocket",
            scope=ScopeFilter(tenant_id=tenant, org_ids=(org,)),
            offset=0,
            limit=10,
        )
        assert [hit.id for hit in mine.hits] == [row]
        assert mine.total == 1
        assert mine.engine == "meili"

        # The anti-oracle, measured rather than argued: another tenant's filter
        # finds nothing AND counts nothing, for a term that is definitely there.
        theirs = live.query(
            kinds=[live_label],
            q="sprocket",
            scope=ScopeFilter(tenant_id=uuid4(), org_ids=(uuid4(),)),
            offset=0,
            limit=10,
        )
        assert theirs.hits == ()
        assert theirs.total == 0

        # And a hat beside the row's own, inside the SAME tenant.
        sibling = live.query(
            kinds=[live_label],
            q="sprocket",
            scope=ScopeFilter(tenant_id=tenant, org_ids=(uuid4(),)),
            offset=0,
            limit=10,
        )
        assert sibling.hits == ()
        assert sibling.total == 0

        # The sentinel is in the index and is not reachable through any of them.
        assert all(str(hit.id) != DECLARATION_DOCUMENT_ID for hit in mine.hits)

        staging = live.begin_rebuild(declaration=declaration, digest="a-second-digest")
        live.stage(
            staging=staging,
            documents=[
                {
                    "id": str(uuid4()),
                    "tenant_id": str(tenant),
                    "org_id": str(org),
                    "label": "Right-handed sprocket",
                    "name": "Right-handed sprocket",
                }
            ],
        )
        live.swap(label=live_label, staging=staging)

        after = live.state(label=live_label)
        assert after.digest == "a-second-digest", "the swap did not make staging live"
    finally:
        # Both, and each in its own `try` — because `swap` leaves the STAGING
        # uid holding the old content rather than deleting it, and a cleanup
        # whose first drop raised would leak the second. A leaked index outlives
        # the checkout that made it: `scripts/sweep.sh` cannot see a Meili index
        # at all yet, so this `finally` is the whole of the tidying.
        for uid in (index_name(live_label), staging_index_name(live_label)):
            try:
                live.drop_index(uid=uid)
            except Exception:  # noqa: BLE001 - a cleanup that raises hides the real failure
                pass
