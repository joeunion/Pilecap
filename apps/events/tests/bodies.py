"""Subject bodies for the spine's own tests. **One helper, one reason.**

`emit` refuses an org-scoped event that names no branch (house rule 59): the
payload's top-level `organization_id` is what `_subject_organization` reads, an
absent key is stamped NULL, and `bridge.group_for` reads NULL as *tenant-wide* —
so a widget announced without its branch would be pushed to every socket in the
tenant while the REST list under a sibling hat never shows it.

Nearly every test in this app uses `example.widget.created` as *some app's
event* — the outbox, the delivery machinery and the replay have no opinion about
widgets — and a widget is an `OrgScopedModel`. So each of those bodies has to
carry a branch, and this is the one place that decides which: **the tenant's
root**, because these tests are not about the hierarchy and a branch chosen per
file would be a fact for a reader to check. The tests that ARE about the
narrowing live in `test_event_organization.py` and name their own organization.
"""

from __future__ import annotations

from typing import Any

from apps.core.models import Tenant
from apps.core.services import root_organization


def in_the_root(tenant: Tenant, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """`payload`, stamped with this tenant's root branch.

    A function rather than a fixture because it is called inside `run_db`
    closures, inside `transaction.atomic()` blocks and at module scope in
    parametrised cases — all places a fixture cannot reach — and because the
    tenant differs per call site in the cross-tenant tests.
    """
    return {"organization_id": str(root_organization(tenant=tenant).pk), **(payload or {})}
