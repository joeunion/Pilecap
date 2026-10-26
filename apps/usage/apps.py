from typing import Any, ClassVar

from django.apps import AppConfig


class UsageConfig(AppConfig):
    """**A number that reaches an invoice is a ledger, not a counter.**

    The platform spends money on behalf of tenants — tokens, storage, messages —
    and the number that surfaces on a dashboard or an invoice months later has to
    be evidence. So usage is recorded the way an accountant records: one row per
    witnessed consumption, appended and never rewritten, corrected by a
    superseding row that says what it corrects and why, and read by summing the
    rows rather than by trusting a column somebody incremented (ADR usage-1).

    **Metering only.** Invoicing is a product-layer decision and stays one; this
    app measures and says so, and nothing here ever refuses an action because a
    number got big. That is the ruling in ADR usage-1 and it is worth saying in
    the registration, because "quota" is the first feature a reader assumes: a
    product that wants a hard limit builds the refusal in its OWN services, on
    this ledger's read and on the `usage.threshold.crossed` event.

    `depends_on` names three apps:

    * `core` — the tenant, the organization tree, `@service`, the scoped
      managers every read here goes through, and `core.log`;
    * `accounts` — nothing is imported from it today, and it is declared because
      the actor a `record_usage` call carries is a person or a token from that
      app and the audit row `@service` writes points at both. The ADR's app map
      names it for the same reason;
    * `events` — **added here, and the ADR's app map row is corrected in the
      same commit.** ADR usage-1's map was written before its own § "Events /
      workflow split" ruled `usage.threshold.crossed` IN, so
      the map says `core, accounts` while the app it describes publishes an
      event. An app that emits imports `emit` — the ordinary downward call a
      domain app makes, the same one `apps.exports` records — so the dependency
      is declared rather than smuggled.

    **There is no `lifecycle.py` here and there should not be one**: this app
    owns no third-party table. `UsageEntry` declares its own lifecycle on the
    class, which is where a declaration belongs when the model can carry it (ADR
    core-13), and `rules.yaml`'s rule-11 whitelist does not name a `lifecycle`
    module for `usage` for exactly that reason. What it DOES name is `meters` —
    see that module's docstring for why the meter vocabulary is a file.
    """

    name = "apps.usage"
    verbose_name = "Usage"
    depends_on: tuple[str, ...] = ("core", "accounts", "events")
    ratchet_floors: ClassVar[dict[str, int]] = {
        "91.block-tail": 211,
        "91.docstring-tail": 725,
        "91.module-tail": 156,
        "91.narrative": 6,
    }

    def ready(self, **kwargs: Any) -> None:
        """Refuse a malformed meter name at boot, before anything can record one.

        A meter name is a **published contract**: it is the string an invoice
        line, a dashboard series and a threshold in a tenant's settings all match
        on, and a typo is a meter that quietly accrues under a name nothing else
        in the deployment knows about. So the whole declared vocabulary is
        validated once, here, at the moment the app registry finishes populating
        — which is the earliest point at which every app's `meters.py` can be
        imported at all.

        The tier is deliberate and it is the strongest one this tree has for a
        declaration: `ImproperlyConfigured` out of `ready()` stops the process,
        the same way `core.exceptions.register_refusal` and
        `core.lifecycle.Lifecycle` refuse at import. A system check would be
        quieter and would let a bad name ride in a running worker until somebody
        remembered to run `manage.py check`.
        """
        from apps.usage.meters import validate_declared_meters

        validate_declared_meters()
