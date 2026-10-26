"""Fixtures every app's tests share."""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import os
import pathlib
import re
import signal
import subprocess
import sys
import time
import tokenize
import warnings
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple, Protocol, TypeVar

import pytest
from asgiref.sync import AsyncToSync, SyncToAsync
from django.db import DEFAULT_DB_ALIAS, connections
from django.test import Client
from pytest_django import DjangoDbBlocker

import apps
from apps.accounts.models import User
from apps.accounts.services import create_user
from apps.core import context
from apps.core.actor import Actor, actor_for, system_actor
from apps.core.models import Membership, Organization, Tenant
from apps.core.services import add_membership, create_tenant, root_organization
from apps.core.tests.isolation import registry_difference, registry_field_names
from apps.core.tests.tree_census import source_tree
from apps.testing._hub import PASSWORD
from apps.testing.absent_world import _APPS_ROOT as _APPS_ROOT
from apps.testing.absent_world import _DJB_ABSENT_REPORT as _DJB_ABSENT_REPORT
from apps.testing.absent_world import _DJB_ABSENT_TESTS as _DJB_ABSENT_TESTS
from apps.testing.absent_world import _DJB_ABSENT_WORLD as _DJB_ABSENT_WORLD
from apps.testing.absent_world import DJB_ABSENT_APP_SUITE, AbsentWorld, collect_ignore
from apps.testing.absent_world import _absent_app_reach as _absent_app_reach
from apps.testing.absent_world import _disabled_app_labels as _disabled_app_labels
from apps.testing.absent_world import _dotted as _dotted
from apps.testing.absent_world import _imported_modules as _imported_modules
from apps.testing.absent_world import _plan_the_absent_world as _plan_the_absent_world
from apps.testing.absent_world import _reaching_the_absent as _reaching_the_absent
from apps.testing.absent_world import _withhold_the_absent_world as _withhold_the_absent_world
from apps.testing.fixtures import (
    TemporalNotDialled,
    admin_actor,
    admin_member,
    api,
    member,
    member_actor,
    nomad,
    other_root_org,
    other_tenant,
    owner,
    owner_actor,
    recorded_workflow_starts,
    root,
    root_org,
    stranger,
    stranger_actor,
    tenant,
)
from apps.testing.fixtures import __getattr__ as __getattr__
from apps.testing.fixtures import _clean_context as _clean_context
from apps.testing.fixtures import _no_dialling_temporal as _no_dialling_temporal
from apps.testing.hooks import _DJB_GATE_SLOT_CORES_PER_SLOT as _DJB_GATE_SLOT_CORES_PER_SLOT
from apps.testing.hooks import _DJB_PRERUN_NODES as _DJB_PRERUN_NODES
from apps.testing.hooks import _DJB_PRERUN_PRINTED as _DJB_PRERUN_PRINTED
from apps.testing.hooks import _DJB_WORKER_REFUSALS as _DJB_WORKER_REFUSALS
from apps.testing.hooks import (
    DJB_REFUSAL_FILE_ENV,
    DJB_WORKER_REFUSAL_KEY,
    pytest_collection_finish,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_report_collectionfinish,
    pytest_report_header,
    pytest_sessionfinish,
    pytest_testnodedown,
    pytest_xdist_node_collection_finished,
)
from apps.testing.hooks import _djb_positive_int as _djb_positive_int
from apps.testing.hooks import _djb_prerun_banner as _djb_prerun_banner
from apps.testing.hooks import _djb_slot_share as _djb_slot_share
from apps.testing.hooks import _record_refusal as _record_refusal
from apps.testing.hooks import _select_items as _select_items
from apps.testing.hooks import _write_scope_counts as _write_scope_counts
from apps.testing.impact import _DJB_MODULE_TEST_IMPORTS as _DJB_MODULE_TEST_IMPORTS
from apps.testing.impact import DJB_IMPACT_ORPHANS_SHOWN, pytest_addoption
from apps.testing.impact import _collects_the_whole_tree as _collects_the_whole_tree
from apps.testing.impact import _impact_selection as _impact_selection
from apps.testing.impact import _is_always_on as _is_always_on
from apps.testing.impact import _is_app_tests_module as _is_app_tests_module
from apps.testing.impact import _module_test_imports as _module_test_imports
from apps.testing.impact import _population_members as _population_members
from apps.testing.impact import _reach_and_populations as _reach_and_populations
from apps.testing.impact import _read_impact_select as _read_impact_select
from apps.testing.registry import _djb_registry_at_session_start as _djb_registry_at_session_start
from apps.testing.registry import (
    _no_module_rewrites_the_real_registry as _no_module_rewrites_the_real_registry,
)
from apps.testing.teardown import _FIRST_START_SECONDS as _FIRST_START_SECONDS
from apps.testing.teardown import _LATER_START_SECONDS as _LATER_START_SECONDS
from apps.testing.teardown import _NOT_THIS_STARTS_CHILD as _NOT_THIS_STARTS_CHILD
from apps.testing.teardown import _PS_HUNG as _PS_HUNG
from apps.testing.teardown import _PS_SECONDS as _PS_SECONDS
from apps.testing.teardown import _START_ATTEMPTS as _START_ATTEMPTS
from apps.testing.teardown import _TEST_SERVER as _TEST_SERVER
from apps.testing.teardown import _a_server_was_started_this_test as _a_server_was_started_this_test
from apps.testing.teardown import _a_start_has_finished_here as _a_start_has_finished_here
from apps.testing.teardown import _alive as _alive
from apps.testing.teardown import _bounded_start as _bounded_start
from apps.testing.teardown import (
    _close_connections_in_persistent_pools as _close_connections_in_persistent_pools,
)
from apps.testing.teardown import (
    _no_test_server_outlives_the_test_that_started_it as _no_test_server_outlives_the_test_that_started_it,  # noqa: E501
)
from apps.testing.teardown import _port_of as _port_of
from apps.testing.teardown import _reap as _reap
from apps.testing.teardown import _servers_started_here as _servers_started_here
from apps.testing.teardown import (
    _temporal_test_servers_are_ours_to_clean_up as _temporal_test_servers_are_ours_to_clean_up,
)
from apps.testing.teardown import (
    _terminate_strays_on_this_workers_database as _terminate_strays_on_this_workers_database,
)
from apps.testing.teardown import _test_server_children as _test_server_children
from apps.testing.teardown import _the_server_answering_is_ours as _the_server_answering_is_ours
from apps.testing.teardown import django_db_setup
from apps.testing.template_only import (
    TEMPLATE_ONLY_SKIP_PREFIX,
    TemplateOnlyReading,
    template_only_reading,
    template_only_skip_reason,
)
from apps.testing.template_only import _declared_namespace as _declared_namespace
from apps.testing.template_only import _Markable as _Markable
from apps.testing.template_only import _withhold_template_only as _withhold_template_only
from apps.testing.tier import _DJB_CENSUS_RESOLVED as _DJB_CENSUS_RESOLVED
from apps.testing.tier import _DJB_MODULE_CENSUS as _DJB_MODULE_CENSUS
from apps.testing.tier import _DJB_MODULE_ORGANS as _DJB_MODULE_ORGANS
from apps.testing.tier import _DJB_MODULE_REACH as _DJB_MODULE_REACH
from apps.testing.tier import _DJB_MODULE_REACH_POPULATIONS as _DJB_MODULE_REACH_POPULATIONS
from apps.testing.tier import _DJB_MODULE_SEEDS as _DJB_MODULE_SEEDS
from apps.testing.tier import _DJB_REACH_TOKENS_MERGED as _DJB_REACH_TOKENS_MERGED
from apps.testing.tier import _DJB_TIER_REPORT as _DJB_TIER_REPORT
from apps.testing.tier import (
    DJB_ALWAYS_ON_FIELD,
    DJB_CENSUS_MARKER,
    DJB_CENSUS_MARKER_LINES,
    DJB_CENSUS_POPULATION,
    DJB_CENSUS_SEEDED_BY,
    DJB_DECLARED_READS,
    DJB_DRAWER_KEYS,
    DJB_IMPACT_FIELD,
    DJB_ORGAN_ATTRIBUTE,
    DJB_ORGAN_FLOORS,
    DJB_POPULATION_FLOOR_DRAWER,
    DJB_POPULATION_FLOOR_MEMBERS,
    DJB_POPULATION_FLOOR_REMEDY,
    DJB_POPULATION_FLOORS,
    DJB_REACH_FLOORS,
    DJB_REACH_KINDS_KEY,
    DJB_REACH_POPULATIONS,
    DJB_REACH_TOKENS,
    DJB_REPO_ROOT,
    DJB_TEMPORAL_ENTRY_POINT,
    DJB_TEMPORAL_ORGAN,
    DJB_WALK_TOKENS,
    PopulationFloor,
    organ,
)
from apps.testing.tier import _always_on_banner as _always_on_banner
from apps.testing.tier import _always_on_headline as _always_on_headline
from apps.testing.tier import _app_label as _app_label
from apps.testing.tier import _assert_the_floors as _assert_the_floors
from apps.testing.tier import _census_banner as _census_banner
from apps.testing.tier import _census_glob_matches as _census_glob_matches
from apps.testing.tier import _census_glob_regex as _census_glob_regex
from apps.testing.tier import _census_population_or_refuse as _census_population_or_refuse
from apps.testing.tier import _census_verdict as _census_verdict
from apps.testing.tier import _code_of as _code_of
from apps.testing.tier import _drawer_reach_kinds as _drawer_reach_kinds
from apps.testing.tier import _drawer_unknown_keys as _drawer_unknown_keys
from apps.testing.tier import _FixtureFunction as _FixtureFunction
from apps.testing.tier import _fixtures_drawer as _fixtures_drawer
from apps.testing.tier import _item_organs as _item_organs
from apps.testing.tier import _module_census_declaration as _module_census_declaration
from apps.testing.tier import _module_census_population as _module_census_population
from apps.testing.tier import _module_census_reason as _module_census_reason
from apps.testing.tier import _module_of as _module_of
from apps.testing.tier import _module_organs as _module_organs
from apps.testing.tier import _module_reach as _module_reach
from apps.testing.tier import _module_reach_populations as _module_reach_populations
from apps.testing.tier import _module_seeds_a_census as _module_seeds_a_census
from apps.testing.tier import _population_floor_text as _population_floor_text
from apps.testing.tier import _population_floors as _population_floors
from apps.testing.tier import _reach_floors as _reach_floors
from apps.testing.tier import _reach_tokens as _reach_tokens
from apps.testing.tier import _way_in as _way_in

