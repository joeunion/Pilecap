"""`--fold-map`, driven against a fixture pair: the states no template tree is in.

The instrument exists because the first consumer's rule ids had drifted across
two adoptions and item 7 of the 2.1.1 release told them to "rename YOUR OWN
rules" with nothing to decide *which* were their own. Every case here is a
state a template checkout is never in — a template rule carried at another
rule's number, a product rule on a template integer, a template fixture sitting
under a product id — so each one builds its own two-file pair under `tmp_path`
rather than leaning on this tree, which would make the drive a fact about
today's rule set instead of about the reader.

It lives beside `test_audit_rule_seam.py` for the reason that module states: a
clause the canary harness cannot plant is driven directly, against the real
implementation, in the app whose tests already reach the engine. It is NOT a
new `apps/test_*.py` root module — that population carries a floor
(`apps/conftest.py`'s `apps_root_modules`) which a rung joining it must raise
in the same commit, and this drive's subject is one reader rather than the
harness itself.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

#: Reached through `importlib` for the reason `test_audit_rule_seam.py` records:
#: `mypy`'s `files = ["apps", "config"]` means a plain import of `quality.*`
#: from a module under `apps/` drags the whole engine into `--strict` for the
#: first time and surfaces findings in code this drive did not touch.
G = importlib.import_module("quality.gate")

#: The one fixture whose bytes were watched riding into a product's drawer
#: under a DIFFERENT number. Named here so the third case is the real class
#: rather than a lookalike.
VALVE_JS = "// rule-50: a vendored directory's own valve, planted to prove it stays OUT\n"

#: The same bytes a formatter has been through: re-indented, one trailing space,
#: one blank line added. THIRTEEN template fixtures reached the first consumer's
#: drawer this way and the exact-sha census found only the untouched ones.
VALVE_JS_REFORMATTED = (
    "    // rule-50:   a vendored directory's own valve, planted to prove it stays OUT   \n\n"
)

#: Deliberately NOT key-shaped. House rule 23's own scanner is a raw regex over
#: `apps/` with no pragma path, so a fixture body in this file that looked like
#: a credential would be a finding about the drive rather than about the rule.
SECRET_TS = "export const label = 'the fixture the template ships at rule 50';\n"

#: A fixture that exists ONLY inside another entry's `extra_files:`.
PROBE_PY = 'class ZzzCanaryConfig:\n    name = "apps.zzz_canary"\n'


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _rules_yaml(path: Path, rules: list[dict[str, object]]) -> Path:
    return _write(path, yaml.safe_dump({"rules": rules}, sort_keys=False))


def _pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(previous file, template rules.yaml, tree root) — the fixture pair.

    The TEMPLATE side is the tree the product just folded: rule 50 is the
    browser-credential rule, at the number the template gives it. The PREVIOUS
    side is what the product's own `quality/rules.yaml` said before the merge,
    with that same rule carried at 58 and two rules of the product's own.
    """
    tree = tmp_path / "tree"
    template = _rules_yaml(
        tree / "quality" / "rules.yaml",
        [
            {
                "id": "50",
                "name": "no-credential-written-down-in-the-browser-tree",
                # `extra_files:` IS PART OF THE PLAN. Reading only each entry's
                # own `fixture:` left 52 of the real tree's 469 fixture files
                # outside the inventory, house rule 60's own plan among them —
                # and a file the inventory cannot see is a file the census
                # cannot give back.
                "canaries": [
                    {
                        "fixture": "secret_literal.ts",
                        "extra_files": [{"fixture": "probe_app_config.py"}],
                    }
                ],
                "negatives": [{"fixture": "vendored_valve.js"}],
            },
            {"id": "54", "name": "the-vocabulary-is-one-shape", "django_check_ids": ["djb.W054"]},
        ],
    )
    _write(tree / "quality" / "negative" / "50" / "vendored_valve.js", VALVE_JS)
    _write(tree / "quality" / "canary" / "50" / "secret_literal.ts", SECRET_TS)
    _write(tree / "quality" / "canary" / "50" / "probe_app_config.py", PROBE_PY)
    previous = _rules_yaml(
        tmp_path / "previous-rules.yaml",
        [
            # (1) A TEMPLATE RULE AT A DRIFTED NUMBER — the same name, four
            #     numbers along, with a check id registered at the old number.
            {
                "id": "58",
                "name": "no-credential-written-down-in-the-browser-tree",
                "django_check_ids": ["djb.W058"],
            },
            # (2) A PRODUCT RULE — a name the template has never heard of,
            #     sitting on an integer the template will mint one day.
            {"id": "55", "name": "deal-stage-guard", "django_check_ids": ["djb.E055"]},
            # (3) A template rule that did not move. One line, no block.
            {"id": "54", "name": "the-vocabulary-is-one-shape"},
        ],
    )
    return previous, template, tree


