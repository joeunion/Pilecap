"""The probe app's tests — real ones, and not one of them pins a query count.

The SECOND form of rule 5's app clause, and the one a real app actually takes.
`_app_is_pinned` is False two ways: an app with no `tests/` at all (the sibling
canary's shape), and an app that HAS tests and never names the pin helper. The
second is the case worth planting, because "we have tests" is exactly the
sentence that gets a missing pin waved through in review.

Nothing in this file may spell the helper's name — not even in prose. The
predicate is a substring search over the app's whole `tests/` tree, so a comment
mentioning it would make the app read as pinned and this canary would go silent
for a reason that has nothing to do with the rule. (It did, once, while this
fixture was being written; the canary refused to fire and said so.)
"""


def test_the_probe_app_answers() -> None:
    assert True


def test_the_probe_app_lists_things() -> None:
    items: list[str] = []
    assert items == []
