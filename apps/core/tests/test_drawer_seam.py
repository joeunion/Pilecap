"""The three places the drawer's seam refused a product for being a product.

MEASURED, NOT IMAGINED. Every case below is one refusal the first consumer of
v2.1.2 met while moving its own rules into `quality/local/` — pasted into the
rung brief verbatim, reproduced here against the engine's own functions, and
each one red on the engine as it shipped:

* **R1 · a product rule could not be about a product's own files.** The
  template declares exactly two scope kinds, `py` (apps, config) and `js`
  (frontend), and `kind_roots` read only those — so a rule whose subject is a
  ledger, a doc, a `.env.example` or a canary under `quality/local/` had no
  kind to name and `check_v1._refuse_outside_roots` refused its runner's every
  finding: *path 'docs/product/queue.md' is outside the roots this rule
  declares (apps, config)*.
* **R3 · a template rule's own finding class had no product-owned home.**
  Rules 50-53 ratchet per FINDING CLASS (`literal`, `api-reach`, `barrel`,
  `consumed-undeclared`), and the drawer's `ratchets:` accepted only
  app-keyed classes on a template rule — *the drawer adds class 'literal',
  whose app 'literal' is not a directory under apps/*.
* **R4 · a directory the ENGINE plants into could not be claimed.**
  `ENGINE_FIXTURES` claims a FILE and `fixture_dir_findings` built `claimed`
  from rule ids alone, so an engine-planted directory whose name is no rule's
  id was exit 2 whatever anybody declared.

WHAT THIS FILE DOES NOT TOUCH: the tree. Every case drives the engine's own
functions over injected declarations and `tmp_path`, because a test that wrote
a real `quality/local/rules.yaml` would move the working tree a concurrent
gate's verdict is keyed on.
"""

# names, never reads: docs/product/queue.md — a path outside the roots, handed to the engine over tmp_path  # noqa: E501

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

#: Reached through `importlib` for the reason `test_drawer_fixture_home.py`
#: states: a plain `from quality import gate` in a module under `apps/` drags
#: the whole `quality/` tree into mypy's `--strict` graph for the first time.
_GATE = importlib.import_module("quality.gate")


def _swap(module: ModuleType, name: str, value: Any) -> Any:
    """Set a module global and hand back what was there. (`setattr`, not `.attr=`.)

    Through `setattr` rather than attribute assignment because `_GATE` is a
    `ModuleType` to mypy `--strict` and a bare `_GATE.LOCAL_DOC = ...` is an
    error there — the same reason the module is reached through `importlib` at
    all. Every caller below restores in a `finally`: these are process globals
    and a case that left one moved would be handing the next case a drawer
    nobody wrote.
    """
    was = getattr(module, name)
    setattr(module, name, value)
    return was


_CHECK_V1 = importlib.import_module("quality.check_v1")
_WORLDS = importlib.import_module("quality.worlds")


# --- R1 · the drawer's fifth key -------------------------------------------------


def test_scope_kinds_is_a_drawer_key() -> None:
    """`scope_kinds:` is one of the drawer's keys, so a product may declare one."""
    assert "scope_kinds" in _GATE.LOCAL_KEYS, sorted(_GATE.LOCAL_KEYS)


def test_a_product_kind_may_name_any_directory_or_file_of_this_tree() -> None:
    """docs/, the drawer itself and a FILE are legal roots; nothing invented is."""
    ok = _GATE._local_scope_kind_problems(
        {
            "ledgers": {"roots": ["docs", "quality", ".env.example"], "suffixes": [".md"]},
        }
    )
    assert ok == [], ok
    absent = _GATE._local_scope_kind_problems(
        {"ledgers": {"roots": ["docs/there-is-no-such-directory"], "suffixes": [".md"]}}
    )
    assert len(absent) == 1 and "neither a directory nor a file" in absent[0], absent
    escaping = _GATE._local_scope_kind_problems(
        {"ledgers": {"roots": ["../elsewhere"], "suffixes": [".md"]}}
    )
    assert len(escaping) == 1 and "RELATIVE" in escaping[0], escaping


