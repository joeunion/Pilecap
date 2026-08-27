"""What goes in the archive, DERIVED from the model registry.

**A hand-written list of tables is the defect this module exists not to be.**
A sweep once found four tables holding an erased person that nobody had listed,
found with a sweep of the registry rather than by reading a service —
because a service says nothing about the tables it does not touch. An export
built from a list has the mirror of that bug and it is quieter: the table
somebody added on Thursday is simply not in the customer's archive, the archive
still opens, every count in it is right, and nobody finds out until the customer
tries to leave.

So the population here is `django_apps.get_models()` narrowed by one question —
**does this model carry a `tenant`** — and the only thing anybody writes down is
the SUBTRACTION, with the reason for each entry. That is the same shape
`test_erasure_residue.py::RETAINED` has, and it is the shape that survives a
product: a new scoped model is in the archive the day it is born, and taking one
out is a sentence a reviewer can disagree with.

## The two ways a model leaves the population

* **`export_excluded = True` on the model**, beside `export_excluded_reason`.
  This is the forward path and the one a product uses on its own tables — the
  declaration lives where the person adding the table is already standing, the
  same move `append_only` and `lifecycle` make (ADR core-6, core-13).
* **`EXCLUSIONS` below**, for a model this app does not own. `apps.exports` may
  not edit `apps/events/models.py` to say what an export does with an event,
  and a rung that could would be one file every app in a parallel wave has to
  touch. Declaring it here is the same trade `LifecycleRegistry` makes for
  third-party tables, one layer up.

**A bare exclusion refuses.** `export_excluded = True` with no reason, an
`EXCLUSIONS` entry whose reason is a word, a model that is excluded in both
places at once, and an entry naming a model that is not in the population are
all `ValueError` at census time — the tier `core.lifecycle` and
`core.exceptions.register_refusal` already set for a malformed declaration. An
exclusion nobody had to justify is a table quietly dropped from somebody's
archive.

## What comes out of a row that stays

Every concrete field, except the **encrypted** ones. That population is derived
too, off rule 15's own field types (`core.fields.EncryptedCharField` /
`EncryptedJSONField`) rather than off a list of column names, and each exclusion
is named in the manifest with its basis — so an archive says what it is not
telling you rather than being silently short. Decrypting a tenant's stored
provider credentials into a zip that leaves the deployment would undo rule 15 at
the one door built to send data outward, which is exactly where it would not be
noticed.

DOES NOT COVER — declared:

* **field-level semantics.** A derived `@property` is not a column, and the
  JSONL is the stored truth. The manifest says which fields are in it; it does
  not promise that reading them reconstitutes every computed value the API
  shows.
* **a model that is not in Django's registry at all** — unmanaged tables,
  views, anything created outside Django. `get_models()` cannot see them and
  neither can this.
* **whether an exclusion's reason is a GOOD one.** The grammar is closed here
  (present, long enough to be a clause); the judgement is review's, exactly as
  it is for a `lifecycle` reason or a `# reach:` sentence.
* **free text a product writes into its own columns.** This decides which
  tables and which fields travel. What a tenant put inside a `notes` column is
  the tenant's, and it travels with it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from django.apps import apps as django_apps
from django.db import models

from apps.core.fields import EncryptedCharField, EncryptedJSONField
from apps.core.models import is_org_scoped

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

__all__ = [
    "EXCLUSIONS",
    "Disposition",
    "FieldExclusion",
    "dispositions",
    "exclusions",
    "plan",
    "encrypted_fields",
    "exported_field_names",
    "scoped_models",
]

#: The class attribute a model sets to leave the archive, and the one beside it
#: that says why. Named once, here, so the model that declares them, the reader
#: below and the tests all say the same words — the discipline
#: `APPEND_ONLY_ATTR` and `LIFECYCLE_ATTR` already follow.
EXCLUDED_ATTR = "export_excluded"
EXCLUDED_REASON_ATTR = "export_excluded_reason"

#: The column every model in the population carries. Read as a field name rather
#: than by `issubclass(TenantScopedModel)`, for `core.models.is_org_scoped`'s
#: reason: the declaration that matters is what the database actually holds, and
#: a product that reached the same shape another way is still a tenant's data.
TENANT_FIELD = "tenant"

#: Long enough to force a clause, short enough that a real reason clears it. The
#: same number and the same reasoning as `core.lifecycle.MIN_REASON` and
#: `quality/gate.py::MIN_REASON`: an escape hatch nobody has to justify is an
#: off switch.
MIN_REASON = 12

#: The field types rule 15 requires a secret-shaped column to be. Derived from
#: the types rather than from a list of column names, so a product that adds a
#: fourth encrypted column gets it excluded on the day it lands.
ENCRYPTED_TYPES: tuple[type[models.Field[Any, Any]], ...] = (
    EncryptedCharField,
    EncryptedJSONField,
)

#: The models this app takes out of the archive, and why. Every entry is a table
#: `apps.exports` does not own — see this module's docstring for why they are
#: here rather than on the models themselves.
#:
#: **Three, and the list is meant to stay short.** Every entry is a row a
#: customer might reasonably expect in their own archive and is not getting, so
#: each reason has to answer that reader rather than a reviewer.
EXCLUSIONS: dict[str, str] = {
    "events.Event": (
        "Ratified: an event payload is the WITNESSED record of what was "
        "emitted, and it is the one place erasure deliberately does NOT reach — "
        "`apps/accounts/tests/test_erasure_residue.py::RETAINED` declares "
        "`events.Event.payload` as a retention and pins that it still holds the "
        "pre-erasure address. That retention is argued for a payload sitting inside "
        "the deployment, under the deployment's own controls, serving replay "
        "fidelity. An export is a file that LEAVES: it is mailed, copied to a laptop "
        "and kept for as long as somebody keeps files, and carrying an erased "
        "person's identifiers out in it would make the erasure a promise that held "
        "everywhere except the one door built to send data outward. The tenant's own "
        "history is readable at the events door, live, under those controls."
    ),
    "core.IdempotencyRecord": (
        "request-replay plumbing rather than the tenant's data: a row here is a "
        "digest of a request body and the response we already sent, it is scoped to "
        "a credential rather than to anything a person would recognise, and it lives "
        "24 hours (`IDEMPOTENCY_TTL_HOURS`). An archive of it would be a list of "
        "hashes, mostly empty by the time anybody opened the file, describing "
        "requests whose real records are in every other table here."
    ),
    "accounts.ApiToken": (
        "credential material. The row is a bearer token's digest, its ceiling and its "
        "expiry — a map of the keys to this tenant's account — and an archive is a "
        "file that travels. A digest is not a usable credential, and the ceiling and "
        "the names still tell a reader which doors are open and to whom. The same "
        "list is readable, live, at the tokens door by the person who minted them, "
        "which is where a credential inventory belongs. Portability does not require "
        "exporting the locks."
    ),
}


@dataclass(frozen=True)
class FieldExclusion:
    """One column left out of a row, and the basis for leaving it out."""

    name: str
    basis: str


@dataclass(frozen=True)
class Disposition:
    """One model that is in the archive, and how it is read.

    `org_scoped` is what decides whether a **subtree** export can carry it at
    all: `visible_to` narrows a row to a part of the network and there is
    nothing to narrow on a model that only carries a tenant, so a branch's
    export skips those rather than handing a branch the whole customer.
    `apps.exports.services` is where that decision is spent; this is where it is
    read off the schema.
    """

    label: str
    model: type[models.Model]
    org_scoped: bool
    excluded_fields: tuple[FieldExclusion, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        """The columns that travel, in the model's own declaration order."""
        left_out = {one.name for one in self.excluded_fields}
        return tuple(
            str(field.name)
            for field in self.model._meta.concrete_fields
            if field.name not in left_out
        )


