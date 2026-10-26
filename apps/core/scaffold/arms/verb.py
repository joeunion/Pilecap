"""The `verb` and `event` arms: a service verb with its event, or the event alone."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.core.management.base import CommandParser

from apps.core.scaffold.arms._common import (
    DROP,
    VERB_WORD,
    Arms,
    _refuse,
    has_a_spelled_past,
    lexicon,
    past_tense,
)
from apps.core.scaffold.copier import Golden, snake
from apps.core.scaffold.shapes import Shape

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("verb", "event")

#: The verb golden's own word; its event says it in the past tense.
GOLDEN_VERB = "touch"
GOLDEN_PAST = "touched"

#: An enum's one-step chain as `scaffold enum` writes it: `<FIELD>_NEXT` and its `A: B` lines.
CHAIN = re.compile(
    r"^    (?P<name>[A-Z][A-Z0-9_]*)_NEXT: ClassVar\[dict\[str, str\]\] = \{\n"
    r"(?P<body>(?:.*\n)*?)    \}",
    re.M,
)
LINK = re.compile(
    r"^ +(?P<camel>[A-Za-z0-9]+)\.(?P<a>[A-Z0-9_]+): (?P=camel)\.(?P<b>[A-Z0-9_]+),$", re.M
)
ARROW = re.compile(r"^(?P<a>[A-Za-z0-9_]+)(?:→|->)(?P<b>[A-Za-z0-9_]+)$")


@dataclass(frozen=True)
class Step:
    """One move along a noun's transitioned enum: its field, its choices class, from and to."""

    field: str
    camel: str
    first: str
    start: str
    end: str


def verb_lines(line: str, verb: str) -> str:
    """A golden `touch` line as the verb `verb` says it: the word, its title and its past."""
    past = past_tense(verb)
    spoken = verb.replace("_", " ")
    for old, new in (
        (GOLDEN_PAST.upper(), past.upper()),
        (GOLDEN_PAST, past),
        ("Touch a", f"{spoken.capitalize()} a"),
        (f"`{GOLDEN_VERB}`", f"`{verb}`"),
        (GOLDEN_VERB, verb),
    ):
        line = line.replace(old, new)
    return line


def event_line(label: str, noun: str, past: str) -> str:
    """The one line both `event` and `verb` write into `events.py` for `past`."""
    return f'{snake(noun).upper()}_{past.upper()} = "{label}.{snake(noun)}.{past}"'


def adopts_event(events: str, label: str, noun: str, past: str, key: str) -> bool:
    """Whether `verb` takes the line `event` already wrote; a refusal when it cannot."""
    said = f'"{label}.{snake(noun)}.{past}"'
    if said not in events:
        return False
    line = event_line(label, noun, past)
    if key == "verb" and re.search(rf"^{re.escape(line)}$", events, re.M):
        return True
    raise _refuse(
        f"apps/{label}/events.py already says {said}"
        + ("." if key == "event" else f" — under another name than `{line.partition(' ')[0]}`.")
    )


