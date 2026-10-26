"""How a model's data dies, declared on the model that holds it.

A retention document is the shape that does not survive a product: it is
written once, it is read by nobody, and the table added on Thursday is not in
it. So the declaration lives **on the model**, where the person adding the
table is already standing, and the population is *discovered* rather than
listed — exactly the move ADR core-6 made for `append_only = True`, generalised
to the question that class of bug actually asks: **what happens to these rows
over time, and who does it?**

    class IdempotencyRecord(BaseModel):
        lifecycle: ClassVar[Lifecycle] = Lifecycle(
            kind=LifecycleKind.PURGED,
            purged_by="apps.core.idempotency.purge_expired",
            reason="...",
        )

Four kinds and no fifth (ADR core-13):

* **`PURGED`** — something deletes these rows on a schedule, and
  **`purged_by` names it** as a dotted path. The declaration is what makes
  "the poller that was never built" a closed question: a schema shaped for a
  sweeper, with no sweeper, is the class of defect this whole vocabulary
  exists to catch, and it has four sightings in this tree's history.
* **`BOUNDED`** — the rows die with their parent. A `CASCADE` from a tenant,
  an organization or an owning row IS the lifecycle, and naming it that way
  says the population cannot outlive the thing it hangs off.
* **`UNBOUNDED`** — the table grows forever, **on purpose**, and the
  declaration carries the `reason` and a dated `trigger` that would make
  somebody revisit it. Unbounded-by-decision and unbounded-by-nobody-thinking
  look identical in a schema; this is what tells them apart.
* **`APPEND_ONLY`** — rows are written and never changed or removed. Same
  required `reason` + dated `trigger` as `UNBOUNDED`, because an append-only
  table is an unbounded one that has also given up its delete.

**A malformed declaration is refused at import** — `PURGED` with nothing to
purge it, `UNBOUNDED` with no reason — which is the strongest tier this tree
has and the same one `core.exceptions.register_refusal` uses (E9). A
declaration checked at gate time is a declaration that is wrong in a running
process for as long as nobody runs the gate.

## The third-party hook, and why there is no shared file

Half the tables in a Django deployment belong to somebody else — allauth's two,
`django_session`, `django_admin_log` — and none of them will ever grow a
`lifecycle` attribute. They are declared by **whichever app owns the concern**,
in that app's own `apps/<x>/lifecycle.py`:

    # apps/accounts/lifecycle.py
    def register(registry: LifecycleRegistry) -> None:
        registry.declare(EmailAddress, Lifecycle(kind=LifecycleKind.BOUNDED, ...))

Discovered, never listed. A central `THIRD_PARTY_LIFECYCLES` dict would be one
file that every app in a parallel wave has to edit, which is the collision this
whole template is shaped around avoiding — the same reasoning that makes
`INSTALLED_APPS` derived and `SCHEDULES` discovered.

## The runtime belt

`AppendOnlyViolation` lives here rather than in `models.py` because the
declaration is what defines the population and this module is the declaration's
home. `BaseModel.save()`/`.delete()` raise it on the update/delete path for any
model in the **declared append-only population** (ADR core-14). See
`apps.core.models.BaseModel.save` for the belt itself and for the honest
statement of what it does not catch.

DOES NOT COVER — declared:

* whether a `reason` or a `trigger` is a *good* one. The grammar is closed
  here (present, long enough to be a clause, and a real calendar date); the
  judgement is review's, exactly as it is for a `# reach:` sentence.
* whether a `purged_by` callable is ever actually *reached* by a schedule.
  That is rule 31's schedule-reachability tooth (LF-Q), which walks
  `apps.workflows.client.discovered_schedules`; this module checks that the
  path is written down, not that it runs.
* whether a `BOUNDED` model's cascade really does cascade. `on_delete` is
  rule 15's subject and the declaration takes it at its word.
* models that are not in the app registry at all — unmanaged tables, views,
  and anything created outside Django.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING, Any

from django.db import models

from apps.core.reason_floor import MIN_REASON as MIN_REASON

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

__all__ = [
    "LIFECYCLE_ATTR",
    "AppendOnlyViolation",
    "Lifecycle",
    "LifecycleKind",
    "LifecycleRegistry",
    "declared_lifecycles",
    "declared_populations",
    "lifecycle_of",
    "population_sources",
    "third_party_lifecycles",
    "undeclared_models",
]


class AppendOnlyViolation(RuntimeError):
    """An attempt to update or delete a row of a declared append-only model.

    A `RuntimeError` and deliberately **not** a `DomainError`: nobody was
    refused permission and no door needs to map this to a status code. It is a
    programming error — the code that raised it is asking for something the
    model's own declaration says is impossible — and it should reach a
    traceback, not a screen.

    `apps.core.audit.AuditImmutable` is a subclass, so the audit trail's own
    long-standing refusal is now a member of this family rather than a
    lookalike beside it: one `except AppendOnlyViolation` catches both, and the
    sentence `AuditEntry` has always said is unchanged.
    """


class LifecycleKind(models.TextChoices):
    """The four ways a table's rows can end. There is deliberately no fifth."""

    PURGED = "purged", "Purged on a schedule"
    BOUNDED = "bounded", "Bounded by an owning row"
    UNBOUNDED = "unbounded", "Unbounded, with a reason"
    APPEND_ONLY = "append_only", "Append-only, with a reason"