def _population(source: Iterable[type[models.Model]] | None) -> list[type[models.Model]]:
    """The registry, or whatever a caller handed in instead.

    Parameterised for the same reason `scopes.family_freeze_findings` takes its
    `live` argument: a census that could only ever be run against the truth is a
    census nobody can prove fires. `tests/test_census.py` plants a scoped model
    through here and through the real registry both, because the two answer
    different questions — one proves the pin can fail, the other proves the
    population is really derived.
    """
    return list(django_apps.get_models() if source is None else source)


def scoped_models(
    source: Iterable[type[models.Model]] | None = None,
) -> list[type[models.Model]]:
    """Every concrete model a tenant owns rows in, sorted by label.

    Proxies and unmanaged models are out: a proxy is another model's table seen
    twice, and an unmanaged one is a table Django did not make and cannot
    promise the shape of.
    """
    return sorted(
        (
            model
            for model in _population(source)
            if not model._meta.proxy
            and model._meta.managed
            and any(field.name == TENANT_FIELD for field in model._meta.concrete_fields)
        ),
        key=lambda model: str(model._meta.label),
    )


def encrypted_fields(model: type[models.Model]) -> tuple[FieldExclusion, ...]:
    """The columns of this model that rule 15 keeps encrypted at rest.

    Named in the manifest rather than silently dropped: an archive that is short
    a column and does not say so is worse than one that refuses, because every
    count in it is still right.
    """
    return tuple(
        FieldExclusion(
            name=str(field.name),
            basis=(
                f"encrypted at rest ({type(field).__name__}, house rule 15) — the "
                "plaintext is recoverable only with this deployment's keys, and an "
                "archive that leaves the deployment must not carry it"
            ),
        )
        for field in model._meta.concrete_fields
        if isinstance(field, ENCRYPTED_TYPES)
    )


