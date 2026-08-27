"""How comms data dies, asserted — house rule 31, ADR core-13.

The declarations themselves live on the models (`apps/comms/models.py`), where
the person adding a table is already standing. This module is what stops them
becoming decoration.

Three kinds of claim, and each one names the failure it catches:

* **The population closes.** Every concrete model in the `comms` app label is
  declared, so the rule-31 ratchet for this app is honestly at zero rather than
  at zero because the census stopped looking. An eighth comms table added
  without a declaration fails here before it fails the gate. (It has already
  done its job once: `MessageEngagement` arrived and this module went
  red naming it, which is the tripwire working rather than a test needing
  maintenance.)
* **The kinds are the ones the rung argued for.** Six of the seven are
  `unbounded` and the seventh is `append_only`, and the near-uniformity is the
  finding: comms has no cascade a `bounded` declaration could name and no
  ratified retention window a `purged` one could implement. Both halves are
  asserted against the SCHEMA rather than against the declarations, so a future
  `on_delete` change that makes `bounded` true (or a `purged` declaration that
  lands without a sweeper) shows up here as a contradiction instead of as a
  comment that quietly went stale.
* **`Message` carries the dated residual's trigger verbatim.** It is closed
  as a declaration and deliberately not as a build; a trigger that
  drifts from the queue row is how a decision loses the condition that would
  reopen it.

What is NOT asserted here, declared: whether these reasons are GOOD ones. The
grammar is closed in `apps.core.lifecycle` (present, long enough to be a clause,
a real calendar date) and the judgement is review's — rule 31's own
`does_not_cover` says the same thing about itself.
"""

from __future__ import annotations

from typing import Any

import pytest
from django.apps import apps as django_apps
from django.db import models

from apps.comms.models import (
    ChannelPreference,
    DeliveryPolicy,
    Device,
    Message,
    MessageEngagement,
    MessageTemplate,
    Recipient,
    SuppressionSurge,
)
from apps.core.lifecycle import LifecycleKind, lifecycle_of

#: The dated residual's trigger, verbatim from its row in `docs/product/queue.md`:
#:
#:     | `comms.Message` has no retention/purge policy — the dated
#:     | residual flagged. Trigger: first tenant past 100k
#:     | messages, or the first compliance ask. | dated residual | …
#:
#: Written out here rather than read from the queue file on purpose: a test
#: that parsed the ledger would pass by re-reading whatever the ledger says
#: today, and the thing being pinned is that the DECLARATION still says what
#: the ruling said when it was taken.
N28_TRIGGER = "first tenant past 100k messages, or the first compliance ask"

#: Every concrete model this app owns, and the kind the rung argued for.
THE_POPULATION = [
    (Recipient, LifecycleKind.UNBOUNDED),
    (MessageTemplate, LifecycleKind.UNBOUNDED),
    (DeliveryPolicy, LifecycleKind.UNBOUNDED),
    (ChannelPreference, LifecycleKind.UNBOUNDED),
    (Message, LifecycleKind.UNBOUNDED),
    (SuppressionSurge, LifecycleKind.UNBOUNDED),
    # ADR comms-9. The one that is not `unbounded`, and the kind is
    # coherent with `append_only = True` on the model rather than a second
    # opinion about the same table: rule 20 asks "may a row be rewritten" and
    # rule 31 asks "what happens to these rows over TIME", and for witnessed
    # engagement history the honest answer to the second is the first.
    (MessageEngagement, LifecycleKind.APPEND_ONLY),
    # ADR comms-9's push half. `unbounded`, and the argument is
    # `Recipient`'s rather than a fresh one: `Device.recipient` is PROTECT, so
    # nothing cascades to it, and `bounded` would be a lifecycle that never
    # fires. A purge is genuinely available here — nothing points AT a device —
    # and is deliberately not declared, because the retention ruling a sweeper
    # would implement is still absent; the test two below holds
    # that absence for the whole app.
    (Device, LifecycleKind.UNBOUNDED),
]


def _comms_models() -> set[type[models.Model]]:
    """The population, read off the registry rather than off the list above.

    Deriving it is the point: a list would answer for itself, and the failure
    worth catching is a seventh table nobody added to the list.
    """
    return {model for model in django_apps.get_models() if model._meta.app_label == "comms"}


def test_every_comms_model_declares_how_its_data_dies() -> None:
    """The rule-31 class for this app is honestly empty.

    Fails when a comms table is added without a `lifecycle` ClassVar — which is
    the whole point of the ratchet holding at zero: the
    seventh table is a violation from birth, and this says so one layer earlier
    and names the model.
    """
    undeclared = sorted(
        model._meta.label for model in _comms_models() if lifecycle_of(model) is None
    )
    assert undeclared == [], (
        f"undeclared comms models: {undeclared}. Rule 31's `comms` ratchet is at 0, "
        "so this is a violation from birth — declare the lifecycle on the model."
    )


def test_the_listed_models_are_the_whole_population() -> None:
    """The parametrized list below really is exhaustive, and stays so.

    Without this, an eighth table could be declared (passing the test above)
    and still never have its KIND argued about by anybody.
    """
    assert {model for model, _ in THE_POPULATION} == _comms_models()