#: The class attribute a model sets to declare its lifecycle. Named once, here,
#: so the model that declares it, the readers below and house rule 31 all say
#: the same word — the same discipline `APPEND_ONLY_ATTR` follows.
LIFECYCLE_ATTR = "lifecycle"

#: A dated trigger carries an ISO calendar date somewhere in it. The date is
#: **when the decision was taken**, in the ADR grammar this repository already
#: writes triggers in ("2026-08-24 · trigger to revisit: …"), because a trigger
#: with no date cannot be aged and a reviewer cannot tell a standing decision
#: from a stale one.
_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

#: The kinds whose declaration is a *decision* rather than a mechanism, and
#: which therefore have to carry the decision with them.
_REASONED_KINDS = frozenset({LifecycleKind.UNBOUNDED, LifecycleKind.APPEND_ONLY})


@dataclass(frozen=True)
class Lifecycle:
    """One model's declared retention, as data.

    Frozen, because a declaration that a later import can rewrite is not a
    declaration. Validated in `__post_init__`, so the refusal lands at the
    moment the class body is evaluated — module import — and names the file it
    came from through the ordinary traceback.

    `declared_for` is filled in by the readers and by `LifecycleRegistry`, so a
    census can print *which model* a declaration belongs to without every
    caller having to carry the pair around. It is never written by hand.
    """

    kind: LifecycleKind
    reason: str = ""
    trigger: str = ""
    purged_by: str = ""
    declared_for: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _as_kind(self.kind))
        _refuse_malformed(self)

    @property
    def is_append_only(self) -> bool:
        return self.kind is LifecycleKind.APPEND_ONLY

    def __str__(self) -> str:
        return f"{self.declared_for or 'lifecycle'}: {self.kind.value}"


def _as_kind(value: Any) -> LifecycleKind:
    """The kind as a member, whatever spelling arrived. Unknown words refuse."""
    if isinstance(value, LifecycleKind):
        return value
    try:
        return LifecycleKind(value)
    except ValueError:
        raise ValueError(
            f"A lifecycle kind is one of {', '.join(k.value for k in LifecycleKind)}; "
            f"got {value!r}. There are four ways a table's rows can end and the "
            f"vocabulary is closed on purpose — a fifth word is a decision to record "
            f"in an ADR, not a string to invent at a declaration site."
        ) from None


