"""`WebhookEndpoint.secret` stops being plaintext in the column (rung W6).

A MEDIUM finding: the one recoverable credential in a tree whose doctrine says
encrypted-at-rest, sitting beside `Connection.credentials`, which has been
encrypted since the day that app landed. The contract does not change — a
`str` goes in and a `str` comes out — only the storage does.

**Expand/contract inside one leaf** (house rule 22), in the order that leaves
no window where a row cannot be read:

1. `AlterField` widens `varchar(255)` to `text`. Postgres does this without
   rewriting the table, and every existing value is still valid text, so the
   column is readable throughout.
2. `RunPython` re-encrypts what is already there, **through raw SQL rather than
   the historical model**. That is the load-bearing detail: after step 1 the
   historical model's `secret` is an `EncryptedCharField`, so reading a row
   through the ORM would try to decrypt plaintext and raise. The cursor sees
   the column as the database holds it, which is exactly what a data migration
   over a changing encoding needs.

The reverse is real and is tested by running it (`migrate events 0001`):
it decrypts every row back to plaintext and narrows the column, so a
deployment that has to roll back gets readable secrets rather than a table of
tokens it no longer has code to open. Which is also the honest statement of
what a rollback costs: the secrets are plaintext again.
"""

from __future__ import annotations

from typing import Any

import apps.core.fields
from django.db import migrations

from apps.core.fields import fernet

TABLE = "events_webhookendpoint"


def _rewrite(schema_editor: Any, transform: Any) -> None:
    """Walk the column, applying `transform` to every non-empty secret.

    **The cipher is fetched only if there is something to transform**, and that
    is deliberate rather than lazy-for-its-own-sake: `fernet()` refuses to guess
    when `CONNECTIONS_ENCRYPTION_KEY` is unset, so demanding it up front would
    make a *fresh* deployment — one with no endpoints yet, which is every new
    product — unable to run its own first migration. A deployment that actually
    holds secrets is still told, loudly, on the row it cannot convert.
    """
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"SELECT id, secret FROM {TABLE}")  # noqa: S608 - constant table name
        rows = [(pk, secret) for pk, secret in cursor.fetchall() if secret]
        if not rows:
            return
        cipher = fernet()
        for pk, secret in rows:
            cursor.execute(
                f"UPDATE {TABLE} SET secret = %s WHERE id = %s",  # noqa: S608
                [transform(cipher, str(secret)), pk],
            )


def encrypt_secrets(apps: Any, schema_editor: Any) -> None:
    """Plaintext in the column becomes ciphertext."""
    _rewrite(
        schema_editor,
        lambda cipher, secret: cipher.encrypt(secret.encode("utf-8")).decode("ascii"),
    )


def decrypt_secrets(apps: Any, schema_editor: Any) -> None:
    """The reverse: ciphertext back to the plaintext a rolled-back build reads."""
    _rewrite(
        schema_editor,
        lambda cipher, secret: cipher.decrypt(secret.encode("ascii")).decode("utf-8"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("events", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="webhookendpoint",
            name="secret",
            field=apps.core.fields.EncryptedCharField(max_length=255),
        ),
        migrations.RunPython(encrypt_secrets, decrypt_secrets),
    ]
