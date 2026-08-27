"""Take the delete out of a box role's grant over the BACKUPS bucket. Nothing else.

WHY A TRANSFORM AND NOT A REPLACEMENT. The first cut of `provision.sh
backup-policy` composed a fresh role policy from scratch and wrote it under a
hard-coded name. Two things were wrong with that and both were invisible until
the live role was read: the live inline policy is named for the environment
(`<namespace>-<env>-box`), not `djb-box`, so the composed one would have landed
BESIDE the real grant and changed nothing (IAM policies are additive); and the
live grant carries `secretsmanager:DescribeSecret` and `ListSecrets`, which
`provision.sh secrets-fetch` needs and a composed replacement dropped.

So: read what is there, remove exactly one thing, write it back. A statement
that ALLOWS a delete over the backups bucket is split — the backups half keeps
every other action, the media half (if the statement covered both) keeps the
delete, because deleting a media file is something a product legitimately does
and deleting its own backup is not.

Declared blind spot: this reads the INLINE policy it is given. A delete granted
by an attached managed policy, or by a second inline policy, is invisible here —
which is why `backup-policy` refuses when the role carries more than one inline
policy rather than narrowing the first and calling it done, and why the bucket
policy (a Deny, which beats any Allow anywhere) is the belt to this braces.
"""

from __future__ import annotations

import json
import os
import sys

DELETE_ACTIONS = ("DeleteObject", "DeleteObjectVersion")


def listed(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return list(value)  # type: ignore[arg-type]


def main() -> int:
    live_path, out_path = sys.argv[1], sys.argv[2]
    backups = os.environ["DJB_BACKUPS_BUCKET"]
    with open(live_path, encoding="utf-8") as handle:
        document = json.load(handle)

    statements: list[dict] = []
    changed: list[str] = []
    for statement in document.get("Statement", []):
        actions = listed(statement.get("Action", []))
        resources = listed(statement.get("Resource", []))
        deletes = [a for a in actions if a.split(":")[-1] in DELETE_ACTIONS]
        touches_backups = any(backups in resource for resource in resources)
        if statement.get("Effect") != "Allow" or not deletes or not touches_backups:
            statements.append(statement)
            continue

        backup_resources = [r for r in resources if backups in r]
        other_resources = [r for r in resources if backups not in r]
        kept = [a for a in actions if a not in deletes]
        statements.append(
            {
                **statement,
                "Sid": "BackupsAppendOnlyNoDelete",
                "Action": kept,
                "Resource": backup_resources,
            }
        )
        if other_resources:
            statements.append(
                {
                    **statement,
                    "Sid": (statement.get("Sid", "Objects") + "Media")[:64],
                    "Action": actions,
                    "Resource": other_resources,
                }
            )
        changed.append(statement.get("Sid", "(no sid)"))

    document["Statement"] = statements
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(document, handle, indent=2)

    if changed:
        print(f"  narrowed: {', '.join(changed)} (delete removed over {backups})")
    else:
        print(f"  nothing to narrow: no Allow-delete over {backups}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
