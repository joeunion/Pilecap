"""The census is DERIVED, and the pin is what makes it fail.

Two claims and they are different claims.

**Derived** is a property of the code: `dispositions()` is
`(concrete registry models carrying a tenant) minus the declared exclusions`,
computed, so a scoped model added tomorrow is in the archive with no edit to
`census.py`. `test_the_census_is_the_registry_minus_the_exclusions` asserts that
identity directly and it cannot go stale.

**Pinned** is a property of THIS TREE: the twenty-one labels below are what the
census answers today, written out by hand, so that a model appearing or
disappearing from a customer's archive is a diff a reviewer reads rather than a
silent widening. The pin is the half that can fail, and
`test_a_planted_scoped_model_breaks_the_pin` proves it can — planted twice,
through the parameterised population and through the REAL app registry, because
those answer different questions: one proves the assertion is live, the other
proves the population is really the registry and not a copy of it.

The derived half without the pin would be a census nobody notices growing. The
pin without the derived half would be `EXPECTED` doing the work, which is the
hand-list this whole module exists not to be.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import pytest
from django.apps import apps as django_apps
from django.db import models

from apps.core.models import BaseModel, OrgScopedModel, TenantScopedModel
from apps.exports import census
from apps.exports.census import (
    EXCLUSIONS,
    MIN_REASON,
    dispositions,
    encrypted_fields,
    exclusions,
    plan,
    scoped_models,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Iterator

#: **The pin.** Every model whose rows go into a tenant-wide archive on this
#: tree, written out rather than derived from the thing it pins — a pin computed
#: from `dispositions()` could not fail.
#:
#: Twenty-three, out of twenty-six models that carry a tenant and forty-one
#: concrete models in the deployment. The review's figure was 38 concrete; the
#: delta is three — `exports.Export` itself, added later, and which is
#: census-INCLUDED (an export contains the tenant's own export records, and that
#: does not recurse, because what a row carries is the artifact's key and never
#: the artifact), `usage.UsageEntry`, added later, and `files.StoredFile` +
#: `files.FileVersion`, added later.
#: the artifact), `usage.UsageEntry`, added later, and
#: `comms.MessageEngagement`, added later.
EXPECTED: frozenset[str] = frozenset(
    {
        "accounts.SsoConnection",
        "accounts.SsoDomain",
        "accounts.SsoIdentity",
        "comms.ChannelPreference",
        "comms.DeliveryPolicy",
        # The census is DERIVED, so `comms.Device` joined the archive
        # the moment the model existed; this line is the diff the pin exists to
        # make somebody read. It BELONGS in a tenant's archive: the push address
        # book is that customer's own record of which of their contacts can be
        # notified and on what, it is org-scoped so a subtree export narrows it
        # correctly, and a customer leaving with a contact book whose push half
        # was silently dropped would have less than the product showed them.
        #
        # WHAT TRAVELS IS THE ROW AND NOT THE CREDENTIAL. `push_token` is an
        # encrypted column, so the field-level fence below drops it from every
        # archive by name — which is exactly right here and is not a compromise:
        # a registration token is a live capability to reach somebody's lock
        # screen, it is minted by the platform and not by us, and it is worthless
        # to a customer moving elsewhere because their new gateway will mint its
        # own. What they get is which devices existed, on what platform, under
        # what label, and when each was retired.
        "comms.Device",
        "comms.Message",
        # The census is DERIVED, so `comms.MessageEngagement` joined
        # the archive the moment the model existed; this line is the diff the pin
        # exists to make somebody read. It BELONGS in a tenant's archive: an
        # engagement row is a fact about that tenant's own correspondence with
        # its own contacts, it is org-scoped so a subtree export narrows it
        # correctly, and a customer leaving with a message log whose opens and
        # clicks were silently dropped would have half of what the product told
        # them they had.
        "comms.MessageEngagement",
        "comms.MessageTemplate",
        "comms.Recipient",
        "comms.SuppressionSurge",
        "connections.Connection",
        "connections.InboundWebhook",
        "core.AuditEntry",
        # Three lines — `core.Grant` here, `core.Role` and `core.RolePermission`
        # below — and they are the diff the pin exists to make somebody read. The
        # census is DERIVED, so all three joined the archive the moment the models
        # existed. They BELONG in a tenant's archive: a tenant's own roles, its
        # deltas on the collections of the declared ones, and the per-person
        # allows and withholds are that customer's own configuration — who they
        # decided may do what, in their own words. An archive that carried the
        # people and not the authority they held would describe a permission
        # system the customer could not reconstruct anywhere else.
        #
        # NONE OF THE THREE CARRIES AN `organization`, so a subtree export SKIPS
        # them rather than narrowing them, and that is right rather than a gap. A
        # role and its collection belong to the whole customer; a grant's place in
        # the tree is its membership's and not a column of its own. There is no
        # honest way to cut any of them to one branch, and the skip says so in the
        # plan, which is what keeps it distinguishable from a tenant that never
        # had the table.
        "core.Grant",
        "core.Invitation",
        "core.Membership",
        "core.Organization",
        # The other two of the three above: the roles one tenant made for itself,
        # and its include/exclude deltas on what a role holds.
        "core.Role",
        "core.RolePermission",
        "events.WebhookEndpoint",
        "example.Widget",
        "example.WidgetEntry",
        "example.WidgetPolicy",
        "exports.Export",
        # Two lines, and they are the diff the pin exists to make
        # somebody read. Both BELONG in a tenant's archive and for different
        # reasons. `StoredFile` is the customer's own filing cabinet — what they
        # called each document, what it was for, who filed it, whether it was
        # archived — and a portability archive that listed no documents would be
        # the largest omission this app could have. `FileVersion` is the history
        # that makes a document's identity mean anything: which version was
        # current when, what its digest was, and how big it was — the fields an
        # export manifest, an audit row and an already-issued presigned URL all
        # cited, which is exactly why ADR files-2 refuses to let a replace rewrite
        # them in place.
        #
        # WHAT TRAVELS IS METADATA, AND THE BYTES DO NOT. Neither row carries
        # object content, and `key` is a column like any other here — the archive
        # is a copy of the tenant's ROWS. Handing a customer the objects
        # themselves is `store_bytes` + `issue_download_url` on the files app,
        # and the export artifact is itself one of those.
        "files.FileVersion",
        "files.StoredFile",
        # The census is DERIVED, so `usage.UsageEntry` joined the
        # archive the moment the model existed; this line is the diff the pin
        # exists to make somebody read. It BELONGS in a tenant's archive: the
        # ledger is that customer's own record of what they consumed, it is
        # org-scoped so a subtree export narrows it correctly, and it holds no
        # third party's data — a customer leaving with an invoice they cannot
        # reconstruct is the portability gap this app exists to close.
        "usage.UsageEntry",
        "workflows.WorkflowRun",
    }
)

#: The three tables a tenant's archive does not carry, by label. Pinned beside
#: the census for the same reason: a table leaving somebody's archive is a
#: decision, and it should be a diff.
EXPECTED_EXCLUSIONS: frozenset[str] = frozenset(
    {"accounts.ApiToken", "core.IdempotencyRecord", "events.Event"}
)

#: The encrypted columns rule 15 keeps out of every archive, on this tree. Four
#: live members, so the field-level exclusion is not a mechanism with nothing in
#: it — a fence nobody can walk into is a fence nobody maintains.
EXPECTED_ENCRYPTED: frozenset[tuple[str, str]] = frozenset(
    {
        ("accounts.SsoConnection", "metadata"),
        ("connections.Connection", "credentials"),
        # The first encrypted column on a table the archive INCLUDES,
        # which is what makes the field-level fence do visible work rather than
        # merely exist: `comms.Device` travels and `push_token` does not, so the
        # archive carries the row without carrying the capability.
        ("comms.Device", "push_token"),
        ("events.WebhookEndpoint", "secret"),
    }
)


@contextmanager
def planted_in_the_registry(name: str) -> Iterator[type[models.Model]]:
    """A real scoped model, in the real app registry, for the length of a test.

    Defining the class registers it — that is Django's own mechanism and it is
    the same one a builder uses when they add a table — so this is the honest
    plant rather than a stand-in. It is removed again in `finally`, and the
    registry's cache is cleared both ways, so nothing after this test sees it.
    """
    model = type(
        name,
        (OrgScopedModel,),
        {
            "__module__": __name__,
            "Meta": type("Meta", (OrgScopedModel.Meta,), {"app_label": "exports"}),
        },
    )
    try:
        yield model
    finally:
        django_apps.all_models["exports"].pop(name.lower(), None)
        django_apps.clear_cache()


class _PlantedScoped(TenantScopedModel):
    """A scoped model that exists only as a value handed to `dispositions()`.

    Abstract on purpose: it is never registered, so it can be passed as part of
    a `source` population without touching the deployment. The pair with
    `planted_in_the_registry` is the point — a parameterised plant proves the
    assertion is live, a registry plant proves the population is the registry.
    """

    class Meta(TenantScopedModel.Meta):
        abstract = True


# --- the derived half ----------------------------------------------------------


def test_the_census_is_the_registry_minus_the_exclusions() -> None:
    """The identity, asserted directly. This is what "derived" means."""
    scoped = {str(model._meta.label) for model in scoped_models()}
    assert set(dispositions()) == scoped - set(exclusions())


def test_the_population_is_every_model_carrying_a_tenant() -> None:
    """And nothing else — no list, no `issubclass`, one question about a column."""
    registry = {
        str(model._meta.label)
        for model in django_apps.get_models()
        if not model._meta.proxy
        and model._meta.managed
        and any(field.name == "tenant" for field in model._meta.concrete_fields)
    }
    assert {str(model._meta.label) for model in scoped_models()} == registry


# --- the pin, and the red that proves it can fail -------------------------------


def platform_only(labels: Iterable[str]) -> set[str]:
    """The labels this TREE owns — the lockfile's apps, and nothing else.

    Disposition D4 of the partition design (`docs/product/partition-closure.md`
    §5). The pin below exists to pin *the platform's own tree* — its own
    docstring has always said "Pinned is a property of THIS TREE" — so its
    quantifier gains the boundary the prose always meant. Without it a cloned
    product's first scoped model breaks a platform pin that was never about the
    product's models, and the product cannot clear the red without editing a
    platform test.

    Read from `quality/partition.yaml`, the same written-down record the gate's
    partition reads, rather than from a second list here: two lists of platform
    apps is exactly the drift the whole lockfile idea exists to avoid.

    **The derived-side tests stay global on purpose** —
    `test_the_census_is_the_registry_minus_the_exclusions` and
    `test_the_population_is_every_model_carrying_a_tenant` quantify over the
    whole registry, because a product model MUST join the archive census, and
    does, derived. Only the hand-pinned set is scoped.
    """
    from quality.partition import platform_apps

    apps = set(platform_apps())
    return {label for label in labels if str(label).split(".", 1)[0] in apps}


def not_a_product_model(models_: Iterable[Any]) -> list[Any]:
    """Every model except one a PRODUCT app declared. D4, over the whole registry.

    `platform_only` filters labels this tree owns; this filters model objects the
    same way but keeps third-party tables — allauth's, django's — because those
    arrive from `INSTALLED_APPS`, which `config/settings/` decides and the
    partition holds in-closure (class C3). What a clone adds is an `apps/<x>/`
    the lockfile does not name, and that is the only thing this drops.
    """
    from django.apps import apps as registry

    from quality.partition import platform_apps

    named = set(platform_apps())
    product = {
        str(config.label)
        for config in registry.get_app_configs()
        if config.name.startswith("apps.") and str(config.label) not in named
    }
    return [model for model in models_ if str(model._meta.app_label) not in product]


def test_the_census_at_this_tree_is_pinned() -> None:
    """Twenty-one models. A twenty-second, or a twentieth, is a diff somebody reads."""
    assert platform_only(dispositions()) == EXPECTED
    assert platform_only(exclusions()) == EXPECTED_EXCLUSIONS


def test_a_planted_scoped_model_breaks_the_pin_through_the_population() -> None:
    """A scoped model the census has never heard of shows up in the answer.

    The parameterised half. It proves the assertion above is live rather than
    vacuous: hand `dispositions()` one more scoped model and the pinned set is
    no longer the answer, and the failure NAMES the model.
    """
    widened = dispositions(source=[*django_apps.get_models(), _PlantedScoped])

    assert platform_only(widened) - EXPECTED == {"exports._PlantedScoped"}
    assert platform_only(widened) != EXPECTED


def test_a_planted_scoped_model_breaks_the_pin_through_the_real_registry() -> None:
    """The same, with the model really registered — the way a builder adds one.

    The registry half. It proves the population is Django's registry and not a
    snapshot of it: nothing in `census.py` is told about this class, and it is
    in the archive anyway, which is exactly the property that makes the table
    somebody adds on Thursday travel.
    """
    with planted_in_the_registry("PlantedExportable"):
        answer = set(dispositions())

    assert "exports.PlantedExportable" in answer
    assert platform_only(answer) != EXPECTED
    # And it is gone again, so no test after this one inherits a phantom table.
    assert platform_only(dispositions()) == EXPECTED


# --- a bare exclusion refuses ---------------------------------------------------


def test_a_bare_exclusion_on_a_model_refuses() -> None:
    """`export_excluded = True` with no reason is an off switch, and it is refused."""
    with planted_in_the_registry("BarelyExcluded") as planted:
        planted.export_excluded = True  # type: ignore[attr-defined]  # the plant's whole point
        with pytest.raises(ValueError, match="export_excluded_reason"):
            dispositions()


def test_an_exclusion_whose_reason_is_a_word_refuses() -> None:
    """A reason nobody can disagree with is not a reason."""
    with planted_in_the_registry("ThinlyExcluded") as planted:
        planted.export_excluded = True  # type: ignore[attr-defined]  # the plant's whole point
        planted.export_excluded_reason = "no"  # type: ignore[attr-defined]  # ditto
        with pytest.raises(ValueError, match="at least"):
            dispositions()
    assert MIN_REASON >= 12


def test_an_exclusion_naming_a_model_that_is_not_there_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale entry reads as a considered decision about something absent.

    Refused rather than ignored, because the quiet failure is worse than the
    loud one: an entry for a table nobody has any more would silently start
    applying to whatever next takes the name.
    """
    monkeypatch.setitem(census.EXCLUSIONS, "example.NoSuchThing", "a" * 40)
    with pytest.raises(ValueError, match="not in the population"):
        dispositions()


