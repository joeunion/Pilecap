#!/usr/bin/env python3
"""The mail round trip, driven end to end — a committed instrument.

    ./scripts/serve.sh                       # in another shell
    uv run python scripts/mail_demo.py
    uv run python scripts/mail_demo.py --base-url http://127.0.0.1:8000
    uv run python scripts/mail_demo.py --verbose   # keep core.log's JSON lines

WHY IT EXISTS. The comms round trip — a service sends, a provider accepts, the
provider posts a signed webhook back, the delivery status moves — was proved
by hand three separate times in two days, and each pass hand-built the same
Svix/Resend-shaped harness and threw it away. Three builds of one instrument
is the definition of something that should have been committed the first
time. This is that instrument.

**It is `oauth_demo.py`'s sibling, and deliberately so**: a committed,
censused, cross-app driver that needs a SERVED STACK and
provider-shaped secrets, exits nonzero naming the refusal, and **is never a gate
leg**. See "NOT A GATE LEG" below — that is a contract, not a preference.

## PREREQUISITES, on the server rather than here

  * **A served stack** — `./scripts/serve.sh`. Legs 4-7 are HTTP.
  * **A worker** — `./scripts/worker.sh`. The door answers **202 Accepted**, on
    purpose: it verifies, stores, hands off to a workflow and returns. The
    status moves when the worker processes that handoff, so with no worker the
    round trip stops after leg 3 and this script says exactly that.
  * **An Anymail ESP backend**, for the Svix half specifically:
    `EMAIL_BACKEND=anymail.backends.resend.EmailBackend`. This is the same
    shape of prerequisite `oauth_demo.py` has in `ZITADEL_MCP_AUDIENCE`, and it
    is not optional decoration: the receiver picks its signature scheme at
    request time, and the ESP-registered Svix verifier only engages when this
    deployment actually sends through an ESP. Without it the door falls back to
    the template's own `X-Signature` HMAC — which this script will drive
    instead, **and name**, because a laptop pass that read like a Resend pass
    would be the exact dishonesty the instrument census exists to refuse.
    (The API key is never used by these legs; nothing here talks to Resend.)
  * **A tenant with an owner** — `uv run python manage.py seed`.

## What it proves that the test suite cannot

`apps/comms/tests/test_esp_webhook.py` proves the same door with Django's test
client, in-process, against a transactional database. That is the right place
for the unit property and it is not what this is for. This drives the door **over
the wire, at a running server**, which is the only way to see:

  * that the route is actually MOUNTED where the client thinks it is — a test
    client resolves a URL through the URLconf; a real POST resolves it through
    ASGI, the middleware stack and whatever a reverse proxy did to the path;
  * that the raw body reaches the signature check BYTE-IDENTICAL — every
    middleware that re-encodes, strips or re-orders is in this path and in no
    test's path, and an HMAC over a body somebody re-serialised is the classic
    way a webhook door passes its tests and fails in production;
  * that the three Svix headers survive the hop with their case and content.

## The legs, each printed as it happens

  1. **arrange** — a tenant, a Resend-shaped connection carrying a Svix signing
     secret, a template, a consenting recipient. In-process (see THE SEAM).
  2. **send** — `comms.services.send()`, the one legal sender. The message comes
     back queued.
  3. **accepted** — `record_message_sent()` under a Resend-shaped `email_id`,
     which is what the webhook will name. "Accepted" is not "delivered", and the
     row says so.
  4. **delivered** — a delivery body POSTed over HTTP at
     `/api/v1/connections/<id>/webhook/`, in the vocabulary THIS STACK'S DOOR
     READS (below). The status must move.
  5. **tampered** — the same signature over a DIFFERENT body. Must be REFUSED.
  6. **stale** — a correctly signed body with an old timestamp. Must be REFUSED.
  7. **complained** — a complaint, which suppresses the address WITHOUT
     transitioning the delivery status (proved live end to end).

## THE VOCABULARY IS PART OF THE SCHEME (ADR comms-13)

The receiver picks its **signature** scheme at request time, and this driver
already asked which one (`scheme_this_stack_uses`). The **body** is picked the
same way, and an earlier version of this driver was not doing it:

  * **svix** — an Anymail ESP is configured, so raw ESP bodies are exactly right:
    `{"type": "email.delivered", "data": {…}}` arrives and
    `providers.esp_normalized` translates it on the way in. Unchanged.
  * **hmac** — no ESP is configured, so **there is nothing to translate with**,
    and the door's contract is anymail's normalised vocabulary itself:
    `{"event_type": "delivered", "message_id": …}`. Posting a raw Resend body
    here was posting a language this stack cannot read; the door stored it,
    answered 202, dropped it, and the message stayed `sent` forever.

A driver that speaks a contract it does not drive is not an instrument, which
is the same argument `scheme_this_stack_uses` makes about signatures — so both
halves are asked once and printed once, and leg 4 says which it used.

## REFUSAL-HONEST (baked in at birth)

A leg that expects a refusal and does not get one is a FAILURE, and this script
exits nonzero naming it. The failure mode this guards against is an instrument that
prints a green line for a door that answered `isError` — so every leg here
asserts the *shape* of the answer, and the two refusal legs assert that the door
said no. A door that accepted a tampered body is the single most important thing
this script can find, and it will not be printed as a pass.

## THE SEAM, declared rather than discovered

Legs 1-3 run **in this process**, through Django and the services; legs 4-7 go
**over HTTP** to the served stack. That split is not laziness: there is no REST
route for `record_message_sent` (a provider handle is something a transport tells
us, not something a client posts), so the arrange half has no wire to use. Both
halves address the SAME database — `scripts/db.sh`'s derived name, which the
server also resolves — so a row written here is a row the server reads. If the
server is pointed at a different database this script will still "pass" leg 3 and
fail leg 4 with a 404, and it says so when it does.

**What it does NOT prove:** that Resend actually delivers mail. It proves the
provider SHAPE — the bodies, the signature scheme, the door's reaction. A live
drive against the real ESP is the thing that proves delivery, once; this is the
repeatable stand-in for the ninety per cent that does not need somebody's
account. Nothing here talks to Resend.

## NOT A GATE LEG. EVER.

It needs a served stack and a real database with rows in it; it writes those
rows; it is slow. `scripts/tests/` is the gate's shell-refusal territory and this
does not belong there. If some future work wants the round trip in the gate,
the unit door test is already there. This
script is for a human, a runbook step, or a field test — and `docs/product/
instruments.md` carries its row saying exactly that.

Stdlib + the project's own dependencies. Python 3.12.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import pathlib
import secrets as _secrets
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_LOOK = 2

_PASSED = 0


def say(leg: str, verdict: str, detail: str = "") -> None:
    line = f"  {verdict:<8} {leg}"
    print(f"{line} — {detail}" if detail else line, flush=True)


def ok(leg: str, detail: str = "") -> None:
    global _PASSED
    _PASSED += 1
    say(leg, "ok", detail)


def die(leg: str, detail: str) -> None:
    """A leg did not do what it exists to do. Exit 1, naming it."""
    say(leg, "FAILED", detail)
    print(
        "\n!! the mail round trip did not complete. The leg above is the finding;\n"
        "   nothing after it ran, so nothing after it is a pass.",
        file=sys.stderr,
    )
    sys.exit(EXIT_FAILED)


def cannot_look(detail: str) -> None:
    """The driver could not run its legs. Exit 2 — it never means 'fine'."""
    print(f"!! mail_demo could not look: {detail}", file=sys.stderr)
    print(
        "   Nothing was asserted. A driver that could not reach its door has not\n   cleared it.",
        file=sys.stderr,
    )
    sys.exit(EXIT_CANNOT_LOOK)


def whsec() -> str:
    """A Svix signing secret in the shape Resend hands one out in.

    Minted per run, never pinned: nothing in this file may be a string somebody
    could mistake for a credential that needs rotating.
    """
    return "whsec_" + base64.b64encode(_secrets.token_bytes(24)).decode()


def resend_event(kind: str, *, email_id: str, to: str, **data: Any) -> dict[str, Any]:
    """One webhook body in Resend's shape — no Anymail key anywhere in it."""
    now = datetime.now(tz=UTC).isoformat()
    return {
        "type": kind,
        "created_at": now,
        "data": {"email_id": email_id, "to": [to], "created_at": now, **data},
    }