__all__ = [
    "AbsentWorld",
    "Actor",
    "Any",
    "AsyncToSync",
    "Callable",
    "Client",
    "DEFAULT_DB_ALIAS",
    "DJB_ABSENT_APP_SUITE",
    "DJB_ALWAYS_ON_FIELD",
    "DJB_CENSUS_MARKER",
    "DJB_CENSUS_MARKER_LINES",
    "DJB_CENSUS_POPULATION",
    "DJB_CENSUS_SEEDED_BY",
    "DJB_DECLARED_READS",
    "DJB_DRAWER_KEYS",
    "DJB_IMPACT_FIELD",
    "DJB_IMPACT_ORPHANS_SHOWN",
    "DJB_ORGAN_ATTRIBUTE",
    "DJB_ORGAN_FLOORS",
    "DJB_POPULATION_FLOORS",
    "DJB_POPULATION_FLOOR_DRAWER",
    "DJB_POPULATION_FLOOR_MEMBERS",
    "DJB_POPULATION_FLOOR_REMEDY",
    "DJB_REACH_FLOORS",
    "DJB_REACH_KINDS_KEY",
    "DJB_REACH_POPULATIONS",
    "DJB_REACH_TOKENS",
    "DJB_REFUSAL_FILE_ENV",
    "DJB_REPO_ROOT",
    "DJB_TEMPORAL_ENTRY_POINT",
    "DJB_TEMPORAL_ORGAN",
    "DJB_WALK_TOKENS",
    "DJB_WORKER_REFUSAL_KEY",
    "DjangoDbBlocker",
    "Iterator",
    "Mapping",
    "Membership",
    "NamedTuple",
    "Organization",
    "PASSWORD",
    "PopulationFloor",
    "Protocol",
    "Sequence",
    "SyncToAsync",
    "TEMPLATE_ONLY_SKIP_PREFIX",
    "TemplateOnlyReading",
    "TemporalNotDialled",
    "Tenant",
    "ThreadPoolExecutor",
    "TypeVar",
    "User",
    "actor_for",
    "add_membership",
    "admin_actor",
    "admin_member",
    "annotations",
    "api",
    "apps",
    "ast",
    "asyncio",
    "collect_ignore",
    "connections",
    "context",
    "create_tenant",
    "create_user",
    "django_db_setup",
    "importlib",
    "member",
    "member_actor",
    "nomad",
    "organ",
    "os",
    "other_root_org",
    "other_tenant",
    "owner",
    "owner_actor",
    "pathlib",
    "pytest",
    "pytest_addoption",
    "pytest_collection_finish",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_report_collectionfinish",
    "pytest_report_header",
    "pytest_sessionfinish",
    "pytest_testnodedown",
    "pytest_xdist_node_collection_finished",
    "re",
    "recorded_workflow_starts",
    "registry_difference",
    "registry_field_names",
    "root",
    "root_org",
    "root_organization",
    "signal",
    "source_tree",
    "stranger",
    "stranger_actor",
    "subprocess",
    "sys",
    "system_actor",
    "template_only_reading",
    "template_only_skip_reason",
    "tenant",
    "time",
    "tokenize",
    "warnings",
]
