"""The field that keeps a secret a secret.

The load-bearing test here is `test_the_column_holds_ciphertext_not_the_token`:
it goes round the ORM entirely and reads the raw column with a cursor, because
a round-trip test alone would pass just as happily if the field stored the
plaintext and did nothing at all.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection as db_connection

from apps.connections.models import Connection, EncryptedJSONField, encryption_keys, fernet
from apps.connections.services import create_connection
from apps.core.actor import Actor
from apps.core.models import Tenant

pytestmark = pytest.mark.django_db

SECRET = {
    "access_token": "sk-live-do-not-log-me",  # pragma: allowlist secret
    "webhook_secret": "shhh",  # pragma: allowlist secret
}


def _raw_column(connection_id: object) -> str:
    """The credentials column exactly as Postgres holds it."""
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT credentials FROM connections_connection WHERE id = %s", [str(connection_id)]
        )
        row = cursor.fetchone()
    return str(row[0])


def test_credentials_survive_a_round_trip(tenant: Tenant, owner_actor: Actor) -> None:
    created = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Round trip", credentials=SECRET
    )
    reloaded = Connection.objects.for_tenant(tenant).get(pk=created.pk)
    assert reloaded.credentials == SECRET
    assert reloaded.access_token == SECRET["access_token"]
    assert reloaded.webhook_secret == SECRET["webhook_secret"]


def test_the_column_holds_ciphertext_not_the_token(tenant: Tenant, owner_actor: Actor) -> None:
    """The property, read past the ORM: the database never sees the token."""
    created = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Opaque", credentials=SECRET
    )
    stored = _raw_column(created.pk)

    assert "sk-live-do-not-log-me" not in stored
    assert "shhh" not in stored
    assert "access_token" not in stored
    # A Fernet token, which is what "encrypted" means here rather than "encoded".
    assert stored.startswith("gAAAAA")
    assert json.loads(fernet().decrypt(stored.encode("ascii")).decode()) == SECRET


def test_an_empty_credential_set_is_still_ciphertext(tenant: Tenant, owner_actor: Actor) -> None:
    created = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Empty", credentials={}
    )
    assert Connection.objects.for_tenant(tenant).get(pk=created.pk).credentials == {}
    assert _raw_column(created.pk).startswith("gAAAAA")


def test_without_a_key_the_field_refuses_rather_than_storing_plaintext(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    """No key is a refusal, not a fallback. This is the whole reason for the field."""
    settings.CONNECTIONS_ENCRYPTION_KEY = ""

    assert encryption_keys() == []
    with pytest.raises(ImproperlyConfigured) as refusal:
        create_connection(
            tenant=tenant, actor=owner_actor, provider="example", name="No key", credentials=SECRET
        )
    assert "CONNECTIONS_ENCRYPTION_KEY" in str(refusal.value)
    assert not Connection.objects.for_tenant(tenant).exists()


def test_a_nonsense_key_is_refused_at_use_rather_than_ignored(
    settings: Any,
) -> None:
    settings.CONNECTIONS_ENCRYPTION_KEY = "not-a-fernet-key"
    with pytest.raises(ImproperlyConfigured):
        fernet()


def test_rotation_reads_with_the_old_key_and_writes_with_the_new(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    """Deploy `NEW,OLD`, re-save, deploy `NEW` — the middle step, proven."""
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    settings.CONNECTIONS_ENCRYPTION_KEY = old_key
    created = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Rotating", credentials=SECRET
    )
    written_under_old = _raw_column(created.pk)

    settings.CONNECTIONS_ENCRYPTION_KEY = f"{new_key},{old_key}"
    reloaded = Connection.objects.for_tenant(tenant).get(pk=created.pk)
    assert reloaded.credentials == SECRET, "the old key must still decrypt during the overlap"

    reloaded.save(update_fields=["credentials", "updated_at"])
    written_under_new = _raw_column(created.pk)
    assert written_under_new != written_under_old

    settings.CONNECTIONS_ENCRYPTION_KEY = new_key
    assert Connection.objects.for_tenant(tenant).get(pk=created.pk).credentials == SECRET


def test_a_row_encrypted_under_a_retired_key_fails_loudly(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    """The third deploy's failure mode: visible, not a silent empty mapping."""
    settings.CONNECTIONS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    created = create_connection(
        tenant=tenant, actor=owner_actor, provider="example", name="Missed", credentials=SECRET
    )

    settings.CONNECTIONS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(ValidationError):
        Connection.objects.for_tenant(tenant).get(pk=created.pk)


def test_the_field_cannot_be_talked_into_returning_plaintext() -> None:
    """`to_python` is the other door into the field, and it decrypts too."""
    field = EncryptedJSONField()
    token = str(field.get_prep_value({"a": 1}))
    assert field.to_python(token) == {"a": 1}
    assert field.to_python({"a": 1}) == {"a": 1}
    with pytest.raises(ValidationError):
        field.to_python("plainly-not-a-token")
