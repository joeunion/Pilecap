"""The app's kinds: `endpoint` is the word the doors use, and neither model names an organization.

Core's flat census (`apps/core/tests/flat_product_baseline.json`) holds this app's six keys.
"""

from __future__ import annotations

import pytest

from apps.events.models import Delivery, WebhookEndpoint

pytestmark = pytest.mark.django_db


def test_the_endpoint_kind_is_the_word_the_doors_use() -> None:
    """`authz_kind = "endpoint"`, and the derived spelling still answers.

    The five declared `endpoint.*` keys are in the vocabulary and CONFORM — that
    is the half that takes their names out of `test_vocabulary.py`'s pinned
    ratchet. The four `webhook_endpoint.*` keys the registry used to derive are
    aliases, so a `Grant` or `RolePermission` row a deployment stored under one
    goes on answering; `refusal_sentence` proves the words a refused caller reads
    did not move either.

    *What differs if this is false*: a stored row under the old spelling holds
    nothing, silently, which is the widening a rename exists to prevent.
    """
    from apps.core.authz import kind_of, refusal_sentence, renamed_permissions, vocabulary
    from apps.events import policies

    assert WebhookEndpoint.authz_kind == "endpoint"
    assert kind_of(WebhookEndpoint) == "endpoint"

    words = vocabulary()
    for verb in ("create", "read", "update", "delete"):
        assert f"endpoint.{verb}" in words, verb
        # The derived spelling is an ALIAS, never a second key in the census.
        assert f"webhook_endpoint.{verb}" not in words, verb

    table = renamed_permissions()
    for old, new in policies.RENAMED_PERMISSIONS.items():
        assert table[old] == new
        assert refusal_sentence(old) == refusal_sentence(new)

    # The conforming half, which is what the pinned ratchet in core lost.
    for key in sorted(policies.ACTION_PROSE):
        assert words[key].conforms, key


def test_the_kinds_name_no_organization_so_core_census_covers_them() -> None:
    """Every cell is asked at the hat, so core's object-less census is this app's whole matrix."""
    for model in (WebhookEndpoint, Delivery):
        fields = {field.name for field in model._meta.get_fields()}  # noqa: SLF001
        assert "organization" not in fields, model.__name__
