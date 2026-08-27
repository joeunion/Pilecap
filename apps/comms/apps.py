from django.apps import AppConfig


class CommsConfig(AppConfig):
    """The one door out of this product to a person.

    `comms.send()` is the only legal sender (`architecture.md`,
    Communications): a product feature does not reach for `django.core.mail`,
    an SMS SDK or a Slack webhook, because consent, quiet hours and suppression
    are enforced **inside** `send()` and anything that goes around it goes
    around those too.

    `depends_on` names five apps and it is worth saying why each is there,
    because comms is the first app in this tree that sits **above** the spine
    rather than beside it (ADR comms-1):

    * `core` and `accounts` — the tenant, the organization tree, the actor, the
      `@service` decorator, the user a `Recipient` may point at;
    * `events` — a message's lifecycle is published (`comms.message.queued`,
      `.sent`, `.failed`, `.suppressed`) and this app **imports** `emit`
      rather than inverting through `core.bridge`. The bridge exists so a
      *lower* layer can call a higher one; comms is higher than the spine, so
      the direct import is the ordinary downward call and the indirection would
      buy nothing but a name to typo;
    * `workflows` — delivery waits and retries, so it is a Temporal workflow;
    * `connections` — the declaration C1-1a made ahead of time is now load
      bearing: `ready()` below registers this app's inbound handler on that
      app's registry, which is how a provider's status webhook reaches
      `record_delivery_status` without comms ever owning a route (ADR comms-3,
      comms-4).
    """

    name = "apps.comms"
    verbose_name = "Communications"
    depends_on: tuple[str, ...] = ("core", "accounts", "events", "workflows", "connections")

    def ready(self) -> None:
        """Claim this app's inbound deliveries. **The whole registration.**

        Here rather than at module import because it reaches into another app,
        and `ready()` is the one moment Django guarantees every app is loaded.
        Nothing in `config/` is edited and no route is added: the receiver in
        `apps/connections` already exists, verifies the signature, stores the
        delivery and then asks its registry who wanted it.

        One registration per entry in `STATUS_PROVIDERS`, which is what makes an
        SMS delivery receipt read with the SMS adapter's vocabulary rather than
        with the email one — comms-a registered a single slug and hard-coded
        `EmailChannel` behind it, which was right while email was the only kind
        that could report back.

        **Two registrations per slug since E1′, and they are the two halves of
        the same seam.** The handler says what a delivery *means*; the verifier
        says whether the sender was really the sender, because an ESP signs the
        way its own vendor decided and `apps/connections`' HMAC-over-body is
        this template's shape rather than anybody's standard. Both are functions
        that app calls without importing this one, and a verifier answers
        `None` — "no opinion, use your own credential" — whenever it cannot
        check, which is every laptop and every test run.

        **And the verifier is per SLUG since T2** (ADR comms-9's SMS half).
        Resend signs with Svix and Twilio signs an HMAC over the callback URL and
        the form fields; one function for both would be one function that knows
        two vendors' schemes, and the map in `providers.STATUS_VERIFIERS` is
        where that fork is written down. A slug with no entry keeps the ESP
        verifier, which has always answered `None` for anything it cannot read —
        the fail-safe direction, and why adding a slug is still one line.

        Importing `providers` here also imports this app's models, which is why
        it is not a module-level import in `apps.py` — an `AppConfig` module is
        read before the app registry is populated.
        """
        from apps.comms.providers import (
            STATUS_PROVIDERS,
            STATUS_VERIFIERS,
            handle_status_webhook,
            verify_status_webhook,
        )
        from apps.connections.providers import (
            register_inbound_handler,
            register_webhook_verifier,
        )

        for provider in STATUS_PROVIDERS:
            register_inbound_handler(provider, handle_status_webhook)
            register_webhook_verifier(
                provider, STATUS_VERIFIERS.get(provider, verify_status_webhook)
            )
