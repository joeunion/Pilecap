"""An exported credential reaches no step that did not ask for it — rule 62's runner.

    python3 quality/runners/workflow_credential_pins.py <root> [<root> …]

THE FIRST CI ATTEMPT IS THE WHOLE ARGUMENT. `aws-actions/configure-aws-
credentials` does not hand its credential to the step that needs it: it writes
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `AWS_SESSION_TOKEN` into the
JOB's environment, over the workflow's own `env:`, for every step after it. The
registry login needed them for one pull; the gate, three steps later, inherited
them too, and every object-store test dialled the compose MinIO with an AWS STS
key MinIO had never heard of. Nothing on the page said the gate step was
holding a cloud credential.

WHAT COUNTS, per job, per step, in document order:

* an EXPORTER — a `uses:` step whose action (before the `@`) is on the rule's
  declared `exporters` list in `quality/rules.yaml`. From that step on, the
  job's environment carries the rule's `exported_names`.
* every `run:` step AFTER an exporter must name EACH exported name as a key of
  its own `env:` map — any value, and EMPTY IS A PIN: a step that sets the name
  to `""` has decided what it holds — or carry `# creds: <reason>`, on a
  comment line inside the step or in the contiguous comment block directly
  above its `-`. The valve is counted and returned as a target; a reason under
  12 characters is its own finding.
* anything else is a FINDING naming the file, the job, the step and the names
  it did not pin (class `unpinned`), or the valve that is too short
  (`short_reason`). A file that is not YAML is class `unreadable`.

It reads every `.yml`/`.yaml` UNDER the roots it is handed, nested ones
included. GitHub runs only the top level of `.github/workflows/`, so a nested
file is judged although it never runs — an over-read, stated in the rule's
`does_not_cover`, and the reason the self-test's plants can live in the probe
namespace instead of inside the real workflow.

It carries no verdict; `quality/gate.py` decides what a finding means.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

_RULES_YAML = "quality/rules.yaml"
_THIS = "quality/runners/workflow_credential_pins.py"

MIN_REASON = 12

VALVE = re.compile(r"#\s*creds:\s*(?P<reason>.*)$")


def declaration(root: Path) -> tuple[list[str], list[str]]:
    """(exporters, exported names), from the one rule whose runner is this file."""
    doc = yaml.safe_load((root / _RULES_YAML).read_text()) or {}
    for rule in doc.get("rules") or []:
        argv = (rule.get("runner") or {}).get("argv") or []
        if _THIS in [str(a) for a in argv]:
            return (
                [str(e) for e in (rule.get("exporters") or [])],
                [str(n) for n in (rule.get("exported_names") or [])],
            )
    return [], []


def _mapping(node: yaml.Node | None) -> dict[str, tuple[yaml.Node, yaml.Node]]:
    """A MappingNode's scalar keys → (key node, value node)."""
    if not isinstance(node, yaml.MappingNode):
        return {}
    out: dict[str, tuple[yaml.Node, yaml.Node]] = {}
    for key, value in node.value:
        if isinstance(key, yaml.ScalarNode):
            out[str(key.value)] = (key, value)
    return out


def _scalar(node: yaml.Node | None) -> str:
    return str(node.value) if isinstance(node, yaml.ScalarNode) else ""


def step_label(step: dict[str, tuple[yaml.Node, yaml.Node]], position: int) -> str:
    name = _scalar(step["name"][1]) if "name" in step else ""
    if name:
        return name
    if "id" in step:
        return f"id {_scalar(step['id'][1])}"
    return f"#{position + 1}"


def valve_in(lines: list[str], first: int, last: int) -> str | None:
    """The `# creds:` reason inside [first, last] or in the comment block above `first`."""
    for i in range(first, min(last, len(lines) - 1) + 1):
        stripped = lines[i].strip()
        if stripped.startswith("#") or " #" in lines[i]:
            m = VALVE.search(lines[i])
            if m:
                return m.group("reason").strip()
    i = first - 1
    while i >= 0 and lines[i].strip().startswith("#"):
        m = VALVE.search(lines[i])
        if m:
            return m.group("reason").strip()
        i -= 1
    return None


