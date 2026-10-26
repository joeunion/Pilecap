"""This app's event names, and `declared_names()`: every installed app's, as `emit` checks them.

The grammar is `<app>.<noun>.<past-tense verb>` (rule 16); the first segment is the emitter's label.
"""

from __future__ import annotations

from apps.core.discovery import imported
from apps.core.exceptions import Invalid
from apps.core.roads import road

#: A tenant added a place to deliver its events to.
ENDPOINT_REGISTERED = "events.endpoint.registered"

# why-not `events.delivery.dead_lettered`: the spine fans it out, so a failing subscriber loops.

# The number of segments in `<app>.<noun>.<past-verb>`.
NAME_SEGMENTS = 3


def declared_names() -> dict[str, frozenset[str]]:
    """Every installed app's declared event names, keyed by app label; read live, never cached."""
    found: dict[str, frozenset[str]] = {}
    for config, module in imported("events"):
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


@road(
    "event_name",
    example="apps/events/tests/test_services.py::test_an_undeclared_name_is_refused_and_writes_nothing",
)
def check_name(name: str) -> str:
    """Refuse an event name the emitting app has not declared, as `Invalid` (rule 14)."""
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
