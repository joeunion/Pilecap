# Models, ledgers and versioned config

The long form of `django-architect` § D.

**D1a — An org-scoped model inherits `OrgScopedModel`, which is
`TenantScopedModel` plus an `organization` FK.** Uniqueness on one still names
`tenant` (a slug is unique per tenant, not per branch) unless the product means
"unique within this branch", which is a decision worth a comment. Services take
the acting organization from **`actor.org`** and never as a parameter — a
service with an `organization=` argument is a door that can write into a branch
it holds no membership over, which is the tenancy hole one level down.
*Enforced:* house rule **24** (the read); review (the write's shape). Form:
conv §2.

**D8 — A ledger declares itself: `append_only = True`; mistakes are
superseded, never edited.** A model whose rows are witnessed history — an
audit entry, a witnessed fact, an accrual, a stage-transition log — declares
`append_only: ClassVar[bool] = True` (`apps.core.models`;
`is_append_only` / `append_only_models` read the population off the registry;
`core.audit.AuditEntry` is the first member). A service may `.create()` a
member's rows; nothing anywhere updates or deletes one. **The correction
convention is a superseding row**: a wrong entry is answered by a new row that
names the row it supersedes (an FK or a recorded id) and states why — the
ledger then holds the mistake *and* the correction, which is what makes it
evidence rather than a table someone tidied. *Why:* the promise used to be a
rule about one model's *name*, and a promise about a name does not survive a
product; discovered off the registry, a product adds a member by declaring it
and the rule covers it in the same commit with no gate edit. A base class was
rejected (ADR core-6): MRO churn to buy a property the attribute already has.
*Enforced:* house rule **20**, generalized over the declaring population;
criterion (introspect shows no update or delete door for a member). Trigger:
first production deploy → DB-grant enforcement (revoke UPDATE/DELETE) as the
belt. *Wrong:* `entry.amount = corrected; entry.save()`. *Right:* a `record_*`
service creating the superseding row.

**D9 — Config a process consumes is versioned: create / revise / retire,
never edited in place.** A template, a policy, a rule set: `name` + `version`,
unique per `(tenant, name, version)`; `revise_*` writes a **new row at
`version + 1`**; `retire_*` moves `is_active` and nothing else; resolution
picks the latest active row; a retired version stays readable because every
row that ran under it points at it. **[main]** `apps/comms/models.py`
(`MessageTemplate`, `DeliveryPolicy`) is the worked shape and
`revise_template` / `retire_policy` in `apps/comms/services.py` the services.
*Why:* config edited in place rewrites history — every row that recorded "sent
under v2" now points at different words — and changes the rules under
processes mid-flight (D11 is that half). A shared versioned-config base class
is **deferred, with its trigger recorded** (the second template-side
consumer); the shape is doctrine now. *Enforced:* review + criterion
("revising yields a new row; rows that ran under the old version still render
it"). *Wrong:* `template.body = new_body; template.save()`. *Right:*
`revise_template(...)` → v+1.

**D10 — Immutable keys under renamable names.** A config row that a snapshot,
a ledger or another row will reference carries an immutable **`key`** slug,
separate from any display name; references — snapshots, event payloads,
foreign records — hold the key (plus the version where D9 applies), and the
display name is free to change without rewriting anybody's history. *Why:*
reference-by-display-name makes every rename either a migration of other
people's data or a silent break of it; reference-by-pk alone loses the
human-legible answer to "what was this sent under" months later. A model may
let one column serve both jobs — comms' `name` does — but then that column is
**immutable by contract** and a renamable label is a separate field added the
day somebody wants renames. *Enforced:* review (the lead names the key column
when placing a referenced config model); criterion ("renaming the config
changes no stored reference and breaks no replay"). *Wrong:* a snapshot
storing `policy="Gold tier escalation"` that a rename orphans. *Right:*
`key="gold-escalation"` immutable, `label` renamable, the snapshot holding
the key.

**D11 — A process judges against the snapshot it started under; moving to
current rules is an explicit service.** When a long-running process starts
under a policy, the policy's material content is **snapshotted into the run's
input** — **[main]** `apps/comms/types.py`: the run carries the *steps*, not
the policy id — and the run finishes under that snapshot; revising the policy
never reaches into a run already waiting (comms proved the semantics over the
wire; this line promotes them to doctrine). A run that *should* pick up the
new rules is moved by a **named, audited service that says so** — never by the
revision silently re-judging in-flight work. *Why:* judging in-flight work
against the live row turns every config edit into an unreviewed bulk action
over everything currently waiting — invisible in the diff, unanswerable in
the audit trail; the snapshot makes "which rules was this decided under" a
recorded fact. It is also what rule 9 already requires: a workflow that
re-read the live row would have history that no longer explains its own
decisions. *Enforced:* house rule **9** (the workflow half); criterion ("a
policy revised mid-wait does not change the waiting run; the mover service
exists and is audited"). *Wrong:* an activity re-reading the policy row at
each step. *Right:* the plan in the run's input, and an explicit `move_*`
service for the deliberate case.
