"""Screens import only from the declared layers — the runner half.

    python3 quality/runners/js_ingredient_boundary.py <root> [<root> …]

THE CHAIN, taken verbatim from the scaffold's own `src/primitives/README.md`
(as the scaffold shipped it): `copy <- tokens <- primitives <-
components <- kit <- screens <- app(routes)` and `api <- app(routes)`. An import may
only run DOWNWARD through that chain — a layer may import from itself or from
anything strictly below it, never from anything above. `api` is not on the
chain at all: it is a leaf only `app` and `journeys` may import directly,
because a component that imports `api` has resolved its own fetch, which is
the ingredient-boundary half of fe-conventions Law 4 ("components render;
they never fetch") as much as it is Law 2 ("one door to the backend"). Every
other layer never imports `api`.

`journeys/` sits ABOVE `app` in this instrument's ranking, not because the
scaffold's chain says so — it does not mention journeys — but because a
journey spec exercises the ASSEMBLED product and is the one file kind allowed
to reach into a route the way a person would; nothing in `src/` may import
FROM `journeys/`, which the same downward-only rule already forbids without a
special case.

WHY THIS RUNNER CANNOT REPEAT RULE 50'S MISTAKE (found when the
scaffold merged: `credentials: "same-origin"` read as a secret because the scan
keyed on an ENGLISH WORD in a name). This rule keys on FILE-PATH POSITION and
import-SPECIFIER RESOLUTION — never on a word appearing in an identifier — so
a framework whose own vocabulary happens to contain "token" or "component" as
a word cannot collide with a population defined by where a file LIVES and
what path an import STRING resolves to.

It carries no verdict; `quality/gate.py` decides what a finding means. No
Node/browser toolchain required — this reads source text with the standard
library only.
"""

from __future__ import annotations

import json
import posixpath
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from quality.runners import _kindscope  # noqa: E402

#: This script, as `rules.yaml` spells it in a `runner.argv`.
_SELF = "quality/runners/js_ingredient_boundary.py"


def allow_listed_api_importers(root: Path) -> frozenset[str]:
    """The paths this rule's `scope.allow_import` names — DERIVED, never typed here.

    Keyed on the rule whose `runner.argv` names THIS script rather than on a
    hard-coded rule id: the runner and the allow-list it honours cannot then
    drift apart, and a renumbered rule does not silently widen the fence.

    An entry ending in `/` is a directory prefix (rule 48's `config/settings/`
    shape); anything else is one exact file, which is the only form this rule
    uses today — a chokepoint is a module, not a tree.
    """
    doc = yaml.safe_load((root / "quality/rules.yaml").read_text()) or {}
    for rule in doc.get("rules") or []:
        argv = [str(a) for a in ((rule.get("runner") or {}).get("argv") or [])]
        if _SELF in argv:
            entries = (rule.get("scope") or {}).get("allow_import") or []
            return frozenset(str(e["path"]) for e in entries)
    return frozenset()


SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
ALLOW_IMPORT = allow_listed_api_importers(Path.cwd())

#: The chain, ranked low-to-high. A layer may import its own rank or lower;
#: never higher. Read from the scaffold's own declared taxonomy, not invented
#: here — `frontend/src/{api,tokens,copy,primitives,components,kit,screens,app}`
#: plus `frontend/journeys`.
LAYER_RANK: dict[str, int] = {
    "copy": 0,
    "tokens": 1,
    "primitives": 2,
    "components": 3,
    "kit": 4,
    "screens": 5,
    "app": 6,
    "journeys": 7,
}
#: `api` is off the chain entirely — a leaf, never a rank, reachable only by
#: the two names in ONLY_API_IMPORTERS.
API_LAYER = "api"
ONLY_API_IMPORTERS = frozenset({"app", "journeys"})
#: The kit is a door for screens: what lies past it is reached through `@pilecap/ui`, never by path.
KIT_DOOR = "@pilecap/ui"
SCREENS = "screens"
PAST_THE_KIT = frozenset({"tokens", "primitives", "components"})

#: A `from`-clause import or re-export, one line at a time. Deliberately
#: line-based, as `quality/runners/js_secrets.py` already is, and for the same
#: reason: a parser is a dependency this instrument is built to avoid, and an
#: import statement split across lines is a declared blind spot rather than a
#: silent miss.
FROM_CLAUSE = re.compile(
    r"""^\s*(?:import|export)\b[^;\n]*?\bfrom\s+(?P<q>['"])(?P<spec>[^'"]+)(?P=q)"""
)
#: A bare side-effect import: `import "./tokens.css";` — no `from` clause.
BARE_IMPORT = re.compile(r"""^\s*import\s+(?P<q>['"])(?P<spec>[^'"]+)(?P=q)""")

#: THE STATEMENT-LEVEL type-only form: `import type {...} from` / `export type
#: {...} from`. The INLINE modifier (`import { type X, Y }`) is deliberately
#: NOT matched — a mixed clause carries a value binding, so the erasure claim
#: the clause below rests on is false for it. Reading only the statement form
#: fails CLOSED (it flags more, never fewer) and is declared in does_not_cover.
TYPE_ONLY = re.compile(r"^\s*(?:import|export)\s+type\b")

