"""A sandbox-imported interceptor that runs the collector inside an activation (LA-WORKER-1)."""

from __future__ import annotations

import gc
from typing import Any

from temporalio.worker import (
    ExecuteWorkflowInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)


class _CollectAfterTheRun(WorkflowInboundInterceptor):
    """The run, then one full collection in the same activation."""

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        result = await super().execute_workflow(input)
        gc.collect()
        return result


class CollectInActivation(Interceptor):
    """Every run ends with the collector running inside its last activation."""

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> type[WorkflowInboundInterceptor]:
        return _CollectAfterTheRun
