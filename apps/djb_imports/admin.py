"""There is no admin for `Import` or `ImportRow`, and the absence is the contract.

Every column on a run is a claim the run made about something it did — the
counts, the status, the rows' outcomes — and every row carries a customer's
imported data. A staff form that could set a status or edit a row's outcome
could mark a file imported that never was, or hide the refusal a row got, with
no run and no audit behind it; a delete action would remove the only record of
what an import wrote. Support answers the same questions through the two doors
a customer uses, `introspect`, the `WorkflowRun` rows and the audit trail every
service here writes. (`apps/exports/admin.py` records the same reasoning.)
"""

from __future__ import annotations