#: Resend's own event names, and the **anymail-normalised** word each becomes.
#: The right-hand column is `apps/comms/providers.EMAIL_STATUS`'s key set and it
#: is what this door reads when nothing is configured to translate the left one.
NORMALISED_EVENT: dict[str, str] = {
    "email.delivered": "delivered",
    "email.bounced": "bounced",
    "email.complained": "complained",
}


def status_body(kind: str, *, scheme: str, email_id: str, to: str, **data: Any) -> dict[str, Any]:
    """One status body in the vocabulary THIS STACK'S DOOR ACTUALLY READS.

    `kind` is named in Resend's spelling at every call site, because that is the
    concrete thing a reader can check against the vendor's documentation — and
    this function is the one place that knows the door may want the other
    column. See the module docstring's "THE VOCABULARY IS PART OF THE SCHEME".

    Extra `data` is Resend-shaped decoration (`subject=`, and whatever a future
    leg adds) and is dropped on the normalised side deliberately: anymail's
    tracking event has its own field names, and inventing a mapping for prose
    the assertions never read would be a second vocabulary to keep in step.
    """
    if scheme == "svix":
        return resend_event(kind, email_id=email_id, to=to, **data)
    return {
        "event_type": NORMALISED_EVENT[kind],
        "message_id": email_id,
        "recipient": to,
        "timestamp": datetime.now(tz=UTC).isoformat(),
    }


