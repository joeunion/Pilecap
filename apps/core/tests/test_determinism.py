"""The workflow seam imports nothing a workflow may not, and its literals equal their rows.

Rule 9 admits `apps.core.determinism` whole and does not re-read it — its declared blind spot.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from datetime import timedelta

from temporalio.common import RetryPolicy

from apps.core import determinism
from apps.workflows.models import WorkflowRun
from apps.workflows.types import MarkRunFinished

#: What the seam may import: the module roots rule 9 already admits for any
#: workflow, `datetime.timedelta`, `sys` (for the module's own road marker) and
#: the standard-library-only marker module.
ADMISSIBLE_ROOTS = {"__future__", "asyncio", "collections", "dataclasses", "typing", "temporalio"}
ADMISSIBLE_MODULES = {"sys", "apps.core.roads"}


def _imports() -> list[tuple[str, list[str]]]:
    tree = ast.parse(inspect.getsource(determinism))
    found: list[tuple[str, list[str]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, []) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.module, [alias.name for alias in node.names]))
    return found


def test_the_seam_imports_nothing_a_workflow_may_not() -> None:
    """Every import is an admitted root, `timedelta`, or one of the two named modules."""
    imports = _imports()
    assert imports, "an import walk that found nothing would pass vacuously"
    refused = [
        module
        for module, names in imports
        if not (
            module.split(".")[0] in ADMISSIBLE_ROOTS
            or module in ADMISSIBLE_MODULES
            or (module == "datetime" and names == ["timedelta"])
        )
    ]
    assert refused == [], f"apps/core/determinism.py imports {refused}"


def test_run_finished_is_the_shape_the_worker_deserialises_into() -> None:
    """The seam's `RunFinished` and the activity's `MarkRunFinished`: same fields, same defaults."""

    def shape(cls: type) -> list[tuple[str, object]]:
        return [(f.name, f.default) for f in dataclasses.fields(cls)]

    assert shape(determinism.RunFinished) == shape(MarkRunFinished)


def test_the_three_words_are_the_ledger_s_words() -> None:
    """A typo here writes a status no door can filter on, and nothing else would complain."""
    assert determinism.COMPLETED == WorkflowRun.Status.COMPLETED
    assert determinism.FAILED == WorkflowRun.Status.FAILED
    assert determinism.CANCELLED == WorkflowRun.Status.CANCELLED


def test_reason_of_names_the_cause_and_stops_at_three_links() -> None:
    """The wrapper's message is useless; the activity's own complaint is three links down."""
    try:
        try:
            try:
                try:
                    raise KeyError("fourth")
                except KeyError as deepest:
                    raise ValueError("the activity's own complaint") from deepest
            except ValueError as cause:
                raise RuntimeError("Activity task failed") from cause
        except RuntimeError as wrapped:
            raise LookupError("outer") from wrapped
    except LookupError as failure:
        said = determinism.reason_of(failure)
    assert said == (
        "LookupError: outer <- RuntimeError: Activity task failed "
        "<- ValueError: the activity's own complaint"
    )


def test_a_retry_policy_starts_at_the_number_it_was_handed() -> None:
    """Handed a floor, the first interval is that floor; handed none, it is the SDK's."""
    floored = determinism.retry_policy(initial_seconds=0.25, maximum_attempts=5)
    assert floored.initial_interval == timedelta(seconds=0.25)
    assert floored.maximum_attempts == 5
    assert determinism.retry_policy(maximum_attempts=5) == RetryPolicy(maximum_attempts=5)
    assert determinism.FINISH_RETRY == RetryPolicy(maximum_attempts=5)
