"""LF1-2: the runtime append-only belt. **The tamper that drove a clean gate.**

Criterion LF1-2 of rung LF-1, carrying ADR core-14 as ratified. The
absent-answer is not hypothetical and is not a guess: a probe wrote an
instance `.save()` tamper on an append-only member and drove it through the
FULL gate, CLEAN. House rule 20's static half reads the source for `.delete()`,
`.update()` and `.bulk_update()` on a name that mentions a member; it cannot
see three innocent-looking lines —

    entry = WidgetEntry.objects.get(pk=...)
    entry.note = "something else"
    entry.save()

— and P4's production database grant, the third belt, protects production,
which is not where a tamper gets written. So the model refuses it too, at the
last possible moment, over the **declared** population.

**Three belts, stated honestly, because a belt whose gaps are unstated is worse
than no belt** (ADR core-14's rejected alternatives):

1. static — house rule 20, the gate, over the source;
2. runtime — this file's subject, over instances;
3. the production database grant — P4, over the deployment.

The queryset path (`Model.objects.filter(...).update(...)`, `.delete()`,
`bulk_update`) is belts 1 and 3 and is deliberately NOT belt 2 — a fourth belt
in the manager buys marginal coverage for real manager complexity. That is
declared residue and `test_the_belt_does_not_reach_the_queryset_path` below
says so out loud rather than letting a reader assume coverage that is not
there.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from django.conf import settings

from apps.core.actor import Actor
from apps.core.audit import AuditEntry, AuditImmutable
from apps.core.lifecycle import AppendOnlyViolation
from apps.core.models import Tenant, append_only_models, is_append_only
from apps.example.models import Widget, WidgetEntry
from apps.example.services import create_widget, record_widget_entry

pytestmark = pytest.mark.django_db


def _rule(rule_id: str) -> dict[str, Any]:
    """One house rule, out of `quality/rules.yaml`. See the test at the foot."""
    path = Path(settings.BASE_DIR) / "quality" / "rules.yaml"
    rules = yaml.safe_load(path.read_text())["rules"]
    return next(rule for rule in rules if str(rule["id"]) == rule_id)


@pytest.fixture
def entry(tenant: Tenant, owner_actor: Actor) -> WidgetEntry:
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Ledgered")
    return record_widget_entry(
        tenant=tenant,
        actor=owner_actor,
        widget=widget,
        note="what was witnessed",
    )


# --- the tamper, verbatim ----------------------------------------------------


def test_an_update_save_on_a_member_raises(entry: WidgetEntry) -> None:
    """**The tamper.** Three innocent lines, refused at the third one.

    Reloaded from the database first, deliberately: that is the shape a tamper
    actually has, and it is the shape `pk is None` would have got wrong —
    `BaseModel` mints the UUID in Python, so an unsaved row already has a
    primary key and only `_state.adding` tells the truth.
    """
    reloaded = WidgetEntry.objects.get(pk=entry.pk)
    reloaded.note = "something else"

    with pytest.raises(AppendOnlyViolation, match="created once and never changed"):
        reloaded.save()

    assert WidgetEntry.objects.get(pk=entry.pk).note == "what was witnessed"


def test_the_refusal_names_the_model_and_the_correction_convention(
    entry: WidgetEntry,
) -> None:
    """A refusal that does not say what to do instead teaches nothing (E9's shape)."""
    entry.note = "edited"
    with pytest.raises(AppendOnlyViolation) as raised:
        entry.save()
    message = str(raised.value)
    assert "example.WidgetEntry" in message
    assert "append_only = True" in message
    assert "superseding row" in message


def test_an_update_with_update_fields_raises_too(entry: WidgetEntry) -> None:
    """`update_fields` is the narrow spelling of the same act, and is the same act."""
    entry.note = "edited"
    with pytest.raises(AppendOnlyViolation):
        entry.save(update_fields=["note"])


def test_deleting_an_instance_raises(entry: WidgetEntry) -> None:
    with pytest.raises(AppendOnlyViolation, match="never deleted"):
        entry.delete()
    assert WidgetEntry.objects.filter(pk=entry.pk).exists()


# --- what the belt must NOT break -------------------------------------------


def test_creating_a_member_is_unaffected(tenant: Tenant, owner_actor: Actor) -> None:
    """A ledger you cannot append to is not a ledger."""
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Fresh")
    line = record_widget_entry(tenant=tenant, actor=owner_actor, widget=widget, note="first")
    assert line.pk is not None
    assert WidgetEntry.objects.filter(pk=line.pk).exists()


def test_the_superseding_row_correction_works(
    entry: WidgetEntry, tenant: Tenant, owner_actor: Actor
) -> None:
    """D8's convention: a mistake is answered, never edited.

    The ledger ends up holding the mistake AND the correction, which is what
    makes it evidence rather than a table somebody tidied. This is the whole
    reason refusing the update is not a loss of capability — the capability is
    a second row, and it is available here.
    """
    correction = record_widget_entry(
        tenant=tenant,
        actor=owner_actor,
        widget=entry.widget,
        note=f"supersedes {entry.pk}: what was witnessed was misrecorded",
    )

    lines = list(WidgetEntry.objects.for_tenant(tenant).filter(widget=entry.widget))
    assert {line.pk for line in lines} == {entry.pk, correction.pk}
    assert WidgetEntry.objects.get(pk=entry.pk).note == "what was witnessed"


def test_a_model_outside_the_population_still_updates_and_deletes(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """The belt is the DECLARATION's, not every model's. Silence is silence."""
    assert not is_append_only(Widget)
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Ordinary")
    widget.name = "Renamed"
    widget.save(update_fields=["name", "updated_at"])
    assert Widget.objects.get(pk=widget.pk).name == "Renamed"
    widget.delete()
    assert not Widget.objects.filter(pk=widget.pk).exists()


def test_an_ordinary_core_row_still_updates(tenant: Tenant) -> None:
    """`BaseModel.save` is on the hot path of every write in the product."""
    tenant.locale = "en-gb"
    tenant.save(update_fields=["locale", "updated_at"])
    assert Tenant.objects.get(pk=tenant.pk).locale == "en-gb"


# --- the belt reads the declaration, not a name list -------------------------


def test_the_population_is_the_declared_one(
    monkeypatch: pytest.MonkeyPatch, tenant: Tenant, owner_actor: Actor
) -> None:
    """ADR core-6's whole point, re-proven one layer down.

    A model joins the population by declaring the attribute, and the belt
    covers it in the same commit with no edit anywhere else — no mixin, no
    base class, no list in `rules.yaml` and no list here. Proven by DECLARING
    an ordinary model append-only for the duration of one test and watching the
    belt close over it.
    """
    widget = create_widget(tenant=tenant, actor=owner_actor, name="Promoted")

    monkeypatch.setattr(Widget, "append_only", True, raising=False)
    assert Widget in append_only_models()

    widget.name = "Renamed"
    with pytest.raises(AppendOnlyViolation, match="example.Widget"):
        widget.save()


def test_the_audit_trail_speaks_the_same_exception(tenant: Tenant) -> None:
    """`AuditImmutable` is a MEMBER of this family now, not a lookalike beside it.

    `AuditEntry` keeps its own, more specific refusal — it predates the belt
    and a table whose whole value is that nothing rewrites it is the last place
    to remove a guard because a general one arrived. What changed is that one
    `except AppendOnlyViolation` now catches every append-only tamper in the
    product, and `AuditImmutable` is still a `RuntimeError`, so nothing that
    caught one before catches less now.
    """
    row = AuditEntry.objects.create(tenant=tenant, action="core.probe")
    row.action = "core.tampered"
    with pytest.raises(AppendOnlyViolation):
        row.save()
    with pytest.raises(AuditImmutable):
        row.save()
    assert issubclass(AuditImmutable, AppendOnlyViolation)
    assert issubclass(AppendOnlyViolation, RuntimeError)


# --- the honest boundary -----------------------------------------------------


def test_the_belt_does_not_reach_the_queryset_path(entry: WidgetEntry) -> None:
    """**Declared residue, said out loud** (ADR core-14's rejected alternative).

    A queryset `.update()` never constructs an instance and never calls
    `save()`, so this belt cannot see it and does not claim to. That path is
    covered by the OTHER TWO belts and by nothing else:

    * house rule 20's static half refuses `WidgetEntry.objects...update(...)`
      anywhere outside the model's own declaring module, at gate time, over
      the source (`quality/rules.yaml` rule 20, `check: append_only_writes`);
    * P4's production database grant refuses the statement itself, in
      production.

    This test EXISTS so that the gap is a written-down fact with a name on it
    rather than something a reader infers wrongly from a green suite. A fourth
    belt in the manager was considered and rejected: marginal coverage for real
    manager complexity. The trigger to revisit is a measured bulk-path tamper
    the two remaining belts miss.
    """
    WidgetEntry.objects.filter(pk=entry.pk).update(note="through the queryset")
    assert WidgetEntry.objects.get(pk=entry.pk).note == "through the queryset"


def test_rule_20_covers_the_path_this_belt_does_not() -> None:
    """The pairing, asserted rather than promised: rule 20 is on and reads `.update`.

    Read out of `rules.yaml` the way the gate reads it, and NOT by importing
    the engine: `quality/` is outside mypy's `files` and importing it from a
    test drags the whole engine into the strict graph. `test_contract_docs.py`
    reads rule 41's ratchet the same way and for the same reason.
    """
    rule = _rule("20")
    assert rule["enabled"] is True
    assert ".update()" in rule["statement"]
