"""The stored failure reason of exports' and files' runs is `core.determinism.reason_of`'s line."""

from __future__ import annotations

import pytest

from apps.core import determinism
from apps.exports import workflows as export_workflows
from apps.files import workflows as file_workflows


def _chained(wrapper: BaseException, cause: BaseException) -> BaseException:
    wrapper.__cause__ = cause
    return wrapper


def test_both_workflows_call_the_one_road() -> None:
    assert vars(export_workflows)["reason_of"] is determinism.reason_of
    assert vars(file_workflows)["reason_of"] is determinism.reason_of


# Each case is one of the five ways this line differs from the private copies it replaced.
@pytest.mark.parametrize(
    ("failure", "said"),
    [
        (
            _chained(RuntimeError("Activity task failed"), ValueError("inner")),
            "RuntimeError: Activity task failed <- ValueError: inner",
        ),
        (RuntimeError("boom"), "RuntimeError: boom"),
        (RuntimeError(), "RuntimeError: "),
        (
            _chained(RuntimeError("same"), ValueError("same")),
            "RuntimeError: same <- ValueError: same",
        ),
        (_chained(RuntimeError(), ValueError("inner")), "RuntimeError:  <- ValueError: inner"),
    ],
    ids=[
        "typed-links",
        "one-link-typed",
        "empty-message",
        "not-deduplicated",
        "empty-wrapper-kept",
    ],
)
def test_the_reason_reads_type_and_message_link_by_link(failure: BaseException, said: str) -> None:
    assert determinism.reason_of(failure) == said