def _run(tmp_path: Path, namespace: str | None = "acme") -> tuple[int, str]:
    previous, template, tree = _pair(tmp_path)
    rc, lines = G.fold_map_lines(
        previous,
        template_path=template,
        namespace=namespace,
        tree=tree,
        template_root=tree,
    )
    return rc, "\n".join(lines)


def test_a_template_rule_at_a_drifted_number_maps_back_to_the_template_number(
    tmp_path: Path,
) -> None:
    """The name matches the template's; the number does not. Every place, named."""
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "TEMPLATE  58 → 50  no-credential-written-down-in-the-browser-tree" in out
    # the id, the two fixture directories, the valve, the check tag, and the
    # FIFTH place — the registration in apps/core/checks.py.
    # F3: NOT a `git mv`. After the fold `quality/canary/58/` also holds the
    # template's own rule 58 plan and `quality/canary/50/` already exists, so a
    # move nests or carries the wrong files — the exact class the FIXTURES
    # census warns about, printed as its own remedy.
    assert "git mv quality/canary/58" not in out and "git mv quality/negative/58" not in out
    assert (
        "DELETE your copies under quality/canary/58/ — do NOT git mv it: after the fold that "
        "directory also holds the template's own rule 58 plan and quality/canary/50/ already "
        "exists, so a move nests or carries the wrong files. the template ships this rule's "
        "at quality/canary/50/: probe_app_config.py, secret_literal.ts" in out
    )
    assert "the template ships this rule's at quality/negative/50/: vendored_valve.js" in out
    assert "and the same under quality/local/canary/acme-58/ if they went into the drawer" in out
    assert "`# rule-58:` → `# rule-50:`" in out
    assert "djb.W058 → djb.W050" in out
    assert "apps/core/checks.py registers djb.W058 → djb.W050" in out
    # A rule whose number did not drift is ONE line and carries no places.
    assert "TEMPLATE  54  the-vocabulary-is-one-shape — unchanged" in out


def test_a_product_rule_maps_into_the_drawer_under_the_namespace(tmp_path: Path) -> None:
    """A name the template does not carry is the product's, at `<ns>-<old n>`."""
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "PRODUCT   55 → acme-55  deal-stage-guard" in out
    assert 'quality/local/rules.yaml — `id: "acme-55"`' in out
    # The PRODUCT direction keeps the move: `quality/local/canary/acme-55/`
    # cannot already exist (the namespace is the product's alone), so there is
    # nothing for it to collide with.
    assert "git mv quality/canary/55 quality/local/canary/acme-55" in out
    assert "git mv quality/negative/55 quality/local/negative/acme-55" in out
    assert "`# rule-55:` → `# rule-acme-55:`" in out
    # The check tag keeps the LETTER and the WIDTH it was declared with and
    # changes only the namespace: an `E` re-spelled as a `W` is a registration
    # no checks.py carries, which is the exit 2 this line exists to prevent.
    assert "djb.E055 → acme.E055" in out


