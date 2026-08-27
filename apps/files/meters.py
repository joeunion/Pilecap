"""What this app counts. **One meter, and it measures bytes we have MEASURED.**

Names only — `apps/usage/meters.py` discovers this module the way
`apps/events/events.py` discovers an app's event names, validates the grammar at
boot (`<app>.<noun>.<unit>`, first segment the declaring app's label), and
`usage.services.record_usage` refuses any name no installed app declares. So a
typo here is a process that will not start, and a typo at a call site is a
refusal before a row exists.

**Why a constant and never a literal at the call site.** A meter name reaches an
invoice line, a dashboard series and a `(meter, period, quantity)` threshold in a
tenant's settings. `apps/usage/meters.py`'s own docstring makes the argument in
full; what this file adds is the first real customer of it.

**What `files.storage.bytes` means, precisely, so nobody has to guess later:**

* it is recorded **once per finalized version**, inside the same transaction
  that flips `PENDING → STORED` (`services.record_stored`), with the
  `idempotency_key` derived from the version's primary key and this name — so a
  `FinalizeUpload` Temporal retries records one entry, not two;
* the quantity is **what the object store handed back when we streamed the
  object** (`storage.sha256_of`), never what an uploader declared. A meter fed a
  client's own number is a meter a client can set;
* **archive never decrements it** (ADR files-2 § metering): archived bytes are
  still held bytes, and this measures storage rather than visibility;
* **purge, when it lands, records a NEGATIVE entry** per purged version — a new
  witnessed fact with its own `ref`, never a supersede. ADR usage-1's supersede
  corrects a *mistake*, and a purge is not a mistake;
* **nothing consults it to refuse an upload.** Metering counts and never blocks
  (the owner's quota-*counting* ruling); the threshold surface is
  `usage.threshold.crossed` and no write path in this app reads the ledger.

**The unit is bytes and not megabytes** because the ledger stores a `Decimal`
and a rounded unit is a rounding decision taken at record time, in the one place
that cannot be revisited. A dashboard divides; a ledger does not.
"""

from __future__ import annotations

#: Bytes held in the object store for one tenant, accrued one finalized version
#: at a time. Recorded by `apps.files.services.record_stored` with the verified
#: size; see the module docstring for the whole contract.
STORAGE_BYTES = "files.storage.bytes"
