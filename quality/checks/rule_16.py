"""Rule 16: naming grammar (event names)."""

from __future__ import annotations

import ast
from pathlib import Path

from quality.checks._hub import CheckResult, _app_dirs, _parse, event_shape

# --- rule 16: naming grammar (event names) ------------------------------------


def event_grammar(root: Path, rule: dict) -> CheckResult:
    # At call time: `quality.engine` imports this package, so a module-level import is a cycle.
    from quality.engine.lexicon import IRREGULAR_FORMS, IRREGULAR_PAST, regularised, tense_word

    out = CheckResult()
    for app in _app_dirs(root):
        events = app / "events.py"
        tree = _parse(events) if events.exists() else None
        if tree is None:
            continue
        rel = str(events.relative_to(root))
        for node in tree.body:
            names, value = _assigned(node)
            if len(names) != 1:
                continue
            name = names[0]
            if not (
                name.isupper() and isinstance(value, ast.Constant) and isinstance(value.value, str)
            ):
                continue
            out.count("event_names")
            text = value.value
            if not event_shape().match(text) or text.split(".")[0] != app.name:
                out.hit(
                    rel,
                    node.lineno,
                    f"event {text!r} does not follow <app>.<noun>.<past-verb> for app {app.name!r}",
                )
                continue
            last = tense_word(text.split(".")[-1])
            if base := regularised(last):
                out.hit(
                    rel,
                    node.lineno,
                    f"event {text!r} — `{last}` is no English past: `{base}` is irregular "
                    f"and its past is `{IRREGULAR_PAST[base][0]}`",
                )
            elif not (last.endswith("ed") or last in IRREGULAR_FORMS):
                out.hit(
                    rel,
                    node.lineno,
                    f"event {text!r} — the verb is not past tense; an event states that "
                    "something HAS happened (an irregular past rule 16's table lacks takes "
                    "`# rule-16: <reason>` on the line)",
                )
    return out


from quality.checks.rule_13_clauses_i_iv import _assigned  # noqa: E402
