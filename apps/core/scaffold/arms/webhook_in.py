"""The `webhook-in` arm: a provider seam, its service and its `ready()` registration."""

from __future__ import annotations

import ast
import difflib
import keyword
import re
import textwrap
from pathlib import Path
from typing import Any

from django.core.management.base import CommandError

from apps.core.scaffold import anchors
from apps.core.scaffold.arms._common import Arms, _refuse, lexicon
from apps.core.scaffold.copier import (
    Golden,
    assemble,
    blocks_of,
    formatted,
    relocations,
    snake,
    tidied,
)
from apps.core.scaffold.shapes import Shape, adopt_verbs

#: The registered shapes this module's arm writes.
KEYS: tuple[str, ...] = ("webhook-in",)

#: The webhook-in golden's own provider, and the verb of the service its handler calls (rule 16).
GOLDEN_PROVIDER = "onboarding"
PROVIDER_WORD = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
WEBHOOK_SERVICE_VERB = "confirm"
#: The module the provider seam is written whole into; its registration goes in `apps.py`.
WEBHOOK_MODULE = "integrations.py"


def webhook_lines(line: str, provider: str) -> str:
    """A golden `onboarding` line as the provider `provider` says it: its slug, class and names."""
    camel = "".join(part.capitalize() for part in provider.split("_"))
    for old, new in (
        (GOLDEN_PROVIDER.upper(), provider.upper()),
        (GOLDEN_PROVIDER.capitalize(), camel),
        (GOLDEN_PROVIDER, provider),
    ):
        line = line.replace(old, new)
    return line


def _app_config(tree: ast.Module) -> ast.ClassDef | None:
    """The module's `AppConfig` subclass, by its base's name."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and any(
            (b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")) == "AppConfig"
            for b in node.bases
        ):
            return node
    return None


def ready_registered(text: str, method: str) -> tuple[str, int]:
    """`text` with the dedented `method` put in its AppConfig's `ready()`, and where it landed."""
    tree = ast.parse(text)
    config = _app_config(tree)
    if config is None:
        raise ValueError("no AppConfig subclass")
    lines = text.splitlines()
    ready = _ready_of(config)
    if ready is None:
        width = " " * config.body[0].col_offset
        block = ["", *textwrap.indent(method, width).rstrip("\n").splitlines()]
        at = config.end_lineno or config.lineno
    else:
        defined = ast.parse(method).body[0]
        assert isinstance(defined, ast.FunctionDef)  # noqa: S101 — narrows the ast type for mypy; a False is a bug, not input
        body = defined.body[1:] if ast.get_docstring(defined) is not None else defined.body
        first = body[0].lineno - 1
        width = " " * ready.body[0].col_offset
        moved = textwrap.dedent("\n".join(method.splitlines()[first:]))
        block = [
            "" if not line.strip() else line for line in textwrap.indent(moved, width).splitlines()
        ]
        at = ready.end_lineno or ready.lineno
    lines[at:at] = block
    landed = "\n".join(lines) + "\n"
    return landed, ready_line(landed)


def verifier_next(seam: str, label: str, provider: str) -> str:
    """The `next:` line naming where the copy's verifier stands, and when it is rewritten."""
    name = f"verify_{provider}_delivery"
    defined = next(
        n for n in ast.parse(seam).body if isinstance(n, ast.FunctionDef) and n.name == name
    )
    return (
        f"next: edit apps/{label}/{WEBHOOK_MODULE}:{defined.lineno} `{name}` if the upstream "
        "does not sign `X-Signature-V2` — a True or False there replaces the receiver's check"
    )


def _ready_of(config: ast.ClassDef) -> ast.FunctionDef | None:
    """The AppConfig's own `ready()`, if it declares one."""
    return next(
        (n for n in config.body if isinstance(n, ast.FunctionDef) and n.name == "ready"), None
    )


def ready_line(text: str) -> int:
    """The line `def ready` stands on in `text`'s AppConfig."""
    config = _app_config(ast.parse(text))
    ready = _ready_of(config) if config is not None else None
    if ready is None:
        raise ValueError("no ready() in the AppConfig")
    return ready.lineno


