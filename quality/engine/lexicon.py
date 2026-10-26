"""A product's own service verbs beside house rule 16's lexicon: the one reader, Django-free."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from apps.core.reach import RULES_DRAWER, read_drawer

#: The key the product's own service verbs live under in its drawer (house rule 16).
PRODUCT_VERBS_KEY = "service_verbs"
#: The particles that make a phrasal verb, whose FIRST word inflects (`pick_up` → `picked_up`).
PARTICLES = frozenset({"up", "down", "out", "in", "off", "on", "over", "back", "away", "through"})
#: A verb is lower-case words joined by `_`, each starting with a letter.
VERB_SHAPE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z][a-z0-9]*)*")


def product_verb_problems(product: object, platform: Iterable[str]) -> list[str]:
    """One line per refused word of a drawer's `service_verbs:`, naming it; absent is none."""
    if product is None:
        return []
    if not isinstance(product, list):
        return [
            f"{RULES_DRAWER}: `{PRODUCT_VERBS_KEY}:` is a {type(product).__name__}, not a list of "
            "words — it is a bare word list, the shape rule 16's own lexicon is"
        ]
    taken = set(platform)
    problems: list[str] = []
    for word in product:
        if not isinstance(word, str) or not VERB_SHAPE.fullmatch(word):
            problems.append(
                f"{RULES_DRAWER}: `{word}` under `{PRODUCT_VERBS_KEY}:` is no verb — lower-case "
                "words joined by `_`, each starting with a letter"
            )
        elif word in taken:
            problems.append(
                f"{RULES_DRAWER}: `{word}` under `{PRODUCT_VERBS_KEY}:` is already house rule 16's "
                f"own verb in quality/rules.yaml — delete it from the drawer"
            )
        taken.add(str(word))
    return problems


def service_verb_lexicon(root: Path, platform: Iterable[str]) -> tuple[str, ...]:
    """Rule 16's lexicon: the platform's verbs, then the drawer's; `ValueError` names a refusal."""
    platform = tuple(str(v) for v in platform)
    product = read_drawer(root).get(PRODUCT_VERBS_KEY)
    problems = product_verb_problems(product, platform)
    if problems:
        raise ValueError("; ".join(problems))
    return (*platform, *(str(v) for v in product or ()))


def tense_word(verb: str) -> str:
    """The tense-carrying word of an event's verb: the one before a particle; `pick_uped`: `up`."""
    *head, last = verb.split("_")
    if head and last in PARTICLES:
        return head[-1]
    stem = last.removesuffix("ed")
    undoubled = stem[:-1] if stem[-1:] == stem[-2:-1] else stem
    bare = {stem, undoubled} & PARTICLES if head and stem != last else set()
    return bare.pop() if bare else last


#: The irregular verbs an event names, base → (participle, *simple past): rule 16 and the scaffold.
IRREGULAR_PAST: dict[str, tuple[str, ...]] = {
    "begin": ("begun", "began"),
    "bend": ("bent",),
    "bind": ("bound",),
    "break": ("broken", "broke"),
    "bring": ("brought",),
    "broadcast": ("broadcast",),
    "build": ("built",),
    "buy": ("bought",),
    "cancel": ("cancelled", "canceled"),
    "cast": ("cast",),
    "catch": ("caught",),
    "choose": ("chosen", "chose"),
    "cut": ("cut",),
    "deal": ("dealt",),
    "do": ("done", "did"),
    "draw": ("drawn", "drew"),
    "drive": ("driven", "drove"),
    "emit": ("emitted",),
    "feed": ("fed",),
    "find": ("found",),
    "forbid": ("forbidden", "forbade"),
    "forget": ("forgotten", "forgot"),
    "forgive": ("forgiven", "forgave"),
    "freeze": ("frozen", "froze"),
    "give": ("given", "gave"),
    "go": ("gone", "went"),
    "grow": ("grown", "grew"),
    "hear": ("heard",),
    "hide": ("hidden", "hid"),
    "hit": ("hit",),
    "hold": ("held",),
    "keep": ("kept",),
    "know": ("known", "knew"),
    "lay": ("laid",),
    "lead": ("led",),
    "leave": ("left",),
    "lend": ("lent",),
    "let": ("let",),
    "lose": ("lost",),
    "make": ("made",),
    "mean": ("meant",),
    "meet": ("met",),
    "override": ("overridden", "overrode"),
    "pay": ("paid",),
    "put": ("put",),
    "quit": ("quit",),
    "read": ("read",),
    "rebuild": ("rebuilt",),
    "redo": ("redone", "redid"),
    "rerun": ("rerun", "reran"),
    "resend": ("resent",),
    "reset": ("reset",),
    "rewrite": ("rewritten", "rewrote"),
    "ride": ("ridden", "rode"),
    "rise": ("risen", "rose"),
    "run": ("run", "ran"),
    "say": ("said",),
    "see": ("seen", "saw"),
    "sell": ("sold",),
    "send": ("sent",),
    "set": ("set",),
    "shake": ("shaken", "shook"),
    "show": ("shown", "showed"),
    "shut": ("shut",),
    "signal": ("signalled", "signaled"),
    "sink": ("sunk", "sank"),
    "speak": ("spoken", "spoke"),
    "spend": ("spent",),
    "spin": ("spun",),
    "split": ("split",),
    "spring": ("sprung", "sprang"),
    "stand": ("stood",),
    "steal": ("stolen", "stole"),
    "stick": ("stuck",),
    "strike": ("struck",),
    "submit": ("submitted",),
    "sweep": ("swept",),
    "take": ("taken", "took"),
    "teach": ("taught",),
    "tear": ("torn", "tore"),
    "tell": ("told",),
    "think": ("thought",),
    "throw": ("thrown", "threw"),
    "understand": ("understood",),
    "undo": ("undone", "undid"),
    "uphold": ("upheld",),
    "wear": ("worn", "wore"),
    "win": ("won",),
    "withdraw": ("withdrawn", "withdrew"),
    "withhold": ("withheld",),
    "write": ("written", "wrote"),
}
#: Every past form the irregular table spells: rule 16 admits each one.
IRREGULAR_FORMS = frozenset(form for forms in IRREGULAR_PAST.values() for form in forms)


def regularised(word: str) -> str:
    """The irregular verb an `-ed` word wrongly regularises (`lended` → `lend`), else ``."""
    if not word.endswith("ed") or word in IRREGULAR_FORMS:
        return ""
    stem = word[:-2]
    undoubled = stem[:-1] if stem[-1:] == stem[-2:-1] else stem
    for base in (stem, word[:-1], undoubled):
        if base in IRREGULAR_PAST:
            return base
    return ""
