"""The names of the things this app says happened.

Names only. `services.py` publishes them with `emit(name=EXPORT_REQUESTED, ...)`
inside the write's transaction, and the grammar is `<app>.<noun>.<past-tense
verb>` (house rule 16) — a past-tense verb always, because an event is a
statement that something *has* happened.

They are constants in one file rather than literals at the call sites for the
reason every app here does it: an event name is a **published contract** a
webhook subscriber matches on, `introspect` reports this file so an integrator
can read the list without reading the source, and a rename that reached a
literal would break every subscription silently.

**Why an export publishes at all.** A tenant-wide archive is one of the two acts
in this product that reach a whole customer at once (erasure is the other), and
"somebody took a copy of everything" is precisely the fact a security team wants
delivered to their own systems rather than discovered in a table. The failure is
published too: an export a customer is waiting on and that died is news, and a
run that only wrote `status=failed` into a row would be news nobody receives.
"""

from __future__ import annotations

EXPORT_REQUESTED = "exports.export.requested"
EXPORT_COMPLETED = "exports.export.completed"

# Said by the activity, hours after the request, when the walk did not finish.
# Same grammar, same file, same contract — and the payload carries the row,
# whose `error` is the activity's own complaint rather than Temporal's wrapper.
EXPORT_FAILED = "exports.export.failed"
