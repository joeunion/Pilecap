"""House-rule checks — pure AST/file scans over a tree, no Django required.

Every check returns a CheckResult carrying findings (path, line, message) AND
targets_matched, so the gate can distinguish pass / fail / UNBOUND (the scope
resolved to too little — green-because-empty is not a pass).

The Django system checks (rules 2, 3, 11, 13-half, 15, 17, 21) live in
`apps/core/checks.py` and run through `manage.py check --tag djb`; the gate
runs that as its own leg. Everything here is what AST can see without a
running registry.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from apps.core.lexicon import looks_plural, verb_of
from quality import loop_key as LK

# import order: the hub first — families import it at their head, it imports them last
from quality.checks._hub import _EVENT_GRAMMAR_CONSTANT as _EVENT_GRAMMAR_CONSTANT
from quality.checks._hub import _EVENT_GRAMMAR_MODULE as _EVENT_GRAMMAR_MODULE
from quality.checks._hub import _EVENT_KINDS_NAME as _EVENT_KINDS_NAME
from quality.checks._hub import _RULE8_FILES as _RULE8_FILES
from quality.checks._hub import _SCOPED_BASE as _SCOPED_BASE
from quality.checks._hub import _UNDECIDED_DRAFT_MARKER as _UNDECIDED_DRAFT_MARKER
from quality.checks._hub import _WRITE_MANAGER_CALLS as _WRITE_MANAGER_CALLS
from quality.checks._hub import (
    APP_FLOORS_ATTRIBUTE,
    EVENT_SEGMENT,
    MEMBER_FLOORS_FILE,
    CheckResult,
    Finding,
    MemberFloor,
    api_modules,
    count_model_classes,
    count_routes,
    event_name_segments,
    event_shape,
    read_member_floors,
    scoped_model_names,
    undecided_noun_census,
)
from quality.checks._hub import _app_config_class as _app_config_class
from quality.checks._hub import _app_dirs as _app_dirs
from quality.checks._hub import _app_floors_node as _app_floors_node
from quality.checks._hub import _app_is_pinned as _app_is_pinned
from quality.checks._hub import _dotted_to_file as _dotted_to_file
from quality.checks._hub import _enclosing_functions as _enclosing_functions
from quality.checks._hub import _exempt as _exempt
from quality.checks._hub import _floor_entry as _floor_entry
from quality.checks._hub import _function_at as _function_at
from quality.checks._hub import _parse as _parse
from quality.checks._hub import _py_files as _py_files
from quality.checks._hub import _read as _read
from quality.checks.rule_1 import auth_user_import
from quality.checks.rule_4 import _SIGNAL_MODULES as _SIGNAL_MODULES
from quality.checks.rule_4 import signal_logic
from quality.checks.rule_5 import (
    SCALE_ENVELOPE,
    SPEC_STAMP_RE,
    hot_path_counts,
    hot_path_registry,
    query_budget_tests,
)
from quality.checks.rule_5 import _has_paginate as _has_paginate
from quality.checks.rule_5 import _hierarchy_proposal_paths as _hierarchy_proposal_paths
from quality.checks.rule_5 import _module_constant as _module_constant
from quality.checks.rule_5 import _scale_spec_stamp as _scale_spec_stamp
from quality.checks.rule_5 import _stamp_findings as _stamp_findings
from quality.checks.rule_7 import _declared_depends as _declared_depends
from quality.checks.rule_7 import depends_on_imports
from quality.checks.rule_8 import _SCOPED_READ_METHODS as _SCOPED_READ_METHODS
from quality.checks.rule_8 import fail_closed_manager_models, scoped_reads
from quality.checks.rule_9 import _WF_ALLOWED_ROOTS as _WF_ALLOWED_ROOTS
from quality.checks.rule_9 import _WF_BANNED_CALLS as _WF_BANNED_CALLS
from quality.checks.rule_9 import _WF_SANCTIONED_RECEIVER as _WF_SANCTIONED_RECEIVER
from quality.checks.rule_9 import _admitted_modules as _admitted_modules
from quality.checks.rule_9 import _wf_sanctioned as _wf_sanctioned
from quality.checks.rule_9 import workflow_determinism
from quality.checks.rule_13_ast_half import service_shape
from quality.checks.rule_13_clauses_i_iv import _ASK_FUNCTIONS as _ASK_FUNCTIONS
from quality.checks.rule_13_clauses_i_iv import _AUTHZ_KEY_RE as _AUTHZ_KEY_RE
from quality.checks.rule_13_clauses_i_iv import _AUTHZ_KIND_DERIVED as _AUTHZ_KIND_DERIVED
from quality.checks.rule_13_clauses_i_iv import _AUTHZ_KIND_RE as _AUTHZ_KIND_RE
from quality.checks.rule_13_clauses_i_iv import _AUTHZ_RE as _AUTHZ_RE
from quality.checks.rule_13_clauses_i_iv import _CAMEL_BOUNDARY as _CAMEL_BOUNDARY
from quality.checks.rule_13_clauses_i_iv import _CRUD_VERBS as _CRUD_VERBS
from quality.checks.rule_13_clauses_i_iv import _FAMILY_MARKER_MIXINS as _FAMILY_MARKER_MIXINS
from quality.checks.rule_13_clauses_i_iv import _FAMILY_MARKER_VERBS as _FAMILY_MARKER_VERBS
from quality.checks.rule_13_clauses_i_iv import _MODEL_BASE_NAMES as _MODEL_BASE_NAMES
from quality.checks.rule_13_clauses_i_iv import _RESERVED_KEYS as _RESERVED_KEYS
from quality.checks.rule_13_clauses_i_iv import _asks as _asks
from quality.checks.rule_13_clauses_i_iv import _assigned as _assigned
from quality.checks.rule_13_clauses_i_iv import _bound_models as _bound_models
from quality.checks.rule_13_clauses_i_iv import _class_base_names as _class_base_names
from quality.checks.rule_13_clauses_i_iv import _class_level_value as _class_level_value
from quality.checks.rule_13_clauses_i_iv import _kind_findings as _kind_findings
from quality.checks.rule_13_clauses_i_iv import _model_facts as _model_facts
from quality.checks.rule_13_clauses_i_iv import _module_string_constants as _module_string_constants
from quality.checks.rule_13_clauses_i_iv import _own_kind as _own_kind
from quality.checks.rule_13_clauses_i_iv import _owned_child_declaration as _owned_child_declaration
from quality.checks.rule_13_clauses_i_iv import _snake_kind as _snake_kind
from quality.checks.rule_13_clauses_i_iv import _written_models as _written_models
from quality.checks.rule_13_clauses_i_iv import (
    ast_vocabulary,
    declared_key_sites,
    family_derived_keys,
    model_kinds,
    string_constants,
)
from quality.checks.rule_14 import _BELOW_DOOR_FILES as _BELOW_DOOR_FILES
from quality.checks.rule_14 import _HTTP_NAMES as _HTTP_NAMES
from quality.checks.rule_14 import http_below_doors
from quality.checks.rule_15_secret_at_rest_clause import _DIGEST_FIELD as _DIGEST_FIELD
from quality.checks.rule_15_secret_at_rest_clause import _RELATION_FIELDS as _RELATION_FIELDS
from quality.checks.rule_15_secret_at_rest_clause import _SECRET_FIELD as _SECRET_FIELD
from quality.checks.rule_15_secret_at_rest_clause import secret_at_rest
from quality.checks.rule_16 import event_grammar
from quality.checks.rule_16_the_rest_of_the_grammar import _SCHEMA_SUFFIXES as _SCHEMA_SUFFIXES
from quality.checks.rule_16_the_rest_of_the_grammar import _base_names as _base_names
from quality.checks.rule_16_the_rest_of_the_grammar import _call_name as _call_name
from quality.checks.rule_16_the_rest_of_the_grammar import _ClassKey as _ClassKey
from quality.checks.rule_16_the_rest_of_the_grammar import _field_assignments as _field_assignments
from quality.checks.rule_16_the_rest_of_the_grammar import _import_bindings as _import_bindings
from quality.checks.rule_16_the_rest_of_the_grammar import _model_classes as _model_classes
from quality.checks.rule_16_the_rest_of_the_grammar import _model_files as _model_files
from quality.checks.rule_16_the_rest_of_the_grammar import _module_functions as _module_functions
from quality.checks.rule_16_the_rest_of_the_grammar import _module_name as _module_name
from quality.checks.rule_16_the_rest_of_the_grammar import _scope_list as _scope_list
from quality.checks.rule_16_the_rest_of_the_grammar import _starts_with_verb as _starts_with_verb
from quality.checks.rule_16_the_rest_of_the_grammar import naming_grammar
from quality.checks.rule_18 import _ID_SHAPE as _ID_SHAPE
from quality.checks.rule_18 import _PREFIX_SUFFIX as _PREFIX_SUFFIX
from quality.checks.rule_18 import _START_NAMES as _START_NAMES
from quality.checks.rule_18 import _STARTER_HOME as _STARTER_HOME
from quality.checks.rule_18 import _SYSTEM_PREFIX as _SYSTEM_PREFIX
from quality.checks.rule_18 import _assigned_values as _assigned_values
from quality.checks.rule_18 import _starter_id_pin as _starter_id_pin
from quality.checks.rule_18 import _system_prefix_ids as _system_prefix_ids
from quality.checks.rule_18 import workflow_ids
from quality.checks.rule_19 import _LOG_CONFIG_FILES as _LOG_CONFIG_FILES
from quality.checks.rule_19 import _LOG_METHODS as _LOG_METHODS
from quality.checks.rule_19 import structured_logging
from quality.checks.rule_20_enforceable_half import _APPEND_ONLY_ATTR as _APPEND_ONLY_ATTR
from quality.checks.rule_20_enforceable_half import (
    _INSTANCE_REWRITE_ALWAYS as _INSTANCE_REWRITE_ALWAYS,
)
from quality.checks.rule_20_enforceable_half import (
    _INSTANCE_REWRITE_IF_READ_BACK as _INSTANCE_REWRITE_IF_READ_BACK,
)
from quality.checks.rule_20_enforceable_half import _QUERYSET_REWRITES as _QUERYSET_REWRITES
from quality.checks.rule_20_enforceable_half import (
    _class_attribute_is_true as _class_attribute_is_true,
)
from quality.checks.rule_20_enforceable_half import append_only_model_names, append_only_writes
from quality.checks.rule_23 import _SECRET_PATTERNS as _SECRET_PATTERNS
from quality.checks.rule_23 import supply_chain
from quality.checks.rule_24 import _INHERITED_ATTR as _INHERITED_ATTR
from quality.checks.rule_24 import _INHERITED_BASE as _INHERITED_BASE
from quality.checks.rule_24 import _MEMBERSHIP as _MEMBERSHIP
from quality.checks.rule_24 import _ORG_BASE as _ORG_BASE
from quality.checks.rule_24 import _ORG_SHAPE_FIELDS as _ORG_SHAPE_FIELDS
from quality.checks.rule_24 import _ORGANIZATION as _ORGANIZATION
from quality.checks.rule_24 import _PERMISSION_ROW_MODELS as _PERMISSION_ROW_MODELS
from quality.checks.rule_24 import _RULE24_FILES as _RULE24_FILES
from quality.checks.rule_24 import _allowed_here as _allowed_here
from quality.checks.rule_24 import _chained_after as _chained_after
from quality.checks.rule_24 import _class_bases_by_name as _class_bases_by_name
from quality.checks.rule_24 import _fk_holders_of as _fk_holders_of
from quality.checks.rule_24 import _parent_map as _parent_map
from quality.checks.rule_24 import _permission_row_writes as _permission_row_writes
from quality.checks.rule_24 import _role_writes as _role_writes
from quality.checks.rule_24 import _rule24_paths as _rule24_paths
from quality.checks.rule_24 import _shape_writes as _shape_writes
from quality.checks.rule_24 import _transitive as _transitive
from quality.checks.rule_24 import (
    inherited_downward_model_names,
    org_fk_model_names,
    org_scoped_annotation_names,
    org_scoped_model_names,
    org_scoped_reads,
    reach_population_names,
)
from quality.checks.rule_25 import _DEFAULT_SENDERS as _DEFAULT_SENDERS
from quality.checks.rule_25 import MAIL_KLASS, mail_imports
from quality.checks.rule_25 import _mail_import as _mail_import
from quality.checks.rule_25 import _permitted_senders as _permitted_senders
from quality.checks.rule_25 import _sender_packages as _sender_packages
from quality.checks.rule_25 import _senders as _senders
from quality.checks.rule_26 import _ORG_WRITE_CALLS as _ORG_WRITE_CALLS
from quality.checks.rule_26 import _REACH_RE as _REACH_RE
from quality.checks.rule_26 import _all_args as _all_args
from quality.checks.rule_26 import _annotation_names as _annotation_names
from quality.checks.rule_26 import _asked_about_at_line as _asked_about_at_line
from quality.checks.rule_26 import _named_at_line as _named_at_line
from quality.checks.rule_26 import _named_through_may_be_named as _named_through_may_be_named
from quality.checks.rule_26 import _org_bound_names as _org_bound_names
from quality.checks.rule_26 import _writes_org_scoped as _writes_org_scoped
from quality.checks.rule_26 import service_reach
from quality.checks.rule_27 import (
    CLIENT_MODULE,
    CLIENT_NAME,
    CLIENT_PACKAGE,
    PAT_SETTING,
    ZITADEL_KLASS,
    zitadel_client,
)
from quality.checks.rule_27 import _imports_client as _imports_client
from quality.checks.rule_27 import _names_pat as _names_pat
from quality.checks.rule_28 import _FINISH_ACTIVITY as _FINISH_ACTIVITY
from quality.checks.rule_28 import _FINISH_CONSTANT as _FINISH_CONSTANT
from quality.checks.rule_28 import _OWNS_NO_RUN_ATTR as _OWNS_NO_RUN_ATTR
from quality.checks.rule_28 import _RUN_DECORATOR as _RUN_DECORATOR
from quality.checks.rule_28 import _WORKFLOW_SEAM_MODULE as _WORKFLOW_SEAM_MODULE
from quality.checks.rule_28 import _WORKFLOWS_LIST as _WORKFLOWS_LIST
from quality.checks.rule_28 import _declared_workflow_names as _declared_workflow_names
from quality.checks.rule_28 import _module_seam_names as _module_seam_names
from quality.checks.rule_28 import _names_used as _names_used
from quality.checks.rule_28 import _references_finish_seam as _references_finish_seam
from quality.checks.rule_28 import _run_method as _run_method
from quality.checks.rule_28 import _seam_names as _seam_names
from quality.checks.rule_28 import workflows_close_runs
from quality.checks.rule_29 import _ROLE_BOUND_RE as _ROLE_BOUND_RE
from quality.checks.rule_29 import _ROLE_PARAM as _ROLE_PARAM
from quality.checks.rule_29 import _ROLE_READ_CALLS as _ROLE_READ_CALLS
from quality.checks.rule_29 import _ROLE_WALL as _ROLE_WALL
from quality.checks.rule_29 import _ROLE_WRITE_CALLS as _ROLE_WRITE_CALLS
from quality.checks.rule_29 import _role_positions as _role_positions
from quality.checks.rule_29 import role_bound_assignment
from quality.checks.rule_30 import _CLOCK_FIELD as _CLOCK_FIELD
from quality.checks.rule_30 import _FIELD_STRING_CALLS as _FIELD_STRING_CALLS
from quality.checks.rule_30 import _READ_KWARG_CALLS as _READ_KWARG_CALLS
from quality.checks.rule_30 import _reads_field as _reads_field
from quality.checks.rule_30 import retry_clock_readers
from quality.checks.rule_31 import _LIFECYCLE_PROBE as _LIFECYCLE_PROBE
from quality.checks.rule_31 import declared_lifecycles
from quality.checks.rule_33 import (
    ENGINE_MODULE,
    ENGINE_NAME,
    ENGINE_PACKAGE,
    MEILI_KLASS,
    MEILI_PACKAGE,
    MEILI_SETTINGS,
    meili_client,
)
from quality.checks.rule_33 import _ as _
from quality.checks.rule_33 import _imports_engine as _imports_engine
from quality.checks.rule_33 import _imports_meili as _imports_meili
from quality.checks.rule_33 import _names_meili_setting as _names_meili_setting
from quality.checks.rule_35 import _unproven_ratchet as _unproven_ratchet
from quality.checks.rule_35 import _untyped_ratchet as _untyped_ratchet
from quality.checks.rule_35 import _vacuous_negatives as _vacuous_negatives
from quality.checks.rule_35 import hot_path_sargability
from quality.checks.rule_36 import _API_PREFIX_NAME as _API_PREFIX_NAME
from quality.checks.rule_36 import _API_PREFIX_VERSION_RE as _API_PREFIX_VERSION_RE
from quality.checks.rule_36 import _API_VERSION_MARKER_RE as _API_VERSION_MARKER_RE
from quality.checks.rule_36 import _CORE_FIELDS_CACHE as _CORE_FIELDS_CACHE
from quality.checks.rule_36 import _CORE_SCHEMAS as _CORE_SCHEMAS
from quality.checks.rule_36 import _CORE_SCHEMAS_MODULE as _CORE_SCHEMAS_MODULE
from quality.checks.rule_36 import _FIELD_TEXT_RE as _FIELD_TEXT_RE
from quality.checks.rule_36 import _GROUP_BUILDER_TENANT as _GROUP_BUILDER_TENANT
from quality.checks.rule_36 import _SCHEMA_PROBE as _SCHEMA_PROBE
from quality.checks.rule_36 import _TENANT_STATUS_ENUM as _TENANT_STATUS_ENUM
from quality.checks.rule_36 import _TENANT_STATUS_LIVE as _TENANT_STATUS_LIVE
from quality.checks.rule_36 import _TENANT_STATUS_SEAM as _TENANT_STATUS_SEAM
from quality.checks.rule_36 import _UNTRACKED_CACHE as _UNTRACKED_CACHE
from quality.checks.rule_36 import _URLS_MODULE as _URLS_MODULE
from quality.checks.rule_36 import _added_lines as _added_lines
from quality.checks.rule_36 import _breaking_change_is_declared as _breaking_change_is_declared
from quality.checks.rule_36 import _callee_name as _callee_name
from quality.checks.rule_36 import _camel_suffix_pairs as _camel_suffix_pairs
from quality.checks.rule_36 import _changed_files as _changed_files
from quality.checks.rule_36 import _class_fields as _class_fields
from quality.checks.rule_36 import _core_schema_fields as _core_schema_fields
from quality.checks.rule_36 import _field_declaration_lines as _field_declaration_lines
from quality.checks.rule_36 import _git as _git
from quality.checks.rule_36 import _is_route_module as _is_route_module
from quality.checks.rule_36 import _is_test_module as _is_test_module
from quality.checks.rule_36 import _message_carries_org as _message_carries_org
from quality.checks.rule_36 import _mounted_api_version as _mounted_api_version
from quality.checks.rule_36 import _narrows_or_equals as _narrows_or_equals
from quality.checks.rule_36 import _out_fields as _out_fields
from quality.checks.rule_36 import _out_fields_inherited as _out_fields_inherited
from quality.checks.rule_36 import _out_fields_with_inheritance as _out_fields_with_inheritance
from quality.checks.rule_36 import _probe_schemas as _probe_schemas
from quality.checks.rule_36 import _ref_schemas as _ref_schemas
from quality.checks.rule_36 import _ref_source as _ref_source
from quality.checks.rule_36 import _resolve_fields as _resolve_fields
from quality.checks.rule_36 import _schema_modules as _schema_modules
from quality.checks.rule_36 import _status_writer_census as _status_writer_census
from quality.checks.rule_36 import _tenant_status_written as _tenant_status_written
from quality.checks.rule_36 import _untracked_files as _untracked_files
from quality.checks.rule_36 import (
    diff_checks,
    renamed_annotation,
    schema_renames,
    socket_group_discipline,
)
from quality.checks.rule_37 import _DATE_FIELDS as _DATE_FIELDS
from quality.checks.rule_37 import _RECENCY_COLUMN as _RECENCY_COLUMN
from quality.checks.rule_37 import _date_fields_of as _date_fields_of
from quality.checks.rule_37 import _declared_indexes as _declared_indexes
from quality.checks.rule_37 import _is_abstract as _is_abstract
from quality.checks.rule_37 import _is_the_composite as _is_the_composite
from quality.checks.rule_37 import _leads_on as _leads_on
from quality.checks.rule_37 import _meta_attribute as _meta_attribute
from quality.checks.rule_37 import _meta_parent as _meta_parent
from quality.checks.rule_37 import _model_index_of as _model_index_of
from quality.checks.rule_37 import _nested_class as _nested_class
from quality.checks.rule_37 import _string_list as _string_list
from quality.checks.rule_37 import tenant_blind_index_census
from quality.checks.rule_38 import _org_models_by_app as _org_models_by_app
from quality.checks.rule_38 import org_scoped_out_schemas
from quality.checks.rule_40 import _CORS_SETTING as _CORS_SETTING
from quality.checks.rule_40 import _CORS_SETTINGS_FILE as _CORS_SETTINGS_FILE
from quality.checks.rule_40 import _REMEDY_DESTINATION_RE as _REMEDY_DESTINATION_RE
from quality.checks.rule_40 import _REMEDY_KIND_SOURCE as _REMEDY_KIND_SOURCE
from quality.checks.rule_40 import _REQUEST_RECEIVERS as _REQUEST_RECEIVERS
from quality.checks.rule_40 import _cors_allowed as _cors_allowed
from quality.checks.rule_40 import _declared_values as _declared_values
from quality.checks.rule_40 import _header_reads as _header_reads
from quality.checks.rule_40 import _imported_modules as _imported_modules
from quality.checks.rule_40 import _is_header_constant_name as _is_header_constant_name
from quality.checks.rule_40 import _literal_root as _literal_root
from quality.checks.rule_40 import _name_root as _name_root
from quality.checks.rule_40 import _remedy_destinations as _remedy_destinations
from quality.checks.rule_40 import _remedy_kinds as _remedy_kinds
from quality.checks.rule_40 import _scope_header_helpers as _scope_header_helpers
from quality.checks.rule_40 import _scope_header_loops as _scope_header_loops
from quality.checks.rule_40 import header_contracts, header_declarations
from quality.checks.rule_41_clause import _DERIVATION_FUNCTION as _DERIVATION_FUNCTION
from quality.checks.rule_41_clause import _DERIVATION_SOURCE as _DERIVATION_SOURCE
from quality.checks.rule_41_clause import _SECOND_HOP_MODULE as _SECOND_HOP_MODULE
from quality.checks.rule_41_clause import ROUTE_METHODS
from quality.checks.rule_41_clause import _added_refusals as _added_refusals
from quality.checks.rule_41_clause import _dispatches_opaquely as _dispatches_opaquely
from quality.checks.rule_41_clause import _door_shape_vocabulary as _door_shape_vocabulary
from quality.checks.rule_41_clause import _function_in as _function_in
from quality.checks.rule_41_clause import _is_route_decorator as _is_route_decorator
from quality.checks.rule_41_clause import _raised_codes as _raised_codes
from quality.checks.rule_41_clause import _refusal_code_sites as _refusal_code_sites
from quality.checks.rule_41_clause import _refusal_codes_by_class as _refusal_codes_by_class
from quality.checks.rule_41_clause import _route_decorators as _route_decorators
from quality.checks.rule_41_clause import _second_hop_codes as _second_hop_codes
from quality.checks.rule_41_role_promise_clause import _AUTHZ_SEAM as _AUTHZ_SEAM
from quality.checks.rule_41_role_promise_clause import _AUTHZ_SOURCE as _AUTHZ_SOURCE
from quality.checks.rule_41_role_promise_clause import _AUTHZ_VALVE as _AUTHZ_VALVE
from quality.checks.rule_41_role_promise_clause import _PLATFORM_ROLE_NAME as _PLATFORM_ROLE_NAME
from quality.checks.rule_41_role_promise_clause import _ROLES_MODULE as _ROLES_MODULE
from quality.checks.rule_41_role_promise_clause import _ROLES_NAME as _ROLES_NAME
from quality.checks.rule_41_role_promise_clause import _WHOLE_VOCABULARY as _WHOLE_VOCABULARY
from quality.checks.rule_41_role_promise_clause import _calls_the_seam as _calls_the_seam
from quality.checks.rule_41_role_promise_clause import _declares_the_valve as _declares_the_valve
from quality.checks.rule_41_role_promise_clause import _module_file as _module_file
from quality.checks.rule_41_role_promise_clause import _policy_refusal_code as _policy_refusal_code
from quality.checks.rule_41_role_promise_clause import (
    _privileged_role_words as _privileged_role_words,
)
from quality.checks.rule_41_role_promise_clause import _promising_spans as _promising_spans
from quality.checks.rule_41_role_promise_clause import _seam_calls as _seam_calls
from quality.checks.rule_41_role_promise_clause import refusal_block_census
from quality.checks.rule_42 import _DOOR_KIND_BY_NAME as _DOOR_KIND_BY_NAME
from quality.checks.rule_42 import _DOOR_RE as _DOOR_RE
from quality.checks.rule_42 import (
    DOOR_GLOBS,
    DOOR_KINDS,
    EXTERNAL_DOOR_KINDS,
    FLOOR_PROXIES,
    INTERNAL_DOOR_KINDS,
    UNRESOLVED,
    count_admin_classes,
    count_apps,
    count_contract_surface,
    count_mount_surface,
    count_noun_roads,
    count_surface_questions,
    door_reachability,
)
from quality.checks.rule_42 import _called_qualnames as _called_qualnames
from quality.checks.rule_42 import _door_kind as _door_kind
from quality.checks.rule_42 import _door_modules as _door_modules
from quality.checks.rule_42 import _dotted as _dotted
from quality.checks.rule_42 import _flatten as _flatten
from quality.checks.rule_42 import _import_maps as _import_maps
from quality.checks.rule_42 import _is_first_party_module as _is_first_party_module
from quality.checks.rule_42 import _resolved_calls as _resolved_calls
from quality.checks.rule_43 import _CONTRACT_DIVIDER_SOURCE as _CONTRACT_DIVIDER_SOURCE
from quality.checks.rule_43 import _SIGNATURE_NAME_RE as _SIGNATURE_NAME_RE
from quality.checks.rule_43 import _VERIFIER_SEAM_RE as _VERIFIER_SEAM_RE
from quality.checks.rule_43 import _as_header_string as _as_header_string
from quality.checks.rule_43 import _contract_docstring as _contract_docstring
from quality.checks.rule_43 import _hmac_shape as _hmac_shape
from quality.checks.rule_43 import _signature_names as _signature_names
from quality.checks.rule_43 import outbound_signer_census
from quality.checks.rule_44 import _CENSUS_DECLARATION as _CENSUS_DECLARATION
from quality.checks.rule_44 import _MCP_PACKAGE as _MCP_PACKAGE
from quality.checks.rule_44 import _MCP_SERVER_CLASS as _MCP_SERVER_CLASS
from quality.checks.rule_44 import _NINJA_PACKAGE as _NINJA_PACKAGE
from quality.checks.rule_44 import _OWN_STATE as _OWN_STATE
from quality.checks.rule_44 import _installed_package_dir as _installed_package_dir
from quality.checks.rule_44 import _mcp_class_attributes as _mcp_class_attributes
from quality.checks.rule_44 import _mcp_server_manager_attributes as _mcp_server_manager_attributes
from quality.checks.rule_44 import _ninja_class_attributes as _ninja_class_attributes
from quality.checks.rule_44 import _ninja_source_dir as _ninja_source_dir
from quality.checks.rule_44 import _package_class_attributes as _package_class_attributes
from quality.checks.rule_44 import _private_attribute_bindings as _private_attribute_bindings
from quality.checks.rule_44 import ninja_internals_census
from quality.checks.rule_45 import _marker_is_called as _marker_is_called
from quality.checks.rule_45 import _mcp_registration_sites as _mcp_registration_sites
from quality.checks.rule_45 import mcp_dispatch_surfaces
from quality.checks.rule_46 import _DOOR_PAIR_MARKER as _DOOR_PAIR_MARKER
from quality.checks.rule_46 import _door_pairs_claimed as _door_pairs_claimed
from quality.checks.rule_46 import _door_pairs_owed as _door_pairs_owed
from quality.checks.rule_46 import _pairs_in as _pairs_in
from quality.checks.rule_46 import door_pair_parity
from quality.checks.rule_47 import _code_status_drop_site as _code_status_drop_site
from quality.checks.rule_47 import declared_refusals_documented
from quality.checks.rule_48 import _CONTENT_READ_DOORS as _CONTENT_READ_DOORS
from quality.checks.rule_48 import (
    DJANGO_STORAGE_MODULE,
    OBJECT_READ_METHODS,
    SEAM_CONTENT_READS,
    SEAM_MODULE,
    SEAM_REL,
    SIGNING_METHODS,
    STORAGE_KLASS,
    STORAGE_PACKAGES,
    STORAGE_SETTINGS,
    storage_client,
)
from quality.checks.rule_48 import _calls_by_name as _calls_by_name
from quality.checks.rule_48 import _calls_method as _calls_method
from quality.checks.rule_48 import _imports_any as _imports_any
from quality.checks.rule_48 import _names_storage_setting as _names_storage_setting
from quality.checks.rule_49 import _AUDIT_KLASS as _AUDIT_KLASS
from quality.checks.rule_49 import _AUDIT_PROBE as _AUDIT_PROBE
from quality.checks.rule_49 import _audit_allow_list as _audit_allow_list
from quality.checks.rule_49 import audit_row_shape
from quality.checks.rule_54 import _KEY_BEARING_DECLARATIONS as _KEY_BEARING_DECLARATIONS
from quality.checks.rule_54 import _MEMBERSHIP_SOURCE as _MEMBERSHIP_SOURCE
from quality.checks.rule_54 import _READ_ALIAS_VERBS as _READ_ALIAS_VERBS
from quality.checks.rule_54 import _READ_KIND_RE as _READ_KIND_RE
from quality.checks.rule_54 import _READ_OPEN_RE as _READ_OPEN_RE
from quality.checks.rule_54 import _ROLE_VALUE_CALLS as _ROLE_VALUE_CALLS
from quality.checks.rule_54 import _ROLE_VALUE_NAMES as _ROLE_VALUE_NAMES
from quality.checks.rule_54 import _ROLE_VALUE_RE as _ROLE_VALUE_RE
from quality.checks.rule_54 import _VIRTUAL_KINDS as _VIRTUAL_KINDS
from quality.checks.rule_54 import _classify_declared_key as _classify_declared_key
from quality.checks.rule_54 import _default_role_offers as _default_role_offers
from quality.checks.rule_54 import _dict_entries as _dict_entries
from quality.checks.rule_54 import _dotted_role_chain as _dotted_role_chain
from quality.checks.rule_54 import _function_valve as _function_valve
from quality.checks.rule_54 import _membership_role_readers as _membership_role_readers
from quality.checks.rule_54 import _role_declarations as _role_declarations
from quality.checks.rule_54 import _role_value_sites as _role_value_sites
from quality.checks.rule_54 import authz_vocabulary_shape
from quality.checks.rule_54_census import _READS_CENSUS_BLIND as _READS_CENSUS_BLIND
from quality.checks.rule_54_census import _clipped as _clipped
from quality.checks.rule_54_census import _read_ask_calls as _read_ask_calls
from quality.checks.rule_54_census import _read_at_phrase as _read_at_phrase
from quality.checks.rule_54_census import _reading_doors as _reading_doors
from quality.checks.rule_54_census import reads_census
from quality.checks.rule_55 import _HAT_SCOPED_RE as _HAT_SCOPED_RE
from quality.checks.rule_55 import _ROOT_CALL as _ROOT_CALL
from quality.checks.rule_55 import _RULE55_FILES as _RULE55_FILES
from quality.checks.rule_55 import _command_files as _command_files
from quality.checks.rule_55 import _node_verdict as _node_verdict
from quality.checks.rule_55 import _organization_names as _organization_names
from quality.checks.rule_55 import tenant_wide_kind_names, tenant_wide_kinds_ask_at_the_root
from quality.checks.rule_58 import _CONSUMER_BASE as _CONSUMER_BASE
from quality.checks.rule_58 import _GROUP_BUILDERS as _GROUP_BUILDERS
from quality.checks.rule_58 import _PATTERN_CALLS as _PATTERN_CALLS
from quality.checks.rule_58 import _PATTERN_LIST as _PATTERN_LIST
from quality.checks.rule_58 import _SOCKET_AUTH_WRAPPER as _SOCKET_AUTH_WRAPPER
from quality.checks.rule_58 import _as_asgi_class as _as_asgi_class
from quality.checks.rule_58 import _consumer_classes as _consumer_classes
from quality.checks.rule_58 import _derived_in as _derived_in
from quality.checks.rule_58 import _extends_the_base as _extends_the_base
from quality.checks.rule_58 import _is_derived_group as _is_derived_group
from quality.checks.rule_58 import _module_bindings as _module_bindings
from quality.checks.rule_58 import _nodes_in_scope as _nodes_in_scope
from quality.checks.rule_58 import _pattern_entries as _pattern_entries
from quality.checks.rule_58 import _resolve_binding as _resolve_binding
from quality.checks.rule_58 import _scope_bodies as _scope_bodies
from quality.checks.rule_58 import socket_join_discipline
from quality.checks.rule_59 import _ORG_KEY_NAME as _ORG_KEY_NAME
from quality.checks.rule_59 import _OUT_SUFFIX as _OUT_SUFFIX
from quality.checks.rule_59 import _all_out_fields as _all_out_fields
from quality.checks.rule_59 import _bound_in as _bound_in
from quality.checks.rule_59 import _certified_out_schemas as _certified_out_schemas
from quality.checks.rule_59 import _dict_names_the_key as _dict_names_the_key
from quality.checks.rule_59 import _emit_sites_by_name as _emit_sites_by_name
from quality.checks.rule_59 import _event_kinds_declared as _event_kinds_declared
from quality.checks.rule_59 import _event_name_constants as _event_name_constants
from quality.checks.rule_59 import _model_paired_with as _model_paired_with
from quality.checks.rule_59 import _module_helpers as _module_helpers
from quality.checks.rule_59 import _names_a_certified_out as _names_a_certified_out
from quality.checks.rule_59 import _nested_certified_out as _nested_certified_out
from quality.checks.rule_59 import _org_scoped_kind_names as _org_scoped_kind_names
from quality.checks.rule_59 import _out_named_in as _out_named_in
from quality.checks.rule_59 import _payload_carries_the_branch as _payload_carries_the_branch
from quality.checks.rule_59 import event_noun_segment, org_scoped_events_carry_their_branch
from quality.checks.rule_60_second_class import _DIVERGENCE_CENSUS as _DIVERGENCE_CENSUS
from quality.checks.rule_60_second_class import _DRAWER_CONFTEST as _DRAWER_CONFTEST
from quality.checks.rule_60_second_class import _DRAWER_CONFTEST_PATH as _DRAWER_CONFTEST_PATH
from quality.checks.rule_60_second_class import _DRAWER_LITERAL as _DRAWER_LITERAL
from quality.checks.rule_60_second_class import _DRAWER_LOCAL_MD as _DRAWER_LOCAL_MD
from quality.checks.rule_60_second_class import _DRAWER_READER_EXTRA as _DRAWER_READER_EXTRA
from quality.checks.rule_60_second_class import _DRAWER_READER_TREES as _DRAWER_READER_TREES
from quality.checks.rule_60_second_class import _DRAWER_TREE_ROOTS as _DRAWER_TREE_ROOTS
from quality.checks.rule_60_second_class import _DRAWERS_DOC as _DRAWERS_DOC
from quality.checks.rule_60_second_class import (
    DrawerRow,
    drawer_literals_opened,
    drawer_rows,
    drawers_table_findings,
    template_owned_files_carry_no_product_edits,
)
from quality.checks.rule_60_second_class import _drawer_case_absent as _drawer_case_absent
from quality.checks.rule_60_second_class import _drawer_literal as _drawer_literal
from quality.checks.rule_60_second_class import _drawer_reader_files as _drawer_reader_files
from quality.checks.rule_60_second_class import _drawer_symbol_absent as _drawer_symbol_absent
from quality.checks.rule_63 import pattern_book_names_its_instruments
from quality.checks.rule_75_resolver import (
    archivable_is_not_append_only,
    declared_class_populations,
)
from quality.checks.rule_76 import _STAMP as _STAMP
from quality.checks.rule_76 import _VERSIONED_ATTR as _VERSIONED_ATTR
from quality.checks.rule_76 import _VERSIONED_MIXIN as _VERSIONED_MIXIN
from quality.checks.rule_76 import _keyword as _keyword
from quality.checks.rule_76 import _literal_strings as _literal_strings
from quality.checks.rule_76 import _row_names as _row_names
from quality.checks.rule_76 import declared_marker_classes, versioned_writes_move_updated_at
from quality.checks.rule_84 import _BANG_RE as _BANG_RE
from quality.checks.rule_84 import _EXIT2_RE as _EXIT2_RE
from quality.checks.rule_84 import _EXIT2_ROADS as _EXIT2_ROADS
from quality.checks.rule_84 import _HAND_URL as _HAND_URL
from quality.checks.rule_84 import _HEREDOC_RE as _HEREDOC_RE
from quality.checks.rule_84 import _REASON_ROAD as _REASON_ROAD
from quality.checks.rule_84 import _SHELL_FN_RE as _SHELL_FN_RE
from quality.checks.rule_84 import _URL_JOB as _URL_JOB
from quality.checks.rule_84 import _calls_named as _calls_named
from quality.checks.rule_84 import _heredoc_lines as _heredoc_lines
from quality.checks.rule_84 import _shell_functions as _shell_functions
from quality.checks.rule_84 import road_uniqueness
from quality.checks.rule_86 import _DOOR_BODY_CALLS as _DOOR_BODY_CALLS
from quality.checks.rule_86 import _MCP_REFUSAL_CALL as _MCP_REFUSAL_CALL
from quality.checks.rule_86 import _called_name as _called_name
from quality.checks.rule_86 import _composing_door as _composing_door
from quality.checks.rule_86 import doors_compose_no_body
from quality.checks.rule_87 import _EMIT_CALL as _EMIT_CALL
from quality.checks.rule_87 import _EVENT_HELPER as _EVENT_HELPER
from quality.checks.rule_87 import _PAYLOAD_RE as _PAYLOAD_RE
from quality.checks.rule_87 import _bound_only_to_helper as _bound_only_to_helper
from quality.checks.rule_87 import _helper_returns as _helper_returns
from quality.checks.rule_87 import _is_helper_call as _is_helper_call
from quality.checks.rule_87 import _payload_through_helper as _payload_through_helper
from quality.checks.rule_87 import event_payloads_through_the_helper
from quality.checks.rule_88 import _APPS_PREFIX as _APPS_PREFIX
from quality.checks.rule_88 import _FIND_SPEC as _FIND_SPEC
from quality.checks.rule_88 import _IMPORT_MODULE as _IMPORT_MODULE
from quality.checks.rule_88 import _own_walk as _own_walk
from quality.checks.rule_88 import one_discovery_walk
from quality.checks.rule_89 import _COORDINATE_COMMENT as _COORDINATE_COMMENT
from quality.checks.rule_89 import _DOES_NOT_COVER as _DOES_NOT_COVER
from quality.checks.rule_89 import _NOQA_CODES as _NOQA_CODES
from quality.checks.rule_89 import _SHELL_DECLARATION as _SHELL_DECLARATION
from quality.checks.rule_89 import (
    COORDINATE_FAMILIES,
    COORDINATE_RE,
    COORDINATE_ROOTS,
    COORDINATE_SKIP,
    loop_key_exclusions_are_derived,
    no_plan_coordinates,
)
from quality.checks.rule_89 import _coordinate_files as _coordinate_files
from quality.checks.rule_89 import _coordinate_owner as _coordinate_owner
from quality.checks.rule_91 import _CITATION as _CITATION
from quality.checks.rule_91 import _COMMENT_MESSAGES as _COMMENT_MESSAGES
from quality.checks.rule_91 import (
    CITATION_LINE,
    COMMENT_APPS_ROOT,
    COMMENT_DRAWER,
    COMMENT_PLATFORM_MEMBERS,
    COMMENT_SKIP,
    MARKER_COMMENT,
    WHY_NOT_LINE,
    comment_census,
    comment_doctrine,
)
from quality.checks.rule_91 import _comment_files as _comment_files
from quality.checks.rule_91 import _comment_members as _comment_members
from quality.checks.rule_91 import _free_line as _free_line
from quality.checks.rule_92 import _is_on_commit_call as _is_on_commit_call
from quality.checks.rule_92 import _is_road_decorated as _is_road_decorated
from quality.checks.rule_92 import _on_commit_names as _on_commit_names
from quality.checks.rule_92 import on_commit_seams
from quality.checks.rule_93 import personal_fields_declared
from quality.checks.rule_94 import product_diff_pays_no_platform_member
from quality.checks.rule_95 import system_layer_commits_carry_their_sanction
from quality.checks.rule_96 import product_apps_import_the_sdk_only
from quality.checks.rule_97 import sdk_surface_is_ratcheted
from quality.checks.rule_98 import harness_budget, harness_census
from quality.checks.rules_6_22 import _migration_files as _migration_files
from quality.checks.rules_6_22 import (
    app_migration_leaf,
    migration_expand_contract,
    migration_leaves,
    migration_parents,
)
from quality.checks.rules_10_12 import _DOOR_FILES as _DOOR_FILES
from quality.checks.rules_10_12 import _NON_MODEL_RECEIVERS as _NON_MODEL_RECEIVERS
from quality.checks.rules_10_12 import _QS_TAIL as _QS_TAIL
from quality.checks.rules_10_12 import _chain_root as _chain_root
from quality.checks.rules_10_12 import _write_calls as _write_calls
from quality.checks.rules_10_12 import door_writes, selector_service_split
from quality.checks.rules_56_and_57 import _CLAIM_METHOD as _CLAIM_METHOD
from quality.checks.rules_56_and_57 import _DOMAIN_MODEL as _DOMAIN_MODEL
from quality.checks.rules_56_and_57 import _JOIN_BULK_CALLS as _JOIN_BULK_CALLS
from quality.checks.rules_56_and_57 import _JOIN_KEY_FIELDS as _JOIN_KEY_FIELDS
from quality.checks.rules_56_and_57 import _JOIN_KEYWORD as _JOIN_KEYWORD
from quality.checks.rules_56_and_57 import _JOIN_MODEL as _JOIN_MODEL
from quality.checks.rules_56_and_57 import _JOIN_NARROWING as _JOIN_NARROWING
from quality.checks.rules_56_and_57 import _JOIN_READS as _JOIN_READS
from quality.checks.rules_56_and_57 import _JOIN_REVERSE as _JOIN_REVERSE
from quality.checks.rules_56_and_57 import _JOIN_WRITE_CALLS as _JOIN_WRITE_CALLS
from quality.checks.rules_56_and_57 import _ROUTER_METHOD as _ROUTER_METHOD
from quality.checks.rules_56_and_57 import _SOCIALLOGIN as _SOCIALLOGIN
from quality.checks.rules_56_and_57 import _allowed_paths as _allowed_paths
from quality.checks.rules_56_and_57 import _join_rows_bound as _join_rows_bound
from quality.checks.rules_56_and_57 import _join_write as _join_write
from quality.checks.rules_56_and_57 import _names_a_join_row as _names_a_join_row
from quality.checks.rules_56_and_57 import _narrowed_to_the_join as _narrowed_to_the_join
from quality.checks.rules_56_and_57 import _reads_the_join as _reads_the_join
from quality.checks.rules_56_and_57 import _receiver_names as _receiver_names
from quality.checks.rules_56_and_57 import home_realm_router, identity_join_writers
from quality.checks.rules_81_and_82 import _ARCHIVABLE_ATTR as _ARCHIVABLE_ATTR
from quality.checks.rules_81_and_82 import _ARCHIVABLE_MIXIN as _ARCHIVABLE_MIXIN
from quality.checks.rules_81_and_82 import _ARCHIVED_AT as _ARCHIVED_AT
from quality.checks.rules_81_and_82 import _BOUND_CONSTRUCTED as _BOUND_CONSTRUCTED
from quality.checks.rules_81_and_82 import _BOUND_READ_BACK as _BOUND_READ_BACK
from quality.checks.rules_81_and_82 import _NOT_A_QUERYSET as _NOT_A_QUERYSET
from quality.checks.rules_81_and_82 import _WIDENINGS_MODULE as _WIDENINGS_MODULE
from quality.checks.rules_81_and_82 import _calls_require_live as _calls_require_live
from quality.checks.rules_81_and_82 import _is_queryset_value as _is_queryset_value
from quality.checks.rules_81_and_82 import _names_bound_to as _names_bound_to
from quality.checks.rules_81_and_82 import _names_the_archive_column as _names_the_archive_column
from quality.checks.rules_81_and_82 import _queryset_bindings as _queryset_bindings
from quality.checks.rules_81_and_82 import _queryset_rooted as _queryset_rooted
from quality.checks.rules_81_and_82 import _service_functions as _service_functions
from quality.checks.rules_81_and_82 import (
    archivable_writes_require_live,
    archive_widenings_are_the_only_widenings,
)
from quality.could_not_look import CouldNotLook
from quality.reason_floor import MIN_REASON
from quality.tree import untracked_paths
from quality.worlds import (
    BUDGETS_FILE,
    SKIP_PARTS,
    Bound,
    Valve,
    base_names,
    budget_ceiling,
    class_graph,
    comment_reason,
    decorator_names,
    descendants,
    fixed_point,
    parse_python,
    py_files,
    reaching,
    read_text,
)

REGISTRY = {
    "product_diff_pays_no_platform_member": product_diff_pays_no_platform_member,
    "product_apps_import_the_sdk_only": product_apps_import_the_sdk_only,
    "sdk_surface_is_ratcheted": sdk_surface_is_ratcheted,
    "system_layer_commits_carry_their_sanction": system_layer_commits_carry_their_sanction,
    "personal_fields_declared": personal_fields_declared,
    "on_commit_seams": on_commit_seams,
    "loop_key_exclusions_are_derived": loop_key_exclusions_are_derived,
    "comment_doctrine": comment_doctrine,
    "road_uniqueness": road_uniqueness,
    "doors_compose_no_body": doors_compose_no_body,
    "event_payloads_through_the_helper": event_payloads_through_the_helper,
    "one_discovery_walk": one_discovery_walk,
    "no_plan_coordinates": no_plan_coordinates,
    "archivable_is_not_append_only": archivable_is_not_append_only,
    "versioned_writes_move_updated_at": versioned_writes_move_updated_at,
    "archive_widenings_are_the_only_widenings": archive_widenings_are_the_only_widenings,
    "archivable_writes_require_live": archivable_writes_require_live,
    "socket_join_discipline": socket_join_discipline,
    "org_scoped_events_carry_their_branch": org_scoped_events_carry_their_branch,
    "auth_user_import": auth_user_import,
    "signal_logic": signal_logic,
    "query_budget_tests": query_budget_tests,
    "depends_on_imports": depends_on_imports,
    "scoped_reads": scoped_reads,
    "migration_leaves": migration_leaves,
    "migration_expand_contract": migration_expand_contract,
    "workflow_determinism": workflow_determinism,
    "door_writes": door_writes,
    "selector_service_split": selector_service_split,
    "service_shape": service_shape,
    "authz_vocabulary_shape": authz_vocabulary_shape,
    "tenant_wide_kinds_ask_at_the_root": tenant_wide_kinds_ask_at_the_root,
    "home_realm_router": home_realm_router,
    "identity_join_writers": identity_join_writers,
    "http_below_doors": http_below_doors,
    "event_grammar": event_grammar,
    "naming_grammar": naming_grammar,
    "workflow_ids": workflow_ids,
    "workflows_close_runs": workflows_close_runs,
    "role_bound_assignment": role_bound_assignment,
    "retry_clock_readers": retry_clock_readers,
    "tenant_blind_index_census": tenant_blind_index_census,
    "secret_at_rest": secret_at_rest,
    "structured_logging": structured_logging,
    "append_only_writes": append_only_writes,
    "org_scoped_reads": org_scoped_reads,
    "supply_chain": supply_chain,
    "mail_imports": mail_imports,
    "service_reach": service_reach,
    "door_reachability": door_reachability,
    "zitadel_client": zitadel_client,
    "meili_client": meili_client,
    "storage_client": storage_client,
    "hot_path_sargability": hot_path_sargability,
    "socket_group_discipline": socket_group_discipline,
    "org_scoped_out_schemas": org_scoped_out_schemas,
    "header_contracts": header_contracts,
    "refusal_block_census": refusal_block_census,
    "outbound_signer_census": outbound_signer_census,
    "ninja_internals_census": ninja_internals_census,
    "mcp_dispatch_surfaces": mcp_dispatch_surfaces,
    "door_pair_parity": door_pair_parity,
    "declared_refusals_documented": declared_refusals_documented,
    "declared_lifecycles": declared_lifecycles,
    "audit_row_shape": audit_row_shape,
    "template_owned_files_carry_no_product_edits": template_owned_files_carry_no_product_edits,
    "pattern_book_names_its_instruments": pattern_book_names_its_instruments,
    "harness_budget": harness_budget,
}


__all__ = [
    "APP_FLOORS_ATTRIBUTE",
    "Any",
    "BUDGETS_FILE",
    "Bound",
    "CITATION_LINE",
    "CLIENT_MODULE",
    "CLIENT_NAME",
    "CLIENT_PACKAGE",
    "COMMENT_APPS_ROOT",
    "COMMENT_DRAWER",
    "COMMENT_PLATFORM_MEMBERS",
    "COMMENT_SKIP",
    "COORDINATE_FAMILIES",
    "COORDINATE_RE",
    "COORDINATE_ROOTS",
    "COORDINATE_SKIP",
    "CheckResult",
    "CouldNotLook",
    "DJANGO_STORAGE_MODULE",
    "DOOR_GLOBS",
    "DOOR_KINDS",
    "DrawerRow",
    "ENGINE_MODULE",
    "ENGINE_NAME",
    "ENGINE_PACKAGE",
    "EVENT_SEGMENT",
    "EXTERNAL_DOOR_KINDS",
    "FLOOR_PROXIES",
    "Finding",
    "INTERNAL_DOOR_KINDS",
    "Iterable",
    "LK",
    "MAIL_KLASS",
    "MARKER_COMMENT",
    "MEILI_KLASS",
    "MEILI_PACKAGE",
    "MEILI_SETTINGS",
    "MEMBER_FLOORS_FILE",
    "MIN_REASON",
    "Mapping",
    "MemberFloor",
    "OBJECT_READ_METHODS",
    "PAT_SETTING",
    "Path",
    "REGISTRY",
    "ROUTE_METHODS",
    "SCALE_ENVELOPE",
    "SEAM_CONTENT_READS",
    "SEAM_MODULE",
    "SEAM_REL",
    "SIGNING_METHODS",
    "SKIP_PARTS",
    "SPEC_STAMP_RE",
    "STORAGE_KLASS",
    "STORAGE_PACKAGES",
    "STORAGE_SETTINGS",
    "UNRESOLVED",
    "Valve",
    "WHY_NOT_LINE",
    "ZITADEL_KLASS",
    "annotations",
    "api_modules",
    "app_migration_leaf",
    "append_only_model_names",
    "append_only_writes",
    "archivable_is_not_append_only",
    "archivable_writes_require_live",
    "archive_widenings_are_the_only_widenings",
    "ast",
    "ast_vocabulary",
    "audit_row_shape",
    "auth_user_import",
    "authz_vocabulary_shape",
    "base_names",
    "budget_ceiling",
    "class_graph",
    "comment_census",
    "comment_doctrine",
    "comment_reason",
    "count_admin_classes",
    "count_apps",
    "count_contract_surface",
    "count_model_classes",
    "count_mount_surface",
    "count_noun_roads",
    "count_routes",
    "count_surface_questions",
    "dataclass",
    "declared_class_populations",
    "declared_key_sites",
    "declared_lifecycles",
    "declared_marker_classes",
    "declared_refusals_documented",
    "decorator_names",
    "depends_on_imports",
    "descendants",
    "diff_checks",
    "door_pair_parity",
    "door_reachability",
    "door_writes",
    "doors_compose_no_body",
    "drawer_literals_opened",
    "drawer_rows",
    "drawers_table_findings",
    "event_grammar",
    "event_name_segments",
    "event_noun_segment",
    "event_payloads_through_the_helper",
    "event_shape",
    "fail_closed_manager_models",
    "family_derived_keys",
    "field",
    "fixed_point",
    "harness_budget",
    "harness_census",
    "header_contracts",
    "header_declarations",
    "home_realm_router",
    "hot_path_counts",
    "hot_path_registry",
    "hot_path_sargability",
    "http_below_doors",
    "identity_join_writers",
    "importlib",
    "inherited_downward_model_names",
    "json",
    "looks_plural",
    "loop_key_exclusions_are_derived",
    "mail_imports",
    "mcp_dispatch_surfaces",
    "meili_client",
    "migration_expand_contract",
    "migration_leaves",
    "migration_parents",
    "model_kinds",
    "naming_grammar",
    "ninja_internals_census",
    "no_plan_coordinates",
    "on_commit_seams",
    "one_discovery_walk",
    "org_fk_model_names",
    "org_scoped_annotation_names",
    "org_scoped_events_carry_their_branch",
    "org_scoped_model_names",
    "org_scoped_out_schemas",
    "org_scoped_reads",
    "os",
    "outbound_signer_census",
    "parse_python",
    "pattern_book_names_its_instruments",
    "personal_fields_declared",
    "product_apps_import_the_sdk_only",
    "py_files",
    "query_budget_tests",
    "re",
    "reach_population_names",
    "reaching",
    "read_member_floors",
    "read_text",
    "reads_census",
    "refusal_block_census",
    "renamed_annotation",
    "retry_clock_readers",
    "road_uniqueness",
    "role_bound_assignment",
    "schema_renames",
    "scoped_model_names",
    "scoped_reads",
    "sdk_surface_is_ratcheted",
    "secret_at_rest",
    "selector_service_split",
    "service_reach",
    "service_shape",
    "signal_logic",
    "socket_group_discipline",
    "socket_join_discipline",
    "storage_client",
    "string_constants",
    "structured_logging",
    "subprocess",
    "supply_chain",
    "sys",
    "system_layer_commits_carry_their_sanction",
    "tempfile",
    "template_owned_files_carry_no_product_edits",
    "tenant_blind_index_census",
    "tenant_wide_kind_names",
    "tenant_wide_kinds_ask_at_the_root",
    "undecided_noun_census",
    "untracked_paths",
    "verb_of",
    "versioned_writes_move_updated_at",
    "workflow_determinism",
    "workflow_ids",
    "workflows_close_runs",
    "yaml",
    "zitadel_client",
]
