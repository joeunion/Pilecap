"""The template-only marker: a template test is DECLARED, never deleted."""

from __future__ import annotations

import importlib.util
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple, Protocol

import pytest

# --- the template-only marker: a template test is DECLARED, never deleted -----
#
# WHAT THIS IS FOR. Some tests assert a property only the TEMPLATE's own tree
# has — that no product owns a word the platform gave back, that the tree maps
# onto itself with nothing to do. On a product that folded a release they are
# red BY CONSTRUCTION, and this file is template-owned (class C2), so a product
# had exactly two moves: delete the template's test, or pin a named skip in a
# conftest of its own. Both are hand edits the next fold fights.
#
# So a test says it once, where it is written:
#
#     @pytest.mark.template_only(reason="<why this property is the template's own>")
#
# and this file honours it. On the template nothing is skipped. On a tree that
# declares `rule_id_namespace:` the test is skipped with ONE sentence naming
# the declaration — the same sentence, prefix for prefix, as the shell twin's
# (`template_only` in `scripts/tests/drive_preamble.sh`), so a product reading
# either suite reads one sentence. `apps/test_template_only.py` is the census
# that keeps the marked set typed and every pinned test present.
#
# THE KEY IS THE ENGINE'S READING, NEVER A SECOND ONE. "Has this tree folded"
# is answered ONE way in this repository: `quality.gate`'s own parse of the
# drawer (`LOCAL_DOC`). "Is any app outside `platform_apps`" is a second
# answer, and a wrong one — the gate's self-test plants `apps/zzz_canary`,
# outside that set, into the template's own tree, which would flip the
# template's suite to "product" for the length of a plant.
#
# THE REGISTRATION is `[tool.pytest.ini_options].markers` in `pyproject.toml`,
# beside `perf`: `--strict-markers` refuses an unregistered or misspelled mark
# at collection, which is what makes a typo a red and not a silent run.

#: The shell twin's prefix, byte for byte (`apps/test_template_only.py` reads
#: `drive_preamble.sh` and holds the two equal).
TEMPLATE_ONLY_SKIP_PREFIX = "template-only: this tree declares rule_id_namespace "


def _declared_namespace(doc: Mapping[str, object] | None = None) -> str | None:
    """The `rule_id_namespace:` this tree declares, or `None` on a template.

    The engine's one reader (`quality.engine.rules.declared_namespace`), imported lazily.
    """
    return importlib.import_module("quality.engine.rules").declared_namespace(doc)  # type: ignore[no-any-return]


#: R10's directory: in the template's own repository always, in a published artifact never.
TEMPLATE_SOURCE = "docs/product/skeletons"
#: The page whose step 3 declares a clone a product.
DAY_ZERO = "docs/sdk/day-zero.md"
#: The checkout this file lives in.
_HOME = Path(__file__).resolve().parents[2]


def undeclared_artifact_refusal(
    root: Path = _HOME, doc: Mapping[str, object] | None = None
) -> str | None:
    """The line refusing the template's own suite on an undeclared release's clone, or `None`."""
    if _declared_namespace(doc) is not None or (root / TEMPLATE_SOURCE).is_dir():
        return None
    return (
        "template-only: this clone of a release declares no rule_id_namespace, so the template's "
        "own tests would read files the release never ships — run `uv run python manage.py "
        f"declare <ns>` first ({DAY_ZERO}, step 3)"
    )


def template_only_skip_reason(reason: str, doc: Mapping[str, object] | None = None) -> str | None:
    """The skip sentence for a template-only test on this tree, or `None` on a template."""
    namespace = _declared_namespace(doc)
    if namespace is None:
        return None
    return f"{TEMPLATE_ONLY_SKIP_PREFIX}{namespace}; {reason}"


class TemplateOnlyReading(NamedTuple):
    """The two readings above, handed to a test through a fixture."""

    declared_namespace: Callable[[Mapping[str, object] | None], str | None]
    skip_reason: Callable[[str, Mapping[str, object] | None], str | None]


@pytest.fixture
def template_only_reading() -> TemplateOnlyReading:
    """The mark's reading, for a drive in an app that may not IMPORT this file.

    The layer contract (`import-linter`) keeps `apps.core` below `accounts` and
    the platform apps, and this file imports both — so a core test that
    imported it would put core above them. A fixture is pytest's own way in,
    and it crosses no layer: the drive of the mark in
    `apps/core/tests/test_fold_map.py` reaches the reading through here.
    """
    return TemplateOnlyReading(_declared_namespace, template_only_skip_reason)


class _Markable(Protocol):
    """What `_withhold_template_only` reads off an item — a `pytest.Item`, or a drive's fake."""

    @property
    def nodeid(self) -> str: ...

    def get_closest_marker(self, name: str) -> Any: ...

    def add_marker(self, marker: Any) -> None: ...


def _withhold_template_only(
    items: Sequence[_Markable], doc: Mapping[str, object] | None = None
) -> list[tuple[_Markable, str]]:
    """Skip every `template_only` test, naming the declaration, on a tree that folded.

    Returns each withheld test with its sentence. A mark with no `reason=` is a
    collection error naming the test, on EVERY tree — the template's included.
    """
    marked: list[tuple[_Markable, str]] = []
    for item in items:
        mark = item.get_closest_marker("template_only")
        if mark is None:
            continue
        reason = mark.kwargs.get("reason")
        if mark.args or not isinstance(reason, str) or not reason.strip():
            raise pytest.UsageError(
                f"{item.nodeid}: @pytest.mark.template_only carries no reason= — "
                "write template_only(reason=\"<why this property is the template's "
                'own>"); a skip that cannot say why is a skip nobody can audit'
            )
        marked.append((item, reason.strip()))
    withheld: list[tuple[_Markable, str]] = []
    for item, reason in marked:
        sentence = template_only_skip_reason(reason, doc)
        if sentence is not None:
            item.add_marker(pytest.mark.skip(reason=sentence))
            withheld.append((item, sentence))
    return withheld
