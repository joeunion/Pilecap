"""The third reader: --selftest-inputs."""

from __future__ import annotations

from quality import tree as T
from quality import worlds as W
from quality.engine._hub import JUDGED_SHAPE_CENSUS, ROOT

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
#   6. THE WALK                       `kind_files` over the measured tree —
#                                     `SCOPE_KINDS`' roots and suffixes, the
#                                     files the live checks actually read
#
# 5 AND 6 WERE MISSING FROM THE FIRST CUT, and the verifier proved it with two
# plants that each moved the engine's verdict while the listing stayed
# byte-identical: a mangled anchor in `docs/product/architecture.md` (exit 2,
# `rule 9: doc … no longer states the rule`) and an `httpx` import in
# `apps/core/workflows.py` (exit 1, `rule 9: apps/core/workflows.py:<line>`). The
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
    ("apps/*/services*", "_measure_budgets_detailed: the service-length budget, file or package"),
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
    # The judged-shape sentence runs the census and re-spells its `base` line.
    (JUDGED_SHAPE_CENSUS, "judged_shape: the census's own `base` line, before the first plant"),
)

_GLOB_META = "*?["


def _tracked_paths() -> tuple[frozenset[str], str]:
    """Every path of the MEASURED tree — a view of `quality.tree.measured_tree` — and why not.

    The tree the ledger banks on and the memo keys on: HEAD plus the working
    tree, a new file that `.gitignore` does not exclude included. The input
    list answers over the same tree the verdict is keyed on, so a byte the
    engine reads is a byte the key moves with.

    READ FRESH, never from the run's cached snapshot: the self-test's censuses
    plant and restore between calls, and a snapshot filled here before the memo
    census plants would hand that census a tree it is no longer standing on.
    """
    read = T.read_tree(ROOT)
    if read.why:
        return frozenset(), f"could not read the measured tree: {read.why}"
    return frozenset(read.blobs), ""


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
        # A FILE, AND THE MEASURED TREE ANSWERS FOR IT TOO. A file `.gitignore`
        # excludes is on the disk and not in the tree the verdict is keyed on,
        # so it is no input: a byte that moved it would move no key.
        if value not in tracked:
            return [], (
                f"names {value!r}, which the measured tree does not carry (ignored by "
                "`.gitignore`) — an input is a byte the verdict's key moves with"
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
    before = len(RUN.broken)
    planted = plant_paths()
    problems.extend(RUN.broken[before:])
    del RUN.broken[before:]
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
    #    from `quality.worlds.kind_files` — the same roots, suffixes and skip dirs
    #    `all_overrides()` walks — intersected with the tracked set, per the
    #    tracked-files rule `_expand_input` already declares.
    #
    #    A root that is not on this checkout contributes nothing and says
    #    nothing, which is `all_overrides()`'s own rule for the same triple. A
    #    root that IS here and contributes no tracked file across ANY of its
    #    kind's suffixes is could-not-look: the walk emptied, and an empty walk
    #    is how every rule of that kind goes quietly green.
    walked_per_root: dict[str, int] = {}
    for root, rels in W.kind_files(ROOT, SCOPE_KINDS, "measured", measured=tracked).items():
        walked_per_root[root] = len(rels)
        paths.update(rels)
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


from quality.engine.plants import plant_paths  # noqa: E402
from quality.engine.rules import _scope_paths  # noqa: E402
from quality.engine.world import PROBE_APP, RULES, RUN, SCOPE_KINDS, say  # noqa: E402
