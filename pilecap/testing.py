"""The testing half: worlds, fixtures, wire drivers and the readers a test asserts with."""

from __future__ import annotations

from apps.core.actor import (
    actor_for,
    system_actor,
)
from apps.core.api.docs import (
    example_for,
)
from apps.core.api.pagination import (
    #: MAX_LIMIT — The ceiling on `?limit=`: a page never holds more.
    MAX_LIMIT,
)
from apps.core.api.scopes import (
    families_of_app,
)
from apps.core.asyncdb import (
    run_db,
)
from apps.core.authz import (
    allows,
    effective_role,
    kind_registry,
    refusal_sentence,
    reset_policies,
    vocabulary,
)
from apps.core.bridge import (
    BridgeNotRegistered,
)
from apps.core.bridge import (
    #: bridge_registry — The bridge's registered handlers by name, for a test to read or clear.
    _registry as bridge_registry,
)
from apps.core.bridge import (
    clear as clear_bridge,
)
from apps.core.bridge import (
    find as find_listener,
)
from apps.core.bridge import (
    get as get_listener,
)
from apps.core.bridge import (
    register as register_listener,
)
from apps.core.bridge import (
    registered as registered_listeners,
)
from apps.core.checks import (
    _VERB_TOOLS as verb_tools,
)
from apps.core.checks import (
    unauthenticated_operation_ids,
)
from apps.core.concurrency import (
    version_of,
)
from apps.core.context import (
    bind,
)
from apps.core.middleware import (
    resolve_org,
)
from apps.core.models import (
    append_only_models,
    is_append_only,
)
from apps.core.observability import (
    configure,
)
from apps.core.schemas import (
    PER_VIEWER_FIELDS,
    without_personal,
)
from apps.core.surfaces import (
    by_key,
    declared,
    forget_declarations,
    named,
)
from apps.core.tests.doors import (
    assert_four_doors,
    assert_refused_at_every_door,
    recorded_envelope,
)
from apps.core.tests.mcp_context import (
    FakeRequest,
    FakeRequestContext,
    context_for,
    tool,
)
from apps.core.tests.permissions_world import (
    #: PASSWORD — The password every permission-world user is created with.
    PASSWORD,
    World,
    build_world,
    census,
    drift,
    noun_census,
    settle_baseline,
)
from apps.core.tests.tree_census import (
    source_tree,
)
from apps.core.tests.wire import (
    MCP_HEADERS,
    MCP_URL,
    REQUEST_FIXED_QUERIES,
    bearer,
    initialize,
    rpc,
    running,
    wire,
)
from apps.core.tests.wire import (
    call as mcp_call,
)
from apps.core.tests.wire import (
    session as mcp_session,
)
from apps.core.verbs import (
    _list_forms as list_forms,
)
from apps.core.verbs import (
    derive_tool_name,
    door_url_name,
    mounted_operations,
    mounted_url_names,
)
from apps.djb_imports.models import (
    Import,
    ImportRow,
)
from apps.djb_imports.tests.store import (
    memory_store,
    stored_csv,
)
from apps.djb_notes.tests.attach_specimen import (
    attach as attach_note,
)
from apps.djb_tags.tests.attach_specimen import (
    attach as attach_tag,
)
from apps.events.activities import (
    SEARCH_INDEX_EVENT,
)
from apps.events.models import (
    Event,
)
from apps.files.tests.attach_specimen import (
    attach as attach_file,
)
from apps.realtime.tests.sockets import (
    a_token,
    an_event,
    opened,
)
from apps.search.api import (
    list_search_kinds_route,
    search_route,
)
from apps.search.engine import (
    scope_expression,
)
from apps.search.registry import (
    catalogue,
    resolve_kinds,
    validate,
)
from apps.search.selectors import (
    COOLDOWN_KEY,
    DEGRADED_KEY,
    TEXT_SEARCH_CONFIG,
    VECTOR_FIELD,
    PostgresEngine,
    get_engine_configuration,
)
from apps.search.tests.seams import (
    replace_search_engine,
)
from apps.search.types import (
    EngineUnavailable,
    IndexState,
    RecordingEngine,
)
from apps.workflows.client import (
    attach_interceptors,
    build_worker,
)
from apps.workflows.context import (
    #: reset_principal — Restore the workflow context the matching set replaced.
    reset_principal,
    set_principal,
)
from apps.workflows.models import (
    WorkflowRun,
)
from apps.workflows.services import (
    finish_run,
)
from apps.workflows.tests.seams import (
    replace_workflow_client,
)

__all__ = [
    "BridgeNotRegistered",
    "COOLDOWN_KEY",
    "DEGRADED_KEY",
    "EngineUnavailable",
    "Event",
    "FakeRequest",
    "FakeRequestContext",
    "Import",
    "ImportRow",
    "IndexState",
    "MAX_LIMIT",
    "MCP_HEADERS",
    "MCP_URL",
    "PASSWORD",
    "PER_VIEWER_FIELDS",
    "PostgresEngine",
    "REQUEST_FIXED_QUERIES",
    "RecordingEngine",
    "SEARCH_INDEX_EVENT",
    "TEXT_SEARCH_CONFIG",
    "VECTOR_FIELD",
    "WorkflowRun",
    "World",
    "a_token",
    "actor_for",
    "allows",
    "an_event",
    "append_only_models",
    "assert_four_doors",
    "assert_refused_at_every_door",
    "attach_file",
    "attach_interceptors",
    "attach_note",
    "attach_tag",
    "bearer",
    "bind",
    "bridge_registry",
    "build_worker",
    "build_world",
    "by_key",
    "catalogue",
    "census",
    "clear_bridge",
    "configure",
    "context_for",
    "declared",
    "derive_tool_name",
    "drift",
    "door_url_name",
    "effective_role",
    "example_for",
    "families_of_app",
    "find_listener",
    "finish_run",
    "forget_declarations",
    "get_engine_configuration",
    "get_listener",
    "initialize",
    "is_append_only",
    "kind_registry",
    "list_forms",
    "list_search_kinds_route",
    "mcp_call",
    "mcp_session",
    "memory_store",
    "mounted_operations",
    "mounted_url_names",
    "named",
    "noun_census",
    "opened",
    "recorded_envelope",
    "refusal_sentence",
    "register_listener",
    "registered_listeners",
    "replace_search_engine",
    "replace_workflow_client",
    "reset_policies",
    "reset_principal",
    "resolve_kinds",
    "resolve_org",
    "rpc",
    "run_db",
    "running",
    "scope_expression",
    "search_route",
    "set_principal",
    "settle_baseline",
    "source_tree",
    "stored_csv",
    "system_actor",
    "tool",
    "unauthenticated_operation_ids",
    "validate",
    "verb_tools",
    "version_of",
    "vocabulary",
    "wire",
    "without_personal",
]
