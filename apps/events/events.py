"""The names this app declares — and the registry every other app's names live in.

Two jobs, and they belong together:

1. **This app's own lifecycle events**, as constants, like any other app's
   `events.py`. There is one — a tenant added a subscriber — and the note below
   says why the two obvious others are not here.

2. **`declared_names()`** — every event name every installed app declares. It is
   the same registry `manage.py introspect` reports, read from the real
   `events.py` modules rather than from a list somebody maintains, and it is
   what `services.emit` validates a name against. An event name is a published
   contract: a webhook subscriber matches on it and a typo is an event that
   silently reaches nobody, so the name has to exist in the emitting app's
   declaration before it can be emitted.

The grammar is `<app>.<noun>.<past-tense verb>` (house rule 16), and the first
segment is the emitting app's label — which is what makes "declared by the
emitting app" a check rather than a hope.
"""

from __future__ import annotations

import importlib
import importlib.util

from django.apps import apps as django_apps

from apps.core.exceptions import Invalid

#: A tenant added a place to deliver its events to.
ENDPOINT_REGISTERED = "events.endpoint.registered"

# There is deliberately **no `events.delivery.dead_lettered` event**, and the
# reason is worth writing down: an event emitted by the spine is fanned out *by*
# the spine. A subscriber that is failing — which is precisely when a delivery
# dead-letters — would have the "your delivery failed" event delivered to it,
# fail again, dead-letter again, and emit again. A product that wants a
# notification on a dead letter reads the `Delivery` rows (they are indexed on
# `dead_lettered_at`) or gets it from the sink; the loop is not worth the
# convenience. The same reasoning applies to a replay.

# The number of segments in `<app>.<noun>.<past-verb>`.
NAME_SEGMENTS = 3


def declared_names() -> dict[str, frozenset[str]]:
    """Every installed app's declared event names, keyed by app label.

    Read from the live app registry, never cached: an app that is installed has
    its `events.py` imported here and its uppercase string constants collected,
    which is exactly what `introspect` reports. Not caching is deliberate — the
    number of apps is small, this runs on a write path a handful of times a
    second at most, and a cache would be one more thing to invalidate in a test
    that plants a module.
    """
    found: dict[str, frozenset[str]] = {}
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module_name = f"{config.name}.events"
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
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


def check_name(name: str) -> str:
    """Refuse an event name the emitting app has not declared.

    Two failures this catches, both otherwise silent for months: a typo
    (`orders.order.creted` reaches no subscriber and raises nothing), and an
    event invented at a call site (a published contract with no declaration,
    which nobody can find when it has to change). The registry is the real one —
    every installed app's `events.py`, the same list `introspect` prints.

    It raises `Invalid`, the domain's word, so the door that hears it maps it
    like any other refusal (house rule 14).
    """
    segments = name.split(".")
    if len(segments) != NAME_SEGMENTS or not all(segment.strip() for segment in segments):
        raise Invalid({"name": [f"{name!r} is not <app>.<noun>.<past-verb>."]})
    declared = declared_names()
    app_label = segments[0]
    if app_label not in declared:
        raise Invalid(
            {"name": [f"No installed app labelled {app_label!r} declares any event names."]}
        )
    if name not in declared[app_label]:
        raise Invalid({"name": [f"{name!r} is not declared in apps/{app_label}/events.py."]})
    return name
