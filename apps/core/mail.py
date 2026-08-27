"""Sending email — as a workflow, because a mail host is a thing that blinks.

Two functions, and the difference between them is the whole point:

* **`send_mail(...)` is what product code calls.** It starts a
  `SendEmailWorkflow` on the caller's commit and returns immediately. Nothing
  talks to an SMTP server inside the request. If the mail host is down, the
  workflow retries with backoff for an hour; if the transaction that asked for
  the email rolls back, no email is sent, because the start was registered on
  `transaction.on_commit`. A service that called an SMTP server inline would
  fail the whole invitation when the mail host blinked, and would hold a
  database transaction open across a network call to somebody else's server
  while it did.

* **`send_now(...)` sends, right here, on this thread.** It is what the
  activity calls, and what a test or a shell session calls when it wants the
  message in `django.core.mail.outbox` without a worker running. Product code
  does not call it.

`render` is shared by both, so the message a test asserts on is the message the
worker sends.

**Templates.** `template="invitation"` renders `mail/invitation.txt`, and
`mail/invitation.html` as an alternative if the app ships one. Text is
mandatory and HTML is optional, in that order deliberately: a message with no
plain-text part is a message some clients render as an empty page, and writing
the text first is what keeps the content in it.

**Where the mail goes.** Locally, Mailpit in `compose.yaml` — every message
caught and readable at http://127.0.0.1:8025, and none of it delivered, so a
laptop cannot email a real customer by accident. Under pytest, Django's locmem
backend. In production, `EMAIL_BACKEND` and the `EMAIL_*` settings, or a
provider through `apps.connections`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string

from apps.core import bridge
from apps.core.log import get_logger
from apps.core.models import Tenant

log = get_logger("apps.core.mail")

# Where a template named `invitation` is looked for. One directory, so an app
# that adds an email adds a file and nothing else.
TEMPLATE_DIR = "mail"

# The workflow that sends it, named as a string because `core` may not import
# the app that defines it. `apps.workflows.workflows.SendEmailWorkflow` carries
# the same name in its `@workflow.defn`, and the worker resolves it by that.
SEND_EMAIL_WORKFLOW = "SendEmailWorkflow"

# How long the workflow will keep trying before it gives up, retries included.
# An invitation that has not gone out in an hour is not going out: the address
# is wrong, or the provider is having a day, and either way a workflow still
# retrying at midnight is noise rather than delivery.
DELIVERY_DEADLINE_SECONDS = 3600


def render(*, template: str, context: dict[str, Any]) -> tuple[str, str | None]:
    """The text body, and the HTML alternative if the template set has one."""
    text = render_to_string(f"{TEMPLATE_DIR}/{template}.txt", context)
    try:
        html: str | None = render_to_string(f"{TEMPLATE_DIR}/{template}.html", context)
    except TemplateDoesNotExist:
        html = None
    return text, html


def send_now(
    *,
    to: Sequence[str],
    subject: str,
    template: str,
    context: dict[str, Any],
    tenant: Tenant | None = None,
) -> int:
    """Render and send, synchronously. Returns how many messages were accepted.

    Called by the activity, and by tests and shell sessions. **Not by product
    code** — a service that called this would be doing network I/O inside a
    database transaction, and would lose the message the first time the mail
    host was slow.
    """
    text, html = render(template=template, context=context)
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=str(settings.DEFAULT_FROM_EMAIL),
        to=list(to),
    )
    if html is not None:
        message.attach_alternative(html, "text/html")
    sent = message.send()
    # The addresses are deliberately not logged: who was emailed what is a fact
    # about a person, and this line exists to answer "did it go out".
    log.info(
        "core.mail.sent",
        template=template,
        recipients=len(to),
        accepted=sent,
        tenant_id=str(tenant.pk) if tenant is not None else None,
    )
    return sent


def message_for(
    *,
    to: Sequence[str],
    subject: str,
    template: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    """The workflow argument `send_mail` starts `SendEmailWorkflow` with.

    A plain dictionary, because `core` may not import
    `apps.workflows.types.SendEmail` — the keys are that dataclass's field names
    and Temporal's converter builds the dataclass from them on the worker side,
    using the type hint on `SendEmailWorkflow.run`. It is a named function
    rather than a literal inside `send_mail` so a test can assert on the exact
    shape that crosses the boundary.
    """
    return {
        "to": list(to),
        "subject": subject,
        "template": template,
        "context": dict(context),
    }


def send_mail(
    *,
    to: Sequence[str],
    subject: str,
    template: str,
    context: dict[str, Any],
    tenant: Tenant,
    key: str,
) -> Any:
    """Start the workflow that will send this email. Returns its `WorkflowRun`.

    Callable from inside a service's `transaction.atomic()`: the visibility row
    is written in the caller's transaction and the Temporal call is deferred to
    `transaction.on_commit`, so a rolled-back invitation emails nobody.

    `key` is required, and is the caller's answer to "what makes this send
    unique and repeatable" — house rule 18. It becomes the last segment of the
    workflow id (`<tenant>:core:email:<key>`), so a service that is retried
    starts one run and not two. A row's primary key is almost always the right
    answer; a random value never is. It is required rather than derived from the
    message, because two identical reminders a week apart are two sends and a
    content digest would refuse the second.

    `context` crosses a workflow boundary and is therefore replayed from
    history: it must be JSON-serialisable, and it must not carry a bearer
    credential — a token in a workflow argument is a token in Temporal's history
    for as long as the retention says. The invitation email carries no token
    for exactly that reason (`apps.accounts.adapter` joins the membership from
    the address at signup).

    **The call goes through `core.bridge`, not through an import.** `workflows`
    sits above `core`, so naming it here — even inside the function body — would
    be the upward import the layer contract exists to refuse. The workflows app
    registers `start_on_commit` and `workflow_id` from its `AppConfig.ready()`
    and this looks them up by name. The return value is the `WorkflowRun` that
    app records; it is typed `Any` because `core` may not name a type that lives
    above it.
    """
    start = bridge.get(bridge.START_WORKFLOW_ON_COMMIT)
    build_id = bridge.get(bridge.WORKFLOW_ID)
    return start(
        workflow=SEND_EMAIL_WORKFLOW,
        arg=message_for(to=to, subject=subject, template=template, context=context),
        tenant=tenant,
        id=build_id(tenant=tenant, app="core", noun="email", key=key),
    )
