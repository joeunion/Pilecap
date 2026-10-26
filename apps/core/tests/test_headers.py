# census: cross-app population=apps/**/*.py walks for a second home of a djb-* header name
"""The Temporal header names import nothing a workflow sandbox refuses."""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import subprocess
import sys
import uuid

import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from apps.core import headers
from apps.core.tests.sandboxwork import SandboxImportProbe
from apps.core.tests.tree_census import source_tree
from apps.workflows.client import attach_interceptors

TASK_QUEUE = "djb-tests-sandbox-import"


def test_the_header_module_imports_the_standard_library_only() -> None:
    """Every import is `__future__` or a standard-library module."""
    tree = ast.parse(inspect.getsource(headers))
    imported = [
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    ]
    foreign = [m for m in imported if m and m.split(".")[0] not in sys.stdlib_module_names]
    assert foreign == [], f"apps/core/headers.py imports {foreign}"


@pytest.mark.asyncio
async def test_a_workflow_importing_the_interceptor_runs_under_the_default_sandbox() -> None:
    """The worker validates and runs a workflow whose module imports `apps.workflows.context`."""
    async with await WorkflowEnvironment.start_time_skipping() as env:
        client = attach_interceptors(env.client)
        async with Worker(client, task_queue=TASK_QUEUE, workflows=[SandboxImportProbe]):
            loaded: list[str] = await client.execute_workflow(
                "SandboxImportProbe",
                id=f"sandbox-import-probe-{uuid.uuid4().hex}",
                task_queue=TASK_QUEUE,
                result_type=list,
            )
    assert "apps.workflows.context" in loaded


TEMPORAL_HEADERS = (
    "TENANT_HEADER",
    "ORG_HEADER",
    "USER_HEADER",
    "CORRELATION_HEADER",
    "CAUSATION_HEADER",
)


def test_every_temporal_header_is_declared_once_in_the_header_module() -> None:
    """Each `djb-*` header is assigned in `apps/core/headers.py` and nowhere else in `apps/`."""
    root = pathlib.Path(headers.__file__).resolve().parents[2]
    homes: dict[str, list[str]] = {name: [] for name in TEMPORAL_HEADERS}
    for path in sorted((root / "apps").rglob("*.py")):
        tree = source_tree(path)
        for node in tree.body:
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not str(node.value.value).startswith("djb-"):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in homes:
                    homes[target.id].append(str(path.relative_to(root)))
    assert homes == {name: ["apps/core/headers.py"] for name in TEMPORAL_HEADERS}


def test_the_header_module_imports_with_no_django_settings() -> None:
    """`import apps.core.headers` succeeds in a process with `DJANGO_SETTINGS_MODULE` unset."""
    root = pathlib.Path(headers.__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    done = subprocess.run(
        [sys.executable, "-c", "import apps.core.headers"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
