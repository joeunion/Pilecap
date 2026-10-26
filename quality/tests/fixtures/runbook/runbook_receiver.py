"""The live receiver `quality/tests/test_runbook.py` drives the runbook at."""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
import uuid

# `manage.py` gets the checkout root for free by living in it; a module four
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[4]))

# Before `django.setup()`, and both for the same reason: a harness whose
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
os.environ["EMAIL_BACKEND"] = "django.core.mail.backends.console.EmailBackend"

import django  # noqa: E402
import pytest  # noqa: E402

django.setup()

from django.core.handlers.wsgi import WSGIHandler  # noqa: E402
from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler  # noqa: E402

from apps.accounts.services import create_user, issue_token  # noqa: E402
from apps.comms import services as comms  # noqa: E402
from apps.comms.models import Message, MessageEngagement  # noqa: E402
from apps.connections.models import Connection  # noqa: E402
from apps.connections.tests.handler_runs import run_handlers_at_the_receipt  # noqa: E402
from apps.core import context  # noqa: E402
from apps.core.actor import actor_for, system_actor  # noqa: E402
from apps.core.models import Membership, Tenant  # noqa: E402
from apps.core.services import add_membership, create_tenant, root_organization  # noqa: E402

#: The tenant every run of this harness works in. One slug, reused: the drive
SLUG = "runbook-drive"
PASSWORD = "runbook-drive-password"  # noqa: S105 — a scratch database's per-run password  # pragma: allowlist secret — a scratch database, per run
OWNER = "owner@runbook.invalid"
TEMPLATE = "runbook-receipt"

#: The two handles the recipes post back. Fixed rather than random for the
HANDLE_V2 = "runbook-handle-v2"
HANDLE_LEGACY = "runbook-handle-legacy"


def _seed() -> dict[str, str]:
    """Every row a deployment would already have, made through the services."""
    tenant = Tenant.objects.filter(slug=SLUG).first()
    if tenant is None:
        tenant = create_tenant(name="Runbook Drive", slug=SLUG, actor=system_actor())

    from apps.accounts.models import User

    owner = User.objects.filter(email=OWNER).first()
    if owner is None:
        owner = create_user(email=OWNER, password=PASSWORD)
    if not Membership.objects.filter(user_id=owner.pk, tenant=tenant).exists():
        add_membership(
            user=owner,
            tenant=tenant,
            is_default=True,
            role=Membership.Role.OWNER,
            actor=system_actor(tenant=tenant),
        )

    root = root_organization(tenant=tenant)
    actor = actor_for(user=owner, tenant=tenant, org=root)

    # No ceiling, said out loud: recipe 1 posts to `/connections/` and this
    _token, plaintext = issue_token(
        user=owner,
        tenant=tenant,
        name=f"runbook-drive-{uuid.uuid4().hex[:8]}",
        scopes=["*"],
        actor=actor_for(user=owner, tenant=tenant),
    )

    recipient = comms.create_recipient(
        tenant=tenant,
        actor=actor,
        email="reader@runbook.invalid",
        display_name="A reader",
    )
    comms.grant_consent(tenant=tenant, actor=actor, recipient=recipient)

    from apps.comms.models import MessageTemplate

    if not MessageTemplate.objects.for_tenant(tenant).filter(name=TEMPLATE).exists():
        comms.create_template(
            tenant=tenant,
            actor=actor,
            name=TEMPLATE,
            subject="Your receipt",
            body="Hello {{ name }}.",
            context_schema={"required": ["name"], "properties": {"name": {"type": "string"}}},
        )

    for handle in (HANDLE_V2, HANDLE_LEGACY):
        if Message.objects.for_tenant(tenant).filter(provider_message_id=handle).exists():
            continue
        queued = comms.send(
            recipient=recipient,
            template=TEMPLATE,
            context={"name": "A reader"},
            channel="email",
            tenant=tenant,
            actor=actor,
        )
        comms.record_message_sent(
            tenant=tenant,
            actor=actor,
            message=queued,
            provider="runbook-drive",
            provider_message_id=handle,
        )

    return {"TENANT": SLUG, "TOKEN": plaintext}


def _serve(env_path: str) -> None:
    """Listen, then say where — in shell, so the drive can `.` the file."""
    # A process with no door binds the chain a door would —
    with context.bound(
        request_id=context.new_id(),
        correlation_id=context.new_correlation_id(),
        actor_kind="system",
        door="shell",
        command="runbook_receiver",
    ):
        seeded = _seed()

    # Port 0: the kernel picks a free one. A fixed port is how a drive ends up
    httpd = ThreadedWSGIServer(("127.0.0.1", 0), WSGIRequestHandler, allow_reuse_address=False)
    httpd.set_app(WSGIHandler())
    # The world serves with no worker: the claimed handler's run is done at the receipt.
    run_handlers_at_the_receipt(pytest.MonkeyPatch())
    host, port = httpd.server_address[0], httpd.server_address[1]

    with open(env_path, "w", encoding="utf-8") as handle:
        handle.write(f"HOST={host}:{port}\n")
        handle.write(f"TOKEN={seeded['TOKEN']}\n")
        handle.write(f"TENANT={seeded['TENANT']}\n")
        handle.write(f"HANDLE_V2={HANDLE_V2}\n")
        handle.write(f"HANDLE_LEGACY={HANDLE_LEGACY}\n")
        handle.write("RECEIVER_READY=1\n")

    httpd.serve_forever()


def _facts() -> None:
    """Everything the drive asks about, one fact per line, in the drive's grammar."""
    tenant = Tenant.objects.filter(slug=SLUG).first()
    if tenant is None:
        print("no-tenant")
        return

    for connection in Connection.objects.for_tenant(tenant).order_by("created_at"):
        secret = connection.webhook_secret or ""
        digest = hashlib.sha256(secret.encode()).hexdigest()[:16] if secret else "-"
        print(f"connection {connection.pk} {connection.provider} {connection.name} {digest}")

    for message in Message.objects.for_tenant(tenant).order_by("created_at"):
        print(f"message {message.provider_message_id or '-'} {message.status}")

    engagements = MessageEngagement.objects.for_tenant(tenant).select_related("message")
    for engagement in engagements.order_by("created_at"):
        handle = engagement.message.provider_message_id or "-"
        print(f"engagement {handle} {engagement.kind} {engagement.url or '-'}")


def _world() -> None:
    """Where this harness's work lands, in shell, so the drive can `.` the output."""
    from django.conf import settings

    print(f"DRIVE_QUEUE={settings.TEMPORAL_TASK_QUEUE}")
    print(f"DRIVE_SLUG={SLUG}")


def _digest(value: str) -> None:
    """The same sha256 prefix `facts` prints, for a secret the drive holds."""
    print(hashlib.sha256(value.encode()).hexdigest()[:16])


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "serve":
        _serve(argv[2])
        return 0
    if len(argv) == 2 and argv[1] == "facts":
        _facts()
        return 0
    if len(argv) == 2 and argv[1] == "world":
        _world()
        return 0
    if len(argv) == 3 and argv[1] == "digest":
        _digest(argv[2])
        return 0
    print(__doc__ or "", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