def _stepped(step: Step) -> dict[str, str]:
    """Each golden `touch` line a transition verb says differently, before the verb's own rename."""
    to, at, chosen = step.end, step.start, f"Widget.{step.camel}"
    reach = ""
    if step.start != step.first:
        reach = f"\nWidget.objects.filter(pk=widget.pk).update({step.field}={chosen}.{at})"
    return {
        # services.py
        '"""Mark a widget as seen now: only `updated_at` moves, and every press is said."""': (
            f'"""Step a widget\'s {step.field} from {at} to {to} through `transition_widget`; '
            'say so."""'
        ),
        "locked = _locked_widget(tenant=tenant, widget=widget)": (
            f"locked = transition_widget(\n    tenant=tenant, actor=actor, widget=widget, "
            f"{step.field}={chosen}.{to}\n)"
        ),
        'require_live(locked, noun="widget")': DROP,
        'require(actor, "widget.update", locked)': DROP,
        'locked.save(update_fields=["updated_at"])': DROP,
        # api.py
        '"""Mark one widget this hat reaches as seen now."""': (
            f'"""Step one widget this hat reaches from {at} to {to}."""'
        ),
        '@also_refuses("archived")': '@also_refuses("archived", "conflict")',
        "Mark one widget as seen now. Takes no body; only its `updated_at` moves.": (
            f"Step one widget's `{step.field}` from `{at.lower()}` to `{to.lower()}`. Takes no "
            "body."
        ),
        "Every press is said to subscribers, a repeat included.": (
            "The step is said to subscribers; a second press is refused."
        ),
        "* `409 archived` — the widget is archived: restore it first.": (
            "* `409 archived` — the widget is archived: restore it first.\n"
            f"* `409 conflict` — the widget's `{step.field}` is not `{at.lower()}`. Nothing "
            "changed."
        ),
        # tests
        "from pilecap import Archived": "from pilecap import Archived, Conflict",
        "def test_a_touch_moves_updated_at_and_says_so_on_every_press(": (
            f"def test_the_touch_steps_{step.field}_from_{at.lower()}_to_{to.lower()}_once("
        ),
        'widget = create_widget(tenant=tenant, actor=owner_actor, name="Seen")': (
            'widget = create_widget(tenant=tenant, actor=owner_actor, name="Seen")'
            + (f"{reach}\nwidget.refresh_from_db()" if reach else "")
        ),
        "again = touch_widget(tenant=tenant, actor=owner_actor, widget=first)": (
            "with pytest.raises(Conflict):\n"
            "    touch_widget(tenant=tenant, actor=owner_actor, widget=first)"
        ),
        "assert widget.updated_at < first.updated_at < again.updated_at": (
            f"assert first.{step.field} == {chosen}.{to}"
        ),
        'assert again.name == "Seen"': 'assert first.name == "Seen"',
        "assert published.count(WIDGET_TOUCHED) == 2": (
            "assert published.count(WIDGET_TOUCHED) == 1"
        ),
        "def test_a_touch_answers_the_widget_seen_now(": (
            f"def test_a_touch_answers_the_widget_at_{to.lower()}("
        ),
        (
            "assert Widget.objects.for_tenant(tenant).get(pk=widget.pk).updated_at > "
            "widget.updated_at"
        ): (
            f"assert Widget.objects.for_tenant(tenant).get(pk=widget.pk).{step.field} == "
            f"{chosen}.{to}"
        ),
        "def test_the_touch_tool_answers_the_widget_seen_now(": (
            f"def test_the_touch_tool_answers_the_widget_at_{to.lower()}("
        ),
        "assert touched.updated_at > widget.updated_at": (
            f"assert touched.{step.field} == {chosen}.{to}"
        ),
        'bearer_header = {"authorization": f"Bearer {bearer}"}': (
            (
                f"await sync_to_async(Widget.objects.filter(pk=widget.pk).update)"
                f"({step.field}={chosen}.{at})\n"
                if reach
                else ""
            )
            + 'bearer_header = {"authorization": f"Bearer {bearer}"}'
        ),
    }


def transition_lines(line: str, verb: str, step: Step | None) -> str:
    """A golden `touch` line as `verb` says it, and as `step`'s move along the enum if any."""
    if step is not None and (swapped := _stepped(step).get(line.strip())) is not None:
        indent = line[: len(line) - len(line.lstrip())]
        line = swapped if swapped == DROP else "\n".join(indent + s for s in swapped.split("\n"))
    return verb_lines(line, verb)


def enum_chain(models: str, noun: str) -> tuple[str, str, list[tuple[str, str]]] | None:
    """`noun`'s transitioned enum as `scaffold enum` wrote it: field, choices class, steps."""
    start = re.search(rf"^class {noun}\(", models, re.M)
    if start is None:
        return None
    end = re.search(r"^class ", models[start.end() :], re.M)
    body = models[start.start() : start.end() + end.start()] if end else models[start.start() :]
    found = CHAIN.search(body)
    if found is None:
        return None
    links = [(m.group("camel"), m.group("a"), m.group("b")) for m in LINK.finditer(found["body"])]
    if not links:
        return None
    return found["name"].lower(), links[0][0], [(a, b) for _, a, b in links]


