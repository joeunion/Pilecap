"""The wire shapes for accounts. Pydantic, so every door speaks the same one.

`TokenIssuedOut` is the only schema in this repository that carries a secret,
and it exists exactly once in the life of a token: the response to the request
that minted it. Nothing reads it back — only the SHA-256 is stored — so a
client that does not keep this response has lost the token and mints another.

The SSO schemas below have the opposite property and it is worth stating out
loud: **`SsoConnectionOut` has no field for the client secret**, and there is no
route anywhere that returns one. A secret goes in through `SsoConnectionIn` and
never comes back; `has_client_secret` is the whole of what any door will say
about it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import ConfigDict, Field

from apps.core.schemas import StrictIn, example


class UserOut(Schema):
    """A person, as the deactivation and erasure doors hand them back.

    **What is not here is the point.** `is_superuser` is the deployment's own
    business and no tenant's; `zitadel_sub` is the identity platform's subject
    and naming it over the wire would hand a caller the key to somebody's
    account on it; `password` is a hash and there is no door in this repository
    that returns one.

    `email` **is** here, and it is what makes an erasure legible: the address
    that comes back from `POST /users/{id}/erase` is the anonymised
    `erased+<uuid>@invalid` one, which is the caller's evidence that the act
    landed rather than a copy of the person who used to be there.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str = Field(
        description="After an erasure this is the anonymised `erased+<uuid>@invalid` form.",
        json_schema_extra=example("dana@example.com"),
    )
    is_active: bool = Field(description="False once the person is deactivated or erased.")
    is_staff: bool = Field(description="Django admin access. An erasure always drops it.")
    date_joined: datetime
    created_at: datetime
    updated_at: datetime


class TokenIn(StrictIn):
    """What a client may send. The user and tenant come from the request."""

    name: str = Field(
        min_length=1,
        max_length=200,
        description="How you will recognise it later.",
        json_schema_extra=example("nightly export"),
    )
    scopes: list[str] | None = Field(
        default=None,
        description=(
            "What this token is allowed to reach, as a list of `section:read` "
            'and `section:write` names — or the single entry "*" for a token '
            "with no limit at all. There is no default: a token you are about "
            "to hand to somebody else's software should be as narrow as the "
            "job needs, so saying nothing is refused rather than read as "
            '"everything". Within a section the write scope includes the read, '
            "so `section:write` on its own is enough to both read and change "
            "that section."
        ),
        json_schema_extra=example(["widgets:read", "widgets:write"]),
    )


class TokenOut(Schema):
    """A token as it can be shown again: everything except the secret."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str = Field(json_schema_extra=example("nightly export"))
    tenant_id: UUID | None
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None
    scopes: list[str] | None = Field(
        default=None,
        description=(
            "What this token is allowed to reach. `null` means no limit: it "
            "can do whatever the person who minted it can."
        ),
        json_schema_extra=example(["widgets:read", "widgets:write"]),
    )


class TokenIssuedOut(TokenOut):
    """The one response that carries the plaintext, and the only time it exists."""

    token: str = Field(
        description="The bearer token. Shown once; it is never recoverable.",
        json_schema_extra=example("djb_3Qn7xKfP2mV8sT1wL5yR9cB4hJ6dG0aZ"),
    )
    effective_scopes: list[str] | None = Field(
        default=None,
        description=(
            "Which of the scopes you asked for your role can back today. A "
            "scope you asked for that is missing here is mostly dead weight: "
            "the token carries it and your role refuses underneath anyway. It "
            "is a guide computed from your role, not a promise about every "
            "call — an individual operation can still refuse for a reason "
            "about the record rather than about you. `null` for a token with "
            "no limit."
        ),
        json_schema_extra=example(["widgets:read"]),
    )


# --- Home-realm discovery -----------------------------------------------------


class RealmIn(StrictIn):
    """An address typed into a login box by nobody in particular."""

    email: str = Field(
        min_length=3,
        max_length=320,
        description="The address the person is about to sign in with.",
    )


class RealmOut(Schema):
    """Where that address signs in — and nothing else about it.

    **`method` is `sso` for every address** (ADR ident-6, W2-R5). Zitadel hosts
    every interactive authentication now, including the passwords of local
    users, so there is one door and the question "which door" has one answer.
    `authorize_url` is always populated and always points at that door;
    `connection_id` is present only when a live customer connection claims the
    address's domain, in which case the URL also carries an opaque hint that
    skips Zitadel's provider picker.

    **The shape is unchanged and `password` stays in the vocabulary**, so a
    client written against the previous contract still compiles and a product
    that reopens a local password door has the word waiting for it.

    **Everything a caller can learn from this is nothing.** No tenant name, no
    slug, no connection name, no indication of whether an account exists, and no
    difference between "that domain has no SSO", "that customer's connection is
    disabled" and "we have never seen that domain" — all three are byte-
    identical. A login form has to answer *something*, and the answer must not
    be enumerable into a customer list.
    """

    method: Literal["sso", "password"]
    connection_id: UUID | None = None
    authorize_url: str = ""


# --- SSO connections ----------------------------------------------------------


class SsoConnectionIn(StrictIn):
    """What an owner or admin sends to set their identity provider up."""

    name: str = Field(min_length=1, max_length=200, description="How you will recognise it.")
    issuer: str = Field(
        min_length=1,
        max_length=500,
        description="The OpenID Connect issuer URL, as the IdP publishes it.",
    )
    client_id: str = Field(min_length=1, max_length=500)
    client_secret: str = Field(
        min_length=1,
        max_length=500,
        description="Stored encrypted. It is never returned by any route.",
    )
    email_domains: list[str] = Field(
        min_length=1,
        description="The email domains this provider owns, like acme.com. Unique across "
        "every tenant: one domain routes to exactly one identity provider.",
    )
    protocol: Literal["oidc"] = Field(
        default="oidc",
        description="OpenID Connect. SAML is a recorded escalation and is refused.",
    )
    default_role: Literal["owner", "admin", "member"] = Field(
        default="member",
        description="The role a person provisioned by this connection joins at. It is "
        "applied to new memberships only and never changes an existing one.",
    )
    enforced: bool = Field(
        default=False,
        description="When true, people in these domains may not sign in with a password.",
    )


class SsoConnectionPatch(StrictIn):
    """A change to a connection. Every field is optional; omitted means unchanged.

    An omitted or empty `client_secret` means "leave the stored one alone" — the
    only thing it can mean, since nothing can read it back to re-send it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=200)
    issuer: str | None = Field(default=None, max_length=500)
    client_id: str | None = Field(default=None, max_length=500)
    client_secret: str | None = Field(default=None, max_length=500)
    email_domains: list[str] | None = Field(default=None, min_length=1)
    default_role: Literal["owner", "admin", "member"] | None = None
    enforced: bool | None = None


class SsoConnectionOut(Schema):
    """A connection as any door may show it. No secret, at any depth."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    protocol: str
    status: str
    issuer: str
    client_id: str
    has_client_secret: bool
    email_domains: list[str]
    default_role: str
    enforced: bool
    created_at: datetime
    updated_at: datetime
    disabled_at: datetime | None
