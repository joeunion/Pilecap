"""One identity-config run per intent change: the key is the intent plus the write's generation."""

from __future__ import annotations

import pytest

from apps.accounts.models import SsoConnection
from apps.accounts.services import update_sso_connection
from apps.accounts.tests.conftest import provider_landed
from apps.core.actor import Actor
from apps.workflows.models import WorkflowRun

pytestmark = pytest.mark.django_db


def _runs(connection: SsoConnection) -> int:
    return WorkflowRun.objects.filter(workflow_id__contains=str(connection.pk)).count()


def test_enforce_release_enforce_is_three_runs_while_none_has_finished(
    owner_actor: Actor, sso_connection: SsoConnection
) -> None:
    connection = provider_landed(sso_connection)
    before = _runs(connection)
    for enforced in (True, False, True):
        connection = update_sso_connection(
            tenant=connection.tenant,
            actor=owner_actor,
            connection=provider_landed(connection),
            enforced=enforced,
        )
    assert _runs(connection) - before == 3


def test_a_write_that_changed_nothing_starts_no_run(
    owner_actor: Actor, sso_connection: SsoConnection
) -> None:
    connection = provider_landed(sso_connection)
    before = _runs(connection)
    update_sso_connection(
        tenant=connection.tenant, actor=owner_actor, connection=connection, name="Renamed"
    )
    assert _runs(connection) == before