def _refuse_malformed(lifecycle: Lifecycle) -> None:
    """Every way a declaration can be a promise nobody kept. Raised at import.

    `ValueError`, at import, is the tier `core.exceptions.register_refusal`
    already set for a malformed declaration (E9) — the strongest one this tree
    has. A system check would be quieter and would let a wrong declaration ride
    in a running process until somebody remembered to run `manage.py check`.
    """
    kind = lifecycle.kind
    where = f" on {lifecycle.declared_for}" if lifecycle.declared_for else ""

    if kind is LifecycleKind.PURGED:
        if not lifecycle.purged_by.strip():
            raise ValueError(
                f"A `purged` lifecycle{where} names what purges it: pass "
                f"purged_by='apps.<app>.<module>.<callable>'. A table declared purged "
                f"with nothing purging it is the poller-that-was-never-built, which is "
                f"the exact defect this vocabulary exists to catch (ADR core-13)."
            )
        if "." not in lifecycle.purged_by.strip("."):
            raise ValueError(
                f"`purged_by`{where} is a DOTTED path to the callable that does the "
                f"purging — `apps.core.idempotency.purge_expired`, not "
                f"{lifecycle.purged_by!r}. It is dotted because rule 31 has to resolve "
                f"it to check that a schedule reaches it."
            )
    elif lifecycle.purged_by.strip():
        raise ValueError(
            f"`purged_by`{where} is only meaningful on a `purged` lifecycle; this one "
            f"is {kind.value!r}. A sweeper named on a bounded or append-only table is "
            f"either a wrong kind or a delete nobody meant to declare."
        )

    if kind in _REASONED_KINDS:
        if len(lifecycle.reason.strip()) < MIN_REASON:
            raise ValueError(
                f"A {kind.value!r} lifecycle{where} carries a `reason` — a table that "
                f"grows forever, or that never lets go of a row, is a DECISION, and "
                f"unbounded-by-decision and unbounded-by-nobody-thinking look identical "
                f"in a schema. Write the sentence a reviewer can disagree with (at "
                f"least {MIN_REASON} characters)."
            )
        if not _dated(lifecycle.trigger):
            raise ValueError(
                f"A {kind.value!r} lifecycle{where} carries a DATED `trigger` — what "
                f"would make somebody revisit this, and when the decision was taken, in "
                f"the ADR grammar this repository already writes triggers in "
                f"('2026-08-24 — the first tenant past 10 million rows'). Got "
                f"{lifecycle.trigger!r}: a trigger with no ISO date cannot be aged, and "
                f"a reviewer cannot tell a standing decision from a stale one."
            )


def _dated(text: str) -> bool:
    """Whether this trigger carries a real calendar date.

    `date.fromisoformat` and not the regex alone, because `2026-13-45` matches
    the shape of a date and is not one — and a check that accepts a
    shaped-but-impossible date is a check that taught somebody the wrong
    grammar.
    """
    for match in _DATE_RE.finditer(text):
        try:
            date.fromisoformat(match.group(0))
        except ValueError:
            continue
        return True
    return False


