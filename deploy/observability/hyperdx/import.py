#!/usr/bin/env python3
"""Put every saved search and dashboard in this directory into a ClickStack.

    python3 deploy/observability/hyperdx/import.py            # create what is missing
    python3 deploy/observability/hyperdx/import.py --replace  # delete by name first

IDEMPOTENT BY NAME. A second run creates nothing and says so, because the point
of the drill is that a stranger can run it against a sink they did not build
without wondering whether they just made a second copy of everything.

RESOLVES SOURCES BY NAME, never by id — see `hdx.py`'s docstring. A fresh
ClickStack volume has fresh ObjectIds; the names (`Logs`, `Traces`) are what the
first-run setup always creates and are therefore the only stable handle.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hdx import client_from_env  # noqa: E402

HERE = Path(__file__).resolve().parent


def _load(directory: str) -> list[tuple[Path, dict]]:
    root = HERE / directory
    return sorted(
        ((path, json.loads(path.read_text(encoding="utf-8"))) for path in root.glob("*.json")),
        key=lambda pair: pair[0].name,
    )


def _resolve(node: dict, sources: dict[str, str], where: Path) -> None:
    """`sourceName` -> `source`, recursively. The inverse of `export.py`'s pass."""
    name = node.pop("sourceName", None)
    if name is not None:
        if name not in sources:
            raise SystemExit(
                f"!! {where.name}: this sink has no source named {name!r} "
                f"(it has: {', '.join(sorted(sources)) or 'none'}). "
                "Complete the ClickStack first-run setup before importing."
            )
        node["source"] = sources[name]
    for value in node.values():
        if isinstance(value, dict):
            _resolve(value, sources, where)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _resolve(item, sources, where)


def main() -> int:
    replace = "--replace" in sys.argv[1:]
    client = client_from_env()
    sources = client.sources_by_name()
    print(f"sources on this sink: {', '.join(sorted(sources)) or '(none)'}")

    created = skipped = 0
    for kind, endpoint, key in (
        ("saved-searches", "/api/saved-search", "saved search"),
        ("dashboards", "/api/dashboards", "dashboard"),
    ):
        existing = {item["name"]: item["id"] for item in client.get(endpoint)}
        for path, body in _load(kind):
            name = body["name"]
            if name in existing:
                if not replace:
                    print(f"  = {key} {name!r} already here")
                    skipped += 1
                    continue
                client.delete(f"{endpoint}/{existing[name]}")
            _resolve(body, sources, path)
            client.post(endpoint, body)
            print(f"  + {key} {name!r}")
            created += 1

    print(f"imported {created}, already present {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
