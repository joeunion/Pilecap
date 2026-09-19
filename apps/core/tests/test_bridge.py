# census: cross-app population=apps/core/**/*.py for an import of an app above core
"""The bridge: what a lower layer gets when it calls upward, and what it does not.

Three properties, and the third is the one that makes the design honest:

1. what an app registered from its `AppConfig.ready()` is what a caller gets;
2. an absent registration is a **refusal in production** and a logged no-op
   everywhere else, so a checkout without the platform apps still runs and a
   deployment without them does not silently stop sending email;
3. **no module under `apps/core` imports an app above it** — scanned with `ast`,
   including inside function bodies, because a function-local import was exactly
   the shape the bridge replaced.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from apps.core import bridge
from apps.core.actor import system_actor
from apps.core.models import Tenant
from apps.core.tests.tree_census import source_tree

CORE_DIR = Path(__file__).resolve().parents[1]

# What `core` may never import. `accounts` and every platform app sit above it;
# `config` is covered by its own import-linter contract and is here too because
# the same scan can say so.
FORBIDDEN_PREFIXES = (
    "apps.accounts",
    "apps.workflows",
    "apps.events",
    "apps.connections",
    "apps.realtime",
    "config",
)


@pytest.fixture
def clean_bridge() -> Iterator[None]:
    """Give the test the real registry back afterwards.

    The bridge is filled once per process, at startup, so a test that plants or
    clears a name has to put back what the apps registered — otherwise the next
    test finds an empty bridge and passes for the wrong reason. Restoring the
    snapshot rather than re-running every `ready()` keeps the restoration to the
    one thing that changed.
    """
    saved = bridge.registered()
    yield
    bridge.clear()
    for name, fn in saved.items():
        bridge.register(name, fn)


# --- What the apps registered ------------------------------------------------


def test_the_platform_apps_filled_their_names() -> None:
    """`ready()` runs in every process — web, worker, manage.py, pytest."""
    assert bridge.is_registered(bridge.START_WORKFLOW_ON_COMMIT)
    assert bridge.is_registered(bridge.WORKFLOW_ID)
    assert bridge.is_registered(bridge.WORKFLOW_CONTEXT)
    assert bridge.is_registered(bridge.EMIT)


@pytest.mark.django_db
def test_emit_is_reachable_from_core_through_the_bridge(tenant: Tenant) -> None:
    """The whole point: a `core` service can say something happened.

    `core` cannot import `apps.events` — it sits two layers below it — so this
    is how `core.services` will emit when it needs to, and it is the same
    callable `apps.events` registered.
    """
    from apps.events.events import ENDPOINT_REGISTERED
    from apps.events.models import Event

    emit = bridge.get(bridge.EMIT)
    event = emit(
        name=ENDPOINT_REGISTERED,
        tenant=tenant,
        payload={"endpoint_id": "from-core"},
        actor=system_actor(tenant=tenant),
    )

    assert Event.objects.for_tenant(tenant).filter(pk=event.pk).exists()


# --- Absent registrations ----------------------------------------------------


def test_an_absent_name_is_a_logged_no_op_outside_production(clean_bridge: None) -> None:
    """A template without the platform apps still has to run."""
    bridge.clear()
    assert bridge.find("workflows.start_on_commit") is None

    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    assert start(workflow="Whatever", arg=None, tenant=None, id="x") is None


def test_an_absent_name_raises_in_production(clean_bridge: None, settings: Any) -> None:
    """A deployment that silently stops sending email is the worse failure."""
    bridge.clear()
    settings.BRIDGE_STRICT = True

    with pytest.raises(bridge.BridgeNotRegistered) as raised:
        bridge.get(bridge.EMIT)
    assert "events.emit" in str(raised.value)


def test_production_settings_are_strict_without_being_told(settings: Any) -> None:
    """`BRIDGE_STRICT` is the override; the settings module is the default."""
    settings.SETTINGS_MODULE = "config.settings.production"
    assert bridge.strict() is True

    settings.SETTINGS_MODULE = "config.settings.local"
    assert bridge.strict() is False


def test_find_never_raises_even_in_production(clean_bridge: None, settings: Any) -> None:
    """The realtime push is allowed not to care, and says so with `find`."""
    bridge.clear()
    settings.BRIDGE_STRICT = True
    assert bridge.find(bridge.REALTIME_PUSH) is None


def test_a_registration_must_be_callable(clean_bridge: None) -> None:
    with pytest.raises(TypeError):
        bridge.register("something.broken", "not a callable")  # type: ignore[arg-type]


def test_what_was_registered_is_what_comes_back(clean_bridge: None) -> None:
    def stub(**kwargs: Any) -> str:
        return "called"

    bridge.register("test.thing", stub)
    got: Callable[..., Any] = bridge.get("test.thing")
    assert got() == "called"
    assert bridge.registered()["test.thing"] is stub


# --- Nothing in `core` reaches upward ----------------------------------------


def _upward_imports(source: Path) -> list[str]:
    """Every import in a module that names an app above `core`. Any nesting."""
    tree = source_tree(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                alias.name for alias in node.names if alias.name.startswith(FORBIDDEN_PREFIXES)
            ]
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith(FORBIDDEN_PREFIXES):
                found += [f"{node.module}.{alias.name}" for alias in node.names]
    return found


def test_no_module_in_core_imports_an_app_above_it() -> None:
    """The one production exception is gone; this is what keeps it gone.

    `import-linter` reads the module graph and can be told to ignore a line;
    this reads the source and cannot. It walks the whole tree, so a
    function-local import — which is what `core.mail` used to do — is caught
    exactly like a top-level one.
    """
    scanned = sorted(
        path
        for path in CORE_DIR.rglob("*.py")
        if "tests" not in path.parts and "migrations" not in path.parts
    )
    assert scanned, "no core modules found — the scan would pass vacuously"

    offences = {
        str(path.relative_to(CORE_DIR)): _upward_imports(path)
        for path in scanned
        if _upward_imports(path)
    }
    # `introspect` and the `djb` system checks are the two modules whose whole
    # job is reading what the mounts found (routes, tools — house rules 3 and
    # 17 diff the live registries); both are exempted by name in the
    # import-linter contract for the same stated reason, and both import
    # lazily, inside the function that needs each mount.
    offences.pop("management/commands/introspect.py", None)
    offences.pop("checks.py", None)

    assert offences == {}, f"core reaches upward: {offences}"


def test_the_scan_would_catch_one(tmp_path: Path) -> None:
    """The canary: a test that cannot fail is not a test."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "def send():\n    from apps.workflows.services import start_workflow_on_commit\n",
        encoding="utf-8",
    )
    assert _upward_imports(planted) == ["apps.workflows.services.start_workflow_on_commit"]
