"""The house-rules gate. Rules are data (quality/rules.yaml); this is the engine.

    python -m quality.gate consistency + live scan + floors + budgets
                                         + the Django system-check leg
    python -m quality.gate --diff REF all of the above + the diff-aware checks
                                         against REF
    python -m quality.gate --selftest plant every canary through the real
                                         scope and demand it fires for ITS rule;
                                         plant every negative and demand silence;
                                         restore everything, whatever happens
    python -m quality.gate --selftest-inputs
                                         every path on this tree that can change
                                         the verdict above, derived and sorted,
                                         one per line — what a banked verdict is
                                         keyed on. Measures nothing; exit 2 and
                                         NO list if any of it cannot be derived

Exit codes: 0 clean · 1 violations · 2 ENFORCEMENT BROKEN (dead canary, noisy
negative, unbound scope/floor, consistency failure, unknown flag, dirty tree
under a plant path, a stale plant standing on the tree, a runner that could not
be believed). 2 outranks a pass — a gate that is broken must never read as a
gate that passed.

Every mode begins with the same preflight: a self-test killed between plant and
restore leaves its fixtures standing, and everything below would then be
measuring them. The quiet half is why it runs first — a planted NEGATIVE reports
nothing at all, so the run goes GREEN over a tree that is partly fixture.

Scope kinds: a rule may be about a language that is not Python. It declares
`kind:` (roots, file suffixes and the comment token a valve is written with),
`needs_tree:` (the tree whose absence makes its live scan a PRINTED skip rather
than a red) and `runner:` (an external instrument speaking the check-v1
protocol, `quality/check_v1.py`). The runner MEASURES and this engine JUDGES:
overrides, ratchets, floors, canary attribution and 0/1/2 never cross the
process boundary, and a runner that cannot be believed is exit 2 rather than
zero findings.

Overrides: a line carrying `# rule-<id>: <reason>` — or the same marker in that
file's own comment syntax, `// rule-<id>: <reason>` in a kind that spells it
that way — on the flagged line or in
the contiguous comment block directly above it — suppresses that rule there.
Every override is counted and printed as a standing section on every run. An
override whose reason is missing or too short to be one is itself a violation.

Ratchets: a rule whose subject already has a backlog records the SIZE of that
backlog in `rules.yaml`, per class of finding — `ratchets: {selectors: 9}`. The
count may shrink and never grow: at or below the number the findings are a
standing backlog, printed as notes; one over it and every finding in that class
is a violation naming the growth. Shrinking never tightens the number by
itself — a human reads the note and commits the lower one, in a diff somebody
sees. A class with no entry is ratcheted at zero, which is what "clean" means.

Self-test plants into the REAL tree (create/append per fixture, try/finally
restore), because a canary proven against a copy proves the copy. It therefore
refuses to run when the tree is already dirty under any plant path: it could
not tell its own plants from your work, and could not restore honestly.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quality import check_v1  # noqa: E402
from quality import checks as C  # noqa: E402
from quality import partition as PART  # noqa: E402
from quality import worlds as W  # noqa: E402
from quality.checks import FLOOR_PROXIES, REGISTRY, CheckResult, Finding  # noqa: E402

_DOC: dict = yaml.safe_load((ROOT / "quality" / "rules.yaml").read_text())

# --- THE PRODUCT'S DRAWER (EP2) -------------------------------------------------
#
# THE SUBJECT. `quality/rules.yaml` is a TEMPLATE-OWNED file. A product that
# wants a rule of its own — and every product does — had nowhere to put it but
# inside that file, so every fold met a conflict in the one file whose conflicts
# are the most expensive on the tree, and the product's rules were re-applied by
# hand each release (P21 § 7b EP2; the consumer's own census, boundary 2b).
#
# THE DRAWER. `quality/local/rules.yaml` is loaded BESIDE the template's, at
# this one loader, and the template never writes a byte of it. Its fixtures live
# under `quality/local/{canary,negative}/<id>/` and its check-v1 runners under
# `quality/local/runners/`, so a product adds a rule without touching one
# template-owned path and a fold has nothing to merge.
#
# FIVE KEYS AND NO MORE. `rule_id_namespace`, `template_rule_ids_through`,
# `rules:`, `ratchets:` and `scope_kinds:`. Anything else — a local `seam:`, a
# local `selftest_residence_backlog:` — is exit 2 NAMING THE KEY AND THE FILE,
# because each of those is a statement about the ENGINE rather than about a
# rule, and an engine a product can reconfigure in a file the template never
# reads is an engine the template cannot vouch for.
#
# WHY `scope_kinds:` IS THE FIFTH, AND WHY IT WAS THE FOURTH'S MISTAKE. D1 read
# it as an engine statement and refused it by name. It is not: a scope kind is
# WHAT A RULE IS ABOUT — its roots, its suffixes, its valve token — and the
# template declares exactly two, `py` (apps, config) and `js` (frontend). A
# product rule whose subject is a ledger, a doc, a `.env.example` or a canary
# under `quality/local/` therefore had NO kind it could name, and
# `check_v1._refuse_outside_roots` refused its runner's every finding: `path
# 'docs/product/queue.md' is outside the roots this rule declares (apps,
# config)`. The first consumer met it on four rules that had run as in-process
# checks for a year. So the key is the drawer's, under the same law as every
# other drawer: a product kind may NOT reuse a template kind's name (refused,
# naming both files), its roots may name any directory or file this tree
# carries, and `SCOPE_KINDS` is the UNION — which is what makes `kind_roots`,
# the override walk, the memo's walk and every floor read the product's roots
# without one template-owned byte moving.
#
# THE TWO NAMESPACE KEYS LIVE HERE AND NOWHERE ELSE. D1 put them in the
# template-owned file because the drawer did not exist yet; this is the home
# they were always for. A tree that still carries either of them in
# `quality/rules.yaml` is refused with the line that names the move — a product
# mid-adoption is exactly who hits it, and a refusal that says which two lines
# to cut into which file costs them a minute instead of an afternoon.
#
# ABSENT IS BYTE-IDENTICAL. No drawer means `LOCAL_DOC` is `{}`, `LOCAL_RULES`
# is empty, and every reader, census, digest and self-test number is the number
# the template printed before the drawer existed. That negative is the drive's
# assertion, not this comment's claim.
LOCAL_DIR = ROOT / "quality" / "local"
LOCAL_RULES_PATH = LOCAL_DIR / "rules.yaml"
LOCAL_CANARY_DIR = LOCAL_DIR / "canary"
LOCAL_NEGATIVE_DIR = LOCAL_DIR / "negative"
LOCAL_RUNNER_DIR = LOCAL_DIR / "runners"

#: The whole vocabulary of the drawer. Closed, and the refusal names the key.
LOCAL_KEYS: frozenset[str] = frozenset(
    {"rule_id_namespace", "template_rule_ids_through", "rules", "ratchets", "scope_kinds"}
)

#: The keys whose HOME is the drawer — refused in the template-owned file.
MOVED_KEYS: tuple[str, ...] = ("rule_id_namespace", "template_rule_ids_through")


def _git_tracks(rel: str) -> bool:
    """Does git carry anything at this path? (a file, or a file under it).

    ITS OWN SUBPROCESS, at import time, because `_tracked_paths()` is four
    thousand lines below this one and the drawer is read before it exists. It
    runs only when a drawer declares `scope_kinds:`, which is at most a handful
    of roots on the trees that have one and none at all on the trees that do
    not.

    UNREADABLE IS TRUE, never false: a checkout with no git (an exported tree,
    a tarball) must not have every drawer root refused as untracked. The
    existence test beside this one is what still holds there.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(ROOT), "ls-files", "--error-unmatch", "-z", "--", rel],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:  # no git, no repository, no answer — existence stands alone
        return True
    return done.returncode == 0 and bool(done.stdout.strip("\0").strip())


def _local_scope_kind_problems(raw: object) -> list[str]:
    """The drawer's `scope_kinds:`, shape-checked — the rest is `seam_consistency`'s.

    THREE REFUSALS AND NOT ONE MORE, because the other half of a kind's shape
    (non-empty `suffixes:`, a dot on each one, a comment token) is already the
    engine's own census over the UNION, and a second opinion here would be two
    spellings of one law that can disagree.

    (a) A NAME THE TEMPLATE ALREADY DECLARES is refused NAMING BOTH FILES. A
        silent win by either side is the worst answer there is: the drawer
        shadowing `py` would re-point every template rule's roots from a file
        the template never reads, and the template shadowing the drawer would
        make a product's rules quietly about somebody else's tree.
    (b) A ROOT THAT IS NOT A PATH OF THIS TREE — absolute, or carrying `..` —
        is refused with the identical sentence `needs_tree` and
        `check_v1._refuse_outside_roots` already use, rather than a third,
        looser one.
    (c) A ROOT THIS TREE DOES NOT CARRY is refused, because a kind whose roots
        name nothing is a rule that scans nothing and reports clean. A root may
        be a DIRECTORY or a FILE (`.env.example` is a subject a product really
        has), and both halves of the walk below know it.
    """
    if raw is None:
        return []
    where = "quality/local/rules.yaml: `scope_kinds:`"
    if not isinstance(raw, dict) or not raw:
        return [f"{where} is {raw!r}, not a non-empty mapping of kind name -> declaration"]
    template_kinds = _DOC.get("scope_kinds") or {}
    problems: list[str] = []
    for name, kind in raw.items():
        label = str(name)
        if label in template_kinds:
            problems.append(
                f"{where} declares the kind {label!r}, which quality/rules.yaml already "
                f"declares. A product kind may not reuse a template kind's name: the two "
                f"files would each believe they owned {label!r}'s roots, and whichever won "
                f"would re-point rules written in the other. Name yours something the "
                f"template does not ({', '.join(sorted(template_kinds)) or 'none'} are taken)"
            )
            continue
        if not isinstance(kind, dict):
            problems.append(f"{where} kind {label!r}: {kind!r} is not a declaration")
            continue
        roots = kind.get("roots")
        if not isinstance(roots, list) or not roots:
            problems.append(f"{where} kind {label!r}: roots is {roots!r}, not a non-empty list")
            continue
        for root in roots:
            candidate = Path(str(root))
            if candidate.is_absolute() or ".." in candidate.parts:
                problems.append(
                    f"{where} kind {label!r}: root {root!r} is not a path RELATIVE to the "
                    "checkout root — an absolute path or a `..` segment could name something "
                    "this tree does not own"
                )
                continue
            if not (ROOT / candidate).exists():
                problems.append(
                    f"{where} kind {label!r}: root {root!r} is neither a directory nor a "
                    "file on this tree. A kind whose roots name nothing is a rule that "
                    "scans nothing and reports clean — which is the one verdict this "
                    "engine will not produce"
                )
                continue
            # TRACKED, NOT MERELY PRESENT, and refused HERE rather than four
            # readers later. The engine's input list is derived from the
            # repository's own answer about what is in a walk
            # (`selftest_inputs_for`, population 6), so an UNTRACKED root scans
            # happily all the way to `--selftest-inputs`, which then refuses it
            # with a sentence about an emptied walk — a refusal whose subject
            # is the drawer, arriving from a reader whose subject is not.
            if not _git_tracks(str(candidate)):
                problems.append(
                    f"{where} kind {label!r}: root {root!r} is on this tree and git carries "
                    "nothing at it. The engine's input list is the tracked set, so an "
                    "untracked root walks files no verdict is keyed on — the walk reads "
                    "full and the key reads empty. Track it, or name a root that is"
                )
    return problems


def _read_local() -> tuple[dict, list[dict], list[str]]:
    """(the drawer's parse, its rules, the problems) — never a traceback.

    Reported through `consistency()` rather than raised, for the reason
    `_read_namespace` is: a malformed drawer must reach a reader as a named
    exit 2, and it must not take the four readers (`--explain`, the listing,
    `--selftest-inputs`, `--fold-map`) down with it on the way.
    """
    problems: list[str] = []
    for key in MOVED_KEYS:
        if key in _DOC:
            problems.append(
                f"quality/rules.yaml declares `{key}:` — that key's HOME is "
                f"quality/local/rules.yaml, the product's drawer (P21 EP2, ADR gate-5). "
                f"quality/rules.yaml is template-owned and a fold overwrites it, so a "
                f"declaration there is a declaration that disappears. Move the line "
                f"(with `{[k for k in MOVED_KEYS if k != key][0]}:` beside it) into "
                f"quality/local/rules.yaml and delete it here"
            )
    if not LOCAL_RULES_PATH.is_file():
        return {}, [], problems
    try:
        loaded = yaml.safe_load(LOCAL_RULES_PATH.read_text())
    except (OSError, yaml.YAMLError) as exc:
        problems.append(
            f"quality/local/rules.yaml could not be read as YAML — {exc}. The drawer is an "
            "input to every verdict on this tree, so a drawer nobody can parse is "
            "could-not-look, never an empty drawer"
        )
        return {}, [], problems
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        problems.append(
            f"quality/local/rules.yaml is a {type(loaded).__name__}, not a mapping — the "
            f"drawer's top level is keys: {', '.join(sorted(LOCAL_KEYS))}"
        )
        return {}, [], problems
    for key in sorted(loaded):
        if key in LOCAL_KEYS:
            continue
        problems.append(
            f"quality/local/rules.yaml declares `{key}:`, which is not one of the drawer's "
            f"keys ({', '.join(sorted(LOCAL_KEYS))}). `{key}` configures the ENGINE rather "
            "than a rule, and the engine is the template's — a product that could "
            "reconfigure it in a file the template never reads would be running a gate "
            "nothing vouches for"
        )
    problems.extend(_local_scope_kind_problems(loaded.get("scope_kinds")))
    raw_rules = loaded.get("rules")
    local_rules: list[dict] = []
    if raw_rules is not None:
        if not isinstance(raw_rules, list) or not all(isinstance(r, dict) for r in raw_rules):
            problems.append(
                "quality/local/rules.yaml: `rules:` is not a list of rule mappings — it is "
                "the same shape quality/rules.yaml's `rules:` carries"
            )
        else:
            local_rules = raw_rules
    # THE DECLARATION IS WHAT MAKES THE ID GRAMMAR BIND, AND WITHOUT IT THE
    # DRAWER MINTS INTEGERS. `id_shape_problem` accepts a plain integer with no
    # `rule_id_namespace` on the tree, because on a template that is the only
    # legal shape there is — so a drawer that carries rules and no namespace
    # loads `60` as a rule of its own and every refusal ADR gate-5 exists for
    # is off. The key is not optional the moment the drawer holds a rule.
    if local_rules and not str(loaded.get("rule_id_namespace") or "").strip():
        problems.append(
            "quality/local/rules.yaml carries `rules:` and no `rule_id_namespace:` — the "
            "drawer's rules would be read under the TEMPLATE's grammar, where a plain "
            "integer is the legal shape, so the drawer could mint an id the next template "
            f"release also mints. Declare the namespace (and `template_rule_ids_through:` "
            f"beside it) — {id_grammar(None)}"
        )
    if problems:
        # A drawer with a refused key is a drawer this engine will not merge:
        # half of a declaration is the one shape that reads as a smaller rule
        # set rather than as a broken one.
        return loaded, [], problems
    return loaded, local_rules, problems


LOCAL_DOC, LOCAL_RULES, _LOCAL_PROBLEMS = _read_local()

RULES: list[dict] = [*_DOC["rules"], *LOCAL_RULES]
RULES_BY_ID: dict[str, dict] = {str(r["id"]): r for r in RULES}

#: The ids the drawer contributed. Read by the fixture-home resolver below, by
#: the `[local]` tag both readers print, and by the ratchet and plant censuses.
LOCAL_RULE_IDS: frozenset[str] = frozenset(str(r["id"]) for r in LOCAL_RULES)


def is_local_rule(rule_id: str) -> bool:
    """Did this id come out of the product's drawer?"""
    return str(rule_id) in LOCAL_RULE_IDS


#: THE DRAWER'S RATCHETS, and the key shape they are written in.
#:
#:     ratchets:
#:       "54": { acme_billing: 12, acme_portal: 3 }
#:       acme-1: { acme_billing: 1 }
#:
#: Rule id → class → count, the SAME `{class: count}` mapping a rule's own
#: `ratchets:` carries, merged into that rule at load. It exists because
#: rules 54/55/62/63 ratchet PER APP and the only apps their counts can name
#: today are the template's: a product's app has no class to stand on, so its
#: first finding is unrecordable and the pre-commit hook is unpassable on the
#: fold branch — a real adopting product met 162 findings with no class to
#: record them in. Recording them in the template's `rules.yaml` is the thing
#: EP2 exists to stop; this is their product-owned home, and the unmeasured
#: form — a class no tree has ever counted, printing the exact line to paste —
#: writes that line INTO THIS FILE rather than into the template's.
#:
#: A class here may name only an app OUTSIDE `quality/partition.yaml`'s
#: `platform_apps` (X3.4): the platform's own backlogs are the template's to
#: record, and a product that could raise one from a file the template never
#: reads would be quietly widening a template rule.
def _merge_local_ratchets() -> list[str]:
    """Fold the drawer's `ratchets:` into their rules. Shape problems, by name."""
    raw = LOCAL_DOC.get("ratchets")
    if raw is None:
        return []
    where = "quality/local/rules.yaml: `ratchets:`"
    if not isinstance(raw, dict):
        return [f"{where} is a {type(raw).__name__}, not a mapping of rule id → class → count"]
    problems: list[str] = []
    for rid, classes in raw.items():
        rid = str(rid)
        rule = RULES_BY_ID.get(rid)
        if rule is None:
            problems.append(
                f"{where} names rule {rid!r}, which is not a rule on this tree — a backlog "
                "recorded against nothing is a number nobody will ever shrink"
            )
            continue
        if not isinstance(classes, dict) or not classes:
            problems.append(
                f"{where} rule {rid}: expected a non-empty `{{<class>: <count>}}` mapping, "
                f"got {classes!r}"
            )
            continue
        recorded = dict(rule.get("ratchets") or {})
        drawer_rule = rid in LOCAL_RULE_IDS
        merged = dict(recorded)
        for klass, count in classes.items():
            name = str(klass)
            # THE REFUSAL THAT MAKES X3.4 TRUE RATHER THAN POLITE, and it is
            # HERE rather than in a later census because a census that prints a
            # note has already let the merge happen: the ceiling is raised, the
            # finding is a note, and the drawer has quietly widened a rule the
            # template owns. A refused class is NOT merged.
            #
            # TWO NAMES A DRAWER CLASS ON A TEMPLATE RULE MAY BE, and the
            # second is what D1 missed. One is an APP of the product's, which
            # is what ADR gate-6 was written for. The other is a FINDING CLASS
            # THE TEMPLATE RULE ITSELF DECLARES under its own `ratchets:` —
            # `literal`, `api-reach`, `barrel`, `consumed-undeclared` — which
            # is not an app and never will be, so the app-directory test
            # refused it with a sentence about `apps/literal/`. A product
            # folding rules 50-53 met exactly that: a backlog in a template
            # rule's own finding class, and no product-owned place to record it.
            #
            # AND THE DRAWER'S NUMBER IS ADDED TO THE TEMPLATE'S, never
            # substituted for it. The template's count is the template's
            # measurement and moves down in a template diff a reviewer reads;
            # the drawer's is the PRODUCT's backlog and moves down in the
            # product's. A substitution would let a drawer erase a template
            # ceiling from a file the template never reads, which is the one
            # move the paragraph above exists to stop. Where the template
            # records the class at 0 — the ordinary case, a class the template
            # declares and has never had a finding in — the sum IS the drawer's
            # number and the two readings coincide.
            template_declared = not drawer_rule and name in recorded
            if not drawer_rule and not template_declared:
                app_part = name.split(".", 1)[0]
                if not (ROOT / "apps" / app_part).is_dir():
                    problems.append(
                        f"{where} rule {rid} is a TEMPLATE rule and the drawer adds class "
                        f"{name!r}, whose app {app_part!r} is not a directory under apps/, "
                        f"and which is not one of the finding classes rule {rid} declares "
                        f"under its own `ratchets:` "
                        f"({', '.join(sorted(str(k) for k in recorded)) or 'none'}). "
                        "A drawer class on a template rule records one of YOUR apps' "
                        "backlogs, or YOUR count for a finding class that rule already "
                        "declares; a name that is neither records nothing and no later "
                        "run can shrink it"
                    )
                    continue
            try:
                value = int(count)
                if value < 0:
                    raise ValueError
            except (TypeError, ValueError):
                problems.append(f"{where} rule {rid}: class {name!r} is {count!r}, not a count")
                continue
            base = int(recorded[name]) if template_declared else 0
            merged[name] = base + value
            DRAWER_RATCHET_CLASSES.add((rid, name))
            DRAWER_RATCHET_PARTS[(rid, name)] = (base, value)
        rule["ratchets"] = merged
    return problems


#: `(rule id, class)` the DRAWER recorded, so every note that hands a reader a
#: number to commit names the file that number actually lives in. A product
#: told to edit `quality/rules.yaml` for a count it wrote in its own drawer is
#: sent to a template-owned file a fold overwrites — which is the whole thing
#: EP2 exists to stop, reappearing in the remedy rather than in the rule.
DRAWER_RATCHET_CLASSES: set[tuple[str, str]] = set()

#: `(rule id, class) -> (what the TEMPLATE recorded, what the DRAWER added)`.
#: The merged ceiling is their sum, and a finding printed against it has to be
#: able to say which half is whose: "past the recorded ratchet of 12" sends a
#: reader looking for a 12 that is written in neither file.
DRAWER_RATCHET_PARTS: dict[tuple[str, str], tuple[int, int]] = {}

_LOCAL_PROBLEMS.extend(_merge_local_ratchets())


def ratchet_home(rule_id: str, klass: str) -> str:
    """Which file this class's recorded number is written in."""
    if (str(rule_id), str(klass)) in DRAWER_RATCHET_CLASSES:
        return "quality/local/rules.yaml"
    return "quality/rules.yaml"


# --- the scope kinds this engine knows -------------------------------------------
#
# The languages a rule may be written about: roots, file suffixes, and the
# comment token a valve is written with. Data, like everything else here, so
# that adding one is a diff a reviewer reads rather than an edit to the walk.
def _scope_kinds() -> dict:
    """The template's kinds, then the drawer's — one mapping, template first.

    THE UNION IS THE WHOLE FIX. Every reader of kinds in this engine already
    goes through this one name: `kind_roots` (what a runner is pointed at and
    measured against), `kind_of_path` (which comment token a valve is written
    with), `_kind_walk` (where the standing override census looks), the memo's
    walk, the `--selftest-inputs` census and `rule_seam_consistency`'s
    "kind {k!r} is not one of the declared scope kinds". So a product declaring
    a kind in its drawer gets all seven, and none of them is a second list that
    can drift from this one.

    A drawer kind whose NAME the template already declares is dropped here and
    refused by `_local_scope_kind_problems` — a refused declaration is never
    merged, for the reason a refused ratchet class is not: half a declaration
    reads as a smaller engine rather than as a broken one.
    """
    kinds = dict(_DOC.get("scope_kinds") or {})
    for name, kind in (LOCAL_DOC.get("scope_kinds") or {}).items():
        if str(name) in kinds or not isinstance(kind, dict):
            continue
        kinds[str(name)] = kind
    return kinds


SCOPE_KINDS: dict = _scope_kinds()

#: The kind names the DRAWER contributed — read by the remedy below, so a
#: product that already has a kind is told to point the rule at it rather than
#: to declare a second one.
LOCAL_SCOPE_KINDS: frozenset[str] = frozenset(
    str(name) for name in (LOCAL_DOC.get("scope_kinds") or {}) if str(name) in SCOPE_KINDS
) - frozenset(str(name) for name in (_DOC.get("scope_kinds") or {}))


def drawer_roots_remedy(rule_id: str) -> str:
    """The one sentence `finding-outside-roots` owes a PRODUCT's rule.

    THE REFUSAL WAS RIGHT AND MUTE. A runner may only report about what it was
    pointed at — that law does not bend for a drawer rule — but the refusal
    named no way to point it anywhere else, and the roots it named come out of
    a template-owned file a fold overwrites. So the remedy rides on the
    refusal, and only for a rule the drawer contributed: a TEMPLATE rule
    reporting outside its roots is a broken instrument, not a missing
    declaration, and telling its author to widen the scope would be the worst
    advice in this module.
    """
    if not is_local_rule(rule_id):
        return ""
    have = f" (yours today: {', '.join(sorted(LOCAL_SCOPE_KINDS))})" if LOCAL_SCOPE_KINDS else ""
    return (
        "This is a rule from YOUR drawer, so its roots are yours to declare: add a scope "
        "kind under `scope_kinds:` in quality/local/rules.yaml — "
        '`<name>: {roots: [...], suffixes: [...], comment: "#"}` — and give the rule '
        f"`kind: <name>`{have}. A product kind's roots may name any directory or file this "
        "tree carries (docs/, quality/local/, .env.example among them); it may not reuse a "
        "kind name quality/rules.yaml already declares"
    )


# The recorded population of the SEAM's own canaries — the process boundary's
# failure modes, which no planted file can exercise because their subject is a
# runner that will not answer rather than a tree that is wrong. Same grammar as
# every other floor in this engine: below it is exit 2, above it is a note a
# human may commit.
SEAM: dict = _DOC.get("seam") or {}

# --- the world this run holds ---------------------------------------------------
#
# Read once, at import, exactly as `config/settings/base.py:117` reads it: a
# running process does not re-derive its world and neither does a gate run. Both
# are DECLARATIONS — `optional = True` on an `AppConfig`, and the deployment's
# `DJB_DISABLED_APPS` — and `quality/worlds.py` carries the whole argument for
# why neither is a list in this file.
OPTIONAL_APPS: frozenset[str] = W.optional_app_labels(ROOT)
DISABLED_APPS: frozenset[str] = W.disabled_app_labels()


def _read_platform_apps() -> tuple[frozenset[str] | None, str | None]:
    """The partition's app list, or why this run could not read it (ADR gate-6).

    READ, NEVER DERIVED, and read from the one file that owns it —
    `quality/partition.yaml`'s `platform_apps`, through the module that already
    parses it. It is what tells an app the TEMPLATE ships from an app a PRODUCT
    added, which is the whole of the unmeasured-ratchet question below.

    UNREADABLE IS NOT EMPTY. An empty set would make every app on the tree
    "outside the partition" and turn every app-keyed ratchet class into an
    unmeasured finding — a refusal storm caused by a missing lockfile rather
    than by anything a reader wrote. So a failure returns None, the unmeasured
    branch stays shut, and `consistency()` says so as exit 2.
    """
    try:
        return frozenset(PART.platform_apps()), None
    except Exception as error:  # a broken or absent lockfile: named, never guessed around
        return None, (
            "the partition lockfile could not be read, so the engine cannot tell a template "
            "app from a product's and the UNMEASURED ratchet branch (ADR gate-6) is shut for "
            f"this run: {error}"
        )


PLATFORM_APPS, _PARTITION_PROBLEM = _read_platform_apps()

# THE SELF-TEST'S OWN BACKLOG, and the only thing standing between "a rule that
# an environment variable can delete" and exit 2. Measured over the whole rule
# set; the members are printed by name on every self-test run. Same grammar as
# `ratchets:` (see this module's header): it may shrink and never grow, one over
# it turns the whole census into violations, and a human commits the lower
# number in a diff somebody reads. Nothing tightens by itself.
RESIDENCE_BACKLOG: int = int(_DOC.get("selftest_residence_backlog") or 0)
CANARY_DIR = ROOT / "quality" / "canary"
NEGATIVE_DIR = ROOT / "quality" / "negative"


def fixture_home(kind: str, rule_id: str) -> Path:
    """Where THIS rule's fixtures of this kind live. `kind` is canary|negative.

    ONE RESOLVER, read by every site that used to spell `CANARY_DIR / rid`. A
    template rule's fixtures are under `quality/{canary,negative}/<id>/` and a
    drawer rule's under `quality/local/{canary,negative}/<id>/` — the SAME
    protocol, the same plan entries, the same self-test, a different tree. A
    second spelling anywhere is how a drawer rule's canary ends up planted from
    a directory nothing censuses.
    """
    base = CANARY_DIR if kind.startswith("canar") else NEGATIVE_DIR
    if is_local_rule(rule_id):
        base = LOCAL_CANARY_DIR if kind.startswith("canar") else LOCAL_NEGATIVE_DIR
    return base / str(rule_id)


def fixture_bases(rule_id: str) -> tuple[tuple[str, Path], ...]:
    """`(("canaries", <its canary tree>), ("negatives", <its negative tree>))`."""
    if is_local_rule(rule_id):
        return (("canaries", LOCAL_CANARY_DIR), ("negatives", LOCAL_NEGATIVE_DIR))
    return (("canaries", CANARY_DIR), ("negatives", NEGATIVE_DIR))


def fixture_trees() -> tuple[tuple[str, Path], ...]:
    """Every fixture tree on this checkout, template's first, drawer's after.

    The drawer's two appear only when the drawer has them, so a tree with no
    `quality/local/` walks exactly the two directories it always walked and
    every census prints the number it printed before EP2.
    """
    trees: list[tuple[str, Path]] = [("canary", CANARY_DIR), ("negative", NEGATIVE_DIR)]
    for kind, base in (("canary", LOCAL_CANARY_DIR), ("negative", LOCAL_NEGATIVE_DIR)):
        if base.is_dir():
            trees.append((kind, base))
    return tuple(trees)


#: THE FIXTURES THE ENGINE ITSELF PLANTS, declared once and read twice.
#:
#: Almost every fixture under the two trees is named by an entry in
#: `quality/rules.yaml`, and the orphan census below reads that plan to decide
#: whether a file has a claimant. A handful are planted by a leg of this module
#: BY PATH instead, because their subject is the engine's own walk rather than
#: any rule's scope — and a path typed inside a function body is a claim the
#: census cannot see. The census read this and the planter reads it too, so a
#: file listed here is claimed exactly once, and deleting the entry without the
#: file (or the file without the entry) is exit 2 rather than a traceback.
#:
#: The reason string is printed by the census when the file is missing, so it
#: has to say which leg would stop working.
VENDORED_VALVE_FIXTURE = NEGATIVE_DIR / "50" / "vendored_valve.js"

ENGINE_FIXTURES: dict[Path, str] = {
    VENDORED_VALVE_FIXTURE: (
        "seam_skip_dir_census plants it inside frontend/node_modules/ to prove a valve in a "
        "vendored directory stays out of the standing override census (F1, Vra 2026-08-31)"
    ),
}
BUDGETS_PATH = ROOT / "quality" / "budgets.yaml"

# --- TWO NAMESPACES FOR RULE IDS (ADR gate-5) -----------------------------------
#
# THE SUBJECT. Rule ids were ONE integer sequence that the template and a
# product both appended to. A product that minted `54` met the template's own
# `54` at the next fold: the ids merged into a duplicate (exit 2, and the only
# thing that ever caught it), and `quality/canary/54/` merged SILENTLY into one
# directory holding both plans. The repair was renumbering the product's rules
# by hand, every release.
#
# THE GRAMMAR. Only the template mints integers. A product declares
# `rule_id_namespace: <ns>` ONCE, top-level in `quality/local/rules.yaml` — the
# product's DRAWER, which no fold overwrites (P21 EP2) — and every
# rule it writes is `<ns>-<n>` — in the id, in the fixture directory
# (`quality/local/{canary,negative}/<ns>-<n>/` — the DRAWER, which is what
# `fixture_home` below resolves for a namespaced id, and not the template's own
# `quality/{canary,negative}/<n>/`), in the valve (`# rule-<ns>-<n>:`) and
# in the check tag (`<ns>.Wnnn`, where the template's are `djb.…`). Two
# namespaces cannot collide, so a fold has nothing to merge.
#
# WHY A SECOND KEY, AND WHY IT IS A NUMBER. A shape wall alone cannot refuse a
# product that types `60`: an integer is a legal shape and the engine has no
# other way to know the template did not mint it. `template_rule_ids_through`
# is that record — the highest integer the TEMPLATE release this tree folded had
# minted — and it is exactly `partition.yaml`'s and `FROZEN_FAMILIES`' pattern:
# a record of the past, written down, in a diff a human reads. The template
# never carries it (its own ids are, by definition, all it has minted), so a
# rung adding a template rule pays nothing; a product carries it and moves it at
# a fold, and forgetting to is a NAMED refusal handing over the line to paste,
# never a silent pass.
#
# WHERE THEY LIVE (P21 EP2, the key-home move). Both keys are read from
# `quality/local/rules.yaml` and refused in `quality/rules.yaml`. D1 shipped
# them in the template-owned file because the drawer did not exist yet, and a
# declaration in a file a fold overwrites is a declaration that disappears at
# the next release — which is the same failure the namespace itself exists to
# end, one file up.

#: WHERE THE GRAMMAR IS WRITTEN UP, cited by the CHANGELOG's own ENTRY and not
#: by the release heading above it. `[Unreleased]` is RENAMED to a version
#: number at every release, so a refusal that cites the heading sends the next
#: reader to a section that no longer exists — and the readers of these lines
#: are on a product tree, holding a fold, with no way to know the heading moved.
#: The entry's title does not move.
GATE5_CITE = 'ADR gate-5, CHANGELOG § "Rule ids are two namespaces"'

NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TEMPLATE_ID_RE = re.compile(r"^\d+$")

#: The template's own check-tag prefix. A product's is its namespace.
TEMPLATE_CHECK_PREFIX = "djb"


def _read_namespace() -> tuple[str | None, int | None, list[str]]:
    """(namespace, the template high-water, problems) off the two top-level keys.

    THE HOME IS THE DRAWER. Both keys are read from `quality/local/rules.yaml`
    and from nowhere else: they are a PRODUCT's declaration, and the
    template-owned `quality/rules.yaml` is a file a fold overwrites. A tree
    that still carries either of them there is refused by `_read_local` with
    the line that names the move.

    Read at import because the valve grammar below is compiled from it, and
    reported through `consistency()` rather than raised: a malformed
    declaration must reach a reader as a named exit 2, not as a traceback that
    takes the four readers (`--explain`, the listing, `--selftest-inputs`,
    `--fold-map`) down with it.
    """
    problems: list[str] = []
    raw_ns = LOCAL_DOC.get("rule_id_namespace")
    raw_through = LOCAL_DOC.get("template_rule_ids_through")
    ns: str | None = None
    if raw_ns is not None:
        candidate = str(raw_ns).strip()
        if not NAMESPACE_RE.match(candidate):
            problems.append(
                f"rule_id_namespace: {raw_ns!r} is not a namespace — it is one lowercase word "
                "matching [a-z][a-z0-9_]*, because it is spelled in a rule id, a directory "
                "name, a valve marker and a check tag (ADR gate-5)"
            )
        elif candidate == TEMPLATE_CHECK_PREFIX:
            problems.append(
                f"rule_id_namespace: {TEMPLATE_CHECK_PREFIX!r} is the TEMPLATE's namespace — a "
                "product that claimed it would be back where the collision started. Pick your "
                "own word"
            )
        else:
            ns = candidate
    through: int | None = None
    if ns is None:
        if raw_through is not None:
            problems.append(
                "template_rule_ids_through is declared with no `rule_id_namespace` — it is a "
                "PRODUCT's record of the template release it folded, and a template has no use "
                "for it (its integers are all it has minted). Remove it, or declare the "
                "namespace it belongs to"
            )
    else:
        try:
            through = int(raw_through)  # type: ignore[arg-type]
            if through < 0:
                raise ValueError
        except (TypeError, ValueError):
            problems.append(
                f"rule_id_namespace: {ns!r} is declared without a usable "
                f"`template_rule_ids_through:` ({raw_through!r}). Record the highest integer "
                "rule id the template release you folded had minted — the engine cannot "
                "otherwise tell a template rule from a product rule that typed an integer"
            )
    return ns, through, problems


RULE_ID_NAMESPACE, TEMPLATE_IDS_THROUGH, _NAMESPACE_PROBLEMS = _read_namespace()


def product_id_re(namespace: str) -> re.Pattern[str]:
    """`<ns>-<n>` — the one shape a product's rule ids may take."""
    return re.compile(rf"^{re.escape(namespace)}-\d+$")


def is_template_id(rule_id: str) -> bool:
    """A plain integer: an id the TEMPLATE minted."""
    return bool(TEMPLATE_ID_RE.match(str(rule_id)))


