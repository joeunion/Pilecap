"""The primitives every MCP tool builds on, and the one tool that proves the mount.

A tool receives the MCP `Context`; `principal(ctx)` turns that into the acting
user and tenant, which `config.mcp`'s bearer-token middleware resolved once, at
the edge, and put on the ASGI scope. A tool never authenticates for itself and
never reads a token.

Tools call services. This one calls nothing, because its whole job is to answer
"is the door open, and whose door is it".
"""

from __future__ import annotations

import inspect
import sys
import typing
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ImproperlyConfigured
from django.db import (
    IntegrityError,
    OperationalError,
    close_old_connections,
    connections,
    models,
)
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.utilities.func_metadata import (
    StrictJsonSchema,
    _is_input_required_type,
    _returns_content,
)
from mcp_types import CallToolResult
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from apps.core import context as bound_context
from apps.core import surfaces
from apps.core.actor import Actor
from apps.core.api import ordered_by, searched
from apps.core.api.docs import contract_of
from apps.core.api.pagination import cursor_page
from apps.core.api.routes import (
    INVITATION_ORDERING,
    INVITATION_SEARCH_FIELDS,
    MEMBERSHIP_ORDERING,
    ORGANIZATION_ORDERING,
    ORGANIZATION_SEARCH_FIELDS,
    _permission_matches,
    _role_matches,
    _sorted_roles,
    add_membership_route,
    create_organization_route,
    create_role_route,
    delete_grant_route,
    delete_role_route,
    get_flags_route,
    get_organization_route,
    get_role_route,
    get_settings_route,
    invite_member_route,
    list_grants_route,
    list_invitations_route,
    list_memberships_route,
    list_organizations_route,
    list_permissions_route,
    list_roles_route,
    membership_permissions_route,
    move_organization_route,
    rename_organization_route,
    revoke_invitation_route,
    revoke_membership_route,
    set_flag_route,
    set_grant_route,
    set_role_permissions_route,
    set_role_route,
    update_role_route,
    update_settings_route,
)
from apps.core.api.scopes import (
    READ,
    SCOPE_SEPARATOR,
    WRITE,
    UnderivableScope,
    families_of_app,
    required_scope,
    within_ceiling,
)
from apps.core.api.scopes import InsufficientScope as InsufficientScope
from apps.core.authz import READ_ALIAS_VERBS, refusal_sentence
from apps.core.discovery import declared_services
from apps.core.exceptions import (
    NON_FIELD_KEY,
    Conflict,
    DomainError,
    Invalid,
    NoActingScope,
    NotFound,
    RateLimited,
    Remedy,
    database_unavailable,
    is_connection_shaped,
    refusal_message,
    register_refusal,
    wire_refusal,
)
from apps.core.flags import enabled_for
from apps.core.lexicon import verb_of
from apps.core.models import Grant, Invitation, Membership, Organization, Role, Tenant
from apps.core.schemas import (
    FlagsOut,
    GrantOut,
    GrantPage,
    InvitationFilter,
    InvitationIssuedOut,
    InvitationOut,
    InvitationPage,
    MembershipFilter,
    MembershipOut,
    MembershipPage,
    MembershipPermissionsOut,
    OrganizationFilter,
    OrganizationOut,
    OrganizationPage,
    PermissionFilter,
    PermissionOut,
    PermissionPage,
    PingOut,
    RoleFilter,
    RoleOut,
    RolePage,
    TenantSettingsOut,
)
from apps.core.selectors import (
    get_invitation,
    get_membership,
    get_membership_permissions,
    get_organization,
    get_role,
    list_grants,
    list_invitations,
    list_memberships,
    list_organizations,
    list_organizations_where,
    list_permissions,
    list_roles,
)
from apps.core.services import (
    add_membership,
    create_grant,
    create_organization,
    create_role,
    delete_grant,
    delete_role,
    invite_member,
    move_organization,
    rename_organization,
    revoke_invitation,
    revoke_membership,
    set_flag,
    set_role,
    set_role_collection,
    update_role,
    update_tenant_settings,
)
from apps.core.surfaces import STAFF, SurfaceDoesNotExpose, SurfaceUnknownHost
from apps.core.throttling import ScopeSubject, refusal

# Where the auth middleware leaves the resolved principal on the ASGI scope.
SCOPE_KEY = "djb.principal"

#: Where the machine door answers. `config.mcp` mounts the transport there and
#: `config.asgi` routes to it; it is declared HERE, with the door's other
#: primitives, so that something under `apps/` — the door index at `/`, which
#: has to name the door — can read it without an app importing `config`
#: (house rule 7's one-way street; `introspect` is the exemption, not a
#: precedent to widen).
MCP_PATH = "/mcp"


@dataclass(frozen=True)
class Principal:
    """Who a tool call is acting as. `core` does not know the user model, so the
    user is typed as the base class every user model derives from."""

    user: AbstractBaseUser
    tenant: Tenant | None
    token: models.Model | None = None
    #: The hat, resolved by the same `core.middleware.resolve_org` the
    #: HTTP door uses, from the same `X-Org` header. A tool never names it: a
    #: caller that could pass an organization as an argument would be a caller
    #: that could read a branch it holds no membership over.
    org: Organization | None = None
    #: The key of the surface the call came in at — resolved once, from the
    #: host, by the mount's middleware (`apps.core.surfaces.resolve_surface`),
    #: exactly as the HTTP door resolves `request.surface`. It narrows which
    #: tools this call may reach and which acts a row offers; it is never an
    #: argument, so no caller chooses its own audience.
    surface: str = STAFF

    def actor(self) -> Actor:
        """The actor a tool hands to a service.

        Always `agent`: a bearer token is a machine acting as a person, and an
        audit row that called that a human click would be wrong in the way that
        matters most.
        """
        return Actor(
            user=self.user,
            token=self.token,
            kind="agent",
            tenant=self.tenant,
            org=self.org,
            surface=self.surface,
        )


class NotAuthenticated(RuntimeError):
    """Raised when a tool runs without a principal — which should be impossible."""


def principal(ctx: Context[Any]) -> Principal:
    """The acting user and tenant for this tool call."""
    request = ctx.request_context.request
    resolved = getattr(request, "scope", {}).get(SCOPE_KEY) if request is not None else None
    if not isinstance(resolved, Principal):
        raise NotAuthenticated("This tool call carries no authenticated principal.")
    return resolved


def release_connections() -> None:
    """Hand back the database connections this thread borrowed.

    A synchronous tool body runs on one of the transport's worker threads, and a
    worker thread has no request cycle to close what it opened — without this,
    every thread in the pool holds a connection open for the life of the process.

    **Skipped while a transaction is open on this thread**, which is what a test
    looks like from in here (pytest-django wraps each test in one, so the
    connection's autocommit differs from the configured one and Django would drop
    it as unusable). Closing a connection out from under an open transaction
    rolls that transaction back; whoever opened it is the one who closes it.
    """
    if any(connection.in_atomic_block for connection in connections.all(initialized_only=True)):
        return
    close_old_connections()


@contextmanager
def tool_call(ctx: Context[Any]) -> Iterator[Principal]:
    """The frame every tool body runs inside. Four jobs, none of them optional.

        with tool_call(ctx) as acting:
            return WidgetOut.from_orm(get_widget(tenant=acting.tenant, widget_id=id))

    1. **Who is calling** — the principal the token middleware resolved, yielded
       so the body never reads the scope for itself.
    2. **Refusals translated once.** A service raises `apps.core.exceptions`; the
       REST door turns those into status codes in `config/api.py` and this is the
       machine door's single equivalent. A tool that caught `NotFound` itself
       would be the fourth copy of a rule that has one place to live.

       The message is not composed here either: `wire_refusal(exc)` builds the
       same body the REST door sends and `refusal_message` renders it, so the
       code leads (it is what a client branches on), the fields follow, and the
       **remedies are the same remedies** a screen would show. Two doors, one
       grammar — an assistant that offered a different way out than the screen
       did would be the drift ADR core-5 exists to close.
    3. **A true race, said the same way.** `IntegrityError` is a constraint the
       database enforced, and `config/api.py:on_integrity_error` has always
       answered it with `Conflict()`. Here it used to escape as an unhandled
       exception — the doors disagreed about the same race. They agree
       now, through the same translation, and the database's own message (which
       names tables, columns and constraint names) is not passed on.
    4. **The connection it borrowed** — see `release_connections`.

    5. **The token's ceiling** (ADR ident-7). A bearer token carries the set of
       capability families it may reach, and this is where the machine door
       checks it — before the body runs, so a refused call reaches no service,
       writes no row and leaves no audit trail. It is here rather than in a tool
       because there is one of this and sixty-nine of those, and a check a tool
       could forget is a check a tool will forget. A session and a token minted
       with no ceiling are untouched.

       **And the surface before it**, as the HTTP door asks it before the
       credential: a tool whose family the call's host does not expose is
       `surface_does_not_expose` (`refuse_off_surface`), whatever the token
       carries.
    """
    release_connections()
    try:
        acting = principal(ctx)
        refuse_off_surface(ctx, acting)
        refuse_out_of_ceiling(ctx, acting)
        yield acting
    except IntegrityError as exc:
        raise ToolError(refusal_message(wire_refusal(Conflict()))) from exc
    except OperationalError as exc:
        # 6. **The database out of reach, said the same way.** The
        #    REST door answers a connection-shaped `OperationalError` with 503
        #    and `Retry-After`; this door has neither a status line nor a
        #    header, so what it owes is the same code and the same remedies in
        #    the one line an assistant reads. Before this, an outage reached an
        #    assistant as a traceback — the same shape exactly, one seam later.
        #
        #    It re-raises what the classifier will not claim, for the reason
        #    `config/api.py:on_operational_error` does: a deadlock is not "come
        #    back later", and a tool that told an agent it was would have it
        #    hammering a healthy database.
        if not is_connection_shaped(exc):
            raise
        refusal = database_unavailable(exc, seam="mcp")
        raise ToolError(refusal_message(wire_refusal(refusal))) from exc
    except DomainError as exc:
        raise ToolError(refusal_message(wire_refusal(exc))) from exc
    finally:
        release_connections()