def scheme_this_stack_uses() -> str:
    """`svix` or `hmac` — WHICH DOOR IS ACTUALLY ARMED, asked rather than assumed.

    The receiver has two schemes and picks between them at request time
    (`apps/connections/api.py::_verified`): a provider-registered verifier
    decides when it recognises the request, and the template's own
    HMAC-over-body decides when it does not. For Resend the registered verifier
    is Anymail's Svix view — but it only ENGAGES when this deployment is
    actually configured with an Anymail ESP backend. On a laptop sending through
    Mailpit, `_anymail_esp()` is falsy, the verifier abstains, and the door
    checks `X-Signature` instead.

    So a driver that always posted Svix headers would get 401 on every laptop
    and read like a broken door. And a driver that always posted the template
    HMAC would pass on an ESP-backed stack while proving nothing about the
    scheme that stack really uses. Neither is an instrument. This asks the
    settings the server is running on, drives the scheme that answers, and
    **prints which one** — so nobody reads a laptop pass as a Resend pass.

    The read is of THIS process's settings, which is the same code and the same
    `.env` the server loaded. If the two were pointed at different settings the
    round trip would fail at leg 4 and say so, which is the honest failure.
    """
    try:
        from apps.comms.providers import _anymail_esp

        return "svix" if _anymail_esp() else "hmac"
    except Exception:  # noqa: BLE001 - an unknown ESP seam is the door's own fallback
        return "hmac"


