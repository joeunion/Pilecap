"""The key and the `url_name` are one vocabulary: a door under a shorter noun is declared.

`<kind>.<verb>` with `<kind>-<verb>` unmounted and `<tail>-<verb>` mounted (`kind` ends `_<tail>`)
is a door the join cannot find; the noun declares it in `act_doors` (`apps/files/models.py`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Set

from apps.core import authz, verbs

#: The recorded backlog: a near-miss key, and the rider that adds its `act_doors` line.
KNOWN_GAPS: dict[str, str] = {
    "delivery_policy.retire": "the comms act_doors rider (policy-retire)",
    "message_template.retire": "the comms act_doors rider (template-retire)",
    "workflow_run.cancel": "WorkflowRun has no act_doors line; run-cancel serves it — until it has",
    "workflow_run.replay": "WorkflowRun has no act_doors line; run-replay serves it — until it has",
}


def near_misses(
    keys: Iterable[tuple[str, str, str]],
    mounted: Set[str],
    doors: Mapping[str, str],
) -> dict[str, str]:
    """`{key: the mounted door it misses}` for each `(key, kind, verb)` whose door is absent."""
    found: dict[str, str] = {}
    for key, kind, verb in keys:
        if doors[key] in mounted:
            continue
        for name in sorted(mounted):
            noun, _, served = name.rpartition("-")
            if served == verb and noun != kind and kind.endswith(f"_{noun}"):
                found[key] = name
    return found


def test_every_door_under_a_shorter_noun_is_declared_or_the_recorded_backlog() -> None:
    """The census over the live vocabulary and mount; it prints the population it judged."""
    registry = authz.kind_registry()
    vocabulary = authz.vocabulary()
    acts = [
        (key, p.kind, p.verb)
        for key, p in sorted(vocabulary.items())
        if p.verb not in ("read", "create")
    ]
    doors = {key: verbs.door_url_name(registry.get(kind), verb, kind) for key, kind, verb in acts}
    mounted = verbs.mounted_url_names()
    missed = near_misses(acts, mounted, doors)
    print(
        f"act doors: {len(vocabulary)} keys, {len(acts)} acts, "
        f"{sum(1 for k in acts if doors[k[0]] not in mounted)} with no door, "
        f"{len(missed)} near misses: {sorted(missed)}"
    )
    assert len(acts) >= 50, "the act population came back nearly empty"
    assert sorted(missed) == sorted(KNOWN_GAPS), (
        f"near misses {missed}; recorded {sorted(KNOWN_GAPS)} — declare the door in the "
        "noun's `act_doors`, and take an entry out of KNOWN_GAPS when its line lands"
    )


def test_a_door_under_a_shorter_noun_is_named_and_a_declared_one_is_not() -> None:
    """Synthetic: `report_template.retire` misses `template-retire`; declared, it does not."""
    keys = [("report_template.retire", "report_template", "retire")]
    mounted = {"template-retire", "report_template-update"}

    derived = {"report_template.retire": "report_template-retire"}
    assert near_misses(keys, mounted, derived) == {"report_template.retire": "template-retire"}

    declared = {"report_template.retire": "template-retire"}
    assert near_misses(keys, mounted, declared) == {}
