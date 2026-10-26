"""One user and one token per load client (the auth throttle keys on the user), via shell."""

import os
import secrets

from apps.accounts.models import User
from apps.accounts.services import create_user, issue_token
from apps.core.actor import system_actor
from apps.core.authz import OWNER_ROLE
from apps.core.models import Membership, Tenant
from apps.core.services import add_membership

slugs = os.environ["ENVELOPE_SLUGS"].split(",")
# The socket probe names its own users (`realtime-probe`), apart from the drive's.
prefix = os.environ.get("ENVELOPE_PREFIX", "load-client")
for n in range(int(os.environ["ENVELOPE_CLIENTS"])):
    tenant = Tenant.objects.get(slug=slugs[n % len(slugs)])
    email = f"{prefix}-{n}@example.invalid"
    user = User.objects.filter(email=email).first() or create_user(
        email=email, password=secrets.token_urlsafe(24)
    )
    if not Membership.objects.filter(user_id=user.pk, tenant=tenant).exists():
        add_membership(
            user=user,
            tenant=tenant,
            is_default=True,
            role=OWNER_ROLE,
            actor=system_actor(tenant=tenant),
        )
    _token, plaintext = issue_token(
        user=user,
        tenant=tenant,
        name=f"{prefix}-{n}-{secrets.token_hex(3)}",
        actor=system_actor(tenant=tenant),
        scopes=["*"],
    )
    print(f"CRED\t{tenant.slug}\t{plaintext}")
