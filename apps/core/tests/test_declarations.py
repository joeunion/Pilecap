"""The two declarations later rungs build on, as importable typed artifacts.

The absent-answer is what this module is for: without these in the tree, the rungs
that fan out from here have no seam to build against, and "the seam is code in
the tree before the fan-out" is the whole reason they landed here
rather than beside the rules that will read them.

* **`append_only`** (ADR core-6) — house rule 20 hard-coded `AuditEntry` by
  name. A product's witnessed facts, accruals and stage-transition logs make
  the same promise and are called none of those things, so the promise becomes
  a class attribute and the rule becomes a closed question over the registry.
* **`MeasuredOut`** (ADR core-7) — a number the UI never computes, with the
  basis it was computed from attached to it.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import models
from pydantic import ValidationError

from apps.core.audit import AuditEntry
from apps.core.models import (
    APPEND_ONLY_ATTR,
    Organization,
    Tenant,
    append_only_models,
    is_append_only,
)
from apps.core.schemas import MeasuredBasisOut, MeasuredOut
from apps.core.tests.isolation import isolated_apps

# --- append-only (ADR core-6) ------------------------------------------------


def test_the_audit_entry_declares_itself_append_only() -> None:
    """The first member of the population, and it says so itself."""
    assert AuditEntry.append_only is True
    assert is_append_only(AuditEntry)
    assert getattr(AuditEntry, APPEND_ONLY_ATTR) is True


def test_a_model_that_did_not_declare_it_is_not_in_the_population() -> None:
    """The default is False, and it is False by absence rather than by listing."""
    for model in (Tenant, Organization):
        assert not is_append_only(model)


def test_the_population_is_discovered_and_holds_the_audit_entry(db: None) -> None:
    """Discovered off the registry, which is what makes rule 20 generalizable.

    A product adds a member by declaring one attribute on its model; nothing in
    `rules.yaml` is edited, and the rule covers the new model in the same
    commit that introduces it. Asserted as membership rather than as an
    equality, because a product adding a second member must not have to come
    and edit this line.
    """
    discovered = append_only_models()
    assert AuditEntry in discovered
    assert all(is_append_only(model) for model in discovered)
    assert all(issubclass(model, models.Model) for model in discovered)


def test_the_declaration_survives_a_subclass() -> None:
    """A product naming an audit row better inherits the promise with it.

    Read as an attribute, so it is inherited — which is right: a subclass of an
    append-only model is append-only, and a subclass that wanted to opt out
    would have to say `append_only = False` out loud, in its own class body,
    where a reviewer sees it.

    Built in a throwaway registry: a model class defined bare in a test body
    registers itself in the GLOBAL one and nothing takes it out, so every
    registry reader that runs after this test on the same worker — the derived
    `<kind>.read` keys among them — would count a model no product has.
    """
    with isolated_apps("apps.core"):

        class BetterNamedEntry(AuditEntry):
            class Meta:
                proxy = True

        assert is_append_only(BetterNamedEntry)


# --- Measured (ADR core-7) ---------------------------------------------------


def test_a_measured_number_round_trips_with_string_decimals() -> None:
    """House rule 15's reason for existing.

    `model_dump(mode="json")` is what a door renders through, and a `Decimal`
    that came back as a float would be a number that had already stopped adding
    up by the time a client saw it. Strings at both levels — the value and
    every input.
    """
    measured = MeasuredOut(
        value=Decimal("1240.50"),
        basis=MeasuredBasisOut(
            formula="gross - discounts",
            inputs={"gross": Decimal("1400.00"), "discounts": Decimal("159.50")},
        ),
    )

    dumped = measured.model_dump(mode="json")
    assert dumped == {
        "value": "1240.50",
        "basis": {
            "formula": "gross - discounts",
            "inputs": {"gross": "1400.00", "discounts": "159.50"},
        },
    }
    assert MeasuredOut(**measured.model_dump()) == measured


def test_the_basis_is_not_optional() -> None:
    """The contract is the *pair*, and a bare number is what it replaces.

    A `MeasuredOut` whose basis could be omitted would be a `Decimal` with a
    longer name, and the first door in a hurry would omit it.
    """
    with pytest.raises(ValidationError):
        MeasuredOut(value=Decimal("1"))  # type: ignore[call-arg]


def test_the_inputs_are_decimals_too() -> None:
    """The parts a person checks the arithmetic against carry the same precision."""
    basis = MeasuredBasisOut(formula="a / b", inputs={"a": Decimal("1"), "b": Decimal("3")})
    assert all(isinstance(value, Decimal) for value in basis.inputs.values())
    assert basis.model_dump(mode="json")["inputs"] == {"a": "1", "b": "3"}
