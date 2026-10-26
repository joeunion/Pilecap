"""The connections provider's one state is enough: neither kind names an organization."""

from __future__ import annotations

import pytest

from apps.connections.models import Connection, InboundWebhook

pytestmark = pytest.mark.django_db


def test_the_two_kinds_name_no_organization_so_the_provider_is_one_state() -> None:
    """`authz_objects.py` gives one `row`, because `where_of` reads a node off `organization`.

    A model that grows an organization turns the one state into a blind spot.
    """
    for model in (Connection, InboundWebhook):
        fields = {field.name for field in model._meta.get_fields()}  # noqa: SLF001
        assert "organization" not in fields, model.__name__