def id_grammar(namespace: str | None = ...) -> str:  # type: ignore[assignment]
    """The one sentence every refusal about an id shape ends with.

    `namespace` defaults to THIS tree's declaration; a caller that was handed
    one (the fixture-directory census, which a canary drives against a tree it
    built) passes it, so the sentence and the census can never be about two
    different trees.
    """
    if namespace is ...:
        namespace = RULE_ID_NAMESPACE
    if namespace is None:
        return (
            "template rule ids are integers; a product declares `rule_id_namespace: <ns>` "
            "once, top-level in quality/local/rules.yaml — the product's drawer — and "
            "names its own rules `<ns>-<n>` "
            f"({GATE5_CITE})"
        )
    return (
        f"product rule ids are {namespace}-<n> — in the id, the fixture directory, "
        f"the valve (`# rule-{namespace}-<n>:`) and the check tag "
        f"(`{namespace}.Wnnn`); the integers are the template's to mint "
        f"({GATE5_CITE})"
    )


def id_shape_problem(rule_id: str) -> str | None:
    """Why this id is not a legal rule id on this tree, or None."""
    rid = str(rule_id)
    if is_template_id(rid):
        if RULE_ID_NAMESPACE is None or TEMPLATE_IDS_THROUGH is None:
            return None
        if int(rid) <= TEMPLATE_IDS_THROUGH:
            return None
        return (
            f"rule {rid}: an integer id above the template release this tree folded "
            f"(`template_rule_ids_through: {TEMPLATE_IDS_THROUGH}`) — {id_grammar()}. If {rid} "
            f"ARRIVED in a template fold, record the new high-water: "
            f"`template_rule_ids_through: {rid}`"
        )
    if RULE_ID_NAMESPACE is not None and product_id_re(RULE_ID_NAMESPACE).match(rid):
        return None
    return f"rule {rid}: not a legal rule id here — {id_grammar()}"


def check_tag_prefix(rule_id: str) -> str:
    """`djb` for a template rule, the namespace for a product's."""
    if is_template_id(rule_id) or RULE_ID_NAMESPACE is None:
        return TEMPLATE_CHECK_PREFIX
    return RULE_ID_NAMESPACE


#: The valve's id half, as ONE string both patterns below are built from. A
#: template tree accepts `rule-<n>` and nothing else; a product tree accepts its
#: own `rule-<ns>-<n>` beside it. Built from the declaration rather than a
#: permissive `[a-z0-9_-]+` so that a valve naming a namespace this tree never
#: claimed is an unmatched marker a reader can see, not a suppression that
#: quietly works.
def _valve_id_pattern() -> str:
    if RULE_ID_NAMESPACE is None:
        return r"\d+"
    return rf"(?:{re.escape(RULE_ID_NAMESPACE)}-)?\d+"


PROBE_APP = "zzz_canary"
PROBE_DIR = ROOT / "apps" / PROBE_APP
PROBE_APPS_PY = f"""from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.{PROBE_APP}"
    depends_on: tuple[str, ...] = ("core", "accounts")
"""

OVERRIDE_RE = re.compile(rf"#\s*rule-({_valve_id_pattern()})\b:?\s*(.*)$")
MIN_REASON = 12  # long enough to force a clause; short enough that a real reason clears it

#: F3 (Vra, 2026-08-31): the sentinel `run_rule`'s third return element carries when a
#: rule COULD NOT LOOK (tree present, toolchain absent; or a live runner
#: refused) rather than ran clean or was legally skipped. Before this existed
#: both shapes returned `""`, so a refused rule's own per-rule line printed
#: `ok` — the true reason sat only in the `broken` section further down, which
#: prints AFTER the per-rule table a reader checks first.
COULD_NOT_LOOK = "COULD-NOT-LOOK — "

#: One compiled valve pattern per comment token. The marker's grammar — the id,
#: the optional colon, the reason — is one string with the token substituted in,
#: so a second language gets the SAME valve, including the same reason floor,
#: rather than a second dialect somebody has to keep in step. Cached because the
#: override walk asks per line.
_OVERRIDE_RES: dict[str, re.Pattern[str]] = {"#": OVERRIDE_RE}


def override_re(comment: str) -> re.Pattern[str]:
    """The `<comment> rule-<id>: <reason>` pattern for one comment syntax."""
    cached = _OVERRIDE_RES.get(comment)
    if cached is None:
        cached = re.compile(re.escape(comment) + rf"\s*rule-({_valve_id_pattern()})\b:?\s*(.*)$")
        _OVERRIDE_RES[comment] = cached
    return cached


broken: list[str] = []
violations: list[str] = []
notes: list[str] = []

#: Which rule each violation line belongs to, RECORDED where the line is
#: appended rather than parsed back out of its text. The trailer below is
#: printed per rule, so the grouping has to be a fact the appender stated; a
#: regex over `rule (\d+):` would be a second, weaker answer to a question the
#: caller already knew. A violation with no entry here is a BUDGET — the one
#: finding class that has no rule id at all (`check_budgets`).
violation_rule: dict[str, str] = {}

#: Per rule id, the comment tokens the files it reported in are written with.
#: The valve a reader is handed has to be paste-able WHERE THE FINDING LIVES
#: (F2, Vra, 2026-08-31): a `.ts` file's own reader must not be told to write
#: `#`. A rule whose findings span two languages therefore prints its marker
#: once per kind present, never once per rule.
finding_kinds: dict[str, set[str]] = {}


def say(msg: str) -> None:
    print(msg)


# --- overrides -----------------------------------------------------------------


def _file_lines(path: Path) -> list[str]:
    try:
        return path.read_text().splitlines()
    except (OSError, UnicodeDecodeError):
        return []


def override_at(path: Path, line: int, rule_id: str) -> str | None:
    """The reason claimed for rule_id at this line, or None when none is claimed.

    The marker counts on the flagged line itself, or in the CONTIGUOUS comment
    block directly above it — never further away, so an exemption cannot drift
    onto code nobody thought about.

    The comment syntax comes from the FILE, through the scope kinds: a valve in
    a `.ts` file is `// rule-<id>: <reason>` and a valve in a `.py` file is the
    `#` form, and both are the same mechanism with the same reason floor rather
    than two grammars a reader has to learn.
    """
    lines = _file_lines(path)
    if not lines or line < 1 or line > len(lines):
        return None
    try:
        rel = str(path.relative_to(ROOT))
    except ValueError:
        rel = str(path)
    comment = W.comment_token(W.kind_of_path(rel, SCOPE_KINDS))
    pattern = override_re(comment)
    m = pattern.search(lines[line - 1])
    if m and m.group(1) == rule_id:
        return m.group(2).strip()
    i = line - 2
    while i >= 0 and lines[i].strip().startswith(comment):
        m = pattern.search(lines[i])
        if m and m.group(1) == rule_id:
            return m.group(2).strip()
        i -= 1
    return None


def _kind_walk() -> list[tuple[str, str, frozenset[str]]]:
    """(root, suffix, skip_dirs) for every place a valve may be written, from the kinds.

    Derived rather than typed so that the census and the suppression cannot
    disagree about where a valve counts: the day a kind declares a root, both
    halves see it. A kind whose roots are not on this checkout contributes
    nothing and says nothing — a frontend-less template has no frontend valves,
    which is a fact rather than a skip.

    `skip_dirs` rides the same tuple for the identical reason: a vendored
    directory (`node_modules`, `.next`, …) must not enter this walk any more
    than it enters a rule's own live scan, and the declaration is `kind_skip_dirs`'s
    — one set, read here and by every runner under `quality/runners/`.
    """
    walk: list[tuple[str, str, frozenset[str]]] = []
    for kind in SCOPE_KINDS.values():
        skip = W.kind_skip_dirs(kind)
        for root in kind.get("roots") or []:
            for suffix in kind.get("suffixes") or []:
                walk.append((str(root), str(suffix), skip))
    return walk


def override_reaches(rule_id: str, rel: str) -> bool:
    """Can the rule this marker names report about this path at all?

    THE WALK IS THE UNION AND A VALVE IS NOT. `_kind_walk()` reads every scope
    kind on the tree — the template's two and any the drawer declares — because
    a valve has to be FINDABLE wherever one can be written. But a valve is an
    exemption FROM ONE RULE, and a rule's subject is its own kind's roots. So a
    product kind rooted at `docs/` with `comment: "#"` made every `# rule-13:`
    shaped line in this repository's prose an override of TEMPLATE rule 13 —
    standing overrides went 41 to 56, and two lines of documentation whose
    "reason" was shorter than `MIN_REASON` became findings recorded against
    rules 13 and 16. A product kind turned a green tree red on rules it does
    not own (V-HD1, HIGH-2, 2026-09-22).

    AN ID NO RULE CLAIMS IS KEPT, never dropped: `rule-99` in a source file is
    somebody's mistake and some other census's finding, and a reach test that
    silently swallowed it would be this fix causing the next one.
    """
    rule = RULES_BY_ID.get(str(rule_id))
    if rule is None:
        return True
    roots = W.kind_roots(rule, SCOPE_KINDS)
    if not roots:
        return True
    for root in roots:
        base = str(root).rstrip("/")
        if rel == base or rel.startswith(base + "/"):
            return True
    return False


def all_overrides() -> list[tuple[str, str, int, str]]:
    """(rule_id, relpath, line, reason) for every override marker in the tree.

    The walk is every kind's; the ATTRIBUTION is one rule's — see
    `override_reaches` for the difference and what it cost to learn.
    """
    found: list[tuple[str, str, int, str]] = []
    seen: set[tuple[str, int]] = set()
    for sub, suffix, skip in _kind_walk():
        base = ROOT / sub
        if not base.exists():
            continue
        # A ROOT MAY BE A FILE. A template kind's roots are all directories, so
        # this branch is dead on a tree with no drawer — but a product kind may
        # name `.env.example`, and a valve written in a file root has to be
        # findable by the same census that finds one in a directory root, or it
        # is an exemption nobody counts.
        if base.is_file():
            candidates = [base] if base.name.endswith(suffix) else []
        else:
            candidates = sorted(base.rglob(f"*{suffix}"))
        for path in candidates:
            if skip & set(path.parts):
                continue
            rel = str(path.relative_to(ROOT))
            pattern = override_re(W.comment_token(W.kind_of_path(rel, SCOPE_KINDS)))
            for lineno, text in enumerate(_file_lines(path), start=1):
                m = pattern.search(text)
                if m and (rel, lineno) not in seen:
                    if not override_reaches(m.group(1), rel):
                        continue
                    seen.add((rel, lineno))
                    found.append((m.group(1), rel, lineno, m.group(2).strip()))
    return sorted(found, key=lambda row: (row[1], row[2]))


