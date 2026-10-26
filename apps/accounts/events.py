"""The names of the things this app says happened.

Names only, in the house grammar (`<app>.<noun>.<past-tense verb>`, house rule
16): an event name is a published contract a webhook subscriber matches on, so
it has one definition here and never a literal at a call site. `introspect`
reports this file.
"""

from __future__ import annotations

#: A tenant's people now have a realm of their own to sign in at — said once
#: when the realm first lands, and again only if the tenant is given a new one.
IDENTITY_HOME_CREATED = "accounts.identity_home.created"

#: The auth-failure spike over the log key `signin.py` writes at every refusal (alerts census).
SPIKES: tuple[dict[str, str | int], ...] = (
    {
        "key": "accounts.signin.refused",
        "threshold": 20,
        "window": "5m",
        "reason": (
            "twenty refused sign-ins in five minutes is a credential-stuffing shape; "
            "signin.py logs this key at every refusal"
        ),
    },
)
