"""Field primitives every app builds on. Today: the two that keep a secret.

`core` owns primitives, so the encryption a product's rows need lives here
rather than in whichever app happened to need it first. `apps.connections`
introduced `EncryptedJSONField` for per-tenant credentials; `apps.accounts`
needs the identical thing for an identity provider's client secret. Two copies
of a cipher are two things to rotate and one to forget, so there is one.

**The setting is still `CONNECTIONS_ENCRYPTION_KEY`**, and deliberately: it is
already in `.env.example`, already refused-by-value in
`config.settings.guards`, and already set in every deployment that exists.
Renaming an environment variable to tidy a module name is a change every
operator has to make for no benefit. One key, one rotation procedure, one name.

Two field types, one cipher: `EncryptedJSONField` for a credential that is a
mapping (a connection's whole credential blob), `EncryptedCharField` for one
that is a single string (a webhook's signing secret, an identity provider's
client secret). Which one a column takes is a question about the value's shape
and never about how much protection it deserves — both get the same.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import models

_fernet_cache: dict[str, MultiFernet] = {}


def encryption_keys() -> list[str]:
    """The configured Fernet keys, newest first. Empty when none is configured."""
    raw = str(getattr(settings, "CONNECTIONS_ENCRYPTION_KEY", "") or "")
    return [key.strip() for key in raw.split(",") if key.strip()]


def fernet() -> MultiFernet:
    """The cipher, or a refusal to start guessing.

    **Key rotation.** `CONNECTIONS_ENCRYPTION_KEY` is a comma-separated list and
    the order is the whole protocol: the **first** key encrypts, and **every**
    key decrypts (`MultiFernet`). Rotating is therefore three deploys, not one:

    1. deploy `NEW,OLD` — new writes use `NEW`, old rows still decrypt;
    2. re-save every encrypted row (a data migration, or a management command
       calling the service that owns the row) so each is re-encrypted under
       `NEW`;
    3. deploy `NEW` alone, which is also the moment a row that was missed starts
       failing loudly instead of quietly reading with a key you meant to retire.

    A missing key is `ImproperlyConfigured`, never a fallback to plaintext: a
    product that boots without the key and silently stores readable secrets is
    the failure this whole field exists to prevent, and it would not be noticed
    until it mattered.
    """
    keys = encryption_keys()
    if not keys:
        raise ImproperlyConfigured(
            "CONNECTIONS_ENCRYPTION_KEY is not set, and this product stores "
            "credentials encrypted. Generate one with "
            "`python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'` and put it in the environment. "
            "There is deliberately no plaintext fallback."
        )
    cache_key = ",".join(keys)
    cipher = _fernet_cache.get(cache_key)
    if cipher is None:
        try:
            cipher = MultiFernet([Fernet(key.encode()) for key in keys])
        except (ValueError, TypeError) as exc:
            raise ImproperlyConfigured(
                "CONNECTIONS_ENCRYPTION_KEY is not a valid Fernet key (or "
                "comma-separated list of them)."
            ) from exc
        _fernet_cache[cache_key] = cipher
    return cipher


class EncryptedJSONField(models.TextField[Any, Any]):
    """A JSON value that is ciphertext everywhere except in Python.

    Stored as a `TextField` rather than `jsonb` on purpose: the ciphertext is
    opaque, so there is nothing for Postgres to index, query or validate, and a
    `jsonb` column would only advertise a structure the database cannot see.

    The cost is stated rather than hidden: **you cannot filter on this column.**
    Anything a query needs to narrow by — a provider, a status, a claimed email
    domain — is a column or a row beside it, never a key inside it.
    """

    if TYPE_CHECKING:
        # django-stubs derives a model's `__init__` signature and its attribute
        # types from these two on the field class. `TextField`'s say `str`,
        # which is true of the *column* and false of the value every caller
        # touches — so `metadata={"a": 1}` in a service would be a type error
        # for storing exactly what this field exists to store.
        _pyi_private_set_type: Any
        _pyi_private_get_type: Any

    def get_internal_type(self) -> str:
        return "TextField"

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        """Ciphertext from the column back into the mapping the caller wrote."""
        if value is None:
            return None
        if value == "":
            return {}
        return self._decrypt(str(value))

    def to_python(self, value: Any) -> Any:
        """Accept what Python already has; decrypt what a serializer hands back."""
        if value is None or not isinstance(value, str):
            return value
        if value == "":
            return {}
        return self._decrypt(value)

    def get_prep_value(self, value: Any) -> Any:
        if value is None:
            return None
        return fernet().encrypt(json.dumps(value, sort_keys=True).encode("utf-8")).decode("ascii")

    def value_to_string(self, obj: Any) -> str:
        """`dumpdata` gets the ciphertext, because a fixture is a file on a disk."""
        prepared = self.get_prep_value(self.value_from_object(obj))
        return "" if prepared is None else str(prepared)

    @staticmethod
    def _decrypt(token: str) -> Any:
        try:
            plain = fernet().decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            # Deliberately says nothing about the value. A message that quoted
            # the token, or distinguished "wrong key" from "corrupt row", would
            # be an oracle in whatever log it landed in.
            raise ValidationError(
                "This value could not be decrypted with the configured CONNECTIONS_ENCRYPTION_KEY."
            ) from exc
        return json.loads(plain.decode("utf-8"))


class EncryptedCharField(models.TextField[Any, Any]):
    """A short string that is ciphertext everywhere except in Python.

    `EncryptedJSONField`'s sibling, sharing its keys, its cipher, its rotation
    procedure and its threat model — a `pg_dump` handed to a contractor, a
    replica in the wrong region, a `SELECT *` in a support query, an ORM
    traceback in a log aggregator. The difference is only the shape of the
    value: a credential that is **one string** rather than a mapping does not
    become a mapping just so it can be encrypted, and `{"secret": "..."}` in
    the column would be a wrapper every reader has to unwrap.

    **A `TextField` column, not a sized `varchar`, and the reason is arithmetic
    rather than taste.** Fernet output is base64 over a 57-byte header-and-MAC
    envelope plus the AES-CBC padded plaintext, so ciphertext runs roughly
    `4/3 * (plaintext + 73)` characters — a 255-character secret needs about
    440. Sizing a `varchar` for that means every caller of this field guessing
    the same arithmetic, and getting it wrong means a `DataError` on the one
    write that mattered. The column is unbounded; the **plaintext** bound is
    kept where it belongs, as `max_length` on the field, which Django applies
    as a validator and not as DDL.

    The cost is the same one the JSON sibling states out loud: **you cannot
    filter on this column.** Two rows holding the same secret hold different
    ciphertext (Fernet carries a random IV), so `.filter(secret=...)` matches
    nothing, ever. A secret is checked by reading the row you already resolved
    and comparing in Python — which is what `hmac.compare_digest` is for.
    """

    def get_internal_type(self) -> str:
        return "TextField"

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Any:
        """Ciphertext from the column back into the string the caller wrote."""
        if value is None:
            return None
        if value == "":
            return ""
        return self._decrypt(str(value))

    def to_python(self, value: Any) -> Any:
        """Accept what Python already has; decrypt what a serializer hands back.

        **The one place in this field that tolerates ambiguity, and it has to.**
        The JSON sibling can tell the two apart by type — its Python value is a
        mapping and its stored form is a `str` — but a *string* field's plaintext
        and its ciphertext are both `str`, and this method is reached from both
        directions: `full_clean()` hands it the plaintext a service just
        assigned, and `loaddata` hands it the ciphertext `value_to_string` wrote.
        So it opens what it can and passes through what it cannot.

        That fallback is **not** a plaintext fallback in the sense the module
        docstring forbids, and the difference is which method the database read
        goes through: rows come back via `from_db_value`, which decrypts and
        **raises**. A row encrypted under a retired key still fails loudly on
        every read; what this tolerates is only a caller assigning the value
        that was never in the column to begin with.
        """
        if value is None or not isinstance(value, str) or value == "":
            return value
        try:
            return self._decrypt(value)
        except ValidationError:
            return value

    def get_prep_value(self, value: Any) -> Any:
        if value is None:
            return None
        text = str(value)
        # An empty secret stays empty rather than becoming a ciphertext blob
        # that decrypts to nothing. "No secret configured" is a state readers
        # test with `if not secret`, and it must not cost a decrypt to answer.
        if text == "":
            return ""
        return fernet().encrypt(text.encode("utf-8")).decode("ascii")

    def value_to_string(self, obj: Any) -> str:
        """`dumpdata` gets the ciphertext, because a fixture is a file on a disk."""
        prepared = self.get_prep_value(self.value_from_object(obj))
        return "" if prepared is None else str(prepared)

    @staticmethod
    def _decrypt(token: str) -> str:
        try:
            plain = fernet().decrypt(token.encode("ascii"))
        except InvalidToken as exc:
            # Says nothing about the value, for the reason the sibling gives:
            # a message that quoted the token, or distinguished "wrong key"
            # from "corrupt row", would be an oracle in whatever log it
            # landed in.
            raise ValidationError(
                "This value could not be decrypted with the configured CONNECTIONS_ENCRYPTION_KEY."
            ) from exc
        return plain.decode("utf-8")
