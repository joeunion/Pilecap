"""`WebhookEndpoint.secret` is ciphertext in the column.

The load-bearing test is `test_the_column_holds_ciphertext_not_the_secret`: it
goes round the ORM entirely and reads the raw column with a cursor, because a
round-trip test alone would pass just as happily if the field stored the
plaintext and did nothing at all. That is the same reason
`apps/connections/tests/test_models.py` exists for the JSON sibling, and these
are deliberately its mirror — one cipher, one set of properties, proven twice
because two field types can drift.

**Where these live is the convention, not an accident.** `EncryptedCharField`
is `apps.core.fields`', like every field primitive; the tests sit in the app
whose column actually uses it, exactly as the JSON field's sit in
`apps/connections`. A primitive is proved through a real row of a real model,
never in the abstract.
"""

from __future__ import annotations

from typing import Any

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import connection as db_connection

from apps.core.actor import Actor
from apps.core.fields import EncryptedCharField
from apps.core.models import Tenant
from apps.events import services
from apps.events.models import WebhookEndpoint

pytestmark = pytest.mark.django_db

# A literal, not a credential: it is compared against itself and never leaves
# the test database. Marked at the site rather than in `.secrets.baseline` so
# the justification travels with the line — and so two worktrees adding
# fixtures do not collide on one generated file.
SECRET = "sk-live-do-not-log-me-9f3a"  # noqa: S105 — a fake secret the test proves never reaches a log  # pragma: allowlist secret


def _raw_column(endpoint_id: object) -> str:
    """The secret column exactly as Postgres holds it."""
    with db_connection.cursor() as cursor:
        cursor.execute(
            "SELECT secret FROM events_webhookendpoint WHERE id = %s", [str(endpoint_id)]
        )
        row = cursor.fetchone()
    return str(row[0])


def _endpoint(tenant: Tenant, actor: Actor, *, url: str, secret: str = SECRET) -> WebhookEndpoint:
    return services.register_endpoint(tenant=tenant, actor=actor, url=url, secret=secret)


def test_the_secret_survives_a_round_trip(tenant: Tenant, owner_actor: Actor) -> None:
    created = _endpoint(tenant, owner_actor, url="https://subscriber.example/a")
    assert WebhookEndpoint.objects.for_tenant(tenant).get(pk=created.pk).secret == SECRET


def test_the_column_holds_ciphertext_not_the_secret(tenant: Tenant, owner_actor: Actor) -> None:
    """What a `pg_dump` handed to a contractor actually contains.

    Read with a cursor, so no field converter can flatter the result.
    """
    created = _endpoint(tenant, owner_actor, url="https://subscriber.example/b")
    raw = _raw_column(created.pk)

    assert SECRET not in raw
    assert raw.startswith("gAAAAA"), "a Fernet token, version byte and all"
    assert len(raw) > len(SECRET), "ciphertext carries an IV and a MAC"


def test_an_empty_secret_stays_empty_rather_than_becoming_a_token(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """An unset secret is a state, and answering it must not cost a decrypt.

    `apps.events.receivers.signature_matches` refuses on a falsy secret — that is
    what makes a revoked connection stop accepting deliveries — and the same
    reading has to survive encryption.
    """
    endpoint = WebhookEndpoint.objects.create(
        tenant=tenant, url="https://subscriber.example/empty", secret=""
    )
    assert _raw_column(endpoint.pk) == ""
    assert WebhookEndpoint.objects.for_tenant(tenant).get(pk=endpoint.pk).secret == ""


def test_two_endpoints_with_one_secret_hold_different_ciphertext(
    tenant: Tenant, owner_actor: Actor
) -> None:
    """Fernet carries a random IV, which is why this column cannot be filtered on.

    Stated as a test rather than only in a docstring: somebody will eventually
    reach for `.filter(secret=...)`, and this is the row of evidence that says
    it would have matched nothing.
    """
    one = _endpoint(tenant, owner_actor, url="https://subscriber.example/one")
    two = _endpoint(tenant, owner_actor, url="https://subscriber.example/two")

    assert _raw_column(one.pk) != _raw_column(two.pk)
    assert not WebhookEndpoint.objects.for_tenant(tenant).filter(secret=SECRET).exists()


def test_without_a_key_the_field_refuses_rather_than_storing_plaintext(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    """There is deliberately no plaintext fallback, for the char field either."""
    settings.CONNECTIONS_ENCRYPTION_KEY = ""
    with pytest.raises(ImproperlyConfigured):
        _endpoint(tenant, owner_actor, url="https://subscriber.example/keyless")


def test_rotation_reads_with_the_old_key_and_writes_with_the_new(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    """Deploy `NEW,OLD`, re-save, deploy `NEW` — the middle step, proven.

    The JSON sibling's property, re-proven for this field because a rotation
    that worked for one column and not the other would be discovered during the
    rotation.
    """
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    settings.CONNECTIONS_ENCRYPTION_KEY = old_key
    created = _endpoint(tenant, owner_actor, url="https://subscriber.example/rotating")
    written_under_old = _raw_column(created.pk)

    settings.CONNECTIONS_ENCRYPTION_KEY = f"{new_key},{old_key}"
    reloaded = WebhookEndpoint.objects.for_tenant(tenant).get(pk=created.pk)
    assert reloaded.secret == SECRET, "the old key must still decrypt during the overlap"

    reloaded.save(update_fields=["secret", "updated_at"])
    assert _raw_column(created.pk) != written_under_old

    settings.CONNECTIONS_ENCRYPTION_KEY = new_key
    assert WebhookEndpoint.objects.for_tenant(tenant).get(pk=created.pk).secret == SECRET


def test_a_row_encrypted_under_a_retired_key_fails_loudly(
    tenant: Tenant, owner_actor: Actor, settings: Any
) -> None:
    """The third deploy's failure mode: visible, not a silently empty secret.

    A silently-empty secret would be worse here than for the JSON sibling: an
    endpoint whose secret read as `""` would have every delivery signed with
    nothing, and a subscriber that verified would simply stop receiving.
    """
    settings.CONNECTIONS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    created = _endpoint(tenant, owner_actor, url="https://subscriber.example/missed")

    settings.CONNECTIONS_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with pytest.raises(ValidationError):
        WebhookEndpoint.objects.for_tenant(tenant).get(pk=created.pk)


def test_the_field_takes_plaintext_from_a_caller_and_ciphertext_from_a_fixture() -> None:
    """`to_python`'s two callers, and why it cannot simply always decrypt.

    `full_clean()` hands it the plaintext a service just assigned; `loaddata`
    hands it what `value_to_string` wrote. Both have to work, and a string
    field cannot tell them apart by type the way the JSON sibling can.
    """
    field = EncryptedCharField(max_length=255)
    token = str(field.get_prep_value(SECRET))

    assert token != SECRET
    assert field.to_python(token) == SECRET, "a fixture's ciphertext is opened"
    assert field.to_python(SECRET) == SECRET, "a caller's plaintext is left alone"
    assert field.to_python("") == ""
    assert field.to_python(None) is None


def test_the_database_read_path_never_falls_back_to_the_raw_value() -> None:
    """The tolerance in `to_python` must not reach `from_db_value`.

    This is the pin on the distinction the field's docstring draws: a row that
    cannot be decrypted is an incident, and answering it with the ciphertext —
    which a caller would then sign a webhook with — would turn a key mistake
    into deliveries nobody can verify.
    """
    field = EncryptedCharField(max_length=255)
    with pytest.raises(ValidationError):
        field.from_db_value("plainly-not-a-token", None, None)