def test_a_product_kind_may_not_reuse_a_template_kinds_name() -> None:
    """The refusal names BOTH files — neither may silently win the name."""
    clash = _GATE._local_scope_kind_problems({"py": {"roots": ["docs"], "suffixes": [".md"]}})
    assert len(clash) == 1, clash
    assert "quality/local/rules.yaml" in clash[0] and "quality/rules.yaml" in clash[0], clash[0]


def test_the_scope_kinds_the_engine_reads_are_the_union() -> None:
    """A drawer kind joins `SCOPE_KINDS`, so `kind_roots` reads the product's roots."""
    saved = _swap(
        _GATE,
        "LOCAL_DOC",
        {
            "scope_kinds": {
                "ledgers": {"roots": ["docs"], "suffixes": [".md"], "comment": "<!--"},
                # A clash is dropped from the union, never merged: it is refused
                # at the loader, and half a declaration reads as a smaller
                # engine rather than as a broken one.
                "py": {"roots": ["docs"], "suffixes": [".md"], "comment": "#"},
            }
        },
    )
    try:
        kinds = _GATE._scope_kinds()
    finally:
        _swap(_GATE, "LOCAL_DOC", saved)
    # The template's four (`compose` and `workflows` are rules 61's and 62's
    # subjects) plus the drawer's one; the clashing `py` is not a fifth.
    assert set(kinds) == {"py", "js", "compose", "workflows", "ledgers"}, sorted(kinds)
    assert _WORLDS.kind_roots({"kind": "ledgers"}, kinds) == ["docs"]
    assert _WORLDS.kind_roots({"kind": "py"}, kinds) == ["apps", "config"]


def test_the_outside_roots_refusal_names_the_drawer_key_for_a_local_rule() -> None:
    """The refusal was right and mute; the remedy rides only on a DRAWER rule."""
    saved = _swap(_GATE, "LOCAL_RULE_IDS", frozenset({"acme-1"}))
    try:
        remedy = _GATE.drawer_roots_remedy("acme-1")
        assert _GATE.drawer_roots_remedy("1") == ""
    finally:
        _swap(_GATE, "LOCAL_RULE_IDS", saved)
    assert "scope_kinds:" in remedy and "quality/local/rules.yaml" in remedy, remedy
    try:
        _CHECK_V1._refuse_outside_roots(
            "docs/product/queue.md",
            index=0,
            roots=["apps", "config"],
            where="rule acme-1",
        )
    except _CHECK_V1.RunnerRefused as refused:
        assert refused.klass == "finding-outside-roots"
        assert "a runner may only report about what it was pointed at" in refused.detail
    else:  # pragma: no cover - the refusal is the point
        raise AssertionError("a finding outside the roots was not refused")
    try:
        _CHECK_V1._refuse_outside_roots(
            "docs/product/queue.md",
            index=0,
            roots=["apps", "config"],
            where="rule acme-1",
            remedy=remedy,
        )
    except _CHECK_V1.RunnerRefused as refused:
        assert remedy in refused.detail, refused.detail
    else:  # pragma: no cover - the refusal is the point
        raise AssertionError("a finding outside the roots was not refused")


# --- R3 · a template rule's own finding class ------------------------------------


def _merge(
    ratchets: dict[str, Any],
    rules: list[dict[str, Any]],
    local_ids: frozenset[str] = frozenset(),
) -> Any:
    """`_merge_local_ratchets` over injected rules. (problems, rules, drawer classes)."""
    by_id = {str(rule["id"]): rule for rule in rules}
    was_doc = _swap(_GATE, "LOCAL_DOC", {"ratchets": ratchets})
    was_rules = _swap(_GATE, "RULES_BY_ID", by_id)
    was_local = _swap(_GATE, "LOCAL_RULE_IDS", local_ids)
    was_classes = set(_GATE.DRAWER_RATCHET_CLASSES)
    try:
        _GATE.DRAWER_RATCHET_CLASSES.clear()
        problems = _GATE._merge_local_ratchets()
        return problems, by_id, set(_GATE.DRAWER_RATCHET_CLASSES)
    finally:
        _swap(_GATE, "LOCAL_DOC", was_doc)
        _swap(_GATE, "RULES_BY_ID", was_rules)
        _swap(_GATE, "LOCAL_RULE_IDS", was_local)
        _GATE.DRAWER_RATCHET_CLASSES.clear()
        _GATE.DRAWER_RATCHET_CLASSES.update(was_classes)


