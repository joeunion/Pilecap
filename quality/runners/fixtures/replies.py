"""One runner that emits a NAMED reply — the seam's whole canary corpus.

    python3 quality/runners/fixtures/replies.py <name>

One file rather than one per form, because the interesting thing about each of
these is the SHAPE of the reply and a reader should be able to see all of them
in one screen. Every name below is driven by `quality/gate.py`'s seam leg, which
asserts the refusal class each one must provoke; a name nothing drives would be
a fixture that proves nothing, and a refusal class nothing emits would be a
branch of the protocol nobody can show fails.

The reply bodies are written as LITERAL TEXT rather than built with `json.dumps`
on purpose: half of them are not valid JSON, and the ones that are must be able
to carry a wrong type or an extra key without a serialiser tidying it away.
"""

from __future__ import annotations

import sys
import time

#: A legal reply, and the base every malformed one is a single edit away from.
CLEAN = '{"protocol": "check-v1", "targets": {"files_scanned": 3}, "findings": []}'

REPLIES: dict[str, str] = {
    "clean": CLEAN,
    # Two findings inside the declared roots, each carrying the class the
    # engine's ratchets are counted against.
    "findings": (
        '{"protocol": "check-v1", "targets": {"files_scanned": 2}, "findings": ['
        '{"path": "quality/one.py", "line": 4, "msg": "a shape finding", "klass": "shape"},'
        '{"path": "quality/two.py", "line": 9, "msg": "a naming finding",'
        ' "klass": "vocabulary"}]}'
    ),
    # Line 0 is how this engine already spells "the file itself".
    "line-zero": (
        '{"protocol": "check-v1", "targets": {"files_scanned": 1}, "findings": ['
        '{"path": "quality/whole-file.py", "line": 0, "msg": "about the file itself"}]}'
    ),
    # -- the malformations, one per refusal class ---------------------------
    "not-json": "Traceback (most recent call last):\n  the instrument fell over\n",
    "not-an-object": '["check-v1"]',
    "wrong-protocol": '{"protocol": "check-v2", "targets": {}, "findings": []}',
    "unknown-key": ('{"protocol": "check-v1", "targets": {}, "findings": [], "verdict": "clean"}'),
    "findings-not-a-list": '{"protocol": "check-v1", "targets": {}, "findings": 0}',
    "finding-not-an-object": (
        '{"protocol": "check-v1", "targets": {}, "findings": ["quality/x.py:3 wrong"]}'
    ),
    "finding-missing-key": (
        '{"protocol": "check-v1", "targets": {}, "findings": [{"path": "quality/x.py", "line": 3}]}'
    ),
    "finding-unknown-key": (
        '{"protocol": "check-v1", "targets": {}, "findings": ['
        '{"path": "quality/x.py", "line": 3, "msg": "m", "severity": "error"}]}'
    ),
    "finding-bad-type": (
        '{"protocol": "check-v1", "targets": {}, "findings": ['
        '{"path": "quality/x.py", "line": "three", "msg": "m"}]}'
    ),
    "finding-outside-roots": (
        '{"protocol": "check-v1", "targets": {}, "findings": ['
        '{"path": "config/settings/base.py", "line": 3, "msg": "not my tree"}]}'
    ),
    "targets-shape": (
        '{"protocol": "check-v1", "targets": {"files_scanned": "several"}, "findings": []}'
    ),
}


def main(argv: list[str]) -> int:
    # The engine appends the rule's declared roots after the runner's own
    # arguments, so a real runner reads them and this double ignores them: what
    # it emits is fixed by name, and reading a root would make the fixture's
    # reply depend on a tree it is not looking at.
    if not argv:
        print("replies.py takes one reply name", file=sys.stderr)
        return 2
    name = argv[0]
    if name == "sleep":
        # The instrument that hangs. Longer than any timeout the seam gives it,
        # so the refusal is the engine giving up rather than a race.
        time.sleep(30)
        return 0
    if name == "stderr-noise":
        # A runner may warn on stderr and still have answered: stderr is not the
        # protocol, and a reader that treated it as one would refuse every
        # instrument that mentions its own cache.
        print("warning: cold cache, this took longer than usual", file=sys.stderr)
        print(
            '{"protocol": "check-v1", "targets": {"files_scanned": 1}, "findings": ['
            '{"path": "quality/noisy.py", "line": 1, "msg": "found anyway"}]}'
        )
        return 0
    body = REPLIES.get(name)
    if body is None:
        print(f"replies.py has no reply named {name!r}", file=sys.stderr)
        return 2
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