def acting_org(acting: Principal) -> Organization:
    """The organization a write happens in, or a refusal. **Fails closed.**

    The machine door's twin of `acting_tenant`: a token whose user holds no
    membership in the acting tenant resolves to no hat, and the answer to
    "which part of the network did you mean" is a refusal rather than a guess
    — `no_acting_scope`, the same refusal the HTTP door gives (`require_hat`).
    """
    if acting.org is None:
        # Raised as the registered refusal and composed by `tool_call`'s one
        # translation — the same body `apps.core.api.acting.require_hat` gives
        # the HTTP door, never a hand-typed `no_org:` line of this door's own.
        # The tenant is judged first, as the addressing law judges it: a hat is
        # a place inside a tenant, so a caller with neither is told about the
        # first absence, in the same words `acting_tenant` uses.
        raise NoActingScope(None if acting.tenant is None else NoActingScope.no_hat_detail)
    return acting.org


def acting_tenant(acting: Principal) -> Tenant:
    """The tenant a write happens in, or a refusal. **Fails closed.**

    A token whose user belongs to no tenant resolves to `None`, exactly as a
    session does at the REST door — and exactly as there, the answer to "which
    tenant did you mean" is a refusal rather than a guess.
    """
    if acting.tenant is None:
        # The registered refusal, said through `tool_call` exactly as
        # `apps.core.api.acting.acting` says it at the HTTP door.
        raise NoActingScope()
    return acting.tenant


def _refusal_for(scope: Mapping[str, Any]) -> RateLimited | None:
    """Run the API's throttles against an ASGI scope. Synchronous; see below."""
    resolved = scope.get(SCOPE_KEY)
    principal_ = resolved if isinstance(resolved, Principal) else None
    client = scope.get("client") or (None, None)
    return refusal(
        subject=ScopeSubject(
            # The same object ninja's `AuthRateThrottle` hashes at the REST door,
            # so one client gets one allowance rather than one per door.
            auth=principal_.user if principal_ is not None else None,
            tenant=principal_.tenant if principal_ is not None else None,
            META={"REMOTE_ADDR": str(client[0] or "")},
        )
    )


async def rate_limit_refusal(scope: Mapping[str, Any]) -> RateLimited | None:
    """What this MCP call has earned: `None`, or the refusal to answer with.

    The counters live in the shared cache, and reading them is blocking work, so
    it happens off the event loop the transport is running on — the same reason
    `apps.core.asyncdb.run_db` exists for the ORM. It is not the ORM, so it does
    not go through `run_db`: nothing here opens a database connection to close.
    """
    return await sync_to_async(_refusal_for, thread_sensitive=False)(scope)


def _user_by_id(user_id: UUID) -> AbstractBaseUser:
    """The person an id names, or `not_found`.

    A membership names a user who may not be in this tenant yet — that is the
    whole point of adding one — so this cannot narrow by tenant, and there is
    nothing to narrow by anyway: `accounts.User` is not a scoped model. What
    keeps it honest is the escalation wall in `add_membership`, which is about
    the granter rather than the grantee.

    `NotFound` rather than `Invalid`: an id that resolves to nobody and an id
    that resolves to somebody you may not name are one answer, here as
    everywhere else.
    """
    found = get_user_model().objects.filter(pk=user_id).first()
    if found is None:
        raise NotFound()
    return found


# --- ADR ident-7: what a tool costs, and the ceiling that has to cover it ------
#
# THE DERIVATION, NOT AN ANNOTATION. A tool's required scope is worked out from
# what is already true about it, in three steps that stop at the first answer:
#
#   1. it declared that it reaches no capability (and said why);
#   2. it is the twin of a REST operation — which is decided by the two of them
#      describing themselves with the SAME text, the identity house rule 41
#      already enforces — and then the twin's scope is the tool's scope;
#   3. it has no twin, so it is classified by its own name against the two
#      grammars this product already speaks: a selector's `get`/`list` reads,
#      and a service's verb writes.
#
# A tool that reaches none of the three is a FINDING and raises. There is no
# fallback on purpose: a default would put a tool outside every ceiling in the
# product and nothing would ever say so.
#
# WHY THE TWIN IS FOUND BY ITS PROSE. The obvious key is the name, and the name
# needs a table of verb spellings (`list_{noun}s`, `get_{noun}`, …) that would be
# a second copy of the one house rule 17 keeps. The prose is already pinned equal
# by rule 41 — `description=contract_of(<the route>)` is how every tool in this
# tree is registered — so matching on it borrows an invariant instead of
# restating one. Two routes sharing one docstring would be ambiguous rather than
# wrong: the pair is dropped, the tool falls through to the name grammar, and the
# census is where that becomes visible.

#: Set by `reaches_no_capability` and read by the derivation. An attribute on the
#: function rather than a list somewhere, so the reason travels with the tool and
#: a reader meets it where the decision was made — the same shape `owns_no_run`,
#: `export_excluded` and `# door:` all take.
NO_CEILING_ATTR = "djb_reaches_no_capability"


def reaches_no_capability[F: Callable[..., Any]](reason: str) -> Callable[[F], F]:
    """Declare that this tool needs no scope, and say why in a sentence.

        @server.tool(name="ping", description=...)
        @reaches_no_capability("it reads back the caller's own principal")
        def ping(ctx): ...

    For the handful of tools that reach nothing a ceiling could narrow — the one
    that answers "is this door open", and whatever a product adds beside it. It
    is a declaration and not an exemption list: the reason sits on the tool, the
    census counts every one of them and prints it, and a blank reason is refused
    here rather than discovered later.
    """
    if not reason.strip():
        raise ValueError(
            "a tool that needs no scope has to say why — the sentence is what a "
            "reviewer disagrees with, and a bare exemption is one nobody can"
        )

    def declare(fn: F) -> F:
        setattr(fn, NO_CEILING_ATTR, reason.strip())
        return fn

    return declare


#: The derivation's two caches. The registries behind them are fixed once the
#: apps have imported, and `tool_call` runs on every call — walking every route
#: in the product per tool call would be a real cost for an answer that cannot
#: have changed. `reset_scope_derivation()` is what a test that plants a router
#: or a tool calls, the same seam `core.authz.reset_policies` is for policies.
_twin_scopes: dict[str, str] | None = None
_service_verbs: frozenset[str] | None = None


def reset_scope_derivation() -> None:
    """Drop the derivation's caches. For tests that plant a route or a tool."""
    global _twin_scopes, _service_verbs
    _twin_scopes = None
    _service_verbs = None


def _operations_by_contract() -> dict[str, str]:
    """Every REST operation's required scope, keyed on the prose it publishes.

    Read off the mounted API through `apps.core.api.mount.bound_operations`,
    the one mount reader (imported inside the call: it imports `config.api`
    lazily, which an app never does at module level — house rule 7's one-way
    street). A bound operation carries its router's tags; an operation whose
    tag is missing or doubled derives nothing here, and rule 41 refuses the
    doubled case one surface earlier.
    """
    from apps.core.api.mount import bound_operations

    found: dict[str, str] = {}
    ambiguous: set[str] = set()
    for _path, _name, operation in bound_operations():
        contract = contract_of(operation.view_func)
        if not contract:
            continue
        try:
            scope = required_scope(tags=operation.tags or [], methods=operation.methods)
        except UnderivableScope:
            continue
        if contract in found and found[contract] != scope:
            ambiguous.add(contract)
        found[contract] = scope
    for contract in ambiguous:
        # Two operations describing themselves identically and needing different
        # scopes: the prose can no longer say which twin a tool has. Dropped
        # rather than guessed, so the tool falls to the name grammar or raises.
        found.pop(contract, None)
    return found


def twin_of(operation: Any, tools: Iterable[Any]) -> Any | None:
    """The MCP tool that is `operation`'s twin — the one publishing its contract word for word.

    The PROSE identity house rule 41 pins (`description=contract_of(view)`), asked
    once here: rule 17 falls back to it for a twin whose name is not the
    url_name's derivation, and `apps/core/tests/test_tool_names.py` reads it to
    name every such pair. `None` when no tool carries the contract, or when two
    do — two twins is no twin, and picking one would be a guess.
    """
    contract = contract_of(operation.view_func)
    if not contract:
        return None
    matches = [tool for tool in tools if str(tool.description or "") == contract]
    return matches[0] if len(matches) == 1 else None


def service_verbs() -> frozenset[str]:
    """Every verb this deployment's own services begin with. A census, not a list.

    The write half of the tool grammar, taken from the tree rather than from the
    gate's configuration: rule 16's declared lexicon was built out of these same
    functions, so reading them directly agrees with it by construction instead of
    by somebody keeping two lists in step.
    """
    global _service_verbs
    if _service_verbs is not None:
        return _service_verbs
    # The one matcher (`apps.core.lexicon.verb_of`) — the gate's rule 16 and the
    # history card ask the same function, so a verb is one word to all three.
    verbs = {verb_of(name) for _, name, _ in declared_services() if not name.startswith("_")}
    _service_verbs = frozenset(verbs)
    return _service_verbs


def _scope_from_the_name(name: str, *, app_label: str) -> str:
    """A twinless tool's scope, from its own name and the app that registered it.

    The family is the app's, and only when the app owns exactly one: an app that
    declares two sections has not said which of them a tool without a twin
    belongs to, and picking one would be this function inventing the answer.
    """
    owned = families_of_app(app_label)
    if len(owned) != 1:
        raise UnderivableScope(
            f"the tool {name!r} has no twin at the HTTP door, so its family would have "
            f"to come from its app — and {app_label!r} owns {len(owned)} sections "
            f"({', '.join(owned) or 'none'}), so there is no one answer. Give it a "
            "twin, or register it in an app that owns one section"
        )
    verb = verb_of(name)
    # The read half of the tool grammar is `authz`'s one alias set: a tool that
    # reads is named the way a key that reads may be spelled.
    if verb in READ_ALIAS_VERBS:
        return f"{owned[0]}{SCOPE_SEPARATOR}{READ}"
    if verb in service_verbs():
        return f"{owned[0]}{SCOPE_SEPARATOR}{WRITE}"
    raise UnderivableScope(
        f"the tool {name!r} begins with {verb!r}, which is neither a way of reading "
        f"({', '.join(sorted(READ_ALIAS_VERBS))}) nor a verb any service in this product "
        "uses — so nothing here can say whether it reads or writes. Name it after what "
        "it does, or give it a twin at the HTTP door"
    )


