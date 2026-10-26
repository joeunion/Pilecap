"""Every shape `manage.py scaffold` knows: a closed registry, the fence word each golden carries."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

#: The verbs the family ships outside `core.verbs.ROADS`, in their adoption order after it.
NON_ROAD_VERBS: tuple[str, ...] = ("attach", "import")


@dataclass(frozen=True)
class Shape:
    """One scaffold shape: its command word and the extract key that is its golden."""

    key: str
    golden: str
    summary: str
    #: The words after the shape, as its own refusal teaches them.
    args: str = "<app> <Noun>"
    #: What it is written onto: a fresh app, a noun `scaffold noun` wrote, an app, the face.
    on: str = "noun"

    @property
    def fence(self) -> str:
        """The shape word its golden's fences open with; empty for the verb-list form and none."""
        word = self.golden.partition(".")[0]
        return "" if word in ("", ADOPT) else word


#: The verb-list form's shape: `adopt <verb>` reads the extract `adopt.<verb>`.
ADOPT = "adopt"

#: The registry `--list` prints; a fence's shape word outside it is a `FenceError`.
SHAPES: tuple[Shape, ...] = (
    Shape(ADOPT, ADOPT, "adopt a family verb on a noun", "<verb> <app> <Noun>", "fresh-app"),
    Shape("noun", "noun", "a noun with its doors", "<app> <Noun>", "fresh-app"),
    Shape("field", "field.due_at", "a field on a noun", "<app> <Noun> <name>:<type>?"),
    Shape("filter", "filter.name", "a list filter", "<app> <Noun> <field>=<lookup>"),
    Shape("ordering", "ordering.due_at", "a list ordering key", "<app> <Noun> <field>"),
    Shape(
        "verb",
        "verb.touch",
        "a verb: service, event, both doors, tests; `--transition` makes it one enum step",
        "<app> <Noun> <verb> [--transition <from>-><to>]",
    ),
    Shape("event", "verb.touch", "an event without a service", "<app> <Noun> <verb>"),
    Shape(
        "enum",
        "enum.status",
        "a status enum with its transitions; its values are UPPER_CASE, and a lower-case value "
        "is upper-cased and said",
        "<app> <Noun> <field> <A,B,C>",
    ),
    Shape(
        "migration",
        "",
        "a paired forward/reverse data migration stub",
        "<app> <name> --data",
        "app",
    ),
    Shape(
        "workflow",
        "workflow.onboard",
        "a workflow and its activities: a human decision is the approval wait; a moment the row "
        "names is the timer, `--on <verb> --until <field>` (golden `workflow.remind`)",
        "<app> <Noun> <process> [--on <v> --until <field>] [--before <d>]",
    ),
    Shape("policy", "policy", "a tenant policy inherited downward", "<app> <Noun>Policy"),
    Shape(
        "stat",
        "stat.count",
        "a measured stat endpoint",
        "<app> <Noun> <key>[=sum:<field>|avg:<field>|count]",
    ),
    Shape("import", "adopt.import", "an import shape", "<app> <Noun>", "fresh-app"),
    Shape("search", "search", "search adoption", "<app> <Noun> <fields>"),
    Shape("child", "child.entry", "a child row", "<app> <Parent> <Child>"),
    Shape("screen", "face", "a screen: face, copy and client", "<Noun>", "face"),
    Shape("surface", "portal", "a surface and its role", "<app> <key>", "app"),
    Shape("role", "portal", "a role", "<app> <key>", "app"),
    Shape("webhook-in", "webhook-in.onboarding", "a webhook received", "<app> <Noun> <provider>"),
)

#: The shape words a fence may open with (the verb-list form is `adopt`'s and reads its verbs).
FENCE_SHAPES: frozenset[str] = frozenset(s.fence for s in SHAPES if s.fence)


def road_verbs(root: Path) -> tuple[str, ...]:
    """`core.verbs.ROADS`' keys in the table's order, read from the literal under `root`."""
    tree = ast.parse((root / "apps/core/verbs.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "ROADS" and isinstance(node.value, ast.Dict):
                return tuple(str(k.value) for k in node.value.keys if isinstance(k, ast.Constant))
    return ()


def adopt_verbs(root: Path) -> tuple[str, ...]:
    """Every verb `scaffold adopt` takes, in adoption order: the roads, then attach and import."""
    return (*road_verbs(root), *NON_ROAD_VERBS)


def shape(key: str) -> Shape | None:
    """The registered shape named `key`, or None."""
    return next((s for s in SHAPES if s.key == key), None)
