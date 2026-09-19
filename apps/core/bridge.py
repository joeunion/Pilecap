"""The bridge — how a lower layer calls a higher one without importing it.

The dependency direction is fixed (`architecture.md`): `core` ← `accounts` ←
platform (`workflows`, `events`, `connections`, `realtime`) ← domain. It is
fixed because an import that runs the other way is a cycle waiting to happen and
a layer contract nobody can write. But two settled decisions do point that way:

* `core.services.invite_member` has to **start a workflow** to send its email,
  and `workflows` sits above `core`;
* a `core` service that wants to say something happened has to **`emit()`**, and
  `events` sits above `core` too;
* and the platform apps are *siblings* — `import-linter` holds them independent
  of each other — so `events` cannot import `workflows` either, even though
  emitting an event is exactly what starts the dispatch workflow.

**So the call inverts.** The higher app registers a callable under a name from
its `AppConfig.ready()`; the lower one looks the name up at call time. No
import, no cycle, no layer violation — and, unlike a function-local import, the
tooling is not being dodged: the dependency is declared on the app
(`depends_on`) and named here, in one place, as a constant.

    # apps/workflows/apps.py
    bridge.register(bridge.START_WORKFLOW_ON_COMMIT, start_workflow_on_commit)

    # apps/core/mail.py
    bridge.get(bridge.START_WORKFLOW_ON_COMMIT)(workflow=..., arg=..., tenant=..., id=...)

**What happens when nobody registered.** A template without the platform apps
still has to run — that is the whole point of a template — so an absent
registration is not a crash on a laptop or in the test suite: `get()` returns a
callable that does nothing and logs `core.bridge.missing`, which is a structured
line somebody can actually search for. In **production** it raises: a deployment
where the email workflow silently never starts is worse than one that refuses to
serve the request, and "the invitations stopped going out in March" is the
incident this refusal prevents.

`find()` is the third answer, for the caller that genuinely does not mind:
the realtime push, which no-ops when `apps.realtime` is not installed. It never
raises, in any environment, and the caller says so at the call site.

## The shape of each name

A name is only half a contract. `bridge.get(EMIT)` returns
`Callable[..., Any]` — which is the honest type, because this module cannot
import the app that fills it, and is also no help at all: a registrant that
grew a keyword or lost one would break its callers at runtime, in whichever
process happened to call it first, with a `TypeError` naming a function `core`
has never heard of.

So each name declares a **`Protocol`** below, and `SHAPES` binds the two
together. The protocols type the foreign classes as `Any` — `core` may not
import `Tenant`'s owner app any more than it may import the function — so what
they pin is the part that actually drifts: the parameter names, that they are
keyword-only, which have defaults, and the arity of what comes back.
`apps/core/tests/test_bridge_shape.py` reads the *live registry* with
`inspect.signature` and compares it to the protocol, so a registrant that
changes shape fails a test in `core` rather than a request in production.

**These are the shapes as the code has them, not as prose remembered them.**
`workflow_context()` returns a **3-tuple** — tenant, user id and the acting hat
— and said "(Tenant | None, str | None)" here until this comment was fixed; the
org became the third element when the hierarchy landed. Code wins, and the test
below is what keeps the comment honest from now on.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from django.conf import settings

from apps.core.log import get_logger

log = get_logger("apps.core.bridge")

# --- The names -------------------------------------------------------------
# Constants rather than string literals at the call site: a name is a contract
# between two apps that never import each other, so a typo would be a silent
# no-op on a laptop and a production refusal months later.

#: `apps.workflows.services.start_workflow_on_commit`
START_WORKFLOW_ON_COMMIT = "workflows.start_on_commit"
#: `apps.workflows.services.workflow_id`
WORKFLOW_ID = "workflows.workflow_id"
#: `apps.workflows.context.workflow_context`
WORKFLOW_CONTEXT = "workflows.context"
#: `apps.workflows.context.platform_context` — the declared opt-out from
#: `WORKFLOW_CONTEXT`'s guard, for the run population that legitimately has no
#: tenant (ADR workflows-3, and now ADR core-8's audit rows too). It is on the
#: bridge for the reason everything else here is: `apps.workflows` sits ABOVE
#: `apps.accounts`, so an activity in a lower app could not reach the accessor
#: at all — and the two platform kinds in `apps/accounts/activities.py`
#: therefore resolved no scope and asserted nothing, which is a platform run
#: proceeding under whatever headers it happened to arrive with (ADR core-9).
PLATFORM_CONTEXT = "workflows.platform_context"
#: `apps.events.services.emit`
EMIT = "events.emit"
#: `apps.realtime.bridge.push_from_spine` — the push into a tenant's socket
#: group, called by the event spine's dispatch workflow with the `EventOut` body
#: a webhook subscriber would receive (`apps.events.schemas.envelope`). Optional:
#: `apps.events` looks it up with `find()` and no-ops when the app is not
#: installed. Shape and the reasons for it: `PushesToSockets`, below.
REALTIME_PUSH = "realtime.push"
#: `apps.realtime.bridge.kick_from_spine` — close every socket one person has
#: open, because what stood behind them was withdrawn (ADR realtime-2 d).
#: Socket auth AND socket subscriptions are both resolved once, at the
#: handshake, which is right for a channel that then stays open for hours and
#: wrong the moment a token is revoked, a user erased, a membership removed or a
#: subtree re-parented: without a way in from outside, a withdrawn credential —
#: or a withdrawn hat — keeps receiving until the client happens to disconnect.
#: Both callers sit BELOW `apps.realtime` and could not import the function at
#: all — which is the bridge's whole reason, restated for a second name. The
#: seam they share is `core.services.close_sockets_on_commit`: `apps.accounts`
#: re-exports it for the credential half (SEC-1 MED-1 promoted it out of that
#: app so `core` could reach it without a second copy), and `core.services`
#: calls it directly for the authorization half. A role change is deliberately
#: NOT a caller; `apps/realtime/bridge.py`'s module docstring holds the reason
#: and the trigger that would change it.
#: Optional, like the push: looked up with `find()`, because a deployment
#: without the socket app has no socket to close. Shape: `KicksUser`, below.
KICK = "realtime.kick"
#: `apps.realtime.bridge.kick_tenant_from_spine` — close every socket open on
#: one TENANT, because the tenant itself was suspended or closed (ADR
#: realtime-2 d, second primitive). A separate name and not a parameter on
#: `KICK`: the two are reached through different groups (`user_group` against
#: `tenant_group`) and they answer different questions — "this credential is
#: gone" against "this workspace is". Folding them into one signature would
#: make every caller pass a discriminator and would put the group choice in
#: the caller rather than in the app that owns the groups.
#: R4 F2 is why it exists: `suspend_tenant` and `close_tenant` wrote a status
#: and registered nothing, so a darkened tenant was refused at the next
#: HANDSHAKE and nowhere else while every live socket went on hearing — and
#: the REST door answered 403 to the same credential for the whole life of
#: the connection. Optional, looked up with `find()`, like the other two.
#: Shape: `KicksTenant`, below.
KICK_TENANT = "realtime.kick_tenant"


# --- The shapes --------------------------------------------------------------
# One protocol per name. Foreign classes are `Any` because `core` may not import
# the app that owns them — that is the whole reason the bridge exists — so what
# these pin is what drifts: the parameter names, keyword-only-ness, the
# defaults, and the arity of the answer. `test_bridge_shape.py` holds the live
# registrants to them.


class StartsWorkflowOnCommit(Protocol):
    """`apps.workflows.services.start_workflow_on_commit`.

    Writes the `WorkflowRun` visibility row inside the caller's transaction and
    defers the Temporal client call to `transaction.on_commit`. `id` has no
    default on purpose (house rule 18): a random default would throw away the
    determinism that makes a retried service idempotent.

    `reask_after_failure` DOES default, to `False`, and the default is the
    contract: it re-opens a run that finished without delivering instead of
    refusing the honest retry, and a caller that says nothing gets the answer
    it always got. It is declared here because the callers that most want it —
    `accounts`' identity runs among them — sit below `apps.workflows` and reach
    the starter through this name, so a keyword absent from this protocol is a
    keyword they cannot pass.
    """

    def __call__(
        self,
        *,
        workflow: Any,
        arg: Any,
        tenant: Any,
        user: Any = None,
        org: Any = None,
        id: str,
        task_queue: str | None = None,
        reask_after_failure: bool = False,
    ) -> Any: ...


class BuildsWorkflowId(Protocol):
    """`apps.workflows.services.workflow_id` — `<tenant_slug>:<app>:<noun>:<key>`."""

    def __call__(self, *, tenant: Any, app: str, noun: str, key: str) -> str: ...


class ReadsWorkflowContext(Protocol):
    """`apps.workflows.context.workflow_context`. **Activities only** — it reads rows.

    **Three** elements: the acting tenant, the acting user's id, and the acting
    **hat**. The org joined when the hierarchy landed; an activity that restored
    the tenant but not the org would read the whole tenant, which is the leak
    `visible_to` exists to close. Anything that describes this as a pair is out
    of date, and `test_bridge_shape.py` calls it and counts.
    """

    def __call__(self) -> tuple[Any, Any, Any]: ...


class ReadsPlatformContext(Protocol):
    """`apps.workflows.context.platform_context`. **Activities only** — it reads rows.

    The same **three** elements as `ReadsWorkflowContext`, and deliberately the
    same arity: a caller unpacks one or the other with the same line, so moving
    an activity between the populations is a one-word change rather than a
    rewrite. What differs is the contract, not the shape — this one **may
    answer `None`**, because the platform population has no tenant rather than a
    missing one, and `workflow_context()` raising is exactly right for the
    second case and exactly wrong for the first.

    **What it does not promise, stated because a caller has to know.** It is a
    plain read of the contextvars the interceptor set; it does not *assert* that
    the tenant is absent. A platform run whose headers somehow carry a tenant
    gets that tenant back from this call. The refusal therefore belongs to the
    caller that knows it is platform-scoped — see
    `apps/accounts/activities.py`, where the two platform kinds fail loudly on
    a stamped tenant rather than proceeding cross-scoped.
    """

    def __call__(self) -> tuple[Any, Any, Any]: ...


class EmitsEvent(Protocol):
    """`apps.events.services.emit`. Called from inside a service's transaction.

    `v` is the payload's schema version and defaults to 1; the correlation pair
    comes from the bound context and is never minted at the call site, which is
    why only `causation_id` is a parameter.
    """

    def __call__(
        self,
        *,
        name: str,
        tenant: Any,
        payload: dict[str, Any],
        # Required and never defaulted since ADR core-22's L1 ruling: `emit`
        # writes an `Event` and an `Outbox` row, and a defaulted actor is a
        # service that looks attributed and files under nobody the moment a
        # caller leaves it out. The declaration and the registrant are pinned
        # against each other by `test_bridge_shape.py`, which is why this
        # comment is here and not only in `events/services.py`.
        actor: Any,
        causation_id: str | None = None,
        v: int = 1,
    ) -> Any: ...


class PushesToSockets(Protocol):
    """`apps.realtime.bridge.push_from_spine`.

    Synchronous, and takes the `EventOut` body as a plain mapping: the caller is
    a plain `def` activity with no event loop, and it cannot import the other
    app's schema to build one. Optional — looked up with `find()`.
    """

    def __call__(self, *, tenant_id: Any, event: Any) -> None: ...


class KicksUser(Protocol):
    """`apps.realtime.bridge.kick_from_spine`.

    Synchronous, for the same reason `PushesToSockets` is: the caller is a plain
    `def` activity with no event loop, and a coroutine handed to a sync caller
    is a coroutine nobody awaits — here that would be a revocation reporting
    success while every socket stayed open.

    `user_id` and not a user row, because `core` may not name the model and a
    cross-process instruction should carry an identifier rather than an object
    anyway. `reason` is free text for the log line and defaults, so a caller
    that has nothing useful to say is not made to invent something. Optional —
    looked up with `find()`.
    """

    def __call__(self, *, user_id: Any, reason: str | None = None) -> None: ...


class KicksTenant(Protocol):
    """`apps.realtime.bridge.kick_tenant_from_spine`.

    Synchronous for the same reason `KicksUser` is, and shaped like it on
    purpose: the two primitives differ only in WHICH group the instruction
    goes to, and a caller that had to learn a second calling convention for
    the same act would eventually get one of them wrong.

    `tenant_id` and not a tenant row, because `core` may not name the model —
    the same argument, one level up. Optional; looked up with `find()`.
    """

    def __call__(self, *, tenant_id: Any, reason: str | None = None) -> None: ...


#: Every name, and the shape whatever fills it must have. Read by
#: `apps/core/tests/test_bridge_shape.py`, which is where the pinning happens:
#: a registrant that gains, loses or renames a keyword fails there instead of
#: failing a request in whichever process called it first.
SHAPES: dict[str, type] = {
    START_WORKFLOW_ON_COMMIT: StartsWorkflowOnCommit,
    WORKFLOW_ID: BuildsWorkflowId,
    WORKFLOW_CONTEXT: ReadsWorkflowContext,
    PLATFORM_CONTEXT: ReadsPlatformContext,
    EMIT: EmitsEvent,
    REALTIME_PUSH: PushesToSockets,
    KICK: KicksUser,
    KICK_TENANT: KicksTenant,
}


class BridgeNotRegistered(RuntimeError):
    """Nobody registered this name, and this deployment refuses to continue.

    Raised only where `strict()` is true — production. Elsewhere the call is a
    logged no-op, so a checkout without the platform apps still runs.
    """


_registry: dict[str, Callable[..., Any]] = {}


def strict() -> bool:
    """Whether an absent registration is a refusal rather than a no-op.

    Production, by the settings module that is actually in force. A product that
    wants the refusal somewhere else — a staging environment, a test that proves
    this behaviour — sets `BRIDGE_STRICT` and that wins.
    """
    configured = getattr(settings, "BRIDGE_STRICT", None)
    if configured is not None:
        return bool(configured)
    module = str(getattr(settings, "SETTINGS_MODULE", "") or "")
    return module.rsplit(".", 1)[-1] == "production"


def register(name: str, fn: Callable[..., Any]) -> None:
    """Fill a bridge name. Called from an `AppConfig.ready()` and nowhere else.

    `ready()` is the one place that runs in every process — the web server, the
    Temporal worker, `manage.py`, pytest — which is exactly the property this
    needs: a bridge filled from a module import would be filled only in the
    processes that happened to import that module.
    """
    if not callable(fn):
        raise TypeError(f"A bridge registration must be callable; {name!r} got {type(fn)!r}.")
    _registry[name] = fn


def registered() -> dict[str, Callable[..., Any]]:
    """Everything registered, as a copy. For `introspect`, and for tests."""
    return dict(_registry)


def is_registered(name: str) -> bool:
    return name in _registry


def clear() -> None:
    """Empty the registry. **Tests only** — production fills it once, at startup."""
    _registry.clear()


def find(name: str) -> Callable[..., Any] | None:
    """The callable, or `None`. Never raises, in any environment.

    For the caller whose work is genuinely optional — the realtime push, which
    has nowhere to go when `apps.realtime` is not installed. A caller that
    cannot do its job without the other app uses `get()` instead, so that
    production says so.
    """
    return _registry.get(name)


def _missing(name: str) -> Callable[..., Any]:
    def noop(*args: Any, **kwargs: Any) -> None:
        log.warning(
            "core.bridge.missing",
            bridge=name,
            detail="Nothing registered this name; the call did nothing.",
        )
        return None

    return noop


def get(name: str) -> Callable[..., Any]:
    """The callable registered under `name`.

    Absent: `BridgeNotRegistered` in production, a logging no-op everywhere
    else. The asymmetry is deliberate — see the module docstring.
    """
    fn = _registry.get(name)
    if fn is not None:
        return fn
    if strict():
        raise BridgeNotRegistered(
            f"Nothing is registered on the bridge as {name!r}. The app that provides "
            "it registers it from its AppConfig.ready(); check that the app is "
            "installed and that its ready() runs."
        )
    return _missing(name)