def scope_for_tool(tool: Any) -> str | None:
    """The scope a tool needs, or `None` when it declared that it needs none.

    Raises `UnderivableScope` rather than answering when none of the three steps
    reaches an answer — see this section's opening note on why there is no
    fallback.
    """
    global _twin_scopes
    if getattr(tool.fn, NO_CEILING_ATTR, ""):
        return None
    if _twin_scopes is None:
        _twin_scopes = _operations_by_contract()
    twin = _twin_scopes.get(str(tool.description or ""))
    if twin is not None:
        return twin
    module = str(getattr(tool.fn, "__module__", ""))
    parts = module.split(".")
    app_label = parts[1] if len(parts) >= 2 and parts[0] == "apps" else ""
    return _scope_from_the_name(str(tool.name), app_label=app_label)


def tool_scopes(server: MCPServer[Any]) -> dict[str, str | None]:
    """Every registered tool and the scope it needs. The census, in one call.

    `None` against a name means that tool declared it reaches no capability.
    Raises on the first tool that derives nothing, which is what makes this a
    census rather than a report: a tool nothing can classify is a hole in the
    ceiling, and a census that skipped it would hide exactly that.

    **The server is a parameter and not an import.** This module is under
    `apps/` and the mount is under `config/`, and the arrow between them points
    one way (house rule 7): `config` calls into an app, never the reverse. A
    caller that wants the census over the real deployment hands over the real
    server — which is what the mount already does when it calls `register`.
    """
    return {tool.name: scope_for_tool(tool) for tool in server._tool_manager.list_tools()}


#: How the requirement is spelled in a tool's published description. One line,
#: derived, and phrased for the agent that has to decide what to ask its human
#: for — which is the whole reason an out-of-ceiling tool stays in the listing.
TOOL_SCOPE_SENTENCE = (
    "Token scope: this tool needs `{scope}`. A token that does not carry it is "
    "refused when the tool is called; ask for a token minted with `{scope}` and "
    "call it again."
)

#: The same clause the HTTP door adds to a read requirement, for the same
#: reason: an agent holding the write half of a section should not go and ask
#: its human for a second token to do something the first one already allows.
TOOL_WRITE_INCLUDES_READ = (
    " A token carrying `{family}:write` satisfies this too: within one section, "
    "the write scope includes the read."
)


def described_with_scope(description: str, scope: str | None) -> str:
    """A tool's published prose plus the line saying which scope reaches it.

    Applied to what `tools/list` sends and never to the registered description,
    for the same reason the HTTP door keeps the two apart: house rule 41 holds
    the registered text equal to its twin's docstring, and this is a derivation
    printed beside that text rather than a second copy of it.
    """
    if scope is None:
        return description
    line = TOOL_SCOPE_SENTENCE.format(scope=scope)
    family, _, verb = scope.rpartition(SCOPE_SEPARATOR)
    if verb == READ and family:
        line += TOOL_WRITE_INCLUDES_READ.format(family=family)
    return f"{description.rstrip()}\n\n{line}" if description.strip() else line


def _tool_name_of(ctx: Context[Any]) -> str:
    """Which tool this call is for, off the request the transport parsed.

    A tool body never needs this — it knows what it is — but the ceiling check
    does, and it runs in the one frame every tool enters rather than in
    sixty-nine of them. Raises rather than returning a blank if the transport
    ever stops carrying it: a ceiling check that quietly could not tell which
    tool it was guarding would pass everything, which is the failure mode worth
    being loud about.
    """
    params = getattr(ctx.request_context, "params", None)
    name = params.get("name") if isinstance(params, Mapping) else None
    if not name:
        inbound = getattr(ctx, "_input_params", None)
        name = getattr(inbound, "name", None)
    if not name:
        raise NotAuthenticated(
            "this tool call carries no tool name, so the token's ceiling cannot be "
            "checked against it; nothing is answered rather than answered unguarded"
        )
    return str(name)


def ceiling_of(acting: Principal) -> Sequence[str] | None:
    """The scopes this credential is limited to, or `None` for "not limited".

    Asked FIRST by both positions of the check, and that ordering is load
    bearing rather than tidy: a session and a `*` token are answered without
    anything touching the server, the registry or the call — which is what keeps
    a tool called as a plain function with a hand-built context (the house test
    shape, `django-conventions` §12) working exactly as it did.
    """
    token = acting.token
    if token is None:
        return None
    scopes: Sequence[str] | None = getattr(token, "scopes", None)
    return scopes


def ceiling_refusal(tool: Any, acting: Principal) -> InsufficientScope | None:
    """The refusal this principal has earned for this tool, or `None`.

    **A predicate over the credential and the tool, and nothing else** — it
    never sees the call's arguments, which is what lets the same answer be
    reached from two places: from inside the tool frame (`refuse_out_of_ceiling`,
    below) and from in front of the transport's argument validation
    (`install_ceiling_gate`). One derivation, two positions; a second copy of
    this arithmetic is how the two positions would come to disagree.

    A session has no ceiling and neither has a token minted without one; what a
    narrow token gets is the same refusal the HTTP door sends, composed later by
    the same `wire_refusal` and rendered by the same `refusal_message`, so an
    agent and a screen are told the same thing about the same credential.

    **An underivable tool refuses a ceilinged token rather than passing it.**
    That is the HTTP door's own answer to the same question
    (`config/api.py::_refused_for_scope` with `required=None`): a capability
    nothing can classify is not a capability everything reaches. A session and a
    `*` token are untouched, so the tree stays usable while rule 41 says the
    true thing about the true cause.
    """
    ceiling = ceiling_of(acting)
    if ceiling is None:
        return None
    try:
        required = scope_for_tool(tool)
    except UnderivableScope:
        return InsufficientScope(
            "This tool does not say which scope reaches it, so a token limited to "
            "a set of scopes cannot be checked against it. Sign in with a session, "
            "or use a token minted with no limit."
        )
    if required is None or within_ceiling(ceiling=ceiling, scope=required):
        return None
    return InsufficientScope(
        f"This token is not scoped for that. It needs {required!r}, and it "
        f"carries {', '.join(repr(held) for held in sorted(ceiling)) or 'nothing'}. "
        "Mint a token that carries it, or make this call with a session instead."
    )


def refuse_out_of_ceiling(ctx: Context[Any], acting: Principal) -> None:
    """Refuse this call when the token's ceiling does not reach this tool.

    The machine door's half of ADR ident-7, in the one contextmanager every tool
    body already enters.

    **This is the belt, and `install_ceiling_gate` is the braces.** The wall that
    an agent actually meets stands one layer out, in front of the
    transport's argument validation, because a check *inside* the body runs
    after the arguments have been parsed and a refusal composed from a parse
    failure names the tool's parameters — the schema of a capability the
    credential was never allowed to reach. This one stays because `tool_call` is
    the frame every body enters and a dispatch path that did not come through
    the mount's wrapper would otherwise arrive unguarded; the derivation is
    shared, so the two cannot answer differently.

    **The tool is refused, never hidden.** It is still in `tools/list`, still
    describes itself, and still says which scope would reach it — because an
    agent that can tell its human what to mint has a way forward, and one that
    was told the capability does not exist has none.

    **The server comes off the context, not out of an import.** The mount lives
    in `config/` and this module lives under `apps/`, where naming it would be
    the wrong way down a one-way street (house rule 7) — and the context is the
    better source anyway: it is the server actually handling this call rather
    than whichever one the process happens to have built.
    """
    if ceiling_of(acting) is None:
        return
    refusal = ceiling_refusal(_called_tool(ctx), acting)
    if refusal is not None:
        raise refusal


def _called_tool(ctx: Context[Any]) -> Any:
    """The registered tool this call is for; refuses rather than guessing when there is none.

    A body is running for a tool the registry does not hold, which cannot happen
    through the transport (the manager refuses an unknown name before dispatch)
    and must not be answered "allowed" if it ever does — so the two walls asked
    inside the frame, the surface and the ceiling, both fail closed here.
    """
    tool = ctx.mcp_server._tool_manager.get_tool(_tool_name_of(ctx))
    if tool is None:
        raise NotAuthenticated(
            "this tool call names a tool this server does not hold, so its walls "
            "cannot be checked; nothing is answered rather than answered unguarded"
        )
    return tool


# --- The surface: which host the call came in at narrows what it may reach ----
#
# A surface (`apps.core.surfaces`) is a host and the scope families it exposes.
# The HTTP door asks `config/api.py::_refused_for_surface` of every operation,
# before the credential; these are the machine door's twin, asking the SAME
# predicate (`surfaces.exposes`) of a tool's family — the family its scope is
# derived from, the one derivation the ceiling uses — so a REST route and its
# MCP twin are on the same surfaces by construction. Refused, the call answers
# `surface_does_not_expose`, the code REST answers; and the listing at a host
# leaves out what that host does not expose, as the OpenAPI document does —
# the reach-refusal posture (rule 26): a customer host is not an oracle for the
# staff door map. A product that declares no surface has one total surface, and
# none of this moves a byte.


def _tool_family(tool: Any) -> tuple[bool, str | None]:
    """Whether a surface narrows this tool at all, and the scope family it belongs to.

    A tool that declared it reaches no capability (`reaches_no_capability`) is
    not narrowed — there is nothing behind it for a surface to withhold, which
    is the ceiling's answer to the same tool. A tool whose scope derives nothing
    has no family, and a surface that names its families does not expose it:
    fail closed, as the HTTP door does for an operation with no one tag.
    """
    try:
        required = scope_for_tool(tool)
    except UnderivableScope:
        return True, None
    if required is None:
        return False, None
    return True, required.rpartition(SCOPE_SEPARATOR)[0] or None