#: THE GENERATED CLIENT MODULE — the one SOURCE whose document shapes any layer
#: may import as types (rule 51's generated-types clause, ruled 2026-09-02).
#:
#: This is NOT a `scope.allow_import` entry and must never become one: an
#: allow-list names CONSUMERS, and the consumers here are an open set that
#: grows by one line per screen forever — the hand-list-of-an-open-set shape
#: the same ruling rejected. This names the closed SOURCE side instead: two
#: module paths, machine-written and refreshed by the client fold, which
#: therefore cannot carry hand logic for a screen to couple to. Because it
#: names no file a rule's scope must validate, `_scope_paths` has nothing to
#: refuse and the clause lands with the runner rather than at a merge window.
#:
#: `api/refusals` is NOT here and cannot be: the refusal vocabulary is excluded
#: from the clause whatever its provenance, because wire-error semantics above
#: the client seam are the rule-14 translation's defect whether the import is
#: erased or not. That vocabulary reaches a screen through the surface-state
#: seam (the R-d-3 route), never directly.
GENERATED_CLIENT_MODULE = "frontend/src/api/client"

#: The face's package aliases (`frontend/tsconfig.json` `paths`), resolved like `@/`.
PACKAGE_ALIASES = {"@pilecap/ui/": "frontend/src/kit/", "@pilecap/copy/": "frontend/src/copy/"}
GENERATED_SCHEMA_DIR = "frontend/src/api/generated/"


def layer_of(rel: Path) -> str | None:
    """The declared layer a path belongs to, or None for anything outside the taxonomy.

    `frontend/src/<layer>/...` -> `<layer>` when `<layer>` is one this rule
    knows (a declared layer or `api`); `frontend/journeys/...` -> `journeys`.
    Everything else — `frontend/next.config.ts`, `frontend/package.json`, an
    `src/` entry this taxonomy does not name — is outside the population this
    rule enforces, exactly as a file outside `apps/`+`config/` is outside
    rule 8's.
    """
    parts = rel.parts
    if len(parts) >= 3 and parts[0] == "frontend" and parts[1] == "src":
        candidate = parts[2]
        if candidate in LAYER_RANK or candidate == API_LAYER:
            return candidate
        return None
    if len(parts) >= 2 and parts[0] == "frontend" and parts[1] == "journeys":
        return "journeys"
    return None


def resolve_spec(spec: str, file_rel: Path) -> Path | None:
    """An import specifier as a repo-relative path, or None for an external package.

    Two shapes only, matching what this template's scaffold actually writes:
    the `@/` alias (the scaffold's `tsconfig.json` maps it to `src/`, the same
    convention fe-conventions' own examples use) and a relative specifier,
    resolved against the IMPORTING file's directory with `posixpath.normpath`
    — imports are always POSIX-shaped regardless of the host OS. A bare
    package specifier (`"react"`, `"next/navigation"`) resolves to nothing:
    it names no path in this tree and is outside this rule's population by
    construction, never a false negative dressed as one.
    """
    if spec.startswith("@/"):
        return Path("frontend/src") / spec[2:]
    for alias, home in PACKAGE_ALIASES.items():
        if spec.startswith(alias):
            return Path(home) / spec[len(alias) :]
    if spec.startswith("."):
        combined = posixpath.normpath(posixpath.join(file_rel.parent.as_posix(), spec))
        return Path(combined)
    return None


def imports_in(path: Path, rel: Path) -> list[tuple[int, str, str]]:
    """(lineno, specifier, line text) for every import/re-export this file carries.

    The line text rides along because the generated-types clause is a question
    about the STATEMENT (was it erased?) and not only about where the specifier
    resolves to.
    """
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    found: list[tuple[int, str, str]] = []
    for lineno, text in enumerate(lines, start=1):
        m = FROM_CLAUSE.match(text) or BARE_IMPORT.match(text)
        if m:
            found.append((lineno, m.group("spec"), text))
    return found


def is_generated_document_type(text: str, target: Path) -> bool:
    """Rule 51's generated-types clause, as a TWO-PART predicate.

    Legal iff BOTH halves hold: the statement is type-only (the edge is erased
    at compile time) AND its source is the generated client module (the shapes
    are machine-written, so there is no hand logic on the other end to couple
    to). Either half alone is exactly what the ruling rejected — erased syntax
    alone is the blanket valve with no edges, and generated source alone would
    legalise a runtime import of the client from any layer, which is Law 2's
    whole subject.

    E+4's rule-16 transfer is the positive reason: a generated type is used
    VERBATIM and never re-declared, and the defect this protects against is the
    hand-typed shadow interface that agrees with its own test and renders
    `undefined` on a live surface.
    """
    if not TYPE_ONLY.match(text):
        return False
    posix = target.as_posix()
    for suffix in SUFFIXES:
        if posix.endswith(suffix):
            posix = posix[: -len(suffix)]
            break
    return posix == GENERATED_CLIENT_MODULE or posix.startswith(GENERATED_SCHEMA_DIR)


