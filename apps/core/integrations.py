"""Which external services this deployment actually talks to. **Derived, never listed.**

A product's first hour is spent finding out what is wired up, and its worst
production morning is spent finding out what was not. Both questions have the
same answer and it was scattered across a settings module, three registries, an
`.env.example`, two runbooks and a comment: **is this integration real here, is
it a fake, or is it simply absent — and if it is not real, what does somebody
type to make it real?**

## The shape, and why it is a registry and not a list

The one criterion that keeps this honest is the owner's: *adding a new
integration in any future rung appears at all four surfaces with NO edit to any
list.* So there is no list. An app that talks to something outside this process
declares it in `apps/<x>/integrations.py::register(registry)` — the same
discovered hook `apps/<x>/lifecycle.py` uses, the same reason (a central dict
would be one file every app in a parallel wave has to edit), and the same
absence of registration anywhere: the module has the conventional name and the
platform looks in it.

`census()` is what the four surfaces read, all four of them:

* `scripts/setup.sh`'s epilogue — minute one, on a fresh clone.
* `manage.py integrations` — on demand, and the same words.
* `deploy/release.sh`'s wall — a production release refuses to proceed past a
  fake (`--wall`).
* the standing prober — `apps/core/activities.py`'s `ScheduleDeclaration`, for
  the rot that arrives after setup, when a key expires and nothing says so.

## Three statuses, and the middle one is the point

`CONFIGURED` · `FAKE` · `NOT_CONFIGURED`. **`FAKE` is a status and not an
absence**, because the failure this whole instrument exists for is the fake
nobody said out loud: a fresh clone keeps `FakeSmsChannel` by design, a real
STOP is signed, verified, stored and dropped, and the only thing in the tree
that says the transport is off is a comment. A slot that is filled by
something that does not leave the process is *more* dangerous than an empty
one, because the empty one refuses and the fake one succeeds.

**Every status that is not `CONFIGURED` carries a remedy, and the constructor
refuses one without it.** A report that says "not configured" and does not say
what to type is a report that sends a person to the source; that is the
instrument checklist's line, and it is enforced at import here rather than
hoped for at review.

## An unreadable seam is exit 2, never a judgment

If an app's `register` raises, the census records the seam as **unreadable** and
says so; it does not report the app's integrations as absent. "I could not look"
and "I looked and it is not there" are different answers, and collapsing them is
how an instrument comes to report a green deployment during an outage of its own
probe. `manage.py integrations` exits 2 on any unreadable seam — the gate's own
semantics, and `scripts/goalpost_scan.py`'s.

## What it cannot see — declared

Named here because the census's own blind spots are the surveyor's map:

* **A fake that misdeclares itself as real.** Every status is what the owning
  app says it is; nothing here audits the claim. The registry can only be as
  honest as the declaration, and that is the price of not hand-listing.
* **Probe depth varies by integration, and each row says which.** `probe="live"`
  means something outside this process answered during the census;
  `probe="declared"` means the row was derived from configuration alone. Only
  integrations with a `zitadel_audit`-shaped read-only probe can be live, and a
  row that says `declared` is not making a weaker claim quietly.
* **Per-tenant credentials are not deployment configuration.** Twilio and FCM
  are `Connection` rows, so "can this deployment send an SMS" is a query and not
  a setting; an app declaring those declares the deployment-level slot, and
  whether any tenant filled it is that app's own report to make.
* **Infrastructure readiness is `/readyz`'s and is deliberately not duplicated
  here.** Postgres, the cache, the channel layer and Temporal have members
  there, live-probed per replica, per request. A second opinion in a second
  place is how two instruments come to disagree.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass, replace

from django.conf import settings
from django.db import models

__all__ = [
    "Census",
    "Integration",
    "IntegrationRegistry",
    "IntegrationStatus",
    "PROBE_DECLARED",
    "PROBE_LIVE",
    "UnreadableSeam",
    "census",
    "declaring_modules",
]

#: The module an app declares its integrations in, and the attribute the
#: platform calls. Named once so the discovery walk and every error message
#: spell it the same way.
INTEGRATIONS_ATTR = "integrations"

#: `live` — something outside this process answered while the census ran.
#: `declared` — the row was derived from this deployment's configuration and
#: nothing was contacted. Two words, closed, because "partially probed" is a
#: sentence a reader cannot act on.
PROBE_LIVE = "live"
PROBE_DECLARED = "declared"
_PROBES = frozenset({PROBE_LIVE, PROBE_DECLARED})

#: The shortest remedy that is a remedy. A word is a shrug.
MIN_REMEDY = 12


class IntegrationStatus(models.TextChoices):
    """The three answers. There is deliberately no fourth."""

    CONFIGURED = "configured", "Configured"
    FAKE = "fake", "Using a fake"
    NOT_CONFIGURED = "not_configured", "Not configured"


@dataclass(frozen=True)
class Integration:
    """One external service, as this deployment currently stands.

    Frozen for the reason every declaration in this tree is: a value that can be
    mutated after the census read it is a value whose printing and whose meaning
    can differ.
    """

    #: A stable slug. It is what a runbook, an alert and a wall all name, so it
    #: is chosen once and does not change with the display title.
    key: str

    #: What a person calls it.
    title: str

    status: IntegrationStatus

    #: What is TRUE, in one sentence a person can act on. Never a status word
    #: repeated: "the console backend prints mail to stdout" rather than "fake".
    detail: str

    #: What to type, click or open. **Required unless CONFIGURED** — see the
    #: module docstring. An env var, a console path, a runbook line.
    remedy: str = ""

    #: `live` or `declared`. Defaults to the weaker claim on purpose.
    probe: str = PROBE_DECLARED

    #: The module that declared it. Never written by hand; the registry fills it.
    declared_by: str = ""

    def __post_init__(self) -> None:
        _refuse_malformed(self)

    @property
    def is_configured(self) -> bool:
        return self.status is IntegrationStatus.CONFIGURED


def _refuse_malformed(integration: Integration) -> None:
    """Refuse a declaration that cannot serve the surfaces. At import, loudly.

    The tier `core.exceptions.register_refusal` and `core.lifecycle.Lifecycle`
    both set, and for the same reason: a malformed declaration that only fails
    at gate time is a declaration that reaches a deployment.
    """
    where = integration.key or "<unnamed>"
    if not integration.key.strip():
        raise ValueError(
            "an integration needs a key: it is what the wall, the alert and the "
            "runbook all name, and a row nobody can name is a row nobody can act on."
        )
    if not integration.title.strip():
        raise ValueError(f"{where} needs a title — the words a person calls it by.")
    if not integration.detail.strip():
        raise ValueError(
            f"{where} declares a status and no detail. The status is a word; the "
            f"detail is what is TRUE, and it is the half a reader can do something "
            f"with."
        )
    if integration.probe not in _PROBES:
        raise ValueError(
            f"{where} declares probe {integration.probe!r}; the vocabulary is "
            f"{sorted(_PROBES)} and it is closed on purpose — 'partially probed' is "
            f"not something a reader can act on."
        )
    if integration.status is IntegrationStatus.CONFIGURED:
        return
    if len(integration.remedy.strip()) < MIN_REMEDY:
        raise ValueError(
            f"{where} is {integration.status.value} and names no remedy. A report "
            f"that says something is missing and does not say what to type sends a "
            f"person to the source, which is the whole failure this census exists "
            f"to stop."
        )


@dataclass(frozen=True)
class UnreadableSeam:
    """A seam that raised while the census was reading it.

    Kept apart from the integrations for the reason in the module docstring: "I
    could not look" is not "I looked and it is not there", and an instrument
    that reports the second when the first is true is worse than one that says
    nothing.
    """

    module: str
    reason: str


@dataclass(frozen=True)
class Census:
    """What the four surfaces read. One value, computed on demand."""

    integrations: tuple[Integration, ...]
    unreadable: tuple[UnreadableSeam, ...]

    @property
    def is_readable(self) -> bool:
        """Whether every seam answered. False is exit 2, never a verdict."""
        return not self.unreadable

    @property
    def unmet(self) -> tuple[Integration, ...]:
        """Everything that is not `CONFIGURED` — what the deploy wall refuses on."""
        return tuple(row for row in self.integrations if not row.is_configured)


class IntegrationRegistry:
    """What an app's `register(registry)` is handed.

    The only writer. A second app declaring the same key is refused rather than
    resolved by import order, exactly as `LifecycleRegistry` refuses a second
    opinion about one table — and for the same reason: two apps disagreeing
    about whether something is configured is a disagreement to settle in a plan.
    """

    def __init__(self) -> None:
        self._declared: dict[str, Integration] = {}

    def declare(self, integration: Integration, *, source: str = "") -> None:
        stated = replace(integration, declared_by=source or integration.declared_by)
        existing = self._declared.get(stated.key)
        if existing is not None and existing != stated:
            raise ValueError(
                f"the integration {stated.key!r} was already declared by "
                f"{existing.declared_by or 'another module'}, and "
                f"{source or 'this registration'} declares it differently. Two apps "
                f"with two opinions about whether something is configured is a "
                f"disagreement to settle in a plan, not by import order."
            )
        self._declared[stated.key] = stated

    def declarations(self) -> tuple[Integration, ...]:
        return tuple(sorted(self._declared.values(), key=lambda row: row.key))


# --- the platform's own seam --------------------------------------------------
#
# ONE ROW, AND THE SHORTNESS OF THIS SECTION IS THE FINDING (INTEG-1, P7).
#
# The charge named five seams to walk — the channel registry, the connections
# slugs, `STORAGES`, the signing-scheme census and the identity door — and
# `apps/core` can declare none of them. Not by oversight: **the house rules
# refuse it, one seam at a time, and they are right to.**
#
#   * OBJECT STORAGE — house rule 48. The bucket, the address and the credential
#     are named in `apps/files/storage.py` and in `config/settings/` and nowhere
#     else. This module tried, and the gate refused it by name: a census row
#     needs to print the env var as its REMEDY, and printing it is exactly what
#     the rule fences. `apps/core/health.py` is on rule 48's allow-list to build
#     a client and `head_bucket`; it earns that by never minting a key and never
#     naming one in a report. So the storage row is `apps/files`' to declare.
#   * SEARCH — house rule 33. Nothing outside `apps/search/engine.py` may name
#     `MEILI_URL` or `MEILI_MASTER_KEY`, so only that app can answer whether the
#     engine is configured.
#   * THE IDENTITY DOOR — house rule 27. `ZITADEL_PAT` is read in exactly one
#     module, and `zitadel.configured()` needs it.
#   * THE CHANNEL REGISTRY and THE CONNECTIONS PROVIDERS — the layer contract.
#     `core` imports nothing above it, so `registered_channels()` and
#     `registered()` are unreachable from here by construction.
#
# **That is the platform-concern boundary doing its job, not a gap in this
# module.** The platform owns the MECHANISM — the value type, the registry, the
# discovered hook, the four surfaces, the wall, the exit codes — and each app
# owns the FACT of whether its own integration is real. Five `integrations.py`
# modules remain owed for connections and accounts; files, search and
# comms landed already — each a dozen lines against this
# seam — and they land in their own lanes rather than being improvised here,
# since this module has no territory in those apps and no way past their rules.
#
# What is left for the platform itself is the one integration whose whole
# configuration is a `config/settings` value that belongs to no app and whose
# seam (`apps/core/mail.py`) is core's: whether mail leaves this process.


PLATFORM_SOURCE = "apps/core/integrations.py"


#: Backends that never put a message on a wire. The console and locmem backends
#: are the shipped defaults, which is exactly why they need naming: a fresh
#: clone is *supposed* to have them, and a production deployment that still has
#: one is the silent failure this census exists for.
_MAIL_STANDINS = {
    "django.core.mail.backends.console.EmailBackend": "printed to this process's stdout",
    "django.core.mail.backends.locmem.EmailBackend": "kept in memory for tests",
    "django.core.mail.backends.dummy.EmailBackend": "discarded",
    "django.core.mail.backends.filebased.EmailBackend": "written to a local directory",
}


def _outbound_email(registry: IntegrationRegistry) -> None:
    """Does mail leave this process?

    Read off `EMAIL_BACKEND`, which is the whole switch (ADR comms-12) — and
    `declared`, never `live`: the only live probe for an outbound mail transport
    is sending mail, and an instrument that sends a message every time somebody
    asks it a question is an instrument that will be run twice.
    """
    backend = str(settings.EMAIL_BACKEND or "")
    standin = _MAIL_STANDINS.get(backend)
    if standin is None:
        registry.declare(
            Integration(
                key="outbound-email",
                title="Outbound email",
                status=IntegrationStatus.CONFIGURED,
                detail=f"{backend} — mail leaves this process.",
                probe=PROBE_DECLARED,
            ),
            source=PLATFORM_SOURCE,
        )
        return
    registry.declare(
        Integration(
            key="outbound-email",
            title="Outbound email",
            status=IntegrationStatus.FAKE,
            detail=f"{backend} — mail is {standin} and never reaches anybody.",
            remedy=(
                "set EMAIL_BACKEND to an SMTP or Anymail backend and fill the "
                "matching credentials in .env (docs/runbooks/deploy.md)."
            ),
            probe=PROBE_DECLARED,
        ),
        source=PLATFORM_SOURCE,
    )


def _platform_seam(registry: IntegrationRegistry) -> None:
    """The platform's own declarations, in the shape an app's `register` has."""
    _outbound_email(registry)


# --- the census ---------------------------------------------------------------


def declaring_modules() -> list[str]:
    """Every `apps.<x>.integrations` module that exists, in app order.

    **The walk, and the whole of the list there is** — derived from
    `get_app_configs()` and a filename, never typed, which is the criterion this
    instrument stands on. `apps.core.integrations` is skipped by name: this
    module IS the primitive, its own declarations are made by `_platform_seam`,
    and a module that discovered itself would declare them twice.

    Its own function so that a test can point the walk at one package without
    doubling `get_app_configs()` itself — which Django also uses to find
    management commands, and which it caches, so a doubled registry leaks out of
    the test that did it and into the next one that runs a command. Found the
    hard way while writing the census tooth.
    """
    from django.apps import apps as django_apps

    found: list[str] = []
    for config in django_apps.get_app_configs():
        if not config.name.startswith("apps."):
            continue
        module_name = f"{config.name}.{INTEGRATIONS_ATTR}"
        if module_name == __name__:
            continue
        if importlib.util.find_spec(module_name) is None:
            continue
        found.append(module_name)
    return found


def census() -> Census:
    """Every integration any app declares, plus every seam that would not answer.

    Not cached, for `core.lifecycle._third_party_registry`'s reason and one
    more: this reads the world. A cached answer is a claim about a moment that
    has passed, and the standing prober exists precisely because those moments
    stop being true.
    """
    registry = IntegrationRegistry()
    unreadable: list[UnreadableSeam] = []

    try:
        _platform_seam(registry)
    except Exception as failure:  # noqa: BLE001 - a seam that raised is unreadable
        unreadable.append(UnreadableSeam(module=__name__, reason=str(failure)))

    for module_name in declaring_modules():
        try:
            module = importlib.import_module(module_name)
            register = getattr(module, "register", None)
            if register is None:
                continue
            register(registry)
        except Exception as failure:  # noqa: BLE001 - see the module docstring
            unreadable.append(UnreadableSeam(module=module_name, reason=str(failure)))

    return Census(
        integrations=registry.declarations(),
        unreadable=tuple(sorted(unreadable, key=lambda seam: seam.module)),
    )
