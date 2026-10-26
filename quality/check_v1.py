"""check-v1 — the protocol an EXTERNAL runner speaks to the house-rules engine.

THE DESIGN LAW THIS FILE EXISTS TO HOLD: **an external runner is a measuring
instrument, never a judge.** A runner is handed a tree and answers one question
— *what did you see* — as JSON: the targets it counted and the findings it
found. Everything a verdict is made of stays here, on this side of the process
boundary: the override suppression, the ratchets, the floors, the canary
attribution, the self-test accounting, and 0/1/2. A runner that decided anything
would be a second gate with its own semantics, agreeing with this one only by
luck, and the day the two disagreed nothing could say which was right.

THE REPLY, whole:

    {"protocol": "check-v1",
     "targets":  {"files_scanned": 12},
     "findings": [{"path": "…/x.ts", "line": 3, "msg": "…", "klass": "…"}]}

`klass` is optional and feeds the engine's per-class ratchets; everything else
above is required, and nothing else is allowed. Strict, in the same way an `In`
schema is strict at the REST door and for the same reason: a key the reader
silently drops is a claim the writer thinks it made.

**COULD-NOT-LOOK IS NOT A PASS, AND THAT IS THE WHOLE POINT OF THE MODULE.**
Every way a runner can fail to be believed — missing, not executable, dead,
slow, mute, lying, or answering about files outside the roots it was pointed
at — raises `RunnerRefused`, which the engine turns into ENFORCEMENT BROKEN
(exit 2) naming the runner and the rule. The failure mode this refuses by
construction is the cheapest one in the world to ship by accident: a runner
that crashes, prints nothing, and is read as *zero findings*, so a whole
language's rules report green from the day they are wired until somebody plants
a violation by hand. The canaries for every class below are driven by the
engine's own self-test, which is what keeps this docstring a fact.

Nothing here imports Django, yaml, or the rest of the engine's world: the
protocol is a pure function of a subprocess's exit status and its bytes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from quality.checks import CheckResult, Finding
from quality.could_not_look import CouldNotLook

#: The one protocol version this engine speaks. A reply that names anything else
#: is refused rather than guessed at: a runner built for a later protocol may be
#: describing findings with a meaning this reader does not have.
PROTOCOL = "check-v1"

#: The reply's whole vocabulary. Closed, and checked both ways — a missing key
#: and an unknown key are two different refusals because they are two different
#: mistakes.
REPLY_KEYS: frozenset[str] = frozenset({"protocol", "targets", "findings"})
FINDING_KEYS_REQUIRED: frozenset[str] = frozenset({"path", "line", "msg"})
FINDING_KEYS_OPTIONAL: frozenset[str] = frozenset({"klass"})

#: How long a runner may take before it is treated as unable to answer. A
#: default rather than a constant: a rule may raise it, and a rule that needs to
#: raise it a long way is telling the reader something about its instrument.
DEFAULT_TIMEOUT = 120


#: EVERY WAY A RUNNER CAN FAIL TO BE BELIEVED, declared. Two censuses hold it
#: honest and they close opposite holes. `emitted_refusal_classes()` reads this
#: module's own source and must return exactly this set — so a class cannot be
#: added, renamed or retired quietly. The engine's seam leg then demands a canary
#: for every member — so a class cannot exist unproven.
#:
#: The hole this closes is the nastiest one an assertion corpus has: a form whose
#: expected signature the code can no longer emit does not fail. It matches
#: nothing, reports nothing, and reads as *stayed silent* forever. A signature
#: checked against a set derived from the source cannot rot that way, because
#: the day the source stops emitting it the set stops containing it.
REFUSAL_CLASSES: frozenset[str] = frozenset(
    {
        "runner-absent",
        "runner-not-executable",
        "runner-failed",
        "runner-timeout",
        "reply-not-json",
        "reply-not-an-object",
        "reply-unknown-key",
        "reply-wrong-protocol",
        "findings-not-a-list",
        "finding-not-an-object",
        "finding-missing-key",
        "finding-unknown-key",
        "finding-bad-type",
        "finding-outside-roots",
        "targets-shape",
    }
)


def emitted_refusal_classes() -> frozenset[str]:
    """The refusal classes this module's source can actually raise.

    Derived from the text rather than by catching exceptions, because the point
    is to see the classes that exist WITHOUT having to provoke each one — the
    provoking is the seam leg's job and this is what tells it what to provoke.
    """
    source = Path(__file__).read_text()
    return frozenset(re.findall(r'(?:RunnerRefused|_refuse)\(\s*"([a-z0-9-]+)"', source))


class RunnerRefused(CouldNotLook):
    """The runner could not be believed — enforcement broken, never a clean run.

    Carries the CLASS of the refusal as well as its prose, so the engine's
    self-test can assert that each class fires for its own canary rather than
    counting one aggregate and hoping the coverage inside it never moved.
    """

    def __init__(self, klass: str, detail: str) -> None:
        super().__init__(detail)
        self.klass = klass
        self.detail = detail


def _refuse(klass: str, where: str, detail: str) -> RunnerRefused:
    return RunnerRefused(klass, f"{where}: {detail}")


def resolve_runner(root: Path, argv: list[str]) -> str:
    """The executable `argv[0]` names, or a refusal saying which way it is absent.

    Two shapes, because two different things are wrong. A BARE NAME is a
    toolchain question — `node`, `false` — answered by the PATH this run holds;
    a name with a separator is a file in this tree, answered by the tree. The
    distinction is what lets the tri-state above this module say "the toolchain
    for this kind is not installed" without also having to guess whether the
    author meant a relative path.
    """
    if not argv:
        raise RunnerRefused("runner-absent", "a runner with an empty argv names no program")
    head = argv[0]
    if os.sep in head or (os.altsep and os.altsep in head):
        candidate = (root / head).resolve()
        if not candidate.exists():
            raise RunnerRefused(
                "runner-absent",
                f"the runner {head!r} names no file on this tree — the rule points at an "
                "instrument that is not here, and a missing instrument is a look that did "
                "not happen",
            )
        if not os.access(candidate, os.X_OK):
            raise RunnerRefused(
                "runner-not-executable",
                f"the runner {head!r} exists and is not executable — nothing ran, so "
                "nothing was seen; make it executable or invoke it through its interpreter",
            )
        return str(candidate)
    found = shutil.which(head)
    if found is None:
        raise RunnerRefused(
            "runner-absent",
            f"the toolchain program {head!r} is not on this run's PATH — the rule's "
            "instrument is not installed here",
        )
    return found


def invoke(
    root: Path,
    *,
    argv: list[str],
    roots: list[str],
    where: str,
    timeout: int = DEFAULT_TIMEOUT,
    remedy: str = "",
) -> CheckResult:
    """Run the runner over `root` and read its reply, or refuse.

    `where` is what the refusal messages name — the rule and its runner — so
    that a reader meets the failing instrument by name in the first line rather
    than after reading a stack trace.

    THE ROOTS ARE APPENDED TO THE COMMAND, and that is the whole reason the
    out-of-roots refusal below has teeth. The runner is TOLD where to look by
    the same declaration it is afterwards measured against, so "the rule's
    scope" and "what the instrument scanned" cannot be two lists that drift.
    A runner that took its roots from its own configuration would be deciding
    its rule's subject, which is a verdict semantic wearing a file path.

    `remedy` is one sentence the caller knows and this module does not: WHICH
    declaration would widen the roots, in the file the caller's rule is written
    in. It rides only on the out-of-roots refusal, because that is the one
    refusal whose cause can be "the rule is about something its kind cannot
    name" rather than "the instrument is broken" — and a refusal that says the
    scope is wrong without saying where the scope is declared sends a product
    to the template-owned file a fold overwrites.
    """
    program = resolve_runner(root, argv)
    command = [program, *argv[1:], *roots]
    try:
        proc = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise _refuse(
            "runner-timeout",
            where,
            f"the runner did not answer within {timeout}s — an instrument that hangs could "
            "not look, and a run that gave up waiting has no findings to report",
        ) from exc
    except OSError as exc:
        raise _refuse("runner-absent", where, f"the runner could not be started ({exc})") from exc
    if proc.returncode != 0:
        raise _refuse(
            "runner-failed",
            where,
            f"the runner exited {proc.returncode}. A non-zero exit is COULD NOT LOOK and "
            "never zero findings — the engine, not the runner, decides whether a tree is "
            f"clean.\n      stdout: {proc.stdout.strip()[-400:]!r}"
            f"\n      stderr: {proc.stderr.strip()[-400:]!r}",
        )
    return parse(proc.stdout, roots=roots, where=where, remedy=remedy)


def parse(payload: str, *, roots: list[str], where: str, remedy: str = "") -> CheckResult:
    """A runner's stdout as a CheckResult, or a refusal naming the malformation.

    Split out from `invoke` deliberately: the parsing half is a pure function of
    a string, so every malformation class can be exercised without a process,
    and the process half can be exercised without inventing a malformation.
    """
    try:
        reply: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise _refuse(
            "reply-not-json",
            where,
            f"the runner's stdout is not JSON ({exc.msg} at line {exc.lineno}). A runner "
            "that printed a traceback, a progress bar or nothing at all has not reported "
            f"a clean tree.\n      stdout: {payload.strip()[-400:]!r}",
        ) from exc
    if not isinstance(reply, dict):
        raise _refuse(
            "reply-not-an-object",
            where,
            f"the reply is a {type(reply).__name__} and check-v1 is an object with "
            f"{', '.join(sorted(REPLY_KEYS))}",
        )
    unknown = sorted(set(reply) - REPLY_KEYS)
    if unknown:
        raise _refuse(
            "reply-unknown-key",
            where,
            f"the reply carries {', '.join(repr(k) for k in unknown)}, which check-v1 does "
            "not define. An unknown key is a claim this reader would silently drop, so it "
            "is refused instead — extend the protocol in quality/check_v1.py first",
        )
    if reply.get("protocol") != PROTOCOL:
        raise _refuse(
            "reply-wrong-protocol",
            where,
            f"the reply declares protocol {reply.get('protocol')!r}, not {PROTOCOL!r} — a "
            "runner speaking a protocol this engine does not know is not a runner this "
            "engine can read",
        )
    result = CheckResult()
    _read_targets(reply.get("targets"), result=result, where=where)
    _read_findings(reply.get("findings"), result=result, roots=roots, where=where, remedy=remedy)
    return result


def _read_targets(raw: Any, *, result: CheckResult, where: str) -> None:
    """`targets` into the CheckResult's counters, or a refusal.

    Targets are what the engine's FLOORS read, which is why their shape is
    checked as hard as the findings' is: a floor is the mechanism that says
    green-because-empty is not a pass, and a floor fed a string counts nothing
    while reporting something.
    """
    if raw is None:
        raise _refuse(
            "targets-shape",
            where,
            "the reply carries no `targets` — a runner that reports findings and counts "
            "nothing leaves every floor unbound, which is how a scan of an empty tree "
            "reads as a clean one",
        )
    if not isinstance(raw, dict):
        raise _refuse("targets-shape", where, f"`targets` is a {type(raw).__name__}, not an object")
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise _refuse("targets-shape", where, f"`targets` has a nameless key {key!r}")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _refuse(
                "targets-shape",
                where,
                f"`targets[{key!r}]` is {value!r}, and a floor can only be read against a count",
            )
        result.count(key, value)


def _read_findings(
    raw: Any, *, result: CheckResult, roots: list[str], where: str, remedy: str = ""
) -> None:
    """`findings` into the CheckResult, or a refusal naming what is wrong with one."""
    if not isinstance(raw, list):
        raise _refuse(
            "findings-not-a-list",
            where,
            f"`findings` is a {type(raw).__name__}, not a list. A reply with no findings "
            "says so with an empty list; a reply that cannot say it in the protocol's own "
            "grammar is not saying the tree is clean",
        )
    for index, item in enumerate(raw):
        result.findings.append(
            _read_finding(item, index=index, roots=roots, where=where, remedy=remedy)
        )


def _read_finding(
    item: Any, *, index: int, roots: list[str], where: str, remedy: str = ""
) -> Finding:
    at = f"findings[{index}]"
    if not isinstance(item, dict):
        raise _refuse(
            "finding-not-an-object", where, f"{at} is a {type(item).__name__}, not an object"
        )
    keys = set(item)
    missing = sorted(FINDING_KEYS_REQUIRED - keys)
    if missing:
        raise _refuse(
            "finding-missing-key",
            where,
            f"{at} is missing {', '.join(repr(k) for k in missing)} — a finding the engine "
            "cannot place is a finding it cannot suppress, ratchet or attribute",
        )
    unknown = sorted(keys - FINDING_KEYS_REQUIRED - FINDING_KEYS_OPTIONAL)
    if unknown:
        raise _refuse(
            "finding-unknown-key",
            where,
            f"{at} carries {', '.join(repr(k) for k in unknown)}, which check-v1 does not define",
        )
    path, line, msg = item["path"], item["line"], item["msg"]
    klass = item.get("klass", "")
    if not isinstance(path, str) or not path.strip():
        raise _refuse("finding-bad-type", where, f"{at}.path is {path!r}, not a path")
    if isinstance(line, bool) or not isinstance(line, int) or line < 0:
        raise _refuse(
            "finding-bad-type",
            where,
            f"{at}.line is {line!r}, not a line number (0 is legal and means the file itself)",
        )
    if not isinstance(msg, str) or not msg.strip():
        raise _refuse("finding-bad-type", where, f"{at}.msg is {msg!r}, not a message")
    if not isinstance(klass, str):
        raise _refuse("finding-bad-type", where, f"{at}.klass is {klass!r}, not a class name")
    _refuse_outside_roots(path, index=index, roots=roots, where=where, remedy=remedy)
    return Finding(path, line, msg, klass)


def _refuse_outside_roots(
    path: str, *, index: int, roots: list[str], where: str, remedy: str = ""
) -> None:
    """A finding must land inside the roots the rule pointed the runner at.

    THE SUBJECT IS SCOPE, NOT TIDINESS. A rule's roots are what its floors are
    measured over, what its valves are discovered in, and what a reader
    understands the rule to be about. A runner free to report anywhere could
    move a rule's subject without the rule changing — the JS rule quietly
    filing findings against `config/`, where a Python rule already has a
    different opinion and a different valve syntax. Refused rather than
    filtered: silently dropping the out-of-scope half would leave the runner
    believing it had reported something.
    """
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise _refuse(
            "finding-outside-roots",
            where,
            f"findings[{index}].path {path!r} is not a path relative to the tree root",
        )
    for root in roots:
        wanted = Path(root).parts
        if candidate.parts[: len(wanted)] == wanted:
            return
    raise _refuse(
        "finding-outside-roots",
        where,
        f"findings[{index}].path {path!r} is outside the roots this rule declares "
        f"({', '.join(roots) or 'none'}) — a runner may only report about what it was "
        "pointed at" + (f". {remedy}" if remedy else ""),
    )