def _declared_exclusion(model: type[models.Model]) -> str | None:
    """This model's own `export_excluded` reason, or `None` when it declares none.

    A bare `True` refuses here, at the moment the census is taken, naming the
    model — the same tier `Lifecycle.__post_init__` refuses a `purged`
    declaration with nothing purging it.
    """
    if not bool(getattr(model, EXCLUDED_ATTR, False)):
        return None
    reason = str(getattr(model, EXCLUDED_REASON_ATTR, "") or "").strip()
    if len(reason) < MIN_REASON:
        raise ValueError(
            f"{model._meta.label} declares `{EXCLUDED_ATTR} = True` and no "
            f"`{EXCLUDED_REASON_ATTR}`. A table taken out of a customer's own archive "
            "is a DECISION, and excluded-by-decision and excluded-by-nobody-thinking "
            "look identical in a schema. Write the sentence a reviewer can disagree "
            f"with (at least {MIN_REASON} characters), or let the row travel."
        )
    return reason


def exclusions(source: Iterable[type[models.Model]] | None = None) -> dict[str, str]:
    """Every model taken out of the archive, by label, with its reason.

    Both halves at once, and they may not overlap: a model that declares its own
    exclusion AND is named in `EXCLUSIONS` is two opinions about one table, which
    is refused loudly rather than resolved by whichever the reader met first —
    `LifecycleRegistry.declare` refuses the same shape for the same reason.

    An entry naming a model that is not in the population refuses too. A stale
    exclusion is the quietest way this file could start lying: it reads as a
    considered decision about a table that no longer exists, and the day
    somebody re-adds a model by that name it is excluded by an argument written
    about something else.
    """
    population = {str(model._meta.label): model for model in scoped_models(source)}
    found: dict[str, str] = {}

    for label, model in population.items():
        declared = _declared_exclusion(model)
        if declared is not None:
            found[label] = declared

    for label, reason in EXCLUSIONS.items():
        named = population.get(label)
        if named is None:
            raise ValueError(
                f"EXCLUSIONS names {label!r} and no model by that label carries a "
                f"`{TENANT_FIELD}` in this deployment. An exclusion for a table that is "
                "not in the population reads as a considered decision about something "
                "that is not there, and it would silently start applying to whatever "
                "next takes the name. Remove the entry, or restore the model."
            )
        if label in found:
            raise ValueError(
                f"{label} declares its own `{EXCLUDED_ATTR}` AND is named in EXCLUSIONS — "
                "two opinions about one table. A model that can carry the declaration "
                "carries it; drop the entry here."
            )
        if len(reason.strip()) < MIN_REASON:
            raise ValueError(
                f"EXCLUSIONS[{label!r}] carries no reason worth the name. A table taken "
                "out of a customer's own archive is a decision somebody has to be able "
                f"to disagree with (at least {MIN_REASON} characters)."
            )
        found[label] = reason.strip()

    return found


def dispositions(source: Iterable[type[models.Model]] | None = None) -> dict[str, Disposition]:
    """What the archive contains, by model label. **The census.**

    `(concrete registry models carrying a tenant) minus the declared
    exclusions` — nothing here is a name somebody typed, and the day a scoped
    model is added it is in this answer with no edit to this file.
    """
    left_out = exclusions(source)
    return {
        str(model._meta.label): Disposition(
            label=str(model._meta.label),
            model=model,
            org_scoped=is_org_scoped(model),
            excluded_fields=encrypted_fields(model),
        )
        for model in scoped_models(source)
        if str(model._meta.label) not in left_out
    }


def plan(
    *, tenant_wide: bool, source: Iterable[type[models.Model]] | None = None
) -> tuple[dict[str, Disposition], dict[str, str]]:
    """`(carried, skipped)` for one export's width.

    The second half is the honest one. A **subtree** export cannot carry a model
    that has no `organization`: there is nothing for `visible_to` to narrow on,
    so the only way to put such a table in a branch's archive is to read it with
    `for_tenant` alone — which is the whole customer's rows, handed to one
    branch, in a file. So those models are SKIPPED, with the reason written into
    the manifest beside the ones that travelled.

    Saying it in the manifest rather than silently is the entire point. An
    archive that is quietly short a table looks exactly like a tenant that never
    had one, and the reader is a customer who is leaving and cannot ask.

    A tenant-wide export skips nothing: its hat is the tenant's root, whose
    subtree is the whole tree, so `visible_to(root)` and `for_tenant` see the
    same rows and the org-scoped question stops mattering.
    """
    carried = dispositions(source)
    if tenant_wide:
        return carried, {}
    skipped = {
        label: (
            "this export covers one organization and everything under it, and this "
            "table carries no organization to narrow on — every row in it belongs to "
            "the tenant as a whole. Ask for a tenant-wide export to receive it."
        )
        for label, disposition in carried.items()
        if not disposition.org_scoped
    }
    return {
        label: disposition for label, disposition in carried.items() if label not in skipped
    }, skipped


def exported_field_names(model: type[models.Model]) -> Sequence[str]:
    """The columns of one model that travel. Convenience over `Disposition`.

    Here rather than only on the dataclass because the archive writer asks the
    question per row and a reader looking for "what does an exported row look
    like" should find one answer, not two.
    """
    left_out = {one.name for one in encrypted_fields(model)}
    return tuple(
        str(field.name) for field in model._meta.concrete_fields if field.name not in left_out
    )
