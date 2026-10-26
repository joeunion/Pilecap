"""The meter vocabulary: `<app>.<noun>.<unit>`, declared in each app's `meters.py` (ADR usage-1).

A `meters.py` holds meter names and nothing else that is an uppercase string: every one counts.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from django.core.exceptions import ImproperlyConfigured

from apps.core.discovery import imported
from apps.core.exceptions import Invalid, Remedy
from apps.usage import types as usage_types

#: The number of segments in `<app>.<noun>.<unit>`.
NAME_SEGMENTS = 3

#: One segment: lowercase, digits and underscores, starting with a letter. The
#: same shape a Django app label and a Python identifier both already hold, so a
#: meter name is safe as a dictionary key, a JSON key, a Prometheus-style series
#: name and a settings key without anybody quoting it.
_SEGMENT = re.compile(r"^[a-z][a-z0-9_]*$")

#: The longest meter name a column will hold. Generous: three segments of a
#: sensible length, and it is `models.UsageEntry.meter`'s `max_length` — named
#: here rather than there because this module owns the grammar.
MAX_METER_LENGTH = 128


def declared_meters() -> dict[str, frozenset[str]]:
    """Every installed app's declared meter names, keyed by app label — read live, never cached.

    Every uppercase, non-underscored `str` of the module is a meter, an imported name included.
    """
    found: dict[str, frozenset[str]] = {}
    for config, module in imported("meters"):
        names = {
            value
            for attribute in dir(module)
            if attribute.isupper() and not attribute.startswith("_")
            for value in [getattr(module, attribute)]
            if isinstance(value, str)
        }
        if names:
            found[config.label] = frozenset(names)
    return found


def grammar_complaint(name: str, *, app_label: str | None = None) -> str:
    """Why this name is not `<app>.<noun>.<unit>`, or `""` when it is.

    A string rather than an exception, because the two callers want different
    tiers out of the same question: `validate_declared_meters` turns it into a
    boot refusal and `check_meter` into a domain refusal. Returning the sentence
    keeps one description of the grammar instead of two that drift.
    """
    if len(name) > MAX_METER_LENGTH:
        return (
            f"{name!r} is longer than {MAX_METER_LENGTH} characters, which is what "
            f"the ledger's `meter` column holds."
        )
    segments = name.split(".")
    if len(segments) != NAME_SEGMENTS:
        return (
            f"{name!r} is not <app>.<noun>.<unit> — three segments, so that a reader "
            f"of an invoice line can tell WHO spent it, WHAT was spent and IN WHAT "
            f"UNIT without a second document."
        )
    if not all(_SEGMENT.match(segment) for segment in segments):
        return (
            f"{name!r} has a segment that is not lowercase letters, digits and "
            f"underscores starting with a letter. A meter name is a dictionary key, "
            f"a JSON key and a settings key, and a name that needs quoting in one of "
            f"them is a name that will be spelled two ways."
        )
    if app_label is not None and segments[0] != app_label:
        return (
            f"{name!r} is declared in apps/{app_label}/meters.py but claims the app "
            f"{segments[0]!r}. The first segment is the declaring app's label — that "
            f"is what makes 'declared by the app that spends it' a check."
        )
    return ""


def validate_declared_meters() -> dict[str, frozenset[str]]:
    """Refuse the whole vocabulary if any declared name breaks the grammar.

    Called from `UsageConfig.ready()`, so a bad name stops the process at boot
    rather than surfacing as a refused write in whichever request first tried to
    record it. Returns the registry it validated, so a caller that wants both
    does not walk twice.
    """
    registry = declared_meters()
    for app_label, names in sorted(registry.items()):
        for name in sorted(names):
            complaint = grammar_complaint(name, app_label=app_label)
            if complaint:
                raise ImproperlyConfigured(
                    f"apps/{app_label}/meters.py declares a meter that is not a meter "
                    f"name: {complaint} A meter is a published contract — an invoice "
                    f"line, a dashboard series and a tenant's threshold all match on "
                    f"this string — so it is refused here, at boot, rather than "
                    f"accruing money under a name nothing else can find."
                )
    return registry


def check_meter(name: str) -> str:
    """Refuse a meter name no installed app has declared.

    Two failures this catches, both otherwise silent for months: a typo, which
    accrues under a name no aggregate sums and no threshold matches; and a meter
    invented at a call site, which is a published contract with no declaration
    that nobody can find when it has to change.

    It raises `Invalid`, the domain's word, so the caller that hears it maps it
    like any other refusal (house rule 14) — even though today's only callers
    are services and activities rather than a door.
    """
    complaint = grammar_complaint(name)
    if complaint:
        raise Invalid({"meter": [complaint]})
    declared = declared_meters()
    app_label = name.split(".")[0]
    if app_label not in declared:
        # The whole name and not only its first segment: this message reaches a
        # caller who sent `not.a.meter`, and a refusal that quotes `'not'` back
        # at them is a refusal about a string they did not type.
        raise Invalid(
            {
                "meter": [
                    f"No installed app labelled {app_label!r} declares any meters, so "
                    f"{name!r} is not one."
                ]
            }
        )
    if name not in declared[app_label]:
        raise Invalid({"meter": [f"{name!r} is not declared in apps/{app_label}/meters.py."]})
    return name


def check_reported_meters(names: Iterable[str]) -> list[str]:
    """Refuse a READ that names a meter no installed app declares. **The door's half.**

    `check_meter` above guards the WRITE seam: a name nobody declared never
    accrues money. This guards the read, and until it existed a typo and a real
    meter sitting at zero were byte-identical answers — `?meters=not.a.meter`
    came back `200` zero-filled, while the operation's own contract promised the
    zero-filling was there "so you can tell none from I asked the wrong
    question." It was not tellable, and an agent cannot ask a person to
    fix a spelling it was never told about.

    Three things this raise site does that `check_meter` deliberately does not:

    * it reports **every** bad name in one answer, under the query parameter's
      own key (`meters`), so a caller that misspelled two does not discover the
      second on the next round trip;
    * it names the registry — which apps declare meters here, and what they
      declare — because a refusal that says "no" without saying what the
      vocabulary IS leaves the caller guessing at a closed set;
    * it carries **remedies** pointing at the vocabulary door
      (`METERS_DESTINATION`), which is the destination grammar: the way out of
      this refusal is one request, and the refusal says which.

    It lives here, in the module that owns the vocabulary, rather than in a
    door: composed once, both doors inherit it through `api.report`, and neither
    is free to describe the same refusal differently.
    """
    wanted = list(names)
    complaints: list[str] = []
    for name in wanted:
        try:
            check_meter(name)
        except Invalid as refusal:
            complaints.extend(
                message for messages in refusal.errors.values() for message in messages
            )
    if not complaints:
        return wanted
    raise Invalid(
        {"meters": [*complaints, _vocabulary_sentence()]},
        remedies=(
            Remedy("List the meters this deployment declares", usage_types.METERS_DESTINATION),
        ),
    )


def every_declared_meter() -> list[str]:
    """Every declared name, flattened and sorted. The one walk both readers share.

    Sorted so that anything derived from it — a sentence, a published example —
    is the same in two processes reading the same tree. An unsorted set would
    make the OpenAPI document differ run to run, which is the property N167c
    protects for `introspect` and which matters here for exactly the same
    reason: a document nobody can diff is a document nobody checks.
    """
    return sorted(name for names in declared_meters().values() for name in names)


def example_meter() -> str | None:
    """The meter the published document shows a caller, or `None` if there is none.

    `UsageReportOut`'s example used to be keyed
    `completions.tokens.input` — a meter no deployment declares, written when
    the read door zero-filled anything it was handed. The undeclared-meter
    refusal turned that into a `400` a stranger hits on their first copy-paste,
    in the OpenAPI document, the reference page and `get_usage.outputSchema` at
    once. The fix is not a better constant: a constant is right until the
    vocabulary moves, and nothing says when it does — which is the whole of how
    the wrong one survived into a published contract.

    So the example is DERIVED, from the same registry the catalogue route
    publishes and the read door refuses against. The **first name in sorted
    order** rather than a chosen one, because choosing would put a second
    opinion about the vocabulary in a second place; on this tree that is
    `files.storage.bytes`, and on a product's tree it is whatever that product
    declares first, with nothing to edit here.

    `None` when nothing is declared, and the caller renders an empty example.
    That is not a degradation: a deployment with no declared meters has a read
    door that can only ever answer `{}`, so an empty example is the only one
    that is not a lie — and there is no name it could show that the door would
    not refuse.
    """
    every = every_declared_meter()
    return every[0] if every else None


def _vocabulary_sentence() -> str:
    """What this deployment's vocabulary actually is, said in one line.

    Derived from the live registry rather than written down, for the same reason
    the catalogue route is derived: a sentence listing meters by hand is wrong
    the morning after the next app declares one, and nothing would fail.
    """
    declared = declared_meters()
    if not declared:
        return (
            "No installed app declares any meters in this deployment, so there is no "
            "meter to ask for yet."
        )
    return "The meters this deployment declares are: " + ", ".join(every_declared_meter()) + "."
