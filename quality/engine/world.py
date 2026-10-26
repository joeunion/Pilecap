"""THE PRODUCT'S DRAWER (EP2)."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

import yaml

from apps.core.reach import EXTENSIONS_KEY, extension_problems
from quality import checks as C
from quality import partition as PART
from quality import worlds as W
from quality.engine._hub import _DOC, ROOT
from quality.engine.lexicon import PRODUCT_VERBS_KEY, product_verb_problems

# --- THE PRODUCT'S DRAWER (EP2) -------------------------------------------------
#
# THE SUBJECT. `quality/rules.yaml` is a TEMPLATE-OWNED file. A product that wants a rule of its
# own — and every product does — had nowhere to put it but inside that file, so every fold met a
# conflict in the one file whose conflicts are the most expensive on the tree, and the product's
# rules were re-applied by hand each release (the consumer's own census measured it).
#
# THE DRAWER. `quality/local/rules.yaml` is loaded BESIDE the template's, at this one loader, and
# the template never writes a byte of it. Its fixtures live under
# `quality/local/{canary,negative}/<id>/` and its check-v1 runners under `quality/local/runners/`,
# so a product adds a rule without touching one template-owned path and a fold has nothing to
# merge.
#
# EIGHT KEYS AND NO MORE. `rule_id_namespace`, `template_rule_ids_through`, `rules:`, `ratchets:`,
# `scope_kinds:`, `service_verbs:`, `scope_extensions:`, `identity_shape:` (tests only).
# Anything else — a local `seam:`, a local `selftest_residence_backlog:` — is exit 2 NAMING THE KEY
# AND THE FILE, because each is a statement about the ENGINE rather than a rule, and an engine a
# product can reconfigure in a file the template never reads is one it cannot vouch for.
#
# WHY `scope_kinds:` IS THE FIFTH, AND WHY IT WAS THE FOURTH'S MISTAKE. D1 read it as an engine
# statement and refused it by name. It is not: a scope kind is WHAT A RULE IS ABOUT — its roots,
# its suffixes, its valve token — and the template declares exactly two, `py` (apps, config) and
# `js` (frontend). A product rule whose subject is a ledger, a doc, a `.env.example` or a canary
# under `quality/local/` therefore had NO kind it could name, and `check_v1._refuse_outside_roots`
# refused its runner's every finding: `path 'docs/product/queue.md' is outside the roots this rule
# declares (apps, config)`. The first consumer met it on four rules that had run as in-process
# checks for a year. So the key is the drawer's, under the same law as every other drawer: a
# product kind may NOT reuse a template kind's name (refused, naming both files), its roots may
# name any directory or file this tree carries, and `SCOPE_KINDS` is the UNION — which is what
# makes `kind_roots`, the override walk, the memo's walk and every floor read the product's roots
# without one template-owned byte moving.
#
# `service_verbs:` (7th) and `scope_extensions:` (8th) ARE THE FIFTH'S REASON: an entry a product
# adds to a template rule's list — a verb, an app label, a module, an open view — is what a rule is
# about, never the engine. `scope_extensions:` is keyed by rule id, each value the rule's own list
# shape, and opens ONLY a list the rule marks `reach: product`; the one reader is
# `apps.core.reach.extended_scope` (verbs: `quality.engine.lexicon`). A platform-only list, a
# non-template rule, a template entry or a malformed word is refused here naming it.
#
# THE TWO NAMESPACE KEYS LIVE HERE AND NOWHERE ELSE. D1 put them in the template-owned file because
# the drawer did not exist yet; this is the home they were always for. A tree that still carries
# either of them in `quality/rules.yaml` is refused with the line that names the move — a product
# mid-adoption is exactly who hits it, and a refusal that says which two lines to cut into which
# file costs them a minute instead of an afternoon.
#
# ABSENT IS BYTE-IDENTICAL. No drawer means `LOCAL_DOC` is `{}`, `LOCAL_RULES` is empty, and every
# reader, census, digest and self-test number is the number the template printed before the drawer
# existed. That negative is the drive's assertion, not this comment's claim.
LOCAL_DIR = ROOT / "quality" / "local"
LOCAL_RULES_PATH = LOCAL_DIR / "rules.yaml"
LOCAL_CANARY_DIR = LOCAL_DIR / "canary"
LOCAL_NEGATIVE_DIR = LOCAL_DIR / "negative"
LOCAL_RUNNER_DIR = LOCAL_DIR / "runners"


def world_module() -> ModuleType:
    """The one module that holds the drawer's paths, ids and namespace; rebind them here."""
    # A reader in another module reads `world_module().<NAME>`: a name bound by import is a copy.
    return sys.modules[world_module.__module__]


