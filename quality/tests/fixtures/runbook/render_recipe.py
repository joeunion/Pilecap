"""Lift one marked recipe out of a runbook and fill in the placeholders it names."""

from __future__ import annotations

import json
import re
import sys

MARKER = re.compile(r"^<!--\s*recipe:\s*([A-Za-z0-9_-]+)\s*-->\s*$")
FENCE = re.compile(r"^```")


def refuse(message: str) -> int:
    print(f"!! render_recipe: {message}", file=sys.stderr)
    print("   Nothing was rendered. A recipe that could not be lifted out of the", file=sys.stderr)
    print("   document has not been driven.", file=sys.stderr)
    return 2


def extract(lines: list[str], marker: str) -> tuple[list[str], str | None]:
    """The fenced block after `marker`, and a refusal message if there is not one."""
    hits = [i for i, line in enumerate(lines) if (m := MARKER.match(line)) and m.group(1) == marker]
    if not hits:
        seen = sorted({m.group(1) for line in lines if (m := MARKER.match(line))})
        carried = ", ".join(seen) or "(none)"
        return [], f"no `<!-- recipe: {marker} -->` in the document. It carries: {carried}"
    if len(hits) > 1:
        at = ", ".join(str(i + 1) for i in hits)
        return [], f"`recipe: {marker}` appears {len(hits)}x (lines {at}); one marker, one block"

    start = hits[0]
    body: list[str] = []
    inside = False
    for line in lines[start + 1 :]:
        if MARKER.match(line) and not inside:
            break
        if FENCE.match(line):
            if inside:
                return body, None
            inside = True
            continue
        if inside:
            body.append(line)
    return [], f"`recipe: {marker}` is not followed by a closed fenced block"


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__ or "", file=sys.stderr)
        return 2
    _, doc, marker, out, table = argv

    try:
        with open(doc, encoding="utf-8") as handle:
            lines = handle.read().splitlines(keepends=True)
    except OSError as failure:
        return refuse(f"cannot read {doc}: {failure}")

    try:
        substitutions: dict[str, str] = json.loads(table)
    except ValueError as failure:
        return refuse(f"the substitution table is not JSON: {failure}")

    body, problem = extract(lines, marker)
    if problem is not None:
        return refuse(problem)

    text = "".join(body)
    for old, new in substitutions.items():
        text = text.replace(old, new)

    with open(out, "w", encoding="utf-8") as handle:
        handle.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
