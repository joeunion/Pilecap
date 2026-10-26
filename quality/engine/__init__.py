"""The house-rules gate: rules are data (`quality/rules.yaml`); this engine judges them.

Exit 0 clean · 1 violations · 2 enforcement broken, and 2 outranks a pass.
Every mode runs the stale-plant preflight first: a leftover planted negative reads green.
A `runner:` measures and this engine judges; ratchets, floors and attribution stay on this side.
The self-test plants into the real tree, never a copy, and refuses a tree dirty under a plant path.
"""

from __future__ import annotations

import ast
import builtins
import contextlib
import dataclasses
import datetime
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
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple

import yaml

from apps.core.roads import road
from quality import check_v1
from quality import checks as C
from quality import partition as PART
from quality import scan_ahead as SA
from quality import tree as T
from quality import worlds as W
from quality.checks import (
    EVENT_SEGMENT,
    FLOOR_PROXIES,
    REGISTRY,
    CheckResult,
    Finding,
    event_name_segments,
)
from quality.could_not_look import CouldNotLook
from quality.could_not_look import CouldNotLook as PlantCollisionCouldNotLook

# import order: the hub first — families import it at their head, it imports them last
from quality.engine._hub import _DOC as _DOC
from quality.engine._hub import (
    ENGINE,
    JUDGED_SHAPE_CENSUS,
    ROOT,
    engine_leg,
    engine_number,
    engine_probes,
)
from quality.engine.cli import _MEMO_PENDING as _MEMO_PENDING
from quality.engine.cli import (
    GRAMMAR,
    BacklogCensus,
    backlog_census,
    backlog_census_lines,
    backlog_listing,
    dated_valve_verdicts,
    live_scan,
    main,
    scan_ahead_unmemoised,
    standing_section_lines,
    valve_backlog_kind,
)
from quality.engine.explain import (
    BUDGET_TRAILER,
    RATCHET_HEADER_PATHS,
    TRAILER_KEYS,
    census_reader_census,
    census_reader_problem,
    explain,
    record_violation,
    remedy_pointer,
    resolve_census,
    rule_trailer,
    rules_listing,
    trailer_census,
    trailer_for,
    valve_lines,
)
from quality.engine.explain import _census_probe_answers as _census_probe_answers
from quality.engine.explain import _census_probe_raises as _census_probe_raises
from quality.engine.explain import _first_sentence as _first_sentence
from quality.engine.fold_map import _by_name as _by_name
from quality.engine.fold_map import _fold_map_drawer_pairs as _fold_map_drawer_pairs
from quality.engine.fold_map import _fold_map_fixture_findings as _fold_map_fixture_findings
from quality.engine.fold_map import _fold_map_fixture_paths as _fold_map_fixture_paths
from quality.engine.fold_map import _fold_map_local_rules as _fold_map_local_rules
from quality.engine.fold_map import _fold_map_product_block as _fold_map_product_block
from quality.engine.fold_map import _fold_map_remedy as _fold_map_remedy
from quality.engine.fold_map import _fold_map_rules as _fold_map_rules
from quality.engine.fold_map import _fold_map_template_block as _fold_map_template_block
from quality.engine.fold_map import _fold_map_template_files as _fold_map_template_files
from quality.engine.fold_map import (
    _fold_map_template_side_problems as _fold_map_template_side_problems,
)
from quality.engine.fold_map import _renumbered_check_ids as _renumbered_check_ids
from quality.engine.fold_map import _sha256_of as _sha256_of
from quality.engine.fold_map import _shape_hash_of as _shape_hash_of
from quality.engine.fold_map import fold_map, fold_map_lines
from quality.engine.memo import _ENGINE_DIGEST as _ENGINE_DIGEST
from quality.engine.memo import _MEASURED as _MEASURED
from quality.engine.memo import (
    MEMO_KEEP,
    MEMO_PROBE_ENV,
    MEMO_SCHEMA,
    cli_census,
    inputs_census,
    measured_blobs,
    memo_attribute,
    memo_census,
    memo_components,
    memo_consistency,
    memo_consult,
    memo_contract,
    memo_counts,
    memo_declined_ids,
    memo_declines,
    memo_home,
    memo_key,
    memo_lines,
    memo_moved,
    memo_probe,
    memo_read,
    memo_report,
    memo_reset,
    memo_state,
    memo_write,
    prefetched,
    prefetched_runners,
)
from quality.engine.memo import _captured as _captured
from quality.engine.memo import _engine_digest as _engine_digest
from quality.engine.memo import _engine_digest_of as _engine_digest_of
from quality.engine.memo import _entry_path as _entry_path
from quality.engine.memo import _paths_digest as _paths_digest
from quality.engine.plants import _PLANT_AST_CACHE as _PLANT_AST_CACHE
from quality.engine.plants import _PLANT_KIND_REACH as _PLANT_KIND_REACH
from quality.engine.plants import _REGISTERED_CHECK_ID as _REGISTERED_CHECK_ID
from quality.engine.plants import _RESOLVED as _RESOLVED
from quality.engine.plants import _RESOLVED_PRIMED as _RESOLVED_PRIMED
from quality.engine.plants import (
    DRIVE_FIXTURE_DIR,
    MIN_FIXTURE_SIGNATURE,
    NAMESPACE_EXEMPT_RE,
    NEEDS_CLEAN_TREES,
    NEEDS_SHAPES,
    PLACEHOLDER,
    PLANT_COLLIDES_BODY_RE,
    PLANT_COLLIDES_RE,
    PLANT_COLLISION_INTROSPECT_KEYS,
    PLANT_COLLISION_NO_DATABASE,
    PLANT_MODES,
    PLANT_NAMESPACE_EXAMPLE_ROOT,
    PLANT_TEXT_WORD_RE,
    PLANT_TEXT_WORD_SUFFIXES,
    SERVED_KINDS,
    Plant,
    check_id_census,
    consistency,
    plan_created_paths,
    plant_collision_census,
    plant_collision_leg,
    plant_collision_population,
    plant_collision_run,
    plant_declared_names,
    plant_event_string_re,
    plant_namespace_census,
    plant_namespace_line,
    plant_paths,
    plant_served_names,
    prime_plant_resolution,
    refuse_stale_plants,
    require_blind_spot,
    resolve_plant_text,
    stale_plants,
    tree_dirty_on_template_owned,
    tree_dirty_under_plants,
)
from quality.engine.plants import _namespace_exempt_problem as _namespace_exempt_problem
from quality.engine.plants import _plant_dotted_site as _plant_dotted_site
from quality.engine.plants import _plant_marker as _plant_marker
from quality.engine.plants import _plant_name_line as _plant_name_line
from quality.engine.plants import _plant_real_ast as _plant_real_ast
from quality.engine.plants import _plant_rel as _plant_rel
from quality.engine.plants import _plant_skip_real as _plant_skip_real
from quality.engine.readers import _GLOB_META as _GLOB_META
from quality.engine.readers import HARDCODED_READS, selftest_inputs, selftest_inputs_for
from quality.engine.readers import _expand_input as _expand_input
from quality.engine.readers import _tracked_paths as _tracked_paths
from quality.engine.rules import _RECORDED_AT as _RECORDED_AT
from quality.engine.rules import _TEXT_AT as _TEXT_AT
from quality.engine.rules import _YAML_LOADER as _YAML_LOADER
from quality.engine.rules import (
    ALLOW_LIST_KEYS,
    BARE_LISTS,
    FROZEN_LIST_HOMES,
    FROZEN_TRUNKS,
    FrozenBase,
    PlanForm,
    allow_list_census,
    allow_list_entries,
    allow_list_reasons,
    claimed_fixtures,
    duplicate_id_findings,
    engine_fixture_dirs,
    engine_fixture_findings,
    entry_forms,
    fixture_census,
    fixture_dir_findings,
    fixture_files_on_disk,
    frozen_base,
    frozen_base_suffix,
    frozen_declaration_problems,
    frozen_departures,
    frozen_entries,
    frozen_file,
    frozen_judgement,
    frozen_lists_at,
    frozen_problems,
    local_plant_consistency,
    local_ratchet_consistency,
    orphan_fixture_findings,
    plan_forms,
    plant_mode_findings,
    recorded_number,
    registry_floor_consistency,
    rule_seam_consistency,
    seam_consistency,
    text_at,
)
from quality.engine.rules import _entry_descriptor as _entry_descriptor
from quality.engine.rules import _git_at as _git_at
from quality.engine.rules import _scope_paths as _scope_paths
from quality.engine.rules import _tree_text as _tree_text
from quality.engine.rules import _yaml_child as _yaml_child
from quality.engine.rules import _yaml_number as _yaml_number
from quality.engine.rules import _yaml_path as _yaml_path
from quality.engine.run import _MARKER_TOKEN as _MARKER_TOKEN
from quality.engine.run import _RECORDING_SHA as _RECORDING_SHA
from quality.engine.run import (
    HELD_BACKLOG,
    HELD_FINDINGS,
    all_overrides,
    apply_overrides,
    apply_ratchets,
    check_budgets,
    drawer_ratchetable_class,
    finding_class_line,
    local_runner_argv,
    marker_tokens,
    measure_budgets,
    member_unmeasured_line,
    named_valve_tokens,
    override_at,
    override_reaches,
    recording_sha,
    resolve_check_problem,
    run_django_leg,
    run_rule,
    run_runner,
    standing_valves,
    unmeasured_app,
    unmeasured_line,
    weight,
)
from quality.engine.run import _docstring_lines as _docstring_lines
from quality.engine.run import _file_lines as _file_lines
from quality.engine.run import _measure_budgets_detailed as _measure_budgets_detailed
from quality.engine.run import _one_rule_valve as _one_rule_valve
from quality.engine.run import _walked_lines as _walked_lines
from quality.engine.selftest import (
    APPEND_FREE_NAME_BACKLOG,
    NEEDS_SHAPE_MEANS,
    SEAM_ABSENT_TREE,
    SEAM_REPLIES,
    SELFTEST_RESULT,
    FindingKey,
    append_free_name_bound,
    append_free_name_census,
    append_free_name_leg,
    append_free_names,
    census_leg,
    could_not_look_cause,
    declaration_leg,
    django_batch,
    drawer_case_problem,
    drawers_leg,
    form_delta,
    frozen_history_forms,
    frozen_leg,
    headroom_judgement,
    headroom_not_judged,
    judged_shape,
    member_floor_leg,
    names_planted,
    namespace_leg,
    narrowed_ids,
    plant_hygiene_census,
    ratchet_headroom,
    ratchet_leg,
    raw_form_findings,
    residence_bound,
    residence_findings,
    residence_leg,
    seam_leg,
    seam_sentinel_census,
    seam_skip_dir_census,
    seam_valve_census,
    selftest,
    selftest_floor,
    shape_verdict,
)
from quality.engine.selftest import _as_product_tree as _as_product_tree
from quality.engine.selftest import _bound_names as _bound_names
from quality.engine.selftest import _finding_key as _finding_key
from quality.engine.selftest import _not_producible_clause as _not_producible_clause
from quality.engine.selftest import _replies as _replies
from quality.engine.selftest import _seam_canaries as _seam_canaries
from quality.engine.selftest import _seam_probe as _seam_probe
from quality.engine.selftest import _seam_rule as _seam_rule
from quality.engine.world import _FLOOR_PROBLEMS as _FLOOR_PROBLEMS
from quality.engine.world import _LOCAL_PROBLEMS as _LOCAL_PROBLEMS
from quality.engine.world import _LOCAL_RATCHET_PROBLEMS as _LOCAL_RATCHET_PROBLEMS
from quality.engine.world import _NAMESPACE_PROBLEMS as _NAMESPACE_PROBLEMS
from quality.engine.world import _OVERRIDE_RES as _OVERRIDE_RES
from quality.engine.world import _PARTITION_PROBLEM as _PARTITION_PROBLEM
from quality.engine.world import (
    BUDGETS_PATH,
    CANARY_DIR,
    COULD_NOT_LOOK,
    DISABLED_APPS,
    DJANGO_ID_RE,
    DJANGO_ID_TO_RULE,
    DRAWER_RATCHET_CLASSES,
    DRAWER_RATCHET_PARTS,
    ENGINE_FIXTURES,
    GATE5_CITE,
    LOCAL_CANARY_DIR,
    LOCAL_DIR,
    LOCAL_DOC,
    LOCAL_KEYS,
    LOCAL_NEGATIVE_DIR,
    LOCAL_RULE_IDS,
    LOCAL_RULES,
    LOCAL_RULES_PATH,
    LOCAL_RUNNER_DIR,
    LOCAL_SCOPE_KINDS,
    MEMBER_FLOOR_SOURCES,
    MOVED_KEYS,
    NAMESPACE_RE,
    NEGATIVE_DIR,
    OPTIONAL_APPS,
    OVERRIDE_RE,
    PLATFORM_APPS,
    PROBE_APP,
    PROBE_APPS_PY,
    PROBE_DIR,
    RESIDENCE_BACKLOG,
    RULE_ID_NAMESPACE,
    RULES,
    RULES_BY_ID,
    RUN,
    SCOPE_KINDS,
    SEAM,
    TEMPLATE_CHECK_PREFIX,
    TEMPLATE_ID_RE,
    TEMPLATE_IDS_THROUGH,
    VENDORED_VALVE_FIXTURE,
    Run,
    check_tag_prefix,
    django_id_pattern,
    drawer_roots_remedy,
    finding_kinds,
    fixture_bases,
    fixture_home,
    fixture_trees,
    frozen_classes,
    id_grammar,
    id_shape_problem,
    is_frozen,
    is_local_rule,
    is_member_rule,
    is_template_id,
    member_rules,
    override_re,
    product_id_re,
    ratchet_home,
    ratchet_paste_key,
    say,
    violation_rule,
    world_module,
)
from quality.engine.world import _git_tracks as _git_tracks
from quality.engine.world import _local_scope_kind_problems as _local_scope_kind_problems
from quality.engine.world import _merge_local_ratchets as _merge_local_ratchets
from quality.engine.world import _merge_member_floors as _merge_member_floors
from quality.engine.world import _read_local as _read_local
from quality.engine.world import _read_namespace as _read_namespace
from quality.engine.world import _read_platform_apps as _read_platform_apps
from quality.engine.world import _scope_kinds as _scope_kinds
from quality.engine.world import _valve_id_pattern as _valve_id_pattern
from quality.reason_floor import MIN_REASON

