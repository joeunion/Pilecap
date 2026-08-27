#!/usr/bin/env python3
"""Pull every saved search and dashboard out of a ClickStack, into this directory.

    python3 deploy/observability/hyperdx/export.py

The inverse of `import.py`: every `source` id is rewritten back to the source's
NAME and every instance-local field (`_id`, `id`, `team`, `__v`, timestamps) is
dropped, so the JSON that lands here is a description of the surface rather than
a snapshot of one container's Mongo. Re-running after a UI change is the way a
dashboard somebody drew by hand becomes code — draw it, export it, commit it.

The file name is the object's name, slugified. Committing the result is the
whole point; nothing here writes to the sink.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hdx import client_from_env  # noqa: E402

HERE = Path(__file__).resolve().parent

# Fields that describe THIS instance and nothing about the surface.
DROP = {"_id", "team", "__v", "createdAt", "updatedAt", "createdBy", "updatedBy"}


# `id` is TWO different things in this API and telling them apart matters.
#
# A stored document carries both `_id` and `id` — the same Mongo ObjectId twice —
# and both are instance-local, so both go. A dashboard TILE carries `id` alone,
# and that one is the author's own handle ("delivery-outcomes"): it is part of
# the layout, the API rejects a tile without it, and dropping it made the first
# re-import onto a fresh volume fail with `path: ["tiles",0,"id"] Required`.
#
# So: drop `id` only where `_id` sits beside it. That is the whole rule, and it
# is the reason the drill is performed against a fresh volume rather than
# assumed — this export looked perfect against the sink it came from.
def _drops_id(node: dict) -> bool:
    return "_id" in node


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "unnamed"


def _clean(node, sources: dict[str, str]):
    if isinstance(node, list):
        return [_clean(item, sources) for item in node]
    if not isinstance(node, dict):
        return node
    drop_id = _drops_id(node)
    out = {}
    for key, value in node.items():
        if key in DROP or (key == "id" and drop_id):
            continue
        if key == "source" and isinstance(value, str) and value in sources:
            out["sourceName"] = sources[value]
            continue
        out[key] = _clean(value, sources)
    return out


def main() -> int:
    client = client_from_env()
    sources = client.sources_by_id()

    total = 0
    for directory, endpoint in (
        ("saved-searches", "/api/saved-search"),
        ("dashboards", "/api/dashboards"),
    ):
        target = HERE / directory
        target.mkdir(parents=True, exist_ok=True)
        for item in client.get(endpoint):
            body = _clean(item, sources)
            path = target / f"{_slug(item['name'])}.json"
            text = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False)
            path.write_text(text + "\n", encoding="utf-8")
            print(f"  -> {path.relative_to(HERE.parent.parent.parent)}")
            total += 1

    print(f"exported {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
