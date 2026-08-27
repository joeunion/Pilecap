"""There is no admin for `UsageEntry`, and the absence is the contract.

A `ModelAdmin` is a door with an edit form and a delete action on it by default,
and this table is the one table in the product where that is not a risk but a
contradiction: every row is a witnessed fact about money spent on somebody's
behalf, and the model **refuses its own `save()` and `delete()`** because of it
(`append_only = True`, `core.models.BaseModel`). A change form here would be a
form whose Save button raises `AppendOnlyViolation` — a door that cannot work,
offered to somebody who does not know that yet.

**The delete is the worse half, and it is worse than exports'.** Deleting a usage
row does not lose a pointer to something; it loses the evidence. An invoice
derived from these rows and a customer disputing it eighteen months later are the
same conversation, and a support engineer who tidied one row away has removed the
only artifact that could settle it.

Support answers the same questions without a form:

* what was recorded — the read door (`GET /api/v1/usage/`) and
  `manage.py introspect`, plus the audit trail `@service` writes for every
  recording;
* the number is wrong — `services.record_correction`, which writes a superseding
  row carrying the corrected full quantity and the reason. Both rows stay
  readable and every total moves to the corrected one; that is the operation, and
  it exists precisely so that "fix it in the admin" never has to;
* make it go away — there is no such operation, on purpose. Retention on this
  table is archival, dated and declared (`UsageEntry.lifecycle`), never a DELETE
  at a call site.

`apps/exports/admin.py` and `apps/example/admin.py` record the same reasoning for
their own models: "no admin" is a statement, not an omission somebody will
helpfully fill in. This file exists to hold that statement, because a missing file
says nothing.
"""

from __future__ import annotations
