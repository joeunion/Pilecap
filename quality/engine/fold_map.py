"""The fourth reader: --fold-map."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from quality.engine._hub import ROOT

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
        namespace = world_module().RULE_ID_NAMESPACE
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


from quality.engine.world import (  # noqa: E402
    ENGINE_FIXTURES,
    GATE5_CITE,
    TEMPLATE_CHECK_PREFIX,
    say,
    world_module,
)
