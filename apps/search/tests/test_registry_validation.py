"""The boot refusal: every way a declaration can be a promise nobody kept.

**Why these refusals are worth a module of their own.** Every defect here
is silent by construction. A `Searchable` naming a field the model does not have
builds a document whose text is `None` — the index exists, the queries succeed,
and nothing is ever found. A `refresh_on` name nobody declares is a subscription
that never fires: the startup reconcile writes the first document and then the
kind is frozen at whatever the rows said on the day of the deploy. A weight
outside Postgres's four is inert on Meilisearch and an error on the degradation
engine, so it ships green and breaks on the one day the circuit is already open.

None of the three raises anything where it is written, and none of them shows up
in a result. So they are refused where a wrong declaration can still stop
something: `SearchConfig.ready()`, which runs in the web server, the Temporal
worker, `manage.py` and pytest alike (the tier
`apps.usage.meters.validate_declared_meters` and `core.lifecycle.Lifecycle`
already set — the strongest tier).

**Nothing in this repository declares a `Searchable` yet** (`apps/example`
is the one that adopts it), so every declaration here is planted through the registry's one
discovery seam — which is also the honest way to test a refusal: the fixture
hands `validate()` exactly the shape a real `apps/<x>/search.py` would have
produced, and the last test drives the whole boot path rather than the function.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ImproperlyConfigured

from apps.core.models import Organization
from apps.example.events import WIDGET_CREATED, WIDGET_UPDATED
from apps.example.models import Widget
from apps.search import registry
from apps.search.types import Searchable

pytestmark = pytest.mark.django_db


def plant(**overrides: object) -> Searchable:
    """A declaration that is legal in every respect except the one under test.

    One helper rather than a literal per test, because the point of each of
    these is the *single* thing that is wrong: a test that spelled a whole
    `Searchable` out could pass for the wrong reason the day a second field of
    it stopped validating.
    """
    fields: dict[str, object] = {
        "model": Widget,
        "label": "widgets",
        "fields": [("name", "A")],
        "refresh_on": (WIDGET_CREATED, WIDGET_UPDATED),
        "display": "name",
    }
    fields.update(overrides)
    return Searchable(**fields)  # type: ignore[arg-type]


def test_a_correct_declaration_is_accepted_and_handed_back() -> None:
    """The negative, first: everything below has to be silent about this one.

    A refusal nobody ever sees pass is a refusal that could be refusing
    everything.
    """
    declared = plant()
    assert registry.validate([declared]) == (declared,)


# --- the three shapes ADR search-2 names --------------------------------------


def test_a_field_the_model_does_not_have_refuses_at_boot() -> None:
    """Shape one. The columns it DOES have are in the message, on purpose.

    A refusal that says "no such field" and stops has made somebody open two
    files. This one hands them the answer, because the overwhelmingly likely
    cause is a typo or a renamed column.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(fields=[("name", "A"), ("descriptoin", "B")])])

    said = str(refusal.value)
    assert "'descriptoin'" in said
    assert "which the model does not have" in said
    assert "notes" in said, "the available columns are what makes this fixable in one read"
    assert "nothing is ever found" in said


def test_a_weight_outside_the_four_refuses_at_boot() -> None:
    """Shape two. The letters are Postgres's, and that is the whole reason."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(fields=[("name", "E")])])

    said = str(refusal.value)
    assert "'E'" in said
    assert "A, B, C, D" in said
    assert "setweight" in said, "a reader has to learn WHERE the letters come from"


def test_a_refresh_on_name_no_app_declares_refuses_at_boot() -> None:
    """Shape three, and the one that survives longest in the wild if it ships.

    A missing field breaks the day somebody searches. This one breaks nothing
    visible at all: the reconcile builds the index, the documents are correct,
    and then the kind never moves again.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(refresh_on=(WIDGET_CREATED, "example.widget.renamed"))])

    said = str(refusal.value)
    assert "'example.widget.renamed'" in said
    assert "apps/example/events.py does not declare" in said
    assert "silently never fires" in said


def test_an_event_naming_an_app_that_is_not_installed_refuses_separately() -> None:
    """The other half of shape three: a real grammar, a name nobody publishes.

    Two messages rather than one, because the fixes are different — install the
    app, or fix the name — and a refusal that cannot tell them apart makes the
    reader do the diagnosis it was supposed to have done.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(refresh_on=("invoices.invoice.issued",))])

    said = str(refusal.value)
    assert "no installed app is labelled 'invoices'" in said


# --- the shapes the ADR's own list carries beside those three -----------------


def test_a_model_with_no_tenant_refuses_at_boot() -> None:
    """ADR search-2's fourth: neither `TenantScopedModel` nor `OrgScopedModel`.

    The sharpest of the five, and the one that is a security property rather
    than a usability one: `document_for` stamps `tenant_id`, the injected filter
    excludes on it, and a document with no tenant is one no filter can exclude.
    """
    from apps.accounts.models import User

    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(model=User, fields=[("email", "A")], refresh_on=())])

    said = str(refusal.value)
    assert "carries no tenant" in said
    assert "probing oracle" in said


def test_two_kinds_may_not_share_one_label() -> None:
    """One label is one index, so two of them is two shapes in one place.

    Not in the ADR's list and added here because the failure is worse than any
    of them: each kind's rebuild silently empties the other, and the tell is
    "search keeps losing things" with no error anywhere.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate(
            [
                plant(),
                plant(model=Organization, refresh_on=(), fields=[("name", "A")]),
            ]
        )

    said = str(refusal.value)
    assert "already declares" in said
    assert "One label is one index" in said


