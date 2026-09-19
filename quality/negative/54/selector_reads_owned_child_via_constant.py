"""The right form for an owned child: the read asks for the AGGREGATE's kind.

Clause (e) judges a selector against the kind of the row it hands back, and an
owned child's kind is its parent's — reading a line of a ledger IS reading the
ledger. So `canary_ledger.read` is the correct question here and
`canary_ledger_line.read` would be a word for a thing that is not a kind.

This file is the negative that makes the resolution observable rather than
internal. A reader that resolves `authz_kind_of = PARENT_KIND` the way the
runtime does answers `canary_ledger` and this stays silent; a reader that reads
only a string literal answers `canary_ledger_line` and reports the right form as
a selector asking for the wrong kind. That is the direction the mistake actually
falls in — a valve invited onto correct code — which is why it belongs with the
negatives and not with the canaries.
"""

from django.db.models import QuerySet

from apps.core.authz import require

from .models import CanaryLedgerLine


def list_canary_ledger_lines(*, tenant, actor) -> QuerySet[CanaryLedgerLine]:
    """Every line of the ledgers this tenant can read."""
    require(actor, "canary_ledger.read")
    return CanaryLedgerLine.objects.for_tenant(tenant)