def surface_refusal(
    tool: Any, surface: surfaces.Surface | None
) -> SurfaceDoesNotExpose | SurfaceUnknownHost | None:
    """The refusal this surface owes a call to this tool, or `None` when the surface exposes it.

    A predicate over the tool and the surface, like `ceiling_refusal`, so the
    wall in front of the arguments and the belt inside the frame reach one
    answer. `None` for a surface is one nothing resolved, and nothing is exposed
    on it.
    """
    narrowed, family = _tool_family(tool)
    if not narrowed or surfaces.exposes(surface, family):
        return None
    if surface is None:
        return SurfaceUnknownHost()
    return surfaces.does_not_expose(surface)


def surface_named(key: str | None) -> surfaces.Surface | None:
    """The declared surface a door recorded by its key; `None` for no key or an undeclared one."""
    return surfaces.declared().get(key) if key else None


def refuse_off_surface(ctx: Context[Any], acting: Principal) -> None:
    """Refuse this call when the surface it came in at does not expose this tool's family.

    `refuse_out_of_ceiling`'s twin, and asked BEFORE it, in the order the HTTP
    door asks the two: whether this host offers the capability at all is a fact
    about the address, and a credential question answered first would tell a
    caller on a customer host that a staff tool exists behind it.

    A total surface is answered before the context is touched — a surface that
    exposes even a call of no family exposes every one — so a tool called as a
    plain function with a hand-built context works exactly as it did.
    """
    surface = surface_named(acting.surface)
    if surfaces.exposes(surface, None):
        return
    refusal = surface_refusal(_called_tool(ctx), surface)
    if refusal is not None:
        raise refusal


def listed_here(server: MCPServer[Any], listed: Sequence[Any]) -> list[Any]:
    """The listed tools the surface this request came in at exposes — every one, outside a request.

    The surface is the one the mount's middleware bound for this request
    (`context`, beside `door`), the same read the OpenAPI document narrows by,
    so a host's tool list and its document cannot disagree about what it offers.
    Outside a request nothing is bound and the list is whole; on a total surface
    it is whole too, byte for byte.
    """
    bound = bound_context.value("surface")
    if not bound:
        return list(listed)
    surface = surface_named(str(bound))
    if surfaces.exposes(surface, None):
        return list(listed)
    return [
        tool
        for tool in listed
        if (registered := server._tool_manager.get_tool(str(tool.name))) is not None
        and surface_refusal(registered, surface) is None
    ]


def _listed_scope(server: MCPServer[Any], name: str) -> str | None:
    """The scope for one listed tool, or `None` if it derives nothing.

    The listing is the one place a derivation failure must not raise: an agent
    asking what it can do should get the catalogue, and a tool with no scope
    line is a finding the census reports rather than an error that empties the
    list. `tool_scopes()` is where an underivable tool is loud.
    """
    tool = server._tool_manager.get_tool(name)
    if tool is None:  # pragma: no cover - the listing named it a line ago
        return None
    try:
        return scope_for_tool(tool)
    except UnderivableScope:
        return None


def install_scope_lines(server: MCPServer[Any]) -> None:
    """Put the derived scope on every listed tool, once, at the mount.

    Wraps the server's own listing rather than editing the tools, and does it
    lazily — the wrapper runs per request, by which time every app has
    registered, so a tool contributed by an app that loads after this one is
    still covered. Idempotent: a second mount in one process (a test builds its
    own server) must not stack wrappers.
    """
    if getattr(server, LISTING_WRAPPED_ATTR, False):
        return
    listing = server.list_tools

    async def list_tools_with_scopes() -> list[Any]:
        listed = await listing()
        return [
            tool.model_copy(
                update={
                    "description": described_with_scope(
                        str(tool.description or ""), _listed_scope(server, str(tool.name))
                    )
                }
            )
            for tool in listed
        ]

    server.list_tools = list_tools_with_scopes  # type: ignore[method-assign]
    setattr(server, LISTING_WRAPPED_ATTR, True)


#: Marks a server whose listing already carries scope lines, so mounting twice in
#: one process cannot stack two wrappers and print the line twice.
LISTING_WRAPPED_ATTR = "djb_scope_lines_installed"

#: Marks a server whose listing is already narrowed to the request's surface.
SURFACE_LISTING_ATTR = "djb_surface_listing_installed"


def install_surface_listing(server: MCPServer[Any]) -> None:
    """Narrow the tool listing to what the request's surface exposes, once, at the mount.

    Wraps the server's own listing, as `install_scope_lines` does, so a tool an
    app contributes tomorrow is narrowed without this module knowing it exists.
    Idempotent.
    """
    if getattr(server, SURFACE_LISTING_ATTR, False):
        return
    listing = server.list_tools

    async def list_tools_on_this_surface() -> list[Any]:
        return listed_here(server, await listing())

    server.list_tools = list_tools_on_this_surface  # type: ignore[method-assign]
    setattr(server, SURFACE_LISTING_ATTR, True)


# --- The ceiling answers BEFORE the arguments are validated -----------------
#
# THE DEFECT. The transport parses and validates a tool's arguments before it
# runs the body, and the ceiling was checked inside the body (`tool_call`). So a
# token holding nothing at all on a family could send that family's tools a
# deliberately malformed call and be answered about the arguments — a pydantic
# error naming the tool's required parameters. That is the schema of a
# capability the credential was never allowed to reach, read out through a wall
# that was standing one step too far back. Well-formed calls refused correctly
# throughout; it was only ever the malformed probe that got past.
#
# THE HTTP DOOR NEVER HAD IT, which is the reason this is a finding rather than
# a preference: `config/api.py::_guard_the_ceiling` sits between authentication
# and the view, so a scoped-out request is refused before ninja parses a body.
# Rule 17's spirit is that the two doors agree, and they did not.
#
# THE SEAM, AND WHAT WAS REJECTED. `MCPServer.call_tool(name, arguments,
# context)` is the server's own PUBLIC dispatch method and the last place that
# holds the name, the principal and the arguments *unparsed* — the tool manager
# it delegates to validates on the next line. Wrapping it is the same move
# `install_scope_lines` already makes on the public `list_tools`, from the same
# `register()`, and it touches no private attribute of the library.
#   * REJECTED — wrapping `MCPServer._handle_call_tool` or the `ToolManager`:
#     both are private, and neither buys anything the public method does not.
#   * REJECTED — the SDK's own low-level `middleware=` hook. It is the most
#     official seam there is and it is out of reach: it is a constructor
#     argument, so taking it would mean editing `config/mcp.py` to register
#     something — the one thing an app never does (house rule: registration is
#     by discovery). The wrapper installs itself from the app.
#   * REJECTED — validating after the ceiling inside the existing frame. There
#     is no such frame: by the time `tool_call` runs, validation has already
#     happened and already answered.
#   * REJECTED — making the validation error quieter for everybody. That pays
#     for the wall by taking the schema away from callers entitled to it; the
#     leak is closed at the wall, and an in-ceiling caller is told exactly what
#     it always was.
#
# THE ONE COUPLING, AND ITS TRIPWIRE. `Tool.run` dresses anything a body raises
# as "Error executing tool <name>: <message>", so every refusal an agent has
# ever read from this door wears that coat. Refusing one layer out means putting
# it on by hand, restated below as `TOOL_ERROR_SENTENCE` — a copy of somebody
# else's prose, which is exactly the shape `config/api.py` sanctions with a
# tripwire rather than trusts. The tripwire is the one test in
# `apps/core/tests/test_mcp_wall.py` named for the transport's dressing: it
# measures the sentence off a real in-body refusal over the wire and goes red
# the day the transport rewords it. This wrap joins the ninja/mcp-internals
# census being taken in the parallel quality rung.

#: How the MCP transport dresses anything a tool body raises
#: (`mcp.server.mcpserver.tools.base.Tool.run`). Restated here because a refusal
#: raised in front of the body has to wear the same coat as the sixty-nine
#: raised inside one — an agent that had to parse two shapes for one class of
#: answer is worse off than one told a small untruth about "executing". Measured
#: by a tripwire test, never assumed.
TOOL_ERROR_SENTENCE = "Error executing tool {name}: {message}"

#: Marks a server whose dispatch already checks the ceiling, so a second mount
#: in one process cannot stack two wrappers.
CEILING_WRAPPED_ATTR = "djb_ceiling_gate_installed"


# --- An argument a tool does not have is a refusal, not a shrug -------------
#
# THE PAIR A FIELD TEST FOUND, at a door it did not reach.
#
#   (a) SILENTLY DROPPED. `create_endpoint(url=…, event_types=[…])` behaved
#       exactly as the same call with no `event_types` at all — measured
#       byte-identical over the wire — because pydantic's default is to ignore
#       what it does not recognise. The misspelled name vanished on the way in
#       and the tool answered success: an endpoint with a signing secret,
#       subscribed to nothing. It is the 201-for-nothing trap strict request
#       bodies had just closed at the HTTP door, still open here, and
#       it is the worst failure shape a platform whose callers are agents can
#       have — the caller's only evidence is a success.
#   (b) OUTSIDE THE GRAMMAR. An argument failure came back as `2 validation
#       errors for create_organization_toolArguments … Field required
#       [type=missing, input_value={…}]`: a library's rendering of its own error
#       object, with no `code` to branch on, no `errors` map, no remedies, and
#       the caller's own payload echoed back inside it. Every *in-body* refusal
#       at this same door was correctly enveloped by `tool_call`, so one door
#       answered one class of failure in two grammars — and the second one fired
#       only on the call the caller had already got wrong.
#
# ONE SEAM, SEVENTY TOOLS. The transport derives a pydantic model per tool from
# the function's signature (`mcp.server.mcpserver.utilities.func_metadata`), and
# a tool's published `inputSchema` is that model's JSON schema. Both come off
# the one object, so the strictness is declared ONCE, on the model
# (`_forbid_unknown_arguments`), and the published schema then *reports*
# `additionalProperties: false` rather than claiming it separately. No tool is
# edited, and a tool an app registers tomorrow is covered without this module
# knowing it exists.
#   * REJECTED — `extra="forbid"` per tool, or a shared base class for tool
#     arguments: seventy edits and a house rule to keep them in step, for
#     something one seam already knows.
#   * REJECTED — injecting `additionalProperties: false` into the published
#     schema while the model stays lax. That publishes a promise the door does
#     not keep, which is the same class of untruth as the silent drop.
#   * REJECTED — refusing inside the tool body. The body runs AFTER the
#     transport has parsed the arguments, which is the exact position the ceiling
#     check moved out of.
#
# AND THE ORDER IS THE INVARIANT. The ceiling answers first, the arguments
# second, which is why both walls stand in ONE wrapper (`install_ceiling_gate`)
# rather than in two: two wrappers can be installed in either order and nothing
# in the code would ever say which was meant. An out-of-ceiling call still
# learns nothing about the schema of a capability it may not reach; an
# in-ceiling call is told exactly what is wrong with its arguments, by name.