@pytest.mark.parametrize("label", ["Widgets", "widget kinds", "widgets!", "", "_widgets"])
def test_a_label_that_cannot_be_an_index_name_refuses_at_boot(label: str) -> None:
    """It becomes a Meilisearch index uid AND the value `?kinds=` names.

    Both halves are public: one is a 400 from the server at the first write of a
    fresh checkout, the other is a vocabulary a client has to be able to type.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(label=label)])
    assert "cannot be an index name" in str(refusal.value)


def test_a_dotted_field_refuses_because_a_generated_column_cannot_walk_one() -> None:
    """`display` may be dotted; a searchable field may not, and they differ.

    The same `fields` list builds the degradation engine's `search_vector`
    generated column, and a generated column may only reference its own
    table. Allowing the dot here would make the two engines search different
    text — which is exactly the failure the one-declaration design exists to
    prevent, arriving on the day the circuit opens.
    """
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(fields=[("owner.email", "A")])])

    said = str(refusal.value)
    assert "not a walk across a relation" in said
    assert "`display` may be dotted" in said


def test_a_kind_with_no_fields_refuses_at_boot() -> None:
    """An index that answers every query with nothing is not a kind."""
    with pytest.raises(ImproperlyConfigured) as refusal:
        registry.validate([plant(fields=[])])
    assert "declares no fields" in str(refusal.value)


# --- and the boot itself ------------------------------------------------------


def test_the_refusal_is_the_BOOT_refusal_and_not_merely_a_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SearchConfig.ready()` is where a wrong declaration stops the process.

    Every test above calls `validate()` directly, which proves the grammar and
    proves nothing at all about *when* it is applied — a validator nobody calls
    is the poller-that-was-never-built, one vocabulary along. So this one drives
    the real `ready()` of the real `AppConfig` with the declarations planted at
    the discovery seam, which is the exact path a deployment takes.

    It also proves the ORDER: the bridge must NOT be registered when the
    declarations are wrong. A deployment that refused its declarations and still
    installed a working tap would index against a registry it had just called a
    lie.
    """
    from apps.core import bridge
    from apps.events.activities import SEARCH_INDEX_EVENT

    config = django_apps.get_app_config("search")
    monkeypatch.setattr(registry, "declarations", lambda: (plant(fields=[("nope", "A")]),))

    saved = bridge.registered()
    try:
        bridge.clear()
        for name, fn in saved.items():
            if name != SEARCH_INDEX_EVENT:
                bridge.register(name, fn)

        with pytest.raises(ImproperlyConfigured) as refusal:
            config.ready()

        assert "'nope'" in str(refusal.value)
        assert bridge.find(SEARCH_INDEX_EVENT) is None, (
            "the tap was installed by a boot that had already refused its declarations"
        )
    finally:
        # The registry is filled once per process, at startup; put back exactly
        # what was there rather than leaving the next test a half-booted app.
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)


def test_a_good_boot_registers_the_tap_under_the_name_the_spine_looks_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Criterion 3: the name registers from `AppConfig.ready()` and nowhere else.

    And it registers under the constant `apps/events/activities.py` owns rather
    than under a string spelled twice — the constant is imported, so there is
    one spelling and a typo is impossible rather than merely unlikely.
    """
    from apps.core import bridge
    from apps.events.activities import SEARCH_INDEX_EVENT
    from apps.search.activities import index_event

    config = django_apps.get_app_config("search")
    monkeypatch.setattr(registry, "declarations", lambda: (plant(),))

    saved = bridge.registered()
    try:
        bridge.clear()
        assert bridge.find(SEARCH_INDEX_EVENT) is None
        config.ready()
        assert bridge.find(SEARCH_INDEX_EVENT) is index_event
    finally:
        bridge.clear()
        for name, fn in saved.items():
            bridge.register(name, fn)


def test_the_registrant_has_the_shape_the_spine_calls_it_with() -> None:
    """The bridge shape, pinned on the REGISTRANT's side (criterion 3).

    `core.bridge.SHAPES` cannot hold this one: ADR search-2 keeps the name out
    of `apps/core` because no ingredient may touch that app, so the pinning has
    to live here instead. What it pins is what drifts — the parameter names,
    that they are keyword-only, and that something boolean comes back — because
    `apps/events/activities.py::index_search` calls it by those names across a
    registry that cannot type-check anything.
    """
    import inspect

    from apps.search.activities import index_event

    signature = inspect.signature(index_event)
    assert list(signature.parameters) == ["tenant_id", "event"]
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    ), "the spine calls this with keywords; a positional parameter is a caller it can break"
    assert signature.return_annotation == "bool"
