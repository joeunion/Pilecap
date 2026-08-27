"""Print a policy document as one line per statement — Sid, Effect, actions.

`backup-policy --check` reads two documents back (the bucket's and the box
role's) and a human has to be able to see, in one screen, whether the guard is
there and whether the box can still delete. Dumping raw JSON does not answer
that; a summary that FLAGS a delete grant does.

Reads the document on stdin. `bucket` mode takes the raw policy string the
`--query Policy --output text` form returns; `role` mode takes the JSON object
`--query PolicyDocument --output json` returns. Both end up as the same shape.

It reports NOTHING about whether the policy is correct — it is a reading aid,
and the verdict is the delete probe in `docs/runbooks/deploy.md`, which asks S3
rather than asking a document.
"""

from __future__ import annotations

import json
import sys


def actions(statement: dict) -> list[str]:
    value = statement.get("Action", [])
    return [value] if isinstance(value, str) else list(value)


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "role"
    raw = sys.stdin.read().strip()
    if not raw:
        print("  (nothing to read)")
        return 0
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        # An AWS error message rather than a document — show it verbatim; a
        # NoSuchBucketPolicy IS the answer when the guard has not landed.
        print("  " + raw.splitlines()[0])
        return 0
    if isinstance(document, str):
        document = json.loads(document)
    for statement in document.get("Statement", []):
        names = actions(statement)
        deletes = any(name.endswith(("DeleteObject", "DeleteObjectVersion")) for name in names)
        flag = "   <-- CAN DELETE" if deletes and statement.get("Effect") == "Allow" else ""
        sid = statement.get("Sid", "(no sid)")
        shown = ",".join(names) if mode == "role" else f"{len(names)} action(s)"
        print(f"  {sid:<34} {statement.get('Effect', '?'):<5} {shown}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
