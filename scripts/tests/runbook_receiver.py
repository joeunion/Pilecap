"""The live receiver `scripts/tests/test_runbook_recipes.sh` drives the runbook at.

Not a test and not an instrument: it reports no verdict of its own and asserts
nothing. It is the WORLD the drive runs the runbook's printed recipes against —
a real HTTP server, on a real Postgres database, with the rows a deployment
would have — and a reader of what it says. Every assertion lives in the drive.

    uv run python scripts/tests/runbook_receiver.py serve <env-file>
    uv run python scripts/tests/runbook_receiver.py facts
    uv run python scripts/tests/runbook_receiver.py world

WHY A SERVER AND NOT THE TEST CLIENT. The recipes in `docs/runbooks/deploy.md`
are `curl` and `urllib.request` against a URL. Driving them through Django's
test client would mean rewriting them into something else, and a rewritten
recipe is the second copy the whole tooth exists to abolish — the recipe must
run AS PRINTED, which means something has to be listening on a socket.

WHAT IT SEEDS, and why each row is there:

  * a tenant, an owner and a membership     nothing reads without one;
  * a bearer token, no ceiling              the connection-create recipe posts
                                            with `Authorization: Bearer $TOKEN`;
  * a recipient with email consent          a bounce suppresses an address, and
                                            an address with no consent row would
                                            make `send()` refuse before we got
                                            anywhere near the receiver;
  * a transactional template                `send()` needs one;
  * two messages, each `record_message_sent`
    under a known provider handle           one per house scheme, so the two
                                            recipes never race for one row.

It does NOT create the connection. That is recipe 1's job, and the drive runs
recipe 1 to make it: the runbook's own three moves are the set-up.

EVERY WRITE GOES THROUGH A SERVICE (house rule 10). This file is a door like any
other command, so it gets the same authorization, the same audit rows and the
same refusals a route would. Nothing here calls `.create()`.

THE DATABASE IS THE CALLER'S. `DATABASE_NAME` is read from the environment (the
drive derives a scratch name and drops it afterwards) and this file neither
creates nor drops one; a checkout's own development database is never touched
unless a caller points this at it, which the drive does not do.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
import uuid

# `manage.py` gets the checkout root for free by living in it; a module two
# directories down does not, and `sys.path[0]` is `scripts/tests`. Inserted
# rather than appended so this checkout wins over anything else on the path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

# Before `django.setup()`, and both for the same reason: a harness whose
# behaviour depends on what the developer happens to have in `.env` is a harness
# that proves something different on every machine.
#
#   DJANGO_SETTINGS_MODULE  `local`, which is the settings a deployment-shaped
#                           run uses. `test` would give the suite's database
#                           name and its locmem mail.
#   EMAIL_BACKEND           the console backend, i.e. NO Anymail ESP. That is
#                           the fork the two house-scheme recipes live on: with
#                           no ESP the Svix verifier answers "no opinion" and the
#                           receiver's own HMAC stands, which is exactly the
#                           deployment the recipes are written for.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
os.environ["EMAIL_BACKEND"] = "django.core.mail.backends.console.EmailBackend"

import django  # noqa: E402

django.setup()

from django.core.handlers.wsgi import WSGIHandler  # noqa: E402
from django.core.servers.basehttp import ThreadedWSGIServer, WSGIRequestHandler  # noqa: E402

from apps.accounts.services import create_user, issue_token  # noqa: E402
from apps.comms import services as comms  # noqa: E402
from apps.comms.models import Message, MessageEngagement  # noqa: E402
from apps.connections.models import Connection  # noqa: E402
from apps.core.actor import actor_for, system_actor  # noqa: E402
from apps.core.models import Membership, Tenant  # noqa: E402
from apps.core.services import add_membership, create_tenant, root_organization  # noqa: E402

#: The tenant every run of this harness works in. One slug, reused: the drive
#: gives each run its own DATABASE, so there is nothing for a stable slug to
#: collide with, and a stable slug is what lets `facts` find the rows again from
#: a second process without being told where to look.
SLUG = "runbook-drive"
PASSWORD = "runbook-drive-password"  # pragma: allowlist secret — a scratch database, per run
OWNER = "owner@runbook.invalid"
TEMPLATE = "runbook-receipt"

#: The two handles the recipes post back. Fixed rather than random for the
#: reason the slug is: the drive has to substitute one into a recipe and then
#: ask about it, from two different processes.
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
    # harness is a scratch database that lives for one drive.
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
    seeded = _seed()

    # Port 0: the kernel picks a free one. A fixed port is how a drive ends up
    # verifying a sibling worktree's server instead of its own.
    httpd = ThreadedWSGIServer(("127.0.0.1", 0), WSGIRequestHandler, allow_reuse_address=False)
    httpd.set_app(WSGIHandler())
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
    """Everything the drive asks about, one fact per line, in the drive's grammar.

    Printed rather than answered per question so that a failing case can dump the
    whole world in one place. The shapes:

        connection <id> <provider> <name> <secret-sha256-prefix>
        message    <provider_message_id> <status>
        engagement <provider_message_id> <kind> <url>
    """
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
    """Where this harness's work lands, in shell, so the drive can `.` the output.

    THE DRIVE HAS TO CLEAN UP AFTER THIS FILE, and to do that it has to know two
    things it must not derive for itself: the Temporal TASK QUEUE the seeded
    sends dispatch onto, and the TENANT SLUG every workflow id starts with.

    Both are read here rather than recomputed in the shell, and that is the
    no-second-copy discipline the whole drive is built on, applied to its own
    cleanup. The queue is `settings.TEMPORAL_TASK_QUEUE` — the one seam
    `config/settings/base.py` derives it at — so a deployment that pins the
    queue outright, or a change to how the name is derived from the database,
    moves the drive's cleanup with it. A shell copy of that arithmetic would
    have gone on terminating a queue nothing uses and stranding the real one,
    silently, which is the exact defect this reports against.

    Printed as shell assignments for the reason `serve` writes an env file: the
    drive sources it.
    """
    from django.conf import settings

    print(f"DRIVE_QUEUE={settings.TEMPORAL_TASK_QUEUE}")
    print(f"DRIVE_SLUG={SLUG}")


def _digest(value: str) -> None:
    """The same sha256 prefix `facts` prints, for a secret the drive holds.

    So the drive can prove the connection recipe stored the secret it was given
    without either side printing the secret itself.
    """
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