def test_a_model_excluded_in_both_places_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two opinions about one table is a disagreement to settle, not to resolve by order."""
    with planted_in_the_registry("DoublyExcluded") as planted:
        planted.export_excluded = True  # type: ignore[attr-defined]  # the plant's whole point
        planted.export_excluded_reason = "a" * 40  # type: ignore[attr-defined]  # ditto
        monkeypatch.setitem(census.EXCLUSIONS, "exports.DoublyExcluded", "b" * 40)
        with pytest.raises(ValueError, match="two opinions"):
            dispositions()


def test_every_declared_exclusion_carries_a_reason_worth_reading() -> None:
    """Not just present — long enough to be an argument a reviewer can refuse.

    The reader of these sentences is a customer who is leaving and cannot ask
    why a table is missing, so the bar is higher than the mechanical one and
    this asserts the mechanical one plus a length nothing accidental clears.
    """
    for label, reason in EXCLUSIONS.items():
        assert len(reason) > 120, f"{label}'s exclusion reason is a note, not an argument"


# --- the field-level exclusion has real members ---------------------------------


def test_every_encrypted_column_in_the_deployment_is_excluded_by_name() -> None:
    """Rule 15's population, and the archive's exclusion list, are one population.

    Derived off the field TYPES rather than off column names, so a fourth
    encrypted column added tomorrow leaves the archive on the day it lands. The
    pin below is what makes a THIRD one going missing a diff.
    """
    found = {
        (str(model._meta.label), one.name)
        for model in scoped_models()
        for one in encrypted_fields(model)
    }
    assert found == EXPECTED_ENCRYPTED


def test_an_excluded_field_is_off_the_travelling_list_and_named_with_its_basis() -> None:
    """Both halves: the column does not travel, and the archive says it did not."""
    connection = dispositions()["connections.Connection"]

    assert "credentials" not in connection.field_names
    basis = {one.name: one.basis for one in connection.excluded_fields}
    assert "credentials" in basis
    assert "encrypted at rest" in basis["credentials"]
    assert "house rule 15" in basis["credentials"]


# --- the subtree plan says what it cannot carry ---------------------------------


def test_a_tenant_wide_export_skips_nothing() -> None:
    """The root's subtree is the whole tree, so every dispositioned model travels."""
    carried, skipped = plan(tenant_wide=True)

    assert platform_only(carried) == EXPECTED
    assert platform_only(skipped) == set()


