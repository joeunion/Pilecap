"""Rule 17's schema probe: the PUBLISHED shape of named `Out` fields, read from a tree.

Started as a subprocess by `quality/checks/rule_36.py::diff_checks`, with the tree it
reads as its working directory — the tip's checkout, or a throwaway worktree
of the ref — for the reason every probe here is one: the gate must not stand
Django up in its own process, and a ref's classes cannot be imported into the
tip's.

THE FACT IT MEASURES. A field re-typed in Python is a breaking change only if
the document a client reads moves: `list[dict[str, str]]` re-typed as
`list[RemedyOut]` with the same two string keys publishes the same JSON, and
the annotation is not the contract — `model_json_schema(mode="serialization")`
is. Each field's schema is printed with every `$ref` inlined and the prose keys
(`title`, `description`, `examples`) and the `default` dropped, so two spellings of one shape
print one value.

Input: argv, each `<schemas module path>::<Class>`. Output: one JSON object,
`{"<path>::<Class>": {"<field>": <schema>}, ...}`; a class the tree does not
define is absent. Exit 0 when it printed; non-zero when it could not look.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

#: Keys that are not the shape: prose, and a default (which a serialised
#: answer always fills, so it moves no client's parse).
_NOT_THE_SHAPE = frozenset({"title", "description", "examples", "example", "default"})


def _inline(node: Any, defs: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            if name in seen:
                return {"$recursive": True}
            return _inline(defs.get(name, {}), defs, (*seen, name))
        return {k: _inline(v, defs, seen) for k, v in node.items() if k not in _NOT_THE_SHAPE}
    if isinstance(node, list):
        return [_inline(item, defs, seen) for item in node]
    return node


def main(argv: list[str]) -> int:
    root = Path.cwd()
    sys.path.insert(0, str(root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    import django

    django.setup()
    out: dict[str, dict[str, Any]] = {}
    for spec in argv:
        path, _, cls = spec.partition("::")
        module_name = path.removesuffix(".py").replace("/", ".")
        module = importlib.import_module(module_name)
        model = getattr(module, cls, None)
        if model is None or not hasattr(model, "model_json_schema"):
            continue
        schema = model.model_json_schema(mode="serialization")
        defs = schema.get("$defs", {})
        props = schema.get("properties", {})
        out[spec] = {name: _inline(field, defs) for name, field in props.items()}
    json.dump(out, sys.stdout, sort_keys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
