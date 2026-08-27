"""Lift one marked recipe out of a runbook and fill in the placeholders it names.

    python3 scripts/tests/render_recipe.py <doc> <marker> <out> <substitutions-json>

Used only by `scripts/tests/test_runbook_recipes.sh`. It asserts nothing and
reports no verdict beyond three refusals, each exit 2 with a sentence:

  * the marker is not in the document at all;
  * the marker appears more than once (which recipe did you mean?);
  * the marker is not followed by a fenced block before the next marker.

THE ONE RULE. The block is copied out **byte for byte** and then a declared,
finite substitution table is applied to it. Nothing is reformatted, nothing is
re-indented, no line is dropped, and the substitutions are the caller's, printed
by the caller. A renderer that "fixed up" a recipe would be the second copy the
whole tooth exists to abolish, one layer down.

WHY A SEPARATE FILE and not a `sed` in the drive: the placeholders in this
runbook are UTF-8 ellipses (`…`) inside shell-quoted JSON. `sed` over that is a
locale-dependent guess about bytes, and BSD and GNU `sed` disagree about the
escapes involved. `str.replace` is neither.
"""

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
