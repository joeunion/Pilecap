"""THE PER-RULE MEMO."""

from __future__ import annotations

import ast
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
from pathlib import Path

import yaml

from quality import tree as T
from quality import worlds as W
from quality.checks import REGISTRY, CheckResult, Finding
from quality.engine._hub import _DOC, ROOT, engine_number, engine_probes
from quality.reason_floor import MIN_REASON

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
# THE KEY, per rule, `rule-v2:<sha256>` over six components, each named so a
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
#   engine  `engine_closure` — `ENGINE_CLOSURE`, the top level and what they run, EXCEPT
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
# THE KEY IS RE-DERIVED AFTER THE SCAN, AND A KEY THAT MOVED BANKS NOTHING. The
# measured tree is read once per process and every rule's key comes from that
# one snapshot, while each rule's scan reads the working tree at its own later
# moment — so a second agent's edit landing in between was scanned, and its
# finding banked under the key of the tree BEFORE the edit and served, red, on
# every later run of that earlier tree (the consumer's fold, reproduced). A
# check reports what it found and never which bytes it read, so "the bytes as
# read" is not a fact this engine has; the measured tree read AGAIN after the
# scan, deriving the same components, is the proof that what the scan read is
# what the key names. When they differ the write is refused, counted, and the
# component that moved is printed. The cost is one more measured-tree read per
# MISS; a hit pays nothing. Locking the tree was rejected: two agents in one
# checkout is the breach, and the memo's job is not to lie about it. The schema
# moved to `rule-v2` with this, so every entry the old writer banked misses once
# (`miss(key)`) and is pruned by `MEMO_KEEP`.
#
# WHERE IT LIVES. `<git common dir>/djb-rules-memo/<rule id>/<sha>.json` — per
# checkout, shared across that checkout's worktrees exactly as the gate ledger
# is, and never committed. `DJB_RULES_MEMO_DIR` is the scratch seam a drive
# points at its own `mktemp -d`, refused when relative for
# `gate_ledger_path`'s reason; `DJB_RULES_NO_MEMO=1` is the valve that scans
# everything and is printed. `DJB_RULES_MEMO_PROBE_AFTER_KEY=<absolute path>` is
# a drive's seam and nothing else: `memo_probe` runs that executable between a
# rule's key and its scan, so a drive can move the tree inside the one window a
# key and a scan can disagree in. The gate never sets it, and a run that has it
# set prints so.
#
# WHAT IT CANNOT SEE, declared: a check that reads a path its walk does not
# name (population 4's blind spot, inherited exactly — the mitigation is
# structural rather than hopeful, since `engine` re-keys every rule the moment
# anybody writes such a read into `quality/`); the installed environment, which
# is why every rule whose check boots Django or shells out declines the memo in
# `rules.yaml` with a reason; and the first run after any byte under a kind's
# roots moves, which re-keys every rule of that kind — the memo pays on the
# SECOND and later reads of one tree (the hook, the loop, the verifier's
# consult and the push all measure one tree), never on the first; and a byte
# that lands AND is reverted between the two reads of the measured tree around
# one scan — both reads agree, the scan read the byte, and the write banks. The
# re-read shrinks the window from a whole run to one rule's scan; it does not
# close it.

MEMO_SCHEMA = "rule-v2"

#: How many entries per rule survive a write — `engine: memo: keep` in
#: quality/rules.yaml. A key is one tree, and a builder bouncing between two or
#: three trees wants all of them warm; the recorded number is that with room,
#: and the oldest by mtime go first.
MEMO_KEEP = engine_number("memo", "keep")

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
    "refused": 0,
    "probed": 0,
}

#: The ids that declared `memo: { no: ... }` and were reached this run, and the
#: one-line sentence each miss or undecidable key owes its reader.
memo_declined_ids: list[str] = []
#: The unmemoised scans `quality.scan_ahead` answered ahead of the loop, popped in rule order.
prefetched: dict[str, tuple] = {}
#: The `runner:` rules' replies (or refusals), run ahead on threads: each is a subprocess.
prefetched_runners: dict[str, object] = {}
memo_lines: list[str] = []


