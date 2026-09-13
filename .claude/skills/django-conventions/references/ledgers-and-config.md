# Ledgers and config — append-only, versioned, snapshotted

The long form of `django-conventions` §2, for rows that are witnessed history
and for configuration a process consumes.

### Ledgers and config — append-only, versioned, snapshotted

**A ledger declares itself.** Rows that are witnessed history — audit
entries, witnessed facts, accruals, transition logs — set
`append_only = True` (discovered off the registry by
`apps.core.models.append_only_models`; `core.audit.AuditEntry` is the first
member). House rule 20 covers every declaring model: services `.create()`,
nothing updates or deletes.

```python
# wrong — history edited in place
entry.amount = corrected
entry.save()

# right — the declaration, and a correction as a new row naming what it supersedes
class WidgetEntry(OrgScopedModel):
    append_only = True
```

**Config a process consumes is versioned — create / revise / retire, never
edited in place.** `name` + `version`, unique per `(tenant, name, version)`;
`revise_*` writes a new row at `version + 1`; `retire_*` moves `is_active`
and nothing else; a retired version stays readable because rows that ran
under it point at it. `apps/comms/models.py` (`MessageTemplate`,
`DeliveryPolicy`) and `revise_template` / `retire_policy` in
`apps/comms/services.py` are the worked shape. There is no shared base class
yet — the shape is the doctrine, the base class is deferred with a recorded
trigger.

**References hold immutable keys, not display names.** A config row that a
snapshot, a ledger or another row will reference carries an immutable `key`
slug separate from anything renamable; references store the key (and the
version). A single column may serve both jobs — comms' `name` does — but then
it is immutable by contract, and a renamable label is a separate field.

**A process judges against the snapshot it started under.** A run's input
carries the policy's material content (`apps/comms/types.py`: the run holds
the *steps*, not the policy id) and the run finishes under it — revising a
policy never reaches into a run mid-wait, and a workflow that re-read the
live row would violate rule 9 anyway. Moving in-flight work to current rules
is an explicit, audited service that says so — never a side effect of the
revision.