def is_allow_listed(rel: Path) -> bool:
    """Is this file one the rule's `scope.allow_import` names BY PATH?

    Named modules only — never a syntax, never a specifier shape. That is the
    whole distinction the R-d-3 re-ruling turns on: a blanket `import type`
    valve is legality by syntax and has no edges, while a path names one module
    and the rule's third canary proves the module next door still fires.
    """
    text = rel.as_posix()
    return any(
        text.startswith(entry) if entry.endswith("/") else text == entry for entry in ALLOW_IMPORT
    )


def findings_in(path: Path, rel: Path) -> tuple[list[dict], int]:
    own_layer = layer_of(rel)
    if own_layer is None:
        return [], 0
    own_rank = LAYER_RANK.get(own_layer)  # None for "api" itself
    found: list[dict] = []
    checked = 0
    for lineno, spec, text in imports_in(path, rel):
        target = resolve_spec(spec, rel)
        if target is None:
            continue
        target_layer = layer_of(target)
        if target_layer is None:
            continue
        checked += 1
        if target_layer == API_LAYER:
            # THE GENERATED-TYPES CLAUSE, checked before the reach: a type-only
            # import of the generated client module's document shapes is legal
            # from ANY layer. The refusal vocabulary is excluded by the SOURCE
            # half of the predicate — `api/refusals` is not the generated
            # module — so it stays flagged whatever its provenance, and reaches
            # a screen through the surface-state seam instead.
            if is_generated_document_type(text, target):
                continue
            # `api` REACHING ITS OWN LAYER IS A SELF-IMPORT, NEVER A REACH.
            # This rule's own statement opens "a file ... imports only from its
            # own layer or a layer strictly below it" — a layer importing
            # itself is the FIRST thing the chain permits, and `api` is not
            # exempted from that clause by being off the ranked chain. Being a
            # leaf bounds what may reach IN; it says nothing about a leaf's
            # internal cohesion, and `api/client.ts` importing `api/refusals.ts`
            # is exactly the one-door shape Law 2 asks for rather than a breach
            # of it. Without this clause the runner flagged six imports the
            # statement it cites permits — every internal edge of the scaffold's
            # own api layer (RDF-1; the Vcd measurement against merged
            # `frontend/`), which is a rule contradicting its own text.
            if (
                own_layer != API_LAYER
                and own_layer not in ONLY_API_IMPORTERS
                and not is_allow_listed(rel)
            ):
                found.append(
                    {
                        "path": str(rel),
                        "line": lineno,
                        "msg": (
                            f"`{own_layer}` imports the API client directly ({spec!r}) — only "
                            "`app` (routes) and `journeys` may; every other layer renders a "
                            "SurfaceState it is handed, it never resolves its own fetch "
                            "(fe-conventions Law 2 and Law 4)"
                        ),
                        "klass": "api-reach",
                    }
                )
            continue
        target_rank = LAYER_RANK.get(target_layer)
        if target_rank is None or own_rank is None:
            # `own_layer == "api"` — the leaf itself importing something. `api`
            # is never on the chain, so it has no ranked ceiling to violate;
            # its own shape (one door to the backend) is a different rule's
            # business.
            continue
        if target_rank > own_rank:
            found.append(
                {
                    "path": str(rel),
                    "line": lineno,
                    "msg": (
                        f"`{own_layer}` imports from `{target_layer}` ({spec!r}) — the import "
                        "contract runs the other way (copy <- tokens <- primitives <- "
                        "components <- kit <- screens <- app(routes)); an import may only run "
                        "DOWNWARD through it"
                    ),
                    "klass": "upward-import",
                }
            )
        elif own_layer == SCREENS and target_layer in PAST_THE_KIT:
            found.append(
                {
                    "path": str(rel),
                    "line": lineno,
                    "msg": (
                        f"`screens` imports `{target_layer}` past the kit ({spec!r}) — a screen "
                        f"takes what the kit draws through its door, `{KIT_DOOR}/<module>` "
                        "(`frontend/src/kit/surface.json` names every module and export); a "
                        "piece the kit does not export joins the kit first"
                    ),
                    "klass": "past-the-kit",
                }
            )
    return found, checked


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv]
    findings: list[dict] = []
    scanned = 0
    checked_total = 0
    for root in roots:
        for path in _kindscope.files_under(root, SUFFIXES):
            # `root` is handed to us relative to the checkout (e.g. "frontend"),
            # and `rglob` returns paths built on it — `path` IS already the
            # checkout-relative path `check_v1`'s outside-roots refusal wants,
            # with no second rebasing needed.
            rel = path
            scanned += 1
            file_findings, checked = findings_in(path, rel)
            findings.extend(file_findings)
            checked_total += checked
    print(
        json.dumps(
            {
                "protocol": "check-v1",
                "targets": {"files_scanned": scanned, "imports_checked": checked_total},
                "findings": findings,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
