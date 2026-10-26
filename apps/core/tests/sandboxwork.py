"""A workflow whose module imports the run-principal interceptor, for the default sandbox to load.

Not collected; it exists to be imported into the sandbox, so it imports only what a workflow may.
"""

from __future__ import annotations

import sys

from temporalio import workflow

import apps.workflows.context  # noqa: F401 - the import under test


@workflow.defn(name="SandboxImportProbe")
class SandboxImportProbe:
    """Answers the `apps.*` modules the sandbox loaded for it."""

    @workflow.run
    async def run(self) -> list[str]:
        return sorted(name for name in sys.modules if name.startswith("apps."))
