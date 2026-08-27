"""The declaration, and the chain it names, walked link by link.

House rule 31's whole finding, in one sentence: **a schema shaped for a sweeper,
with no sweeper, looks exactly like a schema that is finished.** This app has no
schema at all and a population of copied personal data in somebody else's
server, which is the same finding one level further out — so the declaration in
`apps/search/lifecycle.py` owes exactly what a model's `lifecycle` ClassVar owes,
and this module is what collects it.

The tooth rule 31 grows for models (LF-Q) resolves `purged_by` and walks the
schedule chain that reaches it. It cannot see this population — its subject is
`django_apps.get_models()` and there is no model here — so the walk is done from
inside the app instead, which is the same thing `apps/exports/tests/
test_lifecycle.py` does for a chain a static walk cannot fully see. **A
declaration nothing walks is a promise, and a promise is what the rule exists to
refuse.**
"""

from __future__ import annotations

import importlib

from apps.core.lifecycle import Lifecycle, LifecycleKind
from apps.search import activities, lifecycle


def test_the_documents_are_declared_and_the_declaration_is_purged() -> None:
    """The population exists, has a name, and says how it ends.

    `PURGED` and not `BOUNDED`: a document does die with its row in the ordinary
    case, but the case that matters is a tenant erased in one act, whose rows
    are gone before any event describes them. `BOUNDED` would have declared that
    away — see the module's own reasoning.
    """
    declared = lifecycle.populations()

    assert set(declared) == {lifecycle.DOCUMENTS}
    document = declared[lifecycle.DOCUMENTS]
    assert isinstance(document, Lifecycle)
    assert document.kind is LifecycleKind.PURGED
    assert document.declared_for == lifecycle.DOCUMENTS


def test_the_census_hands_back_a_copy_and_not_the_module_s_own_dict() -> None:
    """A reader that returns its module's mutable object is a census a caller can edit."""
    first = lifecycle.populations()
    first.clear()

    assert set(lifecycle.populations()) == {lifecycle.DOCUMENTS}


def test_purged_by_resolves_to_something_that_is_actually_there() -> None:
    """Rule 31's `unresolvable` class, asked of a population the rule cannot see.

    A dotted path that names nothing importable clears every check the primitive
    can make at import — it is a dotted string — and is a purge into the void.
    The only way to find out is to resolve it, so this resolves it.
    """
    path = lifecycle.DOCUMENT_LIFECYCLE.purged_by
    module_name, _, attribute = path.rpartition(".")

    module = importlib.import_module(module_name)
    purger = getattr(module, attribute, None)

    assert callable(purger), f"{path} names nothing callable"


def test_the_belt_underneath_the_purge_is_a_real_declared_schedule() -> None:
    """The other half of "eventually", named rather than assumed.

    The declaration names the prompt disposal (`delete_tenant_documents`). What
    makes a MISSED purge recoverable rather than permanent is the hourly
    reconcile, which rebuilds each kind from Postgres — so a document whose row
    has gone stops existing at the next rebuild whether anybody called the purge
    or not. That claim is only worth writing down if the schedule is really
    declared, so this reads it off the app's own `SCHEDULES` rather than off the
    prose.

    Containment and not equality: `SCHEDULES` is this app's list, and asserting
    about its whole contents would be asserting about whatever the next rung
    declares (django-conventions §12).
    """
    assert lifecycle.DOCUMENT_LIFECYCLE.purged_by.endswith("delete_tenant_documents")
    assert activities.RECONCILE in activities.SCHEDULES
    assert activities.RECONCILE.name == "search.reconcile-indexes"


def test_this_app_still_declares_no_models_for_rule_31_to_find() -> None:
    """The premise the whole module rests on, pinned so it cannot rot silently.

    If this app ever grows a table, rule 31 becomes its subject and the named
    population above stops being the whole story — and the failure of this test
    is the notice. `apps.py` says a rung that finds itself running
    `makemigrations search` has been asked for the wrong thing; this is that
    sentence with teeth.
    """
    from django.apps import apps as django_apps

    assert list(django_apps.get_app_config("search").get_models()) == []
