"""A test builds fakes for a living, and test modules are outside the walk.

The real one this is modelled on is `apps/core/tests/test_method_refusal.py`,
which stands up a `PathView` and puts its own `_find_operation` and
`_not_allowed` on it — which is how its wire behaviour is proved at all. A
rule that censused those would make the only way to test a wrap be not to.
Planted in the gate's own scaffold rather than beside the real test (: a
plant in a product app dies the day that app grows the healthy feature).
"""

from typing import Any


def test_a_path_view_that_answers_nothing() -> None:
    class Fake:
        pass

    path_view: Any = Fake()
    path_view._find_operation = lambda request: None
    path_view._not_allowed = lambda: None
    path_view._sync_view = lambda request: None
    path_view._async_view = lambda request: None
    assert path_view._find_operation(None) is None
