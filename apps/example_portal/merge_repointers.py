"""How a widget merge carries the requests about the merged widget to the survivor.

`core.verbs.hook("merge_repointers")` finds this file; nothing registers it.
The key is `"widget"` — a request names a widget and nothing else — so this app
answers for widget merges alone. The merge service calls `count` for its dry
run and `repoint` inside its transaction, and `repoint` calls this app's own
service (C3): a merge never writes this app's rows from outside it.
"""

from __future__ import annotations

# golden: portal begin
from typing import Any

from apps.example_portal.selectors import list_portal_requests_about
from apps.example_portal.services import move_portal_requests
from pilecap import Repointer
from pilecap.tenancy import Tenant


def count_requests_about(*, tenant: Tenant, loser: Any) -> int:
    """How many requests a merge of `loser` would carry to the survivor — the dry run's answer."""
    return int(list_portal_requests_about(tenant=tenant, widget=loser).count())


REPOINTERS: dict[str, Repointer] = {
    "widget": Repointer(
        title="Portal requests", count=count_requests_about, repoint=move_portal_requests
    ),
}
# golden: portal end