def test_a_drawer_ratchet_may_name_a_finding_class_the_template_rule_declares() -> None:
    """`literal` is rule 50's class, not an app — and the count lives in the drawer."""
    problems, by_id, drawer = _merge(
        {"50": {"literal": 12}}, [{"id": "50", "ratchets": {"literal": 0}}]
    )
    assert problems == [], problems
    assert by_id["50"]["ratchets"] == {"literal": 12}
    assert ("50", "literal") in drawer
    # And the home a note sends a reader to follows the pair, so the product is
    # told to edit its OWN file and not the one a fold overwrites.
    _GATE.DRAWER_RATCHET_CLASSES.add(("50", "literal"))
    try:
        assert _GATE.ratchet_home("50", "literal") == "quality/local/rules.yaml"
    finally:
        _GATE.DRAWER_RATCHET_CLASSES.discard(("50", "literal"))


def test_a_drawer_count_is_added_to_the_templates_and_never_replaces_it() -> None:
    """The template's measurement survives: a drawer may add its own, not erase one."""
    _problems, by_id, _drawer = _merge(
        {"54": {"nonconforming": 7}}, [{"id": "54", "ratchets": {"nonconforming": 3}}]
    )
    assert by_id["54"]["ratchets"] == {"nonconforming": 10}


def test_a_class_that_is_neither_an_app_nor_a_declared_class_is_refused() -> None:
    """The existing sentence, plus the list of the rule's declared classes."""
    problems, by_id, _drawer = _merge(
        {"50": {"not_a_thing": 4}}, [{"id": "50", "ratchets": {"literal": 0, "barrel": 0}}]
    )
    assert len(problems) == 1, problems
    assert "is not a directory under apps/" in problems[0], problems[0]
    assert "barrel, literal" in problems[0], problems[0]
    assert by_id["50"]["ratchets"] == {"literal": 0, "barrel": 0}


# --- R4 · a directory the engine plants into -------------------------------------


def test_an_engine_planted_directory_is_claimed_and_an_undeclared_one_is_not(
    tmp_path: Path,
) -> None:
    """`claimed |= {the engine's own directories}` — the half a file census cannot see."""
    canary = tmp_path / "canary"
    (canary / "partition").mkdir(parents=True)
    (canary / "partition" / "x.py").write_text("# planted by the engine\n")
    (canary / "nobodys").mkdir()
    (canary / "nobodys" / "x.py").write_text("# planted by nothing\n")
    saved = _swap(
        _GATE,
        "ENGINE_FIXTURES",
        {_GATE.CANARY_DIR / "partition" / "x.py": "the partition census plants it"},
    )
    try:
        assert _GATE.engine_fixture_dirs() == {"partition"}
        found = _GATE.fixture_dir_findings((("canary", canary),))
    finally:
        _swap(_GATE, "ENGINE_FIXTURES", saved)
    assert not [line for line in found if "partition" in line], found
    assert [line for line in found if "nobodys" in line], found


# --- V-HD1 · the three readers a product kind reached that the fix had missed ----


def test_a_file_root_is_its_own_walk_in_the_inputs_census() -> None:
    """HIGH-1: `.env.example` as a root was `--selftest-inputs` exit 2 (an emptied walk)."""
    assert (ROOT / ".env.example").is_file()
    saved = _swap(
        _GATE,
        "SCOPE_KINDS",
        {
            **_GATE.SCOPE_KINDS,
            "ledgers": {"roots": [".env.example"], "suffixes": [".md"], "comment": "#"},
        },
    )
    try:
        paths, problems = _GATE.selftest_inputs_for(_GATE.RULES)
    finally:
        _swap(_GATE, "SCOPE_KINDS", saved)
    assert problems == [], problems
    assert ".env.example" in paths


