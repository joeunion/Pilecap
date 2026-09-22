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
from pathlib import Path

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


def test_this_template_tree_maps_onto_itself_with_nothing_to_do(tmp_path: Path) -> None:
    """The live end: the real reader, on the real tree, is the steady state.

    The fixture pair proves the three drifted shapes; this proves the shipped
    defaults reach them — that `fold_map_lines()` with no arguments but the
    path reads THIS tree's `quality/rules.yaml` and its real fixture trees.
    """
    rc, lines = G.fold_map_lines(G.ROOT / "quality" / "rules.yaml")
    out = "\n".join(lines)
    assert rc == 0, out
    assert "none — every template fixture on this tree is at the path it ships at." in out
    assert "unchanged; nothing to renumber" in out
