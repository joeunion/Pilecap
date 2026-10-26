from typing import ClassVar

from django.apps import AppConfig


class WorkflowsConfig(AppConfig):
    """The durable-work platform: the Temporal client, the worker, the context."""

    name = "apps.workflows"
    verbose_name = "Workflows"
    # `accounts`: the run ledger grew its own REST and MCP doors,
    # and a door in this repository declares `API_AUTH` from `apps.accounts.auth`
    # by name rather than inheriting the API default (so that reading one file
    # tells you what it takes to call those routes). It is a downward import —
    # this app sits above `accounts` in the fixed layers — and it is declared
    # here because house rule 7 reads this line and nothing else.
    depends_on: tuple[str, ...] = ("core", "accounts")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 600,
        "91.docstring-tail": 1438,
        "91.module-tail": 480,
        "91.narrative": 8,
    }

    def ready(self) -> None:
        """Fill the bridge names this app provides.

        `core.mail` has to start a workflow and `core` sits below this app;
        `apps.events` has to start one too and `import-linter` holds the
        platform apps independent of each other. Neither may import this app, so
        this app hands them the callables they need, by name, from the one hook
        that runs in every process — the web server, the worker, `manage.py` and
        pytest alike (`apps.core.bridge`).

        `platform_context` is the fourth and the newest (ADR core-9). It is not
        for `core`: it is for `apps/accounts`, whose activity runs two
        **platform** kinds and, until this name existed, could not reach the
        declared accessor at all — this app sits above accounts, so the gap
        was reported rather than smuggling an upward import. The result was
        two platform runs resolving no scope and asserting nothing.

        The imports are inside `ready()` because `apps.py` is read by
        `config.settings.discovery` before Django exists.
        """
        from apps.core import bridge
        from apps.workflows.context import platform_context, workflow_context
        from apps.workflows.services import start_workflow_on_commit, workflow_id

        bridge.register(bridge.START_WORKFLOW_ON_COMMIT, start_workflow_on_commit)
        bridge.register(bridge.WORKFLOW_ID, workflow_id)
        bridge.register(bridge.WORKFLOW_CONTEXT, workflow_context)
        bridge.register(bridge.PLATFORM_CONTEXT, platform_context)