def apply_overrides(rule_id: str, findings: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """(kept, suppressed). A bare override becomes its own finding, kept."""
    kept: list[Finding] = []
    suppressed: list[Finding] = []
    for finding in findings:
        reason = override_at(ROOT / finding.path, finding.line, rule_id)
        if reason is None:
            kept.append(finding)
        elif len(reason) >= MIN_REASON:
            suppressed.append(finding)
        else:
            marker = W.comment_token(W.kind_of_path(finding.path, SCOPE_KINDS))
            kept.append(
                Finding(
                    finding.path,
                    finding.line,
                    f"override `{marker} rule-{rule_id}` with no reason — an escape hatch "
                    f"nobody has to justify is an off switch (suppressing: {finding.msg})",
                )
            )
    return kept, suppressed


#: The sha the recording line is stamped with, read once per process. A
#: recording says WHEN a count was true, and the only honest answer is the tree
#: the count was measured on.
_RECORDING_SHA: str | None = None


def recording_sha() -> str:
    """This checkout's HEAD, short — the stamp on a `recorded-at` line.

    A literal `<sha>` when git cannot answer (an exported tree, a tarball): the
    line is still the line to paste, and a reader who has no git has no sha to
    put in it either.
    """
    global _RECORDING_SHA
    if _RECORDING_SHA is None:
        _RECORDING_SHA = "<sha>"
        try:
            done = subprocess.run(
                ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            if done.returncode == 0 and done.stdout.strip():
                _RECORDING_SHA = done.stdout.strip()
        except Exception:  # no git, no repository, no answer — the literal stands
            pass
    return _RECORDING_SHA


def unmeasured_app(klass: str, findings: list[Finding]) -> str | None:
    """The PRODUCT app this ratchet class belongs to, or None (ADR gate-6).

    THE SUBJECT. Per-app ratchet classes are keyed `<app>` or `<app>.<what>`,
    and every recorded one names an app the TEMPLATE ships. A product's own app
    has no entry, and an absent entry is a ratchet of zero — which is the right
    answer for a template app (a clean class stays clean by absence) and an
    unreadable one for a product's (nothing anywhere says the class exists, what
    the grammar is, or that recording it is allowed at all).

    THE APP IS CONFIRMED BY THE FINDINGS, never inferred from the key alone.
    `nonconforming` and `secrets` are class names, not app names, and a
    predicate that read the key on its own would offer to record an app that
    does not exist. So a class is app-keyed only when EVERY finding in it sits
    under `apps/<label>/` for the label the key opens with — fail closed, and no
    stat of the tree is needed to decide it.

    Three ways this answers None, all deliberate: an app INSIDE the partition
    (the template's own — absence is the measurement), the plant scaffold
    (`apps/zzz_canary` exists only between `Plant.put` and `Plant.restore`, and
    a recording for it would name an app nobody can open), and a run that could
    not read the partition at all (`_read_platform_apps`).
    """
    if PLATFORM_APPS is None:
        return None
    label = str(klass).split(".", 1)[0].strip()
    if not label or label == PROBE_APP or label in PLATFORM_APPS:
        return None
    prefix = f"apps/{label}/"
    if not findings:
        return None
    if not all(str(finding.path).replace("\\", "/").startswith(prefix) for finding in findings):
        return None
    return label


def unmeasured_line(rid: str, klass: str, app: str, count: int) -> str:
    """The finding an unmeasured class prints — and it IS the line to paste.

    Everything a reader needs is here because everything a reader needs is
    knowable here: which class, which app, why the engine calls it a product's,
    the exact text to record, the stamp that says when it was true, and the one
    direction the number may move afterwards.
    """
    return (
        f"class {klass!r} has NEVER BEEN MEASURED — apps/{app} is outside the partition "
        f"(quality/partition.yaml `platform_apps`), so it is an app this template did not "
        f"ship, and no `ratchets:` entry on rule {rid} names this class. An absent entry is "
        f"a ceiling of zero, which is the right answer for a template app and an unreadable "
        f"one for yours: green-because-unrecorded is not a pass (quality/budgets.yaml), so "
        f"this is a violation and not a note. RECORD IT — in quality/local/rules.yaml, YOUR "
        f'drawer, under its top-level `ratchets:`, under `"{rid}":`, paste:  '
        f"{klass}: {count}  # recorded-at {recording_sha()} [fold]  — the drawer is where a "
        f"product's counts live, because quality/rules.yaml is template-owned and a fold "
        f"overwrites it (P21 EP2); the recording is the "
        f"ONE time a number here may arrive from nothing, it belongs to the fold that "
        f"brought the app in, and after it the class moves DOWN only, by a person's hand, "
        f"in a diff a reviewer reads (ADR gate-6). The whole class follows:"
    )


def drawer_ratchetable_class(rule_id: str, klass: str, rule: dict) -> bool:
    """May a PRODUCT record its own count for this class, in its own drawer?

    The mirror of the acceptance branch in `_merge_local_ratchets`, and it has
    to be a predicate rather than a comment because a finding that cannot say
    "you may record this" leaves the product to reverse-engineer the grammar —
    which is the whole of ADR gate-6's context, reappearing one class-kind
    over. True for a TEMPLATE rule's own FINDING class: one the rule declares
    under its `ratchets:` whose name is not an app on this tree (an app-keyed
    class takes `unmeasured_app`'s route, and a PLATFORM app's ceiling is the
    template's under X3.4).
    """
    if is_local_rule(rule_id):
        return False
    if str(klass) not in {str(k) for k in (rule.get("ratchets") or {})}:
        return False
    return not (ROOT / "apps" / str(klass).split(".", 1)[0]).is_dir()


def finding_class_line(rid: str, klass: str, recorded: int, count: int) -> str:
    """The `recorded-at` paste line for a template rule's own finding class.

    `unmeasured_line`'s sibling, and the reason it exists: `unmeasured_app`
    answers None for a class that is not app-keyed, so `literal` — rule 50's
    own class, the one a product folding v2.1.2 actually had a backlog in —
    printed no paste line at all and the product typed its number by hand.
    """
    mine = max(0, count - recorded)
    return (
        f"class {klass!r} is at {count} violations against rule {rid}'s own recorded ceiling "
        f"of {recorded} — this is a TEMPLATE rule's FINDING class, not an app: the template "
        f"measured its own tree at {recorded} and yours is the backlog on top of it. RECORD "
        f"YOURS — in quality/local/rules.yaml, YOUR drawer, under its top-level `ratchets:`, "
        f'under `"{rid}":`, paste:  {klass}: {mine}  # recorded-at {recording_sha()} [fold]'
        f"  — the drawer's number is ADDED to the template's {recorded} and never replaces "
        f"it, so the template's measurement stays the template's to move; the recording "
        f"belongs to the fold that brought your code in, and after it the class moves DOWN "
        f"only, by a person's hand, in a diff a reviewer reads (ADR gate-6). The whole class "
        f"follows:"
    )


def apply_ratchets(rule: dict, kept: list[Finding]) -> list[Finding]:
    """Findings within a recorded backlog are notes; one over it, all of them fail.

    Counted per CLASS (`Finding.klass`), so a backlog of nine badly named
    selectors cannot pay for one badly named model. A class with no recorded
    ratchet is ratcheted at zero — the ordinary case, where the first finding
    is a violation.

    AND WHEN THE CLASS IS A PRODUCT APP'S, the zero says so out loud (ADR
    gate-6). An app outside `quality/partition.yaml`'s partition with no entry
    on this rule is UNMEASURED rather than clean: the findings still fail,
    exactly as before, and the header they arrive under is the `ratchets:` line
    to paste, stamped with the sha it was true at. See `unmeasured_app` for
    which classes qualify and `unmeasured_line` for what the header says.
    """
    rid = str(rule["id"])
    recorded = rule.get("ratchets") or {}
    #: The class names this rule has WRITTEN DOWN, whatever their value. A
    #: recorded 0 is a measurement; an absent key is the thing ADR gate-6 is
    #: about, and `recorded.get(klass, 0)` cannot tell the two apart.
    named = {str(key) for key in recorded}
    by_class: dict[str, list[Finding]] = {}
    for finding in kept:
        by_class.setdefault(finding.klass, []).append(finding)
    out: list[Finding] = []
    for klass, findings in sorted(by_class.items()):
        allowed = int(recorded.get(klass, 0)) if klass else 0
        label = klass or "(rule)"
        if len(findings) > allowed:
            parts = DRAWER_RATCHET_PARTS.get((rid, str(klass)))
            # THE FINDING IS HOMED WHERE THE NUMBER IS WRITTEN, and it says
            # which half of a summed ceiling is whose — "past the recorded
            # ratchet of 12" sends a reader looking for a 12 that is written in
            # neither file once the template's own count is non-zero.
            home = ratchet_home(rid, str(klass)) if klass else "quality/rules.yaml"
            split = f" (template {parts[0]} + drawer {parts[1]})" if parts else ""
            if allowed:
                out.append(
                    Finding(
                        home,
                        0,
                        f"class {label!r} is at {len(findings)} violations, past the recorded "
                        f"ratchet of {allowed}{split} — a backlog may shrink and never grow. "
                        f"Fix the new one, or reduce another; raising the number is a diff a "
                        f"reviewer reads, in {home}. The whole class follows:",
                        klass,
                    )
                )
            elif klass and drawer_ratchetable_class(rid, str(klass), rule):
                # A TEMPLATE RULE'S OWN FINDING CLASS, recorded at 0 and now
                # over it. `unmeasured_app` answers None here — the class names
                # no app and never will — so before this branch the product got
                # the findings and no line to paste anywhere.
                out.append(
                    Finding(
                        "quality/local/rules.yaml",
                        0,
                        finding_class_line(rid, str(klass), allowed, len(findings)),
                        klass,
                    )
                )
            elif klass and str(klass) not in named:
                # UNMEASURED, not zero (ADR gate-6). The verdict is the same
                # exit 1 it already was — what changes is that the header now
                # says the class exists, why it has no ceiling, and the exact
                # line that gives it one. A class the product HAS recorded at
                # zero is measured and takes the ordinary path above.
                app = unmeasured_app(str(klass), findings)
                if app is not None:
                    out.append(
                        Finding(
                            "quality/rules.yaml",
                            0,
                            unmeasured_line(rid, str(klass), app, len(findings)),
                            klass,
                        )
                    )
            out.extend(findings)
        else:
            notes.append(
                f"rule {rid} ratchet: class {label} at {len(findings)} of the recorded "
                f"{allowed} — standing backlog, not a pass; nothing new landed."
            )
            for finding in findings:
                notes.append(f"    backlog {finding}")
            if len(findings) < allowed:
                notes.append(
                    f"    rule {rid}: class {label} is now BELOW its ratchet of {allowed} — "
                    f"a human may commit {len(findings)} to {ratchet_home(rid, label)}; "
                    "nothing tightens by itself."
                )
    for klass, allowed in sorted(recorded.items()):
        # A class that has gone all the way to clean is the one worth saying
        # out loud, and it is the one no finding would mention.
        if str(klass) not in by_class and int(allowed) > 0:
            notes.append(
                f"rule {rid} ratchet: class {klass} has NO violations left against a "
                f"recorded {allowed} — a human may commit 0 to "
                f"{ratchet_home(rid, str(klass))}."
            )
    return out


# --- running one rule ----------------------------------------------------------


def local_runner_argv(impl: str) -> list[str] | None:
    """`check: <name>` as a check-v1 runner in the drawer, or None.

    THE SECOND HALF OF ONE RESOLVER (X3.3). `check:` has always named an entry
    in `quality.checks.REGISTRY`, and a product may not edit `checks.py` — it
    is template-owned, and a product's check in it is a conflict in the one
    file whose conflicts are worst. So a name the registry does not hold is
    looked for ONCE more, as `quality/local/runners/<name>.py`, and invoked
    across the check-v1 process boundary exactly as a `runner:` rule is: the
    runner MEASURES, this engine JUDGES, and a runner that cannot be believed
    is exit 2 rather than zero findings.

    Neither a registry name nor a file here is a refusal that names both
    places it looked — `resolve_check_problem` below is that sentence, and it
    is the ONLY place either reader decides a `check:` is unresolvable.
    """
    path = LOCAL_RUNNER_DIR / f"{impl}.py"
    if not path.is_file():
        return None
    # Checkout-relative when it is inside the checkout — which is the only
    # place a real drawer sits, and what makes the refusal messages readable —
    # and absolute otherwise, so a probe that points `LOCAL_RUNNER_DIR` at a
    # tempdir it built gets an answer rather than a traceback.
    try:
        where = str(path.relative_to(ROOT))
    except ValueError:
        where = str(path)
    return ["python3", where]


def resolve_check_problem(rule_id: str, impl: str) -> str | None:
    """Why this `check:` resolves to nothing on this tree, or None."""
    if impl in REGISTRY:
        return None
    if local_runner_argv(impl) is not None:
        return None
    return (
        f"rule {rule_id}: check impl {impl!r} resolves to nothing — it is not a name in "
        f"quality/checks.py's REGISTRY and there is no check-v1 runner at "
        f"quality/local/runners/{impl}.py. A product never edits checks.py (it is "
        "template-owned and a fold overwrites it): write the runner in the drawer, or "
        "re-scope a registry check the template already ships"
    )


def run_runner(rule: dict) -> CheckResult:
    """A `runner:` rule's external instrument, through the check-v1 protocol.

    THE SEAM, AND THE ONE SENTENCE IT IS BUILT AROUND: the runner measures and
    this engine judges. What comes back is a CheckResult and nothing else — no
    verdict, no severity, no suppression — so a `runner:` rule rejoins the
    pipeline below at exactly the point an in-process `check:` rule does, and
    every semantic after that line is the same code for both. A refusal is
    raised rather than returned: could-not-look must not be able to arrive here
    wearing an empty findings list.
    """
    runner = rule.get("runner") or {}
    argv = [str(a) for a in (runner.get("argv") or [])]
    return check_v1.invoke(
        ROOT,
        argv=argv,
        roots=W.kind_roots(rule, SCOPE_KINDS),
        where=f"rule {rule['id']} runner {' '.join(argv)!r}",
        timeout=int(runner.get("timeout") or check_v1.DEFAULT_TIMEOUT),
        remedy=drawer_roots_remedy(str(rule["id"])),
    )


def run_rule(rule: dict, *, floors: bool = True) -> tuple[list[Finding], dict, str]:
    """The rule's check + override + ratchet pipeline. (violations, targets, skip).

    `skip` is empty for a rule that ran; a SKIPPED sentence for a rule about a
    tree this checkout does not have; and a `COULD_NOT_LOOK`-prefixed sentence
    (F3, Vra, 2026-08-31) for a rule that could not be run at all — its tree present
    with no toolchain, or a live runner this engine refused to believe. The
    three are returned rather than printed here because this function runs
    inside the self-test as well, where the plant has just made the tree exist
    and there is nothing to announce; the caller that DOES print (`live_scan`)
    is what turns the prefix into a status distinct from `ok`, so a refused
    rule's own line cannot read as a rule that ran clean.
    """
    rid = str(rule["id"])
    targets: dict = {}
    findings: list[Finding] = []
    verdict, why = W.tree_verdict(ROOT, rule, SCOPE_KINDS)
    if verdict == "broken":
        broken.append(f"rule {rid}: {why}")
        return [], targets, COULD_NOT_LOOK + why
    absent = verdict == "skip"
    impl = rule.get("check")
    if impl and not absent:
        unresolved = resolve_check_problem(rid, impl)
        if unresolved:
            broken.append(unresolved)
            return [], targets, COULD_NOT_LOOK + unresolved
        if impl in REGISTRY:
            # THE ONE CONSULT. `memo_consult` either replays this rule's last
            # answer for a key nothing has moved, or calls the check and banks
            # it — and everything below this line runs either way, so no memo
            # can hide an unbound floor, a ratchet that grew or a valve that
            # lost its reason. See THE PER-RULE MEMO, below.
            result: CheckResult = memo_consult(rule, impl)
        else:
            # THE DRAWER'S RUNNER, across the same process boundary a
            # `runner:` rule crosses, and refused the same way: a runner that
            # will not answer is could-not-look, never zero findings.
            argv = local_runner_argv(str(impl)) or []
            try:
                result = check_v1.invoke(
                    ROOT,
                    argv=argv,
                    roots=W.kind_roots(rule, SCOPE_KINDS),
                    where=f"rule {rid} local runner {' '.join(argv)!r}",
                    remedy=drawer_roots_remedy(rid),
                    timeout=int(
                        (rule.get("runner") or {}).get("timeout") or check_v1.DEFAULT_TIMEOUT
                    ),
                )
            except check_v1.RunnerRefused as exc:
                broken.append(f"rule {rid}: LOCAL RUNNER REFUSED ({exc.klass}) — {exc.detail}")
                return [], targets, COULD_NOT_LOOK + f"({exc.klass}) {exc.detail}"
        targets.update(result.targets_matched)
        findings.extend(result.findings)
    if rule.get("runner") and not absent:
        try:
            reply = run_runner(rule)
        except check_v1.RunnerRefused as exc:
            # COULD NOT LOOK, and it outranks a pass. Reported and the rule
            # produces nothing — never zero findings, which is the shape a
            # broken instrument would otherwise wear.
            broken.append(f"rule {rid}: RUNNER REFUSED ({exc.klass}) — {exc.detail}")
            return [], targets, COULD_NOT_LOOK + f"({exc.klass}) {exc.detail}"
        targets.update(reply.targets_matched)
        findings.extend(reply.findings)
    proxy = rule.get("floor_proxy")
    if proxy and not absent:
        targets.update(FLOOR_PROXIES[proxy](ROOT, rule).targets_matched)
    kept, _suppressed = apply_overrides(rid, findings)
    kept = apply_ratchets(rule, kept)
    if floors:
        for key, floor in (rule.get("floors") or {}).items():
            matched = targets.get(key, 0)
            # A floor that counts registry members an ABSENT app contributed is
            # lowered by exactly what that app contributed, and the message says
            # so. Everything else keeps the recorded number: a smaller
            # world is the one legal reason a floor may fall, and it has to be
            # paid for by a named app. An ABSENT TREE is the second, larger
            # subtraction and it takes every floor to zero — the derivation runs
            # here rather than being skipped around, so that the one path a
            # frontend-less template takes every run is the same path every
            # other rule takes.
            expected = W.derived_floor(rule, key, int(floor), DISABLED_APPS, absent_tree=absent)
            if matched < expected:
                paid = (
                    ""
                    if expected == int(floor)
                    else (
                        f" (recorded {floor}, lowered to {expected} — "
                        f"{', '.join(sorted(DISABLED_APPS))} is not in this deployment)"
                    )
                )
                broken.append(
                    f"rule {rid}: UNBOUND — {key}={matched} below floor {expected}{paid}; "
                    "the check may be watching nothing"
                )
    return kept, targets, why if absent else ""


# --- the Django system-check leg -------------------------------------------------

DJANGO_ID_TO_RULE: dict[str, str] = {}
for _rule in RULES:
    for _cid in _rule.get("django_check_ids") or []:
        DJANGO_ID_TO_RULE[str(_cid)] = str(_rule["id"])


def run_django_leg() -> list[tuple[str, str]]:
    """(rule_id, message) per djb error from `manage.py check --tag djb`.

    settings=test, no database. A non-djb crash in the leg is enforcement
    broken, not a pass.
    """
    env = dict(os.environ)
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    proc = subprocess.run(
        [sys.executable, "manage.py", "check", "--tag", "djb"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = proc.stdout + proc.stderr
    found: list[tuple[str, str]] = []
    for line in output.splitlines():
        m = re.search(r"\((djb\.[EW]\d+)\)", line)
        if m:
            rule_id = DJANGO_ID_TO_RULE.get(m.group(1), m.group(1))
            found.append((rule_id, line.strip()))
    if proc.returncode != 0 and not found:
        broken.append(
            f"the Django check leg failed without a djb finding (exit {proc.returncode}) — "
            f"enforcement is broken, not clean:\n{output.strip()[-2000:]}"
        )
    return found


# --- budgets: the rising floors --------------------------------------------------


def _docstring_lines(node: object) -> int:
    """How many source lines the first statement spends being a docstring.

    The docstring is the first Expr-of-a-str-Constant statement in the body —
    the same thing `ast.get_docstring` reads — and nothing else. A module whose
    first statement is a string that is NOT a docstring does not exist in
    Python's grammar, so there is no ambiguity to resolve here.
    """
    import ast as _ast

    body = getattr(node, "body", None)
    if not body:
        return 0
    first = body[0]
    if (
        isinstance(first, _ast.Expr)
        and isinstance(first.value, _ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return (first.end_lineno or first.lineno) - first.lineno + 1
    return 0


def measure_budgets() -> dict[str, dict[str, int]]:
    """The measured value of every budget subject, keyed as budgets.yaml keys it.

    `service_function_length` measures the BODY MINUS THE DOCSTRING: the
    span from `def` to the last line, less whatever the docstring spends. The
    ceiling exists to catch a service growing a SECOND JOB, and prose is the
    opposite of that — a function that shrinks by ten lines of code while its
    author writes ten lines explaining why measured flat under the old span, so
    the instrument could not see the thing it was pointed at. Rule-mandated
    comment lines (13's `# authz:`, 26's `# reach:`) still count, deliberately:
    "a rule-mandated block" is an open set, and an unfalsifiable population is
    the one thing the checklist forbids an instrument to carry.
    """
    return {
        section: {key: value for key, (value, _label) in subjects.items()}
        for section, subjects in _measure_budgets_detailed().items()
    }


def _measure_budgets_detailed() -> dict[str, dict[str, tuple[int, str]]]:
    """Every budget subject as (measured value, the label that NAMES it).

    The label is what lets a refusal say *which function* grew. `service_
    function_length` is keyed per FILE (the ruling: re-keying per function would
    make every new function a new-subject red and rewrite budgets.yaml's
    contract for a message-sized win), so without a label the message can only
    point at a module and leave the reader to go and find the longest thing in
    it.

    THE SUBJECT IS A FUNCTION, NOT A FILE. A `services.py` holding no top-level
    `def` at all records NO subject: a "longest function" of 0 with an empty
    label is not a measurement anybody took, it is a placeholder, and handing it
    to `check_budgets` turns "a new subject fails until a human measures it"
    into "a new empty module fails until a human commits a zero". The doctrine
    is about a subject that HAS a value; the first real function in a module
    becomes that subject in the change that writes it, exactly when a person can
    measure it — which is how every recorded ceiling here got its number. The
    module with one `def` is a subject and still fails without a ceiling, which
    is the half that keeps the doctrine true.
    """
    import ast as _ast

    service_lengths: dict[str, tuple[int, str]] = {}
    for path in sorted(ROOT.glob("apps/*/services.py")):
        tree = C._parse(path)
        if tree is None:
            continue
        longest, label, functions = 0, "", 0
        for node in tree.body:
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                functions += 1
                end = node.end_lineno or node.lineno
                measured = end - node.lineno + 1 - _docstring_lines(node)
                if measured > longest or not label:
                    longest = max(longest, measured)
                    label = f"{node.name} (lines {node.lineno}-{end})"
        # Counted, never inferred from the label: a function whose whole body is
        # its docstring measures 0, and reading "no label" as "no function"
        # would let that one module out of the population it belongs to.
        if functions == 0:
            continue
        service_lengths[str(path.relative_to(ROOT))] = (longest, label)
    out_fields: dict[str, tuple[int, str]] = {}
    for path in sorted(ROOT.glob("apps/*/schemas.py")):
        tree = C._parse(path)
        if tree is None:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, _ast.ClassDef) and node.name.endswith("Out"):
                key = f"{path.relative_to(ROOT)}::{node.name}"
                end = node.end_lineno or node.lineno
                out_fields[key] = (
                    sum(1 for s in node.body if isinstance(s, _ast.AnnAssign)),
                    f"{node.name} (lines {node.lineno}-{end})",
                )
    return {"service_function_length": service_lengths, "out_schema_fields": out_fields}


def check_budgets(recorded: dict | None = None) -> list[str]:
    if recorded is None:
        recorded = yaml.safe_load(BUDGETS_PATH.read_text()) if BUDGETS_PATH.exists() else None
    if not recorded:
        return ["quality/budgets.yaml is missing or empty — the rising floors are not recorded"]
    problems: list[str] = []
    for section, subjects in _measure_budgets_detailed().items():
        ceilings = recorded.get(section) or {}
        for key, (value, label) in subjects.items():
            named = f"{key} — {label}" if label else key
            ceiling = ceilings.get(key)
            if ceiling is None:
                problems.append(
                    f"budget: {section} has no recorded ceiling for {named} (measured {value}) — "
                    "a new subject fails until a human measures it and commits the number. "
                    f"The line to paste under `{section}:` in quality/budgets.yaml:\n"
                    f"  {key}: {value}"
                )
            elif value > int(ceiling):
                problems.append(
                    f"budget: {section} {named} grew to {value}, past the recorded ceiling "
                    f"{ceiling} — shrink it, or raise the ceiling in quality/budgets.yaml "
                    "in a diff a reviewer sees. The line to paste, verbatim:\n"
                    f"  {key}: {value}"
                )
            elif value < int(ceiling):
                notes.append(
                    f"budget note: {section} {named} measured {value}, below its ceiling "
                    f"{ceiling} — a human may commit the lower number:\n"
                    f"  {key}: {value}"
                )
    return problems


# --- consistency -----------------------------------------------------------------


def _scope_paths(node: object, trail: tuple[str, ...] = ()) -> Iterator[tuple[str, str]]:
    """Every `path:` a rule's scope names, with the key trail that names it.

    Walked structurally rather than by a list of known keys, so a rule that
    invents a new allow-list shape is covered on the day it is written.
    """
    if isinstance(node, dict):
        value = node.get("path")
        if isinstance(value, str) and value.strip():
            yield ".".join(trail) or "scope", value.strip()
        for key, child in node.items():
            if key != "path":
                yield from _scope_paths(child, (*trail, str(key)))
    elif isinstance(node, list):
        for child in node:
            yield from _scope_paths(child, trail)


def registry_floor_consistency(rule: dict) -> None:
    """A floor over a registry an optional app feeds must say what it counts.

    `probed_paths: 11` is a fact about eleven executed registry entries — and
    six of rule 35's twenty-one entries are the worked example's. Take the
    worked example out and the same number is a fact about a world that no
    longer exists, so the floor reads as a broken gate rather than as a smaller
    tree. The repair is not a lower number (that would lower it for everybody);
    it is a DECLARED BASIS, from which the expectation is derived per run.

    Required only where it bites: a registry with no optional-app member feeds
    no world-dependent number, and taxing it would be a rule about nothing. The
    day such a member arrives, this refuses — which is the day the floor
    actually became world-dependent.
    """
    rid = str(rule["id"])
    registry = rule.get("registry") or []
    declared = rule.get("registry_floors") or {}
    floors = rule.get("floors") or {}
    if not registry:
        if declared:
            broken.append(f"rule {rid}: registry_floors declared with no registry to feed them")
        return
    for key, basis in declared.items():
        if str(basis) not in W.REGISTRY_BASES:
            broken.append(
                f"rule {rid}: registry_floors {key!r} names basis {basis!r}, which is not "
                f"one of {', '.join(sorted(W.REGISTRY_BASES))}"
            )
        if key not in floors:
            broken.append(
                f"rule {rid}: registry_floors names {key!r}, which is not one of this "
                "rule's floors — a derivation for a number nobody reads"
            )
    if not any(W.registry_entry_app(e) in OPTIONAL_APPS for e in registry):
        return
    for key in floors:
        if key not in declared:
            broken.append(
                f"rule {rid}: floor {key!r} is pinned to {floors[key]} over a registry an "
                f"OPTIONAL app feeds ({', '.join(sorted(OPTIONAL_APPS))}) and does not say "
                "what it counts. Declare `registry_floors: {"
                f"{key}: <basis>"
                "}` so the expectation is derived from the apps this deployment "
                f"actually holds — one of {', '.join(sorted(W.REGISTRY_BASES))}; `opaque` "
                "is the honest answer where the registry cannot count it, and carries its "
                "reason on the rule"
            )


def seam_consistency() -> None:
    """The scope-kind declarations, and the seam's own recorded population.

    The seam is held to the grammar it enforces on everything else: a declared
    blind spot and a recorded self-test population, refused when missing rather
    than defaulted. A default here would be the exact defect the key exists to
    end — a plan that quietly loses a canary and keeps printing a total.
    """
    for name, kind in SCOPE_KINDS.items():
        if not isinstance(kind, dict):
            broken.append(f"scope kind {name!r}: not a declaration")
            continue
        for key in ("roots", "suffixes"):
            value = kind.get(key)
            if not isinstance(value, list) or not value:
                broken.append(f"scope kind {name!r}: {key} is {value!r}, not a non-empty list")
        for suffix in kind.get("suffixes") or []:
            if not str(suffix).startswith("."):
                broken.append(f"scope kind {name!r}: suffix {suffix!r} does not start with a dot")
        if not str(kind.get("comment", "")).strip():
            broken.append(
                f"scope kind {name!r}: no comment token — a kind whose valve syntax is "
                "unknown is a kind whose overrides cannot be found, and an override nobody "
                "can find is an exemption nobody can count"
            )
    # THE SIGNATURE CENSUS, both directions. A form whose expected signature the
    # code can no longer emit is the quietest failure an assertion corpus has:
    # it matches nothing, reports nothing, and reads as "stayed silent" forever.
    # So the refusal classes are declared, derived from the protocol module's own
    # source, and demanded of the canary table — a class cannot be renamed
    # without its canary, and cannot exist without one.
    emitted = check_v1.emitted_refusal_classes()
    for missing in sorted(check_v1.REFUSAL_CLASSES - emitted):
        broken.append(
            f"the seam declares the refusal class {missing!r}, which quality/check_v1.py no "
            "longer raises — a canary expecting it would match nothing and read as silence"
        )
    for undeclared in sorted(emitted - check_v1.REFUSAL_CLASSES):
        broken.append(
            f"quality/check_v1.py raises the refusal class {undeclared!r}, which is not in "
            "REFUSAL_CLASSES — a way to be unbelievable that nothing is obliged to prove"
        )
    canaried = {want for _label, _rule, want in _seam_canaries()}
    for unproven in sorted(check_v1.REFUSAL_CLASSES - canaried):
        broken.append(
            f"the refusal class {unproven!r} has no seam canary — a branch of the protocol "
            "nobody can show fires is a branch nobody can show works"
        )
    declared = SEAM.get("selftest_floor")
    if not isinstance(declared, dict) or {"canaries", "negatives"} - set(declared):
        broken.append(
            "the seam has no selftest_floor — record how many runner-protocol canary forms "
            "and negatives the plan holds, so a plan that quietly loses one is exit 2"
        )
    else:
        for kind_name, count in declared.items():
            try:
                if int(count) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                broken.append(f"the seam's selftest_floor {kind_name!r} is {count!r}, not a count")
    if not str(SEAM.get("does_not_cover", "")).strip():
        broken.append("the seam has no does_not_cover — an undeclared blind spot")


def rule_seam_consistency(rule: dict) -> None:
    """A rule's kind, runner and tree declarations — shape only, never existence.

    `needs_tree` is deliberately NOT resolved against the filesystem, and that
    is the one place this differs from the scope-path assertion below it. A
    scope allow-list is a fact about today; a `needs_tree` is a statement about
    a tree a product may or may not have grown, and refusing the absent case
    would refuse the template's own steady state.
    """
    rid = str(rule["id"])
    kind = rule.get("kind")
    if kind is not None and not isinstance(kind, dict) and str(kind) not in SCOPE_KINDS:
        broken.append(
            f"rule {rid}: kind {kind!r} is not one of the declared scope kinds "
            f"({', '.join(sorted(SCOPE_KINDS)) or 'none'})"
        )
    wanted = rule.get("needs_tree")
    if wanted is not None:
        if not isinstance(wanted, str) or not wanted.strip():
            broken.append(f"rule {rid}: needs_tree is {wanted!r}, not a path")
        else:
            # F6 (Vra, 2026-08-31): a non-empty string is not yet a PATH — an absolute
            # one, or one carrying `..`, could name something this checkout
            # does not own, which is exactly the shape `check_v1._refuse_outside_roots`
            # already refuses on the runner's OWN findings. `needs_tree` gets
            # the identical refusal rather than a second, looser one.
            candidate = Path(wanted)
            if candidate.is_absolute() or ".." in candidate.parts:
                broken.append(
                    f"rule {rid}: needs_tree is {wanted!r}, not a path RELATIVE to the "
                    "checkout root — an absolute path or a `..` segment could name something "
                    "this tree does not own"
                )
    runner = rule.get("runner")
    if runner is None:
        return
    if not isinstance(runner, dict):
        broken.append(f"rule {rid}: runner is {runner!r}, not a declaration")
        return
    argv = runner.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        broken.append(f"rule {rid}: runner argv is {argv!r}, not a non-empty list of strings")
    if "timeout" in runner:
        try:
            if int(runner["timeout"]) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            broken.append(f"rule {rid}: runner timeout is {runner['timeout']!r}, not seconds")
    if not W.kind_roots(rule, SCOPE_KINDS):
        broken.append(
            f"rule {rid}: a runner rule whose kind declares no roots can report about "
            "anywhere, which makes its scope whatever the instrument feels like"
        )
    if rule.get("needs_tree") is None and W.needs_tree(rule, SCOPE_KINDS) is None:
        broken.append(
            f"rule {rid}: a runner rule declares `needs_tree` — either on itself or on its "
            "kind — because a checkout without the tree must skip and say so rather than "
            "run an instrument at nothing"
        )


# --- the declaration's own census: one id per rule, one claimant per fixture -----
#
# Two failures of the DECLARATION rather than of the tree, and both arrive by
# the same route: a product merges a template release and the two rule sets are
# appended into one file. An id both sequences minted collides; a fixture
# directory both sequences numbered merges two rules' files into one directory.
# The first was already exit 2 with three words and no way forward; the second
# was not seen at all.


def _entry_descriptor(rule: dict, position: int) -> str:
    """How a reader tells two entries with one id apart, without a diff.

    The position in `quality/rules.yaml`'s own `rules:` list and the first
    words of the statement: enough for a product to say at a glance which of
    the two colliding entries is the one it wrote.
    """
    statement = " ".join(str(rule.get("statement") or "").split())
    if len(statement) > 70:
        statement = statement[:67] + "..."
    if rule.get("check"):
        mechanism = f"check {rule['check']}"
    elif rule.get("django_check_ids"):
        mechanism = "django checks " + ",".join(str(c) for c in rule["django_check_ids"])
    elif rule.get("runner"):
        mechanism = "a runner"
    elif rule.get("diff"):
        mechanism = "a diff rule"
    else:
        mechanism = "no mechanism"
    return f"entry #{position} in `rules:` ({mechanism}) — {statement or '(no statement)'}"


def duplicate_id_findings(rules: list[dict]) -> list[str]:
    """Two entries declaring one id, and what the holder of the red does next.

    THE REMEDY IS THE POINT. A bare `duplicate id` is true and unactionable:
    the reader cannot see WHICH two entries collided, does not know that the
    two also now share one canary directory, one negative directory and one
    valve number, and has no way to know which of the two is supposed to move.
    Every one of those is knowable here, so every one of them is said here.
    """
    seen: dict[str, tuple[int, dict]] = {}
    lines: list[str] = []
    for position, rule in enumerate(rules, start=1):
        rid = str(rule["id"])
        first = seen.get(rid)
        if first is None:
            seen[rid] = (position, rule)
            continue
        lines.append(
            f"rule {rid}: duplicate id — two entries in quality/rules.yaml declare it. "
            f"THE COLLISION: {_entry_descriptor(first[1], first[0])} AND "
            f"{_entry_descriptor(rule, position)}. They share more than the id: one canary "
            f"directory (quality/canary/{rid}/), one negative directory "
            f"(quality/negative/{rid}/) and one valve number, so a fold has merged two "
            f"rules' fixtures as well as their ids. REMEDY: only the template mints integer "
            f"ids, so the entry that moves is the product's. The namespace grammar is LIVE "
            f"on this tree ({GATE5_CITE}): declare "
            f"`rule_id_namespace: <ns>` once, top-level in quality/local/rules.yaml, beside "
            f"`template_rule_ids_through: <n>`, rename the product's entry to `<ns>-<n>`, "
            f"`git mv` both of its fixture directories to that id, rewrite its valve "
            f"comments to `# rule-<ns>-<n>:` and its check tag to `<ns>.Wnnn`. After that a "
            f"fold cannot collide at all. Do NOT renumber it to another integer: the "
            f"integers are the template's to mint and the next release takes the one you "
            f"picked."
        )
    return lines


def fixture_files_on_disk() -> list[Path]:
    """Every file under the two fixture trees, in one sorted list.

    `__pycache__` and `.DS_Store` are skipped because neither can be tracked
    (both are in `.gitignore`), so neither is a file anybody declared or can
    delete meaningfully — the census is about the tree git carries.
    """
    found: list[Path] = []
    for _kind, base in fixture_trees():
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.name == ".DS_Store":
                continue
            found.append(path)
    return found


def claimed_fixtures(rules: list[dict]) -> set[Path]:
    """Every fixture path some entry of some rule names, extra files included."""
    claimed: set[Path] = set(ENGINE_FIXTURES)
    for rule in rules:
        rid = str(rule["id"])
        for kind, base in fixture_bases(rid):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    claimed.add(base / rid / str(e["fixture"]))
    return claimed


def orphan_fixture_findings(rules: list[dict], on_disk: list[Path]) -> list[str]:
    """A fixture file no entry claims — the mirror of the missing-fixture refusal.

    `consistency()` has always refused a fixture a rule NAMES and the tree does
    not have. This is the other direction, and it is the one a fold produces: a
    file sitting in `quality/canary/<n>/` or `quality/negative/<n>/` that no
    entry anywhere names. Nothing plants it, so nothing proves anything with
    it, and it reads to every later reader as coverage the self-test has — the
    most expensive kind of wrong, because it is wrong in the direction of
    confidence. It is exit 2 rather than a violation for the same reason a dead
    canary is: the failure is in the enforcement's own plan, not in the code
    under it.
    """
    claimed = claimed_fixtures(rules)
    ids = {str(rule["id"]) for rule in rules}
    lines: list[str] = []
    for path in on_disk:
        if path in claimed:
            continue
        base = NEGATIVE_DIR
        for _tree_kind, tree in fixture_trees():
            if tree in path.parents:
                base = tree
                break
        # THE DIRECTORY IS NAMED FROM THE TREE IT WAS FOUND IN, never from the
        # template's spelling: a drawer fixture reported as living under
        # `quality/canary/` sends its reader to a path that does not exist.
        here = base.relative_to(ROOT)
        home = (
            "quality/local/rules.yaml" if base.is_relative_to(LOCAL_DIR) else "quality/rules.yaml"
        )
        parts = path.relative_to(base).parts
        rid = parts[0] if len(parts) > 1 else None
        if rid is None:
            nearest = (
                f"it sits directly in {here}/, which belongs to no rule at all — "
                f"every fixture lives under {here}/<rule id>/"
            )
        elif rid not in ids:
            nearest = (
                f"its directory {here}/{rid}/ is named for rule {rid}, and no rule "
                f"{rid} exists in {home}"
            )
        else:
            nearest = (
                f"rule {rid} is the nearest rule — no entry of rule {rid} claims it, in "
                f"`canaries:`, in `negatives:` or in any `extra_files:`"
            )
        lines.append(
            f"orphan fixture {path.relative_to(ROOT)}: {nearest}. A fixture no entry names "
            f"is planted by nothing and demonstrates nothing, and it reads as coverage this "
            f"self-test does not have. Either CLAIM it — add it to that rule's plan and raise "
            f"the rule's `selftest_floor` in the same diff — or, if a leg of quality/gate.py "
            f"plants it by path rather than through the plan, declare it in "
            f"ENGINE_FIXTURES — or DELETE it. After a template "
            f"fold this is usually two rules' fixtures merged into one directory by a "
            f"colliding id; fix the id first and the files follow it."
        )
    return lines


def engine_fixture_findings(engine: dict[Path, str]) -> list[str]:
    """An engine-planted fixture the tree does not have.

    The mirror of the orphan census, for the claims that live in this module
    rather than in `quality/rules.yaml`. It is the guard that turns "somebody
    deleted a fixture nothing in the plan named" from a `FileNotFoundError`
    halfway through a self-test into a refusal that says which leg breaks and
    why the file is there.
    """
    return [
        f"engine fixture {path.relative_to(ROOT)} is declared in ENGINE_FIXTURES and is not "
        f"on this tree: {why}. Restore the file, or delete the declaration in the same diff "
        "as the leg that reads it"
        for path, why in engine.items()
        if not path.is_file()
    ]


def fixture_census() -> None:
    """The orphan census over the real fixture trees, with its own floor.

    THE FLOOR IS HALF THE CENSUS. A walk that found nothing would report no
    orphans and read exactly like a clean tree, which is the green-because-empty
    shape every floor in this engine exists to refuse — so an empty walk, or a
    plan that claims no fixtures at all, is itself exit 2.
    """
    on_disk = fixture_files_on_disk()
    claimed = claimed_fixtures(RULES)
    if not on_disk or not claimed:
        broken.append(
            f"the orphan-fixture census looked at {len(on_disk)} file(s) under "
            f"quality/canary and quality/negative against {len(claimed)} claimed by "
            "quality/rules.yaml — one of the two is empty, so the census would report a "
            "clean tree whatever the tree held. That is could-not-look, not clean"
        )
        return
    broken.extend(engine_fixture_findings(ENGINE_FIXTURES))
    broken.extend(orphan_fixture_findings(RULES, on_disk))


def engine_fixture_dirs(engine: dict[Path, str] | None = None) -> set[str]:
    """The fixture DIRECTORY names `ENGINE_FIXTURES` claims, for the dir census.

    THE HALF `claimed_fixtures` COULD NOT REACH. That function claims engine
    fixtures BY PATH, so the FILE census is satisfied; the DIRECTORY census
    builds `claimed` out of rule ids alone, so a directory the engine plants
    into — one whose name is not any rule's id — is "a fixture directory no
    rule claims", exit 2, and NOTHING a reader declares can clear it. The
    template has never met it only because its one engine fixture happens to
    sit inside rule 50's directory; the first consumer's `read_census`
    partition fixtures do not, and their tree was exit 2 whatever they wrote.

    The name is the FIRST segment under the fixture tree, not `path.parent.name`
    — an engine fixture nested two deep belongs to the directory at the top of
    that tree, which is the thing the census iterates.
    """
    names: set[str] = set()
    for path in ENGINE_FIXTURES if engine is None else engine:
        for _kind, base in fixture_trees():
            if base in path.parents:
                names.add(path.relative_to(base).parts[0])
                break
        else:
            names.add(path.parent.name)
    return names


def fixture_dir_findings(
    bases: tuple[tuple[str, Path], ...] | None = None,
    claimed: set[str] | None = None,
    namespace: str | None = ...,  # type: ignore[assignment]
) -> list[str]:
    """Every directory under `quality/{canary,negative}/` is claimed by a rule.

    THE HALF A FILE CENSUS CANNOT SEE. A fold that merged two rules numbered
    `54` merged their fixture DIRECTORIES too, and the tree that came out had
    one `quality/canary/54/` holding two plans and no complaint from anything.
    A directory no rule id claims is therefore exit 2 — could-not-look, not a
    smaller census — and where its name carries a namespace this tree has not
    declared, the refusal says so, because that is the shape a half-finished
    adoption leaves behind (a `git mv` done and the key not written, or the key
    written and one directory missed).

    IT OVERLAPS `orphan_fixture_findings` DELIBERATELY, and the overlap is one
    line per unclaimed directory rather than a second census: that one answers
    "this FILE is planted by nothing", which is a symptom, and this one answers
    "this DIRECTORY belongs to no rule", which is the cause and the only half
    that can see an EMPTY unclaimed directory or say which namespace the name
    is under. Both are exit 2, so the extra line costs a reader nothing and
    saves them the inference.
    """
    if bases is None:
        bases = fixture_trees()
    if claimed is None:
        claimed = {str(rule["id"]) for rule in RULES} | engine_fixture_dirs()
    if namespace is ...:
        namespace = RULE_ID_NAMESPACE
    found: list[str] = []
    for kind, base in bases:
        try:
            here = str(base.relative_to(ROOT))
        except ValueError:
            here = f"quality/{kind}"
        if not base.is_dir():
            found.append(
                f"{here}/ is not a directory — the fixture tree the self-test plants "
                "from is gone, and every plan that reads from it would skip in silence"
            )
            continue
        for entry in sorted(base.iterdir()):
            name = entry.name
            if name in claimed:
                continue
            if not entry.is_dir():
                found.append(
                    f"{here}/{name}: a loose file at the top of the fixture tree — "
                    f"fixtures live in `{here}/<rule id>/` and nothing plants this"
                )
                continue
            prefix = name.rsplit("-", 1)[0] if "-" in name else None
            if prefix is not None and prefix != namespace:
                found.append(
                    f"{here}/{name}/: a fixture directory under the namespace "
                    f"{prefix!r}, which this tree has not claimed — {id_grammar(namespace)}"
                )
                continue
            found.append(
                f"{here}/{name}/: a fixture directory no rule claims — every "
                "directory here is one rule's id, and an unclaimed one is a plan that "
                "plants nothing or a rule that was renamed and left its fixtures behind"
            )
    return found


def local_ratchet_consistency() -> None:
    """A drawer ratchet names a PRODUCT app, never one inside the partition (X3.4).

    THE DIRECTION IS THE POINT. The drawer exists so a product's own backlog
    has somewhere to stand; it is not a second dial on the template's. A class
    naming an app in `quality/partition.yaml`'s `platform_apps` would raise a
    TEMPLATE rule's ceiling from a file the template never reads and no fold
    ever shows a reviewer — the quietest way there is to widen a rule.
    """
    raw = LOCAL_DOC.get("ratchets")
    if not isinstance(raw, dict) or not raw:
        return
    if PLATFORM_APPS is None:
        broken.append(
            _PARTITION_PROBLEM
            + " — and the drawer's `ratchets:` cannot be judged either: which classes are "
            "the template's to move is exactly the question that file answers"
        )
        return
    platform = PLATFORM_APPS
    app_dirs = (
        {d.name for d in (ROOT / "apps").iterdir() if d.is_dir()}
        if (ROOT / "apps").is_dir()
        else set()
    )
    for rid, classes in raw.items():
        if not isinstance(classes, dict):
            continue
        for klass in classes:
            name = str(klass)
            # A CLASS IS `<app>` OR `<app>.<kind>` — rules 54 and 55 key theirs
            # the second way (`core.role-value`), so a check that only read the
            # whole string would let `core.role-value: 12` through and the
            # drawer would be raising a platform ceiling after all.
            app_part = name.split(".", 1)[0]
            if name in platform or app_part in platform:
                broken.append(
                    f"quality/local/rules.yaml: `ratchets:` rule {rid} records class {name!r}, "
                    f"whose app {app_part!r} is inside quality/partition.yaml's "
                    "`platform_apps`. The "
                    "drawer records a PRODUCT's backlog; a platform app's ceiling is the "
                    "template's to move, in a diff a reviewer reads. "
                    f"Record {name!r} in quality/rules.yaml, or record the class of the "
                    "product app whose findings these really are"
                )
            elif is_local_rule(str(rid)) and app_dirs and app_part not in app_dirs:
                # DRAWER RULES ONLY. A class on a TEMPLATE rule whose app is not
                # on the tree is refused outright by `_merge_local_ratchets`; a
                # drawer rule's own classes need not be apps at all, so the most
                # this can honestly be is a line in case it is a typo.
                notes.append(
                    f"quality/local/rules.yaml ratchet: rule {rid} class {name!r} is not an "
                    "app on this tree — legal on a rule of your own (a class need not be an "
                    "app), said out loud in case it is a typo for one"
                )


def local_plant_consistency() -> None:
    """A drawer rule's fixtures plant into a PRODUCT app, or `apps/example` (X3.6).

    PLANT PORTABILITY. A canary is planted THROUGH THE REAL SCOPE, into
    the real tree — so a product rule whose canary plants into `apps/core` is a
    product writing a fixture into a template-owned app, and the next fold
    either loses it or conflicts on it. `apps/example` is the one platform app
    a product's plant may use: it is the worked example every clone carries and
    the template's own canaries already plant there, so a product with no app
    of its own yet still has somewhere to demonstrate from.
    """
    if not LOCAL_RULE_IDS:
        return
    if PLATFORM_APPS is None:
        broken.append(
            _PARTITION_PROBLEM
            + " — and a drawer rule's plant sites cannot be judged either: which apps the "
            "template owns is exactly the question that file answers"
        )
        return
    platform = PLATFORM_APPS
    allowed_platform = {"example"}
    for rule in RULES:
        rid = str(rule["id"])
        if not is_local_rule(rid):
            continue
        for kind in ("canaries", "negatives"):
            singular = "canary" if kind == "canaries" else "negative"
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    target = str(e.get("plant_at") or "")
                    parts = target.split("/")
                    if len(parts) < 2 or parts[0] != "apps" or "{{" in parts[1]:
                        continue
                    app = parts[1]
                    if app in platform and app not in allowed_platform:
                        broken.append(
                            f"rule {rid}: {singular} {e.get('fixture')} plants at {target}, "
                            f"inside the platform app {app!r} (quality/partition.yaml "
                            "`platform_apps`). A drawer rule plants into one of YOUR apps, or "
                            "into apps/example — the template owns the rest, and a fixture a "
                            "fold overwrites is a canary that stops firing without a diff "
                            "(plant portability, ADR gate-5's drawer)"
                        )


def consistency() -> None:
    seam_consistency()
    for problem in _LOCAL_PROBLEMS:
        broken.append(problem)
    for problem in _NAMESPACE_PROBLEMS:
        broken.append(problem)
    if _PARTITION_PROBLEM:
        broken.append(_PARTITION_PROBLEM)
    local_ratchet_consistency()
    local_plant_consistency()
    broken.extend(duplicate_id_findings(RULES))
    fixture_census()
    broken.extend(fixture_dir_findings())
    for rule in RULES:
        rid = str(rule["id"])
        shape = id_shape_problem(rid)
        if shape:
            broken.append(shape)
        impl = rule.get("check")
        if impl:
            unresolved = resolve_check_problem(rid, str(impl))
            if unresolved:
                broken.append(unresolved)
        if (
            not impl
            and not rule.get("django_check_ids")
            and not rule.get("diff")
            and not rule.get("runner")
        ):
            broken.append(f"rule {rid}: no mechanism at all — not a rule, a wish")
        proxy = rule.get("floor_proxy")
        if proxy and proxy not in FLOOR_PROXIES:
            broken.append(f"rule {rid}: floor proxy {proxy!r} not in registry")
        doc = rule.get("doc") or {}
        doc_path = ROOT / doc.get("file", "")
        if not doc_path.is_file():
            broken.append(f"rule {rid}: doc file {doc.get('file')} missing")
        elif str(doc.get("contains", "")).lower() not in doc_path.read_text().lower():
            broken.append(
                f"rule {rid}: doc {doc['file']} no longer states the rule (anchor "
                f"{doc['contains']!r} missing)"
            )
        # THE VALVE, AS DATA (contract B.1). Every rule says how a legitimate
        # exception to it is recorded — the marker, and where it has to sit —
        # or says that nothing can excuse it and why. Before this field the
        # grammar was prose in four files (`quality/gate.py`'s generic
        # override, `checks.py`'s `# authz:`/`# reach:`/`# door:`/
        # `# role-bound:`, the conventions skill's table) and a reader holding
        # a red had no way to learn any of it from the red. A rule with
        # NEITHER form is exit 2 rather than a quieter trailer: the census of
        # which rules genuinely have no valve is the point of the field, and a
        # rule that silently declined to answer it would be the one place the
        # census cannot see.
        valve = rule.get("valve")
        if not isinstance(valve, dict):
            broken.append(
                f"rule {rid}: no valve — declare `valve: {{ marker: ..., where: ... }}` or "
                "`valve: { none: <why nothing can excuse this> }`; a red that cannot say how "
                "to record a legitimate exception is a red nobody can act on"
            )
        else:
            excuse = str(valve.get("none") or "").strip()
            marker = str(valve.get("marker") or "").strip()
            where = str(valve.get("where") or "").strip()
            if excuse and (marker or where):
                broken.append(
                    f"rule {rid}: valve declares `none:` AND a marker — one or the other, "
                    "never both; a reader cannot be told there is no valve and handed one"
                )
            elif excuse:
                if len(excuse) < MIN_REASON:
                    broken.append(
                        f"rule {rid}: valve `none:` reason is {len(excuse)} characters — a "
                        "claim that nothing can excuse this rule is exactly the claim that "
                        "owes a sentence a reviewer can disagree with"
                    )
            elif not (marker and where):
                broken.append(
                    f"rule {rid}: valve declares neither `marker:` + `where:` nor "
                    "`none: <reason>` — a valve a reader cannot paste, in a place the rule "
                    "will not read it, is not a valve"
                )
        canaries = rule.get("canaries") or []
        if len(canaries) < 2:
            broken.append(
                f"rule {rid}: fewer than two canary forms — a check that can't "
                "demonstrably fail two ways is decoration"
            )
        if not rule.get("negatives"):
            broken.append(f"rule {rid}: no negatives — restraint unproven")
        if not rule.get("floors"):
            broken.append(f"rule {rid}: no floors — green-because-empty would read as a pass")
        # the recorded self-test population. Required rather than
        # defaulted, because a rule that arrives without one is ratcheted at
        # zero and its canaries could all stop being planted in silence — which
        # is the exact failure this key exists to end.
        declared = rule.get("selftest_floor")
        if not isinstance(declared, dict) or {"canaries", "negatives"} - set(declared):
            broken.append(
                f"rule {rid}: no selftest_floor — record how many canary forms and negatives "
                "this rule's plan holds, so a plan that quietly loses one is exit 2 and not a "
                "smaller total nobody reads"
            )
        else:
            for kind, count in declared.items():
                try:
                    if int(count) < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    broken.append(
                        f"rule {rid}: selftest_floor {kind!r} is {count!r}, which is not a count"
                    )
        for klass, count in (rule.get("ratchets") or {}).items():
            # A ratchet nobody can read is an off switch with extra steps.
            if not str(klass).strip():
                broken.append(f"rule {rid}: a ratchet with no class name")
            try:
                if int(count) < 0:
                    raise ValueError
            except (TypeError, ValueError):
                broken.append(f"rule {rid}: ratchet {klass!r} is {count!r}, which is not a count")
        # `remedies:` is a fix form per finding class (ADR gate-6). An empty one
        # is worse than none: `--explain` prints the key and the reader learns
        # that somebody meant to write a remedy here.
        remedies = rule.get("remedies")
        if remedies is not None:
            if not isinstance(remedies, dict) or not remedies:
                broken.append(
                    f"rule {rid}: `remedies:` is {remedies!r} — it is a mapping of finding "
                    "class (or `*`) to the fix form for that class, and an empty one is a "
                    "promise `--explain` cannot keep"
                )
            else:
                for klass, text in remedies.items():
                    if not str(klass).strip() or len(str(text or "").strip()) < MIN_REASON:
                        broken.append(
                            f"rule {rid}: remedy {klass!r} is {text!r} — a fix form says what "
                            "to WRITE INSTEAD, and a reader cannot act on a blank one"
                        )
        if not str(rule.get("does_not_cover", "")).strip():
            broken.append(f"rule {rid}: no does_not_cover — an undeclared blind spot")
        registry_floor_consistency(rule)
        rule_seam_consistency(rule)
        for kind, base in fixture_bases(rid):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    if not (base / rid / e["fixture"]).is_file():
                        broken.append(
                            f"rule {rid}: {kind[:-1]} fixture {e['fixture']} missing from "
                            f"{(base / rid).relative_to(ROOT)}/"
                        )
                # A form may DECLARE the world it needs when its plant path
                # cannot say so, and a declaration naming an app that is not on
                # this tree is a plan for a world nobody can enter.
                declared = entry.get("needs_app")
                if declared and not (ROOT / "apps" / str(declared)).is_dir():
                    broken.append(
                        f"rule {rid}: {kind[:-1]} {entry['fixture']} declares "
                        f"`needs_app: {declared}`, which is not an app under apps/"
                    )
        for cid in rule.get("django_check_ids") or []:
            # THE CHECK TAG IS THE ID'S FOURTH SPELLING (ADR gate-5). A
            # product's system check answers `acme.W001`, never `djb.W001`:
            # two products and the template all writing `djb.` is the id
            # collision again, one layer down, where Django's own registry
            # merges them and nothing here would see it.
            want = check_tag_prefix(rid)
            if not str(cid).startswith(f"{want}."):
                broken.append(
                    f"rule {rid}: django check id {cid} is not a `{want}.` tag — {id_grammar()}"
                )
            if is_template_id(rid):
                checks_src = (ROOT / "apps" / "core" / "checks.py").read_text()
                where = "apps/core/checks.py"
                found = str(cid) in checks_src
            else:
                # A product's checks live in the product's own app, so the
                # presence census reads every `checks.py` under `apps/` rather
                # than the template's one file.
                found = any(
                    str(cid) in p.read_text() for p in sorted(ROOT.glob("apps/*/checks.py"))
                )
                where = "any apps/*/checks.py"
            if not found:
                broken.append(f"rule {rid}: django check id {cid} not present in {where}")
        # every path a rule's SCOPE names must resolve on this
        # tree. A scope entry is read as a fact about today — "this file may
        # import the engine", "this tree may name the credential" — and rule
        # 33's own does_not_cover already declared it cannot tell whether an
        # allow-listed module still DESERVES to be. This is the sibling it was
        # missing: whether it EXISTS. Two of rule 33's five allow_import
        # entries named files no rung had written yet, so the statement a
        # reader was handed as true today described a tree that did not exist,
        # and nothing anywhere could say so. A forward-looking entry is now
        # added by the rung that lands the file, which keeps the allow-list a
        # diff rather than a discovery (the same discipline rule 11's
        # `extra_modules` comments record about themselves).
        for where, path in _scope_paths(rule.get("scope") or {}):
            if not (ROOT / path).exists():
                broken.append(
                    f"rule {rid}: scope {where} names {path}, which does not exist on this "
                    "tree — an allow-list entry is a fact about today, not a plan; add it in "
                    "the rung that writes the file"
                )


# --- planting --------------------------------------------------------------------


# --- plant placeholders: a fixture may not freeze the tree's state ------------
#
# THE INCIDENT (P7, the SRCH-FIX push). Rule 6's negative plants "one honest new
# leaf on top of the real one" into `apps/example/migrations/`, and all three of
# its moving parts were TYPED: the parent in the fixture, the number in
# `plant_at`, and the marker in its extra file. R-e landed
# `0011_widget_search_vector`, so the plant stopped being a successor and became
# a SECOND LEAF — the negative fired, the self-test went exit 2, and the push was
# blocked by a fixture rather than by the tree.
#
# THIS WAS THE FOURTH TIME. rules.yaml's own comment on that entry said so
# ("CORE-11 (0010) is the third rung to pay this"), and paying it a fifth time
# means every rung that touches `apps/example` — the designated search-adoption
# app, which will keep growing migrations — owes an edit to a file in `quality/`
# that has nothing to do with what it built. That is the collision the whole
# discovery discipline exists to avoid, pointed at the gate instead of at
# `config/`.
#
# THE FIX IS DERIVATION, the same answer the rest of this engine already gives:
# a fixture names what it wants and the resolver reads today's tree.
#
# {{leaf:<app>}} the app's current single migration leaf
# {{after:<app>:<slug>}} the next number after it, plus <slug> —
# `0011_widget_search_vector` -> `0012_neg_leaf`
#
# Substituted in BOTH `plant_at` and fixture CONTENT, because a plant that
# derived its parent but kept a typed filename would still fork the graph on the
# number alone. An unknown placeholder, or an app whose graph does not have
# exactly one leaf, is exit 2 (could-not-look) — never a silent literal.
PLACEHOLDER = re.compile(r"\{\{(leaf|after):([A-Za-z_][A-Za-z0-9_]*)(?::([A-Za-z0-9_]+))?\}\}")

# : Resolved ONCE, against the unplanted tree, and cached. Deliberate: the
# : resolver reads the migration graph, and rule 6's canaries plant INTO that
# : graph — a resolver that re-read per plant would be reading a tree an earlier
# : plant had already moved. `selftest` primes it before the first plant, and
# : `tree_dirty_under_plants` (which runs first, and refuses a dirty tree) is what
# : makes "unplanted" a fact rather than a hope.
_RESOLVED: dict[str, str] = {}
_RESOLVED_PRIMED = False


def resolve_plant_text(text: str) -> str:
    """Every `{{...}}` in a plant_at or a fixture body, replaced from today's tree."""

    def one(match: re.Match[str]) -> str:
        kind, app_label, slug = match.group(1), match.group(2), match.group(3)
        leaf = _RESOLVED.get(app_label)
        if leaf is None:
            leaf = C.app_migration_leaf(ROOT, app_label)
            if leaf is None:
                broken.append(
                    f"plant placeholder {match.group(0)}: apps/{app_label} does not have "
                    "exactly one migration leaf on this tree, so a fixture cannot be "
                    "chained onto it. The self-test could not look — it has not passed"
                )
                return match.group(0)
            _RESOLVED[app_label] = leaf
        if kind == "leaf":
            return leaf
        number, _, _rest = leaf.partition("_")
        try:
            nxt = f"{int(number) + 1:04d}"
        except ValueError:
            broken.append(
                f"plant placeholder {match.group(0)}: the leaf {leaf!r} does not begin with "
                "a migration number, so there is no 'next' to derive"
            )
            return match.group(0)
        return f"{nxt}_{slug}" if slug else nxt

    return PLACEHOLDER.sub(one, text)


def prime_plant_resolution() -> None:
    """Read the tree's leaves once, before anything is planted into it."""
    global _RESOLVED_PRIMED
    if _RESOLVED_PRIMED:
        return
    _RESOLVED_PRIMED = True
    for rule in RULES:
        for kind in ("canaries", "negatives"):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    resolve_plant_text(str(e["plant_at"]))
                    fixture = fixture_home(kind, str(rule["id"])) / e["fixture"]
                    if fixture.is_file():
                        resolve_plant_text(fixture.read_text())


class Plant:
    """Plant fixture files into the real tree; restore exactly, whatever happens."""

    def __init__(self) -> None:
        self.saved: dict[Path, bytes | None] = {}
        self.made_dirs: list[Path] = []

    def _remember(self, target: Path) -> None:
        if target not in self.saved:
            self.saved[target] = target.read_bytes() if target.exists() else None

    def put(self, fixture: Path, plant_at: str, mode: str) -> None:
        plant_at = resolve_plant_text(plant_at)
        target = ROOT / plant_at
        self._remember(target)
        parent = target.parent
        missing: list[Path] = []
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for d in reversed(missing):
            d.mkdir()
            self.made_dirs.append(d)
        content = resolve_plant_text(fixture.read_text())
        if mode == "append":
            base = target.read_text() if target.exists() else ""
            target.write_text(base + content)
        else:
            target.write_text(content)

    def scaffold_probe(self) -> None:
        self._remember(PROBE_DIR / "__init__.py")
        self._remember(PROBE_DIR / "apps.py")
        PROBE_DIR.mkdir(exist_ok=True)
        self.made_dirs.append(PROBE_DIR)
        (PROBE_DIR / "__init__.py").write_text("")
        (PROBE_DIR / "apps.py").write_text(PROBE_APPS_PY)

    def restore(self) -> None:
        for target, original in self.saved.items():
            if original is None:
                target.unlink(missing_ok=True)
            else:
                target.write_bytes(original)
        for d in reversed(self.made_dirs):
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        if PROBE_DIR.exists():
            shutil.rmtree(PROBE_DIR, ignore_errors=True)
        self.saved.clear()
        self.made_dirs.clear()


def plant_paths() -> list[str]:
    """Every path a plant can touch, RESOLVED — the dirty check reads these.

    Resolved rather than literal because `git status --porcelain -- <path>` on a
    `{{after:example:neg_leaf}}.py` matches nothing at all: the refusal that
    protects the tree would go on saying "clean" about a path it was no longer
    naming (N-Q32b).
    """
    prime_plant_resolution()
    paths: set[str] = {f"apps/{PROBE_APP}"}
    for rule in RULES:
        for kind in ("canaries", "negatives"):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    paths.add(resolve_plant_text(str(e["plant_at"])))
    return sorted(paths)


#: Short enough that no real fixture is excluded; long enough that a stub, a
#: blank line or a one-word file cannot match half the tree by accident.
MIN_FIXTURE_SIGNATURE = 20


def stale_plants() -> list[str]:
    """Files on this tree that ARE a fixture — the residue of a run that died.

    THE INCIDENT SHAPE, and it is the worst one this engine has: a self-test
    killed between plant and restore leaves its fixtures standing. The next run
    then reads planted wrongness as the product's own work — or, far worse,
    reads a planted NEGATIVE as a clean scan and reports green over a tree that
    is partly fixture. A gate that measures its own leftovers is not measuring
    anything, and nothing in its output says so.

    CLOSED QUESTION, AND DELIBERATELY THE NARROWEST TOTAL ONE: a plant target
    whose bytes ARE the fixture's bytes. Nobody writes a file identical to a
    planted violation by accident, and an ordinary edit under a plant path —
    which is most of `apps/` on any working day — is silent here. That is
    exactly why this can run on EVERY mode while the dirty-tree refusal below
    can only run inside the self-test: one asks whether a file changed, this
    asks whether a file IS a fixture.

    The scaffold app is the loudest member and needs no comparison at all: it
    exists only while a plant holds it, so finding it at rest is finding a run
    that never finished.
    """
    found: list[str] = []
    if PROBE_DIR.exists():
        found.append(
            f"apps/{PROBE_APP}/ — the self-test's scaffold app, which exists only while a "
            "plant is held. Finding it at rest is finding a run that never restored"
        )
    mark = len(broken)
    for rule in RULES:
        for kind, base in fixture_bases(str(rule["id"])):
            for entry in rule.get(kind) or []:
                for e in [entry, *(entry.get("extra_files") or [])]:
                    fixture = base / str(rule["id"]) / e["fixture"]
                    if not fixture.is_file():
                        continue
                    body = resolve_plant_text(fixture.read_text())
                    if len(body.strip()) < MIN_FIXTURE_SIGNATURE:
                        continue
                    target = ROOT / resolve_plant_text(str(e["plant_at"]))
                    if not target.is_file():
                        continue
                    try:
                        text = target.read_text()
                    except (OSError, UnicodeDecodeError):
                        continue
                    if text == body or (e["mode"] == "append" and text.endswith(body)):
                        found.append(
                            f"{target.relative_to(ROOT)} — the "
                            f"{'canary' if kind == 'canaries' else 'negative'} "
                            f"{e['fixture']} of rule {rule['id']} is standing on the tree"
                        )
    # Placeholder resolution reads the migration graph and can refuse; that
    # refusal belongs to the self-test, not to a preflight whose whole job is to
    # look at the tree before anything else does. Taken back rather than
    # surfaced here, so a preflight cannot invent a verdict of its own.
    del broken[mark:]
    return found


def refuse_stale_plants() -> None:
    """Exit 2 before anything measures a tree it would be measuring wrong.

    F4 (Vra, 2026-08-31): true of BOTH modes `main()` runs, not only `--selftest`. This
    function only appends to `broken`; the one `return` inside it is the
    "nothing stale" case. What used to make the header sentence a claim rather
    than a fact was `main()`'s own branch below it — `--selftest` already
    skipped its leg on `if not broken`, and plain scan mode called `live_scan`
    unconditionally, one `return`(-equivalent guard) short of the sentence
    above. Both modes now honour it.
    """
    stale = stale_plants()
    if not stale:
        return
    broken.append(
        "STALE PLANTS ON THE TREE — a self-test that did not reach its restore left these "
        "behind, and every leg after this line would be reading fixtures as the product's "
        "own code. A negative left standing is the dangerous half: it reports nothing and "
        "the run goes green over a tree that is partly planted. Remove them and run again "
        "(`git status --porcelain`, then `git checkout --` the tracked ones and delete the "
        "untracked ones):\n  " + "\n  ".join(stale)
    )


def tree_dirty_under_plants() -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", *plant_paths()],
        capture_output=True,
        text=True,
        check=False,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


# --- selftest --------------------------------------------------------------------


def names_planted(finding: Finding, plant_at: str) -> bool:
    parts = Path(plant_at).parts
    suffix = "/".join(parts[-2:]) if len(parts) >= 2 else parts[-1]
    return plant_at in finding.path or suffix in finding.path or suffix in str(finding)


def selftest_floor(rule: dict) -> dict[str, int]:
    """The canary/negative population this rule RECORDS, as a rising floor.

    . The self-test used to print one aggregate — `117 canary forms fired`
    — and nothing compared it to anything, so "did THIS rule's canaries fire"
    was answered by arithmetic against rules.yaml rather than by reading the
    output. Counting the entries in `rules.yaml` and comparing THAT to what
    fired would not have closed it either: a total derived from the same file
    it is checking cannot notice that file shrinking. A canary deleted from a
    plan takes the expectation with it and the run stays green.

    So the population is RECORDED, in the same grammar as `floors` and the
    budget ceilings: below it is exit 2 naming the rule, above it is a note
    saying a human may commit the higher number. Growth is free; a plan that
    quietly loses a form is not.
    """
    declared = rule.get("selftest_floor") or {}
    return {
        "canaries": int(declared.get("canaries", 0)),
        "negatives": int(declared.get("negatives", 0)),
    }


def residence_findings(rules: list[dict]) -> list[str]:
    """A rule whose whole canary plan lives in an app a deployment may remove.

    THE SUBJECT. `optional = True` is a promise that a product can ship
    without an app. A rule whose every canary form plants into that app keeps
    its promise and loses its teeth in the same move: the check still runs, the
    self-test still prints a line, and nothing anywhere can demonstrate that the
    rule can fail. That is not a rule with a smaller world; it is a rule an
    environment variable deleted.

    The population is read off the `optional` declarations, never a list here
    (`quality/worlds.py`), and the same ratchet grammar the rest of this engine
    uses holds it: at or below `selftest_residence_backlog` the members are
    NOTES, printed by name every run; one over it and every member is exit 2
    naming the growth. Shrinking never tightens the number by itself.
    """
    template, product = W.split_residence_census(W.residence_census(rules, OPTIONAL_APPS))

    def _line(rid: str, app: str) -> str:
        return (
            f"rule {rid}: every canary form this rule has plants in apps/{app}, which declares "
            f"`optional = True` — a deployment that leaves {app} out leaves this rule unable to "
            "demonstrate a failure at all. Re-home one form into an app the product cannot "
            "remove, or say in the rule why the subject only exists there"
        )

    findings: list[str] = []
    # THE PRODUCT'S OWN CENSUS, AT ZERO (D4, ADR gate-5). The recorded backlog
    # is a measurement of the TEMPLATE's rules that a product folds and never
    # retypes, so a namespaced rule is never counted into it and never hidden
    # by it: the first one is named the moment it is written.
    if product:
        findings.append(
            f"selftest residence: {len(product)} product rule(s) prove nothing without an "
            "optional app, against a backlog of 0 — `selftest_residence_backlog` records the "
            "TEMPLATE's members and a product never retypes it (ADR gate-5). The members "
            "follow:"
        )
        findings.extend(_line(rid, app) for rid, app in product)
    if len(template) > RESIDENCE_BACKLOG:
        findings.append(
            f"selftest residence is at {len(template)} template rules, past the recorded "
            f"backlog of {RESIDENCE_BACKLOG} — a rule whose whole canary plan lives in an "
            f"optional app may shrink and never grow. The whole census follows:"
        )
        findings.extend(_line(rid, app) for rid, app in template)
    return findings


def residence_leg() -> None:
    """Run the residence census, and prove the census itself can fail.

    THE MECHANISM'S OWN CANARY, in the shape the budget canary already uses
    below: this leg's subject is `rules.yaml` data rather than the tree, so its
    forms are RULE-SHAPED and asserted directly. Planting a file could not
    exercise it — there is no file whose presence makes a rule's canary plan
    live in one app.
    """
    census, _product = W.split_residence_census(W.residence_census(RULES, OPTIONAL_APPS))
    for line in residence_findings(RULES):
        broken.append(line)
    if len(census) <= RESIDENCE_BACKLOG:
        # The standing backlog, printed BY NAME on every run: a number nobody
        # can expand into a list is a number nobody can pay down. Said with
        # `say` and not through `notes`, which a self-test run fills with every
        # ratchet note from every planted tree and never prints.
        say(
            f"selftest residence: {len(census)} of {len(RULES)} rules prove nothing without "
            f"an optional app, against a recorded backlog of {RESIDENCE_BACKLOG}:"
        )
        for rid, app in census:
            say(f"    rule {rid}: whole canary plan in apps/{app}")
        if len(census) < RESIDENCE_BACKLOG:
            say(
                f"    a human may commit {len(census)} to quality/rules.yaml "
                "(selftest_residence_backlog); nothing tightens by itself."
            )

    optional_app = min(OPTIONAL_APPS) if OPTIONAL_APPS else None
    if optional_app is None:
        # No app in this tree declares `optional = True`, so the census has no
        # subject and its canary would be a plant into a world that does not
        # exist. Said out loud rather than skipped silently.
        say(
            "selftest residence: no app declares `optional = True` on this tree, so the "
            "residence census has no subject and its canary did not run."
        )
        return
    canary = {
        "id": "residence-canary",
        "canaries": [
            {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
            {"fixture": "b.py", "plant_at": f"apps/{optional_app}/services.py", "mode": "append"},
        ],
    }
    if not residence_findings([*RULES, canary]):
        broken.append(
            "RESIDENCE CANARY DEAD — a rule planted 100% in "
            f"apps/{optional_app} did not push the census past its recorded backlog"
        )
    # THE NEGATIVE, and it is rule 35's real plan set rather than an invention:
    # three forms in `core`, `events` and `realtime` and one in `quality/`
    # itself. A census that fired here would be telling every mixed-residence
    # rule to move canaries that are already outside the optional world.
    mixed = {
        "id": "residence-negative",
        "canaries": [
            {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
            {"fixture": "b.py", "plant_at": "apps/core/audit.py", "mode": "append"},
        ],
    }
    if residence_findings([*RULES, mixed]):
        broken.append(
            "RESIDENCE FALSE-POSITIVE REGRESSION — a rule with one canary form outside "
            f"apps/{optional_app} was counted into the residence census"
        )


def ratchet_leg() -> None:
    """The UNMEASURED branch, and proof that it fires for one shape only.

    THE SUBJECT IS `rules.yaml` DATA AND A LIST OF FINDINGS, so the forms are
    forged and handed to the shipped function directly — the shape
    `residence_leg` above and `declaration_leg` below already use, and the only
    honest one here: no file on any tree makes a ratchet class unmeasured. What
    makes one unmeasured is an app the partition does not name, and the nearest
    real one does not exist on the template (that is what the template BEING
    the partition means).

    ONE CANARY AND FOUR NEGATIVES, and the negatives are the whole argument:
    the branch must stay silent for a template app (absence IS the measurement
    there), for a class that is not an app at all, for the plant scaffold, and
    for a class the product has already recorded — including at zero, which is
    a measurement somebody made and not an absent one.
    """
    fired = 0
    silent = 0

    def _finding(path: str, klass: str) -> Finding:
        return Finding(path, 12, "a forged finding, planted by the self-test", klass)

    def _rule(ratchets: dict) -> dict:
        return {"id": "54", "ratchets": dict(ratchets)}

    def _headers(rule: dict, findings: list[Finding]) -> list[str]:
        return [
            str(f.msg) for f in apply_ratchets(rule, findings) if f.path == "quality/rules.yaml"
        ]

    if PLATFORM_APPS is None:
        broken.append(
            "RATCHET LEG COULD NOT RUN — the partition lockfile did not read, so nothing "
            "here can tell a product app from a template one. The line above names it"
        )
        return

    # -- THE CANARY: a class keyed on an app the partition does not name ------
    outsider = "acme"
    if outsider in PLATFORM_APPS:  # pragma: no cover - the template ships no `acme`
        broken.append(
            "RATCHET CANARY COULD NOT RUN — this tree's partition names an app called "
            f"{outsider!r}, so the canary's outsider is not outside anything"
        )
        return
    hits = [_finding(f"apps/{outsider}/selectors.py", f"{outsider}.read")]
    lines = _headers(_rule({}), hits)
    paste = f"{outsider}.read: 1  # recorded-at {recording_sha()} [fold]"
    wanted = (paste, f"apps/{outsider}", "platform_apps", "NEVER BEEN MEASURED", "ADR gate-6")
    if not lines:
        broken.append(
            "UNMEASURED-RATCHET CANARY DEAD — a finding in a class keyed on "
            f"apps/{outsider}, which the partition does not name and no ratchet records, "
            "produced no header at all: the product holding it is back at a zero nothing "
            "explains"
        )
    else:
        absent = [w for w in wanted if w not in lines[-1]]
        if absent:
            broken.append(
                "UNMEASURED-RATCHET CANARY MUTE — the header fired without the part a "
                f"reader acts on: {', '.join(absent)} is not in the line. The line IS the "
                f"remedy, and a header without it is the bare zero it replaced: {lines[-1]}"
            )
        else:
            fired += 1
    # AND THE FINDINGS THEMSELVES STILL FAIL. The recording is a remedy, never
    # an amnesty: a header that arrived INSTEAD of the violations would have
    # turned green-because-unrecorded into green-because-explained.
    if not [f for f in apply_ratchets(_rule({}), hits) if f.path != "quality/rules.yaml"]:
        broken.append(
            "UNMEASURED-RATCHET CANARY SOFTENED — the unmeasured header replaced the "
            "violations instead of heading them; an unrecorded class is still exit 1 "
            "(quality/budgets.yaml)"
        )

    # -- THE NEGATIVES --------------------------------------------------------
    negatives = (
        (
            "a template app",
            _rule({}),
            [_finding("apps/core/selectors.py", "core.read")],
            "apps/core is inside the partition, where an absent entry IS the measurement — "
            "offering to record one would ask the template to write down its own zeroes",
        ),
        (
            "a class that is not an app",
            _rule({}),
            [_finding("apps/core/policies.py", "nonconforming")],
            "`nonconforming` is a class name, not an app label, and a header naming "
            "apps/nonconforming would send a reader to a directory nobody has",
        ),
        (
            "the plant scaffold",
            _rule({}),
            [_finding(f"apps/{PROBE_APP}/services.py", f"{PROBE_APP}.role-value")],
            f"apps/{PROBE_APP} exists between `Plant.put` and `Plant.restore` and nowhere "
            "else; a recording for it names an app nobody can open",
        ),
        (
            "a class the product recorded at zero",
            _rule({f"{outsider}.read": 0}),
            [_finding(f"apps/{outsider}/selectors.py", f"{outsider}.read")],
            "a recorded 0 is a measurement somebody made; only an ABSENT entry is unmeasured",
        ),
    )
    for what, rule, findings, why in negatives:
        if _headers(rule, findings):
            broken.append(
                f"UNMEASURED-RATCHET FALSE POSITIVE — {what} was offered a recording line: {why}"
            )
        else:
            silent += 1

    say(
        f"ratchet census: {fired} of 1 canary forms fired · {silent} of 4 negatives stayed "
        "silent (a product app's class with no entry says how to record it; a template app, "
        "a non-app class, the plant scaffold and a class already recorded at zero say "
        "nothing)"
    )
    if fired != 1 or silent != 4:
        broken.append(
            f"RATCHET LEG SHORT — {fired} of 1 canary forms fired and {silent} of 4 "
            "negatives stayed silent; the lines above name which"
        )


@contextlib.contextmanager
def _as_product_tree(namespace: str, through: int) -> Iterator[None]:
    """Hold this process as if `rules.yaml` declared a product namespace.

    The wall's subject is `rules.yaml` DATA — two top-level keys and the id of
    every rule — so its canaries are rule-shaped and asserted directly, exactly
    as the residence census's are above. No file anywhere makes this tree a
    product tree, and a plant that tried would be proving something about a
    checkout nobody has.
    """
    global RULE_ID_NAMESPACE, TEMPLATE_IDS_THROUGH
    was = (RULE_ID_NAMESPACE, TEMPLATE_IDS_THROUGH)
    cached = dict(_OVERRIDE_RES)
    RULE_ID_NAMESPACE, TEMPLATE_IDS_THROUGH = namespace, through
    # The valve patterns are compiled FROM the declaration and cached per
    # comment token, so a swapped declaration with a warm cache would test the
    # template's regex and call it the product's.
    _OVERRIDE_RES.clear()
    try:
        yield
    finally:
        RULE_ID_NAMESPACE, TEMPLATE_IDS_THROUGH = was
        _OVERRIDE_RES.clear()
        _OVERRIDE_RES.update(cached)


def namespace_leg() -> None:
    """The id-grammar wall, and proof that every half of it can fail (ADR gate-5).

    FOUR CANARIES AND FOUR NEGATIVES, and the split is the point: the wall
    refuses three shapes and MUST NOT refuse the two that are legal, because a
    grammar that refused the template's own integers would take the whole rule
    set down and a grammar that refused nothing is the colliding tree this wall
    exists to end.
    """
    # -- the canaries: each of these must be refused ---------------------------
    if id_shape_problem("acme-1") is None:
        broken.append(
            "NAMESPACE CANARY DEAD — `acme-1` was accepted on a tree that declares no "
            "`rule_id_namespace`; a product id nothing claims must be refused"
        )
    with _as_product_tree("acme", 59):
        for probe, why in (
            ("60", "an integer above the template's recorded high-water"),
            ("other-2", "an id under a namespace this tree did not declare"),
            ("acme_3", "an id that is not `<ns>-<n>` at all"),
        ):
            problem = id_shape_problem(probe)
            if problem is None:
                broken.append(
                    f"NAMESPACE CANARY DEAD — {probe!r} ({why}) was accepted on a tree "
                    "declaring `rule_id_namespace: acme`"
                )
            elif "acme-<n>" not in problem:
                broken.append(
                    f"NAMESPACE CANARY MUTE — the refusal of {probe!r} does not name the "
                    f"grammar a reader has to write instead: {problem}"
                )
        # -- the negatives, INSIDE the product world -------------------------
        for legal in ("59", "1", "acme-1", "acme-204"):
            if id_shape_problem(legal) is not None:
                broken.append(
                    "NAMESPACE FALSE-POSITIVE REGRESSION — the legal id "
                    f"{legal!r} was refused on a tree declaring `rule_id_namespace: acme`"
                )
        if not override_re("#").search("# rule-acme-1: a product's own valve"):
            broken.append(
                "NAMESPACE CANARY DEAD — `# rule-acme-1:` is not a valve on a tree "
                "declaring `rule_id_namespace: acme`, so a product could not excuse its "
                "own rule anywhere"
            )
    if override_re("#").search("# rule-acme-1: a namespace this tree never claimed"):
        broken.append(
            "NAMESPACE FALSE-POSITIVE REGRESSION — `# rule-acme-1:` reads as a valve on a "
            "tree that declares no namespace, so a marker naming nothing would suppress"
        )

    # -- THE PRODUCT HALF OF THE RESIDENCE CENSUS (D4, and V-D's rider) -------
    #
    # `residence_findings` splits its census in two and counts the product's
    # members against ZERO — the branch that exists so a namespaced rule is
    # never hidden inside a backlog the template measured. Nothing planted it:
    # the template has no product rules, so on every real run that branch is
    # dead code with nobody watching it. The canary is a forged `acme-1` whose
    # whole canary plan lives in the one optional app, and the negative is the
    # same rule with one form outside it.
    optional_app = min(OPTIONAL_APPS) if OPTIONAL_APPS else None
    if optional_app is None:
        say(
            "rule ids: no app declares `optional = True` on this tree, so the product half "
            "of the residence census has no subject and its canary did not run."
        )
    else:
        whole = {
            "id": "acme-1",
            "canaries": [
                {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
                {
                    "fixture": "b.py",
                    "plant_at": f"apps/{optional_app}/services.py",
                    "mode": "append",
                },
            ],
        }
        lines = residence_findings([*RULES, whole])
        header = [
            line
            for line in lines
            if "1 product rule(s)" in line and "against a backlog of 0" in line
        ]
        named = [line for line in lines if "rule acme-1:" in line and optional_app in line]
        if not header or not named:
            broken.append(
                "PRODUCT-RESIDENCE CANARY DEAD — a product rule `acme-1` whose whole canary "
                f"plan plants into apps/{optional_app} did not produce the product census's "
                "own line (1 against 0) with the member named. The branch counts a "
                f"product's rules against zero and nothing else watches it: {lines}"
            )
        mixed = {
            "id": "acme-1",
            "canaries": [
                {"fixture": "a.py", "plant_at": f"apps/{optional_app}/models.py", "mode": "append"},
                {"fixture": "b.py", "plant_at": "apps/core/audit.py", "mode": "append"},
            ],
        }
        if [line for line in residence_findings([*RULES, mixed]) if "product rule(s)" in line]:
            broken.append(
                "PRODUCT-RESIDENCE FALSE-POSITIVE REGRESSION — a product rule with one canary "
                f"form outside apps/{optional_app} was counted into the product census"
            )

    # -- the fixture-directory census, against a tree it builds itself ---------
    scratch = Path(tempfile.mkdtemp(prefix="djb-nsdir-"))
    try:
        (scratch / "canary" / "1").mkdir(parents=True)
        (scratch / "canary" / "acme-1").mkdir()
        (scratch / "canary" / "other-9").mkdir()
        bases = (("canary", scratch / "canary"),)
        loud = fixture_dir_findings(bases, claimed={"1", "acme-1"}, namespace="acme")
        if not any("other-9" in line and "'other'" in line for line in loud):
            broken.append(
                "NAMESPACE CANARY DEAD — a fixture directory under a namespace the tree has "
                f"not claimed did not name it: {loud}"
            )
        quiet = fixture_dir_findings(bases, claimed={"1", "acme-1", "other-9"}, namespace="acme")
        if quiet:
            broken.append(
                "NAMESPACE FALSE-POSITIVE REGRESSION — fixture directories every rule claims "
                f"were reported anyway: {quiet}"
            )
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    if RULE_ID_NAMESPACE is None:
        highest = max((int(r["id"]) for r in RULES if is_template_id(str(r["id"]))), default=0)
        say(
            f"rule ids: template mode — {len(RULES)} rules, integers minted through {highest}. "
            f"A product folding this release records `rule_id_namespace: <ns>` and "
            f"`template_rule_ids_through: {highest}` (ADR gate-5)."
        )
    else:
        say(
            f"rule ids: product mode — namespace {RULE_ID_NAMESPACE!r}, the template's "
            f"integers recorded through {TEMPLATE_IDS_THROUGH}."
        )


# --- RULE 60's THIRD CLASS: one plant per drawer, through the drawer's own case
#
# WHAT CLASSES (a) AND (b) CANNOT SEE. Class (a) asks whether a product edited
# a template-owned file; class (b) asks whether every drawer this tree opens is
# written down with its reader and its case. Both are text. Neither can tell a
# drawer that WORKS from a drawer whose reader opens the directory, reads the
# members and throws them away — and that failure is silent in the worst
# direction: the product drops its leg in, the gate says nothing, and the leg
# never runs.
#
# SO THIS ONE RUNS THEM. Per live row of the `drawers` table, the case that row
# names is invoked — `<drive> --case <case>` for a shell drive, the node id for
# the one pytest drawer — and the case is the assertion. THAT IS THE WHOLE
# DESIGN: the case already plants one item and already asserts the reader ran
# it and named it, so a census that grepped the transcript for `local:<name>`
# would be a second, weaker opinion about a property the case owns. One reader
# per drawer, one case per drawer, and this leg is neither.
#
# WHY IT IS HERE AND NOT IN THE RULE'S CHECK. The cases cost tens of seconds;
# rule 60's check runs on every `--fast`, whose whole target is under a minute.
# The self-test is where the engine already pays for proof, and it is the one
# place that runs BEFORE the drives it invokes (`scripts/check.sh`'s selftest
# leg: "the engine's own `--selftest` runs first"), so a case cannot collide
# with the same drive running as a registered member beside it — two of them
# would refuse outright if it did (`test_gate_explain` will not overwrite an
# existing `quality/local/`, `test_sweep`'s scratch identity is derived per
# checkout).
#
# EXIT SEMANTICS, and they are the tree's and not the plan's letter. A case
# that RAN AND FAILED is a drawer whose reader did not take the plant: it is
# reported here, and `broken` makes it exit 2, because a drawer nobody can
# extend means the extension convention is not enforced for it — which is the
# definition of enforcement broken. A case that could not be RUN at all — no
# such drive, no such case, the drive itself exit 2 — is the same verdict by a
# different road and says which road it was.
#: How long the leg is allowed to take. The plan's ceiling (§ 7b X7.3), printed
#: against the measurement on every run so a case that grew is visible the run
#: it grew, rather than the release somebody times the gate.
DRAWERS_LEG_CEILING_S = 240


def drawer_case_problem(row: C.DrawerRow, timeout: int = 300) -> tuple[str, str]:
    """Run one row's case. `("", transcript)` when the drawer held.

    The victim is the case's own: every one of them builds its plant in a
    scratch directory or a clone and tears it down, which is the condition of
    being a registered drive here. This function creates nothing.
    """
    drive, _, case = row.case.partition("::")
    target = ROOT / drive
    if not case or not target.is_file():
        return (f"the case {row.case!r} is not a case in this tree", "")
    if drive.endswith(".py"):
        argv = ["uv", "run", "pytest", f"{drive}::{case}", "-p", "no:randomly", "-q"]
        held, held_what = (
            re.compile(r"^\s*\d+ (passed|subtests? passed)", re.M),
            "a `N passed` line",
        )
    else:
        argv = ["bash", drive, "--case", case]
        held, held_what = re.compile(r"^\s*ok\b", re.M), "an `ok` line"
    # THE OUTPUT GOES TO A FILE, NEVER A PIPE. Every drive here refuses a piped
    # stdout — the same guard the gate has, for the same reason — so
    # `capture_output=True` measures the refusal and not the drawer. Paid once,
    # by `test_divergence_census.sh` answering "this drive refuses pipes".
    try:
        with tempfile.NamedTemporaryFile("w+", prefix="djb-drawer-", suffix=".log") as sink:
            proc = subprocess.run(
                argv,
                cwd=ROOT,
                stdout=sink,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
            sink.flush()
            sink.seek(0)
            transcript = sink.read().rstrip()
    except subprocess.TimeoutExpired:
        return (f"the case did not finish inside {timeout}s", "")
    except OSError as error:  # a toolchain this checkout does not have
        return (f"the case could not be started — {error}", "")
    if proc.returncode == 2:
        return ("the case COULD NOT LOOK (exit 2) — it cleared nothing", transcript)
    if proc.returncode != 0:
        return (f"the case did not hold (exit {proc.returncode})", transcript)
    if not held.search(transcript):
        # A case that ran, said nothing and exited 0 has asserted nothing, and
        # is the one shape that reads exactly like a drawer that works.
        return (f"the case exited 0 and its transcript carries no {held_what}", transcript)
    return ("", transcript)


def drawers_leg() -> None:
    """Prove every drawer's reader really runs a planted item, and say what it cost."""
    doc = ROOT / C._DRAWERS_DOC
    if not doc.is_file():
        broken.append(
            f"DRAWERS CENSUS COULD NOT LOOK — {C._DRAWERS_DOC} is not in this tree, so "
            "there is no table of drawers to run. Rule 60's class (b) says the same "
            "thing about the same file; this leg proves nothing without it."
        )
        return
    rows, _bad = C.drawer_rows(doc.read_text())
    live = [row for row in rows if row.state == "live"]
    held = [row for row in rows if row.state == "held"]
    if not live:
        broken.append(
            "DRAWERS CENSUS HAS NO SUBJECT — the `drawers` table declares no live row, so "
            "this leg would pass by running nothing. Rule 60's `drawer_rows` floor is the "
            "other half of this sentence."
        )
        return

    started = time.time()
    ran = 0
    for row in live:
        why, transcript = drawer_case_problem(row)
        if why:
            broken.append(
                f"DRAWER BROKEN — `{row.drawer}` (reader `{row.reader}`): {why}. The case "
                f"`{row.case}` is what proves one planted item reaches that reader; a "
                "drawer whose reader does not run the plant is a seam a product drops a "
                "file into and never hears from again. Transcript:\n"
                + ("\n".join(f"      | {line}" for line in transcript.splitlines()[-12:]))
            )
            continue
        ran += 1
        say(f"  drawer {row.drawer}: {row.case.rpartition('::')[2]} held")

    # -- THE LEG'S OWN CANARY AND NEGATIVE, each building its own victim ------
    # The subject is `drawer_case_problem`, so the forms are ROWS handed to it
    # — the shape `residence_leg` and `namespace_leg` already use — and the
    # victim is a two-line script this leg writes and removes. A row pointing
    # at a real drive would be a canary about somebody else's case.
    canary_fired = 0
    negative_silent = 0
    with tempfile.TemporaryDirectory(prefix="djb-drawers-canary-") as scratch:
        red = Path(scratch) / "test_a_drawer_that_does_not_run_its_plant.sh"
        red.write_text(
            "#!/usr/bin/env bash\n"
            "# Planted by the drawers leg and removed in the same breath: the shape of a\n"
            "# reader that opened the drawer and did not run what was in it.\n"
            'echo "  FAILED   the drawer was opened and the plant never ran"\n'
            "exit 1\n"
        )
        green = Path(scratch) / "test_a_drawer_that_runs_its_plant.sh"
        green.write_text(
            "#!/usr/bin/env bash\n"
            'echo "  ok       the planted item reached the reader and was named"\n'
            "exit 0\n"
        )
        forms = (
            ("a case that did not hold", red, True),
            ("a case that held", green, False),
            (
                "a case this tree does not have",
                Path(scratch) / "test_nothing_here.sh",
                True,
            ),
        )
        for label, script, must_fire in forms:
            try:
                rel = str(script.relative_to(ROOT))
            except ValueError:
                # The scratch is outside the checkout (rung-execution §5), so the
                # row names it by absolute path — which `drawer_case_problem`
                # resolves through `ROOT /`, and an absolute path there is itself.
                rel = str(script)
            # THE FORGED DRAWER IS DELIBERATELY NOT DRAWER-SHAPED, and that
            # is the rule working on its own canary harness: class (b) derives
            # its population from the drawer paths the template's own code
            # SPELLS, so a realistic one written here — even inside a comment,
            # which the census reads exactly as it reads code — would be a
            # drawer this file opens with no row, a finding against the census
            # by the census. The drawer field is a label in the message; the
            # subject of these three forms is the case.
            forged = C.DrawerRow(
                0, "live", label, "scripts/forged-drawer.d/<n>.sh", "x::y", f"{rel}::case_x"
            )
            why, _ = drawer_case_problem(forged, timeout=30)
            if must_fire and why:
                canary_fired += 1
            elif must_fire:
                broken.append(
                    f"DRAWERS CANARY DEAD — {label} was handed to the drawer census and it "
                    "reported nothing. Every verdict this leg prints above is then a "
                    "verdict from a census that cannot fail."
                )
            elif why:
                broken.append(
                    f"DRAWERS FALSE-POSITIVE REGRESSION — {label} was reported as a broken "
                    f"drawer: {why}"
                )
            else:
                negative_silent += 1

    seconds = time.time() - started
    say(
        f"  drawers census: {ran} of {len(live)} live drawer(s) ran a planted item through "
        f"their own case · {len(held)} held (a reserved name, no reader by design) · "
        f"{canary_fired} of 2 canary forms fired · {negative_silent} of 1 negative stayed "
        f"silent · {seconds:.0f}s against a recorded ceiling of {DRAWERS_LEG_CEILING_S}s"
    )
    if canary_fired != 2 or negative_silent != 1:
        broken.append(
            f"DRAWERS LEG SHORT — {canary_fired} of 2 canary forms fired and "
            f"{negative_silent} of 1 negative stayed silent; the lines above name which"
        )
    if seconds > DRAWERS_LEG_CEILING_S:
        broken.append(
            f"DRAWERS CENSUS OVER ITS CEILING — {seconds:.0f}s against {DRAWERS_LEG_CEILING_S}s "
            "(plan P21 § TEAM F § 7b X7.3). A census nobody can afford is a census somebody "
            "turns off: run the cheapest case that proves discovery for the drawer that "
            "grew, or commit a higher ceiling in a diff a reviewer reads."
        )


def declaration_leg() -> None:
    """Prove the declaration's own censuses can fail, and say how many did.

    RULE-SHAPED AND FILE-SHAPED, because the subjects are of different kinds
    and a canary has to be planted through the mechanism the check really
    reads. The duplicate-id refusal's subject is `rules.yaml` data and the
    engine-fixture refusal's is a declaration in this module, so their forms
    are scratch data handed to the finding function — the shape `residence_leg`
    above already uses. The orphan census's subject is a FILE ON DISK, so its
    two forms are real files written into the real fixture trees and removed in
    a `finally`: a synthetic listing would have proved the arithmetic and left
    the walk itself able to go blind.

    Four forms, three negatives, each canary building its own victim. A form
    that does not fire is exit 2, never a pass.
    """
    fired = 0
    silent = 0

    # -- the duplicate id: it must fire, AND it must carry its remedy ----------
    # A refusal that fires with three words is the state this leg was written
    # against, so "did it fire" is not the whole question: the canary asserts
    # the parts of the remedy a reader acts on — both colliding entries, the
    # shared fixture directories, and which of the two is the one that moves.
    victim_id = str(RULES[0]["id"])
    dup = {
        "id": victim_id,
        "statement": "a scratch entry planted by the self-test to collide with a real id",
        "check": "zzz-declaration-canary",
    }
    dup_lines = duplicate_id_findings([*RULES, dup])
    if not dup_lines:
        broken.append(
            f"DUPLICATE-ID CANARY DEAD — a second entry declaring id {victim_id} did not "
            "raise a duplicate-id finding at all"
        )
    else:
        line = dup_lines[-1]
        wanted = (
            "THE COLLISION:",
            "REMEDY:",
            f"quality/canary/{victim_id}/",
            f"quality/negative/{victim_id}/",
            "rule_id_namespace",
            # THE CITE IS PART OF THE REMEDY, asserted so a later rewrite that
            # drops it goes red rather than quietly leaving a product to guess
            # where the grammar is written down (V-D1a rider).
            "ADR gate-5",
            "CHANGELOG",
        )
        absent = [w for w in wanted if w not in line]
        if absent:
            broken.append(
                f"DUPLICATE-ID CANARY MUTE — the refusal fired for id {victim_id} without "
                f"the part of its remedy a reader acts on: {', '.join(absent)} is not in the "
                "line. A duplicate id a product cannot act on is the state this remedy "
                "replaced"
            )
        else:
            fired += 1
    # THE NEGATIVE: an entry with an id nothing else holds is not a collision.
    fresh = dict(dup, id="zzz-declaration-negative")
    if duplicate_id_findings([*RULES, fresh]):
        broken.append(
            "DUPLICATE-ID FALSE-POSITIVE REGRESSION — an entry whose id no other entry "
            "holds was reported as a duplicate"
        )
    else:
        silent += 1

    # -- the orphan fixture: two forms, each a real file, each removed --------
    # Form one is the shape a fold produces: a file in a REAL rule's directory
    # that the rule's plan does not name. Form two is the directory half: a
    # fixture directory numbered for a rule that does not exist.
    real_dir = next(
        (NEGATIVE_DIR / str(r["id"]) for r in RULES if (NEGATIVE_DIR / str(r["id"])).is_dir()),
        None,
    )
    if real_dir is None:
        broken.append(
            "ORPHAN-FIXTURE CANARY COULD NOT RUN — no rule on this tree has a negative "
            "fixture directory, so the census has no real directory to be planted into"
        )
    else:
        forms = (
            real_dir / "zzz_orphan_canary.py",
            NEGATIVE_DIR / "zzz-no-such-rule" / "zzz_orphan_canary.py",
        )
        for victim in forms:
            made_dir = not victim.parent.is_dir()
            if made_dir:
                victim.parent.mkdir(parents=True)
            victim.write_text(
                "# planted by the self-test's declaration leg and removed in the same "
                "breath; a copy that outlived its run is the census working\n"
            )
            try:
                lines = orphan_fixture_findings(RULES, fixture_files_on_disk())
            finally:
                victim.unlink(missing_ok=True)
                if made_dir:
                    victim.parent.rmdir()
            rel = str(victim.relative_to(ROOT))
            if any(rel in line for line in lines):
                fired += 1
            else:
                broken.append(
                    f"ORPHAN-FIXTURE CANARY DEAD — {rel} was written into the fixture tree "
                    "and no entry of any rule claims it, and the census did not name it"
                )
    # -- the engine's own claims: a declared fixture the tree does not have --
    # The form that turned a real deletion into a FileNotFoundError halfway
    # through a self-test before this guard existed. The victim is a synthetic
    # declaration, never the real dict: deleting the real file to prove the
    # point would break the very leg the file exists for.
    absent = ROOT / "quality" / "negative" / "zzz-no-such-rule" / "zzz_never_written.js"
    if engine_fixture_findings({absent: "a scratch declaration planted by the self-test"}):
        fired += 1
    else:
        broken.append(
            f"ENGINE-FIXTURE CANARY DEAD — {absent.relative_to(ROOT)} is declared and is not "
            "on this tree, and the census did not say so"
        )
    if engine_fixture_findings(ENGINE_FIXTURES):
        broken.append(
            "ENGINE-FIXTURE REGRESSION — a fixture this module plants by path is missing "
            "from the tree; the lines from the consistency census above name it"
        )
    else:
        silent += 1

    # THE NEGATIVE, and it is the tree itself: at rest, after both plants were
    # removed, every file under the two fixture trees is claimed by an entry.
    # It is the restore-proof as well as the restraint-proof — a plant that
    # outlived its `finally` would show up here as a finding.
    at_rest = orphan_fixture_findings(RULES, fixture_files_on_disk())
    if at_rest:
        broken.append(
            "ORPHAN-FIXTURE FALSE-POSITIVE OR UNRESTORED PLANT — the tree at rest is not "
            "clean under the orphan census: " + " | ".join(at_rest)
        )
    else:
        silent += 1

    say(
        f"declaration census: {fired} of 4 canary forms fired · {silent} of 3 negatives "
        "stayed silent (duplicate id with its remedy; an unclaimed file in a real rule's "
        "directory; a fixture directory no rule is named for; an engine-planted fixture "
        "the tree does not have)"
    )
    if fired != 4 or silent != 3:
        broken.append(
            f"DECLARATION LEG SHORT — {fired} of 4 canary forms fired and {silent} of 3 "
            "negatives stayed silent; the lines above name which"
        )


# --- the seam's own canaries: a process boundary that cannot fail silently -------
#
# WHY THESE ARE NOT PLANTED FILES. Every other canary in this engine is a wrong
# file dropped into the real tree, because every other check's subject IS a
# file. The seam's subject is a RUNNER THAT WILL NOT ANSWER — missing, dead,
# slow, mute, lying, or reporting about somewhere it was never pointed — and no
# file anywhere makes a subprocess exit non-zero. So the forms are rules rather
# than fixtures, driven straight through `run_rule` so that the whole pipeline
# they must survive is the pipeline they are proved against, and they are
# counted against a recorded floor in `rules.yaml` exactly as a planted plan is.
#
# THE FAILURE MODE ALL OF THIS EXISTS TO REFUSE, said once: a runner that
# crashes, prints nothing and is read as zero findings. Every rule of a whole
# language then reports green from the day it is wired, and nothing on either
# side of the boundary can tell anybody. The list below is that sentence turned
# into a population a reader can count.

#: The seam's test double: one runner that emits a NAMED reply. One file rather
#: than fifteen, because the interesting thing about each form is the reply's
#: shape and a reader should be able to see all of them side by side.
SEAM_REPLIES = "quality/runners/fixtures/replies.py"


def _replies(name: str) -> list[str]:
    return ["python3", SEAM_REPLIES, name]


def _seam_rule(
    label: str,
    *,
    argv: list[str],
    roots: list[str],
    needs_tree: str | None = None,
    timeout: int | None = None,
    floors: dict | None = None,
) -> dict:
    """A synthetic rule for one seam form — inline kind, so no row is added to
    the population the self-test is measuring."""
    rule: dict = {
        "id": f"seam:{label}",
        "kind": {"roots": roots, "suffixes": [".py"], "comment": "#"},
        "runner": {"argv": argv} if timeout is None else {"argv": argv, "timeout": timeout},
    }
    if needs_tree is not None:
        rule["needs_tree"] = needs_tree
    if floors is not None:
        rule["floors"] = floors
    return rule


def _seam_probe(rule: dict, *, floors: bool = False) -> tuple[list[Finding], dict, str, list[str]]:
    """Run one synthetic rule and TAKE BACK whatever it appended to `broken`.

    The refusals these forms provoke are the proof, not the verdict: leaving
    them in `broken` would make a healthy seam exit 2 for demonstrating that it
    works. Removed by slice rather than by matching text, so a form that
    produced two refusals cannot leave one behind.
    """
    mark = len(broken)
    kept, targets, skip = run_rule(rule, floors=floors)
    produced = broken[mark:]
    del broken[mark:]
    return kept, targets, skip, produced


#: (label, the form, the refusal class its message must name). Each class is a
#: separate way to be unbelievable, and each one is here because reading it as
#: "clean" is a plausible mistake for an engine to make.
def _seam_canaries() -> list[tuple[str, dict, str]]:
    present = "quality"
    js_roots = ["quality"]
    nothing = "djb-no-such-instrument-on-this-box"
    return [
        # -- the runner will not run: three ways, and none of them is "clean" --
        ("runner-absent", _seam_rule("absent", argv=[nothing], roots=js_roots), "runner-absent"),
        (
            "runner-not-executable",
            _seam_rule("not-exec", argv=["quality/rules.yaml"], roots=js_roots),
            "runner-not-executable",
        ),
        # The POSIX always-fails program, resolved through PATH rather than
        # spelled as a path so that the form is about a runner that FAILS and
        # never accidentally about one that is missing on some other box.
        (
            "runner-failed",
            _seam_rule("failed", argv=["false"], roots=js_roots, needs_tree=present),
            "runner-failed",
        ),
        (
            "runner-timeout",
            _seam_rule(
                "timeout", argv=_replies("sleep"), roots=js_roots, needs_tree=present, timeout=1
            ),
            "runner-timeout",
        ),
        # -- the runner answers, and the answer cannot be believed ------------
        (
            "reply-not-json",
            _seam_rule("not-json", argv=_replies("not-json"), roots=js_roots, needs_tree=present),
            "reply-not-json",
        ),
        (
            "reply-not-an-object",
            _seam_rule(
                "not-object", argv=_replies("not-an-object"), roots=js_roots, needs_tree=present
            ),
            "reply-not-an-object",
        ),
        (
            "reply-wrong-protocol",
            _seam_rule(
                "wrong-protocol",
                argv=_replies("wrong-protocol"),
                roots=js_roots,
                needs_tree=present,
            ),
            "reply-wrong-protocol",
        ),
        (
            "reply-unknown-key",
            _seam_rule(
                "unknown-key", argv=_replies("unknown-key"), roots=js_roots, needs_tree=present
            ),
            "reply-unknown-key",
        ),
        (
            "findings-not-a-list",
            _seam_rule(
                "findings-scalar",
                argv=_replies("findings-not-a-list"),
                roots=js_roots,
                needs_tree=present,
            ),
            "findings-not-a-list",
        ),
        (
            "finding-not-an-object",
            _seam_rule(
                "finding-scalar",
                argv=_replies("finding-not-an-object"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-not-an-object",
        ),
        (
            "finding-missing-key",
            _seam_rule(
                "finding-missing",
                argv=_replies("finding-missing-key"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-missing-key",
        ),
        (
            "finding-unknown-key",
            _seam_rule(
                "finding-extra",
                argv=_replies("finding-unknown-key"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-unknown-key",
        ),
        (
            "finding-bad-type",
            _seam_rule(
                "finding-type",
                argv=_replies("finding-bad-type"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-bad-type",
        ),
        # A runner reporting about somewhere it was never pointed would move a
        # rule's subject without the rule changing.
        (
            "finding-outside-roots",
            _seam_rule(
                "outside",
                argv=_replies("finding-outside-roots"),
                roots=js_roots,
                needs_tree=present,
            ),
            "finding-outside-roots",
        ),
        # Targets feed the floors, and a floor fed a string counts nothing while
        # reporting something.
        (
            "targets-shape",
            _seam_rule(
                "targets", argv=_replies("targets-shape"), roots=js_roots, needs_tree=present
            ),
            "targets-shape",
        ),
        # -- the tri-state's refusing cell: a subject with no instrument ------
        (
            "tree-present-toolchain-absent",
            _seam_rule("cell-b", argv=[nothing], roots=js_roots, needs_tree=present),
            "IS on this tree and its instrument is not",
        ),
        # The same cell reached the other way. A toolchain is absent when the
        # PATH does not hold it AND when the file that is there cannot be run,
        # and a cell that only knew the first would let a chmod turn a rule off.
        (
            "tree-present-instrument-unrunnable",
            _seam_rule(
                "cell-b-twin", argv=["quality/rules.yaml"], roots=js_roots, needs_tree=present
            ),
            "exists and is not executable",
        ),
    ]


#: The stand-in cell-a uses to prove "an absent tree derives its floor to 0".
#: A LITERAL PRODUCT DIRECTORY NAME IS THE WRONG SHAPE HERE — this used to be
#: the literal "frontend", which was a legal stand-in for exactly as long as
#: no product tree by that name existed. The scaffold rung made `frontend/` a
#: real, tracked directory, and from that commit on cell-a stopped skipping:
#: `tree_verdict` saw a present tree, ran the canned-reply runner for real,
#: and its recorded floor of 150 fired UNBOUND against a canned
#: `files_scanned=3` — the check was never watching frontend at all (js_roots
#: stayed ["quality"]), but nothing told it the tree it was gating on had
#: stopped being absent. This name is synthetic and namespaced so nothing a
#: product grows can collide with it by accident; `seam_sentinel_census`
#: below proves that assumption on every run rather than trusting it forever,
#: which is the difference between fixing today's collision and fixing the
#: class of defect.
SEAM_ABSENT_TREE = "djb-no-such-tree-on-this-box"


def seam_leg() -> tuple[int, int]:
    """Fire every seam canary, hold every seam negative silent. (fired, silent)."""
    fired = 0
    silent = 0
    present, absent_tree = "quality", SEAM_ABSENT_TREE
    js_roots = ["quality"]

    for label, rule, wanted in _seam_canaries():
        kept, _targets, skip, produced = _seam_probe(rule)
        text = " ".join(produced)
        if wanted in text:
            fired += 1
        else:
            broken.append(
                f"SEAM CANARY DEAD — the {label} form did not refuse naming {wanted!r}. It "
                f"produced {produced!r} with {len(kept)} findings and skip={skip!r}; a runner "
                "this engine cannot believe must be could-not-look and never a clean scan"
            )

    # -- the negatives: the shapes the seam must ACCEPT ----------------------
    #
    # Without these the module above could pass every canary by refusing
    # everything, which is a protocol that reads nothing and a gate that can
    # never go green.
    accepted: list[tuple[str, dict, int, dict]] = [
        (
            "clean-reply",
            _seam_rule("clean", argv=_replies("clean"), roots=js_roots, needs_tree=present),
            0,
            {"files_scanned": 3},
        ),
        (
            "findings-inside-roots",
            _seam_rule("findings", argv=_replies("findings"), roots=js_roots, needs_tree=present),
            2,
            {"files_scanned": 2},
        ),
        # Line 0 is how this engine already spells "the file itself", and a
        # protocol that refused it would refuse half the findings it will carry.
        (
            "file-level-finding",
            _seam_rule("line-zero", argv=_replies("line-zero"), roots=js_roots, needs_tree=present),
            1,
            {"files_scanned": 1},
        ),
        # stderr is not the protocol. A runner that warns about a cache while
        # answering correctly has answered correctly.
        (
            "stderr-is-not-the-protocol",
            _seam_rule("stderr", argv=_replies("stderr-noise"), roots=js_roots, needs_tree=present),
            1,
            {"files_scanned": 1},
        ),
    ]
    for label, rule, want_findings, want_targets in accepted:
        kept, targets, skip, produced = _seam_probe(rule)
        if produced or skip or len(kept) != want_findings or targets != want_targets:
            broken.append(
                f"SEAM FALSE-POSITIVE REGRESSION — the {label} form is a legal check-v1 reply "
                f"and was not read as one: refusals={produced!r}, skip={skip!r}, "
                f"findings={len(kept)} (wanted {want_findings}), targets={targets!r} (wanted "
                f"{want_targets!r})"
            )
        else:
            silent += 1

    # The klass a runner declares must survive the boundary, because it is what
    # the engine's per-class ratchets are counted against: a klass dropped in
    # transit silently merges two backlogs into one.
    kept, _targets, _skip, produced = _seam_probe(
        _seam_rule("klass", argv=_replies("findings"), roots=js_roots, needs_tree=present)
    )
    if produced or sorted(f.klass for f in kept) != ["shape", "vocabulary"]:
        broken.append(
            "SEAM FALSE-POSITIVE REGRESSION — a runner's declared finding classes did not "
            f"survive the boundary: got {[f.klass for f in kept]!r}, wanted ['shape', "
            "'vocabulary']"
        )
    else:
        silent += 1

    # -- the tri-state's two silent cells ------------------------------------
    #
    # A SKIP THAT PRINTS NOTHING IS INDISTINGUISHABLE FROM A PASS, so the
    # sentence is asserted here and not merely the silence: the printed line is
    # the criterion, and a future edit that keeps the skip and drops the words
    # is exactly the regression this catches.
    _kept, targets, skip, produced = _seam_probe(
        _seam_rule(
            "cell-a",
            argv=_replies("clean"),
            roots=js_roots,
            needs_tree=absent_tree,
            floors={"files_scanned": 150},
        ),
        floors=True,
    )
    if produced or not skip.strip() or targets:
        broken.append(
            "SEAM TRI-STATE REGRESSION — a rule whose tree is not on this checkout did not "
            f"skip-and-say-so: refusals={produced!r}, sentence={skip!r}. A recorded floor of "
            "150 over an absent tree must derive to 0 rather than report UNBOUND"
        )
    else:
        silent += 1
    verdict, why = W.tree_verdict(
        ROOT,
        _seam_rule("cell-c", argv=_replies("clean"), roots=js_roots, needs_tree=present),
        SCOPE_KINDS,
    )
    if verdict != "run" or why:
        broken.append(
            f"SEAM TRI-STATE REGRESSION — a present tree with a present instrument gave "
            f"{verdict!r} ({why!r}) instead of running"
        )
    else:
        silent += 1

    silent += seam_valve_census()
    silent += seam_skip_dir_census()
    hygiene_fired, hygiene_silent = plant_hygiene_census()
    fired += hygiene_fired
    silent += hygiene_silent
    sentinel_fired, sentinel_silent = seam_sentinel_census()
    fired += sentinel_fired
    silent += sentinel_silent
    say(f"seam: {fired} runner-protocol canary forms refused · {silent} legal shapes accepted")
    return fired, silent


def seam_sentinel_census() -> tuple[int, int]:
    """Prove the tri-state's own 'absent tree' sentinel is actually absent. (fired, silent).

    THE DEFECT THIS EXISTS TO CATCH, NOT JUST TODAY'S INSTANCE OF IT. Cell-a's
    proof that "an absent tree derives its floor to 0" is only as honest as
    its stand-in tree genuinely being absent — `SEAM_ABSENT_TREE` replaces the
    literal "frontend", which was a legal choice for exactly as long as no
    product tree by that name existed, and stopped being one, silently, the
    moment the scaffold rung made `frontend/` real. A new synthetic name fixes
    that one collision; it does not fix the CLASS unless something checks,
    every run, that the name still holds no real tree. So: plant a directory
    at the sentinel path and prove the collision is caught loudly (fired);
    remove it and prove the ordinary, empty case stays silent (silent) — the
    same two-directions discipline as `plant_hygiene_census`, aimed at the
    premise a tri-state cell stands on rather than at the cell itself.
    """
    fired = 0
    silent = 0
    sentinel = ROOT / SEAM_ABSENT_TREE
    if sentinel.exists():
        broken.append(
            f"SEAM SELFTEST SENTINEL COLLISION — {SEAM_ABSENT_TREE!r} is meant to be a tree "
            "this checkout never has, and it already does, before the self-test planted "
            "anything. Cell-a's proof that an absent tree derives its floor to 0 needs a name "
            "nothing on the tree will ever hold — pick a different one rather than silently "
            "reading a present tree as though it were absent."
        )
        return fired, silent
    try:
        sentinel.mkdir()
        if (ROOT / SEAM_ABSENT_TREE).exists():
            fired += 1
        else:
            broken.append(
                "SEAM SENTINEL CANARY DEAD — a directory planted at the seam's own 'absent "
                f"tree' sentinel ({SEAM_ABSENT_TREE!r}) was not detected as present. If this "
                "check cannot see a real collision, cell-a can silently start scanning a real "
                "tree under that name exactly as it did for 'frontend' once."
            )
    finally:
        if sentinel.exists():
            sentinel.rmdir()
    if not (ROOT / SEAM_ABSENT_TREE).exists():
        silent += 1
    else:
        broken.append(
            f"SEAM SELFTEST SENTINEL COLLISION — {SEAM_ABSENT_TREE!r} was not restored "
            "cleanly after the plant; a later run reading it as absent would be wrong."
        )
    return fired, silent


def plant_hygiene_census() -> tuple[int, int]:
    """The two plant-path refusals, proved in both directions. (fired, silent).

    THE PAIR, and they are not the same question. One asks whether a plant path
    is DIRTY — the self-test's refusal, which exists because a run that cannot
    tell its plants from your work cannot restore honestly. The other asks
    whether a plant path IS A FIXTURE — the preflight, which exists because a
    run killed before its restore leaves the tree carrying wrongness that every
    later run reads as the product's own. A gate that had only the first would
    still go green over the residue of the run that died; a gate that had only
    the second would plant on top of somebody's uncommitted work.

    Driven from inside the self-test because that is the one place a plant can
    be held on purpose, and asserted in both directions because a refusal that
    fired on everything would refuse every ordinary working tree.
    """
    fired = 0
    silent = 0
    forms = [
        # A CREATED plant, standing where a dead run would have left it.
        ("50", NEGATIVE_DIR, RULES_BY_ID["50"]["negatives"][0]),
        # An APPENDED plant, which leaves a real tracked file with the fixture
        # on the end of it — a different residue and a different comparison.
        ("1", CANARY_DIR, RULES_BY_ID["1"]["canaries"][0]),
    ]
    for rid, base, entry in forms:
        plant = Plant()
        try:
            plant.put(base / rid / entry["fixture"], entry["plant_at"], entry["mode"])
            standing = [line for line in stale_plants() if entry["fixture"] in line]
            if standing:
                fired += 1
            else:
                broken.append(
                    f"STALE-PLANT CANARY DEAD — {entry['fixture']} was standing at "
                    f"{entry['plant_at']} ({entry['mode']}) and the preflight did not see it. "
                    "A run that dies before restore would then be measured as the product"
                )
            # The dirty-path half over the same held plant: whatever else it is,
            # a plant path carrying content git did not put there is a path this
            # engine must refuse to plant into.
            if any(str(entry["plant_at"]) in line for line in tree_dirty_under_plants()):
                fired += 1
            else:
                broken.append(
                    f"DIRTY-PLANT-PATH CANARY DEAD — {entry['plant_at']} was dirty and the "
                    "refusal did not see it. A self-test that cannot tell its own plants "
                    "from somebody's uncommitted work cannot restore honestly"
                )
        finally:
            plant.restore()
    # The restored tree is the negative for BOTH, and it is the assertion that
    # keeps either from being "any file under a plant path".
    residue = stale_plants() + tree_dirty_under_plants()
    if residue:
        broken.append(
            "PLANT-HYGIENE FALSE-POSITIVE REGRESSION — a restored tree was reported as "
            f"carrying residue: {residue}"
        )
    else:
        silent += 1
    return fired, silent


def seam_valve_census() -> int:
    """A valve written in a second language is suppressed AND counted. (1 or 0).

    THE HALF THAT IS EASY TO LOSE. Suppression alone is an off switch: the
    standing override section is the only thing that makes an exemption a
    decision somebody can read back, and a valve syntax the census walk does not
    know about is silently uncountable while still silently working. So the
    proving rule's own negative is planted and BOTH halves are asserted over the
    same file.
    """
    rid = "50"
    entries = [
        e
        for e in (RULES_BY_ID.get(rid, {}).get("negatives") or [])
        if "valve" in str(e.get("fixture", ""))
    ]
    if not entries:
        broken.append(
            f"SEAM VALVE CENSUS — rule {rid} has no valve negative to plant, so nothing "
            "proves a second language's exemption is counted rather than merely obeyed"
        )
        return 0
    entry = entries[0]
    plant = Plant()
    try:
        plant.put(
            fixture_home("negative", rid) / entry["fixture"], entry["plant_at"], entry["mode"]
        )
        rows = [row for row in all_overrides() if row[1] == str(entry["plant_at"])]
        if not rows:
            broken.append(
                "SEAM VALVE CENSUS — a `// rule-` valve planted at "
                f"{entry['plant_at']} is invisible to the standing override census. An "
                "exemption nobody counts is an off switch with extra steps"
            )
            return 0
        if rows[0][0] != rid or len(rows[0][3]) < MIN_REASON:
            broken.append(
                f"SEAM VALVE CENSUS — the planted valve was read as {rows[0]!r}, which is "
                f"not rule {rid} carrying a reason"
            )
            return 0
        return 1
    finally:
        plant.restore()


def seam_skip_dir_census() -> int:
    """A valve planted inside a kind's declared VENDORED directory stays OUT. (1 or 0).

    F1 (Vra, 2026-08-31). Before `quality/rules.yaml`'s `scope_kinds.js.skip_dirs`
    existed, `all_overrides()` skipped only `__pycache__` while the `js_secrets`
    runner carried its own separate `SKIP_DIRS` — two lists that disagreed, and
    a `// rule-` valve sitting inside a vendored `node_modules/` would have
    entered the standing override census exactly as a real one does. Planting
    one there and demanding it stay invisible to the census is the engine-side
    half of the fix; `quality/runners/js_secrets.py`'s own read of the identical
    declaration (`quality/runners/_kindscope.py`) is the runner-side half, and
    nothing here can see that half — only that both sides now consult one list.
    """
    target = "frontend/node_modules/some-pkg/index.js"
    plant = Plant()
    try:
        plant.put(VENDORED_VALVE_FIXTURE, target, "create")
        rows = [row for row in all_overrides() if row[1] == target]
        if rows:
            broken.append(
                "SEAM SKIP-DIR CENSUS — a `// rule-` valve planted inside "
                f"frontend/node_modules/ was counted in the standing override census: {rows!r}. "
                "A vendored directory must not enter the census any more than it enters a live "
                "scan"
            )
            return 0
        return 1
    finally:
        plant.restore()


def selftest() -> None:
    # Read the tree's migration leaves BEFORE anything is planted into it, and
    # stop if any placeholder could not be resolved: a self-test that guessed a
    # parent would be proving something about a graph it invented.
    prime_plant_resolution()
    if broken:
        return
    dirty = tree_dirty_under_plants()
    if dirty:
        broken.append(
            "selftest refused: the tree is dirty under plant paths — it could not tell "
            "its plants from your work, or restore honestly:\n  " + "\n  ".join(dirty)
        )
        return

    residence_leg()
    ratchet_leg()
    namespace_leg()
    declaration_leg()
    drawers_leg()

    fired = 0
    silent = 0
    seam_fired, seam_silent = seam_leg()
    seam_floor = {
        "canaries": int((SEAM.get("selftest_floor") or {}).get("canaries", 0)),
        "negatives": int((SEAM.get("selftest_floor") or {}).get("negatives", 0)),
    }
    for kind, got in (("canaries", seam_fired), ("negatives", seam_silent)):
        want = seam_floor[kind]
        if got < want:
            broken.append(
                f"seam: SELFTEST POPULATION SHORT — {got} of {want} recorded {kind}. Either a "
                "form stopped proving what it claims (the line above names it) or the plan "
                "lost one: the number lives in `seam.selftest_floor` and not in the length of "
                "the list, so a form deleted from the list cannot take its own expectation "
                "with it. Restore the form, or commit the lower number in a diff a reviewer "
                "reads"
            )
        elif got > want:
            say(
                f"  seam selftest: {kind} at {got} against a recorded {want} — a human may "
                "commit the higher number to quality/rules.yaml; nothing tightens by itself."
            )
    fired += seam_fired
    silent += seam_silent
    # : Per rule id: how many canary forms fired for IT, and how many of its
    # : negatives stayed silent. Attributed at the point of assertion, never
    # : divided out of a total afterwards.
    per_rule: dict[str, dict[str, int]] = {
        str(rule["id"]): {"canaries": 0, "negatives": 0}
        for rule in RULES
        if rule.get("enabled", True)
    }
    # : The forms this run did NOT plant because the app they need is not in
    # : this deployment. Counted per rule and per kind, printed on the
    # : rule's own line, and subtracted from its recorded population — a world
    # : that is smaller is not a plan that shrank.
    skipped: dict[str, dict[str, int]] = {rid: {"canaries": 0, "negatives": 0} for rid in per_rule}
    absent: dict[str, set[str]] = {rid: set() for rid in per_rule}

    # -- AST + diff canaries and negatives, one fixture at a time ---------------
    for rule in RULES:
        rid = str(rule["id"])
        if not rule.get("enabled", True):
            continue
        for entry in rule.get("canaries") or []:
            via = entry.get("via", "ast")
            gone = W.entry_out_of_world(entry, DISABLED_APPS)
            if gone:
                skipped[rid]["canaries"] += 1
                absent[rid].add(gone)
                continue
            if via == "django":
                continue  # batched probe runs below
            plant = Plant()
            try:
                home = fixture_home("canary", rid)
                plant.put(home / entry["fixture"], entry["plant_at"], entry["mode"])
                for extra in entry.get("extra_files") or []:
                    plant.put(home / extra["fixture"], extra["plant_at"], extra["mode"])
                if via == "diff":
                    result = C.diff_checks(ROOT, "HEAD", RULES_BY_ID).get(rid, CheckResult())
                    kept, _ = apply_overrides(rid, result.findings)
                else:
                    kept, _, _skip = run_rule(rule, floors=False)
                want = (entry.get("expect") or {}).get("contains")
                hit = any(
                    names_planted(f, resolve_plant_text(str(entry["plant_at"])))
                    and (not want or want in str(f))
                    for f in kept
                )
                if hit:
                    fired += 1
                    per_rule[rid]["canaries"] += 1
                else:
                    broken.append(
                        f"rule {rid}: CANARY DEAD — planted form {entry['fixture']} did not fire"
                    )
            finally:
                plant.restore()
        for entry in rule.get("negatives") or []:
            via = entry.get("via", "ast")
            gone = W.entry_out_of_world(entry, DISABLED_APPS)
            if gone:
                skipped[rid]["negatives"] += 1
                absent[rid].add(gone)
                continue
            if via == "django":
                continue
            plant = Plant()
            try:
                home = fixture_home("negative", rid)
                plant.put(home / entry["fixture"], entry["plant_at"], entry["mode"])
                for extra in entry.get("extra_files") or []:
                    plant.put(home / extra["fixture"], extra["plant_at"], extra["mode"])
                if via == "diff":
                    result = C.diff_checks(ROOT, "HEAD", RULES_BY_ID).get(rid, CheckResult())
                    kept, _ = apply_overrides(rid, result.findings)
                else:
                    kept, _, _skip = run_rule(rule, floors=False)
                # A negative fires when something in the output NAMES it. The
                # plant path is that signature for a one-file fixture; a
                # MULTI-FILE negative is not, because a finding about a relation
                # between three modules is pathed at whichever of them is wrong,
                # which need not be the one written as `plant_at`. Such a fixture
                # declares its own signature in `expect.contains` — the same
                # grammar the django probe uses — and the two are read together,
                # never one instead of the other.
                want = (entry.get("expect") or {}).get("contains")
                hits = [
                    f
                    for f in kept
                    if names_planted(f, resolve_plant_text(str(entry["plant_at"])))
                    or (want and want in str(f))
                ]
                if hits:
                    broken.append(
                        f"rule {rid}: FALSE-POSITIVE REGRESSION — negative {entry['fixture']} "
                        f"fired: {hits[0]}"
                    )
                else:
                    silent += 1
                    per_rule[rid]["negatives"] += 1
            finally:
                plant.restore()

    # -- the Django probe runs: all django canaries in one app, then negatives --
    #
    # One subprocess per corpus rather than one per fixture: each fixture is
    # still asserted individually (its expected id must fire naming its own
    # subject), and a probe app that fails to import fails EVERY assertion —
    # loudly, as exit 2 — rather than any canary quietly passing.
    for kind, is_canary in (("canaries", True), ("negatives", False)):
        entries: list[tuple[str, dict]] = []
        for rule in RULES:
            rid = str(rule["id"])
            if not rule.get("enabled", True):
                continue
            for entry in rule.get(kind) or []:
                if entry.get("via") != "django":
                    continue
                # Already counted as out-of-world in the AST loop above; the
                # two loops must agree about what this run's world holds or the
                # census would count the same form twice, once each way.
                if W.entry_out_of_world(entry, DISABLED_APPS):
                    continue
                entries.append((rid, entry))
        if not entries:
            continue
        plant = Plant()
        try:
            plant.scaffold_probe()
            for rid, entry in entries:
                home = fixture_home(kind, rid)
                plant.put(home / entry["fixture"], entry["plant_at"], entry["mode"])
                for extra in entry.get("extra_files") or []:
                    plant.put(home / extra["fixture"], extra["plant_at"], extra["mode"])
            env = dict(os.environ)
            env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
            proc = subprocess.run(
                [sys.executable, "manage.py", "check", "--tag", "djb"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            output = proc.stdout + proc.stderr
            error_lines = [ln for ln in output.splitlines() if "(djb." in ln]
            if is_canary:
                for rid, entry in entries:
                    expect = entry.get("expect") or {}
                    wanted_id, wanted_text = expect.get("id", ""), expect.get("contains", "")
                    hit = any(wanted_id in ln and wanted_text in ln for ln in error_lines)
                    if hit:
                        fired += 1
                        per_rule[rid]["canaries"] += 1
                    else:
                        broken.append(
                            f"rule {rid}: CANARY DEAD — django form {entry['fixture']} did not "
                            f"raise {wanted_id} naming {wanted_text!r}"
                        )
                if not error_lines:
                    broken.append(
                        "django canary probe produced no djb findings at all — output:\n"
                        + output.strip()[-2000:]
                    )
            else:
                # A negative is silent when nothing in the probe's output NAMES
                # it. The probe app is the signature for a fixture planted into
                # `apps/zzz_canary`; a fixture planted anywhere else names no
                # app at all, so it declares its own signature in
                # `expect.contains` — without one, a negative planted outside
                # the probe app could fire and be counted silent, which is a
                # regression corpus that cannot regress.
                ran = proc.returncode in (0, 1) and (proc.returncode == 0 or error_lines)
                for rid, entry in entries:
                    signature = (entry.get("expect") or {}).get("contains") or PROBE_APP
                    noisy = [ln for ln in error_lines if signature in ln]
                    if noisy:
                        for ln in noisy:
                            broken.append(
                                f"rule {rid}: FALSE-POSITIVE REGRESSION — the django negative "
                                f"{entry['fixture']} fired: {ln}"
                            )
                    elif ran:
                        silent += 1
                        per_rule[rid]["negatives"] += 1
                if not ran:
                    broken.append(
                        f"the django negative probe failed to run (exit {proc.returncode}):\n"
                        + output.strip()[-2000:]
                    )
        finally:
            plant.restore()

    # -- the budget mechanism's own canary: a ceiling below reality must fire ----
    measured = measure_budgets()
    section = "service_function_length"
    budget_canary = 0
    if measured[section]:
        key, value = next(iter(measured[section].items()))
        problems = check_budgets({section: {key: value - 1}})
        if any("grew" in p and key in p for p in problems):
            fired += 1
            budget_canary = 1
        else:
            broken.append("BUDGET CANARY DEAD — a ceiling below the measured value did not fire")

    leftover = tree_dirty_under_plants()
    if leftover:
        broken.append(
            "selftest left the tree dirty under plant paths — restore failed:\n  "
            + "\n  ".join(leftover)
        )

    # -- what each rule can show for itself -------------------------------
    #
    # One line per rule, and then the assertion the line exists for: a rule at
    # or above its recorded population passes and prints; one below it is exit
    # 2 NAMING THE RULE, whether its canaries failed to fire or stopped being
    # planted at all. The aggregate at the foot is what it always was, and it
    # is now the sum of things a reader can check individually.
    # : Kept local, not appended to the module-level `notes`: a self-test run
    # : accumulates every ratchet note from every planted tree, and printing
    # : those would bury the one thing this section exists to say.
    grown: list[str] = []
    say("selftest, by rule (fired/recorded · silent/recorded):")
    for rule in RULES:
        rid = str(rule["id"])
        name = rule.get("name", "")
        if not rule.get("enabled", True):
            say(f"  rule {rid} {name}: DISABLED — not planted")
            continue
        recorded = selftest_floor(rule)
        got = per_rule[rid]
        # THE ONLY LEGAL LOWERING, and it is paid for by a NAMED APP.
        # The recorded number in rules.yaml never moves — a reviewer still
        # reads the plan's full population in the diff — and what this run
        # expected falls by exactly the forms whose world this deployment does
        # not hold, with the app that took them printed on the same line. A
        # shrink nothing absent paid for is still POPULATION SHORT.
        floor = {k: max(0, recorded[k] - skipped[rid][k]) for k in ("canaries", "negatives")}
        status = (
            "ok"
            if got["canaries"] >= floor["canaries"] and got["negatives"] >= floor["negatives"]
            else "SHORT"
        )
        elsewhere = (
            ""
            if not absent[rid]
            else (
                f" · {skipped[rid]['canaries']}c/{skipped[rid]['negatives']}n not in this "
                f"world ({', '.join(sorted(absent[rid]))} disabled; recorded "
                f"{recorded['canaries']}/{recorded['negatives']})"
            )
        )
        say(
            f"  rule {rid} {name}: canaries {got['canaries']}/{floor['canaries']} · "
            f"negatives {got['negatives']}/{floor['negatives']} — {status}{elsewhere}"
        )
        for kind in ("canaries", "negatives"):
            if got[kind] < floor[kind]:
                broken.append(
                    f"rule {rid}: SELFTEST POPULATION SHORT — {got[kind]} of {floor[kind]} "
                    f"recorded {kind} were planted and proved. Either a form died (the line "
                    f"above it says which) or the plan lost one: a canary deleted from "
                    f"`canaries:` takes its own expectation with it, which is why the number "
                    f"lives in `selftest_floor` and not in the length of the list. Restore the "
                    f"form, or commit the lower number in a diff a reviewer reads"
                )
            elif got[kind] > floor[kind]:
                grown.append(
                    f"rule {rid} selftest: {kind} at {got[kind]} against a recorded "
                    f"{floor[kind]} — a human may commit the higher number to "
                    "quality/rules.yaml; nothing tightens by itself."
                )
    say(f"  budgets: canary {budget_canary}/1 — the mechanism's own, outside any rule")
    for note in grown:
        say(f"  {note}")
    # CANARY B.5-1, GENERALISED. A canary firing proves the rule can find its
    # subject; this proves the RED it would print is one a reader can act on.
    # Run over the rules whose canaries actually fired on THIS tree, so a rule
    # skipped for an absent world is not asked to explain a red it cannot
    # produce here.
    trailer_census([rid for rid, got in per_rule.items() if got["canaries"] > 0])
    cli_census()
    say(f"selftest: {fired} canary forms fired · {silent} negatives stayed silent · tree restored")


# --- main ------------------------------------------------------------------------


# --- the trailer: what a RED owes its reader ------------------------------------
#
# THE DEFECT (DX-ARCH #1; the consumer's ranked first cost). A finding
# printed `rule 13: apps/paper/services.py:42: <msg>` and stopped. Every other
# fact the rule DECLARES — where it is written down (`doc:`), how a legitimate
# exception is recorded (`valve:`), what it cannot see (`does_not_cover`) — sat
# in `rules.yaml` and reached nobody: `doc:` was read only by `consistency()`,
# and the valve grammar was prose in four different files. A reader holding a
# red had to find the rule in a 7,000-line yaml to learn what to do about it.
#
# THE FIX IS FOUR LINES, PRINTED ONCE PER RULE rather than once per finding: a
# rule with twelve findings owes its reader one trailer, not twelve.
#
# THE KEYS ARE ASCII AND THEY ARE THE CONTRACT. Drives
# assert `doc:`, `valve:`, `blind:`, `next:` and the marker text — never the
# `§` or `—` glyphs, which are prose and may be reworded without the meaning
# moving.
TRAILER_KEYS: tuple[str, ...] = ("doc:", "valve:", "blind:", "next:")

#: A budget violation has no rule id — `check_budgets` measures a recorded
#: number, not a declared rule — so it says where its number lives instead of
#: pretending to a `rules.yaml` entry it does not have.
BUDGET_TRAILER: list[str] = ["    doc:    — (a budget, not a rule; see quality/budgets.yaml)"]


def remedy_pointer(rid: str) -> str:
    """The tail a finding carries when its rule declares `remedies:` (ADR gate-6).

    A ratcheted rule's classes are the shapes it refuses, and each one has a
    FIX FORM — the spelling that makes the finding go away honestly. Those live
    in the rule's `remedies:` block, which `--explain` prints, and the finding
    itself carries the one-word route to them: a red that names its own reader
    is a red a builder can act on without going to look for the rule.
    """
    rule = RULES_BY_ID.get(rid) or {}
    if not rule.get("remedies"):
        return ""
    return f" · fix form: --explain {rid}"


#: The two files a RATCHET HEADER is pathed at. A header is not a valvable
#: finding — there is no comment you can write in a rules file to excuse a
#: backlog — so it must not contribute a valve token to its rule's trailer.
#: Before rules 50-53 declared their finding classes no js rule had a ratchet,
#: so no js rule had ever carried a yaml-pathed row; the day one did, rule 52's
#: block printed a `# rule-52:` line for findings that were all `.ts`, which is
#: precisely the defect `valve_lines`' per-finding-kind substitution exists to
#: prevent (found by `case_a_frontend_finding_prints_the_slash_valve_token`).
RATCHET_HEADER_PATHS: frozenset[str] = frozenset({"quality/rules.yaml", "quality/local/rules.yaml"})


def record_violation(rid: str, finding: object, *, path: str = "") -> None:
    """Append a finding AND remember whose it is, so the trailer can group."""
    text = f"rule {rid}: {finding}{remedy_pointer(rid)}"
    violations.append(text)
    violation_rule[text] = rid
    if path and str(path) not in RATCHET_HEADER_PATHS:
        token = W.comment_token(W.kind_of_path(path, SCOPE_KINDS))
        finding_kinds.setdefault(rid, set()).add(token)


def _first_sentence(text: object) -> str:
    """The first sentence of a declaration, flattened onto one line.

    `does_not_cover` and `statement` are paragraphs in the yaml; a trailer line
    and a listing row each want the opening claim. The whole of either is one
    `--explain` away, which is what the `next:` line is for.
    """
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    cut = flat.find(". ")
    return flat if cut < 0 else flat[: cut + 1]


def valve_lines(rule: dict, tokens: object = ()) -> list[str]:
    """The `valve:` half of a trailer — one line per comment token present.

    The marker a rule declares may carry `<comment>` where the file's own
    line-comment token belongs (the generic `<comment> rule-<id>: <reason>`
    override). It is substituted PER FINDING'S KIND, not per rule, so a rule
    that reported in a `.py` file and a `.ts` file prints both forms and each
    reader can paste the one their file speaks.
    """
    valve = rule.get("valve") or {}
    excuse = str(valve.get("none") or "").strip()
    if excuse:
        return [f"    valve:  none — {excuse}"]
    marker = str(valve.get("marker") or "").strip()
    where = str(valve.get("where") or "").strip()
    if not marker:
        return ["    valve:  (none declared — quality/rules.yaml has lost this rule's entry)"]
    present = sorted({str(t) for t in tokens}) or ["#"]
    out: list[str] = []
    for token in present:
        line = f"    valve:  {marker.replace('<comment>', token)} — {where} (counted and printed)"
        if line not in out:
            out.append(line)
    return out


def rule_trailer(rule: dict, tokens: object = ()) -> list[str]:
    """The four lines every RED carries, in reading order."""
    doc = rule.get("doc") or {}
    rid = str(rule["id"])
    lines = [f'    doc:    {doc.get("file", "—")} § "{doc.get("contains", "")}"']
    lines += valve_lines(rule, tokens)
    lines.append(f"    blind:  {_first_sentence(rule.get('does_not_cover'))}")
    lines.append(f"    next:   python -m quality.gate --explain {rid}")
    return lines


def trailer_for(rid: str) -> list[str]:
    """The trailer for a violation group — a rule's four lines, or the budget's."""
    rule = RULES_BY_ID.get(rid)
    if rule is None:
        return list(BUDGET_TRAILER)
    return rule_trailer(rule, finding_kinds.get(rid, set()))


def trailer_census(fired: object) -> None:
    """Every rule that just PROVED it can go RED must be able to explain itself.

    Canary B.5-1, generalised. A canary firing says the rule can find its
    subject; this says the finding it produces is actionable. A rule whose
    trailer has lost a key is exit 2 and not a quieter red, for the same reason
    a dead canary is: a red that cannot explain itself is broken enforcement,
    and the builder holding it is the last person who can tell.
    """
    checked = 0
    carried = 0
    for rid in sorted({str(r) for r in fired}, key=lambda r: (len(r), r)):
        rule = RULES_BY_ID.get(rid)
        if rule is None:
            continue
        checked += 1
        lines = rule_trailer(rule, ())
        whole = True
        for key in TRAILER_KEYS:
            filled = any(
                line.strip().startswith(key) and line.strip()[len(key) :].strip() for line in lines
            )
            if not filled:
                whole = False
                broken.append(
                    f"rule {rid}: RED WITHOUT A TRAILER — its canary fired, so this rule can go "
                    f"red on somebody's tree, and the block it would print carries no `{key}` "
                    "line. A red that cannot explain itself is broken enforcement"
                )
        carried += 1 if whole else 0
    # SAID OUT LOUD ON SUCCESS, in the seam and residence censuses' grammar. An
    # instrument that is silent when it passes is an instrument whose call can
    # be deleted without anything looking different — and this one runs over
    # every rule that just proved it can go red, which is the population nobody
    # would notice going quiet.
    if carried == checked:
        say(f"trailer census: {checked} rule(s) with findings, every one carried its four lines")
    else:
        say(f"trailer census: {carried} of {checked} rule(s) with findings carried four lines")


# --- the two readers: --explain <id>, and the listing ---------------------------
#
# Both read `RULES` — the parsed yaml, in the tree's own order — and never a
# second file. `--rules` is the LISTING's other name — the seam the derived
# rule list in the working guide reads: two readers do not both invent a
# printer for one question, so the alias is `cmp`-identical output rather than
# a second implementation.


def rules_listing() -> int:
    """`id  name  first sentence`, one line per rule. Disabled rules marked."""
    for rule in RULES:
        rid = str(rule["id"])
        name = str(rule.get("name", ""))
        # `[local]` is the drawer's tag and it is printed by BOTH readers: a
        # reader holding a red has to be able to tell whose rule refused them,
        # because the remedy differs (a template rule is the template's to
        # argue with; a drawer rule is the product's own). On a tree with no
        # drawer no line carries it, which is what makes the absent-drawer
        # negative a byte-identical `cmp`.
        mark = "  [local]" if is_local_rule(rid) else ""
        mark += "" if rule.get("enabled", True) else "  [DISABLED]"
        say(f"{rid:>3}  {name:<44}  {_first_sentence(rule.get('statement'))}{mark}")
    return 0


def explain(rid: str) -> int:
    """One rule's whole declaration, in reading order. Unknown id → exit 2."""
    rule = RULES_BY_ID.get(rid)
    if rule is None:
        say(
            f"‼ unknown rule id {rid!r}: `python -m quality.gate --explain` with no id prints "
            "the listing of every rule this tree holds"
        )
        return 2
    enabled = "enabled" if rule.get("enabled", True) else "DISABLED"
    home = " · [local]" if is_local_rule(rid) else ""
    say(f"rule {rid} · {rule.get('name', '')} · {enabled}{home}")
    if home:
        say(
            "  home: quality/local/rules.yaml — this product's drawer; its fixtures are "
            f"under quality/local/{{canary,negative}}/{rid}/"
        )
    if not rule.get("enabled", True):
        say(f"  disabled_reason: {rule.get('disabled_reason', 'no reason recorded')}")
    say("")
    say("statement:")
    say(f"  {' '.join(str(rule.get('statement', '')).split())}")
    say("")
    say("mechanism:")
    for key in ("check", "django_check_ids", "diff", "runner"):
        if rule.get(key):
            say(f"  {key}: {rule[key]}")
    say("")
    doc = rule.get("doc") or {}
    say(f'doc:    {doc.get("file", "—")} § "{doc.get("contains", "")}"')
    for line in valve_lines(rule, ()):
        say(line.strip())
    say("")
    say(f"floors: {rule.get('floors') or {}}")
    if rule.get("ratchets"):
        say(f"ratchets: {rule['ratchets']}")
    # ONE LINE PER FINDING CLASS, and each one is a fix form rather than a
    # restatement of the rule (ADR gate-6). `*` is the catch-all a rule whose
    # classes are per-app declares: one remedy, every class.
    for klass, text in (rule.get("remedies") or {}).items():
        say(f"remedies: {klass} — {' '.join(str(text).split())}")
    say("")
    say("does_not_cover:")
    say(f"  {' '.join(str(rule.get('does_not_cover', '')).split())}")
    say("")
    say("canaries:")
    for entry in rule.get("canaries") or []:
        say(f"  {entry.get('fixture')} → {entry.get('plant_at')} ({entry.get('via', 'ast')})")
    say("negatives:")
    for entry in rule.get("negatives") or []:
        say(f"  {entry.get('fixture')} → {entry.get('plant_at')} ({entry.get('via', 'ast')})")
    # --- THE CENSUS (C0's seam) -------------------------------------------
    #
    # Everything above this line is the rule's DECLARATION: what it says, where
    # it is written down, how an exception is recorded, what it cannot see. All
    # of it is true of an empty checkout. A rule may also declare `census:` — a
    # dotted path to a callable this reader runs over THIS TREE — so that
    # `--explain <id>` can answer "and what does that mean here, right now?"
    # without a second reader, a second walker or a management command. Rule
    # 59's census is the worked example: its third class prints one draft
    # `EVENT_KINDS` line per undecided noun, scattered through a gate's output;
    # the census is the block each `events.py` actually needs, grouped by app.
    #
    # THREE FAILURES, THREE DIFFERENT ANSWERS, none of them a crash:
    #   no `census:` key      nothing printed at all — every rule that came
    #                         before this seam explains byte-identically
    #   unresolvable          EXIT 2, naming the dotted path. A declaration
    #                         pointing at a callable that is not there is
    #                         broken enforcement, and 2 outranks a pass.
    #   the callable RAISES   a `could not look:` line naming the exception,
    #                         and the rest of the explanation still prints. A
    #                         reader that dies on a tree its census stumbled on
    #                         takes the declaration down with it, and the
    #                         declaration is the part that is always true.
    census = rule.get("census")
    if census:
        import importlib

        dotted = str(census)
        module_name, _, attr = dotted.rpartition(".")
        problem = ""
        fn = None
        if not module_name or not attr:
            problem = "it is not a dotted path to a callable (want `package.module.name`)"
        else:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:  # noqa: BLE001 — any import failure is the same verdict
                problem = f"{module_name} would not import: {type(exc).__name__}: {exc}"
            else:
                fn = getattr(module, attr, None)
                if fn is None:
                    problem = f"{module_name} has no attribute {attr!r}"
                elif not callable(fn):
                    problem = f"{module_name}.{attr} is a {type(fn).__name__}, not a callable"
        if problem:
            say("")
            say(f"‼ rule {rid}: census {dotted!r} does not resolve — {problem}")
            return 2
        say("")
        say("census (this tree):")
        try:
            lines = list(fn(ROOT, rule))
        except Exception as exc:  # noqa: BLE001 — a stumbling census reports, never crashes
            say(f"  could not look: {dotted} raised {type(exc).__name__}: {exc}")
        else:
            for line in lines:
                say(f"  {line}")
            if not lines:
                say("  nothing to report on this tree")
    say("")
    say(f"selftest_floor: {rule.get('selftest_floor') or {}}")
    return 0


# --- the third reader: --selftest-inputs ---------------------------------------
#
# WHAT IT ANSWERS. "Which bytes on this tree can change the engine's verdict?"
# Nobody could answer it before, which is why the house-rules leg re-measured on
# every rung: a verdict that cannot name its inputs cannot be banked against
# them, so it was banked against nothing and paid for in full, every time.
#
# DERIVED, NEVER TYPED — the same discipline `scope:` itself carries. The list
# is six populations, each read from something that already exists:
#
#   1. the engine's own text          `git ls-files -- quality`
#   2. every enabled rule's scope     `_scope_paths()`, the SAME walker
#                                     `consistency()` uses to refuse a scope
#                                     naming a file that is not there
#   3. every path a plant can touch   `plant_paths()`, already resolved
#   4. the reads the engine SPELLS    the tuple below, and only those
#   5. every enabled rule's DOC       `doc.file` — `consistency()` reads the
#                                     anchor out of it on every run
#   6. THE WALK                       `_kind_walk()` over the tracked set —
#                                     `SCOPE_KINDS`' roots and suffixes, the
#                                     files the live checks actually read
#
# 5 AND 6 WERE MISSING FROM THE FIRST CUT, and the verifier proved it with two
# plants that each moved the engine's verdict while the listing stayed
# byte-identical: a mangled anchor in `docs/product/architecture.md` (exit 2,
# `rule 9: doc … no longer states the rule`) and an `httpx` import in
# `apps/core/workflows.py` (exit 1, `rule 9: apps/core/workflows.py:160`). The
# lesson is the one this section is now shaped around: **`scope:` is an
# ALLOW-LIST OVER THE WALK, NOT THE WALK.** A rule that names no exemption reads
# the whole of `apps/**/*.py` and contributes nothing to population 2.
#
# Population 4 is the one hand list, and it is hand-written because the thing it
# describes is hand-written: a `ROOT.glob(...)` in this module's own source. It
# is the declared blind spot rather than a hidden one — a check that grows a
# fifth read and does not join it here keys a verdict that cannot see its own
# input. The docstring below states it, and the mitigation is structural
# rather than hopeful: every one of those reads lives in `quality/`, so
# population 1 re-keys the moment somebody writes one.
#
# EXIT 2, NEVER A SHORTER LIST. Every failure here is could-not-look. A scope
# that expands to nothing, a `git` that would not answer, an unresolved plant
# placeholder: each of them would silently REMOVE inputs from the list, and a
# key computed over a list that quietly lost a member is a key that reuses a
# verdict for a tree it never saw. So a derivation that fails prints the rule id
# and the path it could not derive, prints NO paths at all, and exits 2.

#: Every path this module reads that no rule's `scope:` and no plant names —
#: the engine's hard-coded reads, each beside the line that makes it. A glob
#: here MUST expand to something on this tree; a plain path must exist.
HARDCODED_READS: tuple[tuple[str, str], ...] = (
    ("apps/*/services.py", "_measure_budgets_detailed: the service-length budget"),
    ("apps/*/schemas.py", "_measure_budgets_detailed: the Out-schema field budget"),
    ("apps/core/checks.py", "consistency: every rule's django_check_ids must be present"),
    ("quality/budgets.yaml", "BUDGETS_PATH: the recorded ceilings"),
    # THE DRAWERS LEG RUNS THE CASE EVERY `drawers` ROW NAMES, so the drives
    # holding those cases are inputs to this engine's verdict exactly as a
    # rule's scope is. Declared as the two DIRECTORIES rather than as the ten
    # files, because the rows move: a row repointed at another drive in
    # `scripts/tests/` would otherwise key the verdict on bytes nobody
    # measured, and the collapse is honest here because the leg really can run
    # any member of them.
    ("scripts/tests", "drawers_leg: the shell case each `drawers` row names"),
    ("apps/core/tests/test_conftest_local.py", "drawers_leg: the fixtures drawer's case"),
)

_GLOB_META = "*?["


def _tracked_paths() -> tuple[frozenset[str], str]:
    """Every path git has under version control here — and why it could not answer."""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z", "--cached"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return frozenset(), (
            f"could not read the tracked set: `git ls-files` exited {proc.returncode} — "
            f"{proc.stderr.strip() or 'no stderr'}"
        )
    return frozenset(p for p in proc.stdout.split("\0") if p), ""


def _expand_input(value: str, tracked: frozenset[str]) -> tuple[list[str], str]:
    """One declared read, expanded to the paths it names on THIS tree.

    A directory becomes the tracked files under it — a scope naming
    `apps/comms/` is a statement about the code in there, so a byte changing in
    any of it changes what the engine read. Tracked rather than walked: a walk
    would carry `__pycache__` into a list whose whole purpose is to be stable.
    """
    value = value.strip().rstrip("/")
    if not value:
        return [], "names the empty path"
    if any(ch in value for ch in _GLOB_META):
        matched = sorted(str(p.relative_to(ROOT)) for p in ROOT.glob(value))
        if not matched:
            return [], f"names {value!r}, which expands to nothing on this tree"
        out: list[str] = []
        for m in matched:
            if (ROOT / m).is_dir():
                under = [p for p in tracked if p == m or p.startswith(m + "/")]
                if not under:
                    return [], f"names {value!r}, whose match {m!r} holds no tracked file"
                out.extend(under)
            else:
                out.append(m)
        return sorted(set(out)), ""
    target = ROOT / value
    if target.is_dir():
        under = sorted(p for p in tracked if p.startswith(value + "/"))
        if not under:
            return [], f"names the directory {value!r}, which holds no tracked file"
        return under, ""
    if target.exists():
        # A FILE, AND THE TRACKED RULE APPLIES TO IT TOO. Every other branch
        # here answers out of `tracked`; this one used to answer out of the
        # filesystem, so an untracked file entered a list whose whole purpose
        # is to be the repository's own answer about what was read.
        if value not in tracked:
            return [], (
                f"names {value!r}, which git does not carry — the input list is the "
                "repository's own answer about what was read, and an untracked file in it "
                "is a byte that moves the verdict without moving the key"
            )
        return [value], ""
    return [], f"names {value!r}, which does not exist on this tree"


def selftest_inputs_for(rules: list[dict]) -> tuple[list[str], list[str]]:
    """(the sorted input paths, the derivations that failed).

    Takes the rule list rather than reading `RULES`, so a canary can hand it a
    scratch rule whose scope names nothing and watch it refuse — the victim is
    created by the probe rather than found on the tree (rung-execution §2).

    **does_not_cover:** a read this module SPELLS and `HARDCODED_READS` does not
    carry (population 4 above); an untracked file anywhere — inside a scope
    directory or inside the walk (the tracked set is the repository's own answer
    about what is in there, and it is what keeps the list byte-stable); a
    runner subprocess that reads outside its kind's declared roots
    (`quality/runners/` mirrors `SCOPE_KINDS`, and a runner that walked
    somewhere else would be a defect that rule's own drive owes); what a check
    does with a path once it has read it. PATHS, NEVER BYTES: a byte changing
    inside a listed file does not move this list — it is the key computed OVER
    the list — the caller that banks a verdict on it — that hashes content.
    """
    tracked, trouble = _tracked_paths()
    if trouble:
        return [], [trouble]

    problems: list[str] = []
    paths: set[str] = set()

    # 1. the engine's own text.
    under_quality = sorted(p for p in tracked if p.startswith("quality/"))
    if not under_quality:
        problems.append(
            "no tracked path under quality/ — the engine cannot be reading none of itself, "
            "so this is a checkout `git ls-files` answered about something else"
        )
    paths.update(under_quality)

    # 2. every enabled rule's scope, through the walker consistency() already uses.
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rid = str(rule.get("id", "?"))
        for trail, value in _scope_paths(rule.get("scope") or {}):
            found, why = _expand_input(value, tracked)
            if why:
                problems.append(f"rule {rid}: scope {trail} {why}")
                continue
            paths.update(found)

    # 3. every path a plant can touch. `plant_paths()` resolves its placeholders
    #    against today's tree and reports an unresolvable one by appending to
    #    `broken` — which here is could-not-look, not a line to print.
    before = len(broken)
    planted = plant_paths()
    problems.extend(broken[before:])
    del broken[before:]
    for p in planted:
        if "{{" in p:
            problems.append(f"plant path {p!r} still carries an unresolved placeholder")
            continue
        paths.add(p)
    # The probe app is a directory this engine CREATES and removes; it is a read
    # of the tree either way, and its absence is never a derivation failure.
    paths.add(f"apps/{PROBE_APP}")

    # 4. the reads this module spells.
    for value, why_read in HARDCODED_READS:
        found, why = _expand_input(value, tracked)
        if why:
            problems.append(f"hard-coded read ({why_read}) {why}")
            continue
        paths.update(found)

    # 5. every enabled rule's DOC. `consistency()` reads the anchor text out of
    #    that file and refuses the rule when the prose no longer states it, so a
    #    rule's documentation is an input to the verdict exactly as its scope is
    #    — derived from `doc.file`, the same way population 2 is derived from
    #    `scope:`. A rule with no doc file is could-not-look: the check that
    #    reads it is unconditional, so the path it would read cannot be unknown.
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        rid = str(rule.get("id", "?"))
        doc_file = str((rule.get("doc") or {}).get("file") or "").strip()
        if not doc_file:
            problems.append(
                f"rule {rid}: doc names no file, so the anchor consistency() reads on every "
                "run cannot be derived"
            )
            continue
        found, why = _expand_input(doc_file, tracked)
        if why:
            problems.append(f"rule {rid}: doc {why}")
            continue
        paths.update(found)

    # 6. THE WALK ITSELF — the population every live check reads, and the one a
    #    scope-shaped derivation cannot see. `scope:` is an ALLOW-LIST over the
    #    walk, not the walk: rule 9 reads every `apps/**/*.py` and names none of
    #    them, so a violation planted in `apps/core/workflows.py` moves the
    #    verdict while a scopes-and-plants listing stays byte-identical. Derived
    #    from `_kind_walk()` — the same (root, suffix, skip_dirs) triples
    #    `all_overrides()` walks — intersected with the tracked set, per the
    #    tracked-files rule `_expand_input` already declares.
    #
    #    A root that is not on this checkout contributes nothing and says
    #    nothing, which is `all_overrides()`'s own rule for the same triple. A
    #    root that IS here and contributes no tracked file across ANY of its
    #    kind's suffixes is could-not-look: the walk emptied, and an empty walk
    #    is how every rule of that kind goes quietly green.
    walked_per_root: dict[str, int] = {}
    for root, suffix, skip in _kind_walk():
        if not (ROOT / root).exists():
            continue
        walked_per_root.setdefault(root, 0)
        # A FILE ROOT IS ITS OWN WALK — the fourth reader of that rule, and the
        # one a drawer kind rooted at `.env.example` reached first: a prefix
        # test spelled `root + "/"` matches nothing for a file, the count stays
        # 0, and this census refuses a root that is exactly where it said it
        # would be. The suffix filter does not apply for the same reason it does
        # not in `all_overrides()` and `_kind_walk()`: a suffix filter over ONE
        # named path is a second opinion about a file somebody declared.
        if (ROOT / root).is_file():
            if root in tracked:
                paths.add(root)
                walked_per_root[root] += 1
            continue
        for p in tracked:
            if not p.startswith(root + "/") or not p.endswith(suffix):
                continue
            if skip & set(Path(p).parts):
                continue
            paths.add(p)
            walked_per_root[root] += 1
    for root, count in sorted(walked_per_root.items()):
        if count == 0:
            problems.append(
                f"scope-kind root {root!r} is on this tree and holds no tracked file of any "
                "suffix its kind declares — the walk every live check of that kind reads has "
                "emptied, which is how a rule goes green over nothing"
            )

    if problems:
        return [], problems
    return sorted(paths), []


def selftest_inputs() -> int:
    """Print the engine's inputs, one per line. Any failed derivation → exit 2."""
    paths, problems = selftest_inputs_for(RULES)
    if problems:
        say(
            "‼ --selftest-inputs COULD NOT LOOK (exit 2). A list that quietly lost a member "
            "would key a verdict for a tree nobody measured, so nothing is printed:"
        )
        for p in problems:
            say(f"  !! {p}")
        return 2
    for path in paths:
        say(path)
    return 0


# --- the fourth reader: --fold-map ----------------------------------------------
#
# THE SUBJECT (HOTFIX-RULEMAP-1, the first consumer's fold of 2.1.1). Item 7 of
# that release tells a product to "rename YOUR OWN rules to `<ns>-<n>`" and
# hands it no instrument for deciding WHICH rules are its own. The first
# consumer's ids had drifted across two adoptions: four TEMPLATE rules were
# being carried at numbers the template gives four other rules, and they went
# into the product's drawer as `<ns>-58..61` before anybody noticed. Both
# directions of that mistake are silent:
#
#   a TEMPLATE rule parked under a product namespace STOPS BEING FOLDED — the
#   next release improves the template's copy and the product keeps the old
#   one, under a name nothing will ever reconcile;
#   a PRODUCT rule left on a template integer COLLIDES AGAIN at the next
#   release, which is the whole defect ADR gate-5 exists to end.
#
# THE MATCHING KEY IS THE NAME, NEVER THE NUMBER. The number is precisely the
# thing that drifted, so a map built on it would agree with the mistake. Every
# rule carries an `id`-adjacent `name:` (`quality/rules.yaml` § the schema), and
# a rule with no name is exit 2 rather than a rule this reader silently skips.
#
# WHAT IT READS. Two files: the product's PREVIOUS `quality/rules.yaml` — the
# one before the merge, which a product gets with
# `git show <their pre-merge sha>:quality/rules.yaml` — and the TEMPLATE's
# current one on this tree. The drawer (`quality/local/rules.yaml`) contributes
# the namespace a product block is spelled with, and nothing else.
#
# WHICH FILE IS THE TEMPLATE SIDE (HOTFIX-RULEMAP-2, the same consumer, one
# release later). The sentence above — "the TEMPLATE's current one on this
# tree" — was the defect, and it was a defect IN THE WRONG DIRECTION: CHANGELOG
# § [2.1.2] item 2 sent a product here AFTER `git merge`, and on that tree
# `quality/rules.yaml` is THE MERGE RESULT — the product's names at the
# product's numbers — not the release's. Measured on the consumer's own
# worktree, same previous file: the merged file as the template side printed
# `unchanged; nothing to renumber` for rule after rule at exit 0, UNMATCHED
# empty, a map with nothing to do; the RELEASE's own file printed twelve
# renames and twenty-seven fixture findings. NOTHING IN THE OUTPUT
# DISTINGUISHED THE TWO. So:
#
#   the template side is an argument — `--fold-map <previous> [<template>]` —
#   and the header line NAMES THE PATH it used and whether it was given;
#   with no second argument the tree's file is used as before, and TWO TEETH
#   refuse (exit 2) the states in which that file is not a release file;
#   the fixture BYTES are a third road, `--template-tree <dir>`, because a
#   rules.yaml alone cannot carry them — and without it the FIXTURES section
#   SAYS IN ITS OWN HEADER that it is a lower bound.
#
# THE TEETH, AND WHY NEITHER IS "THE SAME NAME AT A DIFFERENT NUMBER". That
# predicate is the healthy case — a template rule at a drifted number IS a
# shared name at two ids, and refusing it would refuse the two-argument road
# this hotfix exists to open. And the consumer's own measured run had NO such
# pair: every shared name sat at the same id (those were the `unchanged` lines)
# and the rest were absent from the merged file altogether. So the tooth is the
# whole comparison, not one half of it:
#
#   TOOTH A — the tree's `quality/rules.yaml` is not the SAME RULE SET as the
#   previous file: some name at a different id, a name in one and not the
#   other, either direction. A pre-merge tree passes it because there the two
#   files ARE the same file (which is also the template's own steady state, and
#   the one-argument form's only honest use); a merged tree never does, because
#   a merge that changed nothing is a fold with nothing to map.
#   TOOTH B — `quality/local/rules.yaml` already carries a rule under the
#   namespace whose NAME still sits in the template side at a bare integer: a
#   rule the product namespaced that is the template's after all. Not the same
#   predicate as A (its input is the drawer, not the previous file) and it
#   fires where A is silent, so it is a second clause of one function rather
#   than a second function.
#
# THE FIFTH PLACE. Item 7 names four places a rule id is written: the id, the
# fixture directory, the valve and the check tag. There is a FIFTH, and it is
# the one a renumber reds on: a rule declaring `django_check_ids:` has that id
# REGISTERED in `apps/core/checks.py`, and `consistency()` refuses a declared id
# the file does not carry ("django check id … not present in …"). So the map
# prints it as a place, per rule, out of the rule's own declaration rather than
# out of a guess about the letter or the width.
#
# THE FIXTURE CLASS IS WIDER THAN "THE SAME ID". `quality/negative/50/vendored_valve.js`
# rode into the first consumer's drawer as `…/<ns>-58/vendored_valve.js`: the
# file moved between DIFFERENT numbers, so an id-keyed census cannot see it. The
# FIXTURES section is therefore keyed on CONTENT — every fixture file on this
# tree whose bytes the template ships anywhere under
# `quality/{canary,negative}/`, at any id, printed with the template path it
# belongs at.


def _fold_map_rules(path: Path) -> tuple[list[dict], str]:
    """The `rules:` list in a rules.yaml, or the reason nobody can read it.

    Could-not-look is a STRING here rather than an exception for the same
    reason every other reader refuses rather than raises: a traceback out of a
    reader takes the reader down with it, and this one runs on a tree in the
    middle of a merge — the most broken state any of them ever sees.
    """
    try:
        doc = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        return [], f"{path} could not be read as YAML — {exc}"
    if doc is None:
        doc = {}
    if not isinstance(doc, dict):
        return [], f"{path} is a {type(doc).__name__}, not a mapping carrying a `rules:` key"
    raw = doc.get("rules")
    if raw is None:
        return [], f"{path} carries no `rules:` key — it is not a quality/rules.yaml"
    if not isinstance(raw, list) or not all(isinstance(r, dict) for r in raw):
        return [], f"{path}: `rules:` is not a list of rule mappings"
    return raw, ""


def _fold_map_local_rules(tree: Path) -> list[dict]:
    """The drawer's `rules:` on the GIVEN tree — absent is empty, never a raise.

    `LOCAL_RULES` is the module-level read of ROOT's drawer; this one takes the
    tree as an argument for the reason every other input to this reader does:
    the state tooth B exists for is one no template checkout is ever in, so a
    drive has to be able to build it somewhere else. A drawer nobody can parse
    is empty HERE and could-not-look in `consistency()`, which owns that
    refusal — two opinions about one file is the thing principle 9 forbids.
    """
    try:
        doc = yaml.safe_load((tree / "quality" / "local" / "rules.yaml").read_text())
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(doc, dict):
        return []
    raw = doc.get("rules")
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, dict)]


def _by_name(rules: list[dict]) -> dict[str, str]:
    """name -> id, first occurrence wins, nameless skipped."""
    out: dict[str, str] = {}
    for rule in rules:
        name = str(rule.get("name") or "").strip()
        if name:
            out.setdefault(name, str(rule.get("id", "")).strip())
    return out


def _fold_map_drawer_pairs(
    local_rules: list[dict], template_by_name: dict[str, str]
) -> list[tuple[str, str, str]]:
    """(name, the id the drawer gives it, the integer id the template side does).

    A rule the product has ALREADY namespaced whose name the template side
    still carries at a bare integer is the first of the two silent directions
    in this reader's header: a template rule parked under a product namespace
    stops being folded. It is a REFUSAL when the template side was taken from
    the tree (the file may be a merge result, so the reader cannot tell which
    of the two files is wrong) and a FINDING when the release's own file was
    handed in (there the answer is certain: the drawer is wrong).
    """
    out: list[tuple[str, str, str]] = []
    for rule in local_rules:
        name = str(rule.get("name") or "").strip()
        if not name:
            continue
        there = template_by_name.get(name)
        if there is not None and there.isdigit():
            out.append((name, str(rule.get("id", "")).strip(), there))
    return out


def _fold_map_remedy(tree: Path) -> list[str]:
    """The two-argument road, with the tag left as a PLACEHOLDER.

    WHY A PLACEHOLDER AND NOT `TEMPLATE_VERSION`, WHICH IS RIGHT THERE. The
    census hotfix in this same release paid for this: the checkout's own
    version answers a DIFFERENT question on either side of the merge — before
    it, the release you are LEAVING; after it, the one you just folded — and
    this refusal fires on both trees, so a derived tag would be confidently
    wrong half the time, which is worse than a blank a reader fills in. The
    reading is still handed over, on its own line and LABELLED as this
    checkout's, because a datum a reader can judge is worth having and a datum
    pasted into a command is not.
    """
    out = [
        "  Take the RELEASE's own file and hand it in as the second argument:",
        "    git show v<the release you are folding>:quality/rules.yaml > /tmp/template-rules.yaml",
        "    python -m quality.gate --fold-map <previous rules.yaml> /tmp/template-rules.yaml",
        "  and add `--template-tree <a git worktree or git archive of that tag>` if you want "
        "the FIXTURES section at full strength — the rules.yaml alone cannot carry bytes.",
    ]
    try:
        version = (tree / "TEMPLATE_VERSION").read_text().strip()
    except OSError:
        version = ""
    if version:
        out.append(
            f"  The tag is a placeholder on purpose: THIS CHECKOUT's TEMPLATE_VERSION reads "
            f"{version}, which after the merge is the release you just folded and before it is "
            "the one you are leaving — this refusal fires on both trees, so the reader names "
            "the number rather than pasting it into the command."
        )
    return out


def _fold_map_template_side_problems(
    *, previous: list[dict], template_rules: list[dict], local_rules: list[dict]
) -> list[str]:
    """The two teeth on an IMPLICIT template side — empty when it looks like a release.

    Read the header block above for why neither tooth is "the same name at a
    different number". A is the whole comparison of two rule sets; B is the
    drawer's own contradiction. Both are printed here; the caller refuses.
    """
    problems: list[str] = []
    prev_by_name = _by_name(previous)
    template_by_name = _by_name(template_rules)
    drifted = [
        (n, i, template_by_name[n])
        for n, i in prev_by_name.items()
        if n in template_by_name and template_by_name[n] != i
    ]
    only_previous = [n for n in prev_by_name if n not in template_by_name]
    only_template = [n for n in template_by_name if n not in prev_by_name]
    total = len(drifted) + len(only_previous) + len(only_template)
    if total:
        if drifted:
            name, old, new = drifted[0]
            problems.append(
                f"`{name}` is `{old}` in the previous file and `{new}` in this tree's "
                "quality/rules.yaml"
            )
        if only_previous:
            problems.append(
                f"`{only_previous[0]}` is in the previous file and NOT in this tree's "
                "quality/rules.yaml"
            )
        if only_template:
            problems.append(
                f"`{only_template[0]}` is in this tree's quality/rules.yaml and NOT in the "
                "previous file"
            )
        problems.append(
            f"{total} rule name(s) differ in all — the previous file and this tree's "
            "quality/rules.yaml are not the same rule set: this is your merged tree, or a "
            "release checkout that is not your pre-merge tree — either way hand the release's "
            "file in as the second argument"
        )
    for name, mine, theirs in _fold_map_drawer_pairs(local_rules, template_by_name):
        problems.append(
            f"`{name}` is in your drawer as `{mine}` AND in this tree's quality/rules.yaml at "
            f"the template integer `{theirs}` — a rule you namespaced that is the template's "
            "after all, which is the direction that stops being folded"
        )
        break
    return problems


def _fold_map_fixture_paths(rules: list[dict], root: Path) -> set[Path]:
    """Every fixture path the given rule set NAMES, under `root`.

    Declared rather than walked, so the template's inventory is the set of
    files the template's own plans claim — a stray file somebody left under
    `quality/canary/` is not evidence about where anything belongs.

    `extra_files:` IS PART OF THE PLAN, and reading only each entry's own
    `fixture:` left 52 of this tree's 469 fixture files outside the inventory —
    among them `quality/canary/60/the_declared_template_base`, house rule 60's
    own plan, which is exactly the kind of file a product carries across a fold.
    A file the inventory cannot see is a file the FIXTURES census below cannot
    give back, silently. `claimed_fixtures()` walks the same two levels for the
    orphan census; this one does it against an arbitrary root, which is what a
    drive needs and what `fixture_bases()` cannot give it.
    """
    out: set[Path] = set()
    for rule in rules:
        rid = str(rule.get("id", "")).strip()
        if not rid:
            continue
        for key, kind in (("canaries", "canary"), ("negatives", "negative")):
            for entry in rule.get(key) or []:
                if not isinstance(entry, dict):
                    continue
                extra = entry.get("extra_files") or []
                for e in [entry, *(extra if isinstance(extra, list) else [])]:
                    if not isinstance(e, dict):
                        continue
                    fixture = str(e.get("fixture") or "").strip()
                    if fixture:
                        out.add(root / "quality" / kind / rid / fixture)
    return out


def _fold_map_template_files(rules: list[dict], root: Path) -> dict[tuple[str, str], list[str]]:
    """(kind, rule id) -> the file names the TEMPLATE's own plan ships there.

    Read by the TEMPLATE block so its remedy can NAME the files rather than
    move a directory. The distinction is the whole of F3 below.
    """
    out: dict[tuple[str, str], list[str]] = {}
    for path in _fold_map_fixture_paths(rules, root):
        rel = path.relative_to(root).parts  # quality/<kind>/<id>/<name>
        if len(rel) >= 4:
            out.setdefault((rel[1], rel[2]), []).append(rel[-1])
    return {k: sorted(set(v)) for k, v in out.items()}


def _sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _shape_hash_of(path: Path) -> str | None:
    """A hash of the file's SHAPE: no trailing whitespace, no runs, no blank lines.

    THE EXACT SHA IS NOT ENOUGH, and the first consumer paid for the gap: of
    the thirteen template fixtures that had ridden into their drawer, the byte-
    identical ones were found and a `.tsx` whose indentation a formatter had
    changed and a `.py` carrying one extra trailing newline were not. A
    reformatter is the single likeliest thing to happen to a file between one
    fold and the next, so a census that only sees untouched bytes is a census
    that stops working on exactly the trees that need it.

    It is a SECOND key and not a replacement: a normalised match is still
    reported as "this is the template's", because collapsing whitespace cannot
    turn one fixture into another — every fixture here is a distinct plant with
    distinct identifiers, and two of them that agree after normalisation are
    the same file.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return hashlib.sha256("\n".join(line for line in lines if line).encode()).hexdigest()


def _fold_map_fixture_findings(
    template_rules: list[dict], *, tree: Path, template_root: Path
) -> list[str]:
    """`<product path> — this is the template's; put it back at <template path>`.

    KEYED ON CONTENT, NOT ON THE ID. The whole class is a file that
    moved between two DIFFERENT numbers, so the only witness is the bytes. A
    file sitting at the path the template ships it at is silent — that is the
    steady state, and it is why a template tree's own run prints nothing here.

    THREE KEYS, IN DESCENDING CONFIDENCE, AND EACH FILE IS REPORTED UNDER THE
    FIRST THAT HITS. The exact sha is the certain one. The shape hash
    (`_shape_hash_of`) is the one a reformatter cannot break, and it says the
    same sentence because a whitespace difference does not make a file somebody
    else's. The BASENAME is the last resort and says something weaker — READ
    IT — because a name survives any edit at all, including edits that really
    did make the file the product's. One certain finding and two suspicions
    beat one certain finding, as long as the reader is told which is which.
    """
    by_hash: dict[str, set[str]] = {}
    by_shape: dict[str, set[str]] = {}
    by_name: dict[str, set[str]] = {}
    # ENGINE_FIXTURES is declared as absolute paths under ROOT and is RE-ROOTED
    # here: a drive hands this function a template root of its own, and an
    # absolute ROOT path inside that walk is a file from another tree whose
    # `relative_to` would raise inside a reader.
    engine = {template_root / p.relative_to(ROOT) for p in ENGINE_FIXTURES}
    for path in _fold_map_fixture_paths(template_rules, template_root) | engine:
        rel = str(path.relative_to(template_root))
        digest = _sha256_of(path)
        if digest is None:
            # A path the template's plan NAMES and this root does not have is
            # not this reader's finding (`consistency()` owns that refusal),
            # but its NAME is still evidence, so it stays in the name index.
            by_name.setdefault(path.name, set()).add(rel)
            continue
        by_hash.setdefault(digest, set()).add(rel)
        shape = _shape_hash_of(path)
        if shape is not None:
            by_shape.setdefault(shape, set()).add(rel)
        by_name.setdefault(path.name, set()).add(rel)
    findings: list[str] = []
    for base in (
        tree / "quality" / "canary",
        tree / "quality" / "negative",
        tree / "quality" / "local" / "canary",
        tree / "quality" / "local" / "negative",
    ):
        if not base.is_dir():
            continue
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            here = str(path.relative_to(tree))
            homes: set[str] = set()
            for index, key in (
                (by_hash, _sha256_of(path)),
                (by_shape, _shape_hash_of(path)),
            ):
                if key is not None and key in index:
                    homes = index[key]
                    break
            if homes:
                if here in homes:
                    continue
                for home in sorted(homes):
                    findings.append(f"{here} — this is the template's; put it back at {home}")
                continue
            named = by_name.get(path.name) or set()
            if named and here not in named:
                for home in sorted(named):
                    findings.append(f"{here} — NAME MATCH — read it: {home}")
    return findings


def _renumbered_check_ids(rule: dict, new_prefix: str, new_number: str) -> list[str]:
    """A rule's declared django check ids, re-spelled at the new id.

    The LETTER and the WIDTH come from what the rule actually declares
    (`djb.E013`, `djb.W054`), never from a guess: an `E` rewritten as a `W` is
    a registration `apps/core/checks.py` does not carry, which is the same
    exit 2 this line exists to prevent.
    """
    out: list[str] = []
    for raw in rule.get("django_check_ids") or []:
        tag = str(raw)
        match = re.match(r"^(?P<ns>[A-Za-z0-9_]+)\.(?P<letter>[A-Za-z])(?P<digits>\d+)$", tag)
        if match is None:
            out.append(f"{tag} — unreadable as `<ns>.<letter><digits>`; re-spell it by hand")
            continue
        width = len(match.group("digits"))
        out.append(f"{tag} → {new_prefix}.{match.group('letter')}{new_number.zfill(width)}")
    return out


def fold_map_lines(
    previous_path: Path,
    *,
    template_path: Path | None = None,
    template_rules: list[dict] | None = None,
    namespace: str | None = ...,  # type: ignore[assignment]
    tree: Path = ROOT,
    template_root: Path | None = None,
) -> tuple[int, list[str]]:
    """(exit code, the map). The whole reader, as a function a test can call.

    Every input is an argument with a live-tree default, because the three
    cases this instrument exists for — a template rule at a drifted number, a
    product rule, a template fixture under a product id — are states no
    template checkout is ever in. A drive that could only run against ROOT
    could only ever prove the steady state.
    """
    if namespace is ...:
        namespace = RULE_ID_NAMESPACE
    # WAS THE TEMPLATE SIDE GIVEN, OR TAKEN? Captured BEFORE the defaults fill
    # it in, because every sentence below turns on it: the header says which,
    # the two teeth run only on the taken one, and the FIXTURES section
    # declares itself a lower bound whenever the bytes came from this tree.
    template_given = template_path is not None or template_rules is not None
    template_root_given = template_root is not None
    if template_path is None:
        template_path = tree / "quality" / "rules.yaml"
    if template_root is None:
        template_root = tree
    lines: list[str] = []
    previous, problem = _fold_map_rules(previous_path)
    problems = [problem] if problem else []
    if template_rules is None:
        template_rules, template_problem = _fold_map_rules(template_path)
        if template_problem:
            problems.append(template_problem)
    if problems:
        lines.append(
            "‼ --fold-map COULD NOT LOOK (exit 2). A map built from half its inputs is a "
            "rename list somebody would paste, so nothing is printed:"
        )
        lines.extend(f"  !! {p}" for p in problems)
        return 2, lines

    nameless = [str(r.get("id", "?")) for r in previous if not str(r.get("name") or "").strip()]
    if nameless:
        lines.append(
            "‼ --fold-map COULD NOT LOOK (exit 2). The NAME is the matching key — the number "
            "is the thing that drifted — so a rule with no name cannot be placed on either "
            "side of the map, and guessing from its number would agree with the mistake:"
        )
        for rid in nameless:
            lines.append(f"  !! {previous_path}: rule {rid} declares no `name:`")
        return 2, lines

    local_rules = _fold_map_local_rules(tree)
    if not template_given:
        # THE TEETH. They run ONLY here: with an explicit second argument the
        # caller has said which file is the release's, and a reader that
        # second-guessed that would refuse the road this hotfix exists to open.
        side_problems = _fold_map_template_side_problems(
            previous=previous, template_rules=template_rules, local_rules=local_rules
        )
        if side_problems:
            lines.append(
                "‼ --fold-map COULD NOT LOOK (exit 2). The template side was TAKEN from this "
                f"tree ({template_path}) because no second argument was given, and that file "
                "is not a template RELEASE file:"
            )
            lines.extend(f"  !! {p}" for p in side_problems)
            lines.append(
                "  AFTER `git merge`, quality/rules.yaml IS THE MERGE RESULT — your names at "
                "your numbers — so a map built against it renames the TEMPLATE's rules into "
                "your namespace and leaves YOURS on template integers: the exact failure this "
                "reader exists to prevent, printed as a clean map at exit 0."
            )
            lines.extend(_fold_map_remedy(tree))
            return 2, lines

    template_by_name: dict[str, str] = {}
    for rule in template_rules:
        name = str(rule.get("name") or "").strip()
        if name:
            template_by_name.setdefault(name, str(rule.get("id", "")))

    ships = _fold_map_template_files(template_rules, template_root)
    lines.append(
        f"fold map · previous {previous_path} · template side {template_path} "
        + ("(GIVEN)" if template_given else "(TAKEN from this tree — no second argument)")
    )
    lines.append(
        f"matched BY NAME, never by number · {len(previous)} rule(s) in the previous file · "
        f"{len(template_rules)} in the template's"
    )
    lines.append("")

    unmatched: list[tuple[str, str]] = []
    for rule in previous:
        old = str(rule.get("id", "")).strip()
        name = str(rule.get("name")).strip()
        new = template_by_name.get(name)
        if new is not None:
            # A RULE THAT DID NOT MOVE IS ONE LINE. The map's whole subject is
            # the drift, and a block of five "places" that all say the number
            # they already say is the noise a reader skims past — which is how
            # the four that HAD moved went unnoticed in the first place.
            if old == new:
                lines.append(f"TEMPLATE  {old}  {name} — unchanged; nothing to renumber")
                continue
            lines.extend(
                _fold_map_template_block(
                    rule, old=old, new=new, name=name, ships=ships, ns=namespace
                )
            )
            lines.append("")
            continue
        if namespace:
            lines.extend(_fold_map_product_block(rule, old=old, ns=namespace, name=name))
            lines.append("")
            continue
        unmatched.append((old, name))

    if unmatched:
        lines.append("UNMATCHED — this reader will not guess:")
        for old, name in unmatched:
            lines.append(f"  {old}  {name}")
        lines.append(
            "  No rule of this name is in the template's current rules.yaml, and this tree "
            "declares no `rule_id_namespace:` — so there is no `<ns>-<n>` to write. Declare "
            "the namespace in quality/local/rules.yaml (with `template_rule_ids_through:` "
            f"beside it) and run --fold-map again — {GATE5_CITE}."
        )
        lines.append("")

    drawer_pairs = _fold_map_drawer_pairs(local_rules, template_by_name)
    if drawer_pairs:
        # The same pairs tooth B refuses on, printed as FINDINGS because here
        # the release's own file was handed in: with that file certain, the
        # drawer is the side that is wrong, and the reader can say so.
        if lines and lines[-1] != "":
            lines.append("")
        lines.append("DRAWER — namespaced in quality/local/rules.yaml, and still the TEMPLATE's:")
        for name, mine, theirs in drawer_pairs:
            lines.append(
                f"  {mine} → {theirs}  {name} — the release carries this name at the template "
                f"integer {theirs}, so it is not yours to namespace: delete `{mine}` from the "
                "drawer (and its fixtures under quality/local/) and take the template's copy"
            )

    findings = _fold_map_fixture_findings(template_rules, tree=tree, template_root=template_root)
    if lines and lines[-1] != "":
        lines.append("")
    lines.append("FIXTURES — bytes the template ships, found at another path on this tree:")
    if not template_root_given:
        # A SILENT LOWER BOUND IS NOT ACCEPTABLE. The inventory's paths come
        # from the template side's rules, but the BYTES can only be read off a
        # tree, and with no `--template-tree` that tree is this one — which
        # after a merge holds the merge result, so a template fixture the merge
        # overwrote in place reads as at home and a release path this tree does
        # not have degrades to a NAME MATCH.
        lines.append(
            f"  A LOWER BOUND — the fixture BYTES were read from THIS TREE ({template_root}), "
            "not from a checkout of the release, so a template fixture the merge overwrote in "
            "place reads as at home. `--template-tree <a git worktree or git archive of the "
            "tag>` is what makes this section complete."
        )
    if findings:
        for finding in findings:
            lines.append(f"  {finding}")
        lines.append(
            "  Three keys, at ANY id: exact bytes, then the same bytes with whitespace "
            "normalised (a reformatter between two folds is the commonest single edit), "
            "then the BASENAME — which survives any edit and is therefore a READ IT rather "
            "than a verdict. The class is a fixture that moved between two DIFFERENT "
            "numbers, which an id-keyed census cannot see."
        )
    else:
        lines.append("  none — every template fixture on this tree is at the path it ships at.")
    return 0, lines


def _fold_map_template_block(
    rule: dict,
    *,
    old: str,
    new: str,
    name: str,
    ships: dict[tuple[str, str], list[str]],
    ns: str | None,
) -> list[str]:
    """The five places a TEMPLATE rule carried at the wrong number is renumbered.

    F3, AND IT IS NOT A WORDING NIT. The first form of this block said
    `git mv quality/canary/<old> quality/canary/<new>`, and AFTER THE FOLD that
    is wrong twice over: `quality/canary/<old>/` now also holds the template's
    OWN rule-<old> plan, and `quality/canary/<new>/` already exists — so the
    move either nests one directory inside the other or carries another rule's
    fixtures into its home. That is the exact class the FIXTURES census below
    warns about, printed as the remedy for it. The remedy is therefore DELETE
    YOUR COPIES, with the template's own file list for the new id beside it, so
    the reader can see what they are deleting against.
    """
    out = [
        f"TEMPLATE  {old} → {new}  {name}",
        "  This rule is the TEMPLATE's. It is not yours to namespace: a template rule parked "
        "under a product namespace stops being folded, silently.",
        f"    id          quality/rules.yaml already carries it as `{new}` — delete your copy",
    ]
    for kind in ("canary", "negative"):
        files = ships.get((kind, new)) or []
        shipped = (
            f"the template ships this rule's at quality/{kind}/{new}/: {', '.join(files)}"
            if files
            else f"the template ships none at quality/{kind}/{new}/ — anything there is another "
            "rule's or is yours"
        )
        out.append(
            f"    fixtures    DELETE your copies under quality/{kind}/{old}/ — do NOT git mv it: "
            f"after the fold that directory also holds the template's own rule {old} plan and "
            f"quality/{kind}/{new}/ already exists, so a move nests or carries the wrong files. "
            f"{shipped}"
        )
        if ns:
            out.append(
                f"    fixtures    and the same under quality/local/{kind}/{ns}-{old}/ if they "
                "went into the drawer"
            )
    out.append(f"    valve       `# rule-{old}:` → `# rule-{new}:`")
    tags = _renumbered_check_ids(rule, TEMPLATE_CHECK_PREFIX, new)
    if tags:
        out.append(f"    check tag   {', '.join(tags)}   (quality/rules.yaml django_check_ids)")
        out.append(
            f"    django check  apps/core/checks.py registers {', '.join(tags)} — the FIFTH "
            "place, and the one a renumber reds on (`django check id … not present in …`)"
        )
    else:
        out.append("    check tag   none declared")
    return out


def _fold_map_product_block(rule: dict, *, old: str, ns: str, name: str) -> list[str]:
    """The same five places, into the drawer, for a rule that is the PRODUCT's."""
    new = f"{ns}-{old}"
    out = [
        f"PRODUCT   {old} → {new}  {name}",
        "  No rule of this name is in the template's current rules.yaml, so it is yours: a "
        "product rule left on a template integer collides again at the next release.",
        f'    id          quality/local/rules.yaml — `id: "{new}"`',
    ]
    for kind in ("canary", "negative"):
        out.append(f"    fixtures    git mv quality/{kind}/{old} quality/local/{kind}/{new}")
    out.append(f"    valve       `# rule-{old}:` → `# rule-{new}:`")
    tags = _renumbered_check_ids(rule, ns, old)
    if tags:
        out.append(f"    check tag   {', '.join(tags)}   (quality/local/rules.yaml)")
        out.append(
            f"    django check  your own apps/<app>/checks.py registers {', '.join(tags)} — "
            "the FIFTH place, and the one a renumber reds on"
        )
    else:
        out.append("    check tag   none declared")
    return out


def fold_map(previous: str, template: str | None = None, template_tree: str | None = None) -> int:
    """`--fold-map <previous> [<template>] [--template-tree <dir>]`, printed.

    0 with the map · 2 could-not-look. `--template-tree` alone is enough: a
    checkout of the tag carries its own `quality/rules.yaml`, so naming the
    tree names the file, and the two-argument form stays the short road for a
    reader who only has the yaml.
    """
    root = Path(template_tree) if template_tree else None
    if template is not None:
        template_path: Path | None = Path(template)
    elif root is not None:
        template_path = root / "quality" / "rules.yaml"
    else:
        template_path = None
    rc, lines = fold_map_lines(Path(previous), template_path=template_path, template_root=root)
    for line in lines:
        say(line)
    return rc


# --- THE PER-RULE MEMO -----------------------------------------------------------
#
# WHAT IT ANSWERS. "Did anything this rule reads move since the last time it
# was scanned?" Before it, the answer was never asked: the house-rules leg
# re-ran all 57 rules on every gate, dozens of times a day, and a rule whose
# every input was byte-identical to the run five minutes earlier paid its full
# scan again. `--selftest-inputs` (the third reader) already derives the whole
# engine's inputs; this is the same derivation PER RULE, and the memo is what
# it keys.
#
# IT IS A PROJECTION OF THE SCAN, NEVER A SECOND OPINION (principle 9). The
# rule's own scope is the owner of what the memo may say; the memo holds a copy
# of ONE call's answer and nothing else. So a rule whose inputs cannot be
# derived is not memoised — by construction, and it says so — and an
# undecidable key never reads the cache: could-not-look outranks a hit exactly
# as it outranks a pass.
#
# WHAT IS MEMOISED, AND WHAT IS NOT. The value is the `check:` call's
# `(findings, targets)` and NOTHING further down the pipeline: overrides,
# ratchets, floors, the runner, the floor proxy and the Django leg all run on
# every rule on every run (`run_rule`), so a memo can never hide an unbound
# floor, a valve that lost its reason, or a ratchet that grew.
#
# THE KEY, per rule, `rule-v1:<sha256>` over six components, each named so a
# miss can be attributed to the one that moved:
#
#   rule    the rule's own mapping, dumped canonically — its statement, its
#           scope, its ratchets, its doc anchor text. A byte in ONE rule's
#           yaml re-keys THAT rule and no other, which is why this component
#           exists beside `engine` rather than inside it.
#   scope   population 2 of `selftest_inputs_for` — the `scope:` allow-list,
#           expanded through `_expand_input` over the measured tree.
#   walk    population 6, narrowed to THIS RULE'S KIND — `scope:` is an
#           allow-list OVER the walk, not the walk, so a key that read only
#           `scope:` would hit on a violation planted in a file no rule names.
#   reads   population 4 — `HARDCODED_READS`, the reads this module spells.
#   doc     population 5 — the doc file's blob and the anchor text
#           `consistency()` looks for in it.
#   engine  population 1 — every tracked path under `quality/` EXCEPT
#           `rules.yaml`, plus the canonical dump of every top-level key of
#           `rules.yaml` that is not `rules:` (`scope_kinds`, `seam`, the
#           backlogs). `rules.yaml`'s own bytes are deliberately absent: they
#           are covered per rule by `rule` above, and keying every rule on the
#           whole file would make one rule's reword re-scan fifty-six others.
#
# THE BLOBS COME FROM THE MEASURED TREE, never from `git hash-object` over the
# working tree: the same `git read-tree HEAD` + `git add -A` + `write-tree`
# read `scripts/gate_ledger.sh::gate_measured_tree` banks every other verdict
# in this system on. A row that vouches for bytes has to vouch for bytes
# somebody can name (13: one tree reading, not two).
#
# WHERE IT LIVES. `<git common dir>/djb-rules-memo/<rule id>/<sha>.json` — per
# checkout, shared across that checkout's worktrees exactly as the gate ledger
# is, and never committed. `DJB_RULES_MEMO_DIR` is the scratch seam a drive
# points at its own `mktemp -d`, refused when relative for
# `gate_ledger_path`'s reason; `DJB_RULES_NO_MEMO=1` is the valve that scans
# everything and is printed.
#
# WHAT IT CANNOT SEE, declared: a check that reads a path its walk does not
# name (population 4's blind spot, inherited exactly — the mitigation is
# structural rather than hopeful, since `engine` re-keys every rule the moment
# anybody writes such a read into `quality/`); the installed environment, which
# is why every rule whose check boots Django or shells out declines the memo in
# `rules.yaml` with a reason; and the first run after any byte under a kind's
# roots moves, which re-keys every rule of that kind — the memo pays on the
# SECOND and later reads of one tree (the hook, the loop, the verifier's
# consult and the push all measure one tree), never on the first.

MEMO_SCHEMA = "rule-v1"

#: How many entries per rule survive a write. A key is one tree, and a builder
#: bouncing between two or three trees wants all of them warm; twenty is that
#: with room, and the oldest by mtime go first.
MEMO_KEEP = 20

#: The run's memo state, in one mutable mapping rather than module globals, so
#: that `main` and the census can set it without `global` and a drive can read
#: it in process.
memo_state: dict[str, object] = {"bypass": False, "home": None}

#: Counted like every valve in this engine, and PRINTED on every live scan.
memo_counts: dict[str, int] = {
    "scanned": 0,
    "hits": 0,
    "misses": 0,
    "undecidable": 0,
    "declined": 0,
}

#: The ids that declared `memo: { no: ... }` and were reached this run, and the
#: one-line sentence each miss or undecidable key owes its reader.
memo_declined_ids: list[str] = []
memo_lines: list[str] = []


def memo_consistency(rules: list[dict] | None = None) -> None:
    """Every `memo:` declaration is one shape and carries a reason, or exit 2.

    The valve's own grammar (`consistency()`, `valve:`), one field over: a rule
    that declines to be memoised is making a claim — that its check reads
    something no key here can name — and a claim nobody wrote down is a claim
    nobody can disagree with. The census of which rules decline IS the point of
    the field, so a declaration that silently declined to answer would be the
    one place the census cannot see.
    """
    for rule in rules if rules is not None else RULES:
        rid = str(rule["id"])
        declared = rule.get("memo")
        if declared is None:
            continue
        if isinstance(declared, dict) and set(declared) == {False}:
            # YAML 1.1, AND IT COSTS EVERY AUTHOR ONCE. A bare `no:` key parses
            # as the BOOLEAN False, so the declaration reads back as
            # `{False: '<reason>'}` and a reader looking for `no` finds
            # nothing — which would silently memoise a rule that declined.
            # Named here rather than left to be rediscovered.
            broken.append(
                f"rule {rid}: `memo:` declares a bare `no:` key, which yaml reads as the "
                'BOOLEAN false — quote it (`"no": <reason>`), or this rule is memoised '
                "while its yaml says it is not"
            )
            continue
        if not isinstance(declared, dict) or set(declared) != {"no"}:
            broken.append(
                f"rule {rid}: `memo:` takes exactly one form — "
                "`memo: { no: <why this rule's check cannot be keyed on blobs> }`. "
                f"This one is {declared!r}, which the engine cannot read as a declaration; "
                "a rule that is memoised by accident replays an answer for inputs nobody "
                "named"
            )
            continue
        reason = str(declared.get("no") or "").strip()
        if len(reason) < MIN_REASON:
            broken.append(
                f"rule {rid}: `memo: no` with a {len(reason)}-character reason — declining "
                "the memo says this rule reads something the key cannot name (a registry, a "
                "Django boot, a population), and that is exactly the claim owing a sentence "
                "a reviewer can disagree with"
            )


def memo_reset() -> None:
    """Zero the run's counters. One live scan per process; a drive runs several."""
    for key in memo_counts:
        memo_counts[key] = 0
    del memo_declined_ids[:]
    del memo_lines[:]


def memo_report() -> None:
    """The two counted sentences, printed on every live scan.

    TWO, not one, and each is a different closed question. The first is the
    arithmetic a reader checks against the clock — how many of this run's
    checks actually ran — and it is the line a drive asserts by its words. The
    second is the memo's own census in the grammar every valve in this engine
    prints: how many rules could be memoised, what the consult did, and WHICH
    rules declined, by id. A silent memo is a memo nobody can catch quietly
    turning itself off.
    """
    memoisable = sum(
        1
        for rule in RULES
        if rule.get("enabled", True) and rule.get("check") and memo_declines(rule) is None
    )
    # THE DECLINING COUNT IS READ OFF THE POPULATION, never off the run. A
    # rule that declares `memo: no` and has no `check:` to skip is never
    # reached by the consult, so counting what the consult SAW would print a
    # smaller number every run and make the census unfalsifiable: the closed
    # question is "which rules declare they cannot be memoised", and the rule
    # set is what answers it.
    declining = [str(r["id"]) for r in RULES if r.get("memo") is not None]
    say(f"  house rules: {memo_counts['scanned']} scanned · {memo_counts['hits']} memoized")
    say(
        f"  memo: {len(RULES)} rules · {memoisable} memoisable "
        f"({memo_counts['hits']} hits, {memo_counts['misses']} misses, "
        f"{memo_counts['undecidable']} undecidable) · "
        f"{len(declining)} memo: no ({' '.join(declining) or 'none'}), "
        f"{memo_counts['declined']} of them scanned here"
    )
    for line in memo_lines:
        say(f"    {line}")


def memo_home() -> tuple[Path | None, str]:
    """This checkout's memo directory, and why there is none.

    `--git-common-dir` for `gate_local_path`'s reason: one memo per CHECKOUT,
    shared by its worktrees, never committed and never carried by a clone.
    """
    override = str(memo_state.get("home") or os.environ.get("DJB_RULES_MEMO_DIR") or "").strip()
    if override:
        if not override.startswith("/"):
            return None, (
                f"DJB_RULES_MEMO_DIR={override!r} is relative — it would resolve against "
                "whatever directory a caller left behind, and a memo nobody can name is a "
                "memo nobody can audit"
            )
        return Path(override), ""
    proc = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    common = proc.stdout.strip()
    if proc.returncode != 0 or not common:
        return None, (
            f"`git rev-parse --git-common-dir` exited {proc.returncode} — "
            f"{proc.stderr.strip() or 'no stderr'}"
        )
    base = Path(common)
    if not base.is_absolute():
        base = ROOT / common
    return base / "djb-rules-memo", ""


_MEASURED: tuple[dict[str, str], str] | None = None


def measured_blobs() -> tuple[dict[str, str], str]:
    """path -> blob sha over the MEASURED tree, and why it could not be read.

    `git read-tree HEAD` into a throwaway index, `git add -A` over it,
    `write-tree`, `ls-tree -r` — `scripts/gate_ledger.sh::gate_measured_tree`'s
    own read, in process. It sees the working tree (an uncommitted edit moves a
    blob) and it sees a brand-new untracked file (`add -A` stages it), which is
    what a walk-shaped check sees too. Read once per process: a gate run does
    not re-derive its world half way through.
    """
    global _MEASURED
    if _MEASURED is None:
        _MEASURED = _read_measured_blobs()
    return _MEASURED


def _read_measured_blobs() -> tuple[dict[str, str], str]:
    fd, index = tempfile.mkstemp(prefix="djb-rules-memo-index.")
    os.close(fd)
    os.unlink(index)  # git wants to create it, not inherit an empty one
    env = dict(os.environ)
    env["GIT_INDEX_FILE"] = index
    try:
        for argv in (["read-tree", "HEAD"], ["add", "-A"], ["write-tree"]):
            proc = subprocess.run(
                ["git", "-C", str(ROOT), *argv],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            if proc.returncode != 0:
                return {}, (
                    f"`git {' '.join(argv)}` exited {proc.returncode} — "
                    f"{proc.stderr.strip() or 'no stderr'}"
                )
        tree = proc.stdout.strip()
        if not tree:
            return {}, "`git write-tree` printed no tree"
        listing = subprocess.run(
            ["git", "-C", str(ROOT), "ls-tree", "-r", "-z", tree],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if listing.returncode != 0:
            return {}, (
                f"`git ls-tree -r {tree}` exited {listing.returncode} — "
                f"{listing.stderr.strip() or 'no stderr'}"
            )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(index)
    blobs: dict[str, str] = {}
    for record in listing.stdout.split("\0"):
        if not record:
            continue
        meta, _, path = record.partition("\t")
        fields = meta.split()
        if len(fields) < 3 or not path:
            continue
        blobs[path] = fields[2]
    if not blobs:
        return {}, "the measured tree named no path at all"
    return blobs, ""


def _paths_digest(paths: list[str], blobs: dict[str, str]) -> str:
    """One component: `<path>\\0<blob>` per line, sorted, sha256 of the whole."""
    digest = hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(blobs[path].encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


_ENGINE_DIGEST: str | None = None


def _engine_digest(blobs: dict[str, str]) -> str:
    """Population 1, minus `rules.yaml`'s bytes and plus its non-rule content.

    Every rule reads the engine, so the engine is in every rule's key. What is
    NOT in it is `quality/rules.yaml`'s blob: one rule's reword would otherwise
    re-scan the other fifty-six, and the per-rule `rule` component already
    carries that rule's own text. The file's OTHER top-level keys — the scope
    kinds, the seam, the backlogs — are read here from the parse, because they
    change what every rule scans.
    """
    global _ENGINE_DIGEST
    if _ENGINE_DIGEST is None:
        skip = {"quality/rules.yaml", "quality/local/rules.yaml"}
        under = [p for p in blobs if p.startswith("quality/") and p not in skip]
        rest = {k: v for k, v in _DOC.items() if k != "rules"}
        # THE DRAWER IS THE SAME SHAPE, for the same reason (X3.5). Its blob is
        # subtracted so that rewording ONE product rule does not re-scan the
        # other fifty-seven — the per-rule `rule` component already carries
        # that rule's own text — and its NON-rule keys are folded in here,
        # because the namespace, the high-water and the drawer's ratchets
        # change what every rule scans or how every finding is judged. A key
        # added to the drawer therefore moves the engine digest, and a
        # no-op edit to it moves nothing.
        rest_local = {k: v for k, v in LOCAL_DOC.items() if k != "rules"}
        digest = hashlib.sha256()
        digest.update(_paths_digest(under, blobs).encode("utf-8"))
        digest.update(b"\n")
        digest.update(yaml.safe_dump(rest, sort_keys=True, allow_unicode=True).encode("utf-8"))
        digest.update(b"\n")
        digest.update(
            yaml.safe_dump(rest_local, sort_keys=True, allow_unicode=True).encode("utf-8")
        )
        _ENGINE_DIGEST = digest.hexdigest()
    return _ENGINE_DIGEST


def memo_components(rule: dict) -> tuple[dict[str, str], str]:
    """The six named halves of this rule's key, or why the key is undecidable.

    Every failure here is could-not-look and returns the sentence: a component
    that quietly derived to nothing would key a verdict for inputs nobody
    measured, which is the one thing a memo must never do.
    """
    blobs, trouble = measured_blobs()
    if trouble:
        return {}, trouble
    names = frozenset(blobs)
    components: dict[str, str] = {}

    components["rule"] = hashlib.sha256(
        yaml.safe_dump(rule, sort_keys=True, allow_unicode=True).encode("utf-8")
    ).hexdigest()

    scoped: list[str] = []
    for trail, value in _scope_paths(rule.get("scope") or {}):
        found, why = _expand_input(value, names)
        if why:
            return {}, f"scope {trail} {why}"
        scoped.extend(found)
    components["scope"] = _paths_digest(scoped, blobs)

    kind = W.scope_kind(rule, SCOPE_KINDS)
    skip = W.kind_skip_dirs(kind)
    suffixes = tuple(str(s) for s in (kind.get("suffixes") or []))
    if not suffixes:
        return {}, "its kind declares no suffix, so the walk it reads cannot be derived"
    walked: list[str] = []
    for root in (str(r) for r in (kind.get("roots") or [])):
        if not (ROOT / root).exists():
            continue
        if (ROOT / root).is_file():
            # A FILE ROOT IS ITS OWN WALK, and a suffix filter over one named
            # path would be a second opinion about a file somebody declared.
            here = [root] if root in names else []
        else:
            here = [
                p
                for p in names
                if p.startswith(root + "/")
                and p.endswith(suffixes)
                and not (skip & set(Path(p).parts))
            ]
        if not here:
            return {}, (
                f"the walk root {root!r} is on this tree and holds no file of any suffix its "
                "kind declares — an emptied walk is how a rule goes green over nothing"
            )
        walked.extend(here)
    components["walk"] = _paths_digest(walked, blobs)

    reads: list[str] = []
    for value, why_read in HARDCODED_READS:
        found, why = _expand_input(value, names)
        if why:
            return {}, f"hard-coded read ({why_read}) {why}"
        reads.extend(found)
    components["reads"] = _paths_digest(reads, blobs)

    doc = rule.get("doc") or {}
    doc_file = str(doc.get("file") or "").strip()
    if not doc_file:
        return {}, "doc names no file, so the anchor consistency() reads cannot be derived"
    found, why = _expand_input(doc_file, names)
    if why:
        return {}, f"doc {why}"
    anchor = hashlib.sha256(_paths_digest(found, blobs).encode("utf-8"))
    anchor.update(str(doc.get("contains", "")).encode("utf-8"))
    components["doc"] = anchor.hexdigest()

    components["engine"] = _engine_digest(blobs)
    return components, ""


def memo_key(rule: dict) -> tuple[str | None, dict[str, str], str]:
    """(`rule-v1:<sha256>`, its components, "") or (None, {}, why it is undecidable)."""
    components, why = memo_components(rule)
    if why:
        return None, {}, why
    digest = hashlib.sha256()
    digest.update(MEMO_SCHEMA.encode("utf-8"))
    for name in sorted(components):
        digest.update(b"\0")
        digest.update(name.encode("utf-8"))
        digest.update(b"=")
        digest.update(components[name].encode("utf-8"))
    return f"{MEMO_SCHEMA}:{digest.hexdigest()}", components, ""


def memo_declines(rule: dict) -> str | None:
    """The reason this rule declines the memo, or None when it takes one.

    An empty string is a declaration with no reason — `consistency()` is where
    that is exit 2; here it still declines, because a rule that said it cannot
    be memoised is not memoised while somebody argues about the sentence.
    """
    declared = rule.get("memo")
    if declared is None:
        return None
    if isinstance(declared, dict):
        return str(declared.get("no") or "").strip()
    return ""


def _entry_path(home: Path, rid: str, key: str) -> Path:
    return home / rid / (key.split(":")[-1] + ".json")


def memo_read(home: Path, rid: str, key: str) -> CheckResult | None:
    """The banked answer for this key, or None. A file that will not parse is a miss."""
    path = _entry_path(home, rid, key)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("key") != key:
        return None
    try:
        findings = [
            Finding(str(f[0]), int(f[1]), str(f[2]), str(f[3])) for f in payload["findings"]
        ]
        targets = {str(k): int(v) for k, v in dict(payload["targets"]).items()}
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    with contextlib.suppress(OSError):
        os.utime(path)  # newest-first is what attribution and pruning read
    return CheckResult(findings=findings, targets_matched=targets)


def memo_write(
    home: Path, rid: str, key: str, components: dict[str, str], result: CheckResult
) -> None:
    """Bank one answer, then prune this rule to the last MEMO_KEEP keys.

    Written through a temporary file in the same directory and renamed, so a
    killed run leaves no half-written entry a later run would read as an
    answer. A memo that cannot be written is not a failure: the scan already
    happened and its verdict stands.
    """
    path = _entry_path(home, rid, key)
    payload = {
        "key": key,
        "components": components,
        "findings": [[f.path, f.line, f.msg, f.klass] for f in result.findings],
        "targets": dict(result.targets_matched),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".writing-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        return
    entries = sorted(
        (p for p in path.parent.glob("*.json")),
        key=lambda p: p.stat().st_mtime if p.exists() else 0.0,
        reverse=True,
    )
    for stale in entries[MEMO_KEEP:]:
        with contextlib.suppress(OSError):
            stale.unlink()


def memo_attribute(home: Path, rid: str, components: dict[str, str]) -> str:
    """Which component moved, read off the newest entry this rule already holds.

    A rule with no entry at all misses `cold` — there is nothing to have moved
    against, and saying so is the difference between a first run and a
    regression in the key.
    """
    folder = home / rid
    try:
        entries = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return "cold"
    for entry in entries:
        try:
            previous = json.loads(entry.read_text(encoding="utf-8")).get("components")
        except (OSError, ValueError):
            continue
        if not isinstance(previous, dict):
            continue
        moved = [name for name in sorted(components) if previous.get(name) != components[name]]
        if moved:
            return ",".join(moved)
        return "key"  # the components agree and the key did not: a schema move
    return "cold"


def memo_consult(rule: dict, impl: str) -> CheckResult:
    """The `check:` call, through the memo. THE ONLY PLACE A SCAN IS SKIPPED.

    Everything `run_rule` does after this — the runner, the floor proxy, the
    overrides, the ratchets and the floors — runs on every rule on every run,
    so no memo can hide an unbound floor or a ratchet that grew.
    """
    rid = str(rule["id"])

    def scan() -> CheckResult:
        memo_counts["scanned"] += 1
        return REGISTRY[impl](ROOT, rule)

    if memo_state.get("bypass") or os.environ.get("DJB_RULES_NO_MEMO"):
        return scan()
    declined = memo_declines(rule)
    if declined is not None:
        memo_counts["declined"] += 1
        if rid not in memo_declined_ids:
            memo_declined_ids.append(rid)
        return scan()
    home, why_home = memo_home()
    if home is None:
        key, components, why = None, {}, why_home
    else:
        key, components, why = memo_key(rule)
    if key is None:
        memo_counts["undecidable"] += 1
        memo_lines.append(f"rule {rid}: memo undecidable — {why}; scanned")
        return scan()
    assert home is not None
    banked = memo_read(home, rid, key)
    if banked is not None:
        memo_counts["hits"] += 1
        return banked
    memo_counts["misses"] += 1
    memo_lines.append(f"rule {rid}: miss({memo_attribute(home, rid, components)})")
    result = scan()
    memo_write(home, rid, key, components, result)
    return result


def memo_census() -> None:
    """The memo, driven: the key, the bypass, and every way the consult must refuse.

    A FOURTH counted sentence beside the trailer, CLI and inputs censuses, and
    the same grammar: the count is in the line, so deleting a probe is visible
    rather than silent.

    IT RUNS INSIDE `--selftest`, WHERE THE BYPASS IS ON — which is exactly
    where a memo most needs driving, because a bypass that stopped working
    would make every canary below it a canary that could replay yesterday's
    green. Every probe builds its own victim: a scratch rule appended to
    `RULES` for the length of one probe (`inputs_census`' idiom), a stub check
    registered in `REGISTRY` and removed, and a memo directory under
    `mktemp -d` that is deleted whatever happens — nothing here reads or writes
    the checkout's own memo, which is the claim probe 6 asserts about the
    self-test as a whole.
    """
    probes = 8
    answered = 0
    memoisable = [
        rule
        for rule in RULES
        if rule.get("enabled", True) and rule.get("check") and memo_declines(rule) is None
    ]
    if not memoisable:
        broken.append(
            "memo census: no rule is memoisable at all — either every rule declined or the "
            "declaration reads as something this engine cannot see, and a memo with no "
            "subject cannot be driven"
        )
        say(f"memo census: answered {answered} of {probes} probes")
        return

    # -- 1. BYTE-STABILITY. Two passes over one tree, same keys. -------------
    first = {str(r["id"]): memo_key(r)[0] for r in memoisable}
    second = {str(r["id"]): memo_key(r)[0] for r in memoisable}
    if first == second and all(k for k in first.values()):
        answered += 1
    else:
        undecided = sorted(rid for rid, key in first.items() if not key)
        broken.append(
            "memo census: the per-rule key is not byte-stable on one tree "
            f"(undecidable: {undecided[:5] or 'none'}; disagreed: "
            f"{sorted(r for r in first if first[r] != second.get(r))[:5]}) — a key that "
            "moves while nothing else does reuses nothing and re-keys everything"
        )

    # -- 2. ONE RULE'S BYTE RE-KEYS ONE RULE. --------------------------------
    # The isolation the whole per-rule shape exists for: a reword of rule A's
    # statement must not re-scan rule B. Driven on a COPY of the mapping, so
    # the tree and `RULES` are untouched.
    victim = memoisable[0]
    vid = str(victim["id"])
    moved = dict(victim)
    moved["statement"] = str(victim.get("statement", "")) + " "
    after = {str(r["id"]): memo_key(moved if str(r["id"]) == vid else r)[0] for r in memoisable}
    rekeyed = sorted(rid for rid in first if first[rid] != after.get(rid))
    if rekeyed == [vid]:
        answered += 1
    else:
        broken.append(
            f"memo census: one byte in rule {vid}'s statement re-keyed {len(rekeyed)} rule(s) "
            f"({rekeyed[:6]}) — a per-rule key that moves its neighbours is one key wearing "
            "fifty-seven names"
        )

    # -- 3-7. THE CONSULT, over a stub check and a scratch memo of its own. --
    home = Path(tempfile.mkdtemp(prefix="djb-memo-census."))
    calls: dict[str, int] = {"n": 0}

    def stub(root: Path, rule: dict) -> CheckResult:
        calls["n"] += 1
        result = CheckResult()
        result.hit("apps/example/services.py", 1, f"the census stub's finding for {rule['id']}")
        result.count("probe", 1)
        return result

    scratch = {
        "id": "zzz-memo-census",
        "enabled": True,
        "check": "zzz_memo_census_stub",
        "doc": {"file": "quality/rules.yaml", "contains": "rules"},
        "scope": {},
    }
    saved_state = dict(memo_state)
    REGISTRY["zzz_memo_census_stub"] = stub
    try:
        memo_state["bypass"] = False
        memo_state["home"] = str(home)

        # 3. A COLD CONSULT SCANS AND BANKS; THE SECOND IS A HIT THAT REPLAYS
        #    THE RED. A hit that printed `ok` over a banked violation is the
        #    failure this engine cannot survive, so the finding is compared
        #    rather than the count.
        memo_reset()
        cold = memo_consult(scratch, "zzz_memo_census_stub")
        warm = memo_consult(scratch, "zzz_memo_census_stub")
        replayed = [str(f) for f in warm.findings] == [str(f) for f in cold.findings]
        if (
            calls["n"] == 1
            and memo_counts["hits"] == 1
            and memo_counts["misses"] == 1
            and replayed
            and warm.targets_matched == cold.targets_matched
        ):
            answered += 1
        else:
            broken.append(
                f"memo census: two consults on one tree ran the check {calls['n']} time(s) "
                f"for {memo_counts['hits']} hit(s) and {memo_counts['misses']} miss(es), "
                f"replaying the finding: {replayed} — a hit that does not replay the red is a "
                "cache that turned a violation into a pass"
            )

        # 4. A MOVED INPUT MISSES THAT RULE AND NAMES THE COMPONENT.
        memo_reset()
        moved_scratch = dict(scratch)
        moved_scratch["statement"] = "one byte the previous key never saw"
        memo_consult(moved_scratch, "zzz_memo_census_stub")
        named = [ln for ln in memo_lines if "miss(rule)" in ln]
        if memo_counts["misses"] == 1 and memo_counts["hits"] == 0 and named:
            answered += 1
        else:
            broken.append(
                "memo census: a moved byte in the rule's own text did not print "
                f"`rule <id>: miss(rule)` ({memo_lines or 'nothing printed'}) — a miss that "
                "cannot name what moved is a re-scan nobody can attribute"
            )

        # 5. `memo: no` SCANS ALWAYS, AND A BARE DECLARATION IS EXIT 2.
        memo_reset()
        declining = dict(scratch)
        declining["memo"] = {"no": "the census's own scratch rule, declining on purpose"}
        before = calls["n"]
        memo_consult(declining, "zzz_memo_census_stub")
        memo_consult(declining, "zzz_memo_census_stub")
        bare = dict(scratch)
        bare["memo"] = {"no": ""}
        before_broken = len(broken)
        memo_consistency([bare])
        refused = broken[before_broken:]
        del broken[before_broken:]
        if (
            calls["n"] - before == 2
            and memo_counts["hits"] == 0
            and memo_counts["declined"] == 2
            and refused
        ):
            answered += 1
        else:
            broken.append(
                f"memo census: a declining rule was consulted {calls['n'] - before} time(s) "
                f"with {memo_counts['hits']} hit(s), and a reasonless declaration was refused "
                f"{len(refused)} time(s) — a `memo: no` nobody has to justify is an off switch"
            )

        # 6. AN UNDECIDABLE KEY SCANS, PRINTED, AND NEVER HITS. Its victim is a
        #    scratch rule whose scope names a directory no tree has — the shape
        #    `--selftest-inputs`' own canaries use, and it carries no made-up
        #    docs path (the dangling-docs census reads those).
        memo_reset()
        blind = dict(scratch)
        blind["scope"] = {"allow_import": [{"path": "apps/nowhere/*.py"}]}
        before = calls["n"]
        memo_consult(blind, "zzz_memo_census_stub")
        memo_consult(blind, "zzz_memo_census_stub")
        said = [ln for ln in memo_lines if "memo undecidable" in ln and "scanned" in ln]
        if (
            calls["n"] - before == 2
            and memo_counts["undecidable"] == 2
            and memo_counts["hits"] == 0
            and len(said) == 2
        ):
            answered += 1
        else:
            broken.append(
                "memo census: a rule whose scope cannot be derived was consulted "
                f"{calls['n'] - before} time(s) for {memo_counts['hits']} hit(s) and said "
                f"{len(said)} undecidable line(s) — an undecidable key that reads the cache is "
                "a verdict for a tree nobody measured"
            )

        # 7. PRUNING. Twenty-five keys planted, twenty survive — the newest.
        memo_reset()
        planted = []
        for n in range(MEMO_KEEP + 5):
            keyed = dict(scratch)
            keyed["statement"] = f"pruning probe {n}"
            key, components, why = memo_key(keyed)
            if not key:
                break
            memo_write(home, "zzz-memo-census", key, components, CheckResult())
            planted.append(key)
        kept = sorted((home / "zzz-memo-census").glob("*.json"))
        if len(planted) == MEMO_KEEP + 5 and len(kept) == MEMO_KEEP:
            answered += 1
        else:
            broken.append(
                f"memo census: {len(planted)} keys banked left {len(kept)} entries where "
                f"{MEMO_KEEP} was recorded — a memo directory that only grows is a cache with "
                "no resource limit, which is the line every cache in this system owes"
            )

        # 8. THE BYPASS IS REAL, AND A PLANTED FALSE ENTRY IS THE PROOF.
        #    A word printed by the thing under test is not evidence that it did
        #    anything. So: bank an entry saying THIS RULE FOUND NOTHING, under
        #    the very key the consult will compute, and then ask for the answer
        #    twice — once with the bypass off, where the false entry MUST win
        #    (that is what makes it a real plant), and once with it on, where
        #    the check MUST run and its finding MUST come back.
        memo_reset()
        lying = dict(scratch)
        lying["statement"] = "the planted false entry's rule"
        key, components, _why = memo_key(lying)
        memo_write(home, str(lying["id"]), str(key), components, CheckResult())
        memo_state["bypass"] = False
        suppressed = memo_consult(lying, "zzz_memo_census_stub")
        memo_state["bypass"] = True
        through = memo_consult(lying, "zzz_memo_census_stub")
        if not suppressed.findings and len(through.findings) == 1:
            answered += 1
        else:
            broken.append(
                "memo census: the planted false entry returned "
                f"{len(suppressed.findings)} finding(s) with the memo on and "
                f"{len(through.findings)} with the self-test's bypass on — the bypass is "
                "proved by a plant the memo would otherwise have silenced, never by a printed "
                "word, and one of those two halves did not behave"
            )
    finally:
        memo_state.clear()
        memo_state.update(saved_state)
        REGISTRY.pop("zzz_memo_census_stub", None)
        shutil.rmtree(home, ignore_errors=True)
        memo_reset()

    say(f"memo census: answered {answered} of {probes} probes")


def _captured(argv: list[str]) -> tuple[int, str]:
    """`main(argv)`'s status and stdout, for the CLI census below."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(argv)
    return rc, buf.getvalue()


def cli_census() -> None:
    """The reader half of the self-test: the two flags a red points people at.

    Canaries B.5-2 and B.5-6's sibling. `--explain` and the listing are what
    the trailer's `next:` line promises, and a promise nothing drives is a
    promise that can be deleted by accident — the same argument every drive in
    `scripts/tests/` carries. Driven through `main`'s own argv dispatch, not
    through the printers, because the claim under test is that TWO NAMES reach
    ONE printer, and calling the printer twice would prove only
    that it is deterministic.
    """
    probes = 4
    answered = 0
    enabled = [str(r["id"]) for r in RULES if r.get("enabled", True)]
    if not enabled:
        broken.append("cli census: no enabled rule to explain — the listing would be empty")
        say(f"cli census: --explain/--rules answered {answered} of {probes} probes")
        return
    by_explain = _captured(["--explain"])
    by_rules = _captured(["--rules"])
    if by_explain == by_rules:
        answered += 1
    else:
        broken.append(
            "cli census: `--explain` with no id and `--rules` printed different things — "
            "they are one printer with two names, and a second implementation is the drift "
            "rule 17 exists against"
        )
    listed = [line for line in by_rules[1].splitlines() if line.strip()]
    if len(listed) == len(RULES):
        answered += 1
    else:
        broken.append(
            f"cli census: the listing printed {len(listed)} lines for {len(RULES)} rules — a "
            "rule a reader cannot see listed is a rule whose red points at nothing"
        )
    rc, text = _captured(["--explain", enabled[0]])
    if rc == 0 and "valve:" in text and "statement:" in text:
        answered += 1
    else:
        broken.append(
            f"cli census: `--explain {enabled[0]}` exited {rc} without printing the rule's own "
            "statement and valve — the `next:` line on every red points here"
        )
    rc, text = _captured(["--explain", "zzz-no-such-rule"])
    if rc == 2 and "listing" in text:
        answered += 1
    else:
        broken.append(
            f"cli census: `--explain` of an unknown id exited {rc} — an unknown id is "
            "could-not-look (exit 2) naming the listing, never a silent nothing"
        )
    # The same reason the trailer census says its count out loud: these four
    # probes are the only thing standing between the `next:` line on every red
    # and a flag somebody deleted. A silent pass is a pass nobody can miss.
    say(f"cli census: --explain/--rules answered {answered} of {probes} probes")
    inputs_census()


def inputs_census() -> None:
    """The third reader, driven: `--selftest-inputs` and the ways it must refuse.

    A SECOND SENTENCE rather than four more probes on the one above, and the
    reason is the census grammar itself: `cli census: --explain/--rules answered
    4 of 4 probes` is a claim a drive asserts by its exact words
    (`scripts/tests/test_gate_explain.sh:937`), and growing its count would edit
    a file outside `quality/` to say nothing new. Two readers, two counted
    sentences, one prefix — the same shape the seam and residence censuses
    already print.

    Driven through `main`'s own argv dispatch, never through `selftest_inputs()`,
    because the claim under test includes the FLAG: a reader that works and a
    flag nobody wired to it look identical from inside the printer.
    """
    probes = 6
    answered = 0

    rc, text = _captured(["--selftest-inputs"])
    lines = [ln for ln in text.splitlines() if ln.strip()]
    relative = all(not ln.startswith("/") and ".." not in ln.split("/") for ln in lines)
    if rc == 0 and lines and lines == sorted(lines) == sorted(set(lines)) and relative:
        answered += 1
    else:
        broken.append(
            f"cli census: `--selftest-inputs` exited {rc} with {len(lines)} line(s) that are not "
            "a sorted, duplicate-free, checkout-relative list — a key computed over it would "
            "depend on the order the engine happened to walk the tree in"
        )

    rc2, text2 = _captured(["--selftest-inputs"])
    if (rc, text) == (rc2, text2):
        answered += 1
    else:
        broken.append(
            "cli census: `--selftest-inputs` printed two different things on one tree — a "
            "printer that is not byte-stable cannot key anything"
        )

    # EVERY POPULATION IS REPRESENTED, checked without re-using `_expand_input`
    # — a probe that re-derives through the code under test proves only that the
    # code is deterministic. A scope naming a directory is COVERED when the
    # listing carries something under it, which is the claim a key needs.
    listed = set(lines)

    def covered(want: str) -> bool:
        want = want.rstrip("/")
        return want in listed or any(p.startswith(want + "/") for p in listed)

    scoped = [
        p
        for rule in RULES
        if rule.get("enabled", True)
        for _trail, p in _scope_paths(rule.get("scope") or {})
    ]
    docs = [
        str((rule.get("doc") or {}).get("file") or "")
        for rule in RULES
        if rule.get("enabled", True)
    ]
    # The walk, re-derived here from SCOPE_KINDS rather than from `_kind_walk()`
    # — two spellings of one population on purpose, so a triple dropped from the
    # walk is a disagreement rather than a shared blind spot.
    walked = [
        str(p.relative_to(ROOT))
        for kind in SCOPE_KINDS.values()
        for root in kind.get("roots") or []
        if (ROOT / str(root)).is_dir()
        for suffix in kind.get("suffixes") or []
        for p in (ROOT / str(root)).rglob(f"*{suffix}")
        if not (W.kind_skip_dirs(kind) & set(p.relative_to(ROOT).parts))
    ]
    # A FILE ROOT is its own member of the walk — see `all_overrides`. Dead on a
    # tree with no drawer, for the same reason the branch there is.
    walked.extend(
        root
        for kind in SCOPE_KINDS.values()
        for root in (str(r) for r in (kind.get("roots") or []))
        if (ROOT / root).is_file()
    )
    tracked_now = _tracked_paths()[0]
    populations = {
        "the engine's own text": ["quality/rules.yaml", "quality/gate.py"],
        "a rule's scope": scoped,
        "a plant path": plant_paths(),
        # Every enabled rule's doc anchor — `consistency()` reads it on every
        # run, so a rule's prose is an input (the verifier's F1).
        "a rule's doc": docs,
        # The SCOPE_KINDS walk, tracked half — the files the live checks read
        # and no `scope:` names (the verifier's F2).
        "the scope-kind walk": sorted(set(walked) & tracked_now),
    }
    missing = {
        name: sorted(w for w in want if not covered(w))[:3]
        for name, want in populations.items()
        if not all(covered(w) for w in want)
    }
    if not missing and all(want for want in populations.values()):
        answered += 1
    else:
        broken.append(
            f"cli census: `--selftest-inputs` did not carry every population it derives: "
            f"{missing or 'one population derived to nothing'} — an input it cannot see is a "
            "byte that changes the verdict without changing the key"
        )

    hard_ok = True
    for value, why_read in HARDCODED_READS:
        found, why = _expand_input(value, _tracked_paths()[0])
        if why or not set(found) <= listed:
            hard_ok = False
            broken.append(
                f"cli census: the hard-coded read {value!r} ({why_read}) is not in "
                f"`--selftest-inputs` — {why or 'its expansion is not all listed'}"
            )
    if hard_ok:
        answered += 1

    # THE TWO CANARIES, and each builds its own victim: a rule that exists for
    # the length of one probe — one whose scope names a directory no tree has,
    # one whose DOC names a file no tree has. The listing must refuse each BY ID
    # and print nothing; a shorter list is the failure this reader is shaped
    # against, and it is the exact shape the verifier's F1/F2 plants had.
    for probe_id, scratch in (
        (
            "zzz-census-no-such-scope",
            {
                "id": "zzz-census-no-such-scope",
                "enabled": True,
                "doc": {"file": "quality/rules.yaml"},
                "scope": {"allow_import": [{"path": "apps/nowhere/*.py"}]},
            },
        ),
        # The doc half of the canary carries NO PATH LITERAL, deliberately: a
        # made-up `docs/…md` spelled here is a dangling pointer to the
        # documentation census (`scripts/check.sh`'s dangling-docs leg caught
        # exactly that), and a canary may not buy its victim with a second
        # census's red. A rule with no doc file at all reaches the same branch.
        (
            "zzz-census-no-such-doc",
            {"id": "zzz-census-no-such-doc", "enabled": True, "doc": {}},
        ),
    ):
        RULES.append(scratch)
        try:
            rc3, text3 = _captured(["--selftest-inputs"])
        finally:
            RULES.remove(scratch)
        printed = [
            ln for ln in text3.splitlines() if ln.strip() and not ln.strip().startswith(("‼", "!!"))
        ]
        if rc3 == 2 and probe_id in text3 and not printed:
            answered += 1
        else:
            broken.append(
                f"cli census: the scratch rule {probe_id} left `--selftest-inputs` at exit "
                f"{rc3} with {len(printed)} path(s) printed — a population it cannot derive is "
                "could-not-look naming the rule, never a shorter list"
            )

    say(f"cli census: --selftest-inputs answered {answered} of {probes} probes")
    memo_census()


def live_scan(diff_ref: str | None, *, terse: bool = False) -> None:
    # (line, status) — the status is carried beside the text rather than
    # re-derived from it, because `--terse` drops exactly the `ok` rows and a
    # reader of the count line has to be able to add them back up.
    per_rule: list[tuple[str, str]] = []
    counts = {"ok": 0, "RED": 0, "skipped": 0}
    memo_reset()
    django_findings = [] if os.environ.get("GATE_SKIP_DJANGO_LEG") else run_django_leg()
    diff_results = C.diff_checks(ROOT, diff_ref, RULES_BY_ID) if diff_ref else {}

    for rule in RULES:
        rid = str(rule["id"])
        name = rule.get("name", "")
        if not rule.get("enabled", True):
            counts["skipped"] += 1
            per_rule.append(
                (
                    f"  rule {rid} {name}: DISABLED — "
                    f"{rule.get('disabled_reason', 'no reason recorded')}",
                    "skipped",
                )
            )
            continue
        kept, targets, skip = run_rule(rule)
        if skip:
            # THE PRINTED SKIP, and the line IS the criterion. A rule that
            # legally looked at nothing and a rule that quietly stopped working
            # produce the same silence, so the only thing that tells a reader
            # which one happened is a sentence naming the tree and saying the
            # floors derived to zero.
            #
            # F3 (Vra, 2026-08-31): a rule that could NOT look — its `broken.append`
            # already fired above, inside `run_rule` — is a THIRD status, never
            # this one and never `ok` below. Without this branch its line here
            # read `ok` while the true reason surfaced only in the broken
            # section further down, which a reader meets after the per-rule
            # table this line belongs to.
            counts["skipped"] += 1
            if skip.startswith(COULD_NOT_LOOK):
                per_rule.append((f"  rule {rid} {name}: {skip}", "skipped"))
            else:
                per_rule.append((f"  rule {rid} {name}: SKIPPED — {skip}", "skipped"))
            continue
        for rule_id, line in django_findings:
            if rule_id == rid:
                # The django leg reports through `manage.py check`, whose lines
                # are already pathed prose; there is no Finding to read a kind
                # off, so the trailer falls back to the default token.
                record_violation(rid, line)
        if rid in diff_results:
            diff_kept, _ = apply_overrides(rid, diff_results[rid].findings)
            kept = kept + diff_kept
        for finding in kept:
            record_violation(rid, finding, path=finding.path)
        shown = ", ".join(f"{k}={v}" for k, v in sorted(targets.items())) or "django-leg"
        status = "ok" if not kept and not any(r == rid for r, _ in django_findings) else "RED"
        counts[status] += 1
        per_rule.append((f"  rule {rid} {name}: {status} ({shown})", status))

    for problem in check_budgets():
        violations.append(problem)

    say(
        f"House rules: {len(RULES)} rules · {counts['ok']} ok · {counts['RED']} RED · "
        f"{counts['skipped']} skipped"
    )
    memo_report()
    # `--terse`: the ok rows are ~50 lines of other apps' good news
    # between a builder and their own finding, and the count line above already
    # holds the number. What it drops is EXACTLY the rows whose status is `ok`
    # and the standing-override detail — never a RED, never a SKIPPED, never a
    # COULD-NOT-LOOK, and never the ENFORCEMENT BROKEN block, which `main`
    # prints whatever this flag says.
    for line, status in per_rule:
        if terse and status == "ok":
            continue
        say(line)

    standing = [
        (r, p, ln, reason) for r, p, ln, reason in all_overrides() if len(reason) >= MIN_REASON
    ]
    say(f"overrides (standing): {len(standing)}")
    if not terse:
        for rule_id, path, lineno, reason in standing:
            say(f"  rule-{rule_id} {path}:{lineno} — {reason}")
    for rule_id, path, lineno, reason in all_overrides():
        if len(reason) < MIN_REASON:
            # F2 (Vra, 2026-08-31): the remedy must be paste-able where the finding
            # lives — a `.ts` file's own reader must not be told to write `#`.
            marker = W.comment_token(W.kind_of_path(path, SCOPE_KINDS))
            record_violation(
                rule_id,
                f"{path}:{lineno}: override `{marker} rule-{rule_id}` with no reason — an "
                "escape hatch nobody has to justify is an off switch",
                path=path,
            )
    for note in notes:
        say(f"  {note}")


#: THE ARGUMENT GRAMMAR, IN ONE STRING. Two refusals print it — an unknown
#: argument and a `--fold-map` with nothing after it — and two spellings of one
#: list is exactly how a flag comes to exist that no refusal mentions.
GRAMMAR = (
    "quality.gate takes --selftest, --selftest-inputs, --diff <ref>, "
    "--fold-map <previous rules.yaml> [<template rules.yaml>] [--template-tree <dir>], "
    "--terse, --explain [<id>] or --rules"
)


def main(argv: list[str]) -> int:
    diff_ref: str | None = None
    fold_map_previous: str | None = None
    fold_map_template: str | None = None
    fold_map_template_tree: str | None = None
    mode = "scan"
    terse = False
    explain_id: str | None = None
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--selftest":
            mode = "selftest"
        elif arg == "--selftest-inputs":
            mode = "inputs"
        elif arg == "--terse":
            terse = True
        elif arg == "--rules":
            mode = "listing"
        elif arg == "--explain":
            # `--explain` alone IS the listing: one printer, two names, so
            # `--rules` and a reader's bare `--explain` cannot come to
            # disagree about what the rule set is.
            if args and not args[0].startswith("-"):
                mode, explain_id = "explain", args.pop(0)
            else:
                mode = "listing"
        elif arg == "--diff":
            if not args:
                say("‼ --diff needs a ref")
                return 2
            diff_ref = args.pop(0)
        elif arg == "--fold-map":
            # THE ARGUMENT IS NOT OPTIONAL, and the refusal carries the command
            # that produces it. The reader runs on a tree in the middle of a
            # merge, where the file it needs is not on disk at all: a bare
            # `--fold-map` that fell back to anything would map the tree
            # against itself and print a rename list of no renames.
            if not args or args[0].startswith("-"):
                say(
                    "‼ --fold-map needs the path to your PREVIOUS quality/rules.yaml — the one "
                    "before the merge: `git show <your pre-merge sha>:quality/rules.yaml > "
                    "/tmp/previous-rules.yaml`. " + GRAMMAR
                )
                return 2
            mode, fold_map_previous = "fold-map", args.pop(0)
            # THE SECOND PATH IS THE TEMPLATE SIDE, AND IT IS OPTIONAL. Taking
            # it positionally rather than behind a flag is what keeps the
            # refusals' one-line remedy a line somebody pastes; a following
            # FLAG is still a flag, by the same test the first argument uses.
            if args and not args[0].startswith("-"):
                fold_map_template = args.pop(0)
        elif arg == "--template-tree":
            if not args or args[0].startswith("-"):
                say("‼ --template-tree needs a directory. " + GRAMMAR)
                return 2
            fold_map_template_tree = args.pop(0)
        else:
            # A mistyped flag must never be a silently different run.
            say(f"‼ unknown argument {arg!r}: " + GRAMMAR)
            return 2

    if fold_map_template_tree is not None and mode != "fold-map":
        # A flag that only means something to one mode must never be a silently
        # ignored flag in another: the same law `--tesre` is refused under. THE
        # `mode` CLAUSE IS THE POINT AND IT WAS MISSING (F1, HOTFIX-RULEMAP-2F):
        # without it this guard fired on the one mode the flag EXISTS for, so
        # `--template-tree` was reachable from the function and dead from the
        # command line — the shape a pytest suite that calls `fold_map_lines`
        # and never `main` cannot see, which is why the case that pins it is an
        # sh probe through `main`s own argv dispatch.
        say("‼ --template-tree is only meaningful with --fold-map. " + GRAMMAR)
        return 2

    # THE FOUR READERS RETURN BEFORE ANYTHING MEASURES. `--explain`, the
    # listing, `--selftest-inputs` and `--fold-map` read the parsed yaml and the
    # tree's own file names, and nothing else: the first two are how a builder holding a
    # red finds out what to do about it, and the third is what a banked verdict
    # is keyed on — so all three must answer on a tree whose plants are dirty or
    # whose consistency is broken, the states in which a reader most needs them.
    # The inputs reader in particular must answer on a tree the self-test cannot
    # run on, or a could-not-look would silently become a cache hit.
    if mode == "listing":
        return rules_listing()
    if mode == "explain":
        return explain(str(explain_id))
    if mode == "inputs":
        return selftest_inputs()
    if mode == "fold-map":
        # The loudest case of all: a tree mid-merge, whose plants may be dirty
        # and whose consistency may be broken precisely BECAUSE the ids
        # collided. A reader that refused to answer there would be a reader
        # nobody could use on the only day they need it.
        return fold_map(str(fold_map_previous), fold_map_template, fold_map_template_tree)

    # BEFORE ANYTHING MEASURES ANYTHING. A tree carrying a dead run's fixtures
    # is a tree every leg below would read wrongly, and the failure is silent in
    # the direction that matters: a planted negative reports nothing at all.
    refuse_stale_plants()
    consistency()
    # THE MEMO'S OWN SHAPE, refused in the same breath and for the same reason
    # every other declared field is: a `memo: no` nobody has to justify is an
    # off switch. It is a SIBLING of `consistency()` rather than a clause
    # inside it because the criteria that asked for the memo put `consistency()`
    # out of territory; the position in `main` is what makes it identical in
    # effect — before anything measures, and exit 2 outranks a pass.
    memo_consistency()
    if mode == "selftest":
        # THE SELF-TEST NEVER CONSULTS OR WRITES THE MEMO, and the line is
        # printed rather than assumed. Every canary plants a violation into the
        # real tree and demands its rule finds it; a rule that replayed a
        # banked answer would go green over a tree it never read, and the
        # dead-canary exit 2 this whole engine turns on would be the thing the
        # memo silenced. The proof that the bypass is real, rather than a
        # printed word, is `memo_census`'s planted FALSE entry below.
        memo_state["bypass"] = True
        say("memo: bypassed (selftest) — every rule scans; the memo is neither read nor written")
        if not broken:
            selftest()
    elif not broken:
        live_scan(diff_ref, terse=terse)

    seen: set[str] = set()
    deduped = [v for v in violations if not (v in seen or seen.add(v))]
    if broken:
        # NEVER SUPPRESSED BY `--terse`. Exit 2 outranks a pass, and a flag
        # whose whole job is to print less must not be able to print less of
        # the one section that says the enforcement itself stopped working.
        say("ENFORCEMENT BROKEN (exit 2 — outranks any pass):")
        for b in broken:
            say(f"  !! {b}")
    if deduped:
        say("Violations:")
        # Grouped by rule, in the order each rule first reported, so a rule
        # with twelve findings owes its reader ONE trailer rather than twelve.
        order: list[str] = []
        groups: dict[str, list[str]] = {}
        for v in deduped:
            rid = violation_rule.get(v, "")
            if rid not in groups:
                groups[rid] = []
                order.append(rid)
            groups[rid].append(v)
        for rid in order:
            for v in groups[rid]:
                say(f"  x {v}")
            for line in trailer_for(rid):
                say(line)
    if not broken and not deduped:
        if mode == "selftest":
            say("selftest clean: every canary fired, every negative stayed silent.")
        else:
            say(f"House rules: {len(RULES)} rules · all scopes bound · clean.")
    return 2 if broken else (1 if deduped else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