register_refusal(
    code="invalid_arguments",
    boundary="door",
    remedy=(
        "The call did not match the tool's argument schema, so the machine door "
        "refused it before the tool body ran. `errors` is keyed on the argument "
        "names the caller sent, with the unknown ones saying so in as many words. "
        "Tool arguments are STRICT here (apps/core/mcp.py::_forbid_unknown_arguments "
        'puts extra="forbid" on the model the transport derives from each tool\'s '
        "signature) and every published inputSchema carries "
        "`additionalProperties: false`, so a misspelled argument is a refusal rather "
        "than a silent drop — which is what stops a typo'd name from returning a "
        "healthy result for a call that did nothing (the same shape at the "
        "tool door)."
    ),
    fact=(
        "The call does not match the shape this tool accepts. No tool body ran, "
        "nothing was read and nothing was written. The answer names each argument and "
        "what is wrong with it, in the names you sent, including any name that is not "
        "one of this tool's arguments: unknown arguments are refused rather than "
        "ignored, so a misspelling can never look like a success."
    ),
    remedies=(
        Remedy("Read the failing arguments and resend", "field:errors"),
        Remedy("Read the arguments this tool accepts", "introspect:tools"),
    ),
    # NO `status=`, and that is the declaration (ADR core-23). This refusal is
    # only ever made at the MACHINE door, and the machine door has no status
    # codes at all — a tool answers a refusal as one line of text through
    # `refusal_message`. A number here would be a fact invented to fill a column,
    # published into `x-refusal-codes` for an HTTP operation that can never make
    # this refusal. The registry's `status` is optional exactly for this.
)


class InvalidArguments(Invalid):
    """The call did not match the tool's argument schema.

    A NARROWER `Invalid`, exactly as the HTTP door's `invalid_body` is and for
    the same reason: a client that already branches on `invalid` keeps working,
    and the narrower code exists because the fix is genuinely different —
    nothing about the *data* was judged, the call did not match the shape this
    tool accepts, and no tool body ran at all.

    It is registered here rather than beside `invalid_body` because the two are
    not one refusal wearing two names: `invalid_body` is about a JSON request
    body and its remedy names ninja and the OpenAPI document, and this door has
    neither. It could not be imported even if they were the same — `config` sits
    above `apps` and the arrow points one way (house rule 7).

    It has no raise site outside this module: `_argument_refusal` composes it
    out of what the transport's own argument model already worked out.
    """

    code = "invalid_arguments"
    default_detail = "The call does not match the shape this tool accepts."


#: What the validator means, said to the caller rather than to whoever wrote the
#: validator. Only the types whose own message is framework vocabulary are
#: translated; anything else keeps pydantic's sentence, which is usually the
#: better one ("Input should be a valid UUID").
#:
#: The HTTP door keeps its own table (`config/api.py::FIELD_SENTENCES`) and this
#: is deliberately not a copy of it: the two doors have different nouns — a
#: *field* of a request body there, an *argument* of a call here — and a door
#: that called a tool argument a field would be describing something its caller
#: cannot see. What IS shared is the grammar, and it is shared by construction:
#: `wire_refusal` composes and `refusal_message` renders, for this refusal
#: exactly as for every in-body refusal `tool_call` translates.
ARGUMENT_SENTENCES: dict[str, str] = {
    # THE ONE THIS RUNG EXISTS FOR. pydantic says "Extra inputs are not
    # permitted", which describes the RULE. The caller needs to be told about
    # their own call: this is not one of the tool's arguments, so check it.
    "extra_forbidden": "This tool has no argument by that name. Check the spelling.",
    "missing": "This argument is required.",
    "json_invalid": "This argument is not valid JSON.",
}

#: pydantic prefixes a custom validator's message with its own error class.
#: Stripped so the sentence a validator wrote reaches the wire on its own.
_PYDANTIC_PREFIXES = ("Value error, ", "Assertion failed, ")

#: Marks a server whose listing already sweeps the argument models strict, so a
#: second mount in one process cannot stack two wrappers.
STRICT_WRAPPED_ATTR = "djb_strict_arguments_installed"


def _forbid_unknown_arguments(tool: Any) -> None:
    """Make one tool refuse arguments it does not have, and republish its schema.

    **The seam.** `tool.fn_metadata.arg_model` is the pydantic model the
    transport derived from the tool's signature and `tool.parameters` is that
    model's JSON schema — the `inputSchema` a client reads. One object, so the
    strictness is declared once and the schema reports it.

    A strict SUBCLASS rather than a mutated configuration: the model the SDK
    built is left as it was found, pydantic merges the parent's configuration
    into the child's (`arbitrary_types_allowed` survives), and the regenerated
    schema is identical to the old one but for the `additionalProperties: false`
    the forbidding puts there — measured, not assumed, by the listing test.
    Idempotent, because the sweeps that call it run per request.
    """
    metadata = tool.fn_metadata
    model = metadata.arg_model
    if model.model_config.get("extra") == "forbid":
        return
    # Annotated because the three-argument `type()` is typed as plain `type`,
    # and what comes back is the one thing this function is about: a model.
    strict: type[BaseModel] = type(
        model.__name__, (model,), {"model_config": ConfigDict(extra="forbid")}
    )
    metadata.arg_model = strict
    tool.parameters = strict.model_json_schema(by_alias=True)


def forbid_unknown_arguments(server: MCPServer[Any]) -> None:
    """Apply the seam to every tool this server holds. Idempotent, and cheap.

    Lazily, from the listing rather than once at `register()`, for the same
    reason `install_scope_lines` wraps the listing: an app discovered after this
    one contributes its tools later, and a sweep that ran at registration time
    would have covered only whatever happened to exist by then.
    """
    for tool in server._tool_manager.list_tools():
        _forbid_unknown_arguments(tool)


def install_strict_arguments(server: MCPServer[Any]) -> None:
    """Publish `additionalProperties: false` on every tool this server lists.

    Wraps the listing rather than editing any tool. The dispatch side does the
    same thing for the one tool it is about to run (`install_ceiling_gate`), so
    a tool that is called without ever being listed is strict too — the listing
    is where the *published* half is kept honest, not where the strictness comes
    from. Idempotent.
    """
    if getattr(server, STRICT_WRAPPED_ATTR, False):
        return
    listing = server.list_tools

    async def list_tools_with_strict_schemas() -> list[Any]:
        forbid_unknown_arguments(server)
        return await listing()

    server.list_tools = list_tools_with_strict_schemas  # type: ignore[method-assign]
    setattr(server, STRICT_WRAPPED_ATTR, True)


#: Marks a server whose listing already publishes its RESULT schemas the way the
#: results are rendered, so a second mount in one process cannot stack two
#: wrappers. Its own mark rather than `STRICT_WRAPPED_ATTR`'s: two seams, two
#: marks, so removing one never silently takes the other with it.
SERIALIZED_OUTPUT_ATTR = "djb_serialized_output_schemas_installed"

#: One rendered schema per output MODEL. `model_json_schema` builds a schema
#: from scratch every time it is asked and this sweep runs on every listing, so
#: the rendering is done once per model and handed out by identity — which is
#: also the sweep's second-time no-op test, the same shape the argument sweep
#: uses when it reads `extra == "forbid"` off the model it already made strict.
#:
#: No `reset_` seam beside it, unlike `reset_scope_derivation`: that one caches a
#: whole-registry answer a planted route falsifies, and this one is keyed on the
#: output type itself (a model class or the SDK's `Annotated` dict), so a planted
#: tool with a new type gets a new entry and one with an existing type gets the
#: right answer. The day something can falsify an entry, the seam arrives with it.
_serialized_output_schemas: dict[Any, dict[str, Any]] = {}


def _publish_serialized_output_schema(tool: Any) -> None:
    """Publish one tool's result schema the way the result is really rendered.

    **A pydantic model has TWO JSON schemas** — a validation
    one, describing what may be parsed INTO it, and a serialization one,
    describing what comes OUT — and for a `Decimal` field they disagree: the
    first accepts a JSON number or a numeric string, the second is the string
    alone. django-ninja renders `openapi.json` in serialization mode, because a
    response schema describes a response; the MCP SDK renders `outputSchema` in validation mode
    (`self._output_adapter(...).json_schema(schema_generator=StrictJsonSchema)` with no
    `mode=`, `func_metadata.py`), because that call is the one it also uses for arguments. So the
    same `MeasuredOut.value` published as `{"type": "string", "pattern": ...}` at
    one door and `anyOf: [number, string]` at the other, while the shared
    contract prose promised every number as a JSON string — ADR core-7's whole
    point, since a float is where a figure quietly stops adding up. The wire
    agreed all along (both doors send the string): what disagreed was the
    document a client generates from, which is the half nobody meets until a
    generated client has already been written against the wrong one.

    **The seam.** `tool.fn_metadata.output_model` is the model the transport
    derived from the tool's return annotation and `tool.fn_metadata.output_schema`
    is its rendering — the `outputSchema` a client reads. Re-rendering the same
    model with the SDK's own generator and `mode="serialization"` changes the
    published document and nothing else: at call time the SDK reads
    `output_schema` only to ask whether it is `None`, and builds the body through a `TypeAdapter`
    over `output_model` dumped with `mode="json", by_alias=True` — so a result that went out
    before this ran goes out byte for byte the same after it.

    `Tool.output_schema` is a `cached_property` over the same attribute, so the
    cached copy is dropped in the same breath the attribute is rebound; a listing
    that had already run would otherwise go on publishing the schema it cached.

    A model that cannot be rendered in serialization mode raises here rather than
    being quietly left as it was found. That is deliberate and it is the same bet
    the HTTP door already takes: ninja renders the same models the same way, so
    such a model brings `openapi.json` down too, and a door that published one
    schema in the mode nobody asked for would be the defect this function exists
    to close, wearing a green gate.
    """
    metadata = tool.fn_metadata
    model = metadata.output_model
    if model is None or metadata.output_schema is None:
        return
    published = _serialized_output_schemas.get(model)
    if published is None:
        published = TypeAdapter(model).json_schema(
            schema_generator=StrictJsonSchema, mode="serialization"
        )
        _serialized_output_schemas[model] = published
    if metadata.output_schema is published:
        return
    metadata.output_schema = published
    # `functools.cached_property`'s own documented invalidation: the cache is an
    # entry in the instance dictionary, and deleting it is how the next read is
    # made to recompute.
    tool.__dict__.pop("output_schema", None)