class VerbArm(Arms):
    """`scaffold verb` and `scaffold event`."""

    def create_parser(self, prog_name: str, subcommand: str, **kwargs: Any) -> CommandParser:
        """The command's parser, with the one flag this arm reads: `--transition FROM→TO`."""
        parser = super().create_parser(prog_name, subcommand, **kwargs)
        parser.add_argument(
            "--transition",
            default="",
            help="verb: the body is this one step of the noun's enum, FROM→TO (or FROM->TO)",
        )
        return parser

    def step(self, root: Path, label: str, noun: str, verb: str, asked: str) -> Step | None:
        """The enum step `verb` is: `--transition`'s, else inferred from its past tense, or None."""
        models = root / "apps" / label / "models.py"
        services = root / "apps" / label / "services.py"
        chain = enum_chain(models.read_text(), noun) if models.is_file() else None
        transitioned = services.is_file() and (
            f"def transition_{snake(noun)}(" in services.read_text()
        )
        if chain is None or not transitioned:
            if asked:
                raise _refuse(
                    f"`{noun}` carries no transitioned enum — `--transition` steps along the one "
                    f"`scaffold enum {label} {noun} <field> <A,B,C>` writes; scaffold it first."
                )
            return None
        field, camel, steps = chain
        inferred = ""
        if asked:
            arrow = ARROW.match(asked)
            if arrow is None:
                raise _refuse(f"{asked!r} is no `FROM→TO` — e.g. `--transition DRAFT→ACTIVE`.")
            start, end = arrow["a"].upper(), arrow["b"].upper()
        else:
            inferred = past_tense(verb)
            end = inferred.upper()
            start = next((a for a, b in steps if b == end), "")
            if not start:
                return None
        if (start, end) not in steps:
            raise _refuse(
                f"`{start}→{end}` is not one step of `{field}` — its steps are "
                f"{', '.join(f'{a}→{b}' for a, b in steps)}."
            )
        said = f" (inferred from `{inferred}`)" if inferred else ""
        self.stdout.write(f"step: {field} {start}→{end} through `transition_{snake(noun)}`{said}")
        return Step(field, camel, steps[0][0], start, end)

    def verb(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`verb <app> <Noun> <verb>`: service, event, both doors, tests; `event`: the name only."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3 and shape.key == "verb":
            raise _refuse(
                "verb takes <app> <Noun> <verb> [--transition <from>-><to>] — e.g. "
                "`verb orders Order close`, or `… ship --transition PACKED->SHIPPED`."
            )
        if len(words) != 3:
            raise _refuse(
                f"{shape.key} takes <app> <Noun> <verb> — e.g. `{shape.key} orders Order close`."
            )
        label, noun, verb = words
        if not VERB_WORD.match(verb) or keyword.iskeyword(verb):
            raise _refuse(f"{verb!r} is no verb — lower case words joined by `_`.")
        declared = lexicon(root)
        if verb not in declared:
            raise _refuse(
                f"`{verb}` is not a declared service verb — house rule 16 would refuse "
                f"`{verb}_{snake(noun)}`. Take one of: {' '.join(declared)}. A product adds "
                "its own under `service_verbs:` in quality/local/rules.yaml."
            )
        past = past_tense(verb)
        if not has_a_spelled_past(verb):
            raise _refuse(f"`{verb}` has no past tense the scaffold can spell for its event.")
        asked = str(options.get("transition") or "")
        if asked and shape.key != "verb":
            raise _refuse("`--transition` is the verb's: an event alone writes no body to step.")
        adopted = False
        if not options["check"]:
            events = root / "apps" / label / "events.py"
            text = events.read_text() if events.is_file() else ""
            adopted = adopts_event(text, label, noun, past, shape.key)
            services = root / "apps" / label / "services.py"
            if shape.key == "verb" and services.is_file():
                if f"def {verb}_{snake(noun)}(" in services.read_text():
                    raise _refuse(f"apps/{label}/services.py already has `{verb}_{snake(noun)}`.")
        step = None
        if shape.key == "verb":
            step = self.step(root, label, noun, verb, asked)
        if shape.key == "event":
            golden = Golden(
                golden.key, golden.app, tuple(f for f in golden.files if f == "events.py")
            )
        if adopted:
            golden = Golden(
                golden.key, golden.app, tuple(f for f in golden.files if f != "events.py")
            )
            line = event_line(label, noun, past)
            self.stdout.write(f"adopted: apps/{label}/events.py `{line}` — the verb emits it")
        self.additive(
            root, golden, label, noun, lambda line: transition_lines(line, verb, step), options
        )