#: The `Run` fields the door still reads as module names (`quality.gate.broken`).
_RUN_LISTS = frozenset(f.name for f in dataclasses.fields(Run))

__all__ = [
    "ALLOW_LIST_KEYS",
    "APPEND_FREE_NAME_BACKLOG",
    "Any",
    "BARE_LISTS",
    "BUDGETS_PATH",
    "BUDGET_TRAILER",
    "BacklogCensus",
    "C",
    "CANARY_DIR",
    "COULD_NOT_LOOK",
    "CheckResult",
    "CouldNotLook",
    "DISABLED_APPS",
    "DJANGO_ID_RE",
    "DJANGO_ID_TO_RULE",
    "DRAWER_RATCHET_CLASSES",
    "DRAWER_RATCHET_PARTS",
    "DRIVE_FIXTURE_DIR",
    "ENGINE",
    "ENGINE_FIXTURES",
    "EVENT_SEGMENT",
    "FLOOR_PROXIES",
    "FROZEN_LIST_HOMES",
    "FROZEN_TRUNKS",
    "Finding",
    "FindingKey",
    "FrozenBase",
    "GATE5_CITE",
    "GRAMMAR",
    "HARDCODED_READS",
    "HELD_BACKLOG",
    "HELD_FINDINGS",
    "Iterator",
    "JUDGED_SHAPE_CENSUS",
    "LOCAL_CANARY_DIR",
    "LOCAL_DIR",
    "LOCAL_DOC",
    "LOCAL_KEYS",
    "LOCAL_NEGATIVE_DIR",
    "LOCAL_RULES",
    "LOCAL_RULES_PATH",
    "LOCAL_RULE_IDS",
    "LOCAL_RUNNER_DIR",
    "LOCAL_SCOPE_KINDS",
    "MEMBER_FLOOR_SOURCES",
    "MEMO_KEEP",
    "MEMO_PROBE_ENV",
    "MEMO_SCHEMA",
    "MIN_FIXTURE_SIGNATURE",
    "MIN_REASON",
    "MOVED_KEYS",
    "ModuleType",
    "NAMESPACE_EXEMPT_RE",
    "NAMESPACE_RE",
    "NEEDS_CLEAN_TREES",
    "NEEDS_SHAPES",
    "NEEDS_SHAPE_MEANS",
    "NEGATIVE_DIR",
    "NamedTuple",
    "OPTIONAL_APPS",
    "OVERRIDE_RE",
    "PART",
    "PLACEHOLDER",
    "PLANT_COLLIDES_BODY_RE",
    "PLANT_COLLIDES_RE",
    "PLANT_COLLISION_INTROSPECT_KEYS",
    "PLANT_COLLISION_NO_DATABASE",
    "PLANT_MODES",
    "PLANT_NAMESPACE_EXAMPLE_ROOT",
    "PLANT_TEXT_WORD_RE",
    "PLANT_TEXT_WORD_SUFFIXES",
    "PLATFORM_APPS",
    "PROBE_APP",
    "PROBE_APPS_PY",
    "PROBE_DIR",
    "Path",
    "PlanForm",
    "Plant",
    "PlantCollisionCouldNotLook",
    "RATCHET_HEADER_PATHS",
    "REGISTRY",
    "RESIDENCE_BACKLOG",
    "ROOT",
    "RULES",
    "RULES_BY_ID",
    "RULE_ID_NAMESPACE",
    "RUN",
    "Run",
    "SA",
    "SCOPE_KINDS",
    "SEAM",
    "SEAM_ABSENT_TREE",
    "SEAM_REPLIES",
    "SELFTEST_RESULT",
    "SERVED_KINDS",
    "T",
    "TEMPLATE_CHECK_PREFIX",
    "TEMPLATE_IDS_THROUGH",
    "TEMPLATE_ID_RE",
    "TRAILER_KEYS",
    "ThreadPoolExecutor",
    "VENDORED_VALVE_FIXTURE",
    "W",
    "all_overrides",
    "allow_list_census",
    "allow_list_entries",
    "allow_list_reasons",
    "annotations",
    "append_free_name_bound",
    "append_free_name_census",
    "append_free_name_leg",
    "append_free_names",
    "apply_overrides",
    "apply_ratchets",
    "ast",
    "backlog_census",
    "backlog_census_lines",
    "backlog_listing",
    "broken",
    "builtins",
    "census_leg",
    "census_reader_census",
    "census_reader_problem",
    "check_budgets",
    "check_id_census",
    "check_tag_prefix",
    "check_v1",
    "claimed_fixtures",
    "cli_census",
    "consistency",
    "contextlib",
    "could_not_look_cause",
    "dated_valve_verdicts",
    "datetime",
    "declaration_leg",
    "django_batch",
    "django_id_pattern",
    "drawer_case_problem",
    "drawer_ratchetable_class",
    "drawer_roots_remedy",
    "drawers_leg",
    "duplicate_id_findings",
    "engine_fixture_dirs",
    "engine_fixture_findings",
    "engine_leg",
    "engine_number",
    "engine_probes",
    "entry_forms",
    "event_name_segments",
    "explain",
    "finding_class_line",
    "finding_kinds",
    "fixture_bases",
    "fixture_census",
    "fixture_dir_findings",
    "fixture_files_on_disk",
    "fixture_home",
    "fixture_trees",
    "fold_map",
    "fold_map_lines",
    "form_delta",
    "frozen_base",
    "frozen_base_suffix",
    "frozen_classes",
    "frozen_declaration_problems",
    "frozen_departures",
    "frozen_entries",
    "frozen_file",
    "frozen_history_forms",
    "frozen_judgement",
    "frozen_leg",
    "frozen_lists_at",
    "frozen_problems",
    "hashlib",
    "headroom_judgement",
    "headroom_not_judged",
    "id_grammar",
    "id_shape_problem",
    "inputs_census",
    "io",
    "is_frozen",
    "is_local_rule",
    "is_member_rule",
    "is_template_id",
    "json",
    "judged_shape",
    "live_scan",
    "local_plant_consistency",
    "local_ratchet_consistency",
    "local_runner_argv",
    "main",
    "marker_tokens",
    "measure_budgets",
    "measured_blobs",
    "member_floor_leg",
    "member_rules",
    "member_unmeasured_line",
    "memo_attribute",
    "memo_census",
    "memo_components",
    "memo_consistency",
    "memo_consult",
    "memo_contract",
    "memo_counts",
    "memo_declined_ids",
    "memo_declines",
    "memo_home",
    "memo_key",
    "memo_lines",
    "memo_moved",
    "memo_probe",
    "memo_read",
    "memo_report",
    "memo_reset",
    "memo_state",
    "memo_write",
    "named_valve_tokens",
    "names_planted",
    "namespace_leg",
    "narrowed_ids",
    "notes",
    "orphan_fixture_findings",
    "os",
    "override_at",
    "override_re",
    "override_reaches",
    "plan_created_paths",
    "plan_forms",
    "plant_collision_census",
    "plant_collision_leg",
    "plant_collision_population",
    "plant_collision_run",
    "plant_declared_names",
    "plant_event_string_re",
    "plant_hygiene_census",
    "plant_mode_findings",
    "plant_namespace_census",
    "plant_namespace_line",
    "plant_paths",
    "plant_served_names",
    "prefetched",
    "prefetched_runners",
    "prime_plant_resolution",
    "product_id_re",
    "ratchet_headroom",
    "ratchet_home",
    "ratchet_leg",
    "ratchet_paste_key",
    "raw_form_findings",
    "re",
    "record_violation",
    "recorded_number",
    "recording_sha",
    "refuse_stale_plants",
    "registry_floor_consistency",
    "remedy_pointer",
    "require_blind_spot",
    "residence_bound",
    "residence_findings",
    "residence_leg",
    "resolve_census",
    "resolve_check_problem",
    "resolve_plant_text",
    "road",
    "rule_seam_consistency",
    "rule_trailer",
    "rules_listing",
    "run_django_leg",
    "run_rule",
    "run_runner",
    "say",
    "scan_ahead_unmemoised",
    "seam_consistency",
    "seam_leg",
    "seam_sentinel_census",
    "seam_skip_dir_census",
    "seam_valve_census",
    "selftest",
    "selftest_floor",
    "selftest_inputs",
    "selftest_inputs_for",
    "shape_verdict",
    "shutil",
    "stale_plants",
    "standing_section_lines",
    "standing_valves",
    "subprocess",
    "sys",
    "tempfile",
    "text_at",
    "time",
    "trailer_census",
    "trailer_for",
    "tree_dirty_on_template_owned",
    "tree_dirty_under_plants",
    "unmeasured_app",
    "unmeasured_line",
    "valve_backlog_kind",
    "valve_lines",
    "violation_rule",
    "violations",
    "weight",
    "world_module",
    "yaml",
]


def __getattr__(name: str) -> list[str]:
    """`broken`, `violations`, `notes`: the door's names for this process's `RUN` lists."""
    if name in _RUN_LISTS:
        return getattr(RUN, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