def post_webhook(
    base_url: str,
    connection_id: str,
    payload: dict[str, Any],
    *,
    secret: str,
    scheme: str,
    when: datetime | None = None,
    tamper: bool = False,
) -> tuple[int, str]:
    """Sign the way this stack's door checks, POST it, return (status, body).

    `tamper` alters the body AFTER the signature is computed — the only honest
    way to drive that leg, because a signature over one body and a request
    carrying another is exactly what an attacker who captured a delivery has.
    """
    body = json.dumps(payload).encode()
    moment = when or datetime.now(tz=UTC)
    msg_id = f"msg_{uuid4().hex[:20]}"
    headers = {"Content-Type": "application/json"}
    if scheme == "svix":
        from svix.webhooks import Webhook as SvixWebhook

        headers.update(
            {
                "svix-id": msg_id,
                "svix-timestamp": str(int(moment.timestamp())),
                "svix-signature": SvixWebhook(secret).sign(
                    msg_id=msg_id, timestamp=moment, data=body.decode()
                ),
            }
        )
    else:
        import hashlib
        import hmac as _hmac

        headers["X-Signature"] = (
            "sha256=" + _hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        )
        # Recorded on the `InboundWebhook` row and nothing else reads it, so it
        # names whichever key this body actually carries rather than assuming
        # Resend's.
        headers["X-Event-Type"] = str(payload.get("type") or payload.get("event_type") or "")
    if tamper:
        altered = dict(payload)
        if "type" in altered:
            altered["type"] = "email.delivered"
        else:
            altered["event_type"] = "delivered"
        body = json.dumps(altered).encode()
    request = urllib.request.Request(
        f"{base_url}/api/v1/connections/{connection_id}/webhook/",
        data=body,
        method="POST",
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, response.read().decode()[:400]
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()[:400]
    except urllib.error.URLError as error:
        cannot_look(
            f"no server at {base_url} ({error.reason}). Start one with "
            f"./scripts/serve.sh, or name another with --base-url."
        )
        raise  # unreachable; keeps the type checker honest
    return 0, ""  # pragma: no cover


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").splitlines()[0],
        epilog="Needs a served stack. NEVER a gate leg — see the module docstring.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("DJB_BASE_URL", "http://127.0.0.1:8000"),
        help="the served stack (default: %(default)s)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="leave core.log's per-service JSON lines on stdout",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    # The checkout root, not `scripts/`, is where `config` and `apps` live.
    # `manage.py` gets this for free by sitting at the root; a script one
    # directory down has to say so.
    root = str(pathlib.Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    try:
        import django

        django.setup()
    except Exception as error:  # noqa: BLE001 - an import guard, reported as could-not-look
        cannot_look(f"Django would not start ({type(error).__name__}: {error})")

    # QUIET THE SERVICE LOG, and say why. `core.log` writes one structured JSON
    # line per service call to stdout — correct for a server, and it buries this
    # driver's seven lines under a hundred. A reader who cannot find the verdict
    # has not been given one. `--verbose` puts them back for anybody debugging
    # the round trip itself.
    import logging

    if not args.verbose:
        logging.getLogger("apps.core.service").setLevel(logging.WARNING)

    from django.db import connection as db_connection

    from apps.comms import services as comms
    from apps.comms.models import Message
    from apps.comms.providers import STATUS_PROVIDER
    from apps.connections.services import create_connection
    from apps.core.actor import Actor  # noqa: F401  (typing only, imported for clarity)

    scheme = scheme_this_stack_uses()
    print(f"mail_demo: the comms round trip against {base_url}")
    print(f"  database: {db_connection.settings_dict['NAME']}")
    print(
        f"  signature scheme this stack's door will use: {scheme.upper()}"
        + (
            "  (Anymail ESP configured — the Resend/Svix shape)"
            if scheme == "svix"
            else "  (no Anymail ESP — the template's own X-Signature HMAC;"
            " point this at an ESP-backed stack to drive the Svix shape)"
        )
    )
    print(
        "  status vocabulary these legs will POST: "
        + (
            "RAW RESEND bodies ({'type': 'email.delivered', …}), translated on arrival by anymail"
            if scheme == "svix"
            else "ANYMAIL-NORMALISED bodies ({'event_type': 'delivered', …}) —"
            " with no ESP configured there is nothing to translate a raw one with"
        )
    )
    print("  (leg 1-3 in this process, legs 4-7 over the wire — see the header's SEAM)")

    # --- leg 1: arrange -----------------------------------------------------
    try:
        tenant, actor = _arrange_tenant()
    except Exception as error:  # noqa: BLE001
        cannot_look(
            f"could not arrange a tenant ({type(error).__name__}: {error}). "
            f"Has this database been migrated? `uv run python manage.py migrate`."
        )

    secret = whsec()
    stamp = uuid4().hex[:8]
    esp = create_connection(
        tenant=tenant,
        actor=actor,
        provider=STATUS_PROVIDER,
        name=f"Resend (mail_demo {stamp})",
        credentials={"webhook_secret": secret, "access_token": "mail-demo-not-a-key"},
    )
    comms.create_template(
        tenant=tenant,
        actor=actor,
        name=f"maildemo_{stamp}",
        subject="Receipt",
        body="Hello {{ name }}, your receipt is ready.",
    )
    address = f"mail-demo-{stamp}@example.com"
    recipient = comms.create_recipient(
        tenant=tenant, actor=actor, email=address, display_name="Mail Demo"
    )
    ok("1 arrange", f"connection {esp.pk}, recipient {address}, secret {len(secret)} chars")

    # --- leg 2: send --------------------------------------------------------
    message = comms.send(
        recipient=recipient,
        template=f"maildemo_{stamp}",
        context={"name": "Ada"},
        channel="email",
        tenant=tenant,
        actor=actor,
    )
    ok("2 send", f"message {message.pk} status={message.status}")

    # --- leg 3: the transport accepted it -----------------------------------
    email_id = str(uuid4())
    message = comms.record_message_sent(
        tenant=tenant,
        actor=actor,
        message=message,
        provider="anymail:resend",
        provider_message_id=email_id,
    )
    ok("3 accepted", f"provider handle {email_id} (accepted is not delivered)")

    # --- leg 4: the signed delivery, over the wire --------------------------
    status, body = post_webhook(
        base_url,
        str(esp.pk),
        status_body("email.delivered", scheme=scheme, email_id=email_id, to=address),
        secret=secret,
        scheme=scheme,
    )
    if status >= 300:
        die("4 delivered", f"the door refused a VALID delivery: HTTP {status} {body}")
    before = message.status
    message = _await_status_change(Message, message.pk, before)
    if message is None:
        die(
            "4 delivered",
            f"the door answered {status} (accepted) but the status never moved from "
            f"{before!r} within {SETTLE_SECONDS}s. The 202 is a promise to PROCESS, "
            f"not a claim to have processed. THIS DRIVER CANNOT TELL THESE APART "
            f"FROM OUT HERE — all it can see is a row that did not change:\n"
            f"     (a) THE BODY WAS READ AND DROPPED. The handler names its own "
            f"cause and prints a remedy; grep the SERVER log for "
            f"comms.status.untranslatable_body (the vocabulary was unreadable — "
            f"this run posted the {scheme!r} one), comms.status.no_message_id, "
            f"comms.status.ignored (read and non-terminal), or "
            f"comms.status.unknown_message (no row carries that handle).\n"
            f"     (b) NOTHING PROCESSED IT. The handoff is a workflow, so no "
            f"worker running (./scripts/worker.sh), or a worker on another task "
            f"queue, looks exactly the same from here.\n"
            f"   Read the server log first: (a) always says which, (b) never says "
            f"anything at all — the two are easy to mistake for each other; check "
            f"the server log before assuming which one this is.",
        )
    ok("4 delivered", f"HTTP {status}; status {before!r} -> {message.status!r}")

    # --- leg 5: a tampered body must be REFUSED -----------------------------
    status, body = post_webhook(
        base_url,
        str(esp.pk),
        status_body("email.bounced", scheme=scheme, email_id=email_id, to=address),
        secret=secret,
        scheme=scheme,
        tamper=True,
    )
    if status < 300:
        die(
            "5 tampered",
            f"THE DOOR ACCEPTED A TAMPERED BODY (HTTP {status}). A signature over one "
            f"body and a request carrying another is what a captured delivery looks like.",
        )
    ok("5 tampered", f"refused with HTTP {status}, as it must be")

    # --- leg 6: a stale timestamp must be REFUSED ---------------------------
    status, body = post_webhook(
        base_url,
        str(esp.pk),
        status_body("email.delivered", scheme=scheme, email_id=email_id, to=address),
        secret=secret,
        scheme=scheme,
        when=datetime.now(tz=UTC) - timedelta(days=2),
    )
    if scheme == "svix":
        # The five-minute replay window is the VENDOR LIBRARY's, and this
        # product deliberately does not re-implement it. Under the template's
        # own HMAC there is no timestamp in the signed material at all, so an
        # old body is indistinguishable from a fresh one — declared here rather
        # than dressed up as a pass.
        if status < 300:
            die(
                "6 stale",
                f"the door accepted a 2-day-old signature (HTTP {status}) — replay is open",
            )
        ok("6 stale", f"refused with HTTP {status}, as it must be")
    else:
        say(
            "6 stale",
            "n/a",
            "the template HMAC signs no timestamp — replay windows are the ESP "
            "library's, and this stack is not ESP-backed. NOT a pass.",
        )

    # --- leg 7: a complaint suppresses without transitioning ----------------
    settled = message.status
    status, body = post_webhook(
        base_url,
        str(esp.pk),
        status_body(
            "email.complained", scheme=scheme, email_id=email_id, to=address, subject="Receipt"
        ),
        secret=secret,
        scheme=scheme,
    )
    if status >= 300:
        die("7 complained", f"the door refused a valid complaint: HTTP {status} {body}")
    # A complaint is allowed to change nothing, so this WAITS THE SAME WINDOW
    # before concluding it did — otherwise "nothing happened yet" and "nothing
    # happens" would be the same observation, and the leg would pass for the
    # wrong reason on a slow machine.
    moved = _await_status_change(Message, message.pk, settled)
    message = moved if moved is not None else Message.objects.get(pk=message.pk)
    if message.status != settled:
        die(
            "7 complained",
            f"a complaint moved status {settled!r} -> "
            f"{message.status!r}; a complaint must not transition status",
        )
    ok("7 complained", f"HTTP {status}; status stayed {settled!r} (news, not a transition)")

    print(f"\nmail_demo: {_PASSED} legs passed. The round trip is whole.")
    print(f"  rows left behind: connection {esp.pk}, message {message.pk}, {address}")
    print("  Nothing here deletes them. A driver that tidied up could not be read")
    print("  afterwards, and reading the rows is half of why anybody runs it.")
    return EXIT_OK


#: How long a 202 gets to become a processed webhook before this driver calls it
#: a finding. The handoff is a Temporal workflow and the worker polls, so this is
#: a worker's round trip and not a network timeout.
SETTLE_SECONDS = 20


def _await_status_change(model: Any, pk: Any, before: str) -> Any:
    """Poll for the status to move, or None if it never does.

    POLLING AND NOT SLEEPING-THEN-LOOKING: the difference matters for what the
    failure MEANS. A fixed sleep that is too short reports a broken door on a
    busy laptop; one that is long enough for the worst case wastes that long on
    every healthy run. This returns the moment the row changes and only spends
    the full budget when nothing happens at all.
    """
    import time

    deadline = time.monotonic() + SETTLE_SECONDS
    while time.monotonic() < deadline:
        row = model.objects.get(pk=pk)
        if row.status != before:
            return row
        time.sleep(0.25)
    return None


def _arrange_tenant() -> tuple[Any, Any]:
    """The tenant and an owner actor to act as. Reuses one if the database has one."""
    from apps.core.actor import actor_for
    from apps.core.models import Membership, Tenant

    tenant = Tenant.objects.order_by("created_at").first()
    if tenant is None:
        raise RuntimeError("no tenant in this database — run `uv run python manage.py seed` first")
    membership = (
        Membership.objects.filter(tenant=tenant, role="owner")
        .select_related("user", "organization")
        .first()
    )
    if membership is None:
        raise RuntimeError(f"tenant {tenant.slug} has no owner membership to act as")
    return tenant, actor_for(user=membership.user, tenant=tenant, org=membership.organization)


if __name__ == "__main__":
    sys.exit(main())
