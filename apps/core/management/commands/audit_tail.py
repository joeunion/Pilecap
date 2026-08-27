"""`manage.py audit_tail` — read the compliance trail from a shell.

    uv run python manage.py audit_tail --platform
    uv run python manage.py audit_tail --tenant acme --limit 100

`AuditEntry.objects.for_platform()` landed with ADR
core-8 and gave the deployment's own actions a population of their own; nothing
could *read* it without opening a Django shell and typing the query, which
means the one population that exists for compliance was the one population with
no door. The admin has always listed a tenant's trail — that is
`AuditEntryAdmin`, and it is read-only for the reason this command is
read-only — but the admin is scoped to the staff member's acting tenant, so the
platform rows are precisely the rows it cannot show (see
`apps/core/tests/test_platform_population.py`).

**Read-only, absolutely.** It writes nothing, it takes no `--delete`, and the
model would refuse one anyway: `AuditEntry` declares `append_only = True` and
`lifecycle` `APPEND_ONLY`, so `BaseModel`'s runtime belt and the model's own
`save`/`delete` both refuse. Reads are not audited, here or anywhere — a trail
that recorded its own readers would grow faster than the thing it records.

**The two populations are asked for with two different words**, exactly as the
manager spells them: `--platform` reads `for_platform()` and `--tenant <slug>`
reads `for_tenant(t)`. There is no "everything" flag. `for_tenant(None)`
returns nothing by design and widening that here would make this command the
one place in the product where tenancy does not hold.

## The read shape is the pinned one, deliberately

Both queries are the dotted paths house rule 35's registry already pins —
`apps.core.audit.AuditEntry.objects.for_tenant` (clause `index_served` +
`index_in_plan: auditentry_tenant_created`) and
`...for_platform` (`no_seq_scan_on` + `index_in_plan:
auditentry_platform_created`). So this command adds **no new read shape**, and
that is a constraint on how it is written rather than a happy accident:

* no `order_by()` of its own — the model's `Meta.ordering` is `-created_at`,
  which is the direction both pinned indexes serve;
* no `select_related()` and no attribute hop across a foreign key — the columns
  printed below are all local, so a page costs one statement whatever `--limit`
  is, and nothing here re-plans the query the probe measured;
* `--limit` is a `LIMIT` on the tail, which is what makes it a tail.

`apps/core/tests/test_audit_tail.py` asserts that pairing (rule 35's clause):
if a future reader needs a column that is not local, the honest move is to
stop and re-pin the plan, not to add a join here and let the gate discover it.
"""

from __future__ import annotations

from typing import Any

from django.core.management.base import CommandError
from django.db.models import QuerySet

from apps.core.audit import AuditEntry
from apps.core.management import BaseCommand
from apps.core.models import Tenant

#: How many rows a bare invocation prints. A tail is a tail: enough to see what
#: just happened, few enough to read. `--limit 0` means "no limit" and is
#: spelled that way rather than as a separate flag.
DEFAULT_LIMIT = 50

#: The columns, in the order they are printed. Every one of them is a LOCAL
#: column of `core_auditentry` — see the module docstring on why that is a
#: constraint and not a preference. `input` is deliberately absent: it is
#: already redacted by `core.service.redact`, but it is per-row JSON and a tail
#: is for scanning, not for reading one row (`--limit 1` plus the admin is how
#: somebody reads one).
COLUMNS = (
    "created_at",
    "action",
    "outcome",
    "door",
    "actor_kind",
    "object_type",
    "object_id",
    "correlation_id",
)


class Command(BaseCommand):
    help = "Print the tail of the audit trail for one tenant, or for the platform."

    def add_arguments(self, parser: Any) -> None:
        population = parser.add_mutually_exclusive_group(required=True)
        population.add_argument(
            "--platform",
            action="store_true",
            help=(
                "The rows no tenant owns — the deployment's own actions "
                "(AuditEntry.objects.for_platform(), ADR core-8)."
            ),
        )
        population.add_argument(
            "--tenant",
            default=None,
            metavar="SLUG",
            help="One tenant's trail, by the slug an X-Tenant header would name.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=DEFAULT_LIMIT,
            help=f"How many rows, newest first. 0 for all. Default {DEFAULT_LIMIT}.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        limit = int(options["limit"])
        if limit < 0:
            raise CommandError("--limit is a count of rows; it cannot be negative.")

        rows: QuerySet[AuditEntry]
        if options["platform"]:
            rows = AuditEntry.objects.for_platform()
            population = "platform"
        else:
            slug = str(options["tenant"]).strip().lower()
            tenant = Tenant.objects.filter(slug=slug).first()
            if tenant is None:
                raise CommandError(
                    f"There is no tenant with the slug {slug!r}.\n"
                    "The slug is the public handle an X-Tenant header names — the one on "
                    "the tenant row, not the tenant's display name."
                )
            rows = AuditEntry.objects.for_tenant(tenant)
            population = f"tenant {tenant.slug}"

        # Sliced AFTER the population is chosen and never re-ordered: the
        # model's own `-created_at` ordering is what both pinned indexes serve.
        page = list(rows[:limit] if limit else rows)

        self.stdout.write(f"{len(page)} audit {'row' if len(page) == 1 else 'rows'} ({population})")
        for entry in page:
            self.stdout.write("\t".join(_cell(entry, column) for column in COLUMNS))


def _cell(entry: AuditEntry, column: str) -> str:
    """One column of one row, as text. Local columns only — see the docstring."""
    value = getattr(entry, column)
    return "" if value is None else str(value)