def test_a_subtree_export_skips_exactly_the_models_it_cannot_narrow() -> None:
    """And the reason is in the plan, so it reaches the customer's manifest.

    A model with no `organization` cannot be narrowed to a branch, and reading
    it with `for_tenant` alone would put the whole customer's rows in one
    branch's archive. Skipping is the fail-closed direction; saying so is what
    stops it being indistinguishable from a tenant that never had the table.
    """
    carried, skipped = plan(tenant_wide=False)

    assert platform_only(carried) | platform_only(skipped) == EXPECTED
    assert set(carried) == {label for label, one in dispositions().items() if one.org_scoped}
    assert set(skipped) == {label for label, one in dispositions().items() if not one.org_scoped}
    for reason in skipped.values():
        assert "tenant-wide export" in reason


def test_the_export_row_is_in_its_own_census() -> None:
    """An archive carries the tenant's export records, and that is not a loop.

    The row holds the artifact's KEY and never the artifact, so an export of the
    exports is a few hundred bytes per previous archive.
    """
    disposition = dispositions()["exports.Export"]

    assert disposition.org_scoped is True
    assert "artifact_key" in disposition.field_names
    assert disposition.excluded_fields == ()


def test_the_counts_this_report_states(capsys: Any) -> None:
    """The three numbers this report states, measured rather than typed."""
    concrete = len(not_a_product_model([m for m in django_apps.get_models() if not m._meta.proxy]))
    # 39 -> 40: `usage.UsageEntry`, the metering ledger.
    # 40 -> 41: `comms.MessageEngagement`, the opened/clicked record.
    # 41 -> 43: `files.StoredFile` and `files.FileVersion`, the
    # document aggregate (both models landed together; the three numbers move
    # together by construction, and a diff that moved only one would be the
    # thing to look at).
    # 43 -> 44: `comms.Device`, the push address book.
    # 44 -> 45: `accounts.IdentityBranding`, the hosted sign-in screen's intent
    # row. Only THIS number moves, unlike every entry above: it carries no
    # `tenant`, so it never joins `scoped_models()` and the other two counts
    # below are untouched — the deployment's own login-screen intent has no
    # tenant to be a customer's.
    # 45 -> 48: `core.Role`, `core.RolePermission` and `core.Grant`, the three
    # tables behind a tenant's own roles, its deltas on the declared ones and one
    # person's exceptions. ALL THREE numbers move together, which is the shape to
    # expect: each carries a `tenant`, so each joins `scoped_models()`, and none
    # is excluded, so each is dispositioned into the archive. A diff that moved
    # only one of the three would be the thing to look at.
    assert concrete == 48, (
        "the review's 38, plus exports.Export, usage.UsageEntry, "
        "comms.MessageEngagement, the two files models, "
        "comms.Device, accounts.IdentityBranding and the three permission tables"
    )
    assert len(not_a_product_model(scoped_models())) == 32
    assert len(platform_only(dispositions())) == 29
    assert len(platform_only(exclusions())) == 3
    assert issubclass(dispositions()["core.AuditEntry"].model, BaseModel)