class WebhookInArm(Arms):
    """`scaffold webhook-in`."""

    def webhook_in(
        self,
        root: Path,
        goldens: dict[str, Golden],
        shape: Shape,
        words: list[str],
        options: dict[str, Any],
    ) -> None:
        """`webhook-in <app> <Noun> <provider>`: the provider seam, its service, its `ready()`."""
        golden = self.golden_of(shape, goldens)
        if len(words) != 3:
            raise _refuse(
                "webhook-in takes <app> <Noun> <provider> — e.g. `webhook-in orders Order stripe`."
            )
        label, noun, provider = words
        event = f"{label}.{snake(noun)}.{provider}_confirmed"
        if not PROVIDER_WORD.match(provider) or keyword.iskeyword(provider):
            raise _refuse(
                f"{provider!r} is no provider — house rule 16 would refuse the event `{event}` "
                "(<app>.<noun>.<past-verb>, lower snake case); name it as its slug, e.g. `stripe`."
            )
        if WEBHOOK_SERVICE_VERB not in lexicon(root):
            raise _refuse(
                f"{WEBHOOK_SERVICE_VERB}: not a declared service verb — house rule 16 would refuse "
                f"`{WEBHOOK_SERVICE_VERB}_{snake(noun)}_{provider}`."
            )
        self.refuse_names(root, label, noun, check=bool(options["check"]))
        app_dir = root / "apps" / label
        config = app_dir / "apps.py"
        try:
            found = _app_config(ast.parse(config.read_text())) if config.is_file() else None
        except SyntaxError:
            found = None
        if found is None:
            raise _refuse(
                f"apps/{label}/apps.py declares no AppConfig whose `ready()` the registration can "
                "extend — it lives there, through `pilecap.connections`, because a product's "
                "`receivers.py` is mounted by nothing (rule 42 knows only the platform's "
                "`apps/events/receivers.py`)."
            )
        moves = relocations(golden.app, label, noun)
        method = "".join(
            self.renamed(webhook_lines(line, provider), moves) + "\n"
            for line in (root / golden.path(anchors.APP_CONFIG)).read_text().splitlines()
        )
        if options["check"]:
            self.compare_ready(root, golden, label, method)
        elif (app_dir / WEBHOOK_MODULE).is_file():
            raise _refuse(
                f"apps/{label} already has an `{WEBHOOK_MODULE}` — the provider seam is written "
                "whole, one per app; a second provider registers by hand in that module."
            )
        text = tidied(ready_registered(config.read_text(), method)[0], root, "apps.py", label)
        call = method.strip().splitlines()[-1].strip()
        self.additive(
            root,
            Golden(golden.key, golden.app, tuple(f for f in golden.files if f != "apps.py")),
            label,
            noun,
            lambda line: webhook_lines(line, provider),
            options,
            taken=f"{provider}_confirmed_at",
            migration=f"{snake(noun)}_{provider}_confirmed_at",
            extra=("apps.py", text, ready_line(text), f"`ready()`: {call}"),
        )
        if not options["check"] and not options["dry_run"]:
            seam = (app_dir / WEBHOOK_MODULE).read_text()
            self.stdout.write(verifier_next(seam, label, provider))

    def compare_ready(self, root: Path, golden: Golden, label: str, method: str) -> None:
        """Exit 1 unless the target's fenced `ready()` lines, dedented, read as the golden's."""
        source = (root / "apps" / label / anchors.APP_CONFIG).read_text()
        blocks = blocks_of(source, golden.key, adopt_verbs(root), f"apps/{label}/apps.py")
        fenced = formatted(textwrap.dedent(assemble(blocks)), root, anchors.APP_CONFIG)
        want = formatted(method, root, anchors.APP_CONFIG)
        if fenced != want:
            self.stdout.write(
                "".join(
                    difflib.unified_diff(
                        fenced.splitlines(keepends=True),
                        want.splitlines(keepends=True),
                        f"apps/{label}/apps.py (fenced)",
                        golden.path(anchors.APP_CONFIG),
                    )
                )
            )
            raise CommandError(f"apps/{label}/apps.py differs from its golden", returncode=1)
        self.stdout.write(f"apps/{label}/apps.py: `ready()` reads line-for-line.")