#: The whole vocabulary of the drawer. Closed, and the refusal names the key.
LOCAL_KEYS: frozenset[str] = frozenset(
    {
        "rule_id_namespace",
        "template_rule_ids_through",
        "rules",
        "ratchets",
        "scope_kinds",
        "service_verbs",
        "scope_extensions",
        "identity_shape",
    }
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
                f"quality/local/rules.yaml, the product's drawer (ADR gate-5). "
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
    platform_verbs = next(
        (
            (r.get("scope") or {})[PRODUCT_VERBS_KEY]
            for r in _DOC["rules"]
            if (r.get("scope") or {}).get(PRODUCT_VERBS_KEY)
        ),
        [],
    )
    problems.extend(product_verb_problems(loaded.get(PRODUCT_VERBS_KEY), platform_verbs))
    problems.extend(extension_problems(loaded.get(EXTENSIONS_KEY), _DOC["rules"]))
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
#: A Django check id -> the rule that owns it, for the system-check leg.
DJANGO_ID_TO_RULE: dict[str, str] = {
    str(cid): str(rule["id"]) for rule in RULES for cid in rule.get("django_check_ids") or []
}

#: The ids the drawer contributed. Read by the fixture-home resolver below, by
#: the `[local]` tag both readers print, and by the ratchet and plant censuses.
LOCAL_RULE_IDS: frozenset[str] = frozenset(str(r["id"]) for r in LOCAL_RULES)


def is_local_rule(rule_id: str) -> bool:
    """Did this id come out of the product's drawer?"""
    return str(rule_id) in LOCAL_RULE_IDS


def frozen_classes(rule: dict) -> frozenset[str]:
    """The finding classes a rule's `frozen:` names: a recorded number that may only fall.

    At zero the class has no `ratchets:` line and a finding is a violation with no
    paste line; a drawer never records one (ADR gate-6).
    """
    return frozenset(str(k) for k in (rule.get("frozen") or ()))


def is_frozen(rule: dict, klass: str) -> bool:
    """Is this class frozen — by name, or by its `<member>.<class>` suffix on a member rule."""
    names = frozen_classes(rule)
    klass = str(klass)
    if klass in names:
        return True
    return is_member_rule(rule) and klass.partition(".")[2] in names


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
#: `platform_apps`: the platform's own backlogs are the template's to
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
            # THE REFUSAL THAT MAKES THE PARTITION TRUE RATHER THAN POLITE, and it is
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
            # refused it with a sentence about an app directory named `literal`. A product
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
            if not drawer_rule and is_frozen(rule, name):
                problems.append(
                    f"{where} rule {rid}: class {name!r} is frozen on rule {rid} (its "
                    "`frozen:`) — a drawer may not record it, which would lift the template's "
                    "number; fix each finding, or excuse it where it stands with the rule's "
                    f"valve (`--explain {rid}`)"
                )
                continue
            if not drawer_rule and is_member_rule(rule):
                app_part = name.split(".", 1)[0]
                if (ROOT / "apps" / app_part / "apps.py").is_file():
                    problems.append(
                        f"{where} rule {rid}: class {name!r} is app {app_part!r}'s floor — it "
                        f"lives in apps/{app_part}/apps.py `ratchet_floors`, keyed "
                        f'"{rid}.{name.partition(".")[2]}"'
                    )
                    continue
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

#: `(rule id, class) -> path:line` of every floor a MEMBER declared (rule `member_classes:`).
MEMBER_FLOOR_SOURCES: dict[tuple[str, str], str] = {}


def member_rules(rules: list[dict]) -> dict[str, list[str]]:
    """Rule id → the classes it counts per member; their floors live with the member."""
    return {
        str(r["id"]): [str(c) for c in r["member_classes"]]
        for r in rules
        if r.get("member_classes")
    }


def is_member_rule(rule: dict) -> bool:
    """Does this rule keep its per-member floors with the members (`member_classes:`)?"""
    return bool(rule.get("member_classes"))


def _merge_member_floors() -> list[str]:
    """Fold every member's floors into its rule; a template app must declare (ADR gate-6)."""
    by_rule = member_rules(RULES)
    if not by_rule:
        return []
    problems: list[str] = []
    for rid in sorted(by_rule):
        rule = RULES_BY_ID[rid]
        if rule.get("ratchets"):
            problems.append(
                f"quality/rules.yaml rule {rid} keeps `ratchets:` beside `member_classes:` — "
                "a member's floor lives in its own declaration "
                f"(apps/<label>/apps.py `{C.APP_FLOORS_ATTRIBUTE}`, or {C.MEMBER_FLOORS_FILE})"
            )
        rule["ratchets"] = {}
    floors, read = C.read_member_floors(ROOT, by_rule, PLATFORM_APPS or ())
    problems.extend(read)
    for floor in floors:
        key = (floor.rule, floor.klass)
        if key in MEMBER_FLOOR_SOURCES:
            problems.append(
                f"{floor.source}: {floor.klass!r} on rule {floor.rule} is also declared at "
                f"{MEMBER_FLOOR_SOURCES[key]} — one number, one home"
            )
            continue
        MEMBER_FLOOR_SOURCES[key] = floor.source
        RULES_BY_ID[floor.rule]["ratchets"][floor.klass] = floor.count
    return problems


def ratchet_home(rule_id: str, klass: str) -> str:
    """Which file this class's recorded number is written in."""
    if (str(rule_id), str(klass)) in DRAWER_RATCHET_CLASSES:
        return "quality/local/rules.yaml"
    source = MEMBER_FLOOR_SOURCES.get((str(rule_id), str(klass)))
    if source:
        return source.rsplit(":", 1)[0]
    rule = RULES_BY_ID.get(str(rule_id))
    if rule is not None and is_member_rule(rule):
        member = str(klass).partition(".")[0]
        if (ROOT / "apps" / member / "apps.py").is_file():
            return f"apps/{member}/apps.py"
        return C.MEMBER_FLOORS_FILE
    return "quality/rules.yaml"


def ratchet_paste_key(rule_id: str, klass: str) -> str:
    """The key a paste line spells: `"<rule>.<class>"` in an app's declaration, else the class."""
    if ratchet_home(rule_id, klass).endswith("/apps.py"):
        return f'"{rule_id}.{str(klass).partition(".")[2]}"'
    return str(klass)


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
    with), `kind_files` (where the standing override census looks), the memo's
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

