"""Planted: a third wrap of a REAL ninja private, and the census untold.

`Operation._result_to_response` exists on the installed django-ninja, so the
existence half of this rule is satisfied and only the census half can fire.
That separation is the point: "we hold a private nobody wrote down" and "a
private we wrote down is gone" are two different findings, and a canary that
could only ever prove them together would prove neither.
"""

from typing import Any


def _reshape_the_response(operation: Any) -> None:
    inner = getattr(operation, "_result_to_response", None)
    if inner is None:
        raise RuntimeError("this ninja Operation has no `_result_to_response`")

    def result_to_response(request: Any, result: Any, temporal_response: Any) -> Any:
        return inner(request, result, temporal_response)

    operation._result_to_response = result_to_response
