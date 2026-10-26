"""No credential is written down in the browser tree — the runner half.

    python3 quality/runners/js_secrets.py <root> [<root> …]

THE POPULATION, and why it is a second one rather than a wider first. The house
already refuses a secret in the tree; that refusal is enforced over Python, over
the settings modules and over the environment files, and it has never had a
subject in a browser tree because there has never been one. A browser tree is
the place where this defect is WORST rather than merely equal: a literal in a
Python module is readable by whoever can read the repository, and a literal in a
frontend module is readable by whoever loads the page. The right form is the
same one the settings modules already use — the value arrives from the
environment at build time and the tree names it rather than holding it.

WHAT IT LOOKS AT, exactly: a declaration or an object property whose NAME is
credential-shaped and whose value is a quoted literal. Named rather than
entropic on purpose. An entropy scan over a browser tree fires on hashes,
base64 sprites, minified chunks and generated ids, and a rule whose findings are
mostly noise gets valved everywhere and then means nothing; a name is a claim
the author made about what the value IS, which is a closed question with an
answer the author already wrote down.

It carries no verdict. It prints a check-v1 reply — targets and findings — and
`quality/gate.py` decides what that means, applies the valves, reads the floors
and chooses the exit code. No Node or browser toolchain required, so a checkout
that has no such toolchain at all can still be scanned the day it grows a tree
— this module reads only the interpreter running it and `quality/rules.yaml`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _kindscope  # noqa: E402

#: The suffixes a browser tree's own source carries. Data files and stylesheets
#: are out of this instrument's population and stay in its blind spots below.
SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")

#: Directories a browser tree grows that are not its source: vendored packages
#: and build output. Read from `quality/rules.yaml`'s `scope_kinds.js.skip_dirs`
#: — the F1 fix (Vra, 2026-08-31): this used to be a literal here AND a different one
#: (just `__pycache__`) in `quality/gate.py`'s override walk, two lists that
#: could disagree. `Path.cwd()` is the checkout root: `quality/check_v1.py`'s
#: `invoke()` always runs a runner with `cwd=<the real tree root>`, self-test
#: plants included — never a copy.

#: The credential-shaped name. `*_hash` and `*Hash` are excluded for the reason
#: the field-policy rule excludes them: a hash is the artefact that exists so
#: the secret does not have to.
NAME = re.compile(
    r"(secret|token|credential|password|passwd|api_?key|private_?key|signing_?key"
    r"|access_?key|client_?secret)",
    re.IGNORECASE,
)
NOT_A_SECRET = re.compile(r"hash$", re.IGNORECASE)

#: A binding — `const apiSecret = "…"` — and an object property — `apiSecret:
#: "…"`. Two forms rather than a general expression parser, because these two
#: are what a credential is actually written as and a parser would be a
#: dependency this instrument is built to avoid.
BINDING = re.compile(
    r"""^\s*(?:export\s+)?(?:const|let|var)\s+
        (?P<name>[A-Za-z_$][\w$]*)\s*
        (?::[^=]+?)?=\s*
        (?P<quote>["'`])(?P<value>[^"'`]*)(?P=quote)""",
    re.VERBOSE,
)
PROPERTY = re.compile(
    r"""^\s*(?P<name>[A-Za-z_$][\w$]*)\s*:\s*
        (?P<quote>["'`])(?P<value>[^"'`]*)(?P=quote)""",
    re.VERBOSE,
)

#: Short enough that a flag, a mode name or an empty placeholder is not a
#: credential; long enough that a real one clears it. The same reasoning as the
#: override reason floor: force a real value to be a real value.
MIN_VALUE = 8

#: fetch's OWN enumerated `credentials:` option (the `RequestCredentials`
#: union). The property name matches `credential` and a member like
#: "same-origin" clears MIN_VALUE, so a name-based scan reads cookie-inclusion
#: policy as a secret — found live at the R-a x SCAFFOLD merge
#: (frontend/src/api/client.ts's `fetch(..., { credentials: "same-origin" })`),
#: which is exactly the risk a NAME-vocabulary scan carries: a framework's own
#: word colliding with a credential-shaped one. Closed narrowly, by the exact
#: property name and the exact closed enum fetch itself defines — never by
#: widening MIN_VALUE or loosening NAME, either of which would cost the rule
#: its whole population.
FETCH_CREDENTIALS_MODES = frozenset({"omit", "same-origin", "include"})


def _is_fetch_credentials_mode(name: str, value: str) -> bool:
    """`credentials: "same-origin"` and its two siblings — fetch's own words."""
    return name.lower() == "credentials" and value in FETCH_CREDENTIALS_MODES


def findings_in(path: Path, rel: str) -> list[dict]:
    found: list[dict] = []
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return found
    for lineno, text in enumerate(lines, start=1):
        for pattern in (BINDING, PROPERTY):
            m = pattern.match(text)
            if not m:
                continue
            name, value = m.group("name"), m.group("value")
            if NOT_A_SECRET.search(name) or not NAME.search(name):
                continue
            if _is_fetch_credentials_mode(name, value):
                continue
            if len(value) < MIN_VALUE:
                continue
            found.append(
                {
                    "path": rel,
                    "line": lineno,
                    "msg": (
                        f"`{name}` holds a literal in a tree that ships to a browser — "
                        "whoever loads the page can read it. Take the value from the build "
                        "environment and let this module name it, the way the settings "
                        "modules already do"
                    ),
                    "klass": "literal",
                }
            )
            break
    return found


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv]
    findings: list[dict] = []
    scanned = 0
    for root in roots:
        for path in _kindscope.files_under(root, SUFFIXES):
            scanned += 1
            findings.extend(findings_in(path, str(path)))
    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {"files_scanned": scanned, "literals_flagged": len(findings)},
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
