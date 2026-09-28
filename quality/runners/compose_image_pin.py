"""Every compose image is pinned by digest — the runner half of house rule 61.

    python3 quality/runners/compose_image_pin.py <root> [<root> …]

THE WITHDRAWAL IS THE WHOLE ARGUMENT. A tag is a promise the publisher can take
back: Docker Hub dropped MinIO's tag, quay.io served the byte-identical digest
until the project archived itself and withdrew every public image, and every
clone of this template failed at its first `compose up`. A digest cannot be
moved under the same name, and an index digest (a MULTI-ARCH manifest list)
is the one a Mac, a Graviton box and an amd64 runner all resolve to the right
layers from.

WHAT COUNTS, per `image:` line in each compose file it is handed:

* PINNED — the reference ends `@sha256:<64 hex>`, and its registry (the first
  path component when it carries a `.` or a `:` or is `localhost`, otherwise
  Docker Hub, `docker.io`) is on the rule's own declared allow-list in
  `quality/rules.yaml` (`allow_registries`, read from the rule whose runner is
  this file — one declaration, never a second list here).
* VALVED — `# pin-exception: <reason>` on the line, or in the contiguous
  comment block directly above it. Counted and returned as a target, so the
  engine prints how many exceptions stand; a reason under 12 characters is its
  own finding. An interpolated reference (`${…}`) can only ever be valved: its
  digest is resolved by whatever supplies the variables, and the valve says
  where.
* anything else — a FINDING, classed `unpinned` (a tag, or an interpolation
  with no valve), `registry` (a digest from a registry not on the list) or
  `short_reason`.

WHAT IT CANNOT SEE, and says so in the rule's `does_not_cover`: whether a
pinned digest is an INDEX at all. That is a registry question — `docker buildx
imagetools inspect <ref>` answers it, over the network — and a static scan that
pretended to know would be the worse instrument. The rung that pins transcribes
the inspection; this runner holds the pin once it is there.

It carries no verdict; `quality/gate.py` decides what a finding means.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

_RULES_YAML = "quality/rules.yaml"
_THIS = "quality/runners/compose_image_pin.py"

MIN_REASON = 12

IMAGE_LINE = re.compile(r"^(?P<indent>\s*)image:\s*(?P<rest>.*)$")
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")
VALVE = re.compile(r"#\s*pin-exception:\s*(?P<reason>.*)$")


def allow_registries(root: Path) -> list[str]:
    """The allow-list, from the one rule whose runner is this file."""
    doc = yaml.safe_load((root / _RULES_YAML).read_text()) or {}
    for rule in doc.get("rules") or []:
        argv = (rule.get("runner") or {}).get("argv") or []
        if _THIS in [str(a) for a in argv]:
            return [str(r) for r in (rule.get("allow_registries") or [])]
    return []


def split_value(rest: str) -> tuple[str, str]:
    """(the reference, the trailing comment) — a YAML comment starts at ` #`."""
    m = re.search(r"\s#", rest)
    if m is None:
        value, comment = rest, ""
    else:
        value, comment = rest[: m.start()], rest[m.start() :].strip()
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1]
    return value, comment


def registry_of(ref: str) -> str:
    """The registry host a reference pulls from — Docker's own resolution rule."""
    name = ref.split("@", 1)[0]
    first, sep, _rest = name.partition("/")
    if sep and ("." in first or ":" in first or first == "localhost"):
        return first
    return "docker.io"


def valve_reason(lines: list[str], index: int, comment: str) -> str | None:
    """The `# pin-exception:` reason on the line or in the comment block above it."""
    m = VALVE.search(comment)
    if m:
        return m.group("reason").strip()
    i = index - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        m = VALVE.search(lines[i])
        if m:
            return m.group("reason").strip()
        i -= 1
    return None


def scan(path: Path, rel: str, allowed: list[str], targets: dict) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return [
            {
                "path": rel,
                "line": 0,
                "msg": f"`{rel}` could not be read, so no image line in it was judged",
                "klass": "unreadable",
            }
        ]
    found: list[dict] = []
    here = 0
    for index, text in enumerate(lines):
        m = IMAGE_LINE.match(text)
        if m is None:
            continue
        ref, comment = split_value(m.group("rest"))
        if not ref:
            continue
        here += 1
        targets["image_lines"] += 1
        lineno = index + 1
        reason = valve_reason(lines, index, comment)
        if reason is not None:
            targets["pin_exception_valves"] += 1
            if len(reason) < MIN_REASON:
                found.append(
                    {
                        "path": rel,
                        "line": lineno,
                        "msg": (
                            f"`image: {ref}` carries a pin-exception whose reason is "
                            f"{len(reason)} characters — an exception is a sentence a reviewer "
                            f"can disagree with, and one under {MIN_REASON} characters is not one"
                        ),
                        "klass": "short_reason",
                    }
                )
            continue
        if "${" in ref:
            found.append(
                {
                    "path": rel,
                    "line": lineno,
                    "msg": (
                        f"`image: {ref[:60]}…` is interpolated, so no digest can be written on the "
                        "line and nothing here says what pins it. Write `# pin-exception: <what "
                        "resolves this reference to a digest, and where>` on the line or directly "
                        "above it"
                    ),
                    "klass": "unpinned",
                }
            )
            continue
        if not DIGEST.search(ref):
            found.append(
                {
                    "path": rel,
                    "line": lineno,
                    "msg": (
                        f"`image: {ref}` names a tag, not a digest — a tag is a promise the "
                        "publisher can withdraw, and the MinIO withdrawal broke every clone at "
                        "its first `compose up`. Pin it `@sha256:<64 hex>` of the MULTI-ARCH "
                        f"index (`docker buildx imagetools inspect {ref}`), or write "
                        "`# pin-exception: <reason>` on the line"
                    ),
                    "klass": "unpinned",
                }
            )
            continue
        host = registry_of(ref)
        if host not in allowed:
            found.append(
                {
                    "path": rel,
                    "line": lineno,
                    "msg": (
                        f"`image: {ref.split('@', 1)[0]}@sha256:…` is pinned, but to {host}, "
                        "which is not on this rule's allow-list "
                        f"({', '.join(allowed) or 'empty'}) in quality/rules.yaml — a digest from "
                        "a registry nobody decided to trust is a pin on somebody else's promise. "
                        "Pull from a listed registry, add the registry to the list in the same "
                        "diff, or write `# pin-exception: <reason>`"
                    ),
                    "klass": "registry",
                }
            )
            continue
        targets["pinned"] += 1
    targets[f"images_in:{rel}"] = here
    return found


def main(argv: list[str]) -> int:
    root = Path.cwd()
    allowed = allow_registries(root)
    targets: dict = {"files_scanned": 0, "image_lines": 0, "pinned": 0, "pin_exception_valves": 0}
    findings: list[dict] = []
    for arg in argv:
        path = root / arg
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(p for p in path.rglob("*") if p.suffix in (".yaml", ".yml"))
        else:
            candidates = []
        for candidate in candidates:
            targets["files_scanned"] += 1
            rel = str(candidate.relative_to(root))
            findings.extend(scan(candidate, rel, allowed, targets))
    targets["allow_registries"] = len(allowed)
    print(json.dumps({"protocol": "check-v1", "targets": targets, "findings": findings}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
