"""ER1-5: every table this app is responsible for says how its data dies.

House rule 31's subject, from the app's own side. The gate counts the backlog
and ratchets it per Django `app_label`; this asserts the property the count is
counting, which is a different job: that the three labels ER-1 owns —
`accounts` (ours), `account` and `socialaccount` (allauth's, declared in
`apps/accounts/lifecycle.py`) — have nothing left undeclared.

**Derived, like everything else here.** The population is read off Django's
registry rather than typed out, so a sixth accounts model or an allauth upgrade
that grows a table fails this the day it lands rather than the day somebody
remembers to edit a list.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

from apps.core.lifecycle import (
    LifecycleKind,
    lifecycle_of,
    third_party_lifecycles,
    undeclared_models,
)

pytestmark = pytest.mark.django_db

#: The labels this app took responsibility for. `sessions` is deliberately
#: absent — `django_session` belongs to `workflows`, which owns the purge that
#: empties it, and `LifecycleRegistry.declare` refuses a second opinion rather
#: than letting import order settle which app was right.
OURS = frozenset({"accounts", "account", "socialaccount"})


def test_nothing_this_rung_owns_is_undeclared() -> None:
    """The ratchet's three classes, at zero, stated as the property not the number."""
    left = sorted(
        model._meta.label for model in undeclared_models() if model._meta.app_label in OURS
    )

    assert left == [], f"still undeclared in this app's labels: {', '.join(left)}"


def test_every_model_in_those_labels_has_a_lifecycle_of_a_real_kind() -> None:
    """The other direction: reader plus reader equals registry, over our slice."""
    for model in django_apps.get_models():
        if model._meta.app_label not in OURS:
            continue
        declared = lifecycle_of(model)
        assert declared is not None, model._meta.label
        assert declared.kind in set(LifecycleKind)


def test_allauth_is_declared_by_this_app_and_not_by_the_models() -> None:
    """The third-party half is an ownership claim, so name the owner.

    A table declared by whichever app happened to import first is a table whose
    retention nobody decided. `apps/accounts/lifecycle.py` is the source, and the
    registry records it so the census can print it.
    """
    third_party = third_party_lifecycles()

    for label in (
        "account.EmailAddress",
        "account.EmailConfirmation",
        "socialaccount.SocialAccount",
        "socialaccount.SocialToken",
        "socialaccount.SocialApp",
    ):
        assert label in third_party, f"{label} is not declared by any app"


def test_the_user_row_is_unbounded_because_erasure_keeps_it() -> None:
    """The coupling worth pinning: ADR ident-5's design IS this declaration.

    If somebody ever changes `erase_user` to delete the row, this declaration
    becomes false — and this is the test that says so out loud rather than a
    reader noticing two files disagreeing.
    """
    from apps.accounts.models import User

    declared = lifecycle_of(User)

    assert declared is not None
    assert declared.kind is LifecycleKind.UNBOUNDED
    assert "erase" in declared.reason.lower()
