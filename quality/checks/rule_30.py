"""Rule 30: a retry clock that nothing reads is a promise nobody keeps."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from quality.checks._hub import CheckResult, _parse, _py_files

# --- rule 30: a retry clock that nothing reads is a promise nobody keeps -------
#
# A finding about one column, generalised (ADR events-3). `emit()` wrote
# `Outbox.next_attempt_at`, indexed it over `(status, next_attempt_at)`,
# documented it in three modules — and NOTHING in production ever queried it. A
# row whose dispatch died held a promise for ever, with a management command
# nobody had a reason to run as the only recovery. The column was not broken; it
# was unread, and unread looks exactly like working.
#
# THE CLOSED QUESTION over a name-shaped population: a `DateTimeField` whose
# name matches the retry-clock grammar must be READ by production code outside
# its own declaring module and outside tests.
#
# A READ is a query, and the distinction is the entire rule. On this tree the
# field is *mentioned* in eleven places that are not reads: two writes in
# services.py, and prose in activities.py and workflows.py. A grep-shaped rule
# would have been green through the whole period the column had no reader —
# which is the period the review found.
_CLOCK_FIELD = re.compile(r"^(next_attempt_at|.*_retry_at|retry_after_.*)$")
# The queryset verbs whose STRING arguments name fields.
_FIELD_STRING_CALLS = {"order_by", "only", "values", "values_list", "defer", "F", "distinct"}
# LEX-1: the verbs whose KEYWORD arguments name a field being READ. The first
# draft matched a `field=`/`field__` keyword on ANY call, which is the rule's own
# defect wearing the rule's pass: `Outbox.objects.filter(...).update(
# next_attempt_at=None)` clears the clock and `Outbox(next_attempt_at=when)` sets
# it, and each counted as its own reader. A product that closed its clock from a
# second module therefore SILENCED rule 30 with a write — the exact state
# (written everywhere, queried nowhere) the rule was written to find.
#
# ENUMERATED FROM WHAT THIS TREE ACTUALLY USES, counted over apps/ minus
# migrations: `filter` (259 keyword callsites), `get` (207), `Q` (19),
# `exclude` (4), `get_or_create` (1). `When`, `annotate` and `aggregate` are in
# the set with zero callsites today, and deliberately: they are the ordinary
# next spellings of a lookup, and a rule that fired on the first `annotate` a
# product wrote would be accusing a field that IS read. `update_or_create` is in
# for the same reason and on the same terms as `get_or_create`.
#
# `get_or_create`/`update_or_create` are the LOOKUP HALF only, and that falls out
# of the shape rather than needing an exclusion: the lookup is keywords on the
# call, while the write half lives inside `defaults={...}` as dict KEYS, which
# are not keyword arguments and are never matched here.
#
# Writes are absent by construction — `update`, `bulk_update`, `create` and a
# model constructor are none of them read verbs, so none of them can answer for
# a clock. `order_by`/`values`/`F` and the rest name fields as STRINGS and are
# handled by _FIELD_STRING_CALLS above.
_READ_KWARG_CALLS = {
    "filter",
    "exclude",
    "get",
    "get_or_create",
    "update_or_create",
    "Q",
    "When",
    "annotate",
    "aggregate",
}


def _reads_field(tree: ast.Module, field: str) -> list[int]:
    """Lines where this module QUERIES `field` — never merely mentions it."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _call_name(node)
        # filter(next_attempt_at__lt=...) / exclude(next_attempt_at=None) — and
        # ONLY on a read verb: .update(next_attempt_at=None) is a write.
        if callee in _READ_KWARG_CALLS:
            for kw in node.keywords:
                if kw.arg and (kw.arg == field or kw.arg.startswith(f"{field}__")):
                    lines.append(node.lineno)
        # order_by("next_attempt_at"), order_by("-next_attempt_at"), F("...")
        if callee in _FIELD_STRING_CALLS:
            for arg in node.args:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.lstrip("-+") == field
                ):
                    lines.append(node.lineno)
    return sorted(set(lines))


def retry_clock_readers(root: Path, rule: dict) -> CheckResult:
    out = CheckResult()
    for path, node in _model_classes(root):
        rel = path.relative_to(root).as_posix()
        for line, name, value in _field_assignments(node):
            if not _CLOCK_FIELD.match(name) or "DateTimeField" not in _call_name(value):
                continue
            out.count("retry_clocks")
            readers: list[str] = []
            for other in _py_files(root, "apps"):
                orel = other.relative_to(root).as_posix()
                if orel == rel or "/tests/" in orel or "/migrations/" in orel:
                    continue
                otree = _parse(other)
                if otree is None:
                    continue
                readers += [f"{orel}:{n}" for n in _reads_field(otree, name)]
            if readers:
                out.count("clocks_with_readers")
                continue
            out.hit(
                rel,
                line,
                f"{node.name}.{name} is a retry clock that production code writes and "
                "NOTHING reads — no filter, no order_by, anywhere outside this module and "
                "the tests. A row whose work died holds its promise for ever and nothing "
                "will ever notice. Give the clock its reader — a selector, and a schedule "
                "that runs it (ADR events-3)",
                klass="clocks",
            )
    return out


from quality.checks.rule_16_the_rest_of_the_grammar import (  # noqa: E402
    _call_name,
    _field_assignments,
    _model_classes,
)