def serialize_output_schemas(server: MCPServer[Any]) -> None:
    """Apply the seam to every tool this server holds. Idempotent, and cheap.

    Lazily, from the listing rather than once at `register()`, for the reason
    `forbid_unknown_arguments` is: an app discovered after this one contributes
    its tools later, and a sweep that ran at registration time would have covered
    only whatever happened to exist by then.
    """
    for tool in server._tool_manager.list_tools():
        _publish_serialized_output_schema(tool)


def install_serialized_output_schemas(server: MCPServer[Any]) -> None:
    """Publish every tool's result schema in serialization mode.

    Wraps the listing rather than editing any tool, the way the argument
    strictness does — and it is the listing rather than the dispatch because the
    published document is the only thing that was ever wrong: the values on the
    wire were right at both doors before this existed. Idempotent.
    """
    if getattr(server, SERIALIZED_OUTPUT_ATTR, False):
        return
    listing = server.list_tools

    async def list_tools_with_serialized_output() -> list[Any]:
        serialize_output_schemas(server)
        return await listing()

    server.list_tools = list_tools_with_serialized_output  # type: ignore[method-assign]
    setattr(server, SERIALIZED_OUTPUT_ATTR, True)


def _owes_a_schema(declared: object, fn: Callable[..., Any]) -> tuple[bool, object]:
    """Whether a return annotation names a class the library should schema, and its resolution."""
    # Invariant: the library answers a bare `dict` or `datetime` with no schema by design.
    if declared is inspect.Signature.empty:
        return False, declared
    try:
        resolved: object = typing.get_type_hints(fn).get("return", declared)
    except (NameError, TypeError, AttributeError):
        return False, declared
    if (
        not isinstance(resolved, type)
        or _returns_content(resolved)
        or _is_input_required_type(resolved)
        or issubclass(resolved, CallToolResult)
    ):
        return False, resolved
    return resolved.__module__.partition(".")[0] not in sys.stdlib_module_names, resolved


def refuse_unstructured_results(server: MCPServer[Any]) -> None:
    """Raise naming every tool whose return class the library built no output schema for."""
    # Invariant: the SDK answers such a tool with text alone (`func_metadata.py`'s fallback).
    silent = []
    for tool in server._tool_manager.list_tools():
        if tool.fn_metadata.output_schema is not None:
            continue
        declared = inspect.signature(tool.fn).return_annotation
        owed, resolved = _owes_a_schema(declared, tool.fn)
        if owed:
            silent.append(f"MCP tool `{tool.name}` returns `{declared}` ({resolved!r})")
    if silent:
        raise ImproperlyConfigured(
            "; ".join(silent) + " — the MCP library built no output schema for that type, so "
            "every answer would carry no structuredContent"
        )


def _accepted_arguments(tool: Any) -> tuple[str, ...]:
    """Every argument this tool takes, spelled the way a caller has to send it."""
    fields = tool.fn_metadata.arg_model.model_fields
    return tuple(sorted(info.alias or name for name, info in fields.items()))


def _argument_message(entry: Mapping[str, Any]) -> str:
    """One argument error, said in plain language."""
    sentence = ARGUMENT_SENTENCES.get(str(entry.get("type", "")))
    if sentence is not None:
        return sentence
    message = str(entry.get("msg") or "").strip()
    for prefix in _PYDANTIC_PREFIXES:
        if message.startswith(prefix):
            message = message[len(prefix) :]
    return message or "This value is not valid."


def _argument_sentence(tool: Any, unknown: Sequence[str], errors: Mapping[str, list[str]]) -> str:
    """The one human sentence at the top of the refusal.

    It names the unknown arguments explicitly, because that is the failure a
    caller is least able to see for itself: a missing argument is visible in its
    own call, while a name that is *almost* right looks correct until somebody
    reads the schema beside it. And it names what the tool does take, because
    this door has nowhere to send anyone away to read — the HTTP door answers
    that with `docs:openapi`, and one line of text is the whole medium here.
    """
    accepted = ", ".join(_accepted_arguments(tool))
    takes = f" This tool takes: {accepted}." if accepted else " This tool takes no arguments."
    named = ", ".join(f"`{name}`" for name in dict.fromkeys(unknown))
    if unknown and len(errors) == len(set(unknown)):
        # No article on the singular: "has no argument called `x`" reads, and
        # "has no an argument called `x`" does not. The HTTP door's twin of this
        # sentence (`config/api.py::_validation_sentence`) carried the article
        # and now drops it too — so both doors say "has no <noun>
        # called". Mirroring the REGISTER is what these two owe each other, not
        # the wording; the twin was copied from here rather than this from the
        # twin, which is why this comment could go on being right while the
        # neighbour was wrong.
        subject = "argument" if len(set(unknown)) == 1 else "arguments"
        return (
            f"This tool has no {subject} called {named}, so the call was refused rather "
            f"than carried out without it. Nothing was changed.{takes}"
        )
    if unknown:
        return (
            f"The call does not match the shape this tool accepts, and it names {named}, "
            f"which this tool does not have. See each argument below.{takes}"
        )
    return (
        "The call does not match the shape this tool accepts. See each argument below "
        f"and what is wrong with it.{takes}"
    )


def _argument_refusal(tool: Any, arguments: Mapping[str, Any]) -> InvalidArguments | None:
    """This call's argument refusal, or `None` when the arguments hold.

    Validated HERE, in front of the transport's own pass, because a refusal
    composed after the transport has answered is not a refusal — the answer has
    already gone. The cost is one extra validation pass, which is the cost the
    SDK itself pays for any tool taking a resolver parameter (`Tool.run`'s
    `pre_validated`); nothing in this tree has a stateful validator for it to
    disturb.

    Anything that is not a validation failure falls through untouched: the
    transport is about to make the identical parse a line later and will answer
    it exactly as it always has, and a wrapper that turned its own bug into a
    refusal would be inventing one.
    """
    _forbid_unknown_arguments(tool)
    metadata = tool.fn_metadata
    try:
        metadata.arg_model.model_validate(metadata.pre_parse_json(dict(arguments)))
    except ValidationError as invalid:
        errors: dict[str, list[str]] = {}
        unknown: list[str] = []
        for entry in invalid.errors():
            name = ".".join(str(part) for part in entry.get("loc") or ()) or NON_FIELD_KEY
            errors.setdefault(name, []).append(_argument_message(entry))
            if str(entry.get("type", "")) == "extra_forbidden":
                unknown.append(name)
        return InvalidArguments(errors, detail=_argument_sentence(tool, unknown, errors))
    return None


def _malformed_call(
    server: MCPServer[Any], name: str, arguments: Mapping[str, Any]
) -> InvalidArguments | None:
    """The argument refusal for this dispatch, or `None`.

    A name this server does not hold answers `None` rather than complaining
    about arguments: the dispatch below is about to refuse it as an unknown
    tool, and that is the true answer.
    """
    tool = server._tool_manager.get_tool(name)
    if tool is None:
        return None
    return _argument_refusal(tool, arguments)


def _refused_before_arguments(
    server: MCPServer[Any], context: Any, name: str
) -> DomainError | None:
    """The surface's answer, then the ceiling's, for this dispatch, reading no arguments.

    The surface first, in the HTTP door's order: whether this host offers the
    tool at all is a fact about the address and is answered before anything
    about the credential.

    `None` means "not mine to refuse", and it covers three honest cases: a call
    with no context (an in-process caller, which the body's own frame still
    guards), a call carrying no principal (impossible through the mount, which
    401s first — and the body raises it the way it always did), and a name this
    server does not hold, which the dispatch below is about to refuse as an
    unknown tool. Guessing at any of the three here would replace a true answer
    with a ceiling's.
    """
    if context is None:
        return None
    try:
        acting = principal(context)
    except NotAuthenticated:
        return None
    tool = server._tool_manager.get_tool(name)
    if tool is None:
        return None
    off_surface = surface_refusal(tool, surface_named(acting.surface))
    if off_surface is not None:
        return off_surface
    if ceiling_of(acting) is None:
        return None
    return ceiling_refusal(tool, acting)