class LifecycleRegistry:
    """Where an app declares a lifecycle for a table it does not own.

    Handed to `register(registry)` in each discovered `apps/<x>/lifecycle.py`.
    The only writer of the third-party half; the models' own `lifecycle`
    ClassVars are the other half and neither can silently overwrite the other
    (see `lifecycle_of`).
    """

    def __init__(self) -> None:
        self._declared: dict[str, Lifecycle] = {}
        self._populations: dict[str, Lifecycle] = {}
        self._sources: dict[str, str] = {}

    def declare(self, model: type[models.Model], lifecycle: Lifecycle, *, source: str = "") -> None:
        """Declare `lifecycle` for a model this app does not own.

        A second app declaring the same model is **refused**, loudly, rather
        than resolved by import order: two apps with different opinions about
        when `django_session` rows die is a disagreement to settle in a plan,
        and letting whichever app loaded last win is how the disagreement
        becomes invisible.
        """
        label = model._meta.label
        if isinstance(getattr(model, LIFECYCLE_ATTR, None), Lifecycle):
            raise ValueError(
                f"{label} declares its own `lifecycle` on the model; {source or 'a '}"
                f"third-party registration would be a second opinion about the same "
                f"table. A model that can carry the declaration carries it."
            )
        existing = self._declared.get(label)
        if existing is not None and existing != replace(lifecycle, declared_for=label):
            raise ValueError(
                f"{label} already has a lifecycle declared by {self._sources[label]}, and "
                f"{source or 'this registration'} declares a different one. Two apps with "
                f"two opinions about when a table's rows die is a disagreement to settle "
                f"in a plan, not by import order."
            )
        self._declared[label] = replace(lifecycle, declared_for=label)
        self._sources[label] = source or "a third-party registration"

    def declare_population(self, name: str, lifecycle: Lifecycle, *, source: str = "") -> None:
        """Declare a lifecycle for a population **that no table holds**.

        `declare` above takes a `type[models.Model]` and keys everything on
        `model._meta.label`, which is the right shape for a third-party *table*
        and no shape at all for the populations that are not tables: the
        documents `apps/search` writes into somebody else's index, the objects
        `apps/files` writes into a bucket. Both are copies of personal data that
        outlive the row unless something takes them out, and both are exactly
        what house rule 31 exists to stop being silent about — one level further
        out than a rule reading `get_models()` can reach.

        Until this existed, `apps/search/lifecycle.py` carried its declaration
        in a module-level `POPULATIONS` dict of its own: the same `Lifecycle`
        value type, import-refused identically, and **read by nobody but its own
        app's tests**. That was the honest interim and it says so in its own
        docstring; this is the reader arriving. `apps/files` names
        `delete_tenant_objects` for the same shape, so the seam has two callers
        before it has one.

        **Deliberately a separate key space from `declarations()`.** A
        population name is not an `app_label.ModelName` and must not be able to
        pass as one: readers downstream split a label on its dot to get an app
        label, and a `"search.Document"` sitting in the model half would quietly
        become a model in the app `search` that no database has. Two dicts, two
        readers, one registry — and the two refusals below are what keep the
        halves from disagreeing.

        Refused, both loudly and at registration:

        1. **A name that IS a concrete model's label.** That table can carry the
           declaration on the class where the person adding it is standing, and
           a population declaration beside it would be a second opinion of the
           kind `declare` already refuses from the other direction.
        2. **A second, different declaration for the same name.** Same sentence,
           same reason: two apps disagreeing about when a population dies is a
           disagreement to settle in a plan, not by import order. Declaring the
           identical thing twice is not a disagreement and is allowed.
        """
        from django.apps import apps as django_apps

        key = str(name)
        if any(model._meta.label == key for model in django_apps.get_models()):
            raise ValueError(
                f"{key} is a concrete model's label, so it is a table and not an "
                f"off-ORM population; {source or 'this registration'} should declare "
                f"it on the model class, where the person adding the table is already "
                f"standing. A population declaration beside a model's own would be a "
                f"second opinion about the same rows."
            )
        stated = replace(lifecycle, declared_for=key)
        existing = self._populations.get(key)
        if existing is not None and existing != stated:
            raise ValueError(
                f"the population {key} already has a lifecycle declared by "
                f"{self._sources[key]}, and {source or 'this registration'} declares a "
                f"different one. Two apps with two opinions about when a population's "
                f"data dies is a disagreement to settle in a plan, not by import order."
            )
        self._populations[key] = stated
        self._sources[key] = source or "a population registration"

    def declarations(self) -> dict[str, Lifecycle]:
        return dict(self._declared)

    def populations(self) -> dict[str, Lifecycle]:
        """Every off-ORM population declared here, by name. Never a model label."""
        return dict(self._populations)

    def sources(self) -> dict[str, str]:
        """Which module declared each third-party lifecycle. For the census."""
        return dict(self._sources)


