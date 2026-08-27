"""`manage.py zitadel_audit` — does Zitadel still say what our rows say?

    uv run python manage.py zitadel_audit

**The honest half of ADR ident-2.** The enforceable half is house rule 27: no
module outside `apps/accounts/zitadel.py` reaches the management API, so nothing
*in this codebase* can write identity configuration behind the services' back. A
check cannot see Zitadel's console, and somebody with an admin login can change
anything in it. So the console is a declared blind spot, and this is the
tripwire: a read-only report saying where the two disagree.

**It changes nothing, and that is a property rather than a promise.** Every call
it makes is a `GET` or a `_search` (`apps/accounts/zitadel.py`, "reads"), and the
test drives it against an instance a raw API call has deliberately mutated —
standing in for somebody in the console — and asserts both halves: the drift is
reported, and the instance afterwards is byte-identical to the instance before.
Repairing is deliberately not built (shop-the-price): an auto-repairing
reconciler guards drift nobody can cause yet, and its trigger is named in the
ADR — first observed drift, or first production deploy, whichever comes first.

**Two populations, not one.** Every customer `SsoConnection` is compared against
the IdP its row names — and then the **workforce** door is compared against the
environment, because it has no row to name anything with (`_report_workforce`).
Without that section, the one door the people running
this product sign in through was the one thing rule 27's blind spot covered
completely, since the row-by-row walk had nothing to start from.

**What it cannot see**, said out loud rather than left to be discovered: it
compares what our rows *declare*. A class of Zitadel configuration this product
never writes — a login policy nobody set through us, a second organisation, an
IdP created by hand under a name no row claims — is invisible to it, except for
the one summary line counting IdPs Zitadel has that no row names. That is the
declared blind spot on rule 27 and it is repeated here because the person
reading a clean report is the person who most needs to know what "clean" covers.
The workforce section narrows that blind spot by one door and does not close it:
the domain list itself is not in Zitadel to compare against (ADR ident-6), so
what is reconciled there is the door's existence and the Google project it
points at.

Exit status is the report's verdict: **0 when the two agree, 1 when they do
not**, so `zitadel_audit` can be a cron line or a deploy step rather than
something a person has to read. It never exits 2 — this is a tripwire, not a
gate leg.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management.base import CommandError

from apps.accounts import zitadel
from apps.accounts.models import SsoConnection
from apps.core.management import BaseCommand


# What an SSO connection is called inside Zitadel. The same derivation
# `apps/accounts/activities.py` uses, restated here rather than imported,
# because a command importing an activity would drag Temporal into a shell
# process for one f-string. `apps/accounts/tests/test_zitadel.py` pins
# the two against each other, so a change to one fails a test rather than
# silently making the audit compare the wrong names.
def idp_name_for(connection: SsoConnection) -> str:
    return f"{connection.tenant.slug}:{connection.pk}"


# The workforce provider's name, restated here for the same reason
# `idp_name_for` is: a command may not import an activity. It has no row at all
# — its intent is the environment — so this constant is the *only* handle either
# side has on it, which makes the restatement more load-bearing here than there.
# `test_zitadel_workforce_audit.py` pins the two together.
WORKFORCE_IDP_NAME = "Workforce Google"


def workforce_idp_name() -> str:
    return str(getattr(settings, "GOOGLE_WORKFORCE_IDP_NAME", WORKFORCE_IDP_NAME))


def workforce_domains() -> list[str]:
    """The domains this deployment's workforce door is configured for.

    **The switch, not a decoration.** Empty means the door is off entirely —
    `config/settings/base.py` and `services.sync_workforce_identity_config` both
    read it that way — which is what makes "empty here, a live provider there"
    a disagreement worth a line.
    """
    return [
        str(one).strip().lower()
        for one in (getattr(settings, "GOOGLE_WORKSPACE_DOMAINS", []) or [])
        if str(one).strip()
    ]


class Command(BaseCommand):
    help = "Report where Zitadel and our identity-config rows disagree. Changes nothing."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--tenant",
            default="",
            help="Only audit one tenant's connections, by slug.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not zitadel.configured():
            raise CommandError(
                "Zitadel is not configured: ZITADEL_ISSUER and ZITADEL_PAT must both "
                "be set. There is nothing to compare against."
            )

        try:
            drift = self._report(tenant_slug=str(options["tenant"]).strip().lower())
        except zitadel.ZitadelError as error:
            raise CommandError(str(error)) from error

        self.stdout.write("")
        if drift:
            self.stdout.write(self.style.WARNING(f"{drift} disagreement(s). Nothing was changed."))
            # A non-zero exit so this can be a deploy step. `SystemExit` rather
            # than `CommandError`, because the report already said everything
            # and a traceback-shaped error on top of it would read as a crash.
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Zitadel agrees with every row. Nothing changed."))

    def _report(self, *, tenant_slug: str) -> int:
        """Every comparison, printed. Returns how many disagreed."""
        org = zitadel.organization()
        self.stdout.write(f"instance        {org.get('name', '?')} ({org.get('id', '?')})")

        providers = zitadel.identity_providers()
        by_id = {str(row.get("id", "")): row for row in providers}
        self.stdout.write(f"idps in zitadel {len(providers)}")
        self.stdout.write("")

        rows = SsoConnection.objects.select_related("tenant").order_by("tenant__slug", "name")
        if tenant_slug:
            rows = rows.filter(tenant__slug=tenant_slug)

        drift = 0
        claimed: set[str] = set()
        for connection in rows:
            label = f"{connection.tenant.slug}/{connection.name}"
            state = connection.sync_state
            if state == SsoConnection.SyncState.UNMANAGED:
                self.stdout.write(f"unmanaged   {label} — no sync has ever been asked for")
                continue
            if state == SsoConnection.SyncState.PENDING:
                # Not drift: the run may still be in flight. Reported anyway,
                # because a row that has been `pending` since last Tuesday is
                # the most interesting line in this report.
                self.stdout.write(f"pending     {label} — sync started, not yet applied")
                continue
            if not connection.zitadel_idp_id:
                self.stdout.write(f"DRIFT       {label} — {state} but no Zitadel id recorded")
                drift += 1
                continue

            claimed.add(connection.zitadel_idp_id)
            remote = by_id.get(connection.zitadel_idp_id)
            if remote is None:
                remote = zitadel.get_identity_provider(idp_id=connection.zitadel_idp_id)
            if remote is None:
                self.stdout.write(
                    f"DRIFT       {label} — names idp {connection.zitadel_idp_id}, "
                    "which Zitadel does not have"
                )
                drift += 1
                continue

            expected = idp_name_for(connection)
            actual = str(remote.get("name", ""))
            if actual != expected:
                self.stdout.write(
                    f"DRIFT       {label} — idp is named {actual!r}, our row expects {expected!r}"
                )
                drift += 1
                continue

            remote_issuer = zitadel.oidc_issuer_of(remote)
            if remote_issuer and remote_issuer != connection.issuer:
                self.stdout.write(
                    f"DRIFT       {label} — idp issuer is {remote_issuer!r}, our row "
                    f"says {connection.issuer!r}"
                )
                drift += 1
                continue

            self.stdout.write(f"agrees      {label} — idp {connection.zitadel_idp_id}")

        # The workforce door, which has no row to walk and so was invisible to
        # everything above. It goes before the unclaimed count so that the
        # provider it claims is not also reported as a stranger.
        workforce_drift, workforce_id = self._report_workforce(providers)
        drift += workforce_drift
        if workforce_id:
            claimed.add(workforce_id)

        # The one thing the row-by-row walk structurally cannot see: an IdP that
        # exists in Zitadel and that no row of ours claims. Counted rather than
        # called drift, because a deployment may legitimately carry providers
        # this product did not create — and a count is what makes a person go
        # and look.
        unclaimed = [row for row in providers if str(row.get("id", "")) not in claimed]
        if unclaimed:
            self.stdout.write("")
            self.stdout.write(
                f"unclaimed   {len(unclaimed)} idp(s) in Zitadel that no row of ours names: "
                + ", ".join(sorted(str(row.get("name", "?")) for row in unclaimed))
            )
        return drift

    def _report_workforce(self, providers: list[dict[str, Any]]) -> tuple[int, str]:
        """The deployment's own door. Returns (disagreements, the idp id we claimed).

        **Why this section exists.** Every other line in this report starts from
        a row. The workforce provider has none — its intent is the environment
        (`_apply_workforce_provider`: "nothing is written back, and that is the
        honest shape") — so the row-by-row walk could not see it, and the one
        door the people running this product sign in through was the one thing
        rule 27's blind spot covered completely.

        **What is compared.** `GOOGLE_WORKSPACE_DOMAINS` is the switch: empty is
        the door off, non-empty is the door on. Zitadel either holds a Google
        provider under our name or it does not. Both directions of that
        disagreement are drift, and each is its own sentence, because they are
        different incidents: one is staff who cannot sign in, the other is a
        live Google door onto a product that refuses everybody it sends.

        Then the client id, which is the console change our rows structurally
        cannot notice: a provider re-pointed at somebody else's Google project
        still has our name on it and would otherwise read as clean.

        **What is not compared, and why it cannot be.** The domain *list* is not
        in Zitadel at all, deliberately (ADR ident-6, `ensure_google_identity_
        provider`): `GOOGLE_WORKSPACE_DOMAINS` stays ours and is enforced by
        `selectors.is_workforce_email` at the moment an assertion arrives,
        because a restriction expressed only in somebody else's console is a
        restriction we cannot test. So there is no per-domain set to diff — the
        report prints the list beside the provider and says where it is
        enforced, which is the true thing to print rather than a comparison
        against a field that does not exist.
        """
        name = workforce_idp_name()
        domains = workforce_domains()
        provider = next(
            (row for row in providers if str(row.get("name", "")) == name),
            None,
        )
        self.stdout.write("")

        if provider is None:
            if not domains:
                self.stdout.write(
                    f"workforce   off on both sides — GOOGLE_WORKSPACE_DOMAINS is empty "
                    f"and Zitadel holds no provider named {name!r}"
                )
                return 0, ""
            self.stdout.write(
                f"DRIFT       workforce — GOOGLE_WORKSPACE_DOMAINS names "
                f"{', '.join(domains)}, but Zitadel holds no provider named {name!r}. "
                "Staff cannot sign in; run manage.py sync_workforce_idp."
                # This line used to name `zitadel_seed` and
                # `sync_workforce_identity_config`, and NEITHER is a way out of
                # this drift: `zitadel_seed` makes the project, the applications
                # and the dev user and has never touched a provider, and
                # `sync_workforce_identity_config` is the *service* — a name
                # with no command behind it, so an operator who pasted it got
                # "Unknown command". A remedy that does not work is worse than
                # none: it costs the reader the time to try it and then the
                # trust to believe the next one. `sync_workforce_idp` is the
                # command that exists, and it is the door onto that service.
            )
            return 1, ""

        provider_id = str(provider.get("id", ""))
        if not domains:
            self.stdout.write(
                f"DRIFT       workforce — GOOGLE_WORKSPACE_DOMAINS is empty, so this "
                f"deployment refuses every workforce address, but Zitadel still holds "
                f"a live provider named {name!r} (idp {provider_id})"
            )
            return 1, provider_id

        expected_client = str(getattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "") or "").strip()
        actual_client = zitadel.google_client_id_of(provider)
        if expected_client and actual_client and actual_client != expected_client:
            self.stdout.write(
                f"DRIFT       workforce — idp {provider_id} points at Google client "
                f"{actual_client!r}, this deployment is configured for "
                f"{expected_client!r}"
            )
            return 1, provider_id

        self.stdout.write(
            f"agrees      workforce — idp {provider_id}, domains {', '.join(domains)} "
            "(enforced here, not in Zitadel — ADR ident-6)"
        )
        return 0, provider_id