@pytest.mark.parametrize(("model", "kind"), THE_POPULATION)
def test_the_comms_declarations_say_what_the_rung_said_they_would(
    model: type[Any], kind: LifecycleKind
) -> None:
    declared = lifecycle_of(model)
    assert declared is not None
    assert declared.kind is kind
    assert declared.declared_for == model._meta.label


@pytest.mark.parametrize(("model", "kind"), THE_POPULATION)
def test_every_comms_declaration_carries_a_reason_and_a_dated_trigger(
    model: type[Any], kind: LifecycleKind
) -> None:
    """`unbounded` is a DECISION, so it has to carry the decision.

    `apps.core.lifecycle` already refuses a malformed one at import, which
    means this cannot fail while the app imports at all — and that is exactly
    why it is written as a claim about non-emptiness rather than as a re-run of
    the primitive's grammar: it is the line that has to change if somebody ever
    weakens the primitive, and a reviewer reads it here in the app that would
    be weakened.
    """
    declared = lifecycle_of(model)
    assert declared is not None
    assert declared.reason.strip() != ""
    assert declared.trigger.strip() != ""


def test_the_message_declaration_carries_n28s_trigger_verbatim() -> None:
    """The dated residual, closed as a declaration and not as a build.

    Fails when somebody edits the trigger into a paraphrase — at which point
    the condition that would reopen the decision has quietly changed and
    nobody would know which one was ratified.
    """
    declared = lifecycle_of(Message)
    assert declared is not None
    assert N28_TRIGGER in declared.trigger, (
        f"`Message.lifecycle.trigger` no longer carries the dated residual's trigger verbatim. "
        f"Expected to find {N28_TRIGGER!r}; got {declared.trigger!r}."
    )
    # And the date, because a trigger that cannot be aged cannot be told from a
    # stale one — the primitive's own argument, pinned at the site that has to
    # keep it true.
    assert "2026-08-24" in declared.trigger


# --- the two arguments the kinds rest on, checked against the SCHEMA ----------


def test_no_comms_cascade_hangs_off_a_parent_that_actually_dies() -> None:
    """Why nothing here is `bounded`, including the two rows that DO cascade.

    `bounded` means the rows die with their parent, and in this app no parent
    dies: `tenant` and `organization` are PROTECT on every scoped model,
    `Message` PROTECTs both `Recipient` and `MessageTemplate`, and
    `SuppressionSurge.connection` is PROTECT too.

    **Two CASCADEs exist and both are asserted here rather than excused**, with
    the same shape of argument:

    * `ChannelPreference.recipient` — `Recipient` is `unbounded` and archives
      rather than dies, so the cascade never fires;
    * `MessageEngagement.message` — `Message` is `unbounded` on its
      dated trigger, so that one never fires either. It is a real ownership
      edge, and the day that ruling arrives it is the edge that sweeps
      engagement rows first; today it settles nothing.

    **This is the test that turns the argument into a tripwire.** The day
    somebody changes one of these to CASCADE off a parent that is `purged` or
    `bounded`, the honest kind for the child changes with it — and this fails,
    naming the field, instead of leaving a declaration that is quietly no longer
    the truest one available.
    """
    cascades = sorted(
        f"{model._meta.label}.{field.name}"
        for model in _comms_models()
        for field in model._meta.get_fields()
        if isinstance(field, models.ForeignKey) and field.remote_field.on_delete is models.CASCADE
    )
    assert cascades == [
        "comms.ChannelPreference.recipient",
        "comms.MessageEngagement.message",
    ], (
        f"the comms cascade set changed: {cascades}. Every declaration in this app "
        "rests on there being no parent whose death takes the rows with it; a new "
        "CASCADE means the honest kind for that model may now be `bounded`."
    )
    # And the two parents that exist are both rows that do not die — which is
    # what makes the sentence above true rather than merely stated.
    for parent in (Recipient, Message):
        declared = lifecycle_of(parent)
        assert declared is not None
        assert declared.kind is LifecycleKind.UNBOUNDED


def test_comms_declares_no_purge_because_no_retention_ruling_exists() -> None:
    """The absence, asserted, so it reads as a decision rather than an omission.

    A `purged` declaration is a promise that something sweeps the table, and
    rule 31 makes it a promise a `ScheduleDeclaration` chain has to keep. Comms
    ships none — not because sweeping is hard, but because the RULING a sweeper
    would implement does not exist. Building the reader first is rule
    30's defect pointed the other way.

    Fails the day a `purged` declaration lands here: at which point the rung
    that added it owes the callable, the activity, the workflow and the
    `ScheduleDeclaration`, in the same commit — and this test is where that
    obligation is written down for the person about to add it.
    """
    purged = sorted(
        model._meta.label
        for model in _comms_models()
        if (declared := lifecycle_of(model)) is not None and declared.kind is LifecycleKind.PURGED
    )
    assert purged == [], (
        f"comms now declares a purge for {purged}, which rule 31 requires a "
        "`ScheduleDeclaration` chain to reach: write the sweeper, its activity, its "
        "workflow and its `SCHEDULES` entry in the same commit, and update this test "
        "to name the retention ruling that authorised the window."
    )