# Member floors first, so the drawer's numbers add to the template's; every problem is exit 2.
_FLOOR_PROBLEMS: list[str] = _merge_member_floors()
_LOCAL_RATCHET_PROBLEMS: list[str] = _merge_local_ratchets()

# THE SELF-TEST'S OWN BACKLOG, and the only thing standing between "a rule that
# an environment variable can delete" and exit 2. Measured over the whole rule
# set; the members are printed by name on every self-test run. Same grammar as
# `ratchets:` (see this module's header), judged as one `quality.worlds.Bound`:
# one over it turns the whole census into violations, and a human commits the
# lower number in a diff somebody reads.
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
        "vendored directory stays out of the standing override census (ruled 2026-08-31)"
    ),
}
BUDGETS_PATH = ROOT / W.BUDGETS_FILE
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
# product's DRAWER, which no fold overwrites (ADR gate-5) — and every
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
# WHERE THEY LIVE (ADR gate-5, the drawer). Both keys are read from
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


def django_id_pattern(namespace: str | None = ...) -> re.Pattern[str]:  # type: ignore[assignment]
    """The one pattern a system-check line's id is read with: `(<prefix>.[EW]<n>)`.

    THE CHECK TAG IS THE ID'S FOURTH SPELLING (ADR gate-5), so the prefixes the
    leg reads are DERIVED the way `_valve_id_pattern` derives the valve's id
    half: the template's own `djb`, and — on a product tree — the namespace its
    drawer declares. A leg that read `djb.` alone never saw a product's check
    fire, and every one of that product's django canaries was dead on arrival.
    `namespace` defaults to THIS tree's declaration; a caller proving the
    derivation passes one.
    """
    if namespace is ...:
        namespace = RULE_ID_NAMESPACE
    prefixes = [TEMPLATE_CHECK_PREFIX] + ([str(namespace)] if namespace else [])
    alternation = "|".join(re.escape(p) for p in prefixes)
    return re.compile(rf"\(((?:{alternation})\.[EW]\d+)\)")


#: Compiled once from this tree's declaration; the live leg and the self-test's
#: django probe both read it, so the two can never disagree about which lines
#: are findings.
DJANGO_ID_RE = django_id_pattern()


PROBE_APP = "zzz_canary"
PROBE_DIR = ROOT / "apps" / PROBE_APP
PROBE_APPS_PY = f"""from django.apps import AppConfig


class ZzzCanaryConfig(AppConfig):
    name = "apps.{PROBE_APP}"
    depends_on: tuple[str, ...] = ("core", "accounts")
"""

OVERRIDE_RE = re.compile(rf"#\s*rule-({_valve_id_pattern()}):\s*(.*)$")

#: (ruled 2026-08-31): the sentinel `run_rule`'s third return element carries when a
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
        cached = re.compile(re.escape(comment) + rf"\s*rule-({_valve_id_pattern()}):\s*(.*)$")
        _OVERRIDE_RES[comment] = cached
    return cached


@dataclass
class Run:
    """One engine run's findings: enforcement that broke, violations, and notes."""

    broken: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


#: This process's one run; the door re-exports its lists by name, so a second would orphan them.
RUN = Run()

#: Which rule each violation line belongs to, RECORDED where the line is
#: appended rather than parsed back out of its text. The trailer below is
#: printed per rule, so the grouping has to be a fact the appender stated; a
#: regex over `rule (\d+):` would be a second, weaker answer to a question the
#: caller already knew. A violation with no entry here is a BUDGET — the one
#: finding class that has no rule id at all (`check_budgets`).
violation_rule: dict[str, str] = {}

#: Per rule id, the comment tokens the files it reported in are written with.
#: The valve a reader is handed has to be paste-able WHERE THE FINDING LIVES
#: (ruled 2026-08-31): a `.ts` file's own reader must not be told to write
#: `#`. A rule whose findings span two languages therefore prints its marker
#: once per kind present, never once per rule.
finding_kinds: dict[str, set[str]] = {}


def say(msg: str) -> None:
    print(msg)