def test_an_untracked_root_is_refused_at_the_drawer_and_not_four_readers_later(
    tmp_path: Path,
) -> None:
    """LOW: the refusal's subject is the drawer, so it arrives in the drawer's own file."""
    untracked = ROOT / "zzz_drawer_untracked_probe"
    untracked.mkdir()
    try:
        (untracked / "x.md").write_text("# not git's\n")
        problems = _GATE._local_scope_kind_problems(
            {"ledgers": {"roots": [untracked.name], "suffixes": [".md"]}}
        )
    finally:
        (untracked / "x.md").unlink(missing_ok=True)
        untracked.rmdir()
    assert len(problems) == 1 and "git carries" in problems[0], problems


def test_a_product_kind_never_attributes_a_valve_to_a_template_rule() -> None:
    """HIGH-2: the walk is the union; the ATTRIBUTION is one rule's own roots."""
    saved = _swap(
        _GATE,
        "SCOPE_KINDS",
        {
            **_GATE.SCOPE_KINDS,
            "ledgers": {"roots": ["docs"], "suffixes": [".md"], "comment": "#"},
        },
    )
    try:
        # Rule 13 is a `py` rule: docs/ is not its subject, whatever a line of
        # prose there happens to look like.
        assert not _GATE.override_reaches("13", "docs/product/architecture.md")
        assert _GATE.override_reaches("13", "apps/core/services.py")
        # An id no rule claims is kept — it is some other census's finding.
        assert _GATE.override_reaches("99", "docs/product/architecture.md")
        saved_ids = _swap(_GATE, "LOCAL_RULE_IDS", frozenset({"acme-2"}))
        saved_rules = _swap(
            _GATE,
            "RULES_BY_ID",
            {**_GATE.RULES_BY_ID, "acme-2": {"id": "acme-2", "kind": "ledgers"}},
        )
        try:
            # …and the product's own rule DOES reach there, which is the half
            # that makes the union walk worth having.
            assert _GATE.override_reaches("acme-2", "docs/product/architecture.md")
        finally:
            _swap(_GATE, "RULES_BY_ID", saved_rules)
            _swap(_GATE, "LOCAL_RULE_IDS", saved_ids)
    finally:
        _swap(_GATE, "SCOPE_KINDS", saved)


def test_a_finding_class_over_its_ceiling_prints_the_line_to_paste() -> None:
    """MED: `unmeasured_app` answers None for a finding class, so it got no paste line."""
    rule = {"id": "50", "ratchets": {"literal": 0}}
    assert _GATE.drawer_ratchetable_class("50", "literal", rule)
    # An app-keyed class is not this branch's: it keeps `unmeasured_app`'s.
    assert not _GATE.drawer_ratchetable_class("55", "core", {"id": "55", "ratchets": {"core": 4}})
    findings = [_GATE.Finding("frontend/app/x.ts", 3, "a credential", "literal") for _ in range(2)]
    out = _GATE.apply_ratchets(dict(rule), findings)
    header = out[0]
    assert header.path == "quality/local/rules.yaml", header
    assert "recorded-at" in header.msg and "[fold]" in header.msg, header.msg
    assert "literal: 2" in header.msg, header.msg


def test_a_summed_ceiling_says_which_half_is_whose() -> None:
    """The finding is homed where the number lives and names both contributions."""
    _problems, by_id, _drawer = _merge(
        {"50": {"literal": 3}}, [{"id": "50", "ratchets": {"literal": 1}}]
    )
    assert by_id["50"]["ratchets"] == {"literal": 4}
    _GATE.DRAWER_RATCHET_CLASSES.add(("50", "literal"))
    _GATE.DRAWER_RATCHET_PARTS[("50", "literal")] = (1, 3)
    try:
        findings = [
            _GATE.Finding("frontend/app/x.ts", n, "a credential", "literal") for n in range(5)
        ]
        out = _GATE.apply_ratchets({"id": "50", "ratchets": {"literal": 4}}, findings)
    finally:
        _GATE.DRAWER_RATCHET_CLASSES.discard(("50", "literal"))
        _GATE.DRAWER_RATCHET_PARTS.pop(("50", "literal"), None)
    header = out[0]
    assert header.path == "quality/local/rules.yaml", header
    assert "(template 1 + drawer 3)" in header.msg, header.msg