def install_ceiling_gate(server: MCPServer[Any]) -> None:
    """Put the surface, the token's ceiling, then the argument grammar, in front of dispatch.

    See the note above for why the wall moved and what was rejected.
    Installed from `register()` beside `install_scope_lines`, for the same
    reason: it wraps the server rather than any tool, so it covers whatever the
    apps discovered after this one contribute without this module knowing they
    exist. Idempotent.

    **Two walls, one wrapper, and the order between them is the point.**
    The ceiling is asked first and reads no arguments at all, so a credential
    that may not reach this tool is answered about itself and learns nothing
    about the tool's schema — which is the whole point of the ceiling check. Only
    then are the
    arguments judged, for a caller entitled to the answer, in the same refusal
    grammar every in-body refusal wears. They are not two installers because two
    installers can be called in either order and nothing in the code would say
    which was meant; here the order is four lines apart and legible.
    """
    if getattr(server, CEILING_WRAPPED_ATTR, False):
        return
    dispatch = server.call_tool

    async def call_tool_within_ceiling(
        name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        refusal = _refused_before_arguments(server, context, name)
        if refusal is not None:
            raise ToolError(
                TOOL_ERROR_SENTENCE.format(
                    name=name, message=refusal_message(wire_refusal(refusal))
                )
            )
        malformed = _malformed_call(server, name, arguments)
        if malformed is not None:
            raise ToolError(
                TOOL_ERROR_SENTENCE.format(
                    name=name, message=refusal_message(wire_refusal(malformed))
                )
            )
        return await dispatch(name, arguments, context)

    server.call_tool = call_tool_within_ceiling  # type: ignore[method-assign]
    setattr(server, CEILING_WRAPPED_ATTR, True)


def register(server: MCPServer[Any]) -> None:
    """Contribute this app's tools. `config.mcp` discovers and calls this."""

    @server.tool(
        name="ping",
        description="Confirm the machine door is open and report the acting tenant.",
    )
    @reaches_no_capability(
        "it reads back the principal the caller already holds — the tenant and "
        "organization their own token resolved to — and touches nothing else. A "
        "ceiling that hid this would stop an agent confirming its credential works "
        "at all, which is the one question every narrow token needs to ask first."
    )
    def ping(ctx: Context[Any]) -> PingOut:
        acting = principal(ctx)
        return PingOut(
            ok=True,
            tenant=acting.tenant.slug if acting.tenant is not None else None,
            org=acting.org.slug if acting.org is not None else None,
        )

    # The tenancy and hierarchy tools — the twins of every route in
    # `apps/core/api/routes.py` bar one. Registered from here so discovery
    # still finds a single `register`.
    register_tenancy_tools(server)

    # And the scope line on every listed tool (ADR ident-7). Installed from here
    # because this is the app that owns the seam, and it wraps the LISTING rather
    # than editing any tool — so it covers whatever the apps discovered after
    # this one contribute, without this module knowing they exist.
    install_scope_lines(server)

    # And the listing narrowed to the host's surface, as the OpenAPI document
    # is: a customer host lists what it offers and nothing of the staff doors.
    install_surface_listing(server)

    # And the ceiling in front of the transport's argument validation, for the
    # same reason and by the same means: one wrap of the server's own dispatch,
    # covering every tool any app contributes. That same
    # wrapper judges the arguments too, immediately after — the order between
    # the two is what keeps a schema away from a credential that may not reach
    # the capability it describes.
    install_ceiling_gate(server)

    # And the strictness on every published argument schema: unknown
    # arguments are refused rather than dropped, and the listing says so with
    # `additionalProperties: false`. One seam over all of them, never a
    # per-tool declaration.
    install_strict_arguments(server)

    # And the result schemas rendered the way the results are: the HTTP
    # door publishes what comes OUT of a model and this one used to publish what
    # may be parsed INTO one, so a `Decimal` was a string at one door and
    # "number or string" at the other. Same shape as the line above — one wrap of
    # the listing, covering whatever any app contributes.
    install_serialized_output_schemas(server)


def register_tenancy_tools(server: MCPServer[Any]) -> None:
    """The machine door onto the tenancy and hierarchy capabilities.

    Every one of these is the twin of a route in `apps/core/api/routes.py`, over
    the same selectors, the same services and the same schemas — and every
    `description=` is `contract_of(<that route>)`, the contract half of the very
    function the OpenAPI document describes, so the two doors cannot come to
    describe one capability differently (house rule 41).

    **One capability is deliberately absent**: accepting an invitation. The
    token mints a membership for whoever holds it, and the person is named by
    the session rather than by the payload — a bearer token accepting on
    somebody else's behalf is an impersonation shape, not a parity gap. ADR
    core-16, recorded as rule 17's exemption in `quality/rules.yaml` with that
    reason.

    It is a second function rather than more lines in `register()` because
    `register()` is this module's own tool — the one that proves the mount —
    and these are the app's; `register()` calls this at the end, so discovery
    still finds exactly one entry point.
    """

    # --- Organizations --------------------------------------------------------

    @server.tool(name="list_organizations", description=contract_of(list_organizations_route))
    def list_organizations_tool(
        ctx: Context[Any],
        name: str | None = None,
        depth: int | None = None,
        q: str | None = None,
        ordering: str = "path",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
        can: str | None = None,
    ) -> OrganizationPage:
        with tool_call(ctx) as acting:
            actor = acting.actor()
            rows: models.QuerySet[Organization] = OrganizationFilter(name=name, depth=depth).filter(
                list_organizations(tenant=acting.tenant, org=acting_org(acting), actor=actor)
            )
            rows = searched(rows, q, fields=ORGANIZATION_SEARCH_FIELDS)
            if can is not None:
                rows = list_organizations_where(rows, actor=actor, can=can)
            rows = ordered_by(rows, ordering, allowed=ORGANIZATION_ORDERING, default="path")
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return OrganizationPage(
                items=[OrganizationOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="get_organization", description=contract_of(get_organization_route))
    def get_organization_tool(ctx: Context[Any], organization_id: UUID) -> OrganizationOut:
        with tool_call(ctx) as acting:
            return OrganizationOut.from_orm(
                get_organization(
                    tenant=acting_tenant(acting),
                    org=acting_org(acting),
                    organization_id=organization_id,
                    actor=acting.actor(),
                )
            )

    @server.tool(name="create_organization", description=contract_of(create_organization_route))
    def create_organization_tool(
        ctx: Context[Any], parent_id: UUID, name: str, slug: str
    ) -> OrganizationOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            # ONE actor for the whole tool body, not one per call: the read and
            # the write are two questions in one request, and PR0's memo is on
            # the instance — two `acting.actor()` calls would pay the three
            # statements twice.
            actor = acting.actor()
            parent = get_organization(
                tenant=tenant, org=acting_org(acting), organization_id=parent_id, actor=actor
            )
            return OrganizationOut.from_orm(
                create_organization(
                    tenant=tenant,
                    parent=parent,
                    name=name,
                    slug=slug,
                    actor=actor,
                )
            )

    @server.tool(name="update_organization", description=contract_of(rename_organization_route))
    def update_organization_tool(
        ctx: Context[Any], organization_id: UUID, name: str
    ) -> OrganizationOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            organization = get_organization(
                tenant=tenant,
                org=acting_org(acting),
                organization_id=organization_id,
                actor=actor,
            )
            return OrganizationOut.from_orm(
                rename_organization(
                    tenant=tenant, organization=organization, name=name, actor=actor
                )
            )

    @server.tool(name="move_organization", description=contract_of(move_organization_route))
    def move_organization_tool(
        ctx: Context[Any], organization_id: UUID, new_parent_id: UUID
    ) -> OrganizationOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            hat = acting_org(acting)
            actor = acting.actor()
            organization = get_organization(
                tenant=tenant, org=hat, organization_id=organization_id, actor=actor
            )
            new_parent = get_organization(
                tenant=tenant, org=hat, organization_id=new_parent_id, actor=actor
            )
            return OrganizationOut.from_orm(
                move_organization(
                    tenant=tenant,
                    organization=organization,
                    new_parent=new_parent,
                    actor=actor,
                    started_by=acting.user,
                )
            )

    # --- Memberships ----------------------------------------------------------

    @server.tool(name="list_memberships", description=contract_of(list_memberships_route))
    def list_memberships_tool(
        ctx: Context[Any],
        role: str | None = None,
        organization_id: UUID | None = None,
        ordering: str = "role",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> MembershipPage:
        with tool_call(ctx) as acting:
            rows: models.QuerySet[Membership] = MembershipFilter(
                role=role, organization_id=organization_id
            ).filter(
                list_memberships(tenant=acting.tenant, org=acting_org(acting), actor=acting.actor())
            )
            rows = ordered_by(rows, ordering, allowed=MEMBERSHIP_ORDERING, default="role")
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return MembershipPage(
                items=[MembershipOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_membership", description=contract_of(add_membership_route))
    def create_membership_tool(
        ctx: Context[Any],
        user_id: UUID,
        role: str,
        organization_id: UUID | None = None,
        is_default: bool = False,
    ) -> MembershipOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            organization = (
                get_organization(
                    tenant=tenant,
                    org=acting_org(acting),
                    organization_id=organization_id,
                    actor=actor,
                )
                if organization_id is not None
                else None
            )
            user = _user_by_id(user_id)
            return MembershipOut.from_orm(
                add_membership(
                    user=user,
                    tenant=tenant,
                    organization=organization,
                    is_default=is_default,
                    role=role,
                    actor=actor,
                )
            )

    @server.tool(name="update_membership", description=contract_of(set_role_route))
    def update_membership_tool(ctx: Context[Any], membership_id: UUID, role: str) -> MembershipOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            membership = get_membership(
                tenant=tenant, org=acting_org(acting), membership_id=membership_id, actor=actor
            )
            return MembershipOut.from_orm(
                set_role(tenant=tenant, membership=membership, role=role, actor=actor)
            )

    @server.tool(name="delete_membership", description=contract_of(revoke_membership_route))
    def delete_membership_tool(ctx: Context[Any], membership_id: UUID) -> dict[str, bool]:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            membership = get_membership(
                tenant=tenant, org=acting_org(acting), membership_id=membership_id, actor=actor
            )
            revoke_membership(tenant=tenant, membership=membership, actor=actor)
            # The HTTP twin answers 204 with no body; a tool has no status code
            # to carry that, so it says the same thing in the one word it can.
            return {"revoked": True}

    # --- Roles, grants and the vocabulary --------------------------------------
    #
    # Eleven twins of the eleven routes, over the same selectors, the same
    # services and the same schemas. Every `description=` is `contract_of(...)`
    # of its own route, which is what makes `scope_for_tool` derive
    # `roles:read`/`roles:write` from the twin rather than from a second table.

    @server.tool(name="list_roles", description=contract_of(list_roles_route))
    def list_roles_tool(
        ctx: Context[Any],
        kind: str | None = None,
        q: str | None = None,
        ordering: str = "key",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> RolePage:
        with tool_call(ctx) as acting:
            # The HTTP route's own narrowing and sorting functions, imported
            # rather than reimplemented: a list assembled twice is two answers
            # waiting to differ, which is exactly what rule 46 exists to catch.
            filters = RoleFilter(kind=kind, q=q)
            views = [
                view
                for view in list_roles(tenant=acting_tenant(acting), actor=acting.actor())
                if _role_matches(view, filters)
            ]
            rows = _sorted_roles(views, ordering)
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
                ordering=("key",),
            )
            return RolePage(
                items=list(page.items),
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="get_role", description=contract_of(get_role_route))
    def get_role_tool(ctx: Context[Any], key: str) -> RoleOut:
        with tool_call(ctx) as acting:
            return RoleOut.of(get_role(tenant=acting_tenant(acting), key=key, actor=acting.actor()))

    @server.tool(name="create_role", description=contract_of(create_role_route))
    def create_role_tool(
        ctx: Context[Any],
        key: str,
        name: str,
        description: str = "",
        permissions: list[str] | None = None,
    ) -> RoleOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            create_role(
                tenant=tenant,
                actor=actor,
                key=key,
                name=name,
                description=description,
                permissions=permissions or [],
            )
            return RoleOut.of(get_role(tenant=tenant, key=key, actor=actor))

    @server.tool(name="update_role", description=contract_of(update_role_route))
    def update_role_tool(
        ctx: Context[Any],
        key: str,
        name: str | None = None,
        description: str | None = None,
    ) -> RoleOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            row = Role.objects.for_tenant(tenant).filter(key=key).first()
            if row is None:
                raise NotFound()
            update_role(tenant=tenant, actor=actor, role=row, name=name, description=description)
            return RoleOut.of(get_role(tenant=tenant, key=key, actor=actor))

    @server.tool(
        name="update_role_permissions", description=contract_of(set_role_permissions_route)
    )
    def set_role_permissions_tool(
        ctx: Context[Any], key: str, permissions: list[str] | None = None
    ) -> RoleOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            set_role_collection(
                tenant=tenant, actor=actor, role_key=key, permissions=permissions or []
            )
            return RoleOut.of(get_role(tenant=tenant, key=key, actor=actor))

    @server.tool(name="delete_role", description=contract_of(delete_role_route))
    def delete_role_tool(ctx: Context[Any], key: str) -> dict[str, bool]:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            row = Role.objects.for_tenant(tenant).filter(key=key).first()
            if row is None:
                raise NotFound()
            delete_role(tenant=tenant, actor=actor, role=row)
            # The HTTP twin answers 204 with no body; a tool has no status code
            # to carry that, so it says the same thing in the one word it can.
            return {"deleted": True}

    @server.tool(name="list_grants", description=contract_of(list_grants_route))
    def list_grants_tool(
        ctx: Context[Any],
        membership_id: UUID,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> GrantPage:
        with tool_call(ctx) as acting:
            rows = list_grants(
                tenant=acting_tenant(acting),
                org=acting_org(acting),
                membership_id=membership_id,
                actor=acting.actor(),
            )
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return GrantPage(
                items=[
                    GrantOut.of(row, sentence=refusal_sentence(str(row.permission)))
                    for row in page.items
                ],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="update_grant", description=contract_of(set_grant_route))
    def set_grant_tool(
        ctx: Context[Any], membership_id: UUID, permission: str, effect: str
    ) -> GrantOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            membership = get_membership(
                tenant=tenant,
                org=acting_org(acting),
                membership_id=membership_id,
                actor=actor,
            )
            grant = create_grant(
                tenant=tenant,
                actor=actor,
                membership=membership,
                permission=permission,
                effect=effect,
            )
            return GrantOut.of(grant, sentence=refusal_sentence(permission))

    @server.tool(name="delete_grant", description=contract_of(delete_grant_route))
    def delete_grant_tool(
        ctx: Context[Any], membership_id: UUID, permission: str
    ) -> dict[str, bool]:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            membership = get_membership(
                tenant=tenant,
                org=acting_org(acting),
                membership_id=membership_id,
                actor=actor,
            )
            row = (
                Grant.objects.for_tenant(tenant)
                .filter(membership=membership, permission=permission)
                .first()
            )
            if row is None:
                raise NotFound()
            delete_grant(tenant=tenant, actor=actor, grant=row)
            return {"deleted": True}

    @server.tool(
        name="get_membership_permissions",
        description=contract_of(membership_permissions_route),
    )
    def get_membership_permissions_tool(
        ctx: Context[Any], membership_id: UUID
    ) -> MembershipPermissionsOut:
        with tool_call(ctx) as acting:
            return MembershipPermissionsOut.of(
                get_membership_permissions(
                    tenant=acting_tenant(acting),
                    org=acting_org(acting),
                    membership_id=membership_id,
                    actor=acting.actor(),
                )
            )

    @server.tool(name="list_permissions", description=contract_of(list_permissions_route))
    def list_permissions_tool(
        ctx: Context[Any],
        kind: str | None = None,
        verb: str | None = None,
        decided_by: str | None = None,
        is_read: bool | None = None,
        q: str | None = None,
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> PermissionPage:
        with tool_call(ctx) as acting:
            filters = PermissionFilter(
                kind=kind, verb=verb, decided_by=decided_by, is_read=is_read, q=q
            )
            rows = [
                PermissionOut.of(word)
                for word in list_permissions(actor=acting.actor())
                if _permission_matches(word, filters)
            ]
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
                ordering=("key",),
            )
            return PermissionPage(
                items=list(page.items),
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    # --- Invitations ----------------------------------------------------------

    @server.tool(name="list_invitations", description=contract_of(list_invitations_route))
    def list_invitations_tool(
        ctx: Context[Any],
        status: str | None = None,
        email: str | None = None,
        organization_id: UUID | None = None,
        q: str | None = None,
        ordering: str = "-created_at",
        cursor: str | None = None,
        limit: int | None = None,
        include_count: bool = False,
    ) -> InvitationPage:
        with tool_call(ctx) as acting:
            rows: models.QuerySet[Invitation] = InvitationFilter(
                status=status, email=email, organization_id=organization_id
            ).filter(
                list_invitations(
                    tenant=acting_tenant(acting), org=acting_org(acting), actor=acting.actor()
                )
            )
            rows = searched(rows, q, fields=INVITATION_SEARCH_FIELDS)
            rows = ordered_by(rows, ordering, allowed=INVITATION_ORDERING, default="-created_at")
            page = cursor_page(
                rows,
                tenant=acting.tenant,
                cursor=cursor,
                limit=limit,
                include_count=include_count,
            )
            return InvitationPage(
                items=[InvitationOut.from_orm(row) for row in page.items],
                has_more=page.has_more,
                next_cursor=page.next_cursor,
                count=page.count,
            )

    @server.tool(name="create_invitation", description=contract_of(invite_member_route))
    def create_invitation_tool(
        ctx: Context[Any],
        email: str,
        role: str = "member",
        organization_id: UUID | None = None,
    ) -> InvitationIssuedOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            # Resolved through the hat's own subtree, the same way
            # `add_membership_tool` and both HTTP twins resolve theirs (ADR
            # core-20): a node outside it is `not_found`, never a placement.
            organization = (
                get_organization(
                    tenant=tenant,
                    org=acting_org(acting),
                    organization_id=organization_id,
                    actor=actor,
                )
                if organization_id is not None
                else None
            )
            invitation, token = invite_member(
                tenant=tenant,
                email=email,
                role=role,
                organization=organization,
                invited_by=acting.user,
                actor=actor,
            )
            return InvitationIssuedOut(invitation=InvitationOut.from_orm(invitation), token=token)

    @server.tool(name="delete_invitation", description=contract_of(revoke_invitation_route))
    def delete_invitation_tool(ctx: Context[Any], invitation_id: UUID) -> InvitationOut:
        with tool_call(ctx) as acting:
            tenant = acting_tenant(acting)
            actor = acting.actor()
            invitation = get_invitation(
                tenant=tenant, org=acting_org(acting), invitation_id=invitation_id, actor=actor
            )
            return InvitationOut.from_orm(
                revoke_invitation(tenant=tenant, invitation=invitation, actor=actor)
            )

    # --- The tenant's own configuration ---------------------------------------

    @server.tool(name="get_settings", description=contract_of(get_settings_route))
    def get_settings_tool(ctx: Context[Any]) -> TenantSettingsOut:
        with tool_call(ctx) as acting:
            return TenantSettingsOut.from_orm(acting_tenant(acting))

    @server.tool(name="update_settings", description=contract_of(update_settings_route))
    def update_settings_tool(
        ctx: Context[Any],
        values: dict[str, Any] | None = None,
        timezone: str | None = None,
        locale: str | None = None,
    ) -> TenantSettingsOut:
        with tool_call(ctx) as acting:
            return TenantSettingsOut.from_orm(
                update_tenant_settings(
                    tenant=acting_tenant(acting),
                    values=values,
                    timezone=timezone,
                    locale=locale,
                    actor=acting.actor(),
                )
            )

    @server.tool(name="get_flags", description=contract_of(get_flags_route))
    def get_flags_tool(ctx: Context[Any]) -> FlagsOut:
        with tool_call(ctx) as acting:
            return FlagsOut(flags=enabled_for(acting_tenant(acting)))

    @server.tool(name="update_flags", description=contract_of(set_flag_route))
    def set_flags_tool(ctx: Context[Any], name: str, enabled: bool | None) -> FlagsOut:
        with tool_call(ctx) as acting:
            return FlagsOut(
                flags=enabled_for(
                    set_flag(
                        tenant=acting_tenant(acting),
                        name=name,
                        enabled=enabled,
                        actor=acting.actor(),
                    )
                )
            )
