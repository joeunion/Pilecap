"""What two or more sections share, and what they need at import time."""

from __future__ import annotations

import sys

import yaml

from quality import partition as PART
from quality import worlds as W

#: The repository root, read from a sibling at a fixed depth: it holds wherever this code lives.
ROOT = PART.ROOT

_DOC: dict = yaml.safe_load((ROOT / "quality" / "rules.yaml").read_text())

#: The engine's own recorded numbers (`engine:` in quality/rules.yaml): each
#: leg's population, the drawers leg's ceiling in seconds, the memo's keep.
ENGINE: dict[str, dict[str, int]] = {
    str(leg): {str(k): int(v) for k, v in (numbers or {}).items()}
    for leg, numbers in (_DOC.get("engine") or {}).items()
}


def engine_number(leg: str, key: str) -> int:
    """One recorded engine number; a missing one is broken enforcement, never zero."""
    try:
        return ENGINE[leg][key]
    except KeyError:
        print(
            f"!! COULD NOT LOOK: quality/rules.yaml `engine: {leg}: {key}` is not recorded — "
            "the engine's own legs judge against the recorded number, and an absent one is "
            "a leg that cannot fail",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


def engine_leg(leg: str, *, fired: int, silent: int) -> None:
    """Judge one engine leg's canaries and negatives against `engine: <leg>:` — the one judge.

    Each half is a `Bound` floor: under it is `<LEG> LEG SHORT`, exit 2; over
    it is the one room note (`quality.worlds.room_note`).
    """
    for kind, got in (("canaries", fired), ("negatives", silent)):
        bound = W.Bound(
            direction="floor",
            recorded=engine_number(leg, kind),
            measured=got,
            home=f"quality/rules.yaml `engine: {leg}:`",
            klass=kind,
            subject=f"the {leg} leg's {kind}",
            word="population",
        )
        if bound.breached:
            RUN.broken.append(
                f"{leg.upper()} LEG SHORT — {bound.breach_clause()}; the lines above name which"
            )
        room = W.room_note(bound)
        if room:
            say(room)


def engine_probes(leg: str, answered: int) -> None:
    """Judge a reader census's answered probes against `engine: <leg>: probes`."""
    bound = W.Bound(
        direction="floor",
        recorded=engine_number(leg, "probes"),
        measured=answered,
        home=f"quality/rules.yaml `engine: {leg}:`",
        klass="probes",
        subject=f"the {leg} census's probes",
        word="population",
    )
    room = W.room_note(bound)
    if room:
        say(room)


#: The census whose own `base` line is the judged-shape sentence.
JUDGED_SHAPE_CENSUS = "quality/djb/rituals/divergence.py"


from quality.engine.world import RUN, say  # noqa: E402