def step_spans(lines: list[str], starts: list[int], tail: int) -> list[tuple[int, int]]:
    """Each step's own lines: its `-` line to the line before the next step's
    comment block (a comment block directly above a step belongs to THAT step)."""
    spans: list[tuple[int, int]] = []
    for n, start in enumerate(starts):
        end = (starts[n + 1] - 1) if n + 1 < len(starts) else tail
        end = min(end, len(lines) - 1)
        while end > start and (not lines[end].strip() or lines[end].strip().startswith("#")):
            end -= 1
        spans.append((start, end))
    return spans


def scan(path: Path, rel: str, exporters: list[str], names: list[str], targets: dict) -> list[dict]:
    try:
        text = path.read_text()
        tree = yaml.compose(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return [
            {
                "path": rel,
                "line": 0,
                "msg": f"`{rel}` is not YAML this runner can read ({type(exc).__name__}), so no "
                "step in it was judged",
                "klass": "unreadable",
            }
        ]
    lines = text.splitlines()
    found: list[dict] = []
    jobs = _mapping(_mapping(tree).get("jobs", (None, None))[1])
    for job_name, (_k, job_node) in jobs.items():
        targets["jobs"] += 1
        steps_node = _mapping(job_node).get("steps", (None, None))[1]
        if not isinstance(steps_node, yaml.SequenceNode):
            continue
        steps = [s for s in steps_node.value if isinstance(s, yaml.MappingNode)]
        starts = [s.start_mark.line for s in steps]
        spans = step_spans(lines, starts, max(steps_node.end_mark.line, 0))
        exporter_at: tuple[str, int] | None = None
        # Indexed, not `zip(..., strict=True)`: a runner is invoked through the box's
        # own `python3`, which may predate the keyword.
        for position, node in enumerate(steps):
            first, last = spans[position]
            step = _mapping(node)
            targets["steps"] += 1
            uses = _scalar(step["uses"][1]) if "uses" in step else ""
            if uses and uses.split("@", 1)[0] in exporters:
                targets["exporter_steps"] += 1
                exporter_at = (uses.split("@", 1)[0], first + 1)
                continue
            if exporter_at is None or "run" not in step:
                continue
            targets["run_steps_after_an_exporter"] += 1
            env = _mapping(step["env"][1]) if "env" in step else {}
            missing = [n for n in names if n not in env]
            label = step_label(step, position)
            if not missing:
                targets["pinned_steps"] += 1
                continue
            reason = valve_in(lines, first, last)
            if reason is not None:
                targets["creds_valves"] += 1
                if len(reason) < MIN_REASON:
                    found.append(
                        {
                            "path": rel,
                            "line": first + 1,
                            "msg": (
                                f"job {job_name}, step '{label}': the creds reason is "
                                f"{len(reason)} characters — a step that keeps a cloud credential "
                                f"owes a sentence a reviewer can disagree with, and one under "
                                f"{MIN_REASON} characters is not one"
                            ),
                            "klass": "short_reason",
                        }
                    )
                continue
            found.append(
                {
                    "path": rel,
                    "line": first + 1,
                    "msg": (
                        f"job {job_name}, step '{label}' runs after {exporter_at[0]} "
                        f"(line {exporter_at[1]}) with {', '.join(missing)} unset in its env: — "
                        "the exporter wrote them into the JOB's environment, so this step "
                        "inherits a cloud credential nothing on it asked for. Pin each name in "
                        "the step's own env: (empty is a pin), or write `# creds: <reason>` in "
                        "the step when it really does need them"
                    ),
                    "klass": "unpinned",
                }
            )
    return found


def main(argv: list[str]) -> int:
    root = Path.cwd()
    exporters, names = declaration(root)
    targets: dict = {
        "files_scanned": 0,
        "jobs": 0,
        "steps": 0,
        "exporter_steps": 0,
        "run_steps_after_an_exporter": 0,
        "pinned_steps": 0,
        "creds_valves": 0,
        "declared_exporters": len(exporters),
        "declared_names": len(names),
    }
    findings: list[dict] = []
    for arg in argv:
        path = root / arg
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = sorted(p for p in path.rglob("*") if p.suffix in (".yml", ".yaml"))
        else:
            candidates = []
        for candidate in candidates:
            targets["files_scanned"] += 1
            rel = str(candidate.relative_to(root))
            findings.extend(scan(candidate, rel, exporters, names, targets))
    print(json.dumps({"protocol": "check-v1", "targets": targets, "findings": findings}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
