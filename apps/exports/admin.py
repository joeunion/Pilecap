"""There is no admin for `Export`, and the absence is the contract.

A `ModelAdmin` is a door with an edit form and a delete action on it by default,
and every one of this model's columns is a claim the run made about something it
did: the artifact key names an object in a bucket, the manifest says what is in
it, the status says whether it finished. A staff form that could set any of them
is a form that can point a customer's download at somebody else's archive, or
mark a failed export complete, with no run and no audit of the work behind it.

**The delete is the worse half.** Deleting an `Export` row through an admin form
removes the only pointer to the object in storage — and the purge sweeps by
walking rows, so the archive it named becomes a copy of a customer's database
that nothing in the deployment knows about and nothing will ever delete. That is
the precise failure `Export.lifecycle` exists to prevent, reachable through a
form somebody would have added to be helpful.

Support answers the same questions without a form:

* what happened — `manage.py introspect`, the `WorkflowRun` row, and the audit
  trail every service here writes;
* make one — the same door a customer uses, as the customer's own
  administrator;
* make it go away sooner — there is no such operation, on purpose. The
  retention window is the same for every archive and shortening it for one is a
  data-policy decision, not a click.

`apps/example/admin.py` records the same reasoning for `WidgetEntry` and
`WidgetPolicy`: "no admin" is a statement, not an omission somebody will
helpfully fill in. This file exists to hold that statement, because a missing
file says nothing.
"""

from __future__ import annotations