def test_a_template_fixture_under_a_product_id_is_found_by_its_bytes(tmp_path: Path) -> None:
    """The class: the file moved between DIFFERENT numbers, so only bytes see it."""
    previous, template, tree = _pair(tmp_path)
    _write(tree / "quality" / "local" / "negative" / "acme-58" / "vendored_valve.js", VALVE_JS)
    rc, lines = G.fold_map_lines(
        previous, template_path=template, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 0, out
    assert (
        "quality/local/negative/acme-58/vendored_valve.js — this is the template's; "
        "put it back at quality/negative/50/vendored_valve.js" in out
    )


def test_a_reformatted_template_fixture_is_found_by_its_shape_not_its_bytes(
    tmp_path: Path,
) -> None:
    """F1(a). A formatter between two folds is the commonest single edit there is.

    The copy carries a DIFFERENT BASENAME on purpose, so the only key that can
    reach it is the whitespace-normalised hash — a name match would prove
    nothing about (a).
    """
    previous, template, tree = _pair(tmp_path)
    _write(tree / "quality" / "local" / "negative" / "acme-58" / "valve.js", VALVE_JS_REFORMATTED)
    rc, lines = G.fold_map_lines(
        previous, template_path=template, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 0, out
    assert (
        "quality/local/negative/acme-58/valve.js — this is the template's; put it back at "
        "quality/negative/50/vendored_valve.js" in out
    )


def test_a_renamed_content_copy_is_found_by_its_basename_and_only_read_it(
    tmp_path: Path,
) -> None:
    """F1(b). A name survives any edit — so it is a READ IT, never a verdict."""
    previous, template, tree = _pair(tmp_path)
    _write(
        tree / "quality" / "local" / "canary" / "acme-59" / "vendored_valve.js",
        "// nothing the template ever shipped; entirely the product's own plant\n",
    )
    rc, lines = G.fold_map_lines(
        previous, template_path=template, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 0, out
    assert (
        "quality/local/canary/acme-59/vendored_valve.js — NAME MATCH — read it: "
        "quality/negative/50/vendored_valve.js" in out
    )
    # And it is NOT claimed as the template's: the weaker key gets the weaker
    # sentence, or the two findings mean the same thing and neither is useful.
    assert "acme-59/vendored_valve.js — this is the template's" not in out


def test_a_fixture_named_only_inside_extra_files_is_in_the_inventory(tmp_path: Path) -> None:
    """F2. `extra_files:` is part of the plan, and 52 of 469 files live only there."""
    previous, template, tree = _pair(tmp_path)
    _write(tree / "quality" / "local" / "canary" / "acme-58" / "probe_app_config.py", PROBE_PY)
    rc, lines = G.fold_map_lines(
        previous, template_path=template, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 0, out
    assert (
        "quality/local/canary/acme-58/probe_app_config.py — this is the template's; put it "
        "back at quality/canary/50/probe_app_config.py" in out
    )


def test_a_fixture_at_the_path_the_template_ships_it_at_is_silent(tmp_path: Path) -> None:
    """The control. Without it the case above could be firing on every file."""
    rc, out = _run(tmp_path)
    assert rc == 0, out
    assert "none — every template fixture on this tree is at the path it ships at." in out


def test_a_rule_with_no_name_is_exit_2_naming_the_rule(tmp_path: Path) -> None:
    """The matching key is the name. A rule without one cannot be placed at all."""
    _, template, tree = _pair(tmp_path)
    previous = _rules_yaml(
        tmp_path / "nameless.yaml",
        [{"id": "58", "name": "no-credential-written-down-in-the-browser-tree"}, {"id": "55"}],
    )
    rc, lines = G.fold_map_lines(
        previous, template_path=template, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 2, out
    assert "rule 55 declares no `name:`" in out
    # NOTHING ELSE IS PRINTED. A half-map is a rename list somebody would paste.
    assert "TEMPLATE" not in out and "PRODUCT" not in out


def test_an_unreadable_previous_file_is_exit_2_and_prints_no_map(tmp_path: Path) -> None:
    """Could-not-look, never an empty map over a file nobody could open."""
    _, template, tree = _pair(tmp_path)
    rc, lines = G.fold_map_lines(
        tmp_path / "no-such-file.yaml",
        template_path=template,
        namespace="acme",
        tree=tree,
        template_root=tree,
    )
    out = "\n".join(lines)
    assert rc == 2, out
    assert "COULD NOT LOOK" in out and "no-such-file.yaml" in out


def test_with_no_namespace_declared_a_product_rule_is_unmatched_and_gets_no_arrow(
    tmp_path: Path,
) -> None:
    """Never a guess: with no `rule_id_namespace:` there is no `<ns>-<n>` to write."""
    rc, out = _run(tmp_path, namespace=None)
    assert rc == 0, out
    assert "UNMATCHED — this reader will not guess:" in out
    assert "55  deal-stage-guard" in out
    assert "PRODUCT" not in out


# --- HOTFIX-FOLDMAP-3: THE SELF-MAP IS TEMPLATE-ONLY ---------------------------
#
# The case below asserts the map of THIS TREE onto ITSELF has nothing to do,
# and that is a property of the TEMPLATE's own tree and of no other. A product
# that has folded declares `rule_id_namespace:` in `quality/local/rules.yaml`,
# carries drawer rules under it and a drawer fixture tree beside them — and
# `_fold_map_fixture_findings()` walks `quality/local/canary` and
# `quality/local/negative` on exactly the same three keys it walks the
# template's trees on, so a FIXTURES section with content is what a folded tree
# produces by construction. The first consumer measured it red on their fold of
# v2.1.3, and it is red on every consumer forever: a suite the template ships
# must not carry a case a product cannot make green.
#
# The condition is the ENGINE's own reading and not a second one. There is no
# sibling template-only mark in this tree to join — the only skip mechanism
# under `apps/` is `apps/core/tests/template_shape.py`, and it is keyed to the
# closed `DJB_IDENTITY_SHAPE` key set (it raises `ValueError` on a key outside
# it, on purpose), so widening it to carry "has this tree folded?" would break the
# closed population that makes its skips countable. One template-only case
# exists today, so the helper lives here beside it rather than in
# `apps/conftest.py`; the second one that arrives is what moves it.


def _declared_namespace(doc: Mapping[str, object] | None = None) -> str | None:
    """The `rule_id_namespace:` this tree declares, or `None` on a template.

    Read off the ENGINE's own drawer parse — `quality.gate._read_local()`,
    whose result is the module global `LOCAL_DOC` — rather than by opening
    `quality/local/rules.yaml` here. A second reader of that file is a second
    opinion about whether this tree has folded, and every refusal ADR gate-5
    exists for is keyed on the engine's.

    The RAW declaration and not `RULE_ID_NAMESPACE`: that global is `None`
    whenever the declaration is malformed (`_read_namespace()` reports the
    problem and yields nothing), and a product with a typo in its namespace is
    still a product. The question here is whether the tree has folded, never
    whether its declaration parses.

    `doc` exists for the drive below and is the same device
    `template_shape(shape=...)` uses for the same reason: a mark passes
    nothing and gets the ambient declaration, while the test OF the mechanism
    hands it a drawer it built, because reading the ambient one there would
    make the template's own test of the mechanism red on the first product
    that declares anything.
    """
    declared = (G.LOCAL_DOC if doc is None else doc).get("rule_id_namespace")
    return str(declared or "").strip() or None


def _skip_unless_template_tree(doc: Mapping[str, object] | None = None) -> None:
    """Skip with ONE reason string naming the condition that turned the case off."""
    namespace = _declared_namespace(doc)
    if namespace is not None:
        pytest.skip(
            f"template-only: this tree declares rule_id_namespace {namespace}; "
            "the self-map has content by construction on a product"
        )


def test_this_template_tree_maps_onto_itself_with_nothing_to_do(tmp_path: Path) -> None:
    """The live end: the real reader, on the real tree, is the steady state.

    The fixture pair proves the three drifted shapes; this proves the shipped
    defaults reach them — that `fold_map_lines()` with no arguments but the
    path reads THIS tree's `quality/rules.yaml` and its real fixture trees.

    TEMPLATE-ONLY — see the block above. On a folded tree the assertion below
    is red by construction, so the case skips naming the declaration that made
    it so rather than handing a product a red it cannot clear.
    """
    _skip_unless_template_tree()
    rc, lines = G.fold_map_lines(G.ROOT / "quality" / "rules.yaml")
    out = "\n".join(lines)
    assert rc == 0, out
    assert "none — every template fixture on this tree is at the path it ships at." in out
    assert "unchanged; nothing to renumber" in out


def _swap(module: ModuleType, name: str, value: Any) -> Any:
    """Set a module global and hand back what was there. (`setattr`, not `.attr=`.)

    The idiom `apps/core/tests/test_drawer_seam.py` records: `G` is a
    `ModuleType` to mypy `--strict`, so a bare `G.LOCAL_RULES_PATH = ...` is an
    error there — the same reason the module is reached through `importlib` at
    all. The one caller below restores in a `finally`: this is a process
    global, and a case that left it moved would hand the next case a drawer
    nobody wrote.
    """
    was = getattr(module, name)
    setattr(module, name, value)
    return was


def _read_drawer(path: Path) -> dict[str, object]:
    """`quality.gate._read_local()` run over a drawer THIS test wrote.

    The engine's reader and not a `yaml.safe_load()` here: the subject is
    whether the declaration a consumer types is the declaration the mark sees,
    and a second parser would only prove the second parser agrees with itself.
    An absent path is legal and is the TEMPLATE's own state — `_read_local()`
    answers `{}` for it, which is what `LOCAL_DOC` holds on this tree.
    """
    was = _swap(G, "LOCAL_RULES_PATH", path)
    try:
        doc, _rules, problems = G._read_local()
    finally:
        _swap(G, "LOCAL_RULES_PATH", was)
    assert problems == [], problems
    assert isinstance(doc, dict), doc
    out: dict[str, object] = doc
    return out


def test_the_self_map_is_template_only_and_the_skip_names_the_declaration(
    tmp_path: Path,
) -> None:
    """The mark's own drive: it fires on a product's drawer and not on this tree.

    The product side is a REAL drawer read by the engine's real reader — the
    file written under `tmp_path` and `_read_local()` run over it — rather than
    a hand-built mapping, so what is proved is that the declaration a consumer
    types is the declaration the skip sees.
    """
    drawer = tmp_path / "quality" / "local" / "rules.yaml"
    drawer.parent.mkdir(parents=True, exist_ok=True)
    drawer.write_text("rule_id_namespace: acme\ntemplate_rule_ids_through: 60\n")
    product = _read_drawer(drawer)
    assert _declared_namespace(product) == "acme", product

    with pytest.raises(pytest.skip.Exception) as raised:
        _skip_unless_template_tree(product)
    assert str(raised.value) == (
        "template-only: this tree declares rule_id_namespace acme; "
        "the self-map has content by construction on a product"
    ), str(raised.value)

    # THE CONTROL, and it is the TEMPLATE's own drawer state — no file at all —
    # read by the same reader. Without it the mark could be firing on every
    # tree, and a case that skips everywhere reads in a run exactly like a case
    # that passed.
    #
    # It is built rather than read off THIS tree on purpose: an assertion that
    # the ambient tree declares no namespace is itself red by construction on a
    # product, which is the very defect the skip above closes — the mechanism's
    # own drive must not re-enter the divergence class it polices. That this
    # tree really is a template is what the self-map case above proves by
    # RUNNING in the template's suite.
    template = _read_drawer(tmp_path / "quality" / "local" / "absent.yaml")
    assert template == {}, template
    assert _declared_namespace(template) is None, template
    _skip_unless_template_tree(template)


# --- HOTFIX-RULEMAP-2: WHICH FILE IS THE TEMPLATE SIDE -------------------------
#
# The first consumer measured the defect in the wrong direction. CHANGELOG
# § [2.1.2] item 2 sent them here AFTER `git merge`, and on that tree
# `quality/rules.yaml` is the MERGE RESULT — their names at their numbers — so
# the map they got renamed four TEMPLATE rules into their namespace and left
# four PRODUCT rules on template integers, at exit 0, with UNMATCHED empty and
# nothing in the output to say which file it had read.
#
# The pair below is that shape, synthesized: twelve rules the product carried,
# six of them the template's at drifted numbers and six their own on template
# integers. Against the RELEASE's file it is twelve renames; against a merged
# tree it is a map with nothing to do.

#: name -> (the id the product carried, the id the RELEASE gives it)
CONSUMER_DRIFT = {
    "surfaces-resolve-inside-this-tree": ("58", "50"),
    "every-door-answers-the-same": ("59", "51"),
    "a-ledger-never-un-happens": ("60", "52"),
    "the-vocabulary-is-one-shape-2": ("61", "53"),
    "no-credential-in-the-browser-tree-2": ("57", "49"),
    "a-schedule-is-a-declaration": ("56", "48"),
}
#: name -> the template integer the product's own rule was sitting on
CONSUMER_OWN = {
    "deal-stage-guard-2": "50",
    "quote-expiry-guard": "51",
    "carrier-code-shape": "52",
    "policy-number-shape": "53",
    "renewal-window-guard": "54",
    "premium-rounds-to-cents": "55",
}


def _previous_rules() -> list[dict[str, object]]:
    out: list[dict[str, object]] = [
        {"id": old, "name": name} for name, (old, _new) in CONSUMER_DRIFT.items()
    ]
    out += [{"id": rid, "name": name} for name, rid in CONSUMER_OWN.items()]
    return out


def _release_rules() -> list[dict[str, object]]:
    return [{"id": new, "name": name} for name, (_old, new) in CONSUMER_DRIFT.items()]


def _consumer_pair(tmp_path: Path, *, merged: list[dict[str, object]]) -> tuple[Path, Path, Path]:
    """(previous, the RELEASE's rules.yaml, a tree whose rules.yaml is `merged`)."""
    tree = tmp_path / "consumer"
    # F3: a real product tree carries one, and the remedy READS it — labelled,
    # never pasted into the command. Without it here the labelled line could
    # not be asserted at all.
    _write(tree / "TEMPLATE_VERSION", "2.1.2\n")
    previous = _rules_yaml(tmp_path / "before.yaml", _previous_rules())
    release = _rules_yaml(tmp_path / "template-rules.yaml", _release_rules())
    _rules_yaml(tree / "quality" / "rules.yaml", merged)
    return previous, release, tree


def _headers(out: str) -> list[str]:
    return [
        line
        for line in out.splitlines()
        if (line.startswith("TEMPLATE  ") or line.startswith("PRODUCT   ")) and " → " in line
    ]


def test_the_merged_tree_taken_implicitly_is_exit_2_naming_the_pair(tmp_path: Path) -> None:
    """The subject. The template side is not an argument, so it is not a guess."""
    previous, _release, tree = _consumer_pair(
        tmp_path,
        # the merge result: the template's entries arrived at the template's
        # numbers, the product's own stayed on the integers they had.
        merged=_release_rules() + [{"id": rid, "name": n} for n, rid in CONSUMER_OWN.items()],
    )
    rc, lines = G.fold_map_lines(previous, namespace="acme", tree=tree)
    out = "\n".join(lines)
    assert rc == 2, out
    assert "COULD NOT LOOK" in out
    assert "The template side was TAKEN from this tree" in out
    assert str(tree / "quality" / "rules.yaml") in out
    assert (
        "`surfaces-resolve-inside-this-tree` is `58` in the previous file and `50` in this "
        "tree's quality/rules.yaml" in out
    )
    assert (
        "git show v<the release you are folding>:quality/rules.yaml > /tmp/template-rules.yaml"
        in out
    )
    assert "--fold-map <previous rules.yaml> /tmp/template-rules.yaml" in out
    # NOTHING ELSE IS PRINTED — a half-map of this shape is the clean-looking
    # map the whole hotfix is about.
    assert "TEMPLATE  " not in out and "PRODUCT   " not in out
    # F2: the sentence does not claim to know WHICH tree this is.
    assert (
        "not the same rule set: this is your merged tree, or a release checkout that is not "
        "your pre-merge tree" in out
    )
    # F3: TEMPLATE_VERSION is READ AND LABELLED, and NEVER pasted into the
    # command — the census hotfix's lesson: the checkout's version answers a
    # different question on either side of the merge.
    assert "THIS CHECKOUT's TEMPLATE_VERSION reads 2.1.2" in out
    assert re.search(r"git show v\d", out) is None, out


def test_a_merged_tree_that_agrees_about_every_number_is_still_exit_2(tmp_path: Path) -> None:
    """The half the brief's own predicate does not reach — and the consumer's real shape.

    Their measured run had NO shared name at a different id: every match was
    `unchanged` and the rest were absent from the merged file altogether. A
    tooth written as "the same name at a different number" would have printed
    exactly the clean map they got. The predicate is therefore the whole
    comparison — a name in one file and not the other counts — which is why
    this tree, where every shared name agrees, still refuses.
    """
    previous, _release, tree = _consumer_pair(
        tmp_path,
        merged=_previous_rules() + [{"id": "62", "name": "a-rule-the-release-minted"}],
    )
    rc, lines = G.fold_map_lines(previous, namespace="acme", tree=tree)
    out = "\n".join(lines)
    assert rc == 2, out
    assert (
        "`a-rule-the-release-minted` is in this tree's quality/rules.yaml and NOT in the "
        "previous file" in out
    )
    assert "1 rule name(s) differ in all" in out


def test_a_pre_merge_tree_whose_rules_yaml_is_the_previous_file_is_silent(
    tmp_path: Path,
) -> None:
    """The control: the tooth must not refuse the one honest use of the short form."""
    previous, _release, tree = _consumer_pair(tmp_path, merged=_previous_rules())
    rc, lines = G.fold_map_lines(previous, namespace="acme", tree=tree)
    out = "\n".join(lines)
    assert rc == 0, out
    assert "COULD NOT LOOK" not in out
    assert _headers(out) == []


def test_the_explicit_template_side_maps_the_consumer_pair_at_twelve_renames(
    tmp_path: Path,
) -> None:
    """(b) on their worktree: the RELEASE's own file, handed in, is the right map."""
    previous, release, tree = _consumer_pair(
        tmp_path,
        merged=_release_rules() + [{"id": rid, "name": n} for n, rid in CONSUMER_OWN.items()],
    )
    rc, lines = G.fold_map_lines(
        previous, template_path=release, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 0, out
    headers = _headers(out)
    assert len(headers) == 12, headers
    assert sum(1 for h in headers if h.startswith("TEMPLATE")) == 6, headers
    assert sum(1 for h in headers if h.startswith("PRODUCT")) == 6, headers
    assert "TEMPLATE  58 → 50  surfaces-resolve-inside-this-tree" in out
    assert "PRODUCT   50 → acme-50  deal-stage-guard-2" in out
    # and no rule is left believing it did not move
    assert "unchanged; nothing to renumber" not in out


def test_the_header_names_the_template_side_path_and_whether_it_was_given(
    tmp_path: Path,
) -> None:
    """Criterion 1. `the template's` alone is what let two runs look identical."""
    previous, release, tree = _consumer_pair(tmp_path, merged=_previous_rules())
    _, given = G.fold_map_lines(
        previous, template_path=release, namespace="acme", tree=tree, template_root=tree
    )
    assert f"template side {release} (GIVEN)" in given[0]
    _, taken = G.fold_map_lines(previous, namespace="acme", tree=tree)
    assert (
        f"template side {tree / 'quality' / 'rules.yaml'} (TAKEN from this tree — no second "
        "argument)" in taken[0]
    )


def test_a_drawer_rule_the_template_side_still_carries_is_exit_2(tmp_path: Path) -> None:
    """Tooth B. Not tooth A's predicate — its input is the drawer, not the previous file.

    It fires where A is silent: a tree whose rules.yaml agrees with the
    previous file rule for rule, and whose drawer has already namespaced a rule
    the template turns out to own.
    """
    previous, _release, tree = _consumer_pair(tmp_path, merged=_previous_rules())
    _write(
        tree / "quality" / "local" / "rules.yaml",
        yaml.safe_dump(
            {
                "rule_id_namespace": "acme",
                "template_rule_ids_through": 61,
                "rules": [{"id": "acme-58", "name": "surfaces-resolve-inside-this-tree"}],
            },
            sort_keys=False,
        ),
    )
    rc, lines = G.fold_map_lines(previous, namespace="acme", tree=tree)
    out = "\n".join(lines)
    assert rc == 2, out
    assert (
        "`surfaces-resolve-inside-this-tree` is in your drawer as `acme-58` AND in this tree's "
        "quality/rules.yaml at the template integer `58`" in out
    )


def test_the_same_drawer_pair_is_a_finding_when_the_release_file_is_given(
    tmp_path: Path,
) -> None:
    """With the release's own file certain, the drawer is the side that is wrong."""
    previous, release, tree = _consumer_pair(tmp_path, merged=_previous_rules())
    _write(
        tree / "quality" / "local" / "rules.yaml",
        yaml.safe_dump(
            {
                "rule_id_namespace": "acme",
                "template_rule_ids_through": 61,
                "rules": [{"id": "acme-58", "name": "surfaces-resolve-inside-this-tree"}],
            },
            sort_keys=False,
        ),
    )
    rc, lines = G.fold_map_lines(
        previous, template_path=release, namespace="acme", tree=tree, template_root=tree
    )
    out = "\n".join(lines)
    assert rc == 0, out
    assert "DRAWER — namespaced in quality/local/rules.yaml, and still the TEMPLATE's:" in out
    assert "acme-58 → 50  surfaces-resolve-inside-this-tree" in out


def test_fixtures_declares_itself_a_lower_bound_unless_a_template_tree_is_given(
    tmp_path: Path,
) -> None:
    """Criterion 3. A silent lower bound is the failure; a declared one is a fact.

    The fixture BYTES can only be read off a tree, so a `--fold-map` carrying
    only a rules.yaml reads them from THIS tree — which after a merge holds the
    merge result too. The section says so in its own header, and stops saying
    so exactly when a `--template-tree` has made it complete.
    """
    previous, release, tree = _consumer_pair(tmp_path, merged=_previous_rules())
    _, taken = G.fold_map_lines(previous, template_path=release, namespace="acme", tree=tree)
    assert "A LOWER BOUND — the fixture BYTES were read from THIS TREE" in "\n".join(taken)
    assert "--template-tree" in "\n".join(taken)
    release_tree = tmp_path / "release-checkout"
    _rules_yaml(release_tree / "quality" / "rules.yaml", _release_rules())
    _, complete = G.fold_map_lines(
        previous,
        template_path=release_tree / "quality" / "rules.yaml",
        namespace="acme",
        tree=tree,
        template_root=release_tree,
    )
    assert "A LOWER BOUND" not in "\n".join(complete)