def memo_contract() -> str:
    """The memo's contract in one sentence: `memo_consult`'s first docstring line."""
    return (memo_consult.__doc__ or "").strip().splitlines()[0]


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
            RUN.broken.append(
                f"rule {rid}: `memo:` declares a bare `no:` key, which yaml reads as the "
                'BOOLEAN false — quote it (`"no": <reason>`), or this rule is memoised '
                "while its yaml says it is not"
            )
            continue
        if not isinstance(declared, dict) or set(declared) != {"no"}:
            RUN.broken.append(
                f"rule {rid}: `memo:` takes exactly one form — "
                "`memo: { no: <why this rule's check cannot be keyed on blobs> }`. "
                f"This one is {declared!r}, which the engine cannot read as a declaration; "
                "a rule that is memoised by accident replays an answer for inputs nobody "
                "named"
            )
            continue
        reason = str(declared.get("no") or "").strip()
        if len(reason) < MIN_REASON:
            RUN.broken.append(
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
        f"{memo_counts['undecidable']} undecidable, {memo_counts['refused']} refused) · "
        f"{len(declining)} memo: no ({' '.join(declining) or 'none'}), "
        f"{memo_counts['declined']} of them scanned here"
    )
    if os.environ.get("DJB_RULES_NO_MEMO"):
        say("  memo: DJB_RULES_NO_MEMO is set — every rule scanned; nothing read or written")
    probe = os.environ.get(MEMO_PROBE_ENV, "").strip()
    if probe:
        say(
            f"  memo probe: {MEMO_PROBE_ENV}={probe} ran {memo_counts['probed']} time(s) "
            "between a key and its scan — a drive's seam; the gate never sets it"
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


#: The run's snapshot of the measured tree; `None` until first asked. A drive
#: that moves a byte mid-process sets it back to `None` to re-read.
_MEASURED: tuple[dict[str, str], str] | None = None


def measured_blobs() -> tuple[dict[str, str], str]:
    """path -> blob sha over the MEASURED tree, and why it could not be read.

    `quality.tree.read_tree` — the one read of the tree — taken once per
    process: a gate run does not re-derive its world half way through.
    """
    global _MEASURED
    if _MEASURED is None:
        read = T.read_tree(ROOT)
        _MEASURED = (read.blobs, read.why)
    return _MEASURED


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
#: The engine's declared closure (CI-THIRD-2): its digest's roots, and its imports' boundary.
ENGINE_CLOSURE = (
    "quality/engine/",
    "quality/checks/",
    "quality/runners/",
    "quality/canary/",
    "quality/negative/",
    "quality/tools/",
    "quality/sdk/",
    "quality/local/",
)
#: Fixtures the engine plants, read as data: their spellings are never followed.
_PLANTED = ("quality/canary/", "quality/negative/")
_SPELLED = re.compile(r"quality(\.[A-Za-z_][A-Za-z0-9_]*)+")
_CLOSURE: dict[frozenset[str], list[str]] = {}


def closure_root(path: str) -> bool:
    """Whether `path` is under a declared root or is a top-level `quality/` file."""
    return path.startswith(ENGINE_CLOSURE) or (path.startswith("quality/") and path.count("/") == 1)


def module_path(dotted: str, names: frozenset[str]) -> str:
    """The tracked file a dotted `quality.*` name resolves to, or `""`."""
    stem = dotted.replace(".", "/")
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in names:
            return candidate
    return ""


def spelled(path: Path) -> tuple[list[str], list[str]]:
    """`(imports, spellings)`: the `quality.*` modules a file imports, and those it names to run."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return [], []
    imports: list[str] = []
    named: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            imports += [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SPELLED.fullmatch(node.value):
                named.append(node.value)
    return [m for m in imports if m.startswith("quality.")], named


def engine_closure(names: frozenset[str]) -> list[str]:
    """Every path the engine digest keys: the roots, the top level, and what their code reaches."""
    if names in _CLOSURE:
        return _CLOSURE[names]
    skip = {"quality/rules.yaml", "quality/local/rules.yaml"}
    out = {p for p in names if closure_root(p) and p not in skip}
    todo = [p for p in out if p.endswith(".py") and not p.startswith(_PLANTED)]
    while todo:
        imports, named = spelled(ROOT / todo.pop())
        for dotted in (*imports, *named):
            found = module_path(dotted, names)
            if found and found not in out:
                out.add(found)
                todo.append(found)
    _CLOSURE[names] = sorted(out)
    return _CLOSURE[names]


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
        _ENGINE_DIGEST = _engine_digest_of(blobs)
    return _ENGINE_DIGEST


def _engine_digest_of(blobs: dict[str, str]) -> str:
    """The engine component over these blobs, computed now — `_engine_digest` caches it."""
    under = engine_closure(frozenset(blobs))
    rest = {k: v for k, v in _DOC.items() if k != "rules"}
    # THE DRAWER IS THE SAME SHAPE, for the same reason. Its blob is
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
    digest.update(yaml.safe_dump(rest_local, sort_keys=True, allow_unicode=True).encode("utf-8"))
    return digest.hexdigest()


def memo_components(
    rule: dict, measured: tuple[dict[str, str], str] | None = None
) -> tuple[dict[str, str], str]:
    """The six named halves of this rule's key, or why the key is undecidable.

    Every failure here is could-not-look and returns the sentence: a component
    that quietly derived to nothing would key a verdict for inputs nobody
    measured, which is the one thing a memo must never do. `measured` is a
    measured tree read afresh (`memo_moved`); without it the run's one snapshot
    is used, and so is the run's one engine digest.
    """
    blobs, trouble = measured_blobs() if measured is None else measured
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

    components["engine"] = _engine_digest(blobs) if measured is None else _engine_digest_of(blobs)
    return components, ""


def memo_key(rule: dict) -> tuple[str | None, dict[str, str], str]:
    """(`<MEMO_SCHEMA>:<sha256>`, its components, "") or (None, {}, why it is undecidable)."""
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
            Finding(str(f[0]), int(f[1]), str(f[2]), str(f[3]), int(f[4]) if len(f) > 4 else 1)
            for f in payload["findings"]
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
        "findings": [[f.path, f.line, f.msg, f.klass, f.weight] for f in result.findings],
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


def memo_moved(rule: dict, before: dict[str, str]) -> tuple[list[str], str]:
    """The components that moved while this rule scanned, and why they could not be re-read.

    The measured tree is read AGAIN — never the run's cached snapshot, which is
    the very thing the race lives in — and this rule's components re-derived
    over it. An empty list and an empty sentence is the one answer that lets a
    write through: the tree the scan read is the tree the key names.
    """
    fresh = T.read_tree(ROOT)
    after, why = memo_components(rule, (fresh.blobs, fresh.why))
    if why:
        return [], why
    return [name for name in sorted(before) if after.get(name) != before[name]], ""


#: The drive's seam between a key and its scan (`memo_probe`).
MEMO_PROBE_ENV = "DJB_RULES_MEMO_PROBE_AFTER_KEY"


def memo_probe(rid: str) -> None:
    """Run the drive's probe between a rule's key and its scan; the gate never sets it.

    The one window in which the bytes a key names and the bytes a scan reads can
    disagree is the time between the two, and no drive could reach it from
    outside the process: the key is derived and the scan starts in the same
    call. The executable is handed the rule id and runs at the checkout's root.
    A relative path or a probe that exits non-zero is exit 2 — a seam that did
    not do what the drive asked has moved nothing anybody can name.
    """
    probe = os.environ.get(MEMO_PROBE_ENV, "").strip()
    if not probe:
        return
    memo_counts["probed"] += 1
    if not probe.startswith("/"):
        RUN.broken.append(
            f"{MEMO_PROBE_ENV}={probe!r} is relative — it would resolve against whatever "
            "directory the engine was started from"
        )
        return
    proc = subprocess.run([probe, rid], cwd=str(ROOT), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        RUN.broken.append(
            f"{MEMO_PROBE_ENV}={probe!r} exited {proc.returncode} for rule {rid} — "
            f"{proc.stderr.strip() or 'no stderr'}"
        )


def memo_consult(rule: dict, impl: str) -> CheckResult:
    """An entry is written only when the measured tree is the same before and after the scan.

    The `check:` call, through the memo, and THE ONLY PLACE A SCAN IS SKIPPED: a
    hit replays the banked answer; a miss scans, re-reads the measured tree
    (`memo_moved`) and banks the answer only under a key that still names the
    tree the scan read — otherwise the write is refused, counted and printed.
    The first line above is the contract `--explain <id>` prints for every
    memoisable rule. Everything `run_rule` does after this — the runner, the
    floor proxy, the overrides, the ratchets and the floors — runs on every rule
    on every run, so no memo can hide an unbound floor or a ratchet that grew.
    """
    rid = str(rule["id"])

    def scan() -> CheckResult:
        memo_counts["scanned"] += 1
        ahead = prefetched.pop(rid, None)
        if ahead is None:
            return REGISTRY[impl](ROOT, rule)
        result, raised, printed, more_broken, more_notes = ahead
        sys.stdout.write(printed)
        RUN.broken.extend(more_broken)
        RUN.notes.extend(more_notes)
        if raised is not None:
            raise raised
        return result

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
    assert home is not None  # noqa: S101 — narrows Optional for mypy; a None is a bug, not input
    banked = memo_read(home, rid, key)
    if banked is not None:
        memo_counts["hits"] += 1
        return banked
    memo_counts["misses"] += 1
    memo_lines.append(f"rule {rid}: miss({memo_attribute(home, rid, components)})")
    memo_probe(rid)
    result = scan()
    moved, why_not = memo_moved(rule, components)
    if moved or why_not:
        memo_counts["refused"] += 1
        memo_lines.append(
            f"rule {rid}: memo write refused — the tree moved during the scan ({','.join(moved)})"
            if moved
            else f"rule {rid}: memo write refused — the measured tree could not be re-read "
            f"after the scan ({why_not})"
        )
        return result
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
    probes = engine_number("memo", "probes")
    answered = 0
    memoisable = [
        rule
        for rule in RULES
        if rule.get("enabled", True) and rule.get("check") and memo_declines(rule) is None
    ]
    if not memoisable:
        RUN.broken.append(
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
        RUN.broken.append(
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
        RUN.broken.append(
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
            RUN.broken.append(
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
            RUN.broken.append(
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
        before_broken = len(RUN.broken)
        memo_consistency([bare])
        refused = RUN.broken[before_broken:]
        del RUN.broken[before_broken:]
        if (
            calls["n"] - before == 2
            and memo_counts["hits"] == 0
            and memo_counts["declined"] == 2
            and refused
        ):
            answered += 1
        else:
            RUN.broken.append(
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
            RUN.broken.append(
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
            RUN.broken.append(
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
            RUN.broken.append(
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
    engine_probes("memo", answered)


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
    probes = engine_number("cli", "probes")
    answered = 0
    enabled = [str(r["id"]) for r in RULES if r.get("enabled", True)]
    if not enabled:
        RUN.broken.append("cli census: no enabled rule to explain — the listing would be empty")
        say(f"cli census: --explain/--rules answered {answered} of {probes} probes")
        return
    by_explain = _captured(["--explain"])
    by_rules = _captured(["--rules"])
    if by_explain == by_rules:
        answered += 1
    else:
        RUN.broken.append(
            "cli census: `--explain` with no id and `--rules` printed different things — "
            "they are one printer with two names, and a second implementation is the drift "
            "rule 17 exists against"
        )
    listed = [line for line in by_rules[1].splitlines() if line.strip()]
    if len(listed) == len(RULES):
        answered += 1
    else:
        RUN.broken.append(
            f"cli census: the listing printed {len(listed)} lines for {len(RULES)} rules — a "
            "rule a reader cannot see listed is a rule whose red points at nothing"
        )
    rc, text = _captured(["--explain", enabled[0]])
    if rc == 0 and "valve:" in text and "statement:" in text:
        answered += 1
    else:
        RUN.broken.append(
            f"cli census: `--explain {enabled[0]}` exited {rc} without printing the rule's own "
            "statement and valve — the `next:` line on every red points here"
        )
    rc, text = _captured(["--explain", "zzz-no-such-rule"])
    if rc == 2 and "listing" in text:
        answered += 1
    else:
        RUN.broken.append(
            f"cli census: `--explain` of an unknown id exited {rc} — an unknown id is "
            "could-not-look (exit 2) naming the listing, never a silent nothing"
        )
    # The same reason the trailer census says its count out loud: these four
    # probes are the only thing standing between the `next:` line on every red
    # and a flag somebody deleted. A silent pass is a pass nobody can miss.
    say(f"cli census: --explain/--rules answered {answered} of {probes} probes")
    engine_probes("cli", answered)
    census_reader_census()
    inputs_census()


def inputs_census() -> None:
    """The third reader, driven: `--selftest-inputs` and the ways it must refuse.

    A SECOND SENTENCE rather than four more probes on the one above, and the
    reason is the census grammar itself: `cli census: --explain/--rules answered
    4 of 4 probes` is a claim a drive asserts by its exact words
    (`quality/tests/test_engine_explain.py`), and growing its count would edit
    a file outside `quality/` to say nothing new. Two readers, two counted
    sentences, one prefix — the same shape the seam and residence censuses
    already print.

    Driven through `main`'s own argv dispatch, never through `selftest_inputs()`,
    because the claim under test includes the FLAG: a reader that works and a
    flag nobody wired to it look identical from inside the printer.
    """
    probes = engine_number("inputs", "probes")
    answered = 0

    rc, text = _captured(["--selftest-inputs"])
    lines = [ln for ln in text.splitlines() if ln.strip()]
    relative = all(not ln.startswith("/") and ".." not in ln.split("/") for ln in lines)
    if rc == 0 and lines and lines == sorted(lines) == sorted(set(lines)) and relative:
        answered += 1
    else:
        RUN.broken.append(
            f"cli census: `--selftest-inputs` exited {rc} with {len(lines)} line(s) that are not "
            "a sorted, duplicate-free, checkout-relative list — a key computed over it would "
            "depend on the order the engine happened to walk the tree in"
        )

    rc2, text2 = _captured(["--selftest-inputs"])
    if (rc, text) == (rc2, text2):
        answered += 1
    else:
        RUN.broken.append(
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
    # The walk, re-derived here from SCOPE_KINDS rather than from `kind_files`
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
        "the engine's package": sorted(p for p in tracked_now if p.startswith("quality/engine/")),
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
        RUN.broken.append(
            f"cli census: `--selftest-inputs` did not carry every population it derives: "
            f"{missing or 'one population derived to nothing'} — an input it cannot see is a "
            "byte that changes the verdict without changing the key"
        )

    hard_ok = True
    for value, why_read in HARDCODED_READS:
        found, why = _expand_input(value, tracked_now)
        if why or not set(found) <= listed:
            hard_ok = False
            RUN.broken.append(
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
            RUN.broken.append(
                f"cli census: the scratch rule {probe_id} left `--selftest-inputs` at exit "
                f"{rc3} with {len(printed)} path(s) printed — a population it cannot derive is "
                "could-not-look naming the rule, never a shorter list"
            )

    say(f"cli census: --selftest-inputs answered {answered} of {probes} probes")
    engine_probes("inputs", answered)
    memo_census()


from quality.engine.cli import main  # noqa: E402
from quality.engine.explain import census_reader_census  # noqa: E402
from quality.engine.plants import plant_paths  # noqa: E402
from quality.engine.readers import HARDCODED_READS, _expand_input, _tracked_paths  # noqa: E402
from quality.engine.rules import _scope_paths  # noqa: E402
from quality.engine.world import LOCAL_DOC, RULES, RUN, SCOPE_KINDS, say  # noqa: E402