def _third_party_registry() -> LifecycleRegistry:
    """Build the registry by discovering `apps/<x>/lifecycle.py::register`.

    Not cached. The population is small (one module per installed app at most),
    a reader is called by a census, a management command or the gate rather
    than by a request, and a cache here would be a stale answer in exactly the
    process that reloads modules for a living — the test suite.

    `apps.core.lifecycle` is skipped by name: this module IS the primitive, it
    exposes no `register`, and naming the skip is cheaper than a reader
    wondering later whether the primitive declares anything about itself.
    """
    from apps.core.discovery import imported

    registry = LifecycleRegistry()
    _declare_core_tables(registry)
    for _, module in imported(LIFECYCLE_ATTR):
        if module.__name__ == __name__:
            continue
        register = getattr(module, "register", None)
        if register is None:
            continue
        register(registry)
    return registry


def _declare_core_tables(registry: LifecycleRegistry) -> None:
    """Declare the third-party tables core owns; this module is the primitive, never discovered."""
    from django.contrib.admin.models import LogEntry

    registry.declare(
        LogEntry,
        Lifecycle(
            kind=LifecycleKind.UNBOUNDED,
            reason="the owner retains every admin log (2026-10-08)",
            trigger="2026-10-08 — a retention period set for admin history, or erasure reaching it",
        ),
        source="apps/core/lifecycle.py",
    )


def third_party_lifecycles() -> dict[str, Lifecycle]:
    """Every lifecycle declared for a table the declaring app does not own."""
    return _third_party_registry().declarations()


def declared_populations() -> dict[str, Lifecycle]:
    """Every off-ORM population any app declared, by name.

    The reader `apps/search/lifecycle.py` was one short of. Discovered through
    the same `register(registry)` hook the third-party tables use, so an app
    that starts writing into a keyspace of its own declares how that data dies
    in the module the platform already looks in, and nothing central is edited.

    Kept separate from `third_party_lifecycles()` on purpose: these keys are
    names, not `app_label.ModelName`, and a reader that joined the two would
    hand a downstream `label.split(".")[0]` an app that does not exist.
    """
    return _third_party_registry().populations()


def population_sources() -> dict[str, str]:
    """Which module declared each off-ORM population. For the census and its report."""
    registry = _third_party_registry()
    sources = registry.sources()
    return {name: sources[name] for name in registry.populations()}


def lifecycle_of(model: type[models.Model]) -> Lifecycle | None:
    """This model's declared lifecycle, or `None` when nobody declared one.

    The model's own attribute first, the third-party registry second — and the
    two can never disagree, because `LifecycleRegistry.declare` refuses to
    register a model that carries the attribute itself.

    Inherited, deliberately: a product that declares a lifecycle on an abstract
    base has declared it for every table under that base, which is the same way
    `append_only` and `inherited_downward` read.
    """
    declared = getattr(model, LIFECYCLE_ATTR, None)
    if isinstance(declared, Lifecycle):
        return replace(declared, declared_for=model._meta.label)
    return third_party_lifecycles().get(model._meta.label)


def declared_lifecycles() -> dict[str, Lifecycle]:
    """Every concrete model in the registry that has a lifecycle, by label.

    Keyed by `app_label.ModelName` rather than by the class, so the answer is
    printable, diffable and orderable — a census reads it, and a census whose
    keys are class objects is a census nobody can paste into a report.
    """
    return {
        model._meta.label: declared
        for model in _concrete_models()
        if (declared := lifecycle_of(model)) is not None
    }


def undeclared_models() -> list[type[models.Model]]:
    """Every concrete model that has declared nothing. **Rule 31's subject.**

    The complement of `declared_lifecycles()` over the same population, which
    is the property the census test pins: reader plus reader equals registry,
    with nothing falling between them. Sorted by label so a backlog printed on
    two runs of the gate is the same list in the same order.
    """
    return sorted(
        (model for model in _concrete_models() if lifecycle_of(model) is None),
        key=lambda model: model._meta.label,
    )


def _concrete_models() -> Iterator[type[models.Model]]:
    """The population both readers are over: what `get_models()` returns.

    Django's registry already excludes abstract bases and, by default, the
    auto-created through tables of a plain `ManyToManyField` — a table nobody
    declared a model for is a table nobody can put an attribute on, and rule 31
    would be asking a product to declare a lifecycle for a row Django owns.
    """
    from django.apps import apps as django_apps

    yield from django_apps.get_models()
